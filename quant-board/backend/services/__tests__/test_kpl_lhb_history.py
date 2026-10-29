# -*- coding: utf-8 -*-
"""kpl_lhb_history 测试：parse_* 纯函数 + fetch mock _post_form（零真实 HTTP，红线 7）。

样本自 2026-10-29 开火实测响应（.tmp_review/lhbhis_probe_results.jsonl）截取构造。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_lhb_history as lh  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache():
    lh._CACHE.clear()
    yield
    lh._CACHE.clear()


LIST_SAMPLE = {
    "errcode": "0", "date": "2026-10-28", "YCnum": 3,
    "orderSign": ["19", "20", "21"],
    "ttag": 0.001,
    "info": [
        {"BID": "1",
         "Reason": "沪市主板:日价格偏离值达到7%前5只证券",
         "Index": ["日偏离值;6", "成交额;4", "涨幅;2"],
         "stockList": [
             ["600715", "文投控股", "10.16", "7.96", "432493211", "15.08", "9.25", "21.6", "2连板", "0", "1", "2"],
             ["600173", "卧龙地产", "10.1", "1.07", "40007343", "9.88", "9.19", "9.19", "首板", "0", "1", "1"],
         ]},
        {"BID": "2", "Reason": "日涨幅15%前2只证券", "Index": ["涨幅;2"],
         "stockList": [["300291", "明冠新材", "6.24", "20", "18.86", "1022143152"]]},
    ],
}

STOCK_SAMPLE = {
    "errcode": "0", "Count": 2, "ttag": 0.002,
    "info": [
        ["603696", "安记食品", "食品加工、社区团购", "14.31", "-10", "16.38", "562678136",
         "-0.069832", "-27469779", "49176780", "-76646559", "38.72", "3365712000",
         "3365712000", "1423696176", "5.79", "", "3739", "3", "偏离-7%", "1793170523", "1"],
        ["300291", "明冠新材", "AI视频、AI应用", "6.24", "20", "18.86", "1022143152",
         "0", "142492716", "513876847", "-371384131", "30.22", "5807933939",
         "5877391422", "3625312364", "22.31", "首板", "3833", "90", "涨幅15%", "1793168368", "1"],
    ],
}


class TestParseHisLhbList:
    def test_parse_groups(self):
        out = lh.parse_his_lhb_list(LIST_SAMPLE)
        assert out["ok"] is True and out["date"] == "2026-10-28" and out["yc_num"] == 3
        assert out["raw_group_count"] == 2
        g0 = out["groups"][0]
        assert g0["bid"] == "1"
        assert "偏离值达到7%" in g0["reason"]
        assert g0["index_cols"] == ["日偏离值;6", "成交额;4", "涨幅;2"]
        assert g0["stocks"][0][0] == "600715" and len(g0["stocks"]) == 2
        assert out["order_sign"] == ["19", "20", "21"]
        assert "raw_len" in out

    def test_parse_empty_structured_not_fake_zero(self):
        # 当日未生成：info=[] 但 orderSign 给出全量 BID —— fail-visible 保留结构化空态
        empty = {"errcode": "0", "date": "2026-10-29", "YCnum": 0,
                 "orderSign": ["19", "20"], "info": []}
        out = lh.parse_his_lhb_list(empty)
        assert out["groups"] == [] and out["yc_num"] == 0
        assert out["order_sign"] == ["19", "20"]      # 结构化空态证据，不伪装

    def test_parse_malformed_fail_visible(self):
        out = lh.parse_his_lhb_list({"info": "garbage", "errcode": "0"})
        assert out["groups"] == [] and "raw_len" in out


class TestParseHisLhbStock:
    def test_parse_rows(self):
        out = lh.parse_his_lhb_stock(STOCK_SAMPLE)
        assert out["count"] == 2 and len(out["rows"]) == 2
        r0 = out["rows"][0]
        assert r0["stock_id"] == "603696" and r0["reason"] == "偏离-7%"
        assert r0["main_net_amount"] == "-27469779"   # raw 原样，缩放 task-3 裁决
        assert r0["ts"] == "1793170523" and r0["is_new"] is True
        assert len(r0["raw"]) == 22

    def test_parse_malformed_row_skipped_fail_visible(self):
        out = lh.parse_his_lhb_stock({"Count": 1, "info": [["600000", "只有两列"]], "errcode": "0"})
        assert out["rows"] == [] and out["count"] == 1   # Count 保留上游口径，行不伪装


class TestFetchMocked:
    def test_fetch_uses_swapped_a_c_and_caches(self, monkeypatch):
        calls = []
        def fake_post(url, params, ua):
            calls.append((url, params, ua))
            return dict(LIST_SAMPLE)
        monkeypatch.setattr(lh, "_post_form", fake_post)
        out1 = lh.fetch_his_lhb_list("2026-10-28")
        out2 = lh.fetch_his_lhb_list("2026-10-28")
        assert out1["date"] == "2026-10-28" and len(calls) == 1   # TTL 缓存命中
        url, params, ua = calls[0]
        # a/c 互换是本链关键坑：a=OnTheLHBList, c=HisBeOnTheLHB
        assert params["a"] == "OnTheLHBList" and params["c"] == "HisBeOnTheLHB"
        assert params["Date"] == "2026-10-28"
        assert params["Token"] and params["UserID"] and params["DeviceID"]  # 凭据公共出口
        assert "apphis.longhuvip.com" in url

    def test_fetch_stock_params(self, monkeypatch):
        calls = []
        monkeypatch.setattr(lh, "_post_form", lambda u, p, ua: (calls.append((u, p)), dict(STOCK_SAMPLE))[1])
        out = lh.fetch_his_lhb_stock("2026-10-28")
        assert lh.parse_his_lhb_stock(out)["count"] == 2
        assert calls[0][1]["a"] == "OnTheLHBStock" and calls[0][1]["c"] == "HisBeOnTheLHB"

    def test_fetch_errcode_raises_structured(self, monkeypatch):
        monkeypatch.setattr(lh, "_post_form", lambda u, p, ua: {"errcode": 1020, "errmsg": "参数出错"})
        with pytest.raises(Exception):
            lh.fetch_his_lhb_list("2026-10-28")
