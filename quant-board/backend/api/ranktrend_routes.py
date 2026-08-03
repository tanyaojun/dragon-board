import math
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend import (
    RankTrendPythonEngine,
    analyze_rank_resonance,
    attention_rank_lookup,
    market_regime,
    percentile_rank,
)
from backend.data import repository_factory, snapshot_cache
from backend.settings import get_settings

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


def _to_engine_frame(bundle: dict[str, Any]) -> dict[str, Any]:
    """把 repository bundle 组装成引擎期望的 frame（含 marketContext）。"""
    return {
        "tradingDate": bundle.get("tradingDate"),
        "slotTime": bundle.get("slotTime"),
        "type": bundle.get("type"),
        "timestamp": bundle.get("timestamp"),
        "stocks": bundle.get("rows") or bundle.get("stocks") or [],
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
        projection="ranktrend",
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


def _analyze_frames(
    engine: RankTrendPythonEngine,
    frames: list[dict[str, Any]],
    series_by_code: dict[str, list[tuple[str, int, float]]],
    codes: list[str],
) -> list[dict[str, Any]]:
    """逐帧按「该股到该帧为止的出现序列前缀」跑 golden pipeline（旧 TS 合同）。

    技术/周期/风险/决策/观察/策略/jump 以该股最近 50 次出现中的前缀为输入，
    resonance 使用同一前缀（series.percentiles.slice(0, index+1)）。
    """
    wanted = set(codes) if codes else None
    series_index: dict[str, dict[str, int]] = {}
    for code, bars in series_by_code.items():
        series_index[code] = {key: idx for idx, (key, _rank, _pct) in enumerate(bars)}
    output: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        key = f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip()
        regime = market_regime(frame)
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
            stocks_out.append({"code": code, "analysis": analysis})
        output.append({
            "frameKey": key,
            "regime": regime,
            "marketMedianPercentile": market_median_percentile,
            "marketMedianShortChange": market_median,
            "marketSampleCount": market_sample_count,
            "totalCount": len(frame.get("stocks", [])),
            "stocks": stocks_out,
        })
    return output


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
def analyze_ranktrend(
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
    cached = cache.get_response(cache_key)
    if cached is not None:
        return cached

    repo = repository_factory.create_repository(db, enable_backup=False)
    engine = RankTrendPythonEngine()
    raw_frames, series_by_code = _load_frames_for_analysis(
        repo, dataset_id, snapshot_type, frame_keys, current_frame
    )
    frames_out = _analyze_frames(engine, raw_frames, series_by_code, codes)
    response = {"ok": True, "frames": frames_out, "source": "py_golden", "issues": []}
    response = {**response, "cache": {"hit": False, "store": "py_golden"}}
    if cache.get_generation(generation_key) == generation:
        cache.set_response(cache_key, response, ttl_seconds=_analyze_cache_ttl_seconds())
        cache.register_dependencies(
            cache_key,
            snapshot_cache.build_snapshot_cache_index_keys(
                prefix=get_settings().redis_key_prefix,
                dataset_id=dataset_id,
            ),
        )
    return response
