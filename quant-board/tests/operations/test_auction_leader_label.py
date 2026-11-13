# -*- coding: utf-8 -*-
"""竞价龙头 runner 测试（vA1；零真实 jev / 零网络，AGENTS §1.2-7）。

锁定口径：dry-run 零调用零写入；无 --confirm-budget 实跑被预算护栏挡（SystemExit）；
幂等（ok 档不重烧）；推送缺席 → skippedReason + 零调用（不兜底选龙）；
单只 force 重跑只重建命中股；锚行随已结算样本滚动（防 look-ahead）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_leader_label as L

DATE = "2026-11-13"


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def update_one(self, flt, update, upsert=False):
        d = self.docs.setdefault(flt["_id"], {"_id": flt["_id"]})
        d.update(update.get("$set") or {})

    def find(self, query=None, projection=None):
        return [dict(d) for d in self.docs.values()
                if all(d.get(k) == v for k, v in (query or {}).items())]

    def find_one(self, query=None, projection=None, **kw):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (query or {}).items()):
                return dict(d)
        return None

    def count_documents(self, query=None):
        return len(self.find(query))


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _push(db, stocks=None):
    db["kpl_live_daily"].docs[DATE] = {
        "_id": DATE, "items": [],
        "auctionPush": {"entries": [{"time": "09:15", "comment": "竞价看龙头：机器人中重科技",
                                     "stocks": [{"code": "603135", "name": "中重科技",
                                                 "pct": 3.0, "board": "机器人",
                                                 "boardRaw": "机器人"}]}],
                        "stocks": stocks or [{"code": "603135", "name": "中重科技",
                                              "pct": 3.0, "board": "机器人",
                                              "boardRaw": "机器人"}],
                        "parseState": {"entryN": 1, "unmatchedSegments": [],
                                       "unassignedCodes": []}}}


@pytest.fixture()
def env(monkeypatch):
    db = FakeDb()
    _push(db)
    monkeypatch.setattr(L, "_db", lambda: db)
    monkeypatch.setattr(L.digest, "build_theme_evidence_block",
                        lambda *a, **k: {"text": "题材证据块：测试", "state": {},
                                         "events": [], "news": []})
    monkeypatch.setattr(L, "collect_lhb_facts",
                        lambda date: {"ok": True, "groups": [], "stocks": []})
    monkeypatch.setattr(L, "apply_evidence_gate",
                        lambda answers, evidence, keys=None, prob_key=None: (
                            answers, {"applied": False}))
    calls = []

    def fake_dispatch(narrative, questions):
        calls.append((narrative, tuple(questions)))
        return {"fake": True}, 12

    def fake_parse(env_, ms, expected_keys=None):
        return {"ok": True, "model": "fake", "usage": {"input_tokens": 100, "output_tokens": 20},
                "answers": {k: {"choice": "mid_45_65" if k == "auction_leader_seal_today"
                                else ("hard_fact" if k == "leader_catalyst_hardness"
                                      else ("core_seat" if k == "auction_seat_durability"
                                            else "fermenting")),
                                "confidence": 0.7,
                                "probabilities": {"mid_45_65": 0.6}}
                            for k in (expected_keys or ())}}

    monkeypatch.setattr(L, "_dispatch_jev", fake_dispatch)
    monkeypatch.setattr(L, "parse_jev_response", fake_parse)
    return db, calls


def test_dry_run_zero_calls(env):
    db, calls = env
    res = L.run(DATE, dry_run=True)
    assert res["ok"] and res["dryRun"]
    assert calls == []
    assert db[L.COLLECTION].docs == {}


def test_budget_guard_blocks_real_run(env):
    db, calls = env
    with pytest.raises(SystemExit):
        L.run(DATE)
    assert calls == []


def test_push_missing_skips_zero_calls(env):
    db, calls = env
    db["kpl_live_daily"].docs[DATE]["auctionPush"]["stocks"] = []
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"] and res["skippedReason"] == "auction_push_missing"
    assert calls == []


def test_fire_writes_docs_and_idempotent(env):
    db, calls = env
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"] and res["okCount"] == 2      # 1 板块 + 1 个股
    col = db[L.COLLECTION]
    leader = col.docs[f"{DATE}:603135"]
    sector = col.docs[f"{DATE}:board:机器人"]
    assert leader["docKind"] == "leader" and leader["status"] == "ok"
    assert leader["auctionSealToday"] == "mid_45_65"
    assert leader["questionSetVersion"] == "vA1"
    assert leader["outcomeSealedToday"] is None
    assert "竞价看龙头推送：" in leader["narrative"]
    assert sector["docKind"] == "sector"
    assert sector["themeSpeculationDepth"] == "fermenting"
    n = len(calls)
    res2 = L.run(DATE, confirm_budget=True)
    assert len(calls) == n                        # 幂等：ok 档不重烧
    assert res2["leaders"] == 0


def test_single_code_force_rerun(env):
    db, calls = env
    L.run(DATE, confirm_budget=True)
    before = db[L.COLLECTION].docs[f"{DATE}:603135"]["computedAt"]
    n = len(calls)
    import time as _t
    _t.sleep(0.005)   # computedAt 毫秒位防同毫秒误报
    L.run(DATE, confirm_budget=True, force=True, codes={"603135"})
    # force 含板块 doc 重标（v12 同款）：命中股 + 其板块 = 2 调用，非整日
    assert len(calls) == n + 2
    assert db[L.COLLECTION].docs[f"{DATE}:603135"]["computedAt"] != before


def test_base_rate_anchor_lookahead_safe(env):
    db, calls = env
    col = db[L.COLLECTION]
    col.docs["2026-11-13:600001"] = {
        "_id": "2026-11-13:600001", "tradingDate": "2026-11-13", "docKind": "leader",
        "status": "ok", "sampleOrigin": "live", "outcomeSealedToday": True}
    col.docs["2026-11-14:600002"] = {
        "_id": "2026-11-14:600002", "tradingDate": "2026-11-14", "docKind": "leader",
        "status": "ok", "sampleOrigin": "live", "outcomeSealedToday": True}
    stats = L.auction_seal_base_rate(db, before="2026-11-14")
    assert stats["n"] == 1                        # 当日及以后结算不得入锚（防 look-ahead）
    res = L.run(DATE, dry_run=True)
    assert res["ok"]


def _load_eval_module():
    import importlib.util
    p = Path(__file__).resolve().parents[2] / "scripts" / "auction_leader_pilot_eval.py"
    spec = importlib.util.spec_from_file_location("auction_leader_pilot_eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_settle_writes_outcome_from_pool(monkeypatch):
    E = _load_eval_module()
    db = FakeDb()
    db[E.COLLECTION].docs[f"{DATE}:603135"] = {
        "_id": f"{DATE}:603135", "tradingDate": DATE, "docKind": "leader",
        "code": "603135", "outcomeSealedToday": None}
    monkeypatch.setattr(E, "_db", lambda: db)
    monkeypatch.setattr(E, "sealed_sets", lambda db_, date: ({"603135"}, {"603135"}))
    res = E.write_outcome(db, DATE)
    assert res["settled"] == 1 and res["crossMismatch"] == 0
    doc = db[E.COLLECTION].docs[f"{DATE}:603135"]
    assert doc["outcomeSealedToday"] is True and doc["outcomeSource"] == "daban_pool"
    assert doc["outcomeCross"] is True

def test_skip_fetch_failed_retries_vs_verified_missing(env, monkeypatch):
    """review major-5：晨间取数失败 ok=False 交退避重试；验证后缺席 ok=True 零调用。"""
    db, calls = env
    monkeypatch.setattr(L, "roster_for", lambda db, date, fetch_missing=True: (
        None, {"pushState": "fetch_failed", "reason": "fetch_failed: boom"}))
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"] is False and res["errorCode"] == "auction_push_fetch_failed"
    assert calls == []
    monkeypatch.setattr(L, "roster_for", lambda db, date, fetch_missing=True: (
        None, {"reason": "auction_push_missing_history"}))
    res2 = L.run(DATE, confirm_budget=True)
    assert res2["ok"] is True and res2["skippedReason"] == "auction_push_missing"


def test_sealed_prev_caliber():
    """review major-3：broken 炸板≠封板；健康查无此股=False；degraded=None。"""
    healthy = {"items": {"600001": {"item": {"pool_state": "sealed"}},
                         "600002": {"item": {"pool_state": "broken"}}}, "degraded": None}
    assert L._sealed_prev(healthy, healthy["items"]["600001"]) is True
    assert L._sealed_prev(healthy, healthy["items"]["600002"]) is False
    assert L._sealed_prev(healthy, {}) is False
    assert L._sealed_prev({"items": {}, "degraded": "pool_empty"}, {}) is False
    assert L._sealed_prev({"items": {}, "degraded": "no_archive"}, {}) is None


def test_gate_forces_seal_probabilities(env, monkeypatch):
    """review minor：证据门强制 insufficient 时封板题概率分布与 gate 元数据不失真。"""
    db, calls = env
    from backend.analysis.hotlist.theme_leader_ammo import apply_evidence_gate as real_gate
    monkeypatch.setattr(L, "apply_evidence_gate", real_gate)
    monkeypatch.setattr(L.digest, "build_theme_evidence_block",
                        lambda *a, **k: {"text": "题材证据块：测试", "state": {},
                                         "events": [], "news": [],
                                         "evidenceMissing": True,
                                         "evidenceMissingReason": "corpus_not_collected"})
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    seal = doc["answers"]["auction_leader_seal_today"]
    assert seal["choice"] == "insufficient"
    assert seal["probabilities"] == {"insufficient": 1.0}
    assert doc["gate"]["modelChoice"] == "mid_45_65"
    assert doc["auctionSealProbabilities"] == {"insufficient": 1.0}


def test_sample_origin_auto_backfill_for_history(env):
    """review minor：历史日补跑默认 backfill（防混入 live 锚人群）；当日 live。"""
    import copy
    db, calls = env
    past = "2026-11-12"
    db["kpl_live_daily"].docs[past] = {
        **copy.deepcopy(db["kpl_live_daily"].docs[DATE]), "_id": past}
    res = L.run(past, confirm_budget=True)
    assert res["ok"]
    assert db[L.COLLECTION].docs[f"{past}:603135"]["sampleOrigin"] == "backfill"
    L.run(DATE, confirm_budget=True)
    assert db[L.COLLECTION].docs[f"{DATE}:603135"]["sampleOrigin"] == "live"


def test_codes_selfheal_degraded_sector(env):
    """review nit：龙头全 ok + 板块 degraded 时 --codes 不带 force 也自愈板块档。"""
    db, calls = env
    L.run(DATE, confirm_budget=True)
    col = db[L.COLLECTION]
    col.docs[f"{DATE}:board:机器人"]["status"] = "degraded"
    n = len(calls)
    L.run(DATE, confirm_budget=True, codes={"603135"})
    assert col.docs[f"{DATE}:board:机器人"]["status"] == "ok"
    assert len(calls) == n + 1


def test_board_mapping_jiuyan_override(env, monkeypatch):
    """2026-11-13 用户裁决（二次修订）：板块归属取 T−1 涨停分组名；推送概念事实并列。"""
    db, calls = env
    monkeypatch.setattr(L, "trading_dates_before", lambda *a, **k: ["2026-11-11", "2026-11-12"])
    db["jiuyan_action"].docs["2026-11-12:final"] = {
        "_id": "2026-11-12:final",
        "fields": [{"name": "机器人", "stocks": [{"code": "603135"}, {"code": "600001"}]},
                   {"name": "大消费", "stocks": [{"code": "603135"}]}]}
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert doc["board"] == "机器人" and doc["pushBoard"] == "机器人"
    assert doc["boardSource"] == "jiuyan_action_t1"
    assert doc["boardMapping"]["pickedBy"] == "push_bridge"   # 推送桥优先于组大小
    assert doc["boardMapping"]["t1Date"] == "2026-11-12"
    assert "板块归属：机器人" in doc["narrative"]
    assert f"{DATE}:board:机器人" in db[L.COLLECTION].docs
    sec = db[L.COLLECTION].docs[f"{DATE}:board:机器人"]
    assert sec["boardSources"] == ["jiuyan_action_t1"]
    assert sec["segmentRows"][0]["pushBoard"] == "机器人"


def test_board_mapping_t1_missing_fallback(env, monkeypatch):
    """T−1 final 缺席 → 回退推送概念 + pickedBy=t1_final_missing 留痕（不伪造）。"""
    db, calls = env
    monkeypatch.setattr(L, "trading_dates_before", lambda *a, **k: ["2026-11-11", "2026-11-12"])
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert doc["board"] == "机器人" and doc["boardSource"] == "push_concept"
    assert doc["boardMapping"]["pickedBy"] == "t1_final_missing"
    assert doc["boardMapping"]["t1Final"] is False
