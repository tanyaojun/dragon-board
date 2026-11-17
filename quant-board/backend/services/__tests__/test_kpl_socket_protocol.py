# -*- coding: utf-8 -*-
"""KPL 协议纯逻辑层测试。

红线（2026-10-27）：一切自动化测试禁止触发真实 KPL 连接 / 真实 signsvc 调用。
本文件只用 fixture 字节与 mock codec —— kpl_collector_service 的网络路径在此不测。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_socket_protocol as proto  # noqa: E402


class TestFlags:
    def test_flags_formula(self):
        # 实测事实：601/610 d=2 加密=0x11；602 d=0=0x01；2301 d=1=0x09
        assert proto.flags(2, True) == 0x11
        assert proto.flags(2, False) == 0x10
        assert proto.flags(0, True) == 0x01
        assert proto.flags(1, True) == 0x09


class TestVarint:
    def test_short_value_single_byte(self):
        assert proto.encode_varint(1) == b"\x01"
        assert proto.encode_varint(127) == b"\x7f"

    def test_long_value_two_bytes(self):
        # 190 > 127 必须两字节 —— 早期 1 字节硬塞导致 1002 的回归测试
        assert proto.encode_varint(190) == b"\xbe\x01"

    def test_pb_bytes_length_field(self):
        out = proto.pb_bytes(5, b"x" * 190)
        assert out[0] == (5 << 3) | 2
        assert out[1:3] == b"\xbe\x01"


class TestBuildFrames:
    def test_build_auth_frame_matches_app_observed_format(self):
        # app 实测帧头: 30 000001?? 0001 0262 11 0000
        frame = proto.build_frame(proto.CMD_AUTH, 1, b"\xaa" * 16, d=2, encrypted=True)
        assert frame[0] == 0x30
        ln = int.from_bytes(frame[1:5], "big")
        assert ln == 7 + 16
        assert frame[5:7] == b"\x00\x01"          # seq
        assert frame[7:9] == b"\x02\x62"          # cmd 610
        assert frame[9] == 0x11                   # flags
        assert frame[10:12] == b"\x00\x00"        # extlen

    def test_build_subscribe_frame_with_route_ext(self):
        # 0x40 订阅帧: pkg=40, cmd=2301(0x08fd), d=1→flags 0x09, ext=02 08fd
        frame = proto.build_frame(
            proto.CMD_PLATE_LIST, 3, b"\x08\x00", d=1, encrypted=True,
            pkg=proto.PKG_ROUTE, ext=bytes([0x02, 0x08, 0xFD]),
        )
        assert frame[0] == 0x40
        assert frame[5:7] == b"\x00\x03"
        assert frame[7:9] == b"\x08\xfd"
        assert frame[9] == 0x09
        assert frame[10:12] == bytes([0x00, 0x03])          # extlen
        assert frame[12:15] == bytes([0x02, 0x08, 0xFD])  # ext route header
        assert frame[12:15] == bytes([0x02, 0x08, 0xFD])  # ext 路由头


class TestAuthReqPb:
    def test_auth_req_fields(self):
        pb = proto.build_auth_req_pb(
            device_id="4a81acf4", version_name="6.3.20.2", channel_id=129,
            signature_hex="ab" * 95, user_id="0", token="", conn_type=99,
            cur_time=1793033481, api_version="w48",
        )
        parsed = proto.parse_pb(pb)
        assert parsed[1][0] == b"4a81acf4"
        assert parsed[2][0] == 1
        assert parsed[4][0] == 129
        assert parsed[5][0] == b"ab" * 95
        assert parsed[6][0] == b"0"
        assert parsed[8][0] == 99
        assert parsed[10][0] == b"w48"


class TestParseIncoming:
    def test_parse_260_challenge_real_capture(self):
        # 2026-10-26 真实捕获的 260 帧结构，程序化重建（避免手打 hex 笔误）
        body = (
            (260).to_bytes(2, "big")          # cmd
            + b"\x00"                          # status
            + b"\x00\x00"                      # extlen
            + proto.pb_varint_field(1, 1793025791)
            + proto.pb_bytes(2, b"2db64e49ca378ac2a21331deca1a7425")
            + proto.pb_varint_field(3, 1)
        )
        raw = bytes([proto.PKG_SERVER]) + len(body).to_bytes(4, "big") + body
        info = proto.parse_incoming(raw)
        assert info["fmt"] == "srv"
        assert info["cmd"] == 260
        server_time, challenge, code_type = proto.parse_challenge_260(info["payload"])
        assert server_time == 1793025791
        assert challenge == "2db64e49ca378ac2a21331deca1a7425"
        assert code_type == 1

    def test_parse_echo_610_ack(self):
        # 610 认证应答（echo 格式, 加密 payload 截取）
        raw = bytes.fromhex(
            "300000003700050262110000a4497d750000000006a33a4c8c898120"
        )
        info = proto.parse_incoming(raw)
        assert info["fmt"] == "echo"
        assert info["cmd"] == proto.CMD_AUTH
        assert info["seq"] == 5
        assert info["payload"][:4] == bytes.fromhex("a4497d75")

    def test_parse_push_frame_0x60(self):
        # 0x60 服务器主动推送（真实捕获结构）：ext 路由 + cmd + inner extlen
        inner_ext = b"\x00\x00"
        body = struct_pack = (
            len(b"hqList|74:20030/3001-0/").to_bytes(2, "big")
            + b"hqList|74:20030/3001-0/"
            + (3001).to_bytes(2, "big")
            + b"\x01"
            + inner_ext
            + b"\xde\xad\xbe\xef"
        )
        raw = bytes([0x60]) + len(body).to_bytes(4, "big") + body
        info = proto.parse_incoming(raw)
        assert info["fmt"] == "push"
        assert info["kind"] == 6
        assert info["cmd"] == 3001
        assert info["ext"].startswith("hqList|")
        assert info["payload"] == b"\xde\xad\xbe\xef"

    def test_garbage_raises(self):
        try:
            proto.parse_incoming(b"\xff\x00\x00\x00\x00")
        except proto.FrameDecodeError:
            pass
        else:
            raise AssertionError("expected FrameDecodeError")


class TestParseGroupQuotas:
    def test_real_push_item(self):
        # 2026-10-27 真实推送解密帧（板块 885423 安防）
        payload = bytes.fromhex(
            "1002"
            "4a01" "01"
            "52bd03"
            "0a063838353432331206e5ae89e998b2"
            "a20600"
            "a20608313230312e343836"
            "a206062d302e383234"
            "a2060b3531363835383036303830"
            "a20605322e373734"
        )
        out = proto.parse_group_quotas(payload)
        assert out["items"], "items must not be empty"
        item = out["items"][0]
        assert item["stock_id"] == "885423"
        assert item["name"] == "安防"
        assert "1201.486" in item["quotas"]     # 价格（推断列）
        assert "-0.824" in item["quotas"]       # 涨跌（推断列）
        assert out["raw_len"] == len(payload)

    def test_empty_payload_yields_empty_items(self):
        out = proto.parse_group_quotas(b"")
        assert out["items"] == []


class TestParseErrResp:
    def test_1002_error(self):
        # 真实 1002 错误帧: 08 ea07 12 13 "错误：1002"
        payload = bytes.fromhex("08ea071213e8bf9ee68ea5e99499e8afafefbc9a31303032")
        err = proto.parse_err_resp(payload)
        assert err["code"] == 1002
        assert "1002" in err["msg"]

class TestIndexSimpleQuotes:
    def test_negative_values_signed_varint(self):
        # 3006 IndexSimpleQuotasResp：负 int 以 10 字节补码 varint 编码
        # incPrice=-824 → uint64 回绕 (1<<64)-824；必须还原为 -824 而非 18446744073709529846
        item = (
            proto.pb_bytes(1, b"000001")
            + proto.pb_bytes(2, "平安银行".encode())
            + proto.pb_varint_field(3, 113000)
            + proto.pb_varint_field(4, (1 << 64) - 824)
            + proto.pb_varint_field(5, (1 << 64) - 1)
        )
        payload = proto.pb_bytes(1, item)
        out = proto.parse_index_simple_quotes(payload)
        assert out["items"][0]["stock_id"] == "000001"
        assert out["items"][0]["name"] == "平安银行"
        assert out["items"][0]["price"] == 113000
        assert out["items"][0]["inc_price"] == -824
        assert out["items"][0]["inc_rate"] == -1

    def test_positive_values_unchanged(self):
        item = (
            proto.pb_bytes(1, b"000001")
            + proto.pb_varint_field(3, 113000)
            + proto.pb_varint_field(5, 125)
        )
        out = proto.parse_index_simple_quotes(proto.pb_bytes(1, item))
        assert out["items"][0]["price"] == 113000
        assert out["items"][0]["inc_rate"] == 125
        assert out["items"][0]["inc_price"] is None


class TestHQReasons2203:
    """2203 涨停原因推送（试点）：HQReq 构造 + HQReasonsResp 解析（proto 反编译合同）。"""

    def test_build_hq_req_pb_bytes(self):
        # Hq.HQReq{f1 stockId}：单 len-delimited 字段，App 同款（StockQuotationInfoPresenter）
        assert proto.build_hq_req_pb("301697") == b"\x0a\x06" + b"301697"

    def test_parse_hq_reasons_resp_full(self):
        payload = (
            proto.pb_bytes(1, b"301697")
            + proto.pb_bytes(2, "光伏+次新股；据投资者关系活动记录表……".encode())
            + proto.pb_bytes(3, "异动提醒文本".encode())
            + proto.pb_bytes(6, "质押文本".encode())
            + proto.pb_varint_field(10, 3)
            + proto.pb_varint_field(11, 44)
            + proto.pb_bytes(12, "801070".encode())
            + proto.pb_bytes(12, "801631".encode())
            + proto.pb_bytes(13, "2连板".encode())
            + proto.pb_bytes(14, "光伏".encode())
            + proto.pb_varint_field(100, 2)      # f100 ztTag（多字节 tag a2 06）
            + proto.pb_varint_field(500, 7)      # f500 msgId
            + proto.pb_bytes(600, "光伏".encode())   # f600 plate
            + proto.pb_bytes(700, "tp1".encode())
            + proto.pb_bytes(700, "tp2".encode())
        )
        out = proto.parse_hq_reasons_resp(payload)
        assert out["stock_id"] == "301697"
        assert out["zt"].startswith("光伏+次新股")
        assert out["fx"] == "异动提醒文本"
        assert out["pledge"] == "质押文本"
        assert out["rank"] == 3 and out["rank_total"] == 44
        assert out["rank_top"] == ["801070", "801631"]
        assert out["zt_group"] == "2连板" and out["theme"] == "光伏"
        assert out["zt_tag"] == 2 and out["msg_id"] == 7
        assert out["plate"] == "光伏" and out["tp"] == ["tp1", "tp2"]
        assert out["jc"] == "" and out["jj"] == ""   # 缺字段回空串不报错

    def test_parse_hq_reasons_resp_empty_payload(self):
        out = proto.parse_hq_reasons_resp(b"")
        assert out["stock_id"] == "" and out["zt"] == "" and out["rank_top"] == []
        assert out["raw_len"] == 0


class TestStockMX2006:
    """2006/2007 分时成交明细 + 2009 大单标签（大单分时试点，2026-11-08 实弹验证）。"""

    def test_build_hq_item_req_pb_bytes(self):
        # Hq.HQItemReq{f1 stockId, f2 count}：App 侧 2006 固定 count=25
        assert proto.build_hq_item_req_pb("301697", 25) == b"\x0a\x06" + b"301697" + b"\x10\x19"

    def test_build_hq_list_req_pb_bytes(self):
        # Hq.HQListReq{f1 stockId, f2 currNum}：2009/2015/2001-2004 增量通用
        assert proto.build_hq_list_req_pb("301697", 0) == b"\x0a\x06" + b"301697" + b"\x10\x00"

    def test_parse_stock_mx_resp_full(self):
        item = (
            proto.pb_varint_field(1, 145700000)   # time 9 位 HHMMSS+ms
            + proto.pb_varint_field(2, 366000)     # price 元×10000 → 36.60
            + proto.pb_varint_field(3, 1)          # priceColor
            + proto.pb_varint_field(4, 5)          # vol 手
            + proto.pb_varint_field(5, 0)          # volColor
            + proto.pb_varint_field(6, 18300)      # tur 成交额元
            + proto.pb_varint_field(7, 0)          # origin
        )
        payload = (
            proto.pb_bytes(1, b"301697")
            + proto.pb_bytes(2, b"20261106")
            + proto.pb_varint_field(4, 1344)
            + proto.pb_bytes(10, item)
        )
        out = proto.parse_stock_mx_resp(payload)
        assert out["stock_id"] == "301697" and out["day"] == "20261106"
        assert out["total"] == 1344 and len(out["items"]) == 1
        it = out["items"][0]
        assert it["time"] == 145700000 and it["price"] == 366000
        assert it["price_color"] == 1 and it["vol"] == 5
        assert it["vol_color"] == 0 and it["tur"] == 18300 and it["origin"] == 0
        # 缩放互证（实弹：5手×36.60元×100股 = 18300 元）
        assert it["vol"] * (it["price"] / 10000) * 100 == it["tur"]

    def test_parse_stock_mx_resp_empty(self):
        out = proto.parse_stock_mx_resp(b"")
        assert out["stock_id"] == "" and out["total"] == 0 and out["items"] == []

    def test_parse_ty_dan_label_resp_full(self):
        lab = (
            proto.pb_varint_field(1, 2)
            + proto.pb_varint_field(2, 1794338025)
            + proto.pb_varint_field(3, 5200000)
        )
        payload = (
            proto.pb_bytes(1, b"301697")
            + proto.pb_bytes(2, b"20261106")
            + proto.pb_varint_field(9, 4)
            + proto.pb_bytes(10, lab)
        )
        out = proto.parse_ty_dan_label_resp(payload)
        assert out["stock_id"] == "301697" and out["total"] == 4
        assert out["items"] == [{"tag": 2, "timestamp": 1794338025, "tur": 5200000}]

    def test_parse_ty_dan_label_resp_empty(self):
        out = proto.parse_ty_dan_label_resp(b"")
        assert out["total"] == 0 and out["items"] == [] and out["day"] == ""


class TestAntiCheat261:
    """261/262 反作弊轮（2026-11-08 实现）：App 口径逐字节对照（qn0.g / GameClient$onChallenge$2）。"""

    def _data(self, value: int = 0x0BADF00D, tail: bytes = b"chal-abcdef") -> bytes:
        return b"T" * 24 + b"O" * 8 + value.to_bytes(4, "big") + tail

    def test_parse_anti_cheat_261_takes_field1(self):
        data = self._data()
        payload = proto.pb_bytes(1, data) + proto.pb_bytes(2, b"ignored")
        assert proto.parse_anti_cheat_261(payload) == data
        assert proto.parse_anti_cheat_261(b"") == b""

    def test_anti_cheat_challenge_splits_token_d_and_ascii(self):
        data = self._data(value=7, tail=b"c1|8fd")
        token, d, challenge = proto.anti_cheat_challenge(data)
        assert token == b"T" * 24 + b"O" * 8
        assert d == 7
        assert challenge == "c1|8fd"
        # <36 字节：App 丢弃且不断连（返回空 token/0/空串）
        assert proto.anti_cheat_challenge(b"short") == (b"", 0, "")

    def test_build_anti_cheat_ans_262_token_passthrough_and_be_int32(self):
        data = self._data()
        ans = proto.build_anti_cheat_ans_262(data, 0x1A2B3C4D)
        parsed = proto.parse_pb(ans)
        assert len(parsed[1]) == 1
        body = parsed[1][0]
        assert len(body) == 36
        assert body[:32] == data[:32]            # token 原样回填
        assert body[32:36] == (0x1A2B3C4D).to_bytes(4, "big")
        # 负数按 32 位补码写入（App: (int) long）
        body_neg = proto.parse_pb(proto.build_anti_cheat_ans_262(data, -2))[1][0]
        assert body_neg[32:36] == b"\xff\xff\xff\xfe"


class TestStockRelatedTheme2013:
    """2013 题材库热度推送（题材龙头语料第 2 项）：StockRelatedThemeResp 解析合同。

    proto 反编译自 ServiceHqStock.java 描述符：stockId=1, items=2(repeated
    Item{id=1, name=2, number=3 float/wiretype5})；2026-11-08。"""

    def _item(self, tid: str = "80001", name: str = "光伏", num: float = 96.5) -> bytes:
        import struct as _st
        body = proto.pb_bytes(1, tid.encode()) + proto.pb_bytes(2, name.encode())
        if num is not None:
            body += b"\x1d" + _st.pack("<f", num)   # field 3 wiretype 5 (fixed32)
        return body

    def test_parse_full(self):
        payload = (proto.pb_bytes(1, b"301697")
                   + proto.pb_bytes(2, self._item())
                   + proto.pb_bytes(2, self._item("80002", "有机硅", 71.0)))
        out = proto.parse_stock_related_theme_resp(payload)
        assert out["stock_id"] == "301697"
        assert len(out["themes"]) == 2
        assert out["themes"][0] == {"id": "80001", "name": "光伏", "number": 96.5}
        assert abs(out["themes"][1]["number"] - 71.0) < 1e-5

    def test_parse_pb_captures_fixed32_float(self):
        # parse_pb 此前跳过 wiretype 5；2026-11-08 起捕获 little-endian float（新增键不影响旧读点）
        import struct as _st
        pb = proto.parse_pb(b"\x1d" + _st.pack("<f", 3.25))
        assert pb[3][0] == 3.25

    def test_parse_non_finite_and_varint_number_fail_visible(self):
        """评审 P2：NaN/Inf（fixed32 unpack 可产）与 varint 形态 → repr 原样，不出派生值。"""
        import struct as _st
        nan_payload = (proto.pb_bytes(1, b"301697")
                       + proto.pb_bytes(2, self._item() + b"\x1d" + _st.pack("<f", float("nan"))))
        out = proto.parse_stock_related_theme_resp(nan_payload)
        n = out["themes"][0]["number"]
        assert isinstance(n, str) and "nan" in n
        inf_payload = (proto.pb_bytes(1, b"301697")
                       + proto.pb_bytes(2, self._item() + b"\x1d" + _st.pack("<f", float("inf"))))
        out2 = proto.parse_stock_related_theme_resp(inf_payload)
        assert isinstance(out2["themes"][0]["number"], str) and "inf" in out2["themes"][0]["number"]
        # varint 形态（wiretype 0 → int）：repr(v) 带出原值（不得 bytes(int) 按值分配零字节）
        varint_payload = (proto.pb_bytes(1, b"301697")
                          + proto.pb_bytes(2, self._item() + b"\x18\x05"))   # f3 varint=5
        out3 = proto.parse_stock_related_theme_resp(varint_payload)
        assert out3["themes"][0]["number"] == "5"

    def test_parse_empty_and_missing_number(self):
        out = proto.parse_stock_related_theme_resp(b"")
        assert out["stock_id"] == "" and out["themes"] == []
        payload = proto.pb_bytes(1, b"301697") + proto.pb_bytes(2, self._item(num=None))
        out2 = proto.parse_stock_related_theme_resp(payload)
        assert out2["themes"][0]["number"] is None
        assert out2["themes"][0]["name"] == "光伏"


# ---------- 2026-11-11 ④：详情四通道 Req 构造 + Resp 解析（字段号=proto 描述符） ----------

class TestStockDetailChannels20261111:
    """2014/2202/2030/2010（封板大单/爆发原因/异动提醒/所属板块，mock 全绿；
    缩放/时间编码待实弹校准，原始值透出不换算）。"""

    def test_build_stock_zt_big_order_req(self):
        # {stockId=1, type=2, count=3}；proto3 零值省略
        assert (proto.build_stock_zt_big_order_req_pb("002708", 0, 0)
                == proto.pb_bytes(1, b"002708"))
        req = proto.build_stock_zt_big_order_req_pb("002708", 1, 5)
        assert req == (proto.pb_bytes(1, b"002708")
                       + proto.pb_varint_field(2, 1) + proto.pb_varint_field(3, 5))

    def test_build_abnormal_price_req(self):
        assert proto.build_abnormal_price_req_pb("002708") == proto.pb_bytes(1, b"002708")

    def test_parse_stock_zt_big_order_resp(self):
        import struct as _struct

        def pb_fixed32(field: int, f: float) -> bytes:
            return proto.encode_varint((field << 3) | 5) + _struct.pack("<f", f)

        # rate=41.15（fixed32 float）＝tur/ztTur×100（21376680/51950196×100）帧内自洽样本
        item = (proto.pb_varint_field(1, 941)
                + proto.pb_varint_field(2, 21376680)
                + pb_fixed32(3, 41.15)
                + proto.pb_varint_field(4, 208147347)
                + proto.pb_varint_field(5, 103086910)
                + proto.pb_varint_field(6, 51950196))
        payload = (proto.pb_bytes(1, b"002708")
                   + proto.pb_varint_field(2, 1)
                   + proto.pb_bytes(3, b"sealed")
                   + proto.pb_varint_field(4, 3)
                   + proto.pb_bytes(5, item)
                   + proto.pb_bytes(5, proto.pb_varint_field(2, 222)))
        d = proto.parse_stock_zt_big_order_resp(payload)
        assert d["stock_id"] == "002708" and d["type"] == 1
        assert d["zt_state"] == "sealed" and d["total"] == 3
        it0 = d["items"][0]
        # raw 字段全保留
        assert (it0["time"], it0["tur"], it0["buy_tur"], it0["sell_tur"],
                it0["zt_tur"]) == (941, 21376680, 208147347, 103086910, 51950196)
        assert abs(it0["rate"] - 41.15) < 0.01
        # 派生字段（2026-11-11 裁决：time=HHMM、金额族=元×1、rate=百分数原样）
        assert it0["time_text"] == "09:41"
        assert it0["tur_yuan"] == 21376680.0
        assert it0["zt_tur_yuan"] == 51950196.0
        assert it0["buy_tur_yuan"] == 208147347.0
        assert it0["sell_tur_yuan"] == 103086910.0
        assert abs(it0["rate_pct"] - 41.15) < 0.01, "rate 已是百分数（tur/zt×100），不×100"
        # 缺位派生 = None（fail-visible，不补 0/不伪造）
        assert d["items"][1]["time"] == 0 and d["items"][1]["time_text"] is None
        assert d["items"][1]["rate"] is None and d["items"][1]["rate_pct"] is None
        assert d["items"][1]["tur"] == 222 and d["items"][1]["tur_yuan"] == 222.0

    def test_bdo_time_text_decoding(self):
        """time=HHMM 裁决：941→09:41 / 1500→15:00 / 0（proto3 缺省=缺位）→None。"""
        assert proto.BDO_TIME_IS_HHMM and proto.BDO_TUR_DIVISOR == 1
        assert proto.BDO_RATE_IS_PERCENT

        def one(t) -> dict:
            return proto.bdo_item_yuan({"time": t})

        assert one(941)["time_text"] == "09:41"
        assert one(1500)["time_text"] == "15:00"
        assert one(1130)["time_text"] == "11:30"
        assert one(0)["time_text"] is None, "0=缺位不可分，不伪造 00:00"
        assert one(None)["time_text"] is None
        assert one(b"\x01")["time_text"] is None, "异形帧 bytes 透传 → None"

    def test_bdo_item_yuan_missing_and_weird(self):
        # 非数值字段派生 None；数值 0 是真实值（该分钟无大单）不吞
        y = proto.bdo_item_yuan({"tur": 0, "buy_tur": b"\x01", "rate": None})
        assert y["tur_yuan"] == 0.0
        assert y["buy_tur_yuan"] is None
        assert y["zt_tur_yuan"] is None and y["sell_tur_yuan"] is None
        assert y["rate_pct"] is None

    def test_bdo_aggregate_last(self):
        """尾条派生聚合：zt=封单额级值、buy/sell=当日累计 → 取尾条最新态（sum 无意义）。"""
        d = {"items": [
            {"zt_tur": 22391088, "buy_tur": 5236460, "sell_tur": 0},
            {"zt_tur": 51950196, "buy_tur": 208147347, "sell_tur": 103086910},
        ]}
        assert proto.bdo_aggregate_last(d) == {
            "zt_tur_yuan": 51950196.0, "buy_tur_yuan": 208147347.0,
            "sell_tur_yuan": 103086910.0}
        # 空/异形 → {}（*_yuan 缺位 fail-visible，不补 0）
        assert proto.bdo_aggregate_last({"items": []}) == {}
        assert proto.bdo_aggregate_last({"items": ["x", 3]}) == {}
        assert proto.bdo_aggregate_last({}) == {}
        assert proto.bdo_aggregate_last(None) == {}
        # 尾条字段全非数值 → 跳过找上一条
        d2 = {"items": [{"zt_tur": 100}, {"zt_tur": b"\x01"},
                        {"zt_tur": 51950196, "buy_tur": 7}]}
        assert proto.bdo_aggregate_last(d2) == {"zt_tur_yuan": 51950196.0,
                                                "buy_tur_yuan": 7.0}

    def test_parse_bf_reason_resp(self):
        payload = (proto.pb_bytes(1, b"002708")
                   + proto.pb_bytes(2, "光伏订单放量".encode())
                   + proto.pb_varint_field(3, 801464))
        d = proto.parse_bf_reason_resp(payload)
        assert d == {"stock_id": "002708", "desc": "光伏订单放量", "jump_id": 801464,
                     "raw_len": len(payload)}

    def test_parse_abnormal_price_resp(self):
        payload = (proto.pb_bytes(1, b"002708")
                   + proto.pb_varint_field(2, 580)
                   + proto.pb_bytes(3, b"2026-11-10")
                   + proto.pb_varint_field(10, 600)
                   + proto.pb_varint_field(11, 321))
        d = proto.parse_abnormal_price_resp(payload)
        assert d["stock_id"] == "002708" and d["price"] == 580
        assert d["date"] == "2026-11-10"
        assert d["next_day_price"] == 600 and d["next_day_zf"] == 321

    def test_parse_stock_related_plate_resp(self):
        plate = (proto.pb_bytes(1, b"801464")
                 + proto.pb_bytes(2, "机器人".encode())
                 + proto.pb_varint_field(3, 0)
                 + proto.pb_bytes(5, "002708".encode())
                 + proto.pb_varint_field(6, 0)
                 + proto.pb_varint_field(7, 1))
        payload = (proto.pb_bytes(1, b"002708")
                   + proto.pb_bytes(2, plate)
                   + proto.pb_varint_field(4, 9))
        d = proto.parse_stock_related_plate_resp(payload)
        assert d["stock_id"] == "002708" and d["max_size"] == 9
        assert d["plates"][0]["plate_id"] == "801464"
        assert d["plates"][0]["plate_name"] == "机器人"
        assert d["plates"][0]["qz_type"] == 1

    def test_parsers_tolerate_truncated_payload(self):
        # fail-visible：乱码/截断宽容解析不出异常（同 parse_pb 宽容模式）
        for parser in (proto.parse_stock_zt_big_order_resp,
                       proto.parse_bf_reason_resp,
                       proto.parse_abnormal_price_resp,
                       proto.parse_stock_related_plate_resp):
            d = parser(b"\xff\xff\xff")
            assert isinstance(d, dict) and "raw_len" in d


class TestSubReqs211:
    """211 SubReqs 批量订阅信封（2026-11-17 P0，Base.java 描述符合同）。"""

    def test_build_sub_reqs_pb_bytes(self):
        items = [{"seqId": 7, "cmd": 2103, "version": 0, "codec": 0,
                  "subId": 2103, "data": b"\x08\x08"}]
        pb = proto.build_sub_reqs_pb(items)
        # reqs=f1 LEN；Item 内 f1..f5 varint + f20 LEN（tag=a2 01 两字节）
        assert pb[0] == 0x0A                      # f1 wire2
        assert pb[2] == 0x08 and pb[3] == 7       # seqId=7
        assert pb[4] == 0x10 and pb[5] == 0xB7 and pb[6] == 0x10  # cmd=2103
        assert b"\xa2\x01\x02\x08\x08" in pb      # f20 data
        back = proto.parse_sub_reqs_pb(pb)
        assert back == items

    def test_build_multi_items_roundtrip(self):
        items = [
            {"seqId": 1, "cmd": 2114, "version": 0, "codec": 0, "subId": 2114, "data": b""},
            {"seqId": 2, "cmd": 2203, "version": 3, "codec": 1, "subId": 99,
             "data": b"\x0a\x06600001"},
        ]
        assert proto.parse_sub_reqs_pb(proto.build_sub_reqs_pb(items)) == items

    def test_parse_tolerates_garbage(self):
        assert proto.parse_sub_reqs_pb(b"") == []
        assert proto.parse_sub_reqs_pb(b"\xff\xff") == []
        # 缺位字段补 0/空（宽容模式）
        out = proto.parse_sub_reqs_pb(proto.pb_bytes(1, proto.pb_varint_field(2, 2116)))
        assert out == [{"seqId": 0, "cmd": 2116, "version": 0, "codec": 0,
                        "subId": 0, "data": b""}]


class TestUnsubIdReq402:
    def test_build_nonpacked_roundtrip(self):
        pb = proto.build_unsub_id_req_pb([7, 300])
        assert pb == proto.pb_varint_field(1, 7) + proto.pb_varint_field(1, 300)
        assert proto.parse_unsub_id_req_pb(pb) == [7, 300]

    def test_parse_packed_compat(self):
        packed = proto.pb_bytes(1, proto.encode_varint(5) + proto.encode_varint(9))
        assert proto.parse_unsub_id_req_pb(packed) == [5, 9]

    def test_parse_empty(self):
        assert proto.parse_unsub_id_req_pb(b"") == []


class TestExtAttrs:
    """ext 属性线类型（App SocketReaderThread：key1=8B/key2=2B/key3=len2+bytes/key4=4B）。"""

    def test_attr2_subid_two_bytes_be(self):
        # z6.c(int) 只写 2 字节 BE——与现行订阅 ext `02 <cmd BE>` 逐字节同构
        ext = proto.encode_ext_attrs({2: 3006})
        assert ext == bytes.fromhex("020bbe")
        assert proto.parse_ext_attrs(ext) == {2: 3006}

    def test_attr3_topic_string(self):
        ext = proto.encode_ext_attrs({3: b"hq|1:20030/3006-0/"})
        assert ext[0] == 3
        assert proto.parse_ext_attrs(ext) == {3: b"hq|1:20030/3006-0/"}
        # str 输入按 utf-8 编码
        assert proto.encode_ext_attrs({3: "ab"}) == bytes.fromhex("0300026162")

    def test_mixed_attrs_sorted_roundtrip(self):
        attrs = {4: 0x01020304, 2: 211, 3: b"t", 1: 2**40}
        ext = proto.encode_ext_attrs(attrs)
        assert ext[0] == 1 and ext[9] == 2     # key 升序
        assert proto.parse_ext_attrs(ext) == attrs

    def test_unknown_key_fail_visible(self):
        with pytest.raises(proto.FrameDecodeError):
            proto.encode_ext_attrs({9: 1})
        with pytest.raises(proto.FrameDecodeError):
            proto.parse_ext_attrs(bytes.fromhex("0900"))

    def test_truncated_fail_visible(self):
        for bad in (bytes.fromhex("0200"), bytes.fromhex("0300056162"),
                    bytes.fromhex("0100"), bytes.fromhex("040000")):
            with pytest.raises(proto.FrameDecodeError):
                proto.parse_ext_attrs(bad)


class TestFrameParseExtensions:
    def test_echo_frame_ext_captured(self):
        ext = bytes.fromhex("0208370300026162")   # attr2=2103 + attr3="ab"
        body = (42).to_bytes(2, "big") + (2103).to_bytes(2, "big") \
            + b"\x01" + len(ext).to_bytes(2, "big") + ext + b"\xaa\x00"
        fr = proto.parse_incoming(bytes([0x40]) + len(body).to_bytes(4, "big") + body)
        assert fr["fmt"] == "echo" and fr["kind"] == 4
        assert fr["seq"] == 42 and fr["ext"] == ext
        assert proto.parse_ext_attrs(fr["ext"]) == {2: 2103, 3: b"ab"}

    def test_unsub_ack_pkg_0x50(self):
        payload = b"\xaa" + proto.build_unsub_id_req_pb([7])
        body = (9).to_bytes(2, "big") + (402).to_bytes(2, "big") + b"\x01" \
            + (0).to_bytes(2, "big") + payload
        fr = proto.parse_incoming(bytes([0x50]) + len(body).to_bytes(4, "big") + body)
        assert fr["fmt"] == "unsub_ack" and fr["kind"] == 5 and fr["cmd"] == 402

    def test_heartbeat_pkg_0x10(self):
        fr = proto.parse_incoming(bytes([0x10]) + (2).to_bytes(4, "big") + b"\x00\x01")
        assert fr["fmt"] == "heartbeat" and fr["kind"] == 1

    def test_push_ext_raw_preserved(self):
        ext = bytes.fromhex("020bbe")   # 二进制 topic（utf-8 replace 有损）
        body = len(ext).to_bytes(2, "big") + ext + (3006).to_bytes(2, "big") \
            + b"\x01" + (0).to_bytes(2, "big") + b"\xaa"
        fr = proto.parse_incoming(bytes([0x60]) + len(body).to_bytes(4, "big") + body)
        assert fr["ext_raw"] == ext
