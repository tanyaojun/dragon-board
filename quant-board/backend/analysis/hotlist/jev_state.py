# -*- coding: utf-8 -*-
"""jev state 构建器。

历史：阶段 1（情绪回放 REJECT）与阶段 2（五维打标 REJECT）的构建器已随证伪清理
（2026-09-28，数据可再生，判定留档 hotlist-jev/*.md）；仅保留阶段 3 驱动打标所需。
2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事（纯原始证据，零规则输出，零预测问）。
fail-visible 约定见 quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §8。
"""
import math
from collections import Counter

# score 锚点：0-100 共 10 档（jev score 上限 10 档）。
# 与 services/jev/jev_client.py::SCORE_ANCHORS 同源，两侧勿单方修改。
SCORE_ANCHORS_10 = ["0", "11", "22", "33", "44", "56", "67", "78", "89", "100"]

_INDEX_KEYS = ("sh", "hs300", "zz500", "zz1000")
_LIFECYCLE_KEYS = ("ignition", "expansion", "crowded", "reversal", "cooling", "unknown")
_LEADER_LIMIT = 8
_ZT_EPS = 0.999

# 五档 criteria（边际方向语义，阶段 0 已验证表述；frame_stage/sequence_stage/day_stage 共用文案基）
_STAGE_CRITERIA = {
    "ice": "冰点：赚钱效应殆尽，涨停稀少跌停增多，普遍观望",
    "start": "启动：从弱势基线开始修复，试错资金进场，局部热点出现",
    "ferment": "发酵：赚钱效应扩散，涨停与连板增多，热点扩散",
    "climax": "高潮：全面亢奋，涨停潮普涨，拥挤明显",
    "retreat": "退潮：从强势转弱，高位股集体走弱，炸板增多",
}
_DAY_STAGE_CRITERIA = {
    "ice": "冰点：全天赚钱效应殆尽，涨停稀少跌停增多，普遍观望",
    "start": "启动：全天整体从弱势基线修复，试错资金进场",
    "ferment": "发酵：全天赚钱效应扩散，涨停与连板增多",
    "climax": "高潮：全天全面亢奋，涨停潮普涨，拥挤明显",
    "retreat": "退潮：全天从强势转弱，高位股集体走弱，炸板增多",
}
_DAY_PATTERN_CRITERIA = {
    "steady_strong": "全天强势主导（多数时段发酵/高潮）",
    "steady_weak": "全天弱势主导（多数时段退潮/冰点）",
    "rally_fade": "冲高回落：早中盘走强、尾盘转弱",
    "low_recover": "低开修复：早盘弱、盘中或尾盘修复转强",
    "wide_swing": "剧烈反复：强弱多次交替",
    "narrow_range": "窄幅平淡：无明确方向、温度低位徘徊",
    "unclear": "证据不足，无法归纳",
}


def _stage_question(instructions: str) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": dict(_STAGE_CRITERIA)}


def _score_question(instructions: str) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": list(SCORE_ANCHORS_10)}


# 槽位四问：Q1 当前帧截面 + Q2 当日连续帧序列（均五档）+ 描述性 score；零预测（无 noul）。
JEV_SLOT_QUESTIONS = {
    "frame_stage": _stage_question("仅凭【当前帧】证据，判断当前A股短线热榜情绪处于哪一档？"),
    "sequence_stage": _stage_question("结合【当日已落库连续帧】证据序列（含当前帧），判断当前情绪处于哪一档？"),
    "temperature": _score_question("当前短线情绪温度（0=彻底冰点，100=极度亢奋）"),
    "crowding": _score_question("高位拥挤度（0=无人问津，100=极度拥挤危险）"),
}

# 日级四问（盘后固定当日总体）：同样零预测。
JEV_DAY_QUESTIONS = {
    "day_stage": {
        "type": "choice", "instructions": "综合今日全天连续帧证据，今日短线热榜情绪总体处于哪一档？",
        "criteria": dict(_DAY_STAGE_CRITERIA),
    },
    "day_pattern": {
        "type": "choice", "instructions": "今日全天情绪路径属于哪种形态？",
        "criteria": dict(_DAY_PATTERN_CRITERIA),
    },
    "day_temperature": _score_question("今日全天短线情绪温度（0=彻底冰点，100=极度亢奋）"),
    "day_crowding": _score_question("今日全天高位拥挤度（0=无人问津，100=极度拥挤危险）"),
}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _calc_trin(up_count: int, down_count: int, up_turnover: float, down_turnover: float) -> float | None:
    """热榜 TRIN（Arms Index）：广度比 / 量能比。任一分母不可算返回 None（不发明数值）。"""
    if (up_count <= 0 or down_count <= 0 or up_turnover <= 0 or down_turnover <= 0):
        return None
    return round((up_count / down_count) / (up_turnover / down_turnover), 3)


def collect_slot_evidence(*, frame: dict | None, rows: list, yesterday_rows: list,
                          analysis_by_code: dict, slot_time: str) -> dict:
    """单帧原始证据聚合（纯函数，无 IO）。

    输入仅原始数据：帧（limitSummary/indices）、行情行（pctChange/zlje/rank/reason）、
    昨日行、个股生命周期 analysis（displayStatus.stage）。**零规则五档输出**。
    fail-visible：缺源记 quality.degradedSources，保持 None/缺失，不伪造 0。
    indices.change 为涨跌额点数（帧现口径，无百分比）。
    """
    from backend.analysis.hotlist.sentiment import build_yesterday_hot_limit_evidence, derive_row_flags

    degraded: list[str] = []

    # ── 帧级：指数 + 涨停/炸板/连板 ──
    indices: dict = {}
    limit = {"ztCount": None, "maxBoard": None, "boards": {},
             "zhabanCount": None, "zhabanRate": None, "fengbanRate": None}
    if frame is None:
        degraded.append("指数缺失（帧缺失）")
        degraded.append("涨停证据缺失（帧缺失）")
    else:
        frame_indices = frame.get("indices") if isinstance(frame.get("indices"), dict) else {}
        for key in _INDEX_KEYS:
            entry = frame_indices.get(key)
            if isinstance(entry, dict) and _finite(entry.get("change")):
                indices[key] = entry["change"]
        if not indices:
            degraded.append("指数缺失")
        ls = frame.get("limitSummary") if isinstance(frame.get("limitSummary"), dict) else {}
        boards = ls.get("continuousBoards") if isinstance(ls.get("continuousBoards"), dict) else {}
        zhaban = ls.get("zhaban") if isinstance(ls.get("zhaban"), dict) else {}
        limit["boards"] = {k: boards.get(k) for k in ("yiban", "erban", "sanban", "sibanPlus")}
        limit["maxBoard"] = boards.get("maxBoard") if _finite(boards.get("maxBoard")) else None
        limit["zhabanCount"] = zhaban.get("count") if _finite(zhaban.get("count")) else None
        limit["zhabanRate"] = zhaban.get("rate") if _finite(zhaban.get("rate")) else None
        limit["fengbanRate"] = zhaban.get("fengbanRate") if _finite(zhaban.get("fengbanRate")) else None
        zt = zhaban.get("ztCount") if _finite(zhaban.get("ztCount")) else None
        if zt is None and boards:
            zt = sum(int(boards.get(k) or 0) for k in ("yiban", "erban", "sanban", "sibanPlus"))
        limit["ztCount"] = zt
        if zt is None:
            degraded.append("涨停证据缺失")

    # ── 行级：涨跌分布（五桶互斥 + 缺失计数）+ 热榜 TRIN（量价确认，自算不读规则文档）──
    breadth = {"total": len(rows), "limitUp": 0, "up5": 0, "up0": 0,
               "down0": 0, "down5": 0, "pctMissing": 0}
    fund = {"zljeSum": None, "zljePos": 0, "zljeNeg": 0, "zljeMissing": 0}
    fund_total = 0.0
    fund_seen = 0
    # TRIN 原料：change>0 涨/<0 跌（与规则链同分桶），按行 turnover（成交额）分向合计；
    # TRIN = (涨家/跌家) / (涨向额/跌向额)，任一分母不可算（含单边）保持 None，不发明数值。
    trin_up_count = trin_down_count = 0
    trin_up_turnover = trin_down_turnover = 0.0
    for row in rows:
        pct = row.get("pctChange")
        price, lup = row.get("price"), row.get("limitUpPrice")
        is_zt = (_finite(price) and _finite(lup) and float(price) >= float(lup) * _ZT_EPS)
        row_turnover = row.get("turnover")
        if _finite(pct):
            pct = float(pct)
            if is_zt:
                breadth["limitUp"] += 1
            elif pct >= 5:
                breadth["up5"] += 1
            elif pct >= 0:
                breadth["up0"] += 1
            elif pct > -5:
                breadth["down0"] += 1
            else:
                breadth["down5"] += 1
            if _finite(row_turnover):
                if pct > 0:
                    trin_up_count += 1
                    trin_up_turnover += float(row_turnover)
                elif pct < 0:
                    trin_down_count += 1
                    trin_down_turnover += float(row_turnover)
        else:
            breadth["pctMissing"] += 1
        zlje = row.get("zlje")
        if _finite(zlje):
            fund_total += float(zlje)
            fund_seen += 1
            if zlje > 0:
                fund["zljePos"] += 1
            elif zlje < 0:
                fund["zljeNeg"] += 1
        else:
            fund["zljeMissing"] += 1
    if fund_seen:
        fund["zljeSum"] = fund_total
    breadth["trin"] = _calc_trin(trin_up_count, trin_down_count, trin_up_turnover, trin_down_turnover)
    breadth["upTurnover"] = round(trin_up_turnover, 2) if trin_up_turnover else None
    breadth["downTurnover"] = round(trin_down_turnover, 2) if trin_down_turnover else None

    # ── 跨日：新进/淘汰 + 昨日涨停今日表现 ──
    today_codes = {str(row.get("code")) for row in rows if row.get("code")}
    if yesterday_rows:
        yesterday_codes = {str(row.get("code")) for row in yesterday_rows if row.get("code")}
        turnover = {"newCount": len(today_codes - yesterday_codes),
                    "droppedCount": len(yesterday_codes - today_codes)}
        # top_n=None = 全池口径（有意区别于规则链的池大小截断：jev 看全量昨日涨停承接）
        yesterday_limit = build_yesterday_hot_limit_evidence(yesterday_rows, rows, None)
    else:
        turnover = {"newCount": None, "droppedCount": None}
        yesterday_limit = None
        degraded.append("昨日行缺失")

    # ── 个股生命周期分布（displayStatus.stage，与规则链 join 同源口径）──
    lifecycle = {key: 0 for key in _LIFECYCLE_KEYS}
    lifecycle_missing = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        stage = analysis.get("displayStatus", {}).get("stage") if isinstance(analysis, dict) else None
        if isinstance(stage, str) and stage in lifecycle:
            lifecycle[stage] += 1
        else:
            lifecycle_missing += 1
    if rows and lifecycle_missing == len(rows):
        degraded.append("生命周期join缺失")

    # ── 行级标记：强资确认/风险预警（derive_row_flags 唯一来源，不重写判据）──
    # 行级形态判定（强资=冷却阶段强资金且量能承接；风险=反转/冷却未确认/共振存疑且主力占比转负），
    # 是规则五档的上游特征而非档位本身；只喂计数不给比率与阈值语义（保留 jev 独立解读空间）。
    strong_money_rows = 0
    risk_rows = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        if not isinstance(analysis, dict):
            continue
        flags = derive_row_flags(analysis, row)
        if flags.get("strongMoney"):
            strong_money_rows += 1
        if flags.get("risk"):
            risk_rows += 1
    row_flags = {"strongMoney": strong_money_rows, "risk": risk_rows,
                 "judgeable": len(rows) - lifecycle_missing}

    # ── 焦点个股（热度 top）与涨停原因分布 ──
    def _sort_key(row):
        return (-(row.get("heat") or 0), row.get("rank") or 9999)

    leaders = []
    for row in sorted((r for r in rows if isinstance(r, dict)), key=_sort_key)[:_LEADER_LIMIT]:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        stage = analysis.get("displayStatus", {}).get("stage") if isinstance(analysis, dict) else None
        price, lup = row.get("price"), row.get("limitUpPrice")
        leaders.append({
            "name": row.get("name") or row.get("code"),
            "theme": row.get("mainTheme"),
            "pct": row.get("pctChange"),
            "zt": bool(_finite(price) and _finite(lup) and float(price) >= float(lup) * _ZT_EPS),
            "stage": stage if isinstance(stage, str) and stage else None,
            "heat": row.get("heat"),
        })
    reason_counter = Counter(
        str(row.get("reason")).strip() for row in rows
        if isinstance(row.get("reason"), str) and row.get("reason").strip())
    reasons = [[reason, count] for reason, count in reason_counter.most_common(5)]

    return {
        "slotTime": slot_time,
        "indices": indices,
        "limit": limit,
        "breadth": breadth,
        "fund": fund,
        "turnover": turnover,
        "yesterdayLimit": yesterday_limit,
        "lifecycle": lifecycle,
        "lifecycleMissing": lifecycle_missing,
        "rowFlags": row_flags,
        "leaders": leaders,
        "reasons": reasons,
        "quality": {"degradedSources": degraded},
    }


def _fmt_yi(value) -> str:
    """元 → 亿（带符号，2 位小数）；非数返回 缺。"""
    return f"{float(value) / 1e8:+.2f}亿" if _finite(value) else "缺"


_LIFECYCLE_NAMES = {"ignition": "点火", "expansion": "扩散", "crowded": "拥挤",
                    "reversal": "反转", "cooling": "冷却", "unknown": "未知"}
_INDEX_NAMES = {"sh": "沪指", "hs300": "沪深300", "zz500": "中证500", "zz1000": "中证1000"}


def format_evidence_line(ev: dict) -> str:
    """单帧证据压缩行（槽位已走段与日级逐帧段共用）。缺项如实写缺。"""
    parts = [str(ev.get("slotTime") or "?")]
    idx = ev.get("indices") or {}
    idx_bits = [f"{_INDEX_NAMES[k]} {idx[k]:+.2f}点" for k in _INDEX_KEYS if _finite(idx.get(k))]
    parts.append("·".join(idx_bits) if idx_bits else "指数缺")
    limit = ev.get("limit") or {}
    lim_bits = []
    if limit.get("ztCount") is not None:
        lim_bits.append(f"涨停 {int(limit['ztCount'])}")
    if limit.get("maxBoard"):
        lim_bits.append(f"最高 {int(limit['maxBoard'])} 连板")
    if limit.get("zhabanRate") is not None:
        lim_bits.append(f"炸板率 {float(limit['zhabanRate']):.0f}%")
    elif limit.get("zhabanCount") is not None:
        lim_bits.append(f"炸板 {int(limit['zhabanCount'])} 家")
    parts.append("·".join(lim_bits) if lim_bits else "涨停证据缺")
    breadth = ev.get("breadth") or {}
    breadth_bit = (f"涨跌 涨停{breadth.get('limitUp', 0)}/涨5+{breadth.get('up5', 0)}"
                   f"/涨{breadth.get('up0', 0)}/跌{breadth.get('down0', 0)}/大跌{breadth.get('down5', 0)}")
    if breadth.get("pctMissing"):
        breadth_bit += f"(缺{breadth['pctMissing']})"
    trin = breadth.get("trin")
    if trin is not None:
        breadth_bit += f"｜TRIN {float(trin):.2f}"
    parts.append(breadth_bit)
    fund = ev.get("fund") or {}
    if fund.get("zljeSum") is not None:
        fund_bit = f"主力净额 {_fmt_yi(fund['zljeSum'])}(正{fund.get('zljePos', 0)}负{fund.get('zljeNeg', 0)})"
        if fund.get("zljeMissing"):
            fund_bit += f"缺{fund['zljeMissing']}"
        parts.append(fund_bit)
    else:
        parts.append("主力净额缺")
    turnover = ev.get("turnover") or {}
    if turnover.get("newCount") is not None:
        parts.append(f"新进 {turnover['newCount']}·淘汰 {turnover['droppedCount']}")
    else:
        parts.append("新进淘汰缺")
    yl = ev.get("yesterdayLimit")
    if isinstance(yl, dict) and yl.get("count"):
        yl_bits = [f"昨涨停承接 {int(yl['count'])} 只"]
        if yl.get("avgChange") is not None:
            yl_bits.append(f"均{float(yl['avgChange']):+.2f}%")
        if yl.get("positiveRate") is not None:
            yl_bits.append(f"红盘率{float(yl['positiveRate']) * 100:.0f}%")
        parts.append("·".join(yl_bits))
    else:
        parts.append("昨涨停承接缺")
    lifecycle = ev.get("lifecycle") or {}
    parts.append("·".join(f"{_LIFECYCLE_NAMES[k]} {lifecycle.get(k, 0)}"
                          for k in ("ignition", "expansion", "crowded", "cooling")))
    row_flags = ev.get("rowFlags") or {}
    if row_flags:
        parts.append(f"强资{row_flags.get('strongMoney', 0)}·风险{row_flags.get('risk', 0)}")
    return "｜".join(parts)


def _format_current_evidence_section(ev: dict) -> str:
    lines = ["【当前帧证据】"]
    idx = ev.get("indices") or {}
    idx_bits = [f"{_INDEX_NAMES[k]} {idx[k]:+.2f}点" for k in _INDEX_KEYS if _finite(idx.get(k))]
    lines.append("指数：" + ("、".join(idx_bits) if idx_bits else "缺失"))
    limit = ev.get("limit") or {}
    boards = limit.get("boards") or {}
    lim_bits = []
    if limit.get("ztCount") is not None:
        lim_bits.append(f"涨停 {int(limit['ztCount'])} 家")
    if limit.get("maxBoard"):
        lim_bits.append(f"最高 {int(limit['maxBoard'])} 连板")
    if any(boards.get(k) is not None for k in ("yiban", "erban", "sanban", "sibanPlus")):
        lim_bits.append(f"（一板{boards.get('yiban', 0) or 0}/二板{boards.get('erban', 0) or 0}"
                        f"/三板{boards.get('sanban', 0) or 0}/四板以上{boards.get('sibanPlus', 0) or 0}）")
    if limit.get("zhabanCount") is not None:
        lim_bits.append(f"炸板 {int(limit['zhabanCount'])} 家")
    if limit.get("zhabanRate") is not None:
        lim_bits.append(f"炸板率 {float(limit['zhabanRate']):.0f}%")
    if limit.get("fengbanRate") is not None:
        lim_bits.append(f"封板率 {float(limit['fengbanRate']):.0f}%")
    lines.append("涨停与炸板：" + ("、".join(lim_bits) if lim_bits else "缺失"))
    breadth = ev.get("breadth") or {}
    missing_bit = f"（涨幅缺失 {breadth['pctMissing']}）" if breadth.get("pctMissing") else ""
    lines.append(f"涨跌分布：共 {breadth.get('total', 0)} 只——涨停 {breadth.get('limitUp', 0)}、"
                 f"涨≥5% {breadth.get('up5', 0)}、涨0~5% {breadth.get('up0', 0)}、"
                 f"跌0~5% {breadth.get('down0', 0)}、跌≥5% {breadth.get('down5', 0)}{missing_bit}")
    trin = breadth.get("trin")
    if trin is not None:
        up_t, down_t = breadth.get("upTurnover"), breadth.get("downTurnover")
        side = "涨势放量" if trin < 1 else "量价背离（涨势缩量或跌势放量）"
        lines.append(f"热榜TRIN：{float(trin):.2f}（{side}；涨向成交 {_fmt_yi(up_t)} vs 跌向成交 {_fmt_yi(down_t)}）")
    else:
        lines.append("热榜TRIN：不可算（单边或成交额缺失）")
    fund = ev.get("fund") or {}
    if fund.get("zljeSum") is not None:
        lines.append(f"主力资金：净额合计 {_fmt_yi(fund['zljeSum'])}（正 {fund.get('zljePos', 0)} 家"
                     f"/负 {fund.get('zljeNeg', 0)} 家/缺失 {fund.get('zljeMissing', 0)} 家）")
    else:
        lines.append("主力资金：缺失")
    turnover = ev.get("turnover") or {}
    if turnover.get("newCount") is not None:
        lines.append(f"新进淘汰：新进 {turnover['newCount']}、淘汰 {turnover['droppedCount']}（对比昨日）")
    else:
        lines.append("新进淘汰：缺失（昨日行缺失）")
    yl = ev.get("yesterdayLimit")
    if isinstance(yl, dict) and yl.get("count"):
        yl_bits = [f"{int(yl['count'])} 只"]
        if yl.get("avgChange") is not None:
            yl_bits.append(f"平均 {float(yl['avgChange']):+.2f}%")
        if yl.get("positiveRate") is not None:
            yl_bits.append(f"红盘率 {float(yl['positiveRate']) * 100:.0f}%")
        if yl.get("weakeningRate") is not None:
            yl_bits.append(f"转弱率 {float(yl['weakeningRate']) * 100:.0f}%")
        if yl.get("failedOrWeakRate") is not None:
            yl_bits.append(f"失败或走弱率 {float(yl['failedOrWeakRate']) * 100:.0f}%")
        lines.append("昨日涨停今日表现：" + "、".join(yl_bits))
    else:
        lines.append("昨日涨停今日表现：缺失")
    lifecycle = ev.get("lifecycle") or {}
    missing = ev.get("lifecycleMissing") or 0
    missing_bit = f"（缺失 {missing}）" if missing else ""
    lines.append("池内生命周期：" + "、".join(
        f"{_LIFECYCLE_NAMES[k]} {lifecycle.get(k, 0)}" for k in _LIFECYCLE_KEYS) + missing_bit)
    row_flags = ev.get("rowFlags") or {}
    if row_flags and row_flags.get("judgeable"):
        lines.append(f"行级标记：资金确认 {row_flags.get('strongMoney', 0)} 只（冷却阶段强资金且量能承接，攻击强度）"
                     f"/ 风险预警 {row_flags.get('risk', 0)} 只（反转、冷却未确认、或共振存疑且主力净占比转负，撤退压力）")
    leaders = ev.get("leaders") or []
    if leaders:
        leader_bits = []
        for leader in leaders:
            pct = leader.get("pct")
            bits = [str(leader.get("name") or "?"),
                    str(leader.get("theme") or "题材缺"),
                    f"{float(pct):+.2f}%" if _finite(pct) else "涨幅缺"]
            if leader.get("zt"):
                bits.append("涨停")
            if leader.get("stage"):
                bits.append(_LIFECYCLE_NAMES.get(leader["stage"], str(leader["stage"])))
            leader_bits.append("／".join(bits) + f"（热度 {leader.get('heat')}）")
        lines.append("焦点个股：" + "；".join(leader_bits))
    reasons = ev.get("reasons") or []
    if reasons:
        lines.append("涨停原因：" + "、".join(f"{reason} ×{count}" for reason, count in reasons))
    return "\n".join(lines)


def build_slot_jev_state(*, trading_date: str, slot_time: str, current: dict,
                         priors: list, missing_slots: list | None = None) -> str:
    """槽位叙事 state（Q1 当前帧 + Q2 当日序列共用一次调用的输入）。

    priors = 当日早于本槽各帧的 evidence（升序）；missing_slots = 预期槽位中无帧的槽。
    零规则输出：输入输出均不含规则五档/摘要/信号。
    """
    degraded = list((current.get("quality") or {}).get("degradedSources") or [])
    if missing_slots:
        degraded.append("缺失槽位：" + "、".join(missing_slots))
    prior_lines = [format_evidence_line(ev) for ev in priors if isinstance(ev, dict)]
    lines = [
        f"{trading_date} {slot_time} 时点快照（A股短线热榜情绪观察，原始市场证据）。",
        _format_current_evidence_section(current),
        "【当日已走帧证据】\n" + ("\n".join(prior_lines) if prior_lines else "（本日暂无更早已落库帧）"),
        "【数据质量】" + ("；".join(degraded) if degraded else "无缺失") + "。",
    ]
    return "\n".join(lines)[:4000]


def build_day_jev_state(*, trading_date: str, evidences: list) -> str:
    """日级叙事 state（盘后固定当日总体）。evidences = 全日各帧 evidence 升序。"""
    if not evidences:
        return f"{trading_date} 交易日全天热榜情绪证据轨迹：无帧证据。"
    degraded: list[str] = []
    for ev in evidences:
        for item in (ev.get("quality") or {}).get("degradedSources") or []:
            if item not in degraded:
                degraded.append(item)
    last = evidences[-1]
    turnover = last.get("turnover") or {}
    fund = last.get("fund") or {}
    max_board = max(((ev.get("limit") or {}).get("maxBoard") or 0)
                    for ev in evidences if isinstance(ev, dict))
    new_bit = f"新进 {turnover['newCount']}" if turnover.get("newCount") is not None else "新进 缺"
    dropped_bit = f"淘汰 {turnover['droppedCount']}" if turnover.get("droppedCount") is not None else "淘汰 缺"
    lines = [
        f"{trading_date} 交易日全天热榜情绪证据轨迹（A股短线情绪观察，原始市场证据）。",
        "【逐帧证据】\n" + "\n".join(format_evidence_line(ev) for ev in evidences if isinstance(ev, dict)),
        f"【当日累计】{new_bit}、{dropped_bit}（对比昨日）；主力净额合计 {_fmt_yi(fund.get('zljeSum'))}；"
        f"最高连板峰值 {int(max_board)} 板",
        "【数据质量】" + ("；".join(degraded) if degraded else "无缺失") + "。",
    ]
    return "\n".join(lines)[:6000]


def _tag_names(tags) -> list:
    """tags 兼容两种形态：[{Name:...}] 对象数组或字符串数组。"""
    out = []
    for t in tags or []:
        if isinstance(t, dict) and t.get("Name"):
            out.append(str(t["Name"]))
        elif isinstance(t, str) and t:
            out.append(t)
    return out


def build_driver_label_narrative(ths_reason: str, row: dict, mappings: list) -> str:
    """涨停驱动打标叙事：THS 涨停原因 + 行业/题材上下文 + 业务底座映射（≤4 条）。

    映射缺失时如实输出"无题材映射记录"（该缺失本身是判别信号）。
    """
    name = row.get("name") or row.get("code") or "未知"
    head = f"{name}（{row.get('mainTheme') or '行业未标注'}，热榜第{row.get('rank')}名）：今日涨停原因：{ths_reason}。"
    segs = []
    for m in (mappings or [])[:4]:
        theme = m.get("themeName") or m.get("themeId") or "未知题材"
        tags = "/".join(_tag_names(m.get("tags")))
        reason = str(m.get("reason") or "")[:60]
        segs.append(f"【{theme}】{('标签:' + tags + '；') if tags else ''}{reason}")
    base = "；".join(segs) if segs else "无题材映射记录"
    return f"{head}公司业务底座（题材映射）：{base}。"[:1200]
