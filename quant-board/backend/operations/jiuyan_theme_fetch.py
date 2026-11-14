# -*- coding: utf-8 -*-
"""韭研题材语料拉取层（产业树 `ai/industry/list` + 全成分树 `stock-tree` + 早报 `timeline/news`）。

背景（用户提问「jev 能不能靠 jiuyan 的板块异动解析判题材」）：
`/action/field` 只给板块名/家数/名单 + 个股 expound，**没有板块级文本**。同一套认证下
韭研产业树端点携带板块级催化原文（本模块只做拉取+解析，不落库）：

- `/ai/industry/list {}` → AI 产业树：顶层板块 `group_name` + **板块级催化原文 `content`**
  + `hot`（热度）+ `update_time` + `children`（子行业，各自也有 content）
- `/timeline/news {limit}` → 当日「早报」+ 未来 1-3 日日历（2026-11-14 晨间例外复活：
  只恢复早报单端点、只供 09:26 竞价链晨间窗消费；`timeline/list` 日历不恢复——KPL 日历
  是超集，复活即双轨；裁决见 auction-preopen-catalyst-preregistration-20261114.md §0，
  2026-10-23 退役依据见 theme-corpus-extra-sources-survey-20261023.md §8，
  原 `jiuyan_timeline` 集合已 drop 不复活）。

设计裁决（AGENTS §1.2-1/§4.0）：
- 单一事实源：事件语料只认开盘啦，产业树催化只认韭研（每类语料一个权威源）；
  早报为独立语料类型（人工隔夜汇总），晨间窗专属源（不融进事件层）；
- fail-visible：errCode 9=短时限流、1/110=鉴权失败，结构化返回；解析缺字段不伪造 0/空成功；
- 与异动采集共用认证链（`jiuyan_auth`），不新建凭据通道。
"""
from __future__ import annotations

import json
import re

# 端点（POST，与 /action/field 同一 API_BASE）
PATH_AI_INDUSTRY = "/ai/industry/list"
# 全成分树（V3-1，2026-10-25 实测定形：GET 被 405 拒「请求方式错误」,不是用GET」，
# POST body {"code": 一级code} → errCode=0 data=该产业全树，成分挂各级节点 stock_list[]）
PATH_STOCK_TREE = "/ai/industry/stock-tree"
# 早报端点（2026-11-14 晨间例外复活，只恢复早报/不复活 timeline_list 日历——KPL 日历是超集，
# 见 auction-preopen-catalyst-preregistration-20261114.md §0；原 2026-10-23 退役归档于
# theme-corpus-extra-sources-survey-20261023.md §8）
PATH_TIMELINE_NEWS = "/timeline/news"


def normalize_stock_code(raw: object) -> str:
    """sz300454/sh600519 → 6 位纯数字（与 sector 链 code 同型）；非 6 位数字返回 ''（剔）。"""
    s = str(raw or "").strip().lower()
    for p in ("sz", "sh", "bj"):
        if s.startswith(p):
            s = s[len(p):]
            break
    return s if len(s) == 6 and s.isdigit() else ""


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


# ── 全成分树（V3-1：板块节点三期全成分增强） ──────────────────────────────
def parse_stock_tree(payload: dict) -> dict:
    """`/ai/industry/stock-tree` 响应 → {ok, root}；root = 一级节点全树原样（审计用）。"""
    err = _errcode_error(payload, "ai/industry/stock-tree")
    if err:
        return {**err, "root": None}
    data = (payload or {}).get("data")
    if not isinstance(data, dict) or not (data.get("code") or data.get("name")):
        return {"ok": False, "error": f"stock-tree data 形状异常: {type(data).__name__}",
                "root": None}
    return {"ok": True, "root": data}


def flatten_stock_tree(root: dict) -> dict:
    """全树展平为一级产业成分集（V3 预登记 §成分口径=全量纳入+披露强度）。

    同股多节点出现取 shares_range 最高的人次（关联最强口径）；leafPath 记该人次
    挂的叶子路径（审计「这只股为什么在这」）；非 6 位 code 剔除并计入 invalidN。
    """
    industry = {"code": str(root.get("code") or ""),
                "name": (root.get("name") or root.get("group_name") or "").strip()}
    best: dict[str, dict] = {}
    invalid = 0

    def _walk(node: dict, path: list[str]) -> None:
        nonlocal invalid
        if not isinstance(node, dict):
            return
        seg = str(node.get("name") or node.get("group_name") or "").strip()
        p = path + ([seg] if seg else [])
        for s in node.get("stock_list") or []:
            if not isinstance(s, dict):
                continue
            code = normalize_stock_code(s.get("stock_code"))
            if not code:
                invalid += 1
                continue
            shares = s.get("shares_range")
            shares = float(shares) if isinstance(shares, (int, float)) else None
            cur = best.get(code)
            if cur is not None and (shares is None or (cur.get("sharesRange") or -1.0) >= shares):
                continue
            best[code] = {
                "code": code,
                "name": str(s.get("stock_name") or "").strip(),
                "sharesRange": shares,
                "exaggeratedCount": int(s.get("exaggerated_count") or 0),
                "isShares": bool(s.get("is_shares")),
                "content": str(s.get("content") or "").strip(),
                "leafPath": "/".join(p),
            }
        for kid in node.get("children") or []:
            _walk(kid, p)

    _walk(root, [])
    return {**industry, "stocks": [best[c] for c in sorted(best)], "invalidN": invalid}


def parse_timeline_news(payload: dict) -> dict:
    """`/timeline/news` → {ok, days:[{date, items:[{articleId,title,content}]}]}。

    data 形状不稳定（实测有时 list，有时 {msg,data:[...]}）：两种都接受，宁可如实空列表
    （代码自 git 3fde9716 恢复，2026-11-14 晨间例外）。
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


def parse_timeline_news_response(payload: dict) -> dict:
    """`/timeline/news` 完整响应 → 解析结果 + errCode 结构化错误。"""
    err = _errcode_error(payload, "timeline/news")
    if err:
        return {**err, "days": []}
    return parse_timeline_news(payload)


def fetch_timeline_news(*, session_cookie: str, token: str, timestamp: str,
                        limit: int = 20) -> dict:
    """拉早报+未来 1-3 日投资日历（当日早报项由 is_briefing 语义在上层筛选）。"""
    return _fetch(PATH_TIMELINE_NEWS, {"limit": limit}, session_cookie=session_cookie,
                  token=token, timestamp=timestamp, parser=parse_timeline_news_response,
                  what="timeline/news")


# ── 早报识别/切段（纯函数；v3 语义自 git 3fde9716 恢复，2026-11-14 晨间例外）──

# 当日事件清单（早报/复盘）而非既定日程；盘前链只认早报/盘前必读两类（复盘/收盘必读
# 是 T 日盘后产物，对 09:26 晨间窗是前视，不收）。
BRIEFING_TITLES = ("早报", "盘前必读")


def is_briefing(item: dict) -> bool:
    """当日事件清单（早报）而非既定日程：标题在名单内，或正文以「1、热点事件」开头。"""
    title = str((item or {}).get("title") or "").strip()
    content = str((item or {}).get("content") or "").strip()
    return title in BRIEFING_TITLES or content.startswith("1、热点事件")


def extract_briefing(days: list[dict], date: str) -> dict | None:
    """timeline/news days → 当日（`date`）早报项；无当日块/无早报项 → None（=not_published）。"""
    for day in days or []:
        if str(day.get("date") or "") != str(date or ""):
            continue
        for it in day.get("items") or []:
            if is_briefing(it):
                return it
    return None


def split_briefing_paragraphs(content: str) -> list[str]:
    """早报正文 → 题材归因短句段：按「N）」/「N、」编号行切，段内续行归并；
    空段丢弃，顺序保留（纯文本变换，无判读）。"""
    out: list[str] = []
    cur: list[str] = []
    for raw in str(content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\d+[）)、]", line):
            if cur:
                out.append("".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        out.append("".join(cur))
    return [p for p in out if p.strip()]


def fetch_industry_stock_tree(code: str, *, session_cookie: str, token: str,
                              timestamp: str) -> dict:
    """拉单个一级产业全成分树。返回 {ok, root, industry}（industry=展平成分集）。"""
    res = _fetch(PATH_STOCK_TREE, {"code": str(code)}, session_cookie=session_cookie,
                 token=token, timestamp=timestamp, parser=parse_stock_tree,
                 what=f"stock-tree[{code}]")
    if res.get("ok"):
        res["industry"] = flatten_stock_tree(res["root"])
    return res
