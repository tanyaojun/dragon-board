# -*- coding: utf-8 -*-
"""jev state 构建器：把锚定帧/行/情绪桶压缩为 jev 评估 state（纯函数，无 IO）。

fail-visible：缺源记 quality.degraded，保持 None/空，不伪造零值。
见 quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §5/§8。
"""
from __future__ import annotations

STAGE_KEYS = ("ignition", "expansion", "crowded", "reversal", "cooling", "unknown")
STOCK_LIMIT = 15
ZT_EPS = 0.999


def _degraded(items: list, code: str, detail: str) -> None:
    items.append({"code": code, "detail": detail[:120]})


def _market(frame: dict, deg: list) -> dict:
    """market 层：marketStats 优先（zt/dt/炸板率/涨跌比/晋级率），limitSummary.zhaban 兜底。"""
    ms = frame.get("marketStats") or {}
    ls = frame.get("limitSummary") or {}
    idx = frame.get("indices") or {}
    m: dict = {}
    if "sh" in idx and isinstance(idx["sh"], dict):
        m["sh"] = round(idx["sh"]["change"], 2)
    if "zz500" in idx and isinstance(idx["zz500"], dict):
        m["zz500"] = round(idx["zz500"]["change"], 2)

    zt = ms.get("ztCount")
    dt = ms.get("dtCount")
    zb = (ms.get("zhaban") or {}).get("rate")
    if zb is None:
        zb = (ls.get("zhaban") or {}).get("rate")
    up, down = ms.get("upCount"), ms.get("downCount")
    if up is not None and down is not None and (up + down) > 0:
        m["upRatio"] = round(up / (up + down), 3)
    boards = ms.get("limitData") or ls.get("continuousBoards") or {}
    yiban, promoted = boards.get("yiban"), 0
    for k in ("erban", "sanban", "sibanPlus"):
        promoted += boards.get(k) or 0
    if yiban:
        m["promotionRate"] = round(promoted / yiban, 3)
    for k, v in (("zt", zt), ("dt", dt), ("zhabanRate", zb)):
        if v is not None:
            m[k] = v
        else:
            _degraded(deg, "market", f"{k} 缺失（marketStats/limitSummary 均无）")
    return m


def _lifecycle(sentiment_doc: dict | None, prev_counts: dict | None, deg: list) -> dict | None:
    if not sentiment_doc:
        _degraded(deg, "lifecycle", "情绪桶文档缺失")
        return None
    layers = (sentiment_doc.get("metrics") or {}).get("layers") or {}
    layer = layers.get("top50") or layers.get("all") or {}
    counts = layer.get("stageCounts")
    if counts is None:
        _degraded(deg, "lifecycle", "metrics.layers.top50.stageCounts 缺失")
        return None
    out: dict = {"counts": {k: int(counts.get(k) or 0) for k in STAGE_KEYS}}
    if prev_counts:
        out["migration"] = {k: int(counts.get(k) or 0) - int(prev_counts.get(k) or 0) for k in STAGE_KEYS}
    return out


def _stocks(rows: list, analysis_by_code: dict, deg: list) -> list:
    def sort_key(r):
        return (-(r.get("heat") or 0), r.get("rank") if r.get("rank") is not None else 9999)

    out = []
    for r in sorted(rows, key=sort_key)[:STOCK_LIMIT]:
        price, lup = r.get("price"), r.get("limitUpPrice")
        zt = bool(price and lup and price >= lup * ZT_EPS)
        stage = analysis_by_code.get(r.get("code"))
        if stage is None:
            _degraded(deg, "stock_stage_missing", f"{r.get('code')} 无 displayStatus.stage")
        speed = r.get("speed")
        out.append({
            "n": r.get("name"),
            "s": stage,
            "pct": round(r["pctChange"], 2) if r.get("pctChange") is not None else None,
            "spd": round(speed, 2) if speed is not None else None,
            "zt": zt,
            "heat": r.get("heat"),
            "th": r.get("mainTheme"),
        })
    return out


def build_replay_state(frame: dict, rows: list, analysis_by_code: dict,
                       sentiment_doc: dict | None, prev_counts: dict | None,
                       prev_codes: set) -> dict:
    """锚定帧 + 行 + 行级 stage 映射 + 情绪桶 → jev state（§5 四层结构）。"""
    deg: list = []
    codes = {r.get("code") for r in rows if r.get("code")}
    return {
        "asOf": f"{frame.get('tradingDate')} {frame.get('slotTime')}",
        "slot": (frame.get("slotTime") or "").replace(":", "") + "+0",
        "market": _market(frame, deg),
        "lifecycle": _lifecycle(sentiment_doc, prev_counts, deg),
        "stocks": _stocks(rows, analysis_by_code, deg),
        "hotlist": {"platforms": len({p for r in rows for p in (r.get("platforms") or [])}),
                    "entries": len(rows),
                    "newEntries": len(codes - set(prev_codes or set()))},
        "quality": {"degraded": deg},
    }
