from __future__ import annotations

from backend.analysis.ranktrend.volume_price import (
    compute_synergy_state,
    compute_volume_price_score,
)
from backend.api.ranktrend_routes import _apply_resonance_final


def _vp(code: str = "600001", chg: float = 9.97, vr: float = 0.75, zlje: float = 1e6, zljzb: float = 1.0):
    return compute_volume_price_score(code, chg, vr, zlje, zljzb)


def test_shrink_limit_up_not_tradeable() -> None:
    # 缩量涨停（主板）：封板买不进，可交易性压低 → 非顶格分、降出 S 强档
    r = _vp("600001", 9.97, 0.75)
    assert r["score"] == 76  # 50 + 15 + 8 + 3（旧口径 +25 → 93）
    assert r["quadrant"] == "rise_shrink"
    assert "缩量涨停（封板不可买）" in r["reasons"]
    assert r["signalTier"] == "C"  # 封板不可买，不再归 S 强档


def test_board_limit_up_pct() -> None:
    # 创业板 20% 缩量涨停、北交所 30% 缩量涨停
    cyb = _vp("300001", 19.97, 0.6)
    bj = _vp("830001", 29.9, 0.6)
    assert "缩量涨停（封板不可买）" in cyb["reasons"]
    assert "缩量涨停（封板不可买）" in bj["reasons"]
    # 创业板 12%（未达 20%）不判涨停 → 缩量上涨
    assert "缩量上涨（惜售/无量涨）" in _vp("300001", 12.0, 0.6)["reasons"]


def test_volume_limit_up_keeps_rank() -> None:
    # 放量涨停（有换手，可排单成交）：保持 rise_volume + 资金流入 → A
    r = compute_volume_price_score("600001", 9.97, 1.5, 1e6, 1.0)
    assert r["quadrant"] == "rise_volume"
    assert r["signalTier"] == "A"
    assert r["score"] == 80  # 50 + 15 + 12.5 + 3 → round(80.5) = 80


def test_shrink_limit_down_penalty() -> None:
    # 缩量跌停：封死卖不出，风险加重（对称于涨停不可买）
    r = compute_volume_price_score("600001", -9.97, 0.5, -1e6, -1.0)
    assert r["score"] == 17  # 50 - 15（方向） - 15（缩量跌停加重） - 3
    assert "缩量下跌（无量阴跌）" in r["reasons"]


def test_over_volume_is_selloff() -> None:
    # 过度放量（>2.5）上涨 → 出货惩罚
    r = compute_volume_price_score("600001", 3.0, 3.0, -500000.0, -0.2)
    assert r["score"] == 37  # 50 + 8（3-5%档） - 20 - 0.6
    assert "过度放量上涨（疑似出货）" in r["reasons"]


def test_abnormal_fund_ratio_is_selloff() -> None:
    r = compute_volume_price_score("600001", 3.0, 1.5, 999999.0, 53.83)
    assert r["score"] == 56  # 50 + 8 + 12.5 - 15（对倒惩罚）
    assert "主力净占比异常高（疑似对倒出货）" in r["reasons"]


def test_missing_volume_ratio_returns_none() -> None:
    r = compute_volume_price_score("600001", 3.0, None, 1e6, 1.0)
    assert r["score"] is None
    assert r["reasons"]


def test_direction_five_buckets() -> None:
    """涨跌幅八档：涨停/7%+/5-7%/3-5%/2-3%/1-2%/0.5-1%/0-0.5%/平盘，下跌对称。"""
    # 0-0.5% 档 → +1
    assert compute_volume_price_score("600001", 0.3, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 1.0
    assert compute_volume_price_score("600001", 0.49, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 1.0
    # 0.5-1% 档 → +2
    assert compute_volume_price_score("600001", 0.5, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 2.0
    # 1-2% 档 → +4
    assert compute_volume_price_score("600001", 1.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 4.0
    assert compute_volume_price_score("600001", 1.9, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 4.0
    # 2-3% 档 → +6
    assert compute_volume_price_score("600001", 2.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 6.0
    assert compute_volume_price_score("600001", 2.9, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 6.0
    # 3-5% 档 → +8
    assert compute_volume_price_score("600001", 3.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 8.0
    assert compute_volume_price_score("600001", 4.9, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 8.0
    # 5-7% 档 → +10
    assert compute_volume_price_score("600001", 5.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 10.0
    assert compute_volume_price_score("600001", 6.9, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 10.0
    # 7% 以上（未涨停）→ +12
    assert compute_volume_price_score("600001", 7.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    assert compute_volume_price_score("600001", 9.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    # 主板涨停（9.8）→ +15；主板 9.7（未涨停）→ +12
    assert compute_volume_price_score("600001", 9.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("600001", 9.7, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    # 下跌对称：-0.3% → -1；-2% → -6；-6% → -10；主板跌停（-9.8）→ -15
    assert compute_volume_price_score("600001", -0.3, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -1.0
    assert compute_volume_price_score("600001", -2.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -6.0
    assert compute_volume_price_score("600001", -6.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -10.0
    assert compute_volume_price_score("600001", -9.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -15.0
    # 平盘 → 0
    assert compute_volume_price_score("600001", 0.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 0.0


def test_direction_limit_by_board() -> None:
    """涨跌停按板块区分（主板/创业板/科创板/北交所），不写死单一阈值。"""
    # 创业板 300/301：12%（未达 20%）→ +12；19.8 涨停 → +15
    assert compute_volume_price_score("300001", 12.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    assert compute_volume_price_score("300001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("301001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    # 科创板 688/689：19.8 涨停 → +15；12%（未达 20%）→ +12
    assert compute_volume_price_score("688001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("689001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("688001", 12.0, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    # 北交所 8/4 开头：19.8 未达 30% → +12；29.8 涨停 → +15
    assert compute_volume_price_score("830001", 29.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("830001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    # 交易所前缀兼容：sz300001 创业板、SH600001 主板
    assert compute_volume_price_score("sz300001", 19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("SH600001", 9.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 15.0
    assert compute_volume_price_score("SH600001", 9.7, 1.0, 0.0, 0.0)["breakdown"]["direction"] == 12.0
    # 跌停同样按板块：创业板 -19.8、主板 -9.8
    assert compute_volume_price_score("300001", -19.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -15.0
    assert compute_volume_price_score("300001", -9.8, 1.0, 0.0, 0.0)["breakdown"]["direction"] == -12.0


def test_synergy_states() -> None:
    assert compute_synergy_state("ignition", 80.0, "buy", "buy", 1.0)["state"] == "启动确认"
    assert compute_synergy_state("expansion", 80.0, "buy", "buy", 1.0)["state"] == "主升确认"
    assert compute_synergy_state("crowded", 30.0, "buy", "buy", 1.0)["state"] == "风险升级"
    assert compute_synergy_state("reversal", 60.0, "sell", "sell", 25.0)["state"] == "风险升级"  # 资金对倒
    assert compute_synergy_state("cooling", 30.0, "hold", "hold", 1.0)["state"] == "退潮"
    assert compute_synergy_state("expansion", 30.0, "buy", "buy", 1.0)["state"] == "suspect"  # 量价分低
    assert compute_synergy_state("expansion", None, "buy", "buy", 1.0)["state"] == "noData"
    assert compute_synergy_state("crowded", 30.0, "buy", "buy", 1.0)["hardWarn"] is True


def _analysis_with_vp(vp_score: float | None = 60.0, direction: str = "buy", status: str = "ok") -> dict:
    return {
        "decision": {"base": {"signal": direction}},
        "resonance": {"status": status, "direction": direction, "score": 60.0},
        "observation": {"volumePrice": {"score": vp_score}},
    }


def test_resonance_adjusted_with_vp_score() -> None:
    a = _analysis_with_vp(80.0)  # 60 + (80-50)*0.15 = 64.5
    _apply_resonance_final(a, a["resonance"])
    assert a["resonance"]["rawScore"] == 60.0
    assert a["resonance"]["score"] == 64.5
    assert a["decision"]["final"] == {"signal": "buy", "confidence": 64.5}


def test_resonance_buy_downgraded_when_vp_low() -> None:
    a = _analysis_with_vp(30.0)  # 60 + (30-50)*0.15 = 57；buy + vp≤40 → hold
    _apply_resonance_final(a, a["resonance"])
    assert a["resonance"]["score"] == 57.0
    assert a["decision"]["final"]["signal"] == "hold"


def test_resonance_insufficient_unchanged() -> None:
    a = _analysis_with_vp(80.0, status="insufficient")
    _apply_resonance_final(a, a["resonance"])
    assert a["decision"]["final"] == {"signal": "hold", "confidence": 0}


def test_resonance_without_vp_keeps_raw() -> None:
    a = _analysis_with_vp(None)
    _apply_resonance_final(a, a["resonance"])
    assert a["resonance"]["rawScore"] == 60.0
    assert a["resonance"]["score"] == 60.0

def test_vp_param_config_defaults() -> None:
    """量价参数化默认值 = 原硬编码（golden 不漂移）。"""
    from backend.analysis.ranktrend.engine import RankTrendConfig
    c = RankTrendConfig()
    assert c.volumePriceDirectionBuckets == [15.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 1.0]
    assert c.volumePriceNormalRatio == 2.0
    assert c.volumePriceBase == 50.0
    assert c.volumePriceOverVolumeRatio == 2.5
    assert c.volumePriceAbnormalFundRatio == 20.0
    assert c.volumePriceShrinkRatio == 0.95
    assert c.volumePriceMildRatio == 1.05


def test_vp_direction_buckets_config_effect() -> None:
    """方向八档分值参数化生效：提高 7%+ 档分值 → 对应分数变化。"""
    from backend.analysis.ranktrend.engine import RankTrendConfig
    from backend.analysis.ranktrend.volume_price import _direction_bucket
    c = RankTrendConfig()
    assert _direction_bucket("600001", 8.0, c) == 12.0  # 7%+ 档
    c2 = RankTrendConfig.from_patch({"volumePriceDirectionBuckets": [15.0, 18.0, 10.0, 8.0, 6.0, 4.0, 2.0, 1.0]})
    assert _direction_bucket("600001", 8.0, c2) == 18.0


def test_vp_normal_ratio_config_effect() -> None:
    """量比 2.0 边界参数化生效：volumePriceNormalRatio 提高 → 更大 vr 走"正常放量"分支。"""
    from backend.analysis.ranktrend.engine import RankTrendConfig
    r_default = compute_volume_price_score("600001", 5.0, 2.4, 1e6, 1.0)  # vr=2.4 > 2.0 → 过度放量分支
    c2 = RankTrendConfig.from_patch({"volumePriceNormalRatio": 3.0})
    r_new = compute_volume_price_score("600001", 5.0, 2.4, 1e6, 1.0, c2)  # vr=2.4 <= 3.0 → 正常放量分支
    assert r_default["breakdown"]["volume"] != r_new["breakdown"]["volume"]
