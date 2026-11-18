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

import math
import struct
from typing import Any, Dict, List, Optional, Tuple

# 命令常量（混淆常量名还原）
CMD_AUTH = 610  # TYPE_QUANTIZE_MOTIONSTEPS；601 是历史误判（app 从未发送 601）
CMD_LOGIN_STATE = 602
CMD_UNSUB = 402
CMD_SUB_BATCH = 211  # Base.SubReqs 批量订阅信封（RE 收口 2026-11-17：当前 App 版本
                     # 无发送路径，仅 proto+qn0.o ack 展开在；请求侧语义待探针钉死，
                     # 见 docs/kpl-socket/sub-registry-refactor-plan.md §1.3）
CMD_PLATE_LIST = 2301  # Hq.PlateSearchListResp（版本 + dataUrl）
CMD_STOCK_LIST = 2303  # Hq.StockSearchListNewResp（version + txtUrl）
CMD_HK_LIST = 2304
CMD_GROUP_QUOTAS = 3001  # Hq.GroupStockQuotasResp（板块行情）
CMD_HQ_ID_LIST = 3006  # Hq.HQStockIdListReq（个股行情订阅，f1 repeated stockIds）
CMD_HQ_REASONS = 2203  # Hq.HQReasonsResp（个股涨停原因实时推送，请求 Hq.HQReq{f1 stockId}）
CMD_STOCK_RELATED_THEME = 2013  # ServiceHqStock.StockRelatedThemeResp（个股题材库热度推送，
                                # 请求同 Hq.HQReq{f1 stockId}；2026-11-08 逆向）
CMD_STOCK_RELATED_PLATE = 2010  # Hq.StockRelatedPlateListResp（所属板块实时，请求同 HQReq）
CMD_STOCK_ZT_BIG_ORDER = 2014   # ServiceHqStock.StockZTBigOrderDetailResp（封板大单明细）
CMD_ABNORMAL_PRICE = 2030       # ServiceHqStock.AbnormalPriceResp（异动提醒）

# ── 2014 封板大单实弹值裁决（2026-11-11 收盘日档 16 股 2936 items 全样本被动校准，
#    证据链与复验路径见 docs/kpl-socket/detail-scaling-verification.md）──────────
# - time = HHMM（时×100+分）：0 条越界、0 条落午休空洞（1131-1259）、全 items 时序单调；
#   首条时间与池 zt_time 封板时刻对齐（一字板 09:25 封 → 首条 09:30）。
# - zt_tur/tur/buy_tur/sell_tur = 元×1：16/16 股尾条 zt_tur 与池 zt_tur（App 渲染封单额）
#   精确吻合（实测全部 1.00000）；buy/sell 全 items 单调（累计语义）且 buy−sell 与池
#   main_net（元原样，lhb-scaling-verification 同源）量级一致（×100/×10000 越界排除）。
# - rate = tur/ztTur×100：2905/2905 items 帧内自洽（含 298629.53% 极端样本精确吻合），
#   raw 已是百分数，rate_pct 原样不乘 100。
BDO_TUR_DIVISOR = 1         # 2014 金额族（tur/buyTur/sellTur/ztTur）raw → 元除数
BDO_TIME_IS_HHMM = True     # 2014 time 编码 = HHMM（时×100+分）
BDO_RATE_IS_PERCENT = True  # 2014 rate 已是百分数（tur/ztTur×100）

# 2030 异动提醒 price/nextDayPrice/nextDayZf 缩放与 zf 口径：**未钉死**（2026-11-11 阴性——
# 当日事件推送 16/16 样本三字段全缺位，date 语义=异动日；复验路径见
# docs/kpl-socket/detail-scaling-verification.md §二）。证据不足解析器不动，原始值透出。
ABN_SCALING_VERIFIED = False

# 2010 所属板块 plateIncRate/stockIncRate = **百分数原样**（2026-11-11 被动交叉校准裁决，
# 零新增开火；证据链见 docs/kpl-socket/detail-scaling-verification.md §四）：
# 35/35 封板成分股 stock_inc_rate 与 limit_rules 板别涨停幅吻合（最大差 0.18=低价股
# tick 舍入）；266 个 plate_inc_rate 落 [-0.19, 4.84]（中位 1.37），比率形态 261/266
# 超成分股 30% 涨幅上限，排除。未来证据推翻时置 False，叙事百分比段集体缺席
# （同 2030 kill-switch 模式）。
RPLATE_INC_IS_PERCENT = True
CMD_BF_REASON = 2202            # Hq.BFReasonResp（爆发原因推送，请求同 HQReq）
CMD_STOCK_MX_SUB = 2006   # Hq.StockMXResp 首拉+订阅（请求 Hq.HQItemReq{f1 stockId, f2 count}，App 固定 count=25）
CMD_STOCK_MX_PUSH = 2007  # Hq.StockMXResp 增量推送（不在 @y51 订阅面内，服务端跟在 2006 订阅后推）
CMD_TY_DAN_LABEL = 2009   # Hq.TYDanLabelResp 大单标签推送（分时图大单标记，请求 Hq.HQListReq{stockId,currNum=已收数}）
CMD_CHALLENGE = 260
CMD_ANTI_CHEAT = 261
CMD_ANTI_CHEAT_ANS = 262
CMD_ERROR = 201  # Base.ErrResp（服务器拒绝/错误）
CMD_ERROR_NT = 110  # 服务器错误通知通道（2026-11-17 211 探针实弹：payload 同 ErrResp
                    # {code,msg}，GCM 加密；批量订阅被拒项逐项下发 2000，非致命不断连）
CMD_RESUB_NT = 220  # Base.ResubNt（服务端订阅注册表失效→客户端重发订阅；App qn0.j）

PKG_SERVER = 0x20
PKG_AUTH = 0x30  # e(3)<<4
PKG_ROUTE = 0x40  # e(4)<<4
PKG_UNSUB = 0x50  # e(5)<<4 退订通道（App SocketRepository.n：cmd 402 + UnsubIdReq）
PKG_PUSH = 0x60
PKG_HEARTBEAT = 0x10  # 服务端心跳（kind1，App 只读延迟统计，无需应答）

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
                # fixed32（proto float，如 2013 题材热度 number）→ 捕获 little-endian float；
                # 此前一律跳过（无消费方），新增键不影响既有 pb_first 读点
                out.setdefault(f, []).append(struct.unpack("<f", data[i : i + 4])[0])
                i += 4
            elif w == 1:
                i += 8
            else:
                break
        except Exception:
            break
    return out


def decode_packed_varints(raw: Any) -> List[int]:
    """packed repeated varint 字段 → int 列表（f20/f40 indexes 等）。

    2026-10-29 开火实测：2112/3004 的 indexes 服务器按 packed varint 下发，
    parse_pb 把 wire-type-2 的值收成 bytes——不解码就原样进快照导致读口不可
    JSON 序列化（fail-visible 修复）。int 输入直接包 list，bytes 按 varint 流解码。
    """
    if isinstance(raw, (bytes, bytearray)):
        out: List[int] = []
        i = 0
        while i < len(raw):
            shift = 0
            val = 0
            while i < len(raw):   # 截断防护：continuation bit 未闭合时不越界（fail-visible）
                b = raw[i]
                i += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            out.append(val)
        return out
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, list):
        flat: List[int] = []
        for x in raw:
            flat.extend(decode_packed_varints(x))
        return flat
    return []


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
    """服务器应答帧（echo）：[seq 2BE][cmd 2BE][flags 1][extlen 2BE][ext][payload]。

    ext 原始字节透出（2026-11-17 注册表化 P0：订阅 ack 的 attr2=subId/attr3=topic
    是注册表权威 key，App qn0.o 同款；此前 ext 被丢弃）。"""
    if len(body) < 7:
        raise FrameDecodeError(f"echo frame too short: {len(body)}B")
    seq = struct.unpack(">H", body[0:2])[0]
    cmd = struct.unpack(">H", body[2:4])[0]
    fl = body[4]
    extlen = struct.unpack(">H", body[5:7])[0]
    ext = body[7 : 7 + extlen]
    payload = body[7 + extlen :]
    return {"fmt": "echo", "cmd": cmd, "seq": seq, "flags": fl, "ext": ext,
            "payload": payload}


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
        "ext_raw": ext,   # 注册表 topic 匹配用原始字节（utf-8 replace 有损，2026-11-17）
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
    if pkg == PKG_HEARTBEAT:
        # kind1 服务端心跳：App SocketReaderThread 只统计延迟（len≠0 记 err heart
        # len），无需应答；payload 原样透出供观测
        return {"fmt": "heartbeat", "kind": 1, "payload": body}
    if pkg == PKG_PUSH:
        info = parse_push_frame(body)
        info["kind"] = 6
        return info
    if pkg in (PKG_AUTH, PKG_ROUTE, PKG_UNSUB):
        # 客户端帧不会有服务器发来；容忍服务器 echo 客户端格式。
        # pkg 0x50 = 退订 ack（kind5，App qn0.q 按 UnsubIdReq.subIds 清注册表）
        info = parse_echo_frame(body)
        info["kind"] = pkg >> 4
        if pkg == PKG_UNSUB:
            info["fmt"] = "unsub_ack"
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
    """2301/2303/2304 版本应答（PlateSearchListResp 等）：f2 version/f4 dataUrl 等。

    2026-10-27 实测：板块清单快照 url 在 **f7**（如
    https://appimgcdn.kaipanla.com/plate/146_<version>.data，f4 为历史误记/其他应答形态）。
    """
    pb = parse_pb(payload)
    out: Dict[str, Any] = {
        "resp_type": pb_first(pb, 1, 0),
        "version": pb_first(pb, 2, 0),
    }
    for f in (4, 7):
        v = pb_first(pb, f)
        if isinstance(v, bytes):
            out.setdefault("urls", []).append(v.decode("utf-8", "replace"))
    return out


def parse_plate_snapshot(data: bytes) -> Dict[str, Dict[str, str]]:
    """2301 CDN 快照（plate/146_<version>.data）→ {板块id: {name/parent/flag/py}}。

    结构（2026-10-27 实测）：外层 pb{f1: 类型, f2: version, f6: repeated 板块项}；
    板块项 pb{f1: id, f2: 名称, f3: 拼音码, f4: 类别标志, f5: 短串(部分条目), f6: 父板块 id
    （"0"=顶级，如 803040 数据采集→801159 机器人概念；全市场 1572 条，543 条有父级）}。
    """
    pb = parse_pb(data)
    out: Dict[str, Dict[str, str]] = {}
    for entry in pb.get(6, []):
        sub = parse_pb(entry)

        def s(k: int) -> str:
            v = sub.get(k)
            if not v:
                return ""
            val = v[0]
            return val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)

        pid = s(1)
        if pid:
            out[pid] = {"name": s(2), "parent": s(6), "flag": s(4), "py": s(3)}
    return out


# ── 订阅注册表化协议层（2026-11-17 P0，RE 合同见 sub-registry-refactor-plan.md §1）──

def build_sub_reqs_pb(items: List[Dict[str, Any]]) -> bytes:
    """Base.SubReqs{reqs=1 repeated Item} 构造（cmd 211 批量订阅信封）。

    Item{seqId=1 u32, cmd=2 u32, version=3 u32, codec=4 u32, subId=5 u32, data=20 bytes}
    （Base.java 描述符逐字）。六字段显式写入（含 0 值，proto2/3 解析器均兼容）；
    data=f20 → tag varint 两字节 a2 01。请求侧 data=内层 req pb（编码由 codec
    字段指示，语义待探针 U2 钉死）；ack 侧 data=首帧 resp 快照（qn0.o 用 x() 解析）。"""
    out = b""
    for it in items:
        body = b""
        body += pb_varint_field(1, int(it.get("seqId", 0)))
        body += pb_varint_field(2, int(it.get("cmd", 0)))
        body += pb_varint_field(3, int(it.get("version", 0)))
        body += pb_varint_field(4, int(it.get("codec", 0)))
        body += pb_varint_field(5, int(it.get("subId", 0)))
        body += pb_bytes(20, bytes(it.get("data") or b""))
        out += pb_bytes(1, body)
    return out


def parse_sub_reqs_pb(payload: bytes) -> List[Dict[str, Any]]:
    """SubReqs 解析（ack 回声/请求回读共用）。宽容模式：非法项跳过不抛
    （fail-visible 由调用方计数）；缺位字段补 0/空 bytes。"""
    pb = parse_pb(payload)
    out: List[Dict[str, Any]] = []
    for raw in pb.get(1, []):
        if not isinstance(raw, (bytes, bytearray)):
            continue
        ip = parse_pb(bytes(raw))
        out.append({
            "seqId": int(pb_first(ip, 1, 0) or 0),
            "cmd": int(pb_first(ip, 2, 0) or 0),
            "version": int(pb_first(ip, 3, 0) or 0),
            "codec": int(pb_first(ip, 4, 0) or 0),
            "subId": int(pb_first(ip, 5, 0) or 0),
            "data": bytes(pb_first(ip, 20, b"") or b""),
        })
    return out


def build_unsub_id_req_pb(sub_ids: List[int]) -> bytes:
    """Base.UnsubIdReq{subIds=1 repeated u32}（cmd 402 / pkg 0x50 退订）。
    非 packed 逐项 tag（proto2 基线；proto3 解析器亦兼容非 packed）。"""
    return b"".join(pb_varint_field(1, int(s)) for s in sub_ids)


def parse_unsub_id_req_pb(payload: bytes) -> List[int]:
    """UnsubIdReq 解析（退订 ack 回声）：兼容 packed/非 packed f1。"""
    pb = parse_pb(payload)
    out: List[int] = []
    for v in pb.get(1, []):
        out.extend(decode_packed_varints(v))
    return out


def encode_ext_attrs(attrs: Dict[int, Any]) -> bytes:
    """帧 ext 属性段构造（App ux0.n/x6 线格式，SocketReaderThread ext 解析同款）：
    key1=Long(8B BE)、key2=Short(2B BE)、key3=String(len2+bytes)、key4=Int(4B BE)。
    订阅帧 attr2=subId（2BE，z6.c 只写 2 字节——与现行 `02 <cmd BE>` 逐字节同构）；
    ack 侧 attr3=topic 字符串。未知 key 拒绝（fail-fast，不造非法帧）。"""
    out = b""
    for key in sorted(attrs):
        v = attrs[key]
        if key == 1:
            out += bytes([1]) + struct.pack(">q", int(v))
        elif key == 2:
            out += bytes([2]) + struct.pack(">H", int(v))
        elif key == 3:
            raw = v.encode("utf-8") if isinstance(v, str) else bytes(v)
            out += bytes([3]) + struct.pack(">H", len(raw)) + raw
        elif key == 4:
            out += bytes([4]) + struct.pack(">I", int(v))
        else:
            raise FrameDecodeError(f"unknown ext attr key {key}")
    return out


def parse_ext_attrs(ext: bytes) -> Dict[int, Any]:
    """ext 属性段解析（echo/push 的 attr2=subId、attr3=topic 捕获）。
    截断/未知 key 抛 FrameDecodeError（fail-visible，调用方计数不吞）。"""
    out: Dict[int, Any] = {}
    i, n = 0, len(ext)
    while i < n:
        key = ext[i]; i += 1
        if key == 1:
            if i + 8 > n:
                raise FrameDecodeError(f"ext attr1 truncated at {i}")
            out[1] = struct.unpack(">q", ext[i:i + 8])[0]; i += 8
        elif key == 2:
            if i + 2 > n:
                raise FrameDecodeError(f"ext attr2 truncated at {i}")
            out[2] = struct.unpack(">H", ext[i:i + 2])[0]; i += 2
        elif key == 3:
            if i + 2 > n:
                raise FrameDecodeError(f"ext attr3 len truncated at {i}")
            ln = struct.unpack(">H", ext[i:i + 2])[0]; i += 2
            if i + ln > n:
                raise FrameDecodeError(f"ext attr3 body truncated at {i}")
            out[3] = ext[i:i + ln]; i += ln
        elif key == 4:
            if i + 4 > n:
                raise FrameDecodeError(f"ext attr4 truncated at {i}")
            out[4] = struct.unpack(">I", ext[i:i + 4])[0]; i += 4
        else:
            raise FrameDecodeError(f"unknown ext attr key {key} at {i - 1}")
    return out


def parse_resub_topics(payload: bytes) -> List[str]:
    """Base.ResubNt{topics: repeated string} 解析（field 1, wire type 2）。

    宽容解析：任何 field>1 或非 LEN 编码的跳过；载荷空/解析异常返回 []（= 全量
    重发语义，与 App topics 空分支一致）。"""
    out: List[str] = []
    try:
        i, n = 0, len(payload)
        while i < n:
            tag = payload[i]; i += 1
            field, wire = tag >> 3, tag & 7
            if wire == 0:
                v = 0; shift = 0
                while i < n:
                    b = payload[i]; i += 1
                    v |= (b & 0x7F) << shift
                    if not b & 0x80:
                        break
                    shift += 7
            elif wire == 2:
                ln = 0; shift = 0
                while i < n:
                    b = payload[i]; i += 1
                    ln |= (b & 0x7F) << shift
                    if not b & 0x80:
                        break
                    shift += 7
                blob = payload[i:i + ln]; i += ln
                if field == 1:
                    out.append(blob.decode("utf-8", errors="replace"))
            elif wire == 5:
                i += 4
            elif wire == 1:
                i += 8
            else:
                break   # 3/7 保留：停止（fail-visible 上游留痕）
    except Exception:   # noqa: BLE001 — 宽容：坏载荷 → []（全量重发）
        return out
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


def build_hq_req_pb(stock_id: str) -> bytes:
    """Hq.HQReq{f1 stockId}：ServiceHqStock 单股订阅通用请求体。

    2203 涨停原因推送试点（2026-11-08）用；App 侧 2010/2012/2013/2203/2204 等
    均用此请求（StockQuotationInfoPresenter 3470-3530）。"""
    return pb_bytes(1, stock_id.encode("utf-8"))


def build_stock_zt_big_order_req_pb(stock_id: str, type_: int = 0, count: int = 0) -> bytes:
    """StockZTBigOrderDetailReq{f1 stockId, f2 type, f3 count}：2014 封板大单订阅。

    字段合同（proto 描述符，2026-11-11 提取自 ServiceHqStock.java）；App 基线
    （StockQuotationInfoPresenter case 2014）：type = 页签筛选 stock_zt_da_dan_select
    （默认 0），count = 本地已收数（首拉 0 取全量，增量语义待实弹校准）。
    proto3 零值省略（与 build_forecast_lhb_req_pb 同约定）。"""
    out = pb_bytes(1, str(stock_id).encode("utf-8"))
    if type_:
        out += pb_varint_field(2, int(type_))
    if count:
        out += pb_varint_field(3, int(count))
    return out


def build_abnormal_price_req_pb(stock_id: str) -> bytes:
    """AbnormalPriceReq{f1 stockId}：2030 异动提醒订阅（与 Hq.HQReq 同形，独立命名
    防混用；sub AbnormalPrice，SubAbnormalPrice 服务合同见 service_hq_stock 描述符）。"""
    return pb_bytes(1, str(stock_id).encode("utf-8"))


def bdo_item_yuan(item: Dict[str, Any]) -> Dict[str, Any]:
    """2014 单条 item raw → 派生字段（2026-11-11 裁决，单一换算出口；叙事回退同源复用）。

    - time_text：HHMM → "HH:MM"；raw 缺位/0（proto3 缺省与缺位不可分，A 股无 00:00
      交易时段）或结构非法 → None（缺失保持缺失，不伪造时间）。
    - tur_yuan/buy_tur_yuan/sell_tur_yuan/zt_tur_yuan：raw ÷ BDO_TUR_DIVISOR；
      非数值（异形帧 bytes 透传）→ None。0 是真实值（该分钟尚无大单/封单），不吞。
    - rate_pct：raw 原样（已是百分数 tur/ztTur×100）；缺位/非数值 → None。
    """
    out: Dict[str, Any] = {"time_text": None, "tur_yuan": None, "buy_tur_yuan": None,
                           "sell_tur_yuan": None, "zt_tur_yuan": None, "rate_pct": None}
    t = item.get("time")
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        ti = int(t)
        if ti > 0 and 0 <= ti % 100 <= 59 and ti // 100 <= 23:
            out["time_text"] = f"{ti // 100:02d}:{ti % 100:02d}"
    for rk, yk in (("tur", "tur_yuan"), ("buy_tur", "buy_tur_yuan"),
                   ("sell_tur", "sell_tur_yuan"), ("zt_tur", "zt_tur_yuan")):
        v = item.get(rk)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[yk] = v / BDO_TUR_DIVISOR
    rt = item.get("rate")
    if isinstance(rt, (int, float)) and not isinstance(rt, bool):
        out["rate_pct"] = float(rt)
    return out


def bdo_aggregate_last(data: Dict[str, Any]) -> Dict[str, Any]:
    """2014 解析产物 → 尾条派生聚合 {zt_tur_yuan, buy_tur_yuan, sell_tur_yuan}。

    尾条语义（2026-11-11 裁决）：zt_tur=该分钟封单额（级值，sum 无意义）、
    buy/sell_tur=当日累计封板大单买/卖额（sum 同样无意义）→ 展示口径一律取**最后一条**
    （最新状态）。items 空/无数值尾条 → 返回 {}（*_yuan 缺位 fail-visible，不补 0）。
    本函数防御式实现（异形帧不抛），供采集层在同一守卫内复用。
    """
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    for it in reversed(items):
        if not isinstance(it, dict):
            continue
        y = bdo_item_yuan(it)
        if y["zt_tur_yuan"] is None and y["buy_tur_yuan"] is None and y["sell_tur_yuan"] is None:
            continue
        return {k: y[k] for k in ("zt_tur_yuan", "buy_tur_yuan", "sell_tur_yuan")
                if y[k] is not None}
    return {}


def parse_stock_zt_big_order_resp(payload: bytes) -> Dict[str, Any]:
    """2014 StockZTBigOrderDetailResp → 封板大单明细（2026-11-11 ④ 协议层落地）。

    字段合同（proto 描述符，ServiceHqStock.java）：
    Resp{stockId=1(string), type=2(uint32), ztState=3(string), total=4(uint32),
    items=5(repeated Item)}；Item{time=1(uint32), tur=2(uint64), rate=3(float),
    buyTur=4(uint64), SellTur=5(uint64), ztTur=6(uint64)}。
    缩放/时间编码已钉死（2026-11-11 实弹值校准，见模块头裁决注与
    docs/kpl-socket/detail-scaling-verification.md）：time=HHMM、金额族=元×1、
    rate=百分数（tur/ztTur×100）。**raw 字段全保留**，items 追加派生字段
    time_text/tur_yuan/buy_tur_yuan/sell_tur_yuan/zt_tur_yuan/rate_pct
    （bdo_item_yuan 单一换算出口；缺位派生=None，fail-visible 不补 0）。"""
    pb = parse_pb(payload)
    items: List[Dict[str, Any]] = []
    for raw in pb.get(5, []):
        sub = parse_pb(raw)
        item = {
            "time": _signed64(pb_first(sub, 1, 0)),
            "tur": _signed64(pb_first(sub, 2, 0)),
            "rate": pb_first(sub, 3),
            "buy_tur": _signed64(pb_first(sub, 4, 0)),
            "sell_tur": _signed64(pb_first(sub, 5, 0)),
            "zt_tur": _signed64(pb_first(sub, 6, 0)),
        }
        item.update(bdo_item_yuan(item))
        items.append(item)
    return {
        "stock_id": _s_field(pb, 1),
        "type": pb_first(pb, 2, 0),
        "zt_state": _s_field(pb, 3),
        "total": pb_first(pb, 4, 0),
        "items": items,
        "raw_len": len(payload),
    }


def parse_bf_reason_resp(payload: bytes) -> Dict[str, Any]:
    """2202 BFReasonResp → 爆发原因推送（与 GetHisBFReason 历史同构；proto 描述符：
    stockId=1(string), desc=2(string 爆发解析全文), jumpId=3(int64)）。"""
    pb = parse_pb(payload)
    return {
        "stock_id": _s_field(pb, 1),
        "desc": _s_field(pb, 2),
        "jump_id": _signed64(pb_first(pb, 3, 0)),
        "raw_len": len(payload),
    }


def parse_abnormal_price_resp(payload: bytes) -> Dict[str, Any]:
    """2030 AbnormalPriceResp → 异动提醒（proto 描述符：stockId=1, price=2(uint32),
    date=3(string), nextDayPrice=10(uint32), nextDayZf=11(float)）。
    price 族缩放与 next_day_zf 口径**未钉死**（2026-11-11 阴性：当日事件推送
    16/16 样本三字段全缺位，无对照样本；解析器不动，原始值透出不换算，
    复验路径见 docs/kpl-socket/detail-scaling-verification.md §二）。"""
    pb = parse_pb(payload)
    return {
        "stock_id": _s_field(pb, 1),
        "price": _signed64(pb_first(pb, 2, 0)),
        "date": _s_field(pb, 3),
        "next_day_price": _signed64(pb_first(pb, 10, 0)),
        "next_day_zf": pb_first(pb, 11),
        "raw_len": len(payload),
    }


def parse_stock_related_plate_resp(payload: bytes) -> Dict[str, Any]:
    """2010 StockRelatedPlateListResp → 所属板块实时（proto 描述符：
    Resp{stockId=1, items=2(repeated Item), indexes=3(repeated uint32), maxSize=4}；
    Item{plateId=1(string), plateName=2(string), plateIncRate=3(float),
    stockId=4(string), stockName=5(string), stockIncRate=6(float), qzType=7(uint32)}）。
    qzType 语义未定，原样透出不自算。"""
    pb = parse_pb(payload)

    items: List[Dict[str, Any]] = []
    for raw in pb.get(2, []):
        sub = parse_pb(raw)
        items.append({
            "plate_id": _s_field(sub, 1),
            "plate_name": _s_field(sub, 2),
            "plate_inc_rate": pb_first(sub, 3),
            "stock_id": _s_field(sub, 4),
            "stock_name": _s_field(sub, 5),
            "stock_inc_rate": pb_first(sub, 6),
            "qz_type": pb_first(sub, 7, 0),
        })
    return {
        "stock_id": _s_field(pb, 1),
        "plates": items,
        "indexes": decode_packed_varints(pb.get(3, [])),
        "max_size": pb_first(pb, 4, 0),
        "raw_len": len(payload),
    }


def _s_field(pb: Dict[int, List[Any]], field: int) -> str:
    """pb string 字段取首个并解码（详情四通道解析共用）。"""
    v = pb_first(pb, field, b"")
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "replace")
    return "" if v is None else str(v)


def parse_anti_cheat_261(payload: bytes) -> bytes:
    """261 AntiCheatChallenge pb：f1 data（token32 + BE32 d + ASCII 挑战串）。

    服务端主动帧，payload 不加密（客户端直接 parse_pb）。App 侧取法
    （qn0.g / GameClient$onChallenge$2，反编译源码逐字对照）：
    data = f1；data 长度 < 36 视为无效帧（App 直接丢弃不断连）。
    """
    pb = parse_pb(payload)
    data = pb_first(pb, 1, b"")
    return bytes(data) if isinstance(data, (bytes, bytearray)) else b""


def anti_cheat_challenge(data: bytes) -> Tuple[bytes, int, str]:
    """拆 261 data → (token32, d, 挑战串)。

    App 口径：`new String(data, 36, len-36, US_ASCII)` = 挑战串；
    `d = BE32(data[32:36])` 作为 execEncryptedHex 第二参。
    """
    if len(data) < 36:
        return b"", 0, ""
    token = data[:32]
    d = int.from_bytes(data[32:36], "big")
    challenge = bytes(data[36:]).decode("ascii", "replace")
    return token, d, challenge


def build_anti_cheat_ans_262(data: bytes, value: int) -> bytes:
    """262 应答 pb：f1 = token32 + BE int32（EXEC 结果）。

    App 口径（qn0.g）：`new byte[36]` 前 32 字节原样回填 token，
    `[32:36] = (int) execEncryptedHex` 大端写入；外层 = AntiCheatChallenge{data}。
    `value` 取 Long.MIN_VALUE 时属 VM 失败（App 会直接断连），调用方不得发送。
    """
    body = bytes(data[:32]) + struct.pack(">I", int(value) & 0xFFFFFFFF)
    return pb_bytes(1, body)


def parse_hq_reasons_resp(payload: bytes) -> Dict[str, Any]:
    """2203 HQReasonsResp → 个股涨停原因实时推送解析。

    proto 反编译自 Hq.java 描述符（2026-11-08，字段号经 msgId=500 与既有
    parse 基准互证）：stockId=1, zt=2(涨停原因), fx=3(风险提示/异动),
    jc=4(减持), jj=5(解禁), pledge=6(质押), rank=10, rankTotal=11,
    rankTop=12(repeated), ztGroup=13(涨停梯队串), theme=14(题材), dd=15,
    childTheme=16, label=17, ztTag=100(uint32), msgId=500(uint64),
    plate=600(关联板块名), tp=700(repeated)。与 HTTP GetStockPanKou 的
    ZTReason/FXReason/JianChi/JieJin/Pledge 字段族同源互证。"""
    pb = parse_pb(payload)

    def _s(field: int) -> str:
        v = pb_first(pb, field, b"")
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).decode("utf-8", "replace")
        return "" if v is None else str(v)

    def _sl(field: int) -> List[str]:
        out: List[str] = []
        for v in pb.get(field, []):
            out.append(bytes(v).decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v))
        return out

    return {
        "stock_id": _s(1),
        "zt": _s(2),
        "fx": _s(3),
        "jc": _s(4),
        "jj": _s(5),
        "pledge": _s(6),
        "rank": _signed64(pb_first(pb, 10, 0)),
        "rank_total": _signed64(pb_first(pb, 11, 0)),
        "rank_top": _sl(12),
        "zt_group": _s(13),
        "theme": _s(14),
        "dd": _s(15),
        "child_theme": _s(16),
        "label": _s(17),
        "zt_tag": _signed64(pb_first(pb, 100, 0)),
        "msg_id": _signed64(pb_first(pb, 500, 0)),
        "plate": _s(600),
        "tp": _sl(700),
        "raw_len": len(payload),
    }


def parse_stock_related_theme_resp(payload: bytes) -> Dict[str, Any]:
    """2013 StockRelatedThemeResp → 个股题材库热度推送解析（2026-11-08 题材龙头语料）。

    proto 反编译自 ServiceHqStock.java 描述符（.tmp_review/main_src，与 2203 同批
    jadx 产物互证）：StockRelatedThemeResp{stockId=1(string), items=2(repeated
    Item{ id=1(string), name=2(string), number=3(float, wiretype=5) })}；
    请求 Hq.HQReq{f1 stockId}（与 2203 同款，复用 build_hq_req_pb）。
    number = App「题材库」页签的题材热度数值；items 可能含空 id/name（App 原样）。
    fail-visible：非有限 float（NaN/Inf）与非 float 形态（varint/bytes）原样 repr 透出，
    不猜、不出派生值（评审 2026-11-08 P2：NaN/Inf 会让 JSON 端点序列化出非法字面量）。"""
    pb = parse_pb(payload)

    def _s(field: int) -> str:
        v = pb_first(pb, field, b"")
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).decode("utf-8", "replace")
        return "" if v is None else str(v)

    themes: List[Dict[str, Any]] = []
    for raw in pb.get(2, []):
        if not isinstance(raw, (bytes, bytearray)):
            continue
        sub = parse_pb(bytes(raw))
        item: Dict[str, Any] = {"id": "", "name": "", "number": None}
        for v in sub.get(1, []):
            item["id"] = (bytes(v).decode("utf-8", "replace")
                          if isinstance(v, (bytes, bytearray)) else str(v))
        for v in sub.get(2, []):
            item["name"] = (bytes(v).decode("utf-8", "replace")
                            if isinstance(v, (bytes, bytearray)) else str(v))
        for v in sub.get(3, []):
            # 评审 2026-11-08 P2：NaN/Inf 由 struct.unpack("<f") 产生（非法 JSON 序列化 +
            # 下游 round OverflowError），非有限值并入 fail-visible 分支原样 repr；
            # varint 形态（wiretype 0 → int）按 repr(v) 带出原值（bytes(int) 会按值分配零字节）
            if isinstance(v, float) and math.isfinite(v):
                item["number"] = v
            elif isinstance(v, (bytes, bytearray)):
                item["number"] = repr(bytes(v)[:80])
            else:
                item["number"] = repr(v)[:80]
        themes.append(item)
    return {"stock_id": _s(1), "themes": themes}


def build_hq_list_req_pb(stock_id: str, curr_num: int) -> bytes:
    """Hq.HQListReq{f1 stockId(string), f2 currNum(uint32)}：增量分页订阅通用请求体。

    2009 大单标签（currNum=已收数）/ 2015 逐笔委托 / 2001-2004 分时价量（App 传
    本地已收数实现增量）。"""
    return pb_bytes(1, stock_id.encode("utf-8")) + pb_varint_field(2, int(curr_num))


def build_hq_item_req_pb(stock_id: str, count: int) -> bytes:
    """Hq.HQItemReq{f1 stockId(string), f2 count(uint32)}：2006 分时成交明细首拉请求。

    App 侧 StockQuotationInfoPresenter 3498 固定 count=25（首拉最近 25 条成交，
    之后同订阅由服务端经 2007 推增量）。"""
    return pb_bytes(1, stock_id.encode("utf-8")) + pb_varint_field(2, int(count))


def parse_stock_mx_resp(payload: bytes) -> Dict[str, Any]:
    """2006/2007 StockMXResp → 分时成交明细（大单分时试点，2026-11-08）。

    proto 反编译自 Hq.java 描述符：stockId=1, day=2, total=4,
    items=10(repeated Item{time=1, price=2, priceColor=3, vol=4, volColor=5,
    tur=6, origin=7})。

    缩放/语义（App 侧 nn0.y + DataStyleHelper 互证）：
    - time 为 9 位 int（HHMMSS+毫秒，V0 补齐 9 位取 HH/MM）；price 为 元×10000
      （DataStyleHelper.S0 = /10000.0f）；vol 为 手（>10000 App 显示“万”手）；
      turnoverMoney 公式 = vol*price/100（= vol手*100股*price元，单位 元）。
    - priceColor/volColor 为服务端涨跌染色（0/1/2 红绿白系，原样透出不自算）；
      origin 为交易所来源 int。
    """
    pb = parse_pb(payload)

    def _s(field: int) -> str:
        v = pb_first(pb, field, b"")
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).decode("utf-8", "replace")
        return "" if v is None else str(v)

    items: List[Dict[str, Any]] = []
    for raw in pb.get(10, []):
        sub = parse_pb(raw)
        items.append({
            "time": _signed64(pb_first(sub, 1, 0)),
            "price": _signed64(pb_first(sub, 2, 0)),
            "price_color": _signed64(pb_first(sub, 3, 0)),
            "vol": _signed64(pb_first(sub, 4, 0)),
            "vol_color": _signed64(pb_first(sub, 5, 0)),
            "tur": _signed64(pb_first(sub, 6, 0)),
            "origin": _signed64(pb_first(sub, 7, 0)),
        })
    return {
        "stock_id": _s(1),
        "day": _s(2),
        "total": _signed64(pb_first(pb, 4, 0)),
        "items": items,
        "raw_len": len(payload),
    }


def parse_ty_dan_label_resp(payload: bytes) -> Dict[str, Any]:
    """2009 TYDanLabelResp → 大单标签推送（分时图大单标记，tag 语义服务端定义原样透出）。

    proto 反编译自 Hq.java 描述符：stockId=1, day=2, total=9,
    items=10(repeated Item{tag=1, timestamp=2(int64 unix秒), tur=3(uint64 成交额)})。
    App 侧 nn0.Q：tag 原样入 bean（ee1 TYDanBean），timestamp 格式化 HH:mm 显示，
    tur 经 O(tur,7) 千分位显示；tag 具体档位（大单/超大单）App 未硬编码，不自算。
    """
    pb = parse_pb(payload)

    def _s(field: int) -> str:
        v = pb_first(pb, field, b"")
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).decode("utf-8", "replace")
        return "" if v is None else str(v)

    items: List[Dict[str, Any]] = []
    for raw in pb.get(10, []):
        sub = parse_pb(raw)
        items.append({
            "tag": _signed64(pb_first(sub, 1, 0)),
            "timestamp": _signed64(pb_first(sub, 2, 0)),
            "tur": _signed64(pb_first(sub, 3, 0)),
        })
    return {
        "stock_id": _s(1),
        "day": _s(2),
        "total": _signed64(pb_first(pb, 9, 0)),
        "items": items,
        "raw_len": len(payload),
    }


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
        # review 2026-11-18 M1：wire5 float 可产 NaN/Inf（struct.unpack("<f")）——
        # 非法 JSON 序列化杀 relay 整帧 + 下游 round(inf) OverflowError 杀会话 +
        # NaN 占首帧名额；非有限→None 按缺字段处理（镜像 2013 守卫，fail-visible）
        if isinstance(price, float) and not math.isfinite(price):
            price = None
        if isinstance(inc_price, float) and not math.isfinite(inc_price):
            inc_price = None
        if isinstance(inc_rate, float) and not math.isfinite(inc_rate):
            inc_rate = None
        item["price"] = price
        item["inc_price"] = inc_price
        item["inc_rate"] = inc_rate
        items.append(item)
    return {"items": items, "raw_len": len(payload)}
