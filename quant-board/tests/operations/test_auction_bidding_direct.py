# -*- coding: utf-8 -*-
"""竞价列表真源头直采器（MorningBiddingList @ kaipanla.com）测试——纯假库/假 POST。

合同锁定（2026-11-16 雷电模拟器 mitmproxy 实抓 + st=100 重放验证）：
1. POST form a=MorningBiddingList&c=HomeDingPan&Type=4&PidType=0&Order=1&st=N&Index=M；
2. 17 列统一数组位 → 具名字段映射，未破译列保 colN 原名不猜，raw 全行保留；
3. 翻页 Index 按页长偏移，rows < st 即末页，≤MAX_PAGES；
4. 持久化 _id=日期、rows 键=code6、source=kpl_direct_morning_bidding。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_bidding_direct as M


class FakeMblDb:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def __getitem__(self, name):
        return self

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find_one(self, q):
        return self.docs.get(q["_id"])


def _row(code: str, extra: float = 1.0) -> list:
    return [code, "测试股", 10.0 + extra, 5.0, 1000000.0 * extra, 10, 500000.0, 0.5,
            2000000.0, 800000.0, 2000000.0, "测试板块", 1e9, -50000.0, 900000.0,
            -40000.0, "首板"]


def test_parse_mbl_rows_named_and_raw():
    rows = M.parse_mbl_rows([_row("000831")])
    r = rows["000831"]
    assert r["name"] == "测试股" and r["zt_buy_amount"] == 1000000.0
    assert r["plate"] == "测试板块" and r["state"] == "首板"
    assert r["col9"] == 800000.0, "未破译列保原名不猜"
    assert r["raw"][0] == "000831", "raw 全行保留"
    assert len(r["raw"]) == 17
    # 缺列如实缺（短行）
    rows2 = M.parse_mbl_rows([["600715", "短行"]])
    assert rows2["600715"]["name"] == "短行" and rows2["600715"]["plate"] is None


def test_parse_mbl_rows_skips_bad():
    rows = M.parse_mbl_rows([None, [], ["", "空码"], _row("000831")])
    assert set(rows.keys()) == {"000831"}


def test_fetch_pagination_until_short_page(monkeypatch):
    calls = []

    def fake_post(url, params):
        calls.append(params["Index"])
        idx = params["Index"]
        n = 100 if idx == 0 else 14   # 第二页 14 行 < st=100 → 末页
        return {"errcode": "0", "info": [_row(f"60{i:04d}") for i in range(idx, idx + n)],
                "day": "2026-11-17", "time": 1, "status": 1}

    monkeypatch.setattr(M, "_post", fake_post)
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "ok" and res["n_rows"] == 114 and res["pages"] == 2
    assert calls == [0, 100], "Index 按页长偏移"
    assert res["day"] == "2026-11-17"


def test_fetch_http_error_structured(monkeypatch):
    def fake_post(url, params):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_post", fake_post)
    res = M.fetch_morning_bidding_list()
    assert res["state"] == "http_error:RuntimeError" and res["rows"] == {}


def test_persist_and_load_roundtrip():
    db = FakeMblDb()
    res = {"state": "ok", "rows": M.parse_mbl_rows([_row("000831")]),
           "n_rows": 1, "pages": 1, "day": "2026-11-17", "time": 1, "status": 1,
           "attempts": [{"index": 0, "state": "ok"}]}
    p = M.persist_morning_bidding_raw(db, "2026-11-17", res)
    assert p["ok"] is True and p["n_rows"] == 1
    rows = M.load_morning_bidding_raw(db, "2026-11-17")
    assert rows["000831"]["bidding_pct"] == 10
    assert M.load_morning_bidding_raw(db, "2099-01-01") is None


def test_bidding_series_line_rendering():
    from backend.analysis.hotlist.auction_leader_ammo import bidding_series_line
    facts = {"first": {"ts": 1765275305, "bidding_pct": 2.1},
             "max": {"ts": 1765275760, "zt_buy_amount": 3.0e8},
             "last": {"ts": 1765275910, "bidding_pct": 4.2}}
    line = bidding_series_line(facts)
    assert line and line.startswith("竞价过程事实：")
    assert "首帧竞价涨幅 2.10%" in line and "委买额峰值 3.00亿" in line
    assert "观测值口径" not in line and "socket" not in line, "§1.2-8 开发注释禁进行文"
    assert bidding_series_line(None) is None
    assert bidding_series_line({"first": {"ts": 1, "bidding_pct": None}}) is None
