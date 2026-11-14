# -*- coding: utf-8 -*-
"""竞价龙头晨间投喂 runner（vA2，预登记 auction-leader-vA2-preregistration-20261114）。

定位：每条投喂 = 当日选龙双源并集的一只个股（A4e：09:15「竞价看龙头」推送 ∪
jiuyan T−1 涨停分组龙一/二/三，官方封板口径 ≥3 家，2026-11-14 用户裁决 B1–B3）；
板块级 doc 判深度/延续（v12 A2 拆题同款）。09:26 挂链（9:25 竞价冻结 + archiver
≤60s 轮询 lag），失败限次退避（scheduler 侧）。

与题材龙头链关系：独立集合 `hotlist_jev_auction_leader_labels`、独立题集 vA2；
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
    auction_dragon_line,
    auction_push_line,
    auction_structure_line,
    auction_trial_line,
    build_auction_leader_narrative,
    build_auction_sector_narrative,
)
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.services.kpl_ranking_service import (
    derive_bid_ratio_prev_vol,
    get_auction_snapshot_tencent,
    get_daban_prev_day_basis,
)
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
from backend.operations.auction_trial_fetch import (
    fetch_auction_trial, persist_trial_raw)
from backend.operations.theme_leader_baseline import (day_leader_rows, sealed_and_info,
                                                      trading_dates)
from backend.operations.jev_label_jiuyan import jiuyan_streak_map
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
# A4e/B1/B2（2026-11-14 用户裁决）：jiuyan 源板块达标 = 官方封板口径涨停家数 ≥3
JIUYAN_DRAGON_MIN_SEALED = 3
SOURCE_PUSH = "auction_push"
SOURCE_JIUYAN_DRAGON = "jiuyan_dragon_t1"


def jiuyan_dragon_roster(db: Any, prev_date: str | None) -> tuple[list[dict], dict]:
    """A4e 双源选龙：jiuyan T−1 涨停打标链各板块龙一/二/三（封板家数 ≥3）。

    单一事实源：龙序 = `jiuyan_board_dragons`/`dragon_rows`（高度 M 降序 + 封板时间
    升序，与 relay 梯队表同口径；B4：龙序不排除炸板股，炸板事实行内标注）；达标家数
    = `jiuyan_board_info` zhaban/excluded 旗标（触板 − THS 炸板（含回封补证）− ST/北交所，
    B2 官方封板口径，禁第二套二分）。零新增外呼源：全库内读 + 既有 `_daily_bars`
    （本地 vipdoc 优先；本地缺文件股回退既有线上 mootdx 日线，进程内缓存+负缓存，
    量级 ≤ T−1 炸板池命中数；预算见 vA2 预登记 §6，review M1）。

    宁缺毋猜（B2）：T−1 final 缺席 / THS 炸板池缺失 → 整源缺席 + reason 结构化留痕
    （不回退触板口径——会混入炸板股）。返回 (rows, state)：rows = [{code, name,
    board（主板）, dragonRoles（全部龙序，封板家数降序→组名升序）}]。
    """
    state: dict = {"t1Date": prev_date, "countCaliber": "sealed_official",
                   "minSealed": JIUYAN_DRAGON_MIN_SEALED}
    if not prev_date:
        return [], {**state, "reason": "no_prev_date"}
    from backend.operations.jev_label_jiuyan import (
        jiuyan_board_dragons, jiuyan_board_info)
    doc = db["jiuyan_action"].find_one({"_id": f"{prev_date}:final"}, {"fields": 1}) or {}
    fields = doc.get("fields") or []
    if not any(f.get("stocks") for f in fields):
        return [], {**state, "t1Final": False, "reason": "t1_final_missing"}
    info, meta = jiuyan_board_info(db, prev_date)
    if not meta.get("thsPoolFound"):
        return [], {**state, "t1Final": True, "thsPoolFound": False,
                    "reason": "ths_pool_missing"}
    dragons = jiuyan_board_dragons(db, prev_date)
    qualified: list[dict] = []
    by_code: dict[str, dict] = {}
    for f in fields:
        name = str(f.get("name") or "")
        stocks = f.get("stocks") or []
        if not name or not stocks:
            continue
        sealed_n = 0
        for s in stocks:
            c = str(s.get("code") or "")[-6:]
            i = info.get(c) or {}
            if c and not i.get("zhaban") and not i.get("excluded"):
                sealed_n += 1
        if sealed_n < JIUYAN_DRAGON_MIN_SEALED:
            continue
        qualified.append({"board": name, "sealedN": sealed_n, "touchN": len(stocks)})
        for r in dragons.get(name) or []:
            code = r.get("code")
            if not code:
                continue
            role = {"board": name, "role": r.get("role"), "boards": r.get("boards"),
                    "days": r.get("days"), "time": r.get("time"), "sealedN": sealed_n}
            if (info.get(code) or {}).get("zhaban"):
                role["zhaban"] = True
            e = by_code.setdefault(code, {"code": code, "name": r.get("name"),
                                          "dragonRoles": []})
            e["dragonRoles"].append(role)
    rows: list[dict] = []
    for code, e in by_code.items():
        # 多板龙序主板：封板家数降序 → 组名升序（B6，A4b 同序无推送桥）
        roles = sorted(e["dragonRoles"], key=lambda x: (-x["sealedN"], x["board"]))
        rows.append({"code": code, "name": e.get("name"), "board": roles[0]["board"],
                     "dragonRoles": roles})
    rows.sort(key=lambda r: (r["board"], r["code"]))
    return rows, {**state, "t1Final": True, "thsPoolFound": True,
                  "boardsQualified": qualified, "dragonN": len(rows)}


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
    n_push = n_jiuyan = 0
    dates: list[str] = []
    for d in db[COLLECTION].find({}, {"tradingDate": 1, "docKind": 1, "status": 1,
                                      "sampleOrigin": 1, "outcomeSealedToday": 1,
                                      "selectionSources": 1}):
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
        # vA2 锚人群构成：双源股归韭研龙桶；vA1 旧档无 selectionSources 按推送计
        if SOURCE_JIUYAN_DRAGON in (d.get("selectionSources") or [SOURCE_PUSH]):
            n_jiuyan += 1
        else:
            n_push += 1
        dates.append(date)
    if not n:
        return None
    return {"n": n, "rate": ok * 100.0 / n, "nPush": n_push, "nJiuyan": n_jiuyan,
            "start": min(dates), "end": max(dates)}


def roster_for(db: Any, date: str, *, fetch_missing: bool = True) -> tuple[dict | None, dict]:
    """推送源（A4e 双源之一）：kpl_live_daily.auctionPush 投影；当日缺投影时晨间补归档一次。

    历史日无投影 → (None, {reason})（直播不可回放，不伪造名单；jiuyan 源仍可跑，B3）；
    当日补归档失败同样结构化返回（fail-visible）。fetch_missing=False（dry-run）纯只读：
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


def _sealed_prev_cross(pool_prev: dict, hit: dict, cross: dict | None,
                       code: str) -> tuple[bool | None, str]:
    """昨日封板事实 + 来源留痕（2026-11-14b 原料层修复 P1，天普 605255 复盘）。

    KPL 池是截断排序榜（max_size 分页；11-12 档漏 605255 → 假事实「昨日未封板」）：
    **缺席 ≠ 未封板**。交叉源 = sealed_and_info（韭研 final ∪ THS 炸板二分 + TDX
    回封补证，题材链单一实现复用，纯 DB 读零新采集）。判定矩阵：
    - 池降级 → None（不判，不变）；
    - 池命中 sealed → True（pool）；
    - 池命中 broken：交叉源证封板 → None（冲突不伪造）；否则 False（pool）；
    - 池缺席：交叉源不可用（THS 缺/取数失败）→ False（pool_only 旧口径+留痕）；
      交叉源证封板 → True（jiuyan_ths，池漏档）；证炸板 → False（jiuyan_ths_zhaban）；
      全源无触板记录 → False（pool）。
    """
    deg = pool_prev.get("degraded")
    if deg is not None:
        return None, "pool_degraded"
    state = (hit.get("item") or {}).get("pool_state")
    sealed_set = (cross or {}).get("sealed")
    info = (cross or {}).get("info") or {}
    if hit and state == "sealed":
        return True, "pool"
    if hit and state == "broken":
        if sealed_set is not None and code in sealed_set:
            return None, "conflict_pool_broken_cross_sealed"
        return False, "pool"
    if sealed_set is None:
        return False, "pool_only"
    if code in sealed_set:
        return True, "jiuyan_ths"
    if (info.get(code) or {}).get("zhaban"):
        return False, "jiuyan_ths_zhaban"
    return False, "pool"


def _sealed_prev(pool_prev: dict, hit: dict) -> bool | None:
    """旧口径兼容入口（池单源）；新代码走 _sealed_prev_cross（多源交叉+留痕）。"""
    return _sealed_prev_cross(pool_prev, hit, None, "")[0]


def _in_auction_window() -> bool:
    """竞价补源有效窗 [09:25, 09:30)：09:30 起连续竞价，现价已非竞价冻结值，不补。"""
    return "09:25" <= time.strftime("%H:%M") < "09:30"


def _auction_ladder_line(t1_row: dict | None, prev_date: str | None) -> str | None:
    """梯队行消费点卫生（2026-11-13 用户竞价链加严裁决，review 2026-11-13f finding-2）：
    theme 共享 board_ladder_line 的「不可算」占位段在竞价叙事剔除（缺数据段不出现），
    可算事实段保留（龙头高度可算、次高缺位 → 仅保龙头段）。"""
    if not t1_row:
        return None
    line = board_ladder_line(t1_row)
    if not line:
        return None
    segs = []
    for seg in line.split("；"):
        if "不可算" not in seg:
            segs.append(seg)
        elif "龙头" in seg and "次高" in seg:
            segs.append(seg.split("，")[0])
    out = "；".join(segs)
    return f"昨日（{prev_date}）{out}" if out else None


def build_one(db: Any, date: str, prev_date: str | None, row: dict,
              *, t1_row: dict | None, pool_prev: dict, lanes: dict,
              gene_corpus: dict, notice_corpus: dict, heat_corpus: dict,
              reason_corpus: dict, lhb_facts: dict | None,
              market_line: str, base_rate_stats: dict | None,
              sector_judgment: dict | None, board_codes: list[str],
              basis_map: dict | None = None, basis_state: str = "missing",
              bid_supplement: str | None = None,
              prev_cross: dict | None = None, streak_map: dict | None = None,
              trial: dict | None = None) -> dict:
    """个股级投喂组装（零网络零模型）：T−1 语料 + 当日竞价 + 推送行。

    trial = 试盘源载荷（增量2 骨架，合同定案前恒 None → trialState=contract_pending，
    叙事无试盘行；定案后 = {"row": 盯盘试盘行具名字段, "source", "fetchedAt",
    "prevPercentCross"}，由晨间窗内采集器單股传入）。"""
    code = str(row.get("code") or "")
    board = row.get("board")
    rows = [row]
    # 昨日结构事实：T−1 龙头行命中 → 高度/10日涨幅；池档+交叉源 → 昨日封板/首封时点
    hit = (pool_prev.get("items") or {}).get(code) or {}
    item = hit.get("item") or {}
    sealed_prev, sealed_src = _sealed_prev_cross(pool_prev, hit, prev_cross, code)
    facts = {
        "streak": (t1_row or {}).get("streak") or (streak_map or {}).get(code),
        "gain10": (t1_row or {}).get("gain10"),
        "sealedPrev": sealed_prev,
        "ztTime": _hhmm(item.get("zt_time")),
    }
    # 池漏档但交叉源证封板 → 首封时点取韭研（纯事实补全，来源留痕 prevPoolCross）
    if not facts["ztTime"] and sealed_prev is True and prev_cross:
        jt = ((prev_cross.get("info") or {}).get(code) or {}).get("time")
        if isinstance(jt, str) and jt:
            facts["ztTime"] = jt[:5]
    bid_items = lanes.get("bid") or {}
    # board=None（未归属）不出 peers：「同板竞价对比」名不副实（review nit）
    peers = [{"name": r.get("name"), "code": r.get("code"), "pct": (bid_items.get(str(r.get("code"))) or {}).get("bidding_pct"),
              "amount": (bid_items.get(str(r.get("code"))) or {}).get("bidding_amount")}
             for r in board_codes if str(r.get("code")) != code] if board else []
    bid_item = bid_items.get(code)
    bid_source = None
    if bid_item is not None:
        bid_source = str(bid_item.get("source") or "kpl_bid_lane")
        bid_item = {**bid_item, "ratio_prev_vol": derive_bid_ratio_prev_vol(
            bid_item, (basis_map or {}).get(code))}
    bid_entries = [{"label": f"{row.get('name') or code}",
                    "item": bid_item, "peers": peers}]
    lhb_codes, lhb_roles = _lhb_codes_roles(
        [str(r.get("code")) for r in board_codes], [(code, "待判龙头")])
    lhb_txt = lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles) \
        if lhb_facts is not None else None
    if lhb_txt and prev_date:
        lhb_txt = lhb_txt.replace("龙虎榜：", f"龙虎榜（{prev_date} 榜单）：", 1)
    block = digest.build_theme_evidence_block(
        db, board_name=board or "", date=date, leader_code=code, sealed_codes=None,
        l2_fallback_date=prev_date, leader_expound_chars=1200, include_morning=True,
        include_flash=True)
    narrative = build_auction_leader_narrative(
        date=date, prev_date=prev_date, market_line=market_line,
        leader_name=str(row.get("name") or ""), leader_code=code, board=board,
        push_board=row.get("pushBoard"),
        push_line=None,   # 推送行由 run() 注入（全日共用 entries，个股级只列自身）
        dragon_line=auction_dragon_line(row.get("dragonRoles"), prev_date=prev_date),
        bid_line=auction_bid_line(bid_entries),
        trial_line=auction_trial_line((trial or {}).get("row")),
        structure=auction_structure_line(facts, prev_date=prev_date),
        ladder_line=_auction_ladder_line(t1_row, prev_date),
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
            # 真竞价涨幅（09:25 匹配价，bid 通道 bidding_pct；含腾讯榜外补源）——
            # 与推送芯片 pct（实时涨幅）严格分离，落库 auctionPct 取此值（2026-11-14 修复）
            "auctionBidPct": (bid_item or {}).get("bidding_pct"),
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "corpusState": {"prevDate": prev_date, "bidLane": lanes.get("bidLane"),
                            "bidIn": code in bid_items, "bidSource": bid_source,
                            "bidSupplement": bid_supplement,
                            "basisState": basis_state,
                            "prevPool": pool_prev.get("degraded"),
                            "prevPoolCross": sealed_src,
                            "l2Date": block.get("l2Date"),
                            "l2FallbackUsed": block.get("l2FallbackUsed"),
                            "lhbDate": prev_date,
                            "morningState": block.get("morningState"),
                            "morningDate": block.get("morningDate"),
                            "flashState": block.get("flashState"),
                            "trialState": ({"state": "ok",
                                            "source": trial.get("source"),
                                            "fetchedAt": trial.get("fetchedAt"),
                                            "prevPercentCross": trial.get("prevPercentCross")}
                                           if trial else {"state": "contract_pending"})},
            "chars": len(narrative), "estimatedTokens": estimate_tokens(len(narrative))}


def build_sector_one(db: Any, date: str, prev_date: str | None, board: str,
                     rows: list[dict], *, t1_rows: dict, pool_prev: dict,
                     lanes: dict, reason_corpus: dict, lhb_facts: dict | None,
                     market_line: str, base_rate_stats: dict | None,
                     push_entries: list[dict],
                     basis_map: dict | None = None, basis_state: str = "missing",
                     prev_cross: dict | None = None) -> dict:
    """板块级投喂组装（深度/延续两题；板内推送股并列事实）。"""
    members = []
    for r in rows:
        code = str(r.get("code") or "")
        hit = (pool_prev.get("items") or {}).get(code) or {}
        members.append({"streak": (t1_rows.get(code) or {}).get("streak"),
                        "sealedPrev": _sealed_prev_cross(pool_prev, hit, prev_cross, code)[0]})
    bid_items = lanes.get("bid") or {}
    bid_entries = []
    for r in rows:
        _bi = bid_items.get(str(r.get("code")))
        if _bi is not None:
            _bi = {**_bi, "ratio_prev_vol": derive_bid_ratio_prev_vol(
                _bi, (basis_map or {}).get(str(r.get("code"))))}
        bid_entries.append({"label": str(r.get("name") or r.get("code")), "item": _bi})
    codes = [str(r.get("code")) for r in rows]
    dragon_roles = [x for r in rows for x in (r.get("dragonRoles") or [])
                    if x.get("board") == board]
    lhb_codes, lhb_roles = _lhb_codes_roles(codes, [(c, "入选龙头") for c in codes])
    lhb_txt = lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles) \
        if lhb_facts is not None else None
    if lhb_txt and prev_date:
        lhb_txt = lhb_txt.replace("龙虎榜：", f"龙虎榜（{prev_date} 榜单）：", 1)
    block = digest.build_theme_evidence_block(
        db, board_name=board, date=date, leader_code=codes[0] if codes else "",
        sealed_codes=None, l2_fallback_date=prev_date, include_morning=True,
        include_flash=True)
    narrative = build_auction_sector_narrative(
        date=date, prev_date=prev_date, market_line=market_line,
        board=board,
        push_line=auction_push_line(push_entries, codes=codes),
        dragon_line=auction_dragon_line(dragon_roles, prev_date=prev_date),
        board_structure=auction_board_structure_line(members, prev_date=prev_date),
        bid_line=auction_bid_line(bid_entries),
        base_rate=auction_base_rate_line(base_rate_stats),
        reason_line=limitup_reason_line(reason_entries_for_leaders(rows, reason_corpus)),
        lhb_facts_line=lhb_txt,
        evidence_block=block["text"])
    return {"docKind": DOC_KIND_SECTOR, "rows": rows, "board": board,
            "narrative": narrative, "evidence": block,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "corpusState": {"prevDate": prev_date, "bidLane": lanes.get("bidLane"),
                            "bidIn": any(str(r.get("code") or "") in bid_items
                                         for r in rows),   # review 2026-11-13f：板块级=任一成员在榜
                            "basisState": basis_state,
                            "prevPool": pool_prev.get("degraded"), "lhbDate": prev_date,
                            "morningState": block.get("morningState"),
                            "morningDate": block.get("morningDate"),
                            "flashState": block.get("flashState")},
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
    tpat = answers.get("trial_settlement_pattern") or {}
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
                                "pushBoard": r.get("pushBoard"),
                                "sources": r.get("selectionSources"),
                                "dragonRole": next((x.get("role") for x in
                                                    (r.get("dragonRoles") or [])
                                                    if x.get("board") == built["board"]), None)}
                               for r in rows]}
    else:
        row = built["row"]
        doc = {"_id": f"{date}:{row['code']}", "origin": ORIGIN, "tradingDate": date,
               "docKind": DOC_KIND_LEADER, "code": row["code"],
               "name": row.get("name"), "board": row.get("board"),
               "pushBoard": row.get("pushBoard"),
               "boardSource": row.get("boardSource"),
               "boardMapping": row.get("boardMapping"),
               "selectionSources": row.get("selectionSources") or [SOURCE_PUSH],
               "dragonRoles": row.get("dragonRoles") or [],
               # 竞价涨幅=bid 通道真竞价值（bidding_pct）；实时涨幅=推送芯片 pct。
               # 2026-11-14 修复：旧版把推送实时 pct 误存为 auctionPct（读口对历史档 join 兜底）
               "auctionPct": built.get("auctionBidPct"),
               "realtimePct": row.get("pct")}
    doc.update({
        "ammoVersion": AMMO_VERSION_AUCTION_LEADER,
        "questionSetVersion": QUESTION_SET_VERSION_AUCTION_LEADER,
        "questionSetHash": QUESTION_SET_HASH_AUCTION_LEADER,
        "lhbState": built.get("lhbState"),
        "corpusState": built.get("corpusState"),
        "corpusFrozen": bool(built.get("corpusFrozen")),
        "auctionPushState": built.get("auctionPushState"),
        "sectorJudgmentState": (built.get("sectorJudgmentState")
                                if doc_kind == DOC_KIND_LEADER else None),
        "evidenceState": built["evidence"]["state"],
        "evidenceMissing": bool((built.get("evidence") or {}).get("evidenceMissing")),
        "evidenceMissingReason": (built.get("evidence") or {}).get("evidenceMissingReason"),
        "evidenceEventTitles": [e.get("title") for e in built["evidence"].get("events") or []],
        "evidenceNewsTitles": [n.get("title") for n in built["evidence"].get("news") or []],
        # 事件列证据三徽章（复刻题材龙头 tlRowHtml evid；读口透传，旧档缺→fail-visible）
        "evidenceIndustry": (built["evidence"].get("industry") or {}).get("name"),
        "evidenceBoardResolved": bool(built["evidence"].get("boardResolved")),
        "evidenceKwordTags": list(built["evidence"].get("kwordTags") or []),
        "narrative": narrative, "questionsRaw": questions,
        "answers": answers, "modelAnswers": raw_answers, "gate": gate,
        "auctionSealToday": seal.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "auctionSealProbabilities": seal.get("probabilities") if doc_kind == DOC_KIND_LEADER else None,
        "leaderCatalystHardness": hard.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "auctionSeatDurability": seat.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "trialSettlementPattern": tpat.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "trialSettlementProbabilities": tpat.get("probabilities") if doc_kind == DOC_KIND_LEADER else None,
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
    push_rows = [{"code": str(s.get("code")), "name": s.get("name"),
                  "board": s.get("board"), "pct": s.get("pct")}
                 for s in (push or {}).get("stocks") or [] if s.get("code")]
    prev_dates = trading_dates_before(db, date, 2, dataset_id)
    prev_date = prev_dates[-1] if prev_dates else None
    # A4e 双源选龙（2026-11-14 裁决 B1–B3）：推送 ∪ jiuyan T−1 龙一/二/三（封板 ≥3 家）
    jrows, jstate = jiuyan_dragon_roster(db, prev_date)
    fetch_failed = (push_meta or {}).get("pushState") == "fetch_failed"
    if not push_rows and not jrows:
        reason = (push_meta or {}).get("reason") or "auction_push_missing"
        print(f"{date} 选龙双源均缺席（推送: {reason}；jiuyan: {jstate.get('reason') or '无达标龙股'}），"
              "跳过打标（fail-visible，不兜底选龙）")
        return {"ok": not fetch_failed, "date": date, "leaders": 0,
                "skippedReason": "auction_push_missing",
                "errorCode": "auction_push_fetch_failed" if fetch_failed else None,
                "auctionPushState": push_meta, "jiuyanDragonState": jstate}
    if fetch_failed:
        # B3：瞬时取数失败即使 jiuyan 源在场也先重试（不吃掉推送样本）；重试耗尽当日双源皆失
        print(f"{date} 竞价推送取数失败，交退避重试（jiuyan 源 {len(jrows)} 股待重试后合并）")
        return {"ok": False, "date": date, "leaders": 0,
                "skippedReason": "auction_push_missing",
                "errorCode": "auction_push_fetch_failed",
                "auctionPushState": push_meta, "jiuyanDragonState": jstate}
    # 并集去重（B6）：推送股保留 pct/概念桥映射，龙序并列披露；jiuyan 单源股 pct=None
    by_code: dict[str, dict] = {}
    for s in push_rows:
        by_code[s["code"]] = {**s, "selectionSources": [SOURCE_PUSH], "dragonRoles": []}
    overlap_n = 0
    for jr in jrows:
        cur = by_code.get(jr["code"])
        if cur is not None:
            overlap_n += 1
            cur["selectionSources"].append(SOURCE_JIUYAN_DRAGON)
            cur["dragonRoles"] = jr["dragonRoles"]
            if not cur.get("name"):
                cur["name"] = jr.get("name")
        else:
            by_code[jr["code"]] = {"code": jr["code"], "name": jr.get("name"),
                                   "board": jr["board"], "pct": None,
                                   "selectionSources": [SOURCE_JIUYAN_DRAGON],
                                   "dragonRoles": jr["dragonRoles"],
                                   "_dragonPrimary": True}
    rows = list(by_code.values())
    selection = {"pushN": len(push_rows), "jiuyanN": len(jrows),
                 "overlapN": overlap_n, "unionN": len(rows)}
    if not push_rows:
        print(f"{date} 推送验证后缺席（{(push_meta or {}).get('reason')}），"
              f"跑 jiuyan 单源 {len(jrows)} 股（B3，auctionPushState 留痕）")
    # 2026-11-13 用户裁决（二次修订）：板块归属取 jiuyan 打标链 **T−1 涨停分组**
    # 板块名（产业树成分反查映射不上，作废）；无命中回退推送概念 + boardSource 留痕
    bctx = ABM.load_board_context(db, prev_date)
    for r in rows:
        if r.pop("_dragonPrimary", False):
            # B6：jiuyan 单源股板块 = 龙序主板（封板家数降序→组名升序，已定序）
            r["pushBoard"] = None
            r["boardSource"] = ABM.SOURCE_JIUYAN
            r["boardMapping"] = {"pickedBy": "dragon_t1",
                                 "candidates": [{"name": x["board"], "n": x["sealedN"]}
                                                for x in r["dragonRoles"]],
                                 "t1Final": True, "t1Date": prev_date}
            continue
        res = ABM.resolve_leader_board(bctx, r["code"], r.get("board"))
        r["board"] = res["board"]
        r["pushBoard"] = res["pushBoard"]
        r["boardSource"] = res["boardSource"]
        r["boardMapping"] = {"pickedBy": res["pickedBy"],
                             "candidates": res["candidates"],
                             "t1Final": res["t1Final"],
                             "t1Date": prev_date}
    excluded = [r for r in rows if r["board"] and digest.is_not_a_theme(r["board"])]
    if excluded:
        print(f"{date} 排除非题材行政桶 {len(excluded)} 只（{'、'.join(sorted({r['board'] for r in excluded}))}）——仅日志留痕")
        rows = [r for r in rows if not (r["board"] and digest.is_not_a_theme(r["board"]))]
    if codes:
        rows = [r for r in rows if r["code"] in codes]
    if not rows:
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders",
                "selection": selection, "jiuyanDragonState": jstate}
    rows.sort(key=lambda r: (str(r.get("board") or ""), -(r.get("pct") or 0)))
    # 一次取数全日共用（与题材链同哲学；T−1 语料 + 当日竞价）
    from backend.operations.jev_label_jiuyan import market_facts_line
    market_line = market_facts_line(db, prev_date, dataset_id) if prev_date else None
    t1_rows: dict[str, dict] = {}
    if prev_date:
        t1_all, _meta = day_leader_rows(db, prev_date, dataset_id,
                                        prev_date=prev_dates[-2] if len(prev_dates) > 1 else None,
                                        space_mode=True, pool_dates=prev_dates)
        for r in t1_all or []:
            t1_rows[str(r.get("code"))] = r
    pool_prev = fetch_pool_quality(db, prev_date) if prev_date else {"items": {}, "degraded": "no_prev_date"}
    # P1 交叉源（2026-11-14b）：韭研+THS 封板二分（题材链单一实现复用，纯 DB 读
    # 零外呼）；THS 缺/取数失败 → sealed=None 回退池单源旧口径 + prevPoolCross 留痕
    prev_cross: dict = {"sealed": None, "info": {}, "state": "no_prev_date"}
    streak_map: dict = {}
    if prev_date:
        try:
            _s, _i, _m = sealed_and_info(db, prev_date)
            prev_cross = {"sealed": _s, "info": _i,
                          "state": "ok" if _s is not None else "ths_missing"}
        except Exception as exc:  # noqa: BLE001 — 交叉源失败不阻断投喂
            prev_cross = {"sealed": None, "info": {}, "state": f"fetch_failed:{exc}"}
        try:
            streak_map = jiuyan_streak_map(db, prev_date) or {}
        except Exception:  # noqa: BLE001 — 连板补全失败不阻断（streak 缺位省略）
            streak_map = {}
    lanes = fetch_daban_lanes(db, date)
    # 竞昨比原料（腾讯日K，按日 12h 缓存与页面共享；≤入选股数/日（双源 roster）、
    # 单股失败 10min 退避——红线 9 预算见 vA2 预登记 §6）；dry-run 零外呼
    basis_map: dict = {}
    basis_state = "dry_run_skipped" if dry_run else "missing"
    if not dry_run:
        try:
            bp = get_daban_prev_day_basis(date, [r["code"] for r in rows])
            basis_map = bp.get("basis") or {}
            basis_state = "ok" if basis_map else "missing"
        except Exception as exc:   # noqa: BLE001 原料失败不阻断投喂（竞昨比缺席）
            basis_state = f"fetch_failed:{exc}"
    # 竞价榜外补源（2026-11-13 用户裁决：KPL 竞价榜非全市场）：腾讯竞价快照，
    # 仅 09:25–09:30 窗口、仅榜外缺码、单条批量 URL；失败不阻断（榜外照旧缺席）
    bid_items = lanes.get("bid") or {}
    bid_supplement = "skipped_dry_run" if dry_run else "skipped_out_of_window"
    if not dry_run and _in_auction_window():
        missing = [r["code"] for r in rows if r["code"] not in bid_items]
        if missing:
            try:
                sup = get_auction_snapshot_tencent(missing)
                for c, it in (sup.get("items") or {}).items():
                    bid_items[c] = it
                bid_supplement = "tencent_auction" if sup.get("items") else "sup_missing"
            except Exception as exc:   # noqa: BLE001 补源失败不阻断
                bid_supplement = f"fetch_failed:{exc}"
    if bid_items:
        lanes["bid"] = bid_items   # 写回（lanes 假件可能无 bid 键：保证注入传播）
    # 试盘源采集（2026-11-14c 定案接线，勘察 §6 合同；WzsLinker api-auction.php）：
    # 仅 09:25–09:30 窗（试盘行已定格，与 bid 补源同窗）、裸读≤1 + 陈旧补拉≤1（红线 9
    # 台账 §6.4）；dry-run 零外呼；actual_date 守卫在解析层（回退数据不得冒充当日）
    trial_state: dict = {"state": "skipped_dry_run" if dry_run else "skipped_out_of_window"}
    trial_rows: dict = {}
    if not dry_run and _in_auction_window():
        try:
            tr = fetch_auction_trial(date)
            trial_rows = tr.get("rows") or {}
            trial_state = {k: tr[k] for k in ("state", "saved_at", "fetched", "n_rows",
                                              "actual_date", "message") if tr.get(k) is not None}
            trial_state["attempts"] = tr.get("attempts") or []
            # 全量 raw 日档落库（2026-11-14 用户裁决，§4.0 原始记录自持）：仅 ok 态写，
            # 空档也是事实；persistState 进 trialState（fail-visible）
            if tr.get("state") == "ok":
                trial_state["persistState"] = persist_trial_raw(db, date, tr)
        except Exception as exc:   # noqa: BLE001 试盘失败不阻断投喂（整行缺席留痕）
            trial_state = {"state": f"fetch_failed:{exc}"}
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
    push_entries = (push or {}).get("entries") or []
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
                base_rate_stats=base_rate_stats, push_entries=push_entries,
                basis_map=basis_map, basis_state=basis_state,
                prev_cross=prev_cross))
    built_leaders: list[dict] = []
    for r in todo:
        board = str(r.get("board") or "未归属")
        # 〇 重跑语料冻结（2026-11-14b）：单只重跑（codes+force）复用晨间原件
        # narrative/corpusState，防盘后重跑用当日 final 重建注入 look-ahead
        # （天普 11-13 21:10 重跑教训）；全日 force 不受影响（有意重建）
        frozen_doc = col.find_one({"_id": f"{date}:{r['code']}"}) if (codes and force) else None
        trow = trial_rows.get(r["code"])
        trial = ({"row": trow, "source": "wzslinker_auction",
                  "fetchedAt": trial_state.get("saved_at"),
                  "prevPercentCross": None} if trow else None)
        built = build_one(db, date, prev_date, r,
                          t1_row=t1_rows.get(r["code"]), pool_prev=pool_prev,
                          lanes=lanes, gene_corpus=gene_corpus,
                          notice_corpus=notice_corpus, heat_corpus=heat_corpus,
                          reason_corpus=reason_corpus, lhb_facts=lhb_facts,
                          market_line=market_line, base_rate_stats=base_rate_stats,
                          basis_map=basis_map, basis_state=basis_state,
                          bid_supplement=bid_supplement,
                          sector_judgment=sector_answers.get(board),
                          board_codes=by_board.get(board, [r]),
                          prev_cross=prev_cross, streak_map=streak_map,
                          trial=trial)
        if (frozen_doc and frozen_doc.get("status") == "ok"
                and frozen_doc.get("narrative")):
            built["narrative"] = frozen_doc["narrative"]
            built["corpusState"] = frozen_doc.get("corpusState") or built["corpusState"]
            built["corpusFrozen"] = True
            built["chars"] = len(built["narrative"])
            built["estimatedTokens"] = estimate_tokens(built["chars"])
        else:
            # runner 级 trialState：有试盘行=骨架 ok 态上叠采集观测；无行= runner 态
            # （skipped_dry_run / skipped_out_of_window / fetch_failed / fallback / no_row）
            if trial is not None:
                built["corpusState"]["trialState"] = {
                    **(built["corpusState"].get("trialState") or {}), **trial_state}
            else:
                built["corpusState"]["trialState"] = (
                    {**trial_state, "state": "no_row"}
                    if trial_state.get("state") == "ok" else trial_state)
        built["auctionPushState"] = {"source": push_meta.get("source"),
                                     "entryN": len(push_entries),
                                     "reason": push_meta.get("reason")}
        # 推送行注入（全日共用 entries；个股级只列自身）
        push_txt = auction_push_line(push_entries, codes=[r["code"]])
        if push_txt and not built.get("corpusFrozen"):
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
                "docs": len(built_all), "estimatedTokens": est,
                "selection": selection, "jiuyanDragonState": jstate}
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
        if not b.get("corpusFrozen"):
            # 冻结叙事已含晨间注入，不二次注入；仍须重判（重跑=冻结语料+新判答）
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
              "selection": selection, "jiuyanDragonState": jstate,
              "questionSetVersion": QUESTION_SET_VERSION_AUCTION_LEADER}
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="竞价龙头晨间投喂（vA2）")
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