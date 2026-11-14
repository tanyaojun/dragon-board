# -*- coding: utf-8 -*-
"""韭研产业树一级节点 → 粗分组对照层（2026-11-14 用户裁决「采纳建议，请实施」）。

背景：产业树一级 108 节点为热点概念细粒度（单日「机器人」拆 4-5 个节点），涨停
打标链分组名为用户视角粗桶（近 60 日 168 名，与树一级 exact 重叠仅 32/168）——
竞价试盘页等消费方需统一到粗桶口径。**对照层非物理加层**：jiuyan_industry_stocks
为上游周频全量刷新（交易日 16:10 守卫挂链），物理加层必被冲掉（P4 对照桥非物理
改名同款教训，theme-governance-p1p4 §五B）。

映射来源（P4 范式粗粒度版）：
- auto_vote：一级节点成分股 × 近 60 日打标链分组归属投票，Top1 占比 ≥
  AUTO_VOTE_THRESHOLD（T3 重叠率双峰判据同款 0.40）自动落库（votes/members
  留审计字段）；2026-11-14 实测 107/108 节点有归属证据，Top1 与人工直觉一致；
- manual：CLI --set 人工固化（root 须在打标链分组名全集，有据收录）；
- 低置信 → unmapped 披露不落库（消费方保留 level-1 原值兜底，不猜）。
事件桶（公告/其他/新股/ST 板块/北交所等）不入粗桶词表、不入投票。
缓存：root_index 300s TTL（jiuyan_board 同规），reset 清缓存供测试/诊断。
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from backend.services.theme.industry_alias import EXCLUDE_WORDS

COLLECTION = "jiuyan_industry_root_mapping"
COLLECTION_ACTION = "jiuyan_action"
COLLECTION_INDUSTRY_STOCKS = "jiuyan_industry_stocks"
AUTO_VOTE_THRESHOLD = 0.40     # T3 重叠率双峰判据同款（§五A：≥0.40 自动晋升）
HIST_DAYS = 60                 # 打标链归属证据窗口（与读口 boardHist 兜底同窗）
VOTE_EXCLUDE = EXCLUDE_WORDS | {"ST板块", "北交所", "摘帽", "摘帽相关", "ST相关"}

# 粗桶同义归一种子（2026-11-14 用户确认口径：同一概念定一个主名，票数按主名合并）。
# 背景：打标链分组名为编辑手写、同名漂移频繁（医疗医药/医药医疗、液冷散热/AI散热/
# AI液冷/数据中心散热…日期区间交叠或衔接），不归一则同义桶分摊票数（低置信假阳性）
# 且左表同义板块并存。主名取主流（档数高/近期仍用/名称干净）。纯同义合并，
# 不合并真细分（算力租赁不动待验，油服/电子布等独立概念不动）。库内
# jiuyan_root_alias manual 行可覆盖种子（改主名/增别名不改代码）。
ROOT_ALIAS_SEED: dict[str, str] = {
    "医药医疗": "医疗医药",
    "AI散热": "液冷散热", "AI液冷": "液冷散热", "AI液冷散热": "液冷散热",
    "数据中心散热": "液冷散热", "金刚石散热": "液冷散热",
    "有色": "有色金属", "有色资源": "有色金属", "金属有色": "有色金属",
    "房地产": "地产", "地产基建": "地产", "地产产业链": "地产",
    "被动元器件": "被动元件",
    "稀土磁材": "稀土永磁",
    "影视短剧": "短剧", "AI短剧": "短剧",
    "AI端侧": "端侧AI",
    "无人驾驶": "智能驾驶",
    "农业": "农林牧渔", "大农业": "农林牧渔",
    "存储芯片": "存储",
    "国产半导体": "国产芯片",
    "算力租赁": "算力",
    "玻璃基板封装": "玻璃基板",
    "钨金属": "钨",
    "光刻机(胶)": "光刻机",
    "AI影视/传媒": "AI影视",
    "出版传媒": "传媒",
    "核聚变": "可控核聚变",
    "消费": "大消费",
    "油服": "油气",
    "航运": "港口航运",
    "电子布": "玻纤",
}
COLLECTION_ALIAS = "jiuyan_root_alias"   # 库内覆盖行（_id=别名 → rootName=主名）
_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def reset_jiuyan_industry_root_cache() -> None:
    """清空进程内对照缓存（测试换假库 / 手工诊断用）。"""
    _CACHE.clear()


def canonical_root(name: str, alias: dict[str, str]) -> str:
    """分组名 → 主名（别名表命中则归一，未命中原样；fail-visible 不猜）。"""
    n = str(name or "").strip()
    return alias.get(n, n)


def root_alias_map(db: Any) -> dict[str, str]:
    """别名→主名（种子 ∪ 库内 manual 覆盖；读异常回落种子，不阻断）。"""
    out = dict(ROOT_ALIAS_SEED)
    try:
        for d in db[COLLECTION_ALIAS].find({}, {"rootName": 1}):
            a = str(d.get("_id") or "").strip()
            m = str(d.get("rootName") or "").strip()
            if a and m:
                out[a] = m
    except Exception:
        pass
    return out


def daban_root_vocab(db: Any) -> list[str]:
    """粗桶主名词表（打标链分组名去事件桶 + 同义归一后去重）——
    粗桶全集 + manual_set 校验依据。"""
    alias = root_alias_map(db)
    out: set[str] = set()
    for doc in db[COLLECTION_ACTION].find({}, {"fields.name": 1}):
        for f in doc.get("fields") or []:
            n = str((f or {}).get("name") or "").strip()
            if n and n not in VOTE_EXCLUDE:
                out.add(canonical_root(n, alias))
    return sorted(out)


def _stock_group_votes(db: Any, alias: dict[str, str]) -> dict[str, Counter]:
    """code → 历史打标链分组归属投票（近 HIST_DAYS 日，事件桶不入，票数按主名
    合并；tradingDate Python 侧排序，FakeCol 测试约束同 jiuyan_board）。"""
    docs = list(db[COLLECTION_ACTION].find(
        {}, {"tradingDate": 1, "fields.name": 1, "fields.stocks.code": 1}))
    docs = sorted((d for d in docs if isinstance(d, dict)),
                  key=lambda x: str(x.get("tradingDate") or ""))[-HIST_DAYS:]
    votes: dict[str, Counter] = defaultdict(Counter)
    for doc in docs:
        for f in doc.get("fields") or []:
            n = str((f or {}).get("name") or "").strip()
            if not n or n in VOTE_EXCLUDE:
                continue
            n = canonical_root(n, alias)
            for s in f.get("stocks") or []:
                c = str((s or {}).get("code") or "")[-6:]
                if c:
                    votes[c][n] += 1
    return votes


def build_root_votes(db: Any) -> dict[str, dict[str, Any]]:
    """一级节点 → 投票建议（纯读，不落库；票按主名合并）：{node: {root, top1Ratio,
    topVotes, totalVotes, membersTagged, top3}}。top3 供审计/低置信人工裁决参考。"""
    votes = _stock_group_votes(db, root_alias_map(db))
    out: dict[str, dict[str, Any]] = {}
    for d in db[COLLECTION_INDUSTRY_STOCKS].find({}, {"name": 1, "stocks.code": 1}):
        node = str(d.get("name") or "").strip()
        if not node:
            continue
        cnt: Counter = Counter()
        members = 0
        for s in d.get("stocks") or []:
            c = str((s or {}).get("code") or "")[-6:]
            if c in votes:
                members += 1
                cnt += votes[c]
        if not members or not cnt:
            continue
        top = cnt.most_common()
        total = sum(cnt.values())
        out[node] = {"root": top[0][0], "top1Ratio": round(top[0][1] / total, 4),
                     "topVotes": top[0][1], "totalVotes": total,
                     "membersTagged": members,
                     "top3": [f"{k}({v})" for k, v in top[:3]]}
    return out


def rebuild_roots(db: Any, *, threshold: float = AUTO_VOTE_THRESHOLD) -> dict[str, Any]:
    """幂等重建 auto_vote 行（manual 不动；低置信不落、unmapped 披露）。返回摘要。"""
    vocab = set(daban_root_vocab(db))
    suggestions = build_root_votes(db)
    if not suggestions:
        return {"ok": False, "reason": "无投票证据（打标链日档或产业成分库为空）",
                "added": [], "changed": [], "unmapped": list(suggestions)}
    added: list[str] = []
    changed: list[str] = []
    unmapped: list[dict] = []
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for node, sug in sorted(suggestions.items()):
        existing = db[COLLECTION].find_one({"_id": node}) or {}
        if existing.get("matchType") == "manual":
            continue
        root = sug["root"]
        if root not in vocab or sug["top1Ratio"] < threshold:
            unmapped.append({"node": node, "top3": sug["top3"],
                             "top1Ratio": sug["top1Ratio"],
                             "reason": "low_confidence" if root in vocab else "root_not_in_vocab"})
            if existing:   # stale auto_vote 行不再达标 → 回退删除（人工裁决入口，manual 不动）
                db[COLLECTION].delete_one({"_id": node})
                changed.append(f"-{node}")
            continue
        if existing.get("rootName") == root and existing.get("matchType") == "auto_vote":
            continue
        (added if not existing else changed).append(node)
        db[COLLECTION].replace_one(
            {"_id": node},
            {"_id": node, "nodeName": node, "rootName": root,
             "matchType": "auto_vote", "top1Ratio": sug["top1Ratio"],
             "topVotes": sug["topVotes"], "totalVotes": sug["totalVotes"],
             "membersTagged": sug["membersTagged"], "top3": sug["top3"],
             "mappedAt": existing.get("mappedAt") or now, "updatedAt": now},
            upsert=True)
    return {"ok": True, "threshold": threshold, "nodes": len(suggestions),
            "added": added, "changed": changed, "unmapped": unmapped}


def manual_set(db: Any, node: str, root: str) -> dict[str, Any]:
    """人工固化归属（root 须在打标链分组名全集）；root 空串=删除该行回 auto。"""
    node = str(node or "").strip()
    root = str(root or "").strip()
    if not node:
        return {"ok": False, "error": "missing_node"}
    if not root:
        db[COLLECTION].delete_one({"_id": node})
        reset_jiuyan_industry_root_cache()
        return {"ok": True, "deleted": node}
    if root not in set(daban_root_vocab(db)):
        return {"ok": False, "error": f"打标链分组名全集无此粗桶: {root}"}
    db[COLLECTION].replace_one(
        {"_id": node},
        {"_id": node, "nodeName": node, "rootName": root, "matchType": "manual",
         "mappedAt": time.strftime("%Y-%m-%dT%H:%M:%S")},
        upsert=True)
    reset_jiuyan_industry_root_cache()
    return {"ok": True, "node": node, "rootName": root}


def root_index(db: Any) -> dict[str, str]:
    """node → 粗桶名全量（300s TTL 缓存；读库异常 → 空索引 + reason 留痕，不阻断）。"""
    hit = _CACHE.get("index")
    now = time.monotonic()
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1]
    index: dict[str, str] = {}
    reason = None
    try:
        for d in db[COLLECTION].find({}, {"rootName": 1}):
            node = str(d.get("_id") or "")
            root = str(d.get("rootName") or "")
            if node and root:
                index[node] = root
    except Exception as exc:  # noqa: BLE001 — 读库异常结构化留痕（jiuyan_board 同规）
        index = {}
        reason = f"read_failed: {type(exc).__name__}"
    if reason:   # 失败不进缓存：下次重试，不把失败冻 300s
        return index
    _CACHE["index"] = (now, index)
    return index


def root_index_meta(db: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """node → 粗桶名全量 + meta（读异常/空对照层结构化留痕；root_index 的带诊断版）。"""
    hit = _CACHE.get("index")
    now = time.monotonic()
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1], {"mapped": len(hit[1])}
    index: dict[str, str] = {}
    reason = None
    try:
        for d in db[COLLECTION].find({}, {"rootName": 1}):
            node = str(d.get("_id") or "")
            root = str(d.get("rootName") or "")
            if node and root:
                index[node] = root
    except Exception as exc:  # noqa: BLE001 — 读库异常结构化留痕（jiuyan_board 同规）
        index = {}
        reason = f"read_failed: {type(exc).__name__}"
    meta: dict[str, Any] = {"mapped": len(index)}
    if reason:
        meta["reason"] = reason   # 失败不进缓存：下次重试，不把失败冻 300s
        return index, meta
    _CACHE["index"] = (now, index)
    return index, meta


def root_of(db: Any, level1_name: str) -> str | None:
    """单节点归属（读口逐行消费走 root_index，本函数供单点查询/诊断）。"""
    return root_index(db).get(str(level1_name or ""))


def main(argv: list[str] | None = None) -> int:
    """CLI：--rebuild-root（幂等重建 auto_vote，manual 不动）/ --set "节点=粗桶"（人工
    固化，空值=删除回 auto）/ --list（对照全表）。纯本地零上游零模型。"""
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="韭研产业树一级节点→粗分组对照层（打标链板块名口径）")
    ap.add_argument("--rebuild-root", dest="rebuild_root", action="store_true",
                    help="成分股历史打标归属投票幂等重建 auto 行（Top1 占比≥0.40 落库，manual 不动）")
    ap.add_argument("--set", dest="manual", default=None,
                    help="人工固化：节点名=粗桶名（空值=删除回 auto）")
    ap.add_argument("--list", action="store_true", help="打印当前对照全表")
    args = ap.parse_args(argv)

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    out: dict[str, Any] = {}
    if args.rebuild_root:
        out = rebuild_roots(db)
    if args.manual:
        node, _, root = args.manual.partition("=")
        out = manual_set(db, node.strip(), root.strip())
    if args.list or not (args.rebuild_root or args.manual):
        rows = list(db[COLLECTION].find({}, {"_id": 0}).sort("_id", 1))
        out["list"] = [{"node": r.get("nodeName"), "root": r.get("rootName"),
                        "matchType": r.get("matchType"), "top1Ratio": r.get("top1Ratio")}
                       for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
