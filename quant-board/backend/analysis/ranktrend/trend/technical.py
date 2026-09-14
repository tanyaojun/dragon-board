from __future__ import annotations

import math
from typing import Any
from ..engine.config import RankTrendConfig
from ..engine.primitives import clamp, average, normalize_signed, signal_confidence, weighted_share, _is_finite_number, get_macd_min_samples, get_momentum_min_samples, get_technical_min_computable_samples

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
        strong = (
            hist > 0
            and gap > 0
            and gap > prev_gap
            and hist >= prev_hist
            and strong_gap >= config.macdGoldenStrongGapMin
            and gap >= max(1e-6, gap_scale * config.macdGoldenGapScaleRatio)
        )
        confirmed = strong
        if strong:
            cross = "golden"
            raw_score = clamp(config.macdRawScoreWeights[0] * strong_gap + config.macdRawScoreWeights[1] * impulse, 0, 1)
    elif detected == "death":
        valid = (
            hist < 0
            and gap < 0
            and (abs(gap) >= max(1e-6, gap_scale * config.macdDeathGapScaleRatio) or strong_gap >= config.macdDeathStrongGapMin)
        )
        confirmed = valid and gap < prev_gap and hist <= prev_hist
        if valid:
            cross = "death"
            raw_score = -clamp(config.macdRawScoreWeights[0] * strong_gap + config.macdRawScoreWeights[1] * impulse, 0, 1)
    return {"dif": dif, "dea": dea, "histogram": hist, "cross": cross, "confirmed": confirmed, "rawScore": raw_score}


def calculate_ma_cross(percentiles: list[float], config: RankTrendConfig) -> dict[str, Any]:
    """MA 快慢线交叉因子（2026-09-12 阶段 17 观察因子，排名百分位序列，与 MACD 同输入）。

    - fast/slow = 简单均线全窗均值（maFastPeriod/maSlowPeriod，默认 10/20）；
    - 样本不足（len < maSlowPeriod）→ fast/slow=None、state="unknown"（fail-visible 不伪造 0）；
      len == maSlowPeriod 无前值 → 只算值不判交叉；
    - rawScore 仅交叉帧非零（golden +1 / death -1），镜像 MACD 二值参与语义；
      强度加权有意省略（阶段 13 实证 MACD gap 阈值面全冗余，不引入新参数）；
    - 周期合同（fast≥1 且 slow>fast）运行期复检：from_patch 之外直接构造 RankTrendConfig
      不触发校验/修复，非法周期在此 fail-fast 抛 ValueError（不静默产出空因子）。
    """
    fast_period = int(config.maFastPeriod)
    slow_period = int(config.maSlowPeriod)
    if fast_period < 1 or slow_period <= fast_period:
        raise ValueError(
            f"MA 周期需 fast>=1 且 slow>fast，实际 fast={fast_period}, slow={slow_period}"
        )
    if len(percentiles) < slow_period:
        return {"fast": None, "slow": None, "state": "unknown", "cross": "none", "rawScore": 0.0}
    fast = average(percentiles[-fast_period:])
    slow = average(percentiles[-slow_period:])
    state = "bull" if fast > slow else "bear" if fast < slow else "flat"
    if len(percentiles) < slow_period + 1:
        return {"fast": fast, "slow": slow, "state": state, "cross": "none", "rawScore": 0.0}
    prev_fast = average(percentiles[-1 - fast_period : -1])
    prev_slow = average(percentiles[-1 - slow_period : -1])
    cross = "none"
    raw_score = 0.0
    if prev_fast <= prev_slow and fast > slow:
        cross = "golden"
        raw_score = 1.0
    elif prev_fast >= prev_slow and fast < slow:
        cross = "death"
        raw_score = -1.0
    return {"fast": fast, "slow": slow, "state": state, "cross": cross, "rawScore": raw_score}


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
    signal = "buy" if score >= config.momentumScoreThreshold else "sell" if score <= -config.momentumScoreThreshold else "hold"
    return {"values": values, "prevValues": prev_values, "score": score, "signal": signal, "confidence": clamp(50 + abs(score) * config.momentumConfidenceSlope, 50, 95)}


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
    share_boost = config.momentumDirectionShareBoost
    direction_score = clamp(direction_raw * (share_boost[0] + share_boost[1] * max(positive_share, negative_share)), -1, 1)
    long_window = period_scores[-min(2, len(period_scores)):]
    long_oppose_buy = len(long_window) == 2 and all(score <= -config.momentumLongOpposeThreshold for score in long_window)
    long_oppose_sell = len(long_window) == 2 and all(score >= config.momentumLongOpposeThreshold for score in long_window)
    direction_signal = "hold"
    if direction_score >= config.momentumDirectionThreshold and positive_share >= config.momentumSignalShareMin and not long_oppose_buy:
        direction_signal = "buy"
    elif direction_score <= -config.momentumDirectionThreshold and negative_share >= config.momentumSignalShareMin and not long_oppose_sell:
        direction_signal = "sell"
    long_agreement = len([s for s in long_window if (s >= config.momentumLongAgreeThreshold if direction_score >= 0 else s <= -config.momentumLongAgreeThreshold)])

    accelerations = [values[i] - prev_values[i] for i in range(count)]
    accel_scores = [normalize_signed(accelerations[i], buy[i], abs(sell[i])) for i in range(count)]
    accel_raw = sum(accel_scores[i] * weights[i] for i in range(count))
    short_scores = accel_scores[:min(2, len(accel_scores))]
    accel_boost = config.momentumAccelShareBoost
    accel_score = clamp(accel_raw * (accel_boost[0] + accel_boost[1] * average([abs(score) for score in short_scores])), -1, 1)
    accel_signal = "hold"
    if accel_score >= config.momentumAccelThreshold and any(score > 0 for score in short_scores):
        accel_signal = "buy"
    elif accel_score <= -config.momentumAccelThreshold and any(score < 0 for score in short_scores):
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
        zero_weights = config.momentumZeroWeights
        if trigger_prev <= 0 < trigger_now and confirm_score >= -config.momentumZeroConfirmThreshold:
            zero_signal = "buy"
            zero_score = clamp(zero_weights[0] * trigger_strength + zero_weights[1] * max(0, confirm_strength), -1, 1)
        elif trigger_prev >= 0 > trigger_now and confirm_score <= config.momentumZeroConfirmThreshold:
            zero_signal = "sell"
            zero_score = -clamp(zero_weights[0] * trigger_strength + zero_weights[1] * max(0, confirm_strength), 0, 1)
        strong_confirm = (
            (zero_signal == "buy" and confirm_score > config.momentumZeroStrongConfirmThreshold)
            or (zero_signal == "sell" and confirm_score < -config.momentumZeroStrongConfirmThreshold)
        )
        zero_conf = signal_confidence(zero_score, config.momentumZeroStrongConfirmBonus if strong_confirm else 0)

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
    if len(percentiles) >= get_technical_min_computable_samples(config) and data:
        signals = analyze_momentum_signals(data, config)
        score = data["score"]
    else:
        signals, macd, score = fallback_signals(percentiles, macd, fallback or {}, len(percentiles) >= get_macd_min_samples(config), config)
    return {
        "movingAverage": {"ma5": ma5, "ma10": ma10, "trend": "up" if ma5 > ma10 else "down" if ma5 < ma10 else "steady"},
        "macd": macd,
        "maCross": calculate_ma_cross(percentiles, config),
        "signals": signals,
        "momentumScore": score,
        "momentumProfile": profile,
    }


def fallback_signals(percentiles: list[float], macd: dict[str, Any], fallback: dict[str, Any], macd_available: bool, config: RankTrendConfig | None = None) -> tuple[dict[str, Any], dict[str, Any], float]:
    # 阈值/权重 2026-09-14 参数化（config.fallback*，默认值=原硬编码，golden 不漂移）
    c = config or RankTrendConfig()
    dir_w = list(c.fallbackDirectionWeights or [0.4, 0.3, 0.2, 0.1])
    accel_w = list(c.fallbackAccelWeights or [0.55, 0.25, 0.2])
    zero_w = list(c.fallbackZeroWeights or [0.5, 0.35, 0.15])
    cap_w = list(c.fallbackCapitalWeights or [0.6, 0.4])

    def value(key: str) -> float | None:
        raw = fallback.get(key)
        return float(raw) if _is_finite_number(raw) else None

    display_raw, price_raw, volume_raw = value("displayChange"), value("stockChange"), value("volumeRatio")
    zlje, zljzb = value("zlje"), value("zljzb")
    display = normalize_signed(display_raw, c.fallbackDisplayNormScale, c.fallbackDisplayNormScale) if display_raw is not None else None
    price = normalize_signed(price_raw, c.fallbackPriceNormScale, c.fallbackPriceNormScale) if price_raw is not None else None
    volume = clamp(math.tanh((volume_raw - 1) / c.fallbackVolumeTanhScale), -1, 1) if volume_raw is not None else None
    capital_parts = []
    if zlje is not None:
        capital_parts.append(cap_w[0] if zlje > 0 else -cap_w[0] if zlje < 0 else 0)
    if zljzb is not None:
        capital_parts.append(cap_w[1] if zljzb > 0 else -cap_w[1] if zljzb < 0 else 0)
    if len(capital_parts) == 2:
        capital = sum(capital_parts) / (cap_w[0] + cap_w[1])
    elif len(capital_parts) == 1:
        # 单边可用时按该分量的自身权重归一（忠实原分支语义：zlje 在用 cap_w[0]，否则 cap_w[1]）
        single_weight = cap_w[0] if zlje is not None else cap_w[1]
        capital = capital_parts[0] / single_weight if single_weight else None
    else:
        capital = None

    def weighted(parts: list[tuple[float | None, float]]) -> float:
        available = [(v, w) for v, w in parts if v is not None]
        return clamp(sum(v * w for v, w in available) / sum(w for _, w in available), -1, 1) if available else 0.0

    direction_score = weighted([(display, dir_w[0]), (price, dir_w[1]), (capital, dir_w[2]), (volume, dir_w[3])])
    accel_score = weighted([(display, accel_w[0]), (price, accel_w[1]), (volume, accel_w[2])])
    zero_base = weighted([(display, zero_w[0]), (price, zero_w[1]), (volume, zero_w[2])])
    direction_signal = "buy" if direction_score >= c.fallbackDirectionThreshold else "sell" if direction_score <= -c.fallbackDirectionThreshold else "hold"
    if direction_signal == "buy":
        direction_agreement = int(display is not None and display > 0) + int(price is not None and price > 0) + int(capital is not None and capital >= 0)
    elif direction_signal == "sell":
        direction_agreement = int(display is not None and display < 0) + int(price is not None and price < 0) + int(capital is not None and capital <= 0)
    else:
        direction_agreement = 0
    accel_signal = "buy" if accel_score >= c.fallbackAccelThreshold and ((display is not None and display > 0) or (price is not None and price > 0)) else "sell" if accel_score <= -c.fallbackAccelThreshold and ((display is not None and display < 0) or (price is not None and price < 0)) else "hold"
    if accel_signal == "buy":
        accel_agreement = int(display is not None and display > 0) + int(price is not None and price > 0) + int(volume is not None and volume > 0)
    elif accel_signal == "sell":
        accel_agreement = int(display is not None and display < 0) + int(price is not None and price < 0) + int(volume is not None and volume < 0)
    else:
        accel_agreement = 0
    zero_signal = "hold"
    zero_score = 0.0
    if display is not None and price is not None and volume is not None and display > c.fallbackZeroDisplayMin and price > 0 and volume >= -c.fallbackZeroVolumeBand:
        zero_signal = "buy"
        zero_score = max(0, zero_base)
    elif display is not None and price is not None and volume is not None and display < -c.fallbackZeroDisplayMin and price < 0 and volume <= c.fallbackZeroVolumeBand:
        zero_signal = "sell"
        zero_score = min(0, zero_base)
    if zero_signal == "buy":
        zero_agreement = int(price is not None and price > 0) + int(volume is not None and volume > 0)
    elif zero_signal == "sell":
        zero_agreement = int(price is not None and price < 0) + int(volume is not None and volume < 0)
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
            weighted([(display, 0.45), (price, 0.35), (capital, 0.2)]) * 100,
    )
