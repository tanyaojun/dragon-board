# -*- coding: utf-8 -*-
"""KPL 龙虎榜链B协议：3004/3101 RealtimeLHB（service_hq_list.proto，2026-10-29 自主 dex 逆向）。

- 3004 = SubRealtimeLHB（订阅推送）、3101 = GetRealtimeLHBRangeData（带时间段单发），
  两者共用 RealtimeLHBReq/RealtimeLHBResp（qn0.java case 3004/3101）。
- Req：f1 quotaType, f2 sortType, f3 cxType, f4 limitType, f5 stType, f6 zbType,
  f7 cybType, f8 kcbType, f9 bjsType, f10 indexType(string), f20 start, f21 count,
  f30 startTime, f31 endTime（HHMM）。
- Resp：f1-f10 回显请求同名字段；f30 total, f31 minMTime, f32 maxMTime,
  f33 days(repeated string), f34 timestamp(int64), f40 indexes(repeated uint32),
  f41 items(repeated GroupStockQuotasResp.Item), f42 indexNames(repeated string),
  f500 msgId。
- items 复用 GroupStockQuotasResp.Item 口径（同 3001）：f1 stockId, f2 name,
  f100 quotas[]（紧凑字符串数组原样保留，字段级语义在展示层标注为推断——与
  parse_group_quotas 同一约定，单一事实源）。
- App 基线（PlateWeightStockPresenterImpl 订阅帧）：quotaType=6, sortType=1,
  limitType=4, bjsType=1, start=0, count=1（该 UI 只取首位；采集默认放宽 count=30，
  开火对账时可传 count=1 复现 App 帧）。
- proto3 零值省略（与 kpl_daban_protocol.build_forecast_lhb_req_pb 同约定）。

pytest 纪律：纯协议模块，零网络/零 adb/零真实 KPL 调用（AGENTS.md 红线 7）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from backend.services.kpl_socket_protocol import (
    decode_packed_varints, pb_bytes, pb_varint_field,
)

CMD_REALTIME_LHB_SUB = 3004    # SubRealtimeLHB 订阅
CMD_REALTIME_LHB_RANGE = 3101  # GetRealtimeLHBRangeData 单发

# App 基线默认（侦察笔记 2026-10-28；count 放宽为采集口径，App 原 UI count=1）
REALTIME_LHB_BASELINE = {
    "quota_type": 6,
    "sort_type": 1,
    "limit_type": 4,
    "bjs_type": 1,
    "count": 30,
}


def build_realtime_lhb_req_pb(
    quota_type: int = REALTIME_LHB_BASELINE["quota_type"],
    sort_type: int = REALTIME_LHB_BASELINE["sort_type"],
    cx_type: int = 0,
    limit_type: int = REALTIME_LHB_BASELINE["limit_type"],
    st_type: int = 0,
    zb_type: int = 0,
    cyb_type: int = 0,
    kcb_type: int = 0,
    bjs_type: int = REALTIME_LHB_BASELINE["bjs_type"],
    index_type: str = "",
    start: int = 0,
    count: int = REALTIME_LHB_BASELINE["count"],
    start_time: int = 0,
    end_time: int = 0,
) -> bytes:
    """RealtimeLHBReq → pb 字节（proto3 零值省略）。"""
    out = bytearray()
    for fid, val in ((1, quota_type), (2, sort_type), (3, cx_type), (4, limit_type),
                     (5, st_type), (6, zb_type), (7, cyb_type), (8, kcb_type),
                     (9, bjs_type), (20, start), (21, count),
                     (30, start_time), (31, end_time)):
        if val:
            out += pb_varint_field(fid, val)
    if index_type:
        out += pb_bytes(10, index_type.encode())
    return bytes(out)


def parse_quota_item(raw: bytes) -> Dict[str, Any]:
    """GroupStockQuotasResp.Item（f1 stockId, f2 name, f100 quotas[]）→ dict。

    quotas 原样保留字符串列表（缩放/语义在展示层标注，同 3001 约定）。
    """
    from backend.services.kpl_socket_protocol import parse_pb, pb_first

    sub = parse_pb(raw)
    return {
        "stock_id": (pb_first(sub, 1, b"") or b"").decode("utf-8", "replace"),
        "name": (pb_first(sub, 2, b"") or b"").decode("utf-8", "replace"),
        "quotas": [
            q.decode("utf-8", "replace") if isinstance(q, bytes) else str(q)
            for q in sub.get(100, [])
        ],
    }


def parse_realtime_lhb(payload: bytes) -> Dict[str, Any]:
    """RealtimeLHBResp → 结构化 dict（fail-visible：乱码宽容解析，保留 raw_len）。"""
    from backend.services.kpl_socket_protocol import parse_pb, pb_first

    pb = parse_pb(payload)
    items: List[Dict[str, Any]] = [parse_quota_item(raw) for raw in pb.get(41, [])]
    out: Dict[str, Any] = {
        # 回显请求字段
        "quota_type": pb_first(pb, 1, 0),
        "sort_type": pb_first(pb, 2, 0),
        "limit_type": pb_first(pb, 4, 0),
        "bjs_type": pb_first(pb, 9, 0),
        "index_type": (pb_first(pb, 10, b"") or b"").decode("utf-8", "replace")
        if isinstance(pb_first(pb, 10, b""), bytes) else str(pb_first(pb, 10, "")),
        # 数据字段
        "total": pb_first(pb, 30, 0),
        "min_mtime": pb_first(pb, 31, 0),
        "max_mtime": pb_first(pb, 32, 0),
        "days": [d.decode("utf-8", "replace") if isinstance(d, bytes) else str(d)
                 for d in pb.get(33, [])],
        "timestamp": pb_first(pb, 34, 0),
        "indexes": decode_packed_varints(pb.get(40, [])),
        "items": items,
        "index_names": [n.decode("utf-8", "replace") if isinstance(n, bytes) else str(n)
                        for n in pb.get(42, [])],
        "msg_id": pb_first(pb, 500, 0),
        "raw_len": len(payload),
    }
    return out


# collector dispatch 注册表（与 kpl_daban_protocol.DABAN_RESP_PARSERS 同构；
# 3004/3101 属 ServiceHqList 族，单一解析器共用 Resp 同型）
LHB_RESP_PARSERS: Dict[int, Callable[[bytes], Dict[str, Any]]] = {
    CMD_REALTIME_LHB_SUB: parse_realtime_lhb,
    CMD_REALTIME_LHB_RANGE: parse_realtime_lhb,
}
