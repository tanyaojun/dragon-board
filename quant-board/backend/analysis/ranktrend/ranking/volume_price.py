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
    # 档位边界 2026-09-14 参数化（config.volumePriceDirectionThresholds，默认=原硬编码）
    for index, threshold in enumerate(c.volumePriceDirectionThresholds, start=1):
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
    amount_ratio: Any = None,
) -> dict[str, Any]:
    """量价评分（0-100）与方向/象限/依据，与 TS computeVolumePriceScore 口径一致。

    amount_ratio（2026-08-18 G3）：成交额量比（当前成交额 / 前 N 帧均额）——"价量资金"维度。
    None/0（历史缺失）→ 不参与（fail-visible，不破坏原量价档位）；≥1.5 放量资金加分、
    ≤0.5 缩量资金减分。
    """
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
            volume_score = (
                c.volumeScoreUpShrinkLimitUp if limit_up
                else min(c.volumeScoreUpCap, c.volumeScoreUpShrinkBase + (c.volumePriceShrinkRatio - vr) * c.volumeScoreUpShrinkSlope)
            )
        elif vr <= c.volumePriceMildRatio:
            # 准缩量涨停同理压低；非涨停常态 5 分
            volume_score = c.volumeScoreUpMildLimitUp if limit_up else c.volumeScoreUpMildNormal
        elif vr <= c.volumePriceNormalRatio:
            volume_score = min(c.volumeScoreUpCap, c.volumeScoreUpNormalBase + (vr - 1) * c.volumeScoreUpNormalSlope)
        elif vr <= c.volumePriceOverVolumeRatio:
            volume_score = max(c.volumeScoreUpOverFloor, c.volumeScoreUpOverBase - (vr - 2) * c.volumeScoreUpOverSlope)
        else:
            volume_score = -min(c.volumeScoreUpExcessCap, c.volumeScoreUpExcessBase + (vr - c.volumePriceOverVolumeRatio) * c.volumeScoreUpExcessSlope)
    elif chg < 0:
        if vr > c.volumePriceMildRatio:
            volume_score = c.volumeScoreDownOverMild
        elif vr >= c.volumePriceShrinkRatio:
            volume_score = c.volumeScoreDownShrink
        else:
            # 缩量跌停封死卖不出，风险加重（对称于涨停不可买）
            volume_score = c.volumeScoreDownLimitDown if limit_down else c.volumeScoreDownNormal

    # 资金（净占比；>abnormal 判对倒出货）——系数 2026-09-14 参数化
    ratio = _finite(zljzb)
    inflow = _finite(zlje)
    fund_score = 0.0
    if ratio is not None and ratio > c.volumePriceAbnormalFundRatio:
        fund_score = -min(c.fundScoreCap, c.fundScoreDumpBase + (ratio - c.volumePriceAbnormalFundRatio) * c.fundScoreDumpSlope)
    elif ratio is not None and ratio > 0:
        fund_score = min(c.fundScoreCap, ratio * c.fundScoreNetSlope)
    elif ratio is not None and ratio < 0:
        fund_score = -min(c.fundScoreCap, abs(ratio) * c.fundScoreNetSlope)
    elif ratio is None and inflow is not None:
        fund_score = c.fundScoreInOutStep if inflow > 0 else -c.fundScoreInOutStep if inflow < 0 else 0.0

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

    # 2026-08-18 G3：成交额量比增强（"价量资金"）——amount_ratio None/0（历史缺失）不参与（fail-visible）
    amount_score = 0.0
    ar = _finite(amount_ratio)
    if ar is not None and ar > 0:
        if ar >= c.amountRatioHigh:
            amount_score = c.amountScoreStep
            reasons.append(f"成交额放量资金（量比 {ar:.2f} ≥ {c.amountRatioHigh}）")
        elif ar <= c.amountRatioLow:
            amount_score = -c.amountScoreStep
            reasons.append(f"成交额缩量资金（量比 {ar:.2f} ≤ {c.amountRatioLow}）")
        score = round(_clamp(score + amount_score))
    elif ar is not None and ar <= 0:
        reasons.append("成交额数据缺失（amount=0，不参与量价资金判定）")

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
            "amount": round(amount_score, 1),
        },
    }


def compute_amount_ratio(amount_history: list[Any] | None, config: RankTrendConfig | None = None) -> float | None:
    """成交额量比（2026-08-18 G3）：当前帧成交额 / 前 N 帧（amountRatioPeriod）平均成交额。

    历史不足/全缺失/当前为 0/None/非有限 → None（fail-visible，不参与量价资金判定）。
    """
    c = config or RankTrendConfig()
    raw = amount_history or []
    if not raw:
        return None
    # 当前帧必须取原始序列最后一帧：0/None/非有限 → None（不静默回退上一帧，fail-visible 合同）
    cur = _finite(raw[-1])
    if cur is None or cur <= 0:
        return None
    period = max(1, int(c.amountRatioPeriod))
    base_vals: list[float] = []
    for v in raw[:-1]:
        n = _finite(v)
        if n is not None and n > 0:
            base_vals.append(n)
    if not base_vals:
        return None
    base = base_vals[-period:]  # 前 N 帧（不含当前）
    avg = sum(base) / len(base)
    if avg <= 0:
        return None
    return round(cur / avg, 4)


# ── synergy 档位强度权重（vote 语义改进 2026-08-15，v4 权重，horizon=1 验收口径）──
# 2026-09-14 参数化：默认值迁移至 config.tierSynergyVoteStrengths（S/A/B/C/D/E），
# 本模块常量保留为向后兼容 fallback（config 缺失/长度不符时使用）。
# v4 = 权重扫描最优（saEx=0.0651、passHard=True、spearman=1.0，优于 v0 基线 0.0519）：
# S=1.2/A=1.0/B=0.8/C=0.5/D=1.0/E=1.0 —— 档位区分体现在 S/B/C，D/E 恢复方向主导。
_VOTE_STRENGTH_ORDER: tuple[str, ...] = ("S", "A", "B", "C", "D", "E")
_VOTE_STRENGTH_FALLBACK: dict[str, float] = {"S": 1.2, "A": 1.0, "B": 0.8, "C": 0.5, "D": 1.0, "E": 1.0}


def _lc_veto_keep_hard(config: RankTrendConfig, lc_veto_path: str | None) -> bool:
    """soft 模式下 E 帧是否保留硬否决（阶段 24 d1/d2 路径分流）。

    all_soft 恒转负票；*_hard 模式按 lc_veto_path 分流，路径未知（None：直接构造/测试
    调用未派生时）保守保留硬否决——风险门 fail-safe，生产链路 assemble_observation 恒派生。
    """
    path_mode = str(getattr(config, "lifecycleVetoPathMode", "all_soft") or "all_soft")
    if path_mode not in ("all_soft", "reversal_hard", "highrisk_hard"):
        raise ValueError(f"lifecycleVetoPathMode 非法枚举 {path_mode!r}（可选 all_soft/reversal_hard/highrisk_hard）")
    if path_mode == "all_soft":
        return False
    if lc_veto_path is None:
        return True
    if path_mode == "reversal_hard":
        return lc_veto_path == "reversal"
    return lc_veto_path == "highrisk"


def _lc_gate_veto_path(lifecycle_obs: dict[str, Any]) -> str:
    """lifecycle veto 路径派生（阶段 24，与阶段 23.2 的 8816/11003 分流统计同源）。

    reasons 含"反转路径" → reversal；含"风险背离/过热" → highrisk；兜底按 stage 判
    （reversal → reversal，否则 highrisk）。仅 lc 档位为 E 时由 assemble_observation 调用。
    """
    reasons_text = " ".join(str(r) for r in (lifecycle_obs.get("reasons") or []))
    if "反转路径" in reasons_text:
        return "reversal"
    if "风险背离" in reasons_text or "过热" in reasons_text:
        return "highrisk"
    return "reversal" if str(lifecycle_obs.get("stage") or "") == "reversal" else "highrisk"


def _synergy_tier(
    res_tier: str | None,
    res_dir: str | None,
    rank_tier: str | None,
    rank_dir: str | None,
    vp_tier: str | None,
    vp_dir: str | None,
    lc_tier: str | None,
    config: RankTrendConfig | None = None,
    cs_tier: str | None = None,
    pm_tier: str | None = None,
    dv_tier: str | None = None,
    *,
    lc_veto_path: str | None = None,
) -> tuple[str, list[str]]:
    """四维合并档位（synergy.signalTier）。规则见 docs/ranktrend-observation-discrete-tiers-design.md §7。

    阈值读 config.tierSynergyVote*（vote 求和为整数，strong/weak/reverse 均为 int）。
    cs_tier：crossSection 第 5 维（2026-08-17 G2）；pm_tier：priceMomentum 第 6 维
    （2026-08-17 G1，价格动量/均线）；dv_tier：priceRankDivergence 第 7 维
    （2026-08-18 量名背离——confirm_up 一致强 / rank_lead 关注度先行 / confirm_down /
    price_lead_warn 出货预警）——权重 tierSynergyCrossSectionVote/
    tierSynergyPriceMomentumVote/tierSynergyDivergenceVote。无 direction 字段的维度
    档位自带方向（A/B 强势、C/D 弱势），投票 = 档位符号 × 强度 × 权重。
    """
    c = config or RankTrendConfig()
    # 阶段 24 方案 A：环境门干预形态（默认 hard/hard/hard = 现行为，golden 不漂移）。
    # E 短路否决：hard 恒短路；soft 下按 pathMode 分流（*_hard 保留侧/路径未知 fail-safe
    # 仍短路），转负票侧在票值求和后扣 strength 重走阶梯；off 不干预（评估锚 ≡ 23.8
    # wrapper 把 lc_tier 置 "C" 的删除面）。vp E→D 出货短路（同构位）：off 静默不计票、
    # soft 强制负票（E 强度 × vp 权重）替代短路。
    veto_mode = str(getattr(c, "lifecycleVetoGateMode", "hard") or "hard")
    downgrade_mode = str(getattr(c, "lifecycleDowngradeGateMode", "hard") or "hard")
    vp_gate_mode = str(getattr(c, "volumePriceGateMode", "hard") or "hard")
    for _name, _mode, _legal in (
        ("lifecycleVetoGateMode", veto_mode, ("hard", "soft", "off")),
        ("lifecycleDowngradeGateMode", downgrade_mode, ("hard", "soft", "off")),
        ("volumePriceGateMode", vp_gate_mode, ("hard", "soft", "off")),
    ):
        if _mode not in _legal:
            raise ValueError(f"{_name} 非法枚举 {_mode!r}（可选 {'/'.join(_legal)}）")
    veto_strength = float(getattr(c, "lifecycleVetoVoteStrength", 1.5))
    downgrade_penalty = float(getattr(c, "lifecycleDowngradePenalty", 0.5))
    if veto_strength < 0 or downgrade_penalty < 0:
        raise ValueError(f"lifecycleVetoVoteStrength/lifecycleDowngradePenalty 不能为负（{veto_strength}/{downgrade_penalty}）")

    lc_e_negative_vote = False
    if lc_tier == "E":
        if veto_mode == "hard" or (veto_mode == "soft" and _lc_veto_keep_hard(c, lc_veto_path)):
            return "E", ["周期一票否决"]
        if veto_mode == "soft":
            lc_e_negative_vote = True

    vp_e_forced_vote: float | None = None
    if vp_tier == "E":
        if vp_gate_mode == "hard":
            return "D", ["量价出货硬风险"]
        strengths = getattr(c, "tierSynergyVoteStrengths") or []
        e_strength = strengths[_VOTE_STRENGTH_ORDER.index("E")] if len(strengths) == 6 else _VOTE_STRENGTH_FALLBACK["E"]
        vp_weight = float(getattr(c, "tierSynergyVolumePriceVote", 1.0) or 0.0)
        vp_e_forced_vote = 0.0 if vp_gate_mode == "off" else -e_strength * vp_weight

    _CS_STRENGTH_ORDER = ("A", "B", "C", "D")  # 强度值 2026-09-14 参数化（config.tierSynergyCsStrengths）
    cs_strengths = list(getattr(c, "tierSynergyCsStrengths") or [])
    _CS_STRENGTH = dict(zip(_CS_STRENGTH_ORDER, cs_strengths)) if len(cs_strengths) == 4 else {"A": 1.0, "B": 0.5, "C": -0.5, "D": -1.0}

    def _vote(tier: str | None, direction: str | None) -> float:
        """档位强度加权投票（vote 语义改进 2026-08-15，方案 1：方向主导 × 档位幅度）。

        vote = strength(tier) × dir_sign(direction)，dir_sign: buy/up=+1, sell/down=-1, hold=0。
        方向主导（D/E 档 buy 仍投正分），档位强度决定幅度（v4：S=1.2/A=1.0/B=0.8/C=0.5/
        D=1.0/E=1.0，权重扫描最优；2026-09-14 起读 config.tierSynergyVoteStrengths）。
        全 1.0 权重 = 旧票数语义（方向 ±1）。
        """
        if tier in ("unknown", None) or not direction:
            return 0.0
        strengths = getattr(c, "tierSynergyVoteStrengths") or []
        strength = strengths[_VOTE_STRENGTH_ORDER.index(tier)] if tier in _VOTE_STRENGTH_ORDER and len(strengths) == 6 else _VOTE_STRENGTH_FALLBACK.get(tier, 0.0)
        if direction in ("buy", "up"):
            return strength
        if direction in ("sell", "down"):
            return -strength
        return 0.0

    # 维度票权重参数化（2026-09-14）：res/rank/vp 默认 1.0=原硬编码行为（golden 不漂移）；
    # cs 既有 config 权重。vp E→D 硬降为结构规则（上方早退分支），不随权重归零。
    v = (
        _vote(res_tier, res_dir) * float(getattr(c, "tierSynergyResonanceVote", 1.0) or 0.0)
        + _vote(rank_tier, rank_dir) * float(getattr(c, "tierSynergyRankVote", 1.0) or 0.0)
        + (_vote(vp_tier, vp_dir) * float(getattr(c, "tierSynergyVolumePriceVote", 1.0) or 0.0) if vp_e_forced_vote is None else vp_e_forced_vote)
    )
    cs_weight = float(getattr(c, "tierSynergyCrossSectionVote", 0.0) or 0.0)
    if cs_weight and cs_tier:
        if cs_tier == "A_PERSIST":
            # T4 独立档票值（§12.2 审定修正 3：不扩 _CS_STRENGTH dict、在消费处显式分支，
            # 防"映射不命中静默零票"陷阱——与 §15 list-shape 守卫同族教训）。
            v += float(getattr(c, "tierSynergyCsPersistStrength", 0.5) or 0.0) * cs_weight
        elif cs_tier in _CS_STRENGTH:
            v += _CS_STRENGTH[cs_tier] * cs_weight
    pm_weight = float(getattr(c, "tierSynergyPriceMomentumVote", 0.0) or 0.0)
    if pm_weight and pm_tier and pm_tier in _CS_STRENGTH:
        v += _CS_STRENGTH[pm_tier] * pm_weight
    dv_weight = float(getattr(c, "tierSynergyDivergenceVote", 0.0) or 0.0)
    if dv_weight and dv_tier and dv_tier in _CS_STRENGTH:
        v += _CS_STRENGTH[dv_tier] * dv_weight
    # 阶段 3 修复方向 3：档位分级按票数（strong/strong+1），A 档可达。
    # 旧规则 v>=strong 且 lc==A → S 独占 S 判定，而周期档位只有 A/B/D/E（无 C），
    # v>=strong 且 lc∉{A,B,D} 的 A 分支永远不可达 → synergy A 档 n=0（阶段 3 诊断实证）。
    # 新规则：S = v>=strong+1（高票一致，如四维至少 3 票同向），A = v==strong（刚达强买线），
    # B/D/C 语义不变；周期 B/D 时 S/A 降一档规则保留。
    gate_reasons: list[str] = []
    if lc_e_negative_vote:
        v -= veto_strength
        gate_reasons.append("周期否决负票（soft）")
    if vp_e_forced_vote is not None and vp_gate_mode == "soft":
        gate_reasons.append("量价出货负票（soft）")

    def _ladder(vote_sum: float) -> tuple[str, list[str]]:
        if vote_sum >= c.tierSynergyVoteStrong + 1:
            return "S", ["方向一致强买（档位加权高分）"]
        if vote_sum >= c.tierSynergyVoteStrong:
            return "A", ["方向一致强买"]
        if vote_sum >= c.tierSynergyVoteWeak:
            return "B", ["方向分歧，弱买"]
        if vote_sum <= c.tierSynergyVoteReverse:
            return "D", ["反向"]
        return "C", ["无明确方向"]

    tier, reasons = _ladder(v)
    reasons = reasons + gate_reasons
    # 周期 B（caution）/D（cooling/crowded 回避）对已达 S/A 的干预（阶段 24 双轴形态）：
    # hard=降一档（现行为）；soft=连续惩罚重走阶梯（首评作用域与 hard 一致，仅 S/A）；
    # off=不干预。
    if lc_tier in ("B", "D") and tier in ("S", "A"):
        if downgrade_mode == "hard":
            tier = "A" if tier == "S" else "B"
            reasons = reasons + [f"周期 {lc_tier} 环境降档"]
        elif downgrade_mode == "soft":
            first_tier = tier
            tier, _ = _ladder(v - downgrade_penalty)
            if tier != first_tier:
                reasons = reasons + [f"周期 {lc_tier} 环境惩罚（{first_tier}→{tier}，soft）"]
    return tier, reasons


def assemble_observation(
    analysis: dict[str, Any],
    stock: dict[str, Any],
    config: RankTrendConfig | None = None,
    lc_tier_override: str | None = None,
) -> dict[str, Any]:
    """组装 observation.volumePrice / observation.synergy + 各维 signalTier（回测方案 §3.2）。

    与 API 单股链路（原 ranktrend_routes.py 内联组装）同源：resonance 已写入 analysis 时参与
    synergy 投票；replay 链路无 resonance（缺横截面市场 median）时共振维缺票（vote=0），
    synergy 仍可计算。返回写入后的 observation。

    lc_tier_override（WP2a）：B/D 环境降档 K 帧确认未达时由 engine 传入确认值（如 "C"），
    仅替换传入 _synergy_tier 的 lc_tier（synergy 连锁降档判断）；None = 现行为，
    照旧取 observation.lifecycle.signalTier，发布输出 lifecycle.signalTier 不受影响。
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
        amount_ratio=((observation.get("amountRatio") or None)),
    )
    observation["volumePrice"] = vp
    observation["synergy"] = compute_synergy_state(
        (observation.get("lifecycle") or {}).get("stage"),
        vp.get("score"),
        (observation.get("rankTrend") or {}).get("direction"),
        resonance.get("direction"),
        stock.get("zljzb"),
        c,
        cs_tier=((observation.get("crossSection") or {}).get("signalTier")),
    )
    _lc_obs = observation.get("lifecycle") or {}
    _lc_effective_tier = str(lc_tier_override) if lc_tier_override else str(_lc_obs.get("signalTier") or "")
    _syn_tier, _syn_reasons = _synergy_tier(
        resonance.get("signalTier"), resonance.get("direction"),
        (observation.get("rankTrend") or {}).get("signalTier"), (observation.get("rankTrend") or {}).get("direction"),
        vp.get("signalTier"), vp.get("direction"),
        # WP2a：B/D 降档确认 override（None = 现行为，照旧取 lifecycle.signalTier）
        str(lc_tier_override) if lc_tier_override else (observation.get("lifecycle") or {}).get("signalTier"),
        c,
        cs_tier=((observation.get("crossSection") or {}).get("signalTier")),
        pm_tier=((observation.get("priceMomentum") or {}).get("signalTier")),
        dv_tier=((observation.get("priceRankDivergence") or {}).get("signalTier")),
        # 阶段 24 方案 A：veto 路径派生（仅生效档位为 E 时需要；soft + *_hard 分流消费）
        lc_veto_path=_lc_gate_veto_path(_lc_obs) if _lc_effective_tier == "E" else None,
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
    cs_tier: str | None = None,
) -> dict[str, Any]:
    """四象协同状态：阶段 × 量价（主），技术/共振协同；输出给候选池分层。

    cs_tier（2026-08-18 P0 A1 口径对齐）：crossSection 第 5 维档位——state 与 signalTier
    投票口径一致。cs A（高位+排名上升）可补足主升确认的共振方向缺失；cs D（低位+下降）
    直接升级风险状态；reasons 标注 cs 贡献（fail-visible）。
    """
    c = config or RankTrendConfig()
    stage = str(stage or "")
    ratio = _finite(zljzb)
    fund_suspect = ratio is not None and ratio > c.volumePriceAbnormalFundRatio
    reasons: list[str] = []
    cs_strong = cs_tier == "A"
    cs_weak = cs_tier == "D"

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
    elif stage in ("ignition", "expansion") and high_vp and tech_buy and cs_strong:
        # 2026-08-18 P0 A1：crossSection A（高位+排名上升）补足共振方向缺失——与 signalTier 投票口径一致
        state = "启动确认" if stage == "ignition" else "主升确认"
        reasons = [f"阶段={stage}", f"量价分={vp_score}（≥75）", "技术 buy", "横截面 A（热度高位+排名上升）"]
    elif stage in ("crowded", "reversal") and (low_vp or fund_suspect or cs_weak):
        state = "风险升级"
        reasons = [
            f"阶段={stage}",
            f"量价分={vp_score}（≤40）" if low_vp else "",
            "资金对倒" if fund_suspect else "",
            "横截面 D（低位+排名下降）" if cs_weak else "",
        ]
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
