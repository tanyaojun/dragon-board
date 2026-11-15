# -*- coding: utf-8 -*-
"""KPL 最强风口协议层（GetFengKListBest）：13 位行解析 + 缓存 + pytest 护栏（全 mock）。

口径：13 位行数组位置语义来自 H5 getRangeLi_fk 逐位逆向（模块头）；缺位不补 0
（partial 透出）；State=0 付费墙 fail-visible；pytest 禁真实调用（红线 7）。
"""
import pytest

from backend.services import kpl_stock_fengkou as svc

ROW_FULL = ["600410", "华胜天成", "5871", "1", "10.00", "12345678", "", "1",
            "20000000", "-8000000", "AI应用、机器人概念", 1763000200,
            "AI应用、机器人概念"]


class TestParseFengkouRow:
    def test_full_row_mapped_raw_kept(self):
        out = svc.parse_fengkou_row(ROW_FULL)
        assert out["stock_id"] == "600410"
        assert out["name"] == "华胜天成"
        assert out["strength"] == "5871"
        assert out["trend_state"] == "1"
        assert out["change_pct"] == "10.00"
        assert out["main_net"] == "12345678"
        assert out["name_red"] is True
        assert out["main_buy"] == "20000000"
        assert out["main_sell"] == "-8000000"
        assert out["boards"] == ["AI应用", "机器人概念"]
        assert out["hot_boards"] == ["AI应用", "机器人概念"]
        assert out["peak_time"] == "10:16"
        assert out["raw"] == ROW_FULL and out["raw_len"] == 13
        assert "partial" not in out
        assert out["unknown6"] == ""   # 未确认位原样保留，不猜语义

    def test_short_row_partial_no_zero_fill(self):
        out = svc.parse_fengkou_row(["002739", "儒意电影", "2684"])
        assert out["strength"] == "2684"
        assert out["change_pct"] is None and out["main_net"] is None
        assert out["boards"] == [] and out["peak_time"] is None
        assert out["partial"] is True
        assert "main_net" in out["missing_fields"]

    def test_boards_split_empty_and_hot_intersection_semantics(self):
        out = svc.parse_fengkou_row(["300528", "幸福蓝海", "1616", "-1", "20.01",
                                     "", "", "", "", "",
                                     "影视院线、短剧", 0, "影视院线"])
        assert out["boards"] == ["影视院线", "短剧"]
        assert out["hot_boards"] == ["影视院线"]   # ∩ 由前端取角标，此处仅透传
        assert out["peak_time"] is None           # epoch<=0 → None（不猜）

    def test_non_string_boards_degrade_to_empty(self):
        out = svc.parse_fengkou_row(["000001", "x", "1", "0", "0", "0", "", "",
                                     "", "", 123, 0, None])
        assert out["boards"] == [] and out["hot_boards"] == []


class TestParseFengkou:
    def test_state_1_payload(self):
        r = svc.parse_fengkou({"State": 1, "Day": "2026-11-14", "Time": 1763000200,
                               "Tip": "", "List": [ROW_FULL]})
        assert r["ok"] is True and r["day"] == "2026-11-14"
        assert r["n_rows"] == 1 and r["partial_n"] == 0
        assert r["time_hhmm"] == "10:16"

    def test_state_0_vip_locked_fail_visible(self):
        r = svc.parse_fengkou({"State": 0, "Day": "2026-11-14", "Tip": "开通功能",
                               "List": []})
        assert r["ok"] is False and r["degraded"] is True
        assert r["reason"] == "vip_locked" and r["state"] == 0
        assert r["items"] == [] and "开通功能" in r["error"]

    @pytest.mark.parametrize("payload", [{"State": 1, "List": None},
                                         {"State": 1, "List": {"a": 1}}, {}])
    def test_unexpected_list_degraded(self, payload):
        r = svc.parse_fengkou(payload)
        assert r["ok"] is False and r["degraded"] is True
        assert r["reason"] == "unexpected_payload"


class TestFetchAndGuard:
    def test_cache_hit_no_refetch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form",
                            lambda *a, **k: calls.append(a)
                            or {"State": 1, "Day": "2026-11-14", "List": [ROW_FULL]})
        r1 = svc.fetch_fengkou_raw()
        r2 = svc.fetch_fengkou_raw()
        assert len(calls) == 1 and r1 is r2
        svc._CACHE.clear()

    def test_day_routes_to_his_host_with_day_param(self, monkeypatch):
        seen = {}

        def fake_post(url, params, ua):
            seen["url"] = url
            seen["params"] = params
            return {"State": 1, "Day": "2026-11-13", "List": []}

        monkeypatch.setattr(svc, "_post_form", fake_post)
        svc.fetch_fengkou_raw(day="2026-11-13")
        assert seen["url"] == svc._HOST_HIS
        assert seen["params"]["Day"] == "20261113"
        svc._CACHE.clear()

    def test_time_pass_through(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(svc, "_post_form",
                            lambda url, params, ua: seen.update(params)
                            or {"State": 1, "List": []})
        svc.fetch_fengkou_raw(time_hhmm="1430")
        assert seen["Time"] == "1430" and seen["c"] == "StockFengKData"
        svc._CACHE.clear()

    def test_pytest_guard_blocks_real_call(self):
        # 生产 _post_form 未被 monkeypatch 时，pytest 进程内直接拒绝（红线 7）
        svc._CACHE.clear()
        with pytest.raises(RuntimeError, match="红线 7"):
            svc.fetch_fengkou_raw()

    def test_cache_key_normalized_dashless_day(self, monkeypatch):
        # 评审 P2："2026-11-13" 与 "20261113" 必须归一为同一条缓存（同上游请求不重复发）
        calls = []
        monkeypatch.setattr(svc, "_post_form",
                            lambda url, params, ua: calls.append(params.get("Day"))
                            or {"State": 1, "Day": "2026-11-13", "List": []})
        svc.fetch_fengkou_raw(day="2026-11-13")
        r2 = svc.fetch_fengkou_raw(day="20261113")
        assert len(calls) == 1 and calls[0] == "20261113" and r2["Day"] == "2026-11-13"
        svc._CACHE.clear()

    def test_get_fengkou_reraises_pytest_guard(self):
        # 评审 P2：宽 except 不得吞护栏 RuntimeError（响亮失败优先于降级载荷）
        svc._CACHE.clear()
        with pytest.raises(RuntimeError, match="红线 7"):
            svc.get_fengkou()

    def test_get_fengkou_kpl_errcode_degraded_login_flag(self, monkeypatch):
        from backend.services.kpl_ranking_service import KplRankingError

        def raise_1001(url, params, ua):
            raise KplRankingError("kpl_errcode", errorCode="1001", error="登录状态失效！")

        monkeypatch.setattr(svc, "_post_form", raise_1001)
        r = svc.get_fengkou()
        assert r["ok"] is False and r["degraded"] is True
        assert r["reason"] == "1001" and r["login_expired"] is True
        assert r["items"] == []
