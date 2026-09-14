# -*- coding: utf-8 -*-
"""Track 1 交易层复核：环境门形态候选的 winRate×pf 对照（阶段 24 §5.2，saEx 盲区闭环）。

背景：veto/降档/vp 短路形态改变直接动 entry/exit（synergy tier 分布平移 →
synergyExitOnDanger / downgradeSteps / S,A 入场池），saEx harness 测不到交易层效应
（阶段 23.5 对 decisionReversal* 的同类裁定）。判定卡通过候选（e1a_vp_off /
p2_e1a_b1）在进用户决策前必须过本复核。

口径：
- 三臂：baseline（当前默认）/ e1a（volumePriceGateMode=off）/ p2（e1a + veto 负票 0.75）；
- 交易配置：DEFAULT_TRADE_CONFIG + entryStrategy=rank_trend_candidate（生产默认）；
- 窗口：decision 04-15~07-31（主）+ oos2 09-01~12（9 月高增益窗）；8 月 FINAL 冻结窗
  排除（assert_not_frozen）；
- 指标：tradeCount / winRate / pf / winRate×pf / totalReturn / maxDD（对照阶段 7/
  lifecycle-rearchitecture 交易模拟口径）。

用法：
  python -m backend.operations.track1_lifecycle_gate_trade [--window decision]
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
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames
from backend.operations.evaluate_ts_factor_weights import WINDOWS

ARMS: list[dict[str, Any]] = [
    {"key": "baseline", "desc": "当前默认（gate 全 hard）", "strategy_config": {}},
    {"key": "e1a_vp_off", "desc": "vp E→D 短路移除（Track 2 PASS_CANDIDATE）", "strategy_config": {"volumePriceGateMode": "off"}},
    {"key": "p2_e1a_b1", "desc": "e1a × veto 负票 0.75（Track 2 PASS_CANDIDATE 首选）", "strategy_config": {"volumePriceGateMode": "off", "lifecycleVetoGateMode": "soft", "lifecycleVetoVoteStrength": 0.75}},
]

_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


def _trade_metrics(sim: dict[str, Any]) -> dict[str, Any]:
    """从 TradeSimulator summary 直取指标（totalReturn/maxDrawdown/winRate 已含未平仓市值口径）。"""
    win_rate = sim.get("winRate")
    pf = sim.get("profitFactor")
    wrxpf = round(win_rate * pf, 4) if isinstance(win_rate, (int, float)) and isinstance(pf, (int, float)) else None
    return {
        "tradeCount": sim.get("tradeCount"),
        "winRate": win_rate,
        "profitFactor": pf,
        "winRateXpf": wrxpf,
        "totalReturn": sim.get("totalReturn"),
        "maxDD": sim.get("maxDrawdown"),
    }


def run_window(window: str) -> dict[str, Any]:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    frames = load_frames(start, end)
    assert_not_frozen(frames, "scan")
    out: dict[str, Any] = {"window": {"start": start, "end": end, "frameCount": len(frames)}, "arms": {}}
    for arm in ARMS:
        t0 = time.time()
        config = RankTrendConfig.from_patch(arm["strategy_config"])
        _assert_overrides_applied(config, arm["strategy_config"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
        sim = TradeSimulator().run(frames, signals, {"entryStrategy": "rank_trend_candidate"})
        metrics = _trade_metrics(sim)
        out["arms"][arm["key"]] = {"desc": arm["desc"], **metrics}
        print(
            f"[track1] {window} {arm['key']}: trades={metrics['tradeCount']} winRate={metrics['winRate']} "
            f"pf={metrics['profitFactor']} wrxpf={metrics['winRateXpf']} ret={metrics['totalReturn']} "
            f"dd={metrics['maxDD']} ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
    base = out["arms"]["baseline"]
    for arm in ARMS[1:]:
        m = out["arms"][arm["key"]]
        m["wrxpfVsBaseline"] = (
            round(m["winRateXpf"] / base["winRateXpf"], 4)
            if m.get("winRateXpf") is not None and base.get("winRateXpf") not in (None, 0)
            else None
        )
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Track 1 交易层复核：环境门形态候选（阶段 24 §5.2）")
    parser.add_argument("--window", default="decision", choices=["decision", "oos1", "oos2"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-arm", default="", help="追加臂：JSON {key,desc,strategy_config}（候选 Track 1 复核）")
    args = parser.parse_args()

    if args.extra_arm:
        extra = json.loads(args.extra_arm)
        key = extra.get("key")
        if not isinstance(key, str) or not key.strip():
            raise SystemExit("extra arm key 必须是非空字符串（review I4）")
        if any(arm["key"] == key for arm in ARMS):
            raise SystemExit(f"extra arm key 冲突: {key}（与既有臂重名会污染对照读数，review I4）")
        strategy_config = extra.get("strategy_config", {})
        if not isinstance(strategy_config, dict):
            raise SystemExit("extra arm strategy_config 必须是对象（dict）")
        extra["strategy_config"] = strategy_config
        extra.setdefault("desc", "extra arm")
        ARMS.append(extra)
    report = run_window(args.window)
    out_path = Path(args.out) if args.out else REPORT_DIR / f"track1-lifecycle-gate-{args.window}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["arms"], ensure_ascii=False, indent=2))
    print(f"[track1] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
