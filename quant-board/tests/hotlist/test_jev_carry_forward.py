# -*- coding: utf-8 -*-
"""连板承接（方案 A）+ 解析去重压缩（方案 B）测试——纯假 db/假 dispatch，零真实 jev 调用。

2026-10-20 用户裁决「采纳 A+B」：
- A：证据签名未变（解析正文逐字相同 + 题集/原料同代 + 上一判定 ≤2 交易日内）→
  driver_type/catalyst_depth/catalyst_freshness 承接，只重判 buy_side_logic（+相位）；
- B：承接路径叙事保留「首行原因 + 事件型事项行」，非事件核实段省略并声明。

锁定口径：
1. 承接必须在文档里可追溯（labelSource/carriedFrom/carriedQuestionKeys/reevaluatedQuestionKeys/
   carriedQuestionSetHash 齐全），不得伪装成当日独立判定；
2. 承接路径**只问买盘逻辑**（题集=单题），叙事**变短**（B 生效）；
3. 任一条件不满足 → 退回全量四题实判（不静默降级、不假装承接）；
4. `--force`/开关关闭 → 全量实判。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.analysis.hotlist.jev_carry_forward import (
    CARRY_KEYS,
    compress_narrative,
    carry_decision,
    doc_expound_signature,
    expound_block,
    expound_signature,
)

D1, D2, D3 = "2026-10-15", "2026-10-16", "2026-10-19"
EXPLAIN = ("人形机器人（金属腱绳）+商业航天+光伏+轮胎\n"
           "1、公司主营业务以胎圈钢丝、钢帘线以及胶管钢丝的研产销为主，"
           "公司机器人腱绳产品总体尚处于探索试验阶段，目前未实现批量生产。\n"
           "2、2025年12月4日，公司参加航空轮胎用缆型胎圈钢丝标准研讨，"
           "缆型胎圈钢丝技术长期被国外垄断，公司成功打破技术壁垒。")


# ── 纯函数：签名 / 切块 ──────────────────────────────────────────────────
def test_expound_signature_normalizes_numbering_and_whitespace():
    a = expound_signature("主线A+题材B\n1、细节一\n2、细节二")
    b = expound_signature("  主线A+题材B  \n\n1. 细节一\n2、  细节二\n")
    assert a == b, "行首编号/空白差异不应算证据变化"
    assert expound_signature("主线A+题材B\n1、细节一（改）") != a
    assert expound_signature("") is None and expound_signature(None) is None


def test_doc_expound_signature_prefers_stored_field_and_falls_back_to_narrative():
    stored = {"expoundSignature": "abc123", "narrative": "whatever"}
    assert doc_expound_signature(stored) == "abc123"
    narr = "该股：X\n韭研解析全文：\n" + EXPLAIN
    legacy = {"narrative": narr}
    assert doc_expound_signature(legacy) == expound_signature(EXPLAIN)
    assert doc_expound_signature({}) is None
    assert expound_block("无解析行") is None


# ── 纯函数：B 压缩 ────────────────────────────────────────────────────
def _narrative(expound=EXPLAIN):
    return "\n".join([
        "2026-10-16 交易日 · 盘面事实：涨停 59 家",
        "该股：大业股份（603278），今日涨停价 9.91，2天2板",
        "身位：THS 封板梯队：2连板 · 首封 09:37",
        "板块地位：所属韭研板块「机器人」今日涨停 10 家，该股板块内 第 2 封板",
        "韭研解析全文：",
        expound,
    ])


def test_compress_keeps_reason_and_event_lines_only():
    out, stats = compress_narrative(_narrative(), D1)
    assert stats["applied"] is True
    assert stats["prevDate"] == D1
    assert stats["keptItems"] == 1 and stats["droppedItems"] == 1  # 事件行=标准研讨；基建段被省略
    assert EXPLAIN.split("\n")[0] in out                      # 首行（=涨停原因）保留
    assert "缆型胎圈钢丝" in out                               # 事件行正文保留（判 buy_side 需要）
    assert "未实现批量生产" not in out                          # 非事件核实段省略
    assert f"正文与前一日 {D1} 逐字相同" in out and "已省略" in out
    assert stats["droppedChars"] > 0
    # 头尾 4 行（盘面/该股/身位/板块地位）原样保留
    for keep in ("盘面事实", "该股：大业股份", "身位：THS", "板块地位："):
        assert keep in out


def test_compress_noop_paths_are_explicit():
    # 无解析块
    out, stats = compress_narrative("该股：X\n盘面事实：…", D1)
    assert out == "该股：X\n盘面事实：…" and stats == {"applied": False, "reason": "no_expound_block"}
    # 正文为空
    out, stats = compress_narrative("勾\n韭研解析全文：\n", D1)
    assert stats["applied"] is False and stats["reason"] == "empty_expound_body"
    # 正文全是事件行 → 无可省
    event_only = "主线A\n1、中标 XX 项目\n2、量产公告披露"
    out, stats = compress_narrative(_narrative(event_only), D1)
    assert stats["applied"] is False and stats["reason"] == "no_non_event_item"
    assert out == _narrative(event_only)


# ── 纯函数：A 准入 ────────────────────────────────────────────────────
def _prev_doc(date=D2, expound=EXPLAIN, status="ok", qs="qsh", ammo="2026-10-16a"):
    return {"code": "603278", "tradingDate": date, "status": status,
            "questionSetHash": qs, "ammoVersion": ammo,
            "narrative": _narrative(expound),
            "answers": {"driver_type": {"choice": "concept_stretch"},
                        "catalyst_depth": {"choice": "core_main_business"},
                        "catalyst_freshness": {"choice": "continuing"},
                        "buy_side_logic": {"choice": "sector_follow"}}}


def _decide(prev_doc, expound=EXPLAIN, gap=1, qs="qsh", ammo="2026-10-16a"):
    return carry_decision(today_expound=expound, prev_doc=prev_doc,
                          today_question_set_hash=qs, today_ammo_version=ammo,
                          gap_trading_days=gap)


def test_carry_decision_eligible_and_reasons():
    ok = _decide(_prev_doc())
    assert ok["eligible"] is True and ok["prevDate"] == D2 and ok["reason"] is None
    assert _decide(_prev_doc(), expound="")["reason"] == "no_expound"
    assert _decide(None)["reason"] == "no_prev_doc"
    assert _decide(_prev_doc(), gap=3)["reason"] == "gap_too_far"
    assert _decide(_prev_doc(), gap=None)["reason"] == "gap_too_far"
    assert _decide(_prev_doc(status="degraded"))["reason"] == "prev_not_ok"
    assert _decide(_prev_doc(qs="other"))["reason"] == "prev_question_set_mismatch"
    assert _decide(_prev_doc(ammo="2026-10-11a"))["reason"] == "prev_ammo_mismatch"
    assert _decide(_prev_doc(), expound="主线A+题材B\n1、细节（新）")["reason"] == "expound_changed"
    broken = _prev_doc()
    broken["answers"] = {"driver_type": {"choice": "concept_stretch"}}
    dec = _decide(broken)
    assert dec["reason"] == "prev_answers_incomplete"
    assert set(dec["missing"]) == {"catalyst_depth", "catalyst_freshness"}


# ── 假 db / 假 dispatch ────────────────────────────────────────────────
def _match(doc: dict, query: dict) -> bool:
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$gte" and (val is None or not val >= arg):
                    return False
                if op == "$lte" and (val is None or not val <= arg):
                    return False
                if op == "$lt" and (val is None or not val < arg):
                    return False
                if op == "$regex" and not re.search(arg, str(val or "")):
                    return False
                if op == "$ne" and val == arg:
                    return False
                if op == "$in" and val not in arg:
                    return False
                if op not in ("$gte", "$lte", "$lt", "$regex", "$ne", "$in"):
                    raise AssertionError(f"fake 未支持算子 {op}")
        elif val != cond:
            return False
    return True


class FakeCol:
    def __init__(self, docs=None):
        self._docs = [dict(d) for d in (docs or [])]

    def find(self, query=None, projection=None):
        return [dict(d) for d in self._docs if _match(d, query or {})]

    def find_one(self, query, projection=None, sort=None):
        for d in self._docs:
            if _match(d, query or {}):
                return dict(d)
        return None

    def replace_one(self, query, doc, upsert=False):
        for i, d in enumerate(self._docs):
            if _match(d, query or {}):
                self._docs[i] = dict(doc)
                return type("R", (), {"matched_count": 1, "upserted_id": None})()
        if upsert:
            self._docs.append(dict(doc))
        return type("R", (), {"matched_count": 0, "upserted_id": doc.get("_id")})()


class FakeDb:
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, name):
        return self._cols.setdefault(name, FakeCol())


def _stock(expound=EXPLAIN):
    return {"code": "603278", "name": "大业股份", "num": "3天3板", "day": 3,
            "time": "09:25:00", "price": 10.9, "expound": expound}


def _jiuyan(date, expound=EXPLAIN):
    return {"_id": f"{date}:final", "kind": "jiuyan_action", "tradingDate": date,
            "fetchedAt": f"{date}T15:36:00",
            "fields": [{"name": "机器人", "stocks": [_stock(expound)]}]}


def _db(day2_expound=EXPLAIN):
    return FakeDb({
        # 交易日轴（trading_dates_before 查 snapshot_frames）
        "snapshot_frames": FakeCol([{"tradingDate": d, "type": "half_hour",
                                     "datasetId": runner.DEFAULT_DATASET_ID,
                                     "slotTime": "15:00"} for d in (D1, D2, D3)]),
        "jiuyan_action": FakeCol([_jiuyan(D2), _jiuyan(D3, day2_expound)]),
        "hotlist_jev_driver_labels": FakeCol([]),
        "snapshot_stock_rows": FakeCol([]),
    })


def _patch_dispatch(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_dispatch(narrative, questions):
        calls.append((narrative, questions))
        return ({}, 12)

    def fake_parse(env, ms, expected_keys=None):
        answers = {}
        for key in expected_keys or ():
            answers[key] = {"choice": "sector_follow", "probabilities": {"sector_follow": 0.9}}
        if "driver_type" in answers:
            answers["driver_type"] = {"choice": "concept_stretch",
                                      "probabilities": {"concept_stretch": 0.8}}
            answers["catalyst_depth"] = {"choice": "core_main_business", "probabilities": {}}
            answers["catalyst_freshness"] = {"choice": "continuing", "probabilities": {}}
        return {"ok": True, "answers": answers,
                "usage": {"input_tokens": 900, "output_tokens": 60},
                "model": "fake", "errorCode": None, "errorDetail": None, "latencyMs": ms}

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    monkeypatch.setattr(runner, "parse_jev_response", fake_parse)
    return calls


@pytest.fixture
def no_tdx(monkeypatch):
    monkeypatch.setattr(runner, "_daily_bars", lambda code: [])
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: [])


def test_run_carries_three_fields_and_asks_only_buy_side(monkeypatch, no_tdx, capsys):
    db = _db()
    monkeypatch.setattr(runner, "_db", lambda: db)
    calls = _patch_dispatch(monkeypatch)
    # 先把 D2 打成实判基线（模拟"上一标签日"）
    runner.run(D2, D2, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL, carry_forward=False)
    assert len(calls) == 1 and set(calls[0][1]) == {"driver_type", "catalyst_depth",
                                                    "catalyst_freshness", "buy_side_logic"}
    base = db["hotlist_jev_driver_labels"].find_one({"_id": f"{D2}:603278"})
    assert base["labelSource"] == "fresh_judgment"
    assert base["expoundSignature"] == expound_signature(EXPLAIN)

    # D3 解析正文逐字相同 → A 承接 + B 压缩，只问买盘逻辑
    runner.run(D3, D3, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL, carry_forward=True)
    assert len(calls) == 2
    narrative, questions = calls[1]
    assert set(questions) == {"buy_side_logic"}, "承接路径只重判买盘逻辑"
    assert "已省略" in narrative and "正文与前一日" in narrative, "B 压缩须生效"
    doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{D3}:603278"})
    assert doc["labelSource"] == "carry_forward"
    assert doc["carriedFrom"] == D2
    assert set(doc["carriedQuestionKeys"]) == set(CARRY_KEYS)
    assert doc["reevaluatedQuestionKeys"] == ["buy_side_logic"]
    assert doc["carriedQuestionSetHash"] == base["questionSetHash"]
    assert doc["label"] == "concept_stretch" and doc["catalystDepth"] == "core_main_business"
    assert doc["freshness"] == "continuing" and doc["buySideLogic"] == "sector_follow"
    # answers 仍是完整四题（承接 3 + 实判 1），下游消费零变化
    assert set(doc["answers"]) == {"driver_type", "catalyst_depth", "catalyst_freshness",
                                   "buy_side_logic"}
    assert doc["narrativeCompression"]["applied"] is True
    assert doc["askedQuestionSetHash"] != doc["questionSetHash"], "实问题集 hash 须与四题集区分"
    assert "carried=1" in capsys.readouterr().out


def test_run_falls_back_to_full_judgment_when_expound_changed(monkeypatch, no_tdx):
    db = _db(day2_expound=EXPLAIN + "\n3、新增：中标 5 亿元订单（今日新增事件）")
    monkeypatch.setattr(runner, "_db", lambda: db)
    calls = _patch_dispatch(monkeypatch)
    runner.run(D2, D2, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL, carry_forward=False)
    runner.run(D3, D3, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL, carry_forward=True)
    assert set(calls[1][1]) == {"driver_type", "catalyst_depth", "catalyst_freshness",
                                "buy_side_logic"}, "证据变化必须全量重判"
    doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{D3}:603278"})
    assert doc["labelSource"] == "fresh_judgment" and "carriedFrom" not in doc


def test_run_force_and_env_switch_disable_carry(monkeypatch, no_tdx):
    db = _db()
    monkeypatch.setattr(runner, "_db", lambda: db)
    calls = _patch_dispatch(monkeypatch)
    monkeypatch.setenv("JEV_CARRY_FORWARD_ENABLED", "0")
    assert runner.carry_forward_enabled() is False
    runner.run(D2, D2, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL)
    runner.run(D3, D3, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL)
    assert len(calls) == 2 and all(len(q) == 4 for _, q in calls), "开关关闭=全量实判"
    # force 也不承接（口径代际重放必须全量）
    monkeypatch.setenv("JEV_CARRY_FORWARD_ENABLED", "1")
    runner.run(D3, D3, False, "tok", "acc", workers=1, confirm_budget=True,
               slot=runner.SLOT_FINAL, force=True)
    assert len(calls) == 3 and len(calls[2][1]) == 4
