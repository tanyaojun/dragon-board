from __future__ import annotations

import re
import time
from typing import Any


_AMOUNT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([万亿]?)\s*$")
_AMOUNT_UNITS: dict[str, float] = {"": 1.0, "万": 10_000.0, "亿": 100_000_000.0}


# L2 主力资金 7 档边界（单位：元），按 2026-08-08 方案文档确认：
# 超大单 ≥1000 万；大单 300-1000 万；中单 100-300 万；小单 30-100 万。
L2_BUCKETS: tuple[dict[str, Any], ...] = (
    {"tier": "ge_1000w", "min": 10_000_000, "max": None, "category": "超大单"},
    {"tier": "700_1000w", "min": 7_000_000, "max": 10_000_000, "category": "大单"},
    {"tier": "500_700w", "min": 5_000_000, "max": 7_000_000, "category": "大单"},
    {"tier": "300_500w", "min": 3_000_000, "max": 5_000_000, "category": "大单"},
    {"tier": "100_300w", "min": 1_000_000, "max": 3_000_000, "category": "中单"},
    {"tier": "50_100w", "min": 500_000, "max": 1_000_000, "category": "小单"},
    {"tier": "30_50w", "min": 300_000, "max": 500_000, "category": "小单"},
)

# 低于该金额的单子不进入 7 档（mainMonitorDetail 监控阈值约 30 万）
MIN_BUCKET_AMOUNT = 300_000


def aggregate_l2_buckets(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """按 7 档边界聚合 mainMonitorDetail 的 ``data.list`` 逐笔。

    每笔使用 ``money``（单笔金额，元）分档，``tradetype`` 判定方向
    （``"1"`` 主动买，其余按卖处理，与 THS 约定一致）；低于 30 万或
    金额缺失的笔不入档。返回与 ``L2_BUCKETS`` 顺序一致的 7 档统计，
    每档含 ``buyCount/sellCount/buyAmount/sellAmount/net``。
    """
    stats: dict[str, dict[str, Any]] = {
        b["tier"]: {
            **b,
            "buyCount": 0,
            "sellCount": 0,
            "buyAmount": 0.0,
            "sellAmount": 0.0,
            "net": 0.0,
        }
        for b in L2_BUCKETS
    }
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        money = _parse_money(row.get("money"))
        if money is None or money < MIN_BUCKET_AMOUNT:
            continue
        tier = _bucket_for(money)
        if tier is None:
            continue
        stat = stats[tier]
        if str(row.get("tradetype")) == "1":
            stat["buyCount"] += 1
            stat["buyAmount"] += money
        else:
            stat["sellCount"] += 1
            stat["sellAmount"] += money
    for stat in stats.values():
        stat["net"] = stat["buyAmount"] - stat["sellAmount"]
    return [stats[b["tier"]] for b in L2_BUCKETS]


def _bucket_for(money: float) -> str | None:
    for bucket in L2_BUCKETS:
        if money >= bucket["min"] and (bucket["max"] is None or money < bucket["max"]):
            return bucket["tier"]
    return None


def _parse_money(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        # L4（2026-08-11 审计）：防御带千分位逗号/空白的字符串金额，避免整笔丢档
        value = value.replace(",", "").strip()
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def parse_amount(value: Any) -> float | None:
    """解析万/亿文本（或 float 元）为元；无法解析返回 None。"""
    text = str(value or "").strip().replace(",", "").replace("元", "")
    match = _AMOUNT_RE.fullmatch(text)
    if not match:
        return None
    return float(match.group(1)) * _AMOUNT_UNITS[match.group(2)]


def parse_l2_summary(code: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    """从 ``load_raw`` 的 raw（data.title 摘要）构建 Redis 缓存行。

    title 的 ``mainbuy/mainsell`` 缺失或无法解析时返回 None（由调用方退避，
    保留 last-good）。返回行含 ``zlje``（mainbuy − mainsell）与
    ``buyAmount/sellAmount``（供 MongoDB ``total`` 使用）。
    """
    data = raw.get("data") or {}
    title = data.get("title") or {}
    main_buy = parse_amount(title.get("mainbuy"))
    main_sell = parse_amount(title.get("mainsell"))
    session_date = str(raw.get("sessionDate") or "")
    if main_buy is None or main_sell is None or not session_date:
        return None
    return {
        "code": code,
        "zlje": main_buy - main_sell,
        "buyAmount": main_buy,
        "sellAmount": main_sell,
        "sessionDate": session_date,
        "source": "ths_main_monitor",
        "moneyFlowSource": "ths_main_monitor",
        "sourceTs": int(raw.get("fetchedAt") or 0),
    }


def build_l2_persist_doc(
    code: str,
    raw: dict[str, Any],
    summary: dict[str, Any],
    buckets: list[dict[str, Any]],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """构建 MongoDB ``fund_flow_l2`` 文档（total 摘要 + 7 档 buckets）。"""
    return {
        "code": code,
        "sessionDate": summary["sessionDate"],
        "tradingDate": summary["sessionDate"],
        "source": "ths_main_monitor",
        "sourceTs": summary["sourceTs"],
        "updatedAt": now_ms if now_ms is not None else int(time.time() * 1000),
        "total": {
            "zlje": summary["zlje"],
            "buyAmount": summary["buyAmount"],
            "sellAmount": summary["sellAmount"],
        },
        "buckets": buckets,
    }
