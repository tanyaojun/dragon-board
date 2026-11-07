# -*- coding: utf-8 -*-
"""2103 打板页签按日快照存档（2026-11-07 涨停行情/集合竞价历史回放数据源）。

背景（2026-11-07 实测固化）：上游 HisDaBanList 历史端点为严格白名单参数
（仅 Day+全局五件套+凭据），不认页签参数，返回默认集合（实证 2026-11-06 为
9 只 5~6.5% 涨幅非涨停股，连板/涨停时间/封单全空）——打板页签历史帧无上游读口。
本服务在 :8000 主链周期拉取本机 :8002 collector 合并快照（2103，与实时读口
/daban-list 同构），按日合并进 MongoDB `kpl_daban_pool`（_id=交易日）：

- 涨停池通道（pidType=1，无前缀字段）：成员并集 + 收盘态标注——sealed=收盘仍封住 /
  broken=曾入池后掉出即炸板未回封（字段保留其最后封住时快照 + last_seen_ts）；
  回封自动恢复 sealed；页缺口帧跳过掉出标注防误标。
- 集合竞价通道（pidType=8，bid_ 前缀字段；2026-11-08 用户裁决：与涨停池同集合同日档，
  不另建数据集）：成员并集 + 字段随最新帧刷新（无炸板语义，不标 pool_state）。

两通道在同一次写里各改各的前缀字段（单写者顺序执行，无并发冲突），日档互不覆盖。
供 GET /api/kpl/daban-pool（涨停池）与 GET /api/kpl/daban-bidding（集合竞价）
历史回放读口消费（前端逐日回退找最近有档交易日，板块行情成分股 kplShiftDate 同款）。

纪律：storage_backend != mongodb 时禁用（不写其它后端）；pytest 经
get_runtime_mongodb_database 护栏自动落 dragon_board_test；拉取失败/空帧不写、
不覆盖既有存档（fail-visible，结构化记 status）。
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from backend.core.settings import get_settings
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

_COLLECTION = "kpl_daban_pool"
_UPSTREAM_POOL = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=1"
_UPSTREAM_BID = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=8"

# 通道配置：prefix=日档字段前缀；mark_broken=掉出标注（仅涨停池有炸板语义）
_LANES: dict[str, dict[str, Any]] = {
    "pool": {"prefix": "", "mark_broken": True},
    "bid": {"prefix": "bid_", "mark_broken": False},
}


def archive_lane_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    *,
    lane: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """把一份 2103 合并快照合并进 kpl_daban_pool 日档的指定通道（成员并集）。

    口径（2026-11-07 用户评审提出炸板缺陷后固化）：涨停池=当前封住口径，盘中封住、
    尾盘炸板未回封的股只出现在盘中帧——若按「最新一帧覆盖写」日档会丢失。故改为：
    - 入池过即留档（按 stock_id 成员并集，字段随最新帧刷新）；
    - 涨停池通道：本帧在池 → pool_state='sealed'；曾入池、本帧掉出 → 'broken'
      （炸板未回封，字段保留其最后封住时快照 + last_seen_ts）；回封自动恢复 'sealed'；
      防误标：本帧页缺口（pages_missing 非空）时跳过掉出标注。
    - 集合竞价通道：只做并集 + 字段刷新（竞价五件套 9:25 后冻结，成员为当日曾入列全集）。
    日档读写以「读全文 → 只改本通道前缀字段 → 整 doc 回写」进行，两通道互不覆盖。
    纯函数（db 注入，pytest 用假库）；空帧/缺日期不写（结构化返回，不伪装成功）。
    """
    cfg = _LANES[lane]
    p = cfg["prefix"]
    date = str(snapshot.get("date") or "")
    items = snapshot.get("items") or []
    if not date or not items:
        return {"ok": False, "reason": "empty_snapshot", "lane": lane,
                "date": date or None, "item_n": len(items)}
    ts = snapshot.get("ts")
    pages_missing = snapshot.get("pages_missing") or []
    incoming: dict[str, dict[str, Any]] = {}
    for it in items:
        sid = str(it.get("stock_id") or "")
        if sid:
            incoming[sid] = it
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get(p + "items") or []:
        sid = str(m.get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    for sid, it in incoming.items():
        merged = dict(members.get(sid) or {})
        merged.update(it)
        merged["stock_id"] = sid
        merged["last_seen_ts"] = ts
        if cfg["mark_broken"]:
            merged["pool_state"] = "sealed"
        members[sid] = merged
    broken_marked = 0
    if cfg["mark_broken"] and not pages_missing:
        for sid, m in members.items():
            if sid not in incoming and m.get("pool_state") == "sealed":
                m["pool_state"] = "broken"
                broken_marked += 1
    sealed_n = sum(1 for m in members.values() if m.get("pool_state") == "sealed")
    broken_n = sum(1 for m in members.values() if m.get("pool_state") == "broken")
    lane_doc = {
        p + "date": date,
        p + "ts": ts,
        p + "pid_type": snapshot.get("pid_type"),
        p + "items": list(members.values()),   # 全量：具名字段 + quotas×28 原始数组（含未破译位）
        p + "max_size": snapshot.get("max_size"),
        p + "pages": snapshot.get("pages"),
        p + "pages_expected": snapshot.get("pages_expected"),
        p + "pages_missing": pages_missing,
        p + "pages_meta": snapshot.get("pages_meta"),   # 页级 order_type/sort_type/index/count/indexes
        p + "raw_len": snapshot.get("raw_len"),
        p + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    if cfg["mark_broken"]:
        # sealed_n/broken_n 仅涨停池通道有意义（竞价成员无 pool_state，写入恒 0 纯噪声，评审 m2）
        lane_doc[p + "sealed_n"] = sealed_n
        lane_doc[p + "broken_n"] = broken_n
    db[_COLLECTION].replace_one({"_id": date}, {"_id": date, **row, **lane_doc}, upsert=True)
    return {"ok": True, "lane": lane, "date": date, "item_n": len(members),
            "sealed_n": sealed_n, "broken_n": broken_n, "broken_marked": broken_marked}


def archive_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """涨停池通道（pidType=1，无前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="pool", now=now)


def archive_bid_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """集合竞价通道（pidType=8，bid_ 前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="bid", now=now)


def load_day(db: Any, date: str, *, lane: str = "pool") -> dict[str, Any]:
    """按日读存档；无档/该通道无数据返回结构化降级（fail-visible，不回退默认集合冒充）。

    lane=pool：返回整日档（涨停池字段无前缀 + 竞价 bid_ 前缀字段同 doc 可见）；
    lane=bid：映射为与 /daban-list 同构的载荷（items/ts/max_size/…），前端零转换渲染。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date, "lane": lane}
    row.pop("_id", None)
    if lane == "pool":
        if not row.get("items"):
            # 与 bid 通道对称：日档存在（如仅竞价通道写档）但涨停池通道无数据时结构化降级，
            # 不伪装 ok:true+items:[]（评审 m1；前端逐日回退遇 no_archive 才继续回退）
            return {"ok": False, "degraded": True, "reason": "no_archive", "date": date,
                    "lane": lane, "note": "日档存在但涨停池通道无数据（旧档或涨停池采集未运行）"}
        return {"ok": True, "source": "local_archive", "lane": lane, **row}
    p = _LANES["bid"]["prefix"]
    if not row.get(p + "items"):
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date,
                "lane": lane, "note": "日档存在但集合竞价通道无数据（旧档或竞价采集未运行）"}
    return {
        "ok": True, "source": "local_archive", "lane": lane,
        "date": row.get(p + "date"), "ts": row.get(p + "ts"),
        "pid_type": row.get(p + "pid_type"), "items": row.get(p + "items"),
        "max_size": row.get(p + "max_size"), "pages": row.get(p + "pages"),
        "pages_expected": row.get(p + "pages_expected"),
        "pages_missing": row.get(p + "pages_missing"),
        "pages_meta": row.get(p + "pages_meta"), "raw_len": row.get(p + "raw_len"),
        "archived_at": row.get(p + "archived_at"),
    }


class DabanPoolArchiver:
    """周期拉取 :8002 涨停池+集合竞价快照并按日存档（main.py startup 启动，mongodb 模式专用）。

    单任务循环内顺序处理两通道：涨停池失败不阻断竞价通道（各自结构化记 lastResult）。
    """

    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        database_factory: Callable[[], Any] = get_runtime_mongodb_database,
        settings: Any | None = None,
        upstream_url: str = _UPSTREAM_POOL,
        bid_upstream_url: str = _UPSTREAM_BID,
    ) -> None:
        current = settings or get_settings()
        self.enabled = current.storage_backend == "mongodb"
        self.interval_seconds = max(30, int(interval_seconds))
        self._database_factory = database_factory
        self._upstream_url = upstream_url
        self._bid_upstream_url = bid_upstream_url
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "intervalSeconds": self.interval_seconds,
            "lastRunAt": self._last_run_at,
            "lastResult": self._last_result,
            "lastError": self._last_error,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._archive_once()
            except asyncio.CancelledError:
                return
            except Exception as error:   # 单轮失败不退循环（fail-visible 进 status）
                self._last_error = str(error)
            await asyncio.sleep(self.interval_seconds)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        resp = await client.get(url)
        return resp.json()

    async def _archive_once(self) -> None:
        # 单写者约束：整 doc 读改写仅在单进程单 archiver 内一致（本服务单实例部署）；
        # 双通道 fetch/archive 均逐通道 try/except，任一通道失败不阻断另一通道（含 fetch 阶段）。
        self._last_run_at = datetime.now(TZ_SHANGHAI).isoformat()
        results: dict[str, Any] = {}
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            for key, url, fn in (
                ("pool", self._upstream_url, archive_snapshot),
                ("bid", self._bid_upstream_url, archive_bid_snapshot),
            ):
                try:
                    payload = await self._fetch(client, url)
                except Exception as error:   # fetch 阶段失败同样不连带另一通道（评审 M1）
                    results[key] = {"ok": False, "reason": f"fetch_failed:{error}"}
                    continue
                if not payload.get("ok"):
                    # collector 未运行/快照降级：该通道不写、不覆盖既有存档，结构化透出
                    results[key] = {"ok": False,
                                    "reason": f"collector_degraded:{payload.get('reason') or 'unknown'}"}
                    continue
                results[key] = await asyncio.to_thread(fn, self._database_factory(), payload)
        self._last_result = results
        self._last_error = None if all(r.get("ok") for r in results.values()) \
            else ";".join(f"{k}:{r.get('reason')}" for k, r in results.items() if not r.get("ok"))


_daban_pool_archiver: Optional[DabanPoolArchiver] = None


def get_daban_pool_archiver() -> DabanPoolArchiver:
    global _daban_pool_archiver
    if _daban_pool_archiver is None:
        _daban_pool_archiver = DabanPoolArchiver()
    return _daban_pool_archiver


async def close_daban_pool_archiver() -> None:
    global _daban_pool_archiver
    if _daban_pool_archiver is not None:
        await _daban_pool_archiver.stop()
        _daban_pool_archiver = None
