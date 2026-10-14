# -*- coding: utf-8 -*-
"""jev 涨停打标弹药纯函数层（2026-10-05 批次D I14 从 operations/jev_label_jiuyan.py 平移）。

归档边界（AGENTS §2.2 / docs/README.md 分层表）：题目常量、题集哈希、纯文本/数值计算
放 analysis（无 IO、可单测）；Mongo/TDX 取数与 jev 调用编排留 operations runner。
本文件不得新增任何 IO。runner 通过 from-import 复用并对外保持原符号名（测试/调用方无感）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.core.limit_rules import limit_ratio


# ── 常量 ──
THS_KEYS = ("one", "two", "three", "four", "high")
# 2026-10-05 批次B（原料口径，审查 I6/I7/I8）：涨停判定线精确化（×1.10/0.20/0.30/0.05，
# 旧 ×1.098 少算 1–6 分钱）、跌停家数补 ST ±5%、快照取数带 datasetId 隔离。
# 新落库文档盖 ammoVersion 戳；缺该字段的旧文档 = 旧代原料（口径未知，fail-visible），
# 用户裁决不整月重跑（旧文档留档不回写）。
# 2026-10-11 P1-1（预登记 jev-ammo-p1-preregistration.md §一）：除权修正因子入叙事
# （板序假阴根治），原料代际顺延。
AMMO_VERSION = "2026-10-11a"
DEFAULT_DATASET_ID = "dragonboard_live"

# ── 题目集（原文平移，判据改动须走改门） ──
# 考题集 §二（2026-10-03 用户逐题确认 + Q5 裁决收官 26d8ddbb）：
# 个股四题（Q1-Q3 与 v2 jev_label_jiuyan.py 逐字一致=同题锚；Q4 买盘逻辑）+ Q5 相位题拆日级独立调用（run_phase_band_day）。
QUESTIONS_STOCK = {
    "driver_type": {"type": "choice",
                    "instructions": "该股今日涨停的最主要驱动类型是哪一类？只依据所给信息打标，不预测后市。",
                    "criteria": {
                        "policy": "政策驱动：政策/规划/监管变化直接利好（国家级或地方产业政策、行业规则变化）",
                        "order_earnings": "订单业绩：订单中标、合同签署、业绩预告/财报超预期等经营实质利好",
                        "product_event": "产品事件：产品发布/技术突破/项目落地等公司产品或技术层面事件",
                        "ma_restructure": "重组并购：收购、重组、控制权变更、分拆上市等资本运作",
                        "industry_cycle": "行业周期：行业景气/价格周期驱动（涨价、供需反转、周期回暖），非单一个股事件",
                        "capital_flow": "资金接力：无明确新催化或催化本身无新意，主要由资金接力/情绪带动/板块联动上涨",
                        "concept_stretch": "蹭概念：催化与公司实际业务的实质关联弱或明显蹭热点；注意：催化所指业务若已是公司主业或已有实质承接，不应判此类（那是其他驱动类型）"}},
    "catalyst_depth": {"type": "choice",
                       "instructions": "以解析中最主要的涨停催化为准，该催化所指的业务/事件，在解析所述的公司业务版图中落在哪一层？"
                                       "依据解析中给出的收入占比、订单、项目、参股关系等证据判断，不预测后市。"
                                       "注意：供货节奏动词（研发→送样→验证→认证→小批量→批量量产→规模出货）与证据可信度规则"
                                       "（公告/定期报告最高，研报/权威媒体次之，网传/传闻/未证实仅作线索且不得支撑放量层）"
                                       "仅用于区分新业务的两层；催化所指业务若已是公司主要收入来源，无论叙事如何描述其节奏，一律判核心主业承接。"
                                       "并购重组类催化：标的公司业务与公司现有主业同业或紧密上下游按第一层判，跨行业转型按第二/三层判，"
                                       "纯控制权变更/壳资源运作且无明确业务注入按第五层判；"
                                       "解析给出收入占比/金额证据时，以大额业务为业务版图重心。",
                       "criteria": {
                           "core_main_business": "核心主业承接：催化所指业务是公司当前主要收入来源（解析明确的主业或占比最高的业务），且催化事件直接作用于该业务（政策/景气作用于它、订单落在它、产品属于它）；供货节奏描述不改变本层判定",
                           "new_business_scaling": "新业务放量承接：催化所指新业务已有越过认证线的实质证据——小批量供货、批量交付、中标、形成实质收入（周交付、订单加单、产能爬坡均属此层）；且支撑证据须为公告/定期报告/权威研报级，网传传闻级证据不得支撑本层",
                           "new_business_early": "新业务早期承接：催化所指新业务处于研发、送样、验证、认证阶段，或仅有合作意向/框架协议/网传订单；前提是催化所指业务与公司存在真实业务关系（研发/送样/认证的是公司自身或其并购/参股实体的业务）——仅靠名称/地域/概念联想的归概念组装层",
                           "equity_or_affiliate": "股权关联传导：催化主要经由参股公司、控股股东或兄弟公司、参股基金等间接传导，公司自身报表业务不直接承接",
                           "concept_assembly": "概念组装弱关联：催化与公司业务的实质联系弱——主要靠名称/地域/行业大概念联想、经营范围变更、极小规模贸易型业务等组装而成，解析所述主业与催化所指业务明显不同",
                           "insufficient_evidence": "信息不足：解析未提供足以判断催化落点的业务信息，不强行归类"}},
    "catalyst_freshness": {"type": "choice",
                           "instructions": "该股本次涨停对应的催化事件处于什么阶段？只依据所给信息打标，不预测后市。"
                                           "以解析中标注的具体日期为准判断：催化事件首次出现距今≤2 个交易日判今日新催化；"
                                           "日期不可考时才依据信息模糊程度判信息不足。",
                           "criteria": {
                               "fresh_catalyst": "今日新催化：解析日期证据显示事件首次出现距今≤2 个交易日（今日公告、今日发布、昨日盘后新消息）",
                               "continuing": "老催化续命：解析日期证据显示事件首次出现距今>2 个交易日（近 3-30 天已知事件/题材的延续发酵）",
                               "none": "无明确催化：无具体事件，主要由资金接力/情绪/板块联动带动",
                               "unclear": "信息不足：解析未提供可判断催化新旧的事件日期，不强行归类"}},
    "buy_side_logic": {"type": "choice",
                       "instructions": "该股今日涨停的最主要买盘逻辑是哪一类？只依据所给信息判断，不预测后市。",
                       "criteria": {
                           "independent_catalyst": "自身独立催化：今日涨停主要由该公司自身的公告/订单/事件驱动，解析中存在对应的具体事件行（公告、中标、业绩、产品、重组等）",
                           "sector_follow": "板块联动跟随：同板块多股今日集体异动，该股为跟随位（盘面/板块地位显示该板块今日涨停家数多，且该股封板时间偏晚）",
                           "high_board_relay": "高位卡位/情绪接力：无明确新催化，主要靠连板高度与情绪地位接续资金（身位显示 3 板及以上梯队，且解析中无新增具体事件行）",
                           "pure_sentiment": "纯情绪修复：无板块协同、无连板高度、无新增事件，属情绪性反弹"}},
}

# Q5 相位题：日级独立调用专用（C 架构=日级粗哨兵，强/非强两档实测有效，冷/弱边界信任规则分）
# 市场相位带题（jiuyanLabel 链 phase_band_daily；独立戳——v1 起戳，跨代不可比违规防范
# 对齐 I15 题集代际裁决；此前无戳=缺陷修复 2026-10-13）。
QUESTION_SET_VERSION_PHASE_BAND = "v1"
QUESTIONS_PHASE = {"phase_band": {"type": "choice",
                   "instructions": "仅依据所给盘面事实（涨停家数、炸板率、连板梯队、板块效应及各自近 20 日分位），"
                                   "判断当日市场情绪相位落在哪一档？只依据所给信息判断，不预测后市。",
                   "criteria": {
                       "cold_lt40": "冷带：情绪低迷，涨停家数/梯队高度/板块效应处于近 20 日低位区（对应情绪分 40 分线以下）",
                       "weak_40_60": "弱势带：情绪中性偏弱，涨停与梯队处于中位附近（对应情绪分 40-60）",
                       "strong_ge60": "强势带：情绪活跃偏强，涨停家数/梯队高度/板块效应处于近 20 日高位区（对应情绪分 60 分线以上）",
                       "insufficient": "证据不足：所给盘面事实不足以判断，不强行归类"}}}

# 个股相位分线题（2026-10-04 用户澄清题意后裁决试点：问该股自身本轮行情位置，非市场相位；
# 设计稿见 docs/hotlist-jev/jev-driver-label-v3-questionset.md 尾部。
# v0.5（同日用户令）：量能锚升级对比前 3 日均量+缩量/放量语义按位置与封板质量分化入题；
# 判据改动经用户裁决冻结）
QUESTIONS_STOCK_PHASE = {"stock_phase_position": {"type": "choice",
                          "instructions": "仅依据该股自身证据（价格位置轴：20 日窗口涨幅/距 20 日最高/窗口低点距今交易日数/"
                                          "近 5 日涨幅贡献/量能缩放；结构轴：近 10 日涨停序列=几天几板/断板反包；"
                                          "质量轴：当日板型=一字板/秒板硬板/炸板回封/烂板/触板未封），"
                                          "判断该股当前处在自身本轮行情相位分线的哪个位置？只判位置，不预测后市。"
                                          "判定优先级：质量示警（烂板/炸板收盘/尾盘勉强板/放巨量滞涨）的分歧位 > 位置归层。"
                                          "注意四条：①涨停日现价常即 20 日新高，距高点≈0 不能单独当高位证据；"
                                          "②位置分界看形态不只看涨幅——窗口低点距今 ≤8 日=低位新鲜（即使涨幅 30-50% 也是启动），"
                                          "≥15 日=趋势已久（即使涨幅 <50% 也算高位），中间带由量能与板型定（放量 ≥1.5 倍+强板=放量加速）；"
                                          "③单次炸板回封且封板至收盘=当日弱转强修复（中性偏多），不是分歧示警；"
                                          "④量能语义看封板质量：缩量板=一致锁定惜售（加速/一致佐证），"
                                          "放量板=换手充分——低位放量承接是健康启动、高位放量且封得稳是加速、"
                                          "放量但封不住/反复开板才是分歧出货，同位置缩量与放量结论可能不同。",
                          "criteria": {
                              "divergence": "分歧位（示警优先）：高位或趋势已久（窗口涨幅 ≥50%、3 连板+、或窗口低点距今 ≥15 日）且当日示警——"
                                            "烂板（炸板≥2 次回封）、炸板收盘（触板未封）、尾盘勉强封板、放巨量滞涨（量比 ≥1.5 倍但封不住/反复开板）；"
                                            "判例：趋势爬升一整月后的缩量首板赶顶（窗口低点距今 ≥15 日、平量/缩量）=高位分歧",
                              "climax": "高位加速（一致段）：高位（窗口涨幅 ≥50%、4 连板+、或趋势已久）且加速形态——"
                                        "放量（≥1.5 倍）强板、一字板/秒板/早封硬板、缩量加速或缩量反包（量能萎缩=一致锁定惜售）；"
                                        "高位断板反包且板型硬亦判本层；"
                                        "判例①：高位回撤后再放量强板创新高（窗口低点距今 9-14 日、量比 ≥1.5）=放量加速；"
                                        "判例②：高位断板多日后缩量硬板反包（量比 ≤0.7、秒封）=惜售一致修复",
                              "ferment": "中位发酵：窗口涨幅 30-50% 且低点距今 9-14 日且板型正常；或 2-3 连板晋级顺利",
                              "start": "低位启动：窗口低点距今 ≤8 个交易日（低位新鲜，即使窗口涨幅 30-50%）；或窗口涨幅 <30%；"
                                       "含首板突破长期平台、深回调（距 20 日最高 >20%）后反包首板；低位断板反包=启动确认归本层；"
                                       "低位放量换手板（量比 ≥1.5 倍且封得稳）=承接健康属本层；"
                                       "判例：长期平台后 4 天 2 板突破（低点距今 ≤8 日）=启动确认",
                              "insufficient": "信息不足：位置/结构/质量三轴证据均缺失（如上市窗口过短），不强行归类"}}}

# 合并同 call 题集（2026-10-04 用户裁决「真合并后再跑」）：四题原样 + 相位题原文，判据逐字不变
# （题目语义零变更仅打包方式变化——同 call 共享 narrative 输入，相位边际成本从 ≈2,420 tokens/只
# 独立调用降至题干+答案数百 tokens）。存量老文档补齐仍走单题 CLI（run_stock_phase_pilot 保留）。
QUESTIONS_STOCK_WITH_PHASE = {**QUESTIONS_STOCK, "stock_phase_position": QUESTIONS_STOCK_PHASE["stock_phase_position"]}

# 批次C I15：题目集代际戳（对齐情绪链 QUESTION_SET_VERSION 裁决）。v3.1=四题+合并相位（2026-10-04 定版）。
# 文档缺 questionSetVersion/questionSetHash = 旧代产物（判据口径未知，fail-visible），跨代不可比。
QUESTION_SET_VERSION_DRIVER = "v3.1"


def _questions_hash(questions: dict) -> str:
    """题集内容哈希（前 12 位）：判据任何一字变更即换代，比整 dict 比对轻且可索引。"""
    payload = json.dumps(questions, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def _usage_tokens(usage: Any) -> int:
    """usage → token 实付（优先 total_tokens，否则 input+output；批次C I12 统一口径）。"""
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
        return int(total)
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)

# 情绪周期段位题（questionset-review §十二，2026-10-03 用户批准 3 天试点不全量；归宿=情绪轨道，
# 试点期借打标 runner 的弹药层执行，落 hotlist_jev_cycle_stage_pilot 临时集合）。
# cycle_stage v5（2026-10-11 P2-4 预登记 jev-cycle-v5-preregistration.md §三，判据全文冻结件）：
# v1-v4 四轮不过线根因=判据引用叙事没有的证据（量能方向/全市场涨跌/大面规模三行 v4 未接线）；
# v5 = 三件套接线进叙事 + 判据只绑定叙事已有读数与近 20 日相对锚（不发明绝对阈值——
# 校准回算两打脸：C9 深谷≠cycle 冰点（08-19 崩盘日反例）、量能方向双向皆有属亚型维度）。
# 拐点日问题 v5 不承诺修（历史四轮未收敛，不在门内）。版本戳独立 v5（§四修旧债：
# v1-v4 曾共用 QUESTION_SET_VERSION_DRIVER，判据换代不动戳=跨代不可比违规）。
QUESTION_SET_VERSION_CYCLE = "v5"
QUESTIONS_CYCLE = {"cycle_stage": {"type": "choice",
                   "instructions": "以下是最近 10 个交易日的盘面序列与今日盘面事实（含量能方向、全市场涨跌、大面规模三行）。请判断：今日市场情绪处于情绪周期的哪一段？"
                                   "判段以「今日各项指标在近 10 日序列中的相对位置」为主锚（先读摆动锚：峰值距今几天决定回落段还是回升段、谷值距今几天决定是否冰点区），"
                                   "并用近 20 日分位读数（盘面事实行与量能方向行）校准当日位置。"
                                   "特别注意：冰点是稀缺事件（全月仅 1-2 次）——判冰点必须同时满足「涨停家数掉出常态带（断层）」与「池内涨跌均衡、大面未再放大」；"
                                   "量能方向只区分冰点亚型（放量崩塌后动能衰竭 vs 缩量冰封），不单独定冰点；跌停成排且大面仍在放大的日子是杀跌退潮，不是冰点。"
                                   "证据行大面积缺失（fail-visible）时选 insufficient，不强行归类。只依据所给信息判断，不预测后市。",
                   "criteria": {
                       "ebb_early": "退潮早期：涨停家数/最高板自近期峰值回落的前 1-3 天，炸板率与断板亏钱抬升，但量能未明显收缩、跌停未成排——高位股开始补跌的初段",
                       "ice_end": "冰点（退潮末期·断层日，全月仅 1-2 次）：涨停家数掉出常态带（近 20 日分位 ≤20 的断层）且池内涨跌均衡（没人买也没人卖）、大面未再放大（大面规模行读数）——量能方向行只注记亚型（放量崩塌后动能衰竭 vs 缩量冰封）不单独定冰点；反弹在即",
                       "repair": "修复启动：涨停家数自近 10 日谷值明显回升，且量能方向行转正（较昨日放量）、低位首板增多；家数/高度尚未贴近窗口峰值",
                       "ferment": "发酵主升：涨停家数与梯队连日走高（近 20 日中位区）、晋级顺畅、炸板率不高，亏钱效应收敛",
                       "climax": "高潮：涨停家数或最高板创近 10 日新高或近 20 日分位 ≥80，龙头带动，大面罕见",
                       "divergence": "高潮分歧/退潮风险：家数/高度仍在高位，但炸板率与大面骤升（大面规模行读数抬升）、或龙头烂板断板——高位放量滞涨",
                       "insufficient": "证据不足：涨停家数/量能方向/全市场涨跌/大面读数大面积缺失（fail-visible 行过多），不强行归类"}}}

# ── 纯计算 ──

def _strip(code) -> str:
    c = str(code or "")
    return c[2:] if len(c) > 2 and c[:2] in ("sh", "sz", "bj") else c


def percentile_fraction(values: list, cur) -> float | None:
    """cur 在 values（近20日历史）中的分位（0-1 小数，不含 cur 自身）。

    样本 <10 或 cur 非数返回 None（fail-visible：字段缺席由调用方按缺失呈现，
    不补 0 不伪造）。布尔显式排除（Python 里 bool 是 int 子类，True 会混进均值）。
    """
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < 10 or not isinstance(cur, (int, float)) or isinstance(cur, bool):
        return None
    return sum(1 for v in vals if v < cur) / len(vals)


def percentile_rank(values: list, cur) -> str:
    """percentile_fraction 的 0-100 整数文本形状（驱动打标事实行沿用）。

    算法唯一实现在 percentile_fraction，本函数只做展示形状换算，禁另写一套比较逻辑。
    """
    frac = percentile_fraction(values, cur)
    return "分位不可算" if frac is None else f"{frac * 100:.0f}"


def _limit_pct_of(code: str, name: str | None = None) -> float:
    """板籍涨跌幅限制（精确比例）：主板 0.10 / 创业·科创 0.20 / 北交所 0.30。

    2026-10-05 二次修正（用户裁决「阈值公共函数，禁硬编码副本」）：
    唯一权威 = core/limit_rules.limit_ratio；并撤销批次B 的 ST ±5% 特判——
    2026-09 新规主板 ST 亦 ±10%（与前端 StockUtils/规则链/快照派生一致），
    name 形参保留兼容调用方，新规下不再依赖 ST 标记。
    历史：批次B I6 已废除 ×1.098 系（容差被取整吸收成少算 1–6 分钱），
    容差统一由比较处 -1e-6 吸收。
    """
    return limit_ratio(code)


def _div_scale_map(window: list[dict], adj_prev: dict[str, float] | None) -> dict[str, float]:
    """P1-1 位置轴辅助（纯函数）：由逐日除权参考价 adj_prev 推每棒归一至今日基准的乘数。

    scale(t) = Π_{s=t+1..T} 参考价(s)/raw(s-1)（无事件链接比值=1 恒等）；adj_prev 为空
    或缺链接时该链接按 1 处理。反向递推：scale(T)=1；scale(t-1)=scale(t)×参考价(t)/raw(t-1)。
    """
    if not adj_prev or not window:
        return {}
    scale = {window[-1]["date"]: 1.0}
    for i in range(len(window) - 1, 0, -1):
        cur, prior = window[i], window[i - 1]
        ref = adj_prev.get(cur["date"])
        if (ref is None or not (isinstance(prior.get("close"), (int, float)) and prior["close"] > 0)
                or cur["date"] not in scale):
            scale[prior["date"]] = scale.get(cur["date"], 1.0)
            continue
        scale[prior["date"]] = scale[cur["date"]] * ref / prior["close"]
    return scale


def position_line_from_bars(date: str, code: str, bars: list[dict],
                            adj_prev: dict[str, float] | None = None) -> str:
    """弹药 6 行：价格位置轴原始可数锚（不给档位标签防预判，阈值锚在判据里）。
    fail-visible：TDX 不可用/缺今日棒/数据不足如实标注，不伪造数字。"""
    if not bars:
        return "个股位置：TDX 日线不可用（fail-visible，价格位置轴缺失）"
    window = [b for b in bars if b["date"] <= date]
    today = next((b for b in window if b["date"] == date), None)
    if today is None:
        return f"个股位置：{date} 无当日日线棒（停牌或数据缺口，fail-visible）"
    if len(window) < 2:
        return "个股位置：上市数据不足 2 根日线（fail-visible）"
    # P1-1 除权修正：窗口价格归一至今日基准（逐日除权参考价递推），未提供=原口径（字节不变）
    if adj_prev:
        scale = _div_scale_map(window, adj_prev)
        last20 = window[-20:]
        high20 = max(b["high"] * scale.get(b["date"], 1.0) for b in last20)
        closes20 = [b["close"] * scale.get(b["date"], 1.0) for b in last20]
        today_close = today["close"] * scale.get(date, 1.0)
        adj_note = " · 除权修正已应用"
    else:
        last20 = window[-20:]
        high20 = max(b["high"] for b in last20)
        closes20 = [b["close"] for b in last20]
        today_close = today["close"]
        adj_note = ""
    low_close = min(closes20)
    low_ago = len(closes20) - 1 - closes20.index(low_close)
    gap_pct = (high20 - today_close) / high20 * 100
    chg_pct = (today_close - low_close) / low_close * 100
    # 形态锚（v0.4 用户判例校准：位置分界看低点新鲜度不只看涨幅）
    prev5_close = closes20[-6] if len(closes20) >= 6 else closes20[0]
    contrib_pct = (today_close - prev5_close) / (today_close - low_close) * 100 \
        if today_close > low_close else None
    contrib_txt = f"{contrib_pct:.0f}%" if contrib_pct is not None else "不可算"
    # 量能锚（v0.5 用户令：对比前三日均量——缩量涨停/放量涨停语义不同）
    prev3_vols = [b["vol"] for b in last20[-4:-1]]
    avail = [v for v in prev3_vols if v > 0]
    if avail:
        base = sum(avail) / len(avail)
        ratio = today["vol"] / base
        tag = "放量" if ratio >= 1.5 else ("缩量" if ratio <= 0.7 else "平量")
        base_txt = "前 3 日均量" if len(avail) == 3 else f"前 {len(avail)} 日均量（缺 {3 - len(avail)} 日）"
        vol_txt = f"今日为{base_txt}的 {ratio:.2f} 倍（{tag}）"
    else:
        vol_txt = "前 3 日量能缺失（fail-visible）"
    note = "" if len(last20) >= 20 else f"（上市窗口仅 {len(last20)} 根）"
    return (f"个股位置：现价 {today_close:.2f} · 距 20 日最高 {high20:.2f} 差 {gap_pct:.1f}%"
            f" · 20 日窗口涨幅 {chg_pct:+.1f}%（最低收盘 {low_close:.2f}，距今 {low_ago} 个交易日）"
            f" · 近 5 日贡献 {contrib_txt}{note}"
            f" · 量能：{vol_txt}{adj_note}")


def sequence_line_from_bars(date: str, code: str, name: str | None, n: int,
                            bars: list[dict],
                            adj_prev: dict[str, float] | None = None) -> str:
    """弹药 7：近 n 日涨停序列（收盘口径，板籍阈值判定）——几天几板/断板反包（隔日弱转强）机械锚。
    fail-visible：日线缺当日棒/窗口不足如实标注。P1-1：adj_prev 提供时逐链用除权参考价
    （交易所公式精确昨收，原「除权日 prev_close 失真」已知边缘根治），None=原口径。"""
    window = [b for b in bars if b["date"] <= date]
    if not window or window[-1]["date"] != date:
        return "板序：当日日线棒缺失（fail-visible）"
    adj_note = " · 除权修正已应用" if adj_prev else ""
    seq: list[int] = []
    i = len(window) - 1
    while i >= 1 and len(seq) < n:
        prev_close = (adj_prev or {}).get(window[i]["date"]) or window[i - 1]["close"]
        up = window[i]["close"] >= round(prev_close * (1 + _limit_pct_of(code, name)), 2) - 1e-6
        seq.append(1 if up else 0)
        i -= 1
    if not seq:
        return "板序：窗口不足无法判定（fail-visible）"
    seq.reverse()
    marks = "".join("●" if v else "○" for v in seq)
    streak = 0
    for v in reversed(seq):
        if not v:
            break
        streak += 1
    rewrap = seq[-1] == 1 and (len(seq) < 2 or seq[-2] == 0) and any(seq[:-1])
    tag = " · 今日=断板反包（隔日弱转强）" if rewrap else ""
    return (f"板序：近 {len(seq)} 日 {marks}（●=涨停，末位今日） · 当前连板 {streak}"
            f" · 窗口内 {sum(seq)} 板{tag}{adj_note}")


def board_shape_line_from_bars(date: str, code: str, name: str | None,
                               prev_close: float | None, intraday: list[dict]) -> str:
    """弹药 8：当日板型（TDX 5 分钟线机械判定）——首触/炸板波次/末封/一字，烂板回封=当日弱转强。
    fail-visible：昨收缺失/5 分钟棒缺失/未触板（与涨停人口矛盾=数据缺口）如实标注。
    intraday = 未按日过滤的 5 分钟棒（本函数内过滤，保持纯函数语义）。"""
    if not prev_close or prev_close <= 0:
        return "板型：昨收缺失无法判定涨停价（fail-visible）"
    bars = [b for b in intraday if b["date"] == date]
    if not bars:
        return "板型：当日 5 分钟棒缺失（fail-visible）"
    lp = round(prev_close * (1 + _limit_pct_of(code, name)), 2)
    tol = 1e-6
    touches = [b for b in bars if b["high"] >= lp - tol]
    if not touches:
        return "板型：当日未触板（与涨停人口矛盾，数据缺口 fail-visible）"
    first_touch = touches[0]["hm"]
    sealed_flags = [b["close"] >= lp - tol for b in bars]
    waves = 0
    for k in range(1, len(sealed_flags)):
        if sealed_flags[k - 1] and not sealed_flags[k]:
            waves += 1
    sealed_to_close = bool(sealed_flags[-1])
    last_seal = next((bars[k]["hm"] for k in range(len(bars) - 1, -1, -1)
                      if sealed_flags[k]), "--")
    one_word = bars[0]["open"] >= lp - tol and all(sealed_flags)
    if one_word:
        shape = "一字板"
    elif not sealed_to_close:
        shape = "触板未封/炸板收盘"
    elif waves == 0:
        shape = "秒板/硬板（一波封住）" if first_touch <= "10:30" else "一波封住（首触偏晚）"
    elif waves == 1:
        shape = "炸板回封（当日弱转强）"
    else:
        shape = "烂板（炸板≥2 次回封）"
    return (f"当日板型：首触 {first_touch} · 炸板 {waves} 次 · 末封 {last_seal}"
            f" · {'封板至收盘' if sealed_to_close else '收盘未封'} · 板型={shape}")
