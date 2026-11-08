# -*- coding: utf-8 -*-
"""涨停原因全文·历史档案链（GetDayZhangTing）：parse 纯函数 + 缓存/降级（全 mock，禁真实调用）。"""
import pytest

from backend.services import kpl_zt_reason_history as svc


def _sample_payload():
    return {
        "StockID": "301697",
        "List": [
            {"ZSCode": ["801070", "801631"], "Reason": "光伏+次新股；据投资者关系活动记录表……",
             "Date": "2026-11-06", "SCDW": "", "SCLT": "日内龙一",
             "GNSM": "据2026年11月4日投资者关系活动记录表……", "Type": "0", "PZSCode": "0",
             "Group_Str": "", "Boom_ZS": "据11月6日媒体报道……", "QitaStr": ""},
            {"ZSCode": ["803022"], "Reason": "太空光伏+次新股；……",
             "Date": "2026-11-05", "SCLT": "", "GNSM": "", "Boom_ZS": "", "QitaStr": ""},
            "bad_row",
        ],
    }


class TestParseZtReasonHistory:
    def test_full_fields_and_date_filter(self):
        out = svc.parse_zt_reason_history(_sample_payload(), "2026-11-06")
        assert out["ok"] is True and out["stock_id"] == "301697"
        assert out["matched_date"] == "2026-11-06"
        assert len(out["items"]) == 1 and out["dropped"] == 1   # 非 dict 行计入 dropped
        it = out["items"][0]
        assert it["reason"].startswith("光伏+次新股")
        assert it["gns"].startswith("据2026年11月4日")
        assert it["boom_zs"].startswith("据11月6日媒体报道")
        assert it["sclt"] == "日内龙一" and it["zs_codes"] == ["801070", "801631"]

    def test_date_mismatch_note_not_masquerade(self):
        out = svc.parse_zt_reason_history(_sample_payload(), "2026-11-03")
        assert out["items"] == [] and out["matched_date"] == "2026-11-06"
        assert "2026-11-06" in out["note"] and "不伪装" in out["note"]

    def test_empty_list_ok_not_error(self):
        out = svc.parse_zt_reason_history({"StockID": "000525", "List": []}, "2026-11-06")
        assert out["ok"] is True and out["items"] == [] and out["matched_date"] == ""

    def test_malformed_body(self):
        out = svc.parse_zt_reason_history({"List": None}, "2026-11-06")
        assert out["ok"] is True and out["items"] == [] and out["dropped"] == 0


class TestFetchCacheAndDegraded:
    def test_cache_hit_no_refetch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form", lambda *a, **k: calls.append(a) or _sample_payload())
        r1 = svc.fetch_stock_zt_reason_raw("301697")
        r2 = svc.fetch_stock_zt_reason_raw("301697")
        assert len(calls) == 1 and r1 is r2
        svc._CACHE.clear()

    def test_ttl_expiry_refetch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form", lambda *a, **k: calls.append(a) or {"StockID": "x", "List": []})
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0)
        svc.fetch_stock_zt_reason_raw("000525")
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0 + svc._CACHE_TTL_SECONDS + 1)
        svc.fetch_stock_zt_reason_raw("000525")
        assert len(calls) == 2
        svc._CACHE.clear()

    def test_get_stock_zt_reason_upstream_error_degraded(self, monkeypatch):
        class FakeErr(Exception):
            errorCode = "1020"
            error = "严格白名单"
        def boom(*a, **k):
            raise FakeErr()
        monkeypatch.setattr(svc, "_post_form", boom)
        out = svc.get_stock_zt_reason("2026-11-06", "301697")
        assert out["ok"] is False and out["degraded"] is True
        assert out["reason"] == "1020" and out["items"] == [] and out["stock_id"] == "301697"

    def test_get_stock_zt_reason_ok(self, monkeypatch):
        monkeypatch.setattr(svc, "_post_form", lambda *a, **k: _sample_payload())
        out = svc.get_stock_zt_reason("2026-11-06", "301697")
        assert out["ok"] is True and out["date"] == "2026-11-06"
        assert out["items"][0]["gns"].startswith("据2026年11月4日")
        svc._CACHE.clear()
