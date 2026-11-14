# -*- coding: utf-8 -*-
"""韭研板块名（产业树一级节点）→ 个股归属索引（2026-11-06，上涨/下跌复盘「板块」字段）。

单一事实源 = `jiuyan_industry_stocks`（韭研产业树 stock-tree 全成分快照，
`operations/jiuyan_theme_store.save_industry_stocks` 落库、交易日 16:10 周频守卫刷新）。
消费方：`jev_rise_review` / `jev_dieban_review` / 竞价试盘读口 —— board = 韭研粗桶名
（2026-11-14 用户裁决：一级节点经 jiuyan_industry_root 对照层归一到打标链粗桶口径，
unmapped 节点保留一级原值兑底，rootMapped/rootReason 入 meta）；韭研未收录的个股
board 置空（页面显示「未分板块」，2026-11-06 用户裁决：不回推主题材名，避免单列双口径）。

归属规则（确定性，不猜）：节点按 `_id` 升序，取**首个**收录该股的一级产业；
一股多产业不聚合（board 保持单值语义，板块 chips/筛选/分布共用）。
产业库空 → 索引为空 + meta.nodes=0，调用方 fail-visible 记 degraded，不得静默全量回退。

全 monkeypatch 测试约束（§1.2-7）：FakeCol.find 返回 list，禁止链式 `.sort()`，
排序在 Python 侧完成；模块缓存随进程存活，测试经 `reset_jiuyan_board_cache()` 清空。
"""
from __future__ import annotations

import time
from typing import Any

from backend.operations.jiuyan_theme_store import COLLECTION_INDUSTRY_STOCKS

_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict[str, str], dict[str, Any]]] = {}
_CACHE_KEY = "index"


def reset_jiuyan_board_cache() -> None:
    """清空进程内索引缓存（测试换假库 / 手工诊断用）。"""
    _CACHE.clear()


def board_index(db: Any) -> tuple[dict[str, str], dict[str, Any]]:
    """返回 (code → 韭研板块粗桶主名, meta)（2026-11-14 归一后：同义漂移经
    root_alias 归一到主名，unmapped 节点保留一级原值，见下方归一段）。

    meta = {batchDate, nodes, codes}：batchDate 成分快照批次（多批次并存取最大值）、
    nodes 收录一级产业数、codes 去重后可归属个股数；读库异常时 meta 额外带
    reason='industry_stocks_read_failed'（不进缓存，下次重试）。库空/缺失 →
    ({}, {batchDate: None, nodes: 0, codes: 0})（fail-visible，不抛异常）。
    """
    hit = _CACHE.get(_CACHE_KEY)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1], hit[2]
    index: dict[str, str] = {}
    nodes = 0
    batches: list[str] = []
    read_failed = False
    try:
        docs = db[COLLECTION_INDUSTRY_STOCKS].find(
            {"stockN": {"$gt": 0}}, {"name": 1, "batchDate": 1, "stocks.code": 1})
    except Exception:                       # 读库异常 → 空索引，不阻断读口主链（§4.0）
        docs = []
        read_failed = True                  # 根因区分：读库失败 ≠ 产业库真空（review minor）
    for d in sorted((x for x in docs if isinstance(x, dict)),
                    key=lambda x: str(x.get("_id") or "")):
        name = str(d.get("name") or "")
        if not name:
            continue
        nodes += 1
        if d.get("batchDate"):
            batches.append(str(d["batchDate"]))
        for s in d.get("stocks") or []:
            code = str((s or {}).get("code") or "")[-6:]
            if code and code not in index:
                index[code] = name
    meta: dict[str, Any] = {"batchDate": max(batches) if batches else None,
                            "nodes": nodes, "codes": len(index)}
    if read_failed:
        meta["reason"] = "industry_stocks_read_failed"   # 调用方据此组装 degraded 根因
        return index, meta                  # 失败不进缓存：下次轮询重试，不把失败冻 300s
    # 粗桶归一（2026-11-14 用户裁决）：一级节点太细（单日机器人拆 4-5 节点）而打标链
    # 分组名粗——board 归一到打标链粗桶口径（jiuyan_industry_root_mapping 对照层，
    # 非物理加层）；unmapped 节点保留一级原值兑底（不猜）；对照层数/异常入 meta
    # （rootMapped=0 为合法态=对照层未建，调用方不必 degraded）。
    try:
        from backend.services.jev import jiuyan_industry_root
        r_idx, r_meta = jiuyan_industry_root.root_index_meta(db)
    except Exception as exc:                # noqa: BLE001 — 归一层不可用不阻断主链
        r_idx, r_meta = {}, {"reason": f"root_import_failed: {type(exc).__name__}"}
    if r_idx:
        index = {c: r_idx.get(b, b) for c, b in index.items()}
    meta["rootMapped"] = len(r_idx)
    if r_meta.get("reason"):
        meta["rootReason"] = r_meta["reason"]
    _CACHE[_CACHE_KEY] = (now, index, meta)
    return index, meta


def apply_boards(stocks: list[dict], index: dict[str, str]) -> None:
    """就地改写 stock 字典列表：board = 韭研产业名，未收录置空（不回推主题材名）。

    boardSource 语义：'jiuyan'＝韭研产业树一级节点归属；None＝韭研未收录
    （board 置空，前端显示「未分板块」；2026-11-06 用户裁决不回退主题材名，
    避免同一列混两种板块体系）。
    """
    for s in stocks or []:
        if not isinstance(s, dict):
            continue
        code = str(s.get("code") or "")[-6:]
        jy = index.get(code)
        if jy:
            s["board"] = jy
            s["boardSource"] = "jiuyan"
        else:
            s["board"] = None
            s["boardSource"] = None
