from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.analysis.ranktrend import RankTrendPythonEngine, market_regime
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
        frames = [
            frame for frame in frames
            if f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip() in wanted
        ]
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
    output: list[dict[str, Any]] = []
    for frame in frames:
        key = f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip()
        regime = market_regime(frame)
        stocks_out: list[dict[str, Any]] = []
        for signal in by_key.get(key, []):
            code = str(signal.get("code") or "")
            if codes and code not in codes:
                continue
            stocks_out.append({"code": code, "analysis": signal.get("rankTrend")})
        output.append({
            "frameKey": key,
            "regime": regime,
            "totalCount": len(frame.get("stocks", [])),
            "stocks": stocks_out,
        })
    return output


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
