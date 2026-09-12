# -*- coding: utf-8 -*-
"""MA 交叉因子贡献度评估（backend/operations，2026-09-12，阶段 17）。

用户命题：技术结构四因子（方向/加速度/零线交叉/MACD）之外补均线 MA（参数定 10/20），
评估其与 MACD 的回测贡献度，决定是否加入技术信号。实现见
`backend/analysis/ranktrend/trend/technical.py::calculate_ma_cross`（接线默认全关，golden 不漂移）。

评估三口径（four-dim-algorithm-research 流程步骤 2/4/5，复用阶段 13/14 方法论）：
  A 事件级区分度：MA 金叉帧 vs MACD 金叉帧子集 h1 saEx/exAcc/n（tier_forward_returns + signal_filter，
    分位桶基线在子集内重算，与阶段 14 regime 分桶同口径）；
  B 状态级区分度：MA 多头排列(fast>slow) vs MACD 多头(dif>dea) 子集同上；
  C 边际贡献：evaluate_gate 六组 trial（baseline / 去MACD / 加MA / MA替代MACD / MA进trend_buy / 全开）。
    权重类 trial 走 from_patch（5 权重归一化和为 1，保证与 baseline 同量纲可比）。

窗口纪律：决策窗 04-15~07-31 + OOS-1 08-15~08-31 + OOS-2 09-01~09-09；FINAL(8/1-8/14) 冻结
（assert_not_frozen purpose=scan）；全程不写回默认值，正贡献仅作为候选默认值等用户决策。

fail-visible：子集样本量、unknown 率、macd 预热期（dif=dea=0）剔除数均如实输出，不伪造 0。

用法：
  python -m backend.operations.evaluate_ma_factor_contribution [--window decision|oos1|oos2|all]
      [--skip-trials] [--out <path>]
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
from backend.operations.optimize_resonance_parameters import _tier_summary, load_frames, sa_excess_of

WINDOWS: dict[str, tuple[str, str]] = {
    "decision": ("2026-04-15", "2026-07-31"),
    "oos1": ("2026-08-15", "2026-08-31"),
    "oos2": ("2026-09-01", "2026-09-09"),
}

# 边际贡献 trial 组（权重类经 from_patch 归一化，5 权重和恒为 1，与 baseline 同量纲）。
TRIALS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "默认配置（四因子）", "overrides": {}},
    {"key": "macd_off", "desc": "MACD 退出决策合成（其余权重归一化放大）", "overrides": {"macdWeight": 0.0}},
    {"key": "ma_join", "desc": "MA 加入决策合成第 5 分量（与 MACD 并存）", "overrides": {"maWeight": 0.25}},
    {"key": "ma_replace", "desc": "MA 替代 MACD 决策分量", "overrides": {"maWeight": 0.25, "macdWeight": 0.0}},
    {"key": "ma_replace_full", "desc": "MA 完全替代 MACD（决策分量 + trend_buy 参与位）", "overrides": {"maWeight": 0.25, "macdWeight": 0.0, "maCrossTrendBuy": True}},
    {"key": "ma_trendbuy", "desc": "仅 MA 金叉进 trend_buy OR 链（权重不动）", "overrides": {"maCrossTrendBuy": True}},
    {"key": "ma_full", "desc": "MA 全开（决策分量 + trend_buy）", "overrides": {"maWeight": 0.25, "maCrossTrendBuy": True}},
]


def _technical_of(signal: dict[str, Any]) -> dict[str, Any]:
    return ((signal.get("rankTrend") or {}).get("technical") or {})


def _ma_cross(signal: dict[str, Any]) -> dict[str, Any]:
    return _technical_of(signal).get("maCross") or {}


def _macd(signal: dict[str, Any]) -> dict[str, Any]:
    return _technical_of(signal).get("macd") or {}


def _macd_trend(signal: dict[str, Any]) -> str:
    """MACD 多空状态（dif/dea 可比时）；预热期（dif=dea=0）与缺字段 → unknown（不伪装）。"""
    macd = _macd(signal)
    dif, dea = macd.get("dif"), macd.get("dea")
    if not isinstance(dif, (int, float)) or not isinstance(dea, (int, float)):
        return "unknown"
    if dif == 0 and dea == 0:
        return "unknown"  # calculate_macd 预热期哨兵值
    return "bull" if dif > dea else "bear" if dif < dea else "flat"


SUBSETS: dict[str, tuple[str, Callable[[dict[str, Any]], bool]]] = {
    "ma_golden_event": ("MA 金叉事件帧", lambda s: _ma_cross(s).get("cross") == "golden"),
    "macd_golden_event": ("MACD 金叉事件帧", lambda s: _macd(s).get("cross") == "golden"),
    "ma_bull_state": ("MA 多头排列(fast>slow)", lambda s: _ma_cross(s).get("state") == "bull"),
    "ma_bear_state": ("MA 空头排列(fast<slow)", lambda s: _ma_cross(s).get("state") == "bear"),
    "macd_bull_state": ("MACD 多头(dif>dea)", lambda s: _macd_trend(s) == "bull"),
    "macd_bear_state": ("MACD 空头(dif<dea)", lambda s: _macd_trend(s) == "bear"),
    "ma_death_event": ("MA 死叉事件帧", lambda s: _ma_cross(s).get("cross") == "death"),
    "macd_death_event": ("MACD 死叉事件帧", lambda s: _macd(s).get("cross") == "death"),
    "both_golden": ("MA 与 MACD 同帧金叉", lambda s: _ma_cross(s).get("cross") == "golden" and _macd(s).get("cross") == "golden"),
}


def _trend_buy_or_chain_without_ma(signal: dict[str, Any]) -> bool:
    """trend_buy OR 链（direction buy / acceleration buy / MACD 金叉，不含 MA）。

    用于解释 ma_trendbuy trial 零增量：若所有 MA 金叉帧该谓词已为 True，
    则 maCrossTrendBuy=True 不可能改变任何 trend_buy 判定。
    """
    technical = _technical_of(signal)
    signals = technical.get("signals") or {}
    direction_buy = (signals.get("direction") or {}).get("signal") == "buy"
    acceleration_buy = (signals.get("acceleration") or {}).get("signal") == "buy"
    macd_golden = _macd(signal).get("cross") == "golden"
    return direction_buy or acceleration_buy or macd_golden


def subset_discrimination(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """A/B 口径：全量 + 各子集 h1 synergy saEx/exAcc/n；分位桶基线子集内重算（阶段 14 同口径）。"""
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    def _stats(filtered: Callable[[dict[str, Any]], bool] | None) -> dict[str, Any]:
        stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy", signal_filter=filtered)
        summary = _tier_summary(stats)
        summary["sampleCount"] = sum((stats.get("tiers") or {}).get(t, {}).get("count") or 0 for t in ("S", "A", "B", "C", "D", "E", "unknown"))
        return summary

    out: dict[str, Any] = {"all": _stats(None)}
    for key, (desc, pred) in SUBSETS.items():
        summary = _stats(pred)
        summary["desc"] = desc
        out[key] = summary
    # 事件重叠原始计数（信号级，非 tier 前瞻样本口径；供"MA 是否只是 MACD 影子"判断）
    out["eventOverlapRawCounts"] = {
        "totalSignals": len(signals),
        "maGolden": sum(1 for s in signals if SUBSETS["ma_golden_event"][1](s)),
        "macdGolden": sum(1 for s in signals if SUBSETS["macd_golden_event"][1](s)),
        "bothGolden": sum(1 for s in signals if SUBSETS["both_golden"][1](s)),
        "maBull": sum(1 for s in signals if SUBSETS["ma_bull_state"][1](s)),
        "macdBull": sum(1 for s in signals if SUBSETS["macd_bull_state"][1](s)),
        "maUnknown": sum(1 for s in signals if (_ma_cross(s).get("state") or "unknown") == "unknown"),
        "macdUnknown": sum(1 for s in signals if _macd_trend(s) == "unknown"),
        # MA 金叉帧被既有 trend_buy OR 链（direction/acceleration/MACD，不含 MA）覆盖的计数
        "maGoldenTrendBuyCovered": sum(
            1 for s in signals if SUBSETS["ma_golden_event"][1](s) and _trend_buy_or_chain_without_ma(s)
        ),
    }
    return out


def run_window(window: str, report: dict[str, Any], skip_trials: bool) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    frames = load_frames(start, end)
    print(f"[ma-eval] {window} frames={len(frames)} window={start}~{end}", file=sys.stderr)
    if not frames:
        print(f"[ma-eval] {window} no frames loaded — skip", file=sys.stderr)
        report[window] = {"error": "no frames", "frameCount": 0}
        return
    assert_not_frozen(frames, "scan")

    entry = report.setdefault(window, {"window": {"start": start, "end": end, "frameCount": len(frames)}})

    # A/B 口径：baseline 单次 replay 复用（maCross 观察字段与权重无关，默认配置即可产出）
    if "subsets" not in entry:
        t0 = time.time()
        from backend.analysis.ranktrend.engine import RankTrendPythonEngine

        signals = RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})
        print(f"[ma-eval] {window} baseline replay done signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)
        entry["subsets"] = subset_discrimination(signals, frames)
        entry["baselineReplaySignals"] = len(signals)
        _save(report)

    # C 口径：evaluate_gate 六组 trial（每组独立 replay）
    if not skip_trials:
        trials = entry.setdefault("trials", {})
        for spec in TRIALS:
            if spec["key"] in trials:
                print(f"[skip] {window}/{spec['key']} (cached)", file=sys.stderr)
                continue
            config = RankTrendConfig.from_patch(spec["overrides"])
            print(f"[ma-eval] {window} {spec['key']} {spec['overrides']} ...", file=sys.stderr)
            t0 = time.time()
            result = evaluate_gate(config, frames)
            result["elapsedSec"] = round(time.time() - t0, 1)
            trials[spec["key"]] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
            print(f"[ma-eval] {window} {spec['key']} -> score={result['score']} syn(saEx={result['synergy']['saEx']} pass={result['synergy']['passHard']}) trend(saEx={result['rankTrend']['saEx']}) ({result['elapsedSec']}s)", file=sys.stderr)
            _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "ma-factor-contribution.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="MA 交叉因子贡献度评估（阶段 17）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--skip-trials", action="store_true", help="只跑事件/状态级区分度（复用 baseline replay）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "ma-factor-contribution.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] loaded windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, args.skip_trials)

    report.pop("__out__", None)
    _save(report)
    print(f"[ma-eval] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
