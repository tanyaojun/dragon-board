# -*- coding: utf-8 -*-
"""热榜行情读口聚合（行情列表五维信号 jev 复核台账，2026-10-12 预登记批次的展示侧）。

预登记唯一来源：docs/hotlist-jev/jev-vote-confirm-lifecycle-recheck-preregistration.md。
数据源（全部只读，零 jev 调用零写入）：
- snapshot_frames：当日 half_hour 帧（默认选帧顺序见 collect_quotes_review，可传 slot_time 固定）；
- snapshot_stock_rows / snapshot_analysis：帧内行情行 + 逐股五维 analysis（与规则链同源）；
- hotlist_jev_vote_confirm_pilot / hotlist_jev_lifecycle_recheck_pilot：双题集复核文档。

fail-visible：目标帧缺失 → noData=true + 结构化 reason；行情/档位/复核文档逐字段缺失
如实 None，不伪造 0 值。jev 与规则投票引擎=并列观察者：agree/diverge 台账仅对照展示
（jev_vote_ammo.synergy_direction 对照锚），不回写引擎、不进候选池、不进交易路径。
"""
from __future__ import annotations

import math
from typing import Any

from backend.analysis.hotlist.jev_vote_ammo import synergy_direction
from backend.operations.jev_label_jiuyan import jiuyan_consecutive_streaks

PILOT_SLOT = "15:00"  # 预登记 §四 冻结口径（与 operations/jev_vote_confirm.py 一致）

# with_docs=True 时原文档保留字段（含大字段；watch 模式每日两槽近全人口，体量可观，
# 前端固定 with_docs=1 的载荷成本由产品侧验收；字段面遵预登记 §八「全保留」）
_DOC_FIELDS = ("_id", "origin", "tradingDate", "slotTime", "code", "name",
               "status", "riskFlag", "synergyTier", "synergyDirection",
               "voteDirection", "voteConfidence", "voteProbabilities",
               "lcStage", "lcConfidence", "lcProbabilities",
               "ammoVersion", "ruleStage", "ruleAction", "prevTradingDate", "prevStage",
               "narrative", "questionsRaw", "answers", "responseRaw",
               "model", "usage", "latencyMs", "errorCode", "errorDetail",
               "questionSetVersion", "questionSetHash", "computedAt")


def _num(value: Any) -> float | None:
    """有限数值透传（bool/NaN/inf→None），缺失如实 None 不伪造 0。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _clean(value: Any) -> str | None:
    """枚举归一：引擎 unknown 字面值与缺失同价（展示层统一 '--'，排序/台账不计票）。"""
    text = str(value) if value else None
    return None if text in (None, "unknown") else text


def _tier(payload: Any) -> str | None:
    return _clean((payload or {}).get("signalTier"))


def _risk_level(doc: dict[str, Any] | None) -> str | None:
    level = ((doc or {}).get("riskFlag") or {}).get("level")
    return str(level) if level else None


def _doc_public(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return {k: doc.get(k) for k in _DOC_FIELDS}


def _vote_brief(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return {"status": doc.get("status"),
            "direction": _clean(doc.get("voteDirection")),
            "confidence": _num(doc.get("voteConfidence")),
            "riskLevel": _risk_level(doc)}


def _lc_brief(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return {"status": doc.get("status"),
            "stage": _clean(doc.get("lcStage")),
            "confidence": _num(doc.get("lcConfidence")),
            "riskLevel": _risk_level(doc)}


def collect_quotes_review(db: Any, date: str, dataset_id: str = "dragonboard_live",
                          with_docs: bool = False, slot_time: str | None = None) -> dict[str, Any]:
    """单日热榜行情 + 五维档位 + 双题集复核台账。

    选帧（slot_time 为空时）：15:00 收盘槽（PILOT_SLOT，冻结口径）→ 有 vote 判读的
    最新帧 → 当天最新帧；传 slot_time 时固定用该帧（帧不存在 → noData + 结构化
    reason），支撑前端按槽位切换查看。返回值另带 voteSlots（当日有 vote 判读的
    槽位升序）供前端重建帧选择器。

    vote 台账按 code 归并时用「决策时点优先级」：11:00（v4-material 代）> 15:00
    （v1 退役代）> 其他槽位；同优先级取 computedAt 最新、再取 _id 最小——不依赖
    游标顺序，重跑结果可复现。LC 台账仍锁 15:00 槽（跨槽拼接禁令不变）。

    with_docs=True（工作台行展开用）：有复核文档的股嵌入完整存档文档
    （narrative/questionsRaw/answers/responseRaw 原样，预登记 §八「全保留」）。
    """
    day_frames = list(db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date}
    ).sort("slotTime", 1))
    if not day_frames:
        return {"ok": True, "date": date, "slotTime": None, "datasetId": dataset_id,
                "snapshotId": None, "rows": [], "summary": _empty_summary(), "noData": True,
                "reason": f"{date} 无 half_hour 帧（非交易日或未采集）"}

    # 注意：这两个 pilot 集合的文档**不带 datasetId**（见 operations/jev_vote_confirm.py
    # 的 doc 组装：_id={date}:{slot}:{code}:{VOTE|LC}，无 datasetId 字段），与
    # hotlist_jev_relay_index 同属单数据集集合。故此处只能按 tradingDate 过滤——
    # 若按 snapshot_* 的习惯补一个 datasetId 条件，生产读口会一条都匹配不上，
    # 直接把整列复核台账静默变成空（有数据不展示，§4.0 明令禁止）。
    vote_slots = [s for s in db["hotlist_jev_vote_confirm_pilot"].distinct(
        "slotTime", {"tradingDate": date}) if s]
    vote_slot_set = set(vote_slots)
    if slot_time:
        frame = next((f for f in day_frames if f.get("slotTime") == slot_time), None)
        if not frame:
            return {"ok": True, "date": date, "slotTime": slot_time, "datasetId": dataset_id,
                    "snapshotId": None, "rows": [], "summary": _empty_summary(), "noData": True,
                    "reason": f"{date} 无 half_hour {slot_time} 帧"}
    else:
        frame = next((f for f in day_frames if f.get("slotTime") == PILOT_SLOT), None)
        if frame is None and vote_slots:
            for slot in sorted(vote_slots, reverse=True):
                frame = next((f for f in day_frames if f.get("slotTime") == slot), None)
                if frame:
                    break
        if frame is None:
            frame = day_frames[-1]

    slot_time = frame.get("slotTime")
    sid = str(frame.get("snapshotId") or "")
    stock_rows = list(db["snapshot_stock_rows"].find(
        {"datasetId": dataset_id, "snapshotId": sid}))
    if not stock_rows:
        return {"ok": True, "date": date, "slotTime": slot_time, "datasetId": dataset_id,
                "snapshotId": sid, "rows": [], "summary": _empty_summary(), "noData": True,
                "reason": f"{date} {slot_time} 帧存在但行集为空（snapshotId={sid}）"}

    analysis_by_code: dict[str, dict[str, Any]] = {}
    for doc in db["snapshot_analysis"].find({"datasetId": dataset_id, "snapshotId": sid}):
        code = str(doc.get("code") or "")
        if code:
            analysis_by_code[code] = doc.get("analysis") or {}
    # vote 台账：v4-material 代（2026-10-13 题集代际覆盖）判读时点=11:00（slotTime="11:00"），
    # v1 代（退役）=15:00——join 双槽兼容，同 code 两代并存时代际新（11:00）覆盖旧；
    # 读口返回 shape 零变化（前端合同不变）。LC 仍锁 15:00 槽（跨槽拼接禁令不变）。
    # 选取键只进本地 dict，不回写 doc（doc 会被 with_docs 原样透出，混入私有键有泄漏风险）；
    # 同优先级按 computedAt 降序（该集合存 ISO 串，可字典序比）再 _id 升序，
    # 彻底消除对游标顺序的依赖，重跑结果可复现。
    vote_by_code: dict[str, dict[str, Any]] = {}
    vote_rank: dict[str, tuple[str, str, str]] = {}

    def _vote_wins(candidate: tuple[str, str, str], current: tuple[str, str, str]) -> bool:
        if candidate[0] != current[0]:
            return candidate[0] < current[0]   # 决策时点优先级：11:00 > 15:00 > 其他
        if candidate[1] != current[1]:
            return candidate[1] > current[1]   # 同优先级取判读时间更新者
        return candidate[2] < current[2]       # 仍同则 _id 升序（确定性收尾）

    for doc in db["hotlist_jev_vote_confirm_pilot"].find({"tradingDate": date}):
        code = str(doc.get("code") or "")
        if not code:
            continue
        slot = doc.get("slotTime", "")
        # 不限定只取 11:00/15:00；同 code 多 slot 并存时，用较早决策时点覆盖收盘复核（11:00 > 15:00 > 其他）。
        rank = ("0" if slot == "11:00" else ("1" if slot == PILOT_SLOT else "2"),
                str(doc.get("computedAt") or ""), str(doc.get("_id") or ""))
        prev_rank = vote_rank.get(code)
        if prev_rank is None or _vote_wins(rank, prev_rank):
            vote_rank[code] = rank
            vote_by_code[code] = doc
    lc_by_code: dict[str, dict[str, Any]] = {}
    for doc in db["hotlist_jev_lifecycle_recheck_pilot"].find(
            {"tradingDate": date, "slotTime": PILOT_SLOT}):
        code = str(doc.get("code") or "")
        if code:
            lc_by_code[code] = doc

    # 连板高度：与涨停复盘页同源（jev_label_jiuyan.jiuyan_board_info，韭研+THS 池 join，
    # 单一事实源）；源缺失/异常结构化降级旗标，不阻断主读口（fail-visible）
    board_info: dict[str, dict[str, Any]] = {}
    board_meta: dict[str, Any] = {}
    board_join_error: str | None = None
    try:
        from backend.operations.jev_label_jiuyan import jiuyan_board_info
        board_info, board_meta = jiuyan_board_info(db, date)
        if not board_meta.get("jiuyanFinalFound"):
            board_join_error = "jiuyan_final_missing"
        elif not board_meta.get("thsPoolFound"):
            board_join_error = "ths_pool_missing"
        elif not board_meta.get("prevPoolFound"):
            board_join_error = "prev_pool_missing"
        elif board_meta.get("prevThsPoolFound") is False:
            board_join_error = "prev_ths_pool_missing"
    except Exception as exc:  # noqa: BLE001 — 辅助 join 失败不阻断主读口（boards 全缺如实 '--'）
        board_join_error = f"board_join_failed: {exc}"

    # 断板股（N>M）真实连续高度：逐日回溯封板链（韭研触板−THS炸板二分，与涨停复盘同源）；
    # 今日不可二分或历史日不可验 → None（宁缺毋猜），streakUnverified 计数 fail-visible
    today_sealed: set[str] | None = None
    if board_meta.get("jiuyanFinalFound") and board_meta.get("thsPoolFound"):
        today_sealed = {code for code, info in board_info.items() if not info.get("zhaban")}
    broken = {code: info["boards"] for code, info in board_info.items()
              if info.get("boards") is not None and info.get("days") is not None
              and info["days"] > info["boards"]}
    streaks: dict[str, int | None] = {}
    streak_unverified = 0
    if broken:
        try:
            streaks = jiuyan_consecutive_streaks(db, date, broken, today_sealed)
            streak_unverified = sum(1 for v in streaks.values() if v is None)
        except Exception:  # noqa: BLE001 — 回溯失败不阻断主读口，断板股连板如实 '--'
            streaks = {code: None for code in broken}
            streak_unverified = len(broken)

    rows: list[dict[str, Any]] = []
    vote_dirs: list[str | None] = []
    lc_stages: list[str | None] = []
    agree_count = diverge_count = lc_agree_count = lc_diverge_count = 0
    vote_reviewed = lc_reviewed = 0  # unreviewed 按行统计：文档 code 不在行集内时不误减
    risk_levels: dict[str, int] = {}
    for row in stock_rows:
        code = str(row.get("code") or "")
        a = analysis_by_code.get(code) or {}
        obs = a.get("observation") or {}
        res = a.get("resonance") or {}
        rule_stage = _clean((obs.get("lifecycle") or {}).get("stage"))
        tiers = {"resonance": _tier(res),
                 "trend": _tier(obs.get("rankTrend")),
                 "heat": _tier(obs.get("crossSection")),
                 "volumePrice": _tier(obs.get("volumePrice")),
                 "cycle": rule_stage,
                 "synergy": _tier(obs.get("synergy"))}
        vote_doc = vote_by_code.get(code)
        lc_doc = lc_by_code.get(code)
        if vote_doc:
            vote_reviewed += 1
        if lc_doc:
            lc_reviewed += 1
        # 连板语义（用户口径）：仅 N==M（如 8天8板）直接计板；N>M（断板）用回溯真实连续高度
        # （不可验 → None 显 '--'）。涨停复盘「高度」消费方仍用原始 M 口径，互不影响。
        b_info = board_info.get(code) or {}
        b_boards, b_days = b_info.get("boards"), b_info.get("days")
        if b_boards is None or b_days is None:
            boards_val = None
        elif b_days == b_boards:
            boards_val = b_boards
        else:
            boards_val = streaks.get(code)
        jev: dict[str, Any] | None = None
        if vote_doc or lc_doc:
            jev = {"vote": _vote_brief(vote_doc), "lc": _lc_brief(lc_doc),
                   "agree": None, "lcAgree": None}
            if vote_doc:
                direction = _clean(vote_doc.get("voteDirection"))
                anchor = synergy_direction(tiers["synergy"])
                if anchor and direction:
                    jev["agree"] = "agree" if anchor == direction else "diverge"
                    if jev["agree"] == "agree":
                        agree_count += 1
                    else:
                        diverge_count += 1
                vote_dirs.append(direction)
                for rf in (_risk_level(vote_doc),):
                    if rf:
                        risk_levels[rf] = risk_levels.get(rf, 0) + 1
            if lc_doc:
                lc_stage = _clean(lc_doc.get("lcStage"))
                if lc_stage and rule_stage:
                    jev["lcAgree"] = "agree" if lc_stage == str(rule_stage) else "diverge"
                    if jev["lcAgree"] == "agree":
                        lc_agree_count += 1
                    else:
                        lc_diverge_count += 1
                lc_stages.append(lc_stage)
                rf = _risk_level(lc_doc)
                if rf:
                    risk_levels[rf] = risk_levels.get(rf, 0) + 1
        item: dict[str, Any] = {
            "code": code,
            "name": row.get("name"),
            "price": _num(row.get("price")),
            "change": _num(row.get("change")),
            "boards": boards_val,
            # 板块=韭研 final 的 field.name（与涨停复盘 boardName 同源同键；final 缺失 → None 前端 '--'）
            "board": b_info.get("boardName"),
            "rank": row.get("rank") if isinstance(row.get("rank"), int)
                    and not isinstance(row.get("rank"), bool) else None,
            "compRank": row.get("compRank") if isinstance(row.get("compRank"), int)
                        and not isinstance(row.get("compRank"), bool) else None,
            "compScore": _num(row.get("compScore")),
            "amount": _num(row.get("amount")),
            "cirMV": _num(row.get("cirMV")),
            "turnoverRate": _num(row.get("turnoverRate")),
            "volumeRatio": _num(row.get("volumeRatio")),
            "resonanceScore": _num(res.get("score")),
            "tiers": tiers,
            "jev": jev,
        }
        if with_docs:
            item["docs"] = {"vote": _doc_public(vote_doc), "lc": _doc_public(lc_doc)}
        rows.append(item)

    rows.sort(key=lambda r: (r["rank"] is None,
                             r["rank"] if r["rank"] is not None else 99999,
                             r["code"]))

    def _status_counts(docs: list[dict[str, Any]]) -> dict[str, int]:
        out = {"ok": 0, "degraded": 0, "insufficient": 0}
        for d in docs:
            status = str(d.get("status") or "unknown")
            if status == "ok":
                out["ok"] += 1
            elif status == "degraded":
                out["degraded"] += 1
            elif status == "data_insufficient":
                out["insufficient"] += 1
        return out

    vote_status = _status_counts(list(vote_by_code.values()))
    lc_status = _status_counts(list(lc_by_code.values()))
    total = len(rows)
    summary = {
        "total": total,
        "tiered": sum(1 for r in rows if r["tiers"]["synergy"]),
        "vote": {**vote_status,
                 "buy": sum(1 for d in vote_dirs if d == "buy"),
                 "sell": sum(1 for d in vote_dirs if d == "sell"),
                 "hold": sum(1 for d in vote_dirs if d == "hold"),
                 "unreviewed": total - vote_reviewed},
        "lc": {**lc_status,
               "stages": _lc_stage_counts(lc_stages),
               "unreviewed": total - lc_reviewed},
        "agree": agree_count,
        "diverge": diverge_count,
        "lcAgree": lc_agree_count,
        "lcDiverge": lc_diverge_count,
        "risk": risk_levels,
        "streakUnverified": streak_unverified,
    }
    return {"ok": True, "date": date, "slotTime": slot_time, "datasetId": dataset_id,
            "snapshotId": sid, "rows": rows, "summary": summary, "noData": False,
            "reason": None, "boardJoinDegraded": board_join_error, "voteSlots": sorted(vote_slot_set)}


def _lc_stage_counts(stages: list[str | None]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in stages:
        if s:
            out[s] = out.get(s, 0) + 1
    return out


def _empty_summary() -> dict[str, Any]:
    return {"total": 0, "tiered": 0,
            "vote": {"ok": 0, "degraded": 0, "insufficient": 0,
                     "buy": 0, "sell": 0, "hold": 0, "unreviewed": 0},
            "lc": {"ok": 0, "degraded": 0, "insufficient": 0, "stages": {},
                   "unreviewed": 0},
            "agree": 0, "diverge": 0, "lcAgree": 0, "lcDiverge": 0, "risk": {},
            "streakUnverified": 0}
