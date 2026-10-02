# -*- coding: utf-8 -*-
"""韭研公社（jiuyangongshe.com）异动数据采集纯函数层（设计 jiuyan-collector-design.md）。

已验证事实（2026-10-02 浏览器抓包）：
- 主数据 `POST {API_BASE}/action/field` body {"date","pc":1} → data[] 板块（name/count/list[]），
  个股 article.action_info{涨停时间 time/连板 num/price(×100 整数)/day/reason/expound 人工解析}；
- 请求头 platform:3 + timestamp(ISO Z 秒级) + token（页内 globalThis.nR4xKp7mQa 铸，铸造在
  jiuyan_mint.py/手动，本模块只消费）+ Cookie SESSION=...；缺一 → errCode 110/登录失效；
- token 与 body 无关、新鲜度 ≥2 分钟；digest 在异动页 SSR HTML 公开（mQ7vL2xR9a:{digest:"…"}）。

fail-visible：解析异常/缺源进 degradedSources，不伪造空数据。
"""
from __future__ import annotations

import json
import re
from typing import Any

API_BASE = "https://web-api.jiuyangongshe.com/jystock-app/api/v1"
ACTION_PAGE = "https://www.jiuyangongshe.com/action/{date}"
DIGEST_RE = re.compile(r'mQ7vL2xR9a:\{digest:"([0-9a-f]{64,})"')
PRICE_SCALE = 100.0  # 站点 price 字段为元×100 整数（新华传媒 10.35 元 → 1035）


def extract_digest(html: str) -> str | None:
    """从异动页 SSR HTML 提取 mQ7vL2xR9a digest（token 生成原料，公开）。"""
    m = DIGEST_RE.search(html or "")
    return m.group(1) if m else None


def parse_field_response(payload: dict) -> dict:
    """action/field 响应 → 归一化结构（纯函数）。

    输出 {fields, totalStocks, degradedSources}；空板块（简图占位）跳过；
    个股缺 article/action_info 时该股降级保留基础字段并记 degradedSources。
    """
    degraded: list[str] = []
    if not isinstance(payload, dict) or payload.get("errCode") not in (0, "0"):
        degraded.append(f"errCode={payload.get('errCode') if isinstance(payload, dict) else 'non-dict'}"
                        f" msg={payload.get('msg') if isinstance(payload, dict) else ''}")
        return {"fields": [], "totalStocks": 0, "degradedSources": degraded}
    data = payload.get("data")
    if not isinstance(data, list):
        degraded.append("data 非数组")
        return {"fields": [], "totalStocks": 0, "degradedSources": degraded}

    fields: list[dict] = []
    total = 0
    for field in data:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        raw_list = field.get("list")
        if not name or not isinstance(raw_list, list):
            if field.get("count"):
                degraded.append(f"板块缺 list: {name}")
            continue
        stocks: list[dict] = []
        for row in raw_list:
            if not isinstance(row, dict):
                continue
            article = row.get("article") if isinstance(row.get("article"), dict) else {}
            info = article.get("action_info") if isinstance(article.get("action_info"), dict) else {}
            if not info:
                degraded.append(f"个股缺 action_info: {row.get('name')}")
            price = info.get("price")
            stocks.append({
                "code": row.get("code"),
                "name": row.get("name"),
                "price": round(float(price) / PRICE_SCALE, 2) if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
                "time": info.get("time"),
                "num": info.get("num"),
                "day": info.get("day"),
                "reason": info.get("reason"),
                "expound": info.get("expound"),
                "articleId": article.get("article_id"),
                "likeCount": article.get("like_count"),
            })
        fields.append({"name": name, "count": field.get("count", len(stocks)), "stocks": stocks})
        total += len(stocks)
    return {"fields": fields, "totalStocks": total, "degradedSources": degraded}


def parse_count_response(payload: dict) -> dict:
    """count-pc 响应 → {all, recommend}（缺失 None，不伪造 0）。"""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"all": None, "recommend": None}
    return {"all": data.get("all"), "recommend": data.get("recommend")}


def build_headers(session_cookie: str, token: str, timestamp: str) -> dict:
    """API 请求头三件套 + 会话（已验证配方，2026-10-02）。"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "platform": "3",
        "timestamp": timestamp,
        "token": token,
        "Cookie": f"SESSION={session_cookie}",
        "Referer": "https://www.jiuyangongshe.com/action/2026-09-30",
        "Origin": "https://www.jiuyangongshe.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
    }


def api_post(url_path: str, body: dict, *, session_cookie: str, token: str, timestamp: str,
             timeout: int = 20) -> tuple[int, str]:
    """真实 API 调用（薄封装，测试用 monkeypatch 替换）。返回 (http_status, text)。"""
    import requests

    resp = requests.post(API_BASE + url_path, json=body, headers=build_headers(session_cookie, token, timestamp),
                         timeout=timeout)
    return resp.status_code, resp.text


def fetch_field(date: str, *, session_cookie: str, token: str, timestamp: str) -> dict:
    """拉取并解析某交易日异动全量。返回 {ok, date, parsed|error}。"""
    status, text = api_post("/action/field", {"date": date, "pc": 1},
                            session_cookie=session_cookie, token=token, timestamp=timestamp)
    if status != 200:
        return {"ok": False, "date": date, "error": f"HTTP {status}"}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "date": date, "error": f"json: {exc}"}
    err = payload.get("errCode")
    if err not in (0, "0"):
        return {"ok": False, "date": date, "error": f"errCode={err} msg={payload.get('msg')}"}
    parsed = parse_field_response(payload)
    return {"ok": True, "date": date, "parsed": parsed}


def fetch_count(date: str, *, session_cookie: str, token: str, timestamp: str) -> dict:
    """count-pc 便宜探针：返回 {ok, all, recommend, authFailed}。authFailed=True = token/会话失效信号。"""
    status, text = api_post("/action/count-pc", {"date": date},
                            session_cookie=session_cookie, token=token, timestamp=timestamp)
    if status != 200:
        return {"ok": False, "authFailed": False, "error": f"HTTP {status}"}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "authFailed": False, "error": f"json: {exc}"}
    if payload.get("errCode") == "110":
        return {"ok": False, "authFailed": True, "error": "token无效"}
    parsed = parse_count_response(payload)
    if payload.get("errCode") not in (0, "0"):
        return {"ok": False, "authFailed": True, "error": f"登录失效({payload.get('msg')})"}
    return {"ok": True, **parsed, "authFailed": False}
