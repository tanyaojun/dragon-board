# -*- coding: utf-8 -*-
"""韭研题材语料采集编排（2026-10-23 v4 换源后单源化：只拉产业树 `ai_industry`）。

**事件层已换源**：投资日历/早报（`timeline_news`/`timeline_list`）随 2026-10-23 裁决
（方案 A：事件层唯一权威源=开盘啦，见 `kpl_theme_collect.py`）退役——采集路径删除，
`jiuyan_timeline` 集合导出归档后 drop。本模块只剩产业树正文刷新（KPL 无对应物）。

流程：`jiuyan_auth.resolve_auth` → `ai/industry/list` 一次 → 落 `jiuyan_ai_industry`。

CLI：
  python -m backend.operations.jiuyan_theme_collect --date 2026-10-23 [--dry-run]

`--dry-run` 不写业务库、只打印统计（零 jev 调用，但**照常计 HTTP 调用数**）。

**额度护栏（2026-10-20 实测教训，保留）**：题材端点（`/jystock-app/api/v1/*`）与异动解析端点
（`/action/*`）是**两套独立日额度**。本层：
1. 按端点计数落地（`jiuyan_api_calls`，`_id={fetchDate}`）；
2. 开工前算额度（`JIUYAN_THEME_DAILY_CALL_BUDGET`），超出即跳过并 fail-visible；
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

# 每源一次调用的标识（额度计数键）——v4 换源后只剩产业树
SOURCE_INDUSTRY = "ai_industry"
ALL_SOURCES = (SOURCE_INDUSTRY,)
# 每日调用护栏（防连发被限流；**不是**日额度上限——实测 errCode=9 是短时限流，静默 ~20 分钟后恢复）。
# v4 换源后每日调度只调 1 次（收盘后正文刷新）；预算 12 只防失控，不阻碍重试。
DEFAULT_DAILY_CALL_BUDGET = 12
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
                 date: str | None = None, budget: int | None = None) -> dict:
    """拉取 + 落库产业树正文（v4 换源后唯一源）。返回结构化统计；失败进 `degraded`。

    `fetch_date` = 采集日（写 contentChangedDate/firstSeenDate）；`date` = 认证铸造用的参考日
    （韭研 token 铸造要一个异动日期，默认取交易日）。
    `budget` = 当日题材端点调用预算（缺省读 env）。
    """
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()

    budget = daily_call_budget() if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    planned = len(ALL_SOURCES)
    skipped_by_budget: list[str] = []
    if used + planned > budget:
        skipped_by_budget = [SOURCE_INDUSTRY]
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
                             "sources": list(ALL_SOURCES),
                             "skippedByBudget": skipped_by_budget,
                             "callsUsedToday": used, "callsThisRun": planned,
                             "budget": budget}

    # 调用计数（失败同样消耗服务端额度）；串行 + 限流退避重试（2026-10-20 实测：
    # 连发触发 errCode=9，静默 ~20 分钟后恢复）。
    def _fetch(source: str, fn: Any, **fkw: Any) -> dict | None:
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

    industry = (None if SOURCE_INDUSTRY in skipped_by_budget
                else _fetch(SOURCE_INDUSTRY, F.fetch_ai_industry, **kw))
    if industry is None:
        stats["sources"] = []
        stats["callsThisRun"] = 0
    industry_stats = {"written": 0, "contentChanged": 0, "withContent": 0}
    if not dry_run and (industry or {}).get("nodes"):
        industry_stats = S.save_industry_nodes(db, fetch_date=fetch_date,
                                               nodes=industry["nodes"])

    if industry is not None:
        if not industry.get("ok"):
            degraded.append(f"{SOURCE_INDUSTRY}: {industry.get('error')}")
        # 空载荷也是异常，不得当“成功无数据”（AGENTS §4.0）：实测服务端间歇限流期间会返回
        # `errCode=0` 但空列表（2026-10-20 15:45 调度采集 industry 就是 fetched=0 而 ok=True，
        # 把限流伪装成“今天没题材”——这正是要禁止的静默降级）。
        elif not (industry.get("nodes") or []):
            empty_sources.append(SOURCE_INDUSTRY)
            degraded.append(f"{SOURCE_INDUSTRY}: 空载荷（errCode=0 但 0 节点，疑服务端限流/降级）")

    stats["industry"] = {**industry_stats, "fetched": len((industry or {}).get("nodes") or [])}
    stats["degraded"] = degraded
    stats["emptySources"] = empty_sources
    stats["ok"] = len(degraded) < max(1, len(ALL_SOURCES))   # 所有源都失败才算失败（§4.0）
    stats["callsUsedTodayAfter"] = S.calls_recorded(db, fetch_date)
    if dry_run:
        stats["dryRun"] = True
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="韭研题材语料采集（产业树正文刷新；事件层已换源开盘啦）")
    ap.add_argument("--date", default=None, help="采集日（默认今天，YYYY-MM-DD）")
    ap.add_argument("--dry-run", action="store_true", help="不写业务库，只打印统计（仍计调用额度）")
    ap.add_argument("--budget", type=int, default=None,
                    help=f"当日题材端点调用预算（缺省 env/常量={DEFAULT_DAILY_CALL_BUDGET}）")
    ap.add_argument("--stock-tree", action="store_true",
                    help="全成分归档模式（V3-1）：拉 stock-tree 落 jiuyan_industry_stocks，断点续拉")
    ap.add_argument("--codes", default=None,
                    help="（--stock-tree）仅拉这些一级 code，逗号分隔；缺省=全量待拉清单")
    ap.add_argument("--force", action="store_true",
                    help="（--stock-tree）忽略当日断点（重拉当日已成功板块）")
    ap.add_argument("--json", default=None, help="统计写入该文件")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.stock_tree:
        codes = ([c.strip() for c in args.codes.split(",") if c.strip()]
                 if args.codes else None)
        result = collect_stock_tree(codes=codes, fetch_date=args.date,
                                    force=args.force, dry_run=args.dry_run,
                                    date=args.date, budget=args.budget)
    else:
        result = collect_once(fetch_date=args.date, dry_run=args.dry_run,
                              budget=args.budget)
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    print(text)
    if args.json:
        from pathlib import Path
        Path(args.json).write_text(text, encoding="utf-8")
    return 0 if result.get("ok") else 1


def collect_stock_tree(*, codes: list[str] | None = None, fetch_date: str | None = None,
                       force: bool = False, dry_run: bool = False,
                       date: str | None = None, budget: int | None = None) -> dict:
    """全成分归档（V3-1，2026-10-25 用户三拍板：全量 108 首拉/周频全量/全量纳入+披露强度）。

    - 待拉清单 = level1 节点 − 当日已成功（断点续拉；--force 重拉当日）；
    - 预算：默认日预算 12 会挡 108 次全量——首拉/周刷须 `--budget 120` 或 env
      `JIUYAN_STOCKTREE_WEEKLY_BUDGET`（调度挂点用后者，默认 120）；
    - 限流护栏同 collect_once：串行 20s 间隔 + errCode=9 退避 60s 重试 1 次；
    - 单板块失败只降级该板块（failed 列表透出），其余继续（§4.0）。
    """
    fetch_date = fetch_date or datetime.now().strftime("%Y-%m-%d")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()

    if codes is not None:
        pending = [{"code": c, "name": ""} for c in codes]
    else:
        pending = ([] if force else
                   S.pending_industry_stock_codes(db, fetch_date))
        if force:
            pending = list(db[S.COLLECTION_INDUSTRY].find(
                {"level": 1}, {"code": 1, "name": 1}).sort("code", 1))
            pending = [{"code": str(n["code"]), "name": str(n.get("name") or "")}
                       for n in pending]

    default_budget = max(daily_call_budget(), _stocktree_weekly_budget())
    budget = default_budget if budget is None else int(budget)
    used = S.calls_recorded(db, fetch_date)
    stats: dict[str, Any] = {"ok": True, "fetchDate": fetch_date, "mode": "stock_tree",
                             "pending": len(pending), "budget": budget,
                             "callsUsedToday": used}
    if not pending:
        stats["note"] = "0 待拉（当日已全部成功或产业树空）"
        return stats
    if used + len(pending) > budget:
        stats.update({"ok": False, "skippedByBudget": ["industry_stock_tree"],
                      "reason": f"当日已用 {used} + 待拉 {len(pending)} > 预算 {budget}"})
        return stats

    auth = jiuyan_auth.resolve_auth(date=date or fetch_date)
    if not auth.get("ok"):
        return {**stats, "ok": False, "error": auth.get("error"),
                "authFailed": bool(auth.get("authFailed")), "degraded": ["auth"]}
    kw = {"session_cookie": auth["session"], "token": auth["token"],
          "timestamp": auth["timestamp"]}

    written = changed = 0
    failed: list[dict] = []
    # token 时效 < 全量挂跑时长（2026-10-25 首拉实测：~25 分钟/60+ 次调用后
    # errCode=110 连串）→ authFailed 时 force_refresh 重铸自愈续跑（限次防死循环）
    auth_refreshes = 0
    MAX_AUTH_REFRESHES = 5
    for i, item in enumerate(pending, 1):
        code, name = item["code"], item.get("name") or ""
        retries = 0
        while True:
            time.sleep(INTER_CALL_DELAY_SECONDS)
            S.record_api_calls(db, fetch_date, ("industry_stock_tree",))
            res = F.fetch_industry_stock_tree(code, **kw)
            if not res.get("rateLimited") or retries >= RATE_LIMIT_MAX_RETRIES:
                break
            retries += 1
            logger.warning("stock-tree[%s] 被限流（errCode=9），%.0fs 后重试 %d/%d",
                           code, RATE_LIMIT_RETRY_SLEEP_SECONDS, retries,
                           RATE_LIMIT_MAX_RETRIES)
            time.sleep(RATE_LIMIT_RETRY_SLEEP_SECONDS)
        if res.get("authFailed") and auth_refreshes < MAX_AUTH_REFRESHES:
            auth_refreshes += 1
            logger.warning("stock-tree[%s] 认证失效（errCode=110），重铸 token %d/%d",
                           code, auth_refreshes, MAX_AUTH_REFRESHES)
            fresh = jiuyan_auth.resolve_auth(date=date or fetch_date, force_refresh=True)
            if fresh.get("ok"):
                kw = {"session_cookie": fresh["session"], "token": fresh["token"],
                      "timestamp": fresh["timestamp"]}
                S.record_api_calls(db, fetch_date, ("industry_stock_tree",))
                res = F.fetch_industry_stock_tree(code, **kw)
        if not res.get("ok"):
            failed.append({"code": code, "name": name, "error": res.get("error")})
            logger.warning("[%d/%d] %s %s 失败: %s", i, len(pending), code, name,
                           res.get("error"))
            continue
        industry = res.get("industry") or {}
        stocks = industry.get("stocks") or []
        if not stocks:
            # 空成分按失败记（不落 stockN=0 假成功，防断点续拉把空档当已成功跳过）
            failed.append({"code": code, "name": name, "error": "空成分（0 股）"})
            logger.warning("[%d/%d] %s %s 空成分", i, len(pending), code, name)
            continue
        if not dry_run:
            st = S.save_industry_stocks(db, code=code,
                                        name=name or industry.get("name") or "",
                                        batch_date=fetch_date, stocks=stocks)
            written += st["written"]
            changed += 1 if st["changed"] else 0
        logger.info("[%d/%d] %s %s → %d 只%s", i, len(pending), code, name,
                    len(stocks), "（成分变更）" if not dry_run and st["changed"] else "")
    stats.update({"written": written, "changed": changed, "failed": failed,
                  "failedN": len(failed),
                  "ok": len(failed) < len(pending),   # 全失败才算失败（§4.0）
                  "callsUsedTodayAfter": S.calls_recorded(db, fetch_date)})
    if dry_run:
        stats["dryRun"] = True
    return stats


def _stocktree_weekly_budget() -> int:
    """周刷预算（调度挂点默认 120 = 108 全量 + 产业树 1 + 重试余量；env 可覆盖）。"""
    try:
        return max(1, int(os.environ.get("JIUYAN_STOCKTREE_WEEKLY_BUDGET", 120)))
    except ValueError:
        return 120


if __name__ == "__main__":
    raise SystemExit(main())
