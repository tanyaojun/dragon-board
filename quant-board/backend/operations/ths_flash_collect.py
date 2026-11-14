# -*- coding: utf-8 -*-
"""同花顺 7×24 快讯采集编排（2026-11-14 盘前催化增量 C；只供 09:26 竞价链晨间窗）。

流程：短路（当日 meta.state=ok 在库 → 零 HTTP）→ 预算护栏（`ths_api_calls`，
`THS_FLASH_DAILY_CALL_BUDGET` 默认 8）→ 逐页拉取（≤3 页，回溯至 ctime < T−1 15:00
窗口起点即停）→ 幂等落库 → meta 覆盖档。

fail-visible（AGENTS §1.2-9/§4.0）：
- 页失败 60s 退避重试一次，仍失败 → meta.state=failed + degraded（有限次，不无限重试）；
- **无凭据、无 socket、无轮询风暴**（两尝试槽，日总调用 ≤ 预算：每次 HTTP 前预算准入，
  含退避重试那次；超出即停不重试，meta 落 failed）；
- 采集与打标解耦：任何失败绝不阻塞 09:26 打标（digest 读窗口，缺档=flashState 披露）。

CLI：
  python -m backend.operations.ths_flash_collect --date 2026-11-14 [--dry-run]

`--dry-run` 完全只读（不写业务库、不写预算计数、不落 meta/items，只打印统计）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from backend.operations import ths_flash_fetch as F
from backend.operations import ths_flash_store as S
from backend.operations.jiuyan_theme_collect import THEME_COLLECT_RESULT_MARKER

logger = logging.getLogger(__name__)

SOURCE_FLASH = "ths_flash"
DEFAULT_PAGES_PER_ATTEMPT = 3
DEFAULT_DAILY_CALL_BUDGET = 8
RETRY_SLEEP_SECONDS = 60.0
RETRY_MAX = 1


def daily_call_budget() -> int:
    try:
        return max(1, int(os.environ.get("THS_FLASH_DAILY_CALL_BUDGET",
                                        DEFAULT_DAILY_CALL_BUDGET)))
    except ValueError:
        return DEFAULT_DAILY_CALL_BUDGET


def flash_enabled() -> bool:
    """快讯采集开关（默认开；`THS_FLASH_COLLECT_ENABLED=0` 关闭）。"""
    return os.environ.get("THS_FLASH_COLLECT_ENABLED", "1") != "0"


def collect_once(*, db: Any = None, fetch_date: str | None = None,
                 dry_run: bool = False, budget: int | None = None) -> dict:
    """拉取 + 落库隔夜快讯。返回结构化统计；失败进 `degraded`/meta 覆盖档。"""
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()
    result: dict[str, Any] = {"ok": True, "fetchDate": fetch_date, "source": SOURCE_FLASH,
                              "skippedByBudget": [], "degraded": []}
    if not flash_enabled():
        return {**result, "skipped": True, "reason": "disabled"}
    budget = daily_call_budget() if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    result["callsUsedToday"] = used
    result["budget"] = budget
    meta = S.get_meta(db, date=fetch_date) or {}
    if str(meta.get("state") or "") == "ok":
        return {**result, "skipped": True, "reason": "already_covered",
                "pages": meta.get("pages"), "written": meta.get("written")}
    pages_planned = DEFAULT_PAGES_PER_ATTEMPT
    # 预算准入语义：真实上限在每次 HTTP 前（_fetch_page_with_backoff）逐次校验，
    # 总调用 ≤ 预算（含退避重试）；此处只做连一页都发不了的快失败。
    if used >= budget:
        return {**result, "ok": False,
                "error": {"code": "budget_exhausted",
                          "message": f"当日已用 {used} ≥ 预算 {budget}"},
                "skippedByBudget": [SOURCE_FLASH]}

    start_epoch, _end = S.flash_window_epochs(fetch_date)
    total_written = skipped_existing = 0
    pages_done = 0
    oldest_ctime: int | None = None
    reached_window_start = False
    error: str | None = None
    for page in range(1, pages_planned + 1):
        res = _fetch_page_with_backoff(db, fetch_date, page, budget=budget,
                                       dry_run=dry_run)
        if not res.get("ok"):
            error = str(res.get("error") or "unknown")
            break
        parsed = F.parse_flash_payload(res.get("payload") or {})
        if not parsed.get("ok"):
            error = str(parsed.get("error") or "parse_failed")
            break
        items = parsed.get("items") or []
        pages_done += 1
        if not dry_run:
            saved = S.save_flash_items(db, fetch_date=fetch_date, items=items)
            total_written += saved.get("written") or 0
            skipped_existing += saved.get("skippedExisting") or 0
        else:
            total_written += len(items)
        if items:
            oldest_ctime = min((it["ctimeEpoch"] for it in items), default=None)
            if oldest_ctime is not None and oldest_ctime < start_epoch:
                reached_window_start = True
                break
        if len(items) < F.FLASH_PAGESIZE:
            reached_window_start = True   # 页尽=到 feed 头，视为窗口覆盖完成
            break
    state = "ok" if (reached_window_start and error is None) else "failed"
    if not dry_run:
        S.save_meta(db, fetch_date=fetch_date, state=state, pages=pages_done,
                    written=total_written, oldest_ctime=oldest_ctime, error=error)
    result.update({"state": state, "pages": pages_done, "written": total_written,
                   "skippedExisting": skipped_existing, "oldestCtime": oldest_ctime,
                   "reachedWindowStart": reached_window_start,
                   "callsUsedToday": used if dry_run else S.calls_recorded(db, fetch_date)})
    if state != "ok":
        return {**result, "ok": False, "degraded": [f"{SOURCE_FLASH}:failed"], "error":
                {"code": "ths_flash_failed", "message": (error or "")[:200]}}
    return result


def _fetch_page_with_backoff(db: Any, fetch_date: str, page: int, *, budget: int,
                             dry_run: bool = False) -> dict:
    """页拉取 + 失败 60s 退避重试一次（有限次，红线 9）。

    每次 HTTP（首发与退避重试）前预算准入：超出即不发起/不重试，返回
    budget_exhausted 失败 → 循环 break → meta 落 failed。总调用严格 ≤ 预算。
    """
    if not dry_run and S.calls_recorded(db, fetch_date) >= budget:
        return {"ok": False, "error": "budget_exhausted"}
    if not dry_run:
        S.record_api_calls(db, fetch_date, 1)
    res = F.fetch_flash_page(page)
    if not res.get("ok"):
        logger.warning("ths_flash page=%s 失败（%s），%.0fs 后重试一次", page,
                       res.get("error"), RETRY_SLEEP_SECONDS)
        time.sleep(RETRY_SLEEP_SECONDS)
        if not dry_run and S.calls_recorded(db, fetch_date) >= budget:
            logger.warning("ths_flash 预算耗尽，放弃重试 page=%s", page)
            return {"ok": False, "error": "budget_exhausted"}
        if not dry_run:
            S.record_api_calls(db, fetch_date, 1)
        res = F.fetch_flash_page(page)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同花顺 7×24 快讯采集（只供 09:26 竞价链晨间窗）")
    ap.add_argument("--date", default=None, help="采集日（默认今天，YYYY-MM-DD）")
    ap.add_argument("--dry-run", action="store_true", help="完全只读：不写业务库/计数/meta，只打印统计")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"当日调用预算（缺省 env/常量={DEFAULT_DAILY_CALL_BUDGET}）")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = collect_once(fetch_date=args.date, dry_run=args.dry_run, budget=args.budget)
    # stdout 机读接口：复用共享标记 THEME_COLLECT_RESULT_JSON:（分派器单一解析实现）
    print(THEME_COLLECT_RESULT_MARKER + json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
