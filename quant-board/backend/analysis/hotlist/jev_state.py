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


def collect_slot_evidence(*, frame: dict | None, rows: list, yesterday_rows: list,
                          analysis_by_code: dict, slot_time: str) -> dict:
    """单帧原始证据聚合（纯函数，无 IO）。

    输入仅原始数据：帧（limitSummary/indices）、行情行（pctChange/zlje/rank/reason）、
    昨日行、个股生命周期 analysis（displayStatus.stage）。**零规则五档输出**。
    fail-visible：缺源记 quality.degradedSources，保持 None/缺失，不伪造 0。
    indices.change 为涨跌额点数（帧现口径，无百分比）。
    """
    from backend.analysis.hotlist.sentiment import build_yesterday_hot_limit_evidence

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

    # ── 行级：涨跌分布（五桶互斥 + 缺失计数）──
    breadth = {"total": len(rows), "limitUp": 0, "up5": 0, "up0": 0,
               "down0": 0, "down5": 0, "pctMissing": 0}
    fund = {"zljeSum": None, "zljePos": 0, "zljeNeg": 0, "zljeMissing": 0}
    fund_total = 0.0
    fund_seen = 0
    for row in rows:
        pct = row.get("pctChange")
        price, lup = row.get("price"), row.get("limitUpPrice")
        is_zt = (_finite(price) and _finite(lup) and float(price) >= float(lup) * _ZT_EPS)
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

    # ── 跨日：新进/淘汰 + 昨日涨停今日表现 ──
    today_codes = {str(row.get("code")) for row in rows if row.get("code")}
    if yesterday_rows:
        yesterday_codes = {str(row.get("code")) for row in yesterday_rows if row.get("code")}
        turnover = {"newCount": len(today_codes - yesterday_codes),
                    "droppedCount": len(yesterday_codes - today_codes)}
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
        "leaders": leaders,
        "reasons": reasons,
        "quality": {"degradedSources": degraded},
    }


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
