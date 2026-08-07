import json
import asyncio
import math
import threading
from time import perf_counter
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend.engine import (
    RankTrendPythonEngine,
    analyze_rank_resonance,
    attention_rank_lookup,
    market_regime,
    percentile_rank,
    _resonance_label,
)
from backend.analysis.theme.momentum import (
    compute_theme_momentum_series,
    stock_theme_exposure,
)
from backend.data.repositories import repository_factory
from backend.data.cache import snapshot_cache
from backend.core.settings import get_settings

router = APIRouter(tags=["ranktrend-analyze"])

SUPPORTED_SNAPSHOT_TYPES = {"quarter_hour", "half_hour", "hourly", "daily"}

# 方案 6.3：analyze 缓存 TTL 与快照读口保持一致（QUANT_BOARD_SNAPSHOT_CACHE_TTL_SECONDS，
# 默认 300s）。新快照 ingest 会递增 dataset generation 并按 dataset 索引删除旧 analyze 响应，
# 因此 TTL 只作为兜底，不需要再对齐某个固定刷新周期。
def _analyze_cache_ttl_seconds() -> int:
    return max(30, get_settings().snapshot_cache_ttl_seconds)

# 分析算法所需的最大回看窗口：共振至少 9 点序列（RESONANCE_MIN_SERIES_POINTS）、
# 技术稳定窗口 30、生命周期 15、横截面 3；取 30 同时满足全部轨道。
ANALYZE_MAX_TRACK_WINDOW = 30

# analyze 并发闸门：per-key 单飞锁 + 全局有界信号量（QUANT_BOARD_ANALYZE_MAX_CONCURRENCY，默认 2）。
# 目的：并发相同请求只计算一次（其余等待共享缓存结果），并限制全局 golden 计算并发，
# 防止前端刷新风暴或重复请求把 FastAPI 线程池打满导致 8000 假死。
# 端点 async 化后：等待信号量的请求是 asyncio 协程，不占线程池槽位；
# 只有拿到信号量的请求才通过 asyncio.to_thread 占用计算线程（最多 2 个）。
_ANALYZE_KEY_LOCKS: dict[str, asyncio.Lock] = {}
_ANALYZE_LOCKS_GUARD = threading.Lock()
_ANALYZE_SEMAPHORE: asyncio.Semaphore | None = None


def _analyze_semaphore() -> asyncio.Semaphore:
    global _ANALYZE_SEMAPHORE
    if _ANALYZE_SEMAPHORE is None:
        _ANALYZE_SEMAPHORE = asyncio.Semaphore(get_settings().quant_board_analyze_max_concurrency)
    return _ANALYZE_SEMAPHORE


def _analyze_key_lock(key: str) -> asyncio.Lock:
    with _ANALYZE_LOCKS_GUARD:
        lock = _ANALYZE_KEY_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _ANALYZE_KEY_LOCKS[key] = lock
        return lock


def _prune_analyze_key_locks() -> None:
    with _ANALYZE_LOCKS_GUARD:
        if len(_ANALYZE_KEY_LOCKS) > 512:
            for key in [k for k, lock in _ANALYZE_KEY_LOCKS.items() if not lock.locked()]:
                del _ANALYZE_KEY_LOCKS[key]


async def _analyze_with_cache_gate(
    cache: Any,
    cache_key: str,
    generation_key: str,
    generation: Any,
    ttl_seconds: int,
    dataset_id: str,
    compute: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """per-key 单飞 + 全局有界并发 + 双检缓存：同 key 并发只计算一次，其余等待共享缓存结果。

    async 版本：等待信号量的请求是协程（不占线程池）；重计算通过 asyncio.to_thread
    在受限的计算线程中执行（并发数 = QUANT_BOARD_ANALYZE_MAX_CONCURRENCY）。
    """
    cached = cache.get_response(cache_key)
    if cached is not None:
        return cached
    lock = _analyze_key_lock(cache_key)
    async with lock:
        cached = cache.get_response(cache_key)
        if cached is not None:
            return cached
        async with _analyze_semaphore():
            response = await asyncio.to_thread(compute)
        if cache.get_generation(generation_key) == generation:
            cache.set_response(cache_key, response, ttl_seconds=ttl_seconds)
            cache.register_dependencies(
                cache_key,
                snapshot_cache.build_snapshot_cache_index_keys(
                    prefix=get_settings().redis_key_prefix,
                    dataset_id=dataset_id,
                ),
            )
        return response


def _to_engine_frame(bundle: dict[str, Any]) -> dict[str, Any]:
    """把 repository bundle 组装成引擎期望的 frame（含 marketContext）。"""
    return {
        "tradingDate": bundle.get("tradingDate"),
        "slotTime": bundle.get("slotTime"),
        "type": bundle.get("type"),
        "timestamp": bundle.get("timestamp"),
        "stocks": bundle.get("rows") or bundle.get("stocks") or [],
        "hotThemes": bundle.get("hotThemes") or [],
        "marketContext": {
            "sentiment": bundle.get("sentiment") or {},
            "marketStats": bundle.get("marketStats") or {},
        },
    }


def _load_frames_for_analysis(
    repo: Any,
    dataset_id: str,
    snapshot_type: str,
    frame_keys: list[str],
    current_frame: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, int, float]]]]:
    # 最近帧优先：倒序加载最近 200 帧后反转回时间升序，供 replay 按时间推进。
    # 旧实现按升序加载最早 200 帧，数据集超过 200 帧后，观察面板请求的最近历史帧
    # 全部落在窗口外，过滤后为空并被误报为 503。
    bundles = repo.load_frame_bundles(
        dataset_id,
        snapshot_type=snapshot_type,
        sort="desc",
        projection="ranktrend+themes",
        limit=200,
    )
    frames = [_to_engine_frame(b) for b in reversed(bundles)]
    # 每股 attention 出现序列（最近 50 次出现，旧 TS rank-series 合同）：
    # 趋势分析输入是「该股的出现序列前缀」，不是连续帧窗口
    series_by_code = _build_code_attention_series(frames)
    if current_frame:
        current_stocks = current_frame.get("stocks") or []
        current_ranks, current_total = attention_rank_lookup(current_stocks)
        current_key = f"{current_frame.get('tradingDate')} {current_frame.get('slotTime')}".strip()
        for code, rank in current_ranks.items():
            series_by_code.setdefault(code, []).append(
                (current_key, rank, percentile_rank(rank, current_total))
            )
        frames.append({
            "tradingDate": current_frame.get("tradingDate"),
            "slotTime": current_frame.get("slotTime"),
            "type": snapshot_type,
            "timestamp": 0,
            "stocks": current_frame.get("stocks") or [],
            "marketContext": {
                "sentiment": current_frame.get("sentiment") or {},
                "marketStats": current_frame.get("marketStats") or {},
            },
        })
    if frame_keys:
        wanted = set(frame_keys)
        # 保留请求帧及其前 ANALYZE_MAX_TRACK_WINDOW-1 帧：共振/技术/生命周期算法需要
        # 足够的百分位历史序列（横截面只需 3 帧，取最大轨道窗口一并覆盖）
        keys = [f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip() for frame in frames]
        keep: set[str] = set()
        for index, key in enumerate(keys):
            if key in wanted:
                keep.update(keys[max(0, index - (ANALYZE_MAX_TRACK_WINDOW - 1)):index + 1])
        frames = [
            frame for frame in frames
            if f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip() in keep
        ]
    else:
        # 实时/最新：保留最近 ANALYZE_MAX_TRACK_WINDOW 帧（当前帧 + 回看窗口），
        # 保证共振/技术观察轨有足够的百分位序列；避免全量分析超时
        frames = frames[-ANALYZE_MAX_TRACK_WINDOW:]
    if not bundles and not current_frame:
        # 全源无数据：明确报告无数据；请求帧缺失但库里有帧时，返回可计算部分由前端逐帧降级
        raise HTTPException(status_code=503, detail="no frames available for analyze")
    return frames, series_by_code


def _build_code_attention_series(
    bundles: list[dict[str, Any]],
    max_bars: int = 50,
) -> dict[str, list[tuple[str, int, float]]]:
    """旧 TS 输入合同：每只代码最近 max_bars 次出现的 (frameKey, attention_rank, percentile)。

    按 avgRankNum 横截面重排（与前端 rank-series rank_basis=attention 一致）；
    综合排名不进入趋势序列。
    """
    series: dict[str, list[tuple[str, int, float]]] = {}
    for bundle in bundles:
        key = f"{bundle.get('tradingDate')} {bundle.get('slotTime')}".strip()
        if not key:
            continue
        stocks = bundle.get("stocks") or []
        ranks, total = attention_rank_lookup(stocks)
        for code, rank in ranks.items():
            series.setdefault(code, []).append((key, rank, percentile_rank(rank, total)))
    for code in series:
        series[code] = series[code][-max_bars:]
    return series


def _compute_theme_momentum_v2_context(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """从 frames 的 hotThemes 聚合日线序列并计算 v2 动量上下文（无 I/O，纯函数）。

    输出 {version, factors(top-20 by score), qualityFlags, computedAt}，供
    frame.themeMomentumContext 与每股只读投影使用。帧级先算一次，每股共享。
    """
    from backend.analysis.theme.daily_series import build_daily_series
    from backend.analysis.theme.momentum import compute_theme_momentum_v2

    sector_rows: list[dict[str, Any]] = []
    for frame in frames:
        for theme in frame.get("hotThemes") or []:
            if not isinstance(theme, dict):
                continue
            # theme 行可能不含日期字段，从 frame 补 tradingDate/slotTime
            theme = dict(theme)
            theme.setdefault("tradingDate", frame.get("tradingDate"))
            theme.setdefault("slotTime", frame.get("slotTime"))
            sector_rows.append(theme)
    try:
        daily = build_daily_series(sector_rows, [])
        result = compute_theme_momentum_v2(list(daily.values()))
    except Exception as exc:  # fail-visible：引擎异常不阻断 analyze（spec §8.1）
        import logging
        logging.getLogger(__name__).exception("theme_momentum_v2 compute failed: %s", exc)
        return {
            "version": "theme_momentum_v2",
            "factors": [],
            "factorsTop20": [],
            "qualityFlags": ["theme_momentum_engine_error"],
            "computedAt": int(frames[-1].get("timestamp") or 0) if frames else 0,
        }
    # context 保留全量 factors（供每股投影按 themeId 查找，避免 top-20 截断导致
    # 第 21 名以后题材每股恒 insufficient——MEDIUM-3）；仅响应序列化时截断 top-20。
    ranked = sorted(
        (v for v in result["factors"].values() if v.get("score") is not None),
        key=lambda item: -float(item["score"]),
    )
    return {
        "version": result["version"],
        "factors": ranked,
        "factorsTop20": ranked[:20],
        "qualityFlags": result["qualityFlags"],
        "computedAt": int(frames[-1].get("timestamp") or 0) if frames else 0,
    }


def _theme_momentum_projection(
    exposure: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """每股只读题材动量投影（第4轨数据源）：所属题材的 v2 分数/方向/角色/phaseLabel。

    完全不参与 resonance/decision（D2 完全解耦）；题材映射缺失或分数不足时
    返回 insufficient + 原因（fail-visible，不伪造）。
    """
    if not exposure:
        return {"status": "insufficient", "reasons": ["theme_mapping_missing"]}
    theme_id = str(exposure.get("themeId") or "")
    factors = {str(f.get("themeId") or ""): f for f in context.get("factors", [])}
    if theme_id not in factors:
        # 兼容旧形状：仅 factorsTop20 时也查一次
        factors = {
            str(f.get("themeId") or ""): f
            for f in context.get("factorsTop20", [])
        }
    factor = factors.get(theme_id)
    if not factor or factor.get("score") is None:
        return {"status": "insufficient", "reasons": ["theme_momentum_insufficient"]}
    return {
        "status": "ok",
        "themeId": theme_id,
        "themeName": factor.get("themeName") or exposure.get("themeName"),
        "score": factor.get("score"),
        "direction": factor.get("direction"),
        "role": exposure.get("role"),
        "phaseLabel": factor.get("phaseLabel"),
        "reasons": [
            f"板块整体动量 {factor.get('direction')}，该股为{exposure.get('role')}跟随"
        ],
    }


def _analyze_frames(
    engine: RankTrendPythonEngine,
    frames: list[dict[str, Any]],
    series_by_code: dict[str, list[tuple[str, int, float]]],
    codes: list[str],
    dataset_id: str = "dragonboard_live",
) -> list[dict[str, Any]]:
    """逐帧按「该股到该帧为止的出现序列前缀」跑 golden pipeline（旧 TS 合同）。

    技术/周期/风险/决策/观察/策略/jump 以该股最近 50 次出现中的前缀为输入，
    resonance 使用同一前缀（series.percentiles.slice(0, index+1)）。
    """
    wanted = set(codes) if codes else None
    momentum_series = _compute_theme_momentum_series_cached(frames, dataset_id)
    momentum_v2_ctx = _compute_theme_momentum_v2_context(frames)
    series_index: dict[str, dict[str, int]] = {}
    for code, bars in series_by_code.items():
        series_index[code] = {key: idx for idx, (key, _rank, _pct) in enumerate(bars)}
    output: list[dict[str, Any]] = []
    last_hot_themes: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        key = f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip()
        regime = market_regime(frame)
        hot_themes = frame.get("hotThemes") or last_hot_themes
        if frame.get("hotThemes"):
            last_hot_themes = hot_themes
        hot_themes_fallback = not bool(frame.get("hotThemes"))
        frame_momentum = momentum_series["frames"][index]
        theme_context = {
            "version": momentum_series["version"],
            "factors": sorted(
                frame_momentum["themes"].values(),
                key=lambda item: -float(item["score"]),
            )[:10],  # 响应只回传 top-10 题材动量摘要，控制体积；内部全量仍参与计算
            "marketThemeMedianShortChange": frame_momentum["marketThemeMedianShortChange"],
            "themeSampleCount": frame_momentum["themeSampleCount"],
            "hotThemesFallback": hot_themes_fallback,
            "qualityFlags": [
                *frame_momentum["qualityFlags"],
                *(["theme_hot_themes_fallback"] if hot_themes_fallback else []),
            ],
        }
        market_median, market_sample_count = _frame_market_median(frames, index)
        market_median_percentile = _frame_market_median_percentile(frame)
        stocks_out: list[dict[str, Any]] = []
        for stock in frame.get("stocks", []):
            if not isinstance(stock, dict):
                continue
            code = str(stock.get("code") or "")
            if not code or (wanted is not None and code not in wanted):
                continue
            bars = series_by_code.get(code)
            pos = series_index.get(code, {}).get(key)
            if not bars or pos is None:
                continue
            prefix = bars[: pos + 1]
            ranks = [item[1] for item in prefix]
            percentiles = [item[2] for item in prefix]
            signal = engine._build_signal(stock, frame, ranks, percentiles, regime, {})
            if not signal:
                continue
            analysis = signal.get("rankTrend") or {}
            jump = analysis.get("jump") or {}
            sample_quality = (analysis.get("meta") or {}).get("sampleQuality") or {}
            resonance = analyze_rank_resonance({
                "percentiles": percentiles,
                "sampleQuality": {
                    "status": sample_quality.get("status") or "insufficient",
                    "timelineValid": sample_quality.get("timelineValid", True),
                },
                "marketMedianShortChange": market_median if market_median is not None else float("nan"),
                "marketSampleCount": market_sample_count,
                "marketMedianPercentile": market_median_percentile,
                "jump": {
                    "direction": jump.get("direction") or "hold",
                    "event": jump.get("event") or "none",
                    "events": jump.get("events") or [],
                },
                "entry": {
                    "isNew": len(percentiles) == 1,
                    "currentAttentionPercentile": percentiles[-1] if percentiles else 0,
                },
            })
            analysis["resonance"] = resonance
            # 当前 live 帧无 hotThemes：题材匹配回退到最近历史帧的题材因子行
            exposure = stock_theme_exposure(stock, hot_themes)
            # D2 完全解耦：题材动量独立为只读投影，不再调节共振分数
            analysis["themeMomentum"] = _theme_momentum_projection(
                exposure, momentum_v2_ctx
            )
            if analysis["resonance"].get("status") == "ok":
                analysis["resonance"]["label"] = _resonance_label(analysis["resonance"].get("score"))
            _apply_resonance_final(analysis, analysis["resonance"])
            stocks_out.append({"code": code, "analysis": analysis})
        output.append({
            "frameKey": key,
            "regime": regime,
            "themeContext": theme_context,
            "themeMomentumContext": momentum_v2_ctx,
            "marketMedianPercentile": market_median_percentile,
            "marketMedianShortChange": market_median,
            "marketSampleCount": market_sample_count,
            "totalCount": len(frame.get("stocks", [])),
            "stocks": stocks_out,
        })
    return output


def _theme_momentum_series_fingerprint(frames: list[dict[str, Any]]) -> str:
    """题材动量序列的输入指纹：帧时间 + 逐帧 hotThemes（id/heat/rank/rotation）。"""
    rows: list[tuple[Any, Any]] = []
    for frame in frames:
        themes = sorted(
            (
                str(theme.get("themeId") or theme.get("entityKey") or theme.get("code") or ""),
                theme.get("heatScore"),
                int(theme.get("rank") or 0) if theme.get("rank") is not None else -1,
                str(theme.get("rotationState") or ""),
            )
            for theme in (frame.get("hotThemes") or [])
            if isinstance(theme, dict)
        )
        rows.append((frame.get("timestamp") or 0, themes))
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _compute_theme_momentum_series_cached(
    frames: list[dict[str, Any]],
    dataset_id: str,
) -> dict[str, Any]:
    """题材动量序列 Redis TTL 缓存：不同 codes 共享同一历史帧窗口时复用计算结果。"""
    cache = snapshot_cache.get_snapshot_redis_cache()
    settings = get_settings()
    generation_key = snapshot_cache.build_snapshot_cache_generation_key(
        prefix=settings.redis_key_prefix,
        dataset_id=dataset_id,
    )
    generation = cache.get_generation(generation_key)
    fingerprint = _theme_momentum_series_fingerprint(frames)
    cache_key = snapshot_cache.SnapshotCacheKeyBuilder(
        prefix=settings.redis_key_prefix
    ).response_key(
        "theme_momentum_series",
        resolved_dataset_id=dataset_id,
        params={"fingerprint": fingerprint, "generation": generation},
    )
    cached = cache.get_response(cache_key)
    if cached is not None and isinstance(cached.get("series"), dict):
        return cached["series"]
    series = compute_theme_momentum_series(frames)
    if cache.get_generation(generation_key) == generation:
        cache.set_response(cache_key, {"series": series}, ttl_seconds=60)
    return series


def _apply_resonance_final(analysis: dict[str, Any], resonance: dict[str, Any]) -> None:
    """resonance 下沉：最终信号 = resonance 方向/分数（对齐旧 TS applyResonanceFinals）。

    Python golden 直接输出融合后的 ``decision.final``，前端只读不再覆盖。
    口径：resonance insufficient → hold/0；否则 final = resonance 方向/分数。
    """
    decision = analysis.get("decision")
    if not isinstance(decision, dict):
        return
    status = str(resonance.get("status") or "")
    if status == "insufficient":
        decision["final"] = {"signal": "hold", "confidence": 0}
        return
    direction = str(resonance.get("direction") or "")
    score = resonance.get("score")
    if direction and score is not None:
        decision["final"] = {"signal": direction, "confidence": float(score)}


def _percentile(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _frame_market_median(frames: list[dict[str, Any]], index: int) -> tuple[float | None, int]:
    """旧 TS calculateMarketMedian 合同：当前帧与前第 3 个市场帧公共股票的
    attention 百分位变化中位数；sampleCount = 当前帧横截面股票数。"""
    start = max(0, index - 3)
    window = frames[start:index + 1]
    current = _frame_cross_section(window[-1])
    sample_count = len(current)
    if len(window) < 4 or not current:
        return None, sample_count
    first = _frame_cross_section(window[0])
    changes: list[float] = []
    for code, current_pct in current.items():
        first_pct = first.get(code)
        if first_pct is not None:
            changes.append(current_pct - first_pct)
    if len(changes) < 20:
        return None, sample_count
    return _median(changes), sample_count


def _frame_cross_section(frame: dict[str, Any]) -> dict[str, float]:
    """旧 TS buildFrameCrossSections 合同：过滤 avgRankNum > 0，按 (avgRankNum, code) 升序，
    百分位 = ((n - idx) / n) * 100（idx 从 0 开始）。"""
    stocks = frame.get("stocks") or []
    valid: list[tuple[str, float]] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        if not code:
            continue
        avg_num = stock.get("avgRankNum")
        try:
            avg_num = float(avg_num)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(avg_num) or avg_num <= 0:
            continue
        valid.append((code, avg_num))
    valid.sort(key=lambda item: (item[1], item[0]))
    total = len(valid)
    return {
        code: ((total - index) / total) * 100
        for index, (code, _avg) in enumerate(valid)
    }


def _frame_market_median_percentile(frame: dict[str, Any]) -> float | None:
    """该帧市场横截面 attention 百分位中位数（与 marketMedianShortChange 同口径）。"""
    return _median(list(_frame_cross_section(frame).values()))


def _normalize_current_frame(current_frame: dict[str, Any] | None) -> dict[str, Any] | None:
    """规范化 currentFrame 参与缓存键。

    只保留影响分析输出的稳定身份字段：
    - slotTime 去掉前端自增的 `current:N` 序列号，避免面板每次打开都生成新键导致缓存永不命中；
    - stocks 只保留 code/rank/avgRankNum（横截面排序原料），剔除 change/volumeRatio/zlje/zljzb
      等实时行情字段，避免行情一跳缓存键就变。
    TTL 范围内的行情时效性差异由 TTL 兜底，ingest 后 generation 递增强制换键。
    """
    if not current_frame:
        return None
    stocks = current_frame.get("stocks") or []
    ordered = sorted(
        (
            {
                "code": stock.get("code"),
                "rank": stock.get("rank"),
                "avgRankNum": stock.get("avgRankNum"),
            }
            for stock in stocks
            if isinstance(stock, dict)
        ),
        key=lambda stock: str(stock.get("code") or ""),
    )
    slot_time = current_frame.get("slotTime")
    normalized_slot = None
    if slot_time is not None:
        value = str(slot_time).strip()
        normalized_slot = "current" if value.startswith("current:") else value
    return {
        "tradingDate": current_frame.get("tradingDate"),
        "slotTime": normalized_slot,
        "stocks": ordered,
    }


def _analyze_cache_key(
    *,
    dataset_id: str,
    snapshot_type: str,
    frame_keys: list[str],
    codes: list[str],
    current_frame: dict[str, Any] | None,
    generation: int,
) -> str:
    """方案 6.3 缓存键：dataset/snapshot_type/frame_keys/codes/currentFrame 内容 + generation。"""
    builder = snapshot_cache.SnapshotCacheKeyBuilder(prefix=get_settings().redis_key_prefix)
    return builder.response_key(
        "ranktrend:analyze",
        resolved_dataset_id=dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "frame_keys": sorted(frame_keys),
            "codes": sorted(codes),
            "current_frame": _normalize_current_frame(current_frame),
            "_generation": generation,
        },
    )


@router.post("/api/ranktrend/analyze")
async def analyze_ranktrend(
    payload: dict[str, Any],
    db=Depends(lambda: repository_factory.get_runtime_mongodb_database()),
) -> dict[str, Any]:
    snapshot_type = str(payload.get("snapshotType") or "half_hour")
    if snapshot_type not in SUPPORTED_SNAPSHOT_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    dataset_id = str(payload.get("datasetId") or "dragonboard_live")
    codes = [str(c) for c in (payload.get("codes") or [])]
    frame_keys = [str(k) for k in (payload.get("frameKeys") or [])]
    current_frame = payload.get("currentFrame")

    # 方案 6.3：Redis 缓存，TTL 60s，键含请求内容与 dataset generation（ingest 后失效）
    cache = snapshot_cache.get_snapshot_redis_cache()
    generation_key = snapshot_cache.build_snapshot_cache_generation_key(
        prefix=get_settings().redis_key_prefix,
        dataset_id=dataset_id,
    )
    generation = cache.get_generation(generation_key)
    cache_key = _analyze_cache_key(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        frame_keys=frame_keys,
        codes=codes,
        current_frame=current_frame,
        generation=generation,
    )

    def compute_analyze() -> dict[str, Any]:
        repo = repository_factory.create_repository(db, enable_backup=False)
        engine = RankTrendPythonEngine()
        raw_frames, series_by_code = _load_frames_for_analysis(
            repo, dataset_id, snapshot_type, frame_keys, current_frame
        )
        frames_out = _analyze_frames(engine, raw_frames, series_by_code, codes, dataset_id=dataset_id)
        return {
            "ok": True,
            "frames": frames_out,
            "source": "py_golden",
            "issues": [],
            "cache": {"hit": False, "store": "py_golden"},
        }

    try:
        return await _analyze_with_cache_gate(
            cache=cache,
            cache_key=cache_key,
            generation_key=generation_key,
            generation=generation,
            ttl_seconds=_analyze_cache_ttl_seconds(),
            dataset_id=dataset_id,
            compute=compute_analyze,
        )
    finally:
        _prune_analyze_key_locks()