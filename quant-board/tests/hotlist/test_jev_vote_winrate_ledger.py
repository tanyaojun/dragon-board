# -*- coding: utf-8 -*-
"""v4-material(b) 两周验证台账测试——全 fake 零 IO。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_vote_winrate_ledger import _score  # noqa: E402


def test_score_frozen_rules():
    assert _score("buy", 3.2) is True and _score("buy", -1.0) is False
    assert _score("sell", -4.1) is True and _score("sell", 2.0) is False
    assert _score("hold", 4.9) is True and _score("hold", 5.0) is False  # |≥5%| 算错
    assert _score("insufficient", 6.0) is None                          # 不计分
    assert _score("hold", None) is None


class _Col:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q=None, projection=None):
        return iter(list(self.docs))

    def find_one(self, q=None, projection=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return d
        return None


class _Rows:
    def find(self, q=None, projection=None):
        sid = q.get("snapshotId")
        if sid and sid.endswith("10-15"):
            return iter([{"code": "600001", "change": 2.0},      # hold 对
                         {"code": "600002", "change": -1.5},     # sell 对
                         {"code": "600003", "change": 6.5}])     # buy 对
        return iter([])


class _FakeDb:
    """最小 fake：frames/dates/rows/analysis/pilot 五集合硬编码一屏。"""

    def __init__(self):
        self.snapshot_frames = _Col([_f("2026-10-14"), _f("2026-10-15"),
                                      _f("2026-10-16")])
        self.snapshot_stock_rows = _Rows()
        self.snapshot_analysis = _Col([_ana("600001", "B")])
        self.hotlist_jev_vote_confirm_pilot = _Col([
            _vote("2026-10-14", "600001", "hold", "B", "buy"),
            _vote("2026-10-14", "600002", "sell", "D", "sell"),
            _vote("2026-10-14", "600003", "buy", "C", "hold"),
        ])

    def __getitem__(self, name):
        return getattr(self, name)


def _f(date):
    return {"datasetId": "dragonboard_live", "type": "half_hour",
            "tradingDate": date, "slotTime": "15:00", "snapshotId": f"sid:{date}"}


def _ana(code, tier):
    return {"code": code, "snapshotId": "sid:2026-10-14",
            "analysis": {"observation": {"synergy": {"signalTier": tier}}}}


def _vote(date, code, direction, tier, rule_dir):
    return {"_id": f"{date}:11:00:{code}:VOTE", "tradingDate": date,
            "slotTime": "11:00", "code": code, "status": "ok",
            "voteDirection": direction, "voteConfidence": 0.8,
            "questionSetVersion": "v4-material", "ammoVersion": "2026-10-13b",
            "synergyTier": tier, "synergyDirection": rule_dir}


def test_ledger_counts_and_verdict():
    from backend.operations import jev_vote_winrate_ledger as led
    db = _FakeDb()
    out = led.build_ledger(db, "dragonboard_live")
    # V4: hold 对(2.0) + sell 对(-1.5) + buy 对(6.5) = 3/3
    assert out["v4"]["n"] == 3 and out["v4"]["win"] == 3
    # 规则线: 600001 buy 错(2.0<5 但 buy 要 >0 ✓ 对)；600002 sell 对；600003 hold 错(6.5)
    assert out["rule"]["n"] == 3 and out["rule"]["win"] == 2
    assert out["summary"]["v4Rate"] == 100.0 and out["summary"]["ruleRate"] == 66.7
    assert out["summary"]["delta"] == 33.3
    assert out["summary"]["verdict"] == "有增量（保留）"
    assert [d["date"] for d in out["days"]] == ["2026-10-14"]

def test_ledger_pending_when_next_day_missing():
    from backend.operations import jev_vote_winrate_ledger as led
    class _NoNext(_FakeDb):
        def __init__(self):
            super().__init__()
            # 只给一个交易日（next_day 不存在）
            self.snapshot_frames.docs = [_f("2026-10-14")]
    out = led.build_ledger(_NoNext(), "dragonboard_live")
    assert out["v4"]["n"] == 0 and out["v4"]["win"] == 0
    assert out["summary"]["v4Rate"] is None and out["summary"]["delta"] is None


def test_ledger_fallback_daily_bars_when_t1_frame_missing():
    from backend.operations import jev_vote_winrate_ledger as led
    class _NoFrameRows(_FakeDb):
        def __init__(self):
            super().__init__()
            # snapshot_stock_rows 返回空，迫使走 _daily_bars 回退
            self.snapshot_stock_rows = _Rows()
            self.snapshot_stock_rows.find = lambda *a, **k: iter([])
    out = led.build_ledger(_NoFrameRows(), "dragonboard_live")
    # TDX 回退在 fake 里无数据，应全部 None 不计分
    assert out["v4"]["n"] == 0


def test_ledger_zero_sample():
    from backend.operations import jev_vote_winrate_ledger as led
    class _Empty(_FakeDb):
        def __init__(self):
            super().__init__()
            self.hotlist_jev_vote_confirm_pilot.docs = []
    out = led.build_ledger(_Empty(), "dragonboard_live")
    assert out["v4"]["n"] == 0 and out["rule"]["n"] == 0
    assert out["summary"]["v4Rate"] is None and out["summary"]["ruleRate"] is None
    assert out["summary"]["delta"] is None and out["summary"]["verdict"] is None


def test_ledger_verdict_delta_zero_triggers_no_increment():
    from backend.operations import jev_vote_winrate_ledger as led
    # 构造平局：V4=1/2=50%, 规则线=1/2=50%
    class _Tie(_FakeDb):
        def __init__(self):
            super().__init__()
            # 600001 hold 对(2.0), 600002 sell 错(1.5 实际涨), 规则线也错
            self.hotlist_jev_vote_confirm_pilot.docs = [
                _vote("2026-10-14", "600001", "hold", "B", "buy"),   # 规则错
                _vote("2026-10-14", "600002", "sell", "D", "sell"),  # 两者都错
            ]
    out = led.build_ledger(_Tie(), "dragonboard_live")
    assert out["v4"]["n"] == 2 and out["rule"]["n"] == 2
    assert out["summary"]["delta"] == 0.0
    assert out["summary"]["verdict"] == "无增量（撤除 vote 判读）"
