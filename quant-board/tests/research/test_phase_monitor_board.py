# -*- coding: utf-8 -*-
"""phase-monitor board 读口测试：哨兵分歧（融合总纲合流点一）纯函数 + c9 账本透传。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.phase_monitor_routes import sentinel_divergence


class _Cursor(list):
    def sort(self, *args: object, **kwargs: object) -> "_Cursor":
        return self


class _Col:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def find(self, *args: object, **kwargs: object) -> _Cursor:
        return _Cursor(self._docs)


class _Db:
    def __init__(self, cols: dict[str, list[dict]]):
        self._cols = cols

    def __getitem__(self, name: str) -> _Col:
        return _Col(self._cols[name])


def test_sentinel_divergence_relations_and_skips():
    """一致/判低/判高逐日正确；哨兵 insufficient 与缺 EOD 分的日期计入 skipped（fail-visible）。"""
    db = _Db({
        "hotlist_sentiment": [
            {"tradingDate": "2026-09-01", "emotionScore": {"score": 55.0}},   # 规则=弱势
            {"tradingDate": "2026-09-02", "emotionScore": {"score": 70.0}},   # 规则=强势
            {"tradingDate": "2026-09-03", "emotionScore": {"score": 45.0}},   # 规则=弱势
            # 09-05 故意无 EOD 分：当日哨兵再响也计入 skipped（fail-visible 不硬比）
        ],
        "hotlist_jev_driver_labels": [
            {"tradingDate": "2026-09-01", "phaseBand": "weak_40_60"},          # 一致
            {"tradingDate": "2026-09-02", "phaseBand": "weak_40_60"},          # 判低（强势读成弱势）
            {"tradingDate": "2026-09-03", "phaseBand": "cold_lt40"},           # 判低（弱势读成低温）
            {"tradingDate": "2026-09-04", "phaseBand": "insufficient"},        # 哨兵证据不足→skip
            {"tradingDate": "2026-09-05", "phaseBand": "strong_ge60"},         # 当日无 EOD 分→skip
        ],
    })
    out = sentinel_divergence(db)
    assert out["summary"] == {"comparable": 3, "agree": 1, "lower": 2, "higher": 0, "skipped": 2}
    days = out["days"]
    assert days[0]["relation"] == "agree" and days[0]["ruleBand"] == "弱势带"
    assert days[1]["relation"] == "lower" and days[1]["sentinelBand"] == "弱势带"
    assert days[2]["relation"] == "lower" and days[2]["sentinelRaw"] == "cold_lt40"


def test_sentinel_divergence_higher_and_empty():
    """哨兵读高方向 + 全空输入返回零计数不报错（fail-visible 空态）。"""
    db = _Db({
        "hotlist_sentiment": [{"tradingDate": "2026-09-01", "emotionScore": {"score": 45.0}}],
        "hotlist_jev_driver_labels": [{"tradingDate": "2026-09-01", "phaseBand": "strong_ge60"}],
    })
    out = sentinel_divergence(db)
    assert out["summary"]["higher"] == 1 and out["days"][0]["relation"] == "higher"

    empty = sentinel_divergence(_Db({"hotlist_sentiment": [], "hotlist_jev_driver_labels": []}))
    assert empty["summary"]["comparable"] == 0 and empty["days"] == []
