# -*- coding: utf-8 -*-
"""规则情绪连续评分核心（路线 B，emotion-score-design.md v2）。

设计原则（用户裁决 2026-09-30）：
- 分数先行：主输出 = 连续情绪分 score（0-100），档位只是分数映射显示层——映射可调，结构不变；
- 分段边界 = 1066 槽 half_hour 历史分布实测分位校准（2026-09-30，出处注于 _CALIB），
  不再有无出处的 magic number；
- 每维贡献可分解：输出附带各维子分明细，缺失维度跳过并权重归一化（fail-visible）；
- 零规则档位依赖：消费 collect_slot_evidence 聚合证据（与 jev 轨道同源），不读 resolve_stage 输出。

档位映射为 B1 设计值（透明可调）；分数域确认复用 stage_confirm.confirm_stage（档位滞回天然防抖）。
"""
from __future__ import annotations

# ── 分段校准表 ──
# 来源：1066 槽 half_hour 历史分布实测分位（2026-09-30 校准，详见
# docs/superpowers/specs/2026-09-30-emotion-score-design.md §3.1）。
# 形状：[(raw 边界, score), ...] 升序，线性插值；每条边界可 diff、可审计。
_CALIB = {
    # 广度：上涨行占比（P10=0.385 / P25=0.470 / P50=0.561 / P75=0.662 / P95=0.800）
    "upRatio": [(0.0, 0), (0.385, 10), (0.470, 25), (0.561, 50), (0.662, 75), (0.800, 95), (1.0, 100)],
    # 攻击占比（点火+扩散+强资确认）/total（P50=0.037 / P75=0.082 / P90=0.130 / P95=0.171 / P99=0.254）
    "attackShare": [(0.0, 5), (0.037, 30), (0.082, 50), (0.130, 70), (0.171, 85), (0.254, 95), (1.0, 100)],
    # 风险占比（反向；P10=0.826 / P50=0.925 / P90=0.978——系统性高位，高分只在显著低于常态时给）
    "riskShare": [(0.0, 100), (0.60, 95), (0.826, 90), (0.925, 50), (0.978, 10), (1.0, 5)],
    # 热榜 TRIN（反向；P5=0.505 / P25=0.696 / P50=0.963 / P75=1.309 / P90=1.682）
    "trin": [(0.0, 95), (0.505, 90), (0.696, 75), (0.963, 50), (1.309, 25), (1.682, 10), (4.0, 0)],
    # 昨日涨停承接正收益率（P10=0.438 / P50=0.643 / P90=0.848）
    "yhPositive": [(0.0, 5), (0.438, 10), (0.643, 50), (0.848, 90), (1.0, 100)],
    # 量能同期对比（百分点；节后积累分布后可再校准，当前为设计值）
    "amountVsSame": [(-80, 0), (-30, 25), (0, 50), (30, 80), (80, 100)],
    # 风险预警行占比（反向，占可判定行 %；首日分布后可再校准，当前为设计值）
    "riskRowsPct": [(0, 95), (40, 70), (60, 50), (80, 20), (100, 5)],
    # 涨停结构（设计值：家数/高度/炸板率归一合成）
    "ztCount": [(0, 0), (20, 30), (45, 60), (80, 90), (150, 100)],
    "maxBoard": [(0, 0), (2, 25), (4, 50), (6, 75), (9, 100)],
    "zhabanRate": [(0, 100), (15, 75), (30, 45), (50, 15), (100, 0)],
}

_WEIGHTS = {
    "upRatio": 1, "attackShare": 1, "riskShare": 1, "trin": 1,
    "yhPositive": 1, "limitStruct": 1, "amountVsSame": 1, "riskRowsPct": 1,
}

# 风险预警行占比超过该值时，压制高潮候选为发酵（score ≥75 场景）
_RISK_ROWS_CLIMAX_SUPPRESS = 70.0


def _interp(points: list[tuple[float, float]], value: float) -> float:
    """分段线性插值；value 低于首边界取首分、高于末边界取末分。"""
    if value <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            ratio = (value - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + (y1 - y0) * ratio
    return float(points[-1][1])


def _finite(value) -> bool:
    from math import isfinite
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def _sub(name: str, raw, dims: dict, skipped: list) -> float | None:
    if not _finite(raw):
        skipped.append(name)
        return None
    sub = _interp(_CALIB[name], float(raw))
    dims[name] = {"raw": round(float(raw), 4), "sub": round(sub, 1)}
    return sub


def compute_emotion_score(evidence: dict) -> dict:
    """连续情绪评分（纯函数）。

    输入 = collect_slot_evidence 聚合证据（与 jev 轨道同源，零规则档位依赖）。
    输出 {score, dims, skippedDims, stageCandidate}；缺维跳过 + 权重归一化。
    """
    dims: dict = {}
    skipped: list[str] = []
    breadth = evidence.get("breadth") or {}
    row_flags = evidence.get("rowFlags") or {}
    lifecycle = evidence.get("lifecycle") or {}
    limit = evidence.get("limit") or {}
    yh = evidence.get("yesterdayLimit") or {}
    amount = evidence.get("totalAmount") or {}

    total = breadth.get("total") or 0
    judgeable = row_flags.get("judgeable") or 0

    # 1. 广度
    up_count = (breadth.get("limitUp") or 0) + (breadth.get("up5") or 0) + (breadth.get("up0") or 0)
    up_ratio = up_count / total if total else None
    # 2. 攻击占比 =（点火 + 扩散 + 强资确认）/ total（自算计数聚合，零规则文档依赖）
    attack = ((lifecycle.get("ignition") or 0) + (lifecycle.get("expansion") or 0)
              + (row_flags.get("strongMoney") or 0))
    attack_share = attack / total if total else None
    # 3. 风险占比
    risk_share = (row_flags.get("risk") or 0) / total if total else None
    # 4. TRIN
    trin = breadth.get("trin")
    # 5. 昨日承接正收益率
    yh_positive = yh.get("positiveRate")
    # 6. 涨停结构合成子分
    zt = limit.get("ztCount")
    mb = limit.get("maxBoard")
    zb = limit.get("zhabanRate")
    zt_sub = _interp(_CALIB["ztCount"], float(zt)) if _finite(zt) else None
    mb_sub = _interp(_CALIB["maxBoard"], float(mb)) if _finite(mb) else None
    zb_sub = _interp(_CALIB["zhabanRate"], float(zb)) if _finite(zb) else None
    struct_parts = [s for s in (zt_sub, mb_sub, zb_sub) if s is not None]
    limit_struct = round(sum(struct_parts) / len(struct_parts), 1) if struct_parts else None
    # 7. 量能同期
    amount_pct = amount.get("vsSamePct")
    # 8. 风险预警行占比（反向）
    risk_rows_pct = (risk_rows_pct_ := row_flags.get("risk") or 0) / judgeable * 100 if judgeable else None

    subs: dict[str, float | None] = {
        "upRatio": _sub("upRatio", up_ratio, dims, skipped),
        "attackShare": _sub("attackShare", attack_share, dims, skipped),
        "riskShare": _sub("riskShare", risk_share, dims, skipped),
        "trin": _sub("trin", trin, dims, skipped),
        "yhPositive": _sub("yhPositive", yh_positive, dims, skipped),
        "limitStruct": limit_struct,
        "amountVsSame": (_sub("amountVsSame", amount_pct, dims, skipped)
                          if amount_pct is not None else None),
        "riskRowsPct": (_sub("riskRowsPct", risk_rows_pct, dims, skipped)
                         if risk_rows_pct is not None else None),
    }
    if limit_struct is None:
        skipped.append("limitStruct")
    else:
        dims["limitStruct"] = {"raw": None, "sub": limit_struct}
    if amount_pct is None:
        skipped.append("amountVsSame")
    if risk_rows_pct is None:
        skipped.append("riskRowsPct")

    valid = [(name, sub) for name, sub in subs.items() if sub is not None]
    if not valid:
        return {"score": None, "dims": dims, "skippedDims": skipped,
                "stageCandidate": None}
    score = sum(sub for _, sub in valid) / len(valid)
    risk_rows_pct_for_map = (
        risk_rows_pct if risk_rows_pct is not None
        else (risk_share * 100 if risk_share is not None else None))
    stage = map_stage(score, risk_rows_pct_for_map)
    return {
        "score": round(score, 1),
        "dims": dims,
        "skippedDims": skipped,
        "stageCandidate": stage,
    }


def map_stage(score: float, risk_rows_pct: float | None = None,
              slope: float | None = None) -> str:
    """分数 → 五档映射（B1 设计值，透明可调；spec §3.3）。

    score 主导 + 风险压制 + 低分斜率修正（区分退潮/冰点方向语义）。
    """
    if score >= 75:
        if risk_rows_pct is not None and risk_rows_pct > _RISK_ROWS_CLIMAX_SUPPRESS:
            return "发酵"  # 风险行占比高位压制高潮候选
        return "高潮"
    if score >= 60:
        return "发酵"
    if score >= 40:
        return "启动"
    if slope is not None and slope < 0:
        return "退潮"
    return "冰点"
