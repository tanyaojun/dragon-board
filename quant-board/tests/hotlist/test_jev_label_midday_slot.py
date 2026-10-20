# -*- coding: utf-8 -*-
"""午盘投喂槽位（2026-10-20 用户裁决）：12:30 午盘名单投喂 jev，16:00 收盘幂等跳过。

需求原文：
  1) 12:00 从 jiuyangongshe.com 拿到的午盘涨停数据，设 12:30 调度任务投喂给 jev 打标；
  2) 16:00 收盘涨停投喂时幂等跳过——**一只涨停股票数据单日不能重复投喂**。

锁定口径（全部假 db/假 dispatch，零真实 jev 调用，AGENTS §1.2-7）：
- `midday_source_state`：午盘名单必须「中午抓的」；收盘后才补写的伪午盘文档（实测
  2026-10-14/16/19 的 fetchedAt=15:20/20:04/20:23）一律拒绝，交收盘链投喂；
- `build_midday_narrative`：只用午盘确实拿得到的证据，收盘口径弹药显式标不可得（§4.0）；
- `run(slot=...)`：午盘与收盘共用 `_id={date}:{code}` + status=ok 幂等判据 → 单日每股一次；
- `run_jiuyan_midday_label_once`：开关/交易日/名单时点三道门，任一不满足即 skipped 且不开火。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations import schedule as sched
from backend.operations.jev_label_jiuyan import (
    SLOT_FINAL,
    SLOT_MIDDAY,
    build_midday_narrative,
    day_population,
    midday_source_state,
    run,
)

DATE = "2026-10-20"
EXPLAIN = "人形机器人（金属腱绳）+商业航天+光伏+轮胎"


# ── 通用假集合（支持本模块用到的查询算子：等值/$gte/$lte/$regex/$ne/$in） ──────────
def _match(doc: dict, query: dict) -> bool:
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$gte":
                    if val is None or not val >= arg:
                        return False
                elif op == "$lte":
                    if val is None or not val <= arg:
                        return False
                elif op == "$regex":
                    if not re.search(arg, str(val or "")):
                        return False
                elif op == "$ne":
                    if val == arg:
                        return False
                elif op == "$in":
                    if val not in arg:
                        return False
                else:  # pragma: no cover — 未覆盖算子直接失败，避免假集合静默放过
                    raise AssertionError(f"fake collection 未支持算子 {op}")
        elif val != cond:
            return False
    return True


class FakeCol:
    def __init__(self, docs=None):
        self._docs: list[dict] = list(docs or [])

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

    def update_one(self, query, update, upsert=False):
        for d in self._docs:
            if _match(d, query or {}):
                d.update(update.get("$set") or {})
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()


class FakeDb:
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, name):
        return self._cols.setdefault(name, FakeCol())


def _stock(code, name, num=None, day=None, time="09:31:00", price=10.0, expound=EXPLAIN):
    return {"code": code, "name": name, "num": num, "day": day, "time": time,
            "price": price, "expound": expound}


def _day_doc(date, slot, stocks, fetched_at):
    return {"_id": f"{date}:{slot}", "kind": "jiuyan_action", "tradingDate": date,
            "updateKind": slot, "fetchedAt": fetched_at,
            "fields": [{"name": "机器人", "stocks": stocks}]}


def _db_with(midday_fetched="2026-10-20T12:06:00"):
    jy = FakeCol([
        _day_doc(DATE, "midday",
                 [_stock("603278", "大业股份", num="3天3板", day=3, time="09:25:00")],
                 midday_fetched),
        _day_doc(DATE, "final",
                 [_stock("603278", "大业股份", num="3天3板", day=3, time="09:25:00"),
                  _stock("600001", "午后首板", time="13:40:00")],
                 "2026-10-20T15:36:00"),
    ])
    return FakeDb({"jiuyan_action": jy, "hotlist_jev_driver_labels": FakeCol([]),
                   "snapshot_stock_rows": FakeCol([])})


def _fake_parse(env, ms, expected_keys=None):
    return {"ok": True, "answers": {"driver_type": {"choice": "concept_stretch", "probabilities": {"concept_stretch": 0.8}}},
            "usage": {"input_tokens": 100, "output_tokens": 10}, "model": "fake-model",
            "errorCode": None, "errorDetail": None, "latencyMs": ms}


@pytest.fixture
def no_tdx(monkeypatch):
    """TDX 日线/分时一律不可用（假环境里不碰网络），叙事走 fail-visible 分支。"""
    monkeypatch.setattr(runner, "_daily_bars", lambda code: [])
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: [])


# ── 午盘名单时点校验 ───────────────────────────────────────────────────────
def test_midday_source_state_accepts_noon_doc():
    state = midday_source_state(_db_with(), DATE)
    assert state["ok"] is True
    assert state["fetchedAt"] == "2026-10-20T12:06:00"
    assert state["reason"] is None


def test_midday_source_state_rejects_post_close_backfill():
    """实测缺陷复刻：10-14/16/19 的 midday 文档是收盘后才补写的（15:20/20:04/20:23）。"""
    for ts in ("2026-10-19T15:20:44", "2026-10-19T20:04:07", "2026-10-20T15:35:50"):
        state = midday_source_state(_db_with(ts), DATE)
        assert state["ok"] is False and state["found"] is True
        assert state["reason"] == "midday_doc_not_noon"
        assert ts in state["detail"]


def test_midday_source_state_accepts_space_separator_timestamp():
    """fetchedAt 分隔符容错（历史上不保证是 ISO 'T' 形式）：只看 HH:MM。"""
    state = midday_source_state(_db_with("2026-10-20 12:06:00"), DATE)
    assert state["ok"] is True
    assert midday_source_state(_db_with(""), DATE)["reason"] == "midday_doc_not_noon"


def test_midday_source_state_missing_doc():
    state = midday_source_state(FakeDb({"jiuyan_action": FakeCol([])}), DATE)
    assert state["ok"] is False and state["found"] is False
    assert state["reason"] == "no_midday_doc"


def test_day_population_reads_midday_doc():
    db = _db_with()
    mid = day_population(db, DATE, SLOT_MIDDAY)
    fin = day_population(db, DATE, SLOT_FINAL)
    assert [e["stock"]["code"] for e in mid] == ["603278"]
    assert [e["stock"]["code"] for e in fin] == ["603278", "600001"]


# ── 午盘叙事口径（fail-visible） ──────────────────────────────────────────
def test_midday_narrative_marks_unavailable_evidence(no_tdx):
    db = _db_with()
    jy_doc = db["jiuyan_action"].find_one({"_id": f"{DATE}:midday"})
    stock = jy_doc["fields"][0]["stocks"][0]
    text = build_midday_narrative(db, DATE, "603278", stock, "机器人", None, jiuyan_doc=jy_doc)
    head = text.splitlines()[0]
    assert "午盘" in head and "12:06" in head
    # v3.2 D10：三项物理不可得压成首行 1 处（原先 4 行各说一次，≈90 字/只）
    assert "午盘不可得项" in head and "当日板型" in head
    assert text.count("午盘不可得") == 1
    # 位置轴/板序：T-1 收盘口径（T-1 不可得时如实标不可算，不冒充当日）
    assert "个股位置：上一交易日" in text and "板序：上一交易日" in text
    assert "停牌" not in text, "午盘无当日棒不得写成「停牌或数据缺口」（会误导读模型）"
    # v3.2 D4a：热榜排名不再投喂（零引用 + 跨轨坐标系；落库字段照存）
    assert "热榜" not in text
    assert EXPLAIN in text                                        # 解析首行（=原因）在场
    assert "3天3板" in text


def test_midday_position_uses_t1_close_caliber(monkeypatch):
    """v3.2 D10：午盘位置/板序用 T-1 收盘口径（真实可得），行内显式标 T-1、不冒充当日。"""
    db = _db_with()
    jy_doc = db["jiuyan_action"].find_one({"_id": f"{DATE}:midday"})
    stock = jy_doc["fields"][0]["stocks"][0]
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: ["2026-10-16", "2026-10-19"][-n:])
    bars = []
    for i, d in enumerate(["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13",
                           "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"]):
        close = 10.0 + i * 0.1
        bars.append({"date": d, "close": close, "high": close, "vol": 1e7})
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: [])
    text = build_midday_narrative(db, DATE, "603278", stock, "机器人", None, jiuyan_doc=jy_doc)
    assert "个股位置：上一交易日（2026-10-19）收盘口径" in text
    assert "板序：上一交易日（2026-10-19）收盘口径 · 近 " in text
    assert "末位=2026-10-19" in text and "末位今日" not in text   # T-1 口径下不得写「末位今日」
    assert "现价" in text and "当前连板" in text      # T-1 真实可算的数字直供
    assert "午盘涨停价 10.0" in text                # 当日韭研事实不受影响
    assert "昨日同板块" in text                       # v3.2 D7 昨日对照


def test_final_narrative_unchanged_shape(no_tdx):
    """收盘槽位的叙事形态不因午盘改动而漂移（判据代际可比）。"""
    db = _db_with()
    jy_doc = db["jiuyan_action"].find_one({"_id": f"{DATE}:final"})
    stock = jy_doc["fields"][0]["stocks"][0]
    text = runner.build_pilot_narrative(db, DATE, "603278", stock, "机器人", None,
                                        jiuyan_doc=jy_doc, slot=SLOT_FINAL)
    assert text.splitlines()[0].startswith(f"{DATE} 交易日 · ")
    assert "身位：" in text and "韭研解析全文：" in text
    assert "午盘" not in text


# ── 单日每股只投喂一次（午盘 → 收盘幂等跳过） ─────────────────────────────
def _patch_jev(monkeypatch):
    calls: list[str] = []

    def fake_dispatch(narrative, questions):
        calls.append(narrative)
        return ({}, 12)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    monkeypatch.setattr(runner, "parse_jev_response", _fake_parse)
    return calls


def test_run_midday_then_final_skips_same_stock(monkeypatch, no_tdx, capsys):
    db = _db_with()
    monkeypatch.setattr(runner, "_db", lambda: db)
    calls = _patch_jev(monkeypatch)

    run(DATE, DATE, False, "tok", "acc", workers=1, confirm_budget=True, slot=SLOT_MIDDAY)
    assert len(calls) == 1 and "午盘" in calls[0]
    mid_doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{DATE}:603278"})
    assert mid_doc["labelSlot"] == SLOT_MIDDAY
    assert mid_doc["jiuyanSourceId"] == f"{DATE}:midday"
    assert mid_doc["jiuyanFetchedAt"] == "2026-10-20T12:06:00"
    assert mid_doc["status"] == "ok"

    # 收盘链：午盘已投喂的 603278 幂等跳过，只有午后新涨停的 600001 被投喂
    run(DATE, DATE, False, "tok", "acc", workers=1, confirm_budget=True, slot=SLOT_FINAL)
    assert len(calls) == 2, "同一只股票单日不得重复投喂"
    assert "午后首板" in calls[1] and "午盘" not in calls[1]
    fin_doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{DATE}:600001"})
    assert fin_doc["labelSlot"] == SLOT_FINAL
    assert db["hotlist_jev_driver_labels"].find_one({"_id": f"{DATE}:603278"})["labelSlot"] == SLOT_MIDDAY
    out = capsys.readouterr().out
    assert "skippedLabeled=1" in out

    # 再跑一次收盘链：全部已投喂 → 零调用（幂等可重入）
    run(DATE, DATE, False, "tok", "acc", workers=1, confirm_budget=True, slot=SLOT_FINAL)
    assert len(calls) == 2


def test_run_midday_refuses_stale_midday_doc(monkeypatch, no_tdx, capsys):
    """午盘名单是收盘补写的 → 拒绝投喂（不拿收盘数据冒充午盘），且零模型调用。"""
    db = _db_with(midday_fetched="2026-10-20T20:04:07")
    monkeypatch.setattr(runner, "_db", lambda: db)
    calls = _patch_jev(monkeypatch)
    run(DATE, DATE, False, "tok", "acc", workers=1, confirm_budget=True, slot=SLOT_MIDDAY)
    assert calls == []
    assert db["hotlist_jev_driver_labels"].find({}) == []
    assert "午盘名单不可投喂" in capsys.readouterr().out


def test_run_midday_budget_guard(monkeypatch, no_tdx):
    db = _db_with()
    monkeypatch.setattr(runner, "_db", lambda: db)
    _patch_jev(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        run(DATE, DATE, False, "tok", "acc", workers=1, slot=SLOT_MIDDAY)
    assert "--confirm-budget" in str(exc.value)
    assert "midday" in str(exc.value)


# ── 调度步（12:30）：三道门 + 开火参数 ────────────────────────────────────
class _Proc:
    returncode = 0
    stdout = "FINAL: ok"
    stderr = ""


def _patch_schedule(monkeypatch, db, run_calls):
    monkeypatch.setattr(sched, "is_trading_day_cached", lambda d: (True, "weekday"))
    monkeypatch.setattr(sched.repository_factory, "get_runtime_mongodb_database", lambda: db)

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(sched.subprocess, "run", fake_run)


def test_midday_label_step_fires_with_slot_flags(monkeypatch):
    db = _db_with()
    run_calls: list[list[str]] = []
    _patch_schedule(monkeypatch, db, run_calls)
    monkeypatch.delenv("JIUYAN_MIDDAY_LABEL_ENABLED", raising=False)
    result = sched.run_jiuyan_midday_label_once(DATE)
    assert result["ok"] is True and result["sourceFetchedAt"] == "2026-10-20T12:06:00"
    assert len(run_calls) == 1
    cmd = run_calls[0]
    assert "--slot" in cmd and cmd[cmd.index("--slot") + 1] == "midday"
    assert "--confirm-budget" in cmd
    assert cmd[cmd.index("--start") + 1] == DATE and cmd[cmd.index("--end") + 1] == DATE


def test_midday_label_step_disabled_by_env(monkeypatch):
    run_calls: list[list[str]] = []
    _patch_schedule(monkeypatch, _db_with(), run_calls)
    monkeypatch.setenv("JIUYAN_MIDDAY_LABEL_ENABLED", "0")
    result = sched.run_jiuyan_midday_label_once(DATE)
    assert result["skipped"] is True and result["reason"] == "disabled"
    assert run_calls == []


def test_midday_label_step_skips_stale_source(monkeypatch):
    run_calls: list[list[str]] = []
    _patch_schedule(monkeypatch, _db_with(midday_fetched="2026-10-19T20:23:07"), run_calls)
    monkeypatch.delenv("JIUYAN_MIDDAY_LABEL_ENABLED", raising=False)
    result = sched.run_jiuyan_midday_label_once(DATE)
    assert result["skipped"] is True and result["reason"] == "midday_doc_not_noon"
    assert run_calls == []


def test_midday_label_step_dry_run_and_non_trading_day(monkeypatch):
    run_calls: list[list[str]] = []
    _patch_schedule(monkeypatch, _db_with(), run_calls)
    assert sched.run_jiuyan_midday_label_once(DATE, dry_run=True)["reason"] == "dry_run"
    monkeypatch.setattr(sched, "is_trading_day_cached", lambda d: (False, "cache"))
    assert sched.run_jiuyan_midday_label_once(DATE)["reason"] == "non_trading_day"
    assert run_calls == []
