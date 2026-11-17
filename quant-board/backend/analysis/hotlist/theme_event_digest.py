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

import logging
import re
from datetime import datetime, timedelta, timezone

from backend.operations import jiuyan_theme_store as S
from backend.operations import kpl_theme_store as KS

logger = logging.getLogger(__name__)

BLOCK_HEADER = "【题材证据】"
CONTENT_CHARS = 260
MAX_EVENTS = 3
EVENT_WINDOW_PAST_DAYS = 3      # 事件/新闻回看窗口（发酵中）
NEWS_WINDOW_PAST_DAYS = 2
# 早报节叙事字数预算（2026-11-14 晨间例外）：早报全文 ~429 字/日，仅命中段进叙事，
# 节合计 ≤600 字（超预算段整段不入，不截断成残句）
MORNING_CHARS = 600
MORNING_MAX_PARAS = 6
# 快讯节（2026-11-14 C 阶段）：隔夜窗 ≤3 条 × 260 字（同 MAX_EVENTS 口径）
FLASH_MAX_ITEMS = 3
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
    # 2026-10-30e 清点实证：KPL 一级 241 板块无「半导体」，对应名「芯片」（播报实证
    # 「芯片（存储）小幅回流，权重长鑫科技…」）；韭研半导体 5 日全未匹配强度榜
    "半导体": ("芯片",),
    "光模块": ("光模块", "光通信"),
    "AI硬件": ("AI硬件", "算力"),
    "AI应用": ("AI应用", "智能体"),
    "AI安全": ("网络安全", "AI应用"),   # KPL 无「网络安全」板块（2026-11-01 历史覆盖实证），落 AI应用
    "存储": ("存储", "DRAM", "芯片"),   # KPL 无独立存储板块（历史覆盖实证），落 芯片
    "固态电池": ("固态电池",),
    # 纯词汇等价（韭研异动板块名 ↔ 产业树命名差异），不含任何语义推断：
    "油气": ("石油",),
    "供热": ("供暖",),
    "出版传媒": ("传媒出版", "文化传媒"),   # KPL 名为「文化传媒」（2026-11-01 历史覆盖实证）
    # ── 2026-11-01 历史覆盖诊断增补（108 交易日基线 84.4%→目标 90%+；
    #    逐条经 KPL 名录全集实证存在对应名，未匹配频次=维护优先级，
    #    详见 docs/hotlist-jev/sector-nodes-v4f §九）──
    "被动元件": ("元器件",),       # KPL「元器件」；MLCC=被动元件子类同归
    "MLCC": ("元器件",),
    "农林牧渔": ("农业",),         # KPL「农业」
    "化肥农药": ("化工",),         # KPL[化工]
    "贵金属": ("黄金", "白银"),    # KPL「黄金」
    "AI影视传媒": ("AI视频",),    # KPL「AI视频」；韭研「AI影视/传媒」归一后为「AI影视传媒」（key 必须用归一形式，带斜杠查不到）
    "短剧": ("AI视频",),           # KPL「AI视频」
    "影视短剧": ("AI视频",),       # KPL [AI视频）
    "AI短剧": ("AI视频",),         # 同上
    "AI散热": ("算力",),           # 算力基建细分（KPL 无液冷/散热独立板块）
    "液冷散热": ("算力",),
    "AI液冷散热": ("算力",),
    "AI液冷": ("算力",),          # 用户二次修正：算力常在当日名录，AI硬件冷门常缺
    "数据中心散热": ("算力",),
    "AI配电": ("算力",),
    "数据要素": ("数字经济",),     # KPL「数字经济」
    "金属有色": ("有色金属",),
    "小金属": ("有色金属",),
    "AI金属": ("有色金属",),       # AI 电力需求带动的铜铝等
    "氧化锆": ("新材料概念",),
    "新能源汽车": ("汽车类",),     # KPL「汽车类」
    "AIPC": ("消费电子",),
    "国产半导体": ("芯片",),
    "可控核聚变": ("核电",),
    "猪肉": ("农业",),
    "数字人民币": ("跨境支付",),
    # 2026-11-13 用户裁决（竞价链 T−1 涨停分组实证：分组名「医疗医药」产业树三通道
    # 全空——树无裸「医药」节点可子串命中；证据门强制全列 insufficient 铛 002172）。
    # 同日四轮裁决：初锚创新药 → 改「医疗」（落医疗器械 hot0.7，与澳洋健康
    # 脑机接口+民营医院驱动弱相关）→ 改「脑机接口」（level1 hot-1.79）→
    # 终锚「AI医疗」（level1 hot-2.12，2026-10-20 正文，AI医疗-AI制药/华为/阿里
    # 子树同池；字面「医药医疗」树内零命中已实证不采用）。alias 通道与
    # board_keywords 事件链同条生效（单一事实源，不重复建映射）；板块级粒度
    # 代价已登记：同分组非 AI医疗驱动股共享此母链，个股事实仍由涨停原因/龙虎榜承载。
    "医疗医药": ("AI医疗",),
    # ── 2026-11-01 用户指认（领域专家逐条拍板，有据收录）：├─
    # 注：冰雪经济↔冰雪产业走既有后缀桥（X经济/X产业 双向补词，10-30e 预登记），
    # 不重复建 alias（单一事实源；重复展开会改变 board_keywords 顺序破坏既有断言）
    "长鑫科技": ("AI硬件",),     # 韭研个股名板块（存储大厂），KPL 归 AI硬件主题
}
# 明确**不做**映射的粗分桶（不是题材，映射过去会伪造板块催化）；「医疗医药」与
# 「医药医疗」为韭研同一粗分桶的字序变体（2026-10-22 归因实测漏收，有据收录）。
# 2026-10-26 用户裁决摘除四个「大X」域桶（大消费/大农业/医药医疗/医疗医药）：它们是
# 真实题材域（韭研只是没给产业树节点），S3 驱动标签补充映射（2026-10-24b）上线后
# 七桶 evidenceMissing 实测全 False——v3 收紧「门控率 100%/49/49 自判 insufficient」
# 的前提失效；10-26 大消费龙头上海九百 4 板（当日最高板）漏判实锤。预登记 §20。
NOT_A_THEME = ("公告", "新股", "其他", "ST板块",
               "ST")   # P2-1（review）："ST 板块"等空格变体归一后恰为 "ST"，一并覆盖


def is_not_a_theme(board_name: str | None) -> bool:
    """行政桶判定（单一事实源，v12 漏排修复）：**原始名 + 归一名双口径**。

    bug 实证（2026-10-28 开火日）：normalize_name("ST板块") 尾缀剥离成 "ST"，
    与原名单 "ST板块" 不等 → ST板块 整板块漏排、jev 白烧两调用且脏行入页面。
    归一口径仍保留（兼容历史行/大小写变体），但必须同时比对原始名。
    """
    name = str(board_name or "").strip()
    return name in NOT_A_THEME or normalize_name(name) in NOT_A_THEME
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
    """板块名 → 匹配关键词（归一后的自身 + 别名 + 经济/产业后缀桥）。

    2026-10-30 后缀桥（用户报障实测：韭研「冰雪经济」↔ KPL「冰雪产业」，10:38 播报
    「冰雪产业异动拉升，冰山冷热直线涨停」漏配）：韭研与 KPL 对同一题材的命名后缀
    存在经济/产业差异，确定性互认——base 以「经济/产业」结尾时补词干与对侧后缀变体；
    词干 ≥2 字且非泛词（GENERIC_ANCHORS，如「消费经济→消费」不桥）才展开。无语义
    推断，只展开字面变体；适用于直播/事件同一条公共链。"""
    base = normalize_name(board_name)
    keys = [base] if base else []
    for alias in ALIASES.get(base, ()):
        a = normalize_name(alias)
        if a and a not in keys:
            keys.append(a)
    for suf_a, suf_b in (("经济", "产业"), ("产业", "经济")):
        if base.endswith(suf_a):
            stem = base[: -len(suf_a)]
            if len(stem) >= 2 and stem not in GENERIC_ANCHORS:
                for cand in (stem, stem + suf_b):
                    if cand not in keys:
                        keys.append(cand)
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


# 残桩正文门槛（2026-11-14 用户报障：大东方大消费→商业航天错联复盘）：
# ai_industry 995 节点中 788 个正文 ≤9 字且多为自复述残桩（「大消费-酒」正文=「酒」），
# 零判读信息量——缺数据/无信息量整行不投喂（AGENTS §1.2-8）：按「无催化正文」处理，
# 且不托底 has_content（三层缺失门不被假证据掩护）。有催化正文极少 <10 字。
_STUB_CONTENT_CHARS = 10


def _is_stub_content(node: dict | None) -> bool:
    """正文 <10 字视为自复述残桩（韭研冷节点只回填了节点名本身），零信息量。"""
    return len(str((node or {}).get("content") or "").strip()) < _STUB_CONTENT_CHARS


def _leader_node_membership(db, node: dict | None,
                            leader_code: str | None) -> str | None:
    """龙头 ∈ 产业树成分验证（S3 门，2026-11-14）：沿匹配节点 path 自下而上回溯最近
    一级节点，查成分快照（jiuyan_industry_stocks，周频 batchDate）成员码集合。
    返回 'member' | 'not_member' | None（快照缺席/读失败=无法核验，不缓存不伪造）；
    零网络纯库读。词面命中 ≠ 业务关联：不在树 = KPL 蹭标签，不得注入叙事。"""
    if not node or not leader_code:
        return None
    code6 = str(leader_code)[-6:]
    names = ([str(p) for p in (node.get("path") or [])]
             or [str(node.get("name") or "")])
    try:
        from backend.operations import jiuyan_theme_store as JTS
        for name in reversed(names):
            snap = JTS.get_industry_stocks_by_name(db, name)
            if not snap:
                continue
            codes = {str(s.get("code"))[-6:] for s in snap.get("stocks") or []}
            return "member" if code6 in codes else "not_member"
    except Exception:                                    # noqa: BLE001 读失败如实降级
        return None
    return None


# ── 确定性关联锚（v3 引入，v4 沿用；早报段落匹配的通用化） ─────────────────
# 背景：完整板块名子串匹配不上语义同源的事件（「俄乌重建」vs「俄乌和平」）。
# 规则：①含式命中（关键词 ⊆ 归一文本）；②最长公共连续子串 ≥2 字且含 ≥1 汉字
# （纯拉丁/数字锚如「AI」不得关联）。关联方式逐条显式披露，不做语义泛化、不加猜测别名。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# 共享子串锚的泛词黑名单（2026-10-24a）：横切多题材的 2 字泛词不得充当关联锚——
# 10-23 实例：中办国办《意见》经「应用」被挂给 AI应用（该事件与 AI应用 的唯一关联
# 就是这 2 字）。只封泛词；2 字专有锚（俄乌/冰雪 等）不受影响，G2 修复
# （俄乌重建↔俄乌和平）依赖它们。
GENERIC_ANCHORS = ("应用", "科技", "智能", "数据", "概念", "技术", "消费", "能源", "金融",
                   "经济")   # P1-1（review 2026-10-28）：冰雪/低空/银发/数字等「X经济」并存，不互锚


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
    return text if len(text) <= limit else text[:limit] + "…"


# ── 2026-11-17 语料精简（用户裁决，西陇科学 002584 案例审计）──
# 纯叙事渲染层压缩：落库原文（jiuyan expound / 2203 zt）不动，单一事实源仍在库。

_ENUM_ITEM = r"[^，。；：、！？\s等]{1,8}"
_ENUM_RUN_RE = re.compile(_ENUM_ITEM + r"(?:、" + _ENUM_ITEM + r"){7,}")


def _compress_enum(text: str) -> str:
    """长枚举压缩：≥8 个短项（≤8 字）的「、」连续枚举只留前 3 项+「等」。

    西陇案例：解析摘录罗列 13 个化学品名（~70 字符），驱动标签已承载类别
    （PCB用化学试剂），逐项枚举判读价值低。阈值 ≥8 保守起步，短枚举不动。
    """
    def _sub(m: re.Match) -> str:
        items = m.group(0).split("、")
        return "、".join(items[:3]) + "等"
    out = _ENUM_RUN_RE.sub(_sub, str(text or ""))
    return out.replace("等等", "等")


_SENT_END = "。！？；"


def _clip_excerpt(text: str, limit: int) -> str:
    """摘录截断治理：超预算时回退到最后一个完整句界，丢弃尾部半句碎片。

    西陇案例：硬截断产出「3、2026年6月23日网传纪要，氧化锆卡…」零信息半句。
    回退后若只剩编号空头（「3、」）一并剔除；尾附「…」显式披露仍有删节
    （fail-visible）。预算内无任何句界时保留硬截断（宁截勿空）。
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    k = max(cut.rfind(ch) for ch in _SENT_END)
    if k <= 0:
        return cut + "…"
    out = re.sub(r"\s*\d+、\s*$", "", cut[:k + 1]).rstrip()
    return (out + "…") if out else cut + "…"


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
    """题材事件 → 板块：标题/正文命中关键词即算（确定性包含+共享子串锚，逐条带关联方式）。

    v12（2026-10-28 用户裁决）：附 `titleHit` 标志（标题级命中=强；仅正文/子串级=弱，
    渲染时降级标注）；事件正文不再进叙事（仅标题+热度+日期）。
    """
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for ev in events or []:
        title = str(ev.get("title") or "")
        title_hit = _anchor_hit(base, keys, title)
        hit = title_hit or _anchor_hit(base, keys, str(ev.get("content") or "")[:200])
        if hit:
            out.append({**ev, "matchHow": hit["how"], "titleHit": title_hit is not None})
        if len(out) >= limit:
            break
    return out


def _strip_html(s: str) -> str:
    """新题正文（HTML 单主链）→ 匹配用文本（2026-11-02 正文预登记 §五.1）。"""
    return re.sub(r"<[^>]+>", " ", str(s or ""))


def match_morning_paragraphs(paragraphs: list[str], board_name: str | None,
                             *, limit: int = MORNING_MAX_PARAS) -> list[dict]:
    """早报段落 → 板块：确定性关键词/共享子串锚（同事件通道口径，无语义猜测）。

    返回 [{text, matchHow}]；matchHow 只进结构化字段（AGENTS §1.2-8 不进叙事）。
    """
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for p in paragraphs or []:
        text = str(p or "").strip()
        if not text:
            continue
        hit = _anchor_hit(base, keys, text)
        if hit:
            out.append({"text": text, "matchHow": hit["how"]})
        if len(out) >= limit:
            break
    return out


def _morning_fetched_after_cutoff(mdoc: dict, date: str) -> bool:
    """早报档 fetch 时点晚于当日 09:26 → 迟到档（morningState=late，不渲染）。

    防前视：调度 done 集是内存态，进程重启后错过槽按 ≥时点补跑——若早报当日发布
    晚于 09:26，迟到补跑会把晚间内容当晨间证据。快讯侧同款截止 baked 进读口，
    此处对齐。时点取 fetchedAt（内容抓取时刻）；无时点字段（异常/legacy）放行。
    """
    raw = str(mdoc.get("fetchedAt") or mdoc.get("firstSeenAt") or "").strip()
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if dt.tzinfo is not None:   # 落库侧为本地墙钟（UTC+8）；带时区则归一到 UTC+8 后比墙钟
        dt = dt.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    try:
        cutoff = datetime.strptime(f"{date} 09:26", "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return dt > cutoff


def match_flash_items(items: list[dict], board_name: str | None,
                      *, limit: int = FLASH_MAX_ITEMS) -> list[dict]:
    """快讯 → 板块：标题锚优先，digest 兑底（无题材标签，命中均属关键词级弱关联）。

    matchHow 只进结构化字段（AGENTS §1.2-8 不进叙事）。
    """
    base = normalize_name(board_name)
    if not base:
        return []
    keys = board_keywords(board_name)
    out = []
    for it in items or []:
        title = str(it.get("title") or "")
        digest_txt = str(it.get("digest") or "")
        hit = _anchor_hit(base, keys, title)
        if not hit and digest_txt and digest_txt != title:
            hit = _anchor_hit(base, keys, digest_txt, anchor_text=title)
        if hit:
            out.append({**it, "matchHow": hit["how"]})
        if len(out) >= limit:
            break
    return out


def match_kpl_news(items: list[dict], board_name: str | None,
                   *, limit: int = MAX_EVENTS) -> list[dict]:
    """题材新闻 → 板块：**Kword 题材标签优先**，**ZSName 官方板块次之**（2026-11-02
    用户裁决①：KPL 新题自带板块归属，确定性互认，消大部分别名维护），回落标题锚，
    最后正文锚兑底（2026-11-02 正文预登记 §五.1：命中标弱匹配「仅正文级关联」，
    同 2026-10-28 事件通道语义，防泛科技通稿误配）。"""
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
            # ② ZSName 官方板块归属（2026-11-02 用户裁决①）：归一后与 keys 双向包含（≥2 字），
            # 同 Kword 通道口径；ZSName 为空（约七成条目）不参与
            zs = normalize_name(str(it.get("zsName") or ""))
            if len(zs) >= 2 and any(k and (k in zs or zs in k) for k in keys):
                hit = {"how": f"ZSName板块「{str(it.get('zsName'))}」", "anchor": zs if len(zs) <= len(base) else base}
        if not hit:
            hit = _anchor_hit(base, keys, str(it.get("title") or ""))
        if not hit:
            # ④ 正文锚兑底（2026-11-02 正文预登记 §五.1）：HTML 剩标签后确定性关联；
            # 两步：先用标题做共享子串短锚，未中再对正文全文共享子串（review 2026-11-02
            # Minor：仅存在于正文的关联也要能命中，同事件通道 content 无 anchor_text 口径）；
            # 标题未命中 → 弱匹配（titleHit=False），同事件通道语义
            body = _strip_html(str(it.get("contentHtml") or ""))
            if body:
                hit = _anchor_hit(base, keys, body, anchor_text=str(it.get("title") or ""))
                if not hit:
                    hit = _anchor_hit(base, keys, body)
                if hit:
                    hit = {**hit, "how": f"正文锚{'' if hit['how'] == '包含' else '·' + hit['how']}",
                           "titleHit": False}
        if hit:
            rec = {**it, "matchHow": hit["how"]}
            if "titleHit" in hit:
                rec["titleHit"] = hit["titleHit"]
            out.append(rec)
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
    """热度序列渲染为一行（按日 新闻·事件·最高热度，供模型直读趋势）。

    2026-11-17 语料精简（用户裁决）：连续全零日（新闻0·事件0·无热度）合并为
    区间段「MM-DD~MM-DD 新闻0·事件0（连续N日）」——断流事实无损，消除逐字
    重复（西陇科学 11-17 案例：9 日零值逐字重复 ~140 字符）。单日零值原样。
    """
    rows = series["series"]
    parts: list[str] = []
    i = 0

    def _is_zero(s: dict) -> bool:
        return not s["newsN"] and not s["eventN"] and s.get("maxHot") is None

    while i < len(rows):
        s = rows[i]
        if _is_zero(s):
            j = i
            while j + 1 < len(rows) and _is_zero(rows[j + 1]):
                j += 1
            if j > i:
                parts.append(f"{s['date'][5:]}~{rows[j]['date'][5:]} "
                             f"新闻0·事件0（连续{j - i + 1}日）")
            else:
                parts.append(f"{s['date'][5:]} 新闻0·事件0")
            i = j + 1
        else:
            seg = f"{s['date'][5:]} 新闻{s['newsN']}·事件{s['eventN']}"
            if s.get("maxHot") is not None:
                seg += f"（最高热度{s['maxHot']}）"
            parts.append(seg)
            i += 1
    return "；".join(parts)


def build_theme_evidence_block(db, *, board_name: str, date: str,
                              leader_code: str | None = None,
                              window_days: int = 3, content_chars: int = CONTENT_CHARS,
                              max_events: int = MAX_EVENTS,
                              include_l2: bool = True,
                              sealed_codes: frozenset[str] | set[str] | None = None,
                              l2_fallback_date: str | None = None,
                              leader_expound_chars: int | None = None,
                              include_morning: bool = False,
                              include_flash: bool = False) -> dict:
    """生成题材证据块（v4：产业树 + KPL 事件/新闻/日历 + L2 板内解析）。

    返回 {text, industry, events, news, calendar, state, ...}（text 直接可拼进叙事）。
    代际：v2（2026-10-20 确定性门）→ v3（2026-10-22 L2 板内解析 + 门收窄）→
    **v4（2026-10-23 事件层换源开盘啦**：韭研 timeline/早报退役；题材事件/新闻/日历
    三节改消费 `kpl_theme_*`；早报段落匹配泛化为共享子串锚）。
    `include_l2=False` = relay 兼容形状（不出板内解析/新闻流节；事件层来源标签随换源
    更新——relay 题材证据行为派生锚（不作主锚、判据未变），来源漂移已登记不重放）。
    `l2_fallback_date`（2026-11-14b 竞价链原料修复，可选）：当日 final 未生成时
    （晨间 09:26 槽）回退该日（T−1）final 取板内解析；回退命中时板内解析行内显式
    标注榜单日期（数据事实），返回 l2Date/l2FallbackUsed 供 corpusState 留痕。
    缺省 None = 旧行为（题材链零变化）。
    `leader_expound_chars`（同上，可选）：待判龙头自身解析摘录的独立字数上限
    （leader_code 在场时生效；同伴/板块级仍 content_chars）——防 260 字截断丢掉
    控制权变更/公告等公司级硬事实（天普 605255 11-13 复盘）。缺省 None = 旧行为。
    `include_morning`（2026-11-14 晨间例外，可选）：True 时消费当日韭研早报档
    （`jiuyan_morning_report`，只供 09:26 竞价链；17:30 题材链缺省 False 字节级零变化）。
    仅命中段渲染（节合计 ≤MORNING_CHARS），缺席=整行零字；状态返回
    morningState/morningDate/morningHits 供 corpusState 留痕。**不参与 evidenceMissing
    三层门**（题面 hash 冻结，早报是补充供给非判据层变更）。
    `include_flash`（2026-11-14 C 阶段，可选）：True 时消费同花顺 7×24 隔夜窗
    （[T−1 日历日 15:00, 当日 09:26)，截止 baked 进读口防回放前视）；≤3 条×260 字，
    节名「隔夜快讯（同花顺7×24）」；返回 flashState/flashDate/flashHits；缺席=整行零字；
    同样不参与 evidenceMissing 三层门。
    """
    state = corpus_state(db, date=date)
    nodes = S.get_industry_nodes(db) if state.get("ok") else []
    match = (match_industry(nodes, board_name) if nodes
             else {"matched": False, "method": None, "node": None, "candidates": []})
    # S3（2026-10-24b）：板内解析提前取——产业树首通道渲染要用龙头驱动标签做第二匹配。
    # sealed 口径与板内解析节完全一致（boardCodes 封板名单），不引入第二个口径。
    snap = board_snapshot(db, date, board_name, leader_code,
                          sealed_codes=sealed_codes) if include_l2 else None
    l2_date = date
    if include_l2 and snap is None and l2_fallback_date and l2_fallback_date != date:
        snap = board_snapshot(db, l2_fallback_date, board_name, leader_code,
                              sealed_codes=sealed_codes)
        if snap is not None:
            l2_date = l2_fallback_date
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
        lines.append("题材语料未采集。")
    # 语料已采集时的「取数日/语料条数/采集日」管道计数行已随语料卫生红线撤出叙事
    # （AGENTS §1.2-8）：条数/新鲜度属开发诊断，新鲜度已由各条目的日期字段承载。

    node = match.get("node")
    if not state.get("ok"):
        pass                                   # 未采集行已在前面给出，不再伪造 L3 明细
    elif not match.get("matched"):
        if board_name:                        # 空名（未归属股）不掏空占位（review 2026-11-13f）
            lines.append(f"板块级催化：产业树未映射（「{board_name}」）")
    elif not (node or {}).get("content") or _is_stub_content(node):
        # 残桩正文（≤9 字自复述）按缺席处理（2026-11-14）：不伪装成催化原文
        lines.append(f"板块级催化：产业树节点「{node.get('name')}」无催化正文")
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
            gap_txt = f"晚于取数日 {-gap} 天"
        else:
            gap_txt = "未知"
        # 语料卫生红线（AGENTS §1.2-8）：匹配方式（exact/contains/…）不进叙事，
        # 只留 match 结构化字段
        lines.append(
            f"板块级催化原文（「{node.get('name')}」，"
            f"热度 {node.get('hot')}，正文更新 {chg}={gap_txt}）："
            f"{_clip(node.get('content'), content_chars)}")

    # S3 驱动标签补充映射（2026-10-24b）：龙头驱动标签词命中产业树**不同**节点时
    # 并列披露一行（只补最优先一个；命中首通道同名节点/节点无正文 → 不重复不凑数）。
    # 首通道未映射时同样适用（此时任何命中都是增量）。
    # 2026-11-14 成分验证门（用户报障：大东方 600327 零售标签蹭「商业航天」被注入
    # 卫星叙事）：词面命中 ≠ 业务关联，注入前必须验证龙头 ∈ 匹配节点（含一级祖先）
    # 成分快照——不在/无法核验/残桩正文一律不注入，跳过原因留 s3State 供审计不进叙事；
    # 继续扫后续标签词（各词独立门，不连坐）。
    s3_state: str | None = None
    s3_term: str | None = None
    s3_node_name: str | None = None
    if include_l2 and state.get("ok") and nodes and leader_tag_line:
        first_name = normalize_name((node or {}).get("name"))
        for term in _tag_terms(leader_tag_line):
            m2 = match_industry(nodes, term)
            n2 = m2.get("node") or {}
            if not m2.get("matched") or normalize_name(n2.get("name")) == first_name:
                continue
            s3_term, s3_node_name = term, n2.get("name")
            if _is_stub_content(n2):
                s3_state = s3_state or "skipped_stub_content"
                continue
            mem = _leader_node_membership(db, n2, leader_code)
            if mem != "member":
                s3_state = s3_state or (
                    "skipped_not_member" if mem == "not_member"
                    else "skipped_unverifiable")
                continue
            chg2 = n2.get("contentChangedDate") or "未知"
            gap2 = _days_between(chg2, date)
            gap2_txt = ("当日" if gap2 == 0 else f"{gap2} 天前"
                        if isinstance(gap2, int) and gap2 > 0 else "未知")
            lines.append(
                f"产业树补充映射（龙头标签词「{term}」关联「{n2.get('name')}」，"
                f"热度 {n2.get('hot')}，"
                f"正文更新 {chg2}={gap2_txt}）：{_clip(n2.get('content'), content_chars)}")
            s3_state = "injected"
            break

    # 当日题材事件（开盘啦 Topic：仅标题+热度+日期；2026-10-28 用户裁决，正文不出、弱匹配降级）
    heat = (theme_heat_series(db, board_name, date=date, days=HEAT_WINDOW_DAYS)
            if (include_l2 and state.get("ok")) else None)
    if heat is not None:
        if heat.get("any"):
            lines.append(f"题材热度序列（近 {HEAT_WINDOW_DAYS} 日）："
                         f"{_heat_line(heat)}")
        else:
            lines.append(f"题材热度序列：近 {HEAT_WINDOW_DAYS} 日无该题材的新闻/事件痕迹")
    if state.get("ok"):
        if not ev_hits:
            lines.append("当日题材事件：无匹配")
        else:
            lines.append("当日题材事件：")
            for ev in ev_hits:
                src = f"，来源 {ev.get('source')}" if ev.get("source") else ""
                hot = f"，热度 {ev.get('hotVal')}" if ev.get("hotVal") is not None else ""
                # 语料卫生红线：匹配方式/弱匹配标注不进叙事（AGENTS §1.2-8），
                # 匹配质量只留结构化字段（matchHow/titleHit）
                parens = (src + hot).lstrip("，")
                lines.append(f"- {ev.get('day')} {ev.get('title')}"
                             + (f"（{parens}）" if parens else ""))

    # 早报节（2026-11-14 晨间例外，include_morning=True 才渲染；只供 09:26 竞价链）。
    # 与 KPL 池独立读（corpus_state ok 与否不影响早报档披露，§4.0 部分异常不阻断）；
    # 粗分桶（NOT_A_THEME）不参与匹配（防泛科技/公告类早报句误配）；缺席=整行零字。
    morning_state: str | None = None
    morning_date: str | None = None
    morning_hits: list[dict] = []
    if include_morning:
        morning_date = date
        if is_not_a_theme(board_name):
            morning_state = "disabled"
        else:
            try:
                mdoc = S.get_morning_report(db, date=date) or {}
            except Exception as exc:      # noqa: BLE001 读不到如实当缺档，不伪造；留痕
                logger.warning("早报读口异常（date=%s）：%s", date, exc)
                mdoc = {}
            m_state = str(mdoc.get("state") or "")
            if m_state == "ok" and _morning_fetched_after_cutoff(mdoc, date):
                # 迟到档：fetch 时点晚于当日 09:26（进程重启后补跑槽可能采到
                # 晚间才发布的早报）→ 不渲染，防前视；快讯侧同款截止已 baked 进读口
                morning_state = "late"
                morning_hits = []
            elif m_state == "ok":
                morning_hits = match_morning_paragraphs(mdoc.get("paragraphs") or [],
                                                        board_name)
                morning_state = "ok" if morning_hits else "no_hit"
            else:
                morning_state = m_state or "missing"
        used = 0
        morning_lines: list[str] = []
        for i, hit in enumerate(morning_hits):
            text = hit["text"]
            if i == 0 and len(text) > MORNING_CHARS:
                text = text[:MORNING_CHARS] + "…"   # 首段必入（超长截断至预算）
            elif used + len(text) > MORNING_CHARS or used >= MORNING_CHARS:
                break
            used += len(text)
            morning_lines.append(f"- {text}")
        if morning_lines:
            lines.append(f"早盘催化（韭研早报 {date}）：")
            lines.extend(morning_lines)

    # 隔夜快讯节（2026-11-14 C 阶段，include_flash=True 才渲染；只供 09:26 竞价链）。
    # 窗口 [T−1 日历日 15:00, 当日 09:26)（截止 baked 进读口，防盘后重跑/回放前视）；
    # 与 KPL 池/早报独立读；缺席=整行零字；粗分桶不参与。
    flash_state: str | None = None
    flash_date: str | None = None
    flash_hits: list[dict] = []
    if include_flash:
        flash_date = date
        if is_not_a_theme(board_name):
            flash_state = "disabled"
        else:
            try:
                from backend.operations import ths_flash_store as TS
                start_epoch, end_epoch = TS.flash_window_epochs(date)
                flash_items = TS.get_flash_window(db, start_epoch=start_epoch,
                                                  end_epoch=end_epoch)
            except Exception as exc:      # noqa: BLE001 读不到如实当缺档，不伪造；留痕
                logger.warning("快讯读口异常（date=%s）：%s", date, exc)
                flash_items = []
            flash_hits = match_flash_items(flash_items, board_name)
            flash_state = "ok" if flash_hits else (
                "no_hit" if flash_items else "missing")
        if flash_hits:
            lines.append("隔夜快讯（同花顺7×24）：")
            for it in flash_hits:
                when = f"{it.get('ctimeDate')} {it.get('ctimeHHMM')}".strip()
                lines.append(f"- {when} {_clip(it.get('title'), content_chars)}")

    # 近两日题材新闻（开盘啦 ThemeNews）+ 前瞻日历（开盘啦 Type=3）。
    # 2026-10-24a：两节均无匹配时合并为一行（原两行各带一遍「无数据 ≠ 无催化」套话，
    # 纯 token 冗余）；单边有命中维持分列，语义不变。
    news_section = include_l2 and state.get("ok")
    cal_section = state.get("ok")
    news_no_match = news_section and not news_hits
    cal_no_match = cal_section and not cal_hits
    if news_no_match and cal_no_match:
        lines.append("题材新闻/前瞻日历：均无匹配")
    else:
        if news_section:
            if news_no_match:
                lines.append("近两日题材新闻：无匹配")
            else:
                lines.append("近两日题材新闻：")
                for it in news_hits:
                    stocks = it.get("stocks") or []
                    top = [s for s in stocks if s.get("setTop")][:3] or stocks[:3]
                    # KPL Rate 本身就是百分数值（-1.74 = 当日 -1.74%），不再 ×100
                    st_txt = "关联股 " + "、".join(
                        f"{s.get('name')}{s.get('rate'):+.2f}%"
                        if isinstance(s.get("rate"), (int, float)) else str(s.get("name"))
                        for s in top) if top else ""
                    # 语料卫生红线：匹配方式/弱匹配标注不进叙事（AGENTS §1.2-8）
                    parens = f"（{st_txt}）" if st_txt else ""
                    lines.append(f"- {it.get('eventDate')} [{it.get('kword')}] {it.get('title')}"
                                 f"{parens}")
        if cal_section:
            if cal_no_match:
                lines.append(f"未来 {window_days} 日既定事件：无匹配")
            else:
                lines.append(f"未来 {window_days} 日既定事件：")
                for ev in cal_hits:
                    fd = _days_between(date, ev.get("date"))
                    when = f"{ev.get('date')}" + (f"（T+{fd}）" if isinstance(fd, int) and fd >= 0 else "")
                    tag = f" [{ev.get('tagName')}]" if ev.get("tagName") else ""
                    lines.append(f"- {when}{tag} {ev.get('brief')}")

    # ── L2 板内解析（韭研异动库：板块分组 + 逐股 expound；v3 起纳入证据）──
    # include_l2=False（relay 兼容形状）：整节不渲染。
    # snap 已在产业树匹配阶段提前取得（S3 第二匹配通道共用，口径同一份）。
    board_resolved = False
    board_stocks_n = 0
    if not include_l2:
        pass
    elif snap is None:
        lines.append(f"板内解析：当日无「{board_name}」板块分组")
    else:
        board_stocks_n = snap["count"]
        stocks = snap["stocks"]
        lead = next((s for s in stocks
                     if str(s.get("code") or "")[-6:] == str(leader_code or "")),
                    stocks[0] if stocks else None)
        exp = str((lead or {}).get("expound") or "")
        tag_line = exp.splitlines()[0].strip() if exp else ""
        body = "\n".join(exp.splitlines()[1:]).strip()
        # P2-2（review）：板块级 doc（leader_code 空）回退取韭研分组首只成员——
        # 不得冒称「龙头」（与双龙一结构行可能互相矛盾），显式标注身位
        # （2026-10-30g：「韭研分组序，非推导龙一」精简为「非龙一」，防误读保留）
        lead_label = "龙头" if str(leader_code or "") else "板内成员（非龙一）"
        # 回退榜单日期显式入行（数据事实，非开发注释；AGENTS §1.2-8）
        l2_tag = f"，{l2_date} 榜单" if l2_date != date else ""
        if lead is not None and exp:
            board_resolved = True
            lead_chars = (leader_expound_chars
                          if leader_code and leader_expound_chars else content_chars)
            lines.append(f"板内解析（「{board_name}」{board_stocks_n} 只{l2_tag}）："
                         f"{lead_label} {lead.get('name')}（{lead.get('code')}）驱动标签「{tag_line}」｜"
                         f"解析摘录：{_clip_excerpt(_compress_enum(body or exp), lead_chars)}")
        elif lead is not None:
            lines.append(f"板内解析（「{board_name}」{board_stocks_n} 只{l2_tag}）："
                         f"{lead_label} {lead.get('name')}（{lead.get('code')}）无异动解析")
        peer_tags = []
        for p in [s for s in stocks if s is not lead][:5]:
            pe = str(p.get("expound") or "")
            pt = pe.splitlines()[0].strip() if pe else ""
            if pt:
                peer_tags.append(f"{p.get('name')}（{pt}）")
        if peer_tags:
            board_resolved = True
            lines.append("板内同伴驱动：" + "、".join(peer_tags))

    has_content = bool((node or {}).get("content")) and not _is_stub_content(node)
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
            "l2Date": l2_date if include_l2 else None,
            "l2FallbackUsed": bool(include_l2 and l2_date != date),
            "morningState": morning_state,
            "morningDate": morning_date,
            "morningHits": morning_hits,
            "flashState": flash_state,
            "flashDate": flash_date,
            "flashHits": flash_hits,
            "s3State": s3_state,
            "s3Term": s3_term,
            "s3Node": s3_node_name,
            "unmappedCandidates": match.get("candidates") or []}
