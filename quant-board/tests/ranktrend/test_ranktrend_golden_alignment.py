import hashlib
import json
import os
from pathlib import Path

from backend.analysis import ranktrend
from backend.analysis.ranktrend import engine as ranktrend_engine
from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest.engine import BacktestEngine
from backend.services import GoldenService


def _make_frames(include_hotlist_sentiment: bool = False) -> list[dict]:
    frames = [
        {
            "snapshotId": f"s{i}",
            "type": "half_hour",
            "timestamp": i,
            "tradingDate": "2026-06-05",
            "slotTime": "10:00",
            "marketContext": {
                "payload": {
                    "sentiment": {"phaseName": "发酵期"},
                    "marketData": {"ztCount": 42, "dtCount": 1, "upCount": 3200, "downCount": 900},
                }
            },
            "stocks": [
                {
                    "code": "000001",
                    "name": "样本",
                    "rank": max(1, 30 - i * 3),
                    "avgRankNum": max(1, 30 - i * 3),
                    "change": 1.5,
                    "volumeRatio": 1.8,
                    "zlje": 1200,
                    "zljzb": 1.2,
                }
            ],
        }
        for i in range(8)
    ]
    if include_hotlist_sentiment:
        for frame in frames:
            frame["hotlistSentiment"] = {"stage": "冰点", "riskLevel": "高", "confidence": 95}
    return frames


def test_golden_replay_uses_pure_analysis_candidate_tier_without_hotlist(monkeypatch) -> None:
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    frames = _make_frames()

    signals = engine.replay(frames, meta={"sampleQuality": "ok"})

    assert signals
    strategy = signals[-1]["rankTrend"]["strategy"]
    assert strategy["regime"]["state"] == "strong"
    assert "hotlist" not in strategy
    assert all("热榜情绪" not in reason for reason in strategy["reasons"])
    execution_strategy = signals[-1]["rankTrend"]["executionStrategy"]
    assert "candidateTier" in execution_strategy
    assert all("hotlistSentiment" not in frame for frame in frames)
    assert all("hotlistSentimentStatus" not in frame for frame in frames)
    assert all("hotlistSentimentReason" not in frame for frame in frames)
    assert signals[-1]["candidateTier"] == strategy["candidateTier"]


def test_golden_replay_regime_consumes_hotlist_sentiment() -> None:
    # 2026-08-18 口径统一：regime 情绪阶段读 hotlistSentiment（热榜池同源），
    # 全市场 sentiment 降为对照。预置 hotlistSentiment（冰点+高风险）→ regime 状态应反映热榜情绪（非 strong）。
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    baseline_frames = _make_frames()
    frames = _make_frames(include_hotlist_sentiment=True)
    baseline_signals = engine.replay(
        baseline_frames,
        meta={"datasetId": "dragonboard_live", "snapshotType": "half_hour", "sampleQuality": "ok"},
    )

    signals = engine.replay(
        frames,
        meta={"datasetId": "dragonboard_live", "snapshotType": "half_hour", "sampleQuality": "ok"},
    )

    assert baseline_signals
    assert signals
    baseline_strategy = baseline_signals[-1]["rankTrend"]["strategy"]
    strategy = signals[-1]["rankTrend"]["strategy"]
    # 无热榜情绪：池内因子 strong（全市场只作对照）
    assert baseline_strategy["regime"]["state"] == "strong"
    assert any("全市场情绪对照" in reason for reason in baseline_strategy["regime"]["reasons"])
    # 预置热榜情绪（冰点-8 + 高风险-8）→ 状态降级，不再被全市场"发酵期"误导
    assert strategy["regime"]["state"] != "strong"
    assert any("热榜情绪阶段" in reason for reason in strategy["regime"]["reasons"])
    assert any("热榜情绪风险" in reason for reason in strategy["regime"]["reasons"])
    assert "hotlist" not in strategy
    assert all("热榜情绪" not in reason for reason in strategy["reasons"])
    assert signals[-1]["candidateTier"] == baseline_signals[-1]["candidateTier"]
    assert signals[-1]["action"] == baseline_signals[-1]["action"]
    assert strategy["candidateTier"] == baseline_strategy["candidateTier"]
    assert strategy["action"] == baseline_strategy["action"]
    assert all(frame.get("hotlistSentiment", {}).get("stage") == "冰点" for frame in frames)
    assert all("hotlistSentimentStatus" not in frame for frame in frames)
    assert all("hotlistSentimentReason" not in frame for frame in frames)


def test_execution_replay_uses_hotlist_strategy_tier_when_requested() -> None:
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    frames = _make_frames(include_hotlist_sentiment=True)

    signals = engine.replay(
        frames,
        meta={"sampleQuality": "ok", "candidateTierMode": "execution"},
    )

    assert signals
    execution_strategy = signals[-1]["rankTrend"]["executionStrategy"]
    assert execution_strategy["hotlist"]["stage"] == "冰点"
    assert all("hotlistSentimentStatus" not in frame for frame in frames)
    assert signals[-1]["candidateTier"] not in {"A_MAIN", "B_IGNITION"}
    assert any("热榜冰点期" in reason or "暂停入场" in reason for reason in execution_strategy["reasons"])


def test_backtest_engine_requests_execution_candidate_tier(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_replay(self, frames, warmup_count=None, window_size=50, meta=None):
        captured["meta"] = meta or {}
        return []

    monkeypatch.setattr(ranktrend.RankTrendPythonEngine, "replay", fake_replay)

    BacktestEngine().run(
        [{"snapshotId": "s1", "stocks": [], "tradingDate": "2026-06-05", "slotTime": "10:00"}],
        {
            "strategy_config": {},
            "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
            "enable_trade_simulation": False,
            "quality_gate": {},
        },
    )

    assert captured["meta"]["candidateTierMode"] == "execution"


def test_build_signal_runs_risk_aware_analysis_order(monkeypatch) -> None:
    engine = RankTrendPythonEngine(RankTrendConfig())
    order: list[str] = []

    monkeypatch.setattr(
        ranktrend_engine,
        "analyze_technical",
        lambda percentiles, config, fallback: order.append("technical")
        or {
            "signals": {
                "direction": {"signal": "buy", "score": 1},
                "acceleration": {"signal": "buy", "score": 1},
                "zeroCross": {"signal": "hold", "score": 0},
            },
            "macd": {"cross": "golden", "rawScore": 1, "histogram": 0.2},
            "momentumProfile": {"short": 6, "mid": 5, "long": 4, "acceleration": 2},
        },
    )
    monkeypatch.setattr(ranktrend_engine, "detect_rank_jumps", lambda *args, **kwargs: {"hasJump": False, "events": []})
    monkeypatch.setattr(
        ranktrend_engine,
        "analyze_cycle",
        lambda ranks, percentiles, config, **kwargs: order.append("cycle")
        or {
            "rawStage": "expansion",
            "stage": "expansion",
            "transition": "ignition->expansion",
            "confidence": 78,
            "metrics": {
                "rankVelocity": 12,
                "rankAcceleration": 6,
                "drawdownFromPeak": 0,
                "hotZoneStreak": 1,
                "rankPathCommitment": 0.82,
            },
            "decision": {"action": "allow", "reasons": ["initial"]},
        },
    )
    monkeypatch.setattr(
        ranktrend_engine,
        "analyze_risk",
        lambda current_percentile, technical, cycle, zlje, zljzb, volume_ratio, config: order.append("risk")
        or {
            "pressure": 0.2,
            "divergence": {"severity": 0.1},
            "overheat": {"severity": 0.1},
            "synergy": 0,
        },
    )
    monkeypatch.setattr(
        ranktrend_engine,
        "analyze_cycle_with_risk",
        lambda cycle, risk, momentum, config: order.append("cycle_with_risk")
        or {
            **cycle,
            "decision": {"action": "allow", "reasons": ["risk aware"]},
        },
    )
    monkeypatch.setattr(
        ranktrend_engine,
        "compose_decision",
        lambda technical, cycle, risk, config: order.append("decision")
        or {
            "base": {"signal": "buy", "confidence": 80, "combinedScore": 0.5, "scoreMargin": 0.3},
            "final": {"signal": "buy", "confidence": 82},
        },
    )
    monkeypatch.setattr(
        ranktrend_engine,
        "compose_analysis_candidate_tier",
        lambda technical, cycle, risk, regime, config: order.append("strategy")
        or {
            "regime": regime,
            "momentum": technical["momentumProfile"],
            "candidateTier": "A_MAIN",
            "action": "focus",
            "reasons": ["analysis only"],
        },
    )

    signal = engine._build_signal(
        {
            "code": "000001",
            "name": "样本",
            "change": 1.5,
            "volumeRatio": 1.8,
            "zlje": 1200,
            "zljzb": 1.2,
        },
        {"snapshotId": "s7", "timestamp": 7, "tradingDate": "2026-06-05", "slotTime": "10:00", "type": "half_hour"},
        [30, 24, 18, 12],
        [25, 40, 55, 78],
        {"state": "strong", "score": 82, "reasons": ["strong regime"]},
        {"sampleQuality": "ok"},
    )

    assert signal is not None
    assert order.index("technical") < order.index("cycle") < order.index("risk")
    assert order.index("risk") < order.index("cycle_with_risk") < order.index("decision") < order.index("strategy")


def test_compose_decision_does_not_add_implicit_macd_buy_gate() -> None:
    config = RankTrendConfig.from_patch(
        {
            "momentumPeriods": [3, 5, 8, 13, 21],
            "momentumWeights": [0.15, 0.2, 0.25, 0.25, 0.15],
            "buyThresholds": [5, 8, 13, 21, 34],
            "sellThresholds": [-5, -8, -13, -21, -34],
            "macdFast": 13,
            "macdSlow": 21,
            "macdSignal": 8,
            "directionWeight": 0.3,
            "accelerationWeight": 0.25,
            "crossWeight": 0.2,
            "macdWeight": 0.25,
            "buyScoreThreshold": 0.12,
            "sellScoreThreshold": -0.12,
        }
    )

    decision = ranktrend.compose_decision(
        technical={
            "signals": {
                "direction": {"signal": "buy", "score": 0.5719578382696798},
                "acceleration": {"signal": "buy", "score": 0.4179498301302663},
                "zeroCross": {"signal": "hold", "score": 0},
            },
            "macd": {"cross": "none", "rawScore": 0},
        },
        cycle={"stage": "crowded"},
        risk={
            "pressure": 0,
            "divergence": {"severity": 0},
            "overheat": {"severity": 0},
            "synergy": 0,
        },
        config=config,
    )

    assert config.requireMacdGoldenCross is False
    assert decision["base"]["signal"] == "buy"
    assert decision["final"]["signal"] == "buy"


def test_compose_analysis_candidate_tier_keeps_ts_veto_and_regime_contract() -> None:
    strategy = ranktrend.compose_analysis_candidate_tier(
        technical={
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "buy"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "golden"},
            "momentumProfile": {"short": 8, "mid": 6, "long": 4, "acceleration": 2},
        },
        cycle={
            "stage": "expansion",
            "decision": {"action": "veto", "reasons": ["veto"]},
        },
        risk={
            "pressure": 0.12,
            "divergence": {"severity": 0.08},
            "overheat": {"severity": 0.11},
        },
        regime={"state": "strong", "score": 88, "reasons": ["strong regime"]},
    )

    assert strategy["regime"]["state"] == "strong"
    assert "marketRegime" not in strategy
    assert strategy["candidateTier"] == "N_NEUTRAL"
    assert strategy["action"] == "hold"
    assert "生命周期辅助决策一票否决，阻止进入 A/B 候选池" in strategy["reasons"]
    assert "市场环境强，允许跟踪点火/扩散机会" in strategy["reasons"]


def test_compose_analysis_candidate_tier_matches_ts_weak_market_downgrade() -> None:
    strategy = ranktrend.compose_analysis_candidate_tier(
        technical={
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "hold"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "none"},
            "momentumProfile": {"short": 5, "mid": 5, "long": 2, "acceleration": 1},
        },
        cycle={
            "stage": "expansion",
            "decision": {"action": "allow", "reasons": ["allow"]},
        },
        risk={
            "pressure": 0.2,
            "divergence": {"severity": 0.1},
            "overheat": {"severity": 0.1},
        },
        regime={"state": "retreat", "score": 22, "reasons": ["retreat regime"]},
    )

    assert strategy["candidateTier"] == "N_NEUTRAL"
    assert strategy["action"] == "hold"
    # 2026-08-18 环境门数据修正：retreat 仍禁 A/B（风控保留），降级措辞改为强/退潮
    assert any("市场强/退潮环境买入信号降级为观察" in r for r in strategy["reasons"])
    assert "市场退潮，优先控制回撤风险" in strategy["reasons"]


def test_golden_service_normalizes_cycle_and_decision_summary() -> None:
    normalized = GoldenService._normalize_expected_payload(
        [
            {
                "snapshotId": "half_hour:2026-06-06:11:00",
                "code": "000001",
                "candidateTier": "A_MAIN",
                "action": "focus",
                "stage": "expansion",
                "regime": "strong",
                "rank": 44,
                "confidence": 78.2,
                "rankTrend": {
                    "technical": {
                        "signals": {"direction": {"signal": "buy"}},
                        "momentumProfile": {"short": 5.0, "mid": 4.5, "long": 2.0, "acceleration": 1.2},
                    },
                    "cycle": {
                        "transition": "ignition->expansion",
                        "entryAdvice": {"bias": "preferred"},
                        "decision": {"action": "allow", "confidence": 73.0},
                    },
                    "risk": {"pressure": 0.12, "divergence": {"severity": 0.08}, "overheat": {"severity": 0.11}},
                    "decision": {
                        "base": {"signal": "buy", "confidence": 82.5},
                        "final": {"signal": "buy", "confidence": 78.2},
                    },
                },
            }
        ]
    )

    row = normalized[0]
    assert row["cycle"]["transition"] == "ignition->expansion"
    assert row["cycle"]["entryAdvice"]["bias"] == "preferred"
    assert row["cycle"]["decision"]["action"] == "allow"
    assert row["decision"]["final"]["confidence"] == 78.2


def test_golden_service_compare_reports_nested_cycle_path() -> None:
    expected = [{"cycle": {"transition": "ignition->expansion"}}]
    actual = [{"cycle": {"transition": "expansion->crowded"}}]

    issues = GoldenService._compare(expected, actual, tolerance=1e-6, strict=True)

    assert issues == ["$[0].cycle.transition: expected 'ignition->expansion' actual 'expansion->crowded'"]


# ---------------------------------------------------------------------------
# 引擎性能优化 golden 护栏（2026-09-23）：代表性帧集 replay 输出全字段快照逐位比对。
#
# 覆盖路径：多 lifecycle stage（ignition/expansion/crowded/reversal/cooling）、
# regime 四相位（发酵/高潮/退潮/冰点）+ hotlistSentiment 有/无双分支、样本不足
# （sparse 股）、市场字段缺失（change/volumeRatio/zlje/zljzb 轮流缺失）、
# 滑动窗口跨越（64 帧 > window_size=50）、ATR high/low 缺失与 close 全缺、
# avgRankNum<=0 池过滤、analysis/execution 双档位源、lifecycleConfirmFrames=2
# 的 veto/B-D 连续确认链、replay_frame_at 单帧链、BacktestEngine 撮合链。
#
# 重建快照（仅限引擎行为有意变更且已评审后）：
#   Git Bash: RANKTREND_GOLDEN_SNAPSHOT_REGEN=1 python -m pytest tests/test_ranktrend_golden_alignment.py -k snapshot -q
#   PowerShell: $env:RANKTREND_GOLDEN_SNAPSHOT_REGEN="1" 后运行同命令
# 帧集生成器与本快照必须同步演化；改动 _guardrail_frames 后必须重建快照并逐行 review diff。
# ---------------------------------------------------------------------------

GOLDEN_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "ranktrend_golden_replay_snapshot_v1.json.gz"


def _write_golden_snapshot(snapshot: dict) -> None:
    import gzip

    with gzip.open(GOLDEN_SNAPSHOT_PATH, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(snapshot, fh, sort_keys=True, ensure_ascii=False, indent=1, allow_nan=False)
        fh.write("\n")


def _read_golden_snapshot() -> dict:
    import gzip

    with gzip.open(GOLDEN_SNAPSHOT_PATH, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _guardrail_frames() -> list[dict]:
    phases = [
        {"phaseName": "发酵期", "marketData": {"ztCount": 42, "dtCount": 1, "upCount": 3200, "downCount": 900}},
        {"phaseName": "高潮期", "marketData": {"ztCount": 88, "dtCount": 3, "upCount": 4100, "downCount": 500}},
        {"phaseName": "退潮期", "marketData": {"ztCount": 18, "dtCount": 12, "upCount": 1200, "downCount": 3300}},
        {"phaseName": "冰点期", "marketData": {"ztCount": 5, "dtCount": 25, "upCount": 600, "downCount": 4200}},
    ]
    hotlist_stages = [("冰点", "高"), ("发酵", "中"), ("高潮", "低"), ("退潮", "中")]
    slots = ["10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30"]
    frames: list[dict] = []
    for i in range(64):
        phase = phases[(i // 16) % 4]
        stocks: list[dict] = []

        def _bar(code: str, close: float, *, with_hl: bool = True) -> dict:
            bar = {"code": code, "close": close, "price": close, "amount": 50_000_000 + i * 1_000_000, "volume": 120_000 + i * 900}
            if with_hl:
                bar["high"] = close + 0.15
                bar["low"] = close - 0.2
            return bar

        riser_close = 10 + i * 0.2
        stocks.append({
            **_bar("600001", riser_close),
            "name": "连板晋升", "rank": max(1, 44 - i * 2 // 3),
            "avgRankNum": max(1.0, 44 - i * 0.65),
            "change": 2.5 + (i % 5), "volumeRatio": 1.1 + (i % 4) * 0.4,
            "zlje": 800 + i * 120, "zljzb": 0.8 + (i % 6) * 0.3,
        })
        crowded_avg = 1.2 + (i % 3) * 0.4 if i <= 52 else 1.2 + (i - 52) * 2.2
        stocks.append({
            **_bar("600002", 20 + i * 0.1),
            "name": "龙头横盘", "rank": 1 if i <= 52 else 1 + (i - 52),
            "avgRankNum": crowded_avg,
            "change": 6.9 - (i % 3), "volumeRatio": 2.2,
            "zlje": 5200 + i * 60, "zljzb": 2.4,
        })
        if i < 30:
            reverser_avg, reverser_chg = 2.5 + (i % 2), 5.0
        elif i < 48:
            reverser_avg, reverser_chg = 3 + (i - 30) * 2.6, -1 - (i % 4)
        else:
            reverser_avg, reverser_chg = 50 + i, -3 - (i % 3)
        stocks.append({
            **_bar("600003", max(3.0, 18 - i * 0.12)),
            "name": "断板回落", "rank": max(1, int(reverser_avg)),
            "avgRankNum": reverser_avg, "change": reverser_chg,
            "volumeRatio": 0.7 + (i % 3) * 0.5, "zlje": -400 + i * 30, "zljzb": -0.6 + (i % 4) * 0.4,
        })
        stocks.append({
            **_bar("600004", 8 + (i % 9) * 0.1),
            "name": "温和退潮", "rank": 9 + i // 3,
            "avgRankNum": 9 + i * 0.35,
            "change": 1.2 - (i % 3) * 0.8, "volumeRatio": 0.9,
            "zlje": 120 - i * 9, "zljzb": 0.3 - (i % 5) * 0.2,
        })
        stocks.append({
            **_bar("600005", 6 + (i % 6) * 0.35),
            "name": "榜单震荡", "rank": 6 + (i * 7) % 23,
            "avgRankNum": 6 + (i * 7) % 23,
            "change": ((i * 11) % 13) - 6, "volumeRatio": 0.6 + ((i * 5) % 9) * 0.35,
            "zlje": ((i * 13) % 19) * 100 - 900, "zljzb": ((i * 3) % 7) - 3,
        })
        if i % 3 == 0:
            stocks.append({
                **_bar("600006", 15 + i * 0.1, with_hl=False),
                "name": "间歇在榜", "rank": 4,
                "avgRankNum": 4.4, "change": 3.3, "volumeRatio": 1.6, "zlje": 900, "zljzb": 1.1,
            })
        if i < 2 or 30 <= i < 32:
            stocks.append({
                **_bar("600009", 12.0 + (i % 4), with_hl=False),
                "name": "短暂在榜", "rank": 8,
                "avgRankNum": 8.8, "change": 2.0, "volumeRatio": 1.2, "zlje": 500, "zljzb": 0.5,
            })
        no_fields: dict = {
            "code": "600007", "name": "缺字段样本", "rank": 12 + (i * 3) % 9,
            "avgRankNum": 12 + (i * 3) % 9,
        }
        if i % 2:
            no_fields["change"] = 1.8
        if i % 3 != 0:
            no_fields["volumeRatio"] = 1.0 + (i % 2) * 0.5
        if i % 4 != 0:
            no_fields["zlje"] = 300 + i * 7
        if i % 5 != 0:
            no_fields["zljzb"] = 0.4
        if i % 7 != 0:
            no_fields["price"] = 9.5 + (i % 4) * 0.1
            no_fields["close"] = no_fields["price"]
        stocks.append(no_fields)
        stocks.append({
            "code": "600008", "name": "零均榜过滤", "rank": 20, "avgRankNum": 0,
            "change": 0.5, "volumeRatio": 0.8, "zlje": 10, "zljzb": 0.1,
            "close": 5.0, "price": 5.0, "amount": 8_000_000, "volume": 30_000,
        })
        frame = {
            "snapshotId": f"gg:2026-06-{i // 8 + 1:02d}:{slots[i % 8]}",
            "type": "half_hour",
            "timestamp": 1_782_000_000_000 + i * 1_800_000,
            "tradingDate": f"2026-06-{i // 8 + 1:02d}",
            "slotTime": slots[i % 8],
            "marketContext": {"payload": {"sentiment": {"phaseName": phase["phaseName"]}, "marketData": phase["marketData"]}},
            "stocks": stocks,
        }
        if i >= 24:
            stage, risk = hotlist_stages[(i // 8) % 4]
            frame["hotlistSentiment"] = {"stage": stage, "riskLevel": risk, "confidence": 55 + (i % 9)}
            frame["hotlistSentimentStatus"] = "ok"
        frames.append(frame)
    return frames


def _build_golden_snapshot() -> dict:
    frames = _guardrail_frames()
    meta_ok = {"sampleQuality": "ok"}
    scenarios: dict[str, dict] = {}

    engine = RankTrendPythonEngine(RankTrendConfig())
    scenarios["replayDefaultAnalysis"] = {
        "configRepr": repr(engine.config),
        "signals": engine.replay(frames, meta=meta_ok),
    }
    engine_exec = RankTrendPythonEngine(RankTrendConfig())
    scenarios["replayDefaultExecution"] = {
        "configRepr": repr(engine_exec.config),
        "signals": engine_exec.replay(frames, meta={"sampleQuality": "ok", "candidateTierMode": "execution"}),
    }
    engine_k2 = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3, "lifecycleConfirmFrames": 2}))
    scenarios["replayPatchedConfirmK2"] = {
        "configRepr": repr(engine_k2.config),
        "signals": engine_k2.replay(frames, meta=meta_ok),
    }
    for index in (10, 40, 63):
        engine_at = RankTrendPythonEngine(RankTrendConfig())
        scenarios[f"frameAt{index}"] = {
            "configRepr": repr(engine_at.config),
            "signals": engine_at.replay_frame_at(frames, index, window_size=50, meta=meta_ok),
        }
    result = BacktestEngine().run(
        _guardrail_frames(),
        {
            "strategy_config": {},
            "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
            "enable_trade_simulation": True,
            "quality_gate": {},
            "random_seed": 20260430,
        },
    )
    simulation = result.get("tradeSimulation") or {}
    scenarios["backtestSimulation"] = {
        "trades": simulation.get("trades") or [],
        "equityCurve": simulation.get("equityCurve") or [],
        "equityHistory": simulation.get("equityHistory") or [],
        "tradeEvents": simulation.get("tradeEvents") or [],
    }
    return {
        "schemaVersion": 1,
        "framesDigest": hashlib.sha256(_canonical_json(frames).encode("utf-8")).hexdigest(),
        "scenarios": scenarios,
    }


def _structural_diffs(expected, actual, prefix: str, limit: int = 8) -> list[str]:
    diffs: list[str] = []
    if type(expected) is not type(actual):
        diffs.append(f"{prefix}: type {type(expected).__name__} vs {type(actual).__name__}")
        return diffs
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                diffs.append(f"{prefix}.{key}: 快照缺键，输出多出")
            elif key not in actual:
                diffs.append(f"{prefix}.{key}: 输出缺键")
            else:
                diffs.extend(_structural_diffs(expected[key], actual[key], f"{prefix}.{key}", limit))
            if len(diffs) >= limit:
                break
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            diffs.append(f"{prefix}: list 长度 {len(expected)} vs {len(actual)}")
        for idx in range(min(len(expected), len(actual))):
            diffs.extend(_structural_diffs(expected[idx], actual[idx], f"{prefix}[{idx}]", limit))
            if len(diffs) >= limit:
                break
    elif expected != actual:
        diffs.append(f"{prefix}: snapshot={expected!r} vs output={actual!r}")
    return diffs


def test_golden_replay_full_field_snapshot_unchanged() -> None:
    snapshot = _build_golden_snapshot()
    if os.environ.get("RANKTREND_GOLDEN_SNAPSHOT_REGEN") == "1":
        _write_golden_snapshot(snapshot)
        # 重建运行永不计绿：regen 模式下写入后即失败，必须去掉开关重跑逐位通过才算数
        # （否则环境变量泄漏会让护栏变成写入后自比的恒真测试）。
        raise AssertionError(
            "golden 快照已重建：请去掉 RANKTREND_GOLDEN_SNAPSHOT_REGEN 后重跑本测试确认逐位通过，"
            "并 review 快照 diff 后才允许提交。"
        )
    assert GOLDEN_SNAPSHOT_PATH.exists(), (
        f"缺少 golden 快照 fixture：{GOLDEN_SNAPSHOT_PATH}。"
        "首次生成请显式运行 RANKTREND_GOLDEN_SNAPSHOT_REGEN=1 并 review 快照内容后再入库。"
    )
    stored = _read_golden_snapshot()
    assert stored["schemaVersion"] == snapshot["schemaVersion"], "快照 schemaVersion 不一致，需确认版本演进"
    assert stored["framesDigest"] == snapshot["framesDigest"], (
        "护栏帧集已变化：必须显式 RANKTREND_GOLDEN_SNAPSHOT_REGEN=1 重建快照并逐行 review diff，"
        "否则无法判断引擎输出漂移来源。"
    )
    for name, actual_scenario in snapshot["scenarios"].items():
        expected_scenario = stored["scenarios"].get(name)
        assert expected_scenario is not None, f"快照缺少场景 {name}，需重建快照"
        if "configRepr" in actual_scenario:
            assert expected_scenario.get("configRepr") == actual_scenario["configRepr"], f"{name}: config 指纹漂移"
        if _canonical_json(expected_scenario) != _canonical_json(actual_scenario):
            diffs = _structural_diffs(expected_scenario, actual_scenario, f"{name}")
            raise AssertionError(
                f"场景 {name} 输出与 golden 快照不一致（逐位护栏，引擎行为发生漂移）：\n" + "\n".join(diffs)
            )
