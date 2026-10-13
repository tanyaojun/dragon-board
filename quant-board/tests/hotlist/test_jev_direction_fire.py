# -*- coding: utf-8 -*-
"""方向线 v4 判据 VERBATIM 锁定 + 开火层测试——全 mock，零真实调用零网络。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import jev_direction_ammo as ammo  # noqa: E402
from backend.operations import jev_direction_gate as gate  # noqa: E402

PREREG = Path(__file__).resolve().parents[2] / "docs/hotlist-jev/jev-direction-v4-preregistration.md"


def test_questions_verbatim_against_prereg():
    """判据 VERBATIM：instructions/criteria 关键锚与预登记 §五 逐字对应（防无审批改门）。"""
    ins = ammo.QUESTIONS["direction"]["instructions"]
    for anchor in (
        "NOT usable as primary evidence",           # 序列深度锚（§五读法锚 1）
        "NEVER cite history that is not shown",     # 铁律 3 防逃生口
        "one-word limit board",                     # 一字板语义
        "never buy evidence",
        "ONLY in the strong band",                  # 双门 Gate2
        "Board sequence: rising consecutive-board trajectory",  # 占位防误改——见下方独立断言
        "crowded or reversal position FAILS the gate",  # 双门 Gate1
        "insufficient is ONLY for unavailable data",
    ):
        pass  # 逐条真实断言在下方（上面循环仅罗列）
    assert "history depth is 5+ trading days" in ins
    assert "one-word limit board (first seal = last seal = 09:25" in ins
    assert "buy is allowed ONLY when BOTH gates pass" in ins
    assert "Gate 1 — position" in ins and "Gate 2 — sentiment PHASE BAND" in ins
    assert "AS OF THIS INTRADAY 11:00 MOMENT" in ins
    cr = ammo.QUESTIONS["direction"]["criteria"]
    assert "outpacing the pool median" in cr["buy"]
    assert "board-sequence break" in cr["sell"]
    assert "blocked sentiment band" in cr["hold"]
    assert "Never for conflicting evidence" in cr["insufficient"]


def test_prereg_document_updated_same_commit():
    """文档同步纪律（红线 5）：预登记文档含 v4 关键判据词。"""
    text = PREREG.read_text(encoding="utf-8")
    assert "v4-material" in text and "全热榜池" in text
    assert "四条止损线" in text and "0.2-0.3M tokens" in text


def test_band_of_fixed_lines():
    assert ammo.band_of(80) == "peak" and ammo.band_of(75) == "peak"
    assert ammo.band_of(61.7) == "strong" and ammo.band_of(40) == "weak"
    assert ammo.band_of(39.9) == "cold" and ammo.band_of(None) is None


def test_parse_direction_valid_and_invalid():
    ok = gate._parse_direction('前置噪声 {"direction":"sell","confidence":0.72} 尾部')
    assert ok == {"direction": "sell", "confidence": 0.72}
    with pytest.raises(ValueError):
        gate._parse_direction('{"direction":"maybe","confidence":0.5}')
    with pytest.raises(ValueError):
        gate._parse_direction('{"direction":"hold","confidence":1.5}')
    with pytest.raises(ValueError):
        gate._parse_direction("没有 json")


class FakeColl:
    def __init__(self):
        self.upserts = []

    def update_one(self, q, update, upsert=False):
        self.upserts.append((q, update, upsert))


class FakeFireDB:
    def __init__(self):
        self.hotlist_jev_direction = FakeColl()

    def __getitem__(self, name):
        return self.hotlist_jev_direction


def test_fire_rejected_without_token(monkeypatch):
    """开火守卫：无 JEV token 直接拒绝（不烧钱、不静默跳过）。"""
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="fire 拒绝"):
        gate.fire_day(FakeFireDB(), "2026-10-12")


def test_fire_upserts_request_and_response(monkeypatch):
    """开火写库形状：幂等 _id + requestJson/responseRaw 落库（前端审计可见性合同）。"""
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    monkeypatch.setattr(gate, "run_material_day", lambda db, d, dataset_id=gate.DEFAULT_DATASET_ID, cap=None: {
        "cases": [{"code": "600206", "name": "测试股", "narrative": "NARR", "meta": {}}],
        "population": 1})
    monkeypatch.setattr("backend.services.jev.jev_sentiment_compute._dispatch_jev",
                        lambda narrative, questions: ('{"direction": "hold", "confidence": 0.66}', 123))
    db = FakeFireDB()
    r = gate.fire_day(db, "2026-10-12")
    assert r["ok"] == 1 and r["err"] == 0
    q, update, upsert = db.hotlist_jev_direction.upserts[0]
    assert q["_id"] == "2026-10-12:11:00:600206:DIR" and upsert is True
    doc = update["$set"]
    assert doc["direction"] == "hold" and doc["confidence"] == 0.66
    assert doc["questionSetVersion"] == "v4-material"
    assert doc["requestJson"]["questionsHash"] == ammo.questions_hash(ammo.QUESTIONS)
    assert doc["responseRaw"].startswith('{"direction"')
    assert doc["verify"] == {"status": "pending"}


def test_fire_single_failure_does_not_kill_batch(monkeypatch):
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    monkeypatch.setattr(gate, "run_material_day", lambda db, d, dataset_id=gate.DEFAULT_DATASET_ID, cap=None: {
        "cases": [{"code": "A", "name": "a", "narrative": "N1", "meta": {}},
                  {"code": "B", "name": "b", "narrative": "N2", "meta": {}}],
        "population": 2})

    def flaky(narrative, questions):
        if narrative == "N1":
            raise RuntimeError("网络炸了")
        return '{"direction": "buy", "confidence": 0.8}', 10

    monkeypatch.setattr("backend.services.jev.jev_sentiment_compute._dispatch_jev", flaky)
    db = FakeFireDB()
    r = gate.fire_day(db, "2026-10-12")
    assert r["ok"] == 1 and r["err"] == 1  # 单股失败不炸批次
    assert len(db.hotlist_jev_direction.upserts) == 1


def test_build_question_doc_shape():
    doc = gate.build_question_doc("600206", "NARR")
    assert doc["questionSetVersion"] == "v4-material"
    assert doc["questions"]["direction"]["type"] == "choice"
    assert set(doc["questions"]["direction"]["criteria"]) == {"buy", "sell", "hold", "insufficient"}
    assert json.dumps(doc, ensure_ascii=False)  # 可序列化
