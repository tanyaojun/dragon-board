"""竞价订阅 lane（2026-11-19 用户裁决：live 归档脱离浏览器在线依赖）。

宇宙=pid=8 竞价池 2103 推送成员（服务端默认订阅面）；窗 [09:15,09:30) 内
中途增量补订 3006 + 并入 setup 面。源码锚：w30.java:230 /
StockInfoBottomSelectBar.java:175（App 会话中途 m(3006, e((byte)4)) 原行为）。
频控：零新增连接、≤200 id/帧、拟人停顿、窗外零帧；超帽只披露不静默。
"""
import struct

import pytest

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
    s = K(Codec())
    monkeypatch.setattr(s, "_human_pause", lambda *a, **k: None)
    return s


@pytest.fixture
def in_window(monkeypatch):
    monkeypatch.setattr(K, "_auction_window_active", staticmethod(lambda now=None: True))


@pytest.fixture
def out_window(monkeypatch):
    monkeypatch.setattr(K, "_auction_window_active", staticmethod(lambda now=None: False))


def _items(*codes):
    return [{"stock_id": c} for c in codes]


def test_feed_window_gate(svc, out_window):
    assert svc._feed_auction_lane(_items("600102")) == 0, "窗外不累积（面预算）"
    assert svc._auction_lane_status()["universe_n"] == 0


def test_feed_dedup_whitelist_pending(svc, in_window):
    n = svc._feed_auction_lane(_items("600102", "801044", "600102", "301391"))
    assert n == 2, "板块 id 不入 3006 面；跨页去重"
    st = svc._auction_lane_status()
    assert st["universe_n"] == 2 and st["pending_n"] == 2
    assert svc._feed_auction_lane(_items("600102")) == 0, "重复推送不重复入队"
    assert any(e.get("type") == "auction_lane_status" for e in svc._history)


def test_feed_cross_day_reset(svc, in_window):
    svc._feed_auction_lane(_items("600102"))
    svc._auction_lane_date = "2026-11-18"
    svc._feed_auction_lane(_items("301391"))
    assert svc._auction_lane_ids == ["301391"], "跨日重置不残留昨日面"


def test_feed_cap_disclosure(svc, in_window):
    svc._auction_lane_cap = 2
    svc._feed_auction_lane(_items("600102", "600100", "600101"))
    st = svc._auction_lane_status()
    assert st["universe_n"] == 2 and st["cap_dropped_n"] == 1, "超帽=面预算决策，披露不静默"


def test_effective_face_union_and_reset(svc, in_window):
    svc.set_subscriptions(["801044", "600000"])
    svc._feed_auction_lane(_items("600102"))
    assert svc._effective_stock_ids() == ["801044", "600000", "600102"]
    svc.reset_subscriptions_to_default()
    eff = svc._effective_stock_ids()
    assert "600102" in eff and "600000" not in eff, \
        "浏览器面回落默认不抹服务端 lane（单写者分离）"


def test_effective_face_out_window(svc, out_window):
    svc.set_subscriptions(["600000"])
    svc._auction_lane_ids = ["600102"]   # 昨日残留/窗内累积均不得入窗外 face
    assert svc._effective_stock_ids() == ["600000"]


def test_drain_mid_session_frames_chunked(svc, in_window):
    codes = [f"60{i:04d}" for i in range(250)]
    svc._feed_auction_lane(_items(*codes))
    sock = FakeSock()
    svc._drain_auction_subs(sock, iter(range(1, 100)).__next__)
    assert len(sock.frames) == 2, "250 id → 200+50 两帧（1106 护栏）"
    for fr in sock.frames:
        assert fr[0] == proto.PKG_ROUTE, "pkg=0x40 订阅路由通道（App e((byte)4)）"
        assert struct.unpack(">H", fr[7:9])[0] == proto.CMD_HQ_ID_LIST
        assert fr[12:15] == bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_ID_LIST)
    st = svc._auction_lane_status()
    assert st["pending_n"] == 0 and st["subscribed_n"] == 250
    assert st["sub_frames"] == 2
    svc._drain_auction_subs(sock, iter(range(100, 200)).__next__)
    assert len(sock.frames) == 2, "队空零帧"


def test_drain_send_fail_fail_visible_fail_fast(svc, in_window):
    codes = [f"60{i:04d}" for i in range(250)]
    svc._feed_auction_lane(_items(*codes))
    sock = FakeSock(fail_at=1)
    with pytest.raises(OSError):
        svc._drain_auction_subs(sock, iter(range(1, 100)).__next__)
    st = svc._auction_lane_status()
    assert st["send_drops"] == 50, "未发 id 计数披露（下一会话 setup 全面自愈）"
    assert any(e.get("type") == "subscribe_send_dropped" and e.get("lane") == "auction"
               for e in svc._history)


def test_drain_out_window_clears_no_send(svc, in_window, monkeypatch):
    svc._feed_auction_lane(_items("600102"))
    monkeypatch.setattr(K, "_auction_window_active", staticmethod(lambda now=None: False))
    sock = FakeSock()
    svc._drain_auction_subs(sock, iter(range(1, 10)).__next__)
    assert sock.frames == [] and svc._auction_lane_status()["pending_n"] == 0
