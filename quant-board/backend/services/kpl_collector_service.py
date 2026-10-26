# -*- coding: utf-8 -*-
"""KPL socket 采集服务：后台线程维持 signsvc + TLS 会话链，解码行情事件并广播。

职责边界（2026-10-27 设计）：
- 本模块是唯一允许发起真实 KPL TLS 连接的运行时组件；pytest 不得触发（用 mock codec）。
- 加密/解密/签名全部走注入的 codec（默认 SignSvcAdbCodec → 模拟器内 signsvc 常驻进程）。
- fail-visible：连接失败 / 解码失败 / 服务器错误一律变成结构化事件广播，绝不静默丢弃；
  同时记录 last_error 供 /api/kpl/status 查询。
- 会话模型：服务器 TTL ≈ 60-90s（与心跳频率无关），连接断开后 2s 重连（app 的
  ReconnectManager 同款策略），数据流跨会话连续写入同一事件流。
- WebSocket 层（serve_kpl_socket.py）只做转发：从 subscribe() 的队列读取事件推送浏览器。

线程模型：
- 主线程（FastAPI/uvicorn）只消费事件队列，绝不阻塞在 socket 读写。
- 采集线程 _run_loop 持有 TLS socket；stop() 置位停止标志并关闭 socket。
"""
from __future__ import annotations

import os
import queue
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from backend.services import kpl_socket_protocol as proto

# 与 .tmp_review/kpl_collector.py 一致的连接参数（实测有效组合）
DEFAULT_HOST = "124.71.0.49"
DEFAULT_PORT = 8080
TLS_SNI = "socket.kaipan.com"


class SignSvcError(RuntimeError):
    """signsvc 调用失败（含设备离线 / READY 超时 / RES null）。"""


class SignSvcAdbCodec:
    """通过 adb 驱动模拟器内 signsvc 常驻进程，提供 ENC/DEC/WBE。

    WBE(challenge, deviceId, connType, curTime) → signature bytes（hex 字符串）
    ENC(plain) → GCM 密文；DEC(cipher) → 明文。失败抛 SignSvcError（fail-visible）。
    """

    def __init__(self, adb_path: str, device: str, shell_cmd: str, ready_timeout: float = 30.0):
        self._adb = adb_path
        self._device = device
        self._shell_cmd = shell_cmd
        self._ready_timeout = ready_timeout
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _ensure_ready(self) -> subprocess.Popen:
        with self._lock:
            if self._proc is not None:
                return self._proc
            proc = subprocess.Popen(
                [self._adb, "-s", self._device, "shell", self._shell_cmd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            deadline = time.time() + self._ready_timeout
            while time.time() < deadline:
                line = proc.stdout.readline().decode(errors="replace").strip()  # type: ignore[union-attr]
                if line == "READY":
                    self._proc = proc
                    return proc
                if proc.poll() is not None:
                    raise SignSvcError(f"signsvc exited before READY")
            raise SignSvcError("signsvc READY timeout")

    def _cmd(self, q: str) -> str:
        for attempt in range(2):
            try:
                proc = self._ensure_ready()
                assert proc.stdin is not None and proc.stdout is not None
                proc.stdin.write((q + "\n").encode())
                proc.stdin.flush()
                eof = 0
                while True:
                    line = proc.stdout.readline().decode(errors="replace").strip()
                    if line.startswith(("RESH", "RES ", "ERR")):
                        return line
                    if line == "":
                        # 子进程 EOF（segfault 等）：readline 立即返回空串，避免死旋
                        eof += 1
                        if eof > 50:
                            raise OSError("signsvc EOF")
                        continue
                    # MARK 等杂音跳过
            except Exception:
                if attempt == 1:
                    raise SignSvcError(f"signsvc pipe broken: {q[:12]}…")
                # 重建进程后重试一次
                with self._lock:
                    try:
                        if self._proc is not None:
                            self._proc.kill()
                    except Exception:
                        pass
                    self._proc = None
        raise SignSvcError("unreachable")

    def enc(self, plain: bytes) -> Optional[bytes]:
        line = self._cmd("ENC|" + plain.hex())
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return bytes.fromhex(hx.strip())
        return None

    def dec(self, cipher_hex: str) -> Optional[bytes]:
        line = self._cmd("DEC|" + cipher_hex)
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return bytes.fromhex(hx.strip())
        return None

    def wbe(self, challenge: str, device_id: str, conn_type: str, cur_time: str) -> Optional[str]:
        line = self._cmd(f"WBE|{challenge}|{device_id}|{conn_type}|{cur_time}")
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return hx.strip()
        return None

    def close(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None


class KplEvent(dict):
    """结构化事件：type ∈ auth/sub/push/error/status；全部可 JSON 序列化。"""


class KplCollectorService:
    """采集 + 广播服务。start() 后事件进入广播队列，WebSocket 消费者各持游标。"""

    def __init__(
        self,
        codec: Any,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        device_id: str = "",
        user_id: str = "0",
        token: str = "",
        version_name: str = "6.3.20.2",
        channel_id: int = 129,
        conn_type: int = 99,
        api_version: str = "w48",
        stock_ids: Optional[List[str]] = None,
        history: int = 200,
        human_delay: bool = True,
    ):
        self._codec = codec
        self._host = host
        self._port = port
        self._device_id = device_id
        self._user_id = user_id
        self._token = token
        self._version_name = version_name
        self._channel_id = channel_id
        self._conn_type = conn_type
        self._api_version = api_version
        # 拟人延迟开关（服务器对 <1s 完成认证的连接 ~6s 即断连；pytest 置 False）
        self._human_delay = human_delay
        # 板块(801044/885423) + 个股(000001 平安银行)：3001 同时承载板块与个股行情订阅
        self._stock_ids = stock_ids or ["801044", "885423", "000001"]
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subs_lock = threading.Lock()
        self._subs: List[queue.Queue] = []
        self._history = deque(maxlen=history)
        self._status = "idle"
        self._last_error = ""
        self._session_no = 0
        self._stats = {"sessions": 0, "pushes": 0, "errors": 0, "started_at": 0.0}

    # ---- 公共 API ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._stats["started_at"] = time.time()
        self._thread = threading.Thread(target=self._run_loop, name="kpl-collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        return {
            "status": self._status,
            "last_error": self._last_error,
            "sessions": self._stats["sessions"],
            "pushes": self._stats["pushes"],
            "errors": self._stats["errors"],
            "uptime_s": round(time.time() - self._stats["started_at"], 1)
            if self._stats["started_at"]
            else 0,
            "running": self.is_running(),
        }

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._subs_lock:
            self._subs.append(q)
            # 新订阅者先回放最近历史（fail-visible：不丢已发生的事件）
            for ev in list(self._history):
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)

    # ---- 内部 ----

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, dict):
            return {k: KplCollectorService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [KplCollectorService._json_safe(v) for v in value]
        return value

    def _emit(self, event: KplEvent) -> None:
        event = KplCollectorService._json_safe(dict(event))
        self._history.append(event)
        with self._subs_lock:
            dead = []
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                # 溢出移除前先尽力塞一条降级事件，避免前端连接看似健康但数据已停
                try:
                    q.put_nowait({"type": "error", "ts": time.time(),
                                  "msg": "subscriber queue overflow, re-subscribe required"})
                except queue.Full:
                    pass
                self._subs.remove(q)

    def _err(self, msg: str, **extra: Any) -> None:
        self._last_error = msg
        self._stats["errors"] += 1
        self._emit(KplEvent(type="error", ts=time.time(), msg=msg, **extra))

    def _tls_connect(self) -> Optional[ssl.SSLSocket]:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            ctx.set_ciphers("ECDHE-RSA-AES128-GCM-SHA256")
        except Exception:
            pass
        # 客户端证书：服务器要求 mTLS（缺证书 → sslv3 alert handshake failure）
        cert = Path(os.environ.get(
            "KPL_CLIENT_CERT", r"D:/dragon-board/.tmp_review/client_cert.pem"))
        key = Path(os.environ.get(
            "KPL_CLIENT_KEY", r"D:/dragon-board/.tmp_review/client_key.pem"))
        if cert.exists() and key.exists():
            ctx.load_cert_chain(str(cert), str(key))
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((self._host, self._port), timeout=15)
        return ctx.wrap_socket(raw, server_hostname=TLS_SNI)

    def _read_frame(self, sock: ssl.SSLSocket) -> Optional[Dict[str, Any]]:
        h = b""
        while len(h) < 5:
            c = sock.recv(5 - len(h))
            if not c:
                return None
            h += c
        pkg = h[0]
        ln = int.from_bytes(h[1:5], "big")
        if ln > 8 * 1024 * 1024:
            raise proto.FrameDecodeError(f"frame too large: {ln}B")
        body = b""
        while len(body) < ln:
            c = sock.recv(min(65536, ln - len(body)))
            if not c:
                return None
            body += c
        # 注意: parse_incoming 期望完整帧（pkg+len+body），h 已含 pkg+len，不能只拼 pkg
        frame = h + body
        if os.environ.get("KPL_DEBUG"):
            with open(os.environ["KPL_DEBUG"], "a") as f:
                f.write(f"S {int(time.time())} {frame.hex()}\n")
        return proto.parse_incoming(frame)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self._session_no += 1
            self._stats["sessions"] += 1
            try:
                self._session()
            except (ssl.SSLError, OSError, socket.timeout) as exc:
                self._err(f"session#{self._session_no} network: {type(exc).__name__}: {exc}")
            except SignSvcError as exc:
                self._err(f"session#{self._session_no} signsvc: {exc}")
                # signsvc 故障重试间隔拉长
                self._stop.wait(5.0)
                continue
            except Exception as exc:  # 未知异常也必须 fail-visible
                self._err(f"session#{self._session_no} unexpected: {type(exc).__name__}: {exc}")
            if self._stop.is_set():
                break
            self._status = "reconnecting"
            self._stop.wait(2.0)
        self._status = "stopped"

    def _dbg(self, direction: str, data: bytes) -> None:
        if not os.environ.get("KPL_DEBUG"):
            return
        with open(os.environ["KPL_DEBUG"], "a") as f:
            f.write(f"{direction} {int(time.time())} {data.hex()}\n")

    def _session(self) -> None:
        self._status = "connecting"
        seq = [0]  # 会话内递增 seq（重复 seq 会被服务器 110/2000 拒绝并断连）

        def next_seq() -> int:
            seq[0] += 1
            return seq[0]

        sock = self._tls_connect()
        try:
            sock.settimeout(2)
            # 1) 260 challenge
            deadline = time.time() + 15
            challenge = server_time = None
            while time.time() < deadline:
                fr = self._read_frame(sock)
                if fr is None:
                    raise proto.FrameDecodeError("closed before 260")
                if fr["cmd"] == proto.CMD_CHALLENGE:
                    server_time, challenge, _ = proto.parse_challenge_260(fr["payload"])
                    break
            if not challenge:
                self._err("no 260 challenge in 15s")
                return
            self._status = "authenticating"
            # 2) WBE 签名 → 610 AuthReq
            sig_hex = self._codec.wbe(
                challenge, self._device_id, str(self._conn_type), str(server_time)
            )
            if not sig_hex:
                self._err("WBE returned empty signature")
                return
            auth_pb = proto.build_auth_req_pb(
                device_id=self._device_id,
                version_name=self._version_name,
                channel_id=self._channel_id,
                signature_hex=sig_hex,
                user_id=self._user_id,
                token=self._token,
                conn_type=self._conn_type,
                cur_time=int(server_time),
                api_version=self._api_version,
            )
            enc_body = self._codec.enc(auth_pb)
            if not enc_body:
                self._err("ENC failed for AuthReq")
                return
            auth_frame = proto.build_frame(proto.CMD_AUTH, next_seq(), enc_body, d=2, encrypted=True)
            # 拟人延迟：服务器对 <1s 完成认证+订阅的连接做机器人检测并 ~6s 即断连
            # （实测 collector adb 链路 5-8s 完成 → 75-160s 会话；服务 <1s → 6s 会话）
            if self._human_delay:
                time.sleep(1.2)
            self._dbg("C", auth_frame)
            sock.sendall(auth_frame)
            # 3) 610 ack（加密 AuthResp）
            deadline = time.time() + 15
            auth_ok = False
            while time.time() < deadline:
                fr = self._read_frame(sock)
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 610 ack")
                if fr["fmt"] == "echo" and fr["cmd"] == proto.CMD_AUTH:
                    dec = self._codec.dec(fr["payload"].hex())
                    if not dec:
                        # fail-visible：认证本身成功，但解密失败必须结构化上报，不得仍作完整成功
                        self._err("610 ack decode failed (DEC returned empty)")
                        self._emit(KplEvent(type="auth", ts=time.time(), ok=True,
                                            decode_degraded=True, server_ip="",
                                            session=self._session_no))
                    else:
                        info = proto.parse_auth_resp(dec)
                        self._emit(
                            KplEvent(type="auth", ts=time.time(), ok=True,
                                     server_ip=info.get("server_ip", ""),
                                     session=self._session_no)
                        )
                    auth_ok = True
                    break
                if fr["cmd"] == proto.CMD_ERROR:
                    err = proto.parse_err_resp(fr["payload"])
                    self._err(f"auth rejected: {err}")
                    self._emit(KplEvent(type="auth", ts=time.time(), ok=False, error=err))
                    return
            if not auth_ok:
                self._err("no 610 ack in 15s")
                return
            # 4) 602 登录态
            ls_pb = proto.build_login_state_pb(self._user_id, self._token, self._device_id)
            enc_ls = self._codec.enc(ls_pb)
            ls_frame = proto.build_frame(proto.CMD_LOGIN_STATE, next_seq(), enc_ls or ls_pb, d=0,
                                         encrypted=bool(enc_ls))
            if self._human_delay:
                time.sleep(0.6)
            self._dbg("C", ls_frame)
            sock.sendall(ls_frame)
            self._status = "subscribing"
            # 5) 2301 版本订阅（pkg 0x40 + ext 路由头 02 08fd），与 collector 一致：
            #    发 2301 → 读 ack → 发 2303+2304 → 读 ack → 发 3001 → 读 ack（不乱序）
            vr = proto.build_version_req_pb(0)
            enc_vr = self._codec.enc(vr)
            ext = bytes([0x02]) + struct.pack(">H", proto.CMD_PLATE_LIST)
            vr_frame = proto.build_frame(proto.CMD_PLATE_LIST, next_seq(), enc_vr or vr, d=1,
                                         encrypted=bool(enc_vr), pkg=proto.PKG_ROUTE, ext=ext)
            if self._human_delay:
                time.sleep(0.8)
            self._dbg("C", vr_frame)
            sock.sendall(vr_frame)
            deadline = time.time() + 10
            while time.time() < deadline:
                fr = self._read_frame(sock)
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 2301 ack")
                if fr["fmt"] == "echo" and fr["cmd"] == proto.CMD_PLATE_LIST:
                    break
            # 5b) 2303+2304 订阅（app 的 AttachAppTimerTask 三件套）
            for sub_cmd, ext_bytes in (
                (proto.CMD_STOCK_LIST, bytes([0x02]) + struct.pack(">H", proto.CMD_STOCK_LIST)),
                (proto.CMD_HK_LIST, bytes([0x02]) + struct.pack(">H", proto.CMD_HK_LIST)),
            ):
                enc_sub = self._codec.enc(vr)
                sub_frame = proto.build_frame(sub_cmd, next_seq(), enc_sub or vr, d=0,
                                              encrypted=bool(enc_sub), pkg=proto.PKG_ROUTE,
                                              ext=ext_bytes)
                self._dbg("C", sub_frame)
                sock.sendall(sub_frame)
            deadline = time.time() + 10
            acks_needed = 2
            while acks_needed > 0 and time.time() < deadline:
                fr = self._read_frame(sock)
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 2303/2304 ack")
                if fr["fmt"] == "echo" and fr["cmd"] in (proto.CMD_STOCK_LIST, proto.CMD_HK_LIST):
                    acks_needed -= 1
            # 6) 3001 板块+个股行情订阅
            gq = proto.build_group_quotas_req_pb(self._stock_ids)
            enc_gq = self._codec.enc(gq)
            ext3 = bytes([0x02]) + struct.pack(">H", proto.CMD_GROUP_QUOTAS)
            gq_frame = proto.build_frame(proto.CMD_GROUP_QUOTAS, next_seq(), enc_gq or gq, d=0,
                                         encrypted=bool(enc_gq), pkg=proto.PKG_ROUTE, ext=ext3)
            if self._human_delay:
                time.sleep(0.6)
            self._dbg("C", gq_frame)
            sock.sendall(gq_frame)
            deadline = time.time() + 10
            while time.time() < deadline:
                fr = self._read_frame(sock)
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 3001 ack")
                if fr["fmt"] == "echo" and fr["cmd"] == proto.CMD_GROUP_QUOTAS:
                    break
            # 6b) 3006 个股行情订阅：HQStockIdListReq{f1 repeated stockIds}（个股实时价）
            hq = b"".join(proto.pb_bytes(1, sid.encode()) for sid in self._stock_ids)
            enc_hq = self._codec.enc(hq)
            ext6 = bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_ID_LIST)
            hq_frame = proto.build_frame(proto.CMD_HQ_ID_LIST, next_seq(), enc_hq or hq, d=0,
                                         encrypted=bool(enc_hq), pkg=proto.PKG_ROUTE, ext=ext6)
            self._dbg("C", hq_frame)
            sock.sendall(hq_frame)
            self._status = "streaming"
            self._emit(KplEvent(type="status", ts=time.time(), status="streaming",
                                session=self._session_no))
            # 7) 收流 + 保活（3001 轮询 5s；服务器 TTL 由重连机制兜底）
            last_keepalive = time.time()
            auth_frame_cache = [None]
            hb_flip = [0]
            while not self._stop.is_set():
                try:
                    fr = self._read_frame(sock)
                except socket.timeout:
                    fr = "timeout"  # 哨兵：本轮无数据，不是断连；保活块仍然执行
                now = time.time()
                if now - last_keepalive > 1:
                    # 保活交替: 610 AuthReq 原样重发（签名绑定初始 challenge/curTime，
                    # 重建帧会签名/时间不匹配 → 服务器断连）/ 3001 轮询
                    hb_flip[0] += 1
                    if hb_flip[0] % 2 == 1:
                        if hb_flip[0] == 1:
                            auth2 = proto.build_auth_req_pb(
                                device_id=self._device_id,
                                version_name=self._version_name,
                                channel_id=self._channel_id,
                                signature_hex=sig_hex,
                                user_id=self._user_id,
                                token=self._token,
                                conn_type=self._conn_type,
                                cur_time=int(server_time),
                                api_version=self._api_version,
                            )
                            enc2 = self._codec.enc(auth2)
                            if enc2:
                                auth_frame_cache[0] = proto.build_frame(
                                    proto.CMD_AUTH, next_seq(), enc2, d=2,
                                    encrypted=True, pkg=proto.PKG_AUTH)
                        if auth_frame_cache[0] is not None:
                            # seq 递增但 AuthReq 内容原样（与 kpl_collector 行为一致）
                            frame_bytes = auth_frame_cache[0]
                            frame_bytes = frame_bytes[:5] + next_seq().to_bytes(2, "big") + frame_bytes[7:]
                            self._dbg("C", frame_bytes)
                            sock.sendall(frame_bytes)
                    else:
                        gq2 = proto.build_group_quotas_req_pb(self._stock_ids)
                        enc2 = self._codec.enc(gq2)
                        if enc2:
                            ka_frame = proto.build_frame(proto.CMD_GROUP_QUOTAS, next_seq(), enc2, d=0,
                                                         encrypted=True, pkg=proto.PKG_ROUTE, ext=ext3)
                            self._dbg("C", ka_frame)
                            sock.sendall(ka_frame)
                    last_keepalive = now
                if fr == "timeout":
                    continue
                if fr is None:
                    # 服务器断开 → 返回触发重连
                    self._err(f"session#{self._session_no} closed by server")
                    return
                self._dispatch(fr)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _dispatch(self, fr: Dict[str, Any]) -> None:
        cmd = fr["cmd"]
        payload = fr.get("payload", b"")
        if cmd == proto.CMD_ERROR:
            err = proto.parse_err_resp(payload)
            self._err(f"server error: {err}")
            self._emit(KplEvent(type="error", ts=time.time(), server=err))
            return
        if cmd == proto.CMD_ANTI_CHEAT:
            # 261 反作弊轮：data[0:32] 原样 + [32:36] 由 EXEC 计算 —— EXEC 依赖白盒，
            # 当前会话未实现 EXEC 注入时 fail-visible 上报
            self._emit(KplEvent(type="anti_cheat", ts=time.time(),
                                note="EXEC round not implemented; monitoring only"))
            return
        if cmd == proto.CMD_HQ_ID_LIST:
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"3006 push decode failed ({len(payload)}B)")
                return
            quotes = proto.parse_index_simple_quotes(dec)
            self._stats["pushes"] += 1
            self._emit(KplEvent(type="stock_quotes", ts=time.time(),
                                source="push" if fr.get("fmt") == "push" else "resp",
                                **quotes))
            return
        if cmd == proto.CMD_GROUP_QUOTAS:
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"3001 push decode failed ({len(payload)}B)")
                return
            quotes = proto.parse_group_quotas(dec)
            self._stats["pushes"] += 1
            self._emit(KplEvent(type="quotes", ts=time.time(),
                                source="push" if fr.get("fmt") == "push" else "poll",
                                **quotes))
            return
        if cmd in (proto.CMD_PLATE_LIST, proto.CMD_STOCK_LIST, proto.CMD_HK_LIST):
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"{cmd} version frame decode failed ({len(payload)}B)")
                return
            info = proto.parse_version_resp(dec)
            self._emit(KplEvent(type="version", ts=time.time(), cmd=cmd, **info))
            return
        # 其他 cmd：fail-visible 记录原始帧（截断）
        self._emit(KplEvent(type="raw", ts=time.time(), cmd=cmd,
                            payload_hex=payload[:64].hex(), payload_len=len(payload)))
