# -*- coding: utf-8 -*-
"""维度话语权归零对照 harness（backend/operations，2026-09-14，阶段 23 追问）。

用户命题：共振/趋势/横截面/量价/周期每个维度在 synergy 总档投票中谁的话语权最大，
当前权重分配是否"拍脑袋"。

投票算术事实（volume_price.py:339-367，2026-09-14 核实）：
- v = res票 + rank票 + vp票 + cs票；res/rank/vp 权重硬编码 1.0（vote = 档位强度
  × 方向符号，_VOTE_STRENGTH S=1.2/A=1.0/B=0.8/C=0.5/D=1.0/E=1.0，v4 实证 2026-08-15，
  saEx 0.0651 vs 旧口径 0.0519）；cs = _CS_STRENGTH × tierSynergyCrossSectionVote(=1.0)；
- 档位线：S≥strong+1(3.0) / A≥strong(2.0) / B≥weak(1.0) / D≤reverse(-1.0) / else C；
- 周期维不投票（环境门）：lc E → synergy E 一票否决；vp E → 硬降 D；lc B/D → S/A 降一档；
- pm/dv 权重默认 0（G1/dv 实证负贡献关闭）；热榜情绪不进 v 求和（走 regime strong 门
  与 compose_strategy 候选池通道）。

话语权测量两层：
- 层 1 结构统计（baseline 单次 replay）：各维实际投票率（方向非 hold 占比）、
  档位分布、环境门触发率（E 帧 + "环境降档"帧）；
- 层 2 整维归零对照（trial）：每维从合成中移除 vs baseline 的 ΔsaEx + 档位翻转率
  （话语权主指标 = 该维能改变多少最终判定）。翻转率 ≠ 话语权价值：翻多大要和
  ΔsaEx 方向一起读（翻转大但 saEx 恶化 = 该维在保护排序质量）。

归零路径（如实区分，fail-visible）：
- cs：config patch tierSynergyCrossSectionVote=0（干净配置路径）；
- rank/vp：monkeypatch volume_price._synergy_tier wrapper 置空 tier/dir（无配置字段，
  评估态注入，跑完恢复；no_vp 同时移除 vp E→D 硬降规则，desc 标注）；
- lc_gate：wrapper 把 lc_tier 置 "C"（同时去掉 E veto 与 B/D 降档）；
- res（共振）：replay 链路 100% 缺票（阶段 3 诊断，缺横截面 median → vote=0）——
  无法做"去共振"对照（本来就为 0 的票无法归零），结构事实如实报告；
  共振维的真实话语权在 API 单股链路，不在本 harness 口径内。

窗口纪律：三窗同前；FINAL(8/1-8/14) 冻结守卫。基线锚：baseline trial 必须复现
阶段 22.8 三窗读数（0.0939/0.0854/0.0737）。

基线注记（2026-09-14 落默认后）：用户决策采纳 combo_three_quarter（res/rank/cs 票权
0.75、vp 1.0，阶段 23.9）后，本 harness 历史报告中的 baseline/trial 读数基于旧默认
1.0 基线，重跑将基于新默认计算，数值与历史报告不可直接对比；新默认端到端锚 =
decision 0.1044 / oos1 0.0918 / oos2 0.0933（已逐位验证 = combo_three_quarter 实证口径）。

用法：
  python -m backend.operations.evaluate_dimension_voting_power [--window ...] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import _tier_summary

BASELINE_ANCHOR: dict[str, float] = {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}

# 归零对照维度：rank/vp/lc_gate 走 wrapper 注入；cs 走 config patch。
NEUTRAL_DIMS = ("rank", "vp", "lc_gate")

DIM_ZERO_TRIALS: list[dict[str, Any]] = [
    {
        "key": "dim_no_rank",
        "desc": "去趋势维票（rank tier/dir 置空；趋势维是 v≥3/S 档的主力票源假设待验）",
        "mechanism": "monkeypatch",
        "dim": "rank",
        "overrides": {},
    },
    {
        "key": "dim_no_vp",
        "desc": "去量价维票（vp tier/dir 置空；同时移除 vp E→D 出货硬降规则，如实标注）",
        "mechanism": "monkeypatch",
        "dim": "vp",
        "overrides": {},
    },
    {
        "key": "dim_no_cs",
        "desc": "去横截面维票（tierSynergyCrossSectionVote 1.0→0，G2 实证正贡献维的反向对照）",
        "mechanism": "config",
        "dim": None,
        "overrides": {"tierSynergyCrossSectionVote": 0.0},
    },
    {
        "key": "dim_no_lc_gate",
        "desc": "去周期环境门（lc_tier 一律 C：同时移除 E veto 与 B/D 降档，如实标注）",
        "mechanism": "monkeypatch",
        "dim": "lc_gate",
        "overrides": {},
    },
]


# 5 档维度权重扫描（2026-09-14：res/rank/vp 权重参数化后全 config 路径，无需 monkeypatch）。
# 档位 {×0, ×0.5, ×1.5, ×2.0} + baseline(×1.0)。×0 与归零对照同构（dimw_rank__x00 ↔
# dim_no_rank 交叉验证锚）；vp 权重 0 时 E→D 出货硬降仍生效（结构规则，与 no_vp 的
# monkeypatch 归零语义差异，如实标注）。
_DIM_WEIGHT_FIELD: dict[str, str] = {
    "res": "tierSynergyResonanceVote",
    "rank": "tierSynergyRankVote",
    "vp": "tierSynergyVolumePriceVote",
    "cs": "tierSynergyCrossSectionVote",
}

DIM_WEIGHT_SCAN_TRIALS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "默认配置（四维票权重全 1.0，阶段 22.8 后基线）", "overrides": {}},
    *[
        {
            "key": f"dimw_{dim}__x{tag}",
            "desc": f"{dim} 票权重 ×{factor}（{field}；当前默认 1.0）",
            "overrides": {field: factor},
        }
        for dim, field in _DIM_WEIGHT_FIELD.items()
        for factor, tag in ((0.0, "00"), (0.5, "05"), (1.5, "15"), (2.0, "20"))
    ],
]

# 第二轮精扫（2026-09-14 第一轮证据驱动）：res/rank/cs 左侧通道 ×0.25/×0.625/×0.75 找峰
# （三轴 ×0.5 三窗全正、归零档全不可行 → 下限 0.25）；vp 确认窄峰 ×0.75/×1.25。
DIM_REFINE_TRIALS: list[dict[str, Any]] = [
    {"key": "dimw_res__x025", "desc": "精扫：res 票权重 ×0.25（左侧通道找峰）", "overrides": {"tierSynergyResonanceVote": 0.25}},
    {"key": "dimw_res__x0625", "desc": "精扫：res 票权重 ×0.625（峰定位）", "overrides": {"tierSynergyResonanceVote": 0.625}},
    {"key": "dimw_res__x075", "desc": "精扫：res 票权重 ×0.75（峰定位）", "overrides": {"tierSynergyResonanceVote": 0.75}},
    {"key": "dimw_rank__x025", "desc": "精扫：rank 票权重 ×0.25（左侧通道找峰）", "overrides": {"tierSynergyRankVote": 0.25}},
    {"key": "dimw_rank__x0625", "desc": "精扫：rank 票权重 ×0.625（峰定位）", "overrides": {"tierSynergyRankVote": 0.625}},
    {"key": "dimw_rank__x075", "desc": "精扫：rank 票权重 ×0.75（峰定位）", "overrides": {"tierSynergyRankVote": 0.75}},
    {"key": "dimw_cs__x025", "desc": "精扫：cs 票权重 ×0.25（左侧通道找峰）", "overrides": {"tierSynergyCrossSectionVote": 0.25}},
    {"key": "dimw_cs__x0625", "desc": "精扫：cs 票权重 ×0.625（峰定位）", "overrides": {"tierSynergyCrossSectionVote": 0.625}},
    {"key": "dimw_cs__x075", "desc": "精扫：cs 票权重 ×0.75（峰定位）", "overrides": {"tierSynergyCrossSectionVote": 0.75}},
    {"key": "dimw_vp__x075", "desc": "精扫：vp 票权重 ×0.75（窄峰确认）", "overrides": {"tierSynergyVolumePriceVote": 0.75}},
    {"key": "dimw_vp__x125", "desc": "精扫：vp 票权重 ×1.25（窄峰确认）", "overrides": {"tierSynergyVolumePriceVote": 1.25}},
]

# 组合提案（Track 2 判定卡对象，2026-09-14 第一轮证据直译）：res/rank/cs 三轴同档减权、
# vp 保持 1.0（vp 两侧受损 OOS 双负，不动）。
# 机制警告：三轴同减半后 v 上限 ≈ (1.2+1.0+1.0)/2 + 1.0 = 2.6 < strong+1=3 → S 线不可达、
# S 档消失（档位重分布），必须过 C3 passHard 核查后才能谈落默认。
DIM_COMBO_TRIALS: list[dict[str, Any]] = [
    {
        "key": "combo_quarter_three",
        "desc": "组合下探：res/rank/cs ×0.25、vp 1.0（三轴剂量下探）",
        "overrides": {"tierSynergyResonanceVote": 0.25, "tierSynergyRankVote": 0.25, "tierSynergyCrossSectionVote": 0.25},
    },
    {
        "key": "combo_half_three",
        "desc": "组合直译：res/rank/cs ×0.5、vp 1.0（第一轮三轴 ×0.5 三窗全正的证据组合；S 档将消失）",
        "overrides": {"tierSynergyResonanceVote": 0.5, "tierSynergyRankVote": 0.5, "tierSynergyCrossSectionVote": 0.5},
    },
    {
        "key": "combo_three_quarter",
        "desc": "组合温和：res/rank/cs ×0.75、vp 1.0（温和减权档）",
        "overrides": {"tierSynergyResonanceVote": 0.75, "tierSynergyRankVote": 0.75, "tierSynergyCrossSectionVote": 0.75},
    },
]


def make_neutralize_wrapper(dim: str, original: Callable[..., tuple[str, list[str]]]) -> Callable[..., tuple[str, list[str]]]:
    """构造 _synergy_tier 包装器：把目标维的 tier/dir 位置参数置空（None）。

    _synergy_tier(res_t, res_d, rank_t, rank_d, vp_t, vp_d, lc_t, [config], **kw)——
    前 7 个位置参数按索引映射；res 不在 NEUTRAL_DIMS（replay 缺票，无法归零）。
    """
    if dim not in NEUTRAL_DIMS:
        raise ValueError(f"未知归零维度 {dim!r}，可选 {NEUTRAL_DIMS}")
    zero_idx = {"rank": (2, 3), "vp": (4, 5), "lc_gate": (6,)}[dim]
    # lc_gate 置显式 "C"（中性档，与 WP2a lc_tier_override 语义一致）；
    # rank/vp 置 None（缺票语义 = _vote 返回 0，与共振缺票同构）。
    neutral_value = "C" if dim == "lc_gate" else None

    def wrapper(*args: Any, **kwargs: Any) -> tuple[str, list[str]]:
        args = list(args)
        for i in zero_idx:
            if i < len(args):
                args[i] = neutral_value
        return original(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# 层 1：结构统计（baseline 单次 replay 复用）
# ---------------------------------------------------------------------------


def _obs(signal: dict[str, Any], name: str) -> dict[str, Any]:
    return ((signal.get("rankTrend") or {}).get("observation") or {}).get(name) or {}


def _dir_of(signal: dict[str, Any], name: str) -> str:
    return str(_obs(signal, name).get("direction") or "")


def structural_power_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """各维实际投票率/档位分布 + 环境门触发率（fail-visible：缺字段如实计数）。"""
    n = len(signals)
    if n == 0:
        return {"totalSignals": 0}
    def _share(pred: Callable[[dict[str, Any]], bool]) -> float:
        return round(sum(1 for s in signals if pred(s)) / n, 4)

    syn_tiers: dict[str, int] = {}
    rank_tiers: dict[str, int] = {}
    vp_tiers: dict[str, int] = {}
    cs_tiers: dict[str, int] = {}
    downgrades = 0
    for s in signals:
        syn = _obs(s, "synergy")
        t = str(syn.get("signalTier") or "unknown")
        syn_tiers[t] = syn_tiers.get(t, 0) + 1
        reasons = syn.get("tierReasons") if isinstance(syn.get("tierReasons"), list) else []
        if any("环境降档" in str(r) for r in reasons):
            downgrades += 1
        for name, bucket in (("rankTrend", rank_tiers), ("volumePrice", vp_tiers), ("crossSection", cs_tiers)):
            bt = str(_obs(s, name).get("signalTier") or "unknown")
            bucket[bt] = bucket.get(bt, 0) + 1
    return {
        "totalSignals": n,
        "voteRate": {
            # 有方向才有非零票；方向词汇两套并存：rank 用 buy/sell、vp 用 up/down
            # （volume_price.py:152），cs 无方向字段按档位符号投票（非 unknown 计）
            "rank": _share(lambda s: _dir_of(s, "rankTrend") in ("buy", "sell", "up", "down")),
            "vp": _share(lambda s: _dir_of(s, "volumePrice") in ("buy", "sell", "up", "down")),
            "cs": _share(lambda s: _obs(s, "crossSection").get("signalTier") in ("A", "B", "C", "D")),
        },
        "lcGate": {
            "vetoShare": _share(lambda s: bool(_obs(s, "lifecycle").get("veto"))),
            "downgradeShare": round(downgrades / n, 4),
        },
        "tierDistribution": {
            "synergy": syn_tiers,
            "rankTrend": rank_tiers,
            "volumePrice": vp_tiers,
            "crossSection": cs_tiers,
        },
    }


# ---------------------------------------------------------------------------
# 层 2：话语权汇总（ΔsaEx + 档位翻转率）
# ---------------------------------------------------------------------------


def _trial_result(report: dict[str, Any], win: str, key: str) -> dict[str, Any] | None:
    return (((report.get(win) or {}).get("trials") or {}).get(key) or {}).get("result")


def power_summary(report: dict[str, Any], key: str) -> dict[str, Any]:
    """维度话语权汇总：逐窗 ΔsaEx + 档位翻转帧占比（逐位对齐比较）。

    verdict：insufficient_data（无 trial 读数）/ measured。翻转率 None（序列长度
    不一致，无法逐位对齐）如实传播，不伪造 0。
    """
    from backend.operations.evaluate_ts_factor_weights import _rel_improve

    windows: dict[str, Any] = {}
    seen = False
    flip_vals: list[float] = []
    rel_vals: list[float] = []
    for win in WINDOWS:
        base, trial = _trial_result(report, win, "baseline"), _trial_result(report, win, key)
        if not trial:
            continue
        seen = True
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        base_tiers = (base or {}).get("signalTiers") or []
        trial_tiers = trial.get("signalTiers") or []
        if base_tiers and trial_tiers and len(base_tiers) == len(trial_tiers):
            flips = sum(1 for a, b in zip(base_tiers, trial_tiers) if a != b)
            flip_rate = round(flips / len(base_tiers), 4)
            flip_vals.append(flip_rate)
        else:
            flip_rate = None
        rel = _rel_improve(trial_sa, base_sa)
        if rel is not None:
            rel_vals.append(rel)
        windows[win] = {
            "saEx": trial_sa,
            "saExDelta": None if (trial_sa is None or base_sa is None) else round(trial_sa - base_sa, 4),
            "saExRel": rel,
            "tierFlipRate": flip_rate,
            "compared": min(len(base_tiers), len(trial_tiers)) or None,
        }
    if not seen:
        return {"verdict": "insufficient_data", "windows": windows}
    return {
        "verdict": "measured",
        "windows": windows,
        "meanTierFlipRate": round(sum(flip_vals) / len(flip_vals), 4) if flip_vals else None,
        "meanSaExRel": round(sum(rel_vals) / len(rel_vals), 4) if rel_vals else None,
    }


# ---------------------------------------------------------------------------
# 窗口执行
# ---------------------------------------------------------------------------


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def _record_signal_tiers(signals: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for s in signals:
        out.append(str(_obs(s, "synergy").get("signalTier") or "unknown"))
    return out


def run_window(window: str, report: dict[str, Any]) -> None:
    import backend.analysis.ranktrend.ranking.volume_price as vp_mod
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[dim-power] {window} frames={len(frames)}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        assert_not_frozen(frames, "scan")
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    # 层 1：结构统计 + baseline trial（同一次 replay 产出信号序列供逐位对齐；
    # structural 独立缓存——口径修复后可只重算结构统计而复用 trial 缓存）
    trials = entry.setdefault("trials", {})
    if "structural" not in entry or "baseline" not in trials:
        t0 = time.time()
        engine = RankTrendPythonEngine(config=RankTrendConfig())
        signals = engine.replay(frames, meta={})
        if "structural" not in entry:
            entry["structural"] = structural_power_stats(signals)
        if "baseline" not in trials:
            result = evaluate_gate(RankTrendConfig(), frames)
            trials["baseline"] = {
                "desc": "默认配置（阶段 22.8 后基线）",
                "overrides": {},
                "result": {**result, "signalTiers": _record_signal_tiers(signals)},
            }
            print(
                f"[dim-power] {window} baseline syn(saEx={result['synergy']['saEx']}) "
                f"signals={len(signals)} ({time.time() - t0:.0f}s)",
                file=sys.stderr,
            )
        else:
            print(f"[dim-power] {window} structural recomputed ({time.time() - t0:.0f}s)", file=sys.stderr)
        _save(report)

    for spec in DIM_ZERO_TRIALS:
        key = spec["key"]
        trials = entry.setdefault("trials", {})
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[dim-power] {window} {key} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        restore: Any = None
        if spec["mechanism"] == "monkeypatch":
            original = vp_mod._synergy_tier
            vp_mod._synergy_tier = make_neutralize_wrapper(spec["dim"], original)

            def _restore() -> None:
                vp_mod._synergy_tier = original

            restore = _restore
        try:
            engine = RankTrendPythonEngine(config=config)
            signals = engine.replay(frames, meta={})
            result = evaluate_gate(config, frames)
        finally:
            if restore is not None:
                restore()
        result = {**result, "signalTiers": _record_signal_tiers(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[dim-power] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({result.get('elapsedSec', round(time.time() - t0, 1))}s)",
            file=sys.stderr,
        )
        _save(report)

    # 5 档扫描 + 第二轮精扫 + 组合提案（全 config 路径；baseline 已在上一步确保存在）
    for spec in (*DIM_WEIGHT_SCAN_TRIALS, *DIM_REFINE_TRIALS, *DIM_COMBO_TRIALS):
        key = spec["key"]
        if key == "baseline":
            continue
        trials = entry.setdefault("trials", {})
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[dim-power] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _record_signal_tiers(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[dim-power] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "dimension-voting-power.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="维度话语权归零对照（阶段 23 追问）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "dimension-voting-power.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report)

    summary = {spec["key"]: power_summary(report, spec["key"]) for spec in DIM_ZERO_TRIALS}
    summary.update({spec["key"]: power_summary(report, spec["key"]) for spec in (*DIM_WEIGHT_SCAN_TRIALS, *DIM_REFINE_TRIALS, *DIM_COMBO_TRIALS) if spec["key"] != "baseline"})
    report["power"] = summary
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"power": summary}, ensure_ascii=False, indent=2))
    print(f"[dim-power] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
