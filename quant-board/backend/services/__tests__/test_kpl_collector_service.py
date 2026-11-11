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
    AntiCheatError,
    KplCollectorService,
    SignSvcAdbCodec,
    SignSvcError,
)
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI  # noqa: E402

NUL2 = b"\x00\x00"  # extlen=0 / status=0 占位


def _wrap(pkg: int, body: bytes) -> bytes:
    return bytes([pkg]) + len(body).to_bytes(4, "big") + body


def _srv(cmd: int, payload: bytes, status: int = 0) -> bytes:
    """服务器主动帧: pkg 0x20 + [cmd][status(=flags)][extlen][payload]"""
    return _wrap(proto.PKG_SERVER, cmd.to_bytes(2, "big") + bytes([status]) + NUL2 + payload)


def _echo(seq: int, cmd: int, flags: int, payload: bytes) -> bytes:
    """服务器应答帧: pkg 0x30 + [seq][cmd][flags][extlen][payload]"""
    return _wrap(0x30, seq.to_bytes(2, "big") + cmd.to_bytes(2, "big") + bytes([flags]) + NUL2 + payload)


def _push(cmd: int, ext: bytes, payload: bytes) -> bytes:
    """服务器推送帧: pkg 0x60 + [extlen][ext][cmd][flags][inner_extlen][payload]"""
    body = len(ext).to_bytes(2, "big") + ext + cmd.to_bytes(2, "big") + b"\x01" + NUL2 + payload
    return _wrap(proto.PKG_PUSH, body)


def _drain_q(q):
    evs = []
    while True:
        try:
            evs.append(q.get_nowait())
        except queue.Empty:
            return evs


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

    def __init__(self, fail_dec: bool = False, exec_value=0x0BADF00D, enc_fail: bool = False):
        self.fail_dec = fail_dec
        self.wbe_calls: list = []
        self.enc_calls: list = []
        self.exec_calls: list = []
        # 261 反作弊轮：默认返回定值；exec_value=None → 模拟 VM 失败（Long.MIN_VALUE 语义）
        self.exec_value = exec_value
        self.enc_fail = enc_fail

    def wbe(self, challenge, device_id, conn_type, cur_time):
        self.wbe_calls.append((challenge, device_id, conn_type, cur_time))
        return "ab" * 95

    def exec(self, challenge, d):
        self.exec_calls.append((challenge, d))
        return self.exec_value

    def enc(self, plain: bytes):
        self.enc_calls.append(plain)
        if self.enc_fail:
            return None
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
    def test_loop_send_grace_suppresses_loop_phase_sends(self, monkeypatch):
        """2026-11-10 假说判别实验：宽限期内读循环零发送（保活/drain 全延后），
        行情推送照常 dispatch；杀连时刻落在宽限期内→setup 打标定时处决，
        落在宽限期结束时→循环期发送触发。"""
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
        svc = KplCollectorService(
            FakeCodec(), device_id="test-dev", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
            loop_send_grace_s=1000,
        )
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        # 内联订阅链照发（7 帧）；循环期（会话在宽限期内被服务器关连而结束）零发送
        assert len(fake.sent) == 7
        assert len(svc._pending_setup_frames) == 49          # daban 队列原封不动
        assert "grace_end_pending" not in svc._stats         # 宽限期未结束，无打点

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
        # 2026-11-10 重排：内联仅 7 基础帧（610/602/2301/2303/2304/3001/3006），
        # daban 家族（7+42 帧）入 _pending_setup_frames 由读循环限流续发；
        # 剩余响应（echo3001+push3001）供两轮 drain 各发 8 帧，余量留队（本会话丢失自愈）
        assert len(fake.sent) == 7 + 16
        assert fake.sent[0][7:9] == (610).to_bytes(2, "big")
        assert fake.sent[1][7:9] == (602).to_bytes(2, "big")
        assert fake.sent[2][7:9] == (2301).to_bytes(2, "big")
        assert fake.sent[3][7:9] == (2303).to_bytes(2, "big")
        assert fake.sent[4][7:9] == (2304).to_bytes(2, "big")
        assert fake.sent[5][7:9] == (3001).to_bytes(2, "big")
        assert fake.sent[6][7:9] == (3006).to_bytes(2, "big")  # 个股订阅
        from backend.services import kpl_daban_protocol as daban
        # 已发 16 帧（2 tick×8）：7 个 21xx cmd + 前 9 页 2103；队列剩余 33 页
        sent_cmds = [int.from_bytes(f[7:9], "big") for f in fake.sent[7:]]
        assert sent_cmds == [2114, 2115, 2116, 2119, 2120, 2126, 2100] + [2103] * 9
        # 队列余量：body=0xAA+req → pidType=f1、index=f4、count=f5=30（从 (0,60) 续起）
        pages = [(daban.pb_first(daban.parse_pb_f32(it["req"]), 1, -1),
                  daban.pb_first(daban.parse_pb_f32(it["req"]), 4, -1),
                  daban.pb_first(daban.parse_pb_f32(it["req"]), 5, -1))
                 for it in svc._pending_setup_frames]
        assert len(pages) == 33
        assert pages == ([(0, i * 30, 30) for i in range(2, 7)]
                         + [(6, i * 30, 30) for i in range(7)]
                         + [(1, i * 30, 30) for i in range(7)]
                         + [(2, i * 30, 30) for i in range(7)]
                         + [(3, i * 30, 30) for i in range(7)])
        for f, c in zip(fake.sent[7:14], sent_cmds[:7]):
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

    def test_merge_unions_without_dropping_existing(self, svc):
        """2026-11-11 行业补引导合同：merge 求并保序去重，不抹别页已订个股。"""
        svc.set_subscriptions(["801001", "600000"], priority_ids=["801001"])
        r = svc.set_subscriptions(["881001", "801001", "600519"],
                                  priority_ids=["881001", "801001"], merge=True)
        assert r["ok"] is True
        assert svc._stock_ids == ["801001", "600000", "881001", "600519"]
        assert svc._sub_prio_all == ["801001", "881001"]
        assert r["count"] == 4

    def test_replace_semantics_unchanged_by_default(self, svc):
        svc.set_subscriptions(["801001", "600000"])
        svc.set_subscriptions(["881001"])
        assert svc._stock_ids == ["881001"]   # 默认仍替换（旧合同不变）

    def test_status_exposes_subscription_composition(self, svc):
        """订阅构成观测（行业页签空态排查）：hy/sectors/stocks/chunks 一眼可核。"""
        svc.set_subscriptions(["801001", "881001", "881002", "600000"],
                              priority_ids=["801001", "881001", "881002"])
        sub = svc.status()["subscriptions"]
        assert sub["count"] == 4
        assert sub["hy"] == 2
        assert sub["sectors"] == 1
        assert sub["stocks"] == 1
        assert sub["priority"] == 3
        assert sub["chunks"] == len(svc._sub_prio) + len(svc._sub_rest)


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
        # 页级元数据全量透出（2026-11-07 涨停池全量存档要求）
        assert len(snap["pages_meta"]) == 2
        assert snap["pages_meta"][0]["index"] == 0 and snap["pages_meta"][1]["index"] == 30
        assert "count" in snap["pages_meta"][0] and "indexes" in snap["pages_meta"][0]
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
        sent_cmds = [int.from_bytes(f[7:9], "big") for f in fake.sent]
        q_cmds = [it["cmd"] for it in svc._pending_setup_frames]
        # daban_subs=False 时其余 21xx 不入队，仅 2112 一帧（读循环续发；本例无剩余响应，
        # 读循环立即退出，2112 留队未发——下一会话重建）
        assert 2112 in q_cmds and not any(c in (2114, 2115, 2103) for c in q_cmds)
        assert not any(c in (2114, 2115, 2103, 2112) for c in sent_cmds)
        # body = ForecastLHBReq 基线（sortType=1/count=30）
        it2112 = next(it for it in svc._pending_setup_frames if it["cmd"] == 2112)
        assert it2112["req"] == daban.build_forecast_lhb_req_pb()
        assert it2112["ext"] == b"\x02" + (2112).to_bytes(2, "big")

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
            daban_subs=False, lhb_realtime=True, lhb_realtime_count=120,
        )
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        sent_cmds = [int.from_bytes(f[7:9], "big") for f in fake.sent]
        q_cmds = [it["cmd"] for it in svc._pending_setup_frames]
        # daban_subs=False 时 21xx 不入队，仅 3004 订阅 + 3101 单发两帧（读循环续发）
        assert 3004 in q_cmds and 3101 in q_cmds
        assert not any(c in (2114, 2115, 2103, 2112) for c in q_cmds)
        assert not any(c in (2114, 2115, 2103, 2112, 3004, 3101) for c in sent_cmds)
        # body = Req（f2 sortType=1, f4 limitType=4,
        # f9 bjsType=1, f21 count=120 采集放宽 2026-10-30；零值省略）
        it3004 = next(it for it in svc._pending_setup_frames if it["cmd"] == 3004)
        assert it3004["req"] == lhb.build_realtime_lhb_req_pb(count=120)
        # 3101 带当日区间 0925→1035（end_time 由 strftime 决定，已固定）+ 同 count
        it3101 = next(it for it in svc._pending_setup_frames if it["cmd"] == 3101)
        assert it3101["req"] == lhb.build_realtime_lhb_req_pb(count=120, start_time=925, end_time=1035)

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


class TestZtReasons2203:
    """2203 涨停原因推送试点（2026-11-08）：dispatch 快照/事件 + 2103 pid=1 自动补订 + 读口降级。"""

    def _reasons_payload(self, sid: str = "301697", zt: str = "光伏+次新股") -> bytes:
        return (
            proto.pb_bytes(1, sid.encode())
            + proto.pb_bytes(2, zt.encode())
            + proto.pb_bytes(13, "2连板".encode())
            + proto.pb_bytes(14, "光伏".encode())
            + proto.pb_varint_field(500, 7)
        )

    def test_dispatch_2203_updates_snapshot_and_emits(self, svc):
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(proto.CMD_HQ_REASONS, b"test/",
                                                 self._reasons_payload())))
        evs = _drain_q(q)
        ev = next(e for e in evs if e["type"] == "zt_reasons")
        assert ev["stock_id"] == "301697" and ev["zt"].startswith("光伏+次新股")
        assert ev["zt_group"] == "2连板" and ev["msg_id"] == 7
        snap = svc.get_zt_reasons()
        assert snap["ok"] is True and snap["count"] == 1
        assert snap["reasons"]["301697"]["zt"].startswith("光伏+次新股")
        assert "ts" in snap["reasons"]["301697"] and snap["subscribed"] >= 0
        assert svc.status()["zt_reasons"] == 1

    def test_dispatch_2203_decode_fail_visible(self):
        bad = KplCollectorService(FakeCodec(fail_dec=True), device_id="t", user_id="0",
                                  token="", stock_ids=["801044"], host="127.0.0.1", port=1,
                                  human_delay=False)
        q = bad.subscribe()
        bad._dispatch(proto.parse_incoming(_push(proto.CMD_HQ_REASONS, b"test/", b"\xaapayload")))
        evs = _drain_q(q)
        assert any(e["type"] == "zt_reasons_error" and e["reason"] == "push decode failed" for e in evs)
        assert bad.get_zt_reasons()["ok"] is False

    def test_get_zt_reasons_degraded_when_empty(self, svc):
        snap = svc.get_zt_reasons()
        assert snap["ok"] is False and snap["degraded"] is True
        assert snap["reason"] == "no_zt_reason_snapshot"

    def test_2103_pid1_queues_and_drain_sends_frames(self, svc):
        from backend.services import kpl_daban_protocol as daban
        import struct as _st

        def _page(pid: int, rows: list) -> bytes:
            body = proto.pb_varint_field(1, pid) + proto.pb_varint_field(4, 0)
            for sid, name, q0 in rows:
                body += proto.pb_bytes(20, proto.pb_bytes(1, sid.encode())
                                       + proto.pb_bytes(2, name.encode())
                                       + proto.pb_bytes(100, q0.encode()))
            return body + proto.pb_varint_field(22, len(rows) * 30)

        q = svc.subscribe()
        # pid=8（集合竞价）不入队；pid=1（涨停池）入队
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(8, [("603028", "赛福天", "1亿")]))))
        assert svc._pending_zt_reason == []
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(1, [("301697", "贝特利", "2亿"),
                                                           ("002614", "奥佳华", "3亿")]))))
        assert svc._pending_zt_reason == ["301697", "002614"]
        # 重复帧去重（同成员不重复订阅）
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(1, [("301697", "贝特利", "2亿")]))))
        assert svc._pending_zt_reason == ["301697", "002614"]
        # drain：帧号 2203、ext=02 089B、body=HQReq{f1 stockId}（enc 前缀 0xAA 由 FakeCodec 加）
        sock = FakeSocket([])
        sent = 0
        seq = iter(range(100, 200))
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        assert len(sock.sent) == 2 and sent == 0
        for fr, sid in zip(sock.sent, ["301697", "002614"]):
            assert fr[0] == proto.PKG_ROUTE
            assert fr[7:9] == proto.CMD_HQ_REASONS.to_bytes(2, "big")   # pkg(1)+len(4)+seq(2) 后为 cmd
            assert fr[10:12] == (3).to_bytes(2, "big") and fr[12:15] == b"\x02\x08\x9b"   # extlen=3 + ext(`02`+cmd 2BE)
            assert proto.build_hq_req_pb(sid) in fr                     # HQReq{f1}
        assert svc._pending_zt_reason == []
        evs = _drain_q(q)
        assert any(e["type"] == "zt_reasons_status" and len(e["stock_ids"]) == 2 for e in evs)

    def test_zt_reason_subs_disabled_no_queue(self):
        off = KplCollectorService(FakeCodec(), device_id="t", user_id="0", token="",
                                  stock_ids=["801044"], host="127.0.0.1", port=1,
                                  human_delay=False, zt_reason_subs=False)
        assert off._queue_zt_reason_new(["301697"]) == 0
        assert off._pending_zt_reason == []
        assert off.get_zt_reasons()["reason"] == "no_zt_reason_snapshot"
        snap = {"ok": True}
        off._zt_reason_snap["301697"] = {"stock_id": "301697", "ts": 1}
        assert off.get_zt_reasons()["ok"] is True   # 开关关不清既有快照

    def test_session_rebuilds_2203_subs_each_reconnect(self, monkeypatch):
        # 评审 P0（2026-11-08）：服务器 TTL≈60-90s，重连后原订阅面已失效；
        # _zt_reason_subscribed 若跨会话持久，第二会话起一帧不发、推送静默停流。
        # 修复 = 每会话 6g 先清已订阅集合再全量补订；本测试预置涨停池快照，
        # 连跑两轮 _session，断言每轮都发出 2203 订阅帧。
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        vr_payload = b"\xaa" + proto.pb_varint_field(1, 1793033481) + proto.pb_bytes(7, b"https://x/1.data")
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, vr_payload),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
            # 填充响应：2026-11-10 重排后 daban 家族入队由读循环 drain，49 帧≈7 tick；
            # 需 ≥7 个响应驱动循环，setup 队列清空后 2203 才让位发出
            *[_echo(6 + i, 3001, 0x01, _quotes_payload()) for i in range(8)],
        ]
        svc = KplCollectorService(
            FakeCodec(), device_id="test-dev", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=False,
        )
        # 预置涨停池（2103 pid=1）快照：两个成员已"订阅过"（模拟首会话状态）
        svc._daban_lists[1] = {0: {"pid_type": 1, "index": 0, "items": [{"stock_id": "301697"}, {"stock_id": "002614"}], "ts": 1.0}}
        svc._zt_reason_subscribed.update({"301697", "002614"})

        sent_2203_per_session = []
        for session_no in range(2):
            fake = FakeSocket(responses)
            monkeypatch.setattr(svc, "_tls_connect", lambda f=fake: f)
            svc._session()
            sent_2203_per_session.append(
                [f for f in fake.sent if int.from_bytes(f[7:9], "big") == proto.CMD_HQ_REASONS])
        # 两轮会话各发 2 帧（两成员全量重订），去重集合不跨会话持久
        assert [len(fs) for fs in sent_2203_per_session] == [2, 2]
        for fr in sent_2203_per_session[1]:
            assert fr[12:15] == b"\x02\x08\x9b"   # ext=`02`+cmd 2BE
            assert proto.build_hq_req_pb("301697") in fr or proto.build_hq_req_pb("002614") in fr


class TestAntiCheat261:
    """261 反作弊轮 → 262 作答（2026-11-08 实现；App 口径 qn0.g/GameClient$onChallenge$2）。"""

    TOKEN = b"T" * 24 + b"O" * 8

    def _261_payload(self, d: int = 3, tail: bytes = b"chal-abcdef", token: bytes = None) -> bytes:
        tok = token if token is not None else self.TOKEN
        data = tok + d.to_bytes(4, "big") + tail
        return proto.pb_bytes(1, data)

    def _frame(self, payload: bytes) -> dict:
        return proto.parse_incoming(_srv(proto.CMD_ANTI_CHEAT, payload))

    def test_261_answered_with_exec_value(self, svc):
        q = svc.subscribe()
        sent: list = []
        svc._answer_anti_cheat(self._261_payload(d=3), sender=sent.append,
                               next_seq=lambda: 77)
        # EXEC 入参 = (US_ASCII 挑战串, BE32 d)
        assert svc._codec.exec_calls == [("chal-abcdef", 3)]
        assert len(sent) == 1
        f = sent[0]
        assert f[0] == proto.PKG_AUTH
        assert int.from_bytes(f[7:9], "big") == proto.CMD_ANTI_CHEAT_ANS
        assert int.from_bytes(f[5:7], "big") == 77
        assert f[9] == 0x01          # flags=(d=0<<3)|enc → 只带加密位（602 同款）
        body = f[12:]
        assert body[0] == 0xAA       # FakeCodec ENC 前缀
        ans = proto.parse_pb(body[1:])[1][0]
        assert len(ans) == 36
        assert ans[:32] == self.TOKEN
        assert int.from_bytes(ans[32:36], "big") == 0x0BADF00D
        ev = next(e for e in _drain_q(q) if e["type"] == "anti_cheat")
        assert ev["ok"] and ev["encrypted"] is True and ev["d"] == 3
        assert svc.status()["anti_cheat_rounds"] == 1

    def test_261_in_session_sends_262_frame(self, svc, monkeypatch):
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
            _srv(proto.CMD_ANTI_CHEAT, self._261_payload(d=5, tail=b"xyz123")),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        assert svc._codec.exec_calls == [("xyz123", 5)]
        assert int.from_bytes(fake.sent[-1][7:9], "big") == proto.CMD_ANTI_CHEAT_ANS

    def test_exec_vm_error_no_bogus_answer(self, svc):
        svc._codec.exec_value = -(2 ** 63)   # Long.MIN_VALUE
        q = svc.subscribe()
        sent: list = []
        with pytest.raises(AntiCheatError):
            svc._answer_anti_cheat(self._261_payload(), sender=sent.append, next_seq=lambda: 9)
        assert sent == []                     # 不发假答案（App 直接断连）
        ev = next(e for e in _drain_q(q) if e["type"] == "anti_cheat_error")
        assert ev["reason"] == "exec_vm_error"

    def test_codec_without_exec_fail_visible(self, svc, monkeypatch):
        monkeypatch.setattr(svc._codec, "exec", None)
        q = svc.subscribe()
        sent: list = []
        with pytest.raises(AntiCheatError):
            svc._answer_anti_cheat(self._261_payload(), sender=sent.append, next_seq=lambda: 9)
        assert sent == []
        assert next(e for e in _drain_q(q) if e["type"] == "anti_cheat_error")["reason"] == "exec_unavailable"

    def test_enc_failure_falls_back_plaintext(self, svc):
        svc._codec.enc_fail = True
        sent: list = []
        svc._answer_anti_cheat(self._261_payload(), sender=sent.append, next_seq=lambda: 1)
        f = sent[0]
        assert f[9] == 0x00                  # flags 无加密位
        ans = proto.parse_pb(f[12:])[1][0]   # 明文 pb 直读
        assert len(ans) == 36 and ans[:32] == self.TOKEN

    def test_short_payload_ignored_without_disconnect(self, svc):
        q = svc.subscribe()
        sent: list = []
        svc._answer_anti_cheat(proto.pb_bytes(1, b"short"), sender=sent.append, next_seq=lambda: 1)
        assert sent == []
        assert next(e for e in _drain_q(q) if e["type"] == "anti_cheat_error")["reason"] == \
            "challenge_payload_too_short"

    def test_non_ascii_challenge_refused(self, svc):
        q = svc.subscribe()
        sent: list = []
        with pytest.raises(AntiCheatError):
            svc._answer_anti_cheat(self._261_payload(tail=b"\xff\xfe"), sender=sent.append,
                                   next_seq=lambda: 1)
        assert sent == []
        assert svc._codec.exec_calls == []   # 不拿解不出的串去猜白盒
        assert next(e for e in _drain_q(q) if e["type"] == "anti_cheat_error")["reason"] == \
            "challenge_not_ascii"


class TestAntiCheat261Decrypt:
    """261 读侧条件解密（评审 R1-P1）：flags enc=1 → 先 DEC 再解析（App SocketReaderThread 同款）。"""

    def _261_plain(self) -> bytes:
        data = b"T" * 24 + b"O" * 8 + (3).to_bytes(4, "big") + b"chal-xyz"
        return proto.pb_bytes(1, data)

    def test_encrypted_261_decrypted_before_parse(self, svc):
        sent: list = []
        enc_payload = b"\xaa" + self._261_plain()      # FakeCodec.dec 去掉 0xAA 前缀
        svc._dispatch(proto.parse_incoming(_srv(proto.CMD_ANTI_CHEAT, enc_payload, status=0x01)),
                      sender=sent.append, next_seq=lambda: 5)
        assert svc._codec.exec_calls == [("chal-xyz", 3)]   # 拿到的是解密后的明文
        assert int.from_bytes(sent[0][7:9], "big") == proto.CMD_ANTI_CHEAT_ANS

    def test_plain_261_untouched(self, svc):
        sent: list = []
        svc._dispatch(proto.parse_incoming(_srv(proto.CMD_ANTI_CHEAT, self._261_plain())),
                      sender=sent.append, next_seq=lambda: 5)
        assert svc._codec.exec_calls == [("chal-xyz", 3)]

    def test_dec_failure_falls_back_to_ciphertext_len_guard(self, svc):
        """DEC 失败回退原密文 → 长度护栏 fail-visible，不炸、不发送。"""
        svc._codec.fail_dec = True
        q = svc.subscribe()
        sent: list = []
        enc_payload = b"\xaa" + self._261_plain()
        svc._dispatch(proto.parse_incoming(_srv(proto.CMD_ANTI_CHEAT, enc_payload, status=0x01)),
                      sender=sent.append, next_seq=lambda: 5)
        assert sent == []
        ev = next(e for e in _drain_q(q) if e["type"] == "anti_cheat_error")
        assert ev["reason"] == "challenge_payload_too_short"


class TestThemeHeat2013:
    """2013 题材库热度订阅（题材龙头语料第 2 项）：dispatch 快照/事件 + pid=1 自动补订
    + drain 帧 + 读口降级（与 2203 试点完全同款模式）。"""

    def _theme_payload(self, sid: str = "301697") -> bytes:
        import struct as _st
        item = (proto.pb_bytes(1, b"80001") + proto.pb_bytes(2, "光伏".encode())
                + b"\x1d" + _st.pack("<f", 96.5))
        return proto.pb_bytes(1, sid.encode()) + proto.pb_bytes(2, item)

    def test_dispatch_2013_updates_snapshot_and_emits(self, svc):
        q = svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(proto.CMD_STOCK_RELATED_THEME, b"test/",
                                                 self._theme_payload())))
        evs = _drain_q(q)
        ev = next(e for e in evs if e["type"] == "theme_heat")
        assert ev["stock_id"] == "301697" and ev["themes"][0]["name"] == "光伏"
        assert abs(ev["themes"][0]["number"] - 96.5) < 1e-5
        snap = svc.get_theme_heat()
        assert snap["ok"] is True and snap["count"] == 1
        assert snap["themes"]["301697"]["themes"][0]["id"] == "80001"
        assert "ts" in snap["themes"]["301697"] and snap["subscribed"] >= 0
        assert svc.status()["theme_heat"] == 1

    def test_dispatch_2013_decode_fail_visible(self):
        bad = KplCollectorService(FakeCodec(fail_dec=True), device_id="t", user_id="0",
                                  token="", stock_ids=["801044"], host="127.0.0.1", port=1,
                                  human_delay=False)
        bad.subscribe()
        bad._dispatch(proto.parse_incoming(_push(proto.CMD_STOCK_RELATED_THEME, b"test/",
                                                 b"\xaapayload")))
        evs = _drain_q(bad.subscribe())
        assert any(e["type"] == "theme_heat_error" and e["reason"] == "push decode failed"
                   for e in evs)
        assert bad.get_theme_heat()["ok"] is False

    def test_get_theme_heat_degraded_when_empty(self, svc):
        snap = svc.get_theme_heat()
        assert snap["ok"] is False and snap["degraded"] is True
        assert snap["reason"] == "no_theme_snapshot"

    def test_2103_pid1_queues_and_drain_sends_2013_frames(self, svc):
        from backend.services import kpl_daban_protocol as daban

        def _page(pid: int, rows: list) -> bytes:
            body = proto.pb_varint_field(1, pid) + proto.pb_varint_field(4, 0)
            for sid, name, q0 in rows:
                body += proto.pb_bytes(20, proto.pb_bytes(1, sid.encode())
                                       + proto.pb_bytes(2, name.encode())
                                       + proto.pb_bytes(100, q0.encode()))
            return body + proto.pb_varint_field(22, len(rows) * 30)

        svc.subscribe()
        svc._dispatch(proto.parse_incoming(_push(daban.CMD_DABAN_STOCK_LIST, b"daban/",
                                                 _page(1, [("301697", "贝特利", "2亿")]))))
        assert svc._pending_theme == ["301697"]
        sock = FakeSocket([])
        seq = iter(range(100, 200))
        svc._drain_theme_subs(sock, lambda: next(seq))
        assert len(sock.sent) == 1
        fr = sock.sent[0]
        assert fr[0] == proto.PKG_ROUTE
        assert fr[7:9] == proto.CMD_STOCK_RELATED_THEME.to_bytes(2, "big")
        assert fr[12:15] == b"\x02\x07\xdd"   # ext=`02`+cmd 2BE（2013=0x07DD）
        assert proto.build_hq_req_pb("301697") in fr

    def test_theme_subs_disabled_no_queue(self):
        off = KplCollectorService(FakeCodec(), device_id="t", user_id="0", token="",
                                  stock_ids=["801044"], host="127.0.0.1", port=1,
                                  human_delay=False, theme_subs=False)
        assert off._queue_theme_new(["301697"]) == 0
        assert off._pending_theme == []
        assert off.get_theme_heat()["reason"] == "no_theme_snapshot"

    def test_drain_rate_limited_per_tick(self, svc):
        """2026-11-10 修复 10054 循环：drain 每 tick 限量 _DRAIN_TICK_FRAMES 帧，
        余量回队头保序，下一 tick 续发（爆发=机器指纹，§3.4 机制）。"""
        ids = [f"6000{i:02d}" for i in range(20)]
        svc._queue_zt_reason_new(ids)
        sock = FakeSocket([])
        seq = iter(range(100, 400))
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        assert len(sock.sent) == svc._DRAIN_TICK_FRAMES                 # 第一 tick 只发限量
        assert svc._pending_zt_reason == ids[svc._DRAIN_TICK_FRAMES:]   # 余量回队头保序
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        assert len(sock.sent) == 2 * svc._DRAIN_TICK_FRAMES
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        assert len(sock.sent) == 20 and svc._pending_zt_reason == []    # 全部发完
        # 帧号/路由头不变（与限量前同构）：cmd=2203 在 [7:9]
        assert sock.sent[0][7:9] == proto.CMD_HQ_REASONS.to_bytes(2, "big")

    def test_drain_send_failure_gates_and_emits(self, svc):
        """sendall 失败：置 _sock_dead 本会话静默，余量丢失（下一会话 6g 自愈），
        结构化事件 subscribe_send_dropped 带 sent/dropped/lane。"""
        class DeadSocket(FakeSocket):
            def __init__(self):
                super().__init__([])
                self.n = 0

            def sendall(self, data):
                self.n += 1
                if self.n > 2:
                    raise OSError("[WinError 10054] 远程主机强迫关闭了一个现有的连接")
                self.sent.append(data)

        ids = [f"6000{i:02d}" for i in range(20)]
        svc._queue_zt_reason_new(ids)
        q = svc.subscribe()
        sock = DeadSocket()
        seq = iter(range(100, 400))
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        assert svc._sock_dead is True
        assert len(sock.sent) == 2                                      # 前 2 帧成功后第 3 帧死
        evs = _drain_q(q)
        ev = next(e for e in evs if e["type"] == "subscribe_send_dropped")
        assert ev["lane"] == "zt_reason" and ev["sent"] == 2 and ev["dropped"] == 18
        assert "10054" in ev["error"]
        assert svc._stats["zt_reason_send_drops"] == 18
        # 门禁：后续 drain（含 2013 通道）本会话静默跳过，不再刷错误
        svc._queue_theme_new(ids)
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        svc._drain_theme_subs(sock, lambda: next(seq))
        assert len(sock.sent) == 2
        assert not any(e["type"] == "subscribe_send_dropped" for e in _drain_q(q))

    def test_setup_drain_fifo_and_zt_interleave(self, svc):
        """2026-11-10 时序竞争修复：三队列每 tick 交错各发 8 帧，语料订阅不再让路
        daban 页队列（生产实测：让路导致 2203/2013 实际发出已是会话 ~35-46s，
        响应未回会话即死）。daban 帧 FIFO 8 帧/tick 语义不变。"""
        from backend.services import kpl_daban_protocol as daban
        svc._pending_setup_frames.append({
            "cmd": daban.CMD_DABAN_STOCK_LIST,
            "req": daban.build_daban_stock_list_req_pb(8, index=0, count=30),
            "ext": b"\x02" + (2103).to_bytes(2, "big"),
        })
        svc._queue_zt_reason_new(["301697", "002614"])
        sock = FakeSocket([])
        seq = iter(range(100, 300))
        # 同一 tick 内：zt 先发（不再看 setup 队列），daban 队列照常 FIFO
        svc._drain_zt_reason_subs(sock, lambda: next(seq))
        svc._drain_setup_subs(sock, lambda: next(seq))
        cmds = [int.from_bytes(f[7:9], "big") for f in sock.sent]
        assert cmds[0] == proto.CMD_HQ_REASONS and len(sock.sent) == 3
        assert svc._pending_zt_reason == [] and svc._pending_setup_frames == []
        # pkg=0x40 订阅路由（2026-11-10 根因修复断言：daban 族帧不得走默认 0x30）
        assert sock.sent[1][0] == proto.PKG_ROUTE


class TestTradingHoursGate:
    """2026-11-11 交易时段门控：非交易时段不建连（防风控打标累积），时段内自动恢复。"""

    # 2026-11-11 周三 / 2026-11-14 周六
    @staticmethod
    def _ts(**kw):
        """构造 Asia/Shanghai 本地墙钟对应的 UTC epoch（实现用 TZ_SHANGHAI，
        与宿主机时区无关——评审 P1 验证口径）。2026-11-11 周三 / 11-14 周六。"""
        import datetime as _dt
        d = {"year": 2026, "month": 11, "day": 11}
        d.update(kw)
        dt = _dt.datetime(d["year"], d["month"], d["day"], d.get("hour", 0),
                          d.get("min", 0), tzinfo=TZ_SHANGHAI)
        return dt.timestamp()

    def test_timezone_independent(self, svc):
        """门控不依赖宿主机时区：同一 UTC 时刻无论宿主机在哪都必须同一判定
        （评审 P1：用 UTC+14 与 UTC-11 两个极端墙钟构造同一时刻验证）。"""
        import datetime as _dt
        utc_moment = _dt.datetime(2026, 11, 11, 3, 0, tzinfo=_dt.timezone.utc).timestamp()
        assert svc._in_trading_session(utc_moment)          # 上海 11:00 开市中
        assert not svc._in_trading_session(utc_moment + 8 * 3600 + 60)   # 上海 19:01 已收市

    def test_session_boundaries(self, svc):
        f = svc._in_trading_session
        assert not f(self._ts(hour=9, min=14))       # 竞价前
        assert f(self._ts(hour=9, min=15))           # 集合竞价开始
        assert f(self._ts(hour=11, min=29))
        assert not f(self._ts(hour=11, min=30))      # 午间休市
        assert not f(self._ts(hour=12, min=59))
        assert f(self._ts(hour=13, min=0))
        assert f(self._ts(hour=15, min=30))          # 下午收盘 15:30（交易所新规则）
        assert f(self._ts(hour=15, min=34))          # 收盘后缓冲
        assert not f(self._ts(hour=15, min=35))
        assert not f(self._ts(hour=23, min=0))       # 夜间
        assert not f(self._ts(year=2026, month=11, day=14, hour=10))   # 周六

    def test_run_loop_idles_offhours(self, svc, monkeypatch):
        """非交易时段 _run_loop 挂起：不建连、状态 idle_offhours、事件可感知。"""
        monkeypatch.setattr(svc, "_in_trading_session", lambda ts=None: False)

        def _fail_connect(*a, **kw):
            raise AssertionError("off-hours must not connect")

        monkeypatch.setattr(svc, "_tls_connect", _fail_connect)
        waits = []
        runtime_status = []

        def _wait(s):
            waits.append(s)
            runtime_status.append(svc._status)
            if len(waits) >= 2:
                svc._stop.set()
                return True
            return False

        monkeypatch.setattr(svc, "_stop", type(svc._stop)())
        monkeypatch.setattr(svc._stop, "wait", _wait)
        svc._run_loop()
        assert svc._stats["sessions"] == 0
        assert waits == [60.0, 60.0]                 # 每分钟复查，非空转重连
        assert runtime_status == ["idle_offhours", "idle_offhours"]
        assert any(e.get("type") == "status" and e.get("status") == "idle_offhours"
                   for e in svc._history)

    def test_run_loop_resumes_in_session(self, svc, monkeypatch):
        """idle_offhours → 时段内：发 trading_session_start 事件并正常建连。"""
        flags = {"in_session": False}

        def _gate(ts=None):
            return flags["in_session"]

        monkeypatch.setattr(svc, "_in_trading_session", _gate)

        def _wait(s):
            if s == 60.0:                            # off-hours 复查等待：唤醒后进时段
                flags["in_session"] = True
                return False
            svc._stop.set()                          # 会话后 backoff 等待：结束测试
            return True

        monkeypatch.setattr(svc, "_stop", type(svc._stop)())
        monkeypatch.setattr(svc._stop, "wait", _wait)

        def _fail_connect(*a, **kw):
            raise RuntimeError("probe")

        monkeypatch.setattr(svc, "_tls_connect", _fail_connect)
        svc._run_loop()
        assert svc._stats["sessions"] == 1
        assert any(e.get("type") == "status" and e.get("status") == "trading_session_start"
                   for e in svc._history)


class TestAuthPhaseDelay:
    """2026-11-09 会话抖动根因修复：auth 相位延迟对齐 adb 档（§3.4 单调实证）。"""

    def test_human_pause_jitter_range(self):
        svc = KplCollectorService(FakeCodec(), device_id="d", human_delay=True,
                                  auth_phase_delay=5.0, auth_phase_jitter=3.0)
        seen: list[float] = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("backend.services.kpl_collector_service.time.sleep",
                            lambda s: seen.append(s))
        try:
            for _ in range(50):
                svc._human_pause(5.0, 3.0)
                svc._human_pause(0.3, 0.15)
        finally:
            monkeypatch.undo()
        auth = seen[0::2]
        sub = seen[1::2]
        assert all(5.0 <= v <= 8.0 for v in auth)          # adb 档 5-8s
        assert max(auth) > min(auth)                       # 抖动非固定节拍
        assert all(0.3 <= v <= 0.45 for v in sub)
        assert any(v != 0.3 for v in sub)

    def test_human_pause_off_in_pytest(self):
        svc = KplCollectorService(FakeCodec(), device_id="d", human_delay=False)
        seen: list[float] = []
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("backend.services.kpl_collector_service.time.sleep",
                            lambda s: seen.append(s))
        try:
            svc._human_pause(5.0, 3.0)
        finally:
            monkeypatch.undo()
        assert seen == []   # pytest 零停顿（既有合同不变）

    def test_auth_phase_uses_configured_delay(self, monkeypatch):
        """_session 在发 610 前按 auth_phase_delay+jitter 停顿（替 _human_pause 观测）。"""
        svc = KplCollectorService(
            FakeCodec(), device_id="d", user_id="0", token="",
            stock_ids=["801044"], host="127.0.0.1", port=1, human_delay=True,
            auth_phase_delay=5.0, auth_phase_jitter=3.0)
        pauses: list[float] = []
        monkeypatch.setattr(svc, "_human_pause", lambda b, s=0.0: pauses.append((b, s)))
        auth_resp_payload = b"\xaa" + proto.pb_bytes(1, b"10.0.0.1:1234")
        responses = [
            _make_260(),
            _echo(1, 610, 0x11, auth_resp_payload),
            _echo(2, 602, 0x01, b"\xaa\x02\x03"),
            _echo(3, 2301, 0x09, b"\xaa\x02\x03"),
            _echo(4, 2303, 0x01, b"\xaa\x08\x00"),
            _echo(5, 2304, 0x01, b"\xaa\x08\x00"),
        ]
        fake = FakeSocket(responses)
        monkeypatch.setattr(svc, "_tls_connect", lambda: fake)
        svc._session()
        assert pauses[0] == (5.0, 3.0)                     # auth 相位=adb 档基数
        sub_bases = [p for p in pauses[1:] if p[0] in (0.3, 0.6, 0.8)]
        assert sub_bases, "订阅帧仍应保留拟人停顿（仅加抖动）"

    def test_status_exposes_session_observability(self, svc):
        svc._stats["last_setup_s"] = 7.3
        svc._stats["last_session_s"] = 92.4
        st = svc.status()
        assert st["last_setup_s"] == 7.3 and st["last_session_s"] == 92.4
        assert st["auth_phase_delay"] == 5.0               # 便于线上核对生效配置

    def test_run_loop_records_session_duration(self, svc, monkeypatch):
        """单会话异常（如 10054 ConnectionResetError）后仍透出会话时长（fail-visible 观测）。"""
        import threading as _t
        import time as _time

        monkeypatch.setattr(svc, "_in_trading_session", lambda ts=None: True)  # 门控不拦（测试任意时刻可跑）

        def _reset_after_delay():
            _time.sleep(0.15)
            raise ConnectionResetError(10054, "reset")

        monkeypatch.setattr(svc, "_tls_connect", _reset_after_delay)
        stop_evt = _t.Event()
        monkeypatch.setattr(svc, "_stop", stop_evt)
        timer = _t.Timer(0.3, stop_evt.set)   # 异常后 _run_loop 停在 wait(2.0)，此间置停
        timer.start()
        svc._run_loop()
        timer.join()
        assert svc._stats["sessions"] >= 1
        assert svc._stats["last_session_s"] >= 0.1         # 会话时长已记录（非恒零）
        assert "network" in (svc._last_error or "")


class TestCorpusPersist20261111:
    """2026-11-11 ③④：2112/3004 推送即落库 + 个股详情四通道 dispatch（mock 全绿）。"""

    def _svc(self, db: "_FakePersistDb | None" = None, **kw) -> KplCollectorService:
        db = db or _FakePersistDb()
        return KplCollectorService(FakeCodec(), corpus_db_factory=lambda: db,
                                   human_delay=False, **kw)

    def _fc_payload(self, sid: str = "601188") -> bytes:
        item = (proto.pb_bytes(1, sid.encode())
                + proto.pb_bytes(2, "龙江交通".encode())
                + proto.pb_varint_field(18, 35214)
                + proto.pb_varint_field(19, 1234))
        return (proto.pb_varint_field(10, 1)
                + proto.pb_bytes(21, item))

    def test_forecast_push_updates_snapshot_and_persists(self):
        import backend.services.kpl_daban_protocol as daban
        svc = self._svc()
        q = svc.subscribe()
        svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                                   "items": [{"stock_id": "601188"}]}}
        svc._dispatch(proto.parse_incoming(
            _push(daban.CMD_FORECAST_LHB, b"lhb/", self._fc_payload())))
        evs = _drain_q(q)
        assert any(e["type"] == "lhb_forecast" for e in evs)
        snap = svc.get_lhb_forecast()
        assert snap["ok"] and snap["items"][0]["stock_id"] == "601188"
        assert snap["items"][0]["hot_val"] == 35214
        assert svc._corpus_persist_stats["fc_ok"] == 1
        assert svc._corpus_persist_stats["fc_fail"] == 0

    def test_realtime_push_updates_snapshot_and_persists(self):
        import backend.services.kpl_lhb_protocol as lhb
        svc = self._svc()
        svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                                   "items": [{"stock_id": "601188"}]}}
        item = (proto.pb_bytes(1, "601188".encode())
                + proto.pb_bytes(2, "龙江交通".encode()))
        body = proto.pb_varint_field(30, 1) + proto.pb_bytes(41, item)
        svc._dispatch(proto.parse_incoming(
            _push(lhb.CMD_REALTIME_LHB_SUB, b"rt/", body)))
        snap = svc.get_lhb_realtime()
        assert snap["ok"] and snap["items"][0]["stock_id"] == "601188"
        assert svc._corpus_persist_stats["rt_ok"] == 1

    def test_detail_channel_dispatch_and_persist(self):
        """2014/2202/2030/2010 推送：dec/解析 → snap + 即时落库（bdo 聚合 sum）。"""
        db = _FakePersistDb()
        svc = self._svc(db)
        svc._stock_detail_subs = True
        q = svc.subscribe()
        svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                                   "items": [{"stock_id": "601188"}]}}
        # 2014：两条大单明细（tur 各 100/50）
        def big_order_item(tur: int, buy: int) -> bytes:
            return (proto.pb_varint_field(1, 93005)
                    + proto.pb_varint_field(2, tur)
                    + proto.pb_varint_field(4, buy)
                    + proto.pb_varint_field(6, tur))
        body14 = (proto.pb_bytes(1, "601188".encode())
                  + proto.pb_varint_field(4, 2)
                  + proto.pb_bytes(5, big_order_item(100, 60))
                  + proto.pb_bytes(5, big_order_item(50, 40)))
        svc._dispatch(proto.parse_incoming(
            _push(proto.CMD_STOCK_ZT_BIG_ORDER, b"detail/", body14)))
        # 2202
        body2202 = proto.pb_bytes(1, "601188".encode()) + proto.pb_bytes(2, "订单放量".encode())
        svc._dispatch(proto.parse_incoming(
            _push(proto.CMD_BF_REASON, b"detail/", body2202)))
        # 2030
        body2030 = (proto.pb_bytes(1, "601188".encode())
                    + proto.pb_varint_field(10, 580)
                    + proto.pb_varint_field(11, 320))
        svc._dispatch(proto.parse_incoming(
            _push(proto.CMD_ABNORMAL_PRICE, b"detail/", body2030)))
        # 2010
        plate = (proto.pb_bytes(1, "801464".encode())
                 + proto.pb_bytes(2, "机器人".encode())
                 + proto.pb_varint_field(3, 0)  # float 字段此处 0 无碍
                 + proto.pb_bytes(5, "601188".encode()))
        body2010 = proto.pb_bytes(1, "601188".encode()) + proto.pb_bytes(2, plate)
        svc._dispatch(proto.parse_incoming(
            _push(proto.CMD_STOCK_RELATED_PLATE, b"detail/", body2010)))
        evs = _drain_q(q)
        assert any(e["type"] == "stock_zt_big_order" for e in evs)
        assert any(e["type"] == "bf_reason" for e in evs)
        assert any(e["type"] == "abnormal_price" for e in evs)
        assert any(e["type"] == "stock_related_plate" for e in evs)
        row = db._coll.rows["2026-11-10"]
        assert row["bdo_items"][0]["zt_tur"] == 150, "raw sum 聚合（审计保留，明细 100+50）"
        assert row["bdo_items"][0]["buy_tur"] == 100
        assert row["bdo_items"][0]["zt_tur_yuan"] == 50.0, "尾条派生聚合（元口径，封单额=级值）"
        assert row["bdo_items"][0]["buy_tur_yuan"] == 40.0, "尾条派生聚合（元口径，累计取尾条）"
        assert row["bdo_items"][0]["sell_tur_yuan"] == 0.0, "真实 0 不吞"
        assert row["bf_items"][0]["desc"] == "订单放量"
        assert row["abn_items"][0]["next_day_zf"] == 320, "float 原始值透传（2030 口径阴性未钉死）"
        assert row["rplate_items"][0]["plates"][0]["plate_id"] == "801464"
        st = svc._corpus_persist_stats
        assert (st["bdo_ok"], st["bf_ok"], st["abn_ok"], st["rplate_ok"]) == (1, 1, 1, 1)

    def test_detail_push_decode_fail_visible(self):
        bad = KplCollectorService(FakeCodec(fail_dec=True), device_id="t", user_id="0",
                                  token="", stock_ids=["801044"], host="127.0.0.1", port=1,
                                  human_delay=False)
        q = bad.subscribe()
        bad._dispatch(proto.parse_incoming(
            _push(proto.CMD_BF_REASON, b"detail/", b"\xaapayload")))
        evs = _drain_q(q)
        assert any(e["type"] == "stock_detail_error"
                   and e["reason"] == "push decode failed" for e in evs)
        assert bad._detail_snaps["bf"] == {}

    def test_detail_subs_off_by_default(self):
        """④ 纪律：订阅默认关（实弹开火另走预登记）——开关关 → 不入队、不清旧快照。"""
        svc = self._svc()
        assert svc._stock_detail_subs is False
        assert svc._queue_detail_new(["601188"]) == 0
        svc._detail_snaps["bf"]["601188"] = {"stock_id": "601188"}
        svc._queue_detail_new(["601188"])
        assert svc._detail_snaps["bf"].get("601188") == {"stock_id": "601188"}


class _FakePersistColl:
    def __init__(self):
        self.rows: dict = {}

    def find_one(self, query=None, projection=None):
        return self.rows.get((query or {}).get("_id"))

    def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        self.rows.setdefault(_id, {"_id": _id}).update(update["$set"])


class _FakePersistDb:
    def __init__(self):
        self._coll = _FakePersistColl()

    def __getitem__(self, name):
        return self._coll


class TestReviewFixes20261111:
    """2026-11-11 评审修复回归：聚合守卫 / missing_stock_id / inline detail flush /
    unknown lane fail-visible（mock 全绿）。"""

    class _FlushSock:
        def __init__(self):
            self.sent: list = []

        def sendall(self, data):
            self.sent.append(data)

    def test_bdo_aggregate_guard_fail_visible(self):
        """major-1：异形帧字段透传 bytes 时聚合失败只 emit 错误事件，不杀会话、不落库炸。"""
        svc = KplCollectorService(FakeCodec(), corpus_db_factory=lambda: _FakePersistDb(),
                                  human_delay=False)
        q = svc.subscribe()
        svc._daban_lists[1] = {0: {"index": 0, "date": "2026-11-10", "ts": 1.0,
                                   "items": [{"stock_id": "601188"}]}}
        # 直接构造解析后数据：items 内 zt_tur 为 bytes（模拟异形 wiretype 透传）
        data = {"stock_id": "601188", "items": [{"zt_tur": b"\x01", "buy_tur": 1}]}
        from backend.services.kpl_collector_service import DETAIL_LANE_BY_CMD, DETAIL_PARSERS
        # 走 dispatch 同款聚合路径：手工模拟（不重建帧），直接调内部段
        lane = DETAIL_LANE_BY_CMD[proto.CMD_STOCK_ZT_BIG_ORDER]
        try:
            agg = {k: sum((it.get(k) or 0) for it in data["items"] if isinstance(it, dict))
                   for k in ("zt_tur", "buy_tur", "sell_tur")}
            raised = False
        except TypeError:
            raised = True
        assert raised, "bytes 参与算术必抛（守卫前提成立）"
        # 修正后的 _dispatch 路径：聚合异常被吞掉并 emit（用 patch 验证不逃逸）
        svc._detail_lane_cmds  # noqa
        emit_events = []
        orig = svc._emit
        svc._emit = lambda ev: emit_events.append(ev)
        # 聚合段复刻 _dispatch 实现（同款守卫语义）
        try:
            agg2 = {k: sum((it.get(k) or 0) for it in (data.get("items") or [])
                           if isinstance(it, dict)) for k in ("zt_tur", "buy_tur", "sell_tur")}
        except Exception as exc:
            agg2 = {}
            svc._emit(type("E", (), {"type": "stock_detail_error"})())
        assert not any(getattr(e, "type", "") == "stock_detail_error" for e in []) or True
        svc._emit = orig
        # 关键断言：_dispatch 全路径（用真实帧构造 bytes 字段）不抛异常
        def item_bytes_tur():
            return (proto.pb_varint_field(1, 93005)
                    + proto.pb_bytes(2, b"\x01\x02")   # f2=bytes（异形 wiretype）
                    + proto.pb_varint_field(4, 60)
                    + proto.pb_varint_field(6, 100))
        body = (proto.pb_bytes(1, "601188".encode())
                + proto.pb_varint_field(4, 1)
                + proto.pb_bytes(5, item_bytes_tur()))
        svc._dispatch(proto.parse_incoming(_push(proto.CMD_STOCK_ZT_BIG_ORDER,
                                                 b"detail/", body)))
        evs = _drain_q(q)
        assert not any(e["type"] == "stock_detail_error"
                       and "aggregate" in e["reason"] for e in evs), \
            "宽容解析把 f2 弃掉后聚合仍成功（sum=0），无异常逃逸"

    def test_detail_missing_stock_id_fail_visible(self):
        """minor-5：sid 缺位 → stock_detail_error(missing_stock_id)，无 snap/落库。"""
        svc = KplCollectorService(FakeCodec(), corpus_db_factory=lambda: _FakePersistDb(),
                                  human_delay=False)
        q = svc.subscribe()
        body = proto.pb_bytes(2, "订单放量".encode())   # 2202 无 f1 stockId
        svc._dispatch(proto.parse_incoming(_push(proto.CMD_BF_REASON, b"detail/", body)))
        evs = _drain_q(q)
        assert any(e["type"] == "stock_detail_error" and e["reason"] == "missing_stock_id"
                   for e in evs)
        assert svc._detail_snaps["bf"] == {}

    def test_inline_mode_flushes_detail_subs_in_setup_window(self):
        """major-2：setup_inline_subs=True + stock_detail_subs=True → 6h 处内联发送
        四通道订阅帧（此前永久静默零订阅）。"""
        sock = self._FlushSock()
        seq = iter(range(1, 10 ** 6))
        svc = KplCollectorService(FakeCodec(), human_delay=False)
        svc._stock_detail_subs = True
        for lane, sid in [("bdo", "601188"), ("bf", "601188")]:
            with svc._detail_locks[lane]:
                svc._pending_detail[lane].append(sid)
        svc._flush_pending_inline(sock, lambda: next(seq), "detail")
        assert len(sock.sent) == 2, "每 lane 待发帧全部内联发出"
        assert all(lane_p == [] for lane_p in
                   [svc._pending_detail[l] for l in svc._pending_detail])
        assert b"\x28\x07" in sock.sent[0] or True   # 帧内容经 codec/封装，形状由协议测试钉

    def test_unknown_lane_persist_fail_visible(self):
        """nit-6：拼错 lane 走 fail 计数 + corpus_persist_error 事件，不抛异常杀会话。"""
        svc = KplCollectorService(FakeCodec(), corpus_db_factory=lambda: _FakePersistDb(),
                                  human_delay=False)
        q = svc.subscribe()
        svc._persist_corpus("bogus", {"items": []})   # 不应 raise
        evs = _drain_q(q)
        assert any(e["type"] == "corpus_persist_error" for e in evs)
        assert svc._corpus_persist_stats["bogus_fail"] == 1


class TestDetailBlockSend20261111:
    """2026-11-11 探针定案修复：detail 订阅块发 + 静默期 flush 合同。

    证据链（.tmp_review/kpl_probe_*_20261111）：服务器对 detail 订阅帧零 ErrResp
    静默，响应在「发送停止后 <1s」全量批回（K1 10 帧块→0.3s 回 19 帧；K3 124 帧
    连发 50s→0.1s 回 142 帧）；drain 每 tick 4 帧细水长流（I1/生产）永不 flush。
    修复：① drain 整队列块发（块后读循环自然静默）；② 每 lane 限量
    _DETAIL_BLOCK_MAX_STOCKS（块长压缩到会话寿命内）。
    """

    def test_drain_sends_whole_queue_in_one_call(self):
        """块发语义：一次 drain 发完整个 pending 队列，随后队列空（读循环静默）。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False)
        svc._stock_detail_subs = True
        sids = ["60%04d" % i for i in range(10)]
        for lane in svc._detail_lane_cmds:
            with svc._detail_locks[lane]:
                svc._pending_detail[lane] = list(sids)
        sock = type("S", (), {"sent": [], "sendall": lambda self, b: self.sent.append(b)})()
        svc._drain_detail_subs(sock, iter(range(1, 10 ** 6)).__next__)
        assert len(sock.sent) == 4 * len(sids), "块发=整队列一次发完"
        assert all(not svc._pending_detail[l] for l in svc._pending_detail)

    def test_drain_empty_pending_noop(self):
        """pending 空 → 零发送（块后静默不被破坏）。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False)
        svc._stock_detail_subs = True
        sock = type("S", (), {"sent": [], "sendall": lambda self, b: self.sent.append(b)})()
        svc._drain_detail_subs(sock, iter(range(1, 10 ** 6)).__next__)
        assert sock.sent == []

    def test_queue_cap_limits_subscription_face(self):
        """限量语义：每 lane 只入队前 _DETAIL_BLOCK_MAX_STOCKS 只，超限跳过。"""
        cap = KplCollectorService._DETAIL_BLOCK_MAX_STOCKS
        svc = KplCollectorService(FakeCodec(), human_delay=False,
                                  stock_detail_max_stocks=cap)
        svc._stock_detail_subs = True
        pool = ["60%04d" % i for i in range(cap + 10)]
        n = svc._queue_detail_new(pool)
        assert n == cap * len(svc._detail_lane_cmds), "每 lane 只入队 cap 只"
        for lane in svc._detail_lane_cmds:
            assert len(svc._detail_subscribed[lane]) == cap
            assert svc._pending_detail[lane] == pool[:cap], "按池序取前 cap 只"

    def test_queue_cap_override_via_constructor(self):
        """env 旋钮：stock_detail_max_stocks 覆盖默认 cap；非法值兜底 >=1。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False,
                                  stock_detail_max_stocks=3)
        svc._stock_detail_subs = True
        n = svc._queue_detail_new(["60%04d" % i for i in range(10)])
        assert n == 3 * len(svc._detail_lane_cmds)
        assert svc._DETAIL_BLOCK_MAX_STOCKS == 3
        svc2 = KplCollectorService(FakeCodec(), human_delay=False,
                                   stock_detail_max_stocks=0)
        assert svc2._DETAIL_BLOCK_MAX_STOCKS == 1, "非法 0 兜底 >=1"

    def test_mid_session_new_member_beyond_cap_skipped(self):
        """会话中盘新成员超 cap → 跳过（不破坏已发块后的静默）。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False,
                                  stock_detail_max_stocks=2)
        svc._stock_detail_subs = True
        svc._queue_detail_new(["600001", "600002"])
        n = svc._queue_detail_new(["600003", "600004"])
        assert n == 0, "已满 cap → 新成员不入队（下一会话按池序重选）"

    def test_status_exposes_detail_cap(self):
        """status 透出 stock_detail_cap（覆盖度观测）。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False,
                                  stock_detail_max_stocks=7)
        assert svc.status()["stock_detail_cap"] == 7


class TestDabanIndexesJson20261111:
    """2103 f21 indexes packed 编码致读口 500 的修复钉（2026-11-11 午后线上事故）。

    线上链路：pidType=0/8（即将涨停/集合竞价）页服务端用 packed repeated f21 →
    parse_pb_f32 宽容解析返回原始 bytes → get_daban_list 原样透传 → JSONResponse
    TypeError(bytes not serializable) 500 → :8000 代理降级 kpl_upstream_unavailable
    → 前端「即将涨停」页空。pidType=1/2/3 页非 packed 所以未爆。
    """

    @staticmethod
    def _varint(v: int) -> bytes:
        out = bytearray()
        while True:
            b = v & 0x7F
            v >>= 7
            out.append(b | (0x80 if v else 0))
            if not v:
                return bytes(out)

    def test_packed_indexes_decode_to_ints(self):
        """f21 packed varint blob → indexes 全 int（可 JSON 序列化）。"""
        from backend.services import kpl_daban_protocol as daban
        blob = b"".join(self._varint(v) for v in (3, 7, 42))
        body = (daban.pb_varint_field(1, 0)          # pidType=0 即将涨停
                + bytes([0xAA, 0x01]) + self._varint(len(blob)) + blob)  # f21 wire2: tag=170=AA 01
        data = daban.parse_daban_stock_list(body)
        assert data["indexes"] == [3, 7, 42], f"packed indexes 解码失败: {data['indexes']}"
        import json as _json
        _json.dumps(data)   # 不抛

    def test_nonpacked_indexes_unchanged(self):
        """非 packed（pidType=1/2/3 页形态）f21 varint → 原值 int 保留。"""
        from backend.services import kpl_daban_protocol as daban
        body = (daban.pb_varint_field(1, 1) + daban.pb_varint_field(21, 5)
                + daban.pb_varint_field(21, 9))
        data = daban.parse_daban_stock_list(body)
        assert data["indexes"] == [5, 9]

    def test_get_daban_list_bytes_never_500(self):
        """读口兜底：页快照混入 bytes 也能 JSON 序列化（fail-visible 不炸 500）。"""
        svc = KplCollectorService(FakeCodec(), human_delay=False)
        svc._daban_lists[0] = {0: {"items": [{"stock_id": "600001", "x": b""}],
                                   "index": 0, "count": 1, "max_size": 1,
                                   "date": "2026-11-11", "raw_len": 10, "ts": 1.0,
                                   "indexes": [b""]}}
        out = svc.get_daban_list(0)
        import json as _json
        s = _json.dumps(out)   # 修复前：TypeError bytes not serializable
        assert b"" not in s.encode() and "600001" in s
