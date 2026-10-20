# -*- coding: utf-8 -*-
"""韭研「题材/事件」语料拉取层（L3 前瞻事件日历 + 板块级催化原文，2026-10-20）。

背景（用户提问「jev 能不能靠 jiuyan 的板块异动解析判题材」）：
`/action/field` 只给板块名/家数/名单 + 个股 expound，**没有板块级文本**。但同一套认证下
韭研另有三个端点携带题材语料（本模块只做拉取+解析，不落库）：

1. `/timeline/news {limit}` → **未来 1-3 日投资日历**（事件标题 + 内容）+ 当日「早报」事件清单：
     e.g. 2026-10-21「英伟达GTC大会：将在德国柏林举行，黄仁勋 21 日主题演讲…聚焦物理AI」
2. `/timeline/list {limit}` → 更宽的时间轴：已发生≈2 周 + **未发生≈2 周**，每条带
     `grade`（重要度 1-5）、`create_time`（录入时间→事件新近度）、`theme_list`（题材标签）
3. `/ai/industry/list {}` → AI 产业树：顶层板块 `group_name` + **板块级催化原文 `content`**
     + `hot`（热度）+ `update_time` + `children`（子行业，各自也有 content）

设计裁决（AGENTS §1.2-1/§4.0）：
- 单一事实源：题材语料只认韭研这三条端点，不接财联社/同花顺（多源会出"看着像催化"的口径漂移）；
- fail-visible：errCode 9=配额、1/110=鉴权失败，结构化返回；解析缺字段不伪造 0/空成功；
- 与异动采集共用认证链（`jiuyan_auth`），不新建凭据通道。
"""
from __future__ import annotations

import json

# 端点（POST，与 /action/field 同一 API_BASE）
PATH_TIMELINE_NEWS = "/timeline/news"
PATH_TIMELINE_LIST = "/timeline/list"
PATH_AI_INDUSTRY = "/ai/industry/list"


def api_post_json(url_path: str, body: dict, *, session_cookie: str, token: str,
                  timestamp: str, timeout: int = 20) -> tuple[int, str]:
    """真实 API 调用薄封装（测试 monkeypatch 替换）。返回 (http_status, text)。

    用 `requests` 而非 httpx：韭研 TLS 指纹会拒 httpx（SSL UNEXPECTED_EOF），与
    `jiuyan_fetch.api_post` 保持一致。
    """
    import requests

    from backend.operations.jiuyan_fetch import API_BASE, build_headers

    resp = requests.post(API_BASE + url_path, json=body,
                         headers=build_headers(session_cookie, token, timestamp), timeout=timeout)
    return resp.status_code, resp.text


def _errcode_error(payload: dict, what: str) -> dict | None:
    """统一 errCode → 结构化错误（None 表示可继续解析）。errCode 缺失按 0 处理（部分端点裸 payload）。

    errCode=9 的定性（2026-10-20 实测）：**短时限流**，不是日额度耗尽。证据：
    - 连发 6 次 `timeline/list` → 6 次全 9；静默 ~20 分钟后再发同一请求 → 成功返回完整数据；
    - 同时段异动端点（`/action/*`）errCode=0 —— 两套服务各自限流，不是同一计数；
    - 站方 msg = “非常抱歉！服务繁忙，请稍后再试！”（**不得据 msg 猜，只按 errCode 结构化**）。
    因此本层标 `rateLimited`（保留 `quota` 旧键兼容），由编排层串行 + 间隔 + 有限重试。
    """
    err = payload.get("errCode") if isinstance(payload, dict) else None
    if err in (0, "0", None):
        return None
    msg = payload.get("msg") or payload.get("message") or ""
    if str(err) == "9":
        return {"ok": False, "rateLimited": True, "quota": True, "authFailed": False,
                "error": f"{what}: errCode=9 限流/查阅受限({msg})"}
    return {"ok": False, "authFailed": str(err) in ("1", "110", "401"),
            "error": f"{what}: errCode={err} msg={msg}"}


# ── 解析（纯函数，可单测） ────────────────────────────────────────────────
def parse_timeline_news(payload: dict) -> dict:
    """`/timeline/news` → {ok, days:[{date, items:[{articleId,title,content}]}]}。

    data 形状不稳定（实测有时 list，有时 {msg,data:[...]}）：两种都接受，宁可如实空列表。
    """
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return {"ok": False, "error": f"timeline/news data 形状异常: {type(data).__name__}",
                "days": []}
    days = []
    for block in data:
        if not isinstance(block, dict):
            continue
        items = []
        for art in block.get("list") or []:
            if not isinstance(art, dict):
                continue
            items.append({
                "articleId": str(art.get("article_id") or ""),
                "title": (art.get("title") or "").strip(),
                "content": (art.get("content") or "").strip(),
            })
        days.append({"date": str(block.get("date") or ""), "items": items})
    return {"ok": True, "days": [d for d in days if d["date"]]}


def parse_timeline_list(payload: dict) -> dict:
    """`/timeline/list` → {ok, items:[{timelineId,articleId,date,title,content,grade,
    createTime,themes}]}（含**未来**日期 = 事件日历；grade/录入时间用于新近度判定）。"""
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return {"ok": False, "error": f"timeline/list data 形状异常: {type(data).__name__}",
                "items": []}
    out = []
    for block in data:
        if not isinstance(block, dict):
            continue
        date = str(block.get("date") or "")
        for art in block.get("list") or []:
            if not isinstance(art, dict):
                continue
            tl = art.get("timeline") or {}
            themes = [str(t.get("name") or t.get("title") or t)
                      for t in (tl.get("theme_list") or art.get("theme_list") or []) if t]
            grade = tl.get("grade")
            out.append({
                "timelineId": str(tl.get("timeline_id") or ""),
                "articleId": str(art.get("article_id") or ""),
                "date": str(tl.get("date") or date),
                "title": (art.get("title") or "").strip(),
                "content": (art.get("content") or "").strip(),
                "grade": grade if isinstance(grade, int) else None,
                "createTime": tl.get("create_time") or None,
                "themes": [t for t in themes if t],
            })
    return {"ok": True, "items": [it for it in out if it["date"] and it["title"]]}


def _walk_industry(node: dict, parent_code: str | None, parent_path: list[str],
                   out: list[dict]) -> None:
    """递归展平 `ai/industry/list`（children 可能是 dict/单元素/列表/缺失）。"""
    if not isinstance(node, dict):
        return
    code = str(node.get("code") or "")
    name = (node.get("group_name") or node.get("name") or "").strip()
    # children 里嵌套了「子节点本体」，直接用它的 code/name（实测：父项 children 是首个子的完整对象）
    kids = node.get("children")
    if isinstance(kids, dict):
        kids = [kids]
    if not isinstance(kids, list):
        kids = []
    level = node.get("level")
    path = parent_path + ([name] if name else [])
    if code or name:
        out.append({
            "code": code,
            "name": name,
            "level": level if isinstance(level, int) else None,
            "parentCode": parent_code,
            "path": path,
            "content": (node.get("content") or "").strip(),
            "hot": node.get("hot") if isinstance(node.get("hot"), (int, float)) else None,
            "updateTime": node.get("update_time") or node.get("updateTime") or None,
            "stockCount": node.get("stock_count") if isinstance(node.get("stock_count"), int) else None,
        })
    for kid in kids:
        kid_code = str((kid or {}).get("code") or "") if isinstance(kid, dict) else ""
        if kid_code and kid_code == code:      # 自身重复包裹，避免死循环
            continue
        _walk_industry(kid, code or parent_code, path, out)


def parse_ai_industry(payload: dict) -> dict:
    """`/ai/industry/list` → {ok, nodes:[{code,name,level,parentCode,path,content,hot,...}]}。"""
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return {"ok": False, "error": f"ai/industry/list data 形状异常: {type(data).__name__}",
                "nodes": []}
    nodes: list[dict] = []
    for top in data:
        _walk_industry(top, None, [], nodes)
    seen: set[str] = set()
    uniq = []
    for n in nodes:
        key = n["code"] or f"{n['name']}@{n['level']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)
    return {"ok": True, "nodes": uniq}


def parse_timeline_news_response(payload: dict) -> dict:
    """`/timeline/news` 完整响应 → 解析结果 + errCode 结构化错误。"""
    err = _errcode_error(payload, "timeline/news")
    if err:
        return {**err, "days": []}
    return parse_timeline_news(payload)


def parse_timeline_list_response(payload: dict) -> dict:
    err = _errcode_error(payload, "timeline/list")
    if err:
        return {**err, "items": []}
    return parse_timeline_list(payload)


def parse_ai_industry_response(payload: dict) -> dict:
    err = _errcode_error(payload, "ai/industry/list")
    if err:
        return {**err, "nodes": []}
    return parse_ai_industry(payload)


# ── 拉取（网络层；测试 mock api_post_json） ───────────────────────────────
def _fetch(path: str, body: dict, *, session_cookie: str, token: str, timestamp: str,
           parser, what: str) -> dict:
    status, text = api_post_json(path, body, session_cookie=session_cookie, token=token,
                                 timestamp=timestamp)
    if status != 200:
        return {"ok": False, "authFailed": False, "error": f"{what}: HTTP {status}"}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"ok": False, "authFailed": False, "error": f"{what}: json {exc}"}
    return parser(payload)


def fetch_timeline_news(*, session_cookie: str, token: str, timestamp: str,
                        limit: int = 20) -> dict:
    return _fetch(PATH_TIMELINE_NEWS, {"limit": limit}, session_cookie=session_cookie,
                  token=token, timestamp=timestamp, parser=parse_timeline_news_response,
                  what="timeline/news")


def fetch_timeline_list(*, session_cookie: str, token: str, timestamp: str,
                        limit: int = 60) -> dict:
    return _fetch(PATH_TIMELINE_LIST, {"limit": limit}, session_cookie=session_cookie,
                  token=token, timestamp=timestamp, parser=parse_timeline_list_response,
                  what="timeline/list")


def fetch_ai_industry(*, session_cookie: str, token: str, timestamp: str) -> dict:
    return _fetch(PATH_AI_INDUSTRY, {}, session_cookie=session_cookie, token=token,
                  timestamp=timestamp, parser=parse_ai_industry_response,
                  what="ai/industry/list")
