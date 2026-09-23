r"""通达信官方行情主站协议变体探测（隔离研究探针，不进生产链路）。

背景（2026-09-23）：
- 官方双线主站（connect.cfg [HQHOST] 48 个）TCP 可达，但对 tdxpy 裸协议的
  get_security_quotes/bars 返回 4 字节空响应（zip_size=unzip_size=4），
  而 get_security_count / get_minute_time_data 正常返回——命令级软拒绝。
- 本探针系统化穷举 tdxpy 请求帧的可变字段（flags/压缩位/版本字节/种子/
  握手开关/命令字邻域），观察是否存在能让官方主站返回真实行情的变体。
- 每个变体都在国泰君安老主站上做对照：若 GTJA 也失败说明帧本身非法，
  不能归因为官方拒绝行为变化。

运行：
    python python-bridge/research/tdx_official_protocol_probe.py
"""

import struct
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tdxpy.hq import TdxHq_API  # noqa: E402

OFFICIAL_IP = "129.204.230.128"  # 通达信深圳双线主站7（connect.cfg现行表）
GTJA_IP = "117.34.114.20"  # 国泰君安（tdxpy协议兼容对照组）
PORT = 7709


def build_quotes_frame(
    stocks=((0, b"000001"),),
    flags=0x010C,
    seed=0x6320,
    zip_flag=0x0200,
    cmd=0x053E,
    cmd_high=0x05,
    count_override=None,
):
    """按 GetSecurityQuotesCmd.setParams 的格式构建请求帧，允许变体注入。"""
    stock_list = [(m, c.encode() if isinstance(c, str) else c) for m, c in stocks]
    stock_len = len(stock_list)
    pkgdatalen = stock_len * 7 + 12
    val = (
        flags,
        (zip_flag << 16) | seed,
        pkgdatalen,
        pkgdatalen,
        (cmd_high << 16) | cmd,
        0,
        0,
        stock_len if count_override is None else count_override,
    )
    pkg = bytearray(struct.pack("<HIHHIIHH", *val))
    for market, code in stock_list:
        pkg.extend(struct.pack("<B6s", market, code))
    return bytes(pkg)


def send_raw(ip, frame, with_setup=True, timeout=4.0):
    """连接并发送原始帧，返回 (ok, body_bytes_or_hex, err)。"""
    api = TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=False)
    try:
        api.connect(ip, PORT, time_out=timeout)
        api.need_setup = False  # connect 时已按需执行过 setup；此行防重复
        if not with_setup:
            # 已在 connect 里发送过 SetupCmd1/2/3，无法撤销；改为新建不带 setup 的连接
            api.disconnect()
            api = TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=False)
            api.setup = lambda: None  # 屏蔽握手
            api.connect(ip, PORT, time_out=timeout)
        body = api.send_raw_pkg(frame)
        return True, bytes(body), ""
    except Exception as exc:  # noqa: BLE001
        return False, b"", f"{type(exc).__name__}: {exc}"
    finally:
        try:
            api.disconnect()
        except Exception:  # noqa: BLE001
            pass


def probe_variant(name, frame, with_setup=True, control=True):
    """官方探测 + GTJA 对照，返回结果行。"""
    ok_o, body_o, err_o = send_raw(OFFICIAL_IP, frame, with_setup=with_setup)
    ok_g, body_g, err_g = (True, b"", "")
    if control:
        ok_g, body_g, err_g = send_raw(GTJA_IP, frame, with_setup=with_setup)
    verdict = "HIT!" if (ok_o and len(body_o) > 4) else "refused"
    row = {
        "exp": name,
        "official": f"{'OK' if ok_o else 'ERR'} len={len(body_o)} {body_o[:16].hex() or ''}{err_o}",
        "gtja": f"{'OK' if ok_g else 'ERR'} len={len(body_g)}{err_g}",
        "verdict": verdict,
    }
    return row


def main():
    rows = []

    def run(name, frame, **kw):
        try:
            row = probe_variant(name, frame, **kw)
        except Exception:  # noqa: BLE001
            row = {"exp": name, "official": "PROBE_ERR", "gtja": "-", "verdict": traceback.format_exc()[-200:]}
        rows.append(row)
        print(f"[{row['verdict']:>7}] {name}\n         official: {row['official']}\n         gtja    : {row['gtja']}")
        time.sleep(0.2)

    std1 = build_quotes_frame()

    # E1 基线（含 SetupCmd1/2/3 握手，tdxpy 默认行为）
    run("E1 baseline quotes frame", std1)

    # E2/E3 握手变体
    run("E2 no-setup handshake", std1, with_setup=False)
    run("E3 multi-stock 3codes(深000001/深399001/沪600036)",
        build_quotes_frame(stocks=((0, "000001"), (0, "399001"), (1, "600036"))))

    # E4 flags 变体（首 ushort）
    for f in (0x000C, 0x020C, 0x030C, 0x010D, 0x0102):
        run(f"E4 flags=0x{f:04X}", build_quotes_frame(flags=f), control=False)

    # E5 压缩位变体（第二 dword 高 16 位）
    for z in (0x0000, 0x0100, 0x0300):
        run(f"E5 zipflag=0x{z:04X}", build_quotes_frame(zip_flag=z), control=False)

    # E6 cmd dword 高字节（疑似协议版本号 0x05）
    for h in (0x00, 0x01, 0x04, 0x06, 0x07):
        run(f"E6 cmdHigh=0x{h:02X}", build_quotes_frame(cmd_high=h), control=(h == 0x00))

    # E7 种子变体
    for s in (0x0000, 0x1234):
        run(f"E7 seed=0x{s:04X}", build_quotes_frame(seed=s), control=False)

    # E8 命令字邻域扫描（quotes 载荷）
    for cmd in (0x053C, 0x053D, 0x053F, 0x0540, 0x0541, 0x0542, 0x2001, 0x2101, 0x2111):
        run(f"E8 cmd=0x{cmd:04X}", build_quotes_frame(cmd=cmd), control=False)

    # E9/E10 握手拆分（API 级）：2026-09-23 突破点——
    # SetupCmd3 携带旧版"招商证券金钻"客户端标识串，官方主站据此软拒绝 quotes/bars；
    # 只发 SetupCmd1+2 时官方主站行情/K线/指数全部正常（GTJA 对照亦正常）。
    from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2, SetupCmd3

    def api_probe(ip, setup_fn, fn_name, **fn_args):
        api = TdxHq_API(heartbeat=False, auto_retry=False, raise_exception=False)
        try:
            if setup_fn is not None:
                api.setup = lambda: setup_fn(api.client)
            api.connect(ip, PORT, time_out=4)
            result = getattr(api, fn_name)(**fn_args)
            return "EMPTY" if not result else f"DATA {len(result)}条"
        except Exception as exc:  # noqa: BLE001
            return f"ERR {type(exc).__name__}"
        finally:
            try:
                api.disconnect()
            except Exception:  # noqa: BLE001
                pass

    e9 = lambda ip: api_probe(ip, lambda c: (SetupCmd1(c).call_api(), SetupCmd2(c).call_api()),  # noqa: E731
                              "get_security_quotes", all_stock=[(0, "000001")])
    e10 = lambda ip: api_probe(ip, lambda c: SetupCmd3(c).call_api(),  # noqa: E731
                               "get_security_quotes", all_stock=[(0, "000001")])
    rows.append({"exp": "E9 setup1+2无3", "official": e9(OFFICIAL_IP), "gtja": e9(GTJA_IP),
                 "verdict": "HIT!" if "DATA" in e9(OFFICIAL_IP) else "refused"})
    rows.append({"exp": "E10 仅setup3", "official": e10(OFFICIAL_IP), "gtja": e10(GTJA_IP), "verdict": "refused"})
    for r in rows[-2:]:
        print(f"[{r['verdict']:>7}] {r['exp']}\n         official: {r['official']}\n         gtja    : {r['gtja']}")

    print("\n==== 结论 ====")
    hits = [r for r in rows if r["verdict"] == "HIT!"]
    print(f"变体总数 {len(rows)}, 官方返回数据(HIT) {len(hits)}")
    for h in hits:
        print("  HIT:", h["exp"], h["official"])


if __name__ == "__main__":
    main()
