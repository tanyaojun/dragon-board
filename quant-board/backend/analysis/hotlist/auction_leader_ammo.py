# -*- coding: utf-8 -*-
"""竞价龙头链 vA4 题集 + 叙事行（预登记 auction-leader-vA2-preregistration-20261114，
基线 vA1）。选龙双源：KPL 09:15 推送 ∪ 竞价试盘强度板块前三（2026-11-15 用户裁决
移除韭研 T−1 龙序源——实测封板概率极低，vA4 清理身位题龙序判据）；身位题措辞
「同板推送股」→「同板入选股」（B5 换代）。

代际纪律：独立题集常量/独立 hash/独立 AMMO 戳（跨代不可比）；板块两题与催化硬度题
**原文复用 v17**（import 不复制，单一事实源）；删除 leader_headroom /
leader_rebound_popularity（A2：盘前无当日空间锚 / 事件门以收盘封板确认为前提）。

叙事行只放数据事实（AGENTS §1.2-8）：口径/窗口/判据指引一律留在代码注释与 docs；
缺数据整行缺席（None），行内字段缺位 = 缺位字段不出现（无占位符）。全部新行过
tests/hotlist/test_narrative_hygiene.py 黑名单。
"""
from __future__ import annotations

import re

from typing import Any

from backend.operations.auction_trial_derive import normalize_trial_time

_TIME_PAT = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")   # 规范 hh:mm(:ss)（finding-2 防御）
from backend.analysis.hotlist.theme_leader_ammo import (
    QUESTIONS_THEME_LEADER,
    _fmt_amount_yuan,
    _qnum,
    _questions_hash,
)

QUESTION_SET_VERSION_AUCTION_LEADER = "vA6"   # 2026-11-18 投喂文本红线清洁（用户裁决）：共享题源（题材深度/延续/硬度 instructions）随题材 v19 清洁被动变更→换代 vA6（vA5 未首烧零代际成本）；判据语义零变动。前版 vA5 = fb671c8f0223（含 B4 接线 + review 清洁度修；再前 vA4 = cd5639a7407f，跨代不可比）
AMMO_VERSION_AUCTION_LEADER = "2026-11-19a"   # 竞价三字段单一投影层（用户裁决彻底版）：净额状态门缺位整段缺席（掉池股未公布不烘 0）、额=col10 掉池前虚拟观测、换手派生；留池真 0 照出；bidLine/bidLineState 结构化字段供外科重建。题面 vA6 hash 不变。前版 2026-11-18d = 共享题材证据块「无匹配」占位行整行缺席；再前 2026-11-18c = jj_percent 权威换源（3006 存档 09:25 开盘涨幅）

# 板块级子集（原文复用 v17，一字不改）
AUCTION_SECTOR_QUESTIONS = ("theme_speculation_depth", "theme_continuation")

QUESTIONS_AUCTION_LEADER = {
    "theme_speculation_depth": QUESTIONS_THEME_LEADER["theme_speculation_depth"],
    "theme_continuation": QUESTIONS_THEME_LEADER["theme_continuation"],
    "auction_leader_seal_today": {
        "type": "choice",
        "instructions": "仅依据所给证据，判断该竞价龙头在**当日**（本交易日）继续封板"
                        "（涨停）的概率落在哪一档。只判概率档位，不预测价格、不给买卖"
                        "建议。硬规则：①锚对齐：概率中枢=「竞价封板基础率」锚行（程序"
                        "直算、随窗滚动的历史竞价龙头当日封板率）；档位偏离中枢一档以上"
                        "（上调或下调），理由必须点名锚行具体数字，并给出锚未覆盖的当日"
                        "新证据（竞价承接突变、催化硬度、身位竞争等），不得凭整体行情"
                        "乐观或悲观移动档位；锚行缺席时按在场证据判档且 confidence ≤0.6，"
                        "不得以「无历史锚」判 insufficient；②量化证据：「竞价」行（高开"
                        "幅度/竞价额/竞价换手/竞价净额/竞昨比/涨停委买额/同板对比；竞昨比="
                        "竞价额/昨日成交额，涨停委买额=一字封队强度）与「竞价试盘」行（开始/"
                        "结束试盘时点、试盘涨幅、首开额/最终额）是当日承接的两条可量化"
                        "判据源，双时点合读（时点语义与背离读法详见形态题③）。一字板分支："
                        "09:25 匹配价≈涨停限制且竞价成交/换手为零时按硬一字读法，竞价零值"
                        "是「无对手盘」而非抛压，不得作负证据，涨停委买额作封队强度证据；"
                        "可撤窗（09:20 前）结束试盘不得单独作负"
                        "证据（撤单后由真实委托承接封板是常见活板形态），须与试盘涨幅"
                        "符号/强度、最终额相对首开额的增减合读；试盘涨幅为负（end 时点"
                        "跌破昨收）可作显著负证据；试盘行缺席时回退按竞价行判据，不得"
                        "悬空引用缺席行。竞价放量高开且净额为正=承接强；竞价缩量低开或"
                        "净额大幅为负=承接弱。偏离中枢而引用时必须点名具体数字；行缺席"
                        "时不得以该行为由调档，也不得自行补 0；③催化与身位：有明确日期"
                        "与新鲜度的题材证据（产业树/题材事件·新闻/前瞻日历/板内解析）"
                        "权重高于结构特征；引用新闻须按业务/产业链关联核实；「催化硬度」"
                        "「身位」两题同调用判答可作交叉引用；④缺失门：三层证据（产业树/"
                        "题材事件·新闻/板内解析）同时缺失判 insufficient（程序强制覆盖，"
                        "原答另存备查），不得用结构特征硬填空档；⑤昨日结构事实（连板高度/"
                        "首封时点/昨日封板与否）与涨停基因行（历史打板画像）只作背景佐证，"
                        "不得单独定档。",
        "criteria": {
            "high_ge65": "高概率≥65%：竞价放量高开且净额为正（承接强），或硬一字"
                         "（09:25 匹配≈限价且成交/换手为零、涨停委买额成封队）且试盘/末帧"
                         "顶近限价；催化硬而新鲜（硬事实/当日新增题材事件·新闻/未来 1-2 日"
                         "既定事件），身位稳固或同板竞价对比领先",
            "mid_45_65": "中等 45%-65%：承接与催化一强一弱，或与锚中枢同档；典型：催化"
                         "新鲜但竞价缩量/净额为负，或竞价强但催化陈旧",
            "low_25_45": "偏低 25%-45%：竞价缩量低开或净额大幅为负（承接弱），或催化"
                         "陈旧无新增且身位被同板竞价对比挑战",
            "verylow_lt25": "很低<25%：竞价大幅低开+净额大幅流出，且题材退潮（板块判定"
                            "=退潮期/临近结束）或昨日断板今日无承接",
            "insufficient": "证据不足：三层证据（产业树/题材事件·新闻/板内解析）同时"
                            "缺失；锚行缺席本身不是 insufficient 理由",
        },
    },
    # vA3 方向解耦（裁决①：资金并入形态题判据；硬度题保留可证实性单维度）：
    # 负面硬事实（澄清公告/风险提示等公司级可证实事实）按硬事实计档，不因利空降档——
    # 方向影响由封板题/形态题合读，本题只判「有多可证实」不判方向（vA2 天普澄清案）
    "leader_catalyst_hardness": {
        **QUESTIONS_THEME_LEADER["leader_catalyst_hardness"],
        # vA5（2026-11-18 B5）：竞价叙事无爆发原因行/打标交叉行（题材链专属装配位），
        # 证据清单同步收窄防悬空引用；③交叉参考规则保留（条件式，行缺席不触发）。
        # ①继承题材 v18 驱动归因（valence 中性：是否驱动事实）；⑤方向解耦沿 vA3 裁决保留（两维正交：①判
        # 「是不是驱动事实」，⑤判「驱动事实不因利空降档」；澄清/否认类归①处理）。
        "instructions": QUESTIONS_THEME_LEADER["leader_catalyst_hardness"]["instructions"]
                        .replace("（涨停原因行/爆发原因行/板内解析/题材证据块/打标交叉行/"
                                 "公告计数行）",
                                 "（涨停原因行/板内解析/题材证据块/公告计数行）")
                        + "⑤方向解耦：负面硬事实（风险提示、股东减持等公司级可证实事实）"
                        "若为驱动事实同样按硬事实计档——硬度只判「可证实性」，不判利好"
                        "利空方向；其对封板/形态的影响由封板题与形态题合读，本题不得因"
                        "方向利空而降档至软催化（澄清/否认类按①驱动归因处理）。",
    },
    # vA5 B4（2026-11-18）：龙虎榜行接为 T−1 背景佐证（与题材身位题跨链对齐；
    # 盘前链 T−1 榜单不作当日承接确证，区别于题材盘后链身位题①点名消费）。
    "auction_seat_durability": {
        "type": "choice",
        "instructions": "仅依据所给证据（昨日梯队/结构行、同板入选股间"
                        "竞价高开与竞价额对比、热度排名行、龙虎榜行（T−1 主力净额/"
                        "席位买入/机构净买，背景佐证）、题材热度行、板块判定行），"
                        "判断该竞价龙头在板块内的**身位稳固度**——是稳固核心、被挑战，"
                        "还是可替代的接力位。只判身位性质，不预测价格、不给买卖建议。"
                        "硬规则：①判档必须点名昨日梯队领先差/同板竞价对比/"
                        "热度排名中至少一项具体事实；②同板对比中竞价额为零且高开≈限价"
                        "的入选股按一字无对手盘读，不作额落后（与封板题一字板分支同口径）；"
                        "龙虎榜行（T−1 榜单）只作背景佐证，不证明当日承接，不作定档确证；"
                        "高开幅度与竞价额均落后于同板其他入选股且无独立催化时默认 "
                        "relay_seat，除非昨日高度显著领先（领先差≥1 板）或热度排名 Top3；"
                        "③板块判定=退潮期/"
                        "临近结束时默认不得判 core_seat；④板块结构缺席且三层证据（产业树/"
                        "题材事件·新闻/板内解析）同时缺席才判 insufficient；证据部分缺位"
                        "按在场证据判档并降低置信。",
        "criteria": {
            "core_seat": "身位稳固：昨日高度领先（领先差≥1 板）或热度/催化无可替代，"
                         "且当日竞价对比不落后于同板入选股，板块判定活跃",
            "contested_seat": "身位被挑战：与同板入选股竞价对比持平或热度分流（排名非"
                              "Top3），但板块仍活跃，走向取决于开盘后卡位",
            "relay_seat": "接力位：高位卡位/情绪接力驱动、无独立催化、同板竞价对比落后，"
                          "随时可被替代",
            "insufficient": "证据不足：板块结构缺席且三层证据同时缺席；部分缺位按在场"
                            "证据判档并降低置信",
        },
    },
    # vA3 新增（预登记 §2.2，五档均为 09:25 可观测事实，不问结局；校准梯度见预登记 §1，
    # 禁嵌题面——题面随每次投喂重复注入，嵌率烧 token 且锚定偏差）
    "trial_settlement_pattern": {
        "type": "choice",
        "instructions": "仅依据所给证据（竞价试盘行：开始/结束试盘时点、试盘涨幅、首开额/"
                        "首加额/最大额/最终额、竞价成交/换手；竞价行：09:25 匹配价、竞价"
                        "成交额/换手；竞价过程事实行：首帧/峰值/末帧时点与涨幅；结构行："
                        "连板/昨日封板），判断该股当日集合竞价试盘的"
                        "**结算形态**属哪一档。形态档全部为 09:25 前可观测事实，不涉及对"
                        "日内走势或收盘的预测，不给买卖建议。硬规则：①主锚=结束试盘时点"
                        "三档（09:25:00 全匹配 / 09:20–09:25 不可撤窗 / 09:20 前可撤窗）"
                        "×试盘涨幅相对当日涨跌幅限制的强度（顶死≥95% / 一半以上 / 一半"
                        "以下 / 为负）；试盘行在场但结束试盘时点/试盘涨幅缺席（序列观测源）"
                        "时，以竞价过程事实行末帧时点/涨幅作结束试盘观测代理，confidence "
                        "≤0.6，理由须点名末帧时点；②资金姿态合读：最终额相对首开额的增减（含首加额）"
                        "只作档内合读证据——撤单后资金撤减不等于弱（试盘单退出后由真实"
                        "委托承接是常见活板形态），维持挂着不等于强，不得单凭增减定档；"
                        "③试盘涨幅是「结束试盘时点」快照、竞价行是 09:25 匹配冻结值，"
                        "两者背离本身是形态信息，合读时须分别点名时点；④试盘行缺席判 "
                        "insufficient，不得以竞价行硬填形态档。",
        "criteria": {
            "hard_oneword": "硬一字形态：结束试盘=09:25:00（竞价全程匹配）且试盘涨幅"
                            "顶近当日涨停限制，竞价行匹配价亦≈限价；试盘锚字段缺席时，"
                            "竞价行 09:25 匹配≈限价且成交/换手为零（无对手盘）+末帧涨幅"
                            "顶近限价可共证本档",
            "no_cancel_settle": "不可撤窗定型：结束试盘落在 09:20–09:25（不可撤单窗内"
                                "最后定型），试盘涨幅未顶死或试盘有反复",
            "cancel_weak": "可撤窗撤单+试盘负涨幅：结束试盘在 09:20 前，且试盘涨幅为负"
                           "（end 时点已跌破昨收）",
            "cancel_neutral": "可撤窗撤单+低强度：结束试盘在 09:20 前，试盘涨幅为正但"
                              "低于当日涨跌幅限制的一半",
            "cancel_strong": "可撤窗撤单+高强度：结束试盘在 09:20 前，但试盘涨幅不低于"
                             "当日涨跌幅限制的一半",
            "insufficient": "试盘行缺席（非涨停价试盘/榜外/采集缺席）；竞价行不能替代"
                            "试盘行定形态档",
        },
    },
}
QUESTION_SET_HASH_AUCTION_LEADER = _questions_hash(QUESTIONS_AUCTION_LEADER)
AUCTION_LEADER_KEYS = tuple(QUESTIONS_AUCTION_LEADER)
# 个股级子集（同调用判答零额外调用次数；vA3 = 4 题）
AUCTION_LEADER_QUESTIONS = ("auction_leader_seal_today", "leader_catalyst_hardness",
                            "trial_settlement_pattern", "auction_seat_durability")


# ── 叙事行（纯数据事实；None=整行缺席） ─────────────────────────────────────

def auction_push_line(entries: list[dict] | None, *,
                      codes: list[str] | None = None) -> str | None:
    """09:15 竞价看龙头推送行：推送原文 + 每股竞价涨幅（芯片 pct）。

    entries = parse_auction_push 产物 entries（升序）；codes 给出时只列相关股
    （个股级=待判股自身；板块级=板内推送股）。无条目 → None（整行缺席）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for e in entries:
        stocks = e.get("stocks") or []
        if codes is not None:
            stocks = [s for s in stocks if s.get("code") in set(codes)]
        if not stocks:
            continue
        seg = "、".join(
            f"{s.get('name') or s.get('code')} {s['pct']:+.2f}%"
            if isinstance(s.get("pct"), (int, float)) else f"{s.get('name') or s.get('code')}"
            for s in stocks)
        parts.append((f"{e.get('time')} " if e.get('time') else "") + seg)
    if not parts:
        return None
    # 时点语义标注（2026-11-13 用户裁决：09:15 试盘与 09:25 匹配两时点并存，
    # 裸并置矛盾锚致 jev 自判 insufficient——002172 当日 -10.06% vs -0.90% 实证；
    # 市场机制语义属数据事实，非口径/采集开发注释，红线 8 用户显式裁决豁免）
    return "竞价看龙头推送（09:15 试盘价）：" + "；".join(parts)


def auction_bid_line(entries: list[dict] | None) -> str | None:
    """当日集合竞价六件套行（09:25 匹配冻结；2026-11-13 用户裁决补齐六字段）：
    竞价涨幅%/竞价净额/竞价换手%/竞价成交额/竞昨比/涨停委买额 + 同板对比。

    entries = [{"label", "item", "peers"}]；item = bid 日档具名字段（bidding_pct/
    bidding_net/bidding_turnover/bidding_amount/zt_buy_amount）+ 派生
    ratio_prev_vol（竞昨比，runner 经 get_daban_prev_day_basis 原料派生）；
    peers = 同板其他入选股 [{name, pct, amount}]（对比事实，缺省不出对比段）。
    三字段状态门（2026-11-19 投影层裁决）：item 经 apply_trio 合并后，净额 None=
    未公布缺位 → 净额段整段缺席（无占位符）；**留池撮合后真 0 是事实照出**
    （「竞价净额 0」仅当 in_pool_matched 真 0）；额=公布值或 col10 掉池前虚拟
    观测、换手=公布值或派生，缺位同规则缺席。src/时点/口径只进结构化字段与
    页面 tooltip，不进叙事（红线 8）。
    信息量门槛：六字段任一可读且非 0 才出该股段；全缺 → None（整行缺席）。
    单字段缺位 = 缺位字段不出现（无占位符；2026-11-13 用户裁决：叙事禁「不可考」噪声）。
    覆盖边界与补源：bid 通道 = KPL 竞价榜 top N（max_size 百余只）；榜外入选股由
    runner 在 09:25–09:30 窗内经腾讯竞价快照补齐（source=tencent_auction），
    窗外/补源失败仍缺席 → 整行缺席 + corpusState.bidIn/bidSource 留痕，不伪造。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item")
        if not isinstance(item, dict):
            continue
        pct = _qnum(item.get("bidding_pct"))
        net = _qnum(item.get("bidding_net"))
        tur = _qnum(item.get("bidding_turnover"))
        amt = _qnum(item.get("bidding_amount"))
        ratio = _qnum(item.get("ratio_prev_vol"))
        ztb = _qnum(item.get("zt_buy_amount"))
        six = (pct, net, tur, amt, ratio, ztb)
        if not any(v is not None and v != 0 for v in six):
            continue
        seg = f"{entry.get('label') or '该股'} "
        seg += f"竞价涨幅 {pct:+.2f}%" if pct is not None else ""
        seg += f" 竞价净额 {_fmt_amount_yuan(net)}" if net is not None else ""
        seg += f" 竞价换手 {tur:g}%" if tur is not None else ""
        seg += f" 竞价成交额 {_fmt_amount_yuan(amt)}" if amt is not None else ""
        seg += f" 竞昨比 {ratio:.2f}%" if ratio is not None else ""
        seg += f" 涨停委买额 {_fmt_amount_yuan(ztb)}" if ztb is not None else ""
        peers = [p for p in (entry.get("peers") or []) if isinstance(p, dict)]
        if peers:
            # 身位题硬规则②引用「高开幅度与竞价额均落后」→ peers 额可读必须入叙事
            #（2026-11-13 review minor：判据不得引用叙事没有的证据）
            def _peer_txt(p: dict) -> str:
                # 名称缺位用代码兑底（review 2026-11-13f finding-5），名码全缺不列
                txt = str(p.get("name") or p.get("code") or "")
                if not txt:
                    return ""
                if isinstance(p.get("pct"), (int, float)):
                    txt += f" {p['pct']:+.2f}%"
                amt = _qnum(p.get("amount"))
                if amt is not None:
                    txt += f" 额 {_fmt_amount_yuan(amt)}"
                return txt
            cmp_txt = "、".join(t for t in (_peer_txt(p) for p in peers[:3]) if t)
            seg += f"；同板竞价对比 {cmp_txt}"
        parts.append(seg.strip())
    # 时点语义标注（2026-11-13 用户裁决）：与 09:15 试盘推送行区分，消解同叙事
    # 双竞价涨幅矛盾锚；市场机制语义属数据事实，非口径开发注释
    return "竞价（09:25 匹配价）：" + "；".join(parts) if parts else None


def _trial_amount(v: Any) -> str | None:
    """试盘金额：数值（元）→ 亿/万双门槛（≥1亿才用亿；试盘主力档 100万–1亿若走
    _fmt_amount_yuan 的 100万门槛会渲染成 X.XX亿 非零显零式误导，961万→0.10亿）；
    「961万」等上游串 → 原样透传；缺/0 → None。"""
    if v is None or isinstance(v, bool) or v == "" or v == 0:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f"{f / 1e8:.2f}亿" if abs(f) >= 1e8 else f"{f / 1e4:.1f}万"
    s = str(v).strip()
    return s or None


def _trial_pct(v: Any) -> str | None:
    """试盘百分：数值 → +X.XX%（涨幅）/X.XX%（换手）形态；上游串原样透传；缺/0 → None。"""
    if v is None or isinstance(v, bool) or v == "" or v == 0:
        return None
    if isinstance(v, (int, float)):
        return f"{float(v):+.2f}%"
    s = str(v).strip()
    return s or None


def _trial_turnover(v: Any) -> str | None:
    if v is None or isinstance(v, bool) or v == "" or v == 0:
        return None
    if isinstance(v, (int, float)):
        return f"{float(v):g}%"
    s = str(v).strip()
    return s or None


def bidding_series_line(facts: dict | None) -> str | None:
    """竞价过程事实行（2026-11-16 socket 序列观测值；与 WzsLinker 试盘行并列不互替）。

    facts = 逐股过程事实（kpl_bidding_series 派生：first/max/last 观测帧）。
    语义纪律（只留 docstring/结构化字段，§1.2-8 开发注释禁进行文）：first=观测首帧、
    max=委买额观测峰值、last=末帧——观测值事实，非 KPL 委托簿统计语义（首开/首加/
    撤后余额），不冒充试盘行；缺帧/缺字段整段缺席（不补 0，§红线8）；来源与时点
    溯源走 corpusState.mblState/trialState 与序列读口。
    """
    if not isinstance(facts, dict):
        return None
    def _ts(v):
        try:
            import datetime as _dt
            cst = _dt.timezone(_dt.timedelta(hours=8))   # 序列层/归档层同为 CST 口径
            return _dt.datetime.fromtimestamp(float(v), cst).strftime("%H:%M:%S")
        except (TypeError, ValueError, OSError):
            return None
    def _pct(v):
        try:
            return f"{float(v):.2f}%"
        except (TypeError, ValueError):
            return None
    def _yi(v):
        try:
            return f"{float(v) / 1e8:.2f}亿"
        except (TypeError, ValueError):
            return None
    first, mx, last = facts.get("first"), facts.get("max"), facts.get("last")
    if not first and not last:
        return None
    segs = []
    if first:
        p = _pct(first.get("bidding_pct"))
        t = _ts(first.get("ts"))
        if p and t:
            segs.append(f"首帧竞价涨幅 {p}（{t}）")
    if mx:
        y = _yi(mx.get("zt_buy_amount"))
        t = _ts(mx.get("ts"))
        if y and t:
            segs.append(f"委买额峰值 {y}（{t}）")
    if last:
        p = _pct(last.get("bidding_pct"))
        t = _ts(last.get("ts"))
        if p and t:
            segs.append(f"末帧 {p}（{t}）")
    if not segs:
        return None
    return "竞价过程事实：" + " → ".join(segs)


def auction_trial_line(trial: dict | None) -> str | None:
    """当日竞价试盘行（KPL 盯盘试盘页签 Type=7；2026-11-14c 骨架，合同定案前不接线）。

    trial = 盯盘试盘行具名字段（start_time/end_time/first_amount/first_add/
    max_amount/last_amount/jj_percent/jj_amount/jj_turnover；数值元或上游
    「961万」串均可，串原样透传）。缺位字段不出现；全缺 → None（整行缺席）。
    零值口径（review finding-8 裁决留痕）：试盘侧 0=缺席（无信息量不占位，
    §红线8 缺数据处理），与竞价侧「真零=事实」（一字板分支供给）不同，两行
    口径不同是有意设计。

    时点纪律（勘察 §4 语义警示）：jj_percent/jj_amount/jj_turnover 是 end_time
    时点快照——end_time ≥ 09:25 标「竞价全程匹配」，早于则标「{end} 时点」；
    start/end 任一缺或非 hh:mm 规范格式 → 时点不可锚，快照三列整组不出
    （review finding-2：非规范串不得参与 ≥09:25 语义比较，事实不可出）。
    语义警示：first/first_add/max/last_amount 语义待窗内与 App 同屏核对，
    只出 App 原名数值、不解释含义；pre_percent 不进叙事（结构行已覆盖昨日
    事实，交叉值走 corpusState.trialState.prevPercentCross 结构化留痕）。
    """
    if not isinstance(trial, dict):
        return None
    start = normalize_trial_time(trial.get("start_time"))
    end = normalize_trial_time(trial.get("end_time"))
    # review finding-2：时点语义（≥09:25 比较与快照注）仅对规范 hh:mm(:ss) 开放；
    # 非规范串（含未补零带冒号）不得参与字典序比较——时点不可锚 = 快照事实不可出
    canon = bool(start and _TIME_PAT.match(str(start))) and bool(end and _TIME_PAT.match(str(end)))
    amounts = "，".join(
        txt for txt in (
            _trial_amount(trial.get("first_amount")) and
            f"首开 {_trial_amount(trial.get('first_amount'))}",
            _trial_amount(trial.get("first_add")) and
            f"首加 {_trial_amount(trial.get('first_add'))}",
            _trial_amount(trial.get("max_amount")) and
            f"最大 {_trial_amount(trial.get('max_amount'))}",
            _trial_amount(trial.get("last_amount")) and
            f"最终 {_trial_amount(trial.get('last_amount'))}") if txt)
    auction_seg = None
    if canon:
        note = "竞价全程匹配" if end >= "09:25" else f"{end} 时点"
        pct = _trial_pct(trial.get("jj_percent"))
        amt = _trial_amount(trial.get("jj_amount"))
        tur = _trial_turnover(trial.get("jj_turnover"))
        parts = [p for p in (
            f"试盘涨幅 {pct}（{note}）" if pct else None,
            f"竞价成交 {amt}" if amt else None,
            f"换手 {tur}" if tur else None) if p]
        if parts:
            auction_seg = "；" + "，".join(parts)
    body = amounts + (auction_seg or "")
    if not body:
        return None
    head = "竞价试盘"
    if canon:
        head += f"（{start}–{end}）"
    elif start:
        head += f"（{start} 起）"
    return head + "：" + body


def auction_board_strength_line(board: str | None, strength: dict | None) -> str | None:
    """板块竞价强度行（第三源 trial 龙头专属，root 粗桶口径；纯数据事实）。

    strength = trialStrength 载荷（boardAmt/btier/boardTrialN）；板名/额/档/家数
    任一缺 → None（整行缺席，不留占位）。双源 leader 不出本行（口径不同不混比）。
    """
    if not board or not isinstance(strength, dict):
        return None
    amt_txt = _trial_amount(strength.get("boardAmt"))
    btier = strength.get("btier")
    n = strength.get("boardTrialN")
    if amt_txt is None or not btier or not isinstance(n, int):
        return None
    return f"板块竞价强度：{board} 试盘竞价成交 Σ{amt_txt}，强度档 {btier}，板内试盘 {n} 只"


def auction_trial_selection_line(strength: dict | None) -> str | None:
    """竞价强度入选行（第三源 trial 龙头专属；纯数据事实，无判据指引）。

    strength = trialStrength 载荷（jjRatio/jjtier/posture/rank）；严格档入选股
    posture 恒 decrease；任一字段缺/非撤减 → None（整行缺席）。
    """
    if not isinstance(strength, dict):
        return None
    ratio = strength.get("jjRatio")
    jjtier = strength.get("jjtier")
    rank = strength.get("rank")
    if (not isinstance(ratio, (int, float)) or isinstance(ratio, bool)
            or not jjtier or not isinstance(rank, int)):
        return None
    if strength.get("posture") != "decrease":
        return None
    return f"竞价强度入选：jj_ratio {ratio:g}%（{jjtier}），资金姿态撤减，板内强度排名 {rank}"


def auction_structure_line(facts: dict | None, *, prev_date: str) -> str | None:
    """昨日结构事实行（T−1 池档/龙头行直读）：高度/首封时点/昨日封板与否。

    facts = {streak, ztTime, sealedPrev, gain10}；全缺 → None（整行缺席）；
    prev_date 缺 → None（事实必随 T−1）。字段缺位 = 缺位字段不出现（无占位符）。
    """
    if not isinstance(facts, dict) or not prev_date:
        return None
    streak = facts.get("streak")
    sealed = facts.get("sealedPrev")
    zt = facts.get("ztTime")
    if streak is None and sealed is None and not zt:
        return None
    seg = f"昨日（{prev_date}）结构："
    if isinstance(streak, int):
        seg += f"连板 {streak} 板"
    if sealed is True:
        seg += "，昨日封板" + (f"（首封 {zt}）" if zt else "")
    elif sealed is False:
        seg += "，昨日未封板"
    gain = facts.get("gain10")
    if isinstance(gain, (int, float)):
        seg += f"，10 日涨幅 {gain:g}%"
    return seg


def auction_board_structure_line(members: list[dict] | None, *,
                                 prev_date: str | None) -> str | None:
    """板块级昨日结构行：板内入选股昨日封板家数 + 高度分布（纯事实）；prev_date 缺 → None。

    成员 = 双源入选股全集（推送 ∪ 竞价强度），措辞「推送 N 只」→「入选 N 只」。
    """
    if not prev_date:
        return None
    members = [m for m in (members or []) if isinstance(m, dict)]
    if not members:
        return None
    sealed_n = sum(1 for m in members if m.get("sealedPrev") is True)
    heights: dict[int, int] = {}
    for m in members:
        s = m.get("streak")
        if isinstance(s, int):
            heights[s] = heights.get(s, 0) + 1
    dist = "、".join(f"{h} 板 {n} 家" for h, n in sorted(heights.items(), reverse=True))
    seg = f"昨日（{prev_date}）板内结构：入选 {len(members)} 只，昨日封板 {sealed_n} 只"
    if dist:
        seg += f"；高度分布 {dist}"
    return seg


def auction_base_rate_line(stats: dict | None) -> str | None:
    """竞价封板基础率锚行（程序直算滚动；无已结算样本 → None 整行缺席）。

    vA4：锚行披露人群构成（推送 a/竞价强度 b；互斥优先级 auction_push >
    auction_trial_strength，trial 桶=仅竞价强度源股；vA1 旧档按推送计；
    已退役韭研龙序源历史档不计入）。
    """
    if not isinstance(stats, dict):
        return None
    n = stats.get("n")
    rate = stats.get("rate")
    if not isinstance(n, int) or n <= 0 or not isinstance(rate, (int, float)):
        return None
    comp = ""
    if isinstance(stats.get("nPush"), int):
        comp = f"：推送 {stats['nPush']}"
        if isinstance(stats.get("nTrial"), int):
            comp += f"/竞价强度 {stats['nTrial']}"
    return (f"竞价封板基础率：历史竞价龙头当日封板率 {rate:.1f}%（{n} 样本{comp}，"
            f"窗 {stats.get('start') or '?'}~{stats.get('end') or '?'}）")


def build_auction_leader_narrative(*, date: str, prev_date: str,
                                   leader_name: str, leader_code: str, board: str | None,
                                   push_line: str | None, bid_line: str | None,
                                   structure: str | None,
                                   trial_line: str | None = None,
                                   bidding_series_line: str | None = None,
                                   board_strength: str | None = None,
                                   trial_selection: str | None = None,
                                   ladder_line: str | None = None,
                                   base_rate: str | None = None,
                                   sector_judgment: str | None = None,
                                   theme_heat_line: str | None = None,
                                   gene_line: str | None = None,
                                   reason_line: str | None = None,
                                   popularity_rank_line: str | None = None,
                                   notice_count_line: str | None = None,
                                   regulatory_line: str | None = None,
                                   lhb_facts_line: str | None = None,
                                   push_board: str | None = None,
                                   evidence_block: str) -> str:
    """个股级晨间叙事（顺序固定，便于逐字复现与回归比对）。

    push_board：KPL 推送的题材炒作概念（2026-11-13 裁决：板块归属取韭研板块名，
    推送概念仅作事实并列披露，供 jev 交叉理解推送语境）。
    2026-11-18a（用户裁决，广百案例审计 B 类）：`market_line` 参数删除——昨日盘面
    事实行四题零消费且封板题①明令「不得凭整体行情乐观或悲观移动档位」（题材链
    2026-11-17a 同款判例）；板块级叙事 build_auction_sector_narrative 不受影响。
    `popularity_rank_line` 接线（身位题证据清单/Top3 例外此前悬空）：与涨停原因行
    同源 reason_corpus，零新采集；None 不出行。
    """
    belong = f"板块归属：{board}" if board else None
    lines = [f"{date} 交易日 · 竞价龙头盘前投喂"]
    lines.append(f"待判龙头：{leader_name}（{leader_code}）")
    if belong:
        if push_board and push_board != board:
            belong += f"（竞价推送概念：{push_board}）"
        lines.append(belong)
    for ln in (push_line, trial_line, bidding_series_line, board_strength, trial_selection,
               bid_line, structure, ladder_line, base_rate,
               sector_judgment, theme_heat_line, gene_line, reason_line,
               popularity_rank_line, notice_count_line, regulatory_line, lhb_facts_line):
        if ln:
            lines.append(ln)
    if evidence_block:   # review R1：空块（无内容行）不出裸头/空行
        lines.append(evidence_block)
    return "\n".join(lines)


def build_auction_sector_narrative(*, date: str, prev_date: str, market_line: str,
                                   board: str, push_line: str | None,
                                   board_structure: str | None,
                                   bid_line: str | None = None,
                                   base_rate: str | None = None,
                                   lhb_facts_line: str | None = None,
                                   reason_line: str | None = None,
                                   regulatory_line: str | None = None,
                                   evidence_block: str) -> str:
    """板块级晨间叙事（深度/延续两题；双源入选股并列事实）。"""
    lines = [f"{date} 交易日 · 竞价龙头盘前投喂"]
    if market_line:
        lines.append(f"昨日（{prev_date}）{market_line}")
    lines.append(f"待判板块：{board}")
    for ln in (push_line, board_structure, bid_line, base_rate, reason_line,
               regulatory_line, lhb_facts_line):
        if ln:
            lines.append(ln)
    if evidence_block:   # review R1：空块（无内容行）不出裸头/空行
        lines.append(evidence_block)
    return "\n".join(lines)