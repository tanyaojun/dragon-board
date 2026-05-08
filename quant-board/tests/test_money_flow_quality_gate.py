from backend.data.quality_gate import evaluate_snapshot_quality


def test_formal_money_flow_gate_blocks_estimated_l1_rows() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:00",
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:30",
        },
    ]
    stock_rows = [
        {
            "snapshotId": "s1",
            "rowId": "s1-000001",
            "code": "000001",
            "price": 10,
            "change": 1,
            "volume": 100,
            "turnover": 1000,
            "turnoverRate": 1,
            "avgRankNum": 1,
            "finalConfidence": 70,
            "capitalFlowSource": "estimated_l1",
            "capitalFlowConfidence": "low",
            "moneyFlowEstimated": True,
        },
        {
            "snapshotId": "s2",
            "rowId": "s2-000001",
            "code": "000001",
            "price": 11,
            "change": 2,
            "volume": 110,
            "turnover": 1200,
            "turnoverRate": 1.2,
            "avgRankNum": 1,
            "finalConfidence": 72,
            "capitalFlowSource": "broker_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
    ]

    result = evaluate_snapshot_quality(
        frames,
        stock_rows,
        require_formal_money_flow=True,
    )

    assert result.passed is False
    assert result.severity == "fail"
    assert result.stats["estimatedL1MoneyFlowCount"] == 1
    assert result.stats["formalMoneyFlowCoverageRatio"] == 0.5
    assert any("estimated_l1 money flow blocked" in issue for issue in result.issues)


def test_formal_money_flow_gate_passes_broker_l2_rows() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
        },
    ]
    stock_rows = [
        {
            "snapshotId": "s1",
            "code": "000001",
            "price": 10,
            "volume": 100,
            "capitalFlowSource": "broker_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
        {
            "snapshotId": "s2",
            "code": "600000",
            "price": 12,
            "volume": 120,
            "capitalFlowSource": "official_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
    ]

    result = evaluate_snapshot_quality(
        frames,
        stock_rows,
        require_formal_money_flow=True,
    )

    assert result.passed is True
    assert result.stats["formalMoneyFlowCoverageRatio"] == 1
