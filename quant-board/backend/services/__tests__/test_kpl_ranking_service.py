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

    def test_sons_parsed_and_paired(self, monkeypatch):
        # 2026-10-28 实测合同：list_son=父板块 id 列表、list_soninfo=同 19 列子板块行，
        # 等长按位配对（App 二级板块行的唯一来源，非客户端强度过滤）
        def fake_post(url, params, ua):
            return {"errcode": 0,
                    "list": [["801159", "机器人概念", 24234, 2.38, 0, 1, 0, 0, 0, 0]],
                    "list_son": [801159],
                    "list_soninfo": [["801928", "智元机器人", 2835, 4.051, 0.239,
                                      1, 0, 0, 0, 0]]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-28")
        assert list(out["sons"].keys()) == ["801159"]
        son = out["sons"]["801159"][0]
        assert son["plate_id"] == "801928" and son["name"] == "智元机器人"
        assert son["strength"] == 2835 and "raw" in son

    def test_sons_unpaired_fail_visible(self, monkeypatch):
        # list_son 与 list_soninfo 长度不等 → 不猜配对，结构化透出（不伪装成无子板块）
        def fake_post(url, params, ua):
            return {"errcode": 0,
                    "list": [["801159", "机器人概念", 24234, 2.38, 0, 1, 0, 0, 0, 0]],
                    "list_son": [801159, 801001],
                    "list_soninfo": [["801928", "智元机器人", 2835, 4.051, 0.239,
                                      1, 0, 0, 0, 0]]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-29")
        assert out["sons"] == {}
        assert out["sons_unpaired"]["parents"] == ["801159", "801001"]
        assert out["sons_unpaired"]["row_count"] == 1

    def test_sons_absent_keys_means_empty(self, monkeypatch):
        # 上游确认无子板块（响应无 list_son 键）→ sons={} 且无 unpaired 标记
        def fake_post(url, params, ua):
            return {"errcode": 0,
                    "list": [["801159", "机器人概念", 24234, 2.38, 0, 1, 0, 0, 0, 0]]}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        out = get_sector_ranking("2026-10-30")
        assert out["sons"] == {} and "sons_unpaired" not in out


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


class TestDabanListHistory:
    """2103 历史回看读口（2026-10-28 白名单参数语义）：全 mock 上游。"""

    HIST_ROW = ["002639", "雪人股份", 0, "", 5.24, 0, 0, 0, 0, "", 0,
                "制雪产业", 620244653, 2231432699, 24.59, 8865169443,
                "廖", 14.27]

    def _fake_post(self, calls, errcode=0, rows=None):
        def fake(url, params, ua):
            calls.append(dict(params))
            return {"errcode": errcode,
                    "list": rows if rows is not None else [list(self.HIST_ROW)],
                    "day": "2026-10-27"}
        return fake

    def test_whitelist_params_only(self, monkeypatch):
        # 上游严格白名单（实测 2026-10-28）：Day 外多传任意键一律 1020——不得出现
        # PidType/Type/Order/Is_st/Index/st/Filter 家族
        calls = []
        monkeypatch.setattr(svc, "_post_form", self._fake_post(calls))
        svc.get_daban_list_history("2026-10-27", 8)
        assert len(calls) == 1
        keys = set(calls[0])
        assert keys == {"a", "c", "Day", "apiv", "VerSion", "PhoneOSNew", "Red",
                        "UserID", "DeviceID", "Token"}
        assert calls[0]["Day"] == "2026-10-27"

    def test_row_parsed_and_note_present(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form", self._fake_post(calls))
        payload = svc.get_daban_list_history("2026-10-27", 8)
        assert payload["ok"] is True and payload["pid_type"] == 8
        assert payload["items"][0]["stock_id"] == "002639"
        assert payload["items"][0]["pct"] == 5.24
        assert "不认页签参数" in payload["note"]

    def test_empty_list_fail_visible_and_not_cached(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form", self._fake_post(calls, rows=[]))
        with pytest.raises(KplRankingError) as ei:
            svc.get_daban_list_history("2026-10-27", 0)
        assert ei.value.reason == "upstream_empty_list"
        # 异常空态不进缓存：再拉仍打上游（30s TTL 只兜成功态）
        with pytest.raises(KplRankingError):
            svc.get_daban_list_history("2026-10-27", 0)
        assert len(calls) == 2

    def test_cache_shared_by_date_across_tabs(self, monkeypatch):
        # 缓存 key 按日共享（上游对 pid_type 不敏感）：三页签同日 30s 内最多 1 发上游
        calls = []
        monkeypatch.setattr(svc, "_post_form", self._fake_post(calls))
        p8 = svc.get_daban_list_history("2026-10-27", 8)
        p0 = svc.get_daban_list_history("2026-10-27", 0)
        p6 = svc.get_daban_list_history("2026-10-27", 6)
        assert len(calls) == 1
        assert [p["pid_type"] for p in (p8, p0, p6)] == [8, 0, 6]
        assert p8["items"] == p0["items"] == p6["items"]


class TestDabanPrevDayBasis:
    """竞昨比原料（昨日日K 昨收/昨量，腾讯 ifzq）：全 mock HTTP。"""

    def test_prev_bar_parse(self, monkeypatch):
        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"sh603028": {"qfqday": [
                    ["2026-10-24", "9.00", "9.10", "9.20", "8.90", "100000.0"],
                    ["2026-10-27", "9.15", "9.66", "9.70", "9.10", "200000.0"],
                    ["2026-10-28", "9.70", "9.80", "9.90", "9.60", "30000.0"],
                ]}}}

        captured = {}

        def fake_get(url, headers=None, trust_env=None, timeout=None):
            captured["url"] = url
            return _FakeResp()

        monkeypatch.setattr(svc.httpx, "get", fake_get)
        b = svc._fetch_tencent_prev_bar("603028", "2026-10-28")
        # 只取 date 之前最近一根（当日盘中K不得混入）；量列不复权
        assert b == {"prev_date": "2026-10-27", "prev_close": 9.66,
                     "prev_volume_shou": 200000.0}
        assert "param=sh603028,day,2026-10-08,2026-10-28,20,qfq" in captured["url"]

    def test_no_prev_kline_fail_visible(self, monkeypatch):
        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"sz888888": {"qfqday": []}}}

        monkeypatch.setattr(svc.httpx, "get", lambda *a, **k: _FakeResp())
        with pytest.raises(KplRankingError) as ei:
            svc._fetch_tencent_prev_bar("888888", "2026-10-28")
        assert ei.value.reason == "no_prev_kline"

    def test_batch_and_fail_isolation(self, monkeypatch):
        calls = []

        def fake_fetch(code, date):
            calls.append(code)
            if code == "999999":
                raise KplRankingError("no_prev_kline", code=code)
            return {"prev_date": "2026-10-27", "prev_close": 10.0,
                    "prev_volume_shou": 50000.0}

        monkeypatch.setattr(svc, "_fetch_tencent_prev_bar", fake_fetch)
        svc._basis_cache.clear()
        out = svc.get_daban_prev_day_basis("2026-10-28", ["603028", "999999"])
        assert out["basis"]["603028"]["prev_close"] == 10.0
        assert out["missing"] == ["999999"]
        # 失败单股 10 分钟内不重试（防 4s 页面轮询打爆上游）；命中股不重复拉
        out2 = svc.get_daban_prev_day_basis("2026-10-28", ["603028", "999999"])
        assert calls.count("603028") == 1 and calls.count("999999") == 1
        assert out2["missing"] == ["999999"]

    def test_input_guards(self):
        svc._basis_cache.clear()
        with pytest.raises(KplRankingError):
            svc.get_daban_prev_day_basis("2026-10-28", [])
        with pytest.raises(KplRankingError) as ei:
            svc.get_daban_prev_day_basis("2026-10-28", [f"c{i}" for i in range(900)])
        assert ei.value.reason == "too_many_codes"


# ── 市场雷达/直播流（2026-10-28）：parse_radar_row + get_market_radar ──────────

def test_parse_radar_row_normalizes_and_dedups():
    row = svc.parse_radar_row({"time": 1793158191, "status": "涨停回封",
                               "stock_name": "科达利", "plate_type": 1,
                               "status_color": 1, "zf": "", "stockid": "002850",
                               "LBstatus": "首板", "content": "涨停打开后，再次封涨停，当前封单2.00亿元",
                               "content2": "当前封单2.00亿"})
    assert row is not None
    assert row["id"] == "1793158191:002850:涨停回封"
    assert row["code"] == "002850" and row["name"] == "科达利"
    assert row["lb_status"] == "首板" and row["color"] == 1
    assert row["zf"] is None and row["content2"].startswith("当前封单")
    assert ":" in row["time"]   # HH:MM:SS
    # 缺 stockid / 非法时间 → None（计入 skipped，不猜补）
    assert svc.parse_radar_row({"time": 1, "status": "x", "stock_name": "n"}) is None
    assert svc.parse_radar_row({"time": "abc", "stockid": "002850"}) is None


def test_radar_sorted_skipped_and_cached(monkeypatch):
    payload = {"list": [
        {"time": 1793158191, "status": "涨停回封", "stock_name": "科达利",
         "stockid": "002850", "LBstatus": "首板", "status_color": 1, "zf": "",
         "content": "c1", "content2": "", "plate_type": 1},
        {"time": "bad", "stockid": "1"},                      # 非法 → skipped
        {"time": 1793158100, "status": "封死涨停", "stock_name": "正强股份",
         "stockid": "301382", "LBstatus": "首板", "status_color": 1, "zf": "",
         "content": "c2", "content2": "", "plate_type": 1},
    ], "date": "2026-10-28", "errcode": 0}
    calls = []
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(a), payload)[1])
    out = svc.get_market_radar(st=60)
    assert out["ok"] and out["date"] == "2026-10-28"
    assert [it["code"] for it in out["items"]] == ["002850", "301382"]   # ts 降序
    assert out["skipped"] == 1
    # 5s TTL 命中：不再发上游
    out2 = svc.get_market_radar(st=60)
    assert len(calls) == 1 and out2["items"] == out["items"]


def test_radar_empty_not_cached_and_error_passthrough(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(1), {"list": [], "errcode": 0})[1])
    out = svc.get_market_radar()
    assert out["ok"] and out["items"] == []
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(1), {"list": [], "errcode": 0})[1])
    svc.get_market_radar()          # 空不缓存 → 再次请求真的发上游
    assert len(calls) == 2
    def boom(*a, **k):
        raise KplRankingError("upstream_http_502", url="x")
    monkeypatch.setattr(svc, "_post_form", boom)
    with pytest.raises(KplRankingError):
        svc.get_market_radar()


# ── 直播解说流（2026-10-28）：parse_live_row + get_live_commentary ──────────────

def test_parse_live_row_normalizes():
    row = svc.parse_live_row({
        "ID": "94474", "Time": 1793158020, "Type": "0",
        "Comment": "机器人持续强势，各分支轮动走强（该内容由AI大模型根据行情自动生成）",
        "PlateCode": "801159", "PlateName": "机器人概念", "PlateJE": "7354203034.000",
        "PlateZDF": "3.87", "UserName": "xqm",
        "Stock": [["688836", "宇树科技", 12.49], ["688585", "上纬新材", 20], ["bad"]],})
    assert row["id"] == "zb:94474"
    assert row["plate_code"] == "801159" and row["user"] == "xqm"
    assert row["ts"] == 1793158020 and row["plate_name"] == "机器人概念"
    assert row["plate_pct"] == 3.87
    assert row["stocks"] == [{"code": "688836", "name": "宇树科技", "pct": 12.49},
                             {"code": "688585", "name": "上纬新材", "pct": 20}]
    # 缺 Time / Comment → None
    assert svc.parse_live_row({"Time": 1, "Comment": ""}) is None
    assert svc.parse_live_row({"Time": "x", "Comment": "c"}) is None


def test_live_sorted_cached_and_error(monkeypatch):
    payload = {"List": [
        {"ID": "2", "Time": 1793158020, "Comment": "b", "Type": "0", "Stock": []},
        {"ID": "1", "Time": 1793158200, "Comment": "a", "Type": "0",
         "Stock": [["688836", "宇树科技", 12.49]]},
    ], "date": "2026-10-28", "Notice": "直播即将开始！！！", "errcode": 0}
    calls = []
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(1), payload)[1])
    out = svc.get_live_commentary(st=30)
    assert out["ok"] and out["date"] == "2026-10-28"
    assert out["notice"].startswith("直播")
    assert [it["id"] for it in out["items"]] == ["zb:1", "zb:2"]        # ts 降序
    assert out["items"][0]["stocks"][0]["name"] == "宇树科技"
    out2 = svc.get_live_commentary(st=30)
    assert len(calls) == 1 and out2 == out                              # 15s TTL 命中
    def boom(*a, **k):
        raise KplRankingError("upstream_http_502", url="x")
    svc._cache.clear()                                                  # 否则 15s TTL 命中不发上游
    monkeypatch.setattr(svc, "_post_form", boom)
    with pytest.raises(KplRankingError):
        svc.get_live_commentary()


def test_live_empty_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(1), {"List": [], "Notice": "", "errcode": 0})[1])
    svc.get_live_commentary()
    monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (calls.append(1), {"List": [], "Notice": "", "errcode": 0})[1])
    svc.get_live_commentary()
    assert len(calls) == 2      # 空 items 不缓存


def test_live_credentials_from_common_source_and_not_leaked(monkeypatch):
    """凭据红线钉死：UserID/Token/DeviceID 只来自公共出口、只进请求参数，不入返回 payload。"""
    from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS
    captured = {}
    payload = {"List": [{"ID": "1", "Time": 1793158020, "Comment": "c", "Type": "0", "Stock": []}],
               "date": "2026-10-28", "Notice": "", "errcode": 0}
    def fake_post(url, params, ua):
        captured["url"], captured["params"] = url, params
        return payload
    monkeypatch.setattr(svc, "_post_form", fake_post)
    out = svc.get_live_commentary()
    # 凭据=公共出口原值，逐键钉死（防有人改成本地硬编码或遗漏）
    for key in ("UserID", "Token", "DeviceID"):
        assert captured["params"][key] == KPL_APP_BASE_PARAMS[key]
    # 返回体（含 items 深处）不得携带任何凭据键
    dumped = repr(out)
    for key in ("UserID", "Token", "DeviceID"):
        assert key not in dumped
        assert KPL_APP_BASE_PARAMS[key] not in dumped
    # 结构化异常 detail 只带 url，不带 params
    def boom(url, params, ua):
        raise KplRankingError("upstream_http_502", url=url)
    svc._cache.clear()                                  # 否则 15s TTL 命中不发上游
    monkeypatch.setattr(svc, "_post_form", boom)
    with pytest.raises(KplRankingError) as ei:
        svc.get_live_commentary()
    assert "Token" not in str(ei.value.detail) and KPL_APP_BASE_PARAMS["Token"] not in str(ei.value.detail)


def _wait_stocks_meta(date, pred, timeout=5.0):
    """真实后台线程构建 → deadline 轮询（不 patch 全局 threading/time，防波及 pytest）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        e = svc._stocks_meta_cache.get(date) or {}
        if pred(e):
            return e
        time.sleep(0.02)
    raise AssertionError(f"stocks-meta 未在 {timeout}s 内到达预期态: {e.get('state')}")


def test_live_stocks_meta_index_building_then_done(monkeypatch):
    """直播个股 meta 索引（2026-10-29）：惰性后台构建 → hits/missed 如实分账。

    解说/雷达流不带 地位/换手/概念（此前前端硬编码 "--"）；唯一 KPL 口径来源=
    板块成分股接口。索引按 (date) 建，TTL 内二调零上游；不在板块宇宙如实 missed。
    """
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [
                            {"plate_id": "801159", "name": "机器人概念", "strength": 100}],
                         "sons": {}})
    def fake_stocks(pid, date, page=0, page_size=100):
        assert pid == "801159" and page == 0
        return {"ok": True, "date": date, "plate_id": pid, "page": 0,
                "page_size": page_size, "has_more": False,
                "items": [{"code": "603278", "name": "大业股份",
                           "rank_title": "龙一", "turnover": 12.3,
                           "board_status": "3天2板", "concept": "机器人,减速器"},
                          {"code": "000001", "name": "平安银行",
                           "rank_title": "", "turnover": 0.8,
                           "board_status": "", "concept": ""}]}
    monkeypatch.setattr(svc, "get_sector_stocks", fake_stocks)

    out = svc.get_live_stocks_meta(["603278", "300999"], "2026-10-28")
    assert out["ok"] is True
    entry = _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "done")
    assert len(entry["index"]) == 2
    # done 后重读：hits 分账 + missed 如实透出（不伪装命中）
    out2 = svc.get_live_stocks_meta(["603278", "300999"], "2026-10-28")
    assert out2["building"] is False
    assert out2["hits"]["603278"]["rank_title"] == "龙一"
    assert out2["hits"]["603278"]["concept"] == "机器人,减速器"
    assert out2["hits"]["603278"]["board_status"] == "3天2板"
    assert out2["missed"] == ["300999"]
    # TTL 内二调零上游：改 mock 为爆炸再读一次（不触发重建）
    def boom(*a, **k):
        raise AssertionError("索引 TTL 内不得重拉上游")
    monkeypatch.setattr(svc, "get_sector_ranking", boom)
    out3 = svc.get_live_stocks_meta(["603278"], "2026-10-28")
    assert out3["building"] is False and out3["hits"]["603278"]["turnover"] == 12.3
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_ranking_failure_is_error_state(monkeypatch):
    """排行失败 → error 态结构化透出（fail-visible），不伪装成空宇宙；下次调用自动重建。"""
    svc._stocks_meta_cache.clear()
    def boom(date):
        raise svc.KplRankingError("upstream_http_502", url="x")
    monkeypatch.setattr(svc, "get_sector_ranking", boom)
    out = svc.get_live_stocks_meta(["603278"], "2026-10-28")
    assert out["ok"] is True
    entry = _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "error")
    assert "upstream_http_502" in str(entry.get("error") or "")
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_build_crash_becomes_error_not_stuck_building(monkeypatch):
    """非业务异常兜底：构建崩溃 → error 态（不得让 entry 永远钉在 building）。"""
    svc._stocks_meta_cache.clear()
    def crash(date):
        raise RuntimeError("mocked crash")
    monkeypatch.setattr(svc, "get_sector_ranking", crash)
    svc.get_live_stocks_meta(["603278"], "2026-10-28")
    entry = _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "error")
    assert "build_crash" in str(entry.get("error") or "")
    svc._stocks_meta_cache.clear()


# ── 2026-10-29 §9.2/§9.7 勘察处置：层3 1020 结构化 + 盘前空排行不伪装 done ──

def test_sector_stocks_1020_structured_as_date_state(monkeypatch):
    """层3 1020 结构化：判别探针实证历史日同参数可用 → 主因=当日盘前/数据未生成。

    不伪装空成分股、不误报凭据失效、不重包装为参数错；note 携带处置指引（盘后重试）。
    """
    monkeypatch.setattr(
        svc, "_post_form",
        lambda url, params, ua: {"errcode": 1020, "errmsg": "参数错误"})
    with pytest.raises(KplRankingError) as ei:
        get_sector_stocks("801159", "2099-01-01")
    assert ei.value.reason == "upstream_1020_date_state"
    assert ei.value.detail["date"] == "2099-01-01"
    assert ei.value.detail["plate_id"] == "801159"
    assert "数据未生成" in ei.value.detail["note"]


def test_sector_stocks_other_errcode_keeps_generic_reason(monkeypatch):
    """非 1020 业务错误不重包装（保留 kpl_errcode 原语义与 errorCode 明细）。"""
    monkeypatch.setattr(
        svc, "_post_form",
        lambda url, params, ua: {"errcode": 7, "errmsg": "other"})
    with pytest.raises(KplRankingError) as ei:
        get_sector_stocks("801159", "2099-01-02")
    assert ei.value.reason == "kpl_errcode"
    assert ei.value.detail["errorCode"] == "7"


def test_live_stocks_meta_empty_ranking_is_error_not_done(monkeypatch):
    """盘前/未生成：排行全零行被过滤后 items 空 → error 态，不伪装成 done 空 index。

    2026-10-29 层3 判别探针同源结论；error 态让下次调用自动重建（数据生成后可用）。
    """
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [], "sons": {}})
    def boom(*a, **k):
        raise AssertionError("空排行不得触发成分股扫描")
    monkeypatch.setattr(svc, "get_sector_stocks", boom)
    svc.get_live_stocks_meta(["603278"], "2026-10-28")
    entry = _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "error")
    assert "ranking_empty" in str(entry.get("error") or "")
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_partial_plate_failure_keeps_rest(monkeypatch):
    """单板块失败 → failed_plates 记账且其余板块照常（增量失败隔离）。"""
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [
                            {"plate_id": "801159", "name": "机器人概念", "strength": 100},
                            {"plate_id": "801573", "name": "半导体", "strength": 90}], "sons": {}})
    def fake_stocks(pid, date, page=0, page_size=100):
        if pid == "801573":                       # 失败板块放非探针位（探针=plates[0]）
            raise svc.KplRankingError("upstream_http_502", url="x")
        if pid == "801159":
            return {"ok": True, "date": date, "plate_id": pid, "page": 0,
                    "page_size": page_size, "has_more": False,
                    "items": [{"code": "000678", "name": "襄阳轴承", "rank_title": "龙一",
                               "turnover": 18.9, "board_status": "5连板", "concept": "机器人"}]}
        return {"ok": True, "date": date, "plate_id": pid, "page": 0,
                "page_size": page_size, "has_more": False,
                "items": [{"code": "603061", "name": "金海通", "rank_title": "龙二",
                           "turnover": 6.1, "board_status": "首板", "concept": "芯片"}]}
    monkeypatch.setattr(svc, "get_sector_stocks", fake_stocks)
    svc.get_live_stocks_meta(["603061"], "2026-10-28")
    entry = _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "done")
    assert entry["failed_plates"] == ["801573"]
    assert "000678" in entry["index"], "失败板块不得中断其余板块入库"
    out = svc.get_live_stocks_meta(["000678", "603061"], "2026-10-28")
    assert out["failedPlates"] == ["801573"]
    assert out["hits"]["000678"]["rank_title"] == "龙一"
    assert out["missed"] == ["603061"], "失败板块的成分股如实 missed（不伪装命中）"
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_stale_rebuild_keeps_old_index_available(monkeypatch):
    """TTL 过期重建：旧索引继续命中（stale 可用），重建后合并新数据。"""
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [
                            {"plate_id": "801159", "name": "机器人概念", "strength": 100}], "sons": {}})
    monkeypatch.setattr(svc, "get_sector_stocks",
                        lambda pid, date, page=0, page_size=100:
                        {"ok": True, "date": date, "plate_id": pid, "page": 0,
                         "page_size": page_size, "has_more": False,
                         "items": [{"code": "603278", "name": "大业股份", "rank_title": "龙一",
                                    "turnover": 12.3, "board_status": "3天2板",
                                    "concept": "机器人"}]})
    svc.get_live_stocks_meta(["603278"], "2026-10-28")
    _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "done")
    # 把 entry 调老 → 触发 stale 重建
    with svc._stocks_meta_lock:
        svc._stocks_meta_cache["2026-10-28"]["built_at"] -= svc._STOCKS_META_TTL_SECONDS + 1
    out = svc.get_live_stocks_meta(["603278"], "2026-10-28")
    assert out["building"] is True
    assert "603278" in out["hits"], "重建期间旧索引必须继续可用（stale 可用）"
    _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "done")
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_building_partial_hits_visible(monkeypatch):
    """building 期间已构建部分可被读口命中（渐进可用），missed 不预判。"""
    svc._stocks_meta_cache.clear()
    with svc._stocks_meta_lock:
        svc._stocks_meta_cache["2026-10-28"] = {
            "state": "building",
            "index": {"603278": {"rank_title": "龙一", "turnover": 12.3,
                                 "board_status": "3天2板", "concept": "机器人",
                                 "plate_id": "801159"}},
            "failed_plates": [], "built_at": time.time(), "error": None}
    out = svc.get_live_stocks_meta(["603278", "300999"], "2026-10-28")
    assert out["building"] is True
    assert out["hits"]["603278"]["rank_title"] == "龙一", "构建中已命中部分必须可见"
    assert out["missed"] == [], "building 期间不得把未扫到的股预判为 missed"
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_error_rebuild_cooldown(monkeypatch):
    """error 态重建最小间隔（review P1-2）：冷却内不重起线程，冷却过后自动重建。"""
    svc._stocks_meta_cache.clear()
    calls = {"n": 0}

    def boom(date):
        calls["n"] += 1
        raise svc.KplRankingError("upstream_http_502", url="x")

    monkeypatch.setattr(svc, "get_sector_ranking", boom)
    svc.get_live_stocks_meta(["603278"], "2026-10-28")
    _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "error")
    out = svc.get_live_stocks_meta(["603278"], "2026-10-28")     # 冷却内
    assert out["building"] is False and calls["n"] == 1, "冷却内不得重起构建线程"
    # 冷却过期（last_attempt_at 调老）→ 允许重建
    with svc._stocks_meta_lock:
        svc._stocks_meta_cache["2026-10-28"]["last_attempt_at"] -= svc._STOCKS_META_RETRY_SECONDS + 1
    svc.get_live_stocks_meta(["603278"], "2026-10-28")
    _wait_stocks_meta("2026-10-28", lambda e: e.get("state") == "error" and calls["n"] >= 2)
    assert calls["n"] == 2
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_falls_back_when_today_layer3_unavailable(monkeypatch):
    """当日层3 查史盘中不可用（2026-10-29 实测 1020_date_state）→ 回退上一交易日，
    fb 透出、昨日数据正常入库；连板/换手/地位/概念照常命中。"""
    svc._stocks_meta_cache.clear()

    def fake_stocks(pid, date, page=0, page_size=100):
        if date == "2026-10-29":
            raise svc.KplRankingError("upstream_1020_date_state", url="x")
        return {"ok": True, "date": date, "plate_id": pid, "page": 0,
                "page_size": page_size, "has_more": False,
                "items": [{"code": "000678", "name": "襄阳轴承", "rank_title": "龙一",
                           "turnover": 18.89, "board_status": "5连板",
                           "concept": "机器人概念"}]}

    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [
                            {"plate_id": "801159", "name": "机器人概念", "strength": 100}],
                         "sons": {}})
    monkeypatch.setattr(svc, "get_sector_stocks", fake_stocks)
    svc.get_live_stocks_meta(["000678"], "2026-10-29")
    entry = _wait_stocks_meta("2026-10-29", lambda e: e.get("state") == "done")
    assert entry["index"]["000678"]["board_status"] == "5连板"
    out = svc.get_live_stocks_meta(["000678"], "2026-10-29")
    assert out["fb"] == "2026-10-28", "回退日必须 fb 透出（fail-visible，不伪装当日口径）"
    assert out["hits"]["000678"]["concept"] == "机器人概念"
    svc._stocks_meta_cache.clear()


def test_live_stocks_meta_all_dates_unavailable_is_error(monkeypatch):
    """近 5 个交易日层3 全不可用 → error 态（fail-visible，不伪装空宇宙）。"""
    svc._stocks_meta_cache.clear()

    def boom(pid, date, page=0, page_size=100):
        raise svc.KplRankingError("upstream_1020", url="x")

    monkeypatch.setattr(svc, "get_sector_ranking",
                        lambda date: {"ok": True, "date": date, "items": [
                            {"plate_id": "801159", "name": "机器人概念", "strength": 100}],
                         "sons": {}})
    monkeypatch.setattr(svc, "get_sector_stocks", boom)
    svc.get_live_stocks_meta(["000678"], "2026-10-29")
    entry = _wait_stocks_meta("2026-10-29", lambda e: e.get("state") == "error")
    assert "stocks_unavailable_5d" in str(entry.get("error") or "")
    svc._stocks_meta_cache.clear()


# ── 2026-10-29 直播横幅排查：孤立空/1020 板块 = 合法空宇宙，不得弹「构建失败」 ──

def _stock_row(code):
    # meta 构建器消费 get_sector_stocks 的已解析行（dict），不是原始数组
    return {"code": code, "name": f"股{code}", "rank_title": "龙一",
            "turnover": 12.3, "board_status": "3天2板", "concept": "机器人,减速器"}


def test_live_meta_isolated_empty_plate_not_failed(monkeypatch):
    """801574 场景回归：孤立板块 1020/空表 = 合法空宇宙——failedPlates 必须为空
    （不弹「部分板块构建失败」横幅），单列 emptyPlates 披露；其余板块照常入索引。"""
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking", lambda date: {
        "ok": True, "date": date,
        "items": [{"plate_id": "801159", "name": "机器人概念", "strength": 100},
                  {"plate_id": "801574", "name": "年报增长", "strength": 50}],
        "sons": {}})
    def fake_stocks(pid, date, page=0, page_size=100):
        if pid == "801574":
            # 当日盘中 1020（801574 实测）——孤立命中=空宇宙/未生成
            raise svc.KplRankingError("upstream_1020_date_state", plate_id=pid, date=date)
        return {"ok": True, "items": [_stock_row("603278")], "has_more": False}
    monkeypatch.setattr(svc, "get_sector_stocks", fake_stocks)
    monkeypatch.setattr(svc, "_stocks_meta_probe_eff_date", lambda date, pid: date)
    svc.get_live_stocks_meta(["603278"], "2026-10-29")
    entry = _wait_stocks_meta("2026-10-29", lambda e: e.get("state") == "done")
    assert entry.get("failed_plates") == [], "孤立空板块不得进 failedPlates（横幅根因）"
    assert entry.get("empty_plates") == ["801574"]
    assert "603278" in entry["index"]
    out = svc.get_live_stocks_meta(["603278"], "2026-10-29")
    assert out["emptyPlates"] == ["801574"] and out["failedPlates"] == []
    svc._stocks_meta_cache.clear()


def test_live_meta_all_plates_empty_is_error(monkeypatch):
    """全板块皆空/1020 = 凭据失效或数据未生成 → error 态（不伪装成 done 空索引）。"""
    svc._stocks_meta_cache.clear()
    def boom(pid, date, page=0, page_size=100):
        raise svc.KplRankingError("upstream_1020_date_state", plate_id=pid, date=date)
    monkeypatch.setattr(svc, "get_sector_ranking", lambda date: {
        "ok": True, "date": date,
        "items": [{"plate_id": "801159", "name": "机器人概念", "strength": 100},
                  {"plate_id": "801574", "name": "年报增长", "strength": 50}],
        "sons": {}})
    monkeypatch.setattr(svc, "get_sector_stocks", boom)
    monkeypatch.setattr(svc, "_stocks_meta_probe_eff_date", lambda date, pid: date)
    svc.get_live_stocks_meta(["603278"], "2026-10-29")
    entry = _wait_stocks_meta("2026-10-29", lambda e: e.get("state") == "error")
    assert "stocks_all_empty" in str(entry.get("error") or "")
    svc._stocks_meta_cache.clear()


def test_live_meta_real_failure_still_disclosed(monkeypatch):
    """网络类真失败（非空/非1020）仍进 failedPlates 透出（fail-visible 不放松）。"""
    svc._stocks_meta_cache.clear()
    monkeypatch.setattr(svc, "get_sector_ranking", lambda date: {
        "ok": True, "date": date,
        "items": [{"plate_id": "801159", "name": "机器人概念", "strength": 100},
                  {"plate_id": "801574", "name": "年报增长", "strength": 50}],
        "sons": {}})
    def fake_stocks(pid, date, page=0, page_size=100):
        if pid == "801574":
            raise svc.KplRankingError("upstream_http_502", url="x")
        return {"ok": True, "items": [_stock_row("603278")], "has_more": False}
    monkeypatch.setattr(svc, "get_sector_stocks", fake_stocks)
    monkeypatch.setattr(svc, "_stocks_meta_probe_eff_date", lambda date, pid: date)
    svc.get_live_stocks_meta(["603278"], "2026-10-29")
    entry = _wait_stocks_meta("2026-10-29", lambda e: e.get("state") == "done")
    assert entry.get("failed_plates") == ["801574"], "真失败必须照旧透出"
    assert entry.get("empty_plates") == []
    svc._stocks_meta_cache.clear()
