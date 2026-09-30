# -*- coding: utf-8 -*-
"""双轨验收制 Track 2 统一判定 harness（backend/operations，2026-09-13，阶段 20）。

用户决策（2026-09-13）：双轨验收制通过但需简化流程 + 增加多信号组合验证；P1 即刻启动
（9 月已有 10 个交易日数据）；P2 安排 A/B 实验。本 harness 把 P1 复验 + P1 组合 + P2
persist A/B 收敛为一次跑完的 trial 表，每 trial 自动产出判定卡（无需人工汇总多份报告）。

Trial 组（B-202610 前置修复后口径，2026-09-25；原 2026-09-13 用户批准清单见阶段 20）：
  - P1 复验：fund10_over2（OverVolumeRatio 2.5→2.0；**fund10 已于 2026-09-15 落默认**，
    AbnormalFundRatio=10.0 即现值不再是扰动轴，本 trial 在新默认栈上仅测 over 轴）+
    fund10_revert（O2 对照基线：AbnormalFundRatio 还原 20.0，观察池 O2 baselineNote）；
    jump25_fresh06（jumpDeltaPct 15→25 + tierResonanceJumpFreshnessMin 0.5→0.6）
  - P1 多信号组合验证：combo_p1（over2+jump25+fresh06 三参叠加，fund10 已在默认栈）；
    combo_all（三参 + persist，检测跨维度交互）
  - P2 A/B：persist_on（crossSectionPersistFrames=3，阶段 18 H1成立/H2证伪后的组合面复验）
  - MA 补验：ma_join / ma_full（阶段 17 口径）
  - B-202610 阶段 2/3 增补（2026-09-25）：R2_revert（三轴票权还原 1.0）、
    R3_revert（五因子权重还原）、O3_revert_vsB080（B 档票强度还原 0.8；原 O3_vsb070 晋升臂
    于 2026-09-30 落默认后重定义为回退对照，fund10_over2 先例）、O5_buyThr018
    （buyScoreThreshold 0.18）——default_review 回退 trial 与观察池候选同卡判定

Track 2 判定卡（简化流程：一次 evaluate_gate 自动产出全部口径，替代人工拼表）：
  C1 决策窗 synergy saEx 相对改善 ≥ +3%（相对 baseline，baseline saEx>0）
  C2 OOS ≥1 窗（oos1/oos2u）同向为正改善
  C3 决策窗 passHard 不降（baseline True → trial False 一票否决）
  C4 regime 四桶（strong/normal/weak/retreat）决策窗 saEx 相对 baseline 下降 ≤ 0.01（绝对差）
  C5 决策窗翻转率 veto/bd_downgrade 相对 baseline 上升 ≤ +0.01（绝对差）
  结论：C1∧C2 = PASS_CANDIDATE（进入交易层复核+golden 变更流程）；C3 False = REJECT；
        其余 = OBSERVE。

窗口纪律（B-202610 口径，2026-09-16 用户裁决，单一事实源 data_windows.WINDOWS）：
决策窗 04-15~07-31（assert_not_frozen purpose=scan）+ OOS-1 08-15~08-31 +
OOS-2 09-01~09-30 全月（09-13 前帧已被阶段 0-26 harness 消费，读数仅作折扣参考）+
OOS-2u 09-13~09-30 未消费裁决子窗（**C2 判定读数以 oos2u 为准**，M3 窗口消费折扣）；
FINAL(8/1-8/14) 冻结不进判定。oos2u 消费禁令（2026-09-16 起）：09-13 后新帧除批次
执行外不得跑结论性扫描。历史口径（oos2=09-01~09-12）见阶段 20 原始记录。
组合交互提示：combo 相对"其组成单因子最优值"的改善输出对比行（检测相互抵消），不作硬门槛。

口径来源：evaluate_gate（WP2 harness，含 regimeView 四桶 + WP3.2 翻转率 + passHard）；
load_frames（optimize_resonance_parameters，projection=ranktrend）。fail-visible：
样本量/缺失桶/None saEx 如实输出，不伪造 0。

用法：
  python -m backend.operations.evaluate_track2_candidates [--window decision|oos1|oos2|oos2u|all]
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

from backend.optimization.data_windows import WINDOWS as ALL_STANDARD_WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import load_frames

# 窗口单一事实源：backend/optimization/data_windows.py（2026-09-16 B-202610 口径）。
# oos2 判定读数以 oos2u 未消费子窗为准（M3），oos2 全月仅作折扣参考披露。
WINDOWS: dict[str, tuple[str, str]] = {
    k: ALL_STANDARD_WINDOWS[k] for k in ("decision", "oos1", "oos2", "oos2u")
}

# 组合扰动轴（fund10 已于 2026-09-15 落默认进默认栈，combo 相对当前默认栈定义，不再重复写该轴）
P1_OVERRIDES: dict[str, Any] = {
    "volumePriceOverVolumeRatio": 2.0,
    "jumpDeltaPct": 25.0,
    "tierResonanceJumpFreshnessMin": 0.6,
}

TRIALS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "默认配置", "overrides": {}},
    {
        "key": "fund10_revert",
        "desc": "O2 对照基线：fund10 回退口径（AbnormalFundRatio 还原 20.0，观察池 O2 baselineNote）",
        "overrides": {"volumePriceAbnormalFundRatio": 20.0},
    },
    {
        "key": "fund10_over2",
        "desc": "P1 复验：over 阈值 2.5→2.0（fund10 已落默认，本 trial 在新默认栈上仅测 over 轴；旧两参口径见阶段 20）",
        "overrides": {"volumePriceOverVolumeRatio": 2.0},
    },
    {
        "key": "jump25_fresh06",
        "desc": "P1：jumpDeltaPct 15→25 + freshnessMin 0.5→0.6（阶段 9.5 8月 +283%）",
        "overrides": {"jumpDeltaPct": 25.0, "tierResonanceJumpFreshnessMin": 0.6},
    },
    {"key": "combo_p1", "desc": "P1 多信号组合：over2+jump25+fresh06 三参叠加（fund10 已在默认栈）", "overrides": dict(P1_OVERRIDES)},
    {
        "key": "persist_on",
        "desc": "P2 A/B：crossSection 持续高位路径 N=3（阶段 18 H1成立/H2证伪）",
        "overrides": {"crossSectionPersistFrames": 3},
    },
    {"key": "combo_all", "desc": "全组合：P1 三参 + persist（跨维度交互检测）", "overrides": {**P1_OVERRIDES, "crossSectionPersistFrames": 3}},
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
    # ── B-202610 阶段 2/3 增补 trial（2026-09-25 演练；default_review 回退 trial 判定卡读数
    #    = 回退相对当前默认栈的效应：C1/C2 全过=回退更优提示回退，反之保持）──
    {
        "key": "R2_revert_combo_three_quarter",
        "desc": "R2 回退：res/rank/cs 三轴票权 0.75→1.0（§23.9.1 combo_three_quarter 单项还原）",
        "overrides": {"tierSynergyResonanceVote": 1.0, "tierSynergyRankVote": 1.0, "tierSynergyCrossSectionVote": 1.0},
    },
    {
        "key": "R3_revert_ts_weights",
        "desc": "R3 回退：五因子权重还原 0.24/0.20/0.16/0.20/0.20（§22.8 p2_aggressive 单项还原）",
        "overrides": {"directionWeight": 0.24, "accelerationWeight": 0.20, "crossWeight": 0.16, "macdWeight": 0.20, "maWeight": 0.20},
    },
    {
        # vsB_070 落默认（2026-09-30 用户决策）后，本 trial 按 fund10_over2 先例重定义为回退对照臂：
        # overrides = 还原 0.8（落默认前默认值），判定卡语义从"晋升候选"变为"回退复核"。
        "key": "O3_revert_vsB080",
        "desc": "O3 回退对照：tierSynergyVoteStrengths[2] 还原 0.8（2026-09-30 vsB_070 已落默认，B-202610 批次 PASS_CANDIDATE + Track 1 中性 80 笔）",
        "overrides": {"tierSynergyVoteStrengths": [1.2, 1.0, 0.8, 0.5, 1.0, 1.0]},
    },
    {
        "key": "O5_buyThr018",
        "desc": "O5 观察池：buyScoreThreshold 0.12→0.18（§13.3 两窗同向一窗反向）",
        "overrides": {"buyScoreThreshold": 0.18},
    },
]

# 组合交互提示用：combo 由哪些单因子 trial 组成（判定卡输出 combo vs 最优单因子对比行）
COMBO_PARTS: dict[str, list[str]] = {"combo_p1": ["fund10_over2", "jump25_fresh06"], "combo_all": ["fund10_over2", "jump25_fresh06", "persist_on"]}

# baseline 锚（gen-2026-10-b202610，config/ranktrend-anchors.json，2026-09-16 预建；
# 来源=本 harness baseline trial 逐位读数：decision 655 帧 / oos1 110 帧（封闭窗）；
# oos2 全月 206 帧 / oos2u 120 帧为 2026-09-30 正式复跑填充，与注册表同步）。
BASELINE_ANCHORS: dict[str, float | None] = {"decision": 0.1323, "oos1": 0.0862, "oos2": 0.0841, "oos2u": 0.0534}

_OVERRIDE_MISSING = object()

# 决策五权重经 from_patch 整体归一化（engine/config.py from_patch，和恒为 1）——patch 值≠
# config 实际值是设计行为（evaluate_ma_factor_contribution 同款语义），豁免值比较只断言字段
# 存在；typo 字段不存在仍被拦截（守卫核心目标）。
_NORMALIZED_WEIGHT_FIELDS = frozenset(
    {"directionWeight", "accelerationWeight", "crossWeight", "macdWeight", "maWeight"}
)


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（审计 §7.2.1-B1，范式同 evaluate_cs_strengths review C1）：
    from_patch 对未知字段静默忽略（hasattr 无 else），字段拼错会静默跑成 baseline 复刻、
    产出假零效应结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 无此字段）——检查字段名拼写/配置代际")
        if key in _NORMALIZED_WEIGHT_FIELDS:
            continue
        if actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


def _assert_baseline_anchor(window: str, sa_ex: float | None) -> None:
    """baseline 锚 trial 级即时 raise（B-202610 批判定器）：漂移=代际/config 污染，不许带病出判定卡。"""
    anchor = BASELINE_ANCHORS.get(window)
    if anchor is None:
        return
    actual = None if sa_ex is None else round(float(sa_ex), 4)
    if actual != round(float(anchor), 4):
        raise AssertionError(
            f"baseline 锚漂移: {window} saEx={actual} vs gen-2026-10-b202610 锚 {anchor}"
            f"——检查 config 代际/frames 窗口完整性，校准后重跑（锚注册表 {window} 值以 anchors.json 为准）"
        )


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
        cached = trials.get(spec["key"])
        if cached is not None:
            if cached.get("overrides") == spec["overrides"]:
                print(f"[skip] {window}/{spec['key']} (cached)", file=sys.stderr)
                continue
            # trial 定义随代际/口径更新（如 fund10_over2 两参→仅 over 轴）：旧口径缓存
            # 不得按 key 跳过冒充新口径读数，重跑覆盖（fail-visible）
            print(f"[rerun] {window}/{spec['key']} overrides 变更，旧口径缓存作废重跑", file=sys.stderr)
            del trials[spec["key"]]
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        print(f"[track2] {window} {spec['key']} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(config, frames)  # type: ignore[name-defined] # noqa: F821
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[spec["key"]] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        if spec["key"] == "baseline":
            _assert_baseline_anchor(window, result["synergy"]["saEx"])
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
    # C2 判定读数以 oos2u（未消费子窗）为准，oos2 全月仅作折扣参考（M3 纪律）
    oos = [cards.get(w) for w in ("oos1", "oos2u")]
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
            for win in ("oos1", "oos2u", "oos2")
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
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "oos2u", "all"])
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
