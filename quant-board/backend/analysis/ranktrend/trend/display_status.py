# -*- coding: utf-8 -*-
"""displayStatus 纯投影（2026-09-10 口径统一：生命周期 stage 主轴，spec §3/§10）。

`docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`

- displayStatus 只是 `cycle.stage` 的**展示投影**：`{stage, label, tooltip}`；
- `label ≡ STAGE_LABELS[stage]`，stage 缺失/非法 → `stage=None` + `label="无阶段"`；
- **没有分类层**：不存在 8 类 label/classKey，不存在样本门 / 风险修正层 / 兜底类；
- cooling 且强资金 + 量能承接 → **只追加 tooltip**，不改变 label/stage、不进任何计数；
- 词表（`STAGE_LABELS` / `STAGE_TOOLTIPS`）是**单一来源**，前端只消费后端产出的 label，
  不得自维护第二套映射（历史教训：前端 `CYCLE_LABELS` 用"降温"、`DataTable` 用"冷却"，
  同一状态两套词）。

为什么删除分类层（spec §10.1）：实测 978 帧 / 220,736 行证明 8 类无法反推 stage
（`样本不足` 跨 4 个 stage、`转弱预警` 跨 3 个），8 类中 `主升确认`/`资金背离`/`新入观察`
从未出现，且修正层用互斥 return **覆盖**了 stage 主轴信息。"把一等字段（`cycle.stage` /
`synergy.state` / `meta.sampleQuality` / `zlje`+`signalTier`）复制成第二套状态分类就是病灶本身。"

已删除且**不得恢复**：三层修正级联、8 类 `_STATUS`/`_STAGE_KEYS`/`_make`/`_make_stage_missing`、
`STAGE_MISSING_LABELS`/`STAGE_MISSING_TOOLTIP`/`_STAGE_MISSING_PREFIX`/
`is_stage_missing_fallback`/`_sample_status`（`test_removed_symbols_are_gone` 锁定）。
"""
from __future__ import annotations

import math
from typing import Any

# 生命周期 5 态枚举（stage 主轴唯一判据；join 层与本模块共用，禁止各写一套）
STAGE_ENUM = ("ignition", "expansion", "crowded", "reversal", "cooling")

# 展示词表（单一来源）：前端只消费，不自维护
STAGE_LABELS: dict[str, str] = {
    "ignition": "点火",
    "expansion": "扩散",
    "crowded": "拥挤",
    "reversal": "反转",
    "cooling": "冷却",
}

STAGE_UNKNOWN_LABEL = "无阶段"

STAGE_TOOLTIPS: dict[str, str] = {
    "ignition": "点火启动，观察是否扩散。",
    "expansion": "扩散确认，趋势向上。",
    "crowded": "注意力拥挤高位，追高风险上升。",
    "reversal": "排名反转回落，注意风险。",
    "cooling": "注意力冷却消退。",
}

STAGE_UNKNOWN_TOOLTIP = "生命周期阶段缺失或非法，无法判定。"

STRONG_SUPPORT_NOTE = "资金承接仍强。"

_PRICE_KEYS = ("price", "latestPrice", "lastPrice", "close")


def _as_dict(value: Any) -> dict[str, Any]:
    """形状归一：非 dict（None/list/str/数值）一律视为空 dict。

    纯函数必须对非法输入形状容错——否则单股异常形状会沿调用链抛错，而调用点
    （`ranktrend_routes.py` 的 `compute_display_status` 调用）没有 try 兜底。
    """
    return value if isinstance(value, dict) else {}


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _is_invalid_quote(stock: dict[str, Any]) -> bool:
    """无效行情判据（**当前无消费方，不得在展示链路重新启用**）。

    纯投影下"无效行情"不再改判展示状态 —— 否则又会制造第二套结论。保留定义供周期列灰框 /
    诊断复用；展示状态只认 `cycle.stage`。若将来要恢复使用，必须同批修改 spec 与测试。

    判据：价格类字段（`price`/`latestPrice`/`lastPrice`/`close`，取首个有值者）非有限或 ≤0，
    或成交额 `turnover` 非有限或 <0。
    缺失 ≠ 无效（字段全缺时不判无效，fail-visible）；`turnover == 0` 视为有效（集合竞价）。
    """
    stock = _as_dict(stock)
    price = next((stock[k] for k in _PRICE_KEYS if _has_value(stock.get(k))), None)
    if _has_value(price):
        try:
            number = float(price)
        except (TypeError, ValueError):
            return True
        if not math.isfinite(number) or number <= 0:
            return True
    if _has_value(stock.get("turnover")):
        try:
            number = float(stock["turnover"])
        except (TypeError, ValueError):
            return True
        if not math.isfinite(number) or number < 0:
            return True
    return False


def _is_strong_money(stock: dict[str, Any]) -> bool:
    """强资金：主力净额 > 0 且 zljzb ≥ 8%（口径沿用，仅用于 cooling 的 tooltip 提示）。"""
    stock = _as_dict(stock)
    try:
        zlje = float(stock.get("zlje"))
        zljzb = float(stock.get("zljzb"))
    except (TypeError, ValueError):
        return False
    return zlje > 0 and zljzb >= 8


def _is_volume_supported(analysis: dict[str, Any]) -> bool:
    """量能承接：`volumePrice.signalTier ∈ {A, B}`（排除过热 E 与走弱 D）。缺失 → False。"""
    vp = _as_dict(_as_dict(analysis).get("observation")).get("volumePrice")
    return str(_as_dict(vp).get("signalTier") or "") in ("A", "B")


def stage_of(analysis: dict[str, Any]) -> str:
    """取 `cycle.stage`；缺失或非法形状返回空串。"""
    return str(_as_dict(_as_dict(analysis).get("cycle")).get("stage") or "")


def is_stage_missing(analysis: dict[str, Any]) -> bool:
    """stage 缺失或非法枚举。

    join 层与前端一律复用本判据，禁止第二套枚举实现——`compute_display_status` 的空态分支
    与本函数必须始终等价（旧 8 类时代 `stageMissing` 判据分叉过的教训）。
    """
    return stage_of(analysis) not in STAGE_ENUM


def compute_display_status(analysis: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    """stage 纯投影：`{stage, label, tooltip}`。

    `is_stage_missing(analysis)` 与本函数等价：stage 为空串或非法枚举时 `stage=None`、
    `label=STAGE_UNKNOWN_LABEL`、`tooltip=STAGE_UNKNOWN_TOOLTIP`。
    """
    raw_stage = stage_of(analysis)
    stage = raw_stage if raw_stage in STAGE_ENUM else None
    if stage is None:
        return {"stage": None, "label": STAGE_UNKNOWN_LABEL, "tooltip": STAGE_UNKNOWN_TOOLTIP}
    tooltip = STAGE_TOOLTIPS.get(stage) or STAGE_UNKNOWN_TOOLTIP
    # cooling 且强资金 + 量能承接：仅 tooltip 追加，不改 label/stage、不进计数
    if stage == "cooling" and _is_strong_money(stock) and _is_volume_supported(analysis):
        tooltip = f"{tooltip}{STRONG_SUPPORT_NOTE}"
    return {"stage": stage, "label": STAGE_LABELS[stage], "tooltip": tooltip}
