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

_QUESTIONS_ROUTE_PATH = "backend.data.repositories.repository_factory.get_runtime_mongodb_database"

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
    monkeypatch.setattr(ops, "load_kpl_wrap", lambda db, date: ({"ok": True, "time": "15:00", "comment": "综述", "fromArchive": True}, []))
    monkeypatch.setattr(ops, "load_relay_judgment", lambda db, date: ({"ok": True, "index": 30.6, "answers": {}}, []))
    monkeypatch.setattr(ops, "load_eod_judge", lambda db, date: ({"ok": True, "score": 43.0, "stage": "退潮", "riskLevel": "高"}, []))
    monkeypatch.setattr(ops, "load_theme_boards", lambda db, date: ({"ok": True, "boards": []}, []))
    monkeypatch.setattr(ops, "load_market_amount", lambda db, date: ({"ok": True, "todayTurnover": 1.0, "yesterdayTurnover": 1.0, "change1d": 0, "mainNetAmount": None}, []))
    monkeypatch.setattr(ops, "load_promotion", lambda db, date, prev: ({"ok": True, "rate": 23.1, "baseCount": 39, "promotedCount": 9, "brokenCount": 30, "denom": 39}, []))


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
    # 判据只引用 state 字段：不含未定义占位符；无开发黑话/无预判提示（开火前文本清理）
    for spec in qs.values():
        for v in spec["criteria"].values():
            assert "{" not in v and "}" not in v
            assert "开火" not in v and "贫料" not in v
    assert "净流入未转负" not in qs["money_style"]["criteria"]["低吸为主"], \
        "判据不得包含机械判不核对的资金预判"


def test_build_state_no_duplicate_degraded_sources():
    """投喂语料去重：degradedSources 只在顶层一份，summary 内剔除（开火前文本清理）。"""
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    state = corpus.build_state("2026-10-31", facts, {"eod": 62.0})
    assert "degradedSources" not in state["summary"]
    assert state["degradedSources"] == facts["degradedSources"]
    assert "degradedSources" not in state["summary"]["rise"]


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
    # 未知/未判定档位 → 不足段（不硬编故事；且无开发黑话入页）
    n2 = corpus.compose_recap_text("d", f, {}, {"recap_shape": None})["narrative"]
    assert "原料不足" in n2 and "开火" not in n2


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
    assert rep["answers"]["recap_shape"]["choice"] == "强势延续"
    assert "hotlist_jev_daily_recap" not in db.collections      # 零写库
    assert "persistedId" not in rep


def test_apply_happy_path_jev_sources_and_persist(material, monkeypatch):
    answers = {"recap_shape": "强势延续", "money_style": "接力为主", "plan_bias": "进攻",
               "focus_direction": "算力", "risk_flag": "中风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))  # conftest 护栏清空 token
    monkeypatch.setattr(ops, "dispatch_jev_call",
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
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(invalid))
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
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(answers))
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
    monkeypatch.setattr(ops, "dispatch_jev_call",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["jev"] is None
    assert rep["answers"]["recap_shape"]["source"] == "rule_fallback"
    assert rep["text"]["conclusion"]          # 机械版成文仍在（fail-visible 不丢当日日报）


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


def test_partial_missing_material_still_emits(monkeypatch):
    """部分缺料（单页缺）仍出包出日报（§4.0 fail-visible：不硬门禁不静默）。"""
    monkeypatch.setattr(ops, "load_emotion", lambda db, date: (dict(EMOTION), []))
    monkeypatch.setattr(ops, "collect_rise_review", lambda db, date: {"ok": False})
    monkeypatch.setattr(ops, "collect_dieban_review", lambda db, date: mk_dieban())
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call",
                        lambda *a, **k: ({"success": False, "errors": [{"message": "network: x"}]}, 5))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    assert rep["ok"] is True
    assert any(d["reason"] == "review_doc_unavailable" for d in rep["degraded"])
    assert rep["answers"]["recap_shape"]["source"] == "rule_fallback"
    assert rep["text"]["conclusion"]          # 机械版成文仍在


# ---------------------------------------------------------------- 评审修复（2026-10-31）回归

def test_nodata_page_registered_with_reason():
    """评审 Major-1：ok=True+noData=True 页必须登记结构化原因（门2 degraded 率不得低估）。"""
    nodata_rise = {"ok": True, "noData": True, "reason": "2026-10-31 无 half_hour 快照行（未回填）",
                   "degraded": [], "stocks": []}
    facts = corpus.collect_review_facts(nodata_rise, mk_dieban())
    assert facts["rise"]["noData"] is True
    hit = [d for d in facts["degradedSources"] if d["source"] == "rise" and d["action"] == "page_no_data"]
    assert len(hit) == 1 and "无 half_hour 快照行" in hit[0]["reason"]
    # 单页 noData 仍按可数锚点机械判（fail-visible 不硬门禁）
    assert corpus.rule_recap_shape(facts) == "混沌轮动"


def test_focus_direction_skips_unsegmented_bucket():
    """评审 nit：「未分板块」兕底桶不得成为主攻方向档位。"""
    facts = corpus.collect_review_facts(
        mk_rise(positive={"netInflowTotal": 1e8, "topBoards": [{"board": "未分板块", "count": 3},
                                                               {"board": "算力", "count": 2}]}),
        mk_dieban())
    assert corpus.rule_focus_direction(facts) == "算力"
    qs = corpus.build_questions(facts)
    assert "未分板块" not in qs["focus_direction"]["criteria"]
    # 全部为未分板块 → 空仓观望
    facts2 = corpus.collect_review_facts(
        mk_rise(positive={"netInflowTotal": 1e8, "topBoards": [{"board": "未分板块", "count": 3}]}),
        mk_dieban())
    assert corpus.rule_focus_direction(facts2) == "空仓观望"


def test_apply_plan_bias_insufficient_override_keeps_degraded_consistent(material, monkeypatch):
    """评审 Minor-1：plan_bias 被 jev 判 insufficient 又被兕底覆盖时，degraded 记录同步改写。"""
    answers = {"recap_shape": "退潮防守", "money_style": "观望为主",
               "plan_bias": "insufficient_evidence", "focus_direction": "空仓观望",
               "risk_flag": "高风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(answers))
    rep = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())["report"]
    # 兜底跟随最终 recap_shape（退潮防守→防守），落库 degraded 与 answers 自洽
    assert rep["answers"]["plan_bias"] == {"choice": "防守", "source": "rule_fallback"}
    pb = [d for d in rep["degraded"] if d["source"] == "plan_bias"]
    assert len(pb) == 1 and pb[0]["action"] == "rule_fallback"
    assert "plan_bias_insufficient_overridden" in pb[0]["reason"]


def test_apply_missing_token_full_rule_fallback(material, monkeypatch):
    """评审 Minor-3②：apply 但缺 jev token → 全机械判兜底 + degraded 登记，不炸不烧。"""
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", ""))
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=FakeDb())
    rep = result["report"]
    assert rep["skippedJev"] is False and rep["jev"] is None
    assert all(rep["answers"][q]["source"] == "rule_fallback" for q in QUESTION_KEYS)
    assert any(d["source"] == "jev" and d["reason"] == "missing_jev_token"
               for d in rep["degraded"])


def test_apply_force_recomputes_existing_ok_doc(material, monkeypatch):
    """评审 Minor-3①：--force 对已有 ok 文档仍重算（幂等跳过仅缺省生效）。"""
    answers = {"recap_shape": "分歧加剧", "money_style": "低吸为主", "plan_bias": "均衡",
               "focus_direction": "算力", "risk_flag": "中风险"}
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(answers))
    db = FakeDb()
    col = db.collections.setdefault("hotlist_jev_daily_recap", FakeCol())
    col.docs["2026-10-31"] = {"_id": "2026-10-31", "ok": True}
    result = ops.run_daily_recap_for_date("2026-10-31", apply=True, force=True, db=db)
    assert result.get("skipped") is None
    assert result["report"]["answers"]["recap_shape"]["choice"] == "分歧加剧"
    # 缺省（无 force）仍幂等跳过
    result2 = ops.run_daily_recap_for_date("2026-10-31", apply=True, db=db)
    assert result2.get("skipped") is True


def test_daily_recap_route_four_paths(monkeypatch):
    """评审 Minor-3④：读口四条路径（422 缺参 / 502 读库异常 / missing / 命中投影）。"""
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
    assert "_id" not in r.json()["report"]          # 内部键不下发

    r = client.get("/api/hotlist-jev/daily-recap")  # 缺 date → 422
    assert r.status_code == 422


def test_load_kpl_wrap_found_strips_ai_note(monkeypatch):
    """语料 v2：15:00 大盘综述原样入语料（剔 AI 生成尾注）；判别词单一事实源复用。"""
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

    # 非综述时点/判别词不命中 → 显式降级（不拿其他时点冒充综述）
    class NoWrapDb:
        def __getitem__(self, name):
            return self

        def find_one(self, q):
            return {"_id": "d", "items": [{"time": "14:55", "comment": "尾盘低迷"}]}

    payload2, degraded2 = ops.load_kpl_wrap(NoWrapDb(), "d")
    assert payload2 == {"ok": False, "reason": "no_15:00_wrap_in_archive"}
    assert degraded2[0]["source"] == "kpl_wrap" and degraded2[0]["action"] == "corpus_absent"

    # 归档整缺
    class EmptyDb:
        def __getitem__(self, name):
            return self

        def find_one(self, q):
            return None

    payload3, degraded3 = ops.load_kpl_wrap(EmptyDb(), "d")
    assert payload3 == {"ok": False, "reason": "archive_missing"}
    assert degraded3[0]["reason"] == "archive_missing"


def test_load_relay_judgment_structured_only(monkeypatch):
    """语料 v2：连板情绪判定只喂结构化档位；缺档/非 ok 显式降级；narrative 原文不回流。"""
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

    payload3, degraded3 = ops.load_relay_judgment(RelayDb({"status": "degraded"}), "2026-10-30")
    assert payload3 == {"ok": False, "reason": "relay_status_degraded"}


def test_build_state_v2_blocks_and_fail_visible():
    """语料 v2：kplWrap/relayJudgment 入 state 顶层；缺料 ok:false 透传。"""
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    state = corpus.build_state("2026-10-31", facts, {"eod": 62.0},
                               kpl_wrap={"ok": True, "comment": "综述"},
                               relay_judgment={"ok": True, "index": 30.6})
    assert state["kplWrap"] == {"ok": True, "comment": "综述"}
    assert state["relayJudgment"] == {"ok": True, "index": 30.6}
    assert "degradedSources" not in state["summary"]
    state2 = corpus.build_state("2026-10-31", facts, {"eod": 62.0})
    assert state2["kplWrap"] == {"ok": False, "reason": "kpl_wrap_unavailable"}
    assert state2["relayJudgment"] == {"ok": False, "reason": "relay_judgment_unavailable"}


def test_load_eod_judge_and_theme_and_amount(monkeypatch):
    """语料 v3：EOD 结构化判定（half_hour EOD 同源）；题材方向块；量能锚点。"""

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
    assert amount["ok"] is True and amount["todayTurnover"] == 5322e8
    assert amount["yesterdayTurnover"] == 5312e8 and amount["change1d"] == -2
    assert adeg == []

    # 缺档/缺量能 → 显式降级
    p2, d2 = ops.load_eod_judge(SentDb({}), "d")
    assert p2 == {"ok": False, "reason": "eod_doc_missing"} and d2[0]["source"] == "eod_judge"
    p3, d3 = ops.load_market_amount(SentDb({"metrics": {}}), "d")
    assert p3 == {"ok": False, "reason": "turnover_missing"} and d3[0]["reason"] == "turnover_missing"


def test_load_theme_boards_and_promotion(monkeypatch):
    """语料 v3：题材方向块（板块级 doc 枚举）；晋级率（复用 _promotion_stats 单一算式）。"""

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
    assert by_name["AI硬件"]["continuation"] == "ending"
    assert degraded == []

    # 无板块档 → 显式降级（不伪造空名单）
    class EmptyThemeDb:
        def __getitem__(self, name):
            return self

        def find(self, q):
            return []

    p2, d2 = ops.load_theme_boards(EmptyThemeDb(), "d")
    assert p2 == {"ok": False, "reason": "theme_sector_docs_missing"}
    assert d2[0]["reason"] == "theme_sector_docs_missing"

    # 晋级率：prev_date 缺 → 降级；正常 → 数值透传（内部 _promotion_stats 由 ops 引用替换）
    p3, d3 = ops.load_promotion(object(), "2026-10-30", None)
    assert p3 == {"ok": False, "reason": "prev_trading_date_unknown"}
    assert d3[0]["reason"] == "prev_trading_date_unknown"

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
        assert d4 == []
        ops._promotion_stats = lambda db, prev, date, ds: {"ok": False, "reason": "x final 缺失"}
        p5, d5 = ops.load_promotion(FakeStatsDb(), "2026-10-30", "2026-10-29")
        assert p5["ok"] is False and "promotion_unavailable" in p5["reason"]
    finally:
        ops._promotion_stats = orig


def test_build_state_v3_blocks():
    """语料 v3：四块入 state 顶层；缺料 ok:false 透传。"""
    facts = corpus.collect_review_facts(mk_rise(), mk_dieban())
    state = corpus.build_state(
        "2026-10-31", facts, {"eod": 43.0},
        kpl_wrap={"ok": True, "comment": "综述"},
        relay_judgment={"ok": True, "index": 30.6},
        eod_judge={"ok": True, "stage": "退潮", "riskLevel": "高"},
        theme_boards={"ok": True, "boards": [{"board": "医疗医药", "continuation": "strong_extend"}]},
        market_amount={"ok": True, "todayTurnover": 5322e8},
        promotion={"ok": True, "rate": 23.1})
    assert state["eodJudge"] == {"ok": True, "stage": "退潮", "riskLevel": "高"}
    assert state["themeBoards"]["boards"][0]["board"] == "医疗医药"
    assert state["marketAmount"]["ok"] and state["promotion"]["rate"] == 23.1
    state2 = corpus.build_state("2026-10-31", facts, {"eod": 43.0})
    assert state2["eodJudge"] == {"ok": False, "reason": "eod_judge_unavailable"}
    assert state2["themeBoards"] == {"ok": False, "reason": "theme_boards_unavailable"}
    assert state2["marketAmount"] == {"ok": False, "reason": "market_amount_unavailable"}
    assert state2["promotion"] == {"ok": False, "reason": "promotion_unavailable"}


def test_persist_failure_marks_result_and_degraded(material, monkeypatch):
    """评审 Minor-2：落库失败 → persistFailed 顶层可见（main 据此 exit 1），degraded 登记。"""
    monkeypatch.setattr(ops, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(ops, "dispatch_jev_call", lambda *a, **k: _envelope(
        {"recap_shape": "强势延续", "money_style": "接力为主", "plan_bias": "进攻",
         "focus_direction": "算力", "risk_flag": "中风险"}))

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
