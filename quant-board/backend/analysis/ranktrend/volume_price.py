"""量价评分与四象协同（阶段 2：量能协同轴）。

TS `src/services/rankTrend/volumePriceValidation.ts::computeVolumePriceScore` 的 Python 移植——
口径一致（方向 + 量价交叉 + 资金 + 板块涨停），后端生产 `observation.volumePrice`，前端只消费，
与三轨（resonance/technical/lifecycle）数据链路保持一致。

量价分 0-100：
- 方向（涨跌幅八档，对称）：涨停/跌停（板块阈值）±15；7%+ ±12；5-7% ±10；
  3-5% ±8；2-3% ±6；1-2% ±4；0.5-1% ±2；0-0.5% ±1；平盘 0
- 量价交叉（量比幅度 + 板块涨停语境）：
  缩量涨停（vr≤0.95 且达板块涨停）+25；缩量上涨（非涨停）+10~15；
  温和放量上涨（1.05≤vr≤2）+10~15；放量过大（2<vr≤2.5）渐扣；
  过度放量（vr>2.5）-15~-20（出货风险）；缩量下跌 -10；放量下跌 -20；常态 ±5
- 资金：0<zljzb≤20 → +min(15, zljzb×3)；zljzb>20 → -min(15, 10+(zljzb-20)×0.5)（对倒出货）；
  zljzb<0 → -min(15, |zljzb|×3)；缺失按 zlje 符号 ±5
- score = clamp(round(50 + 方向 + 量价 + 资金), 0, 100)

四象协同状态（observation.synergy）：
- 启动确认：点火/扩散 + 量价分≥75 + 技术 buy + 共振 ↑
- 主升确认：扩散 + 量价分≥75 + 技术 buy + 共振 ↑
- 风险升级：拥挤/反转 + 量价分≤40 或 资金对倒（zljzb>20）
- 退潮：降温 + 量价分≤40
- 存疑：其余（共振↑但量价分低=无量虚涨等）
"""
from __future__ import annotations

import math
from typing import Any

from backend.analysis.ranktrend.engine import RankTrendConfig

_LIMIT_UP_20 = ("300", "301", "688", "689")  # 创业板 / 科创板 20%
_LIMIT_UP_30 = ("8", "4", "9")  # 北交所 30%（9 开头 B 股误判为北交所，热榜池无 B 股，记录待数据源补齐）
# 口径说明：TS 旧版涨停判定复用 resolveLiveLimitState（quote_limit_price 真实涨跌停价优先 + 板块 fallback）；
# 后端帧数据无 quote_limit_price 字段，这里只用板块 fallback——与 TS 在无实时价时的行为等价（热榜池场景）。
_OVER_VOLUME_RATIO = 2.5
_ABNORMAL_FUND_RATIO = 20.0


def _daily_limit_pct(code: Any) -> float:
    value = str(code or "").strip()
    # 兼容交易所前缀（sz300001 / SH600001 / bj830001），归一为纯 6 位代码再判板块
    if len(value) > 6 and value[:2].lower() in ("sz", "sh", "bj"):
        value = value[2:]
    value = value[-6:] if value.isdigit() else value
    if value.startswith(_LIMIT_UP_20):
        return 19.8  # 创业板 / 科创板 20%
    if value.startswith(_LIMIT_UP_30):
        return 29.8  # 北交所 30%
    return 9.8  # 主板 10%


def _is_limit_up(code: Any, change: float | None) -> bool:
    if change is None:
        return False
    return change >= _daily_limit_pct(code)


def _is_limit_down(code: Any, change: float | None) -> bool:
    if change is None:
        return False
    return change <= -_daily_limit_pct(code)


def _direction_bucket(code: Any, chg: float) -> float:
    """涨跌幅八档方向分（对称）：涨停/跌停 ±15、7%+ ±12、5-7% ±10、3-5% ±8、
    2-3% ±6、1-2% ±4、0.5-1% ±2、0-0.5% ±1、平盘 0。"""
    if chg >= _daily_limit_pct(code):
        return 15.0
    if chg <= -_daily_limit_pct(code):
        return -15.0
    magnitude = abs(chg)
    if magnitude >= 7.0:
        return 12.0 if chg > 0 else -12.0
    if magnitude >= 5.0:
        return 10.0 if chg > 0 else -10.0
    if magnitude >= 3.0:
        return 8.0 if chg > 0 else -8.0
    if magnitude >= 2.0:
        return 6.0 if chg > 0 else -6.0
    if magnitude >= 1.0:
        return 4.0 if chg > 0 else -4.0
    if magnitude >= 0.5:
        return 2.0 if chg > 0 else -2.0
    if magnitude > 0:
        return 1.0 if chg > 0 else -1.0
    return 0.0


def _finite(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def compute_volume_price_score(
    code: Any,
    change: Any,
    volume_ratio: Any,
    zlje: Any,
    zljzb: Any,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    """量价评分（0-100）与方向/象限/依据，与 TS computeVolumePriceScore 口径一致。"""
    c = config or RankTrendConfig()
    chg = _finite(change)
    vr = _finite(volume_ratio)
    if chg is None or vr is None or vr <= 0:
        return {
            "score": None,
            "direction": None,
            "quadrant": None,
            "reasons": ["量价数据不足（涨跌/量比缺失），不评估"],
        }

    # 方向（涨跌幅五档）
    direction = "up" if chg > 0 else "down" if chg < 0 else "neutral"
    direction_score = _direction_bucket(code, chg)

    # 量价交叉（量比幅度 + 板块涨停）
    limit_up = _is_limit_up(code, chg)
    volume_score = 0.0
    if chg > 0:
        if vr <= c.volumePriceShrinkRatio:
            volume_score = 25.0 if limit_up else min(15.0, 10 + (c.volumePriceShrinkRatio - vr) * 15)
        elif vr <= c.volumePriceMildRatio:
            volume_score = 20.0 if limit_up else 5.0
        elif vr <= 2.0:
            volume_score = min(15.0, 10 + (vr - 1) * 5)
        elif vr <= c.volumePriceOverVolumeRatio:
            volume_score = max(5.0, 15 - (vr - 2) * 10)
        else:
            volume_score = -min(20.0, 15 + (vr - c.volumePriceOverVolumeRatio) * 10)
    elif chg < 0:
        if vr > c.volumePriceMildRatio:
            volume_score = -20.0
        elif vr >= c.volumePriceShrinkRatio:
            volume_score = -5.0
        else:
            volume_score = -10.0

    # 资金（净占比；>20% 判对倒出货）
    ratio = _finite(zljzb)
    inflow = _finite(zlje)
    fund_score = 0.0
    if ratio is not None and ratio > c.volumePriceAbnormalFundRatio:
        fund_score = -min(15.0, 10 + (ratio - c.volumePriceAbnormalFundRatio) * 0.5)
    elif ratio is not None and ratio > 0:
        fund_score = min(15.0, ratio * 3)
    elif ratio is not None and ratio < 0:
        fund_score = -min(15.0, abs(ratio) * 3)
    elif ratio is None and inflow is not None:
        fund_score = 5.0 if inflow > 0 else -5.0 if inflow < 0 else 0.0

    score = round(_clamp(c.volumePriceBase + direction_score + volume_score + fund_score))

    # 象限（change 方向 × 放缩量）
    volume_state = "up" if vr >= c.volumePriceMildRatio else "down" if vr <= c.volumePriceShrinkRatio else "normal"
    quadrant = None
    if chg > 0:
        quadrant = "rise_volume" if volume_state == "up" else "rise_shrink" if volume_state == "down" else "normal"
    elif chg < 0:
        quadrant = "fall_volume" if volume_state == "up" else "fall_shrink" if volume_state == "down" else "normal"
    else:
        quadrant = "normal"

    reasons: list[str] = []
    if limit_up and vr <= c.volumePriceShrinkRatio:
        reasons.append("缩量涨停（封板惜售，好票）")
    elif vr <= c.volumePriceShrinkRatio and chg > 0:
        reasons.append("缩量上涨（惜售/无量涨）")
    elif vr > c.volumePriceOverVolumeRatio and chg > 0:
        reasons.append("过度放量上涨（疑似出货）")
    elif vr > c.volumePriceMildRatio and chg > 0:
        reasons.append("放量上涨（量价配合）")
    elif vr > c.volumePriceMildRatio and chg < 0:
        reasons.append("放量下跌（风险）")
    elif vr < c.volumePriceShrinkRatio and chg < 0:
        reasons.append("缩量下跌（无量阴跌）")
    if ratio is not None and ratio > c.volumePriceAbnormalFundRatio:
        reasons.append("主力净占比异常高（疑似对倒出货）")
    elif ratio is not None and ratio > 0:
        reasons.append("主力净流入")
    elif ratio is not None and ratio < 0:
        reasons.append("主力净流出")

    return {
        "score": score,
        "direction": direction,
        "quadrant": quadrant,
        "reasons": reasons,
        "breakdown": {
            "direction": round(direction_score, 1),
            "volume": round(volume_score, 1),
            "fund": round(fund_score, 1),
        },
    }


def compute_synergy_state(
    stage: Any,
    vp_score: float | None,
    technical_direction: Any,
    resonance_direction: Any,
    zljzb: Any,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    """四象协同状态：阶段 × 量价（主），技术/共振协同；输出给候选池分层。"""
    c = config or RankTrendConfig()
    stage = str(stage or "")
    ratio = _finite(zljzb)
    fund_suspect = ratio is not None and ratio > c.volumePriceAbnormalFundRatio
    reasons: list[str] = []

    if vp_score is None:
        return {"state": "noData", "hardWarn": False, "reasons": ["量价数据不足，不判定协同"]}

    tech_buy = technical_direction == "buy"
    res_up = resonance_direction == "buy"
    low_vp = vp_score <= c.synergyLowVp
    high_vp = vp_score >= c.synergyHighVp

    state = "suspect"
    if stage in ("ignition", "expansion") and high_vp and tech_buy and res_up:
        state = "启动确认" if stage == "ignition" else "主升确认"
        reasons = [f"阶段={stage}", f"量价分={vp_score}（≥75）", "技术 buy", "共振 ↑"]
    elif stage in ("crowded", "reversal") and (low_vp or fund_suspect):
        state = "风险升级"
        reasons = [f"阶段={stage}", f"量价分={vp_score}（≤40）" if low_vp else "", "资金对倒" if fund_suspect else ""]
    elif stage == "cooling" and low_vp:
        state = "退潮"
        reasons = [f"阶段={stage}", f"量价分={vp_score}（≤40）"]
    else:
        if res_up and not high_vp:
            reasons.append("共振↑但量价分低（无量虚涨）")
        if tech_buy and not high_vp:
            reasons.append("技术 buy 但量价证伪")

    return {
        "state": state,
        "hardWarn": state == "风险升级",
        "reasons": [r for r in reasons if r],
    }
