"""方案 A：当前帧 percentile 权威化单测（2026-08-23）。

根因：current_frame 的 rank/avgRankNum 是前端派生漂移值（随 zljzb/八平台热榜重算），
旧实现用 attention_rank_lookup 把它们 append 进 percentile 序列，污染横截面/趋势/周期。
修复后：current_frame 复用该 code 权威历史帧最后一个 percentile，仅标记当前帧 key。

本测试：历史帧 002279 保持权威 rank=1（高位 percentile）；current_frame 传入漂移 rank=50。
断言 currentFrame 帧的 currentPercentile ≈ 权威高位（历史 rank=1），不随前端 rank=50 漂移。
"""
import pytest
from fastapi.testclient import TestClient

from backend.data.cache import snapshot_cache
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _disable_redis(monkeypatch):
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=None, ttl_seconds=60, empty_ttl_seconds=10
        ),
    )


class FakeRepo:
    def __init__(self, frames):
        self.frames = frames

    def load_frame_bundles(self, *args, **kwargs):
        frames = list(self.frames)
        if kwargs.get("sort") == "desc":
            frames.sort(key=lambda f: int(f.get("timestamp") or 0), reverse=True)
            limit = kwargs.get("limit")
            if limit and limit > 0:
                frames = frames[:limit]
        return frames

    def dataset_to_dict(self, dataset):
        return {}


def _frame(ts, date, slot, rank):
    return {
        "tradingDate": date,
        "slotTime": slot,
        "type": "half_hour",
        "timestamp": ts,
        "rows": [{"code": "002279", "name": "久其软件", "rank": rank, "avgRankNum": float(rank)}],
        "hotlist": [],
        "stocks": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }


def _make_history():
    # 002279 历史权威：rank=1（高位 percentile）；多个交易日保证 attention 序列够长
    frames = []
    dates = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
    for i, d in enumerate(dates):
        frames.append(_frame(i + 1, d, "14:00", rank=1))
    return frames


def test_current_frame_uses_authoritative_percentile(monkeypatch):
    frames = _make_history()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    # 前端漂移 rank=50（若旧实现，会把该股 percentile 拉到高位）；权威应为 rank=1 对应的高位百分位
    payload = {
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": [f"{d} 14:00" for d in ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]],
        "currentFrame": {
            "tradingDate": "2026-08-14",
            "slotTime": "current",
            "stocks": [{
                "code": "002279",
                "rank": 50,          # 漂移 rank（综合排名重算）
                "avgRankNum": 50.0,  # 漂移 avgRankNum（八平台热榜重算）
                "change": 5.0,
                "volumeRatio": 1.5,
                "zlje": 10,
                "zljzb": 0.1,
            }],
        },
    }
    resp = client.post("/api/ranktrend/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    # 找 currentFrame 帧（slotTime == 'current'）
    cf = next((f for f in body.get("frames", []) if str(f.get("frameKey", "")) == "2026-08-14 current"), None)
    if cf is None:
        # frameKey 可能格式不同，取最后一帧
        cf = body["frames"][-1]
    assert cf is not None
    stock = next((s for s in cf.get("stocks", []) if s.get("code") == "002279"), None)
    assert stock is not None
    meta = stock.get("analysis", {}).get("meta", {})
    current_percentile = meta.get("currentPercentile")
    # 权威 rank=1（历史高位）→ percentile 应高（>60%），而非被 rank=50 拉到低位
    assert current_percentile is not None
    assert current_percentile > 60, (
        f"current_frame percentile 应反映权威高位(rank=1)，实际 {current_percentile}"
        f"（若 <60 说明仍被前端漂移 rank=50 污染）"
    )


def test_market_percentiles_attached_to_meta(monkeypatch):
    # G3：全市场帧（≥20 只 turnover>0）→ analyze 每只股票 meta 挂 marketPercentiles（后端 golden 分位）
    stocks = [
        {
            "code": f"6{i:05d}",
            "name": f"股{i}",
            "rank": i + 1,
            "avgRankNum": float(i + 1),
            "change": 1.0,
            "volumeRatio": float(i + 1),
            "zlje": 1000.0,
            "zljzb": 0.1,
            "turnover": float(i + 1),
            "turnoverRate": float(i + 1),
        }
        for i in range(22)
    ]
    frames = []
    for idx, (d, slot) in enumerate([("2026-08-13", "14:00"), ("2026-08-14", "14:00")]):
        frames.append({
            "tradingDate": d, "slotTime": slot, "type": "half_hour", "timestamp": idx + 1,
            "rows": [{
                "code": s["code"], "name": s["name"], "rank": s["rank"], "avgRankNum": s["avgRankNum"],
                "turnover": s["turnover"], "volumeRatio": s["volumeRatio"], "turnoverRate": s["turnoverRate"],
            } for s in stocks],
            "hotlist": [], "stocks": stocks,
            "sentiment": {"phaseName": "启动"}, "marketStats": {},
        })
    monkeypatch.setattr("backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: object())
    monkeypatch.setattr("backend.data.repositories.repository_factory.create_repository", lambda db, enable_backup=True: FakeRepo(frames))
    payload = {
        "snapshotType": "half_hour",
        "codes": [s["code"] for s in stocks],
        "frameKeys": ["2026-08-13 14:00", "2026-08-14 14:00"],
        "currentFrame": {
            "tradingDate": "2026-08-14", "slotTime": "current",
            "stocks": stocks,
        },
    }
    resp = client.post("/api/ranktrend/analyze", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    cf = body["frames"][-1]
    sample = next((s for s in cf.get("stocks", []) if s.get("code") == "600000"), None)
    assert sample is not None
    mp = (sample.get("analysis", {}).get("meta", {})).get("marketPercentiles", {})
    assert "turnoverP50" in mp and "volumeRatioP50" in mp and "turnoverRateP50" in mp
    # turnover = 1..22 → P50 应在 [10,13] 区间（22 只线性插值 ≈ 11.5）
    assert 10 <= mp["turnoverP50"] <= 13
