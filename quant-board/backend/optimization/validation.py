from __future__ import annotations

import math
from typing import Any


def split_frames(frames: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
    validation_mode = str(request.get("validation_mode") or request.get("validationMode") or "none")
    validation_ratio = clamp(float(request.get("validation_ratio") or request.get("validationRatio") or 0.3), 0.05, 0.8)
    warmup_bars = max(0, int(request.get("validation_warmup_bars") or request.get("validationWarmupBars") or request.get("warmup_bars") or 40))
    train_range = normalize_range(request.get("train_range") or request.get("trainRange"))
    validation_range = normalize_range(request.get("validation_range") or request.get("validationRange"))
    warnings: list[str] = []
    split_mode = validation_mode

    if train_range or validation_range:
        split_mode = "explicit_range"
        validation_frames = filter_by_range(frames, validation_range) if validation_range else []
        if train_range:
            train_frames = filter_by_range(frames, train_range)
        elif validation_frames:
            validation_start = str(validation_frames[0].get("tradingDate") or "")
            train_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") < validation_start]
        else:
            train_frames = frames
    elif validation_mode in ("auto", "auto_split", "ratio", "chronological"):
        train_frames, validation_frames = auto_split(frames, validation_ratio)
        split_mode = "auto_split"
    else:
        train_frames = frames
        validation_frames = []
        split_mode = "none"

    if not train_frames:
        warnings.append("train 分段为空，已回退为全样本训练。")
        train_frames = frames
    if split_mode != "none" and not validation_frames:
        warnings.append("validation 分段为空，本次优化只能按样本内结果排序。")
    if validation_frames and len(validation_frames) < 10:
        warnings.append(f"validation 只有 {len(validation_frames)} 个快照，样本外指标波动会较大。")

    validation_signal_frames = with_warmup(frames, validation_frames, warmup_bars)
    metadata = {
        "mode": split_mode,
        "validationRatio": validation_ratio if split_mode == "auto_split" else None,
        "validationWarmupBars": warmup_bars,
        "train": frame_range(train_frames),
        "validation": frame_range(validation_frames) if validation_frames else None,
        "validationSignalFrames": frame_range(validation_signal_frames) if validation_signal_frames else None,
        "hasValidation": bool(validation_frames),
    }
    return {
        "train_frames": train_frames,
        "train_signal_frames": train_frames,
        "validation_frames": validation_frames,
        "validation_signal_frames": validation_signal_frames,
        "metadata": metadata,
        "warnings": warnings,
    }


def auto_split(frames: list[dict[str, Any]], validation_ratio: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dates = sorted({str(frame.get("tradingDate") or "") for frame in frames if frame.get("tradingDate")})
    if len(dates) >= 3:
        validation_date_count = max(1, min(len(dates) - 1, math.ceil(len(dates) * validation_ratio)))
        validation_dates = set(dates[-validation_date_count:])
        train_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") not in validation_dates]
        validation_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") in validation_dates]
        return train_frames, validation_frames
    split_index = max(1, min(len(frames) - 1, math.ceil(len(frames) * (1 - validation_ratio)))) if len(frames) > 1 else len(frames)
    return frames[:split_index], frames[split_index:]


def with_warmup(frames: list[dict[str, Any]], phase_frames: list[dict[str, Any]], warmup_bars: int) -> list[dict[str, Any]]:
    if not phase_frames:
        return []
    first_id = str(phase_frames[0].get("snapshotId"))
    first_index = next((idx for idx, frame in enumerate(frames) if str(frame.get("snapshotId")) == first_id), 0)
    start = max(0, first_index - warmup_bars)
    return frames[start:first_index] + phase_frames


def normalize_range(value: Any) -> tuple[str | None, str | None] | None:
    if not value:
        return None
    if isinstance(value, dict):
        start = value.get("start") or value.get("startDate") or value.get("from")
        end = value.get("end") or value.get("endDate") or value.get("to")
        return (str(start) if start else None, str(end) if end else None)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (str(value[0]) if value[0] else None, str(value[1]) if value[1] else None)
    return None


def filter_by_range(frames: list[dict[str, Any]], value: tuple[str | None, str | None]) -> list[dict[str, Any]]:
    start, end = value
    result = frames
    if start:
        result = [frame for frame in result if str(frame.get("tradingDate") or "") >= start]
    if end:
        result = [frame for frame in result if str(frame.get("tradingDate") or "") <= end]
    return result


def frame_range(frames: list[dict[str, Any]]) -> dict[str, Any]:
    if not frames:
        return {"snapshotCount": 0, "startDate": None, "endDate": None, "startSnapshotId": None, "endSnapshotId": None}
    return {
        "snapshotCount": len(frames),
        "startDate": frames[0].get("tradingDate"),
        "endDate": frames[-1].get("tradingDate"),
        "startSnapshotId": frames[0].get("snapshotId"),
        "endSnapshotId": frames[-1].get("snapshotId"),
    }


def clamp(value: float, lower: float, upper: float) -> float:
    if not math.isfinite(value):
        return lower
    return min(upper, max(lower, value))
