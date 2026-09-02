from __future__ import annotations

from backend.services.theme.kpl_hotness_cache import KplHotnessCache, extract_theme_hots


def test_extract_prefers_table_level1_hot_over_stocklist_hotnum() -> None:
    """tck2.js 顺序：Table.Level1 的 Hot 先占位，同股 StockList 的 HotNum 不再加。"""
    api_data = {
        "Table": [
            {
                "Level1": {"Name": "龙头", "Stocks": [{"StockID": "000001", "Hot": 300}]},
                "Level2": [],
            }
        ],
        "StockList": [{"StockID": "000001", "HotNum": 500}],
    }

    assert extract_theme_hots(api_data) == {"000001": 300}


def test_extract_zero_hot_does_not_block_later_sources() -> None:
    """tck2.js 精确语义：Hot<=0 不占位——同股后续来源（StockList.HotNum）仍可贡献。"""
    api_data = {
        "Table": [
            {
                "Level1": {"Stocks": [{"StockID": "000001", "Hot": 0}]},
                "Level2": [{"Stocks": [{"StockID": "000002", "Hot": 200}]}],
            }
        ],
        "StockList": [
            {"StockID": "000001", "HotNum": 500},
            {"StockID": "000002", "HotNum": 999},
        ],
    }

    assert extract_theme_hots(api_data) == {"000001": 500, "000002": 200}


def test_extract_ignores_invalid_and_non_positive_values() -> None:
    """缺字段/非法值/非正数按 tck2.js `> 0` 判定跳过，不产生伪造热度。"""
    api_data = {
        "Table": [
            {
                "Level1": {"Stocks": [{"StockID": "000001", "Hot": "abc"}, {"StockID": "000002"}]},
                "Level2": [{"Stocks": [{"StockID": "000003", "Hot": -5}]}],
            }
        ],
        "StockList": [{"StockID": "000004", "HotNum": 120}],
    }

    assert extract_theme_hots(api_data) == {"000004": 120}


def test_extract_empty_or_malformed_payload_returns_empty_dict() -> None:
    assert extract_theme_hots({}) == {}
    assert extract_theme_hots({"Table": None, "StockList": None}) == {}
    assert extract_theme_hots({"Table": ["bad", 1, None]}) == {}


def test_refresh_once_updates_memory_and_reports_counts() -> None:
    payloads = {
        "226": {"Table": [], "StockList": [{"StockID": "000001", "HotNum": 1200}]},
        "227": {"Table": [], "StockList": [{"StockID": "000002", "HotNum": 300}]},
    }
    cache = KplHotnessCache(
        lambda: ["226", "227"],
        fetcher=lambda theme_id: payloads[theme_id],
        refresh_interval_seconds=600,
    )

    result = cache.refresh_once()

    assert result["ok"] is True
    assert result["fetched"] == 2
    assert result["failedThemeIds"] == []
    assert cache.get_theme_hots(["226", "227"]) == {
        "226": {"000001": 1200.0},
        "227": {"000002": 300.0},
    }


def test_refresh_failure_keeps_last_good_values_visible() -> None:
    """fail-visible：拉取失败保留上次成功值，失败题材结构化上报，不静默清空。"""
    payloads = {"226": {"Table": [], "StockList": [{"StockID": "000001", "HotNum": 1200}]}}
    cache = KplHotnessCache(
        lambda: ["226"],
        fetcher=lambda theme_id: payloads[theme_id],
        refresh_interval_seconds=600,
    )
    cache.refresh_once()

    def broken_fetch(theme_id: str) -> dict:
        raise RuntimeError("网络错误: timeout")

    cache._fetcher = broken_fetch
    result = cache.refresh_once()

    assert result["ok"] is False
    assert result["failedThemeIds"] == ["226"]
    assert cache.get_theme_hots(["226"]) == {"226": {"000001": 1200.0}}
    health = cache.get_health()
    assert health["lastResult"]["failedThemeIds"] == ["226"]


def test_refresh_errcode_none_keeps_last_good() -> None:
    """errcode != 0（题材被删除/无数据）与网络失败同路径：保留 last-good 并分类上报。"""
    payloads = {"226": {"Table": [], "StockList": [{"StockID": "000001", "HotNum": 1200}]}}
    cache = KplHotnessCache(
        lambda: ["226"],
        fetcher=lambda theme_id: payloads[theme_id],
        refresh_interval_seconds=600,
    )
    cache.refresh_once()
    payloads["226"] = None

    result = cache.refresh_once()

    assert result["ok"] is False
    assert result["failedThemeIds"] == ["226"]
    assert cache.get_theme_hots(["226"]) == {"226": {"000001": 1200.0}}


def test_get_theme_hots_returns_only_cached_requested_ids() -> None:
    cache = KplHotnessCache(
        lambda: ["226"],
        fetcher=lambda theme_id: {"Table": [], "StockList": [{"StockID": "000001", "HotNum": 100}]},
        refresh_interval_seconds=600,
    )
    cache.refresh_once()

    hots = cache.get_theme_hots(["226", "999"])

    # 999 未刷新过：保持缺失（调用方按 kpl_hotness_unavailable 打标），不伪造空值
    assert hots == {"226": {"000001": 100.0}}


def test_refresh_reports_zero_themes_without_faking_success() -> None:
    cache = KplHotnessCache(
        lambda: [],
        fetcher=lambda theme_id: {},
        refresh_interval_seconds=600,
    )

    result = cache.refresh_once()

    assert result["ok"] is False
    assert result["fetched"] == 0
    assert "no_theme_ids" in result["reasons"]


# ── 后台线程生命周期（2026-09 审计 L3） ──

def test_stop_timeout_keeps_thread_reference() -> None:
    """stop() join 超时（全量刷新一轮可达数分钟）时不置空线程引用：
    后续 start() 借 is_alive 拒绝重复启动，避免双刷新循环。"""
    cache = KplHotnessCache(lambda: [], fetcher=lambda theme_id: None, request_delay_seconds=0)

    class SlowThread:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            pass  # 模拟 join(5) 超时：refresh_once 仍在跑，线程仍存活

    slow = SlowThread()
    cache._thread = slow  # type: ignore[assignment]
    cache.stop()

    assert cache._thread is slow
    # 线程仍存活时 start() 不再新建（无双循环、不 clear stop_event）
    cache.start()
    assert cache._thread is slow


def test_start_stop_lifecycle_is_idempotent() -> None:
    cache = KplHotnessCache(lambda: [], fetcher=lambda theme_id: None, request_delay_seconds=0)

    cache.start()
    thread = cache._thread
    assert thread is not None and thread.is_alive()
    cache.start()  # 幂等：不另建线程
    assert cache._thread is thread

    cache.stop()
    assert cache._thread is None
    cache.stop()  # 幂等
    cache.start()
    assert cache._thread is not thread and cache._thread.is_alive()
    cache.stop()
    assert cache._thread is None
