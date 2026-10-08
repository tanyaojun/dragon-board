# -*- coding: utf-8 -*-
"""日度情绪一句话（jev daily line）测试：纯函数 + mock jev（零真实调用，硬红线 §1.2#7）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import BAND_TAGS
from backend.data.repositories import repository_factory
from backend.operations import jev_daily_line as jl
from backend.operations import schedule

# 2026-10-08 真实盘中槽（EOD 44.8 作 close，不入序列）
TODAY_SLOTS = {
    "09:30": 61.6, "10:00": 66.6, "10:30": 53.8, "11:00": 49.4, "11:30": 58.2,
    "13:00": 59.0, "13:30": 56.6, "14:00": 51.0, "14:30": 57.5, "15:00": 44.8,
}
DATE = "2026-10-08"


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: dict = {}
        self.find_results: list = []

    def find(self, query, projection=None):
        return self.find_results

    def find_one(self, query, projection=None):
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = doc


class _FakeDb:
    def __init__(self) -> None:
        self._colls: dict = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection())


def _ok_envelope(answer: str) -> dict:
    return {"result": {"state": "Completed",
                       "result": {"answers": {"daily_shape": {"type": "choice", "choice": answer}}}}}


# ---------------------------------------------------------------- 曲线事实 / 机械判

def test_collect_curve_facts_today():
    facts = jl.collect_curve_facts(TODAY_SLOTS, 44.8)
    assert facts["slotsCount"] == 10
    assert facts["open"] == 61.6 and facts["openSlot"] == "09:30"
    assert facts["close"] == 44.8 and facts["closeSource"] == "eod"
    assert facts["peak"] == 66.6 and facts["peakTime"] == "10:00"
    assert facts["trough"] == 44.8 and facts["troughTime"] == "15:00"
    assert facts["range"] == 21.8
    assert facts["openPos"] == 0.771 and facts["closePos"] == 0.0
    assert facts["peakPos"] == 0.111 and facts["troughPos"] == 1.0
    assert facts["degradedSources"] == []


def test_collect_curve_facts_drops_non_numeric_and_registers():
    slots = dict(TODAY_SLOTS)
    slots["12:00"] = None  # 非数值槽：丢弃计数 + degraded 登记，不伪造
    facts = jl.collect_curve_facts(slots, 44.8)
    assert facts["slotsCount"] == 10
    assert facts["degradedSources"] == [
        {"source": "slots", "reason": "non_numeric_scores: 1", "action": "dropped"}]


def test_collect_curve_facts_missing_eod_falls_back_last_slot():
    facts = jl.collect_curve_facts(TODAY_SLOTS, None)
    assert facts["close"] == 44.8 and facts["closeSource"] == "last_slot"
    assert any(d["source"] == "eod" for d in facts["degradedSources"])


def test_rule_shape_today_is_gaokai_dizou():
    assert jl.rule_shape(jl.collect_curve_facts(TODAY_SLOTS, 44.8)) == "高开低走"


def test_rule_shape_variants():
    didi = {"09:30": 30, "10:00": 35, "11:00": 40, "14:00": 50, "15:00": 60}
    assert jl.rule_shape(jl.collect_curve_facts(didi, 60)) == "低开高走"
    chonggao = {"09:30": 50, "10:00": 65, "11:00": 58, "14:00": 50, "15:00": 46}
    assert jl.rule_shape(jl.collect_curve_facts(chonggao, 46)) == "冲高回落"
    tandi = {"09:30": 55, "10:00": 45, "11:00": 58, "14:00": 56, "15:00": 54}
    assert jl.rule_shape(jl.collect_curve_facts(tandi, 54)) == "探底回升"
    dandan = {"09:30": 58, "10:00": 50, "11:00": 56, "14:00": 62, "15:00": 68}
    assert jl.rule_shape(jl.collect_curve_facts(dandan, 68)) == "单边走强"
    zhai = {"09:30": 50, "10:30": 52, "13:00": 51, "14:00": 53, "15:00": 50.5}
    assert jl.rule_shape(jl.collect_curve_facts(zhai, 50.5)) == "窄幅震荡"


def test_rule_shape_insufficient_slots_is_unknown_with_degraded():
    facts = jl.collect_curve_facts({"09:30": 60, "15:00": 40}, 40)
    assert facts["slotsCount"] == 2
    assert jl.rule_shape(facts) == jl.SHAPE_UNKNOWN


# ---------------------------------------------------------------- 日历 / 分位 / 拼句

def test_calendar_flag_gap_threshold():
    assert jl.calendar_flag("2026-09-30", "2026-10-08") == "节后首日"  # 长假 gap=8
    assert jl.calendar_flag("2026-10-05", "2026-10-08") is None  # 跨周末 gap=3 不触发
    assert jl.calendar_flag(None, "2026-10-08") is None
    assert jl.calendar_flag("bad", "2026-10-08") is None


def test_eod_percentile_sample_guard():
    assert jl.eod_percentile([1.0, 2.0, 3.0], 2.0) is None  # 样本 <8 不硬给
    prior = [float(i) for i in range(20)]  # 0..19
    assert jl.eod_percentile(prior, 10.0) == 50.0
    assert jl.eod_percentile(prior, -1.0) == 0.0


def test_sentence_band_words_keys_track_engine_band_tags():
    # 句内带词字典键集合 = 引擎 BAND_TAGS 单一事实源（防手抄漂移）
    assert set(jl.SENTENCE_BAND_WORDS.keys()) == set(BAND_TAGS)


def test_build_sentence_full_matches_expected_example():
    sentence = jl.build_sentence({"calendarFlag": "节后首日", "shape": "高开低走",
                                  "bandWord": "弱势带", "action": "无入场"})
    assert sentence == "节后首日情绪高开低走收弱势带，策略基线无入场"


def test_build_sentence_degrades_gracefully():
    # unknown 省略形态子句、calendar 空则自然前移
    assert jl.build_sentence({"calendarFlag": None, "shape": "unknown",
                              "bandWord": "弱势带", "action": "无入场"}) == "情绪收弱势带，策略基线无入场"
    assert jl.build_sentence({"calendarFlag": "节后首日", "shape": "unknown",
                              "bandWord": "低温带", "action": "入场3笔"}) == "节后首日情绪收低温带，策略基线入场3笔"
    assert jl.build_sentence({"calendarFlag": None, "shape": "高开低走",
                              "bandWord": "弱势带", "action": "读数暂缺"}) == "情绪高开低走收弱势带，策略基线读数暂缺"


# ---------------------------------------------------------------- 主流程（mock jev，零真实调用）

def _patch_happy_path(monkeypatch, envelope, *, eod=44.8, slots=TODAY_SLOTS, trade_count=0):
    monkeypatch.setattr(jl, "load_eod_scores", lambda end: {"2026-09-30": 59.1, DATE: eod})
    monkeypatch.setattr(jl, "load_day_slot_scores", lambda db, d: slots)
    monkeypatch.setattr(jl, "load_month_trade_count", lambda db, month: trade_count)
    monkeypatch.setattr(jl, "_get_db", lambda: _FakeDb())
    monkeypatch.setattr(jl, "_jev_credentials", lambda: ("acc", "tok"))
    monkeypatch.setattr(jl, "call_jev", lambda *a, **k: (envelope, 123))
    captured: dict = {}
    monkeypatch.setattr(jl, "persist_daily_line",
                        lambda report: captured.setdefault("report", report) and f"line:{report['date']}")
    return captured


def test_run_apply_jev_answer_used(monkeypatch):
    captured = _patch_happy_path(monkeypatch, _ok_envelope("高开低走"))
    result = jl.run_daily_line_for_date(DATE, apply=True)
    assert result["ok"] is True
    report = result["report"]
    assert report["parts"]["shape"] == "高开低走"
    assert report["shapeSource"] == "jev"
    assert report["ruleShape"] == "高开低走"  # 规则交叉核对同判
    assert report["sentence"] == "节后首日情绪高开低走收弱势带，策略基线无入场"
    assert report["parts"]["bandLabel"] == "弱势期"
    assert report["parts"]["bandWord"] == "弱势带"
    assert report["reference"]["prevEod"] == 59.1
    assert report["reference"]["prevEodGapDays"] == 8
    assert report["persistedId"] == f"line:{DATE}"
    assert captured["report"]["date"] == DATE
    assert not any(d["source"] == "daily_shape" for d in report["degraded"])


def test_run_apply_jev_not_completed_falls_back(monkeypatch):
    _patch_happy_path(monkeypatch, {"result": {"state": "Failed"}})
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["shapeSource"] == "rule_fallback"
    assert report["sentence"] == "节后首日情绪高开低走收弱势带，策略基线无入场"  # 句子仍产出（fail-visible 兑底）
    assert any(d["source"] == "daily_shape" and "not_completed" in d["reason"] for d in report["degraded"])


def test_run_apply_jev_invalid_choice_falls_back(monkeypatch):
    _patch_happy_path(monkeypatch, _ok_envelope("乱写的形态"))
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["shapeSource"] == "rule_fallback"
    assert any("invalid_choice" in d["reason"] for d in report["degraded"])


def test_run_apply_jev_insufficient_evidence_keeps_shape_unknown(monkeypatch):
    _patch_happy_path(monkeypatch, _ok_envelope("insufficient_evidence"))
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["parts"]["shape"] == jl.SHAPE_UNKNOWN
    assert report["shapeSource"] == "jev"  # jev 已答（弃权），句子省略形态子句
    assert report["sentence"] == "节后首日情绪收弱势带，策略基线无入场"
    assert any("insufficient_evidence" in d["reason"] for d in report["degraded"])


def test_run_dry_mode_zero_jev_calls(monkeypatch):
    def _boom(*a, **k):  # dry 模式烧调用即测试失败
        raise AssertionError("dry 模式不得调用 jev")

    _patch_happy_path(monkeypatch, {})
    monkeypatch.setattr(jl, "call_jev", _boom)
    result = jl.run_daily_line_for_date(DATE, apply=False)
    report = result["report"]
    assert report["skippedJev"] is True
    assert report["shapeSource"] == "rule"
    assert report["sentence"] == "节后首日情绪高开低走收弱势带，策略基线无入场"


def test_run_no_eod_structured_failure(monkeypatch):
    monkeypatch.setattr(jl, "_get_db", lambda: _FakeDb())
    monkeypatch.setattr(jl, "load_eod_scores", lambda end: {"2026-09-30": 59.1})
    result = jl.run_daily_line_for_date(DATE, apply=True)
    assert result["ok"] is False and result["errorCode"] == "no_eod"


def test_run_insufficient_slots_skips_jev(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("原料不足不得调用 jev")

    _patch_happy_path(monkeypatch, {}, slots={"09:30": 61.6, "15:00": 44.8})
    monkeypatch.setattr(jl, "call_jev", _boom)
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["parts"]["shape"] == jl.SHAPE_UNKNOWN and report["shapeSource"] == "rule"
    assert report["sentence"] == "节后首日情绪收弱势带，策略基线无入场"
    assert any(d["reason"].startswith("insufficient_slots") for d in report["degraded"])


def test_load_day_slot_scores_passthrough_and_end_to_end_degraded(monkeypatch):
    # loader 原样透传不预过滤：缺分槽由 collect_curve_facts 统一登记（评审 P2：生产路径可达性）
    coll = _FakeCollection()
    coll.find_results = [
        {"slotTime": "09:30", "emotionScore": {"score": 61.6}},
        {"slotTime": "10:00", "emotionScore": {"score": None}},
        {"slotTime": "10:30"},
    ]
    fake = _FakeDb()
    fake._colls["hotlist_sentiment"] = coll
    monkeypatch.setattr(jl, "_get_db", lambda: fake)
    raw = jl.load_day_slot_scores(fake, DATE)
    assert raw == {"09:30": 61.6, "10:00": None, "10:30": None}
    _patch_happy_path(monkeypatch, _ok_envelope("高开低走"))
    monkeypatch.setattr(jl, "load_day_slot_scores", lambda db, d: raw)
    result = jl.run_daily_line_for_date(DATE, apply=True)
    assert any(d["reason"] == "non_numeric_scores: 2" for d in result["report"]["degraded"])


def test_run_missing_token_falls_back(monkeypatch):
    _patch_happy_path(monkeypatch, {})
    monkeypatch.setattr(jl, "_jev_credentials", lambda: ("acc", ""))
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["shapeSource"] == "rule_fallback"
    assert report["sentence"]  # 句子仍产出（fail-visible 兑底）
    assert any(d["reason"] == "missing_jev_token" for d in report["degraded"])


def test_run_call_parse_exception_falls_back(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("socket exploded")

    _patch_happy_path(monkeypatch, {})
    monkeypatch.setattr(jl, "call_jev", _raise)
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["shapeSource"] == "rule_fallback"
    assert any(d["reason"].startswith("call_parse_exception") for d in report["degraded"])


def test_run_prior_none_dropped_registered(monkeypatch):
    _patch_happy_path(monkeypatch, _ok_envelope("高开低走"))
    monkeypatch.setattr(jl, "load_eod_scores",
                        lambda end: {"2026-09-28": 50.0, "2026-09-29": None,
                                     "2026-09-30": 59.1, DATE: 44.8})
    result = jl.run_daily_line_for_date(DATE, apply=True)
    report = result["report"]
    assert report["reference"]["prevEodDate"] == "2026-09-30"
    assert any(d["reason"] == "prior_eod_none_dropped: 1" for d in report["degraded"])


# ---------------------------------------------------------------- 落库 / 排程步

def test_persist_daily_line_writes_and_upserts(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: fake)
    doc_id = jl.persist_daily_line({"date": DATE, "sentence": "s"})
    assert doc_id == f"line:{DATE}"
    assert fake["phase_monitor"].docs[f"line:{DATE}"]["kind"] == "daily_line"
    jl.persist_daily_line({"date": DATE, "sentence": "s2"})
    assert fake["phase_monitor"].docs[f"line:{DATE}"]["report"]["sentence"] == "s2"  # 幂等覆盖


def test_persist_daily_line_missing_date_skips(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: fake)
    assert jl.persist_daily_line({"sentence": "s"}) is None
    assert fake["phase_monitor"].docs == {}


def test_schedule_step_dry_run_skips():
    result = schedule._run_jev_daily_line_step(DATE, dry_run=True)
    assert result == {"ok": True, "skipped": True, "reason": "dry_run"}


def test_schedule_step_gate_skips_without_eod(monkeypatch):
    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (False, "no EOD doc"))
    result = schedule._run_jev_daily_line_step(DATE, dry_run=False)
    assert result == {"ok": True, "skipped": True, "reason": "no EOD doc"}


def test_schedule_step_success_path(monkeypatch):
    fake = _FakeDb()
    fake["phase_monitor"].docs[f"line:{DATE}"] = {
        "_id": f"line:{DATE}", "updatedAt": "2099-01-01T00:00:00",
        "report": {"sentence": "节后首日情绪高开低走收弱势带，策略基线无入场"}}

    class _Proc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (True, ""))
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(schedule.repository_factory, "get_runtime_mongodb_database", lambda: fake)
    result = schedule._run_jev_daily_line_step(DATE, dry_run=False)
    assert result["ok"] is True and result["mongoFresh"] is True
    assert result["sentence"] == "节后首日情绪高开低走收弱势带，策略基线无入场"


def test_schedule_step_subprocess_failure_is_structured(monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (True, ""))
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: _Proc())
    result = schedule._run_jev_daily_line_step(DATE, dry_run=False)
    assert result["ok"] is False
    assert result["error"]["code"] == "jev_daily_line_failed"


def test_schedule_step_timeout_is_structured(monkeypatch):
    def _timeout(*a, **k):
        raise schedule.subprocess.TimeoutExpired(cmd="jev_daily_line", timeout=600)

    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (True, ""))
    monkeypatch.setattr(schedule.subprocess, "run", _timeout)
    result = schedule._run_jev_daily_line_step(DATE, dry_run=False)
    assert result["ok"] is False
    assert result["error"]["code"] == "jev_daily_line_timeout"
