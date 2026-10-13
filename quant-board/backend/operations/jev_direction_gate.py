# -*- coding: utf-8 -*-
"""方向线 v4 原料 runner（2026-10-13 原料审计落地批）——**本批只组装不开火**。

预登记状态：判据未修订（沿用 v3-gate 文本暂位，v4 判据预登记随后，改门须用户点头）；
本文件产出=八块原料叙事（.tmp 落档）+ 人口/黑名单/时点验收，**不调用 jev、不挂链、不落业务库**。
原料合同：docs/hotlist-jev/jev-direction-material-audit.md；事实单一源：
backend/analysis/hotlist/market_facts.py（与 relay/cycle/phase 同算法）。
黑名单（零出现，测试机验）：引擎 tiers/finalSignal/synergy/compScore/compRank/
leadStatus/themeRole/avgRankNum；jev 各线答案（情绪槽位/EOD、relay answers、
driver 打标结论、cycle/phase 答案）。
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from backend.analysis.hotlist.market_facts import (
    FACTS_VERSION,
    fold_attention_series,
    frame_market_facts,
    swing_anchor,
)

DEFAULT_DATASET_ID = "dragonboard_live"
DIRECTION_SLOT = "11:00"
HOT_ZONE = 80
SERIES_MAIN_MIN_DAYS = 5  # 序列证据作为主证据的最小历史深度（用户裁决 2026-10-13）
SERIES_WINDOW_DAYS = 10
QUESTION_SET_VERSION = "v4-material"

# 黑名单字段（叙事零出现机验基线）
BLACKLIST_FIELDS = (
    "compScore", "compRank", "leadStatus", "themeRole", "avgRankNum",
    "finalSignal", "synergy", "voteDirection", "relayPhase", "cycleStage",
    "driverType", "catalystDepth", "phaseBand", "crowding", "temperature",
)


# ── 帧基础设施（与 v3 同源） ──────────────────────────────

def _slot_frame(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": slot},
        sort=[("timestamp", -1)])


def _frame_rows(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, dict]:
    f = _slot_frame(db, date, slot, dataset_id)
    if not f:
        return {}
    return {str(r["code"]): r for r in db["snapshot_stock_rows"].find(
        {"datasetId": dataset_id, "snapshotId": str(f["snapshotId"])})}


def _day_slot_frames(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[tuple[str, str]]:
    return [(str(f["slotTime"]), str(f["snapshotId"])) for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": d}).sort([("slotTime", 1)])]


def _trading_dates_with_slot(db: Any, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    return sorted({f["tradingDate"] for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": slot},
        {"tradingDate": 1}) if f.get("tradingDate")})


def _pct_rank(rank: Any, total: int) -> float | None:
    if not isinstance(rank, (int, float)) or not total:
        return None
    return round((total - rank + 1) / total * 100, 2)


def _r2(v: Any) -> Any:
    return round(v, 2) if isinstance(v, (int, float)) else v


def _f(v: Any, suffix: str = "") -> str:
    if not isinstance(v, (int, float)):
        return "missing"
    return f"{round(v, 2)}{suffix}"


# ── 判读日上下文 ──────────────────────────────────────────

def setup_day(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    dates = _trading_dates_with_slot(db, DIRECTION_SLOT)
    if d not in dates:
        raise LookupError(f"{d} 无 {DIRECTION_SLOT} 帧（未采集或非交易日）")
    idx = dates.index(d)
    prev10 = dates[max(0, idx - 10):idx]
    cur = _frame_rows(db, d, DIRECTION_SLOT, dataset_id)
    d3 = prev10[-3] if len(prev10) >= 3 else None
    d3_close = _frame_rows(db, d3, "15:00", dataset_id) if d3 else {}
    diffs = []
    for code, r in cur.items():
        p_now = _pct_rank(r.get("rank"), len(cur))
        r3 = d3_close.get(code)
        if p_now is None or not r3:
            continue
        p3 = _pct_rank(r3.get("rank"), len(d3_close))
        if p3 is not None:
            diffs.append(p_now - p3)
    diffs.sort()
    n = len(diffs)
    # 情绪相位带 as-of（hotlist_sentiment 规则描述分，非 jev 答案——白名单）
    sent_doc = db["hotlist_sentiment"].find_one(
        {"datasetId": dataset_id, "snapshotType": "half_hour", "tradingDate": d,
         "slotTime": {"$lte": DIRECTION_SLOT}}, sort=[("slotTime", -1)])
    es = (sent_doc or {}).get("emotionScore") or {}
    sscore = es.get("score")
    band = ("peak" if sscore >= 75 else "strong" if sscore >= 60
            else "weak" if sscore >= 40 else "cold") if isinstance(sscore, (int, float)) else None
    return {
        "dates": dates, "prev10": prev10, "cur": cur, "pool": len(cur),
        "mm": round(diffs[n // 2], 2) if n else None,
        "up_share": round(len([x for x in diffs if x > 0]) / n * 100, 1) if n else None,
        "sent": {"score": sscore, "band": band, "stage": (sent_doc or {}).get("stage"),
                 "slotTime": (sent_doc or {}).get("slotTime")},
        "series_days": [x for x in _trading_dates_with_slot(db, "09:30") if x < d][-SERIES_WINDOW_DAYS:],
        "prev3": prev10[-3:],
        "market": frame_market_facts(db, d, DIRECTION_SLOT, dataset_id),
        "swing": swing_anchor(db, d, DIRECTION_SLOT, dataset_id=dataset_id),
    }


# ── 原料组装：八块 ────────────────────────────────────────

def build_attention_series(db: Any, code: str, ctx: dict,
                           dataset_id: str = DEFAULT_DATASET_ID) -> list[dict]:
    pts = []
    for dd in ctx["series_days"]:
        for slot, sid in _day_slot_frames(db, dd, dataset_id):
            r = db["snapshot_stock_rows"].find_one(
                {"datasetId": dataset_id, "snapshotId": sid, "code": code},
                {"rank": 1, "change": 1})
            if not r or r.get("rank") is None:
                continue
            n = db["snapshot_stock_rows"].count_documents(
                {"datasetId": dataset_id, "snapshotId": sid})
            p = _pct_rank(r["rank"], n)
            if p is not None:
                pts.append({"d": dd, "slot": slot, "rank": r["rank"], "pct": p,
                            "chg": _r2(r.get("change"))})
    return pts


def build_state_v4(db: Any, code: str, d: str, ctx: dict,
                   dataset_id: str = DEFAULT_DATASET_ID) -> tuple[str, dict, dict]:
    """八块原料：序列折叠 / 位置（连板轨迹+TDX 位置轴）/ 量价+板型 / 市场时点 /
    摆动锚 / 题材归类 / 质量自标 / 门。返回 (head, blocks, meta)。"""
    row = ctx["cur"].get(code)
    if not row:
        raise LookupError(f"{code} 不在判读帧")
    series = build_attention_series(db, code, ctx, dataset_id)
    cur_pct = _pct_rank(row.get("rank"), ctx["pool"])
    series.append({"d": d, "slot": DIRECTION_SLOT, "rank": row.get("rank"),
                   "pct": cur_pct, "chg": _r2(row.get("change"))})
    folded = fold_attention_series(series, ctx["series_days"], d, cur_pct)  # 范围与查询窗口同源，防边缘日静默丢弃
    seen_days = len(folded["days"])
    first_seen = seen_days <= 1

    # 位置块：TDX 日线位置轴+板序（driver ammo 纯函数，共享算法）
    pos_lines, seq_lines = [], []
    try:
        from backend.operations.jev_label_jiuyan import _daily_bars, _adj_prev_series
        from backend.analysis.hotlist import jev_driver_ammo as ammo
        bars = _daily_bars(code)
        adj = _adj_prev_series(d, code, bars) if bars else None
        pos_lines.append(ammo.position_line_from_bars(d, code, bars, adj or None))
        seq_lines.append(ammo.sequence_line_from_bars(d, code, row.get("name"), 10, bars, adj or None))
    except Exception as exc:  # TDX 不可用=位置轴缺失（fail-visible），不阻断其余块
        pos_lines.append(f"个股位置：TDX 不可用 {type(exc).__name__}（fail-visible）")
        seq_lines.append("板序：TDX 不可用（fail-visible）")

    # 量价+板型块（帧层白名单直采）
    chg, vr = row.get("change"), row.get("volumeRatio")
    vr_meta = row.get("volumeRatioMeta") or {}
    zlje, zljzb = row.get("zlje"), row.get("zljzb")
    zlje = None if zlje == 0 else zlje
    zljzb = None if zljzb == 0 else zljzb  # 0.0/0.0=缺失活案例（审计 R3 前置）
    lim = 19.8 if str(code)[-6:].startswith(("300", "301", "688", "689")) else \
        29.8 if str(code)[-6:].startswith(("8", "4", "9")) else 9.8
    up = isinstance(chg, (int, float)) and chg >= lim
    dn = isinstance(chg, (int, float)) and chg <= -lim

    mkt = ctx["market"] or {}
    sent = ctx["sent"] or {}
    sw = ctx["swing"] or {}
    head = f"{d} {DIRECTION_SLOT} (intraday) · {code} {row.get('name') or ''}".rstrip()
    blocks = {
        "series": ["[Attention Series · daily-folded from cross-day appearances; percentile 0-100 "
                   "= attention rank; LAST = current intraday reading; direction +/- = day-over-day",
                   f"history depth: {seen_days} trading days"
                   + (" · FIRST-SEEN / SHORT HISTORY: attention series is NOT usable as primary "
                      "evidence; rely on position / board sequence / board type; lower confidence"
                      if seen_days < SERIES_MAIN_MIN_DAYS else ""),
                   *[f"{x['d']}: percentile {_f(x['pct'])} change {_f(x['chg'])}%" for x in folded["folded"]],
                   f"day-over-day directions (oldest→newest): {folded['directions']}",
                   f"against-trend jump day indexes (|flip|>=8pt): {folded['jumpIdxs'] or 'none'}",
                   f"consecutive falling days (incl. today): {folded['consecutiveFalling']}"],
        "position": ["[Position · price axis (TDX daily) + board sequence]"] + pos_lines + seq_lines,
        "vp": ["[Volume-Price + Board Type]",
               f"change: {_f(chg)}% · volume ratio: {_f(vr)} (5-day base status: "
               f"{(vr_meta or {}).get('status') or 'missing'}) · main-force net flow: "
               f"{_f(None if zlje is None else zlje / 1e8)} (100M CNY) · net ratio: {_f(zljzb, '%')}"
               f" · turnover: {_f(row.get('turnoverRate'), '%')}",
               f"limit-up: {'yes' if up else 'no'} · limit-down: {'yes' if dn else 'no'}"
               f" · first seal: {row.get('firstZtTime') or 'missing'}"
               f" · last seal: {row.get('lastZtTime') or 'missing'}"
               f" · seal order (fengdan): {row.get('fengdan') if row.get('fengdan') is not None else 'missing'}"
               f" · board height: {row.get('boardHeight') if row.get('boardHeight') is not None else 'missing'}",
               ],
        "market": ["[Market · as-of 11:00 frame facts (same-source with relay line)]",
                   f"limit-up count: {_f(mkt.get('ztCount'))} · zhaban: {_f(mkt.get('zhabanCount'))}"
                   f" (rate {_f(mkt.get('zhabanRate'), '%')}) · big drawdown: {_f(mkt.get('drawdownCount'))}"
                   f" · max board: {_f(mkt.get('maxBoard'))}",
                   f"THS intraday pools failed/drawdown/rushing: "
                   f"{'/'.join(str((mkt.get('thsPools') or {}).get(k)) for k in ('failed', 'drawdown', 'rushing'))}"
                   f" (height-bucket ladder only exists in 15:00 frames)",
                   f"frame seal quality: 一字板 {_f((mkt.get('sealQuality') or {}).get('byzCount'))}"
                   f" · 硬板 {_f((mkt.get('sealQuality') or {}).get('hardCount'))}"
                   f" · 烂板 {_f((mkt.get('sealQuality') or {}).get('rottenCount'))}"
                   f" (share {_f((mkt.get('sealQuality') or {}).get('rottenShare'))}"
                   f", avg success {_f((mkt.get('sealQuality') or {}).get('avgSucRate'))})",
                   f"pool breadth up/down/flat: {_f(mkt.get('upCount'))}/{_f(mkt.get('downCount'))}/"
                   f"{_f(mkt.get('flatCount'))}",
                   f"swing anchor: peak {sw.get('peak')} ({sw.get('peakDate')}, {sw.get('peakAgo')}d ago)"
                   f" · trough {sw.get('trough')} ({sw.get('troughDate')}, {sw.get('troughAgo')}d ago)"
                   f" · today {sw.get('cur')} (vs prev {_f(sw.get('deltaPrev'), '')}, vs peak {_f(sw.get('distPeak'), '')})"
                   if sw.get("ok") else "swing anchor: insufficient window (fail-visible)"],
        "themes": ["[Themes · jiuyan sector labels (collection facts)]",
                   f"sector label: {row.get('sectorLabel') or 'missing'} · main theme: "
                   f"{row.get('mainTheme') or 'missing'} · themes: {row.get('themes') or 'missing'}"],
        "quality": ["[Data Quality · self-reported]",
                    f"qualityFlags: {row.get('qualityFlags') or 'none'} · missingFields: "
                    f"{row.get('missingFields') or 'none'}"],
        "gate": ["[Market Gate · environment for BUY decisions]",
                 f"hot-list sentiment phase band: {sent.get('band') or 'missing'} (score "
                 f"{_f(sent.get('score'))}; fixed lines: cold <40 / weak 40-60 / strong 60-75 / peak >=75)"
                 f" · pool median 3-trading-day percentile change: {_f(ctx['mm'])}"
                 f" · pool breadth (rising 3-day percentile): {_f(ctx['up_share'], '%')}"],
    }
    meta = {"folded": {k: v for k, v in folded.items() if k != "folded"},
            "seenDays": seen_days, "firstSeen": first_seen,
            "series_points": len(series), "folded_days": len(folded["folded"]),
            "market": mkt, "swing": sw if sw.get("ok") else {"ok": False},
            "sentiment": sent, "factsVersion": FACTS_VERSION}
    return head, blocks, meta


# ── 人口（v3 口径：≥4 槽+前三日连续+主力非空；streak 冗余门禁评审后待裁决） ──

def build_population(db: Any, d: str, ctx: dict, dataset_id: str = DEFAULT_DATASET_ID) -> tuple[list[str], dict]:
    """v4 口径（2026-10-13 用户裁决）：人口=全热榜池（判读帧全部在榜股）。

    v3 三条件排除（主力非空/当日>=4槽/前三日连续）取消：那是「序列为主证据」判据的
    影子，把新面孔（最强 ignition 候选）系统性挡在 buy 判读外。v4 证据结构以位置
    （TDX）+板序+板型为主，不依赖在榜历史；序列不足降级为 case 级质量自标
    （seenDays/FIRST-SEEN），不挡判读。
    """
    codes = sorted(ctx["cur"].keys())
    mf_missing = len([c for c, r in ctx["cur"].items()
                      if r.get("zlje") is None or r.get("zljzb") is None])
    return codes, {"full_pool": len(codes), "mainforce_missing_counted": mf_missing}


def run_material_day(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID,
                     cap: int | None = None) -> dict:
    """组装一个判读日的全部原料叙事（不开火）：返回统计+逐例 narrative 摘要。"""
    ctx = setup_day(db, d, dataset_id)
    codes, pop_stats = build_population(db, d, ctx, dataset_id)
    if cap:
        codes = codes[:cap]
    out = []
    for code in codes:
        head, blocks, meta = build_state_v4(db, code, d, ctx, dataset_id)
        narrative = "\n".join([head, *[ln for b in blocks.values() for ln in b]])
        out.append({"code": code, "name": ctx["cur"][code].get("name"),
                    "narrative": narrative, "meta": meta})
    return {"date": d, "pool": ctx["pool"], "population": len(codes),
            "populationStats": pop_stats, "cases": out,
            "market": ctx["market"], "swing": ctx["swing"], "sent": ctx["sent"]}


# ── 开火层（预登记批后才允许真实调用；--fire 无 token 拒绝） ──

def build_question_doc(code: str, narrative: str) -> dict:
    """单例完整请求文档（=发给 jev 的原始 json）：题集判据+原料叙事。

    原始 json 就是这个 dict 的 json.dumps —— 开火前送用户确认的对象。
    """
    from backend.analysis.hotlist.jev_direction_ammo import (
        AMMO_VERSION, QUESTION_SET_VERSION, QUESTIONS, questions_hash)
    return {"questionSetVersion": QUESTION_SET_VERSION,
            "ammoVersion": AMMO_VERSION,
            "questionsHash": questions_hash(QUESTIONS),
            "questions": QUESTIONS,
            "narrative": narrative}


def fire_day(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID,
             cap: int | None = None) -> dict:
    """开火：逐例调用 jev → 解析 → upsert hotlist_jev_direction。

    幂等 _id={date}:11:00:{code}:DIR；请求/响应原文都落库（前端审计可见性要求）；
    token 预检无 token 直接拒绝（不烧钱不静默跳过——开火是显式动作）。
    """
    import os
    from datetime import datetime, timezone
    from backend.analysis.hotlist.jev_direction_ammo import (
        QUESTION_SET_VERSION, QUESTIONS)
    from backend.services.jev.jev_sentiment_compute import _dispatch_jev
    if not (os.environ.get("JEV_TYPESAFE_KEY") or os.environ.get("JEV_CF_TOKEN")):
        raise RuntimeError("fire 拒绝：无 JEV token（开火须显式 token 预检通过，预登记批后执行）")
    mat = run_material_day(db, d, dataset_id, cap=cap)
    coll = db["hotlist_jev_direction"]
    ok = err = 0
    for case in mat["cases"]:
        doc = build_question_doc(case["code"], case["narrative"])
        try:
            resp_text, _ms = _dispatch_jev(case["narrative"], QUESTIONS)
            parsed = _parse_direction(resp_text)
            now = datetime.now(timezone.utc).isoformat()
            coll.update_one(
                {"_id": f"{d}:{DIRECTION_SLOT}:{case['code']}:DIR"},
                {"$set": {"date": d, "slot": DIRECTION_SLOT,
                          "code": case["code"], "name": case["name"],
                          "direction": parsed["direction"],
                          "confidence": parsed["confidence"],
                          "questionSetVersion": QUESTION_SET_VERSION,
                          "requestJson": doc, "responseRaw": resp_text,
                          "verify": {"status": "pending"}, "createdAt": now}},
                upsert=True)
            ok += 1
        except Exception as exc:  # 单股失败不炸批次（fail-visible 计数）
            err += 1
            print(f"[v4-fire] {case['code']} 失败: {type(exc).__name__}: {exc}")
    return {"date": d, "ok": ok, "err": err, "population": mat["population"]}


def _parse_direction(resp_text: str) -> dict:
    """jev 返回 → {direction, confidence}；解析失败抛异常（不伪造成 hold）。"""
    import json as _json
    import re
    m = re.search(r"\{[\s\S]*\}", resp_text)
    if not m:
        raise ValueError(f"响应无 json: {resp_text[:120]!r}")
    data = _json.loads(m.group(0))
    d = data.get("direction")
    c = data.get("confidence")
    if d not in ("buy", "sell", "hold", "insufficient"):
        raise ValueError(f"direction 非法: {d!r}")
    if not isinstance(c, (int, float)) or not (0 <= c <= 1):
        raise ValueError(f"confidence 非法: {c!r}")
    return {"direction": d, "confidence": round(float(c), 3)}


def _main() -> None:
    ap = argparse.ArgumentParser(description="jev direction v4 runner (dry=组装; fire=调用需预登记批)")
    ap.add_argument("--day", required=True)
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--out", default=None, help="dry: .tmp 落档路径")
    ap.add_argument("--sample-json", action="store_true",
                    help="dry: 额外导出 1 例完整请求原始 json（开火前送用户确认）")
    ap.add_argument("--fire", action="store_true",
                    help="开火：真实调用 jev 并落库（无 token 拒绝；须预登记批+用户开火令）")
    args = ap.parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    if args.fire:
        r = fire_day(db, args.day, cap=args.cap)
        print(f"[v4-fire] {args.day} ok={r['ok']} err={r['err']} / 人口 {r['population']}")
        return
    r = run_material_day(db, args.day, cap=args.cap)
    print(f"[v4-material] {args.day} 池 {r['pool']} 人口(全池) {r['population']} "
          f"主力缺失计数 {r['populationStats']['mainforce_missing_counted']}")
    print(f"[v4-material] 市场 as-of 11:00: 涨停 {r['market']['ztCount']} 涨/跌 "
          f"{r['market']['upCount']}/{r['market']['downCount']} 情绪带 {r['sent']['band']}")
    if r["cases"]:
        c0 = r["cases"][0]
        print(f"[v4-material] 样例 {c0['code']} 叙事 {len(c0['narrative'])} 字符 / "
              f"折叠 {c0['meta']['folded_days']} 日 / 序列点 {c0['meta']['series_points']}")
        bad = [w for w in BLACKLIST_FIELDS if w in c0["narrative"]]
        print(f"[v4-material] 黑名单字段机验: {'FAIL ' + str(bad) if bad else 'PASS（零出现）'}")
    if args.sample_json and r["cases"]:
        doc = build_question_doc(r["cases"][0]["code"], r["cases"][0]["narrative"])
        path = args.out.replace(".json", "") + "_request_sample.json" if args.out \
            else f".tmp/v4_request_sample_{args.day}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"[v4-material] 原始请求样例落档 {path}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, default=str)
        print(f"[v4-material] 落档 {args.out}")


if __name__ == "__main__":
    _main()
