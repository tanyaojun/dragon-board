from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.settings import get_settings
from backend.data.cache import snapshot_cache
from backend.data.repositories import repository_factory
from backend.services.theme.hotlist_sentiment_service import get_hotlist_sentiment_service


router = APIRouter(prefix="/api/hotlist-sentiment", tags=["hotlist-sentiment"])

# 读口缓存版本号：响应结构变化时递增，避免旧结构响应被命中（2026-09-10 新增）。
# v2（2026-09-24）：series/slots 响应新增 rawStage/stageConfirmState/diagnostics 确认字段。
_HOTLIST_SENTIMENT_CACHE_VERSION = "v2"
_SERIES_CACHE_VERSION = _HOTLIST_SENTIMENT_CACHE_VERSION


def _series_cache_key(dataset_id: str, snapshot_type: str, days: int) -> str:
    prefix = get_settings().redis_key_prefix.strip(":")
    return f"{prefix}:hotlist:sentiment:series:{dataset_id}:{snapshot_type}:{days}:{_SERIES_CACHE_VERSION}"


class HotListSentimentPayload(BaseModel):
    tradingDate: str
    datasetId: str = "dragonboard_live"
    snapshotType: str = "half_hour"
    stage: str = "启动"
    riskLevel: str = "中"
    confidence: float = 0
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    turnover: dict[str, Any] = Field(default_factory=dict)
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # 阶段多帧确认字段（2026-09-24）：rawStage=截面事实、stage=确认投影、
    # stageConfirmState=确认状态（pending/pendingStage/pendingSince/confirmSlots/historyStatus）。
    # 未提供时不伪造（exclude_none 排除），旧结构手工导入保持原样入库。
    rawStage: str | None = None
    stageConfirmState: dict[str, Any] | None = None
    diagnostics: list[str] = Field(default_factory=list)


@router.post("/ingest")
def ingest_hotlist_sentiment(payload: HotListSentimentPayload) -> dict[str, Any]:
    query = {
        "datasetId": payload.datasetId,
        "snapshotType": payload.snapshotType,
        "tradingDate": payload.tradingDate,
    }

    try:
        # 每次取当前运行时 db 传入 service，兼容测试 monkeypatch（单例缓存不阻塞注入）
        get_hotlist_sentiment_service(
            repository_factory.get_runtime_mongodb_database()
        ).upsert(payload.model_dump(exclude_none=True))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB primary is unavailable: {exc}") from exc

    return {"status": "ok", **query}


@router.get("/series")
def get_hotlist_sentiment_series(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    days: int = 3,
) -> dict[str, Any]:
    """EOD 情绪序列读口：**Redis TTL 缓存 + 数据依赖失效**（2026-09-10）。

    此前该读口每次请求直读 MongoDB，最新交易日还可能触发 lazy compute
    （单日 analyze 级重算）——用户要求读口统一走 Redis TTL 缓存。

    缓存要点：

    - 命中即返回，响应标注 ``cache.hit``（可观测，不静默掩盖数据来源）；
    - **只缓存 ``ok=True`` 的成功响应**：降级/异常响应不缓存，避免把"MongoDB 不可用"
      固化成"看起来正常的历史序列"（fail-visible）；
    - TTL = ``QUANT_BOARD_HOTLIST_SENTIMENT_CACHE_TTL_SECONDS``（默认 60s）；
    - 依赖注册到 ``<prefix>:snapshot:index:dataset:<dataset_id>``：**任何**快照写入
      （ingest 路由或 collector 直写，统一经数据层 after-save 钩子）与 hotlist 重算
      都会立即失效本缓存，无需等 TTL 过期。
    """
    capped_days = max(1, min(int(days), 30))
    settings = get_settings()
    cache = snapshot_cache.get_snapshot_redis_cache()
    cache_key = _series_cache_key(dataset_id, snapshot_type, capped_days)
    cached = cache.get_response(cache_key)
    if cached is not None:
        return {**cached, "cache": {"hit": True, "store": "redis"}}

    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "items": []}
    try:
        from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

        response = HotListSentimentComputeService(db).ensure_series(dataset_id, snapshot_type, capped_days)
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"series_compute_failed: {exc}", "items": []}

    if response.get("ok"):
        response = {**response, "cache": {"hit": False, "store": "mongodb"}}
        cache.set_response(
            cache_key,
            response,
            ttl_seconds=settings.hotlist_sentiment_cache_ttl_seconds,
        )
        cache.register_dependencies(
            cache_key,
            snapshot_cache.build_snapshot_cache_index_keys(
                prefix=settings.redis_key_prefix,
                dataset_id=dataset_id,
            ),
        )
    return response


@router.get("/slots")
def get_hotlist_sentiment_slots(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
) -> dict[str, Any]:
    """当日槽位情绪文档序列读口（2026-09-15，前端「日内情绪轨迹」消费）。

    槽位文档由采集主链同步后处理链逐槽写入（analyze → 槽位情绪 → EOD），
    回答"今天情绪怎么走到现在"；series 读口（EOD 终值）回答"近几日怎么变"。
    trading_date 缺省回落最新交易日；无帧结构化降级（fail-visible，不伪装空序列）。
    缓存与 series 同口径：Redis TTL + dataset 索引依赖失效（采集链每槽写库即失效）。
    """
    capped_version = _HOTLIST_SENTIMENT_CACHE_VERSION
    settings = get_settings()
    cache = snapshot_cache.get_snapshot_redis_cache()
    trading_date = (trading_date or "").strip() or None
    cache_key = (
        f"{settings.redis_key_prefix.strip(':')}:hotlist:sentiment:slots:"
        f"{dataset_id}:{snapshot_type}:{trading_date or 'latest'}:{capped_version}"
    )
    cached = cache.get_response(cache_key)
    if cached is not None:
        return {**cached, "cache": {"hit": True, "store": "redis"}}

    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "items": []}
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService
    from backend.services.theme.hotlist_sentiment_service import get_hotlist_sentiment_service

    dates = HotListSentimentBackfillService(db).trading_dates(
        dataset_id=dataset_id, snapshot_type=snapshot_type
    )
    if not dates:
        return {"ok": False, "degraded": True, "reason": "no_snapshot_trading_date", "items": []}
    resolved_date = trading_date if trading_date in dates else dates[-1]
    try:
        docs = get_hotlist_sentiment_service(db).list_slot_documents(
            dataset_id, snapshot_type, resolved_date
        )
    except Exception as exc:
        return {
            "ok": False,
            "degraded": True,
            "reason": f"slots_read_failed: {exc}",
            "tradingDate": resolved_date,
            "items": [],
        }
    response = {
        "ok": True,
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": resolved_date,
        "items": [{key: value for key, value in doc.items() if key != "_id"} for doc in docs],
        "cache": {"hit": False, "store": "mongodb"},
    }
    cache.set_response(cache_key, response, ttl_seconds=settings.hotlist_sentiment_cache_ttl_seconds)
    cache.register_dependencies(
        cache_key,
        snapshot_cache.build_snapshot_cache_index_keys(
            prefix=settings.redis_key_prefix,
            dataset_id=dataset_id,
        ),
    )
    return response

def _normalize_market_limit_rows(items: Any) -> list[dict[str, Any]]:
    """THS 涨停池原始条目 → 明细面板行映射（纯映射，不含口径判定）。

    连板高度复用 analysis._parse_board_height_text（"首板"→1、"N连板"→N）；时间戳支持
    北京时间 unix 秒与 "HH:MM[:SS]" 文本两种形态 → HH:MM。数值字段缺失保留 None
    （前端显示 --），不伪造 0。
    """
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.analysis.hotlist.sentiment import _parse_board_height_text

    tz = ZoneInfo("Asia/Shanghai")

    def _opt_number(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None

    def _hhmm(raw: Any) -> str:
        if isinstance(raw, str):
            match = re.match(r"^(\d{1,2}):(\d{2})", raw.strip())
            if match:
                return f"{int(match.group(1)):02d}:{match.group(2)}"
        try:
            seconds = int(float(raw))
        except (TypeError, ValueError):
            return ""
        if seconds <= 1_000_000_000:  # 非 epoch 秒量级（如 HHMMSS 数字）不误读为时间戳
            return ""
        return datetime.fromtimestamp(seconds, tz).strftime("%H:%M")

    rows: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().zfill(6)
        if not code:
            continue
        rows.append(
            {
                "code": code,
                "name": str(item.get("name") or "").strip(),
                "change": _opt_number(item.get("change_rate")),
                "highDays": str(item.get("high_days") or "").strip(),
                "boardHeight": max(
                    _parse_board_height_text(item.get("high_days")),
                    _parse_board_height_text(item.get("continue_day")),
                ),
                "firstLimitUpTime": _hhmm(item.get("first_limit_up_time")),
                "lastLimitUpTime": _hhmm(item.get("last_limit_up_time")),
                "turnoverRate": _opt_number(item.get("turnover_rate")),
                "openNum": _opt_number(item.get("open_num")),
                "limitUpType": str(item.get("limit_up_type") or "").strip(),
                "reasonType": str(item.get("reason_type") or "").strip(),
            }
        )
    return rows


@router.get("/limit-stocks")
async def get_hotlist_sentiment_limit_stocks(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
) -> dict[str, Any]:
    """涨停池成分股明细读口（2026-09-25，市场概览三容器 → 明细面板消费）。

    一次返回热榜池涨停 / 昨日热榜涨停两份名单（复用 analysis 涨停证据口径，与
    limitEvidence 聚合同源）+ 全市场涨停名单（THS 涨停池实时接口，指定最近交易日取数，
    非交易日自然回落上一交易日）。各部分失败结构化标注不互相阻断（fail-visible）。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {
            "ok": False,
            "degraded": True,
            "reason": f"mongodb_unavailable: {exc}",
            "tradingDate": "",
            "diagnostics": [],
            "pool": {"rows": []},
            "market": {"rows": [], "degraded": True, "reason": "not_loaded"},
            "yesterday": {"rows": []},
        }
    import asyncio

    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    # 同步 Mongo 多次往返放线程池，避免阻塞事件循环（本路由因 THS 上游为 async 而 async def）
    detail = await asyncio.to_thread(
        HotListSentimentBackfillService(db).limit_stocks_detail, dataset_id, snapshot_type
    )
    if not detail.get("ok"):
        detail.setdefault("market", {"rows": [], "degraded": True, "reason": "not_loaded"})
        return detail

    market: dict[str, Any] = {"rows": [], "degraded": False, "reason": None}
    trading_date = str(detail.get("tradingDate") or "")
    if trading_date:
        try:
            from backend.market_proxy.limitup import get_limitup_service

            payload = await get_limitup_service().get_limit_up_list(trading_date.replace("-", ""))
            data = payload.get("data") if isinstance(payload, dict) else None
            items = data.get("info") if isinstance(data, dict) else None
            market["rows"] = _normalize_market_limit_rows(items)
            if not market["rows"]:
                market["degraded"] = True
                market["reason"] = "THS 涨停池当日无数据（info 为空）"
        except Exception as exc:
            market = {"rows": [], "degraded": True, "reason": f"limitup_upstream_failed: {exc}"}
    else:
        market["degraded"] = True
        market["reason"] = "no trading date resolved"
    detail["market"] = market
    return detail
