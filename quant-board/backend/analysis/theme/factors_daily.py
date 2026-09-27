"""题材日频因子装配（设计 §5.1 D1 拥挤度分位数生产接线，2026-09-27）。

crowding_percentile.py 提供分位数原语（Phase 2 研究侧）；本模块把
"逐日原料 → trailing 分位 → 落库行"装配为纯函数，供
services/theme/daily_factors_service 编排落库与缓存。

口径（与 Phase 2 runner 固化语义一致）：
  - 一股多题材重复计入是白名单既定口径（份额独立、全题材份额和可 >1）；
  - 零覆盖题材（成员全不在当日采集池）当日不可观测 → 不产出行、不入分位序列；
  - 分位窗口观测数 < min_periods → None + insufficient_history 标记（不伪造中性值）。

fail-visible：缺日/缺成员/缺原料全部以 None + qualityFlags 显式落库，不伪造、不中断；
仅当输入无任何 stock rows（全源无数据）时返回 no_stock_rows 且不产出任何行。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.analysis.theme.crowding_percentile import (
    MIN_PERIODS_DEFAULT,
    WINDOW_DEFAULT,
    combine_equal_weight,
    rolling_percentile,
    theme_amount_share,
    theme_turnover_mean,
)

FACTOR_VERSION = "theme-daily-factors-v1"

_FACTOR_KEYS = ("amountShare", "turnoverMean", "amountSharePct", "turnoverMeanPct", "crowdingPercentile")


def build_daily_factor_rows(
    stock_daily: dict[str, dict[str, dict[str, float | None]]],
    members: dict[str, set[str]],
    *,
    target_dates: list[str] | None = None,
    theme_names: dict[str, str] | None = None,
    window: int = WINDOW_DEFAULT,
    min_periods: int = MIN_PERIODS_DEFAULT,
) -> tuple[list[dict[str, Any]], list[str]]:
    """装配日频因子行。

    输入：
      stock_daily  {date: {"amount": {code: v}, "turnover": {code: v|None}}}（收盘槽横截面）
      members      {themeId: set(stockCode)}（theme_stock_mappings 平铺）
      target_dates 缺省 = 全部有 stock rows 的日期；不在 stock_daily 的目标日打标跳过
    返回：(rows, quality_flags)，rows 按 (tradingDate, themeId) 升序。
    """
    if not stock_daily:
        return [], ["no_stock_rows"]

    names = theme_names or {}
    days = sorted(stock_daily)
    targets = sorted(set(target_dates)) if target_dates is not None else days
    unknown_targets = [d for d in targets if d not in stock_daily]
    known_targets = [d for d in targets if d in stock_daily]

    # 逐题材原料序列（仅可观测日入序列，Phase 2 口径）
    shares_by_theme: dict[str, dict[str, float]] = defaultdict(dict)
    turnover_by_theme: dict[str, dict[str, float]] = defaultdict(dict)
    observable_by_day: dict[str, set[str]] = {}
    for d in days:
        amounts = stock_daily[d].get("amount") or {}
        turnovers = stock_daily[d].get("turnover") or {}
        amount_keys = set(amounts)
        turnover_keys = {code for code, v in turnovers.items() if v is not None}
        observable: set[str] = set()
        if amounts:
            # pool_total <= 0（当日全零成交额等）→ theme_amount_share 返回 {}：
            # 该日 amount 不可观测，不产原料值（fail-visible，不伪造 0 份额）
            shares = theme_amount_share({c: v for c, v in amounts.items() if v is not None}, members)
            for tid, codes in members.items():
                if codes & amount_keys and tid in shares:
                    shares_by_theme[tid][d] = shares[tid]
                    observable.add(tid)
        if turnovers:
            tmeans = theme_turnover_mean(turnovers, members)
            for tid, tmean in tmeans.items():
                if tmean is not None and members[tid] & turnover_keys:
                    turnover_by_theme[tid][d] = tmean
                    observable.add(tid)
        observable_by_day[d] = observable

    pct_share = {
        tid: rolling_percentile(seq, window=window, min_periods=min_periods)
        for tid, seq in shares_by_theme.items()
    }
    pct_turnover = {
        tid: rolling_percentile(seq, window=window, min_periods=min_periods)
        for tid, seq in turnover_by_theme.items()
    }

    flags: list[str] = []
    if unknown_targets:
        flags.extend(f"target_date_missing:{d}" for d in unknown_targets)
    zero_coverage_days = sum(1 for d in known_targets for tid in members if tid not in observable_by_day[d])
    if zero_coverage_days:
        flags.append(f"zero_coverage_theme_days:{zero_coverage_days}")

    rows: list[dict[str, Any]] = []
    insufficient_rows = 0
    for d in known_targets:
        amounts = stock_daily[d].get("amount") or {}
        turnovers = stock_daily[d].get("turnover") or {}
        amount_keys = set(amounts)
        turnover_keys = {code for code, v in turnovers.items() if v is not None}
        for tid in sorted(observable_by_day[d]):
            share = shares_by_theme[tid].get(d)
            tmean = turnover_by_theme[tid].get(d)
            share_pct = pct_share.get(tid, {}).get(d)
            turnover_pct = pct_turnover.get(tid, {}).get(d)
            bc = combine_equal_weight(
                {d: share_pct},
                {d: turnover_pct},
            )[d]
            row_flags: list[str] = []
            if share_pct is None and turnover_pct is None:
                row_flags.append("insufficient_history")
            if tid not in shares_by_theme or d not in shares_by_theme[tid]:
                row_flags.append("amount_unobservable")
            if tid not in turnover_by_theme or d not in turnover_by_theme[tid]:
                row_flags.append("turnover_unobservable")
            if share_pct is None and (amount_keys & members[tid]):
                # 当日有成员行情但分位仍缺 → 历史不足（与 insufficient_history 合并语义）
                if "insufficient_history" not in row_flags:
                    row_flags.append("insufficient_history")
            if "insufficient_history" in row_flags:
                insufficient_rows += 1
            rows.append({
                "tradingDate": d,
                "themeId": tid,
                "themeName": str(names.get(tid) or ""),
                "factorVersion": FACTOR_VERSION,
                "factors": {
                    "amountShare": share,
                    "turnoverMean": tmean,
                    "amountSharePct": share_pct,
                    "turnoverMeanPct": turnover_pct,
                    "crowdingPercentile": bc,
                },
                "qualityFlags": row_flags,
            })
    if insufficient_rows:
        flags.append(f"insufficient_history_rows:{insufficient_rows}")
    return rows, flags
