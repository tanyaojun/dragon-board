# -*- coding: utf-8 -*-
"""kpl_daban_archiver 单测（2026-11-07）：涨停池按日存档纯函数 + 启用护栏。

口径：成员并集 + 收盘态标注（sealed/broken=炸板未回封；回封恢复 sealed；
页缺口帧跳过掉出标注防误标）。
pytest 纪律：全部注入假库/假 settings，不发真实 HTTP、不触真实 Mongo。
"""
from datetime import datetime

from backend.services.kpl_daban_archiver import (
    DabanPoolArchiver,
    archive_bid_snapshot,
    archive_snapshot,
    load_day,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def replace_one(self, q: dict, doc: dict, upsert: bool = False) -> None:
        assert upsert is True
        self.rows[q["_id"]] = doc

    def find_one(self, q: dict) -> dict | None:
        return self.rows.get(q["_id"])


class _FakeDb:
    def __init__(self) -> None:
        self._coll = _FakeCollection()

    def __getitem__(self, name: str):
        assert name == "kpl_daban_pool"
        return self._coll


def _snap(ts: float, stock_ids: list[str], pages_missing: list[int] | None = None,
          date: str = "2026-11-07") -> dict:
    return {
        "ok": True, "date": date, "ts": ts, "pages_missing": pages_missing or [],
        "max_size": 40, "pages": 2, "pages_expected": 2, "pid_type": 1, "raw_len": 1234,
        "pages_meta": [{"index": 0, "count": 30, "order_type": 0, "sort_type": 0,
                        "indexes": [0], "max_size": 40, "date": date, "ts": ts}],
        "items": [{"stock_id": sid, "name": f"股{sid}", "zt_reason": "机器人",
                   "plate_id": "801464", "zt_tur": 1000.0 * int(sid),
                   "quotas": ["", "", "", "", "", "", "", "100万", "", "", "首板", "",
                              "机器人", "机器人概念", "100万", "50万", "3.2", "1.5亿", "", "",
                              "4", "801464", "", "", "", "", "", ""]}
                  for sid in stock_ids],
    }


def _states(row: dict) -> dict[str, str]:
    return {m["stock_id"]: m.get("pool_state") for m in row["items"]}


def test_merge_union_and_broken_marking():
    db = _FakeDb()
    # 帧1：A、B 在池
    r1 = archive_snapshot(db, _snap(100.0, ["000001", "000002"]), now=datetime(2026, 11, 7, 10, 0, tzinfo=TZ_SHANGHAI))
    assert r1["ok"] and r1["item_n"] == 2 and r1["sealed_n"] == 2 and r1["broken_n"] == 0
    # 全字段落库：pid_type/pages_meta/raw_len/items 内 quotas×28 原始数组 + plate_id 具名
    row0 = load_day(db, "2026-11-07")
    assert row0["pid_type"] == 1 and row0["raw_len"] == 1234
    assert row0["pages_meta"][0]["count"] == 30
    m0 = row0["items"][0]
    assert m0["plate_id"] == "801464" and len(m0["quotas"]) == 28 and m0["quotas"][21] == "801464"
    # 帧2：B 掉出（炸板未回封），A 仍在，C 新入池
    r2 = archive_snapshot(db, _snap(200.0, ["000001", "000003"]))
    assert r2["item_n"] == 3 and r2["sealed_n"] == 2 and r2["broken_n"] == 1 and r2["broken_marked"] == 1
    row = load_day(db, "2026-11-07")
    assert _states(row) == {"000001": "sealed", "000002": "broken", "000003": "sealed"}
    broken = next(m for m in row["items"] if m["stock_id"] == "000002")
    # broken 成员保留其最后封住时字段 + last_seen_ts（非当前帧 ts）
    assert broken["zt_tur"] == 1000.0 * 2 and broken["last_seen_ts"] == 100.0
    # 尾盘帧3：B 回封（重新入池）→ 恢复 sealed
    archive_snapshot(db, _snap(300.0, ["000001", "000002", "000003"]))
    row3 = load_day(db, "2026-11-07")
    assert set(_states(row3).values()) == {"sealed"} and row3["broken_n"] == 0


def test_pages_missing_skips_broken_marking():
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002"]))
    # 帧2 页缺口：B 缺席可能是采集缺页而非真炸板 → 不标注，保持 sealed
    r = archive_snapshot(db, _snap(200.0, ["000001"], pages_missing=[1]))
    assert r["broken_marked"] == 0 and r["broken_n"] == 0
    row = load_day(db, "2026-11-07")
    assert _states(row)["000002"] == "sealed"
    # 后续完整帧：B 真掉出才标注
    archive_snapshot(db, _snap(300.0, ["000001"]))
    assert _states(load_day(db, "2026-11-07"))["000002"] == "broken"


def test_merge_updates_fields_of_existing_member():
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"]))
    archive_snapshot(db, _snap(200.0, ["000001"]))
    m = load_day(db, "2026-11-07")["items"][0]
    assert m["last_seen_ts"] == 200.0 and m["pool_state"] == "sealed"


def test_archive_snapshot_empty_not_written():
    db = _FakeDb()
    assert archive_snapshot(db, {"ok": True, "date": "", "items": []})["reason"] == "empty_snapshot"
    assert archive_snapshot(db, {"ok": True, "date": "2026-11-07", "items": []})["reason"] == "empty_snapshot"
    assert load_day(db, "2026-11-07")["reason"] == "no_archive"


def test_load_day_no_archive_degraded():
    assert load_day(_FakeDb(), "2026-01-01") == {
        "ok": False, "degraded": True, "reason": "no_archive", "date": "2026-01-01", "lane": "pool"}


def _bid_snap(ts: float, stock_ids: list[str], date: str = "2026-11-07") -> dict:
    return {
        "ok": True, "date": date, "ts": ts, "pages_missing": [],
        "max_size": 210, "pages": 6, "pages_expected": 6, "pid_type": 8, "raw_len": 9000,
        "pages_meta": [{"index": 0, "count": 30, "indexes": [0]}],
        "items": [{"stock_id": sid, "name": f"竞{sid}", "bidding_pct": 3.2,
                   "bidding_net": 500.0 * int(sid),
                   "quotas": ["", "3.2", "500", "0.9", "966万", "", "2.1", "", "", "", "",
                              "", "", "机器人概念", "", "", "", "15.8亿", "", "", "", "",
                              "", "", "", "", ""]}
                  for sid in stock_ids],
    }


def test_bid_lane_same_doc_no_broken_marking():
    """集合竞价通道：同日档 bid_ 前缀字段，成员并集+字段刷新，无 pool_state 标注。"""
    db = _FakeDb()
    # 同日档先写涨停池、再写竞价：两通道互不覆盖
    archive_snapshot(db, _snap(100.0, ["000001"]), now=datetime(2026, 11, 7, 10, 0, tzinfo=TZ_SHANGHAI))
    r = archive_bid_snapshot(db, _bid_snap(200.0, ["300001", "300002"]),
                             now=datetime(2026, 11, 7, 10, 1, tzinfo=TZ_SHANGHAI))
    assert r["ok"] and r["lane"] == "bid" and r["item_n"] == 2
    row = load_day(db, "2026-11-07")   # pool 通道=整日档
    assert len(row["items"]) == 1 and len(row["bid_items"]) == 2   # 涨停池字段未被竞价覆盖
    assert row["bid_pid_type"] == 8 and row["bid_max_size"] == 210
    assert all("pool_state" not in m for m in row["bid_items"])   # 竞价无炸板语义
    # 成员并集+字段刷新：第二帧只剩 300001，300002 保留旧值不删除
    r2 = archive_bid_snapshot(db, _bid_snap(300.0, ["300001"]))
    assert r2["item_n"] == 2
    row2 = load_day(db, "2026-11-07", lane="bid")   # bid 通道=映射为 /daban-list 同构载荷
    assert row2["ok"] and [m["stock_id"] for m in row2["items"]] == ["300001", "300002"]
    assert row2["ts"] == 300.0 and row2["max_size"] == 210


def test_bid_lane_no_archive_when_doc_only_pool():
    """日档存在但竞价通道无数据（旧档）：结构化降级，不回退其它通道冒充。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"]))
    r = load_day(db, "2026-11-07", lane="bid")
    assert r["ok"] is False and r["degraded"] and r["reason"] == "no_archive" and r["lane"] == "bid"


def test_archiver_disabled_without_mongodb():
    class _S:
        storage_backend = "sqlite"

    archiver = DabanPoolArchiver(settings=_S())
    assert archiver.enabled is False
    archiver.start()   # 无运行事件循环 + 禁用：不启动、不抛
    assert archiver.status()["running"] is False


def test_archiver_enabled_with_mongodb_requires_loop():
    class _S:
        storage_backend = "mongodb"

    archiver = DabanPoolArchiver(settings=_S(), interval_seconds=1)
    assert archiver.enabled is True
    # 无 asyncio 运行循环（同步单测上下文）：start() 直接返回不建任务
    archiver.start()
    assert archiver.status()["running"] is False
