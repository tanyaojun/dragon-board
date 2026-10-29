# -*- coding: utf-8 -*-
"""TDX 日线取数（题材龙头链共用：后日溢价结算 + 空间龙一推导的 10 日涨幅）。

坑位记录（2026-10-26 实测，均为生产级）：
1. **SetupCmd3 握手补丁必须打**：tdxpy 原始 setup 连发 SetupCmd1/2/3，其中 Cmd3 携带
   旧版「招商证券金钻」客户端标识——通达信官方现行主站对该标识软拒绝（连接成功但
   quotes/bars 返空）。81 节点全池返空、逐节点也无异常，就是没打补丁的症状。
   补丁与 python-bridge/main.py 同款（只发 Cmd1+2），`TDX_KEEP_TDXPY_SETUP3=1` 回退。
2. **直连 tdxpy，不走 mootdx Quotes**：mootdx 的 DataFrame 装饰在当前版本报
   `cannot insert datetime, already exists`（pandas 列冲突），绕开。
3. 原始价**未复权**：T→T+2 窗口内除权除息会失真（罕见，消费方如实声明不伪装精确）。
"""
from __future__ import annotations

import json
from pathlib import Path

TDX_HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")

# 进程内缓存：历史日线不随时间变化（除权回补除外，罕见且可接受），同 (code, offset) 不重拉。
# key=(code, offset)；值=bars dict 或 None（拉不到，负缓存防全池重扫拖垮挂链）。
_BARS_CACHE: dict[tuple[str, int], dict[str, dict] | None] = {}


def _setup_no3(api) -> None:   # pragma: no cover - 网络协议层，真机验证
    from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2
    SetupCmd1(api.client).call_api()
    SetupCmd2(api.client).call_api()


def _market_of(code: str) -> int:
    return 1 if str(code).startswith(("6", "9")) else 0


def fetch_daily_bars(code: str, offset: int = 15, max_probe: int = 15,
                     use_cache: bool = True) -> dict[str, dict] | None:
    """TDX 日线 → {"YYYY-MM-DD": {"open": f, "close": f}}；全池探测至出数。

    拉不到返回 None（负缓存，fail-visible 由调用方决定跳过口径）；节点池探测上限
    `max_probe` 个，防全池死节点拖垮挂链（15×5s≈75s 上限）。
    """
    key = (str(code), int(offset))
    if use_cache and key in _BARS_CACHE:
        return _BARS_CACHE[key]

    def _setup(self):
        _setup_no3(self)

    from tdxpy.hq import TdxHq_API
    TdxHq_API.setup = _setup
    pool = json.loads(TDX_HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
    market = _market_of(code)
    last_err: Exception | None = None
    for h in pool[:max_probe]:
        api = TdxHq_API()
        try:
            if not api.connect(h["ip"], int(h.get("port") or 7709), time_out=5):
                continue
            try:
                bars = api.get_security_bars(9, market, str(code), 0, offset)
            finally:
                api.disconnect()
            if bars:
                out = {f"{int(b['year']):04d}-{int(b['month']):02d}-{int(b['day']):02d}":
                       {"open": float(b["open"]), "close": float(b["close"])}
                       for b in bars}
                _BARS_CACHE[key] = out
                return out
            last_err = RuntimeError(f"{h['ip']} 空 K 线")
        except Exception as exc:   # 单节点失败换下一个
            last_err = exc
    _BARS_CACHE[key] = None
    return None


def gain10_from_bars(bars: dict[str, dict] | None, end_date: str,
                     window: int = 10) -> float | None:
    """截至 `end_date` 的 N 交易日收盘涨幅（%）：C(end)/C(endo−window) − 1。

    样本不足 window+1 根 → None（不伪造）；end 当日尚未收盘的 bar 也参与（调用方
    保证在收盘后调用，与 17:30 挂链时点一致）。
    """
    if not bars:
        return None
    series = [v["close"] for d, v in sorted(bars.items()) if d <= end_date]
    if len(series) < window + 1:
        return None
    base = series[-(window + 1)]
    if not base:
        return None
    return round((series[-1] / base - 1) * 100, 2)


def fetch_gains10(codes, end_date: str, window: int = 10) -> dict[str, float | None]:
    """批量 10 日涨幅：{code: gain%}；拉不到的 code 值为 None（fail-visible 由调用方处置）。"""
    return {c: gain10_from_bars(fetch_daily_bars(c), end_date, window) for c in codes}
