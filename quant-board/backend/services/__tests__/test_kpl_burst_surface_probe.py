"""爆发指纹隔离探针工具 mock 测试（全 mock，零真实连接，README §六）。

验证变体订阅面构成（隔离变量正确）+ 控制变量固定 + 受控池注入 + 单会话禁重连
死因分类 + 帧族分组。探针预登记：docs/kpl-socket/
burst-fingerprint-isolation-probe-preregistration-20261117.md。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import probe_kpl_burst_surface as probe  # noqa: E402

from backend.services import kpl_daban_protocol as daban  # noqa: E402
from backend.services import kpl_socket_protocol as proto  # noqa: E402


class _Codec:
    def wbe(self, *a):
        return "ab" * 95

    def enc(self, p):
        return b"\xaa" + p

    def dec(self, h):
        b = bytes.fromhex(h)
        return b[1:] if b[:1] == b"\xaa" else b

    def exec(self, *a):
        return 1


def _mk(variant, pool=None, **kw):
    base = dict(device_id="t", user_id="0", token="", stock_ids=["801044"],
                host="127.0.0.1", port=1, human_delay=False)
    base.update(kw)
    return probe.ProbeSurfaceCollector(_Codec(), variant, pool=pool, **base)


class TestVariantSurface:
    def test_s0_globals_only(self):
        svc = _mk("S0")
        assert svc._daban_subs is True
        assert svc._daban_list_pids == ()          # 无 2103 页
        assert svc._zt_reason_subs is False        # 无 per-stock
        assert svc._theme_subs is False

    def test_s1_pages_no_perstock(self):
        svc = _mk("S1")
        assert svc._daban_list_pids == (0, 8, 6, 1, 2, 3)
        assert svc._daban_list_pages == 7
        assert svc._zt_reason_subs is False and svc._theme_subs is False

    def test_s2_perstock_no_pages(self):
        svc = _mk("S2", pool=["000001", "000002"])
        assert svc._daban_list_pids == ()
        assert svc._zt_reason_subs is True and svc._theme_subs is True

    def test_s3_full(self):
        svc = _mk("S3", pool=["000001"])
        assert svc._daban_list_pids == (0, 8, 6, 1, 2, 3)
        assert svc._zt_reason_subs is True and svc._theme_subs is True

    def test_control_variables_fixed(self):
        svc = _mk("S0")
        assert svc._ka_mode == "off"               # 消除 610 因素
        assert svc._sub_batch_mode == "direct"     # 不引入 211 风控面
        assert svc._sub_unique_id is True
        assert svc._sub_registry_enabled is True
        assert svc._stock_detail_subs is False     # 详情阴性源不在爆发面
        assert svc._daban_lhb is False and svc._lhb_realtime is False


class TestControlledPool:
    def test_s2_pool_override(self):
        svc = _mk("S2", pool=["000001", "600000"])
        assert svc._pool_stock_ids() == ["000001", "600000"]

    def test_s0_no_pool_uses_super(self):
        svc = _mk("S0")
        assert svc._pool_stock_ids() == []         # 无 2103 pid=1 快照

    def test_per_stock_requires_pool(self):
        with pytest.raises(ValueError):
            _mk("S2")
        with pytest.raises(ValueError):
            _mk("S3", pool=[])

    def test_unknown_variant(self):
        with pytest.raises(ValueError):
            _mk("S9")


class TestSingleSessionDeath:
    def test_run_loop_records_rst_no_reconnect(self, monkeypatch):
        svc = _mk("S0")

        def _rst():
            raise ConnectionResetError(10054, "burst RST")

        monkeypatch.setattr(svc, "_session", _rst)
        svc._run_loop()
        assert svc._stats["sessions"] == 1         # 单会话禁重连
        assert svc._last_death_cause == "rst_10054"
        assert svc._death_cause_counts == {"rst_10054": 1}
        assert svc._status == "stopped"
        deaths = [e for e in svc._history if e["type"] == "session_death"]
        assert deaths and deaths[-1]["cause"] == "rst_10054"

    def test_run_loop_clean_eof(self, monkeypatch):
        svc = _mk("S0")
        monkeypatch.setattr(svc, "_session", lambda: None)
        svc._session_streaming = True              # 模拟进入收流后服务器干净关连
        svc._run_loop()
        assert svc._last_death_cause == "eof_clean"
        assert svc._stats["sessions"] == 1


class TestFrameFamily:
    def test_grouping(self):
        f = probe._frame_family
        assert f(daban.CMD_DABAN_STOCK_LIST) == "2103_pages"
        assert f(proto.CMD_HQ_REASONS) == "2203_perstock"
        assert f(proto.CMD_STOCK_RELATED_THEME) == "2013_perstock"
        assert f(proto.CMD_GROUP_QUOTAS) == "3001_3006"
        assert f(proto.CMD_HQ_ID_LIST) == "3001_3006"
        assert f(daban.CMD_ZD_STAT) == "globals"
        assert f(2100) == "globals"