# -*- coding: utf-8 -*-
"""jiuyan_board_info 单测：触板二分（方案A）+ 漏标连板口径 + meta 降级旗标。

2026-10-11 用户裁决方案A：韭研触板名单经 THS 15:00 炸板池二分——
- zhaban=True：在今日炸板池 → 非涨停股（断板/触板未封）；
- excluded：'st'|'bse'（官方简图不计涨停家数）；
- boardUnmarked：num 空 且 昨日在「昨日涨停池」（昨日触板-昨日炸板）——
  昨日炸板股今日涨停=首板不得误标（10-09 金健米业/东亚药业误标教训）；
- 任一池缺失 → meta 旗标降级，宁漏标不误标。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan import dragon_rows, jiuyan_board_dragons, jiuyan_board_info


class FinalCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, projection=None):
        for d in self.docs:
            if d.get("_id") == query.get("_id"):
                return d
        return None


class FramesCol:
    """snapshot_frames 替身：find=trading_dates_before 交易日轴；find_one=15:00 池帧。"""

    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        lt = (query.get("tradingDate") or {}).get("$lt")
        return [dict(r) for r in self.rows if lt is None or str(r.get("tradingDate")) < lt]

    def find_one(self, query, projection=None, sort=None):
        want_date = query.get("tradingDate")
        want_slot = query.get("slotTime")
        for r in self.rows:
            if (want_date is None or r.get("tradingDate") == want_date) and \
               (want_slot is None or r.get("slotTime") == want_slot):
                return dict(r)
        return None


class MultiFakeDb:
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, name):
        return self._cols[name]


def _pool_frame(date, failed_codes, ok=True, degraded=False, failed_items=None):
    items = failed_items if failed_items is not None else [{"code": c} for c in failed_codes]
    return {"tradingDate": date, "slotTime": "15:00", "type": "half_hour", "datasetId": "dragonboard_live",
            "limitSummary": {"thsPools": {"ok": ok, "degraded": degraded, "date": date.replace("-", ""),
                                          "pools": {"failed": {"key": "failed", "total": len(items),
                                                               "items": items}}}}}


def _final(date, stocks_by_field):
    """stocks_by_field: [(板块名, [stock dict])]"""
    return {"_id": f"{date}:final",
            "fields": [{"name": name, "stocks": sts} for name, sts in stocks_by_field]}


def _std_cols(today_stocks, prev_codes, today_failed=(), prev_failed=(), frames=True):
    cols = {
        "jiuyan_action": FinalCol([
            _final("2026-10-09", [("大农业", today_stocks)]),
            _final("2026-10-08", [("X", [{"code": c, "num": None} for c in prev_codes])]),
        ]),
    }
    if frames:
        cols["snapshot_frames"] = FramesCol([
            _pool_frame("2026-10-09", list(today_failed)),
            _pool_frame("2026-10-08", list(prev_failed)),
        ])
    else:
        cols["snapshot_frames"] = FramesCol([])
    return MultiFakeDb(cols)


def test_board_info_bisect_and_unmarked():
    """二分主路径：昨日炸板股今日涨停=首板不标；昨日涨停今日num空=漏标；炸板/ST/北交所标记。"""
    today = [
        {"code": "600001", "name": "昨炸今停", "num": None, "time": "10:00:00"},   # 昨日在池+昨日炸板 → 首板
        {"code": "600002", "name": "真漏标", "num": None, "time": "10:05:00"},     # 昨日在池+昨日封板 → 漏标
        {"code": "600003", "name": "正常连板", "num": "2天2板", "time": "09:31:00"},
        {"code": "600004", "name": "今日炸板", "num": None, "time": "13:00:00"},   # 今日炸板池 → zhaban
        {"code": "600005", "name": "ST某某", "num": None, "time": "14:00:00"},     # excluded=st
        {"code": "920001", "name": "北交某", "num": None, "time": "14:30:00"},     # excluded=bse
    ]
    info, meta = jiuyan_board_info(
        _std_cols(today, prev_codes=["600001", "600002", "600003"],
                  today_failed=["600004"], prev_failed=["600001"]), "2026-10-09")
    assert meta == {"jiuyanFinalFound": True, "prevPoolFound": True,
                    "thsPoolFound": True, "prevThsPoolFound": True, "thsZhabanTotal": 1}
    assert "boardUnmarked" not in info["600001"]  # 昨日炸板股今日涨停=首板，不误标
    assert info["600002"]["boardUnmarked"] is True  # 昨日封板今日 num 空 → 真漏标
    assert info["600003"]["boards"] == 2 and "boardUnmarked" not in info["600003"]
    assert info["600004"]["zhaban"] is True
    assert info["600005"]["excluded"] == "st"
    assert info["920001"]["excluded"] == "bse"
    assert "zhaban" not in info["600002"]  # 漏标股是真涨停股，非炸板


def test_board_info_opennum_passthrough():
    """炸板卡数据：open_num→openNum 透传（炸板卡「反复开板」消费），None/缺失不透传；meta 带池总数。"""
    today = [
        {"code": "600004", "name": "多次开板", "num": None, "time": "13:00:00"},
        {"code": "600006", "name": "无开板次数字段", "num": None, "time": "13:30:00"},
    ]
    cols = {
        "jiuyan_action": FinalCol([
            _final("2026-10-09", [("大农业", today)]),
            _final("2026-10-08", [("X", [{"code": "600004", "num": None}])]),
        ]),
        "snapshot_frames": FramesCol([
            _pool_frame("2026-10-09", [], failed_items=[{"code": "600004", "open_num": 3}, {"code": "600006"}]),
            _pool_frame("2026-10-08", ["600004"]),
        ]),
    }
    info, meta = jiuyan_board_info(cols, "2026-10-09")
    assert info["600004"]["zhaban"] is True and info["600004"]["openNum"] == 3
    assert info["600006"]["zhaban"] is True and "openNum" not in info["600006"]
    assert meta["thsZhabanTotal"] == 2  # 含韭研未收录股（榜外差额注记用）


def test_board_info_ths_pool_missing_degrades():
    """今日+昨日帧全缺失 → 二分不可用：不标 zhaban/boardUnmarked，meta 显式降级。"""
    today = [{"code": "600001", "name": "X", "num": None, "time": "10:00:00"}]
    info, meta = jiuyan_board_info(_std_cols(today, prev_codes=["600001"], frames=False), "2026-10-09")
    assert meta["thsPoolFound"] is False and meta["prevPoolFound"] is False
    assert meta["prevThsPoolFound"] is None  # 无昨日轴=不适用
    assert "zhaban" not in info["600001"] and "boardUnmarked" not in info["600001"]


def test_board_info_prev_ths_missing_keeps_today_bisect():
    """仅昨日炸板池缺失（昨日轴无 15:00 帧）：今日二分可用（zhaban 照标），漏标判定降级（宁漏标不误标）。"""
    today = [
        {"code": "600001", "name": "X", "num": None, "time": "10:00:00"},
        {"code": "600004", "name": "Y", "num": None, "time": "13:00:00"},
    ]
    cols = {
        "jiuyan_action": FinalCol([
            _final("2026-10-09", [("大农业", today)]),
            _final("2026-10-08", [("X", [{"code": "600001", "num": None}])]),
        ]),
        "snapshot_frames": FramesCol([_pool_frame("2026-10-09", ["600004"]),
                                      {"tradingDate": "2026-10-08", "slotTime": "09:30",
                                       "type": "half_hour", "datasetId": "dragonboard_live"}]),
    }
    info, meta = jiuyan_board_info(cols, "2026-10-09")
    assert meta["thsPoolFound"] is True and meta["prevThsPoolFound"] is False
    assert info["600004"]["zhaban"] is True
    assert "boardUnmarked" not in info["600001"]  # prev_sealed 不可信 → 不标


def test_board_info_final_missing():
    cols = {"jiuyan_action": FinalCol([]),
            "snapshot_frames": FramesCol([_pool_frame("2026-10-08", [])])}
    info, meta = jiuyan_board_info(cols, "2026-10-09")
    assert info == {} and meta["jiuyanFinalFound"] is False


def test_board_info_dedup_first_field_wins():
    """同 code 出现在多个板块取首现（与 join 展示口径一致）。"""
    cols = {
        "jiuyan_action": FinalCol([
            _final("2026-10-09", [
                ("首现板块", [{"code": "600825", "num": "2天2板"}]),
                ("后续板块", [{"code": "600825", "num": "3天3板"}]),
            ]),
            _final("2026-10-08", [("X", [{"code": "600825"}])]),
        ]),
        "snapshot_frames": FramesCol([_pool_frame("2026-10-09", []), _pool_frame("2026-10-08", [])]),
    }
    info, meta = jiuyan_board_info(cols, "2026-10-09")
    assert info["600825"]["boards"] == 2 and info["600825"]["boardName"] == "首现板块"


# ── 板块领涨（2026-10-12 用户需求）：dragon_rows 龙序 + jiuyan_board_dragons 分组 + 路由挂载 ──


def test_dragon_rows_ordering():
    """龙序=板数降序→封板时间升序；「N天M板」取 M；num 缺失=首板垫底；time 缺失垫底且输出 None。"""
    stocks = [
        {"code": "A", "name": "三板", "num": "3天3板", "time": "10:00:00"},
        {"code": "B", "name": "二板晚", "num": "2天2板", "time": "11:00:00"},
        {"code": "C", "name": "二板早", "num": "5天2板", "time": "09:35:00"},  # 跨度天数≠板数：5天2板=2板
    ]
    rows = dragon_rows(stocks)
    assert [r["name"] for r in rows] == ["三板", "二板早", "二板晚"]
    assert rows[1]["boards"] == 2 and rows[1]["time"] == "09:35"  # time 截 HH:MM
    assert [r["role"] for r in rows] == ["龙一", "龙二", "龙三"]
    tail = dragon_rows([
        {"code": "D", "name": "首板无time", "num": None, "time": None},
        {"code": "E", "name": "首板晚", "num": None, "time": "14:00:00"},
        {"code": "F", "name": "首板早", "num": None, "time": "09:30:00"},
    ])
    assert [r["name"] for r in tail] == ["首板早", "首板晚", "首板无time"]
    assert tail[2]["boards"] is None and tail[2]["time"] is None


def test_dragon_rows_top_truncation():
    stocks = [{"code": str(i), "name": f"股{i}", "num": None, "time": f"09:{i:02d}"} for i in range(5)]
    assert len(dragon_rows(stocks)) == 3
    assert len(dragon_rows(stocks, top=1)) == 1


def test_board_dragons_grouped_and_final_missing():
    cols = {"jiuyan_action": FinalCol([
        _final("2026-10-09", [
            ("AI影视", [{"code": "A", "name": "龙一甲", "num": "3天3板", "time": "09:25:00"},
                        {"code": "B", "name": "龙二乙", "num": "3天3板", "time": "09:30:00"}]),
            ("其他", [{"code": "C", "name": "独苗", "num": None, "time": "09:47:00"}]),
        ]),
        _final("2026-10-08", [("X", [])]),
    ])}
    got = jiuyan_board_dragons(MultiFakeDb(cols), "2026-10-09")
    assert [d["name"] for d in got["AI影视"]] == ["龙一甲", "龙二乙"]
    assert [d["name"] for d in got["其他"]] == ["独苗"]
    cols2 = {"jiuyan_action": FinalCol([_final("2026-10-08", [("X", [])])])}
    assert jiuyan_board_dragons(MultiFakeDb(cols2), "2026-10-09") == {}  # final 缺失 → {}（fail-visible）


class _LabelsCol:
    """hotlist_jev_driver_labels 替身：find_one 按 _id（PHASE 哨兵）、find 按 tradingDate+origin 排除。"""

    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, projection=None):
        for d in self.docs:
            if d.get("_id") == query.get("_id"):
                return dict(d)
        return None

    def find(self, query, projection=None):
        excluded = (query.get("origin") or {}).get("$ne")
        return [dict(d) for d in self.docs
                if d.get("tradingDate") == query.get("tradingDate")
                and d.get("origin") != excluded]


def test_limitup_route_attaches_board_dragons(monkeypatch):
    """路由把 boardDragons 按板块挂到每行；韭研 final 外的板块 → 空数组（前端显示 '-'）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api import hotlist_jev_limitup_routes as limitup_module
    from backend.data.repositories import repository_factory

    labels = [
        {"_id": "2026-10-09:600001", "tradingDate": "2026-10-09", "status": "ok",
         "origin": "driver_label_jiuyan_v3_pilot", "code": "600001", "name": "龙一甲",
         "label": "ma_restructure", "jiuyanContext": {"board": "AI影视"}},
        {"_id": "2026-10-09:600009", "tradingDate": "2026-10-09", "status": "ok",
         "origin": "driver_label_jiuyan_v3_pilot", "code": "600009", "name": "域外股",
         "label": "ma_restructure", "jiuyanContext": {"board": "不存在板块"}},
    ]
    db = MultiFakeDb({
        "hotlist_jev_driver_labels": _LabelsCol(labels),
        "jiuyan_action": FinalCol([
            _final("2026-10-09", [("AI影视", [
                {"code": "600001", "name": "龙一甲", "num": "3天3板", "time": "09:25:00"},
                {"code": "600002", "name": "龙二乙", "num": "3天3板", "time": "09:30:00"}])]),
            _final("2026-10-08", [("X", [{"code": "600001", "num": "2天2板"}])]),
        ]),
        "snapshot_frames": FramesCol([_pool_frame("2026-10-09", []), _pool_frame("2026-10-08", [])]),
    })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    app = FastAPI()
    app.include_router(limitup_module.router)
    resp = TestClient(app).get("/api/hotlist-jev/limitup-labels", params={"date": "2026-10-09"})
    assert resp.status_code == 200
    body = resp.json()
    by_code = {s["code"]: s for s in body["stocks"]}
    dragons = by_code["600001"]["boardDragons"]
    assert [d["name"] for d in dragons] == ["龙一甲", "龙二乙"]
    assert dragons[0]["role"] == "龙一" and dragons[0]["boards"] == 3
    assert by_code["600009"]["boardDragons"] == []
