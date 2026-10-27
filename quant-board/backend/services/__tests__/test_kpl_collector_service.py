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
        # 7 基础帧（610/602/2301/2303/2304/3001/3006）+ 6 打板/情绪帧（daban_subs 默认开）
        assert len(fake.sent) == 13
        assert fake.sent[0][7:9] == (610).to_bytes(2, "big")
        assert fake.sent[1][7:9] == (602).to_bytes(2, "big")
        assert fake.sent[2][7:9] == (2301).to_bytes(2, "big")
        assert fake.sent[3][7:9] == (2303).to_bytes(2, "big")
        assert fake.sent[4][7:9] == (2304).to_bytes(2, "big")
        assert fake.sent[5][7:9] == (3001).to_bytes(2, "big")
        assert fake.sent[6][7:9] == (3006).to_bytes(2, "big")  # 个股订阅
        # 6c) 打板/情绪订阅帧：2114/2115/2116/2119/2120/2126（ext 路由头 02 <cmdBE>）
        daban_cmds_sent = [int.from_bytes(f[7:9], "big") for f in fake.sent[7:]]
        assert daban_cmds_sent == [2114, 2115, 2116, 2119, 2120, 2126]
        for f, c in zip(fake.sent[7:], daban_cmds_sent):
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
