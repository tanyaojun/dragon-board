# -*- coding: utf-8 -*-
"""Track 1 维度话语权交易复核 harness（方案 A，审计修订稿 §2）。

臂表（§2.1，全 config 路径）：baseline / w1_old（res/rank/cs=1.0，23.9.1 落默认的
交易层直验）/ no_res / no_rank / no_vp / no_cs（各维票权归零，交易层边际）。

审计修订落实：
- M1 归因边界：no_* 臂只证"票权>0"，0.75 vs 1.0 裁决只来自 w1_old 臂（本 harness
  只出读数，判读按提案 §2.3 预登记规则在报告/文档层完成）；
- M2 样本量门槛：tradeCount < 30 的窗读数降级 "observation"，不进判定；
  触发面漂移卡：每臂并列 S+A 触发率 + 入场集合相对 baseline 的新增笔数（区分
  "票价值钱"与"入场集合变形"，e1a 教训）；
- M4 锚校验：w1_old 臂 saEx 副产须逐位复现阶段 24.3 a1 锚（0.0939/0.0854/0.0737）；
  baseline 臂 saEx 副产应复现 23.9.1 锚（0.1044/0.0918/0.0933）——不符即 patch 打错
  字段或 replay meta 影响了 synergy 组装，先修再继续；
- M3 窗口复用折扣：报告头标注 "windowsConsumed": true（三窗已被阶段 12-24 消费）。

用法：
  python -m backend.operations.track1_dimension_power [--window all] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.core.backtest.execution import TradeSimulator
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames
from backend.operations.track1_lifecycle_gate_trade import _trade_metrics

# 锚（审计 M4）代际注记（2026-09-15 fund10 落默认）：baseline = post-fund10 基线锚
# （报告 baseline-anchor-post-fund10.json；pre-fund10 代际 = 0.1044/0.0918/0.0933）；
# w1_old = 24.3 a1 实测（pre-fund10 代际，重跑漂移时按代际漂移处理——警告 + staleAnchor，不阻断）
ANCHOR_BASELINE: dict[str, float] = {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}
ANCHOR_W1_OLD: dict[str, float] = {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}
_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")

_W1 = {"tierSynergyResonanceVote": 1.0, "tierSynergyRankVote": 1.0, "tierSynergyCrossSectionVote": 1.0}

ARMS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "当前生产基线（combo_three_quarter，23.9.1 临时默认）", "overrides": {}, "anchor": ANCHOR_BASELINE},
    {"key": "w1_old", "desc": "旧 1.0 票权（a1 口径；0.75 vs 1.0 的交易层裁决臂，审计 M1/M4）", "overrides": dict(_W1), "anchor": ANCHOR_W1_OLD},
    {"key": "no_res", "desc": "res 票权归零（只证票权>0，M1）", "overrides": {"tierSynergyResonanceVote": 0.0}, "anchor": None},
    {"key": "no_rank", "desc": "rank 票权归零（只证票权>0，M1）", "overrides": {"tierSynergyRankVote": 0.0}, "anchor": None},
    {"key": "no_vp", "desc": "vp 票权归零（E→D 硬短路保留——与 23.8 monkeypatch 口径差异，§2.2）", "overrides": {"tierSynergyVolumePriceVote": 0.0}, "anchor": None},
    {"key": "no_cs", "desc": "cs 票权归零（只证票权>0，M1）", "overrides": {"tierSynergyCrossSectionVote": 0.0}, "anchor": None},
]

TRADE_COUNT_FLOOR = 30  # 审计 M2：低于此值的窗读数降级 observation


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def anchor_enforce(window: str, key: str, info: dict[str, Any]) -> bool:
    """锚失配处置（M4 + review I3 代际策略）：baseline 失配 = 当前配置跑不出基线锚，
    先修 patch/更新锚代际再继续（raise）；非 baseline（w1_old 代际绑定锚）失配按
    代际漂移处理——警告 + staleAnchor 标记，不阻断。返回是否 stale。"""
    if not info.get("checked") or info.get("match"):
        return False
    detail = f"{window}/{key} 锚失配: expected={info.get('expected')} actual={info.get('actual')}"
    if key == "baseline":
        raise ValueError(f"{detail}——baseline 须逐位复现当前代际锚（ANCHOR_BASELINE），先修 patch/更新锚代际")
    print(f"[warn] {detail}（代际漂移，标 staleAnchor，不阻断）", file=sys.stderr)
    return True


def _entry_keys(sim: dict[str, Any]) -> set[str]:
    """入场集合键（snapshotId:code），用于触发面漂移卡（审计 M2）。"""
    keys: set[str] = set()
    for event in sim.get("tradeEvents") or []:
        if str(event.get("action")) == "buy":
            keys.add(f"{event.get('snapshotId')}:{event.get('code')}")
    return keys


def arm_reading(sim: dict[str, Any], syn_stats: dict[str, Any], base_keys: set[str] | None) -> dict[str, Any]:
    """单臂单窗读数：交易指标 + S+A 触发率 + 入场集合漂移（M2）+ 样本量降级标注。"""
    metrics = _trade_metrics(sim)
    dist = syn_stats.get("distribution") or {}
    total = sum(v for v in dist.values() if isinstance(v, (int, float)))
    metrics["triggerRateSA"] = round((dist.get("S", 0) + dist.get("A", 0)) / total, 4) if total else None
    metrics["tradeCountGrade"] = "observation" if (metrics.get("tradeCount") or 0) < TRADE_COUNT_FLOOR else "decision"
    keys = _entry_keys(sim)
    metrics["entryCount"] = len(keys)
    if base_keys is not None:
        metrics["entryNewVsBaseline"] = len(keys - base_keys)
        metrics["entryDroppedVsBaseline"] = len(base_keys - keys)
    return metrics


def run_window(window: str, report: dict[str, Any]) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
    from backend.operations.optimize_resonance_parameters import _tier_summary
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = load_frames(start, end)
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，review I2）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[dim-track1] {window} frames={len(frames)}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        _save(report)
    if not frames:
        return

    arms = entry.setdefault("arms", {})
    base_keys: set[str] | None = None
    if "baseline" in arms:
        base_keys = set(arms["baseline"].get("entryKeys") or [])

    for spec in ARMS:
        key = spec["key"]
        if key in arms:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            if key == "baseline":
                base_keys = set(arms[key].get("entryKeys") or [])
            continue
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        # meta 同阶段 24.4 track1（candidateTierMode=execution 影响出场规则消费的 candidateTier）
        signals = engine.replay(frames, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
        sim = TradeSimulator().run(frames, signals, {"entryStrategy": "rank_trend_candidate"})
        syn_stats = _tier_summary(tier_forward_returns(signals, frames, horizon=1, dimension="synergy"))
        reading = arm_reading(sim, syn_stats, base_keys if key != "baseline" else None)
        reading["saExSideProduct"] = syn_stats.get("saEx")
        reading["anchor"] = anchor_check(window, syn_stats.get("saEx"), spec.get("anchor"))
        if anchor_enforce(window, key, reading["anchor"]):
            reading["staleAnchor"] = True  # 代际漂移标记（review I3：非 baseline 锚不阻断但留痕）
        reading["desc"] = spec["desc"]
        reading["entryKeys"] = sorted(_entry_keys(sim))
        if key == "baseline":
            base_keys = set(reading["entryKeys"])
        arms[key] = reading
        print(
            f"[dim-track1] {window} {key}: trades={reading['tradeCount']} wr={reading['winRate']} "
            f"pf={reading['profitFactor']} wrxpf={reading['winRateXpf']} ret={reading['totalReturn']} "
            f"trig={reading['triggerRateSA']} saEx={reading['saExSideProduct']} ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3：三窗已被阶段 12-24 消费，结论须标注折扣
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "track1-dimension-power.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__",)}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Track 1 维度话语权交易复核（方案 A）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "track1-dimension-power.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report)
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({w: {k: {kk: vv for kk, vv in a.items() if kk != "entryKeys"} for k, a in (report.get(w) or {}).get("arms", {}).items()} for w in windows}, ensure_ascii=False, indent=2))
    print(f"[dim-track1] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
