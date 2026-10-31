# -*- coding: utf-8 -*-
"""复盘日报测试（operations/jev_daily_recap + services/jev/jev_daily_recap_corpus）。

题目集 v2（2026-10-31 用户裁决）：4 道计划题（基调+仓位/打法/回避/验证信号）；环境题全删
（EOD/连板情绪链已回答）；主攻方向机械派生；短叙事删除；模板 v3。
全离线：mock call_jev / FakeDb，零网络零真库零模型调用（硬红线 §1.2#7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_daily_recap as ops
from backend.services.jev import jev_daily_recap_corpus as corpus

QUESTION_KEYS = ("plan_bias", "play_style", "avoid_focus", "key_watch")

_QUESTIONS_ROUTE_PATH = "backend.data.repositories.repository_factory.get_runtime_mongodb_database"


def mk_rise(**kw):
    base = {
        "ok": True, "noData": False,
        "pool": {"up": 30, "down": 5, "ratio": 6.0, "strong": 3, "streak2": 4, "maxStreak": 4,
                 "maxStreakName": "龙头A"},
        "fullRise": {"count": 400},
        "positive": {"netInflowTotal": 2.0e8, "topBoards": [{"board": "算力", "count": 8},
                                                            {"board": "机器人", "count": 5}]},
        "degraded": [],
        "stocks": [
            {"code": "1", "name": "甲", "board": "算力", "pctChange": 9.0, "shape": "high_close", "streak": 2},
            {"code": "2", "name": "乙", "board": "算力", "pctChange": 6.0, "shape": "fade", "streak": None},
            {"code": "3", "name": "丙", "board": "机器人", "pctChange": -1.0, "shape": "big_face", "streak": None},
            {"code": "4", "name": "丁", "board": "机器人", "pctChange": 7.0, "shape": "zha_ban", "streak": None},
        ],
    }
    base.update(kw)
    return base


def mk_dieban(**kw):
    base = {
        "ok": True, "noData": False,
        "pool": {"up": 5, "down": 30, "dieban": 3, "deepDrop": 4, "oneWord": 1, "streak2": 2,
                 "maxStreak": 2, "maxStreakName": "高位B"},
        "fullMarket": {"count": 3},
        "negative": {"netOutflowTotal": -3.0e8, "topBoards": [{"board": "地产", "count": 4}]},
        "degraded": [],
        "stocks": [
            {"code": "9", "name": "庚", "board": "地产", "pctChange": -10.0, "shape": None, "streak": 3},
            {"code": "8", "name": "辛", "board": "地产", "pctChange": -7.0, "shape": "tail_dive", "streak": None},
            {"code": "7", "name": "壬", "board": None, "pctChange": -9.0, "shape": "down", "streak": None},
        ],
    }
    base.update(kw)
    return base


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, q=None, *a, **k):
        if not q:
            return None
        doc = self.docs.get(q.get("_id"))
        if doc is None or (q.get("ok") is True and doc.get("ok") is not True):
            return None
        return doc

    def replace_one(self, q, doc, *a, **k):
        self.docs[q.get("_id")] = doc


class FakeDb:
    def __init__(self):
        self.collections: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCol())


def _envelope(answers: dict[str, str], usage: dict | None = None) -> tuple[dict, int]:
    return ({"success": True, "result": {"state": "Completed",
            "result": {"model": "m",
                       "answers": {q: {"type": "choice", "choice": v} for q, v in answers.items()},
                       "usage": usage or {}}}}, 42)


# 语料 v3 各块 mock 值（10-30 实录形态：亏钱/退潮/晋级率低）
RELAY_ANSWERS = {"relay_phase": "divergence", "relay_momentum": "weakening",
                 "ladder_health": "pyramid", "money_effect": "losing",
                 "theme_pulse": "mainline_continue"}
EMOTION = {"eod": 43.0, "prevEod": 55.0, "prevEodDate": "2026-10-29", "eod20dPercentile": 15.0,
           "bandTag": "弱0-20", "bandLabel": "弱势期"}
EOD_JUDGE = {"ok": True, "score": 43.0, "stage": "退潮", "riskLevel": "高"}
THEME_BOARDS = {"ok": True, "boards": [
    {"board": "医疗医药", "continuation": "strong_extend", "depth": "igniting"},
    {"board": "AI硬件", "continuation": "ending", "depth": "igniting"}]}
MARKET_AMOUNT = {"ok": True, "todayTurnover": 5322e8, "yesterdayTurnover": 5312e8,
                 "change1d": -2, "mainNetAmount": -105.6e8}
PROMOTION = {"ok": True, "rate": 23.1, "baseCount": 39, "promotedCount": 9,
             "brokenCount": 30, "denom": 39}


@pytest.fixture()
def material(monkeypatch):
    """数据装载边界：全部 loader 固定 mock；call_jev 由各用例自行 monkeypatch。"""
    monkeypatch.setattr(ops, "load_emotion", lambda db, date: (dict(EMOTION), []))
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: mk_rise())
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: mk_dieban())
    monkeypatch.setattr(ops, "load_kpl_wrap",
                        lambda db, date: ({"ok": True, "time": "15:00", "comment": "综述", "fromArchive": True}, []))
    monkeypatch.setattr(ops, "load_relay_judgment",
                        lambda db, date: ({"ok": True, "index": 30.6, "answers": dict(RELAY_ANSWERS),
                                           "leaderStrengthScore": 5.25, "questionSetVersion": "v7.1"}, []))
    monkeypatch.setattr(ops, "load_eod_judge", lambda db, date: (dict(EOD_JUDGE), []))
    monkeypatch.setattr(ops, "load_theme_boards",
                        lambda db, date: ({"ok": True, "boards": [dict(b) for b in THEME_BOARDS["boards"]]}, []))
    monkeypatch.setattr(ops, "load_market_amount", lambda db, date: (dict(MARKET_AMOUNT), []))
    monkeypatch.setattr(ops, "load_promotion",
                        lambda db, date, prev: (dict(PROMOTION), []))


def _mk_state(**overrides):
    """组装完整 state（fixture 同款值），供纯函数用例使用。"""
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    return corpus.build_state(
        "2026-10-31", facts, dict(EMOTION),
        kpl_wrap={"ok": True, "time": "15:00", "comment": "综述"},
        relay_judgment={"ok": True, "index": 30.6, "answers": dict(RELAY_ANSWERS),
                        "leaderStrengthScore": 5.25, "questionSetVersion": "v7.1"},
        eod_judge=dict(EOD_JUDGE), theme_boards={"ok": True, "boards": [dict(b) for b in THEME_BOARDS["boards"]]},
        market_amount=dict(MARKET_AMOUNT), promotion=dict(PROMOTION), **overrides)


# ---------------------------------------------------------------- 语料拼装（纯函数）

def test_collect_review_facts_shape_counts_and_passthrough():
    facts = corpus.collect_review_facts(
        mk_rise(degraded=[{"scope": "ret3d", "reason": "insufficient_history"}]), mk_dieban())
    assert facts["rise"]["shapes"]["high_close"] == 1
    assert facts["dieban"]["limitDownCount"] == 3
    assert facts["rise"]["topStocks"][0]["code"] == "1"
    assert any(d["source"] == "rise" and "ret3d" in d["reason"] for d in facts["degradedSources"])


def test_collect_review_facts_missing_page_not_false():
    facts = corpus.collect_review_facts(None, mk_dieban())
    assert facts["rise"]["noData"] is True
    assert facts["dieban"]["noData"] is False
    assert any(d["reason"] == "review_doc_unavailable" for d in facts["degradedSources"])


def test_collect_review_facts_nodata_page_registered_with_reason():
    """评审 Major-1：ok=True+noData=True 页必须登记结构化原因（门2 degraded 率不得低估）。"""
    nodata_rise = {"ok": True, "noData": True, "reason": "2026-10-30 无 half_hour 快照行（未回填）",
                   "degraded": [], "stocks": []}
    facts = corpus.collect_review_facts(nodata_rise, mk_dieban())
    hit = [d for d in facts["degradedSources"] if d["source"] == "rise" and d["action"] == "page_no_data"]
    assert len(hit) == 1 and "无 half_hour 快照行" in hit[0]["reason"]


# ---------------------------------------------------------------- 机械判 v2（与 criteria 同数）

def test_rule_plan_bias_branches():
    v = corpus._mech_view(_mk_state())
    # fixture：losing + pyramid + 跌停3 → 防守
    assert corpus.rule_plan_bias(v) == "防守"
    # 空仓观望：losing 且 跌停≥50
    v2 = corpus._mech_view(_mk_state())
    v2["limit_down"] = 81
    assert corpus.rule_plan_bias(v2) == "空仓观望"
    # 空仓观望：losing 且 梯队断层
    v3 = corpus._mech_view(_mk_state())
    v3["ladder_health"] = "inverted"
    assert corpus.rule_plan_bias(v3) == "空仓观望"
    # 进攻：strong + momentum 强化 + riskLevel≠高
    v4 = corpus._mech_view(_mk_state())
    v4.update({"money_effect": "strong", "relay_momentum": "accelerating", "risk_level": "中"})
    assert corpus.rule_plan_bias(v4) == "进攻"
    # 均衡：neutral
    v5 = corpus._mech_view(_mk_state())
    v5["money_effect"] = "neutral"
    assert corpus.rule_plan_bias(v5) == "均衡"
    # 均衡：strong 但 riskLevel=高
    v6 = corpus._mech_view(_mk_state())
    v6.update({"money_effect": "strong", "relay_momentum": "accelerating", "risk_level": "高"})
    assert corpus.rule_plan_bias(v6) == "均衡"
    # 缺料 → insufficient
    v7 = corpus._mech_view(_mk_state())
    v7["money_effect"] = None
    assert corpus.rule_plan_bias(v7) == "insufficient_evidence"


def test_rule_play_style_branches():
    v = corpus._mech_view(_mk_state())
    assert corpus.rule_play_style(v) == "只看不追"      # losing（fixture 基准）
    v2 = corpus._mech_view(_mk_state())
    v2.update({"money_effect": "neutral", "leader_strength": 6.5})
    assert corpus.rule_play_style(v2) == "龙头核心"      # pyramid + neutral + 强度≥6
    v3 = corpus._mech_view(_mk_state())
    v3.update({"money_effect": "neutral", "leader_strength": 5.25})
    assert corpus.rule_play_style(v3) == "分歧低吸"      # divergence + neutral
    v4 = corpus._mech_view(_mk_state())
    v4.update({"money_effect": "strong", "leader_strength": 4.0, "relay_phase": "rotation"})
    assert corpus.rule_play_style(v4) == "低位首板"      # 点火强延续题材在场
    v5 = corpus._mech_view(_mk_state())
    v5["money_effect"] = None
    assert corpus.rule_play_style(v5) == "insufficient_evidence"


def test_rule_avoid_focus_branches():
    v = corpus._mech_view(_mk_state())
    assert corpus.rule_avoid_focus(v) == "无明确回避"    # 大面1/跌停3/炸板1
    v2 = corpus._mech_view(_mk_state())
    v2["limit_down"] = 81
    assert corpus.rule_avoid_focus(v2) == "高位断板承接"
    v3 = corpus._mech_view(_mk_state())
    v3["big_face"] = 4
    assert corpus.rule_avoid_focus(v3) == "高位断板承接"
    v4 = corpus._mech_view(_mk_state())
    v4["zha_ban"] = 25
    assert corpus.rule_avoid_focus(v4) == "追高打板"
    v5 = corpus._mech_view(_mk_state())
    v5["ending_boards"] = 3
    assert corpus.rule_avoid_focus(v5) == "弱势板块补跌"


def test_rule_key_watch_branches():
    v = corpus._mech_view(_mk_state())
    assert corpus.rule_key_watch(v) == "晋级率修复"      # rate 23.1 < 30
    v2 = corpus._mech_view(_mk_state())
    v2["promotion_rate"] = 45.0
    v2["zha_ban"] = 25
    assert corpus.rule_key_watch(v2) == "炸板率回落"
    v3 = corpus._mech_view(_mk_state())
    v3["promotion_rate"] = 45.0
    v3["zha_ban"] = 5
    assert corpus.rule_key_watch(v3) == "量能维持"       # change1d=-2
    v4 = corpus._mech_view(_mk_state())
    v4.update({"promotion_rate": 45.0, "change1d": 3, "zha_ban": 5, "limit_down": 40})
    assert corpus.rule_key_watch(v4) == "高位股承接"


def test_derive_focus_direction_from_theme_boards():
    state = _mk_state()
    assert corpus.derive_focus_direction(state) == "医疗医药"   # strong_extend top1（板名字典序）
    # 全衰竭 → 空仓观望
    state2 = _mk_state()
    state2["themeBoards"] = {"ok": True, "boards": [{"board": "AI硬件", "continuation": "ending",
                                                     "depth": "igniting"}]}
    assert corpus.derive_focus_direction(state2) == "空仓观望"


def test_build_questions_criteria_reference_fed_fields():
    """题目集 v2：4 题、判据只引用语料已有字段、与机械判同数、无开发黑话。"""
    qs = corpus.build_questions(_mk_state())
    assert set(qs) == set(QUESTION_KEYS)
    allowed_tokens = ("state.", "money_effect", "relay_momentum", "ladder_health", "riskLevel",
                      "relay_phase", "leaderStrengthScore", "continuation", "depth",
                      "promotion.rate", "marketAmount.change1d", "跌停", "大面", "炸板", "强势",
                      "题材点火", "衰竭")
    for spec in qs.values():
        for val in spec["criteria"].values():
            assert "{" not in val and "}" not in val
            assert "开火" not in val and "贫料" not in val
        assert "insufficient_evidence" in spec["criteria"]


# ---------------------------------------------------------------- 成文模板 v3

def test_compose_recap_text_two_sections_no_narrative():
    state = _mk_state()
    slots = {"plan_bias": "空仓观望", "play_style": "只看不追",
             "avoid_focus": "高位断板承接", "key_watch": "晋级率修复"}
    text = corpus.compose_recap_text("2026-10-31", state, slots)
    assert set(text) == {"conclusion", "plan"}                    # 短叙事已删
    assert "【复盘结论】" in text["conclusion"] and "晋级率23.1%" in text["conclusion"]
    assert "EOD判定：退潮·风险级高" in text["conclusion"]
    assert "【隔日交易计划】倾向空仓观望" in text["plan"]
    assert "进攻方向医疗医药" in text["plan"]                      # 机械派生方向
    assert "隔日验证晋级率修复" in text["plan"]
    assert "非交易信号" in text["plan"]
    # 缺槽 → 未判定（不伪造）
    text2 = corpus.compose_recap_text("2026-10-31", state, {})
    assert "未判定" in text2["plan"]


# ---------------------------------------------------------------- 主流程（dry / apply / 幂等）

def test_dry_run_zero_call_zero_write(material, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry 模式不得真调用 jev")
    monkeypatch.setattr(ops, "dispatch_jev_call", boom)
    db = FakeDb()
    result = ops.run_daily_recap_for_date("2026-10-31", apply=False, db=db)
    assert result["ok"] and result["report"]["skippedJev"] is True
    rep = result["report"]
    assert all(rep["answers"][q]["source"] == "rule_dry" for q in QUESTION_KEYS)
    # fixture 值下的机械判：防守/只看不追/无明确回避/晋级率修复
    assert rep["answers"]["plan_bias"]["choice"] == "防守"
    assert rep["answers"]["key_watch"]["choice"] == "晋级率修复"
    assert "hotlist_jev_daily_recap" not in db.collections      # 零写库
    assert "persistedId" not in rep


def test_apply_happy_path_jev_sources_and_persist(material, monkeypatch):
    answers = {"plan_bias": "空仓观望", "play_style": "只看不追",
               "avoid_focus": "高位断板承接", "key_watch": "晋级率修复"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))  # conftest 护栏清空 token
    monkeypatch.setattr(ops, "dispatch_jev_call",
                        lambda *a, **k: _envelope(answers, usage={"totalTokens": 99}))
    db = FakeDb()
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=db)["report"]
    assert all(rep["answers"][q]["source"] == "jev" for q in QUESTION_KEYS)
    assert rep["usage"] == {"totalTokens": 99}
    assert db.collections["hotlist_jev_daily_recap"].docs["2026-10-31"]["_id"] == "2026-10-31"
    assert rep["persistedId"] == "2026-10-31"


def test_apply_invalid_choice_rule_fallback(material, monkeypatch):
    invalid = {"plan_bias": "胡说八道", "play_style": "乱来",
               "avoid_focus": "瞎写", "key_watch": "不存在"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(invalid))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert all(rep["answers"][q]["source"] == "rule_fallback" for q in QUESTION_KEYS)
    assert rep["answers"]["plan_bias"]["choice"] == "防守"        # 机械判兜底
    assert rep["answers"]["key_watch"]["choice"] == "晋级率修复"
    assert any(d["reason"].startswith("invalid_choice") for d in rep["degraded"])


def test_apply_jev_insufficient_slot_unjudged(material, monkeypatch):
    answers = {"plan_bias": "insufficient_evidence", "play_style": "只看不追",
               "avoid_focus": "高位断板承接", "key_watch": "晋级率修复"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(answers))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["answers"]["plan_bias"] == {"choice": None, "source": "jev_insufficient"}
    assert rep["answers"]["play_style"]["source"] == "jev"
    assert any(d["source"] == "plan_bias" for d in rep["degraded"])


def test_apply_call_failure_full_rule_fallback(material, monkeypatch):
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["jev"] is None
    assert all(rep["answers"][q]["source"] == "rule_fallback" for q in QUESTION_KEYS)
    assert rep["text"]["plan"]          # 机械版成文仍在（fail-visible 不丢当日日报）


def test_no_material_no_jev(material, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("贫料日不得烧 jev")
    monkeypatch.setattr(ops, "dispatch_jev_call", boom)
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: {"ok": False})
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: {"ok": False})
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())
    assert result["ok"] is False and result["errorCode"] == "no_material"


def test_idempotent_skip_existing_ok_doc(material):
    db = FakeDb()
    col = db.collections.setdefault("hotlist_jev_daily_recap", FakeCol())
    col.docs["2026-10-31"] = {"_id": "2026-10-31", "ok": True}
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=db)
    assert result.get("skipped") is True and result.get("reason") == "already_ok_doc"


def test_apply_force_recomputes_existing_ok_doc(material, monkeypatch):
    answers = {"plan_bias": "进攻", "play_style": "龙头核心",
               "avoid_focus": "无明确回避", "key_watch": "量能维持"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(answers))
    db = FakeDb()
    col = db.collections.setdefault("hotlist_jev_daily_recap", FakeCol())
    col.docs["2026-10-31"] = {"_id": "2026-10-31", "ok": True}
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, force=True, db=db)
    assert result.get("skipped") is None
    assert result["report"]["answers"]["plan_bias"]["choice"] == "进攻"
    result2 = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=db)
    assert result2.get("skipped") is True


def test_apply_missing_token_full_rule_fallback(material, monkeypatch):
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", ""))
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())
    rep = result["report"]
    assert rep["skippedJev"] is False and rep["jev"] is None
    assert all(rep["answers"][q]["source"] == "rule_fallback" for q in QUESTION_KEYS)
    assert any(d["source"] == "jev" and d["reason"] == "missing_jev_token"
               for d in rep["degraded"])


def test_persist_failure_marks_result_and_degraded(material, monkeypatch):
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(
        {"plan_bias": "防守", "play_style": "只看不追",
         "avoid_focus": "高位断板承接", "key_watch": "晋级率修复"}))

    class BoomDb(FakeDb):
        def __getitem__(self, name):
            if name == "hotlist_jev_daily_recap":
                raise RuntimeError("mock persist down")
            return super().__getitem__(name)

    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=BoomDb())
    assert result["ok"] is True and result.get("persistFailed") is True
    rep = result["report"]
    assert rep["persistedId"] is None
    assert any(d["source"] == "persistence" and d["reason"].startswith("persist_failed")
               for d in rep["degraded"])


def test_partial_missing_material_still_emits(monkeypatch):
    """部分缺料（单页缺）仍出包出日报（§4.0 fail-visible：不硬门禁不静默）。"""
    monkeypatch.setattr(ops, "load_emotion", lambda db, date: (dict(EMOTION), []))
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: {"ok": False})
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: mk_dieban())
    monkeypatch.setattr(ops, "load_kpl_wrap", lambda db, date: ({"ok": False, "reason": "x"}, [
        {"source": "kpl_wrap", "reason": "x", "action": "corpus_absent"}]))
    monkeypatch.setattr(ops, "load_relay_judgment", lambda db, date: ({"ok": False, "reason": "x"}, []))
    monkeypatch.setattr(ops, "load_eod_judge", lambda db, date: ({"ok": False, "reason": "x"}, []))
    monkeypatch.setattr(ops, "load_theme_boards", lambda db, date: ({"ok": False, "reason": "x"}, []))
    monkeypatch.setattr(ops, "load_market_amount", lambda db, date: ({"ok": False, "reason": "x"}, []))
    monkeypatch.setattr(ops, "load_promotion", lambda db, date, prev: ({"ok": False, "reason": "x"}, []))
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["ok"] is True
    assert rep["answers"]["plan_bias"]["source"] == "rule_fallback"
    assert rep["text"]["conclusion"]          # 机械版成文仍在


# ---------------------------------------------------------------- 语料 v3 loaders

def test_load_kpl_wrap_found_strips_ai_note(monkeypatch):
    from backend.operations.theme_leader_label import _AI_GEN_NOTE

    class WrapDb:
        def __getitem__(self, name):
            assert name == "kpl_live_daily"
            return self

        def find_one(self, q):
            assert q == {"_id": "2026-10-30"}
            return {"_id": "2026-10-30", "items": [
                {"time": "14:55", "comment": "尾盘低迷" + _AI_GEN_NOTE},
                {"time": "15:00", "comment": "三大指数冲高回落，创业板指跌超-4%" + _AI_GEN_NOTE},
            ]}

    payload, degraded = ops.load_kpl_wrap(WrapDb(), "2026-10-30")
    assert payload["ok"] is True and payload["time"] == "15:00"
    assert payload["comment"] == "三大指数冲高回落，创业板指跌超-4%"
    assert _AI_GEN_NOTE not in payload["comment"] and degraded == []

    class NoWrapDb:
        def __getitem__(self, name):
            return self

        def find_one(self, q):
            return {"_id": "d", "items": [{"time": "14:55", "comment": "尾盘低迷"}]}

    payload2, degraded2 = ops.load_kpl_wrap(NoWrapDb(), "d")
    assert payload2 == {"ok": False, "reason": "no_15:00_wrap_in_archive"}
    assert degraded2[0]["source"] == "kpl_wrap" and degraded2[0]["action"] == "corpus_absent"

    class EmptyDb:
        def __getitem__(self, name):
            return self

        def find_one(self, q):
            return None

    payload3, degraded3 = ops.load_kpl_wrap(EmptyDb(), "d")
    assert payload3 == {"ok": False, "reason": "archive_missing"}


def test_load_relay_judgment_structured_only(monkeypatch):
    class RelayDb:
        def __init__(self, doc):
            self.doc = doc

        def __getitem__(self, name):
            assert name == "hotlist_jev_relay_index"
            return self

        def find_one(self, q):
            assert q == {"_id": "2026-10-30:RELAY"}
            return self.doc

    good = {"_id": "2026-10-30:RELAY", "status": "ok", "relayIndex": 30.6,
            "questionSetVersion": "v7.1",
            "narrative": "模型生成的叙事原文（不得回流）",
            "answers": {"relay_phase": {"choice": "divergence", "confidence": 0.87},
                        "relay_momentum": {"choice": "weakening"},
                        "ladder_health": {"choice": "pyramid"},
                        "money_effect": {"choice": "losing"},
                        "theme_pulse": {"choice": "mainline_continue"},
                        "leader_strength": {"score": 5.25},
                        "relay_index": {"score": 2.75}}}
    payload, degraded = ops.load_relay_judgment(RelayDb(good), "2026-10-30")
    assert payload["ok"] is True and payload["index"] == 30.6
    assert payload["answers"]["relay_phase"] == "divergence"
    assert payload["leaderStrengthScore"] == 5.25 and degraded == []
    assert "narrative" not in payload        # 模型原文不进语料

    payload2, degraded2 = ops.load_relay_judgment(RelayDb({}), "2026-10-30")
    assert payload2 == {"ok": False, "reason": "relay_doc_missing"}
    assert degraded2[0]["source"] == "relay_judgment"


def test_load_eod_judge_and_theme_and_amount(monkeypatch):
    class SentDb:
        def __init__(self, doc):
            self.doc = doc

        def __getitem__(self, name):
            assert name == "hotlist_sentiment"
            return self

        def find_one(self, q):
            assert q["snapshotType"] == "half_hour" and q["slotTime"] == "EOD"
            return self.doc

    doc = {"emotionScore": {"score": 43.0}, "stage": "退潮", "riskLevel": "高",
           "metrics": {"comparison": {
               "today": {"totalTurnover": 5322e8, "mainNetAmount": -105.6e8},
               "yesterday": {"totalTurnover": 5312e8}, "totalChange1d": -2}}}
    payload, degraded = ops.load_eod_judge(SentDb(doc), "2026-10-30")
    assert payload == {"ok": True, "score": 43.0, "stage": "退潮", "riskLevel": "高"}
    assert degraded == []

    amount, adeg = ops.load_market_amount(SentDb(doc), "2026-10-30")
    assert amount["ok"] is True and amount["caliber"] == "pool"   # 无参考集合 → 回退池内口径
    assert amount["todayTurnover"] == 5322e8
    assert amount["yesterdayTurnover"] == 5312e8 and amount["change1d"] == -2
    assert adeg == []

    # 全市场口径优先（market_daily_amount 有当日 → market caliber；SentDb 无该集合 → 异常回退池内）
    class MarketDb:
        def __getitem__(self, name):
            if name == "market_daily_amount":
                return self

            assert name == "hotlist_sentiment"
            return self

        def find_one(self, q):
            return doc

        def find(self, q=None, projection=None):
            return [{"_id": "2026-10-30", "totalAmount": 16744.7e8},
                    {"_id": "2026-10-29", "totalAmount": 15565.2e8},
                    {"_id": "2026-10-28", "totalAmount": 14000e8}]

    mk, mkdeg = ops.load_market_amount(MarketDb(), "2026-10-30")
    assert mk == {"ok": True, "caliber": "market", "todayTurnover": 16744.7e8,
                  "yesterdayTurnover": 15565.2e8, "change1d": 7.58,
                  "prevDate": "2026-10-29"}
    assert mkdeg == []

    p2, d2 = ops.load_eod_judge(SentDb({}), "d")
    assert p2 == {"ok": False, "reason": "eod_doc_missing"} and d2[0]["source"] == "eod_judge"
    p3, d3 = ops.load_market_amount(SentDb({"metrics": {}}), "d")
    assert p3 == {"ok": False, "reason": "turnover_missing"} and d3[0]["reason"] == "turnover_missing"


def test_load_theme_boards_and_promotion(monkeypatch):
    class ThemeDb:
        def __getitem__(self, name):
            assert name == "hotlist_jev_theme_leader_labels"
            return self

        def find(self, q):
            assert q == {"tradingDate": "2026-10-30", "docKind": "sector"}
            return [{"board": "医疗医药", "answers": {
                        "theme_continuation": {"choice": "strong_extend"},
                        "theme_speculation_depth": {"choice": "igniting"}}},
                    {"board": "AI硬件", "answers": {
                        "theme_continuation": {"choice": "ending"},
                        "theme_speculation_depth": {"choice": "igniting"}}}]

    payload, degraded = ops.load_theme_boards(ThemeDb(), "2026-10-30")
    assert payload["ok"] is True and len(payload["boards"]) == 2
    by_name = {b["board"]: b for b in payload["boards"]}
    assert by_name["医疗医药"]["continuation"] == "strong_extend"
    assert degraded == []

    class EmptyThemeDb:
        def __getitem__(self, name):
            return self

        def find(self, q):
            return []

    p2, d2 = ops.load_theme_boards(EmptyThemeDb(), "d")
    assert p2 == {"ok": False, "reason": "theme_sector_docs_missing"}

    p3, d3 = ops.load_promotion(object(), "2026-10-30", None)
    assert p3 == {"ok": False, "reason": "prev_trading_date_unknown"}

    class FakeStatsDb:
        pass

    orig = ops._promotion_stats
    try:
        ops._promotion_stats = lambda db, prev, date, ds: {
            "ok": True, "rate": 23.1, "base": ["a", "b"],
            "promoted": ["a"], "broken": ["b"], "denom": 2}
        p4, d4 = ops.load_promotion(FakeStatsDb(), "2026-10-30", "2026-10-29")
        assert p4 == {"ok": True, "rate": 23.1, "baseCount": 2, "promotedCount": 1,
                      "brokenCount": 1, "denom": 2}   # 只喂数值，代码名单不进语料
        ops._promotion_stats = lambda db, prev, date, ds: {"ok": False, "reason": "x final 缺失"}
        p5, d5 = ops.load_promotion(FakeStatsDb(), "2026-10-30", "2026-10-29")
        assert p5["ok"] is False and "promotion_unavailable" in p5["reason"]
    finally:
        ops._promotion_stats = orig


def test_build_state_v3_blocks():
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    state = corpus.build_state(
        "2026-10-31", facts, dict(EMOTION),
        kpl_wrap={"ok": True, "comment": "综述"},
        relay_judgment={"ok": True, "index": 30.6},
        eod_judge={"ok": True, "stage": "退潮", "riskLevel": "高"},
        theme_boards={"ok": True, "boards": [{"board": "医疗医药", "continuation": "strong_extend"}]},
        market_amount={"ok": True, "todayTurnover": 5322e8},
        promotion={"ok": True, "rate": 23.1})
    assert state["eodJudge"] == {"ok": True, "stage": "退潮", "riskLevel": "高"}
    assert state["themeBoards"]["boards"][0]["board"] == "医疗医药"
    assert state["marketAmount"]["ok"] and state["promotion"]["rate"] == 23.1
    assert "degradedSources" not in state["summary"]
    state2 = corpus.build_state("2026-10-31", facts, dict(EMOTION))
    assert state2["eodJudge"] == {"ok": False, "reason": "eod_judge_unavailable"}
    assert state2["themeBoards"] == {"ok": False, "reason": "theme_boards_unavailable"}
    assert state2["marketAmount"] == {"ok": False, "reason": "market_amount_unavailable"}
    assert state2["promotion"] == {"ok": False, "reason": "promotion_unavailable"}


# ---------------------------------------------------------------- 读口路由

def test_daily_recap_route_four_paths(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app

    class _Col:
        def __init__(self, doc=None, boom=False):
            self.doc, self.boom = doc, boom

        def find_one(self, q=None, *a, **k):
            if self.boom:
                raise RuntimeError("mock db down")
            return self.doc

    class _Db:
        def __init__(self, col):
            self.col = col

        def __getitem__(self, name):
            return self.col

    client = TestClient(app)

    monkeypatch.setattr(_QUESTIONS_ROUTE_PATH, lambda: _Db(_Col()))
    r = client.get("/api/hotlist-jev/daily-recap", params={"date": "2026-10-31"})
    assert r.status_code == 200 and r.json()["missing"] is True
    assert "未生成" in r.json()["missingReason"] and "开火" not in r.json()["missingReason"]

    monkeypatch.setattr(_QUESTIONS_ROUTE_PATH, lambda: _Db(_Col(boom=True)))
    r = client.get("/api/hotlist-jev/daily-recap", params={"date": "2026-10-31"})
    assert r.status_code == 502 and r.json()["ok"] is False

    doc = {"_id": "2026-10-31", "ok": True, "date": "2026-10-31",
           "text": {"conclusion": "c"}, "answers": {}}
    monkeypatch.setattr(_QUESTIONS_ROUTE_PATH, lambda: _Db(_Col(doc)))
    r = client.get("/api/hotlist-jev/daily-recap", params={"date": "2026-10-31"})
    assert r.status_code == 200 and r.json()["missing"] is False
    assert r.json()["report"]["text"]["conclusion"] == "c"
    assert "_id" not in r.json()["report"]

    r = client.get("/api/hotlist-jev/daily-recap")
    assert r.status_code == 422


def test_daily_recap_route_series(monkeypatch):
    """区间列表模式（连板情绪同构）：轻量投影、只列 ok 档、按日期升序。"""
    from fastapi.testclient import TestClient
    from backend.main import app

    class ListCol:
        def find(self, q):
            assert q["ok"] is True and q["_id"]["$gte"] == "2026-10-20" and q["_id"]["$lte"] == "2026-10-31"
            return [{"_id": "2026-10-28", "ok": True, "date": "2026-10-28",
                     "answers": {"plan_bias": {"choice": "空仓观望", "source": "jev"},
                                 "play_style": {"choice": "只看不追", "source": "jev"},
                                 "avoid_focus": {"choice": "高位断板承接", "source": "jev"},
                                 "key_watch": {"choice": "晋级率修复", "source": "jev"}},
                     "ruleAnswers": {"plan_bias": "空仓观望", "play_style": "只看不追",
                                     "avoid_focus": "高位断板承接", "key_watch": "晋级率修复"},
                     "questionSetVersion": "v2", "templateVersion": 3, "skippedJev": False,
                     "generatedAt": "t", "text": {"conclusion": "重载荷不下发"}},
                    {"_id": "2026-10-27", "ok": True, "date": "2026-10-27",
                     "answers": {}, "ruleAnswers": {}, "questionSetVersion": "v2"}]

    class ListDb:
        def __getitem__(self, name):
            return ListCol()

    monkeypatch.setattr(_QUESTIONS_ROUTE_PATH, lambda: ListDb())
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/daily-recap", params={"start": "2026-10-20", "end": "2026-10-31"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and [x["date"] for x in body["series"]] == ["2026-10-27", "2026-10-28"]
    row = body["series"][1]
    assert row["plan_bias"] == "空仓观望" and row["agree"] == 4 and row["questionTotal"] == 4
    assert "text" not in row and "summary" not in row      # 重载荷不下发
