"""阶段 5：信号→收益映射缺口诊断（纯函数，analysis 层就近放置）。

回答"S/A 档 excess 为正（阶段 3 已证）为什么不转化为交易收益"：
1. horizon_price_return_stats：S/A 档信号触发后未来 horizon 帧的**价格收益**分布
   （交易收益口径，区别于 tier_monotonicity 的排名收益），对照同分位桶未入场样本；
2. sa_bucket_distribution：S/A 档触发时当前排名分位桶分布（验证"追强集中在高分位、被均值回归吃掉"）；
3. sa_vs_amain_overlap：S/A 档信号 ∩ A_MAIN 入场集合的 Jaccard 重叠（定位信号→交易损耗环节）；
4. assess_gap：缺口归属判定——horizon 收益为正但交易收益为负 → 退出吞利润；
   horizon 收益本身为负 → 入场时机（均值回归）。

fail-visible：帧边界不足 / 未来帧缺股票 / 缺价格 → 样本不计入收益统计，
但以 skipped* 计数显式暴露，不伪造收益、不用 0 伪装缺失。
"""

from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.research.tier_monotonicity import tier_signal_of

# 与 tier_monotonicity 分位桶一致：rank 1-based → percentile 0-100 → 桶 0-9
BUCKET_COUNT = 10
DEFAULT_ENTRY_TIERS = ("S", "A")


def signal_entry_tier(signal: dict[str, Any]) -> str:
    """读取 synergy 合并档位（交易决策消费的主档位）。"""
    return tier_signal_of(signal, "synergy")


def _price_of(row: dict[str, Any]) -> float | None:
    """从 frame 股票行取价格（price 优先，回退 lastTradePrice/close/lastPrice）；全缺 → None。"""
    for key in ("price", "lastTradePrice", "close", "lastPrice"):
        value = row.get(key)
        if value is not None:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    return None


def _percentile(rank: float, total: int) -> float:
    if rank <= 0 or total <= 0:
        return 0.0
    return ((total - rank + 1) / total) * 100


def _build_lookup(
    frames: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, dict[str, Any]]]]:
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


def _summarize(samples: list[float]) -> dict[str, Any]:
    """收益样本分布摘要（均值/中位数/分位/胜率/亏损率）。空样本 → None 不伪造。"""
    count = len(samples)
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "winRate": None,
            "lossRate": None,
        }
    ordered = sorted(samples)
    total = sum(ordered)

    def quantile(q: float) -> float:
        pos = (len(ordered) - 1) * q
        lower = int(pos)
        upper = min(lower + 1, len(ordered) - 1)
        frac = pos - lower
        return ordered[lower] * (1 - frac) + ordered[upper] * frac

    return {
        "count": count,
        "mean": round(total / count, 6),
        "median": round(quantile(0.5), 6),
        "p25": round(quantile(0.25), 6),
        "p75": round(quantile(0.75), 6),
        "winRate": round(sum(1 for value in samples if value > 0) / count, 4),
        "lossRate": round(sum(1 for value in samples if value < 0) / count, 4),
    }


def horizon_price_return_stats(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = 3,
    entry_tiers: tuple[str, ...] = DEFAULT_ENTRY_TIERS,
) -> dict[str, Any]:
    """S/A 档信号触发后未来 horizon 帧的价格收益分布，对照同分位桶未入场样本。

    收益口径：价格收益 = future_price / entry_price - 1（交易收益口径）；
    未入场样本对照 = 同分位桶内非 entry_tiers 档信号（"追强不追"的反事实）。
    """
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    entry_samples: list[float] = []
    control_samples: list[float] = []
    # 分位桶条件化：桶 → {entrySamples, controlSamples}
    by_bucket: dict[int, dict[str, list[float]]] = {
        bucket: {"entry": [], "control": []} for bucket in range(BUCKET_COUNT)
    }
    skipped_frame_boundary = 0
    skipped_missing_row = 0
    skipped_missing_price = 0
    skipped_invalid_rank = 0
    for signal in signals:
        tier = signal_entry_tier(signal)
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None or entry + horizon >= totals:
            skipped_frame_boundary += 1
            continue
        current_row = (stock_by_frame_code[entry] or {}).get(code)
        target_row = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current_row or not target_row:
            skipped_missing_row += 1
            continue
        entry_price = _price_of(current_row)
        future_price = _price_of(target_row)
        if entry_price is None or future_price is None:
            skipped_missing_price += 1
            continue
        price_return = future_price / entry_price - 1.0
        current_pct = _percentile(float(current_row.get("rank") or 0), len(stock_by_frame_code[entry]))
        # fail-visible：rank 缺失/超界（占位 rank=999 等）→ percentile 无意义（<=0 或 >100），
        # 样本跳过并计数，不伪造分位桶（与 tier_monotonicity 同口径）。
        if current_pct <= 0 or current_pct > 100:
            skipped_invalid_rank += 1
            continue
        bucket = min(BUCKET_COUNT - 1, int(current_pct // 10))
        is_entry = tier in entry_tiers
        bucket_target = "entry" if is_entry else "control"
        by_bucket[bucket][bucket_target].append(price_return)
        if is_entry:
            entry_samples.append(price_return)
        else:
            control_samples.append(price_return)

    bucket_report: dict[str, dict[str, Any]] = {}
    for bucket, groups in by_bucket.items():
        entry_stats = _summarize(groups["entry"])
        control_stats = _summarize(groups["control"])
        bucket_report[str(bucket)] = {
            "entryCount": entry_stats["count"],
            "entryMean": entry_stats["mean"],
            "controlCount": control_stats["count"],
            "controlMean": control_stats["mean"],
        }
    return {
        "horizon": horizon,
        "entry": _summarize(entry_samples),
        "control": _summarize(control_samples),
        "byBucket": bucket_report,
        "frameCount": totals,
        "indexedFrameCount": len(index_by_snapshot),
        "skippedFrameBoundary": skipped_frame_boundary,
        "skippedMissingRow": skipped_missing_row,
        "skippedMissingPrice": skipped_missing_price,
        "skippedInvalidRank": skipped_invalid_rank,
    }


def sa_bucket_distribution(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    entry_tiers: tuple[str, ...] = DEFAULT_ENTRY_TIERS,
) -> dict[str, int]:
    """S/A 档信号触发时当前排名分位桶分布（验证"追强集中高分位"）。

    输出：{"0": count, ..., "9": count}，仅统计 entry_tiers 档信号且能找到当前 rank 的样本。
    """
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    distribution: dict[str, int] = {str(bucket): 0 for bucket in range(BUCKET_COUNT)}
    for signal in signals:
        tier = signal_entry_tier(signal)
        if tier not in entry_tiers:
            continue
        code = str(signal.get("code") or "")
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None:
            continue
        row = (stock_by_frame_code[entry] or {}).get(code)
        if not row:
            continue
        current_pct = _percentile(float(row.get("rank") or 0), len(stock_by_frame_code[entry]))
        # fail-visible：rank 缺失/超界（占位 rank=999 等）→ 不计入分位桶（不伪造位置）
        if current_pct <= 0 or current_pct > 100:
            continue
        bucket = min(BUCKET_COUNT - 1, int(current_pct // 10))
        distribution[str(bucket)] += 1
    return distribution


def sa_vs_amain_overlap(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """S/A 档信号 ∩ A_MAIN 入场集合的重叠度（Jaccard）与方向占比。

    - jaccard：|S/A ∩ A_MAIN| / |S/A ∪ A_MAIN|（0-1，越大说明信号与入场越一致）；
    - saShareInAmain：A_MAIN 入场的股票中 S/A 档占比（越大说明入场确实在追强）；
    - amainShareInSa：S/A 档信号中实际进入 A_MAIN 候选的比例（越大说明信号损耗越小）。
    """
    sa_codes: set[str] = set()
    amain_codes: set[str] = set()
    for signal in signals:
        code = str(signal.get("code") or "")
        if not code:
            continue
        if signal_entry_tier(signal) in DEFAULT_ENTRY_TIERS:
            sa_codes.add(code)
        if str(signal.get("candidateTier") or "") == "A_MAIN":
            amain_codes.add(code)
    intersection = sa_codes & amain_codes
    union = sa_codes | amain_codes
    return {
        "saCount": len(sa_codes),
        "amainCount": len(amain_codes),
        "intersection": len(intersection),
        "jaccard": round(len(intersection) / len(union), 4) if union else None,
        "saShareInAmain": round(len(intersection) / len(amain_codes), 4) if amain_codes else None,
        "amainShareInSa": round(len(intersection) / len(sa_codes), 4) if sa_codes else None,
    }


def assess_gap(
    entry_median: float | None,
    entry_win_rate: float | None,
    trade_median: float | None,
    trade_win_rate: float | None,
) -> dict[str, Any]:
    """缺口归属判定（阶段 5 诊断第 4/5 项）。

    规则（fail-visible：任一侧无样本 → unknown，不猜）：
    - entry_median <= 0 → 缺口在**入场时机**（追强信号触发后本身回落，均值回归主导）；
    - entry_median > 0 且 trade_median < 0 → 缺口在**退出机制**（horizon 收益为正但交易净收益为负，退出吞利润）；
    - 两者皆正 → 映射正常（no gap）；
    - 样本不足 → unknown 并附原因。
    """
    if entry_median is None or trade_median is None:
        return {"location": "unknown", "reason": "样本不足：入场 horizon 收益或交易净收益无可用样本"}
    if entry_median <= 0:
        return {
            "location": "entry",
            "reason": (
                f"S/A 档信号触发后 {entry_median:+.4f} 收益（中位数为负）——追强入场本身回落，"
                "缺口在入场时机/选股（均值回归主导），不在交易执行"
            ),
        }
    if trade_median < 0:
        return {
            "location": "exit",
            "reason": (
                f"horizon 收益中位数 {entry_median:+.4f} 为正但交易净收益中位数 {trade_median:+.4f} 为负"
                "——信号方向正确但退出机制吞利润（止损/止盈/降档退出过早）"
            ),
        }
    return {
        "location": "none",
        "reason": (
            f"horizon 收益 {entry_median:+.4f} 与交易净收益 {trade_median:+.4f} 均为正"
            "——信号→交易映射无缺口，可进入阶段 6 参数搜索/滚动迭代"
        ),
    }
