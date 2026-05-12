from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from backend.data.database import ResearchSessionLocal
from backend.data.models import (
    ThemeFactorFrameModel,
    ThemeStockExposureModel,
    ThemeSignalModel,
    ThemeQualityReportModel,
)
from backend.data.json_codec import dumps_json_field, loads_json_field


class ThemeResearchRepository:
    def __init__(self) -> None:
        self._session: Any = None
        self._mongo_repo: Any = None

    @property
    def mongo_repo(self) -> Any:
        if self._mongo_repo is None:
            from backend.data.repository_factory import get_runtime_mongodb_database
            from backend.data.mongo_research_repository import MongoResearchRepository

            self._mongo_repo = MongoResearchRepository(get_runtime_mongodb_database())
        return self._mongo_repo

    @property
    def is_mongodb(self) -> bool:
        from backend.settings import get_settings

        return get_settings().storage_backend == "mongodb"

    @property
    def session(self) -> Any:
        if self._session is None:
            self._session = ResearchSessionLocal()
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # ── 因子帧 ─────────────────────────────

    def save_factor_frames(self, rows: list[dict[str, Any]]) -> int:
        if self.is_mongodb:
            return self.mongo_repo.save_factor_frames(rows)
        count = 0
        try:
            for item in rows:
                model = ThemeFactorFrameModel(
                    dataset_id=str(item.get("datasetId") or ""),
                    snapshot_id=str(item.get("snapshotId") or ""),
                    snapshot_type=str(item.get("snapshotType") or "half_hour"),
                    trading_date=str(item.get("tradingDate") or ""),
                    slot_time=str(item.get("slotTime") or ""),
                    strategy_version=str(item.get("strategyVersion") or "theme-trend-v12"),
                    config_hash=str(item.get("configHash") or ""),
                    random_seed=int(item.get("randomSeed") or 0),
                    theme_id=str(item.get("themeId") or ""),
                    theme_name=str(item.get("themeName") or ""),
                    heat_score=float(item.get("heatScore") or 0.0),
                    momentum_score=float(item.get("momentumScore") or 0.0),
                    breadth_score=float(item.get("breadthScore") or 0.0),
                    fund_score=float(item.get("fundScore") or 0.0),
                    leadership_score=float(item.get("leadershipScore") or 0.0),
                    correlation_score=float(item.get("correlationScore") or 0.0),
                    crowding_risk=float(item.get("crowdingRisk") or 0.0),
                    persistence_score=float(item.get("persistenceScore") or 0.0),
                    rotation_state=str(item.get("rotationState") or "neutral"),
                    rank=int(item.get("rank") or 0),
                    quality_flags_json=dumps_json_field(item.get("qualityFlags") or []),
                    lifecycle=str(item.get("lifecycle") or "neutral"),
                )
                self.session.add(model)
                count += 1
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("failed to save theme factor frames") from None
        return count

    def get_factor_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        trading_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_mongodb:
            return self.mongo_repo.get_factor_frames(dataset_id, snapshot_type, trading_date)
        try:
            stmt = select(ThemeFactorFrameModel).where(
                ThemeFactorFrameModel.dataset_id == dataset_id,
                ThemeFactorFrameModel.snapshot_type == snapshot_type,
            )
            if trading_date:
                stmt = stmt.where(ThemeFactorFrameModel.trading_date == trading_date)
            rows = self.session.scalars(stmt.order_by(ThemeFactorFrameModel.snapshot_id)).all()
            return [_factor_to_dict(row) for row in rows]
        except SQLAlchemyError:
            return []

    # ── 个股暴露 ─────────────────────────────

    def save_stock_exposures(self, rows: list[dict[str, Any]]) -> int:
        if self.is_mongodb:
            return self.mongo_repo.save_stock_exposures(rows)
        count = 0
        try:
            for item in rows:
                model = ThemeStockExposureModel(
                    dataset_id=str(item.get("datasetId") or ""),
                    snapshot_id=str(item.get("snapshotId") or ""),
                    snapshot_type=str(item.get("snapshotType") or "half_hour"),
                    trading_date=str(item.get("tradingDate") or ""),
                    slot_time=str(item.get("slotTime") or ""),
                    strategy_version=str(item.get("strategyVersion") or "theme-trend-v12"),
                    config_hash=str(item.get("configHash") or ""),
                    random_seed=int(item.get("randomSeed") or 0),
                    code=str(item.get("code") or ""),
                    theme_id=str(item.get("themeId") or ""),
                    theme_name=str(item.get("themeName") or ""),
                    role=str(item.get("role") or "unknown"),
                    role_score=float(item.get("roleScore") or 0.0),
                    exposure_weight=float(item.get("exposureWeight") or 0.0),
                    theme_contribution=float(item.get("themeContribution") or 0.0),
                    risk_penalty=float(item.get("riskPenalty") or 0.0),
                    reasons_json=dumps_json_field(item.get("reasons") or []),
                )
                self.session.add(model)
                count += 1
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("failed to save theme stock exposures") from None
        return count

    def get_stock_exposures(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        code: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_mongodb:
            return self.mongo_repo.get_stock_exposures(dataset_id, snapshot_id=snapshot_id, code=code)
        try:
            stmt = select(ThemeStockExposureModel).where(
                ThemeStockExposureModel.dataset_id == dataset_id,
            )
            if snapshot_id:
                stmt = stmt.where(ThemeStockExposureModel.snapshot_id == snapshot_id)
            if code:
                stmt = stmt.where(ThemeStockExposureModel.code == code)
            rows = self.session.scalars(stmt.order_by(ThemeStockExposureModel.exposure_weight.desc())).all()
            return [_exposure_to_dict(row) for row in rows]
        except SQLAlchemyError:
            return []

    # ── 信号 ─────────────────────────────

    def save_signals(self, rows: list[dict[str, Any]]) -> int:
        if self.is_mongodb:
            return self.mongo_repo.save_signals(rows)
        count = 0
        try:
            for item in rows:
                model = ThemeSignalModel(
                    dataset_id=str(item.get("datasetId") or ""),
                    snapshot_id=str(item.get("snapshotId") or ""),
                    snapshot_type=str(item.get("snapshotType") or "half_hour"),
                    trading_date=str(item.get("tradingDate") or ""),
                    slot_time=str(item.get("slotTime") or ""),
                    strategy_version=str(item.get("strategyVersion") or "theme-trend-v12"),
                    config_hash=str(item.get("configHash") or ""),
                    random_seed=int(item.get("randomSeed") or 0),
                    theme_id=str(item.get("themeId") or ""),
                    theme_name=str(item.get("themeName") or ""),
                    signal=str(item.get("signal") or "watch"),
                    risk=str(item.get("risk") or "none"),
                    lifecycle=str(item.get("lifecycle") or "neutral"),
                    score=float(item.get("score") or 0.0),
                )
                self.session.add(model)
                count += 1
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("failed to save theme signals") from None
        return count

    def get_signals(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        signal: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_mongodb:
            return self.mongo_repo.get_signals(dataset_id, snapshot_type, signal=signal)
        try:
            stmt = select(ThemeSignalModel).where(
                ThemeSignalModel.dataset_id == dataset_id,
                ThemeSignalModel.snapshot_type == snapshot_type,
            )
            if signal:
                stmt = stmt.where(ThemeSignalModel.signal == signal)
            rows = self.session.scalars(stmt.order_by(ThemeSignalModel.score.desc())).all()
            return [_signal_to_dict(row) for row in rows]
        except SQLAlchemyError:
            return []

    # ── 质量报告 ─────────────────────────────

    def save_quality_report(self, report: dict[str, Any]) -> bool:
        if self.is_mongodb:
            return self.mongo_repo.save_quality_report(report)
        try:
            model = ThemeQualityReportModel(
                dataset_id=str(report.get("datasetId") or ""),
                snapshot_type=str(report.get("snapshotType") or "half_hour"),
                strategy_version=str(report.get("strategyVersion") or "theme-trend-v12"),
                config_hash=str(report.get("configHash") or ""),
                random_seed=int(report.get("randomSeed") or 0),
                passed=bool(report.get("passed", False)),
                severity=str(report.get("severity") or "pass"),
                research_grade=str(report.get("researchGrade") or "research_ready"),
                issues_json=dumps_json_field(report.get("issues") or []),
                warnings_json=dumps_json_field(report.get("warnings") or []),
                stats_json=dumps_json_field(report.get("stats") or {}),
                theme_coverage=float(report.get("themeCoverage") or 0.0),
                frame_count=int(report.get("frameCount") or 0),
                stock_count=int(report.get("stockCount") or 0),
                theme_count=int(report.get("themeCount") or 0),
            )
            self.session.add(model)
            self.session.commit()
            return True
        except SQLAlchemyError:
            self.session.rollback()
            return False

    def get_quality_reports(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
    ) -> list[dict[str, Any]]:
        if self.is_mongodb:
            return self.mongo_repo.get_quality_reports(dataset_id, snapshot_type)
        try:
            stmt = (
                select(ThemeQualityReportModel)
                .where(
                    ThemeQualityReportModel.dataset_id == dataset_id,
                    ThemeQualityReportModel.snapshot_type == snapshot_type,
                )
                .order_by(ThemeQualityReportModel.id.desc())
            )
            rows = self.session.scalars(stmt).all()
            return [_quality_to_dict(row) for row in rows]
        except SQLAlchemyError:
            return []

    # ── 删除 ─────────────────────────────

    def delete_theme_research(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        snapshot_id: str | None = None,
    ) -> dict[str, int]:
        if self.is_mongodb:
            return self.mongo_repo.delete_theme_research(dataset_id, snapshot_type, snapshot_id)
        deleted: dict[str, int] = {}
        try:
            for attr in ("theme_signals", "theme_stock_exposures", "theme_factor_frames"):
                stmt = delete(self._model_for(attr)).where(
                    self._model_for(attr).dataset_id == dataset_id,
                    self._model_for(attr).snapshot_type == snapshot_type,
                )
                if snapshot_id:
                    stmt = stmt.where(self._model_for(attr).snapshot_id == snapshot_id)
                result = self.session.execute(stmt)
                deleted[attr] = result.rowcount
            qr_stmt = delete(ThemeQualityReportModel).where(
                ThemeQualityReportModel.dataset_id == dataset_id,
                ThemeQualityReportModel.snapshot_type == snapshot_type,
            )
            deleted["theme_quality_reports"] = self.session.execute(qr_stmt).rowcount
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("failed to delete theme research data") from None
        return deleted

    @staticmethod
    def _model_for(table: str) -> Any:
        return {
            "theme_factor_frames": ThemeFactorFrameModel,
            "theme_stock_exposures": ThemeStockExposureModel,
            "theme_signals": ThemeSignalModel,
        }[table]


def _factor_to_dict(row: ThemeFactorFrameModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "datasetId": row.dataset_id,
        "snapshotId": row.snapshot_id,
        "snapshotType": row.snapshot_type,
        "tradingDate": row.trading_date,
        "slotTime": row.slot_time,
        "strategyVersion": row.strategy_version,
        "configHash": row.config_hash,
        "randomSeed": row.random_seed,
        "themeId": row.theme_id,
        "themeName": row.theme_name,
        "heatScore": row.heat_score,
        "momentumScore": row.momentum_score,
        "breadthScore": row.breadth_score,
        "fundScore": row.fund_score,
        "leadershipScore": row.leadership_score,
        "correlationScore": row.correlation_score,
        "crowdingRisk": row.crowding_risk,
        "persistenceScore": row.persistence_score,
        "rotationState": row.rotation_state,
        "rank": row.rank,
        "qualityFlags": loads_json_field(row.quality_flags_json),
        "lifecycle": row.lifecycle,
    }


def _exposure_to_dict(row: ThemeStockExposureModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "datasetId": row.dataset_id,
        "snapshotId": row.snapshot_id,
        "snapshotType": row.snapshot_type,
        "tradingDate": row.trading_date,
        "slotTime": row.slot_time,
        "strategyVersion": row.strategy_version,
        "configHash": row.config_hash,
        "randomSeed": row.random_seed,
        "code": row.code,
        "themeId": row.theme_id,
        "themeName": row.theme_name,
        "role": row.role,
        "roleScore": row.role_score,
        "exposureWeight": row.exposure_weight,
        "themeContribution": row.theme_contribution,
        "riskPenalty": row.risk_penalty,
        "reasons": loads_json_field(row.reasons_json),
    }


def _signal_to_dict(row: ThemeSignalModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "datasetId": row.dataset_id,
        "snapshotId": row.snapshot_id,
        "snapshotType": row.snapshot_type,
        "tradingDate": row.trading_date,
        "slotTime": row.slot_time,
        "strategyVersion": row.strategy_version,
        "configHash": row.config_hash,
        "randomSeed": row.random_seed,
        "themeId": row.theme_id,
        "themeName": row.theme_name,
        "signal": row.signal,
        "risk": row.risk,
        "lifecycle": row.lifecycle,
        "score": row.score,
    }


def _quality_to_dict(row: ThemeQualityReportModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "datasetId": row.dataset_id,
        "snapshotType": row.snapshot_type,
        "strategyVersion": row.strategy_version,
        "configHash": row.config_hash,
        "randomSeed": row.random_seed,
        "passed": row.passed,
        "severity": row.severity,
        "researchGrade": row.research_grade,
        "issues": loads_json_field(row.issues_json),
        "warnings": loads_json_field(row.warnings_json),
        "stats": loads_json_field(row.stats_json),
        "themeCoverage": row.theme_coverage,
        "frameCount": row.frame_count,
        "stockCount": row.stock_count,
        "themeCount": row.theme_count,
    }
