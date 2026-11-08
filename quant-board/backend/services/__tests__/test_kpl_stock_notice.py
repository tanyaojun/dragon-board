# -*- coding: utf-8 -*-
"""公告/新闻/研报计数协议层测试（apphis CompanyNotice/GetCompanyCount，全 mock）。"""
from backend.services import kpl_stock_notice as N


def test_parse_notice_count_full():
    out = N.parse_notice_count({"news": 3, "report": 0, "announcement": 2,
                                "CID": 9, "Date": "20261108"}, stock_id="301697")
    assert out["ok"] is True and out["stock_id"] == "301697"
    assert out["counts"] == {"announcement": 2, "report": 0, "news": 3}
    assert out["upstream_date"] == "20261108" and out["window_note"] == N.WINDOW_NOTE
    assert "partial" not in out


def test_parse_notice_count_missing_field_not_zero():
    """缺位不补 0（AGENTS §4.0）：news 缺位 → None + partial。"""
    out = N.parse_notice_count({"announcement": 2, "Date": "20261108"}, stock_id="301697")
    assert out["counts"]["news"] is None and out["counts"]["report"] is None
    assert out["partial"] is True and set(out["missing_fields"]) == {"report", "news"}


def test_parse_notice_count_unexpected_payload():
    out = N.parse_notice_count({"errcode": "1018"}, stock_id="301697")
    assert out["ok"] is False and out["degraded"] is True and out["reason"] == "unexpected_payload"


def test_get_notice_count_error_degrades(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("http down")
    monkeypatch.setattr(N, "_post_form", boom)
    out = N.get_notice_count("301697")
    assert out["ok"] is False and "RuntimeError" in out["reason"]
