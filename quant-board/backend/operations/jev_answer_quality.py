# -*- coding: utf-8 -*-
"""判答质量观测（2026-11-18 C1 用户裁决「采纳全部建议」，零新调用替代审计）。

背景（协议层已按 §1.2-6 ③查实）：jev 平台 answer schema 只回 choice/confidence/
probabilities，无 reason——请求体 `{"model","input":{"state","questions"}}` 无客户端
schema 参数（`jev_client._call_primary`），解析层 `answers` 整体透传零丢弃
（`parse_jev_response`），ops 层 answerReasons 接收位已就绪（平台放开零改动接住）。
题面「理由必须点名」义务整体不可审计 → 本模块用**已落库** probabilities 计算
max_prob / top2 margin，max_prob < threshold 入观察桶，按 questionSetHash 代际分段
（跨代不可比），供人工抽检。判答质量不可审计 ≠ 不可观测：三分撕裂/低置信判答
概率分布本身就暴露（西陇 hard_fact 0.57、广百封板 mid 0.50 均被 0.6 阈值捕获）。

纪律：不触发任何 jev 调用（§1.2-7）；纯库读，on-demand 全扫描（两 collection
千级 doc，CLI 人工触发，非盘中链路）；不写库、不投影进叙事（开发诊断不进语料，
§1.2-8）。平台 reason 字段 feature request 已登记
（docs/hotlist-jev/leftover-items-resolution-20261118.md §3），外部依赖时间不可控。
"""
from __future__ import annotations

import math
from typing import Any

# 观察阈值：max_prob < 0.6 入桶（2026-11-18 审计实证校准起点，非判据——
# 不调模型、不改题面，仅人工抽检分流；调整阈值不需要换代）
LOW_CONFIDENCE_THRESHOLD = 0.6

COLLECTIONS = (
    "hotlist_jev_theme_leader_labels",
    "hotlist_jev_auction_leader_labels",
)


def _answer_max_prob(a: dict) -> tuple[float | None, float | None]:
    """单题判答 → (max_prob, top2_margin)。probabilities 优先（重算不信任存储
    confidence）；缺概率分布时回退 confidence 字段（margin 不可算=None，不编造）。"""
    probs = a.get("probabilities")
    if isinstance(probs, dict) and probs:
        vals = sorted(
            (float(v) for v in probs.values()
             if isinstance(v, (int, float)) and not isinstance(v, bool)
             and math.isfinite(v)),
            reverse=True)
        if vals:
            return vals[0], (vals[0] - vals[1]) if len(vals) > 1 else None
    c = a.get("confidence")
    if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c):
        return float(c), None
    return None, None


def low_confidence_report(db: Any, *, date_start: str | None = None,
                          date_end: str | None = None,
                          threshold: float = LOW_CONFIDENCE_THRESHOLD,
                          collections: tuple[str, ...] = COLLECTIONS) -> dict:
    """低置信判答清单（按代际分段）。

    只读 status=ok 档（degraded 档判答残缺不进质量统计，其本身已由 corpusState
    fail-visible 暴露）；日期按 _id 前缀 YYYY-MM-DD 过滤（闭区间）；每代际记录
    questionSetVersion / ammoVersions（同 hash 可跨 AMMO 代——题面不变语料变）/
    判答总数 / 入桶数 / 入桶率 / 明细行。
    """
    generations: dict[str, dict] = {}
    total = flagged = 0
    for coll in collections:
        for doc in db[coll].find({}):
            if doc.get("status") != "ok":
                continue
            _id = str(doc.get("_id") or "")
            date = _id.split(":")[0]
            if date_start and date < date_start:
                continue
            if date_end and date > date_end:
                continue
            answers = doc.get("answers") or {}
            if not isinstance(answers, dict):
                continue
            gkey = str(doc.get("questionSetHash") or "unknown")
            g = generations.setdefault(gkey, {
                "questionSetVersion": doc.get("questionSetVersion"),
                "ammoVersions": set(),
                "totalAnswers": 0, "flagged": 0, "rows": []})
            if doc.get("ammoVersion"):
                g["ammoVersions"].add(str(doc["ammoVersion"]))
            for qk, a in answers.items():
                if not isinstance(a, dict):
                    continue
                mp, margin = _answer_max_prob(a)
                if mp is None:
                    continue
                g["totalAnswers"] += 1
                total += 1
                if mp < threshold:
                    g["flagged"] += 1
                    flagged += 1
                    g["rows"].append({
                        "date": date, "id": _id, "docKind": doc.get("docKind"),
                        "question": qk, "choice": a.get("choice"),
                        "maxProb": round(mp, 4),
                        "margin": round(margin, 4) if margin is not None else None})
    for g in generations.values():
        g["ammoVersions"] = sorted(g["ammoVersions"])
        g["flagRate"] = (round(g["flagged"] / g["totalAnswers"], 4)
                         if g["totalAnswers"] else None)
        g["rows"].sort(key=lambda r: (r["date"], r["id"], r["question"]))
    return {"threshold": threshold, "totalAnswers": total, "flagged": flagged,
            "flagRate": round(flagged / total, 4) if total else None,
            "generations": generations}
