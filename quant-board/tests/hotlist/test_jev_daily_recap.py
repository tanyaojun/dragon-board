# -*- coding: utf-8 -*-
"""复盘日报测试（operations/jev_daily_recap + services/jev/jev_daily_recap_corpus）。

预登记：docs/hotlist-jev/jev-daily-recap-design.md（2026-10-31 用户裁决）。
全离线：mock call_jev / FakeDb，零网络零真库零模型调用（硬红线 §1.2#7）。
覆盖：语料拼装 fail-visible（部分缺料出包+degraded；全缺 no_material 不烧题）、
机械判分支全路、逐题无效答案兜底、成文模板（含机械版兜底）、dry 零调用零写库、
幂等跳过、短叙事预写文段库选段。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_daily_recap as ops
from backend.services.jev import jev_daily_recap_corpus as corpus

QUESTION_KEYS = ("recap_shape", "money_style", "plan_bias", "focus_direction", "risk_flag")


def mk_rise(**kw):
    base = {
        "ok": True, "noData": False,
        "pool": {"up": 30, "down": 5, "ratio": 6.0, "strong": 3, "streak2": 4, "maxStreak": 4,
                 "maxStreakName": "龙头A"},
        "fullRise": {"count": 400},
        "positive": {"netInflowTotal": 2.0e8, "topBoards": [{"board": "算力", "count": 8},
                                                            {"board": "机器人", "count": 5}]},
        "degraded": [{"scope": "ret3d", "reason": "insufficient_history"}],
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


EMOTION = {"eod": 62.0, "prevEod": 55.0, "prevEodDate": "2026-10-30", "eod20dPercentile": 80.0,
           "bandTag": "强60-80", "bandLabel": "高温带", "dailyLineSentence": "情绪收高温带",
           "dailyShape": "单边走强"}


@pytest.fixture()
def material(monkeypatch):
    """数据装载边界：两页复盘 + 情绪锚点固定；call_jev 由各用例自行 monkeypatch。"""
    monkeypatch.setattr(ops, "load_emotion", lambda db, date: (dict(EMOTION), []))
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: mk_rise())
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: mk_dieban())


# ---------------------------------------------------------------- 语料拼装（纯函数）

def test_collect_review_facts_shape_counts_and_passthrough():
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    assert facts["rise"]["shapes"] == {"big_face": 1, "zha_ban": 1, "fade": 1,
                                       "high_close": 1, "tail_dive": 0, "up": 0, "down": 0, "flat": 0}
    assert facts["dieban"]["limitDownCount"] == 3
    assert facts["rise"]["topStocks"][0]["code"] == "1"      # 涨幅降序
    assert facts["dieban"]["topStocks"][0]["code"] == "9"    # 跌幅升序
    # 逐页 degraded 透传（fail-visible：ret3d 缺史不静默）
    assert any(d["source"] == "rise" and "ret3d" in d["reason"] for d in facts["degradedSources"])


def test_collect_review_facts_missing_page_not_false():
    facts = corpus.collect_review_facts(None, mk_dieban())
    assert facts["rise"]["noData"] is True
    assert facts["dieban"]["noData"] is False
    assert any(d["reason"] == "review_doc_unavailable" for d in facts["degradedSources"])


def test_rule_recap_shape_all_branches():
    # 强势延续：涨跌比≥2 且 大面≤炸板 且 连涨高度≥3
    assert corpus.rule_recap_shape(corpus.collect_review_facts(mk_rise(), mk_dieban())) == "强势延续"
    # 分歧加剧：两旺(≥10/≥10) 且 大面>0 且 强势>0（强市分支先被破坏：ratio<2）
    f = corpus.collect_review_facts(
        mk_rise(pool={"up": 20, "down": 12, "ratio": 1.7, "strong": 1, "streak2": 0, "maxStreak": 1},
                stocks=[{"pctChange": 8, "shape": "big_face"}, {"pctChange": 6, "shape": "high_close"}]),
        mk_dieban())
    assert corpus.rule_recap_shape(f) == "分歧加剧"
    # 退潮防守：大面>强势 且 跌停≥5
    f = corpus.collect_review_facts(
        mk_rise(pool={"up": 3, "down": 30, "ratio": 0.1, "strong": 0, "streak2": 0, "maxStreak": 1},
                stocks=[{"pctChange": -2, "shape": "big_face"}, {"pctChange": -4, "shape": "big_face"}]),
        mk_dieban(fullMarket={"count": 6}))
    assert corpus.rule_recap_shape(f) == "退潮防守"
    # 冰点修复：连跌高度≥3 且 池内涨≥跌（强市/两旺/退潮分支先破坏）
    f = corpus.collect_review_facts(
        mk_rise(pool={"up": 12, "down": 10, "ratio": 1.2, "strong": 0, "streak2": 0, "maxStreak": 1},
                stocks=[{"pctChange": 6, "shape": "up"}]),
        mk_dieban(pool={"up": 8, "down": 20, "dieban": 3, "deepDrop": 2, "oneWord": 0,
                        "streak2": 3, "maxStreak": 3}))
    assert corpus.rule_recap_shape(f) == "冰点修复"
    # 混沌轮动：以上均不满足
    f = corpus.collect_review_facts(
        mk_rise(pool={"up": 3, "down": 2, "ratio": 1.5, "strong": 0, "streak2": 0, "maxStreak": 1},
                stocks=[{"pctChange": 1, "shape": "up"}]),
        mk_dieban())
    assert corpus.rule_recap_shape(f) == "混沌轮动"
    # 两页全缺 → insufficient_evidence
    assert corpus.rule_recap_shape(corpus.collect_review_facts({"ok": False}, {"ok": False})) \
        == "insufficient_evidence"


def test_rule_money_plan_focus_risk():
    f = corpus.collect_review_facts(mk_rise(), mk_dieban())
    assert corpus.rule_money_style(f) == "低吸为主"       # ratio≥2 但 大面=1≠0（形态分化）
    f0 = corpus.collect_review_facts(
        mk_rise(stocks=[s for s in mk_rise()["stocks"] if s["shape"] != "big_face"]), mk_dieban())
    assert corpus.rule_money_style(f0) == "接力为主"      # ratio≥2 且 大面=0
    assert corpus.rule_plan_bias("强势延续") == "进攻"
    assert corpus.rule_plan_bias("退潮防守") == "防守"
    assert corpus.rule_plan_bias("混沌轮动") == "均衡"
    assert corpus.rule_plan_bias("insufficient_evidence") == "insufficient_evidence"
    assert corpus.rule_focus_direction(f) == "算力"        # 板块 top1
    assert corpus.rule_risk_flag(f) == "中风险"            # 大面1<5、跌停3<10、非全低风险
    # 观望/高风险：大面≥5
    f2 = corpus.collect_review_facts(
        mk_rise(stocks=[{"pctChange": -1, "shape": "big_face"}] * 5), mk_dieban())
    assert corpus.rule_money_style(f2) == "观望为主"
    assert corpus.rule_risk_flag(f2) == "高风险"


def test_build_questions_focus_choices_dynamic_and_all_five():
    qs = corpus.build_questions(corpus.collect_review_facts(mk_rise(), mk_dieban()))
    assert set(qs) == set(QUESTION_KEYS)
    assert list(qs["focus_direction"]["criteria"]) == ["算力", "机器人", "空仓观望"]  # top8 + 空仓观望
    # 判据只引用 state 字段：不含未定义占位符
    for spec in qs.values():
        for v in spec["criteria"].values():
            assert "{" not in v and "}" not in v


# ---------------------------------------------------------------- 成文模板 / 短叙事

def test_compose_recap_text_slots_and_missing():
    f = corpus.collect_review_facts(mk_rise(), mk_dieban())
    slots = {"recap_shape": "强势延续", "money_style": "接力为主", "plan_bias": "进攻",
             "focus_direction": "算力", "risk_flag": "中风险"}
    text = corpus.compose_recap_text("2026-10-31", f, {"eod": 62.0, "bandLabel": "高温带",
                                                       "eod20dPercentile": 80.0}, slots)
    assert "强势延续（接力为主）" in text["conclusion"]
    assert "上涨400家" in text["conclusion"] and "跌停3家" in text["conclusion"]
    assert "大面1·炸板1·冲高回落1·强势1·尾盘跳水0" in text["conclusion"]
    assert "倾向进攻，主攻方向算力" in text["plan"]
    assert "非交易信号" in text["plan"]
    # 缺槽 → 未判定/暂缺（不伪造档位）
    text2 = corpus.compose_recap_text("2026-10-31", f, {}, {"recap_shape": None})
    assert "未判定" in text2["conclusion"] and "暂缺" in text2["conclusion"]


def test_narrative_library_selection_and_fallback():
    f = corpus.collect_review_facts(mk_rise(), mk_dieban())
    n = corpus.compose_recap_text("d", f, {}, {"recap_shape": "强势延续", "focus_direction": "算力"})["narrative"]
    assert "连涨梯队最高4板" in n and "算力" in n
    # 未知/未判定档位 → 不足段（不硬编故事）
    n2 = corpus.compose_recap_text("d", f, {}, {"recap_shape": None})["narrative"]
    assert "原料不足" in n2


# ---------------------------------------------------------------- 主流程（dry / apply / 幂等）

def test_dry_run_zero_call_zero_write(material, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry 模式不得真调用 jev")
    monkeypatch.setattr(ops, "call_jev", boom)
    db = FakeDb()
    result = ops.run_daily_recap_for_date("2026-10-31", apply=False, db=db)
    assert result["ok"] and result["report"]["skippedJev"] is True
    rep = result["report"]
    assert all(rep["answers"][q]["source"] == "rule_dry" for q in QUESTION_KEYS)
    assert rep["answers"]["recap_shape"]["choice"] == "强势延续"
    assert "hotlist_jev_daily_recap" not in db.collections      # 零写库
    assert "persistedId" not in rep


def test_apply_happy_path_jev_sources_and_persist(material, monkeypatch):
    answers = {"recap_shape": "强势延续", "money_style": "接力为主", "plan_bias": "进攻",
               "focus_direction": "算力", "risk_flag": "中风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))  # conftest 护栏清空 token
    monkeypatch.setattr(ops, "call_jev",
                        lambda *a, **k: _envelope(answers, usage={"totalTokens": 99}))
    db = FakeDb()
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=db)["report"]
    assert all(rep["answers"][q]["source"] == "jev" for q in QUESTION_KEYS)
    assert rep["usage"] == {"totalTokens": 99}
    assert rep["text"]["conclusion"].startswith("【复盘结论】强势延续")
    assert db.collections["hotlist_jev_daily_recap"].docs["2026-10-31"]["_id"] == "2026-10-31"
    assert rep["persistedId"] == "2026-10-31"


def test_apply_invalid_choice_rule_fallback_plan_follows_final_shape(material, monkeypatch):
    invalid = {"recap_shape": "胡说八道", "money_style": "接力为主", "plan_bias": "乱来",
               "focus_direction": "不存在的板块", "risk_flag": "中风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "call_jev", lambda *a, **k: _envelope(invalid))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    # 无效答案逐题兜底；有效答案（money_style/risk_flag）仍采信 jev
    assert rep["answers"]["recap_shape"]["source"] == "rule_fallback"
    assert rep["answers"]["plan_bias"]["source"] == "rule_fallback"
    assert rep["answers"]["focus_direction"]["source"] == "rule_fallback"
    assert rep["answers"]["money_style"]["source"] == "jev"
    assert rep["answers"]["risk_flag"]["source"] == "jev"
    # recap_shape 兜底=机械判；plan_bias 兜底跟随最终 recap_shape（强势延续→进攻）
    assert rep["answers"]["recap_shape"]["choice"] == "强势延续"
    assert rep["answers"]["plan_bias"]["choice"] == "进攻"
    assert any(d["reason"].startswith("invalid_choice") for d in rep["degraded"])


def test_apply_jev_insufficient_slot_unjudged(material, monkeypatch):
    answers = {"recap_shape": "insufficient_evidence", "money_style": "接力为主",
               "plan_bias": "进攻", "focus_direction": "算力", "risk_flag": "中风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "call_jev", lambda *a, **k: _envelope(answers))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["answers"]["recap_shape"]["choice"] is None
    assert rep["answers"]["recap_shape"]["source"] == "jev_insufficient"
    # plan_bias 题本身已被 jev 有效作答 → 照常采信；兜底跟随最终 recap_shape 只在 plan 缺答时生效
    assert rep["answers"]["plan_bias"] == {"choice": "进攻", "source": "jev"}
    assert any(d["source"] == "recap_shape" and d["reason"] == "insufficient_evidence"
               for d in rep["degraded"])
    assert "原料不足" in rep["text"]["narrative"]      # 短叙事按 recap_shape=None 落不足段


def test_apply_call_failure_full_rule_fallback(material, monkeypatch):
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "call_jev",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["jev"] is None
    assert rep["answers"]["recap_shape"]["source"] == "rule_fallback"
    assert rep["text"]["conclusion"]          # 机械版成文仍在（fail-visible 不丢当日日报）


def test_no_material_no_jev(material, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("贫料日不得烧 jev")
    monkeypatch.setattr(ops, "call_jev", boom)
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


def test_partial_missing_material_still_emits(monkeypatch):
    """部分缺料（单页缺）仍出包出日报（§4.0 fail-visible：不硬门禁不静默）。"""
    monkeypatch.setattr(ops, "load_emotion", lambda db, date: (dict(EMOTION), []))
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: {"ok": False})
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: mk_dieban())
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "call_jev",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["ok"] is True
    assert any(d["reason"] == "review_doc_unavailable" for d in rep["degraded"])
    assert rep["answers"]["recap_shape"]["source"] == "rule_fallback"
    assert rep["text"]["conclusion"]          # 机械版成文仍在
