"""东方财富 datacenter-web 龙虎榜个股席位明细（2026-10-30 用户解禁东财源）。

合同（README docs/kpl-socket §13.2 同步）：
- 上游：`https://datacenter-web.eastmoney.com/api/data/v1/get`
  - 个股上榜日期列表：reportName=RPT_DAILYBILLBOARD_DETAILSNEW
  - 买卖前 5 席位：RPT_BILLBOARD_DAILYDETAILSBUY / RPT_BILLBOARD_DAILYDETAILSSELL
    （sortColumns=BUY/SELL，必带 source=WEB & client=WEB，Referer=data.eastmoney.com）
- 金额单位=元（浮点原样）；占比字段 TOTAL_BUYRIO/TOTAL_SELLRIO 为 0-1 小数，归一为百分数。
- 同一票同日多个上榜原因按 TRADE_ID 多组返回，前端按 reason 透出。
- fail-visible：上游异常抛 LhbSeatUpstreamError，由路由层转结构化降级（不伪装空结果）。
- 测试禁止真实调用（monkeypatch client），TTL 缓存进程内。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EASTMONEY_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_LIST = "RPT_DAILYBILLBOARD_DETAILSNEW"
REPORT_BUY = "RPT_BILLBOARD_DAILYDETAILSBUY"
REPORT_SELL = "RPT_BILLBOARD_DAILYDETAILSSELL"

DATES_TTL_SECONDS = 600.0   # 上榜日期列表 10min
DETAIL_TTL_SECONDS = 1800.0  # 席位明细为盘后 EOD 数据 30min
CACHE_MAX_ENTRIES = 256

_HEADERS = {
    "Referer": "https://data.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}

_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LhbSeatParamError(ValueError):
    """code/date 参数非法。"""


class LhbSeatUpstreamError(RuntimeError):
    """上游请求或响应结构异常。"""


def normalize_lhb_code(code: str) -> str:
    c = str(code or "").strip()
    if c.upper().startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    if not _CODE_RE.match(c):
        raise LhbSeatParamError(f"code 非法（需 6 位数字）：{code!r}")
    return c


def normalize_lhb_date(date: str) -> str:
    d = str(date or "").strip().replace("/", "-")
    if not _DATE_RE.match(d):
        raise LhbSeatParamError(f"date 非法（需 YYYY-MM-DD）：{date!r}")
    return d


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None  # NaN → None


def _ratio_pct(value: Any) -> float | None:
    n = _num(value)
    return None if n is None else round(n * 100.0, 2)


def parse_seat_rows(items: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """BUY/SELL 报表行 → {rank,code,name,buy,sell,net,buy_ratio,sell_ratio,reason,trade_id}。

    side='buy' 按 BUY 降序（买入榜前5），side='sell' 按 SELL 降序。
    上游缺行/缺字段逐行容错，非数显 None（前端 '--'），不伪装 0。
    """
    sort_key = "buy" if side == "buy" else "sell"
    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        buy = _num(it.get("BUY"))
        sell = _num(it.get("SELL"))
        net = _num(it.get("NET"))
        if net is None and buy is not None and sell is not None:
            net = round(buy - sell, 2)
        rows.append(
            {
                "code": str(it.get("SECURITY_CODE") or "").strip() or None,
                "name": str(it.get("OPERATEDEPT_NAME") or "").strip() or None,
                "buy": buy,
                "sell": sell,
                "net": net,
                "buy_ratio": _ratio_pct(it.get("TOTAL_BUYRIO")),
                "sell_ratio": _ratio_pct(it.get("TOTAL_SELLRIO")),
                "reason": str(it.get("EXPLANATION") or "").strip() or None,
                "trade_id": str(it.get("TRADE_ID") or "").strip() or None,
            }
        )
    rows.sort(
        key=lambda r: (r[sort_key] if r[sort_key] is not None else float("-inf")),
        reverse=True,
    )
    # 同股同日多上榜原因（多 TRADE_ID）会重复返回同一席位行：按 (code, 营业部名) 去重，
    # 保证单股买卖榜各最多 5 行（同花顺/东财客户端展示口径）；全日场景同样防重
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in rows:
        key = (r["code"] or "") + "|" + (r["name"] or f"__anon_{len(deduped)}")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    rows = deduped
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def aggregate_by_stock(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全日席位行按股票聚合（买/卖各侧独立聚合，供左列表过滤与营业部反查）。"""
    acc: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r.get("code")
        if not code:
            continue
        a = acc.setdefault(code, {"code": code, "buy": 0.0, "sell": 0.0, "net": 0.0})
        if r["buy"] is not None:
            a["buy"] = round(a["buy"] + r["buy"], 2)
        if r["sell"] is not None:
            a["sell"] = round(a["sell"] + r["sell"], 2)
        if r["net"] is not None:
            a["net"] = round(a["net"] + r["net"], 2)
    return sorted(acc.values(), key=lambda x: x["buy"], reverse=True)


_BRANCH_STRIP = ("股份有限公司", "有限责任公司", "有限公司")


def normalize_branch_name(name: str) -> str:
    """营业部名归一：去公司后缀与「证券」，供 KPL/东财名称匹配（华泰证券总部↔华泰证券股份有限公司总部）。"""
    n = str(name or "").strip()
    for frag in _BRANCH_STRIP:
        n = n.replace(frag, "")
    return n.replace("证券", "").replace(" ", "")


def match_branch_rows(
    rows: list[dict[str, Any]], branch_name: str
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    """在全日席位行中匹配营业部：归一后相等优先，否则 difflib 相似度 ≥0.6 取最优。

    返回 (匹配到的东财全名, 该营业部全部行, 未命中时的候选名 top5)。
    """
    import difflib

    names = sorted({r["name"] for r in rows if r.get("name")})
    if not names:
        return None, [], []
    target = normalize_branch_name(branch_name)
    exact = [n for n in names if normalize_branch_name(n) == target]
    if exact:
        hit = exact[0]
        return hit, [r for r in rows if r["name"] == hit], []
    scored = sorted(
        ((difflib.SequenceMatcher(None, target, normalize_branch_name(n)).ratio(), n) for n in names),
        key=lambda x: x[0],
        reverse=True,
    )
    best_score, best = scored[0]
    if best_score >= 0.6:
        return best, [r for r in rows if r["name"] == best], []
    return None, [], [n for _, n in scored[:5]]


def parse_stock_dates(items: list[dict[str, Any]], code: str) -> dict[str, Any]:
    """RPT_DAILYBILLBOARD_DETAILSNEW 行 → {code,name,dates}，日期倒序去重。"""
    dates: list[str] = []
    name: str | None = None
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            dropped += 1
            continue
        raw = str(it.get("TRADE_DATE") or "")
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
        if not m:
            dropped += 1
            continue
        if not name:
            name = str(it.get("SECURITY_NAME_ABBR") or "").strip() or None
        if m.group(1) not in dates:
            dates.append(m.group(1))
    dates.sort(reverse=True)
    return {"code": code, "name": name, "dates": dates, "dropped": dropped}


class LhbSeatDetailService:
    """东财龙虎榜席位明细 + 上榜日期，进程内 TTL 缓存。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        dates_ttl: float = DATES_TTL_SECONDS,
        detail_ttl: float = DETAIL_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._dates_ttl = float(dates_ttl)
        self._detail_ttl = float(detail_ttl)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0, headers=_HEADERS)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _dc_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        client = await self._get_client()
        full = {
            "columns": "ALL",
            "pageNumber": 1,
            "pageSize": 500,
            "source": "WEB",
            "client": "WEB",
            **params,
        }
        try:
            resp = await client.get(EASTMONEY_DC_URL, params=full)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # httpx / json
            raise LhbSeatUpstreamError(f"东财 datacenter 请求失败：{exc}") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            msg = payload.get("message") if isinstance(payload, dict) else payload
            raise LhbSeatUpstreamError(f"东财 datacenter 返回异常：{msg}")
        result = payload.get("result") or {}
        data = result.get("data")
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]

    async def _dc_list_all(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """分页拉全（datacenter result.pages 驱动，上限 10 页防失控）。"""
        all_rows: list[dict[str, Any]] = []
        for page in range(1, 11):
            rows = await self._dc_list({**params, "pageNumber": page, "pageSize": 500})
            all_rows.extend(rows)
            if len(rows) < 500:
                break
        return all_rows

    @staticmethod
    def _cache_get(cache: dict[str, tuple[float, Any]], key: str, ttl: float) -> Any | None:
        hit = cache.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl:
            return hit[1]
        return None

    @staticmethod
    def _cache_put(cache: dict[str, tuple[float, Any]], key: str, value: Any) -> None:
        if len(cache) >= CACHE_MAX_ENTRIES:
            oldest = min(cache, key=lambda k: cache[k][0])
            cache.pop(oldest, None)
        cache[key] = (time.monotonic(), value)

    async def get_day_seats(self, date: str) -> dict[str, Any]:
        """全市场当日席位行（东财）：左列表净买入/总买卖增补与「席位榜」口径对照 +
        营业部反查数据底座（席位三态过滤已随读数入口修正删除，2026-10-30 用户裁决）。

        原始行与聚合结果同帧入缓存（day/dayrows 双 key），营业部反查不再二次打上游。
        """
        day = normalize_lhb_date(date)
        async with self._lock:
            cached = self._cache_get(self._cache, f"day:{day}", self._detail_ttl)
            if cached is not None:
                return cached
        # 上游拉取不持锁（code review P2）：冷启动多报表多页拉全可能超 ：8008 代理 20s 超时，
        # 不阻塞其它 key 的缓存命中；回锁后双检，并发重复拉取以先入者为准
        flt = f"(TRADE_DATE='{day}')"
        buy_items, sell_items, list_items = await asyncio.gather(
            self._dc_list_all(
                {"reportName": REPORT_BUY, "sortColumns": "BUY", "sortTypes": "-1", "filter": flt}
            ),
            self._dc_list_all(
                {"reportName": REPORT_SELL, "sortColumns": "SELL", "sortTypes": "-1", "filter": flt}
            ),
            self._dc_list_all(
                {"reportName": REPORT_LIST,
                 # 名单报表自带行情/原因列（2026-10-30 用户裁决补全字段）：收盘价/涨跌幅/
                 # 换手率/上榜原因（交易所口径），当日左列表 83 只全覆盖（3004 选股帧
                 # 只覆盖涨幅≥~5%，概念仍需 KPL 3004/2112）
                 "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,"
                            "CHANGE_RATE,TURNOVERRATE,EXPLANATION",
                 "sortColumns": "SECURITY_CODE", "sortTypes": "1", "filter": flt}
            ),
        )
        buy_rows = parse_seat_rows(buy_items, "buy")
        sell_rows = parse_seat_rows(sell_items, "sell")
        raw_rows = buy_rows + sell_rows
        # 证券名称来自当日上榜名单报表（席位报表本身不带名称）；同名多行去重；
        # 行情/原因字典同步提取（原样字符串不缩放，缺字段不键入——fail-visible）
        names: dict[str, str] = {}
        day_quotes: dict[str, dict[str, str]] = {}
        for it in list_items:
            code = str(it.get("SECURITY_CODE") or "").strip()
            nm = str(it.get("SECURITY_NAME_ABBR") or "").strip()
            if code and nm:
                names[code] = nm
            dq: dict[str, str] = {}
            for key, col in (("price", "CLOSE_PRICE"), ("zf", "CHANGE_RATE"),
                             ("tur", "TURNOVERRATE"), ("reason", "EXPLANATION")):
                v = it.get(col)
                if v not in (None, ""):
                    dq[key] = str(v)
            if code and dq:
                day_quotes[code] = dq
        stocks = aggregate_by_stock(raw_rows)
        for s in stocks:
            s["name"] = names.get(s["code"])
        out = {
            "ok": True,
            "date": day,
            "stocks": stocks,
            "names": names,
            "day_quotes": day_quotes,
            "branches": sorted({r["name"] for r in raw_rows if r.get("name")}),
            "upstream_counts": {"buy": len(buy_items), "sell": len(sell_items)},
        }
        async with self._lock:
            cached = self._cache_get(self._cache, f"day:{day}", self._detail_ttl)
            if cached is not None:
                return cached   # 并发重复拉取，以先入者为准
            if stocks:
                # 空日不入缓存（2026-10-30 回退裁决配套）：榜约 17:30 盘后生成，
                # 缓存空态会遮住刚生成的数据；回退探测由路由层 walk_back 负责
                self._cache_put(self._cache, f"day:{day}", out)
                self._cache_put(self._cache, f"dayrows:{day}", raw_rows)
        if not stocks:
            out = {**out, "note": ("该日期无上榜席位数据（盘前/盘中查当日属正常：榜约 17:30 "
                                   "盘后生成；非交易日亦空），非降级")}
        return out

    async def get_branch_seats(self, date: str, branch_name: str) -> dict[str, Any]:
        """营业部反查：按 KPL 营业部名匹配东财当日席位行，按股聚合买卖明细。"""
        if not str(branch_name or "").strip():
            raise LhbSeatParamError("branch 营业部名称不能为空")
        day = normalize_lhb_date(date)
        day_out = await self.get_day_seats(date)   # 确保全日行已拉取/缓存（同日命中缓存不再打上游）
        async with self._lock:
            raw_rows = self._cache_get(self._cache, f"dayrows:{day}", self._detail_ttl) or []
        matched, _rows, candidates = match_branch_rows(raw_rows, branch_name)
        names = day_out.get("names", {})
        buy, sell = aggregate_by_stock(_rows), aggregate_by_stock(_rows)
        for grp in (buy, sell):
            for x in grp:
                x["name"] = names.get(x["code"])
        buy = sorted((x for x in buy if x["buy"] > 0), key=lambda x: x["buy"], reverse=True)
        sell = sorted((x for x in sell if x["sell"] > 0), key=lambda x: x["sell"], reverse=True)
        return {
            "ok": True,
            "date": day,
            "name": branch_name,
            "matched": matched,
            "candidates": candidates,
            "buy": buy,
            "sell": sell,
        }

    async def get_seat_dates(self, code: str) -> dict[str, Any]:
        norm = normalize_lhb_code(code)
        async with self._lock:
            cached = self._cache_get(self._cache, f"dates:{norm}", self._dates_ttl)
            if cached is not None:
                return cached
        items = await self._dc_list(   # 上游拉取不持锁（同 get_day_seats）
            {
                "reportName": REPORT_LIST,
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "pageSize": 120,
                "filter": f'(SECURITY_CODE="{norm}")',
            }
        )
        out = parse_stock_dates(items, norm)
        async with self._lock:
            cached = self._cache_get(self._cache, f"dates:{norm}", self._dates_ttl)
            if cached is not None:
                return cached
            self._cache_put(self._cache, f"dates:{norm}", out)
        return out

    async def get_seat_detail(self, code: str, date: str) -> dict[str, Any]:
        norm = normalize_lhb_code(code)
        day = normalize_lhb_date(date)
        async with self._lock:
            cached = self._cache_get(self._cache, f"detail:{norm}:{day}", self._detail_ttl)
            if cached is not None:
                return cached
        flt = f"(SECURITY_CODE=\"{norm}\")(TRADE_DATE='{day}')"
        buy_items, sell_items = await asyncio.gather(   # 上游拉取不持锁（同 get_day_seats）
            self._dc_list(
                {
                    "reportName": REPORT_BUY,
                    "sortColumns": "BUY",
                    "sortTypes": "-1",
                    "filter": flt,
                }
            ),
            self._dc_list(
                {
                    "reportName": REPORT_SELL,
                    "sortColumns": "SELL",
                    "sortTypes": "-1",
                    "filter": flt,
                }
            ),
        )
        out = {
            "ok": True,
            "code": norm,
            "date": day,
            "buy": parse_seat_rows(buy_items, "buy"),
            "sell": parse_seat_rows(sell_items, "sell"),
            "upstream_counts": {"buy": len(buy_items), "sell": len(sell_items)},
        }
        async with self._lock:
            cached = self._cache_get(self._cache, f"detail:{norm}:{day}", self._detail_ttl)
            if cached is not None:
                return cached
            self._cache_put(self._cache, f"detail:{norm}:{day}", out)
        return out


_service: LhbSeatDetailService | None = None


def get_lhb_seat_service() -> LhbSeatDetailService:
    global _service
    if _service is None:
        _service = LhbSeatDetailService()
    return _service


async def close_lhb_seat_service() -> None:
    global _service
    if _service is not None:
        await _service.close()
        _service = None
