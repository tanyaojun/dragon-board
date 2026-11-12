# -*- coding: utf-8 -*-
"""jev 题目集置信度全景统计（2026-10-11 立项，只读，零 jev API 调用）。

背景见 docs/hotlist-jev/jev-questionset-ammo-confidence-review.md §三：
confidence 全部为模型自报（parse_jev_response 原样透传），但从未做过跨集合统计——
「离 90 有多远、哪些题天生到不了 90」无台账。本脚本扫六集合现行代文档产出观测表。

统计口径：
- 只统计 status=ok 文档；degraded/no_data 单独计数（fail-visible，不伪装）。
- choice 题：top 概率（probabilities 最大值）< 0.60 计骑墙（与复核工作台犹豫阈值同口径）；
  insufficient/insufficient_evidence/unclear 计逃生率。
- score 题：probabilities 直方图按档序算标准差 hstd（离散度，越大越犹豫）。
- confidence 直读仅 answers 原样落库的集合（sentiment/crowding_pilot）；
  打标/Q5/cycle/relay/zhaban 五链自 2026-10-11 P0-2 起新文档补落 answers 原样包
  （confidence/直方图保全），此前旧文档只提取 choice+probabilities——
  旧文档如实计入「无 confidence 可读」（历史不可回补），这正是解析层丢弃证据
  （review §三登记）。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe scripts/jev_confidence_landscape.py [--out data/reports/xxx.md]
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import get_runtime_mongodb_database

# 骑墙阈值：与复核工作台犹豫阈值 60% 同口径（jev-temp-crowding-confidence-deepening.md §四）
HESITANT_THRESHOLD = 0.60
# 逃生档（各题实际枚举的「证据不足」类答案统一计数）
ESCAPE_CHOICES = {"insufficient", "insufficient_evidence", "unclear"}

# ── 纯统计层（零 IO，测试直接喂假文档） ──────────────────────────────

def pct(vals: list[float], q: float) -> float | None:
    """线性插值分位数；空列表返回 None。"""
    if not vals:
        return None
    s = sorted(vals)
    idx = (len(s) - 1) * q / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return round(s[lo] * (1 - frac) + s[hi] * frac, 3)


def hist_std(probabilities: dict[str, float]) -> float | None:
    """score 题档位直方图标准差：档序按数值排序（"0".."9" 与 "0","11",.."100" 均适用）。"""
    try:
        items = sorted((float(k), v) for k, v in probabilities.items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool))
    except (TypeError, ValueError):
        return None
    total = sum(v for _, v in items)
    if len(items) < 2 or total <= 0:
        return None
    probs = [v / total for _, v in items]
    mean = sum(i * p for i, p in enumerate(probs))
    var = sum(i * i * p for i, p in enumerate(probs)) - mean * mean
    return round(math.sqrt(max(var, 0.0)), 2)


def answer_view(doc: dict, key: str) -> dict | None:
    """answers 原样落库的集合（sentiment/crowding_pilot）：直读单题视图。"""
    a = (doc.get("answers") or {}).get(key)
    return a if isinstance(a, dict) else None


def field_view(doc: dict, choice_field: str, prob_field: str | None,
               conf_field: str | None = None) -> dict | None:
    """字段提取型集合（driver/relay/zhaban/cycle）：choice/probabilities 独立字段。
    P0-2 之前的旧文档 confidence 结构性缺失；新文档可选 conf_field（如 stockPhaseConfidence）。"""
    choice = doc.get(choice_field)
    prob = doc.get(prob_field)
    conf = doc.get(conf_field) if conf_field else None
    if choice is None and prob is None and conf is None:
        return None
    return {"choice": choice,
            "probabilities": prob if isinstance(prob, dict) else None,
            "confidence": conf}


def blob_or_field(doc: dict, key: str, choice_field: str, prob_field: str | None,
                  conf_field: str | None = None) -> dict | None:
    """P0-2 后五链新文档带 answers 原样包（含 confidence/score 直方图），优先直读；
    缺该题（partial_answers）或旧文档回退字段提取（历史文档行为不变）。"""
    a = (doc.get("answers") or {}).get(key)
    if isinstance(a, dict):
        return a
    return field_view(doc, choice_field, prob_field, conf_field)


def score_blob_or_field(doc: dict, key: str, score_field: str) -> dict | None:
    """score 题版：blob 直读（带 type/probabilities 直方图/confidence），
    旧文档回退顶层归一分字段（无直方图，hstd 不可测——如实计 noProb）。
    review P1：blob 的 score 是原始锚点期望（0-9 标尺），按 legend 分母归一到 0-100
    与顶层字段同标尺（对齐 parse_jev_response），防同版本段两标尺混桶。"""
    a = (doc.get("answers") or {}).get(key)
    if isinstance(a, dict):
        score, legend = a.get("score"), a.get("legend") or {}
        denom = len(legend) - 1 if isinstance(legend, dict) else 0
        normalized = (round(score / denom * 100, 1)
                      if isinstance(score, (int, float)) and not isinstance(score, bool) and denom > 0
                      else None)
        return {"type": "score", "score": normalized,
                "probabilities": a.get("probabilities"), "confidence": a.get("confidence")}
    score = doc.get(score_field)
    if score is None:
        return None
    return {"type": "score", "score": score, "probabilities": None, "confidence": None}


# 每集合题目视图提取器：(doc) -> {题key: 单题视图}
# choice_field/prob_field 映射自各 runner 落库代码（核对行号见 review §一）。
def _extract_sentiment(doc: dict) -> dict:
    keys = ["frame_stage", "sequence_stage", "temperature", "crowding"] \
        if doc.get("kind") == "slot" else \
        ["day_stage", "day_pattern", "day_temperature", "day_crowding"]
    return {k: v for k in keys if (v := answer_view(doc, k))}


def _extract_crowding_pilot(doc: dict) -> dict:
    keys = ["crowding_score"] if doc.get("kind") == "slot" else ["day_crowding_score"]
    return {k: v for k in keys if (v := answer_view(doc, k))}


def _extract_driver(doc: dict) -> dict:
    if doc.get("origin") == "phase_band_daily":
        return {"phase_band": v for v in [blob_or_field(doc, "phase_band", "phaseBand", "phaseBandProbabilities")] if v}
    out = {}
    for key, (cf, pf) in {"driver_type": ("label", "driverProbabilities"),
                          "catalyst_depth": ("catalystDepth", "catalystDepthProbabilities"),
                          "catalyst_freshness": ("freshness", None),  # 旧文档 probabilities 未落库
                          "buy_side_logic": ("buySideLogic", "buySideProbabilities")}.items():
        if (v := blob_or_field(doc, key, cf, pf)):
            out[key] = v
    sp = blob_or_field(doc, "stock_phase_position", "stockPhasePosition",
                       "stockPhaseProbabilities", "stockPhaseConfidence")
    if sp:
        out["stock_phase_position"] = sp
    return out


def _extract_relay(doc: dict) -> dict:
    out = {}
    for key, (cf, pf) in {"relay_phase": ("relayPhase", "relayPhaseProbabilities"),
                          "relay_momentum": ("relayMomentum", None),   # 旧文档 probabilities 未落库
                          "ladder_health": ("ladderHealth", None),     # 同上
                          "money_effect": ("moneyEffect", None),       # 同上
                          "theme_pulse": ("themePulse", None)}.items():  # 同上
        if (v := blob_or_field(doc, key, cf, pf)):
            out[key] = v
    for key, sf in [("relay_index", "relayIndex"), ("leader_strength", "leaderStrength")]:
        if (v := score_blob_or_field(doc, key, sf)):
            out[key] = v
    return out


def _extract_zhaban(doc: dict) -> dict:
    return {"zhaban_cause": v for v in [blob_or_field(doc, "zhaban_cause", "zhabanCause", "zhabanCauseProbabilities")] if v}


COLLECTION_SPECS: list[dict[str, Any]] = [
    {"collection": "hotlist_jev_sentiment", "label": "情绪链 槽级4题+EOD 4题（v2.x）",
     "extractor": _extract_sentiment},
    {"collection": "hotlist_jev_driver_labels", "label": "涨停打标 个股4题+Q5哨兵（v3.1）",
     "extractor": _extract_driver},
    {"collection": "hotlist_jev_relay_index", "label": "连板接力 7题（v3）",
     "extractor": _extract_relay},
    {"collection": "hotlist_jev_zhaban_labels", "label": "炸板归因 单题（v1）",
     "extractor": _extract_zhaban},
    {"collection": "hotlist_jev_crowding_pilot", "label": "拥挤连续分 2题（v3.0-pilot）",
     "extractor": _extract_crowding_pilot},
]


def accumulate(docs: Iterable[dict], extractor) -> dict:
    """一组文档 → {「版本段|题key」: 指标累积}。纯函数。"""
    buckets: dict[tuple[str, str], dict] = {}
    counters = {"ok": 0, "not_ok": 0, "not_ok_detail": {}}
    for doc in docs:
        if doc.get("status") != "ok":
            counters["not_ok"] += 1
            counters["not_ok_detail"][doc.get("status") or "unknown"] = \
                counters["not_ok_detail"].get(doc.get("status") or "unknown", 0) + 1
            continue
        counters["ok"] += 1
        version = str(doc.get("questionSetVersion") or "(no-stamp)")
        for key, view in (extractor(doc) or {}).items():
            b = buckets.setdefault((version, key), {
                "n": 0, "choice_counts": {}, "confs": [], "tops": [], "hstds": [],
                "scores": [], "escape": 0, "no_prob": 0, "no_conf": 0})
            b["n"] += 1
            conf = view.get("confidence")
            if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                b["confs"].append(float(conf))
            else:
                b["no_conf"] += 1
            prob = view.get("probabilities")
            if isinstance(prob, dict) and prob:
                vals = [v for v in prob.values()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if vals:
                    b["tops"].append(max(vals))
                    hs = hist_std(prob)
                    if hs is not None and view.get("type") == "score":
                        b["hstds"].append(hs)
                else:
                    b["no_prob"] += 1
            else:
                b["no_prob"] += 1
            choice = view.get("choice")
            if choice is not None:
                b["choice_counts"][str(choice)] = b["choice_counts"].get(str(choice), 0) + 1
                if str(choice) in ESCAPE_CHOICES:
                    b["escape"] += 1
            score = view.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                b["scores"].append(float(score))
    return {"buckets": buckets, "counters": counters}


def summarize_bucket(b: dict) -> dict:
    """累积器 → 单行摘要。"""
    n = b["n"]
    top_choices = sorted(b["choice_counts"].items(), key=lambda kv: -kv[1])[:3]
    out = {"n": n,
           "top3": " ".join(f"{k}×{v}" for k, v in top_choices) or "-",
           "score_mean": round(sum(b["scores"]) / len(b["scores"]), 1) if b["scores"] else None,
           "escape_pct": round(b["escape"] * 100 / n, 1) if n else None,
           "conf_p50": pct(b["confs"], 50), "conf_p90": pct(b["confs"], 90),
           "conf_lt060_pct": round(sum(1 for c in b["confs"] if c < HESITANT_THRESHOLD) * 100
                                   / len(b["confs"]), 1) if b["confs"] else None,
           "top_p50": pct(b["tops"], 50), "top_p90": pct(b["tops"], 90),
           "top_lt060_pct": round(sum(1 for t in b["tops"] if t < HESITANT_THRESHOLD) * 100
                                  / len(b["tops"]), 1) if b["tops"] else None,
           "hstd_p50": pct(b["hstds"], 50),
           "no_conf_n": b["no_conf"], "no_prob_n": b["no_prob"]}
    return out


def render_markdown(all_stats: dict[str, dict]) -> str:
    lines = ["# jev 题目集置信度全景（自动生成，只读统计）",
             "",
             f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M')}",
             f"- 骑墙阈值：top 概率/confidence < {HESITANT_THRESHOLD}（复核工作台同口径）",
             "- confP50/P90=模型自报 confidence；topP50/P90=probabilities 最大值；"
             "hstdP50=score 题档位直方图标准差（越大越犹豫）",
             "- noConf/noProb=落库结构缺失计数（五链未提取 confidence / 部分题未存 probabilities，",
             "  属解析层丢弃证据，见 review §三；非模型行为）",
             ""]
    for spec, stats in zip(COLLECTION_SPECS, [all_stats[s["collection"]] for s in COLLECTION_SPECS]):
        c = stats["counters"]
        lines += [f"## {spec['label']} — `{spec['collection']}`", "",
                  f"ok={c['ok']}，非ok={c['not_ok']}"
                  + (f"（{c['not_ok_detail']}）" if c["not_ok_detail"] else ""), "",
                  "| 版本段 | 题 | n | 答案top3/score均值 | confP50 | confP90 | conf<60% | topP50 | topP90 | top<60% | hstdP50 | 逃生% | noConf | noProb |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        rows = sorted(stats["buckets"].items(), key=lambda kv: (kv[0][0], kv[0][1]))
        for (version, key), b in rows:
            s = summarize_bucket(b)
            score_cell = f"mean={s['score_mean']}" if s["score_mean"] is not None else s["top3"]
            def f(v, suffix=""):
                return f"{v}{suffix}" if v is not None else "-"
            lines.append(
                f"| {version} | {key} | {s['n']} | {score_cell} "
                f"| {f(s['conf_p50'])} | {f(s['conf_p90'])} | {f(s['conf_lt060_pct'], '%')} "
                f"| {f(s['top_p50'])} | {f(s['top_p90'])} | {f(s['top_lt060_pct'], '%')} "
                f"| {f(s['hstd_p50'])} | {f(s['escape_pct'], '%')} "
                f"| {f(s['no_conf_n'])} | {f(s['no_prob_n'])} |")
        lines.append("")
    return "\n".join(lines)


# ── IO 层 ─────────────────────────────────────────────────────────────

def scan_collection(db, spec: dict) -> dict:
    docs = db[spec["collection"]].find(
        {"status": {"$in": ["ok", "degraded", "no_data"]}},
        {"answers": 1, "kind": 1, "origin": 1, "status": 1, "questionSetVersion": 1,
         "label": 1, "driverProbabilities": 1, "catalystDepth": 1, "catalystDepthProbabilities": 1,
         "freshness": 1, "buySideLogic": 1, "buySideProbabilities": 1,
         "stockPhasePosition": 1, "stockPhaseProbabilities": 1, "stockPhaseConfidence": 1,
         "phaseBand": 1, "phaseBandProbabilities": 1,
         "cycleStage": 1, "cycleStageProbabilities": 1,
         "relayPhase": 1, "relayPhaseProbabilities": 1, "relayMomentum": 1, "ladderHealth": 1,
         "moneyEffect": 1, "themePulse": 1, "relayIndex": 1, "leaderStrength": 1,
         "zhabanCause": 1, "zhabanCauseProbabilities": 1})
    return accumulate(docs, spec["extractor"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="jev 题目集置信度全景统计（只读）")
    ap.add_argument("--out", default=None, help="markdown 输出文件（缺省只打印 stdout）")
    args = ap.parse_args(argv)

    db = get_runtime_mongodb_database()
    all_stats = {}
    for spec in COLLECTION_SPECS:
        try:
            all_stats[spec["collection"]] = scan_collection(db, spec)
        except Exception as e:  # 集合缺失等：如实报错继续（fail-visible）
            all_stats[spec["collection"]] = {"buckets": {}, "counters": {"ok": 0, "not_ok": 0,
                                                                        "not_ok_detail": {f"scan_error:{type(e).__name__}": 1}}}
            print(f"[warn] {spec['collection']} 扫描失败：{type(e).__name__}: {e}", file=sys.stderr)
    md = render_markdown(all_stats)
    print(md)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(md, encoding="utf-8")
        print(f"\n[written] {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
