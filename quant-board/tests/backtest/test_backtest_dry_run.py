from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.storage.test_mongo_research_repository import FakeMongoDatabase


def _seed_frames_with_signals(db: FakeMongoDatabase) -> None:
    """72 帧 × 8 股（带 avgRankNum/市场字段/价格 bar），保证默认链路能产生 signals 与 trades。"""
    frames = []
    stock_rows = []
    slots = ("09:30", "10:00", "10:30", "11:00", "13:30", "14:00", "14:30", "15:00")
    for index in range(72):
        day = index // 36 + 1
        snapshot_id = f"s{index}"
        timestamp = 1_778_520_000 + index * 1_800
        frames.append(
            {
                "datasetId": "ds_dry",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": f"2026-05-{11 + day:02d}",
                "slotTime": slots[index % 8],
                "timestamp": timestamp,
                "captureMode": "real_time",
                "stockRowCount": 8,
                "marketContext": {
                    "payload": {
                        "sentiment": {"phaseName": "发酵期"},
                        "marketData": {"ztCount": 42, "dtCount": 1, "upCount": 3200, "downCount": 900},
                    }
                },
            }
        )
        for rank in range(1, 9):
            # 000001 前段沉寂、第 35 帧排名跳升（触发 rank jump→点火→扩散入场），
            # 000008 逐步走弱（反转路径），其余震荡
            if rank == 1:
                avg_rank_num = 15.0 + (index % 3) if index < 35 else 2.0 + (index % 2) * 0.5
                change = 4.0 + (index % 2)
            elif rank == 8:
                avg_rank_num = 2.0 + index * 0.2
                change = 5.0 - index * 0.1
            else:
                avg_rank_num = rank + (index % 7) * 0.5
                change = ((index * rank) % 9) - 4
            close = 10 + rank + index * 0.1
            stock_rows.append(
                {
                    "datasetId": "ds_dry",
                    "snapshotId": snapshot_id,
                    "timestamp": timestamp,
                    "rank": rank,
                    "code": f"00000{rank}",
                    "name": f"stock-{rank}",
                    "avgRankNum": avg_rank_num,
                    "price": close,
                    "close": close,
                    "high": close + 0.1,
                    "low": close - 0.1,
                    "change": change,
                    "changePct": change,
                    "volumeRatio": 1.2 + (index % 4) * 0.3,
                    "zlje": 800 + rank * 100 + index * 10,
                    "zljzb": 0.8 + (rank % 3) * 0.4,
                    "volume": 10000 + rank,
                    "amount": 100000 + rank,
                    "moneyFlowSource": "formal",
                    "moneyFlowConfidence": 1,
                }
            )
    db["snapshot_frames"].insert_many(frames, ordered=False)
    db["snapshot_stock_rows"].insert_many(stock_rows, ordered=False)


def _make_service(monkeypatch):
    import backend.data.repositories.repository_factory as factory
    import backend.services as services

    db = FakeMongoDatabase()
    _seed_frames_with_signals(db)
    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr(services, "storage_source_label", lambda: "mongodb")
    return db, services.BacktestService(None)


_PAYLOAD = {"datasetId": "ds_dry", "snapshotType": "half_hour", "enableTradeSimulation": True}


def test_dry_run_skips_persistence_and_returns_full_trades(monkeypatch) -> None:
    db, service = _make_service(monkeypatch)

    response = service.run_ranktrend({**_PAYLOAD, "dryRun": True})

    # 跳过五表落库（run/trades/equity/signals/quality）
    assert db["backtest_runs"].count_documents({}) == 0
    assert db["backtest_trades"].count_documents({}) == 0
    assert db["backtest_equity_curve"].count_documents({}) == 0
    assert db["backtest_signals"].count_documents({}) == 0
    assert db["backtest_quality_reports"].count_documents({}) == 0
    # 响应自带全量 trades/equityCurve 供归因（不落库 → 分析脚本从响应体取）
    assert response.get("dryRun") is True
    assert isinstance(response.get("trades"), list)
    assert len(response["trades"]) >= 1, "种子帧应产生至少一笔成交，否则等价断言退化为空对空"
    assert response.get("equityCurve")
    assert len(response["trades"]) == len(response["result"].get("trades") or [])
    assert any("dry" in note.lower() for note in response.get("notes") or [])
    # 旧「已落库」措辞不得出现在 dry-run 摘要
    assert all("已落库" not in note for note in response.get("notes") or [])


def test_default_path_still_persists_when_dry_run_absent(monkeypatch) -> None:
    db, service = _make_service(monkeypatch)

    response = service.run_ranktrend(dict(_PAYLOAD))

    assert not response.get("dryRun")
    assert db["backtest_runs"].count_documents({}) == 1
    # 对称证据：默认路径五表齐全（dry 侧断言的是同集合零写入）
    assert db["backtest_trades"].count_documents({}) >= 1
    assert db["backtest_equity_curve"].count_documents({}) >= 1
    assert db["backtest_signals"].count_documents({}) >= 1
    assert db["backtest_quality_reports"].count_documents({}) >= 1
    assert response["runId"]
    # 默认路径保持既有契约：摘要声明完整结果已落库
    assert response.get("notes") and any("已落库" in note for note in response["notes"])


def test_dry_run_trades_match_persisted_run_bit_for_bit(monkeypatch) -> None:
    _db, service = _make_service(monkeypatch)

    captured: dict[str, dict] = {}
    original_summary = service._summary_response

    def _spy_summary(run_id, result, metadata=None, **kwargs):
        captured["result"] = result
        return original_summary(run_id, result, metadata, **kwargs)

    service._summary_response = _spy_summary
    service.run_ranktrend(dict(_PAYLOAD))
    persisted_trades = (captured["result"].get("tradeSimulation") or {}).get("trades") or []

    dry = service.run_ranktrend({**_PAYLOAD, "dryRun": True})

    assert dry["trades"] == persisted_trades


def test_dry_run_skips_result_json_serialization(monkeypatch) -> None:
    import backend.services.backtest_service as backtest_service_module

    _db, service = _make_service(monkeypatch)

    def _forbidden(*args, **kwargs):
        raise AssertionError("dry_run 不应触发 dumps_json_field 大序列化")

    monkeypatch.setattr(backtest_service_module, "dumps_json_field", _forbidden)
    response = service.run_ranktrend({**_PAYLOAD, "dryRun": True})
    assert response.get("dryRun") is True
