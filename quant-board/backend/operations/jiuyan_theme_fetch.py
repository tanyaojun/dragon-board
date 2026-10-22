# -*- coding: utf-8 -*-
"""韭研题材语料拉取层（仅剩产业树 `ai/industry/list`；2026-10-23 v4 换源后单源化）。

背景（用户提问「jev 能不能靠 jiuyan 的板块异动解析判题材」）：
`/action/field` 只给板块名/家数/名单 + 个股 expound，**没有板块级文本**。同一套认证下
韭研产业树端点携带板块级催化原文（本模块只做拉取+解析，不落库）：

- `/ai/industry/list {}` → AI 产业树：顶层板块 `group_name` + **板块级催化原文 `content`**
  + `hot`（热度）+ `update_time` + `children`（子行业，各自也有 content）

**事件层（日历/早报）已换源**：`timeline/news`、`timeline/list` 两端点随 2026-10-23
裁决（方案 A：事件层唯一权威源=开盘啦，`kpl_theme_fetch.py`）退役，采集与解析代码删除，
`jiuyan_timeline` 集合导出归档后 drop（data/backups/jiuyan_timeline-archive-20261023.jsonl）。
产业树无 KPL 对应物，保留。设计裁决（AGENTS §1.2-1/§4.0）：
- 单一事实源：事件语料只认开盘啦，产业树催化只认韭研（每类语料一个权威源）；
- fail-visible：errCode 9=配额、1/110=鉴权失败，结构化返回；解析缺字段不伪造 0/空成功；
- 与异动采集共用认证链（`jiuyan_auth`），不新建凭据通道。
"""
from __future__ import annotations

import json

# 端点（POST，与 /action/field 同一 API_BASE）
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


def fetch_ai_industry(*, session_cookie: str, token: str, timestamp: str) -> dict:
    return _fetch(PATH_AI_INDUSTRY, {}, session_cookie=session_cookie, token=token,
                  timestamp=timestamp, parser=parse_ai_industry_response,
                  what="ai/industry/list")
