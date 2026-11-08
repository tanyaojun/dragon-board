# -*- coding: utf-8 -*-
"""涨停基因语料通道 + 增量存档器单测（2026-11-08，题材龙头语料投喂 jev）。

口径：gene_items 按 stock_id 并集、字段级 $set 只写 gene_ 前缀（不与打板通道整 doc 互踩）；
缺失不补 0、失败进 gene_failures（fail-visible）；pending_n 暴露覆盖度。
pytest 纪律：注入假库 + fetcher 桩，不发真实 HTTP（红线 7）。
"""
import asyncio
from datetime import datetime

from backend.services.kpl_gene_corpus import (
    GeneCorpusArchiver,
    archive_gene_corpus,
    load_gene_corpus,
    pick_gene_targets,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def replace_one(self, q: dict, doc: dict, upsert: bool = False) -> None:   # 打板通道行为
        assert upsert is True
        self.rows[q["_id"]] = doc

    def update_one(self, q: dict, update: dict, upsert: bool = False) -> None:
        """基因通道：字段级 $set（必须不带 upsert，避免与打板通道抢建日档）。"""
        assert upsert is False
        row = self.rows.setdefault(q["_id"], {"_id": q["_id"]})
        row.update(update["$set"])

    def find_one(self, q: dict) -> dict | None:
        return self.rows.get(q["_id"])


class _FakeDb:
    def __init__(self) -> None:
        self._coll = _FakeCollection()

    def __getitem__(self, name: str):
        assert name == "kpl_daban_pool"
        return self._coll


def _pool_row(date: str, stock_ids: list[str]) -> dict:
    return {"_id": date, "items": [{"stock_id": sid, "name": f"股{sid}"} for sid in stock_ids],
            "ts": 100.0}


def _gene(sid: str) -> dict:
    return {"ok": True, "stock_id": sid,
            "gene": {"zt_count": 4, "premium5_count": 1, "next_day_red_pct": 50,
                     "first_seal_pct": 100, "first_broken_pct": 0, "lianban_pct": 50},
            "gene_labels": {"zt_count": "涨停次数"},
            "raw": [4, 1, 50, 100, 0, 50], "raw_len": 6,
            "window_note": "上游未标注统计窗口（六元数组原样透出，不自算不反推）"}


def test_pick_gene_targets_missing_first_limit_and_close_refresh():
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001", "000002", "000003"])
    before_close = datetime(2026, 11, 6, 10, 30, tzinfo=TZ_SHANGHAI)
    plan = pick_gene_targets(db, "2026-11-06", limit=2, now=before_close)
    assert plan["ok"] is True and plan["targets"] == ["000001", "000002"]
    assert plan["pending_n"] == 3 and plan["refresh_n"] == 0 and plan["after_close"] is False

    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000001")]},
                        now=before_close)
    after_close = datetime(2026, 11, 6, 15, 30, tzinfo=TZ_SHANGHAI)
    plan2 = pick_gene_targets(db, "2026-11-06", limit=5, now=after_close)
    assert plan2["targets"] == ["000002", "000003", "000001"]   # 缺失优先、旧值排队尾
    assert plan2["pending_n"] == 2 and plan2["refresh_n"] == 1

    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000001")]},
                        now=after_close)
    plan3 = pick_gene_targets(db, "2026-11-06", limit=5, now=after_close)
    assert plan3["targets"] == ["000002", "000003"] and plan3["refresh_n"] == 0


def test_pick_gene_targets_no_archive_and_empty_pool():
    assert pick_gene_targets(_FakeDb(), "2026-11-06")["reason"] == "no_archive"
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = {"_id": "2026-11-06", "items": []}
    assert pick_gene_targets(db, "2026-11-06")["reason"] == "empty_pool"


def test_archive_gene_corpus_sets_only_gene_prefix():
    """字段级 $set：只动 gene_ 前缀，池成员/其它通道字段保持原样（不与打板通道互踩）。"""
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001", "000002"])
    db._coll.rows["2026-11-06"]["bid_items"] = [{"stock_id": "300001"}]
    out = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [
        _gene("000001"),
        {"ok": False, "stock_id": "000002", "degraded": True, "reason": "1020", "error": "白名单"},
    ]}, now=datetime(2026, 11, 6, 14, 0, tzinfo=TZ_SHANGHAI))
    assert out["ok"] is True and out["merged_n"] == 1 and out["failures_n"] == 1
    assert out["pending_n"] == 1
    row = db._coll.rows["2026-11-06"]
    assert row["gene_count"] == 1 and row["gene_pending_n"] == 1
    assert row["gene_items"][0]["raw"] == [4, 1, 50, 100, 0, 50]
    assert row["gene_items"][0]["source"] == "http_GetZhangTingGene"
    assert row["gene_failures"][0]["stock_id"] == "000002"
    assert [m["stock_id"] for m in row["items"]] == ["000001", "000002"]   # 打板通道不变
    assert row["bid_items"] == [{"stock_id": "300001"}]
    assert "reason_items" not in row

    out2 = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000002")]},
                               now=datetime(2026, 11, 6, 14, 30, tzinfo=TZ_SHANGHAI))
    assert out2["pending_n"] == 0 and out2["item_n"] == 2
    assert db._coll.rows["2026-11-06"]["gene_failures"] == []


def test_archive_gene_corpus_all_failed_and_no_date():
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001"])
    out = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [
        {"ok": False, "stock_id": "000001", "reason": "1020", "error": "白名单"}]})
    assert out["ok"] is False and out["reason"] == "no_gene_fetched"
    assert "gene_items" not in db._coll.rows["2026-11-06"]   # 不写、不覆盖既有
    assert archive_gene_corpus(db, {"genes": [_gene("000001")]})["reason"] == "no_pool_date"


def test_gene_point_in_time_flags():
    """时点语义：抓取日==日档交易日 → same_day=True；回填 → False + 读口 note 提示。"""
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001", "000002"])
    same_day = datetime(2026, 11, 6, 15, 30, tzinfo=TZ_SHANGHAI)
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000001")]}, now=same_day)
    backfill = datetime(2026, 11, 8, 20, 0, tzinfo=TZ_SHANGHAI)
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000002")]}, now=backfill)
    items = {it["stock_id"]: it for it in db._coll.rows["2026-11-06"]["gene_items"]}
    assert items["000001"]["same_day"] is True and items["000001"]["fetched_date"] == "2026-11-06"
    assert items["000002"]["same_day"] is False and items["000002"]["fetched_date"] == "2026-11-08"
    out = load_gene_corpus(db, "2026-11-06")
    assert out["same_day_n"] == 1 and out["backfill_n"] == 1
    assert "回填抓取" in out["note"] and "不得当该日盘后已知信息使用" in out["note"]


def test_load_gene_corpus_degraded_and_ok():
    db = _FakeDb()
    assert load_gene_corpus(db, "2026-11-06")["reason"] == "no_archive"
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001"])
    assert load_gene_corpus(db, "2026-11-06")["reason"] == "no_gene_corpus"
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_gene("000001")]})
    out = load_gene_corpus(db, "2026-11-06")
    assert out["ok"] is True and out["count"] == 1 and out["pending_n"] == 0
    assert out["corpus_source"] == "http_GetZhangTingGene"
    assert "未标注统计窗口" in out["items"][0]["window_note"]


class _S:
    storage_backend = "mongodb"


class _Resp:
    def __init__(self, content):
        self._c = content

    def json(self):
        return self._c


class _Client:
    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        return _Resp({"ok": True, "date": "2026-11-06"})


def test_archiver_round_limits_fetch_and_writes(monkeypatch):
    from backend.services import kpl_gene_corpus as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    calls: list[str] = []

    def _fetch(sid: str) -> dict:
        calls.append(sid)
        return _gene(sid) if sid != "000002" else {"ok": False, "stock_id": sid,
                                                   "reason": "1020", "error": "白名单"}

    db = _FakeDb()
    db._coll.rows["2026-11-06"] = _pool_row("2026-11-06", ["000001", "000002", "000003"])
    archiver = GeneCorpusArchiver(settings=_S(), database_factory=lambda: db,
                                  gene_fetcher=_fetch, gene_limit=2)
    asyncio.run(archiver._run_once())
    res = archiver.status()["lastResult"]
    assert calls == ["000001", "000002"]              # limit 控发数
    assert res["gene"]["ok"] is True and res["gene"]["merged_n"] == 1
    assert res["gene"]["pending_n"] == 2
    row = db._coll.rows["2026-11-06"]
    assert [g["stock_id"] for g in row["gene_items"]] == ["000001"]
    assert row["gene_failures"][0]["stock_id"] == "000002"


def test_archiver_round_collector_degraded_no_write(monkeypatch):
    from backend.services import kpl_gene_corpus as mod

    class _BadClient(_Client):
        async def get(self, url, timeout=None):
            return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})

    monkeypatch.setattr(mod.httpx, "AsyncClient", _BadClient)
    db = _FakeDb()
    archiver = GeneCorpusArchiver(settings=_S(), database_factory=lambda: db,
                                  gene_fetcher=_gene, gene_limit=2)
    asyncio.run(archiver._run_once())
    res = archiver.status()
    assert res["lastResult"]["pool"]["reason"].startswith("collector_degraded:")
    assert res["lastError"] and db._coll.rows == {}   # 无交易日不猜、不写


def test_archiver_disabled_without_mongodb():
    class _S2:
        storage_backend = "sqlite"

    archiver = GeneCorpusArchiver(settings=_S2())
    assert archiver.enabled is False
    archiver.start()
    assert archiver.status()["running"] is False