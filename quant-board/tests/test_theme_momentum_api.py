# quant-board/tests/test_theme_momentum_api.py
"""GET /api/theme-momentum/summary 只读接口：返回 v2 全字段排行与质量标记。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.analysis.theme.daily_series import ThemeDailySeries
from backend.analysis.theme.momentum import compute_theme_momentum_v2
from backend.analysis.theme.momentum_config import ThemeMomentumConfig
from backend.main import app

client = TestClient(app)


def _fake_daily_list() -> list[ThemeDailySeries]:
    n = 25
    return [
        ThemeDailySeries(
            theme_id="BKAI",
            theme_name="人工智能",
            dates=[f"2026-06-{10 + i:02d}" for i in range(n)],
            changes=[0.05] * n,
            zt_counts=[5] * n,
            breadths=[70.0] * n,
            inflows=[2.0] * n,
            amount_ratios=[0.05] * n,
            quality_flags=[],
        ),
        ThemeDailySeries(
            theme_id="BKBA",
            theme_name="机器人",
            dates=[f"2026-06-{10 + i:02d}" for i in range(n)],
            changes=[0.01] * n,
            zt_counts=[2] * n,
            breadths=[55.0] * n,
            inflows=[0.5] * n,
            amount_ratios=[0.03] * n,
            quality_flags=[],
        ),
    ]


def test_theme_momentum_summary_returns_factors(monkeypatch) -> None:
    import backend.api.theme_momentum_routes as routes

    monkeypatch.setattr(
        routes,
        "_load_recent_sector_rows",
        lambda db, dataset_id, snapshot_type: [],
    )
    monkeypatch.setattr(
        routes,
        "build_daily_series",
        lambda rows, stock_rows: {
            s.theme_id: s for s in _fake_daily_list()
        },
    )
    monkeypatch.setattr(
        routes,
        "compute_theme_momentum_v2",
        lambda daily_list, cfg=None, computed_at=0: compute_theme_momentum_v2(
            daily_list, cfg=ThemeMomentumConfig(), computed_at=computed_at
        ),
    )
    monkeypatch.setattr(
        "backend.api.theme_momentum_routes.get_runtime_mongodb_database",
        lambda: {"fake": "db"},
    )

    resp = client.get(
        "/api/theme-momentum/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"] == "theme_momentum_v2"
    assert len(body["factors"]) == 2
    # 排行按 score 降序：BKAI 涨幅更高应排前
    assert body["factors"][0]["themeId"] == "BKAI"
    assert body["factors"][0]["direction"] == "up"
    assert set(body["factors"][0]) >= {
        "themeId", "themeName", "score", "direction", "phaseLabel",
        "rps", "nearHigh", "windowMomentum", "breadth", "flowVolume",
        "crowdingPenalty", "intraday", "reasons",
    }
    assert body["factors"][0]["rps"]["d20"] is not None


def test_theme_momentum_summary_empty_db(monkeypatch) -> None:
    """无数据时不崩溃，返回空 factors + 质量标记（fail-visible）。"""
    import backend.api.theme_momentum_routes as routes

    monkeypatch.setattr(
        routes,
        "_load_recent_sector_rows",
        lambda db, dataset_id, snapshot_type: [],
    )
    monkeypatch.setattr(
        routes,
        "build_daily_series",
        lambda rows, stock_rows: {},
    )
    monkeypatch.setattr(
        routes,
        "compute_theme_momentum_v2",
        lambda daily_list, cfg=None, computed_at=0: {
            "version": "theme_momentum_v2",
            "factors": {},
            "qualityFlags": ["cross_section_insufficient"],
            "computedAt": computed_at,
        },
    )
    monkeypatch.setattr(
        "backend.api.theme_momentum_routes.get_runtime_mongodb_database",
        lambda: {"fake": "db"},
    )

    resp = client.get(
        "/api/theme-momentum/summary",
        params={"dataset_id": "empty_test", "snapshot_type": "hourly"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["factors"] == []
    assert "cross_section_insufficient" in body["qualityFlags"]


def test_theme_momentum_summary_real_data_in_pytest_db(monkeypatch) -> None:
    """端到端：连 pytest 库（已复制 live 的 snapshot_sector_rows 数据）验证真实输出。

    前置：tests/conftest.py 已把 QUANT_BOARD_MONGODB_DATABASE 设为 dragon_board_quant_pytest，
    需本机 MongoDB 可用且已复制数据（见交付检查记录）。数据不足时降级验证（fail-visible）。
    """
    import backend.api.theme_momentum_routes as routes

    # 不 mock 数据源：走真实 pytest 库；仅允许 Redis 缓存不可用时降级
    monkeypatch.setattr(
        "backend.api.theme_momentum_routes.get_runtime_mongodb_database",
        routes.get_runtime_mongodb_database,
    )
    resp = client.get(
        "/api/theme-momentum/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["version"] == "theme_momentum_v2"
    # 有数据：factors 非空且字段齐全；无数据：qualityFlags 标记（fail-visible）
    if body["factors"]:
        first = body["factors"][0]
        assert set(first) >= {
            "themeId", "themeName", "score", "direction", "phaseLabel",
            "rps", "nearHigh", "windowMomentum", "breadth", "flowVolume",
            "crowdingPenalty", "intraday", "reasons",
        }
        assert 0 <= first["score"] <= 100
        assert first["direction"] in {"up", "neutral", "down"}
        assert first["phaseLabel"] in {"启动", "扩散", "过热", "退潮", "中性"}
    else:
        assert "cross_section_insufficient" in body["qualityFlags"]

