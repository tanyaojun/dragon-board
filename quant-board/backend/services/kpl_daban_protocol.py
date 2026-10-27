# -*- coding: utf-8 -*-
"""KPL 打板/情绪 socket 订阅协议（service_hq_daban.proto + hq.proto）。

2026-10-27 逆向自 app 主 dex（main_src 反编译源码）：
- cmd 分发表：defpackage/qn0.java（2100-2126 号段）
- pb 合同：ServiceHqDaban.java 的 proto 描述符字符串（字段编号/类型）
- 请求构造：MoodPresenterImpl.k()（QxMarketEnergyReq{type} 或空 Req）
- 订阅机制：SocketPresenter.y() → e((byte)4) 即 0x40 通道（与 2301/3001/3006 同帧型）

帧格式复用 kpl_socket_protocol 的既有合同：
- CLI 订阅帧 [0x40][len4BE][seq2][cmd2][flags1][extlen2][ext=02 <cmdBE>][body]
- 推送帧 [0x60][extlen2][ext][cmd2][flags1][inner_extlen2][payload加密]（连接态 GCM 解密）

红线：本模块为纯协议逻辑，禁止任何网络/adb/子进程调用；pytest 全 mock。
"""
from __future__ import annotations

import math
import struct
from typing import Any, Dict, List, Optional

from backend.services.kpl_socket_protocol import (
    pb_first,
    pb_varint_field,
    _signed64,
)

# ---------------------------------------------------------------------------
# 命令常量（qn0.java 接收分发器 + MoodPresenterImpl 订阅调用）
# ---------------------------------------------------------------------------

CMD_DABAN_HEAD = 2100        # Hq.DaBanHeadResp（打板头：今昨涨/跌/封板数）
CMD_MARKET_ENERGY = 2106     # Hq.QxMarketEnergyResp（市场量能/预测量能/事件）
CMD_ZD_STAT_LINE = 2111      # Hq.QxZDStatLineChartResp（涨跌停折线）
CMD_ZD_STAT = 2114           # ServiceHqDaban.QxNewZDStatResp（涨跌停统计，含 map）
CMD_MARKET_OVERVIEW = 2115   # ServiceHqDaban.QxMarketOverviewResp（综合强度）
CMD_PLATE_STRENGTH = 2116    # ServiceHqDaban.QxPlateStrengthAndLossEffectResp（亏钱效应+LiveMarkets）
CMD_MARKET_HIGH_BENCH = 2117  # ServiceHqDaban.QxMarketHighBenchmarkResp（高度基准）
CMD_WEIGHT_PERF_V2 = 2118    # ServiceHqDaban.QxWeightPerformanceV2Resp（权重+大幅回撤）
CMD_ZT_SITUATION_V2 = 2119   # ServiceHqDaban.QxZtSituationRespV2（涨停表现：天梯/破板率）
CMD_ZT_STOCK_LIST = 2120     # ServiceHqDaban.QxZtSituationStockResp（涨停个股：封单/回封）
CMD_ZT_STOCK_LIST_PB = 2121  # 同上（跌停方向，BsType 区分）
CMD_WIND_VANE = 2126         # ServiceHqDaban.QxWindVaneResp（风向标）
CMD_DABAN_STOCK_LIST = 2103  # Hq.DaBanStockListResp（打板个股列表：竞价/即将涨停等页签）

# 2103 pidType → 页签（APK 资源数组 PatternTabs × PatternTabsServerPidType，2026-10-27
# androguard 解包 base_new.apk：['竞价','即将涨停','风向标','涨停','炸板','跌停',…]
# × ['8','0','6','1','2','3',…]）。已接：竞价/即将涨停/风向标；其余增量。
DABAN_LIST_PIDS: Dict[int, str] = {
    8: "bidding",       # 集合竞价
    0: "about_to_zt",   # 即将涨停
    6: "wind_vane",     # 风向标
}

DABAN_SUB_CMDS: tuple = (
    CMD_ZD_STAT,
    CMD_MARKET_OVERVIEW,
    CMD_PLATE_STRENGTH,
    CMD_ZT_SITUATION_V2,
    CMD_ZT_STOCK_LIST,
    CMD_WIND_VANE,
)


# ---------------------------------------------------------------------------
# 请求体构造（proto3，EmptyReq = 空 body）
# ---------------------------------------------------------------------------

def build_market_energy_req_pb(market_type: int = 1) -> bytes:
    """QxMarketEnergyReq{f1 type}：2114/2115/2118/2119 的请求体（MoodPresenterImpl type=l）。"""
    return pb_varint_field(1, market_type)


def build_zt_situation_stock_req_pb(bs_type: int = 1, order_type: int = 0, sort_type: int = 0) -> bytes:
    """QxZtSituationStockReq{f1 bsType, f2 orderType, f3 sortType}：2120(涨停)/2121(跌停)。"""
    return pb_varint_field(1, bs_type) + pb_varint_field(2, order_type) + pb_varint_field(3, sort_type)


def build_empty_req_pb() -> bytes:
    """pb.Empty：2116/2126/2100 等空请求（0 字节 body）。"""
    return b""


def build_daban_stock_list_req_pb(
    pid_type: int, order_type: int = 18, sort_type: int = 1,
    index: int = 0, count: int = 30,
) -> bytes:
    """2103 DaBanStockListReq{f1 pidType, f2 orderType, f3 sortType, f4 index, f5 count}。

    参数基线 = BiddingZTlQuotaPresenter 字段默认值（k=18 orderType / l=1 sortType /
    k0() 的 a0(0, 30)：index=0 count=30）；filter flags（stType/cxType/…）App 默认关=0，
    proto3 默认值不编码，省略。orderType 语义参照 2120 教训：必须用 App 在用基线值，
    不得自行填 0。
    """
    return (pb_varint_field(1, pid_type) + pb_varint_field(2, order_type)
            + pb_varint_field(3, sort_type) + pb_varint_field(4, index)
            + pb_varint_field(5, count))


# ---------------------------------------------------------------------------
# 带 fixed32/64 支持的 pb 解析（情绪模块大量 float 字段是 wire type 5）
# ---------------------------------------------------------------------------

def parse_pb_f32(data: bytes) -> Dict[int, List[Any]]:
    """宽容模式 pb 解析，比 parse_pb 多支持 wire 5(fixed32/float) 与 wire 1(fixed64/double)。

    tag 与长度均为 varint（field>=16 时 tag 两字节，如 quotas f100 → a2 06）。
    """
    out: Dict[int, List[Any]] = {}
    i, n = 0, len(data)
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
                out.setdefault(f, []).append(struct.unpack("<f", data[i : i + 4])[0])
                i += 4
            elif w == 1:
                out.setdefault(f, []).append(struct.unpack("<d", data[i : i + 8])[0])
                i += 8
            else:
                break
        except Exception:
            break
    return out


def _s(v: Any) -> str:
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else ("" if v is None else str(v))


# ---------------------------------------------------------------------------
# 响应解析（字段编号/类型严格对齐 service_hq_daban.proto）
# ---------------------------------------------------------------------------

def parse_zd_stat(payload: bytes) -> Dict[str, Any]:
    """2114 QxNewZDStatResp：f1 date, f10 zdStat, f11 zdStatBx。

    Stat{f1 zt, f2 dt, f3 realZt, f4 realDt, f5 rise, f6 down, f20 zdList(map entry{f1 key, f2 value})}。
    """
    pb = parse_pb_f32(payload)

    def stat(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        zd_list: Dict[str, int] = {}
        for entry in sub.get(20, []):
            e = parse_pb_f32(entry)
            zd_list[_s(pb_first(e, 1, b""))] = int(pb_first(e, 2, 0))
        return {
            "zt": pb_first(sub, 1, 0),
            "dt": pb_first(sub, 2, 0),
            "real_zt": pb_first(sub, 3, 0),
            "real_dt": pb_first(sub, 4, 0),
            "rise": pb_first(sub, 5, 0),
            "down": pb_first(sub, 6, 0),
            "zd_list": zd_list,
        }

    return {
        "date": _s(pb_first(pb, 1, b"")),
        "zd_stat": stat(pb_first(pb, 10, b"")) if pb.get(10) else None,
        "zd_stat_bx": stat(pb_first(pb, 11, b"")) if pb.get(11) else None,
        "raw_len": len(payload),
    }


def parse_market_overview(payload: bytes) -> Dict[str, Any]:
    """2115 QxMarketOverviewResp：综合强度/涨跌停比/预测量能。"""
    pb = parse_pb_f32(payload)
    return {
        "hs_ratio": pb_first(pb, 1),
        "hs_money": pb_first(pb, 2),
        "hsj_ratio": pb_first(pb, 3),
        "hsj_money": pb_first(pb, 4),
        "plate_strong_td": pb_first(pb, 5),
        "plate_strong_yd": pb_first(pb, 6),
        "loss_effect_td": pb_first(pb, 7),
        "loss_effect_yd": pb_first(pb, 8),
        "short_qx_td": pb_first(pb, 9),
        "qx_status": _s(pb_first(pb, 10, b"")),
        "drawback_num": pb_first(pb, 11),
        "forecast_money": _s(pb_first(pb, 12, b"")),
        "forecast_zf": _s(pb_first(pb, 13, b"")),
        "strong": pb_first(pb, 14),
        "raw_len": len(payload),
    }


def parse_plate_strength(payload: bytes) -> Dict[str, Any]:
    """2116 QxPlateStrengthAndLossEffectResp：亏钱效应趋势 + LiveMarkets 实时事件流。

    字段：f1 day, f10 plateStrengthTrend, f11 lossEffectTrend, f12 shortQxTrend,
    f20 LiveMarkets[]{f1 time, f2 msg, f3 isNew}, f21 marketQxTrend。
    Trend{f1 time(str), f2 num(uint)}。
    """
    pb = parse_pb_f32(payload)

    def trend(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        return {"time": _s(pb_first(sub, 1, b"")), "num": pb_first(sub, 2)}

    def live(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        return {
            "time": _s(pb_first(sub, 1, b"")),
            "msg": _s(pb_first(sub, 2, b"")),
            "is_new": pb_first(sub, 3),
        }

    return {
        "day": _s(pb_first(pb, 1, b"")),
        "plate_strength_trend": [trend(r) for r in pb.get(10, [])],
        "loss_effect_trend": [trend(r) for r in pb.get(11, [])],
        "short_qx_trend": [trend(r) for r in pb.get(12, [])],
        "live_markets": [live(r) for r in pb.get(20, [])],
        "market_qx_trend": [trend(r) for r in pb.get(21, [])],
        "raw_len": len(payload),
    }


def parse_weight_perf_v2(payload: bytes) -> Dict[str, Any]:
    """2118 QxWeightPerformanceV2Resp：权重表现 + 大幅回撤榜。msgId=f500（varint f4 03）。"""
    pb = parse_pb_f32(payload)

    def withdraw(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        return {
            "stock_id": _s(pb_first(sub, 1, b"")),
            "stock_name": _s(pb_first(sub, 2, b"")),
            "ratio": pb_first(sub, 3),
            "max_ratio": pb_first(sub, 4),
            "plate": _s(pb_first(sub, 5, b"")),
            "tag": pb_first(sub, 6, 0),
        }

    def index_stock(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        return {
            "index_id": _s(pb_first(sub, 1, b"")),
            "index_name": _s(pb_first(sub, 2, b"")),
            "ratio": pb_first(sub, 3),
            "stock_id": _s(pb_first(sub, 4, b"")),
            "stock_name": _s(pb_first(sub, 5, b"")),
            "stock_ratio": pb_first(sub, 6),
        }

    return {
        "quota_type": pb_first(pb, 1),
        "sort_type": pb_first(pb, 2),
        "withdraw_list": [withdraw(r) for r in pb.get(3, [])],
        "date": _s(pb_first(pb, 4, b"")),
        "num": pb_first(pb, 5),
        "msg_id": pb_first(pb, 500),
        "rise_stock_list": [index_stock(r) for r in pb.get(10, [])],
        "down_stock_list": [index_stock(r) for r in pb.get(11, [])],
        "raw_len": len(payload),
    }


def parse_zt_situation_v2(payload: bytes) -> Dict[str, Any]:
    """2119 QxZtSituationRespV2：连板天梯（1-4 板+高度）+ 破板率 + 昨日涨停/破板今表现。"""
    pb = parse_pb_f32(payload)
    return {
        "first_plate": pb_first(pb, 1, 0),
        "second_plate": pb_first(pb, 2, 0),
        "third_plate": pb_first(pb, 3, 0),
        "four_plate": pb_first(pb, 13, 0),
        "high_plate": pb_first(pb, 4, 0),
        "second_plate_ratio": pb_first(pb, 5),
        "third_plate_ratio": pb_first(pb, 6),
        "four_plate_ratio": pb_first(pb, 14),
        "high_plate_ratio": pb_first(pb, 7),
        "today_zb_ratio": pb_first(pb, 8),
        "yesterday_zt_state": pb_first(pb, 9),
        "yesterday_continue_plate": pb_first(pb, 10),
        "yesterday_pb_state": pb_first(pb, 11),
        "zt_state_sign": _s(pb_first(pb, 12, b"")),
        "raw_len": len(payload),
    }


def parse_zt_stock_list(payload: bytes) -> Dict[str, Any]:
    """2120/2121 QxZtSituationStockResp：涨停/跌停个股（封单 ztTur、状态 ztState、回封 state）。

    Item 字段（21 个）：f1 stockId, f2 stockName, f3 tag, f4 state, f5 price(int32),
    f6 increase(float), f7 ztTime, f8 ztReason, f9 ztReasonCount, f10 ztReasonJumpId,
    f11 ztState(str), f12 ztTur(uint64), f13 ztMaxTur, f14 mainNetAmount(int64),
    f15 mainBuy, f16 mainSell, f17 totalTur, f18 plate, f19 amplitude(float),
    f20 realCaptital, f21 turRate(float)。
    """
    pb = parse_pb_f32(payload)
    items: List[Dict[str, Any]] = []
    for raw in pb.get(10, []):
        sub = parse_pb_f32(raw)
        items.append({
            "stock_id": _s(pb_first(sub, 1, b"")),
            "stock_name": _s(pb_first(sub, 2, b"")),
            "tag": pb_first(sub, 3, 0),
            "state": pb_first(sub, 4, 0),
            "price": _signed64(pb_first(sub, 5, 0)),
            "increase": pb_first(sub, 6),
            "zt_time": pb_first(sub, 7, 0),
            "zt_reason": _s(pb_first(sub, 8, b"")),
            "zt_reason_count": pb_first(sub, 9, 0),
            "zt_reason_jump_id": _s(pb_first(sub, 10, b"")),
            "zt_state": _s(pb_first(sub, 11, b"")),
            "zt_tur": _signed64(pb_first(sub, 12, 0)),
            "zt_max_tur": _signed64(pb_first(sub, 13, 0)),
            "main_net_amount": _signed64(pb_first(sub, 14, 0)),
            "main_buy": _signed64(pb_first(sub, 15, 0)),
            "main_sell": _signed64(pb_first(sub, 16, 0)),
            "total_tur": _signed64(pb_first(sub, 17, 0)),
            "plate": _s(pb_first(sub, 18, b"")),
            "amplitude": pb_first(sub, 19),
            "real_captital": _signed64(pb_first(sub, 20, 0)),
            "tur_rate": pb_first(sub, 21),
        })
    return {
        "bs_type": pb_first(pb, 1, 0),
        "order_type": pb_first(pb, 2, 0),
        "sort_type": pb_first(pb, 3, 0),
        "day": _s(pb_first(pb, 4, b"")),
        "total": pb_first(pb, 5, 0),
        "items": items,
        "indexs": list(pb.get(11, [])),
        "raw_len": len(payload),
    }


def parse_wind_vane(payload: bytes) -> Dict[str, Any]:
    """2126 QxWindVaneResp：风向标（领涨/领跌代表股）。"""
    pb = parse_pb_f32(payload)

    def item(raw: bytes) -> Dict[str, Any]:
        sub = parse_pb_f32(raw)
        return {
            "stock_id": _s(pb_first(sub, 1, b"")),
            "stock_name": _s(pb_first(sub, 2, b"")),
            "increase": pb_first(sub, 3),
            "plate": _s(pb_first(sub, 4, b"")),
        }

    return {
        "up": [item(r) for r in pb.get(1, [])],
        "down": [item(r) for r in pb.get(2, [])],
        "raw_len": len(payload),
    }


# 2103 quotas 字符串列 → 语义名（2026-10-27 逆向三方对齐，缺一不可）：
# ① nn0.U()：DaBanStockListResp.Item.quotas 下标 → 统一数组位置（arrayPosition）
# ② APK tinker 资产 assets/PatternDynamicQuota：arrayPosition → 列名
# ③ APK 资源 PatternTabs/PatternTitleVisibleArrayPosition：页签默认列序
# （竞价=18,19,11,4,20,22,21,15；即将涨停=17,4,5,11,12,13,14,15）
# 未列入的 quotas 下标（20/21 号列无目录名）只进 raw quotas，不猜语义（fail-visible）。
DABAN_QUOTA_NAMES: Dict[int, str] = {
    0: "zt_buy_amount",     # 涨停委买额（pos18）
    1: "bidding_pct",       # 竞价涨幅（pos19）
    2: "bidding_net",       # 竞价净额（pos20）
    3: "bidding_turnover",  # 竞价换手（pos21）
    4: "bidding_amount",    # 竞价成交额（pos22）
    5: "price",             # 价格（pos17）
    6: "pct",               # 涨幅（pos4；App 竞价页签改叫「实时涨幅」）
    7: "amount",            # 成交额（pos13）
    8: "zt_time",           # 涨停时间（pos6）
    9: "open_time",         # 开板时间（pos7）
    10: "state",            # 状态（pos9）
    11: "speed",            # 涨速（pos5）
    12: "zt_reason",        # 涨停原因（pos16）
    13: "plate",            # 板块（pos11）
    14: "zt_tur",           # 封单（pos8）
    15: "main_net",         # 主力净额（pos12）
    16: "real_turnover",    # 实际换手（pos14）
    17: "real_float",       # 实际流通（pos15）
    18: "max_zt_tur",       # 最大封单（pos23）
    19: "last_zt_time",     # 最后涨停时间（pos25）
    22: "amplitude",        # 振幅（pos28）
    23: "turnover_rate",    # 换手率（pos29）
    24: "volume_ratio",     # 量比（pos30）
    25: "total_mv",         # 总市值（pos31）
    26: "float_mv",         # 流通市值（pos32）
}


def _maybe_num(v: str) -> Any:
    """quota 字符串可转数字则转（排序/聚合用），否则原样保留（App 侧常带「亿/万」单位）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return f if math.isfinite(f) else v


def parse_daban_stock_list(payload: bytes) -> Dict[str, Any]:
    """2103 DaBanStockListResp：打板个股列表（竞价 pidType=8 / 即将涨停 pidType=0）。

    Resp{f1 pidType, f2 orderType, f3 sortType, f4 index, f5 count, f20 items,
    f21 indexes, f22 maxSize, f23 date}；
    Item{f1 stockId, f2 name, f3 stockTag, f4 financingTag, f5 backZT, f6 warnTag,
    f100 quotas(repeated string)}。
    """
    pb = parse_pb_f32(payload)
    items: List[Dict[str, Any]] = []
    for raw in pb.get(20, []):
        sub = parse_pb_f32(raw)
        quotas = [_s(q) for q in sub.get(100, [])]
        named: Dict[str, Any] = {}
        for i, q in enumerate(quotas):
            name = DABAN_QUOTA_NAMES.get(i)
            if name is not None:
                named[name] = _maybe_num(q)
        items.append({
            "stock_id": _s(pb_first(sub, 1, b"")),
            "name": _s(pb_first(sub, 2, b"")),
            "stock_tag": _s(pb_first(sub, 3, b"")),
            "financing_tag": pb_first(sub, 4, 0),
            "back_zt": pb_first(sub, 5, 0),
            "warn_tag": _s(pb_first(sub, 6, b"")),
            **named,
            "quotas": quotas,   # fail-visible：未对齐列（含 20/21）原样保留
        })
    return {
        "pid_type": pb_first(pb, 1, 0),
        "order_type": pb_first(pb, 2, 0),
        "sort_type": pb_first(pb, 3, 0),
        "index": pb_first(pb, 4, 0),
        "count": pb_first(pb, 5, 0),
        "items": items,
        "indexes": list(pb.get(21, [])),
        "max_size": pb_first(pb, 22, 0),
        "date": _s(pb_first(pb, 23, b"")),
        "raw_len": len(payload),
    }


DABAN_RESP_PARSERS: Dict[int, Any] = {
    CMD_ZD_STAT: parse_zd_stat,
    CMD_MARKET_OVERVIEW: parse_market_overview,
    CMD_PLATE_STRENGTH: parse_plate_strength,
    CMD_WEIGHT_PERF_V2: parse_weight_perf_v2,
    CMD_ZT_SITUATION_V2: parse_zt_situation_v2,
    CMD_ZT_STOCK_LIST: parse_zt_stock_list,
    CMD_ZT_STOCK_LIST_PB: parse_zt_stock_list,
    CMD_WIND_VANE: parse_wind_vane,
    CMD_DABAN_STOCK_LIST: parse_daban_stock_list,
}
