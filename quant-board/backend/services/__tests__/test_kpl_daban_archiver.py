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
    archive_lhb_forecast,
    archive_lhb_realtime,
    archive_snapshot,
    archive_stock_detail_corpus,
    archive_zb_snapshot,
    load_day,
    load_gene_corpus,
    load_lhb_forecast,
    load_lhb_realtime,
    load_stock_detail_corpus,
    pick_gene_targets,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


from backend.services import kpl_stock_notice as N


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

    def find_one(self, q: dict, sort: list | None = None) -> dict | None:
        """仿 Mongo 语义：精确 _id 走 key 查找，其余条件走扫描；**返回副本**不暴露内行。

        （返回副本是关键：读口 load_day 会 pop _id，若返回 live dict 会把库内 _id 抹掉，
        而字段级 $set 写库不再补写 _id —— mock 与生产 Mongo 的 copy 语义必须一致。）
        """
        if not sort and set(q) == {"_id"} and isinstance(q["_id"], str):
            row = self.rows.get(q["_id"])
            return dict(row) if row else None
        rows = [(k, dict(r)) for k, r in self.rows.items()]
        if sort:
            for field, direction in reversed(sort):
                rows.sort(key=lambda kv: str(kv[1].get(field) or ""), reverse=direction < 0)
        for _key, row in rows:
            ok = True
            for field, cond in q.items():
                val = row.get(field)
                if field == "items.0":          # 数组非空判定（先于 $exists 分支）
                    if not row.get("items"):
                        ok = False
                elif isinstance(cond, dict):
                    if "$exists" in cond and (val is not None) != bool(cond["$exists"]):
                        ok = False
                    if "$gte" in cond and not (val is not None and str(val) >= str(cond["$gte"])):
                        ok = False
                elif val != cond:
                    ok = False
                if not ok:
                    break
            if ok:
                return row
        return None


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


# 周日 11-08（非交易日）：周末会话推送上一交易日（周五 11-06）详情，既有口径保留
_TEST_CLOCK = lambda: datetime(2026, 11, 8, 10, 0, tzinfo=TZ_SHANGHAI)


def _patch_trading_calendar(monkeypatch) -> None:
    """护栏交易日判定打桩（周一~五启发，不发真实 bridge HTTP；pytest 红线）。"""
    from backend.services import kpl_daban_archiver as arch
    monkeypatch.setattr(arch, "is_trading_day_cached",
                         lambda d: (d.weekday() < 5, "test"))


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
            return _Resp(_snap(100.0, ["000001"], date="2026-11-06") if url.endswith("pid_type=1")
                         else _bid_snap(200.0, ["300001"], date="2026-11-06"))

    monkeypatch.setattr(arch.httpx, "AsyncClient", _FailClient)
    _patch_trading_calendar(monkeypatch)
    db = _FakeDb()
    archiver = DabanPoolArchiver(
        settings=_S(), database_factory=lambda: db, interval_seconds=60,
        gene_fetcher=_fake_gene, clock=_TEST_CLOCK)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    # 涨停/竞价正常落库；炸板池 fetch 失败、跌停池 collector 降级：各自结构化透出，互不连带
    assert res["pool"]["ok"] is True and res["bid"]["ok"] is True
    assert res["zb"]["ok"] is False and res["zb"]["reason"].startswith("fetch_failed:")
    assert res["dt"]["ok"] is False and res["dt"]["reason"].startswith("collector_degraded:")
    assert archiver.status()["lastError"]
    # db 里只有 pool/bid 两通道写了当日档
    row = db._coll.rows["2026-11-06"]
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
            return _Resp(snaps[pid](100.0, [sid], date="2026-11-06"))

    monkeypatch.setattr(arch.httpx, "AsyncClient", _OkClient)

    def _boom_zb(db, snap, *, now=None):   # 模拟 Mongo 写失败（落库阶段异常）
        raise OSError("mongo down")

    monkeypatch.setattr(arch, "archive_zb_snapshot", _boom_zb)
    _patch_trading_calendar(monkeypatch)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, clock=_TEST_CLOCK)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    # 炸板池落库失败：只本通道结构化失败，其余三通道照常落库
    assert res["pool"]["ok"] is True and res["bid"]["ok"] is True and res["dt"]["ok"] is True
    assert res["zb"]["ok"] is False and res["zb"]["reason"].startswith("archive_failed:")
    assert "zb:archive_failed:" in archiver.status()["lastError"]
    doc = db._coll.rows["2026-11-06"]
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


def test_reason_corpus_source_override_http_backfill():
    """来源标注参数（2026-11-09 HTTP 档案链回填）：doc 级 reason_source 跟随，
    HTTP 原文字段（gns/boom_zs/sclt/zs_codes/matched_date/source）透传不丢。"""
    from backend.services.kpl_daban_archiver import archive_reason_corpus
    db = _FakeDb()
    ts = datetime(2026, 11, 9, 15, 40, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_reason_corpus(
        db, _reason_snap("2026-11-06", {"301697": {
            "zt": "光伏+储能全文", "gns": "概念解析", "boom_zs": "媒体催化",
            "sclt": "日内梯队", "zs_codes": ["801464"], "matched_date": "2026-11-06",
            "source": "http_GetDayZhangTing", "ts": ts}}),
        source="http_GetDayZhangTing")
    assert r["ok"] and r["merged_n"] == 1
    row = db._coll.rows["2026-11-06"]
    assert row["reason_source"] == "http_GetDayZhangTing"
    it = row["reason_items"][0]
    assert it["zt"] == "光伏+储能全文" and it["gns"] == "概念解析"
    assert it["zs_codes"] == ["801464"] and it["source"] == "http_GetDayZhangTing"
    # 默认不传 source 仍是 socket_2203（既有合同不变）
    db2 = _FakeDb()
    archive_reason_corpus(db2, _reason_snap("2026-11-06", {"301697": _reason_item("301697", ts)}))
    assert db2._coll.rows["2026-11-06"]["reason_source"] == "socket_2203"


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


def test_latest_archived_pool_day_fallback():
    """:8002 无快照时用库内最近含成员的日档（限 10 天内，超窗不补）。"""
    from backend.services.kpl_daban_archiver import latest_archived_pool_day

    db = _FakeDb()
    assert latest_archived_pool_day(db) is None
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-05"))
    archive_snapshot(db, _snap(200.0, ["000002"], date="2026-11-06"))
    db._coll.rows["2026-10-01"] = {"_id": "2026-10-01", "items": [{"stock_id": "000009"}]}
    now = datetime(2026, 11, 8, 20, 0, tzinfo=TZ_SHANGHAI)
    assert latest_archived_pool_day(db, now=now) == "2026-11-06"      # 最近档
    assert latest_archived_pool_day(db, now=datetime(2026, 11, 20, 20, 0,
                                                     tzinfo=TZ_SHANGHAI)) is None   # 超窗


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
    _patch_trading_calendar(monkeypatch)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fetch, gene_limit=2,
                                 clock=_TEST_CLOCK)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["gene"]
    assert calls == ["000001", "000002"]         # limit=2 控发数
    assert res["ok"] is True and res["merged_n"] == 1 and res["pending_n"] == 2
    row = db._coll.rows["2026-11-06"]
    assert [g["stock_id"] for g in row["gene_items"]] == ["000001"]
    assert row["gene_failures"][0]["stock_id"] == "000002"
    assert archiver.status()["lastResult"]["pool"]["ok"] is True   # 其它通道不受影响


def test_archiver_gene_backfills_when_collector_down(monkeypatch):
    """采集器未运行（快照全降级）时：gene 通道回退库内最近日档补语料，其它通道正常降级。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

    class _S:
        storage_backend = "mongodb"

    class _Resp:
        def json(self):
            return {"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"}

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, timeout=None):
            return _Resp()

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002"], date="2026-11-06"))
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fake_gene, gene_limit=2)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    assert res["pool"]["ok"] is False and "collector_degraded" in res["pool"]["reason"]
    assert res["gene"]["ok"] is True and res["gene"]["date_source"] == "local_archive"
    row = db._coll.rows["2026-11-06"]
    assert [g["stock_id"] for g in row["gene_items"]] == ["000001", "000002"]
    assert row["gene_pending_n"] == 0
    assert row["gene_items"][0]["same_day"] is False     # 11-08 回填 11-06 档


# ── 2013 题材库热度语料通道（2026-11-08 题材龙头语料第 2 项，与 reason 通道同款） ──

def _theme_snap(date: str, items: dict, ts: float = 1794338025.0) -> dict:
    return {"ok": True, "date": date, "themes": items, "count": len(items), "ts": ts}


def _theme_item(sid: str, ts: float) -> dict:
    return {"stock_id": sid, "name": "贝特利", "ts": ts,
            "themes": [{"id": "80001", "name": "光伏", "number": 96.5},
                       {"id": "80002", "name": "有机硅", "number": 71.0}]}


def test_theme_corpus_merged_into_same_day_doc():
    """语料与打板通道同集合同日档 theme_ 前缀字段（不另建数据集），字段级 $set。"""
    from backend.services.kpl_daban_archiver import archive_theme_corpus, load_theme_corpus
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    ts = datetime(2026, 11, 6, 14, 40, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_theme_corpus(db, _theme_snap("2026-11-06", {"301697": _theme_item("301697", ts)}),
                             now=datetime(2026, 11, 6, 14, 45, tzinfo=TZ_SHANGHAI))
    assert r["ok"] is True and r["item_n"] == 1
    row = db["kpl_daban_pool"].rows["2026-11-06"]
    assert row["theme_source"] == "socket_2013" and row["theme_count"] == 1
    assert row["theme_items"][0]["themes"][0]["name"] == "光伏"
    # 增量合并（并集），既有条目字段随最新帧刷新
    archive_theme_corpus(db, _theme_snap("2026-11-06",
                                         {"002614": _theme_item("002614", ts + 30)}),
                         now=datetime(2026, 11, 6, 14, 50, tzinfo=TZ_SHANGHAI))
    row2 = db["kpl_daban_pool"].rows["2026-11-06"]
    assert row2["theme_count"] == 2
    assert "items.0.stock_id" not in row2   # 池 items 不被语料回写冲掉
    loaded = load_theme_corpus(db, "2026-11-06")
    assert loaded["ok"] is True and loaded["count"] == 2


def test_theme_corpus_stale_and_empty_snapshots():
    """跨日残留保护 + 空快照/无日期结构化降级（与 reason 通道同款合同）。"""
    from backend.services.kpl_daban_archiver import archive_theme_corpus, load_theme_corpus
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001"], date="2026-11-06"))
    old = datetime(2026, 11, 5, 14, 40, tzinfo=TZ_SHANGHAI).timestamp()
    r = archive_theme_corpus(db, _theme_snap("2026-11-06", {"301697": _theme_item("301697", old)}))
    assert r["ok"] is False and r["reason"] == "all_stale" and r["skipped_stale"] == 1
    assert archive_theme_corpus(db, {"ok": True, "themes": {}})["reason"] == "no_pool_date"
    assert archive_theme_corpus(db, _theme_snap("2026-11-06", {}))["reason"] == "empty_themes"
    # 读口降级：日档缺失 vs 语料未落库严格分开
    assert load_theme_corpus(db, "2026-11-07")["reason"] == "no_archive"
    assert load_theme_corpus(db, "2026-11-06")["reason"] == "no_theme_corpus"


# ── 公告计数语料通道（2026-11-08 题材龙头语料第 3 项，与 gene 通道同款懒取） ──

def _notice_result(sid: str, ok: bool = True) -> dict:
    if not ok:
        return {"ok": False, "reason": "http_error", "stock_id": sid}
    return {"ok": True, "stock_id": sid,
            "counts": {"announcement": 2, "report": 1, "news": 0},
            "upstream_date": "20261106", "window_note": N.WINDOW_NOTE}


def test_notice_corpus_lazy_targets_and_merge():
    """懒取目标（缺失优先/收盘后终值刷新）+ 并集落库 + pending/failures 暴露。"""
    from backend.services.kpl_daban_archiver import (archive_notice_corpus,
                                                     load_notice_corpus, pick_notice_targets)
    db = _FakeDb()
    archive_snapshot(db, _snap(100.0, ["000001", "000002"], date="2026-11-06"))
    now = datetime(2026, 11, 6, 14, 40, tzinfo=TZ_SHANGHAI)
    plan = pick_notice_targets(db, "2026-11-06", limit=1, now=now)
    assert plan["ok"] is True and plan["targets"] == ["000001"] and plan["pending_n"] == 2
    r = archive_notice_corpus(db, {"date": "2026-11-06", "notices": [
        _notice_result("000001"), _notice_result("000002", ok=False)]},
        now=now)
    assert r["ok"] is True and r["item_n"] == 1 and r["failures_n"] == 1 and r["pending_n"] == 1
    row = db["kpl_daban_pool"].rows["2026-11-06"]
    assert row["notice_source"] == "http_GetCompanyCount"
    assert row["notice_items"][0]["counts"]["announcement"] == 2
    assert row["notice_items"][0]["same_day"] is True
    loaded = load_notice_corpus(db, "2026-11-06")
    assert loaded["ok"] is True and loaded["count"] == 1 and loaded["backfill_n"] == 0
    # 全失败且无既有 → 结构化降级不覆盖
    r2 = archive_notice_corpus(db, {"date": "2026-11-07",
                                    "notices": [_notice_result("X", ok=False)]})
    assert r2["ok"] is False and r2["reason"] == "no_notice_fetched"
    assert load_notice_corpus(db, "2026-11-07")["reason"] == "no_archive"


# ── 快照日期新鲜度护栏（2026-11-09 盘中错档事故固化）──────────────────────────
# 事故：11-09（周一）盘前/早盘帧 date 滞留 2026-11-06（上游翻日滞留），当日 zb/dt/bid
# 甚至 pool 帧被成员并集合并进 11-06 历史档，污染其收盘终态。

def test_snapshot_date_freshness_pure_function():
    """纯函数口径：交易日只收当日；非交易日只收最近交易日；非法日期不猜。"""
    from backend.services.kpl_daban_archiver import snapshot_date_freshness_error
    from backend.snapshot_collector.trading_calendar import is_trading_day_cached as _real

    monday = datetime(2026, 11, 9, 10, 0, tzinfo=TZ_SHANGHAI)     # 交易日盘中
    sunday = datetime(2026, 11, 8, 10, 0, tzinfo=TZ_SHANGHAI)     # 非交易日
    assert snapshot_date_freshness_error("2026-11-09", monday) is None
    assert snapshot_date_freshness_error("2026-11-06", monday) == "stale_snapshot_date"
    assert snapshot_date_freshness_error("2026-11-06", sunday) is None   # 周末收上一交易日
    assert snapshot_date_freshness_error("2026-11-05", sunday) == "stale_snapshot_date"
    assert snapshot_date_freshness_error("", monday) == "invalid_snapshot_date"
    assert snapshot_date_freshness_error("20261109", monday) == "invalid_snapshot_date"
    # 注：不在此处调真实 is_trading_day_cached（含 bridge HTTP 探测，环境漂移）——
    # 日历本身的断言属 trading_calendar 测试（评审 MINOR）


def test_archive_once_precomputes_trading_context_once(monkeypatch):
    """评审 R2-MAJOR 回归：交易日上下文每轮仅预计算一次（to_thread），非逐 lane 重复探测。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch

    calls = []
    # 上下文直接打桩（非交易日 + 最近交易日 11-06，与 _TEST_CLOCK 周日口径一致）
    monkeypatch.setattr(arch, "_trading_day_context",
                        lambda now: calls.append(now) or (False, "2026-11-06"))

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
            if url.endswith("pid_type=2"):
                return _Resp(_bid_snap(200.0, ["300001"], date="2026-11-06"))
            if url.endswith("pid_type=3"):
                return _Resp(_snap(100.0, ["400001"], date="2026-11-06"))
            if "/reasons" in url:
                return _Resp({"ok": True, "date": "2026-11-06", "reasons": {}})
            if "/themes" in url:
                return _Resp({"ok": True, "date": "2026-11-06", "themes": {}})
            return _Resp(_snap(100.0, ["000001"], date="2026-11-06"))

    monkeypatch.setattr(arch.httpx, "AsyncClient", _OkClient)
    db = _FakeDb()
    archiver = DabanPoolArchiver(
        database_factory=lambda: db, interval_seconds=60,
        gene_fetcher=_fake_gene, clock=_TEST_CLOCK)
    asyncio.run(archiver._archive_once())
    assert len(calls) == 1   # 四通道 + reason/theme 共 6 次判定，上下文只探测一次
    res = archiver.status()["lastResult"]
    for lane in ("pool", "bid", "zb", "dt"):
        assert res[lane]["ok"] is True


def test_archive_once_stale_date_lane_skipped(monkeypatch):
    """事故回归：交易日（周一）收到 date=上周五的帧 → 四通道逐通道 skip，零落库。"""
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
                return _Resp(_snap(100.0, ["000001"], date="2026-11-06"))
            if url.endswith("pid_type=8"):
                return _Resp(_bid_snap(200.0, ["300001"], date="2026-11-06"))
            if url.endswith("pid_type=2"):
                return _Resp(_zb_snap(300.0, ["600001"], date="2026-11-06"))
            return _Resp(_dt_snap(400.0, ["000002"], date="2026-11-06"))

    monday_clock = lambda: datetime(2026, 11, 9, 10, 0, tzinfo=TZ_SHANGHAI)
    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    _patch_trading_calendar(monkeypatch)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fake_gene,
                                 clock=monday_clock)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    for lane in ("pool", "bid", "zb", "dt"):
        assert res[lane]["ok"] is False and res[lane]["reason"] == "stale_snapshot_date"
        assert res[lane]["date"] == "2026-11-06"
    # 零落库：错档写入不会发生（事故里这批帧会并进 2026-11-06 档）
    assert db._coll.rows.get("2026-11-06") is None
    # pool_date 未产出 → 基因不猜日期；reason/theme 已迁移 collector 推送即落库
    # （单写者，2026-11-10 裁决），本服务仅标注迁移态（不再产出 no_pool_date）
    assert res["reason"].get("note") == "moved_to_collector_push_time"
    assert res["theme"].get("note") == "moved_to_collector_push_time"
    assert res["gene"]["reason"] in ("no_pool_date", "no_archive")


def test_archive_once_fresh_date_still_archives(monkeypatch):
    """交易日收到当日帧：护栏放行，照常落库（不因护栏误伤正常采集）。"""
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
            pid = url.rsplit("=", 1)[-1] if "pid_type" in url else ""
            snaps = {"1": _snap, "8": _bid_snap, "2": _zb_snap, "3": _dt_snap}
            sid = "300001" if pid == "8" else "600001" if pid in ("2", "3") else "000001"
            if not pid:
                return _Resp({"ok": False, "degraded": True, "reason": "no_zt_reason_snapshot"})
            return _Resp(snaps[pid](100.0, [sid], date="2026-11-09"))

    monday_clock = lambda: datetime(2026, 11, 9, 10, 0, tzinfo=TZ_SHANGHAI)
    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    _patch_trading_calendar(monkeypatch)
    db = _FakeDb()
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fake_gene,
                                 clock=monday_clock)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    assert all(res[lane]["ok"] is True for lane in ("pool", "bid", "zb", "dt"))
    row = db._coll.rows["2026-11-09"]
    assert "items" in row and "bid_items" in row and "zb_items" in row and "dt_items" in row


# ── 板块身位通道（2026-11-10 用户需求「当日实时身位 + 落库」，龙头三合一） ──────

class _FramesColl:
    def __init__(self, dates):
        self._dates = dates

    def find(self, query, projection=None):
        lo = query.get("tradingDate", {}).get("$lt", "9999")
        return [{"tradingDate": d} for d in self._dates if d < lo]


class _ProjTolerantCollection(_FakeCollection):
    """lead 通道 find_one 带 projection 实参（生产 Mongo 语义）；假库忽略投影返回整行。"""

    def find_one(self, q, projection=None, sort=None):
        if set(q) == {"_id"} and isinstance(q.get("_id"), str):
            row = self.rows.get(q["_id"])
            return dict(row) if row else None
        return super().find_one(q, sort)


class _LeadAwareDb(_FakeDb):
    """带 snapshot_frames 的假库（lead 通道 trading_dates_before 交易日轴用）。"""

    def __init__(self, frame_dates):
        super().__init__()
        self._coll = _ProjTolerantCollection()
        self._frame_dates = frame_dates

    def __getitem__(self, name):
        if name == "snapshot_frames":
            return _FramesColl(self._frame_dates)
        return self._coll


def test_archive_once_lead_channel(monkeypatch):
    """lead 通道：pool 归档成功后计算身位落库（lead_ 前缀），fetcher 全桩零真实 TDX。"""
    import asyncio
    from backend.services import kpl_daban_archiver as arch
    from backend.services import kpl_lead_service as lead

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
            return _Resp(_snap(100.0, ["000001"], date="2026-11-06")
                         if url.endswith("pid_type=1") else
                         {"ok": False, "degraded": True, "reason": "no_daban_list_snapshot"})

    monkeypatch.setattr(arch.httpx, "AsyncClient", _Client)
    _patch_trading_calendar(monkeypatch)
    # 红线 7：TDX/涨跌幅取数全桩（默认实现替换，pytest 零真实外部调用）
    monkeypatch.setattr(lead, "_default_gains_fetcher", lambda c, d: {x: 20.0 for x in c})
    monkeypatch.setattr(lead, "_default_day_change_fetcher", lambda c, d: {x: -1.0 for x in c})
    db = _LeadAwareDb(frame_dates=["2026-11-05", "2026-11-04"])
    archiver = DabanPoolArchiver(settings=_S(), database_factory=lambda: db,
                                 interval_seconds=60, gene_fetcher=_fake_gene,
                                 clock=_TEST_CLOCK)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    assert res["pool"]["ok"] is True and res["lead"]["ok"] is True
    assert res["lead"]["boards_n"] == 1
    row = db._coll.rows["2026-11-06"]
    lad = row["lead_boards"]["801464"]["items"]
    assert lad[0]["code"] == "000001" and lad[0]["label"] == "龙一"
    assert row["lead_source"] == "leader_trinity_v1"
    assert sorted(row["lead_missing_pool_dates"]) == ["2026-11-04", "2026-11-05"]   # 缺日披露
    # 历史日缺档：lead 结构化失败不伪装（其它通道不受影响）
    db2 = _FakeDb()
    archiver2 = DabanPoolArchiver(settings=_S(), database_factory=lambda: db2,
                                  interval_seconds=60, gene_fetcher=_fake_gene,
                                  clock=lambda: datetime(2026, 11, 9, 10, 0, tzinfo=TZ_SHANGHAI))
    asyncio.run(archiver2._archive_once())
    assert archiver2.status()["lastResult"]["lead"]["ok"] is False


# ---------- 2026-11-11 ③④：fc/rt 落库 + 个股详情四通道（同款并集合同） ----------

def _fc_item(sid: str, hot: int = 100, ts: float = 1794289200.0) -> dict:
    return {"stock_id": sid, "stock_name": f"股{sid}", "hot_val": hot,
            "main_net_amount": 12345, "ts": ts, "ts_date": "2026-11-10"}


def test_archive_lhb_forecast_union_refresh_and_stale_skip():
    db = _FakeDb()
    r1 = archive_lhb_forecast(db, {"date": "2026-11-10", "items": [
        _fc_item("603278"), _fc_item("000001")]})
    assert r1["ok"] and r1["item_n"] == 2
    # 并集 + 字段随新帧刷新
    r2 = archive_lhb_forecast(db, {"date": "2026-11-10", "items": [
        dict(_fc_item("603278", hot=200), ts=1794290000.0), _fc_item("000002")]})
    assert r2["ok"] and r2["item_n"] == 3 and r2["merged_n"] == 2
    row = db._coll.rows["2026-11-10"]
    items = {i["stock_id"]: i for i in row["fc_items"]}
    assert items["603278"]["hot_val"] == 200
    assert items["603278"]["first_ts"] == 1794289200.0, "first_ts 首次到流不覆盖"
    # 跨日残留 skip
    r3 = archive_lhb_forecast(db, {"date": "2026-11-10", "items": [
        dict(_fc_item("999999"), ts=1790000000.0)]})
    assert r3["ok"] is False and r3["reason"] == "all_stale" and r3["skipped_stale"] == 1
    assert "999999" not in {i["stock_id"] for i in row["fc_items"]}


def test_archive_lhb_forecast_empty_suppression_and_no_date():
    db = _FakeDb()
    r = archive_lhb_forecast(db, {"date": "2026-11-10", "items": []})
    assert r["ok"] is False and r["reason"] == "empty_fc_items" and r["empty"] is True, \
        "空帧抑制（不覆盖非空）"
    assert archive_lhb_forecast(db, {"items": [_fc_item("000001")]})["reason"] == "no_pool_date"


def test_load_lhb_forecast_layers():
    db = _FakeDb()
    assert load_lhb_forecast(db, "2026-11-10")["reason"] == "no_archive"
    db._coll.update_one({"_id": "2026-11-10"}, {"$set": {"date": "2026-11-10"}}, upsert=True)
    assert load_lhb_forecast(db, "2026-11-10")["reason"] == "no_fc_corpus", \
        "日档在但语料未落库 ≠ 无档（fail-visible 分层）"
    archive_lhb_forecast(db, {"date": "2026-11-10", "items": [_fc_item("603278")]})
    loaded = load_lhb_forecast(db, "2026-11-10")
    assert loaded["ok"] and loaded["items"][0]["stock_id"] == "603278"


def test_archive_lhb_realtime_union_contract():
    db = _FakeDb()
    r = archive_lhb_realtime(db, {"date": "2026-11-10", "items": [
        {"stock_id": "603278", "name": "大业股份", "quotas": ["9.9"],
         "ts": 1794289200.0}]})
    assert r["ok"] and r["item_n"] == 1
    loaded = load_lhb_realtime(db, "2026-11-10")
    assert loaded["ok"] and loaded["items"][0]["quotas"] == ["9.9"]


def test_archive_stock_detail_lanes_contract():
    db = _FakeDb()
    r = archive_stock_detail_corpus(db, {"date": "2026-11-10", "items": [
        {"stock_id": "603278", "zt_tur": 100, "buy_tur": 50, "items": [],
         "zt_tur_yuan": 100.0, "buy_tur_yuan": 50.0, "sell_tur_yuan": 0.0,
         "ts": 1794289200.0}]},
        lane="bdo")
    assert r["ok"] and r["lane"] == "bdo"
    loaded = load_stock_detail_corpus(db, "2026-11-10", lane="bdo")
    assert loaded["ok"] and loaded["items"][0]["zt_tur"] == 100
    assert loaded["items"][0]["zt_tur_yuan"] == 100.0, "尾条派生聚合随新日档落库"
    # 旧日档（无派生字段）向后兼容可读，raw 合同不变
    archive_stock_detail_corpus(db, {"date": "2026-11-09", "items": [
        {"stock_id": "603278", "zt_tur": 77237472, "buy_tur": 407660096,
         "items": [{"time": 941, "zt_tur": 77237472}], "ts": 1794202800.0}]},
        lane="bdo")
    legacy = load_stock_detail_corpus(db, "2026-11-09", lane="bdo")
    assert legacy["ok"]
    assert "zt_tur_yuan" not in legacy["items"][0], "旧档无派生字段，不伪造"
    assert legacy["items"][0]["zt_tur"] == 77237472
    # rplate plates 列表原样
    archive_stock_detail_corpus(db, {"date": "2026-11-10", "items": [
        {"stock_id": "603278", "plates": [{"plate_name": "人形机器人"}],
         "ts": 1794289200.0}]}, lane="rplate")
    loaded = load_stock_detail_corpus(db, "2026-11-10", lane="rplate")
    assert loaded["ok"] and loaded["items"][0]["plates"][0]["plate_name"] == "人形机器人"


# ── 监管风险 lane（2026-11-15 预登记 theme-leader-regulatory-risk）──────────
# 日槽 17:00 门控 / 每日一次 / 预算护栏 / 日期错配 / 开关 / 与它 lane 隔离。

class _RegColl(_FakeCollection):
    def find_one(self, q, projection=None, sort=None):
        return super().find_one(q, sort=sort)

    def update_one(self, q, update, upsert=False):
        super().update_one(q, update, upsert=upsert)
        for key, delta in (update.get("$inc") or {}).items():
            row = self.rows[q["_id"]]
            cur = row
            parts = key.split(".")
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = int(cur.get(parts[-1]) or 0) + int(delta)


class _RegDb:
    def __init__(self):
        self.pool = _RegColl()
        self.calls = _RegColl()

    def __getitem__(self, name):
        return {"kpl_daban_pool": self.pool, "kpl_api_calls": self.calls}[name]


def _reg_payload(date="2026-11-13"):
    return {"date": date, "calls": 5,
            "groups": {"today": [], "tomorrow": [], "recent": [],
                       "monitor_current": [], "monitor_history": []},
            "by_code": {"600327": {"today": {"stock_id": "600327"}}},
            "states": {"severe": {"ok": True}}}


class _AllFailClient:
    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        raise OSError("conn refused")


def _reg_archiver(db, clock, fetcher=None, monkeypatch=None):
    from backend.services import kpl_daban_archiver as arch

    class _S:
        storage_backend = "mongodb"
    if monkeypatch is not None:
        monkeypatch.setattr(arch.httpx, "AsyncClient", _AllFailClient)
        _patch_trading_calendar(monkeypatch)
    return arch.DabanPoolArchiver(
        settings=_S(), database_factory=lambda: db, interval_seconds=60,
        gene_fetcher=_fake_gene, clock=clock,
        regulatory_fetcher=fetcher or (lambda: _reg_payload()))


def test_regulatory_lane_daily_slot_and_idempotent(monkeypatch):
    import asyncio
    db = _RegDb()
    clock = lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI)  # 周五 17:00 槽后
    archiver = _reg_archiver(db, clock, monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]
    # 它 lane 全失败不连带 regulatory（隔离）
    assert res["pool"]["ok"] is False
    assert res["regulatory"]["ok"] is True and res["regulatory"]["date"] == "2026-11-13"
    assert db.pool.rows["2026-11-13"]["reg_date"] == "2026-11-13"
    assert db.calls.rows["2026-11-13"]["calls"]["regulatory"] == 5
    # 第二轮：每日一次，不重复采不重复计数
    asyncio.run(archiver._archive_once())
    res2 = archiver.status()["lastResult"]
    assert res2["regulatory"]["note"] == "already_archived"
    assert db.calls.rows["2026-11-13"]["calls"]["regulatory"] == 5


def test_regulatory_lane_waiting_slot_and_non_trading_day(monkeypatch):
    import asyncio
    db = _RegDb()
    a1 = _reg_archiver(db, lambda: datetime(2026, 11, 13, 10, 0, tzinfo=TZ_SHANGHAI),
                       monkeypatch=monkeypatch)
    asyncio.run(a1._archive_once())
    assert a1.status()["lastResult"]["regulatory"]["note"] == "waiting_slot"
    # 槽前边界 16:59 仍不采（2026-11-15 裁决 15:10→17:00）
    a1b = _reg_archiver(db, lambda: datetime(2026, 11, 13, 16, 59, tzinfo=TZ_SHANGHAI),
                        monkeypatch=monkeypatch)
    asyncio.run(a1b._archive_once())
    assert a1b.status()["lastResult"]["regulatory"]["note"] == "waiting_slot"
    a2 = _reg_archiver(db, lambda: datetime(2026, 11, 15, 17, 20, tzinfo=TZ_SHANGHAI),
                       monkeypatch=monkeypatch)  # 周日
    asyncio.run(a2._archive_once())
    assert a2.status()["lastResult"]["regulatory"]["note"] == "waiting_slot"
    assert "2026-11-13" not in db.pool.rows


def test_regulatory_budget_exhausted(monkeypatch):
    import asyncio
    db = _RegDb()
    db.calls.rows["2026-11-13"] = {"_id": "2026-11-13", "calls": {"regulatory": 10}}
    archiver = _reg_archiver(db, lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI),
                             monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["regulatory"]
    assert res["ok"] is False and res["reason"] == "budget_exhausted"
    assert "reg_date" not in db.pool.rows.get("2026-11-13", {})


def test_regulatory_date_mismatch_not_written(monkeypatch):
    import asyncio
    db = _RegDb()
    archiver = _reg_archiver(db, lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI),
                             fetcher=lambda: _reg_payload("2026-11-12"),
                             monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["regulatory"]
    assert res["ok"] is False and res["reason"] == "date_mismatch"
    assert "reg_date" not in db.pool.rows.get("2026-11-13", {})


def test_regulatory_disabled_env(monkeypatch):
    import asyncio
    monkeypatch.setenv("KPL_REGULATORY_ENABLED", "0")
    db = _RegDb()
    archiver = _reg_archiver(db, lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI),
                             monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    assert archiver.status()["lastResult"]["regulatory"]["note"] == "disabled"


def test_regulatory_budget_reserve_gate(monkeypatch):
    """review m2：used=6 时 6+5>10 → 发弹前 skip（fetcher 不得被调）。"""
    import asyncio
    db = _RegDb()
    db.calls.rows["2026-11-13"] = {"_id": "2026-11-13", "calls": {"regulatory": 6}}

    def _boom():
        raise AssertionError("budget reserved gate must skip before fetch")

    archiver = _reg_archiver(db, lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI),
                             fetcher=_boom, monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["regulatory"]
    assert res["ok"] is False and res["reason"] == "budget_exhausted"
    assert "reg_date" not in db.pool.rows.get("2026-11-13", {})


def test_regulatory_lane_partial_endpoint_failure_still_writes(monkeypatch):
    """m5：lane 级部分端点失败仍落库 + reg_states 留痕（§4.0）。"""
    import asyncio
    db = _RegDb()
    payload = _reg_payload()
    payload["states"]["severe"] = {"ok": False, "reason": "errcode:1002"}
    payload["states"]["monitor_current"] = {"ok": True}
    payload["groups"]["today"] = None
    payload["groups"]["tomorrow"] = None
    payload["groups"]["monitor_current"] = [{"stock_id": "600825"}]
    payload["by_code"]["600825"] = {"monitor_current": {"stock_id": "600825"}}
    archiver = _reg_archiver(db, lambda: datetime(2026, 11, 13, 17, 20, tzinfo=TZ_SHANGHAI),
                             fetcher=lambda: payload, monkeypatch=monkeypatch)
    asyncio.run(archiver._archive_once())
    res = archiver.status()["lastResult"]["regulatory"]
    assert res["ok"] is True
    row = db.pool.rows["2026-11-13"]
    assert row["reg_states"]["severe"]["ok"] is False
    assert row["reg_groups"]["today"] is None      # 缺失≠真零
    assert row["reg_groups"]["monitor_current"]   # 成功组照落
