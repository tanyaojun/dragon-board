# -*- coding: utf-8 -*-
"""KplCollectorService 测试 —— 全 mock（红线：测试不得触发真实 KPL 连接/signsvc）。

用 FakeCodec 替代 signsvc，FakeSocket 替代 TLS socket；验证：
1. 260 → 610 → 602 → 订阅 → 收流的完整会话状态机
2. 服务器错误帧 fail-visible 上报（不静默）
3. 推送/应答帧解码失败 fail-visible 上报
"""
from __future__ import annotations

import queue
import io
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_socket_protocol as proto  # noqa: E402
from backend.services.kpl_collector_service import (  # noqa: E402
    KplCollectorService,
    SignSvcAdbCodec,
    SignSvcError,
)

NUL2 = b"\x00\x00"  # extlen=0 / status=0 占位


def _wrap(pkg: int, body: bytes) -> bytes:
    return bytes([pkg]) + len(body).to_bytes(4, "big") + body


def _srv(cmd: int, payload: bytes) -> bytes:
    """服务器主动帧: pkg 0x20 + [cmd][status][extlen][payload]"""
    return _wrap(proto.PKG_SERVER, cmd.to_bytes(2, "big") + b"\x00" + NUL2 + payload)


def _echo(seq: int, cmd: int, flags: int, payload: bytes) -> bytes:
    """服务器应答帧: pkg 0x30 + [seq][cmd][flags][extlen][payload]"""
    return _wrap(0x30, seq.to_bytes(2, "big") + cmd.to_bytes(2, "big") + bytes([flags]) + NUL2 + payload)


def _push(cmd: int, ext: bytes, payload: bytes) -> bytes:
    """服务器推送帧: pkg 0x60 + [extlen][ext][cmd][flags][inner_extlen][payload]"""
    body = len(ext).to_bytes(2, "big") + ext + cmd.to_bytes(2, "big") + b"\x01" + NUL2 + payload
    return _wrap(proto.PKG_PUSH, body)


def _make_260(server_time: int = 1793033481) -> bytes:
    body = (
        (260).to_bytes(2, "big") + b"\x00" + NUL2
        + proto.pb_varint_field(1, server_time)
        + proto.pb_bytes(2, b"2db64e49ca378ac2a21331deca1a7425")
        + proto.pb_varint_field(3, 1)
    )
    return _wrap(proto.PKG_SERVER, body)


class FakeCodec:
    """signsvc 替身：ENC 加 0xAA 前缀，DEC 去前缀；WBE 返回固定签名。"""

    def __init__(self, fail_dec: bool = False):
        self.fail_dec = fail_dec
        self.wbe_calls: list = []
        self.enc_calls: list = []

    def wbe(self, challenge, device_id, conn_type, cur_time):
        self.wbe_calls.append((challenge, device_id, conn_type, cur_time))
        return "ab" * 95

    def enc(self, plain: bytes):
        self.enc_calls.append(plain)
        return b"\xaa" + plain

    def dec(self, cipher_hex: str):
        if self.fail_dec:
            return None
        raw = bytes.fromhex(cipher_hex)
        if raw.startswith(b"\xaa"):
            return raw[1:]
        return raw


class FakeSocket:
    """预编排服务器响应的 socket 替身（流式语义：recv 按 TCP 字节流切片）。"""

    def __init__(self, responses: list):
        self._stream = bytearray(b"".join(responses))
        self.sent: list = []
        self.closed = False

    def settimeout(self, t):
        pass

    def recv(self, n):
        if not self._stream:
            return b""  # 服务器干净断开
        chunk = bytes(self._stream[:n])
        del self._stream[:n]
        return chunk

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


def _quotes_payload() -> bytes:
    item = (
        proto.pb_bytes(1, b"885423")
        + proto.pb_bytes(2, "测试板块".encode())
        + proto.pb_bytes(100, b"12.34")
        + proto.pb_bytes(100, b"-0.5")
    )
    return b"\xaa" + proto.pb_varint_field(4, 1793033481) + proto.pb_bytes(10, item)


@pytest.fixture
def svc() -> KplCollectorService:
    return KplCollectorService(
        FakeCodec(), device_id="test-dev", user_id="0", token="",
        stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
    )


class TestSessionStateMachine:
    def test_full_session_emits_auth_and_quotes(self, svc, monkeypatch):
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
            _echo(6, 3001, 0x01, _quotes_payload()),
            _push(3001, b"hqList|1:20030/3001-0/", _quotes_payload()),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()

        assert len(svc._codec.wbe_calls) == 1
        assert svc._codec.wbe_calls[0][0] == "2db64e49ca378ac2a21331deca1a7425"
        # 7 基础帧（610/602/2301/2303/2304/3001/3006）+ 7 打板/情绪帧（含 2100 打板头）+ 21 帧 2103（3 页签×7 页）
        assert len(fake.sent) == 35
        assert fake.sent[0][7:9] == (610).to_bytes(2, "big")
        assert fake.sent[1][7:9] == (602).to_bytes(2, "big")
        assert fake.sent[2][7:9] == (2301).to_bytes(2, "big")
        assert fake.sent[3][7:9] == (2303).to_bytes(2, "big")
        assert fake.sent[4][7:9] == (2304).to_bytes(2, "big")
        assert fake.sent[5][7:9] == (3001).to_bytes(2, "big")
        assert fake.sent[6][7:9] == (3006).to_bytes(2, "big")  # 个股订阅
        # 6c) 打板/情绪订阅帧：2114/2115/2116/2119/2120/2126（ext 路由头 02 <cmdBE>）
        daban_cmds_sent = [int.from_bytes(f[7:9], "big") for f in fake.sent[7:]]
        assert daban_cmds_sent == [2114, 2115, 2116, 2119, 2120, 2126, 2100] + [2103] * 21
        # 2103 分页订阅：3 页签×7 页，body=0xAA+req → pidType=f1、index=f4、count=f5=30
        from backend.services import kpl_daban_protocol as daban
        pages = []
        for f in fake.sent[14:]:
            req = daban.parse_pb_f32(f[16:])   # 去掉 0xAA 前缀
            pages.append((daban.pb_first(req, 1, -1), daban.pb_first(req, 4, -1),
                          daban.pb_first(req, 5, -1)))
        assert pages == ([(8, i * 30, 30) for i in range(7)]
                         + [(0, i * 30, 30) for i in range(7)]
                         + [(6, i * 30, 30) for i in range(7)])
        for f, c in zip(fake.sent[7:14], daban_cmds_sent[:7]):
            assert f[12] == 0x02 and f[13:15] == c.to_bytes(2, "big")  # ext=[02][cmd BE]

    def test_events_broadcast_to_subscribers(self, svc, monkeypatch):
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        q = svc.subscribe()
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
            _echo(6, 3001, 0x01, _quotes_payload()),
            _push(3001, b"hqList|1:20030/3001-0/", _quotes_payload()),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        events = []
        while True:
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break
        types = [e["type"] for e in events]
        assert "auth" in types and "quotes" in types
        quotes_ev = next(e for e in events if e["type"] == "quotes")
        assert quotes_ev["items"][0]["stock_id"] == "885423"
        assert "1201.486" in quotes_ev["items"][0]["quotas"] or "测试板块" == quotes_ev["items"][0]["name"]

    def test_server_error_fail_visible(self, svc, monkeypatch):
        # 服务器拒绝: 260 后直接 201 ErrResp(code=1002) —— 必须出现在事件流, 不静默
        err_payload = proto.pb_varint_field(1, 1002) + proto.pb_bytes(2, "错误：1002".encode())
        responses = [
            _make_260(),
            _srv(201, err_payload),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        q = svc.subscribe()
        events = []
        while True:
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break
        assert any(e["type"] == "error" for e in events), "错误必须广播（fail-visible）"
        assert svc.status()["last_error"] != ""

    def test_decode_failure_fail_visible(self, svc, monkeypatch):
        # 3001 推送到达但 DEC 失败 → 必须广播 error（不静默丢弃）
        svc._codec = FakeCodec(fail_dec=True)
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, b"\xaa" + proto.pb_varint_field(1, 1793033481)),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
            _echo(6, 3001, 0x01, b"\xde\xad"),
            _push(3001, b"hqList|1:20030/3001-0/", b"\xde\xad"),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        q = svc.subscribe()
        events = []
        while True:
            try:
                events.append(q.get_nowait())
            except queue.Empty:
                break
        assert any(e["type"] == "error" and "decode" in e.get("msg", "") for e in events)


class TestSubscriberSemantics:
    def test_3006_hq_subscription_chunked(self, monkeypatch):
        # 3006 单帧 id 超 ~241 被服务器 1106 拒绝（2026-10-27 精选板块引导实测）→ 必须分块
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        svc = KplCollectorService(
            FakeCodec(), device_id="test-dev", user_id="0", token="",
            stock_ids=[f"{i:06d}" for i in range(450)], host="127.0.0.1", port=1, human_delay=False,
        )
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
            _echo(6, 3001, 0x01, _quotes_payload()),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        hq_cmds = [f for f in fake.sent if int.from_bytes(f[7:9], "big") == 3006]
        assert len(hq_cmds) == 3   # ceil(450/200)
        covered = []
        from backend.services import kpl_daban_protocol as daban
        for f in hq_cmds:
            req = daban.parse_pb_f32(f[16:])   # 去 0xAA 前缀
            covered += [s.decode() for s in req.get(1, [])]
        assert covered == [f"{i:06d}" for i in range(450)]   # 无丢失无重复

    def test_late_subscriber_gets_history(self, svc):
        svc._emit({"type": "quotes", "items": []})
        svc._emit({"type": "status", "status": "streaming"})
        q = svc.subscribe()
        got = []
        while True:
            try:
                got.append(q.get_nowait())
            except queue.Empty:
                break
        assert len(got) == 2  # 历史回放，新订阅者不丢已发生事件

    def test_unsubscribe_stops_delivery(self, svc):
        q = svc.subscribe()
        svc.unsubscribe(q)
        svc._emit({"type": "status", "status": "x"})
        with pytest.raises(queue.Empty):
            q.get_nowait()


class TestSetSubscriptions:
    """动态订阅清单（2026-10-27 精选板块页需求）：下一 3001 构造即生效。"""

    def test_valid_update_replaces_ids(self, svc):
        r = svc.set_subscriptions(["801159", "803029", " 801044 "])
        assert r["ok"] is True
        assert r["count"] == 3
        assert svc._stock_ids == ["801159", "803029", "801044"]  # 修剪空白

    def test_empty_list_rejected_keeps_current(self, svc):
        before = list(svc._stock_ids)
        r = svc.set_subscriptions([])
        assert r["ok"] is False
        assert "reason" in r
        assert svc._stock_ids == before  # fail-visible：空清单不得清空现有订阅

    def test_none_like_entries_filtered(self, svc):
        r = svc.set_subscriptions(["", "  ", "801001"])
        assert r["ok"] is True
        assert svc._stock_ids == ["801001"]


class TestSignSvcCodecErrors:
    def test_signsvc_error_is_typed(self, monkeypatch):
        # 红线：测试零真实 adb/子进程调用——_ensure_ready 直接 mock 为抛错
        monkeypatch.setattr(SignSvcAdbCodec, "_ensure_ready",
                            lambda self: (_ for _ in ()).throw(SignSvcError("mock")))
        codec = SignSvcAdbCodec.__new__(SignSvcAdbCodec)  # 跳过 __init__（不触发构造副作用）
        codec._lock = threading.Lock()
        codec._proc = None
        # _cmd 在 ensure_ready 失败时应抛 SignSvcError（不吞异常）
        with pytest.raises(SignSvcError):
            codec._cmd("PING")

    def test_cmd_eof_sentinel_is_fail_visible(self, monkeypatch):
        # 读线程 EOF 哨兵 → _cmd 必须 fail-visible 抛错（不再靠 50 次空转计数）
        codec = SignSvcAdbCodec.__new__(SignSvcAdbCodec)
        codec._lock = threading.Lock()
        codec._lines = queue.Queue()
        killed = []

        class _FakeProc:
            stdin = io.BytesIO()

            def poll(self):
                return 1

            def kill(self):
                killed.append(1)

        codec._proc = _FakeProc()
        monkeypatch.setattr(SignSvcAdbCodec, "_ensure_ready", lambda self: codec._proc)
        codec._lines.put("__EOF__")  # 第一次尝试：EOF
        codec._lines.put("__EOF__")  # 重建重试：仍 EOF → 放弃
        with pytest.raises(SignSvcError):
            codec._cmd("ENC aa")
        assert killed, "EOF 后必须触发 kill 重建路径"


class TestDabanDispatch:
    def _drain(self, q):
        evs = []
        while True:
            try:
                evs.append(q.get_nowait())
            except queue.Empty:
                return evs
    def test_daban_push_emits_structured_event(self, svc, monkeypatch):
        # 2119 推送帧 → zt_situation 事件（天梯字段解析进广播流）
        from backend.services import kpl_daban_protocol as daban
        body = (
            proto.pb_varint_field(1, 40) + proto.pb_varint_field(2, 8)
            + proto.pb_varint_field(3, 6) + proto.pb_varint_field(13, 1)
        )
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_ZT_SITUATION_V2, b"daban/", body)))
        evs = self._drain(q)
        assert any(e["type"] == "zt_situation" and e["first_plate"] == 40 for e in evs)

    def test_daban_push_decode_fail_visible(self, svc, monkeypatch):
        # 解密失败（fail_dec=True 模拟 signsvc DEC 失败）→ daban_error + error 事件，不静默丢弃
        from backend.services import kpl_daban_protocol as daban
        from backend.services import kpl_collector_service as _svc_mod
        q = svc.subscribe()
        svc._codec.fail_dec = True
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_ZT_SITUATION_V2, b"daban/", b"\xff\xff")))
        evs = self._drain(q)
        types = [e["type"] for e in evs]
        assert "daban_error" in types and "error" in types

    def test_daban_push_garbage_parse_fail_visible(self, svc, monkeypatch):
        # dec 成功但内容乱码 → 解析器宽容返回结构化空值（不抛不丢）
        from backend.services import kpl_daban_protocol as daban
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_WIND_VANE, b"daban/", b"\xff\xff\xff\xff")))
        evs = self._drain(q)
        assert any(e["type"] == "wind_vane" for e in evs)

    def test_daban_stock_list_push_caches_snapshot(self, svc, monkeypatch):
        # 2103 推送 → daban_stocks 事件 + 按 (pidType, index) 页缓存（读口跨页合并全量）
        from backend.services import kpl_daban_protocol as daban
        def _page(idx: int, rows: list) -> bytes:
            body = proto.pb_varint_field(1, 8) + proto.pb_varint_field(4, idx)
            for sid, name, q0 in rows:
                body += proto.pb_bytes(20, proto.pb_bytes(1, sid.encode())
                                       + proto.pb_bytes(2, name.encode())
                                       + proto.pb_bytes(100, q0.encode()))
            return body + proto.pb_varint_field(22, 183)
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(0, [("603028", "赛福天", "13.02亿")]))))
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(30, [("300604", "长川科技", "2.1亿")]))))
        evs = self._drain(q)
        ev = next(e for e in evs if e["type"] == "daban_stocks" and e["pid_type"] == 8 and e["index"] == 30)
        assert ev["items"][0]["zt_buy_amount"] == "2.1亿"
        snap = svc.get_daban_list(8)
        assert snap["ok"] is True and snap["max_size"] == 183
        assert [it["stock_id"] for it in snap["items"]] == ["603028", "300604"]   # 按 index 拼接
        assert snap["pages"] == 2 and snap["pages_expected"] == 7 and snap["pages_missing"] == [2, 3, 4, 5, 6]
        assert "ts" in snap
        # 另一页签无快照 → fail-visible 结构化降级，不伪装空列表
        miss = svc.get_daban_list(0)
        assert miss["ok"] is False and miss["degraded"] is True and miss["reason"] == "no_daban_list_snapshot"

    def test_daban_empty_frame_suppressed_over_nonempty(self, svc):
        # 空帧抑制（2026-10-28 盘中实测）：风向标页上游列表重建窗口高频回空 Resp 帧
        # （35s 内 14 帧 12 空/2 满），空帧不得覆盖非空页缓存，否则读口绝大多数时间为空
        from backend.services import kpl_daban_protocol as daban
        def _page(idx: int, rows: list) -> bytes:
            body = proto.pb_varint_field(1, 6) + proto.pb_varint_field(4, idx)
            for sid, name, q0 in rows:
                body += proto.pb_bytes(20, proto.pb_bytes(1, sid.encode())
                                       + proto.pb_bytes(2, name.encode())
                                       + proto.pb_bytes(100, q0.encode()))
            return body + proto.pb_varint_field(22, 25)
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(0, [("000559", "msmk", "1亿")]))))
        snap1 = svc.get_daban_list(6)
        assert [it["stock_id"] for it in snap1["items"]] == ["000559"]
        # 空帧到达：不覆盖非空缓存，仅刷 ts + 记 last_empty_seen；空帧本身仍 fail-visible 广播
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/", _page(0, []))))
        evs = self._drain(q)
        assert any(e["type"] == "daban_stocks" and e["pid_type"] == 6 and not e["items"] for e in evs)
        snap2 = svc.get_daban_list(6)
        assert [it["stock_id"] for it in snap2["items"]] == ["000559"]
        page = svc._daban_lists[6][0]
        assert page.get("last_empty_seen") is not None and page["ts"] >= snap1["ts"]
        # 随后的满帧正常覆盖（last_empty_seen 清除）
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(0, [("002708", "bb", "2亿")]))))
        snap3 = svc.get_daban_list(6)
        assert [it["stock_id"] for it in snap3["items"]] == ["002708"]
        assert "last_empty_seen" not in svc._daban_lists[6][0]


class TestForecastLHB2112:
    """2112 会不会上龙虎榜：订阅帧开关（默认关）+ 推送事件 lhb_forecast。"""

    def test_session_sends_2112_only_when_enabled(self, monkeypatch):
        from backend.services import kpl_daban_protocol as daban
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
        ]
        svc = KplCollectorService(
            FakeCodec(), device_id="test-dev", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
            daban_subs=False, daban_lhb=True,
        )
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        cmds = [int.from_bytes(f[7:9], "big") for f in fake.sent]
        # daban_subs=False 时其余 21xx 不发，仅 2112 一帧
        assert 2112 in cmds and not any(c in (2114, 2115, 2103) for c in cmds)
        # body = 0xAA + ForecastLHBReq 基线（sortType=1/count=30）
        f2112 = next(f for f in fake.sent if int.from_bytes(f[7:9], "big") == 2112)
        assert f2112[16:] == daban.build_forecast_lhb_req_pb()  # FakeCodec.enc 的 0xAA 前缀在 [15]

    def test_2112_push_emits_lhb_forecast(self, svc):
        from backend.services import kpl_daban_protocol as daban
        item = (proto.pb_bytes(1, b"000001") + proto.pb_bytes(2, "平安银行".encode())
                + proto.pb_bytes(20, "龙虎榜".encode()))
        payload = proto.pb_varint_field(10, 1) + proto.pb_bytes(21, item)
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_FORECAST_LHB, b"daban/", payload)))
        evs = [dict(e) for e in list(q.queue)]
        ev = next(e for e in evs if e["type"] == "lhb_forecast")
        assert ev["items"][0]["stock_id"] == "000001"
        assert ev["items"][0]["reason"] == "龙虎榜"
        assert ev["total"] == 1


class TestRealtimeLHB3004:
    """3004/3101 RealtimeLHB（ServiceHqList 族）：订阅/单发开关 + 推送事件 realtime_lhb。"""

    def test_session_sends_3004_3101_when_enabled(self, monkeypatch):
        from backend.services import kpl_lhb_protocol as lhb
        from backend.services import kpl_collector_service as cc
        # 固定 3101 的动态 end_time（HHMM），锁完整请求体
        monkeypatch.setattr(cc.time, "strftime", lambda fmt: "1035")
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
        ]
        svc = KplCollectorService(
            FakeCodec(), device_id="test-dev", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
            daban_subs=False, lhb_realtime=True,
        )
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        cmds = [int.from_bytes(f[7:9], "big") for f in fake.sent]
        # daban_subs=False 时 21xx 不发，仅 3004 订阅 + 3101 单发两帧
        assert 3004 in cmds and 3101 in cmds
        assert not any(c in (2114, 2115, 2103, 2112) for c in cmds)
        # body = FakeCodec.enc 前缀 0xAA + App 基线 Req（f2 sortType=1, f4 limitType=4,
        # f9 bjsType=1, f21 count=30；零值省略）
        f3004 = next(f for f in fake.sent if int.from_bytes(f[7:9], "big") == 3004)
        assert f3004[16:] == lhb.build_realtime_lhb_req_pb()
        # 3101 带当日区间 0925→1035（end_time 由 strftime 决定，已固定）
        f3101 = next(f for f in fake.sent if int.from_bytes(f[7:9], "big") == 3101)
        assert f3101[16:] == lhb.build_realtime_lhb_req_pb(start_time=925, end_time=1035)

    def test_3004_push_emits_realtime_lhb(self, svc):
        from backend.services import kpl_lhb_protocol as lhb
        # Item 复用 GroupStockQuotasResp.Item 口径：f1 stockId, f2 name, f100 quotas[]
        item = (proto.pb_bytes(1, b"600229") + proto.pb_bytes(2, "天津普林".encode())
                + proto.pb_bytes(100, b"12.34") + proto.pb_bytes(100, "3.5亿".encode()))
        payload = (proto.pb_varint_field(30, 5)          # total
                   + proto.pb_bytes(33, b"2026-10-29")   # days
                   + proto.pb_bytes(41, item))
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(lhb.CMD_REALTIME_LHB_SUB, b"lhb/", payload)))
        evs = [dict(e) for e in list(q.queue)]
        ev = next(e for e in evs if e["type"] == "realtime_lhb")
        assert ev["total"] == 5
        assert ev["days"] == ["2026-10-29"]
        assert ev["items"][0]["stock_id"] == "600229"
        assert ev["items"][0]["quotas"] == ["12.34", "3.5亿"]

    def test_3101_same_parser_registered(self):
        from backend.services import kpl_lhb_protocol as lhb
        assert lhb.LHB_RESP_PARSERS[lhb.CMD_REALTIME_LHB_RANGE] is lhb.parse_realtime_lhb
        assert lhb.LHB_RESP_PARSERS[lhb.CMD_REALTIME_LHB_SUB] is lhb.parse_realtime_lhb


class TestLhbSnapshots:
    """task-4：2112/3004 快照缓存 + 读口降级（fail-visible）。"""

    def test_no_snapshot_degraded(self):
        svc = KplCollectorService(
            FakeCodec(), device_id="d", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
            daban_subs=False, daban_lhb=True, lhb_realtime=True,
        )
        fc = svc.get_lhb_forecast()
        rl = svc.get_lhb_realtime()
        assert fc["ok"] is False and fc["degraded"] is True and fc["reason"] == "no_lhb_forecast_snapshot"
        assert rl["ok"] is False and rl["degraded"] is True and rl["reason"] == "no_lhb_realtime_snapshot"
        assert "running" in fc and "running" in rl

    def test_2112_push_populates_forecast_snapshot(self, svc):
        from backend.services import kpl_daban_protocol as daban
        payload = proto.pb_varint_field(10, 2) + proto.pb_bytes(
            21, proto.pb_bytes(1, b"600715") + proto.pb_bytes(20, "偏离-7%".encode()))
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_FORECAST_LHB, b"daban/", payload)))
        snap = svc.get_lhb_forecast()
        assert snap["ok"] is True
        assert snap["total"] == 2 and snap["items"][0]["stock_id"] == "600715"
        assert snap["items"][0]["reason"] == "偏离-7%"
        assert "ts" in snap
        # 空帧抑制（同 2103/3004 规；2026-10-29 午间实测：休市推流 total=96/items=[]）
        payload_empty = proto.pb_varint_field(10, 1)   # total=1 但无 items
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_FORECAST_LHB, b"daban/", payload_empty)))
        kept = svc.get_lhb_forecast()
        assert kept["total"] == 2 and kept["items"][0]["stock_id"] == "600715"
        assert "last_empty_seen" in kept
        # total=0 才是服务端语义清空，正常覆盖（payload 需非空，纯空帧走 decode-fail 降级）
        svc._dispatch(proto.parse_incoming(_push(
            daban.CMD_FORECAST_LHB, b"daban/", proto.pb_bytes(12, b"2026-10-29"))))
        cleared = svc.get_lhb_forecast()
        assert cleared["total"] == 0 and cleared["items"] == []

    def test_3004_push_populates_snapshot_with_empty_frame_suppression(self, svc):
        from backend.services import kpl_lhb_protocol as lhb
        item = proto.pb_bytes(1, b"600229") + proto.pb_bytes(2, "天津普林".encode())
        full = proto.pb_varint_field(30, 5) + proto.pb_bytes(41, item)
        svc._dispatch(proto.parse_incoming(_push(lhb.CMD_REALTIME_LHB_SUB, b"lhb/", full)))
        snap = svc.get_lhb_realtime()
        assert snap["ok"] is True and snap["total"] == 5
        assert snap["items"][0]["stock_id"] == "600229"
        # 空帧抑制：空 items 不覆盖非空快照（仅刷 ts + last_empty_seen）
        empty = proto.pb_varint_field(30, 0)
        svc._dispatch(proto.parse_incoming(_push(lhb.CMD_REALTIME_LHB_SUB, b"lhb/", empty)))
        snap2 = svc.get_lhb_realtime()
        assert snap2["total"] == 5 and snap2["items"][0]["stock_id"] == "600229"
        assert "last_empty_seen" in snap2

    def test_3004_snapshot_json_serializable(self, svc):
        # 读口合同：快照必须可 JSON 序列化（packed varint indexes 修复回归）
        import json as _json
        from backend.services import kpl_lhb_protocol as lhb
        item = proto.pb_bytes(1, b"600229") + proto.pb_bytes(2, "天津普林".encode())
        payload = (proto.pb_varint_field(30, 1) + proto.pb_bytes(40, b"\x00\x01\x02")
                   + proto.pb_bytes(41, item))
        svc._dispatch(proto.parse_incoming(_push(lhb.CMD_REALTIME_LHB_SUB, b"lhb/", payload)))
        snap = svc.get_lhb_realtime()
        assert snap["indexes"] == [0, 1, 2]
        _json.dumps(snap, ensure_ascii=False)  # 不抛即合格
