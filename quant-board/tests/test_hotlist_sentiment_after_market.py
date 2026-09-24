# -*- coding: utf-8 -*-
"""盘后/回填 EOD 写口必须与 services 读口同口径（golden displayStatus join + limitSummary 市场证据）。

2026-09-15 回归：盘后任务 run_after_market_once → run_hotlist_sentiment_for_latest_day →
run_for_date 用无 join 的旧口径覆盖当日 EOD 文档（statusSourceCounts=displayStatus 0 /
fallback 236，limitEvidence.market 缺失 → 面板「全池状态结构」六格全 0、「无阶段」100%）。
读口 ensure_series 见库行不重算，坏文档当天固化。本文件守护：operations 层所有
hotlist_sentiment 写口（run_for_date / run_for_date_slots）不得再产出无 join 文档。
"""
from __future__ import annotations

from typing import Any

from tests.test_hotlist_sentiment_backfill import FakeMongoDb, stock


def _setup_db() -> FakeMongoDb:
    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s2",
            "type": "half_hour",
            "tradingDate": "2026-06-05",
            "timestamp": 200,
            "slotTime": "15:00",
            "limitSummary": {
                "continuousBoards": {"yiban": 5},
                "zhaban": {"count": 3},
                "thsPools": {"failedCount": 3},
            },
        },
    ]
    db["snapshot_stock_rows"].rows = [
        stock("s2", "000001", 1, 9.9, 500),
        stock("s2", "000003", 2, 3, 300),
    ]
    # golden analyze 产物：snapshot_analysis 带 displayStatus 投影（生产由 after-save 钩子落库）
    db["snapshot_analysis"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s2",
            "code": "000001",
            "analysis": {"displayStatus": {"stage": "ignition", "label": "点火"}},
        },
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s2",
            "code": "000003",
            "analysis": {"displayStatus": {"stage": "crowded", "label": "拥挤"}},
        },
    ]
    return db


def _eod_doc(db: FakeMongoDb) -> dict[str, Any]:
    docs = [doc for _, doc, _ in db["hotlist_sentiment"].replace_calls if doc.get("slotTime") == "EOD"]
    assert docs, "EOD 文档未被写库"
    return docs[-1]


def test_after_market_eod_joins_golden_display_status() -> None:
    from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day

    db = _setup_db()
    result = run_hotlist_sentiment_for_latest_day(
        db,
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
    )
    assert result["ok"] is True

    doc = _eod_doc(db)
    source = doc["metrics"]["statusSourceCounts"]
    assert source["displayStatus"] == 2, "golden displayStatus 必须命中全部行"
    assert source["fallback"] == 0
    stage_counts = doc["metrics"]["layers"]["all"]["stageCounts"]
    assert stage_counts["ignition"] == 1 and stage_counts["crowded"] == 1
    assert stage_counts["unknown"] == 0, "join 命中后不得再落「无阶段」兜底"
    assert not any("displayStatus" in warning for warning in doc["warnings"])


def test_after_market_eod_carries_limit_summary_market_evidence() -> None:
    from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day

    db = _setup_db()
    run_hotlist_sentiment_for_latest_day(db, dataset_id="dragonboard_live", snapshot_type="half_hour")

    doc = _eod_doc(db)
    market = doc["metrics"]["limitEvidence"]["market"]
    assert market["ztCount"] == 5, "frame.limitSummary 必须映射为全市场证据（面板顶部快捷指标）"


def test_slots_backfill_slot_and_eod_docs_join_golden_display_status() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = _setup_db()
    result = HotListSentimentBackfillService(db).run_for_date_slots(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )
    assert result["ok"] is True

    slot_docs = [doc for _, doc, _ in db["hotlist_sentiment"].replace_calls if doc.get("slotTime") == "15:00"]
    assert slot_docs, "槽位文档未被写库"
    slot_source = slot_docs[-1]["metrics"]["statusSourceCounts"]
    assert slot_source["displayStatus"] == 2 and slot_source["fallback"] == 0

    eod_doc = _eod_doc(db)
    eod_source = eod_doc["metrics"]["statusSourceCounts"]
    assert eod_source["displayStatus"] == 2 and eod_source["fallback"] == 0


def _frame(slot: str, snapshot_id: str, limit_summary: dict | None) -> dict[str, Any]:
    return {
        "datasetId": "dragonboard_live",
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-06-05",
        "timestamp": 100 if slot == "14:30" else 200,
        "slotTime": slot,
        "limitSummary": limit_summary,
    }


_EMPTY_LIMIT_SUMMARY = {"continuousBoards": None, "zhaban": None, "yesterdayZt": None, "thsPools": None}
_VALID_LIMIT_SUMMARY = {
    "continuousBoards": {"yiban": 7},
    "zhaban": {"count": 2},
    "thsPools": {"failedCount": 1},
}


def test_eod_market_evidence_falls_back_to_latest_valid_slot() -> None:
    """最新帧 limitSummary 全 null（上游涨停池接口间歇失败）→ 回退当日最近有效槽位并标注。

    fail-visible：不伪造 0，回退来源随 warnings 落库；displayStatus join 仍锚定最新帧。
    """
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        _frame("14:30", "s_1430", _VALID_LIMIT_SUMMARY),
        _frame("15:00", "s_1500", _EMPTY_LIMIT_SUMMARY),
    ]
    db["snapshot_stock_rows"].rows = [stock("s_1500", "000001", 1, 9.9, 500)]
    db["snapshot_analysis"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s_1500",
            "code": "000001",
            "analysis": {"displayStatus": {"stage": "ignition", "label": "点火"}},
        },
    ]

    result = HotListSentimentBackfillService(db).run_for_date(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )
    assert result["ok"] is True

    doc = _eod_doc(db)
    assert doc["snapshotId"] == "s_1500", "join/锚定帧必须是当日最新帧"
    market = doc["metrics"]["limitEvidence"]["market"]
    assert market["ztCount"] == 7, "市场证据应回退到 14:30 槽位"
    # 2026-09-24 诊断与业务提示分离：回退来源属数据诊断，随 diagnostics 标注（fail-visible），
    # 不再混入业务风险提示 warnings
    assert any("14:30" in item and "limitSummary" in item for item in doc["diagnostics"]), (
        "回退来源必须随 diagnostics 标注（fail-visible）"
    )
    assert all("limitSummary" not in item for item in doc["warnings"]), (
        "业务 warnings 不得混入数据回退类诊断标注"
    )


def test_eod_market_evidence_no_fallback_warning_when_latest_frame_valid() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        _frame("14:30", "s_1430", _VALID_LIMIT_SUMMARY),
        _frame("15:00", "s_1500", _VALID_LIMIT_SUMMARY),
    ]
    db["snapshot_stock_rows"].rows = [stock("s_1500", "000001", 1, 9.9, 500)]
    db["snapshot_analysis"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s_1500",
            "code": "000001",
            "analysis": {"displayStatus": {"stage": "ignition", "label": "点火"}},
        },
    ]

    HotListSentimentBackfillService(db).run_for_date(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )

    doc = _eod_doc(db)
    assert doc["metrics"]["limitEvidence"]["market"]["ztCount"] == 7
    assert not any("limitSummary" in warning for warning in doc["warnings"])


def test_eod_market_evidence_missing_when_all_slots_empty() -> None:
    """全日无有效 limitSummary → 市场证据缺失可见，不得伪造数值。"""
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        _frame("14:30", "s_1430", _EMPTY_LIMIT_SUMMARY),
        _frame("15:00", "s_1500", _EMPTY_LIMIT_SUMMARY),
    ]
    db["snapshot_stock_rows"].rows = [stock("s_1500", "000001", 1, 9.9, 500)]
    db["snapshot_analysis"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s_1500",
            "code": "000001",
            "analysis": {"displayStatus": {"stage": "ignition", "label": "点火"}},
        },
    ]

    HotListSentimentBackfillService(db).run_for_date(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )

    doc = _eod_doc(db)
    market = doc["metrics"]["limitEvidence"]["market"]
    assert market.get("ztCount") in (None, 0), "缺失透传，不伪造"

