# -*- coding: utf-8 -*-
"""题材龙头弹药镜像命中管道诊断（只读：不写库、不调 jev、不修 upstream）。

背景（2026-11-04 归因，见 docs/hotlist-jev/theme-leader-seal-attribution-20261104.md）：
  live 龙头行的 `evidenceEventTitles` 自 2026-10-30 起全空、`evidenceNewsTitles`
  11-02 上线后非空率低、Kword 标签覆盖 11/61——需要区分三层根因：
    A. 采集层：kpl_theme_* 事件/新闻池当日无数据；
    B. 匹配层：池有料但 match_kpl_events/news 对板块零命中（关键词/子串锚问题）；
    C. 落库层：当日命中非零但 evidence*Titles 镜像为空（写库链路问题）。

方法：
  1) 逐日取 corpus_state + 事件/新闻/日历池当日窗内池量（与 build_theme_evidence_block
     同窗口参数：事件回看 3 日、新闻回看 2 日、日历未来 3 日）；
  2) 逐龙头行回放 `digest.build_theme_evidence_block`（零网络零模型，同 v4 口径），
     将回放命中数与当日落库镜像对比，逐行判 A/B/C；
  3) 回放用的是**当前**库存量（窗口相对 date 计算，源集合为滚动窗时旧日期可能低估），
     结论以「当日落库镜像 + 当日 state」为主、回放为辅，delta 显式披露不掩盖。

产物：
  data/reports/theme-leader/ammo-mirror-audit-20261104.json（逐日/逐行明细 + 汇总）
用法：
  .venv/Scripts/python.exe -m backend.operations.diagnose_theme_ammo_hits \
      [--start 2026-10-23] [--end 2026-11-03] [--out data/reports/theme-leader/…json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.analysis.hotlist import theme_event_digest as digest
from backend.operations import kpl_theme_store as KS
from backend.operations.theme_leader_seal_stats import LEADER_COLLECTION

EVENT_PAST, NEWS_PAST, CAL_WINDOW = 3, 2, 3   # 与 build_theme_evidence_block 默认窗一致


def classify_zero(persisted: int, replay: int, pool: int) -> str:
    """零命中根因分类：pool=0 → 采集层；池有料回放异常 → 回放层；池有料回放零命中 →
    匹配层；回放命中但落库 0 → 落库层。review 2026-11-05：回放异常不得并入 B（防 B 虚增）。"""
    if persisted > 0:
        return "ok"
    if pool <= 0:
        return "A_pool_empty"
    if replay < 0:
        return "replay_error"
    if replay <= 0:
        return "B_match_zero"
    return "C_persist_zero"


def diagnose_row(db, doc: dict) -> dict:
    date = str(doc.get("tradingDate"))
    board = str(doc.get("board") or "")
    code = str(doc.get("code") or "")
    persisted_events = len(doc.get("evidenceEventTitles") or [])
    persisted_news = len(doc.get("evidenceNewsTitles") or [])
    persisted_kword = len(doc.get("evidenceKwordTags") or [])
    try:
        block = digest.build_theme_evidence_block(
            db, board_name=board, date=date, leader_code=code,
            sealed_codes=None, include_l2=True)
        replay_events = len(block.get("events") or [])
        replay_news = len(block.get("news") or [])
        replay_kword = len(block.get("kwordTags") or [])
        match = block.get("match") or {}
        board_resolved = bool(block.get("boardResolved"))
        err = None
    except Exception as exc:  # noqa: BLE001 — 回放失败显式记录，不中断整体诊断（fail-visible）
        replay_events = replay_news = replay_kword = -1
        match, board_resolved, err = {}, None, str(exc)
    return {
        "date": date, "code": code, "board": board,
        "segment": doc.get("segment"),
        "ver": str(doc.get("questionSetVersion")),
        "persisted": {"events": persisted_events, "news": persisted_news,
                      "kword": persisted_kword,
                      "boardResolved": doc.get("evidenceBoardResolved"),
                      "stale": bool((doc.get("evidenceState") or {}).get("stale"))},
        "replay": {"events": replay_events, "news": replay_news, "kword": replay_kword,
                   "boardResolved": board_resolved,
                   "industryMatched": match.get("matched"),
                   "industryMethod": match.get("method"), "error": err},
        "zeroCause": {
            "events": classify_zero(persisted_events, replay_events, -1),
            "news": classify_zero(persisted_news, replay_news, -1),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="题材龙头弹药镜像命中管道诊断（只读）")
    ap.add_argument("--start", default="2026-10-23")
    ap.add_argument("--end", default="2026-11-03")
    ap.add_argument("--mongo", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="dragon_board_quant")
    ap.add_argument("--out", default="data/reports/theme-leader/ammo-mirror-audit.json")
    args = ap.parse_args()

    db = MongoClient(args.mongo)[args.db]
    docs = list(db[LEADER_COLLECTION].find(
        {"docKind": {"$ne": "sector"}, "leaderSuperseded": {"$ne": True},
         "sampleOrigin": "live", "status": {"$ne": "skipped"},
         "tradingDate": {"$gte": args.start, "$lte": args.end}}))
    if not docs:
        print(f"区间 {args.start}~{args.end} 无 live 龙头行（采集未跑或区间早于投产日）",
              file=sys.stderr)
        return 1

    # 逐日池量（当日窗口径，独立于逐行回放）
    dates = sorted({str(d.get("tradingDate")) for d in docs})
    pools: dict[str, dict] = {}
    for date in dates:
        state = digest.corpus_state(db, date=date)
        pools[date] = {
            "state": {k: state.get(k) for k in
                      ("ok", "stale", "latestFetchDate", "industry", "topic", "news", "calendar")},
            "poolEvents": len(KS.get_topic_events(db, date=date,
                                                  include_past_recent=EVENT_PAST, window_days=1)),
            "poolNews": len(KS.get_news_items(db, date=date,
                                              include_past_recent=NEWS_PAST, window_days=1)),
            "poolCalendar": len(KS.get_calendar_items(db, date=date, window_days=CAL_WINDOW)),
        }

    rows = [diagnose_row(db, d) for d in docs]
    for r in rows:
        p = pools.get(r["date"]) or {}
        for k in ("events", "news"):
            r["zeroCause"][k] = classify_zero(
                r["persisted"][k],
                r["replay"][k], p.get("poolEvents" if k == "events" else "poolNews") or 0)

    # 汇总：逐日 A/B/C 分布 + 板块映射失败行
    by_date: dict[str, dict] = {}
    for date in dates:
        g = [r for r in rows if r["date"] == date]
        by_date[date] = {
            "rows": len(g),
            "pool": pools.get(date),
            "persistedEventHitRows": sum(1 for r in g if r["persisted"]["events"] > 0),
            "persistedNewsHitRows": sum(1 for r in g if r["persisted"]["news"] > 0),
            "replayEventHitRows": sum(1 for r in g if r["replay"]["events"] > 0),
            "replayNewsHitRows": sum(1 for r in g if r["replay"]["news"] > 0),
            "industryUnmatchedRows": sum(1 for r in g if r["replay"]["industryMatched"] is False),
            "kwordCoveredRows": sum(1 for r in g if r["persisted"]["kword"] > 0),
            "staleRows": sum(1 for r in g if r["persisted"]["stale"]),
            "eventsZeroCause": dict(defaultdict(int, {
                c: sum(1 for r in g if r["zeroCause"]["events"] == c)
                for c in {r["zeroCause"]["events"] for r in g}})),
            "newsZeroCause": dict(defaultdict(int, {
                c: sum(1 for r in g if r["zeroCause"]["news"] == c)
                for c in {r["zeroCause"]["news"] for r in g}})),
        }
    causes = ("events", "news")
    summary = {
        "range": {"start": args.start, "end": args.end},
        "rows": len(rows),
        "overallZeroCause": {k: dict(defaultdict(int, {
            c: sum(1 for r in rows if r["zeroCause"][k] == c)
            for c in {r["zeroCause"][k] for r in rows}})) for k in causes},
        "industryUnmatchedRows": sum(1 for r in rows if r["replay"]["industryMatched"] is False),
        "replayErrorRows": sum(1 for r in rows if r["replay"]["error"]),
        "persistReplayDeltaRows": sum(
            1 for r in rows if r["replay"]["error"] is None and (
                r["replay"]["events"] != r["persisted"]["events"]
                or r["replay"]["news"] != r["persisted"]["news"])),
    }
    report = {"summary": summary, "byDate": by_date, "rows": rows}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"summary": summary, "byDate": by_date}, ensure_ascii=False, indent=2))
    print(f"[saved] {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
