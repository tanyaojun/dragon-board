"""无 I/O 快照派生服务：MarketFactBundle → SnapshotBundle。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot
from backend.snapshot_derivation.models import MarketFactBundle, SnapshotBundle
from backend.snapshot_derivation.projection import build_ingest_payload


class SnapshotDerivationService:
    """把一次采集的原始事实按快照类型投影为完整 SnapshotBundle。

    不请求网络、不读数据库；投影实现位于 projection.py（由原 collector builder
    迁入）。派生元数据写入 frame.metadata.derivation，供审计与回放。
    """

    VERSION = "snapshot_derivation_v1"

    def derive(self, fact: MarketFactBundle, *, theme_governance: Any = None) -> SnapshotBundle:
        slot = SnapshotSlot(
            snapshot_type=fact.snapshot_type,
            trading_date=fact.trading_date,
            slot_time=fact.slot_time,
            timestamp_ms=fact.timestamp_ms,
        )
        ctx = MarketDataContext(
            stocks=list(fact.stocks),
            quotes=list(fact.quotes),
            depth=list(fact.depth),
            money_flow=list(fact.money_flow),
            themes=dict(fact.themes),
            limit_up=dict(fact.limit_up),
            sectors=list(fact.sectors),
            source_health=list(fact.source_health),
            market_meta=dict(fact.market_meta),
            snapshot_context=dict(fact.snapshot_context),
            limit_summary=dict(fact.limit_summary),
            indices=dict(fact.indices),
        )
        payload = build_ingest_payload(
            slot,
            ctx,
            dataset_id=fact.dataset_id,
            source=fact.source,
            capture_mode=fact.capture_mode,
            theme_governance=theme_governance,
        )
        derived_at = datetime.now(timezone.utc).isoformat()
        derivation_meta: dict[str, Any] = {
            "algorithmVersion": fact.algorithm_version,
            "configHash": fact.config_hash,
            "inputEvidence": {
                "stocks": len(fact.stocks),
                "quotes": len(fact.quotes),
                "depth": len(fact.depth),
                "moneyFlow": len(fact.money_flow),
                "themes": len(fact.themes),
                "limitUp": len(fact.limit_up),
                "sectors": len(fact.sectors),
                "sourceHealth": len(fact.source_health),
            },
            "derivedAt": derived_at,
            "qualityIssues": list(fact.quality_issues),
        }
        for frame in payload.get("frames") or []:
            metadata = dict(frame.get("metadata") or {})
            metadata["derivation"] = derivation_meta
            frame["metadata"] = metadata
        return SnapshotBundle(
            records=payload.get("items") or [],
            frames=payload.get("frames") or [],
            stock_rows=payload.get("stockRows") or [],
            sector_rows=payload.get("sectorRows") or [],
        )
