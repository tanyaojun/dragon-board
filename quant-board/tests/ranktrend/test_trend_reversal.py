"""趋势反转判定测试（阶段 6 趋势反转层）。

验证 trend_reversal_of：
1. 低位 + 此前下行 + 当前回升 → 判定反转；
2. 高位（非低位）→ 不判定（高位反转是 reversal stage 语义，不重复）；
3. 此前未下行 → 不判定；
4. 当前未回升 → 不判定；
5. 缺数据（历史帧不足/缺行/无效 rank）→ fail-visible 不伪造。
"""

from __future__ import annotations

from backend.analysis.ranktrend.signal_return_gap import _build_lookup
from backend.analysis.ranktrend.trend_reversal import tier_shift_reversal_of, trend_reversal_of


def _frames(frame_count: int = 8) -> list[dict]:
    frames: list[dict] = []
    for i in range(frame_count):
        # rank 1-based；第 idx 只股票 percentile = (total-rank+1)/total*100
        rows = [{"code": f"{idx:06d}", "rank": idx + 1, "price": 10.0} for idx in range(10)]
        frames.append({"snapshotId": f"s{i}", "stocks": rows})
    return frames


def _signal(snapshot_id: str, code: str, velocity: float) -> dict:
    return {
        "snapshotId": snapshot_id,
        "code": code,
        "rankTrend": {"cycle": {"metrics": {"rankVelocity": velocity, "rankAcceleration": velocity}}},
    }


def _rank_frame(frames: list[dict], frame_index: int, code_to_rank: dict[str, int]) -> None:
    """改写指定帧的 rank（维持 10 只股票）。"""
    frames[frame_index]["stocks"] = [
        {"code": code, "rank": rank, "price": 10.0} for code, rank in code_to_rank.items()
    ]


def test_trend_reversal_detected() -> None:
    """低位 + 此前下行 + 当前回升 → 判定反转（confidence=1.0）。"""
    frames = _frames()
    # 000005 处于低位（rank=6 → pct=50）；s0-s6 下行，s7 回升
    _rank_frame(frames, 0, {f"{i:06d}": 1 for i in range(10)})
    _rank_frame(frames, 3, {f"{i:06d}": (5 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 6, {f"{i:06d}": (8 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 7, {f"{i:06d}": (6 if i == 5 else i + 1) for i in range(10)})
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    signal = _signal("s7", "000005", velocity=2.0)
    result = trend_reversal_of(signal, index_by_snapshot, stock_by_frame_code)
    assert result["isReversal"] is True
    assert result["confidence"] == 1.0


def test_high_position_not_reversal() -> None:
    """当前分位高（rank=1 → pct=100）→ 不判定（高位是 reversal stage 语义，不重复）。"""
    frames = _frames()
    _rank_frame(frames, 0, {f"{i:06d}": 1 for i in range(10)})
    _rank_frame(frames, 3, {f"{i:06d}": 1 for i in range(10)})
    _rank_frame(frames, 6, {f"{i:06d}": (3 if i == 0 else i + 1) for i in range(10)})
    _rank_frame(frames, 7, {f"{i:06d}": (1 if i == 0 else i + 1) for i in range(10)})
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    signal = _signal("s7", "000000", velocity=2.0)  # 高位 rank=1
    result = trend_reversal_of(signal, index_by_snapshot, stock_by_frame_code)
    assert result["isReversal"] is False
    assert any("低位区" in reason for reason in result["reasons"])


def test_no_prior_downtrend_not_reversal() -> None:
    """此前未下行（持续上涨）→ 不判定。"""
    frames = _frames()
    _rank_frame(frames, 0, {f"{i:06d}": (8 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 3, {f"{i:06d}": (7 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 6, {f"{i:06d}": (6 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 7, {f"{i:06d}": (5 if i == 5 else i + 1) for i in range(10)})
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    signal = _signal("s7", "000005", velocity=2.0)
    result = trend_reversal_of(signal, index_by_snapshot, stock_by_frame_code)
    assert result["isReversal"] is False
    assert any("此前下行未确认" in reason for reason in result["reasons"])


def test_no_current_rebound_not_reversal() -> None:
    """当前未回升（velocity<=0）→ 不判定。"""
    frames = _frames()
    _rank_frame(frames, 0, {f"{i:06d}": 1 for i in range(10)})
    _rank_frame(frames, 3, {f"{i:06d}": (5 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 6, {f"{i:06d}": (8 if i == 5 else i + 1) for i in range(10)})
    _rank_frame(frames, 7, {f"{i:06d}": (8 if i == 5 else i + 1) for i in range(10)})
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    signal = _signal("s7", "000005", velocity=0.0)
    result = trend_reversal_of(signal, index_by_snapshot, stock_by_frame_code)
    assert result["isReversal"] is False
    assert any("未回升" in reason for reason in result["reasons"])


def test_missing_history_fail_visible() -> None:
    """历史帧不足 → 不判定且 reasons 说明（fail-visible，不伪造）。"""
    frames = _frames()
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    signal = _signal("s0", "000005", velocity=1.0)  # 首帧无历史
    result = trend_reversal_of(signal, index_by_snapshot, stock_by_frame_code)
    assert result["isReversal"] is False
    assert any("历史帧不足" in reason for reason in result["reasons"])


def test_missing_lookup_fail_visible() -> None:
    """缺帧索引/查找表 → 不判定且 reasons 说明。"""
    signal = _signal("s0", "000005", velocity=1.0)
    result = trend_reversal_of(signal, None, None)
    assert result["isReversal"] is False
    assert any("帧索引" in reason for reason in result["reasons"])


def test_tier_shift_reversal_d_to_b_ignition() -> None:
    """D_EXIT_RISK → B_IGNITION：档位转向判定为 True（用户立项核心场景）。"""
    result = tier_shift_reversal_of({"candidateTier": "B_IGNITION"}, "D_EXIT_RISK")
    assert result["isReversal"] is True
    assert result["confidence"] == 1.0
    assert result["currentTier"] == "B_IGNITION"
    assert result["prevTier"] == "D_EXIT_RISK"


def test_tier_shift_reversal_d_to_a_main() -> None:
    """D_EXIT_RISK → A_MAIN：扩散买档也属跃迁目标。"""
    result = tier_shift_reversal_of({"candidateTier": "A_MAIN"}, "D_EXIT_RISK")
    assert result["isReversal"] is True


def test_tier_shift_reversal_stays_in_d() -> None:
    """D_EXIT_RISK → D_EXIT_RISK：仍在风险档，不算跃迁。"""
    result = tier_shift_reversal_of({"candidateTier": "D_EXIT_RISK"}, "D_EXIT_RISK")
    assert result["isReversal"] is False
    assert len(result["reasons"]) >= 1


def test_tier_shift_reversal_not_from_risk_tier() -> None:
    """非风险档（N_NEUTRAL → B_IGNITION）不算档位转向。"""
    result = tier_shift_reversal_of({"candidateTier": "B_IGNITION"}, "N_NEUTRAL")
    assert result["isReversal"] is False


def test_tier_shift_reversal_to_crowded_excluded() -> None:
    """D_EXIT_RISK → C_CROWDED：拥挤档为高位偏卖语义，不纳入跃迁。"""
    result = tier_shift_reversal_of({"candidateTier": "C_CROWDED"}, "D_EXIT_RISK")
    assert result["isReversal"] is False


def test_tier_shift_reversal_missing_prev_fail_visible() -> None:
    """缺前一帧档位 → False + reasons 说明（不伪造）。"""
    result = tier_shift_reversal_of({"candidateTier": "B_IGNITION"}, None)
    assert result["isReversal"] is False
    assert any("前一帧" in r for r in result["reasons"])


def test_tier_shift_reversal_same_signal_consumable() -> None:
    """输出与 trend_reversal_of 同构：isReversal/confidence 可被 trend_reversal_jump 消费。"""
    result = tier_shift_reversal_of({"candidateTier": "B_IGNITION"}, "D_EXIT_RISK")
    assert set(("isReversal", "confidence")) <= set(result.keys())
