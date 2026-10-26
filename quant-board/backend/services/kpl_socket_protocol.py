# -*- coding: utf-8 -*-
"""KPL（开盘啦）socket 协议纯逻辑层：帧构造 / 帧解析 / 推送帧解码。

协议事实（2026-10-26 实测逆向，见 docs/hotlist-jev/socket-push-handoff-20261026.md §3.9-3.11）：

- 服务器主动帧（pkg=0x20）：[pkg][len 4BE][cmd 2BE][status 1][extlen 2BE][payload]
  - 260 ChallengeAuthNt：payload = pb{1: serverTime, 2: challenge(32 hex ASCII), 3: codeType}
- 客户端帧（pkg=0x30/0x40）：[pkg][len 4BE][seq 2BE][cmd 2BE][flags 1][extlen 2BE][ext][body]
  - pkg = e(N)<<4：e(3)→0x30（行情/鉴权），e(4)→0x40（订阅路由通道）
  - flags = (d << 3) | enc：601/610 d=2→0x11（加密）；602 d=0→0x01；2301 d=1→0x09
  - cmd 勘误：认证帧命令号 = **610**（TYPE_QUANTIZE_MOTIONSTEPS），601 从未被 app 发送
- 服务器应答帧（echo 格式）：[seq 2BE][cmd 2BE][flags 1][extlen 2BE][body]
- 服务器推送帧（pkg=0x60）：[extlen 2BE][ext ascii 路由][cmd 2BE][flags 1][inner extlen 2BE][payload]
- 认证流程：260 → 610(AuthReq{deviceId, platformId=1, versionName, channelId, signature,
  userId, token, connType, curTime, apiVersion, appType}) → 610 ack(加密 AuthResp{serverIP}) →
  602(LoginStateReq{userId, token, deviceId}) → 订阅（2301/2303/2304 版本轮询 + 3001 板块行情）
- 服务器连接 TTL ≈ 60-90s，与心跳频率无关；客户端需断线重连维持数据流（app 的 ReconnectManager 同款）

所有构造/解析均为纯函数；加密/解密通过注入的 codec 回调完成（signsvc ENC/DEC），
本模块不做任何网络 I/O —— pytest 全部走 mock，不触发真实 KPL 连接。
"""
from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

# 命令常量（混淆常量名还原）
CMD_AUTH = 610  # TYPE_QUANTIZE_MOTIONSTEPS；601 是历史误判（app 从未发送 601）
CMD_LOGIN_STATE = 602
CMD_UNSUB = 402
CMD_PLATE_LIST = 2301  # Hq.PlateSearchListResp（版本 + dataUrl）
CMD_STOCK_LIST = 2303  # Hq.StockSearchListNewResp（version + txtUrl）
CMD_HK_LIST = 2304
CMD_GROUP_QUOTAS = 3001  # Hq.GroupStockQuotasResp（板块行情）
CMD_HQ_ID_LIST = 3006  # Hq.HQStockIdListReq（个股行情订阅，f1 repeated stockIds）
CMD_CHALLENGE = 260
CMD_ANTI_CHEAT = 261
CMD_ANTI_CHEAT_ANS = 262
CMD_ERROR = 201  # Base.ErrResp（服务器拒绝/错误）

PKG_SERVER = 0x20
PKG_AUTH = 0x30  # e(3)<<4
PKG_ROUTE = 0x40  # e(4)<<4
PKG_PUSH = 0x60

FLAG_ENC_BIT = 0x01


def flags(d: int, encrypted: bool) -> int:
    """flags = (d << 3) | enc。d 来自 ux0 builder 的 g(N)（优先级）。"""
    return (d << 3) | (FLAG_ENC_BIT if encrypted else 0)


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b7 = value & 0x7F
        value >>= 7
        if value:
            out.append(b7 | 0x80)
        else:
            out.append(b7)
            return bytes(out)


def _tag_varint(field: int, wire_type: int) -> bytes:
    """pb tag 本身是 varint（field>=16 时两字节，如 quotas f100 → a2 06）。"""
    return encode_varint((field << 3) | wire_type)


def pb_bytes(field: int, value: bytes) -> bytes:
    """len-delimited 字段（正确 varint 长度；早期实现 1 字节硬塞导致 1002 的教训）。"""
    return _tag_varint(field, 2) + encode_varint(len(value)) + value


def pb_varint_field(field: int, value: int) -> bytes:
    return _tag_varint(field, 0) + encode_varint(value)


def parse_pb(data: bytes) -> Dict[int, List[Any]]:
    """通用 pb 解析（宽容模式：非法 tag 停止）。字符串按 bytes 返回由调用方解码。

    tag 本身是 varint（field>=16 时两字节，如 quotas f100 → a2 06）。
    """
    out: Dict[int, List[Any]] = {}
    i = 0
    n = len(data)
    while i < n:
        try:
            tag, sh = 0, 0
            while i < n:
                b = data[i]
                i += 1
                tag |= (b & 0x7F) << sh
                sh += 7
                if not (b & 0x80):
                    break
            else:
                break
            f, w = tag >> 3, tag & 7
            if w == 0:
                v, sh = 0, 0
                while i < n:
                    b = data[i]
                    i += 1
                    v |= (b & 0x7F) << sh
                    sh += 7
                    if not (b & 0x80):
                        break
                out.setdefault(f, []).append(v)
            elif w == 2:
                ln, sh = 0, 0
                while i < n:
                    b = data[i]
                    i += 1
                    ln |= (b & 0x7F) << sh
                    sh += 7
                    if not (b & 0x80):
                        break
                out.setdefault(f, []).append(data[i : i + ln])
                i += ln
            elif w == 5:
                i += 4
            elif w == 1:
                i += 8
            else:
                break
        except Exception:
            break
    return out


def pb_first(pb: Dict[int, List[Any]], field: int, default: Any = None) -> Any:
    vals = pb.get(field)
    return vals[0] if vals else default


def build_frame(
    cmd: int,
    seq: int,
    body: bytes,
    *,
    d: int = 2,
    encrypted: bool = True,
    pkg: int = PKG_AUTH,
    ext: bytes = b"",
) -> bytes:
    """客户端帧。pkg=0x30 (e3) 鉴权/行情；pkg=0x40 (e4) 订阅路由（需 ext 路由头）。"""
    fl = flags(d, encrypted)
    inner = struct.pack(">H", seq) + struct.pack(">H", cmd) + bytes([fl]) + struct.pack(
        ">H", len(ext)
    ) + ext + body
    return bytes([pkg]) + struct.pack(">I", len(inner)) + inner


def build_auth_req_pb(
    *,
    device_id: str,
    version_name: str,
    channel_id: int,
    signature_hex: str,
    user_id: str,
    token: str,
    conn_type: int,
    cur_time: int,
    api_version: str,
) -> bytes:
    """User.AuthReq pb。signature = hex(whiteBoxEncrypt(challenge, deviceId, connType, curTime))。"""
    out = b""
    out += pb_bytes(1, device_id.encode())
    out += pb_varint_field(2, 1)  # platformId
    out += pb_bytes(3, version_name.encode())
    out += pb_varint_field(4, channel_id)
    out += pb_bytes(5, signature_hex.encode())
    out += pb_bytes(6, str(user_id).encode())
    out += pb_bytes(7, token.encode())
    out += pb_varint_field(8, conn_type)
    out += pb_bytes(10, api_version.encode())
    return out  # appType=0 默认省略


def build_login_state_pb(user_id: str, token: str, device_id: str) -> bytes:
    return pb_bytes(1, str(user_id).encode()) + pb_bytes(2, token.encode()) + pb_bytes(
        3, device_id.encode()
    )


def build_version_req_pb(version: int) -> bytes:
    return pb_varint_field(1, version)


def build_group_quotas_req_pb(stock_ids: List[str], *, quota_type: int = 0, sort_type: int = 2,
                              start: int = 0, count: Optional[int] = None) -> bytes:
    """GroupStockQuotasReq：f1 quotaType, f2 sortType, f3 start, f4 count, f10 stockIds。
    count 与 stockIds 数量一致（实测 2000 错误与 count>len 相关）。"""
    if count is None:
        count = len(stock_ids)
    out = pb_varint_field(1, quota_type) + pb_varint_field(2, sort_type) + pb_varint_field(3, start)
    out += pb_varint_field(4, count)
    for sid in stock_ids:
        out += pb_bytes(10, sid.encode())
    return out


class FrameDecodeError(ValueError):
    """帧结构无法解析（fail-visible：调用方必须上报而非静默丢弃）。"""


def parse_server_frame(body: bytes) -> Dict[str, Any]:
    """服务器主动帧（pkg=0x20 已剥离）：[cmd 2BE][status 1][extlen 2BE][payload]。"""
    if len(body) < 5:
        raise FrameDecodeError(f"server frame too short: {len(body)}B")
    cmd = struct.unpack(">H", body[0:2])[0]
    status = body[2]
    extlen = struct.unpack(">H", body[3:5])[0]
    payload = body[5 + extlen :]
    return {"fmt": "srv", "cmd": cmd, "status": status, "extlen": extlen, "payload": payload}


def parse_echo_frame(body: bytes) -> Dict[str, Any]:
    """服务器应答帧（echo）：[seq 2BE][cmd 2BE][flags 1][extlen 2BE][payload]。"""
    if len(body) < 7:
        raise FrameDecodeError(f"echo frame too short: {len(body)}B")
    seq = struct.unpack(">H", body[0:2])[0]
    cmd = struct.unpack(">H", body[2:4])[0]
    fl = body[4]
    extlen = struct.unpack(">H", body[5:7])[0]
    payload = body[7 + extlen :]
    return {"fmt": "echo", "cmd": cmd, "seq": seq, "flags": fl, "payload": payload}


def parse_push_frame(body: bytes) -> Dict[str, Any]:
    """服务器推送帧（pkg=0x60 已剥离）：[extlen 2BE][ext][cmd 2BE][flags 1][inner_extlen 2BE][payload]。"""
    if len(body) < 2:
        raise FrameDecodeError(f"push frame too short: {len(body)}B")
    extlen = struct.unpack(">H", body[0:2])[0]
    ext = body[2 : 2 + extlen]
    base = 2 + extlen
    if len(body) < base + 5:
        raise FrameDecodeError(f"push frame header short: {len(body)}B ext={extlen}")
    cmd = struct.unpack(">H", body[base : base + 2])[0]
    fl = body[base + 2]
    inner_extlen = struct.unpack(">H", body[base + 3 : base + 5])[0]
    payload = body[base + 5 + inner_extlen :]
    return {
        "fmt": "push",
        "cmd": cmd,
        "flags": fl,
        "ext": ext.decode("utf-8", "replace"),
        "payload": payload,
    }


def parse_incoming(payload: bytes) -> Dict[str, Any]:
    """按 pkg 分派的三合一入口。返回 dict 含 fmt/cmd/payload 等。"""
    if not payload:
        raise FrameDecodeError("empty frame")
    pkg = payload[0]
    ln = struct.unpack(">I", payload[1:5])[0]
    body = payload[5 : 5 + ln]
    if pkg == PKG_SERVER:
        return parse_server_frame(body)
    if pkg == PKG_PUSH:
        info = parse_push_frame(body)
        info["kind"] = 6
        return info
    if pkg in (PKG_AUTH, PKG_ROUTE):
        # 客户端帧不会有服务器发来；容忍服务器 echo 客户端格式
        info = parse_echo_frame(body)
        info["kind"] = pkg >> 4
        return info
    raise FrameDecodeError(f"unknown pkg {pkg:#x}")


def parse_challenge_260(payload: bytes) -> Tuple[int, str, int]:
    """ChallengeAuthNt pb：f1 serverTime, f2 challenge(32 hex ASCII), f3 codeType。"""
    pb = parse_pb(payload)
    server_time = pb_first(pb, 1, 0)
    challenge = pb_first(pb, 2, b"")
    if isinstance(challenge, bytes):
        challenge = challenge.decode("ascii", "replace")
    code_type = pb_first(pb, 3, 1)
    return int(server_time), challenge, int(code_type)


def parse_auth_resp(payload: bytes) -> Dict[str, Any]:
    """AuthResp pb：f1 serverIP（引导连接的任务完成后据此进入主会话）。"""
    pb = parse_pb(payload)
    ip = pb_first(pb, 1, b"")
    if isinstance(ip, bytes):
        ip = ip.decode("utf-8", "replace")
    return {"server_ip": ip}


def parse_group_quotas(payload: bytes) -> Dict[str, Any]:
    """GroupStockQuotasResp → 结构化行情（fail-visible：保留 raw 供降级展示）。

    Item 字段（Hq.proto）：f1 stockId, f2 name, f100(0x64) quotas[]。
    quotas 数组元素为紧凑字符串编码的价格/涨跌/成交额序列（顺序按 app 展示列），
    这里原样返回列表，字段级语义在展示层标注为推断。
    """
    pb = parse_pb(payload)
    items: List[Dict[str, Any]] = []
    for raw in pb.get(10, []):
        sub = parse_pb(raw)
        item: Dict[str, Any] = {
            "stock_id": (pb_first(sub, 1, b"") or b"").decode("utf-8", "replace"),
            "name": (pb_first(sub, 2, b"") or b"").decode("utf-8", "replace"),
            "quotas": [
                q.decode("utf-8", "replace") if isinstance(q, bytes) else str(q)
                for q in sub.get(100, [])
            ],
        }
        items.append(item)
    return {
        "timestamp": pb_first(pb, 4, 0),
        "indexes": list(pb.get(9, [])),
        "items": items,
        "raw_len": len(payload),
    }


def parse_version_resp(payload: bytes) -> Dict[str, Any]:
    """2301/2303/2304 版本应答（PlateSearchListResp 等）：f2 version/f4 dataUrl 等。"""
    pb = parse_pb(payload)
    out: Dict[str, Any] = {
        "resp_type": pb_first(pb, 1, 0),
        "version": pb_first(pb, 2, 0),
    }
    for f in (4,):
        v = pb_first(pb, f)
        if isinstance(v, bytes):
            out.setdefault("urls", []).append(v.decode("utf-8", "replace"))
    return out


def parse_err_resp(payload: bytes) -> Dict[str, Any]:
    pb = parse_pb(payload)
    code = pb_first(pb, 1, 0)
    msg = pb_first(pb, 2, b"")
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", "replace")
    return {"code": code, "msg": msg}

def _signed64(v: Any) -> Any:
    """pb 负 int 以 10 字节补码 varint 编码，parse 出来是 uint64 回绕值，还原为有符号。"""
    if isinstance(v, int) and v >= (1 << 63):
        return v - (1 << 64)
    return v


def parse_index_simple_quotes(payload: bytes) -> Dict[str, Any]:
    """3006 IndexSimpleQuotasResp → 个股/指数实时行情（id/name/price/incPrice/incRate）。"""
    pb = parse_pb(payload)
    items: List[Dict[str, Any]] = []
    for raw in pb.get(1, []):
        sub = parse_pb(raw)
        item: Dict[str, Any] = {
            "stock_id": (pb_first(sub, 1, b"") or b"").decode("utf-8", "replace"),
            "name": (pb_first(sub, 2, b"") or b"").decode("utf-8", "replace"),
        }
        price = _signed64(pb_first(sub, 3))
        inc_price = _signed64(pb_first(sub, 4))
        inc_rate = _signed64(pb_first(sub, 5))
        if isinstance(price, bytes):
            price = price.decode("utf-8", "replace")
        if isinstance(inc_price, bytes):
            inc_price = inc_price.decode("utf-8", "replace")
        if isinstance(inc_rate, bytes):
            inc_rate = inc_rate.decode("utf-8", "replace")
        item["price"] = price
        item["inc_price"] = inc_price
        item["inc_rate"] = inc_rate
        items.append(item)
    return {"items": items, "raw_len": len(payload)}
