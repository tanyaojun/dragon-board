# -*- coding: utf-8 -*-
"""高档个案登记簿测试（零 jev 调用 / 零网络 / 零写入，fake db）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location(
        "theme_leader_high_tier_ledger",
        ROOT / "scripts" / "theme_leader_high_tier_ledger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LG = _load()


class FakeCol:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query=None, projection=None):
        return [dict(d) for d in self.docs
                if all(d.get(k) == v for k, v in (query or {}).items())]

    def find_one(self, query=None, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                return dict(d)
        return None


class FakeDb:
    def __init__(self, labels, relays=()):
        self._labels = FakeCol(labels)
        self._relays = FakeCol(relays)

    def __getitem__(self, name):
        if name == LG.COLLECTION:
            return self._labels
        if name == "hotlist_jev_relay_index":
            return self._relays
        raise KeyError(name)


def _relay(date, choices):
    return {"_id": f"{date}:RELAY",
            "answers": {k: {"choice": v} for k, v in choices.items()}}


def _doc(code, name, date="2026-10-22", tier="high_ge65", **kw):
    d = {
        "_id": f"{date}:{code}", "tradingDate": date, "code": code, "name": name,
        "board": "机器人", "status": "ok", "leaderNextdayContinue": tier,
        "questionSetVersion": "v8",
        "structure": {"streak": 5},
        "answers": {"leader_nextday_continue": {"confidence": 0.41,
                                                "probabilities": {"high_ge65": 0.51}}},
        "outcomeSealedNextDay": True,
        "outcomeDay2": {"date": "2026-10-26", "openPct": 10.03, "closePct": 8.08},
    }
    d.update(kw)
    return d


def test_ledger_lists_high_tier_with_outcome_premium_and_regime():
    db = FakeDb([_doc("603278", "大业股份")],
                [_relay("2026-10-22", {"relay_phase": "divergence",
                                       "relay_momentum": "weakening",
                                       "money_effect": "losing",
                                       "ladder_health": "fracture"})])
    out = LG.build_ledger(db)
    assert out["total"] == 1 and out["sealedCount"] == 1
    r = out["rows"][0]
    assert r["streak"] == 5 and r["conf"] == 0.41 and r["probHigh"] == 0.51
    assert r["day2"]["openPct"] == 10.03 and r["day2"]["closePct"] == 8.08
    assert r["regime"] == {"relay_phase": "divergence", "relay_momentum": "weakening",
                           "money_effect": "losing", "ladder_health": "fracture"}
    assert out["meanDay2ClosePct"] == 8.08
    assert out["maturity"]["readyForBucketing"] is False, "2 例 < 5 门槛=个案登记阶段"


def test_ledger_excludes_superseded_other_tiers_and_skipped():
    db = FakeDb([
        _doc("603278", "大业股份"),
        _doc("603089", "正裕工业", date="2026-10-26", tier="low_25_45",
             outcomeSealedNextDay=None, outcomeDay2=None),
        _doc("603278", "幽灵行", date="2026-10-23", leaderSuperseded=True),
        _doc("603278", "跳过行", date="2026-10-24", status="skipped"),
    ])
    out = LG.build_ledger(db)
    assert out["total"] == 1 and out["rows"][0]["code"] == "603278"


def test_ledger_mean_skips_unknown_outcome_and_premium():
    db = FakeDb([
        _doc("603278", "大业股份"),
        _doc("603089", "正裕工业", date="2026-10-26",
             outcomeSealedNextDay=None, outcomeDay2=None),
    ])
    out = LG.build_ledger(db)
    assert out["total"] == 2 and out["outcomeKnown"] == 1
    assert out["day2PremiumKnown"] == 1 and out["meanDay2ClosePct"] == 8.08


def test_ledger_no_entry_case_has_skipped_premium():
    db = FakeDb([_doc("600094", "大名城", date="2026-10-26",
                      outcomeSealedNextDay=False,
                      outcomeDay2={"date": "2026-10-27",
                                   "skipped": "next_day_not_sealed"})])
    out = LG.build_ledger(db)
    assert out["sealedCount"] == 0 and out["day2PremiumKnown"] == 0
    assert out["meanDay2ClosePct"] is None
    assert out["rows"][0]["day2"]["skipped"] == "next_day_not_sealed"
