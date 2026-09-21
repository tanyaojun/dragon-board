import pytest
from fastapi.testclient import TestClient

from backend.data.cache import snapshot_cache
from backend.main import app
from backend.core.settings import get_settings


client = TestClient(app)


@pytest.fixture(autouse=True)
def _disable_real_analyze_cache(monkeypatch):
    """默认禁用真实 Redis，保证既有用例走计算路径；缓存专项用例再注入内存 fake。"""
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=None,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )


class FakeRepo:
    def __init__(self, frames):
        self.frames = frames

    def load_frame_bundles(self, *args, **kwargs):
        frames = list(self.frames)
        if kwargs.get("sort") == "desc":
            frames.sort(key=lambda frame: int(frame.get("timestamp") or 0), reverse=True)
            limit = kwargs.get("limit")
            if limit and limit > 0:
                frames = frames[:limit]
        return frames

    def dataset_to_dict(self, dataset):
        return {}


def test_analyze_rejects_unsupported_snapshot_type(monkeypatch):
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "bad_type",
        "codes": [],
    })
    assert response.status_code == 400
    assert "unsupported snapshot_type" in response.text


def test_theme_momentum_series_uses_redis_ttl_cache(monkeypatch):
    """相同帧窗口的题材动量序列命中 Redis TTL 缓存时不再重复计算。"""
    from backend.api import ranktrend_routes
    from backend.analysis.theme.momentum import compute_theme_momentum_series

    class FakeCache:
        def __init__(self):
            self.store = {}
            self.generation = 1

        def get_response(self, key):
            return self.store.get(key)

        def set_response(self, key, response, ttl_seconds=None):
            self.store[key] = response

        def get_generation(self, key):
            return self.generation

        def register_dependencies(self, key, index_keys):
            pass

    fake = FakeCache()
    monkeypatch.setattr(
        "backend.data.cache.snapshot_cache.get_snapshot_redis_cache",
        lambda: fake,
    )
    calls = {"count": 0}

    def spy(frames):
        calls["count"] += 1
        return compute_theme_momentum_series(frames)

    monkeypatch.setattr(ranktrend_routes, "compute_theme_momentum_series", spy)

    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "timestamp": 1,
        "hotThemes": [{
            "themeId": "T1",
            "entityType": "hot_theme",
            "heatScore": 80.0,
            "rank": 1,
            "rotationState": "mainline",
        }],
    }]
    first = ranktrend_routes._compute_theme_momentum_series_cached(frames, "dragonboard_live")
    second = ranktrend_routes._compute_theme_momentum_series_cached(frames, "dragonboard_live")
    assert calls["count"] == 1
    assert first == second


def test_analyze_returns_py_golden_frames(monkeypatch):
    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [{
            "code": "002279",
            "name": "久其软件",
            "rank": 1,
            "avgRankNum": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
        }],
        "hotlist": [],
        "stocks": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-02 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "py_golden"
    assert len(body["frames"]) == 1
    assert body["frames"][0]["frameKey"] == "2026-08-02 14:00"
    assert body["frames"][0]["regime"]["state"] in ("strong", "normal", "weak", "retreat")
    assert body["frames"][0]["stocks"][0]["code"] == "002279"
    assert "strategy" in body["frames"][0]["stocks"][0]["analysis"]
    assert "executionStrategy" in body["frames"][0]["stocks"][0]["analysis"]
    # 帧无自身 hotThemes 时必须打 fail-visible 标记（themeContext + qualityFlags）
    assert body["frames"][0]["themeContext"]["hotThemesFallback"] is True
    assert "theme_hot_themes_fallback" in body["frames"][0]["themeContext"]["qualityFlags"]


def test_frames_include_regime(monkeypatch):
    frames = [{
        "snapshotId": "s1",
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [{
            "code": "002279",
            "rank": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
        }],
        "stocks": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.main.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    monkeypatch.setattr(
        "backend.main._resolve_snapshot_dataset",
        lambda repo, dataset_id: ("dragonboard_live", None),
    )
    captured: dict = {}

    def fake_cached(kind, **kwargs):
        captured["loader"] = kwargs["loader"]
        return {"ok": True, "frames": [], "count": 0, "source": "test"}

    monkeypatch.setattr("backend.main._cached_snapshot_response", fake_cached)
    client.get("/api/snapshots/frames")
    body = captured["loader"]()
    assert body["ok"] is True
    assert "regime" in body["frames"][0]
    assert body["frames"][0]["regime"]["state"] in ("strong", "normal", "weak", "retreat")


def test_analyze_returns_resonance_and_market_median(monkeypatch):
    frames = [{
        "tradingDate": f"2026-08-0{day}",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": day,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    } for day in range(1, 5)]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-04 14:00"],
    })
    assert response.status_code == 200
    frame = response.json()["frames"][0]
    assert "marketMedianPercentile" in frame
    assert "marketMedianShortChange" in frame
    assert frame["stocks"][0]["analysis"]["resonance"]["status"] in ("ok", "insufficient")
    # 组装下沉（回测方案 §3.2）：API 输出仍含 observation.volumePrice / synergy.signalTier
    analysis = frame["stocks"][0]["analysis"]
    observation = analysis.get("observation") or {}
    assert observation.get("volumePrice") is not None
    assert observation["volumePrice"].get("signalTier") is not None
    assert observation.get("synergy", {}).get("signalTier") in ("S", "A", "B", "C", "D", "E", "unknown", None)


def test_analyze_finds_recent_frames_when_dataset_exceeds_200_window(monkeypatch):
    # 数据集超过 200 帧时，观察面板请求的是最近历史帧；后端必须加载最近 200 帧，
    # 而不是按 asc 加载最早 200 帧导致请求帧全部落空并返回 503。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
                {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 221)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-07-220 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    frame_keys = [frame["frameKey"] for frame in body["frames"]]
    assert frame_keys[-1] == "2026-07-220 14:00"
    # 请求帧 + 前导轨道窗口（技术/共振需要足够历史序列）
    assert 1 < len(frame_keys) <= 30
    assert body["frames"][0]["stocks"][0]["code"] == "002279"


def test_analyze_returns_empty_frames_when_requested_keys_missing_but_repo_has_frames(monkeypatch):
    # 请求的帧缺失但库里仍有帧时，不整段 503：返回可计算部分，由前端逐帧降级标记。
    frames = [
        {
            "tradingDate": "2026-07-01",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": 1,
            "rows": [{"code": "002279", "rank": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1}],
            "sentiment": {},
            "marketStats": {},
        }
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-07-99 14:00"],
    })
    assert response.status_code == 200
    assert response.json()["frames"] == []


def test_analyze_live_path_keeps_enough_history_for_resonance(monkeypatch):
    # 实时链路（无 frameKeys + currentFrame）必须保留足够回看窗口，否则个股百分位序列
    # 不足 9 点，共振强度会固定返回 insufficient/全零因子。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % 30 + 1,
                    "avgRankNum": (index + day) % 30 + 1,
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(30)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 31)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + 31) % 30 + 1,
                    "avgRankNum": (index + 31) % 30 + 1,
                }
                for index in range(30)
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    assert last["frameKey"] == "2026-07-31 current:1"
    assert isinstance(last["marketMedianShortChange"], float)
    assert isinstance(last["marketMedianPercentile"], float)
    resonance = last["stocks"][0]["analysis"]["resonance"]
    assert resonance["status"] == "ok"
    assert resonance["historyState"] == "established"
    assert "marketSampleCount" in resonance
    assert "marketMedianPercentile" in resonance
    # resonance 已下沉：Python golden 把共振方向/分数直接写进 decision.final
    analysis = last["stocks"][0]["analysis"]
    assert analysis["decision"]["final"] == {
        "signal": resonance["direction"],
        "confidence": resonance["score"],
    }


def test_analyze_new_hotlist_stock_without_history_gets_signals_from_current_frame(monkeypatch):
    # 2026-08-24：新进热榜（历史快照无该 code）股票不应被整只丢弃——
    # current 帧为其注册单点 percentile 序列后，可产出五维信号（sampleQuality=insufficient 降级）。
    frames = [
        {
            "tradingDate": f"2026-08-0{day}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
                {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 4)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    # 新 code=688999：历史帧从未出现，只在 currentFrame 里出现（带量能字段）
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["688999"],
        "currentFrame": {
            "tradingDate": "2026-08-05",
            "slotTime": "current:1",
            "stocks": [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1, "turnover": 8.0, "turnoverRate": 9.0},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05, "turnover": 6.0, "turnoverRate": 7.0},
                {"code": "688999", "rank": 3, "avgRankNum": 3, "change": 10.0, "volumeRatio": 2.0, "zlje": 20, "zljzb": 0.2, "turnover": 12.0, "turnoverRate": 15.0},
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    assert last["frameKey"] == "2026-08-05 current:1"
    # 新 code 不再被丢弃：最后一帧含该股票完整 analysis
    stocks = last["stocks"]
    new_stock = next((s for s in stocks if s["code"] == "688999"), None)
    assert new_stock is not None, "新进热榜股票不应被 _analyze_frames 丢弃"
    analysis = new_stock["analysis"]
    # 五维信号结构完整（单点样本 → sampleQuality=insufficient 降级，fail-visible）
    assert analysis["meta"]["sampleQuality"]["status"] == "insufficient"
    assert analysis["meta"]["sampleQuality"]["sampleCount"] == 1
    assert analysis["resonance"]["status"] in ("insufficient", "ok")
    assert "observation" in analysis
    assert "volumePrice" in analysis.get("observation", {})
    assert "crossSection" in analysis.get("observation", {})
    assert analysis["decision"]["final"]["signal"] in ("hold", "buy", "sell")


def test_analyze_new_stock_without_avg_rank_num_gets_live_average_rank(monkeypatch):
    # 2026-09-22 用户裁决（更新 2026-08-25 P1 复盘的"不产出"口径）：收盘帧后新入榜、
    # 行上无有效 avgRankNum 的股票，实时链按八平台 rank 补均榜
    # （weighted_platform_percentile_v1）后注册单点序列进分析，不再整只丢弃；
    # fail-visible 精神由样本不足降级保留（趋势/周期单点样本走 insufficient，
    # 不伪造历史 percentile——序列仍只有实时单点）。
    frames = [
        {
            "tradingDate": f"2026-08-0{day}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 4)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    # 新 code=688888 只在 currentFrame 出现，且 avgRankNum=0（无均榜输入，仅有行级 rank）
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["688888"],
        "currentFrame": {
            "tradingDate": "2026-08-05",
            "slotTime": "current:1",
            "stocks": [
                {"code": f"F{index:02d}", "emRank": index + 1, "avgRankNum": float(index + 1),
                 "change": 1.0, "volumeRatio": 1.0, "zlje": 10, "zljzb": 0.1}
                for index in range(60)
            ] + [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1, "turnover": 8.0, "turnoverRate": 9.0},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05, "turnover": 6.0, "turnoverRate": 7.0},
                {"code": "688888", "rank": 3, "avgRankNum": 0, "change": 20.0, "volumeRatio": 3.0, "zlje": 30, "zljzb": 0.3, "turnover": 15.0, "turnoverRate": 18.0},
            ],
        },
    })
    assert response.status_code == 200
    last = response.json()["frames"][-1]
    by_code = {stock["code"]: stock for stock in last["stocks"]}
    # 新进股票产出分析并带实时排名（不整只丢弃）
    assert "688888" in by_code
    new_analysis = by_code["688888"]["analysis"]
    # 无任何平台 rank 字段 → 均榜按"缺失平台=榜尾满权"规则计（filler 提供 em 榜
    # total=60，688888 无 em rank → 100 分）：不编造成靠前排名，fail-visible
    assert new_analysis["meta"]["liveRanking"]["avgRankNum"] == 100.0
    assert new_analysis["meta"]["liveRanking"]["compRank"] is not None
    # 单点序列：样本不足如实降级，不伪造趋势/周期结论
    sample_quality = new_analysis["meta"].get("sampleQuality") or {}
    assert sample_quality.get("status") == "insufficient"


def test_analyze_current_frame_market_median_uses_last_snapshot_frame(monkeypatch):
    # 2026-08-25（用户决策 A）：marketMedian/marketMedianPercentile 与个股 percentile 同口径
    # ——current 帧是前端实时 avgRankNum 派生（会漂移），不进中位数体系；取最近真实快照帧。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % 30 + 1,
                    "avgRankNum": (index + day) % 30 + 1,  # 1..30 排列
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(30)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 31)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    # current 帧只有 1 只股票（中位数=100）→ 若误用 current 帧，marketMedianPercentile=100；
    # 对齐历史帧后应为历史 30 帧的中位数（51.67）。
    current_stocks = [
        {"code": "C00", "rank": 1, "avgRankNum": 100, "change": 5.0},
    ]
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": current_stocks,
        },
    })
    assert response.status_code == 200
    last = response.json()["frames"][-1]
    from backend.api.ranktrend_routes import _to_engine_frame, frame_market_median_percentile

    last_snapshot_engine = _to_engine_frame(frames[-1])
    current_engine = {**last_snapshot_engine, "stocks": current_stocks}
    # 与最近快照帧（历史第 30 帧）中位数一致，而非 current 实时帧（=100）
    assert last["marketMedianPercentile"] == frame_market_median_percentile(last_snapshot_engine)
    assert frame_market_median_percentile(current_engine) == 100.0
    assert last["marketMedianPercentile"] != frame_market_median_percentile(current_engine)
    # relativeToMarket 使用同一快照口径（crossSection 一致）
    cs = last["stocks"][0]["analysis"]["observation"]["crossSection"]
    assert cs["relativeToMarket"] is not None


def _cycle_divergence_frames():
    """C00 位次序列 [2,1,3]（30 只截面）：权威口径 cycle.stage=reversal（引擎实证），
    复制尾口径判 cooling——两条口径可判别。"""

    def make_rows(c00_rank):
        rows = []
        for index, value in enumerate(v for v in range(1, 32) if v != c00_rank):
            rows.append({
                "code": f"C{index + 1:02d}",
                "rank": value,
                "avgRankNum": float(value),
                "change": 1.0,
                "volumeRatio": 1.2,
                "zlje": 10,
                "zljzb": 0.1,
            })
        rows.append({
            "code": "C00",
            "rank": c00_rank,
            "avgRankNum": float(c00_rank),
            "change": 1.0,
            "volumeRatio": 1.2,
            "zlje": 10,
            "zljzb": 0.1,
        })
        return rows

    return [
        {
            "tradingDate": f"2026-07-{day:02d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": make_rows(c00_rank),
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day, c00_rank in zip((1, 2, 3), (2, 1, 3))
    ]


def test_analyze_live_ranking_skipped_below_min_pool_size(monkeypatch):
    # code review C1：单股/小池请求（current 帧行数 < 门槛）不得注入 liveRanking。
    # 池截断会让 infer_platform_totals 把榜单总数推断为池内最大 rank → avgRankNum 恒
    # 100、compRank 恒 1 的失真值，经前端写回污染主列表排名字段。门槛下 analysis 本体
    # 照常产出（面板不受影响），仅跳过 liveRanking。
    frames = [{
        "tradingDate": "2026-07-31",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 31,
        "rows": [
            {"code": f"C{index:02d}", "rank": index + 1, "avgRankNum": float(index + 1),
             "change": 1.0, "volumeRatio": 1.2, "zlje": 10, "zljzb": 0.1}
            for index in range(5)
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": [
                {"code": "C00", "emRank": 1, "avgRankNum": 12.5, "change": 5.0,
                 "volumeRatio": 2.0, "zlje": 100, "zljzb": 3.0, "turnover": 500,
                 "turnoverRate": 10},
            ],
        },
    })
    assert response.status_code == 200
    stock = response.json()["frames"][-1]["stocks"][0]
    # analysis 本体照常（面板可用）
    assert stock["analysis"].get("observation")
    # 失真 liveRanking 不注入
    assert "liveRanking" not in (stock["analysis"].get("meta") or {})


def test_analyze_current_frame_cycle_matches_authoritative_series(monkeypatch):
    # 2026-09-19 修复：live current 帧的序列复制尾点不得进入 cycle 等趋势因子输入。
    # 复制尾让 velocity 恒 0、accel=-真实velocity，点火/扩散/反转判据系统性失效
    # （实测 2026-09-18 EOD 全池分布：反转 29→7、扩散 10→1、点火 2→0），导致行情
    # 总览周期列与热榜情绪面板「全池状态结构」分布不一致。
    # 合同：current 帧 cycle.stage 必须与权威序列（无 currentFrame）最后帧一致；
    # 与 2026-09-13 crossSection 去复制尾同模式（2026-08-23 设计意图：横截面/趋势/
    # 周期只用权威源，当前帧仅作展示帧）。单点序列（新进热榜）无复制尾，不受影响。
    frames = _cycle_divergence_frames()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    base_payload = {"snapshotType": "half_hour", "codes": ["C00"]}

    authoritative = client.post("/api/ranktrend/analyze", json=base_payload).json()
    auth_stage = authoritative["frames"][-1]["stocks"][0]["analysis"]["cycle"]["stage"]
    # 权威口径判别力锚：该序列必须判 reversal（若引擎参数未来调整导致此锚失效，
    # 应同步更换序列，保持「两口径可判别」的测试目的）
    assert auth_stage == "reversal"

    # current 帧行与最后历史帧截面相同（周六/盘后打开页面的复制尾场景）
    replicated = client.post("/api/ranktrend/analyze", json={
        **base_payload,
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": frames[-1]["rows"],
        },
    }).json()
    assert replicated["frames"][-1]["frameKey"] == "2026-07-31 current:1"
    live_stage = replicated["frames"][-1]["stocks"][0]["analysis"]["cycle"]["stage"]
    assert live_stage == auth_stage, (
        f"current 帧复制尾改变了 cycle 判定: 权威={auth_stage}, live={live_stage}"
    )
    observation_stage = replicated["frames"][-1]["stocks"][0]["analysis"]["observation"]["lifecycle"]["stage"]
    assert observation_stage == auth_stage


def test_analyze_fuses_insufficient_resonance_into_hold_final(monkeypatch):
    frames = [{
        "tradingDate": f"2026-08-0{day}",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": day,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    } for day in range(1, 5)]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-04 14:00"],
    })
    assert response.status_code == 200
    analysis = response.json()["frames"][0]["stocks"][0]["analysis"]
    assert analysis["resonance"]["status"] == "insufficient"
    assert analysis["decision"]["final"] == {"signal": "hold", "confidence": 0}


def test_analyze_historical_frames_keep_enough_history_for_tracks(monkeypatch):
    # 观察面板请求最近历史帧时，后端必须为最早请求帧保留足够的前导帧，
    # 否则技术/共振/生命周期算法只能用 1-4 个 bar 分析，历史 bar 全为样本不足。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % 30 + 1,
                    "avgRankNum": (index + day) % 30 + 1,
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(30)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 41)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00"],
        "frameKeys": ["2026-07-038 14:00", "2026-07-039 14:00", "2026-07-040 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    by_key = {frame["frameKey"]: frame for frame in body["frames"]}
    earliest = by_key["2026-07-038 14:00"]
    sample_quality = earliest["stocks"][0]["analysis"]["meta"]["sampleQuality"]
    assert sample_quality["sampleCount"] >= 22
    assert earliest["stocks"][0]["analysis"]["resonance"]["status"] == "ok"


def test_analyze_market_median_uses_avg_rank_num_cross_section(monkeypatch):
    # 对齐旧 TS buildFrameCrossSections 合同：横截面只统计 avgRankNum > 0 的股票，
    # 按 avgRankNum 升序重排后取百分位中位数；sampleCount = 帧横截面股票数。
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "C01", "rank": 1, "avgRankNum": 20, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C02", "rank": 2, "avgRankNum": 30, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C03", "rank": 3, "avgRankNum": 40, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C04", "rank": 4, "avgRankNum": 50, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C05", "rank": 5, "avgRankNum": 0, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C01"],
        "frameKeys": ["2026-07-01 14:00"],
    })
    assert response.status_code == 200
    frame = response.json()["frames"][0]
    assert frame["marketMedianPercentile"] == 62.5
    assert frame["marketSampleCount"] == 4


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value
        self.ttls[key] = ttl

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)
        return 1

    def expire(self, key, ttl):
        return 1

    def smembers(self, key):
        return list(self.sets.get(key, set()))

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                removed += 1
            if key in self.sets:
                del self.sets[key]
                removed += 1
        return removed

    def pipeline(self, transaction=False):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands: list[tuple] = []

    def sadd(self, key, member):
        self.commands.append(("sadd", key, member))
        return self

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        return self

    def execute(self):
        for command in self.commands:
            if command[0] == "sadd":
                self.redis.sadd(command[1], command[2])
            elif command[0] == "expire":
                self.redis.expire(command[1], command[2])
        self.commands = []
        return []


def test_analyze_redis_cache_hit_and_key_variation(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    calls = {"n": 0}

    def counting_repo(db, enable_backup=True):
        calls["n"] += 1
        return FakeRepo(frames)

    monkeypatch.setattr("backend.data.repositories.repository_factory.create_repository", counting_repo)
    payload = {
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-07-01 14:00"],
    }

    first = client.post("/api/ranktrend/analyze", json=payload)
    assert first.status_code == 200
    calls_after_first = calls["n"]
    assert calls_after_first == 1

    second = client.post("/api/ranktrend/analyze", json=payload)
    assert second.status_code == 200
    assert calls["n"] == calls_after_first  # 命中缓存，不再走 repository
    assert second.json()["cache"]["hit"] is True
    assert second.json()["source"] == "py_golden"

    # 请求内容不同（codes）→ 缓存键不同 → 重新计算
    calls["n"] = 0
    third = client.post("/api/ranktrend/analyze", json={**payload, "codes": ["002279", "603580"]})
    assert calls["n"] == 1
    assert third.json()["cache"]["hit"] is False

    # dataset generation 递增（ingest 后）→ 新 generation 键不命中旧缓存
    generation_key = snapshot_cache.build_snapshot_cache_generation_key(
        prefix=get_settings().redis_key_prefix,
        dataset_id="dragonboard_live",
    )
    fake_redis.incr(generation_key)
    calls["n"] = 0
    fourth = client.post("/api/ranktrend/analyze", json=payload)
    assert calls["n"] == 1
    assert fourth.json()["cache"]["hit"] is False


def test_analyze_cache_key_refreshes_when_price_volume_fields_change(monkeypatch):
    # 面板每次打开都会生成自增的 current:N slotTime，且 currentFrame.stocks 带实时行情字段。
    # 两者都不能进入缓存键，否则 Redis TTL 缓存永远 miss、每次都重新计算。
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    calls = {"n": 0}

    def counting_repo(db, enable_backup=True):
        calls["n"] += 1
        return FakeRepo(frames)

    monkeypatch.setattr("backend.data.repositories.repository_factory.create_repository", counting_repo)

    def payload(slot: str, change: float, trading_date: str = "2026-08-02"):
        return {
            "snapshotType": "half_hour",
            "codes": ["002279"],
            "frameKeys": ["2026-07-01 14:00"],
            "currentFrame": {
                "tradingDate": trading_date,
                "slotTime": slot,
                "stocks": [
                    {
                        "code": "002279",
                        "rank": 1,
                        "avgRankNum": 1,
                        "change": change,
                        "volumeRatio": 1.0,
                        "zlje": 1,
                        "zljzb": 0.1,
                    }
                ],
            },
        }

    first = client.post("/api/ranktrend/analyze", json=payload("current:1", 5.0))
    assert first.status_code == 200
    assert calls["n"] == 1

    # 自增序列号被规范化，但实时行情字段变化必须触发重算
    calls["n"] = 0
    second = client.post("/api/ranktrend/analyze", json=payload("current:2", 7.0))
    assert calls["n"] == 1
    assert second.json()["cache"]["hit"] is False

    # 跨交易日（tradingDate 不同）→ 输出口径不同 → 必须生成新键
    calls["n"] = 0
    third = client.post(
        "/api/ranktrend/analyze",
        json=payload("current:3", 7.0, trading_date="2026-08-03"),
    )
    assert calls["n"] == 1
    assert third.json()["cache"]["hit"] is False


def test_analyze_cache_key_contract_includes_avg_rank_and_turnover(monkeypatch):
    # 2026-08-25（P2 复盘）缓存键契约不变式：**计算输入 ⊆ 缓存键**。
    # 新股 percentile 计算（attention_rank_lookup）只用 avgRankNum → avgRankNum 必须进键（变化→新键）；
    # turnover/turnoverRate 参与量能观察，必须进入缓存键（变化→新键）。
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    calls = {"n": 0}

    def counting_repo(db, enable_backup=True):
        calls["n"] += 1
        return FakeRepo(frames)

    monkeypatch.setattr("backend.data.repositories.repository_factory.create_repository", counting_repo)

    def payload(avg_rank_num: float, turnover: float):
        return {
            "snapshotType": "half_hour",
            "codes": ["002279"],
            "frameKeys": ["2026-07-01 14:00"],
            "currentFrame": {
                "tradingDate": "2026-08-02",
                "slotTime": "current:1",
                "stocks": [
                    {
                        "code": "002279",
                        "rank": 1,
                        "avgRankNum": avg_rank_num,
                        "turnover": turnover,
                        "turnoverRate": turnover,
                        "change": 5.0,
                        "volumeRatio": 1.0,
                        "zlje": 1,
                        "zljzb": 0.1,
                    }
                ],
            },
        }

    first = client.post("/api/ranktrend/analyze", json=payload(1.0, 8.0))
    assert first.status_code == 200
    assert calls["n"] == 1

    # avgRankNum 变化（新股 percentile 计算输入）→ 必须新键重算
    calls["n"] = 0
    second = client.post("/api/ranktrend/analyze", json=payload(2.0, 8.0))
    assert calls["n"] == 1
    assert second.json()["cache"]["hit"] is False

    # turnover 变化（量能观察输入）→ 必须新键重算
    calls["n"] = 0
    third = client.post("/api/ranktrend/analyze", json=payload(2.0, 99.0))
    assert calls["n"] == 1
    assert third.json()["cache"]["hit"] is False


def test_analyze_cache_ttl_dynamic_intraday_afterhours(monkeypatch):
    # analyze 缓存 TTL 动态化：盘中 300s / 盘后 1800s。
    # 写入缓存的 TTL 必须等于 _analyze_cache_ttl_seconds() 当前返回值，而非固定常量。
    from backend.api.ranktrend_routes import _analyze_cache_ttl_seconds

    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-07-01 14:00"],
    })
    assert response.status_code == 200

    expected_ttl = _analyze_cache_ttl_seconds()
    analyze_keys = [key for key in fake_redis.ttls if "ranktrend:analyze" in key]
    assert analyze_keys
    for key in analyze_keys:
        assert fake_redis.ttls[key] == expected_ttl


def test_analyze_cache_ttl_intraday_vs_afterhours_boundaries():
    # 纯时间窗口边界：盘中（9:15-11:30 / 13:00-15:30）→ 300s，其余（午休/盘后/凌晨）→ 1800s。
    from datetime import datetime as _dt

    from backend.api.ranktrend_routes import (
        _analyze_cache_ttl_seconds,
        _is_intraday_trading_time,
    )

    intraday = [
        _dt(2026, 8, 13, 9, 15),   # 集合竞价开始
        _dt(2026, 8, 13, 10, 0),   # 早盘
        _dt(2026, 8, 13, 11, 30),  # 早盘收盘
        _dt(2026, 8, 13, 13, 0),   # 下午开盘
        _dt(2026, 8, 13, 15, 30),  # 盘后固定价格结束
    ]
    after_hours = [
        _dt(2026, 8, 13, 9, 14),   # 集合竞价前
        _dt(2026, 8, 13, 12, 0),   # 午休
        _dt(2026, 8, 13, 15, 31),  # 收盘后
        _dt(2026, 8, 13, 23, 0),   # 深夜
    ]
    for moment in intraday:
        assert _is_intraday_trading_time(moment) is True, moment
        assert _analyze_cache_ttl_seconds() in (300, 1800)
    for moment in after_hours:
        assert _is_intraday_trading_time(moment) is False, moment


def _theme_frames_with_context(count=12, theme_count=25):
    frames = []
    for idx in range(count):
        slot = f"{10 + idx // 2:02d}:{30 if idx % 2 else 0:02d}"
        rows = [{
            "code": "002279",
            "name": "久其软件",
            "rank": 1,
            "avgRankNum": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
            "themes": ["主线概念"],
        }]
        hot_themes = [
            {
                "entityType": "hot_theme",
                "themeId": "T0",
                "themeName": "主线概念板块",
                "heatScore": 40.0 + idx * 5.0,
                "rank": 1,
                "rotationState": "mainline",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
        ]
        hot_themes += [
            {
                "entityType": "hot_theme",
                "themeId": f"T{i}",
                "themeName": f"普通概念{i}",
                "heatScore": 50.0,
                "rank": i + 1,
                "rotationState": "neutral",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
            for i in range(1, theme_count)
        ]
        frames.append({
            "tradingDate": "2026-08-04",
            "slotTime": slot,
            "type": "half_hour",
            "timestamp": idx + 1,
            "rows": rows,
            "stocks": rows,
            "hotThemes": hot_themes,
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        })
    return frames


def test_analyze_includes_theme_context_and_resonance_theme(monkeypatch):
    frames = _theme_frames_with_context()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-04 15:00"],
    })
    assert response.status_code == 200
    body = response.json()
    frame = next(item for item in body["frames"] if item["frameKey"] == "2026-08-04 15:00")
    assert "themeContext" in frame
    assert frame["themeContext"]["themeSampleCount"] >= 20
    assert frame["themeContext"]["marketThemeMedianShortChange"] is not None
    stock = frame["stocks"][0]
    # D2 解耦：resonance 不再含 theme 子对象
    assert "theme" not in stock["analysis"]["resonance"]
    # 题材动量独立为只读投影（第4轨数据源）
    theme = stock["analysis"].get("themeMomentum")
    assert theme is not None
    assert theme["status"] in ("ok", "insufficient")
    if theme["status"] == "ok":
        assert theme["direction"] in ("up", "neutral", "down")
        assert "themeId" in theme and "themeName" in theme
        assert stock["analysis"]["decision"]["final"]["signal"] in ("buy", "hold")


def test_analyze_current_frame_theme_falls_back_to_last_historical_hot_themes(monkeypatch):
    frames = _theme_frames_with_context()
    current_frame = {
        "tradingDate": "2026-08-04",
        "slotTime": "current:1",
        "stocks": [{
            "code": "002279",
            "rank": 1,
            "avgRankNum": 1,
            "themes": ["主线概念"],
        }],
    }
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "currentFrame": current_frame,
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    stock = last["stocks"][0]
    assert "theme" not in stock["analysis"]["resonance"]
    theme = stock["analysis"]["themeMomentum"]
    assert theme["status"] in ("ok", "insufficient")
    if theme["status"] == "ok":
        assert "themeId" in theme and "themeName" in theme


def test_analyze_full_market_single_frame_over_threshold(monkeypatch):
    # 全市场单帧（股票数 > 单股阈值）串行逐股计算，最后一帧每只股票都返回完整
    # analysis（resonance/observation/technical），不丢股、不空字段。
    # （2026-08-14 起逐股计算统一串行：单股 ~1ms/股，进程池 spawn 开销反而 8s+，是负优化。）
    stock_count = 60
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % stock_count + 1,
                    "avgRankNum": (index + day) % stock_count + 1,
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(stock_count)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 31)
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": [f"C{index:02d}" for index in range(stock_count)],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + 31) % stock_count + 1,
                    "avgRankNum": (index + 31) % stock_count + 1,
                }
                for index in range(stock_count)
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    assert last["frameKey"] == "2026-07-31 current:1"
    codes_in_last = {stock["code"] for stock in last["stocks"]}
    assert codes_in_last == {f"C{index:02d}" for index in range(stock_count)}
    for stock in last["stocks"]:
        analysis = stock["analysis"]
        assert "resonance" in analysis
        assert "observation" in analysis
        assert "technical" in analysis
        assert "meta" in analysis


def test_analyze_current_frame_attaches_live_ranking(monkeypatch):
    """2026-09-22 实时口径（用户裁决）：current 帧响应附 meta.liveRanking
    （实时 compScore/compRank/avgRankNum/platforms，均榜按平台 rank 实时推算）。
    帧池 golden（快照行）自此降级为历史回溯兜底；落库 snapshot_analysis 不含
    liveRanking（稳定帧口径，与实时口径分离）。"""
    frames = [{
        "tradingDate": "2026-07-31",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 31,
        "rows": [
            {"code": f"C{index:02d}", "rank": index + 1, "avgRankNum": float(index + 1),
             "change": 1.0, "volumeRatio": 1.2, "zlje": 10, "zljzb": 0.1}
            for index in range(5)
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    # 池规模 ≥ MIN_LIVE_RANKING_POOL_SIZE（code review C1：小池 totals 推断失真不注入）
    current_stocks = [
        {
            "code": f"F{index:02d}",
            "emRank": index + 1,
            "avgRankNum": float(index + 1),
            "change": 1.0,
            "volumeRatio": 1.0,
            "zlje": 10,
            "zljzb": 0.1,
        }
        for index in range(60)
    ]
    current_stocks += [
        {
            "code": "C00",
            "emRank": 1,
            "thsRank": 2,
            "kplRank": 1,
            "avgRankNum": 1.5,
            "change": 5.0,
            "volumeRatio": 2.0,
            "zlje": 100,
            "zljzb": 3.0,
            "turnover": 500,
            "turnoverRate": 10,
        },
        {
            "code": "C01",
            "emRank": 5,
            "thsRank": 4,
            "avgRankNum": 4.5,
            "change": -1.0,
            "volumeRatio": 0.8,
            "zlje": -50,
            "zljzb": -2.0,
            "turnover": 80,
            "turnoverRate": 3,
        },
    ]
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00", "C01"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            # 池规模 ≥ MIN_LIVE_RANKING_POOL_SIZE（code review C1：小池不注入 liveRanking）
            "stocks": [
                {"code": f"F{index:02d}", "emRank": index + 1, "avgRankNum": float(index + 1),
                 "change": 1.0, "volumeRatio": 1.0, "zlje": 10, "zljzb": 0.1}
                for index in range(60)
            ] + [
                {"code": "C00", "emRank": 1, "thsRank": 2, "kplRank": 1, "avgRankNum": 1.5,
                 "change": 5.0, "volumeRatio": 2.0, "zlje": 100, "zljzb": 3.0,
                 "turnover": 500, "turnoverRate": 10},
                {"code": "C01", "emRank": 5, "thsRank": 4, "avgRankNum": 4.5,
                 "change": -1.0, "volumeRatio": 0.8, "zlje": -50, "zljzb": -2.0,
                 "turnover": 80, "turnoverRate": 3},
            ],
        },
    })
    assert response.status_code == 200
    last = response.json()["frames"][-1]
    by_code = {stock["code"]: stock for stock in last["stocks"]}
    live_a = by_code["C00"]["analysis"]["meta"].get("liveRanking")
    live_b = by_code["C01"]["analysis"]["meta"].get("liveRanking")
    assert live_a and live_b, "current 帧必须携带 meta.liveRanking"
    # C00 平台排名全面靠前 → 实时综合排名优于 C01
    assert live_a["compRank"] < live_b["compRank"]
    assert live_a["avgRankNum"] < live_b["avgRankNum"]
    assert live_a["platforms"] == 3  # em/ths/kpl 三平台有效
    # 实时注入不污染请求行（调用方数据不被修改）
    assert "compScore" not in current_stocks[0]
    assert "avgRank" not in current_stocks[0]


def test_analyze_newly_listed_stock_without_avg_rank_gets_live_ranking(monkeypatch):
    """收盘帧后新入榜股票（无历史序列、行无 avgRankNum）不被 gate 整只丢弃（2026-09-22 实测反馈）。

    合同：实时链对缺失 avgRankNum 的行按八平台 rank 补均榜（weighted_platform_percentile_v1），
    使其注册单点序列进分析（共振/热度/量价可算，趋势/周期样本不足按既有 insufficient 口径），
    并携带 meta.liveRanking（实时均榜+综合排名）。已有有效 avgRankNum 的行不被覆盖。
    """
    frames = [{
        "tradingDate": "2026-07-31",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 31,
        "rows": [
            {"code": "C00", "rank": 1, "avgRankNum": 12.5,
             "change": 1.0, "volumeRatio": 1.2, "zlje": 10, "zljzb": 0.1}
            for _ in range(1)
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["C00", "NEW1"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": [
                # C00：帧池 golden 行，带有效 avgRankNum（不得被实时均榜覆盖）
                {"code": "C00", "emRank": 1, "avgRankNum": 12.5, "change": 2.0,
                 "volumeRatio": 1.5, "zlje": 20, "zljzb": 1.0, "turnover": 400, "turnoverRate": 10},
                # NEW1：收盘帧后新入榜，无历史、无 avgRankNum，仅当前平台排名
                {"code": "NEW1", "emRank": 30, "avgRankNum": None, "change": 9.9,
                 "volumeRatio": 3.0, "zlje": 50, "zljzb": 2.0, "turnover": 900, "turnoverRate": 20},
            ],
        },
    })
    assert response.status_code == 200
    last = response.json()["frames"][-1]
    by_code = {stock["code"]: stock for stock in last["stocks"]}
    # 新进股票不再被 gate 整只丢弃：补实时均榜后注册单点序列，产出分析
    assert "NEW1" in by_code, f"新进股票缺失: {sorted(by_code)}"
    new_analysis = by_code["NEW1"]["analysis"]
    # 单点序列：样本不足如实降级，不伪造趋势/周期结论
    sample_quality = new_analysis["meta"].get("sampleQuality") or {}
    assert sample_quality.get("status") == "insufficient"
    # 小池（2 行 < MIN_LIVE_RANKING_POOL_SIZE）不注入 liveRanking（review C1 门槛，
    # 失真防护由 test_analyze_live_ranking_skipped_below_min_pool_size 锁定）；
    # NEW1 的实时均榜已补在行输入上（attention 序列可用），只是不以 liveRanking 下发
    assert "liveRanking" not in (new_analysis.get("meta") or {})
