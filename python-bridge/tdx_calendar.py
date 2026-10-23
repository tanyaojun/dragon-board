"""通达信官方交易日历：自实现 tdx.com.cn 拉取，绕开 mootdx 共享 pickle 缓存。

背景（2026-08-06 排查确认）：
- python-bridge 生产环境用系统 Python（pandas 3.x），测试/量化环境用
  quant-board venv（pandas 2.x）。两者共用 mootdx 用户级缓存
  ``~/.mootdx/caches/holiday.plk``（pandas pickle）。
- pandas 3.0 写入的 pickle（StringDtype reduce 3 参数）被 pandas 2.2.3 读取时
  触发 ``pandas/compat/pickle_compat.py`` 的 ``issubclass`` TypeError；mootdx
  file_cache 只捕获 FileNotFoundError/EOFError，异常冒泡导致 holiday() 崩溃
  （历史 /api/calendar 503，两环境互写缓存互相触发重拉）。
- 本模块等价实现 mootdx.utils.holiday._holiday 的 tdx.com.cn 数据源
  （httpx GET + 正则提取 textarea + split('|')），缓存改为「内存 + 独立 JSON
  文件」，不再读写 mootdx 的 holiday.plk，也不依赖 pandas 序列化，从根上消除
  跨 pandas 版本 pickle 互写振荡。
- 判定语义与 mootdx 等价：周末与列表中的中国节假日视为非交易日；调休上班的
  周末（tdx 源不标注）按非交易日处理，属于上游数据口径限制。

fail-visible：日历不可用时返回 None（不猜测交易日），调用方已按此降级
（/api/calendar 返回 503 + errorCode=tdx_calendar_unavailable）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_TDX_CALENDAR_URL = "https://www.tdx.com.cn/url/holiday/"
_HTTP_TIMEOUT_SECONDS = 10.0

# 缓存策略：TTL 内直接命中（内存/文件），过期后重拉；拉取失败进入冷却，避免高频重试刷屏。
_FETCH_TTL_SECONDS = 24 * 3600
_FAILURE_COOLDOWN_SECONDS = 60

# 独立 JSON 缓存：与 mootdx 的 holiday.plk 同目录但不同文件名、纯文本格式，
# 不依赖 pandas，跨环境（pandas 2.x / 3.x）无兼容问题；mootdx 不会读取该文件。
_CACHE_PATH = Path.home() / ".mootdx" / "caches" / "holiday_bridge.json"

_MEMORY_HOLIDAYS: set[date] | None = None
_MEMORY_FETCHED_AT_TS: float = 0.0
_LAST_FAILURE_AT_TS: float = 0.0
_FETCH_IN_PROGRESS = False
_LOCK = threading.Lock()

_TEXTAREA_RE = re.compile(r'<textarea id="data" style="display:none;">([\s\w\W]+)</textarea>', re.M)


def _now_ts() -> float:
    return time.time()


def _reset_cache() -> None:
    """测试用：清空进程内缓存状态（不影响磁盘缓存文件）。"""
    global _MEMORY_HOLIDAYS, _MEMORY_FETCHED_AT_TS, _LAST_FAILURE_AT_TS, _FETCH_IN_PROGRESS
    with _LOCK:
        _MEMORY_HOLIDAYS = None
        _MEMORY_FETCHED_AT_TS = 0.0
        _LAST_FAILURE_AT_TS = 0.0
        _FETCH_IN_PROGRESS = False


def parse_tdx_holiday_text(text: str) -> set[date]:
    """解析 tdx.com.cn 节假日页文本，返回中国节假日日期集合（等价 mootdx 逻辑）。

    页面结构：textarea 内每行 ``YYYYMMDD|节日名|国家|交易所``，只保留国家为「中国」的行
    （「中国香港」「中国台湾」等同 mootdx 精确匹配语义，不作用于 A 股判定）。
    解析不到中国节假日时抛 ValueError（fail-visible：上层转为 None，不猜测交易日）。
    """
    match = _TEXTAREA_RE.findall(text)
    if not match:
        raise ValueError("tdx holiday page: textarea block not found")
    raw = match[0].strip()
    if not raw:
        raise ValueError("tdx holiday page: textarea block is empty")

    holidays: set[date] = set()
    for line in raw.split("\n"):
        parts = line.split("|")
        if len(parts) < 3 or parts[2].strip() != "中国":
            continue
        try:
            holidays.add(datetime.strptime(parts[0].strip(), "%Y%m%d").date())
        except ValueError:
            continue  # 非日期行（表头/说明），跳过
    if not holidays:
        raise ValueError("tdx holiday page: no China holidays parsed")
    return holidays


def _fetch_tdx_holidays() -> set[date]:
    # 2026-10-23 起 tdx.com.cn 对 httpx/OpenSSL 默认 ClientHello 掐断 TLS 握手
    # （SSL: UNEXPECTED_EOF_WHILE_READING），同机 curl/requests/urllib 均正常；
    # 改用标准库 urllib + 浏览器 UA（不新增依赖），失败语义不变（异常冒泡由调用方降级）。
    request = urllib.request.Request(
        _TDX_CALENDAR_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        raw = response.read()
    text = raw.decode("gbk", errors="replace")
    return parse_tdx_holiday_text(text)


def _load_cache_file() -> tuple[set[date], float] | None:
    """读取 JSON 缓存；文件缺失/损坏/无有效数据返回 None（由调用方重拉覆盖）。"""
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        fetched_at = float(raw["fetchedAt"])
        holidays = {datetime.strptime(item, "%Y-%m-%d").date() for item in raw["holidays"]}
    except Exception:
        return None
    if not holidays:
        return None
    return holidays, fetched_at


def _write_cache_file(holidays: set[date], fetched_at: float) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetchedAt": fetched_at,
            "holidays": sorted(item.isoformat() for item in holidays),
        }
        # 临时文件 + 原子替换，避免并发/中断留下半写缓存
        tmp_path = Path(f"{_CACHE_PATH}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, _CACHE_PATH)
    except Exception:
        logger.debug("failed to write tdx calendar cache", exc_info=True)


def _get_holidays() -> set[date] | None:
    """返回中国节假日集合；日历不可用（拉取失败且在冷却内）返回 None。

    快路径（内存新鲜）无锁；网络拉取在锁外执行并置 _FETCH_IN_PROGRESS 标记，
    避免慢上游（最长 _HTTP_TIMEOUT_SECONDS）阻塞高频行情路径——拉取期间其它线程
    按不可用返回 None（fail-visible），不排队等待。
    """
    global _MEMORY_HOLIDAYS, _MEMORY_FETCHED_AT_TS, _LAST_FAILURE_AT_TS, _FETCH_IN_PROGRESS
    now = _now_ts()
    memory = _MEMORY_HOLIDAYS
    if memory is not None and now - _MEMORY_FETCHED_AT_TS < _FETCH_TTL_SECONDS:
        return memory

    with _LOCK:
        now = _now_ts()
        memory = _MEMORY_HOLIDAYS
        if memory is not None and now - _MEMORY_FETCHED_AT_TS < _FETCH_TTL_SECONDS:
            return memory
        if now - _LAST_FAILURE_AT_TS < _FAILURE_COOLDOWN_SECONDS:
            return None

        # 内存过期/丢失：尝试从 JSON 文件恢复（进程重启复用，避免每次启动都依赖网络）。
        loaded = _load_cache_file()
        if loaded is not None:
            holidays, fetched_at = loaded
            if now - fetched_at < _FETCH_TTL_SECONDS:
                _MEMORY_HOLIDAYS = holidays
                _MEMORY_FETCHED_AT_TS = fetched_at
                return holidays

        if _FETCH_IN_PROGRESS:
            return None  # 其它线程正在拉取：不阻塞，按不可用降级
        _FETCH_IN_PROGRESS = True

    try:
        holidays = _fetch_tdx_holidays()
    except Exception as error:
        logger.warning("TDX trading calendar fetch failed: %s", error)
        holidays = None
    finally:
        with _LOCK:
            # 原子完成：重置拉取标记 + 更新内存，避免重置后、更新前的空窗被其它线程再次触发拉取
            _FETCH_IN_PROGRESS = False
            if holidays is None:
                _LAST_FAILURE_AT_TS = _now_ts()
            else:
                _MEMORY_HOLIDAYS = holidays
                _MEMORY_FETCHED_AT_TS = now

    if holidays is None:
        return None

    _write_cache_file(holidays, now)
    return holidays


def is_trading_day(value: date) -> bool | None:
    """判断是否为交易日；日历不可用时返回 None（不猜测）。"""
    holidays = _get_holidays()
    if holidays is None:
        return None
    if value in holidays:
        return False
    return value.weekday() < 5
