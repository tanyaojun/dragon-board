"""轮动运行时服务：历史读取 → 引擎计算 → 写入 sector_rows/frame（I/O 走 to_thread）。"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.history import RotationHistoryService
from backend.snapshot_derivation.models import SnapshotBundle


class ThemeRotationService:
    """把轮动结果写入 SnapshotBundle（派生后的 sector_rows/frames），异常不阻断入库。"""

    def __init__(
        self,
        repo: Any,
        config: ThemeRotationConfig | None = None,
        engine: ThemeRotationEngine | None = None,
        previous_trading_day_fn: Any = None,
    ) -> None:
        self.config = config or ThemeRotationConfig()
        self._history = RotationHistoryService(repo, self.config, previous_trading_day_fn)
        self._engine = engine or ThemeRotationEngine(self.config)

    async def enrich_bundle(
        self,
        bundle: SnapshotBundle,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        slot_timestamp_ms: int,
        computed_at: int,
    ) -> None:
        """加载历史、计算轮动、就地修改 bundle.sector_rows 与 bundle.frames。"""
        try:
            if not bundle.sector_rows:
                # 9.6-⑤：theme_heat 全源不可用 → sectors=[]，显式标注而非静默
                self._record_issue(bundle, "theme_rotation_no_sector_input: sectors empty")
                return
            history = await asyncio.to_thread(
                self._history.load,
                dataset_id,
                snapshot_type,
                trading_date,
                slot_timestamp_ms,
            )
            current_sector_rows = list(bundle.sector_rows)
            current_stock_rows = list(bundle.stock_rows)
            frame = (bundle.frames or [{}])[0]
            indices = frame.get("indices") if isinstance(frame, dict) else None
            result = self._engine.compute(
                current_sector_rows,
                history.slots,
                current_stock_rows,
                indices=indices,
                computed_at=computed_at,
                trading_date=trading_date,
            )
            self._apply(result, bundle)
        except Exception as exc:  # fail-visible：轮动失败不得阻断快照入库
            self._record_issue(bundle, f"theme_rotation_failed: {type(exc).__name__}: {exc}")

    def _apply(self, result, bundle: SnapshotBundle) -> None:
        from backend.analysis.theme_rotation.engine import _theme_key

        status_by_key = {s.theme_id: s for s in result.statuses}
        for row in bundle.sector_rows:
            status = status_by_key.get(_theme_key(row))
            if status is None:
                continue
            # M12：仅在引擎有明确判定时覆盖，避免把前端透传值覆成 None
            if status.rotation_state is not None:
                row["rotationState"] = status.rotation_state
            else:
                flags = list(row.get("qualityFlags") or [])
                if "rotation_history_insufficient" not in flags:
                    flags.append("rotation_history_insufficient")
                row["qualityFlags"] = flags
            if status.lifecycle is not None:
                row["lifecycle"] = status.lifecycle
            if status.rotation_score is not None:
                row["rotationScore"] = status.rotation_score
            row["heatTrend"] = status.heat_trend
            row["flowTrend"] = status.flow_trend
            row["breadthTrend"] = status.breadth_trend
            row["crowdingTrend"] = status.crowding_trend
            row["rankChange"] = status.rank_change
            row["mainlineConcentrationRank"] = status.mainline_concentration_rank
            row["reasons"] = status.reasons
            row["factorBreakdown"] = status.factor_breakdown
            flags = list(row.get("qualityFlags") or [])
            for flag in status.quality_flags:
                if flag not in flags:
                    flags.append(flag)
            row["qualityFlags"] = flags

        for frame in bundle.frames:
            # C1：必须 camelCase 落库（消费端/历史旧行均为 camelCase）
            # L5：只覆盖 frame 顶层 rotationSummary，不动 themeContext.rotationAnalysis（迁移期兼容）
            frame["rotationSummary"] = result.market.to_camel_dict()

        derivation = self._derivation_meta(bundle, result)
        for frame in bundle.frames:
            metadata = dict(frame.get("metadata") or {})
            derivation_meta = dict(metadata.get("derivation") or {})
            derivation_meta["algorithmVersion"] = self.config.algorithm_version
            derivation_meta["rotationEvidence"] = derivation
            metadata["derivation"] = derivation_meta
            frame["metadata"] = metadata

    @staticmethod
    def _derivation_meta(bundle: SnapshotBundle, result) -> dict[str, Any]:
        return {
            "framesUsed": result.frames_used,
            "marketPhase": result.market.market_phase,
            "qualityIssues": list(result.quality_issues),
        }

    @staticmethod
    def _record_issue(bundle: SnapshotBundle, message: str) -> None:
        for frame in bundle.frames:
            metadata = dict(frame.get("metadata") or {})
            derivation_meta = dict(metadata.get("derivation") or {})
            issues = list(derivation_meta.get("qualityIssues") or [])
            issues.append(message)
            derivation_meta["qualityIssues"] = issues
            metadata["derivation"] = derivation_meta
            frame["metadata"] = metadata
