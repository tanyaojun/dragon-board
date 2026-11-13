# -*- coding: utf-8 -*-
"""竞价龙头链 vA1 题集 + 叙事行（预登记 auction-leader-vA1-preregistration-20261113）。

代际纪律：独立题集常量/独立 hash/独立 AMMO 戳（跨代不可比）；板块两题与催化硬度题
**原文复用 v17**（import 不复制，单一事实源）；删除 leader_headroom /
leader_rebound_popularity（A2：盘前无当日空间锚 / 事件门以收盘封板确认为前提）。

叙事行只放数据事实（AGENTS §1.2-8）：口径/窗口/判据指引一律留在代码注释与 docs；
缺数据整行缺席（None），行内字段缺位 = 缺位字段不出现（无占位符）。全部新行过
tests/hotlist/test_narrative_hygiene.py 黑名单。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.theme_leader_ammo import (
    QUESTIONS_THEME_LEADER,
    _fmt_amount_yuan,
    _qnum,
    _questions_hash,
)

QUESTION_SET_VERSION_AUCTION_LEADER = "vA1"
AMMO_VERSION_AUCTION_LEADER = "2026-11-13f"   # review 修复（卫生/渲染/缺席口径，供给换代）

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
                        "幅度/竞价额/竞价换手/竞价净额/同板对比）是当日承接的唯一可量化"
                        "判据源——竞价放量高开且净额为正=承接强；竞价缩量低开或净额大幅"
                        "为负=承接弱。偏离中枢而引用时必须点名具体数字；行缺席"
                        "时不得以该行为由调档，也不得自行补 0；③催化与身位：有明确日期"
                        "与新鲜度的题材证据（产业树/题材事件·新闻/前瞻日历/板内解析）"
                        "权重高于结构特征；引用新闻须按业务/产业链关联核实；「催化硬度」"
                        "「身位」两题同调用判答可作交叉引用；④缺失门：三层证据（产业树/"
                        "题材事件·新闻/板内解析）同时缺失判 insufficient（程序强制覆盖，"
                        "原答另存备查），不得用结构特征硬填空档；⑤昨日结构事实（连板高度/"
                        "首封时点/昨日封板与否）只作背景佐证，不得单独定档。",
        "criteria": {
            "high_ge65": "高概率≥65%：竞价放量高开且净额为正（承接强），催化硬而新鲜"
                         "（硬事实/当日新增题材事件·新闻/未来 1-2 日既定事件），身位稳固"
                         "或同板竞价对比领先",
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
    "leader_catalyst_hardness": QUESTIONS_THEME_LEADER["leader_catalyst_hardness"],
    "auction_seat_durability": {
        "type": "choice",
        "instructions": "仅依据所给证据（昨日梯队/结构行、同板推送股间竞价高开与竞价额"
                        "对比、热度排名行、题材热度行、板块判定行），判断该竞价龙头在"
                        "板块内的**身位稳固度**——是稳固核心、被挑战，还是可替代的接力位。"
                        "只判身位性质，不预测价格、不给买卖建议。硬规则：①判档必须点名"
                        "昨日梯队领先差/同板竞价对比/热度排名中至少一项具体事实；②同板"
                        "竞价对比高开幅度与竞价额均落后于同板其他推送股且无独立催化时"
                        "默认 relay_seat，除非昨日高度显著领先（领先差≥1 板）或热度排名"
                        "Top3；③板块判定=退潮期/临近结束时默认不得判 core_seat；④板块"
                        "结构缺席且三层证据（产业树/题材事件·新闻/板内解析）同时缺席"
                        "才判 insufficient；证据部分缺位按在场证据判档并降低置信。",
        "criteria": {
            "core_seat": "身位稳固：昨日高度领先（领先差≥1 板）或热度/催化无可替代，"
                         "且当日竞价对比不落后于同板推送股，板块判定活跃",
            "contested_seat": "身位被挑战：与同板推送股竞价对比持平或热度分流（排名非"
                              "Top3），但板块仍活跃，走向取决于开盘后卡位",
            "relay_seat": "接力位：高位卡位/情绪接力驱动、无独立催化、同板竞价对比落后，"
                          "随时可被替代",
            "insufficient": "证据不足：板块结构缺席且三层证据同时缺席；部分缺位按在场"
                            "证据判档并降低置信",
        },
    },
}
QUESTION_SET_HASH_AUCTION_LEADER = _questions_hash(QUESTIONS_AUCTION_LEADER)
AUCTION_LEADER_KEYS = tuple(QUESTIONS_AUCTION_LEADER)
# 个股级子集（同调用判答零额外调用次数）
AUCTION_LEADER_QUESTIONS = ("auction_leader_seal_today", "leader_catalyst_hardness",
                            "auction_seat_durability")


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
    return "竞价看龙头推送：" + "；".join(parts)


def auction_bid_line(entries: list[dict] | None) -> str | None:
    """当日集合竞价六件套行（9:25 冻结；2026-11-13 用户裁决补齐六字段）：
    竞价涨幅%/竞价净额/竞价换手%/竞价成交额/竞昨比/涨停委买额 + 同板对比。

    entries = [{"label", "item", "peers"}]；item = bid 日档具名字段（bidding_pct/
    bidding_net/bidding_turnover/bidding_amount/zt_buy_amount）+ 派生
    ratio_prev_vol（竞昨比，runner 经 get_daban_prev_day_basis 原料派生）；
    peers = 同板其他推送股 [{name, pct, amount}]（对比事实，缺省不出对比段）。
    信息量门槛：六字段任一可读且非 0 才出该股段；全缺 → None（整行缺席）。
    单字段缺位 = 缺位字段不出现（无占位符；2026-11-13 用户裁决：叙事禁「不可考」噪声）。
    覆盖边界与补源：bid 通道 = KPL 竞价榜 top N（max_size 百余只）；榜外推送股由
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
    return "竞价：" + "；".join(parts) if parts else None


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
    """板块级昨日结构行：板内推送股昨日封板家数 + 高度分布（纯事实）；prev_date 缺 → None。"""
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
    seg = f"昨日（{prev_date}）板内结构：推送 {len(members)} 只，昨日封板 {sealed_n} 只"
    if dist:
        seg += f"；高度分布 {dist}"
    return seg


def auction_base_rate_line(stats: dict | None) -> str | None:
    """竞价封板基础率锚行（程序直算滚动；无已结算样本 → None 整行缺席）。"""
    if not isinstance(stats, dict):
        return None
    n = stats.get("n")
    rate = stats.get("rate")
    if not isinstance(n, int) or n <= 0 or not isinstance(rate, (int, float)):
        return None
    return (f"竞价封板基础率：历史竞价龙头当日封板率 {rate:.1f}%（{n} 样本，"
            f"窗 {stats.get('start') or '?'}~{stats.get('end') or '?'}）")


def build_auction_leader_narrative(*, date: str, prev_date: str, market_line: str,
                                   leader_name: str, leader_code: str, board: str | None,
                                   push_line: str | None, bid_line: str | None,
                                   structure: str | None,
                                   ladder_line: str | None = None,
                                   base_rate: str | None = None,
                                   sector_judgment: str | None = None,
                                   theme_heat_line: str | None = None,
                                   gene_line: str | None = None,
                                   reason_line: str | None = None,
                                   notice_count_line: str | None = None,
                                   lhb_facts_line: str | None = None,
                                   push_board: str | None = None,
                                   evidence_block: str) -> str:
    """个股级晨间叙事（顺序固定，便于逐字复现与回归比对）。

    push_board：KPL 推送的题材炒作概念（2026-11-13 裁决：板块归属取韭研板块名，
    推送概念仅作事实并列披露，供 jev 交叉理解推送语境）。
    """
    belong = f"板块归属：{board}" if board else None
    lines = [f"{date} 交易日 · 竞价龙头盘前投喂"]
    if market_line:
        lines.append(f"昨日（{prev_date}）{market_line}")
    lines.append(f"待判龙头：{leader_name}（{leader_code}）")
    if belong:
        if push_board and push_board != board:
            belong += f"（竞价推送概念：{push_board}）"
        lines.append(belong)
    for ln in (push_line, bid_line, structure, ladder_line, base_rate,
               sector_judgment, theme_heat_line, gene_line, reason_line,
               notice_count_line, lhb_facts_line):
        if ln:
            lines.append(ln)
    lines.append(evidence_block)
    return "\n".join(lines)


def build_auction_sector_narrative(*, date: str, prev_date: str, market_line: str,
                                   board: str, push_line: str | None,
                                   board_structure: str | None,
                                   bid_line: str | None = None,
                                   base_rate: str | None = None,
                                   lhb_facts_line: str | None = None,
                                   reason_line: str | None = None,
                                   evidence_block: str) -> str:
    """板块级晨间叙事（深度/延续两题；双龙一/多推送股并列事实）。"""
    lines = [f"{date} 交易日 · 竞价龙头盘前投喂"]
    if market_line:
        lines.append(f"昨日（{prev_date}）{market_line}")
    lines.append(f"待判板块：{board}")
    for ln in (push_line, board_structure, bid_line, base_rate, reason_line,
               lhb_facts_line):
        if ln:
            lines.append(ln)
    lines.append(evidence_block)
    return "\n".join(lines)