# -*- coding: utf-8 -*-
"""双轨验收制 Track 2 统一判定 harness（backend/operations，2026-09-13，阶段 20）。

用户决策（2026-09-13）：双轨验收制通过但需简化流程 + 增加多信号组合验证；P1 即刻启动
（9 月已有 10 个交易日数据）；P2 安排 A/B 实验。本 harness 把 P1 复验 + P1 组合 + P2
persist A/B 收敛为一次跑完的 trial 表，每 trial 自动产出判定卡（无需人工汇总多份报告）。

Trial 组（用户批准清单）：
  - P1 复验：fund10_over2（volumePriceAbnormalFundRatio 20→10 + OverVolumeRatio 2.5→2.0，
    阶段 9.5 8月 +438%）；jump25_fresh06（jumpDeltaPct 15→25 + tierResonanceJumpFreshnessMin
    0.5→0.6，阶段 9.5 8月 +283%）
  - P1 多信号组合验证：combo_p1（四参叠加）；combo_all（四参 + persist，检测跨维度交互）
  - P2 A/B：persist_on（crossSectionPersistFrames=3，阶段 18 H1成立/H2证伪后的组合面复验）

Track 2 判定卡（简化流程：一次 evaluate_gate 自动产出全部口径，替代人工拼表）：
  C1 决策窗 synergy saEx 相对改善 ≥ +3%（相对 baseline，baseline saEx>0）
  C2 OOS ≥1 窗（oos1/oos2）同向为正改善
  C3 决策窗 passHard 不降（baseline True → trial False 一票否决）
  C4 regime 四桶（strong/normal/weak/retreat）决策窗 saEx 相对 baseline 下降 ≤ 0.01（绝对差）
  C5 决策窗翻转率 veto/bd_downgrade 相对 baseline 上升 ≤ +0.01（绝对差）
  结论：C1∧C2 = PASS_CANDIDATE（进入交易层复核+golden 变更流程）；C3 False = REJECT；
        其余 = OBSERVE。

窗口纪律：决策窗 04-15~07-31（assert_not_frozen purpose=scan）+ OOS-1 08-15~08-31 +
OOS-2 09-01~09-12（9 月 10 个交易日复验窗，用户批准）；FINAL(8/1-8/14) 冻结不进判定。
组合交互提示：combo 相对"其组成单因子最优值"的改善输出对比行（检测相互抵消），不作硬门槛。

口径来源：evaluate_gate（WP2 harness，含 regimeView 四桶 + WP3.2 翻转率 + passHard）；
load_frames（optimize_resonance_parameters，projection=ranktrend）。fail-visible：
样本量/缺失桶/None saEx 如实输出，不伪造 0。

用法：
  python -m backend.operations.evaluate_track2_candidates [--window decision|oos1|oos2|all]
      [--verdict-only] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import load_frames

WINDOWS: dict[str, tuple[str, str]] = {
    "decision": ("2026-04-15", "2026-07-31"),
    "oos1": ("2026-08-15", "2026-08-31"),
    "oos2": ("2026-09-01", "2026-09-12"),
}

P1_OVERRIDES: dict[str, Any] = {
    "volumePriceAbnormalFundRatio": 10.0,
    "volumePriceOverVolumeRatio": 2.0,
    "jumpDeltaPct": 25.0,
    "tierResonanceJumpFreshnessMin": 0.6,
}

TRIALS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "默认配置", "overrides": {}},
    {
        "key": "fund10_over2",
        "desc": "P1：量价 fund 阈值 20→10 + over 阈值 2.5→2.0（阶段 9.5 8月 +438%）",
        "overrides": {"volumePriceAbnormalFundRatio": 10.0, "volumePriceOverVolumeRatio": 2.0},
    },
    {
        "key": "jump25_fresh06",
        "desc": "P1：jumpDeltaPct 15→25 + freshnessMin 0.5→0.6（阶段 9.5 8月 +283%）",
        "overrides": {"jumpDeltaPct": 25.0, "tierResonanceJumpFreshnessMin": 0.6},
    },
    {"key": "combo_p1", "desc": "P1 多信号组合：fund10+over2+jump25+fresh06 四参叠加", "overrides": dict(P1_OVERRIDES)},
    {
        "key": "persist_on",
        "desc": "P2 A/B：crossSection 持续高位路径 N=3（阶段 18 H1成立/H2证伪）",
        "overrides": {"crossSectionPersistFrames": 3},
    },
    {"key": "combo_all", "desc": "全组合：P1 四参 + persist（跨维度交互检测）", "overrides": {**P1_OVERRIDES, "crossSectionPersistFrames": 3}},
    {
        "key": "ma_join",
        "desc": "MA 补验（2026-09-13 用户质询）：MA 进决策合成第 5 分量（与 MACD 并存，阶段 17 ±0.01）",
        "overrides": {"maWeight": 0.25},
    },
    {
        "key": "ma_full",
        "desc": "MA 补验：决策分量 + trend_buy 参与位全开（阶段 17 接线零增量复核）",
        "overrides": {"maWeight": 0.25, "maCrossTrendBuy": True},
    },
]

# 组合交互提示用：combo 由哪些单因子 trial 组成（判定卡输出 combo vs 最优单因子对比行）
COMBO_PARTS: dict[str, list[str]] = {"combo_p1": ["fund10_over2", "jump25_fresh06"], "combo_all": ["fund10_over2", "jump25_fresh06", "persist_on"]}


def run_window(window: str, report: dict[str, Any]) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    if "frames" not in entry:
        frames = load_frames(start, end)
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[track2] {window} frames={len(frames)} window={start}~{end}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        assert_not_frozen(frames, "scan")
        entry.pop("error", None)
        _save(report)

    trials = entry.setdefault("trials", {})
    for spec in TRIALS:
        if spec["key"] in trials:
            print(f"[skip] {window}/{spec['key']} (cached)", file=sys.stderr)
            continue
        config = RankTrendConfig.from_patch(spec["overrides"])
        print(f"[track2] {window} {spec['key']} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(config, frames)  # type: ignore[name-defined] # noqa: F821
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[spec["key"]] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        r = result
        print(
            f"[track2] {window} {spec['key']} -> score={r['score']} syn(saEx={r['synergy']['saEx']} "
            f"pass={r['synergy']['passHard']}) flip(veto={r['flipRates']['veto']:.4f}) ({result['elapsedSec']}s)",
            file=sys.stderr,
        )
        _save(report)


def _rel_improve(trial: float | None, base: float | None) -> float | None:
    if trial is None or base is None or base == 0:
        return None
    return round((trial - base) / abs(base), 4)


def _verdict_window(entry: dict[str, Any], win: str) -> dict[str, Any] | None:
    """单窗判定卡数据（trial vs baseline）。"""
    trials = entry.get("trials") or {}
    base = (trials.get("baseline") or {}).get("result")
    if not base:
        return None
    out: dict[str, Any] = {}
    for spec in TRIALS:
        key = spec["key"]
        if key == "baseline":
            continue
        result = (trials.get(key) or {}).get("result")
        if not result:
            continue
        b_syn, t_syn = base["synergy"], result["synergy"]
        row: dict[str, Any] = {
            "saEx": t_syn["saEx"],
            "saExRel": _rel_improve(t_syn["saEx"], b_syn["saEx"]),
            "passHard": t_syn["passHard"],
            "score": result["score"],
            "trendSaEx": result["rankTrend"]["saEx"],
            "flipVeto": result["flipRates"]["veto"],
            "flipBd": result["flipRates"]["bd_downgrade"],
            "regimeSaEx": {
                state: (result.get("regimeView") or {}).get(state, {}).get("saEx")
                for state in ("strong", "normal", "weak", "retreat")
            },
            "regimeRel": {
                state: _rel_improve(
                    (result.get("regimeView") or {}).get(state, {}).get("saEx"),
                    (base.get("regimeView") or {}).get(state, {}).get("saEx"),
                )
                for state in ("strong", "normal", "weak", "retreat")
            },
        }
        out[key] = row
    return out


def verdict(report: dict[str, Any]) -> dict[str, Any]:
    """判定卡组装：C1-C5 全自动，combo 附加交互提示行。"""
    cards: dict[str, Any] = {}
    for win in WINDOWS:
        entry = report.get(win) or {}
        w = _verdict_window(entry, win)
        if w:
            cards[win] = w

    out: dict[str, Any] = {"criteria": "C1决策窗saEx相对≥+3% C2 OOS≥1窗同向 C3 passHard不降 C4 regime桶降幅≤0.01 C5翻转升幅≤0.01"}
    dec = cards.get("decision") or {}
    oos = [cards.get(w) for w in ("oos1", "oos2")]
    for key in [s["key"] for s in TRIALS if s["key"] != "baseline"]:
        if key not in dec:
            continue
        d = dec[key]
        c1 = d["saExRel"] is not None and d["saExRel"] >= 0.03
        c2 = any(
            o and key in o and o[key]["saExRel"] is not None and o[key]["saExRel"] > 0 for o in oos
        )
        # C3 需 baseline passHard 对照；baseline 缺失时 C3 无法判否（fail-visible 不误杀）
        base_pass = bool(((report.get("decision", {}).get("trials", {}).get("baseline") or {}).get("result") or {}).get("synergy", {}).get("passHard"))
        c3 = (d["passHard"] or not base_pass) if base_pass else True
        c4 = all(
            (base_sa is None or trial_sa is None) or (trial_sa - base_sa >= -0.01)
            for base_sa, trial_sa in zip(
                _regime_base(report, "decision"), d["regimeSaEx"].values()
            )
        )
        base_flip = _flip_base(report, "decision")
        c5 = d["flipVeto"] - base_flip["veto"] <= 0.01 and d["flipBd"] - base_flip["bd_downgrade"] <= 0.01
        oos_detail = {
            win: (cards[win][key]["saExRel"] if cards.get(win) and key in cards[win] else None)
            for win in ("oos1", "oos2")
        }
        conclusion = "PASS_CANDIDATE" if (c1 and c2 and c3) else ("REJECT" if not c3 else "OBSERVE")
        card: dict[str, Any] = {
            "conclusion": conclusion,
            "C1_decisionSaExRel": {"value": d["saExRel"], "pass": c1},
            "C2_oosPositiveCount": {"detail": oos_detail, "pass": c2},
            "C3_passHardKept": {"value": d["passHard"], "pass": c3},
            "C4_regimeNotWorse": {"value": d["regimeRel"], "pass": c4},
            "C5_flipNotWorse": {"vetoDelta": round(d["flipVeto"] - base_flip["veto"], 5), "bdDelta": round(d["flipBd"] - base_flip["bd_downgrade"], 5), "pass": c5},
        }
        parts = COMBO_PARTS.get(key)
        if parts:
            best = max(
                (dec[p]["saEx"] for p in parts if p in dec and dec[p]["saEx"] is not None),
                default=None,
            )
            card["comboInteraction"] = {
                "parts": parts,
                "bestSingleSaEx": best,
                "comboSaEx": d["saEx"],
                "note": "combo ≥ best 单因子 = 叠加有效；< best = 相互抵消，观察",
            }
        out[key] = card
    return out


def _regime_base(report: dict[str, Any], win: str) -> list[float | None]:
    base = ((report.get(win) or {}).get("trials") or {}).get("baseline", {}).get("result") or {}
    view = base.get("regimeView") or {}
    return [(view.get(state) or {}).get("saEx") for state in ("strong", "normal", "weak", "retreat")]


def _flip_base(report: dict[str, Any], win: str) -> dict[str, float]:
    base = ((report.get(win) or {}).get("trials") or {}).get("baseline", {}).get("result") or {}
    return {"veto": float((base.get("flipRates") or {}).get("veto") or 0.0), "bd_downgrade": float((base.get("flipRates") or {}).get("bd_downgrade") or 0.0)}


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "track2-candidates.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k != "__out__"}
    # verdict 每次落盘都重算（幂等、秒级）：中断续跑时缓存报告始终带最新判定卡
    payload["verdict"] = verdict(report)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Track 2 统一判定 harness（阶段 20）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--verdict-only", action="store_true", help="只从缓存报告组装判定卡，不跑 trial")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "track2-candidates.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)

    if args.verdict_only:
        cards = verdict(report)
        print(json.dumps(cards, ensure_ascii=False, indent=2))
        return 0

    report["__out__"] = str(out_path)
    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report)
    report.pop("__out__", None)
    report["verdict"] = verdict(report)
    _save(report)
    print(json.dumps(report.get("verdict") or {}, ensure_ascii=False, indent=2))
    print(f"[track2] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
