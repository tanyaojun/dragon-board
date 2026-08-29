"""趋势反转 × Jump 跳跃度搭配分析（阶段 6 方向：低位弱转强 + 排名跳跃确认，纯函数）。

背景（用户方向 2026-08-16）：单用排名百分位判定"弱转强"（trend_reversal_of）h8 无正期望
（winRate 0.4829 < 全量 0.4991）。原因：rankVelocity > 0 只说明排名回升（注意力回来），
不含"跳跃性"——而弱转强最有信息量的是**排名跳跃式上升**（jump.direction=buy）。
本模块统计分析 trend_reversal 信号按 jump 参数（事件方向 / 新鲜度 / 幅度）分桶的
未来 horizon 价格收益，回答"趋势反转 + 哪些 jump 参数值组合才有正期望"。

输入：replay 信号（含 rankTrend.trendReversal.isReversal、rankTrend.resonance.jump、
rankTrend.resonance.jumpFreshness）+ frames。输出：分桶 h1/h3/h8 价格收益分布。

fail-visible：每桶独立统计 skipped*（帧边界/缺行/缺价/无效 rank），不伪造收益、不用 0 伪装缺失。
"""

from __future__ import annotations

from typing import Any, Callable

from backend.analysis.ranktrend.research.signal_return_gap import (
    _build_lookup,
    _percentile,
    _price_of,
    _summarize,
)

# 默认分析期
DEFAULT_HORIZONS = (1, 3, 8)
# 新鲜度分层阈值（resonanceJumpFreshnessDecay=3，tierResonanceJumpFreshnessMin=0.5）
FRESHNESS_HIGH = 0.5
FRESHNESS_MID = 0.2
# 幅度分层阈值（jumpDeltaPct 默认 10/15，>20 为显著跳跃）
MAGNITUDE_HIGH = 20.0
MAGNITUDE_MID = 10.0


def _is_trend_reversal(signal: dict[str, Any]) -> bool:
    """读 replay 注入的 trendReversal 标记；缺字段 → False（不伪造）。"""
    marker = (signal.get("rankTrend") or {}).get("trendReversal") or {}
    return bool(marker.get("isReversal"))


def _jump_of(signal: dict[str, Any]) -> dict[str, Any]:
    """完整 jump 事件对象在 rankTrend.jump（detect_rank_jumps 全量输出）；
    resonance 内只暴露 jumpFreshness（由 analyze_rank_resonance 内部消费 events 后输出），
    不含 jump 字段本身。"""
    return (signal.get("rankTrend") or {}).get("jump") or {}


def _jump_event(signal: dict[str, Any]) -> str:
    return str(_jump_of(signal).get("event") or "none")


def _jump_direction(signal: dict[str, Any]) -> str:
    return str(_jump_of(signal).get("direction") or "hold")


def _jump_freshness(signal: dict[str, Any]) -> float | None:
    freshness = (signal.get("rankTrend") or {}).get("resonance", {}).get("jumpFreshness")
    try:
        return float(freshness)
    except (TypeError, ValueError):
        return None


def _jump_magnitude(signal: dict[str, Any]) -> float | None:
    """最近一次跳跃事件幅度；无事件 → None（不是 0，避免与真实 0 幅度混淆）。"""
    events = _jump_of(signal).get("events") or []
    if not events:
        return None
    latest = events[-1]
    try:
        return float(latest.get("magnitude"))
    except (TypeError, ValueError):
        return None


def _is_jump_buy(signal: dict[str, Any]) -> bool:
    return _jump_event(signal) == "jump" and _jump_direction(signal) == "buy"


def trend_reversal_jump_buckets() -> dict[str, Callable[[dict[str, Any]], bool]]:
    """分桶定义：全部为 trend_reversal 信号的子集过滤条件（调用方先过滤 isReversal）。"""
    return {
        "all_trend_reversal": lambda s: True,
        "jump_event": lambda s: _jump_event(s) == "jump",
        "jump_buy": _is_jump_buy,
        "jump_freshness_high": lambda s: (_jump_freshness(s) or 0) >= FRESHNESS_HIGH,
        "jump_freshness_mid": lambda s: (
            FRESHNESS_MID <= (_jump_freshness(s) or 0) < FRESHNESS_HIGH
        ),
        "jump_freshness_low": lambda s: (_jump_freshness(s) or 0) < FRESHNESS_MID,
        "jump_magnitude_high": lambda s: (_jump_magnitude(s) or 0) >= MAGNITUDE_HIGH,
        "jump_magnitude_mid": lambda s: (
            MAGNITUDE_MID <= (_jump_magnitude(s) or 0) < MAGNITUDE_HIGH
        ),
        # 组合：跳跃买 + 新鲜 / 大幅 / 新鲜且大幅
        "jump_buy_freshness_high": lambda s: _is_jump_buy(s)
        and (_jump_freshness(s) or 0) >= FRESHNESS_HIGH,
        "jump_buy_magnitude_high": lambda s: _is_jump_buy(s)
        and (_jump_magnitude(s) or 0) >= MAGNITUDE_HIGH,
        "jump_buy_freshness_high_magnitude_high": lambda s: _is_jump_buy(s)
        and (_jump_freshness(s) or 0) >= FRESHNESS_HIGH
        and (_jump_magnitude(s) or 0) >= MAGNITUDE_HIGH,
    }


def _bucket_price_stats(
    filtered: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int,
    index_by_snapshot: dict[str, int],
    stock_by_frame_code: list[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """对给定信号子集统计 horizon 价格收益（同 signal_return_gap 口径）。"""
    totals = len(frames)
    samples: list[float] = []
    skipped = {"frameBoundary": 0, "missingRow": 0, "missingPrice": 0, "invalidRank": 0}
    for signal in filtered:
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            skipped["frameBoundary"] += 1
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            skipped["missingRow"] += 1
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            skipped["missingPrice"] += 1
            continue
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        if current_pct <= 0 or current_pct > 100:
            skipped["invalidRank"] += 1
            continue
        samples.append(future_price / entry_price - 1.0)
    stats = _summarize(samples)
    stats["skipped"] = skipped
    return stats


def trend_reversal_jump_stats(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """trendReversal 信号按 jump 参数分桶的 horizon 价格收益统计。"""
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    buckets = trend_reversal_jump_buckets()
    tr_signals = [s for s in signals if _is_trend_reversal(s)]
    result: dict[str, Any] = {
        "frameCount": len(frames),
        "signalCount": len(signals),
        "trendReversalCount": len(tr_signals),
        "horizons": {},
    }
    for horizon in horizons:
        result["horizons"][str(horizon)] = {}
        for bucket_name, predicate in buckets.items():
            filtered = [s for s in tr_signals if predicate(s)]
            result["horizons"][str(horizon)][bucket_name] = _bucket_price_stats(
                filtered, frames, horizon, index_by_snapshot, stock_by_frame_code
            )
    return result
