# -*- coding: utf-8 -*-
"""KPL 代理路由 `backend/api/kpl_proxy_routes.py` 合同测试（2026-10-27 加）。

钉住 fail-visible 合同（AGENTS §4.0）：
1. 上游 :8002 正常 → 状态原样透传；
2. 上游不可用 → 结构化 502（ok=False + degraded=True + reason），不得空数据伪装成功；
3. 上游异常 JSON/网络错误 → 同样结构化 502。

测试红线：全部 mock 上游（httpx AsyncClient / websockets），零真实连接。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import kpl_proxy_routes


class _FakeResponse:
    def __init__(self, content, status_code=200):
        self._content = content
        self.status_code = status_code

    def json(self):
        return self._content


class _FakeAsyncClient:
    """上下文管理器风格的假 httpx.AsyncClient（共享客户端契约：is_closed 可查）。"""
    responses = []  # 由测试注入
    fail_with = None
    is_closed = False

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)

    async def post(self, url, json=None, timeout=None):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)


@pytest.fixture()
def client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.fail_with = None
    monkeypatch.setattr(kpl_proxy_routes.httpx, "AsyncClient", _FakeAsyncClient)
    kpl_proxy_routes._SHARED_CLIENT = None  # 共享客户端重建（否则跨测试复用真客户端）
    app = FastAPI()
    app.include_router(kpl_proxy_routes.router)
    return TestClient(app)


def test_status_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "status": "streaming", "sessions": 3})
    ]
    r = client.get("/api/kpl/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "streaming"
    assert body["sessions"] == 3


def test_upstream_unavailable_is_structured_502(client):
    _FakeAsyncClient.fail_with = OSError("connection refused")
    r = client.get("/api/kpl/status")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert "kpl_upstream_unavailable" in body["reason"]


def test_start_stop_post_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "running": True}),
        _FakeResponse({"ok": True, "running": False}),
    ]
    assert client.post("/api/kpl/start").json()["running"] is True
    assert client.post("/api/kpl/stop").json()["running"] is False


def test_subscriptions_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "subscriptions": {"count": 240, "running": True}})
    ]
    r = client.post("/api/kpl/subscriptions", json={"stock_ids": ["801159"]})
    assert r.status_code == 200
    assert r.json()["subscriptions"]["count"] == 240


class TestHistoryReads:
    """历史回看读口（KPL HTTP 三端点）：日期校验 + 服务层结构化错误透出。"""

    def test_missing_date_rejected_400(self, client):
        r = client.get("/api/kpl/sector-ranking")
        assert r.status_code == 400
        assert r.json()["ok"] is False

    def test_malformed_date_rejected_400(self, client):
        assert client.get("/api/kpl/sector-ranking", params={"date": "20261024"}).status_code == 400
        assert client.get(
            "/api/kpl/sector-stocks", params={"plate": "801159", "date": "x"}).status_code == 400

    def test_missing_plate_rejected_400(self, client):
        r = client.get("/api/kpl/sector-stocks", params={"date": "2026-10-24"})
        assert r.status_code == 400
        assert r.json()["reason"] == "missing_plate"

    def test_ranking_ok_passthrough(self, client, monkeypatch):
        monkeypatch.setattr(
            kpl_proxy_routes.kpl_ranking_service, "get_sector_ranking",
            lambda date: {"ok": True, "date": date, "items": [{"plate_id": "801159"}]})
        r = client.get("/api/kpl/sector-ranking", params={"date": "2026-10-24"})
        assert r.status_code == 200
        assert r.json()["items"][0]["plate_id"] == "801159"

    def test_ranking_service_error_structured_502(self, client, monkeypatch):
        from backend.services.kpl_ranking_service import KplRankingError

        def _raise(date):
            raise KplRankingError("kpl_errcode", errorCode="1020")

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_ranking", _raise)
        r = client.get("/api/kpl/sector-ranking", params={"date": "2026-10-24"})
        assert r.status_code == 502
        body = r.json()
        assert body["ok"] is False and body["degraded"] is True
        assert body["errorCode"] == "1020"

    def test_live_stocks_meta_validation_and_passthrough(self, client, monkeypatch):
        """直播个股 meta 读口（2026-10-29）：日期/缺码校验 + 服务层透传（零外呼查索引）。"""
        r = client.get("/api/kpl/live-stocks-meta", params={"date": "bad", "codes": "600000"})
        assert r.status_code == 400
        r = client.get("/api/kpl/live-stocks-meta", params={"date": "2026-10-29"})
        assert r.status_code == 400 and r.json()["reason"] == "missing_codes"
        captured = {}

        def _fake(codes, date):
            captured["codes"], captured["date"] = list(codes), date
            return {"ok": True, "date": date, "building": False,
                    "hits": {codes[0]: {"rank_title": "龙一", "turnover": 9.9,
                                        "board_status": "首板", "concept": "机器人",
                                        "plate_id": "801159"}},
                    "missed": ["300999"], "failedPlates": [], "indexSize": 1,
                    "error": None}

        monkeypatch.setattr(
            kpl_proxy_routes.kpl_ranking_service, "get_live_stocks_meta", _fake)
        r = client.get("/api/kpl/live-stocks-meta",
                       params={"date": "2026-10-29", "codes": "603278,300999"})
        assert r.status_code == 200
        body = r.json()
        assert captured["codes"] == ["603278", "300999"] and captured["date"] == "2026-10-29"
        assert body["hits"]["603278"]["rank_title"] == "龙一"
        assert body["missed"] == ["300999"]

    def test_stocks_service_error_structured_502(self, client, monkeypatch):
        from backend.services.kpl_ranking_service import KplRankingError

        def _raise(plate, date, page=0):
            raise KplRankingError("empty_list_check_credentials", plate_id=plate)

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_stocks", _raise)
        r = client.get("/api/kpl/sector-stocks",
                       params={"plate": "801159", "date": "2026-10-24"})
        assert r.status_code == 502
        assert r.json()["reason"] == "empty_list_check_credentials"

    def test_stocks_page_param_passthrough(self, client, monkeypatch):
        captured = {}

        def _fake(plate, date, page=0):
            captured["page"] = page
            return {"ok": True, "items": [], "total": 0}

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_stocks", _fake)
        client.get("/api/kpl/sector-stocks", params={"plate": "801159", "date": "2026-10-24", "page": 2})
        assert captured["page"] == 2

    def test_stocks_negative_page_rejected_400(self, client):
        r = client.get("/api/kpl/sector-stocks",
                       params={"plate": "801159", "date": "2026-10-24", "page": -1})
        assert r.status_code == 400
        assert r.json()["reason"] == "invalid_page"


class TestWsRelay:
    """WS /api/kpl/ws/kpl-quotes 双向中继：mock 上游 websockets.connect。"""

    def test_ws_relay_downstream_and_upstream(self, client, monkeypatch):
        import asyncio
        import json as jsonlib

        upstream_msgs = [jsonlib.dumps({"type": "ping", "n": 1}),
                         jsonlib.dumps({"type": "stock_quotes", "items": []})]
        upstream_sent = []

        class _FakeUpstream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def recv(self):
                if upstream_msgs:
                    await asyncio.sleep(0.01)
                    return upstream_msgs.pop(0)
                # 无更多上游消息后挂起，等测试端关闭
                await asyncio.sleep(3600)

            async def send(self, msg):
                upstream_sent.append(msg)

        def _fake_connect(*args, **kwargs):
            return _FakeUpstream()

        monkeypatch.setattr(kpl_proxy_routes.websockets, "connect", _fake_connect)
        with client.websocket_connect("/api/kpl/ws/kpl-quotes") as ws:
            first = ws.receive_json()
            assert first["type"] == "ping"
            second = ws.receive_json()
            assert second["type"] == "stock_quotes"
            # 下行：浏览器 → 上游
            ws.send_text(jsonlib.dumps({"type": "ping", "n": 2}))


def test_daban_list_passthrough(client):
    """2103 打板个股列表快照：pid_type 透传上游，结构原样回浏览器。"""
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "pid_type": 8, "max_size": 181, "items": []})
    ]
    r = client.get("/api/kpl/daban-list", params={"pid_type": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["max_size"] == 181


def test_daban_list_upstream_unavailable_structured_502(client):
    _FakeAsyncClient.fail_with = OSError("connection refused")
    r = client.get("/api/kpl/daban-list")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and "kpl_upstream_unavailable" in body["reason"]


def test_daban_list_history_date_validation(client):
    r = client.get("/api/kpl/daban-list-history")
    assert r.status_code == 400
    assert r.json()["reason"].startswith("invalid_or_missing_date")
    r = client.get("/api/kpl/daban-list-history", params={"date": "2026-10-24", "pid_type": 99})
    assert r.status_code == 400
    assert r.json()["reason"] == "invalid_pid_type"


def test_daban_list_history_passthrough(client, monkeypatch):
    class _FakeUpstream:
        @staticmethod
        def get_daban_list_history(date, pid_type):
            return {"ok": True, "date": date, "pid_type": pid_type, "items": [{"stock_id": "603028"}]}

    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_daban_list_history",
                        _FakeUpstream.get_daban_list_history)
    r = client.get("/api/kpl/daban-list-history", params={"date": "2026-10-24", "pid_type": 8})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["items"][0]["stock_id"] == "603028"


def test_daban_list_history_service_error_structured_502(client, monkeypatch):
    from backend.services.kpl_ranking_service import KplRankingError

    def _boom(date, pid_type):
        raise KplRankingError("kpl_errcode", errorCode="1020", error="参数出错")

    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_daban_list_history", _boom)
    r = client.get("/api/kpl/daban-list-history", params={"date": "2026-10-24", "pid_type": 8})
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and body["errorCode"] == "1020"


def test_daban_head_validation(client):
    r = client.get("/api/kpl/daban-head")
    assert r.status_code == 400


def test_daban_head_upstream_unreachable_502(client, monkeypatch):
    from backend.services.kpl_ranking_service import KplRankingError

    def _boom(date):
        raise KplRankingError("upstream_unreachable: ConnectError", url="apphis")

    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_daban_head_info", _boom)
    r = client.get("/api/kpl/daban-head", params={"date": "2026-10-27"})
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and "upstream_unreachable" in body["reason"]


def test_daban_head_passthrough(client, monkeypatch):
    from backend.services.kpl_ranking_service import KplRankingError

    class _Up:
        @staticmethod
        def get_daban_head_info(date):
            if date == "2026-10-26":
                raise KplRankingError("kpl_errcode", errorCode="1020", error="参数出错")
            return {"ok": True, "date": date, "raw": {"nums": {"tZhangTing": 84, "lZhangTing": 33, "tFengBan": 87.234, "lFengBan": 58.9286, "tDieTing": 7, "lDieTing": 49}}}

    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_daban_head_info", _Up.get_daban_head_info)
    r = client.get("/api/kpl/daban-head", params={"date": "2026-10-27"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["raw"]["nums"]["tZhangTing"] == 84
    r = client.get("/api/kpl/daban-head", params={"date": "2026-10-26"})
    assert r.status_code == 502 and r.json()["errorCode"] == "1020"


def test_daban_prev_day_basis_passthrough(client, monkeypatch):
    monkeypatch.setattr(
        kpl_proxy_routes.kpl_ranking_service, "get_daban_prev_day_basis",
        lambda date, codes: {"ok": True, "date": date,
                             "basis": {c: {"prev_date": "2026-10-27", "prev_close": 9.66,
                                           "prev_volume_shou": 200000.0} for c in codes},
                             "missing": [], "source": "tencent_ifzq"})
    r = client.get("/api/kpl/daban-prev-day-basis",
                   params={"date": "2026-10-28", "codes": "603028,301660"})
    assert r.status_code == 200
    body = r.json()
    assert body["basis"]["603028"]["prev_close"] == 9.66 and body["missing"] == []


def test_daban_prev_day_basis_validation(client):
    r = client.get("/api/kpl/daban-prev-day-basis")
    assert r.status_code == 400
    r = client.get("/api/kpl/daban-prev-day-basis", params={"date": "2026-10-28"})
    assert r.status_code == 400 and r.json()["reason"] == "missing_codes"


def test_lhb_passthrough_routes(client):
    # lhb-forecast / lhb-realtime 纯透传 :8002（两条路由都断言）
    _FakeAsyncClient.responses = [_FakeResponse({"ok": False, "degraded": True,
                                                 "reason": "no_lhb_forecast_snapshot"}),
                                  _FakeResponse({"ok": False, "degraded": True,
                                                 "reason": "no_lhb_realtime_snapshot"})]
    r = client.get("/api/kpl/lhb-forecast")
    assert r.status_code == 200
    assert r.json()["reason"] == "no_lhb_forecast_snapshot"
    r = client.get("/api/kpl/lhb-realtime")
    assert r.status_code == 200
    assert r.json()["reason"] == "no_lhb_realtime_snapshot"


def test_lhb_history_missing_date_structured_422(client):
    r = client.get("/api/kpl/lhb-history")
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and body["degraded"] is True
    assert body["reason"] == "missing_date"


def test_lhb_history_upstream_error_structured_502(client, monkeypatch):
    from backend.services import kpl_lhb_history as lhb_his
    def boom(date):
        raise RuntimeError("upstream limit")
    monkeypatch.setattr(lhb_his, "fetch_his_lhb_list", boom)
    r = client.get("/api/kpl/lhb-history?date=2026-10-28")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and body["reason"] == "upstream_error"


def test_lhb_history_ok(client, monkeypatch):
    from backend.services import kpl_lhb_history as lhb_his
    monkeypatch.setattr(lhb_his, "fetch_his_lhb_list",
                        lambda date: {"errcode": "0", "date": date, "YCnum": 1,
                                      "orderSign": [], "info": []})
    monkeypatch.setattr(lhb_his, "fetch_his_lhb_stock",
                        lambda date: {"errcode": "0", "Count": 0, "info": []})
    r = client.get("/api/kpl/lhb-history?date=2026-10-28")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["list"]["date"] == "2026-10-28"
    assert body["list"]["order_sign"] == []      # 结构化空态保留
    assert body["stocks"]["count"] == 0


def test_lhb_sale_missing_date_structured_422(client):
    r = client.get("/api/kpl/lhb-sale")
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False and body["degraded"] is True
    assert body["reason"] == "missing_date"


def test_lhb_sale_upstream_error_structured_502(client, monkeypatch):
    from backend.services import kpl_lhb_sale as sale_svc
    def boom(date, type_=0):
        raise RuntimeError("upstream limit")
    monkeypatch.setattr(sale_svc, "fetch_lhb_sale", boom)
    r = client.get("/api/kpl/lhb-sale?date=2026-10-28")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and body["reason"] == "upstream_error"


def test_lhb_sale_ok_with_empty_note(client, monkeypatch):
    from backend.services import kpl_lhb_sale as sale_svc
    monkeypatch.setattr(sale_svc, "fetch_lhb_sale",
                        lambda date, type_=0: {"errcode": "0", "Time": date,
                                               "Total": 0, "list": []})
    r = client.get("/api/kpl/lhb-sale?date=2026-10-29")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["rows"] == [] and body["total"] == 0
    assert "盘后生成" in body["note"]             # 结构化空态显式提示，不伪装

    monkeypatch.setattr(sale_svc, "fetch_lhb_sale",
                        lambda date, type_=0: {"errcode": "0", "Time": date,
                                               "Total": 1, "list": [
            {"ID": "1", "Name": "华泰证券总部", "Buy": "100.0",
             "Sell": "50.0", "JoinNum": 2}]})
    r = client.get("/api/kpl/lhb-sale?date=2026-10-28")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"][0]["name"] == "华泰证券总部" and "note" not in body



def test_lhb_stock_board_restored_routes(client, monkeypatch):
    """/lhb-stock-board 恢复（2026-10-30 读数入口修正）：当日左列表主源=实际上榜名单。"""
    from backend.services import kpl_lhb_sale as sale_svc
    r = client.get("/api/kpl/lhb-stock-board")
    assert r.status_code == 422 and r.json()["reason"] == "missing_date"

    def boom(date):
        raise RuntimeError("upstream limit")

    monkeypatch.setattr(sale_svc, "fetch_lhb_stock_list", boom)
    r = client.get("/api/kpl/lhb-stock-board?date=2026-10-30")
    assert r.status_code == 502 and r.json()["reason"] == "upstream_error"

    monkeypatch.setattr(sale_svc, "fetch_lhb_stock_list",
                        lambda date: {"errcode": "0", "Time": date, "Total": 1, "list": [
                            {"ID": "603696", "Name": "安记食品", "BuyIn": "121003701.36",
                             "JoinNum": 4, "Turnover": "562678136", "IncreaseAmount": "10.01%"}]})
    r = client.get("/api/kpl/lhb-stock-board?date=2026-10-30")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["total"] == 1
    assert body["rows"][0]["code"] == "603696"
    assert body["rows"][0]["buy_in"] == "121003701.36"       # 元原样不缩放
    assert body["rows"][0]["increase_amount"] == "10.01%"


def test_lhb_day_fallback_routes(client, monkeypatch):
    """当日无数据回退（2026-10-30 用户裁决）：空日逐日历日回看至上个有数据日，显式标注。"""
    from backend.services import kpl_lhb_sale as sale_svc
    # 2026-11-01（周日）/10-31（周六）空，10-30 有数据
    data = {"errcode": "0", "Time": "2026-10-30", "Total": 1, "list": [
        {"ID": "000678", "Name": "襄阳轴承", "BuyIn": "-134504061",
         "Turnover": "3224592082", "IncreaseAmount": "-3.57%"}]}

    def fake_stock_list(date):
        assert isinstance(date, str) and date >= "2026-10-21"   # 回看不越过 10 日上限
        return data if date == "2026-10-30" else {"errcode": "0", "Time": date,
                                                  "Total": 0, "list": []}

    monkeypatch.setattr(sale_svc, "fetch_lhb_stock_list", fake_stock_list)
    r = client.get("/api/kpl/lhb-stock-board?date=2026-11-01")
    body = r.json()
    assert r.status_code == 200 and body["rows"]
    assert body["effective_date"] == "2026-10-30" and body["requested_date"] == "2026-11-01"
    assert "已回退" in body["note"]

    def fake_sale(date, type_=0):
        return data if date == "2026-10-30" else {"errcode": "0", "Time": date,
                                                  "Total": 0, "list": []}

    monkeypatch.setattr(sale_svc, "fetch_lhb_sale", fake_sale)
    r = client.get("/api/kpl/lhb-sale?date=2026-11-01")
    body = r.json()
    assert r.status_code == 200 and body["rows"][0]["name"] == "襄阳轴承"
    assert body["effective_date"] == "2026-10-30" and "已回退" in body["note"]

    # 回看 10 日全空：不伪装，显式注明未回退
    monkeypatch.setattr(sale_svc, "fetch_lhb_stock_list",
                        lambda date: {"errcode": "0", "Time": date, "Total": 0, "list": []})
    r = client.get("/api/kpl/lhb-stock-board?date=2020-01-01")
    body = r.json()
    assert r.status_code == 200 and body["rows"] == [] and "均为空" in body["note"]
