# -*- coding: utf-8 -*-
"""题材证据块（L3 消费层，2026-10-20）。

把 `jiuyan_timeline`（未来事件日历）+ `jiuyan_ai_industry`（板块级催化原文 + 热度）压成
**一段可投喂给 jev 的确定性证据块**，供「板块龙头隔日连板概率」题集使用（尚未接入打标链，
先交证据层 + 预览脚本，判据变更须预登记，见 docs/hotlist-jev/theme-leader-nextday-preregistration-20261020.md）。

设计要点：
- **确定性、无模型**：只做名字归一 + 包含匹配 + 截断，不做语义猜测；
- **fail-visible**：语料未采集 → 明说"未采集"；板块未映射 → 明说"未映射"；无未来事件 →
  明说"无（不代表无催化）"。绝不用 T-1 数据或"无催化"冒充；
- 每个事实带**来源与时间戳**（热度、内容更新日、事件录入日），让模型能判断新旧；
- 文本长度可控（`content_chars`/`max_events`），便于 token 预算。
"""
from __future__ import annotations

import re

from backend.operations import jiuyan_theme_store as S

BLOCK_HEADER = "【题材证据 · 韭研产业树 + 投资日历】"
CONTENT_CHARS = 260
EVENT_CHARS = 200
MAX_EVENTS = 3
# 「早报/复盘」是当日事件清单（含题材归因短句），不是既定日程：单独一节展示
BRIEFING_TITLES = ("早报", "盘前必读", "复盘", "收盘必读")

# 板块名归一：去掉这些后缀/噪声，便于与产业树名字对齐（只做确定性别名，不做语义泛化）
_SUFFIXES = ("概念", "板块", "指数", "行业", "主题", "题材", "产业链", "链")
# 韭研异动板块名 → 产业树/事件关键词（人工确定性别名，改这里要有据可依）
ALIASES: dict[str, tuple[str, ...]] = {
    "ST摘帽": ("ST", "摘帽"),
    "人形机器人": ("机器人",),
    "机器人": ("机器人",),
    "低空经济": ("低空", "eVTOL"),
    "光模块": ("光模块", "光通信"),
    "AI硬件": ("AI硬件", "算力"),
    "AI应用": ("AI应用", "智能体"),
    "存储": ("存储", "DRAM"),
    "固态电池": ("固态电池",),
    # 纯词汇等价（韭研异动板块名 ↔ 产业树命名差异），不含任何语义推断：
    "油气": ("石油",),
    "供热": ("供暖",),
    "AI安全": ("网络安全",),
    "出版传媒": ("传媒出版",),
}
# 明确**不做**映射的粗分桶（不是题材，映射过去会伪造板块催化）：
NOT_A_THEME = ("公告", "新股", "其他", "ST板块", "大消费", "大农业", "医药医疗")
# 产业树里不是题材的兜底节点名（名字命中即跳过，避免「其他」→「外贸-其他」这种空催化）
GENERIC_NODE_NAMES = ("其他", "杂项", "其它")


def normalize_name(name: str | None) -> str:
    s = re.sub(r"[\s\u3000（）()【】\[\]、·/]+", "", str(name or ""))
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if len(s) > len(suf) and s.endswith(suf):
                s = s[: -len(suf)]
                changed = True
    return s


def board_keywords(board_name: str | None) -> list[str]:
    """板块名 → 匹配关键词（归一后的自身 + 别名）。"""
    base = normalize_name(board_name)
    keys = [base] if base else []
    for alias in ALIASES.get(base, ()):
        a = normalize_name(alias)
        if a and a not in keys:
            keys.append(a)
    return [k for k in keys if len(k) >= 2]


def match_industry(nodes: list[dict], board_name: str | None) -> dict:
    """板块名 → 产业树节点。返回 {matched, method, node, candidates}。

    优先级：**板块本名**归一后精确相等 → 本名双向包含 → 别名包含（别名不得参与精确匹配，
    否则「AI硬件」的别名「算力」会把「算力概念」误判成 exact）。
    同层内取 level 最小、热度最高、名字最短者。
    """
    base = normalize_name(board_name)
    aliases = [normalize_name(a) for a in ALIASES.get(base, ()) if normalize_name(a)]
    if not base or base in NOT_A_THEME or not nodes:
        return {"matched": False, "method": None, "node": None, "candidates": []}
    exact, contains, alias_hits = [], [], []
    for node in nodes:
        name = normalize_name(node.get("name"))
        if not name or name in GENERIC_NODE_NAMES or name.endswith(tuple(GENERIC_NODE_NAMES)):
            continue
        if name == base:
            exact.append(node)
        elif base in name or name in base:
            contains.append(node)
        elif any(a in name or name in a for a in aliases):
            alias_hits.append(node)
    pool, method = ((exact, "exact") if exact else
                    (contains, "contains") if contains else
                    (alias_hits, "alias") if alias_hits else ([], None))
    if not pool:
        return {"matched": False, "method": None, "node": None, "candidates": []}
    pool = sorted(pool, key=lambda n: (n.get("level") or 9, -(n.get("hot") or 0),
                                       len(n.get("name") or "")))
    return {"matched": True, "method": method, "node": pool[0],
            "candidates": [n.get("name") for n in pool[:5]]}


def _days_between(a: str | None, b: str | None) -> int | None:
    from datetime import datetime
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit] + f"…[截断，原文 {len(text)} 字]"


def is_briefing(ev: dict) -> bool:
    """当日事件清单（早报/复盘）而非既定日程。"""
    title = (ev.get("title") or "").strip()
    return title in BRIEFING_TITLES or (ev.get("content") or "").startswith("1、热点事件")


def match_events(events: list[dict], board_name: str | None,
                 *, tags: tuple[str, ...] = ()) -> list[dict]:
    """事件 → 板块：标题/正文/题材标签命中关键词即算（确定性包含匹配）。"""
    keys = board_keywords(board_name) + [t for t in tags if t]
    if not keys:
        return []
    out = []
    for ev in events or []:
        haystack = f"{ev.get('title') or ''} {ev.get('content') or ''} " \
                   f"{' '.join(ev.get('themes') or [])}"
        if any(k and k in haystack for k in keys):
            out.append(ev)
    return out


def corpus_state(db, *, date: str) -> dict:
    """语料新鲜度（fail-visible 用）：最近一次采集日、条目数。"""
    tl_latest = None
    ind_latest = None
    tl_n = ind_n = 0
    try:
        tl_n = db[S.COLLECTION_TIMELINE].count_documents({})
        ind_n = db[S.COLLECTION_INDUSTRY].count_documents({})
        row = db[S.COLLECTION_TIMELINE].find_one(
            {}, {"lastFetchDate": 1}, sort=[("lastFetchDate", -1)]) or {}
        tl_latest = row.get("lastFetchDate")
        row2 = db[S.COLLECTION_INDUSTRY].find_one(
            {}, {"lastFetchDate": 1}, sort=[("lastFetchDate", -1)]) or {}
        ind_latest = row2.get("lastFetchDate")
    except Exception as exc:  # noqa: BLE001 读不到就如实报未采集，不伪造
        return {"ok": False, "error": str(exc), "timeline": 0, "industry": 0,
                "latestFetchDate": None, "stale": True}
    latest = max([d for d in (tl_latest, ind_latest) if d] or [None]) if (tl_latest or ind_latest) else None
    return {"ok": bool(latest), "timeline": tl_n, "industry": ind_n,
            "latestFetchDate": latest, "stale": latest != date, "date": date}


def build_theme_evidence_block(db, *, board_name: str, date: str,
                              window_days: int = 3, content_chars: int = CONTENT_CHARS,
                              max_events: int = MAX_EVENTS) -> dict:
    """生成题材证据块。返回 {text, industry, events, state}（text 直接可拼进叙事）。"""
    state = corpus_state(db, date=date)
    if not state.get("ok"):
        text = (f"{BLOCK_HEADER}\n韭研题材语料未采集（fail-visible：无数据 ≠ 无催化）。"
                f"请勿据此判断催化有无。")
        return {"text": text, "industry": None, "events": [], "state": state,
                "boardMapped": False, "hasContent": False, "eventCount": 0,
                "evidenceMissing": True, "evidenceMissingReason": "corpus_not_collected"}

    nodes = S.get_industry_nodes(db)
    match = match_industry(nodes, board_name)
    events_all = S.get_timeline_window(db, date=date, window_days=window_days)
    matched = match_events(events_all, board_name)
    briefings = [e for e in matched if is_briefing(e)][:1]
    events = [e for e in matched if not is_briefing(e)][:max_events]

    lines = [BLOCK_HEADER]
    stale = "" if not state.get("stale") else f"（注意：语料最近采集日 {state.get('latestFetchDate')}，非当日）"
    lines.append(f"取数日 {date}，语料 {state.get('timeline')} 条事件 / "
                 f"{state.get('industry')} 个产业节点{stale}")

    node = match.get("node")
    if not match.get("matched"):
        coarse = "（该板块属粗分桶，非题材分类）" if normalize_name(board_name) in NOT_A_THEME else ""
        lines.append(f"板块级催化：未映射{coarse}（「{board_name}」在韭研产业树无同名/包含节点；"
                     f"不代表无催化）")
    elif not (node or {}).get("content"):
        lines.append(f"板块级催化：产业树节点「{node.get('name')}」无催化正文（原文为空，如实标注）")
    else:
        chg = node.get("contentChangedDate") or "未知"
        gap = _days_between(chg, date)
        # gap<0 = 语料正文晚于取数日（只会在「用今天的语料回放历史日」时出现）——
        # 必须显式说出来：这种回放的题材证据含有未来信息，不能当离线重放结论用。
        if gap == 0:
            gap_txt = "当日"
        elif isinstance(gap, int) and gap > 0:
            gap_txt = f"{gap} 天前"
        elif isinstance(gap, int) and gap < 0:
            gap_txt = f"晚于取数日 {-gap} 天（回放含未来信息，仅作对照，不得当离线重放结论）"
        else:
            gap_txt = "未知"
        lines.append(
            f"板块级催化原文（韭研产业树「{node.get('name')}」，匹配方式 "
            f"{match.get('method')}，热度 {node.get('hot')}，正文更新 {chg}={gap_txt}）："
            f"{_clip(node.get('content'), content_chars)}")

    for bf in briefings:
        lines.append(f"当日事件清单（韭研「{bf.get('title')}」，{bf.get('date')}）："
                     f"{_clip(bf.get('content'), content_chars)}")
    if not events:
        lines.append(f"未来 {window_days} 日既定事件：无匹配（「{board_name}」相关事件未命中，"
                     f"无数据 ≠ 无催化）")
    else:
        lines.append(f"未来 {window_days} 日既定事件（韭研投资日历）：")
        for ev in events:
            fd = _days_between(date, ev.get("date"))
            when = f"{ev.get('date')}" + (f"（T+{fd}）" if isinstance(fd, int) and fd >= 0 else "")
            meta = []
            if ev.get("grade"):
                meta.append(f"重要度{ev.get('grade')}")
            if ev.get("firstSeenDate"):
                meta.append(f"录入 {ev.get('firstSeenDate')}")
            if ev.get("themes"):
                meta.append("题材:" + "/".join(ev.get("themes")[:3]))
            lines.append(f"- {when} {ev.get('title')}"
                         + (f"（{'，'.join(meta)}）" if meta else "")
                         + f"：{_clip(ev.get('content'), EVENT_CHARS)}")

    # 结构性「关键证据缺失」标志（2026-10-20 判据 v2 用）：判据层据此**代码强制** insufficient，
    # 不再只靠模型自觉（v1 实测：未映射板块的催化题判了 insufficient，但概率题仍给 0.34/0.18）。
    # 口径：未映射 > （已映射但正文空且无未来事件）。**「催化陈旧」不算缺失**——
    # stale 本身是证据（题集规则：老催化 → 判低概率），缺失才判不足。
    has_content = bool((node or {}).get("content"))
    missing_reason = None
    if not match.get("matched"):
        missing_reason = "board_unmapped"
    elif not has_content and not events:
        missing_reason = "no_content_no_event"
    return {"text": "\n".join(lines), "industry": node if match.get("matched") else None,
            "events": events, "state": state,
            "boardMapped": bool(match.get("matched")), "hasContent": has_content,
            "eventCount": len(events),
            "evidenceMissing": missing_reason is not None,
            "evidenceMissingReason": missing_reason,
            "unmappedCandidates": match.get("candidates") or []}
