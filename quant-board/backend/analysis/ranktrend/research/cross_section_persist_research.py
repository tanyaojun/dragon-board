# -*- coding: utf-8 -*-
"""crossSection 持续高位 A 档替代路径实证（2026-09-13 方案2，four-dim-algorithm-research 流程）。

背景：A 档唯一路径 delta>=5 受数学边界压制（delta ≤ 100 − pct），pct > 95 的强势股
（榜首 pct=100）永不可达。方案2 给 A 档加"持续高位"替代路径（pct ≥ PersistMin 且
近 N 帧 attention percentile 均值 ≥ PersistMeanMin 且窗口满帧合法），默认关闭
（crossSectionPersistFrames=0），是否落地默认由本实证决定。

假设（可证伪，先列判定标准再跑数据）：
- H1（正向区分度）：persist_only_A 样本 h1 excessDirectionAccuracy > 0，且高于
  同口径留在 B 桶的高位样本（pct>=85 未升级者）；
- H2（不稀释）：persist_only_A exDirAcc ≥ delta_A exDirAcc − 0.02（宽容带）；
- H3（样本量）：persist_only_A 全决策窗口 n ≥ 500，不足则结论降级为观察项。

口径（与生产/tier_forward_returns 对齐）：
- 档位输入序列：每股"出现序列"attention percentile（avgRankNum>0 按 avgRankNum 排序
  rank=index+1，percentile_rank 归一），与 _build_code_attention_series 同构；N∈{3,5}
  窗口不受 max_bars=50 截断影响，直接用完整前缀序列；
- h1 收益：帧列表相邻帧 rank 字段 _percentile 差 /100（tier_forward_returns 既定口径），
  分位桶（每 10 分位）基线去趋势；
- 数据窗口纪律：train/val/test 用于假设判定（assert_not_frozen 守卫），
  FINAL（8 月）只读 report，不参与判定、不回改参数。

用法：
    cd quant-board && ./.venv/Scripts/python.exe -m \
      backend.analysis.ranktrend.research.cross_section_persist_research
"""
from __future__ import annotations

import sys
from typing import Any

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    attention_rank_lookup,
    percentile_rank,
)
from backend.analysis.ranktrend.trend.cross_section import compute_cross_section
from backend.analysis.ranktrend.tier_monotonicity import _percentile  # research 复用既定收益口径
from backend.data.repositories import repository_factory
from backend.optimization.data_windows import assert_not_frozen, in_window

DATASET_ID = "dragonboard_live"
SNAPSHOT_TYPE = "half_hour"

# 决策窗口（train+val+test）与只读窗口（final report）
DECISION_START, DECISION_END = "2026-04-15", "2026-07-31"
FINAL_START, FINAL_END = "2026-08-01", "2026-08-14"

# 参数变体（少量敏感性点；大规模扫描属 ranktrend-tier-longterm-test 职责）
VARIANTS: list[tuple[str, int, float, float]] = [
    ("V0 主候选 (90,85,N=3)", 3, 90.0, 85.0),
    ("V1 长窗口 (90,85,N=5)", 5, 90.0, 85.0),
    ("V2 宽松 (88,82,N=3)", 3, 88.0, 82.0),
    ("V3 严格 (92,88,N=3)", 3, 92.0, 88.0),
]

BUCKETS = ("delta_A", "persist_only_A", "high_B", "other_B", "C", "D", "unknown")


def _load_frames(start: str, end: str) -> list[dict[str, Any]]:
    db = repository_factory.get_runtime_mongodb_database()
    repo = repository_factory.create_repository(db, enable_backup=False)
    bundles = repo.load_frame_bundles(
        DATASET_ID,
        snapshot_type=SNAPSHOT_TYPE,
        start_date=start,
        end_date=end,
        sort="asc",
        projection="ranktrend+themes",
    )
    # 同 key 去重（保留后出现 = ingest 最新覆盖），与 2026-09-13 同帧跳过修复语义一致：
    # 重复帧会让相邻 bar pct 恒等（假 delta=0），扭曲档位与收益。
    dedup: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        key = f"{bundle.get('tradingDate')} {bundle.get('slotTime')}".strip()
        if key:
            dedup[key] = bundle
    return [dedup[key] for key in sorted(dedup)]


def _build_attention_series(
    frames: list[dict[str, Any]],
) -> dict[str, list[tuple[int, float]]]:
    """每股出现序列 [(frame_idx, attention percentile)]（按帧升序 append，缺帧不填充）。"""
    series: dict[str, list[tuple[int, float]]] = {}
    for idx, frame in enumerate(frames):
        ranks, total = attention_rank_lookup(frame.get("stocks") or [])
        for code, rank in ranks.items():
            series.setdefault(code, []).append((idx, percentile_rank(rank, total)))
    return series


def _stats(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """分桶 h1 统计 + 分位桶基线去趋势（口径同 tier_forward_returns）。"""
    bucket_deltas: dict[int, list[float]] = {}
    for s in samples:
        bucket_deltas.setdefault(s["bucket"], []).append(s["delta"])
    baseline_acc = {
        b: (sum(1 for d in ds if d > 0) / len(ds) if ds else None) for b, ds in bucket_deltas.items()
    }
    baseline_mean = {b: (sum(ds) / len(ds) if ds else None) for b, ds in bucket_deltas.items()}
    out: dict[str, dict[str, Any]] = {}
    for label in BUCKETS:
        group = [s for s in samples if s["label"] == label]
        if not group:
            out[label] = {"n": 0, "dirAcc": None, "exDirAcc": None, "meanRet": None, "exMeanRet": None}
            continue
        deltas = [s["delta"] for s in group]
        acc = sum(1 for d in deltas if d > 0) / len(deltas)
        mean = sum(deltas) / len(deltas)
        accs = [baseline_acc[s["bucket"]] for s in group if baseline_acc.get(s["bucket"]) is not None]
        means = [baseline_mean[s["bucket"]] for s in group if baseline_mean.get(s["bucket"]) is not None]
        b_acc = sum(accs) / len(accs) if accs else None
        b_mean = sum(means) / len(means) if means else None
        out[label] = {
            "n": len(group),
            "dirAcc": round(acc, 4),
            "exDirAcc": round(acc - b_acc, 4) if b_acc is not None else None,
            "meanRet": round(mean, 6),
            "exMeanRet": round(mean - b_mean, 6) if b_mean is not None else None,
        }
    return out


def _print_window(title: str, samples: list[dict[str, Any]], report_only: bool) -> dict[str, Any]:
    stats = _stats(samples)
    tag = "（FINAL 只读 report，不参与判定）" if report_only else ""
    print(f"\n=== {title} {tag}帧样本 n={len(samples)} ===")
    header = f"{'桶':<14}{'n':>8}{'dirAcc':>9}{'exDirAcc':>10}{'meanRet':>10}{'exMeanRet':>11}"
    print(header)
    for label in BUCKETS:
        s = stats[label]
        cells = "".join(
            f"{s[k]:>10}" if isinstance(s[k], float) else (f"{s[k]:>8}" if k == "n" else f"{'--':>10}")
            for k in ("n", "dirAcc", "exDirAcc", "meanRet", "exMeanRet")
        )
        print(f"{label:<14}{cells}")
    return stats


def _judge(variant: str, decision_stats: list[dict[str, Any]]) -> None:
    """假设判定：只看 train/val/test（8 月冻结纪律），FINAL 不参与。"""
    agg: dict[str, dict[str, Any]] = {}
    for stats in decision_stats:
        for label in BUCKETS:
            slot = agg.setdefault(label, {"n": 0, "pos": 0, "ex_accs": []})
            slot["n"] += stats[label]["n"]
    # 方向精度合并需逐样本，这里用窗口级均值近似输出 + 样本量精确合计
    persist_n = sum(s["persist_only_A"]["n"] for s in decision_stats)
    print(f"\n--- {variant} 假设判定（train+val+test 合计）---")
    print(f"H3 样本量: persist_only_A n={persist_n}（门槛 500）→ {'达标' if persist_n >= 500 else '不足，结论降级观察项'}")
    for label in ("delta_A", "persist_only_A", "high_B"):
        ex_accs = [s[label]["exDirAcc"] for s in decision_stats if s[label]["exDirAcc"] is not None]
        mean_ex = sum(ex_accs) / len(ex_accs) if ex_accs else None
        print(f"{label}: 窗口级 exDirAcc 均值 = {round(mean_ex, 4) if mean_ex is not None else '--'}")
    if persist_n == 0:
        print("H1/H2 无法判定：persist_only_A 无样本")
        return
    ex = {
        label: [
            s[label]["exDirAcc"]
            for s in decision_stats
            if s[label]["exDirAcc"] is not None
        ]
        for label in ("delta_A", "persist_only_A", "high_B")
    }
    mean = {k: (sum(v) / len(v) if v else None) for k, v in ex.items()}
    if mean["persist_only_A"] is None:
        print("H1/H2 无法判定：persist_only_A exDirAcc 不可得")
        return
    h1_positive = mean["persist_only_A"] > 0
    h1_vs_b = mean["high_B"] is not None and mean["persist_only_A"] > mean["high_B"]
    h2 = mean["delta_A"] is not None and mean["persist_only_A"] >= mean["delta_A"] - 0.02
    print(f"H1 正向区分度: exDirAcc>0={h1_positive}，>high_B={h1_vs_b}")
    print(f"H2 不稀释（≥ delta_A−0.02）: {h2}")


def main() -> int:
    # Windows GBK 控制台：强制 UTF-8 输出（中文 + 数学符号）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from backend.optimization.data_windows import split_window

    print(f"加载数据 {DATASET_ID}/{SNAPSHOT_TYPE} {DECISION_START}~{FINAL_END} ...")
    all_frames = _load_frames(DECISION_START, FINAL_END)
    decision_frames = [f for f in all_frames if in_window(f, DECISION_START, DECISION_END)]
    final_frames = [f for f in all_frames if in_window(f, FINAL_START, FINAL_END)]
    print(f"帧数: 决策窗口(train/val/test)={len(decision_frames)} FINAL(8月只读)={len(final_frames)}")
    # 冻结守卫：决策样本禁止包含 FINAL 帧
    assert_not_frozen(decision_frames, purpose="scan")

    # 序列/标签都在全局决策帧列表上构建（idx 对齐），分窗口只切样本范围——
    # 跨窗口的每股出现前缀保持连续，与生产"该股出现序列"语义一致。
    decision_series = _build_attention_series(decision_frames)
    print(f"决策窗口股票数（attention 序列）: {len(decision_series)}")
    frame_dates = [str(f.get("tradingDate") or "") for f in decision_frames]

    for variant in VARIANTS:
        name = variant[0]
        decision_stats: list[dict[str, Any]] = []
        for window in ("train", "val", "test"):
            win_frames = split_window(decision_frames, window)
            if not win_frames:
                print(f"\n=== {name} / {window}: 无帧，跳过 ===")
                continue
            start_date, end_date = win_frames[0].get("tradingDate"), win_frames[-1].get("tradingDate")
            # 日期有序；同日多帧时取首/末帧（index 只找第一个匹配会截短窗口末日）
            start_idx = next(i for i, d in enumerate(frame_dates) if d >= str(start_date))
            end_idx = next((i for i, d in enumerate(frame_dates) if d > str(end_date)), len(frame_dates)) - 1
            samples = _label_samples_frames_range(decision_frames, decision_series, variant, start_idx, end_idx)
            stats = _print_window(f"{name} / {window}（{start_date}~{end_date}）", samples, report_only=False)
            decision_stats.append(stats)
        _judge(name, decision_stats)

    if final_frames:
        name = VARIANTS[0][0]
        # FINAL 只读 report：序列前缀从决策窗口末尾延续（跨窗口连续），仅在 FINAL 帧范围取样本
        samples = _label_samples_frames_range(
            all_frames,
            _build_attention_series(all_frames),
            VARIANTS[0],
            len(all_frames) - len(final_frames),
            len(all_frames) - 1,
        )
        _print_window(f"{name} / FINAL(8月)", samples, report_only=True)
        print("（FINAL 结果仅呈现，不参与任何参数决策）")
    return 0


def _label_samples_frames_range(
    frames: list[dict[str, Any]],
    series: dict[str, list[tuple[int, float]]],
    variant: tuple[str, int, float, float],
    start_idx: int,
    end_idx: int,
) -> list[dict[str, Any]]:
    """在全局帧列表的 [start_idx, end_idx] 范围打标签（序列用全局前缀，窗口边界正确）。"""
    _name, persist_frames, persist_min, persist_mean_min = variant
    base_cfg = RankTrendConfig()
    persist_cfg = RankTrendConfig(
        crossSectionPersistFrames=persist_frames,
        crossSectionPersistMin=persist_min,
        crossSectionPersistMeanMin=persist_mean_min,
    )
    by_code_frames = [
        {str(r.get("code")): r for r in (f.get("stocks") or []) if r.get("code")} for f in frames
    ]
    samples: list[dict[str, Any]] = []
    for idx in range(start_idx, min(end_idx, len(frames) - 1)):
        current_map = by_code_frames[idx]
        future_map = by_code_frames[idx + 1]
        for code, row in current_map.items():
            occ = series.get(code) or []
            # 二分：当前帧 idx 在该股出现序列中的位置（序列元素 idx 全局单调）
            lo, hi = 0, len(occ)
            while lo < hi:
                mid = (lo + hi) // 2
                if occ[mid][0] < idx:
                    lo = mid + 1
                else:
                    hi = mid
            if lo >= len(occ) or occ[lo][0] != idx:
                continue
            percentiles = [p for _i, p in occ[: lo + 1]]
            base = compute_cross_section(percentiles, None, base_cfg)
            persist = compute_cross_section(percentiles, None, persist_cfg)
            base_tier = str(base.get("signalTier"))
            persist_tier = str(persist.get("signalTier"))
            if base_tier == "A":
                label = "delta_A"
            elif persist_tier == "A":
                label = "persist_only_A"
            elif base_tier == "B" and float(base.get("percentile") or 0) >= 85.0:
                label = "high_B"
            elif base_tier in {"B", "C", "D", "unknown"}:
                label = base_tier
            else:
                label = "unknown"
            target = future_map.get(code)
            if not target:
                continue
            current_pct = _percentile(float(row.get("rank") or 0), len(current_map))
            future_pct = _percentile(float(target.get("rank") or 0), len(future_map))
            if current_pct <= 0 or future_pct <= 0:
                continue
            samples.append(
                {
                    "tradingDate": str(frames[idx].get("tradingDate") or ""),
                    "label": label,
                    "delta": (future_pct - current_pct) / 100.0,
                    "bucket": min(9, int(current_pct // 10)),
                }
            )
    return samples


if __name__ == "__main__":
    sys.exit(main())
