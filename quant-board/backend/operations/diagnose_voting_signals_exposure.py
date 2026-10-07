# -*- coding: utf-8 -*-
"""四投票信号 R1/D1 诊断包（backend/operations，2026-10-07）。

预登记合同：docs/ranktrend-tier-backtest/reasoning-corpus-voting-signals.md §12.0/§12.2
（判定线跑数前冻结，跑后不得回看调线；§12.2 六项审定修正已冻结纳入）。

一次默认配置数据 pass（只读、零行为变化、零 config 写回）。R1 部分（§12.0）：
- 时间正规化暴露度 / jump 降级轴分解 / 四维+synergy 档位分布 / S 守门维断言 /
  fund 直方图 / len 桶 / persist_eligible / 双动量一致率 / res D∧buy；
D1 部分（§12.2 合同，2026-10-07 用户裁决开跑）：
- regime 四态分列（strong/normal/weak/retreat；预注册对比对=strong vs retreat）；
- h8 前视读数（帧索引 +8 前视 percentile delta + 分位桶基线，逐字镜像
  tier_monotonicity.tier_forward_returns 口径：raw rank + 帧内股票数）；
- T1 三态 trigger（cross_day / same_day_gap / same_day_adjacent）× h8 excess
  （含 dual_mom_disagree 混淆分层）；
- T3 warming 模拟（len4-8 ∧ res unknown ∧ market_ctx_ok；同日子窗差分；cap C/B 两档
  票值 0.375/0.525；只投 buy 非负票；crossed_B/crossed_A 计数）；
- T4 persist 分层（eligible_n5 / B_not_eligible / other）× h8；
- T5 新入榜模拟（entry_strength/confirm 通过率 @vr 1.0/1.25/1.5/would-be S b1/b2/
  would-be synergy S）；
- jump 事件表加列（trigger_type / pass @vr 1.25/1.5 / chg·vr bucket × h8）。

W0-2 增补（2026-10-07，ranktrend-vote-structure-redesign-plan.md；判定线跑数前冻结）：
- amount 杠杆重估列：amount_ratio 可算率（分窗分月）/ 可算帧 ar 分布 / amount_score≠0 帧占比 /
  可算帧 h8 分层（ar≥amountRatioHigh / ≤amountRatioLow / 中间带，含 strong/retreat 对照列）。
- **预声明判定线（冻结，跑后不得调）**：可算率 <20% → 维持归档；≥20% 且 h8 分层差 ≥0.02 →
  立项「amount 进档位判定」L2 预登记（喂 tier 方向，非调 score——§4.2 量价①根因）。
  分层差操作口径 = decision 窗三对分层差（high−mid / low−mid / high−low）取 |max|，
  判据量 = excess_mean（分位桶基线校正，本脚本 D1 框架标准读数；raw mean_ret 同列披露）。
  判定 population=decision 窗（脚本冻结惯例），分窗分月全披露供严格口径复核。
- 实施：主 vp 调用保持不传 amount_ratio（存量读数零漂移）；amount 列走第二次
  compute_volume_price_score 调用（amount_ratio=ar），逐帧自证 tier 零漂移（vp_tier_drift 计数，
  期望 0——tier 由 quadrant/fund/reasons 决定不消费 score）。

窗口对齐：与 optimization.data_windows.WINDOWS 标准窗一致（decision 04-15~07-31 /
oos1 08-15~08-31 / oos2 09-01~09-30 全月）+ midgap 08-01~08-14 报告列；
主判定 population=decision 窗（§12.0 冻结）。

口径简化（自证线覆盖）：sampleQuality 恒过时间线检查（可能高估 res 参与率，对照 D-a 登记）；
主 vp 调用不传 amount_ratio（W0-2 amount 列走独立二次调用，存量读数零漂移）；h8 population=全部股帧
（与 harness 的 replay 信号 population≈等价，len=1 有信号）。

用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_voting_signals_exposure \
      [--end 2026-09-30] [--out data/reports/voting-signals-exposure-diagnosis.json] [--skip-engine-check]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank, clamp
from backend.analysis.ranktrend.engine.runtime import (
    _lifecycle_tier,
    _rank_trend_tier,
    _confirm_jump,
    detect_rank_jumps,
    frame_market_median,
    frame_market_median_percentile,
)
from backend.analysis.ranktrend.ranking.volume_price import _synergy_tier, compute_amount_ratio, compute_volume_price_score
from backend.analysis.ranktrend.trend.cross_section import compute_cross_section
from backend.analysis.ranktrend.trend.lifecycle import analyze_cycle, lifecycle_decision
from backend.analysis.ranktrend.trend.risk import analyze_risk, market_regime
from backend.analysis.ranktrend.trend.technical import analyze_technical
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

HISTORY_WINDOW = 50  # replay 默认窗口（runtime.replay_frame_at window_size=50）
RANK_PERIODS = (3, 5, 8, 13, 21)
PERSIST_NS = (3, 5, 10)
FUND_BINS = (0.5, 1.0, 2.0, 3.0, 5.0)

WINDOW_RANGES = (
    ("decision", "2026-04-15", "2026-07-31"),
    ("midgap", "2026-08-01", "2026-08-14"),
    ("oos1", "2026-08-15", "2026-08-31"),
    ("oos2", "2026-09-01", "2026-09-30"),  # 与 data_windows.WINDOWS 标准窗对齐（全月）
)


def window_label(trading_date: str) -> str:
    for label, start, end in WINDOW_RANGES:
        if start <= trading_date <= end:
            return label
    return "outside"


def _finite(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def compose_base_signal(technical: dict, config: RankTrendConfig) -> tuple[str, float]:
    """compose_decision 的 base 复刻（risk/reversal 只影响 final/confidence，不影响 base/tier）。"""

    def cross_signal(cross: str) -> str:
        return "buy" if cross == "golden" else "sell" if cross == "death" else "hold"

    components = [
        {"signal": technical["signals"]["direction"]["signal"], "rawScore": clamp(technical["signals"]["direction"]["score"], -1, 1), "weight": config.directionWeight},
        {"signal": technical["signals"]["acceleration"]["signal"], "rawScore": clamp(technical["signals"]["acceleration"]["score"], -1, 1), "weight": config.accelerationWeight},
        {"signal": technical["signals"]["zeroCross"]["signal"], "rawScore": clamp(technical["signals"]["zeroCross"]["score"], -1, 1), "weight": config.crossWeight},
        {"signal": cross_signal(technical["macd"]["cross"]), "rawScore": clamp(technical["macd"]["rawScore"], -1, 1), "weight": config.macdWeight},
    ]
    if config.maWeight > 0:
        ma_cross = technical.get("maCross") or {}
        components.append({
            "signal": cross_signal(str(ma_cross.get("cross") or "none")),
            "rawScore": clamp(float(ma_cross.get("rawScore") or 0.0), -1, 1),
            "weight": config.maWeight,
        })
    combined = sum(c["rawScore"] * c["weight"] for c in components)
    buy_count = len([c for c in components if c["signal"] == "buy"])
    sell_count = len([c for c in components if c["signal"] == "sell"])
    base = "hold"
    if buy_count >= config.decisionMinAgreement and sell_count <= config.decisionMaxOpposition and combined >= config.buyScoreThreshold:
        base = "hold" if config.requireMacdGoldenCross else "buy"
    elif sell_count >= config.decisionMinAgreement and buy_count <= config.decisionMaxOpposition and combined <= config.sellScoreThreshold:
        base = "sell"
    return base, clamp(combined, -1, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-15")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--out", default="data/reports/voting-signals-exposure-diagnosis.json")
    ap.add_argument("--skip-engine-check", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    config = RankTrendConfig()

    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date=args.start, end_date=args.end,
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    frames.sort(key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    frame_dates = [str(f.get("tradingDate") or "") for f in frames]
    labels = [window_label(d) for d in frame_dates]
    attention_maps = [attention_rank_lookup(f.get("stocks") or []) for f in frames]
    # W0-2：逐帧 code→row 映射（同引擎 _stock_lookup 语义）——amount 历史按 rank 序列元素对齐收集
    stock_row_maps: list[dict[str, dict]] = [
        {str(s.get("code") or ""): s for s in (f.get("stocks") or []) if s.get("code")} for f in frames
    ]
    # D1 前置：regime 四态 + raw rank 前视表（h8 逐字镜像 tier_forward_returns：raw rank/帧内行数）
    regime_states: list[str] = []
    raw_rank_maps: list[dict[str, float]] = []
    raw_totals: list[int] = []
    regime_states = [str(market_regime(f, config).get("state") or "missing") for f in frames]
    for f in frames:
        rmap: dict[str, float] = {}
        for s in f.get("stocks") or []:
            c = str(s.get("code") or "")
            r = _finite(s.get("rank"))
            if c and r is not None:
                rmap[c] = r
        raw_rank_maps.append(rmap)
        raw_totals.append(len(f.get("stocks") or []))
    print(f"frames={len(frames)} labels={dict(Counter(labels))} regimes={dict(Counter(regime_states))}", file=sys.stderr)

    engine = None if args.skip_engine_check else RankTrendPythonEngine(config=config)
    engine_check_indices = [] if args.skip_engine_check else [len(frames) // 2, len(frames) // 2 + 1, len(frames) - 2]
    engine_signals: dict[str, dict] = {}

    # ── 聚合容器 ──
    exposure: dict[str, Counter] = defaultdict(Counter)   # metric -> {n, cross_day, non_adj}；"_engine" 子树存自证计数
    jump_dec: dict[str, Counter] = defaultdict(Counter)   # window -> {event_jump_n, pass, fail_chg_only, fail_vr_only, fail_both}
    tier_dist: dict[str, dict] = defaultdict(lambda: defaultdict(Counter))  # window -> dim -> tier counts
    s_gate: dict[str, Counter] = defaultdict(Counter)     # window -> {s_total, s_cs_pos, s_cs_notpos, s_lc_downgraded}
    len_buckets: dict[str, Counter] = defaultdict(Counter)
    momentum_consist: dict[str, Counter] = defaultdict(Counter)  # window -> {n_profile_score, agree, n_short_relmom, agree_sr}
    res_struct: dict[str, Counter] = defaultdict(Counter)        # window -> {ok, insuff, d_and_buy, total}
    fund_vals: dict[str, list] = defaultdict(list)
    fund_ctx: dict[str, Counter] = defaultdict(Counter)    # window -> {rise_volume_n, fund_pos_n}
    persist_elig: dict[str, Counter] = defaultdict(Counter)  # window -> {N: count, frames: n}
    macd_ctx: dict[str, Counter] = defaultdict(Counter)    # window -> {multi_day_series, n_ge22}
    # W0-2 容器
    amount_ctx: dict[str, Counter] = defaultdict(Counter)          # window -> {total, computable, score_ne0, vp_tier_drift}
    amount_ctx_month: dict[str, Counter] = defaultdict(Counter)    # "YYYY-MM" -> 同上
    ar_vals: dict[str, list] = defaultdict(list)                   # window -> 可算帧 ar 值（分布/占比）

    # ── D1 容器（regime_states/raw_rank_maps/raw_totals 已在前置块构建）──
    h8_base: dict[str, list] = defaultdict(lambda: [[0, 0] for _ in range(10)])   # window -> bucket -> [n, pos]
    h8_base_sum: dict[str, list] = defaultdict(lambda: [[0.0, 0] for _ in range(10)])  # window -> bucket -> [sum_delta, n]
    # h8 分层 cell：key=(window, cell_name, bucket) -> [n, pos, sum_delta]；cell_name 由调用方拼
    h8_cells_skipped: Counter = Counter()   # (window, reason) -> n（h8 无前视/缺 rank，fail-visible）
    warming_stats: dict[str, Counter] = defaultdict(Counter)   # window -> 各种计数
    warming_h8: Counter = Counter()    # (window, stratum, bucket) -> [n, pos]
    ne_stats: dict[str, Counter] = defaultdict(Counter)        # window -> new-entry 计数
    jump_h8: Counter = Counter()       # (window, key, bucket) -> [n, pos]

    stock_frames_total = 0

    def h8_of(fi: int, code: str) -> tuple[float, int] | None:
        """h8 前视（帧索引 +8，逐字镜像 tier_forward_returns：raw rank/帧内股票数，>0 双检）。"""
        f8 = fi + 8
        if f8 >= len(frames):
            return None
        cur = raw_rank_maps[fi].get(code)
        fut = raw_rank_maps[f8].get(code)
        if not cur or not fut:
            return None
        cur_pct = percentile_rank(cur, raw_totals[fi])
        fut_pct = percentile_rank(fut, raw_totals[f8])
        if cur_pct <= 0 or fut_pct <= 0:
            return None
        return ((fut_pct - cur_pct) / 100.0, min(9, int(cur_pct // 10)))

    def h8_add(window: str, cell: str, sample: tuple[float, int] | None) -> None:
        if sample is None:
            h8_cells_skipped[(window, "no_forward_or_rank")] += 1
            return
        delta, bucket = sample
        h8_base[window][bucket][0] += 1
        h8_base[window][bucket][1] += int(delta > 0)
        h8_base_sum[window][bucket][0] += delta
        h8_base_sum[window][bucket][1] += 1
        key = (window, cell, bucket)
        h8_cell_acc[key][0] += 1
        h8_cell_acc[key][1] += int(delta > 0)
        h8_cell_acc[key][2] += delta

    h8_cell_acc: dict = defaultdict(lambda: [0, 0, 0.0])

    def span_trigger(dates: list[str], fis: list[int], start_idx: int) -> str:
        """序列元素区间 [start_idx, end] 的三态 trigger：任一相邻对跨日→cross_day；
        否则任一相邻对帧距 ≥2→same_day_gap；否则 same_day_adjacent。"""
        cross = False
        gap = False
        for k in range(max(1, start_idx), len(dates)):
            if dates[k] != dates[k - 1]:
                cross = True
            elif fis[k] - fis[k - 1] >= 2:
                gap = True
        if cross:
            return "cross_day"
        return "same_day_gap" if gap else "same_day_adjacent"

    def exp_add(win: str, metric: str, n: int, cross_day: int, non_adj: int) -> None:
        c = exposure[win].setdefault(metric, Counter())
        c["n"] += n
        c["cross_day"] += cross_day
        c["non_adj"] += non_adj

    for fi, frame in enumerate(frames):
        label = labels[fi]
        ranks_map, total = attention_maps[fi]
        history_start = max(0, fi - HISTORY_WINDOW + 1)
        market_short_change, market_sample = frame_market_median(frames, fi)
        market_median_pct = frame_market_median_percentile(frame)

        if not args.skip_engine_check and fi in engine_check_indices:
            # 自证对照必须走带 market_ctx 的全量链（replay）；replay_frame_at 不传 market_ctx，
            # resonance 恒缺失（2026-10-07 首跑 13.6% 假 mismatch 的根因），不可用于共振比对。
            lo = max(0, fi - HISTORY_WINDOW + 1)
            snap_id = str(frame.get("snapshotId") or "")
            engine_signals = {
                str(s.get("code")): s.get("rankTrend") or {}
                for s in engine.replay(frames[lo : fi + 1], warmup_count=1, window_size=HISTORY_WINDOW)
                if str(s.get("snapshotId") or "") == snap_id
            }

        for stock in frame.get("stocks") or []:
            code = str(stock.get("code") or "")
            if not code:
                continue
            ranks: list[float] = []
            pcts: list[float] = []
            elem_dates: list[str] = []
            elem_fi: list[int] = []
            amounts: list[Any] = []  # W0-2：与 ranks/pcts 元素严格对齐（同生产 _replay_stock 语义）
            for hj in range(history_start, fi + 1):
                r = attention_maps[hj][0].get(code)
                if r is None:
                    continue
                ranks.append(float(r))
                pcts.append(percentile_rank(float(r), attention_maps[hj][1]))
                elem_dates.append(frame_dates[hj])
                elem_fi.append(hj)
                amounts.append((stock_row_maps[hj].get(code) or {}).get("amount"))
            stock_frames_total += 1
            ln = len(pcts)
            regime = regime_states[fi]
            len_buckets[label]["total"] += 1
            len_buckets[label]["len_1"] += int(ln == 1)
            len_buckets[label]["len_2_3"] += int(2 <= ln <= 3)
            len_buckets[label]["len_4_8"] += int(4 <= ln <= 8)
            len_buckets[label]["len_9_21"] += int(9 <= ln <= 21)
            len_buckets[label]["len_ge22"] += int(ln >= 22)

            # MACD/MA 跨日渗入（报告列）
            if ln >= 2:
                multi_day = any(elem_dates[k] != elem_dates[k - 1] for k in range(1, ln))
                macd_ctx[label]["n_ge22"] += int(ln >= 22)
                macd_ctx[label]["multi_day_series"] += int(multi_day)

            # ── 暴露度（端点日期语义；≥2 帧）──
            if ln >= 2:
                cd = elem_dates[-1] != elem_dates[-2]
                na = cd or (elem_fi[-1] - elem_fi[-2]) >= 2
                exp_add(label, "cs_last_pair", 1, int(cd), int(na))
                for n in RANK_PERIODS:
                    if ln >= n + 1:
                        cd_n = elem_dates[-1] != elem_dates[-1 - n]
                        # 序列内部相邻对里是否有同日非相邻（端点同日也可能中间有洞）
                        na_n = cd_n or any(
                            (elem_dates[k] != elem_dates[k - 1]) or (elem_fi[k] - elem_fi[k - 1]) >= 2
                            for k in range(ln - n, ln)
                        )
                        exp_add(label, f"rank_period_{n}", 1, int(cd_n), int(na_n))
                if ln >= 4:
                    cd3 = elem_dates[-1] != elem_dates[-4]
                    exp_add(label, "zero_trigger(3)", 1, int(cd3), int(cd3))
                if ln >= 6:
                    cd5 = elem_dates[-1] != elem_dates[-6]
                    exp_add(label, "zero_confirm(5)", 1, int(cd5), int(cd5))
            if ln >= config.resonanceMidWindowBars + 1:
                cd_s = elem_dates[-1] != elem_dates[-1 - config.resonanceShortWindowBars]
                cd_m = elem_dates[-1] != elem_dates[-1 - config.resonanceMidWindowBars]
                path_win = range(ln - config.resonancePathWindowBars, ln)
                cd_p = any(elem_dates[k] != elem_dates[k - 1] for k in path_win if k >= 1)
                exp_add(label, "res_short_start", 1, int(cd_s), int(cd_s))
                exp_add(label, "res_mid_start", 1, int(cd_m), int(cd_m))
                exp_add(label, "res_path_win", 1, int(cd_p), int(cd_p))

            # ── 各维生产函数（同引擎口径）──
            fallback = {
                "displayChange": pcts[-1] - pcts[-2] if ln >= 2 else 0.0,
                "stockChange": stock.get("change"),
                "volumeRatio": stock.get("volumeRatio"),
                "zlje": stock.get("zlje"),
                "zljzb": stock.get("zljzb"),
            }
            technical = analyze_technical(pcts, config, fallback)

            # rank
            base_signal, combined = compose_base_signal(technical, config)
            rank_tier, _ = _rank_trend_tier(base_signal, combined, config)
            tier_dist[label]["rank"][rank_tier] += 1

            # ── D1/T1：三态 trigger × h8（dual_mom_disagree 混淆分层；dm 仅 ln≥22 有定义）──
            comp_v = _finite(technical["momentumProfile"].get("composite")) or 0.0
            score_v = _finite(technical.get("momentumScore")) or 0.0
            dm = "na" if ln < 22 else ("1" if (comp_v != 0 and score_v != 0 and (comp_v > 0) != (score_v > 0)) else "0")
            h8s = h8_of(fi, code)
            h8_add(label, f"all@{regime}", h8s)
            if ln >= 2:
                trig = span_trigger(elem_dates, elem_fi, ln - 1)
                h8_add(label, f"t1|cs_delta_last|{trig}|{regime}|{dm}", h8s)
            for n in RANK_PERIODS:
                if ln >= n + 1:
                    trig = span_trigger(elem_dates, elem_fi, ln - n)
                    h8_add(label, f"t1|rank_p{n}|{trig}|{regime}|{dm}", h8s)
            if ln >= 4:
                h8_add(label, f"t1|zero_trigger3|{span_trigger(elem_dates, elem_fi, ln - 3)}|{regime}|{dm}", h8s)
            if ln >= 6:
                h8_add(label, f"t1|zero_confirm5|{span_trigger(elem_dates, elem_fi, ln - 5)}|{regime}|{dm}", h8s)
            if ln >= config.resonanceMidWindowBars + 1:
                h8_add(label, f"t1|res_short|{span_trigger(elem_dates, elem_fi, ln - config.resonanceShortWindowBars)}|{regime}|{dm}", h8s)
                h8_add(label, f"t1|res_mid|{span_trigger(elem_dates, elem_fi, ln - config.resonanceMidWindowBars)}|{regime}|{dm}", h8s)
                h8_add(label, f"t1|res_path|{span_trigger(elem_dates, elem_fi, ln - config.resonancePathWindowBars)}|{regime}|{dm}", h8s)

            # vp（主调用不传 amount_ratio：档位不消费 score，存量读数零漂移）
            vp = compute_volume_price_score(
                code, stock.get("change"), stock.get("volumeRatio"),
                stock.get("zlje"), stock.get("zljzb"), config,
            )
            tier_dist[label]["vp"][vp.get("signalTier") or "unknown"] += 1

            # ── W0-2：amount 杠杆重估列（判定线冻结见文件头）──
            ar = compute_amount_ratio(amounts, config)
            _ac = amount_ctx[label]
            _acm = amount_ctx_month[(frame_dates[fi] or "unknown")[:7]]
            _ac["total"] += 1
            _acm["total"] += 1
            if ar is not None:
                _ac["computable"] += 1
                _acm["computable"] += 1
                ar_vals[label].append(ar)
                # 独立二次调用仅供 amount 列；tier 漂移自证（期望 0）
                vp_ar = compute_volume_price_score(
                    code, stock.get("change"), stock.get("volumeRatio"),
                    stock.get("zlje"), stock.get("zljzb"), config, amount_ratio=ar,
                )
                _ac["vp_tier_drift"] += int(vp_ar.get("signalTier") != vp.get("signalTier"))
                amt_score = _finite((vp_ar.get("breakdown") or {}).get("amount"))
                _ac["score_ne0"] += int(amt_score is not None and abs(amt_score) > 0)
                band = "high" if ar >= config.amountRatioHigh else "low" if ar <= config.amountRatioLow else "mid"
                h8_add(label, f"amount|{band}|{regime}", h8s)
                h8_add(label, f"amount|{band}|all", h8s)
            if vp.get("quadrant") == "rise_volume":
                fund_ctx[label]["rise_volume_n"] += 1
                fund_v = _finite((vp.get("breakdown") or {}).get("fund"))
                if fund_v is not None and fund_v > 0:
                    fund_ctx[label]["fund_pos_n"] += 1
                    fund_vals[label].append(fund_v)

            # cs（len=1 也投票：绝对档降级）
            cs = compute_cross_section(pcts, market_median_pct, config)
            cs_tier = str(cs.get("signalTier") or "unknown")
            tier_dist[label]["cs"][cs_tier] += 1

            # jump（分解在 confirm 前）+ res
            jump = detect_rank_jumps(
                pcts, ranks,
                delta_pct=config.jumpDeltaPct,
                reset_lookback=config.jumpResetLookback,
                sustain_count=config.jumpSustainCount,
            )
            if jump.get("event") == "jump" and jump.get("direction") in ("buy", "sell"):
                jd = jump_dec[label]
                jd["event_jump_n"] += 1
                chg = _finite(stock.get("change"))
                vr = _finite(stock.get("volumeRatio"))
                direction = jump["direction"]
                ok_chg = chg is not None and (
                    chg >= config.jumpConfirmChangeMin if direction == "buy" else chg <= -config.jumpConfirmChangeMin
                )
                ok_vr = vr is not None and vr >= config.jumpConfirmVolumeRatioMin
                if ok_chg and ok_vr:
                    jd["pass"] += 1
                elif not ok_chg and ok_vr:
                    jd["fail_chg_only"] += 1
                elif ok_chg and not ok_vr:
                    jd["fail_vr_only"] += 1
                else:
                    jd["fail_both"] += 1
                # D1/T2：vr 剂量通过标记 + trigger_type + bucket × h8
                ok_125 = ok_chg and vr is not None and vr >= 1.25
                ok_150 = ok_chg and vr is not None and vr >= 1.5
                jd["pass_v125"] += int(ok_125)
                jd["pass_v150"] += int(ok_150)
                trig_j = span_trigger(elem_dates, elem_fi, ln - 1) if ln >= 2 else "na"
                vr_b = "lt1" if (vr is None or vr < 1.0) else "1_125" if vr < 1.25 else "125_150" if vr < 1.5 else "ge150"
                chg_b = ("ge3" if direction == "buy" else "le-3") if ok_chg else ("lt3" if direction == "buy" else "gt-3")
                h8_add(label, f"jump|{'pass' if ok_chg and ok_vr else 'fail'}_v10|{trig_j}", h8s)
                h8_add(label, f"jump|{'pass' if ok_125 else 'fail'}_v125|{trig_j}", h8s)
                h8_add(label, f"jump|{'pass' if ok_150 else 'fail'}_v150|{trig_j}", h8s)
                h8_add(label, f"jump|vr_{vr_b}|{trig_j}", h8s)
                h8_add(label, f"jump|{chg_b}|{trig_j}", h8s)
            jump = _confirm_jump(jump, stock, config)
            res = analyze_rank_resonance_compat(
                pcts, jump, market_short_change, market_sample, market_median_pct, config
            )
            res_tier = str(res.get("signalTier") or "unknown")
            res_dir = str(res.get("direction") or "")
            tier_dist[label]["res"][res_tier] += 1
            rs = res_struct[label]
            rs["total"] += 1
            rs["ok"] += int(res.get("status") == "ok")
            rs["d_and_buy"] += int(res_tier == "D" and res_dir == "buy")

            # lifecycle（G1 时间键接线，同生产默认 cross_day）
            cyc = analyze_cycle(ranks, pcts, config, time_keys=elem_dates)
            risk = analyze_risk(
                pcts[-1] if pcts else 0.0, technical, cyc,
                fallback["zlje"], fallback["zljzb"], fallback["volumeRatio"], config,
            )
            decision = lifecycle_decision(
                cyc["rawStage"], cyc["stage"], cyc["transition"], float(cyc["confidence"]),
                cyc["metrics"], risk, technical["momentumProfile"], config=config,
            )
            action = str(decision.get("action") or "caution")
            lc_tier = _lifecycle_tier(cyc["stage"], action)[0]

            # synergy（pm/dv 票权 0 不传）
            syn_tier, _ = _synergy_tier(
                res_tier, res_dir, rank_tier, base_signal,
                vp.get("signalTier"), vp.get("direction"),
                lc_tier, config, cs_tier=cs_tier,
            )
            tier_dist[label]["synergy"][syn_tier] += 1
            if syn_tier == "S":
                sg = s_gate[label]
                sg["s_total"] += 1
                sg["s_cs_pos"] += int(cs_tier in ("A", "B"))
                sg["s_cs_notpos"] += int(cs_tier not in ("A", "B"))

            # ── D1/T3：warming 模拟（len∈[4,8] ∧ market_ctx_ok；同日子窗差分；cap C/B 两档只投 buy）──
            if 4 <= ln <= 8:
                ws = warming_stats[label]
                ws["len4_8_total"] += 1
                ctx_ok = market_short_change is not None and market_sample >= config.resonanceMinMarketSampleCount
                if ctx_ok:
                    ws["eligible"] += 1
                    j_w = None
                    for k_w in range(max(0, ln - 1 - config.resonanceShortWindowBars), ln - 1):
                        if elem_dates[k_w] == elem_dates[-1]:
                            j_w = k_w
                    if j_w is None:
                        ws["eligible_no_sameday"] += 1
                        h8_add(label, f"warming|no_vote|{regime}", h8s)
                        h8_add(label, "warming|no_vote|all", h8s)
                    else:
                        rel_mom_w = clamp((pcts[-1] - pcts[j_w] - market_short_change) / config.resonanceMomentumScale, -1, 1)
                        if rel_mom_w <= config.resonanceDirectionThreshold:
                            ws["eligible_hold"] += 1
                            h8_add(label, f"warming|no_vote|{regime}", h8s)
                            h8_add(label, "warming|no_vote|all", h8s)
                        else:
                            ws["eligible_buy"] += 1
                            h8_add(label, f"warming|buy|{regime}", h8s)
                            h8_add(label, "warming|buy|all", h8s)
                            for cap_tier, tag in (("C", "w1"), ("B", "w2")):
                                sim_tier_w, _ = _synergy_tier(
                                    cap_tier, "buy", rank_tier, base_signal,
                                    vp.get("signalTier"), vp.get("direction"),
                                    lc_tier, config, cs_tier=cs_tier,
                                )
                                ws[f"vote_{tag}"] += 1
                                ws[f"crossed_B_{tag}"] += int(sim_tier_w in ("S", "A", "B") and syn_tier not in ("S", "A", "B"))
                                ws[f"crossed_A_{tag}"] += int(sim_tier_w in ("A", "S") and syn_tier not in ("A", "S"))
                                ws[f"sim_S_{tag}"] += int(sim_tier_w == "S")

            # 双动量一致率（len>=22：momentumScore 来自 momentum_data）
            if ln >= 22:
                mc = momentum_consist[label]
                comp = _finite(technical["momentumProfile"].get("composite")) or 0.0
                score = _finite(technical.get("momentumScore")) or 0.0
                if comp != 0 and score != 0:
                    mc["n_profile_score"] += 1
                    mc["agree"] += int((comp > 0) == (score > 0))
                if res.get("status") == "ok":
                    short_v = _finite(technical["momentumProfile"].get("short")) or 0.0
                    rel = _finite(res.get("relativeMomentum")) or 0.0
                    if short_v != 0 and rel != 0:
                        mc["n_short_relmom"] += 1
                        mc["agree_sr"] += int((short_v > 0) == (rel > 0))

            # persist_eligible（N∈{3,5,10}；pct≥90 ∧ 近N均值≥85）+ T4 分层 h8
            pe = persist_elig[label]
            pe["frames"] += 1
            elig5 = False
            for n in PERSIST_NS:
                if ln >= n:
                    window = pcts[-n:]
                    ok = pcts[-1] >= 90.0 and sum(window) / n >= 85.0
                    pe[n] += int(ok)
                    if n == 5:
                        elig5 = ok
            strat = "eligible_n5" if elig5 else ("B_not_eligible" if cs_tier == "B" else "other")
            h8_add(label, f"persist|{strat}|{regime}", h8s)
            h8_add(label, f"persist|{strat}|all", h8s)

            # ── D1/T5：新入榜模拟（len==1；would-be S b1/b2 + would-be synergy S）──
            if ln == 1:
                ne = ne_stats[label]
                ne["n"] += 1
                pct_now = pcts[-1]
                strength = clamp((pct_now - 50.0) / config.resonanceEntryStrengthScale, 0, 1)
                chg_v = _finite(stock.get("change"))
                vr_v = _finite(stock.get("volumeRatio"))
                ok_chg_ne = chg_v is not None and chg_v >= config.jumpConfirmChangeMin
                p10 = ok_chg_ne and vr_v is not None and vr_v >= config.jumpConfirmVolumeRatioMin
                p125 = ok_chg_ne and vr_v is not None and vr_v >= 1.25
                p150 = ok_chg_ne and vr_v is not None and vr_v >= 1.5
                ne["pct_gt50"] += int(pct_now > 50)
                ne["strength_ge03"] += int(strength >= 0.3)
                ne["chg_ok"] += int(ok_chg_ne)
                ne["pass_v10"] += int(p10)
                ne["pass_v125"] += int(p125)
                ne["pass_v150"] += int(p150)
                ne["would_S_b1"] += int(p10 and strength > 0)
                ne["would_S_b2"] += int(p10 and strength >= 0.3)
                sim_tier_ne, _ = _synergy_tier(
                    "S", "buy", rank_tier, base_signal,
                    vp.get("signalTier"), vp.get("direction"),
                    lc_tier, config, cs_tier=cs_tier,
                )
                ne["would_syn_S_b1"] += int(p10 and strength > 0 and sim_tier_ne == "S")
                ne["would_syn_S_b2"] += int(p10 and strength >= 0.3 and sim_tier_ne == "S")
                h8_add(label, "new_entry_all", h8s)
                if p10 and strength >= 0.3:
                    h8_add(label, "new_entry_wouldS_b2", h8s)

            # 引擎自证（检查帧逐股比对四维+synergy）
            if not args.skip_engine_check and fi in engine_check_indices:
                eng = engine_signals.get(code) or {}
                obs = eng.get("observation") or {}
                for dim, my_tier, eng_tier in (
                    ("rank", rank_tier, (obs.get("rankTrend") or {}).get("signalTier")),
                    ("vp", vp.get("signalTier"), (obs.get("volumePrice") or {}).get("signalTier")),
                    ("cs", cs_tier, (obs.get("crossSection") or {}).get("signalTier")),
                    ("res", res_tier, (eng.get("resonance") or {}).get("signalTier")),
                    ("synergy", syn_tier, (obs.get("synergy") or {}).get("signalTier")),
                ):
                    matched = str(eng_tier or "unknown") == str(my_tier)
                    exposure["_engine"][f"{dim}|{'match' if matched else 'mismatch'}"] += 1

    # ── 聚合输出 ──
    def shares(c: Counter, key: str) -> float | None:
        n = c.get("n", 0)
        return round(c[key] / n, 4) if n else None

    exposure_out = {}
    for win, metrics in sorted(exposure.items()):
        if win == "_engine":
            continue
        exposure_out[win] = {
            name: {"n": c["n"], "cross_day_share": shares(c, "cross_day"), "non_adjacent_share": shares(c, "non_adj")}
            for name, c in sorted(metrics.items())
        }

    jump_out = {
        win: {k: int(v) for k, v in sorted(c.items())} for win, c in sorted(jump_dec.items())
    }
    tier_out = {
        win: {dim: dict(sorted(cnt.items())) for dim, cnt in dims.items()}
        for win, dims in sorted(tier_dist.items())
    }
    sg_out = {
        win: {k: int(v) for k, v in sorted(c.items())} for win, c in sorted(s_gate.items())
    }
    len_out = {
        win: {k: round(v / c["total"], 4) if k != "total" else int(v) for k, v in sorted(c.items())}
        for win, c in sorted(len_buckets.items())
    }
    mc_out = {
        win: {
            "profile_vs_score_agree": round(c["agree"] / c["n_profile_score"], 4) if c.get("n_profile_score") else None,
            "n_profile_score": int(c.get("n_profile_score", 0)),
            "short_vs_relmom_agree": round(c["agree_sr"] / c["n_short_relmom"], 4) if c.get("n_short_relmom") else None,
            "n_short_relmom": int(c.get("n_short_relmom", 0)),
        }
        for win, c in sorted(momentum_consist.items())
    }
    res_out = {
        win: {
            "participation": round(c["ok"] / c["total"], 4) if c["total"] else None,
            "d_and_buy_share": round(c["d_and_buy"] / c["total"], 4) if c["total"] else None,
            "total": int(c["total"]),
        }
        for win, c in sorted(res_struct.items())
    }
    fund_out = {}
    for win, vals in sorted(fund_vals.items()):
        if not vals:
            fund_out[win] = {"n": 0}
            continue
        arr = np.array(vals, dtype=float)
        fund_out[win] = {
            "n": int(arr.size),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "share_below": {str(b): round(float((arr < b).mean()), 4) for b in FUND_BINS},
            "rise_volume_n": int(fund_ctx[win]["rise_volume_n"]),
            "fund_pos_n": int(fund_ctx[win]["fund_pos_n"]),
        }
    persist_out = {
        win: {
            f"elig_share_N{n}": round(c.get(n, 0) / c["frames"], 4) if c.get("frames") else None
            for n in PERSIST_NS
        }
        for win, c in sorted(persist_elig.items())
    }
    engine_compare = exposure.get("_engine", Counter())
    engine_stats = {}
    for dim in ("rank", "vp", "cs", "res", "synergy"):
        m = int(engine_compare.get(f"{dim}|match", 0))
        mm = int(engine_compare.get(f"{dim}|mismatch", 0))
        engine_stats[dim] = {"match": m, "mismatch": mm,
                             "rate": round(m / (m + mm), 4) if (m + mm) else None}

    # ── D1 h8 聚合 ──
    def h8_excess(window: str, cell: str) -> dict:
        acc_n = acc_pos = 0
        acc_sum = 0.0
        w_acc = w_mean = 0.0
        base = h8_base[window]
        base_sum = h8_base_sum[window]
        for b in range(10):
            n_b, pos_b, sum_b = h8_cell_acc.get((window, cell, b), [0, 0, 0.0])
            if not n_b:
                continue
            acc_n += n_b
            acc_pos += pos_b
            acc_sum += sum_b
            if base[b][0]:
                w_acc += n_b * (base[b][1] / base[b][0])
                w_mean += n_b * (base_sum[b][0] / base_sum[b][1])
        if not acc_n:
            return {"n": 0}
        acc_v = acc_pos / acc_n
        mean_v = acc_sum / acc_n
        base_acc_v = w_acc / acc_n
        base_mean_v = w_mean / acc_n
        return {"n": acc_n, "acc": round(acc_v, 4), "excess_acc": round(acc_v - base_acc_v, 4),
                "mean_ret": round(mean_v, 6), "excess_mean": round(mean_v - base_mean_v, 6)}

    h8_base_out = {
        w: {f"b{b}": {"n": arr[b][0], "acc": round(arr[b][1] / arr[b][0], 4) if arr[b][0] else None,
                      "mean_ret": round(h8_base_sum[w][b][0] / h8_base_sum[w][b][1], 6) if h8_base_sum[w][b][1] else None}
            for b in range(10) if arr[b][0]}
        for w, arr in h8_base.items()
    }
    cells_by_window: dict[str, dict] = defaultdict(dict)
    for (w, cell, _b) in list(h8_cell_acc.keys()):
        if cell not in cells_by_window[w]:
            cells_by_window[w][cell] = h8_excess(w, cell)
    h8_cells_out = {w: dict(sorted(c.items())) for w, c in sorted(cells_by_window.items())}

    def h8_excess_merged(window: str, prefixes: tuple[str, ...]) -> dict:
        """跨 regime/dm 合并的 h8 excess（cell 前缀匹配）。"""
        acc_n = acc_pos = 0
        acc_sum = 0.0
        w_acc = w_mean = 0.0
        base = h8_base[window]
        base_sum = h8_base_sum[window]
        for (w, cell, b), (n_b, pos_b, sum_b) in h8_cell_acc.items():
            if w != window or not n_b or not any(cell.startswith(p) for p in prefixes):
                continue
            acc_n += n_b
            acc_pos += pos_b
            acc_sum += sum_b
            if base[b][0]:
                w_acc += n_b * (base[b][1] / base[b][0])
                w_mean += n_b * (base_sum[b][0] / base_sum[b][1])
        if not acc_n:
            return {"n": 0}
        acc_v = acc_pos / acc_n
        mean_v = acc_sum / acc_n
        base_acc_v = w_acc / acc_n
        base_mean_v = w_mean / acc_n
        return {"n": acc_n, "acc": round(acc_v, 4), "excess_acc": round(acc_v - base_acc_v, 4),
                "mean_ret": round(mean_v, 6), "excess_mean": round(mean_v - base_mean_v, 6)}

    # T1 判定直接读数：feature × trigger（跨 regime/dm 合并）
    t1_collapsed: dict[str, dict] = defaultdict(dict)
    for f in ("cs_delta_last", "res_short", "res_mid", "res_path", "rank_p3", "rank_p5",
              "rank_p8", "rank_p13", "rank_p21", "zero_trigger3", "zero_confirm5"):
        for trig in ("cross_day", "same_day_gap", "same_day_adjacent"):
            merged = h8_excess_merged("decision", (f"t1|{f}|{trig}|",))
            if merged.get("n"):
                t1_collapsed[f][trig] = merged
    t1_collapsed_out = {f: dict(sorted(t.items())) for f, t in sorted(t1_collapsed.items())}

    warming_out = {}
    for w, c in sorted(warming_stats.items()):
        warming_out[w] = {k: int(v) for k, v in sorted(c.items())}
    # warming h8 按 regime 聚合（分桶读数）
    warming_h8_out = {}
    for w in sorted(warming_stats.keys()):
        warming_h8_out[w] = {
            regime_k: h8_excess(w, f"warming|buy|{regime_k}")
            for regime_k in ("strong", "normal", "weak", "retreat")
        }
    ne_h8_out = {w: {"all": h8_excess(w, "new_entry_all"),
                     "wouldS_b2": h8_excess(w, "new_entry_wouldS_b2")} for w in sorted(ne_stats.keys())}
    jump_h8_out = {}
    for w in sorted(jump_dec.keys()):
        jump_h8_out[w] = {
            name: h8_excess(w, name)
            for name in sorted({k[1] for k in h8_cell_acc
                                if k[0] == w and k[1].startswith("jump|")})
        }
    persist_h8_out = {}
    for w in sorted(persist_elig.keys()):
        persist_h8_out[w] = {
            name: h8_excess(w, name)
            for name in sorted({k[1] for k in h8_cell_acc
                                if k[0] == w and k[1].startswith("persist|")})
        }

    # ── W0-2：amount 杠杆重估读出（判定线冻结见文件头）──
    def _ar_quantiles(vals: list) -> dict | None:
        if not vals:
            return None
        arr = np.array(vals, dtype=float)
        return {f"p{p}": round(float(np.percentile(arr, p)), 3) for p in (10, 25, 50, 75, 90)}

    amount_out = {}
    for win, c in sorted(amount_ctx.items()):
        n, k = int(c["total"]), int(c["computable"])
        vals = ar_vals.get(win) or []
        arr = np.array(vals, dtype=float) if vals else None
        amount_out[win] = {
            "total": n,
            "computable": k,
            "computable_rate": round(k / n, 4) if n else None,
            "amount_score_ne0_share": round(int(c["score_ne0"]) / k, 4) if k else None,
            "vp_tier_drift": int(c["vp_tier_drift"]),
            "share_ge_high": round(float((arr >= config.amountRatioHigh).mean()), 4) if arr is not None and arr.size else None,
            "share_le_low": round(float((arr <= config.amountRatioLow).mean()), 4) if arr is not None and arr.size else None,
            "ar_quantiles": _ar_quantiles(vals),
        }
    amount_month_out = {
        m: {
            "total": int(c["total"]),
            "computable": int(c["computable"]),
            "computable_rate": round(int(c["computable"]) / c["total"], 4) if c["total"] else None,
        }
        for m, c in sorted(amount_ctx_month.items())
    }
    amount_h8_out = {}
    for w in sorted(amount_ctx.keys()):
        amount_h8_out[w] = {band: h8_excess(w, f"amount|{band}|all") for band in ("high", "mid", "low")}

    def _amount_strata_diffs(strata: dict) -> dict:
        def _pick(band: str, key: str):
            v = strata.get(band) or {}
            return v.get(key) if v.get("n") else None
        out = {}
        for a, b in (("high", "mid"), ("low", "mid"), ("high", "low")):
            ea, eb = _pick(a, "excess_mean"), _pick(b, "excess_mean")
            ra, rb = _pick(a, "mean_ret"), _pick(b, "mean_ret")
            out[f"{a}_vs_{b}"] = {
                "excess_mean_diff": round(ea - eb, 4) if (ea is not None and eb is not None) else None,
                "mean_ret_diff": round(ra - rb, 6) if (ra is not None and rb is not None) else None,
            }
        return out

    amount_diffs_by_window = {w: _amount_strata_diffs(s) for w, s in amount_h8_out.items()}

    # ── 冻结判定线评估（§12.0 冻结 + §12.2 修正，只对照不调线）──
    dec_exp = exposure_out.get("decision", {})
    q1_metrics = {k: v.get("cross_day_share") for k, v in dec_exp.items()
                  if k.startswith(("cs_last_pair", "res_", "rank_period_", "zero_"))}
    q1_hits = {k: v for k, v in q1_metrics.items() if v is not None and v >= 0.15}
    q1_all_below5 = all(v is None or v < 0.05 for v in q1_metrics.values())
    dec_fund = fund_out.get("decision", {})
    fund_below1 = (dec_fund.get("share_below") or {}).get("1.0")
    dec_len = len_out.get("decision", {})
    warm_share = dec_len.get("len_4_8")  # §12.2 修正：R4 线按 [4,8] 精确占比
    dec_ne = dict(ne_stats.get("decision", {}))
    ne_n = dec_ne.get("n", 0)
    dec_persist = persist_out.get("decision", {})
    persist_n5 = dec_persist.get("elig_share_N5")
    dec_sg = sg_out.get("decision", {})
    s_gate_violation = dec_sg.get("s_cs_notpos", 0)
    # T4 阶段1：persist 分层 h8 差（overall + strong/retreat 对比对）
    def _ex(cell):
        v = h8_excess("decision", cell)
        return v.get("excess_acc") if isinstance(v, dict) else None
    t4_stage1 = {"lines": {"pos": 0.02, "neg": -0.02}}
    for scope in ("all", "strong", "retreat"):
        e_el = _ex(f"persist|eligible_n5|{scope}")
        e_bne = _ex(f"persist|B_not_eligible|{scope}")
        diff = round(e_el - e_bne, 4) if (e_el is not None and e_bne is not None) else None
        t4_stage1[scope] = {"excess_eligible_n5": e_el, "excess_B_not_eligible": e_bne, "diff": diff}
    d_all = t4_stage1["all"]["diff"]
    t4_stage1["verdict_overall"] = (
        "正态优先" if d_all is not None and d_all >= 0.02
        else "负态优先" if d_all is not None and d_all <= -0.02
        else "归档（|差|<0.02 或读数不足）"
    )
    d_s = t4_stage1["strong"]["diff"]
    d_r = t4_stage1["retreat"]["diff"]
    t4_stage1["regime_contrast"] = (
        "两桶同向" if (d_s is not None and d_r is not None and (d_s >= 0) == (d_r >= 0))
        else "反号→阶段2挂起" if (d_s is not None and d_r is not None)
        else "读数不足"
    )

    # W0-2 冻结判定线评估（判定 population=decision 窗；分窗分月全披露）
    dec_amount_rate = (amount_out.get("decision") or {}).get("computable_rate")
    dec_amount_diffs = amount_diffs_by_window.get("decision", {})
    _diff_vals = [v["excess_mean_diff"] for v in dec_amount_diffs.values() if v["excess_mean_diff"] is not None]
    _max_abs_diff = max((abs(v) for v in _diff_vals), default=None)
    _total_all = sum(int(c["total"]) for c in amount_ctx.values())
    _comp_all = sum(int(c["computable"]) for c in amount_ctx.values())
    if dec_amount_rate is None or dec_amount_rate < 0.20:
        amount_verdict = "维持归档（可算率<20%）"
    elif _max_abs_diff is not None and _max_abs_diff >= 0.02:
        amount_verdict = "达立项线→L2 预登记候选（amount 喂 tier）"
    else:
        amount_verdict = "维持归档（分层差<0.02）"
    amount_gate = {
        "thresholds": {"high": config.amountRatioHigh, "low": config.amountRatioLow, "period": config.amountRatioPeriod},
        "line_rate": 0.20, "line_strata_diff": 0.02,
        "computable_rate_decision": dec_amount_rate,
        "computable_rate_total": round(_comp_all / _total_all, 4) if _total_all else None,
        "computable_rate_by_month": {m: v["computable_rate"] for m, v in amount_month_out.items()},
        "decision_strata_diffs": dec_amount_diffs,
        "strata_diffs_by_window": amount_diffs_by_window,
        "max_abs_excess_mean_diff_decision": _max_abs_diff,
        "verdict": amount_verdict,
    }

    gates = {
        "q1_open_case": {"hits_ge15": q1_hits, "all_below_5": q1_all_below5,
                         "verdict": "立项L2" if q1_hits else ("归档" if q1_all_below5 else "观察带5-15%")},
        "r2b_fund": {"fund_lt_1_share": fund_below1, "line_open": 0.10, "line_lazy": 0.03,
                     "verdict": ("可预登记" if (fund_below1 or 0) >= 0.10 else ("缓议" if (fund_below1 or 0) >= 0.03 else "放弃"))},
        "r4_warming": {"len_4_8_share": warm_share, "line": 0.03,
                       "verdict": ("可预登记" if (warm_share or 0) >= 0.03 else "放弃")},
        "r5_persist": {"elig_share_N5": persist_n5, "line_open": 0.01, "line_drop": 0.003,
                       "verdict": ("可预登记" if (persist_n5 or 0) >= 0.01 else ("放弃" if (persist_n5 or 0) < 0.003 else "观察带"))},
        "t4_stage1": t4_stage1,
        "t5_new_entry": {"n": ne_n,
                         "p_pct_gt50": round(dec_ne.get("pct_gt50", 0) / ne_n, 4) if ne_n else None,
                         "p_pass_v10": round(dec_ne.get("pass_v10", 0) / ne_n, 4) if ne_n else None,
                         "would_S_b2": dec_ne.get("would_S_b2", 0),
                         "would_syn_S_b2": dec_ne.get("would_syn_S_b2", 0)},
        "amount_leverage": amount_gate,
        "s_gate_selfcheck": {"s_cs_notpos_decision": s_gate_violation,
                             "verdict": "PASS" if s_gate_violation == 0 else "FAIL(接线bug，读数作废)"},
    }

    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "start": args.start, "end": args.end,
            "frames_loaded": len(frames),
            "stock_frames_total": stock_frames_total,
            "preregistration": "reasoning-corpus-voting-signals.md §12.0/§12.2（判定线冻结；六项修正已纳入）",
            "population_primary": "decision 窗（序列≥2 股帧为主判定；len=1 单列新入榜桶）",
            "regime_distribution": dict(Counter(regime_states)),
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "b0_anchors": {
            "saEx_three_window": {"decision": 0.1450, "oos1": 0.0983, "oos2": 0.1172},
            "provenance": "生命周期轮同日（2026-10-07 14:15）trial runner G1 行=现默认（lifecycleTimeGapStrictness=cross_day），口径 data_windows.WINDOWS 标准窗（oos2=09-01~09-30 全月）；Track 1 decision 172 笔 wrxpf 0.4140 / oos2 76 笔 0.1660（14:25 报告）",
            "track1": {"decision": {"trades": 172, "wrxpf": 0.4140, "maxDD": -0.2231},
                       "oos2": {"trades": 76, "wrxpf": 0.1660, "maxDD": -0.1817}},
        },
        "exposure": exposure_out,
        "macd_ma_context": {w: dict(c) for w, c in sorted(macd_ctx.items())},
        "jump_decomposition": jump_out,
        "tier_distribution": tier_out,
        "s_gate_check": sg_out,
        "len_buckets": len_out,
        "momentum_consistency": mc_out,
        "res_structure": res_out,
        "fund_histogram": fund_out,
        "persist_eligible": persist_out,
        "self_check_engine": engine_stats,
        "h8_bucket_baselines": h8_base_out,
        "h8_cells": h8_cells_out,
        "t1_collapsed": t1_collapsed_out,
        "warming": {"stats": warming_out, "h8_by_regime": warming_h8_out},
        "new_entry": {"stats": {w: {k: int(v) for k, v in sorted(c.items())} for w, c in sorted(ne_stats.items())},
                      "h8": ne_h8_out},
        "jump_h8": jump_h8_out,
        "persist_h8": persist_h8_out,
        "w02_amount": {
            "by_window": amount_out,
            "by_month": amount_month_out,
            "h8_strata_by_window": amount_h8_out,
            "strata_diffs_by_window": amount_diffs_by_window,
            "gate": amount_gate,
        },
        "gates": gates,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "out": str(out_path),
        "elapsed_sec": report["meta"]["elapsed_sec"],
        "engine_selfcheck": engine_stats,
        "res_participation": {w: v["participation"] for w, v in res_out.items()},
        "gates": gates,
        "t4_stage1": gates.get("t4_stage1"),
        "t5_new_entry": gates.get("t5_new_entry"),
        "amount_leverage": gates.get("amount_leverage"),
    }, ensure_ascii=False, indent=1))


def analyze_rank_resonance_compat(
    pcts: list[float],
    jump: dict,
    market_short_change: float | None,
    market_sample: int,
    market_median_pct: float | None,
    config: RankTrendConfig,
) -> dict:
    """analyze_rank_resonance 输入包装（runtime.py:1393-1416 同构；sampleQuality 简化为恒过）。"""
    from backend.analysis.ranktrend.engine.runtime import analyze_rank_resonance

    return analyze_rank_resonance(
        {
            "percentiles": pcts,
            "sampleQuality": {},
            "marketMedianShortChange": (
                market_short_change if market_short_change is not None else float("nan")
            ),
            "marketSampleCount": market_sample or 0,
            "marketMedianPercentile": market_median_pct,
            "jump": {
                "direction": jump.get("direction") or "hold",
                "event": jump.get("event") or "none",
                "events": jump.get("events") or [],
            },
            "entry": {"isNew": len(pcts) == 1, "currentAttentionPercentile": pcts[-1] if pcts else 0},
        },
        config,
    )


if __name__ == "__main__":
    main()
