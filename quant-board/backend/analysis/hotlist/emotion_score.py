# -*- coding: utf-8 -*-
"""规则情绪连续评分核心（路线 B，emotion-score-design.md v3）。

设计原则（用户裁决 2026-09-30）：
- 分数先行：主输出 = 连续情绪分 score（0-100），档位只是分数映射显示层——映射可调，结构不变；
- 分段边界 = 历史分布实测分位校准（jev 聚合口径 T1.5 重放 2026-09-30，出处注于 _CALIB），
  不再有无出处的 magic number；
- 每维贡献可分解：输出附带各维子分明细，缺失维度跳过并权重归一化（fail-visible）；
- 零规则档位依赖：消费 collect_slot_evidence 聚合证据（与 jev 轨道同源），不读 resolve_stage 输出。

档位映射为设计值 + score 实测分布核对（T1.5：五档历史全部可达）；分数域确认复用
stage_confirm.confirm_stage（档位滞回天然防抖）。高潮压制条款已按审计 B3 裁决删除
（riskRowsPct 历史 P10=84.7 系统性高位，保留则高潮档二次不可达；score 本身已含风险两维）。
"""
from __future__ import annotations

# ── 分段校准表（T1.5 jev 口径重放，2026-09-30 首校；详见
# docs/superpowers/specs/2026-09-30-emotion-score-calibration.md）──
# 形状：[(raw 边界, score), ...] 升序，线性插值；每条边界可 diff、可审计。
# 锚定模式：主维 P10→10 / P25→25 / P50→50 / P75→75 / P95→95（反向维镜像 P10→90/
# P50→50/P90→10，trin 加 P5→90/P25→75/P75→25，attackShare 分位锚 sub 系 T1.5 设计值）。
# 【重校准 2026-10-08】首轮月度刷新（docs/hotlist-jev/emotion-score-recalib-
# preregistration-20261008.md 六门全过后落地）：全量滚动 1081 槽（2026-07-14~10-08），
# 6 个有 stored raw 维锚位 raw 刷新，sub/设计点原样保留；EOD 迁移确认层 5.3%、
# 均值 Δ−0.3、相位翻转 0 天。对照产物 data/backups/emotion-score-recalib-20261008.json。
_CALIB = {
    # 广度：上涨行占比（pct>=0 含平盘，jev 口径；1081 槽实测，含 pctChange→change 回退）。
    # 与 v2 规则链口径（change>0）的差异 = 平盘行归属（audit B1）。
    "upRatio": [(0.0, 0), (0.4333, 10), (0.5062, 25), (0.5894, 50), (0.6991, 75), (0.8421, 95), (1.0, 100)],
    # 攻击占比（点火+扩散+强资确认）/total（1081 槽实测；join 率≈100%，与规则口径收敛）
    "attackShare": [(0.0, 0), (0.0385, 30), (0.0839, 50), (0.1384, 70), (0.1829, 85), (0.2613, 95), (1.0, 100)],
    # 风险占比（反向；1081 槽实测；(0.60,95) 为低风险过渡设计点，历史 min=0.578）
    "riskShare": [(0.0, 100), (0.60, 95), (0.8206, 90), (0.9249, 50), (0.9777, 10), (1.0, 0)],
    # 热榜 TRIN（反向；1064 槽实测）
    "trin": [(0.0, 95), (0.5176, 90), (0.699, 75), (0.959, 50), (1.301, 25), (1.674, 10), (4.0, 0)],
    # 昨日涨停承接正收益率（1080 槽实测）
    "yhPositive": [(0.0, 5), (0.4375, 10), (0.6407, 50), (0.8478, 90), (1.0, 100)],
    # 量能同期对比（百分点；历史帧无 totalAmount，设计值待积累 ≥20 交易日后校准）
    "amountVsSame": [(-80, 0), (-30, 25), (0, 50), (30, 80), (80, 100)],
    # 风险预警行占比（反向；1081 槽实测）
    "riskRowsPct": [(0, 100), (84.0164, 90), (93.8596, 50), (98.01, 10), (100, 0)],
    # 涨停结构（198 真信号槽实测，2026-07-30~09-30 覆盖 18.6% 样本；另 349 槽 limitSummary
    # 接口失败期假 0 已剔除——样本局限，待积累后重校准；2026-10-08 重校准未覆盖：
    # raw 不在情绪文档，需 evidence 域另采后随下一轮刷新）
    "ztCount": [(0, 0), (9.7, 10), (30, 25), (42, 50), (60, 75), (102.15, 95), (150, 100)],
    "maxBoard": [(0, 0), (3, 10), (4, 25), (5, 50), (6, 75), (8.15, 95), (10, 100)],
    "zhabanRate": [(0, 100), (11.49, 90), (16.75, 75), (25.39, 50), (33.89, 25), (43.2, 5), (100, 0)],
}

_WEIGHTS = {
    "upRatio": 1, "attackShare": 1, "riskShare": 1, "trin": 1,
    "yhPositive": 1, "limitStruct": 1, "amountVsSame": 1, "riskRowsPct": 1,
}

# 第八维冻结门（2026-10-08 裁决 A-①，eod-emotion-rule-audit-20261008.md P1-1）：
# amountVsSame 评分维冻结，原料照常采集（record_amount_vs_same 每日只记不评）。
# 否决依据（amountvs-same-dimension-assessment 2026-10-06）：①尾部信号单向稀释器
# （20 次阈值穿越全部指向中位：深谷 +3.2/高峰 −3.0）②校准曲线系设计值（±30pp 才到
# 25/80 分，实测 p90 仅 +13.7pp）③T+1 预测力增量为零。10-05 方向二报告预期「10-09 激活」
# 与该评估矛盾且无门控，10-08 已被实证自动激活（EOD 分 44.8→7 维口径 41.6）——现冻结。
# 重启条件：≥20 交易日样本积累后重校准 _CALIB["amountVsSame"]，随预登记重放一并裁决。
_AMOUNT_VS_SAME_ENABLED = False


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


def compute_emotion_score(evidence: dict, slope: float | None = None) -> dict:
    """连续情绪评分（纯函数）。

    输入 = collect_slot_evidence 聚合证据（与 jev 轨道同源，零规则档位依赖）；
    slope = 当日上一有效槽 score 差（接线层提供，T2 起），仅影响低分段退潮/冰点区分。
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
    risk_rows_pct = (row_flags.get("risk") or 0) / judgeable * 100 if judgeable else None

    subs: dict[str, float | None] = {
        "upRatio": _sub("upRatio", up_ratio, dims, skipped),
        "attackShare": _sub("attackShare", attack_share, dims, skipped),
        "riskShare": _sub("riskShare", risk_share, dims, skipped),
        "trin": _sub("trin", trin, dims, skipped),
        "yhPositive": _sub("yhPositive", yh_positive, dims, skipped),
        "limitStruct": limit_struct,
        "amountVsSame": (_sub("amountVsSame", amount_pct, dims, skipped)
                          if (_AMOUNT_VS_SAME_ENABLED and amount_pct is not None) else None),
        "riskRowsPct": (_sub("riskRowsPct", risk_rows_pct, dims, skipped)
                         if risk_rows_pct is not None else None),
    }
    if limit_struct is None:
        skipped.append("limitStruct")
    else:
        dims["limitStruct"] = {"raw": None, "sub": limit_struct}
    if (not _AMOUNT_VS_SAME_ENABLED) or amount_pct is None:
        skipped.append("amountVsSame")
    if risk_rows_pct is None:
        skipped.append("riskRowsPct")

    valid = [(name, sub) for name, sub in subs.items() if sub is not None]
    if not valid:
        return {"score": None, "dims": dims, "skippedDims": skipped,
                "stageCandidate": None}
    score = sum(sub for _, sub in valid) / len(valid)
    return {
        "score": round(score, 1),
        "dims": dims,
        "skippedDims": skipped,
        "stageCandidate": map_stage(score, slope),
    }


# EOD 方向判别冻结阈值（B+C 预登记 2026-10-08，emotion-score-map-stage-bc-preregistration.md；
# 回放验证落在稳定平台：变体 −6/−8 同结果、−10/−15 腰斩，非刀锋边界）
_DD_RETREAT_THRESHOLD = -8.0     # EOD 自日内峰回撤≤此值 → 退潮（修尾盘反抽日）
_UPPER_BAND_STRONG_SLOPE = -10.0  # ≥60 段强负 slope → 退潮（修高位急跌日，浅回落不接管）


def map_stage(score: float, slope: float | None = None, path: dict | None = None) -> str:
    """分数 → 五档映射（边界设计值经 T1.5 score 实测分布核对；spec v3 §3.3）。

    score 主导 + slope/dd 方向修正；高潮压制条款已按审计 B3 删除。
    - A 预登记（2026-10-08）：[40,60) slope<0 → 退潮（修高位回落日误判启动）；
    - B+C 预登记（2026-10-08）：path 仅 EOD 传入（盘中槽恒 None 零行为变化）——
      ≥60 段接强方向（dd≤−8 或 slope<−10 → 退潮，消除 60 边界跳变）；中段 dd≤−8
      补充 slope（修尾盘反抽日：全天跌末步 +1 的日 子）；dd 缺失退化现行规则
      （fail-visible 不发明方向）；bounce 不入映射（锚案例 09-24 裁决 dd 优先）。
      回放：114 日迁移 8 天（启动→退潮 5 + 发酵→退潮 3），其它档位零触碰。
    """
    dd: float | None = None
    if isinstance(path, dict):
        raw_dd = path.get("dd")
        if isinstance(raw_dd, (int, float)) and not isinstance(raw_dd, bool):
            dd = float(raw_dd)
    if score >= 75:
        return "高潮"
    if score >= 60:
        if (dd is not None and dd <= _DD_RETREAT_THRESHOLD) or (slope is not None and slope < _UPPER_BAND_STRONG_SLOPE):
            return "退潮"
        return "发酵"
    if score >= 40:
        if (dd is not None and dd <= _DD_RETREAT_THRESHOLD) or (slope is not None and slope < 0):
            return "退潮"
        return "启动"
    if slope is not None and slope < 0:
        return "退潮"
    return "冰点"
