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

import re
import time
from typing import Any

from backend.operations.jiuyan_theme_store import COLLECTION_INDUSTRY_STOCKS

_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict[str, str], dict[str, Any]]] = {}
_CACHE_KEY = "index"


def reset_jiuyan_board_cache() -> None:
    """清空进程内索引缓存与板块名称桥缓存（测试换假库 / 手工诊断用）。"""
    _CACHE.clear()
    _BRIDGE_CACHE.clear()


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


# ══════════ jiuyan↔KPL 板块名称桥（2026-11-14 落地；2026-11-15 自 api 路由下沉
# service 单源：竞价龙头读口 / 竞价试盘读口 / 竞价强度第三源 / 评估脚本共用，
# 消除 analysis→api 耦合，AGENTS §2.2 三层分离）══════════
# 用户指路：未分组 40+ 主因 = 桥未接（theme_industry_mapping 202 条构建于 KPL 252
# 名录，未覆盖打板页 bk_name 词表，48 只未分组 bk 仅命中 2）+ 韭研产业树为热点
# 概念树（一级 108 节点），医药/环保/水务等传统行业树上无节点。桥接链三级：
#   ① theme_industry_mapping（P4 治理桥，_id=KPL 题材名 → industryNames）
#   ② sector_industry_mapping（板块节点 V3 桥，board → industryNames）
#   ③ industry_alias.suggest_for 同引擎实时建议（exact/contains/multi-union）
#   ④ 近 60 日打标链涨停分组最近归属兑底（打标链个股身位；事件桶停用词不入）
# 映射/名单进程内 300s 缓存（board_index 同规）；纯读零写入零上游外呼。
_BRIDGE_CACHE: dict[str, tuple[float, dict]] = {}
_BRIDGE_TTL_S = 300.0


def _norm_bk(value: object) -> str:
    """KPL bk_name 归一：去尾部计数括号「半导体(3)」→「半导体」，再去 概念/板块 后缀
    （industry_alias._normalize 同链，单一事实源不镜像造轮子）。"""
    s = str(value or "").strip()
    s = re.sub(r"（[^（]*）$|\([^)]*\)$", "", s).strip()
    try:
        from backend.services.theme.industry_alias import _normalize
        return _normalize(s)
    except Exception:
        return s


def _bridge_maps(db: Any) -> dict:
    """桥原料一次载入（300s 缓存）：names=stock_names 字典、maps={theme,sector}、
    inds=产业树一级节点名、hist=近 60 日打标链 (date, name, codes) 升序序列。
    各原料读失败结构化留痕（*_error），不阻断读口主链（§4.0）。"""
    hit = _BRIDGE_CACHE.get("maps")
    now = time.monotonic()
    if hit is not None and now - hit[0] < _BRIDGE_TTL_S:
        return hit[1]
    out: dict = {"names": {}, "maps": [], "inds": [], "hist": [],
                 "histError": None, "sourceErrors": {}}
    try:
        for s in db["stock_names"].find({}, {"code": 1, "name": 1}):
            c = str(s.get("code") or "")[-6:]
            if c and c not in out["names"]:
                out["names"][c] = str(s.get("name") or "")
    except Exception as exc:
        out["names"] = {}
        out["maps"] = []
        out["histError"] = f"stock_names:{type(exc).__name__}"
        out["sourceErrors"]["stock_names"] = out["histError"]
        return out   # 失败态不缓存（review minor-1）：下一请求重试，不冻 300s 降级原料
    for col, key in (("theme_industry_mapping", "theme"), ("sector_industry_mapping", "sector")):
        m: dict[str, list[str]] = {}
        try:
            for x in db[col].find({}, {"industryNames": 1, "board": 1}):
                names = [str(n) for n in (x.get("industryNames") or []) if n]
                if names:
                    m[str(x.get("board") or x["_id"])] = names
        except Exception as exc:
            out["histError"] = out["histError"] or f"{col}:{type(exc).__name__}"
            out["sourceErrors"][col] = f"{col}:{type(exc).__name__}"
        out["maps"].append({"key": key, "map": m})
    try:
        out["inds"] = [str(d["name"]) for d in db["jiuyan_industry_stocks"].find({}, {"name": 1}) if d.get("name")]
    except Exception as exc:
        out["inds"] = []
        out["sourceErrors"]["jiuyan_industry_stocks"] = f"inds:{type(exc).__name__}"
    try:
        docs = list(db["jiuyan_action"].find(
            {}, {"tradingDate": 1, "fields.name": 1, "fields.stocks.code": 1}))
        docs = sorted((d for d in docs if isinstance(d, dict)),
                      key=lambda x: str(x.get("tradingDate") or ""))[-60:]
        out["hist"] = [(str(d.get("tradingDate") or ""), d.get("fields") or []) for d in docs]
    except Exception as exc:
        out["hist"] = []
        out["histError"] = out["histError"] or f"jiuyan_action:{type(exc).__name__}"
        out["sourceErrors"]["jiuyan_action"] = f"jiuyan_action:{type(exc).__name__}"
    if out["sourceErrors"]:
        return out   # 部分原料降级：不缓存，下一请求重试（§4.0 不把故障冻成常态）
    _BRIDGE_CACHE["maps"] = (now, out)
    return out


def _bridge_lookup(bk_name: object, maps: list[dict], inds: list[str]) -> list[str]:
    """bk_name → 桥接板块名（① 治理桥 → ② V3 桥 → ③ suggest_for 同引擎实时建议）。
    多命中（multi-union）全保留（前端每组各计一次）；全 miss → []。"""
    bk = str(bk_name or "").strip()
    if not bk:
        return []
    norm = _norm_bk(bk)
    for m in maps:
        names = (m.get("map") or {}).get(norm) or (m.get("map") or {}).get(bk)
        if names:
            return names
    if not inds:
        return []
    try:
        from backend.services.theme.industry_alias import suggest_for
        sug = suggest_for(norm, inds)
    except Exception:
        sug = None
    return [str(n) for n in (sug or {}).get("names") or []]


def _bridge_hist(hist: list, need: set[str]) -> dict[str, list[str]]:
    """近 60 日打标链最近归属：code → 最近出现日的涨停分组名（同日多组全保留，
    事件桶 停用词不入（VOTE_EXCLUDE 单源含 ST板块/北交所/摘帽等，粗桶口径）；旧日期不再覆盖
    （最近身位优先，确定性）。"""
    try:
        from backend.services.jev.jiuyan_industry_root import VOTE_EXCLUDE
        _EXCL = VOTE_EXCLUDE
    except Exception:
        _EXCL = {"公告", "其他", "新股", "次新", "ST", "B股", "转债", "其他相关",
                 "ST板块", "北交所", "摘帽", "摘帽相关", "ST相关"}
    out: dict[str, list[str]] = {}
    for _date, fields in hist:   # hist 升序 → 后写覆盖 = 最近身位
        for f in fields or []:
            nm = str((f or {}).get("name") or "").strip()
            if not nm or nm in _EXCL:
                continue
            for s in f.get("stocks") or []:
                c = str((s or {}).get("code") or "")[-6:]
                if c in need:
                    out.setdefault(c, [])
                    if nm not in out[c]:
                        out[c].insert(0, nm)   # 同日多组：后组插前（fields 逆序优先，后组为更新身位）
    return out
