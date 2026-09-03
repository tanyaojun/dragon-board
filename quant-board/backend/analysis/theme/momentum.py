# quant-board/backend/analysis/theme_momentum.py
"""题材动量（板块共振）纯计算。

从 snapshot sector rows（entityType=hot_theme）的题材因子序列计算多帧相对动量，
并为每股生成题材暴露与共振调节。本模块不访问 HTTP/MongoDB/缓存，输出确定性结果。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from backend.analysis.theme.heat_level import resolve_heat_level

# 固定参数（与个股共振 analyze_rank_resonance 对齐；不做参数搜索）
THEME_SHORT_WINDOW_BARS = 3
THEME_MID_WINDOW_BARS = 8
THEME_PATH_WINDOW_BARS = 8
THEME_JUMP_DECAY_BARS = 3
THEME_JUMP_RANK_SLOTS = 3
THEME_JUMP_HEAT_DELTA = 15.0
# heatLevel 相对分（0-100 rank 百分位）量纲参数（2026-09 落库迁移 design D3）：
# 消费对象从 heatScore 改为 heatLevel 序列，数值沿用旧 0-100 校准值，上线后按真实数据核定。
# 注意（design §5.5）：rank 百分位与 rank 变化同源，THEME_JUMP_HEAT_DELTA 信号与
# rank_jump 信号可能同帧重复触发，首日观察重叠率后再核定，本次不重校。
THEME_RELATIVE_MOMENTUM_SCALE = 15.0
THEME_DRAWDOWN_SCALE = 20.0
THEME_CROSS_SECTION_MIN = 20
THEME_SERIES_MIN_BARS = THEME_MID_WINDOW_BARS + 1
THEME_MOMENTUM_VERSION = "theme-momentum-v2"  # 2026-09 heatLevel 落库迁移：序列消费对象 heatScore → heatLevel

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
LIFECYCLE_BOOST = {"mainline", "expansion", "ignition", "emerging", "inflow"}
LIFECYCLE_PENALTY = {"crowded", "divergence", "cooling", "reversal", "outflow"}
REVERSAL_LIFECYCLES = {"cooling", "outflow", "divergence"}


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
    """每题材按 (frame_index, heatLevel, rank) 记录；仅 rankEligible 且热度相对分可用。

    热度读取统一走 heat_level.resolve_heat_level（design §4.2）：新落库行吃 heatLevel
    相对分；v1/未标记旧行 ≤100 heatScore 回退；v2 标记行不回退（M1 边界窗口消除）。"""
    series: dict[str, list[tuple[int, float, int | None]]] = defaultdict(list)
    for frame_index, frame in enumerate(frames):
        for theme in frame.get("hotThemes") or []:
            if not isinstance(theme, dict):
                continue
            if str(theme.get("entityType") or "hot_theme") != "hot_theme":
                continue
            theme_id = _theme_id(theme)
            heat = resolve_heat_level(theme)
            if not theme_id or heat is None or not _theme_rank_eligible(theme):
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
        _clamp((short_change - market_median) / THEME_RELATIVE_MOMENTUM_SCALE, -1, 1)
        if market_median is not None
        else 0.0
    )
    acceleration = _clamp(
        (
            (short_change - mid_change * THEME_SHORT_WINDOW_BARS / THEME_MID_WINDOW_BARS)
            / THEME_RELATIVE_MOMENTUM_SCALE
        ),
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
    reversal_penalty = _clamp(0.6 * switch_rate + 0.4 * drawdown / THEME_DRAWDOWN_SCALE, 0, 1)
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
    # 热度阈值（70/45/20）消费 heatLevel 相对分（design §4.2）：缺失（含 v2 行显式
    # None / 绝对值）不参与热度分层，只保留涨跌侧的 noise 判定。
    heat = resolve_heat_level(theme)
    change = _num(stock.get("change"))
    if heat is not None:
        if heat >= 70 and change >= 5:
            return "core"
        if heat >= 45 and change > 0:
            return "follower"
        if heat < 20:
            return "noise"
    if change < -5:
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

# ════════════ v2：独立第四维题材动量（日线主口径 + 槽位日内辅口径） ════════════
# 2026-08-06 重构：题材动量不再并入个股共振（D2 完全解耦）。
# 日线六维：RPS(5/10/20) / 距年内高点 / 多窗口动量 / 整体性 / 资金量能 / 拥挤惩罚。
# 展示标签 phaseLabel（启动/扩散/过热/退潮/中性）为非状态机派生，不进任何合同。

from backend.analysis.theme.daily_series import ThemeDailySeries, virtual_index
from backend.analysis.theme.momentum_config import ThemeMomentumConfig


def _clamp100(value: float) -> float:
    """0-100 区间钳制（v2 专用，避免与 v1 的 0-1 _clamp 混淆）。"""
    return max(0.0, min(100.0, value))


def _num100(value: Any, default: float | None = None) -> float | None:
    """数值化，NaN/None → default；v2 语义：缺失保持缺失（不补零）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def _percentile_rank(value: float, values: list[float]) -> float:
    """value 在 values 中的横截面百分位（0-100，越大越强）。

    `<= value` 计数占全体比例——与"板块 RPS = 涨幅在全体板块中的分位"口径一致。
    """
    if not values:
        return 50.0
    below = sum(1 for v in values if v <= value)
    return (below / len(values)) * 100.0


def _n_day_return(changes: list[float], window: int) -> float:
    """最近 N 日累计收益：(1+c[-N:]) 连乘 - 1；窗口不足时用可用天数。"""
    series = changes[-window:]
    if not series:
        return 0.0
    product = 1.0
    for change in series:
        product *= 1.0 + change
    return product - 1.0


def _rps_for(
    window: int,
    series: ThemeDailySeries,
    all_returns: dict[int, list[float]],
) -> float | None:
    """N 日收益在全体板块横截面的百分位排名（0-100）。"""
    if len(series.changes) < window:
        return None
    ret = _n_day_return(series.changes, window)
    peers = all_returns.get(window, [])
    if not peers:
        return None
    return _percentile_rank(ret, peers)


def _near_high_score(series: ThemeDailySeries, cfg: ThemeMomentumConfig) -> float | None:
    """虚拟收益指数当前值 / 数据窗内 max(Index) 的接近度（0-100）。

    数据不足 full_window_days 时降级为"数据窗内高点"（reasons 由调用方标注）。
    窗内从未创新高（peak 贴近起点 1.0）时接近度语义失真，返回 None 由调用方
    标注 near_high_window_limited，避免普跌板块被高估（MEDIUM-2）。
    """
    if not series.changes:
        return None
    index = virtual_index(series.changes)
    current = index[-1]
    peak = max(index)
    if peak <= 0:
        return None
    # 窗内最高指数未明显高于起点（未创新高）：接近度无意义，降级 None
    if peak <= 1.05:
        return None
    return _clamp100(current / peak * 100.0)


def _window_momentum_score(series: ThemeDailySeries, cfg: ThemeMomentumConfig) -> float | None:
    """5/10/20 日收益率的加权符号强度（50 + Σ w·ret·coef，0-100）。"""
    if len(series.changes) < cfg.min_history_days:
        return None
    score = 50.0
    for window, weight in zip(cfg.rps_windows, cfg.rps_weights):
        ret = _n_day_return(series.changes, window)
        score += ret * 100.0 * weight * cfg.momentum_coefficient
    return _clamp100(score)


def _breadth_score(series: ThemeDailySeries) -> float | None:
    """整体性：日 breadthScore + 涨停家数贡献（0-100）。"""
    if not series.breadths:
        return None
    breadth = series.breadths[-1]
    zt = series.zt_counts[-1] if series.zt_counts else 0
    return _clamp100(breadth * 0.8 + min(zt * 5.0, 20.0))


def _flow_volume_score(series: ThemeDailySeries) -> float | None:
    """资金量能：主力净流入符号强度 + 成交额占比（0-100）。"""
    if not series.inflows:
        return None
    inflow = series.inflows[-1]
    ratio = series.amount_ratios[-1] if series.amount_ratios else 0.0
    inflow_score = _clamp100(50.0 + inflow * 10.0)
    ratio_score = _clamp100(ratio * 1000.0)
    return _clamp100(inflow_score * 0.6 + ratio_score * 0.4)


def _apply_crowding_penalty(
    base: float, crowding: float | None, cfg: ThemeMomentumConfig
) -> float:
    """拥挤门禁：crowding ≥ start 后线性扣分，封顶 penalty_max（动量崩溃对冲）。缺失（None）不扣。"""
    if crowding is None or crowding < cfg.crowding_penalty_start:
        return base
    penalty = min(
        cfg.crowding_penalty_max,
        (crowding - cfg.crowding_penalty_start) * cfg.crowding_penalty_slope,
    )
    return max(0.0, base - penalty)


def _phase_label(score: float, crowding: float | None, cfg: ThemeMomentumConfig) -> str:
    """展示标签（非状态机）：启动/扩散/过热/退潮/中性。crowding 缺失（None）时不判过热。

    仅展示解释，不进任何合同/回测/决策；题材周期 1-3 天~半个月，不做固定状态机。
    """
    if (
        crowding is not None
        and crowding >= cfg.phase_overheated_crowding
        and score >= cfg.phase_heat_score
    ):
        return "过热"
    if score >= cfg.phase_heat_score:
        return "扩散"
    if score >= cfg.phase_start_score:
        return "启动"
    if score <= cfg.phase_cool_score:
        return "退潮"
    return "中性"


def _intraday_state(
    current_row: dict[str, Any] | None,
    prev_row: dict[str, Any] | None,
) -> dict[str, float]:
    """槽位日内辅口径：短变化/涨停增量/资金增量（仅快照，不判定生命周期）。"""
    def num(v: Any) -> float:
        v = _num100(v)
        return v if v is not None else 0.0
    short_change = num(current_row.get("change") if current_row else None)
    zt_cur = num(current_row.get("ztCount") if current_row else None)
    zt_prev = num(prev_row.get("ztCount") if prev_row else None)
    inflow_cur = num(current_row.get("mainNetInflow") if current_row else None)
    inflow_prev = num(prev_row.get("mainNetInflow") if prev_row else None)
    return {
        "shortChange": round(short_change, 4),
        "ztDelta": round(zt_cur - zt_prev, 2),
        "inflowDelta": round(inflow_cur - inflow_prev, 4),
    }




def _rotation_state_for_v2(
    score: float | None,
    direction: str,
    inflow: float | None,
    crowding: float | None,
) -> str:
    """v2 的 rotationState 方向标签（spec D10，无状态机钳制）。

    基于日线动量方向 + 资金方向；mainline 需横截面 Top 判定（由 theme_rotation
    引擎负责），此处仅产出 inflow/outflow/neutral，reasons 标注来源 v2。
    """
    if score is None:
        return "neutral"
    if direction == "up" or (inflow is not None and inflow > 0):
        return "inflow"
    if direction == "down" or (inflow is not None and inflow < 0):
        return "outflow"
    return "neutral"


def compute_theme_momentum_v2(
    daily_series_list: list[ThemeDailySeries],
    cfg: ThemeMomentumConfig | None = None,
    computed_at: int = 0,
) -> dict[str, Any]:
    """日线主口径题材动量（纯函数，无 I/O）。

    输入为 daily_series.build_daily_series 的产物；输出每题材
    {themeId, themeName, score, direction, phaseLabel, rps, nearHigh,
     windowMomentum, breadth, flowVolume, crowdingPenalty, intraday, reasons}。

    fail-visible：横截面不足打 qualityFlags；单题材序列不足对应维度 None + reason，
    不补零、不伪造；至少 3 个可用维度才合成综合分，否则 score=None。
    """
    cfg = cfg or ThemeMomentumConfig()

    # 横截面收益集合（各窗口）
    all_returns: dict[int, list[float]] = {}
    for window in cfg.rps_windows:
        all_returns[window] = [
            _n_day_return(s.changes, window)
            for s in daily_series_list
            if len(s.changes) >= window + 1
        ]

    factors: dict[str, dict[str, Any]] = {}
    for series in daily_series_list:
        reasons: list[str] = []

        rps: dict[str, float | None] = {}
        for window in cfg.rps_windows:
            value = _rps_for(window, series, all_returns)
            rps[f"d{window}"] = round(value, 1) if value is not None else None
            if value is None:
                reasons.append(f"rps_d{window}_history_insufficient")

        near_high = _near_high_score(series, cfg)
        if near_high is not None:
            if len(series.changes) < cfg.near_high_full_window_days:
                reasons.append("near_high_window_limited")
        else:
            # None：无数据或窗内未创新高（语义失真降级），统一标注
            reasons.append("near_high_window_limited")

        window_momentum = _window_momentum_score(series, cfg)
        if window_momentum is None:
            reasons.append("window_momentum_history_insufficient")

        breadth = _breadth_score(series)
        flow_volume = _flow_volume_score(series)
        if "amount_ratio_missing" in series.quality_flags and flow_volume is not None:
            flow_volume = None
            reasons.append("flow_volume_unavailable")

        # 拥挤门禁（spec §5.2）：使用真实 crowdingRisk 日线（build_daily_series 聚合）；
        # 数据缺失时保持缺失（crowding=None）→ 不扣分 + crowding_unavailable 标记
        # （fail-visible：不伪造、不用宽度反向代理造成自抵消）。
        crowding = (
            series.crowding_days[-1] if series.crowding_days else None
        )
        if crowding is None:
            reasons.append("crowding_unavailable")

        # 合成综合分：可用维度 < 3 则不产分
        scores: dict[str, float] = {}
        if rps.get("d5") is not None and rps.get("d10") is not None and rps.get("d20") is not None:
            scores["rps"] = (
                rps["d5"] * cfg.rps_weights[0]
                + rps["d10"] * cfg.rps_weights[1]
                + rps["d20"] * cfg.rps_weights[2]
            )
        if near_high is not None:
            scores["near_high"] = near_high
        if window_momentum is not None:
            scores["window_momentum"] = window_momentum
        if breadth is not None:
            scores["breadth"] = breadth
        if flow_volume is not None:
            scores["flow_volume"] = flow_volume

        if len(scores) < 3:
            factors[series.theme_id] = {
                "themeId": series.theme_id,
                "themeName": series.theme_name,
                "score": None,
                "direction": "neutral",
                "rotationState": "neutral",
                "phaseLabel": "中性",
                "rps": rps,
                "nearHigh": round(near_high, 1) if near_high is not None else None,
                "windowMomentum": (
                    round(window_momentum, 1) if window_momentum is not None else None
                ),
                "breadth": round(breadth, 1) if breadth is not None else None,
                "flowVolume": round(flow_volume, 1) if flow_volume is not None else None,
                "crowdingPenalty": 0.0,
                "ztCount": int(series.zt_counts[-1]) if series.zt_counts else 0,
                "intraday": (
                    _intraday_state(
                        (getattr(series, "latest_slots", []) or [None])[-1],
                        (getattr(series, "latest_slots", []) or [None, None])[-2]
                        if len(getattr(series, "latest_slots", []) or []) >= 2 else None,
                    )
                    if len(getattr(series, "latest_slots", []) or []) >= 2
                    else {"shortChange": 0.0, "ztDelta": 0.0, "inflowDelta": 0.0, "unavailable": True}
                ),
                "reasons": reasons + ["insufficient_factors"],
            }
            continue

        total_weight = sum(cfg.weights[k] for k in scores)
        base = sum(scores[k] * cfg.weights[k] for k in scores) / total_weight
        score = _apply_crowding_penalty(base, crowding if crowding is not None else 0.0, cfg)

        # 槽位日内辅口径（spec D3）：当日收盘槽 vs 前一日收盘槽快照
        slots = getattr(series, "latest_slots", [])
        intraday = (
            _intraday_state(slots[-1], slots[-2])
            if len(slots) >= 2
            else {"shortChange": 0.0, "ztDelta": 0.0, "inflowDelta": 0.0, "unavailable": True}
        )
        # direction 结合动量方向（spec §5.2：score 相对 50 且动量方向一致）：
        # 普跌市中 RPS 分位可能高但绝对动量（windowMomentum 以 50 为中性）为负，
        # 此时不标 up 而降级 neutral，避免方向与真实收益矛盾。
        momentum_dir = (
            "up"
            if window_momentum is not None and window_momentum > 50.0
            else "down"
            if window_momentum is not None and window_momentum < 50.0
            else "neutral"
        )
        if score >= cfg.direction_up_threshold and momentum_dir == "up":
            direction = "up"
        elif score <= cfg.direction_down_threshold and momentum_dir == "down":
            direction = "down"
        else:
            direction = "neutral"
            if score >= cfg.direction_up_threshold or score <= cfg.direction_down_threshold:
                reasons.append(
                    f"direction_consistency(momentum_dir={momentum_dir}, score={score:.0f})"
                )
        rotation_state = _rotation_state_for_v2(
            score, direction, series.inflows[-1] if series.inflows else None, crowding
        )
        if rotation_state != "neutral":
            reasons.append(f"rotationState={rotation_state}(v2)")
        factors[series.theme_id] = {
            "themeId": series.theme_id,
            "themeName": series.theme_name,
            "score": round(score, 1),
            "direction": direction,
            "rotationState": rotation_state,
            "phaseLabel": _phase_label(score, crowding, cfg),
            "rps": rps,
            "nearHigh": round(near_high, 1) if near_high is not None else None,
            "windowMomentum": round(window_momentum, 1) if window_momentum is not None else None,
            "breadth": round(breadth, 1) if breadth is not None else None,
            "flowVolume": round(flow_volume, 1) if flow_volume is not None else None,
            "crowdingPenalty": round(base - score, 1),
            "ztCount": int(series.zt_counts[-1]) if series.zt_counts else 0,
            "intraday": intraday,
            "reasons": reasons,
        }

    return {
        "version": cfg.version,
        "factors": factors,
        "qualityFlags": (
            ["cross_section_insufficient"]
            if len(daily_series_list) < cfg.cross_section_min
            else []
        ),
        "computedAt": computed_at,
    }
