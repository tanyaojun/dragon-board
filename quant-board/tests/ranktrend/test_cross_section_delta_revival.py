# -*- coding: utf-8 -*-
"""crossSection percentileDelta 复活（2026-09-13，A/D 档数学不可达修复）。

背景（2026-09-13 排查，snapshot_analysis 240,521 条实证）：
- 全库 ``crossSection.percentileDelta`` 恒 0（220,045 条非空值 max=min=avg=0.0）→
  A 档（delta>=5）与 D 档（delta<=-5）自 2026-08-17 因子上线以来从未出现（A=0/D=0），
  依赖 delta 的 B/C 分支（"中位之上+热度显著上升"/"热度排名显著下降"）同样零命中。
- 根因 1（入库链路）：``compute_snapshot_analysis`` 把 current_frame（= 刚入库的
  最后一帧）再传给 ``_load_frames_for_analysis`` → 同帧重复 append + series 复制尾
  → 序列末两项恒相等 → delta 恒 0。
- 根因 2（live 链路）：990c69d8（2026-08-23 修复 A）当前帧复用 bars[-1] 权威 pct
  防漂移——复制尾把 crossSection 的 delta 一并清零（level 展示稳定目标保留）。

修复语义（golden 算法 ``compute_cross_section`` 不动，只修数据供给）：
- 入库链路：current_frame 与 bundles 最后一帧同 key 时整段跳过（不重复 append 帧、
  不复制 series）→ 序列以真实权威帧结束，delta = 真实跨帧变化，A/D 恢复可达。
- live 链路：crossSection 输入去掉复制尾——level 仍 = 权威 pct（展示稳定），
  delta = 上一权威帧 vs 上上权威帧（滞后一个快照周期的真实变化）；technical/cycle/
  趋势/共振等其它因子输入不变（golden 不漂移）。

测试数据：10 只股票（600000 目标 + 陪跑 avgRankNum=1..9）。
percentile_rank = ((total-rank+1)/total)*100，total=10：
- F1 avgRankNum=15 → rank=10 → pct=10.0
- F2 avgRankNum=3.5 → rank=4  → pct=70.0
- F3 avgRankNum=0.5 → rank=1  → pct=100.0
F3 vs F2 delta=30（≥5）且 level=100（≥85）→ 修复后 A 档可达。
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.analysis.ranktrend.engine import RankTrendPythonEngine
from backend.api.ranktrend_routes import (
    _analyze_frames,
    _analyze_one_stock,
    _load_frames_for_analysis,
)


def _stock(code: str, avg_rank_num: float) -> dict[str, Any]:
    return {
        "code": code,
        "name": f"股{code}",
        "avgRankNum": avg_rank_num,
        "rank": 1,
        "change": 2.0,
        "volumeRatio": 1.5,
        "zlje": 1200.0,
        "zljzb": 1.2,
        "amount": 5000.0,
        "price": 10.0,
        "turnover": 80000.0,
    }


def _stocks(avg: float) -> list[dict[str, Any]]:
    return [_stock("600000", avg)] + [_stock(f"60000{i}", float(i)) for i in range(1, 10)]


def _bundle(date: str, avg: float, ts: int) -> dict[str, Any]:
    return {
        "tradingDate": date,
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": ts,
        "rows": _stocks(avg),
        "hotThemes": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }


def _make_bundles() -> list[dict[str, Any]]:
    """F1(pct=10) → F2(pct=70) → F3(pct=100)，600000 热度分位真实上升 delta=30。"""
    return [
        _bundle("2026-08-12", 15.0, 1),
        _bundle("2026-08-13", 3.5, 2),
        _bundle("2026-08-14", 0.5, 3),
    ]


class FakeRepo:
    def __init__(self, frames: list[dict[str, Any]]):
        self.frames = frames

    def load_frame_bundles(self, *args: Any, **kwargs: Any):
        out = list(self.frames)
        if kwargs.get("sort") == "desc":
            out.sort(key=lambda f: int(f.get("timestamp") or 0), reverse=True)
            limit = kwargs.get("limit")
            if limit and limit > 0:
                out = out[:limit]
        return out


def _snapshot_current_frame() -> dict[str, Any]:
    """入库链路的 current_frame：与最后一帧 bundle 同帧（compute_snapshot_analysis 场景）。"""
    return {
        "tradingDate": "2026-08-14",
        "slotTime": "14:00",
        "type": "half_hour",
        "stocks": _stocks(0.5),
    }


def _live_current_frame() -> dict[str, Any]:
    """live 链路的 current_frame：前端实时帧（slotTime=current:N，avgRankNum 漂移值）。"""
    return {
        "tradingDate": "2026-08-14",
        "slotTime": "current:1",
        "stocks": [_stock("600000", 50.0)] + [_stock(f"60000{i}", float(i)) for i in range(1, 10)],
    }


def _load(bundles: list[dict[str, Any]], current_frame: dict[str, Any] | None):
    return _load_frames_for_analysis(
        FakeRepo(bundles), "dragonboard_live", "half_hour", [], current_frame=current_frame, codes=None
    )


def _analyze(frames, series):
    output = _analyze_frames(RankTrendPythonEngine(), frames, series, [])
    assert output, "analyze 无输出"
    return output[-1]


def _cs_of(last_frame: dict[str, Any], code: str = "600000") -> dict[str, Any]:
    stock = next((s for s in last_frame["stocks"] if s.get("code") == code), None)
    assert stock is not None, "目标股缺失"
    analysis = stock.get("analysis") or {}
    return (analysis.get("observation") or {}).get("crossSection") or {}


# ---------------------------------------------------------------------------
# 入库链路：current_frame 与 bundles 最后一帧同 key → 不重复 append，delta 真实
# ---------------------------------------------------------------------------


def test_snapshot_chain_skips_duplicate_current_frame() -> None:
    frames, series = _load(_make_bundles(), _snapshot_current_frame())

    keys = [f"{fr.get('tradingDate')} {fr.get('slotTime')}".strip() for fr in frames]
    assert keys.count("2026-08-14 14:00") == 1, f"同帧重复 append：{keys}"
    bars = series["600000"]
    bar_keys = [b[0] for b in bars]
    assert len(set(bar_keys)) == len(bar_keys), f"series 存在重复帧：{bar_keys}"
    assert bar_keys[-1] == "2026-08-14 14:00"
    assert bars[-1][2] == pytest.approx(100.0)


def test_snapshot_chain_cross_section_delta_real_and_tier_a_reachable() -> None:
    """修复前：同帧复制尾 → delta=0 → 恒 B 档（横截面高位）；修复后 delta=30 → A 档可达。"""
    frames, series = _load(_make_bundles(), _snapshot_current_frame())

    last = _analyze(frames, series)

    assert last["frameKey"] == "2026-08-14 14:00"
    cs = _cs_of(last)
    assert cs.get("percentile") == pytest.approx(100.0)
    assert cs.get("percentileDelta") == pytest.approx(30.0), (
        f"入库链路 delta 应为真实跨帧变化 30（F3 100 - F2 70），实际 {cs.get('percentileDelta')}"
    )
    assert cs.get("signalTier") == "A", f"高位+上升确认应产出 A 档，实际 {cs.get('signalTier')}"


def test_snapshot_chain_last_frame_keeps_ingest_stock_fields() -> None:
    """同帧跳过时，最后一帧的股票行必须保留 ingest 原始行字段。

    bundle 读侧走 ranktrend+themes 白名单投影（code/name/rank/avgRankNum/change/
    volumeRatio/zlje/zljzb + themes 五字段），amount/price/turnover/OHLC 全部丢失——
    若直接用投影行 analyze，amountRatio/ATR 会降级 insufficient、displayStatus tooltip
    的价格/成交额回退。同帧语义 = 权威序列 + ingest 原始行（与修复前 output[-1] 一致）。
    """
    bundles = _make_bundles()
    whitelist = {
        "code", "name", "rank", "avgRankNum", "change", "volumeRatio", "zlje", "zljzb",
    }
    # 模拟读侧白名单投影行（丢 amount/price/turnover）
    bundles[-1] = {
        **bundles[-1],
        "rows": [
            {key: row[key] for key in whitelist if key in row}
            for row in bundles[-1]["rows"]
        ],
    }
    current = _snapshot_current_frame()
    frames, _series = _load(bundles, current)

    assert frames[-1]["tradingDate"] == "2026-08-14"
    last_rows = frames[-1]["stocks"]
    sample = next(r for r in last_rows if r.get("code") == "600000")
    assert sample.get("amount") == 5000.0, (
        f"最后一帧行应保留 ingest 原始字段 amount，实际 keys={sorted(sample.keys())}"
    )
    assert sample.get("turnover") == 80000.0
    assert sample.get("price") == 10.0


# ---------------------------------------------------------------------------
# live 链路：复制尾保留（防漂移），但 crossSection 输入去尾 → delta 滞后一拍真实值
# ---------------------------------------------------------------------------


def test_live_chain_strips_copied_tail_for_cross_section() -> None:
    bundles = _make_bundles()
    frames, series = _load(bundles, _live_current_frame())

    # 复制 append 机制保留（防漂移）：series 末两项 pct 相等、key 不同
    bars = series["600000"]
    assert bars[-1][0].endswith("current:1")
    assert bars[-1][2] == pytest.approx(bars[-2][2]) == pytest.approx(100.0)
    assert bars[-1][0] != bars[-2][0]

    last = _analyze(frames, series)

    assert str(last["frameKey"]).endswith("current:1")
    cs = _cs_of(last)
    # level 不变：仍为权威 pct=100（修复 A 的展示稳定目标保住）
    assert cs.get("percentile") == pytest.approx(100.0)
    # delta 去复制尾：= 上一权威帧 vs 上上权威帧（F3 100 - F2 70 = 30），不再恒 0
    assert cs.get("percentileDelta") == pytest.approx(30.0), (
        f"live 链路 delta 应去复制尾取权威帧差 30，实际 {cs.get('percentileDelta')}"
    )
    assert cs.get("signalTier") == "A"


def test_live_chain_other_factors_keep_full_prefix() -> None:
    """golden 护栏：去尾只影响 crossSection——meta.currentPercentile 与 technical 输入
    仍用完整 prefix（含复制尾），与 2026-08-23 修复 A 行为一致。"""
    frames, series = _load(_make_bundles(), _live_current_frame())

    last = _analyze(frames, series)

    stock = next(s for s in last["stocks"] if s.get("code") == "600000")
    analysis = stock.get("analysis") or {}
    meta = analysis.get("meta") or {}
    assert meta.get("currentPercentile") == pytest.approx(100.0), (
        "currentPercentile 应保持权威值（复制尾不被移除，其它因子输入不变）"
    )
    observation = analysis.get("observation") or {}
    # technical 与 observation 的 crossSection 同源同构（两处挂载一致）
    technical = analysis.get("technical") or {}
    assert technical.get("crossSection") == observation.get("crossSection")


# ---------------------------------------------------------------------------
# D 档对称可达（低位 + 下降确认）：修复前与 A 档同样恒不可达
# ---------------------------------------------------------------------------


def test_snapshot_chain_tier_d_reachable_on_declining_heat() -> None:
    """D 档 = percentile<=15 且 delta<=-5。600000 热度 100→20→10：
    F3 vs F2 delta=-10 且 pct=10 → D 档（修复前 delta 恒 0 时永远不可达）。"""
    bundles = [
        _bundle("2026-08-12", 0.5, 1),   # rank=1  → pct=100
        _bundle("2026-08-13", 8.5, 2),   # rank=9  → pct=20
        _bundle("2026-08-14", 9.5, 3),   # rank=10 → pct=10
    ]
    current = {
        "tradingDate": "2026-08-14",
        "slotTime": "14:00",
        "type": "half_hour",
        "stocks": _stocks(9.5),
    }
    frames, series = _load(bundles, current)

    last = _analyze(frames, series)

    cs = _cs_of(last)
    assert cs.get("percentile") == pytest.approx(10.0)
    assert cs.get("percentileDelta") == pytest.approx(-10.0), (
        f"低位下降场景 delta 应为 -10，实际 {cs.get('percentileDelta')}"
    )
    assert cs.get("signalTier") == "D", f"低位+下降确认应产出 D 档，实际 {cs.get('signalTier')}"


# ---------------------------------------------------------------------------
# live 链路新进热榜：单点序列不参与去尾（首帧缺 delta 走绝对档降级，不变 unknown）
# ---------------------------------------------------------------------------


def test_live_chain_new_stock_single_point_not_stripped() -> None:
    """历史无记录的新股走单点注册（len==1），去尾条件 len>=2 不命中——
    crossSection 用原序列 → delta=None（首帧缺确认）→ 高位绝对档 B 降级，
    而不是被错误去尾后变 unknown（横截面数据不足）。"""
    bundles = [
        _bundle("2026-08-12", 5.0, 1),   # 陪跑池：600000 不在其中
        _bundle("2026-08-13", 5.0, 2),
        _bundle("2026-08-14", 5.0, 3),
    ]
    for bundle in bundles:
        bundle["rows"] = [_stock(f"60000{i}", float(i)) for i in range(1, 10)]
    current = {
        "tradingDate": "2026-08-14",
        "slotTime": "current:1",
        "stocks": [_stock("300999", 0.5)] + [_stock(f"60000{i}", float(i)) for i in range(1, 10)],
    }
    frames, series = _load(bundles, current)

    # 新股单点注册：series 里只有 1 个 bar（current_key 本身）
    bars = series["300999"]
    assert len(bars) == 1 and bars[0][0].endswith("current:1")

    last = _analyze(frames, series)

    cs = _cs_of(last, code="300999")
    assert cs.get("percentile") == pytest.approx(100.0)
    assert cs.get("percentileDelta") is None, (
        f"单点序列（首帧）delta 应为 None（缺历史确认），实际 {cs.get('percentileDelta')}"
    )
    assert cs.get("signalTier") == "B", (
        f"高位首帧应降级 B（缺 delta 确认），实际 {cs.get('signalTier')}"
    )
    assert any("首帧" in reason or "缺 delta" in reason for reason in cs.get("tierReasons") or [])


# ---------------------------------------------------------------------------
# golden 护栏：不显式传 crossSection 输入的路径（replay/backtest/单股合同）行为不变
# ---------------------------------------------------------------------------


def _one_stock_args(percentiles: list[float]) -> tuple[Any, ...]:
    """replay/backtest/单股合同：task tuple 只有原 4 个 history_args（无 crossSection 入参）。"""
    from backend.analysis.ranktrend.engine import RankTrendConfig, market_regime

    stock = _stock("000001", 3.0)
    frame = {"snapshotId": "s1", "type": "half_hour", "tradingDate": "2026-08-14", "slotTime": "14:00"}
    ranks = list(range(len(percentiles), 0, -1))
    return (
        RankTrendConfig(), stock, frame, ranks, percentiles, market_regime(frame), [],
        {"version": "t", "frames": [], "themes": {}},
        None, 0, None,
        [2.0] * len(percentiles), [1000.0] * len(percentiles), [None] * len(percentiles),
    )


def test_one_stock_contract_without_cs_input_keeps_legacy_delta() -> None:
    """task tuple 不带 crossSection 入参（旧合同）→ 用完整 percentiles，delta=末两项差。

    锁定"不传新参数 = 现行为"：replay/backtest/research 链路 golden 不漂移。
    含重复尾的序列（末两项相等）→ delta=0，与修复前一致。"""
    result = _analyze_one_stock(_one_stock_args([10.0, 70.0, 100.0, 100.0]))
    assert result is not None
    analysis = result.get("analysis") or {}
    cs = (analysis.get("observation") or {}).get("crossSection") or {}
    assert cs.get("percentile") == pytest.approx(100.0)
    assert cs.get("percentileDelta") == pytest.approx(0.0), (
        "不显式传 crossSection 入参时应保持现行为（完整序列 delta=末两项差）"
    )
    assert cs.get("signalTier") == "B"


def test_one_stock_contract_cs_input_overrides_delta_only() -> None:
    """显式传 crossSection 输入（去复制尾序列）→ level 取输入末项、delta 取末两项差。

    live 链路修复的落点契约：cross_section_percentiles 与 percentiles 并行供给，
    互不污染。"""
    args = list(_one_stock_args([10.0, 70.0, 100.0, 100.0]))
    args.append(None)  # history_args[3]: gate_confirm_state（None → 直通 = 现行为）
    args.append([10.0, 70.0, 100.0])  # history_args[4]: 去复制尾，delta = 100 - 70 = 30
    result = _analyze_one_stock(tuple(args))
    assert result is not None
    analysis = result.get("analysis") or {}
    cs = (analysis.get("observation") or {}).get("crossSection") or {}
    assert cs.get("percentile") == pytest.approx(100.0)
    assert cs.get("percentileDelta") == pytest.approx(30.0), (
        f"显式去尾入参应产出 delta=30，实际 {cs.get('percentileDelta')}"
    )
    assert cs.get("signalTier") == "A"
