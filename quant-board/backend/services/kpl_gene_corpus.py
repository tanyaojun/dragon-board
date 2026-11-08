# -*- coding: utf-8 -*-
"""涨停基因（溢价基因）语料通道 + 独立增量存档器（2026-11-08 用户需求：
题材龙头语料投喂 jev 模型；前端页面暂不上）。

为什么独立于 DabanPoolArchiver（2026-11-08 决策）：
- 打板通道（2103 socket 合并快照）由 DabanPoolArchiver 按 60s 整轮拉取、整 doc 读改写；
  涨停基因是 **HTTP 单股粒度**（apphq StockL2Data/GetZhangTingGene，服务端 _post_form
  全局 ≥2s 单发间隔），只能逐股懒取、天然分期补齐——节奏与约束都不同；
- 独立模块 + 独立循环，且写库用 **字段级 $set（只动 gene_ 前缀字段）**，不与打板通道的
  整 doc replace 互相踩写（两者同进程同事件循环、各自 to_thread 落库，整 doc 读改写会
  丢更新）。日档同一集合 kpl_daban_pool（用户裁决：不另建数据集）。

落库（gene_ 前缀字段，与 reason_ 同款）：
- gene_items：按 stock_id 并集 [{stock_id, gene{zt_count, premium5_count, next_day_red_pct,
  first_seal_pct, first_broken_pct, lianban_pct}, gene_labels, raw 六元数组原样, raw_len,
  window_note, partial?, missing_fields?, fetched_at, source}]
- gene_date / gene_source / gene_count / gene_pending_n（涨停池成员中尚无基因的只数）
  / gene_failures（失败条目，fail-visible）/ gene_archived_at

拉取策略（控发数）：每轮只拉 limit 只（默认 6，服务端 ≥2s 间隔天然限速）；缺失优先，
收盘后（≥15:05）对盘中拉到的旧值各刷新一次终值；全部失败且无既有语料 → ok False。

pytest 纪律：pytest 进程内 `kpl_stock_gene` 侧有硬护栏（红线 7），测试全部注入 fetcher 桩。
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from backend.core.settings import get_settings
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.kpl_daban_archiver import _COLLECTION   # 同一数据集（单一事实源）
from backend.services.kpl_stock_gene import get_zt_gene
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

_GENE_LANE = "gene"
_GENE_CLOSE_CUTOFF = (15, 5)   # 收盘后刷新时点 15:05：盘中先拉保可用，收盘后刷终值
_UPSTREAM_POOL = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=1"


def _pool_member_ids(row: dict[str, Any]) -> list[str]:
    """日档涨停池成员 stock_id（无前缀 items 字段），保持原始顺序。"""
    out: list[str] = []
    for m in row.get("items") or []:
        sid = str((m or {}).get("stock_id") or "").strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def _close_cutoff(now: datetime) -> datetime:
    """该日的收盘后刷新截止时刻（本地 15:05）。"""
    return now.replace(hour=_GENE_CLOSE_CUTOFF[0], minute=_GENE_CLOSE_CUTOFF[1],
                       second=0, microsecond=0)


def pick_gene_targets(db: Any, date: str, *, limit: int = 6,
                      now: Optional[datetime] = None) -> dict[str, Any]:
    """挑本轮要拉基因的成员（纯函数，不写库）：缺失优先，收盘后补一次终值刷新。

    顺序：①涨停池成员中尚无 gene_items 的股（按池内顺序）→ ②收盘后（≥15:05）对盘中
    拉的旧值（fetched_at < 当日 15:05）各刷新一次。limit 控发数（服务端全局 ≥2s 单发
    间隔，不能一轮打 30 只）。日档不存在/池为空 → targets 空 + 结构化 reason（不静默）。
    """
    stamp = now or datetime.now(TZ_SHANGHAI)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    members = _pool_member_ids(row)
    if not members:
        reason = "no_archive" if not row else "empty_pool"
        return {"ok": False, "reason": reason, "date": date,
                "targets": [], "pending_n": 0, "refresh_n": 0}
    done: dict[str, str] = {}
    for g in row.get("gene_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            done[sid] = str(g.get("fetched_at") or "")
    cutoff = _close_cutoff(stamp).isoformat()
    after_close = stamp >= _close_cutoff(stamp)
    missing = [sid for sid in members if sid not in done]
    refresh = [sid for sid in members if sid in done and after_close and done[sid] < cutoff]
    ordered = missing + refresh
    return {"ok": True, "date": date, "targets": ordered[:max(0, int(limit))],
            "pending_n": len(missing), "refresh_n": len(refresh),
            "member_n": len(members), "gene_n": len(done), "after_close": after_close}


def archive_gene_corpus(db: Any, payload: dict[str, Any], *,
                        now: Optional[datetime] = None) -> dict[str, Any]:
    """涨停基因语料落库（字段级 $set，只写 gene_ 前缀字段，不与打板通道整 doc 互踩）。

    payload: {"date": 交易日, "genes": [get_zt_gene 结果, ...]}
    仅写入 ok 的条目（raw 六元数组原样 + 具名字段 + window_note + fetched_at + source）；
    失败条目进 gene_failures（fail-visible，不伪装成 0）。本批无一成功且无既有语料 →
    ok False（no_gene_fetched），不写库、不覆盖既有语料。
    """
    date = str(payload.get("date") or "")
    genes = payload.get("genes") or []
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _GENE_LANE,
                "date": None, "item_n": 0}
    stamp = (now or datetime.now(TZ_SHANGHAI)).isoformat()
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    members: dict[str, dict[str, Any]] = {}
    for g in row.get("gene_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            members[sid] = dict(g)
    merged_n = 0
    failures: list[dict[str, Any]] = []
    for res in (genes if isinstance(genes, list) else []):
        res = res if isinstance(res, dict) else {}
        sid = str(res.get("stock_id") or "").strip()
        if not res.get("ok"):
            failures.append({"stock_id": sid, "reason": res.get("reason") or "failed",
                             "error": str(res.get("error") or "")[:120]})
            continue
        if not sid:
            failures.append({"stock_id": "", "reason": "missing_stock_id"})
            continue
        item: dict[str, Any] = {
            "stock_id": sid,
            "gene": res.get("gene") or {},
            "gene_labels": res.get("gene_labels") or {},
            "raw": res.get("raw"),
            "raw_len": res.get("raw_len"),
            "window_note": res.get("window_note"),
            "fetched_at": stamp,
            "source": "http_GetZhangTingGene",
        }
        if res.get("partial"):
            item["partial"] = True
            item["missing_fields"] = res.get("missing_fields") or []
        members[sid] = item
        merged_n += 1
    if not merged_n and not members:
        return {"ok": False, "reason": "no_gene_fetched", "lane": _GENE_LANE,
                "date": date, "item_n": 0, "failures_n": len(failures)}
    pending = [sid for sid in _pool_member_ids(row) if sid not in members]
    fields = {
        "gene_date": date,
        "gene_source": "http_GetZhangTingGene",
        "gene_items": list(members.values()),
        "gene_count": len(members),
        "gene_pending_n": len(pending),
        "gene_failures": failures,
        "gene_archived_at": stamp,
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": fields})
    return {"ok": True, "lane": _GENE_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "failures_n": len(failures), "pending_n": len(pending)}


def load_gene_corpus(db: Any, date: str) -> dict[str, Any]:
    """涨停基因语料读口（jev 投喂原料）：{ok, date, items, count, pending_n, archived_at}。

    fail-visible：「日档不存在」（no_archive）与「日档在但基因语料未落库」
    （no_gene_corpus）严格分开，不伪装空语料；pending_n>0 = 涨停池成员尚有未拉的股
    （语料覆盖度未满，消费方可见）。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _GENE_LANE}
    items = row.get("gene_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_gene_corpus",
                "date": date, "lane": _GENE_LANE, "item_n": 0,
                "failures": row.get("gene_failures") or [],
                "note": "日档存在但涨停基因语料未落库（存档器未运行或该轮全部拉取失败）"}
    return {"ok": True, "source": "local_archive", "lane": _GENE_LANE,
            "date": row.get("gene_date") or date, "items": items,
            "count": len(items), "pending_n": row.get("gene_pending_n") or 0,
            "failures": row.get("gene_failures") or [],
            "archived_at": row.get("gene_archived_at"),
            "corpus_source": row.get("gene_source") or "http_GetZhangTingGene"}


class GeneCorpusArchiver:
    """涨停基因语料增量存档器（独立循环，字段级 $set 只写 gene_ 前缀）。

    每轮：拉一次 :8002 涨停池快照取「当前交易日」（周末/盘前=上一交易日，与打板通道
    同口径）→ pick_gene_targets 挑本轮 limit 只 → 逐股 get_zt_gene（HTTP，服务端 ≥2s
    限频）→ archive_gene_corpus 落库。任一环节失败只记 lastResult，不退循环。
    pandas/pytest 无关：fetcher 与 database_factory 均可注入（pytest 全 mock）。
    """

    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        database_factory: Callable[[], Any] = get_runtime_mongodb_database,
        settings: Any | None = None,
        pool_upstream_url: str = _UPSTREAM_POOL,
        gene_fetcher: Callable[[str], dict[str, Any]] = get_zt_gene,
        gene_limit: int = 6,
    ) -> None:
        current = settings or get_settings()
        self.enabled = current.storage_backend == "mongodb"
        self.interval_seconds = max(30, int(interval_seconds))
        self._database_factory = database_factory
        self._pool_upstream_url = pool_upstream_url
        self._gene_fetcher = gene_fetcher
        self._gene_limit = max(1, int(gene_limit))
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
            "geneLimit": self._gene_limit,
            "lastRunAt": self._last_run_at,
            "lastResult": self._last_result,
            "lastError": self._last_error,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                return
            except Exception as error:   # 单轮失败不退循环（fail-visible 进 status）
                self._last_error = str(error)
            await asyncio.sleep(self.interval_seconds)

    async def _run_once(self) -> None:
        self._last_run_at = datetime.now(TZ_SHANGHAI).isoformat()
        result: dict[str, Any] = {}
        self._last_result = result   # 渐进发布：异常时也是本轮部分结果，不留上一轮残影
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            try:
                payload = (await client.get(self._pool_upstream_url)).json()
            except Exception as error:
                result["pool"] = {"ok": False, "reason": f"fetch_failed:{error}"}
                self._last_error = f"pool:fetch_failed:{error}"
                return
            date = str(payload.get("date") or "") if payload.get("ok") else ""
            if not date:
                result["pool"] = {"ok": False, "reason": f"collector_degraded:"
                                                       f"{payload.get('reason') or 'unknown'}"}
                self._last_error = "pool:collector_degraded"
                return
            result["pool"] = {"ok": True, "date": date}
            try:
                db = self._database_factory()
                plan = await asyncio.to_thread(pick_gene_targets, db, date,
                                               limit=self._gene_limit)
            except Exception as error:
                result["plan"] = {"ok": False, "reason": f"plan_failed:{error}"}
                self._last_error = f"plan:{error}"
                return
            result["plan"] = {k: plan.get(k) for k in
                              ("ok", "reason", "pending_n", "refresh_n", "member_n", "gene_n")}
            if not plan.get("targets"):
                result["gene"] = {"ok": True, "skipped": "no_targets", "date": date,
                                  "pending_n": plan.get("pending_n")}
                self._last_error = None
                return
            genes = [await asyncio.to_thread(self._gene_fetcher, sid)
                     for sid in plan["targets"]]
            try:
                result["gene"] = await asyncio.to_thread(
                    archive_gene_corpus, db, {"date": date, "genes": genes})
            except Exception as error:
                result["gene"] = {"ok": False, "reason": f"archive_failed:{error}"}
        self._last_error = None if result.get("gene", {}).get("ok") \
            else f"gene:{result.get('gene', {}).get('reason')}"


_gene_corpus_archiver: Optional[GeneCorpusArchiver] = None


def get_gene_corpus_archiver() -> GeneCorpusArchiver:
    global _gene_corpus_archiver
    if _gene_corpus_archiver is None:
        _gene_corpus_archiver = GeneCorpusArchiver()
    return _gene_corpus_archiver


async def close_gene_corpus_archiver() -> None:
    global _gene_corpus_archiver
    if _gene_corpus_archiver is not None:
        await _gene_corpus_archiver.stop()
        _gene_corpus_archiver = None