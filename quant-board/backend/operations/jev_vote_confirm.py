# -*- coding: utf-8 -*-
"""行情列表五维信号 jev 复核双题集 runner（vote_confirm + lifecycle_recheck pilot）。

预登记（唯一合同）：docs/hotlist-jev/jev-vote-confirm-lifecycle-recheck-preregistration.md。
取数：snapshot_frames + snapshot_stock_rows + snapshot_analysis（与规则链/情绪链同源 join，
正式快照读口合同不变，本 runner 只读不写快照集合）。

口径（预登记冻结）：
- 槽位 = half_hour 15:00（当日收盘槽；daily 15:30 帧行情字段实测稀疏不可用）；
- 人口：A=全热榜池（v4-material 代，判读时点=11:00 槽帧）；B=全量（生产挂链传
  --include-cooling；缺省=非 cooling pilot 口径，历史对照台账不混代）；
- 预检 riskFlag（runner 侧）：data_insufficient 不调用落留痕文档；partial/ok 进判读；
- **无抽样帽**（2026-10-14 用户裁决「帽子盖的是自己的眼睛，毫无实际意义」：A/B 抽样上限
  全部取消，判读人口=候选全量；v4 代起 A 本就无帽，本次把 B 的 cap_igex/cap_total 一并拆除，
  pilot/扩窗期的抽样语义随预登记 §六/§十一 留档 git 历史，不再进生产链）；
- 熔断：TOKEN_FUSE=150_000 tokens/次运行，逐 call 累计，达限即停（预登记 §六）；
- 落库（预登记 §八）：answers 原样包 + confidence 升顶层 + responseRaw ok/degraded 一律
  存完整 envelope（修 cycle pilot「ok 存 None」口子）。

默认 dry-run（零 jev 调用：打印人口/预检/叙事字数）；--fire 且有 token 才真实调用
（开火只走预登记 + 用户批准路径，AGENTS §1.2-7）。
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, _questions_hash, _usage_tokens
from backend.analysis.hotlist.market_facts import (
    FACTS_VERSION,
    fold_attention_series,
    frame_market_facts,
    swing_anchor,
)
from backend.analysis.hotlist.jev_vote_ammo import (
    BACKFILL_FIELDS,
    QUESTION_SET_VERSION_LIFECYCLE_RECHECK,
    QUESTION_SET_VERSION_VOTE_CONFIRM,
    QUESTIONS_LIFECYCLE_RECHECK,
    QUESTIONS_VOTE_CONFIRM,
    STAGE_ZH,
    VOTE_AMMO_VERSION,
    build_lifecycle_narrative,
    lifecycle_risk_flag,
    synergy_direction,
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


# ── 方向题集 v4-material：八块原料组装编排（题集代际 2026-10-13，原 v1 复核内核退役） ──

DIRECTION_SLOT = "11:00"
HOT_ZONE = 80
SERIES_MAIN_MIN_DAYS = 5  # 序列证据作为主证据的最小历史深度（用户裁决 2026-10-13）
SERIES_WINDOW_DAYS = 10

BLACKLIST_FIELDS = (
    "compScore", "compRank", "leadStatus", "themeRole", "avgRankNum",
    "finalSignal", "synergy", "voteDirection", "relayPhase", "cycleStage",
    "driverType", "catalystDepth", "phaseBand", "crowding", "temperature",
)


def run_vote_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                 fire: bool = False, workers: int = 1,
                 token_fuse: int | None = None,
                 only_codes: list[str] | None = None) -> dict:
    """方向判读（题集 v4-material 代际，2026-10-13 用户裁决覆盖 v1 复核内核）。

    - 原料=八块叙事（market_facts 单一源：序列折叠/位置+板序/量价+板型/市场 as-of 11:00/
      摆动锚/题材/质量自标/门）；人口=全热榜池（判读帧全部在榜股）；
    - 判读时点=11:00 槽帧（计分口径冻结：判读=11:00、验证=隔日涨幅、hold |≥5%| 算错）；
      as-of 组装无未来函数，调度在 15:30 after_market 步跑判读的仍是 11:00 时点原料；
    - 存档 hotlist_jev_vote_confirm_pilot（_id={date}:11:00:{code}:VOTE），字段 VOTE 兼容
      （voteDirection/voteConfidence/narrative/questionsRaw/responseRaw），前端零改动；
    - workers>1=并发；token_fuse 逐 call 累计熔断；done-skip 幂等（status=ok 跳过）。
    """
    col = db["hotlist_jev_vote_confirm_pilot"]
    questions = QUESTIONS_VOTE_CONFIRM
    qhash = _questions_hash(questions)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    tokens = 0
    stats = {"ok": 0, "degraded": 0, "skip": 0, "data_insufficient": 0, "no_frame": 0}
    for date in dates:
        try:
            ctx = setup_day(db, date, dataset_id)
        except LookupError as exc:
            stats["no_frame"] += 1
            print(f"[vote] {date} {exc}")
            continue
        codes, pop_stats = build_population(db, date, ctx, dataset_id)
        rule_map = _rule_direction_map(db, date, dataset_id)
        print(f"[vote] {date} 全池人口={len(codes)} 主力缺失计数="
              f"{pop_stats['mainforce_missing_counted']} 规则线档位覆盖={len(rule_map)}")

        def _work_vote(code: str) -> tuple[str, dict, int]:
            """单股：v4 八块叙事 → jev 调用 → VOTE 兼容存档（pymongo replace_one 线程安全）。"""
            name = (ctx["cur"].get(code) or {}).get("name")
            head, blocks, meta = build_state_v4(db, code, date, ctx, dataset_id)
            narrative = "\n".join([head, *[ln for b in blocks.values() for ln in b]])
            _id = f"{date}:{DIRECTION_SLOT}:{code}:VOTE"
            env, ms = _dispatch_jev(narrative, questions)
            parsed = parse_jev_response(env, ms, expected_keys=set(questions))
            used = _usage_tokens(parsed.get("usage"))
            ans = (parsed.get("answers") or {}).get("direction") or {}
            tier, rule_dir = rule_map.get(str(code), (None, ""))
            doc = {"_id": _id, "origin": "vote_confirm_pilot", "tradingDate": date,
                   "slotTime": DIRECTION_SLOT, "code": code, "name": name,
                   "ammoVersion": VOTE_AMMO_VERSION,
                   "questionSetVersion": QUESTION_SET_VERSION_VOTE_CONFIRM,
                   "questionSetHash": qhash,
                   "riskFlag": None,  # v4 质量自标（meta.seenDays/missingFields）替代预检 riskFlag
                   "synergyTier": tier, "synergyDirection": rule_dir,
                   "status": "ok" if parsed["ok"] else "degraded",
                   "narrative": narrative, "questionsRaw": questions,
                   "answers": parsed.get("answers"),
                   "voteDirection": ans.get("choice"), "voteConfidence": ans.get("confidence"),
                   "voteProbabilities": ans.get("probabilities"),
                   "seenDays": meta.get("seenDays"), "firstSeen": meta.get("firstSeen"),
                   "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "responseRaw": env,  # §八：ok/degraded 一律存完整 envelope
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            col.replace_one({"_id": _id}, doc, upsert=True)
            return code, doc, used

        allowed = set(only_codes) if only_codes else None
        todo = []
        for code in codes:
            if allowed is not None and code not in allowed:
                continue
            _id = f"{date}:{DIRECTION_SLOT}:{code}:VOTE"
            if col.find_one({"_id": _id, "status": "ok"}):
                stats["skip"] += 1
                continue
            todo.append(code)
        if not fire:
            for code in todo[:20]:
                print(f"[vote] dry-run {date}:{code}:{DIRECTION_SLOT}:VOTE")
            print(f"[vote] dry-run 待判 {len(todo)} 例（全池口径）")
            continue
        if todo and tokens >= fuse:
            print(f"[vote] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
            continue
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(_work_vote, todo))
            for code, doc, used in results:
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[vote] {date} {code} → {doc['voteDirection']} "
                      f"conf={doc['voteConfidence']} tokens={used}(cum={tokens})")
        else:
            for code in todo:
                if tokens >= fuse:
                    print(f"[vote] 熔断：累计 {tokens} ≥ fuse={fuse}，停止后续调用")
                    break
                code, doc, used = _work_vote(code)
                tokens += used
                stats["ok" if doc["status"] == "ok" else "degraded"] += 1
                print(f"[vote] {date} {code} → {doc['voteDirection']} "
                      f"conf={doc['voteConfidence']} tokens={used}(cum={tokens})")
    stats["tokens"] = tokens
    print("FINAL[vote]:", stats)
    return stats


def _rule_direction_map(db: Any, date: str, dataset_id: str) -> dict[str, tuple]:
    """规则线对照 map（同股同场）：当日 15:00 快照引擎 synergy 档 → (tier, direction)。

    仅作对照列（synergyTier/synergyDirection 字段 + 前端 agree 对照），非判读依赖；
    15:00 分析产物未落库时返回空 map（对照缺失如实降级，不阻断判读）。
    """
    frame15 = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour",
         "tradingDate": date, "slotTime": "15:00"}, {"snapshotId": 1})
    out: dict[str, tuple] = {}
    if not frame15:
        return out
    for a in db["snapshot_analysis"].find(
            {"datasetId": dataset_id, "snapshotId": str(frame15["snapshotId"])},
            {"code": 1, "analysis.observation.synergy.signalTier": 1}):
        syn = ((a.get("analysis") or {}).get("observation") or {}).get("synergy") or {}
        tier = syn.get("signalTier")
        d8 = synergy_direction(tier)
        if d8:
            out[str(a.get("code"))] = (tier, d8)
    return out


def run_lifecycle_day(db, dates: list[str], dataset_id: str = DEFAULT_DATASET_ID,
                      fire: bool = False, workers: int = 1, token_fuse: int | None = None,
                      slot: str = PILOT_SLOT, include_cooling: bool = False) -> dict:
    """题集 B：环境门阶段诊断复核。落 hotlist_jev_lifecycle_recheck_pilot。
    无抽样帽（2026-10-14 用户裁决取消）：人口=候选全量，逐股判读；done-skip 幂等。
    workers>1=并发；token_fuse 缺省=TOKEN_FUSE(150k)，全量回填显式放宽。"""
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
        candidates = pop["candidates"]  # 无抽样帽：候选全量进判读（2026-10-14 用户裁决）

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
        for c in candidates:
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


# ── 方向题集 v4-material：八块原料组装编排（题集代际 2026-10-13，原 v1 复核内核退役） ──

DIRECTION_SLOT = "11:00"
HOT_ZONE = 80
SERIES_MAIN_MIN_DAYS = 5  # 序列证据作为主证据的最小历史深度（用户裁决 2026-10-13）
SERIES_WINDOW_DAYS = 10

BLACKLIST_FIELDS = (
    "compScore", "compRank", "leadStatus", "themeRole", "avgRankNum",
    "finalSignal", "synergy", "voteDirection", "relayPhase", "cycleStage",
    "driverType", "catalystDepth", "phaseBand", "crowding", "temperature",
)


def _v4_slot_frame(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": slot},
        sort=[("timestamp", -1)])


def _frame_rows(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, dict]:
    f = _v4_slot_frame(db, date, slot, dataset_id)
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
          include_cooling: bool = False) -> None:
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
                    ("hotlist_jev_vote_confirm_pilot", "VOTE", run_vote_day, {}),
                    ("hotlist_jev_lifecycle_recheck_pilot", "LC", run_lifecycle_day,
                     {})):
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
    ap.add_argument("--codes", dest="codes", default="",
                    help="逗号分隔 code 子集（单股判读；缺省=全池）")
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
              include_cooling=args.include_cooling)
        return
    if args.vote_day:
        only = [c.strip() for c in args.codes.split(",") if c.strip()] or None
        run_vote_day(db, args.vote_day, args.dataset_id, fire=args.fire,
                     workers=args.workers, token_fuse=args.token_fuse, only_codes=only)
    if args.lifecycle_day:
        run_lifecycle_day(db, args.lifecycle_day, args.dataset_id, fire=args.fire,
                          workers=args.workers, token_fuse=args.token_fuse, slot=args.slot,
                          include_cooling=args.include_cooling)


if __name__ == "__main__":
    __main__()
