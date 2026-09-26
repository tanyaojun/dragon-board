"""主线题材归属判定链（Phase R1 研究纯函数，设计文档 §5.5）。

三层：原料白名单 → MainlineScore 合成 → 个股归属。
硬约束：原料白名单封闭（MAINLINE_FACTOR_KEYS），依赖归属的派生因子
（如成交额占比拥挤度）严禁回流——循环依赖防护，新增输入需设计评审。
fail-visible：因子缺失按可用因子重分配权重并打 factorCoverage 标记；
归属无据时回退 themes[0]（旧口径）打 fallback 标记，不伪造。
已知限制：传入 weights 中白名单外的 key 会被忽略且无提示；调用方传错因子名不会报错，
属已知限制（白名单封闭的代价）。
接线位置（后续任务）：snapshot_derivation/projection.py 替换 row_themes[0] 兜底。
"""

from __future__ import annotations

import math
from typing import Any

# 原料白名单：封闭。全部为 sector rows 同槽可用、且不依赖归属判定的独立原料。
MAINLINE_FACTOR_KEYS = ("heatLevel", "momentumScore", "ztCount", "fundScore")

# 研究初始权重（Phase R1 敏感性扫描定版，非生产默认；见 diagnose_theme_rotation_r1）。
DEFAULT_MAINLINE_WEIGHTS = {
    "heatLevel": 0.40,
    "momentumScore": 0.25,
    "ztCount": 0.20,
    "fundScore": 0.15,
}

# 平局消歧阈值：Top1/Top2 分差小于该值时允许涨停原因介入。
TIE_BREAK_EPS = 2.0


def _normalize_theme_label(name: str) -> str:
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    """横截面 percentile rank 归一（0-1），并列取平均秩，单题材归中 0.5。"""
    if not values:
        return {}
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2
        for k in range(i, j + 1):
            out[items[k][0]] = avg_rank / (n - 1)
        i = j + 1
    return out


def mainline_scores(
    sector_rows: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """单槽题材横截面 → {themeKey: {score, status, factorCoverage, factorsUsed}}。

    每因子在当槽横截面做 percentile rank 后加权合成（0-100 分）。
    缺失因子（含 NaN/inf/bool 等非 finite 数值）：该题材按可用因子重分配权重，
    coverage<1 标 degraded；全缺标 insufficient、score=None。
    同一 entityKey/entityName 在横截面重复出现时保留后行计算结果并打
    duplicate_entity 标记（qualityFlags），计算口径不变、只补可诊断性。
    """
    w = {
        k: float((weights or DEFAULT_MAINLINE_WEIGHTS).get(k, 0.0))
        for k in MAINLINE_FACTOR_KEYS
    }
    ranks: dict[str, dict[str, float]] = {}
    for key in MAINLINE_FACTOR_KEYS:
        vals: dict[str, float] = {}
        for row in sector_rows:
            v = row.get(key)
            tkey = row.get("entityKey") or row.get("entityName")
            if (
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(float(v))
                and tkey is not None
            ):
                vals[str(tkey)] = float(v)
        if vals:
            ranks[key] = _percentile_ranks(vals)
    key_counts: dict[str, int] = {}
    for row in sector_rows:
        raw_key = row.get("entityKey") or row.get("entityName")
        if raw_key is None:
            continue
        skey = str(raw_key)
        key_counts[skey] = key_counts.get(skey, 0) + 1
    out: dict[str, dict[str, Any]] = {}
    for row in sector_rows:
        raw_key = row.get("entityKey") or row.get("entityName")
        if raw_key is None:
            # 与因子收集阶段一致：entityKey/entityName 双缺失的 row 不产出条目
            continue
        tkey = str(raw_key)
        num = 0.0
        den = 0.0
        used: list[str] = []
        for key in MAINLINE_FACTOR_KEYS:
            r = ranks.get(key, {}).get(tkey)
            if r is None:
                continue
            num += w[key] * r
            den += w[key]
            used.append(key)
        total_w = sum(w.values())
        flags = ["duplicate_entity"] if key_counts.get(tkey, 0) > 1 else []
        if den <= 0:
            out[tkey] = {
                "score": None,
                "status": "insufficient",
                "factorCoverage": 0.0,
                "factorsUsed": [],
                "qualityFlags": flags,
            }
            continue
        out[tkey] = {
            "score": round(100.0 * num / den, 2),
            "status": "ok" if abs(den - total_w) < 1e-9 else "degraded",
            "factorCoverage": round(den / total_w, 4) if total_w else 0.0,
            "factorsUsed": used,
            "qualityFlags": flags,
        }
    return out


def assign_main_theme(
    stock_themes: list[str],
    theme_scores: dict[str, dict[str, Any]],
    *,
    reason_text: str | None = None,
    fallback_theme: str | None = None,
    tie_break_eps: float = TIE_BREAK_EPS,
) -> dict[str, Any]:
    """个股归属：所属题材中 MainlineScore 最高者（§5.5 判定层）。

    stock_themes: 该股所属题材名列表（market_context.themes 顺序）。
    reason_text: 涨停原因文本（THS reasonType / 复合原因"机器人+军工"）；
      Top1/Top2 分差 < tie_break_eps 且原因含某候选题材名（归一后子串匹配）
      时选该题材，reason=tie_break_reason。注意：短题材名可能子串误命中，
      消歧仅作平局处理、非第一优先级（命中会追加 tie_break:{题材} 标记可审计）。
    fallback_theme: 兜底，通常 = stock_themes[0]（旧口径 themes[0]）。
    """
    candidates = [
        t
        for t in stock_themes
        if t in theme_scores and theme_scores[t].get("score") is not None
    ]
    if not candidates:
        fb = fallback_theme or (stock_themes[0] if stock_themes else None)
        if fb is None:
            return {
                "mainTheme": None,
                "mainThemeReason": "unassigned",
                "qualityFlags": ["no_theme"],
                "scoreGap": None,
            }
        return {
            "mainTheme": fb,
            "mainThemeReason": "fallback",
            "qualityFlags": ["fallback"],
            "scoreGap": None,
        }
    ranked = sorted(candidates, key=lambda t: theme_scores[t]["score"], reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    top_score = theme_scores[top]["score"]
    gap = (top_score - theme_scores[second]["score"]) if second else None
    chosen = top
    reason = "mainline_score"
    flags: list[str] = []
    if gap is not None and gap < tie_break_eps and reason_text:
        norm_reason = str(reason_text)
        hits = [
            t
            for t in ranked[:3]
            if _normalize_theme_label(t) and _normalize_theme_label(t) in norm_reason
        ]
        if hits:
            chosen = hits[0]
            reason = "tie_break_reason"
            flags.append("tie_broken")
            flags.append(f"tie_break:{chosen}")
    if gap is not None:
        flags.append(f"gap:{round(gap, 2)}")
    return {
        "mainTheme": chosen,
        "mainThemeReason": reason,
        "qualityFlags": flags,
        "scoreGap": None if gap is None else round(gap, 2),
    }
