"""趋势反转判定（RankTrend 分析方法本体，纯函数）。

背景（阶段 6 综合评估 + 业务口径决策）：
- 现有 cycle stage 的 reversal = "高位反转"（排名从高分位回落，卖出语义）；
- cooling = 默认态（占 75% 样本），内部混杂"低位回升中"与"低位继续走弱"；
- RankTrend 分析方法的本质是排名趋势：**由跌转升的拐点（低位趋势反转）** 才是与
  分析方法匹配的信号，当前系统没有独立层识别它。

本模块新增趋势反转判定（analysis 层纯函数）：
- trend_reversal_of(signal)：检测"低分位 + 此前下行 + 当前回升"拐点（观察信号，不直接是买点）；
- 输出 {isReversal, confidence(0-1), reasons}，供分层策略新增"趋势反转层"档位消费；
- fail-visible：缺字段/样本不足 → isReversal=False + reasons 说明（不静默伪造）。

注意（研究 v2 实证）：简单"下行→回升"拐点 h8 无正期望（winRate 0.4829 < 全量 0.4991），
本判定只作"趋势反转层"的观察/候选标记，具体买点需结合量价/资金/情绪进一步搜索验证。
"""

from __future__ import annotations

from typing import Any

# 低位阈值（percentile 0-100，低分位 = 排名靠后）
LOW_PCT_MAX = 50.0
# 此前下行确认：entry 前 1 帧 percentile 相对前 3 帧均值的下降幅度
DOWN_CONFIRM_DELTA = 0.5
# 回升确认：当前帧 rankVelocity > 0
LOOKBACK = 4


def _pct_series_of(
    signal: dict[str, Any],
    index_by_snapshot: dict[str, int],
    stock_by_frame_code: list[dict[str, dict[str, Any]]],
    lookback: int = LOOKBACK,
) -> list[float]:
    """entry 及前 lookback-1 帧的 percentile 序列（含当前帧）；缺行/无效 rank → 空列表。"""
    from backend.analysis.ranktrend.signal_return_gap import _percentile

    code = str(signal.get("code") or "")
    entry = index_by_snapshot.get(str(signal.get("snapshotId")))
    if entry is None:
        return []
    series: list[float] = []
    for frame_index in range(max(0, entry - lookback + 1), entry + 1):
        row = (stock_by_frame_code[frame_index] or {}).get(code)
        if not row:
            return []
        pct = _percentile(float(row.get("rank") or 0), len(stock_by_frame_code[frame_index]))
        if pct <= 0 or pct > 100:
            return []
        series.append(pct)
    return series


def trend_reversal_of(
    signal: dict[str, Any],
    index_by_snapshot: dict[str, int] | None = None,
    stock_by_frame_code: list[dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """低位趋势反转判定（观察信号）。

    条件（全部满足才算拐点，缺数据 fail-visible 不算）：
    1. 当前分位低：current_pct <= LOW_PCT_MAX（低位区，非高位追强）；
    2. 此前下行：entry 前 1 帧 percentile 显著低于前 3 帧均值（近期在跌，不是持续上涨回调）；
    3. 当前回升：cycle.metrics.rankVelocity > 0（本帧排名开始回升）。
    返回 confidence：满足 1 且 2 且 3 → 1.0；缺任一维度 → 0 且 reasons 说明。
    """
    from backend.analysis.ranktrend.signal_return_gap import _percentile

    reasons: list[str] = []
    code = str(signal.get("code") or "")
    entry = index_by_snapshot.get(str(signal.get("snapshotId"))) if index_by_snapshot else None
    if index_by_snapshot is None or stock_by_frame_code is None or entry is None:
        return {"isReversal": False, "confidence": 0.0, "reasons": ["缺少帧索引/股票查找表，无法判定"]}
    current_row = (stock_by_frame_code[entry] or {}).get(code)
    if not current_row:
        return {"isReversal": False, "confidence": 0.0, "reasons": ["当前帧缺该股票行"]}
    current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
    if current_pct <= 0 or current_pct > 100:
        return {"isReversal": False, "confidence": 0.0, "reasons": [f"当前帧 rank 无效（pct={current_pct}）"]}

    series = _pct_series_of(signal, index_by_snapshot, stock_by_frame_code)
    if len(series) < LOOKBACK:
        return {
            "isReversal": False,
            "confidence": 0.0,
            "reasons": [f"历史帧不足（{len(series)}/{LOOKBACK}），无法确认此前下行"],
        }

    prior_mean = sum(series[:3]) / 3
    prior_last = series[2]
    down_confirmed = prior_mean - prior_last > DOWN_CONFIRM_DELTA
    metrics = (signal.get("rankTrend") or {}).get("cycle", {}).get("metrics") or {}
    velocity = float(metrics.get("rankVelocity") or 0)
    low_position = current_pct <= LOW_PCT_MAX

    if not low_position:
        reasons.append(f"当前分位 {current_pct:.1f} 不在低位区（> {LOW_PCT_MAX:.0f}），非低位反转")
    if not down_confirmed:
        reasons.append(f"此前下行未确认（前3帧均值 {prior_mean:.1f} vs 前1帧 {prior_last:.1f}）")
    if velocity <= 0:
        reasons.append(f"当前未回升（rankVelocity={velocity:.2f} <= 0）")

    is_reversal = low_position and down_confirmed and velocity > 0
    return {
        "isReversal": is_reversal,
        "confidence": 1.0 if is_reversal else 0.0,
        "currentPct": round(current_pct, 2),
        "priorMeanPct": round(prior_mean, 2),
        "priorLastPct": round(prior_last, 2),
        "rankVelocity": round(velocity, 3),
        "reasons": reasons or ["低位 + 此前下行 + 当前回升，判定为趋势反转"],
    }
