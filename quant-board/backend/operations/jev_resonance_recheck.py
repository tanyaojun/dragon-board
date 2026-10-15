# -*- coding: utf-8 -*-
"""共振维独立判读 runner（2026-10-14 试点；题集合同=docs/hotlist-jev/jev-resonance-recheck-preregistration.md）。

- 取数（全部只读，零写入快照集合）：snapshot_frames + snapshot_stock_rows（当日 ≤判读槽的全部
  half_hour 帧）+ snapshot_analysis（同帧**引擎共振读数**，仅作对照锚快照落档，不进叙事）；
- **同源（零第二实现）**：分位序列/市场基准/跳变标记全部委托引擎同一实现——
  attention_rank_lookup + percentile_rank（engine/primitives.py）、
  frame_market_median / frame_market_median_percentile（engine/runtime.py）、
  detect_rank_jumps（engine/runtime.py）。本 runner 只做「取数→拼叙事→调用→落档」；
- 判读帧默认 15:00：引擎共振需 ≥9 棒（resonanceMidWindowBars+1），午盘帧（11:00 仅 5 槽）
  天然 insufficient——这是已登记的 fail-visible 事实（原料结构决定），不是缺陷；
- 人口=判读帧全池，**无抽样帽**（2026-10-14 用户裁决「帽子盖的是自己的眼睛」）；
- 预检 riskFlag：data_insufficient 不调用落留痕文档；partial/ok 进判读；
- 落库 hotlist_jev_resonance_recheck_pilot，_id={date}:{slot}:{code}:RES；answers 原样包 +
  confidence 升顶层 + responseRaw ok/degraded 一律存完整 envelope + 引擎对照锚快照；
- 默认 dry-run（零 jev 调用）；--fire 且 token 才真实调用（AGENTS §1.2-7）；done-skip 幂等。
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, _questions_hash, _usage_tokens
from backend.analysis.hotlist.jev_resonance_ammo import (
    QUESTIONS_RESONANCE_RECHECK,
    QUESTION_SET_VERSION_RESONANCE_RECHECK,
    RESONANCE_AMMO_VERSION,
    RESONANCE_MIN_BARS,
    RESONANCE_MIN_MARKET_SAMPLE,
    build_resonance_narrative,
    resonance_risk_flag,
    short_window_excess,
    strength_band,
)
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank
from backend.analysis.ranktrend.engine.runtime import (
    detect_rank_jumps,
    frame_market_median,
    frame_market_median_percentile,
)
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

PILOT_SLOT = "15:00"
TOKEN_FUSE = 150_000  # 与双题集同款：单次运行逐 call 累计熔断线（缺省值）

# 与引擎同源的帧窗口（ranktrend_routes.ANALYZE_FULL_MARKET_LOAD_LIMIT / _build_code_attention_series.max_bars）
# rolling_frames / appearance_series 为**跨题集共享取数原语**（趋势 pilot 直接 import，零第二实现）：
# 共振/趋势/热度三维的引擎输入都是同一条「跨日最近 ≤50 次进榜出现」序列，取数只有一份。
FRAME_LOAD_LIMIT = 280
SERIES_MAX_BARS = 50


# ── 取数（只读；等值查询 + Python 过滤，不用操作符查询）──

def rolling_frames(db, date: str, dataset_id: str, slot: str,
                    limit: int = FRAME_LOAD_LIMIT) -> list[tuple[str, str, str, dict[str, dict]]]:
    """判读帧（含）之前的最近 limit 个 half_hour 帧，跨日、按 (tradingDate, slotTime) 升序。

    与引擎 _load_frames_for_analysis 同口径：倒序取最近 limit 帧再反转为升序；
    判读帧 = tradingDate==date 且 slotTime==slot 的帧。返回 [(tradingDate, slotTime, snapshotId, {code: row})]。
    """
    frames = list(db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour"},
        {"snapshotId": 1, "slotTime": 1, "tradingDate": 1}))
    picked: list[tuple[str, str, str]] = []
    for f in sorted(frames, key=lambda x: (str(x.get("tradingDate") or ""),
                                           str(x.get("slotTime") or "")), reverse=True):
        d, s = str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")
        if not d or not s or (d, s) > (date, slot):
            continue
        picked.append((d, s, str(f.get("snapshotId") or "")))
        if len(picked) >= limit:
            break
    picked.reverse()
    out: list[tuple[str, str, str, dict[str, dict]]] = []
    for d, s, sid in picked:
        rows = {str(r.get("code")): r for r in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "snapshotId": sid}) if r.get("code")}
        out.append((d, s, sid, rows))
    return out


def appearance_series(frames: list[tuple[str, str, str, dict[str, dict]]]
                       ) -> dict[str, list[tuple[str, int, int, float]]]:
    """每股注意力出现序列（引擎 _build_code_attention_series 同实现）：
    逐帧 attention_rank_lookup 重排 → percentile_rank，每股保留最近 SERIES_MAX_BARS 次出现。
    元素=(frameKey, attention_rank, attention_total, percentile)。"""
    series: dict[str, list[tuple[str, int, int, float]]] = {}
    for d, s, _sid, rows in frames:
        key = f"{d} {s}"
        ranks, total = attention_rank_lookup(list(rows.values()))
        for code, rank in ranks.items():
            series.setdefault(code, []).append((key, rank, total, percentile_rank(rank, total)))
    for code in series:
        series[code] = series[code][-SERIES_MAX_BARS:]
    return series


def _engine_resonance(db, dataset_id: str, snapshot_id: str, code: str) -> dict[str, Any] | None:
    """同帧引擎共振读数（对照锚快照；缺失/异常如实 None，不伪造）。"""
    doc = db["snapshot_analysis"].find_one(
        {"datasetId": dataset_id, "snapshotId": snapshot_id, "code": code})
    r = ((doc or {}).get("analysis") or {}).get("resonance") or {}
    if not r:
        return None
    return {"status": r.get("status"), "direction": r.get("direction"),
            "score": r.get("score"), "label": r.get("label"),
            "signalTier": r.get("signalTier"), "historyState": r.get("historyState"),
            "marketSampleCount": r.get("marketSampleCount")}


# ── 人口构建（纯取数+预检；无调用）──

def build_population(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                     slot: str = PILOT_SLOT) -> dict:
    """判读帧全池人口的共振语料（出现序列/市场基准/跳变标记全部引擎同源算法现算）。

    返回 {candidates, insufficient, meta}；candidates 每项含 code/name/series/market/entry/
    jumpEvents/quality/riskFlag/engine（对照锚快照）。序列=该股最近 ≤50 次进榜出现的前缀
    （末项=判读帧），与引擎 prefix=bars[:pos+1] 逐位同源。
    """
    frames = rolling_frames(db, date, dataset_id, slot)
    judgment = None
    for i, (d, s, _sid, _rows) in enumerate(frames):
        if d == date and s == slot:
            judgment = i  # 取最后一个匹配（理论唯一）
    if judgment is None:
        return {"candidates": [], "insufficient": [],
                "meta": {"error": "no_frame", "tradingDate": date, "slot": slot}}
    engine_frames = [{"stocks": list(rows.values())} for _d, _s, _sid, rows in frames]
    median_short, sample_count = frame_market_median(engine_frames, judgment)
    median_pct = frame_market_median_percentile(engine_frames[judgment])
    pool_size = len(engine_frames[judgment].get("stocks") or [])
    series_by_code = appearance_series(frames)
    judgment_key = f"{date} {slot}"
    _jd, _js, judgment_sid, judgment_rows = frames[judgment]
    candidates: list[dict] = []
    insufficient: list[dict] = []
    for code in sorted(judgment_rows.keys()):
        row = judgment_rows[code]
        bars_all = series_by_code.get(code) or []
        pos = next((i for i, item in enumerate(bars_all) if item[0] == judgment_key), None)
        if pos is None:
            # 判读帧在榜但无 attention 序列（avgRankNum 缺失）——引擎同口径跳过；
            # fail-visible：本题集显式留痕，不静默消失（§4.0）。
            insufficient.append({
                "code": code, "name": row.get("name"), "series": [], "market": None,
                "entry": {"isNew": True, "currentPercentile": None},
                "jumpEvents": [], "bars": 0,
                "quality": {"missingAppearances": [], "missingFields": ["avgRankNum"]},
                "riskFlag": {"level": "data_insufficient",
                             "reasons": ["无 attention 序列（avgRankNum 缺失，引擎同口径跳过）"]},
                "engine": _engine_resonance(db, dataset_id, judgment_sid, code)})
            continue
        prefix = bars_all[: pos + 1]
        series: list[dict] = []
        prev_pct: float | None = None
        for key, rank, total, pct in prefix:
            d, s = key.split(" ", 1)
            series.append({"tradingDate": d, "slot": s, "rank": rank, "total": total,
                           "percentile": pct,
                           "delta": (pct - prev_pct) if prev_pct is not None else None})
            prev_pct = pct
        bars = len(prefix)
        market = ({"medianShortChange": median_short, "sampleCount": sample_count,
                   "medianPercentile": median_pct, "poolSize": pool_size}
                  if median_short is not None else None)
        entry = {"isNew": bars == 1, "currentPercentile": prefix[-1][3] if prefix else None}
        jump_events = (detect_rank_jumps([p for _k, _r, _t, p in prefix]).get("events") or []) \
            if bars >= 3 else []
        quality = {"missingAppearances": [],
                   "missingFields": ["avgRankNum"] if row.get("avgRankNum") in (None, 0) else []}
        rf = resonance_risk_flag(bars, sample_count, timeline_valid=True)
        if market is None:
            # 市场基准不可算（窗口不足 4 帧或公共样本 <20）：与引擎 insufficient 同口径，
            # 不论序列多长都不可判（相对强弱没有标尺）——fail-visible 写明真实样本数。
            rf = {"level": "data_insufficient",
                  "reasons": rf["reasons"] + [f"市场基准不可算（公共样本={sample_count}，需4帧窗口）"]}
        cand = {"code": code, "name": row.get("name"), "series": series, "market": market,
                "entry": entry, "jumpEvents": jump_events, "quality": quality,
                "riskFlag": rf, "bars": bars,
                "engine": _engine_resonance(db, dataset_id, judgment_sid, code)}
        (insufficient if rf["level"] == "data_insufficient" else candidates).append(cand)
    meta = {"tradingDate": date, "slot": slot, "snapshotId": judgment_sid,
            "frameWindow": len(frames), "poolSize": pool_size,
            "marketSampleCount": sample_count,
            "population_n": len(candidates) + len(insufficient),
            "minBars": RESONANCE_MIN_BARS, "minMarketSample": RESONANCE_MIN_MARKET_SAMPLE}
    return {"candidates": candidates, "insufficient": insufficient, "meta": meta}


# ── 留痕文档（data_insufficient：不调用，落 riskFlag 留痕）──

def _insufficient_doc(date: str, slot: str, code: str, name: Any, rf: dict,
                      qhash: str) -> dict:
    return {"_id": f"{date}:{slot}:{code}:RES", "origin": "resonance_recheck_pilot",
            "tradingDate": date, "slotTime": slot, "code": code, "name": name,
            "ammoVersion": RESONANCE_AMMO_VERSION,
            "questionSetVersion": QUESTION_SET_VERSION_RESONANCE_RECHECK,
            "questionSetHash": qhash, "riskFlag": rf, "status": "data_insufficient",
            "shortExcess": None,
            "answers": None, "responseRaw": None, "usage": None, "latencyMs": None,
            "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ── 单日运行 ──

def run_resonance_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                      fire: bool = False, workers: int = 1, token_fuse: int | None = None,
                      slot: str = PILOT_SLOT, only_codes: list[str] | None = None) -> dict:
    """共振维独立判读（题集 v1）：全池无帽；dry-run 零调用；--fire 才真实调用。"""
    col = db["hotlist_jev_resonance_recheck_pilot"]
    questions = QUESTIONS_RESONANCE_RECHECK
    qhash_hex = _questions_hash(questions)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        pop = build_population(db, date, dataset_id, slot)
        if pop["meta"].get("error"):
            stats["no_frame"] += 1
            print(f"[resonance] {date} {slot} {pop['meta']['error']}，跳过")
            continue
        print(f"[resonance] {date} 判读槽={pop['meta']['slot']} 池={pop['meta']['poolSize']} "
              f"候选={len(pop['candidates'])} 预检不足={len(pop['insufficient'])} "
              f"市场基准样本={pop['meta']['marketSampleCount']}")
        if fire:
            for c in pop["insufficient"]:
                col.replace_one({"_id": f"{date}:{slot}:{c['code']}:RES"},
                                _insufficient_doc(date, slot, c["code"], c["name"],
                                                  c["riskFlag"], qhash_hex), upsert=True)
                stats["data_insufficient"] += 1

        def _work(c: dict) -> tuple[str, dict, int]:
            narrative = build_resonance_narrative(
                trading_date=date, slot=slot, code=c["code"], name=c["name"],
                series=c["series"], market=c["market"], entry=c["entry"],
                jump_events=c["jumpEvents"], quality=c["quality"])
            env, ms = _dispatch_jev(narrative, questions)
            parsed = parse_jev_response(env, ms, expected_keys=set(questions))
            used = _usage_tokens(parsed.get("usage"))
            ans = parsed.get("answers") or {}
            direction = (ans.get("resonance_direction") or {})
            strength = (ans.get("resonance_strength") or {})
            engine = c.get("engine") or {}
            doc = {"_id": f"{date}:{slot}:{c['code']}:RES", "origin": "resonance_recheck_pilot",
                   "tradingDate": date, "slotTime": slot, "code": c["code"], "name": c["name"],
                   "ammoVersion": RESONANCE_AMMO_VERSION,
                   "questionSetVersion": QUESTION_SET_VERSION_RESONANCE_RECHECK,
                   "questionSetHash": qhash_hex, "riskFlag": c["riskFlag"],
                   "bars": c["bars"],
                   "status": "ok" if parsed["ok"] else "degraded",
                   "narrative": narrative, "questionsRaw": questions,
                   "answers": parsed.get("answers"),
                   "resonanceDirection": direction.get("choice"),
                   "resonanceConfidence": direction.get("confidence"),
                   "resonanceProbabilities": direction.get("probabilities"),
                   "resonanceScore": strength.get("score"),
                   "resonanceScoreConfidence": strength.get("confidence"),
                   # 判据第一步输入（同款纯函数现算，非判定产物）：事后可机械核对
                   # 「模型方向 vs 超额符号」，归因零成本（v1 首日即靠手工重算才发现 93 例）
                   "shortExcess": short_window_excess(c["series"], c["market"]),
                   # 引擎对照锚快照（同帧同股；台账机械可算，不回写引擎）
                   "engineDirection": engine.get("direction"),
                   "engineScore": engine.get("score"),
                   "engineTier": engine.get("signalTier"),
                   "engineLabel": engine.get("label"),
                   "engineStatus": engine.get("status"),
                   "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "responseRaw": env,  # ok/degraded 一律存完整 envelope
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            return c["code"], doc, used

        allowed = set(only_codes) if only_codes else None
        todo = []
        for c in pop["candidates"]:
            if allowed is not None and c["code"] not in allowed:
                continue
            _id = f"{date}:{slot}:{c['code']}:RES"
            # done-skip **按题集代际**：同代际已 ok 才跳过；代际升级（改门）必须重跑，
            # 同 _id 整档覆盖旧读数（单一事实源，不留双轨；v1 首日读数由 v2 取代，
            # v1 台账数字已存档于预登记 §七·跑）。
            if col.find_one({"_id": _id, "status": "ok",
                             "questionSetVersion": QUESTION_SET_VERSION_RESONANCE_RECHECK}):
                stats["skip"] += 1
                continue
            todo.append(c)
        if not fire:
            for c in todo[:20]:
                print(f"[resonance] dry-run {date}:{slot}:{c['code']}:RES "
                      f"bars={c['bars']} riskFlag={c['riskFlag']['level']}")
            print(f"[resonance] dry-run 待判 {len(todo)} 例（全池口径，无帽）")
            continue
        if todo and tokens >= fuse:
            print(f"[resonance] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
            continue
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_work, todo))
            for code, doc, used in results:
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[resonance] {date} {code} → {doc['resonanceDirection']} "
                      f"score={doc['resonanceScore']} conf={doc['resonanceConfidence']} "
                      f"(引擎 {doc['engineDirection']}/{doc['engineTier']}) tokens={used}(cum={tokens})")
        else:
            for c in todo:
                if tokens >= fuse:
                    print(f"[resonance] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    break
                code, doc, used = _work(c)
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[resonance] {date} {code} → {doc['resonanceDirection']} "
                      f"score={doc['resonanceScore']} conf={doc['resonanceConfidence']} "
                      f"(引擎 {doc['engineDirection']}/{doc['engineTier']}) tokens={used}(cum={tokens})")
    stats["tokens"] = tokens
    print("FINAL[resonance]:", stats)
    return stats


# ── 对照台账（纯读+小写，零 jev 调用；与 jev_vote_winrate_ledger 同形态）──

def build_ledger(db: Any, dataset_id: str = DEFAULT_DATASET_ID,
                 start: str | None = None) -> dict[str, Any]:
    """jev 共振判读 vs 引擎共振读数的一致性台账（同帧同股机械对照）。

    agree/diverge 按 direction 直比；强度按 STRENGTH_BANDS 分桶比对（jev score vs 引擎 score）；
    两侧 insufficient/缺失不计票（fail-visible：缺对照锚的单列）。
    """
    import collections

    out: dict[str, Any] = {"dir": collections.Counter(), "band": collections.Counter(),
                           "missingAnchor": 0, "jevInsufficient": 0, "engineInsufficient": 0,
                           "days": []}
    per_day: dict[str, dict[str, Any]] = {}
    for doc in db["hotlist_jev_resonance_recheck_pilot"].find(
            {"status": "ok", "slotTime": PILOT_SLOT}):
        date = str(doc.get("tradingDate") or "")
        if not date or (start and date < start):
            continue
        jd = doc.get("resonanceDirection")
        ed = doc.get("engineDirection")
        if jd == "insufficient":
            out["jevInsufficient"] += 1
        if not ed:
            out["missingAnchor"] += 1
            continue
        if ed == "hold" and doc.get("engineStatus") == "insufficient":
            out["engineInsufficient"] += 1
            continue
        if jd in ("buy", "sell", "hold"):
            out["dir"]["agree" if jd == ed else "diverge"] += 1
            day = per_day.setdefault(date, {"date": date, "agree": 0, "diverge": 0})
            day["agree" if jd == ed else "diverge"] += 1
        js, es = doc.get("resonanceScore"), doc.get("engineScore")
        jb, eb = strength_band(js), strength_band(es)
        if jb and eb:
            out["band"]["agree" if jb == eb else "diverge"] += 1
    out["days"] = [per_day[k] for k in sorted(per_day)]
    total = out["dir"]["agree"] + out["dir"]["diverge"]
    out["summary"] = {
        "dirAgree": out["dir"]["agree"], "dirDiverge": out["dir"]["diverge"],
        "dirAgreeRate": round(out["dir"]["agree"] / total * 100, 1) if total else None,
        "bandAgree": out["band"]["agree"], "bandDiverge": out["band"]["diverge"],
        "missingAnchor": out["missingAnchor"], "jevInsufficient": out["jevInsufficient"],
        "engineInsufficient": out["engineInsufficient"],
    }
    return out


def __main__():
    ap = argparse.ArgumentParser(description="共振维独立判读（题集 v1 试点）")
    ap.add_argument("--resonance-day", dest="resonance_day", action="append", default=[],
                    help="指定交易日跑共振独立判读（可多次传参）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    ap.add_argument("--fire", action="store_true",
                    help="真实调用 jev（只走预登记+用户批准开火路径；默认 dry-run 零调用）")
    ap.add_argument("--codes", dest="codes", default="",
                    help="逗号分隔 code 子集（单股判读；缺省=全池）")
    ap.add_argument("--workers", dest="workers", type=int, default=1,
                    help="并发数（默认 1 串行；回填建议 4）")
    ap.add_argument("--token-fuse", dest="token_fuse", type=int, default=None,
                    help="本次运行熔断线（缺省=150k；全量回填显式放宽）")
    ap.add_argument("--slot", dest="slot", default=PILOT_SLOT,
                    help="判读帧（默认 15:00：引擎共振需 ≥9 槽，午盘帧天然 insufficient）")
    ap.add_argument("--ledger", action="store_true",
                    help="只跑对照台账（纯读零调用零 jev）")
    args = ap.parse_args()
    if not args.resonance_day and not args.ledger:
        raise SystemExit("需要 --resonance-day 或 --ledger（可多次传参）")
    if args.fire and not ((os.environ.get("JEV_CF_TOKEN") or "").strip()
                          or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip()):
        raise SystemExit("--fire 需要环境变量 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    if args.ledger:
        import json
        print(json.dumps(build_ledger(db, args.dataset_id)["summary"], ensure_ascii=False))
        return
    only = [c.strip() for c in args.codes.split(",") if c.strip()] or None
    run_resonance_day(db, args.resonance_day, args.dataset_id, fire=args.fire,
                      workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                      only_codes=only)


if __name__ == "__main__":
    __main__()
