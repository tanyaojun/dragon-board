# -*- coding: utf-8 -*-
"""竞价龙头读口/重跑 API 合同测试（零 jev / 零网络；FakeDb 注入）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api import hotlist_jev_auction_routes as R
from backend.data.repositories import repository_factory

DATE = "2026-11-13"


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in (query or {}).items():
                val = d.get(k)
                if isinstance(v, dict):
                    if "$gte" in v and not (val is not None and val >= v["$gte"]):
                        ok = False
                    if "$lte" in v and not (val is not None and val <= v["$lte"]):
                        ok = False
                elif val != v:
                    ok = False
            if ok:
                out.append(dict(d))
        return FakeCursor(out)

    def find_one(self, query=None, projection=None, **kw):
        for d in self.find(query):
            return d
        return None


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb()
    col = db[R.COLLECTION]
    col.docs[f"{DATE}:603135"] = {
        "_id": f"{DATE}:603135", "tradingDate": DATE, "docKind": "leader",
        "code": "603135", "name": "中重科技", "board": "机器人", "auctionPct": 3.0,
        "auctionSealToday": "mid_45_65", "auctionSealProbabilities": {"mid_45_65": 0.6},
        "status": "ok", "questionSetVersion": "vA1", "narrative": "叙事全文",
        "questionsRaw": {"auction_leader_seal_today": {}},
        "answers": {"auction_leader_seal_today": {"choice": "mid_45_65", "confidence": 0.7}},
        "outcomeSealedToday": None, "computedAt": "2026-11-13T09:26:00.000"}
    col.docs[f"{DATE}:board:机器人"] = {
        "_id": f"{DATE}:board:机器人", "tradingDate": DATE, "docKind": "sector",
        "board": "机器人", "status": "ok",
        "answers": {"theme_speculation_depth": {"choice": "fermenting"},
                    "theme_continuation": {"choice": "weak_extend"}}}
    db[R.LIVE_COLLECTION].docs[DATE] = {
        "_id": DATE, "auctionPush": {"stocks": [
            {"code": "603135", "name": "中重科技", "board": "机器人", "pct": 3.0},
            {"code": "600327", "name": "大东方", "board": "大消费", "pct": -8.64}]}}
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app), db


def test_get_single_date_merges_sector_and_roster(client):
    c, db = client
    r = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE})
    doc = r.json()
    assert doc["ok"] and not doc.get("no_data")
    rows = {x["code"]: x for x in doc["leaders"]}
    assert rows["603135"]["choice"] == "mid_45_65"
    assert rows["603135"]["themeSpeculationDepth"] == "fermenting"
    assert rows["603135"]["labelMissing"] is False
    assert rows["600327"]["labelMissing"] is True     # 推送 roster 缺档行披露
    assert doc["nodeFilter"]["labelMissingRows"] == 1
    assert doc["sectorCount"] == 1


def test_get_with_narrative(client):
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders",
                params={"date": DATE, "with_narrative": 1}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["narrative"] == "叙事全文"
    assert "auction_leader_seal_today" in row["questionsRaw"]


def test_get_range_and_no_data(client):
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders",
                params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert doc["ok"] and len(doc["leaders"]) == 2
    empty = c.get("/api/hotlist-jev/auction-leaders", params={"date": "2026-11-12"}).json()
    assert empty["no_data"] is True


def test_rerun_missing_token(client):
    c, db = client
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"})
    assert r.json()["errorCode"] == "missing_token"


def test_rerun_bad_payload(client):
    c, db = client
    import os
    os.environ["JEV_CF_TOKEN"] = "x"
    try:
        r = c.post("/api/hotlist-jev/auction-leaders/rerun", json={"date": "", "code": ""})
        assert r.json()["errorCode"] == "bad_payload"
    finally:
        del os.environ["JEV_CF_TOKEN"]

def test_rerun_success_summary_and_force(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    seen = {}

    def fake_run(date, **kw):
        seen.update(kw)
        db[AL.COLLECTION].docs[f"{date}:603135"]["computedAt"] = "2026-11-13T09:30:00.000"
        return {"leaders": 1, "okCount": 2, "degraded": 0, "tokensUsed": 240}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["ok"] and r["summary"]["labeled"] == 1 and r["summary"]["okCount"] == 2
    assert seen["force"] is True and seen["codes"] == {"603135"}
    assert seen["sample_origin"] == "live"


def test_rerun_not_rerun_when_computedAt_stale(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    monkeypatch.setattr(AL, "run", lambda date, **kw: {"leaders": 0})
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["errorCode"] == "not_rerun"


def test_rerun_not_written(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")

    def fake_run(date, **kw):
        db[AL.COLLECTION].docs.pop(f"{date}:603135", None)
        return {"leaders": 0}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["errorCode"] == "not_written"


def test_rerun_backfill_origin_passthrough(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    db[AL.COLLECTION].docs[f"{DATE}:603135"]["sampleOrigin"] = "backfill"
    seen = {}

    def fake_run(date, **kw):
        seen.update(kw)
        db[AL.COLLECTION].docs[f"{date}:603135"]["computedAt"] = "2026-11-13T09:31:00.000"
        return {"leaders": 1, "okCount": 1}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["ok"] and seen["sample_origin"] == "backfill"


def test_no_param_500_cap_truncated(client):
    c, db = client
    col = db[R.COLLECTION]
    col.docs.pop(f"{DATE}:board:机器人", None)   # sector 档占帽会让 leader 窗=499
    for i in range(501):
        code = f"{i:06d}"
        col.docs[f"{DATE}:{code}"] = {
            "_id": f"{DATE}:{code}", "tradingDate": DATE, "docKind": "leader",
            "code": code, "name": f"股{i}", "board": "机器人", "status": "ok"}
    doc = c.get("/api/hotlist-jev/auction-leaders").json()
    assert doc["truncated"] is True
    labeled = [r for r in doc["leaders"] if not r.get("labelMissing")]
    assert len(labeled) == 500


def test_legacy_doc_auction_pct_joined_from_bid_lane(client):
    """2026-11-14 修复：旧档（auctionPct=推送实时 pct）读口 join bid 通道 bidding_pct。"""
    c, db = client
    db["kpl_daban_pool"].docs[DATE] = {
        "_id": DATE, "bid_date": DATE,
        "bid_items": [{"stock_id": "603135", "bidding_pct": 5.5, "pct": 3.0}]}
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["auctionPct"] == 5.5       # 真竞价值（bid 通道 join）
    assert row["realtimePct"] == 3.0      # 原 auctionPct（推送实时）转 realtimePct


def test_legacy_doc_no_bid_lane_auction_pct_none(client):
    """旧档无 bid 通道档 → 竞价涨幅 None（fail-visible，不拿实时冒充）。"""
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["auctionPct"] is None
    assert row["realtimePct"] == 3.0


def test_new_doc_auction_pct_stored_direct(client):
    """新档（含 realtimePct）→ 直读落库 auctionPct/realtimePct，不再 join。"""
    c, db = client
    d = db[R.COLLECTION].docs[f"{DATE}:603135"]
    d["auctionPct"] = 6.2
    d["realtimePct"] = 3.0
    # 即便 bid 通道给了不同值，新档以落库为准
    db["kpl_daban_pool"].docs[DATE] = {
        "_id": DATE, "bid_items": [{"stock_id": "603135", "bidding_pct": 9.9}]}
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["auctionPct"] == 6.2
    assert row["realtimePct"] == 3.0


def test_evidence_fields_exposed(client):
    """事件列证据字段透传（复刻题材龙头）。"""
    c, db = client
    d = db[R.COLLECTION].docs[f"{DATE}:603135"]
    d["evidenceIndustry"] = "机器人产业"
    d["evidenceBoardResolved"] = True
    d["evidenceKwordTags"] = ["减速器", "伺服"]
    d["evidenceEventTitles"] = ["某事件"]
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["evidenceIndustry"] == "机器人产业"
    assert row["evidenceBoardResolved"] is True
    assert row["evidenceKwordTags"] == ["减速器", "伺服"]
    assert row["evidenceEventTitles"] == ["某事件"]


def test_legacy_evidence_reconstructed(client, monkeypatch):
    """旧档事件列证据三徽章读口重建（单一事实源 build_theme_evidence_block）。"""
    c, db = client
    from backend.analysis.hotlist import theme_event_digest as digest
    calls = []
    def fake_block(db_, *, board_name, date, leader_code=None, **kw):
        calls.append((board_name, date))
        return {"industry": {"name": "机器人产业"}, "boardResolved": True,
                "kwordTags": ["减速器"], "events": [], "news": []}
    monkeypatch.setattr(digest, "build_theme_evidence_block", fake_block)
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["evidenceIndustry"] == "机器人产业"
    assert row["evidenceBoardResolved"] is True
    assert row["evidenceKwordTags"] == ["减速器"]
    assert calls, "旧档应触发证据重建"


def test_new_doc_evidence_no_reconstruction(client, monkeypatch):
    """新档（含 evidenceKwordTags）直读落库，不触发读口重建。"""
    c, db = client
    d = db[R.COLLECTION].docs[f"{DATE}:603135"]
    d["realtimePct"] = 3.0
    d["evidenceIndustry"] = "存储产业"
    d["evidenceBoardResolved"] = True
    d["evidenceKwordTags"] = ["芯片"]
    from backend.analysis.hotlist import theme_event_digest as digest
    def boom(*a, **k):
        raise AssertionError("新档不应触发证据重建")
    monkeypatch.setattr(digest, "build_theme_evidence_block", boom)
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["evidenceIndustry"] == "存储产业"
    assert row["evidenceKwordTags"] == ["芯片"]


def test_legacy_evidence_reconstruction_failure_fail_visible(client, monkeypatch):
    """证据重建失败 → 三字段 None/[]，不阻断读口（fail-visible）。"""
    c, db = client
    from backend.analysis.hotlist import theme_event_digest as digest
    def boom(*a, **k):
        raise RuntimeError("corpus read boom")
    monkeypatch.setattr(digest, "build_theme_evidence_block", boom)
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    assert doc["ok"]
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["evidenceIndustry"] is None
    assert row["evidenceKwordTags"] == []


def test_pct_normalization_legacy_and_new(client):
    """评审 M2：空串/非数字 bidding_pct 与落库值两分支统一归一 None（不 coerce 成 0）。"""
    c, db = client
    # 旧档：bid 通道 bidding_pct 为空串 → auctionPct=None（垫后，非 0）
    db["kpl_daban_pool"].docs[DATE] = {
        "_id": DATE, "bid_items": [{"stock_id": "603135", "bidding_pct": ""}]}
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["auctionPct"] is None
    assert row["realtimePct"] == 3.0
    # 新档：落库 auctionPct 空串 / realtimePct 非数字串 → 双双 None
    d = db[R.COLLECTION].docs[f"{DATE}:603135"]
    d["auctionPct"] = ""
    d["realtimePct"] = "abc"
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["auctionPct"] is None
    assert row["realtimePct"] is None


def test_roster_row_contract_alignment(client):
    """评审 M1：推送 roster 缺档行 auctionPct=None、realtimePct=推送 pct（合同统一）。"""
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "600327")
    assert row["labelMissing"] is True
    assert row["auctionPct"] is None        # 不拿推送实时 pct 冒充竞价涨幅
    assert row["realtimePct"] == -8.64


# ── 第三源：竞价试盘强度 roster 行源（2026-11-15 预登记）──────────────────

def _seed_trial_day(db, date=DATE):
    """§7.17 raw 退役：试盘日种子=官方序列档（4 股两帧撤减，与原 raw 同值形态）。"""
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()
    db["jiuyan_industry_stocks"].docs["node:机器人"] = {
        "_id": "node:机器人", "name": "机器人", "stockN": 4, "batchDate": "2026-10-25",
        "stocks": [{"code": c} for c in ("600100", "600101", "600102", "600103")]}
    db["stock_names"].docs["600100"] = {"code": "600100", "name": "甲"}
    db["stock_names"].docs["600102"] = {"code": "600102", "name": "丙"}
    _seed_trial_series(db, date)


def test_get_trial_roster_labelmissing(client):
    """行源 ∪ trial roster：未打标强度候选出 labelMissing 行 + 源/trialStrength 透传。"""
    c, db = client
    _seed_trial_day(db)
    try:
        doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
        assert doc["ok"]
        rows = {x["code"]: x for x in doc["leaders"]}
        assert rows["600102"]["labelMissing"] is True
        assert rows["600102"]["selectionSources"] == ["auction_trial_strength"]
        assert rows["600102"]["board"] == "机器人"
        assert rows["600102"]["trialStrength"]["rank"] == 1
        assert rows["600102"]["trialStrength"]["jjtier"] == "mid50_95"
        assert rows["600102"]["name"] == "丙"
        assert "600103" not in rows                    # 每板前三
        # 推送缺档 600327 + 3 trial = 4；已打标 603135 不重复
        assert doc["nodeFilter"]["labelMissingRows"] == 4
        assert "trialRosterError" not in doc["nodeFilter"]
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_get_trial_roster_failure_fail_visible(client, monkeypatch):
    """trial roster 计算失败 → trialRosterError 留痕，labels/推送 roster 不受阻。"""
    c, db = client
    from backend.analysis.hotlist import auction_strength as AS
    _seed_trial_day(db)

    def boom(*a, **k):
        raise RuntimeError("trial roster boom")
    monkeypatch.setattr(AS, "trial_strength_roster", boom)
    try:
        doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
        assert doc["ok"]
        assert "trial roster boom" in doc["nodeFilter"]["trialRosterError"]
        rows = {x["code"]: x for x in doc["leaders"]}
        assert rows["603135"]["labelMissing"] is False
        assert rows["600327"]["labelMissing"] is True
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_trial_strength_passthrough_labeled_doc(client):
    """已打标 trial 源 doc：selectionSources/trialStrength 直读透传。"""
    c, db = client
    d = db[R.COLLECTION].docs[f"{DATE}:603135"]
    d["selectionSources"] = ["auction_push", "auction_trial_strength"]
    d["trialStrength"] = {"boardAmt": 2.4e8, "btier": "中热 2-5亿", "jjRatio": 70.0,
                          "jjtier": "mid50_95", "posture": "decrease", "rank": 3,
                          "boardTrialN": 4}
    doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["selectionSources"] == ["auction_push", "auction_trial_strength"]
    assert row["trialStrength"]["rank"] == 3


def test_trial_merge_into_push_missing_row(client):
    """推送缺档行同时是 trial 候选 → 合并源标签 + trialStrength（N3 同款）。"""
    c, db = client
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()
    db["jiuyan_industry_stocks"].docs["node:大消费"] = {
        "_id": "node:大消费", "name": "大消费", "stockN": 3, "batchDate": "2026-10-25",
        "stocks": [{"code": c} for c in ("600327", "600400", "600401")]}
    pcts = {"600327": 7.0, "600400": 8.0, "600401": 9.0}
    ticks = []
    for hm, zb in (("09:16:00", 1e7), ("09:24:00", 5e6)):
        ticks.append({"ts": _cst_ts(DATE, hm), "it": [
            {"s": c, "bidding_pct": jp, "bidding_amount": 8e7,
             "bidding_turnover": 1.0, "zt_buy_amount": zb} for c, jp in pcts.items()]})
    db["kpl_bidding_series"].docs[DATE] = {
        "_id": DATE, "ticks": ticks, "updated_at": f"{DATE}T09:26:09+08:00"}
    try:
        doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
        rows_out = {x["code"]: x for x in doc["leaders"]}
        r = rows_out["600327"]
        assert r["labelMissing"] is True
        assert r["selectionSources"] == ["auction_push", "auction_trial_strength"]
        assert r["trialStrength"]["rank"] == 3
        assert doc["nodeFilter"]["labelMissingRows"] == 3   # 600327 合并 + 2 纯 trial
    finally:
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


# ── 竞价试盘日档读口（§7.14 迁链；2026-11-18 §7.17 raw 整集合退役→单主链）──
# 单主链三态 + 日期索引 + 回退 + 行情补全，全 FakeDb 零网络零 jev。

def _cst_ts(date: str, hm: str) -> float:
    from datetime import datetime, timedelta, timezone
    h, m, s = (int(x) for x in hm.split(":"))
    return datetime.strptime(date, "%Y-%m-%d").replace(
        hour=h, minute=m, second=s, tzinfo=timezone(timedelta(hours=8))).timestamp()


def _seed_trial_series(db, date=DATE, codes=None):
    """官方序列档：两帧（首帧委买 1e7 → 末帧 5e6 撤减）。codes 默认 4 股。"""
    pcts = {"600100": 7.0, "600101": 8.0, "600102": 9.0, "600103": 6.5}
    use = codes or list(pcts)
    ticks = []
    for hm, zb in (("09:16:00", 1e7), ("09:24:00", 5e6)):
        ticks.append({"ts": _cst_ts(date, hm), "it": [
            {"s": c, "bidding_pct": pcts.get(c, 5.0), "bidding_amount": 6e7,
             "bidding_turnover": 1.2, "zt_buy_amount": zb,
             "price": 10.0, "pct": pcts.get(c, 5.0), "real_float": 5e9} for c in use]})
    db["kpl_bidding_series"].docs[date] = {
        "_id": date, "date": date, "ticks": ticks,
        "updated_at": f"{date}T09:26:09+08:00", "window": ["09:15:00", "09:27:00"]}


def test_auction_trial_derived_single_main_chain(client):
    """§7.17 raw 退役 → 官方序列派生单主链（无历史档回退）。"""
    c, db = client
    _seed_trial_series(db)
    try:
        doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
        assert doc["ok"] and not doc.get("degraded")
        d = doc["doc"]
        assert d["source"] == "kpl_bidding_series_derived"
        assert set(d["rows"]) == {"600100", "600101", "600102", "600103"}
        assert d["nRows"] == 4
        assert d["savedAt"] == f"{DATE}T09:26:09+08:00"
        assert doc["trialState"]["state"] == "ok"
        # 派生行观测值字段在场、无源字段如实缺席（不补 0）
        r = d["rows"]["600102"]
        assert r["first_amount"] == 1e7 and r["last_amount"] == 5e6
        assert r["start_time"] == "09:16:00" and r["end_time"] == "09:24:00"
        assert r["first_add"] is None      # 仅撤减帧，无追加委买
        assert r["price"] == 10.0 and r["percent"] == 9.0
        assert r["circulated_value"] == 5e9
        assert r["pre_percent"] is None    # 昨涨幅无零外呼本地源
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_both_absent_degraded(client):
    """全源无档 → 结构化降级（不伪装成功/不伪造 0）。"""
    c, _db = client
    doc = c.get("/api/hotlist-jev/auction-trial").json()
    assert doc["ok"] and doc["degraded"] and doc["doc"] is None
    assert doc["dates"] == []


def test_auction_trial_latest_series_index(client):
    """日期索引=series；无 date 取最新有档日。"""
    c, db = client
    _seed_trial_day(db, DATE)
    _seed_trial_series(db, "2026-11-18", codes=["600102"])
    try:
        doc = c.get("/api/hotlist-jev/auction-trial").json()
        assert doc["dates"] == [DATE, "2026-11-18"]
        assert doc["doc"]["tradingDate"] == "2026-11-18"
        assert doc["doc"]["source"] == "kpl_bidding_series_derived"
        assert set(doc["doc"]["rows"]) == {"600102"}
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_date_fallback_earlier(client):
    """请求日双源皆缺 → 向更早有用日回退并 dateFallback 透出（不冒充当日）。"""
    c, db = client
    _seed_trial_day(db, DATE)
    try:
        doc = c.get("/api/hotlist-jev/auction-trial",
                    params={"date": "2026-11-18"}).json()
        assert doc["dateFallback"] == {"requested": "2026-11-18", "served": DATE}
        assert doc["doc"]["tradingDate"] == DATE
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_partial_fields_not_zeroed(client):
    """部分股末帧委买额缺位 → 该股如实缺席，其余股照显（不连带清空/不补 0）。"""
    c, db = client
    _seed_trial_series(db, codes=["600102", "600900"])
    ticks = db["kpl_bidding_series"].docs[DATE]["ticks"]
    for it in ticks[-1]["it"]:
        if it["s"] == "600900":
            del it["zt_buy_amount"]
    try:
        doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
        assert set(doc["doc"]["rows"]) == {"600102"}
        assert doc["trialState"]["state"] == "ok"
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_no_date_fallback_when_today_empty(client):
    """评审 M1：最新日序列档零可用行（委买全 0）→ 无 date 也回退历史档，不吞数据。"""
    c, db = client
    _seed_trial_day(db, DATE)
    db["kpl_bidding_series"].docs["2026-11-18"] = {
        "_id": "2026-11-18", "ticks": [{"ts": _cst_ts("2026-11-18", "09:16:00"),
        "it": [{"s": "600102", "zt_buy_amount": 0}]}],
        "updated_at": "2026-11-18T09:26:09+08:00"}
    try:
        doc = c.get("/api/hotlist-jev/auction-trial").json()
        assert doc["ok"] and not doc.get("degraded")
        assert doc["dateFallback"] == {"requested": "2026-11-18", "served": DATE}
        assert doc["doc"]["tradingDate"] == DATE
        assert doc["trialState"]["source"] == "kpl_bidding_series_derived"
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_derive_exception_degraded(client, monkeypatch):
    """§7.17 无回退：derive 抛异常 → 结构化降级 derive_failed 留痕，不伪装。"""
    c, db = client
    _seed_trial_day(db)
    from backend.operations import auction_trial_derive as D

    def boom(*a, **k):
        raise RuntimeError("derive boom")
    monkeypatch.setattr(D, "derive_trial_rows_from_series", boom)
    doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
    assert doc["degraded"] and doc["doc"] is None
    assert doc["trialState"]["state"] == "derive_failed:RuntimeError"


def test_auction_trial_both_absent_trialstate(client):
    """评审 m4：双缺降级断言 trialState 在场 + reason 结构化。"""
    c, _db = client
    doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
    assert doc["degraded"] and doc["doc"] is None
    assert doc["trialState"]["state"] == "absent"
    assert doc["trialState"]["reason"] == "no_series_archive"
    assert DATE in doc["reason"]


def test_auction_trial_fallback_to_series_day(client):
    """评审 m4：跨日回退命中更早日为 series 派生（源序不变）。"""
    c, db = client
    _seed_trial_day(db, DATE)
    _seed_trial_series(db, "2026-11-17", codes=["600102"])
    try:
        doc = c.get("/api/hotlist-jev/auction-trial",
                    params={"date": "2026-11-18"}).json()
        assert doc["dateFallback"] == {"requested": "2026-11-18", "served": "2026-11-17"}
        assert doc["doc"]["source"] == "kpl_bidding_series_derived"
        assert set(doc["doc"]["rows"]) == {"600102"}
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_quote_supplement_join(client, monkeypatch):
    """昨涨幅=落库独立源 join；现价=实时快照 join；仅补缺位+miss 计数透出。"""
    c, db = client
    _seed_trial_series(db)
    for t in db["kpl_bidding_series"].docs[DATE]["ticks"]:
        for it in t["it"]:
            it.pop("price", None)   # 实测 pid=8 price 列空 → 派生 price=None
    db["kpl_bidding_series"].docs[DATE]["prev_pct"] = {
        "600102": {"pct": 5.5}, "600100": {"pct": -1.2}}
    monkeypatch.setattr(R, "read_realtime_prices",
                        lambda codes: ({"600102": {"price": 12.5}}, 1794965169000))
    try:
        doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
        rows = doc["doc"]["rows"]
        assert rows["600102"]["pre_percent"] == 5.5
        assert rows["600100"]["pre_percent"] == -1.2
        assert rows["600102"]["price"] == 12.5
        assert rows["600101"]["price"] is None
        assert doc["prevPctMissCount"] == 2
        assert doc["priceMissCount"] == 3
        assert doc["priceFetchedAtMs"] == 1794965169000
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_trial_quote_supplement_error_trace(client, monkeypatch):
    """补全读失败 → quoteSupplementError 留痕，主读口不阻断。"""
    c, db = client
    _seed_trial_series(db)

    def boom(codes):
        raise RuntimeError("redis boom")
    monkeypatch.setattr(R, "read_realtime_prices", boom)
    try:
        doc = c.get("/api/hotlist-jev/auction-trial", params={"date": DATE}).json()
        assert doc["ok"] and doc["doc"]
        assert "redis boom" in doc["quoteSupplementError"]
    finally:
        from backend.services.jev import jiuyan_board, jiuyan_industry_root
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_auction_leaders_trial_supplement_series_primary(client):
    """auction-leaders trial 缺档补行同源序：官方序列派生单主链（§7.17）。"""
    c, db = client
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    _seed_trial_day(db)
    try:
        doc = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE}).json()
        rows = {x["code"]: x for x in doc["leaders"]}
        assert rows["600102"]["trialStrength"]["rank"] == 1
        assert rows["600102"]["selectionSources"] == ["auction_trial_strength"]
    finally:
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()
