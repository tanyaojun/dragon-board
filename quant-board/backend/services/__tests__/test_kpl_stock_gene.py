# -*- coding: utf-8 -*-
"""KPL 涨停基因协议层（GetZhangTingGene）：六元数组解析 + 缓存 + pytest 护栏（全 mock）。

口径：六元数组原样保留 raw，具名字段由 GENE_FIELDS 映射；缺位不补 0（partial 透出）；
统计窗口上游未标注 → window_note 原样透出，禁止自算/反推。
"""
import pytest

from backend.services import kpl_stock_gene as svc


class TestParseZtGene:
    def test_six_elements_mapped_raw_kept(self):
        out = svc.parse_zt_gene({"StockID": "301697", "List": [4, 1, 50, 100, 0, 50],
                                 "ttag": 0.0013, "errcode": "0"})
        assert out["ok"] is True and out["stock_id"] == "301697"
        assert out["gene"] == {"zt_count": 4, "premium5_count": 1, "next_day_red_pct": 50,
                               "first_seal_pct": 100, "first_broken_pct": 0,
                               "lianban_pct": 50}
        assert out["raw"] == [4, 1, 50, 100, 0, 50] and out["raw_len"] == 6
        assert out["gene_labels"]["zt_count"] == "涨停次数"
        assert "未标注统计窗口" in out["window_note"]
        assert "partial" not in out

    def test_short_list_partial_no_zero_fill(self):
        """缺位不补 0（fail-visible）：missing_fields 透出，脏值也不当数值用。"""
        out = svc.parse_zt_gene({"StockID": "000525", "List": [4, {"bad": 1}]})
        assert out["ok"] is True and out["partial"] is True
        assert out["gene"]["zt_count"] == 4
        assert out["gene"]["premium5_count"] is None
        assert out["gene"]["lianban_pct"] is None
        assert set(out["missing_fields"]) == {"premium5_count", "next_day_red_pct",
                                             "first_seal_pct", "first_broken_pct",
                                             "lianban_pct"}
        assert out["raw"] == [4, {"bad": 1}]

    @pytest.mark.parametrize("payload", [{"List": None}, {"List": {"a": 1}}, {}])
    def test_unexpected_payload_degraded(self, payload):
        out = svc.parse_zt_gene(payload, stock_id="301697")
        assert out["ok"] is False and out["degraded"] is True
        assert out["reason"] == "unexpected_payload" and out["stock_id"] == "301697"


class TestFetchAndGuard:
    def test_cache_hit_no_refetch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form",
                            lambda *a, **k: calls.append(a) or {"StockID": "301697",
                                                                "List": [4, 1, 50, 100, 0, 50]})
        r1 = svc.fetch_zt_gene_raw("301697")
        r2 = svc.fetch_zt_gene_raw("301697")
        assert len(calls) == 1 and r1 is r2
        svc._CACHE.clear()

    def test_ttl_expiry_refetch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(svc, "_post_form",
                            lambda *a, **k: calls.append(a) or {"StockID": "000525", "List": [1]})
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0)
        svc.fetch_zt_gene_raw("000525")
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0 + svc._CACHE_TTL_SECONDS + 1)
        svc.fetch_zt_gene_raw("000525")
        assert len(calls) == 2
        svc._CACHE.clear()

    def test_pytest_guard_blocks_real_call(self):
        """红线 7：pytest 内未 mock `_post_form` 时硬护栏拒绝真实调用（结构化降级）。"""
        svc._CACHE.clear()
        out = svc.get_zt_gene("301697")
        assert out["ok"] is False and out["degraded"] is True
        assert out["reason"] == "RuntimeError"
        assert "红线 7" in out["error"]

    def test_get_zt_gene_errcode_degraded(self, monkeypatch):
        class _Err(Exception):
            errorCode = "1020"
            error = "严格白名单"
        monkeypatch.setattr(svc, "_post_form", lambda *a, **k: (_ for _ in ()).throw(_Err()))
        out = svc.get_zt_gene("301697")
        assert out["ok"] is False and out["reason"] == "1020" and out["stock_id"] == "301697"

    def test_get_zt_gene_ok(self, monkeypatch):
        monkeypatch.setattr(svc, "_post_form",
                            lambda *a, **k: {"StockID": "301697", "List": [4, 1, 50, 100, 0, 50]})
        out = svc.get_zt_gene("301697")
        assert out["ok"] is True and out["gene"]["lianban_pct"] == 50
        svc._CACHE.clear()