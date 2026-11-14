# -*- coding: utf-8 -*-
"""监管风险补采 CLI 合同测试（2026-11-15 review M2/m1/m5 补）。

钉住：日期校验先于发弹；预算门控先于发弹（预留预期发数）；dry-run 计数不写库；
正常路径与 archiver 同写路径。全 mock（红线 7，零真实 HTTP）。
"""
from __future__ import annotations

import backend.operations.kpl_regulatory_collect as C


class _Col:
    def __init__(self):
        self.docs = {}

    def find_one(self, q, projection=None):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    def update_one(self, q, update, upsert=False):
        d = self.docs.setdefault(q["_id"], {"_id": q["_id"]})
        d.update(update.get("$set") or {})
        for k, v in (update.get("$inc") or {}).items():
            base = d
            parts = k.split(".")
            for p in parts[:-1]:
                base = base.setdefault(p, {})
            base[parts[-1]] = base.get(parts[-1], 0) + v


class _Db:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, n):
        return self.cols.setdefault(n, _Col())


def _payload(date="2026-11-13"):
    return {"date": date, "calls": 5, "states": {"severe": {"ok": True}},
            "groups": {"today": []}, "by_code": {"600327": {}}}


def test_invalid_date_no_fetch(monkeypatch):
    called = []
    monkeypatch.setattr(C, "collect_regulatory",
                        lambda d: called.append(d) or _payload())
    assert C.collect_once(db=_Db(), date="foo")["reason"] == "invalid_date"
    assert C.collect_once(db=_Db(), date="2026-13-99")["reason"] == "invalid_date"
    assert not called                      # 校验先于发弹，不污染 latest 档


def test_budget_pre_gate_no_fetch(monkeypatch):
    db = _Db()
    db[C.COLLECTION_API_CALLS].docs["2026-11-13"] = {
        "_id": "2026-11-13", "calls": {"regulatory": 6}}
    called = []
    monkeypatch.setattr(C, "collect_regulatory",
                        lambda d: called.append(d) or _payload())
    r = C.collect_once(db=db, date="2026-11-13")
    assert r["reason"] == "budget_exhausted" and not called   # 6+5>10 发弹前 skip


def test_dry_run_counts_but_not_writes(monkeypatch):
    db = _Db()
    monkeypatch.setattr(C, "collect_regulatory", lambda d: _payload())
    r = C.collect_once(db=db, date="2026-11-13", dry_run=True)
    assert r["ok"] and r["dry_run"]
    assert db[C.COLLECTION_API_CALLS].docs["2026-11-13"]["calls"]["regulatory"] == 5
    assert not db.cols.get("kpl_daban_pool", _Col()).docs     # 不写库


def test_normal_writes_and_counts(monkeypatch):
    db = _Db()
    monkeypatch.setattr(C, "collect_regulatory", lambda d: _payload())
    r = C.collect_once(db=db, date="2026-11-13")
    assert r["ok"] is True
    assert db["kpl_daban_pool"].docs["2026-11-13"]["reg_date"] == "2026-11-13"
    assert db[C.COLLECTION_API_CALLS].docs["2026-11-13"]["calls"]["regulatory"] == 5
