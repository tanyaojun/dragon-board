# -*- coding: utf-8 -*-
"""竞价龙头晨间投喂 runner（vA1，预登记 auction-leader-vA1-preregistration-20261113）。

定位：每条投喂 = **当日 09:15「竞价看龙头」推送的一只个股**（选龙单源=A4，不允许
bid 通道兜底）；板块级 doc 判深度/延续（v12 A2 拆题同款）。09:26 挂链（9:25 竞价
冻结 + archiver ≤60s 轮询 lag），失败限次退避（scheduler 侧）。

与题材龙头链关系：独立集合 `hotlist_jev_auction_leader_labels`、独立题集 vA1；
复刻骨架（dry-run/estimate/confirm-budget/幂等/单只重跑/stdout 标记行）与语料读口
（fetch_* 单一事实源复用 theme_leader_label，禁第二套取数）。

花 token 的口子只有一个：`_label_one` 里的 `_dispatch_jev`；`--dry-run`/`--estimate`
全程零调用。真实开火必须 `--confirm-budget`（AGENTS §1.2-7）。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.auction_leader_label --date 2026-11-13 --dry-run
  ./.venv/Scripts/python.exe -m backend.operations.auction_leader_label --date 2026-11-13 --confirm-budget
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_board_map as ABM
from backend.analysis.hotlist import theme_event_digest as digest
from backend.analysis.hotlist.auction_leader_ammo import (
    AMMO_VERSION_AUCTION_LEADER,
    AUCTION_LEADER_QUESTIONS,
    AUCTION_SECTOR_QUESTIONS,
    QUESTION_SET_HASH_AUCTION_LEADER,
    QUESTION_SET_VERSION_AUCTION_LEADER,
    QUESTIONS_AUCTION_LEADER,
    auction_base_rate_line,
    auction_bid_line,
    auction_board_structure_line,
    auction_push_line,
    auction_structure_line,
    build_auction_leader_narrative,
    build_auction_sector_narrative,
)
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.jev_lhb_ammo import collect_lhb_facts
from backend.analysis.hotlist.theme_leader_ammo import (
    apply_evidence_gate,
    board_ladder_line,
    limitup_reason_line,
    lhb_line,
    notice_count_line,
    sector_judgment_line,
    theme_heat_line,
    zt_gene_line,
)
from backend.operations.theme_leader_baseline import day_leader_rows, trading_dates
from backend.operations.theme_leader_label import (
    DOC_KIND_LEADER,
    DOC_KIND_SECTOR,
    _lhb_codes_roles,
    _lhb_state_payload,
    fetch_daban_lanes,
    fetch_gene_corpus,
    fetch_notice_corpus,
    fetch_pool_quality,
    fetch_reason_corpus,
    fetch_theme_heat,
    estimate_tokens,
    gene_entries_for_leaders,
    notice_entries_for_leaders,
    reason_entries_for_leaders,
    theme_heat_entries_for_leaders,
    trading_dates_before,
)
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev
from backend.services.kpl_live_archive import archive_morning_live, load_auction_push

logger = logging.getLogger(__name__)

COLLECTION = "hotlist_jev_auction_leader_labels"
ORIGIN = "auction_leader_label_v1"
RESULT_MARKER = "AUCTION_LEADER_RESULT_JSON:"
SAMPLE_ORIGIN_LIVE = "live"
SAMPLE_ORIGIN_BACKFILL = "backfill"
# 基础率锚窗起点（投产日；防 look-ahead 右边界=before 当日排除）
BASE_RATE_START = "2026-11-13"


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


def auction_seal_base_rate(db: Any, before: str) -> dict | None:
    """竞价封板基础率锚（滚动直算，零 jev 零写入）：已结算竞价龙头当日封板率。

    人群：docKind=leader、status=ok、sampleOrigin=live、outcomeSealedToday 非空、
    tradingDate ∈ [BASE_RATE_START, before)——排除当日及以后（防 look-ahead）。
    无已结算行 → None（锚行整行缺席，封板题 confidence ≤0.6 规则承接）。
    """
    n = ok = 0
    dates: list[str] = []
    for d in db[COLLECTION].find({}, {"tradingDate": 1, "docKind": 1, "status": 1,
                                      "sampleOrigin": 1, "outcomeSealedToday": 1}):
        date = str(d.get("tradingDate") or "")
        if not (BASE_RATE_START <= date < before):
            continue
        if d.get("docKind") == DOC_KIND_SECTOR or d.get("status") != "ok":
            continue
        if (d.get("sampleOrigin") or SAMPLE_ORIGIN_LIVE) != SAMPLE_ORIGIN_LIVE:
            continue
        outcome = d.get("outcomeSealedToday")
        if outcome is None:
            continue
        n += 1
        ok += 1 if outcome else 0
        dates.append(date)
    if not n:
        return None
    return {"n": n, "rate": ok * 100.0 / n,
            "start": min(dates), "end": max(dates)}


def roster_for(db: Any, date: str, *, fetch_missing: bool = True) -> tuple[dict | None, dict]:
    """选龙单源（A4）：kpl_live_daily.auctionPush 投影；当日缺投影时晨间补归档一次。

    历史日无投影 → (None, {reason})（直播不可回放，不伪造名单）；当日补归档失败
    同样结构化返回（fail-visible）。fetch_missing=False（dry-run）纯只读：
    不发起直播 HTTP、不写归档（频控预算与零副作用）。
    """
    push = load_auction_push(db, date)
    if push is not None:
        return push, {"source": "archive"}
    if not fetch_missing:
        return None, {"reason": "auction_push_missing", "dryRun": True}
    if date != time.strftime("%Y-%m-%d"):
        return None, {"reason": "auction_push_missing_history"}
    state = archive_morning_live(db, date)
    push = load_auction_push(db, date)
    if push is None:
        return None, {"reason": state.get("reason") or "auction_push_missing",
                      "pushState": state.get("pushState")}
    return push, {"source": "morning_fetch", "pushState": state.get("pushState")}


def _hhmm(ts: Any) -> str | None:
    from backend.analysis.hotlist.theme_leader_ammo import _hhmm_from_ts
    return _hhmm_from_ts(ts)


def _inject_auction_sector_judgment(narrative: str, line: str) -> str:
    """板块判定行注入固定位置：基础率锚行前（无锚行则板块归属行后）；先剔陈旧行。"""
    lines = [ln for ln in narrative.split("\n") if not ln.startswith("板块判定：")]
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("竞价封板基础率：")), None)
    if idx is None:
        idx = next((i for i, ln in enumerate(lines) if ln.startswith("板块归属：")), None)
        idx = idx + 1 if idx is not None else len(lines)
    lines.insert(idx, line)
    return "\n".join(lines)


def _sealed_prev(pool_prev: dict, hit: dict) -> bool | None:
    """昨日封板事实（2026-11-13 review major-3）：池档健康 → 命中且 pool_state=sealed
    （炸板 broken 不算封板，与 kpl_lead_service 权威口径同）；健康查无此股=真不在池
    → False；pool_empty → False；其余 degraded → None（不伪装）。"""
    deg = pool_prev.get("degraded")
    if deg == "pool_empty":
        return False
    if deg is not None:
        return None
    return bool(hit) and (hit.get("item") or {}).get("pool_state") == "sealed"


def build_one(db: Any, date: str, prev_date: str | None, row: dict,
              *, t1_row: dict | None, pool_prev: dict, lanes: dict,
              gene_corpus: dict, notice_corpus: dict, heat_corpus: dict,
              reason_corpus: dict, lhb_facts: dict | None,
              market_line: str, base_rate_stats: dict | None,
              sector_judgment: dict | None, board_codes: list[str]) -> dict:
    """个股级投喂组装（零网络零模型）：T−1 语料 + 当日竞价 + 推送行。"""
    code = str(row.get("code") or "")
    board = row.get("board")
    rows = [row]
    # 昨日结构事实：T−1 龙头行命中 → 高度/10日涨幅；池档 → 昨日封板/首封时点
    hit = (pool_prev.get("items") or {}).get(code) or {}
    item = hit.get("item") or {}
    facts = {
        "streak": (t1_row or {}).get("streak"),
        "gain10": (t1_row or {}).get("gain10"),
        "sealedPrev": _sealed_prev(pool_prev, hit),
        "ztTime": _hhmm(item.get("zt_time")),
    }
    bid_items = lanes.get("bid") or {}
    # board=None（未归属）不出 peers：「同板竞价对比」名不副实（review nit）
    peers = [{"name": r.get("name"), "pct": (bid_items.get(str(r.get("code"))) or {}).get("bidding_pct"),
              "amount": (bid_items.get(str(r.get("code"))) or {}).get("bidding_amount")}
             for r in board_codes if str(r.get("code")) != code] if board else []
    bid_entries = [{"label": f"{row.get('name') or code}",
                    "item": bid_items.get(code), "peers": peers}]
    lhb_codes, lhb_roles = _lhb_codes_roles(
        [str(r.get("code")) for r in board_codes], [(code, "待判龙头")])
    lhb_txt = lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles) \
        if lhb_facts is not None else None
    if lhb_txt and prev_date:
        lhb_txt = lhb_txt.replace("龙虎榜：", f"龙虎榜（{prev_date} 榜单）：", 1)
    block = digest.build_theme_evidence_block(
        db, board_name=board or "", date=date, leader_code=code, sealed_codes=None)
    narrative = build_auction_leader_narrative(
        date=date, prev_date=prev_date or "不可考", market_line=market_line,
        leader_name=str(row.get("name") or ""), leader_code=code, board=board,
        push_board=row.get("pushBoard"),
        push_line=None,   # 推送行由 run() 注入（全日共用 entries，个股级只列自身）
        bid_line=auction_bid_line(bid_entries),
        structure=auction_structure_line(facts, prev_date=prev_date or "不可考"),
        ladder_line=(f"昨日（{prev_date}）" + board_ladder_line(t1_row))
        if t1_row else None,
        base_rate=auction_base_rate_line(base_rate_stats),
        sector_judgment=sector_judgment_line(sector_judgment),
        theme_heat_line=theme_heat_line(theme_heat_entries_for_leaders(rows, heat_corpus)),
        gene_line=zt_gene_line(gene_entries_for_leaders(rows, gene_corpus)),
        reason_line=limitup_reason_line(reason_entries_for_leaders(rows, reason_corpus)),
        notice_count_line=notice_count_line(notice_entries_for_leaders(rows, notice_corpus)),
        lhb_facts_line=lhb_txt,
        evidence_block=block["text"])
    return {"docKind": DOC_KIND_LEADER, "row": row, "narrative": narrative,
            "evidence": block,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "corpusState": {"prevDate": prev_date, "bidLane": lanes.get("bidLane"),
                            "prevPool": pool_prev.get("degraded"),
                            "lhbDate": prev_date},
            "chars": len(narrative), "estimatedTokens": estimate_tokens(len(narrative))}


def build_sector_one(db: Any, date: str, prev_date: str | None, board: str,
                     rows: list[dict], *, t1_rows: dict, pool_prev: dict,
                     lanes: dict, reason_corpus: dict, lhb_facts: dict | None,
                     market_line: str, base_rate_stats: dict | None,
                     push_entries: list[dict]) -> dict:
    """板块级投喂组装（深度/延续两题；板内推送股并列事实）。"""
    members = []
    for r in rows:
        code = str(r.get("code") or "")
        hit = (pool_prev.get("items") or {}).get(code) or {}
        members.append({"streak": (t1_rows.get(code) or {}).get("streak"),
                        "sealedPrev": _sealed_prev(pool_prev, hit)})
    bid_items = lanes.get("bid") or {}
    bid_entries = [{"label": str(r.get("name") or r.get("code")),
                    "item": bid_items.get(str(r.get("code")))} for r in rows]
    codes = [str(r.get("code")) for r in rows]
    lhb_codes, lhb_roles = _lhb_codes_roles(codes, [(c, "推送龙头") for c in codes])
    lhb_txt = lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles) \
        if lhb_facts is not None else None
    if lhb_txt and prev_date:
        lhb_txt = lhb_txt.replace("龙虎榜：", f"龙虎榜（{prev_date} 榜单）：", 1)
    block = digest.build_theme_evidence_block(
        db, board_name=board, date=date, leader_code=codes[0] if codes else "",
        sealed_codes=None)
    narrative = build_auction_sector_narrative(
        date=date, prev_date=prev_date or "不可考", market_line=market_line,
        board=board,
        push_line=auction_push_line(push_entries, codes=codes),
        board_structure=auction_board_structure_line(members, prev_date=prev_date or "不可考"),
        bid_line=auction_bid_line(bid_entries),
        base_rate=auction_base_rate_line(base_rate_stats),
        reason_line=limitup_reason_line(reason_entries_for_leaders(rows, reason_corpus)),
        lhb_facts_line=lhb_txt,
        evidence_block=block["text"])
    return {"docKind": DOC_KIND_SECTOR, "rows": rows, "board": board,
            "narrative": narrative, "evidence": block,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "corpusState": {"prevDate": prev_date, "bidLane": lanes.get("bidLane"),
                            "prevPool": pool_prev.get("degraded"), "lhbDate": prev_date},
            "chars": len(narrative), "estimatedTokens": estimate_tokens(len(narrative))}


def _label_one(db, col, date: str, built: dict, *,
               sample_origin: str = SAMPLE_ORIGIN_LIVE) -> tuple[bool, int]:
    """单条真实 jev 调用（唯一花 token 的路径）；按 docKind 分流题面子集。"""
    doc_kind = built.get("docKind", DOC_KIND_LEADER)
    questions = ({k: QUESTIONS_AUCTION_LEADER[k] for k in AUCTION_SECTOR_QUESTIONS}
                 if doc_kind == DOC_KIND_SECTOR else
                 {k: QUESTIONS_AUCTION_LEADER[k] for k in AUCTION_LEADER_QUESTIONS})
    narrative = built["narrative"]
    env, ms = _dispatch_jev(narrative, questions)
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    raw_answers = parsed.get("answers") or {}
    answers, gate = apply_evidence_gate(raw_answers, built.get("evidence") or {},
                                        keys=tuple(questions),
                                        prob_key="auction_leader_seal_today") \
        if parsed["ok"] else (raw_answers, {"applied": False, "reason": None})
    seal = answers.get("auction_leader_seal_today") or {}
    hard = answers.get("leader_catalyst_hardness") or {}
    seat = answers.get("auction_seat_durability") or {}
    depth = answers.get("theme_speculation_depth") or {}
    contn = answers.get("theme_continuation") or {}
    if doc_kind == DOC_KIND_SECTOR:
        rows = built.get("rows") or []
        if not rows:
            raise ValueError("_label_one: sector doc 缺 rows")
        doc = {"_id": f"{date}:board:{built['board']}", "origin": ORIGIN,
               "tradingDate": date, "docKind": DOC_KIND_SECTOR,
               "code": None, "name": None, "board": built["board"],
               "boardSources": sorted({str(r.get("boardSource")) for r in rows}),
               "segmentRows": [{"code": r.get("code"), "name": r.get("name"),
                                "pct": r.get("pct"),
                                "pushBoard": r.get("pushBoard")} for r in rows]}
    else:
        row = built["row"]
        doc = {"_id": f"{date}:{row['code']}", "origin": ORIGIN, "tradingDate": date,
               "docKind": DOC_KIND_LEADER, "code": row["code"],
               "name": row.get("name"), "board": row.get("board"),
               "pushBoard": row.get("pushBoard"),
               "boardSource": row.get("boardSource"),
               "boardMapping": row.get("boardMapping"),
               "auctionPct": row.get("pct")}
    doc.update({
        "ammoVersion": AMMO_VERSION_AUCTION_LEADER,
        "questionSetVersion": QUESTION_SET_VERSION_AUCTION_LEADER,
        "questionSetHash": QUESTION_SET_HASH_AUCTION_LEADER,
        "lhbState": built.get("lhbState"),
        "corpusState": built.get("corpusState"),
        "auctionPushState": built.get("auctionPushState"),
        "sectorJudgmentState": (built.get("sectorJudgmentState")
                                if doc_kind == DOC_KIND_LEADER else None),
        "evidenceState": built["evidence"]["state"],
        "evidenceMissing": bool((built.get("evidence") or {}).get("evidenceMissing")),
        "evidenceMissingReason": (built.get("evidence") or {}).get("evidenceMissingReason"),
        "evidenceEventTitles": [e.get("title") for e in built["evidence"].get("events") or []],
        "evidenceNewsTitles": [n.get("title") for n in built["evidence"].get("news") or []],
        "narrative": narrative, "questionsRaw": questions,
        "answers": answers, "modelAnswers": raw_answers, "gate": gate,
        "auctionSealToday": seal.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "auctionSealProbabilities": seal.get("probabilities") if doc_kind == DOC_KIND_LEADER else None,
        "leaderCatalystHardness": hard.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "auctionSeatDurability": seat.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "themeSpeculationDepth": depth.get("choice") if doc_kind == DOC_KIND_SECTOR else None,
        "themeContinuation": contn.get("choice") if doc_kind == DOC_KIND_SECTOR else None,
        "status": "ok" if parsed["ok"] else "degraded",
        "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
        "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
        "responseRaw": None if parsed["ok"] else env,
        "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")
        + ".%03d" % (int(time.time() * 1000) % 1000),
        "sampleOrigin": sample_origin,
        # 结局留空：当日收盘后由结算链回填（防 look-ahead）；重跑重建原样带走
        "outcomeSealedToday": None,
    })
    old = col.find_one({"_id": doc["_id"]}) or {}
    for k, v in old.items():
        if k.startswith("outcome"):
            doc[k] = v
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    from backend.analysis.hotlist.jev_driver_ammo import _usage_tokens
    return bool(parsed["ok"]), _usage_tokens(parsed.get("usage"))


def run(date: str, *, dry_run: bool = False, confirm_budget: bool = False,
        max_leaders: int | None = None, force: bool = False,
        codes: set[str] | None = None, dataset_id: str = DEFAULT_DATASET_ID,
        sample_origin: str | None = None) -> dict:
    """当日晨间投喂主流程。dry_run 全程零 jev 调用零写入（含不补拉直播/不写归档）。

    sample_origin 缺省自动裁决：当日=live、历史日=backfill（防事后补跑混入 live 锚人群）；
    显式传入（rerun 路由保留原 origin）优先。
    """
    db = _db()
    if sample_origin is None:
        sample_origin = (SAMPLE_ORIGIN_LIVE if date == time.strftime("%Y-%m-%d")
                         else SAMPLE_ORIGIN_BACKFILL)
    push, push_meta = roster_for(db, date, fetch_missing=not dry_run)
    if push is None or not push.get("stocks"):
        reason = (push_meta or {}).get("reason") or "auction_push_missing"
        # 晨间取数失败（瞬时抖动）≠ 验证后缺席：ok=False 交调度 3×5min 退避（A1）
        fetch_failed = (push_meta or {}).get("pushState") == "fetch_failed"
        print(f"{date} 竞价推送缺席（{reason}），跳过打标（fail-visible，不兜底选龙）")
        return {"ok": not fetch_failed, "date": date, "leaders": 0,
                "skippedReason": "auction_push_missing",
                "errorCode": "auction_push_fetch_failed" if fetch_failed else None,
                "auctionPushState": push_meta}
    rows = [{"code": str(s.get("code")), "name": s.get("name"),
             "board": s.get("board"), "pct": s.get("pct")}
            for s in push["stocks"] if s.get("code")]
    # 2026-11-13 用户裁决：板块归属取韭研板块名（推送概念是题材炒作概念，与证据层
    # 口径错位致三层证据假性全缺）；无成分映射回退推送概念 + boardSource 留痕
    bctx = ABM.load_board_context(db, date)
    for r in rows:
        res = ABM.resolve_leader_board(bctx, r["code"], r.get("board"))
        r["board"] = res["board"]
        r["pushBoard"] = res["pushBoard"]
        r["boardSource"] = res["boardSource"]
        r["boardMapping"] = {"pickedBy": res["pickedBy"],
                             "candidates": res["candidates"]}
    excluded = [r for r in rows if r["board"] and digest.is_not_a_theme(r["board"])]
    if excluded:
        print(f"{date} 排除非题材行政桶 {len(excluded)} 只（{'、'.join(sorted({r['board'] for r in excluded}))}）——仅日志留痕")
        rows = [r for r in rows if not (r["board"] and digest.is_not_a_theme(r["board"]))]
    if codes:
        rows = [r for r in rows if r["code"] in codes]
    if not rows:
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders"}
    rows.sort(key=lambda r: (str(r.get("board") or ""), -(r.get("pct") or 0)))
    prev_dates = trading_dates_before(db, date, 2, dataset_id)
    prev_date = prev_dates[-1] if prev_dates else None
    # 一次取数全日共用（与题材链同哲学；T−1 语料 + 当日竞价）
    from backend.operations.jev_label_jiuyan import market_facts_line
    market_line = market_facts_line(db, prev_date, dataset_id) if prev_date else "不可考"
    t1_rows: dict[str, dict] = {}
    if prev_date:
        t1_all, _meta = day_leader_rows(db, prev_date, dataset_id,
                                        prev_date=prev_dates[-2] if len(prev_dates) > 1 else None,
                                        space_mode=True, pool_dates=prev_dates)
        for r in t1_all or []:
            t1_rows[str(r.get("code"))] = r
    pool_prev = fetch_pool_quality(db, prev_date) if prev_date else {"items": {}, "degraded": "no_prev_date"}
    lanes = fetch_daban_lanes(db, date)
    gene_corpus = fetch_gene_corpus(db, prev_date) if prev_date else {}
    notice_corpus = fetch_notice_corpus(db, prev_date) if prev_date else {}
    heat_corpus = fetch_theme_heat(db, prev_date) if prev_date else {}
    reason_corpus = fetch_reason_corpus(db, prev_date) if prev_date else {}
    lhb_facts = None
    if prev_date:
        try:
            lhb_facts = collect_lhb_facts(prev_date)
        except Exception as exc:  # noqa: BLE001 — fail-visible 不阻断
            lhb_facts = {"ok": False, "degraded": True, "reason": f"fetch_failed: {exc}"}
    base_rate_stats = auction_seal_base_rate(db, before=date)
    push_entries = push.get("entries") or []
    by_board: dict[str, list[dict]] = {}
    for r in rows:
        by_board.setdefault(str(r.get("board") or "未归属"), []).append(r)
    col = db[COLLECTION]
    done = {str(d.get("code")) for d in col.find({"tradingDate": date, "status": "ok"})
            if d.get("code")}
    done_boards = {str(d.get("board")) for d in col.find(
        {"tradingDate": date, "status": "ok", "docKind": DOC_KIND_SECTOR}) if d.get("board")}
    todo = [r for r in rows if force or r["code"] not in done]
    if max_leaders is not None and len(todo) > max_leaders:
        print(f"{date} {len(todo)} 只超上限 {max_leaders}，截断（其余记账，fail-visible）")
        todo = todo[:max_leaders]
    todo_boards = ({str(r.get("board") or "未归属") for r in todo}
                   - (set() if force else done_boards))
    if codes and not force:
        # 单只重跑同时自愈该日 degraded 板块 doc（题材链 P2-4 同款：龙头全 ok 但
        # 板块 degraded 的档 codes 也修得了）；范围=选中行所在板块
        todo_boards |= {
            str(d.get("board")) for d in col.find(
                {"tradingDate": date, "docKind": DOC_KIND_SECTOR, "status": "degraded"})
            if d.get("board") and str(d.get("board")) in
            {str(r.get("board") or "未归属") for r in rows}}
    # v17 同款：板块判答预载（库读兜底；同轮新跑由标注循环先板块后个股注入）
    sector_answers: dict[str, dict] = {}
    for d in col.find({"tradingDate": date, "docKind": DOC_KIND_SECTOR, "status": "ok"}):
        if d.get("board"):
            sector_answers[str(d["board"])] = d.get("answers") or {}
    built_sectors: list[dict] = []
    for board, brows in by_board.items():
        if board in todo_boards and board != "未归属":
            built_sectors.append(build_sector_one(
                db, date, prev_date, board, brows, t1_rows=t1_rows,
                pool_prev=pool_prev, lanes=lanes, reason_corpus=reason_corpus,
                lhb_facts=lhb_facts, market_line=market_line,
                base_rate_stats=base_rate_stats, push_entries=push_entries))
    built_leaders: list[dict] = []
    for r in todo:
        board = str(r.get("board") or "未归属")
        built = build_one(db, date, prev_date, r,
                          t1_row=t1_rows.get(r["code"]), pool_prev=pool_prev,
                          lanes=lanes, gene_corpus=gene_corpus,
                          notice_corpus=notice_corpus, heat_corpus=heat_corpus,
                          reason_corpus=reason_corpus, lhb_facts=lhb_facts,
                          market_line=market_line, base_rate_stats=base_rate_stats,
                          sector_judgment=sector_answers.get(board),
                          board_codes=by_board.get(board, [r]))
        built["auctionPushState"] = {"source": push_meta.get("source"),
                                     "entryN": len(push_entries)}
        # 推送行注入（全日共用 entries；个股级只列自身）
        push_txt = auction_push_line(push_entries, codes=[r["code"]])
        if push_txt:
            # 按行首定位插入（板块归属行可能带推送概念后缀，精确串 replace 会失配）
            _lines = built["narrative"].split("\n")
            for _i, _ln in enumerate(_lines):
                if _ln.startswith("板块归属："):
                    _lines.insert(_i + 1, push_txt)
                    break
            built["narrative"] = "\n".join(_lines)
        built["sectorJudgmentState"] = ("injected" if sector_answers.get(board)
                                        else "sector_missing")
        built_leaders.append(built)
    built_all = built_sectors + built_leaders
    est = sum(b["estimatedTokens"]["budgetGuard"] for b in built_all)
    if dry_run:
        for b in built_all:
            print(f"----- {b.get('docKind')} {b.get('board') or (b.get('row') or {}).get('code')} "
                  f"chars={b['chars']} -----")
            print(b["narrative"])
        return {"ok": True, "date": date, "dryRun": True, "leaders": len(todo),
                "docs": len(built_all), "estimatedTokens": est}
    if not confirm_budget:
        print(f"{date} 预计 {len(built_all)} 调用 ≈{est} tokens；真实开火需 --confirm-budget")
        raise SystemExit(2)
    # 先板块后个股（板块判答注入个股叙事，v17 同款）
    ok_n = degraded_n = tokens = 0
    for b in built_sectors:
        ok, tk = _label_one(db, col, date, b, sample_origin=sample_origin)
        ok_n += 1 if ok else 0
        degraded_n += 0 if ok else 1
        tokens += tk
        if ok:
            sector_answers[str(b["board"])] = b.get("answers") or {}
    for b in built_leaders:
        board = str((b.get("row") or {}).get("board") or "未归属")
        line = sector_judgment_line(sector_answers.get(board))
        if line:
            b["narrative"] = _inject_auction_sector_judgment(b["narrative"], line)
            b["sectorJudgmentState"] = "injected"
        else:
            b["narrative"] = "\n".join(ln for ln in b["narrative"].split("\n")
                                       if not ln.startswith("板块判定："))
            b["sectorJudgmentState"] = "sector_missing"
        ok, tk = _label_one(db, col, date, b, sample_origin=sample_origin)
        ok_n += 1 if ok else 0
        degraded_n += 0 if ok else 1
        tokens += tk
    result = {"ok": True, "date": date, "leaders": len(todo), "docs": len(built_all),
              "okCount": ok_n, "degraded": degraded_n, "tokensUsed": tokens,
              "estimatedTokensBudgetGuard": est,
              "questionSetVersion": QUESTION_SET_VERSION_AUCTION_LEADER}
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="竞价龙头晨间投喂（vA1）")
    ap.add_argument("--date", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--confirm-budget", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-leaders", type=int, default=None)
    ap.add_argument("--codes", default=None, help="逗号分隔单只重跑")
    ap.add_argument("--sample-origin", default=None, choices=["live", "backfill"],
                    help="缺省自动：当日 live / 历史日 backfill")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run(args.date, dry_run=args.dry_run or args.estimate,
                 confirm_budget=args.confirm_budget, force=args.force,
                 max_leaders=args.max_leaders,
                 codes=set(args.codes.split(",")) if args.codes else None,
                 sample_origin=args.sample_origin)
    # 标记行统一在 main 打（覆盖 skip/失败外全部返回路径；调度只认标记行）
    if not (args.dry_run or args.estimate):
        print(RESULT_MARKER + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()