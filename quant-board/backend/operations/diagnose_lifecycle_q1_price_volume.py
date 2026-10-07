# -*- coding: utf-8 -*-
"""生命周期 Q1 诊断步：price_changes/amount_history 喂入前的原料检验（backend/operations，2026-10-07）。

Q1（语料 §6 八问主线）：价量原料已逐帧采集并传入 _build_signal，但 analyze_cycle 不消费。
本脚本为预登记前的步骤 0+1（只读、零 API 调用、零 config 写回），产出四块 schema：

- A 覆盖率：price_changes/amount_history 在出现序列里的可用率（股帧级+步级，按月分布）；
- B gap 步价量分辨（核心靶子）：跨日步排名大跳 × 当日价格方向交叉，两组后续排名走向
  （未来 ≤3 步 Δpct 均值）对比 + 按 code 聚块 bootstrap 95% CI（seed 冻结）；
  同日相邻步作对照组——检验分辨力是否 gap 步特有；
- C 量维度：gap 步量比（amount / 前 3 可用步均值）按价量交叉分组分布（dv 结构性无量输入，
  此处为 Q1 独有增量）；
- D dv 重叠率（步骤 0）：compute_price_rank_divergence（单帧四态、无量输入、无 temporalGap
  防御、投票权重 0.0 纯观察）与 Q1 拟新增证据的覆盖交叉——靶子帧上 dv 已标号占比（重叠）/
  unknown·flat 占比（盲区）；并量化 dv 现状把跨日差分当 rankDir 的暴露面。
- E 可填充率：gap 步上价/量/量比三证据齐备率（决定 Q1 在 G1 空出的证据位上的实际可用面）。

dv 复刻自证：step 级方向判定与真函数 compute_price_rank_divergence 抽样对齐（2000 步），
防复刻漂移；阈值同 config.priceRankChangeMin/priceRankDeltaMin（默认 0.0，严格比较、flat 态）。

用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_lifecycle_q1_price_volume \
      [--start 2026-04-15] [--end 2026-10-07] [--out data/reports/lifecycle-q1-price-volume-diagnosis.json] \
      [--rank-delta-min 10] [--boot-iters 10000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank
from backend.analysis.ranktrend.trend.price_rank_divergence import compute_price_rank_divergence
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database

BOOTSTRAP_SEED = 20261007  # 与 P3 诊断同惯例：种子冻结于脚本常量
FWD_STEPS = 3              # 后续走向窗口：未来 ≤3 个出现步
AMOUNT_BASE_STEPS = 3      # 量比基准：前 3 个可用步均值


def _finite(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if np.isfinite(num) else None


def step_dv_state(change_cur: float | None, pct_cur: float | None, pct_prev: float | None,
                  change_min: float, delta_min: float) -> str:
    """step 级复刻 compute_price_rank_divergence 的方向交叉（同阈值/同 flat 语义）。

    与真函数的区别仅在输入投影：真函数吃全序列取 [-1]/[-2]，这里直接给步两端。
    抽样自证见 main（L0）。
    """
    if change_cur is None or pct_cur is None or pct_prev is None:
        return "unknown"
    price_dir = "up" if change_cur > change_min else "down" if change_cur < -change_min else "flat"
    delta = pct_cur - pct_prev
    rank_dir = "up" if delta > delta_min else "down" if delta < -delta_min else "flat"
    if price_dir == "up" and rank_dir == "up":
        return "confirm_up"
    if price_dir == "up" and rank_dir == "down":
        return "price_lead_warn"
    if price_dir == "down" and rank_dir == "up":
        return "rank_lead"
    if price_dir == "down" and rank_dir == "down":
        return "confirm_down"
    return "unknown"  # flat 态与真函数一致归 unknown


def month_label(trading_date: str) -> str:
    return trading_date[:7] if len(trading_date) >= 7 else "unknown"


def group_fwd_stats(rows: list[dict]) -> dict:
    fwd = np.array([r["fwd"] for r in rows], dtype=float) if rows else np.array([])
    return {
        "n": int(len(rows)),
        "fwd_mean": float(fwd.mean()) if len(rows) else None,
        "fwd_median": float(np.median(fwd)) if len(rows) else None,
        "fwd_up_share": float((fwd > 0).mean()) if len(rows) else None,
    }


def clustered_bootstrap_mean_diff(a_rows: list[dict], b_rows: list[dict], iters: int, rng: np.random.Generator) -> dict:
    """按 code 聚块 bootstrap：两组 fwd 均值差（a−b）的 95% CI。

    code 内先聚均值（消除同股多步相关），再对 code 重采样。
    """
    def by_code(rows: list[dict]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            out[r["code"]].append(r["fwd"])
        return {k: float(np.mean(v)) for k, v in out.items()}

    a, b = by_code(a_rows), by_code(b_rows)
    if not a or not b:
        return {"n_a": len(a_rows), "n_b": len(b_rows), "codes_a": len(a), "codes_b": len(b),
                "diff_mean": None, "ci95": None}
    a_vals = np.array(list(a.values()))
    b_vals = np.array(list(b.values()))
    na, nb = len(a_vals), len(b_vals)
    diffs = np.empty(iters, dtype=float)
    for it in range(iters):
        pa = a_vals[rng.integers(0, na, na)]  # 两组独立按 code 重采样（code 内先聚均值）
        pb = b_vals[rng.integers(0, nb, nb)]
        diffs[it] = float(pa.mean() - pb.mean())
    observed = float(a_vals.mean() - b_vals.mean())
    return {
        "n_a": len(a_rows), "n_b": len(b_rows), "codes_a": len(a), "codes_b": len(b),
        "diff_mean": observed,
        "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-15")
    ap.add_argument("--end", default="2026-10-07")
    ap.add_argument("--out", default="data/reports/lifecycle-q1-price-volume-diagnosis.json")
    ap.add_argument("--rank-delta-min", type=float, default=10.0)
    ap.add_argument("--boot-iters", type=int, default=10_000)
    ap.add_argument("--ratio-field", choices=("amount", "volumeRatio"), default="amount",
                    help="量证据口径：amount=cur/前3可用步均值（gap 步存在当日累计 vs 昨日尾盘累计的时点污染，仅对照）；"
                         "volumeRatio=行情源量比字段直接取值（当日累计均量 vs 近 5 日，口径干净，Q1 候选）")
    args = ap.parse_args()
    t0 = time.time()
    config = RankTrendConfig()
    change_min = float(getattr(config, "priceRankChangeMin", 0.0))
    delta_min = float(getattr(config, "priceRankDeltaMin", 0.0))
    rank_delta_min = args.rank_delta_min

    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date=args.start, end_date=args.end,
        projection="ranktrend", fields=["code", "rank", "avgRankNum", "change", "amount", "volumeRatio", "tradingDate", "slotTime"],
    )
    frames.sort(key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    frame_dates = [str(f.get("tradingDate") or "") for f in frames]
    print(f"frames={len(frames)} months={Counter(month_label(d) for d in frame_dates)}", file=sys.stderr)

    # ── 一次性按 code 构建完整出现序列（与引擎同口径：attention 重排、缺帧跳过不插值）──
    # 序列元素：(pct, change, amount, trading_date)；相邻步级分析，第一步无前驱跳过。
    series: dict[str, list[dict]] = defaultdict(list)
    row_missing = Counter()  # 股帧级字段缺失计数（fail-visible）
    stock_frame_total = 0
    for fi, frame in enumerate(frames):
        stocks = frame.get("stocks") or []
        ranks_map, total = attention_rank_lookup(stocks)
        date = frame_dates[fi]
        if not date:
            row_missing["frame_no_date"] += 1
        rows_by_code = {}
        for stock in stocks:
            if isinstance(stock, dict):
                c = str(stock.get("code") or "")
                if c:
                    rows_by_code[c] = stock
        for code, rank in ranks_map.items():
            stock_frame_total += 1
            row = rows_by_code.get(code)
            chg = _finite(row.get("change")) if row else None
            amt = _finite(row.get("amount")) if row else None
            if chg is None:
                row_missing["change_missing"] += 1
            if amt is None:
                row_missing["amount_missing"] += 1
            series[code].append({
                "pct": percentile_rank(float(rank), total),
                "change": chg,
                "amount": amt,
                "vr": _finite(row.get("volumeRatio")) if row else None,
                "date": date,
            })

    rng = np.random.default_rng(BOOTSTRAP_SEED)

    # ── 步级聚合容器 ──
    step_counter = 0                          # 全局步计数（dv 抽样自证用）
    step_total = Counter()                     # month -> n_steps
    bucket_counter = Counter()                 # {gap,same_day,date_unknown} -> n
    cov = Counter()                            # 步级价量可用率（gap/同日 × 字段）
    # B：gap 步排名大跳 × 价格方向交叉（后续走向 rows 带 code/fwd）
    cross_gap_down: dict[str, list[dict]] = defaultdict(list)   # month -> confirm_down/diverge_up/price_missing rows
    cross_gap_up: dict[str, list[dict]] = defaultdict(list)     # month -> confirm_up/diverge_down rows
    cross_same_down: dict[str, list[dict]] = defaultdict(list)  # 同日对照（全窗合并）
    cross_same_up: dict[str, list[dict]] = defaultdict(list)
    # C：gap 步量比（按交叉组）
    ratio_gap_down: dict[str, list[float]] = defaultdict(list)
    ratio_gap_up: dict[str, list[float]] = defaultdict(list)
    # D：dv（步级复刻 + 抽样真函数自证）
    dv_state_gap: Counter = Counter()
    dv_state_same: Counter = Counter()
    dv_cross_gap_down: Counter = Counter()     # 靶子步上 dv 的 state（重叠率主表）
    dv_rankdir_gap_up_down: Counter = Counter()  # gap 步 rankDir 分布（dv 无 temporalGap 防御暴露面）
    # E：gap 步三证据齐备率
    fill = Counter()

    step_dv_checked = 0
    step_dv_mismatch = 0

    for code, elems in series.items():
        n = len(elems)
        if n < 2:
            continue
        # 预算量比基准（前 3 可用步均值）：步 i 的基准=elems[i-3..i-1] 可用 amount 均值
        for i in range(1, n):
            cur, prev = elems[i], elems[i - 1]
            month = month_label(cur["date"])
            is_gap = bool(cur["date"]) and bool(prev["date"]) and cur["date"] != prev["date"]
            # 空日期步无法判定跨日：单列（fail-visible），不进 gap 也不进同日组
            date_unknown = (not cur["date"]) or (not prev["date"])
            step_counter += 1
            step_total[month] += 1
            bucket = "gap" if is_gap else ("same_day" if not date_unknown else "date_unknown")
            bucket_counter[bucket] += 1

            delta = cur["pct"] - prev["pct"]
            price = cur["change"]
            if price is not None:
                cov[f"{bucket}_price_ok"] += 1
            else:
                cov[f"{bucket}_price_missing"] += 1

            # 量证据：amount=cur/前3可用步均值（口径有日内时点污染，对照用）；
            # volumeRatio=行情源量比直接取值（Q1 候选口径）。0 值一律视为伪值排除。
            if args.ratio_field == "amount":
                base_amts = [e["amount"] for e in elems[max(0, i - AMOUNT_BASE_STEPS):i] if e["amount"] is not None and e["amount"] > 0]
                ratio = None
                if cur["amount"] is not None and cur["amount"] > 0 and len(base_amts) >= 2:
                    ratio = cur["amount"] / (sum(base_amts) / len(base_amts))
            else:
                ratio = cur["vr"] if cur["vr"] is not None and cur["vr"] > 0 else None
            if ratio is not None:
                cov[f"{bucket}_ratio_ok"] += 1
            else:
                cov[f"{bucket}_ratio_missing"] += 1

            # E：gap 步三证据齐备
            if is_gap:
                fill["gap_steps"] += 1
                if price is not None:
                    fill["gap_price_ok"] += 1
                if cur["amount"] is not None:
                    fill["gap_amount_ok"] += 1
                if price is not None and ratio is not None:
                    fill["gap_price_ratio_ok"] += 1

            # 后续走向：未来 ≤3 步 Δpct 均值
            fwd_vals = [elems[j]["pct"] - elems[j - 1]["pct"] for j in range(i + 1, min(i + 1 + FWD_STEPS, n))]
            fwd = float(np.mean(fwd_vals)) if fwd_vals else None

            # D：dv 步级复刻（抽样与真函数对齐自证）
            dv_state = step_dv_state(price, cur["pct"], prev["pct"], change_min, delta_min)
            if is_gap:
                dv_state_gap[dv_state] += 1
                dv_rankdir_gap_up_down["rank_up" if delta > delta_min else "rank_down" if delta < -delta_min else "rank_flat"] += 1
            elif not date_unknown:
                dv_state_same[dv_state] += 1
            if step_dv_checked < 2000 and step_counter % 500 == 0:
                real = compute_price_rank_divergence([e["change"] for e in elems[: i + 1]],
                                                     [e["pct"] for e in elems[: i + 1]], config)
                if real["state"] != dv_state:
                    step_dv_mismatch += 1
                step_dv_checked += 1

            # B/C：排名大跳 × 价格方向交叉
            if price is None:
                group = "price_missing"
            elif price > 0:
                group = "price_up"
            elif price < 0:
                group = "price_down"
            else:
                group = "price_flat"
            row = {"code": code, "fwd": fwd} if fwd is not None else None

            if is_gap and delta <= -rank_delta_min:
                dv_cross_gap_down[dv_state] += 1
                if ratio is not None:
                    ratio_gap_down[group].append(ratio)
                # 后续走向对比只纳入价方向明确组（up/down；flat/missing 单列不进对比）
                if row and group in ("price_up", "price_down"):
                    cross_gap_down[month].append({**row, "group": group})
                    cross_gap_down["ALL"].append({**row, "group": group})
            elif is_gap and delta >= rank_delta_min:
                if ratio is not None:
                    ratio_gap_up[group].append(ratio)
                if row and group in ("price_up", "price_down"):
                    cross_gap_up[month].append({**row, "group": group})
                    cross_gap_up["ALL"].append({**row, "group": group})
            elif not is_gap and not date_unknown and fwd is not None:
                # 同日对照组（全窗合并）
                if delta <= -rank_delta_min and group in ("price_up", "price_down"):
                    cross_same_down["ALL"].append({**row, "group": group})
                elif delta >= rank_delta_min and group in ("price_up", "price_down"):
                    cross_same_up["ALL"].append({**row, "group": group})

    # ── 汇总输出 ──
    months = sorted({m for m in step_total if m != "all"})
    coverage = {
        "stock_frame_total": stock_frame_total,
        "row_field_missing": dict(row_missing),
        "step_monthly": {m: step_total[m] for m in months},
        "step_bucket": dict(bucket_counter),
        "step_field_availability": {
            bucket: {
                "price_ok": cov[f"{bucket}_price_ok"], "price_missing": cov[f"{bucket}_price_missing"],
                "ratio_ok": cov[f"{bucket}_ratio_ok"], "ratio_missing": cov[f"{bucket}_ratio_missing"],
            }
            for bucket in ("gap", "same_day", "date_unknown")
        },
    }

    def summarize_cross(cross: dict[str, list[dict]]) -> dict:
        out = {}
        for key in set(cross.keys()) | {"ALL"}:
            rows = cross.get(key, [])
            if not rows:
                continue
            groups = defaultdict(list)
            for r in rows:
                groups[r["group"]].append(r)
            summary = {g: group_fwd_stats(gr) for g, gr in groups.items()}
            if key == "ALL" and groups.get("price_up") and groups.get("price_down"):
                summary["bootstrap_up_minus_down"] = clustered_bootstrap_mean_diff(
                    groups["price_up"], groups["price_down"], args.boot_iters, rng)
            out[key] = summary
        return out

    result = {
        "meta": {
            "script": "diagnose_lifecycle_q1_price_volume.py",
            "window": [args.start, args.end],
            "ratio_field": args.ratio_field,
            "frames": len(frames),
            "codes_with_series": len(series),
            "stock_frame_total": stock_frame_total,
            "rank_delta_min": rank_delta_min,
            "fwd_steps": FWD_STEPS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_iters": args.boot_iters,
            "dv_step_selfcheck": {"checked": step_dv_checked, "mismatch": step_dv_mismatch},
            "zero_api_calls": True,
        },
        "A_coverage": coverage,
        "B_gap_price_cross": {
            "gap_rank_drop_le_neg": summarize_cross(cross_gap_down),
            "gap_rank_spike_ge_pos": summarize_cross(cross_gap_up),
            "same_day_control_rank_drop": summarize_cross(cross_same_down),
            "same_day_control_rank_spike": summarize_cross(cross_same_up),
        },
        "C_amount_ratio_gap": {
            "rank_drop": {g: {"n": len(v), "median": float(np.median(v)) if v else None,
                              "p25": float(np.percentile(v, 25)) if v else None,
                              "p75": float(np.percentile(v, 75)) if v else None}
                          for g, v in ratio_gap_down.items()},
            "rank_spike": {g: {"n": len(v), "median": float(np.median(v)) if v else None,
                               "p25": float(np.percentile(v, 25)) if v else None,
                               "p75": float(np.percentile(v, 75)) if v else None}
                           for g, v in ratio_gap_up.items()},
        },
        "D_dv_overlap": {
            "dv_state_gap_steps": dict(dv_state_gap),
            "dv_state_same_day_steps": dict(dv_state_same),
            "dv_on_target_gap_rank_drop": dict(dv_cross_gap_down),
            "dv_gap_rank_dir_exposure": dict(dv_rankdir_gap_up_down),
            "note": "dv=compute_price_rank_divergence 四态（confirm_up/rank_lead/confirm_down/price_lead_warn，flat 归 unknown）；"
                    "dv 无量输入→量维度重叠率结构性为 0；dv 无 temporalGap 防御→gap 步 rankDir 即隔夜跳变。",
        },
        "E_gap_fill_rate": {
            "gap_steps": fill["gap_steps"],
            "price_ok": fill["gap_price_ok"],
            "amount_ok": fill["gap_amount_ok"],
            "price_and_ratio_ok": fill["gap_price_ratio_ok"],
            "price_ok_share": fill["gap_price_ok"] / fill["gap_steps"] if fill["gap_steps"] else None,
            "amount_ok_share": fill["gap_amount_ok"] / fill["gap_steps"] if fill["gap_steps"] else None,
            "both_share": fill["gap_price_ratio_ok"] / fill["gap_steps"] if fill["gap_steps"] else None,
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    print(json.dumps({
        "frames": len(frames),
        "codes": len(series),
        "steps_total": sum(step_total.values()),
        "gap_steps": bucket_counter["gap"],
        "dv_step_selfcheck": {"checked": step_dv_checked, "mismatch": step_dv_mismatch},
        "B_ALL_gap_rank_drop": result["B_gap_price_cross"]["gap_rank_drop_le_neg"].get("ALL"),
        "B_ALL_gap_rank_spike": result["B_gap_price_cross"]["gap_rank_spike_ge_pos"].get("ALL"),
        "B_ALL_same_day_rank_drop": result["B_gap_price_cross"]["same_day_control_rank_drop"].get("ALL"),
        "E_gap_fill": result["E_gap_fill_rate"],
        "D_dv_on_target": dict(dv_cross_gap_down),
        "elapsed_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=2, default=str))
    print(f"\nsaved -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
