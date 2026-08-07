"""回填历史快照中的 jumpDirection / jumpConfidence 字段。

从 snapshot_stock_rows 的 compRank 跨帧序列重建百分位时间线，
运行与前端 detectRankJumps 完全等价的跳变检测算法。

macdCross 无法回填——MACD DIF/DEA 原始值从未存入快照，
crossSignal（零轴穿越）是排名趋势动量信号的零轴穿越，
与 MACD 金叉死叉是两个独立的技术指标，无法互相推断。
macdCross 只在新快照（本次代码改动之后采集的）中才有准确值。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _percentile_from_rank(comp_rank: int, total_stocks: int) -> float:
    """将综合排名转为百分位（排名越靠前百分位越高）。"""
    if total_stocks <= 1:
        return 50.0
    return round(max(0.0, min(100.0, 100.0 - ((comp_rank - 1) / (total_stocks - 1)) * 100.0)), 2)


def _detect_jump(percentiles: list[float], delta: float = 15.0) -> dict[str, Any]:
    """Python 等价实现 detectRankJumps，与前端 jumpDetector.ts 行为一致。

    Args:
        percentiles: 按时序排列的百分位序列
        delta: 跳变阈值（百分位变化超过此值视为一次跳变事件）

    Returns:
        dict with direction ('buy'/'sell'/'hold'), confidence (50-95),
        eventCount, surgeCount, collapseCount
    """
    default: dict[str, Any] = {
        "direction": "hold",
        "confidence": 50.0,
        "eventCount": 0,
        "surgeCount": 0,
        "collapseCount": 0,
    }

    if len(percentiles) < 3:
        return default

    ref = percentiles[0]
    events: list[dict[str, Any]] = []

    for i, p in enumerate(percentiles):
        cum_change = p - ref
        if abs(cum_change) > delta:
            events.append({
                "index": i,
                "direction": "surge" if cum_change > 0 else "collapse",
                "magnitude": round(abs(cum_change), 2),
            })
            # 参考点回退到最近 3 点的均值，避免连续小波动误触
            lookback = min(3, i + 1)
            ref = sum(percentiles[max(0, i - lookback + 1) : i + 1]) / lookback

    if not events:
        cum = percentiles[-1] - percentiles[0]
        return {**default, "cumulativeChange": round(cum, 2)}

    latest = events[-1]
    surge_count = sum(1 for e in events if e["direction"] == "surge")
    collapse_count = sum(1 for e in events if e["direction"] == "collapse")
    sustained = surge_count >= 2 or collapse_count >= 2
    direction = "buy" if latest["direction"] == "surge" else "sell"

    mag = latest["magnitude"]
    overshoot = mag - delta
    mag_factor = min(1.0, mag / max(delta * 2, 1))
    overshoot_factor = min(1.0, max(0.0, overshoot) / max(delta, 1))
    sustain_bonus = 0.2 if sustained else 0.0
    raw_conf = 55.0 + 25.0 * mag_factor + 15.0 * overshoot_factor + 20.0 * sustain_bonus
    confidence = round(min(95.0, max(50.0, raw_conf)), 1)

    return {
        "direction": direction,
        "confidence": confidence,
        "eventCount": len(events),
        "surgeCount": surge_count,
        "collapseCount": collapse_count,
    }


def backfill_jump_fields(
    database: Any,
    *,
    dataset_id: str = "dragonboard_live",
    trading_dates: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """主入口：回填 snapshot_stock_rows 的 jumpDirection 和 jumpConfidence。

    对每个交易日内每只股票，从跨帧 compRank 序列重建百分位时间线，
    运行跳变检测后将结果写回 MongoDB。只在字段缺失时才写入，不覆盖已有值。

    Args:
        database: MongoDB database 对象
        dataset_id: 数据集 ID
        trading_dates: 限定交易日列表，为空则扫描全部
        dry_run: True 时只预览不写入

    Returns:
        包含 affectedCount、perDate 明细和 errors 的摘要 dict
    """
    stock_coll = database["snapshot_stock_rows"]
    frame_coll = database["snapshot_frames"]

    query: dict[str, Any] = {"datasetId": dataset_id}
    if trading_dates:
        query["tradingDate"] = {"$in": trading_dates}

    date_pipeline = list(stock_coll.aggregate([
        {"$match": query},
        {"$group": {"_id": "$tradingDate"}},
        {"$sort": {"_id": 1}},
    ]))
    all_dates = [d["_id"] for d in date_pipeline if d["_id"]]

    if not all_dates:
        return {"ok": True, "dryRun": dry_run, "affectedCount": 0, "perDate": {}, "errors": []}

    per_date: dict[str, Any] = {}
    total_affected = 0
    errors: list[dict[str, Any]] = []

    for trading_date in all_dates:
        date_result = _backfill_one_date(
            database, dataset_id, trading_date,
            stock_coll=stock_coll, frame_coll=frame_coll,
            dry_run=dry_run,
        )
        per_date[trading_date] = date_result
        total_affected += date_result.get("affectedCount", 0)
        if date_result.get("errors"):
            errors.extend(date_result["errors"])

    return {
        "ok": len(errors) == 0,
        "dryRun": dry_run,
        "affectedCount": total_affected,
        "datesScanned": len(all_dates),
        "perDate": per_date,
        "errors": errors,
        "generatedAt": datetime.now(UTC).isoformat(),
    }


def _backfill_one_date(
    database: Any,
    dataset_id: str,
    trading_date: str,
    *,
    stock_coll: Any,
    frame_coll: Any,
    dry_run: bool,
) -> dict[str, Any]:
    """回填单个交易日。"""
    # 取该日所有 snapshot 帧，按时序排列
    frames = list(frame_coll.find(
        {"datasetId": dataset_id, "tradingDate": trading_date},
        {"snapshotId": 1, "timestamp": 1, "stockRowCount": 1, "_id": 0},
    ).sort("timestamp", 1))

    if len(frames) < 2:
        return {"affectedCount": 0, "frameCount": len(frames), "reason": "too_few_frames"}

    snapshot_ids = [f["snapshotId"] for f in frames]
    frame_stock_counts = {f["snapshotId"]: f.get("stockRowCount", 100) for f in frames}

    # 获取该日所有股票行
    all_rows = list(stock_coll.find(
        {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}},
    ).sort([("code", 1), ("timestamp", 1)]))

    # 按 stockCode 分组
    code_groups: dict[str, list[dict[str, Any]]] = {}
    for row in all_rows:
        code = row.get("code", "")
        if not code:
            continue
        code_groups.setdefault(code, []).append(row)

    affected = 0
    errors: list[dict[str, Any]] = []

    for code, rows in code_groups.items():
        if len(rows) < 2:
            continue

        # 按 snapshot 时序对齐，缺失帧记为 None
        row_by_snapshot = {r["snapshotId"]: r for r in rows}
        aligned: list[dict[str, Any] | None] = [row_by_snapshot.get(sid) for sid in snapshot_ids]

        # 构建百分位序列
        percentiles: list[float] = []
        valid_indices: list[int] = []

        for i, row in enumerate(aligned):
            if row is None:
                continue
            cr = row.get("compRank") or row.get("rank") or 0
            if cr <= 0:
                continue
            total = frame_stock_counts.get(row.get("snapshotId", ""), 100)
            percentiles.append(_percentile_from_rank(cr, total))
            valid_indices.append(i)

        if len(percentiles) < 3:
            continue

        # 运行跳变检测
        jump = _detect_jump(percentiles)

        # 写回每个有效行（同一股票同一交易日所有帧共享同一跳变结论）
        for idx in valid_indices:
            row = aligned[idx]
            if row is None:
                continue

            # 只在字段缺失时才回填，不覆盖已有值
            current_dir = row.get("jumpDirection")
            current_conf = row.get("jumpConfidence")
            if current_dir is not None and current_dir != "" and current_conf is not None:
                continue

            if dry_run:
                affected += 1
            else:
                try:
                    stock_coll.update_one(
                        {"_id": row["_id"]},
                        {"$set": {
                            "jumpDirection": jump["direction"],
                            "jumpConfidence": jump["confidence"],
                        }},
                    )
                    affected += 1
                except Exception as exc:
                    errors.append({
                        "code": code,
                        "snapshotId": row.get("snapshotId"),
                        "error": str(exc),
                    })

    return {
        "affectedCount": affected,
        "frameCount": len(frames),
        "stockCount": len(code_groups),
        "errors": errors,
    }
