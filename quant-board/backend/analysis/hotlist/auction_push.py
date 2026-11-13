# -*- coding: utf-8 -*-
"""KPL 直播 09:15「竞价看龙头」推送解析（竞价龙头链 vA1 选龙单源，纯函数零 IO）。

单一事实源 = 直播归档 `kpl_live_daily.items`（parse_live_row 归一产物，含 stocks
[{code,name,pct}] 芯片）；本模块只做「条目筛选 + 板块归属解析」投影，不取数不落库。

板块归属算法（预登记 auction-leader-vA1 §4）：推送 comment 形如
「竞价看龙头：机器人中重科技；羊年概念东方海洋、澳洋健康；芯片天普股份；…」——
板块名与股名之间**无分隔符**，故以条目自身 stocks[].name 为锚、**最长全名优先**
消耗式匹配各「；」分段（防子串误配：「日出东方」先于「大东方」消耗），段内残差
前缀 = 板块候选名（digest.normalize_name 归一）；未匹配到任何股名的段 / 未出现在
任何段的股 → board=None 披露（不丢弃，fail-visible）。
"""
from __future__ import annotations

import re
import time
from typing import Any

from backend.analysis.hotlist import theme_event_digest as digest

AUCTION_PUSH_PREFIX = "竞价看龙头"
# 推送时点窗（含端点）：09:15 推送、09:25 竞价冻结前的修订条都收
PUSH_WINDOW_START = "09:15"
PUSH_WINDOW_END = "09:25"
_SEG_SPLIT = re.compile(r"[；;]")


def select_push_entries(items: list[dict] | None, date: str, *,
                        start: str = PUSH_WINDOW_START,
                        end: str = PUSH_WINDOW_END) -> list[dict]:
    """直播 items → 当日窗内「竞价看龙头」条目（ts 升序；多条修订全收）。"""
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        comment = str(it.get("comment") or "").strip()
        if not comment.startswith(AUCTION_PUSH_PREFIX):
            continue
        ts = it.get("ts")
        try:
            day = time.strftime("%Y-%m-%d", time.localtime(float(ts)))
        except (TypeError, ValueError):
            continue
        if day != str(date):
            continue
        hhmm = str(it.get("time") or "")
        if not (start <= hhmm <= end):
            continue
        out.append(it)
    out.sort(key=lambda r: r.get("ts") or 0)
    return out


def _match_names(segment: str, names: list[str]) -> list[tuple[int, str]]:
    """段内消耗式全名匹配（最长优先）：返回 (起始位置, 股名) 升序列表。"""
    consumed: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for name in names:                      # names 已按长度降序
        if not name:
            continue
        pos = 0
        while True:
            idx = segment.find(name, pos)
            if idx < 0:
                break
            end = idx + len(name)
            if any(not (end <= s or idx >= e) for s, e in consumed):
                pos = idx + 1               # 与已消耗区间重叠 → 跳过（防子串误配）
                continue
            consumed.append((idx, end))
            hits.append((idx, name))
            break                           # 每股名每段只认一次
    hits.sort(key=lambda kv: kv[0])
    return hits


def parse_auction_push(entries: list[dict] | None) -> dict[str, Any]:
    """推送条目 → roster 投影（entries 升序；同 code 跨条目取最新 ts 的 pct/board）。

    返回 {entries:[{time,comment,stocks:[{code,name,pct,board,boardRaw}]}],
          stocks:[{code,name,pct,board,boardRaw}]（union，最新优先）,
          parseState:{entryN, unmatchedSegments, unassignedCodes}}。
    零条目 → stocks=[] + parseState.entryN=0（调用方按缺席留痕，不伪造名单）。
    """
    out_entries: list[dict] = []
    by_code: dict[str, dict] = {}
    unmatched: list[str] = []
    for it in entries or []:
        comment = str(it.get("comment") or "").strip()
        stocks = [s for s in (it.get("stocks") or []) if isinstance(s, dict)]
        names = sorted({str(s.get("name") or "").strip() for s in stocks},
                       key=lambda n: (-len(n), n))   # 同长 tie 定序（跨进程稳定）
        body = comment[len(AUCTION_PUSH_PREFIX):].lstrip("：: ").strip()
        entry_stocks: list[dict] = []
        assigned: set[str] = set()
        for seg in _SEG_SPLIT.split(body):
            seg = seg.strip()
            if not seg:
                continue
            hits = _match_names(seg, names)
            if not hits:
                unmatched.append(seg)
                continue
            board_raw = seg[:hits[0][0]].strip(" ：:，,、")
            board = digest.normalize_name(board_raw) or None
            for _pos, name in hits:
                src = next((s for s in stocks
                            if str(s.get("name") or "").strip() == name), None)
                if src is None:
                    continue
                code = str(src.get("code") or "")[-6:]
                if not code:
                    continue
                assigned.add(code)
                entry_stocks.append({"code": code, "name": name,
                                     "pct": src.get("pct"),
                                     "board": board, "boardRaw": board_raw or None})
        for s in stocks:                    # 未出现在任何段的股 → board=None 披露
            code = str(s.get("code") or "")[-6:]
            if code and code not in assigned:
                entry_stocks.append({"code": code,
                                     "name": str(s.get("name") or "").strip(),
                                     "pct": s.get("pct"),
                                     "board": None, "boardRaw": None})
        out_entries.append({"time": it.get("time"), "comment": comment,
                            "stocks": entry_stocks})
        for s in entry_stocks:              # 最新 ts 优先（entries 升序遍历）
            prev = by_code.get(s["code"])
            if prev is None:
                by_code[s["code"]] = dict(s)
            else:
                if s["pct"] is not None:
                    prev["pct"] = s["pct"]   # 后到修订条缺 pct 不抹已知值
                if s["board"]:
                    prev["board"], prev["boardRaw"] = s["board"], s["boardRaw"]
    unassigned = sorted(c for c, s in by_code.items() if not s.get("board"))
    return {"entries": out_entries,
            "stocks": list(by_code.values()),
            "parseState": {"entryN": len(out_entries),
                           "unmatchedSegments": unmatched,
                           "unassignedCodes": unassigned}}