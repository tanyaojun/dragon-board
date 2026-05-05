from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.analysis.theme_trend import (
    ThemeTrendConfig,
    ThemeTrendPythonEngine,
    ThemeTrendResult,
    ThemeFactorFrame,
    ThemeStockExposureFrame,
    ThemeSignalRow,
    ThemeQualityReport,
    STRATEGY_VERSION,
    FACTOR_VERSION,
    SIGNAL_VERSION,
)
from backend.data.database import SessionLocal
from backend.data.repository import Repository
from backend.data.theme_research_repository import ThemeResearchRepository
from backend.utils import stable_hash

DEFAULT_MIN_FRAME_COUNT = 2


def build_theme_research(
    dataset_id: str,
    snapshot_type: str = "half_hour",
    *,
    engine_config: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    random_seed: int = 0,
) -> ThemeTrendResult:
    """从正式快照事实表回放构建题材研究帧，结果写入 research SQLite。

    不修改 themeDATA.db，不进入 Supabase 链路。

    已知限制：当前逐帧回放，跨帧概念（persistence/cooling/reversal 等生命周期推断）
    在单帧视角下不完全可靠。后续迭代将实现真正的跨帧回放。
    """
    session = SessionLocal()
    repo = Repository(session=session)
    research_repo = ThemeResearchRepository()

    try:
        frames = repo.load_frame_bundles(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not frames:
            return _empty_result(
                dataset_id,
                snapshot_type,
                engine_config,
                random_seed,
                reason="empty_frames",
            )

        config = ThemeTrendConfig.from_patch(engine_config or {})
        config_hash = stable_hash(engine_config or {})
        resolved_meta = dict(meta or {})

        engine = ThemeTrendPythonEngine()
        all_factors: list[ThemeFactorFrame] = []
        all_exposures: list[ThemeStockExposureFrame] = []
        all_signals: list[ThemeSignalRow] = []
        quality_reports: list[dict[str, Any]] = []
        theme_ids: set[str] = set()
        stock_codes: set[str] = set()

        for frame in frames:
            typed = engine.replay_typed([frame], config=config, meta=resolved_meta)

            snapshot_id = str(frame.get("snapshotId") or "")
            trading_date = str(frame.get("tradingDate") or "")
            slot_time = str(frame.get("slotTime") or "")

            for factor in typed.factors:
                factor.datasetId = dataset_id
                factor.snapshotId = snapshot_id
                factor.snapshotType = snapshot_type
                factor.tradingDate = trading_date
                factor.slotTime = slot_time
                factor.configHash = config_hash
                factor.randomSeed = random_seed
                all_factors.append(factor)
                theme_ids.add(factor.themeId)

            for exposure in typed.exposures:
                exposure.datasetId = dataset_id
                exposure.snapshotId = snapshot_id
                exposure.snapshotType = snapshot_type
                exposure.tradingDate = trading_date
                exposure.slotTime = slot_time
                exposure.configHash = config_hash
                exposure.randomSeed = random_seed
                all_exposures.append(exposure)
                stock_codes.add(exposure.code)

            for signal in typed.signals:
                signal.datasetId = dataset_id
                signal.snapshotId = snapshot_id
                signal.snapshotType = snapshot_type
                signal.tradingDate = trading_date
                signal.slotTime = slot_time
                signal.configHash = config_hash
                signal.randomSeed = random_seed
                all_signals.append(signal)

            quality_reports.append(typed.qualityReport.to_dict())

        # 事务性写入：任一写入失败则全部回滚
        try:
            if all_factors:
                research_repo.save_factor_frames([item.to_dict() for item in all_factors])
            if all_exposures:
                research_repo.save_stock_exposures([item.to_dict() for item in all_exposures])
            if all_signals:
                research_repo.save_signals([item.to_dict() for item in all_signals])
        except Exception:
            # 回滚由各个 save_* 方法内部处理，此处仅阻止继续写入质量报告
            raise

        merged_quality = _merge_quality_reports(
            quality_reports,
            dataset_id,
            snapshot_type,
            engine_config,
            random_seed,
            len(frames),
            theme_ids=theme_ids,
            stock_codes=stock_codes,
        )
        research_repo.save_quality_report(merged_quality.to_dict())

        return ThemeTrendResult(
            factors=all_factors,
            exposures=all_exposures,
            signals=all_signals,
            qualityReport=merged_quality,
            strategyVersion=STRATEGY_VERSION,
            factorVersion=FACTOR_VERSION,
            signalVersion=SIGNAL_VERSION,
            meta=resolved_meta,
        )
    finally:
        research_repo.close()
        repo.close()
        session.close()


def _merge_quality_reports(
    reports: list[dict[str, Any]],
    dataset_id: str,
    snapshot_type: str,
    engine_config: dict[str, Any] | None,
    random_seed: int,
    total_frames: int,
    *,
    theme_ids: set[str] | None = None,
    stock_codes: set[str] | None = None,
) -> ThemeQualityReport:
    all_errors: list[str] = []
    all_warnings: list[str] = []

    for r in reports:
        all_errors.extend(r.get("errors", []))
        all_warnings.extend(r.get("warnings", []))

    unique_errors = list(dict.fromkeys(all_errors))
    unique_warnings = list(dict.fromkeys(all_warnings))
    blocked = bool(unique_errors)

    if blocked:
        severity = "fail"
        research_grade = "failed"
    elif unique_warnings:
        severity = "warn"
        research_grade = "degraded"
    else:
        severity = "pass"
        research_grade = "research_ready"

    return ThemeQualityReport(
        passed=not blocked,
        severity=severity,
        researchGrade=research_grade,
        issues=unique_errors,
        warnings=unique_warnings,
        stats={
            "totalFrames": total_frames,
            "snapshotType": snapshot_type,
            "errorCount": len(unique_errors),
            "warningCount": len(unique_warnings),
        },
        frameCount=total_frames,
        themeCount=len(theme_ids) if theme_ids is not None else 0,
        stockCount=len(stock_codes) if stock_codes is not None else 0,
        themeCoverage=0.0,
        datasetId=dataset_id,
        snapshotType=snapshot_type,
        configHash=stable_hash(engine_config or {}),
        randomSeed=random_seed,
    )


def _empty_result(
    dataset_id: str,
    snapshot_type: str,
    engine_config: dict[str, Any] | None,
    random_seed: int,
    reason: str,
) -> ThemeTrendResult:
    qr = ThemeQualityReport(
        passed=False,
        severity="fail",
        researchGrade="failed",
        issues=[reason],
        warnings=[],
        stats={"snapshotType": snapshot_type},
        frameCount=0,
        themeCount=0,
        stockCount=0,
        themeCoverage=0.0,
        datasetId=dataset_id,
        snapshotType=snapshot_type,
        configHash=stable_hash(engine_config or {}),
        randomSeed=random_seed,
    )
    return ThemeTrendResult(
        qualityReport=qr,
        strategyVersion=STRATEGY_VERSION,
        factorVersion=FACTOR_VERSION,
        signalVersion=SIGNAL_VERSION,
    )
