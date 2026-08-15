"""档位单调性统计（回测方案 §5.1，纯函数，analysis 层就近放置）。

合同：
- tier_forward_returns(signals, frames, horizon)：按 synergy.signalTier 分层统计未来 horizon
  帧的相对排名收益（percentileDelta，归一化 0-1 刻度）/方向精度/样本数。
- tier_monotonicity_score(stats)：Spearman 单调相关 + 相邻反转 + 硬约束判定（§5.2）。
- fail-visible：样本不足/无 D/E 样本/unknown 占比超限均返回结构化结果，不静默吞数据。
"""

from __future__ import annotations

from typing import Any

# 档位序（单调性验证用）：S > A > B > C；D/E 为反向/风险档不参与正向单调链。
TIER_ORDER = ["S", "A", "B", "C"]
TIER_VALUES = {"S", "A", "B", "C", "D", "E", "unknown"}

# 四维信号（+ synergy 合并）的 signalTier 在 signal 内的路径（阶段 3 区分度诊断）：
# resonance 由 API 单股链路写入 rankTrend.resonance（replay 链路缺横截面数据，无该维）；
# 其余四维由 engine 层 assemble_observation / compose_observation_scores 写入 observation.<dim>。
DIMENSION_PATHS: dict[str, tuple[str, ...]] = {
    "resonance": ("rankTrend", "resonance", "signalTier"),
    "rankTrend": ("rankTrend", "observation", "rankTrend", "signalTier"),
    "volumePrice": ("rankTrend", "observation", "volumePrice", "signalTier"),
    "lifecycle": ("rankTrend", "observation", "lifecycle", "signalTier"),
    "synergy": ("rankTrend", "observation", "synergy", "signalTier"),
}
DEFAULT_DIMENSION = "synergy"

# 硬约束阈值（回测方案 §5.2）
MIN_S_SAMPLES = 30
MIN_SA_DIRECTION_ACCURACY = 0.60
MAX_UNKNOWN_RATE = 0.05
D_E_BELOW_C_DELTA = 0.005  # D/E 比 C 低 0.5 个百分点（0-1 刻度）


def tier_signal_of(signal: dict[str, Any], dimension: str = DEFAULT_DIMENSION) -> str:
    """读取指定维度（synergy/共振/趋势/量价/周期）的 signalTier；缺字段/非法值回退 'unknown'（不伪装、不归零）。"""
    path = DIMENSION_PATHS.get(dimension)
    if path is None:
        return "unknown"
    current: Any = signal or {}
    for key in path:
        if not isinstance(current, dict):
            return "unknown"
        current = current.get(key)
    return str(current) if current in TIER_VALUES else "unknown"


def _percentile(rank: float, total: int) -> float:
    if rank <= 0 or total <= 0:
        return 0.0
    return ((total - rank + 1) / total) * 100


def _build_lookup(frames: list[dict[str, Any]]) -> tuple[dict[str, int], list[dict[str, dict[str, Any]]]]:
    index_by_snapshot: dict[str, int] = {}
    stock_by_frame_code: list[dict[str, dict[str, Any]]] = []
    for index, frame in enumerate(frames):
        index_by_snapshot[str(frame.get("snapshotId"))] = index
        by_code: dict[str, dict[str, Any]] = {}
        for row in frame.get("stocks") or []:
            code = str(row.get("code") or "")
            if code:
                by_code[code] = row
        stock_by_frame_code.append(by_code)
    return index_by_snapshot, stock_by_frame_code


def tier_forward_returns(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = 3,
    dimension: str = DEFAULT_DIMENSION,
) -> dict[str, Any]:
    """按指定维度 signalTier 分层统计未来 horizon 帧的相对排名收益。

    收益口径：该股该帧 signalTier 在未来 horizon 帧的 percentileDelta
    （percentile(future_rank) - percentile(current_rank)，归一化 0-1 刻度）；
    directionAccuracy = buy 类档位（S/A/B）中 percentileDelta > 0 的比例。
    帧边界不足/股票缺失 → 该样本不计入（found=False），不伪造收益。
    dimension 支持 resonance/rankTrend/volumePrice/lifecycle/synergy（阶段 3 四维诊断）。
    """
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    by_tier: dict[str, list[float]] = {tier: [] for tier in TIER_VALUES}
    for signal in signals:
        tier = tier_signal_of(signal, dimension)
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            continue  # 帧边界不足：不计样本（fail-visible：从 count 缺失可见）
        future = entry + horizon
        current = (stock_by_frame_code[entry] or {}).get(code)
        target = (stock_by_frame_code[future] or {}).get(code)
        if not current or not target:
            continue
        # rank 按 1-based 语义（evaluator 同口径）；缺失/非法 rank 归 0 后 _percentile 返回 0 → 该样本跳过（count 减少可见）
        current_pct = _percentile(float(current.get("rank") or 0), len(stock_by_frame_code[entry]))
        future_pct = _percentile(float(target.get("rank") or 0), len(stock_by_frame_code[future]))
        if current_pct <= 0 or future_pct <= 0:
            continue
        by_tier[tier].append((future_pct - current_pct) / 100.0)

    tiers: dict[str, dict[str, Any]] = {}
    for tier, deltas in by_tier.items():
        count = len(deltas)
        if count == 0:
            tiers[tier] = {"count": 0, "meanFutureReturn": None, "directionAccuracy": None}
            continue
        # 注：unknown 档也统计收益（实现超集，plan §5.1 示例为 null），但不参与单调性链
        tiers[tier] = {
            "count": count,
            "meanFutureReturn": round(sum(deltas) / count, 6),
            "directionAccuracy": round(sum(1 for d in deltas if d > 0) / count, 4),
        }

    total_samples = sum(tiers[tier]["count"] for tier in TIER_VALUES)
    unknown_rate = (tiers.get("unknown", {}).get("count") or 0) / max(1, total_samples)
    monotonicity = _monotonicity_of(tiers, unknown_rate)
    return {
        "horizon": horizon,
        "tiers": tiers,
        "unknownRate": round(unknown_rate, 4),
        "frameCount": totals,
        "indexedFrameCount": len(index_by_snapshot),  # 若小于 frameCount，说明存在重复 snapshotId（数据异常，显式暴露）
        "monotonicity": monotonicity,
    }


def _monotonicity_of(tiers: dict[str, dict[str, Any]], unknown_rate: float) -> dict[str, Any]:
    """Spearman 相关（档位序 vs 收益序）+ 相邻反转 + 硬约束判定（回测方案 §5.2）。"""
    ranked = [(tier, tiers.get(tier, {}).get("meanFutureReturn")) for tier in TIER_ORDER]
    present = [(tier, value) for tier, value in ranked if value is not None]
    # 档位等级：S→3, A→2, B→1, C→0（TIER_ORDER 从高到低）；Spearman 验证"档位高 → 收益高"（正相关）
    tier_levels = [len(TIER_ORDER) - 1 - TIER_ORDER.index(tier) for tier, _ in present]
    spearman = _spearman(tier_levels, [value for _, value in present]) if len(present) >= 2 else None

    reversals: list[dict[str, Any]] = []
    for index in range(1, len(present)):
        prev_tier, prev_value = present[index - 1]
        tier, value = present[index]
        if value > prev_value + 1e-12:
            reversals.append({"higher": tier, "lower": prev_tier, "gap": round(value - prev_value, 6)})

    # 硬约束（§5.2）：
    s_count = tiers.get("S", {}).get("count") or 0
    a_count = tiers.get("A", {}).get("count") or 0
    s_accuracy = tiers.get("S", {}).get("directionAccuracy") or 0
    a_accuracy = tiers.get("A", {}).get("directionAccuracy") or 0
    c_return = tiers.get("C", {}).get("meanFutureReturn")
    d_return = tiers.get("D", {}).get("meanFutureReturn")
    e_return = tiers.get("E", {}).get("meanFutureReturn")
    de_below_c = True
    if c_return is not None and (d_return is not None or e_return is not None):
        worst_de = min(value for value in (d_return, e_return) if value is not None)
        de_below_c = worst_de < c_return - D_E_BELOW_C_DELTA
    # S/A 合并方向精度：样本池加权（避免 A 无样本时 None→0 拖死、以及算术平均偏离真实精度）
    sa_total = s_count + a_count
    sa_accuracy = (s_count * s_accuracy + a_count * a_accuracy) / sa_total if sa_total > 0 else None

    checks = {
        "sSampleCount": {"ok": s_count >= MIN_S_SAMPLES, "actual": s_count},
        "monotonicNoReversal": {
            "ok": not reversals and (spearman is None or spearman > 0),
            "reversals": reversals,
            "validTiers": len(present),
        },
        "saDirectionAccuracy": {
            "ok": sa_accuracy is None or sa_accuracy >= MIN_SA_DIRECTION_ACCURACY,
            "actual": round(sa_accuracy, 4) if sa_accuracy is not None else None,
        },
        "deBelowC": {"ok": de_below_c, "actual": {"D": d_return, "E": e_return, "C": c_return}},
        "unknownRateBelow5pct": {"ok": unknown_rate < MAX_UNKNOWN_RATE, "actual": unknown_rate},
    }
    return {
        "spearmanRankCorr": round(spearman, 4) if spearman is not None else None,
        "reversals": reversals,
        "passHardConstraint": all(check["ok"] for check in checks.values()),
        "checks": checks,
    }


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman 秩相关（无 scipy 依赖，按排名对计算）。"""
    n = len(xs)
    if n < 2:
        return 0.0
    x_ranks = _rank_map(xs)
    y_ranks = _rank_map(ys)
    d = sum((x_ranks[i] - y_ranks[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d) / (n * (n * n - 1))


def _rank_map(values: list[float]) -> list[float]:
    """同值取平均秩（标准 Spearman）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        avg = (index + end) / 2 + 1
        for i in range(index, end + 1):
            ranks[order[i]] = avg
        index = end + 1
    return ranks


def tier_monotonicity_score(stats: dict[str, Any] | None) -> dict[str, Any]:
    """单调性得分与硬约束判定（供 objective.tier_risk_adjusted 消费，见回测方案 §5.1）。"""
    stats = stats or {}
    monotonicity = stats.get("monotonicity") or {}
    tiers = stats.get("tiers") or {}
    present = [value for value in (tiers.get(tier, {}).get("meanFutureReturn") for tier in TIER_ORDER) if value is not None]
    mean = sum(present) / len(present) if present else 0.0
    return {
        "score": round(monotonicity.get("spearmanRankCorr") or 0.0, 4),
        "meanFutureReturn": round(mean, 6),
        "passHardConstraint": bool(monotonicity.get("passHardConstraint")),
        "spearmanRankCorr": monotonicity.get("spearmanRankCorr"),
        "reversals": monotonicity.get("reversals") or [],
        "unknownRate": stats.get("unknownRate"),
        "checks": monotonicity.get("checks") or {},
    }


def tier_discrimination(stats: dict[str, Any] | None) -> dict[str, Any]:
    """档位区分度指标（阶段 3 四维信号区分度诊断）。

    从 tier_forward_returns 输出中提取"档位 → 未来收益/方向精度"的分离度：
    - sMinusC / aMinusC：S/A 档相对 C 档的未来收益差（>0 且越大区分度越强）；
    - tierSpread：S/A/B/C 档收益极差（0-1 刻度）；
    - saDirectionAccuracy：S/A 合并方向精度（样本池加权，无样本时 None 不伪造）；
    - cDirectionAccuracy：C 档方向精度（对照组）；
    - deVsC：D/E 中最差档相对 C 的收益差（应 < 0，反向风险档低于中性档）；
    - positiveMonotonic：Spearman>0 且无相邻反转（阶段 3 验收"tierDiscrimination 呈正单调"）。
    fail-visible：样本不足的档位返回 None/如实数值，不静默吞掉、不用 0 伪装。
    """
    stats = stats or {}
    tiers = stats.get("tiers") or {}
    monotonicity = stats.get("monotonicity") or {}

    def ret(tier: str) -> float | None:
        return (tiers.get(tier) or {}).get("meanFutureReturn")

    def acc(tier: str) -> float | None:
        return (tiers.get(tier) or {}).get("directionAccuracy")

    s, a, c = ret("S"), ret("A"), ret("C")
    d, e = ret("D"), ret("E")
    present = [value for value in (s, a, ret("B"), c) if value is not None]
    s_count = (tiers.get("S") or {}).get("count") or 0
    a_count = (tiers.get("A") or {}).get("count") or 0
    sa_total = s_count + a_count
    sa_accuracy = (
        (s_count * (acc("S") or 0) + a_count * (acc("A") or 0)) / sa_total if sa_total > 0 else None
    )
    de_values = [value for value in (d, e) if value is not None]
    worst_de = min(de_values) if de_values else None
    spearman = monotonicity.get("spearmanRankCorr")
    return {
        "sMinusC": round(s - c, 6) if s is not None and c is not None else None,
        "aMinusC": round(a - c, 6) if a is not None and c is not None else None,
        "tierSpread": round(max(present) - min(present), 6) if present else None,
        "saDirectionAccuracy": round(sa_accuracy, 4) if sa_accuracy is not None else None,
        "cDirectionAccuracy": acc("C"),
        "deVsC": round(worst_de - c, 6) if worst_de is not None and c is not None else None,
        "positiveMonotonic": bool(
            spearman is not None and spearman > 0 and not (monotonicity.get("reversals") or [])
        ),
    }
