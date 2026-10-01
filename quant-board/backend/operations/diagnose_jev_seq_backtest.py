# -*- coding: utf-8 -*-
"""SP4-T5 前置：jev_seq_v1 全窗历史对照回测（in-sample，方向参考；样本外走廊仍是晋升门槛）。

用法（quant-board 目录，独立进程）：
  ./.venv/Scripts/python.exe -m backend.operations.diagnose_jev_seq_backtest

三臂（生产管线 BacktestService.run_ranktrend，dryRun，种子/策略与正式窗一致）：
  baseline     : 相位控制关（gate off + 归因 eodScores）
  champion     : ladder ③ [[40,1.0],[60,0.0],[999,0.3]]（前日 EOD 定相，现行默认）
  jev_seq_v1   : source=jev_seq_slot 两因子制（labels v3：offense 1.0 / defense 0.3 / unknown 1.0）
读数：全窗 + 逐月 交易数/净收益和/胜率/PF/最大回撤，jev 臂分源归因（直读/回退/unknown）。
诚实边界：jev 标签派生自同窗数据 → 本对照 in-sample，选择偏差不可排除；首段（03-27→04-14）
无 jev 标签 → unknown 放行≈基线。产物 data/reports/phase-monitor/jev-seq-backtest.json。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_pulse import load_eod_scores

LABELS = Path("data/reports/phase-monitor/phase-labels-jev-v3.json")
OUT = Path("data/reports/phase-monitor/jev-seq-backtest.json")
START, END = "2026-03-27", "2026-09-30"


def _stats(summary: dict) -> dict:
    from backend.operations.phase_trade_slice import round_trips_of

    trades = round_trips_of(summary)
    rets = [float(t["netReturn"]) for t in trades if isinstance(t.get("netReturn"), (int, float))]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    eq = [float(pt.get("equity") or 0.0) for pt in (summary.get("equityCurve") or [])]
    peak, mdd = 0.0, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    monthly: dict[str, dict] = {}
    for t in trades:
        m = str(t.get("entryTradingDate") or "")[:7]
        r = float(t.get("netReturn") or 0.0)
        slot = monthly.setdefault(m, {"trades": 0, "sumNetReturn": 0.0})
        slot["trades"] += 1
        slot["sumNetReturn"] = round(slot["sumNetReturn"] + r, 4)
    return {
        "tradeCount": len(rets),
        "sumNetReturn": round(sum(rets), 4) if rets else 0.0,
        "winRate": round(len(wins) / len(rets), 4) if rets else None,
        "profitFactor": round(sum(wins) / abs(sum(losses)), 4) if wins and losses else None,
        "maxDrawdown": round(mdd, 4) if len(eq) >= 2 else None,
        "finalEquity": round(eq[-1], 2) if eq else None,
        "monthly": dict(sorted(monthly.items())),
    }


def _jev_source_stats(summary: dict) -> dict:
    counts = {"direct": 0, "fallback": 0, "unknown": 0}
    for t in summary.get("roundTripTrades") or []:
        ep = t.get("entryPhase") if isinstance(t.get("entryPhase"), dict) else None
        if not isinstance(ep, dict) or ep.get("source") != "jev_seq_slot":
            continue
        if ep.get("phaseLabel") in ("offense", "defense"):
            counts["fallback" if ep.get("fallbackUsed") else "direct"] += 1
        else:
            counts["unknown"] += 1
    return counts


def main() -> int:
    from backend.cli import runtime_session
    from backend.services.backtest_service import BacktestService

    eod_scores = load_eod_scores(END)
    eod_valid = {d: s for d, s in eod_scores.items() if s is not None}
    jev = json.loads(LABELS.read_text(encoding="utf-8")) if LABELS.exists() else None
    if jev is None:
        print(f"[jev-backtest] labels v3 缺失：{LABELS}", file=sys.stderr)
        return 2

    base_payload = {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "start_date": START,
        "end_date": END,
        "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
        "random_seed": 20260430,
        "dryRun": True,
    }
    arms = {
        "baseline": {"phaseExposureControl": {"mode": "off", "eodScores": eod_valid}},
        "champion": {"phaseExposureControl": {"mode": "ladder",
                                              "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
                                              "eodScores": eod_valid}},
        "jev_seq_v1": {"phaseExposureControl": {
            "source": "jev_seq_slot",
            "phaseLabels": jev.get("slotLabels") or {},
            "fallbackLabels": jev.get("fallbackLabels") or {},
            "offenseFactor": 1.0, "defenseFactor": 0.3, "unknownFactor": 1.0}},
    }
    service = BacktestService(runtime_session())
    report = {
        "meta": {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "window": [START, END], "randomSeed": 20260430,
            "labelsVersion": (jev.get("meta") or {}).get("version"),
            "honesty": "in-sample 历史对照（jev 标签派生自同窗数据，选择偏差不可排除）；"
                       "样本外走廊（10-12 月脉拍）才是晋升门槛；首段无 jev 标签日 unknown 放行≈基线",
        },
        "arms": {},
    }
    for name, ctrl in arms.items():
        print(f"[jev-backtest] 运行臂 {name} ...", file=sys.stderr)
        summary = service.run_ranktrend({**base_payload, "trade_config": ctrl})
        entry = _stats(summary)
        raw_trades = summary.get("roundTripTrades") or []
        first_ep = raw_trades[0].get("entryPhase") if raw_trades else None
        # fail-visible：原始往返笔数 + 首笔归因源（防配置未达模拟器的静默失效）
        entry["debug"] = {"rawRoundTripCount": len(raw_trades),
                          "firstEntryPhaseSource": (first_ep or {}).get("source") if isinstance(first_ep, dict) else None,
                          "payloadCtrlKeys": sorted(ctrl.keys())}
        if name == "jev_seq_v1":
            entry["sourceAttribution"] = _jev_source_stats(summary)
        report["arms"][name] = entry
        print(f"[jev-backtest] {name}: {json.dumps({k: entry[k] for k in ('tradeCount', 'sumNetReturn', 'maxDrawdown')}, ensure_ascii=False)}", file=sys.stderr)

    b, c, j = report["arms"]["baseline"], report["arms"]["champion"], report["arms"]["jev_seq_v1"]
    report["comparison"] = {
        "champion_vs_baseline": {"netReturnDelta": round(c["sumNetReturn"] - b["sumNetReturn"], 4),
                                 "ddImprovement": round(b["maxDrawdown"] - c["maxDrawdown"], 4) if b["maxDrawdown"] is not None and c["maxDrawdown"] is not None else None},
        "jev_vs_champion": {"netReturnDelta": round(j["sumNetReturn"] - c["sumNetReturn"], 4),
                            "ddImprovement": round(c["maxDrawdown"] - j["maxDrawdown"], 4) if c["maxDrawdown"] is not None and j["maxDrawdown"] is not None else None,
                            "tradesDelta": j["tradeCount"] - c["tradeCount"]}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # 评审 P1-3 自检：防配置未达模拟器的静默失效报告（如 arms 双重嵌套事故）
    champ_src = (c.get("debug") or {}).get("firstEntryPhaseSource")
    jev_src_sum = sum((j.get("sourceAttribution") or {}).values())
    if champ_src is None or (j["tradeCount"] > 0 and jev_src_sum == 0):
        print("[jev-backtest][自检失败] champion 无归因戳或 jev 分源全零——配置疑似未达模拟器，产物无效（已存档供排查）",
              file=sys.stderr)
        print(f"-> {OUT}（INVALID）")
        return 3
    print(json.dumps(report["comparison"], ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
