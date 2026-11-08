# -*- coding: utf-8 -*-
"""kpl_daban_archiver 单测（2026-11-07 涨停池/2026-11-08 竞价+炸板+跌停通道）。

口径：成员并集 + 收盘态标注（sealed/broken；涨停池=炸板未回封、跌停池=打开跌停
未回封；回封恢复 sealed；页缺口帧跳过掉出标注防误标）。
pytest 纪律：全部注入假库/假 settings，不发真实 HTTP、不触真实 Mongo。
"""
from datetime import datetime

from backend.services.kpl_daban_archiver import (
    DabanPoolArchiver,
    archive_bid_snapshot,
    archive_dt_snapshot,
    archive_gene_corpus,
    archive_snapshot,
    archive_zb_snapshot,
    load_day,
    load_gene_corpus,
    pick_gene_targets,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def replace_one(self, q: dict, doc: dict, upsert: bool = False) -> None:
        assert upsert is True
        self.rows[q["_id"]] = doc

    def update_one(self, q: dict, update: dict, upsert: bool = False) -> None:
        """生产已改字段级 $set（各通道含 gene 通道同款并发合同）；假库同语义合并。"""
        assert "_id" not in update["$set"], "$set 不得改写 _id"
        row = self.rows.setdefault(q["_id"], {"_id": q["_id"]}) if upsert else self.rows.get(q["_id"])
        assert upsert or row is not None, "非 upsert 更新不应凭空造档"
        row.update(update["$set"])

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


def _fake_gene(sid: str) -> dict:
    """基因 fetcher 桩（红线 7：pytest 内不得真实调用 apphq）。"""
    return {"ok": True, "stock_id": sid,
            "gene": {"zt_count": 4, "premium5_count": 1, "next_day_red_pct": 50,
                     "first_seal_pct": 100, "first_broken_pct": 0, "lianban_pct": 50},
            "gene_labels": {"zt_count": "涨停次数"},
            "raw": [4, 1, 50, 100, 0, 50], "raw_len": 6,
            "window_note": "上游未标注统计窗口（六元数组原样透出，不自算不反推）"}


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


def _zb_snap(ts: float, stock_ids: list[str], date: str = "2026-11-08") -> dict:
    return {
        "ok": True, "date": date, "ts": ts, "pages_missing": [],
        "max_size": 12, "pages": 1, "pages_expected": 1, "pid_type": 2, "raw_len": 888,
        "pages_meta": [{"index": 0, "count": 30, "indexes": [0]}],
        "items": [{"stock_id": sid, "name": f"炸{sid}", "zt_reason": "机器人",
                   "open_time": 39000.0 * int(sid) % 40000, "zt_tur": 777.0 * int(sid),
                   "quotas": [""] * 28}
                  for sid in stock_ids],
    }


def _dt_snap(ts: float, stock_ids: list[str], pages_missing: list[int] | None = None,
             date: str = "2026-11-08") -> dict:
    return {
        "ok": True, "date": date, "ts": ts, "pages_missing": pages_missing or [],
        "max_size": 5, "pages": 1, "pages_expected": 1, "pid_type": 3, "raw_len": 555,
        "pages_meta": [{"index": 0, "count": 30, "indexes": [0]}],
        "items": [{"stock_id": sid, "name": f"跌{sid}", "pct": -10.0,
                   "zt_reason": "业绩预亏", "zt_tur": 55.0 * int(sid),
                   "quotas": [""] * 28}
                  for sid in stock_ids],
    }


def test_zb_lane_union_no_pool_state():
    """炸板池通道（2026-11-08）：zb_ 前缀同日档，成员并集+字段刷新，无 pool_state
    （回封后掉出仍留档，回封语义由涨停池通道 sealed 承载）。"""
    db = _FakeDb()
    # 同日档先写涨停池、再写炸板池：两通道互不覆盖
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-08"))
    r = archive_zb_snapshot(db, _zb_snap(200.0, ["600001", "600002"]))
    assert r["ok"] and r["lane"] == "zb" and r["item_n"] == 2
    row = load_day(db, "2026-11-08")
    assert len(row["items"]) == 1 and len(row["zb_items"]) == 2   # 涨停池字段未被炸板池覆盖
    assert row["zb_pid_type"] == 2 and row["zb_max_size"] == 12
    assert all("pool_state" not in m for m in row["zb_items"])
    # 成员并集：第二帧只剩 600001，600002（已回封掉出）保留旧值不删除
    archive_zb_snapshot(db, _zb_snap(300.0, ["600001"]))
    row2 = load_day(db, "2026-11-08", lane="zb")   # 映射为 /daban-list 同构载荷
    assert row2["ok"] and [m["stock_id"] for m in row2["items"]] == ["600001", "600002"]
    assert row2["ts"] == 300.0 and row2["max_size"] == 12


def test_zb_lane_no_archive_when_doc_only_pool():
    """日档存在但炸板池通道无数据（旧档）：结构化降级，不伪装空列表。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-08"))
    r = load_day(db, "2026-11-08", lane="zb")
    assert r["ok"] is False and r["degraded"] and r["reason"] == "no_archive" and r["lane"] == "zb"


def test_dt_lane_broken_marking():
    """跌停池通道（2026-11-08）：dt_ 前缀同日档，与涨停池同款收盘态标注——
    sealed=收盘仍跌停 / broken=曾入池后掉出即打开跌停未回封；回封恢复 sealed。"""
    db = _FakeDb()
    r1 = archive_dt_snapshot(db, _dt_snap(100.0, ["000001", "000002"]))
    assert r1["ok"] and r1["item_n"] == 2 and r1["sealed_n"] == 2
    # 帧 2：000002 打开跌停掉出 → broken，字段保留最后封住时快照
    r2 = archive_dt_snapshot(db, _dt_snap(200.0, ["000001"]))
    assert r2["item_n"] == 2 and r2["sealed_n"] == 1 and r2["broken_n"] == 1 and r2["broken_marked"] == 1
    row = load_day(db, "2026-11-08", lane="dt")
    states = {m["stock_id"]: m.get("pool_state") for m in row["items"]}
    assert states == {"000001": "sealed", "000002": "broken"}
    broken = next(m for m in row["items"] if m["stock_id"] == "000002")
    assert broken["zt_tur"] == 55.0 * 2 and broken["last_seen_ts"] == 100.0
    # 帧 3：000002 重新封住跌停（回封）→ 恢复 sealed
    archive_dt_snapshot(db, _dt_snap(300.0, ["000001", "000002"]))
    row3 = load_day(db, "2026-11-08", lane="dt")
    assert all(m.get("pool_state") == "sealed" for m in row3["items"])


def test_dt_lane_pages_missing_skips_broken_marking():
    """跌停池通道页缺口帧：缺席可能是采集缺页而非真打开 → 不标注，保持 sealed。"""
    db = _FakeDb()
    archive_dt_snapshot(db, _dt_snap(100.0, ["000001", "000002"]))
    r = archive_dt_snapshot(db, _dt_snap(200.0, ["000001"], pages_missing=[1]))
    assert r["broken_marked"] == 0
    row = load_day(db, "2026-11-08", lane="dt")
    assert {m.get("pool_state") for m in row["items"]} == {"sealed"}


def test_dt_lane_no_archive_when_doc_only_pool():
    """日档存在但跌停池通道无数据（旧档）：结构化降级，不伪装空列表。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-08"))
    r = load_day(db, "2026-11-08", lane="dt")
    assert r["ok"] is False and r["degraded"] and r["reason"] == "no_archive" and r["lane"] == "dt"


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


def test_archive_once_lane_isolation(monkeypatch):
    """单轮四通道：任一通道 fetch 失败/降级不阻断其它通道落库（2026-11-08 增补炸板/跌停）。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

    class _S:
        storage_backend = "mongodb"

    class _Resp:
        def __init__(self, content):
            self._c = content

        def json(self):
            return self._c

    class _FailClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            if url.endswith("pid_type=2"):
                raise OSError("conn refused")   # 炸板池 fetch 失败
            if url.endswith("pid_type=3"):
                return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})
            return _Resp(_snap(100.0, ["000001"], date="2026-11-08") if url.endswith("pid_type=1")
                         else _bid_snap(200.0, ["300001"], date="2026-11-08"))

    monkeypatch.setattr(arch.httpx, "AsyncClient", _FailClient)
    db = _FakeDb()
    archiver = DabanPoolArchiver(
        settings=_S(), database_factory=lambda: db, interval_seconds=60,
        gene_fetcher=_fake_gene)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    # 涨停/竞价正常落库；炸板池 fetch 失败、跌停池 collector 降级：各自结构化透出，互不连带
    assert res["pool"]["ok"] is True and res["bid"]["ok"] is True
    assert res["zb"]["ok"] is False and res["zb"]["reason"].startswith("fetch_failed:")
    assert res["dt"]["ok"] is False and res["dt"]["reason"].startswith("collector_degraded:")
    assert archiver.status()["lastError"]
    # db 里只有 pool/bid 两通道写了当日档
    row = db._coll.rows["2026-11-08"]
    assert "items" in row and "bid_items" in row and "zb_items" not in row and "dt_items" not in row


# ── 评审 P2-3 补丁用例（2026-11-08）：落库异常隔离 / 不写噪声键 / 残留键保留 /
#    非法 lane / 四通道同档 / 合法空池 / 页缺口后补标 ──────────────────────────

def test_archive_stage_failure_isolated(monkeypatch):
    """落库阶段（fn 抛错）逐通道隔离：评审 P1-1 —— 不得连带后续通道全部不落库。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

    class _S:
        storage_backend = "mongodb"

    class _Resp:
        def __init__(self, content):
            self._c = content

        def json(self):
            return self._c

    class _OkClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            pid = url.rsplit("=", 1)[-1]
            snaps = {"1": _snap, "8": _bid_snap, "2": _zb_snap, "3": _dt_snap}
            sid = "300001" if pid == "8" else "600001" if pid in ("2", "3") else "000001"
            return _Resp(snaps[pid](100.0, [sid], date="2026-11-08"))

    monkeypatch.setattr(arch.httpx, "AsyncClient", _OkClient)

    def _boom_zb(db, snap, *, now=None):   # 模拟 Mongo 写失败（落库阶段异常）
        raise OSError("mongo down")

    monkeypatch.setattr(arch, "archive_zb_snapshot", _boom_zb)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db, interval_seconds=60)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    # 炸板池落库失败：只本通道结构化失败，其余三通道照常落库
    assert res["pool"]["ok"] is True and res["bid"]["ok"] is True and res["dt"]["ok"] is True
    assert res["zb"]["ok"] is False and res["zb"]["reason"].startswith("archive_failed:")
    assert "zb:archive_failed:" in archiver.status()["lastError"]
    doc = db._coll.rows["2026-11-08"]
    assert "items" in doc and "bid_items" in doc and "dt_items" in doc and "zb_items" not in doc


def test_no_sealed_keys_on_non_mark_lanes():
    """竞价/炸板池不写 <p>sealed_n / <p>broken_n（评审 P2-3 第 2 条）。"""
    db = _FakeDb()
    archive_bid_snapshot(db, _bid_snap(100.0, ["300001"], date="2026-11-08"))
    archive_zb_snapshot(db, _zb_snap(100.0, ["600001"], date="2026-11-08"))
    doc = db._coll.rows["2026-11-08"]
    for prefix in ("bid_", "zb_"):
        assert prefix + "sealed_n" not in doc and prefix + "broken_n" not in doc
    r_zb = archive_zb_snapshot(db, _zb_snap(200.0, ["600001"], date="2026-11-08"))
    assert "sealed_n" not in r_zb and "broken_n" not in r_zb


def test_stale_noise_key_preserved():
    """旧档残留噪声键（如早期 bid_sealed_n）在后续通道写入时被保留（不擅自清理他人数据）。"""
    db = _FakeDb()
    db._coll.rows["2026-11-08"] = {"_id": "2026-11-08", "bid_sealed_n": 0}
    archive_zb_snapshot(db, _zb_snap(100.0, ["600001"], date="2026-11-08"))
    doc = db._coll.rows["2026-11-08"]
    assert doc.get("bid_sealed_n") == 0 and len(doc["zb_items"]) == 1


def test_load_day_invalid_lane():
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-08"))
    r = load_day(db, "2026-11-08", lane="nope")
    assert r["ok"] is False and r["reason"] == "invalid_lane" and r["lane"] == "nope"


def test_four_lanes_same_doc_all_readable():
    """四通道同档共存：一次写全后四种 lane 各读一次，字段互不覆盖（评审 P2-3 第 5 条）。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-08"))
    archive_bid_snapshot(db, _bid_snap(110.0, ["300001"], date="2026-11-08"))
    archive_zb_snapshot(db, _zb_snap(120.0, ["600001"], date="2026-11-08"))
    archive_dt_snapshot(db, _dt_snap(130.0, ["600002"], date="2026-11-08"))
    assert len(db._coll.rows) == 1
    pool = load_day(db, "2026-11-08")
    assert [m["stock_id"] for m in pool["items"]] == ["000001"]
    got = {}
    for lane, prefix, sid in (("bid", "bid_", "300001"), ("zb", "zb_", "600001"),
                              ("dt", "dt_", "600002")):
        r = load_day(db, "2026-11-08", lane=lane)
        got[lane] = (r["ok"], r["ts"], r["items"][0]["stock_id"], r.get("empty"))
        assert r["ok"] and r["pid_type"] == {"bid": 8, "zb": 2, "dt": 3}[lane]
    assert got == {"bid": (True, 110.0, "300001", False),
                   "zb": (True, 120.0, "600001", False),
                   "dt": (True, 130.0, "600002", False)}
    assert pool["bid_items"] and pool["zb_items"] and pool["dt_items"]


def test_legal_empty_pool_recorded_and_readable():
    """源可用但池为空（如 0 家跌停）：记空档且读口返回 ok+empty（不触发前端逐日回退）。"""
    db = _FakeDb()
    empty = {"ok": True, "date": "2026-11-08", "ts": 100.0, "pages_missing": [],
             "max_size": 0, "pages": 1, "pages_expected": 1, "pid_type": 3,
             "raw_len": 12, "pages_meta": [{"index": 0, "count": 0}], "items": []}
    r = archive_dt_snapshot(db, empty)
    assert r["ok"] is True and r["empty"] is True and r["item_n"] == 0
    got = load_day(db, "2026-11-08", lane="dt")
    assert got["ok"] is True and got["empty"] is True and got["items"] == []
    assert "池为空" in got["note"]
    # 空帧不覆盖已有成员：先有成员再收到空帧 → 保留成员，不写清空
    db2 = _FakeDb()
    archive_dt_snapshot(db2, _dt_snap(100.0, ["000001"], date="2026-11-08"))
    r2 = archive_dt_snapshot(db2, dict(empty, ts=200.0))
    assert r2["ok"] is True and r2["empty"] is False and r2["note"] == "empty_snapshot_ignored"
    assert [m["stock_id"] for m in load_day(db2, "2026-11-08", lane="dt")["items"]] == ["000001"]
    # 连页都没收到（源不可用）：不写、不伪装
    r3 = archive_dt_snapshot(_FakeDb(), {k: v for k, v in empty.items() if k != "pages"})
    assert r3["ok"] is False and r3["reason"] == "empty_snapshot"


def test_dt_pages_missing_then_full_frame_marks_broken():
    """跌停池：页缺口帧不标打开，后续完整帧缺席才标 broken（评审 P2-3 第 7 条）。"""
    db = _FakeDb()
    archive_dt_snapshot(db, _dt_snap(100.0, ["000001", "000002"]))
    archive_dt_snapshot(db, _dt_snap(200.0, ["000001"], pages_missing=[0]))
    states = {m["stock_id"]: m.get("pool_state")
              for m in load_day(db, "2026-11-08", lane="dt")["items"]}
    assert states["000002"] == "sealed"
    archive_dt_snapshot(db, _dt_snap(300.0, ["000001"]))
    states = {m["stock_id"]: m.get("pool_state")
              for m in load_day(db, "2026-11-08", lane="dt")["items"]}
    assert states["000002"] == "broken"


# ── 2203 涨停原因语料通道（2026-11-08 用户需求：作为 jev 语料投喂） ──────────────

def _reason_snap(date: str, items: dict, ts: float = 1794338025.0) -> dict:
    return {"ok": True, "date": date, "reasons": items, "count": len(items), "ts": ts}


def _reason_item(sid: str, ts: float, zt: str = "光伏+次新股") -> dict:
    return {"stock_id": sid, "zt": zt, "fx": "", "jc": "", "jj": "", "pledge": "",
            "zt_group": "2连板", "theme": "光伏", "dd": "", "child_theme": "太空光伏",
            "label": "首板", "zt_tag": 3, "rank": 1, "rank_total": 12,
            "rank_top": ["板块龙一"], "plate": "光伏、有机硅", "tp": ["太空"],
            "msg_id": 7, "ts": ts}


def test_reason_corpus_merged_into_same_day_doc():
    """语料与打板通道同集合同日档（不另建数据集），原文透传不改写不拼接。"""
    from backend.services.kpl_daban_archiver import archive_reason_corpus
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    ts = datetime(2026, 11, 6, 14, 40, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_reason_corpus(db, _reason_snap("2026-11-06", {"301697": _reason_item("301697", ts)}),
                              now=datetime(2026, 11, 8, 15, 5, tzinfo=TZ_SHANGHAI))
    assert r["ok"] and r["item_n"] == 1 and r["merged_n"] == 1
    row = db._coll.rows["2026-11-06"]
    assert row["items"][0]["stock_id"] == "000001"          # 打板通道未被覆盖
    assert row["reason_source"] == "socket_2203" and row["reason_count"] == 1
    it = row["reason_items"][0]
    assert it["zt"] == "光伏+次新股" and it["plate"] == "光伏、有机硅"
    assert it["rank_top"] == ["板块龙一"] and it["tp"] == ["太空"]
    assert it["ts_date"] == "2026-11-06" and it["first_ts"] == ts
    # 读口：lane=reason（供 jev 语料消费）
    corpus = load_day(db, "2026-11-06", lane="reason")
    assert corpus["ok"] is True and corpus["lane"] == "reason"
    assert corpus["count"] == 1 and corpus["corpus_source"] == "socket_2203"
    assert corpus["items"][0]["stock_id"] == "301697"


def test_reason_corpus_refreshes_and_keeps_first_ts():
    from backend.services.kpl_daban_archiver import archive_reason_corpus
    db = _FakeDb()
    t1 = datetime(2026, 11, 6, 10, 0, tzinfo=TZ_SHANGHAI).timestamp()
    t2 = datetime(2026, 11, 6, 14, 0, tzinfo=TZ_SHANGHAI).timestamp()
    archive_reason_corpus(db, _reason_snap("2026-11-06", {"301697": _reason_item("301697", t1)}))
    archive_reason_corpus(db, _reason_snap("2026-11-06",
                                           {"301697": {**_reason_item("301697", t2, zt="光伏（更正）"),
                                                       "theme": ""}}))
    it = db._coll.rows["2026-11-06"]["reason_items"][0]
    assert it["zt"] == "光伏（更正）" and it["ts"] == t2 and it["first_ts"] == t1
    assert it["theme"] == "光伏"        # 空字段不覆盖既有原料（不烘成空）


def test_reason_corpus_stale_entries_skipped():
    """跨日残留（推送 ts 早于该交易日）不污染当日档（fail-visible 计数）。"""
    from backend.services.kpl_daban_archiver import archive_reason_corpus
    db = _FakeDb()
    old = datetime(2026, 11, 5, 14, 0, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_reason_corpus(db, _reason_snap("2026-11-06", {"301697": _reason_item("301697", old)}))
    assert r["ok"] is False and r["reason"] == "all_stale" and r["skipped_stale"] == 1
    assert "2026-11-06" not in db._coll.rows            # 不写、不造空档
    # 周末回看：推送 ts=11-08（周日）> 交易日 11-06 → 保留（服务端重推当期详情）
    weekend = datetime(2026, 11, 8, 12, 28, tzinfo=TZ_SHANGHAI).timestamp()
    r2 = archive_reason_corpus(db, _reason_snap("2026-11-06", {"301697": _reason_item("301697", weekend)}))
    assert r2["ok"] is True and db._coll.rows["2026-11-06"]["reason_items"][0]["ts_date"] == "2026-11-08"


def test_reason_corpus_requires_trading_day_and_payload():
    from backend.services.kpl_daban_archiver import archive_reason_corpus, load_reason_corpus
    db = _FakeDb()
    assert archive_reason_corpus(db, {"ok": True, "reasons": {}})["reason"] == "no_pool_date"
    assert archive_reason_corpus(db, {"ok": True, "date": "2026-11-06", "reasons": {}})["reason"] \
        == "empty_reasons"
    assert db._coll.rows == {}
    # 读口：无档 vs 日档在但语料缺 —— 严格区分，不伪装空语料
    assert load_reason_corpus(db, "2026-11-06")["reason"] == "no_archive"
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    miss = load_reason_corpus(db, "2026-11-06")
    assert miss["ok"] is False and miss["reason"] == "no_reason_corpus" and miss["item_n"] == 0


def test_reason_corpus_accepts_items_list_shape():
    """兼容 items list 形态（2203 快照两种载荷）。"""
    from backend.services.kpl_daban_archiver import archive_reason_corpus
    db = _FakeDb()
    ts = datetime(2026, 11, 6, 9, 40, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_reason_corpus(db, {"ok": True, "date": "2026-11-06",
                                   "items": [_reason_item("600001", ts)]})
    assert r["ok"] is True and r["item_n"] == 1


def test_archive_once_fetches_reason_corpus_with_pool_date(monkeypatch):
    """单轮额外拉 :8002 /zt-reasons 并落到涨停池快照交易日（周末详情挂上一交易日）。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

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
            if url.endswith("/zt-reasons"):
                ts = datetime(2026, 11, 8, 12, 28, tzinfo=TZ_SHANGHAI).timestamp()
                return _Resp({"ok": True, "reasons": {"301697": _reason_item("301697", ts)},
                              "count": 1, "ts": ts})
            if url.endswith("pid_type=1"):
                return _Resp(_snap(100.0, ["000001"], date="2026-11-06"))
            if url.endswith("pid_type=8"):
                return _Resp(_bid_snap(200.0, ["300001"], date="2026-11-06"))
            return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fake_gene)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    assert res["pool"]["ok"] is True and res["reason"]["ok"] is True
    assert res["reason"]["date"] == "2026-11-06"      # 跟随涨停池交易日，不挂周日
    row = db._coll.rows["2026-11-06"]
    assert row["reason_items"][0]["stock_id"] == "301697"
    assert row["items"][0]["stock_id"] == "000001"     # 打板通道同档共存
    assert "reason:" not in (archiver.status()["lastError"] or "")   # 语料通道不报错

    # 无涨停池交易日（如 collector 全降级）→ 不猜日期、不写语料
    class _Degraded(_Client):
        async def get(self, url, timeout=None):
            if url.endswith("pid_type=1"):
                return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})
            return await super().get(url, timeout)

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Degraded)
    db2 = _FakeDb()
    archiver2 = DabanPoolArchiver(settings=_S(), database_factory=lambda: db2,
                                  interval_seconds=60, gene_fetcher=_fake_gene)
    asyncio.run(archiver2._archive_once())
    assert archiver2.status()["lastResult"]["reason"]["reason"] == "no_pool_date"
    # 竞价通道仍可独立落库；语料字段不写（日期不明不猜）
    assert all("reason_items" not in r for r in db2._coll.rows.values())



def test_gene_corpus_fields_survive_lane_writes():
    """评审 R2-P1：字段级 $set 并发合同 —— 模拟 gene 语料先写，lane 整通道写不得回写冲掉。"""
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = {"_id": "2026-11-06", "gene_items": [{"stock_id": "301697"}],
                                   "gene_archived_at": "2026-11-08T15:00:00+08:00"}
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    row = db._coll.rows["2026-11-06"]
    assert row["gene_items"] == [{"stock_id": "301697"}] and "gene_archived_at" in row
    assert row["items"][0]["stock_id"] == "000001"      # 本通道字段照写
    # 反向：lane 先写，gene $set 只加字段也不冲 lane
    db._coll.update_one({"_id": "2026-11-06"}, {"$set": {"gene_count": 1}}, upsert=True)
    assert db._coll.rows["2026-11-06"]["items"][0]["stock_id"] == "000001"


def test_reason_corpus_stale_pool_date_skipped(monkeypatch):
    """评审 R2-P2：涨停池快照日期过旧（>3 天）→ stale_pool_date 不落库（不把当日详情挂进旧档）。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

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
            if url.endswith("/zt-reasons"):
                return _Resp({"ok": True, "reasons": {}, "count": 0, "ts": 1.0})
            if url.endswith("pid_type=1"):
                return _Resp(_snap(100.0, ["000001"], date="2026-10-01"))   # 一多月前
            return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db, interval_seconds=60)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    assert res["reason"]["ok"] is False and res["reason"]["reason"] == "stale_pool_date"
    # pool 通道照常落自己的档（那是它的事实）；语料字段不得挂进旧交易日档
    assert "reason_items" not in db._coll.rows.get("2026-10-01", {})


# ── 涨停基因语料通道（2026-11-08，题材龙头语料投喂 jev；前端不上）───────────────

def test_pick_gene_targets_missing_first_limit_and_close_refresh():
    """缺失优先、limit 控发数、收盘后仅对盘中旧值刷一次（不重复刷新）。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002", "000003"], date="2026-11-06"))
    before_close = datetime(2026, 11, 6, 10, 30, tzinfo=TZ_SHANGHAI)
    plan = pick_gene_targets(db, "2026-11-06", limit=2, now=before_close)
    assert plan["ok"] is True and plan["targets"] == ["000001", "000002"]
    assert plan["pending_n"] == 3 and plan["refresh_n"] == 0 and plan["after_close"] is False

    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000001")]},
                        now=before_close)
    after_close = datetime(2026, 11, 6, 15, 30, tzinfo=TZ_SHANGHAI)
    plan2 = pick_gene_targets(db, "2026-11-06", limit=5, now=after_close)
    assert plan2["targets"] == ["000002", "000003", "000001"]   # 缺失优先、旧值排队尾
    assert plan2["pending_n"] == 2 and plan2["refresh_n"] == 1 and plan2["after_close"] is True

    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000001")]},
                        now=after_close)
    plan3 = pick_gene_targets(db, "2026-11-06", limit=5, now=after_close)
    assert plan3["targets"] == ["000002", "000003"] and plan3["refresh_n"] == 0


def test_pick_gene_targets_no_archive_and_empty_pool():
    assert pick_gene_targets(_FakeDb(), "2026-11-06")["reason"] == "no_archive"
    db = _FakeDb()
    db._coll.rows["2026-11-06"] = {"_id": "2026-11-06", "items": []}
    assert pick_gene_targets(db, "2026-11-06")["reason"] == "empty_pool"


def test_archive_gene_corpus_union_pending_and_failures():
    """并集写入 + raw 原样 + 覆盖度 pending + 失败进 gene_failures（不伪装 0）。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002"], date="2026-11-06"))
    out = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [
        _fake_gene("000001"),
        {"ok": False, "stock_id": "000002", "degraded": True, "reason": "1020", "error": "白名单"},
    ]}, now=datetime(2026, 11, 6, 14, 0, tzinfo=TZ_SHANGHAI))
    assert out["ok"] is True and out["merged_n"] == 1 and out["failures_n"] == 1
    assert out["pending_n"] == 1
    row = db._coll.rows["2026-11-06"]
    assert row["gene_count"] == 1 and row["gene_pending_n"] == 1
    assert row["gene_items"][0]["raw"] == [4, 1, 50, 100, 0, 50]
    assert row["gene_items"][0]["source"] == "http_GetZhangTingGene"
    assert row["gene_items"][0]["same_day"] is True
    assert row["gene_failures"][0]["stock_id"] == "000002"
    assert [m["stock_id"] for m in row["items"]] == ["000001", "000002"]   # 打板通道不被覆盖
    assert "reason_items" not in row and "zb_items" not in row

    out2 = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000002")]},
                               now=datetime(2026, 11, 6, 14, 30, tzinfo=TZ_SHANGHAI))
    assert out2["pending_n"] == 0 and out2["item_n"] == 2
    assert db._coll.rows["2026-11-06"]["gene_failures"] == []


def test_gene_point_in_time_flags():
    """回填（抓取日≠日档交易日）标 same_day=False + 读口 backfill_n/note 提示。"""
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002"], date="2026-11-06"))
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000001")]},
                        now=datetime(2026, 11, 6, 15, 30, tzinfo=TZ_SHANGHAI))
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000002")]},
                        now=datetime(2026, 11, 8, 20, 0, tzinfo=TZ_SHANGHAI))
    items = {it["stock_id"]: it for it in db._coll.rows["2026-11-06"]["gene_items"]}
    assert items["000001"]["same_day"] is True and items["000001"]["fetched_date"] == "2026-11-06"
    assert items["000002"]["same_day"] is False and items["000002"]["fetched_date"] == "2026-11-08"
    out = load_gene_corpus(db, "2026-11-06")
    assert out["same_day_n"] == 1 and out["backfill_n"] == 1
    assert "回填抓取" in out["note"] and "不得当该日盘后已知信息使用" in out["note"]


def test_archive_gene_corpus_all_failed_and_no_date():
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    out = archive_gene_corpus(db, {"date": "2026-11-06", "genes": [
        {"ok": False, "stock_id": "000001", "reason": "1020", "error": "白名单"}]})
    assert out["ok"] is False and out["reason"] == "no_gene_fetched"
    assert "gene_items" not in db._coll.rows["2026-11-06"]   # 不写、不覆盖既有
    assert db._coll.rows["2026-11-06"]["items"]             # 打板通道原样
    assert archive_gene_corpus(db, {"genes": [_fake_gene("000001")]})["reason"] == "no_pool_date"


def test_load_gene_corpus_degraded_and_ok():
    db = _FakeDb()
    assert load_gene_corpus(db, "2026-11-06")["reason"] == "no_archive"
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    assert load_gene_corpus(db, "2026-11-06")["reason"] == "no_gene_corpus"
    archive_gene_corpus(db, {"date": "2026-11-06", "genes": [_fake_gene("000001")]})
    out = load_gene_corpus(db, "2026-11-06")
    assert out["ok"] is True and out["count"] == 1 and out["pending_n"] == 0
    assert out["corpus_source"] == "http_GetZhangTingGene"
    assert "未标注统计窗口" in out["items"][0]["window_note"]
    assert load_day(db, "2026-11-06", lane="gene")["count"] == 1   # 统一 lane 分发


def test_archiver_gene_lane_round(monkeypatch):
    """单轮：pool 落库后按 limit 懒取基因写 gene_items，失败只记 failures 不连带其它通道。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

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
            if url.endswith("pid_type=1"):
                return _Resp(_snap(100.0, ["000001", "000002", "000003"], date="2026-11-06"))
            if url.endswith("/zt-reasons"):
                return _Resp({"ok": False, "degraded": True, "reason": "no_zt_reason_snapshot"})
            return _Resp({"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})

    calls: list[str] = []

    def _fetch(sid: str) -> dict:
        calls.append(sid)
        return _fake_gene(sid) if sid != "000002" else {"ok": False, "stock_id": sid,
                                                       "reason": "1020", "error": "白名单"}

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fetch, gene_limit=2)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["gene"]
    assert calls == ["000001", "000002"]         # limit=2 控发数
    assert res["ok"] is True and res["merged_n"] == 1 and res["pending_n"] == 2
    row = db._coll.rows["2026-11-06"]
    assert [g["stock_id"] for g in row["gene_items"]] == ["000001"]
    assert row["gene_failures"][0]["stock_id"] == "000002"
    assert archiver.status()["lastResult"]["pool"]["ok"] is True   # 其它通道不受影响
