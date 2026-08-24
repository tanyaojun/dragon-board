import json
import asyncio
import math
import threading
from datetime import datetime
from time import perf_counter
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    RankTrendPythonEngine,
    analyze_rank_resonance,
    attention_rank_lookup,
    frame_market_median,
    frame_market_median_percentile,
    frame_market_percentiles,
    market_regime,
    percentile_rank,
    _resonance_label,
)
from backend.analysis.ranktrend.volume_price import (
    _synergy_tier,
    assemble_observation,
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

# analyze 缓存 TTL 动态化（2026-08-13）：
# - 盘中交易时段（9:15-11:30 / 13:00-15:30）：300s，保证盘中数据新鲜度；
# - 盘后/非交易时段：1800s，配合 dump.rdb 恢复覆盖关机重启，避免冷启动逐股重算 5-10s。
# 新快照 ingest 会递增 dataset generation 并按 dataset 索引删除旧 analyze 响应，
# 因此 TTL 只作为兜底，不需要再对齐某个固定刷新周期。
RANK_TREND_ANALYZE_CACHE_TTL_INTRA_DAY_SECONDS = 300
RANK_TREND_ANALYZE_CACHE_TTL_AFTER_HOURS_SECONDS = 1800


def _is_intraday_trading_time(now: datetime) -> bool:
    """A 股盘中交易时段（纯时间窗口，不含交易日判断）。

    早盘 9:15-11:30（含集合竞价），下午 13:00-15:30（含盘后固定价格）。
    午休、周末、节假日按盘后处理（数据静态，可用更长 TTL）。
    """
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 15 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60 + 30)


def _analyze_cache_ttl_seconds() -> int:
    if _is_intraday_trading_time(datetime.now()):
        return RANK_TREND_ANALYZE_CACHE_TTL_INTRA_DAY_SECONDS
    return RANK_TREND_ANALYZE_CACHE_TTL_AFTER_HOURS_SECONDS

# 分析算法所需的最大回看窗口：共振至少 9 点序列（RESONANCE_MIN_SERIES_POINTS）、
# 技术稳定窗口 30、生命周期 15、横截面 3；取 30 同时满足全部轨道。
ANALYZE_MAX_TRACK_WINDOW = 30

# 单股/少量 codes 的 analyze（如排名趋势面板打开）加载帧数：趋势序列 max_bars=50，
# 60 帧足够热门股凑满 50 次出现（与全量 200 帧序列质量一致），数据量仅为 200 帧的 1/3，
# 避免每次打开面板都从 MongoDB/Redis 搬运 200 帧 × 全市场（~70MB，3.5-4.5s）成为冷启动瓶颈。
ANALYZE_SMALL_CODES_LOAD_LIMIT = 60

# 全市场最新帧 analyze（无 frame_keys / codes 大批量）的历史窗帧数。
# 实测依据（dragonboard_live, half_hour, 2026-08-23）：当前帧活跃股 232 只中 207 只历史 ≥50 次；
# 它们"最近 50 次出现"覆盖的连续帧跨度 P90=277、max=824、均值 121。旧默认 200 帧对 P90 活跃股
# 不足（200 帧内约 36 次 < 50），导致大量活跃股 macd/momentum 序列不完整。取 280（P90 上沿）
# 覆盖约 90% 活跃股；仍不足的股由 engine 的 sampleQuality 标为 insufficient（fail-visible）。
# 性能：280 帧 × projection="ranktrend+themes" 仅略高于旧 200 帧（+40%），且有 Redis analyze 缓存。
ANALYZE_FULL_MARKET_LOAD_LIMIT = 280

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
    codes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, int, float]]]]:
    # 最近帧优先：倒序加载最近 ANALYZE_FULL_MARKET_LOAD_LIMIT 帧后反转回时间升序，供 replay 按时间推进。
    # 旧实现按升序加载最早 200 帧，数据集超过 200 帧后，观察面板请求的最近历史帧
    # 全部落在窗口外，过滤后为空并被误报为 503。
    # 单股/少量 codes（无 frame_keys）只加载 60 帧：趋势序列 max_bars=50 已足够，
    # 避免每次打开排名趋势面板都搬运全量（~70MB）成为 4s+ 冷启动瓶颈。
    load_limit = ANALYZE_FULL_MARKET_LOAD_LIMIT
    skip_cache_write = False
    if not frame_keys and codes and len(codes) <= ANALYZE_SMALL_CODES_MAX:
        load_limit = ANALYZE_SMALL_CODES_LOAD_LIMIT
        # 单股面板低频打开：60 帧 bundles 缓存（~21MB）写读都 ~0.9s，几乎无净收益，
        # 跳过缓存写，直接读 MongoDB（stock+sector ~1.7s）反而更省。
        skip_cache_write = True
    bundles = repo.load_frame_bundles(
        dataset_id,
        snapshot_type=snapshot_type,
        sort="desc",
        projection="ranktrend+themes",
        limit=load_limit,
        skip_cache_write=skip_cache_write,
    )
    frames = [_to_engine_frame(b) for b in reversed(bundles)]
    # 每股 attention 出现序列（最近 50 次出现，旧 TS rank-series 合同）：
    # 趋势分析输入是「该股的出现序列前缀」，不是连续帧窗口
    series_by_code = _build_code_attention_series(frames)
    if current_frame:
        current_stocks = current_frame.get("stocks") or []
        current_key = f"{current_frame.get('tradingDate')} {current_frame.get('slotTime')}".strip()
        # current 帧全市场 attention rank/percentile（与历史帧同构：按 avgRankNum 排序，
        # G3 权威算法），供新进热榜（历史无记录）股票注册单点序列用。
        cur_ranks, cur_total = attention_rank_lookup(current_stocks)
        cur_pcts = {code: percentile_rank(rank, cur_total) for code, rank in cur_ranks.items()}
        for code in {str(s.get("code")) for s in current_stocks if isinstance(s, dict)}:
            bars = series_by_code.get(code)
            if bars:
                # 2026-08-23 修复 A（防过拟合排查）：当前帧 percentile 不再用前端派生的
                # rank/avgRankNum（随 zljzb/八平台热榜重算、会漂移，污染横截面/趋势/周期）。
                # 改为复用该 code 在权威历史帧的最后一个 percentile——横截面/趋势/周期只用
                # 权威源，当前帧仅作展示帧（量价仍用其字段）。
                _key, _rank, _pct = bars[-1]
                series_by_code[code].append((current_key, _rank, _pct))
            elif code in cur_pcts:
                # 2026-08-24 新进热榜（历史无该 code）：用 current 帧截面 percentile 注册
                # 单点序列（与历史帧同构的 attention percentile，非前端派生值），使新股
                # 也能获得五维信号——横截/量价/共振可算，趋势/周期因单点样本走
                # sampleQuality=insufficient 降级（fail-visible），不再整只被丢弃。
                series_by_code[code] = [(current_key, cur_ranks[code], cur_pcts[code])]
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


# 单股/少量 codes 判定阈值：codes 数量 <= 此值视为"面板单股/小批量"场景，
# 走 60 帧轻量加载（见 _load_frames_for_analysis）；超过则视为全市场首屏/信号刷新。
ANALYZE_SMALL_CODES_MAX = 50


def _analyze_one_stock(args: tuple[Any, ...]) -> dict[str, Any] | None:
    """进程池 worker：单只股票的完整 golden 计算（纯函数，无共享状态）。

    args 依次为 (config, stock, frame, ranks, percentiles, regime, hot_themes,
    momentum_v2_ctx, market_median, market_sample_count, market_median_percentile)。
    返回 {code, analysis} 或 None。engine 按需构造轻量实例（仅含 config，不注入
    sentiment_provider——_build_signal 不依赖它，hotlistSentiment 已预置进 frame）。
    """
    (
        config, stock, frame, ranks, percentiles, regime, hot_themes,
        momentum_v2_ctx, market_median, market_sample_count, market_median_percentile,
    ) = args
    engine = RankTrendPythonEngine(config=config)
    signal = engine._build_signal(stock, frame, ranks, percentiles, regime, {}, assemble=False)
    if not signal:
        return None
    code = str(stock.get("code") or "")
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
    }, config)
    analysis["resonance"] = resonance
    # 当前 live 帧无 hotThemes：题材匹配回退到最近历史帧的题材因子行
    exposure = stock_theme_exposure(stock, hot_themes)
    # D2 完全解耦：题材动量独立为只读投影，不再调节共振分数
    analysis["themeMomentum"] = _theme_momentum_projection(exposure, momentum_v2_ctx)
    # 2026-08-18（前端链路对齐）：_build_signal(assemble=False) 不挂载 crossSection，
    # 而 synergy 第 5 维投票（tierSynergyCrossSectionVote=1.0 默认打开）需要 cs_tier——
    # 否则前端【四维】档位停留在旧投票口径。这里与 replay 链路同源补挂载
    # （percentiles/market_median_percentile 已在 args 中）。
    from backend.analysis.ranktrend.cross_section import compute_cross_section

    analysis.setdefault("observation", {})["crossSection"] = compute_cross_section(
        percentiles,
        market_median_percentile,
        config,
    )
    analysis.setdefault("technical", {})["crossSection"] = analysis["observation"]["crossSection"]
    # 四象协同轴（阶段 2）：组装下沉（回测方案 §3.2）——observation.volumePrice / synergy
    # 由 engine 层 assemble_observation 统一产出，与 replay 链路同源同构
    assemble_observation(analysis, stock, config)
    # 2026-08-23 前后端分离 G2：displayStatus 状态分类后端 golden 生产（前端只做 label 映射）
    from backend.analysis.ranktrend.display_status import compute_display_status

    analysis["displayStatus"] = compute_display_status(analysis, stock)
    _apply_resonance_final(analysis, analysis["resonance"], config)
    if analysis["resonance"].get("status") == "ok":
        analysis["resonance"]["label"] = _resonance_label(analysis["resonance"].get("score"))
    return {"code": code, "analysis": analysis}


def _latest_market_percentiles(frames: list[dict[str, Any]]) -> dict[str, float]:
    """最近一个含量能字段的全市场帧分位（G3）。currentFrame 归一化后缺失量能字段，
    故跳过 currentFrame 帧，取最近真实全市场快照帧的分位（后端 golden）。"""
    for frame in reversed(frames):
        pct = frame_market_percentiles(frame)
        if pct:
            return pct
    return {}


def _analyze_frames(
    engine: RankTrendPythonEngine,
    frames: list[dict[str, Any]],
    series_by_code: dict[str, list[tuple[str, int, float]]],
    codes: list[str],
    dataset_id: str = "dragonboard_live",
    *,
    full_history: bool = True,
) -> list[dict[str, Any]]:
    """逐帧按「该股到该帧为止的出现序列前缀」跑 golden pipeline（旧 TS 合同）。

    技术/周期/风险/决策/观察/策略/jump 以该股最近 50 次出现中的前缀为输入，
    resonance 使用同一前缀（series.percentiles.slice(0, index+1)）。

    full_history=False 用于首屏全市场场景（无 frame_keys）：历史帧仅输出轻量 meta
    （currentRank/currentPercentile），完整四信号只在最后一帧计算——前端
    updateLatestAnalysisSeries 只消费历史帧的 meta 两字段，完整分析由观察面板按需
    单股（带 frame_keys）再请求。这样把 30 帧 × 全市场的逐股重算压缩为 1 帧完整 + 29 帧轻量。
    """
    wanted = set(codes) if codes else None
    momentum_series = _compute_theme_momentum_series_cached(frames, dataset_id)
    momentum_v2_ctx = _compute_theme_momentum_v2_context(frames)
    series_index: dict[str, dict[str, int]] = {}
    for code, bars in series_by_code.items():
        series_index[code] = {key: idx for idx, (key, _rank, _pct) in enumerate(bars)}
    output: list[dict[str, Any]] = []
    last_hot_themes: list[dict[str, Any]] = []
    last_frame_index = len(frames) - 1
    # 2026-08-23 前后端分离 G3：全市场量能分位（后端 golden，替代前端当前视图自算分位）。
    # currentFrame 归一化后缺量能字段 → 取最近真实全市场快照帧分位，响应内所有帧共享。
    market_percentiles = _latest_market_percentiles(frames)
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
        market_median, market_sample_count = frame_market_median(frames, index)
        market_median_percentile = frame_market_median_percentile(frame)
        stocks_out: list[dict[str, Any]] = []
        full_tasks: list[tuple[Any, ...]] = []
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
            if not full_history and index != last_frame_index:
                # 首屏全市场场景（无 frame_keys）：历史帧仅输出轻量 meta，
                # 前端 updateLatestAnalysisSeries 只消费 currentRank/currentPercentile；
                # 完整四信号（technical/cycle/risk/resonance/volumePrice）只在最后一帧计算。
                stocks_out.append({
                    "code": code,
                    "analysis": {
                        "meta": {
                            "code": code,
                            "currentRank": ranks[-1] if ranks else 0,
                            "currentPercentile": percentiles[-1] if percentiles else 0.0,
                            "marketPercentiles": market_percentiles,
                        },
                    },
                })
                continue
            full_tasks.append((
                engine.config, stock, frame, ranks, percentiles, regime, hot_themes,
                momentum_v2_ctx, market_median, market_sample_count, market_median_percentile,
            ))

        # 完整四信号计算：单股逐股纯 Python 计算仅 ~1ms/股，全市场 224 股串行 ~0.2s。
        # 进程池并行（spawn 8 worker 重新导入 backend）反而要 8s+，是负优化，统一串行。
        if full_tasks:
            results = [_analyze_one_stock(task) for task in full_tasks]
            for result in results:
                if result:
                    (result["analysis"].setdefault("meta", {}))["marketPercentiles"] = market_percentiles
                    stocks_out.append(result)
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


# 量价修正权重（0.15）：量价分每偏离 50 分 1 分，共振分调整 ±0.15 分（满分 ±7.5）。
# 历史 0.6（±30）/ 0.3（±15）导致共振高分占比过高（约 20%），0.15 下高分（≥80）回落到 10-15%，
# 以排名动量（rawScore）为主、量价仅温和修正。
RESONANCE_VOLUME_PRICE_WEIGHT = 0.15


def _apply_resonance_final(analysis: dict[str, Any], resonance: dict[str, Any], config: RankTrendConfig | None = None) -> None:
    """resonance 下沉：最终信号 = resonance 方向/分数（对齐旧 TS applyResonanceFinals）。

    Python golden 直接输出融合后的 ``decision.final``，前端只读不再覆盖。
    口径：resonance insufficient → hold/0；否则 final = resonance 方向/分数。
    量价修正（阶段 2）：resonance.rawScore 保留原始排名动量分；resonance.score 并入量价协同
    （score + (vpScore−50)×RESONANCE_VOLUME_PRICE_WEIGHT，clamp 0-100）；量价分 ≤40 且 buy → final 降级 hold。
    """
    c = config or RankTrendConfig()
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
        raw = float(score)
        resonance["rawScore"] = raw
        vp_score = ((analysis.get("observation") or {}).get("volumePrice") or {}).get("score")
        adjusted = raw
        if isinstance(vp_score, (int, float)):
            adjusted = max(0.0, min(100.0, raw + (vp_score - 50) * c.resonanceVolumePriceWeight))
        resonance["score"] = adjusted
        final_signal = direction
        if direction == "buy" and isinstance(vp_score, (int, float)) and vp_score <= 40:
            final_signal = "hold"  # 量价证伪（无量虚涨/放量下跌）降级
        decision["final"] = {"signal": final_signal, "confidence": adjusted}


def _percentile(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100


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

    # 方案 6.3：Redis 缓存，TTL 300s（与前端 LRU 一致），键含请求内容与 dataset generation（ingest 后失效）
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
        from backend.services.theme.hotlist_sentiment_service import make_hotlist_sentiment_provider
        engine = RankTrendPythonEngine(
            sentiment_provider=make_hotlist_sentiment_provider(dataset_id, snapshot_type),
        )
        raw_frames, series_by_code = _load_frames_for_analysis(
            repo, dataset_id, snapshot_type, frame_keys, current_frame, codes=codes
        )
        frames_out = _analyze_frames(
            engine, raw_frames, series_by_code, codes, dataset_id=dataset_id,
            full_history=bool(frame_keys),
        )
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