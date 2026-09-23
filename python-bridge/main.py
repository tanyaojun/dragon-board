import asyncio
import contextlib
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Iterable

# 被外部进程（如 DragonBoardLauncher）重定向输出时，stderr 默认按系统区域编码（GBK），
# launcher 按 UTF-8 解码会造成中文日志/警告乱码。pipe 下强制 UTF-8 对齐；
# 终端直跑（isatty）保持默认编码，不影响手工调试显示。
if sys.stderr is not None and not sys.stderr.isatty():
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# tdxpy 在非交易时段调用分笔接口会输出 DeprecationWarning「目前不是交易时间段, ...」，
# 属既有预期行为（接口本身返回 None）。按消息文本精确过滤（不依赖 module 解析，
# 比按 module 匹配更鲁棒），避免刷屏 launcher 日志，不影响行情拉取。
warnings.filterwarnings("ignore", message=r"目前不是交易时间段.*")

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mootdx.quotes import Quotes

from l2.qmt_provider import QmtL2Provider
from tdxpy.helper import time_frame as tdx_is_trading_frame
import tdx_bj_compat
import tdx_calendar
import tdx_fund_flow
import tdx_fundamental
from tdx_hq_cache import OfficialHQCacheDepthReader

# 北交所（920 号段）行情兼容 patch：mootdx/tdxpy 未实现北交所，运行时替换
# （幂等；失败仅告警，不影响行情主链路）。
tdx_bj_compat.install_bj_compat()

# tdxpy 握手身份 patch（2026-09-23）：TdxHq_API.setup() 默认连发 SetupCmd1/2/3，
# 其中 SetupCmd3 携带旧版"招商证券金钻"客户端标识串。通达信官方现行主站
# （connect.cfg 双线主站）将该标识会话判定为旧第三方客户端，对 quotes/bars
# 返回 4 字节空响应（软拒绝）；实测只发 SetupCmd1+2 时官方主站行情/K线/指数
# 全部正常返回，券商老主站（国泰君安）不受影响。探测证据与变体矩阵：
# python-bridge/research/tdx_official_protocol_probe.py
# 设 TDX_KEEP_TDXPY_SETUP3=1 可恢复 tdxpy 原始三连握手（回退开关）。
def _tdx_hq_setup_without_legacy_identity(self):
    from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2

    SetupCmd1(self.client).call_api()
    SetupCmd2(self.client).call_api()


if os.getenv("TDX_KEEP_TDXPY_SETUP3", "") not in ("1", "true", "True"):
    from tdxpy.hq import TdxHq_API

    TdxHq_API.setup = _tdx_hq_setup_without_legacy_identity
from trading_time import (
    MORNING_CONTINUOUS_START_HHMM,
    hhmm,
    is_after_trading_day_complete,
    is_quote_trading_session,
)


def default_log_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "logs"))


def default_log_filename() -> str:
    configured = os.getenv("TDX_BRIDGE_LOG_FILE", "").strip()
    if configured:
        return configured
    try:
        port = int(os.getenv("TDX_BRIDGE_PORT", "8765").strip() or "8765")
    except ValueError:
        port = 8765
    return f"bridge-{port}.log" if port > 0 else "bridge.log"


def configure_logging() -> str:
    log_dir = os.path.abspath(os.getenv("TDX_BRIDGE_LOG_DIR", default_log_dir()))
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, default_log_filename())

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = TimedRotatingFileHandler(
        filename=log_path,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    return log_path


LOG_FILE_PATH = configure_logging()
logger = logging.getLogger("tdx_l2_bridge")


class FastApiWebSocketClient:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket

    async def __aiter__(self):
        async for message in self.websocket.iter_text():
            yield message

    async def send(self, message: str) -> None:
        await self.websocket.send_text(message)


class _ClientSendQueue:
    """每客户端独立发送队列：broadcast 只入队（丢旧保新），由后台任务逐条发送。

    慢客户端只影响自己的队列，不再拖拽其他客户端与心跳推送。
    """

    def __init__(self, client: Any, maxsize: int = 8) -> None:
        self.client = client
        self.maxsize = max(1, int(maxsize))
        self.queue: deque[str] = deque()
        self.closed = False
        self.sender_task: asyncio.Task[None] | None = None

    def enqueue(self, message: str) -> None:
        if self.closed:
            return
        if len(self.queue) >= self.maxsize:
            self.queue.popleft()  # 丢旧保新：行情是快照式消费，旧帧无保留价值
        self.queue.append(message)
        if self.sender_task is None or self.sender_task.done():
            self.sender_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while self.queue and not self.closed:
                message = self.queue.popleft()
                await self.client.send(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 发送失败视为客户端失效；由 broadcast/清理路径移除
            self.closed = True
        finally:
            self.sender_task = None

    async def close(self) -> None:
        self.closed = True
        self.queue.clear()
        task = self.sender_task
        self.sender_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


DEFAULT_L2_SERVER_CANDIDATES = (
    "124.71.222.84:7719,"
    "139.9.2.221:7719,"
    "106.52.50.92:7719,"
    "115.159.210.142:7719,"
    "124.70.201.50:7719,"
    "139.159.214.37:7719,"
    "110.41.14.158:7719,"
    "123.249.28.184:7719,"
    "49.233.65.70:7719,"
    "139.9.208.12:7719,"
    "175.178.1.74:7719,"
    "139.9.211.54:7719,"
    "123.60.164.170:7719,"
    "49.235.186.69:7719,"
    "123.60.162.102:7719,"
    "124.220.164.89:7719,"
    "175.24.205.60:7719,"
    "150.158.160.127:7719,"
    "139.9.1.206:7719,"
    "43.138.33.225:7719,"
    "43.136.49.71:7719,"
    "203.195.161.155:7719,"
    "106.52.221.102:7719,"
    "119.3.183.88:7719,"
    "139.9.143.183:7719,"
    "120.46.206.187:7719,"
    "106.54.40.15:7719,"
    "124.220.73.3:7719,"
    "49.235.176.135:7719,"
    "116.205.235.110:7719,"
    "116.205.238.42:7719,"
    "116.205.239.160:7719,"
    "1.94.169.137:7719"
)


def default_helper_exe_path() -> str:
    return os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "tools",
            "TdxL2Helper",
            "bin",
            "Release",
            "net8.0-windows",
            "win-x86",
            "publish",
            "TdxL2Helper.exe",
        )
    )


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no"}


def env_path(name: str, default: str) -> str:
    raw = os.getenv(name)
    value = (raw if raw is not None else default).strip()
    return os.path.abspath(value) if value else ""


def parse_server_candidates(raw: str) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        if ":" not in item:
            continue
        host, port_text = item.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            continue
        pair = (host.strip(), port)
        if pair[0] and pair not in candidates:
            candidates.append(pair)
    return candidates


TDX_HOSTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tdx_hosts.json")


def load_tdx_hosts() -> list[dict[str, Any]]:
    """加载本地行情服务器池（tdx_hosts.json）。

    池来源：通达信客户端 connect.cfg [HQHOST] 现行官方主站 + 实测仍兼容 tdxpy
    协议的券商老主站。配合模块顶部的握手补丁（跳过 SetupCmd3），官方主站与
    券商老主站均为可用的生产候选。文件缺失或损坏时返回空列表，
    调用方回退到 mootdx/tdxpy 内置列表。
    """
    try:
        with open(TDX_HOSTS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    hosts: list[dict[str, Any]] = []
    for item in data.get("candidates", []):
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip", "")).strip()
        try:
            port = int(item.get("port", 0))
        except (TypeError, ValueError):
            continue
        if not ip or not 0 < port < 65536:
            continue
        hosts.append({"name": str(item.get("name", ip)), "ip": ip, "port": port})
    return hosts


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000).astimezone().isoformat(timespec="seconds")


def is_opening_sampling_window(start: datetime | None = None, end: datetime | None = None) -> bool:
    current = start or datetime.now()
    finished = end or current
    if _is_trading_day_cached(current) is not True and _is_trading_day_cached(finished) is not True:
        return False

    window_start = 9 * 3600 + 15 * 60
    window_end = 9 * 3600 + 36 * 60  # 09:36:00
    start_seconds = current.hour * 3600 + current.minute * 60 + current.second
    end_seconds = finished.hour * 3600 + finished.minute * 60 + finished.second
    return start_seconds <= window_end and end_seconds >= window_start


class OpeningRawQuoteFileSink:
    def __init__(self, directory: str) -> None:
        self.directory = os.path.abspath(directory)
        self.reported_failure = False

    def record_many(self, quotes: Iterable[dict[str, Any]], source: str) -> None:
        rows = [self._row(item, source) for item in quotes]
        rows = [item for item in rows if item]
        if not rows:
            return

        try:
            os.makedirs(self.directory, exist_ok=True)
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                grouped[str(row["tradingDate"])].append(row)
            for trading_date, items in grouped.items():
                path = os.path.join(self.directory, f"opening-raw-quotes-{trading_date}.jsonl")
                with open(path, "a", encoding="utf-8") as handle:
                    for item in items:
                        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as error:
            if not self.reported_failure:
                self.reported_failure = True
                logger.warning("opening raw quote write failed: %s", error)

    def _row(self, item: dict[str, Any], source: str) -> dict[str, Any] | None:
        captured_at = str(item.get("capturedAt") or item.get("bridgeTs") or "").strip()
        try:
            timestamp = datetime.fromisoformat(captured_at)
        except ValueError:
            source_ts = to_int(item.get("sourceTs"), 0)
            if source_ts <= 0:
                return None
            timestamp = datetime.fromtimestamp(source_ts / 1000).astimezone()
            captured_at = timestamp.isoformat(timespec="seconds")

        code = normalize_code(item.get("code"))
        if not code:
            return None

        return {
            "source": source,
            "tradingDate": timestamp.date().isoformat(),
            "timestamp": captured_at,
            "code": code,
            "name": str(item.get("name") or "").strip(),
            "lastPrice": to_number(item.get("lastPrice")),
            "preClose": to_number(item.get("preClose")),
            "open": to_number(item.get("open")),
            "high": to_number(item.get("high")),
            "low": to_number(item.get("low")),
            "changePct": to_number(item.get("changePct")),
            "volume": to_number(item.get("volume")),
            "amount": to_number(item.get("amount")),
            "sampleKind": str(item.get("sampleKind") or ""),
            "openingForcedSample": bool(item.get("openingForcedSample")),
            "requestedCount": item.get("requestedCount"),
            "receivedCount": item.get("receivedCount"),
            "elapsedMs": item.get("elapsedMs"),
            "slowBatches": item.get("slowBatches"),
            "truncatedBatches": item.get("truncatedBatches"),
            "sourceTs": item.get("sourceTs"),
            "capturedAt": item.get("capturedAt"),
            "bridgeTs": item.get("bridgeTs"),
        }


def _is_trading_day_cached(date: datetime) -> bool | None:
    """使用通达信官方交易日历（自实现 tdx.com.cn 拉取，绕开 mootdx 共享 pickle 缓存）。

    不可用时不猜测交易日，返回 None 由调用方降级（/api/calendar 返回 503）。
    实现细节见 tdx_calendar 模块：内存 + 独立 JSON 缓存，不再读写 mootdx 的
    ~/.mootdx/caches/holiday.plk，系统 Python（pandas 3.x）与 quant-board venv
    （pandas 2.x）不再互相触发跨版本 pickle 重拉。
    """
    return tdx_calendar.is_trading_day(date.date())


def is_trading_session_now(now: datetime | None = None) -> bool:
    current = now or datetime.now()
    if _is_trading_day_cached(current) is not True:
        return False

    return is_quote_trading_session(current)


def latest_completed_trading_date(now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    current_status = _is_trading_day_cached(current)
    if current_status is None:
        raise RuntimeError("TDX trading calendar unavailable")
    if current_status and is_after_trading_day_complete(current):
        return current
    candidate = current - timedelta(days=1)
    for _ in range(370):
        status = _is_trading_day_cached(candidate)
        if status is None:
            raise RuntimeError("TDX trading calendar unavailable")
        if status:
            return candidate
        candidate -= timedelta(days=1)
    raise RuntimeError("no completed trading day found in TDX calendar")


def resolve_minute_session_date(now: datetime | None = None) -> tuple[str, bool]:
    current = now or datetime.now().astimezone()
    status = _is_trading_day_cached(current)
    if status is None:
        raise RuntimeError("TDX trading calendar unavailable")
    current_hhmm = hhmm(current)
    if status and current_hhmm >= MORNING_CONTINUOUS_START_HHMM:
        return current.strftime("%Y%m%d"), is_after_trading_day_complete(current)
    completed = latest_completed_trading_date(current)
    return completed.strftime("%Y%m%d"), True


def resolve_requested_session_date(value: str) -> str:
    try:
        candidate = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("invalid requested date") from exc

    for _ in range(370):
        status = _is_trading_day_cached(candidate)
        if status is None:
            raise RuntimeError("TDX trading calendar unavailable")
        if status:
            return candidate.strftime("%Y%m%d")
        candidate -= timedelta(days=1)
    raise RuntimeError("no trading day found in TDX calendar")


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_number(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed == parsed else 0.0


def to_optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:] if digits else ""


def pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row:
            value = row.get(key)
            if value is not None and value != "":
                return value
    return default


def frame_to_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return list(frame.to_dict("records"))
        except Exception:
            return []
    if isinstance(frame, dict):
        return [frame]
    if isinstance(frame, list):
        return [item for item in frame if isinstance(item, dict)]
    return []


def normalize_quote_row(row: dict[str, Any], captured_ms: int | None = None) -> dict[str, Any] | None:
    code = normalize_code(pick(row, "code", "symbol"))
    if not code:
        return None

    raw_last_price = pick(row, "price", "lastPrice", "last_price")
    last_price = to_number(raw_last_price)
    last_price_source = "last" if last_price > 0 else "missing"
    pre_close = to_number(pick(row, "last_close", "pre_close", "preClose"))
    derived_change_pct = ((last_price - pre_close) / pre_close * 100) if last_price > 0 and pre_close > 0 else 0.0
    change_pct = to_number(pick(row, "percent", "change", "change_pct", "changePct"))
    if change_pct == 0.0 and derived_change_pct != 0.0:
        change_pct = derived_change_pct

    turnover_rate = to_optional_number(pick(row, "turnover_rate", "turnoverRate"))
    volume = to_number(pick(row, "volume", "vol", "trade"))
    amount = to_number(pick(row, "amount", "turnover"))
    tdx_buy_volume = to_number(pick(row, "b_vol", "buy_volume", "buyVolume"))
    tdx_sell_volume = to_number(pick(row, "s_vol", "sell_volume", "sellVolume"))
    tdx_current_volume = to_number(pick(row, "cur_vol", "current_volume", "currentVolume"))

    captured_ms = captured_ms or now_ms()
    payload = {
        "code": code,
        "name": str(pick(row, "name", "volunit", default="") or "").strip(),
        "lastPrice": last_price,
        "changePct": change_pct,
        "changeAmount": to_number(pick(row, "price_change", "changeAmount")) or ((last_price - pre_close) if last_price > 0 else 0.0),
        "volume": volume,
        "amount": amount,
        "open": to_number(pick(row, "open")),
        "high": to_number(pick(row, "high")),
        "low": to_number(pick(row, "low")),
        "preClose": pre_close,
        "tdxBuyVolume": tdx_buy_volume,
        "tdxSellVolume": tdx_sell_volume,
        "tdxCurrentVolume": tdx_current_volume,
        "sourceTs": captured_ms,
        "capturedAt": iso_from_ms(captured_ms),
        "bridgeTs": iso_from_ms(captured_ms),
        "lastPriceSource": last_price_source,
    }

    if turnover_rate is not None:
        payload["turnoverRate"] = turnover_rate
    # 估值指标（换手率/市值/PE/PB）：由 tdx_fundamental 用财务数据 + 实时行情计算，
    # 只补缺失字段（不覆盖上游已有值）；财务数据缺失时无这些字段。
    fundamentals = tdx_fundamental.compute_fundamentals(code, last_price, volume)
    if fundamentals:
        for key, value in fundamentals.items():
            if key not in payload:
                payload[key] = value
    if not payload["name"]:
        payload.pop("name", None)

    return payload


def is_placeholder_quote_row(quote_item: dict[str, Any]) -> bool:
    last_price = to_number(quote_item.get("lastPrice"))
    pre_close = to_number(quote_item.get("preClose"))
    volume = to_number(quote_item.get("volume"))
    return pre_close > 0 and last_price <= 0 and volume <= 0


def extract_depth_levels(row: dict[str, Any], side: str) -> list[dict[str, float]]:
    levels: list[dict[str, float]] = []
    aliases = ("bid", "buy") if side == "bid" else ("ask", "sell")

    for index in range(1, 11):
        price = 0.0
        volume = 0.0
        for alias in aliases:
            price = price or to_number(
                pick(
                    row,
                    f"{alias}{index}",
                    f"{alias}{index}_price",
                    f"{alias}_price{index}",
                    f"{alias}{index}price",
                    f"{alias[0]}{index}_p",
                )
            )
            volume = volume or to_number(
                pick(
                    row,
                    f"{alias}_vol{index}",
                    f"{alias}{index}_vol",
                    f"{alias}_volume{index}",
                    f"{alias}{index}volume",
                    f"{alias[0]}{index}_v",
                )
            )
        if price > 0 or volume > 0:
            levels.append({"price": price, "volume": volume})
    return levels


def normalize_depth_row(row: dict[str, Any]) -> dict[str, Any] | None:
    code = normalize_code(pick(row, "code", "symbol"))
    if not code:
        return None

    bids = extract_depth_levels(row, "bid")
    asks = extract_depth_levels(row, "ask")
    if not bids and not asks:
        return None

    return {
        "code": code,
        "bids": bids,
        "asks": asks,
        "sourceTs": now_ms(),
    }


def depth_matches_quote_window(
    quote_item: dict[str, Any] | None,
    depth_item: dict[str, Any] | None,
) -> bool:
    if not quote_item or not depth_item:
        return False

    bids = depth_item.get("bids") or []
    asks = depth_item.get("asks") or []
    if not bids or not asks:
        return False

    last_price = to_number(quote_item.get("lastPrice"))
    bid1 = to_number(bids[0].get("price"))
    ask1 = to_number(asks[0].get("price"))
    if last_price <= 0 or bid1 <= 0 or ask1 <= 0 or ask1 < bid1:
        return False

    midpoint = (bid1 + ask1) / 2
    tolerance = max(0.3, last_price * 0.12)
    return abs(midpoint - last_price) <= tolerance or (bid1 - tolerance) <= last_price <= (ask1 + tolerance)


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "b", "买", "买盘", "0"}:
        return "buy"
    if text in {"sell", "s", "卖", "卖盘", "1"}:
        return "sell"
    return "neutral"


def normalize_tick_row(code: str, row: dict[str, Any]) -> dict[str, Any] | None:
    normalized_code = normalize_code(code)
    if not normalized_code:
        return None

    price = to_number(pick(row, "price"))
    volume = to_number(pick(row, "volume", "vol"))
    if price <= 0 and volume <= 0:
        return None

    amount = to_number(pick(row, "amount"))
    inferred_amount = price * volume * 100 if price > 0 and volume > 0 else 0.0
    if inferred_amount > 0 and (amount <= 0 or amount < inferred_amount * 0.2):
        amount = inferred_amount

    return {
        "code": normalized_code,
        "price": price,
        "volume": volume,
        "amount": amount,
        "side": normalize_side(pick(row, "side", "buyorsell", "bsflag")),
        "tradeTime": str(pick(row, "time", "tradeTime", "datetime", default="") or ""),
        "sourceTs": now_ms(),
    }


@dataclass
class QuoteFetchStats:
    requested_codes: int = 0
    batches: int = 0
    failed_batches: int = 0
    truncated_batches: int = 0
    slow_batches: int = 0
    received_quotes: int = 0
    received_depth: int = 0
    elapsed_ms: int = 0
    halted_codes: int = 0  # 本轮因无数据挂起而跳过的代码数

    def to_payload(self) -> dict[str, int]:
        return {
            "requestedCount": self.requested_codes,
            "receivedCount": self.received_quotes,
            "receivedDepthCount": self.received_depth,
            "elapsedMs": self.elapsed_ms,
            "batches": self.batches,
            "failedBatches": self.failed_batches,
            "slowBatches": self.slow_batches,
            "truncatedBatches": self.truncated_batches,
            "haltedCodes": self.halted_codes,
        }


@dataclass
class BridgeConfig:
    host: str = os.getenv("TDX_BRIDGE_HOST", "127.0.0.1")
    port: int = env_int("TDX_BRIDGE_PORT", 8765)
    path: str = os.getenv("TDX_BRIDGE_PATH", "/ws/quotes")
    poll_interval_ms: int = env_int("TDX_POLL_INTERVAL_MS", 100)
    target_cycle_interval_ms: int = env_int("TDX_TARGET_CYCLE_INTERVAL_MS", 600)
    heartbeat_interval_ms: int = env_int("TDX_HEARTBEAT_INTERVAL_MS", 5000)
    trading_heartbeat_interval_ms: int = env_int("TDX_TRADING_HEARTBEAT_INTERVAL_MS", 1000)
    timeout_seconds: int = env_int("TDX_TIMEOUT_SECONDS", 15)
    use_bestip: bool = env_bool("TDX_USE_BESTIP", True)
    quote_batch_size: int = env_int("TDX_QUOTE_BATCH_SIZE", 40)
    quote_batch_min_size: int = env_int("TDX_QUOTE_BATCH_MIN_SIZE", 20)
    quote_batch_max_size: int = env_int("TDX_QUOTE_BATCH_MAX_SIZE", 50)
    quote_batch_concurrency: int = env_int("TDX_QUOTE_BATCH_CONCURRENCY", 3)
    tick_fetch_concurrency: int = env_int("TDX_TICK_FETCH_CONCURRENCY", 4)
    client_send_queue_maxsize: int = env_int("TDX_CLIENT_SEND_QUEUE_MAXSIZE", 8)
    slow_batch_threshold_ms: int = env_int("TDX_SLOW_BATCH_THRESHOLD_MS", 1200)
    batch_growth_step: int = env_int("TDX_BATCH_GROWTH_STEP", 2)
    batch_shrink_step: int = env_int("TDX_BATCH_SHRINK_STEP", 5)
    healthy_cycles_before_grow: int = env_int("TDX_HEALTHY_CYCLES_BEFORE_GROW", 5)
    dead_code_max_failures: int = env_int("TDX_DEAD_CODE_MAX_FAILURES", 3)
    dead_code_retry_ms: int = env_int("TDX_DEAD_CODE_RETRY_MS", 1800000)  # 30 分钟
    tick_window: int = env_int("TDX_TICK_WINDOW", 60)
    tick_codes_per_cycle: int = env_int("TDX_TICK_CODES_PER_CYCLE", 0)
    speed_window_ms: int = env_int("TDX_SPEED_WINDOW_MS", 60000)
    speed_min_window_ms: int = env_int("TDX_SPEED_MIN_WINDOW_MS", 30000)
    speed_history_max_ms: int = env_int("TDX_SPEED_HISTORY_MAX_MS", 180000)
    server_host: str | None = os.getenv("TDX_SERVER_HOST") or None
    server_port: int | None = env_int("TDX_SERVER_PORT", 0) or None
    server_candidates: str = os.getenv("TDX_SERVER_CANDIDATES", "")
    l2_enabled: bool = env_bool("TDX_L2_ENABLED", False)
    l2_server_host: str = os.getenv("TDX_L2_SERVER_HOST", "124.71.222.84").strip()
    l2_server_port: int = env_int("TDX_L2_SERVER_PORT", 7719)
    l2_server_candidates: str = os.getenv("TDX_L2_SERVER_CANDIDATES", DEFAULT_L2_SERVER_CANDIDATES)
    l2_timeout_seconds: int = env_int("TDX_L2_TIMEOUT_SECONDS", 3)
    l2_probe_interval_ms: int = env_int("TDX_L2_PROBE_INTERVAL_MS", 30000)
    l2_required: bool = env_bool("TDX_L2_REQUIRED", False)
    probe_symbol: str = normalize_code(os.getenv("TDX_PROBE_SYMBOL", "000001")) or "000001"
    l2_username: str = os.getenv("TDX_L2_USERNAME", "").strip()
    l2_password: str = os.getenv("TDX_L2_PASSWORD", "").strip()
    l2_helper_enabled: bool = env_bool("TDX_L2_HELPER_ENABLED", False)
    l2_helper_exe_path: str = env_path("TDX_L2_HELPER_EXE_PATH", default_helper_exe_path())
    l2_helper_tdx_root: str = env_path("TDX_L2_HELPER_TDX_ROOT", r"D:\APP_SOFT\TDX")
    l2_helper_buffer_size: int = env_int("TDX_L2_HELPER_BUFFER_SIZE", 4096)
    l2_helper_heartbeat_interval_ms: int = env_int("TDX_L2_HELPER_HEARTBEAT_INTERVAL_MS", 1000)
    l2_helper_probe_login_state: bool = env_bool("TDX_L2_HELPER_PROBE_LOGIN_STATE", False)
    l2_helper_stable_loginret_surface: bool = env_bool("TDX_L2_HELPER_STABLE_LOGINRET_SURFACE", False)
    l2_helper_login_function: str = os.getenv("TDX_L2_HELPER_LOGIN_FUNCTION", "").strip().lower()
    l2_helper_login_profile: str = os.getenv("TDX_L2_HELPER_LOGIN_PROFILE", "").strip()
    l2_helper_login_arg1: str = os.getenv("TDX_L2_HELPER_LOGIN_ARG1", "")
    l2_helper_login_arg2: str = os.getenv("TDX_L2_HELPER_LOGIN_ARG2", "")
    l2_helper_login_arg3: str = os.getenv("TDX_L2_HELPER_LOGIN_ARG3", "")
    l2_helper_login_arg4: str = os.getenv("TDX_L2_HELPER_LOGIN_ARG4", "")
    l2_helper_setl2_arg1: str = os.getenv("TDX_L2_HELPER_SETL2_ARG1", "")
    l2_helper_setl2_arg2: str = os.getenv("TDX_L2_HELPER_SETL2_ARG2", "")
    l2_helper_setl2_arg3: str = os.getenv("TDX_L2_HELPER_SETL2_ARG3", "")
    official_cache_depth_enabled: bool = env_bool("TDX_OFFICIAL_CACHE_DEPTH_ENABLED", True)
    official_cache_root: str = env_path("TDX_OFFICIAL_CACHE_ROOT", r"D:\APP_SOFT\TDX\T0002\hq_cache")
    l2_provider: str = os.getenv("L2_PROVIDER", "").strip().lower()
    qmt_l2_enabled: bool = env_bool("QMT_L2_ENABLED", False)
    qmt_l2_code_limit: int = env_int("QMT_L2_CODE_LIMIT", 80)
    qmt_l2_poll_interval_ms: int = env_int("QMT_L2_POLL_INTERVAL_MS", 600)
    qmt_l2_require_official: bool = env_bool("QMT_L2_REQUIRE_OFFICIAL", True)


class TdxL2Bridge:
    helper_restart_base_ms = 1000
    helper_restart_max_ms = 30000
    helper_stop_timeout_ms = 5000
    helper_stage_timeout_ms = 25000
    helper_boot_timeout_ms = 15000
    helper_login_retry_window_ms = 6000

    # 财务数据（市值/PE/PB 计算原料）后台刷新间隔
    finance_refresh_interval_ms = 30 * 60 * 1000
    # 资金流（主力/大单/中单/小单）广播间隔：累计值变化慢，低频推送
    fund_flow_broadcast_interval_ms = 5 * 1000

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.clients: set[Any] = set()
        self.client_pools: dict[Any, list[str]] = {}
        self.client_queues: dict[Any, _ClientSendQueue] = {}
        self.fetch_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.quote_client = None
        self.tdx_connected = False
        self.latest_quotes: dict[str, str] = {}
        self.latest_depth: dict[str, str] = {}
        self.tick_seen_keys: dict[str, set[str]] = defaultdict(set)
        self.tick_seen_queues: dict[str, deque[str]] = defaultdict(deque)
        self.quote_price_history: dict[str, deque[tuple[int, float]]] = defaultdict(deque)
        self.full_state_requested = True
        self.tick_cursor = 0
        self.tick_fetch_supported = True
        self.tick_fetch_warning_emitted = False
        self._last_finance_refresh_ts = 0
        self._finance_refresh_in_progress = False
        self._last_fund_flow_broadcast_ts = 0
        self._last_fund_flow_date = ""
        self.last_tick_error = ""
        self.current_quote_batch_size = self.clamp_quote_batch_size(self.config.quote_batch_size)
        self.healthy_fetch_cycles = 0
        self._manual_server: tuple[str, int] | None = None
        self.active_server: tuple[str, int] | None = None
        self.l2_probe_cursor = 0
        self.qmt_l2_provider = (
            QmtL2Provider(require_official=self.config.qmt_l2_require_official)
            if self.config.l2_provider == "qmt" and self.config.qmt_l2_enabled
            else None
        )
        self.latest_l2_status_payload = ""
        self.latest_quote_stats = QuoteFetchStats()
        self.last_quote_cycle_ts = 0
        self.last_quote_error = ""
        # 高频 WARNING 节流（2026-08-06）：同一缺失代码集合 / 同一重试失败代码在冷却窗口内
        # 只记一条，防止持续故障（如个别 TDX 不支持代码）每轮刷屏打爆日志。
        self._partial_data_warn_ts: dict[tuple[str, ...], float] = {}
        self._refetch_fail_warn_ts: dict[str, float] = {}
        self._warn_cooldown_s = 60.0
        self.opening_raw_quote_sink = OpeningRawQuoteFileSink(
            os.path.join(default_log_dir(), "opening-raw-quotes")
        )
        self.last_qmt_l2_poll_ts = 0
        self.cached_qmt_l2_snapshot: tuple[list[dict[str, Any]], list[dict[str, Any]]] = ([], [])
        self.helper_process: asyncio.subprocess.Process | None = None
        self.helper_runtime_root: str | None = None
        self.helper_launch_count = 0
        self.helper_consecutive_failures = 0
        self.official_cache_reader = (
            OfficialHQCacheDepthReader(self.config.official_cache_root)
            if self.config.official_cache_depth_enabled and os.path.isdir(self.config.official_cache_root)
            else None
        )
        self.l2_state: dict[str, Any] = {
            "enabled": self.config.l2_enabled,
            "host": self.config.l2_server_host if self.config.l2_enabled else "",
            "port": self.config.l2_server_port if self.config.l2_enabled else 0,
            "status": "disabled" if not self.config.l2_enabled else "pending",
            "message": "L2 disabled" if not self.config.l2_enabled else "L2 provider pending",
            "lastProbeTs": 0,
            "fallbackActive": False,
            "runtime": self.build_runtime_state(),
        }
        if self.qmt_l2_provider:
            self.l2_state.update(
                {
                    "provider": "qmt",
                    "status": "pending",
                    "message": "QMT L2 provider pending",
                    "fallbackActive": True,
                }
            )

        if self.config.l2_username or self.config.l2_password:
            logger.warning(
                "TDX_L2_USERNAME / TDX_L2_PASSWORD 已配置，但当前 mootdx/tdxpy 公共 API 未暴露显式登录接口，bridge 暂未实际应用该凭据。"
            )
        if self.config.official_cache_depth_enabled and not self.official_cache_reader:
            logger.warning(
                "TDX_OFFICIAL_CACHE_DEPTH_ENABLED 已开启，但官方缓存目录不可用: %s",
                self.config.official_cache_root,
            )

        # Backend collector subscription pool (Phase 2)
        self._backend_pool_codes: list[str] = []
        self._backend_pool_ts: int = 0
        self._backend_pool_lock = asyncio.Lock()
        self._backend_cached_quotes: list[dict[str, Any]] = []
        self._backend_cached_depth: list[dict[str, Any]] = []
        self._backend_cached_stats: Any = None

        # 无数据代码挂起（2026-08-12：688836 新股未上市 TDX 无数据，含它的
        # 批量行情请求整批返回空——连续失败 N 次挂起，避免每轮重复请求 + 拖累
        # 同批其他股票；到期自动重试，上市后有数据自动恢复）
        self._dead_codes: dict[str, float] = {}  # code -> 下次重试时间戳(ms)
        self._dead_fail_counts: dict[str, int] = {}

    def is_code_halted(self, code: str, now_ms_value: int) -> bool:
        """代码是否处于无数据挂起（未到重试时间）。"""
        return now_ms_value < self._dead_codes.get(code, 0)

    def halt_code(self, code: str, now_ms_value: int) -> None:
        """记录一次单只请求失败；连续失败达阈值后挂起（dead_code_retry_ms 后重试）。"""
        count = self._dead_fail_counts.get(code, 0) + 1
        if count >= self.config.dead_code_max_failures:
            self._dead_codes[code] = now_ms_value + self.config.dead_code_retry_ms
            self._dead_fail_counts.pop(code, None)
            logger.warning(
                "quote code halted (no data after %s attempts): %s; retry in %ss",
                count,
                code,
                self.config.dead_code_retry_ms / 1000.0,
            )
        else:
            self._dead_fail_counts[code] = count

    def unhalt_code(self, code: str) -> None:
        """单只请求成功（拿到数据）后清除挂起/失败计数。"""
        self._dead_codes.pop(code, None)
        self._dead_fail_counts.pop(code, None)

    def halted_codes(self, now_ms_value: int) -> list[str]:
        """当前处于挂起窗口内的代码列表。"""
        return [code for code, retry_at in self._dead_codes.items() if now_ms_value < retry_at]

    def prune_quote_speed_history(self, code: str, current_ts: int) -> deque[tuple[int, float]]:
        history = self.quote_price_history[code]
        history_window = max(self.config.speed_history_max_ms, self.config.speed_window_ms)
        cutoff = current_ts - history_window
        while history and history[0][0] < cutoff:
            history.popleft()
        return history

    def compute_quote_speed(self, code: str, price: float, source_ts: int, row: dict[str, Any]) -> float:
        explicit_speed = to_optional_number(
            pick(row, "speed", "rise_speed", "riseSpeed", "speed_pct", "speedPct")
        )
        if explicit_speed is not None:
            return round(explicit_speed, 4)

        if price <= 0:
            return 0.0

        history = self.prune_quote_speed_history(code, source_ts)
        if history and history[-1][0] == source_ts:
            history[-1] = (source_ts, price)
        else:
            history.append((source_ts, price))

        target_ts = source_ts - self.config.speed_window_ms
        base_ts = 0
        base_price = 0.0

        for ts, historic_price in history:
            if ts <= target_ts and historic_price > 0:
                base_ts = ts
                base_price = historic_price
            else:
                break

        if base_price <= 0:
            if len(history) < 2:
                return 0.0

            oldest_ts, oldest_price = history[0]
            span_ms = source_ts - oldest_ts
            if oldest_price <= 0 or span_ms < self.config.speed_min_window_ms:
                return 0.0

            delta_pct = (price - oldest_price) / oldest_price * 100
            return round(delta_pct * (self.config.speed_window_ms / span_ms), 4)

        span_ms = source_ts - base_ts
        if span_ms <= 0:
            return 0.0

        delta_pct = (price - base_price) / base_price * 100
        if span_ms != self.config.speed_window_ms:
            delta_pct *= self.config.speed_window_ms / span_ms
        return round(delta_pct, 4)

    def helper_login_args(self) -> tuple[str, str, str, str]:
        return (
            self.config.l2_helper_login_arg1,
            self.config.l2_helper_login_arg2,
            self.config.l2_helper_login_arg3,
            self.config.l2_helper_login_arg4,
        )

    def helper_setl2_args(self) -> tuple[str, str, str]:
        return (
            self.config.l2_helper_setl2_arg1,
            self.config.l2_helper_setl2_arg2,
            self.config.l2_helper_setl2_arg3,
        )

    def helper_login_requested(self) -> bool:
        return bool(self.config.l2_helper_login_function)

    def helper_use_stable_loginret_surface(self) -> bool:
        return self.helper_login_requested() or self.config.l2_helper_stable_loginret_surface

    def helper_should_isolate_runtime(self) -> bool:
        return self.helper_use_stable_loginret_surface()

    def build_runtime_state(self) -> dict[str, Any]:
        login_args = self.helper_login_args()
        setl2_args = self.helper_setl2_args()
        enabled = self.config.l2_helper_enabled
        return {
            "enabled": enabled,
            "status": "disabled" if not enabled else "idle",
            "message": "x86 helper disabled" if not enabled else "x86 helper not started",
            "exePath": self.config.l2_helper_exe_path if enabled else "",
            "helperAppBase": "",
            "tdxRoot": self.config.l2_helper_tdx_root if enabled else "",
            "bufferSize": self.config.l2_helper_buffer_size,
            "heartbeatIntervalMs": self.config.l2_helper_heartbeat_interval_ms,
            "probeLoginState": self.config.l2_helper_probe_login_state,
            "stableLoginRetSurface": self.helper_use_stable_loginret_surface(),
            "loginFunction": self.config.l2_helper_login_function,
            "loginProfile": self.config.l2_helper_login_profile,
            "loginArgCount": sum(1 for value in login_args if value),
            "loginConfigured": self.helper_login_requested(),
            "setL2ArgCount": sum(1 for value in setl2_args if value),
            "setL2Configured": any(setl2_args),
            "pid": 0,
            "active": False,
            "launchCount": 0,
            "restartCount": 0,
            "startedAt": 0,
            "lastEvent": "",
            "lastEventTs": 0,
            "lastGeneratedAt": "",
            "lastHeartbeatTs": 0,
            "heartbeatCount": 0,
            "uptimeMs": 0,
            "sampleIndex": -1,
            "lastExitCode": None,
            "nextRestartTs": 0,
            "lastError": "",
            "stderrLineCount": 0,
            "lastStderrTs": 0,
            "runtimeLayout": {},
            "modules": [],
            "tcInit": {},
            "probeGetLoginRet": {},
            "probeGetRightInfo": {},
            "probeLoginRetText": "",
            "loginRequest": {},
            "loginResult": {},
            "postLoginGetLoginRet": {},
            "postLoginGetRightInfo": {},
            "postLoginRetText": "",
            "lastGetL2Info": {},
            "deepRegister": {},
            "deepStart": {},
            "lastDeepCallback": {},
            "lastDeepCallbackTs": 0,
            "deepCallbackCount": 0,
        }

    def runtime_state(self) -> dict[str, Any]:
        runtime = self.l2_state.get("runtime")
        if not isinstance(runtime, dict):
            runtime = self.build_runtime_state()
            self.l2_state["runtime"] = runtime
        return runtime

    def update_runtime_state(self, **updates: Any) -> None:
        runtime = self.runtime_state()
        runtime.update(updates)

    def build_helper_command(self, exe_path: str | None = None) -> list[str]:
        command = [
            exe_path or self.config.l2_helper_exe_path,
            "host-runtime",
            "--event-stream",
            "--sample-count",
            "0",
            "--tdx-root",
            self.config.l2_helper_tdx_root,
            "--buffer-size",
            str(self.config.l2_helper_buffer_size),
            "--heartbeat-interval-ms",
            str(self.config.l2_helper_heartbeat_interval_ms),
        ]
        if self.config.l2_helper_probe_login_state:
            command.append("--probe-login-state")
        if self.helper_use_stable_loginret_surface():
            command.append("--stable-loginret-surface")
        if self.config.l2_helper_login_function:
            command.extend(["--login-function", self.config.l2_helper_login_function])
        if self.config.l2_helper_login_profile:
            command.extend(["--login-profile", self.config.l2_helper_login_profile])
        for index, value in enumerate(self.helper_login_args(), start=1):
            if value:
                command.extend([f"--login-arg{index}", value])
        for index, value in enumerate(self.helper_setl2_args(), start=1):
            if value:
                command.extend([f"--setl2-arg{index}", value])
        return command

    def extract_buffer_text(self, report: Any) -> str:
        if not isinstance(report, dict):
            return ""
        arg1 = report.get("arg1")
        if not isinstance(arg1, dict):
            return ""
        text = str(arg1.get("gb18030Preview") or arg1.get("ansiPreview") or "").strip()
        return text

    def prepare_helper_runtime_exe(self) -> str:
        source_exe = self.config.l2_helper_exe_path
        if not self.helper_should_isolate_runtime():
            return source_exe

        source_dir = os.path.dirname(source_exe)
        if not source_dir or not os.path.isdir(source_dir):
            return source_exe

        self.cleanup_helper_runtime_dir()
        runtime_root = tempfile.mkdtemp(prefix="tdx-helper-runtime-")
        target_dir = os.path.join(runtime_root, os.path.basename(source_dir))
        shutil.copytree(source_dir, target_dir)
        self.helper_runtime_root = runtime_root
        return os.path.join(target_dir, os.path.basename(source_exe))

    def cleanup_helper_runtime_dir(self) -> None:
        root = self.helper_runtime_root
        self.helper_runtime_root = None
        if not root:
            return
        shutil.rmtree(root, ignore_errors=True)

    def helper_restart_delay_ms(self) -> int:
        exponent = max(0, self.helper_consecutive_failures - 1)
        return min(self.helper_restart_max_ms, self.helper_restart_base_ms * (2**exponent))

    async def sleep_or_stop(self, delay_ms: int) -> None:
        if delay_ms <= 0:
            return
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=delay_ms / 1000)
        except asyncio.TimeoutError:
            pass

    def summarize_buffer_snapshot(self, snapshot: Any) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return {}
        return {
            "size": to_int(snapshot.get("size")),
            "nonZeroBytes": to_int(snapshot.get("nonZeroBytes")),
            "ansiPreview": str(snapshot.get("ansiPreview") or "")[:96],
            "gb18030Preview": str(snapshot.get("gb18030Preview") or "")[:96],
        }

    def summarize_call_report(self, report: Any, include_buffers: bool = False) -> dict[str, Any]:
        if not isinstance(report, dict):
            return {}
        summary = {
            "invoked": bool(report.get("invoked")),
            "elapsedMs": to_int(report.get("elapsedMs")),
            "returnValue": to_int(report.get("returnValue")),
            "win32LastError": to_int(report.get("win32LastError")),
            "errorType": str(report.get("errorType") or ""),
            "error": str(report.get("error") or ""),
        }
        if "bufferSize" in report:
            summary["bufferSize"] = to_int(report.get("bufferSize"))
        if "function" in report:
            summary["function"] = str(report.get("function") or "")
        if "skipped" in report:
            summary["skipped"] = bool(report.get("skipped"))
        if "skipReason" in report:
            summary["skipReason"] = str(report.get("skipReason") or "")
        if include_buffers:
            if "arg1" in report:
                summary["arg1"] = self.summarize_buffer_snapshot(report.get("arg1"))
            if "arg2" in report:
                summary["arg2"] = self.summarize_buffer_snapshot(report.get("arg2"))
            if "arg3" in report:
                summary["arg3"] = self.summarize_buffer_snapshot(report.get("arg3"))
        return summary

    def summarize_runtime_layout(self, layout: Any) -> dict[str, Any]:
        if not isinstance(layout, dict):
            return {}
        return {
            "ok": bool(layout.get("ok")),
            "helperDirectory": str(layout.get("appBaseDirectory") or layout.get("helperDirectory") or ""),
            "currentDirectory": str(layout.get("currentDirectory") or ""),
            "tcPluginsDllCount": to_int(layout.get("tcPluginsDllCount")),
            "etradeXmbPresent": bool(layout.get("etradeXmbPresent")),
            "tcOemXmbPresent": bool(layout.get("tcOemXmbPresent")),
            "usersProfilePresent": bool(layout.get("usersProfilePresent")),
            "syncedItemCount": len(layout.get("syncedItems") or []),
            "errorCount": len(layout.get("errors") or []),
        }

    def summarize_modules(self, modules: Any) -> list[dict[str, Any]]:
        summarized: list[dict[str, Any]] = []
        if not isinstance(modules, list):
            return summarized
        for module in modules:
            if not isinstance(module, dict):
                continue
            summarized.append(
                {
                    "name": str(module.get("name") or ""),
                    "path": str(module.get("path") or ""),
                    "exists": bool(module.get("exists")),
                    "loaded": bool(module.get("loaded")),
                    "error": str(module.get("error") or "")[:200],
                }
            )
        return summarized

    def apply_helper_event(self, event_type: str, payload: dict[str, Any]) -> None:
        generated_at = str(payload.get("generatedAt") or "")
        runtime = self.runtime_state()
        current_status = str(runtime.get("status") or "")
        updates: dict[str, Any] = {
            "lastEvent": event_type,
            "lastEventTs": now_ms(),
            "lastGeneratedAt": generated_at,
        }

        if event_type == "boot":
            self.helper_consecutive_failures = 0
            updates.update(
                {
                    "status": "booting",
                    "message": "x86 helper booted",
                    "processArchitecture": str(payload.get("processArchitecture") or ""),
                    "pointerSizeBits": to_int(payload.get("pointerSizeBits")),
                    "tcPath": str(payload.get("tcPath") or ""),
                    "deepPath": str(payload.get("deepPath") or ""),
                    "runtimeLayout": self.summarize_runtime_layout(payload.get("runtimeLayout")),
                    "lastError": "",
                }
            )
        elif event_type == "modules":
            session_error = str(payload.get("sessionError") or payload.get("error") or "")
            updates.update(
                {
                    "status": "running" if not session_error else "module_error",
                    "message": "helper modules loaded" if not session_error else session_error,
                    "modules": self.summarize_modules(payload.get("modules")),
                    "lastError": session_error,
                }
            )
        elif event_type == "tc_init":
            report = self.summarize_call_report(payload.get("result"))
            error = str(report.get("error") or "")
            updates.update(
                {
                    "status": "initialized" if not error else "init_error",
                    "message": "TC_Init_Environ completed" if not error else error,
                    "tcInit": report,
                    "lastError": error,
                }
            )
        elif event_type == "probe_login_state":
            login_ret = self.summarize_call_report(payload.get("getLoginRet"), include_buffers=True)
            updates.update(
                {
                    "status": "running",
                    "message": "helper login-state probe captured",
                    "probeGetLoginRet": login_ret,
                    "probeGetRightInfo": self.summarize_call_report(payload.get("getRightInfo"), include_buffers=True),
                    "probeLoginRetText": self.extract_buffer_text(login_ret),
                }
            )
        elif event_type == "post_login_state":
            login_ret = self.summarize_call_report(payload.get("getLoginRet"), include_buffers=True)
            login_ret_text = self.extract_buffer_text(login_ret)
            updates.update(
                {
                    "status": "auth_feedback" if login_ret_text else "running",
                    "message": f"helper login feedback: {login_ret_text}" if login_ret_text else "helper post-login state captured",
                    "postLoginGetLoginRet": login_ret,
                    "postLoginGetRightInfo": self.summarize_call_report(payload.get("getRightInfo"), include_buffers=True),
                    "postLoginRetText": login_ret_text,
                }
            )
        elif event_type == "tc_login":
            report = self.summarize_call_report(payload.get("result"))
            error = str(report.get("error") or "")
            updates.update(
                {
                    "status": "login_error" if error else "running",
                    "message": "helper login invoked" if not error else error,
                    "loginRequest": payload.get("request") if isinstance(payload.get("request"), dict) else {},
                    "loginResult": report,
                    "lastError": error,
                }
            )
        elif event_type == "tc_setl2":
            report = self.summarize_call_report(payload.get("result"))
            error = str(report.get("error") or "")
            updates.update(
                {
                    "status": "setl2_error" if error else "running",
                    "message": "helper setl2 invoked" if not error else error,
                    "setL2Args": payload.get("args") if isinstance(payload.get("args"), dict) else {},
                    "setL2Result": report,
                    "lastError": error,
                }
            )
        elif event_type in {"getl2info", "heartbeat"}:
            report = self.summarize_call_report(
                payload.get("result") if event_type == "getl2info" else payload.get("getL2Info"),
                include_buffers=True,
            )
            updates.update(
                {
                    "status": "live" if event_type == "heartbeat" else "running",
                    "message": "x86 helper heartbeat active" if event_type == "heartbeat" else "TC_GetL2Info captured",
                    "lastGetL2Info": report,
                    "sampleIndex": to_int(payload.get("sampleIndex"), -1),
                    "uptimeMs": to_int(payload.get("uptimeMs")),
                    "lastError": str(report.get("error") or ""),
                }
            )
            if event_type == "heartbeat":
                updates["lastHeartbeatTs"] = now_ms()
                updates["heartbeatCount"] = to_int(runtime.get("heartbeatCount")) + 1
        elif event_type == "deep_register":
            report = self.summarize_call_report(payload.get("result"))
            error = str(report.get("error") or "")
            updates.update(
                {
                    "status": "deep_register_error" if error else ("live" if current_status == "live" else "running"),
                    "message": "TDXDeep callback registered" if not error else error,
                    "deepRegister": report,
                    "lastError": error,
                }
            )
        elif event_type == "deep_start":
            report = self.summarize_call_report(payload.get("result"))
            error = str(report.get("error") or "")
            updates.update(
                {
                    "status": "deep_start_error" if error else ("live" if current_status == "live" else "running"),
                    "message": "TDXDeep start invoked" if not error else error,
                    "deepStart": report,
                    "lastError": error,
                }
            )
        elif event_type == "deep_callback":
            callback_payload = payload.get("data")
            if not isinstance(callback_payload, dict):
                callback_payload = payload.get("callback")
            if not isinstance(callback_payload, dict):
                callback_payload = {key: value for key, value in payload.items() if key != "generatedAt"}
            updates.update(
                {
                    "status": "live" if current_status == "live" else "running",
                    "message": "TDXDeep callback active",
                    "lastDeepCallback": callback_payload,
                    "lastDeepCallbackTs": now_ms(),
                    "deepCallbackCount": to_int(runtime.get("deepCallbackCount")) + 1,
                }
            )
        elif event_type == "shutdown":
            error = str(payload.get("error") or "")
            ok = bool(payload.get("ok"))
            updates.update(
                {
                    "status": "stopping" if ok else "shutdown_error",
                    "message": "x86 helper shutting down" if ok else error or "x86 helper shutdown reported an error",
                    "uptimeMs": to_int(payload.get("uptimeMs")),
                    "sampleCount": to_int(payload.get("sampleCount")),
                    "lastError": error,
                }
            )
        elif event_type == "error":
            error = str(payload.get("error") or "x86 helper reported an error")
            updates.update(
                {
                    "status": "error",
                    "message": error,
                    "lastError": error,
                    "errorType": str(payload.get("errorType") or ""),
                }
            )
        else:
            updates.update(
                {
                    "status": "running",
                    "message": f"x86 helper event: {event_type}",
                }
            )

        self.update_runtime_state(**updates)

    async def consume_helper_stdout(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while not stream.at_eof():
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError as error:
                self.update_runtime_state(
                    status="protocol_error",
                    message="x86 helper emitted invalid NDJSON",
                    lastEvent="invalid_ndjson",
                    lastEventTs=now_ms(),
                    lastError=f"invalid_ndjson:{error.msg}",
                )
                logger.warning("l2 helper emitted invalid NDJSON: %s", error)
                continue

            event_type = str(event.get("event") or "").strip()
            payload = event.get("payload")
            if not event_type or not isinstance(payload, dict):
                self.update_runtime_state(
                    status="protocol_error",
                    message="x86 helper emitted an incomplete event",
                    lastEvent="invalid_event",
                    lastEventTs=now_ms(),
                    lastError="invalid_event_shape",
                )
                logger.warning("l2 helper emitted an incomplete event")
                continue
            self.apply_helper_event(event_type, payload)

    async def consume_helper_stderr(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while not stream.at_eof():
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            runtime = self.runtime_state()
            first_stderr = to_int(runtime.get("stderrLineCount")) == 0
            self.update_runtime_state(
                stderrLineCount=to_int(runtime.get("stderrLineCount")) + 1,
                lastStderrTs=now_ms(),
            )
            if first_stderr:
                logger.warning("l2 helper emitted stderr output")

    async def stop_helper_process(self, process: asyncio.subprocess.Process | None = None) -> None:
        active = process or self.helper_process
        if active is None or active.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            active.terminate()
        try:
            await asyncio.wait_for(active.wait(), timeout=self.helper_stop_timeout_ms / 1000)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                active.kill()
            with contextlib.suppress(Exception):
                await active.wait()

    async def wait_for_helper_hang(self, process: asyncio.subprocess.Process) -> str:
        while not self.stop_event.is_set():
            if process.returncode is not None:
                return ""

            runtime = self.runtime_state()
            started_at = to_int(runtime.get("startedAt"))
            now = now_ms()
            last_event_ts = to_int(runtime.get("lastEventTs"))
            last_heartbeat_ts = to_int(runtime.get("lastHeartbeatTs"))
            last_deep_callback_ts = to_int(runtime.get("lastDeepCallbackTs"))
            last_event = str(runtime.get("lastEvent") or "")
            status = str(runtime.get("status") or "")
            login_configured = bool(runtime.get("loginConfigured"))
            setl2_configured = bool(runtime.get("setL2Configured"))
            login_result = runtime.get("loginResult") if isinstance(runtime.get("loginResult"), dict) else {}
            login_error = str(login_result.get("error") or "")
            login_error_type = str(login_result.get("errorType") or "")
            post_login_ret_text = str(runtime.get("postLoginRetText") or "")

            if last_event_ts <= 0:
                if started_at > 0 and now - started_at > self.helper_boot_timeout_ms:
                    return "helper produced no startup events within boot timeout"
            else:
                stage_timeout_ms = self.helper_stage_timeout_ms
                heartbeat_timeout_ms = max(
                    self.helper_stage_timeout_ms,
                    self.config.l2_helper_heartbeat_interval_ms * 3,
                )
                last_live_signal_ts = max(last_heartbeat_ts, last_deep_callback_ts)
                if last_live_signal_ts > 0 and now - last_live_signal_ts > heartbeat_timeout_ms:
                    signal_name = "heartbeat/deep callback" if last_deep_callback_ts > 0 else "heartbeat"
                    return f"helper {signal_name} stalled for {now - last_live_signal_ts} ms"

                login_feedback_events = {"post_login_state", "getl2info", "heartbeat", "deep_callback"}
                login_feedback_deadline_exceeded = (
                    started_at > 0 and now - started_at > self.helper_login_retry_window_ms
                )
                if (
                    login_configured
                    and last_event in login_feedback_events
                    and login_feedback_deadline_exceeded
                    and not post_login_ret_text
                    and (login_error_type or login_error)
                ):
                    return "helper login produced no usable auth feedback; retrying"

                staged_events = {
                    "boot",
                    "modules",
                    "tc_init",
                    "probe_login_state",
                    "tc_login",
                    "post_login_state",
                    "tc_setl2",
                    "deep_register",
                    "deep_start",
                    "getl2info",
                }
                expected_steady_state = (
                    last_event == "heartbeat"
                    or last_event == "deep_callback"
                    or status == "live"
                    or (
                        last_event == "getl2info"
                        and not login_configured
                        and not setl2_configured
                    )
                )
                if not expected_steady_state and last_event in staged_events and now - last_event_ts > stage_timeout_ms:
                    return f"helper stalled after {last_event} for {now - last_event_ts} ms"

            await asyncio.sleep(1.0)

        return ""

    async def helper_loop(self) -> None:
        if not self.config.l2_helper_enabled:
            return

        while not self.stop_event.is_set():
            try:
                exe_path = self.prepare_helper_runtime_exe()
            except Exception as error:
                self.cleanup_helper_runtime_dir()
                self.update_runtime_state(
                    status="spawn_error",
                    message=f"failed to prepare x86 helper runtime: {error}",
                    active=False,
                    pid=0,
                    nextRestartTs=now_ms() + self.helper_restart_max_ms,
                    lastError=str(error),
                )
                logger.warning("failed to prepare l2 helper runtime: %s", error)
                await self.sleep_or_stop(self.helper_restart_max_ms)
                continue

            command = self.build_helper_command(exe_path)
            exe_path = command[0] if command else ""
            if not exe_path:
                self.cleanup_helper_runtime_dir()
                self.update_runtime_state(
                    status="spawn_error",
                    message="x86 helper executable path is empty",
                    active=False,
                    pid=0,
                    nextRestartTs=now_ms() + self.helper_restart_max_ms,
                    lastError="helper_exe_path_empty",
                )
                await self.sleep_or_stop(self.helper_restart_max_ms)
                continue
            if not os.path.exists(exe_path):
                self.cleanup_helper_runtime_dir()
                self.update_runtime_state(
                    status="spawn_error",
                    message=f"x86 helper executable not found: {exe_path}",
                    active=False,
                    pid=0,
                    nextRestartTs=now_ms() + self.helper_restart_max_ms,
                    lastError="helper_executable_not_found",
                )
                logger.warning("l2 helper executable not found: %s", exe_path)
                await self.sleep_or_stop(self.helper_restart_max_ms)
                continue

            self.helper_launch_count += 1
            self.update_runtime_state(
                status="starting",
                message="starting x86 helper subprocess",
                active=False,
                pid=0,
                exePath=exe_path,
                helperAppBase=os.path.dirname(exe_path),
                launchCount=self.helper_launch_count,
                restartCount=max(0, self.helper_launch_count - 1),
                startedAt=now_ms(),
                nextRestartTs=0,
                lastExitCode=None,
            )

            logger.info(
                "starting l2 helper: exe=%s tdx_root=%s buffer_size=%s heartbeat_interval_ms=%s probe_login_state=%s stable_loginret_surface=%s login_function=%s login_profile=%s login_configured=%s setl2_configured=%s",
                exe_path,
                self.config.l2_helper_tdx_root,
                self.config.l2_helper_buffer_size,
                self.config.l2_helper_heartbeat_interval_ms,
                self.config.l2_helper_probe_login_state,
                self.helper_use_stable_loginret_surface(),
                self.config.l2_helper_login_function,
                self.config.l2_helper_login_profile,
                self.helper_login_requested(),
                any(self.helper_setl2_args()),
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=os.path.dirname(exe_path) or None,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as error:
                self.helper_process = None
                self.cleanup_helper_runtime_dir()
                self.helper_consecutive_failures += 1
                delay_ms = self.helper_restart_delay_ms()
                self.update_runtime_state(
                    status="spawn_error",
                    message=f"failed to start x86 helper: {error}",
                    active=False,
                    pid=0,
                    nextRestartTs=now_ms() + delay_ms,
                    lastError=str(error),
                )
                logger.warning("failed to start l2 helper: %s", error)
                await self.sleep_or_stop(delay_ms)
                continue

            self.helper_process = process
            self.update_runtime_state(
                status="running",
                message="x86 helper subprocess started",
                active=True,
                pid=process.pid or 0,
            )

            stdout_task = asyncio.create_task(self.consume_helper_stdout(process.stdout))
            stderr_task = asyncio.create_task(self.consume_helper_stderr(process.stderr))
            wait_task = asyncio.create_task(process.wait())
            stop_task = asyncio.create_task(self.stop_event.wait())
            hang_task = asyncio.create_task(self.wait_for_helper_hang(process))
            hang_reason = ""

            try:
                done, _ = await asyncio.wait(
                    {wait_task, stop_task, hang_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task in done and not wait_task.done():
                    await self.stop_helper_process(process)
                elif hang_task in done and not wait_task.done():
                    with contextlib.suppress(Exception):
                        hang_reason = hang_task.result()
                    self.update_runtime_state(
                        status="hung",
                        message=hang_reason or "x86 helper appears hung; restarting",
                        lastError=hang_reason or "helper_hung",
                    )
                    logger.warning("l2 helper appears hung: %s", hang_reason or "unknown reason")
                    await self.stop_helper_process(process)
                exit_code = await wait_task
            finally:
                stop_task.cancel()
                hang_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task
                with contextlib.suppress(asyncio.CancelledError):
                    await hang_task

            with contextlib.suppress(Exception):
                await stdout_task
            with contextlib.suppress(Exception):
                await stderr_task

            self.helper_process = None
            self.cleanup_helper_runtime_dir()
            self.update_runtime_state(active=False, pid=0, lastExitCode=exit_code)

            if self.stop_event.is_set():
                self.update_runtime_state(
                    status="stopped",
                    message="x86 helper stopped",
                    nextRestartTs=0,
                )
                break

            self.helper_consecutive_failures += 1
            delay_ms = self.helper_restart_delay_ms()
            self.update_runtime_state(
                status="exited" if exit_code == 0 else "failed",
                message=(hang_reason or f"x86 helper exited with code {exit_code}; restarting"),
                nextRestartTs=now_ms() + delay_ms,
                lastError=hang_reason or ("" if exit_code == 0 else f"exit_code:{exit_code}"),
            )
            logger.warning("l2 helper exited with code %s; restart in %sms", exit_code, delay_ms)
            await self.sleep_or_stop(delay_ms)

    def is_l2_server(self, server: tuple[str, int] | None) -> bool:
        return bool(server and self.config.l2_enabled and server in self.l2_candidate_servers())

    def l2_candidate_servers(self) -> list[tuple[str, int]]:
        if not self.config.l2_enabled:
            return []

        candidates: list[tuple[str, int]] = []
        if self.config.l2_server_host and self.config.l2_server_port:
            candidates.append((self.config.l2_server_host, self.config.l2_server_port))

        for pair in parse_server_candidates(self.config.l2_server_candidates):
            if pair not in candidates:
                candidates.append(pair)

        return candidates

    def set_l2_state(self, status: str, message: str, fallback_active: bool) -> None:
        if not self.config.l2_enabled:
            return
        self.l2_state.update(
            {
                "enabled": True,
                "host": self.config.l2_server_host,
                "port": self.config.l2_server_port,
                "status": status,
                "message": message,
                "lastProbeTs": now_ms(),
                "fallbackActive": fallback_active,
            }
        )

    def clamp_quote_batch_size(self, value: int) -> int:
        min_size = max(1, self.config.quote_batch_min_size)
        max_size = max(min_size, self.config.quote_batch_max_size)
        return max(min_size, min(max_size, value))

    def candidate_servers(self) -> list[tuple[str, int]]:
        """显式指定的候选来源：手动选择 / L2 / 环境变量（不含 tdx_hosts.json 服务器池）。"""
        candidates: list[tuple[str, int]] = []

        if self._manual_server:
            candidates.append(self._manual_server)

        if self.config.l2_required:
            candidates.extend(self.l2_candidate_servers())

        if self.config.server_host and self.config.server_port:
            pair = (self.config.server_host, self.config.server_port)
            if pair not in candidates:
                candidates.append(pair)

        for pair in parse_server_candidates(self.config.server_candidates):
            if pair not in candidates:
                candidates.append(pair)

        return candidates

    def pool_candidates(self) -> list[tuple[str, int]]:
        """本地服务器池（tdx_hosts.json）候选：官方现行主站 + 实测兼容券商节点。

        显式候选之外也始终走池，避免回落 mootdx bestip 的"仅测 TCP"路径
        （会把重连带到 TCP 可达但行情返回空的节点上反复失败）。
        """
        candidates: list[tuple[str, int]] = []
        for host in load_tdx_hosts():
            pair = (host["ip"], host["port"])
            if pair not in candidates:
                candidates.append(pair)
        return candidates

    def _rank_pool_servers_by_latency(self) -> list[tuple[str, int]]:
        """并行探测池内节点，按行情可用 + TCP 延迟排序。

        scan_tdx_servers 的排序规则天然满足需求：当前连接（若仍行情可用）置顶
        保持粘性，其后按 tcpMs 升序。探测异常或无可用节点时返回空列表，
        调用方回退池文件顺序。
        """
        try:
            results = self.scan_tdx_servers()
        except Exception as error:  # noqa: BLE001
            logger.warning("ranked pool scan failed, fallback to file order: %s", error)
            return []
        return [(r["ip"], int(r["port"])) for r in results if r["quoteOk"]]

    def next_l2_probe_server(self) -> tuple[str, int] | None:
        candidates = self.l2_candidate_servers()
        if not candidates:
            return None
        server = candidates[self.l2_probe_cursor % len(candidates)]
        self.l2_probe_cursor = (self.l2_probe_cursor + 1) % len(candidates)
        return server

    def aggregate_pool(self) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for codes in self.client_pools.values():
            for code in codes:
                if not code or code in seen:
                    continue
                seen.add(code)
                merged.append(code)
        return merged

    async def ensure_client(self) -> None:
        if self.quote_client is not None:
            return

        last_error: Exception | None = None

        # 候选顺序：显式指定（手动选择/L2/环境变量）优先；服务器池默认按
        # "行情可用 + 延迟最低"排序（启动/重连时并行实测一遍），让连接落在
        # 最快节点上而非池文件首位；手动选择时跳过测速直接连用户选的节点。
        explicit = self.candidate_servers()
        pool = self.pool_candidates()
        if pool and not self._manual_server:
            ranked = await asyncio.to_thread(self._rank_pool_servers_by_latency)
            if ranked:
                pool = ranked

        for server in explicit + pool or [None]:
            try:
                def _create_client():
                    timeout_seconds = (
                        self.config.l2_timeout_seconds
                        if self.is_l2_server(server)
                        else self.config.timeout_seconds
                    )
                    client = Quotes.factory(
                        market="std",
                        server=server,
                        bestip=self.config.use_bestip and server is None,
                        heartbeat=True,
                        auto_retry=True,
                        timeout=timeout_seconds,
                    )
                    probe_frame = client.quotes(symbol=[self.config.probe_symbol])
                    if not frame_to_records(probe_frame):
                        client.close()
                        raise RuntimeError(
                            f"probe_quote_empty:{self.config.probe_symbol}"
                        )
                    return client

                self.quote_client = await asyncio.to_thread(_create_client)
                self.tdx_connected = True
                # bestip 模式下从连接后的 client 取实际 IP
                if server is None and hasattr(self.quote_client, "server"):
                    actual = self.quote_client.server
                    if isinstance(actual, (list, tuple)) and len(actual) >= 2:
                        self.active_server = (str(actual[0]), int(actual[1]))
                    else:
                        self.active_server = server
                else:
                    self.active_server = server
                if self.is_l2_server(server):
                    self.set_l2_state("live", "L2 server returned quote data", False)
                elif self.config.l2_enabled:
                    self.set_l2_state(
                        self.l2_state.get("status") or "fallback",
                        self.l2_state.get("message") or "L2 unavailable, using fallback quote server",
                        True,
                    )
                if server:
                    logger.info("mootdx client connected via %s:%s", server[0], server[1])
                else:
                    logger.info("mootdx client connected via bestip")
                return
            except Exception as error:
                last_error = error
                if self.is_l2_server(server):
                    self.set_l2_state(
                        "protocol_pending",
                        f"{server[0]}:{server[1]} connected but standard quote probe returned no usable data: {error}",
                        True,
                    )
                    logger.warning(
                        "L2 server %s:%s is reachable but not usable via standard mootdx quote commands: %s",
                        server[0],
                        server[1],
                        error,
                    )
                    if self.config.l2_required:
                        await self.reset_client()
                        raise error
                logger.warning("failed to connect mootdx server %s: %s", server, error)
                await self.reset_client()

        if last_error:
            raise last_error
        raise RuntimeError("no_tdx_server_available")

    async def probe_l2_server(self, server: tuple[str, int]) -> None:
        try:
            def _probe():
                client = Quotes.factory(
                    market="std",
                    server=server,
                    bestip=False,
                    heartbeat=True,
                    auto_retry=False,
                    timeout=self.config.l2_timeout_seconds,
                )
                try:
                    probe_frame = client.quotes(symbol=[self.config.probe_symbol])
                    return frame_to_records(probe_frame)
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass

            records = await asyncio.to_thread(_probe)
            if records:
                self.set_l2_state("live", f"{server[0]}:{server[1]} returned quote data", False)
                logger.info("L2 probe succeeded via %s:%s rows=%s", server[0], server[1], len(records))
                return

            self.set_l2_state(
                "protocol_pending",
                f"{server[0]}:{server[1]} connected but standard quote probe returned no usable data",
                True,
            )
            logger.warning("L2 probe empty via %s:%s", server[0], server[1])
        except Exception as error:
            self.set_l2_state(
                "protocol_pending",
                f"{server[0]}:{server[1]} probe failed: {error}",
                True,
            )
            logger.warning("L2 probe failed via %s:%s: %s", server[0], server[1], error)

    async def reset_client(self) -> None:
        client = self.quote_client
        self.quote_client = None
        self.tdx_connected = False
        self.active_server = None
        if client is None:
            return
        try:
            await asyncio.to_thread(client.close)
        except Exception:
            pass

    async def handle_client(self, websocket: Any) -> None:
        self.clients.add(websocket)
        self.client_pools[websocket] = []
        queue = _ClientSendQueue(websocket, self.config.client_send_queue_maxsize)
        self.client_queues[websocket] = queue
        try:
            async for message in websocket:
                data = json.loads(message)
                message_type = data.get("type")
                if message_type != "set_hot_pool":
                    continue

                codes: list[str] = []
                seen: set[str] = set()
                for raw_code in data.get("codes", []):
                    code = normalize_code(raw_code)
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    codes.append(code)
                self.client_pools[websocket] = codes
                self.full_state_requested = True
                logger.info("updated hot pool from client: %s", len(codes))
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)
            self.client_pools.pop(websocket, None)
            self.client_queues.pop(websocket, None)
            await queue.close()
            self.full_state_requested = True

    def status_snapshot(self) -> dict[str, Any]:
        pool = self.aggregate_pool()
        active_server = (
            f"{self.active_server[0]}:{self.active_server[1]}" if self.active_server else ""
        )
        return {
            "ok": True,
            "service": "tdx-quote-bridge",
            "serverTs": now_ms(),
            "websocket": {
                "url": f"ws://{self.config.host}:{self.config.port}{self.config.path}",
                "clients": len(self.clients),
                "subscribedCount": len(pool),
            },
            "tdx": {
                "connected": self.tdx_connected,
                "activeServer": active_server,
            },
            "quotes": {
                "received": len(self.latest_quotes),
                "depth": len(self.latest_depth),
                "batchSize": self.current_quote_batch_size,
                "lastCycleTs": self.last_quote_cycle_ts,
                "lastCycle": {
                    "requested": self.latest_quote_stats.requested_codes,
                    "batches": self.latest_quote_stats.batches,
                    "failedBatches": self.latest_quote_stats.failed_batches,
                    "truncatedBatches": self.latest_quote_stats.truncated_batches,
                    "slowBatches": self.latest_quote_stats.slow_batches,
                    "receivedQuotes": self.latest_quote_stats.received_quotes,
                    "receivedDepth": self.latest_quote_stats.received_depth,
                    "elapsedMs": self.latest_quote_stats.elapsed_ms,
                },
                "lastError": self.last_quote_error,
            },
            "tick": {
                # L1 分笔自算链路诊断（非全日完整分笔，不作为资金列来源）
                "fetchSupported": self.tick_fetch_supported,
                "tickWindow": self.config.tick_window,
                "lastError": self.last_tick_error or "",
            },
            "fundFlow": {
                "source": "tdx_fund_flow",
                "accumulatedCodes": len(tdx_fund_flow.snapshot()),
                "lastDate": self._last_fund_flow_date or "",
                "lastBroadcastTs": self._last_fund_flow_broadcast_ts or 0,
                "broadcastIntervalMs": self.fund_flow_broadcast_interval_ms,
            },
            "l2": self.l2_state,
            "logFile": LOG_FILE_PATH,
        }

    def scan_tdx_servers(self) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        file_hosts = load_tdx_hosts()
        if file_hosts:
            all_hosts = [(h["name"], h["ip"], h["port"]) for h in file_hosts]
        else:
            # 回退：tdx_hosts.json 缺失时使用 mootdx/tdxpy 内置列表（已严重过期）
            from mootdx.consts import HQ_HOSTS
            from tdxpy.constants import hq_hosts

            all_hosts = list(hq_hosts) + list(HQ_HOSTS)
        active_addr = f"{self.active_server[0]}:{self.active_server[1]}" if self.active_server else ""

        results: list[dict[str, Any]] = []

        def _probe(name: str, ip: str, port: int) -> dict[str, Any]:
            import socket

            entry: dict[str, Any] = {
                "name": name, "ip": ip, "port": port,
                "tcpMs": None, "quoteOk": False, "isActive": False,
            }
            # TCP test
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.7)
                t0 = time.perf_counter()
                sock.connect((ip, port))
                entry["tcpMs"] = round((time.perf_counter() - t0) * 1000, 1)
                sock.close()
            except Exception:
                return entry

            # Quote test
            try:
                from tdxpy.hq import TdxHq_API

                api = TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=False)
                api.connect(ip, port, time_out=3)
                probe_result = api.get_security_quotes(
                    [(0, self.config.probe_symbol)]
                )
                api.close()
                if probe_result and len(probe_result) > 0:
                    entry["quoteOk"] = True
            except Exception:
                pass

            return entry

        with ThreadPoolExecutor(max_workers=30) as pool:
            futures = {
                pool.submit(_probe, name, ip, port): (name, ip, port)
                for name, ip, port in all_hosts
            }
            for future in as_completed(futures):
                entry = future.result()
                if active_addr and entry["ip"] == self.active_server[0] and entry["port"] == self.active_server[1]:
                    entry["isActive"] = True
                results.append(entry)

        # Sort: active first, then quote-OK, then TCP-reachable, then unreachable
        def _sort_key(e: dict[str, Any]) -> tuple[int, float]:
            if e["isActive"]:
                return (0, 0)
            if e["quoteOk"]:
                return (1, e.get("tcpMs") or 9999)
            if e.get("tcpMs") is not None:
                return (2, e["tcpMs"])
            return (3, 9999)

        results.sort(key=_sort_key)
        return results

    def select_tdx_server(self, ip: str, port: int) -> dict[str, Any]:
        import json as _json

        from mootdx.consts import CONFIG as MOOTDX_CONFIG
        from mootdx.utils import get_config_path

        config_path = get_config_path("config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = _json.load(fh)
        except Exception:
            cfg = dict(MOOTDX_CONFIG)

        cfg.setdefault("BESTIP", {})["HQ"] = [ip, port]
        with open(config_path, "w", encoding="utf-8") as fh:
            _json.dump(cfg, fh, indent=2, ensure_ascii=False)

        self._manual_server = (ip, port)
        logger.info("TDX server switched to %s:%s via UI, triggering reconnect", ip, port)
        asyncio.create_task(self._reconnect_after_selection(ip, port))

        return {"ok": True, "ip": ip, "port": port}

    async def _reconnect_after_selection(self, ip: str, port: int) -> None:
        await self.reset_client()
        # active_server 由 ensure_client() 连接成功后自动设置，不在此处预填
        self.full_state_requested = True
        self.healthy_fetch_cycles = 0
        self.current_quote_batch_size = self.clamp_quote_batch_size(self.config.quote_batch_size)

    def monitor_html(self) -> str:
        status = self.status_snapshot()
        status_json = json.dumps(status, ensure_ascii=False, indent=2)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TDX Bridge Monitor</title>
  <style>
    body {{ margin: 0; font-family: Consolas, "Microsoft YaHei UI", sans-serif; background: #111419; color: #eef2f7; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
    h1 {{ color: #ffb046; margin: 0 0 8px; font-size: 28px; }}
    .sub {{ color: #91a1b4; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }}
    .card {{ background: #1d222b; border: 1px solid #303846; padding: 14px; border-radius: 6px; }}
    .label {{ color: #91a1b4; font-size: 12px; }}
    .value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
    .ok {{ color: #2cd28c; }}
    .bad {{ color: #eb4b55; }}
    pre {{ background: #090b0f; border: 1px solid #303846; padding: 14px; overflow: auto; border-radius: 6px; }}
    a {{ color: #61a8ff; }}
  </style>
</head>
<body>
  <main>
    <h1>TDX Bridge Monitor</h1>
    <div class="sub">WebSocket: {status["websocket"]["url"]} · JSON: <a href="/status">/status</a> · Health: <a href="/health">/health</a></div>
    <section class="grid">
      <div class="card"><div class="label">TDX 连接</div><div class="value {'ok' if status['tdx']['connected'] else 'bad'}">{'已连接' if status['tdx']['connected'] else '未连接'}</div></div>
      <div class="card"><div class="label">客户端</div><div class="value">{status["websocket"]["clients"]}</div></div>
      <div class="card"><div class="label">订阅股票</div><div class="value">{status["websocket"]["subscribedCount"]}</div></div>
      <div class="card"><div class="label">报价 / 深度缓存</div><div class="value">{status["quotes"]["received"]} / {status["quotes"]["depth"]}</div></div>
      <div class="card"><div class="label">Batch Size</div><div class="value">{status["quotes"]["batchSize"]}</div></div>
      <div class="card"><div class="label">最近循环耗时</div><div class="value">{status["quotes"]["lastCycle"]["elapsedMs"]} ms</div></div>
      <div class="card"><div class="label">截断 / 慢批次</div><div class="value">{status["quotes"]["lastCycle"]["truncatedBatches"]} / {status["quotes"]["lastCycle"]["slowBatches"]}</div></div>
      <div class="card"><div class="label">L2 状态</div><div class="value">{status["l2"].get("status", "")}</div></div>
    </section>
    <h2>状态快照</h2>
    <pre id="status">{status_json}</pre>
  </main>
  <script>
    async function refresh() {{
      const res = await fetch('/status');
      document.getElementById('status').textContent = JSON.stringify(await res.json(), null, 2);
    }}
    setInterval(refresh, 3000);
  </script>
</body>
</html>"""

    def create_app(self) -> FastAPI:
        app = FastAPI(
            title="TDX Bridge Monitor API",
            version="1.0.0",
            description="通达信行情桥运行状态、健康检查和 WebSocket 行情入口。",
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return HTMLResponse(self.monitor_html())

        @app.get("/monitor", include_in_schema=False)
        async def monitor() -> HTMLResponse:
            return HTMLResponse(self.monitor_html())

        @app.get("/health", summary="健康检查")
        async def health() -> JSONResponse:
            return JSONResponse(self.status_snapshot())

        @app.get("/status", summary="运行状态快照")
        async def status() -> JSONResponse:
            return JSONResponse(self.status_snapshot())

        @app.get("/metrics", summary="人类可读关键指标")
        async def metrics() -> PlainTextResponse:
            snapshot = self.status_snapshot()
            lines = [
                f"service={snapshot['service']}",
                f"tdx_connected={snapshot['tdx']['connected']}",
                f"active_server={snapshot['tdx']['activeServer']}",
                f"clients={snapshot['websocket']['clients']}",
                f"subscribed={snapshot['websocket']['subscribedCount']}",
                f"quotes={snapshot['quotes']['received']}",
                f"depth={snapshot['quotes']['depth']}",
                f"elapsed_ms={snapshot['quotes']['lastCycle']['elapsedMs']}",
                f"truncated_batches={snapshot['quotes']['lastCycle']['truncatedBatches']}",
                f"slow_batches={snapshot['quotes']['lastCycle']['slowBatches']}",
                f"l2_status={snapshot['l2'].get('status', '')}",
            ]
            return PlainTextResponse("\n".join(lines) + "\n")

        @app.get("/api/quotes/snapshot", summary="行情快照")
        async def quote_snapshot(codes: str = "") -> JSONResponse:
            parsed_codes = [normalize_code(code) for code in codes.split(",") if code.strip()]
            parsed_codes = [code for code in parsed_codes if code]

            # Phase 2: fall back to backend pool when no codes param
            using_pool = False
            pool_ts = 0
            if not parsed_codes:
                async with self._backend_pool_lock:
                    parsed_codes = list(self._backend_pool_codes)
                    using_pool = True
                    pool_ts = self._backend_pool_ts

            if not parsed_codes:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "missing codes parameter and backend pool is empty",
                        "source": "python_bridge",
                        "serverTs": now_ms(),
                        "subscribedCount": 0,
                        "quotes": [],
                        "depth": [],
                        "ticks": [],
                        "quoteStats": {},
                        "l2": self.l2_state,
                    }
                )
            try:
                quotes, depth, stats = await self.fetch_quotes_and_depth(parsed_codes)

                if not quotes and stats.failed_batches > 0:
                    return JSONResponse(
                        {
                            "ok": False,
                            "error": f"quote fetch failed: {stats.failed_batches}/{stats.batches} batches failed",
                            "source": "python_bridge",
                            "serverTs": now_ms(),
                            "subscribedCount": len(parsed_codes),
                            "quotes": [],
                            "depth": [],
                            "ticks": [],
                            "quoteStats": stats.to_payload(),
                            "l2": self.l2_state,
                        }
                    )

                qmt_depth, qmt_ticks = await self.fetch_qmt_l2_snapshot(parsed_codes)

                if using_pool:
                    async with self._backend_pool_lock:
                        if parsed_codes == self._backend_pool_codes:
                            self._backend_cached_quotes = quotes
                            self._backend_cached_depth = depth
                            self._backend_cached_stats = stats
                            self._backend_pool_ts = now_ms()
                            pool_ts = self._backend_pool_ts

                response_payload = {
                    "ok": True,
                    "source": "python_bridge",
                    "serverTs": now_ms(),
                    "subscribedCount": len(parsed_codes),
                    "quotes": quotes,
                    "depth": depth,
                    "ticks": qmt_ticks,
                    "quoteStats": stats.to_payload(),
                    "l2": self.l2_state,
                }
                if using_pool:
                    response_payload["pooled"] = True
                    response_payload["poolRefreshedAt"] = pool_ts
                return JSONResponse(response_payload)
            except Exception as error:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": str(error),
                        "source": "python_bridge",
                        "serverTs": now_ms(),
                        "subscribedCount": len(parsed_codes),
                        "quotes": [],
                        "depth": [],
                        "ticks": [],
                        "quoteStats": {},
                        "l2": self.l2_state,
                    }
                )

        @app.post("/api/quotes/subscriptions", summary="设置后端采集订阅池")
        async def set_subscriptions(payload: dict) -> JSONResponse:
            codes = [
                normalize_code(str(c).strip())
                for c in payload.get("codes", [])
                if str(c).strip()
            ]
            codes = [c for c in codes if c]
            async with self._backend_pool_lock:
                self._backend_pool_codes = codes
                self._backend_pool_ts = now_ms()
                if codes:
                    try:
                        quotes, depth, stats = await self.fetch_quotes_and_depth(codes)
                        self._backend_cached_quotes = quotes
                        self._backend_cached_depth = depth
                        self._backend_cached_stats = stats
                    except Exception as exc:
                        logger.warning(f"backend pool initial fetch failed: {exc}")
                        self._backend_cached_quotes = []
                        self._backend_cached_depth = []
                        self._backend_cached_stats = None
                else:
                    self._backend_cached_quotes = []
                    self._backend_cached_depth = []
                    self._backend_cached_stats = None
            return JSONResponse(
                {
                    "ok": True,
                    "codes": self._backend_pool_codes,
                    "count": len(self._backend_pool_codes),
                    "setAt": self._backend_pool_ts,
                }
            )

        @app.get("/api/quotes/minute", summary="TDX 分时数据")
        async def minute_data(code: str = "", date: str = "") -> JSONResponse:
            stock_code = normalize_code(code)
            if not stock_code:
                return JSONResponse({"ok": False, "error": "missing code"}, status_code=400)
            try:
                if date:
                    session_date = resolve_requested_session_date(date)
                    current_session_date, current_expected_complete = resolve_minute_session_date()
                    if (
                        date == datetime.now().astimezone().strftime("%Y%m%d")
                        and session_date != current_session_date
                    ):
                        session_date = current_session_date
                    expected_complete = not (
                        session_date == current_session_date and not current_expected_complete
                    )
                else:
                    session_date, expected_complete = resolve_minute_session_date()
                async with self.fetch_lock:
                    await self.ensure_client()
                    assert self.quote_client is not None
                    if expected_complete:
                        frame = await asyncio.to_thread(
                            self.quote_client.minutes,
                            symbol=stock_code,
                            date=session_date,
                        )
                    else:
                        frame = await asyncio.to_thread(
                            self.quote_client.minute,
                            symbol=stock_code,
                        )
                records = frame_to_records(frame)
                if len(records) > 240:
                    raise ValueError("invalid minute point count")
                cumulative_vol = 0.0
                cumulative_amount = 0.0
                points = []
                for idx, r in enumerate(records):
                    price = float(r.get("price", 0))
                    vol = float(r.get("vol", r.get("volume", 0)))
                    if not math.isfinite(price) or not math.isfinite(vol) or price <= 0 or vol < 0:
                        raise ValueError("invalid minute row")
                    cumulative_vol += vol
                    cumulative_amount += price * vol * 100
                    # 计算分时时间：前120点为早盘9:30起，之后为午盘13:00起
                    if idx < 120:
                        total_minutes = 9 * 60 + 30 + idx
                    else:
                        total_minutes = 13 * 60 + (idx - 120)
                    hour = total_minutes // 60
                    minute = total_minutes % 60
                    time_str = f"{hour:02d}{minute:02d}"
                    points.append({
                        "time": time_str,
                        "price": price,
                        "vol": vol,
                        "cumulativeVolume": cumulative_vol,
                        "cumulativeAmount": round(cumulative_amount, 2),
                    })
                return JSONResponse({
                    "ok": True,
                    "data": {
                        "date": session_date,
                        "points": points,
                        "complete": len(points) == 240,
                        "expectedComplete": expected_complete,
                    },
                    "serverTs": now_ms(),
                })
            except RuntimeError as exc:
                return JSONResponse(
                    {"ok": False, "errorCode": "tdx_calendar_unavailable", "error": str(exc)},
                    status_code=503,
                )
            except Exception as exc:
                return JSONResponse(
                    {"ok": False, "error": str(exc)}, status_code=500
                )

        @app.get("/api/tdx-servers", summary="扫描 TDX 行情服务器列表")
        async def tdx_servers() -> JSONResponse:
            servers = await asyncio.to_thread(self.scan_tdx_servers)
            return JSONResponse({
                "ok": True,
                "servers": servers,
                "activeServer": (
                    {"ip": self.active_server[0], "port": self.active_server[1]}
                    if self.active_server else None
                ),
                "serverTs": now_ms(),
            })

        @app.get("/api/calendar", summary="A股交易日历")
        async def calendar(date: str = "") -> JSONResponse:
            try:
                target = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
            except ValueError:
                target = datetime.now()
            is_trading_day = _is_trading_day_cached(target)
            if is_trading_day is None:
                return JSONResponse({
                    "ok": False,
                    "errorCode": "tdx_calendar_unavailable",
                    "isTradingDay": None,
                    "isTradingSession": False,
                    "date": target.strftime("%Y-%m-%d"),
                    "serverTs": now_ms(),
                }, status_code=503)
            return JSONResponse({
                "ok": True,
                "isTradingDay": is_trading_day,
                "isTradingSession": is_trading_session_now(target),
                "date": target.strftime("%Y-%m-%d"),
                "serverTs": now_ms(),
            })

        @app.post("/api/tdx-servers/select", summary="切换 TDX 行情服务器")
        async def tdx_servers_select(body: dict[str, Any]) -> JSONResponse:
            ip = str(body.get("ip", "")).strip()
            port = int(body.get("port", 0))
            if not ip or not port:
                return JSONResponse(
                    {"ok": False, "error": "ip and port required"},
                    status_code=400,
                )
            result = self.select_tdx_server(ip, port)
            return JSONResponse(result)

        @app.websocket(self.config.path)
        async def quotes_socket(websocket: WebSocket) -> None:
            await websocket.accept()
            await self.handle_client(FastApiWebSocketClient(websocket))

        return app

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self.clients:
            return
        message = json.dumps(payload, ensure_ascii=False)
        stale_clients: list[Any] = []

        for client in list(self.clients):
            queue = self.client_queues.get(client)
            if queue is None or queue.closed:
                stale_clients.append(client)
                continue
            # 只入队不等待：慢客户端由自己的发送队列消化，不拖拽其他客户端
            queue.enqueue(message)

        for client in stale_clients:
            self.clients.discard(client)
            self.client_pools.pop(client, None)
            queue = self.client_queues.pop(client, None)
            if queue is not None:
                await queue.close()

    def diff_payloads(
        self,
        items: Iterable[dict[str, Any]],
        cache: dict[str, str],
    ) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        for item in items:
            code = str(item.get("code") or "")
            if not code:
                continue
            compare_item = {k: v for k, v in item.items() if k not in {"sourceTs", "seq"}}
            serialized = json.dumps(compare_item, ensure_ascii=False, sort_keys=True)
            if cache.get(code) == serialized:
                continue
            cache[code] = serialized
            changed.append(item)
        return changed

    def attach_quote_sampling_metadata(
        self,
        quotes: Iterable[dict[str, Any]],
        stats: QuoteFetchStats,
        forced_opening_sample: bool,
    ) -> list[dict[str, Any]]:
        payload = stats.to_payload()
        sample_kind = "opening_auction_forced" if forced_opening_sample else "regular"
        annotated: list[dict[str, Any]] = []
        for item in quotes:
            code = str(item.get("code") or "")
            if not code:
                continue
            annotated.append(
                {
                    **item,
                    "sampleKind": sample_kind,
                    "openingForcedSample": forced_opening_sample,
                    **payload,
                }
            )
        return annotated

    def chunk_codes(self, codes: list[str], batch_size: int) -> list[list[str]]:
        size = self.clamp_quote_batch_size(batch_size)
        return [codes[index : index + size] for index in range(0, len(codes), size)]

    def tune_quote_batch_size(self, stats: QuoteFetchStats) -> None:
        previous = self.current_quote_batch_size
        if (
            stats.failed_batches > 0
            or stats.truncated_batches > 0
            or stats.slow_batches > 0
        ):
            self.healthy_fetch_cycles = 0
            self.current_quote_batch_size = self.clamp_quote_batch_size(
                previous - self.config.batch_shrink_step
            )
        else:
            self.healthy_fetch_cycles += 1
            if self.healthy_fetch_cycles >= max(1, self.config.healthy_cycles_before_grow):
                self.current_quote_batch_size = self.clamp_quote_batch_size(
                    previous + self.config.batch_growth_step
                )
                self.healthy_fetch_cycles = 0

        if self.current_quote_batch_size != previous:
            logger.info(
                "adjusted quote batch size: %s -> %s (failed=%s truncated=%s slow=%s)",
                previous,
                self.current_quote_batch_size,
                stats.failed_batches,
                stats.truncated_batches,
                stats.slow_batches,
            )

    def _warn_throttled(self, cache: dict, key, cooldown_s: float) -> bool:
        """返回 True 表示应记录该 WARNING；同一 key 在冷却窗口内只放行一次。

        用于高频告警节流：key 可为缺失代码集合元组或单个代码，cache 为对应的时间戳字典。
        缓存有界：超过上限时先清理过期条目（≥2×冷却窗口）；若仍超限则删除最旧条目
        直到回到上限，防止长期运行缓存无限增长。
        """
        now = time.monotonic()
        last = cache.get(key)
        if last is not None and now - last < cooldown_s:
            return False
        cache[key] = now
        if len(cache) > 512:
            stale = [k for k, v in cache.items() if now - v >= cooldown_s * 2]
            for k in stale:
                cache.pop(k, None)
            if len(cache) > 512:
                # 仍超限：按时间戳一次排序，删除最旧条目直到回到上限（O(n log n)，避免逐次 min 的 O(n²)）
                for k, _ in sorted(cache.items(), key=lambda kv: kv[1])[: len(cache) - 512]:
                    cache.pop(k, None)
        return True

    async def fetch_quotes_and_depth(
        self, codes: list[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], QuoteFetchStats]:
        stats = QuoteFetchStats(requested_codes=len(codes))
        cycle_started = now_ms()
        if not codes:
            return [], [], stats

        # 无数据挂起代码跳过（2026-08-12：688836 新股未上市 TDX 无数据，
        # 含它的批量请求整批返回空——挂起后不再每轮重复请求/拖累同批）
        now_value = now_ms()
        halted = self.halted_codes(now_value)
        if halted:
            codes = [code for code in codes if code not in halted]
            stats.halted_codes = len(halted)
            stats.requested_codes = len(codes)
        if not codes:
            return [], [], stats

        quotes_by_code: dict[str, dict[str, Any]] = {}
        depth_by_code: dict[str, dict[str, Any]] = {}
        quote_batches = self.chunk_codes(codes, self.current_quote_batch_size)

        async with self.fetch_lock:
            await self.ensure_client()

            # 分批并发：单批仍受 batch_size 上限约束，但多个 batch 在线程池并行执行，
            # 整轮行情耗时从“逐批串行 + 批间延时”降为“ceil(批数/并发)×单批耗时”。
            semaphore = asyncio.Semaphore(max(1, self.config.quote_batch_concurrency))

            async def _fetch_batch(batch_index: int, batch_codes: list[str]) -> None:
                async with semaphore:
                    batch_started = now_ms()
                    stats.batches += 1

                    try:
                        def _fetch(batch: list[str] = batch_codes):
                            assert self.quote_client is not None
                            return self.quote_client.quotes(symbol=batch)

                        frame = await asyncio.to_thread(_fetch)
                        records = frame_to_records(frame)
                        batch_elapsed = now_ms() - batch_started

                        if batch_elapsed >= self.config.slow_batch_threshold_ms:
                            stats.slow_batches += 1

                        record_codes = {
                            normalize_code(pick(row, "code", "symbol"))
                            for row in records
                            if normalize_code(pick(row, "code", "symbol"))
                        }
                        missing_codes = [code for code in batch_codes if code not in record_codes]
                        if missing_codes:
                            stats.truncated_batches += 1
                            if self._warn_throttled(
                                self._partial_data_warn_ts,
                                tuple(sorted(missing_codes)),
                                self._warn_cooldown_s,
                            ):
                                logger.warning(
                                    "quote batch returned partial data: requested=%s received=%s missing=%s batch_size=%s",
                                    len(batch_codes),
                                    len(record_codes),
                                    ",".join(missing_codes[:8]) + ("..." if len(missing_codes) > 8 else ""),
                                    self.current_quote_batch_size,
                                )
                            for missing_code in missing_codes:
                                try:
                                    def _refetch_one(code: str = missing_code):
                                        assert self.quote_client is not None
                                        return self.quote_client.quotes(symbol=[code])

                                    refetched_records = frame_to_records(
                                        await asyncio.to_thread(_refetch_one)
                                    )
                                    if any(
                                        normalize_code(pick(r, "code", "symbol")) == missing_code
                                        for r in refetched_records
                                    ):
                                        self.unhalt_code(missing_code)
                                    records.extend(refetched_records)
                                except Exception as error:
                                    self.halt_code(missing_code, now_ms())
                                    if self._warn_throttled(
                                        self._refetch_fail_warn_ts,
                                        missing_code,
                                        self._warn_cooldown_s,
                                    ):
                                        logger.warning(
                                            "quote refetch failed: code=%s error=%s",
                                            missing_code,
                                            error,
                                        )

                        for row in records:
                            quote_item = normalize_quote_row(row, captured_ms=batch_started)
                            if quote_item:
                                if not is_trading_session_now() and is_placeholder_quote_row(quote_item):
                                    continue
                                quote_item["speed"] = self.compute_quote_speed(
                                    quote_item["code"],
                                    to_number(quote_item.get("lastPrice")),
                                    to_int(quote_item.get("sourceTs"), now_ms()),
                                    row,
                                )
                                quotes_by_code[quote_item["code"]] = quote_item

                            depth_item = normalize_depth_row(row)
                            if depth_item:
                                depth_by_code[depth_item["code"]] = depth_item
                    except Exception as error:
                        stats.failed_batches += 1
                        logger.warning(
                            "quote batch fetch failed: index=%s size=%s sample=%s error=%s",
                            batch_index,
                            len(batch_codes),
                            ",".join(batch_codes[:5]),
                            error,
                        )

            await asyncio.gather(
                *(
                    _fetch_batch(batch_index, batch_codes)
                    for batch_index, batch_codes in enumerate(quote_batches)
                )
            )

        if self.official_cache_reader and codes:
            try:
                cache_depth = await asyncio.to_thread(self.official_cache_reader.read_depth, codes)
                accepted_cache_depth = 0
                for item in cache_depth:
                    quote_item = quotes_by_code.get(item["code"])
                    if depth_matches_quote_window(quote_item, item):
                        depth_by_code[item["code"]] = item
                        accepted_cache_depth += 1
                if cache_depth and accepted_cache_depth == 0:
                    logger.info(
                        "official hq cache depth rejected by quote alignment: requested=%s candidates=%s",
                        len(codes),
                        len(cache_depth),
                    )
            except Exception as error:
                logger.warning("official hq cache depth load failed: %s", error)

        stats.received_quotes = len(quotes_by_code)
        stats.received_depth = len(depth_by_code)
        stats.elapsed_ms = now_ms() - cycle_started
        return list(quotes_by_code.values()), list(depth_by_code.values()), stats

    def current_tick_codes(self, codes: list[str]) -> list[str]:
        if not codes:
            return []
        limit = self.config.tick_codes_per_cycle
        if limit <= 0 or limit >= len(codes):
            return codes

        start = self.tick_cursor % len(codes)
        selected = [codes[(start + offset) % len(codes)] for offset in range(limit)]
        self.tick_cursor = (start + limit) % len(codes)
        return selected

    def dedupe_ticks(self, code: str, ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = self.tick_seen_keys[code]
        queue = self.tick_seen_queues[code]
        fresh: list[dict[str, Any]] = []

        for tick in ticks:
            key = f"{tick['tradeTime']}|{tick['price']}|{tick['volume']}|{tick['side']}"
            if key in seen:
                continue
            seen.add(key)
            queue.append(key)
            while len(queue) > 600:
                expired = queue.popleft()
                seen.discard(expired)
            fresh.append(tick)

        return fresh

    async def fetch_ticks(self, codes: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if not self.tick_fetch_supported:
            return results
        tick_codes = self.current_tick_codes(codes)
        if not tick_codes:
            return results

        # 非交易时段（与 tdxpy time_frame 同一判断）分笔接口本就不可用：tdxpy 会打
        # DeprecationWarning 并返回 None。从源头跳过整个分笔轮询（不连接、不建 task），
        # 行为与 tdxpy 返回 None 等价；_fetch_one 内再判断一次兜底跨时段边界。
        if not tdx_is_trading_frame():
            return results

        async with self.fetch_lock:
            await self.ensure_client()
            semaphore = asyncio.Semaphore(max(1, self.config.tick_fetch_concurrency))

            async def _fetch_one(code: str) -> dict[str, Any] | None:
                async with semaphore:
                    try:
                        # 兜底：拉取期间跨过时段边界（如 11:29:59 进入、11:30:00 执行）
                        # 时避免调用 tdxpy（否则仍会触发其 DeprecationWarning）。
                        if not tdx_is_trading_frame():
                            return None

                        def _fetch():
                            assert self.quote_client is not None
                            return self.quote_client.transaction(
                                symbol=code, start=0, offset=self.config.tick_window
                            )

                        frame = await asyncio.to_thread(_fetch)
                        records = frame_to_records(frame)
                        normalized = [
                            item
                            for item in (normalize_tick_row(code, row) for row in records)
                            if item
                        ]
                        fresh = self.dedupe_ticks(code, normalized)
                        if fresh:
                            # 2026-08-14：TDX L1 分笔自算资金流（tdx_transaction）已废弃——
                            # 非全日完整分笔、累计不可靠，前端不消费；不再累积 tdx_fund_flow。
                            return {"code": code, "items": fresh}
                        return None
                    except NotImplementedError as error:
                        self.tick_fetch_supported = False
                        self.last_tick_error = "transaction API not supported by mootdx/tdxpy runtime"
                        if not self.tick_fetch_warning_emitted:
                            self.tick_fetch_warning_emitted = True
                            logger.warning(
                                "tick transaction API is not supported by current mootdx/tdxpy runtime; disabling tick fetch: %s",
                                error,
                            )
                        return None
                    except Exception as error:
                        self.last_tick_error = str(error)
                        logger.warning("tick fetch failed for %s: %s", code, error)
                        return None

            outcomes = await asyncio.gather(*(_fetch_one(code) for code in tick_codes))
            for outcome in outcomes:
                if outcome:
                    results.append(outcome)

        return results

    def qmt_l2_codes(self, codes: list[str]) -> list[str]:
        limit = max(0, self.config.qmt_l2_code_limit)
        return codes[:limit] if limit else codes

    async def fetch_qmt_l2_snapshot(
        self,
        codes: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.qmt_l2_provider:
            return [], []
        now = now_ms()
        interval = max(0, self.config.qmt_l2_poll_interval_ms)
        if self.cached_qmt_l2_snapshot and interval and now - self.last_qmt_l2_poll_ts < interval:
            return self.cached_qmt_l2_snapshot
        target_codes = self.qmt_l2_codes(codes)
        if not target_codes:
            return [], []
        try:
            snapshot = await asyncio.to_thread(self.qmt_l2_provider.poll_snapshot, target_codes)
            if snapshot.status:
                self.l2_state.update(snapshot.status.to_dict())
            if snapshot.status and snapshot.status.status == "ok":
                self.l2_state["fallbackActive"] = False
            depth = [item.to_dict() for item in snapshot.depth]
            ticks = snapshot.ticks
            self.last_qmt_l2_poll_ts = now_ms()
            self.cached_qmt_l2_snapshot = (depth, ticks)
            return self.cached_qmt_l2_snapshot
        except Exception as error:
            self.l2_state.update(
                {
                    "provider": "qmt",
                    "status": "unknown_error",
                    "message": str(error),
                    "lastProbeTs": now_ms(),
                    "fallbackActive": True,
                }
            )
            logger.warning("qmt l2 snapshot fetch failed: %s", error)
            return [], []

    async def broadcast_l2_status_if_changed(self) -> None:
        if not self.clients:
            return
        payload = json.dumps(self.l2_state, ensure_ascii=False, sort_keys=True)
        if payload == self.latest_l2_status_payload:
            return
        self.latest_l2_status_payload = payload
        await self.broadcast(
            {
                "type": "l2_status",
                "serverTs": now_ms(),
                "l2": self.l2_state,
            }
        )

    async def poll_loop(self) -> None:
        while not self.stop_event.is_set():
            cycle_started = now_ms()
            pool = self.aggregate_pool()

            if not pool:
                await asyncio.sleep(0.2)
                continue

            # 财务数据（市值/PE/PB 计算原料）后台节流刷新：首次 + 每 finance_refresh_interval_ms。
            # 用独立 task + to_thread，不阻塞行情轮询；失败仅 debug 日志，不影响行情。
            if not self._finance_refresh_in_progress and (
                not self._last_finance_refresh_ts
                or now_ms() - self._last_finance_refresh_ts >= self.finance_refresh_interval_ms
            ):
                self._finance_refresh_in_progress = True
                self._last_finance_refresh_ts = now_ms()
                finance_codes = list(pool)
                asyncio.get_running_loop().create_task(self._refresh_finance_background(finance_codes))

            cycle_started_dt = datetime.now().astimezone()
            try:
                quotes, depth, quote_stats = await self.fetch_quotes_and_depth(pool)
                forced_opening_sample = is_opening_sampling_window(cycle_started_dt, datetime.now().astimezone())
                quotes = self.attach_quote_sampling_metadata(
                    quotes,
                    quote_stats,
                    forced_opening_sample,
                )
                if forced_opening_sample:
                    self.opening_raw_quote_sink.record_many(quotes, source="mootdx-bridge")
                self.latest_quote_stats = quote_stats
                self.last_quote_cycle_ts = now_ms()
                self.last_quote_error = ""
                qmt_depth, qmt_ticks = await self.fetch_qmt_l2_snapshot(pool)
                if qmt_depth:
                    depth_by_code = {item["code"]: item for item in depth}
                    for item in qmt_depth:
                        if int(item.get("depthLevelCount") or 0) >= 10:
                            depth_by_code[item["code"]] = item
                    depth = list(depth_by_code.values())
                self.tune_quote_batch_size(quote_stats)
                quote_patch = (
                    quotes
                    if forced_opening_sample
                    else self.diff_payloads(quotes, self.latest_quotes)
                )
                depth_patch = self.diff_payloads(depth, self.latest_depth)
                ticks_batch = qmt_ticks or await self.fetch_ticks(pool)
                subscribed_count = len(pool)

                logger.info(
                    "quote cycle: subscribed=%s quotes=%s depth=%s batch_size=%s batches=%s truncated=%s slow=%s elapsed=%sms",
                    subscribed_count,
                    quote_stats.received_quotes,
                    quote_stats.received_depth,
                    self.current_quote_batch_size,
                    quote_stats.batches,
                    quote_stats.truncated_batches,
                    quote_stats.slow_batches,
                    quote_stats.elapsed_ms,
                )

                if self.full_state_requested:
                    await self.broadcast(
                        {
                            "type": "full_state",
                            "serverTs": now_ms(),
                            "subscribedCount": subscribed_count,
                            "quotes": quotes,
                            "depth": depth,
                            "quoteStats": quote_stats.to_payload(),
                            "openingForcedSample": forced_opening_sample,
                            "l2": self.l2_state,
                        }
                    )
                    await self.broadcast_l2_status_if_changed()
                    self.full_state_requested = False
                else:
                    if quote_patch:
                        await self.broadcast(
                            {
                                "type": "quote_patch",
                                "serverTs": now_ms(),
                                "intervalMs": self.config.poll_interval_ms,
                                "items": quote_patch,
                                "quoteStats": quote_stats.to_payload(),
                                "openingForcedSample": forced_opening_sample,
                            }
                        )
                    if depth_patch:
                        await self.broadcast(
                            {
                                "type": "depth_patch",
                                "serverTs": now_ms(),
                                "intervalMs": self.config.poll_interval_ms,
                                "items": depth_patch,
                            }
                        )
                    await self.broadcast_l2_status_if_changed()

                if ticks_batch:
                    await self.broadcast(
                        {
                            "type": "ticks_batch",
                            "serverTs": now_ms(),
                            "intervalMs": self.config.poll_interval_ms,
                            "items": ticks_batch,
                        }
                    )

                # 2026-08-14：TDX L1 分笔自算资金流（tdx_transaction）已废弃，不再广播
                # fund_flow_patch（前端不消费，非全日完整分笔、累计不可靠）。

                self.tdx_connected = True
            except Exception as error:
                logger.exception("poll loop failed: %s", error)
                self.last_quote_error = str(error)
                await self.reset_client()
                self.full_state_requested = True
                self.healthy_fetch_cycles = 0
                self.current_quote_batch_size = self.clamp_quote_batch_size(
                    self.current_quote_batch_size - self.config.batch_shrink_step
                )

            elapsed = now_ms() - cycle_started
            target_cycle_ms = max(self.config.poll_interval_ms, self.config.target_cycle_interval_ms)
            sleep_ms = max(50, target_cycle_ms - elapsed)
            await asyncio.sleep(sleep_ms / 1000)

    async def _refresh_finance_background(self, codes: list[str]) -> None:
        """后台刷新财务缓存（市值/PE/PB 计算原料）；失败仅 debug 日志，不影响行情。
        使用独立连接（refresh_finance 内自建），不与行情轮询共享 mootdx client（非线程安全）。"""
        try:
            await asyncio.to_thread(tdx_fundamental.refresh_finance, codes)
        except Exception as error:
            logger.debug("finance refresh background failed: %s", error)
        finally:
            self._finance_refresh_in_progress = False

    async def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            trading_session = is_trading_session_now()
            interval_ms = max(
                250,
                self.config.trading_heartbeat_interval_ms
                if trading_session
                else self.config.heartbeat_interval_ms,
            )
            await self.broadcast(
                {
                    "type": "heartbeat",
                    "serverTs": now_ms(),
                    "intervalMs": interval_ms,
                    "tradingSession": trading_session,
                    "subscribedCount": len(self.aggregate_pool()),
                    "tdxConnected": self.tdx_connected,
                    "activeServer": (
                        f"{self.active_server[0]}:{self.active_server[1]}" if self.active_server else ""
                    ),
                    "l2": self.l2_state,
                }
            )
            await self.sleep_or_stop(interval_ms)

    async def l2_probe_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.config.l2_enabled:
                await asyncio.sleep(self.config.l2_probe_interval_ms / 1000)
                continue

            server = self.next_l2_probe_server()
            if server is not None:
                await self.probe_l2_server(server)

            await asyncio.sleep(self.config.l2_probe_interval_ms / 1000)

    async def run(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            config = uvicorn.Config(
                self.create_app(),
                host=self.config.host,
                port=self.config.port,
                log_level="info",
            )
            server = uvicorn.Server(config)
            logger.info(
                "TDX bridge listening on ws://%s:%s%s",
                self.config.host,
                self.config.port,
                self.config.path,
            )
            tasks = [
                asyncio.create_task(server.serve()),
                asyncio.create_task(self.poll_loop()),
                asyncio.create_task(self.heartbeat_loop()),
                asyncio.create_task(self.l2_probe_loop()),
                asyncio.create_task(self.helper_loop()),
            ]
            await self.stop_event.wait()
            server.should_exit = True
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.stop_helper_process()
            await self.reset_client()


async def main() -> None:
    config = BridgeConfig()
    bridge = TdxL2Bridge(config)
    loop = asyncio.get_running_loop()
    _install_accept_error_filter(loop)
    # tdxpy 收盘后调用接口会输出 DeprecationWarning 提示；只是建议性提示，
    # 过滤后避免刷屏 launcher 日志，不影响行情拉取。
    # 模块顶部已按消息文本注册 ignore（更鲁棒）；此处再按 module+message 双条件注册兜底。
    warnings.filterwarnings("ignore", message=r"目前不是交易时间段.*", category=DeprecationWarning, module=r"tdxpy")
    logger.info(
        "bridge bootstrap: pid=%s port=%s path=%s log=%s",
        os.getpid(),
        config.port,
        config.path,
        LOG_FILE_PATH,
    )

    def _shutdown() -> None:
        bridge.stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await bridge.run()


def _install_accept_error_filter(loop: asyncio.AbstractEventLoop) -> None:
    """过滤 Windows IOCP accept 的 WinError 64 噪音。

    Windows 上客户端连接在 accept 完成前断开时，AcceptEx 会返回
    OSError(winerror=64)（"指定的网络名不再可用"）。asyncio 会把该异常
    上报为 "Task exception was never retrieved" / "Accept failed on a socket"
    两条 ERROR，属于正常竞争条件，不代表服务故障；这里只放行其它异常。
    """

    previous = loop.get_exception_handler()

    def _handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 64:
            return
        if previous is not None:
            previous(_loop, context)
        else:
            _loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)


if __name__ == "__main__":
    asyncio.run(main())
