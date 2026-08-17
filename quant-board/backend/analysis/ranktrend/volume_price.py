"""量价评分与四象协同（阶段 2：量能协同轴）。

TS `src/services/rankTrend/volumePriceValidation.ts::computeVolumePriceScore` 的 Python 移植——
TS 侧仅保留象限/量比展示标签；后端生产 `observation.volumePrice`，前端只消费。
注意：本实现已做"涨跌停可交易性"修订（2026-08），分值/档位与 TS 旧版不再逐分一致。

量价分 0-100：
- 方向（涨跌幅八档，对称）：涨停/跌停（板块阈值）±15；7%+ ±12；5-7% ±10；
  3-5% ±8；2-3% ±6；1-2% ±4；0.5-1% ±2；0-0.5% ±1；平盘 0
- 量价交叉（量比幅度 + 板块涨停语境）：涨停封板买不进，可交易性压低——
  缩量涨停（vr≤0.95 且达板块涨停）+8（封板不可买，不给交易满分）；缩量上涨（非涨停）+10~15；
  准缩量涨停（0.95<vr≤1.05）+10；温和放量上涨（1.05≤vr≤2）+10~15；放量过大（2<vr≤2.5）渐扣；
  过度放量（vr>2.5）-15~-20（出货风险）；缩量跌停（封死卖不出）-15；缩量下跌（非跌停）-10；
  放量下跌 -20；常态 ±5
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
    """板块涨跌幅限制（%）：主板 10% / 创业板·科创板 20% / 北交所 30%。

    ST 股与同板块普通股同阈值（沪深交易所新规：ST 涨跌幅 ±10%，创业板/科创板
    ST 仍 ±20%、北交所 ST 仍 ±30%），代码前缀无法区分 ST 标记，天然按板块阈值
    判定即可，勿新增 ST 5% 特判（旧规已废除）。
    """
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


def _direction_bucket(code: Any, chg: float, config: RankTrendConfig | None = None) -> float:
    """涨跌幅八档方向分（对称）：涨停/跌停 ±15、7%+ ±12、5-7% ±10、3-5% ±8、
    2-3% ±6、1-2% ±4、0.5-1% ±2、0-0.5% ±1、平盘 0。

    档位分值 2026-08-17 参数化（config.volumePriceDirectionBuckets，默认值=原硬编码）。
    """
    c = config or RankTrendConfig()
    if chg >= _daily_limit_pct(code):
        return c.volumePriceDirectionBuckets[0]
    if chg <= -_daily_limit_pct(code):
        return -c.volumePriceDirectionBuckets[0]
    magnitude = abs(chg)
    thresholds = (7.0, 5.0, 3.0, 2.0, 1.0, 0.5)
    for index, threshold in enumerate(thresholds, start=1):
        if magnitude >= threshold:
            return c.volumePriceDirectionBuckets[index] if chg > 0 else -c.volumePriceDirectionBuckets[index]
    if magnitude > 0:
        return c.volumePriceDirectionBuckets[7] if chg > 0 else -c.volumePriceDirectionBuckets[7]
    return 0.0


def _finite(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return min(high, max(low, value))


def _volume_price_tier(quadrant: str | None, fund_score: float, reasons: list[str]) -> tuple[str, list[str]]:
    """量价离散档位（signalTier）。规则见 docs/ranktrend-observation-discrete-tiers-design.md §6.3。"""
    if quadrant is None:
        return "unknown", ["量价数据不足"]
    joined = " ".join(reasons)
    if "对倒出货" in joined or "过度放量" in joined:
        return "E", ["硬风险：对倒出货/过度放量"]
    if "缩量涨停" in joined:
        return "C", ["缩量涨停封板，买不进，不可交易"]  # 信号真但执行不可交易，降出强档
    if quadrant == "rise_volume" and fund_score > 0:
        return "A", ["放量上涨 + 资金流入"]
    if quadrant == "rise_volume":
        return "B", ["放量上涨，量价配合"]
    if quadrant in ("rise_shrink", "normal"):
        return "C", ["缩量上涨/常态"]
    return "D", ["放量下跌/缩量下跌"]


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
            "signalTier": "unknown",
            "tierReasons": ["量价数据不足"],
        }

    # 方向（涨跌幅五档）
    direction = "up" if chg > 0 else "down" if chg < 0 else "neutral"
    direction_score = _direction_bucket(code, chg, c)

    # 量价交叉（量比幅度 + 板块涨停语境）
    limit_up = _is_limit_up(code, chg)
    limit_down = _is_limit_down(code, chg)
    volume_score = 0.0
    if chg > 0:
        if vr <= c.volumePriceShrinkRatio:
            # 缩量涨停封板买不进：只保留弱加成（方向分已含涨停溢价），不给交易满分
            volume_score = 8.0 if limit_up else min(15.0, 10 + (c.volumePriceShrinkRatio - vr) * 15)
        elif vr <= c.volumePriceMildRatio:
            # 准缩量涨停同理压低；非涨停常态 5 分
            volume_score = 10.0 if limit_up else 5.0
        elif vr <= c.volumePriceNormalRatio:
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
            # 缩量跌停封死卖不出，风险加重（对称于涨停不可买）
            volume_score = -15.0 if limit_down else -10.0

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
        reasons.append("缩量涨停（封板不可买）")
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

    _tier, _tier_reasons = _volume_price_tier(quadrant, fund_score, reasons)
    return {
        "score": score,
        "direction": direction,
        "quadrant": quadrant,
        "reasons": reasons,
        "signalTier": _tier,
        "tierReasons": _tier_reasons,
        "breakdown": {
            "direction": round(direction_score, 1),
            "volume": round(volume_score, 1),
            "fund": round(fund_score, 1),
        },
    }


# ── synergy 档位强度权重（vote 语义改进 2026-08-15，v4 权重，horizon=1 验收口径）──
# 模块级常量便于权重扫描/实证迭代；方案 1 方向主导（vote = strength × dir_sign）。
# v4 = 权重扫描最优（saEx=0.0651、passHard=True、spearman=1.0，优于 v0 基线 0.0519）：
# S=1.2/A=1.0/B=0.8/C=0.5/D=1.0/E=1.0 —— 档位区分体现在 S/B/C，D/E 恢复方向主导。
_VOTE_STRENGTH: dict[str, float] = {"S": 1.2, "A": 1.0, "B": 0.8, "C": 0.5, "D": 1.0, "E": 1.0}


def _synergy_tier(
    res_tier: str | None,
    res_dir: str | None,
    rank_tier: str | None,
    rank_dir: str | None,
    vp_tier: str | None,
    vp_dir: str | None,
    lc_tier: str | None,
    config: RankTrendConfig | None = None,
) -> tuple[str, list[str]]:
    """四维合并档位（synergy.signalTier）。规则见 docs/ranktrend-observation-discrete-tiers-design.md §7。

    阈值读 config.tierSynergyVote*（vote 求和为整数，strong/weak/reverse 均为 int）。
    """
    c = config or RankTrendConfig()
    if lc_tier == "E":
        return "E", ["周期一票否决"]
    if vp_tier == "E":
        return "D", ["量价出货硬风险"]

    def _vote(tier: str | None, direction: str | None) -> float:
        """档位强度加权投票（vote 语义改进 2026-08-15，方案 1：方向主导 × 档位幅度）。

        vote = strength(tier) × dir_sign(direction)，dir_sign: buy/up=+1, sell/down=-1, hold=0。
        方向主导（D/E 档 buy 仍投正分），档位强度决定幅度（v4：S=1.2/A=1.0/B=0.8/C=0.5/
        D=1.0/E=1.0，权重扫描最优）。全 1.0 权重 = 旧票数语义（方向 ±1）。
        """
        if tier in ("unknown", None) or not direction:
            return 0.0
        strength = _VOTE_STRENGTH.get(tier, 0.0)
        if direction in ("buy", "up"):
            return strength
        if direction in ("sell", "down"):
            return -strength
        return 0.0

    v = _vote(res_tier, res_dir) + _vote(rank_tier, rank_dir) + _vote(vp_tier, vp_dir)
    # 阶段 3 修复方向 3：档位分级按票数（strong/strong+1），A 档可达。
    # 旧规则 v>=strong 且 lc==A → S 独占 S 判定，而周期档位只有 A/B/D/E（无 C），
    # v>=strong 且 lc∉{A,B,D} 的 A 分支永远不可达 → synergy A 档 n=0（阶段 3 诊断实证）。
    # 新规则：S = v>=strong+1（高票一致，如四维至少 3 票同向），A = v==strong（刚达强买线），
    # B/D/C 语义不变；周期 B/D 时 S/A 降一档规则保留。
    if v >= c.tierSynergyVoteStrong + 1:
        tier, reasons = "S", ["方向一致强买（档位加权高分）"]
    elif v >= c.tierSynergyVoteStrong:
        tier, reasons = "A", ["方向一致强买"]
    elif v >= c.tierSynergyVoteWeak:
        tier, reasons = "B", ["方向分歧，弱买"]
    elif v <= c.tierSynergyVoteReverse:
        tier, reasons = "D", ["反向"]
    else:
        tier, reasons = "C", ["无明确方向"]
    # 周期 B（caution）/D（cooling/crowded 回避）时 S/A 降一档
    if lc_tier in ("B", "D") and tier in ("S", "A"):
        tier = "A" if tier == "S" else "B"
        reasons = reasons + [f"周期 {lc_tier} 环境降档"]
    return tier, reasons


def assemble_observation(
    analysis: dict[str, Any],
    stock: dict[str, Any],
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    """组装 observation.volumePrice / observation.synergy + 各维 signalTier（回测方案 §3.2）。

    与 API 单股链路（原 ranktrend_routes.py 内联组装）同源：resonance 已写入 analysis 时参与
    synergy 投票；replay 链路无 resonance（缺横截面市场 median）时共振维缺票（vote=0），
    synergy 仍可计算。返回写入后的 observation。
    """
    c = config or RankTrendConfig()
    observation = analysis.setdefault("observation", {})
    code = str(stock.get("code") or "")
    resonance = analysis.get("resonance") or {}
    vp = compute_volume_price_score(
        code,
        stock.get("change"),
        stock.get("volumeRatio"),
        stock.get("zlje"),
        stock.get("zljzb"),
        c,
    )
    observation["volumePrice"] = vp
    observation["synergy"] = compute_synergy_state(
        (observation.get("lifecycle") or {}).get("stage"),
        vp.get("score"),
        (observation.get("rankTrend") or {}).get("direction"),
        resonance.get("direction"),
        stock.get("zljzb"),
        c,
    )
    _syn_tier, _syn_reasons = _synergy_tier(
        resonance.get("signalTier"), resonance.get("direction"),
        (observation.get("rankTrend") or {}).get("signalTier"), (observation.get("rankTrend") or {}).get("direction"),
        vp.get("signalTier"), vp.get("direction"),
        (observation.get("lifecycle") or {}).get("signalTier"),
        c,
    )
    observation["synergy"]["signalTier"] = _syn_tier
    observation["synergy"]["tierReasons"] = _syn_reasons
    return observation


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
