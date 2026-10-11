# -*- coding: utf-8 -*-
"""行情列表五维信号 jev 复核双题集 runner（vote_confirm + lifecycle_recheck pilot）。

预登记（唯一合同）：docs/hotlist-jev/jev-vote-confirm-lifecycle-recheck-preregistration.md。
取数：snapshot_frames + snapshot_stock_rows + snapshot_analysis（与规则链/情绪链同源 join，
正式快照读口合同不变，本 runner 只读不写快照集合）。

口径（预登记冻结）：
- 槽位 = half_hour 15:00（当日收盘槽；daily 15:30 帧行情字段实测稀疏不可用）；
- 人口：A=synergy 档 ∈ {S,A,B,D}（E 归 B 语境、C 无方向不进）；B=非 cooling；
- 预检 riskFlag（runner 侧）：data_insufficient 不调用落留痕文档；partial/ok 进抽样；
- 抽样（确定性排序防挑样）：A 每日 ≤8(buy)+≤4(sell)，B 每日 ≤8（点火/扩散优先 ≤5）；
- 熔断：TOKEN_FUSE=150_000 tokens/次运行，逐 call 累计，达限即停（预登记 §六）；
- 落库（预登记 §八）：answers 原样包 + confidence 升顶层 + responseRaw ok/degraded 一律
  存完整 envelope（修 cycle pilot「ok 存 None」口子）。

默认 dry-run（零 jev 调用：打印人口/预检/抽样/叙事字数）；--fire 且有 token 才真实调用
（开火只走预登记 + 用户批准路径，AGENTS §1.2-7）。
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, _questions_hash, _usage_tokens
from backend.analysis.hotlist.jev_vote_ammo import (
    BACKFILL_FIELDS,
    QUESTION_SET_VERSION_LIFECYCLE_RECHECK,
    QUESTION_SET_VERSION_VOTE_CONFIRM,
    QUESTIONS_LIFECYCLE_RECHECK,
    QUESTIONS_VOTE_CONFIRM,
    STAGE_ZH,
    VOTE_AMMO_VERSION,
    backfill_quote_fields,
    build_lifecycle_narrative,
    build_vote_narrative,
    lifecycle_risk_flag,
    sample_lifecycle,
    sample_vote,
    synergy_direction,
    vote_risk_flag,
)
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

PILOT_SLOT = "15:00"
TOKEN_FUSE = 150_000  # 预登记 §六 硬顶（一次运行的逐 call 累计）

_EVIDENCE_FIELDS = ("change", "volumeRatio", "zlje", "turnoverRate")


# ── 取数（只读）──

def _slot_frame(db, date: str, dataset_id: str, slot: str = PILOT_SLOT) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": slot})


def _day_rows_by_slot(db, date: str, dataset_id: str) -> list[tuple[str, dict[str, dict]]]:
    """当日 half_hour 逐槽 (slotTime, {code: row})，按槽升序（Python 排序，fake db 友好）。"""
    frames = sorted(
        db["snapshot_frames"].find({"datasetId": dataset_id, "type": "half_hour",
                                    "tradingDate": date}, {"snapshotId": 1, "slotTime": 1}),
        key=lambda f: str(f.get("slotTime") or ""))
    out: list[tuple[str, dict[str, dict]]] = []
    for f in frames:
        rows = db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "snapshotId": str(f.get("snapshotId") or "")})
        out.append((str(f.get("slotTime") or ""), {str(r.get("code")): r for r in rows}))
    return out


def _frame_sparse_fields(rows: list[dict], ratio: float = 0.9) -> list[str]:
    """帧级行情字段稀疏判定：zero/None 占比 ≥ratio → 帧级稀疏（daily 15:30 实测全 0/null；
    live 帧 zlje 缺 7/255 这类个股零星缺口不会误判）。"""
    out: list[str] = []
    n = len(rows)
    if not n:
        return out
    for f in BACKFILL_FIELDS:
        bad = sum(1 for r in rows if r.get(f) is None or r.get(f) == 0)
        if bad / n >= ratio:
            out.append(f)
    return out


def _trajectory(points: list[tuple[str, dict[str, dict]]], code: str,
                label: str = "slot") -> list[dict]:
    """逐时点 {label, rank, change}；该股缺行 → None（fail-visible，叙事标「缺」）。
    label=slot（日内槽位）| date（跨日日期，原料跨日化 b 代）。"""
    out = []
    for t, by_code in points:
        r = by_code.get(code)
        out.append({label: t,
                    "rank": r.get("rank") if r else None,
                    "change": r.get("change") if r else None})
    return out


def _prev_trading_dates(db, date: str, dataset_id: str, slot: str, n: int = 10) -> list[str]:
    """date 之前最近 n 个有 slot 帧的交易日（升序）。跨日原料取数用（与判读帧同槽位定格）。"""
    frames = db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": slot},
        {"tradingDate": 1})
    dates = sorted({str(f.get("tradingDate")) for f in frames
                    if str(f.get("tradingDate") or "") and str(f.get("tradingDate")) < date})
    return dates[-n:]


def _multi_day_rows_by_day(db, date: str, dataset_id: str, slot: str, n: int = 10):
    """近 n 交易日同 slot 帧 → [(tradingDate, {code: row})]（升序，不含当日）。跨日原料：让
    叙事可数锚（「多日」「峰值」）与引擎跨日窗口度量同源——铁律 3/4 补原料方向修复。"""
    out = []
    for d in _prev_trading_dates(db, date, dataset_id, slot, n):
        f = _slot_frame(db, d, dataset_id, slot)
        if not f:
            continue
        rows = db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "snapshotId": str(f.get("snapshotId") or "")})
        out.append((d, {str(r.get("code")): r for r in rows}))
    return out


def _prev_day_stage(db, date: str, dataset_id: str, code: str, slot: str = PILOT_SLOT) -> tuple[str | None, Any]:
    """前一交易日（有 15:00 帧的最大 tradingDate < date）该股 lifecycle stage。缺 → (None, None)。"""
    frames = db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": slot},
        {"tradingDate": 1})
    dates = sorted({str(f.get("tradingDate")) for f in frames
                    if str(f.get("tradingDate") or "") and str(f.get("tradingDate")) < date})
    if not dates:
        return None, None
    prev = dates[-1]
    frame = _slot_frame(db, prev, dataset_id, slot)
    if not frame:
        return prev, None
    doc = db["snapshot_analysis"].find_one(
        {"datasetId": dataset_id, "snapshotId": str(frame.get("snapshotId") or ""), "code": code},
        {"analysis.observation.lifecycle.stage": 1})
    stage = (((doc or {}).get("analysis") or {}).get("observation") or {}).get("lifecycle") or {}
    return prev, stage.get("stage")


# ── 人口构建（纯取数+预检；无调用）──

def build_vote_population(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                      slot: str = PILOT_SLOT, include_neutral: bool = False) -> dict:
    """题集 A 人口。返回 {"buy","sell","insufficient","meta"}；
    候选={code,name,synergyTier,synergyDirection,dims,resonanceScore,riskFlag,row,trajectory}。"""
    frame = _slot_frame(db, date, dataset_id, slot)
    if not frame:
        return {"buy": [], "sell": [], "insufficient": [], "meta": {"error": "no_frame", "tradingDate": date}}
    sid = str(frame.get("snapshotId") or "")
    rows = list(db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": sid}))
    row_by_code = {str(r.get("code")): r for r in rows}
    sparse = _frame_sparse_fields(rows)
    slot_rows = _day_rows_by_slot(db, date, dataset_id)
    multi_day = _multi_day_rows_by_day(db, date, dataset_id, slot)
    buy: list[dict] = []
    sell: list[dict] = []
    neutral: list[dict] = []
    insufficient: list[dict] = []
    for doc in db["snapshot_analysis"].find({"datasetId": dataset_id, "snapshotId": sid}):
        code = str(doc.get("code") or "")
        a = doc.get("analysis") or {}
        obs = a.get("observation") or {}
        syn_tier = (obs.get("synergy") or {}).get("signalTier")
        if syn_tier not in ("S", "A", "B", "D"):
            if not (include_neutral and syn_tier in ("C", "E")):
                continue  # 人口外（C 无方向/E 环境门否决——生产全量覆盖传 include_neutral；
                # E 档五修纳入：jev 判据环境门只注记不投票，方向读数独立成立，
                # 「周期否决 × 方向偏多」= 观察否决是否误杀的样本（用户裁决 2026-10-12））
        res = a.get("resonance") or {}
        rt = obs.get("rankTrend") or {}
        cs = obs.get("crossSection") or {}
        vp = obs.get("volumePrice") or {}
        dims = {"resonance": res.get("signalTier"), "rankTrend": rt.get("signalTier"),
                "crossSection": cs.get("signalTier"), "volumePrice": vp.get("signalTier")}
        row = row_by_code.get(code) or {}
        # 帧级稀疏字段不算个股证据缺口（EOD 补齐读法口径，叙事统一注记）；个股零星缺算缺口
        missing_ev = [f"evidence_missing:{f}" for f in _EVIDENCE_FIELDS
                      if row.get(f) is None and f not in sparse]
        rf = vote_risk_flag(dims, missing_ev)
        tech = a.get("technical") or {}
        cand = {"code": code, "name": row.get("name"), "synergyTier": syn_tier,
                "synergyDirection": synergy_direction(syn_tier), "dims": dims,
                "resonanceScore": res.get("score"), "riskFlag": rf, "row": row,
                "resonance": res, "trend": rt, "crossSection": cs, "volumePrice": vp,
                "trendEvents": {"macdCross": (tech.get("macd") or {}).get("cross"),
                                "maCross": (tech.get("maCross") or {}).get("cross")},
                "gate": {"stage": (obs.get("lifecycle") or {}).get("stage"),
                         "veto": (obs.get("lifecycle") or {}).get("veto")},
                "trajectory": _trajectory(slot_rows, code),
                "multiDayTrajectory": _trajectory(multi_day, code, label="date")}
        if rf["level"] == "data_insufficient":
            insufficient.append(cand)
        elif syn_tier in ("S", "A", "B"):
            buy.append(cand)
        elif syn_tier == "D":
            sell.append(cand)
        else:
            neutral.append(cand)  # C 档（include_neutral 生产全量口径；无方向也全量判读）
    meta = {"tradingDate": date, "snapshotId": sid, "sparse_fields": sparse,
            "population_n": len(buy) + len(sell) + len(neutral) + len(insufficient)}
    return {"buy": buy, "sell": sell, "neutral": neutral,
            "insufficient": insufficient, "meta": meta}


def build_lifecycle_population(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                             slot: str = PILOT_SLOT,
                             include_cooling: bool = False) -> dict:
    """题集 B 人口（非 cooling）。候选含叙事原料；data_insufficient 萡 insufficient。"""
    frame = _slot_frame(db, date, dataset_id, slot)
    if not frame:
        return {"candidates": [], "insufficient": [], "meta": {"error": "no_frame", "tradingDate": date}}
    sid = str(frame.get("snapshotId") or "")
    row_by_code = {str(r.get("code")): r
                   for r in db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": sid})}
    slot_rows = _day_rows_by_slot(db, date, dataset_id)
    multi_day = _multi_day_rows_by_day(db, date, dataset_id, slot)
    candidates: list[dict] = []
    insufficient: list[dict] = []
    for doc in db["snapshot_analysis"].find({"datasetId": dataset_id, "snapshotId": sid}):
        code = str(doc.get("code") or "")
        a = doc.get("analysis") or {}
        obs = a.get("observation") or {}
        lc = obs.get("lifecycle") or {}
        stage = lc.get("stage")
        if not stage:
            continue
        if stage == "cooling" and not include_cooling:
            continue  # pilot 口径：默认态低信息量不进（§三·一）；生产全量覆盖传 include_cooling=True
        cyc = a.get("cycle") or {}
        metrics = cyc.get("metrics") or {}
        evidence = (cyc.get("decision") or {}).get("evidence") or {}
        traj = _trajectory(slot_rows, code)
        computable = sum(1 for t in traj if t.get("rank") is not None or t.get("change") is not None)
        missing: list[str] = []
        prev_date, prev_stage = _prev_day_stage(db, date, dataset_id, code, slot)
        if prev_stage is None:
            missing.append("prev_stage_missing")
        if not metrics:
            missing.append("cycle_metrics_missing")
        rf = lifecycle_risk_flag(computable, bool(metrics), missing)
        cand = {"code": code, "name": (row_by_code.get(code) or {}).get("name"), "stage": stage,
                "riskFlag": rf, "trajectory": traj,
                "multiDayTrajectory": _trajectory(multi_day, code, label="date"),
                "metrics": metrics, "evidence": evidence,
                "prevDate": prev_date, "prevStage": prev_stage,
                "action": (cyc.get("decision") or {}).get("action"),
                "confidence": cyc.get("confidence"),
                "reasons": (cyc.get("decision") or {}).get("reasons")}
        if rf["level"] == "data_insufficient":
            insufficient.append(cand)
        else:
            candidates.append(cand)
    meta = {"tradingDate": date, "snapshotId": sid,
            "population_n": len(candidates) + len(insufficient)}
    return {"candidates": candidates, "insufficient": insufficient, "meta": meta}


# ── 留痕文档（data_insufficient：不调用，落 riskFlag 留痕，预登记 §二·四/§三·四）──

def _insufficient_doc(kind: str, date: str, code: str, name: Any, rf: dict,
                      question_set_version: str, qhash: str, slot: str = PILOT_SLOT) -> dict:
    return {"_id": f"{date}:{slot}:{code}:{kind}", "origin": f"{kind}_pilot",
            "tradingDate": date, "slotTime": slot, "code": code, "name": name,
            "ammoVersion": VOTE_AMMO_VERSION, "questionSetVersion": question_set_version,
            "questionSetHash": qhash, "riskFlag": rf, "status": "data_insufficient",
            "answers": None, "responseRaw": None, "usage": None, "latencyMs": None,
            "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ── 双题集运行 ──

def run_vote_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                 fire: bool = False, cap_buy: int = 8, cap_sell: int = 4,
                 workers: int = 1, token_fuse: int | None = None,
                 slot: str = PILOT_SLOT, include_neutral: bool = False) -> dict:
    """题集 A：方向投票二次确认。落 hotlist_jev_vote_confirm_pilot（_id={date}:15:00:{code}:VOTE）。
    cap_buy/cap_sell 默认=预登记 §六 冻结帽；扩窗修正案（§十一）经 CLI 传参覆盖。
    workers>1=并发（生产回填 §六·产）；token_fuse 缺省=TOKEN_FUSE(150k)，回填显式放宽。"""
    col = db["hotlist_jev_vote_confirm_pilot"]
    questions = QUESTIONS_VOTE_CONFIRM
    qhash = _questions_hash(questions)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        pop = build_vote_population(db, date, dataset_id, slot,
                                    include_neutral=include_neutral)
        if pop["meta"].get("error"):
            stats["no_frame"] += 1
            print(f"[vote] {date} 无 half_hour {slot} 帧，跳过")
            continue
        sparse = pop["meta"]["sparse_fields"]
        print(f"[vote] {date} 人口 buy={len(pop['buy'])} sell={len(pop['sell'])} "
              f"预检不足={len(pop['insufficient'])} 帧级稀疏字段={sparse or '无'}")
        if fire:
            for c in pop["insufficient"]:
                col.replace_one({"_id": f"{date}:{slot}:{c['code']}:VOTE"},
                                _insufficient_doc("VOTE", date, c["code"], c["name"],
                                                  c["riskFlag"], QUESTION_SET_VERSION_VOTE_CONFIRM, qhash, slot),
                                upsert=True)
                stats["data_insufficient"] += 1
        sample = sample_vote(pop["buy"], pop["sell"], cap_buy=cap_buy, cap_sell=cap_sell)
        if pop.get("neutral"):
            sample = sample + pop["neutral"]  # C 档全量判读（无帽，生产覆盖口径）

        def _work_vote(c: dict) -> tuple[str, dict, int]:
            """单股一次 jev 调用+落库（pymongo replace_one 线程安全）；返回 (code, doc, tokens)。"""
            _id = f"{date}:{slot}:{c['code']}:VOTE"
            row = c["row"]
            # EOD 补齐读法挂载点（pilot 主口径 15:00 单帧：sparse 通常为空，函数为 EOD 视角预留）
            row, _, _ = backfill_quote_fields(row, None, sparse)
            narrative = build_vote_narrative(
                trading_date=date, slot=slot, code=c["code"], name=c["name"],
                resonance=c["resonance"], trend=c["trend"], cross_section=c["crossSection"],
                volume_price=c["volumePrice"], trend_events=c["trendEvents"], row=row,
                sparse_fields=sparse, trajectory=c["trajectory"],
                multi_day_trajectory=c.get("multiDayTrajectory"),
                gate=c["gate"], synergy_tier=c["synergyTier"])
            env, ms = _dispatch_jev(narrative, questions)
            parsed = parse_jev_response(env, ms, expected_keys=set(questions))
            used = _usage_tokens(parsed.get("usage"))
            ans = (parsed.get("answers") or {}).get("vote_direction") or {}
            doc = {"_id": _id, "origin": "vote_confirm_pilot", "tradingDate": date,
                   "slotTime": slot, "code": c["code"], "name": c["name"],
                   "ammoVersion": VOTE_AMMO_VERSION,
                   "questionSetVersion": QUESTION_SET_VERSION_VOTE_CONFIRM,
                   "questionSetHash": qhash, "riskFlag": c["riskFlag"],
                   "synergyTier": c["synergyTier"], "synergyDirection": c["synergyDirection"],
                   "status": "ok" if parsed["ok"] else "degraded",
                   "narrative": narrative, "questionsRaw": questions,
                   "answers": parsed.get("answers"),
                   "voteDirection": ans.get("choice"), "voteConfidence": ans.get("confidence"),
                   "voteProbabilities": ans.get("probabilities"),
                   "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "responseRaw": env,  # §八：ok/degraded 一律存完整 envelope
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            col.replace_one({"_id": _id}, doc, upsert=True)
            return c["code"], doc, used

        todo = []
        for c in sample:
            _id = f"{date}:{slot}:{c['code']}:VOTE"
            if col.find_one({"_id": _id, "status": "ok"}):
                stats["skip"] += 1
                continue
            todo.append(c)
        if not fire:
            for c in todo:
                print(f"[vote] dry-run {date}:{c['code']}:{slot}:VOTE "
                      f"riskFlag={c['riskFlag']['level']}")
            continue
        if workers > 1:
            # 并发路径（生产回填）：日粒度熔断预检，单日任务整体提交
            if todo and tokens >= fuse:
                print(f"[vote] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                break
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_work_vote, todo))
            for code, doc, used in results:
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[vote] {date} {code} → {doc['voteDirection']} "
                      f"conf={doc['voteConfidence']} tokens={used}(cum={tokens})")
        else:
            for c in todo:
                if tokens >= fuse:
                    print(f"[vote] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    break
                code, doc, used = _work_vote(c)
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[vote] {date} {code} → {doc['voteDirection']} "
                      f"conf={doc['voteConfidence']} tokens={used}(cum={tokens})")
    stats["tokens"] = tokens
    print("FINAL[vote]:", stats)
    return stats


def run_lifecycle_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                      fire: bool = False, cap_igex: int = 5, cap_total: int = 8,
                      workers: int = 1, token_fuse: int | None = None,
                      slot: str = PILOT_SLOT, include_cooling: bool = False) -> dict:
    """题集 B：环境门阶段诊断复核。落 hotlist_jev_lifecycle_recheck_pilot。
    cap_igex/cap_total 默认=预登记 §六 冻结帽；扩窗修正案（§十一）经 CLI 传参覆盖。
    workers>1=并发（生产回填 §六·产）；token_fuse 缺省=TOKEN_FUSE(150k)，回填显式放宽。"""
    col = db["hotlist_jev_lifecycle_recheck_pilot"]
    questions = QUESTIONS_LIFECYCLE_RECHECK
    qhash = _questions_hash(questions)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        pop = build_lifecycle_population(db, date, dataset_id, slot,
                                         include_cooling=include_cooling)
        if pop["meta"].get("error"):
            stats["no_frame"] += 1
            print(f"[lifecycle] {date} 无 half_hour {slot} 帧，跳过")
            continue
        print(f"[lifecycle] {date} 人口={len(pop['candidates'])} 预检不足={len(pop['insufficient'])}")
        if fire:
            for c in pop["insufficient"]:
                col.replace_one({"_id": f"{date}:{slot}:{c['code']}:LC"},
                                _insufficient_doc("LC", date, c["code"], c["name"],
                                                  c["riskFlag"], QUESTION_SET_VERSION_LIFECYCLE_RECHECK, qhash, slot),
                                upsert=True)
                stats["data_insufficient"] += 1
        sample = sample_lifecycle(pop["candidates"], cap_igex=cap_igex, cap_total=cap_total)

        def _work_lc(c: dict) -> tuple[str, dict, int]:
            """单股一次 jev 调用+落库；返回 (code, doc, tokens)。"""
            _id = f"{date}:{slot}:{c['code']}:LC"
            prev_line = (f"{c['prevDate']} 阶段={STAGE_ZH.get(str(c['prevStage']), c['prevStage'])}"
                         if c["prevStage"] else
                         f"{c['prevDate'] or '无更早帧'} 前一交易日阶段：数据缺口（fail-visible）")
            narrative = build_lifecycle_narrative(
                trading_date=date, slot=slot, code=c["code"], name=c["name"],
                trajectory=c["trajectory"],
                multi_day_trajectory=c.get("multiDayTrajectory"),
                metrics=c["metrics"], evidence=c["evidence"],
                prev_stage_line=prev_line, stage=c["stage"], action=c["action"],
                confidence=c["confidence"], reasons=c["reasons"])
            env, ms = _dispatch_jev(narrative, questions)
            parsed = parse_jev_response(env, ms, expected_keys=set(questions))
            used = _usage_tokens(parsed.get("usage"))
            ans = (parsed.get("answers") or {}).get("lifecycle_stage_recheck") or {}
            doc = {"_id": _id, "origin": "lifecycle_recheck_pilot", "tradingDate": date,
                   "slotTime": slot, "code": c["code"], "name": c["name"],
                   "ammoVersion": VOTE_AMMO_VERSION,
                   "questionSetVersion": QUESTION_SET_VERSION_LIFECYCLE_RECHECK,
                   "questionSetHash": qhash, "riskFlag": c["riskFlag"],
                   "ruleStage": c["stage"], "ruleAction": c["action"],
                   "prevTradingDate": c["prevDate"], "prevStage": c["prevStage"],
                   "status": "ok" if parsed["ok"] else "degraded",
                   "narrative": narrative, "questionsRaw": questions,
                   "answers": parsed.get("answers"),
                   "lcStage": ans.get("choice"), "lcConfidence": ans.get("confidence"),
                   "lcProbabilities": ans.get("probabilities"),
                   "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "responseRaw": env,  # §八：ok/degraded 一律存完整 envelope
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            col.replace_one({"_id": _id}, doc, upsert=True)
            return c["code"], doc, used

        todo = []
        for c in sample:
            _id = f"{date}:{slot}:{c['code']}:LC"
            if col.find_one({"_id": _id, "status": "ok"}):
                stats["skip"] += 1
                continue
            todo.append(c)
        if not fire:
            for c in todo:
                print(f"[lifecycle] dry-run {date}:{c['code']}:{slot}:LC "
                      f"riskFlag={c['riskFlag']['level']}")
            continue
        if workers > 1:
            if todo and tokens >= fuse:
                print(f"[lifecycle] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                break
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_work_lc, todo))
            for code, doc, used in results:
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[lifecycle] {date} {code} → {doc['lcStage']} "
                      f"conf={doc['lcConfidence']} tokens={used}(cum={tokens})")
        else:
            for c in todo:
                if tokens >= fuse:
                    print(f"[lifecycle] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    break
                code, doc, used = _work_lc(c)
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[lifecycle] {date} {code} → {doc['lcStage']} "
                      f"conf={doc['lcConfidence']} tokens={used}(cum={tokens})")
    stats["tokens"] = tokens
    print("FINAL[lifecycle]:", stats)
    return stats


# ── watch 常驻轮询（用户裁决 2026-10-12 二修：每日两帧=上午收盘 11:30 + 下午收盘 15:00，
# 不做每帧跑；只跑 15:00 一帧也不对——上午收盘定格判读同样留档）──

WATCH_SLOTS = ("11:30", "15:00")


def _due_slot(now: "time.struct_time|None" = None, grace: int = 120) -> str | None:
    """最近一个「已结束满 grace 秒」的 watch 槽（仅 11:30/15:00）；非交易时段 → None。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    cur = now.hour * 60 + now.minute
    due = None
    for s in WATCH_SLOTS:
        h, m = int(s[:2]), int(s[3:])
        if cur * 60 + now.second >= h * 3600 + m * 60 + grace:
            due = s
    return due


def _frame_mark_done(db, col_name: str, date: str, slot: str, kind: str) -> bool:
    """帧级运行标记：已跑过（ok 标记在）→ True，跳过；零成本幂等防重。"""
    return db[col_name].find_one({"_id": f"{date}:{slot}:MARK:{kind}"}) is not None


def _write_frame_mark(db, col_name: str, date: str, slot: str, kind: str,
                      stats: dict) -> None:
    db[col_name].replace_one(
        {"_id": f"{date}:{slot}:MARK:{kind}"},
        {"_id": f"{date}:{slot}:MARK:{kind}", "origin": "frame_run_marker",
         "status": "run_marker", "tradingDate": date, "slotTime": slot,
         "stats": {k: v for k, v in stats.items() if k != "tokens"},
         "tokens": stats.get("tokens"),
         "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, upsert=True)


def watch(db, dataset_id: str = DEFAULT_DATASET_ID, interval: int = 60,
          workers: int = 1, token_fuse: int | None = None,
          include_cooling: bool = False, include_neutral: bool = False) -> None:
    """常驻轮询：每 interval 秒检查最近已落库 half_hour 槽，未跑过则全量判读该帧（A+B）。

    - 幂等：帧级标记防重；进程重启无损（状态全在库内）；
    - fail-visible：帧未落库（采集延迟/非交易日）→ no_frame 零成本跳过，下轮再试；
    - 不碰 snapshot_collector 采集进程（jev 外呼不进采集链，失败绝不阻断采集）。
    """
    print(f"[watch] 启动：interval={interval}s workers={workers} "
          f"fuse={token_fuse or TOKEN_FUSE}（Ctrl+C 停止，重启无损）")
    while True:
        slot = _due_slot()
        if slot:
            date = time.strftime("%Y-%m-%d")
            for col_name, kind, runner_fn, kwargs in (
                    ("hotlist_jev_vote_confirm_pilot", "VOTE", run_vote_day,
                     {"cap_buy": 200, "cap_sell": 200, "include_neutral": include_neutral}),
                    ("hotlist_jev_lifecycle_recheck_pilot", "LC", run_lifecycle_day,
                     {"cap_igex": 100, "cap_total": 200})):
                try:
                    if _frame_mark_done(db, col_name, date, slot, kind):
                        continue
                    print(f"[watch] {date} {slot} 帧 → 题{'A' if kind == 'VOTE' else 'B'} 判读...")
                    stats = runner_fn(db, [date], dataset_id, fire=True,
                                      workers=workers, token_fuse=token_fuse,
                                      slot=slot, include_cooling=include_cooling,
                                      **kwargs)
                    _write_frame_mark(db, col_name, date, slot, kind, stats)
                except Exception as e:  # fail-visible：单帧失败不炸常驻，下轮重试（幂等）
                    print(f"[watch] {date} {slot} {kind} 异常：{type(e).__name__}: {str(e)[:150]}（下轮重试）")
        time.sleep(interval)


def __main__():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vote-day", dest="vote_day", action="append", default=[],
                    help="题集 A：指定交易日跑方向投票二次确认（可多次传参）")
    ap.add_argument("--lifecycle-day", dest="lifecycle_day", action="append", default=[],
                    help="题集 B：指定交易日跑生命周期阶段诊断复核（可多次传参）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    ap.add_argument("--fire", action="store_true",
                    help="真实调用 jev（只走预登记+用户批准开火路径；默认 dry-run 零调用）")
    ap.add_argument("--vote-cap-buy", dest="vote_cap_buy", type=int, default=8)
    ap.add_argument("--vote-cap-sell", dest="vote_cap_sell", type=int, default=4)
    ap.add_argument("--lc-cap-igex", dest="lc_cap_igex", type=int, default=5)
    ap.add_argument("--lc-cap-total", dest="lc_cap_total", type=int, default=8)
    ap.add_argument("--workers", type=int, default=1,
                    help="并发数（默认 1 串行；生产回填建议 4，jiuyan 先例默认 2）")
    ap.add_argument("--token-fuse", dest="token_fuse", type=int, default=None,
                    help="本次运行熔断线（缺省=150k；全量回填显式放宽，预登记 §六·产）")
    ap.add_argument("--slot", dest="slot", default=PILOT_SLOT,
                    help="帧级口径（用户裁决 2026-10-12：每帧落库后即跑；默认 15:00 保持回填兼容）")
    ap.add_argument("--watch", action="store_true",
                    help="常驻轮询模式：每个 half_hour 槽落库后自动全量判读该帧（幂等标记防重；"
                         "不碰采集进程，帧未落库则 no_frame 零成本跳过）")
    ap.add_argument("--watch-interval", dest="watch_interval", type=int, default=60,
                    help="watch 轮询间隔秒（默认 60）")
    ap.add_argument("--include-cooling", dest="include_cooling", action="store_true",
                    help="B 题集人口含 cooling 股（生产全量覆盖，用户裁决 2026-10-12："
                         "行情列表每只股都要有周期判读；缺省=非 cooling pilot 口径）")
    ap.add_argument("--include-neutral", dest="include_neutral", action="store_true",
                    help="A 题集人口含 synergy C 档（无方向票也全量判读，生产全量覆盖；"
                         "缺省=pilot 口径）")
    args = ap.parse_args()
    if not args.vote_day and not args.lifecycle_day:
        raise SystemExit("需要 --vote-day 或 --lifecycle-day（可多次传参）")
    if args.fire and not ((os.environ.get("JEV_CF_TOKEN") or "").strip()
                          or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip()):
        raise SystemExit("--fire 需要环境变量 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    if args.watch:
        watch(db, dataset_id=args.dataset_id, interval=args.watch_interval,
              workers=args.workers, token_fuse=args.token_fuse,
              include_cooling=args.include_cooling, include_neutral=args.include_neutral)
        return
    if args.vote_day:
        run_vote_day(db, args.vote_day, args.dataset_id, fire=args.fire,
                     cap_buy=args.vote_cap_buy, cap_sell=args.vote_cap_sell,
                     workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                     include_neutral=args.include_neutral)
    if args.lifecycle_day:
        run_lifecycle_day(db, args.lifecycle_day, args.dataset_id, fire=args.fire,
                          cap_igex=args.lc_cap_igex, cap_total=args.lc_cap_total,
                          workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                          include_cooling=args.include_cooling)


if __name__ == "__main__":
    __main__()
