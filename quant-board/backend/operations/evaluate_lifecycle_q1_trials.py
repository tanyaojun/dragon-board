# -*- coding: utf-8 -*-
"""生命周期 Q1 价量证据喂入 trial runner（2026-10-07 预登记合同 v1.1，判定线冻结于跑数前）。

合同：docs/ranktrend-tier-backtest/lifecycle-q1-preregistration.md（v1.1，Opus 审定 R1-R9 落实）
- 臂数冻结（C-3）：13 剂量臂 + 1 基线臂 = 14 次 replay + 1 组合臂（机械化选臂后内存内补跑）。
- 判定线（C-4，v1.1 冻结，跑后不得回看调线）：
  C-4.1 信号面无害线（三窗中 ≥2 窗 saEx 相对基线 ≥0 且无一窗 <−0.005）
        + 提交线（三窗均值相对改善 ≥+0.002 且 ≥1 窗 ≥+0.003）
        + 负效应线（三窗均值 <−0.003 止损）；全臂未达提交线=零效应阴性登记。
  C-4.2 交易面主判定（decision 窗 wrxpf 相对基线 ≥−0.003 且 maxDD ≤ 基线）；
        oos2/g1era 如实披露（oos2 wrxpf 相对基线 <−0.005 须显式交裁）。
  C-4.3 G1 收益侵蚀监控（不设线）：veto 触发率 rel 变化 + proxy 步翻转按 drop/spike 分列；
        veto 回升 >3.4% rel 须显式交裁。
  C-4.4 分辨力不反转：注入人群内 D3 口径价升/价跌 fwd 分离度不得收窄至基线 50% 以下
        （C-a 臂不适用——R4 裁定）。
  C-4.5 准入：≥1 臂同时过 C-4.1（无害+提交）+C-4.2 → 提交用户裁决落默认。
- 机械化选臂规则（C-3.4 冻结）：C-a 最优=3 臂中 C-4.1 三窗均值相对改善最大且过无害线者；
  C-c 最优=9 臂同规则；组合臂=两最优直接组合（不搜参）。
- 成本：全本地 replay，零 jev/付费模型调用（AGENTS §1.2-7）。

用法：python -m backend.operations.evaluate_lifecycle_q1_trials [--out data/reports/lifecycle-q1-trials.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import collect_flip_report, sa_excess_of
from backend.operations.track1_lifecycle_gate_trade import _assert_overrides_applied, _trade_metrics
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns

# ── 合同冻结常量 ──────────────────────────────────────────────
FULL_WINDOW = ("2026-04-15", "2026-10-07")
WINDOW_G1ERA = ("2026-09-13", "2026-10-07")  # 附加窗，只披露不设线
MAIN_WINDOWS = ("decision", "oos1", "oos2")
GAP_PV_POPULATION_DELTA_MIN = 10.0   # 注入人群 |ΔrankPct|≥10（与 lifecycle.py 冻结常量同源）
FWD_STEPS = 3                        # D3/C-4.4 口径：后续 ≤3 步
VETO_REL_COURT = 0.034               # C-4.3：veto 回升 >3.4% rel 须交裁（G1 −6.8% rel 之半）
SEP_FLOOR_RATIO = 0.5                # C-4.4：分离度不得收窄至基线 50% 以下
HARMLESS_NEG_WINDOW = -0.005         # C-4.1 无害线单窗下限
SUBMIT_MEAN = 0.002                  # C-4.1 提交线三窗均值
SUBMIT_SINGLE = 0.003                # C-4.1 提交线单窗
NEGATIVE_MEAN = -0.003               # C-4.1 负效应线
WRXPF_FLOOR = -0.003                 # C-4.2 wrxpf 相对基线下限（绝对差）
OOS2_COURT = -0.005                  # C-4.2 oos2 披露交裁线

# W0-1 fail-visible 守卫（2026-10-08）：ca_* 臂消费的 tierSynergyDivergenceVote 配置面已被
# W0-1 死票位摘除（from_patch 对未知键静默跳过=臂会静默塌缩成 baseline 假读数）。本 runner
# 为 Q1 历史归档（2026-10-07 已收官全 FAIL，台账 §22），误用必须显式失败而非静默假绿。
from backend.analysis.ranktrend.engine import RankTrendConfig as _W11GuardConfig

if hasattr(_W11GuardConfig(), "tierSynergyDivergenceVote"):
    raise RuntimeError(
        "Q1 runner 归档守卫：tierSynergyDivergenceVote 字段已由 W0-1 摘除后不应重新出现；"
        "若确需重开 dv 权重面，按纪律走新合同重新预登记，不得复用本归档 runner"
    )

ARMS: list[dict] = [
    {"key": "baseline", "desc": "G1 on（cross_day）+ Q1 全 off = 当前生产默认", "overrides": {}},
    # C-a 单独（3 剂量臂）：dv 权重（机制一 off）
    {"key": "ca_025", "desc": "C-a dv 权重 0.25", "overrides": {"tierSynergyDivergenceVote": 0.25}},
    {"key": "ca_050", "desc": "C-a dv 权重 0.50", "overrides": {"tierSynergyDivergenceVote": 0.5}},
    {"key": "ca_075", "desc": "C-a dv 权重 0.75", "overrides": {"tierSynergyDivergenceVote": 0.75}},
    # C-c 单独（9 剂量臂）：direction_gate × vrGate × P
    *[
        {"key": f"cc_vr{int(vr*10)}_p{p}",
         "desc": f"C-c direction_gate vrGate={vr} P={p}",
         "overrides": {"lifecycleGapPriceVolumeMode": "direction_gate",
                        "lifecycleGapPriceVolumeVrGate": vr,
                        "lifecycleGapPriceVolumeProxyP": float(p)}}
        for vr in (1.0, 1.5, 2.0) for p in (3, 5, 8)
    ],
]

_OVERRIDE_MISSING = object()


def load_frames() -> list[dict]:
    repo = MongoRepository(get_runtime_mongodb_database())
    return repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date=FULL_WINDOW[0], end_date=FULL_WINDOW[1],
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )


def window_frames(frames: list[dict], start: str, end: str) -> list[dict]:
    return [f for f in frames if start <= str(f.get("tradingDate") or "") <= end]


def build_pct_tables(frames: list[dict]) -> tuple[dict, dict]:
    """预计算 (帧索引, code) → 百分位 与 **跨日步** Δpct（上一「该股有 rank」帧口径，与
    analyze_cycle percentiles 相邻序列元素语义一致；跨日判定=相邻有 rank 帧 tradingDate 不同，
    与 G1 analyze_cycle 同语义）。供 C-4.3 翻转分解与 C-4.4 分离度复算（合同人群=跨日步）。"""
    pct_at: dict[tuple[int, str], float] = {}
    delta_at: dict[tuple[int, str], float] = {}
    last_pct: dict[str, float] = {}
    last_date: dict[str, str] = {}
    for fi, frame in enumerate(frames):
        date = str(frame.get("tradingDate") or "")
        ranks, total = attention_rank_lookup(frame.get("stocks") or [])
        for code, rank in ranks.items():
            pct = percentile_rank(rank, total)
            pct_at[(fi, code)] = pct
            if code in last_pct:
                # 只记跨日步（合同注入人群前置条件；同日步不计入 drop/spike 桶）
                if date and last_date.get(code) and date != last_date[code]:
                    delta_at[(fi, code)] = pct - last_pct[code]
            last_pct[code] = pct
            if date:
                last_date[code] = date
    return pct_at, delta_at


def _fwd_steps(pct_at: dict, fi: int, code: str, frame_count: int) -> float | None:
    """D3 口径 fwd：后续 ≤3 个「该股有 rank 帧」的逐步 pct 差分均值（无后续步 → None）。"""
    vals: list[float] = []
    prev = pct_at.get((fi, code))
    j = fi + 1
    while j < frame_count and len(vals) < FWD_STEPS:
        nxt = pct_at.get((j, code))
        if nxt is not None and prev is not None:
            vals.append(nxt - prev)
            prev = nxt
        j += 1
    return sum(vals) / len(vals) if vals else None


def evaluate_arm(arm: dict, frames: list[dict], want_track1: bool, pct_tables: tuple[dict, dict]) -> dict:
    """单臂：分窗一次 replay，读数（信号面）+（decision 窗）Track1 与翻转记录。"""
    config = RankTrendConfig.from_patch(arm["overrides"])
    _assert_overrides_applied(config, arm["overrides"])
    engine = RankTrendPythonEngine(config=config)
    out: dict = {"desc": arm["desc"], "windows": {}, "track1": {}}
    for name, (start, end) in {**WINDOWS, "g1era": WINDOW_G1ERA}.items():
        wf = window_frames(frames, start, end)
        if not wf:
            out["windows"][name] = {"empty": True}
            continue
        t0 = time.time()
        signals = engine.replay(wf, meta={})
        reading = _signal_metrics(signals, wf)
        out["windows"][name] = reading
        print(f"[{arm['key']}] {name}: saEx={reading['saEx']} veto={reading['vetoTriggerRate']} "
              f"sa={reading['saFrames']} ({time.time() - t0:.0f}s)", file=sys.stderr)
        if name == "decision":
            # 翻转记录（C-4.3）：JSON 安全键 "帧索引|code" → [veto, proxy 步标记]
            flip_rec: dict[str, list] = {}
            for idx, s in enumerate(signals):
                rt = s.get("rankTrend") or {}
                lc = (rt.get("observation") or {}).get("lifecycle") or {}
                code = str(s.get("code") or "")
                metrics = (rt.get("cycle") or {}).get("metrics") or {}
                flip_rec[f"{reading['frameIndexBySignal'][idx]}|{code}"] = [
                    bool(lc.get("veto")), bool(metrics.get("gapPriceVolumeProxy")),
                ]
            out["decisionFlipRecord"] = flip_rec
            if want_track1:
                out["track1"]["decision"] = _track1(config, wf)
                m = out["track1"]["decision"]
                print(f"[{arm['key']}] track1 decision: trades={m.get('tradeCount')} "
                      f"wrxpf={m.get('winRateXpf')} ret={m.get('totalReturn')} dd={m.get('maxDD')}",
                      file=sys.stderr)
    # 帧索引映射只服务本函数翻转记录构造，不进产物（体积控制）
    for name in out["windows"]:
        if isinstance(out["windows"][name], dict):
            out["windows"][name].pop("frameIndexBySignal", None)
    return out


def _signal_metrics(signals: list[dict], wf: list[dict]) -> dict:
    syn = tier_forward_returns(signals, wf, horizon=1, dimension="synergy")
    flip = collect_flip_report(signals)
    veto_n = 0
    sa_n = 0
    total = 0
    frame_index_by_signal: list[int] = []
    index_by_snapshot = {str(f.get("snapshotId")): i for i, f in enumerate(wf)}
    for s in signals:
        rt = s.get("rankTrend") or {}
        lc = (rt.get("observation") or {}).get("lifecycle") or {}
        syn_tier = (rt.get("observation") or {}).get("synergy", {}).get("signalTier")
        total += 1
        veto_n += 1 if lc.get("veto") else 0
        sa_n += 1 if syn_tier in ("S", "A") else 0
        frame_index_by_signal.append(index_by_snapshot.get(str(s.get("snapshotId")), -1))
    return {
        "signalCount": total,
        "saEx": sa_excess_of(syn),
        "flipRates": flip.get("flip_rates"),
        "vetoTriggerRate": round(veto_n / total, 5) if total else None,
        "vetoFrames": veto_n,
        "saFrames": sa_n,
        "frameIndexBySignal": frame_index_by_signal,
    }


def _track1(config: RankTrendConfig, wf: list[dict]) -> dict:
    from backend.core.backtest.execution import TradeSimulator

    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(wf, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
    sim = TradeSimulator().run(wf, signals, {"entryStrategy": "rank_trend_candidate"})
    return _trade_metrics(sim)


def signal_verdict(arm_read: dict, base_read: dict) -> dict:
    """C-4.1（v1.1：无害线+提交线+负效应线）。"""
    sa_rel = {}
    for w in MAIN_WINDOWS:
        a = arm_read["windows"].get(w, {}).get("saEx")
        b = base_read["windows"].get(w, {}).get("saEx")
        sa_rel[w] = (a - b) if (a is not None and b is not None) else None
    vals = [v for v in sa_rel.values() if v is not None]
    if len(vals) < 3:
        return {"sa_rel": sa_rel, "harmless": False, "submit": False, "negative": None,
                "mean_rel": None, "note": "样本不足（saEx None），按不合格处理（fail-visible）"}
    mean_rel = sum(vals) / 3
    harmless = sum(1 for v in vals if v >= 0.0) >= 2 and all(v > HARMLESS_NEG_WINDOW for v in vals)
    submit = mean_rel >= SUBMIT_MEAN and max(vals) >= SUBMIT_SINGLE
    negative = mean_rel < NEGATIVE_MEAN
    return {"sa_rel": {w: round(v, 5) if v is not None else None for w, v in sa_rel.items()},
            "harmless": harmless, "submit": submit, "negative": negative,
            "mean_rel": round(mean_rel, 5)}


def track1_verdict(arm_track: dict, base_track: dict) -> dict:
    """C-4.2 主判定（decision 窗）。"""
    a, b = arm_track.get("winRateXpf"), base_track.get("winRateXpf")
    dd_a, dd_b = arm_track.get("maxDD"), base_track.get("maxDD")
    if a is None or b is None or dd_a is None or dd_b is None:
        return {"pass": False, "note": "Track1 指标缺失（fail-visible）",
                "arm": arm_track, "base": base_track}
    return {
        "wrxpf_abs_diff": round(a - b, 5),
        "wrxpf_rel": round(a / b - 1, 5) if b not in (None, 0) else None,
        "wrxpf_pass": (a - b) >= WRXPF_FLOOR,
        "maxDD": {"arm": dd_a, "base": dd_b,
                  # 回撤深度（负数域）不恶化 = |arm| ≤ |base|；首轮实现误用 ≤ 直比（把改善判成恶化）
                  "pass": abs(dd_a) <= abs(dd_b)},
        "tradeCount": {"arm": arm_track.get("tradeCount"), "base": base_track.get("tradeCount")},
        "pass": (a - b) >= WRXPF_FLOOR and abs(dd_a) <= abs(dd_b),
    }


def flip_decomposition(arm_read: dict, base_read: dict, delta_at: dict, frames: list[dict]) -> dict:
    """C-4.3：veto 翻转按 解除/新增 × drop/spike 分列（R9 建议采纳：分列披露）。"""
    arm_rec = arm_read.get("decisionFlipRecord") or {}
    base_rec = base_read.get("decisionFlipRecord") or {}
    out = {"released": {"drop": 0, "spike": 0, "unclassified": 0},
           "added": {"drop": 0, "spike": 0, "unclassified": 0}}
    for key, value in arm_rec.items():
        arm_veto, _ = value
        base_veto = base_rec.get(key, (None, False))[0]
        if base_veto is None or base_veto == arm_veto:
            continue  # 只统计翻转步（veto 状态变化）
        # drop/spike 分列按注入人群标识（|Δpct|≥10 跨日步）——flip 记录键 "fi|code" 反解
        try:
            fi_s, code = str(key).split("|", 1)
            delta = delta_at.get((int(fi_s), code))
        except ValueError:
            delta = None
        bucket = "unclassified"
        if delta is not None and delta <= -GAP_PV_POPULATION_DELTA_MIN:
            bucket = "drop"
        elif delta is not None and delta >= GAP_PV_POPULATION_DELTA_MIN:
            bucket = "spike"
        kind = "released" if (base_veto and not arm_veto) else "added"
        out[kind][bucket] += 1
    return out


def separation_check(frames: list[dict], pct_tables: tuple[dict, dict]) -> dict:
    """C-4.4（C-c 臂）：注入人群（全窗跨日步 ∧ |Δpct|≥10）内 D3 口径价升/价跌 fwd 分离度
    （数据层复算，与 diagnose_lifecycle_q1_price_volume.py 的 B 桶同构——fwd=后续 ≤3 有 rank
    帧逐步差分均值）。注：该复算只依赖数据不依赖臂 config（R4：对臂是常量），baseline/各臂
    同值，线自动过——如实登记常量性质；臂效应由 C-4.3 翻转步 fwd 披露补充。"""
    pct_at, delta_at = pct_tables
    frame_count = len(frames)
    up_rows: list[float] = []
    down_rows: list[float] = []
    # 一次性扫描：注入人群步（|Δpct|≥10）按当日 change 归组，fwd=D3 口径
    change_at: dict[tuple[int, str], float] = {}
    for fi, frame in enumerate(frames):
        for st in frame.get("stocks") or []:
            code = str(st.get("code") or "")
            try:
                change_at[(fi, code)] = float(st.get("change"))
            except (TypeError, ValueError):
                pass
    for (fi, code), delta in delta_at.items():
        if abs(delta) < GAP_PV_POPULATION_DELTA_MIN:
            continue
        # 跨日判定：该步与上一有 rank 帧不同 tradingDate
        ch = change_at.get((fi, code))
        if ch is None:
            continue
        fwd = _fwd_steps(pct_at, fi, code, frame_count)
        if fwd is None:
            continue
        (up_rows if ch > 0 else down_rows if ch < 0 else []).append(fwd)
    up_mean = sum(up_rows) / len(up_rows) if up_rows else None
    down_mean = sum(down_rows) / len(down_rows) if down_rows else None
    sep = (up_mean - down_mean) if (up_mean is not None and down_mean is not None) else None
    return {"population": {"up_n": len(up_rows), "down_n": len(down_rows)},
            "up_fwd_mean": round(up_mean, 4) if up_mean is not None else None,
            "down_fwd_mean": round(down_mean, 4) if down_mean is not None else None,
            "separation": round(sep, 4) if sep is not None else None,
            "note": "数据层复算，对全部臂同值（常量）；R4 裁定 C-a 臂本线不适用"}


def pick_best(arm_results: dict, keys: list[str]) -> str | None:
    """机械化选臂（C-3.4）：C-4.1 三窗均值相对改善最大且过无害线者。"""
    best_key, best_mean = None, None
    for key in keys:
        v = arm_results[key]["verdict"]["signal"]
        if not v["harmless"]:
            continue
        mean_rel = v["mean_rel"]
        if mean_rel is None:
            continue
        if best_mean is None or mean_rel > best_mean:
            best_key, best_mean = key, mean_rel
    return best_key


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/lifecycle-q1-trials.json")
    args = ap.parse_args()
    t0 = time.time()
    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)
    out_path = Path(args.out)
    pct_tables = build_pct_tables(frames)
    separation = separation_check(frames, pct_tables)
    print(f"separation(check): {separation}", file=sys.stderr)

    results: dict[str, dict] = {}
    base_read = None
    checkpoint_path = out_path.parent / (out_path.stem + "-checkpoint.json")
    for arm in ARMS:
        t1 = time.time()
        read = evaluate_arm(arm, frames, want_track1=True, pct_tables=pct_tables)
        results[arm["key"]] = {"desc": arm["desc"], "read": read}
        if arm["key"] == "baseline":
            base_read = read
        # 逐臂 checkpoint 增量落盘（上一轮全量算完在最终序列化一步崩掉、Track1 全失的教训）
        checkpoint_path.write_text(
            json.dumps({"partial": True, "completed_arms": list(results),
                        "separation_check": separation, "results": results},
                       ensure_ascii=False, default=str),
            encoding="utf-8")
        print(f"[{arm['key']}] done ({time.time() - t1:.0f}s) -> checkpoint", file=sys.stderr)

    base = results["baseline"]["read"]
    # baseline 补跑 oos2/g1era Track1（过线臂披露窗的同窗对照，C-4.2）
    base_config = RankTrendConfig()
    for wname, (s, e) in (("oos2", WINDOWS["oos2"]), ("g1era", WINDOW_G1ERA)):
        wf = window_frames(frames, s, e)
        base["track1"][wname] = _track1(base_config, wf)
        print(f"[baseline] track1 {wname} done", file=sys.stderr)
    # 第一轮判定（信号面+Track1 主判定）
    for arm in ARMS[1:]:
        key = arm["key"]
        read = results[key]["read"]
        results[key]["verdict"] = {
            "signal": signal_verdict(read, base),
            "track1_decision": track1_verdict(read["track1"].get("decision") or {}, base["track1"].get("decision") or {}),
            "flip": flip_decomposition(read, base, pct_tables[1], frames),
        }

    # 机械化选臂（C-3.4）→ 组合臂（1 剂量臂）
    ca_best = pick_best(results, ["ca_025", "ca_050", "ca_075"])
    cc_best = pick_best(results, [a["key"] for a in ARMS if a["key"].startswith("cc_")])
    combo: dict | None = None
    if ca_best and cc_best:
        ca_ov = next(a["overrides"] for a in ARMS if a["key"] == ca_best)
        cc_ov = next(a["overrides"] for a in ARMS if a["key"] == cc_best)
        combo_arm = {"key": "combo_best", "desc": f"组合 {ca_best} × {cc_best}（机械化选臂，直接组合）",
                     "overrides": {**ca_ov, **cc_ov}}
        t1 = time.time()
        read = evaluate_arm(combo_arm, frames, want_track1=True, pct_tables=pct_tables)
        results["combo_best"] = {"desc": combo_arm["desc"], "read": read}
        results["combo_best"]["verdict"] = {
            "signal": signal_verdict(read, base),
            "track1_decision": track1_verdict(read["track1"].get("decision") or {}, base["track1"].get("decision") or {}),
            "flip": flip_decomposition(read, base, pct_tables[1], frames),
            "combo_of": {"ca": ca_best, "cc": cc_best},
        }
        print(f"[combo_best] done ({time.time() - t1:.0f}s)", file=sys.stderr)
    else:
        combo = {"note": f"选臂失败 ca_best={ca_best} cc_best={cc_best}（无臂过无害线），组合臂不跑"}

    # 过线臂的 oos2/g1era Track1 披露（C-4.2）+ g1era 信号面已在第一轮读数
    key_to_overrides = {a["key"]: a["overrides"] for a in ARMS}
    key_to_overrides["combo_best"] = {**(key_to_overrides.get(ca_best or "", {})),
                                       **(key_to_overrides.get(cc_best or "", {}))}
    for key, item in results.items():
        if key == "baseline":
            continue
        v = item["verdict"]
        if v["signal"]["harmless"] and v["signal"]["submit"] and v["track1_decision"]["pass"]:
            config = RankTrendConfig.from_patch(key_to_overrides.get(key, {}))
            for wname, (s, e) in (("oos2", WINDOWS["oos2"]), ("g1era", WINDOW_G1ERA)):
                wf = window_frames(frames, s, e)
                item["read"]["track1"][wname] = _track1(config, wf)
                print(f"[{key}] track1 {wname} done", file=sys.stderr)
            for wname in ("oos2", "g1era"):
                a = item["read"]["track1"].get(wname, {})
                b = base["track1"].get(wname, {})
                if a.get("winRateXpf") is not None and b.get("winRateXpf") not in (None, 0):
                    item["verdict"][f"{wname}_wrxpf_rel"] = round(a["winRateXpf"] / b["winRateXpf"] - 1, 5)
                    if wname == "oos2" and item["verdict"][f"{wname}_wrxpf_rel"] < OOS2_COURT:
                        item["verdict"]["oos2_court"] = "须显式交裁（oos2 wrxpf 相对基线 < −0.005）"

    out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 1),
            "full_window": FULL_WINDOW,
            "windows_main": dict(WINDOWS), "window_g1era": WINDOW_G1ERA,
            "frozen_lines": {
                "harmless": {"windows_ge2_zero": True, "single_floor": HARMLESS_NEG_WINDOW},
                "submit": {"mean": SUBMIT_MEAN, "single": SUBMIT_SINGLE},
                "negative_mean": NEGATIVE_MEAN,
                "wrxpf_floor_abs": WRXPF_FLOOR, "maxDD": "≤ 基线",
                "veto_rel_court": VETO_REL_COURT, "separation_floor_ratio": SEP_FLOOR_RATIO,
                "oos2_court": OOS2_COURT,
            },
            "contract": "lifecycle-q1-preregistration.md v1.1（判定线冻结于跑数前）",
        },
        "separation_check": separation,
        "arm_selection": {"ca_best": ca_best, "cc_best": cc_best, "combo": combo},
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)  # 完整落盘后撤检查点
    print(json.dumps({"out": str(out_path),
                      "arm_selection": out["arm_selection"],
                      "verdicts": {k: {"signal": v["verdict"]["signal"],
                                        "track1": v["verdict"]["track1_decision"].get("pass")}
                                    for k, v in results.items() if k != "baseline"}},
                     ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
