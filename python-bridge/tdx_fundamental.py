"""通达信财务数据缓存与估值指标计算（供 python-bridge 转发）。

背景（2026-08-06）：mootdx/tdxpy 没有现成的换手率/市值/PE/PB 接口，但
``get_finance_info`` 提供计算原料（流通/总股本、每股净资产、净利润）。本模块：

- 缓存 ``get_finance_info``（经 mootdx ``Quotes.finance``）结果：内存、TTL 刷新、失败冷却；
- 用实时价格/成交量计算：换手率、流通市值、总市值、PE、PB；
- 指标均为估算口径，供前端展示参考，与 akshare（market-proxy）的官方口径可能不一致。

口径说明（2026-08-06 实测验证）：
- 换手率   = 成交量(手 * 100) / 流通股本 * 100（%）
- 流通市值 = 流通股本 * 实时价格（元）：**含限售流通口径**（get_finance_info 的
  liutongguben，与腾讯源、通达信客户端默认「流通市值」列一致）。TDX 协议不提供
  「流通市值Z」（已扣限售股本）口径，如需该口径需另接数据源（如 akshare 东财）。
- 总市值   = 总股本 * 实时价格（元）
- PB       = 价格 / 每股净资产
- PE       = 价格 / (净利润 / 总股本)：注意 ``get_finance_info`` 的净利润(jinglirun)
  为通达信 F10 口径（多期累计，非单期年利润），据此计算的 PE 仅作估算，
  以 ``peEstimated=true`` 标记，与 akshare 的 PE-TTM 不一致。

用法：
- ``compute_fundamentals(code, price, volume_hands)``：查缓存计算（无 IO，行情路径调用）；
- ``refresh_finance(codes, client)``：后台任务刷新财务缓存（网络 IO，勿在行情热路径直接调用）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_FINANCE_TTL_SECONDS = 6 * 3600  # 财务数据每日更新，6 小时刷新足够
_FAILURE_COOLDOWN_SECONDS = 10 * 60
_REFRESH_MAX_CONCURRENCY = 4

_cache: dict[str, dict[str, Any]] = {}
_fetched_at: dict[str, float] = {}
_failed_at: dict[str, float] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def reset() -> None:
    """测试用：清空全部缓存状态。"""
    with _guard:
        _cache.clear()
        _fetched_at.clear()
        _failed_at.clear()
        _locks.clear()


def compute_fundamentals(code: str, price: float, volume_hands: float) -> dict[str, Any] | None:
    """用实时价格/成交量计算估值指标；财务数据缺失返回 None（不阻塞、不猜测）。"""
    fin = _cache.get(code)
    if not fin:
        return None
    try:
        liutong = _num(fin.get("liutongguben"))
        zong = _num(fin.get("zongguben"))
        bvps = _num(fin.get("meigujingzichan"))
        jlr = _num(fin.get("jinglirun"))
        price = _num(price)
        vol = _num(volume_hands)

        out: dict[str, Any] = {}
        if liutong > 0 and price > 0:
            out["floatMarketCap"] = round(liutong * price, 2)
            if vol > 0:
                out["turnoverRate"] = round(vol * 100 / liutong * 100, 2)
        if zong > 0 and price > 0:
            out["totalMarketCap"] = round(zong * price, 2)
            if jlr > 0:
                eps = jlr / zong
                out["pe"] = round(price / eps, 2)
                out["peEstimated"] = True
        if bvps > 0 and price > 0:
            out["pb"] = round(price / bvps, 2)
        return out or None
    except Exception:
        logger.debug("compute_fundamentals failed for %s", code, exc_info=True)
        return None


def refresh_finance(codes: list[str], client: Any, max_concurrency: int = _REFRESH_MAX_CONCURRENCY) -> int:
    """刷新财务缓存（后台任务用）；返回本次成功条数。client 为 mootdx Quotes 实例。"""
    now = time.time()
    todo = [c for c in dict.fromkeys(codes) if _should_refresh(c, now)]
    if not todo:
        return 0

    semaphore = threading.Semaphore(max(1, max_concurrency))
    success = 0
    success_lock = threading.Lock()

    def _fetch(code: str) -> None:
        nonlocal success
        with semaphore:
            if not _should_refresh(code, time.time()):
                return
            try:
                frame = client.finance(symbol=code)
                if frame is None or frame.empty:
                    raise ValueError("empty finance frame")
                fin = dict(frame.iloc[0])
                with _guard:
                    _cache[code] = fin
                    _fetched_at[code] = time.time()
                    _failed_at.pop(code, None)
                with success_lock:
                    success += 1
            except Exception as error:
                with _guard:
                    _failed_at[code] = time.time()
                logger.debug("finance fetch failed for %s: %s", code, error)

    threads = [threading.Thread(target=_fetch, args=(code,), daemon=True) for code in todo]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return success


def _should_refresh(code: str, now: float) -> bool:
    with _guard:
        fetched = _fetched_at.get(code, 0.0)
        if fetched and now - fetched < _FINANCE_TTL_SECONDS:
            return False
        failed = _failed_at.get(code, 0.0)
        if failed and now - failed < _FAILURE_COOLDOWN_SECONDS:
            return False
        return True


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
