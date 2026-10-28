# -*- coding: utf-8 -*-
"""市场历史读口服务：大盘指数（沪/深/创）历史收盘 + 全市场涨跌家数历史。

背景（2026-10-28）：工作台 KPL 行情 KPI 条历史模式此前涨跌家数/大盘指数显 "--"
（无历史来源）。本服务补齐：
- 指数历史：腾讯 ifzq 日 K（web.ifzq.gtimg.cn，实测可用），pct 自前收盘计算；
- 涨跌家数历史：东财 push2ex 涨跌分布仅返回最近完成交易日（无历史日期参数，实测），
  故落本地逐日持久化（quant-board/data/market_breadth_daily.json，gitignored 本地状态），
  自上线起累积；更早日期结构化缺数（fail-visible），不伪装。

纪律：httpx 一律 trust_env=False；测试全 mock 零真实网络；历史收盘不可变用长 TTL，
当日值短 TTL。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BREADTH_STORE = DATA_DIR / "market_breadth_daily.json"

INDEX_CODES = [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指")]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_PUSH2EX = ("https://push2ex.eastmoney.com/getTopicZDFenBu"
            "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt")

_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()


class MarketHistoryError(Exception):
    """结构化错误（fail-visible）：payload 透出给前端，不伪装空数据。"""

    def __init__(self, reason: str, **detail: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail

    def to_payload(self) -> Dict[str, Any]:
        return {"ok": False, "reason": self.reason, **self.detail}


def _cached(key: str, ttl_s: float) -> Optional[Any]:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl_s:
        return hit[1]
    return None


def _store(key: str, value: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


def _iso(date_str: str) -> Optional[_date]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ── 涨跌家数持久化（本地文件，gitignored data/）────────────────────────────

def _load_breadth_store() -> Dict[str, Any]:
    try:
        return json.loads(BREADTH_STORE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"days": {}}
    except Exception as exc:  # 损坏文件不静默吞掉整条链路
        raise MarketHistoryError("breadth_store_corrupted", error=str(exc))


def _save_breadth_store(store: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BREADTH_STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(BREADTH_STORE)


def _fenbu_sums(fenbu: List[Dict[str, int]]) -> Dict[str, int]:
    """东财分桶（键=涨跌幅%整数，负=跌/0=平/正=涨）→ 涨/跌/平家数合计。"""
    rise = down = flat = 0
    for bucket in fenbu or []:
        for key, count in bucket.items():
            try:
                pct = int(key)
            except (TypeError, ValueError):
                continue
            if pct > 0:
                rise += int(count)
            elif pct < 0:
                down += int(count)
            else:
                flat += int(count)
    return {"rise": rise, "down": down, "flat": flat}


def _fetch_push2ex_breadth() -> Dict[str, Any]:
    """东财 push2ex 涨跌分布（仅最近完成交易日，无历史日期参数——实测 2026-10-28）。"""
    resp = httpx.get(_PUSH2EX, headers={"User-Agent": _UA,
                                        "Referer": "https://quote.eastmoney.com/ztb/detail"},
                     trust_env=False, timeout=15)
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    fenbu = data.get("fenbu") or []
    qdate = str(data.get("qdate") or "")
    if not qdate or not fenbu:
        raise MarketHistoryError("upstream_empty_fenbu")
    qdate_iso = f"{qdate[:4]}-{qdate[4:6]}-{qdate[6:8]}"
    return {"date": qdate_iso, **_fenbu_sums(fenbu), "source": "eastmoney_push2ex"}


def get_breadth_history(date_str: str) -> Dict[str, Any]:
    """按日取全市场涨跌家数。命中本地累积库直接返回；目标日新于已累积末日时实时拉
    东财（仅最近完成交易日可得）并落库；更早未累积日期结构化缺数（fail-visible）。"""
    d = _iso(date_str)
    if d is None:
        raise MarketHistoryError("invalid_date", date=date_str)
    store = _load_breadth_store()
    days = store.setdefault("days", {})
    hit = days.get(date_str)
    if hit:
        return {"ok": True, **hit}
    latest = max(days) if days else None
    if latest is None or date_str > latest:
        # 目标日新于已累积末日 → 可能=上游最新可得日；55s 节流防页面轮询打爆上游
        live_cached = _cached("breadthlive", 55.0)
        live = live_cached or _fetch_push2ex_breadth()
        _store("breadthlive", live)
        if live["date"] not in days:
            days[live["date"]] = {
                k: live[k] for k in ("date", "rise", "down", "flat", "source")}
            days[live["date"]]["captured_at"] = datetime.now().isoformat(timespec="seconds")
            _save_breadth_store(store)
            days = store["days"]
        if live["date"] == date_str:
            return {"ok": True, **live}
        latest = max(latest or "", live["date"])
    raise MarketHistoryError(
        "breadth_history_not_accumulated", date=date_str,
        latest_available=latest,
        note=(f"东财涨跌分布仅提供最近交易日（{latest}，已落库）；"
              f"{date_str} 未在本地累积期内，暂无历史来源——持续逐日累积中"))


# ── 大盘指数历史（腾讯 ifzq 日 K）────────────────────────────────────────

def _fetch_tencent_kline(code: str, start: str, end: str) -> List[List[str]]:
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={code},day,{start},{end},20,qfq")
    resp = httpx.get(url, headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"},
                     trust_env=False, timeout=15)
    resp.raise_for_status()
    node = ((resp.json() or {}).get("data") or {}).get(code) or {}
    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        raise MarketHistoryError("upstream_empty_kline", code=code)
    return rows  # [date, open, close, high, low, volume, ...]


def get_index_history(date_str: str) -> Dict[str, Any]:
    """按日取沪/深/创收盘与涨跌幅（自前收盘计算；必须用不复权口径内的原始收盘序列）。"""
    d = _iso(date_str)
    if d is None:
        raise MarketHistoryError("invalid_date", date=date_str)
    ttl = 60.0 if d >= _date.today() else 6 * 3600.0   # 历史收盘不可变，当日值短 TTL
    key = f"idxhist:{date_str}"
    cached = _cached(key, ttl)
    if cached is not None:
        return cached
    start = (d - timedelta(days=30)).strftime("%Y-%m-%d")
    end = d.strftime("%Y-%m-%d")
    items: List[Dict[str, Any]] = []
    for code, name in INDEX_CODES:
        rows = _fetch_tencent_kline(code, start, end)
        closes = {r[0]: float(r[2]) for r in rows if len(r) > 2}
        dates = sorted(closes)
        if date_str not in closes:
            raise MarketHistoryError("date_not_in_kline", code=code, date=date_str)
        idx = dates.index(date_str)
        close = closes[date_str]
        prev = closes[dates[idx - 1]] if idx > 0 else None
        pct = round((close / prev - 1) * 100, 2) if prev else None
        items.append({"code": code, "name": name, "close": close, "pct": pct})
    payload = {"ok": True, "date": date_str, "items": items,
               "source": "tencent_ifzq"}
    _store(key, payload)
    return payload


def get_service() -> "MarketHistoryService":
    return _SERVICE


class MarketHistoryService:
    """薄封装（路由层统一经服务入口，便于替换/测试）。"""

    def index_history(self, date_str: str) -> Dict[str, Any]:
        return get_index_history(date_str)

    def breadth_history(self, date_str: str) -> Dict[str, Any]:
        return get_breadth_history(date_str)


_SERVICE = MarketHistoryService()
