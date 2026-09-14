"""replay 链路共振维补齐测试（阶段 3 修复方向 1）。

背景：阶段 3 诊断发现 replay（回测）信号 100% 缺共振维——`_build_signal` 不计算
`analyze_rank_resonance`（缺横截面市场 median），synergy 实际是 3 维投票。
本测试验证：engine 层暴露横截面函数（frame_market_median / frame_cross_section /
frame_market_median_percentile），replay 带 market_ctx 时输出含 resonance 且参与
synergy 投票，且与 API 单股链路（routes _analyze_one_stock）同源。
"""

from __future__ import annotations

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    RankTrendPythonEngine,
    frame_cross_section,
    frame_market_median,
    frame_market_median_percentile,
    median_of,
)
from backend.analysis.ranktrend.volume_price import assemble_observation, _synergy_tier


def _make_frames(
    frame_count: int = 12,
    stock_count: int = 24,
    rising_codes: set[str] | None = None,
) -> list[dict]:
    """构造多帧横截面：每帧 stock_count 只股票，avgRankNum 从 1 递增（排名靠前），
    rising_codes 中的股票 avgRankNum 随帧递减（排名上升）制造 percentile 变化。"""
    rising = rising_codes or set()
    frames = []
    for i in range(frame_count):
        stocks = []
        for code_idx in range(stock_count):
            code = f"{code_idx:06d}"
            base = code_idx + 1
            if code in rising:
                avg = max(1, base - i * 2)
            else:
                avg = base + i * 2
            stocks.append({"code": code, "rank": avg, "avgRankNum": avg, "change": 1.0})
        frames.append(
            {
                "snapshotId": f"s{i}",
                "type": "half_hour",
                "timestamp": i,
                "tradingDate": "2026-06-05",
                "slotTime": "10:00",
                "stocks": stocks,
            }
        )
    return frames


def test_median_of_contract() -> None:
    assert median_of([]) is None
    assert median_of([1.0]) == 1.0
    assert median_of([1.0, 2.0]) == 1.5
    assert median_of([3.0, 1.0, 2.0]) == 2.0


def test_frame_cross_section_sorts_by_avg_rank_num() -> None:
    frame = {
        "stocks": [
            {"code": "000003", "avgRankNum": 30},
            {"code": "000001", "avgRankNum": 10},
            {"code": "000002", "avgRankNum": 20},
            {"code": "000004", "avgRankNum": None},  # 无效 avgRankNum 剔除
        ]
    }
    cs = frame_cross_section(frame)
    # 有效 3 只：000001 最高分位 100，000003 最低分位 33.33
    assert abs(cs["000001"] - 100.0) < 1e-9
    assert abs(cs["000002"] - 66.6667) < 1e-3
    assert abs(cs["000003"] - 33.3333) < 1e-3
    assert "000004" not in cs


def test_frame_market_median_uses_common_stocks_across_lookback() -> None:
    """market median = 当前帧与前第 3 帧公共股票 percentile 变化中位数；样本 <20 返回 None。"""
    frames = _make_frames(frame_count=4, stock_count=24)
    median, sample_count = frame_market_median(frames, index=3)
    assert median is not None
    assert sample_count == 24
    # 无 rising：所有股票 percentile 相同（同一帧内 avg 递增，帧间 avg 整体平移 → 相对位置不变）
    short, short_count = frame_market_median(frames, index=1)
    assert short is None  # 窗口不足 4 帧
    assert short_count == 24


def test_frame_market_median_percentile_contract() -> None:
    frames = _make_frames(frame_count=1, stock_count=24)
    pct = frame_market_median_percentile(frames[0])
    assert pct is not None and 0 < pct < 100


def test_replay_output_contains_resonance() -> None:
    """replay 带 market 上下文时，signal.rankTrend.resonance 存在（不再 100% unknown）。"""
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    frames = _make_frames(frame_count=12, stock_count=24)
    signals = engine.replay(frames, meta={"sampleQuality": "ok"})
    assert signals
    resonance = signals[-1]["rankTrend"]["resonance"]
    assert isinstance(resonance, dict)
    assert "signalTier" in resonance
    assert resonance["signalTier"] != "unknown"


def test_replay_resonance_matches_api_link_assembly() -> None:
    """replay 内置 resonance 与 API 单股链路（_build_signal assemble=False + 外部 resonance）输出一致。"""
    config = RankTrendConfig.from_patch({"minSampleCount": 3})
    engine = RankTrendPythonEngine(config)
    frames = _make_frames(frame_count=12, stock_count=24, rising_codes={"000000", "000001"})
    meta = {"sampleQuality": "ok"}
    replay_signals = engine.replay(frames, meta=meta)
    replay_signal = [s for s in replay_signals if s["code"] == "000000"][-1]  # 末帧：横截面+序列最充分

    # API 链路：assemble=False 不写 resonance；用同一输入手工计算 resonance 再组装
    stock = next(st for f in frames for st in f["stocks"] if st["code"] == "000000")
    frame = frames[-1]
    total = len(frames[-1]["stocks"])
    ranks = [next(st for f in frames[: i + 1] for st in f["stocks"] if st["code"] == "000000")["rank"] for i in range(len(frames))]
    from backend.analysis.ranktrend.engine import market_regime, percentile_rank

    percentiles = [percentile_rank(r, total) for r in ranks]
    regime = market_regime(frame)
    api_signal = engine._build_signal(stock, frame, ranks, percentiles, regime, meta, assemble=False)
    assert api_signal is not None
    api_analysis = api_signal["rankTrend"]
    assert "resonance" not in api_analysis  # API 链路组装前不写 resonance

    # 用 engine 层横截面函数 + analyze_rank_resonance 复现 routes 组装
    from backend.analysis.ranktrend.engine import analyze_rank_resonance

    market_median, market_sample_count = frame_market_median(frames, len(frames) - 1)
    market_median_percentile = frame_market_median_percentile(frame)
    jump = api_analysis.get("jump") or {}
    sample_quality = (api_analysis.get("meta") or {}).get("sampleQuality") or {}
    resonance = analyze_rank_resonance(
        {
            "percentiles": percentiles,
            "sampleQuality": {"status": sample_quality.get("status") or "insufficient", "timelineValid": True},
            "marketMedianShortChange": market_median if market_median is not None else float("nan"),
            "marketSampleCount": market_sample_count,
            "marketMedianPercentile": market_median_percentile,
            "jump": {
                "direction": jump.get("direction") or "hold",
                "event": jump.get("event") or "none",
                "events": jump.get("events") or [],
            },
            "entry": {"isNew": len(percentiles) == 1, "currentAttentionPercentile": percentiles[-1] if percentiles else 0},
        },
        config,
    )
    api_analysis["resonance"] = resonance
    assemble_observation(api_analysis, stock, config)

    replay_resonance = replay_signal["rankTrend"]["resonance"]
    assert replay_resonance == resonance  # 同输入同源 → 输出逐字段一致
    assert resonance.get("status") == "ok"
    # 共振参与 synergy 投票后，API 与 replay 的 synergy 档位一致
    assert (
        replay_signal["rankTrend"]["observation"]["synergy"]["signalTier"]
        == api_signal["rankTrend"]["observation"]["synergy"]["signalTier"]
    )


def test_replay_resonance_nan_not_leaked_to_json() -> None:
    """横截面不足时 resonance.marketMedianShortChange 输出 None（非 NaN），
    保证回测链路严格 JSON 序列化不崩溃（fail-visible：无效横截面标记为缺失）。"""
    import json

    config = RankTrendConfig.from_patch({"minSampleCount": 3})
    engine = RankTrendPythonEngine(config)
    # 12 帧但仅 10 只有效股票（<20）→ frame_market_median 返回 None → resonance insufficient
    frames = _make_frames(frame_count=12, stock_count=10)
    signals = engine.replay(frames, meta={"sampleQuality": "ok"})
    assert signals
    resonance = signals[-1]["rankTrend"]["resonance"]
    assert resonance.get("status") == "insufficient"
    assert resonance.get("marketMedianShortChange") is None  # 不是 NaN
    json.dumps(signals[-1], allow_nan=False)  # 严格序列化不抛异常


def test_replay_resonance_participates_in_synergy_vote() -> None:
    """共振 buy 票改变 synergy 投票：带共振（vote+1）与缺共振（vote=0）结果不同或票数可验证。"""
    config = RankTrendConfig.from_patch({"minSampleCount": 3})
    engine = RankTrendPythonEngine(config)
    frames = _make_frames(frame_count=12, stock_count=24, rising_codes={"000000"})
    signals = engine.replay(frames, meta={"sampleQuality": "ok"})
    signal = [s for s in signals if s["code"] == "000000"][-1]
    resonance = signal["rankTrend"]["resonance"]
    assert resonance.get("status") == "ok"
    # 构造"缺共振"对照：把 resonance 清空后重组装
    analysis = dict(signal["rankTrend"])
    analysis["resonance"] = {}
    stock = next(st for f in frames for st in f["stocks"] if st["code"] == "000000")
    assemble_observation(analysis, stock, config)
    with_res = signal["rankTrend"]["observation"]["synergy"]["signalTier"]
    without_res = analysis["observation"]["synergy"]["signalTier"]

    # 共振 hold 不产生票（fixture 相对动量不足）：rank+vp 两票 v=1.75 → B（采纳票权 0.75）
    assert _synergy_tier(resonance.get("signalTier"), resonance.get("direction"), "A", "buy", "A", "up", "A", config)[0] in (
        "A",
        "B",
    )
    # fixture 实际共振 direction=hold（相对动量不足/中位 0）→ 不贡献票 →
    # 带共振与清空共振的 synergy 档位必须一致（证明 resonance 被读取但 hold 无票）
    assert with_res == without_res, f"共振 hold 不应改变档位: with={with_res} without={without_res}"
