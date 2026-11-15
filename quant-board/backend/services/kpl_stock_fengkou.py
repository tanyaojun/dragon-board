# -*- coding: utf-8 -*-
"""KPL 最强风口协议层（apphq StockFengKData/GetFengKListBest，2026-11-15 逆向实弹）。

背景：KPL App「最强风口」个股强度榜（底部页签 早盘竞价/板块竞价/最强风口/尾盘抢筹/人气榜）
实为 H5 页 `web2/strongestTuyere.html`（apppage.longhuvip.com/w48/，跳转坐标 main_src
na0.java case 42 → wn1.H），数据合同自 H5 JS（strongestTuyere.js reqZQFK，2026-11-15
拉取 w48 实页核对）：

- POST https://apphq.longhuvip.com/w1/api/index.php
  c=StockFengKData&a=GetFengKListBest&Time=<HHMM|空>（+ 公共凭据，单一事实源
  KPL_APP_BASE_PARAMS）；历史回看 H5 走 apphis 域 + Day=YYYYMMDD（RequestUrl3），
  实测（2026-11-15）apphis 该端点裸参数/带凭据均 1020 参数出错——历史合同待
  有效凭据后同屏核对，本层按 H5 原样透传并 fail-visible。
- 响应 {State, Day("Y-M-D"), Time(epoch), Tip, List:[[...]...], errcode}；
  State=0 → 「开通功能」付费墙（H5 state_tip2 弹窗），fail-visible 不伪装空榜。
- 行 13 位语义（H5 getRangeLi_fk 逐位逆向，位置即上游顺序）：
  [0]代码 [1]名称 [2]强度 [3]涨跌状态(int,>0↑/<0↓/0无) [4]涨跌幅% [5]主力净额
  [6]未渲染（语义未确认，不猜） [7]名称标红标志（truthy→红名，疑涨停，未确认）
  [8]主力买 [9]主力卖 [10]精选板块（「、」分隔） [11]强度峰值时间(epoch秒→HH:MM)
  [12]热点板块（「、」分隔，与[10]交集→App「热」角标）。
  App 排序键（turnSort_fk）：1=[11] 2=[2,5] 3=[4,5] 5=[5] 6=[8] 7=[9]。
- **端点要求登录态**（errcode 1001「登录状态失效」）：付费/登录校验端点；凭据不入代码
  （红线 §1.2.3），只进 quant-board/.env.local（QUANT_BOARD_KPL_APP_USERID/_DEVICEID/
  _TOKEN），公共出口 KPL_APP_BASE_PARAMS 从环境变量组装；2026-11-15 换绑后实弹验证
  State=1（最强风口已开通）；实测「实时」档返回最近交易日全量快照（Time=当日请求时点，
  Day=最近交易日），App 时间滑条=取该日内 Time 点位快照。

频控预算（红线 9）：读口单发、30s TTL 进程内缓存、无重试循环（失败即结构化降级，
不退避不连发）；前端 60s 轮询 × 30s TTL = 实时档 ≤1 发/分钟，历史档切日单发。

pytest 纪律：parse 纯函数全 mock；fetch 仅运维路径真实调用（红线 7，_pytest_guard）。
凭据仅进请求参数，不落库不落日志（红线 §1.2.3）。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from backend.services.kpl_ranking_service import (
    _UA_STOCKS,
    KplRankingError,
    _check_errcode,
    _post_form,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

_HOST_HQ = "https://apphq.longhuvip.com/w1/api/index.php"    # API_HQ（实时档）
_HOST_HIS = "https://apphis.longhuvip.com/w1/api/index.php"  # API_HISTORY（历史档，合同未核实）

_CACHE: Dict[tuple, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()   # 并发 miss 串行化：同键只发一次上游（预算：≤1 发/分钟）
_CACHE_TTL_SECONDS = 30.0

# 行 13 位 → 具名字段（顺序即上游顺序；6/7 位语义未确认，不猜、原样保留）
FENGKOU_ROW_FIELDS: tuple[tuple[int, str, str], ...] = (
    (0, "stock_id", "代码"),
    (1, "name", "名称"),
    (2, "strength", "强度"),
    (3, "trend_state", "涨跌状态"),
    (4, "change_pct", "涨跌幅%"),
    (5, "main_net", "主力净额"),
    (6, "unknown6", "未确认位6"),
    (7, "name_red_raw", "名称标红标志"),
    (8, "main_buy", "主力买"),
    (9, "main_sell", "主力卖"),
    (10, "boards_raw", "精选板块"),
    (11, "peak_time", "强度峰值时间"),
    (12, "hot_boards_raw", "热点板块"),
)


def _global_params() -> Dict[str, Any]:
    """公共参数（凭据单一事实源=KPL_APP_BASE_PARAMS；apphq 组合与 gene 端点实测一致）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w38", "VerSion": "5.16.0.5", "PhoneOSNew": "2", **creds}


def _real_post_form() -> bool:
    """`_post_form` 是否仍为生产实现（未被测试 monkeypatch）——pytest 护栏判据。"""
    return getattr(_post_form, "__module__", "") == "backend.services.kpl_ranking_service"


def _pytest_guard() -> None:
    """硬护栏：pytest 进程内禁止真实调用上游（红线 7：测试全 mock）。"""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST") and _real_post_form():
        raise RuntimeError(
            "pytest 禁止真实调用 KPL 上游 HTTP（红线 7）：请 monkeypatch _post_form 或注入 fetcher")


def fetch_fengkou_raw(time_hhmm: str = "", day: str = "") -> Dict[str, Any]:
    """最强风口原始响应（30s TTL 缓存；真实调用仅运维路径，pytest 全 mock）。

    time_hhmm：App「恢复实时」前的时间滑条值（HHMM 字符串，空=实时最新）；
    day：历史日 YYYYMMDD 或 YYYY-MM-DD（统一去划线后缓存/上游，避免同日两条缓存键）。
    """
    day = str(day or "").replace("-", "")
    key = (str(time_hhmm or ""), day)
    with _CACHE_LOCK:   # 锁包住 miss→fetch→写缓存段：并发同键请求只发一次上游
        cached = _CACHE.get(key)
        if cached and time.time() - cached["ts"] < _CACHE_TTL_SECONDS:
            return cached["data"]
        _pytest_guard()
        if len(_CACHE) >= 64:
            _CACHE.clear()
        params: Dict[str, Any] = {"a": "GetFengKListBest", "c": "StockFengKData",
                                  "Time": str(time_hhmm or ""), **_global_params()}
        host = _HOST_HQ
        if day:
            # H5 历史：RequestUrl3(apphis) + Day=YYYYMMDD（入参允许 YYYY-MM-DD，统一去划线）；
            # apphis 实测 1020（合同未核实）
            params["Day"] = day
            host = _HOST_HIS
        data = _post_form(host, params, _UA_STOCKS)
        _check_errcode(data)
        _CACHE[key] = {"ts": time.time(), "data": data}
        return data


def _epoch_hhmm(v: Any) -> Optional[str]:
    """epoch 秒 → "HH:MM"（App 代码旁时间角标口径）；非数值/<=0 → None（不猜）。"""
    try:
        ts = int(float(v))
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    tm = time.localtime(ts)
    return f"{tm.tm_hour:02d}:{tm.tm_min:02d}"


def _num(v: Any) -> Any:
    return v


def _split_bangs(v: Any) -> List[str]:
    """「、」分隔板块串 → 列表（空串/非串 → []）。"""
    if not isinstance(v, str) or not v.strip():
        return []
    return [p.strip() for p in v.split("、") if p.strip()]


def parse_fengkou_row(row: List[Any]) -> Dict[str, Any]:
    """单行 13 位 → 具名字段 + raw 原样保留（缺位不补 0，partial 标记 fail-visible）。"""
    named: Dict[str, Any] = {}
    missing: List[str] = []
    for idx, name, _label in FENGKOU_ROW_FIELDS:
        val = row[idx] if idx < len(row) else None
        if val is None or isinstance(val, (dict, list)):
            named[name] = None
            missing.append(name)
        else:
            named[name] = val
    boards = _split_bangs(named.pop("boards_raw"))
    hot = _split_bangs(named.pop("hot_boards_raw"))
    out: Dict[str, Any] = {
        "stock_id": str(named.get("stock_id") or ""),
        "name": str(named.get("name") or ""),
        "strength": _num(named.get("strength")),
        "trend_state": named.get("trend_state"),
        "change_pct": _num(named.get("change_pct")),
        "main_net": _num(named.get("main_net")),
        "unknown6": named.get("unknown6"),           # 未确认位，原样保留不猜语义
        "name_red": bool(named.get("name_red_raw")),  # truthy→红名（疑涨停，语义未确认）
        "main_buy": _num(named.get("main_buy")),
        "main_sell": _num(named.get("main_sell")),
        "boards": boards,                              # 精选板块（App 最多展示前 2）
        "hot_boards": hot,                             # 热点板块（∩boards → 「热」角标）
        "peak_time": _epoch_hhmm(named.get("peak_time")),
        "raw": list(row),
        "raw_len": len(row),
    }
    if missing:
        out["partial"] = True
        out["missing_fields"] = missing
    return out


def parse_fengkou(data: Dict[str, Any]) -> Dict[str, Any]:
    """响应 {State, Day, Time, Tip, List} → 结构化载荷；State=0 → 付费墙 fail-visible。"""
    state = data.get("State")
    day = str(data.get("Day") or "")
    tip = str(data.get("Tip") or "")
    if state == 0 or str(state) == "0":
        # 「开通功能」付费墙：App 弹窗口径原样透出（不伪装空榜/不用旧日档冒充）
        return {"ok": False, "degraded": True, "reason": "vip_locked",
                "error": tip or "上游返回 State=0（开通功能付费墙）",
                "state": state, "day": day, "items": [], "raw": None}
    rows = data.get("List")
    if not isinstance(rows, list):
        return {"ok": False, "degraded": True, "reason": "unexpected_payload",
                "error": f"List 非数组（{type(rows).__name__}）",
                "state": state, "day": day, "items": [], "raw": rows}
    items = [parse_fengkou_row(r) for r in rows if isinstance(r, list) and r]
    return {
        "ok": True,
        "day": day,
        "time": data.get("Time"),
        "time_hhmm": _epoch_hhmm(data.get("Time")),
        "tip": tip,
        "state": state,
        "items": items,
        "n_rows": len(items),
        "partial_n": sum(1 for it in items if it.get("partial")),
        "raw_rows": rows,
    }


def get_fengkou(time_hhmm: str = "", date: str = "") -> Dict[str, Any]:
    """读口：{ok, day, time, items, ...}；fail-visible 结构化降级（登录态/付费墙/上游）。"""
    day = str(date or "").replace("-", "")
    try:
        raw = fetch_fengkou_raw(time_hhmm=time_hhmm, day=day)
    except KplRankingError as exc:
        detail = getattr(exc, "detail", {}) or {}
        code = str(detail.get("errorCode") or getattr(exc, "reason", "") or "kpl_errcode")
        return {"ok": False, "degraded": True,
                "reason": code[:60],
                "error": str(detail.get("error") or exc)[:160],
                "day": day or None, "items": [], "raw": None,
                # 登录态类错误（1001/1016）单独透出，前端提示凭据失效
                "login_expired": code in ("1001", "1016")}
    except Exception as exc:   # HTTP/网络层异常 → 结构化降级（不伪装空榜）
        if isinstance(exc, RuntimeError) and "红线 7" in str(exc):
            raise   # pytest 护栏必须响亮失败，不得吞成降级载荷静默通过
        return {"ok": False, "degraded": True, "reason": type(exc).__name__,
                "error": str(exc)[:160], "day": day or None, "items": [], "raw": None}
    return parse_fengkou(raw)
