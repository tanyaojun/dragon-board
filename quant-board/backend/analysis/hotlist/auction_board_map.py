# -*- coding: utf-8 -*-
"""竞价龙头板块映射（2026-11-13 用户裁决二次修订）：取 **jiuyan 打标链 T−1 涨停分组
板块名**（`jiuyan_action {T−1}:final` fields 分组反查）。

病案链：①KPL 推送板块前缀是题材炒作概念（光伏/冰雪产业/羊年），与证据层口径错位；
②首版改韭研产业树全成分反查仍映射不上（产业树节点名/成分覆盖与涨停分组脱节，
2026-11-13 用户裁决作废）。**涨停分组名才是证据层单一口径**：板内解析
（board_snapshot fields name 精确相等）、产业树匹配、热度序列别名桥都消费它。

T−1 而非当日：09:26 晨间当日 final 尚未生成；T−1 涨停分组即昨日资金主战场。
多候选确定性序：①推送概念桥（归一包含/别名关键词，复用 digest 单实现）→
②分组成员数降序（主战场）→③组名升序。无命中/ T−1 final 缺席 → 回退推送概念 +
`boardSource=push_concept` 结构化留痕（fail-visible，不伪造映射）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist import theme_event_digest as digest

SOURCE_JIUYAN = "jiuyan_action_t1"
SOURCE_PUSH = "push_concept"


def load_board_context(db: Any, prev_date: str | None) -> dict:
    """一次取数全日共用：T−1 涨停分组反查索引 + 组成员数 + final 在场旗标。"""
    doc = (db["jiuyan_action"].find_one({"_id": f"{prev_date}:final"}, {"fields": 1})
           if prev_date else None) or {}
    index: dict[str, list[str]] = {}
    group_n: dict[str, int] = {}
    for f in doc.get("fields") or []:
        name = str(f.get("name") or "")
        if not name:
            continue
        stocks = [s for s in f.get("stocks") or [] if s]
        group_n[name] = len(stocks)
        for s in stocks:
            sc = str(s.get("code") or "")[-6:]
            if sc:
                index.setdefault(sc, []).append(name)
    return {"index": index, "groupN": group_n,
            "t1Final": bool(doc.get("fields")), "prevDate": prev_date}


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
    """返回 {board, boardSource, pickedBy, pushBoard, candidates, t1Final}。"""
    push = str(push_board or "").strip() or None
    names = list((ctx.get("index") or {}).get(str(code)[-6:], []))
    cands = [{"name": n, "n": (ctx.get("groupN") or {}).get(n, 0)} for n in names]
    base = {"pushBoard": push, "candidates": cands,
            "t1Final": bool(ctx.get("t1Final"))}
    if not cands:
        return {**base, "board": push, "boardSource": SOURCE_PUSH,
                "pickedBy": "push_fallback" if ctx.get("t1Final") else "t1_final_missing"}
    if len(cands) == 1:
        pick, by = cands[0], "t1_group"
    else:
        bridge = [c for c in cands if push and _push_bridge(push, c["name"])]
        pool, by = ((bridge, "push_bridge") if bridge else (cands, "group_size"))
        pick = sorted(pool, key=lambda c: (-c["n"], c["name"]))[0]
    return {**base, "board": pick["name"], "boardSource": SOURCE_JIUYAN,
            "pickedBy": by}