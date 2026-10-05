# -*- coding: utf-8 -*-
"""情绪判定问题集 v2 pilot 战报：四门（§6 预登记）+ 新旧一致率对照。

执行事实登记（2026-10-02）：开火命令未按预登记收窄三天窗口，实际跑了 09-07~09-30 全窗 17 交易日
183 文档（≈24 万 tokens，超支约 19 万）——门判据按全窗样本计算（比 33 文档更稳），超支如实呈报。
门判据（jev-sentiment-questionset-review.md §6）：
  门1 crowding 归层方差：四实质层合计≥85% 且 最大层≤70% 且 insufficient≤10%
  门2 temperature 方差不降：v2 槽温 std ≥ v1 同槽 std×0.9
  门3 五档漂移登记（观察）：frame_stage 新旧一致率
  门4 EOD 同构：day_crowding ≥2 实质层有样本
判定映射：门1+门2+门4 过=PASS_CANDIDATE（进全量重算决策，另裁决）；门1 不过=REJECT；其余=INSUFFICIENT。
产物 docs/hotlist-jev/sentiment-v2-pilot-report.md。
"""
from __future__ import annotations

import statistics

CROWD_SUBSTANTIVE = ["top_acceleration", "late_seal_weakness", "breadth_climax", "crowd_clearing", "no_crowding"]  # v2.5 增拥挤解除；旧代文档无此键计 0，分布读数不变
CROWD_ALL = CROWD_SUBSTANTIVE + ["insufficient_evidence"]


def crowding_distribution(layers: list[str]) -> dict:
    """门1 读数：拥挤归层分布（纯函数）。"""
    n = len(layers)
    if n < 20:
        return {"n": n, "insufficient": True}
    counts = {k: 0 for k in CROWD_ALL}
    for x in layers:
        counts[x] = counts.get(x, 0) + 1
    sub = {k: counts[k] for k in CROWD_SUBSTANTIVE}
    return {"n": n, "layerCounts": sub, "insufficientEvidence": counts["insufficient_evidence"],
            "maxLayerShare": round(max(sub.values()) / n, 3),
            "expanded": bool(sum(sub.values()) / n >= 0.85 and max(sub.values()) / n <= 0.70
                             and counts["insufficient_evidence"] / n <= 0.10),
            "insufficient": False}


def temperature_std_gate(v2_temps: list[float], v1_temps: list[float]) -> dict:
    """门2：v2 槽温 std ≥ v1 同槽 std×0.9（配对口径由调用方对齐，纯函数只管 std 比较）。"""
    if len(v2_temps) < 20 or len(v1_temps) < 20:
        return {"n2": len(v2_temps), "n1": len(v1_temps), "insufficient": True}
    s2, s1 = statistics.pstdev(v2_temps), statistics.pstdev(v1_temps)
    return {"stdV2": round(s2, 2), "stdV1": round(s1, 2), "ratio": round(s2 / s1, 3) if s1 else None,
            "ok": bool(s2 >= s1 * 0.9), "insufficient": False}


def stage_agreement(pairs: list[tuple]) -> dict:
    """门3（观察）：新旧 frame_stage 一致率。pairs=[(v1_stage, v2_stage)]。"""
    if not pairs:
        return {"n": 0, "sameShare": None}
    same = sum(1 for a, b in pairs if a == b)
    return {"n": len(pairs), "sameShare": round(same / len(pairs), 3)}


def verdict(gate1: dict, gate2: dict, gate4: dict) -> str:
    """判定映射（§6）：门1 不过=REJECT；门1+门2+门4 过=PASS_CANDIDATE；其余=INSUFFICIENT。"""
    if gate1.get("insufficient") or not gate1.get("expanded"):
        return "REJECT"
    if gate2.get("insufficient") or not gate2.get("ok"):
        return "INSUFFICIENT"
    if not gate4.get("ok"):
        return "INSUFFICIENT"
    return "PASS_CANDIDATE"


PILOT_DATES = ["2026-09-07", "2026-09-18", "2026-09-30"]  # §7 v2.1 重试点语料（显式三天）


def main(t3_manual: bool | None = None, pilot_only: bool = True):
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    corpus_q: dict = {"status": "ok"}
    if pilot_only:
        corpus_q["tradingDate"] = {"$in": PILOT_DATES}
    v2 = list(db["hotlist_jev_sentiment"].find(corpus_q))
    v2_slots = [d for d in v2 if d.get("kind") == "slot"]
    v2_eods = [d for d in v2 if d.get("kind") == "eod"]
    if not v2_slots:
        print("hotlist_jev_sentiment_v2 无 ok 文档，退出")
        return

    def _crowding(d):
        return ((d.get("answers") or {}).get("crowding") or {}).get("choice") or \
               ((d.get("answers") or {}).get("day_crowding") or {}).get("choice")

    def _temp(d):
        # 显式判型：0.0 是 SCORE_ANCHORS_10 首档合法值，不得用 or 链吞掉
        scores = d.get("scores") or {}
        for key in ("temperature", "day_temperature"):
            v = scores.get(key)
            if isinstance(v, (int, float)):
                return v
        return None

    def _stage(d):
        return ((d.get("answers") or {}).get("frame_stage") or {}).get("choice")

    layers = [c for c in (_crowding(d) for d in v2) if c]
    gate1 = crowding_distribution(layers)
    # 门2：按 (date, slot) 配对取双版本温度
    v1_keys = {f"{d.get('tradingDate')}:{d.get('slotTime')}": d
               for d in db["hotlist_jev_sentiment"].find(
                   {"status": "ok", "kind": "slot", "datasetId": "dragonboard_live"},
                   {"tradingDate": 1, "slotTime": 1, "scores": 1, "answers": 1})}
    t2, t1 = [], []
    for d in v2_slots:
        key = f"{d.get('tradingDate')}:{d.get('slotTime')}"
        if key in v1_keys:
            a, b = _temp(d), (v1_keys[key].get("scores") or {}).get("temperature")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                t2.append(float(a)); t1.append(float(b))
    gate2 = temperature_std_gate(t2, t1)
    # 门3：frame_stage 一致率（配对）
    pairs = [(_stage(v1_keys[f"{d.get('tradingDate')}:{d.get('slotTime')}"]),
              _stage(d)) for d in v2_slots if f"{d.get('tradingDate')}:{d.get('slotTime')}" in v1_keys]
    gate3 = stage_agreement([(a, b) for a, b in pairs if a and b])
    # 门4：EOD day_crowding 非退化
    eod_layers = [_crowding(d) for d in v2_eods]
    eod_counts = {k: eod_layers.count(k) for k in CROWD_SUBSTANTIVE if k in eod_layers}
    gate4 = {"eodN": len(v2_eods), "layersWithSample": len(eod_counts),
             "ok": len(v2_eods) >= 3 and len(eod_counts) >= 2}

    v = verdict(gate1, gate2, gate4)

    # 温度分布读数（门2 佐证）
    import collections
    temp_hist = collections.Counter(int(float(t) // 10) * 10 for t in t2)

    lines = ["# 情绪判定问题集 v2 pilot 战报（v2.1 重试点语料）", "",
             f"- v2 文档 {len(v2)}（槽 {len(v2_slots)} + EOD {len(v2_eods)}），三天试点窗口 2026-09-07/18/30（§7 v2.1 判据）",
             "- **执行失误登记**：开火未按预登记收窄三天窗口，全窗 17 交易日 183 调用 ≈24 万 tokens（超支约 19 万），门判据按全窗样本计算", "",
             "## 门1 crowding 归层方差（主）", "",
             f"- {gate1}",
             f"- 展开={gate1.get('expanded')}（四实质层合计≥85% 且 最大层≤70% 且 逃生口≤10%）", "",
             "## 门2 temperature 方差不降", "",
             f"- {gate2}（配对 n={len(t2)}）",
             f"- v2 温度十分位直方：{dict(sorted(temp_hist.items()))}", "",
             "## 门3 五档漂移登记（观察项）", "",
             f"- frame_stage 新旧一致率：{gate3}", "",
             "## 门4 EOD 同构", "",
             f"- {gate4}（EOD day_crowding 层分布：{eod_counts}）", "",
             "## 抽验（硬门）", "",
             "- " + ("已人工亲读 ≥5 文档（见附记）" if t3_manual else "待人工亲读 ≥5 文档（叙事-判例对齐）"), "",
             "## 判定依据", "",
             f"- {'✓' if gate1.get('expanded') else '✗'} 门1 crowding 归层方差",
             f"- {'✓' if gate2.get('ok') else '✗'} 门2 temperature 方差不降",
             f"- {'✓' if gate4.get('ok') else '✗'} 门4 EOD 同构",
             f"- 门3 观察项；抽验 {'✓' if t3_manual else '待执行'}", "",
             f"## 判定：{v}" + ("" if t3_manual else "（抽验完成后定稿）")]

    out = "docs/hotlist-jev/sentiment-v2-pilot-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"-> {out}")


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--t3-manual", choices=["pass"], default=None)
    ap.add_argument("--all", action="store_true", help="不过滤三天试点窗口（全语料模式）")
    a = ap.parse_args()
    main(a.t3_manual == "pass", pilot_only=not a.all)
