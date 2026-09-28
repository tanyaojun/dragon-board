# -*- coding: utf-8 -*-
"""微信「个股信息差」（飞火挖掘社）爬取入库：搜狗发现 → 抓文章 → 解析 → 匹配代码 → stock_info_diff。

来源：用户提供的补充信息源（个股信息差系列，日更，正文为个股业务/催化描述）。
存储：独立日级集合 stock_info_diff（_id={date}:{code}，unmatched 用 {date}:un:{idx}），
      meta 文档 _id={date}:_meta 存抓取状态与原文——stock_rows 不动（槽级快照 + Supabase 同构契约）。
fail-visible：解析/匹配/发现每步失败都落 meta 状态，不静默；代码无法匹配的条目保留 unmatched。
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://weixin.sogou.com/"}
SOURCE_NAME = "飞火挖掘社"
SEARCH_QUERY = "个股信息差 飞火挖掘社"


def fetch_html(url: str, timeout: int = 30, opener=None) -> str:
    req = urllib.request.Request(url, headers=UA)
    src = opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)
    return src.read().decode("utf-8", "ignore")


def article_text(html: str) -> str:
    m = re.search(r'id="js_content"(.*?)</div>\s*<script', html, re.S)
    body = m.group(1) if m else html
    text = re.sub(r"<[^>]+>", "\n", body)
    text = re.sub(r"&nbsp;?", " ", text)
    return "\n".join(l.strip() for l in text.split("\n") if l.strip())


def parse_info_diff_entries(text: str, known_names: set[str] | None = None) -> list[dict]:
    """解析「个股信息差」段：按 N、 分条，条内首段"名称：描述"。

    子编号陷阱：条目描述内部常带"1、…2、…"小点——用"候选名是否像股票名"
    （在 known_names 中，或短且无顿号/句号）区分顶层条目与子条目，子条目并入上一条。
    """
    idx = text.find("个股信息差")
    if idx < 0:
        return []
    seg = text[idx + len("个股信息差"):]
    parts = re.split(r"(?:^|\n)\s*(\d{1,2})、", seg)
    known = known_names or set()
    entries: list[dict] = []
    # parts = [前导, 序号, 内容, 序号, 内容, ...]
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1].strip()
        if not body:
            continue
        m = re.match(r"([^：\n]{2,12})：", body)
        is_new = False
        if m:
            candidate = m.group(1).strip()
            is_new = (candidate in known
                      or ("、" not in candidate and "。" not in candidate and len(candidate) <= 8))
        if is_new and m:
            entries.append({"name": m.group(1).strip(),
                            "reason": re.sub(r"\s+", "", body[m.end():]).lstrip("；")[:600]})
        elif entries and entries[-1]["reason"] is not None:
            prev = entries[-1]
            prev["reason"] = (prev["reason"] + "；" + re.sub(r"\s+", "", body).lstrip("；"))[:600]
    return entries


def pick_latest_discovery(html: str) -> dict | None:
    """从搜狗文章搜索页选标题日期最新的条目：标题形如 '9.23个股信息差(...)'。"""
    items = re.findall(r'<a[^>]+href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', html, re.S)
    best = None
    for href, title_html in items:
        title = re.sub(r"<[^>]+>", "", title_html)
        m = re.search(r"(\d{1,2})\.(\d{1,2})个股信息差", title)
        if not m:
            continue
        key = (int(m.group(1)), int(m.group(2)))
        if best is None or key > best["key"]:
            best = {"key": key, "title": title.strip(), "href": href}
    if not best:
        return None
    return {"title": best["title"],
            "href": "https://weixin.sogou.com" + best["href"].replace("&amp;", "&"),
            "month": best["key"][0], "day": best["key"][1]}


def resolve_sogou_link(opener, href: str) -> str:
    """搜狗 /link 页 → JS 片段拼接出真实 mp.weixin URL。"""
    clean = "".join(ch for ch in href.replace("&amp;", "&") if ch.isprintable())
    url = "https://weixin.sogou.com" + urllib.parse.quote(clean, safe="/?=&%")
    body = opener.open(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")
    if "mp.weixin.qq.com" in body:
        m = re.search(r'window\.location\.replace\("([^"]+)"\)', body)
        if m:
            return m.group(1)
    frags = re.findall(r"\+=\s*'([^']*)'", body) or re.findall(r'\+=\s*"([^"]*)"', body)
    if frags:
        joined = "".join(frags)
        if joined.startswith("http"):
            return joined
    raise RuntimeError("sogou /link 解析失败（反爬或页面变更）")


def discover_latest_article() -> tuple[str, str]:
    """搜狗文章搜索 → 最新一篇的 (url, title)。反爬/验证码时抛错（降级手动 --url）。"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    q = urllib.parse.quote(SEARCH_QUERY)
    html = opener.open(urllib.request.Request(
        f"https://weixin.sogou.com/weixin?type=2&query={q}", headers=UA), timeout=30).read().decode("utf-8", "ignore")
    if "antispider" in html.lower() or "验证码" in html:
        raise RuntimeError("sogou 反爬拦截（验证码），降级手动 --url")
    best = pick_latest_discovery(html)
    if not best:
        raise RuntimeError("搜狗结果中未找到带日期的个股信息差条目")
    url = resolve_sogou_link(opener, best["href"])
    return url, best["title"]
