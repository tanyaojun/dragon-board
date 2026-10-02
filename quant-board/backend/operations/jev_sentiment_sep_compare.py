# -*- coding: utf-8 -*-
"""情绪 v2 Q3（7-9 月）战报 + 与规则 EOD 对比归因（用户裁决：季度对比找完整差异再定方向）。

语料：hotlist_jev_sentiment_v2 Q3 交易日（7 月无锚/8 月半锚/9 月满锚=数据梯度天然实验）。
锚深度列=该 EOD 日锚窗口净样本数（build_history_stats 口径），用于检验"锚越满与规则分越收敛"假设。
对照：hotlist_sentiment 规则 EOD（emotionScore.score 连续分 + stageCandidate 规则档位）。
产出 docs/hotlist-jev/sentiment-v2-q3-report.md：
  1) 门1 三项制全月复检（逃生口分账）
  2) 温度 vs 规则分：Spearman + 逐日差值表
  3) v2 day_stage vs 规则 stageCandidate：混淆表
  4) 差异日归因（参照系/结构证据/方向三轴，基于锚分位与规则分位差异）
"""
from __future__ import annotations

import statistics
from collections import Counter

CROWD_SUBSTANTIVE = ["top_acceleration", "late_seal_weakness", "breadth_climax", "no_crowding"]
STAGE_MAP = {"冰点": "ice", "启动": "start", "发酵": "ferment", "高潮": "climax", "退潮": "retreat"}


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
    q3 = {"$regex": "^2026-0[789]"}
    v2_eods = list(db["hotlist_jev_sentiment"].find(
        {"status": "ok", "kind": "eod", "tradingDate": q3},
        {"tradingDate": 1, "answers": 1, "scores": 1, "narrativeRaw": 1}).sort("tradingDate", 1))
    v2_slots = list(db["hotlist_jev_sentiment"].find(
        {"status": "ok", "kind": "slot", "tradingDate": q3},
        {"tradingDate": 1, "slotTime": 1, "answers.crowding.choice": 1, "narrativeRaw": 1,
         "evidenceRaw.limit.zhabanRate": 1}))

    # 1) 门1 三项制全月复检（逃生口分账）
    miss = anchor_gap = genuine = judged = 0
    for d in v2_slots:
        ch = ((d.get("answers") or {}).get("crowding") or {}).get("choice")
        has_rail = isinstance(((d.get("evidenceRaw") or {}).get("limit") or {}).get("zhabanRate"), (int, float))
        anchor_head = (d.get("narrativeRaw") or "").split("【当前帧证据】")[0]
        # 两种锚缺失形态都算锚缺口：指标样本不足（历史样本不足）/窗口全空（历史参照缺失）
        anchor_ok = "历史样本不足" not in anchor_head and "历史参照缺失" not in anchor_head
        if ch == "insufficient_evidence":
            if not has_rail:
                miss += 1
            elif not anchor_ok:
                anchor_gap += 1
            else:
                genuine += 1
        elif ch:
            judged += 1
    judgeable = judged + genuine
    gate1 = {"slots": len(v2_slots), "judged": judged, "escapeDataGap": miss,
             "escapeAnchorGap": anchor_gap, "genuineEscape": genuine,
             "a_ok": genuine / max(judgeable, 1) <= 0.10}
    eod_layers = Counter((((d.get("answers") or {}).get("day_crowding") or {}).get("choice")) for d in v2_eods)

    # 2) 温度 vs 规则分
    rule_eods = {d["tradingDate"]: d.get("emotionScore") or {}
                 for d in db["hotlist_sentiment"].find(
                     {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD",
                      "tradingDate": q3},
                     {"tradingDate": 1, "emotionScore": 1})}
    # 锚深度：每 EOD 日锚窗口净样本（与 runner build_history_stats 同口径）
    from backend.operations.jev_sentiment_pilot import build_history_stats

    anchor_depth = {}
    rows = []
    for d in v2_eods:
        dt = d["tradingDate"]
        stats = build_history_stats(db, "dragonboard_live", dt)
        anchor_depth[dt] = len(stats)
        rule = rule_eods.get(dt) or {}
        score = rule.get("score")
        temp = (d.get("scores") or {}).get("day_temperature")
        stage_v2 = ((d.get("answers") or {}).get("day_stage") or {}).get("choice")
        stage_rule = rule.get("stageCandidate")
        stage_rule_en = STAGE_MAP.get(stage_rule)
        crowd = ((d.get("answers") or {}).get("day_crowding") or {}).get("choice")
        rows.append({"date": dt, "ruleScore": score, "v2Temp": temp, "ruleStage": stage_rule,
                     "ruleStageEn": stage_rule_en,
                     "v2Stage": stage_v2, "v2Crowd": crowd, "anchorN": anchor_depth.get(dt, 0),
                     "month": dt[:7],
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
    conf = Counter((r["ruleStageEn"], r["v2Stage"]) for r in rows if r["ruleStageEn"] and r["v2Stage"])
    same_stage = sum(v for (a, b), v in conf.items() if a == b)
    # 分月拆解（数据梯度检验：无锚 7 月/半锚 8 月/满锚 9 月）
    by_month = {}
    for m in ("2026-07", "2026-08", "2026-09"):
        mr = [r for r in rows if r["month"] == m]
        mp = [(float(r["v2Temp"]), float(r["ruleScore"])) for r in mr
              if isinstance(r["v2Temp"], (int, float)) and isinstance(r["ruleScore"], (int, float))]
        md = [r["diff"] for r in mr if r["diff"] is not None]
        ms = sum(1 for r in mr if r["ruleStageEn"] and r["v2Stage"] and r["ruleStageEn"] == r["v2Stage"])
        by_month[m] = {"days": len(mr), "rho": _spearman([a for a, _ in mp], [b for _, b in mp]),
                       "meanDiff": round(statistics.mean(md), 2) if md else None,
                       "meanAbsDiff": round(statistics.mean(abs(x) for x in md), 2) if md else None,
                       "stageAgree": f"{ms}/{len(mr)}",
                       "anchorN": sorted({r["anchorN"] for r in mr})}

    # 4) 差异日归因（top |diff| 提取锚分位与当日收盘涨停数位置）
    lines = ["# 情绪 v2 Q3（7-9 月）战报 + 规则 EOD 对比归因", "",
             f"- v2 Q3：EOD {len(v2_eods)} + 槽 {len(v2_slots)}", "",
             "## 分月数据梯度（无锚→半锚→满锚 天然实验）", "",
             f"- {by_month}", "",
             "## 门1 三项制全月复检", "",
             f"- {gate1}",
             f"- 三分账语义：数据缺口（无炸板率证据）/锚缺口（证据在场但参照轨不足或缺失）/真违规（证据+轨均在仍逃生）",
             f"- EOD day_crowding 层分布：{dict(eod_layers)}", "",
             "## 温度 vs 规则分", "",
             f"- Spearman={rho}（n={len(pairs)}）；差值：{diff_stats}",
             "", "| 日期 | 锚N | 规则分 | v2温度 | 差 | 规则档 | v2档 | v2拥挤层 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['date']} | {r['anchorN']} | {r['ruleScore']} | {r['v2Temp']} | {r['diff']} | {r['ruleStage']} | {r['v2Stage']} | {r['v2Crowd']} |")
    lines += ["", "## 档位混淆（规则 stageCandidate × v2 day_stage）", "",
              f"- 一致率（经词汇映射）{same_stage}/{sum(conf.values())} = {round(same_stage/sum(conf.values()), 2)}；混淆表 {dict(conf)}", "",
              "## 差异归因（三轴：参照系/结构证据/方向）", "",
              "- 规则分=当日横截面相对口径（涨跌占比/攻击份额/TRIN 等六维合成），无自身历史序列锚；",
              "- v2 温度=以【近20日参照】为坐标系的绝对刻度打分（题干强制锚定）；",
              "- 差异日按 diff 排序后逐日核对锚分位（当月涨停数 p20/p50/p80 与规则分的相对位置），归因写入下表。",
              ""]
    for r in sorted((x for x in rows if x["diff"] is not None), key=lambda x: abs(x["diff"]), reverse=True)[:5]:
        lines.append(f"- {r['date']}：diff={r['diff']}（规则 {r['ruleScore']} / v2 {r['v2Temp']}，规则档 {r['ruleStage']} / v2 档 {r['v2Stage']}）——归因待人工核对锚段后填写")

    out = "docs/hotlist-jev/sentiment-v2-q3-report.md"
    # 重跑保留人工归因收尾段（脚本只负责其生成部分，不覆盖人工分析）
    manual = ""
    try:
        with open(out, "r", encoding="utf-8") as f:
            old = f.read()
        marker = "# 差异完整分析"
        if marker in old:
            manual = old[old.index(marker):]
    except FileNotFoundError:
        pass
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n\n---\n\n" + manual if manual else ""))
    print("\n".join(lines[:40]))
    print(f"-> {out}{'（保留人工归因段 ' + str(len(manual)) + ' 字符）' if manual else ''}")


if __name__ == "__main__":
    main()
