# -*- coding: utf-8 -*-
"""收盘链投喂仅保留板块龙一/二/三（2026-11-13 用户裁决）——全 fake/monkeypatch，禁触真实 jev。

裁决：跟风股打标没参考价值且烧 token，slot=final 自动投喂只保留各板块
dragon_rows(top=3) 并集，跟风跳过数披露；显式 --codes（单股重跑路由）与
midday 手动/回填不受限。龙序单一事实源 = dragon_rows（M 降序 → 封板时间升序），
本测试不引入第二套排序逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import run


class _FakeCol:
    def __init__(self, docs: dict | None = None):
        self.docs = docs or {}
        self.replaced: list[tuple[dict, dict]] = []

    def find(self, _query, _projection=None):
        return list(self.docs.values())

    def find_one(self, query, _projection=None, sort=None):
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append((query, doc))


class _FakeDb:
    def __getitem__(self, name):
        if name == "jiuyan_action":
            return _FakeCol({"d1": {"_id": "d1", "tradingDate": "2026-10-09"}})
        return _FakeCol()


def _pop():
    """同板块 5 只（M 降序龙一/二/三 + 2 跟风）+ 异板块独苗 1 只（=该板块龙一）。"""
    return [
        {"stock": {"code": "600001", "name": "龙一", "num": "4天4板", "time": "09:30:00"}, "board": "b"},
        {"stock": {"code": "600002", "name": "龙二", "num": "3天3板", "time": "09:35:00"}, "board": "b"},
        {"stock": {"code": "600003", "name": "龙三", "num": "2天2板", "time": "09:40:00"}, "board": "b"},
        {"stock": {"code": "600004", "name": "跟风甲", "time": "09:45:00"}, "board": "b"},
        {"stock": {"code": "600005", "name": "跟风乙", "time": "09:50:00"}, "board": "b"},
        {"stock": {"code": "300001", "name": "独苗龙一", "time": "10:00:00"}, "board": "c"},
    ]


def _patch(monkeypatch, pop=None):
    monkeypatch.setattr(runner, "_db", lambda: _FakeDb())
    monkeypatch.setattr(runner, "day_population",
                        lambda db_, date, slot="final": _pop() if pop is None else pop)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    # 承接开关显式关：测试只验证投喂范围，不依赖环境变量
    monkeypatch.setattr(runner, "carry_forward_enabled", lambda: False)
    called: list[str] = []

    def _fake_label(db_, col, acc, token, date, code, *a, **k):
        called.append(code)
        return True, 10

    monkeypatch.setattr(runner, "_label_one", _fake_label)
    return called


def test_final_feeds_only_board_dragons(monkeypatch, capsys):
    """final 自动投喂：仅各板块龙一/二/三并集；跟风跳过且计数披露（fail-visible）。"""
    called = _patch(monkeypatch)
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc",
        workers=1, confirm_budget=True)
    assert called == ["600001", "600002", "600003", "300001"]
    out = capsys.readouterr().out
    assert "跳过跟风 2" in out, "跟风跳过数须披露（fail-visible）"


def test_final_dragon_order_follows_dragon_rows_single_source(monkeypatch):
    """同板数按封板时间升序取前三（dragon_rows 单源，不引第二套逻辑）。"""
    pop = [{"stock": {"code": c, "name": n, "num": "2天2板", "time": t}, "board": "b"}
           for c, n, t in [("600001", "A", "09:40:00"), ("600002", "B", "09:39:00"),
                           ("600003", "C", "09:41:00"), ("600004", "D", "09:42:00")]]
    called = _patch(monkeypatch, pop)
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc",
        workers=1, confirm_budget=True)
    assert sorted(called) == ["600001", "600002", "600003"], "封板最晚 09:42 应作跟风跳过"


def test_final_only_codes_bypasses_dragon_gate(monkeypatch):
    """显式 --codes（单股重跑路由）不受龙门限制：跟风股可按需重跑。"""
    called = _patch(monkeypatch)
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc",
        workers=1, confirm_budget=True, force=True, only_codes={"600004"})
    assert called == ["600004"]


def test_midday_manual_not_restricted(monkeypatch):
    """midday 手动/回填保留既有全名单口径（裁决只限收盘自动投喂）。"""
    called = _patch(monkeypatch)
    monkeypatch.setattr(runner, "midday_source_state", lambda db_, date: {"ok": True})
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc",
        workers=1, confirm_budget=True, slot="midday")
    assert sorted(called) == ["300001", "600001", "600002", "600003", "600004", "600005"]


def test_final_dry_run_population_dragon_only(monkeypatch, capsys):
    """dry-run population 同龙口径（叙事预览与实跑投喂范围一致）。"""
    _patch(monkeypatch)
    monkeypatch.setattr(runner, "build_pilot_narrative", lambda *a, **k: "N")
    run("2026-10-09", "2026-10-09", dry_run=True, token="tok", acc="acc",
        workers=1, confirm_budget=True)
    assert "population=4" in capsys.readouterr().out


def test_final_dragon_gate_uppercase_prefix_codes(monkeypatch, capsys):
    """M1 审查回归：大写交易所前缀原料（SZ001318 形态）龙一/二/三不得被龙门静默排除。

    比较口径末 6 位；items 键保持 _strip 历史幂等口径（仅剥小写前缀，_id={date}:{code}
    不漂移），故 called 含原始大写键——本用例同时锁定该口径。"""
    pop = [
        {"stock": {"code": "SZ001318", "name": "龙一", "num": "4天4板", "time": "09:30:00"}, "board": "b"},
        {"stock": {"code": "sh600002", "name": "龙二", "num": "3天3板", "time": "09:35:00"}, "board": "b"},
        {"stock": {"code": "600003", "name": "龙三", "num": "2天2板", "time": "09:40:00"}, "board": "b"},
        {"stock": {"code": "SZ001319", "name": "跟风", "time": "09:45:00"}, "board": "b"},
    ]
    called = _patch(monkeypatch, pop)
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc",
        workers=1, confirm_budget=True)
    assert sorted(called) == ["600002", "600003", "SZ001318"], \
        "大写前缀龙头须保留（末 6 位比较），跟风排除"
    assert "跳过跟风 1" in capsys.readouterr().out
