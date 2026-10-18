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
「取不到」与「真的 0」是两件事）。窗口内返空池 = 合法 0（当日确实无跌停）。

**实时口径边界**：行情快照 TTL 300s、每 5 分钟刷新，只服务「当日」叙事；历史日不走此路，
回退采集池口径并显式标注——不拿实时快照冒充历史日收盘（fail-visible）。

懒加载只在「当日 + 已过收盘截点」发生（1 次/日）；历史日一律只读参考集合，由 `backfill`
显式回填（防一次叙事 20 连发外呼）。

fail-visible：任何一步取不到都不写成 0。
- `fetch_limit_down_em(date)`：东财跌停池家数；窗口外/熔断/异常/坏负载 → None。
- `full_market_dieban_from_quotes()`：读 Redis 行情快照统计全市场跌停；不可用 → None。
- `limit_down_count(db, date, dataset_id, allow_fetch)`：(count, source)，source ∈
  {em_pool, quotes_snapshot, pool_rows, missing}。当日 miss 且 allow_fetch 且已过收盘截点
  → EM → 快照 → upsert 懒加载再读；历史日只读参考集合；全无 → 采集池降级/missing。
- `reference_counts(db, dates, source)`：参考集合批量同源读（一次 find，禁逐日连发）。
- `backfill(db, start, end, apply)`：EM 回填（dry-run 默认）。窗口内逐日 fetch+upsert，
  已回填跳过；窗口外/连续失败 → 披露缺口，绝不写 0 行。
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

# source 取值（参考集合每行带 source；分位采样必须同源，跨口径混采会污染分位）
SOURCE_EM = "em_pool"                       # 东财跌停池（主源，有历史）
SOURCE_SNAPSHOT = "market_quotes_snapshot"  # 全市场行情快照（兜底，仅当日）
SOURCE_TDX = "tdx_local_bars"               # 本地通达信日线重算（离线，窗口外回填；F7 2026-10-17）
SOURCE_POOL = "pool_rows"                   # 采集池口径（末位降级，叙事内标注）

# 「全市场口径」家族（三家都算全市场，可用在同一列；源内优先级 = 下列顺序，EM 最权威）。
# 采集池口径（仅 250 只）**不在**此列——它系统性低估（10-15 实证池内 6 vs 全市场 26），
# 与全市场口径混采会把「换源」读成真实情绪摆动（2026-10-16 审计问题 #1）。
FULL_MARKET_SOURCES = (SOURCE_EM, SOURCE_SNAPSHOT, SOURCE_TDX)

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
    """清节流/冷却状态（测试夹具用：模块级状态跨用例残留会误导后续用例）。"""
    with _em_lock:
        _em_state["last"] = None
        _em_state["cooldown_until"] = 0.0


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


def fetch_limit_down_em(date: str, *, client: httpx.Client | None = None) -> int | None:
    """全市场跌停家数：东财跌停股池 `getTopicDTPool`（主源）。

    - 窗口外（date < 今天-30 自然日）→ None 且**不外呼**（见 _em_window_start）。
    - 冷却期内（刚吃过 429/403）→ None，不刺激 WAF。
    - 429/403 → 进 30 分钟冷却并返 None；东财风控信号，绝不重试（SKILL 铁律）。
    - 其它异常 / HTTP 200 但 body 非池结构（风控返空/HTML）→ None。
    - 窗口内池为空 = 合法 0（当日确实无跌停）。
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
    count = len(pool)
    total = data.get("tc") if isinstance(data, dict) else None
    # pagesize=10000 实际不可达截断；真截断时以 EM 自报总数兜底（宁多勿少）
    if isinstance(total, int) and not isinstance(total, bool) and total > count:
        count = total
    return count


def full_market_dieban_from_quotes() -> int | None:
    """全市场跌停家数：读 market_proxy 全市场行情 Redis 快照统计；不可用 → None。

    快照行形状（to_tencent_diff_item）：f12=code、f14=name、f3=涨跌幅%。
    行级解析失败跳过（不阻断整体统计）；全量不可用（Redis 挂/key 过期/空）→ None。
    """
    client = get_hotlist_redis_client()
    if client is None:
        return None
    try:
        rows = client.hgetall(market_quotes_redis_key())
    except Exception:  # noqa: BLE001 — Redis 不可用一律不可算，调用方降级
        return None
    if not rows:
        return None
    n = 0
    for code, payload in rows.items():
        try:
            row = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
        except Exception:  # noqa: BLE001 — 单行畸形跳过，不伪 0 不阻断
            continue
        if not isinstance(row, dict):
            continue
        pct = row.get("f3")
        if isinstance(pct, (int, float)) and not isinstance(pct, bool) and is_limit_down_pct(pct, code):
            n += 1
    return n


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
    """(全市场跌停家数, source)。source ∈ {em_pool, quotes_snapshot, pool_rows, missing}。

    懒加载（只当日）：参考集合 miss 且 allow_fetch 且 date=当日 且已过收盘截点 →
    东财跌停池优先，失败退行情快照，upsert 再读。
    历史日不懒加载（实时口径/外呼纪律），只读参考集合——由 `backfill` 显式回填。
    """
    col = db[COLLECTION]
    doc = col.find_one({"_id": date})
    if doc is None and allow_fetch and date == today_str() and _snapshot_is_closing():
        n = fetch_limit_down_em(date)
        src = SOURCE_EM
        if n is None:
            n = full_market_dieban_from_quotes()
            src = SOURCE_SNAPSHOT
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

    - 已回填日跳过（幂等，不重复外呼）；
    - 窗口外/上游不可用/**连续**失败 → 披露缺口，**绝不写 0 行**（「取不到」≠「真的 0」）；
    - **连续** `_EM_MAX_CONSECUTIVE_FAILURES` 次失败即熔断（东财封 IP 前科），剩余日照实披露。
      计数必须**成功即清零**：累计计数会让「一次抖动 + 隔日两次抖动」在第 4 天误熔断，
      把 EM 健康的日子整段标成缺口、叙事回退采集池口径（正是要避免的分位污染）。
    """
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find({}, {"tradingDate": 1})
                    if r.get("tradingDate") and start <= str(r["tradingDate"]) <= end})
    col = db[COLLECTION]
    # 一次 find 批量读已回填日（模块自身规则「一次 find 批量读，禁逐日连发」）
    have = {str(d["_id"]) for d in col.find({"_id": {"$in": dates}}, {"_id": 1})} if dates else set()
    window_start = _em_window_start()
    todo = [d for d in dates if d not in have]
    in_window = [d for d in todo if d >= window_start]
    out_window = [d for d in todo if d < window_start]
    print(f"== 全市场跌停参考集合核查（{start}~{end}）：候选 {len(dates)} 日，"
          f"已回填 {len(have)} 日，待处理 {len(todo)} 日（EM 窗口 {window_start} 起 "
          f"{len(in_window)} 日 / 窗口外 {len(out_window)} 日）==")
    for d in out_window:
        print(f"[缺口] {d}: 早于 EM 30 日窗口 → 无可回填全市场源（叙事回退采集池口径并标注）")
    ok = fail = 0
    for i, d in enumerate(in_window):
        n = fetch_limit_down_em(d)
        if n is None:
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
            if apply:
                col.replace_one({"_id": d}, {"_id": d, "count": n, "source": SOURCE_EM,
                                             "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                upsert=True)
            print(f"[{'回填' if apply else '待回填'}] {d}: {n} 家（东财跌停池）")
        if i < len(in_window) - 1 and sleep is not None:
            sleep(_EM_MIN_INTERVAL)
    print(f"== 核查完成：可回填 {ok} 日，缺口 {fail} 日"
          f"（{'APPLY 已落库' if apply else 'dry-run，加 --apply 落库'}）==")


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
