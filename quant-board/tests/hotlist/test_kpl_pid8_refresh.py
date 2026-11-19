# -*- coding: utf-8 -*-
"""pid8 3s 重请求 lane 测试（2026-11-19 密度根因修复，plan §3/§6；全 mock）。

源码依据（红线 9）：盯盘竞价页 BiddingZTQuotaFragment 继承
MVPTimerTaskFragment→BaseTimerTaskFragment 默认周期 3000ms，定时回调
Xf(666)→Pg()→p.j0(firstVisible,count)→a0(i,i2,true)→y(2103,true)
（0x40 订阅通道重发请求）。服务端按「请求-快照」回整页 burst，会话内无
周期更新——App 靠 3s 定时重请求取密度。
锁定：窗门控 [09:15,09:30)、3s 节拍、帧形态与 setup 6d 同款（pkg 0x40 +
ext 02 0837）、会话重置、send 失败 fail-visible+fail-fast、默认 on
（2026-11-19 用户裁决：socket 无客户端频控，采集不烧 token 无开火门）。
"""
import struct

import pytest

from backend.services import kpl_daban_protocol as daban
from backend.services import kpl_socket_protocol as proto
from backend.services.kpl_collector_service import KplCollectorService as K


class Codec:
    def enc(self, b):
        return b

    def dec(self, b):
        return b


class FakeSock:
    def __init__(self, fail_at=None):
        self.frames = []
        self.fail_at = fail_at

    def sendall(self, frame):
        if self.fail_at is not None and len(self.frames) >= self.fail_at:
            raise OSError(10054, "rst")
        self.frames.append(frame)


@pytest.fixture
def svc(monkeypatch):
    s = K(Codec(), pid8_refresh=True, daban_list_pages=7)
    monkeypatch.setattr(s, "_human_pause", lambda *a, **k: None)
    return s


@pytest.fixture
def in_window(monkeypatch):
    monkeypatch.setattr(K, "_auction_window_active", staticmethod(lambda now=None: True))


@pytest.fixture
def out_window(monkeypatch):
    monkeypatch.setattr(K, "_auction_window_active", staticmethod(lambda now=None: False))


def _seq():
    return iter(range(1, 10000)).__next__


def test_default_on(monkeypatch):
    # 2026-11-19 用户裁决：socket 无客户端频控，App 3s 即接受证据→默认 on
    s = K(Codec())
    assert s._pid8_refresh_status()["enabled"] is True


def test_explicit_off_zero_frames(monkeypatch, in_window):
    s = K(Codec(), pid8_refresh=False)   # env KPL_PID8_REFRESH=0 可关
    monkeypatch.setattr(s, "_human_pause", lambda *a, **k: None)
    sock = FakeSock()
    s._drain_pid8_refresh(sock, _seq(), now=1000.0)
    assert sock.frames == []
    assert s._pid8_refresh_status()["enabled"] is False


def test_window_gate(svc, out_window):
    sock = FakeSock()
    svc._drain_pid8_refresh(sock, _seq(), now=1000.0)
    assert sock.frames == [], "窗外零帧（App 页可见语义的无头等价）"
    assert svc._pid8_refresh_status()["window_active"] is False


def test_3s_cadence_and_frame_shape(svc, in_window):
    sock = FakeSock()
    svc._pid8_last_refresh = 1000.0
    svc._drain_pid8_refresh(sock, _seq(), now=1002.9)
    assert sock.frames == [], "<3s 不重发（App 3000ms 周期同款）"
    svc._drain_pid8_refresh(sock, _seq(), now=1003.0)
    assert len(sock.frames) == 7, "7 页×1 帧（App 3s 周期同款 ≈2.33 帧/s，帧数仅观测非门控）"
    for i, fr in enumerate(sock.frames):
        assert fr[0] == proto.PKG_ROUTE, "pkg=0x40 订阅通道（setup 6d 同款）"
        assert struct.unpack(">H", fr[7:9])[0] == daban.CMD_DABAN_STOCK_LIST
        assert fr[12:15] == bytes([0x02]) + struct.pack(">H", daban.CMD_DABAN_STOCK_LIST), \
            "ext 02 0837 路由头（setup 6d 同款）"
    st = svc._pid8_refresh_status()
    assert st["frames_sent"] == 7 and st["last_ts"] == 1003.0
    # req 体 pid=8 + index 偏移逐页（与 setup 6d 同 builder；假 codec enc 直通）
    for i, fr in enumerate(sock.frames):
        req_i = daban.build_daban_stock_list_req_pb(8, index=i * 30, count=30)
        assert fr[15:] == req_i, f"页#{i} 帧体=pid8 index 偏移请求（setup 6d 同款）"
    svc._drain_pid8_refresh(sock, _seq(), now=1005.0)
    assert len(sock.frames) == 7, "节拍内不重复发"
    svc._drain_pid8_refresh(sock, _seq(), now=1006.0)
    assert len(sock.frames) == 14


def test_session_reset_initial_burst(svc, in_window):
    """会话重建随 setup 初始 burst 重置：_pid8_last_refresh=会话起点，
    首次重请求 +3s（不与 setup burst 叠发）。"""
    sock = FakeSock()
    svc._pid8_last_refresh = 2000.0   # _session streaming 起点同款赋值
    svc._drain_pid8_refresh(sock, _seq(), now=2001.0)
    assert sock.frames == []
    svc._drain_pid8_refresh(sock, _seq(), now=2003.0)
    assert len(sock.frames) == 7


def test_send_fail_fail_visible_fail_fast(svc, in_window):
    sock = FakeSock(fail_at=3)
    svc._pid8_last_refresh = 1000.0
    with pytest.raises(OSError):
        svc._drain_pid8_refresh(sock, _seq(), now=1003.0)
    st = svc._pid8_refresh_status()
    assert st["send_drops"] == 4, "未发帧计数披露（fail-fast 重连，不新增重试循环）"
    assert st["frames_sent"] == 3, "部分发送成功帧计入（review L1 观测面不少计）"
    assert any(e.get("type") == "subscribe_send_dropped"
               and e.get("lane") == "pid8_refresh" for e in svc._history)


def test_pid8_not_in_pids_no_send(monkeypatch, in_window):
    s = K(Codec(), pid8_refresh=True, daban_list_pids=(1, 2, 3))
    monkeypatch.setattr(s, "_human_pause", lambda *a, **k: None)
    sock = FakeSock()
    s._drain_pid8_refresh(sock, _seq(), now=1000.0)
    assert sock.frames == []


def test_status_exposes_lane(svc):
    st = svc.status()["pid8_refresh"]
    assert set(st.keys()) == {"enabled", "frames_sent", "last_ts",
                              "send_drops", "window_active"}
    assert st["enabled"] is True
