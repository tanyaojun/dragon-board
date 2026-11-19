# -*- coding: utf-8 -*-
"""THS mainMonitorDetail L2 摘要解析（Redis 运行态资金行）。

历史：本模块曾含 7 档 buckets 聚合 + fund_flow_l2 MongoDB 持久化文档构建
（2026-08-08 方案）；2026-11-19 用户裁决退役 MongoDB 持久层（集合 mongodump
归档 data/backups/ 后 drop），buckets 聚合无其他消费方随删，只保留
title 摘要解析（Redis 缓存行 + ths-detail/ths-fund-batch 读口共用）。
"""
from __future__ import annotations

import re
from typing import Any


_AMOUNT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([万亿]?)\s*$")
_AMOUNT_UNITS: dict[str, float] = {"": 1.0, "万": 10_000.0, "亿": 100_000_000.0}


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
    ``buyAmount/sellAmount``（买入/卖出总额摘要，随缓存行透出）。
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
