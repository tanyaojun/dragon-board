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

    def _join_display_status_for_frame(
        self, dataset_id: str, frame: dict[str, Any], stocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """golden displayStatus join（就地注入 rows）——与 services 层读口编排同源。

        2026-09-15 修复：本服务此前不 join，盘后任务（run_after_market_once）用它把当日
        EOD 文档覆盖成 fallback 236 口径，读口 ensure_series 见库行不重算，坏文档当天固化。
        延迟 import：services.hotlist_sentiment_compute 模块顶层 import 本模块，反向引用只能在函数内。
        """
        from backend.services.theme.hotlist_sentiment_compute import _join_display_status

        return _join_display_status(self._db, dataset_id, str(frame.get("snapshotId") or ""), stocks)

    @staticmethod
    def _market_data_for_frame(frame: dict[str, Any]) -> dict[str, Any] | None:
        """frame.limitSummary → 全市场证据（面板顶部涨停/炸板/THS 池/封板率快捷指标）。"""
        from backend.services.theme.hotlist_sentiment_compute import _build_market_data_like

        return _build_market_data_like(frame.get("limitSummary"))

    @staticmethod
    def _append_join_warning(doc: dict[str, Any], join_stats: dict[str, Any]) -> None:
        # fail-visible：join 异常/缺失随文档落库（与 _compute_and_persist 同一口径），不静默；
        # 2026-09-24 起进 diagnostics（与业务风险提示 warnings 分离）
        from backend.services.theme.hotlist_sentiment_compute import _append_diagnostic, _join_warning

        _append_diagnostic(doc, _join_warning(join_stats))

    @staticmethod
    def _append_previous_join_issues(doc: dict[str, Any], previous: dict[str, Any]) -> None:
        # fail-visible：昨日/前日 join 异常随文档落库（previous_day_stocks 内统一 join 的产出）；
        # 2026-09-24 起进 diagnostics（与业务风险提示 warnings 分离）
        from backend.services.theme.hotlist_sentiment_compute import _append_diagnostic

        for issue in (previous or {}).get("joinIssues") or []:
            _append_diagnostic(doc, issue)

    @staticmethod
    def _append_evidence_fallback(doc: dict[str, Any], evidence_slot: str) -> None:
        # fail-visible：市场证据回退来源随文档落库，不静默近似；进 diagnostics（业务分离）
        from backend.services.theme.hotlist_sentiment_compute import _append_diagnostic

        _append_diagnostic(doc, f"最新帧 limitSummary 缺失，全市场证据回退自 {evidence_slot} 槽位")

    @staticmethod
    def _invalidate_series_cache(dataset_id: str) -> None:
        """写库后失效 series 读口缓存（fail-safe，与 services 层同口径；异常只记日志）。"""
        from backend.services.theme.hotlist_sentiment_compute import _invalidate_hotlist_sentiment_cache

        _invalidate_hotlist_sentiment_cache(dataset_id)

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
        frame, evidence_frame, evidence_slot = self.latest_frame_with_market_evidence(
            dataset_id, snapshot_type, trading_date
        )
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
        join_stats = self._join_display_status_for_frame(dataset_id, frame, stocks)
        # 日内双轨道收集：shares 趋势点 + 截面阶段序列（因果截断于锚定帧槽位）
        anchored_slot = str(frame.get("slotTime") or "")
        from backend.services.theme.hotlist_sentiment_compute import (
            _collect_intraday_state,
            _stage_confirm_config,
        )

        intraday_state = _collect_intraday_state(
            self._db, dataset_id, snapshot_type, trading_date, before_slot=anchored_slot
        )
        confirm_slots, config_diagnostic = _stage_confirm_config()
        if config_diagnostic:
            intraday_state["diagnostics"].append(config_diagnostic)
        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            market_data=self._market_data_for_frame(evidence_frame) if evidence_frame else None,
            yesterday_trading_date=prior_dates[-1] if prior_dates else None,
            day_before_trading_date=prior_dates[-2] if len(prior_dates) >= 2 else None,
            intraday_history=intraday_state["points"],
            current_slot=str(anchored_slot) if anchored_slot else None,
            stage_history=intraday_state,
            stage_confirm_slots=confirm_slots,
        )
        self._append_join_warning(doc, join_stats)
        self._append_previous_join_issues(doc, previous)
        if evidence_slot:
            # fail-visible：市场证据回退来源随文档落库，不静默近似；进 diagnostics（业务分离）
            self._append_evidence_fallback(doc, evidence_slot)
        if not dry_run:
            # 按 _id 精确写库（Task 1 契约）：存量行 slotTime 为旧值时业务四键 query 会
            # 命中 _id 不同的行导致 MongoDB 拒绝改 _id（DuplicateKeyError）
            self._sentiment.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            self._invalidate_series_cache(dataset_id)
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

    @staticmethod
    def _limit_summary_has_evidence(limit_summary: Any) -> bool:
        if not isinstance(limit_summary, dict):
            return False
        return any(
            isinstance(limit_summary.get(key), dict) and limit_summary.get(key)
            for key in ("continuousBoards", "zhaban", "thsPools", "yesterdayZt")
        )

    def latest_frame_with_market_evidence(
        self, dataset_id: str, snapshot_type: str, trading_date: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """(最新帧, 市场证据帧, 回退槽位)——EOD 市场证据的取帧口径。

        上游涨停/炸板池接口间歇失败时最新帧 limitSummary 全 null（2026-09-14/15 生产形态），
        EOD 文档若直接透传会让面板顶部全市场指标显示 0。收盘后该数据不再变化，回退到
        当日最近有效槽位是合理近似；fail-visible：回退来源由调用方写入 warnings，全日
        无有效帧时证据帧返回 None（缺失可见，不伪造）。
        """
        latest = self.latest_frame(dataset_id, snapshot_type, trading_date)
        if latest is None:
            return None, None, None
        if self._limit_summary_has_evidence(latest.get("limitSummary")):
            return latest, latest, None
        for slot_time in sorted(
            self._slot_times_of_date(dataset_id, snapshot_type, trading_date), reverse=True
        ):
            frame = self.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time)
            if frame and self._limit_summary_has_evidence(frame.get("limitSummary")):
                return latest, frame, str(frame.get("slotTime") or slot_time)
        return latest, None, None

    def previous_day_stocks(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any]:
        # 取前两个交易日的最新 frame 快照行；历史缺失的槽位返回空列表，不伪造数据。
        # 2026-09-24 BUG2 修复：昨日/前日行必须完成 displayStatus join——此前只 join 当日
        # stocks，comparison.yesterday/dayBefore 的 stageCounts 全部 fallback 归 unknown，
        # 前端三日对比 T-1/T-2 冷却/拥挤/风险恒 0。join 在此统一做（4 个调用点共用），
        # 失败 fail-visible：joinIssues 随返回透出（调用方追加进 doc warnings），行保持
        # 无标记由下游 fallback 兜底，不伪造 stage。
        dates = [date for date in self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type) if date < trading_date]
        result: dict[str, Any] = {"yesterday": [], "day_before": [], "joinIssues": []}
        prior_frames: list[tuple[str, str]] = []  # [(role, snapshotId)]
        if dates:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-1])
            if frame:
                result["yesterday"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
                prior_frames.append(("yesterday", str(frame.get("snapshotId") or "")))
        if len(dates) >= 2:
            frame = self.latest_frame(dataset_id, snapshot_type, dates[-2])
            if frame:
                result["day_before"] = self.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
                prior_frames.append(("day_before", str(frame.get("snapshotId") or "")))
        from backend.services.theme.hotlist_sentiment_compute import _join_display_status

        for role, snapshot_id in prior_frames:
            if not snapshot_id or not result[role]:
                continue
            stats = _join_display_status(self._db, dataset_id, snapshot_id, result[role])
            if stats.get("joinFailed"):
                result["joinIssues"].append(f"{role} displayStatus join failed: {stats.get('reason')}")
            elif stats.get("noDisplayStatus"):
                result["joinIssues"].append(
                    f"{role} displayStatus missing on {stats['noDisplayStatus']} stocks（fallback 分类接管）"
                )
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
                join_stats = self._join_display_status_for_frame(dataset_id, frame, stocks)
                # 日内双轨道收集：因果截断于当前槽位
                from backend.services.theme.hotlist_sentiment_compute import (
                    _collect_intraday_state,
                    _stage_confirm_config,
                )

                intraday_state = _collect_intraday_state(
                    self._db, dataset_id, snapshot_type, trading_date, before_slot=str(slot_time)
                )
                confirm_slots, config_diagnostic = _stage_confirm_config()
                if config_diagnostic:
                    intraday_state["diagnostics"].append(config_diagnostic)
                doc = build_hotlist_sentiment_document(
                    dataset_id=dataset_id,
                    snapshot_type=snapshot_type,
                    trading_date=trading_date,
                    frame=frame,
                    stocks=stocks,
                    yesterday_stocks=previous.get("yesterday") or [],
                    day_before_stocks=previous.get("day_before") or [],
                    market_data=self._market_data_for_frame(frame),
                    slot_time=slot_time,
                    intraday_history=intraday_state["points"],
                    current_slot=str(slot_time),
                    stage_history=intraday_state,
                    stage_confirm_slots=confirm_slots,
                )
                self._append_join_warning(doc, join_stats)
                self._append_previous_join_issues(doc, previous)
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
    intraday_history: list[dict[str, Any]] | None = None,
    current_slot: str | None = None,
    stage_history: dict[str, Any] | None = None,
    stage_confirm_slots: int = 2,
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
        intraday_history=intraday_history,
        current_slot=current_slot,
    )
    # 阶段多帧确认（2026-09-24 spec：emotion-stage-multiframe-confirm）：
    # rawStage=本帧截面事实（resolve_stage 输出，永远保留）；stage=确认投影——当日
    # 「严格早于当前槽」的截面序列 + 本帧一次，重放 stage_confirm.confirm_stage 滞回。
    # summary/riskLevel/confidence/signals/warnings 仍是本帧截面证据，不按确认阶段二次计算。
    from backend.analysis.hotlist.stage_confirm import confirm_stage

    raw_stage_value = str(result["stage"])
    history = stage_history or {"rawStagePoints": [], "historyStatus": "empty", "diagnostics": []}
    history_status = str(history.get("historyStatus") or "empty")
    prior_points = list(history.get("rawStagePoints") or [])
    current_stage_slot = str(current_slot or frame.get("slotTime") or slot)
    # historyStatus=unavailable 时历史不可信：只用本帧截面确认（fail-visible 不伪造历史）
    points = [(current_stage_slot, raw_stage_value)] if history_status == "unavailable" else [
        *prior_points, (current_stage_slot, raw_stage_value)
    ]
    confirmed_stage, confirm_state = confirm_stage(points, stage_confirm_slots)
    confirm_state["historyStatus"] = history_status
    return {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}{suffix}",
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "snapshotId": frame.get("snapshotId"),
        "slotTime": slot,
        # 锚定帧的采集槽位（2026-09-24）：slotTime="EOD" 是文档类型哨兵，不含槽位信息；
        # 消费方（前端池对账注脚）需要拿锚定帧槽位与行情列表帧槽位对账，避免拿哨兵值
        # 对比造成的「槽位暂不同步」误报。槽位文档两值相同。
        "anchoredSlotTime": frame.get("slotTime"),
        "timestamp": frame.get("timestamp"),
        "computedAt": int(time.time()),
        "stage": confirmed_stage or raw_stage_value,
        "rawStage": raw_stage_value,
        "stageConfirmState": confirm_state,
        "riskLevel": result["riskLevel"],
        "confidence": result["confidence"],
        "summary": result["summary"],
        "metrics": _metrics_projection(result),
        "turnover": result["turnover"],
        "signals": result["signals"],
        "warnings": result["warnings"],
        # 诊断与业务提示分离（2026-09-24）：join 失败/缺失、市场证据回退来源等数据质量
        # 标注由编排层追加进 diagnostics，不混入业务风险提示 warnings；前端分区块渲染。
        # 初值携带历史收集层的诊断（legacy fallback / 非标准槽 / 读取失败）。
        "diagnostics": list(history.get("diagnostics") or []),
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
        "strongMoneyShare": all_layer["strongMoneyShare"],
        "crowdedShare": all_layer["crowdedShare"],
        "layers": result["metrics"]["layers"],
        "comparison": comparison,
        "limitEvidence": result["metrics"]["limitEvidence"],
        "statusSourceCounts": result["statusSourceCounts"],
        "missingEvidence": result["missingEvidence"],
        "transitionCounts": result["metrics"].get("transitionCounts") or {},
    }


def _business_key(dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, str]:
    return {"datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": trading_date}


def _drop_mongo_id(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_id"}
