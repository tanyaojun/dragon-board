# -*- coding: utf-8 -*-
"""最强风口红名观察采集器测试（2026-11-15 用户裁决「先观察再定」；零真实上游）。

锁定口径：全 mock（get_fengkou/_next_day_pct/db）零网络零真实上游（红线 7）；
fail-visible（红线 4.0）：个别时点降级 doc 照写、T+1 缺股记 missing 不伪造、
全源无数据才不落 doc；幂等：已有 doc 不覆写；pytest 护栏挡真实腾讯调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import fengkou_red_observer as O

DATE = "2026-11-14"
PREV = "2026-11-13"
NEXT = "2026-11-15"


def _fk_payload(pct="10.00", code="002739", name="儒意电影", red=True):
    return {"ok": True, "day": DATE, "n_rows": 2, "items": [
        {"stock_id": code, "name": name, "strength": 2684,
         "trend_state": "0", "change_pct": pct, "main_net": 1,
         "name_red": red, "main_buy": 2, "main_sell": -3,
         "boards": ["影视院线"], "hot_boards": ["影视院线"], "peak_time": "09:35"},
        {"stock_id": "600410", "name": "华胜天成", "strength": 5871,
         "trend_state": "0", "change_pct": "10.00", "main_net": 1,
         "name_red": False, "main_buy": 2, "main_sell": -3,
         "boards": ["AI应用"], "hot_boards": ["AI应用"], "peak_time": "09:50"},
    ]}


class FakeObsCol:
    def __init__(self, docs=None):
        self.docs: dict[str, dict] = {d["_id"]: dict(d) for d in (docs or [])}

    def find_one(self, q, proj=None, sort=None):
        if sort:
            if not self.docs:
                return None
            return dict(self.docs[max(self.docs)])
        return self.docs.get(q.get("_id"))

    def find(self, q, proj=None):
        date_lt = (q.get("date") or {}).get("$lt")
        state = q.get("obsState")
        out = [dict(d) for d in self.docs.values()
               if (state is None or d.get("obsState") == state)
               and (date_lt is None or str(d.get("date")) < date_lt)]
        return iter(out)

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = dict(doc)

    def update_one(self, q, update):
        doc = self.docs.get(q["_id"])
        if doc is not None:
            doc.update(update["$set"])


class FakeFramesCol:
    """snapshot_frames 桩：只回 tradingDate 列表（trading_dates_before 消费）。"""

    def __init__(self, days):
        self.days = list(days)

    def find(self, q, proj=None):
        lt = (q.get("tradingDate") or {}).get("$lt")
        out = [{"tradingDate": d} for d in self.days
               if lt is None or d < lt]
        return iter(out)


class FakePoolCol:
    def __init__(self, names):
        self.names = list(names or [])

    def find_one(self, q, proj=None):
        if not self.names:
            return None
        return {"date": q.get("date"),
                "items": [{"name": n} for n in self.names]}


class FakeDB:
    def __init__(self, docs=None, pool_names=None, trading_days=()):
        self.obs = FakeObsCol(docs)
        self._pool = FakePoolCol(pool_names)
        self._frames = FakeFramesCol(trading_days)

    def __getitem__(self, name):
        if name == O.OBS_COLLECTION:
            return self.obs
        if name == "snapshot_frames":
            return self._frames
        if name == "kpl_daban_pool":
            return self._pool
        raise KeyError(name)


@pytest.fixture(autouse=True)
def _no_real_calls(monkeypatch):
    monkeypatch.setattr(O._fk, "get_fengkou",
                        lambda time_hhmm="": _fk_payload())
    monkeypatch.setattr(O, "_next_day_pct",
                        lambda codes: {"ok": True, "fetchedAt": "t",
                                       "pct": {c: 5.0 for c in codes},
                                       "missingCodes": []})


def test_full_observation_writes_pending_doc():
    db = FakeDB(pool_names=["儒意电影"], trading_days=[PREV, DATE])
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out["ok"] and out["redUnionN"] == 1
    doc = db.obs.docs[DATE]
    assert doc["obsState"] == "pending_next_day"
    assert doc["prevDate"] == PREV
    assert doc["quality"]["probeOkN"] == len(O._PROBE_TIMES)
    red = doc["redUnion"][0]
    assert red["stock_id"] == "002739"
    assert red["times"] == len(O._PROBE_TIMES)
    assert red["inPrevPool"] is True


def test_prev_pool_absent_flagged_not_guessed():
    # T−1 池缺席 → inPrevPool=None + quality.prevPoolAvailable=False（不猜）
    db = FakeDB(pool_names=[], trading_days=[PREV, DATE])
    out = O.run_fengkou_red_observation(DATE, db=db)
    doc = db.obs.docs[DATE]
    assert doc["quality"]["prevPoolAvailable"] is False
    assert doc["redUnion"][0]["inPrevPool"] is None


def test_partial_probe_failure_still_writes(monkeypatch):
    db = FakeDB()

    def flaky(time_hhmm=""):
        if time_hhmm == "1000":
            raise ConnectionError("boom")
        return _fk_payload()

    monkeypatch.setattr(O._fk, "get_fengkou", flaky)
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out["ok"]
    doc = db.obs.docs[DATE]
    bad = [p for p in doc["probes"] if p["time"] == "1000"][0]
    assert bad["ok"] is False and bad["degraded"]
    assert "ConnectionError" in str(bad["reason"])
    assert doc["quality"]["probeOkN"] == len(O._PROBE_TIMES) - 1
    assert doc["redUnion"][0]["times"] == len(O._PROBE_TIMES) - 1


def test_all_degraded_no_doc(monkeypatch):
    db = FakeDB()

    def degraded(time_hhmm=""):
        return {"ok": False, "degraded": True, "reason": "login_expired",
                "login_expired": True}

    monkeypatch.setattr(O._fk, "get_fengkou", degraded)
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out["ok"] is False
    assert out["errorCode"] == "fengkou_red_obs_all_degraded"
    assert DATE not in db.obs.docs  # 全源无数据不落 doc（红线 4.0 唯一不写情形）


def test_backfill_settles_with_missing_visible(monkeypatch):
    # T−1 日 pending + 次日已收盘 → 结算；腾讯缺 1 只 → missing 记录不伪造
    db = FakeDB(docs=[{"_id": PREV, "date": PREV, "obsState": "pending_next_day",
                       "redUnion": [{"stock_id": "002739", "name": "儒意电影",
                                     "times": 6},
                                    {"stock_id": "999999", "name": "已退市",
                                     "times": 2}]}],
                trading_days=[PREV, DATE])

    def partial(codes):
        return {"ok": True, "fetchedAt": "t",
                "pct": {c: (9.9 if c == "002739" else None) for c in codes},
                "missingCodes": ["999999"]}

    monkeypatch.setattr(O, "_next_day_pct", partial)
    out = O.run_fengkou_red_observation(DATE, db=db)
    bf = out["backfill"]["days"]
    assert bf and bf[0]["settled"] and bf[0]["missingN"] == 1
    doc = db.obs.docs[PREV]
    assert doc["obsState"] == "settled"
    assert doc["nextDay"]["date"] == DATE  # trading_days=[PREV, DATE] → T+1=DATE
    assert doc["nextDay"]["pct"]["002739"] == 9.9
    assert doc["nextDay"]["missing"] == ["999999"]


def test_backfill_skips_when_next_day_not_closed():
    # 次日未收盘（trading_days 只有当日）→ 保持 pending（自愈语义）
    db = FakeDB(docs=[{"_id": DATE, "date": DATE, "obsState": "pending_next_day",
                       "redUnion": [{"stock_id": "002739", "name": "儒意电影"}]}],
                trading_days=[DATE])
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out.get("skipped") == "already_observed"
    assert db.obs.docs[DATE]["obsState"] == "pending_next_day"


def test_idempotent_existing_doc_not_overwritten():
    db = FakeDB(docs=[{"_id": DATE, "date": DATE, "obsState": "pending_next_day",
                       "redUnionN": 99, "redUnion": []}])
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out["skipped"] == "already_observed"
    assert db.obs.docs[DATE]["redUnionN"] == 99  # 原档未被动


def test_force_overwrites():
    db = FakeDB(docs=[{"_id": DATE, "date": DATE, "obsState": "pending_next_day",
                       "redUnionN": 99, "redUnion": []}])
    out = O.run_fengkou_red_observation(DATE, db=db, force=True)
    assert out.get("skipped") is None and out["redUnionN"] == 1
    assert db.obs.docs[DATE]["redUnionN"] == 1


def test_pytest_guard_blocks_real_tencent():
    with pytest.raises(RuntimeError, match="红线 7"):
        O._tencent_next_day_pct(["002739"])


def test_dry_run_no_write():
    db = FakeDB()
    out = O.run_fengkou_red_observation(DATE, db=db, dry_run=True)
    assert out["ok"] and out["dryRun"] and DATE not in db.obs.docs


def test_day_mismatch_rejected_no_write(monkeypatch):
    # 评审 P1：CLI --date 历史日（探针实时端点只回最近交易日）→ 错档护栏不落 doc
    db = FakeDB()
    monkeypatch.setattr(O._fk, "get_fengkou", lambda time_hhmm="": _fk_payload())
    out = O.run_fengkou_red_observation("2026-11-10", db=db, force=True)
    assert out["ok"] is False
    assert out["errorCode"] == "fengkou_red_obs_day_mismatch"
    assert "20261114" in out["probeDays"]
    assert "2026-11-10" not in db.obs.docs  # force 亦拦，不静默污染观察材料


def test_day_mismatch_passes_when_day_matches(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(O._fk, "get_fengkou", lambda time_hhmm="": _fk_payload())
    out = O.run_fengkou_red_observation(DATE, db=db, force=True)
    assert out["ok"] and DATE in db.obs.docs


def test_idempotent_skips_before_probes(monkeypatch):
    # 评审 P2：幂等命中时不打探针（零额外上游调用）
    db = FakeDB(docs=[{"_id": DATE, "date": DATE, "obsState": "pending_next_day",
                       "redUnionN": 99, "redUnion": []}])
    calls = []

    def spy(time_hhmm=""):
        calls.append(time_hhmm)
        return _fk_payload()

    monkeypatch.setattr(O._fk, "get_fengkou", spy)
    out = O.run_fengkou_red_observation(DATE, db=db)
    assert out["skipped"] == "already_observed" and calls == []
    assert db.obs.docs[DATE]["redUnionN"] == 99
