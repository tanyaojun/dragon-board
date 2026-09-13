# -*- coding: utf-8 -*-
"""TS 五因子权重实证评估 harness（backend/operations，2026-09-13，权重重定义任务）。

用户命题：技术信号五因子（direction/acceleration/zeroCross/macd/maCross）已归一化，
但权重 0.24/0.20/0.16/0.20/0.20 是历史比例归一化继承值（阶段 21.8），从未按实证定值；
要求"按各因子正向贡献率重新科学评估和重新定义各个因子权重"。

评估两层（用户确认口径）：
  层 1 事件级区分度：五因子 buy/sell 事件/状态帧 h1 synergy 统计（_tier_summary 字段：
    saEx/spearman/passHard/unknownRate/distribution）+ sampleCount/rawHits
    （tier_forward_returns + signal_filter，分位桶基线子集内重算，阶段 17.4 同口径）；
  层 2 边际贡献：留一法（weight→0 ×5）+ 半权法（weight×0.5 ×5）evaluate_gate trial，
    权重类全部走 from_patch 归一化（和=1，与 baseline 同量纲、单变量可归因）；
  提案复核：证据汇总出权重提案后，加 proposal trial 组跑 Track 2 判定卡
    （C1 决策窗 ≥+3% / C2 OOS 同向 / C3 passHard 不掉 / C4 分桶 / C5 翻转率）。

结论规则（先列后跑，防拍脑袋）：
  移除三窗受损 + 事件级三窗正向 → 有正贡献，按边际损失量级定权重占比；
  移除持平/改善 → 权重归 0 关闭观察（机制保留不删实现）；
  提案须过判定卡且跨窗方向一致，跨窗不一致取保守值（接近现权重）。

窗口纪律：决策窗 04-15~07-31 + OOS-1 08-15~31 + OOS-2 09-01~12；FINAL(8/1-8/14)
冻结（assert_not_frozen purpose=scan）。全程不写回默认值，提案等用户决策后另走
golden 变更流程。buyScoreThreshold 不在本 harness 范围（阈值漂移只出复核建议）。

端到端锚：baseline trial 必须逐位复现阶段 21.8 端到端锚三窗读数
（decision 0.0835 / oos1 0.0657 / oos2 0.0572），否则 harness 口径与 Track 2 不一致。

fail-visible：子集样本量（rawHits/sampleCount）、saEx=None 退化如实输出，不伪造 0。

基线注记（2026-09-13）：本 harness 评估与提案产出基于旧默认基线
0.24/0.20/0.16/0.20/0.20；阶段 22.8 用户决策落默认 p2_aggressive
（0.06/0.04/0.24/0.29/0.37）后，TRIAL_GROUPS 各 trial 的 patch 与 desc 文本仍为
历史评估口径——落默认后重跑 core/up 组的 half/quarter/up 档位将基于新默认计算，
数值与 desc 中的历史证据不可直接对比；proposal 组为已采纳的历史记录
（p2_aggressive 即当前默认），重跑判定卡将得到 p2 vs p2 的全零卡片，无意义。

用法：
  python -m backend.operations.evaluate_ts_factor_weights [--window decision|oos1|oos2|all]
      [--group core|up|proposal|all] [--events-only] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import _tier_summary

WINDOWS: dict[str, tuple[str, str]] = {
    "decision": ("2026-04-15", "2026-07-31"),
    "oos1": ("2026-08-15", "2026-08-31"),
    "oos2": ("2026-09-01", "2026-09-12"),
}

WEIGHT_FIELDS = ("directionWeight", "accelerationWeight", "crossWeight", "macdWeight", "maWeight")


def _default_weights() -> dict[str, float]:
    from backend.analysis.ranktrend.engine import RankTrendConfig

    return {f: float(getattr(RankTrendConfig(), f)) for f in WEIGHT_FIELDS}


def make_loo_patch(field: str) -> dict[str, float]:
    """留一 trial patch：目标权重→0（from_patch 归一化把其余四因子等比放大）。"""
    if field not in WEIGHT_FIELDS:
        raise ValueError(f"未知决策权重字段 {field!r}，可选 {WEIGHT_FIELDS}")
    return {field: 0.0}


def make_half_patch(field: str) -> dict[str, float]:
    """半权 trial patch：目标权重×0.5（相对其余因子比例减半，归一化后同量纲）。"""
    if field not in WEIGHT_FIELDS:
        raise ValueError(f"未知决策权重字段 {field!r}，可选 {WEIGHT_FIELDS}")
    return {field: _default_weights()[field] * 0.5}


# ---------------------------------------------------------------------------
# 层 1：事件级区分度（五因子 buy/sell 事件/状态帧谓词）
# ---------------------------------------------------------------------------


def _technical_of(signal: dict[str, Any]) -> dict[str, Any]:
    return ((signal.get("rankTrend") or {}).get("technical") or {})


def _signal_component(signal: dict[str, Any], name: str) -> dict[str, Any]:
    """technical.signals.<name> 子分量；缺字段返回 {}（fail-visible，不伪造 hold）。"""
    return (_technical_of(signal).get("signals") or {}).get(name) or {}


def _cross_of(signal: dict[str, Any], key: str) -> str:
    value = (_technical_of(signal).get(key) or {}).get("cross")
    return str(value) if value else ""


EVENT_SUBSETS: dict[str, tuple[str, Callable[[dict[str, Any]], bool]]] = {
    "direction_buy": ("方向分量 buy 状态帧", lambda s: _signal_component(s, "direction").get("signal") == "buy"),
    "direction_sell": ("方向分量 sell 状态帧", lambda s: _signal_component(s, "direction").get("signal") == "sell"),
    "acceleration_buy": ("加速度分量 buy 状态帧", lambda s: _signal_component(s, "acceleration").get("signal") == "buy"),
    "acceleration_sell": ("加速度分量 sell 状态帧", lambda s: _signal_component(s, "acceleration").get("signal") == "sell"),
    "zeroCross_buy": ("零线交叉分量 buy 状态帧", lambda s: _signal_component(s, "zeroCross").get("signal") == "buy"),
    "zeroCross_sell": ("零线交叉分量 sell 状态帧", lambda s: _signal_component(s, "zeroCross").get("signal") == "sell"),
    "macd_golden_event": ("MACD 金叉事件帧", lambda s: _cross_of(s, "macd") == "golden"),
    "macd_death_event": ("MACD 死叉事件帧", lambda s: _cross_of(s, "macd") == "death"),
    "ma_golden_event": ("MA 金叉事件帧", lambda s: _cross_of(s, "maCross") == "golden"),
    "ma_death_event": ("MA 死叉事件帧", lambda s: _cross_of(s, "maCross") == "death"),
}


def event_discrimination(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """层 1 口径：全量 + 各因子事件/状态子集 h1 synergy 统计 + 原始命中计数。

    每个子集输出 _tier_summary 字段（saEx/spearman/passHard/unknownRate/distribution）
    + sampleCount + rawHits + desc；分位桶基线在子集内重算（阶段 14/17 同口径）；
    saEx=None（完全单调/反单调统计退化）与 unknown 率如实透传，不伪造。
    """
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    def _stats(filtered: Callable[[dict[str, Any]], bool] | None) -> dict[str, Any]:
        stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy", signal_filter=filtered)
        summary = _tier_summary(stats)
        summary["sampleCount"] = sum(
            (stats.get("tiers") or {}).get(t, {}).get("count") or 0
            for t in ("S", "A", "B", "C", "D", "E", "unknown")
        )
        return summary

    out: dict[str, Any] = {"all": _stats(None)}
    for key, (desc, pred) in EVENT_SUBSETS.items():
        summary = _stats(pred)
        summary["desc"] = desc
        summary["rawHits"] = sum(1 for s in signals if pred(s))
        out[key] = summary
    out["totalSignals"] = len(signals)
    return out


# ---------------------------------------------------------------------------
# 层 2：边际贡献 trial（core = 留一 ×5 + 半权 ×5；up/proposal 组视证据后填充）
# ---------------------------------------------------------------------------


def _core_trials() -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = [{"key": "baseline", "desc": "默认配置（五权重 0.24/0.20/0.16/0.20/0.20）", "overrides": {}}]
    label = {
        "directionWeight": "方向一致性",
        "accelerationWeight": "多周期加速度",
        "crossWeight": "零线交叉",
        "macdWeight": "MACD 金死叉",
        "maWeight": "MA10×MA20 金死叉",
    }
    for field in WEIGHT_FIELDS:
        trials.append({
            "key": f"loo_{field.removesuffix('Weight')}",
            "desc": f"留一：移除 {label[field]}（{field}→0，其余归一化放大）",
            "overrides": make_loo_patch(field),
        })
    for field in WEIGHT_FIELDS:
        trials.append({
            "key": f"half_{field.removesuffix('Weight')}",
            "desc": f"半权：{label[field]} 相对比例减半（{field}={_default_weights()[field] * 0.5}）",
            "overrides": make_half_patch(field),
        })
    return trials


def scaled_patch(field: str, factor: float) -> dict[str, float]:
    """dose-response 扫描档：目标权重 = 当前默认 × factor（单变量、from_patch 归一化同量纲）。"""
    return {field: round(_default_weights()[field] * factor, 6)}


TRIAL_GROUPS: dict[str, list[dict[str, Any]]] = {
    "core": _core_trials(),
    # 上调扫描组（2026-09-13 按 decision/oos1/oos2 三窗 core 证据填充）：
    # direction/acceleration 三窗负贡献主导 → 下探 ×0.25 找剂量曲线；
    # cross/macd/ma 在 decision 窗正贡献 → 上探 ×1.5 验证当前点右侧导数。
    "up": [
        {
            "key": "quarter_direction",
            "desc": "direction 权重×0.25（三窗留一 +13.9%/−2.4%/+17.0%，剂量下探）",
            "overrides": scaled_patch("directionWeight", 0.25),
        },
        {
            "key": "quarter_acceleration",
            "desc": "acceleration 权重×0.25（唯一三窗一致负 +2.6%/+7.0%/+6.8%，剂量下探）",
            "overrides": scaled_patch("accelerationWeight", 0.25),
        },
        {
            "key": "up_cross",
            "desc": "zeroCross 权重×1.5（decision 留一 −3.1% 受损，上探右侧导数）",
            "overrides": scaled_patch("crossWeight", 1.5),
        },
        {
            "key": "up_macd",
            "desc": "macd 权重×1.5（decision 留一 −4.1% 受损最多，上探右侧导数）",
            "overrides": scaled_patch("macdWeight", 1.5),
        },
        {
            "key": "up_ma",
            "desc": "ma 权重×1.5（decision 留一 −1.7% 弱正，上探右侧导数）",
            "overrides": scaled_patch("maWeight", 1.5),
        },
    ],
    # 权重提案组（2026-09-13 按 core+up 三窗剂量证据构造，梯度覆盖温和→归零）：
    # 降 direction/acceleration（负贡献）、升 ma（唯一三窗上探全正）、cross/macd 轻升吸收余量。
    "proposal": [
        {
            "key": "p1_moderate",
            "desc": "温和：direction 0.12 / accel 0.10 / cross 0.20 / macd 0.26 / ma 0.32",
            "overrides": {
                "directionWeight": 0.12,
                "accelerationWeight": 0.10,
                "crossWeight": 0.20,
                "macdWeight": 0.26,
                "maWeight": 0.32,
            },
        },
        {
            "key": "p2_aggressive",
            "desc": "激进：direction 0.06 / accel 0.04 / cross 0.24 / macd 0.29 / ma 0.37",
            "overrides": {
                "directionWeight": 0.06,
                "accelerationWeight": 0.04,
                "crossWeight": 0.24,
                "macdWeight": 0.29,
                "maWeight": 0.37,
            },
        },
        {
            "key": "p3_zero_negative",
            "desc": "负因子归零：direction 0 / accel 0 / cross 0.26 / macd 0.34 / ma 0.40（dose 外推上限）",
            "overrides": {
                "directionWeight": 0.0,
                "accelerationWeight": 0.0,
                "crossWeight": 0.26,
                "macdWeight": 0.34,
                "maWeight": 0.40,
            },
        },
    ],
}


def _rel_improve(trial: float | None, base: float | None) -> float | None:
    if trial is None or base is None or base == 0:
        return None
    return round((trial - base) / abs(base), 4)


def _trial_result(report: dict[str, Any], win: str, key: str) -> dict[str, Any] | None:
    return (((report.get(win) or {}).get("trials") or {}).get(key) or {}).get("result")


def contribution_summary(report: dict[str, Any], key: str) -> dict[str, Any]:
    """层 2 汇总：trial vs baseline 逐窗 saEx/score 绝对差与相对差（None 传播不伪造）。

    留一解读：saExDelta<0 的窗口 = 移除受损 = 该因子在该窗有正边际贡献。
    """
    out: dict[str, Any] = {}
    for win in WINDOWS:
        base, trial = _trial_result(report, win, "baseline"), _trial_result(report, win, key)
        if not trial:
            continue
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        base_score = (base or {}).get("score")
        out[win] = {
            "saEx": trial_sa,
            "saExDelta": None if (trial_sa is None or base_sa is None) else round(trial_sa - base_sa, 4),
            "saExRel": _rel_improve(trial_sa, base_sa),
            "passHard": trial.get("synergy", {}).get("passHard"),
            "score": trial.get("score"),
            "scoreDelta": (
                None
                if (base_score is None or trial.get("score") is None)
                else round(trial["score"] - base_score, 4)
            ),
            "trendSaEx": trial.get("rankTrend", {}).get("saEx"),
            "flipVeto": trial.get("flipRates", {}).get("veto"),
            "flipBd": trial.get("flipRates", {}).get("bd_downgrade"),
            "regimeSaEx": {
                state: (trial.get("regimeView") or {}).get(state, {}).get("saEx")
                for state in ("strong", "normal", "weak", "retreat")
            },
        }
    return out


def proposal_verdict(report: dict[str, Any], key: str) -> dict[str, Any]:
    """提案 trial 的 Track 2 判定卡（与 evaluate_track2_candidates 同口径）。

    C1 决策窗 saEx 相对 baseline ≥ +3%；C2 OOS ≥1 窗同向为正；C3 决策窗 passHard 不降；
    C4 regime 四桶 saEx 降幅 ≤ 0.01；C5 翻转率升幅 ≤ +0.01。
    C1∧C2∧C3 → PASS_CANDIDATE；C3 False → REJECT；其余 → OBSERVE。
    """
    base_dec = _trial_result(report, "decision", "baseline")
    if not base_dec:
        return {}
    return _verdict_from_summaries(
        {win: contribution_summary(report, key).get(win) for win in WINDOWS},
        base_pass=bool(base_dec.get("synergy", {}).get("passHard")),
        base_regime=[
            ((base_dec.get("regimeView") or {}).get(state) or {}).get("saEx")
            for state in ("strong", "normal", "weak", "retreat")
        ],
        base_flip={
            "veto": float((base_dec.get("flipRates") or {}).get("veto") or 0.0),
            "bd_downgrade": float((base_dec.get("flipRates") or {}).get("bd_downgrade") or 0.0),
        },
    )


def _verdict_from_summaries(
    summaries: dict[str, dict[str, Any] | None],
    base_pass: bool,
    base_regime: list[float | None],
    base_flip: dict[str, float],
) -> dict[str, Any]:
    dec = summaries.get("decision")
    if not dec:
        return {}
    c1 = dec["saExRel"] is not None and dec["saExRel"] >= 0.03
    oos_rels = [summaries.get(w, {}).get("saExRel") if summaries.get(w) else None for w in ("oos1", "oos2")]
    c2 = any(r is not None and r > 0 for r in oos_rels)
    c3 = dec["passHard"] or not base_pass
    regime_trial = dec["regimeSaEx"]
    c4 = all(
        (b is None or t is None) or (t - b >= -0.01)
        for b, t in zip(base_regime, [regime_trial[s] for s in ("strong", "normal", "weak", "retreat")])
    )
    c5 = ((dec["flipVeto"] or 0.0) - base_flip["veto"] <= 0.01) and (
        (dec["flipBd"] or 0.0) - base_flip["bd_downgrade"] <= 0.01
    )
    conclusion = "PASS_CANDIDATE" if (c1 and c2 and c3) else ("REJECT" if not c3 else "OBSERVE")
    return {
        "conclusion": conclusion,
        "C1_decisionSaExRel": {"value": dec["saExRel"], "pass": c1},
        "C2_oosPositiveCount": {"detail": dict(zip(("oos1", "oos2"), oos_rels)), "pass": c2},
        "C3_passHardKept": {"value": dec["passHard"], "pass": c3},
        "C4_regimeNotWorse": {
            "value": {
                s: (None if (b is None or regime_trial[s] is None) else round(regime_trial[s] - b, 4))
                for s, b in zip(("strong", "normal", "weak", "retreat"), base_regime)
            },
            "pass": c4,
        },
        "C5_flipNotWorse": {
            "vetoDelta": round((dec["flipVeto"] or 0.0) - base_flip["veto"], 5),
            "bdDelta": round((dec["flipBd"] or 0.0) - base_flip["bd_downgrade"], 5),
            "pass": c5,
        },
    }


# ---------------------------------------------------------------------------
# 窗口执行（load_frames 一次/trial 组复用；resume 缓存逐 trial 落盘）
# ---------------------------------------------------------------------------


def run_window(window: str, report: dict[str, Any], groups: list[str], events_only: bool = False) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[ts-weights] {window} frames={len(frames)} window={start}~{end}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        assert_not_frozen(frames, "scan")
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    # 层 1：事件级区分度（baseline 单次 replay 复用，观察字段与权重 patch 无关）
    if "events" not in entry:
        t0 = time.time()
        signals = RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})
        print(f"[ts-weights] {window} baseline replay signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)
        entry["events"] = event_discrimination(signals, frames)
        entry["baselineReplaySignals"] = len(signals)
        _save(report)

    if events_only:
        return

    # 层 2：边际贡献 / 上调 / 提案 trial
    specs: list[dict[str, Any]] = []
    for group in groups:
        specs.extend(TRIAL_GROUPS.get(group) or [])
    seen: set[str] = set()
    trials = entry.setdefault("trials", {})
    for spec in specs:
        key = spec["key"]
        if key in seen:
            continue
        seen.add(key)
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        config = RankTrendConfig.from_patch(spec["overrides"])
        print(f"[ts-weights] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(config, frames)
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "group": _group_of(key), "result": result}
        print(
            f"[ts-weights] {window} {key} -> score={result['score']} syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({result['elapsedSec']}s)",
            file=sys.stderr,
        )
        _save(report)


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    """窗口帧缓存：载入一次存 report 内存态（不落盘，落盘只存统计摘要）。"""
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def _group_of(key: str) -> str:
    for group, specs in TRIAL_GROUPS.items():
        if any(s["key"] == key for s in specs):
            return group
    return "unknown"


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "ts-factor-weights.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="TS 五因子权重实证评估（权重重定义任务）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--group", default="core", choices=["core", "up", "proposal", "all"])
    parser.add_argument("--events-only", action="store_true", help="只跑层 1 事件级区分度（不跑 trial）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "ts-factor-weights.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    groups = ["core", "up", "proposal"] if args.group == "all" else [args.group]
    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, groups, events_only=args.events_only)

    # 汇总：边际贡献逐 trial + 提案判定卡
    summary: dict[str, Any] = {}
    all_keys: list[str] = []
    for group in ("core", "up", "proposal"):
        all_keys.extend(s["key"] for s in TRIAL_GROUPS.get(group) or [])
    for key in all_keys:
        if key == "baseline":
            continue
        if any(_trial_result(report, w, key) for w in WINDOWS):
            summary[key] = contribution_summary(report, key)
    proposal_cards = {
        s["key"]: proposal_verdict(report, s["key"])
        for s in TRIAL_GROUPS.get("proposal") or []
        if _trial_result(report, "decision", s["key"])
    }
    report["contribution"] = summary
    report["proposalVerdicts"] = proposal_cards
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"contribution": summary, "proposalVerdicts": proposal_cards}, ensure_ascii=False, indent=2))
    print(f"[ts-weights] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
