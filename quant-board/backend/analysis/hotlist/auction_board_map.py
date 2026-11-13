# -*- coding: utf-8 -*-
"""竞价龙头板块映射（2026-11-13 用户裁决）：推送概念 → 韭研板块名。

KPL 直播「竞价看龙头」的板块前缀是**题材炒作概念**（光伏/冰雪产业/羊年），与证据层
口径错位：产业树精确节点、韭研异动板内解析分组（`jiuyan_action {date}:final` fields
name 精确相等）、题材热度序列别名桥都按韭研板块名匹配——用推送概念会让三层证据
假性全缺、jev 判 insufficient（2026-11-13 日出东方/东方海洋病案）。

裁决：龙头板块归属取**韭研板块名**——`jiuyan_industry_stocks` 全成分反查；多候选
确定性选择序：①推送概念桥（归一双向包含/别名关键词，复用 digest 单实现）→
②当日韭研异动分组在场 → ③产业树 hot 降序 → ④code 升序。无成分映射 → 回退推送
概念 + `boardSource=push_concept` 结构化留痕（fail-visible，不伪造映射）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist import theme_event_digest as digest
from backend.operations import jiuyan_theme_store as S

SOURCE_JIUYAN = "jiuyan_industry"
SOURCE_PUSH = "push_concept"


def load_board_context(db: Any, date: str) -> dict:
    """一次取数全日共用：成分反查索引 + 当日异动分组名 + 产业树 hot。"""
    nodes = {str(n.get("code") or n.get("_id") or ""): n
             for n in S.get_industry_nodes(db)}
    index: dict[str, list[dict]] = {}
    for d in db[S.COLLECTION_INDUSTRY_STOCKS].find({}, {"name": 1, "stocks": 1}):
        code = str(d.get("_id") or "")
        name = str(d.get("name") or "")
        hot = (nodes.get(code) or {}).get("hot")
        for s in d.get("stocks") or []:
            sc = str(s.get("code") or "")[-6:]
            if sc:
                index.setdefault(sc, []).append(
                    {"code": code, "name": name, "hot": hot})
    act = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    groups = {digest.normalize_name(f.get("name"))
              for f in act.get("fields") or [] if f.get("name")}
    return {"index": index, "groups": groups, "nodes": nodes}


def _push_bridge(push_board: str, cand_name: str) -> bool:
    p = digest.normalize_name(push_board)
    c = digest.normalize_name(cand_name)
    if not p or not c:
        return False
    if p == c or p in c or c in p:
        return True
    return any(digest.normalize_name(k) in c
               for k in digest.board_keywords(push_board))


def resolve_leader_board(ctx: dict, code: str, push_board: str | None) -> dict:
    """返回 {board, boardSource, pickedBy, pushBoard, candidates}（candidates 留痕审计）。"""
    push = str(push_board or "").strip() or None
    cands = list((ctx.get("index") or {}).get(str(code)[-6:], []))
    base = {"pushBoard": push, "candidates": cands}
    if not cands:
        return {**base, "board": push, "boardSource": SOURCE_PUSH,
                "pickedBy": "push_fallback"}
    if len(cands) == 1:
        pick, by = cands[0], "single"
    else:
        bridge = [c for c in cands if push and _push_bridge(push, c["name"])]
        ingroup = [c for c in cands
                   if digest.normalize_name(c["name"]) in (ctx.get("groups") or set())]
        pool, by = ((bridge, "push_bridge") if bridge else
                    (ingroup, "action_group") if ingroup else (cands, "hot"))
        pick = sorted(pool, key=lambda c: (
            -(c["hot"] if isinstance(c.get("hot"), (int, float)) else -1e9),
            str(c["code"])))[0]
    return {**base, "board": pick["name"], "boardSource": SOURCE_JIUYAN,
            "pickedBy": by}