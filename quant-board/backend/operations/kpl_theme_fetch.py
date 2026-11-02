# -*- coding: utf-8 -*-
"""开盘啦（longhuvip）题材语料三端点 HTTP 封装（2026-10-23，v4 换源）。

端点来源：`wzslinker.top/companys/js/longhuvip-proxy-common.js`（未混淆端点映射），
2026-10-22/23 单发实测全部打通（证据 `data/backups/kpl-corpus-probe-20261022/`）：

- `applhb.longhuvip.com  c=Topic&a=InfoList`      题材事件列表（按日分组，带热度/投票）
- `applhb.longhuvip.com  c=Topic&a=InfoGet&ID=`   题材事件详情（全文+来源+精确时间）
- `apparticle.longhuvip.com c=ThemeNews&a=GetList` 题材新闻流（Type=-1，Kword 题材标签+关联个股）
                                                   / 题材日历（Type=3，前瞻事件+日期+类型）

鉴权身份（UserID/DeviceID/Token）**复用** `mapping_refresh.KPL_APP_BASE_PARAMS`
（同一账号体系，零新增凭据；Token 失效只改 mapping_refresh 一处）。
解析函数全部纯函数化（bytes/str → dict），HTTP 与解析分离，测试全 mock。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

REQUEST_TIMEOUT_SECONDS = 15

KPL_TOPIC_HOST = "https://applhb.longhuvip.com/w1/api/index.php"
KPL_NEWS_HOST = "https://apparticle.longhuvip.com/w1/api/index.php"

# 各端点基础参数（a/c/apiv/分页由调用方给）：VerSion 与 PhoneOSNew 按 wzslinker 代理层实测值。
_TOPIC_BASE = {**KPL_APP_BASE_PARAMS, "PhoneOSNew": "2", "VerSion": "5.16.0.3", "apiv": "w38"}
_NEWS_BASE = {**KPL_APP_BASE_PARAMS, "PhoneOSNew": "2", "VerSion": "5.18.0.1", "apiv": "w39"}


def _get_json(url: str) -> dict:
    """GET + JSON 解析；HTTP 层异常抛出，业务层 errcode 由调用方结构化处理。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _check_errcode(data: dict) -> dict | None:
    """KPL 业务错误：errcode≠0 → 结构化错误（照抄韭研 errCode=9 教训：不信 msg 只看码）。"""
    code = data.get("errcode")
    if code in (0, "0", None):
        return None
    return {"ok": False, "errorCode": str(code), "error": str(data.get("errmsg") or "")[:120]}


# ── 解析（纯函数） ──────────────────────────────────────────────────────────
def parse_topic_list(data: dict) -> list[dict]:
    """`c=Topic&a=InfoList` → 逐事件扁平化：[{eventId, day, title, hotVal, isVote, time}]。"""
    out: list[dict] = []
    for day in data.get("List") or []:
        d = str(day.get("Day") or "")
        for ev in day.get("List") or []:
            out.append({
                "eventId": str(ev.get("ID") or ""),
                "day": d,
                "title": str(ev.get("Title") or ""),
                "hotVal": ev.get("HotVal"),
                "isVote": str(ev.get("IsVote") or ""),
                "time": ev.get("Time"),
            })
    return out


def parse_topic_detail(data: dict) -> dict:
    """`c=Topic&a=InfoGet` → {title, content, source, time, hotVal, num}。"""
    return {
        "title": str(data.get("Title") or ""),
        "content": str(data.get("Content") or ""),
        "source": str(data.get("Source") or ""),
        "time": str(data.get("Time") or ""),
        "hotVal": data.get("HotVal"),
        "num": data.get("Num"),
    }


def _ts_to_date(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def parse_news_list(data: dict) -> list[dict]:
    """`c=ThemeNews&a=GetList` → [{cid, title, kword, zsName, source, timeStamp, eventDate, stocks}]。

    `zsName`（2026-11-02 用户裁决①）：KPL 官方板块归属（实测近 50 条覆盖 15 条，
    如光伏研讨会带「光伏」、Neuralink 带「脑机接口」）——确定性板块↔新闻链接第二通道。
    """
    out: list[dict] = []
    for it in data.get("List") or []:
        stocks = [{"code": str(s.get("Code") or "")[-6:], "name": s.get("Name"),
                   "rate": s.get("Rate"), "setTop": s.get("SetTop")}
                  for s in (it.get("Stocks") or []) if s]
        ts = it.get("TimeStamp")
        out.append({
            "cid": str(it.get("CID") or ""),
            "title": str(it.get("Title") or ""),
            "kword": str(it.get("Kword") or ""),
            "zsName": str(it.get("ZSName") or ""),
            "source": str(it.get("Source") or ""),
            "timeStamp": ts,
            "eventDate": _ts_to_date(ts),
            "stocks": stocks,
        })
    return out


def parse_calendar_list(data: dict) -> list[dict]:
    """`Type=3` → [{pid, brief, date, tagName, stocks}]（前瞻事件）。"""
    out: list[dict] = []
    for it in data.get("List") or []:
        stocks = [{"code": str(s.get("Code") or "")[-6:], "name": s.get("Name")}
                  for s in (it.get("Stocks") or []) if s]
        out.append({
            "pid": str(it.get("PID") or ""),
            "brief": str(it.get("Brief") or ""),
            "date": str(it.get("Date") or ""),
            "tagName": str(it.get("TagName") or ""),
            "stocks": stocks,
        })
    return out


# ── HTTP 封装（返回 {ok, ...} 或 {ok: False, errorCode, error}） ─────────────
def fetch_topic_list(*, st: int = 15, index: int = 0) -> dict:
    params = {**_TOPIC_BASE, "a": "InfoList", "c": "Topic", "st": str(st), "Index": str(index)}
    try:
        data = _get_json(f"{KPL_TOPIC_HOST}?{urlencode(params)}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "errorCode": "http_error", "error": f"{type(exc).__name__}: {exc}"[:160]}
    err = _check_errcode(data)
    if err:
        return err
    events = parse_topic_list(data)
    return {"ok": True, "events": events, "empty": not events}


def fetch_topic_detail(event_id: str) -> dict:
    params = {**_TOPIC_BASE, "a": "InfoGet", "c": "Topic", "ID": str(event_id)}
    try:
        data = _get_json(f"{KPL_TOPIC_HOST}?{urlencode(params)}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "errorCode": "http_error", "error": f"{type(exc).__name__}: {exc}"[:160]}
    err = _check_errcode(data)
    if err:
        return err
    return {"ok": True, "detail": parse_topic_detail(data)}


def fetch_news_list(*, news_type: int = -1, st: int = 50, index: int = 0) -> dict:
    params = {**_NEWS_BASE, "c": "ThemeNews", "a": "GetList", "Type": str(news_type),
              "st": str(st), "Index": str(index)}
    try:
        data = _get_json(f"{KPL_NEWS_HOST}?{urlencode(params)}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "errorCode": "http_error", "error": f"{type(exc).__name__}: {exc}"[:160]}
    err = _check_errcode(data)
    if err:
        return err
    if news_type == 3:
        items = parse_calendar_list(data)
    else:
        items = parse_news_list(data)
    return {"ok": True, "items": items, "empty": not items}
