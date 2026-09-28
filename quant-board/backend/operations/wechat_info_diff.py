# -*- coding: utf-8 -*-
"""微信「个股信息差」（飞火挖掘社）抓取与解析。

数据流：搜狗微信文章搜索发现最新一篇（或手动 URL）→ 抓取正文 → 解析个股条目
→ 由调用方（wechat_info_diff_ingest）匹配代码并更新 theme_stock_mappings.stockReason。
不建任何新集合；本模块不做 IO 落库。
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Referer": "https://weixin.sogou.com/"}
SOURCE_NAME = "飞火挖掘社"
SEARCH_QUERY = "个股信息差 飞火挖掘社"


def title_month_day(title: str) -> tuple[int, int] | None:
    """标题里的系列日期（'9.28个股信息差'）→ (月, 日)；无则 None。"""
    m = re.search(r"(\d{1,2})\.(\d{1,2})个股信息差", title or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


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

    子编号陷阱：描述内部常带"1、…2、…"小点——用"候选名是否像股票名"（在
    known_names 中，或短且无顿号/句号）区分顶层条目与子条目，子条目并入上一条。
    """
    idx = text.find("个股信息差")
    if idx < 0:
        return []
    seg = text[idx + len("个股信息差"):]
    parts = re.split(r"(?:^|\n)\s*(\d{1,2})、", seg)
    known = known_names or set()
    entries: list[dict] = []
    for i in range(1, len(parts) - 1, 2):
        body = re.sub(r"\s+", "", parts[i + 1])
        if not body:
            continue
        m = re.match(r"([^：\n]{2,12})：", body)
        candidate = m.group(1).strip() if m else ""
        is_new = bool(candidate) and (candidate in known
                                      or ("、" not in candidate and "。" not in candidate and len(candidate) <= 8))
        if is_new:
            entries.append({"name": candidate, "reason": body[m.end():].lstrip("；")[:600]})
        elif entries:
            prev = entries[-1]
            prev["reason"] = (prev["reason"] + "；" + body.lstrip("；"))[:600]
    return entries


def pick_latest_discovery(html: str) -> dict | None:
    """从搜狗文章搜索页选标题日期最新的条目：标题形如 '9.23个股信息差(...)'。"""
    items = re.findall(r'<a[^>]+href="(/link\?url=[^"]+)"[^>]*>(.*?)</a>', html, re.S)
    best = None
    for href, title_html in items:
        title = re.sub(r"<[^>]+>", "", title_html)
        md = title_month_day(title)
        if not md:
            continue
        if best is None or md > best["md"]:
            best = {"md": md, "title": title.strip(), "href": href}
    if not best:
        return None
    return {"title": best["title"],
            "href": "https://weixin.sogou.com" + best["href"].replace("&amp;", "&"),
            "month": best["md"][0], "day": best["md"][1]}


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
