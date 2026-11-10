# -*- coding: utf-8 -*-
"""collector 推送即落库测试（2026-11-10 用户裁决：与直播文本同款时点，不等盘后轮询）。

红线来源（AGENTS §1.2-8）：2013 题材热度 / 2203 涨停原因推送解析成功后，采集线程内
立即写 kpl_daban_pool 日档（archive_theme_corpus / archive_reason_corpus 同一函数），
不再依赖 :8000 archiver 盘后轮询——2026-11-09 盘中未跑 archiver 导致题材热度全天
缺档的根因修复。

pytest 纪律：全部注入假库（corpus_db_factory），不碰真实 MongoDB、不启动采集线程。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.kpl_collector_service import KplCollectorService


class _FakeCodec:
    """最小 codec 桩：本测试不真正收流，只调 persist 方法。"""


class _FakeColl:
    def __init__(self):
        self.rows: dict = {}

    def find_one(self, query=None, projection=None):
        return self.rows.get((query or {}).get("_id"))

    def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        doc = self.rows.setdefault(_id, {"_id": _id})
        doc.update(update["$set"])


class _FakeDb:
    def __init__(self):
        self._coll = _FakeColl()

    def __getitem__(self, name):
        return self._coll


def _collector(db: _FakeDb, pool_date: str = "2026-11-10") -> KplCollectorService:
    svc = KplCollectorService(_FakeCodec(), corpus_db_factory=lambda: db,
                              human_delay=False)
    # 预置涨停池页快照（2103 pid=1），提供语料日档日期
    svc._daban_lists[1] = {0: {"index": 0, "date": pool_date, "ts": 1.0,
                               "items": [{"stock_id": "601188"}]}}
    return svc


def test_theme_push_persists_immediately():
    """2013 推送 → theme_items 立即写日档（不等盘后 archiver 轮询）。"""
    db = _FakeDb()
    svc = _collector(db, pool_date="2026-11-10")
    svc._persist_corpus("theme", {"items": [{
        "stock_id": "601188", "name": "龙江交通",
        "themes": [{"id": "80001", "name": "冰雪经济", "number": 96.5}],
        "ts": 1794500000.0}]})
    row = db._coll.rows["2026-11-10"]
    assert [m["stock_id"] for m in row["theme_items"]] == ["601188"]
    assert row["theme_items"][0]["themes"][0]["number"] == 96.5
    assert row["theme_source"] == "socket_2013"
    assert svc._corpus_persist_stats["theme_ok"] == 1


def test_reason_push_persists_immediately():
    """2203 推送 → reason_items 立即写日档。"""
    db = _FakeDb()
    svc = _collector(db, pool_date="2026-11-10")
    svc._persist_corpus("reason", {"reasons": {
        "601188": {"stock_id": "601188", "zt": "冰雪经济+中俄贸易",
                   "ts": 1794500000.0}}})
    row = db._coll.rows["2026-11-10"]
    assert row["reason_items"][0]["stock_id"] == "601188"
    assert row["reason_items"][0]["zt"] == "冰雪经济+中俄贸易"
    assert svc._corpus_persist_stats["reason_ok"] == 1


def test_persist_without_pool_date_is_structured_skip():
    """无涨停池快照日期 → 结构化跳过不写（不猜日期不错挂）。"""
    db = _FakeDb()
    svc = _collector(db)
    svc._daban_lists.clear()   # 无 2103 快照
    svc._persist_corpus("theme", {"items": [{"stock_id": "601188", "themes": []}]})
    assert not db._coll.rows, "无交易日不写"
    assert svc._corpus_persist_stats["theme_fail"] == 1
    assert "no_pool_date" in svc._corpus_persist_stats["last_error"]


def test_persist_failure_does_not_raise_and_is_visible():
    """落库异常 → 记账 + 事件，绝不抛出阻断收流。"""
    class _BoomDb:
        def __getitem__(self, name):
            raise RuntimeError("db down")

    svc = KplCollectorService(_FakeCodec(), corpus_db_factory=lambda: _BoomDb(),
                              human_delay=False)
    svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                               "items": [{"stock_id": "601188"}]}}
    svc._persist_corpus("theme", {"items": [{"stock_id": "601188", "themes": []}]})
    assert svc._corpus_persist_stats["theme_fail"] == 1
    assert "db down" in svc._corpus_persist_stats["last_error"]


def test_persist_union_merge_keeps_existing_members():
    """多次推送按 stock_id 并集合并，不覆盖既有成员（与 archiver 同一函数保证）。"""
    db = _FakeDb()
    svc = _collector(db, pool_date="2026-11-10")
    svc._persist_corpus("theme", {"items": [
        {"stock_id": "601188", "name": "龙江交通",
         "themes": [{"id": "80001", "name": "冰雪经济", "number": 96.5}],
         "ts": 1794500000.0}]})
    svc._persist_corpus("theme", {"items": [
        {"stock_id": "601188", "name": "龙江交通",
         "themes": [{"id": "80001", "name": "冰雪经济", "number": 98.0}],
         "ts": 1794500100.0}]})
    svc._persist_corpus("theme", {"items": [
        {"stock_id": "600001", "name": "另一只",
         "themes": [{"id": "80002", "name": "机器人", "number": 50.0}],
         "ts": 1794500200.0}]})
    row = db._coll.rows["2026-11-10"]
    sids = {m["stock_id"] for m in row["theme_items"]}
    assert sids == {"601188", "600001"}
    by_id = {m["stock_id"]: m for m in row["theme_items"]}
    assert by_id["601188"]["themes"][0]["number"] == 98.0   # 字段随最新帧刷新
    assert by_id["601188"]["first_ts"] == 1794500000.0      # 首次到流保留


def test_pytest_process_without_factory_skips_real_db():
    """pytest 进程内未注入假库 → 不落库（测试绝不碰真库）。"""
    svc = KplCollectorService(_FakeCodec(), human_delay=False)
    assert svc._corpus_db() is None
    svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                               "items": [{"stock_id": "601188"}]}}
    svc._persist_corpus("theme", {"items": [{"stock_id": "601188", "themes": []}]})
    assert svc._corpus_persist_stats["theme_fail"] == 1
    assert "corpus_db_unavailable" in svc._corpus_persist_stats["last_error"]
