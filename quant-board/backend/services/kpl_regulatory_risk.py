# -*- coding: utf-8 -*-
"""KPL 监管风险（严重异动/重点监控）协议层（2026-11-15 预登记 theme-leader-regulatory-risk）。

源：KPL App「开盘 › 异动提醒」页（严重异动/重点监控页签），纯 HTTP POST form（非 socket），
c=StockBidYiDong。反编译坐标：SevereAbnormalPresenter.java:232-246 / ox0.java:6876/6947 /
MonitorListAdapter.java:104-134；列序 2026-11-15 探针 8 发实弹与 App 截图交叉定档
（预登记文档 §2）。

端点（5 发/日预算，§1.2-9）：
- HQ  GetPianLiZhi_W46        当日 today+tomorrow 触发组（{Day,Time,List_Today,List_Tormorow}）
- HIS GetYDTPZFPL_W46         历史日触发组（Day；List_Tormorow 历史恒空=结构化空态）
- HIS GetYDTPZFPL_W46_HisAll  近期严重异动（Day,IsZT=0,Index 分页,st；日期降序；不用 IsZT 过滤，
                              客户端按 [15]/[16] 标志派生触发/停牌）
- HQ  GetYDTP_ZDJK_Today      监管期证券（{List}）
- HQ/HIS GetYDTP_ZDJK_His     历史监管证券（上游有限窗，给多少落多少，不伪造完整历史）

频控预算：日采 5 发（severe1+recent2+monitor2），**无重试**（部分端点失败当日定格+
reg_states 留痕；全源失败不写、下一轮自愈）；日预算上限 10 发（调用方 archiver/CLI 发弹前
门控）；计数入 kpl_api_calls calls.regulatory；串行间隔复用 _post_form 全局 ≥2s 锁 +
调用方源间 ≥3s。本模块只做 fetch/parse，落库由 kpl_daban_archiver regulatory lane 消费。

口径纪律：响应全为预格式化数值/字符串（百分比数值原样+%后缀、价格元原样、日期串原样），
不自算不反推；未钉死列（[13]/[19] 等）raw 留档不渲染；缺位 None 不补 0（AGENTS §4.0）。
pytest 纪律：parse 纯函数全 mock；fetch 仅运维/采集路径真实调用（红线 7）。
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

from backend.services.kpl_ranking_service import (
    _UA_STOCKS,
    _check_errcode,
    _post_form,
    KplRankingError,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

_HOST_HQ = "https://apphq.longhuvip.com/w1/api/index.php"    # API_HQ
_HOST_HIS = "https://apphis.longhuvip.com/w1/api/index.php"  # API_HISTORY

INTER_CALL_DELAY_SECONDS = 3.0   # 源间间隔（_post_form 全局 ≥2s 锁之上）
RECENT_PAGES = 2                 # 近期组日采页数（Index=0,1，日期降序 60 行覆盖近期窗）
# 预期日发数（预算门控预留用：severe1 + recent2 + monitor2；review m2）
REGULATORY_EXPECTED_CALLS = 1 + RECENT_PAGES + 2

# 周期标签形态（「10日100%」/「30日200%」）；近期组 [2] 可能是状态文本，须形态判别
PERIOD_RE = re.compile(r"^\d+日\d+%$")


def _global_params() -> Dict[str, Any]:
    """公共参数（凭据单一事实源=KPL_APP_BASE_PARAMS；组合同 kpl_stock_gene 实测）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w38", "VerSion": "5.16.0.5", "PhoneOSNew": "2", **creds}


def _real_post_form() -> bool:
    return getattr(_post_form, "__module__", "") == "backend.services.kpl_ranking_service"


def _pytest_guard() -> None:
    """硬护栏：pytest 进程内禁止真实调用上游（AGENTS 红线 7：测试全 mock）。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and _real_post_form():
        raise RuntimeError(
            "pytest 禁止真实调用 KPL 上游 HTTP（红线 7）：请 monkeypatch _post_form 或注入 fetcher")


def _cell(row: Any, idx: int) -> Any:
    """列取数：短行/非列表 → None（缺位保持缺失，不补 0）。"""
    if not isinstance(row, (list, tuple)) or idx >= len(row):
        return None
    v = row[idx]
    return None if isinstance(v, (dict, list)) else v


def _flag(v: Any) -> bool:
    return str(v) == "1"


def _date_or_none(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    return s if s and s != "0000-00-00" else None


# ── 解析（纯函数，列序定档见预登记 §2） ─────────────────────────────────────

def parse_trigger_row(row: Any, *, group: str) -> Dict[str, Any]:
    """触发组行（20 列）→ 具名字段 + raw 留档。group ∈ {"today","tomorrow"}。

    渲染列：涨幅[3]（明日组为占位 0，消费方不渲染）、触发涨幅[5]、价格[6]、
    偏离空间 today=[7]/tomorrow=[9]、周期[2]（[12]同值冗余）、连板标签[4]、监控标志[11]、板块[10]。
    未钉死列 [13]/[19] 仅 raw 留档。
    """
    space = _cell(row, 7) if group == "today" else _cell(row, 9)
    out: Dict[str, Any] = {
        "stock_id": str(_cell(row, 0) or ""),
        "stock_name": str(_cell(row, 1) or ""),
        "period": _cell(row, 2),
        "pct": _cell(row, 3),
        "streak_tag": str(_cell(row, 4) or "") or None,
        "trigger_pct": _cell(row, 5),
        "price": _cell(row, 6),
        "space_pct": space,
        "status_text": str(_cell(row, 8) or "") or None,
        "plate": str(_cell(row, 10) or "") or None,
        "monitor_flag": _flag(_cell(row, 11)),
        "raw": list(row) if isinstance(row, (list, tuple)) else row,
    }
    if not isinstance(row, (list, tuple)) or len(row) < 20:
        out["partial"] = True
    return out


def parse_recent_row(row: Any) -> Dict[str, Any]:
    """近期严重异动行（20 列）→ 已钉死字段 + raw 留档（未钉死数值列不渲染）。"""
    period = _cell(row, 2)
    out: Dict[str, Any] = {
        "stock_id": str(_cell(row, 0) or ""),
        "stock_name": str(_cell(row, 1) or ""),
        "period": period if isinstance(period, str) and PERIOD_RE.match(period) else None,
        "status_text": str(_cell(row, 8) or "") or None,
        "plate": str(_cell(row, 10) or "") or None,
        "monitor_flag": _flag(_cell(row, 11)),
        "triggered_flag": _flag(_cell(row, 15)),
        "suspended_flag": _flag(_cell(row, 16)),
        "resume_date": _date_or_none(_cell(row, 17)),
        "abnormal_date": _date_or_none(_cell(row, 18)),
        "raw": list(row) if isinstance(row, (list, tuple)) else row,
    }
    if not isinstance(row, (list, tuple)) or len(row) < 20:
        out["partial"] = True
    return out


def parse_monitor_row(row: Any) -> Dict[str, Any]:
    """监控组行（≥4 列）：代码/名称/监控开始/监控结束（hh0 显示映射实锤）。"""
    out: Dict[str, Any] = {
        "stock_id": str(_cell(row, 0) or ""),
        "stock_name": str(_cell(row, 1) or ""),
        "start_date": _date_or_none(_cell(row, 2)),
        "end_date": _date_or_none(_cell(row, 3)),
        "raw": list(row) if isinstance(row, (list, tuple)) else row,
    }
    if not isinstance(row, (list, tuple)) or len(row) < 4:
        out["partial"] = True
    return out


def build_regulatory_payload(raws: Dict[str, Any], states: Dict[str, dict],
                             *, date: Optional[str]) -> Dict[str, Any]:
    """raw 五组 → {date, groups, by_code, states}（纯函数）。

    groups：today/tomorrow/recent/monitor_current/monitor_history（解析后列表；
    端点失败组=None=缺失，与 errcode=0 空列表=真零严格区分）。
    by_code：代码索引 {monitor_current?, monitor_history?, recent[], today?, tomorrow?}。
    """
    groups: Dict[str, Any] = {
        "today": None, "tomorrow": None, "recent": None,
        "monitor_current": None, "monitor_history": None,
    }
    # fail-visible（review m4）：空代码行保留+no_code 标记（不静默丢）；
    # 非列表畸形行计数入 dropped（结构化暴露，raw 不伪造）。
    dropped: Dict[str, int] = {}

    def _list_rows(rows: Any, source: str) -> List[Any]:
        kept = []
        for r in rows or []:
            if isinstance(r, (list, tuple)):
                kept.append(r)
            else:
                dropped[source] = dropped.get(source, 0) + 1
        return kept

    def _mark(items: List[dict]) -> List[dict]:
        for it in items:
            if not it["stock_id"]:
                it["no_code"] = True
        return items

    sev = raws.get("severe")
    if isinstance(sev, dict):
        groups["today"] = _mark([parse_trigger_row(r, group="today")
                                 for r in _list_rows(sev.get("List_Today"), "today")])
        groups["tomorrow"] = _mark([parse_trigger_row(r, group="tomorrow")
                                    for r in _list_rows(sev.get("List_Tormorow"), "tomorrow")])
    recent_rows: List[Any] = []
    for key in sorted(k for k in raws if k.startswith("recent_")):
        payload = raws.get(key)
        if isinstance(payload, dict):
            recent_rows.extend(payload.get("List_His") or [])
    if any(isinstance(raws.get(k), dict) for k in raws if k.startswith("recent_")):
        seen = set()
        recent = []
        for r in _list_rows(recent_rows, "recent"):
            item = parse_recent_row(r)
            if not item["stock_id"]:
                item["no_code"] = True   # 空代码行保留不去重（无法安全判重）
                recent.append(item)
                continue
            key = (item["stock_id"], item["abnormal_date"])
            if key not in seen:
                seen.add(key)
                recent.append(item)
        groups["recent"] = recent
    for key, gname in (("monitor_current", "monitor_current"),
                       ("monitor_history", "monitor_history")):
        payload = raws.get(key)
        if isinstance(payload, dict):
            groups[gname] = _mark([parse_monitor_row(r)
                                   for r in _list_rows(payload.get("List"), gname)])
    by_code: Dict[str, dict] = {}

    def _slot(code: str) -> dict:
        return by_code.setdefault(code, {})

    for gname in ("monitor_current", "monitor_history", "today", "tomorrow"):
        for item in groups[gname] or []:
            if not item.get("no_code"):
                _slot(item["stock_id"])[gname] = item
    for item in groups["recent"] or []:
        if not item.get("no_code"):
            _slot(item["stock_id"]).setdefault("recent", []).append(item)
    return {"date": date, "groups": groups, "by_code": by_code, "states": states,
            "dropped": dropped}


# ── fetch（真实调用仅采集/运维路径；逐端点隔离，fail-visible） ────────────────

def fetch_regulatory_raw(date: Optional[str] = None, *,
                         recent_pages: int = RECENT_PAGES,
                         sleeper=time.sleep) -> Dict[str, Any]:
    """拉五组 raw。date=None=当日（HQ current）；date=历史日（HIS 变体）。

    返回 {raws, states, calls, day}：day=解析出的交易日（date 或 severe.Day）。
    逐端点 try/except 互不连带；recent 的 Day 依赖 severe.Day（severe 失败且无 date
    时 recent 结构化 skip，不猜日期）。
    """
    _pytest_guard()
    raws: Dict[str, Any] = {}
    states: Dict[str, dict] = {}
    calls = 0

    def _shot(name: str, url: str, params: Dict[str, Any]) -> Optional[dict]:
        nonlocal calls
        calls += 1
        try:
            data = _post_form(url, {"c": "StockBidYiDong", **_global_params(), **params},
                              _UA_STOCKS)
            _check_errcode(data)
        except KplRankingError as exc:
            states[name] = {"ok": False, "reason": str(exc.reason)[:60],
                            "errcode": str(getattr(exc, "detail", {}).get("errorCode", ""))}
            return None
        except Exception as exc:  # noqa: BLE001 — 单端点失败不连带
            states[name] = {"ok": False, "reason": f"fetch_failed:{type(exc).__name__}"}
            return None
        states[name] = {"ok": True}
        return data

    if date:
        raws["severe"] = _shot("severe", _HOST_HIS, {"a": "GetYDTPZFPL_W46", "Day": date})
    else:
        raws["severe"] = _shot("severe", _HOST_HQ, {"a": "GetPianLiZhi_W46"})
    day = date or str((raws.get("severe") or {}).get("Day") or "") or None
    sleeper(INTER_CALL_DELAY_SECONDS)
    if day:
        for i in range(max(1, int(recent_pages))):
            raws[f"recent_{i}"] = _shot(
                f"recent_{i}", _HOST_HIS,
                {"a": "GetYDTPZFPL_W46_HisAll", "Day": day, "IsZT": "0",
                 "Index": str(i), "st": "0"})
            sleeper(INTER_CALL_DELAY_SECONDS)
    else:
        states["recent_0"] = {"ok": False, "reason": "no_date"}
    raws["monitor_current"] = _shot("monitor_current", _HOST_HQ, {"a": "GetYDTP_ZDJK_Today"})
    sleeper(INTER_CALL_DELAY_SECONDS)
    if date:
        raws["monitor_history"] = _shot("monitor_history", _HOST_HIS,
                                        {"a": "GetYDTP_ZDJK_His", "Day": date})
    else:
        raws["monitor_history"] = _shot("monitor_history", _HOST_HQ, {"a": "GetYDTP_ZDJK_His"})
    return {"raws": raws, "states": states, "calls": calls, "day": day}


def collect_regulatory(date: Optional[str] = None, *,
                       recent_pages: int = RECENT_PAGES,
                       sleeper=time.sleep) -> Dict[str, Any]:
    """fetch + parse 一体（archiver/CLI 消费）。返回 payload + calls（预算计数用）。"""
    fetched = fetch_regulatory_raw(date, recent_pages=recent_pages, sleeper=sleeper)
    payload = build_regulatory_payload(fetched["raws"], fetched["states"],
                                       date=fetched["day"])
    payload["calls"] = fetched["calls"]
    return payload