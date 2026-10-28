# -*- coding: utf-8 -*-
"""market_history_service 测试 —— 全 mock HTTP + 临时目录持久化（红线：测试零真实网络）。

覆盖（2026-10-28 KPI 历史修复）：
- 东财 push2ex 分桶 → 涨/跌/平合计（含负桶/零桶）；
- breadth-history：本地逐日持久化命中 / 目标日新于已累积 → 拉上游并落库 /
  未累积日期结构化缺数（fail-visible，且不再重复打上游）；
- index-history：腾讯日 K 解析 + pct 自前收盘计算 + 缺日期结构化报错。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import market_history_service as svc  # noqa: E402
from backend.services.market_history_service import (  # noqa: E402
    MarketHistoryError,
    _fenbu_sums,
    get_breadth_history,
    get_index_history,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """持久化文件指向临时目录；进程内缓存每用例清空。"""
    monkeypatch.setattr(svc, "BREADTH_STORE", tmp_path / "breadth.json")
    svc._CACHE.clear()


class TestFenbuSums:
    def test_buckets_aggregate(self):
        fenbu = [{"1": 214}, {"-1": 358}, {"0": 34}, {"-11": 22}, {"11": 7}]
        assert _fenbu_sums(fenbu) == {"rise": 221, "down": 380, "flat": 34}

    def test_empty_and_garbage(self):
        assert _fenbu_sums([]) == {"rise": 0, "down": 0, "flat": 0}
        assert _fenbu_sums([{"x": 3}, {"2": "5"}]) == {"rise": 5, "down": 0, "flat": 0}


class TestBreadthHistory:
    def _live(self, date="2026-10-27", rise=567, down=4774):
        return {"date": date, "rise": rise, "down": down, "flat": 34,
                "source": "eastmoney_push2ex"}

    def test_old_date_miss_fail_visible_without_repeat_fetch(self, monkeypatch):
        calls = []

        def fake_live():
            calls.append(1)
            return self._live("2026-10-27")

        monkeypatch.setattr(svc, "_fetch_push2ex_breadth", fake_live)
        with pytest.raises(MarketHistoryError) as ei:
            get_breadth_history("2026-10-23")
        assert ei.value.reason == "breadth_history_not_accumulated"
        assert ei.value.detail["latest_available"] == "2026-10-27"
        # 第二次请求同类缺数：已落库即不再打上游
        with pytest.raises(MarketHistoryError):
            get_breadth_history("2026-10-24")
        assert len(calls) == 1

    def test_latest_date_ok_and_persisted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "_fetch_push2ex_breadth", lambda: self._live())
        payload = get_breadth_history("2026-10-27")
        assert payload["ok"] is True and payload["rise"] == 567 and payload["down"] == 4774
        # 落库后命中持久化（再打也不会重复拉上游）
        import json
        store = json.loads((tmp_path / "breadth.json").read_text(encoding="utf-8"))
        assert store["days"]["2026-10-27"]["rise"] == 567
        assert get_breadth_history("2026-10-27")["flat"] == 34

    def test_corrupted_store_fail_visible(self, monkeypatch, tmp_path):
        (tmp_path / "breadth.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(MarketHistoryError) as ei:
            get_breadth_history("2026-10-27")
        assert ei.value.reason == "breadth_store_corrupted"

    def test_invalid_date(self):
        with pytest.raises(MarketHistoryError) as ei:
            get_breadth_history("2026/10/27")
        assert ei.value.reason == "invalid_date"


class TestIndexHistory:
    @staticmethod
    def _fake_kline(code, start, end):
        rows_by_code = {
            "sh000001": [["2026-10-24", "3300.00", "3280.00"],
                         ["2026-10-27", "3260.00", "3312.45"]],
            "sz399001": [["2026-10-24", "10400.00", "10300.00"],
                         ["2026-10-27", "10310.00", "10500.10"]],
            "sz399006": [["2026-10-24", "2100.00", "2080.00"],
                         ["2026-10-27", "2085.00", "2150.30"]],
        }
        return rows_by_code[code]

    def test_parse_and_pct(self, monkeypatch):
        monkeypatch.setattr(svc, "_fetch_tencent_kline", self._fake_kline)
        payload = get_index_history("2026-10-27")
        assert payload["ok"] is True and len(payload["items"]) == 3
        by_code = {it["code"]: it for it in payload["items"]}
        assert by_code["sh000001"]["close"] == 3312.45
        # pct 自前收盘计算：(3312.45/3280.00-1)*100
        assert by_code["sh000001"]["pct"] == 0.99
        assert by_code["sz399006"]["pct"] == 3.38

    def test_missing_date_fail_visible(self, monkeypatch):
        monkeypatch.setattr(svc, "_fetch_tencent_kline", self._fake_kline)
        with pytest.raises(MarketHistoryError) as ei:
            get_index_history("2026-10-23")
        assert ei.value.reason == "date_not_in_kline"

    def test_invalid_date(self):
        with pytest.raises(MarketHistoryError) as ei:
            get_index_history("not-a-date")
        assert ei.value.reason == "invalid_date"
