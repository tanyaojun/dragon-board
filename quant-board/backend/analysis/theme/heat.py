from __future__ import annotations

import math
from typing import Any


FACTOR_VERSION = "theme-market-v1"


def _number(value: object, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _is_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score(value: float) -> float:
    return round(_clamp(value), 2)


def _theme_codes(theme: dict[str, object]) -> list[str]:
    values = theme.get("stocks")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _breadth_score(changes: list[float]) -> tuple[float, int]:
    if not changes:
        return 0.0, 0
    count = len(changes)
    up_rate = sum(change > 0 for change in changes) / count
    strong_rate = sum(change >= 5 for change in changes) / count
    zt_count = sum(change >= 9.5 for change in changes)
    limit_up_rate = zt_count / count
    return _score(up_rate * 45 + strong_rate * 30 + limit_up_rate * 25), zt_count


def _fund_score(
    codes: list[str],
    quotes: dict[str, dict[str, object]],
    funds: dict[str, dict[str, object]],
) -> tuple[float | None, int, float | None]:
    covered_codes = [
        code
        for code in codes
        if isinstance(funds.get(code), dict) and _is_number(funds[code].get("mainNetInflow"))
    ]
    if not covered_codes:
        return None, len(covered_codes), None

    main_net_inflow = sum(_number(funds[code].get("mainNetInflow")) for code in covered_codes)
    amount = sum(max(0.0, _number(quotes.get(code, {}).get("amount"))) for code in covered_codes)
    flow_ratio = main_net_inflow / amount if amount > 0 else 0.0
    flow_ratio_score = _clamp(50 + _clamp(flow_ratio, -0.10, 0.10) * 500)
    positive_rate = (
        sum(_number(funds[code].get("mainNetInflow")) > 0 for code in covered_codes)
        / len(covered_codes)
    )
    return _score(flow_ratio_score * 0.70 + positive_rate * 100 * 0.30), len(covered_codes), main_net_inflow


def _correlation_score(changes: list[float]) -> float:
    directions = [change for change in changes if change != 0]
    if not directions:
        return 0.0
    positive = sum(change > 0 for change in directions)
    negative = sum(change < 0 for change in directions)
    return _score(max(positive, negative) / len(directions) * 100)


def _leadership_score(rows: list[dict[str, object]], zt_count: int) -> tuple[float, int]:
    if not rows:
        return 0.0, 0
    max_board_height = max(
        (
            max(
                _number(row.get("boardHeight")),
                _number(row.get("continuousDays")),
                _number(row.get("highDays")),
            )
            for row in rows
        ),
        default=0.0,
    )
    leader_count = sum(
        bool(row.get("hotlistLeader"))
        or "龙" in str(row.get("leadStatus") or "")
        or str(row.get("themeRole") or "") == "leader"
        for row in rows
    )
    limit_up_rate = zt_count / len(rows)
    hotlist_leader_rate = leader_count / len(rows)
    return (
        _score(
            limit_up_rate * 50
            + min(max_board_height * 6, 30)
            + min(hotlist_leader_rate * 100, 20)
        ),
        leader_count,
    )


def _crowding_risk(weighted: float, rows: list[dict[str, object]], changes: list[float]) -> tuple[float, float]:
    volume_ratios = [min(max(_number(row.get("volumeRatio")), 0.0), 10.0) for row in rows]
    avg_capped_volume_ratio = sum(volume_ratios) / len(volume_ratios) if volume_ratios else 0.0
    hot_stock_rate = sum(change >= 7 for change in changes) / len(changes) if changes else 0.0
    risk = (
        (24 if weighted >= 85 else 0)
        + max(0.0, avg_capped_volume_ratio - 2.5) * 12
        + hot_stock_rate * 28
    )
    return _score(risk), round(avg_capped_volume_ratio, 2)


def _trimmed_mean_change(changes: list[float]) -> float:
    values = sorted(_clamp(change, -20, 20) for change in changes)
    if len(values) >= 10:
        trim_count = max(1, math.floor(len(values) * 0.05))
        values = values[trim_count:-trim_count]
    return round(sum(values) / len(values), 2) if values else 0.0


def _compute_theme_factor(
    *,
    theme: dict[str, object],
    quotes: dict[str, dict[str, object]],
    funds: dict[str, dict[str, object]],
    previous_factor: dict[str, object] | None,
    computed_at: int,
) -> dict[str, object]:
    theme_id = str(theme.get("id") or "")
    theme_name = str(theme.get("name") or theme_id)
    codes = _theme_codes(theme)
    rows = [quotes[code] for code in codes if isinstance(quotes.get(code), dict) and _is_number(quotes[code].get("change"))]
    changes = [_number(row.get("change")) for row in rows]
    quote_coverage = len(rows) / len(codes) if codes else 0.0
    breadth_score, zt_count = _breadth_score(changes)
    fund_score, fund_covered_count, main_net_inflow = _fund_score(codes, quotes, funds)
    fund_coverage = fund_covered_count / len(codes) if codes else 0.0
    correlation_score = _correlation_score(changes)
    leadership_score, leader_count = _leadership_score(rows, zt_count)

    if fund_score is None:
        weighted = (
            breadth_score * 0.36 + leadership_score * 0.28 + correlation_score * 0.14
        ) / 0.78
    else:
        weighted = (
            breadth_score * 0.36
            + fund_score * 0.22
            + leadership_score * 0.28
            + correlation_score * 0.14
        )

    crowding_risk, average_volume_ratio = _crowding_risk(weighted, rows, changes)
    consecutive_hot_buckets = int(
        max(0.0, _number((previous_factor or {}).get("consecutiveHotBuckets")))
    )
    persistence_score = _score(min(consecutive_hot_buckets * 20, 100))
    heat_score: int | None = int(
        _clamp(round(weighted + persistence_score * 0.08 - min(crowding_risk * 0.14, 14)))
    )
    trimmed_mean_change = _trimmed_mean_change(changes)
    previous_heat_score = (
        _number(previous_factor.get("heatScore"), float(heat_score))
        if previous_factor and _is_number(previous_factor.get("heatScore"))
        else float(heat_score)
    )
    momentum_score = int(
        _clamp(round(50 + trimmed_mean_change * 8 + (float(heat_score) - previous_heat_score) * 1.5))
    )

    quality_flags: list[str] = []
    if not theme_id:
        quality_flags.append("mapping_missing")
    if not codes:
        quality_flags.append("empty_theme")
    elif len(rows) < 2:
        quality_flags.append("low_sample")
    if any(
        isinstance(quotes.get(code), dict)
        and any(
            value is not None and not _is_number(value)
            for value in (
                quotes[code].get("change"),
                quotes[code].get("amount"),
                quotes[code].get("volumeRatio"),
            )
        )
        for code in codes
    ):
        quality_flags.append("invalid_number")
    if 0.5 <= quote_coverage < 0.8:
        quality_flags.append("theme_quote_coverage_low")
    if 0 < fund_coverage < 0.8:
        quality_flags.append("fund_flow_partial")
    elif fund_coverage == 0:
        quality_flags.append("fund_flow_unavailable")
    if previous_factor is None:
        quality_flags.append("persistence_history_insufficient")

    rank_eligible = quote_coverage >= 0.5
    if not rank_eligible:
        heat_score = None
        momentum_score = 0

    return {
        "themeId": theme_id,
        "themeName": theme_name,
        "rank": 0,
        "rankEligible": rank_eligible,
        "heatScore": heat_score,
        "momentumScore": momentum_score,
        "breadthScore": breadth_score,
        "fundScore": fund_score,
        "leadershipScore": leadership_score,
        "correlationScore": correlation_score,
        "crowdingRisk": crowding_risk,
        "persistenceScore": persistence_score,
        "stockCount": len(codes),
        "quoteCoveredCount": len(rows),
        "fundCoveredCount": fund_covered_count,
        "ztCount": zt_count,
        "leaderCount": leader_count,
        "mainNetInflow": main_net_inflow,
        "volumeRatio": average_volume_ratio,
        "degraded": bool(quality_flags),
        "qualityFlags": quality_flags,
        "computedAt": computed_at,
        "metadata": {
            "quoteCoverage": round(quote_coverage, 4),
            "fundCoverage": round(fund_coverage, 4),
            "trimmedMeanChange": trimmed_mean_change,
            "consecutiveHotBuckets": consecutive_hot_buckets,
        },
    }


def _rank_and_summarize(
    *,
    factors: list[dict[str, object]],
    themes: list[dict[str, object]],
    quotes: dict[str, dict[str, object]],
    funds: dict[str, dict[str, object]],
    computed_at: int,
    mapping_version: str,
) -> dict[str, object]:
    del funds
    stock_codes = list(dict.fromkeys(code for theme in themes for code in _theme_codes(theme)))
    returned_count = sum(
        isinstance(quotes.get(code), dict) and _is_number(quotes[code].get("change"))
        for code in stock_codes
    )
    quote_coverage = returned_count / len(stock_codes) if stock_codes else 0.0
    global_flags = ["quote_coverage_partial"] if 0.85 <= quote_coverage < 0.95 else []
    ok = quote_coverage >= 0.85

    if not ok:
        for factor in factors:
            factor["rank"] = 0
            factor["rankEligible"] = False
    else:
        eligible = [factor for factor in factors if factor["rankEligible"]]
        eligible.sort(
            key=lambda factor: (
                -_number(factor.get("heatScore"), -1),
                -_number(factor.get("momentumScore")),
                str(factor.get("themeName") or ""),
            )
        )
        for rank, factor in enumerate(eligible, start=1):
            factor["rank"] = rank
        ineligible = sorted(
            (factor for factor in factors if not factor["rankEligible"]),
            key=lambda factor: str(factor.get("themeName") or ""),
        )
        factors = eligible + ineligible

    quality: dict[str, object] = {
        "quoteCoverage": round(quote_coverage, 4),
        "requestedCount": len(stock_codes),
        "returnedCount": returned_count,
        "qualityFlags": global_flags,
    }
    if not ok:
        quality["errorCode"] = "quote_coverage_blocked"

    return {
        "ok": ok,
        "computedAt": computed_at,
        "factorVersion": FACTOR_VERSION,
        "mappingVersion": mapping_version,
        "factors": factors,
        "quality": quality,
    }


def compute_theme_heat(
    *,
    themes: list[dict[str, object]],
    quotes: dict[str, dict[str, object]],
    funds: dict[str, dict[str, object]],
    previous_factors: dict[str, dict[str, object]],
    computed_at: int,
    mapping_version: str,
) -> dict[str, object]:
    factors = [
        _compute_theme_factor(
            theme=theme,
            quotes=quotes,
            funds=funds,
            previous_factor=previous_factors.get(str(theme.get("id") or "")),
            computed_at=computed_at,
        )
        for theme in themes
    ]
    return _rank_and_summarize(
        factors=factors,
        themes=themes,
        quotes=quotes,
        funds=funds,
        computed_at=computed_at,
        mapping_version=mapping_version,
    )
