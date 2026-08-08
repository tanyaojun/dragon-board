from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.data.models.models import (
    BacktestEquityCurve,
    BacktestQualityReport,
    BacktestRun,
    BacktestSignal,
    BacktestTrade,
    GoldenRankTrendCase,
    OptimizationRun,
)
from backend.data.ingest.json_codec import dumps_json_field, loads_json_field


class BacktestRepositoryMixin:
    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        try:
            run.request_json = dumps_json_field(run.request_json or "{}")
            run.result_json = dumps_json_field(run.result_json or "{}")
            managed = self.research_session.merge(run)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(BacktestRun, managed.id) or run

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        try:
            return self.research_session.get(BacktestRun, run_id)
        except SQLAlchemyError:
            return None

    # ── 归一化结果存取 ─────────────────────────────

    def save_backtest_trades(self, run_id: str, trades: list[dict[str, Any]], append: bool = True) -> int:
        count = 0
        try:
            for t in trades:
                row = BacktestTrade(
                    backtest_run_id=run_id,
                    code=str(t.get("code") or ""),
                    name=str(t.get("name") or ""),
                    side=str(t.get("side") or t.get("action") or "buy"),
                    entry_snapshot_id=str(t.get("entrySnapshotId") or "") or None,
                    exit_snapshot_id=str(t.get("exitSnapshotId") or "") or None,
                    entry_time=int(t.get("entryTime") or 0) or None,
                    exit_time=int(t.get("exitTime") or 0) or None,
                    entry_trading_date=str(t.get("entryTradingDate") or "") or None,
                    exit_trading_date=str(t.get("exitTradingDate") or "") or None,
                    entry_price=float(t.get("entryPrice")) if t.get("entryPrice") is not None else None,
                    exit_price=float(t.get("exitPrice")) if t.get("exitPrice") is not None else None,
                    quantity=int(t.get("quantity") or 0),
                    gross_return=float(t.get("grossReturn")) if t.get("grossReturn") is not None else None,
                    net_return=float(t.get("netReturn")) if t.get("netReturn") is not None else None,
                    profit=float(t.get("profit")) if t.get("profit") is not None else None,
                    holding_bars=int(t.get("holdingBars") or 0),
                    reason=str(t.get("reason") or "") or None,
                    candidate_tier=str(t.get("candidateTier") or "") or None,
                    stage=str(t.get("stage") or "") or None,
                    regime=str(t.get("regime") or "") or None,
                    explanation=str(t.get("explanation") or "") or None,
                    fill_detail_json=dumps_json_field(t.get("fill") or {}),
                )
                self.research_session.add(row)
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest trades") from exc
        return count

    def get_backtest_trades(self, run_id: str, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        try:
            query = select(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id).order_by(BacktestTrade.id)
            if offset:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            rows = self.research_session.scalars(query).all()
            return [self._trade_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def iter_backtest_trades(self, run_id: str, batch_size: int = 1000):
        yield from self.get_backtest_trades(run_id)

    def count_backtest_trades(self, run_id: str) -> int:
        try:
            return int(
                self.research_session.scalar(
                    select(func.count()).select_from(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id)
                )
                or 0
            )
        except SQLAlchemyError:
            return 0

    def save_backtest_equity_curve(self, run_id: str, curve: list[dict[str, Any]], append: bool = True) -> int:
        count = 0
        try:
            for pt in curve:
                row = BacktestEquityCurve(
                    backtest_run_id=run_id,
                    snapshot_id=str(pt.get("snapshotId") or "") or None,
                    timestamp=int(pt.get("timestamp") or 0) or None,
                    trading_date=str(pt.get("tradingDate") or "") or None,
                    equity=float(pt.get("equity")) if pt.get("equity") is not None else None,
                    cash=float(pt.get("cash")) if pt.get("cash") is not None else None,
                    market_value=float(pt.get("marketValue")) if pt.get("marketValue") is not None else None,
                    position_count=int(pt.get("positionCount") or 0),
                )
                self.research_session.add(row)
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest equity curve") from exc
        return count

    def save_backtest_equity_rows(self, run_id: str, rows: list[dict[str, Any]]) -> int:
        count = 0
        try:
            for pt in rows:
                self.research_session.add(
                    BacktestEquityCurve(
                        backtest_run_id=run_id,
                        snapshot_id=str(pt.get("snapshotId") or "") or None,
                        timestamp=int(pt.get("timestamp") or 0) or None,
                        trading_date=str(pt.get("tradingDate") or "") or None,
                        equity=float(pt.get("equity")) if pt.get("equity") is not None else None,
                        cash=float(pt.get("cash")) if pt.get("cash") is not None else None,
                        market_value=float(pt.get("marketValue")) if pt.get("marketValue") is not None else None,
                        position_count=int(pt.get("positionCount") or 0),
                    )
                )
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to restore normalized backtest equity curve") from exc
        return count

    def get_backtest_equity_curve(self, run_id: str) -> list[dict[str, Any]]:
        try:
            rows = self.research_session.scalars(
                select(BacktestEquityCurve).where(BacktestEquityCurve.backtest_run_id == run_id).order_by(BacktestEquityCurve.id)
            ).all()
            return [self._equity_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def iter_backtest_equity_curve(self, run_id: str, batch_size: int = 1000):
        yield from self.get_backtest_equity_curve(run_id)

    def save_backtest_signals(
        self,
        run_id: str,
        strategy_decisions: dict[str, Any],
        append: bool = True,
    ) -> int:
        count = 0
        try:
            for fr in strategy_decisions.get("frameResults") or []:
                snapshot_id = str(fr.get("snapshotId") or "")
                trading_date = str(fr.get("tradingDate") or "")
                for d in fr.get("buyCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
                for d in fr.get("watchCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
                for d in fr.get("excludedCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest signals") from exc
        return count

    def save_backtest_signal_rows(self, run_id: str, rows: list[dict[str, Any]], append: bool = True) -> int:
        count = 0
        try:
            for item in rows:
                self.research_session.add(
                    BacktestSignal(
                        backtest_run_id=run_id,
                        snapshot_id=str(item.get("snapshotId") or "") or None,
                        trading_date=str(item.get("tradingDate") or "") or None,
                        code=str(item.get("code") or ""),
                        name=str(item.get("name") or ""),
                        candidate_tier=str(item.get("candidateTier") or "") or None,
                        signal=str(item.get("signal") or "") or None,
                        confidence=float(item.get("confidence")) if item.get("confidence") is not None else None,
                        rank=int(item.get("rank")) if item.get("rank") is not None else None,
                        stage=str(item.get("stage") or "") or None,
                        regime=str(item.get("regime") or "") or None,
                        reasons_json=dumps_json_field(item.get("reasons") or []),
                        risk_flags_json=dumps_json_field(item.get("riskFlags") or []),
                        main_theme=str(item.get("mainTheme") or "") or None,
                        theme_heat=float(item.get("themeHeat")) if item.get("themeHeat") is not None else None,
                        theme_contribution=float(item.get("themeContribution")) if item.get("themeContribution") is not None else None,
                        theme_role=str(item.get("themeRole") or "") or None,
                        theme_support_score=float(item.get("themeSupportScore")) if item.get("themeSupportScore") is not None else None,
                        theme_risk_flags_json=dumps_json_field(item.get("themeRiskFlags") or []),
                        theme_reasons_json=dumps_json_field(item.get("themeReasons") or []),
                    )
                )
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to restore normalized backtest signals") from exc
        return count

    @staticmethod
    def _signal_from_decision(run_id: str, snapshot_id: str, trading_date: str, d: dict[str, Any]) -> BacktestSignal:
        return BacktestSignal(
            backtest_run_id=run_id,
            snapshot_id=snapshot_id or None,
            trading_date=trading_date or None,
            code=str(d.get("code") or ""),
            name=str(d.get("name") or ""),
            candidate_tier=str(d.get("candidateTier") or "") or None,
            signal=str(d.get("signal") or "") or None,
            confidence=float(d.get("confidence")) if d.get("confidence") is not None else None,
            rank=int(d.get("rank")) if d.get("rank") is not None else None,
            stage=str(d.get("stage") or "") or None,
            regime=str(d.get("regime") or "") or None,
            reasons_json=dumps_json_field(d.get("reasons") or []),
            risk_flags_json=dumps_json_field(d.get("riskFlags") or []),
            main_theme=str(d.get("mainTheme") or "") or None,
            theme_heat=float(d.get("themeHeat")) if d.get("themeHeat") is not None else None,
            theme_contribution=float(d.get("themeContribution")) if d.get("themeContribution") is not None else None,
            theme_role=str(d.get("themeRole") or "") or None,
            theme_support_score=float(d.get("themeSupportScore")) if d.get("themeSupportScore") is not None else None,
            theme_risk_flags_json=dumps_json_field(d.get("themeRiskFlags") or []),
            theme_reasons_json=dumps_json_field(d.get("themeReasons") or []),
        )

    def get_backtest_signals(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
        tier: str | None = None,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self._backtest_signal_query(run_id, tier=tier, regime=regime).order_by(BacktestSignal.id)
            if offset:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            rows = self.research_session.scalars(query).all()
            return [self._signal_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def iter_backtest_signals(self, run_id: str, batch_size: int = 1000):
        yield from self.get_backtest_signals(run_id)

    def count_backtest_signals(self, run_id: str, tier: str | None = None, regime: str | None = None) -> int:
        try:
            return int(
                self.research_session.scalar(
                    select(func.count()).select_from(
                        self._backtest_signal_query(run_id, tier=tier, regime=regime).subquery()
                    )
                )
                or 0
            )
        except SQLAlchemyError:
            return 0

    @staticmethod
    def _backtest_signal_query(run_id: str, tier: str | None = None, regime: str | None = None):
        query = select(BacktestSignal).where(BacktestSignal.backtest_run_id == run_id)
        if tier:
            query = query.where(BacktestSignal.candidate_tier == tier)
        if regime:
            query = query.where(BacktestSignal.regime == regime)
        return query

    def save_backtest_quality_report(self, run_id: str, data_quality: dict[str, Any], quality_gate: dict[str, Any] | None = None) -> bool:
        try:
            gate = quality_gate if isinstance(quality_gate, dict) else {}
            stats = gate.get("stats") if isinstance(gate.get("stats"), dict) else {}
            row = BacktestQualityReport(
                backtest_run_id=run_id,
                passed=bool(data_quality.get("severity") == "pass"),
                severity=str(data_quality.get("severity") or "pass"),
                research_grade=str(data_quality.get("researchGrade") or "research_ready"),
                frame_count=int(data_quality.get("snapshotCount") or 0),
                stock_count=int(gate.get("stockCount") or stats.get("stockCount") or 0),
                sector_count=int(gate.get("sectorCount") or stats.get("sectorCount") or 0),
                missing_fields_json=dumps_json_field(stats.get("missingFields") or {}),
                nan_counts_json=dumps_json_field(stats.get("nanCounts") or {}),
                inf_counts_json=dumps_json_field(stats.get("infCounts") or {}),
                negative_price_count=int(stats.get("negativePriceCount") or 0),
                non_positive_price_count=int(stats.get("nonPositivePriceCount") or 0),
                negative_volume_count=int(stats.get("negativeVolumeCount") or 0),
                coverage_ratio=float(stats.get("coverageRatio")) if stats.get("coverageRatio") is not None else None,
                time_order_fixed=bool(gate.get("timeOrderFixed") or False),
                time_order_fix_count=int(gate.get("timeOrderFixCount") or 0),
                warnings_json=dumps_json_field(data_quality.get("warnings") or []),
            )
            self.research_session.add(row)
            self.research_session.commit()
            return True
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest quality report") from exc

    def get_backtest_quality_report(self, run_id: str) -> dict[str, Any] | None:
        try:
            row = self.research_session.scalar(
                select(BacktestQualityReport).where(BacktestQualityReport.backtest_run_id == run_id).limit(1)
            )
            return self._quality_to_dict(row) if row else None
        except SQLAlchemyError:
            return None

    # ── research SQLite 维护 ───────────────────────

    def research_storage_summary(self) -> dict[str, Any]:
        tables = {
            "backtest_runs": BacktestRun,
            "backtest_trades": BacktestTrade,
            "backtest_equity_curve": BacktestEquityCurve,
            "backtest_signals": BacktestSignal,
            "backtest_quality_reports": BacktestQualityReport,
            "optimization_runs": OptimizationRun,
            "golden_ranktrend_cases": GoldenRankTrendCase,
        }
        try:
            counts = {
                name: int(self.research_session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in tables.items()
            }
            oldest = self.research_session.scalar(select(func.min(BacktestRun.created_at)))
            newest = self.research_session.scalar(select(func.max(BacktestRun.created_at)))
            return {
                "ok": True,
                "tables": counts,
                "backtestCreatedAt": {
                    "oldest": oldest.isoformat() if oldest else None,
                    "newest": newest.isoformat() if newest else None,
                },
            }
        except SQLAlchemyError as exc:
            return {"ok": False, "error": str(exc), "tables": {}}

    def delete_backtest_run(self, run_id: str, *, checkpoint: bool = False) -> dict[str, Any] | None:
        if not self.get_backtest_run(run_id):
            return None
        try:
            deleted: dict[str, int] = {}
            child_specs = [
                ("backtest_trades", BacktestTrade),
                ("backtest_equity_curve", BacktestEquityCurve),
                ("backtest_signals", BacktestSignal),
                ("backtest_quality_reports", BacktestQualityReport),
            ]
            for name, model in child_specs:
                result = self.research_session.execute(delete(model).where(model.backtest_run_id == run_id))
                deleted[name] = int(result.rowcount or 0)
            result = self.research_session.execute(delete(BacktestRun).where(BacktestRun.id == run_id))
            deleted["backtest_runs"] = int(result.rowcount or 0)
            self.research_session.commit()
            if checkpoint:
                self._checkpoint_research_sqlite()
            return {"ok": True, "runId": run_id, "deleted": deleted}
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to delete backtest run") from exc

    def list_backtest_runs(self, *, limit: int = 50) -> tuple[list[BacktestRun], int]:
        bounded_limit = max(1, min(int(limit), 200))
        total = int(self.research_session.scalar(select(func.count()).select_from(BacktestRun)) or 0)
        query = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(bounded_limit)
        return list(self.research_session.scalars(query).all()), total

    def cleanup_research_backtests(
        self,
        *,
        older_than_days: int = 30,
        keep_latest_per_group: int = 10,
        dataset_id: str | None = None,
        snapshot_type: str | None = None,
        include_failed: bool = False,
        apply: bool = False,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=max(0, older_than_days))
        try:
            query = select(BacktestRun).where(BacktestRun.created_at < cutoff)
            if dataset_id:
                query = query.where(BacktestRun.dataset_id == dataset_id)
            if snapshot_type:
                query = query.where(BacktestRun.snapshot_type == snapshot_type)
            if not include_failed:
                query = query.where(BacktestRun.status == "completed")
            rows = list(self.research_session.scalars(query).all())
            protected = self._protected_backtest_run_ids(keep_latest_per_group, dataset_id=dataset_id, snapshot_type=snapshot_type)
            candidates = [row for row in rows if row.id not in protected]
            run_ids = [row.id for row in candidates]
            counts = self._backtest_delete_counts(run_ids)
            result: dict[str, Any] = {
                "ok": True,
                "apply": bool(apply),
                "cutoff": cutoff.isoformat(),
                "matchedBacktestRuns": len(run_ids),
                "deleteCounts": counts,
                "protectedRuns": sorted(protected),
                "runs": [self.backtest_run_to_dict(row) for row in candidates[:200]],
                "truncated": len(candidates) > 200,
            }
            if apply and run_ids:
                deleted = self._delete_backtest_runs(run_ids)
                if checkpoint:
                    self._checkpoint_research_sqlite()
                result["deleted"] = deleted
            elif apply:
                result["deleted"] = {key: 0 for key in counts}
            return result
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to cleanup research backtests") from exc

    def _protected_backtest_run_ids(
        self,
        keep_latest_per_group: int,
        *,
        dataset_id: str | None = None,
        snapshot_type: str | None = None,
    ) -> set[str]:
        if keep_latest_per_group <= 0:
            return set()
        query = select(BacktestRun).order_by(BacktestRun.created_at.desc())
        if dataset_id:
            query = query.where(BacktestRun.dataset_id == dataset_id)
        if snapshot_type:
            query = query.where(BacktestRun.snapshot_type == snapshot_type)
        grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for row in self.research_session.scalars(query):
            key = (
                row.dataset_id,
                row.strategy_name,
                row.strategy_version,
                row.snapshot_type,
                row.config_hash,
                row.random_seed,
            )
            if len(grouped[key]) < keep_latest_per_group:
                grouped[key].append(row.id)
        protected: set[str] = set()
        for ids in grouped.values():
            protected.update(ids)
        return protected

    def _backtest_delete_counts(self, run_ids: list[str]) -> dict[str, int]:
        if not run_ids:
            return {
                "backtest_runs": 0,
                "backtest_trades": 0,
                "backtest_equity_curve": 0,
                "backtest_signals": 0,
                "backtest_quality_reports": 0,
            }
        specs = [
            ("backtest_runs", BacktestRun, BacktestRun.id),
            ("backtest_trades", BacktestTrade, BacktestTrade.backtest_run_id),
            ("backtest_equity_curve", BacktestEquityCurve, BacktestEquityCurve.backtest_run_id),
            ("backtest_signals", BacktestSignal, BacktestSignal.backtest_run_id),
            ("backtest_quality_reports", BacktestQualityReport, BacktestQualityReport.backtest_run_id),
        ]
        return {
            name: int(self.research_session.scalar(select(func.count()).select_from(model).where(column.in_(run_ids))) or 0)
            for name, model, column in specs
        }

    def _delete_backtest_runs(self, run_ids: list[str]) -> dict[str, int]:
        if not run_ids:
            return self._backtest_delete_counts([])
        deleted: dict[str, int] = {}
        for name, model in [
            ("backtest_trades", BacktestTrade),
            ("backtest_equity_curve", BacktestEquityCurve),
            ("backtest_signals", BacktestSignal),
            ("backtest_quality_reports", BacktestQualityReport),
        ]:
            result = self.research_session.execute(delete(model).where(model.backtest_run_id.in_(run_ids)))
            deleted[name] = int(result.rowcount or 0)
        result = self.research_session.execute(delete(BacktestRun).where(BacktestRun.id.in_(run_ids)))
        deleted["backtest_runs"] = int(result.rowcount or 0)
        self.research_session.commit()
        return deleted

    def _checkpoint_research_sqlite(self) -> None:
        bind = self.research_session.get_bind()
        if bind and bind.dialect.name == "sqlite":
            self.research_session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            self.research_session.commit()

    def vacuum_research_sqlite(self) -> dict[str, Any]:
        bind = self.research_session.get_bind()
        if not bind or bind.dialect.name != "sqlite":
            return {"ok": False, "skipped": True, "reason": "research database is not sqlite"}
        self.research_session.rollback()
        with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
        return {"ok": True, "vacuum": True}

    # ── 序列化 ─────────────────────────────────────

    @staticmethod
    def _trade_to_dict(model: BacktestTrade) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "code": model.code,
            "name": model.name,
            "side": model.side,
            "entrySnapshotId": model.entry_snapshot_id,
            "exitSnapshotId": model.exit_snapshot_id,
            "entryTime": model.entry_time,
            "exitTime": model.exit_time,
            "entryTradingDate": model.entry_trading_date,
            "exitTradingDate": model.exit_trading_date,
            "entryPrice": model.entry_price,
            "exitPrice": model.exit_price,
            "quantity": model.quantity,
            "grossReturn": model.gross_return,
            "netReturn": model.net_return,
            "profit": model.profit,
            "holdingBars": model.holding_bars,
            "reason": model.reason,
            "candidateTier": model.candidate_tier,
            "stage": model.stage,
            "regime": model.regime,
            "explanation": model.explanation,
            "fillDetail": loads_json_field(model.fill_detail_json, {}),
        }

    @staticmethod
    def _equity_to_dict(model: BacktestEquityCurve) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "equity": model.equity,
            "cash": model.cash,
            "marketValue": model.market_value,
            "positionCount": model.position_count,
        }

    @staticmethod
    def _signal_to_dict(model: BacktestSignal) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "snapshotId": model.snapshot_id,
            "tradingDate": model.trading_date,
            "code": model.code,
            "name": model.name,
            "candidateTier": model.candidate_tier,
            "signal": model.signal,
            "confidence": model.confidence,
            "rank": model.rank,
            "stage": model.stage,
            "regime": model.regime,
            "reasons": loads_json_field(model.reasons_json, []),
            "riskFlags": loads_json_field(model.risk_flags_json, []),
            "mainTheme": model.main_theme,
            "themeHeat": model.theme_heat,
            "themeContribution": model.theme_contribution,
            "themeRole": model.theme_role,
            "themeSupportScore": model.theme_support_score,
            "themeRiskFlags": loads_json_field(model.theme_risk_flags_json, []),
            "themeReasons": loads_json_field(model.theme_reasons_json, []),
        }

    @staticmethod
    def _quality_to_dict(model: BacktestQualityReport) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "passed": model.passed,
            "severity": model.severity,
            "researchGrade": model.research_grade,
            "frameCount": model.frame_count,
            "stockCount": model.stock_count,
            "sectorCount": model.sector_count,
            "missingFields": loads_json_field(model.missing_fields_json, {}),
            "nanCounts": loads_json_field(model.nan_counts_json, {}),
            "infCounts": loads_json_field(model.inf_counts_json, {}),
            "negativePriceCount": model.negative_price_count,
            "nonPositivePriceCount": model.non_positive_price_count,
            "negativeVolumeCount": model.negative_volume_count,
            "coverageRatio": model.coverage_ratio,
            "timeOrderFixed": model.time_order_fixed,
            "timeOrderFixCount": model.time_order_fix_count,
            "warnings": loads_json_field(model.warnings_json, []),
        }

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        try:
            run.request_json = dumps_json_field(run.request_json or "{}")
            run.result_json = dumps_json_field(run.result_json or "{}")
            managed = self.research_session.merge(run)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(OptimizationRun, managed.id) or run

    def get_optimization_run(self, run_id: str) -> OptimizationRun | None:
        try:
            return self.research_session.get(OptimizationRun, run_id)
        except SQLAlchemyError:
            return None

    def save_golden_case(self, case: GoldenRankTrendCase) -> GoldenRankTrendCase:
        try:
            case.input_json = dumps_json_field(case.input_json or "{}")
            case.expected_json = dumps_json_field(case.expected_json or "{}")
            managed = self.research_session.merge(case)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(GoldenRankTrendCase, managed.id) or case

    def get_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        try:
            return self.research_session.get(GoldenRankTrendCase, case_id)
        except SQLAlchemyError:
            return None

    @staticmethod
    def backtest_run_to_dict(model: BacktestRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "strategy_version": model.strategy_version,
            "snapshot_type": model.snapshot_type,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "dateStart": model.date_start,
            "dateEnd": model.date_end,
            "errorReason": model.error_reason,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "finished_at": model.finished_at.isoformat() if model.finished_at else None,
        }

    @staticmethod
    def optimization_run_to_dict(model: OptimizationRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "method": model.method,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def golden_case_to_dict(model: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "dataset_id": model.dataset_id,
            "input_json": model.input_json,
            "expected_json": model.expected_json,
            "input": loads_json_field(model.input_json, {}),
            "expected": loads_json_field(model.expected_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }
