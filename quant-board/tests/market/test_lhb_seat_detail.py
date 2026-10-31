"""龙虎榜个股席位明细（东财 datacenter-web）服务与路由测试。

全部 mock httpx 客户端，禁止真实上游调用；数据样例取自 2026-10-30 人工开火探针
（000788 @ 2022-03-15，合同详见 backend/market_proxy/lhb_seat_detail.py 模块注释）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.lhb_seat_detail import (
    LhbSeatParamError,
    LhbSeatUpstreamError,
    LhbSeatDetailService,
    aggregate_by_stock,
    match_branch_rows,
    normalize_branch_name,
    normalize_lhb_code,
    normalize_lhb_date,
    parse_seat_rows,
    parse_stock_dates,
)


# ---------- 参数归一 ----------

def test_normalize_code_strips_prefix_and_rejects_garbage():
    assert normalize_lhb_code("sh000788") == "000788"
    assert normalize_lhb_code("600667") == "600667"
    with pytest.raises(LhbSeatParamError):
        normalize_lhb_code("abc123")
    with pytest.raises(LhbSeatParamError):
        normalize_lhb_code("")
    assert normalize_lhb_date("2022-03-15") == "2022-03-15"
    with pytest.raises(LhbSeatParamError):
        normalize_lhb_date("20220315")


# ---------- 解析层 ----------

def test_parse_seat_rows_sorts_and_normalizes_ratio():
    items = [
        {"OPERATEDEPT_NAME": "B 营业部", "BUY": 100.0, "SELL": 40.0, "NET": 60.0,
         "TOTAL_BUYRIO": 0.0257, "EXPLANATION": "日涨幅偏离值达7%", "TRADE_ID": "4320943"},
        {"OPERATEDEPT_NAME": "A 营业部", "BUY": 3346.4, "SELL": None, "NET": None,
         "TOTAL_BUYRIO": 0.0257},
        "garbage-row",
    ]
    rows = parse_seat_rows(items, "buy")
    assert rows[0]["rank"] == 1
    assert rows[0]["name"] == "A 营业部"
    assert rows[0]["buy_ratio"] == 2.57
    # NET 缺失时派生 = BUY-SELL（SELL 缺失不派生，保持 None）
    assert rows[0]["net"] is None
    assert rows[1]["net"] == 60.0
    assert rows[1]["rank"] == 2
    assert len(rows) == 2
    # sell 榜按 SELL 排序
    sell_rows = parse_seat_rows(
        [{"OPERATEDEPT_NAME": "S1", "BUY": 1.0, "SELL": 9.0},
         {"OPERATEDEPT_NAME": "S2", "BUY": 2.0, "SELL": 5.0}], "sell")
    assert [r["name"] for r in sell_rows] == ["S1", "S2"]


def test_parse_seat_rows_dedupes_seat_across_trade_ids():
    # 同股同日多上榜原因：同一席位在不同 TRADE_ID 下重复返回（000788 人工探针实样）
    items = [
        {"OPERATEDEPT_NAME": "东财宁波", "BUY": 100, "SELL": 0, "TRADE_ID": "t1"},
        {"OPERATEDEPT_NAME": "东财宁波", "BUY": 100, "SELL": 0, "TRADE_ID": "t2"},
        {"OPERATEDEPT_NAME": "东亚前海", "BUY": 90, "SELL": 5, "TRADE_ID": "t2"},
    ]
    rows = parse_seat_rows(items, "buy")
    assert [r["name"] for r in rows] == ["东财宁波", "东亚前海"]
    assert [r["rank"] for r in rows] == [1, 2]


def test_parse_stock_dates_dedupes_desc_and_drops_bad_rows():
    out = parse_stock_dates(
        [{"SECURITY_NAME_ABBR": "Tester", "TRADE_DATE": "2022-03-15 00:00:00"},
         {"TRADE_DATE": "2024-01-05 00:00:00"},
         {"TRADE_DATE": "bad"},
         "x"],
        "000788",
    )
    assert out == {"code": "000788", "name": "Tester",
                   "dates": ["2024-01-05", "2022-03-15"], "dropped": 2}


# ---------- 服务层（mock httpx 客户端） ----------

class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def get(self, url, params=None):
        self.calls.append(params or {})
        return _FakeResp(self.payloads.pop(0))

    async def aclose(self) -> None:
        return None


def _detail_payload(rows: list[dict]) -> dict:
    return {"version": "v", "success": True,
            "result": {"pages": 1, "data": rows}}


@pytest.mark.asyncio
async def test_seat_detail_merges_buy_and_sell_sorted():
    client = _FakeClient([
        _detail_payload([{"OPERATEDEPT_NAME": "A", "BUY": 33464121, "SELL": 0, "NET": 33464121,
                          "TOTAL_BUYRIO": 0.025736148353, "EXPLANATION": "日涨幅偏离值达到7%的前5只证券",
                          "TRADE_ID": "4320943"}]),
        _detail_payload([{"OPERATEDEPT_NAME": "S1", "BUY": 0, "SELL": 29691600, "NET": -29691600,
                          "TOTAL_SELLRIO": 0.0228}]),
    ])
    svc = LhbSeatDetailService(client=client)
    out = await svc.get_seat_detail("000788", "2022-03-15")
    assert out["ok"] is True and out["code"] == "000788" and out["date"] == "2022-03-15"
    assert out["buy"][0]["name"] == "A"
    assert out["buy"][0]["buy_ratio"] == 2.57
    assert out["sell"][0]["sell"] == 29691600.0
    # 两次调用同 key：命中 TTL 缓存，上游只被请求 2 次（买/卖各一）
    await svc.get_seat_detail("000788", "2022-03-15")
    assert len(client.calls) == 2
    # 合同参数：source/client/WEB 必带
    assert client.calls[0]["source"] == "WEB" and client.calls[0]["client"] == "WEB"


@pytest.mark.asyncio
async def test_seat_detail_upstream_failure_raises_structured():
    client = _FakeClient([{"success": False, "message": "返回数据为空", "code": "9201"}])
    svc = LhbSeatDetailService(client=client)
    with pytest.raises(LhbSeatUpstreamError):
        await svc.get_seat_detail("000788", "2022-03-15")


@pytest.mark.asyncio
async def test_seat_dates_ok_and_cache():
    client = _FakeClient([
        {"success": True, "result": {"data": [
            {"SECURITY_NAME_ABBR": "Tester", "SECURITY_CODE": "000788",
             "TRADE_DATE": "2022-03-15 00:00:00"}]}}
    ])
    svc = LhbSeatDetailService(client=client)
    out = await svc.get_seat_dates("000788")
    assert out["dates"] == ["2022-03-15"] and out["name"] == "Tester"
    await svc.get_seat_dates("000788")
    assert len(client.calls) == 1


# ---------- 全日聚合 / 营业部匹配 ----------

def test_normalize_branch_name_and_match():
    assert normalize_branch_name("华泰证券股份有限公司总部") == normalize_branch_name("华泰证券总部")
    rows = [
        {"code": "600519", "name": "华泰证券股份有限公司总部", "buy": 100.0, "sell": 0.0, "net": 100.0},
        {"code": "600519", "name": "中信证券股份有限公司上海分公司", "buy": 50.0, "sell": 30.0, "net": 20.0},
    ]
    matched, hit, cand = match_branch_rows(rows, "华泰证券总部")
    assert matched == "华泰证券股份有限公司总部" and len(hit) == 1 and cand == []
    matched2, _, cand2 = match_branch_rows(rows, "完全不存在的营业部XYZ")
    assert matched2 is None and len(cand2) > 0


def test_aggregate_by_stock_sums_per_code():
    rows = [
        {"code": "600519", "name": "A", "buy": 100.0, "sell": None, "net": 100.0},
        {"code": "600519", "name": "B", "buy": 10.0, "sell": 5.0, "net": 5.0},
        {"code": None, "name": "C", "buy": 9.0, "sell": None, "net": None},
    ]
    out = aggregate_by_stock(rows)
    assert out == [{"code": "600519", "buy": 110.0, "sell": 5.0, "net": 105.0}]


@pytest.mark.asyncio
async def test_day_seats_and_branch_lookup():
    def _day_rows():
        return [
            {"SECURITY_CODE": "600519", "OPERATEDEPT_NAME": "华泰证券股份有限公司总部",
             "BUY": 100.0, "SELL": 0.0, "NET": 100.0, "TRADE_ID": "t1"},
            {"SECURITY_CODE": "000788", "OPERATEDEPT_NAME": "中信证券股份有限公司上海分公司",
             "BUY": 50.0, "SELL": 0.0, "NET": 50.0, "TRADE_ID": "t2"},
        ]
    client = _FakeClient([
        _detail_payload(_day_rows()),   # day: buy
        _detail_payload([]),            # day: sell
        _detail_payload([               # day: 上榜名单（供证券名称/行情/原因）
            {"SECURITY_CODE": "600519", "SECURITY_NAME_ABBR": "贵州茅台",
             "CLOSE_PRICE": "1411.0", "CHANGE_RATE": "1.23", "TURNOVERRATE": "0.55",
             "EXPLANATION": "日振幅值达15%的证券"},
            {"SECURITY_CODE": "000788", "SECURITY_NAME_ABBR": "北大荒"},
        ]),
    ])
    svc = LhbSeatDetailService(client=client)
    day = await svc.get_day_seats("2026-10-30")
    assert day["ok"] is True
    assert {s["code"]: s["buy"] for s in day["stocks"]} == {"600519": 100.0, "000788": 50.0}
    assert day["names"] == {"600519": "贵州茅台", "000788": "北大荒"}
    # day_quotes（2026-10-30 左列表字段补全）：行情/原因原样字符串，缺字段不键入
    assert day["day_quotes"] == {"600519": {"price": "1411.0", "zf": "1.23",
                                            "tur": "0.55", "reason": "日振幅值达15%的证券"}}
    assert day["stocks"][0]["name"] == "贵州茅台"
    assert set(day["branches"]) == {"华泰证券股份有限公司总部", "中信证券股份有限公司上海分公司"}
    # 回归（2026-10-30 线上「query too long」）：filter 必须是短日期串，不得混入 dict 序列化；
    # 且不得携带冗余 url= 参数
    for call in client.calls:
        assert call["filter"] == "(TRADE_DATE='2026-10-30')"
        assert "url" not in call
    # 营业部反查吃同帧 dayrows 缓存：不再打上游（此前双拉导致每点击重试）
    br = await svc.get_branch_seats("2026-10-30", "华泰证券总部")
    assert len(client.calls) == 3
    assert br["matched"] == "华泰证券股份有限公司总部"
    assert br["buy"][0]["code"] == "600519" and br["buy"][0]["buy"] == 100.0
    assert br["buy"][0]["name"] == "贵州茅台"   # 反查行带证券名称（2026-10-30 用户反馈：有代码没名称）
    assert br["sell"] == []
    # 命中日期缓存：同日再取不再打上游
    await svc.get_day_seats("2026-10-30")
    assert len(client.calls) == 3
    await svc.get_branch_seats("2026-10-30", "中信证券上海分公司")
    assert len(client.calls) == 3
    with pytest.raises(LhbSeatParamError):
        await svc.get_branch_seats("2026-10-30", " ")


# ---------- 路由层 ----------

@pytest.mark.asyncio
async def test_routes_contract(monkeypatch: pytest.MonkeyPatch):
    class _StubSvc:
        async def get_seat_detail(self, code, date):
            if code == "bad":
                raise LhbSeatParamError("code 非法")
            if code == "boom":
                raise LhbSeatUpstreamError("上游挂了")
            return {"ok": True, "code": code, "date": date, "buy": [], "sell": []}

        async def get_seat_dates(self, code):
            if code == "boom":
                raise LhbSeatUpstreamError("上游挂了")
            return {"code": code, "name": "T", "dates": ["2022-03-15"], "dropped": 0}

        async def get_day_seats(self, date):
            if date == "bad-day":
                raise LhbSeatParamError("date 非法")
            if date == "boom":
                raise LhbSeatUpstreamError("上游挂了")
            if date == "2026-10-28":   # 仅供回退测试：10-29/10-30 空，10-28 有数据
                return {"ok": True, "date": date, "stocks": [{"code": "600519"}],
                        "branches": ["华泰证券股份有限公司总部"]}
            return {"ok": True, "date": date, "stocks": [], "branches": []}

        async def get_branch_seats(self, date, name):
            if not name:
                raise LhbSeatParamError("branch 营业部名称不能为空")
            if date == "boom":
                raise LhbSeatUpstreamError("上游挂了")
            return {"ok": True, "date": date, "name": name, "matched": name,
                    "candidates": [], "buy": [], "sell": []}

    monkeypatch.setattr(market_data_routes, "get_lhb_seat_service", lambda: _StubSvc())
    app = FastAPI()
    app.include_router(market_data_routes.router)
    c = TestClient(app)

    ok = c.get("/api/market/lhb-seat-detail", params={"code": "000788", "date": "2022-03-15"})
    assert ok.status_code == 200 and ok.json()["buy"] == []
    bad = c.get("/api/market/lhb-seat-detail", params={"code": "bad", "date": "2022-03-15"})
    assert bad.status_code == 422
    degraded = c.get("/api/market/lhb-seat-detail", params={"code": "boom", "date": "2022-03-15"})
    assert degraded.status_code == 200 and degraded.json()["degraded"] is True
    dates = c.get("/api/market/lhb-seat-dates", params={"code": "000788"})
    assert dates.status_code == 200 and dates.json()["dates"] == ["2022-03-15"]
    day = c.get("/api/market/lhb-day-detail", params={"date": "2020-01-01"})
    assert day.status_code == 200 and day.json()["stocks"] == []
    assert "未回退" in day.json()["note"]          # 回看 10 日均空：显式注明不伪装
    fb = c.get("/api/market/lhb-day-detail", params={"date": "2026-10-30"})
    assert fb.status_code == 200 and fb.json()["effective_date"] == "2026-10-28"
    assert fb.json()["requested_date"] == "2026-10-30"
    assert "已回退" in fb.json()["note"]           # 当日无数据回退显式标注（2026-10-30 用户裁决）
    assert fb.json()["stocks"] == [{"code": "600519"}]
    day_bad = c.get("/api/market/lhb-day-detail", params={"date": "bad-day"})
    assert day_bad.status_code == 422
    day_boom = c.get("/api/market/lhb-day-detail", params={"date": "boom"})
    assert day_boom.status_code == 200 and day_boom.json()["degraded"] is True
    br = c.get("/api/market/lhb-branch-detail", params={"date": "2026-10-30", "name": "华泰"})
    assert br.status_code == 200 and br.json()["matched"] == "华泰"
    br_miss = c.get("/api/market/lhb-branch-detail", params={"date": "2026-10-30"})
    assert br_miss.status_code == 422
