# -*- coding: utf-8 -*-
"""竞价龙头 runner 测试（vA2；零真实 jev / 零网络，AGENTS §1.2-7）。

锁定口径：dry-run 零调用零写入；无 --confirm-budget 实跑被预算护栏挡（SystemExit）；
幂等（ok 档不重烧）；推送缺席 → skippedReason + 零调用（不兜底选龙）；
单只 force 重跑只重建命中股；锚行随已结算样本滚动（防 look-ahead）。
"""
from __future__ import annotations

import re
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
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in (query or {}).items():
                val = d.get(k)
                if isinstance(v, dict):
                    # 评审 P2（2026-11-15）：补齐 run() 查询面算子（$lt/$regex 供
                    # trading_dates_before 日轴，$ne/$nin/$exists 供承接链）；
                    # 未知算子显式 raise（旧版静默放行会掩盖日期边界/look-ahead bug）
                    for op, ov in v.items():
                        if op == "$gt":
                            ok = ok and (val is not None and val > ov)
                        elif op == "$gte":
                            ok = ok and (val is not None and val >= ov)
                        elif op == "$lt":
                            ok = ok and (val is not None and val < ov)
                        elif op == "$lte":
                            ok = ok and (val is not None and val <= ov)
                        elif op == "$in":
                            ok = ok and val in ov
                        elif op == "$nin":
                            ok = ok and val not in ov
                        elif op == "$ne":
                            ok = ok and val != ov
                        elif op == "$exists":
                            ok = ok and ((k in d) == bool(ov))
                        elif op == "$regex":
                            ok = ok and (isinstance(val, str)
                                         and re.search(ov, val) is not None)
                        else:
                            raise NotImplementedError(
                                f"FakeCol 未支持的查询算子：{op}（补齐而非静默放行）")
                elif val != v:
                    ok = False
            if ok:
                out.append(dict(d))
        return out

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
    # 离线护栏（review 2026-11-13f finding-3/4）：非补源专项用例默认窗外+假 basis，
    # 防止墙钟落在 09:25–09:30 或未 mock 时真连腾讯（qt/ifzq）；补源专项用例自行覆盖
    monkeypatch.setattr(L, "_in_auction_window", lambda: False)
    monkeypatch.setattr(L, "get_daban_prev_day_basis",
                        lambda date, codes: {"basis": {}, "missing": list(codes)})
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
    assert leader["questionSetVersion"] == "vA6"
    assert leader["outcomeSealedToday"] is None
    assert "竞价看龙头推送（09:15 试盘价）：" in leader["narrative"]
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
    """review major-3：broken 炸板≠封板；健康查无此股=False；degraded=None。
    2026-11-13f：pool_empty 亦归 None（降级不得事实化成「昨日未封板」，用户裁决）。"""
    healthy = {"items": {"600001": {"item": {"pool_state": "sealed"}},
                         "600002": {"item": {"pool_state": "broken"}}}, "degraded": None}
    assert L._sealed_prev(healthy, healthy["items"]["600001"]) is True
    assert L._sealed_prev(healthy, healthy["items"]["600002"]) is False
    assert L._sealed_prev(healthy, {}) is False
    assert L._sealed_prev({"items": {}, "degraded": "pool_empty"}, {}) is None
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
    """review minor：历史日补跑默认 backfill（防混入 live 锚人群）；当日 live。
    日期无关化（2026-11-14）：当日取墙钟今天，历史日用固定过去日 DATE。"""
    import copy
    import time as _t
    db, calls = env
    today = _t.strftime("%Y-%m-%d")
    assert today != DATE   # DATE 为固定历史日
    db["kpl_live_daily"].docs[today] = {
        **copy.deepcopy(db["kpl_live_daily"].docs[DATE]), "_id": today}
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    assert db[L.COLLECTION].docs[f"{DATE}:603135"]["sampleOrigin"] == "backfill"
    L.run(today, confirm_budget=True)
    assert db[L.COLLECTION].docs[f"{today}:603135"]["sampleOrigin"] == "live"


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


def test_bid_six_fields_with_ratio(env, monkeypatch):
    """竞价六件套入叙事（2026-11-13 用户裁决）：六字段 + 竞昨比派生 + 无占位噪声。"""
    db, calls = env
    db["kpl_daban_pool"].docs[DATE] = {
        "_id": DATE, "date": DATE, "bid_empty": False,
        "bid_items": [{"stock_id": "603135", "name": "中重科技",
                       "bidding_pct": 10.0, "bidding_net": 1e6,
                       "bidding_turnover": 1.0, "bidding_amount": 11e6,
                       "zt_buy_amount": 5e6}]}
    monkeypatch.setattr(L, "get_daban_prev_day_basis", lambda date, codes: {
        "ok": True, "date": date,
        "basis": {"603135": {"prev_close": 10.0, "prev_volume_shou": 20000.0}},
        "missing": []})
    L.run(DATE, confirm_budget=True)
    n = db[L.COLLECTION].docs[f"{DATE}:603135"]["narrative"]
    # 竞昨比 = (11e6/(10*1.1*100))/20000*100 = 50%
    assert "竞昨比 50.00%" in n and "涨停委买额 0.05亿" in n
    assert "竞价涨幅 +10.00%" in n and "不可考" not in n
    cs = db[L.COLLECTION].docs[f"{DATE}:603135"]["corpusState"]
    assert cs["bidIn"] is True and cs["basisState"] == "ok"


def test_bid_supplement_tencent_in_window(env, monkeypatch):
    """A4d：竞价榜外码 09:25–09:30 窗内经腾讯补源入叙事；bidSource/bidSupplement 留痕。"""
    db, calls = env
    monkeypatch.setattr(L, "_in_auction_window", lambda: True)
    monkeypatch.setattr(L, "get_auction_snapshot_tencent", lambda codes: {
        "ok": True, "items": {"603135": {"source": "tencent_auction",
                                         "bidding_pct": 10.0, "bidding_net": 1e6,
                                         "bidding_turnover": 1.0,
                                         "bidding_amount": 11e6,
                                         "zt_buy_amount": 5e6}},
        "missing": []})
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert "竞昨比" in doc["narrative"] or "竞价涨幅 +10.00%" in doc["narrative"]
    cs = doc["corpusState"]
    assert cs["bidIn"] is True and cs["bidSource"] == "tencent_auction"
    assert cs["bidSupplement"] == "tencent_auction"


def test_bid_supplement_out_of_window_no_fake(env, monkeypatch):
    """窗外不补：榜外股竞价行整行缺席（不拿盘中最价冒充竞价）。"""
    db, calls = env
    monkeypatch.setattr(L, "_in_auction_window", lambda: False)
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert "竞价（09:25 匹配价）：" not in doc["narrative"]
    cs = doc["corpusState"]
    assert cs["bidIn"] is False and cs["bidSupplement"] == "skipped_out_of_window"


def test_sealed_prev_pool_empty_not_factual():
    """review 2026-11-13f finding-1：pool_empty 降级态不得事实化成「昨日未封板」。"""
    from backend.analysis.hotlist import auction_leader_ammo as AL
    assert L._sealed_prev({"degraded": "pool_empty", "items": {}}, {}) is None
    assert L._sealed_prev({"degraded": "fetch_failed:x", "items": {}}, {}) is None
    assert L._sealed_prev({}, {"item": {"pool_state": "sealed"}}) is True
    assert L._sealed_prev({}, {"item": {"pool_state": "sealed_not"}}) is False
    # 降级态下结构行只缺封板段（若有 streak 可算仍出行）
    ln = AL.auction_structure_line({"streak": 2, "sealedPrev": None}, prev_date="2026-11-12")
    assert ln is not None and "昨日封板" not in ln and "昨日未封板" not in ln and "连板 2 板" in ln


def test_auction_ladder_line_filters_uncomputable():
    """review 2026-11-13f finding-2：theme 共享梯队行的「不可算」段在竞价叙事剔除。"""
    from backend.analysis.hotlist.theme_leader_ammo import board_ladder_line
    # unknown>0 → 该段整段剔除
    row = {"ladderShape": {"first": 3, "two": 1, "threePlus": 1, "unknown": 2},
           "streak": 4, "secondStreak": 2}
    ln = L._auction_ladder_line(row, "2026-11-12")
    assert "不可算" not in ln and "另有" not in ln and "龙头 4 板" in ln
    # 次高缺位 → 仅保龙头段；unknown 缺省 0
    ln2 = L._auction_ladder_line({"ladderShape": {"first": 2, "two": 0, "threePlus": 0},
                                  "streak": 3, "secondStreak": None}, "2026-11-12")
    assert "不可算" not in ln2 and "龙头 3 板" in ln2
    # 龙头高度也缺 → 形态段仍在（纯事实）但无不可算；ladderShape 缺 → None
    ln3 = L._auction_ladder_line({"ladderShape": {"first": 1, "two": 0, "threePlus": 0}}, "2026-11-12")
    assert "不可算" not in ln3 and "首板 1 家" in ln3
    assert L._auction_ladder_line({"ladderShape": None}, "2026-11-12") is None
    assert L._auction_ladder_line(None, "2026-11-12") is None
    # 原共享函数保留「不可算」（theme 链裁决不动），仅竞价消费点过滤
    assert "不可算" in board_ladder_line({"ladderShape": {"first": 1, "two": 0, "threePlus": 0, "unknown": 1},
                                          "streak": None})
# ── vA4 选龙（2026-11-15 用户裁决：退役 jiuyan 龙序第二源，实测封板概率极低）───
# 选龙 = 推送基源 ∪ 竞价强度第三源；jiuyan_dragon_roster/龙序叙事/韭研龙徽章已删。
# 推送语义（缺席跳过/fetch_failed 退避/幂等/锚 look-ahead）由上方既有测试覆盖。


def test_push_missing_third_source_not_alone(env, monkeypatch):
    """vA4：推送缺席时第三源不单独触发（不兜底选龙）→ 零调用 skip。"""
    db, calls = env
    rows = {"600100": _srow(), "600101": _srow(), "600102": _srow()}
    boards = {"机器人": ["600100", "600101", "600102"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        db["kpl_live_daily"].docs[DATE]["auctionPush"]["stocks"] = []
        db["kpl_live_daily"].docs[DATE]["auctionPush"]["entries"] = []
        res = L.run(DATE, confirm_budget=True)
        assert res["ok"] and res["skippedReason"] == "auction_push_missing"
        assert calls == []
        assert "jiuyanDragonState" not in res
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_max_leaders_truncates_union(env, monkeypatch):
    """N5：max_leaders 截断对 推送∪trial 并集生效（其余记账 fail-visible）。"""
    db, calls = env
    rows = {"600100": _srow(), "600101": _srow(), "600102": _srow()}
    boards = {"机器人": ["600100", "600101", "600102"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True, max_leaders=1)
        assert res["leaders"] == 1
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_source_bucket_retires_jiuyan():
    """vA4：source_bucket 推送>强度>退役jiuyan；重叠历史档归存活源。"""
    assert L.source_bucket(["auction_push", "jiuyan_dragon_t1"]) == "auction_push"
    assert L.source_bucket(["jiuyan_dragon_t1", "auction_trial_strength"]) == "auction_trial_strength"
    assert L.source_bucket(["jiuyan_dragon_t1"]) == "jiuyan_dragon_t1"
    assert L.source_bucket(None) == "auction_push"



def test_evaluate_generation_breakdown():
    """vA2 B5：pilot eval 分代披露（跨代不可比，验收不得混算）。"""
    E = _load_eval_module()
    db = FakeDb()
    col = db[E.COLLECTION]
    col.docs[f"{DATE}:600001"] = {
        "_id": f"{DATE}:600001", "tradingDate": DATE, "docKind": "leader",
        "status": "ok", "questionSetVersion": "vA1",
        "auctionSealToday": "mid_45_65", "outcomeSealedToday": True}
    col.docs[f"{DATE}:600002"] = {
        "_id": f"{DATE}:600002", "tradingDate": DATE, "docKind": "leader",
        "status": "ok", "questionSetVersion": "vA2",
        "auctionSealToday": "high_ge65", "outcomeSealedToday": False}
    res = E.evaluate(db, DATE)
    assert res["settledDocs"] == 2
    assert res["byQuestionSetVersion"]["vA1"]["settledDocs"] == 1
    assert res["byQuestionSetVersion"]["vA2"]["buckets"]["high_ge65"]["sealedRate"] == 0.0


def test_auction_pct_from_bid_lane_not_push(env):
    """2026-11-14 修复：auctionPct=bid 通道 bidding_pct（真竞价），realtimePct=推送 pct（实时）。"""
    db, calls = env
    # bid 通道日档：603135 竞价涨幅 5.5（≠推送实时 3.0）
    db["kpl_daban_pool"].docs[DATE] = {
        "_id": DATE, "bid_date": DATE,
        "bid_items": [{"stock_id": "603135", "name": "中重科技",
                       "bidding_pct": 5.5, "pct": 3.0}]}
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    d603 = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert d603["auctionPct"] == 5.5        # 真竞价值（bid 通道）
    assert d603["realtimePct"] == 3.0       # 推送实时 pct
    # 证据三徽章字段落库（复刻题材龙头事件列；env mock 证据块无 industry→None）
    assert "evidenceIndustry" in d603 and "evidenceBoardResolved" in d603
    assert "evidenceKwordTags" in d603


def test_sealed_prev_cross_matrix():
    """2026-11-14b P1：KPL 池=截断排序榜（11-12 漏 605255），缺席≠未封板。
    交叉源=sealed_and_info（韭研 final ∪ THS 炸板二分，题材链单一实现）。"""
    healthy = {"items": {"600001": {"item": {"pool_state": "sealed"}},
                         "600002": {"item": {"pool_state": "broken"}}}, "degraded": None}
    cross = {"sealed": {"600002", "600003"},
             "info": {"600002": {"zhaban": True}, "600003": {"time": "09:47:41"}},
             "state": "ok"}
    # 池命中 sealed → pool True（双源一致或池独证）
    assert L._sealed_prev_cross(healthy, healthy["items"]["600001"], cross, "600001") == (True, "pool")
    # 池命中 broken + 交叉证封板（TDX 回封）→ 冲突不伪造
    assert L._sealed_prev_cross(healthy, healthy["items"]["600002"], cross, "600002") == (
        None, "conflict_pool_broken_cross_sealed")
    # 池漏档 + 交叉证封板 → True（天普 11-12 形态）
    assert L._sealed_prev_cross(healthy, {}, cross, "600003") == (True, "jiuyan_ths")
    # 池漏档 + 交叉无触板记录 → 旧口径 False
    assert L._sealed_prev_cross(healthy, {}, cross, "600009") == (False, "pool")
    # 池漏档 + 交叉证炸板 → False
    cross_zb = {"sealed": set(), "info": {"600010": {"zhaban": True}}, "state": "ok"}
    assert L._sealed_prev_cross(healthy, {}, cross_zb, "600010") == (False, "jiuyan_ths_zhaban")
    # 交叉不可用（THS 缺）→ 旧口径 + pool_only 留痕
    assert L._sealed_prev_cross(healthy, {}, {"sealed": None, "info": {}, "state": "ths_missing"},
                                "600011") == (False, "pool_only")
    # 旧入口兼容：无交叉 → 行为不变
    assert L._sealed_prev(healthy, healthy["items"]["600001"]) is True
    assert L._sealed_prev(healthy, {}) is False


def test_build_one_pool_miss_cross_seals_structure(monkeypatch):
    """池漏档 + 交叉证封板 → 结构行出「昨日封板（首封 …）」（韭研时点补全），
    streak 由 jiuyan_streak_map 兜底；corpusState.prevPoolCross 留痕。"""
    monkeypatch.setattr(L.digest, "build_theme_evidence_block",
                        lambda *a, **k: {"text": "题材证据块：测试", "state": {}})
    row = {"code": "603135", "name": "中重科技", "board": "机器人", "pct": 3.0}
    cross = {"sealed": {"603135"}, "info": {"603135": {"time": "09:47:41"}}, "state": "ok"}
    built = L.build_one(
        None, DATE, "2026-11-12", row, t1_row=None,
        pool_prev={"items": {}, "degraded": None}, lanes={}, gene_corpus={},
        notice_corpus={}, heat_corpus={}, reason_corpus={}, lhb_facts=None,
        base_rate_stats=None, sector_judgment=None,
        board_codes=[row], prev_cross=cross, streak_map={"603135": 3})
    assert "昨日（2026-11-12）结构：连板 3 板，昨日封板（首封 09:47）" in built["narrative"]
    assert built["corpusState"]["prevPoolCross"] == "jiuyan_ths"


def test_frozen_rerun_reuses_morning_narrative(env):
    """2026-11-14b 〇：单只重跑（codes+force）复用晨间原件叙事（防盘后重跑用
    当日 final 重建注入 look-ahead）；判答仍重烧（2 调用），computedAt 真更新。"""
    db, calls = env
    L.run(DATE, confirm_budget=True)
    col = db[L.COLLECTION]
    original = col.docs[f"{DATE}:603135"]["narrative"]
    n = len(calls)
    import time as _t
    _t.sleep(0.005)
    L.run(DATE, confirm_budget=True, force=True, codes={"603135"})
    doc = col.docs[f"{DATE}:603135"]
    assert doc["corpusFrozen"] is True
    assert doc["narrative"] == original
    assert len(calls) == n + 2          # 冻结只冻语料，判答仍重烧（板块自愈+个股）
    assert doc["sectorJudgmentState"] == "injected"


def test_fresh_run_injects_sector_judgment(env):
    """2026-11-18 bug 修复（广百案审计）：首跑板块判答必须注入龙头叙事。
    此前 _label_one 不回写 built["answers"] → run() 收集恒 {} → 板块判定行
    全链悬空（sectorJudgmentState 恒 sector_missing）；重跑场景被 DB 预载+
    冻结叙事掩盖（旧测试只锁重跑），本测试锁首跑路径。"""
    db, calls = env
    L.run(DATE, confirm_budget=True)
    col = db[L.COLLECTION]
    doc = col.docs[f"{DATE}:603135"]
    sec = col.docs[f"{DATE}:board:机器人"]
    assert sec["status"] == "ok" and sec["answers"]
    assert doc["sectorJudgmentState"] == "injected"
    assert "板块判定：" in doc["narrative"]
    assert "炒作深度=" in doc["narrative"]


def test_build_one_drops_market_facts_and_wires_rank(monkeypatch):
    """2026-11-18a B1/B2：龙头叙事不出昨日盘面事实行（四题零消费+封板①禁
    整体行情调档）；热度排名行接线（身位题证据清单/Top3 例外此前悬空），
    与涨停原因同源 reason_corpus，零新采集；Top3 裸码名单不进叙事。"""
    monkeypatch.setattr(L.digest, "build_theme_evidence_block",
                        lambda *a, **k: {"text": "题材证据块：测试", "state": {}})
    row = {"code": "002187", "name": "广百股份", "board": "大消费", "pct": 9.91}
    reason_corpus = {"002187": {"zt": "零售；据2026年半年报，公司从事百货零售",
                                 "rank": 30, "rank_total": 5575,
                                 "rank_top": ["002242", "600715"]}}
    built = L.build_one(
        None, DATE, "2026-11-12", row, t1_row=None,
        pool_prev={"items": {}}, lanes={}, gene_corpus={},
        notice_corpus={}, heat_corpus={}, reason_corpus=reason_corpus,
        lhb_facts=None, base_rate_stats=None, sector_judgment=None,
        board_codes=[row])
    n = built["narrative"]
    assert "盘面事实" not in n, "B1：昨日盘面事实行退役（题材链 2026-11-17a 同款判例）"
    assert "热度排名：30/5575" in n, "B2：身位题证据清单点名行必须可达"
    assert "（Top3：" not in n
    assert n.index("涨停原因：") < n.index("热度排名：")


def test_trial_state_contract_pending_and_renderer_wiring(env, monkeypatch):
    """骨架合同：窗外默认跑 → trialState=skipped_out_of_window 且叙事无试盘行；
    build_one 直传载荷 → trialState=ok + 交叉留痕字段，叙事出试盘行。"""
    db, calls = env
    L.run(DATE, confirm_budget=True)
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert doc["corpusState"]["trialState"] == {"state": "skipped_out_of_window"}
    assert "竞价试盘" not in doc["narrative"]
    # 第三源选龙账随档落库（fail-visible 持久化，2026-11-16 复盘代办⑤）
    assert doc["corpusState"]["trialStrengthState"]["state"] == "absent"
    assert doc["corpusState"]["trialStrengthState"]["reason"] == "no_trial_rows"

    monkeypatch.setattr(L.digest, "build_theme_evidence_block",
                        lambda *a, **k: {"text": "题材证据块：测试", "state": {}})
    row = {"code": "603135", "name": "中重科技", "board": "机器人", "pct": 3.0}
    trial = {"source": "kpl_dingpan_type7", "fetchedAt": "2026-11-16T09:24:50",
             "prevPercentCross": "agree_3src", "row": {
                 "start_time": "09:15:01", "end_time": "09:18:13",
                 "first_amount": "756万", "jj_percent": 4.78}}
    built = L.build_one(
        None, DATE, "2026-11-13", row, t1_row=None,
        pool_prev={"items": {}, "degraded": None}, lanes={}, gene_corpus={},
        notice_corpus={}, heat_corpus={}, reason_corpus={}, lhb_facts=None,
        base_rate_stats=None, sector_judgment=None,
        board_codes=[row], trial=trial)
    assert built["corpusState"]["trialState"]["state"] == "ok"
    assert built["corpusState"]["trialState"]["prevPercentCross"] == "agree_3src"
    i_trial = built["narrative"].index("竞价试盘（09:15:01–09:18:13）")
    assert "首开 756万" in built["narrative"]
    assert "试盘涨幅 +4.78%（09:18:13 时点）" in built["narrative"]


def test_run_wires_trial_in_window(env, monkeypatch):
    """官方序列试盘行 → 叙事出试盘行 + trialState=ok/derived（§7.17 单主链）。"""
    db, calls = env
    monkeypatch.setattr(L, "_in_auction_window", lambda: True)
    db["kpl_bidding_series"].docs[DATE] = _series_doc(DATE, {
        "603135": {"start_time": "09:15:00", "end_time": "09:20:11",
                   "first_amount": 2_116_000.0, "last_amount": 2_116_000.0,
                   "jj_percent": -2.36, "jj_amount": 3_310_000.0}})
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert "竞价试盘（09:15:00–09:20:11）：首开 211.6万" in doc["narrative"]
    assert "试盘涨幅 -2.36%（09:20:11 时点）" in doc["narrative"]
    ts = doc["corpusState"]["trialState"]
    assert ts["state"] == "ok" and ts["source"] == "kpl_bidding_series_derived"
    assert ts["n_rows"] == 1


def test_run_out_of_window_trial_skipped(env, monkeypatch):
    """窗外：零外呼（fetch 不被调）、试盘行缺席、trialState=skipped_out_of_window。"""
    db, calls = env
    monkeypatch.setattr(L, "_in_auction_window", lambda: False)
    L.run(DATE, confirm_budget=True)   # Wzs 已出链：无任何外呼路径可触发
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    assert "竞价试盘" not in doc["narrative"]
    assert doc["corpusState"]["trialState"] == {"state": "skipped_out_of_window"}


def test_corpus_state_morning_flash_fields_persisted(env, monkeypatch):
    """2026-11-14 盘前催化增量 B/C：label 层合同——①两 builder 均以
    include_morning/include_flash=True 调 digest；②corpusState 透传
    morningState/morningDate/flashState/flashDate（个股+板块）；③语料无档 →
    missing（真实 digest 集成已由 digest 层测试+独立 FakeDb 直调锁定）。"""
    db, calls = env
    seen_kwargs: list[dict] = []

    def rich_stub(*a, **k):
        seen_kwargs.append(k)
        return {"text": "题材证据块：测试", "state": {}, "events": [], "news": [],
                "morningState": "missing", "morningDate": DATE,
                "flashState": "missing", "flashDate": DATE}
    monkeypatch.setattr(L.digest, "build_theme_evidence_block", rich_stub)
    L.run(DATE, confirm_budget=True)
    assert seen_kwargs, "label 必须调 digest"
    assert all(k.get("include_morning") is True and k.get("include_flash") is True
               for k in seen_kwargs), "两 builder 均传 True"
    cs = db[L.COLLECTION].docs[f"{DATE}:603135"]["corpusState"]
    assert cs["morningState"] == "missing" and cs["morningDate"] == DATE
    assert cs["flashState"] == "missing" and cs["flashDate"] == DATE
    sector = db[L.COLLECTION].docs[f"{DATE}:board:机器人"]
    assert sector["corpusState"]["morningState"] == "missing"
    assert sector["corpusState"]["flashState"] == "missing"


def test_build_one_wires_regulatory_line():
    """监管风险行（2026-11-15 预登记）：T−1 收盘档 reg_by_code 进晨间叙事；
    无档/无命中整行缺席 + regulatoryState 留痕。"""
    db = FakeDb()
    row = {"code": "605255", "name": "天普股份", "board": "机器人"}
    reg = {"byCode": {"605255": {
        "monitor_current": {"stock_id": "605255", "stock_name": "天普股份",
                            "start_date": "2026-11-13", "end_date": "2026-11-26"},
        "recent": [{"stock_id": "605255", "stock_name": "天普股份",
                    "abnormal_date": "2026-11-16", "suspended_flag": True,
                    "resume_date": "2026-11-19", "monitor_flag": True,
                    "triggered_flag": False, "period": None}]}},
        "laneOk": True, "reason": None, "states": {}}
    built = L.build_one(db, DATE, "2026-11-12", row, t1_row=None,
                        pool_prev={"items": {}}, lanes={}, gene_corpus={},
                        notice_corpus={}, heat_corpus={}, reason_corpus={},
                        lhb_facts=None,
                        base_rate_stats=None, sector_judgment=None,
                        board_codes=[row], reg_corpus=reg)
    n = built["narrative"]
    assert "监管风险：待判龙头 天普股份605255 重点监控(2026-11-13~2026-11-26)" in n
    assert "严重异动2026-11-16 停牌 预计复牌2026-11-19 重点监控" in n
    assert built["regulatoryState"]["hitCodes"] == ["605255"]
    # 无档 → 缺席 + 留痕
    built0 = L.build_one(db, DATE, "2026-11-12", row, t1_row=None,
                         pool_prev={"items": {}}, lanes={}, gene_corpus={},
                         notice_corpus={}, heat_corpus={}, reason_corpus={},
                         lhb_facts=None,
                         base_rate_stats=None, sector_judgment=None,
                         board_codes=[row],
                         reg_corpus={"byCode": {}, "laneOk": False,
                                     "reason": "no_archive", "states": {}})
    assert "监管风险" not in built0["narrative"]
    assert built0["regulatoryState"]["laneOk"] is False


# ── 第三源：竞价试盘强度板块前三（2026-11-15 预登记，严格档并集补充）─────────

def _trial_strength_setup(monkeypatch, db, rows, boards):
    """第三源集成夹具：root 树 + 窗内 fetch mock + 缓存清理（前后）。"""
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()
    for board, codes in boards.items():
        db["jiuyan_industry_stocks"].docs[f"node:{board}"] = {
            "_id": f"node:{board}", "name": board, "stockN": len(codes),
            "batchDate": "2026-10-25", "stocks": [{"code": c} for c in codes]}
    monkeypatch.setattr(L, "_in_auction_window", lambda: True)
    # 评审 P1（2026-11-15）：窗内竞价补源与试盘采集同门控——未 mock 会真连
    # qt.gtimg.cn（红线 9 频控预算）；离线确定性返回，补源缺席不阻断选龙
    monkeypatch.setattr(L, "get_auction_snapshot_tencent",
                        lambda codes: {"ok": False, "items": {}, "missing": list(codes)})
    # §7.17 raw 整集合退役：试盘行种子=官方序列档（单主链）
    db["kpl_bidding_series"].docs[DATE] = _series_doc(DATE, rows)
    yield
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def _srow(jj_percent=7.0, jj_amount=6e7, first=1e7, last=5e6):
    return {"jj_percent": jj_percent, "jj_amount": jj_amount,
            "first_amount": first, "last_amount": last,
            "start_time": "09:15:00", "end_time": "09:20:11"}


def _series_doc(date, rows):
    """§7.17 raw 退役：试盘行种子→官方序列档（每股首/末两帧，start/end 时点）。"""
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))

    def ts(hm):
        h, m, s = (int(x) for x in str(hm).split(":"))
        return datetime.strptime(date, "%Y-%m-%d").replace(
            hour=h, minute=m, second=s, tzinfo=tz).timestamp()
    frames = {}
    for c, r in rows.items():
        for hm, zkey in ((r.get("start_time") or "09:15:00", "first_amount"),
                         (r.get("end_time") or "09:20:11", "last_amount")):
            frames.setdefault(hm, []).append(
                {"s": c, "zt_buy_amount": r.get(zkey),
                 "bidding_pct": r.get("jj_percent"),
                 "bidding_amount": r.get("jj_amount")})
    return {"_id": date, "ticks": [{"ts": ts(hm), "it": its}
                                   for hm, its in sorted(frames.items())],
            "updated_at": f"{date}T09:25:30+08:00"}


def test_trial_strength_third_source_new_leader(env, monkeypatch):
    """严格档第三源入 live 锚：新股 selectionSources/boardSource/boardMapping/
    trialStrength + 两新叙事行 + sector_missing + sector doc 仅双源成员。"""
    db, calls = env
    rows = {"600100": _srow(jj_percent=7.0), "600101": _srow(jj_percent=8.0),
            "600102": _srow(jj_percent=9.0), "600103": _srow(jj_percent=6.5)}
    boards = {"机器人": ["600100", "600101", "600102", "600103"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True)
        assert res["ok"]
        col = db[L.COLLECTION]
        # 推送股 603135（push_concept 机器人）+ 3 trial 新股（600103 板内第 4 不入选）
        assert res["selection"]["trialN"] == 3
        assert res["selection"]["overlapTrialN"] == 0
        assert res["selection"]["unionN"] == 4
        ts_state = res["trialStrengthState"]
        assert ts_state["state"] == "ok" and ts_state["selectedN"] == 3
        assert ts_state["mappedN"] == 4 and ts_state["unmappedN"] == 0
        d = col.docs[f"{DATE}:600102"]
        assert d["selectionSources"] == ["auction_trial_strength"]
        assert d["boardSource"] == "jiuyan_root_trial"
        assert d["board"] == "机器人" and d["realtimePct"] is None
        assert d["boardMapping"]["pickedBy"] == "trial_root_strength"
        assert d["trialStrength"]["rank"] == 1
        assert d["trialStrength"]["jjtier"] == "mid50_95"
        assert d["trialStrength"]["posture"] == "decrease"
        assert d["sectorJudgmentState"] == "sector_missing"
        assert "板块竞价强度：机器人 试盘竞价成交 Σ2.40亿" in d["narrative"]
        assert "强度档 中热 2-5亿" in d["narrative"] and "板内试盘 4 只" in d["narrative"]
        assert "竞价强度入选：jj_ratio 90%（mid50_95），资金姿态撤减，板内强度排名 1" in d["narrative"]
        assert f"{DATE}:600103" not in col.docs          # 每板前三
        # 双源股叙事不变（无新行）；sector doc 仅双源成员（trial 隔离）
        d603 = col.docs[f"{DATE}:603135"]
        assert "板块竞价强度" not in d603["narrative"]
        assert "竞价强度入选" not in d603["narrative"]
        sec = col.docs[f"{DATE}:board:机器人"]
        assert [s["code"] for s in sec["segmentRows"]] == ["603135"]
        assert len(calls) == 5                          # 1 板块 + 4 个股
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_overlap_keeps_dual_board(env, monkeypatch):
    """重叠股追加源标签 + trialStrength，保留双源 board/龙序；双源叙事不出新行。"""
    db, calls = env
    rows = {"603135": _srow(jj_percent=7.0), "600101": _srow(jj_percent=8.0),
            "600102": _srow(jj_percent=9.0), "600103": _srow(jj_percent=6.5)}
    boards = {"机器人": ["603135", "600101", "600102", "600103"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True)
        col = db[L.COLLECTION]
        d603 = col.docs[f"{DATE}:603135"]
        assert d603["selectionSources"] == ["auction_push", "auction_trial_strength"]
        assert d603["boardSource"] == "push_concept"    # 保留双源板块口径
        assert d603["realtimePct"] == 3.0
        assert d603["trialStrength"]["rank"] == 3
        assert "板块竞价强度" not in d603["narrative"]
        assert res["selection"]["overlapTrialN"] == 1
        assert res["selection"]["unionN"] == 3          # 603135 + 600101 + 600102
        assert col.docs[f"{DATE}:600101"]["boardSource"] == "jiuyan_root_trial"
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_peers_isolated_by_board_source(env, monkeypatch):
    """同板竞价对比 peers 限同口径：root trial 股互为 peers，不与 ABM 双源股混比。"""
    db, calls = env
    rows = {"600100": _srow(jj_percent=7.0), "600101": _srow(jj_percent=8.0),
            "600102": _srow(jj_percent=9.0), "600103": _srow(jj_percent=6.5)}
    boards = {"机器人": ["600100", "600101", "600102", "600103"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        for c, n in (("600100", "甲"), ("600101", "乙"), ("600102", "丙"),
                     ("600103", "丁"), ("603135", "中重科技")):
            db["stock_names"].docs[c] = {"code": c, "name": n}
        db["kpl_daban_pool"].docs[DATE] = {
            "_id": DATE, "bid_date": DATE,
            "bid_items": [{"stock_id": c, "name": n, "bidding_pct": jp,
                           "bidding_amount": 6e7}
                          for c, n, jp in (("600100", "甲", 7.0), ("600101", "乙", 8.0),
                                           ("600102", "丙", 9.0), ("600103", "丁", 6.5),
                                           ("603135", "中重科技", 7.0))]}
        L.run(DATE, confirm_budget=True)
        col = db[L.COLLECTION]
        n_trial = col.docs[f"{DATE}:600100"]["narrative"]
        cmp_seg = next(ln for ln in n_trial.split("\n") if ln.startswith("竞价（09:25 匹配价）"))
        assert "乙" in cmp_seg and "丙" in cmp_seg
        assert "中重科技" not in cmp_seg               # ABM 双源股不混入 trial peers
        n_push = col.docs[f"{DATE}:603135"]["narrative"]
        assert "甲" not in n_push and "乙" not in n_push and "丙" not in n_push
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_dry_run_reads_series(env, monkeypatch):
    """历史日 dry-run：窗采集缺席 → 序列档派生（纯库读零外呼），
    第三源候选出现；零 jev 零写。"""
    db, calls = env
    from backend.services.jev import jiuyan_board, jiuyan_industry_root
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()
    db["jiuyan_industry_stocks"].docs["node:机器人"] = {
        "_id": "node:机器人", "name": "机器人", "stockN": 4, "batchDate": "2026-10-25",
        "stocks": [{"code": c} for c in ("600100", "600101", "600102", "600103")]}
    db["kpl_bidding_series"].docs[DATE] = _series_doc(DATE, {
        "600100": _srow(jj_percent=7.0), "600101": _srow(jj_percent=8.0),
        "600102": _srow(jj_percent=9.0), "600103": _srow(jj_percent=6.5)})
    # 单主链纯库读：dry-run 天然零外呼
    try:
        res = L.run(DATE, dry_run=True)
        assert res["ok"] and res["dryRun"]
        assert calls == []                              # dry-run 零外呼零写 and db[L.COLLECTION].docs == {}
        assert res["selection"]["trialN"] == 3
        assert res["trialStrengthState"]["state"] == "ok"
        assert res["leaders"] == 4                      # 1 推送 + 3 trial
    finally:
        jiuyan_board.reset_jiuyan_board_cache()
        jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def test_trial_strength_absent_fail_visible(env):
    """trial 缺（窗外+无日档）→ 第三源整源缺席 + reason；双源不受影响。"""
    db, calls = env
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    assert res["trialStrengthState"]["state"] == "absent"
    assert res["trialStrengthState"]["reason"] == "no_trial_rows"
    assert res["selection"]["trialN"] == 0
    assert res["leaders"] == 1                          # 推送股照跑
    assert f"{DATE}:603135" in db[L.COLLECTION].docs


def test_trial_strength_soft_cap_six(env, monkeypatch):
    """软上限 ≤6 只/日：9 候选截断 6，记账留痕（全局 jj_ratio 降序保留）。"""
    db, calls = env
    rows, boards = {}, {}
    for bi, board in enumerate(["板A", "板B", "板C"]):
        codes = [f"6{bi}{i:02d}00" for i in range(3)]
        boards[board] = codes
        ratios = [[90, 80, 70], [85, 75, 65], [94, 60, 55]][bi]
        for c, jp in zip(codes, ratios):
            rows[c] = _srow(jj_percent=jp / 10.0, jj_amount=8e7)
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True)
        assert res["selection"]["trialN"] == 6
        st = res["trialStrengthState"]
        assert st["cap"] == 6 and st["truncatedN"] == 3 and st["selectedN"] == 6
        assert res["leaders"] == 7                      # 1 推送 + 6 trial
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_non_theme_excluded(env, monkeypatch):
    """非题材行政桶剔除对第三源同规（root 板「其他」）。"""
    db, calls = env
    rows = {"600100": _srow(jj_amount=1e8), "600101": _srow(jj_percent=8.0, jj_amount=1e8),
            "600102": _srow(jj_percent=9.0, jj_amount=1e8)}
    boards = {"其他": ["600100", "600101", "600102"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True)
        col = db[L.COLLECTION]
        assert f"{DATE}:600100" not in col.docs
        assert res["selection"]["trialN"] == 3          # roster 选中 3
        assert res["selection"]["unionN"] == 1          # 行政桶剔除后仅推送股
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_base_rate_anchor_third_bucket_priority(env):
    """vA4 锚人群桶：互斥优先级 auction_push > auction_trial_strength；退役 jiuyan 单源历史档不计入。"""
    db, calls = env
    col = db[L.COLLECTION]
    base = {"tradingDate": "2026-11-13", "docKind": "leader", "status": "ok",
            "sampleOrigin": "live", "outcomeSealedToday": True}
    col.docs["2026-11-13:600001"] = {**base, "_id": "2026-11-13:600001",
                                     "selectionSources": ["auction_push", "auction_trial_strength"]}
    col.docs["2026-11-13:600002"] = {**base, "_id": "2026-11-13:600002",
                                     "selectionSources": ["jiuyan_dragon_t1", "auction_trial_strength"]}
    col.docs["2026-11-13:600003"] = {**base, "_id": "2026-11-13:600003",
                                     "selectionSources": ["auction_trial_strength"]}
    col.docs["2026-11-13:600004"] = {**base, "_id": "2026-11-13:600004"}   # vA1 旧档按推送
    col.docs["2026-11-13:600005"] = {**base, "_id": "2026-11-13:600005",
                                     "selectionSources": ["jiuyan_dragon_t1"]}   # 退役单源→不计入
    stats = L.auction_seal_base_rate(db, before="2026-11-14")
    assert stats["n"] == 4
    assert stats["nPush"] == 2 and stats["nTrial"] == 2
    assert "nJiuyan" not in stats
    from backend.analysis.hotlist import auction_leader_ammo as AL
    ln = AL.auction_base_rate_line(stats)
    assert "推送 2/竞价强度 2" in ln and "韭研龙" not in ln


def test_evaluate_selection_source_breakdown():
    """pilot eval 按 selectionSources 披露第三源构成（互斥优先级同锚）。"""
    E = _load_eval_module()
    db = FakeDb()
    col = db[E.COLLECTION]
    base = {"tradingDate": DATE, "docKind": "leader", "status": "ok",
            "questionSetVersion": "vA4", "auctionSealToday": "mid_45_65"}
    col.docs[f"{DATE}:600001"] = {**base, "_id": f"{DATE}:600001",
                                  "outcomeSealedToday": True,
                                  "selectionSources": ["auction_trial_strength"]}
    col.docs[f"{DATE}:600002"] = {**base, "_id": f"{DATE}:600002",
                                  "outcomeSealedToday": False,
                                  "selectionSources": ["auction_push", "auction_trial_strength"]}
    res = E.evaluate(db, DATE)
    bs = res["bySelectionSource"]
    assert bs["auction_trial_strength"]["settledDocs"] == 1
    assert bs["auction_trial_strength"]["sealedRate"] == 100.0
    assert bs["auction_push"]["settledDocs"] == 1
    assert bs["auction_push"]["sealedRate"] == 0.0


# ── 评审修复 2026-11-15（review-contract P1-2 / review-correctness P2-1/4 / tests-docs P2）──

def test_trial_strength_codes_rerun_trial_only(env, monkeypatch):
    """P1-2：trial-only 股单只重跑（codes 过滤）不得被并集前早退截断。"""
    db, calls = env
    rows = {"600100": _srow(jj_percent=7.0, jj_amount=8e7),
            "600101": _srow(jj_percent=8.0, jj_amount=8e7),
            "600102": _srow(jj_percent=9.0, jj_amount=8e7)}
    boards = {"机器人": ["600100", "600101", "600102"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True, force=True, codes={"600102"})
        assert res["ok"] and "skippedReason" not in res
        assert res["leaders"] == 1
        assert res["selection"]["trialN"] == 3      # 全日 roster 口径
        assert res["selection"]["unionN"] == 1      # codes 过滤后
        col = db[L.COLLECTION]
        d = col.docs[f"{DATE}:600102"]
        assert d["selectionSources"] == ["auction_trial_strength"]
        assert d["boardSource"] == "jiuyan_root_trial"
        assert f"{DATE}:603135" not in col.docs     # codes 语义：双源股不重判
        assert len(calls) == 1                      # 仅 1 个股（trial 无 sector doc）
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_codes_rerun_no_match_still_skips(env, monkeypatch):
    """codes 未命中任何源（双源/trial）→ 保持 skip 语义（零调用零写）。"""
    db, calls = env
    rows = {"600100": _srow(jj_percent=7.0, jj_amount=8e7),
            "600101": _srow(jj_percent=8.0, jj_amount=8e7),
            "600102": _srow(jj_percent=9.0, jj_amount=8e7)}
    boards = {"机器人": ["600100", "600101", "600102"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True, force=True, codes={"999999"})
        assert res["ok"] and res["skippedReason"] == "no_leaders"
        assert res["trialStrengthState"]["selectedN"] == 3
        assert calls == []
        assert db[L.COLLECTION].docs == {}
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_excluded_admin_dual_not_swallow_trial(env, monkeypatch):
    """P2-1：双源行被行政桶剔除后，同 code 的 trial 候选须以 trial_new 入并集
    （不得被排除前 by_code 的 overlap 判定吞掉）。另保一只存活双源股（全排除
    仍 skip 是既有裁决语义，不在本例范围）。"""
    db, calls = env
    push = db["kpl_live_daily"].docs[DATE]["auctionPush"]
    push["stocks"][0]["board"] = "其他"
    push["stocks"][0]["boardRaw"] = "其他"
    push["stocks"].append({"code": "600999", "name": "存活股", "pct": 2.0,
                           "board": "机器人", "boardRaw": "机器人"})
    rows = {"603135": _srow(jj_percent=7.0, jj_amount=8e7),
            "600100": _srow(jj_percent=8.0, jj_amount=8e7),
            "600101": _srow(jj_percent=9.0, jj_amount=8e7)}
    boards = {"机器人": ["603135", "600100", "600101", "600999"]}
    gen = _trial_strength_setup(monkeypatch, db, rows, boards)
    next(gen)
    try:
        res = L.run(DATE, confirm_budget=True)
        col = db[L.COLLECTION]
        assert res["selection"]["overlapTrialN"] == 0
        assert res["selection"]["trialN"] == 3
        assert res["selection"]["unionN"] == 4      # 存活双源 1 + trial_new 3
        d = col.docs[f"{DATE}:603135"]
        assert d["selectionSources"] == ["auction_trial_strength"]
        assert d["boardSource"] == "jiuyan_root_trial"
        assert d["board"] == "机器人"
        sec = col.docs[f"{DATE}:board:机器人"]
        assert [s["code"] for s in sec["segmentRows"]] == ["600999"]  # trial 隔离
        assert len(calls) == 5                      # 1 板块 + 4 个股
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_trial_strength_roster_failure_dual_continues(env, monkeypatch):
    """P2-4：run() roster 异常 → absent/roster_failed 留痕，双源打标不阻断
    （与读口 trialRosterError 对称）。"""
    db, calls = env

    def boom(*a, **k):
        raise RuntimeError("roster boom")

    monkeypatch.setattr(L, "trial_strength_roster", boom)
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    assert res["trialStrengthState"]["state"] == "absent"
    assert "roster boom" in res["trialStrengthState"]["reason"]
    assert f"{DATE}:603135" in db[L.COLLECTION].docs
    assert len(calls) == 2                          # 双源照常：1 板块 + 1 个股


def test_trial_strength_derive_error_fail_visible(env, monkeypatch):
    """§7.17 无回退：派生异常 → trialState derive_failed 留痕，双源不阻断。"""
    db, calls = env

    def boom(*a, **k):
        raise RuntimeError("derive boom")

    monkeypatch.setattr(L, "derive_trial_rows_from_series", boom)
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"]
    assert res["trialStrengthState"]["state"] == "absent"
    doc = db[L.COLLECTION].docs[f"{DATE}:603135"]
    ts = doc["corpusState"]["trialState"]
    assert ts["state"] == "derive_failed:RuntimeError"
    assert len(calls) == 2
