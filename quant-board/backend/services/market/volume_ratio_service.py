from __future__ import annotations

"""全市场量比计算服务（Python golden，前端只消费结果）。

原 TS 本地链（VolumeHistoryService + VolumeRatioCalculator）迁入本模块：
- 历史成交量直接读 MongoDB snapshot_stock_rows（daily + 分时快照行）；
- 历史按 (tradingDate / clockMinute) 写入 Redis TTL 缓存，跨请求复用；
- 算法与 TS 版本逐行对齐：分时优先、日线按 A 股进度折算、加权平均、封顶 99.99。
"""

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

A_SHARE_TRADING_MINUTES = 240
VOLUME_RATIO_HISTORY_WEIGHTS = (5, 3, 2)
VOLUME_RATIO_HISTORY_DAYS = 3
LOOKBACK_DAYS = 4
DATASET_ID = "dragonboard_live"
INTRADAY_TYPES = ("quarter_hour", "half_hour", "hourly")

# 日级历史均量（量比分母）缓存：日级快照低频变化（一天数次），长 TTL 避免重 IO 反复读历史快照
DAILY_CACHE_TTL_SECONDS = 1800
INTRADAY_CACHE_TTL_SECONDS = 300  # 分时历史分母：历史 2 日固定、仅当天在变，300s 缓存合理
# 最近交易日列表缓存：交易日一天只变一次，长 TTL（1h）避免每 5 分钟重跑 tradingDate 聚合
RECENT_DATES_CACHE_TTL_SECONDS = 3600
# 量比结果缓存 TTL 60s（与前端量比刷新门限 VOLUME_RATIO_MIN_INTERVAL_MS=60s 一致）：
# 分子为当日实时量，60s 内量比固定；结果层缓存避免 60s 门限内重复请求仍打历史快照查询。
VOLUME_RATIO_RESULT_CACHE_TTL_SECONDS = 60
REDIS_PREFIX = "volume-ratio"


# ── 纯算法（与 src/services/dataLoader/VolumeRatioCalculator.ts 对齐） ──────────


def normalize_volume_history(
    volumes: list[Any] | None,
    limit: int = VOLUME_RATIO_HISTORY_DAYS,
) -> list[float]:
    if not volumes:
        return []
    output: list[float] = []
    for raw in volumes:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            output.append(value)
        if len(output) >= limit:
            break
    return output


def weighted_average_volume(volumes: list[Any] | None) -> float | None:
    normalized = normalize_volume_history(volumes)
    days_to_use = min(len(normalized), len(VOLUME_RATIO_HISTORY_WEIGHTS))
    if days_to_use == 0:
        return None
    weighted_sum = 0.0
    total_weight = 0.0
    for index in range(days_to_use):
        weight = VOLUME_RATIO_HISTORY_WEIGHTS[index]
        weighted_sum += normalized[index] * weight
        total_weight += weight
    if total_weight == 0:
        return None
    avg_volume = weighted_sum / total_weight
    return avg_volume if avg_volume > 0 else None


def raw_volume_ratio(current_volume: float, expected_volume: float) -> float | None:
    if expected_volume <= 0:
        return None
    ratio = current_volume / expected_volume
    if not math.isfinite(ratio) or ratio <= 0:
        return None
    return min(99.99, max(0.01, round(ratio, 2)))


def resolve_volume_ratio_history(
    current_volume: float,
    volumes: list[Any] | None,
) -> list[float]:
    if not volumes:
        return []
    normalized = normalize_volume_history(volumes, VOLUME_RATIO_HISTORY_DAYS + 1)
    if not normalized:
        return []
    latest_volume = normalized[0]
    relative_diff = abs(latest_volume - current_volume) / current_volume
    if len(normalized) > 1 and relative_diff <= 0.001:
        return normalized[1:4]
    return normalized[0:3]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def ashare_elapsed_trading_minutes(dt: datetime) -> int:
    seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second
    morning_start = 9 * 3600 + 30 * 60
    morning_end = 11 * 3600 + 30 * 60
    afternoon_start = 13 * 3600
    afternoon_end = 15 * 3600
    if seconds_of_day < morning_start:
        return A_SHARE_TRADING_MINUTES
    if seconds_of_day <= morning_end:
        return min(120, max(1, math.ceil((seconds_of_day - morning_start) / 60)))
    if seconds_of_day < afternoon_start:
        return 120
    if seconds_of_day <= afternoon_end:
        return min(
            A_SHARE_TRADING_MINUTES,
            120 + max(1, math.ceil((seconds_of_day - afternoon_start) / 60)),
        )
    return A_SHARE_TRADING_MINUTES


def ashare_volume_clock_minute(dt: datetime) -> float | None:
    seconds_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second
    morning_start = 9 * 3600 + 30 * 60
    morning_end = 11 * 3600 + 30 * 60
    afternoon_start = 13 * 3600
    afternoon_end = 15 * 3600
    if seconds_of_day < morning_start:
        return None
    if seconds_of_day <= morning_end:
        return seconds_of_day / 60
    if seconds_of_day < afternoon_start:
        return morning_end / 60
    if seconds_of_day <= afternoon_end:
        return seconds_of_day / 60
    return afternoon_end / 60


def ashare_expected_volume_progress(dt: datetime) -> float | None:
    elapsed_minutes = ashare_elapsed_trading_minutes(dt)
    if elapsed_minutes <= 30:
        return _clamp(0.06 + (elapsed_minutes / 30) * 0.18, 0.06, 0.24)
    if elapsed_minutes <= 120:
        return 0.24 + ((elapsed_minutes - 30) / 90) * 0.26
    if elapsed_minutes <= 180:
        return 0.5 + ((elapsed_minutes - 120) / 60) * 0.25
    return _clamp(0.75 + ((elapsed_minutes - 180) / 60) * 0.25, 0.75, 1)


def _structured_raw_volume_ratio(
    *,
    current_volume: float,
    expected_volume: float | None,
    source: str,
    history_volumes: list[float],
    calculated_at: int,
) -> dict[str, Any]:
    expected = float(expected_volume) if expected_volume is not None else float("nan")
    if not math.isfinite(expected) or expected <= 0:
        return {
            "status": "unavailable",
            "source": source,
            "currentVolume": current_volume,
            "expectedVolume": expected if math.isfinite(expected) else None,
            "historyVolumes": history_volumes,
            "capped": False,
            "reason": "invalid_expected_volume",
            "calculatedAt": calculated_at,
        }
    raw = current_volume / expected
    if not math.isfinite(raw) or raw <= 0:
        return {
            "status": "unavailable",
            "source": source,
            "currentVolume": current_volume,
            "expectedVolume": expected,
            "historyVolumes": history_volumes,
            "rawRatio": raw if math.isfinite(raw) else None,
            "capped": False,
            "reason": "invalid_raw_ratio",
            "calculatedAt": calculated_at,
        }
    value = raw_volume_ratio(current_volume, expected)
    capped = raw > 99.99
    return {
        "value": value,
        "status": "suspicious" if capped else "fresh",
        "source": source,
        "currentVolume": current_volume,
        "expectedVolume": expected,
        "historyVolumes": history_volumes,
        "rawRatio": round(raw, 4),
        "capped": capped,
        "reason": "ratio_capped" if capped else None,
        "calculatedAt": calculated_at,
    }


def calculate_volume_ratio(
    current_volume: float,
    daily_volumes: list[float] | None,
    intraday_volumes: list[float] | None,
    now: datetime,
) -> dict[str, Any]:
    calculated_at = int(now.timestamp() * 1000)
    if not math.isfinite(current_volume) or current_volume <= 0:
        return {
            "status": "unavailable",
            "source": "unavailable",
            "currentVolume": current_volume if math.isfinite(current_volume) else 0,
            "historyVolumes": [],
            "capped": False,
            "reason": "invalid_current_volume",
            "calculatedAt": calculated_at,
        }

    intraday = normalize_volume_history(intraday_volumes)
    if len(intraday) >= 2:
        return _structured_raw_volume_ratio(
            current_volume=current_volume,
            expected_volume=weighted_average_volume(intraday),
            source="intraday_snapshot",
            history_volumes=intraday,
            calculated_at=calculated_at,
        )

    volumes = resolve_volume_ratio_history(current_volume, daily_volumes)
    if len(volumes) < 2:
        return {
            "status": "unavailable",
            "source": "unavailable",
            "currentVolume": current_volume,
            "historyVolumes": volumes,
            "capped": False,
            "reason": "insufficient_history",
            "calculatedAt": calculated_at,
        }

    expected_progress = ashare_expected_volume_progress(now)
    if expected_progress is None:
        return {
            "status": "unavailable",
            "source": "daily_snapshot",
            "currentVolume": current_volume,
            "historyVolumes": volumes,
            "capped": False,
            "reason": "invalid_trading_progress",
            "calculatedAt": calculated_at,
        }

    avg_daily_volume = weighted_average_volume(volumes)
    if not avg_daily_volume:
        return {
            "status": "unavailable",
            "source": "daily_snapshot",
            "currentVolume": current_volume,
            "historyVolumes": volumes,
            "capped": False,
            "reason": "invalid_history_average",
            "calculatedAt": calculated_at,
        }

    return _structured_raw_volume_ratio(
        current_volume=current_volume,
        expected_volume=avg_daily_volume * expected_progress,
        source="daily_snapshot",
        history_volumes=volumes,
        calculated_at=calculated_at,
    )


# ── 历史构建（MongoDB snapshot_stock_rows + Redis TTL） ──────────────────────


def _slot_minutes(slot_time: str) -> int:
    if slot_time == "daily":
        return -1
    try:
        hours, minutes = slot_time.split(":")
        return int(hours) * 60 + int(minutes)
    except (TypeError, ValueError):
        return -1


def _candidate_intraday_slots(target_clock_minute: float | None) -> list[str]:
    """目标分钟在各快照类型里的相邻槽位（前一档 + 后一档）。

    插值只需要 prev/next 两行，按槽位过滤可把每 code 每天的行数从 240 降到 ≤6。
    """
    if target_clock_minute is None:
        return []
    from backend.snapshot_collector.slots import SLOT_TIMES

    target = int(round(target_clock_minute))
    slots: set[str] = set()
    for slot_times in SLOT_TIMES.values():
        parsed: list[tuple[int, str]] = []
        for slot in slot_times:
            try:
                hours, minutes = slot.split(":")
                parsed.append((int(hours) * 60 + int(minutes), slot))
            except (TypeError, ValueError):
                continue
        if not parsed:
            continue
        before = [(minute, slot) for minute, slot in parsed if minute <= target]
        after = [(minute, slot) for minute, slot in parsed if minute >= target]
        if before:
            slots.add(before[-1][1])
        if after:
            slots.add(after[0][1])
    return sorted(slots)


def _recent_trading_dates(
    db: Any,
    before_trading_date: str,
    limit_dates: int,
    types: tuple[str, ...] | str,
) -> list[str]:
    """数据驱动的最近交易日（走索引聚合，结果缓存 300s）。

    只查这些确切日期的行，避免按窗口/大 limit 拉 200+ bar。
    """
    type_key = "-".join(types) if isinstance(types, tuple) else str(types)
    cache_key = f"{REDIS_PREFIX}:dates:{before_trading_date}:{type_key}"
    cached = _cache_get(cache_key)
    if cached is not None and isinstance(cached.get("dates"), list):
        return [str(item) for item in cached["dates"]]

    query: dict[str, Any] = {"datasetId": DATASET_ID, "tradingDate": {"$lt": before_trading_date}}
    if isinstance(types, tuple):
        query["type"] = {"$in": list(types)}
    else:
        query["type"] = types
    pipeline = [
        {"$match": query},
        {"$group": {"_id": "$tradingDate"}},
        {"$sort": {"_id": -1}},
        {"$limit": limit_dates},
    ]
    dates = [
        str(item.get("_id"))
        for item in db["snapshot_stock_rows"].aggregate(pipeline)
        if item.get("_id")
    ]
    _cache_set(cache_key, {"dates": dates}, RECENT_DATES_CACHE_TTL_SECONDS)
    return dates


def _normalize_code(value: Any) -> str:
    from backend.market_proxy.quotes import normalize_stock_code

    return normalize_stock_code(value)


def _redis_client() -> Any | None:
    from backend.market_proxy.redis_client import get_hotlist_redis_client
    from backend.core.settings import get_settings

    return get_hotlist_redis_client(get_settings())


def _cache_get(key: str) -> dict[str, Any] | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(str(raw))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _cache_set(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.setex(
            key,
            max(1, int(ttl_seconds)),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception:
        return


def build_daily_history(
    db: Any,
    codes: list[str],
    before_trading_date: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, list[float]]:
    """最近 lookback_days 个交易日的日级成交量（按 tradingDate 降序，最新在前）。"""
    cache_key = f"{REDIS_PREFIX}:daily:{before_trading_date}"
    cached = _cache_get(cache_key) or {}
    result = dict(cached)
    # 缓存按日期共享、可能只含部分 code：缺的 code 必须补查合并，不能直接命中漏数据
    missing = [code for code in codes if code not in cached]
    if not missing:
        return result

    # 只查最近的 lookback_days 个交易日，不按窗口/大 limit 拉全量
    dates = _recent_trading_dates(db, before_trading_date, lookback_days, "daily")
    if not dates:
        _cache_set(cache_key, result, DAILY_CACHE_TTL_SECONDS)
        return result

    # 按 50 个 code 分块查询；行数 = code × dates，完全有界
    for start in range(0, len(missing), 50):
        chunk = missing[start : start + 50]
        by_code: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
        rows = db["snapshot_stock_rows"].find(
            {
                "datasetId": DATASET_ID,
                "type": "daily",
                "code": {"$in": chunk},
                "tradingDate": {"$in": dates},
            },
            {"_id": 0, "code": 1, "tradingDate": 1, "volume": 1, "timestamp": 1},
        ).sort([("timestamp", -1)])
        for row in rows:
            code = str(row.get("code") or "")
            trading_date = str(row.get("tradingDate") or "")
            try:
                volume = float(row.get("volume") or 0)
            except (TypeError, ValueError):
                continue
            if not code or not trading_date or not math.isfinite(volume) or volume <= 0:
                continue
            timestamp = int(row.get("timestamp") or 0)
            existing = by_code[code].get(trading_date)
            if existing is None or timestamp > existing[1]:
                by_code[code][trading_date] = (volume, timestamp)

        for code in chunk:
            entries = sorted(by_code[code].items(), key=lambda item: item[0], reverse=True)[
                :lookback_days
            ]
            if entries:
                result[code] = [volume for _, (volume, _timestamp) in entries]

    _cache_set(cache_key, result, DAILY_CACHE_TTL_SECONDS)
    return result


def warmup_daily_history_cache(
    db: Any,
    before_trading_date: str,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict[str, list[float]]:
    """启动预热：一次性装入最近 lookback_days 日全市场 daily 成交量到 Redis。

    与 ``build_daily_history`` 的差异：不按 code 过滤，直接扫全市场 daily 行，
    避免首次量比请求（热榜几百只 code 全部 miss）串行分块查 Mongo，造成量价
    字段长时间显示 ``--``。best-effort：失败/空数据不阻断启动。
    """
    cache_key = f"{REDIS_PREFIX}:daily:{before_trading_date}"
    cached = _cache_get(cache_key) or {}
    result = dict(cached)

    dates = _recent_trading_dates(db, before_trading_date, lookback_days, "daily")
    if not dates:
        return result

    by_code: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    rows = db["snapshot_stock_rows"].find(
        {
            "datasetId": DATASET_ID,
            "type": "daily",
            "tradingDate": {"$in": dates},
        },
        {"_id": 0, "code": 1, "tradingDate": 1, "volume": 1, "timestamp": 1},
    ).sort([("timestamp", -1)])
    for row in rows:
        code = str(row.get("code") or "")
        trading_date = str(row.get("tradingDate") or "")
        try:
            volume = float(row.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if not code or not trading_date or not math.isfinite(volume) or volume <= 0:
            continue
        timestamp = int(row.get("timestamp") or 0)
        existing = by_code[code].get(trading_date)
        if existing is None or timestamp > existing[1]:
            by_code[code][trading_date] = (volume, timestamp)

    for code, entries in by_code.items():
        sorted_entries = sorted(entries.items(), key=lambda item: item[0], reverse=True)[
            :lookback_days
        ]
        if sorted_entries:
            result[code] = [volume for _, (volume, _timestamp) in sorted_entries]

    _cache_set(cache_key, result, DAILY_CACHE_TTL_SECONDS)
    return result


def warmup_volume_ratio_daily() -> None:
    """启动预热入口：预装全市场 daily 历史成交量到 Redis（best-effort）。

    由 main.py 的 startup 事件在后台线程调用；失败只告警不阻断启动。
    数据来自 MongoDB snapshot_stock_rows（storage_backend == "mongodb"）。
    """
    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    trading_date = datetime.now(TZ_SHANGHAI).date().isoformat()
    warmup_daily_history_cache(db, trading_date)


def build_intraday_history(
    db: Any,
    codes: list[str],
    before_trading_date: str,
    target_clock_minute: float | None,
) -> dict[str, list[float]]:
    """分时快照历史：按目标分钟插值，最近 3 个交易日（最新在前）。"""
    if target_clock_minute is None:
        return {}
    slots = _candidate_intraday_slots(target_clock_minute)
    if not slots:
        return {}
    # 缓存 key 用“槽位签名”而不是分钟：同一槽位区间内命中，避免每分钟重查 Mongo
    cache_key = f"{REDIS_PREFIX}:intraday:{before_trading_date}:{'-'.join(slots)}"
    cached = _cache_get(cache_key) or {}
    result = dict(cached)
    missing = [code for code in codes if code not in cached]
    if not missing:
        return result

    # 只查最近 3 个交易日的相邻槽位行：行数 = code × 3 天 × ≤6 槽位，完全有界
    dates = _recent_trading_dates(db, before_trading_date, VOLUME_RATIO_HISTORY_DAYS, INTRADAY_TYPES)
    if not dates:
        _cache_set(cache_key, result, INTRADAY_CACHE_TTL_SECONDS)
        return result
    for start in range(0, len(missing), 50):
        chunk = missing[start : start + 50]
        rows_by_code: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        rows = db["snapshot_stock_rows"].find(
            {
                "datasetId": DATASET_ID,
                "type": {"$in": list(INTRADAY_TYPES)},
                "code": {"$in": chunk},
                "tradingDate": {"$in": dates},
                "slotTime": {"$in": slots},
            },
            {"_id": 0, "code": 1, "tradingDate": 1, "slotTime": 1, "volume": 1, "rowId": 1},
        ).sort([("timestamp", -1)])
        for row in rows:
            code = str(row.get("code") or "")
            trading_date = str(row.get("tradingDate") or "")
            slot_time = str(row.get("slotTime") or "")
            try:
                volume = float(row.get("volume") or 0)
            except (TypeError, ValueError):
                continue
            if (
                not code
                or not trading_date
                or slot_time == "daily"
                or not math.isfinite(volume)
                or volume <= 0
            ):
                continue
            rows_by_code[code][trading_date].append(
                {
                    "slotTime": slot_time,
                    "volume": volume,
                    "rowId": str(row.get("rowId") or ""),
                }
            )

        for code in chunk:
            volumes = _select_intraday_volumes(rows_by_code[code], target_clock_minute)
            if volumes:
                result[code] = volumes

    _cache_set(cache_key, result, INTRADAY_CACHE_TTL_SECONDS)
    return result


def _select_intraday_volumes(
    rows_by_date: dict[str, list[dict[str, Any]]],
    target_clock_minute: float,
) -> list[float]:
    volumes: list[float] = []
    for trading_date in sorted(rows_by_date.keys(), reverse=True):
        if len(volumes) >= VOLUME_RATIO_HISTORY_DAYS:
            break
        rows = sorted(rows_by_date[trading_date], key=lambda row: _slot_minutes(row["slotTime"]))
        previous: dict[str, Any] | None = None
        next_row: dict[str, Any] | None = None
        for row in rows:
            minute = _slot_minutes(str(row["slotTime"]))
            if minute < 0:
                continue
            if minute <= target_clock_minute:
                previous = row
            if minute >= target_clock_minute:
                next_row = row
                break
        if not previous:
            continue
        interpolated = _interpolate_snapshot_volume(
            previous,
            next_row if next_row and next_row["rowId"] != previous["rowId"] else None,
            target_clock_minute,
        )
        if interpolated is not None:
            volumes.append(interpolated)
    return volumes


def _interpolate_snapshot_volume(
    previous: dict[str, Any],
    next_row: dict[str, Any] | None,
    target_clock_minute: float,
) -> float | None:
    previous_volume = float(previous["volume"])
    if not next_row:
        return previous_volume
    previous_minute = _slot_minutes(str(previous["slotTime"]))
    next_minute = _slot_minutes(str(next_row["slotTime"]))
    if previous_minute < 0 or next_minute <= previous_minute:
        return previous_volume
    next_volume = float(next_row["volume"])
    if next_volume < previous_volume:
        return previous_volume
    progress = _clamp(
        (target_clock_minute - previous_minute) / (next_minute - previous_minute),
        0,
        1,
    )
    return previous_volume + (next_volume - previous_volume) * progress


# ── 对外入口 ──────────────────────────────────────────────────────────────────


def compute_volume_ratios(
    db: Any,
    stocks: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """按请求的当前成交量计算每股量比（后端 golden），部分异常逐 code 降级不阻断。"""
    current = now or datetime.now(TZ_SHANGHAI)
    trading_date = current.date().isoformat()
    clock_minute = ashare_volume_clock_minute(current)

    codes: list[str] = []
    payload_by_code: dict[str, float] = {}
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = _normalize_code(stock.get("code"))
        if not code:
            continue
        try:
            volume = float(stock.get("volume") or 0)
        except (TypeError, ValueError):
            volume = float("nan")
        if not math.isfinite(volume) or volume <= 0:
            continue
        if code not in payload_by_code:
            codes.append(code)
        payload_by_code[code] = volume

    items: dict[str, dict[str, Any]] = {}
    if not codes:
        return items

    # 量比结果缓存 60s：同交易日内同 codes 集合复用（量比 60s 粒度，与前端刷新门限一致），
    # 避免 60s 门限内前端重复请求仍触发历史快照查询（重 IO）。
    code_sig = hashlib.sha1(",".join(sorted(codes)).encode("utf-8")).hexdigest()[:16]
    result_cache_key = f"{REDIS_PREFIX}:result:{trading_date}:{code_sig}"
    cached = _cache_get(result_cache_key)
    if cached is not None:
        return cached

    daily = build_daily_history(db, codes, trading_date)
    intraday = build_intraday_history(db, codes, trading_date, clock_minute)
    for code in codes:
        items[code] = calculate_volume_ratio(
            payload_by_code[code],
            daily.get(code),
            intraday.get(code),
            current,
        )
    _cache_set(result_cache_key, items, VOLUME_RATIO_RESULT_CACHE_TTL_SECONDS)
    return items
