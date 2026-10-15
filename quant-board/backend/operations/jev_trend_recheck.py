# -*- coding: utf-8 -*-
"""趋势维独立判读 runner（2026-10-14 试点第二维；题集合同=docs/hotlist-jev/jev-trend-recheck-preregistration.md）。

- 取数（全部只读，零写入快照集合）：**直接复用共振 pilot 的取数原语**
  （operations/jev_resonance_recheck.rolling_frames / appearance_series）——趋势与共振的引擎
  输入是同一条「跨日最近 ≤50 次进榜出现」分位序列，取数只有一份，零第二实现；
- **同源衍生**：MA/MACD/MA交叉/momentum 全部委托引擎 trend/technical.py 同一函数现算
  （可复现算术衍生，非判定产物；引擎自己的 signals/score/direction/tier 一律不喂）；
- 两种模式与引擎同口径：序列 ≥22 次出现=series 模式（主证据=序列+派生）；
  <22=fallback 模式（引擎同款降级，主证据=判读帧行字段 displayChange/stockChange/volumeRatio/zlje/zljzb）；
- 对照锚 = 同帧 snapshot_analysis.observation.rankTrend（direction 取 compose_decision 的
  **base.signal**=纯技术面五分量加权和信号，不含 cycle/risk 对 final 的改写——锚干净）；
- 人口=判读帧全池，**无抽样帽**（2026-10-14 用户裁决）；预检 data_insufficient 不调用落留痕；
- 落库 hotlist_jev_trend_recheck_pilot，_id={date}:{slot}:{code}:TRD；
- 默认 dry-run（零 jev 调用）；--fire 且 token 才真实调用（AGENTS §1.2-7）；done-skip 幂等。
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, _questions_hash, _usage_tokens
from backend.analysis.hotlist.jev_trend_ammo import (
    QUESTIONS_TREND_RECHECK,
    QUESTION_SET_VERSION_TREND_RECHECK,
    TREND_AMMO_VERSION,
    TREND_MIN_BARS,
    build_trend_narrative,
    derived_indicators,
    strength_band,
    trend_risk_flag,
)
from backend.operations.jev_resonance_recheck import appearance_series, rolling_frames
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

PILOT_SLOT = "15:00"
TOKEN_FUSE = 150_000  # 与双题集同款：单次运行逐 call 累计熔断线（缺省值）

# 引擎 fallback_signals 的输入键（判读帧行；与 runtime._analyze_frames 的 fallback dict 同键同源）
_FALLBACK_FIELDS = ("displayChange", "stockChange", "volumeRatio", "zlje", "zljzb")


# ── 引擎同帧读数（对照锚快照；只读不回写）──

def _engine_trend(db, dataset_id: str, snapshot_id: str, code: str) -> dict[str, Any] | None:
    """同帧引擎趋势读数（observation.rankTrend；缺失/异常如实 None，不伪造）。"""
    doc = db["snapshot_analysis"].find_one(
        {"datasetId": dataset_id, "snapshotId": snapshot_id, "code": code})
    r = (((doc or {}).get("analysis") or {}).get("observation") or {}).get("rankTrend") or {}
    if not r:
        return None
    return {"status": None, "direction": r.get("direction"), "score": r.get("score"),
            "signedScore": r.get("signedScore"), "signalTier": r.get("signalTier"),
            "tierReasons": r.get("tierReasons")}


# ── 人口构建（纯取数+预检；无调用）──

def build_population(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                     slot: str = PILOT_SLOT) -> dict:
    """判读帧全池人口的趋势语料（序列/派生读数/帧行字段全部引擎同源现算）。

    返回 {candidates, insufficient, meta}；candidates 每项含 code/name/series/derived/
    frameFields/entry/quality/riskFlag/engine（对照锚快照）。
    """
    frames = rolling_frames(db, date, dataset_id, slot)
    judgment = None
    for i, (d, s, _sid, _rows) in enumerate(frames):
        if d == date and s == slot:
            judgment = i  # 取最后一个匹配（理论唯一）
    if judgment is None:
        return {"candidates": [], "insufficient": [],
                "meta": {"error": "no_frame", "tradingDate": date, "slot": slot}}
    series_by_code = appearance_series(frames)
    judgment_key = f"{date} {slot}"
    _jd, _js, judgment_sid, judgment_rows = frames[judgment]
    candidates: list[dict] = []
    insufficient: list[dict] = []
    for code in sorted(judgment_rows.keys()):
        row = judgment_rows[code]
        bars_all = series_by_code.get(code) or []
        pos = next((i for i, item in enumerate(bars_all) if item[0] == judgment_key), None)
        prev_pct: float | None = None
        series: list[dict] = []
        if pos is not None:
            for key, rank, total, pct in bars_all[: pos + 1]:
                d, s = key.split(" ", 1)
                series.append({"tradingDate": d, "slot": s, "rank": rank, "total": total,
                               "percentile": pct,
                               "delta": (pct - prev_pct) if prev_pct is not None else None})
                prev_pct = pct
        pcts = [s["percentile"] for s in series if isinstance(s.get("percentile"), (int, float))]
        bars = len(pcts)
        # 帧行字段 = 引擎 fallback_signals 的同一输入（displayChange=末项−前项分位差，同 runtime）
        display_change = (pcts[-1] - pcts[-2]) if bars >= 2 else None
        frame_fields = {"displayChange": display_change,
                        "stockChange": row.get("change"),
                        "volumeRatio": row.get("volumeRatio"),
                        "zlje": row.get("zlje"), "zljzb": row.get("zljzb")}
        derived = derived_indicators(pcts) if bars >= 2 else {}
        entry = {"isNew": bars == 1,
                 "currentPercentile": pcts[-1] if pcts else None}
        quality = {"missingAppearances": [],
                   "missingFields": [f for f in _FALLBACK_FIELDS
                                     if frame_fields.get(f) is None]}
        rf = trend_risk_flag(bars)
        cand = {"code": code, "name": row.get("name"), "series": series, "derived": derived,
                "frameFields": frame_fields, "entry": entry, "quality": quality,
                "riskFlag": rf, "bars": bars, "mode": rf.get("mode"),
                "engine": _engine_trend(db, dataset_id, judgment_sid, code)}
        (insufficient if rf["level"] == "data_insufficient" else candidates).append(cand)
    modes: dict[str, int] = {}
    for c in candidates:
        modes[c["mode"] or "?"] = modes.get(c["mode"] or "?", 0) + 1
    meta = {"tradingDate": date, "slot": slot, "snapshotId": judgment_sid,
            "frameWindow": len(frames), "poolSize": len(judgment_rows),
            "population_n": len(candidates) + len(insufficient),
            "modes": modes, "minBars": TREND_MIN_BARS}
    return {"candidates": candidates, "insufficient": insufficient, "meta": meta}


def _insufficient_doc(date: str, slot: str, code: str, name: Any, rf: dict,
                      qhash: str) -> dict:
    return {"_id": f"{date}:{slot}:{code}:THD", "origin": "trend_recheck_pilot",
            "tradingDate": date, "slotTime": slot, "code": code, "name": name,
            "ammoVersion": TREND_AMMO_VERSION,
            "questionSetVersion": QUESTION_SET_VERSION_TREND_RECHECK,
            "questionSetHash": qhash, "riskFlag": rf, "status": "data_insufficient",
            "answers": None, "responseRaw": None, "usage": None, "latencyMs": None,
            "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ── 单日运行 ──

def run_trend_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                  fire: bool = False, workers: int = 1, token_fuse: int | None = None,
                  slot: str = PILOT_SLOT, only_codes: list[str] | None = None) -> dict:
    """趋势维独立判读（题集 v1）：全池无帽；dry-run 零调用；--fire 才真实调用。"""
    col = db["hotlist_jev_trend_recheck_pilot"]
    questions = QUESTIONS_TREND_RECHECK
    qhash_hex = _questions_hash(questions)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        pop = build_population(db, date, dataset_id, slot)
        if pop["meta"].get("error"):
            stats["no_frame"] += 1
            print(f"[trend] {date} {slot} {pop['meta']['error']}，跳过")
            continue
        print(f"[trend] {date} 判读槽={pop['meta']['slot']} 池={pop['meta']['poolSize']} "
              f"候选={len(pop['candidates'])} 预检不足={len(pop['insufficient'])} "
              f"模式={pop['meta']['modes']}")
        if fire:
            for c in pop["insufficient"]:
                col.replace_one({"_id": f"{date}:{slot}:{c['code']}:THD"},
                                _insufficient_doc(date, slot, c["code"], c["name"],
                                                  c["riskFlag"], qhash_hex), upsert=True)
                stats["data_insufficient"] += 1

        def _work(c: dict) -> tuple[str, dict, int]:
            narrative = build_trend_narrative(
                trading_date=date, slot=slot, code=c["code"], name=c["name"],
                series=c["series"], derived=c["derived"], frame_fields=c["frameFields"],
                entry=c["entry"], quality=c["quality"])
            env, ms = _dispatch_jev(narrative, questions)
            parsed = parse_jev_response(env, ms, expected_keys=set(questions))
            used = _usage_tokens(parsed.get("usage"))
            ans = parsed.get("answers") or {}
            direction = (ans.get("trend_direction") or {})
            strength = (ans.get("trend_strength") or {})
            engine = c.get("engine") or {}
            doc = {"_id": f"{date}:{slot}:{c['code']}:THD", "origin": "trend_recheck_pilot",
                   "tradingDate": date, "slotTime": slot, "code": c["code"], "name": c["name"],
                   "ammoVersion": TREND_AMMO_VERSION,
                   "questionSetVersion": QUESTION_SET_VERSION_TREND_RECHECK,
                   "questionSetHash": qhash_hex, "riskFlag": c["riskFlag"],
                   "bars": c["bars"], "mode": c["mode"],
                   "status": "ok" if parsed["ok"] else "degraded",
                   "narrative": narrative, "questionsRaw": questions,
                   "answers": parsed.get("answers"),
                   "trendDirection": direction.get("choice"),
                   "trendConfidence": direction.get("confidence"),
                   "trendProbabilities": direction.get("probabilities"),
                   "trendScore": strength.get("score"),
                   "trendScoreConfidence": strength.get("confidence"),
                   # 引擎对照锚快照（同帧同股；台账机械可算，不回写引擎）
                   "engineDirection": engine.get("direction"),
                   "engineScore": engine.get("score"),
                   "engineSignedScore": engine.get("signedScore"),
                   "engineTier": engine.get("signalTier"),
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
            _id = f"{date}:{slot}:{c['code']}:THD"
            # done-skip 按题集代际：同代际已 ok 才跳过；代际升级（改门）必须重跑，
            # 同 _id 整档覆盖旧读数（单一事实源，不留双轨）。
            if col.find_one({"_id": _id, "status": "ok",
                             "questionSetVersion": QUESTION_SET_VERSION_TREND_RECHECK}):
                stats["skip"] += 1
                continue
            todo.append(c)
        if not fire:
            for c in todo[:20]:
                print(f"[trend] dry-run {date}:{slot}:{c['code']}:THD "
                      f"bars={c['bars']} mode={c['mode']} riskFlag={c['riskFlag']['level']}")
            print(f"[trend] dry-run 待判 {len(todo)} 例（全池口径，无帽）")
            continue
        if todo and tokens >= fuse:
            print(f"[trend] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
            continue
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_work, todo))
            for code, doc, used in results:
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[trend] {date} {code} → {doc['trendDirection']} "
                      f"score={doc['trendScore']} conf={doc['trendConfidence']} "
                      f"(引擎 {doc['engineDirection']}/{doc['engineTier']}) tokens={used}(cum={tokens})")
        else:
            for c in todo:
                if tokens >= fuse:
                    print(f"[trend] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    break
                code, doc, used = _work(c)
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[trend] {date} {code} → {doc['trendDirection']} "
                      f"score={doc['trendScore']} conf={doc['trendConfidence']} "
                      f"(引擎 {doc['engineDirection']}/{doc['engineTier']}) tokens={used}(cum={tokens})")
    stats["tokens"] = tokens
    print("FINAL[trend]:", stats)
    return stats


# ── 对照台账（纯读+小写，零 jev 调用；与共振 pilot 同形态）──

def build_ledger(db: Any, dataset_id: str = DEFAULT_DATASET_ID,
                 start: str | None = None) -> dict[str, Any]:
    """jev 趋势判读 vs 引擎趋势读数的一致性台账（同帧同股机械对照）。

    agree/diverge 按 direction 直比；强度按 STRENGTH_BANDS 分桶比对；
    两侧 insufficient/缺失不计票（fail-visible：缺对照锚的单列）。
    """
    import collections

    out: dict[str, Any] = {"dir": collections.Counter(), "band": collections.Counter(),
                           "missingAnchor": 0, "jevInsufficient": 0, "engineInsufficient": 0,
                           "byMode": collections.Counter(), "days": []}
    per_day: dict[str, dict[str, Any]] = {}
    for doc in db["hotlist_jev_trend_recheck_pilot"].find(
            {"status": "ok", "slotTime": PILOT_SLOT}):
        date = str(doc.get("tradingDate") or "")
        if not date or (start and date < start):
            continue
        jd = doc.get("trendDirection")
        ed = doc.get("engineDirection")
        mode = str(doc.get("mode") or "?")
        if jd == "insufficient":
            out["jevInsufficient"] += 1
        if not ed:
            out["missingAnchor"] += 1
            continue
        if jd in ("buy", "sell", "hold"):
            verdict = "agree" if jd == ed else "diverge"
            out["dir"][verdict] += 1
            out["byMode"][(mode, verdict)] += 1
            day = per_day.setdefault(date, {"date": date, "agree": 0, "diverge": 0})
            day[verdict] += 1
        js, es = doc.get("trendScore"), doc.get("engineScore")
        jb, eb = strength_band(js), strength_band(es)
        if jb and eb:
            out["band"]["agree" if jb == eb else "diverge"] += 1
    out["days"] = [per_day[k] for k in sorted(per_day)]
    total = out["dir"]["agree"] + out["dir"]["diverge"]
    out["summary"] = {
        "dirAgree": out["dir"]["agree"], "dirDiverge": out["dir"]["diverge"],
        "dirAgreeRate": round(out["dir"]["agree"] / total * 100, 1) if total else None,
        "bandAgree": out["band"]["agree"], "bandDiverge": out["band"]["diverge"],
        "byMode": {f"{k[0]}:{k[1]}": v for k, v in sorted(out["byMode"].items())},
        "missingAnchor": out["missingAnchor"], "jevInsufficient": out["jevInsufficient"],
        "engineInsufficient": out["engineInsufficient"],
    }
    return out


def __main__():
    ap = argparse.ArgumentParser(description="趋势维独立判读（题集 v1 试点）")
    ap.add_argument("--trend-day", dest="trend_day", action="append", default=[],
                    help="指定交易日跑趋势独立判读（可多次传参）")
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
                    help="判读帧（默认 15:00；趋势需 ≥22 次出现，午盘帧多为 fallback 模式）")
    ap.add_argument("--ledger", action="store_true",
                    help="只跑对照台账（纯读零调用零 jev）")
    args = ap.parse_args()
    if not args.trend_day and not args.ledger:
        raise SystemExit("需要 --trend-day 或 --ledger（可多次传参）")
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
    run_trend_day(db, args.trend_day, args.dataset_id, fire=args.fire,
                  workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                  only_codes=only)


if __name__ == "__main__":
    __main__()
