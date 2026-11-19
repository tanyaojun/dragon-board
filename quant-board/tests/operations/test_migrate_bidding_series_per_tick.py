# -*- coding: utf-8 -*-
"""kpl_bidding_series 逐 tick 迁移脚本测试（纯假库 + 归档替身，零真实 mongoexport）。

锁定（plan §2/§6）：旧嵌入 fixture → meta+tick 文档、tick_n 核对、幂等重跑、
部分失败重跑不重复、meta 加字段保留、归档失败该档停（fail-visible）、dry-run 零写。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import migrate_bidding_series_per_tick as MG
from tests.series_fake import FakeSeriesCol, seed_series_legacy

DATE = "2026-11-18"


class FakeDb:
    def __init__(self, col):
        self.col = col

    def __getitem__(self, name):
        assert name == MG.COLLECTION
        return self.col


def _legacy_db():
    col = FakeSeriesCol()
    seed_series_legacy(col, {
        "_id": DATE, "date": DATE,
        "ticks": [{"ts": 1000.0 + i, "n": 1,
                   "it": [{"s": "600102", "zt_buy_amount": 1e6 + i}]}
                  for i in range(5)],
        "window": ["09:15:00", "09:27:00"],
        "prev_pct": {"600102": {"pct": 5.5}},
        "prev_pct_state": {"attempts_n": 1},
    })
    # 还原旧嵌入形态（seed_series_legacy 已拆；迁移输入=旧形态单文档）
    ticks = [d for d in col.docs if "it" in d]
    meta = next(d for d in col.docs if d.get("_id") == DATE)
    col.docs = [{**meta, "ticks": [
        {"ts": t["ts"], "n": t["n"], "it": t["it"]} for t in ticks]}]
    return FakeDb(col)


@pytest.fixture
def archive_spy(tmp_path, monkeypatch):
    calls = []

    def fake_export(tools_bin, uri, database, date, out_dir, *, expect_lines):
        calls.append(date)
        out = tmp_path / f"legacy_{date}.json"
        # 一行一档（mongoexport 同款）；行数=legacy ticks 数，供归档完整性校验
        out.write_text("\n".join("{}" for _ in range(expect_lines)) + "\n", encoding="utf-8")
        return out
    monkeypatch.setattr(MG, "_export_legacy", fake_export)
    return calls


def _run(db, tmp_path, **kw):
    doc = db.col.find_one({"_id": DATE})
    return MG.migrate_one(db, Path("tools"), "uri", "dragon_board_test",
                          doc, tmp_path, **kw)


def test_migrate_counts_and_meta_fields(tmp_path, archive_spy):
    db = _legacy_db()
    rep = _run(db, tmp_path)
    assert rep["state"] == "ok" and rep["legacy_ticks"] == 5
    assert rep["tick_docs"] == 5 and rep["meta_tick_n"] == 5
    meta = db.col.find_one({"_id": DATE})
    assert "ticks" not in meta
    assert meta["prev_pct"] == {"600102": {"pct": 5.5}}, "加字段零触碰"
    assert meta["prev_pct_state"] == {"attempts_n": 1}
    assert meta["window"] == ["09:15:00", "09:27:00"]
    ticks = list(db.col.find({"date": DATE, "it": {"$exists": True}}))
    assert [t["ts"] for t in ticks] == [1000.0 + i for i in range(5)]
    assert archive_spy == [DATE], "归档先行（红线 4）"


def test_migrate_idempotent_rerun(tmp_path, archive_spy):
    db = _legacy_db()
    assert _run(db, tmp_path)["state"] == "ok"
    # 重跑输入=已迁 meta（无 ticks）→ 不在 legacy 查询面；模拟部分失败重跑：
    # 人为恢复旧 ticks 数组（归档已在），重跑不得产生重复 tick 文档
    meta = db.col.find_one({"_id": DATE})
    ticks = [{"ts": t["ts"], "n": t["n"], "it": t["it"]}
             for t in db.col.find({"date": DATE, "it": {"$exists": True}})]
    db.col.update_one({"_id": DATE}, {"$set": {"ticks": ticks}})
    rep = _run(db, tmp_path)
    assert rep["state"] == "ok" and rep["cleared_partial"] == 5
    assert db.col.count_documents({"date": DATE, "it": {"$exists": True}}) == 5
    assert db.col.find_one({"_id": DATE})["tick_n"] == 5


def test_migrate_partial_failure_rerun_no_duplicates(tmp_path, archive_spy):
    db = _legacy_db()
    # 模拟上次迁移插了 2 个 tick 文档后中断（旧 ticks 仍在）
    db.col.insert_one({"date": DATE, "ts": 1000.0, "n": 1,
                       "it": [{"s": "600102"}]})
    db.col.insert_one({"date": DATE, "ts": 1001.0, "n": 1,
                       "it": [{"s": "600102"}]})
    rep = _run(db, tmp_path)
    assert rep["state"] == "ok" and rep["cleared_partial"] == 2
    assert db.col.count_documents({"date": DATE, "it": {"$exists": True}}) == 5


def test_migrate_export_failure_stops_date(tmp_path, monkeypatch):
    db = _legacy_db()

    def boom(*a, **k):
        raise RuntimeError("mongoexport missing")
    monkeypatch.setattr(MG, "_export_legacy", boom)
    rep = _run(db, tmp_path)
    assert rep["state"].startswith("failed:")
    meta = db.col.find_one({"_id": DATE})
    assert "ticks" in meta and len(meta["ticks"]) == 5, "归档失败不改写旧档"
    assert db.col.count_documents({"date": DATE, "it": {"$exists": True}}) == 0


def test_migrate_dry_run_zero_write(tmp_path, archive_spy):
    db = _legacy_db()
    rep = _run(db, tmp_path, dry_run=True)
    assert rep["state"] == "dry_run" and rep["legacy_ticks"] == 5
    assert archive_spy == []
    meta = db.col.find_one({"_id": DATE})
    assert "ticks" in meta


def test_migrate_export_partial_file_removed_on_failure(tmp_path, monkeypatch):
    """review S2：mongoexport 失败残留的部分文件被删除，不进下一轮「exists
    即复用」误当完整归档（红线 4：改写唯一完整副本前归档必须可信）。"""
    from types import SimpleNamespace
    db = _legacy_db()
    partial = tmp_path / "kpl_bidding_series_legacy_dragon_board_test_2026-11-18.json"
    partial.write_text("{partial", encoding="utf-8")
    monkeypatch.setattr(MG.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="boom", stdout=""))
    rep = MG.migrate_one(db, Path("tools"), "uri", "dragon_board_test",
                         db.col.find_one({"_id": DATE}), tmp_path)
    assert rep["state"].startswith("failed") and "mongoexport" in rep["error"]
    assert not partial.exists(), "失败残留已删（不污染幂等复用）"
    meta = next(d for d in db.col.docs if d.get("_id") == DATE)
    assert "ticks" in meta and len(meta["ticks"]) == 5, "归档失败不改写旧档"
    assert db.col.count_documents({"date": DATE, "it": {"$exists": True}}) == 0


def test_migrate_archive_line_mismatch_stops(tmp_path, monkeypatch):
    """review S2：归档行数 ≠ legacy ticks → 该档失败，绝不改写唯一完整副本。"""
    db = _legacy_db()
    out = tmp_path / "kpl_bidding_series_legacy_dragon_board_test_2026-11-18.json"

    def bad_export(tools_bin, uri, database, date, out_dir, *, expect_lines):
        out.write_text("{}\n", encoding="utf-8")   # 只 1 行 ≠ 5 ticks
        return out
    monkeypatch.setattr(MG, "_export_legacy", bad_export)
    rep = MG.migrate_one(db, Path("tools"), "uri", "dragon_board_test",
                         db.col.find_one({"_id": DATE}), tmp_path)
    assert rep["state"] == "failed" and "archive_line_mismatch" in rep["error"]
    meta = next(d for d in db.col.docs if d.get("_id") == DATE)
    assert "ticks" in meta and len(meta["ticks"]) == 5, "唯一完整副本未被改写"
    assert db.col.count_documents({"date": DATE, "it": {"$exists": True}}) == 0
