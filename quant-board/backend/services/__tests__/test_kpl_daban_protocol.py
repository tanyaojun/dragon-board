# -*- coding: utf-8 -*-
"""kpl_daban_protocol 测试：pb 构造/解析全部离线（零真实连接/adb/真 jev 红线）。

样本字节按 service_hq_daban.proto 合同手工构造（2026-10-27 逆向自主 dex）。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services import kpl_daban_protocol as dp  # noqa: E402
from backend.services.kpl_socket_protocol import pb_bytes, pb_varint_field  # noqa: E402


def f32(v: float) -> bytes:
    return struct.pack("<f", v)


def tag(field: int, wire: int) -> bytes:
    return dp.parse_pb_f32.__globals__["struct"].pack  # noqa: 仅为提示——tag 用 varint 见下


def vtag(field: int, wire: int) -> bytes:
    """varint tag（field>=16 时两字节）。"""
    t = (field << 3) | wire
    out = bytearray()
    while True:
        b7 = t & 0x7F
        t >>= 7
        if t:
            out.append(b7 | 0x80)
        else:
            out.append(b7)
            return bytes(out)


def f32_field(field: int, v: float) -> bytes:
    return vtag(field, 5) + struct.pack("<f", v)


class TestReqBuilders:
    def test_market_energy_req(self):
        # QxMarketEnergyReq{f1 type=1} → 08 01
        assert dp.build_market_energy_req_pb(1) == b"\x08\x01"
        assert dp.build_market_energy_req_pb(0) == b"\x08\x00"

    def test_zt_situation_stock_req(self):
        # QxZtSituationStockReq{bsType=1, orderType=0, sortType=0}
        assert dp.build_zt_situation_stock_req_pb(1) == b"\x08\x01\x10\x00\x18\x00"

    def test_empty_req(self):
        assert dp.build_empty_req_pb() == b""


class TestZdStat:
    def test_parse_2114(self):
        # QxNewZDStatResp{date="2026-10-26", zdStat{zt=55,dt=25,realZt=52,realDt=23,rise=2252,down=680,
        #   zdList[{"涨停":55}]}}
        stat = (
            pb_varint_field(1, 55) + pb_varint_field(2, 25) + pb_varint_field(3, 52)
            + pb_varint_field(4, 23) + pb_varint_field(5, 2252) + pb_varint_field(6, 680)
            + pb_bytes(20, pb_bytes(1, "涨停".encode()) + pb_varint_field(2, 55))
        )
        body = pb_bytes(1, "2026-10-26".encode()) + pb_bytes(10, stat)
        out = dp.parse_zd_stat(body)
        assert out["date"] == "2026-10-26"
        st = out["zd_stat"]
        assert st["zt"] == 55 and st["dt"] == 25 and st["real_zt"] == 52 and st["real_dt"] == 23
        assert st["rise"] == 2252 and st["down"] == 680
        assert st["zd_list"] == {"涨停": 55}
        assert out["zd_stat_bx"] is None
        assert out["raw_len"] == len(body)

    def test_parse_2114_missing_stat_fail_visible(self):
        # 空/缺 zdStat：不伪装成功，字段显式 None
        out = dp.parse_zd_stat(b"")
        assert out["zd_stat"] is None and out["zd_stat_bx"] is None and out["date"] == ""


class TestMarketOverview:
    def test_parse_2115(self):
        # QxMarketOverviewResp{hsRatio(f)=0.55, hsMoney=9124052992, strong=52, qxStatus="中",
        #   forecastMoney="16232亿", forecastZf="-17.74%", drawbackNum=4}
        body = (
            f32_field(1, 0.55)
            + pb_varint_field(2, 9124052992)
            + pb_varint_field(11, 4)
            + pb_bytes(12, "16232亿".encode())
            + pb_bytes(13, "-17.74%".encode())
            + pb_varint_field(14, 52)
            + pb_bytes(10, "中".encode())
        )
        out = dp.parse_market_overview(body)
        assert out["hs_ratio"] == pytest.approx(0.55, abs=1e-6)
        assert out["hs_money"] == 9124052992
        assert out["drawback_num"] == 4
        assert out["forecast_money"] == "16232亿"
        assert out["forecast_zf"] == "-17.74%"
        assert out["strong"] == 52
        assert out["qx_status"] == "中"


class TestPlateStrength:
    def test_parse_2116_with_live_markets(self):
        # LiveMarkets（f20）：首页「封涨大减」事件流
        live = pb_bytes(1, "14:56:57".encode()) + pb_bytes(2, "春光科技 封涨大减 剩余封单1068万".encode()) + pb_varint_field(3, 1)
        trend = pb_bytes(1, "09:30".encode()) + pb_varint_field(2, 7)
        body = (
            pb_bytes(1, "2026-10-26".encode())
            + pb_bytes(10, trend)
            + pb_bytes(20, live)
        )
        out = dp.parse_plate_strength(body)
        assert out["day"] == "2026-10-26"
        assert out["plate_strength_trend"] == [{"time": "09:30", "num": 7}]
        assert out["live_markets"] == [{
            "time": "14:56:57",
            "msg": "春光科技 封涨大减 剩余封单1068万",
            "is_new": 1,
        }]
        assert out["loss_effect_trend"] == []
        assert out["market_qx_trend"] == []


class TestWeightPerfV2:
    def test_parse_2118(self):
        w = (
            pb_bytes(1, "603933".encode()) + pb_bytes(2, "睿能科技".encode())
            + f32_field(3, -2.72) + f32_field(4, -11.55)
            + pb_bytes(5, "存储/机器人概念".encode()) + pb_varint_field(6, 1)
        )
        idx = (
            pb_bytes(1, "801027".encode()) + pb_bytes(2, "银行".encode())
            + f32_field(3, 1.52) + pb_bytes(4, "601398".encode())
            + pb_bytes(5, "工商银行".encode()) + f32_field(6, 3.12)
        )
        body = (
            pb_bytes(3, w) + pb_bytes(4, "2026-10-26".encode()) + pb_varint_field(5, 4)
            + pb_bytes(10, idx)
        )
        out = dp.parse_weight_perf_v2(body)
        assert out["date"] == "2026-10-26"
        assert out["num"] == 4
        assert len(out["withdraw_list"]) == 1
        wd = out["withdraw_list"][0]
        assert wd["stock_id"] == "603933" and wd["stock_name"] == "睿能科技"
        assert wd["ratio"] == pytest.approx(-2.72, abs=1e-5)
        assert wd["max_ratio"] == pytest.approx(-11.55, abs=1e-4)
        assert out["rise_stock_list"][0]["index_name"] == "银行"
        assert out["rise_stock_list"][0]["stock_name"] == "工商银行"


class TestZtSituationV2:
    def test_parse_2119(self):
        # 情绪页实测值：一板40 二板8 三板6 四板1 高度0；破板率29.49%；
        # 昨日涨停今表现2.48% 连板今表现7.50% 破板今表现-4.87%
        body = (
            pb_varint_field(1, 40) + pb_varint_field(2, 8) + pb_varint_field(3, 6)
            + pb_varint_field(4, 0) + f32_field(5, 0.11) + f32_field(6, 0.67)
            + f32_field(7, 0.0) + f32_field(8, 29.49) + f32_field(9, 2.48)
            + f32_field(10, 7.50) + f32_field(11, -4.87)
            + pb_varint_field(13, 1) + f32_field(14, 1.0)
        )
        out = dp.parse_zt_situation_v2(body)
        assert out["first_plate"] == 40
        assert out["second_plate"] == 8
        assert out["third_plate"] == 6
        assert out["four_plate"] == 1
        assert out["high_plate"] == 0
        assert out["today_zb_ratio"] == pytest.approx(29.49, abs=1e-4)
        assert out["yesterday_zt_state"] == pytest.approx(2.48, abs=1e-5)
        assert out["yesterday_pb_state"] == pytest.approx(-4.87, abs=1e-4)


class TestZtStockList:
    def test_parse_2120(self):
        # 春光科技：price=113000(×10000)，ztTur 封单，state=回封标记（语义待实测对照）
        item = (
            pb_bytes(1, "603657".encode()) + pb_bytes(2, "春光科技".encode())
            + pb_varint_field(3, 1) + pb_varint_field(4, 2)
            + pb_varint_field(5, 113000) + f32_field(6, 10.0)
            + pb_varint_field(7, 1457) + pb_bytes(8, "专用设备".encode())
            + pb_varint_field(9, 1) + pb_bytes(10, "0".encode())
            + pb_bytes(11, "回封".encode()) + pb_varint_field(12, 10680000)
            + pb_varint_field(13, 50000000) + pb_varint_field(17, 300000000)
            + pb_bytes(18, "专用设备".encode())
        )
        body = (
            pb_varint_field(1, 1) + pb_varint_field(2, 0) + pb_varint_field(3, 0)
            + pb_bytes(4, "2026-10-26".encode()) + pb_varint_field(5, 55)
            + pb_bytes(10, item) + pb_varint_field(11, 0)
        )
        out = dp.parse_zt_stock_list(body)
        assert out["bs_type"] == 1
        assert out["total"] == 55
        assert out["day"] == "2026-10-26"
        it = out["items"][0]
        assert it["stock_id"] == "603657" and it["stock_name"] == "春光科技"
        assert it["price"] == 113000
        assert it["increase"] == pytest.approx(10.0, abs=1e-6)
        assert it["zt_tur"] == 10680000
        assert it["zt_state"] == "回封"

    def test_parse_2120_negative_main_net_amount(self):
        # mainNetAmount 为 int64 负值（主力净流出）→ 10 字节补码 varint 回绕还原
        neg = (1 << 64) - 532631043  # -532631043 的 uint64 回绕
        item = pb_bytes(1, "000001".encode()) + pb_bytes(2, "平安银行".encode()) + pb_varint_field(14, neg)
        body = pb_bytes(10, item)
        out = dp.parse_zt_stock_list(body)
        assert out["items"][0]["main_net_amount"] == -532631043


class TestWindVane:
    def test_parse_2126(self):
        up = (
            pb_bytes(1, "301314".encode()) + pb_bytes(2, "凡拓数创".encode())
            + f32_field(3, 10.43) + pb_bytes(4, "数据采集".encode())
        )
        dn = (
            pb_bytes(1, "301314".encode()) + pb_bytes(2, "某股".encode())
            + f32_field(3, -10.04) + pb_bytes(4, "AI视频".encode())
        )
        out = dp.parse_wind_vane(pb_bytes(1, up) + pb_bytes(2, dn))
        assert out["up"][0]["stock_name"] == "凡拓数创"
        assert out["up"][0]["increase"] == pytest.approx(10.43, abs=1e-5)
        assert out["down"][0]["plate"] == "AI视频"


class TestParserRegistry:
    def test_registry_covers_daban_cmds(self):
        for cmd in dp.DABAN_SUB_CMDS:
            assert cmd in dp.DABAN_RESP_PARSERS
        assert dp.DABAN_RESP_PARSERS[dp.CMD_ZT_STOCK_LIST] is dp.parse_zt_stock_list
        assert dp.DABAN_RESP_PARSERS[dp.CMD_ZT_STOCK_LIST_PB] is dp.parse_zt_stock_list

    def test_all_parsers_handle_garbage_fail_visible(self):
        # 宽容解析：乱码不抛异常、返回结构化空值（fail-visible 由调用方上报 raw）
        for parser in dp.DABAN_RESP_PARSERS.values():
            out = parser(b"\xff\xff\xff\xff\xff")
            assert isinstance(out, dict) and "raw_len" in out


# ── 2103 DaBanStockListReq/Resp（打板个股列表：竞价 8 / 即将涨停 0）────────────
# 2026-10-27 逆向：Req/Resp 字段号出自 Hq.java 描述符；quotas 列语义 =
# nn0.U() × assets/PatternDynamicQuota × PatternTitleVisibleArrayPosition 三方对齐。

def _daban_item(stock_id: str, name: str, quotas: list) -> bytes:
    body = pb_bytes(1, stock_id.encode()) + pb_bytes(2, name.encode())
    body += pb_varint_field(4, 1) + pb_varint_field(5, 0)   # financingTag=1, backZT=0
    body += pb_bytes(6, "风险".encode())
    for q in quotas:
        body += pb_bytes(100, q.encode())
    return body


class TestDabanStockList2103:
    def test_req_builder_app_baseline(self):
        # BiddingZTlQuotaPresenter 基线：pidType=8, orderType=18, sortType=1, index=0, count=30
        out = dp.build_daban_stock_list_req_pb(8)
        assert out == (b"\x08\x08" + b"\x10\x12" + b"\x18\x01" + b"\x20\x00" + b"\x28\x1e")
        assert dp.build_daban_stock_list_req_pb(0, count=100).endswith(b"\x28\x64")

    def test_parse_bidding_list(self):
        quotas = ["13.02亿", "10.01", "528.0万", "0.9", "966.7万",
                  "7.14", "10.01", "2.37亿", "09:25:00", "", "1",
                  "0.5", "机器人概念", "机器人概念\n海洋经济", "5280000",
                  "1234万", "3.2", "15.8亿"]
        payload = (
            pb_varint_field(1, 8) + pb_varint_field(2, 18) + pb_varint_field(3, 1)
            + pb_varint_field(4, 0) + pb_varint_field(5, 30)
            + pb_bytes(20, _daban_item("603028", "赛福天", quotas))
            + pb_varint_field(22, 181)
            + pb_bytes(23, b"2026-10-27")
        )
        out = dp.parse_daban_stock_list(payload)
        assert out["pid_type"] == 8
        assert out["max_size"] == 181
        assert out["date"] == "2026-10-27"
        it = out["items"][0]
        assert it["stock_id"] == "603028" and it["name"] == "赛福天"
        assert it["financing_tag"] == 1 and it["warn_tag"] == "风险"
        # 目录列语义（数值列转 float，非数值原样字符串）
        assert it["zt_buy_amount"] == "13.02亿"      # 带单位原样（不猜换算）
        assert it["bidding_pct"] == pytest.approx(10.01)
        assert it["bidding_net"] == "528.0万"
        assert it["bidding_amount"] == "966.7万"
        assert it["pct"] == pytest.approx(10.01)
        assert it["plate"] == "机器人概念\n海洋经济"
        assert it["price"] == pytest.approx(7.14)
        # fail-visible：全部原始列保留
        assert len(it["quotas"]) == 18

    def test_parse_about_to_zt_columns(self):
        quotas = ["", "", "", "", "", "9.87", "5.2", "", "", "", "", "1.2",
                  "", "低空经济", "", "3000万", "", ""]
        payload = pb_varint_field(1, 0) + pb_bytes(20, _daban_item("002078", "某股", quotas))
        it = dp.parse_daban_stock_list(payload)["items"][0]
        assert it["price"] == pytest.approx(9.87)
        assert it["pct"] == pytest.approx(5.2)
        assert it["speed"] == pytest.approx(1.2)
        assert it["plate"] == "低空经济"
        assert it["main_net"] == "3000万"
        # 未映射下标只进 raw quotas，不产生伪语义键
        assert "unknown" not in it and it["quotas"][0] == ""

    def test_parse_garbage_fail_visible(self):
        out = dp.parse_daban_stock_list(b"\xff\xff\xff\xff\xff")
        assert out["items"] == [] and "raw_len" in out

    def test_registry_has_2103(self):
        assert dp.DABAN_RESP_PARSERS[dp.CMD_DABAN_STOCK_LIST] is dp.parse_daban_stock_list
        assert dp.DABAN_LIST_PIDS == {8: "bidding", 0: "about_to_zt", 6: "wind_vane"}
