# -*- coding: utf-8 -*-
"""kpl_live_archive merge-union / 晨间归档测试（review minor-11 补覆盖；零网络零 jev）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_live_archive as A

DATE = time.strftime("%Y-%m-%d")


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find_one(self, query=None, projection=None):
        d = self.docs.get((query or {}).get("_id"))
        return dict(d) if d else None

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def update_one(self, flt, update, upsert=False):
        d = self.docs.setdefault(flt["_id"], {"_id": flt["_id"]})
        d.update(update.get("$set") or {})


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _ts(hhmm: str) -> int:
    return int(time.mktime(time.strptime(f"{DATE} {hhmm}", "%Y-%m-%d %H:%M")))


def _payload(items):
    return {"ok": True, "items": items, "notice": "n"}


def test_merge_union_idempotent_and_commutative():
    db = FakeDb()
    a = _payload([{"id": "zb:1", "ts": _ts("09:15"), "time": "09:15", "comment": "x"},
                  {"id": "zb:2", "ts": _ts("10:00"), "time": "10:00", "comment": "y"}])
    b = _payload([{"id": "zb:2", "ts": _ts("10:00"), "time": "10:00", "comment": "y"},
                  {"id": "zb:3", "ts": _ts("15:00"), "time": "15:00", "comment": "z"}])
    m1 = A.merge_live_archive(db, DATE, a)
    m1b = A.merge_live_archive(db, DATE, a)          # 幂等
    assert m1b["itemCount"] == 2
    m2 = A.merge_live_archive(db, DATE, b)
    assert {i["id"] for i in m2["items"]} == {"zb:1", "zb:2", "zb:3"}
    db2 = FakeDb()
    A.merge_live_archive(db2, DATE, b)
    m3 = A.merge_live_archive(db2, DATE, a)          # 交换律
    assert {i["id"] for i in m3["items"]} == {"zb:1", "zb:2", "zb:3"}


def test_merge_empty_items_no_write_and_keep_projection():
    db = FakeDb()
    col = db[A.LIVE_ARCHIVE_COLLECTION]
    col.docs[DATE] = {"_id": DATE, "items": [{"id": "zb:1", "ts": 1, "time": "09:15",
                                             "comment": "x"}],
                      "auctionPush": {"stocks": [{"code": "603135"}]}, "itemCount": 1}
    before = dict(col.docs[DATE])
    A.merge_live_archive(db, DATE, _payload([]))     # 空 items 不覆盖
    assert col.docs[DATE] == before
    A.merge_live_archive(db, DATE, _payload([{"id": "zb:9", "ts": 2, "time": "15:00",
                                              "comment": "z"}]))
    assert col.docs[DATE]["auctionPush"] == {"stocks": [{"code": "603135"}]}  # keep
    assert col.docs[DATE]["itemCount"] == 2


def test_archive_morning_live_push_ok_missing_failed():
    db = FakeDb()
    push_item = {"id": "zb:p", "ts": _ts("09:15"), "time": "09:15",
                 "comment": "竞价看龙头：机器人中重科技",
                 "stocks": [{"code": "603135", "name": "中重科技", "pct": 3.0}]}
    st = A.archive_morning_live(db, DATE, fetcher=lambda st=100: _payload([push_item]))
    assert st["ok"] and st["pushState"] == "ok" and st["rosterN"] == 1
    assert A.load_auction_push(db, DATE)["stocks"][0]["code"] == "603135"
    db2 = FakeDb()
    st2 = A.archive_morning_live(db2, DATE, fetcher=lambda st=100: _payload(
        [{"id": "zb:x", "ts": _ts("10:00"), "time": "10:00", "comment": "盘中播报"}]))
    assert st2["ok"] and st2["pushState"] == "missing" and st2["rosterN"] == 0
    assert A.load_auction_push(db2, DATE)["stocks"] == []     # 留痕不伪造
    db3 = FakeDb()

    def boom(st=100):
        raise RuntimeError("upstream_502")
    st3 = A.archive_morning_live(db3, DATE, fetcher=boom)
    assert st3["ok"] is False and st3["pushState"] == "fetch_failed"
    st4 = A.archive_morning_live(db3, DATE, fetcher=lambda st=100: {"ok": False, "reason": "x"})
    assert st4["pushState"] == "fetch_failed"
    assert A.load_auction_push(FakeDb(), DATE) is None