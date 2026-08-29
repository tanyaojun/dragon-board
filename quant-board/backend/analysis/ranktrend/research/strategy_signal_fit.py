"""策略-信号匹配度综合评估（纯函数，analysis 层就近放置）。

回答"生命周期分层策略到底匹不匹配 RankTrend 分析方法"（阶段 6 综合评估）：
synergy S/A 档信号有 h8 正期望（阶段 5 已证），但实际入场子集 h8 负/零——损耗发生在哪一环？

逐环节拆解漏斗：
  synergy S/A 档（信号层，RankTrend 分析方法产物）
    → candidateTier 分层（compose_analysis_candidate_tier：A_MAIN/B_IGNITION/C_CROWDED/D_EXIT_RISK/N_NEUTRAL）
    → regime 过滤（A_MAIN 内 strong/normal/weak/retreat 的 h8 差异）
    → 实际入场（TradeSimulator 反查 entry 信号，执行/资金/持仓数损耗）

每个环节输出：样本量、h8 价格收益分布（median/mean/winRate）、相对全量 S/A 档基线的损耗/增益。
fail-visible：空分组 None 不伪造；样本不足如实输出 count 与 None。
"""

from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.research.signal_return_gap import (
    signal_entry_tier,
    _build_lookup,
    _percentile,
    _price_of,
    _summarize,
)

DEFAULT_ENTRY_TIERS = ("S", "A")
HORIZON = 8


def _h8_samples(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = HORIZON,
) -> list[tuple[float, float]]:
    """返回 [(h8 价格收益, 当前分位), ...]；帧边界/缺行/缺价/无效 rank 样本跳过（fail-visible）。"""
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    samples: list[tuple[float, float]] = []
    for signal in signals:
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            continue
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        if current_pct <= 0 or current_pct > 100:
            continue
        samples.append((future_price / entry_price - 1.0, current_pct))
    return samples


def _group_summary(samples: list[float], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """样本收益摘要 + 相对基线的 delta（baseline 为 None 时不输出 delta）。"""
    summary = _summarize(samples)
    if baseline and baseline.get("mean") is not None and summary["mean"] is not None:
        summary["meanDelta"] = round(summary["mean"] - baseline["mean"], 6)
    if baseline and baseline.get("winRate") is not None and summary["winRate"] is not None:
        summary["winRateDelta"] = round(summary["winRate"] - baseline["winRate"], 4)
    return summary


def tier_distribution_by_candidate(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """synergy S/A 档信号按 candidateTier 分层：每层 h8 收益 + 相对 S/A 档全量基线的 delta。

    回答"生命周期分层是否把正期望信号正确归入入场档（A_MAIN）"：
    - 若 A_MAIN 的 winRateDelta <= 0 而 N_NEUTRAL/B_IGNITION > 0 → 分层与信号不匹配；
    - 输出各档样本占比（samples 基于 h8 可计算样本，非信号总数）。
    """
    sa_signals = [signal for signal in signals if signal_entry_tier(signal) in DEFAULT_ENTRY_TIERS]
    samples = _h8_samples(sa_signals, frames, horizon)
    if not samples:
        return {
            "horizon": horizon,
            "saSignalCount": len(sa_signals),
            "sampleCount": 0,
            "baseline": _summarize([]),
            "byCandidateTier": {},
            "note": "S/A 档 h8 无可用样本（帧边界/缺行/缺价/无效 rank 全跳过）",
        }
    values = [sample[0] for sample in samples]
    baseline = _summarize(values)
    # 预置全部分层 key：空档显式 count=0/mean=None（fail-visible，不隐藏缺失档）
    all_tiers = ("A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL")
    tiered_samples: dict[str, list[float]] = {tier: [] for tier in all_tiers}
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    for signal in sa_signals:
        tier = str(signal.get("candidateTier") or "N_NEUTRAL")
        if tier not in tiered_samples:
            tiered_samples[tier] = []
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            continue
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        if current_pct <= 0 or current_pct > 100:
            continue
        tiered_samples[tier].append(future_price / entry_price - 1.0)
    report_by_tier: dict[str, dict[str, Any]] = {}
    for tier in sorted(tiered_samples):
        report_by_tier[tier] = _group_summary(tiered_samples[tier], baseline)
    return {
        "horizon": horizon,
        "saSignalCount": len(sa_signals),
        "sampleCount": len(values),
        "baseline": baseline,
        "byCandidateTier": report_by_tier,
    }


def amain_funnel_by_regime(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """A_MAIN 候选按 regime 分层的 h8 收益 + 相对 A_MAIN 全量基线的 delta。

    回答"regime 过滤（weak_market 不进 A_MAIN）是否排除掉正期望"：
    - 若 weak/retreat 层 winRateDelta 为正 → 排除反而丢信号；
    - 输出各 regime 样本占比。
    """
    amain_signals = [
        signal for signal in signals
        if signal_entry_tier(signal) in DEFAULT_ENTRY_TIERS
        and str(signal.get("candidateTier") or "") == "A_MAIN"
    ]
    if not amain_signals:
        return {
            "horizon": horizon,
            "amainSignalCount": 0,
            "byRegime": {},
            "note": "无 A_MAIN 候选信号",
        }
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    by_regime: dict[str, list[float]] = {}
    for signal in amain_signals:
        regime = str(signal.get("regime") or "normal")
        by_regime.setdefault(regime, [])
    for signal in amain_signals:
        regime = str(signal.get("regime") or "normal")
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            continue
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        if current_pct <= 0 or current_pct > 100:
            continue
        by_regime[regime].append(future_price / entry_price - 1.0)
    all_values = [v for values in by_regime.values() for v in values]
    baseline = _summarize(all_values)
    return {
        "horizon": horizon,
        "amainSignalCount": len(amain_signals),
        "sampleCount": len(all_values),
        "baseline": baseline,
        "byRegime": {regime: _group_summary(values, baseline) for regime, values in sorted(by_regime.items())},
    }


def entered_vs_unentered(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    entered_keys: set[str],
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """A_MAIN 候选内"实际入场 vs 未入场"的 h8 收益对比。

    回答"执行/资金/持仓数损耗是否吃掉信号优势"：
    - entered 相对 unentered 的 winRateDelta <= 0 → 执行环节系统性选错；
    - entered_keys 由调用方从 TradeSimulator roundTripTrades 反查
      （f"{entrySignalSnapshotId}:{code}"）。
    """
    amain_signals = [
        signal for signal in signals
        if signal_entry_tier(signal) in DEFAULT_ENTRY_TIERS
        and str(signal.get("candidateTier") or "") == "A_MAIN"
    ]
    if not amain_signals:
        return {"horizon": horizon, "amainSignalCount": 0, "entered": _summarize([]), "unentered": _summarize([])}
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    entered_values: list[float] = []
    unentered_values: list[float] = []
    for signal in amain_signals:
        key = f"{signal.get('snapshotId')}:{signal.get('code')}"
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            continue
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        if current_pct <= 0 or current_pct > 100:
            continue
        value = future_price / entry_price - 1.0
        if key in entered_keys:
            entered_values.append(value)
        else:
            unentered_values.append(value)
    entered_summary = _summarize(entered_values)
    unentered_summary = _summarize(unentered_values)
    result: dict[str, Any] = {
        "horizon": horizon,
        "amainSignalCount": len(amain_signals),
        "entered": entered_summary,
        "unentered": unentered_summary,
    }
    if entered_summary.get("mean") is not None and unentered_summary.get("mean") is not None:
        result["enteredMeanDelta"] = round(entered_summary["mean"] - unentered_summary["mean"], 6)
    if entered_summary.get("winRate") is not None and unentered_summary.get("winRate") is not None:
        result["enteredWinRateDelta"] = round(entered_summary["winRate"] - unentered_summary["winRate"], 4)
    return result
