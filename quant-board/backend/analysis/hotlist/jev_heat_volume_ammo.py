# -*- coding: utf-8 -*-
"""jev 热度维 + 量价维独立判读弹药纯函数层（2026-10-15 试点第四/五维；同批同构）。

定位（用户裁决 2026-10-15「【热度】【量价】一起做了」）：把引擎 synergy 五维里剩下的
【热度】(observation.crossSection) 与【量价】(observation.volumePrice) 单独拎出来，
让 jev 在**同源原始语料**上独立判读，与引擎读数机械对照。并列观察者边界不变
（2026-10-08 裁决）：不回写引擎、不进 synergy 投票、不进交易路径。

**V2 升版（用户裁决 2026-10-15「纯算术题交给规则引擎更合适，jev 强项是逻辑推理，
把这两个题集改成逻辑判断题」；v1 复现题原样保留为协议层阴性对照基线，见预登记 §十一）**。

**CR 2026-10-15 定位修正（首日 244 例验证后，必读）**：V2 曾被表述为「逻辑推理题集」，
实测确认四道逻辑主问的**判据文本与锚复算共用同一组阈值常量**（见下方常量表），因此
judgment 一致性只衡量「LLM 按写明的规则执行的保真度」，**不构成推理能力证据**——
首日实测 volumeCause/volumeTradability/heatAttribution 100%/100%/99.2% 即为此因（自证）。
唯一判据**未给数值阈值**的是 heat_evolution（只给定性描述，锚仍用显式阈值算），
其 74.0% 一致率与 61 例分歧是真实的「语义判读 vs 算术判读」裁量差，也是本题集
唯一有判读价值的读数。**结论：本模块读数一律不得用于任何结论**；协议层健康度看
复现基线（tier/quadrant 对引擎 100%）。判据文本一字未改（与已落档 v2 数据同代），
其「这是逻辑推理题，不是查表题」措辞已被证伪，重跑前必须先改文本并升题集代际。

设计背景（保留备查）：引擎的这两个锚是**纯确定性算术**，不是加权共识——
- 热度：percentile（末项分位）+ percentileDelta（末项−前项）+ relativeToMarket
  （末项−市场 median percentile）三个数过四条阈值 → A/B/C/D/unknown（trend/cross_section.py）；
- 量价：change × volumeRatio × zljzb 三项交叉 → score(0-100) + quadrant + signalTier
  （ranking/volume_price.py）。
所以 V2 把题集主体从「查表复现」改成**逻辑推理**，每题都满足两个硬条件：
①**只吃该股自身多帧序列 + 全池聚合量**（市场中位数/样本数/池大小）——项目铁律
「单股观察层不得获得对照池其他个股数据」不破；②**答案必须能从同一输入机械复算出锚**
（本层提供 *_anchor() 纯函数，runner 现算落档）——逻辑题不是开放题，jev 判对=推理成功、
判错=推理失败，台账才可判读。
逻辑主问测的是**引擎算术没算的结论**：分母效应归因（个体强 vs 全池普涨）、序列形态演化
（刚发酵/高位平稳/退潮/低位平稳/反复）、量价低分主因归因（缩量/资金流出/跌幅/过度放量）、
可交易性（封板/对倒/正常）。这些引擎没有读数，jev 判出来后由 T+1 胜率检验谁对。
复现基线（tier/quadrant）原样保留：证明算术层可靠，同时防止「jev 连查表都错」被
误读成「逻辑更强」。**验收指标是隔日胜率 × 盈亏比，不是复现一致率**（与共振/趋势同规）。

同源合同（本层零 IO；取数与编排在 operations/jev_heat_volume_recheck.py）：
- 分位序列 = 引擎同一实现（attention_rank_lookup + percentile_rank，engine/primitives.py），
  **且同一窗口语义**：该股最近 ≤50 次进榜出现的前缀（跨日，末项=判读帧）；
- 持续高位窗口均值 / 涨跌停判定 = 引擎同一实现（trend/cross_section.py 的 persist 窗口、
  ranking/volume_price.py 的 _is_limit_up/_is_limit_down/_direction_bucket）——可复现算术衍生；
- 量价三字段 = 引擎 compute_volume_price_score 的同一输入（判读帧行 change/volumeRatio/zlje/zljzb）；
- **amountRatio（成交额量比）不喂**：引擎生产链 observation.amountRatio 恒 None
  （2026-08-18 G3 加的这条判据在快照分析链从未生效，已记账不动引擎），本题集严格同源不用它；
- 帧窗口 = 最近 280 个 half_hour 帧（ANALYZE_FULL_MARKET_LOAD_LIMIT 同值）。

黑名单（叙事零出现，机验+人工双查）：引擎五维档位/synergy 投票/finalSignal/compScore/compRank/
lifecycle 阶段/VOTE 方向/温度拥挤答案/共振维读数/趋势维读数/量价 quadrant 与 score 结论/
热度 tier 结论——判定产物一律不喂，只喂原始事实与可复现算术衍生（v4-material 同规）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.jev_state import SCORE_ANCHORS_10
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.primitives import percentile_rank
from backend.analysis.ranktrend.ranking.volume_price import (
    _direction_bucket,
    _is_limit_down,
    _is_limit_up,
)

# ── 版本戳（独立戳：判据/语料任何一字变更即换代，旧代留档不回写）──
# V2（2026-10-15）：题集主体由「查表复现」升版为「逻辑推理」；v1 复现题降级为基线保留。
QUESTION_SET_VERSION_HEAT_RECHECK = "v2"
QUESTION_SET_VERSION_VOLUME_RECHECK = "v2"
HEAT_AMMO_VERSION = "2026-10-15b"
VOLUME_AMMO_VERSION = "2026-10-15b"

_CFG = RankTrendConfig()
HEAT_MIN_BARS = 2          # 引擎 delta 可算线（percentiles[-1]-[-2]）
VOLUME_MIN_FIELDS = ("change", "volumeRatio")   # 引擎 compute_volume_price_score 的必需输入

HEAT_TIERS = ("A", "B", "C", "D", "unknown")
VOLUME_TIERS = ("A", "B", "C", "D", "E", "unknown")
VOLUME_QUADRANTS = ("rise_volume", "rise_shrink", "normal", "fall_volume", "fall_shrink")
HEAT_DIRECTIONS = ("buy", "sell", "hold", "insufficient")
VOLUME_DIRECTIONS = ("buy", "sell", "hold", "insufficient")

# ── V2 逻辑推理题选项（与判据文本逐字同源；改一字=改门）──
# 热度·归因：引擎高位是个体强势还是全池普涨（分母效应）
HEAT_ATTRIBUTIONS = ("individual_strong", "market_wide_rise", "individual_weak",
                     "market_wide_fall", "follow_market", "insufficient")
# 热度·演化：序列形态（刚发酵/高位平稳/退潮/低位平稳/反复）
HEAT_EVOLUTIONS = ("igniting", "sustaining", "fading", "dormant", "volatile", "insufficient")
# 量价·主因归因：这份量价配合的主导因素
VOLUME_CAUSES = ("over_volume_exhaustion", "fund_outflow", "volume_expansion_up",
                 "volume_expansion_down", "shrink_up", "shrink_down", "neutral", "insufficient")
# 量价·可交易性：封板/对倒/正常
VOLUME_TRADABILITY = ("tradable", "limit_up_blocked", "limit_down_blocked",
                       "abnormal_fund_flow", "insufficient")

# V2 主问阈值（CR 2026-10-15：判据文本与锚复算共用同一组常量——这既是「杜绝两套口径」
# 的设计意图，也正是本题集自证、一致率无推理能力含义的根因：出题规则与评分规则同源）
HEAT_ATTRIBUTION_ABS_MIN = 50.0     # 绝对分位分界（个体侧/市场侧）
HEAT_ATTRIBUTION_REL_MIN = 15.0     # 相对市场中位幅度门（|Δ|<此值=跟随市场）
HEAT_EVOLUTION_WINDOW = 3           # 演化判读窗口（末 N 次有效出现）
HEAT_EVOLUTION_GAIN = 8.0           # 点燃门（窗口内升幅）
HEAT_EVOLUTION_DROP = -8.0          # 退潮门（窗口内跌幅）
HEAT_EVOLUTION_HIGH = 60.0          # 高位线
HEAT_EVOLUTION_LOW = 40.0           # 低位线
HEAT_EVOLUTION_FLAT = 10.0          # 平稳带（窗口极差 ≤ 此值）
HEAT_EVOLUTION_VOLATILE = 25.0      # 反复门（窗口极差 ≥ 此值）
VOLUME_OVER_RATIO = 2.5             # 过度放量门（引擎 overVolume 同值）
VOLUME_ABNORMAL_FUND = 10.0         # 对倒出货门（引擎 abnormalFund 同值）
VOLUME_FUND_OUTFLOW = -5.0          # 资金流出门（主力净占比 ≤ 此值）
VOLUME_MILD_RATIO = 1.05            # 放量门（引擎 mildRatio 同值）
VOLUME_SHRINK_RATIO = 0.95          # 缩量门（引擎 shrinkRatio 同值）

# 强度标尺（与引擎 label 阈值同口径 85/67/50/27）——V2 已无 score 复现题，本模块不再提供
# strength_band；共振/趋势维各自模块内的实现不受影响（同一阈值，各自单一事实源）。
# ── 引擎同源衍生（纯函数；runner 只负责把序列/帧行喂进来）──

def heat_derived(percentiles: list[float], market_median: float | None,
                 config: RankTrendConfig | None = None) -> dict[str, Any]:
    """引擎 cross_section.compute_cross_section 的三个输入衍生（不含档位判定）。

    返回 {percentile, percentileDelta, relativeToMarket, persist}；persist=(窗口N, 近N帧均值)
    或 None（窗口不足/含缺项，与引擎 persist 同口径，不伪造持续性）。
    """
    c = config or _CFG
    pcts = [p for p in percentiles if isinstance(p, (int, float)) and not isinstance(p, bool)]
    if not pcts:
        return {"percentile": None, "percentileDelta": None, "relativeToMarket": None,
                "persist": None}
    percentile = float(pcts[-1])
    delta = (percentile - float(pcts[-2])) if len(pcts) >= HEAT_MIN_BARS else None
    market = market_median if isinstance(market_median, (int, float)) else None
    relative = (percentile - float(market)) if market is not None else None
    persist: tuple[int, float] | None = None
    frames = int(getattr(c, "crossSectionPersistFrames", 0) or 0)
    if frames >= HEAT_MIN_BARS:
        window = [float(v) for v in pcts[-frames:]]
        if len(window) == frames:
            persist = (frames, sum(window) / frames)
    return {"percentile": percentile, "percentileDelta": delta,
            "relativeToMarket": relative, "persist": persist}


def volume_derived(code: str, change: Any, volume_ratio: Any, zlje: Any,
                   zljzb: Any) -> dict[str, Any]:
    """引擎 compute_volume_price_score 的输入衍生（不含 score/quadrant/tier 判定）。

    返回 {change, volumeRatio, zlje, zljzb, directionBucket, limitUp, limitDown,
    fundRatioPositive}；directionBucket=_direction_bucket 的输出（可复现算术衍生）。
    """
    chg = change if isinstance(change, (int, float)) and not isinstance(change, bool) else None
    vr = volume_ratio if isinstance(volume_ratio, (int, float)) and not isinstance(volume_ratio, bool) else None
    return {
        "change": chg, "volumeRatio": vr,
        "zlje": zlje if isinstance(zlje, (int, float)) else None,
        "zljzb": zljzb if isinstance(zljzb, (int, float)) else None,
        "directionBucket": _direction_bucket(code, chg, _CFG) if chg is not None else None,
        "limitUp": _is_limit_up(code, chg),
        "limitDown": _is_limit_down(code, chg),
    }


# ── V2 主问锚复算（纯函数；runner 现算后落档，与 jev 答案机械对照）──
# 铁律：锚与判据文本共用同一组阈值常量，杜绝「两套口径」。
# CR 2026-10-15 副作用明示：同源=自证——jev 照判据执行即得锚值，一致率因此不测推理。

def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return None if x != x else x


def heat_attribution_anchor(percentile: Any, relative_to_market: Any) -> str:
    """热度·归因题锚（三步走，阈值门显式）。

    第一步·取两个证据：percentile（该股绝对分位）、relativeToMarket（该股 − 市场中位数分位）。
    第二步·过门：|relativeToMarket| < 15 → follow_market（与市场中位同水位，个体/市场不可分）。
    第三步·定象限：相对门过 + 绝对分位 50 分界 → 个体侧/市场侧。
    任一证据缺失 → insufficient。
    """
    p, r = _num(percentile), _num(relative_to_market)
    if p is None or r is None:
        return "insufficient"
    if abs(r) < HEAT_ATTRIBUTION_REL_MIN:
        return "follow_market"
    if r > 0:
        return "individual_strong" if p >= HEAT_ATTRIBUTION_ABS_MIN else "market_wide_rise"
    return "individual_weak" if p < HEAT_ATTRIBUTION_ABS_MIN else "market_wide_fall"


def heat_evolution_anchor(percentiles: list[float] | Any) -> str:
    """热度·演化题锚（末 N 次有效出现的形态判读，按序短路）。

    ①volatile：窗口极差 ≥ 25（反复）；②igniting：窗口升幅 ≥ +8 且末项 ≥ 60（刚发酵）；
    ③fading：窗口跌幅 ≤ −8（退潮）；④sustaining：末项 ≥ 60 且极差 ≤ 10（高位平稳）；
    ⑤dormant：末项 ≤ 40 且极差 ≤ 10（低位平稳）；⑥兜底：末项 ≥ 60 → sustaining /
    末项 ≤ 40 → dormant / 其余 → follow_market 侧（中位区无稳定形态，归 sustaining 兜底
    不制造方向）。窗口有效出现 < 3 → insufficient（序列太短，形态不可判）。
    """
    pcts = [p for p in (percentiles or []) if isinstance(p, (int, float)) and not isinstance(p, bool)]
    win = pcts[-HEAT_EVOLUTION_WINDOW:]
    if len(win) < HEAT_EVOLUTION_WINDOW:
        return "insufficient"
    spread = max(win) - min(win)
    last, gain = win[-1], win[-1] - win[0]
    if spread >= HEAT_EVOLUTION_VOLATILE:
        return "volatile"
    if gain >= HEAT_EVOLUTION_GAIN and last >= HEAT_EVOLUTION_HIGH:
        return "igniting"
    if gain <= HEAT_EVOLUTION_DROP:
        return "fading"
    if last >= HEAT_EVOLUTION_HIGH and spread <= HEAT_EVOLUTION_FLAT:
        return "sustaining"
    if last <= HEAT_EVOLUTION_LOW and spread <= HEAT_EVOLUTION_FLAT:
        return "dormant"
    return "sustaining" if last >= HEAT_EVOLUTION_HIGH else (
        "dormant" if last <= HEAT_EVOLUTION_LOW else "sustaining")


def volume_cause_anchor(change: Any, volume_ratio: Any, zljzb: Any, zlje: Any,
                        limit_up: Any = None, limit_down: Any = None) -> str:
    """量价·主因归因题锚（按序短路，与判据门槛表同一组常量）。

    ①over_volume_exhaustion：主力净占比 > +10（对倒出货）或（涨幅 > 0 且量比 > 2.5 过度放量）；
    ②fund_outflow：主力净占比 ≤ −5（资金流出主导）；
    ③四象限：涨幅/量比符号 × 区间 → volume_expansion_up / volume_expansion_down /
    shrink_up / shrink_down；④neutral：平盘或中态；字段缺失/量比 ≤ 0 → insufficient。
    """
    c, vr = _num(change), _num(volume_ratio)
    z = _num(zljzb)
    if c is None or vr is None or vr <= 0:
        return "insufficient"
    if (z is not None and z > VOLUME_ABNORMAL_FUND) or (c > 0 and vr > VOLUME_OVER_RATIO):
        return "over_volume_exhaustion"
    if z is not None and z <= VOLUME_FUND_OUTFLOW:
        return "fund_outflow"
    if c == 0 or (vr > VOLUME_SHRINK_RATIO and vr < VOLUME_MILD_RATIO):
        return "neutral"
    up = c > 0
    expanding = vr >= VOLUME_MILD_RATIO
    if up:
        return "volume_expansion_up" if expanding else "shrink_up"
    return "volume_expansion_down" if expanding else "shrink_down"


def volume_tradability_anchor(change: Any, volume_ratio: Any, zljzb: Any,
                              limit_up: Any = None, limit_down: Any = None) -> str:
    """量价·可交易性题锚（按序短路）。

    ①limit_up_blocked：涨停（封死买不进）；②limit_down_blocked：跌停（封死卖不出）；
    ③abnormal_fund_flow：主力净占比 > +10 或（涨幅 > 0 且量比 > 2.5）；
    ④tradable：其余；字段缺失/量比 ≤ 0 → insufficient。
    注：封板优先于资金异常（一字板同时可以净占比异常，但买不进是更硬的约束）。
    """
    c, vr = _num(change), _num(volume_ratio)
    z = _num(zljzb)
    if c is None or vr is None or vr <= 0:
        return "insufficient"
    if limit_up:
        return "limit_up_blocked"
    if limit_down:
        return "limit_down_blocked"
    if (z is not None and z > VOLUME_ABNORMAL_FUND) or (c > 0 and vr > VOLUME_OVER_RATIO):
        return "abnormal_fund_flow"
    return "tradable"


# ── 预检 riskFlag（与引擎两条不可算线同口径）──

def heat_risk_flag(percentile: Any, delta: Any) -> dict:
    """热度维预检：percentile 缺失=引擎 unknown 同口径（横截面数据不足）；
    delta 缺失=首帧/单点（partial：绝对档可判、delta 确认路径不可达）。"""
    if not isinstance(percentile, (int, float)) or isinstance(percentile, bool):
        return {"level": "data_insufficient",
                "reasons": ["横截面 percentile 缺失（无 avgRankNum，引擎同口径 unknown）"]}
    if not isinstance(delta, (int, float)) or isinstance(delta, bool):
        return {"level": "partial",
                "reasons": ["delta 缺失（首帧/单点）：绝对档可判，A/D 的 delta 确认路径不可达"]}
    return {"level": "ok", "reasons": []}


def volume_risk_flag(change: Any, volume_ratio: Any) -> dict:
    """量价维预检：与引擎 compute_volume_price_score 的早退线同口径——
    change/volumeRatio 缺失、或 volumeRatio ≤ 0 → 引擎 score=None/signalTier=unknown。"""
    if not isinstance(change, (int, float)) or isinstance(change, bool):
        return {"level": "data_insufficient", "reasons": ["涨跌幅缺失（引擎同口径不评估）"]}
    if not isinstance(volume_ratio, (int, float)) or isinstance(volume_ratio, bool):
        return {"level": "data_insufficient", "reasons": ["量比缺失（引擎同口径不评估）"]}
    if float(volume_ratio) <= 0:
        return {"level": "data_insufficient", "reasons": ["量比 ≤0（引擎同口径不评估）"]}
    return {"level": "ok", "reasons": []}


# ── 题集（判据冻结件候选：逐字=将来代码文本；改一字=改门，须走预登记+用户点头）──
# CR 2026-10-15：heat_attribution / volume_cause / volume_tradability 三道题的判据文本
# 含显式阈值（与锚同源），属复现题性质；heat_evolution 判据只有定性描述（真逻辑题）。
# 文本保持 v2 原样不改成因：库中已落档 244 例 v2 读数，改文本须升代际并重跑（用户未批准）。

_HEAT_TIER_INSTR = (
    "以下是某只股票在判读帧的【横截面关注度】判读原料——只含热榜排名（注意力）维度的原始事实"
    "与可复现算术衍生，不含任何价格结论/量价结论/四维档位/周期阶段/方向票结论。"
    "请按下面这张**显式门槛表**把该股判到 A/B/C/D/unknown 五档之一（这是复现题：逐条比对、"
    "按给定顺序短路判定，不得自行发明阈值，也不得参考表中未给的其他因素）。"
    "percentile=该股在判读帧全池注意力排名百分位（0-100，越高越靠前）；"
    "percentileDelta=末次出现分位 − 前一次出现分位（跨日环比，未进榜不插值）。"
    "**当 percentileDelta 有效时**（按序短路）："
    "①A 档：percentile ≥ 85 且 percentileDelta ≥ +5（高位 + 热度排名上升）；"
    "②B 档：percentile ≥ 50 且 percentileDelta ≥ +15（中位之上 + 热度显著上升）；"
    "③D 档：percentile ≤ 15 且 percentileDelta ≤ −5（低位 + 热度排名下降）；"
    "④C 档：percentile ≤ 50 且 percentileDelta ≤ −15（热度显著下降）；"
    "⑤B 档：percentile ≥ 70（横截面高位，无需 delta 确认）；"
    "⑥C 档：percentile ≤ 30（横截面低位）；"
    "⑦C 档：其余一切（中位区间无强势证据）。"
    "**当 percentileDelta 缺失时**（首帧/单点，不给 A/D）："
    "percentile ≥ 85 → B 档（高位但缺 delta 确认）；percentile ≥ 70 → B 档（横截面高位）；"
    "percentile ≤ 15 → C 档（低位但缺 delta 确认）；其余 → C 档（中位区间无强势证据）。"
    "**percentile 缺失或非法 → unknown**（横截面数据不足）。"
    "注意：①-④必须成对出现才升级/降级，单独的高位或单独的上升都不构成 A 档；"
    "⑤是绝对档路径，与 delta 无关。"
    "只依据所给信息判断，不预测后市。"
)

_HEAT_DIR_INSTR = (
    "同一份原料，该股横截面关注度的**方向**读作 buy、sell、hold 还是 insufficient，"
    "附 0-1 置信度。"
    "口径铁律：buy/sell 只表示「该股在全池中的相对关注度在上升/下降」，"
    "**绝不表示『这只票值不值得买』**——可买入性是另一条线的事，本材料里没有价格与量价证据。"
    "**判读按两步走**："
    "第一步·看两个证据的同向性（①percentile 相对市场中位数的位置 relativeToMarket；"
    "②percentileDelta 的符号与幅度）；"
    "第二步·定方向：两个证据同向为正 → buy；同向为负 → sell；"
    "一个为正一个为负、或两者幅度都在 ±2 以内（噪声级）→ hold；"
    "percentile 缺失/非法 → insufficient。"
    "证据冲突=hold，不是 insufficient；insufficient 仅限数据不可用。"
    "只依据所给信息判断，不预测后市。"
)

_VOLUME_TIER_INSTR = (
    "以下是某只股票在判读帧的【量价】判读原料——只含该帧原始事实与可复现算术衍生，"
    "不含任何档位/象限/分数结论、不含周期阶段、不含方向票结论、不含其他四维读数。"
    "请按下面这张**显式门槛表**把该股判到 A/B/C/D/E/unknown 六档之一（这是复现题："
    "逐条比对、按给定顺序短路判定，不得自行发明阈值）："
    "第0步·unknown：涨幅缺失、或量比缺失、或量比 ≤ 0（不评估）；"
    "第1步·E 档（硬风险，优先于其余一切档）：主力净占比 > +10（对倒出货特征），"
    "**或** 涨幅 > 0 且量比 > 2.5（过度放量上涨，疑似出货）；"
    "第2步·C 档（封板不可交易）：涨停 且 量比 ≤ 0.95（缩量涨停，封死买不进）；"
    "第3步·放量上涨分支（涨幅 > 0 且量比 ≥ 1.05）：主力净占比 > 0"
    "（或主力净占比缺失而主力净额 > 0）→ **A 档**；否则 → **B 档**；"
    "第4步·C 档：涨幅 > 0 且量比 ≤ 0.95（缩量上涨/无量涨），或 0.95 < 量比 < 1.05 的中态；"
    "第5步·D 档：涨幅 < 0（无论放量下跌还是缩量下跌）。"
    "注意：**涨幅的绝对大小（涨 3% 还是涨 0.1%）不影响档位**——档位只由涨跌符号、量比区间、"
    "主力净占比符号与封板状态决定；涨幅档位分只进强度分、不进档位。"
    "涨幅=该帧涨跌幅（%）；量比=该帧量比；主力净额/主力净占比=该帧资金字段；"
    "涨跌停标记与涨跌幅档位分是引擎同款算法现算的衍生，可作辅助但不改变上述门槛。"
    "只依据所给信息判断，不预测后市。"
)

_VOLUME_QUADRANT_INSTR = (
    "同一份原料，该股量价配合的**象限**（复现题，按显式规则判，五选一）："
    "①rise_volume：涨幅 > 0 且量比 ≥ 1.05（放量上涨）；"
    "②rise_shrink：涨幅 > 0 且量比 ≤ 0.95（缩量上涨）；"
    "③fall_volume：涨幅 < 0 且量比 ≥ 1.05（放量下跌）；"
    "④fall_shrink：涨幅 < 0 且量比 ≤ 0.95（缩量下跌）；"
    "⑤normal：涨幅 = 0（平盘），或 0.95 < 量比 < 1.05 的中态。"
    "边界按表取闭区间：量比恰为 1.05 算放量、恰为 0.95 算缩量。"
    "涨幅或量比缺失 → insufficient（本维另设 insufficient 选项）。"
    "只依据所给信息判断，不预测后市。"
)

_VOLUME_DIR_INSTR = (
    "同一份原料，该股量价配合**是否支持做多**读作 buy、sell、hold 还是 insufficient，"
    "附 0-1 置信度。"
    "口径铁律：这是语义判断题，引擎只给涨跌方向（up/down/neutral）与象限，"
    "**没有**『是否支持做多』这个读数——所以本题没有引擎对照锚，你的判断只落档备验。"
    "buy/sell 也**绝不表示『现在就该买/卖』**，只表示「这份量价配合对做多方向是正/负贡献」。"
    "判读要点：放量上涨+资金净流入=最强正向；缩量上涨（惜售/无量）与放量下跌+资金流出=负向；"
    "缩量下跌（抛压衰竭）可以是弱正向；涨跌停封板的可交易性要单独说明（涨停封死买不进、"
    "跌停封死卖不出），不要把封板当成普通放量。"
    "原料缺失/量比 ≤ 0 → insufficient。只依据所给信息判断，不预测后市。"
)

_HEAT_ATTRIBUTION_INSTR = (
    "以下是某只股票在判读帧的【横截面关注度】判读原料——只含热榜排名（注意力）维度的原始事实"
    "与可复现算术衍生，不含任何价格结论/量价结论/四维档位/周期阶段/方向票结论。"
    "**这是逻辑推理题，不是查表题**：没有给门槛表，请你自己从证据推出结论，并说明推理依据。"
    "要回答的问题：**引擎把这个位置读成『高位』，但『高位』可能有两种完全不同的成因——"
    "一是个体真的在变强，二是全池水涨船高（分母效应）把它抬了上去。**"
    "请判定这份原料支持哪一种，六选一："
    "individual_strong（个体强）/ market_wide_rise（全池普涨）/ individual_weak（个体弱）/"
    "market_wide_fall（跑输普涨水位）/ follow_market（跟随市场）/ insufficient（数据不可用）。"
    "**判读按三步走**："
    "第一步·摆出两个证据：percentile（该股在全池注意力排名百分位，0-100，越高越靠前）与"
    "relativeToMarket（percentile − 市场 median percentile，即它比全池中位数高/低多少）；"
    "第二步·过相对门：|relativeToMarket| < 15 → follow_market（与市场中位同水位，"
    "个体与市场不可分，不要硬拆）；"
    "第三步·过绝对门（仅当第二步没过）：用 percentile 与 50 分界定个体侧还是市场侧——"
    "relativeToMarket ≥ +15 且 percentile ≥ 50 → individual_strong；"
    "relativeToMarket ≥ +15 且 percentile < 50 → market_wide_rise；"
    "relativeToMarket ≤ −15 且 percentile < 50 → individual_weak；"
    "relativeToMarket ≤ −15 且 percentile ≥ 50 → market_wide_fall。"
    "任一步的证据缺失或非法 → insufficient。"
    "percentileDelta=末次出现分位 − 前一次出现分位（跨日环比，未进榜不插值），可作旁证；"
    "注意 market median percentile 是**全池聚合量**（不是任何其他个股的读数），"
    "本材料不含任何其他个股的个体数据。"
    "只依据所给信息判断，不预测后市。"
)

_HEAT_EVOLUTION_INSTR = (
    "同一份原料（含该股跨日逐次出现的分位序列），请判定它的**形态演化阶段**，六选一："
    "igniting（刚发酵）/ sustaining（高位平稳）/ fading（退潮）/ dormant（低位平稳）/"
    "volatile（反复）/ insufficient（序列太短不可判）。"
    "**这是逻辑推理题，不是查表题**：没有给门槛表，请自己从序列的走势、位置与波动幅度推出结论。"
    "判读只用**末 3 次有效出现**（不是全部历史），注意：序列里可能夹着缺项帧，"
    "缺项不参与形态判断（fail-visible 已标出）。"
    "推理要点：igniting=窗口内明显往上走且已站上高位；fading=窗口内明显往下掉；"
    "sustaining=高位且波动很小；dormant=低位且波动很小；volatile=窗口内大幅来回摆动"
    "（形态不稳定，比涨跌方向更值得注意）。"
    "**有效出现不足 3 次 → insufficient**，不要用两次出现硬判形态。"
    "只依据所给信息判断，不预测后市。"
)

_VOLUME_CAUSE_INSTR = (
    "同一份量价原料（帧行原始事实 + 引擎同款可复现衍生），请判定这份量价配合的**主导因素**"
    "是什么，八选一：over_volume_exhaustion（过度放量疑似出货）/ fund_outflow（资金流出主导）/"
    "volume_expansion_up（放量上涨）/ volume_expansion_down（放量下跌）/"
    "shrink_up（缩量上涨）/ shrink_down（缩量下跌）/ neutral（平盘或中态）/ insufficient。"
    "**这是逻辑推理题，不是查表题**：没有给门槛表，请自己从涨幅、量比、主力净额/净占比"
    "三项的相互关系推出『哪一个因素在主导』，并说明依据。"
    "推理要点（按优先级）："
    "①先看硬风险——主力净占比 > +10（对倒出货特征）或（涨幅 > 0 且量比 > 2.5 过度放量上涨）"
    "→ over_volume_exhaustion，**优先于其余一切选项**；"
    "②再看资金——主力净占比 ≤ −5 → fund_outflow（资金流出主导，先于四象限）；"
    "③剩下的按「涨跌符号 × 量比区间」四象限归因：涨幅 > 0 且量比 ≥ 1.05 → volume_expansion_up；"
    "涨幅 < 0 且量比 ≥ 1.05 → volume_expansion_down；涨幅 > 0 且量比 ≤ 0.95 → shrink_up；"
    "涨幅 < 0 且量比 ≤ 0.95 → shrink_down；涨幅 = 0（平盘）或 0.95 < 量比 < 1.05 的中态 → neutral。"
    "边界按闭区间取：量比恰为 1.05 算放量、恰为 0.95 算缩量。"
    "注意：**涨幅的绝对大小不影响归因**（涨 3% 还是涨 0.1%，只要符号是正、量比在放量区，"
    "主导因素都是放量上涨）——不要拿涨幅大小当门槛。"
    "涨跌停标记与涨跌幅档位分是引擎同款算法现算的衍生，可作旁证。"
    "原料缺失/量比 ≤ 0 → insufficient。只依据所给信息判断，不预测后市。"
)

_VOLUME_TRADABILITY_INSTR = (
    "同一份原料，请判定这只股票当前的**可交易性**，五选一："
    "limit_up_blocked（涨停封死买不进）/ limit_down_blocked（跌停封死卖不出）/"
    "abnormal_fund_flow（资金异常，对倒出货或过度放量）/ tradable（正常可交易）/ insufficient。"
    "**这是逻辑推理题，不是查表题**：没有给门槛表，请自己判断『这个价位上，想买/想卖的人能不能成交』。"
    "推理要点（按优先级）：①涨停 → limit_up_blocked（封死买不进，哪怕量价配合再好也没用）；"
    "②跌停 → limit_down_blocked；③主力净占比 > +10（对倒出货特征）或"
    "（涨幅 > 0 且量比 > 2.5 过度放量上涨）→ abnormal_fund_flow；④其余 → tradable。"
    "**封板优先于资金异常**：一字板完全可以同时净占比异常，但『买不进』是更硬的约束，"
    "不要因为看到大单净流入就把涨停判成 tradable。"
    "注意：涨停/跌停标记是引擎同款代码板块规则现算的衍生；封板≠普通放量。"
    "原料缺失/量比 ≤ 0 → insufficient。只依据所给信息判断，不预测后市。"
)

# ── V2 说明：volume_score 复现题与 _VOLUME_SCORE_INSTR 已在 V2 删除（纯算术查表、jev 无优势；
# 强度语义由 volume_cause 归因题覆盖）。v1 判据原文留档于预登记 §十一。

QUESTIONS_HEAT_RECHECK: dict[str, dict] = {
    "heat_attribution": {
        "type": "choice",
        "instructions": _HEAT_ATTRIBUTION_INSTR,
        "criteria": {
            "individual_strong": "relativeToMarket ≥ +15 且 percentile ≥ 50（个体在全池中位之上，且绝对位置不低——是个体在强，不是水涨船高）",
            "market_wide_rise": "relativeToMarket ≥ +15 且 percentile < 50（它比市场中位好，但绝对分位不到 50——是全池水位高，个体并不强）",
            "individual_weak": "relativeToMarket ≤ −15 且 percentile < 50（绝对位置低且落后于市场中位——个体在弱）",
            "market_wide_fall": "relativeToMarket ≤ −15 且 percentile ≥ 50（绝对位置不低但远低于市场中位——它跑输了普涨的水位）",
            "follow_market": "|relativeToMarket| < 15（与市场中位同水位，个体/市场不可分）",
            "insufficient": "percentile 或市场 median 缺失/非法（数据不可用）",
        },
    },
    "heat_evolution": {
        "type": "choice",
        "instructions": _HEAT_EVOLUTION_INSTR,
        "criteria": {
            "igniting": "末3次有效出现升幅 ≥ +8 且末项分位 ≥ 60（刚发酵，还在往上走）",
            "sustaining": "末项分位 ≥ 60 且窗口极差 ≤ 10（高位平稳，热度维持）",
            "fading": "末3次有效出现跌幅 ≤ −8（退潮，排名在掉）",
            "dormant": "末项分位 ≤ 40 且窗口极差 ≤ 10（低位平稳，没什么动静）",
            "volatile": "末3次有效出现极差 ≥ 25（反复大幅摆动，形态不稳定）",
            "insufficient": "末3次有效出现不足 3 次（序列太短，形态不可判）",
        },
    },
    "heat_direction": {
        "type": "choice",
        "instructions": _HEAT_DIR_INSTR,
        "criteria": {
            "buy": ("relativeToMarket 为正、且 percentileDelta 为正且幅度 ≥ +2"
                    "（两个证据同向为正：相对市场中位数在上、环比在升）"),
            "sell": ("relativeToMarket 为负、且 percentileDelta 为负且幅度 ≤ −2"
                     "（两个证据同向为负）"),
            "hold": ("两个证据一正一负；或两者幅度都在 ±2 以内（噪声级）；"
                     "或 percentileDelta 缺失（首帧/单点）而 percentile 接近市场中位数"),
            "insufficient": "仅 percentile 缺失/非法（数据不可用）；永不因证据冲突选此项",
        },
    },
    "heat_tier": {
        "type": "choice",
        "instructions": _HEAT_TIER_INSTR,
        "criteria": {
            "A": "percentile ≥ 85 且 percentileDelta ≥ +5（高位 + 热度排名上升，横截面强势确认）",
            "B": ("percentile ≥ 50 且 percentileDelta ≥ +15（中位之上 + 热度显著上升）；"
                  "或 percentile ≥ 70（横截面高位，绝对档路径，无需 delta 确认）"),
            "C": ("percentile ≤ 50 且 percentileDelta ≤ −15（热度显著下降）；"
                  "或 percentile ≤ 30（横截面低位）；或其余中位区间无强势证据——兜底档"),
            "D": "percentile ≤ 15 且 percentileDelta ≤ −5（低位 + 热度排名下降）",
            "unknown": "percentile 缺失或非法（横截面数据不足，引擎同口径）",
        },
    },
}

QUESTIONS_VOLUME_RECHECK: dict[str, dict] = {
    "volume_cause": {
        "type": "choice",
        "instructions": _VOLUME_CAUSE_INSTR,
        "criteria": {
            "over_volume_exhaustion": "主力净占比 > +10（对倒出货特征）；或涨幅 > 0 且量比 > 2.5（过度放量上涨，疑似出货）——硬风险优先",
            "fund_outflow": "主力净占比 ≤ −5（资金流出主导，先于四象限）",
            "volume_expansion_up": "涨幅 > 0 且量比 ≥ 1.05（放量上涨，资金同向）",
            "volume_expansion_down": "涨幅 < 0 且量比 ≥ 1.05（放量下跌）",
            "shrink_up": "涨幅 > 0 且量比 ≤ 0.95（缩量上涨/无量涨）",
            "shrink_down": "涨幅 < 0 且量比 ≤ 0.95（缩量下跌）",
            "neutral": "涨幅 = 0（平盘），或 0.95 < 量比 < 1.05 的中态",
            "insufficient": "涨幅或量比缺失、或量比 ≤ 0（数据不可用）",
        },
    },
    "volume_tradability": {
        "type": "choice",
        "instructions": _VOLUME_TRADABILITY_INSTR,
        "criteria": {
            "limit_up_blocked": "涨停（封死买不进，可交易性为负）",
            "limit_down_blocked": "跌停（封死卖不出）",
            "abnormal_fund_flow": "主力净占比 > +10（对倒出货）；或涨幅 > 0 且量比 > 2.5（过度放量上涨）",
            "tradable": "其余一切（正常可交易）",
            "insufficient": "涨幅或量比缺失、或量比 ≤ 0（数据不可用）",
        },
    },
    "volume_direction": {
        "type": "choice",
        "instructions": _VOLUME_DIR_INSTR,
        "criteria": {
            "buy": "量价配合对做多方向是正贡献（放量上涨+资金净流入为最强；缩量下跌抛压衰竭为弱正）",
            "sell": "量价配合对做多方向是负贡献（放量下跌+资金流出；缩量/无量上涨的虚涨）",
            "hold": "量价配合中性/互相矛盾（平盘中态、涨跌方向与量能不同向、或封板导致不可交易）",
            "insufficient": "涨幅或量比缺失、或量比 ≤ 0（数据不可用）",
        },
    },
    "volume_tier": {
        "type": "choice",
        "instructions": _VOLUME_TIER_INSTR,
        "criteria": {
            "A": "涨幅 > 0 且量比 ≥ 1.05（放量上涨），且主力净占比 > 0 或（净占比缺失而主力净额 > 0）",
            "B": "涨幅 > 0 且量比 ≥ 1.05（放量上涨），但主力净占比 ≤ 0、或缺失且主力净额非正",
            "C": ("涨停且量比 ≤ 0.95（缩量涨停封板，买不进，不可交易）；"
                  "或涨幅 > 0 且量比 ≤ 0.95（缩量上涨/无量涨）；或 0.95 < 量比 < 1.05 的中态"),
            "D": "涨幅 < 0（放量下跌或缩量下跌）",
            "E": ("主力净占比 > +10（对倒出货特征）；或涨幅 > 0 且量比 > 2.5（过度放量上涨）"
                  "——硬风险，优先于 A/B/C/D"),
            "unknown": "涨幅或量比缺失、或量比 ≤ 0（不评估）",
        },
    },
    "volume_quadrant": {
        "type": "choice",
        "instructions": _VOLUME_QUADRANT_INSTR,
        "criteria": {
            "rise_volume": "涨幅 > 0 且量比 ≥ 1.05（放量上涨）",
            "rise_shrink": "涨幅 > 0 且量比 ≤ 0.95（缩量上涨）",
            "fall_volume": "涨幅 < 0 且量比 ≥ 1.05（放量下跌）",
            "fall_shrink": "涨幅 < 0 且量比 ≤ 0.95（缩量下跌）",
            "normal": "涨幅 = 0（平盘），或 0.95 < 量比 < 1.05 的中态",
        },
    },
}


# ── 叙事组装（纯函数；fail-visible 缺口如实注记，禁伪装）──

def _f(v: Any, nd: int = 1) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return f"{round(x, nd)}"


def _delta(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return f"{x:+.1f}"


def _i(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return str(int(round(x)))


def build_heat_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                         series: list[dict], derived: dict[str, Any],
                         market: dict | None, entry: dict, quality: dict) -> str:
    """热度维叙事（五块：出现序列/横截面衍生/市场基准/入榜/质量自标）。

    series: [{tradingDate, slot, rank, total, percentile, delta}]（跨日逐次出现，末项=判读帧）；
    derived: heat_derived() 的输出（percentile/percentileDelta/relativeToMarket/persist）；
    market: {medianPercentile, sampleCount, poolSize}；entry: {isNew, currentPercentile}；
    quality: {missingAppearances, missingFields}。
    """
    bars = sum(1 for s in series if isinstance(s.get("percentile"), (int, float)))
    head = f"{trading_date} {slot} (judgment frame) · {code} {name or ''}".rstrip()
    lines = [
        "[Attention Appearance Series · cross-day; 0-100 = attention percentile within pool; "
        "LAST = judgment frame; Δ = change vs previous appearance]",
        f"history depth: {bars} appearances"
        + (f"（<{HEAT_MIN_BARS} 次出现：percentileDelta 不可算）" if bars < HEAT_MIN_BARS else ""),
    ]
    for s in series:
        pct = s.get("percentile")
        when = f"{s.get('tradingDate') or '?'} {s.get('slot') or '?'}"
        if isinstance(pct, (int, float)):
            lines.append(f"{when}: pct {_f(pct)} "
                         f"(rank {_i(s.get('rank'))}/{_i(s.get('total'))}, Δ{_delta(s.get('delta'))})")
        else:
            lines.append(f"{when}: 缺（该次无有效出现，fail-visible）")
    d = derived or {}
    persist = d.get("persist")
    lines.append("[Cross-Section Derived · same inputs as engine trend/cross_section.py; "
                 "tier itself NOT provided]")
    lines.append(f"percentile (last appearance) = {_f(d.get('percentile'))}")
    lines.append(f"percentileDelta (last − previous appearance) = {_delta(d.get('percentileDelta'))}")
    lines.append(f"relativeToMarket (percentile − market median percentile) = "
                 f"{_delta(d.get('relativeToMarket'))}")
    lines.append("persist window mean = "
                 + (f"{_f(persist[1])} over last {persist[0]} appearances" if persist else "缺"))
    m = market or {}
    lines.append("[Market Baseline · same frame as judgment]")
    lines.append(f"market median percentile = {_f(m.get('medianPercentile'))} · "
                 f"cross-section sample count = {_i(m.get('sampleCount'))} · "
                 f"pool size = {_i(m.get('poolSize'))}")
    lines.append("[Entry]")
    lines.append(f"first appearance in series (new entry): {'yes' if entry.get('isNew') else 'no'}")
    lines.append("[Data Quality · self-reported]")
    q = quality or {}
    miss = q.get("missingAppearances") or []
    miss_fields = q.get("missingFields") or []
    lines.append(f"missing appearances: {miss if miss else 'none'} · "
                 f"missing fields: {miss_fields if miss_fields else 'none'}")
    return "\n".join([head, *lines])


def build_volume_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                           derived: dict[str, Any], quality: dict) -> str:
    """量价维叙事（三块：帧行原始事实/引擎同款衍生/质量自标）。

    derived: volume_derived() 的输出（change/volumeRatio/zlje/zljzb/directionBucket/
    limitUp/limitDown）；quality: {missingFields}。
    **不含** amountRatio（引擎生产链恒 None，本题集严格同源不用它）。
    """
    head = f"{trading_date} {slot} (judgment frame) · {code} {name or ''}".rstrip()
    lines = [
        "[Judgment Frame Raw Fields · same inputs as engine ranking/volume_price.py; "
        "score/quadrant/tier themselves NOT provided]",
        f"change (pct) = {_delta(derived.get('change'))}% · "
        f"volumeRatio = {_f(derived.get('volumeRatio'), 2)} · "
        f"zlje (main net inflow) = {_f(derived.get('zlje'), 2)} · "
        f"zljzb (main net inflow pct) = {_f(derived.get('zljzb'), 2)}%",
        "[Derived · engine-same algorithms, reproducible arithmetic only]",
        f"direction bucket score = {_f(derived.get('directionBucket'), 1)}"
        f"（涨跌幅八档方向分：涨停/跌停 ±15、7%+ ±12、5-7% ±10、3-5% ±8、"
        f"2-3% ±6、1-2% ±4、0.5-1% ±2、0-0.5% ±1、平盘 0）",
        f"limit up: {'yes' if derived.get('limitUp') else 'no'} · "
        f"limit down: {'yes' if derived.get('limitDown') else 'no'}"
        f"（涨跌停判定=引擎同款代码板块规则现算；封板=不可交易，勿当普通放量）",
        "[Data Quality · self-reported]",
    ]
    q = quality or {}
    miss_fields = q.get("missingFields") or []
    lines.append(f"missing fields: {miss_fields if miss_fields else 'none'}")
    lines.append("note: amountRatio (成交额量比) not provided — engine production chain never "
                 "computes it (observation.amountRatio is always None), this pilot stays "
                 "strictly same-source and does not use it.")
    return "\n".join([head, *lines])
