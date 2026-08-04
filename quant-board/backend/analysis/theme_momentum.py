# quant-board/backend/analysis/theme_momentum.py
"""题材动量（板块共振）纯计算。

从 snapshot sector rows（entityType=hot_theme）的题材因子序列计算多帧相对动量，
并为每股生成题材暴露与共振调节。本模块不访问 HTTP/MongoDB/缓存，输出确定性结果。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

# 固定参数（与个股共振 analyze_rank_resonance 对齐；不做参数搜索）
THEME_SHORT_WINDOW_BARS = 3
THEME_MID_WINDOW_BARS = 8
THEME_PATH_WINDOW_BARS = 8
THEME_JUMP_DECAY_BARS = 3
THEME_JUMP_RANK_SLOTS = 3
THEME_JUMP_HEAT_DELTA = 15.0
THEME_CROSS_SECTION_MIN = 20
THEME_SERIES_MIN_BARS = THEME_MID_WINDOW_BARS + 1
THEME_MOMENTUM_VERSION = "theme-momentum-v1"

# 融合参数（固定常量，不做参数搜索）
THEME_ADJUSTMENT_SCALE = 0.3
THEME_ADJUSTMENT_MAX = 15.0
THEME_LIFECYCLE_BONUS = 5.0
THEME_LIFECYCLE_PENALTY_MAX = 10.0
THEME_LIFECYCLE_PENALTY_DENOM = 10.0

ROLE_WEIGHTS = {
    "leader": 1.0,
    "core": 0.82,
    "follower": 0.62,
    "independent": 0.38,
    "noise": 0.15,
}
LIFECYCLE_BOOST = {"mainline", "expansion", "ignition", "expanding", "emerging"}
LIFECYCLE_PENALTY = {"crowded", "divergence", "cooling", "reversal", "climax", "outflow"}
REVERSAL_LIFECYCLES = {"cooling", "outflow", "divergence", "climax"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _theme_id(theme: dict[str, Any]) -> str:
    return str(theme.get("themeId") or theme.get("entityKey") or theme.get("code") or "").strip()


def _theme_rank_eligible(theme: dict[str, Any]) -> bool:
    metadata = theme.get("metadata")
    if isinstance(metadata, dict) and metadata.get("rankEligible") is not None:
        return bool(metadata.get("rankEligible"))
    return bool(theme.get("rankEligible", True))


def _normalize_theme_name(value: Any) -> str:
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块", "技术", "产业", "经济", "行业", "主题"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _is_same_theme_name(left: Any, right: Any) -> bool:
    left_name = _normalize_theme_name(left)
    right_name = _normalize_theme_name(right)
    if not left_name or not right_name:
        return False
    if left_name == right_name:
        return True
    shorter, longer = sorted((left_name, right_name), key=len)
    return len(shorter) >= 3 and shorter in longer and len(shorter) / len(longer) >= 0.75


def build_theme_strength_series(
    frames: list[dict[str, Any]],
) -> dict[str, list[tuple[int, float, int | None]]]:
    """每题材按 (frame_index, heatScore, rank) 记录；仅 rankEligible 且 heatScore 有限。

    rank 缺失时记 None（题材 Jump 仍可用 heatScore 判定）。"""
    series: dict[str, list[tuple[int, float, int | None]]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for theme in frame.get("hotThemes") or []:
            if not isinstance(theme, dict):
                continue
            if str(theme.get("entityType") or "hot_theme") != "hot_theme":
                continue
            theme_id = _theme_id(theme)
            heat = _num(theme.get("heatScore"), math.nan)
            if not theme_id or not math.isfinite(heat) or not _theme_rank_eligible(theme):
                continue
            rank = theme.get("rank")
            try:
                rank_int = int(rank) if rank is not None else None
            except (TypeError, ValueError):
                rank_int = None
            series[theme_id].append((frame_index, heat, rank_int))
    return {theme_id: bars for theme_id, bars in series.items() if bars}


def _theme_momentum_for(
    theme_id: str,
    values: list[float],
    ranks: list[int | None],
    market_median: float | None,
    rotation_state: str,
) -> dict[str, Any]:
    last = len(values) - 1
    short_change = values[last] - values[last - THEME_SHORT_WINDOW_BARS]
    mid_change = values[last] - values[last - THEME_MID_WINDOW_BARS]
    relative_momentum = (
        _clamp((short_change - market_median) / 15.0, -1, 1)
        if market_median is not None
        else 0.0
    )
    acceleration = _clamp(
        (short_change - mid_change * THEME_SHORT_WINDOW_BARS / THEME_MID_WINDOW_BARS) / 15.0,
        -1,
        1,
    )
    path = values[-(THEME_PATH_WINDOW_BARS + 1):]
    changes = [path[index + 1] - path[index] for index in range(len(path) - 1)]
    path_direction = 1 if (short_change or mid_change) > 0 else -1 if (short_change or mid_change) < 0 else 0
    directional = [
        change
        for change in changes
        if path_direction != 0 and (1 if change > 0 else -1 if change < 0 else 0) == path_direction
    ]
    persistence = len(directional) / len(changes) if changes else 0.0
    switch_rate = 0.0
    if len(changes) > 1:
        signs = [1 if change > 0 else -1 if change < 0 else 0 for change in changes]
        switch_rate = sum(
            1
            for index in range(1, len(signs))
            if signs[index] != 0 and signs[index - 1] != 0 and signs[index] != signs[index - 1]
        ) / (len(signs) - 1)
    recent_peak = max(path)
    drawdown = max(0.0, recent_peak - values[last])
    reversal_penalty = _clamp(0.6 * switch_rate + 0.4 * drawdown / 20.0, 0, 1)
    if rotation_state in REVERSAL_LIFECYCLES:
        reversal_penalty = _clamp(reversal_penalty + 0.2, 0, 1)

    jump_index: int | None = None
    for index in range(last, max(0, last - 12), -1):
        heat_jump = values[index] - values[index - 1] >= THEME_JUMP_HEAT_DELTA
        rank_jump = (
            ranks[index] is not None
            and ranks[index - 1] is not None
            and int(ranks[index]) <= int(ranks[index - 1]) - THEME_JUMP_RANK_SLOTS
        )
        if heat_jump or rank_jump:
            jump_index = index
            break
    jump_freshness = (
        math.exp(-(last - jump_index) / THEME_JUMP_DECAY_BARS) if jump_index is not None else 0.0
    )

    direction_score = relative_momentum + acceleration + 0.2 * path_direction * persistence
    direction = "buy" if direction_score > 0.1 else "sell" if direction_score < -0.1 else "hold"
    directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
    directional_acceleration = -acceleration if direction == "sell" else acceleration
    raw_score = (
        0.35 * max(0.0, directional_momentum)
        + 0.25 * max(0.0, directional_acceleration)
        + 0.2 * persistence
        + 0.2 * jump_freshness
        - 0.2 * reversal_penalty
    )
    return {
        "themeId": theme_id,
        "status": "ok",
        "direction": direction,
        "score": round(100 * _clamp(raw_score, 0, 1)),
        "relativeMomentum": round(relative_momentum, 6),
        "acceleration": round(acceleration, 6),
        "persistence": round(persistence, 6),
        "jumpFreshness": round(jump_freshness, 6),
        "reversalPenalty": round(reversal_penalty, 6),
        "shortChange": round(short_change, 4),
        "midChange": round(mid_change, 4),
    }


def compute_theme_momentum_series(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """逐帧计算题材动量；返回 frames 列表（与输入等长）。"""
    series = build_theme_strength_series(frames)
    results: list[dict[str, Any]] = []
    for frame_index in range(len(frames)):
        prefix_by_theme: dict[str, tuple[list[float], list[int | None]]] = {}
        for theme_id, bars in series.items():
            prefix = [bar for bar in bars if bar[0] <= frame_index]
            if len(prefix) >= THEME_SERIES_MIN_BARS:
                prefix_by_theme[theme_id] = (
                    [bar[1] for bar in prefix],
                    [bar[2] for bar in prefix],
                )
        short_changes: list[float] = []
        for theme_id, (values, _ranks) in prefix_by_theme.items():
            if len(values) >= THEME_SHORT_WINDOW_BARS + 1:
                short_changes.append(values[-1] - values[-1 - THEME_SHORT_WINDOW_BARS])
        market_median = _median(short_changes)
        cross_section_ok = market_median is not None and len(short_changes) >= THEME_CROSS_SECTION_MIN
        rotation_by_theme: dict[str, str] = {}
        for theme in frames[frame_index].get("hotThemes") or []:
            if isinstance(theme, dict):
                rotation_by_theme[_theme_id(theme)] = str(theme.get("rotationState") or "neutral")
        themes_out: dict[str, dict[str, Any]] = {}
        for theme_id, (values, ranks) in prefix_by_theme.items():
            themes_out[theme_id] = _theme_momentum_for(
                theme_id,
                values,
                ranks,
                market_median if cross_section_ok else None,
                rotation_by_theme.get(theme_id, "neutral"),
            )
        results.append({
            "themes": themes_out,
            "marketThemeMedianShortChange": market_median,
            "themeSampleCount": len(short_changes),
            "crossSectionOk": cross_section_ok,
            "qualityFlags": [] if cross_section_ok else ["theme_cross_section_insufficient"],
        })
    return {"frames": results, "version": THEME_MOMENTUM_VERSION}


def _matches_theme(value: str, theme: dict[str, Any]) -> bool:
    if _theme_id(theme) == value:
        return True
    return _is_same_theme_name(value, str(theme.get("themeName") or theme.get("name") or ""))


def _theme_name(theme: dict[str, Any]) -> str:
    return str(theme.get("themeName") or theme.get("name") or _theme_id(theme))


def _role_for(stock: dict[str, Any], theme: dict[str, Any], matched_main_theme: bool) -> str:
    explicit = str(stock.get("themeRole") or "").strip().lower()
    # themeRole 是股票级字段，只在匹配题材就是 mainTheme（或股票仅属单一题材）时可信
    if explicit in ROLE_WEIGHTS and (matched_main_theme or len(stock.get("themes") or []) <= 1):
        return explicit
    if "龙" in str(stock.get("leadStatus") or ""):
        return "leader"
    heat = _num(theme.get("heatScore"))
    change = _num(stock.get("change"))
    if heat >= 70 and change >= 5:
        return "core"
    if heat >= 45 and change > 0:
        return "follower"
    if heat < 20 or change < -5:
        return "noise"
    return "independent"


def stock_theme_exposure(
    stock: dict[str, Any],
    frame_themes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """主题材选择：mainTheme 优先，未命中时取所属题材中 heatScore 最高者。

    无映射或均不匹配时返回 None。"""
    stock_theme_values = [str(item) for item in (stock.get("themes") or []) if str(item)]
    if not stock_theme_values:
        return None
    valid = [
        theme for theme in frame_themes
        if isinstance(theme, dict) and _theme_rank_eligible(theme)
    ]
    if not valid:
        return None

    main_theme_value = str(stock.get("mainTheme") or "").strip()
    primary: dict[str, Any] | None = None
    matched_main_theme = False
    if main_theme_value:
        for theme in valid:
            if _matches_theme(main_theme_value, theme):
                primary = theme
                matched_main_theme = True
                break
    if primary is None:
        candidates = [
            theme for theme in valid
            if any(_matches_theme(value, theme) for value in stock_theme_values)
        ]
        if not candidates:
            return None
        primary = max(candidates, key=lambda theme: _num(theme.get("heatScore"), -1.0))

    role = _role_for(stock, primary, matched_main_theme)
    role_weight = ROLE_WEIGHTS.get(role, 0.15)
    contribution = _num(stock.get("themeContribution"), role_weight * 60.0)
    crowding_raw = primary.get("crowdingRisk")
    crowding_risk: float | None = None
    if isinstance(crowding_raw, (int, float)):
        numeric = float(crowding_raw)
        crowding_risk = numeric if math.isfinite(numeric) else None
    return {
        "themeId": _theme_id(primary),
        "themeName": _theme_name(primary),
        "role": role,
        "roleWeight": role_weight,
        "themeContribution": round(contribution, 2),
        "heatScore": _num(primary.get("heatScore")),
        "rotationState": str(primary.get("rotationState") or "neutral"),
        "crowdingRisk": crowding_risk,
        "matchedMainTheme": matched_main_theme,
        "reasons": [f"theme:{_theme_id(primary)}"],
    }


def fuse_theme_resonance(
    base_resonance: dict[str, Any] | None,
    exposure: dict[str, Any] | None,
    frame_momentum: dict[str, Any] | None,
    hot_themes_fallback: bool = False,
) -> dict[str, Any]:
    """把题材动量并入个股共振。返回带 theme 子对象的共振结果。

    - 题材数据不足：theme.status=insufficient + reasons，baseScore 原样保留。
    - 有数据：score = clamp(base + adjustment + lifecycleBonus - lifecyclePenalty, 0, 100)，
      direction 不变，label 由调用方按新分数刷新。
    - resonance.baseScore 始终保留调节前分数，供审计与前端对比。"""
    fused = dict(base_resonance or {})
    theme_out: dict[str, Any] = {"status": "insufficient", "reasons": []}
    base_score = _num(fused.get("score"))
    fused["baseScore"] = round(base_score, 0)
    if not frame_momentum or not frame_momentum.get("crossSectionOk"):
        theme_out["reasons"].append("theme_cross_section_insufficient")
    elif exposure is None:
        theme_out["reasons"].append("theme_mapping_missing")
    else:
        momentum = (frame_momentum.get("themes") or {}).get(exposure["themeId"])
        if momentum is None or momentum.get("status") != "ok":
            theme_out["reasons"].append("theme_momentum_insufficient")
        else:
            adjustment = _clamp(
                (momentum["score"] - 50.0) * exposure["roleWeight"] * THEME_ADJUSTMENT_SCALE,
                -THEME_ADJUSTMENT_MAX,
                THEME_ADJUSTMENT_MAX,
            )
            lifecycle_bonus = 0.0
            lifecycle_penalty = 0.0
            extra_reasons: list[str] = (
                ["theme_hot_themes_fallback"] if hot_themes_fallback else []
            )
            if exposure["rotationState"] in LIFECYCLE_BOOST and exposure["role"] in {"leader", "core"}:
                lifecycle_bonus = THEME_LIFECYCLE_BONUS
            if exposure["rotationState"] in LIFECYCLE_PENALTY and exposure["role"] != "leader":
                if exposure.get("crowdingRisk") is None:
                    extra_reasons.append("crowding_risk_missing")
                else:
                    lifecycle_penalty = min(
                        THEME_LIFECYCLE_PENALTY_MAX,
                        _num(exposure.get("crowdingRisk")) / THEME_LIFECYCLE_PENALTY_DENOM,
                    )
            theme_out = {
                "status": "ok",
                "themeId": exposure["themeId"],
                "themeName": exposure["themeName"],
                "role": exposure["role"],
                "roleWeight": round(exposure["roleWeight"], 2),
                "themeMomentumScore": momentum["score"],
                "themeMomentumDirection": momentum["direction"],
                "themeLifecycle": exposure["rotationState"],
                "themeContribution": exposure["themeContribution"],
                "adjustment": round(adjustment + lifecycle_bonus - lifecycle_penalty, 2),
                "reasons": exposure["reasons"] + [f"题材动量 {momentum['score']}"] + extra_reasons,
            }
            fused["score"] = round(
                _clamp(base_score + adjustment + lifecycle_bonus - lifecycle_penalty, 0, 100),
                0,
            )
    fused["theme"] = theme_out
    return fused
