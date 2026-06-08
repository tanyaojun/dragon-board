from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

def clamp(value: float, min_value: float, max_value: float) -> float:
    if not math.isfinite(value):
        return min_value
    return max(min_value, min(max_value, value))


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def normalize_signed(value: float, positive_scale: float, negative_scale: float) -> float:
    scale = abs(positive_scale) if value >= 0 else abs(negative_scale)
    return clamp(math.tanh(value / max(1e-6, scale)), -1, 1)


def signal_confidence(raw_score: float, agreement_bonus: float = 0) -> float:
    return clamp(50 + abs(raw_score) * 40 + agreement_bonus, 50, 90)


def weighted_share(scores: list[float], weights: list[float], predicate) -> float:
    numerator = 0.0
    denominator = 0.0
    for index, score in enumerate(scores):
        weight = float(weights[index] if index < len(weights) else 0)
        if weight <= 0 or not math.isfinite(weight):
            continue
        denominator += weight
        if predicate(score, index):
            numerator += weight
    return numerator / denominator if denominator > 0 else 0.0


@dataclass
class RankTrendConfig:
    momentumPeriods: list[int] = field(default_factory=lambda: [3, 5, 8, 13, 21])
    momentumWeights: list[float] = field(default_factory=lambda: [0.15, 0.2, 0.25, 0.25, 0.15])
    buyThresholds: list[float] = field(default_factory=lambda: [5, 8, 13, 21, 34])
    sellThresholds: list[float] = field(default_factory=lambda: [-5, -8, -13, -21, -34])
    macdFast: int = 13
    macdSlow: int = 21
    macdSignal: int = 8
    requireMacdGoldenCross: bool = False
    jumpDeltaPct: float = 10.0  # 内生阈值跳跃检测的百分位变化阈值
    directionWeight: float = 0.3
    accelerationWeight: float = 0.25
    crossWeight: float = 0.2
    macdWeight: float = 0.25
    buyScoreThreshold: float = 0.12
    sellScoreThreshold: float = -0.12
    # compose_strategy tier thresholds (configurable, defaults match legacy hardcoded values)
    tierAMainMidMomentumMin: float = 4.0
    tierAMainShortMomentumMin: float = -1.0
    tierAMainDivergenceSeverityMax: float = 0.7
    tierBIgnitionShortMomentumMin: float = 3.0
    tierBIgnitionAccelMin: float = 0.5
    tierBIgnitionRiskPressureMax: float = 0.65
    tierCrowdedLongMomentumMin: float = 4.0
    tierCrowdedAccelMax: float = 0.0
    tierCrowdedRiskPressureMin: float = 0.45
    tierExitRiskShortMomentumMax: float = -2.0
    tierExitRiskAccelMax: float = -2.0
    tierExitRiskPressureMin: float = 0.55

    @classmethod
    def from_patch(cls, patch: dict[str, Any] | None = None) -> "RankTrendConfig":
        base = cls()
        if not patch:
            return base
        for key, value in patch.items():
            if hasattr(base, key):
                setattr(base, key, value)
        if base.macdSlow <= base.macdFast:
            base.macdSlow = base.macdFast + 1
        total = base.directionWeight + base.accelerationWeight + base.crossWeight + base.macdWeight
        if total > 0:
            base.directionWeight /= total
            base.accelerationWeight /= total
            base.crossWeight /= total
            base.macdWeight /= total
        return base


def get_macd_min_samples(config: RankTrendConfig) -> int:
    return max(2, int(config.macdSlow))


def get_technical_min_samples(config: RankTrendConfig) -> int:
    return max(get_macd_min_samples(config), max(config.momentumPeriods) + 1, 30)


def percentile_rank(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100


def period_momentum(percentiles: list[float], period: int) -> float:
    if len(percentiles) < period + 1:
        return 0.0
    return percentiles[-1] - percentiles[-1 - period]


def prev_period_momentum(percentiles: list[float], period: int) -> float:
    if len(percentiles) < period + 2:
        return 0.0
    return percentiles[-2] - percentiles[-2 - period]


def moving_average(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    return average(values[-period:]) if len(values) >= period else average(values)


def ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    result: list[float] = []
    ema = values[0]
    for index, value in enumerate(values):
        ema = value if index == 0 else (value - ema) * multiplier + ema
        result.append(ema)
    return result


def calculate_macd(values: list[float], config: RankTrendConfig) -> dict[str, Any]:
    if len(values) < get_macd_min_samples(config):
        return {"dif": 0, "dea": 0, "histogram": 0, "cross": "none", "confirmed": False, "rawScore": 0}
    fast = ema_series(values, config.macdFast)
    slow = ema_series(values, config.macdSlow)
    dif_series = [fast[i] - slow[i] for i in range(len(values))]
    dea_series = ema_series(dif_series, config.macdSignal)
    hist_series = [2 * (dif_series[i] - dea_series[i]) for i in range(len(values))]
    dif = dif_series[-1]
    dea = dea_series[-1]
    hist = hist_series[-1]
    prev_dif = dif_series[-2] if len(dif_series) >= 2 else dif
    prev_dea = dea_series[-2] if len(dea_series) >= 2 else dea
    prev_hist = hist_series[-2] if len(hist_series) >= 2 else hist
    gap = dif - dea
    prev_gap = prev_dif - prev_dea
    detected = "none"
    if prev_dif <= prev_dea and dif > dea:
        detected = "golden"
    elif prev_dif >= prev_dea and dif < dea:
        detected = "death"
    warm_gaps = [item / 2 for item in hist_series[max(0, config.macdSlow - 1):]]
    lookback = warm_gaps[-min(max(config.macdSignal, 3), len(warm_gaps)):] if warm_gaps else [0]
    gap_scale = max(1e-6, average([abs(item) for item in lookback]))
    strong_gap = math.tanh(abs(gap) / gap_scale)
    impulse = math.tanh(abs(gap - prev_gap) / gap_scale)
    cross = "none"
    raw_score = 0.0
    confirmed = False
    if detected == "golden":
        strong = hist > 0 and gap > 0 and gap > prev_gap and hist >= prev_hist and strong_gap >= 0.2 and gap >= max(1e-6, gap_scale * 0.18)
        confirmed = strong
        if strong:
            cross = "golden"
            raw_score = clamp(0.7 * strong_gap + 0.3 * impulse, 0, 1)
    elif detected == "death":
        valid = hist < 0 and gap < 0 and (abs(gap) >= max(1e-6, gap_scale * 0.12) or strong_gap >= 0.18)
        confirmed = valid and gap < prev_gap and hist <= prev_hist
        if valid:
            cross = "death"
            raw_score = -clamp(0.7 * strong_gap + 0.3 * impulse, 0, 1)
    return {"dif": dif, "dea": dea, "histogram": hist, "cross": cross, "confirmed": confirmed, "rawScore": raw_score}


def momentum_profile(percentiles: list[float]) -> dict[str, float]:
    def avg_mom(periods: list[int]) -> float:
        return average([period_momentum(percentiles, period) for period in periods])

    def avg_prev(periods: list[int]) -> float:
        return average([prev_period_momentum(percentiles, period) for period in periods])

    short_periods = [1, 3, 5]
    mid_periods = [5, 8, 13]
    long_periods = [13, 21]
    short = avg_mom(short_periods)
    mid = avg_mom(mid_periods)
    long = avg_mom(long_periods)
    acceleration = average([short - avg_prev(short_periods), mid - avg_prev(mid_periods)])
    shock = rank_shock(percentiles, 10)
    composite = clamp(0.35 * short + 0.4 * mid + 0.25 * long + 0.2 * acceleration, -100, 100)
    return {
        "short": round(short, 2),
        "mid": round(mid, 2),
        "long": round(long, 2),
        "acceleration": round(acceleration, 2),
        "shock": round(shock, 2),
        "composite": round(composite, 2),
    }


def rank_shock(percentiles: list[float], lookback: int = 5) -> float:
    if len(percentiles) < 6:
        return 0.0
    velocities = [percentiles[i] - percentiles[i - 1] for i in range(1, len(percentiles))]
    recent = velocities[-lookback:]
    current = recent[-1]
    baseline = recent[:-1] if lookback > 5 else recent
    if len(baseline) < 3:
        return 0.0
    mean = average(baseline)
    variance = average([(value - mean) ** 2 for value in baseline])
    std = math.sqrt(variance)
    return 0.0 if std < 1e-6 else clamp((current - mean) / std, -5, 5)


def cycle_rank_shock(percentiles: list[float]) -> float:
    if len(percentiles) < 6:
        return 0.0
    velocities = [percentiles[i] - percentiles[i - 1] for i in range(1, len(percentiles))]
    recent = velocities[-5:]
    current = recent[-1] if recent else 0.0
    mean = average(recent)
    variance = average([(value - mean) ** 2 for value in recent])
    std = math.sqrt(variance)
    return 0.0 if not math.isfinite(std) or std < 1e-6 else (current - mean) / std


def rank_path_commitment(percentiles: list[float]) -> float:
    if len(percentiles) < 4:
        return 0.5
    window = percentiles[-8:]
    total_improvement = max(0.0, window[-1] - window[0])
    if total_improvement <= 0:
        return 0.0
    steps = [window[index] - window[index - 1] for index in range(1, len(window))]
    positive_steps = [step for step in steps if step > 0]
    last_step = max(0.0, steps[-1] if steps else 0.0)
    pre_breakout_improvement = sum(positive_steps[:-1])
    positive_step_share = len(positive_steps) / max(1, len(steps))
    pre_breakout_share = pre_breakout_improvement / max(total_improvement, 1)
    last_step_dominance = last_step / max(total_improvement, 1)
    return clamp(
        positive_step_share * 0.45 + pre_breakout_share * 0.45 + (1 - last_step_dominance) * 0.1,
        0,
        1,
    )


def momentum_data(percentiles: list[float], config: RankTrendConfig) -> dict[str, Any] | None:
    if len(percentiles) < max(config.momentumPeriods) + 1:
        return None
    values = [period_momentum(percentiles, period) for period in config.momentumPeriods]
    prev_values = [prev_period_momentum(percentiles, period) for period in config.momentumPeriods]
    score = 0.0
    for index, value in enumerate(values):
        buy = config.buyThresholds[index]
        sell = config.sellThresholds[index]
        weight = config.momentumWeights[index]
        if value >= 0:
            score += math.tanh(value / max(1e-6, abs(buy))) * 100 * weight
        else:
            score -= math.tanh(abs(value) / max(1e-6, abs(sell))) * 100 * weight
    score = clamp(score, -100, 100)
    signal = "buy" if score >= 35 else "sell" if score <= -35 else "hold"
    return {"values": values, "prevValues": prev_values, "score": score, "signal": signal, "confidence": clamp(50 + abs(score) * 0.45, 50, 95)}


def analyze_momentum_signals(data: dict[str, Any] | None, config: RankTrendConfig) -> dict[str, Any]:
    default = {
        "direction": {"signal": "hold", "confidence": 50, "score": 0},
        "acceleration": {"signal": "hold", "confidence": 50, "score": 0},
        "zeroCross": {"signal": "hold", "confidence": 50, "score": 0},
    }
    if not data:
        return default
    values = data["values"]
    prev_values = data["prevValues"]
    count = min(len(values), len(prev_values), len(config.momentumWeights))
    if count == 0:
        return default
    values = values[:count]
    prev_values = prev_values[:count]
    weights = config.momentumWeights[:count]
    buy = config.buyThresholds[:count]
    sell = config.sellThresholds[:count]
    period_scores = [normalize_signed(values[i], buy[i], abs(sell[i])) for i in range(count)]
    direction_raw = sum(period_scores[i] * weights[i] for i in range(count))
    positive_share = weighted_share(period_scores, weights, lambda score, _: score > 0)
    negative_share = weighted_share(period_scores, weights, lambda score, _: score < 0)
    direction_score = clamp(direction_raw * (0.5 + 0.5 * max(positive_share, negative_share)), -1, 1)
    long_window = period_scores[-min(2, len(period_scores)):]
    long_oppose_buy = len(long_window) == 2 and all(score <= -0.25 for score in long_window)
    long_oppose_sell = len(long_window) == 2 and all(score >= 0.25 for score in long_window)
    direction_signal = "hold"
    if direction_score >= 0.2 and positive_share >= 0.6 and not long_oppose_buy:
        direction_signal = "buy"
    elif direction_score <= -0.2 and negative_share >= 0.6 and not long_oppose_sell:
        direction_signal = "sell"
    long_agreement = len([s for s in long_window if (s >= 0.15 if direction_score >= 0 else s <= -0.15)])

    accelerations = [values[i] - prev_values[i] for i in range(count)]
    accel_scores = [normalize_signed(accelerations[i], buy[i], abs(sell[i])) for i in range(count)]
    accel_raw = sum(accel_scores[i] * weights[i] for i in range(count))
    short_scores = accel_scores[:min(2, len(accel_scores))]
    accel_score = clamp(accel_raw * (0.7 + 0.3 * average([abs(score) for score in short_scores])), -1, 1)
    accel_signal = "hold"
    if accel_score >= 0.18 and any(score > 0 for score in short_scores):
        accel_signal = "buy"
    elif accel_score <= -0.18 and any(score < 0 for score in short_scores):
        accel_signal = "sell"
    short_agreement = len([s for s in short_scores if (s > 0 if accel_signal == "buy" else s < 0)]) if accel_signal != "hold" else 0

    zero_signal = "hold"
    zero_score = 0.0
    zero_conf = 50
    if count >= 2:
        trigger_now = values[0]
        trigger_prev = prev_values[0]
        confirm_score = normalize_signed(values[1], buy[1], abs(sell[1]))
        trigger_strength = min(1, abs(normalize_signed(trigger_now, buy[0], abs(sell[0]))))
        confirm_strength = min(1, abs(confirm_score))
        if trigger_prev <= 0 < trigger_now and confirm_score >= -0.15:
            zero_signal = "buy"
            zero_score = clamp(0.7 * trigger_strength + 0.3 * max(0, confirm_strength), -1, 1)
        elif trigger_prev >= 0 > trigger_now and confirm_score <= 0.15:
            zero_signal = "sell"
            zero_score = -clamp(0.7 * trigger_strength + 0.3 * max(0, confirm_strength), 0, 1)
        strong_confirm = (zero_signal == "buy" and confirm_score > 0.15) or (zero_signal == "sell" and confirm_score < -0.15)
        zero_conf = signal_confidence(zero_score, 5 if strong_confirm else 0)

    return {
        "direction": {"signal": direction_signal, "confidence": signal_confidence(direction_score, clamp(long_agreement * 2.5, 0, 5) if direction_signal != "hold" else 0), "score": direction_score},
        "acceleration": {"signal": accel_signal, "confidence": signal_confidence(accel_score, clamp(short_agreement * 2.5, 0, 5)), "score": accel_score},
        "zeroCross": {"signal": zero_signal, "confidence": zero_conf, "score": zero_score},
    }


def analyze_technical(percentiles: list[float], config: RankTrendConfig, fallback: dict[str, float] | None = None) -> dict[str, Any]:
    ma5 = moving_average(percentiles, 5)
    ma10 = moving_average(percentiles, 10)
    macd = calculate_macd(percentiles, config)
    profile = momentum_profile(percentiles)
    data = momentum_data(percentiles, config)
    if len(percentiles) >= get_technical_min_samples(config) and data:
        signals = analyze_momentum_signals(data, config)
        score = data["score"]
    else:
        signals, macd, score = fallback_signals(percentiles, macd, fallback or {}, len(percentiles) >= get_macd_min_samples(config))
    return {
        "movingAverage": {"ma5": ma5, "ma10": ma10, "trend": "up" if ma5 > ma10 else "down" if ma5 < ma10 else "steady"},
        "macd": macd,
        "signals": signals,
        "momentumScore": score,
        "momentumProfile": profile,
    }


def fallback_signals(percentiles: list[float], macd: dict[str, Any], fallback: dict[str, float], macd_available: bool) -> tuple[dict[str, Any], dict[str, Any], float]:
    display = normalize_signed(float(fallback.get("displayChange", 0)), 8, 8)
    price = normalize_signed(float(fallback.get("stockChange", 0)), 6, 6)
    volume = clamp(math.tanh((float(fallback.get("volumeRatio", 0)) - 1) / 0.75), -1, 1)
    zlje = float(fallback.get("zlje", 0))
    zljzb = float(fallback.get("zljzb", 0))
    capital = clamp((0.6 if zlje > 0 else -0.6 if zlje < 0 else 0) + (0.4 if zljzb > 0 else -0.4 if zljzb < 0 else 0), -1, 1)
    direction_score = clamp(display * 0.4 + price * 0.3 + capital * 0.2 + volume * 0.1, -1, 1)
    accel_score = clamp(display * 0.55 + price * 0.25 + volume * 0.2, -1, 1)
    zero_base = clamp(display * 0.5 + price * 0.35 + volume * 0.15, -1, 1)
    direction_signal = "buy" if direction_score >= 0.2 else "sell" if direction_score <= -0.2 else "hold"
    if direction_signal == "buy":
        direction_agreement = int(display > 0) + int(price > 0) + int(capital >= 0)
    elif direction_signal == "sell":
        direction_agreement = int(display < 0) + int(price < 0) + int(capital <= 0)
    else:
        direction_agreement = 0
    accel_signal = "buy" if accel_score >= 0.18 and (display > 0 or price > 0) else "sell" if accel_score <= -0.18 and (display < 0 or price < 0) else "hold"
    if accel_signal == "buy":
        accel_agreement = int(display > 0) + int(price > 0) + int(volume > 0)
    elif accel_signal == "sell":
        accel_agreement = int(display < 0) + int(price < 0) + int(volume < 0)
    else:
        accel_agreement = 0
    zero_signal = "hold"
    zero_score = 0.0
    if display > 0.15 and price > 0 and volume >= -0.2:
        zero_signal = "buy"
        zero_score = max(0, zero_base)
    elif display < -0.15 and price < 0 and volume <= 0.2:
        zero_signal = "sell"
        zero_score = min(0, zero_base)
    if zero_signal == "buy":
        zero_agreement = int(price > 0) + int(volume > 0)
    elif zero_signal == "sell":
        zero_agreement = int(price < 0) + int(volume < 0)
    else:
        zero_agreement = 0
    macd = {**macd, "cross": macd["cross"] if macd_available else "none", "rawScore": clamp(macd["rawScore"], -1, 1) if macd_available else 0}
    return (
        {
            "direction": {"signal": direction_signal, "confidence": signal_confidence(direction_score, clamp(direction_agreement * 1.5, 0, 5)), "score": direction_score},
            "acceleration": {"signal": accel_signal, "confidence": signal_confidence(accel_score, clamp(accel_agreement * 1.5, 0, 5)), "score": accel_score},
            "zeroCross": {"signal": zero_signal, "confidence": signal_confidence(zero_score, clamp(zero_agreement * 2.5, 0, 5)), "score": zero_score},
        },
        macd,
        clamp((display * 0.45 + price * 0.35 + capital * 0.2) * 100, -100, 100),
    )


def detect_rank_jumps(
    percentiles: list[float],
    ranks: list[float] | None = None,
    delta_pct: float = 10.0,
) -> dict[str, Any]:
    """内生阈值排名跳跃检测。

    持续追踪累计排名百分位变化，当 |累计变化| > delta 时触发事件。
    核心原理：波动爆发（来回震荡）的累计变化互相抵消，达不到阈值；
    只有不可逆的趋势性移动才会触发。

    Args:
        percentiles: 排序百分位序列 (0-100)
        ranks: 原始排名序列，用于计算实际排名变化幅度
        delta_pct: 百分位变化阈值，默认 10 个百分点

    Returns:
        event: "jump" | "none"
        direction: "buy" (排名跳跃式上升) | "sell" (排名崩塌式下降) | "hold"
        confidence: 0-100, 基于幅度、过冲量和持续性
    """
    if len(percentiles) < 3:
        return {
            "event": "none", "direction": "hold", "signal": "hold",
            "magnitude": 0, "overshoot": 0, "delta": delta_pct,
            "sustained": False, "confidence": 50, "eventCount": 0,
            "surgeCount": 0, "collapseCount": 0, "events": [],
        }

    ref = percentiles[0]
    events: list[dict[str, Any]] = []

    for i, p in enumerate(percentiles):
        cum_change = p - ref
        if abs(cum_change) > delta_pct:
            events.append({
                "index": i,
                "direction": "surge" if cum_change > 0 else "collapse",
                "magnitude": round(abs(cum_change), 2),
                "overshoot": round(abs(cum_change) - delta_pct, 2),
                "percentile": round(p, 2),
            })
            # 重置到近期均价而非当前极值，防止极端值误触反向事件
            lookback = min(3, i + 1)
            ref = sum(percentiles[i - lookback + 1 : i + 1]) / lookback

    if not events:
        cum = percentiles[-1] - percentiles[0]
        return {
            "event": "none", "direction": "hold", "signal": "hold",
            "magnitude": round(abs(cum), 2), "overshoot": 0, "delta": delta_pct,
            "sustained": False, "confidence": 50, "eventCount": 0,
            "surgeCount": 0, "collapseCount": 0, "events": [],
            "cumulativeChange": round(cum, 2),
        }

    latest = events[-1]
    surge_count = sum(1 for e in events if e["direction"] == "surge")
    collapse_count = sum(1 for e in events if e["direction"] == "collapse")
    sustained = surge_count >= 2 or collapse_count >= 2
    direction = "buy" if latest["direction"] == "surge" else "sell"

    mag = latest["magnitude"]
    overshoot = latest["overshoot"]
    mag_factor = min(1.0, mag / max(delta_pct * 2, 1))
    overshoot_factor = min(1.0, overshoot / max(delta_pct, 1))
    sustain_bonus = 0.20 if sustained else 0
    confidence = clamp(55 + 25 * mag_factor + 15 * overshoot_factor + 20 * sustain_bonus, 50, 95)

    # 排名幅度：如果提供了原始排名，计算实际排名变化
    rank_magnitude = 0
    if ranks and len(ranks) >= 2:
        rank_magnitude = abs(ranks[-1] - ranks[0])

    return {
        "event": "jump",
        "direction": direction,
        "signal": direction,
        "magnitude": round(mag, 2),
        "overshoot": round(overshoot, 2),
        "delta": delta_pct,
        "sustained": sustained,
        "confidence": round(confidence, 1),
        "eventCount": len(events),
        "surgeCount": surge_count,
        "collapseCount": collapse_count,
        "rankMagnitude": rank_magnitude,
        "events": [{"index": e["index"], "direction": e["direction"],
                     "magnitude": e["magnitude"]} for e in events],
    }


def analyze_cycle(ranks: list[float], percentiles: list[float]) -> dict[str, Any]:
    previous_stage = None
    current_stage = None
    current_raw = None
    previous_normalized = None
    metrics = {}
    for index in range(len(percentiles)):
        prefix_ranks = ranks[: index + 1]
        prefix_percentiles = percentiles[: index + 1]
        metrics = cycle_metrics(prefix_ranks, prefix_percentiles)
        raw = raw_stage(len(prefix_percentiles), prefix_percentiles[-1], metrics)
        normalized = normalize_stage(current_stage, raw, prefix_percentiles[-1], metrics)
        previous_stage = current_raw
        previous_normalized = current_stage
        current_raw = raw
        current_stage = normalized
    stage = current_stage or "cooling"
    raw = current_raw or "cooling"
    transition = stage if not previous_normalized or previous_normalized == stage else f"{previous_normalized}->{stage}"
    confidence = cycle_confidence(stage, percentiles[-1] if percentiles else 0, metrics)
    metric_values = metrics or {"rankVelocity": 0, "rankAcceleration": 0, "rankShock": 0, "hotZoneStreak": 0, "bestRecentRank": ranks[-1] if ranks else 999, "drawdownFromPeak": 0, "rankPathCommitment": 0.5}
    return {
        "rawStage": raw,
        "stage": stage,
        "previousStage": previous_normalized,
        "transition": transition,
        "confidence": confidence,
        "metrics": metric_values,
        "entryAdvice": entry_advice(stage, transition),
        "decision": lifecycle_decision(raw, stage, transition, confidence, metric_values),
    }


def cycle_metrics(ranks: list[float], percentiles: list[float]) -> dict[str, Any]:
    current_rank = ranks[-1] if ranks else 999
    rank_window = ranks[-8:]
    percentile_window = percentiles[-8:]
    hot_streak = 0
    for rank, percentile in reversed(list(zip(rank_window, percentile_window))):
        if rank <= 10 or percentile >= 88:
            hot_streak += 1
        else:
            break
    best = min(rank_window) if rank_window else current_rank
    velocity = percentiles[-1] - percentiles[-2] if len(percentiles) >= 2 else 0
    previous_velocity = percentiles[-2] - percentiles[-3] if len(percentiles) >= 3 else 0
    return {
        "rankVelocity": velocity,
        "rankAcceleration": velocity - previous_velocity,
        "rankShock": cycle_rank_shock(percentiles),
        "hotZoneStreak": hot_streak,
        "bestRecentRank": best,
        "drawdownFromPeak": max(0, current_rank - best),
        "rankPathCommitment": rank_path_commitment(percentiles),
    }


def raw_stage(history_length: int, current_percentile: float, metrics: dict[str, Any]) -> str:
    if history_length < 2:
        return "cooling"
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    warm = current_percentile >= 65 or best <= 25
    hot_zone = current_percentile >= 85 or best <= 10
    recovery = velocity > 0 and accel >= -1.2 and (current_percentile >= 50 or best <= 30 or hot >= 1)
    expansion = velocity > 0 and current_percentile >= 70 and (accel >= -1 or hot >= 1 or best <= 20)
    crowded = hot_zone and (hot >= 3 or best <= 5) and drawdown <= 1 and (velocity <= 1 or accel < 0)
    reversal = warm and drawdown >= 2 and (velocity < 0 or accel < -1) and (hot >= 2 or best <= 10)
    if reversal:
        return "reversal"
    if crowded:
        return "crowded"
    if expansion and warm:
        return "expansion"
    if recovery:
        return "ignition"
    return "cooling"


def normalize_stage(previous: str | None, raw: str, current_percentile: float, metrics: dict[str, Any]) -> str:
    if not previous:
        return raw
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    recovery = velocity > 0 and accel >= -1.2 and (current_percentile >= 50 or best <= 30 or hot >= 1)
    weakening = velocity < 0 or accel < -1 or drawdown >= 2
    severe = velocity < -1 or accel < -2.5 or drawdown >= 3
    cooling_ready = current_percentile < 72 or hot <= 1
    crowded_carry = current_percentile >= 82 or best <= 12 or hot >= 2
    if previous == "ignition":
        if raw in ("expansion", "crowded"):
            return "expansion"
        if raw in ("reversal", "cooling"):
            return "cooling" if weakening else "ignition"
        return "ignition"
    if previous == "expansion":
        if raw == "crowded":
            return "crowded"
        if raw == "reversal":
            return "crowded" if crowded_carry and not severe else "reversal" if severe or weakening else "crowded"
        if raw == "cooling":
            return "reversal" if severe or weakening else "expansion"
        return "expansion"
    if previous == "crowded":
        if raw == "reversal":
            return "reversal"
        if raw == "cooling":
            return "cooling" if cooling_ready else "reversal"
        if raw in ("expansion", "ignition"):
            return "reversal" if weakening else "crowded"
        return "crowded"
    if previous == "reversal":
        if raw in ("cooling", "reversal"):
            return raw
        return "cooling" if recovery else "reversal"
    if previous == "cooling":
        if raw in ("cooling", "reversal") or not recovery:
            return "cooling"
        if raw == "expansion" and current_percentile < 72 and hot == 0:
            return "ignition"
        if raw == "crowded":
            return "expansion"
        return raw
    return raw


def cycle_confidence(stage: str, percentile: float, metrics: dict[str, Any]) -> float:
    velocity = metrics.get("rankVelocity", 0)
    accel = metrics.get("rankAcceleration", 0)
    hot = metrics.get("hotZoneStreak", 0)
    best = metrics.get("bestRecentRank", 999)
    drawdown = metrics.get("drawdownFromPeak", 0)
    region = percentile < 60 if stage == "cooling" else percentile >= 50 and percentile < 80 if stage == "ignition" else percentile >= 60 if stage == "expansion" else percentile >= 82 or best <= 10 if stage == "crowded" else percentile >= 70 or best <= 20
    momentum = velocity <= 0 or percentile < 60 if stage == "cooling" else velocity > 0 and accel >= -0.8 if stage == "ignition" else velocity > 0 and accel >= -0.2 if stage == "expansion" else percentile >= 80 and (velocity <= 0 or hot >= 2) if stage == "crowded" else velocity <= 0 or accel < -1
    persistence = hot <= 1 if stage in ("cooling", "ignition") else hot <= 2 if stage == "expansion" else hot >= 2 if stage == "crowded" else hot >= 2 or best <= 10
    draw = drawdown <= 1 or percentile < 60 if stage == "cooling" else drawdown == 0 if stage == "ignition" else drawdown <= 1 if stage in ("expansion", "crowded") else drawdown >= 1
    return clamp(50 + int(region) * 10 + int(momentum) * 10 + int(persistence) * 10 + int(draw) * 10, 50, 90)


def entry_advice(stage: str, transition: str) -> dict[str, Any]:
    if transition in ("cooling->ignition", "ignition->expansion"):
        bias = "preferred"
    elif stage == "reversal":
        bias = "blocked"
    elif stage in ("cooling", "crowded"):
        bias = "avoid"
    else:
        bias = "watch"
    reasons = {
        "preferred": "处于优选阶段路径，可作为情绪周期主观察对象。",
        "watch": "处于可跟踪阶段，但还不是优选出手路径。",
        "avoid": "处于冷却或拥挤阶段，宜观察不宜积极出手。",
        "blocked": "处于反转阶段，应优先回避。",
    }
    return {"bias": bias, "allowed": bias == "preferred", "reason": reasons[bias]}


def lifecycle_decision(
    raw: str,
    stage: str,
    transition: str,
    confidence: float,
    metrics: dict[str, Any],
    risk: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    action = "caution"
    risk = risk or {}
    divergence = risk.get("divergence") if isinstance(risk.get("divergence"), dict) else {}
    overheat = risk.get("overheat") if isinstance(risk.get("overheat"), dict) else {}
    risk_pressure = float(risk.get("pressure") or 0)
    divergence_severity = float(divergence.get("severity") or 0)
    overheat_severity = float(overheat.get("severity") or 0)
    discovery_reasons: list[str] = []
    high_risk_conflict = risk_pressure >= 0.75 or (divergence_severity >= 0.8 and overheat_severity >= 0.7)
    rank_path = float(metrics.get("rankPathCommitment", 0.5))
    momentum = momentum if isinstance(momentum, dict) else {}
    momentum_short = float(momentum.get("short") or 0)
    momentum_mid = float(momentum.get("mid") or 0)
    momentum_long = float(momentum.get("long") or 0)
    momentum_acceleration = float(momentum.get("acceleration") or 0)
    mid_long_committed = momentum_mid >= 15 and momentum_long >= 15 and momentum_acceleration >= 8
    weak_path_commitment = (
        rank_path < 0.45
        and float(metrics.get("rankVelocity") or 0) > 18
        and float(metrics.get("rankAcceleration") or 0) > 12
        and not mid_long_committed
        and stage in ("ignition", "expansion")
    )
    low_visibility_ignition = (
        stage == "ignition"
        and transition == "cooling->ignition"
        and int(metrics.get("hotZoneStreak") or 0) == 0
        and rank_path < 0.7
        and float(metrics.get("rankVelocity") or 0) > 18
        and float(metrics.get("rankAcceleration") or 0) > 12
        and momentum_short >= 18
        and momentum_mid >= 18
        and momentum_acceleration >= 18
    )
    if stage == "reversal" or raw == "reversal":
        action = "veto"
        reasons.append("生命周期进入反转路径，辅助决策一票否决。")
    elif weak_path_commitment:
        action = "caution"
        reasons.append("生命周期B识别到最后一跳过强但整段承接不足，按假突破路径谨慎观察。")
    elif low_visibility_ignition:
        action = "caution"
        reasons.append("生命周期B识别到低可见度首段点火，承接尚未扩散，防止抢占后续高质量仓位。")
    elif high_risk_conflict and stage in ("ignition", "expansion"):
        action = "veto"
        reasons.append("生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。")
    elif stage == "crowded":
        action = "exit_watch"
        reasons.append("生命周期进入拥挤路径，持仓后应进入退出观察。")
    elif stage in ("ignition", "expansion"):
        action = "allow"
        reasons.append("生命周期处于点火或扩散路径，允许 RankTrend 主结构继续进入候选评估。")
    else:
        reasons.append("生命周期仍在冷却路径，辅助决策保持谨慎。")
    if "->" in transition:
        reasons.append(f"阶段路径：{transition}。")
    if stage in ("ignition", "expansion") and float(metrics.get("rankVelocity") or 0) > 0:
        discovery_reasons.append("生命周期存在漏选研究价值：点火/扩散路径仍在改善，但不得绕过 RankTrend 主结构直接制造买入。")
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "discovery": {
            "action": "research_watch" if discovery_reasons else "none",
            "reasons": discovery_reasons,
        },
        "evidence": {
            "rawStage": raw,
            "stage": stage,
            "transition": transition,
            "rankVelocity": metrics.get("rankVelocity", 0),
            "rankAcceleration": metrics.get("rankAcceleration", 0),
            "drawdownFromPeak": metrics.get("drawdownFromPeak", 0),
            "hotZoneStreak": metrics.get("hotZoneStreak", 0),
            "rankPathCommitment": rank_path,
            "momentumShort": momentum_short,
            "momentumMid": momentum_mid,
            "momentumLong": momentum_long,
            "momentumAcceleration": momentum_acceleration,
            "riskPressure": risk_pressure,
            "divergenceSeverity": divergence_severity,
            "overheatSeverity": overheat_severity,
        },
    }


def analyze_risk(current_percentile: float, technical: dict[str, Any], cycle: dict[str, Any], zlje: float, zljzb: float, volume_ratio: float) -> dict[str, Any]:
    metrics = cycle["metrics"]
    overheat = 0.0
    overheat += max(0, current_percentile - 70) * 1.2
    overheat += max(0, metrics["rankShock"]) * 12
    if metrics["rankVelocity"] > 0:
        overheat += min(15, metrics["rankVelocity"] * 1.5)
    if metrics["rankAcceleration"] < 0:
        overheat += min(20, abs(metrics["rankAcceleration"]) * 4)
    if technical["macd"]["histogram"] < 0:
        overheat += min(10, abs(technical["macd"]["histogram"]) * 15)
    if technical["signals"]["direction"]["signal"] == "buy":
        overheat += 5
    if technical["signals"]["acceleration"]["signal"] != "buy":
        overheat += 10
    if technical["signals"]["zeroCross"]["signal"] == "sell":
        overheat += 18
    overheat = clamp(overheat, 0, 100)

    hot_attention = current_percentile >= 70 or metrics["rankVelocity"] > 0
    divergence = 0.0
    if hot_attention:
        divergence += 10
    if hot_attention and zlje <= 0:
        divergence += 25
    if hot_attention and zljzb <= 0:
        divergence += 18
    if volume_ratio >= 2 and zlje <= 0:
        divergence += 15
    if volume_ratio >= 2 and zljzb <= 0:
        divergence += 8
    if metrics["rankShock"] > 0.8 and zlje <= 0:
        divergence += 12
    if cycle["stage"] in ("crowded", "reversal") and zlje <= 0:
        divergence += 12
    if zlje > 0:
        divergence -= 15
    if zljzb > 0:
        divergence -= 10
    if 0 < volume_ratio < 1.5 and zlje > 0:
        divergence -= 6
    divergence = clamp(divergence, 0, 100)

    stage = cycle["stage"]
    over_mult = {"ignition": 0.3, "expansion": 0.55, "crowded": 0.85, "reversal": 1, "cooling": 0.3}
    div_mult = {"ignition": 0.35, "expansion": 0.65, "crowded": 0.9, "reversal": 1, "cooling": 0.35}
    over_sev = clamp((overheat - 45) / 30, 0, 1) * over_mult.get(stage, 1)
    div_sev = clamp((divergence - 40) / 30, 0, 1) * div_mult.get(stage, 1)
    pressure = clamp(0.58 * over_sev + 0.42 * div_sev, 0, 1)
    return {
        "overheat": {"score": overheat, "signal": "sell" if overheat >= 70 and stage in ("crowded", "reversal") else "hold" if overheat >= 45 else "buy", "severity": over_sev},
        "divergence": {"score": divergence, "signal": "sell" if divergence >= 65 else "hold" if divergence >= 40 else "buy", "severity": div_sev},
        "pressure": pressure,
        "synergy": 1 if over_sev >= 0.65 and div_sev >= 0.6 else 0,
    }


def market_regime(frame: dict[str, Any]) -> dict[str, Any]:
    context = frame.get("marketContext") or {}
    payload = context.get("payload") or {}
    sentiment = context.get("sentiment") or payload.get("sentiment") or {}
    market_data = payload.get("marketData") or context.get("marketStats") or {}
    phase = sentiment.get("phaseName") or sentiment.get("phase") or payload.get("phaseName") or ""
    phase = phase[:-1] if isinstance(phase, str) and phase.endswith("期") else phase
    score = 50.0
    reasons: list[str] = []
    if phase:
        score += {"高潮": 14, "发酵": 8, "启动": 0, "退潮": -12, "冰点": -16}.get(phase, 0)
        reasons.append(f"情绪阶段{phase}")
    stocks = frame.get("stocks") or []
    zt = float(market_data.get("ztCount") or 0)
    dt = float(market_data.get("dtCount") or 0)
    up = float(market_data.get("upCount") or 0)
    down = float(market_data.get("downCount") or 0)
    if zt:
        score += clamp((zt - 35) * 0.35, -10, 16)
        reasons.append(f"涨停{zt:g}")
    if dt:
        score -= clamp(dt * 1.6, 0, 18)
        reasons.append(f"跌停{dt:g}")
    if up or down:
        spread = (up - down) / (up + down)
        score += clamp(spread * 18, -18, 18)
        reasons.append(f"涨跌扩散{spread * 100:.0f}%")
    if stocks:
        money_share = len([s for s in stocks if float(s.get("zlje") or 0) > 0]) / len(stocks)
        volume_share = len([s for s in stocks if float(s.get("volumeRatio") or 0) >= 1.2]) / len(stocks)
        score += clamp((money_share - 0.5) * 20, -10, 10)
        score += clamp((volume_share - 0.35) * 10, -5, 7)
        reasons.extend([f"热榜资金正向{money_share * 100:.0f}%", f"量能活跃{volume_share * 100:.0f}%"])
    score = clamp(score, 0, 100)
    state = "strong" if score >= 72 else "normal" if score >= 50 else "weak" if score >= 25 else "retreat"
    return {"state": state, "score": round(score, 1), "reasons": reasons or ["市场环境数据不足，按中性处理"]}


def compose_decision(technical: dict[str, Any], cycle: dict[str, Any], risk: dict[str, Any], config: RankTrendConfig) -> dict[str, Any]:
    def cross_signal(cross: str) -> str:
        return "buy" if cross == "golden" else "sell" if cross == "death" else "hold"

    components = [
        {"signal": technical["signals"]["direction"]["signal"], "rawScore": clamp(technical["signals"]["direction"]["score"], -1, 1), "weight": config.directionWeight},
        {"signal": technical["signals"]["acceleration"]["signal"], "rawScore": clamp(technical["signals"]["acceleration"]["score"], -1, 1), "weight": config.accelerationWeight},
        {"signal": technical["signals"]["zeroCross"]["signal"], "rawScore": clamp(technical["signals"]["zeroCross"]["score"], -1, 1), "weight": config.crossWeight},
        {"signal": cross_signal(technical["macd"]["cross"]), "rawScore": clamp(technical["macd"]["rawScore"], -1, 1), "weight": config.macdWeight},
    ]
    combined = sum(c["rawScore"] * c["weight"] for c in components)
    positive = sum(c["weight"] * max(c["rawScore"], 0) for c in components)
    negative = sum(c["weight"] * max(-c["rawScore"], 0) for c in components)
    buy_count = len([c for c in components if c["signal"] == "buy"])
    sell_count = len([c for c in components if c["signal"] == "sell"])
    base = "hold"
    macd_golden = technical["macd"]["cross"] == "golden"
    if combined >= config.buyScoreThreshold and sell_count <= 1 and positive >= negative:
        if config.requireMacdGoldenCross and not macd_golden:
            base = "hold"
        else:
            base = "buy"
    elif combined <= config.sellScoreThreshold and buy_count <= 1 and negative >= positive:
        base = "sell"
    signed_threshold = config.buyScoreThreshold if base == "buy" else config.sellScoreThreshold if base == "sell" else config.buyScoreThreshold if combined >= 0 else config.sellScoreThreshold
    threshold_scale = max(0.05, abs(signed_threshold))
    score_margin = combined - config.buyScoreThreshold if combined >= 0 else abs(combined) - abs(config.sellScoreThreshold)
    opposing = negative if base == "buy" else positive if base == "sell" else min(positive, negative)
    agreement = clamp(1 - opposing, 0, 1)
    confidence = clamp(50 + 25 * abs(combined) + 15 * agreement + 10 * math.tanh(abs(combined - signed_threshold) / threshold_scale), 50, 95)
    final = base
    final_conf = clamp(confidence - 11 * risk["overheat"]["severity"] - 9 * risk["divergence"]["severity"] - 5 * risk["synergy"], 50, 95)
    if base == "buy" and cycle["stage"] == "reversal" and risk["pressure"] >= 0.78 and risk["overheat"]["severity"] >= 0.7 and score_margin < 0.05:
        final = "hold"
        final_conf = min(final_conf, 62)
    return {"base": {"signal": base, "confidence": confidence, "combinedScore": combined, "scoreMargin": score_margin}, "final": {"signal": final, "confidence": final_conf}}


def compose_strategy(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    hotlist: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    trend_buy = technical["signals"]["direction"]["signal"] == "buy" or technical["signals"]["acceleration"]["signal"] == "buy" or technical["macd"]["cross"] == "golden"
    c = config or RankTrendConfig()
    hotlist_missing = not isinstance(hotlist, dict)
    hotlist_stage = str((hotlist or {}).get("stage") or "") if not hotlist_missing else ""
    hotlist_risk = str((hotlist or {}).get("riskLevel") or "") if not hotlist_missing else ""
    hotlist_state = {
        "state": "missing" if hotlist_missing else "present",
        "stage": hotlist_stage or None,
        "riskLevel": hotlist_risk or None,
        "confidence": (hotlist or {}).get("confidence") if not hotlist_missing else None,
    }
    tier = "N_NEUTRAL"
    reasons: list[str] = []
    lifecycle_decision_data = cycle.get("decision") or {}
    lifecycle_action = str((lifecycle_decision_data.get("action") or ""))
    lifecycle_reasons = lifecycle_decision_data.get("reasons") if isinstance(lifecycle_decision_data.get("reasons"), list) else []
    lifecycle_low_visibility_ignition = lifecycle_action == "caution" and any(
        "低可见度" in str(reason) for reason in lifecycle_reasons
    )

    if hotlist_stage in ("退潮", "冰点"):
        if momentum["short"] <= c.tierExitRiskShortMomentumMax or momentum["acceleration"] <= c.tierExitRiskAccelMax or risk["pressure"] >= c.tierExitRiskPressureMin:
            tier = "D_EXIT_RISK"
            reasons.append(f"热榜{hotlist_stage}期，动量衰减触发退出风险")
        else:
            reasons.append(f"热榜{hotlist_stage}期，暂停入场")
        reasons.append(f"热榜情绪: {hotlist_stage}(风险{hotlist_risk or '未知'})")
        action = {"D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
        return {"hotlist": hotlist_state, "momentum": momentum, "candidateTier": tier, "action": action, "reasons": reasons}

    allow_a_main = hotlist_missing or (hotlist_stage in ("高潮", "发酵") and hotlist_risk != "高")
    allow_b_ignition = hotlist_missing or hotlist_stage in ("高潮", "发酵", "启动")

    if lifecycle_action == "veto":
        reasons.append("生命周期辅助决策一票否决，阻止进入 A/B 候选池")

    if stage in ("reversal", "cooling") and (momentum["short"] <= c.tierExitRiskShortMomentumMax or momentum["acceleration"] <= c.tierExitRiskAccelMax or risk["pressure"] >= c.tierExitRiskPressureMin):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    elif stage == "crowded" or (momentum["long"] >= c.tierCrowdedLongMomentumMin and (momentum["acceleration"] <= c.tierCrowdedAccelMax or risk["pressure"] >= c.tierCrowdedRiskPressureMin)):
        tier = "C_CROWDED"
        reasons.append("长周期热度高位停留，追高性价比下降")
    elif stage == "expansion" and momentum["mid"] >= c.tierAMainMidMomentumMin and momentum["short"] >= c.tierAMainShortMomentumMin and trend_buy and allow_a_main and risk["divergence"]["severity"] < c.tierAMainDivergenceSeverityMax:
        tier = "A_MAIN"
        reasons.append("扩散阶段中周期动量确认，热榜情绪支持A_MAIN入场")
    elif stage == "ignition" and momentum["short"] >= c.tierBIgnitionShortMomentumMin and momentum["acceleration"] >= c.tierBIgnitionAccelMin and allow_b_ignition and risk["pressure"] < c.tierBIgnitionRiskPressureMax:
        tier = "B_IGNITION"
        reasons.append("点火阶段短周期冲击增强，热榜情绪支持B_IGNITION")
        if lifecycle_low_visibility_ignition:
            reasons.append("生命周期B低可见度点火诊断生效，B_IGNITION保留候选但排序降权")
    elif hotlist_stage == "启动" and stage == "expansion" and trend_buy:
        reasons.append("热榜启动期，A_MAIN暂缓，等待扩散确认")
    elif hotlist_risk == "高" and trend_buy:
        reasons.append("热榜情绪高风险，买入信号降级为观察")
    else:
        reasons.append("动量、阶段与风险未形成明确候选池信号")
    if hotlist_missing:
        reasons.append("热榜情绪缺失，按中性处理")
    elif hotlist_stage:
        reasons.append(f"热榜情绪: {hotlist_stage}(风险{hotlist_risk or '未知'})")
    if risk["divergence"]["severity"] >= 0.6:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= 0.65:
        reasons.append("过热压力较高")
    reasons.append(f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} 长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}")
    action = {"A_MAIN": "focus", "B_IGNITION": "watch", "C_CROWDED": "avoid", "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {"hotlist": hotlist_state, "momentum": momentum, "candidateTier": tier, "action": action, "reasons": reasons}


def analyze_cycle_with_risk(
    cycle: dict[str, Any],
    risk: dict[str, Any],
    momentum: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated_cycle = dict(cycle)
    updated_cycle["decision"] = lifecycle_decision(
        str(cycle.get("rawStage") or cycle.get("stage") or "cooling"),
        str(cycle.get("stage") or "cooling"),
        str(cycle.get("transition") or cycle.get("stage") or "cooling"),
        float(cycle.get("confidence") or 50),
        cycle.get("metrics") if isinstance(cycle.get("metrics"), dict) else {},
        risk,
        momentum,
    )
    return updated_cycle


def compose_analysis_candidate_tier(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    reasons: list[str] = []
    money_risk = risk["divergence"]["severity"]
    pressure = risk["pressure"]
    regime_data = regime or {"state": "normal", "score": 0, "reasons": []}
    weak_market = regime_data["state"] in ("weak", "retreat")
    trend_buy = (
        technical["signals"]["direction"]["signal"] == "buy"
        or technical["signals"]["acceleration"]["signal"] == "buy"
        or technical["macd"]["cross"] == "golden"
    )
    tier = "N_NEUTRAL"
    lifecycle_decision_data = cycle.get("decision") or {}

    if lifecycle_decision_data.get("action") == "veto":
        reasons.append("生命周期辅助决策一票否决，阻止进入 A/B 候选池")
    elif stage in ("reversal", "cooling") and (
        momentum["short"] <= -2 or momentum["acceleration"] <= -2 or pressure >= 0.55
    ):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    elif stage == "crowded" or (
        momentum["long"] >= 4 and (momentum["acceleration"] <= 0 or pressure >= 0.45)
    ):
        tier = "C_CROWDED"
        reasons.append("长周期热度高位停留，追高性价比下降")
    elif (
        stage == "expansion"
        and momentum["mid"] >= 4
        and momentum["short"] >= -1
        and trend_buy
        and not weak_market
        and money_risk < 0.7
    ):
        tier = "A_MAIN"
        reasons.append("扩散阶段中周期动量确认，技术信号保持正向")
    elif (
        stage == "ignition"
        and momentum["short"] >= 3
        and momentum["acceleration"] >= 0.5
        and regime_data["state"] != "retreat"
        and pressure < 0.65
    ):
        tier = "B_IGNITION"
        reasons.append("点火阶段短周期冲击增强，仍需继续确认")
    elif weak_market and trend_buy:
        reasons.append("弱势/退潮环境下买入信号降级为观察")
    else:
        reasons.append("动量、阶段与风险未形成明确候选池信号")

    if regime_data["state"] == "strong":
        reasons.append("市场环境强，允许跟踪点火/扩散机会")
    if regime_data["state"] == "retreat":
        reasons.append("市场退潮，优先控制回撤风险")
    if risk["divergence"]["severity"] >= 0.6:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= 0.65:
        reasons.append("过热压力较高")
    reasons.append(
        f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} 长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}"
    )
    action = {"A_MAIN": "focus", "B_IGNITION": "watch", "C_CROWDED": "avoid", "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {
        "regime": regime_data,
        "momentum": momentum,
        "candidateTier": tier,
        "action": action,
        "reasons": reasons,
    }


class RankTrendPythonEngine:
    def __init__(self, config: RankTrendConfig | None = None):
        self.config = config or RankTrendConfig()
        self._stock_lookup: list[dict[str, dict[str, Any]]] = []

    def replay(self, frames: list[dict[str, Any]], warmup_count: int | None = None, window_size: int = 50, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        meta = meta or {}
        self._stock_lookup = self._build_stock_lookup(frames)
        min_count = warmup_count or get_technical_min_samples(self.config)
        start = min_count - 1 if len(frames) >= min_count else 0
        histories = defaultdict(deque)
        signals: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            history_start = max(0, index - window_size + 1)
            for history in histories.values():
                while history and history[0][0] < history_start:
                    history.popleft()

            stocks = frame.get("stocks", [])
            total_count = len(stocks)
            seen_codes: set[str] = set()
            for stock in stocks:
                code = str(stock.get("code") or "")
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                rank = float(stock.get("rank") or 0)
                if rank <= 0:
                    continue
                histories[code].append((index, rank, percentile_rank(rank, total_count)))

            if index < start:
                continue

            regime = market_regime(frame)
            for stock in stocks:
                code = str(stock.get("code") or "")
                series = histories.get(code)
                if not series:
                    continue
                signal = self._build_signal(
                    stock,
                    frame,
                    [item[1] for item in series],
                    [item[2] for item in series],
                    regime,
                    meta,
                )
                if signal:
                    signals.append(signal)
        return signals

    def replay_frame_at(self, frames: list[dict[str, Any]], index: int, window_size: int = 50, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        frame = frames[index]
        history_start = max(0, index - window_size + 1)
        history = frames[history_start: index + 1]
        regime = market_regime(frame)
        output = []
        for stock in frame.get("stocks", []):
            signal = self._replay_stock(stock, frame, history, history_start, regime, meta or {})
            if signal:
                output.append(signal)
        return output

    def _replay_stock(self, stock: dict[str, Any], frame: dict[str, Any], history: list[dict[str, Any]], history_start: int, regime: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
        ranks: list[float] = []
        percentiles: list[float] = []
        code = str(stock.get("code") or "")
        for offset, historical in enumerate(history):
            lookup_index = history_start + offset
            row = self._stock_lookup[lookup_index].get(code) if lookup_index < len(self._stock_lookup) else self._find_stock(historical, code)
            if not row:
                continue
            rank = float(row.get("rank") or 0)
            if rank <= 0:
                continue
            ranks.append(rank)
            percentiles.append(percentile_rank(rank, len(historical.get("stocks", []))))
        return self._build_signal(stock, frame, ranks, percentiles, regime, meta)

    def _build_signal(self, stock: dict[str, Any], frame: dict[str, Any], ranks: list[float], percentiles: list[float], regime: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
        if not ranks:
            return None
        code = str(stock.get("code") or "")
        current_rank = ranks[-1]
        current_percentile = percentiles[-1]
        previous = percentiles[-2] if len(percentiles) >= 2 else current_percentile
        display_change = current_percentile - previous
        fallback = {
            "displayChange": display_change,
            "stockChange": float(stock.get("change") or 0),
            "volumeRatio": float(stock.get("volumeRatio") or 0),
            "zlje": float(stock.get("zlje") or 0),
            "zljzb": float(stock.get("zljzb") or 0),
        }
        technical = analyze_technical(percentiles, self.config, fallback)
        cycle = analyze_cycle(ranks, percentiles)
        risk = analyze_risk(current_percentile, technical, cycle, fallback["zlje"], fallback["zljzb"], fallback["volumeRatio"])
        cycle = analyze_cycle_with_risk(cycle, risk, technical.get("momentumProfile"))
        decision = compose_decision(technical, cycle, risk, self.config)
        strategy = compose_analysis_candidate_tier(technical, cycle, risk, regime)
        jump = detect_rank_jumps(percentiles, ranks, delta_pct=self.config.jumpDeltaPct)
        sample_status = "ok" if len(percentiles) >= get_technical_min_samples(self.config) else "degraded" if len(percentiles) >= 5 else "insufficient"
        rank_trend = {
            "meta": {
                "code": code,
                "currentRank": current_rank,
                "currentPercentile": current_percentile,
                "change": display_change,
                "rawChange": ranks[0] - current_rank,
                "updateTime": frame.get("timestamp"),
                "sampleQuality": {
                    "snapshotType": frame.get("type"),
                    "sampleCount": len(percentiles),
                    "requiredSampleCount": get_technical_min_samples(self.config),
                    "status": sample_status,
                    "coverageWarning": None if meta.get("sampleQuality") == "ok" else (meta.get("warnings") or ["样本质量降级"])[0],
                    "latestTradingDate": frame.get("tradingDate"),
                    "latestSlotTime": frame.get("slotTime"),
                    "delayedCount": meta.get("delayedCount", 0),
                    "restoredCount": meta.get("restoredCount", 0),
                },
            },
            "technical": technical,
            "jump": jump,
            "cycle": cycle,
            "risk": risk,
            "decision": decision,
            "strategy": strategy,
        }
        return {
            "snapshotId": frame.get("snapshotId"),
            "timestamp": frame.get("timestamp"),
            "tradingDate": frame.get("tradingDate"),
            "slotTime": frame.get("slotTime"),
            "code": code,
            "name": stock.get("name") or code,
            "rank": current_rank,
            "price": stock.get("price"),
            "change": stock.get("change"),
            "volume": stock.get("volume"),
            "turnover": stock.get("turnover"),
            "turnoverRate": stock.get("turnoverRate"),
            "volumeRatio": stock.get("volumeRatio"),
            "bid1Price": stock.get("bid1Price"),
            "bid1Volume": stock.get("bid1Volume"),
            "ask1Price": stock.get("ask1Price"),
            "ask1Volume": stock.get("ask1Volume"),
            "lastTradePrice": stock.get("lastTradePrice"),
            "lastTradeVolume": stock.get("lastTradeVolume"),
            "high": stock.get("high"),
            "low": stock.get("low"),
            "highPrice": stock.get("highPrice"),
            "lowPrice": stock.get("lowPrice"),
            "limitUpPrice": stock.get("limitUpPrice") or stock.get("ztPrice"),
            "limitDownPrice": stock.get("limitDownPrice") or stock.get("dtPrice"),
            "leadStatus": stock.get("leadStatus"),
            "fengdan": stock.get("fengdan"),
            "themes": stock.get("themes") or [],
            "mainTheme": stock.get("mainTheme"),
            "themeHeat": stock.get("themeHeat"),
            "themeContribution": stock.get("themeContribution"),
            "themeRole": stock.get("themeRole"),
            "themeRiskFlags": stock.get("themeRiskFlags") or [],
            "rankTrend": rank_trend,
            "candidateTier": strategy["candidateTier"],
            "action": strategy["action"],
            "stage": cycle["stage"],
            "regime": regime["state"],
            "confidence": decision["final"]["confidence"],
        }

    @staticmethod
    def _build_stock_lookup(frames: list[dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
        output: list[dict[str, dict[str, Any]]] = []
        for frame in frames:
            lookup: dict[str, dict[str, Any]] = {}
            for row in frame.get("stocks", []):
                code = str(row.get("code")) if row.get("code") is not None else ""
                if code and code not in lookup:
                    lookup[code] = row
            output.append(lookup)
        return output

    @staticmethod
    def _find_stock(frame: dict[str, Any], code: str) -> dict[str, Any] | None:
        return next((item for item in frame.get("stocks", []) if str(item.get("code")) == code), None)
