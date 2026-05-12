from __future__ import annotations

from typing import Any

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
from backend.data.repository_factory import create_repository, storage_source_label
from backend.data.theme_research_repository import ThemeResearchRepository
from backend.utils import stable_hash


def build_theme_research(
    dataset_id: str,
    snapshot_type: str = "half_hour",
    *,
    engine_config: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    random_seed: int = 0,
) -> ThemeTrendResult:
    """从正式快照事实表回放构建题材研究帧，结果写入 research SQLite。

    使用多帧序列回放（replay_sequence）以追踪题材生命周期在帧间的迁移和持续性。
    不修改 themeDATA.db，不进入 Supabase 链路。

    已知限制：多帧回放依赖 snapshot sector rows 中的预计算因子值（由 TS engine 在捕获时计算）；
    跨帧概念（persistence/cooling/reversal 等）基于帧间 state 追踪而非 TS rotationAnalysis。
    """
    session = None if storage_source_label() == "mongodb" else SessionLocal()
    repo = create_repository(session)
    research_repo = ThemeResearchRepository()

    try:
        frames = repo.load_frame_bundles(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not frames:
            return _empty_result(
                dataset_id, snapshot_type, engine_config, random_seed, reason="empty_frames",
            )

        config = ThemeTrendConfig.from_patch(engine_config or {})
        config_hash = stable_hash(engine_config or {})
        resolved_meta = dict(meta or {})

        engine = ThemeTrendPythonEngine()
        result = engine.replay_sequence_typed(frames, config=config, meta=resolved_meta)

        # 注入数据集级溯源字段（帧级字段已在 replay_sequence 中注入）
        for factor in result.factors:
            factor.datasetId = dataset_id
            factor.snapshotType = snapshot_type
            factor.configHash = config_hash
            factor.randomSeed = random_seed

        for exposure in result.exposures:
            exposure.datasetId = dataset_id
            exposure.snapshotType = snapshot_type
            exposure.configHash = config_hash
            exposure.randomSeed = random_seed

        for signal in result.signals:
            signal.datasetId = dataset_id
            signal.snapshotType = snapshot_type
            signal.configHash = config_hash
            signal.randomSeed = random_seed

        theme_ids = {factor.themeId for factor in result.factors}
        stock_codes = {exposure.code for exposure in result.exposures}

        # 事务性写入：各 save_* 方法内部有独立 rollback。
        # 外层 try/except 阻止写入失败后继续执行 save_quality_report。
        # 注意：当前未使用 savepoint，跨表写入不是原子事务；
        # 若需要严格原子性，后续应使用 session.begin_nested()。
        try:
            if result.factors:
                research_repo.save_factor_frames([item.to_dict() for item in result.factors])
            if result.exposures:
                research_repo.save_stock_exposures([item.to_dict() for item in result.exposures])
            if result.signals:
                research_repo.save_signals([item.to_dict() for item in result.signals])
        except Exception:
            raise

        merged_quality = _build_quality_report(
            [result.qualityReport.to_dict()],
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
            factors=result.factors,
            exposures=result.exposures,
            signals=result.signals,
            qualityReport=merged_quality,
            strategyVersion=STRATEGY_VERSION,
            factorVersion=FACTOR_VERSION,
            signalVersion=SIGNAL_VERSION,
            meta=resolved_meta,
        )
    finally:
        research_repo.close()
        repo.close()
        if session is not None:
            session.close()


def _build_quality_report(
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
