# -*- coding: utf-8 -*-
"""全市场跌停家数源（东财跌停池主 + 行情快照兜底，2026-10-16 口径修正）。

背景（预登记 docs/hotlist-jev/jev-relay-caliber-fix-preregistration.md §2.3）：10-15 语料
「跌停 6 家」取自 snapshot_stock_rows 的 250 只**采集池**，全市场实际 26 家，趋势同时被
扭曲（真实 10-13/14/15=8/11/26 家 vs 池内口径）。本模块给叙事链提供全市场口径。

**双源选型（用户 2026-10-16 裁决）**：
- **主源**：东财跌停股池 `push2ex.eastmoney.com/getTopicDTPool`（quote.eastmoney.com
  涨停板行情-跌停股池同源，akshare `stock_zt_pool_dtgc_em` 的底层端点）。有历史
  （近 30 自然日窗口）、权威、与涨停/炸板池同族同口径。
- **兜底**：market_proxy 全市场行情快照（`MarketQuotesCache` 的 Redis 共享层，腾讯源
  ~5500 行，f3=涨跌幅%），判定走 `core/limit_rules.is_limit_down_pct`（板块阈值自算，
  与 dieban_count 同一条权威线，不写第二份阈值副本）。无上游 IP 风险，但只服务「当日」。
- **末位降级**：采集池口径（250 只），叙事内显式标注「全市场源缺失」。

**不走 akshare 的原因**：`stock_zt_pool_dtgc_em` 内部是裸 `requests.get`——无节流、无
Referer、无会话复用。skills/a-stock-data/SKILL.md「东财防封」铁律（2026-06-30 实测案例：
1 小时 45000 请求不走限流 → push2/push2his 全系列断连、IP 级封禁 20+ 小时）下这是不可
接受的暴露面。故本项目直连端点并套用 eastmoney_fund_provider 同款纪律：
串行最小间隔 + 随机抖动、Keep-Alive 连接复用、UA+Referer 注入、429/403 立即熔断不重试。

**EM 窗口边界**：`date < 今天-30 自然日` 直接判不可用且不外呼。EM 对窗口外日期只返 0 行，
与「当日真的 0 家」在响应上无法区分——把窗口外伪成 0 家会成片污染分位数（AGENTS §4.0：
「取不到」与「真的 0」是两件事）。**窗口内空池也必须由 EM 显式自报 `tc == 0` 才认合法 0**：
限流/软拦截同样会返 HTTP 200 + 空池（2026-10-20 review major：这是唯一能落成「零披露伪 0」
的通路），未自报 0 的空池一律判不可用（可降级到行情快照/本地日线，不伪 0）。

**实时口径边界**：行情快照 TTL 300s、每 5 分钟刷新，只服务「当日」叙事；历史日不走此路，
回退采集池口径并显式标注——不拿实时快照冒充历史日收盘（fail-visible）。

懒加载只在「当日 + 已过收盘截点」发生（1 次/日）；历史日一律只读参考集合，由 `backfill`
显式回填（防一次叙事 20 连发外呼）。

fail-visible：任何一步取不到都不写成 0。
- `fetch_limit_down_em(date)`：东财跌停池家数；窗口外/熔断/异常/坏负载 → None。
- `full_market_dieban_from_quotes()`：读 Redis 行情快照统计全市场跌停；不可用 → None。
- `limit_down_count(db, date, dataset_id, allow_fetch)`：(count, source)，source ∈
  {em_pool, quotes_snapshot, tdx_local_bars, pool_rows, missing}。当日 miss 且 allow_fetch 且已过收盘截点
  → EM → 快照 → upsert 懒加载再读；历史日只读参考集合；全无 → 采集池降级/missing。
- `reference_counts(db, dates, source)`：参考集合批量同源读（一次 find，禁逐日连发）。
- `backfill(db, start, end, apply)`：EM 回填（dry-run 默认）。窗口内逐日 fetch+upsert，
  已回填跳过；窗口外/连续失败 → 披露缺口，绝不写 0 行。
- **逐股明细（2026-10-20 立项，用户指令「第2项」）**：家数参考集合之外，另落
  `market_daily_limit_down_stocks`（一天一文档，`rows` 逐股 + source 优先级 EM > 快照 > TDX）。
  `fetch_limit_down_em_rows()` 与 `fetch_limit_down_em()` 共用同一次 HTTP 载荷（不重复外呼）；
  `rows_for_date()` 供【跌停复盘】页读全市场逐股名单；`save_limit_down_rows()` 遵守
  「高级源不被低级源覆盖」，解析全失败不留空名单（fail-visible）。
"""
from __future__ import annotations

import argparse
import json
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.core.limit_rules import is_limit_down_pct
from backend.market_proxy.quotes import market_quotes_redis_key
from backend.market_proxy.redis_client import get_hotlist_redis_client

COLLECTION = "market_daily_limit_down"
# 逐股明细集合（一天一文档）：全市场跌停名单的单一事实源；与家数集合分表是因为
# 逐股载荷体积大且回填节奏不同（家数表有 EM 窗口外的 TDX 行，逐股表要跟源优先级走）。
COLLECTION_ROWS = "market_daily_limit_down_stocks"

# source 取值（参考集合每行带 source；分位采样必须同源，跨口径混采会污染分位）
SOURCE_EM = "em_pool"                       # 东财跌停池（主源，有历史）
SOURCE_SNAPSHOT = "market_quotes_snapshot"  # 全市场行情快照（兜底，仅当日）
SOURCE_TDX = "tdx_local_bars"               # 本地通达信日线重算（离线，窗口外回填；F7 2026-10-17）
SOURCE_POOL = "pool_rows"                   # 采集池口径（末位降级，叙事内标注）

# 「全市场口径」家族（三家都算全市场，可用在同一列；源内优先级 = 下列顺序，EM 最权威）。
# 采集池口径（仅 250 只）**不在**此列——它系统性低估（10-15 实证池内 6 vs 全市场 26），
# 与全市场口径混采会把「换源」读成真实情绪摆动（2026-10-16 审计问题 #1）。
FULL_MARKET_SOURCES = (SOURCE_EM, SOURCE_SNAPSHOT, SOURCE_TDX)

# 逐股明细的源优先级（数字越大越权威）：主页写库/`save_limit_down_rows` 只允许同级或更高级覆盖
SOURCE_RANK = {SOURCE_POOL: 0, SOURCE_TDX: 1, SOURCE_SNAPSHOT: 2, SOURCE_EM: 3}

SOURCE_LABELS = {
    SOURCE_EM: "全市场·东财跌停池",
    SOURCE_SNAPSHOT: "全市场·行情快照",
    SOURCE_TDX: "全市场·本地日线重算",
    SOURCE_POOL: "采集池口径",
}


def source_label(source: object) -> str:
    """source → 叙事口径文案（单一事实源，禁各处再写一份映射）。"""
    return SOURCE_LABELS.get(str(source or ""), "采集池口径")

_TZ = ZoneInfo("Asia/Shanghai")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
EM_DTPOOL_URL = "https://push2ex.eastmoney.com/getTopicDTPool"
# quote.eastmoney.com 涨停板行情页公开 web token（与 akshare stock_zt_pool_dtgc_em 同值）
EM_UT_TOKEN = "7eea3edcaed734bea9cbfc24409ed989"
EM_REFERER = "https://quote.eastmoney.com/"

# ── 东财风控纪律（skills/a-stock-data/SKILL.md「东财防封」+ eastmoney_fund_provider 同款）──
# SKILL 铁律：串行最小间隔 1s + 随机抖动（固定节拍本身是风控指纹）、连接复用、Referer 必带。
# 本模块请求量极小（懒加载 1 次/日 + 一次性回填 ≤30 次），取比铁律更保守的 1.5s。
_EM_MIN_INTERVAL = 1.5
_EM_COOLDOWN_S = 1800.0        # 命中 429/403 后的冷却（对齐 fund provider 东财模式）
_EM_MAX_CONSECUTIVE_FAILURES = 3   # backfill 连续失败即熔断，不逐日硬打

_em_state: dict[str, Any] = {"last": None, "cooldown_until": 0.0}
_em_lock = threading.Lock()
_em_client: httpx.Client | None = None


def reset_em_throttle_state() -> None:
    """清节流/冷却状态与 HTTP 客户端单例（测试夹具用：模块级状态跨用例残留会误导后续用例）。

    2026-10-20 review nit：只清 `_em_state` 会让 Keep-Alive 连接池跨用例残留（当前靠
    conftest 的离线护栏才不可达，属潜伏）；一并清 `_em_client`。
    """
    global _em_client
    with _em_lock:
        _em_state["last"] = None
        _em_state["cooldown_until"] = 0.0
    _em_client = None


def today_str() -> str:
    """上海时区当日（行情快照的实时口径只对「当日」成立）。"""
    return datetime.now(_TZ).strftime("%Y-%m-%d")


# 收盘截点：15:05 后行情快照才是当日收盘口径（15:00 帧采集 + 快照刷新延迟余量）。
# 截点前不读不写快照——盘中值一旦落参考集合会被后续叙事当成当日收盘数复用（持久错值）。
_AFTER_CLOSE_HHMM = (15, 5)


def _snapshot_is_closing() -> bool:
    """当前上海时间是否已过收盘截点（快照可当当日收盘口径用）。"""
    now = datetime.now(_TZ)
    return (now.hour, now.minute) >= _AFTER_CLOSE_HHMM


def _em_window_start() -> str:
    """EM 跌停池可查窗口起点 = 今天-30 自然日（东财/akshare 同款硬边界）。

    窗口外 EM 只返 0 行，与「当日真的 0 家」在响应上无法区分——所以窗口外直接判
    不可用，绝不把「取不到」写成 0（AGENTS §4.0）。
    """
    return (datetime.now(_TZ) - timedelta(days=30)).strftime("%Y-%m-%d")


def _em_throttle() -> None:
    """串行最小间隔 + 随机抖动（东财风控铁律：固定节拍本身是风控指纹）。

    首次调用基准为空不等待；时间戳由调用方在请求**完成后**记录（end-to-start 口径），
    慢响应也不会背靠背连发。
    """
    with _em_lock:
        last = _em_state["last"]
        if last is not None:
            wait = _EM_MIN_INTERVAL - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait + random.uniform(0.1, _EM_MIN_INTERVAL * 0.3))


def _em_http_client() -> httpx.Client:
    """东财 HTTP 客户端单例：Keep-Alive 连接复用 + UA/Referer 注入。

    东财缺 Referer 时风控拒答率明显升高（eastmoney_fund_provider 实测结论）；
    连接重建频率本身是风控指纹，故复用同一 Client。
    """
    global _em_client
    if _em_client is None:
        _em_client = httpx.Client(
            timeout=15.0, headers={"User-Agent": UA, "Referer": EM_REFERER})
    return _em_client


def _em_pool_payload(date: str, *, client: httpx.Client | None = None) -> dict[str, Any] | None:
    """东财跌停池原始载荷 → {pool: [...], total: tc|None}；不可用 → None。

    所有外呼护栏集中在这一个实现里（家数读口与逐股读口共用，禁写第二份）：
    - 窗口外（date < 今天-30 自然日）→ None 且**不外呼**（见 _em_window_start）。
    - 冷却期内（刚吃过 429/403）→ None，不刺激 WAF。
    - 429/403 → 进 30 分钟冷却并返 None；东财风控信号，绝不重试（SKILL 铁律）。
    - 其它异常 / HTTP 200 但 body 非池结构（风控返空/HTML）→ None。
    - 窗口内池为空：**必须 EM 显式自报 `tc == 0` 才是合法 0**；空池且未自报 0（限流/软
      拦截的典型形态）→ None（不可用，交调用方降级），绝不伪 0（AGENTS §4.0）。
    """
    if date < _em_window_start():
        return None
    if time.monotonic() < _em_state["cooldown_until"]:
        return None
    _em_throttle()
    try:
        http = client or _em_http_client()
        response = http.get(EM_DTPOOL_URL, params={
            "ut": EM_UT_TOKEN, "dpt": "wz.ztzt", "Pageindex": "0",
            "pagesize": "10000", "sort": "fund:asc", "date": date.replace("-", "")})
    except AssertionError:
        raise   # 测试离线护栏（conftest _em_offline_guard）的显式失败不得被吞
    except Exception:  # noqa: BLE001 — 连接超时/被拒/客户端构造失败一律降级，不冒泡中断叙事
        return None
    finally:
        # end-to-start 口径：请求发起并返回后才记基准，慢响应也不会背靠背连发
        with _em_lock:
            _em_state["last"] = time.monotonic()
    if response.status_code in (429, 403):
        with _em_lock:
            _em_state["cooldown_until"] = time.monotonic() + _EM_COOLDOWN_S
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        # HTTP 200 但 body 非 JSON：常见于被风控拦截，按坏负载处理（不当作空池）
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    pool = data.get("pool") if isinstance(data, dict) else None
    if not isinstance(pool, list):
        return None
    total = data.get("tc") if isinstance(data, dict) else None
    total_ok = isinstance(total, int) and not isinstance(total, bool)
    if not pool:
        # 空池二义性闸（2026-10-20 review major）：只有 EM 显式自报总数为 0 才认「当日真 0 家」；
        # 否则（tc 缺失/非 0，典型于限流与窗口边界）判不可用，由快照/本地日线/采集池降级兜底。
        return {"pool": [], "total": total} if total_ok and total == 0 else None
    return {"pool": pool, "total": total}


def _em_price(value: object) -> float | None:
    """EM 池价格 `p` 为 ×1000 定点（5790 → 5.79）；非法/非正 → None。"""
    number = _as_float(value)
    if number is None or number <= 0:
        return None
    return round(number / 1000, 2)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


# 公开别名：数值化 helper 被 market_rise_pool 等兄弟模块复用（review nit 2026-10-31：
# 跨模块 import 私有符号会在本模块重构时静默破坏消费方）；旧名保留兼容既有调用。
as_float = _as_float


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None and number == int(number) else None


def _em_time_text(value: object) -> str | None:
    """EM 封板时间（HHMMSS 整数，如 145406）→ '14:54:06'；非法 → None。"""
    digits = str(value or "").strip()
    if not digits.isdigit():
        return None
    digits = digits.zfill(6)
    hour, minute, second = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def parse_em_pool_rows(pool: Any) -> tuple[list[dict[str, Any]], int]:
    """EM 跌停池原始条目 → 逐股行（(rows, badRows)）。

    字段映射（2026-10-20 实测载荷）：`c` 代码 / `n` 名称 / `p` 价格(×1000) / `zdp` 涨跌幅 /
    `amount` 成交额 / `hs` 换手 / `ltsz` 流通市值 / `tshare` 总市值 / `pe` /
    `hybk` 行业板块 / `days` EM 自报连跌天数 / `oc` 开板次数 / `lbt` 最后封板时间 /
    `fund`+`fba`（语义未定，原样留 raw，不臆造中文名）。
    缺代码或缺价+涨跌幅 → 记 badRows 跳过（不阻断其余行，AGENTS §4.0）。
    """
    rows: list[dict[str, Any]] = []
    bad = 0
    for item in pool if isinstance(pool, list) else []:
        if not isinstance(item, dict):
            bad += 1
            continue
        code = str(item.get("c") or item.get("code") or "").strip()
        if not code:
            bad += 1
            continue
        price = _em_price(item.get("p"))
        pct = _as_float(item.get("zdp"))
        if price is None and pct is None:
            bad += 1
            continue
        row: dict[str, Any] = {
            "code": code,
            "name": (str(item.get("n") or "").strip() or None),
            "pctChange": pct,
            "price": price,
            "amount": _as_float(item.get("amount")),
            "turnoverRate": _as_float(item.get("hs")),
            "floatMarketCap": _as_float(item.get("ltsz")),
            "totalMarketCap": _as_float(item.get("tshare")),
            "pe": _as_float(item.get("pe")),
            "industry": (str(item.get("hybk") or "").strip() or None),
            "emStreakDays": _as_int(item.get("days")),
            "openNum": _as_int(item.get("oc")),
            "lastSealTime": _em_time_text(item.get("lbt")),
            "raw": {k: item.get(k) for k in ("m", "fund", "fba", "days", "oc", "lbt")
                    if item.get(k) is not None},
        }
        rows.append(row)
    return rows, bad


def fetch_limit_down_em(date: str, *, client: httpx.Client | None = None) -> int | None:
    """全市场跌停家数：东财跌停股池 `getTopicDTPool`（主源）；不可用 → None。

    截断日（pagesize=10000 实际不可达，池行数 < EM 自报 tc）以 tc 兜底，宁多勿少。
    逐股名单走 `fetch_limit_down_em_rows`；两者共用 `_em_pool_payload` 同一实现（口径不漂移）
    但各自独立外呼——生产路径已统一走 rows 版（家数 + 逐股一次载荷），本函数只保留给
    家数专用读口与单测（2026-10-20 review nit：旧 docstring 称「同一次载荷」与实现不符）。
    """
    payload = _em_pool_payload(date, client=client)
    if payload is None:
        return None
    count = len(payload["pool"])
    total = payload.get("total")
    if isinstance(total, int) and not isinstance(total, bool) and total > count:
        count = total
    return count


def fetch_limit_down_em_rows(date: str, *, client: httpx.Client | None = None) -> dict[str, Any] | None:
    """全市场跌停**逐股**名单：东财跌停池（主源）；不可用 → None。

    返回 `{count, total, rows, badRows, rowsReturned, truncated}`：
    - `count` = EM 自报 tc（缺/更小时用池行数），与家数读口同式（宁多勿少）；
    - `rowsReturned` = 池实际返回条目数（= `len(rows) + badRows`）；**只有无坏行时
      `count == len(rows)`**，坏行日 `count > len(rows)` 由 `badRows` 披露（2026-10-20 review
      minor：预登记笼统写「count == len(rows)」，按差值判截断的下游会误读）；
    - `truncated` = `count > rowsReturned`（真截断：EM 自报数多于池实际返回条目），页面须显式标注；
    - `badRows` = 解析失败行数（跳过不阻断，不伪 0）；全行失败时 `rows=[]`，
      调用方（save/backfill）**不写空名单**，避免把解析故障落成「当日 0 家」。
    """
    payload = _em_pool_payload(date, client=client)
    if payload is None:
        return None
    pool = payload["pool"]
    rows, bad = parse_em_pool_rows(pool)
    total = payload.get("total")
    count = len(pool)
    if isinstance(total, int) and not isinstance(total, bool) and total > count:
        count = total
    return {"count": count, "total": total if isinstance(total, int) else None,
            "rows": rows, "badRows": bad, "rowsReturned": len(pool),
            "truncated": count > len(pool)}


def full_market_dieban_rows_from_quotes() -> dict[str, Any] | None:
    """全市场跌停**逐股**（market_proxy 全市场行情 Redis 快照，仅当日）；不可用 → None。

    快照行形状（to_tencent_diff_item）：f12=code、f14=name、f2=价、f3=涨跌幅%、
    f5=成交额、f8=换手、f9=pe、f21=流通市值（元）。
    行级解析失败跳过并计入 `badRows`（不阻断整体，AGENTS §4.0）；全量不可用
    （Redis 挂/ key 过期 / 空）→ None（不可算，调用方降级，不伪 0）。
    **全部行都解析失败**（`rows` 空且有 `badRows`）→ None：载荷整体畸变/结构变更时
    不得写 count=0（2026-10-20 review minor：快照分支原先缺 EM 分支的等价护栏）。
    返回与 `fetch_limit_down_em_rows` 同形：
    {count, total, rows, badRows, rowsReturned, truncated}。
    """
    client = get_hotlist_redis_client()
    if client is None:
        return None
    try:
        raw_rows = client.hgetall(market_quotes_redis_key())
    except Exception:  # noqa: BLE001 — Redis 不可用一律不可算，调用方降级
        return None
    if not raw_rows:
        return None
    rows: list[dict[str, Any]] = []
    bad = 0
    for key, payload in raw_rows.items():
        try:
            row = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        except Exception:  # noqa: BLE001 — 单行畸形跳过，不伪 0 不阻断
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        code = str(row.get("f12") or key or "").strip()
        pct = row.get("f3")
        if not code or not isinstance(pct, (int, float)) or isinstance(pct, bool):
            bad += 1
            continue
        if not is_limit_down_pct(pct, code):
            continue
        rows.append({
            "code": code,
            "name": (str(row.get("f14") or "").strip() or None),
            "pctChange": float(pct),
            "price": _as_float(row.get("f2")),
            "amount": _as_float(row.get("f5")),
            "turnoverRate": _as_float(row.get("f8")),
            "floatMarketCap": _as_float(row.get("f21")),
            "totalMarketCap": _as_float(row.get("f20")),
            "pe": _as_float(row.get("f9")),
            "industry": None,
            "emStreakDays": None,
            "openNum": None,
            "lastSealTime": None,
            "raw": None,
        })
    if not rows and bad:
        return None   # 全行畸形：不可算（不写 0 家），与 EM 分支「解析全失败不留空名单」同规
    return {"count": len(rows), "total": None, "rows": rows, "badRows": bad,
            "rowsReturned": len(rows) + bad, "truncated": False}


def full_market_dieban_from_quotes() -> int | None:
    """全市场跌停家数（行情快照口径）；不可用 → None（薄壳：名单唯一实现在 rows 版）。"""
    snapshot = full_market_dieban_rows_from_quotes()
    return None if snapshot is None else snapshot["count"]


def save_limit_down_rows(db: Any, date: str, payload: dict[str, Any], source: str) -> bool:
    """写逐股明细文档（一天一文档）；返回是否写入。

    - **高级源不被低级覆盖**（EM > 行情快照 > 本地日线），同源可重复覆写（幂等刷新）；
    - `rows` 为空且 `count != 0` → **不写**（解析全失败/异常截断不得落成「当日 0 家」）；
      `count == 0` 的空名单是合法真读数，照写；
    - 不做任何覆盖率/质量门禁：部分行解析失败只计入 `badRows`，其余行照写。
    """
    rows = payload.get("rows") or []
    count = payload.get("count")
    if not rows and count != 0:
        return False
    col = db[COLLECTION_ROWS]
    existing = col.find_one({"_id": date}, {"source": 1})
    prev = str((existing or {}).get("source") or "")
    if prev and SOURCE_RANK.get(prev, -1) > SOURCE_RANK.get(source, -1):
        return False
    col.replace_one({"_id": date}, {
        "_id": date, "source": source, "count": count,
        "total": payload.get("total"), "truncated": bool(payload.get("truncated")),
        "badRows": payload.get("badRows") or 0, "rows": rows,
        # rowsReturned 供读口把「逐股 N 行」渲染成实际行数（截断日 count > 行数，
        # 页面不得把 count 当家数又当行数：2026-10-20 review minor）
        "rowsReturned": (payload.get("rowsReturned")
                        if isinstance(payload.get("rowsReturned"), int)
                        else len(rows) + (payload.get("badRows") or 0)),
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, upsert=True)
    return True


def rows_for_date(db: Any, date: str) -> dict[str, Any] | None:
    """逐股明细文档（`market_daily_limit_down_stocks` 一天一文档）；无 → None。"""
    return db[COLLECTION_ROWS].find_one({"_id": date})


def reference_counts(db: Any, dates: Any, source: str | None = None) -> dict[str, int]:
    """参考集合批量读（一次 find，禁逐日连发）：date → count。

    `source` 非空时按源过滤——分位采样必须与当日同源，跨口径混采会污染分位数
    （em_pool / quotes_snapshot / pool_rows 三家口径不同）。
    脏值（count 非 int / 缺键）剔除，不伪 0。
    """
    wanted = [str(d) for d in dates]
    if not wanted:
        return {}
    query: dict[str, Any] = {"_id": {"$in": wanted}}
    if source:
        query["source"] = source
    out: dict[str, int] = {}
    for doc in db[COLLECTION].find(query, {"count": 1, "source": 1}):
        count = doc.get("count")
        if isinstance(count, int) and not isinstance(count, bool):
            out[str(doc["_id"])] = count
    return out


def limit_down_count(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                     allow_fetch: bool = True) -> tuple[int | None, str]:
    """(全市场跌停家数, source)。source ∈ {em_pool, quotes_snapshot, tdx_local_bars, pool_rows, missing}。

    2026-10-18 review P2-2：枚举补 `tdx_local_bars`（F7 新增：读既有本地日线回填行时返回，
    属 FULL_MARKET_SOURCES 家族）；消费方按 `src in FULL_MARKET_SOURCES` 分支，不得只认 EM/快照。

    懒加载（只当日）：参考集合 miss 且 allow_fetch 且 date=当日 且已过收盘截点 →
    东财跌停池优先，失败退行情快照，upsert 再读。
    历史日不懒加载（实时口径/外呼纪律），只读参考集合——由 `backfill` 显式回填。
    """
    col = db[COLLECTION]
    doc = col.find_one({"_id": date})
    if doc is None and allow_fetch and date == today_str() and _snapshot_is_closing():
        # 逐股与家数同一次 EM 载荷（不重复外呼）；EM 拿到载荷即以 EM 为准（即便逐股
        # 全行解析失败也只写家数，不回落快照——回落会把换源读成真实摆动）。
        payload = fetch_limit_down_em_rows(date)
        n: int | None = None
        src = SOURCE_EM
        if payload is not None:
            n = payload["count"]
            save_limit_down_rows(db, date, payload, SOURCE_EM)
        else:
            snapshot = full_market_dieban_rows_from_quotes()
            if snapshot is not None:
                n = snapshot["count"]
                src = SOURCE_SNAPSHOT
                save_limit_down_rows(db, date, snapshot, SOURCE_SNAPSHOT)
        if n is not None:
            doc = {"_id": date, "count": n, "source": src,
                   "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            col.replace_one({"_id": date}, doc, upsert=True)
    if doc is not None and isinstance(doc.get("count"), int) and not isinstance(doc.get("count"), bool):
        return doc["count"], str(doc.get("source") or SOURCE_EM)
    # 函数内延迟 import：jev_label_jiuyan 反向依赖本模块的 limit_down_count（叙事消费方），
    # 模块级 import 会成环（2026-10-16 实测 ImportError）
    from backend.operations.jev_label_jiuyan import dieban_count

    n = dieban_count(db, date, dataset_id)
    return (n, SOURCE_POOL) if isinstance(n, int) and not isinstance(n, bool) else (None, "missing")


def backfill(db: Any, start: str, end: str, *, apply: bool = False,
             sleep: Any = None) -> None:
    """EM 跌停池回填（dry-run 默认）：窗口内逐日 fetch + upsert；窗口外只披露缺口。

    - 已回填日跳过（幂等，不重复外呼）；但**本地日线口径（SOURCE_TDX）不算已回填**——
      EM 是更权威的主源，窗口内一律用 EM 升级覆盖（2026-10-17 F7：否则早期 TDX 行会
      把窗口内的 EM 挡住，参考集合静默停在次要源）；
    - 窗口外已有 SOURCE_TDX 行的日期**按「跳过」打印**（保留既有本地日线读数），
      不得混在「[缺口] 无可回填全市场源」里——那会让读者把「有 TDX 读数」误读成「无数据」
      （2026-10-18 review B5：漏报的是该日尚未拿到 EM，而非该日无任何全市场源）；
      只有窗口外**确实无任何行**的日期才打印缺口。
    - 窗口外/上游不可用/**连续**失败 → 披露缺口，**绝不写 0 行**（「取不到」≠「真的 0」）；
    - **连续** `_EM_MAX_CONSECUTIVE_FAILURES` 次失败即熔断（东财封 IP 前科），剩余日照实披露。
      计数必须**成功即清零**：累计计数会让「一次抖动 + 隔日两次抖动」在第 4 天误熔断，
      把 EM 健康的日子整段标成缺口、叙事回退采集池口径（正是要避免的分位污染）。
    - **逐股明细**（2026-10-20）：同一次 EM 载荷顺带落 `market_daily_limit_down_stocks`；
      家数已回填但逐股缺的日子也要再拉一次（`todo_rows`）——否则页面永远只有家数没有名单。
    """
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find({}, {"tradingDate": 1})
                    if r.get("tradingDate") and start <= str(r["tradingDate"]) <= end})
    col = db[COLLECTION]
    # 一次 find 批量读已回填日（模块自身规则「一次 find 批量读，禁逐日连发」）
    rows = {str(d["_id"]): str(d.get("source") or "")
            for d in col.find({"_id": {"$in": dates}}, {"_id": 1, "source": 1})} if dates else {}
    rows_doc = {str(d["_id"]): str(d.get("source") or "")
                for d in db[COLLECTION_ROWS].find({"_id": {"$in": dates}}, {"_id": 1, "source": 1})} if dates else {}
    # TDX 行不算「已回填」：EM 窗口内以 EM 升级（源优先级 EM > 快照 > TDX > 采集池）
    have = {d for d, s in rows.items() if s != SOURCE_TDX}
    tdx_kept = {d for d, s in rows.items() if s == SOURCE_TDX}
    window_start = _em_window_start()
    todo = [d for d in dates if d not in have]
    in_window = [d for d in todo if d >= window_start]
    out_window = [d for d in todo if d < window_start]
    # 家数已有 EM 但逐股缺的日子：补拉逐股（家数文档保持不动，只写逐股集合）
    todo_rows = [d for d in dates
                 if d >= window_start and d not in in_window
                 and rows_doc.get(d) != SOURCE_EM]
    print(f"== 全市场跌停参考集合核查（{start}~{end}）：候选 {len(dates)} 日，"
          f"已回填 {len(have)} 日，待处理 {len(todo)} 日（EM 窗口 {window_start} 起 "
          f"{len(in_window)} 日 / 窗口外 {len(out_window)} 日）；逐股待补 {len(todo_rows)} 日 ==")
    for d in out_window:
        # 窗口外且窗口外已存本地日线行：**不是缺口**，是刻意保留的次要源读数。
        # 旧版把这类日期一并打成「无可回填全市场源」，读者会误以为该日无数据。
        if d in tdx_kept:
            print(f"[跳过] {d}: 已有 {SOURCE_TDX} 行（EM 窗口外，保留既有本地日线读数，不回填）")
        else:
            print(f"[缺口] {d}: 早于 EM 30 日窗口 → 无可回填全市场源（叙事回退采集池口径并标注）")
    ok = fail = 0
    for i, d in enumerate(in_window):
        payload = fetch_limit_down_em_rows(d)
        if payload is None:
            fail += 1
            print(f"[缺口] {d}: EM 上游不可用（限流/熔断/坏负载）→ 不写 0 行")
            if fail >= _EM_MAX_CONSECUTIVE_FAILURES:
                for rest in in_window[i + 1:]:
                    print(f"[缺口] {rest}: 连续失败熔断，未尝试")
                fail += len(in_window) - i - 1
                break
        else:
            ok += 1
            fail = 0        # 连续计数：成功即清零，别把历史上的抖动算进本次连续失败
            n = payload["count"]
            if apply:
                col.replace_one({"_id": d}, {"_id": d, "count": n, "source": SOURCE_EM,
                                             "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                upsert=True)
                save_limit_down_rows(db, d, payload, SOURCE_EM)
            bad_txt = f" · 坏行 {payload['badRows']}" if payload.get("badRows") else ""
            trunc_txt = "（截断）" if payload.get("truncated") else ""
            print(f"[{'回填' if apply else '待回填'}] {d}: {n} 家 / 逐股 {len(payload['rows'])} 行"
                  f"{trunc_txt}{bad_txt}")
        if i < len(in_window) - 1 and sleep is not None:
            sleep(_EM_MIN_INTERVAL)

    # 家数已有、逐股缺 → 补拉逐股（只写逐股集合，不重写家数）
    # `fail` 是与主循环共享的**连续失败**计数（成功即清零，用于熔断）；
    # `rows_*` 只用于本批报告，不混进「家数缺口」的汇总数字（2026-10-20 review minor）。
    rows_ok = rows_fail = 0
    for j, d in enumerate(todo_rows):
        if fail >= _EM_MAX_CONSECUTIVE_FAILURES:
            print(f"[缺口] {d}: 前序连续失败已达阈值，逐股补拉熔断未尝试（家数保留）")
            rows_fail += 1
            continue
        payload = fetch_limit_down_em_rows(d)
        if payload is None:
            fail += 1
            rows_fail += 1
            print(f"[缺口] {d}: EM 逐股补拉不可用 → 逐股仍缺（家数保留）")
        else:
            fail = 0
            rows_ok += 1
            if apply:
                save_limit_down_rows(db, d, payload, SOURCE_EM)
            print(f"[{'回填' if apply else '待回填'}·逐股] {d}: {payload['count']} 家 / {len(payload['rows'])} 行")
        if j < len(todo_rows) - 1 and sleep is not None:
            sleep(_EM_MIN_INTERVAL)
    print(f"== 核查完成：可回填 {ok} 日，缺口 {fail} 日"
          + (f"；逐股补拉 {rows_ok} 日 / 缺口 {rows_fail} 日" if todo_rows else "")
          + f"（{'APPLY 已落库' if apply else 'dry-run，加 --apply 落库'}）==")


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="全市场跌停家数（东财跌停池）回填/核查")
    ap.add_argument("--start", required=True, help="起始交易日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="截止交易日 YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true", help="落库（默认 dry-run 只披露）")
    args = ap.parse_args()
    backfill(_db(), args.start, args.end, apply=args.apply, sleep=time.sleep)
