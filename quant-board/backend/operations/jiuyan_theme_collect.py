# -*- coding: utf-8 -*-
"""韭研题材/事件语料采集编排（L3，2026-10-20）。

流程：`jiuyan_auth.resolve_auth` → 三个端点各拉一次 → 落 `jiuyan_timeline` /
`jiuyan_ai_industry`。三源互相独立：**任一源失败只降级该源**，不全军覆没（§4.0）。

CLI：
  python -m backend.operations.jiuyan_theme_collect --date 2026-10-20 [--dry-run] [--sources news,list]

`--dry-run` 不写业务库、只打印统计与前 3 条未来事件（零 jev 调用，但**照常计 HTTP 调用数**）。

**额度护栏（2026-10-20 实测教训）**：题材端点（`/jystock-app/api/v1/*`）与异动解析端点
（`/action/*`）是**两套独立日额度**：当日异动端点 errCode=0 时，题材端点仍可能 errCode=9
（且 msg 伪装成「服务繁忙，请稍后再试」——不得据 msg 猜，只按 errCode 结构化）。
今日调研期多次探测把题材额度烧穿后，当天剩下的题材采集全部失败。因此本层：
1. 按端点分别计数落地（`jiuyan_api_calls`，`_id={fetchDate}`）；
2. 开工前先算额度（`JIUYAN_THEME_DAILY_CALL_BUDGET`，默认 4），超出即跳过该源并
   在结果里 fail-visible 列出（不静默空跑、不假装无数据）；
3. 支持分源采集：盘前只需事件日历（`news,list`），收盘后只需板块催化正文（`industry`）。
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

logger = logging.getLogger(__name__)

NEWS_LIMIT = 20
LIST_LIMIT = 60
# 每源一次调用的标识（额度计数键）
SOURCE_NEWS, SOURCE_LIST, SOURCE_INDUSTRY = "timeline_news", "timeline_list", "ai_industry"
ALL_SOURCES = (SOURCE_NEWS, SOURCE_LIST, SOURCE_INDUSTRY)
# 每日调用护栏（防连发被限流；**不是**日额度上限——实测 errCode=9 是短时限流，静默 ~20 分钟后恢复）。
# 调度每日 3 次（盘前 2 + 收盘后 1）；预算 12 只防失控，不阻碍重试。
# 2026-10-20 实测教训：单日 12 次会被「重试 + 启动补跑」吃穿，且砍源顺序把 **industry 砍在最前**，
# 导致当天 `skippedByBudget=["ai_industry"]` → 730 节点 `contentChangedDate` 停在旧日，
# 而 industry 正文正是 `high_ge65` 档「新催化」的唯一入口（详见 §11 可达性核算 0/94）。
DEFAULT_DAILY_CALL_BUDGET = 12
# 额度不足时的**保留优先级**：数值越大越优先保留（先砍 list，其次 news，最后 industry）。
# 原实现按 `want` 顺序从后往前砍 = industry 最先死，与「正文是 high_ge65 唯一入口」正好相反。
SOURCE_KEEP_PRIORITY = {SOURCE_LIST: 0, SOURCE_NEWS: 1, SOURCE_INDUSTRY: 2}
# 源之间最小间隔（秒）：串行 + 间隔，避免连续请求触发限流。
# 实测（2026-10-20）：连续 3 次调用（间隔 5s）能过，紧接再打 2 次就全灭 →
# 阈值约「数分钟内 ~3-5 次」，因此间隔放到 20s，把单轮 3 次摊开到 ≈40s。
INTER_CALL_DELAY_SECONDS = 20.0
# 被限流（errCode=9）后的退避重试：再等这么久重试一次；仍限流则记降级（不无限重试）。
# 60s：实测限流窗口以「分钟」计（静默 ~20 分钟后恢复），退避太短等于白打一次。
# 最坏耗时核算（须 < 调度超时 300s）：3 源 × (20s + 60s) = 240s。
RATE_LIMIT_RETRY_SLEEP_SECONDS = 60.0
RATE_LIMIT_MAX_RETRIES = 1


def daily_call_budget() -> int:
    """题材端点每日 HTTP 调用预算（env 可覆盖；护栏不一，禁用则置很大值）。"""
    try:
        return max(1, int(os.environ.get("JIUYAN_THEME_DAILY_CALL_BUDGET",
                                        DEFAULT_DAILY_CALL_BUDGET)))
    except ValueError:
        return DEFAULT_DAILY_CALL_BUDGET


def collect_once(*, db: Any = None, fetch_date: str | None = None, dry_run: bool = False,
                 date: str | None = None, sources: tuple[str, ...] | None = None,
                 budget: int | None = None) -> dict:
    """拉取 + 落库指定源（默认三源）。返回结构化统计；失败源进 `degraded`，不伪造成功。

    `fetch_date` = 采集日（写 forwardDays/firstSeenDate）；`date` = 认证铸造用的参考日
    （韭研 token 铸造要一个异动日期，默认取交易日）。
    `sources` = 本次要拉的源（盘前只拉事件日历，收盘后只拉催化正文）；缺省=全部。
    `budget` = 当日题材端点调用预算（缺省读 env）；已用+本次计划 超预算时跳过相应源。
    """
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()

    want = tuple(s for s in (sources or ALL_SOURCES) if s in ALL_SOURCES)
    budget = daily_call_budget() if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    planned = len(want)
    skipped_by_budget: list[str] = []
    if used + planned > budget:
        # 额度不够：按 `SOURCE_KEEP_PRIORITY` 从**低价值端**砍（不是按 want 顺序——原实现
        # 把 industry 砍在最前，而它恰是 high_ge65「新催化」唯一入口；实测 2026-10-20 吃过这个亏）。
        by_value = sorted(want, key=lambda s: -SOURCE_KEEP_PRIORITY.get(s, 1))
        keep_n = max(0, budget - used)
        kept = set(by_value[:keep_n])
        skipped_by_budget = [s for s in by_value[keep_n:]]
        want = tuple(s for s in want if s in kept)
        logger.warning("题材采集额度不足：当日已用 %d + 计划 %d > 预算 %d，跳过 %s",
                       used, planned, budget, skipped_by_budget)

    auth = jiuyan_auth.resolve_auth(date=date or fetch_date)
    if not auth.get("ok"):
        return {"ok": False, "error": auth.get("error"), "authFailed": bool(auth.get("authFailed")),
                "degraded": ["auth"], "skippedByBudget": skipped_by_budget,
                "callsUsedToday": used, "budget": budget}

    kw = {"session_cookie": auth["session"], "token": auth["token"], "timestamp": auth["timestamp"]}
    degraded: list[str] = []
    empty_sources: list[str] = []
    stats: dict[str, Any] = {"ok": True, "fetchDate": fetch_date,
                             "tokenSource": str(auth.get("source") or "unknown"),
                             "sources": list(want), "skippedByBudget": skipped_by_budget,
                             "callsUsedToday": used, "callsThisRun": len(want), "budget": budget}

    # 只拉本次需要的源；无论成败都计数（失败的请求同样消耗服务端额度）。
    # 串行 + 源间间隔 + 限流退避重试（2026-10-20 实测：连发触发 errCode=9，静默 ~20 分钟后恢复）。
    def _fetch(source: str, fn: Any, **fkw: Any) -> dict | None:
        if source not in want:
            return None
        retries = 0
        while True:
            time.sleep(INTER_CALL_DELAY_SECONDS)
            S.record_api_calls(db, fetch_date, (source,))
            res = fn(**fkw)
            if not res.get("rateLimited") or retries >= RATE_LIMIT_MAX_RETRIES:
                return res
            retries += 1
            logger.warning("%s 被限流（errCode=9），%.0fs 后重试 %d/%d",
                           source, RATE_LIMIT_RETRY_SLEEP_SECONDS, retries,
                           RATE_LIMIT_MAX_RETRIES)
            time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)

    # P1 修复（2026-10-20 review）：逐段先落库再拉下一段——最坏时序 3 源 420s 会撞穿调度
    # 300s 超时（已提至 480s），若等三源全部 fetch 完才落库，超时被杀 = 已抓到的源全丢。
    news = _fetch(SOURCE_NEWS, F.fetch_timeline_news, limit=NEWS_LIMIT, **kw)
    listing = _fetch(SOURCE_LIST, F.fetch_timeline_list, limit=LIST_LIMIT, **kw)

    timeline_stats = {"written": 0, "skipped": 0, "future": 0, "past": 0}
    events: list[dict] = []
    for day in (news or {}).get("days") or []:
        for it in day.get("items") or []:
            events.append({**it, "date": day["date"], "grade": None, "createTime": None,
                           "themes": [], "timelineId": None})
    events.extend((listing or {}).get("items") or [])
    if not dry_run and events:
        timeline_stats = S.save_timeline_items(db, fetch_date=fetch_date, source="news_list",
                                               items=events)

    industry = _fetch(SOURCE_INDUSTRY, F.fetch_ai_industry, **kw)
    industry_stats = {"written": 0, "contentChanged": 0, "withContent": 0}
    if not dry_run and (industry or {}).get("nodes"):
        industry_stats = S.save_industry_nodes(db, fetch_date=fetch_date,
                                               nodes=industry["nodes"])

    for name, res in ((SOURCE_NEWS, news), (SOURCE_LIST, listing), (SOURCE_INDUSTRY, industry)):
        if res is None:
            continue
        if not res.get("ok"):
            degraded.append(f"{name}: {res.get('error')}")
            continue
        # 空载荷也是异常，不得当“成功无数据”（AGENTS §4.0）：实测服务端间歇限流期间会返回
        # `errCode=0` 但空列表（2026-10-20 15:45 调度采集 industry 就是 fetched=0 而 ok=True，
        # 把限流伪装成“今天没题材”——这正是要禁止的静默降级）。
        items = (res.get("days") if name == SOURCE_NEWS
                 else res.get("items") if name == SOURCE_LIST else res.get("nodes")) or []
        if not items:
            empty_sources.append(name)
            degraded.append(f"{name}: 空载荷（errCode=0 但 0 条，疑服务端限流/降级）")

    stats["timeline"] = {**timeline_stats, "fetched": len(events),
                         "futureSample": [{"date": e["date"], "title": e["title"]}
                                          for e in sorted(events, key=lambda x: x["date"])
                                          if (e.get("date") or "") >= fetch_date][:3]}
    stats["industry"] = {**industry_stats, "fetched": len((industry or {}).get("nodes") or [])}
    stats["degraded"] = degraded
    stats["emptySources"] = empty_sources
    stats["ok"] = len(degraded) < max(1, len(want))   # 本次所有源都失败才算失败（§4.0）
    stats["callsUsedTodayAfter"] = S.calls_recorded(db, fetch_date)
    if dry_run:
        stats["dryRun"] = True
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="韭研题材/事件语料采集（L3）")
    ap.add_argument("--date", default=None, help="采集日（默认今天，YYYY-MM-DD）")
    ap.add_argument("--dry-run", action="store_true", help="不写业务库，只打印统计（仍计调用额度）")
    ap.add_argument("--sources", default=None,
                    help="逗号分隔：timeline_news,timeline_list,ai_industry（缺省=全部）")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"当日题材端点调用预算（缺省 env/常量={DEFAULT_DAILY_CALL_BUDGET}）")
    ap.add_argument("--json", default=None, help="统计写入该文件")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    srcs = (tuple(s.strip() for s in args.sources.split(",") if s.strip())
            if args.sources else None)
    result = collect_once(fetch_date=args.date, dry_run=args.dry_run, sources=srcs,
                          budget=args.budget)
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    print(text)
    if args.json:
        from pathlib import Path
        Path(args.json).write_text(text, encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
