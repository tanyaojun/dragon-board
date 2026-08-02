from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend import RankTrendPythonEngine, analyze_rank_resonance, market_regime
from backend.data import repository_factory

router = APIRouter(tags=["ranktrend-analyze"])

SUPPORTED_SNAPSHOT_TYPES = {"quarter_hour", "half_hour", "hourly", "daily"}


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
) -> list[dict[str, Any]]:
    bundles = repo.load_frame_bundles(
        dataset_id,
        snapshot_type=snapshot_type,
        sort="asc",
        projection="ranktrend",
        limit=200,
    )
    frames = [_to_engine_frame(b) for b in bundles]
    if current_frame:
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
        # 保留请求帧及其前 3 帧作为横截面基准窗口
        keys = [f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip() for frame in frames]
        keep: set[str] = set()
        for index, key in enumerate(keys):
            if key in wanted:
                keep.update(keys[max(0, index - 3):index + 1])
        frames = [
            frame for frame in frames
            if f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip() in keep
        ]
    else:
        # 实时/最新：只保留最后 4 帧（当前帧 + 前 3 帧窗口），避免全量分析超时
        frames = frames[-4:]
    if not frames:
        raise HTTPException(status_code=503, detail="no frames available for analyze")
    return frames


def _analyze_frames(
    engine: RankTrendPythonEngine,
    frames: list[dict[str, Any]],
    codes: list[str],
) -> list[dict[str, Any]]:
    signals_by_frame = engine.replay(frames, warmup_count=1)
    by_key: dict[str, list[dict[str, Any]]] = {}
    for signal in signals_by_frame:
        key = f"{signal.get('tradingDate')} {signal.get('slotTime')}".strip()
        by_key.setdefault(key, []).append(signal)
    # 每股跨帧百分位序列（用于 resonance 横截面与个股序列）
    series_by_code: dict[str, list[float]] = {}
    for frame in frames:
        total = len(frame.get("stocks", []))
        for stock in frame.get("stocks", []):
            code = str(stock.get("code") or "")
            rank = float(stock.get("rank") or 0)
            if code and rank > 0 and total > 0:
                series_by_code.setdefault(code, []).append(_percentile(rank, total))
    output: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        key = f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip()
        regime = market_regime(frame)
        market_median, market_sample_count = _frame_market_median(frames, index)
        stocks_out: list[dict[str, Any]] = []
        for signal in by_key.get(key, []):
            code = str(signal.get("code") or "")
            if codes and code not in codes:
                continue
            analysis = signal.get("rankTrend") or {}
            percentiles = series_by_code.get(code, [])
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
    """当前帧与前 3 个市场帧公共股票的短周期百分位变化中位数（横截面基准）。"""
    start = max(0, index - 3)
    window = frames[start:index + 1]
    if len(window) < 4:
        return None, 0
    current = {str(s.get("code")): s for s in window[-1].get("stocks", []) if s.get("rank", 0) > 0}
    first = {str(s.get("code")): s for s in window[0].get("stocks", []) if s.get("rank", 0) > 0}
    changes: list[float] = []
    for code, stock in current.items():
        first_stock = first.get(code)
        if not first_stock:
            continue
        current_pct = _percentile(float(stock.get("rank") or 0), len(window[-1].get("stocks", [])))
        first_pct = _percentile(float(first_stock.get("rank") or 0), len(window[0].get("stocks", [])))
        changes.append(current_pct - first_pct)
    if len(changes) < 20:
        return None, len(changes)
    return _median(changes), len(changes)


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
    repo = repository_factory.create_repository(db, enable_backup=False)
    engine = RankTrendPythonEngine()
    raw_frames = _load_frames_for_analysis(repo, dataset_id, snapshot_type, frame_keys, current_frame)
    frames_out = _analyze_frames(engine, raw_frames, codes)
    return {"ok": True, "frames": frames_out, "source": "py_golden", "issues": []}
