# -*- coding: utf-8 -*-
"""kpl_ranking_service 测试 —— 全 mock HTTP（红线：测试零真实 KPL 请求）。

解析纯函数用 2026-10-25 实测样本（data/backups/kpl-corpus-probe-20261025/）钉住；
HTTP 层 monkeypatch _post_form；限速 sleep 全部 mock 掉（测试不等待）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_ranking_service as svc  # noqa: E402
from backend.services.kpl_ranking_service import (  # noqa: E402
    KplRankingError,
    get_sector_ranking,
    get_sector_stocks,
    parse_ranking_row,
    parse_stock_row,
)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """单发间隔 2s 只约束生产；测试里 mock sleep + 重置节流时间戳。"""
    monkeypatch.setattr(svc.time, "sleep", lambda s: None)
    monkeypatch.setattr(svc, "_last_request_at", 0.0)
    svc._cache.clear()


# 2026-10-25 实测样本行（kpl_real_ranking.json 首行截取前 10 列，语义钉死）
RANKING_ROW = ["801159", "机器人概念", 36926, 3.382, 0.757, 546381598172,
               9076589975, 45936857410, -36860267435, 1.536]

# 2026-10-25 实测样本行（kpl_plate_stocks.json 凡拓数创，截取前 25 列）
STOCK_ROW = ["301313", "凡拓数创", "游资", 0, "数据采集、数字经济", 61.44, 20,
             1674732917, 45.72, 0, 4158785495, 697287503, -551140604, 146146899,
             41.64, 32.91, 8.73, 16.77, 13.25, 3.51, 21.21, 1.14045, 0,
             "5天3板", "龙一"]


class TestParseRankingRow:
    def test_aligned_fields(self):
        r = parse_ranking_row(RANKING_ROW)
        assert r["plate_id"] == "801159"
        assert r["name"] == "机器人概念"
        assert r["strength"] == 36926          # Gitee 权威释义
        assert r["pct"] == 3.382
        assert r["amount"] == 546381598172
        assert r["main_net"] == -36860267435   # 推断（样本负值自洽）
        assert r["volume_ratio"] == 1.536      # 推断

    def test_raw_preserved_fail_visible(self):
        r = parse_ranking_row(RANKING_ROW)
        assert r["raw"] == RANKING_ROW  # 未对齐列原样保留，不丢不猜

    def test_short_row_no_crash(self):
        r = parse_ranking_row(["801001", "芯片"])
        assert r["plate_id"] == "801001"
        assert r["strength"] is None


class TestParseStockRow:
    def test_aligned_fields(self):
        r = parse_stock_row(STOCK_ROW)
        assert r["code"] == "301313"
        assert r["name"] == "凡拓数创"
        assert r["concept"] == "数据采集、数字经济"
        assert r["price"] == 61.44
        assert r["pct"] == 20
        assert r["turnover"] == 45.72
        assert r["board_status"] == "5天3板"
        assert r["rank_title"] == "龙一"

    def test_main_buy_sell_net_self_consistent(self):
        r = parse_stock_row(STOCK_ROW)
        # 推断语义自洽：主买 + 主卖 = 主净（样本 697287503 - 551140604 = 146146899）
        assert r["main_buy"] + r["main_sell"] == r["main_net"]
        assert r["volume_ratio"] == pytest.approx(1.14045)


class TestErrcode:
    def test_errcode_nonzero_raises(self):
        with pytest.raises(KplRankingError) as ei:
            svc._check_errcode({"errcode": 1020, "errmsg": "param error"})
        assert ei.value.reason == "kpl_errcode"
        assert ei.value.detail["errorCode"] == "1020"

    def test_errcode_zero_ok(self):
        svc._check_errcode({"errcode": 0})
        svc._check_errcode({})
        svc._check_errcode({"errcode": "0"})


class TestGetSectorRanking:
    def test_pages_aggregated_and_cached(self, monkeypatch):
        calls = []

        def fake_post(url, params, ua):
            calls.append((url, dict(params)))
            page = params["Index"]
            rows = [[f"8{i:05d}", f"板块{i}", 1000 + i, 1.0 + i, 0, 1, 0, 0, 0, 0]
                    for i in range(page, page + 80)]   # 恒为 6 位代码（过滤规则要求）
            return {"errcode": 0, "list": rows}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-24")
        assert out["ok"] is True and out["date"] == "2026-10-24"
        assert len(out["items"]) == svc._RANKING_MAX_PAGES * 80  # 满页继续翻
        assert [c[1]["Index"] for c in calls] == [0, 80, 160, 240, 320]
        assert calls[0][1]["Type"] == 1 and calls[0][1]["Date"] == "2026-10-24"
        assert calls[0][1]["Token"] == "0" and calls[0][1]["UserID"] == "0"  # 免凭据
        # 缓存命中：第二次不再发请求
        n = len(calls)
        out2 = get_sector_ranking("2026-10-24")
        assert len(calls) == n and out2["ok"] is True

    def test_short_page_stops_paging(self, monkeypatch):
        calls = []

        def fake_post(url, params, ua):
            calls.append(1)
            return {"errcode": 0, "list": [["801159", "机器人概念", 1, 0, 0, 0, 0, 0, 0, 0]]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-24")
        assert len(calls) == 1  # 尾页不足 80 即停
        assert len(out["items"]) == 1

    def test_zero_garbage_rows_filtered(self, monkeypatch):
        # 2026-10-27 实测：盘前/未生成日上游返回「全零行」（plate_id="0" 名称空）——
        # 不过滤会把引导卡死在无数据日（真正的历史日在更早日期）
        garbage = [["0", "", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
                   for _ in range(80)]
        good = [["801159", "机器人概念", 36926, 3.382, 0.757, 1, 0, 0, 0, 0]]

        def fake_post(url, params, ua):
            return {"errcode": 0, "list": list(garbage) + good}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-27")
        assert len(out["items"]) == 1                       # 垃圾行全滤掉
        assert out["items"][0]["plate_id"] == "801159"


class TestGetSectorStocks:
    def test_requires_credentials_from_common_source(self, monkeypatch):
        captured = {}

        def fake_post(url, params, ua):
            captured.update(params)
            return {"errcode": 0, "list": [STOCK_ROW]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_stocks("801159", "2026-10-24")
        assert out["ok"] is True and out["items"][0]["code"] == "301313"
        # 凭据必须取自公共出口（禁另拷常量），UserID/Token 非游客值
        assert captured["UserID"] == svc.KPL_APP_BASE_PARAMS["UserID"]
        assert captured["Token"] == svc.KPL_APP_BASE_PARAMS["Token"]
        assert captured["PlateID"] == "801159"
        assert captured["a"] == "ZhiShuStockList_W8" and captured["c"] == "ZhiShuRanking"

    def test_empty_first_page_is_structured_error(self, monkeypatch):
        # 现役凭据失效实测返空列表而非 errcode —— 必须结构化报错，不伪装「无成分股」
        monkeypatch.setattr(svc, "_post_form", lambda url, params, ua: {"errcode": 0, "list": []})
        with pytest.raises(KplRankingError) as ei:
            get_sector_stocks("801159", "2026-10-24")
        assert ei.value.reason == "empty_list_check_credentials"

    def test_page_fetches_only_requested_batch(self, monkeypatch):
        # 真·按页取数（2026-10-27 用户二次裁决）：一页 = 一次上游请求（st=100/Index=0），
        # 不再整单拉取——切板块/首屏只等一枪
        rows100 = [[f"30{i:04d}", f"股{i}", "", 0, "概念", 10.0, 1, 1e6, 5, 0,
                    1e7, 1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 0, "首板", "龙一"]
                   for i in range(100)]
        calls = []

        def fake_post(url, params, ua):
            calls.append((params["Index"], params["st"]))
            return {"errcode": 0, "list": list(rows100)}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_stocks("801159", "2026-10-24", page=0)
        assert len(out["items"]) == 100 and out["has_more"] is True
        assert calls == [(0, 100)]              # 只发一枪，Index=0/st=100

    def test_page1_uses_index_offset(self, monkeypatch):
        calls = []

        def fake_post(url, params, ua):
            calls.append(params["Index"])
            return {"errcode": 0, "list": [["300413", "芒果超媒", "", 0, "概念", 24.16, 4,
                                            1e6, 5, 0, 1e7, 1, -1, 0, 0, 0, 0, 0, 0, 0, 0,
                                            1.0, 0, "首板", "龙一"]]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_stocks("801159", "2026-10-24", page=1)
        assert calls == [100]                   # Index=100 行偏移
        assert out["items"][0]["code"] == "300413"
        assert out["has_more"] is False         # 不满一页 = 尾页

    def test_cache_is_per_page(self, monkeypatch):
        calls = []

        def fake_post(url, params, ua):
            calls.append(params["Index"])
            return {"errcode": 0, "list": []}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        with pytest.raises(KplRankingError):
            get_sector_stocks("801159", "2026-10-24", page=0)   # 首页空 → 结构化错误
        out = get_sector_stocks("801159", "2026-10-24", page=1)  # 次页空 → ok 空页（尾页语义）
        assert out["ok"] is True and out["items"] == [] and out["has_more"] is False
        assert len(calls) == 2

    def test_page_size_clamped(self, monkeypatch):
        calls = []

        def fake_post(url, params, ua):
            calls.append(params["st"])
            return {"errcode": 0, "list": []}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        with pytest.raises(KplRankingError):
            get_sector_stocks("801159", "2026-10-24", page=0, page_size=5000)
        assert calls == [svc._STOCKS_MAX_PAGE_SIZE]   # 护栏上限


class TestThrottleDiscipline:
    def test_min_interval_enforced(self, monkeypatch):
        # 纪律：单发间隔 ≥2s（handoff §六）——节流在 _post_form 内，须打真 HTTP 层验证
        slept = []

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"errcode":0,"list":[]}'

        monkeypatch.setattr(svc.time, "sleep", lambda s: slept.append(s))
        monkeypatch.setattr(svc.urllib.request, "urlopen", lambda req, timeout: _FakeResp())
        svc._last_request_at = time.time()  # 刚发过一发 → 必须等待
        svc._post_form("https://apphis.longhuvip.com/w1/api/index.php", {}, "ad")
        assert slept and slept[0] > 0
