"""采集链股票名称回填测试（2026-09-24）。

背景：部分平台来源的 stock row name 是 "-" 占位（如实入库），导致热榜情绪文档
换手明细等下游展示名称缺失。修复：入库前从 `stock_names` 注册集合（code→name）
批量回填；查不到保持原样（fail-visible 不伪造）；已有名称不覆盖。
"""
from __future__ import annotations

from typing import Any


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None):
        query = query or {}
        codes = ((query.get("code") or {}).get("$in")) or []
        rows = [row for row in self.rows if row.get("code") in codes] if codes else list(self.rows)
        return iter(rows)


class FakeMongoDb:
    def __init__(self, stock_names: list[dict[str, Any]]) -> None:
        self.collections = {"stock_names": FakeCollection(stock_names)}

    def __getitem__(self, name: str):
        return self.collections[name]


def _enrich(db, rows):
    from backend.snapshot_collector.service import enrich_stock_names_from_registry

    return enrich_stock_names_from_registry(db, rows)


def test_placeholder_and_empty_names_backfilled() -> None:
    db = FakeMongoDb([
        {"code": "300647", "name": "同花顺新"},
        {"code": "002321", "name": "东华测试"},
    ])
    rows = [
        {"code": "300647", "name": "-"},
        {"code": "002321", "name": ""},
        {"code": "920201", "name": "-"},
    ]
    _enrich(db, rows)
    assert rows[0]["name"] == "同花顺新"
    assert rows[1]["name"] == "东华测试"
    assert rows[2]["name"] == "-"  # 注册表查不到 → 保持原样，不伪造


def test_existing_names_are_not_overwritten() -> None:
    db = FakeMongoDb([{"code": "000001", "name": "注册表名"}])
    rows = [{"code": "000001", "name": "采集原名"}]
    _enrich(db, rows)
    assert rows[0]["name"] == "采集原名"


def test_db_failure_does_not_block_collection() -> None:
    class _Broken:
        def __getitem__(self, name):
            raise RuntimeError("boom")

    rows = [{"code": "300647", "name": "-"}]
    _enrich(_Broken(), rows)  # 不抛出
    assert rows[0]["name"] == "-"


def test_missing_name_key_row_is_filled() -> None:
    db = FakeMongoDb([{"code": "002321", "name": "东华测试"}])
    rows = [{"code": "002321"}]  # 无 name 键
    _enrich(db, rows)
    assert rows[0]["name"] == "东华测试"
