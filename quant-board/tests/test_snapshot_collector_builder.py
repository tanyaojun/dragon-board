"""Tests for snapshot_collector builder module — Task 6: Builder Minimal Ingest Payload."""

from __future__ import annotations

import pytest

from backend.data.schemas import SnapshotIngestRequest
from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest
from backend.snapshot_collector.models import (
    MarketDataContext,
    SnapshotSlot,
    SourceHealth,
)
from backend.snapshot_collector.builder import (
    _enrich_stock_rows_from_quotes,
    build_ingest_payload,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_slot_1500() -> SnapshotSlot:
    """A half_hour slot for 2026-06-11 15:00."""
    import datetime
    from zoneinfo import ZoneInfo

    tz_shanghai = ZoneInfo("Asia/Shanghai")
    dt = datetime.datetime(2026, 6, 11, 15, 0, tzinfo=tz_shanghai)
    return SnapshotSlot(
        snapshot_type="half_hour",
        trading_date="2026-06-11",
        slot_time="15:00",
        timestamp_ms=int(dt.timestamp() * 1000),
    )


def make_fake_context() -> MarketDataContext:
    """Return a minimal MarketDataContext with two stocks and one sector."""
    return MarketDataContext(
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "price": 12.50,
                "pctChange": 2.35,
                "volume": 150000000,
                "amount": 1875000000.0,
                "turnover": 5.5,
                "heat": 92.0,
                "themes": ["银行", "深圳"],
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "rank": 2,
                "price": 9.80,
                "pctChange": -0.51,
                "volume": 80000000,
                "amount": 784000000.0,
                "turnover": 2.1,
                "heat": 75.0,
                "themes": ["银行", "上海"],
            },
        ],
        quotes=[
            {"code": "000001", "price": 12.50, "pctChange": 2.35, "volume": 150000000},
            {"code": "600000", "price": 9.80, "pctChange": -0.51, "volume": 80000000},
        ],
        depth=[
            {"code": "000001", "bidPrice1": 12.49, "askPrice1": 12.51},
            {"code": "600000", "bidPrice1": 9.79, "askPrice1": 9.81},
        ],
        themes={
            "000001": ["银行", "深圳"],
            "600000": ["银行", "上海"],
        },
        sectors=[
            {
                "code": "BK001",
                "name": "银行",
                "entityType": "sector",
                "rank": 1,
                "pctChange": 1.20,
            },
        ],
        source_health=[
            SourceHealth(source="hotlist_proxy", ok=True, row_count=2),
            SourceHealth(source="quote_bridge", ok=True, row_count=2),
            SourceHealth(
                source="money_flow_estimated_l1",
                ok=True,
                row_count=2,
                error="L2 unavailable; using estimated L1 money flow",
            ),
        ],
        market_meta={
            "marketName": "A股",
            "totalVolume": 500000000000,
            "upCount": 2500,
            "downCount": 1800,
        },
    )


# ── Builder output assertions ────────────────────────────────────────────────


class TestBuilderOutput:
    """Verify the builder produces a correct minimal ingest payload."""

    def test_dataset_id_is_shadow(self):
        """Output must reference the shadow dataset."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        assert result["datasetId"] == "dragonboard_backend_shadow"

    def test_dataset_id_custom(self):
        """Custom dataset_id is respected."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx, dataset_id="dragonboard_live")
        assert result["datasetId"] == "dragonboard_live"

    def test_snapshot_id_format(self):
        """Output must contain the canonical snapshot_id."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        assert result["snapshotId"] == "half_hour:2026-06-11:15:00"

    def test_has_one_frame_with_stock_count(self):
        """Frame must exist with stockRowCount matching the stock count."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        frames = result["frames"]
        assert len(frames) == 1
        frame = frames[0]
        assert frame["stockRowCount"] == 2
        assert frame["sectorRowCount"] == 1

    def test_has_two_stock_rows_with_all_fields(self):
        """Stock rows must include code, name, rank, price, pctChange,
        volume, amount, turnover, heat, and themes."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        stock_rows = result["stockRows"]
        assert len(stock_rows) == 2

        # Sorted by rank ascending
        assert stock_rows[0]["code"] == "000001"
        assert stock_rows[1]["code"] == "600000"

        required_fields = [
            "code", "name", "rank", "price", "pctChange",
            "volume", "amount", "turnover", "heat", "themes",
        ]
        for row in stock_rows:
            for field in required_fields:
                assert field in row, f"stock row missing field: {field}"

        # Verify specific field values for first stock
        row0 = stock_rows[0]
        assert row0["code"] == "000001"
        assert row0["name"] == "平安银行"
        assert row0["rank"] == 1
        assert row0["price"] == 12.50
        assert row0["pctChange"] == 2.35
        assert row0["volume"] == 150000000
        assert row0["amount"] == pytest.approx(1875000000.0)
        assert row0["turnover"] == pytest.approx(1875000000.0)
        assert row0["turnoverRate"] == 5.5
        assert row0["heat"] == 92.0
        assert row0["themes"] == ["银行", "深圳"]

    def test_has_at_least_one_sector_row(self):
        """Sector rows must have at least one entry."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        sector_rows = result["sectorRows"]
        assert len(sector_rows) >= 1
        sector = sector_rows[0]
        assert sector["entityType"] == "sector"
        assert sector["entityName"] == "银行"

    def test_sector_factor_fields_preserve_nullable_values(self):
        slot = make_slot_1500()
        ctx = make_fake_context()
        ctx.sectors = [
            {
                "code": "AI",
                "name": "人工智能",
                "entityType": "hot_theme",
                "rank": 1,
                "heatScore": None,
                "fundScore": None,
                "breadthScore": 66,
                "themeQualityFlags": ["fund_flow_unavailable"],
                "metadata": {"quoteCoverage": 0.9},
            }
        ]

        row = build_ingest_payload(slot, ctx)["sectorRows"][0]

        assert row["heatScore"] is None
        assert row["fundScore"] is None
        assert row["breadthScore"] == 66
        assert row["themeQualityFlags"] == ["fund_flow_unavailable"]
        assert row["metadata"] == {"quoteCoverage": 0.9}

    def test_source_is_backend_collector(self):
        """source must be quantboard_backend_collector."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        assert result["source"] == "quantboard_backend_collector"
        # Also check on record and frame level
        for record in result["items"]:
            assert record["source"] == "quantboard_backend_collector"
        for frame in result["frames"]:
            assert frame["source"] == "quantboard_backend_collector"

    def test_capture_mode_is_set(self):
        """captureMode must be set (default real_time, can be delayed)."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        assert result["captureMode"] == "real_time"
        for record in result["items"]:
            assert record["captureMode"] == "real_time"

    def test_capture_mode_delayed(self):
        """captureMode delayed when explicitly set."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx, capture_mode="delayed")
        assert result["captureMode"] == "delayed"

    def test_quality_flags_included(self):
        """qualityFlags must contain partial provider, delayed capture,
        and estimated L1 money flow when provided."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        quality = [
            "quote_provider_partial",
            "delayed_capture",
            "money_flow_estimated_l1",
        ]
        result = build_ingest_payload(slot, ctx, quality_flags=quality)
        assert "qualityFlags" in result
        assert "quote_provider_partial" in result["qualityFlags"]
        assert "delayed_capture" in result["qualityFlags"]
        assert "money_flow_estimated_l1" in result["qualityFlags"]

    def test_quality_flags_absent_when_none(self):
        """qualityFlags should not be present when None."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        assert "qualityFlags" not in result

    def test_record_has_snapshot_metadata(self):
        """Each record must carry snapshot type, trading date, slot time, timestamp."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        records = result["items"]
        assert len(records) == 1
        record = records[0]
        assert record["id"] == "half_hour:2026-06-11:15:00"
        assert record["type"] == "half_hour"
        assert record["tradingDate"] == "2026-06-11"
        assert record["slotTime"] == "15:00"
        assert record["timestamp"] == slot.timestamp_ms
        assert record["captureMode"] == "real_time"
        assert "payload" in record
        assert "hotlist" in record["payload"]

    def test_stock_rows_have_snapshot_context(self):
        """Each stock row must carry snapshotId, type, tradingDate, etc."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        for row in result["stockRows"]:
            assert row["snapshotId"] == "half_hour:2026-06-11:15:00"
            assert row["type"] == "half_hour"
            assert row["tradingDate"] == "2026-06-11"
            assert row["captureMode"] == "real_time"
            assert row["source"] == "quantboard_backend_collector"

    def test_sector_rows_have_snapshot_context(self):
        """Each sector row must carry snapshotId, type, tradingDate, etc."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        result = build_ingest_payload(slot, ctx)
        for row in result["sectorRows"]:
            assert row["snapshotId"] == "half_hour:2026-06-11:15:00"
            assert row["type"] == "half_hour"
            assert row["tradingDate"] == "2026-06-11"
            assert row["captureMode"] == "real_time"
            assert row["source"] == "quantboard_backend_collector"


# ── Normalizer compatibility ─────────────────────────────────────────────────


class TestNormalizerCompatibility:
    """Verify the builder output is accepted by the ingest normalizer."""

    def test_normalizer_accepts_output(self):
        """normalize_snapshot_ingest() must accept the builder output
        without raising an error."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        bundle = build_ingest_payload(slot, ctx)

        request = SnapshotIngestRequest(
            datasetId=bundle["datasetId"],
            bundle=bundle,
            source=bundle["source"],
        )

        result = normalize_snapshot_ingest(request)
        dataset, records, frames, stock_rows, sector_rows, idempotency_key = result

        # Verify the normalizer produced non-empty results
        assert len(records) == 1
        assert len(frames) == 1
        assert len(stock_rows) == 2
        assert len(sector_rows) >= 1
        assert len(idempotency_key) > 0

        # Dataset carries correct identity
        assert dataset.id == "dragonboard_backend_shadow"

        # Records carry the right identity
        assert records[0]["id"] == "half_hour:2026-06-11:15:00"

    def test_normalizer_rejects_empty_stock_rows(self):
        """normalizer must reject a bundle with no hotlist stock records."""
        from backend.data.schemas import SnapshotIngestRequest as Sir

        slot = make_slot_1500()
        ctx = MarketDataContext()  # empty context
        bundle = build_ingest_payload(slot, ctx)

        request = Sir(
            datasetId=bundle["datasetId"],
            bundle=bundle,
            source=bundle["source"],
        )

        with pytest.raises(ValueError, match="hotlist"):
            normalize_snapshot_ingest(request)

    def test_normalizer_with_delayed_mode(self):
        """normalizer must accept delayed capture payloads."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        bundle = build_ingest_payload(slot, ctx, capture_mode="delayed")

        request = SnapshotIngestRequest(
            datasetId=bundle["datasetId"],
            bundle=bundle,
            source=bundle["source"],
        )

        result = normalize_snapshot_ingest(request)
        _, records, frames, stock_rows, _, _ = result
        assert records[0]["captureMode"] == "delayed"
        for frame in frames:
            assert frame["captureMode"] == "delayed"


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestBuilderEdgeCases:
    """Edge cases and robustness."""

    def test_empty_context_produces_structure(self):
        """An empty MarketDataContext should still produce a valid
        bundle structure (normalizer will then reject it for missing
        hotlist — that is the normalizer's job)."""
        slot = make_slot_1500()
        ctx = MarketDataContext()
        result = build_ingest_payload(slot, ctx)
        assert result["datasetId"] == "dragonboard_backend_shadow"
        assert result["snapshotId"] == "half_hour:2026-06-11:15:00"
        assert len(result["items"]) == 1
        assert len(result["frames"]) == 1
        assert len(result["stockRows"]) == 0
        assert len(result["sectorRows"]) == 0

    def test_stock_without_code_is_skipped(self):
        """Stocks missing a code field must not appear in stockRows."""
        slot = make_slot_1500()
        ctx = MarketDataContext(
            stocks=[
                {"name": "NoCode", "rank": 1},
                {"code": "000001", "name": "平安银行", "rank": 2},
            ]
        )
        result = build_ingest_payload(slot, ctx)
        assert len(result["stockRows"]) == 1
        assert result["stockRows"][0]["code"] == "000001"

    def test_sector_without_code_uses_name(self):
        """A sector missing code should use its name as entityKey."""
        slot = make_slot_1500()
        ctx = MarketDataContext(
            stocks=[],
            sectors=[
                {"name": "银行", "entityType": "sector", "rank": 1},
            ],
        )
        result = build_ingest_payload(slot, ctx)
        assert len(result["sectorRows"]) == 1
        assert result["sectorRows"][0]["entityKey"] == "银行"

    def test_builder_preserves_all_valid_snapshot_types(self):
        """Builder correctly uses each valid snapshot_type supplied by the slot
        (validation of the type itself belongs to SnapshotSlot.__post_init__)."""
        import datetime
        from zoneinfo import ZoneInfo

        tz_shanghai = ZoneInfo("Asia/Shanghai")

        for st in ("quarter_hour", "half_hour", "hourly", "daily"):
            dt = datetime.datetime(2026, 6, 11, 15, 0, tzinfo=tz_shanghai)
            slot = SnapshotSlot(
                snapshot_type=st,
                trading_date="2026-06-11",
                slot_time="15:00",
                timestamp_ms=int(dt.timestamp() * 1000),
            )
            ctx = make_fake_context()
            result = build_ingest_payload(slot, ctx)
            assert result["snapshotId"] == f"{st}:2026-06-11:15:00"
            assert result["items"][0]["type"] == st
            assert result["frames"][0]["type"] == st


# ═════════════════════════════════════════════════════════════════════════════
# Quote and money-flow enrichment tests
# ═════════════════════════════════════════════════════════════════════════════


class TestEnrichStockRowsFromQuotes:
    """Unit tests for _enrich_stock_rows_from_quotes."""

    def test_ignores_empty_quotes_and_money_flow(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        _enrich_stock_rows_from_quotes(rows, [], [])
        assert "pe" not in rows[0]
        assert "moneyFlow" not in rows[0]

    def test_fills_missing_price_from_quote(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        quotes = [
            {
                "code": "000001",
                "price": 12.50,
                "pctChange": 2.35,
                "amount": 1875000000.0,
                "turnover": 5.5,
                "volumeRatio": 12.22,
            }
        ]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["price"] == 12.50
        assert rows[0]["pctChange"] == 2.35
        assert rows[0]["change"] == 2.35
        assert rows[0]["turnover"] == 1875000000.0
        assert rows[0]["turnoverRate"] == 5.5
        assert rows[0]["volumeRatio"] == 12.22

    def test_fills_zero_price_from_quote(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1, "price": 0}]
        quotes = [{"code": "000001", "price": 12.50}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["price"] == 12.50

    def test_fills_degraded_name_from_quote(self) -> None:
        rows = [{"code": "000001", "name": "000001", "rank": 1}]
        quotes = [{"code": "000001", "name": "平安银行"}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["name"] == "平安银行"

    def test_build_payload_preserves_explicit_turnover_rate(self) -> None:
        from backend.snapshot_collector.builder import build_ingest_payload
        from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot

        slot = SnapshotSlot("half_hour", "2026-06-11", "10:00", 1781143200000)
        context = MarketDataContext(
            stocks=[
                {
                    "code": "000001",
                    "name": "平安银行",
                    "rank": 1,
                    "pctChange": 2.5,
                    "amount": 125000000.0,
                    "turnover": 125000000.0,
                    "turnoverRate": 3.2,
                    "heat": 88.0,
                }
            ]
        )

        row = build_ingest_payload(slot, context)["stockRows"][0]

        assert row["turnover"] == 125000000.0
        assert row["turnoverRate"] == 3.2

    def test_does_not_overwrite_existing_non_zero_price(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1, "price": 13.00}]
        quotes = [{"code": "000001", "price": 12.50}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["price"] == 13.00

    def test_adds_pe_and_total_market_value(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        quotes = [{"code": "000001", "pe": 8.5, "totalMarketValue": 350000000000.0}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["pe"] == 8.5
        assert rows[0]["totalMarketValue"] == 350000000000.0

    def test_skips_pe_when_none(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        quotes = [{"code": "000001"}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert "pe" not in rows[0]

    def test_adds_money_flow_as_structured_dict(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        money_flow = [
            {
                "code": "000001",
                "mainNetInflow": 50000000.0,
                "superLargeNetInflow": 20000000.0,
                "largeNetInflow": 15000000.0,
                "mediumNetInflow": 5000000.0,
                "smallNetInflow": 10000000.0,
            }
        ]
        _enrich_stock_rows_from_quotes(rows, [], money_flow)
        assert rows[0]["moneyFlow"] == {
            "mainNetInflow": 50000000.0,
            "superLargeNetInflow": 20000000.0,
            "largeNetInflow": 15000000.0,
            "mediumNetInflow": 5000000.0,
            "smallNetInflow": 10000000.0,
        }

    def test_code_mismatch_does_not_cross_assign(self) -> None:
        rows = [
            {"code": "000001", "name": "平安银行", "rank": 1},
            {"code": "600000", "name": "浦发银行", "rank": 2},
        ]
        quotes = [{"code": "000001", "price": 12.50}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert rows[0]["price"] == 12.50
        assert "price" not in rows[1]

    def test_skips_row_without_code(self) -> None:
        rows = [{"name": "NoCode", "rank": 1}]
        quotes = [{"code": "000001", "price": 12.50}]
        _enrich_stock_rows_from_quotes(rows, quotes, [])
        assert "price" not in rows[0]

    def test_quotes_and_money_flow_together(self) -> None:
        rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
        quotes = [{"code": "000001", "price": 12.50, "pe": 8.5, "totalMarketValue": 350000000000.0}]
        money_flow = [{"code": "000001", "mainNetInflow": 50000000.0}]
        _enrich_stock_rows_from_quotes(rows, quotes, money_flow)
        assert rows[0]["price"] == 12.50
        assert rows[0]["pe"] == 8.5
        assert rows[0]["totalMarketValue"] == 350000000000.0
        assert rows[0]["moneyFlow"] is not None


class TestBuilderWithEnrichment:
    """Integration: build_ingest_payload with quotes and money_flow in the context."""

    def test_enrichment_applied_in_full_pipeline(self) -> None:
        """Verify that quotes and money_flow enrich the stock rows in build_ingest_payload."""
        slot = make_slot_1500()
        ctx = make_fake_context()

        # Add money_flow to the context (not present in make_fake_context)
        ctx.money_flow = [
            {
                "code": "000001",
                "mainNetInflow": 50000000.0,
                "superLargeNetInflow": 20000000.0,
                "largeNetInflow": 15000000.0,
                "mediumNetInflow": 5000000.0,
                "smallNetInflow": 10000000.0,
            },
            {
                "code": "600000",
                "mainNetInflow": -10000000.0,
                "superLargeNetInflow": -5000000.0,
                "largeNetInflow": -3000000.0,
                "mediumNetInflow": 0.0,
                "smallNetInflow": -2000000.0,
            },
        ]

        # Add pe and totalMarketValue to the quotes
        ctx.quotes = [
            {"code": "000001", "price": 12.50, "pctChange": 2.35, "volume": 150000000,
             "pe": 8.5, "totalMarketValue": 350000000000.0},
            {"code": "600000", "price": 9.80, "pctChange": -0.51, "volume": 80000000,
             "pe": 5.2, "totalMarketValue": 180000000000.0},
        ]

        result = build_ingest_payload(slot, ctx)
        stock_rows = result["stockRows"]

        # Row 0 should have enrichment
        row0 = stock_rows[0]
        assert row0["code"] == "000001"
        assert row0["pe"] == 8.5
        assert row0["totalMarketValue"] == 350000000000.0
        assert row0["moneyFlow"]["mainNetInflow"] == 50000000.0

        # Row 1 should have enrichment
        row1 = stock_rows[1]
        assert row1["code"] == "600000"
        assert row1["pe"] == 5.2
        assert row1["totalMarketValue"] == 180000000000.0
        assert row1["moneyFlow"]["mainNetInflow"] == -10000000.0

    def test_quote_fills_missing_price_in_stock_row(self) -> None:
        """When hotlist has zero price, quote should fill it."""
        slot = make_slot_1500()
        ctx = make_fake_context()
        # Make one stock have zero price
        ctx.stocks[0]["price"] = 0
        ctx.quotes = [{"code": "000001", "price": 12.50}]

        result = build_ingest_payload(slot, ctx)
        row0 = result["stockRows"][0]
        assert row0["price"] == 12.50


class TestCanonicalSnapshotStockRowContract:
    def test_builder_emits_canonical_live_contract_aliases(self) -> None:
        from backend.snapshot_collector.builder import build_ingest_payload
        from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot

        slot = SnapshotSlot("half_hour", "2026-06-11", "10:00", 1781143200000)
        context = MarketDataContext(
            stocks=[
                {
                    "code": "000001",
                    "name": "平安银行",
                    "rank": 1,
                    "pctChange": 2.5,
                    "amount": 125000000.0,
                    "turnover": 3.2,
                    "heat": 88.0,
                }
            ],
            quotes=[{"code": "000001", "totalMarketValue": 350000000000.0}],
            money_flow=[
                {
                    "code": "000001",
                    "mainNetInflow": 50000000.0,
                    "moneyFlowSource": "estimated_l1",
                    "moneyFlowEstimated": True,
                }
            ],
        )

        row = build_ingest_payload(slot, context)["stockRows"][0]

        assert row["change"] == 2.5
        assert row["turnover"] == 125000000.0
        assert row["turnoverRate"] == 3.2
        assert row["hotness"] == 88.0
        assert row["totalMV"] == 350000000000.0
        assert row["zlje"] == 50000000.0
        assert row["moneyFlowSource"] == "estimated_l1"
        assert row["moneyFlowEstimated"] is True
