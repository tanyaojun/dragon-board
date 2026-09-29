"""组装下沉（回测方案 §3.2）：assemble_observation 单测 + replay 信号含 synergy 集成测试。

合同：
- assemble_observation(analysis, stock, config) 组装 observation.volumePrice / observation.synergy
  + synergy.signalTier / tierReasons，与 API 单股链路同源（resonance 已写入 analysis 时参与投票）。
- replay() 信号含 observation.volumePrice / observation.synergy.signalTier（回测交易链路可消费）。
- API 单股链路输出逐字段不变（由 test_ranktrend_analyze_api 回归覆盖）。
"""

from __future__ import annotations

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.volume_price import assemble_observation


def _vp_positive_stock() -> dict:
    """change>0 且 vr>=1.05 且 zljzb>0 → vp A/up（放量上涨 + 资金流入）。"""
    return {"code": "000001", "name": "样本", "change": 3.5, "volumeRatio": 1.8, "zlje": 1200, "zljzb": 5.0}


def _vp_neutral_stock() -> dict:
    """change=0 → direction neutral → 不投票；quadrant normal → vp C。"""
    return {"code": "000001", "name": "样本", "change": 0.0, "volumeRatio": 1.0, "zlje": 0, "zljzb": 0.0}


def _sample_analysis(res_tier: str | None = "A", res_dir: str | None = "buy") -> dict:
    return {
        "resonance": {"signalTier": res_tier, "direction": res_dir},
        "observation": {
            "rankTrend": {"signalTier": "A", "direction": "buy"},
            "lifecycle": {"stage": "expansion", "signalTier": "A"},
        },
    }


def test_assemble_observation_basic() -> None:
    """resonance + rankTrend + vp 三票 buy → v=0.75+0.75+1.0=2.5，lc==A → A（采纳票权 0.75）。"""
    analysis = _sample_analysis()
    observation = assemble_observation(analysis, _vp_positive_stock())
    vp = observation["volumePrice"]
    assert vp["signalTier"] == "A"
    assert observation["synergy"]["signalTier"] == "A"
    assert observation["synergy"]["tierReasons"]
    # 同步写回 analysis.observation
    assert analysis["observation"] is observation


def test_assemble_observation_without_resonance() -> None:
    """replay 链路无 resonance（横截面缺市场 median）：共振维缺票（vote=0），synergy 仍可计算。"""
    analysis = _sample_analysis()
    analysis.pop("resonance")
    observation = assemble_observation(analysis, _vp_neutral_stock())
    # rank A/buy=0.75 + vp 0 票 → v=0.75 → C（采纳票权 0.75）
    assert observation["synergy"]["signalTier"] == "C"


def test_assemble_observation_resonance_vote_affects_tier() -> None:
    """有 resonance 票时 v=1.5 → B；无 resonance 时 v=0.75 → C（共振票参与投票的差异可见）。
    lc 置 None 隔离周期升档影响（采纳票权 0.75，阶段 23.9）。"""
    analysis = _sample_analysis()
    analysis["observation"]["lifecycle"]["signalTier"] = None
    observation = assemble_observation(analysis, _vp_neutral_stock())
    assert observation["synergy"]["signalTier"] == "B"  # rank A/buy + res A/buy → v=1.5
    analysis_no_res = _sample_analysis()
    analysis_no_res["observation"]["lifecycle"]["signalTier"] = None
    analysis_no_res.pop("resonance")
    observation_no_res = assemble_observation(analysis_no_res, _vp_neutral_stock())
    assert observation_no_res["synergy"]["signalTier"] == "C"  # 仅 rank A/buy=0.75 → C


def test_assemble_observation_config_vote_thresholds() -> None:
    """config 阈值参与组装：strong=3 时 rank A + res A = v=2.0 < strong → B（门槛上调语义）。"""
    analysis = _sample_analysis()  # res A/buy(1.0) + rank A/buy(1.0) → v=2.0
    config = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 3, "tierSynergyVoteWeak": 1})
    observation = assemble_observation(analysis, _vp_neutral_stock(), config)
    assert observation["synergy"]["signalTier"] == "B"


def _make_replay_frames() -> list[dict]:
    """多股合成帧：让 replay 至少产出信号并带 synergy 组装。"""
    stocks_by_change = {
        "000001": 3.5,  # buy 向
        "000002": -2.5,  # sell 向
        "000003": 0.2,
    }
    frames = []
    for i in range(10):
        stocks = []
        for idx, (code, change) in enumerate(stocks_by_change.items()):
            stocks.append(
                {
                    "code": code,
                    "name": f"股{idx}",
                    "rank": max(1, 20 - i - idx),
                    "avgRankNum": max(1, 20 - i - idx),
                    "change": change,
                    "volumeRatio": 1.8 if change > 0 else 0.7,
                    "zlje": 1200 if change > 0 else -800,
                    "zljzb": 5.0 if change > 0 else -4.0,
                }
            )
        frames.append(
            {
                "snapshotId": f"s{i}",
                "type": "half_hour",
                "timestamp": i,
                "tradingDate": "2026-06-05",
                "slotTime": "10:00",
                "marketContext": {
                    "payload": {
                        "sentiment": {"phaseName": "发酵期"},
                        "marketData": {"ztCount": 10, "dtCount": 1, "upCount": 500, "downCount": 100},
                    }
                },
                "stocks": stocks,
            }
        )
    return frames


def test_replay_signal_contains_synergy_tier() -> None:
    """回测 replay 信号含 observation.volumePrice / observation.synergy.signalTier（§3.2 下沉后）。"""
    engine = RankTrendPythonEngine(RankTrendConfig())
    signals = engine.replay(_make_replay_frames(), meta={"sampleQuality": "ok", "warnings": []})
    assert signals
    for signal in signals:
        observation = (signal.get("rankTrend") or {}).get("observation") or {}
        assert "volumePrice" in observation
        assert "synergy" in observation
        assert observation["synergy"].get("signalTier") in (
            "S", "A", "B", "C", "D", "E", "unknown", None,
        )
        assert observation["volumePrice"].get("signalTier") is not None
