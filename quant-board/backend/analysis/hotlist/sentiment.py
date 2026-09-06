"""热榜情绪纯函数——TS HotListSentimentAnalyzer 的 Python 等价实现（唯一权威口径）。

移植源: src/services/hotlist/HotListSentimentAnalyzer.ts（golden 对齐基线见
quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json）。
纯函数：不做 I/O、不持有 db 句柄；缺失/NaN 按 fail-visible 输出标注，不伪造状态。
"""
from __future__ import annotations

import math
import re
from typing import Any

# TS: src/config/constants.ts LIMIT_UP_CONFIG
_LIMIT_THRESHOLDS = {"MAIN": 9.8, "GEM": 19.8, "STAR": 19.8, "NORTH": 29.8}
_CHANGE_TOLERANCE = 0.5

STATUS_LABELS = ["主升确认", "点火观察", "强资确认", "新入观察", "高位拥挤", "资金背离", "转弱预警", "样本不足"]
_YESTERDAY_STRONG_LABELS = {"主升确认", "点火观察", "强资确认"}


def to_number(value: Any) -> float:
    # TS: toNumber —— Number(value)，NaN→0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def normalize_code(value: Any) -> str:
    return str(value or "").strip()


def get_rank(stock: dict, fallback_index: int) -> int:
    # TS: getRank —— compRank ?? rank，>0 有效
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    return int(rank) if rank > 0 else fallback_index + 1


def sort_rows(rows: list[dict] | None) -> list[dict]:
    # TS: sortByRank —— 过滤无 code，按 rank 升序
    filtered = [row for row in (rows or []) if normalize_code(row.get("code"))]
    return sorted(filtered, key=lambda row: get_rank(row, 9999))


def get_trusted_volume_ratio(stock: dict) -> float:
    # TS: getTrustedVolumeRatio（VolumeRatioTrust.ts L1-12）逐分支对齐：
    # value 非有限或 <=0 → 0；meta 缺失（None/0/''）→ 原值直通（视为已收盘可信）；
    # meta 存在（含空 dict，TS 中空对象为 truthy）→ 仅 status=='fresh' 返回原值，否则 0
    value = to_number(stock.get("volumeRatio"))
    if value <= 0:
        return 0.0
    meta = stock.get("volumeRatioMeta")
    if not meta and not isinstance(meta, dict):
        return value
    status = meta.get("status") if isinstance(meta, dict) else None
    return value if status == "fresh" else 0.0


def limit_threshold(code: str) -> float:
    # TS: StockUtils.getLimitThreshold —— 688/689→STAR，30→GEM，43/8/92→NORTH，其余 MAIN；无 ST 特判
    normalized = str(code or "").strip()
    padded = normalized.zfill(6)
    if padded.startswith("688") or padded.startswith("689"):
        return _LIMIT_THRESHOLDS["STAR"]
    if padded.startswith("30"):
        return _LIMIT_THRESHOLDS["GEM"]
    if padded.startswith("43") or padded.startswith("8") or padded.startswith("92"):
        return _LIMIT_THRESHOLDS["NORTH"]
    return _LIMIT_THRESHOLDS["MAIN"]


def check_limit_status(change: float, code: str) -> dict:
    # TS: StockUtils.checkLimitStatus —— isAlmostLimitUp = change >= threshold.up - tolerance*3
    threshold = limit_threshold(code)
    tolerance = _CHANGE_TOLERANCE
    return {
        "isLimitUp": change >= threshold - tolerance,
        "isLimitDown": change <= -threshold + tolerance,
        "isAlmostLimitUp": change >= threshold - tolerance * 3,
        "isAlmostLimitDown": change <= -threshold + tolerance * 3,
        "threshold": {"up": threshold, "down": -threshold},
    }


def _entry_reason(stock: dict) -> str:
    # TS: classifyEntryReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitUp"]:
        return "limit_up"
    if to_number(stock.get("zlje")) > 0 or to_number(stock.get("zljzb")) > 0:
        return "strong_money"
    if get_trusted_volume_ratio(stock) > 2:
        return "new_high_volume"
    return "rank_surge"


def _exit_reason(stock: dict) -> str:
    # TS: classifyExitReason
    change = to_number(stock.get("change"))
    if check_limit_status(change, normalize_code(stock.get("code")))["isLimitDown"]:
        return "limit_down"
    if change < -3:
        return "weakening"
    return "rank_out_of_range"


def compute_turnover(today_rows: list[dict], yesterday_rows: list[dict]) -> dict:
    # TS: computeTurnover L291-320
    today = sort_rows(today_rows)
    yesterday = sort_rows(yesterday_rows)
    today_codes = {normalize_code(row.get("code")) for row in today}
    yesterday_codes = {normalize_code(row.get("code")) for row in yesterday}
    new_entries = [row for row in today if normalize_code(row.get("code")) not in yesterday_codes]
    eliminated = [row for row in yesterday if normalize_code(row.get("code")) not in today_codes]
    return {
        "previousPoolSize": len(yesterday),
        "currentPoolSize": len(today),
        "retainedFromYesterday": sum(1 for row in today if normalize_code(row.get("code")) in yesterday_codes),
        "newEntries": [normalize_code(row.get("code")) for row in new_entries],
        "eliminated": [normalize_code(row.get("code")) for row in eliminated],
        "newEntryDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "entryReason": _entry_reason(row),
            }
            for index, row in enumerate(new_entries)
        ],
        "eliminatedDetails": [
            {
                "code": normalize_code(row.get("code")),
                "name": str(row.get("name") or "").strip(),
                "rank": get_rank(row, index),
                "changePct": to_number(row.get("change")),
                "exitReason": _exit_reason(row),
            }
            for index, row in enumerate(eliminated)
        ],
    }


def _parse_board_height_text(value: Any) -> int:
    # TS: parseBoardHeightText —— "首板"→1，正则 (\d+)\s*(?:连?板|天|日)?
    raw = str(value or "").strip()
    if not raw:
        return 0
    if "首板" in raw:
        return 1
    match = re.search(r"(\d+)\s*(?:连?板|天|日)?", raw)
    return int(to_number(match.group(1))) if match else 0


def _raw_board_height(stock: dict) -> int:
    # TS: getRawBoardHeight
    continuous_days = to_number(stock.get("continuousDays"))
    candidates = [
        to_number(stock.get("boardHeight")),
        to_number(stock.get("highDays")),
        continuous_days if continuous_days > 1 else 0,
        _parse_board_height_text(stock.get("lianbanStr")),
        _parse_board_height_text(stock.get("lianban")),
    ]
    return int(max(candidates))


def _has_limit_up_marker(stock: dict) -> bool:
    # TS: hasLimitUpMarker
    return bool(
        str(stock.get("firstZtTime") or "").strip()
        or str(stock.get("lastZtTime") or "").strip()
        or str(stock.get("first_limit_up_time") or "").strip()
        or str(stock.get("last_limit_up_time") or "").strip()
        or _raw_board_height(stock) > 0
    )


def _has_stock_zhaban_signal(stock: dict) -> bool:
    # TS: hasStockZhabanSignal
    return bool(
        stock.get("isZhaban") is True or stock.get("zhaban") is True
        or stock.get("openedLimit") is True or stock.get("limitOpened") is True
        or stock.get("failedLimitUp") is True or stock.get("isFailedLimitUp") is True
    )


def get_stock_limit_signal(stock: dict) -> dict:
    # TS: getStockLimitSignal L362-378
    code = normalize_code(stock.get("code"))
    status = check_limit_status(to_number(stock.get("change")), code)
    has_marker = _has_limit_up_marker(stock)
    board_height = max(_raw_board_height(stock), 1 if status["isLimitUp"] or has_marker else 0)
    return {
        "isLimitUp": status["isLimitUp"],
        "isAlmostLimitUp": status["isAlmostLimitUp"],
        "isLimitDown": status["isLimitDown"],
        "threshold": status["threshold"]["up"],
        "boardHeight": board_height,
        "isBoard2Plus": board_height >= 2,
        "hasLimitMarker": has_marker,
    }


def _has_limit_up_evidence(stock: dict) -> bool:
    signal = get_stock_limit_signal(stock)
    return signal["isLimitUp"] or signal["hasLimitMarker"]


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _resolve_sample_size(rows: list[dict], top_n: int | None) -> int:
    if top_n and top_n > 0:
        return min(len(rows), int(top_n))
    return len(rows)


def _calculate_hot_trin(up_count: int, down_count: int, up_turnover: float, down_turnover: float) -> float | None:
    # TS: calculateHotTrin —— 注意与旧 operations/_hot_trin 不同：turnover 取原值分桶
    if up_count <= 0 or down_count <= 0 or up_turnover <= 0 or down_turnover <= 0:
        return None
    return (up_count / down_count) / (up_turnover / down_turnover)


def build_day_metrics_from_sorted(sorted_rows: list[dict], top_n: int, trading_date: str | None = None) -> dict:
    # TS: buildDayMetricsFromSorted L458-546；状态计数经 resolve_stock_status（displayStatus 优先）。
    # statusSourceCounts 为后端超集约定（非 TS HotListDayMetrics 字段），Task 6 series 文档透出。
    top = sorted_rows[:top_n]
    status_counts = {label: 0 for label in STATUS_LABELS}
    status_source = {"displayStatus": 0, "fallback": 0}

    up_count = down_count = flat_count = 0
    up_turnover = down_turnover = total_turnover = 0.0
    main_net = super_net = change_sum = 0.0
    near_limit_up = high_gain = high_turnover = 0

    for stock in top:
        change = to_number(stock.get("change"))
        turnover = to_number(stock.get("turnover"))
        turnover_rate = to_number(stock.get("turnoverRate"))
        label = resolve_stock_status(stock, sorted_rows, status_source)
        status_counts[label] += 1
        total_turnover += turnover
        main_net += to_number(stock.get("zlje"))
        super_net += to_number(stock.get("cddje"))
        change_sum += change
        if change > 0:
            up_count += 1
            up_turnover += turnover
        elif change < 0:
            down_count += 1
            down_turnover += turnover
        else:
            flat_count += 1
        if get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            near_limit_up += 1
        if change >= 7:
            high_gain += 1
        if turnover_rate >= 10:
            high_turnover += 1

    total = len(top)
    status_shares = {label: _safe_divide(status_counts[label], total) for label in STATUS_LABELS}
    active = status_counts["主升确认"] + status_counts["点火观察"] + status_counts["强资确认"]
    opportunity = active + status_counts["新入观察"]
    risk = status_counts["资金背离"] + status_counts["转弱预警"]
    crowded = status_counts["高位拥挤"]
    result = {
        "tradingDate": trading_date,
        "total": len(sorted_rows),
        "topN": total,
        "upCount": up_count,
        "downCount": down_count,
        "flatCount": flat_count,
        "upRatio": _safe_divide(up_count, total),
        "downRatio": _safe_divide(down_count, total),
        "hotTrin": _calculate_hot_trin(up_count, down_count, up_turnover, down_turnover),
        "totalTurnover": total_turnover,
        "upTurnover": up_turnover,
        "downTurnover": down_turnover,
        "mainNetAmount": main_net,
        "superNetAmount": super_net,
        "avgChange": _safe_divide(change_sum, total),
        "nearLimitUpCount": near_limit_up,
        "highGainCount": high_gain,
        "highTurnoverCount": high_turnover,
        "statusCounts": status_counts,
        "statusShares": status_shares,
        "activeOpportunityCount": active,
        "activeOpportunityShare": _safe_divide(active, total),
        "opportunityCount": opportunity,
        "opportunityShare": _safe_divide(opportunity, total),
        "riskCount": risk,
        "riskShare": _safe_divide(risk, total),
        "crowdedCount": crowded,
        "crowdedShare": _safe_divide(crowded, total),
    }
    result["statusSourceCounts"] = status_source
    return result


def build_layer_metrics(rows: list[dict], trading_date: str | None = None) -> dict:
    # TS: buildLayerMetrics L731-739
    sorted_rows = sort_rows(rows)
    return {
        "top20": build_day_metrics_from_sorted(sorted_rows, 20, trading_date),
        "top50": build_day_metrics_from_sorted(sorted_rows, 50, trading_date),
        "top100": build_day_metrics_from_sorted(sorted_rows, 100, trading_date),
        "all": build_day_metrics_from_sorted(sorted_rows, len(sorted_rows), trading_date),
    }


def resolve_stock_status(stock: dict, context_rows: list[dict], status_source: dict | None = None) -> str:
    # TS: createStockStatusResolver L419-426 —— rankTrend displayStatus 优先，fallback 兜底。
    # 后端行由编排层注入 displayStatusLabel（snapshot_analysis.displayStatus 的规范 label）。
    label = stock.get("displayStatusLabel")
    if isinstance(label, str) and label in STATUS_LABELS:
        if status_source is not None:
            status_source["displayStatus"] += 1
        return label
    if status_source is not None:
        status_source["fallback"] += 1
    return fallback_status_label(stock)


def fallback_status_label(stock: dict) -> str:
    # TS: getFallbackHistoricalStatus L395-417
    change = to_number(stock.get("change"))
    rank = to_number(stock.get("compRank") if stock.get("compRank") is not None else stock.get("rank"))
    zlje = to_number(stock.get("zlje"))
    zljzb = to_number(stock.get("zljzb"))
    cddje = to_number(stock.get("cddje"))
    cddjzb = to_number(stock.get("cddjzb"))
    volume_ratio = get_trusted_volume_ratio(stock)
    turnover_rate = to_number(stock.get("turnoverRate"))
    strong_money = zlje > 0 and zljzb >= 8 and (cddje > 0 or cddjzb >= 3)
    money_weak = zlje < 0 or zljzb <= -8 or (cddje < 0 and cddjzb <= -3)
    high_position = change >= 8 or rank <= 30
    overheated = high_position and (volume_ratio >= 1.8 or turnover_rate >= 10)
    if money_weak and (rank <= 80 or change > 0):
        return "资金背离"
    if overheated:
        return "高位拥挤"
    if strong_money:
        return "强资确认"
    if change >= 3 or rank <= 100:
        return "新入观察"
    return "样本不足"


def _empty_ths_pools() -> dict:
    # TS: createEmptyThsPoolsEvidence
    return {
        "source": "ths-limitup-pools", "degraded": False, "errors": [],
        "poolCounts": {"one": 0, "two": 0, "three": 0, "four": 0, "high": 0, "failed": 0, "rushing": 0, "drawdown": 0},
        "failedCount": 0, "rushingCount": 0, "drawdownCount": 0,
        "drawdownRiskLabel": "涨停股回撤榜", "maxDrawdown": None, "avgDrawdown": None,
    }


def build_market_limit_evidence(market_data: dict | None) -> dict:
    # TS: buildMarketLimitEvidence L586-607
    if not market_data:
        return {
            "ztCount": 0, "zhabanCount": 0, "fengbanRate": 0,
            "board1": 0, "board2": 0, "board3": 0, "board4Plus": 0,
            "maxContinuousDays": 0, "thsPools": _empty_ths_pools(),
        }
    zhaban = market_data.get("zhaban") if isinstance(market_data.get("zhaban"), dict) else {}
    limit_data = market_data.get("limitData") if isinstance(market_data.get("limitData"), dict) else {}
    board1 = to_number(limit_data.get("yiban"))
    board2 = to_number(limit_data.get("erban"))
    board3 = to_number(limit_data.get("sanban"))
    board4_plus = to_number(limit_data.get("sibanPlus"))
    fallback_max_days = 4 if board4_plus > 0 else 3 if board3 > 0 else 2 if board2 > 0 else 1 if board1 > 0 else 0
    return {
        "ztCount": to_number(market_data.get("ztCount")),
        "zhabanCount": to_number(zhaban.get("count")),
        "fengbanRate": to_number(zhaban.get("fengbanRate")),
        "board1": board1, "board2": board2, "board3": board3, "board4Plus": board4_plus,
        "maxContinuousDays": to_number(market_data.get("maxContinuousDays")) or fallback_max_days,
        "thsPools": market_data.get("thsLimitUpPools") if isinstance(market_data.get("thsLimitUpPools"), dict) else _empty_ths_pools(),
    }


def build_limit_intersection_evidence(sorted_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildLimitIntersectionEvidence L613-643
    top20 = sorted_rows[:20]
    top50 = sorted_rows[:50]
    top100 = sorted_rows[: _resolve_sample_size(sorted_rows, top_n)]
    near = board2plus = 0
    max_height = 0
    zhaban = 0
    for stock in top100:
        signal = get_stock_limit_signal(stock)
        if signal["isAlmostLimitUp"]:
            near += 1
        if signal["isBoard2Plus"]:
            board2plus += 1
        max_height = max(max_height, signal["boardHeight"])
        if _has_stock_zhaban_signal(stock):
            zhaban += 1
    limit_up = sum(1 for stock in top100 if _has_limit_up_evidence(stock))
    size = len(top100)
    return {
        "top20LimitUpCount": sum(1 for stock in top20 if _has_limit_up_evidence(stock)),
        "top50LimitUpCount": sum(1 for stock in top50 if _has_limit_up_evidence(stock)),
        "top100LimitUpCount": limit_up,
        "top100LimitUpShare": _safe_divide(limit_up, size),
        "top100NearLimitUpCount": near,
        "top100Board2PlusCount": board2plus,
        "top100MaxBoardHeight": max_height,
        "top100ZhabanCount": zhaban,
        "top100ZhabanShare": _safe_divide(zhaban, size),
    }


def build_yesterday_hot_limit_evidence(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayHotLimitEvidence L656-712
    empty = {"count": 0, "retainedTop100Count": 0, "avgChange": None, "positiveRate": None, "weakeningRate": None, "failedOrWeakRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_limit_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if _has_limit_up_evidence(row) and normalize_code(row.get("code"))
    ]
    if not yesterday_limit_codes:
        return empty

    matched = retained = positive = weakening = failed_or_weak = 0
    change_sum = 0.0
    for code in yesterday_limit_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            failed_or_weak += 1
            continue
        change = to_number(stock.get("change"))
        today_label = resolve_stock_status(stock, today_rows)
        is_risk = today_label in ("资金背离", "转弱预警")
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or is_risk:
            weakening += 1
        if change <= 0 or is_risk or not get_stock_limit_signal(stock)["isAlmostLimitUp"]:
            failed_or_weak += 1
    return {
        "count": len(yesterday_limit_codes),
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningRate": _safe_divide(weakening, len(yesterday_limit_codes)),
        "failedOrWeakRate": _safe_divide(failed_or_weak, len(yesterday_limit_codes)),
    }


def build_limit_evidence(today_rows: list[dict], yesterday_rows: list[dict], top_n: int | None, market_data: dict | None) -> dict:
    # TS: buildLimitEvidence L714-725
    return {
        "market": build_market_limit_evidence(market_data),
        "intersection": build_limit_intersection_evidence(today_rows, top_n),
        "yesterdayHotLimit": build_yesterday_hot_limit_evidence(yesterday_rows, today_rows, top_n),
    }


def build_yesterday_strong_performance(yesterday_rows: list[dict], today_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildYesterdayStrongPerformance L754-814
    empty = {"count": 0, "matchedCount": 0, "retainedTop100Count": 0, "avgChange": None,
             "positiveCount": 0, "positiveRate": None, "weakeningCount": 0, "weakeningRate": None}
    if not yesterday_rows:
        return empty
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_rows, top_n)
    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    strong_codes = [
        normalize_code(row.get("code"))
        for row in yesterday_rows[:yesterday_size]
        if resolve_stock_status(row, yesterday_rows) in _YESTERDAY_STRONG_LABELS and normalize_code(row.get("code"))
    ]
    if not strong_codes:
        return empty

    matched = retained = positive = weakening = 0
    change_sum = 0.0
    for code in strong_codes:
        stock = today_by_code.get(code)
        if not stock:
            weakening += 1
            continue
        change = to_number(stock.get("change"))
        today_label = resolve_stock_status(stock, today_rows)
        matched += 1
        change_sum += change
        if change > 0:
            positive += 1
        if code in today_top_codes:
            retained += 1
        if change <= -2 or today_label in ("资金背离", "转弱预警"):
            weakening += 1
    return {
        "count": len(strong_codes),
        "matchedCount": matched,
        "retainedTop100Count": retained,
        "avgChange": _safe_divide(change_sum, matched) if matched else None,
        "positiveCount": positive,
        "positiveRate": _safe_divide(positive, matched) if matched else None,
        "weakeningCount": weakening,
        "weakeningRate": _safe_divide(weakening, len(strong_codes)),
    }


def build_comparison(stocks: list[dict], yesterday_rows: list[dict], day_before_rows: list[dict], top_n: int | None) -> dict:
    # TS: buildComparison L816-892
    today_rows = sort_rows(stocks)
    yesterday_sorted = sort_rows(yesterday_rows)
    day_before_sorted = sort_rows(day_before_rows)
    today_size = _resolve_sample_size(today_rows, top_n)
    yesterday_size = _resolve_sample_size(yesterday_sorted, top_n)
    day_before_size = _resolve_sample_size(day_before_sorted, top_n)

    today = build_day_metrics_from_sorted(today_rows, today_size)
    yesterday = build_day_metrics_from_sorted(yesterday_sorted, yesterday_size) if yesterday_sorted else None
    day_before = build_day_metrics_from_sorted(day_before_sorted, day_before_size) if day_before_sorted else None

    today_top_codes = {normalize_code(row.get("code")) for row in today_rows[:today_size]}
    yesterday_top_codes = {normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]}
    day_before_top_codes = {normalize_code(row.get("code")) for row in day_before_sorted[:day_before_size]}
    today_by_code = {normalize_code(row.get("code")): row for row in today_rows if normalize_code(row.get("code"))}

    retain_from_yesterday = len([code for code in today_top_codes if code in yesterday_top_codes])
    retain_from_day_before = len([code for code in today_top_codes if code in day_before_top_codes])
    new_top_codes = [code for code in today_top_codes if code not in yesterday_top_codes]
    new_strong = sum(
        1 for code in new_top_codes
        if code in today_by_code and resolve_stock_status(today_by_code[code], today_rows) == "强资确认"
    )
    yesterday_strong_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if resolve_stock_status(row, yesterday_sorted) == "强资确认" and normalize_code(row.get("code"))
    ]
    yesterday_crowded_codes = [
        normalize_code(row.get("code")) for row in yesterday_sorted[:yesterday_size]
        if resolve_stock_status(row, yesterday_sorted) == "高位拥挤" and normalize_code(row.get("code"))
    ]
    yesterday_strong_retain = (
        _safe_divide(len([code for code in yesterday_strong_codes if code in today_top_codes]), len(yesterday_strong_codes))
        if yesterday_strong_codes else None
    )
    yesterday_crowded_risk = sum(
        1 for code in yesterday_crowded_codes
        if code in today_by_code and resolve_stock_status(today_by_code[code], today_rows) in ("资金背离", "转弱预警")
    )
    return {
        "today": today,
        "yesterday": yesterday,
        "dayBefore": day_before,
        "totalChange1d": today["total"] - yesterday["total"] if yesterday else None,
        "totalChange2d": today["total"] - day_before["total"] if day_before else None,
        "top100RetainFromYesterday": retain_from_yesterday,
        "top100RetainFromDayBefore": retain_from_day_before,
        "top100RetainRateFromYesterday": _safe_divide(retain_from_yesterday, yesterday_size or today_size),
        "top100RetainRateFromDayBefore": _safe_divide(retain_from_day_before, day_before_size or today_size),
        "newTop100Count": len(new_top_codes),
        "newTop100StrongMoneyCount": new_strong,
        "yesterdayStrongRetainRate": yesterday_strong_retain,
        "yesterdayCrowdedRiskCount": yesterday_crowded_risk,
        "yesterdayStrongPerformance": build_yesterday_strong_performance(yesterday_sorted, today_rows, top_n),
    }
