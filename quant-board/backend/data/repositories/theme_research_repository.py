from __future__ import annotations

from typing import Any


class ThemeResearchRepository:
    """题材研究仓储 —— mongodb 单链纯委托（2026-09-29 sqlite 分支退役）。

    全部读写委托 MongoResearchRepository（测试库/生产库由 settings 决定）；
    历史 sqlite ResearchSessionLocal 分支已删除。
    """

    def __init__(self) -> None:
        self._mongo_repo: Any = None

    @property
    def mongo_repo(self) -> Any:
        if self._mongo_repo is None:
            from backend.data.repositories.repository_factory import get_runtime_mongodb_database
            from backend.data.repositories.mongo_research_repository import MongoResearchRepository

            self._mongo_repo = MongoResearchRepository(get_runtime_mongodb_database())
        return self._mongo_repo

    @property
    def is_mongodb(self) -> bool:
        return True

    def close(self) -> None:
        return None

    # ── 因子帧 ─────────────────────────────

    def save_factor_frames(self, rows: list[dict[str, Any]]) -> int:
        return self.mongo_repo.save_factor_frames(rows)

    def get_factor_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        trading_date: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.mongo_repo.get_factor_frames(dataset_id, snapshot_type, trading_date)

    # ── 个股暴露 ─────────────────────────────

    def save_stock_exposures(self, rows: list[dict[str, Any]]) -> int:
        return self.mongo_repo.save_stock_exposures(rows)

    def get_stock_exposures(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        code: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.mongo_repo.get_stock_exposures(dataset_id, snapshot_id=snapshot_id, code=code)

    # ── 信号 ─────────────────────────────

    def save_signals(self, rows: list[dict[str, Any]]) -> int:
        return self.mongo_repo.save_signals(rows)

    def get_signals(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        signal: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.mongo_repo.get_signals(dataset_id, snapshot_type, signal=signal)

    # ── 质量报告 ─────────────────────────────

    def save_quality_report(self, report: dict[str, Any]) -> bool:
        return self.mongo_repo.save_quality_report(report)

    def get_quality_reports(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
    ) -> list[dict[str, Any]]:
        return self.mongo_repo.get_quality_reports(dataset_id, snapshot_type)

    # ── 删除 ─────────────────────────────

    def delete_theme_research(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        snapshot_id: str | None = None,
    ) -> dict[str, int]:
        return self.mongo_repo.delete_theme_research(dataset_id, snapshot_type, snapshot_id)
