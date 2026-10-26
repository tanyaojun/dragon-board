# -*- coding: utf-8 -*-
"""题材证据块（L3 消费层；2026-10-23 v4 换源）。

把 **韭研产业树**（板块级催化原文 + 热度，`jiuyan_ai_industry`）+ **开盘啦题材语料**
（题材事件 `kpl_topic_events` / 题材新闻 `kpl_theme_news`（Kword 题材标签）/ 前瞻日历
`kpl_theme_calendar`）+ **韭研异动板内解析**（L2，`jiuyan_action`）压成一段可投喂给
jev 的确定性证据块，供「板块龙头隔日连板概率」题集使用。

**换源裁决（2026-10-23，方案 A）**：事件层唯一权威源 = 开盘啦；韭研 timeline（投资日历+
早报）退役（重叠实测：KPL 日历是韭研超集、事件粒度更强、新闻流为韭研所无——
见 `docs/hotlist-jev/theme-corpus-extra-sources-survey-20261023.md` §8）。
产业树与板内解析无 KPL 对应物，保留韭研。每类语料一个权威源。

设计要点：
- **确定性、无模型**：只做名字归一 + 包含匹配 + 共享子串锚（≥2 字含汉字）+ 截断，
  不做语义猜测；Kword 题材标签是开盘啦现成的「事件→题材」关联，优先消费；
- **fail-visible**：语料未采集 → 明说"未采集"；板块未映射 → 明说"未映射"；无未来事件 →
  明说"无（不代表无催化）"。绝不用 T-1 数据或"无催化"冒充；
- 每个事实带**来源与时间戳**（来源媒体、热度、事件日期），让模型能判断新旧；
- 文本长度可控（`content_chars`/`max_events`），便于 token 预算。
"""
from __future__ import annotations

import re

from backend.operations import jiuyan_theme_store as S
from backend.operations import kpl_theme_store as KS

BLOCK_HEADER = "【题材证据 · 韭研产业树 + 开盘啦题材事件/新闻/日历】"
CONTENT_CHARS = 260
EVENT_CHARS = 200
MAX_EVENTS = 3
EVENT_WINDOW_PAST_DAYS = 3      # 事件/新闻回看窗口（发酵中）
NEWS_WINDOW_PAST_DAYS = 2
# 热度序列窗（S2，2026-10-24b：5→10 日——「断流/见顶回落」判据需要更长窗才看得出
# 趋势拐点；库内不足的日子自然为 0，fail-visible 不伪造）
HEAT_WINDOW_DAYS = 10

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
# 明确**不做**映射的粗分桶（不是题材，映射过去会伪造板块催化）；「医疗医药」与
# 「医药医疗」为韭研同一粗分桶的字序变体（2026-10-22 归因实测漏收，有据收录）。
# 2026-10-26 用户裁决摘除四个「大X」域桶（大消费/大农业/医药医疗/医疗医药）：它们是
# 真实题材域（韭研只是没给产业树节点），S3 驱动标签补充映射（2026-10-24b）上线后
# 七桶 evidenceMissing 实测全 False——v3 收紧「门控率 100%/49/49 自判 insufficient」
# 的前提失效；10-26 大消费龙头上海九百 4 板（当日最高板）漏判实锤。预登记 §20。
NOT_A_THEME = ("公告", "新股", "其他", "ST板块")
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


# 驱动标签第二匹配通道的候选词切分（S3，2026-10-24b）：韭研 expound 首行按分隔符
# 确定性切词（**非语义分词**），剔泛词黑名单与 <2 字碎片。动机（10-24 置信度归因）：
# 板块名命中宽父节点（「半导体」）或未映射（「俄乌重建」）时，龙头驱动标签里的具体
# 驱动（「存储芯片」「金矿」「华为昇腾」）可补对口产业树节点——真实扫描 10-22/23
# 共 14 只 fire 9 只。边界如实披露：标签词与节点名无字面子串关系时不触发（如「证券」
# ↔层级命名「金融-券商」），不编语义别名；对口内容由板内解析 expound 承载。
_TAG_SPLIT_RE = re.compile(r"[＋+、，,/｜|｜\s（）()【】\[\]]+")


def _tag_terms(tag_line: str | None, limit: int = 3) -> list[str]:
    """「人形机器人（金属腱绳）+商业航天+光伏」→ [人形机器人, 金属腱绳, 商业航天]…（取前 limit）。"""
    out: list[str] = []
    for seg in _TAG_SPLIT_RE.split(str(tag_line or "")):
        w = normalize_name(seg)
        if len(w) >= 2 and w not in GENERIC_ANCHORS and w not in NOT_A_THEME and w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


# ── 确定性关联锚（v3 引入，v4 沿用；早报段落匹配的通用化） ─────────────────
# 背景：完整板块名子串匹配不上语义同源的事件（「俄乌重建」vs「俄乌和平」）。
# 规则：①含式命中（关键词 ⊆ 归一文本）；②最长公共连续子串 ≥2 字且含 ≥1 汉字
# （纯拉丁/数字锚如「AI」不得关联）。关联方式逐条显式披露，不做语义泛化、不加猜测别名。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# 共享子串锚的泛词黑名单（2026-10-24a）：横切多题材的 2 字泛词不得充当关联锚——
# 10-23 实例：中办国办《意见》经「应用」被挂给 AI应用（该事件与 AI应用 的唯一关联
# 就是这 2 字）。只封泛词；2 字专有锚（俄乌/冰雪 等）不受影响，G2 修复
# （俄乌重建↔俄乌和平）依赖它们。
GENERIC_ANCHORS = ("应用", "科技", "智能", "数据", "概念", "技术", "消费", "能源", "金融")


def _shared_anchor(a: str, b: str) -> str | None:
    """最长公共连续子串；≥2 字且含 ≥1 汉字才算关联锚（"AI" 这类纯拉丁锚不得关联）。

    泛词候选在扫描中直接跳过、不当锚：泛词任何题材都能共享，不构成题材关联证据。
    只跳过不整体否决（2026-10-24 review 处置）——否则最长锚是泛词时会连坐专有锚
    （实测「智能驾驶」vs「智能网联驾驶辅助」经「智能」把「驾驶」锚杀掉，且结果取决于
    泛词在板名里的扫描位置）；全部候选皆泛词时 best 保持空串，同样返回 None。
    """
    if not a or not b:
        return None
    best = ""
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            if k > len(best) and a[i:i + k] not in GENERIC_ANCHORS:
                best = a[i:i + k]
    return best if len(best) >= 2 and _CJK_RE.search(best) else None


def _anchor_hit(base: str, keys: list[str], text: str,
                anchor_text: str | None = None) -> dict | None:
    """确定性关联：含式命中 → 共享子串锚。`anchor_text` 缺省用 text（长文本先给短标题）。"""
    if not base or not text:
        return None
    norm_text = normalize_name(text)
    if norm_text:
        for k in keys:
            if k and (k in norm_text or (anchor_text and k in normalize_name(anchor_text))):
                return {"how": "包含",
                        "anchor": k if len(k) <= len(base) else base}
    anchor = _shared_anchor(base, normalize_name(anchor_text or text))
    if anchor:
        return {"how": f"共享子串「{anchor}」", "anchor": anchor}
    return None


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit] + f"…[截断，原文 {len(text)} 字]"


# 电头剥离（2026-10-24a）：通稿开头的「新华社北京10月21日消息，」「财联社10月21日讯，」
# 与条目已带的日期/来源重复，纯 token 冗余。确定性正则（媒体词白名单 + N月N日 + 消息/讯/电
# 后缀 + 尾随标点才剥），不命中原文一字不动；只剥开头一处，无任何语义改写。
# 尾随标点必须存在（2026-10-24 review 处置）：真电头后必跟逗号——可选会截烂
# 「10月21日电话会议」「9月30日消息面回暖」这类普通词开头（电/消息 后接话·报·面）。
_DATELINE_RE = re.compile(
    r"^(?:(?:新华社|财联社|央视新闻|界面新闻|证券时报|上海证券报|澎湃新闻|每日经济新闻"
    r"|21世纪经济报道|红星新闻|参考消息|路透社|彭博社)[^，,。]{0,12}?)?"
    r"\d{1,2}月\d{1,2}日(?:消息|讯|电)[，,、]\s*")


def _strip_dateline(text: str) -> str:
    return _DATELINE_RE.sub("", str(text or ""), count=1)


def _days_between(a: str | None, b: str | None) -> int | None:
    from datetime import datetime
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def board_snapshot(db, date: str, board_name: str | None,
                   leader_code: str | None = None,
                   sealed_codes: frozenset[str] | set[str] | None = None) -> dict | None:
    """韭研异动 `{date}:final` 里该板块的分组与逐股解析（L2 层，原料在库零成本）。

    `sealed_codes` 给出时只保留封板名单（与结构行 boardN 同口径；不把触板未封混进
    L2 计数，免得同篇叙事出现两个不同的「板内只数」）；未给时为韭研异动全量口径
    （预览脚本用，段内披露口径）。
    """
    try:
        doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    except Exception:   # noqa: BLE001 读不到就如实当无分组，不伪造
        return None
    for field in doc.get("fields") or []:
        if str(field.get("name") or "") == str(board_name or ""):
            stocks = [s for s in (field.get("stocks") or []) if s]
            if sealed_codes is not None:
                stocks = [s for s in stocks
                          if str(s.get("code") or "")[-6:] in sealed_codes]
            return {"count": len(stocks), "stocks": stocks,
                    "sealedFilter": sealed_codes is not None}
    return None


def corpus_state(db, *, date: str) -> dict:
    """语料新鲜度（fail-visible 用）：产业树 + KPL 三集合的计数与最近采集日。"""
    try:
        ind_n = db[S.COLLECTION_INDUSTRY].count_documents({})
        kpl = KS.corpus_stats(db)
        latest = kpl.get("latestFetchDate")
        row = db[S.COLLECTION_INDUSTRY].find_one(
            {}, {"lastFetchDate": 1}, sort=[("lastFetchDate", -1)]) or {}
        ind_latest = row.get("lastFetchDate")
        if ind_latest and (latest is None or ind_latest > latest):
            latest = ind_latest
    except Exception as exc:  # noqa: BLE001 读不到就如实报未采集，不伪造
        return {"ok": False, "error": str(exc), "industry": 0,
                "latestFetchDate": None, "stale": True}
    return {"ok": bool(latest), "industry": ind_n,
            "topic": (kpl.get("topic") or {}).get("count"),
            "news": (kpl.get("news") or {}).get("count"),
            "calendar": (kpl.get("calendar") or {}).get("count"),
            "latestFetchDate": latest, "stale": latest != date, "date": date}


def match_kpl_events(events: list[dict], board_name: str | None,
                     *, limit: int = MAX_EVENTS) -> list[dict]:
    """题材事件 → 板块：标题/正文命中关键词即算（确定性包含+共享子串锚，逐条带关联方式）。"""
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for ev in events or []:
        title = str(ev.get("title") or "")
        hit = _anchor_hit(base, keys, title)
        if not hit:
            hit = _anchor_hit(base, keys, str(ev.get("content") or "")[:200])
        if hit:
            out.append({**ev, "matchHow": hit["how"]})
        if len(out) >= limit:
            break
    return out


def match_kpl_news(items: list[dict], board_name: str | None,
                   *, limit: int = MAX_EVENTS) -> list[dict]:
    """题材新闻 → 板块：**Kword 题材标签优先**（开盘啦现成的关联），回落标题锚。"""
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for it in items or []:
        kw = str(it.get("kword") or "")
        hit = None
        if kw:
            kn = normalize_name(kw)
            if any(k and (k in kn or (kn and kn in k)) for k in keys):
                hit = {"how": "Kword标签", "anchor": kn if len(kn) <= len(base) else base}
            else:
                a = _shared_anchor(base, kn)
                if a:
                    hit = {"how": f"Kword共享子串「{a}」", "anchor": a}
        if not hit:
            hit = _anchor_hit(base, keys, str(it.get("title") or ""))
        if hit:
            out.append({**it, "matchHow": hit["how"]})
        if len(out) >= limit:
            break
    return out


def match_kpl_calendar(items: list[dict], board_name: str | None,
                       *, limit: int = MAX_EVENTS) -> list[dict]:
    """前瞻日历 → 板块：brief 命中关键词/锚（确定性）。"""
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for it in items or []:
        hit = _anchor_hit(base, keys, str(it.get("brief") or ""))
        if hit:
            out.append({**it, "matchHow": hit["how"]})
        if len(out) >= limit:
            break
    return out


def theme_heat_series(db, board_name: str | None, *, date: str,
                      days: int = 5) -> dict:
    """题材热度序列（v5）：近 `days` 日该题材的新闻条数/事件数/最高热度按日聚合。

    题材延续性与炒作深度判据的核心原料：单日快照只能看「现在有没有催化」，
    序列才能看「是否断流/见顶回落」。确定性聚合、零模型；匹配口径与事件/新闻相同
    （Kword 标签优先 + 标题/正文确定性锚）。返回 {series: [{date, newsN, eventN, maxHot}],
    any: bool}。
    """
    base = normalize_name(board_name)
    if not base:
        return {"series": [], "any": False}
    news = KS.get_news_items(db, date=date, include_past_recent=days - 1, window_days=0)
    events = KS.get_topic_events(db, date=date, include_past_recent=days - 1, window_days=0)
    news_matched = match_kpl_news(news, board_name, limit=10 ** 6)
    ev_matched = match_kpl_events(events, board_name, limit=10 ** 6)
    by_day: dict[str, dict] = {}
    for it in news_matched:
        d = it.get("eventDate") or ""
        if not d:
            continue
        by_day.setdefault(d, {"date": d, "newsN": 0, "eventN": 0, "maxHot": None})
        by_day[d]["newsN"] += 1
    for ev in ev_matched:
        d = ev.get("day") or ""
        if not d:
            continue
        by_day.setdefault(d, {"date": d, "newsN": 0, "eventN": 0, "maxHot": None})
        by_day[d]["eventN"] += 1
        hv = ev.get("hotVal")
        if isinstance(hv, (int, float)):
            cur = by_day[d]["maxHot"]
            by_day[d]["maxHot"] = hv if cur is None else max(cur, hv)
    from datetime import datetime, timedelta
    try:
        d0 = datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return {"series": [], "any": False}
    series = []
    for i in range(days - 1, -1, -1):
        d = (d0 - timedelta(days=i)).strftime("%Y-%m-%d")
        series.append(by_day.get(d) or {"date": d, "newsN": 0, "eventN": 0, "maxHot": None})
    return {"series": series, "any": any(s["newsN"] or s["eventN"] for s in series)}


def _heat_line(series: dict) -> str:
    """热度序列渲染为一行（按日 新闻·事件·最高热度，供模型直读趋势）。"""
    parts = []
    for s in series["series"]:
        seg = f"{s['date'][5:]} 新闻{s['newsN']}·事件{s['eventN']}"
        if s.get("maxHot") is not None:
            seg += f"（最高热度{s['maxHot']}）"
        parts.append(seg)
    return "；".join(parts)


def build_theme_evidence_block(db, *, board_name: str, date: str,
                              leader_code: str | None = None,
                              window_days: int = 3, content_chars: int = CONTENT_CHARS,
                              max_events: int = MAX_EVENTS,
                              include_l2: bool = True,
                              sealed_codes: frozenset[str] | set[str] | None = None) -> dict:
    """生成题材证据块（v4：产业树 + KPL 事件/新闻/日历 + L2 板内解析）。

    返回 {text, industry, events, news, calendar, state, ...}（text 直接可拼进叙事）。
    代际：v2（2026-10-20 确定性门）→ v3（2026-10-22 L2 板内解析 + 门收窄）→
    **v4（2026-10-23 事件层换源开盘啦**：韭研 timeline/早报退役；题材事件/新闻/日历
    三节改消费 `kpl_theme_*`；早报段落匹配泛化为共享子串锚）。
    `include_l2=False` = relay 兼容形状（不出板内解析/新闻流节；事件层来源标签随换源
    更新——relay 题材证据行为派生锚（不作主锚、判据未变），来源漂移已登记不重放）。
    """
    state = corpus_state(db, date=date)
    nodes = S.get_industry_nodes(db) if state.get("ok") else []
    match = (match_industry(nodes, board_name) if nodes
             else {"matched": False, "method": None, "node": None, "candidates": []})
    # S3（2026-10-24b）：板内解析提前取——产业树首通道渲染要用龙头驱动标签做第二匹配。
    # sealed 口径与板内解析节完全一致（boardCodes 封板名单），不引入第二个口径。
    snap = board_snapshot(db, date, board_name, leader_code,
                          sealed_codes=sealed_codes) if include_l2 else None
    leader_tag_line = ""
    if snap is not None:
        _stocks = snap.get("stocks") or []
        _lead = next((s for s in _stocks
                      if str(s.get("code") or "")[-6:] == str(leader_code or "")),
                     _stocks[0] if _stocks else None)
        _exp = str((_lead or {}).get("expound") or "")
        leader_tag_line = _exp.splitlines()[0].strip() if _exp else ""
    # KPL 语料窗：事件回看 3 日（发酵中）+ 次日；新闻回看 2 日；日历未来 window_days 日
    kpl_events = (KS.get_topic_events(db, date=date,
                                      include_past_recent=EVENT_WINDOW_PAST_DAYS, window_days=1)
                  if state.get("ok") else [])
    kpl_news = (KS.get_news_items(db, date=date,
                                  include_past_recent=NEWS_WINDOW_PAST_DAYS, window_days=1)
                if state.get("ok") else [])
    kpl_calendar = (KS.get_calendar_items(db, date=date, window_days=window_days)
                    if state.get("ok") else [])
    ev_hits = match_kpl_events(kpl_events, board_name, limit=max_events)
    news_hits = match_kpl_news(kpl_news, board_name, limit=max_events)
    cal_hits = match_kpl_calendar(kpl_calendar, board_name, limit=max_events)

    lines = [BLOCK_HEADER]
    if not state.get("ok"):
        lines.append("题材语料（韭研产业树 + 开盘啦事件层）未采集（fail-visible：无数据 ≠ 无催化）。"
                     "请勿据此判断催化有无。")
    else:
        stale = "" if not state.get("stale") else f"（注意：语料最近采集日 {state.get('latestFetchDate')}，非当日）"
        lines.append(f"取数日 {date}，语料：产业树 {state.get('industry')} 节点 / "
                     f"题材事件 {state.get('topic')} · 新闻 {state.get('news')} · "
                     f"日历 {state.get('calendar')} 条{stale}")

    node = match.get("node")
    if not state.get("ok"):
        pass                                   # 未采集行已在前面给出，不再伪造 L3 明细
    elif not match.get("matched"):
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

    # S3 驱动标签补充映射（2026-10-24b）：龙头驱动标签词命中产业树**不同**节点时
    # 并列披露一行（只补最优先一个；命中首通道同名节点/节点无正文 → 不重复不凑数）。
    # 首通道未映射时同样适用（此时任何命中都是增量）。
    if include_l2 and state.get("ok") and nodes and leader_tag_line:
        first_name = normalize_name((node or {}).get("name"))
        for term in _tag_terms(leader_tag_line):
            m2 = match_industry(nodes, term)
            n2 = m2.get("node") or {}
            if not m2.get("matched") or normalize_name(n2.get("name")) == first_name:
                continue
            if not n2.get("content"):
                continue
            chg2 = n2.get("contentChangedDate") or "未知"
            gap2 = _days_between(chg2, date)
            gap2_txt = ("当日" if gap2 == 0 else f"{gap2} 天前"
                        if isinstance(gap2, int) and gap2 > 0 else "未知")
            lines.append(
                f"驱动标签补充映射（龙头标签「{leader_tag_line}」中词「{term}」经 "
                f"{m2.get('method')} 命中产业树「{n2.get('name')}」，热度 {n2.get('hot')}，"
                f"正文更新 {chg2}={gap2_txt}）：{_clip(n2.get('content'), content_chars)}")
            break

    # 当日题材事件（开盘啦 Topic：逐事件全文 + 来源 + 热度）
    heat = (theme_heat_series(db, board_name, date=date, days=HEAT_WINDOW_DAYS)
            if (include_l2 and state.get("ok")) else None)
    if heat is not None:
        if heat.get("any"):
            lines.append(f"题材热度序列（近 {HEAT_WINDOW_DAYS} 日新闻/事件按日聚合；"
                         f"看新增密度是否断流/见顶）：{_heat_line(heat)}")
        else:
            lines.append(f"题材热度序列：近 {HEAT_WINDOW_DAYS} 日无该题材的新闻/事件痕迹"
                         f"（不代表无催化；若板块当日仍涨停，则纯资金/情绪驱动特征明显）")
    if state.get("ok"):
        if not ev_hits:
            lines.append(f"当日题材事件：无匹配（「{board_name}」相关事件未命中，无数据 ≠ 无催化）")
        else:
            lines.append("当日题材事件（开盘啦题材事件，关联方式逐条披露）：")
            for ev in ev_hits:
                src = f"，来源 {ev.get('source')}" if ev.get("source") else ""
                hot = f"，热度 {ev.get('hotVal')}" if ev.get("hotVal") is not None else ""
                body = _strip_dateline(str(ev.get("content") or ""))
                body_txt = f"：{_clip(body, EVENT_CHARS)}" if body else ""
                lines.append(f"- {ev.get('day')} {ev.get('title')}"
                             f"（{ev.get('matchHow')}{src}{hot}）{body_txt}")

    # 近两日题材新闻（开盘啦 ThemeNews）+ 前瞻日历（开盘啦 Type=3）。
    # 2026-10-24a：两节均无匹配时合并为一行（原两行各带一遍「无数据 ≠ 无催化」套话，
    # 纯 token 冗余）；单边有命中维持分列，语义不变。
    news_section = include_l2 and state.get("ok")
    cal_section = state.get("ok")
    news_no_match = news_section and not news_hits
    cal_no_match = cal_section and not cal_hits
    if news_no_match and cal_no_match:
        lines.append(f"题材新闻/前瞻日历：均无匹配（「{board_name}」Kword 标签与日历均未命中，"
                     f"无数据 ≠ 无催化）")
    else:
        if news_section:
            if news_no_match:
                lines.append(f"近两日题材新闻：无匹配（Kword 题材标签未命中「{board_name}」，"
                             f"无数据 ≠ 无催化）")
            else:
                lines.append("近两日题材新闻（开盘啦题材新闻，Kword 题材标签关联）：")
                for it in news_hits:
                    stocks = it.get("stocks") or []
                    top = [s for s in stocks if s.get("setTop")][:3] or stocks[:3]
                    # KPL Rate 本身就是百分数值（-1.74 = 当日 -1.74%），不再 ×100
                    st_txt = "，关联股 " + "、".join(
                        f"{s.get('name')}{s.get('rate'):+.2f}%"
                        if isinstance(s.get("rate"), (int, float)) else str(s.get("name"))
                        for s in top) if top else ""
                    lines.append(f"- {it.get('eventDate')} [{it.get('kword')}] {it.get('title')}"
                                 f"（{it.get('matchHow')}{st_txt}）")
        if cal_section:
            if cal_no_match:
                lines.append(f"未来 {window_days} 日既定事件：无匹配（「{board_name}」相关事件未命中，"
                             f"无数据 ≠ 无催化）")
            else:
                lines.append(f"未来 {window_days} 日既定事件（开盘啦题材日历）：")
                for ev in cal_hits:
                    fd = _days_between(date, ev.get("date"))
                    when = f"{ev.get('date')}" + (f"（T+{fd}）" if isinstance(fd, int) and fd >= 0 else "")
                    tag = f" [{ev.get('tagName')}]" if ev.get("tagName") else ""
                    lines.append(f"- {when}{tag} {ev.get('brief')}（{ev.get('matchHow')}）")

    # ── L2 板内解析（韭研异动库：板块分组 + 逐股 expound；v3 起纳入证据）──
    # include_l2=False（relay 兼容形状）：整节不渲染。
    # snap 已在产业树匹配阶段提前取得（S3 第二匹配通道共用，口径同一份）。
    board_resolved = False
    board_stocks_n = 0
    if not include_l2:
        pass
    elif snap is None:
        lines.append(f"板内解析：当日韭研异动无「{board_name}」板块分组（如实标注；"
                     f"非题材桶或当日未收录）")
    else:
        board_stocks_n = snap["count"]
        stocks = snap["stocks"]
        lead = next((s for s in stocks
                     if str(s.get("code") or "")[-6:] == str(leader_code or "")),
                    stocks[0] if stocks else None)
        exp = str((lead or {}).get("expound") or "")
        tag_line = exp.splitlines()[0].strip() if exp else ""
        body = "\n".join(exp.splitlines()[1:]).strip()
        if lead is not None and exp:
            board_resolved = True
            caliber = "" if snap.get("sealedFilter") else "（韭研异动口径，含触板未封）"
            lines.append(f"板内解析（韭研异动「{board_name}」{board_stocks_n} 只{caliber}）："
                         f"龙头 {lead.get('name')}（{lead.get('code')}）驱动标签「{tag_line}」｜"
                         f"解析摘录：{_clip(body or exp, content_chars)}")
        elif lead is not None:
            caliber = "" if snap.get("sealedFilter") else "（韭研异动口径，含触板未封）"
            lines.append(f"板内解析（韭研异动「{board_name}」{board_stocks_n} 只{caliber}）："
                         f"龙头 {lead.get('name')}（{lead.get('code')}）无异动解析（如实标注）")
        peer_tags = []
        for p in [s for s in stocks if s is not lead][:5]:
            pe = str(p.get("expound") or "")
            pt = pe.splitlines()[0].strip() if pe else ""
            if pt:
                peer_tags.append(f"{p.get('name')}（{pt}）")
        if peer_tags:
            board_resolved = True
            lines.append("板内同伴驱动：" + "、".join(peer_tags))

    has_content = bool((node or {}).get("content"))
    missing_reason = None
    if include_l2:
        # v4 口径：L3（产业树/KPL 事件·新闻·日历）与 L2（板内解析）**均无**可用证据才缺——
        # 缺一层 ≠ 无证据（§4.0）。催化陈旧仍不算缺失（stale 是证据）。
        l3_evidence = bool((match.get("matched") and has_content) or ev_hits
                           or news_hits or cal_hits)
        if not board_resolved and not (ev_hits or news_hits):
            if not state.get("ok"):
                missing_reason = "corpus_not_collected"
            elif not l3_evidence:
                missing_reason = ("industry_tree_unmapped" if not match.get("matched")
                                  else "no_content_no_event")
    else:
        # relay 兼容口径（relay 不消费缺失标志，仅为形状稳定保留 v2 语义）
        if not state.get("ok"):
            missing_reason = "corpus_not_collected"
        elif not match.get("matched"):
            missing_reason = "board_unmapped"
        elif not has_content and not ev_hits and not cal_hits:
            missing_reason = "no_content_no_event"
    return {"text": "\n".join(lines), "industry": node if match.get("matched") else None,
            "events": ev_hits, "news": news_hits, "calendar": cal_hits, "state": state,
            "boardMapped": bool(match.get("matched")), "hasContent": has_content,
            "eventCount": len(ev_hits),
            "boardResolved": board_resolved, "boardStocks": board_stocks_n,
            "kwordTags": [it.get("kword") for it in news_hits if it.get("kword")],
            "heatSeries": heat,
            "evidenceMissing": missing_reason is not None,
            "evidenceMissingReason": missing_reason,
            "unmappedCandidates": match.get("candidates") or []}
