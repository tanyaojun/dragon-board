from __future__ import annotations

import time
from typing import Any

HIGH_POSITION_RANK_CUTOFF = 30


class HotListSentimentBackfillService:
    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db
        self._frames = mongo_db["snapshot_frames"]
        self._stock_rows = mongo_db["snapshot_stock_rows"]
        self._sentiment = mongo_db["hotlist_sentiment"]

    def backfill(
        self,
        *,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        dates = self._trading_dates(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            start_date=start_date,
            end_date=end_date,
        )
        if limit and limit > 0:
            dates = dates[:limit]

        results: list[dict[str, Any]] = []
        written = 0
        skipped = 0
        for trading_date in dates:
            result = self.run_for_date(
                dataset_id=dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                dry_run=dry_run,
            )
            results.append(result)
            written += int(result.get("written") or 0)
            skipped += 1 if result.get("skipped") else 0

        return {
            "ok": True,
            "dryRun": dry_run,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "planned": len(dates),
            "written": written,
            "skipped": skipped,
            "results": results,
        }

    def run_for_latest_day(
        self,
        *,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        dates = self._trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not dates:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no_snapshot_trading_date",
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "written": 0,
            }
        return self.run_for_date(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=dates[-1],
            dry_run=dry_run,
        )

    def run_for_date(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        frame = self._latest_frame(dataset_id, snapshot_type, trading_date)
        if not frame:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no_snapshot_frame",
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "written": 0,
            }
        stocks = self._stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
        if not stocks:
            return {
                "ok": True,
                "skipped": True,
                "reason": "empty_stock_rows",
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "snapshotId": frame.get("snapshotId"),
                "written": 0,
            }

        yesterday_stocks = self._previous_day_stocks(dataset_id, snapshot_type, trading_date)
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=yesterday_stocks,
        )
        if not dry_run:
            self._sentiment.replace_one(_business_key(dataset_id, snapshot_type, trading_date), doc, upsert=True)
        return {
            "ok": True,
            "dryRun": dry_run,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "snapshotId": frame.get("snapshotId"),
            "stage": doc["stage"],
            "riskLevel": doc["riskLevel"],
            "poolSize": doc["metrics"]["poolSize"],
            "written": 0 if dry_run else 1,
        }

    def _trading_dates(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[str]:
        query: dict[str, Any] = {"datasetId": dataset_id, "type": snapshot_type}
        if start_date or end_date:
            date_query: dict[str, str] = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["tradingDate"] = date_query
        dates = {
            str(row.get("tradingDate") or "")
            for row in self._frames.find(query, {"tradingDate": 1})
            if row.get("tradingDate")
        }
        return sorted(dates)

    def _latest_frame(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        return self._frames.find_one(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
            sort=[("timestamp", -1), ("snapshotId", -1)],
        )

    def _previous_day_stocks(self, dataset_id: str, snapshot_type: str, trading_date: str) -> list[dict[str, Any]]:
        dates = [date for date in self._trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type) if date < trading_date]
        if not dates:
            return []
        frame = self._latest_frame(dataset_id, snapshot_type, dates[-1])
        return self._stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []

    def _stocks_for_frame(self, dataset_id: str, snapshot_id: str) -> list[dict[str, Any]]:
        rows = list(
            self._stock_rows.find({"datasetId": dataset_id, "snapshotId": snapshot_id}).sort(
                [("rank", 1), ("code", 1)]
            )
        )
        return [_drop_mongo_id(row) for row in rows]


def run_hotlist_sentiment_for_latest_day(
    mongo_db: Any,
    *,
    dataset_id: str,
    snapshot_type: str = "half_hour",
    dry_run: bool = False,
) -> dict[str, Any]:
    return HotListSentimentBackfillService(mongo_db).run_for_latest_day(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        dry_run=dry_run,
    )


def build_hotlist_sentiment_document(
    *,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    frame: dict[str, Any],
    stocks: list[dict[str, Any]],
    yesterday_stocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sorted_stocks = _sort_by_rank(stocks)
    previous_stocks = _sort_by_rank(yesterday_stocks or [])
    turnover = _compute_turnover(sorted_stocks, previous_stocks)
    metrics = _compute_metrics(sorted_stocks, previous_stocks, turnover)
    stage, risk_level, signals, warnings = _resolve_stage(metrics)
    return {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}",
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "snapshotId": frame.get("snapshotId"),
        "slotTime": frame.get("slotTime"),
        "timestamp": frame.get("timestamp"),
        "computedAt": int(time.time()),
        "stage": stage,
        "riskLevel": risk_level,
        "confidence": _confidence(stage, signals, warnings),
        "summary": f"热榜情绪处于{stage}阶段，全池上涨比例 {metrics['allPoolUpRatio']:.1%}",
        "metrics": metrics,
        "turnover": turnover,
        "signals": signals,
        "warnings": warnings,
    }


def _business_key(dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, str]:
    return {"datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": trading_date}


def _compute_metrics(
    stocks: list[dict[str, Any]],
    yesterday_stocks: list[dict[str, Any]],
    turnover: dict[str, Any],
) -> dict[str, Any]:
    pool_size = len(stocks)
    up_count = sum(1 for stock in stocks if _num(stock.get("change")) > 0)
    near_limit_count = sum(1 for stock in stocks if _num(stock.get("change")) >= 9.5)
    high_gain_count = sum(1 for stock in stocks if _num(stock.get("change")) >= 5)
    labels = [_fallback_status_label(stock) for stock in stocks]
    risk_count = sum(1 for label in labels if label in {"资金背离", "转弱预警"})
    strong_money_count = sum(1 for label in labels if label == "强资确认")
    active_count = sum(1 for label in labels if label in {"主升确认", "点火观察", "强资确认"})
    crowded_count = sum(1 for label in labels if label == "高位拥挤")
    retention = turnover["retainedFromYesterday"] / len(yesterday_stocks) if yesterday_stocks else 0
    return {
        "poolSize": pool_size,
        "allPoolUpRatio": up_count / pool_size if pool_size else 0,
        "hotTrin": _hot_trin(stocks),
        "retentionRate1d": retention,
        "retentionRate2d": 0,
        "limitIntersectionRate": near_limit_count / pool_size if pool_size else 0,
        "newEntryCount": len(turnover["newEntries"]),
        "eliminatedCount": len(turnover["eliminated"]),
        "nearLimitUpCount": near_limit_count,
        "highGainCount": high_gain_count,
        "riskShare": risk_count / pool_size if pool_size else 0,
        "activeOpportunityShare": active_count / pool_size if pool_size else 0,
        "strongMoneyShare": strong_money_count / pool_size if pool_size else 0,
        "crowdedShare": crowded_count / pool_size if pool_size else 0,
    }


def _resolve_stage(metrics: dict[str, Any]) -> tuple[str, str, list[str], list[str]]:
    up_ratio = float(metrics["allPoolUpRatio"])
    hot_trin = metrics["hotTrin"]
    risk_share = float(metrics["riskShare"])
    active_share = float(metrics["activeOpportunityShare"])
    near_limit = int(metrics["nearLimitUpCount"])
    signals: list[str] = []
    warnings: list[str] = []

    if near_limit >= 8:
        signals.append(f"全池近涨停 {near_limit} 只")
    if active_share >= 0.18:
        signals.append(f"强势机会扩散，占比 {active_share:.1%}")
    if hot_trin is not None and hot_trin < 1:
        signals.append(f"热榜 TRIN {hot_trin:.2f}，上涨股成交承接占优")
    if risk_share >= 0.2:
        warnings.append(f"风险压力 {risk_share:.1%}")
    if up_ratio <= 0.42:
        warnings.append(f"热榜上涨宽度偏弱，全池上涨 {up_ratio:.1%}")

    risk_level = "高" if risk_share >= 0.35 or up_ratio <= 0.35 else "中" if risk_share >= 0.2 else "低"
    money_not_weak = hot_trin is None or hot_trin <= 1.15
    if risk_level == "高" and up_ratio > 0.42 and money_not_weak:
        warnings.append("风险等级高，但上涨和成交承接尚未破坏，按阶段主方向处理")
    if risk_level == "高" and up_ratio < 0.52 and not money_not_weak:
        return "退潮", risk_level, signals, warnings or ["风险压力偏高，先按防守阶段处理"]
    if up_ratio >= 0.55 and money_not_weak and near_limit >= 8 and active_share >= 0.18:
        return "高潮", risk_level, signals or ["前排高涨幅与高位拥挤同时增加"], warnings
    if up_ratio >= 0.48 and money_not_weak and active_share >= 0.12:
        return "发酵", risk_level, signals or ["强资确认与点火观察形成有效扩散"], warnings
    if up_ratio >= 0.42 and money_not_weak:
        return "启动", risk_level, signals or ["热榜新增和机会状态开始改善"], warnings
    if risk_level == "高":
        return "退潮", risk_level, signals, warnings or ["热榜机会状态转弱"]
    return "冰点", risk_level, signals or ["热榜机会状态尚未形成有效扩散"], warnings


def _compute_turnover(stocks: list[dict[str, Any]], yesterday_stocks: list[dict[str, Any]]) -> dict[str, Any]:
    today_codes = {_code(stock) for stock in stocks if _code(stock)}
    yesterday_codes = {_code(stock) for stock in yesterday_stocks if _code(stock)}
    new_entries = [stock for stock in stocks if _code(stock) not in yesterday_codes]
    eliminated = [stock for stock in yesterday_stocks if _code(stock) not in today_codes]
    return {
        "previousPoolSize": len(yesterday_stocks),
        "currentPoolSize": len(stocks),
        "retainedFromYesterday": sum(1 for stock in stocks if _code(stock) in yesterday_codes),
        "newEntries": [_code(stock) for stock in new_entries if _code(stock)],
        "eliminated": [_code(stock) for stock in eliminated if _code(stock)],
        "newEntryDetails": [
            {
                "code": _code(stock),
                "name": str(stock.get("name") or ""),
                "rank": _rank(stock, index),
                "changePct": _num(stock.get("change")),
                "entryReason": _entry_reason(stock),
            }
            for index, stock in enumerate(new_entries)
        ],
        "eliminatedDetails": [
            {
                "code": _code(stock),
                "name": str(stock.get("name") or ""),
                "rank": _rank(stock, index),
                "changePct": _num(stock.get("change")),
                "exitReason": _exit_reason(stock),
            }
            for index, stock in enumerate(eliminated)
        ],
    }


def _hot_trin(stocks: list[dict[str, Any]]) -> float | None:
    up_amount = sum(_turnover(stock) for stock in stocks if _num(stock.get("change")) > 0)
    down_amount = sum(_turnover(stock) for stock in stocks if _num(stock.get("change")) < 0)
    up_count = sum(1 for stock in stocks if _num(stock.get("change")) > 0)
    down_count = sum(1 for stock in stocks if _num(stock.get("change")) < 0)
    if down_count == 0 or down_amount <= 0:
        return None
    volume_ratio = up_amount / down_amount if down_amount else 0
    return round((up_count / down_count) / volume_ratio, 4) if volume_ratio > 0 else None


def _turnover(stock: dict[str, Any]) -> float:
    return abs(_num(stock.get("turnover") or stock.get("amount") or stock.get("zlje") or 0))


def _entry_reason(stock: dict[str, Any]) -> str:
    if _num(stock.get("change")) >= 9.8:
        return "limit_up"
    if _num(stock.get("zlje")) > 0 or _num(stock.get("zljzb")) > 0:
        return "strong_money"
    if _num(stock.get("volumeRatio") or stock.get("volume_ratio")) > 2:
        return "new_high_volume"
    return "rank_surge"


def _exit_reason(stock: dict[str, Any]) -> str:
    change = _num(stock.get("change"))
    if change <= -9.8:
        return "limit_down"
    if change < -3:
        return "weakening"
    return "rank_out_of_range"


def _fallback_status_label(stock: dict[str, Any]) -> str:
    change = _num(stock.get("change"))
    rank = _rank(stock, 999)
    zlje = _num(stock.get("zlje"))
    zljzb = _num(stock.get("zljzb"))
    cddje = _num(stock.get("cddje"))
    cddjzb = _num(stock.get("cddjzb"))
    volume_ratio = _num(stock.get("volumeRatio") or stock.get("volume_ratio"))
    turnover_rate = _num(stock.get("turnoverRate") or stock.get("turnover_rate"))

    strong_money = zlje > 0 and zljzb >= 8 and (cddje > 0 or cddjzb >= 3)
    money_weak = zlje < 0 or zljzb <= -8 or (cddje < 0 and cddjzb <= -3)
    high_position = change >= 8 or rank <= HIGH_POSITION_RANK_CUTOFF
    overheated = high_position and (volume_ratio >= 1.8 or turnover_rate >= 10)

    if money_weak and (rank <= 80 or change > 0):
        return "资金背离"
    if overheated:
        return "高位拥挤"
    if strong_money:
        return "强资确认"
    if change >= 3 or rank <= 100:
        return "新入观察"
    if change <= -3:
        return "转弱预警"
    return "样本不足"


def _confidence(stage: str, signals: list[str], warnings: list[str]) -> int:
    base = {"冰点": 50, "启动": 58, "发酵": 68, "高潮": 76, "退潮": 70}.get(stage, 58)
    return max(45, min(90, base + min(18, len(signals) * 5) - min(12, len(warnings) * 3)))


def _sort_by_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(stocks, key=lambda stock: (_rank(stock, 999999), _code(stock)))


def _rank(stock: dict[str, Any], fallback_index: int) -> int:
    rank = int(_num(stock.get("rank") or stock.get("compRank") or stock.get("rankValue")))
    return rank if rank > 0 else fallback_index + 1


def _code(stock: dict[str, Any]) -> str:
    return str(stock.get("code") or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _drop_mongo_id(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_id"}
