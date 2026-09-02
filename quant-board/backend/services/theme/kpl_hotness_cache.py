"""KPL 题材个股人气缓存（tck2.js 口径）。

数据链路：
  longhuvip Theme API（复用 mapping_refresh 的 client）→ extract_theme_hots
  → 进程内 last-good 缓存 → ThemeHeatService 热度计算（heatScore = 人气总和）。

口径来源（D:\\TDX外挂\\KPL题材库1.0\\tck2.js fetchThemeData）：
  hotness = Σ 个股人气值，遍历顺序 Table.Level1.Stocks(Hot) → Table.Level2[].Stocks(Hot)
  → StockList(HotNum)，按 StockID 去重，只收 > 0 的值；Hot <= 0 不占位，
  同股后续来源仍可贡献。

fail-visible 约束：
  拉取失败/errcode != 0 的题材保留上次成功值（last-good），失败列表结构化上报；
  只有全题材均无数据时不伪造成功（ok=False + reason）。缺失题材由调用方
  （compute_theme_heat）按 kpl_hotness_unavailable 打标，不伪装成 0。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from backend.services.theme.mapping_refresh import fetch_theme_detail


def _positive(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric > 0 else 0.0


def _collect_stocks(stocks: object, field: str, hots: dict[str, float]) -> None:
    if not isinstance(stocks, list):
        return
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("StockID") or "").strip()
        hot = _positive(stock.get(field))
        if code and hot > 0 and code not in hots:
            hots[code] = hot


def extract_theme_hots(api_data: dict[str, Any]) -> dict[str, float]:
    """按 tck2.js fetchThemeData 顺序提取题材内个股人气（StockID → Hot）。

    顺序决定优先级：Table.Level1.Stocks 的 Hot → Table.Level2[].Stocks 的 Hot →
    StockList 的 HotNum；同一 StockID 只保留第一个 >0 值（去重求和的提取形态）。
    """
    hots: dict[str, float] = {}
    if not isinstance(api_data, dict):
        return hots

    table = api_data.get("Table")
    for item in table or []:
        if not isinstance(item, dict):
            continue
        level1 = item.get("Level1")
        if isinstance(level1, dict):
            _collect_stocks(level1.get("Stocks"), "Hot", hots)
        for level2 in item.get("Level2") or []:
            if isinstance(level2, dict):
                _collect_stocks(level2.get("Stocks"), "Hot", hots)
    _collect_stocks(api_data.get("StockList"), "HotNum", hots)

    return hots


class KplHotnessCache:
    """题材个股人气进程内缓存：后台线程定时全量刷新，读路径零上游请求。"""

    def __init__(
        self,
        theme_ids_provider: Callable[[], list[str]],
        *,
        fetcher: Callable[[str], dict[str, Any] | None] | None = None,
        refresh_interval_seconds: int = 600,
        request_delay_seconds: float = 0.05,
    ) -> None:
        self._theme_ids_provider = theme_ids_provider
        self._fetcher = fetcher or fetch_theme_detail
        self._refresh_interval_seconds = max(60, int(refresh_interval_seconds))
        self._request_delay_seconds = max(0.0, request_delay_seconds)
        # theme_id → {code: hot}（仅保留请求列表内题材；stale 条目不出读口）
        self._hots: dict[str, dict[str, float]] = {}
        self._last_refresh_at: float | None = None
        self._last_result: dict[str, object] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def refresh_once(self) -> dict[str, object]:
        """全量刷新一轮：逐题材拉取提取。失败题材保留 last-good 并结构化上报。"""
        theme_ids = list(dict.fromkeys(str(item) for item in self._theme_ids_provider() if str(item)))
        result: dict[str, object] = {
            "ok": True,
            "requested": len(theme_ids),
            "fetched": 0,
            "failedThemeIds": [],
            "reasons": [],
            "finishedAt": int(time.time() * 1000),
        }
        if not theme_ids:
            result["ok"] = False
            result["reasons"] = ["no_theme_ids"]
            self._last_result = result
            self._last_refresh_at = time.time()
            return result

        for index, theme_id in enumerate(theme_ids):
            try:
                api_data = self._fetcher(theme_id)
            except Exception as exc:
                with self._lock:
                    result["failedThemeIds"] = [*result["failedThemeIds"], theme_id]  # type: ignore[operator]
                    result["reasons"] = [*result["reasons"], f"{theme_id}: {exc}"]  # type: ignore[operator]
                continue
            if not isinstance(api_data, dict):
                # errcode != 0（题材被删除/无数据）：保留 last-good，分类上报
                with self._lock:
                    result["failedThemeIds"] = [*result["failedThemeIds"], theme_id]  # type: ignore[operator]
                continue
            hots = extract_theme_hots(api_data)
            with self._lock:
                self._hots[theme_id] = hots
                result["fetched"] += 1
            if self._request_delay_seconds and index + 1 < len(theme_ids):
                time.sleep(self._request_delay_seconds)

        if result["failedThemeIds"]:
            result["ok"] = False
        result["finishedAt"] = int(time.time() * 1000)
        with self._lock:
            self._last_result = result
            self._last_refresh_at = time.time()
        return result

    def get_theme_hots(self, theme_ids: list[str]) -> dict[str, dict[str, float]]:
        """读取请求题材的已缓存人气；未刷新过的题材保持缺失，不伪造空值。"""
        wanted = [str(item) for item in theme_ids if str(item)]
        with self._lock:
            return {theme_id: dict(self._hots[theme_id]) for theme_id in wanted if theme_id in self._hots}

    def get_health(self) -> dict[str, object]:
        with self._lock:
            return {
                "refreshIntervalSeconds": self._refresh_interval_seconds,
                "lastRefreshAt": (
                    int(self._last_refresh_at * 1000) if self._last_refresh_at else None
                ),
                "cachedThemeCount": len(self._hots),
                "lastResult": dict(self._last_result) if self._last_result else None,
            }

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="kpl-hotness-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            # join 超时（全量刷新一轮可达数分钟）保留引用：线程退出前再 start()
            # 借 is_alive 拒绝重复启动，避免 clear stop_event 造成双刷新循环。
            if not thread.is_alive():
                self._thread = None

    def _run_loop(self) -> None:
        # 启动即预热一轮（对齐 tck2.js init 后立即 fetchAllThemeData），之后周期刷新
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                self.refresh_once()
            except Exception:
                # 刷新循环永不退出：异常已按题材粒度记录在 lastResult
                pass
            elapsed = time.monotonic() - started
            remaining = max(1.0, self._refresh_interval_seconds - elapsed)
            if self._stop_event.wait(timeout=remaining):
                return
