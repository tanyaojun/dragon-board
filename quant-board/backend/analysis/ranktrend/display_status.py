# -*- coding: utf-8 -*-
"""状态分类 displayStatus 后端生产（2026-08-23，前后端分离 G2）。

前端 getRankTrendDisplayStatus 原是前端自算（依赖前端市场分位/compRank），与后端
observation.synergy.state 不一致。现由后端统一生产 displayStatus（基于后端已有 golden 字段：
synergy.state / strategy.candidateTier / meta.sampleStatus / volumePrice / zljzb），前端只做 label 映射。

枚举（对齐前端 GetRankTrendDisplayStatus 语义 + 后端 synergy.state）：
  sampleStatus=insufficient → 样本不足
  candidateTier=D_EXIT_RISK  → 转弱预警（资金背离时优先）
  candidateTier=C_CROWDED   → 高位拥挤
  candidateTier=A_MAIN      → 主升确认
  candidateTier=B_IGNITION  → 点火观察
  synergy.state=启动确认    → 点火观察
  synergy.state=风险升级    → 转弱预警
  synergy.state=存疑 + 主力净流出 → 资金背离
  兜底                     → 新入观察
"""
from __future__ import annotations

from typing import Any

_DEFAULT = {"label": "新入观察", "classKey": "new_watch", "tooltip": "无明确信号，继续观察。"}

_STATUS = {
    "insufficient": ("样本不足", "insufficient", "历史样本不足，暂不判定状态。"),
    "D_EXIT_RISK": ("转弱预警", "weakening", "撤退/转弱信号，注意风险。"),
    "C_CROWDED": ("高位拥挤", "crowded", "高位拥挤，警惕回落。"),
    "A_MAIN": ("主升确认", "main_confirmed", "主升扩散确认，趋势向上。"),
    "B_IGNITION": ("点火观察", "ignition_watch", "点火启动，观察是否扩散。"),
    "strong_money": ("强资确认", "strong_money", "资金明显介入，但趋势样本仍需确认，重点看后续留榜和资金持续。"),
    "money_divergence": ("资金背离", "money_divergence", "热度仍在但主力资金不支撑，警惕诱多。"),
}


def _is_strong_money(stock: dict[str, Any]) -> bool:
    """G2 强资确认：主力净额 > 0 且 zljzb ≥ 8%（与前端 isStrongMoney 口径对齐）。"""
    try:
        zlje = float(stock.get("zlje") or 0)
        zljzb = float(stock.get("zljzb") or 0)
    except (TypeError, ValueError):
        return False
    return zlje > 0 and zljzb >= 8


def _is_volume_supported(analysis: dict[str, Any]) -> bool:
    """G2 量能承接：volumePrice.signalTier ∈ {A 放量上涨+资金流入, B 放量上涨/量价配合}，
    排除过热(E 对倒/过度放量)与走弱(D)。"""
    vp = (analysis.get("observation") or {}).get("volumePrice") or {}
    return str(vp.get("signalTier") or "") in ("A", "B")


def compute_display_status(
    analysis: dict[str, Any],
    stock: dict[str, Any],
) -> dict[str, str]:
    """基于后端已有 golden 字段生产 displayStatus（label/classKey/tooltip）。"""
    observation = analysis.get("observation") or {}
    synergy = observation.get("synergy") or {}
    strategy = analysis.get("strategy") or {}
    meta = analysis.get("meta") or {}

    sample_status = str(meta.get("sampleStatus") or "ok")
    if sample_status == "insufficient":
        label, key, tip = _STATUS["insufficient"]
        return {"label": label, "classKey": key, "tooltip": tip}

    tier = str(strategy.get("candidateTier") or "")
    if tier in _STATUS:
        label, key, tip = _STATUS[tier]
        return {"label": label, "classKey": key, "tooltip": tip}

    state = str(synergy.get("state") or "")
    if state == "启动确认":
        label, key, tip = _STATUS["B_IGNITION"]
    elif state == "风险升级":
        label, key, tip = _STATUS["D_EXIT_RISK"]
    elif state == "存疑" and (float(stock.get("zljzb") or 0) <= 0):
        label, key, tip = _STATUS["money_divergence"]
    # G2（2026-08-23 补齐）：强资金 + 量能承接 + 无强档位/转弱信号 → 强资确认
    # （sampleStatus insufficient / D_EXIT_RISK / A_MAIN / B_IGNITION / C_CROWDED 已在上方优先 return）
    elif _is_strong_money(stock) and _is_volume_supported(analysis):
        label, key, tip = _STATUS["strong_money"]
    else:
        label, key, tip = _DEFAULT["label"], _DEFAULT["classKey"], _DEFAULT["tooltip"]

    return {"label": label, "classKey": key, "tooltip": tip}
