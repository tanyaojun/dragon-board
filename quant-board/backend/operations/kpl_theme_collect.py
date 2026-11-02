# -*- coding: utf-8 -*-
"""开盘啦题材语料采集编排（2026-10-23，v4 换源：事件层唯一权威源）。

流程：topic_list(1 次) → 识别新事件 → 新事件逐条 InfoGet 补详情（**只补缺失**，单轮上限
`DETAIL_CAP_PER_RUN`）→ news 流(1 次) → calendar(1 次)。三个集合幂等 upsert。

额度护栏（沿用韭研 §5.3 纪律，参数按 KPL 特性放宽——实测单发 3s 间隔无限流）：
1. 调用计数落地 `kpl_api_calls`（失败同样计数）；日预算 `KPL_THEME_DAILY_CALL_BUDGET`（默认 20）；
2. 串行 + 源间间隔 `INTER_CALL_DELAY_SECONDS`（3s）+ 失败退避重试 1 次（20s）；
3. **空载荷 = 降级不是成功**（errcode=0 但 0 条 → `emptySources` + `degraded`，§4.0）；
4. `--dry-run` 不写业务库，只打印统计（仍计 HTTP 调用数，与韭研同口径）。

CLI：
  python -m backend.operations.kpl_theme_collect --date 2026-10-23 [--dry-run] [--budget 20]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from backend.operations import kpl_theme_fetch as F
from backend.operations import kpl_theme_store as S

THEME_COLLECT_RESULT_MARKER = "THEME_COLLECT_RESULT_JSON:"   # stdout 机读接口标记（2026-11-02）

logger = logging.getLogger(__name__)

NEWS_ST = 50
CALENDAR_ST = 50
TOPIC_LIST_ST = 15          # InfoList 上限（实测覆盖 ~16 日）
DETAIL_CAP_PER_RUN = 8      # 单轮新事件详情补拉上限（防首日冷启动连发）

DEFAULT_DAILY_CALL_BUDGET = 20
INTER_CALL_DELAY_SECONDS = 3.0
RETRY_SLEEP_SECONDS = 20.0
RETRY_MAX = 1


def daily_call_budget() -> int:
    try:
        return max(1, int(os.environ.get("KPL_THEME_DAILY_CALL_BUDGET",
                                        DEFAULT_DAILY_CALL_BUDGET)))
    except ValueError:
        return DEFAULT_DAILY_CALL_BUDGET


def collect_once(*, db: Any = None, fetch_date: str | None = None,
                 dry_run: bool = False, budget: int | None = None) -> dict:
    """拉取 + 落库开盘啦三路语料。返回结构化统计；失败/空载荷进 `degraded`（§4.0）。"""
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()

    budget = daily_call_budget() if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    # 计划调用：1(topic list) + 1(news) + 1(calendar) + 新事件详情数（运行中才知道，
    # 先按上限预留判额——不够就只拉列表不补详情，fail-visible）
    planned_max = 3 + DETAIL_CAP_PER_RUN
    skipped_by_budget: list[str] = []
    if used + planned_max > budget:
        skipped_by_budget = ["topic_detail"]
        logger.warning("KPL 采集额度紧张：已用 %d + 预留 %d > 预算 %d，本轮只拉三主源不补详情",
                       used, planned_max, budget)

    degraded: list[str] = []
    empty_sources: list[str] = []
    stats: dict[str, Any] = {"ok": True, "fetchDate": fetch_date, "source": "kpl",
                             "skippedByBudget": skipped_by_budget,
                             "callsUsedToday": used, "budget": budget}

    def _call(source: str, fn: Any, **fkw: Any) -> dict | None:
        """单发 + 间隔 + 退避重试 1 次（仅网络级错误重试，业务 errcode 不重试）；
        无论成败都计数（服务端已扣额度）。注意：重试额外计数不回检日预算——
        护栏防失控不阻碍重试，极端网络抖动下当日实际调用可超出预算上限（review 2026-10-23）。"""
        retries = 0
        while True:
            time.sleep(INTER_CALL_DELAY_SECONDS)
            S.record_api_calls(db, fetch_date, (source,))
            res = fn(**fkw)
            if res.get("ok") or res.get("errorCode") != "http_error" or retries >= RETRY_MAX:
                return res
            retries += 1
            logger.warning("%s 网络错误，%.0fs 后重试 %d/%d", source, RETRY_SLEEP_SECONDS,
                           retries, RETRY_MAX)
            time.sleep(RETRY_SLEEP_SECONDS)

    def _note(source: str, res: dict | None, items: list | tuple) -> None:
        if res is None:
            return
        if not res.get("ok"):
            degraded.append(f"{source}: [{res.get('errorCode')}] {res.get('error')}")
        elif not items:
            empty_sources.append(source)
            degraded.append(f"{source}: 空载荷（errcode=0 但 0 条，疑服务端降级）")

    # ① 题材事件列表
    detail_failures: list[str] = []
    topic_res = _call("topic_list", F.fetch_topic_list, st=TOPIC_LIST_ST)
    events = (topic_res or {}).get("events") or []
    _note("topic_list", topic_res, events)
    # ② 新事件详情（只补缺失；库里已有全文的跳过，省调用）
    details: dict[str, dict] = {}
    if events and "topic_detail" not in skipped_by_budget:
        new_ids = []
        for ev in events:
            eid = str(ev.get("eventId") or "")
            day = str(ev.get("day") or "")
            if not eid or not day:
                continue
            doc = db[S.COLLECTION_TOPIC].find_one({"_id": f"{day}:{eid}"}, {"content": 1}) or {}
            if not doc.get("content"):
                new_ids.append(eid)
        for eid in new_ids[:DETAIL_CAP_PER_RUN]:
            dres = _call("topic_detail", F.fetch_topic_detail, event_id=eid)
            if dres and dres.get("ok") and (dres.get("detail") or {}).get("content"):
                details[eid] = dres["detail"]
            else:
                # 详情失败单列（不进 degraded）：只影响该事件补充进度，不代表采集轮失败
                detail_failures.append(f"topic_detail[{eid}]: {(dres or {}).get('error') or '空详情'}")
    topic_stats = {"written": 0, "detailFetched": 0, "fetched": len(events)}
    if not dry_run and events:
        topic_stats = S.save_topic_events(db, fetch_date=fetch_date, events=events,
                                          details=details)

    # ③ 题材新闻流（Kword 标签 + 关联个股）
    news_res = _call("theme_news", F.fetch_news_list, news_type=-1, st=NEWS_ST)
    news_items = (news_res or {}).get("items") or []
    _note("theme_news", news_res, news_items)
    news_stats = {"written": 0}
    if not dry_run and news_items:
        news_stats = S.save_news_items(db, fetch_date=fetch_date, items=news_items)

    # ④ 前瞻日历
    cal_res = _call("theme_calendar", F.fetch_news_list, news_type=3, st=CALENDAR_ST)
    cal_items = (cal_res or {}).get("items") or []
    _note("theme_calendar", cal_res, cal_items)
    cal_stats = {"written": 0}
    if not dry_run and cal_items:
        cal_stats = S.save_calendar_items(db, fetch_date=fetch_date, items=cal_items)

    stats["topic"] = {**topic_stats, "newDetails": len(details)}
    stats["news"] = {**news_stats, "fetched": len(news_items)}
    stats["calendar"] = {**cal_stats, "fetched": len(cal_items)}
    stats["degraded"] = degraded
    stats["emptySources"] = empty_sources
    # ok 只看三主源（topic_list/theme_news/theme_calendar）的 degraded；
    # 逐事件详情失败单列 detailFailures——它只影响补充进度，不代表本轮采集失败
    # （review 2026-10-23：详情失败混入 degraded 会放大成整轮失败、调度误翻红）
    stats["detailFailures"] = detail_failures
    stats["ok"] = len(degraded) < 3        # 三主源全挂才算失败（任一活源即有数据，§4.0）
    stats["callsUsedTodayAfter"] = S.calls_recorded(db, fetch_date)
    if dry_run:
        stats["dryRun"] = True
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="开盘啦题材语料采集（事件层唯一权威源）")
    ap.add_argument("--date", default=None, help="采集日（默认今天，YYYY-MM-DD）")
    ap.add_argument("--dry-run", action="store_true", help="不写业务库，只打印统计（仍计调用额度）")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"当日 KPL 端点调用预算（缺省 env/常量={DEFAULT_DAILY_CALL_BUDGET}）")
    ap.add_argument("--json", default=None, help="统计写入该文件")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = collect_once(fetch_date=args.date, dry_run=args.dry_run, budget=args.budget)
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    # stdout 机读接口=标记行单行 JSON（2026-11-02）：调度侧不再用「首个 { 截取」，
    # 防未来诊断行含 { 时截中披露文本导致 parse_failed → 结局/语料链静默断链。
    print(THEME_COLLECT_RESULT_MARKER + json.dumps(result, ensure_ascii=False, default=str))
    if args.json:
        from pathlib import Path
        Path(args.json).write_text(text, encoding="utf-8")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
