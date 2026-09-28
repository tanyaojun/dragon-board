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


def _market(frame: dict, sentiment_doc: dict | None, deg: list) -> dict:
    """market 层三级取数：frame.marketStats → 情绪桶 limitEvidence 重构 → limitSummary.zhaban。

    8 月老帧无 marketStats（实测 150/326），limitEvidence 覆盖 359/359，为通用兜底。
    """
    ms = frame.get("marketStats") or {}
    ls = frame.get("limitSummary") or {}
    idx = frame.get("indices") or {}
    le = ((sentiment_doc or {}).get("metrics") or {}).get("limitEvidence") or {}
    lem = le.get("market") or {}
    m: dict = {}
    if "sh" in idx and isinstance(idx["sh"], dict):
        m["sh"] = round(idx["sh"]["change"], 2)
    if "zz500" in idx and isinstance(idx["zz500"], dict):
        m["zz500"] = round(idx["zz500"]["change"], 2)

    zt = ms.get("ztCount")
    if zt is None:
        zt = lem.get("ztCount")
    dt = ms.get("dtCount")
    zb = (ms.get("zhaban") or {}).get("rate") or (ls.get("zhaban") or {}).get("rate")
    if zb is None:
        zbc, ztc = lem.get("zhabanCount"), lem.get("ztCount")
        if zbc is not None and ztc is not None and (zbc + ztc) > 0:
            zb = round(zbc / (zbc + ztc) * 100, 1)
    up, down = ms.get("upCount"), ms.get("downCount")
    if up is not None and down is not None and (up + down) > 0:
        m["upRatio"] = round(up / (up + down), 3)
    boards = ms.get("limitData") or ls.get("continuousBoards") or {}
    if not boards and lem:
        boards = {k: lem.get(k) for k in ("board1", "board2", "board3", "board4Plus")}
    yiban = boards.get("yiban") or boards.get("board1")
    promoted = sum(boards.get(k) or 0 for k in ("erban", "sanban", "sibanPlus", "board2", "board3", "board4Plus"))
    if yiban:
        m["promotionRate"] = round(promoted / yiban, 3)
    if lem.get("maxContinuousDays") is not None:
        m["maxBoard"] = int(lem["maxContinuousDays"])
    if lem.get("fengbanRate") is not None:
        m["fengbanRate"] = round(lem["fengbanRate"], 1)
    for k, v in (("zt", zt), ("dt", dt), ("zhabanRate", zb)):
        if v is not None:
            m[k] = round(v, 1) if isinstance(v, float) else v
        else:
            _degraded(deg, "market", f"{k} 缺失（三级源均无）")
    return m


def _narrative(market: dict, lifecycle: dict | None, stocks: list) -> str:
    """模板化中文行情叙事：只用存在的字段，缺失部分静默跳过（不伪造）。"""
    parts = []
    if market.get("zt") is not None:
        parts.append(f"涨停{market['zt']}家")
    if market.get("dt") is not None:
        parts.append(f"跌停{market['dt']}家")
    if market.get("zhabanRate") is not None:
        parts.append(f"炸板率{market['zhabanRate']}%")
    if market.get("promotionRate") is not None:
        parts.append(f"晋级率{int(market['promotionRate'] * 100)}%")
    if market.get("maxBoard"):
        parts.append(f"最高{market['maxBoard']}板")
    if market.get("sh") is not None:
        parts.append(f"上证{market['sh']:+.2f}%")
    if parts:
        parts = ["今日" + "，".join(parts) + "。"]
    if lifecycle and lifecycle.get("counts"):
        c = lifecycle["counts"]
        parts.append(f"生命周期点火{c.get('ignition')}扩散{c.get('expansion')}拥挤{c.get('crowded')}"
                     f"反转{c.get('reversal')}冷却{c.get('cooling')}。")
    if lifecycle and lifecycle.get("migration"):
        mig = [f"{k}{'+' if v > 0 else ''}{v}" for k, v in lifecycle["migration"].items() if v]
        if mig:
            parts.append("较上一槽：" + "、".join(mig) + "。")
    top = [s for s in stocks if s.get("pct") is not None][:3]
    if top:
        moves = "、".join(f"{s['n']}{s['pct']:+.1f}%" for s in top if s.get("n"))
        if moves:
            parts.append(f"热度前{'三' if len(top) >= 3 else len(top)}：{moves}。")
    return "".join(parts)


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


def _platform_count(r: dict) -> int:
    """platforms 兼容两种存量形态：int（上榜平台数）或 list（平台名集合）。"""
    p = r.get("platforms")
    if isinstance(p, int):
        return p
    if isinstance(p, (list, tuple, set)):
        return len(p)
    return 0


def build_replay_state(frame: dict, rows: list, analysis_by_code: dict,
                       sentiment_doc: dict | None, prev_counts: dict | None,
                       prev_codes: set) -> dict:
    """锚定帧 + 行 + 行级 stage 映射 + 情绪桶 → jev state（§5 四层结构）。"""
    deg: list = []
    codes = {r.get("code") for r in rows if r.get("code")}
    market = _market(frame, sentiment_doc, deg)
    lifecycle = _lifecycle(sentiment_doc, prev_counts, deg)
    stocks = _stocks(rows, analysis_by_code, deg)
    return {
        "asOf": f"{frame.get('tradingDate')} {frame.get('slotTime')}",
        "slot": (frame.get("slotTime") or "").replace(":", "") + "+0",
        "narrative": _narrative(market, lifecycle, stocks),
        "market": market,
        "lifecycle": lifecycle,
        "stocks": stocks,
        "hotlist": {"platforms": max((_platform_count(r) for r in rows), default=0),
                    "entries": len(rows),
                    "newEntries": len(codes - set(prev_codes or set()))},
        "quality": {"degraded": deg},
    }


MACD_CROSS_CN = {"death": "死叉", "golden": "金叉"}


def build_stock_config_narrative(analysis: dict, row: dict) -> str:
    """单股五维配置 → 叙事文本（jev Choice 打标输入）。缺维跳过对应行，不伪造。"""
    parts: list = []
    name = row.get("name") or row.get("code") or "未知"
    head = f"{name}"
    if row.get("rank") is not None:
        head += f"（热榜第{row['rank']}名）"
    parts.append(head + "：")
    res = analysis.get("resonance") or {}
    if res.get("score") is not None:
        extra = []
        if res.get("relativeMomentum") is not None:
            extra.append(f"相对动量{res['relativeMomentum']:.2f}")
        if res.get("acceleration") is not None:
            extra.append(f"加速度{res['acceleration']:.2f}")
        parts.append(f"共振{res.get('label') or ''}{res['score']}分方向{res.get('direction')}"
                     + (f"（{'，'.join(extra)}）" if extra else "") + "；")
    tech = analysis.get("technical") or {}
    ma = (tech.get("movingAverage") or {}).get("trend")
    macd = tech.get("macd") or {}
    if ma or macd.get("cross"):
        seg = "技术 "
        if ma:
            seg += f"MA趋势{ma}"
        if macd.get("cross"):
            seg += f"、MACD{MACD_CROSS_CN.get(macd['cross'], macd['cross'])}"
            seg += "已确认" if macd.get("confirmed") else "未确认"
        parts.append(seg + "；")
    cyc = analysis.get("cycle") or {}
    if cyc.get("stage"):
        cm = cyc.get("metrics") or {}
        seg = f"周期 {cyc['stage']}（前一{cyc.get('previousStage') or '无'}，置信{cyc.get('confidence')}）"
        if cm.get("rankVelocity") is not None:
            seg += f"，rankVelocity{cm['rankVelocity']:.1f}"
        parts.append(seg + "；")
    tm = analysis.get("themeMomentum") or {}
    if tm.get("themeName"):
        parts.append(f"题材 {tm['themeName']}动量{tm.get('score')}分{tm.get('phaseLabel') or ''}；")
    dec = ((analysis.get("decision") or {}).get("final")) or {}
    if dec.get("signal"):
        parts.append(f"决策信号 {dec['signal']}（置信{dec.get('confidence')}）")
    rt = ((analysis.get("observation") or {}).get("rankTrend")) or {}
    if rt.get("signalTier"):
        parts.append(f"，信号层{rt['signalTier']}（{'，'.join(rt.get('tierReasons') or [])}）")
    return "".join(parts)[:800]
