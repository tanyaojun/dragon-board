# -*- coding: utf-8 -*-
"""竞价龙头晨间投喂 runner（vA2，预登记 auction-leader-vA2-preregistration-20261114）。

定位：每条投喂 = 当日选龙双源并集的一只个股（A4e：09:15「竞价看龙头」推送 ∪
jiuyan T−1 涨停分组龙一/二/三，官方封板口径 ≥3 家，2026-11-14 用户裁决 B1–B3）；
2026-11-15 起第三源并集补充：竞价试盘强度板块前三（严格档：中热 2-5亿 ×
mid50_95 × 撤减，root 粗桶口径，仅 leader doc；预登记
auction-leader-trial-strength-source-preregistration-20261115）；
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
    auction_board_strength_line,
    auction_board_structure_line,
    auction_push_line,
    auction_structure_line,
    auction_trial_line,
    auction_trial_selection_line,
    build_auction_leader_narrative,
    build_auction_sector_narrative,
)
from backend.analysis.hotlist.auction_strength import trial_strength_roster
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
    popularity_rank_line,
    regulatory_risk_line,
    sector_judgment_line,
    theme_heat_line,
    zt_gene_line,
)
from backend.operations.auction_bidding_direct import (
    collect_auction_bidding_direct)
from backend.operations.auction_trial_derive import derive_trial_rows_from_series
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
    fetch_regulatory_corpus,
    fetch_theme_heat,
    regulatory_entries_for_codes,
    _regulatory_state,
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
SOURCE_PUSH = "auction_push"
# 已退役第二源（2026-11-15 用户裁决：实测封板概率极低）；仅历史档 selectionSources 读取用
SOURCE_JIUYAN_DRAGON = "jiuyan_dragon_t1"
# 第三源（2026-11-15 预登记 auction-leader-trial-strength-source）：竞价试盘强度
# 板块前三（严格档：中热 2-5亿 × mid50_95 × 撤减，root 粗桶口径）
SOURCE_TRIAL_STRENGTH = "auction_trial_strength"
BOARD_SOURCE_TRIAL = "jiuyan_root_trial"
# 第三源每日软上限（可配；dry-run 实测校准写入预登记；超限全局 jj_ratio 降序截断记账）
TRIAL_STRENGTH_MAX_PER_DAY = 6


def source_bucket(selection_sources: list | None) -> str:
    """锚人群构成桶（互斥优先级）：auction_push > auction_trial_strength > 退役 jiuyan。

    trial 桶 = 仅竞价强度源股；vA1 旧档无 selectionSources 按推送计（单一事实源，
    锚计算与 pilot eval 构成披露共用）。vA4：推送/强度优先于已退役 jiuyan，
    重叠历史档归入存活源；jiuyan 单源历史档返回退役桶（锚不计入）。"""
    srcs = selection_sources or [SOURCE_PUSH]
    if SOURCE_PUSH in srcs:
        return SOURCE_PUSH
    if SOURCE_TRIAL_STRENGTH in srcs:
        return SOURCE_TRIAL_STRENGTH
    return SOURCE_JIUYAN_DRAGON


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
    n_push = n_trial = 0
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
        bucket = source_bucket(d.get("selectionSources"))
        if bucket == SOURCE_JIUYAN_DRAGON:
            continue   # 退役 jiuyan 单源历史档不计入锚（vA4）
        n += 1
        ok += 1 if outcome else 0
        if bucket == SOURCE_TRIAL_STRENGTH:
            n_trial += 1
        else:
            n_push += 1
        dates.append(date)
    if not n:
        return None
    return {"n": n, "rate": ok * 100.0 / n, "nPush": n_push,
            "nTrial": n_trial, "start": min(dates), "end": max(dates)}


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


def _bidding_series_line_for(db: Any, date: str, code: str,
                             state_out: dict | None = None) -> str | None:
    """竞价过程事实行（kpl_bidding_series 派生；纯库读零外呼；缺档/异常=None 整行缺席）。

    state_out 缺席原因结构化透出（§4.0：缺席与缺档不可静默合并）：
    no_series_archive=当日无序列档 / stock_absent=序列档无该股 /
    series_read_failed:*=读口异常。
    """
    try:
        from backend.analysis.hotlist.auction_leader_ammo import bidding_series_line
        from backend.services.kpl_daban_archiver import (
            derive_stock_series_facts, load_bidding_series)
        sdoc = load_bidding_series(db, date)
        if not sdoc:
            if state_out is not None:
                state_out["state"] = "no_series_archive"
            return None
        facts_all = derive_stock_series_facts(sdoc.get("ticks") or [])
        line = bidding_series_line(facts_all.get(str(code)[-6:]))
        if state_out is not None:
            state_out["state"] = "ok" if line else "stock_absent"
        return line
    except Exception as exc:  # noqa: BLE001 — 语料行缺席不阻断投喂；原因进 corpusState
        if state_out is not None:
            state_out["state"] = f"series_read_failed:{type(exc).__name__}"
        return None


def build_one(db: Any, date: str, prev_date: str | None, row: dict,
              *, t1_row: dict | None, pool_prev: dict, lanes: dict, mbl_state: dict | None = None,
              gene_corpus: dict, notice_corpus: dict, heat_corpus: dict,
              reason_corpus: dict, lhb_facts: dict | None,
              base_rate_stats: dict | None,
              sector_judgment: dict | None, board_codes: list[str],
              basis_map: dict | None = None, basis_state: str = "missing",
              bid_supplement: str | None = None,
              prev_cross: dict | None = None, streak_map: dict | None = None,
              trial: dict | None = None, reg_corpus: dict | None = None,
              trial_strength: dict | None = None) -> dict:
    """个股级投喂组装（零网络零模型）：T−1 语料 + 当日竞价 + 推送行。

    trial = 试盘源载荷（增量2 骨架，合同定案前恒 None → trialState=contract_pending，
    叙事无试盘行；定案后 = {"row": 盯盘试盘行具名字段, "source", "fetchedAt",
    "prevPercentCross"}，由晨间窗内采集器單股传入）。
    trial_strength = 第三源 trialStrength 载荷（仅 trial 源 leader 传入；root 口径
    两新行，双源 leader 恒 None 叙事不变）。"""
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
    # 监管风险行（2026-11-15 预登记）：T−1 收盘档 reg_by_code，scope 同龙虎榜行
    reg_entries = regulatory_entries_for_codes(lhb_codes, lhb_roles, reg_corpus or {})
    reg_line = regulatory_risk_line(reg_entries)
    block = digest.build_theme_evidence_block(
        db, board_name=board or "", date=date, leader_code=code, sealed_codes=None,
        l2_fallback_date=prev_date, leader_expound_chars=1200, include_morning=True,
        include_flash=True)
    series_state: dict = {}
    # 2026-11-18a：涨停原因/热度排名共用条目（同源 reason_corpus，零新采集）
    reason_entries = reason_entries_for_leaders(rows, reason_corpus)
    narrative = build_auction_leader_narrative(
        date=date, prev_date=prev_date,
        leader_name=str(row.get("name") or ""), leader_code=code, board=board,
        push_board=row.get("pushBoard"),
        push_line=None,   # 推送行由 run() 注入（全日共用 entries，个股级只列自身）
        bid_line=auction_bid_line(bid_entries),
        trial_line=auction_trial_line((trial or {}).get("row")),
        bidding_series_line=_bidding_series_line_for(db, date, code, series_state),
        board_strength=auction_board_strength_line(board, trial_strength),
        trial_selection=auction_trial_selection_line(trial_strength),
        structure=auction_structure_line(facts, prev_date=prev_date),
        ladder_line=_auction_ladder_line(t1_row, prev_date),
        base_rate=auction_base_rate_line(base_rate_stats),
        sector_judgment=sector_judgment_line(sector_judgment),
        theme_heat_line=theme_heat_line(theme_heat_entries_for_leaders(rows, heat_corpus)),
        gene_line=zt_gene_line(gene_entries_for_leaders(rows, gene_corpus)),
        reason_line=limitup_reason_line(reason_entries),
        popularity_rank_line=popularity_rank_line(reason_entries),
        notice_count_line=notice_count_line(notice_entries_for_leaders(rows, notice_corpus)),
        regulatory_line=reg_line,
        lhb_facts_line=lhb_txt,
        evidence_block=block["text"])
    return {"docKind": DOC_KIND_LEADER, "row": row, "narrative": narrative,
            "evidence": block,
            # 真竞价涨幅（09:25 匹配价，bid 通道 bidding_pct；含腾讯榜外补源）——
            # 与推送芯片 pct（实时涨幅）严格分离，落库 auctionPct 取此值（2026-11-14 修复）
            "auctionBidPct": (bid_item or {}).get("bidding_pct"),
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "regulatoryState": _regulatory_state(reg_corpus or {}, reg_entries),
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
                            "flashDate": block.get("flashDate"),
                            "trialState": ({"state": "ok",
                                            "source": trial.get("source"),
                                            "fetchedAt": trial.get("fetchedAt"),
                                            "prevPercentCross": trial.get("prevPercentCross")}
                                           if trial else {"state": "contract_pending"}),
                            "mblState": mbl_state or None,
                            "seriesState": series_state or None},
            "chars": len(narrative), "estimatedTokens": estimate_tokens(len(narrative))}


def build_sector_one(db: Any, date: str, prev_date: str | None, board: str,
                     rows: list[dict], *, t1_rows: dict, pool_prev: dict,
                     lanes: dict, reason_corpus: dict, lhb_facts: dict | None,
                     market_line: str, base_rate_stats: dict | None,
                     push_entries: list[dict],
                     basis_map: dict | None = None, basis_state: str = "missing",
                     prev_cross: dict | None = None, reg_corpus: dict | None = None) -> dict:
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
    lhb_codes, lhb_roles = _lhb_codes_roles(codes, [(c, "入选龙头") for c in codes])
    lhb_txt = lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles) \
        if lhb_facts is not None else None
    if lhb_txt and prev_date:
        lhb_txt = lhb_txt.replace("龙虎榜：", f"龙虎榜（{prev_date} 榜单）：", 1)
    reg_entries = regulatory_entries_for_codes(lhb_codes, lhb_roles, reg_corpus or {})
    reg_line = regulatory_risk_line(reg_entries)
    block = digest.build_theme_evidence_block(
        db, board_name=board, date=date, leader_code=codes[0] if codes else "",
        sealed_codes=None, l2_fallback_date=prev_date, include_morning=True,
        include_flash=True)
    narrative = build_auction_sector_narrative(
        date=date, prev_date=prev_date, market_line=market_line,
        board=board,
        push_line=auction_push_line(push_entries, codes=codes),
        board_structure=auction_board_structure_line(members, prev_date=prev_date),
        bid_line=auction_bid_line(bid_entries),
        base_rate=auction_base_rate_line(base_rate_stats),
        reason_line=limitup_reason_line(reason_entries_for_leaders(rows, reason_corpus)),
        regulatory_line=reg_line,
        lhb_facts_line=lhb_txt,
        evidence_block=block["text"])
    return {"docKind": DOC_KIND_SECTOR, "rows": rows, "board": board,
            "narrative": narrative, "evidence": block,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_txt is not None),
            "regulatoryState": _regulatory_state(reg_corpus or {}, reg_entries),
            "corpusState": {"prevDate": prev_date, "bidLane": lanes.get("bidLane"),
                            "bidIn": any(str(r.get("code") or "") in bid_items
                                         for r in rows),   # review 2026-11-13f：板块级=任一成员在榜
                            "basisState": basis_state,
                            "prevPool": pool_prev.get("degraded"), "lhbDate": prev_date,
                            "morningState": block.get("morningState"),
                            "morningDate": block.get("morningDate"),
                            "flashState": block.get("flashState"),
                            "flashDate": block.get("flashDate")},
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
                                "sources": r.get("selectionSources")}
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
               # 第三源强度载荷（仅 trial 源股；读口/relay 徽章透传，旧档缺→None）
               "trialStrength": row.get("trialStrength"),
               # 竞价涨幅=bid 通道真竞价值（bidding_pct）；实时涨幅=推送芯片 pct。
               # 2026-11-14 修复：旧版把推送实时 pct 误存为 auctionPct（读口对历史档 join 兜底）
               "auctionPct": built.get("auctionBidPct"),
               "realtimePct": row.get("pct")}
    doc.update({
        "ammoVersion": AMMO_VERSION_AUCTION_LEADER,
        "questionSetVersion": QUESTION_SET_VERSION_AUCTION_LEADER,
        "questionSetHash": QUESTION_SET_HASH_AUCTION_LEADER,
        "lhbState": built.get("lhbState"),
        "regulatoryState": built.get("regulatoryState"),
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
    # 2026-11-18 bug 修复（广百案审计）：判答回写 built——run() 板块标注循环
    # 以 b.get("answers") 收集板块判答供龙头注入；此前不回写 → 恒 {} → 首跑
    # 龙头叙事板块判定行全链悬空（sectorJudgmentState 恒 sector_missing）。
    built["answers"] = answers
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    from backend.analysis.hotlist.jev_driver_ammo import _usage_tokens
    return bool(parsed["ok"]), _usage_tokens(parsed.get("usage"))


def run(date: str, *, dry_run: bool = False, confirm_budget: bool = False,
        max_leaders: int | None = None, force: bool = False,
        codes: set[str] | None = None, dataset_id: str = DEFAULT_DATASET_ID,
        sample_origin: str | None = None, trial_max: int | None = None) -> dict:
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
    # 选龙（vA4）：推送为基源 ∪ 竞价强度第三源（jiuyan 龙序源已退役 2026-11-15）
    fetch_failed = (push_meta or {}).get("pushState") == "fetch_failed"
    if not push_rows:
        reason = (push_meta or {}).get("reason") or "auction_push_missing"
        print(f"{date} 推送源缺席（{reason}），跳过打标（fail-visible，不兜底选龙；"
              "第三源不单独触发）")
        return {"ok": not fetch_failed, "date": date, "leaders": 0,
                "skippedReason": "auction_push_missing",
                "errorCode": "auction_push_fetch_failed" if fetch_failed else None,
                "auctionPushState": push_meta}
    if fetch_failed:
        # B3：瞬时取数失败先重试（不吃掉推送样本）
        print(f"{date} 竞价推送取数失败，交退避重试")
        return {"ok": False, "date": date, "leaders": 0,
                "skippedReason": "auction_push_missing",
                "errorCode": "auction_push_fetch_failed",
                "auctionPushState": push_meta}
    # 基源去重（B6）：推送股保留 pct/概念桥映射；第三源 trial 随后并集
    by_code: dict[str, dict] = {}
    for s in push_rows:
        by_code[s["code"]] = {**s, "selectionSources": [SOURCE_PUSH]}
    rows = list(by_code.values())
    selection = {"pushN": len(push_rows), "unionN": len(rows)}
    # 2026-11-13 用户裁决（二次修订）：板块归属取 jiuyan 打标链 **T−1 涨停分组**
    # 板块名（产业树成分反查映射不上，作废）；无命中回退推送概念 + boardSource 留痕
    bctx = ABM.load_board_context(db, prev_date)
    for r in rows:
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
        # 评审 P2-1（2026-11-15）：by_code 同步剔除——被排除双源行不得在第三源
        # overlap 判定中吞掉同 code 的合法 trial 候选（应作 trial_new 入并集）
        for r in excluded:
            by_code.pop(r["code"], None)
    if codes:
        rows = [r for r in rows if r["code"] in codes]
    # 评审 P1-2（2026-11-15）：codes 单股重跑时早退推迟到第三源并集之后——
    # trial-only 股不在双源名单，旧早退会截断其重跑；全日无 codes 路径语义不变
    if not rows and not codes:
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders",
                "selection": selection}
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
    # 试盘源（2026-11-17 正名，用户裁决）：**主链 = KPL socket 官方推送序列**
    # （pid=8 竞价池实时页，下方 trial_rows_from_series 即官方序列的试盘行加工层，
    # 主链一环）。WzsLinker（第三方非官方代理，11-16 实证故障）**已退役出链**：
    # 判据链零依赖；auction_trial_raw 已于 2026-11-18 整集合退役（§7.17，归档 backups）。
    # 竞价列表真源头直采（2026-11-16 MITM 定案合同：kaipanla.com MorningBiddingList
    # Type=4 PidType=0；与试盘 fetch 同窗一次，冻结态全量快照落 kpl_morning_bidding_raw）
    mbl_state: dict = {"state": "skipped_dry_run" if dry_run else "skipped_out_of_window"}
    if not dry_run and _in_auction_window():
        try:
            mbl_state = collect_auction_bidding_direct(db, date)
        except Exception as exc:  # noqa: BLE001 失败不阻断投喂（fail-visible）
            mbl_state = {"state": f"fetch_failed:{exc}"}
    trial_state: dict = {"state": "skipped_dry_run" if dry_run else "skipped_out_of_window"}
    trial_rows: dict = {}
    # 第三源自建派生（2026-11-16 item11：官方 socket 序列派生试盘字段，WzsLinker
    # 退役第一步）：序列档有委买额数据即用，零 WzsLinker 外呼（红线 9 预算）；
    # 纯库读，dry-run 亦可用（与 archive 回读同语义）
    try:
        derived_rows, derived_state = derive_trial_rows_from_series(db, date)
    except Exception as exc:  # noqa: BLE001 派生失败不阻断（fail-visible 留痕）
        derived_rows, derived_state = {}, {"state": f"derive_failed:{type(exc).__name__}"}
    if derived_rows:
        trial_rows = derived_rows
        trial_state = derived_state
    elif str(derived_state.get("state") or "").startswith("derive_failed"):
        trial_state = derived_state   # 派生异常留痕不丢（无回退后唯一审计面）
    # 2026-11-18 raw 退役（§7.17）：无历史档回退；序列缺席 → 第三源整源缺席
    # （fail-visible，双源不受影响，不兑底选龙）
    # 第三源选龙（严格档 + 每板前三；与读口共用 trial_strength_roster 单一实现）：
    # 中热 2-5亿 × mid50_95 × 撤减，root 粗桶；软上限 ≤6 只/日（超限截断记账）
    try:
        trows, tstate = trial_strength_roster(
            db, date, trial_rows,
            max_total=TRIAL_STRENGTH_MAX_PER_DAY if trial_max is None else trial_max)
    except Exception as exc:  # noqa: BLE001 — roster 失败不阻断双源打标（评审 P2-4，与读口 trialRosterError 对称）
        print(f"{date} 第三源 roster 计算失败：{exc}——双源继续（fail-visible）")
        trows, tstate = [], {"state": "absent",
                             "reason": f"roster_failed:{type(exc).__name__}: {exc}"}
    overlap_trial_n = 0
    trial_new: list[dict] = []
    for tr in trows:
        cur = by_code.get(tr["code"])
        if cur is not None:
            # 重叠股：追加源标签 + 强度载荷（保留基源 board/pct，叙事不变）
            if SOURCE_TRIAL_STRENGTH not in cur["selectionSources"]:
                cur["selectionSources"].append(SOURCE_TRIAL_STRENGTH)
            cur["trialStrength"] = tr["trialStrength"]
            overlap_trial_n += 1
        else:
            new = {"code": tr["code"], "name": tr.get("name"), "board": tr["board"],
                   "pct": None, "pushBoard": None,
                   "selectionSources": [SOURCE_TRIAL_STRENGTH],
                   "boardSource": BOARD_SOURCE_TRIAL,
                   "boardMapping": {"pickedBy": "trial_root_strength",
                                    "candidates": [{"name": tr["board"],
                                                     "n": tr["trialStrength"]["boardTrialN"]}]},
                   "trialStrength": tr["trialStrength"]}
            by_code[tr["code"]] = new
            trial_new.append(new)
    selection["trialN"] = len(trows)
    selection["overlapTrialN"] = overlap_trial_n
    if trial_new:
        rows.extend(trial_new)
        # 第三源同规：非题材行政桶剔除 + codes 过滤（双源行已处理，幂等）
        excluded_t = [r for r in trial_new
                      if r["board"] and digest.is_not_a_theme(r["board"])]
        if excluded_t:
            print(f"{date} 第三源排除非题材行政桶 {len(excluded_t)} 只（{'、'.join(sorted({r['board'] for r in excluded_t}))}）——仅日志留痕")
            rows = [r for r in rows if not (r.get("boardSource") == BOARD_SOURCE_TRIAL
                                            and r["board"]
                                            and digest.is_not_a_theme(r["board"]))]
        if codes:
            rows = [r for r in rows if r["code"] in codes]
        rows.sort(key=lambda r: (str(r.get("board") or ""), -(r.get("pct") or 0)))
        selection["unionN"] = len(rows)
    if not rows:
        # codes 单股重跑：双源与 trial 均未命中 → 保持 skip 语义（评审 P1-2）
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders",
                "selection": selection, "trialStrengthState": tstate}
    gene_corpus = fetch_gene_corpus(db, prev_date) if prev_date else {}
    notice_corpus = fetch_notice_corpus(db, prev_date) if prev_date else {}
    heat_corpus = fetch_theme_heat(db, prev_date) if prev_date else {}
    reason_corpus = fetch_reason_corpus(db, prev_date) if prev_date else {}
    # 监管风险语料（2026-11-15 预登记）：T−1 收盘档（17:00 槽），晨间投喂消费
    reg_corpus = (fetch_regulatory_corpus(db, prev_date) if prev_date
                  else {"byCode": {}, "laneOk": False, "reason": "no_prev_date", "states": {}})
    lhb_facts = None
    if prev_date:
        try:
            lhb_facts = collect_lhb_facts(prev_date)
        except Exception as exc:  # noqa: BLE001 — fail-visible 不阻断
            lhb_facts = {"ok": False, "degraded": True, "reason": f"fetch_failed: {exc}"}
    base_rate_stats = auction_seal_base_rate(db, before=date)
    push_entries = (push or {}).get("entries") or []
    by_board: dict[str, list[dict]] = {}
    by_board_trial: dict[str, list[dict]] = {}
    for r in rows:
        # 第三源隔离：trial（root 口径）不进双源 sector doc/peers，反之亦然
        # （同板竞价对比限同 boardSource 口径，预登记 §3）
        if r.get("boardSource") == BOARD_SOURCE_TRIAL:
            by_board_trial.setdefault(str(r.get("board") or "未归属"), []).append(r)
        else:
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
    # 第三源仅产 leader doc，不新增 sector doc（控预算、避板块口径 _id 冲突）
    todo_boards = ({str(r.get("board") or "未归属") for r in todo
                    if r.get("boardSource") != BOARD_SOURCE_TRIAL}
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
                prev_cross=prev_cross, reg_corpus=reg_corpus))
    built_leaders: list[dict] = []
    for r in todo:
        board = str(r.get("board") or "未归属")
        is_trial = r.get("boardSource") == BOARD_SOURCE_TRIAL
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
                          base_rate_stats=base_rate_stats,
                          basis_map=basis_map, basis_state=basis_state,
                          bid_supplement=bid_supplement,
                          sector_judgment=None if is_trial else sector_answers.get(board),
                          board_codes=(by_board_trial if is_trial else by_board).get(board, [r]),
                          prev_cross=prev_cross, streak_map=streak_map,
                          trial=trial, reg_corpus=reg_corpus,
                          mbl_state=mbl_state,
                          trial_strength=r.get("trialStrength") if is_trial else None)
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
            # 第三源选龙账（mapped/unmapped/selected/hotBoards）随档落库：
            # 原仅随 run() 返回值透传、历史不可追溯（2026-11-16 复盘代办⑤）
            built["corpusState"]["trialStrengthState"] = tstate
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
        # trial 龙头：root 板无 ABM 板块判答 → sector_missing（fail-visible，预登记 §3）
        built["sectorJudgmentState"] = (
            "sector_missing" if is_trial
            else ("injected" if sector_answers.get(board) else "sector_missing"))
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
                "selection": selection, "trialStrengthState": tstate}
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
        # trial 龙头不注入板块判答（root 板无 ABM 判答，sector_missing 恒态）
        if (not b.get("corpusFrozen")
                and (b.get("row") or {}).get("boardSource") != BOARD_SOURCE_TRIAL):
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
              "selection": selection, "trialStrengthState": tstate,
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
    ap.add_argument("--trial-max", type=int, default=None,
                    help="第三源每日软上限（缺省 6；超限全局 jj_ratio 降序截断记账）")
    ap.add_argument("--codes", default=None, help="逗号分隔单只重跑")
    ap.add_argument("--sample-origin", default=None, choices=["live", "backfill"],
                    help="缺省自动：当日 live / 历史日 backfill")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run(args.date, dry_run=args.dry_run or args.estimate,
                 confirm_budget=args.confirm_budget, force=args.force,
                 max_leaders=args.max_leaders,
                 codes=set(args.codes.split(",")) if args.codes else None,
                 sample_origin=args.sample_origin, trial_max=args.trial_max)
    # 标记行统一在 main 打（覆盖 skip/失败外全部返回路径；调度只认标记行）
    if not (args.dry_run or args.estimate):
        print(RESULT_MARKER + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()