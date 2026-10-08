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
    def _append_zhaban_input_missing(doc: dict[str, Any], stocks: list[dict[str, Any]]) -> None:
        # fail-visible（2026-09-25 review）：炸板价格推导依赖行情行 high/limitUpPrice
        # （bridge 行情透传，bridge 离线时缺失），输入缺失按未炸计回 0——缺失行数随文档
        # 落库，让「真无炸板」与「输入缺失回 0」可分辨；进 diagnostics（业务分离）
        from backend.analysis.hotlist.sentiment import count_zhaban_input_missing
        from backend.services.theme.hotlist_sentiment_compute import _append_diagnostic

        missing = count_zhaban_input_missing(stocks)
        if missing:
            _append_diagnostic(doc, f"炸板推导输入缺失 {missing} 行（无炸板标记且无 high/limitUpPrice，按未炸计）")

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
        # 评分 evidence parts 取数（延迟 import：复用 jev 服务层模式，口径与 jev 轨道同源）；
        # 读失败降级为空 + 结构化诊断（部分来源失败不阻断写库，fail-visible）
        from backend.services.jev.jev_sentiment_compute import (
            _load_analysis_by_code,
            _yesterday_total_amounts_by_slot,
        )

        try:
            emotion_analysis = _load_analysis_by_code(
                self._db, dataset_id, str(frame.get("snapshotId") or ""))
            emotion_amounts = _yesterday_total_amounts_by_slot(
                self._db, dataset_id, snapshot_type, trading_date)
            emotion_parts_error = None
        except Exception as exc:
            emotion_analysis, emotion_amounts = {}, None
            emotion_parts_error = f"emotion_evidence_load_failed:{type(exc).__name__}:{exc}"

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
            # 路线 B（T3 写口接线）：昨日行复用 previous_day_stocks（已含 displayStatus join）
            yesterday_rows=previous.get("yesterday") or [],
            analysis_by_code=emotion_analysis,
            yesterday_amounts=emotion_amounts,
        )
        if emotion_parts_error:
            doc.setdefault("diagnostics", []).append(emotion_parts_error)
        self._append_join_warning(doc, join_stats)
        self._append_previous_join_issues(doc, previous)
        self._append_zhaban_input_missing(doc, stocks)
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

    def limit_stocks_detail(self, dataset_id: str, snapshot_type: str) -> dict[str, Any]:
        """涨停池成分股明细（市场概览三容器 → 明细面板数据源；市场名单由路由层异步补充）。

        口径唯一来源 = analysis.hotlist.sentiment 纯函数：涨停判定 _has_limit_up_evidence /
        get_stock_limit_signal，与 limitEvidence 聚合完全同源（生产文档 top_n=None → 全池口径，
        此处同样不截断，明细行数可与聚合数对账）。fail-visible：昨日行缺失 / join 异常不阻断，
        各自结构化标注进 diagnostics，返回可用部分，不伪造名单。
        """
        empty: dict[str, Any] = {
            "ok": False, "degraded": True, "reason": "", "diagnostics": [],
            "tradingDate": "", "prevTradingDate": "",
            "pool": {"rows": []}, "yesterday": {"rows": []},
        }
        dates = self.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not dates:
            return {**empty, "reason": "no trading dates in dataset"}
        trading_date = dates[-1]
        prev_trading_date = dates[-2] if len(dates) >= 2 else ""
        frame = self.latest_frame(dataset_id, snapshot_type, trading_date)
        if frame is None:
            return {
                **empty,
                "reason": f"no snapshot frame on {trading_date}",
                "tradingDate": trading_date,
                "prevTradingDate": prev_trading_date,
            }
        snapshot_id = str(frame.get("snapshotId") or "")
        today_rows = self.stocks_for_frame(dataset_id, snapshot_id)
        from backend.services.theme.hotlist_sentiment_compute import _join_display_status

        join_stats = _join_display_status(self._db, dataset_id, snapshot_id, today_rows)
        diagnostics: list[str] = []
        if join_stats.get("joinFailed"):
            diagnostics.append(f"displayStatus join failed: {join_stats.get('reason')}")
        elif join_stats.get("noDisplayStatus"):
            diagnostics.append(f"displayStatus missing on {join_stats['noDisplayStatus']} stocks（fallback 分类接管）")

        from backend.analysis.hotlist.sentiment import (
            _has_limit_up_evidence,
            _has_stock_zhaban_signal,
            get_rank,
            get_stock_limit_signal,
            is_risk_row,
            normalize_code,
            sort_rows,
            to_number,
        )

        today_sorted = sort_rows(today_rows)
        today_by_code = {
            normalize_code(row.get("code")): row for row in today_sorted if normalize_code(row.get("code"))
        }

        # ① 热榜池涨停名单：当日全池行按涨停证据口径过滤（与 top100LimitUpCount 同源同径）
        pool_rows = []
        for row in today_sorted:
            code = normalize_code(row.get("code"))
            if not code or not _has_limit_up_evidence(row):
                continue
            signal = get_stock_limit_signal(row)
            pool_rows.append(
                {
                    "code": code,
                    "name": str(row.get("name") or "").strip(),
                    "rank": get_rank(row, len(pool_rows)),
                    "change": to_number(row.get("change")),
                    "boardHeight": signal["boardHeight"],
                    # 展示徽章口径：未封板但触及近涨停阈值（isAlmostLimitUp 单判据）；
                    # 与聚合 top100NearLimitUpCount（含涨停行）对账时注意口径差
                    "nearLimitUp": bool(signal["isAlmostLimitUp"] and not signal["isLimitUp"]),
                    "zhaban": _has_stock_zhaban_signal(row),
                    "mainNet": to_number(row.get("zlje")),
                    "firstLimitUpTime": str(
                        row.get("firstZtTime") or row.get("first_limit_up_time") or ""
                    ).strip(),
                    "lastLimitUpTime": str(
                        row.get("lastZtTime") or row.get("last_limit_up_time") or ""
                    ).strip(),
                    "statusLabel": str(row.get("displayStatusLabel") or "").strip(),
                }
            )

        # ② 昨日热榜涨停名单：昨日全池涨停行 × 今日表现（判据同 build_yesterday_hot_limit_evidence）
        previous = self.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        for issue in (previous or {}).get("joinIssues") or []:
            diagnostics.append(str(issue))
        yesterday_sorted = sort_rows((previous or {}).get("yesterday") or [])
        yesterday_rows = []
        for row in yesterday_sorted:
            code = normalize_code(row.get("code"))
            if not code or not _has_limit_up_evidence(row):
                continue
            signal = get_stock_limit_signal(row)
            today = today_by_code.get(code)
            today_change = to_number(today.get("change")) if today else None
            today_signal = get_stock_limit_signal(today) if today else None
            is_risk = bool(today and is_risk_row(today))
            matched = today is not None
            positive = matched and today_change is not None and today_change > 0
            weakened = (not matched) or (today_change is not None and today_change <= -2) or is_risk
            failed_or_weak = (
                (not matched)
                or (today_change is not None and today_change <= 0)
                or is_risk
                or bool(today_signal and not today_signal["isAlmostLimitUp"])
            )
            yesterday_rows.append(
                {
                    "code": code,
                    "name": str(row.get("name") or "").strip(),
                    "rank": get_rank(row, len(yesterday_rows)),
                    "yesterdayChange": to_number(row.get("change")),
                    "boardHeight": signal["boardHeight"],
                    "matched": matched,
                    "todayChange": today_change,
                    "todayRank": get_rank(today, 0) if today else 0,
                    "retained": matched and code in today_by_code,
                    "positive": positive,
                    "weakened": weakened,
                    "failedOrWeak": failed_or_weak,
                }
            )

        return {
            "ok": True,
            "degraded": False,
            "reason": None,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "prevTradingDate": prev_trading_date,
            "snapshotId": snapshot_id,
            "diagnostics": diagnostics,
            "pool": {"rows": pool_rows},
            "yesterday": {"rows": yesterday_rows},
        }

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
        # 评分 evidence parts：昨日同期总额与当日槽无关，循环外取一次（每日 1 次，避免逐槽重复扫描）
        from backend.services.jev.jev_sentiment_compute import _yesterday_total_amounts_by_slot

        try:
            emotion_amounts = _yesterday_total_amounts_by_slot(
                self._db, dataset_id, snapshot_type, trading_date)
            emotion_amounts_error = None
        except Exception as exc:
            emotion_amounts = None
            emotion_amounts_error = f"emotion_evidence_load_failed:yesterday_amounts:{type(exc).__name__}:{exc}"
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
                # 评分 analysis 取数（延迟 import：复用 jev 服务层模式，口径同源）；
                # 读失败降级为空 + 结构化诊断（部分来源失败不阻断写库，fail-visible）
                from backend.services.jev.jev_sentiment_compute import _load_analysis_by_code

                try:
                    emotion_analysis = _load_analysis_by_code(
                        self._db, dataset_id, str(frame.get("snapshotId") or ""))
                    emotion_analysis_error = None
                except Exception as exc:
                    emotion_analysis = {}
                    emotion_analysis_error = f"emotion_evidence_load_failed:analysis:{type(exc).__name__}:{exc}"

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
                    # 路线 B（T3 写口接线）：评分 evidence parts（与 run_for_date 同口径）
                    yesterday_rows=previous.get("yesterday") or [],
                    analysis_by_code=emotion_analysis,
                    yesterday_amounts=emotion_amounts,
                )
                for parts_error in (emotion_amounts_error, emotion_analysis_error):
                    if parts_error:
                        doc.setdefault("diagnostics", []).append(parts_error)
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
    yesterday_rows: list[dict[str, Any]] | None = None,
    analysis_by_code: dict[str, Any] | None = None,
    yesterday_amounts: dict[str, float] | None = None,
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
    # ── 路线 B（emotion-score-design v3）：档位主定义切换为评分驱动 ──
    # 评分消费 collect_slot_evidence 聚合证据（与 jev 轨道同源，零规则档位依赖）；
    # evidence parts 缺失时对应维 skip + 权重归一化（fail-visible），不阻断档位链。
    # signals/warnings/metrics/riskLevel 仍来自级联截面计算（证据层不动，审计 N1）。
    from backend.analysis.hotlist.emotion_score import compute_emotion_score, map_stage
    from backend.analysis.hotlist.jev_state import collect_slot_evidence

    legacy_cascade_stage = str(result["stage"])
    evidence_slot = str(current_slot or frame.get("slotTime") or slot)
    evidence = collect_slot_evidence(
        frame=frame,
        rows=list(stocks),
        yesterday_rows=list(yesterday_rows or []),
        analysis_by_code=analysis_by_code if isinstance(analysis_by_code, dict) else {},
        slot_time=evidence_slot,
        yesterday_same_slot_total_amount=(yesterday_amounts or {}).get(evidence_slot),
    )
    emotion = compute_emotion_score(evidence)
    score_value = emotion["score"]
    # slope（审计 B2）：与当日严格早于本槽的最后一个有效 emotionScore.score 之差；
    # prev 缺失（当日首槽/旧文档无 emotionScore）→ None → 低分判冰点。
    score_points = list((stage_history or {}).get("scorePoints") or [])
    prev_score = score_points[-1][1] if score_points else None
    slope = round(score_value - prev_score, 2) if (score_value is not None and prev_score is not None) else None
    # pathDiag（2026-10-05 方向一；B+C 预登记 2026-10-08 前移至档位映射前）：日内路径诊断
    # ——极值+自高点回撤+自低点反弹。B+C 后 drawdownFromHigh 在 EOD 档进入 map_stage 方向判别
    # （仅 EOD；盘中槽 pathDiag 仍为纯诊断字段，不进档位/regime/门控链）。
    path_diag = None
    if score_value is not None:
        series = [(str(t), float(v)) for t, v in score_points if isinstance(v, (int, float))]
        series.append((evidence_slot, float(score_value)))
        hi_t, hi_v = max(series, key=lambda x: x[1])
        lo_t, lo_v = min(series, key=lambda x: x[1])
        path_diag = {
            "dayHigh": {"slotTime": hi_t, "score": round(hi_v, 1)},
            "dayLow": {"slotTime": lo_t, "score": round(lo_v, 1)},
            "drawdownFromHigh": round(float(score_value) - hi_v, 1),
            "bounceFromLow": round(float(score_value) - lo_v, 1),
            "points": len(series),
        }
    # B+C：仅 EOD（slot_time 哨兵为空 → 日级终值）传 path；盘中槽 path=None 保持末步差分
    # （响应性 + 变更面零）；dd 缺失时 map_stage 内部退化现行规则（fail-visible）。
    stage_path = ({"dd": path_diag["drawdownFromHigh"]}
                  if (not slot_time and path_diag is not None) else None)
    raw_stage_value = map_stage(score_value, slope, path=stage_path) if score_value is not None else None
    # activeDims（2026-10-05 方向二报告 §六#8）：有效维基数戳，跨日可比性按此字段分段
    # （历史文档缺该键=旧代，fail-visible）。2026-10-08 永久退役第八维（研究轮出口 b，
    # amountvs-same-recalibration-study-20261008.md）后总维数=7：前史=10-08 裁决 A-① 临时冻结
    # （audit P1-1，当日曾实证自动激活 44.8→41.6），同日研究轮确认稀释结构性后裁决退役。
    active_dims = 7 - len(emotion.get("skippedDims") or [])
    emotion_doc = {
        "score": score_value,
        "dims": emotion["dims"],
        "skippedDims": emotion["skippedDims"],
        "activeDims": active_dims,
        "pathDiag": path_diag,
        # 与 rawStage 同值（审计 S10：本帧映射档位含方向修正，防两值不一致）
        "stageCandidate": raw_stage_value,
        "slope": slope,
        "version": "score-v1",
        "computedAt": int(time.time()),
    }
    # 阶段多帧确认（2026-09-24 spec：emotion-stage-multiframe-confirm）：
    # rawStage=本帧评分映射档位（含斜率，截面事实）；stage=确认投影——当日「严格早于当前槽」
    # 的截面序列 + 本帧一次，重放 stage_confirm.confirm_stage 滞回（复用零改动，审计 S1）。
    # score=None（证据全缺，方案 B）：rawStage=null、确认序列跳过本槽、不伪造档位（审计 B4）。
    from backend.analysis.hotlist.stage_confirm import confirm_stage

    history = stage_history or {"rawStagePoints": [], "historyStatus": "empty", "diagnostics": []}
    history_status = str(history.get("historyStatus") or "empty")
    prior_points = list(history.get("rawStagePoints") or [])
    current_stage_slot = str(current_slot or frame.get("slotTime") or slot)
    diagnostics_extra = list(history.get("diagnostics") or [])
    if score_value is None:
        diagnostics_extra.append(f"emotion_score_unavailable:slot={evidence_slot}")
    elif prev_score is None and history_status not in ("empty", "unavailable"):
        # 当日已有历史文档但取不到有效 prev score（切换日混合态/旧文档）→ 斜率不可用
        diagnostics_extra.append("emotion_slope_unavailable:prev_score_missing")
    if score_value is not None and "limitStruct" in (emotion.get("skippedDims") or []):
        # 与炸板缺失行同风格（fail-visible）：涨停结构证据缺失使合成维跳过、维度基数降级
        # （独立 if：不并入上方 if/elif 链，两诊断可并存）
        diagnostics_extra.append("emotion_limitstruct_unavailable:limitSummary 缺失（涨停结构维跳过）")
    # historyStatus=unavailable 时历史不可信：只用本帧截面确认（fail-visible 不伪造历史）；
    # score=None 的本帧点两个分支都不得进序列（str(None)="None" 会穿透 confirm_stage
    # 的空串过滤伪造档位，spec §3.4）。
    current_point = [(current_stage_slot, raw_stage_value)] if raw_stage_value else []
    points = current_point if history_status == "unavailable" else [*prior_points, *current_point]
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
        "stage": confirmed_stage or None,
        "rawStage": raw_stage_value,
        "legacyCascadeStage": legacy_cascade_stage,
        "emotionScore": emotion_doc,
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
        # 初值携带历史收集层的诊断（legacy fallback / 非标准槽 / 读取失败 / 评分不可用）。
        "diagnostics": diagnostics_extra,
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
