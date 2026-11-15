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

# 覆盖式渐进 offset 阶梯（2026-11-16 自 leader_wzs 下沉为单源）：15≈近3周 → 250≈近1年；
# 命中即停。同进程多日回填时各档位全部进 _BARS_CACHE，首日后零网络。
_BAR_OFFSET_LADDER: tuple[int, ...] = (15, 40, 80, 160, 250)


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
            # 连接成功 ≠ 可用：get_security_bars 无内置超时，坏节点 recv 可永久
            # 挂起（实测 2026-11-02 回填整链卡死）。socket 级超时兜底，超时抛异常
            # 走下一节点（与 connect 失败同路）。
            api.client.settimeout(10)
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


def bars_covering(code: str, end_date: str,
                  min_dates: int = 1,
                  offsets: tuple[int, ...] | None = None) -> dict[str, dict] | None:
    """覆盖 `end_date` 的日线（含其前至少 min_dates 根）；不覆盖 → 最后一次结果。

    **深历史回填必经此入口**（2026-11-16 用户裁决）：`fetch_daily_bars` 默认只取
    最近 15 根，对距今 >4 个交易日的历史日，≤end_date 的棒不足 → gain10/当日涨幅
    全 None → v5 空间龙一全板块被误判「TDX 日线不可用」跳过（11-12 00:27 回填把
    ≤11-04 板块节点档清空的根因）。offsets 缺省阶梯式（15→…→250，逐档重试，每档
    一次 TDX 连接）；深历史全量回填可传单档大 offset（如 (250,)）。
    """
    last: dict[str, dict] | None = None
    for off in (offsets or _BAR_OFFSET_LADDER):
        bars = fetch_daily_bars(str(code)[-6:], offset=off)
        last = bars
        if bars:
            covered = sorted(d for d in bars if d <= end_date)
            if len(covered) >= min_dates:
                return bars
    return last


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


def fetch_gains10(codes, end_date: str, window: int = 10,
                  offsets: tuple[int, ...] | None = None) -> dict[str, float | None]:
    """批量 10 日涨幅：{code: gain%}；拉不到的 code 值为 None（fail-visible 由调用方处置）。

    走覆盖式日线（bars_covering，min_dates=window+1）：当日链在首档 15 根即命中
    （零额外成本）；历史回填日自动升档，不再把深日期误判「TDX 日线不可用」。
    """
    return {c: gain10_from_bars(bars_covering(c, end_date, min_dates=window + 1,
                                              offsets=offsets),
                                end_date, window) for c in codes}


def covering_day_change_fetcher(codes, date: str,
                                offsets: tuple[int, ...] | None = None) -> dict[str, float | None]:
    """当日涨跌幅%（close vs 前收，覆盖式；2026-11-16 自 leader_wzs 下沉单源）。

    断板候选跌停剔除用；当日不在轴/前收缺失 → None（调用方不剔除，不猜）。
    与 bars_covering 同一 (code, offset) 缓存。
    """
    out: dict[str, float | None] = {}
    for c in codes:
        out[c] = None
        bars = bars_covering(c, date, min_dates=2, offsets=offsets)
        if not bars or date not in bars:
            continue
        ds = sorted(bars)
        i = ds.index(date)
        if i == 0:
            continue
        pc, cc = bars[ds[i - 1]].get("close"), bars[date].get("close")
        if pc and cc:
            out[c] = round((cc / pc - 1) * 100, 2)
    return out
