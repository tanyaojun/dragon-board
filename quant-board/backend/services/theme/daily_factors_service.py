"""题材日频因子计算与落库服务（设计 §5.1，Task1 生产接线 2026-09-27）。

职责：把 daily 收盘槽 stock rows × theme_stock_mappings 聚合为题材级
拥挤度分位因子（D1），落库 theme_daily_factors 集合并写 Redis 缓存。

编排语义：
  - 取数只读快照集合（db 直查最小投影，对齐 R1/Phase 1 runner 范式）；
  - 收盘槽选择复用 backtest_service._close_slot_rows_by_day（15:30 优先 /
    15:00 回退，单一口径不复制）；
  - 自动模式（target_dates=None）补算"有 stock rows 但缺因子行"的日期
    （采集晚到/停机日的 catch-up），单轮上限 max_dates_per_run；
  - fail-visible：分位历史不足/零覆盖/字段缺失全部显式标记；唯一不写数据
    的情形是全源无 stock rows（no_source_data）。

调度：ThemeDailyFactorsScheduler（FastAPI lifespan 内 asyncio 任务，
对齐 ThemeMappingRefreshScheduler 先例），每日盘后执行一次。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.analysis.theme.daily_series import build_daily_series
from backend.analysis.theme.factors_daily import (
    build_daily_factor_rows,
    build_heat_level_streak_values,
    build_momentum_v2_daily_values,
    merge_heat_level_streak_into_rows,
    merge_momentum_v2_into_rows,
)
from backend.analysis.theme.heat_level import resolve_heat_level
from backend.core.settings import get_settings
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.data.repositories.theme_daily_factor_repository import ThemeDailyFactorRepository
from backend.services.backtest_service import _close_slot_rows_by_day

DATASET_ID = "dragonboard_live"
DEFAULT_WINDOW = 60
DEFAULT_MIN_PERIODS = 10
LOOKBACK_BUFFER_CALENDAR_DAYS = 30
MAX_DATES_PER_RUN = 10


def _load_stock_daily(
    db: Any, dataset_id: str, start_date: str, end_date: str
) -> tuple[dict[str, dict[str, dict[str, float | None]]], dict[str, int]]:
    """daily 收盘槽 stock rows → {date: {"amount": {code: v}, "turnover": {code: v}}}

    与 Phase 2 runner load_stock_daily 同口径；缺字段行计数上报（fail-visible）。
    """
    rows = list(
        db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "type": "daily", "tradingDate": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0, "tradingDate": 1, "slotTime": 1, "code": 1, "amount": 1, "turnoverRate": 1},
        )
    )
    missing = {"noCode": 0, "amount": 0, "turnoverRate": 0}
    close_rows_by_day = _close_slot_rows_by_day([row for row in rows if isinstance(row, dict)])
    out: dict[str, dict[str, dict[str, float | None]]] = {}
    for d, day_rows in close_rows_by_day.items():
        amounts: dict[str, float] = {}
        turnovers: dict[str, float] = {}
        for row in day_rows:
            code = row.get("code")
            if not code:
                missing["noCode"] += 1
                continue
            amount = row.get("amount")
            if isinstance(amount, (int, float)):
                amounts[str(code)] = float(amount)
            else:
                missing["amount"] += 1
            turnover = row.get("turnoverRate")
            if isinstance(turnover, (int, float)):
                turnovers[str(code)] = float(turnover)
            else:
                missing["turnoverRate"] += 1
        if amounts or turnovers:
            out[d] = {"amount": amounts, "turnover": turnovers}
    return out, missing


def _load_daily_sector_rows(db: Any, dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """daily 类型 hot_theme sector rows（v2 日线序列源，245 题材全覆盖）。"""
    return list(
        db["snapshot_sector_rows"].find(
            {
                "datasetId": dataset_id,
                "type": "daily",
                "entityType": "hot_theme",
                "tradingDate": {"$gte": start_date, "$lte": end_date},
            },
            {
                "_id": 0,
                "tradingDate": 1,
                "slotTime": 1,
                "entityType": 1,
                "entityKey": 1,
                "themeId": 1,
                "entityName": 1,
                "themeName": 1,
                "change": 1,
                "ztCount": 1,
                "breadthScore": 1,
                "mainNetInflow": 1,
                "crowdingRisk": 1,
                "heatLevel": 1,
                "heatScore": 1,
                "metadata": 1,
            },
        )
    )


def _load_theme_members(db: Any) -> dict[str, set[str]]:
    members: dict[str, set[str]] = defaultdict(set)
    for doc in db["theme_stock_mappings"].find({}, {"themeId": 1, "stockCode": 1}):
        theme_id = doc.get("themeId")
        code = doc.get("stockCode")
        if theme_id is not None and code:
            members[str(theme_id)].add(str(code))
    return dict(members)


def _load_theme_names(db: Any) -> dict[str, str]:
    names: dict[str, str] = {}
    for doc in db["themes"].find({}, {"id": 1, "name": 1}):
        theme_id = doc.get("id")
        if theme_id and doc.get("name"):
            names[str(theme_id)] = str(doc["name"])
    return names


def _write_latest_cache(dataset_id: str, trading_date: str, day_rows: list[dict[str, Any]]) -> bool:
    """最近一日横截面写 Redis（best-effort：失败由调用方打标，不阻断落库结果）。"""
    try:
        settings = get_settings()
        cache = snapshot_cache.get_snapshot_redis_cache()
        key = f"{settings.redis_key_prefix.strip(':')}:theme-daily-factors:{dataset_id}:{trading_date}"
        payload = {
            "datasetId": dataset_id,
            "tradingDate": trading_date,
            "factors": {
                str(row.get("themeId")): {
                    "themeName": row.get("themeName"),
                    "factors": row.get("factors"),
                    "qualityFlags": row.get("qualityFlags"),
                }
                for row in day_rows
            },
        }
        try:
            cache.set_response(key, payload, ttl_seconds=settings.theme_daily_factors_cache_ttl_seconds)
            return True
        except Exception:
            # 连接超时（0.2s 预算）在重计算进程内偶发：重试一次（连接懒建，第二次通常已就绪）
            cache.set_response(key, payload, ttl_seconds=settings.theme_daily_factors_cache_ttl_seconds)
            return True
    except Exception:
        return False


def compute_and_store_daily_factors(
    database: Any = None,
    *,
    dataset_id: str = DATASET_ID,
    target_dates: list[str] | None = None,
    window: int = DEFAULT_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
    max_dates_per_run: int = MAX_DATES_PER_RUN,
    write_redis_cache: bool = True,
    today: str | None = None,
) -> dict[str, Any]:
    """计算并落库题材日频因子（幂等：同键覆盖写）。

    返回结构化运行结果（status/ok/qualityFlags），供调度器 status 与诊断消费；
    全量回填（Phase 4 前）= 显式传 target_dates 循环调用或调大 max_dates_per_run。
    """
    started_at = datetime.now(UTC).isoformat()
    db = database if database is not None else get_runtime_mongodb_database()
    factor_repo = ThemeDailyFactorRepository(db)
    end_day = today or date.today().isoformat()
    start_day = (
        date.fromisoformat(end_day) - timedelta(days=window * 2 + LOOKBACK_BUFFER_CALENDAR_DAYS)
    ).isoformat()

    stock_daily, missing = _load_stock_daily(db, dataset_id, start_day, end_day)
    sector_rows = _load_daily_sector_rows(db, dataset_id, start_day, end_day)
    mode = "auto" if target_dates is None else "explicit"
    if not stock_daily and not sector_rows:
        return {
            "status": "no_source_data",
            "ok": False,
            "datasetId": dataset_id,
            "mode": mode,
            "targetDates": sorted(set(target_dates)) if target_dates is not None else [],
            "computedDates": [],
            "datesWithoutRows": sorted(set(target_dates)) if target_dates is not None else [],
            "skippedExistingDates": [],
            "deferredDates": [],
            "rowCount": 0,
            "window": window,
            "minPeriods": min_periods,
            "stockRowMissing": missing,
            "qualityFlags": ["no_stock_rows"],
            "redisCacheWritten": False,
            "startedAt": started_at,
            "finishedAt": datetime.now(UTC).isoformat(),
        }

    # v2 序列源与覆盖日历（2026-09-27 因子口径收敛批）
    series_by_theme = build_daily_series(sector_rows, [])
    series_dates: set[str] = set()
    for series in series_by_theme.values():
        series_dates.update(series.dates)
    source_dates = set(stock_daily) | {str(r.get("tradingDate")) for r in sector_rows if r.get("tradingDate")}

    skipped_existing: list[str] = []
    deferred: list[str] = []
    if target_dates is None:
        # 完整度 = 拥挤行存在 且（v2 行存在 或 该日不在 v2 序列覆盖内）：
        # 新增因子维度后，缺新维度的旧日期自动补算（自愈），不依赖一次性回填。
        already_crowding = set(factor_repo.computed_dates(dataset_id, start_day, end_day))
        already_v2 = set(
            factor_repo.dates_with_factor_key(dataset_id, start_day, end_day, "factors.momentumV2")
        )
        already_streak = set(
            factor_repo.dates_with_factor_key(dataset_id, start_day, end_day, "factors.heatLevelStreak")
        )
        complete = {d for d in already_crowding if d not in series_dates or (d in already_v2 and d in already_streak)}
        candidates = sorted(source_dates - complete)
        skipped_existing = sorted(source_dates & complete)
        targets = candidates[-max_dates_per_run:] if len(candidates) > max_dates_per_run else candidates
        deferred = sorted(set(candidates) - set(targets))
    else:
        targets = sorted(set(target_dates))

    members = _load_theme_members(db)
    theme_names = _load_theme_names(db)
    flags: list[str] = []
    if not members:
        flags.append("theme_mappings_empty")
    rows, build_flags = build_daily_factor_rows(
        stock_daily,
        members,
        target_dates=targets,
        theme_names=theme_names,
        window=window,
        min_periods=min_periods,
    )
    flags.extend(build_flags)
    # 动量 v2（设计 §2.3，2026-09-27 因子口径收敛批）：同一调度同一集合，
    # 序列源=daily sector rows；v2-only 题材产行（拥挤字段 None + 标记）。
    v2_by_day, v2_flags = build_momentum_v2_daily_values(series_by_theme, target_dates=targets)
    rows, v2_merge_flags = merge_momentum_v2_into_rows(rows, v2_by_day, theme_names=theme_names)
    flags.extend(v2_flags)
    flags.extend(v2_merge_flags)
    # 日级持续性（2026-09-27 persistenceScore 重建立项 Q1=c）：
    # 原料= daily sector rows 的 heatLevel（resolve_heat_level 统一消费规则，
    # v1 回退 heatScore≤100、v2 不回退、缺失显式 None）；连续 ≥ 70 计数。
    heat_level_by_theme: dict[str, dict[str, float | None]] = defaultdict(dict)
    for row in sector_rows:
        theme_id = str(row.get("themeId") or "")
        if not theme_id:
            continue
        day = str(row.get("tradingDate") or "")
        if not day:
            continue
        heat_level_by_theme[theme_id][day] = resolve_heat_level(row)
    streak_by_day, streak_flags = build_heat_level_streak_values(
        dict(heat_level_by_theme), target_dates=targets,
    )
    rows, streak_merge_flags = merge_heat_level_streak_into_rows(
        streak_by_day, rows, theme_names=theme_names,
    )
    flags.extend(streak_flags)
    flags.extend(streak_merge_flags)

    rows_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_day[row["tradingDate"]].append(row)
    written: list[str] = []
    for d in sorted(rows_by_day):
        factor_repo.upsert_day(dataset_id, d, rows_by_day[d])
        written.append(d)
    dates_without_rows = [d for d in targets if d not in rows_by_day]

    if not targets:
        status = "up_to_date"
    elif not written and dates_without_rows:
        status = "no_rows"
    elif dates_without_rows:
        status = "partial"
    else:
        status = "ok"

    redis_written = False
    if write_redis_cache and written:
        latest = max(written)
        redis_written = _write_latest_cache(dataset_id, latest, rows_by_day[latest])
        if not redis_written:
            flags.append("redis_cache_write_failed")

    return {
        "status": status,
        "ok": status in {"ok", "up_to_date"},
        "datasetId": dataset_id,
        "mode": mode,
        "targetDates": targets,
        "computedDates": written,
        "datesWithoutRows": dates_without_rows,
        "skippedExistingDates": skipped_existing,
        "deferredDates": deferred,
        "rowCount": len(rows),
        "window": window,
        "minPeriods": min_periods,
        "stockRowMissing": missing,
        "qualityFlags": flags,
        "redisCacheWritten": redis_written,
        "startedAt": started_at,
        "finishedAt": datetime.now(UTC).isoformat(),
    }
