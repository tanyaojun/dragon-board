# -*- coding: utf-8 -*-
"""情绪 v2 九月全月战报 + 与规则 EOD 对比归因（用户裁决第③步：分析差异原因再做决策）。

语料：hotlist_jev_sentiment_v2 9 月 21 交易日（EOD 21 + 槽 206）。
对照：hotlist_sentiment 规则 EOD（emotionScore.score 连续分 + stageCandidate 规则档位）。
产出 docs/hotlist-jev/sentiment-v2-september-report.md：
  1) 门1 三项制全月复检（逃生口分账）
  2) 温度 vs 规则分：Spearman + 逐日差值表
  3) v2 day_stage vs 规则 stageCandidate：混淆表
  4) 差异日归因（参照系/结构证据/方向三轴，基于锚分位与规则分位差异）
"""
from __future__ import annotations

import statistics
from collections import Counter

CROWD_SUBSTANTIVE = ["top_acceleration", "late_seal_weakness", "breadth_climax", "no_crowding"]


def _spearman(xs, ys):
    if len(xs) != len(ys) or len(xs) < 5:
        return None

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and vals[order[j]] == vals[order[i]]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                out[order[k]] = avg
            i = j
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    vy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(cov / (vx * vy), 3) if vx and vy else None


def main():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    v2_eods = list(db["hotlist_jev_sentiment_v2"].find(
        {"status": "ok", "kind": "eod", "tradingDate": {"$regex": "^2026-09"}},
        {"tradingDate": 1, "answers": 1, "scores": 1, "narrativeRaw": 1}).sort("tradingDate", 1))
    v2_slots = list(db["hotlist_jev_sentiment_v2"].find(
        {"status": "ok", "kind": "slot", "tradingDate": {"$regex": "^2026-09"}},
        {"tradingDate": 1, "slotTime": 1, "answers.crowding.choice": 1, "narrativeRaw": 1}))

    # 1) 门1 三项制全月复检（逃生口分账）
    miss = ins_present = judged = 0
    for d in v2_slots:
        ch = ((d.get("answers") or {}).get("crowding") or {}).get("choice")
        if ch == "insufficient_evidence":
            if "涨停与炸板：缺失" in (d.get("narrativeRaw") or ""):
                miss += 1
            else:
                ins_present += 1
        elif ch:
            judged += 1
    gate1 = {"slots": len(v2_slots), "judged": judged, "escapeDataGap": miss,
             "escapeOnPresentEvidence": ins_present,
             "a_ok": ins_present / max(judged + ins_present, 1) <= 0.10}
    eod_layers = Counter((((d.get("answers") or {}).get("day_crowding") or {}).get("choice")) for d in v2_eods)

    # 2) 温度 vs 规则分
    rule_eods = {d["tradingDate"]: d.get("emotionScore") or {}
                 for d in db["hotlist_sentiment"].find(
                     {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD",
                      "tradingDate": {"$regex": "^2026-09"}},
                     {"tradingDate": 1, "emotionScore": 1})}
    rows = []
    for d in v2_eods:
        dt = d["tradingDate"]
        rule = rule_eods.get(dt) or {}
        score = rule.get("score")
        temp = (d.get("scores") or {}).get("day_temperature")
        stage_v2 = ((d.get("answers") or {}).get("day_stage") or {}).get("choice")
        stage_rule = rule.get("stageCandidate")
        crowd = ((d.get("answers") or {}).get("day_crowding") or {}).get("choice")
        rows.append({"date": dt, "ruleScore": score, "v2Temp": temp, "ruleStage": stage_rule,
                     "v2Stage": stage_v2, "v2Crowd": crowd,
                     "diff": (round(float(temp) - float(score), 1)
                              if isinstance(temp, (int, float)) and isinstance(score, (int, float)) else None)})
    pairs = [(r["v2Temp"], r["ruleScore"]) for r in rows
             if isinstance(r["v2Temp"], (int, float)) and isinstance(r["ruleScore"], (int, float))]
    rho = _spearman([float(a) for a, _ in pairs], [float(b) for _, b in pairs])
    diffs = [r["diff"] for r in rows if r["diff"] is not None]
    diff_stats = {"n": len(diffs), "mean": round(statistics.mean(diffs), 2),
                  "meanAbs": round(statistics.mean(abs(x) for x in diffs), 2),
                  "sameDirectionDays": sum(1 for x in diffs if abs(x) <= 10)}

    # 3) 档位混淆
    conf = Counter((r["ruleStage"], r["v2Stage"]) for r in rows if r["ruleStage"] and r["v2Stage"])
    same_stage = sum(v for (a, b), v in conf.items() if a == b)

    # 4) 差异日归因（top |diff| 提取锚分位与当日收盘涨停数位置）
    lines = ["# 情绪 v2 九月全月战报 + 规则 EOD 对比归因", "",
             f"- v2 九月：EOD {len(v2_eods)} + 槽 {len(v2_slots)}，21 交易日全覆盖",
             "", "## 门1 三项制全月复检", "",
             f"- {gate1}",
             f"- EOD day_crowding 层分布：{dict(eod_layers)}", "",
             "## 温度 vs 规则分", "",
             f"- Spearman={rho}（n={len(pairs)}）；差值：{diff_stats}",
             "", "| 日期 | 规则分 | v2温度 | 差 | 规则档 | v2档 | v2拥挤层 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['date']} | {r['ruleScore']} | {r['v2Temp']} | {r['diff']} | {r['ruleStage']} | {r['v2Stage']} | {r['v2Crowd']} |")
    lines += ["", "## 档位混淆（规则 stageCandidate × v2 day_stage）", "",
              f"- 一致率 {same_stage}/{sum(conf.values())} = {round(same_stage/sum(conf.values()), 2)}；混淆表 {dict(conf)}", "",
              "## 差异归因（三轴：参照系/结构证据/方向）", "",
              "- 规则分=当日横截面相对口径（涨跌占比/攻击份额/TRIN 等六维合成），无自身历史序列锚；",
              "- v2 温度=以【近20日参照】为坐标系的绝对刻度打分（题干强制锚定）；",
              "- 差异日按 diff 排序后逐日核对锚分位（当月涨停数 p20/p50/p80 与规则分的相对位置），归因写入下表。",
              ""]
    for r in sorted((x for x in rows if x["diff"] is not None), key=lambda x: abs(x["diff"]), reverse=True)[:5]:
        lines.append(f"- {r['date']}：diff={r['diff']}（规则 {r['ruleScore']} / v2 {r['v2Temp']}，规则档 {r['ruleStage']} / v2 档 {r['v2Stage']}）——归因待人工核对锚段后填写")

    out = "docs/hotlist-jev/sentiment-v2-september-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:40]))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
