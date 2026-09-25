# -*- coding: utf-8 -*-
"""趋势漏网参数扫描 harness（P5 案：buyThresholds/sellThresholds + 5 momentum 参数 + requireMacdGoldenCross，两轮制粗扫）。

缺口来源（方案 P5，ranktrend-param-gap-scan-plan.md）：
- buyThresholds/sellThresholds（[5,8,13,21,34] 负镜像 [-5,-8,-13,-21,-34]，config.py:11-12）
  长测主链从未扫描；§13 审计清点的是决策层 buyScoreThreshold/sellScoreThreshold，
  与本参数不同名，勿混淆；
- §8.4 参数化 18 项但 5 档表只扫 8 项，剩 5 项漏网即 momentumLongAgreeThreshold(0.15) /
  momentumScoreThreshold(35) / momentumDirectionShareBoost([0.5,0.5]) / momentumAccelShareBoost([0.7,0.3])
  + requireMacdGoldenCross(False，runtime.py:299 消费)——后者从未作为开关 trial 评估。

tanh 尺度语义（审计 M2 修正）：buyThresholds/sellThresholds 不是"buy/sell 触发线"——
trend/technical.py:211-217 以 `tanh(value/abs(threshold))`、:241 以 `normalize_signed`
消费，是动量打分的连续幅度面：阈值缩放改变 tanh 饱和速度，进而改变 momentumScoreThreshold
比较的输入分布。预期剂量曲线而非结构性惰性——本案例唯一全新语义面；浮点档位
（×0.5 → [2.5,4,6.5,10.5,17]）在 tanh 尺度下合法。

先验提示（审计 M3 修正）：
- direction 侧已证默认最优（方向阈值 0.2、LongOppose 0.25 默认最优，§8.4）；
- accel 侧恰相反取中性：momentumAccelThreshold 0.26 曾是唯一单调显著档，靠 §8.5 样本外
  否决才维持默认 0.18——"未被替换"≠"被证明最优"，防"现值即峰"预期污染解读；
- thresholds 预期剂量曲线（见上）。

P5-0 收口注记：momentumConfidenceSlope（technical.py:220）仅进 momentum_data 的
confidence 键，该键全后端零读取方（dead output），已按 §23.3 A 组以代码消费面事实直接
收口——不进扫描、无对照 trial；收口记录归长测计划。（P5-0 提到的 from_patch list 长度
守卫属可选 TDD 项，统一处理，本 harness 以 `_assert_thresholds_len5` 预检兜底。）

锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后）decision 0.1120 / oos1 0.0880 /
oos2 0.0951；首跑三窗任一锚不复现即停（配置漂移），不许带病继续。
pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史口径）。

trial 结构（P5-a 粗扫 22 trial + baseline = 23；单变量 5 档，默认档由 baseline 承担）：
- buyThresholds/sellThresholds 镜像同步缩放 ×0.5/×0.75/×1.25/×1.5 + 快半档 [3,5,8,13,21]
  对照（×1.0=baseline 承担；负值侧镜像同步缩放；两个 list 同一 trial 内同步替换，
  len==5 硬预检——from_patch 对 list 长度零校验：短 list 运行期 IndexError、长 list
  静默截断，防 trial 假绿，总纲预检纪律 1）；
- momentumLongAgreeThreshold 0.05/0.10/0.20/0.25（默认 0.15）；
- momentumScoreThreshold 25/30/40/45（默认 35；thresholds 缩放直接改其比较输入）；
- momentumDirectionShareBoost [0.3,0.7]/[0.4,0.6]/[0.6,0.4]/[0.7,0.3]（默认 [0.5,0.5]；
  乘性位置 raw×(b0+b1×share)，份额和=1，乘子范围 [b0,1]，technical.py:245-246）；
- momentumAccelShareBoost [0.5,0.5]/[0.6,0.4]/[0.8,0.2]/[0.9,0.1]（默认 [0.7,0.3]，
  technical.py:261-262；档位设计对 accel 侧先验取中性）；
- requireMacdGoldenCross True（二值开关 1 对照，不适用 5 档口径，总纲豁免；False=baseline）。

focus 维：synergy + rankTrend（趋势参数动 rankTrend 面，两维 saEx 都出）；判定卡 Track 2
C1（decision saEx rel ≥+3%）/ C2（OOS ≥1 窗同向为正）/ C3（decision passHard 不降）→
PASS_CANDIDATE / OBSERVE；regime 四桶附加读数；每 trial 监控 S+A 触发率
（TRIGGER_RATE_FLAG=0.035，阶段 22.6 观察线）。落默认前最后一步须 Track 1 交易复核
（e1a 教训）。OOS-2 已被阶段 24/25 部分消费，结论标注"窗口已消费"（M3 折扣，
windowsConsumed=true），最终裁决与 9 月全月复验同批。

用法：
  python -m backend.operations.evaluate_trend_leftover_parameters [--window all] [--out <path>]
      [--extra-trial <json>]（P5-b 精扫追加；触及 thresholds 的 extra trial 同样过 len==5 预检）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.operations.evaluate_ts_factor_weights import WINDOWS, _rel_improve
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后，报告 baseline-anchor-post-fund10.json）；
# pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史报告口径）
# 锚单一事实源（2026-09-25 B-202610 演练落地）：硬编码 fund10 代际冻结锚改为运行时读
# 锚注册表 currentGeneration（gen-2026-10-b202610）——注册表更新后自动跟随（审计 D3）。
from backend.operations.harness_common import baseline_anchor

ANCHOR_BASELINE: dict[str, float] = baseline_anchor()[1]
TRIGGER_RATE_FLAG = 0.035  # S+A 触发率旗标（阶段 22.6 观察线）
_OVERRIDE_MISSING = object()

# 默认 thresholds（config.py:11-12 负镜像；tests 锁定代际，漂移即测试失败）
BASE_BUY: list[float] = [5, 8, 13, 21, 34]
BASE_SELL: list[float] = [-5, -8, -13, -21, -34]
FAST_HALF_BUY: list[float] = [3, 5, 8, 13, 21]
BASE_LONG_AGREE = 0.15
BASE_SCORE_THRESHOLD = 35.0
BASE_DIR_BOOST: list[float] = [0.5, 0.5]
BASE_ACCEL_BOOST: list[float] = [0.7, 0.3]


def _scale_thresholds(factor: float) -> dict[str, Any]:
    """镜像同步缩放：buy ×factor，sell 负值侧 ×factor；两个 list 同一 trial 整体替换。"""
    buy = [round(v * factor, 6) for v in BASE_BUY]
    return {"buyThresholds": buy, "sellThresholds": [round(-b, 6) for b in buy]}


def _assert_thresholds_len5(patch: dict[str, Any]) -> None:
    """防假绿预检（总纲预检纪律 1）：from_patch 对 list 长度零校验——短 list 运行期
    IndexError、长 list 静默截断，trial 会假绿。buyThresholds/sellThresholds 必须同一
    trial 内成对出现、len==5（与 momentumPeriods 按 index 对齐）且负值侧镜像同步。"""
    if "buyThresholds" not in patch and "sellThresholds" not in patch:
        return
    if "buyThresholds" not in patch or "sellThresholds" not in patch:
        raise AssertionError("buyThresholds/sellThresholds 必须同一 trial 内同步替换（负值侧镜像同步缩放约束）")
    buy = patch["buyThresholds"]
    sell = patch["sellThresholds"]
    if len(buy) != 5 or len(sell) != 5:
        raise AssertionError(
            f"buyThresholds/sellThresholds 必须保持 5 元素（与 momentumPeriods 按 index 对齐，"
            f"from_patch 零校验：短 list 运行期 IndexError、长 list 静默截断）：buy={buy!r} sell={sell!r}"
        )
    for index, (b, s) in enumerate(zip(buy, sell)):
        if abs(float(s) + float(b)) > 1e-9:
            raise AssertionError(f"thresholds 镜像破缺 index={index}: buy={b!r} sell={s!r}（负值侧必须镜像同步）")
    periods = patch.get("momentumPeriods")
    if periods is not None and len(periods) != 5:
        raise AssertionError(f"momentumPeriods 必须保持 5 元素（thresholds 按 index 对齐）：{periods!r}")


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


# ---------------------------------------------------------------------------
# P5-a trial 表（单变量 5 档；默认档由 baseline 承担，故各组只列非默认档）
# ---------------------------------------------------------------------------

THRESHOLDS_TRIALS: list[dict[str, Any]] = [
    {"key": "thr_x05", "desc": "thresholds ×0.5（tanh 尺度放宽，饱和更慢）", "overrides": _scale_thresholds(0.5)},
    {"key": "thr_x075", "desc": "thresholds ×0.75", "overrides": _scale_thresholds(0.75)},
    {"key": "thr_x125", "desc": "thresholds ×1.25", "overrides": _scale_thresholds(1.25)},
    {"key": "thr_x15", "desc": "thresholds ×1.5（tanh 尺度收紧，饱和更快）", "overrides": _scale_thresholds(1.5)},
    {"key": "thr_fast_half", "desc": "快半档 [3,5,8,13,21] 对照（负镜像 [-3,-5,-8,-13,-21]；档位前移非等比）",
     "overrides": {"buyThresholds": list(FAST_HALF_BUY), "sellThresholds": [-v for v in FAST_HALF_BUY]}},
]

LONG_AGREE_TRIALS: list[dict[str, Any]] = [
    {"key": "long_agree_005", "desc": "momentumLongAgreeThreshold 0.05（放宽长周期附和）", "overrides": {"momentumLongAgreeThreshold": 0.05}},
    {"key": "long_agree_010", "desc": "momentumLongAgreeThreshold 0.10", "overrides": {"momentumLongAgreeThreshold": 0.10}},
    {"key": "long_agree_020", "desc": "momentumLongAgreeThreshold 0.20", "overrides": {"momentumLongAgreeThreshold": 0.20}},
    {"key": "long_agree_025", "desc": "momentumLongAgreeThreshold 0.25（收紧；direction 侧先验：0.2/0.25 默认最优，§8.4）", "overrides": {"momentumLongAgreeThreshold": 0.25}},
]

SCORE_TRIALS: list[dict[str, Any]] = [
    {"key": "score_thr_25", "desc": "momentumScoreThreshold 25（放宽信号触发）", "overrides": {"momentumScoreThreshold": 25}},
    {"key": "score_thr_30", "desc": "momentumScoreThreshold 30", "overrides": {"momentumScoreThreshold": 30}},
    {"key": "score_thr_40", "desc": "momentumScoreThreshold 40", "overrides": {"momentumScoreThreshold": 40}},
    {"key": "score_thr_45", "desc": "momentumScoreThreshold 45（收紧信号触发）", "overrides": {"momentumScoreThreshold": 45}},
]

DIR_BOOST_TRIALS: list[dict[str, Any]] = [
    {"key": "dir_boost_30_70", "desc": "momentumDirectionShareBoost [0.3,0.7]（强趋势乘子上限抬升）", "overrides": {"momentumDirectionShareBoost": [0.3, 0.7]}},
    {"key": "dir_boost_40_60", "desc": "momentumDirectionShareBoost [0.4,0.6]", "overrides": {"momentumDirectionShareBoost": [0.4, 0.6]}},
    {"key": "dir_boost_60_40", "desc": "momentumDirectionShareBoost [0.6,0.4]", "overrides": {"momentumDirectionShareBoost": [0.6, 0.4]}},
    {"key": "dir_boost_70_30", "desc": "momentumDirectionShareBoost [0.7,0.3]（压缩乘子动态域）", "overrides": {"momentumDirectionShareBoost": [0.7, 0.3]}},
]

ACCEL_BOOST_TRIALS: list[dict[str, Any]] = [
    {"key": "accel_boost_50_50", "desc": "momentumAccelShareBoost [0.5,0.5]", "overrides": {"momentumAccelShareBoost": [0.5, 0.5]}},
    {"key": "accel_boost_60_40", "desc": "momentumAccelShareBoost [0.6,0.4]", "overrides": {"momentumAccelShareBoost": [0.6, 0.4]}},
    {"key": "accel_boost_80_20", "desc": "momentumAccelShareBoost [0.8,0.2]", "overrides": {"momentumAccelShareBoost": [0.8, 0.2]}},
    {"key": "accel_boost_90_10", "desc": "momentumAccelShareBoost [0.9,0.1]（accel 侧先验取中性：0.26 靠样本外否决维持 0.18，未被替换≠最优，§8.5）", "overrides": {"momentumAccelShareBoost": [0.9, 0.1]}},
]

SWITCH_TRIALS: list[dict[str, Any]] = [
    {"key": "macd_golden_on", "desc": "requireMacdGoldenCross True（二值开关 1 对照，不适用 5 档口径；runtime.py:299 消费）", "overrides": {"requireMacdGoldenCross": True}},
]

P5_TRIALS: list[dict[str, Any]] = [
    *THRESHOLDS_TRIALS,
    *LONG_AGREE_TRIALS,
    *SCORE_TRIALS,
    *DIR_BOOST_TRIALS,
    *ACCEL_BOOST_TRIALS,
    *SWITCH_TRIALS,
]


def baseline_spec() -> dict[str, Any]:
    """baseline 承担全部 ×1.0 默认档 + 锚断言（post-fund10）。"""
    return {
        "key": "baseline",
        "desc": "当前默认（thresholds [5,8,13,21,34] 负镜像 ×1.0 + longAgree 0.15 + scoreThr 35 "
                "+ dirBoost [0.5,0.5] + accelBoost [0.7,0.3] + requireMacdGoldenCross=False）",
        "overrides": {},
        "anchor": ANCHOR_BASELINE,
    }


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def _tiers_of(signals: list[dict[str, Any]]) -> list[str]:
    out = []
    for s in signals:
        tier = ((((s.get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier"))
        out.append(str(tier or "unknown"))
    return out


def trigger_rate_of(result: dict[str, Any]) -> float | None:
    dist = (result.get("synergy") or {}).get("distribution") or {}
    total = sum(v for v in dist.values() if isinstance(v, (int, float)))
    return round((dist.get("S", 0) + dist.get("A", 0)) / total, 4) if total else None


def regime_delta_of(trial: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
    base_regime = base.get("regimeView") or {}
    trial_regime = trial.get("regimeView") or {}
    if not base_regime or not trial_regime:
        return None
    return {
        state: (
            None
            if (trial_regime.get(state) or {}).get("saEx") is None or (base_regime.get(state) or {}).get("saEx") is None
            else round(trial_regime[state]["saEx"] - base_regime[state]["saEx"], 4)
        )
        for state in ("strong", "normal", "weak", "retreat")
        if state in base_regime
    }


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：focus 双维（synergy 主判定 + rankTrend 趋势面）+ 判定卡 + 触发率漂移。

    判定卡（Track 2，§19.3/§19.6）：C1 decision saEx rel ≥+3% / C2 OOS ≥1 窗同向为正 /
    C3 decision passHard 不降（baseline True → trial False 才算降）→ PASS_CANDIDATE / OBSERVE；
    regime 四桶与 C4/C5 由 regimeDelta/regimeStateCounts 附加读数承接（Track 1 交易复核在落默认前另跑）。
    """
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    trend_rels: dict[str, float | None] = {}
    pass_hard: dict[str, bool | None] = {}
    for win in WINDOWS:
        base = (((report.get(win) or {}).get("trials") or {}).get("baseline") or {}).get("result")
        trial = (((report.get(win) or {}).get("trials") or {}).get(spec["key"]) or {}).get("result")
        if not trial:
            continue
        base_sa = ((base or {}).get("synergy") or {}).get("saEx")
        trial_sa = (trial.get("synergy") or {}).get("saEx")
        base_trend = ((base or {}).get("rankTrend") or {}).get("saEx")
        trial_trend = (trial.get("rankTrend") or {}).get("saEx")
        rels[win] = _rel_improve(trial_sa, base_sa)
        trend_rels[win] = _rel_improve(trial_trend, base_trend)
        pass_hard[win] = (trial.get("synergy") or {}).get("passHard")
        trig = trigger_rate_of(trial)
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "rankTrendSaEx": trial_trend,
            "rankTrendSaExRel": trend_rels[win],
            "rankTrendPassHard": (trial.get("rankTrend") or {}).get("passHard"),
            "passHard": pass_hard[win],
            "triggerRateSA": trig,
            "triggerFlag": bool(trig is not None and trig > TRIGGER_RATE_FLAG),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
            "regimeDelta": regime_delta_of(trial, base or {}),
        }
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    c2 = any(v is not None and v > 0 for v in (rels.get("oos1"), rels.get("oos2")))
    base_pass = ((((report.get("decision") or {}).get("trials") or {}).get("baseline") or {}).get("result") or {}).get("synergy", {}).get("passHard")
    c3 = not (base_pass is True and pass_hard.get("decision") is not True)  # 不降语义：仅 True→False 算降
    card = {"C1_decisionRelGE3pct": c1, "C2_oosAnyPositive": c2, "C3_decisionPassHard": c3}
    return {
        "windows": windows,
        "saExRel": rels,
        "rankTrendSaExRel": trend_rels,
        "verdictCard": card,
        "cardResult": "PASS_CANDIDATE" if all([c1, c2, c3]) else "OBSERVE",
        "focusNote": "focus 维 synergy+rankTrend：趋势参数动 rankTrend 面，rankTrendSaEx(Rel) 同批输出；判定卡以 synergy 口径为准（Track 2 §19.3）",
        "priorNote": "direction 侧已证默认最优（§8.4）；accel 侧取中性（0.26 靠样本外否决维持 0.18——未被替换≠被证明最优）；thresholds 预期剂量曲线（tanh 尺度面）",
    }


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def run_window(window: str, report: dict[str, Any], specs: list[dict[str, Any]] | None = None) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[trend-leftover] {window} frames={len(frames)}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    trials = entry.setdefault("trials", {})
    if specs is None:
        specs = [baseline_spec(), *P5_TRIALS]
    for spec in specs:
        key = spec["key"]
        _assert_thresholds_len5(spec["overrides"])  # 防假绿预检：每个触及 thresholds 的 trial 必须过
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[trend-leftover] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _tiers_of(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[trend-leftover] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"trend(saEx={(result.get('rankTrend') or {}).get('saEx')}) "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # OOS-2 已被阶段 24/25 部分消费（M3 折扣标注）
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "trend-leftover-parameters.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（同 evaluate_ts_factor_weights 模式）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="趋势漏网参数扫描（P5 案，两轮制粗扫）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（P5-b 精扫补跑）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "trend-leftover-parameters.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs: list[dict[str, Any]] = [baseline_spec(), *P5_TRIALS]
    if args.extra_trial:
        extra = json.loads(args.extra_trial)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            specs.append(spec)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, specs)

    summary = {spec["key"]: trial_summary(report, spec) for spec in specs}
    report["summary"] = summary
    report["anchorChain"] = {
        "baseline": all(
            ((((summary.get("baseline") or {}).get("windows") or {}).get(win) or {}).get("anchor") or {}).get("match") is True
            for win in WINDOWS
        )
    }
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({
        "anchorChain": report["anchorChain"],
        "summary": {
            k: {
                **{kk: vv for kk, vv in v.items() if kk != "windows"},
                "windows": {w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "rankTrendSaEx", "rankTrendSaExRel", "triggerRateSA", "triggerFlag")} for w, d in v.get("windows", {}).items()},
            }
            for k, v in summary.items()
        },
    }, ensure_ascii=False, indent=2, default=str))
    print(f"[trend-leftover] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
