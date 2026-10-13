# -*- coding: utf-8 -*-
"""行情列表五维信号 jev 复核双题集弹药纯函数层（vote_confirm + lifecycle_recheck）。

预登记（判据冻结件唯一来源）：docs/hotlist-jev/jev-vote-confirm-lifecycle-recheck-preregistration.md
（2026-10-12 用户五裁决后落方案，判据文本经用户逐字确认）。

归档边界（对齐 jev_driver_ammo/jev_relay_ammo 模式）：题目常量、叙事组装、预检 riskFlag、
对照锚映射、确定性抽样、EOD 补齐读法全部纯函数（零 IO、可单测）；Mongo 取数与 jev 调用
编排留 operations/jev_vote_confirm.py runner。本文件不得新增任何 IO。

红线：
- 判据任何一字变更=改门，须重走预登记+用户点头（判据冻结件逐字=QUESTIONS_* 代码文本，
  开火后只能文档向代码回写）；
- riskFlag 为 runner 侧预检字段（2026-10-12 用户裁决 1：数据性不足不进人口不调用，
  判读性含糊由 probabilities 平铺+confidence 低值如实表达）；
- EOD 补齐读法只补行情原始字段，不拼引擎档位（同帧一致性边界，预登记 §四）。
"""
from __future__ import annotations

from typing import Any

# ── 版本戳（预登记 §五：独立戳，cycle v5 旧债不重犯）──
# vote 题集 v4-material 代（2026-10-13 用户裁决：v1 复核内核退役，题集代际覆盖）——
# 原料重写为八块（market_facts 单一源：序列折叠/位置+板序/量价+板型/市场 as-of 11:00/
# 摆动锚/题材/质量自标/门，组装编排见 operations/jev_vote_confirm.py），人口=全热榜池，
# 判读时点=11:00 槽帧（计分口径冻结）；v1 代（引擎四维档位复核，15:00 收盘槽，候选人口）
# 留档 git 历史（f79e3a70..ee609aa1 窗口）。
QUESTION_SET_VERSION_VOTE_CONFIRM = "v4-material"
QUESTION_SET_VERSION_LIFECYCLE_RECHECK = "v1"
# 原料代际戳（本链自有：v4 起原料=八块叙事（market_facts 单一源），与打标链 AMMO_VERSION 无关）。
VOTE_AMMO_VERSION = "2026-10-13b"

# ── 题集 A：direction（方向判读，v4-material 代际 2026-10-13 用户裁决，四态，八块锚）──
# 判据与预登记 docs/hotlist-jev/jev-direction-v4-preregistration.md §五逐字一致（改门须用户点头）。
QUESTIONS_VOTE_CONFIRM: dict[str, dict] = {
    "direction": {
        "type": "choice",
        "instructions": ("以下是行情列表某股票的描述性原料——无任何预算好的档位、信号或结论。"
                         "原料八块：[序列折叠] 跨日在榜的每日最后槽注意力分位（0-100，越高越热）及日间"
                         "方向符号列、反向跳变标记、连续下跌计数，头部标注历史深度 seenDays——不足 5 个"
                         "交易日（FIRST-SEEN）时序列不作主证据；[位置] TDX 日线位置轴（距 20 日最高、"
                         "20 日窗口涨幅、窗口低点距今交易日数、近 5 日贡献、量能倍数）与板序"
                         "（近 10 日逐日涨停收盘模式，●=涨停收盘○=未收盘，末位为今日）及当前连板数；"
                         "[量价+板型] 当日盘中小涨幅、量比、主力净额与净占比、换手，若在涨停还有首封时间/"
                         "末封时间/封单量/板高；[市场 as-of 11:00] 涨停家数、炸板家数与率、大面家数、"
                         "最高板、THS 盘中三池（炸板/大面/回撤）、帧层封板质量（一字板/硬板/烂板家数、"
                         "烂板占比、平均成功率）、池涨跌家数；[摆动锚] 近 11 个交易日涨停家数峰值/谷值"
                         "（日期+距今）与今日盘中值、较昨日 Δ、距峰值；[题材] 板块归类（采集事实）；"
                         "[质量自标] 缺失字段如实列出；[门] 热榜情绪相位带（固定分线：冷 <40 / 弱 40-60 /"
                         "强 60-75 / 高峰 ≥75）、池中位 3 日分位变化、池广度。"
                         "请判断：该股在当前盘中 11:00 时点的短期方向状态读作 buy、sell、hold 还是"
                         " insufficient，附 0-1 置信度。读法锚："
                         "①序列：历史深度 ≥5 个交易日才可作主证据；FIRST-SEEN/短历史改用位置+板序+板型"
                         "路径并降置信，绝不引用未展示的历史（铁律 3）。多日同向才成趋势（看方向符号列，"
                         "不看相邻槽噪声）；逆多日方向的跳变否决该方向；连续下跌 ≥3 日是退潮证据；"
                         "往复震荡降置信。"
                         "②位置+板序：连板轨迹上升且位置低（距 20 日最高 >20% 或窗口低点距今 ≤8 日）"
                         "= 启动/扩散位；连板高度停滞或下降且高位（距最高 <10% 或低点距今 ≥15 日）= 拥挤位；"
                         "板序断板（末位由 ● 转 ○）加深回撤 = 反转位。"
                         "③量价+板型：价涨+量比 1-2.5 = 确认；量比 >2.5 的上涨 = 派发嫌疑；净占比 >+20% ="
                         " 对倒/洗盘嫌疑不是看多；净占比 ≤-10% = 派发；价跌+放量 = 最强 sell 证据；"
                         "一字板（首封=末封=09:25 且封单大）是真实但不可交易信号，永不作为 buy 证据；"
                         "烂板/反复开板/放巨量滞涨 = 分歧示警。"
                         "④市场 as-of+摆动锚：市场处于摆动锚峰值附近且炸板率/大面走高 = 退潮基调（"
                         "buy 门槛抬高、sell 证据放大）；处于谷值附近且炸板收敛 = 出清末段（不追 sell）；"
                         "市场事实缺失按缺失处理，不用情绪分替代。"
                         "⑤buy 环境门（对最终判定生效，双门 AND）：门 1 位置=启动/扩散位（连板轨迹上升"
                         "且非高位；拥挤/反转位禁 buy）；门 2 情绪相位带按固定分线查表，仅 strong 带"
                         "放行（高峰 ≥75/冷 <40/弱 40-60 拦截，被拦带的看多读数降为 hold 或携崩坏证据"
                         "降为 sell）。"
                         "⑥insufficient 仅限数据不可用（质量自标块列出的关键块缺失）；证据冲突=hold。"
                         "证据冲突或字段缺失时降置信。只依据所给信息判断，不预测后市。"),
        "criteria": {
            "buy": ("序列多日上行（历史深度 ≥5 日）且跑赢池中位；位置=启动/扩散（连板轨迹上升+非高位）；"
                    "量价确认且净占比正常；双门全过（位置门+情绪 strong 带）。"),
            "sell": ("多日下行/连跌 ≥3 日或逆势跳变否决；或高位+板型分歧（烂板/反复开板/放巨量滞涨）；"
                     "或价跌+放量/净占比 ≤-10%；或板序断板+深回撤的反转位；市场处于摆动锚峰值附近且"
                     "炸板/大面走高时放大。"),
            "hold": ("证据混合或幅度太弱；或 buy 门失败但无 sell 证据；或被拦情绪带内的看多读数降级。"),
            "insufficient": "仅数据不可用（质量自标块列出的关键块缺失）；永不因证据冲突。",
        },
    },
}

# ── 题集 B：lifecycle_stage_recheck（环境门阶段诊断复核，五段纯净，无逃生口——裁决 1）──
QUESTIONS_LIFECYCLE_RECHECK: dict[str, dict] = {
    "lifecycle_stage_recheck": {
        "type": "choice",
        "instructions": ("以下是行情列表某股票的生命周期判定原料：当日逐槽排名轨迹、生命周期度量"
                         "（排名速度/加速度/热区停留天数/近期最佳名次/距峰回撤/排名路径承诺度）、"
                         "动量与风险读数、前一交易日阶段，以及规则判读块（仅供复核）。请判断："
                         "该股当前处在自身行情生命周期的哪一段？判段以「排名轨迹的位置与走向」为主锚"
                         "（当日名次在窗口内的位置、全天走高还是走低、较昨日升降），并用动量与风险读数校准。"
                         "特别注意：①点火与扩散的分界在启动的新鲜度（排名刚自低位起升 vs 已在高位持续走强）；"
                         "②拥挤与反转的分界在高位是否出现回落证据（仍在高位区停留但未回落=拥挤，"
                         "已自峰回撤且动能转负=反转）；③降温是既无低位起升也无高位滞留/回落证据的默认态。"
                         "只依据所给信息判断，不预测后市。"),
        "criteria": {
            "ignition": ("点火：排名自低位明显起升（速度与加速度同为正，当前分位尚不高/近期最佳名次尚浅/"
                         "热区停留少）"),
            "expansion": ("扩散：排名在较高位置持续走强（速度为正且当前分位高，加速度或热区停留或最佳名次"
                          "佐证延续）"),
            "crowded": ("拥挤：排名停留高位区多日但已无上升动能（速度趋平或转负）且距峰回撤很小——高位滞留"),
            "reversal": ("反转：自近期峰值明显回撤（距峰回撤读数抬升）且动能转负（速度为负或加速大幅下行）"
                         "——高位回落"),
            "cooling": "降温：排名处于中低位且无起升证据，高位滞留与回落证据均不满足",
        },
    },
}

# ── 展示标签（叙事层中文）──
STAGE_ZH = {"ignition": "点火", "expansion": "扩散", "crowded": "拥挤",
            "reversal": "反转", "cooling": "降温"}
ACTION_ZH = {"allow": "放行", "caution": "谨慎", "veto": "一票否决", "exit_watch": "退出观察"}

# ── 对照锚（预登记 §一裁决 2 / §二·五：机械可算，冻结）──
SYNERGY_DIRECTION_MAP = {"S": "buy", "A": "buy", "B": "buy",
                         "C": "hold", "D": "sell", "E": "sell"}

VOTE_DIMS = ("resonance", "rankTrend", "crossSection", "volumePrice")

# EOD 补齐读法只补行情原始字段（预登记 §四：引擎档位不可跨帧拼接）
BACKFILL_FIELDS = ("change", "volumeRatio", "zlje", "turnoverRate", "amount")

# 档位序（抽样排序用）
TIER_RANK = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


def _finite_num(value: Any) -> float | None:
    """有限数读出：None/非数/NaN → None（fail-visible，不伪造 0）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if v == v else None


def _fmt_num(v: Any, nd: int = 2) -> str:
    n = _finite_num(v)
    return "缺" if n is None else f"{n:.{nd}f}"


# ── 预检 riskFlag（裁决 1 落地：runner 侧，开火前冻结于预登记 §二·四/§三·四）──

def lifecycle_risk_flag(trajectory_slots: int, metrics_present: bool,
                        missing: list[str]) -> dict:
    """题集 B 预检（六修，2026-10-12 用户裁决：上榜晚的股也要有周期判读）。

    data_insufficient（不调用）：当日轨迹槽 <2（无走向变化点可读）或度量块不可算；
    partial：轨迹不足全日/缺前日阶段/个别度量缺失（missing 列明，缺槽在轨迹行如实标缺）；
    ok：轨迹+度量+前日阶段齐。跨日度量（热区停留/距峰回撤）与引擎 stage 是判段主锚，
    当日轨迹槽缺（午后上榜）如实标注即可判——可计算部分照算（fail-visible）。
    """
    if trajectory_slots < 2 or not metrics_present:
        reasons = []
        if trajectory_slots < 2:
            reasons.append(f"当日轨迹槽={trajectory_slots}(<2)")
        if not metrics_present:
            reasons.append("度量块不可算")
        return {"level": "data_insufficient", "reasons": reasons}
    reasons = list(missing or [])
    if trajectory_slots < 10:
        # 归因中性化（review 2026-10-12）：缺槽原因代码不可证，不写死「午后上榜」
        reasons.append(f"当日轨迹仅{trajectory_slots}/10槽（缺槽在轨迹行如实标注）")
    return {"level": "ok" if not reasons else "partial", "reasons": reasons}


# ── 对照锚映射 ──

def synergy_direction(synergy_tier: Any) -> str:
    """synergy 档位 → 引擎投票方向（S/A/B→buy、C→hold、D/E→sell）；档位缺失返回空串不计台账。"""
    return SYNERGY_DIRECTION_MAP.get(str(synergy_tier or ""), "")


# ── 确定性抽样（预登记 §六：排序规则冻结，防挑样）──

def vote_buy_sort_key(c: dict) -> tuple:
    """buy 侧（S/A/B）：最高档位数降序 → 共振分数降序 → 代码升序。"""
    high = sum(1 for d in VOTE_DIMS if (c.get("dims") or {}).get(d) in ("S", "A"))
    return (-high, -(_finite_num(c.get("resonanceScore")) or 0.0), str(c.get("code") or ""))


def vote_sell_sort_key(c: dict) -> tuple:
    """sell 侧（D）：量价 E 短路优先 → 代码升序。"""
    vp_e = 0 if (c.get("dims") or {}).get("volumePrice") == "E" else 1
    return (vp_e, str(c.get("code") or ""))


def sample_lifecycle(cands: list[dict], cap_igex: int = 5, cap_total: int = 8) -> list[dict]:
    """点火/扩散优先全量至 ≤cap_igex（代码升序），剩余名额给拥挤/反转（stage+代码升序），
    再剩余给 cooling（include_cooling 全量覆盖时；代码升序）。"""
    igex = sorted((c for c in cands if c.get("stage") in ("ignition", "expansion")),
                  key=lambda c: str(c.get("code") or ""))
    late = sorted((c for c in cands if c.get("stage") in ("crowded", "reversal")),
                  key=lambda c: (str(c.get("stage") or ""), str(c.get("code") or "")))
    cooling = sorted((c for c in cands if c.get("stage") == "cooling"),
                     key=lambda c: str(c.get("code") or ""))
    n_igex = min(len(igex), cap_igex)
    n_late = min(len(late), max(0, cap_total - n_igex))
    return (igex[:n_igex] + late[:n_late]
            + cooling[: max(0, cap_total - n_igex - n_late)])


# ── EOD 补齐读法（裁决 3：daily 15:30 帧基准，行情字段缺失处从同日 half_hour 15:00 帧补）──

# ── 叙事组装（纯函数；fail-visible 缺口如实注记，禁伪装）──

def _traj_line(points: list[dict]) -> str:
    """轨迹行：points=[{slot|date, rank, change}]（按时间升序）→ 单行；缺如实标「缺」。
    slot=日内槽位；date=跨日日期（跨日原料，铁律 3/4 补原料方向）。"""
    parts = []
    for t in points:
        label = t.get("slot") or t.get("date") or "?"
        rank = _finite_num(t.get("rank"))
        chg = _finite_num(t.get("change"))
        rank_s = "缺" if rank is None else str(int(rank)) if float(rank).is_integer() else f"{rank:.1f}"
        chg_s = "缺" if chg is None else f"{chg:+.2f}%"
        parts.append(f"{label}:{rank_s},{chg_s}")
    return " → ".join(parts)


# 技术面事件字面值 → 中文（macd.cross/maCross.cross：golden/dead/none）
_EVENT_ZH = {"golden": "金叉", "dead": "死叉", "none": "无"}


def _event_std(v: Any) -> str:
    return _EVENT_ZH.get(str(v or ""), "无")


# 量价 direction 取值域是 up/down/neutral（_vote 语义 up≡buy、down≡sell，ranking/volume_price.py）；
# 叙事展示归一到 buy/sell/hold，与判据用词对齐（非伪造，引擎投票语义原样映射）
_DIR_STD = {"buy": "buy", "up": "buy", "sell": "sell", "down": "sell",
            "hold": "hold", "neutral": "hold"}


def _dir_std(v: Any) -> str:
    return _DIR_STD.get(str(v or ""), "无")


def _tier_reasons(reasons: Any) -> str:
    return "；".join(str(r) for r in reasons) if isinstance(reasons, list) and reasons else "无"


def build_lifecycle_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                              trajectory: list[dict], multi_day_trajectory: list[dict] | None = None,
                              metrics: dict, evidence: dict,
                              prev_stage_line: str, stage: Any, action: Any,
                              confidence: Any, reasons: Any) -> str:
    """题集 B 叙事（预登记 §三·二；跨日原料化后判据「多日/峰值」引用有可数锚）。"""
    lines = [
        f"{trading_date} 交易日 {slot} 槽 · {code} {name or ''}".rstrip(),
        f"【当日排名轨迹】（槽:名次,涨幅）{_traj_line(trajectory)}",
        (f"【近10日排名轨迹】（日:名次,涨幅）{_traj_line(multi_day_trajectory or [])}"
         if multi_day_trajectory else "【近10日排名轨迹】数据缺口（fail-visible）"),
        "【生命周期度量】（规则计算读数）",
        (f"排名速度 {_fmt_num(metrics.get('rankVelocity'), 3)} · 排名加速度 {_fmt_num(metrics.get('rankAcceleration'), 3)}"
         f" · 热区停留 {_fmt_num(metrics.get('hotZoneStreak'), 0)} 天 · 近期最佳名次 {_fmt_num(metrics.get('bestRecentRank'), 0)}"
         f" · 距峰回撤 {_fmt_num(metrics.get('drawdownFromPeak'), 2)} 位 · 路径承诺度 {_fmt_num(metrics.get('rankPathCommitment'), 3)}"),
        (f"动量与风险读数：短 {_fmt_num(evidence.get('momentumShort'))} / 中 {_fmt_num(evidence.get('momentumMid'))}"
         f" / 长 {_fmt_num(evidence.get('momentumLong'))} · 动量加速度 {_fmt_num(evidence.get('momentumAcceleration'))}"
         f" · 风险压强 {_fmt_num(evidence.get('riskPressure'), 3)}"),
        f"【前一交易日】{prev_stage_line}",
        (f"【待复核判读】规则判定（仅供复核）：阶段={STAGE_ZH.get(str(stage), stage or '缺')}"
         f" · 动作={ACTION_ZH.get(str(action), action or '缺')} · 置信={_fmt_num(confidence, 0)}"
         f" · 理由={_tier_reasons(reasons)}"),
    ]
    return "\n".join(lines)
