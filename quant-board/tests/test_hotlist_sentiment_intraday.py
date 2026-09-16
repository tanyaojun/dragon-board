# -*- coding: utf-8 -*-
"""盘中热榜情绪链路修复（2026-09-15）的两个回归防线。

背景（生产实测 09-08~09-15）：
1. 槽位文档竞态：collector 每槽落帧后**同步**算槽位情绪，而 analyze 产物由后台
   worker 异步落库（单帧 30s~2min）→ join 永远 miss，盘中槽位文档从来都是 fallback。
   修复：analyze worker 完成该帧落库后，链式重算该槽情绪文档（覆盖 collector 写的
   fallback 保底版）。
2. 盘中 EOD 坏固化：series 读口 lazy compute 只在最新交易日"无库行"时算一次；若首次
   触发落在"帧已落、analysis 未就绪"窗口，写入的 fallback EOD 全天不再重算。
   修复：最新交易日 EOD 锚定帧落后于最新帧、且最新帧 analysis 已就绪时重算；
   analysis 未就绪时保留旧文档（不降级）。
"""
from __future__ import annotations

from typing import Any

from tests.test_hotlist_sentiment_series_api import FakeMongoDb

DS = "dragonboard_live"


def _frame(slot: str, snapshot_id: str, timestamp: int) -> dict[str, Any]:
    return {
        "datasetId": DS,
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-06-05",
        "slotTime": slot,
        "timestamp": timestamp,
    }


def _stock(snapshot_id: str, code: str) -> dict[str, Any]:
    return {
        "datasetId": DS,
        "snapshotId": snapshot_id,
        "code": code,
        "name": f"股{code}",
        "rank": 1,
        "change": 5.0,
        "turnover": 8e8,
        "zlje": 1e8,
        "volumeRatio": 1.4,
    }


def _analysis(snapshot_id: str, code: str, stage: str = "ignition") -> dict[str, Any]:
    return {
        "datasetId": DS,
        "snapshotId": snapshot_id,
        "code": code,
        "analysis": {"displayStatus": {"stage": stage, "label": "点火"}},
    }


def _eod_doc(snapshot_id: str, golden: int, fallback: int) -> dict[str, Any]:
    return {
        "_id": f"{DS}:half_hour:2026-06-05",
        "datasetId": DS,
        "snapshotType": "half_hour",
        "tradingDate": "2026-06-05",
        "snapshotId": snapshot_id,
        "slotTime": "EOD",
        "stage": "启动",
        "riskLevel": "低",
        "confidence": 60,
        "summary": "预置",
        "metrics": {
            "topN": 1,
            "layers": {"all": {"stageCounts": {}}},
            "statusSourceCounts": {"displayStatus": golden, "fallback": fallback},
        },
        "turnover": {"newEntries": [], "eliminated": []},
        "signals": [],
        "warnings": [],
    }


def _seed_intraday(latest_slot: str, analysis_ready: bool) -> FakeMongoDb:
    """09:30 帧已 join 完成；10:00 为最新帧，analysis 按参数就绪/未就绪。"""
    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        _frame("09:30", "s_0930", 100),
        _frame(latest_slot, "s_1000", 200),
    ]
    db["snapshot_stock_rows"].rows = [_stock("s_0930", "000001"), _stock("s_1000", "000001")]
    db["snapshot_analysis"].rows = [_analysis("s_0930", "000001")]
    if analysis_ready:
        db["snapshot_analysis"].rows.append(_analysis("s_1000", "000001"))
    return db


def test_stale_eod_recomputed_when_latest_frame_analysis_ready():
    from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

    db = _seed_intraday("10:00", analysis_ready=True)
    # 盘中已存在的 EOD：09:30 口径（好数据，golden 命中）
    db["hotlist_sentiment"].rows = [_eod_doc("s_0930", golden=1, fallback=0)]

    items = HotListSentimentComputeService(db).ensure_series(DS, "half_hour", 1)["items"]

    doc = next(it for it in items if it.get("tradingDate") == "2026-06-05")
    assert doc["snapshotId"] == "s_1000", "EOD 应刷新到最新帧口径"
    source = doc["metrics"]["statusSourceCounts"]
    assert source["displayStatus"] == 1 and source["fallback"] == 0


def test_stale_eod_kept_when_latest_frame_analysis_not_ready():
    from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

    db = _seed_intraday("10:00", analysis_ready=False)
    db["hotlist_sentiment"].rows = [_eod_doc("s_0930", golden=1, fallback=0)]

    items = HotListSentimentComputeService(db).ensure_series(DS, "half_hour", 1)["items"]

    doc = next(it for it in items if it.get("tradingDate") == "2026-06-05")
    assert doc["snapshotId"] == "s_0930", "analysis 未就绪时保留旧文档，不降级重算"
    assert doc["metrics"]["statusSourceCounts"]["displayStatus"] == 1


def test_up_to_date_eod_not_recomputed():
    from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

    db = _seed_intraday("10:00", analysis_ready=True)
    db["hotlist_sentiment"].rows = [_eod_doc("s_1000", golden=1, fallback=0)]

    items = HotListSentimentComputeService(db).ensure_series(DS, "half_hour", 1)["items"]

    doc = next(it for it in items if it.get("tradingDate") == "2026-06-05")
    assert doc["snapshotId"] == "s_1000"
    assert not db["hotlist_sentiment"].replace_calls, "锚定帧未落后时不得重算（防写放大）"


def test_slot_sentiment_follows_analyze_in_collection_chain():
    """采集主链同步后处理：analyze 先落库、槽位情绪后计算（顺序即正确性，无异步空窗）。

    2026-09-15 重构：此前的钩子 + 后台 worker 路径让槽位情绪永远跑在 analyze 之前
    （fallback 长期化）。本用例是源码顺序契约：post-persist 链内 analyze 调用必须
    先于 compute_and_upsert_for_slot。
    """
    from pathlib import Path

    service_source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "snapshot_collector"
        / "service.py"
    ).read_text(encoding="utf-8")
    chain_start = service_source.index("def _run_post_persist_chain")
    chain_end = service_source.index("def arun_once", chain_start)
    chain_source = service_source[chain_start:chain_end]
    analyze_pos = chain_source.index("analyze_snapshot_and_persist")
    slot_pos = chain_source.index("compute_and_upsert_for_slot")
    assert analyze_pos < slot_pos, "analyze 必须先于槽位情绪（displayStatus join 才能命中）"
