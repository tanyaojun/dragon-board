# -*- coding: utf-8 -*-
"""韭研 fetch/parse 纯函数测试（固定样本来自 2026-09-30 实测响应裁剪）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jiuyan_fetch import (
    build_headers,
    extract_digest,
    fetch_count,
    fetch_field,
    parse_count_response,
    parse_field_response,
)

SAMPLE_SSR = ('window.__NUXT__=(function(a,b,c,d){return {layout:"first",state:{mQ7vL2xR9a:'
              '{digest:"a7047284ed915c8e327699b519a5ce5a5ca7b37bd2c11b87ab0afbcf4c56fd530888adc9145bb3073d0637ff4b43768699cbb585bb593bd9cde7cf9fc80580944b676d4d2"}}}})')

SAMPLE_FIELD = {
    "msg": "",
    "errCode": "0",
    "data": [
        {"date": "2026-09-30", "reason": "", "action_field_id": "", "name": "简图", "count": 0},
        {"action_field_id": "b11d", "name": "医药医疗", "date": "2026-09-30", "count": 2, "list": [
            {"code": "sz000504", "name": "南华生物",
             "article": {"article_id": "a1", "like_count": 12, "comment_count": 0,
                         "action_info": {"time": "10:22:42", "num": "9天5板", "price": 1242, "day": 5,
                                         "edition": 5, "reason": None,
                                         "expound": "细胞医疗+华字辈\n1、公司主要从事生物医药业务"}}},
            {"code": "sh600825", "name": "新华传媒",
             "article": {"article_id": "a2", "like_count": 11,
                         "action_info": {"time": "09:25:00", "num": "7天7板", "price": 1035, "day": 7,
                                         "edition": 7, "reason": None, "expound": "拟收购界面财联社"}}},
        ]},
    ],
}


def test_extract_digest_from_ssr():
    assert extract_digest(SAMPLE_SSR) == ("a7047284ed915c8e327699b519a5ce5a5ca7b37bd2c11b87ab0afbcf4c56"
                                          "fd530888adc9145bb3073d0637ff4b43768699cbb585bb593bd9cde7cf9fc80580944b676d4d2")
    assert extract_digest("<html>无载荷</html>") is None
    assert extract_digest("") is None


def test_parse_field_response_normalizes_and_skips_empty():
    out = parse_field_response(SAMPLE_FIELD)
    assert out["degradedSources"] == []
    assert out["totalStocks"] == 2
    assert len(out["fields"]) == 1  # 简图占位板块（count=0 无 list）跳过
    field = out["fields"][0]
    assert field["name"] == "医药医疗" and field["count"] == 2
    s0 = field["stocks"][0]
    assert s0["code"] == "sz000504" and s0["name"] == "南华生物"
    assert s0["price"] == 12.42  # 站点 price=1242 → /100
    assert s0["time"] == "10:22:42" and s0["num"] == "9天5板" and s0["day"] == 5
    assert s0["articleId"] == "a1" and s0["likeCount"] == 12
    assert s0["expound"].startswith("细胞医疗")


def test_parse_field_response_fail_visible():
    # 非 0 errCode → 降级不伪造
    out = parse_field_response({"errCode": "110", "msg": "token无效，请重试", "data": {}})
    assert out["fields"] == [] and out["totalStocks"] == 0
    assert any("110" in d for d in out["degradedSources"])
    # 个股缺 action_info → 降级保留基础字段
    payload = {"errCode": "0", "data": [{"name": "X", "count": 1, "list": [{"code": "a", "name": "A"}]}]}
    out2 = parse_field_response(payload)
    assert out2["totalStocks"] == 1
    assert any("action_info" in d for d in out2["degradedSources"])
    assert out2["fields"][0]["stocks"][0]["price"] is None


def test_parse_count_response():
    assert parse_count_response({"errCode": "0", "data": {"all": 64, "recommend": 5}}) == {"all": 64, "recommend": 5}
    assert parse_count_response({"errCode": "1", "data": {}}) == {"all": None, "recommend": None}
    assert parse_count_response(None) == {"all": None, "recommend": None}


def test_build_headers_contract():
    h = build_headers("SESS", "TOK", "2026-10-02T00:51:52Z")
    assert h["platform"] == "3" and h["token"] == "TOK" and h["timestamp"] == "2026-10-02T00:51:52Z"
    assert h["Cookie"] == "SESSION=SESS"
    assert h["Origin"] == "https://www.jiuyangongshe.com"


class _FakeResp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text

    def json(self):
        import json
        return json.loads(self.text)


def test_fetch_field_and_count_auth_signals(monkeypatch):
    import backend.operations.jiuyan_fetch as mod

    ok_text = SAMPLE_FIELD.__class__(  # noqa: F841
    )
    monkeypatch.setattr(mod, "api_post", lambda *a, **k: (200, __import__("json").dumps(SAMPLE_FIELD)))
    out = mod.fetch_field("2026-09-30", session_cookie="S", token="T", timestamp="TS")
    assert out["ok"] is True and out["parsed"]["totalStocks"] == 2

    monkeypatch.setattr(mod, "api_post", lambda *a, **k: (200, '{"errCode":"110","msg":"token无效"}'))
    bad = mod.fetch_field("2026-09-30", session_cookie="S", token="T", timestamp="TS")
    assert bad["ok"] is False and "110" in bad["error"]

    monkeypatch.setattr(mod, "api_post", lambda *a, **k: (200, '{"errCode":"0","data":{"all":64,"recommend":5}}'))
    cnt = fetch_count("2026-09-30", session_cookie="S", token="T", timestamp="TS")
    assert cnt["ok"] is True and cnt["all"] == 64 and cnt["authFailed"] is False

    monkeypatch.setattr(mod, "api_post", lambda *a, **k: (200, '{"errCode":"1","msg":"登录失效","data":{}}'))
    cnt2 = fetch_count("2026-09-30", session_cookie="S", token="T", timestamp="TS")
    assert cnt2["ok"] is False and cnt2["authFailed"] is True
