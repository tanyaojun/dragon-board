# -*- coding: utf-8 -*-
"""热度维 + 量价维独立判读 runner（2026-10-15 试点第四/五维；题集合同=docs/hotlist-jev/jev-heat-volume-recheck-preregistration.md）。

- 取数（全部只读，零写入快照集合）：**直接复用共振 pilot 的取数原语**
  （operations/jev_resonance_recheck.rolling_frames / appearance_series）——热度维的横截面
  percentile 与共振/趋势共用同一条「跨日最近 ≤50 次进榜出现」分位序列，取数只有一份；
- **同源衍生**：percentile/percentileDelta/relativeToMarket 委托引擎
  trend/cross_section.compute_cross_section 的同一输入衍生；涨跌停/涨幅档位分委托引擎
  ranking/volume_price 的同一函数——可复现算术衍生，非判定产物；引擎自己的
  tier/quadrant/score 一律不喂；
- 对照锚 = 同帧 snapshot_analysis.observation.crossSection.signalTier（热度）/
  observation.volumePrice.{signalTier,quadrant,score}（量价）——只作台账机械对照，不回写引擎；
- **amountRatio 不喂**：引擎生产链 observation.amountRatio 恒 None（G3 判据从未在快照分析链
  生效，已记账不动引擎），本题集严格同源；
- 人口=判读帧全池，**无抽样帽**；预检 data_insufficient 不调用落留痕；
- 落库两个集合：hotlist_jev_heat_recheck_pilot（_id={date}:{slot}:{code}:HEA）、
  hotlist_jev_volume_recheck_pilot（_id={date}:{slot}:{code}:VPQ）；
- 默认 dry-run（零 jev 调用）；--fire 且 token 才真实调用（AGENTS §1.2-7）；
  done-skip **按题集代际**，同 _id 整档覆盖（改门重跑不挡、不留双轨）。
"""
from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, _questions_hash, _usage_tokens
from backend.analysis.hotlist.jev_heat_volume_ammo import (
    HEAT_AMMO_VERSION,
    HEAT_ATTRIBUTIONS,
    HEAT_EVOLUTIONS,
    QUESTIONS_HEAT_RECHECK,
    QUESTIONS_VOLUME_RECHECK,
    QUESTION_SET_VERSION_HEAT_RECHECK,
    QUESTION_SET_VERSION_VOLUME_RECHECK,
    VOLUME_AMMO_VERSION,
    VOLUME_CAUSES,
    VOLUME_TRADABILITY,
    build_heat_narrative,
    build_volume_narrative,
    heat_attribution_anchor,
    heat_derived,
    heat_evolution_anchor,
    heat_risk_flag,
    volume_cause_anchor,
    volume_derived,
    volume_risk_flag,
    volume_tradability_anchor,
)
from backend.operations.jev_resonance_recheck import appearance_series, rolling_frames
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

PILOT_SLOT = "15:00"
TOKEN_FUSE = 200_000  # 两个维度的合计熔断线（缺省值；单次运行逐 call 累计）

HEAT_COLLECTION = "hotlist_jev_heat_recheck_pilot"
VOLUME_COLLECTION = "hotlist_jev_volume_recheck_pilot"
HEAT_SUFFIX = "HEA"
VOLUME_SUFFIX = "VPQ"


# ── 引擎同帧读数（对照锚快照；只读不回写）──

def _engine_cross_section(db, dataset_id: str, snapshot_id: str, code: str) -> dict[str, Any] | None:
    """同帧引擎横截面读数（observation.crossSection；缺失如实 None，不伪造）。"""
    doc = db["snapshot_analysis"].find_one(
        {"datasetId": dataset_id, "snapshotId": snapshot_id, "code": code})
    r = (((doc or {}).get("analysis") or {}).get("observation") or {}).get("crossSection") or {}
    if not r:
        return None
    return {"percentile": r.get("percentile"), "percentileDelta": r.get("percentileDelta"),
            "relativeToMarket": r.get("relativeToMarket"), "signalTier": r.get("signalTier"),
            "tierReasons": r.get("tierReasons")}


def _engine_volume_price(db, dataset_id: str, snapshot_id: str, code: str) -> dict[str, Any] | None:
    """同帧引擎量价读数（observation.volumePrice；缺失如实 None，不伪造）。"""
    doc = db["snapshot_analysis"].find_one(
        {"datasetId": dataset_id, "snapshotId": snapshot_id, "code": code})
    r = (((doc or {}).get("analysis") or {}).get("observation") or {}).get("volumePrice") or {}
    if not r:
        return None
    return {"score": r.get("score"), "direction": r.get("direction"),
            "quadrant": r.get("quadrant"), "signalTier": r.get("signalTier"),
            "tierReasons": r.get("tierReasons"),
            "amountRatio": (((doc or {}).get("analysis") or {}).get("observation") or {}).get("amountRatio")}


# ── 人口构建（纯取数+预检；无调用）──

def build_population(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                     slot: str = PILOT_SLOT) -> dict:
    """判读帧全池人口的热度/量价语料（横截面衍生/帧行字段全部引擎同源现算）。

    返回 {candidates, insufficient, meta}；candidates 每项含 code/name/series/heat/volume/
    quality/riskFlagHeat/riskFlagVolume/engineHeat/engineVolume（对照锚快照）。
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
    # 市场横截面基准（引擎同源：frame_market_median / frame_market_median_percentile）
    from backend.analysis.ranktrend.engine.runtime import (
        frame_market_median, frame_market_median_percentile)
    engine_frames = [{"stocks": list(rows.values())} for _d, _s, _sid, rows in frames]
    median_short, sample_count = frame_market_median(engine_frames, judgment)
    median_pct = frame_market_median_percentile(engine_frames[judgment])
    pool_size = len(engine_frames[judgment].get("stocks") or [])
    market = ({"medianShortChange": median_short, "sampleCount": sample_count,
               "medianPercentile": median_pct, "poolSize": pool_size}
              if median_pct is not None else None)
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
        hd = heat_derived(pcts, (market or {}).get("medianPercentile"))
        vd = volume_derived(code, row.get("change"), row.get("volumeRatio"),
                            row.get("zlje"), row.get("zljzb"))
        rf_h = heat_risk_flag(hd.get("percentile"), hd.get("percentileDelta"))
        rf_v = volume_risk_flag(row.get("change"), row.get("volumeRatio"))
        quality = {"missingAppearances": [],
                   "missingFields": [f for f in ("change", "volumeRatio", "zlje", "zljzb")
                                     if row.get(f) is None]}
        cand = {"code": code, "name": row.get("name"), "series": series, "heat": hd,
                "volume": vd, "market": market, "bars": bars,
                "quality": quality, "riskFlagHeat": rf_h, "riskFlagVolume": rf_v,
                "heatAttributionAnchor": heat_attribution_anchor(
                    hd.get("percentile"), hd.get("relativeToMarket")),
                "heatEvolutionAnchor": heat_evolution_anchor(pcts),
                "volumeCauseAnchor": volume_cause_anchor(
                    vd.get("change"), vd.get("volumeRatio"), vd.get("zljzb"),
                    vd.get("zlje"), vd.get("limitUp"), vd.get("limitDown")),
                "volumeTradabilityAnchor": volume_tradability_anchor(
                    vd.get("change"), vd.get("volumeRatio"), vd.get("zljzb"),
                    vd.get("limitUp"), vd.get("limitDown")),
                "engineHeat": _engine_cross_section(db, dataset_id, judgment_sid, code),
                "engineVolume": _engine_volume_price(db, dataset_id, judgment_sid, code)}
        (insufficient if (rf_h["level"] == "data_insufficient"
                          and rf_v["level"] == "data_insufficient") else candidates).append(cand)
    meta = {"tradingDate": date, "slot": slot, "snapshotId": judgment_sid,
            "frameWindow": len(frames), "poolSize": len(judgment_rows),
            "population_n": len(candidates) + len(insufficient),
            "heatInsufficient": sum(1 for c in candidates + insufficient
                                    if c["riskFlagHeat"]["level"] == "data_insufficient"),
            "volumeInsufficient": sum(1 for c in candidates + insufficient
                                      if c["riskFlagVolume"]["level"] == "data_insufficient")}
    return {"candidates": candidates, "insufficient": insufficient, "meta": meta}


def _insufficient_doc(date: str, slot: str, code: str, name: Any, dim: str,
                      rf: dict, ammo_version: str, qsv: str, qhash: str) -> dict:
    suffix = HEAT_SUFFIX if dim == "heat" else VOLUME_SUFFIX
    return {"_id": f"{date}:{slot}:{code}:{suffix}", "origin": f"{dim}_recheck_pilot",
            "tradingDate": date, "slotTime": slot, "code": code, "name": name,
            "ammoVersion": ammo_version, "questionSetVersion": qsv,
            "questionSetHash": qhash, "riskFlag": rf, "status": "data_insufficient",
            "answers": None, "responseRaw": None, "usage": None, "latencyMs": None,
            "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ── 单日运行 ──

def run_heat_volume_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                        fire: bool = False, workers: int = 1, token_fuse: int | None = None,
                        slot: str = PILOT_SLOT, only_codes: list[str] | None = None,
                        dims: tuple[str, ...] = ("heat", "volume")) -> dict:
    """热度/量价维独立判读（题集 v2）：全池无帽；dry-run 零调用；--fire 才真实调用。

    **CR 2026-10-15 定位修正**：v2 曾被称作「逻辑推理题集」，首日 244 例验证后确认四道
    逻辑主问的判据文本与锚共用同一组阈值常量 → 一致率只反映规则执行保真度，**不构成
    推理能力证据**（自证）。唯一判据未给数值阈值的是 heat_evolution，其分歧有判读价值。
    读数不得用于任何结论；详见预登记 §十三/§十五。"""
    heat_col = db[HEAT_COLLECTION]
    vol_col = db[VOLUME_COLLECTION]
    q_heat, q_vol = QUESTIONS_HEAT_RECHECK, QUESTIONS_VOLUME_RECHECK
    hash_heat = _questions_hash(q_heat)
    hash_vol = _questions_hash(q_vol)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        pop = build_population(db, date, dataset_id, slot)
        if pop["meta"].get("error"):
            stats["no_frame"] += 1
            print(f"[heat/volume] {date} {slot} {pop['meta']['error']}，跳过")
            continue
        print(f"[heat/volume] {date} 判读槽={pop['meta']['slot']} 池={pop['meta']['poolSize']} "
              f"候选={len(pop['candidates'])} 预检不足={len(pop['insufficient'])} "
              f"热度不可判={pop['meta']['heatInsufficient']} 量价不可判={pop['meta']['volumeInsufficient']}")
        allowed = set(only_codes) if only_codes else None
        todo = [c for c in pop["candidates"]
                if allowed is None or c["code"] in allowed]
        if not fire:
            for c in todo[:20]:
                print(f"[heat/volume] dry-run {date}:{slot}:{c['code']} bars={c['bars']} "
                      f"heatFlag={c['riskFlagHeat']['level']} "
                      f"volFlag={c['riskFlagVolume']['level']}")
            print(f"[heat/volume] dry-run 待判 {len(todo)} 例 × {len(dims)} 维（全池口径，无帽）")
            continue
        if tokens >= fuse:
            print(f"[heat/volume] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
            continue

        def _work(c: dict) -> tuple[str, dict, dict, int]:
            nonlocal tokens
            used_total = 0
            out: dict[str, dict] = {}
            if "heat" in dims:
                if c["riskFlagHeat"]["level"] == "data_insufficient":
                    heat_col.replace_one(
                        {"_id": f"{date}:{slot}:{c['code']}:{HEAT_SUFFIX}"},
                        _insufficient_doc(date, slot, c["code"], c["name"], "heat",
                                          c["riskFlagHeat"], HEAT_AMMO_VERSION,
                                          QUESTION_SET_VERSION_HEAT_RECHECK, hash_heat),
                        upsert=True)
                    with stat_lock:
                        stats["data_insufficient"] += 1
                else:
                    narrative = build_heat_narrative(
                        trading_date=date, slot=slot, code=c["code"], name=c["name"],
                        series=c["series"], derived=c["heat"], market=c["market"],
                        entry={"isNew": c["bars"] == 1,
                               "currentPercentile": (c["heat"] or {}).get("percentile")},
                        quality=c["quality"])
                    env, ms = _dispatch_jev(narrative, q_heat)
                    parsed = parse_jev_response(env, ms, expected_keys=set(q_heat))
                    used_total += _usage_tokens(parsed.get("usage"))
                    ans = parsed.get("answers") or {}
                    attribution = ans.get("heat_attribution") or {}
                    evolution = ans.get("heat_evolution") or {}
                    direction = ans.get("heat_direction") or {}
                    tier = ans.get("heat_tier") or {}
                    eng = c.get("engineHeat") or {}
                    doc = {"_id": f"{date}:{slot}:{c['code']}:{HEAT_SUFFIX}",
                           "origin": "heat_recheck_pilot", "tradingDate": date,
                           "slotTime": slot, "code": c["code"], "name": c["name"],
                           "ammoVersion": HEAT_AMMO_VERSION,
                           "questionSetVersion": QUESTION_SET_VERSION_HEAT_RECHECK,
                           "questionSetHash": hash_heat, "riskFlag": c["riskFlagHeat"],
                           "bars": c["bars"], "status": "ok" if parsed["ok"] else "degraded",
                           "narrative": narrative, "questionsRaw": q_heat,
                           "answers": parsed.get("answers"),
                           # V2 逻辑主问（无引擎锚，锚=同输入机械复算）
                           "heatAttribution": attribution.get("choice"),
                           "heatAttributionConfidence": attribution.get("confidence"),
                           "heatEvolution": evolution.get("choice"),
                           "heatEvolutionConfidence": evolution.get("confidence"),
                           "attributionAnchor": c.get("heatAttributionAnchor"),
                           "evolutionAnchor": c.get("heatEvolutionAnchor"),
                           # 语义问（无引擎锚，只落档等 T+1）
                           "heatDirection": direction.get("choice"),
                           "heatConfidence": direction.get("confidence"),
                           "heatProbabilities": direction.get("probabilities"),
                           # 复现基线（协议层阴性对照）
                           "heatTier": tier.get("choice"),
                           "heatTierConfidence": tier.get("confidence"),
                           "enginePercentile": eng.get("percentile"),
                           "enginePercentileDelta": eng.get("percentileDelta"),
                           "engineRelativeToMarket": eng.get("relativeToMarket"),
                           "engineTier": eng.get("signalTier"),
                           "model": parsed.get("model"), "usage": parsed.get("usage"),
                           "latencyMs": ms, "errorCode": parsed.get("errorCode"),
                           "errorDetail": parsed.get("errorDetail"), "responseRaw": env,
                           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    heat_col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                    out["heat"] = doc
            if "volume" in dims:
                if c["riskFlagVolume"]["level"] == "data_insufficient":
                    vol_col.replace_one(
                        {"_id": f"{date}:{slot}:{c['code']}:{VOLUME_SUFFIX}"},
                        _insufficient_doc(date, slot, c["code"], c["name"], "volume",
                                          c["riskFlagVolume"], VOLUME_AMMO_VERSION,
                                          QUESTION_SET_VERSION_VOLUME_RECHECK, hash_vol),
                        upsert=True)
                    with stat_lock:
                        stats["data_insufficient"] += 1
                else:
                    narrative = build_volume_narrative(
                        trading_date=date, slot=slot, code=c["code"], name=c["name"],
                        derived=c["volume"], quality=c["quality"])
                    env, ms = _dispatch_jev(narrative, q_vol)
                    parsed = parse_jev_response(env, ms, expected_keys=set(q_vol))
                    used_total += _usage_tokens(parsed.get("usage"))
                    ans = parsed.get("answers") or {}
                    cause = ans.get("volume_cause") or {}
                    tradability = ans.get("volume_tradability") or {}
                    direction = ans.get("volume_direction") or {}
                    tier = ans.get("volume_tier") or {}
                    quad = ans.get("volume_quadrant") or {}
                    eng = c.get("engineVolume") or {}
                    doc = {"_id": f"{date}:{slot}:{c['code']}:{VOLUME_SUFFIX}",
                           "origin": "volume_recheck_pilot", "tradingDate": date,
                           "slotTime": slot, "code": c["code"], "name": c["name"],
                           "ammoVersion": VOLUME_AMMO_VERSION,
                           "questionSetVersion": QUESTION_SET_VERSION_VOLUME_RECHECK,
                           "questionSetHash": hash_vol, "riskFlag": c["riskFlagVolume"],
                           "status": "ok" if parsed["ok"] else "degraded",
                           "narrative": narrative, "questionsRaw": q_vol,
                           "answers": parsed.get("answers"),
                           # V2 逻辑主问（无引擎锚，锚=同输入机械复算）
                           "volumeCause": cause.get("choice"),
                           "volumeCauseConfidence": cause.get("confidence"),
                           "volumeTradability": tradability.get("choice"),
                           "volumeTradabilityConfidence": tradability.get("confidence"),
                           "causeAnchor": c.get("volumeCauseAnchor"),
                           "tradabilityAnchor": c.get("volumeTradabilityAnchor"),
                           # 语义问（无引擎锚，只落档等 T+1）
                           "volumeDirection": direction.get("choice"),
                           "volumeConfidence": direction.get("confidence"),
                           "volumeProbabilities": direction.get("probabilities"),
                           # 复现基线（协议层阴性对照）
                           "volumeTier": tier.get("choice"),
                           "volumeTierConfidence": tier.get("confidence"),
                           "volumeQuadrant": quad.get("choice"),
                           "engineScore": eng.get("score"),
                           "engineDirection": eng.get("direction"),
                           "engineQuadrant": eng.get("quadrant"),
                           "engineTier": eng.get("signalTier"),
                           "engineAmountRatio": eng.get("amountRatio"),
                           "model": parsed.get("model"), "usage": parsed.get("usage"),
                           "latencyMs": ms, "errorCode": parsed.get("errorCode"),
                           "errorDetail": parsed.get("errorDetail"), "responseRaw": env,
                           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    vol_col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                    out["volume"] = doc
            return c["code"], out, c, used_total

        # done-skip 按题集代际：同代际已 ok 才跳过；代际升级（改门）必须重跑。
        # 预检不足的维度**不算已判**：留痕文档每次 fire 都重写（幂等、零调用），
        # 否则「热度已判 + 量价预检不足」的股票会被误判为全量完成而永不落量价留痕。
        skipped: set[str] = set()
        for c in todo:
            sid = c["code"]
            heat_done = ("heat" not in dims
                         or c["riskFlagHeat"]["level"] == "data_insufficient"
                         or bool(heat_col.find_one(
                             {"_id": f"{date}:{slot}:{sid}:{HEAT_SUFFIX}",
                              "status": "ok",
                              "questionSetVersion": QUESTION_SET_VERSION_HEAT_RECHECK})))
            vol_done = ("volume" not in dims
                        or c["riskFlagVolume"]["level"] == "data_insufficient"
                        or bool(vol_col.find_one(
                            {"_id": f"{date}:{slot}:{sid}:{VOLUME_SUFFIX}",
                             "status": "ok",
                             "questionSetVersion": QUESTION_SET_VERSION_VOLUME_RECHECK})))
            if heat_done and vol_done and not (
                    c["riskFlagHeat"]["level"] == "data_insufficient"
                    or c["riskFlagVolume"]["level"] == "data_insufficient"):
                stats["skip"] += 1
                skipped.add(sid)
        todo = [c for c in todo if c["code"] not in skipped]
        if not todo:
            print(f"[heat/volume] {date} 全部已判（同代际），跳过")
            continue

        # workers>1 时 _work/_run_one 并发跑：tokens 与 stats 的读-改-写必须加锁，
        # 否则 Python 的 `+=` 非原子会丢计数（2026-10-15 CR：三个新 runner 同款，本 runner 实修）
        stat_lock = threading.Lock()

        def _run_one(c: dict) -> None:
            nonlocal tokens
            with stat_lock:
                if tokens >= fuse:
                    print(f"[heat/volume] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    return
            code, out, _c, used = _work(c)
            with stat_lock:
                tokens += used
                for dim, doc in out.items():
                    stats["ok" if doc["status"] == "ok" else "degraded"] += 1
            h = out.get("heat") or {}
            v = out.get("volume") or {}
            print(f"[heat/volume] {date} {code} → "
                  f"热度 {h.get('heatAttribution', '--')}/{h.get('heatEvolution', '--')}"
                  f"(锚 {h.get('attributionAnchor', '--')}/{h.get('evolutionAnchor', '--')}) · "
                  f"量价 {v.get('volumeCause', '--')}/{v.get('volumeTradability', '--')}"
                  f"(锚 {v.get('causeAnchor', '--')}/{v.get('tradabilityAnchor', '--')}) "
                  f"tokens={used}(cum={tokens})")

        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(_run_one, todo))
        else:
            for c in todo:
                _run_one(c)
    stats["tokens"] = tokens
    print("FINAL[heat/volume]:", stats)
    return stats


# ── 对照台账（纯读+小写，零 jev 调用）──

def build_ledger(db: Any, dataset_id: str = DEFAULT_DATASET_ID,
                 start: str | None = None) -> dict[str, Any]:
    """jev 热度/量价判读 vs 复算锚/引擎读数的一致性台账（同帧同股机械对照）。

    V2 四道主问（CR 2026-10-15：判据文本与锚**共用同一组阈值**，属自证题集，
    一致率=规则执行保真度，不是推理能力证据）：
      heatAttribution ↔ attributionAnchor（个体强 vs 全池普涨，分母效应归因）；
      heatEvolution ↔ evolutionAnchor（序列形态）；
      volumeCause ↔ causeAnchor（量价主因归因）；
      volumeTradability ↔ tradabilityAnchor（可交易性）。
    复现基线（协议层阴性对照，唯一有结论价值的读数）：heatTier ↔ 引擎 crossSection.signalTier、
      volumeTier/volumeQuadrant ↔ 引擎 volumePrice.{signalTier,quadrant}。
    语义 direction **无锚**，只统计分布（引擎只给涨跌方向/象限，不给「是否支持做多」）。
    **验收指标是隔日胜率 × 盈亏比，不是这里的任何一致率**（与共振/趋势同规）。
    """
    import collections

    out: dict[str, Any] = {
        "heatAttribution": collections.Counter(), "heatEvolution": collections.Counter(),
        "volumeCause": collections.Counter(), "volumeTradability": collections.Counter(),
        "heatTier": collections.Counter(), "volumeTier": collections.Counter(),
        "volumeQuadrant": collections.Counter(),
        "heatDirection": collections.Counter(), "volumeDirection": collections.Counter(),
        "missingAnchor": 0, "jevInsufficient": 0, "anchorInsufficient": 0, "days": []}
    per_day: dict[str, dict[str, Any]] = {}

    def _tally(counter: collections.Counter, got: Any, anchor: Any, day: dict, key: str,
               valid: tuple[str, ...]) -> bool:
        """逻辑题对表：got/anch 均在合法选项内才计票。

        三种不可比分别处置（fail-visible，不混票）：
        - got ∈ {None, insufficient}：jev 判「数据不可用」→ 不计 agree/diverge（jevInsufficient 单列）；
        - anchor 缺失/非法（不在合法选项内）：**真缺锚** → missingAnchor（记账待查）；
        - anchor = insufficient：序列/字段太短导致锚侧也不可判 → 既非一致也非分歧，
          单列 anchorInsufficient，**不得计入 missingAnchor**（否则「序列短」会被误报成「取数缺锚」）。
        """
        if got in (None, "insufficient"):
            return False
        if anchor == "insufficient":
            out["anchorInsufficient"] += 1
            return False
        if anchor not in valid:
            out["missingAnchor"] += 1
            return False
        verdict = "agree" if got == anchor else "diverge"
        counter[verdict] += 1
        day[key + ("Agree" if verdict == "agree" else "Diverge")] = \
            day.get(key + ("Agree" if verdict == "agree" else "Diverge"), 0) + 1
        return True

    for doc in db[HEAT_COLLECTION].find({"status": "ok", "slotTime": PILOT_SLOT}):
        date = str(doc.get("tradingDate") or "")
        if not date or (start and date < start):
            continue
        day = per_day.setdefault(date, {"date": date})
        if doc.get("heatAttribution") == "insufficient":
            out["jevInsufficient"] += 1
        _tally(out["heatAttribution"], doc.get("heatAttribution"), doc.get("attributionAnchor"),
               day, "attr", HEAT_ATTRIBUTIONS)
        _tally(out["heatEvolution"], doc.get("heatEvolution"), doc.get("evolutionAnchor"),
               day, "evol", HEAT_EVOLUTIONS)
        jt, et = doc.get("heatTier"), doc.get("engineTier")
        if jt in ("A", "B", "C", "D", "unknown") and et:
            verdict = "agree" if jt == et else "diverge"
            out["heatTier"][verdict] += 1
            day["heatTier" + ("Agree" if verdict == "agree" else "Diverge")] = \
                day.get("heatTier" + ("Agree" if verdict == "agree" else "Diverge"), 0) + 1
        elif jt in ("A", "B", "C", "D", "unknown") and not et:
            out["missingAnchor"] += 1
        if doc.get("heatDirection"):
            out["heatDirection"][doc["heatDirection"]] += 1
    for doc in db[VOLUME_COLLECTION].find({"status": "ok", "slotTime": PILOT_SLOT}):
        date = str(doc.get("tradingDate") or "")
        if not date or (start and date < start):
            continue
        day = per_day.setdefault(date, {"date": date})
        if doc.get("volumeCause") == "insufficient":
            out["jevInsufficient"] += 1
        _tally(out["volumeCause"], doc.get("volumeCause"), doc.get("causeAnchor"),
               day, "cause", VOLUME_CAUSES)
        _tally(out["volumeTradability"], doc.get("volumeTradability"),
               doc.get("tradabilityAnchor"), day, "trad", VOLUME_TRADABILITY)
        jt, et = doc.get("volumeTier"), doc.get("engineTier")
        jq, eq = doc.get("volumeQuadrant"), doc.get("engineQuadrant")
        if jt in ("A", "B", "C", "D", "E", "unknown") and et:
            verdict = "agree" if jt == et else "diverge"
            out["volumeTier"][verdict] += 1
            day["volTier" + ("Agree" if verdict == "agree" else "Diverge")] = \
                day.get("volTier" + ("Agree" if verdict == "agree" else "Diverge"), 0) + 1
        elif jt in ("A", "B", "C", "D", "E", "unknown") and not et:
            out["missingAnchor"] += 1
        if jq in ("rise_volume", "rise_shrink", "normal", "fall_volume", "fall_shrink") and eq:
            verdict = "agree" if jq == eq else "diverge"
            out["volumeQuadrant"][verdict] += 1
            day["volQuad" + ("Agree" if verdict == "agree" else "Diverge")] = \
                day.get("volQuad" + ("Agree" if verdict == "agree" else "Diverge"), 0) + 1
        elif jq in ("rise_volume", "rise_shrink", "normal", "fall_volume", "fall_shrink") and not eq:
            out["missingAnchor"] += 1
        if doc.get("volumeDirection"):
            out["volumeDirection"][doc["volumeDirection"]] += 1
    out["days"] = [per_day[k] for k in sorted(per_day)]

    def rate(c: collections.Counter) -> float | None:
        t = c["agree"] + c["diverge"]
        return round(c["agree"] / t * 100, 1) if t else None

    out["summary"] = {
        # V2 逻辑主问（对复算锚）
        "heatAttributionAgree": out["heatAttribution"]["agree"],
        "heatAttributionDiverge": out["heatAttribution"]["diverge"],
        "heatAttributionAgreeRate": rate(out["heatAttribution"]),
        "heatEvolutionAgree": out["heatEvolution"]["agree"],
        "heatEvolutionDiverge": out["heatEvolution"]["diverge"],
        "heatEvolutionAgreeRate": rate(out["heatEvolution"]),
        "volumeCauseAgree": out["volumeCause"]["agree"],
        "volumeCauseDiverge": out["volumeCause"]["diverge"],
        "volumeCauseAgreeRate": rate(out["volumeCause"]),
        "volumeTradabilityAgree": out["volumeTradability"]["agree"],
        "volumeTradabilityDiverge": out["volumeTradability"]["diverge"],
        "volumeTradabilityAgreeRate": rate(out["volumeTradability"]),
        # 复现基线（对引擎读数；协议层健康度阴性对照）
        "heatTierAgree": out["heatTier"]["agree"], "heatTierDiverge": out["heatTier"]["diverge"],
        "heatTierAgreeRate": rate(out["heatTier"]),
        "volumeTierAgree": out["volumeTier"]["agree"], "volumeTierDiverge": out["volumeTier"]["diverge"],
        "volumeTierAgreeRate": rate(out["volumeTier"]),
        "volumeQuadrantAgree": out["volumeQuadrant"]["agree"],
        "volumeQuadrantDiverge": out["volumeQuadrant"]["diverge"],
        "volumeQuadrantAgreeRate": rate(out["volumeQuadrant"]),
        # 语义问（无锚，只落分布）
        "heatDirection": dict(out["heatDirection"]), "volumeDirection": dict(out["volumeDirection"]),
        "missingAnchor": out["missingAnchor"], "jevInsufficient": out["jevInsufficient"],
        "anchorInsufficient": out["anchorInsufficient"],
    }
    return out


def __main__():
    ap = argparse.ArgumentParser(description="热度维+量价维独立判读（题集 v2；自证题集，读数不用于结论）")
    ap.add_argument("--day", dest="day", action="append", default=[],
                    help="指定交易日跑独立判读（可多次传参）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    ap.add_argument("--fire", action="store_true",
                    help="真实调用 jev（只走预登记+用户批准开火路径；默认 dry-run 零调用）")
    ap.add_argument("--codes", dest="codes", default="",
                    help="逗号分隔 code 子集（单股判读；缺省=全池）")
    ap.add_argument("--workers", dest="workers", type=int, default=1,
                    help="并发数（默认 1 串行；回填建议 4）")
    ap.add_argument("--token-fuse", dest="token_fuse", type=int, default=None,
                    help="本次运行熔断线（缺省=200k；全量回填显式放宽）")
    ap.add_argument("--slot", dest="slot", default=PILOT_SLOT, help="判读帧（默认 15:00）")
    ap.add_argument("--dim", dest="dim", default="both", choices=("heat", "volume", "both"),
                    help="跑哪一维（默认 both）")
    ap.add_argument("--ledger", action="store_true",
                    help="只跑对照台账（纯读零调用零 jev）")
    args = ap.parse_args()
    if not args.day and not args.ledger:
        raise SystemExit("需要 --day 或 --ledger（可多次传参）")
    if args.fire and not ((os.environ.get("JEV_CF_TOKEN") or "").strip()
                          or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip()):
        raise SystemExit("--fire 需要环境变量 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    if args.ledger:
        import json
        print(json.dumps(build_ledger(db, args.dataset_id)["summary"], ensure_ascii=False))
        return
    dims = ("heat", "volume") if args.dim == "both" else (args.dim,)
    only = [c.strip() for c in args.codes.split(",") if c.strip()] or None
    run_heat_volume_day(db, args.day, args.dataset_id, fire=args.fire,
                        workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                        only_codes=only, dims=dims)


if __name__ == "__main__":
    __main__()
