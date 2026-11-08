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
- 炸板池通道（pidType=2，zb_ 前缀字段；2026-11-08 增补，同集合同日档）：成员并集 +
  字段随最新帧刷新，无 pool_state 标注——炸板池成员即当日曾炸板全集（回封后掉出
  仍留档，回封语义由涨停池通道 sealed 承载，两通道互为印证）。
- 跌停池通道（pidType=3，dt_ 前缀字段；2026-11-08 增补，同集合同日档）：与涨停池
  同款收盘态标注——sealed=收盘仍跌停 / broken=曾入池后掉出即打开跌停未回封
  （字段保留其最后封住时快照 + last_seen_ts；回封跌停自动恢复 sealed）；
  页缺口帧跳过掉出标注防误标。
- 涨停原因语料通道（2203 推送，reason_ 前缀字段；2026-11-08 用户需求「作为 jev 语料
  投喂」）：按 stock_id 并集落库 reason_items（zt/fx/jc/jj/pledge/zt_group/theme/
  child_theme/label/plate/tp/rank 等原文，不改写不拼接——组合口径由消费方定）；
  日期跟随涨停池快照交易日（周末/盘前推送的是上一交易日详情），推送 ts 早于该日
  的跨日残留条目跳过不写（不污染当日档）。

各通道在同一次写里各改各的前缀字段（单写者顺序执行，无并发冲突），日档互不覆盖。
供 GET /api/kpl/daban-pool（涨停池）、GET /api/kpl/daban-bidding（集合竞价）、
GET /api/kpl/daban-zhaban（炸板池）、GET /api/kpl/daban-dt（跌停池）、
GET /api/kpl/daban-reasons（涨停原因语料）历史回放
读口消费（前端逐日回退找最近有档交易日，板块行情成分股 kplShiftDate 同款）。

纪律：storage_backend != mongodb 时禁用（不写其它后端）；pytest 经
get_runtime_mongodb_database 护栏自动落 dragon_board_test；拉取失败/空帧不写、
不覆盖既有存档（fail-visible，结构化记 status）。
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from backend.core.settings import get_settings
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

_COLLECTION = "kpl_daban_pool"
_UPSTREAM_POOL = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=1"
_UPSTREAM_BID = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=8"
_UPSTREAM_ZB = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=2"
_UPSTREAM_DT = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=3"
_UPSTREAM_REASONS = "http://127.0.0.1:8002/api/kpl/zt-reasons"   # 2203 涨停原因语料

# 通道配置：prefix=日档字段前缀；mark_broken=掉出标注（涨停池/跌停池有掉出语义，
# 炸板池成员即曾炸板全集、竞价无掉出语义，均不标）
_LANES: dict[str, dict[str, Any]] = {
    "pool": {"prefix": "", "mark_broken": True},
    "bid": {"prefix": "bid_", "mark_broken": False},
    "zb": {"prefix": "zb_", "mark_broken": False},
    "dt": {"prefix": "dt_", "mark_broken": True},
}
# 读口降级 note 用的通道中文名（load_day 通用映射用）
_LANE_LABELS: dict[str, str] = {"pool": "涨停池", "bid": "集合竞价",
                               "zb": "炸板池", "dt": "跌停池"}


def archive_lane_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    *,
    lane: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """把一份 2103 合并快照合并进 kpl_daban_pool 日档的指定通道（成员并集）。

    口径（2026-11-07 用户评审提出炸板缺陷后固化）：涨停池/跌停池=当前封住口径，盘中封住、
    尾盘炸板（打开跌停）未回封的股只出现在盘中帧——若按「最新一帧覆盖写」日档会丢失。故改为：
    - 入池过即留档（按 stock_id 成员并集，字段随最新帧刷新）；
    - 掉出语义通道（涨停池/跌停池，mark_broken=True）：本帧在池 → pool_state='sealed'；
      曾入池、本帧掉出 → 'broken'（涨停池=炸板未回封 / 跌停池=打开跌停未回封，字段保留
      其最后封住时快照 + last_seen_ts）；回封自动恢复 'sealed'；防误标：本帧页缺口
      （pages_missing 非空）时跳过掉出标注。
    - 无掉出语义通道（集合竞价/炸板池，mark_broken=False）：只做并集 + 字段刷新
      （竞价五件套 9:25 后冻结，成员为当日曾入列全集；炸板池回封语义由涨停池通道
      sealed 承载，两通道互为印证）。
    日档读写以「读全文 → 只改本通道前缀字段 → 字段级 $set 回写」进行（与涨停基因语料
    通道 kpl_gene_corpus 同款并发合同），各通道/各写方互不覆盖。
    纯函数（db 注入，pytest 用假库）；空帧/缺日期不写（结构化返回，不伪装成功）。
    """
    cfg = _LANES[lane]
    p = cfg["prefix"]
    date = str(snapshot.get("date") or "")
    items = snapshot.get("items") or []
    if not date:
        return {"ok": False, "reason": "empty_snapshot", "lane": lane,
                "date": None, "item_n": 0}
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
    if not items:
        # 空帧（评审 P2-1）：不覆盖已有成员（fail-visible：不因一帧空把日档清空）；
        # 但源可用且池本为空（如 0 家跌停的强市日）是真实事实，首个写入记空档 + empty 标记，
        # 供读口区分「采集成功且 0 家」与「未采集」（后者才走 no_archive / 前端逐日回退）。
        if members:
            return {"ok": True, "lane": lane, "date": date, "item_n": len(members),
                    "empty": False, "note": "empty_snapshot_ignored"}
        if not snapshot.get("pages"):   # 连页都没收到：源不可用，不写、不伪装
            return {"ok": False, "reason": "empty_snapshot", "lane": lane,
                    "date": date, "item_n": 0}
        empty_doc = {
            p + "date": date, p + "ts": ts, p + "pid_type": snapshot.get("pid_type"),
            p + "items": [], p + "empty": True,
            p + "max_size": snapshot.get("max_size"), p + "pages": snapshot.get("pages"),
            p + "pages_expected": snapshot.get("pages_expected"),
            p + "pages_missing": pages_missing, p + "pages_meta": snapshot.get("pages_meta"),
            p + "raw_len": snapshot.get("raw_len"),
            p + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
        }
        # 字段级 $set（与 kpl_gene_corpus 同款）：只写本通道前缀字段，upsert 由过滤器
        # 等值条件带上 _id；避免整 doc 回写把 gene 语料等并行写方的字段回写冲掉（评审 R2-P1）
        db[_COLLECTION].update_one({"_id": date}, {"$set": empty_doc}, upsert=True)
        return {"ok": True, "lane": lane, "date": date, "item_n": 0, "empty": True}
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
        p + "empty": False,
        p + "max_size": snapshot.get("max_size"),
        p + "pages": snapshot.get("pages"),
        p + "pages_expected": snapshot.get("pages_expected"),
        p + "pages_missing": pages_missing,
        p + "pages_meta": snapshot.get("pages_meta"),   # 页级 order_type/sort_type/index/count/indexes
        p + "raw_len": snapshot.get("raw_len"),
        p + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    result: dict[str, Any] = {"ok": True, "lane": lane, "date": date,
                              "item_n": len(members), "broken_marked": broken_marked}
    if cfg["mark_broken"]:
        # sealed_n/broken_n 仅掉出语义通道有意义（竞价/炸板池成员无 pool_state，
        # 写 doc 与 status 载荷都不带，避免恒 0 语义噪声，评审 P2-4）
        lane_doc[p + "sealed_n"] = sealed_n
        lane_doc[p + "broken_n"] = broken_n
        result["sealed_n"] = sealed_n
        result["broken_n"] = broken_n
    db[_COLLECTION].update_one({"_id": date}, {"$set": lane_doc}, upsert=True)
    return result


def archive_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """涨停池通道（pidType=1，无前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="pool", now=now)


def archive_bid_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """集合竞价通道（pidType=8，bid_ 前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="bid", now=now)


def archive_zb_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """炸板池通道（pidType=2，zb_ 前缀字段；2026-11-08 增补）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="zb", now=now)


def archive_dt_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """跌停池通道（pidType=3，dt_ 前缀字段；2026-11-08 增补）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="dt", now=now)


def load_day(db: Any, date: str, *, lane: str = "pool") -> dict[str, Any]:
    """按日读存档；无档/该通道无数据返回结构化降级（fail-visible，不回退默认集合冒充）。

    lane=pool：返回整日档（涨停池字段无前缀 + 竞价/炸板/跌停前缀字段 + reason_items 同 doc 可见）；
    lane=bid/zb/dt：映射为与 /daban-list 同构的载荷（items/ts/max_size/…），前端零转换渲染；
    lane=reason：2203 涨停原因语料（jev 投喂原料，见 load_reason_corpus）。
    """
    if lane == "reason":
        return load_reason_corpus(db, date)
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date, "lane": lane}
    row.pop("_id", None)
    if lane not in _LANES:
        return {"ok": False, "degraded": True, "reason": "invalid_lane", "date": date, "lane": lane}
    p = _LANES[lane]["prefix"]
    if not row.get(p + "items"):
        # 「采集成功且池为空」（如 0 家跌停）与「未采集」严格分开（评审 P2-1）：
        # 前者 ok:true + empty:true + items:[]（不触发前端逐日回退，不伪装成降级），
        # 后者才 no_archive（前端逐日回退找最近有档交易日）。
        if row.get(p + "empty"):
            return {"ok": True, "source": "local_archive", "lane": lane, "empty": True,
                    "date": row.get(p + "date") or date, "ts": row.get(p + "ts"),
                    "pid_type": row.get(p + "pid_type"), "items": [],
                    "max_size": row.get(p + "max_size"), "pages": row.get(p + "pages"),
                    "pages_expected": row.get(p + "pages_expected"),
                    "pages_missing": row.get(p + "pages_missing"),
                    "pages_meta": row.get(p + "pages_meta"), "raw_len": row.get(p + "raw_len"),
                    "archived_at": row.get(p + "archived_at"),
                    "note": f"该日{_LANE_LABELS.get(lane, lane)}采集成功且池为空（0 家）"}
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date,
                "lane": lane,
                "note": f"日档存在但{_LANE_LABELS.get(lane, lane)}通道无数据（旧档或该页签采集未运行）"}
    if lane == "pool":
        # 涨停池读口=整日档（无前缀字段 + 其它通道前缀字段同 doc 可见，既有合同）
        return {"ok": True, "source": "local_archive", "lane": lane, "empty": False, **row}
    return {
        "ok": True, "source": "local_archive", "lane": lane, "empty": False,
        "date": row.get(p + "date"), "ts": row.get(p + "ts"),
        "pid_type": row.get(p + "pid_type"), "items": row.get(p + "items"),
        "max_size": row.get(p + "max_size"), "pages": row.get(p + "pages"),
        "pages_expected": row.get(p + "pages_expected"),
        "pages_missing": row.get(p + "pages_missing"),
        "pages_meta": row.get(p + "pages_meta"), "raw_len": row.get(p + "raw_len"),
        "archived_at": row.get(p + "archived_at"),
    }


# 2203 涨停原因语料保留字段（原文透传，不改写不拼接）：涨停原因/风险/减持/解禁/质押/
# 梯队/主题/子主题/标签/关联板块/排名/Top/消息 id。组合口径（如 zt+plate）由消费方决定，
# 落库只保证原料在且可追溯。
_REASON_FIELDS = ("zt", "fx", "jc", "jj", "pledge", "zt_group", "theme", "dd",
                  "child_theme", "label", "zt_tag", "rank", "rank_total", "rank_top",
                  "plate", "tp", "msg_id")
_REASON_LANE = "reason"


def _ts_date(ts: Any) -> str:
    """推送 ts（unix 秒）→ 北京时间日期串；非法 ts 返空串（不猜）。"""
    try:
        return datetime.fromtimestamp(float(ts), TZ_SHANGHAI).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _reason_incoming(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """2203 快照 → {stock_id: item}（兼容 collector 读口 reasons dict 与 items list）。"""
    raw = snapshot.get("reasons")
    if raw is None:
        raw = snapshot.get("items")   # 兼容 items list 形态（2203 快照两种载荷）
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for sid, item in raw.items():
            if isinstance(item, dict) and str(sid or "").strip():
                out[str(sid).strip()] = dict(item)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                sid = str(item.get("stock_id") or "").strip()
                if sid:
                    out[sid] = dict(item)
    return out


def archive_reason_corpus(db: Any, snapshot: dict[str, Any], *,
                          now: Optional[datetime] = None) -> dict[str, Any]:
    """2203 涨停原因详情语料落库（2026-11-08 用户需求：作为 jev 语料投喂）。

    写入 kpl_daban_pool 同日档的 reason_ 前缀字段（不另建数据集，与打板通道同步）：
    - reason_items：按 stock_id 并集，字段随最新帧刷新（留 first_ts 首次到流时间）；
    - reason_date/reason_ts/reason_count/reason_archived_at/reason_source；
    - 日期 = 调用方注入的交易日（archiver 取涨停池快照 date：周末/盘前推送的是上一
      交易日详情）；无 date → 不写（不猜）；
    - 跨日残留保护：条目 ts 转北京时间早于该日 → 跳过（skipped_stale），不污染当日档。
    纯函数（db 注入）；空快照/全陈旧不写既有语料（fail-visible 结构化返回）。
    """
    date = str(snapshot.get("date") or "")
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _REASON_LANE,
                "date": None, "item_n": 0}
    incoming = _reason_incoming(snapshot)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get("reason_items") or []:
        sid = str(m.get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    if not incoming:
        return {"ok": False, "reason": "empty_reasons", "lane": _REASON_LANE,
                "date": date, "item_n": len(members)}
    merged_n = skipped_stale = 0
    for sid, it in incoming.items():
        ts = it.get("ts")
        ts_date = _ts_date(ts)
        if ts_date and ts_date < date:
            skipped_stale += 1
            continue
        merged = dict(members.get(sid) or {})
        for f in _REASON_FIELDS:
            if f in it and it[f] not in (None, "", []):
                merged[f] = it[f]
        merged["stock_id"] = sid
        if ts:
            merged["ts"] = ts
            merged["ts_date"] = ts_date or merged.get("ts_date")
            merged.setdefault("first_ts", ts)   # 仅有效 ts 落首次到流（None 占位会堵死回填）
        members[sid] = merged
        merged_n += 1
    if not merged_n:
        return {"ok": False, "reason": "all_stale", "lane": _REASON_LANE, "date": date,
                "item_n": len(members), "skipped_stale": skipped_stale}
    doc = {
        "reason_date": date,
        "reason_source": "socket_2203",
        "reason_items": list(members.values()),
        "reason_count": len(members),
        "reason_ts": max((m.get("ts") or 0) for m in members.values()),
        "reason_archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)   # 字段级 $set，同上
    return {"ok": True, "lane": _REASON_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "skipped_stale": skipped_stale}


def load_reason_corpus(db: Any, date: str) -> dict[str, Any]:
    """2203 涨停原因语料读口（jev 投喂原料）：{ok, date, items, count, ts, archived_at}。

    fail-visible：「日档不存在」（no_archive）与「日档在但语料未落库」（no_reason_corpus，
    该日 collector 未开 2203 订阅或盘中未运行）严格分开，不伪装空语料。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _REASON_LANE}
    items = row.get("reason_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_reason_corpus",
                "date": date, "lane": _REASON_LANE, "item_n": 0,
                "note": "日档存在但 2203 涨停原因语料未落库（需当日盘中运行 collector 且 KPL_ZT_REASON_SUBS≠0）"}
    return {"ok": True, "source": "local_archive", "lane": _REASON_LANE,
            "date": row.get("reason_date") or date, "items": items,
            "count": len(items), "ts": row.get("reason_ts"),
            "archived_at": row.get("reason_archived_at"),
            "corpus_source": row.get("reason_source") or "socket_2203"}


class DabanPoolArchiver:
    """周期拉取 :8002 涨停池/集合竞价/炸板池/跌停池快照 + 2203 涨停原因语料，按日存档
    （main.py startup 启动，mongodb 模式专用；2026-11-08 增补炸板/跌停通道与
    reason_items 语料，同一 kpl_daban_pool 日档各改各前缀/字段）。

    单任务循环内顺序处理四打板通道，再拉一次 2203 语料：任一通道失败不阻断其它通道
    （各自结构化记 lastResult）。
    """

    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        database_factory: Callable[[], Any] = get_runtime_mongodb_database,
        settings: Any | None = None,
        upstream_url: str = _UPSTREAM_POOL,
        bid_upstream_url: str = _UPSTREAM_BID,
        zb_upstream_url: str = _UPSTREAM_ZB,
        dt_upstream_url: str = _UPSTREAM_DT,
        reason_upstream_url: str = _UPSTREAM_REASONS,
    ) -> None:
        current = settings or get_settings()
        self.enabled = current.storage_backend == "mongodb"
        self.interval_seconds = max(30, int(interval_seconds))
        self._database_factory = database_factory
        self._upstream_url = upstream_url
        self._bid_upstream_url = bid_upstream_url
        self._zb_upstream_url = zb_upstream_url
        self._dt_upstream_url = dt_upstream_url
        self._reason_upstream_url = reason_upstream_url
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
        # 单写者约束：同通道写方仅本服务单实例；跨写方（gene 语料通道）为字段级 $set 互不覆盖；
        # 四通道 fetch/archive 均逐通道 try/except，任一通道失败不阻断其它通道（含 fetch 阶段）。
        self._last_run_at = datetime.now(TZ_SHANGHAI).isoformat()
        results: dict[str, Any] = {}
        # 渐进发布：本轮开始即挂上空 dict，逐通道写入，避免异常时出现
        # 「lastRunAt 新、lastResult 还是上一轮」的半失真态（评审 P1-1）
        self._last_result = results
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            pool_date: str | None = None
            for key, url, fn in (
                ("pool", self._upstream_url, archive_snapshot),
                ("bid", self._bid_upstream_url, archive_bid_snapshot),
                ("zb", self._zb_upstream_url, archive_zb_snapshot),
                ("dt", self._dt_upstream_url, archive_dt_snapshot),
            ):
                try:
                    payload = await self._fetch(client, url)
                except Exception as error:   # fetch 阶段失败同样不连带其它通道（评审 M1）
                    results[key] = {"ok": False, "reason": f"fetch_failed:{error}"}
                    continue
                if not payload.get("ok"):
                    # collector 未运行/快照降级：该通道不写、不覆盖既有存档，结构化透出
                    results[key] = {"ok": False,
                                    "reason": f"collector_degraded:{payload.get('reason') or 'unknown'}"}
                    continue
                if key == "pool":
                    pool_date = str(payload.get("date") or "") or None
                try:
                    # 落库阶段同样逐通道隔离（评审 P1-1）：Mongo/库工厂/脏 payload 异常
                    # 只算本通道失败，不连带后续通道全部不落库
                    results[key] = await asyncio.to_thread(fn, self._database_factory(), payload)
                except Exception as error:
                    results[key] = {"ok": False, "reason": f"archive_failed:{error}"}
            # 2203 涨停原因语料（2026-11-08，jev 投喂原料）：日期跟随涨停池快照交易日
            # （周末/盘前推送的是上一交易日详情）；无交易日时不写（不猜、不错挂日期）。
            try:
                rsn = await self._fetch(client, self._reason_upstream_url)
            except Exception as error:
                results["reason"] = {"ok": False, "reason": f"fetch_failed:{error}"}
            else:
                if not rsn.get("ok"):
                    results["reason"] = {"ok": False,
                                         "reason": f"collector_degraded:{rsn.get('reason') or 'unknown'}"}
                elif not pool_date:
                    results["reason"] = {"ok": False, "reason": "no_pool_date"}
                elif pool_date < (datetime.now(TZ_SHANGHAI) - timedelta(days=3)).date().isoformat():
                    # 新鲜度护栏（评审 R2-P2）：涨停池快照日期过旧（>3 天）说明 2103 已停推而
                    # 缓存滞留，2203 若仍在流会把当日详情挂进旧交易日档 —— 结构化 skip 不落库
                    results["reason"] = {"ok": False, "reason": "stale_pool_date", "date": pool_date}
                else:
                    try:
                        results["reason"] = await asyncio.to_thread(
                            archive_reason_corpus, self._database_factory(),
                            {**rsn, "date": pool_date})
                    except Exception as error:
                        results["reason"] = {"ok": False, "reason": f"archive_failed:{error}"}
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
