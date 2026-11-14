# -*- coding: utf-8 -*-
"""同花顺 7×24 快讯拉取/解析层（纯函数优先；2026-11-14 盘前催化增量 C，见
`docs/hotlist-jev/auction-preopen-catalyst-preregistration-20261114.md` §4）。

端点（2026-10-23 勘察 §3 实测 + 2026-11-14 C0 探针复探，零凭据零鉴权）：
  GET https://news.10jqka.com.cn/tapp/news/push/stock/?page={n}&tag=&track=website&pagesize=50
响应：{"code":"200","data":{"list":[{id,seq,title,digest,ctime(epoch 秒),rtime,source,
  stock(JSON 字符串),tag(JSON 字符串),tags,url,...}]}}

设计纪律（AGENTS §1.2-9/§4.0）：
- 频控预算：`THS_FLASH_DAILY_CALL_BUDGET` 默认 8/日（两尝试槽 × ≤3 页 + 退避重试），
  计数集合 `ths_api_calls`；C0 探针连发 3 发（间隔 ≥2s）无限流征兆，仍按预算保守接线；
- 失败结构化返回（ok=False + error），不伪造空成功；解析缺字段如实缺位不补 0。
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

FLASH_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"
FLASH_PAGESIZE = 50


def fetch_flash_page(page: int = 1, *, pagesize: int = FLASH_PAGESIZE,
                     timeout: int = 15) -> dict:
    """真实 HTTP 薄封装（测试 monkeypatch 替换）。返回 {ok, payload|error, httpStatus}。"""
    import requests

    url = f"{FLASH_URL}?page={int(page)}&tag=&track=website&pagesize={int(pagesize)}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — 网络异常结构化，不伪造
        return {"ok": False, "error": f"ths_flash: {type(exc).__name__}: {exc}"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"ths_flash: HTTP {resp.status_code}"}
    try:
        return {"ok": True, "payload": json.loads(resp.text), "httpStatus": resp.status_code}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"ths_flash: json {exc}"}


def _parse_jsonish(value: object) -> list:
    """`stock`/`tag` 字段实测为 JSON 字符串（也可能已是 list/dict）；容错解析，失败返回空列表。"""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    s = str(value or "").strip()
    if not s:
        return []
    try:
        out = json.loads(s)
        if isinstance(out, list):
            return out
        return [out] if isinstance(out, dict) else []
    except json.JSONDecodeError:
        return []


def parse_flash_payload(payload: dict) -> dict:
    """响应 payload → {ok, items:[{id, seq, title, digest, ctimeEpoch, ctimeDate,
    ctimeHHMM, source, stocks:[{name, code}], tags:[...]}]}；形状异常结构化不伪造。"""
    data = (payload or {}).get("data") or {}
    rows = data.get("list")
    code = str((payload or {}).get("code") or "")
    if code != "200" or not isinstance(rows, list):
        return {"ok": False,
                "error": f"ths_flash: code={code or '缺失'} data.list 形状异常: {type(rows).__name__}",
                "items": []}
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ctime_epoch = int(str(row.get("ctime") or "").strip() or 0)
        except (TypeError, ValueError):
            ctime_epoch = 0
        if not ctime_epoch or not str(row.get("title") or "").strip():
            continue                     # 缺 ctime/标题的残条如实剔除（不伪造时间/标题）
        from datetime import datetime, timedelta, timezone
        _tz = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(ctime_epoch, _tz)
        stocks = [{"name": str(s.get("name") or ""), "code": str(s.get("stockCode") or "")}
                  for s in _parse_jsonish(row.get("stock")) if isinstance(s, dict) and s.get("name")]
        tags = [str(t.get("name") or "") if isinstance(t, dict) else str(t)
                for t in _parse_jsonish(row.get("tag"))]
        items.append({
            "id": str(row.get("id") or row.get("seq") or ""),
            "seq": str(row.get("seq") or ""),
            "title": str(row.get("title") or "").strip(),
            "digest": str(row.get("digest") or "").strip(),
            "ctimeEpoch": ctime_epoch,
            "ctimeDate": dt.strftime("%Y-%m-%d"),
            "ctimeHHMM": dt.strftime("%H:%M"),
            "source": str(row.get("source") or ""),
            "stocks": stocks,
            "tags": [t for t in tags if t],
        })
    return {"ok": True, "items": items}
