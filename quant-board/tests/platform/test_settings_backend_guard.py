from __future__ import annotations

import pytest

from backend.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """get_settings 是 lru_cache 单例：改动 env 后必须清缓存，测完再清防止泄漏到其他用例。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_sqlite_backend_requires_explicit_opt_in(monkeypatch):
    """2026-09-29 隔离裁决：sqlite 不再是可用默认链，未显式 opt-in 直接 raise（fail-visible）。"""
    monkeypatch.setenv("QUANT_BOARD_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("QUANT_BOARD_ALLOW_SQLITE_BACKEND", raising=False)
    with pytest.raises(RuntimeError, match="生产禁止 sqlite"):
        get_settings()


def test_sqlite_backend_allowed_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("QUANT_BOARD_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("QUANT_BOARD_ALLOW_SQLITE_BACKEND", "1")
    settings = get_settings()
    assert settings.storage_backend == "sqlite"
    assert settings.allow_sqlite_backend is True


def test_default_backend_is_mongodb():
    """代码默认值翻转：裸环境（无 .env.local）解析为 mongodb/dragon_board_quant，不再静默落 sqlite。"""
    assert Settings.model_fields["storage_backend"].default == "mongodb"


def test_mongodb_backend_resolution_unchanged(monkeypatch):
    monkeypatch.setenv("QUANT_BOARD_STORAGE_BACKEND", "mongodb")
    settings = get_settings()
    assert settings.storage_backend == "mongodb"


def test_production_entrypoint_guard_rejects_sqlite_without_opt_in():
    """8000 API / 8001 采集器 startup fail-fast：sqlite 且未 opt-in → 拒绝启动。"""
    from types import SimpleNamespace

    from backend.core.settings import assert_production_storage_backend

    with pytest.raises(RuntimeError, match="生产入口禁止 sqlite"):
        assert_production_storage_backend(
            SimpleNamespace(storage_backend="sqlite", allow_sqlite_backend=False)
        )
    # opt-in 放行 / mongodb 正常
    assert (
        assert_production_storage_backend(
            SimpleNamespace(storage_backend="sqlite", allow_sqlite_backend=True)
        )
        is None
    )
    assert (
        assert_production_storage_backend(
            SimpleNamespace(storage_backend="mongodb", allow_sqlite_backend=False)
        )
        is None
    )
