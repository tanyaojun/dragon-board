# -*- coding: utf-8 -*-
"""韭研早报晨间采集编排（2026-11-14 晨间例外复活，见
`docs/hotlist-jev/auction-preopen-catalyst-preregistration-20261114.md` §3）。

**定位**：早报（`/timeline/news` 当日块）是独立语料类型（人工编辑隔夜汇总），只供
09:26 竞价龙头链晨间窗消费；17:30 题材链事件层唯一权威源仍=开盘啦（2026-10-23
裁决不变）。`timeline/list` 日历**不恢复**（KPL 日历是超集，复活即双轨）。

流程：短路检查（当日 ok 档已在库 → skipped 零 HTTP）→ 额度护栏（`jiuyan_api_calls`
共享计数器，source=`timeline_news_morning`，日预算 `JIUYAN_THEME_DAILY_CALL_BUDGET`=12）
→ `jiuyan_auth.resolve_auth` → 1 次 POST `/timeline/news` → `is_briefing` 筛当日早报
→ `split_briefing_paragraphs` 切段 → 落 `jiuyan_morning_report`。

fail-visible（AGENTS §1.2-8/§4.0）：
- `not_published` 是结构化状态非失败（早报尚未发布，等下一尝试槽）；
- authFailed 清缓存 force_refresh 自愈一次；errCode=9 短时限流 60s 退避重试一次；
- 全部失败落 state 档供 `corpusState.morningState` 披露；**采集与打标解耦**，
  任何失败绝不阻塞 09:26 打标（打标只读库，缺档=叙事整行缺席）。

额度：题材端点（`/jystock-app/api/v1/*`）与异动端点（`/action/*`）两套独立日额度。
本层每尝试槽最坏 4 次 HTTP（首发 + errCode=9 退避重试 + authFailed 自愈重铸后首发
+ 自愈后再限流重试）；每次 HTTP 前预算准入，总调用严格 ≤ 共享预算，不挤占。
三尝试槽 + 产业树（16:10，1 次/日）共享预算 12（最坏情形下后到者按准入语义
fail-visible 跳过，status 披露）。

CLI：
  python -m backend.operations.jiuyan_morning_collect --date 2026-11-14 [--dry-run]

`--dry-run` 完全只读（不写业务库、不写预算计数、不落 state/ok 档，只打印统计）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from backend.operations import jiuyan_auth, jiuyan_theme_fetch as F, jiuyan_theme_store as S
from backend.operations.jiuyan_theme_collect import (
    DEFAULT_DAILY_CALL_BUDGET,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_RETRY_SLEEP_SECONDS,
    THEME_COLLECT_RESULT_MARKER,
)

logger = logging.getLogger(__name__)

SOURCE_MORNING = "timeline_news_morning"
NEWS_LIMIT = 20


def daily_call_budget() -> int:
    """题材端点每日 HTTP 调用预算（与产业树共享；env 可覆盖）。"""
    try:
        return max(1, int(os.environ.get("JIUYAN_THEME_DAILY_CALL_BUDGET",
                                        DEFAULT_DAILY_CALL_BUDGET)))
    except ValueError:
        return DEFAULT_DAILY_CALL_BUDGET


def morning_enabled() -> bool:
    """早报晨间采集开关（默认开；`JIUYAN_MORNING_COLLECT_ENABLED=0` 关闭）。"""
    return os.environ.get("JIUYAN_MORNING_COLLECT_ENABLED", "1") != "0"


def _fetch_morning(db: Any, fetch_date: str, auth: dict, *, budget: int,
                   dry_run: bool = False) -> tuple[dict, dict | None]:
    """有限次 HTTP：首发 + errCode=9 退避重试 1 次 + authFailed 自愈重试 1 次。

    每次 HTTP 前预算准入（dry_run 跳过计数与准入）：超出即不发起/不重试，
    返回 budget_exhausted 失败。总调用严格 ≤ 共享预算（红线 9）。
    返回 (fetch_result, self_heal_trace|None)。
    """
    def once(a: dict) -> dict:
        if not dry_run:
            if S.calls_recorded(db, fetch_date) >= budget:
                return {"ok": False, "error": "budget_exhausted"}
            S.record_api_calls(db, fetch_date, (SOURCE_MORNING,))
        return F.fetch_timeline_news(session_cookie=a["session"], token=a["token"],
                                     timestamp=a["timestamp"], limit=NEWS_LIMIT)

    self_heal: dict | None = None
    res = once(auth)
    retries = 0
    while res.get("rateLimited") and retries < RATE_LIMIT_MAX_RETRIES:
        retries += 1
        logger.warning("%s 被限流（errCode=9），%.0fs 后重试 %d/%d", SOURCE_MORNING,
                       RATE_LIMIT_RETRY_SLEEP_SECONDS, retries, RATE_LIMIT_MAX_RETRIES)
        time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)
        res = once(auth)
    if res.get("authFailed"):
        from backend.operations.jiuyan_store import clear_cached_session, clear_cached_token
        clear_cached_token()
        clear_cached_session()
        auth2 = jiuyan_auth.resolve_auth(date=fetch_date, force_refresh=True)
        self_heal = {"ok": bool(auth2.get("ok")), "firstError": str(res.get("error") or "")}
        if auth2.get("ok"):
            res = once(auth2)
            retries = 0
            while res.get("rateLimited") and retries < RATE_LIMIT_MAX_RETRIES:
                retries += 1
                time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)
                res = once(auth2)
            res["tokenSource"] = str(auth2.get("source") or "")
    return res, self_heal


def collect_once(*, db: Any = None, fetch_date: str | None = None,
                 dry_run: bool = False, budget: int | None = None) -> dict:
    """拉取 + 落库当日早报（每尝试槽一次）。返回结构化统计；失败进 `degraded`/state 档。

    `fetch_date` = 采集日（早报日档 `_id`）；`budget` = 当日题材端点调用预算（缺省读 env）。
    结果 `state` ∈ ok / not_published / fetch_failed / rate_limited / auth_failed。
    `ok=True` 仅代表本轮采集管道结构化完成（not_published 也算完成——等下一槽），
    早报内容是否在库以 `state` 为准。
    """
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()
    result: dict[str, Any] = {"ok": True, "fetchDate": fetch_date, "source": SOURCE_MORNING,
                              "skippedByBudget": [], "degraded": [], "state": None}
    if not morning_enabled():
        return {**result, "skipped": True, "reason": "disabled"}
    budget = daily_call_budget() if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    result["callsUsedToday"] = used
    result["budget"] = budget
    # 短路：当日 ok 档已在库 → 零 HTTP（重跑/补跑幂等；state 档不短路——允许下一槽重试）
    existing = S.get_morning_report(db, date=fetch_date)
    if (existing or {}).get("state") == "ok":
        return {**result, "skipped": True, "reason": "already_ok",
                "state": "ok", "paragraphs": len(existing.get("paragraphs") or [])}
    if used + 1 > budget:
        return {**result, "ok": False,
                "error": {"code": "budget_exhausted",
                          "message": f"当日已用 {used} + 计划 1 > 预算 {budget}"},
                "skippedByBudget": [SOURCE_MORNING]}

    auth = jiuyan_auth.resolve_auth(date=fetch_date)
    if not auth.get("ok"):
        from backend.operations.jiuyan_store import clear_cached_session, clear_cached_token
        clear_cached_token()
        clear_cached_session()
        auth = jiuyan_auth.resolve_auth(date=fetch_date, force_refresh=True)
        self_heal = {"ok": bool(auth.get("ok")), "firstError": str(auth.get("error") or "")}
        if not auth.get("ok"):
            return _persist_state(db, fetch_date, "auth_failed", result, dry_run,
                                  token_source=str(auth.get("source") or "unknown"),
                                  error=str(auth.get("error") or "auth_missing"),
                                  self_heal=self_heal)
    res, self_heal = _fetch_morning(db, fetch_date, auth, budget=budget, dry_run=dry_run)
    token_source = str(res.get("tokenSource") or auth.get("source") or "unknown")
    if self_heal:
        result["selfHeal"] = self_heal
    if not res.get("ok"):
        state = "rate_limited" if res.get("rateLimited") else "fetch_failed"
        return _persist_state(db, fetch_date, state, result, dry_run,
                              token_source=token_source, error=str(res.get("error") or ""),
                              self_heal=self_heal)
    briefing = F.extract_briefing(res.get("days") or [], fetch_date)
    if briefing is None:
        return _persist_state(db, fetch_date, "not_published", result, dry_run,
                              token_source=token_source, error=None, self_heal=self_heal)
    content = str(briefing.get("content") or "")
    paragraphs = F.split_briefing_paragraphs(content)
    result.update({"state": "ok", "title": str(briefing.get("title") or ""),
                   "paragraphs": len(paragraphs), "chars": len(content)})
    if not dry_run:
        saved = S.save_morning_report(db, fetch_date=fetch_date, state="ok",
                                      title=str(briefing.get("title") or ""),
                                      content=content, paragraphs=paragraphs,
                                      token_source=token_source, self_heal=self_heal)
        result["saved"] = saved
    return result


def _persist_state(db: Any, fetch_date: str, state: str, result: dict, dry_run: bool, *,
                   token_source: str, error: str | None,
                   self_heal: dict | None) -> dict:
    """非 ok 状态落 state 档（dry_run 不写库）并返回结构化结果。

    not_published 非失败（ok=True，等下一尝试槽）；fetch_failed/rate_limited/auth_failed
    为降级（ok=False + degraded，fail-visible）。
    """
    result["state"] = state
    if error:
        result["error"] = {"code": state, "message": error[:200]}
    if self_heal:
        result["selfHeal"] = self_heal
    if not dry_run:
        S.save_morning_report(db, fetch_date=fetch_date, state=state,
                              token_source=token_source, self_heal=self_heal)
    if state == "not_published":
        return {**result, "ok": True}
    return {**result, "ok": False, "degraded": [f"{SOURCE_MORNING}:{state}"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="韭研早报晨间采集（只供 09:26 竞价链晨间窗）")
    ap.add_argument("--date", default=None, help="采集日（默认今天，YYYY-MM-DD）")
    ap.add_argument("--dry-run", action="store_true", help="完全只读：不写业务库/计数/state 档，只打印统计")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"当日题材端点调用预算（缺省 env/常量={DEFAULT_DAILY_CALL_BUDGET}）")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = collect_once(fetch_date=args.date, dry_run=args.dry_run, budget=args.budget)
    # stdout 机读接口：复用共享标记 THEME_COLLECT_RESULT_JSON:（分派器单一解析实现）
    print(THEME_COLLECT_RESULT_MARKER + json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
