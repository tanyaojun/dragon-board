from __future__ import annotations

import time
from typing import Any

from backend.analysis.hotlist.sentiment import compute_hotlist_sentiment


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
        mode: str = "eod",
    ) -> dict[str, Any]:
        dates = self.trading_dates(
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
            # mode="slots"：按帧遍历逐槽落库（WP1b 历史回填）；默认 "eod" 维持日级终值
            result = (
                self.run_for_date_slots(
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    dry_run=dry_run,
                )
                if mode == "slots"
                else self.run_for_date(
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    dry_run=dry_run,
                )
            )
            results.append(result)
            written += int(result.get("written") or 0)
            skipped += 1 if result.get("skipped") else 0

        return {
            "ok": True,
            "dryRun": dry_run,
            "mode": mode,
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
        dates = self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
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
        frame = self.latest_frame(dataset_id, snapshot_type, trading_date)
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
        stocks = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
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

        previous = self.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        prior_dates = [
            date
            for date in self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
            if date < trading_date
        ]
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            yesterday_trading_date=prior_dates[-1] if prior_dates else None,
            day_before_trading_date=prior_dates[-2] if len(prior_dates) >= 2 else None,
        )
        if not dry_run:
            # 按 _id 精确写库（Task 1 契约）：存量行 slotTime 为旧值时业务四键 query 会
            # 命中 _id 不同的行导致 MongoDB 拒绝改 _id（DuplicateKeyError）
            self._sentiment.replace_one({"_id": doc["_id"]}, doc, upsert=True)
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

    def trading_dates(
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

    def latest_frame(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        return self._frames.find_one(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
            sort=[("timestamp", -1), ("snapshotId", -1)],
        )

    def previous_day_stocks(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, list[dict[str, Any]]]:
        # 取前两个交易日的最新 frame 快照行；历史缺失的槽位返回空列表，不伪造数据。
        dates = [date for date in self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type) if date < trading_date]
        result: dict[str, list[dict[str, Any]]] = {"yesterday": [], "day_before": []}
        if dates:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-1])
            result["yesterday"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
        if len(dates) >= 2:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-2])
            result["day_before"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
        return result

    def stocks_for_frame(self, dataset_id: str, snapshot_id: str) -> list[dict[str, Any]]:
        rows = list(
            self._stock_rows.find({"datasetId": dataset_id, "snapshotId": snapshot_id}).sort(
                [("rank", 1), ("code", 1)]
            )
        )
        return [_drop_mongo_id(row) for row in rows]

    def frame_for_slot(
        self, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str
    ) -> dict[str, Any] | None:
        return self._frames.find_one(
            {
                "datasetId": dataset_id,
                "type": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": slot_time,
            },
            sort=[("timestamp", -1), ("snapshotId", -1)],
        )

    def _slot_times_of_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> list[str]:
        return sorted({
            str(row.get("slotTime") or "")
            for row in self._frames.find(
                {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
                {"slotTime": 1},
            )
            if row.get("slotTime")
        })

    def run_for_date_slots(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """按帧遍历：当日全部槽位逐槽计算情绪并 upsert 槽位文档（WP1b 历史回填模式）。

        单槽失败记 slotErrors 继续（无质量阻断）；前一交易日取数与 EOD 模式同口径。
        全部槽位完成后收尾补写当日 EOD 终值（stale 回退链路依赖每日 EOD 存在）。
        """
        previous = self.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        written = 0
        slot_errors: list[dict[str, Any]] = []
        for slot_time in self._slot_times_of_date(dataset_id, snapshot_type, trading_date):
            try:
                frame = self.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time)
                stocks = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or "")) if frame else []
                if not frame or not stocks:
                    slot_errors.append({"slotTime": slot_time, "reason": "no_frame" if not frame else "empty_stock_rows"})
                    continue
                doc = build_hotlist_sentiment_document(
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    frame=frame,
                    stocks=stocks,
                    yesterday_stocks=previous.get("yesterday") or [],
                    day_before_stocks=previous.get("day_before") or [],
                    slot_time=slot_time,
                )
                if not dry_run:
                    # 按 _id 写库（Task 1 契约）——业务四键 query 在存量行 slotTime 为旧值时
                    # 会命中 _id 不同的行导致 MongoDB 拒绝改 _id
                    self._sentiment.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                written += 0 if dry_run else 1
            except Exception as exc:  # 无质量阻断：单槽失败不中断整日回填
                slot_errors.append({"slotTime": slot_time, "reason": f"error: {exc}"})
        eod_written = False
        if not dry_run:
            # 收尾补写当日 EOD 终值（槽位文档不含 EOD；as-of stale 回退与既有 EOD 消费方依赖它）
            eod_result = self.run_for_date(dataset_id=dataset_id, snapshot_type=snapshot_type, trading_date=trading_date)
            eod_written = bool(eod_result.get("written"))
        return {
            "ok": True,
            "dryRun": dry_run,
            "mode": "slots",
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "written": written,
            "eodWritten": eod_written,
            "slotErrors": slot_errors,
        }


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
    day_before_stocks: list[dict[str, Any]] | None = None,
    market_data: dict[str, Any] | None = None,
    yesterday_trading_date: str | None = None,
    day_before_trading_date: str | None = None,
    slot_time: str | None = None,
) -> dict[str, Any]:
    # 编排纯函数唯一口径（Task 5）：EOD 入库文档 = compute_hotlist_sentiment 结果的库 schema 投影。
    # yesterday/day_before 是 {"tradingDate"?, "rows": [...]} 形态——rows 必须是扁平快照行，
    # 取数路径能拿到交易日时透传，由纯函数编排层回填 comparison.yesterday/dayBefore.tradingDate。
    yesterday_payload: dict[str, Any] = {"rows": list(yesterday_stocks or [])}
    if yesterday_trading_date:
        yesterday_payload["tradingDate"] = yesterday_trading_date
    day_before_payload: dict[str, Any] = {"rows": list(day_before_stocks or [])}
    if day_before_trading_date:
        day_before_payload["tradingDate"] = day_before_trading_date
    # _id/slotTime 契约唯一构造点（计划 B Task 1）：slot_time=None → EOD 哨兵（日级终值，
    # _id 无后缀，存量行形态不变）；传 "HH:MM" → slotTime=slot 且 _id 追加 :{slot} 槽位后缀。
    slot = str(slot_time) if slot_time else "EOD"
    suffix = f":{slot}" if slot_time else ""
    result = compute_hotlist_sentiment(
        stocks,
        yesterday=yesterday_payload,
        day_before=day_before_payload,
        market_data=market_data,
    )
    return {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}{suffix}",
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "snapshotId": frame.get("snapshotId"),
        "slotTime": slot,
        "timestamp": frame.get("timestamp"),
        "computedAt": int(time.time()),
        "stage": result["stage"],
        "riskLevel": result["riskLevel"],
        "confidence": result["confidence"],
        "summary": result["summary"],
        "metrics": _metrics_projection(result),
        "turnover": result["turnover"],
        "signals": result["signals"],
        "warnings": result["warnings"],
    }


def _metrics_projection(result: dict[str, Any]) -> dict[str, Any]:
    # TS persistHotListSentiment（HotListSentimentAnalyzer.ts L1306-1338）的 metrics 映射口径：
    # 现有库文档键 ← 纯函数超集结果；layers/comparison/limitEvidence 等超集键随文档透出。
    all_layer = result["metrics"]["layers"]["all"]
    comparison = result["metrics"]["comparison"]
    intersection = result["metrics"]["limitEvidence"]["intersection"]
    return {
        "poolSize": all_layer["total"],
        "topN": all_layer["topN"],
        "allPoolUpRatio": all_layer["upRatio"],
        "hotTrin": all_layer["hotTrin"],
        "retentionRate1d": comparison["top100RetainRateFromYesterday"],
        "retentionRate2d": comparison["top100RetainRateFromDayBefore"],
        "limitIntersectionRate": intersection["top100LimitUpShare"],
        "newEntryCount": len(result["turnover"]["newEntries"]),
        "eliminatedCount": len(result["turnover"]["eliminated"]),
        "nearLimitUpCount": all_layer["nearLimitUpCount"],
        "highGainCount": all_layer["highGainCount"],
        "riskShare": all_layer["riskShare"],
        "activeOpportunityShare": all_layer["activeOpportunityShare"],
        "strongMoneyShare": all_layer["statusShares"]["强资确认"],
        "crowdedShare": all_layer["crowdedShare"],
        "layers": result["metrics"]["layers"],
        "comparison": comparison,
        "limitEvidence": result["metrics"]["limitEvidence"],
        "statusSourceCounts": result["statusSourceCounts"],
        "missingEvidence": result["missingEvidence"],
    }


def _business_key(dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, str]:
    return {"datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": trading_date}


def _drop_mongo_id(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_id"}
