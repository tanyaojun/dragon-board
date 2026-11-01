"""韭研板块 ↔ KPL 板块名录每日匹配诊断（2026-11-01 用户需求：每日实时检查
两套名录到底多少没匹配上，未匹配清单 = ALIASES 异名表维护候选）。

口径（用户裁决纠偏 2026-11-01）：
- KPL 名录 = 当日板块排行**全量**（kpl_ranking_service.get_sector_ranking），
  不是「今日有涨停事件的 plate」子集——那是封板归属口径，不是名录口径；
- 匹配规则单一事实源 = theme_event_digest（normalize_name + ALIASES + 经济/
  产业后缀桥，board_keywords 同链），前端不再镜像造轮子；
- 双向：韭研→KPL 逐板块匹配诊断；KPL→韭研反向覆盖统计（KPL 细分板块
  天然多于韭研粗分桶，未覆盖清单折叠透出，不做静默省略）。

fail-visible：韭研档缺失 / KPL 排行不可用 → ok=False + reason，不静默空表。
纯读零模型调用、零写入。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist import theme_event_digest as digest
from backend.operations.jiuyan_store import get_action_doc, list_action_dates

# 语义桥（2026-11-01 用户拍板第 2 轮）：韭研泛指/事件桶 → KPL 细分板块的
# 一对多映射。常规桥（same/alias/suffix/contains）是同名系匹配，覆盖不了
# 「泛指桶↔细分板块」与「事件桶↔业绩板块」两类真实趋同：
# - 大消费（pan 泛指桥）：泛指食品/饮料/白酒/零售/旅游等行业——成员清单
#   来源：①web 归类（申万大消费 9-10 个一级：农林牧渔/食品饮料/家用电器/
#   纺织服饰/轻工制造/商贸零售/美容护理/社会服务，部分口径含汽车传媒）
#   ②韭研档成分实证（2026-10-30 大消费 6 票：古井贡酒/皇台酒业=白酒、
#   泉阳泉=饮用水、阳光乳业=乳业、东方海洋=水产、浙江东日=商贸）。
#   匹配规则=KPL 归一名与成员词互含（len≥2，与 contains 同哲学）；
#   「消费电子」是科技属性不在成员清单，天然不误命中。
# - 公告（event 事件桥）：公告利好多为上市公司自身业绩驱动（用户裁决），
#   与 KPL「三季报增长」高度趋同；模糊匹配（KPL 归一名含关键词即命中），
#   不做全词等值。重组/中标/收购等事件型关键词未收录，待用户后续裁决。
SEMANTIC_BRIDGES: dict[str, dict[str, Any]] = {
    "大消费": {
        "way": "pan",
        "members": ("食品饮料", "白酒", "啤酒", "乳业", "乳制品", "零食",
                    "预制菜", "食品", "饮料", "农业", "农林牧渔", "养殖",
                    "水产", "种业", "猪肉", "零售", "商贸零售", "新零售",
                    "百货", "免税", "电商", "跨境电商", "旅游", "文旅",
                    "酒店", "餐饮", "纺织服装", "服装", "家电", "家用电器",
                    "美容护理", "医美"),
        "note": "泛指食品/饮料/白酒/零售/旅游等（web 申万归类+韭研档成分实证）",
    },
    "公告": {
        "way": "event",
        "keywords": ("增长", "业绩", "预增", "扭亏"),
        "note": "公告利好多业绩驱动，模糊匹配 KPL 名含关键词（用户拍板非全词）",
    },
}

# KPL 指认存在白名单（2026-11-01 领域专家逐条确认）：排行只列当日有封板事件的
# 活跃板块，KPL 完整名录大于它——冷门/事件板块不在排行内，alias 写了也无 KPL
# 名可命中；无完整名录接口前以白名单并入匹配全集（有据收录，不猜名），
# 当日读口与历史覆盖脚本同源共用（单一事实源）。
KPL_EXTRA_BOARDS: tuple[str, ...] = ("冰雪产业", "美伊战争", "俄乌重建",
                                     "厄尔尼诺", "AI硬件")


def check_sector_names(db: Any, date: str | None = None,
                       kpl_ranking: dict | None = None,
                       kpl_names: list[str] | None = None) -> dict[str, Any]:
    """名录对照诊断。kpl_ranking=get_sector_ranking 产物或直接给 names（测试注入）。"""
    dates = list_action_dates(db)
    target = date or (dates[-1]["date"] if dates else None)
    # 跨日回退（与 jiuyan-action 读口同哲学）：请求日无档 → < 请求日最近有档日；
    # 非交易日/隔日看盘如实透出实际档日，不伪造
    doc = None
    served = target
    if target:
        for k in ("final", "midday"):
            doc = get_action_doc(db, target, k)
            if doc:
                break
        if doc is None:
            earlier = [d["date"] for d in dates if d["date"] < target]
            if earlier:
                served = earlier[-1]
                for k in ("final", "midday"):
                    doc = get_action_doc(db, served, k)
                    if doc:
                        break
    if doc is None:
        return {"ok": False, "reason": f"jiuyan_doc_missing:{target or 'no_dates'}"}

    fields = doc.get("fields") or []
    boards = [str(f.get("name") or "").strip() for f in fields]
    boards = [b for b in boards if b]

    if kpl_names is None:
        kpl_names = [str((it or {}).get("name") or "").strip()
                     for it in ((kpl_ranking or {}).get("items") or [])]
    names = [n for n in kpl_names if n]
    kpl_total = len(names)

    # KPL 归一索引：归一名 → [KPL 原名]（KPL 名与韭研名同规则归一）；
    # 并入指认存在白名单（冷门板块不在当日活跃排行，见 KPL_EXTRA_BOARDS）
    kpl_idx: dict[str, list[str]] = {}
    for n in list(names) + [b for b in KPL_EXTRA_BOARDS if b not in names]:
        kpl_idx.setdefault(digest.normalize_name(n) or n, []).append(n)

    rows: list[dict[str, Any]] = []
    stats = {"same": 0, "alias": 0, "suffix": 0, "contains": 0, "semantic": 0,
             "unmatched": 0}
    list_n_by_board = {str(f.get("name") or "").strip(): len(f.get("stocks") or [])
                       for f in fields}
    excluded: list[dict[str, Any]] = []
    union_keys: set[str] = set()
    for b in boards:
        bridge = SEMANTIC_BRIDGES.get(b)
        admin = digest.is_not_a_theme(b)
        # 行政桶（公告/其他/ST 等）本来就不映射，单列不进未匹配统计——
        # 判定单一事实源 = digest.is_not_a_theme（原始名+归一名双口径）；
        # 例外：有语义桥的桶（公告）参与桥匹配，不再静默单列（用户拍板）
        if admin and not bridge:
            excluded.append({"board": b, "listN": list_n_by_board.get(b, 0)})
            continue
        keys = digest.board_keywords(b)
        union_keys.update(keys)
        base = digest.normalize_name(b)
        alias_norms = {digest.normalize_name(a) for a in digest.ALIASES.get(base, ())}
        hit_names: list[str] = []
        way = None
        bridge_note = None
        for k in keys:
            if k in kpl_idx:
                hit_names = kpl_idx[k]
                way = ("same" if k == base
                       else "alias" if k in alias_norms else "suffix")
                break
        if not way:
            # 双向包含（与 match_industry 同哲学；len≥2 防单字误伤）：
            # 真实对照实证：韭研「医疗医药」↔ KPL「医药」（包含但非等值）
            contains = sorted({n for nk, ns in kpl_idx.items()
                               if len(nk) >= 2 and (base in nk or nk in base)
                               for n in ns})
            if contains:
                hit_names, way = contains, "contains"
        if not way and bridge:
            # 语义桥（一对多）：泛指桶成员互含 / 事件桶关键词模糊匹配
            if bridge["way"] == "pan":
                hits = sorted({n for nk, ns in kpl_idx.items()
                               if any(m == nk or (len(m) >= 2 and (m in nk or nk in m))
                                      for m in bridge["members"])
                               for n in ns})
            else:
                hits = sorted({n for nk, ns in kpl_idx.items()
                               if any(len(wd) >= 2 and wd in nk
                                      for wd in bridge["keywords"])
                               for n in ns})
            if hits:
                hit_names, way = hits, "semantic"
                bridge_note = bridge.get("note")
        if way:
            stats[way] += 1
            rows.append({"board": b, "listN": list_n_by_board.get(b, 0),
                         "matched": True, "way": way,
                         "bridgeNote": bridge_note, "kplNames": hit_names})
        elif admin:
            # 有桥但桥未命中的行政桶：仍单列（不进未匹配统计）
            excluded.append({"board": b, "listN": list_n_by_board.get(b, 0)})
        else:
            stats["unmatched"] += 1
            rows.append({"board": b, "listN": list_n_by_board.get(b, 0),
                         "matched": False, "way": None,
                         "bridgeNote": None, "kplNames": []})
    unmatched_jiuyan = [r["board"] for r in rows if not r["matched"]]

    # 反向覆盖：KPL 名归一后与任一韭研匹配键等值 / 双向包含 → 已覆盖；
    # 被语义桥（泛指成员/事件关键词）命中的也算覆盖
    pan_members = [m for v in SEMANTIC_BRIDGES.values() if v["way"] == "pan"
                   for m in v["members"]]
    event_kws = [w for v in SEMANTIC_BRIDGES.values() if v["way"] == "event"
                 for w in v["keywords"]]
    covered, uncovered = [], []
    for nk, originals in kpl_idx.items():
        hit = nk in union_keys or any(nk in k or k in nk for k in union_keys if len(k) >= 2)
        if not hit:
            hit = any(m == nk or (len(m) >= 2 and (m in nk or nk in m))
                      for m in pan_members) or any(w in nk for w in event_kws)
        (covered if hit else uncovered).extend(originals)

    return {"ok": True, "date": served, "dateRequested": target,
            "dateFallback": served != target,
            "kind": doc.get("kind") or "final",
            "jiuyanTotal": len(boards), "kplTotal": kpl_total,
            "stats": stats, "rows": rows,
            "excludedBuckets": excluded,
            "unmatchedJiuyan": unmatched_jiuyan,
            "uncoveredKpl": sorted(uncovered),
            "uncoveredKplN": len(uncovered)}
