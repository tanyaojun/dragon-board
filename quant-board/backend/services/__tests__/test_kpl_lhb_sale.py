# -*- coding: utf-8 -*-
"""营业部榜链（GetBusinessList）测试：全 mock 零真实调用（AGENTS.md 红线 7）。"""
import pytest

from backend.services import kpl_lhb_history as lh
from backend.services import kpl_lhb_sale as ls

SALE_SAMPLE = {
    "errcode": "0", "Time": "2026-10-28", "Total": 3, "sDay": None,
    "list": [
        {"ID": "20855", "Name": "华泰证券总部", "Buy": "607216061.55",
         "Sell": "447054938.68", "JoinNum": 33},
        {"ID": "18776", "Name": "高盛(中国)证券上海浦东", "Buy": "2770257.04",
         "Sell": "287508.16", "JoinNum": 13},
        "bad-row",                                    # 非 dict → dropped
    ],
}


@pytest.fixture(autouse=True)
def _clear_cache():
    lh._CACHE.clear()
    yield
    lh._CACHE.clear()


class TestFetchMocked:
    def test_fetch_uses_swapped_a_c_and_caches(self, monkeypatch):
        calls = []
        def fake_post(url, params, ua):
            calls.append((url, params, ua))
            return dict(SALE_SAMPLE)
        monkeypatch.setattr(lh, "_post_form", fake_post)
        out1 = ls.fetch_lhb_sale("2026-10-28")
        out2 = ls.fetch_lhb_sale("2026-10-28")
        assert out1["Time"] == "2026-10-28" and len(calls) == 1   # TTL 缓存命中
        url, params, ua = calls[0]
        # a/c 互换规（D1 第一参数→c、第二参数→a）：c=LongHuBang, a=GetBusinessList
        assert params["c"] == "LongHuBang" and params["a"] == "GetBusinessList"
        assert params["Time"] == "2026-10-28"
        assert params["Index"] == "0" and params["Type"] == "0"
        assert params["STAT_SDK_TYPE"] == "500"          # 一页全量（App 每页 100）
        # 专用域 + 凭据公共出口
        assert "applhb.longhuvip.com" in url
        assert params["Token"] and params["UserID"] and params["DeviceID"]

    def test_fetch_errcode_raises_structured(self, monkeypatch):
        monkeypatch.setattr(lh, "_post_form",
                            lambda u, p, ua: {"errcode": 1020, "errmsg": "参数出错"})
        with pytest.raises(Exception):
            ls.fetch_lhb_sale("bad-date")


class TestParse:
    def test_parse_rows_and_dropped(self):
        out = ls.parse_lhb_sale(SALE_SAMPLE)
        assert out["ok"] is True and out["date"] == "2026-10-28" and out["total"] == 3
        assert len(out["rows"]) == 2 and out["dropped"] == 1     # fail-visible 聚合
        r0 = out["rows"][0]
        assert r0["sale_id"] == "20855" and r0["name"] == "华泰证券总部"
        assert r0["buy"] == "607216061.55" and r0["sell"] == "447054938.68"  # 元原样不缩放
        assert r0["join_num"] == 33 and r0["raw"]["ID"] == "20855"

    def test_parse_empty_structured_state(self):
        out = ls.parse_lhb_sale({"errcode": "0", "Time": "2026-10-29",
                                 "Total": 0, "list": []})
        assert out["ok"] is True and out["rows"] == [] and out["total"] == 0
        assert out["dropped"] == 0

    def test_parse_non_list_info(self):
        out = ls.parse_lhb_sale({"errcode": "0", "list": "garbage"})
        assert out["rows"] == [] and out["dropped"] == 0


STOCK_LIST_SAMPLE = {
    "errcode": "0", "Time": "2026-10-29", "Total": 2,
    "list": [
        {"ID": "601188", "Name": "龙江交通", "IncreaseAmount": "10.06%", "D3": "0",
         "BuyIn": "121003701.36", "JoinNum": 4, "Turnover": "642104876",
         "CircPrice": 4569144702.5, "Amplitude": "10.06", "TurnoverRatio": "14.3",
         "Capitalization": 4569144702.5},
        {"Name": "缺ID行"},                       # 缺 ID → dropped
    ],
    "Count": {"601188": 46980},
}

AGENCY_SAMPLE = {
    "errcode": "0", "Time": "2026-10-29", "Day": "2026-10-29", "tag": "lv2",
    "List": [
        {"ID": "920296", "Name": "四方股份", "BuyIn": -3225162.13, "JoinNum": 1,
         "Turnover": "191263535", "IncreaseAmount": "-5.36%", "FengKou": [801573]},
        "bad-row",                                # 非 dict → dropped
    ],
}


class TestStockListAndAgency:
    def test_fetch_stock_list_params(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lh, "_post_form",
                            lambda u, p, ua: (calls.append((u, p)), dict(STOCK_LIST_SAMPLE))[1])
        out = ls.fetch_lhb_stock_list("2026-10-29")
        url, params = calls[0]
        assert params["a"] == "GetStockList" and params["c"] == "LongHuBang"
        assert params["Time"] == "2026-10-29" and params["STAT_SDK_TYPE"] == "500"
        assert "applhb.longhuvip.com" in url
        assert ls.parse_lhb_stock_list(out)["total"] == 2

    def test_fetch_agency_params(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lh, "_post_form",
                            lambda u, p, ua: (calls.append((u, p)), dict(AGENCY_SAMPLE))[1])
        out = ls.fetch_lhb_agency("2026-10-29")
        assert calls[0][1]["a"] == "GetAgencyListV2"
        assert ls.parse_lhb_agency(out)["date"] == "2026-10-29"

    def test_parse_stock_list(self):
        out = ls.parse_lhb_stock_list(STOCK_LIST_SAMPLE)
        assert out["ok"] is True and len(out["rows"]) == 1 and out["dropped"] == 1
        r0 = out["rows"][0]
        assert r0["code"] == "601188" and r0["name"] == "龙江交通"
        assert r0["buy_in"] == "121003701.36"          # 席位买入额，元原样不缩放
        assert r0["join_num"] == 4 and r0["raw"]["ID"] == "601188"
        assert out["count_map"] == {"601188": 46980}   # 语义未考，原样透传不消费

    def test_parse_stock_list_count_map_non_dict_passthrough_none(self):
        out = ls.parse_lhb_stock_list({"errcode": "0", "list": [], "Count": "garbage"})
        assert out["count_map"] is None and out["rows"] == []

    def test_parse_agency_negative_net_buy(self):
        out = ls.parse_lhb_agency(AGENCY_SAMPLE)
        assert out["ok"] is True and len(out["rows"]) == 1 and out["dropped"] == 1
        r0 = out["rows"][0]
        assert r0["code"] == "920296"
        assert r0["buy_in"] == -3225162.13 and r0["join_num"] == 1   # 负=净卖出，元原样

    def test_parse_agency_missing_list_key(self):
        out = ls.parse_lhb_agency({"errcode": "0"})   # List 大小写陷阱：缺 List → 空
        assert out["rows"] == [] and out["dropped"] == 0
