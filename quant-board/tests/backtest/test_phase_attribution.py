# -*- coding: utf-8 -*-
"""SP1 归因字段测试（章程 ranktrend-position-management-charter.md §4 SP1-T2；计划 ranktrend-position-sp1-plan.md）。

覆盖：_phase_context 纯函数（四带标签/Q1 两档/deltaScore/缺失 fail-visible）、
golden 锚（off+eodScores 与空 config 行为逐位相同）、ladder 臂 entryPhase 盖戳与因子一致、
trade_events/openPositions 透传、脉拍 attribution_stats 装配。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest import TradeSimulator
from backend.operations.phase_pulse import attribution_stats


def _jump_signal(snapshot_id: str, date: str, price: float, volume: int) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "code": "600001",
        "name": "测试股",
        "rank": 8,
        "price": price,
        "change": 2,
        "volume": volume,
        "candidateTier": "A_MAIN",
        "stage": "ignite",
        "regime": "strong",
        "confidence": 90,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "buy"},
                },
            },
            "meta": {"rawChange": 120},
        },
    }


FRAMES = [
    {"snapshotId": "s1", "timestamp": "s1", "tradingDate": "2026-05-06", "slotTime": "10:00"},
    {"snapshotId": "s2", "timestamp": "s2", "tradingDate": "2026-05-07", "slotTime": "10:00"},
    {"snapshotId": "s3", "timestamp": "s3", "tradingDate": "2026-05-08", "slotTime": "10:00"},
]

BASE = {
    "entryStrategy": "ranktrend_jump",
    "initialCapital": 100000,
    "positionSize": 0.1,
    "maxPositions": 1,
    "maxHoldingBars": 1,
    "enforceT1": True,
    "useOrderBookPrice": False,
    "enforceLimitStatus": False,
    "enforceOrderBookQueue": False,
    "enforceVolumeLimit": True,
    "volumeParticipationRate": 1,
    "feeRate": 0,
    "stampTaxRate": 0,
    "slippageRate": 0,
    "stopLoss": -0.5,
    "takeProfit": 0.5,
}

# 与既有 round-trips 参照测试同构的三信号结构（s2/s3 促成两次退出切片）
FULL_SIGNALS = [
    _jump_signal("s1", "2026-05-06", 10.0, 2_000),
    _jump_signal("s2", "2026-05-07", 9.0, 500),
    _jump_signal("s3", "2026-05-08", 12.0, 2_000),
]


def _run(trade_config: dict, signals: list[dict] | None = None, **overrides) -> dict:
    return TradeSimulator().run(
        FRAMES,
        signals if signals is not None else list(FULL_SIGNALS),
        {**BASE, **trade_config, **overrides},
    )


# ── _phase_context 纯函数 ──


def test_phase_context_full_fields():
    cfg = {"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-04": 55.0, "2026-05-05": 65.0}}}
    ctx = TradeSimulator._phase_context(cfg, "2026-05-06")
    assert ctx["prevDate"] == "2026-05-05"
    assert ctx["prevScore"] == 65.0
    assert ctx["prev2Score"] == 55.0
    assert ctx["deltaScore"] == 10.0
    assert ctx["phase"] == "offense"  # ≥60（Q1 口径）
    assert ctx["band"] == "强60-80"
    assert ctx["factor"] == 1.0  # mode=off 恒 1.0


def test_phase_context_band_mapping():
    def band_of(score: float) -> str:
        cfg = {"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-05": score}}}
        return TradeSimulator._phase_context(cfg, "2026-05-06")["band"]

    assert band_of(39.9) == "冷10-40"
    assert band_of(40.0) == "弱势40-60"
    assert band_of(59.9) == "弱势40-60"
    assert band_of(60.0) == "强60-80"
    assert band_of(80.0) == "极热≥80"


def test_phase_context_gap_day_strict_prev():
    """缺档日（前日键存在但分数缺失）→ 严格前日键：归因全 None，不回跳更早有分日（评审 P1#1）。"""
    cfg = {"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-04": 55.0, "2026-05-05": None}}}
    ctx = TradeSimulator._phase_context(cfg, "2026-05-06")
    assert ctx["prevDate"] == "2026-05-05"
    assert ctx["prevScore"] is None and ctx["prev2Score"] is None
    assert ctx["deltaScore"] is None and ctx["band"] is None and ctx["phase"] is None
    assert ctx["factor"] == 1.0


def test_phase_context_defense_and_delta_missing():
    cfg = {"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-05": 45.0}}}
    ctx = TradeSimulator._phase_context(cfg, "2026-05-06")
    assert ctx["phase"] == "defense"
    assert ctx["prev2Score"] is None
    assert ctx["deltaScore"] is None


def test_phase_context_no_ctrl_or_no_scores():
    ctx = TradeSimulator._phase_context({}, "2026-05-06")
    assert ctx["prevScore"] is None and ctx["band"] is None and ctx["factor"] == 1.0
    ctx2 = TradeSimulator._phase_context({"phaseExposureControl": {"mode": "off", "eodScores": {}}}, "2026-05-06")
    assert ctx2["prevDate"] is None and ctx2["prevScore"] is None


# ── golden 锚（全模拟）──


def test_golden_anchor_off_with_eod_behaviour_identical():
    eod = {"2026-05-05": 30.0, "2026-05-06": 45.0, "2026-05-07": 65.0}
    plain = _run({})
    off = _run({"phaseExposureControl": {"mode": "off", "eodScores": eod}})

    def strip(trades: list[dict]) -> list[dict]:
        return [{k: v for k, v in t.items() if k not in ("entryPhase", "entryAtr")} for t in trades]

    # 行为字段逐位相同（归因新字段除外）：roundTripTrades + tradeEvents + 权益曲线（评审 P2#7 广度补强）
    strip_ev = lambda evs: [
        {k: v for k, v in e.items() if k not in ("entryPhase", "entryAtr")} for e in evs
    ]
    assert strip_ev(plain["tradeEvents"]) == strip_ev(off["tradeEvents"])
    assert [round(float(p["equity"]), 6) for p in plain["equityCurve"]] == [
        round(float(p["equity"]), 6) for p in off["equityCurve"]
    ]
    assert strip(plain["roundTripTrades"]) == strip(off["roundTripTrades"])
    assert plain["tradeCount"] == off["tradeCount"]
    assert plain["totalReturn"] == off["totalReturn"]
    # 空 config 不带归因字段（生产默认路径结构逐位不变）
    assert plain["roundTripTrades"][0]["entryPhase"] is None
    assert plain["roundTripTrades"][0]["entryAtr"] is None
    # off+eodScores 带归因且 factor=1.0（入场 05-06 前日 05-05=30 → 冷带）
    ep = off["roundTripTrades"][0]["entryPhase"]
    assert ep["factor"] == 1.0
    assert ep["prevScore"] == 30.0
    assert ep["band"] == "冷10-40"
    assert ep["phase"] == "defense"


# ── ladder 臂盖戳与因子一致 ──


def test_ladder_entry_phase_stamped_and_factor_consistent():
    eod = {"2026-05-05": 65.0}
    cfg = {"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]], "eodScores": eod}}
    res = _run(cfg)
    rt = res["roundTripTrades"][0]
    assert rt["entryPhase"]["factor"] == 0.3  # 前日 65 ≥60 → 三成
    assert rt["entryPhase"]["band"] == "强60-80"
    assert rt["entryPhase"]["phase"] == "offense"
    # 归因与实际行为一致：0.3 仓位 → 数量/盈亏小于满仓臂
    off = _run({"phaseExposureControl": {"mode": "off", "eodScores": eod}})
    assert rt["quantity"] < off["roundTripTrades"][0]["quantity"]


def test_missing_prev_score_fail_visible():
    cfg = {
        "phaseExposureControl": {
            "mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
            "eodScores": {"2026-05-05": None},
        }
    }
    res = _run(cfg)
    rt = res["roundTripTrades"][0]
    assert rt["entryPhase"]["prevScore"] is None
    assert rt["entryPhase"]["band"] is None
    assert rt["entryPhase"]["factor"] == 1.0  # 缺分数放行（不错杀）
    assert res["tradeCount"] == 1


# ── 透传：trade_events / openPositions ──


def test_trade_events_carry_entry_phase():
    eod = {"2026-05-05": 30.0}
    cfg = {"phaseExposureControl": {"mode": "off", "eodScores": eod}}
    res = _run(cfg)  # 三信号结构：s2/s3 触发卖出（卖出评估在信号驱动路径）
    buy_events = [e for e in res["tradeEvents"] if e.get("action") == "buy"]
    sell_events = [e for e in res["tradeEvents"] if e.get("action") == "sell"]
    assert buy_events and buy_events[0]["entryPhase"]["prevScore"] == 30.0
    assert sell_events and all(e.get("entryPhase") is not None for e in sell_events)


def test_open_positions_carry_entry_phase():
    eod = {"2026-05-05": 30.0}
    cfg = {"phaseExposureControl": {"mode": "off", "eodScores": eod}}
    res = _run(cfg, signals=[_jump_signal("s1", "2026-05-06", 10.0, 2_000)], maxHoldingBars=99)
    assert res["openPositionCount"] == 1
    assert res["openPositions"][0]["entryPhase"]["prevScore"] == 30.0
    assert res["openPositions"][0]["entryAtr"] is None  # useAtrStops 关 → 无 ATR（fail-visible null）


def test_ladder_blocked_trades_produce_no_trade_rows():
    """ladder factor=0 阻断笔不产生 trade（计划 T2.6②；blockedByPhase 计数可见）。"""
    cfg = {
        "phaseExposureControl": {
            "mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
            "eodScores": {"2026-05-05": 45.0},  # 前日 45 ∈[40,60) → 禁开仓
        }
    }
    res = _run(cfg)
    assert res["tradeCount"] == 0
    assert res["matchingDiagnostics"]["blockedByPhase"] >= 1


# ── 脉拍归因装配 ──


def test_pulse_attribution_stats():
    trades = [
        {"reason": "止盈", "entryPhase": {"band": "冷10-40", "factor": 1.0, "prevScore": 30.0, "phase": "defense"}},
        {"reason": "相位调仓(入冷清仓)", "entryPhase": {"band": "强60-80", "factor": 0.3, "prevScore": 65.0, "phase": "offense"}},
        {"reason": "止损", "entryPhase": {"band": "冷10-40", "factor": 1.0, "prevScore": 25.0, "phase": "defense"}},
        {"entryPhase": {"band": None, "factor": 1.0, "prevScore": None}},
        {"entryPhase": None},
        {},
    ]
    stats = attribution_stats(trades)
    assert stats["availableTrades"] == 3
    assert stats["missingEntryPhase"] == 3
    assert stats["byBand"]["冷10-40"]["trades"] == 2
    assert stats["byBand"]["冷10-40"]["factorSet"] == [1.0]
    assert stats["byBand"]["强60-80"]["factorSet"] == [0.3]
    assert stats["byPhase"] == {"defense": 2, "offense": 1}
    assert stats["rebalanceCount"] == 1


# ── SP2-T3 臂装配 ──


def test_build_arm_trade_configs_builtin_and_budget():
    from backend.operations.phase_pulse import build_arm_trade_configs

    eod = {"2026-05-05": 65.0}
    spec = build_arm_trade_configs(["baseline", "champion"], "", eod)
    assert set(spec["arms"]) == {"baseline", "champion"}
    assert spec["skipped"] == []
    assert spec["arms"]["baseline"]["phaseExposureControl"]["mode"] == "off"
    assert spec["arms"]["champion"]["phaseExposureControl"]["ladder"] == [[40, 1.0], [60, 0.0], [999, 0.3]]


def test_build_arm_trade_configs_challenger_budget_and_skip(tmp_path):
    import json

    from backend.operations.phase_pulse import build_arm_trade_configs

    cfg_file = tmp_path / "arms.json"
    cfg_file.write_text(json.dumps({
        "exit_v1": {"trade_config": {"phaseExitCoupling": {"mode": "per_band", "bands": {}}}},
        "rebal_v1": {"trade_config": {"phaseRebalance": {"enabled": True, "eodScores": {}}}},
        "extra": {"trade_config": {}},
        "broken": {},
    }, ensure_ascii=False), encoding="utf-8")
    spec = build_arm_trade_configs(
        ["baseline", "champion", "exit_v1", "rebal_v1", "extra", "broken", "ghost"], str(cfg_file), {})
    # 挑战者预算 ≤2：extra 被截断；broken 畸形 / ghost 未登记 → skipped 带原因码（评审 P2-5）
    assert set(spec["arms"]) == {"baseline", "champion", "exit_v1", "rebal_v1"}
    assert spec["skipped"] == ["budget:extra", "malformed:broken", "unregistered:ghost"]


def test_build_arm_trade_configs_jev_labels_injection(tmp_path):
    """SP4-T4：labels v3 注入 source=jev_seq_slot 臂（配置内已有键优先、文件覆盖）。"""
    from backend.operations.phase_pulse import build_arm_trade_configs

    cfg = tmp_path / "arms.json"
    cfg.write_text(json.dumps({
        "jev_seq_v1": {"trade_config": {"phaseExposureControl": {
            "source": "jev_seq_slot", "offenseFactor": 1.0, "defenseFactor": 0.3, "unknownFactor": 1.0,
            "phaseLabels": {"2026-01-01|09:30": "offense"},   # 配置内已有键
        }}},
    }, ensure_ascii=False), encoding="utf-8")
    jev = {"slotLabels": {"2026-01-01|09:30": "defense", "2026-01-02|10:00": "offense"},
           "fallbackLabels": {"2026-01-02": "offense"}}
    spec = build_arm_trade_configs(["baseline", "jev_seq_v1"], str(cfg), {}, None, jev)
    ec = spec["arms"]["jev_seq_v1"]["phaseExposureControl"]
    assert ec["phaseLabels"]["2026-01-01|09:30"] == "defense"  # 文件覆盖配置内键
    assert ec["phaseLabels"]["2026-01-02|10:00"] == "offense"
    assert ec["fallbackLabels"]["2026-01-02"] == "offense"
    # jev_labels=None（文件缺失）→ 保留配置内键，不崩溃（fail-visible 由调用方记录）
    spec2 = build_arm_trade_configs(["jev_seq_v1"], str(cfg), {}, None, None)
    assert spec2["arms"]["jev_seq_v1"]["phaseExposureControl"]["phaseLabels"]["2026-01-01|09:30"] == "offense"


def test_attribution_stats_jev_source_not_missing():
    """SP4 评审 P1-1：jev 源交易 prevScore 按设计置空——按 phaseLabel 分源计数，不误计 missing。"""
    trades = [
        {"entryPhase": {"source": "jev_seq_slot", "phaseLabel": "defense", "fallbackUsed": False, "factor": 0.3}},
        {"entryPhase": {"source": "jev_seq_slot", "phaseLabel": "offense", "fallbackUsed": True, "factor": 1.0}},
        {"entryPhase": {"source": "jev_seq_slot", "phaseLabel": None, "fallbackUsed": True, "factor": 1.0}},
        {"entryPhase": {"source": "prev_eod", "prevScore": 65.0, "phase": "offense", "band": "强60-80", "factor": 0.3}},
        {"entryPhase": None},
    ]
    stats = attribution_stats(trades)
    assert stats["availableTrades"] == 4
    assert stats["missingEntryPhase"] == 1  # 仅真正无盖章的一笔
    assert stats["byPhase"] == {"defense": 1, "offense": 2, "unknown": 1}  # jev unknown 档也入 byPhase
    assert stats["sourceAttribution"] == {"direct": 1, "fallback": 1, "unknown": 1}
