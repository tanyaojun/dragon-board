# -*- coding: utf-8 -*-
"""jev 阶段1 对比分析：hotlist_jev_sentiment(replay) vs 规则档位 vs 实际行情演化。

四组指标（只读，产出 markdown 报告）：
 1 档位对照：jev stage vs rule stage（一致率+混淆矩阵）
 2 日内前瞻：heating_30m / retreat_eod 分组 vs 下一槽炸板率与涨停数变化、尾盘退潮兑现
 3 次日溢价：crowding 分组 vs 次日晋级率与 lifecycle 恶化
 4 退化率：degraded/total + 错误分布

判定语义：PASS_CANDIDATE（有可消费增量）/ INSUFFICIENT（样本或区分度不足）/ REJECT（无增量）。
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict

from pymongo import MongoClient

DB = "dragon_board_quant"
EN2CN = {"ice": "冰点", "start": "启动", "ferment": "发酵", "climax": "高潮", "retreat": "退潮"}
STAGE_CN = ["冰点", "启动", "发酵", "高潮", "退潮"]
HEAT_ORDINAL = {"冰点": 0, "启动": 1, "发酵": 2, "高潮": 3, "退潮": 4}  # 热度序（退潮=高潮后回落，置末）
SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]


def _market_of(frame):
    ms = frame.get("marketStats") or {}
    zb = (ms.get("zhaban") or {}).get("rate")
    if zb is None:
        zb = ((frame.get("limitSummary") or {}).get("zhaban") or {}).get("rate")
    return {"zt": ms.get("ztCount"), "zhabanRate": zb}


def _promotion_of(frame):
    boards = (frame.get("marketStats") or {}).get("limitData") \
        or ((frame.get("limitSummary") or {}).get("continuousBoards") or {})
    yiban = boards.get("yiban") or 0
    promoted = sum(boards.get(k) or 0 for k in ("erban", "sanban", "sibanPlus"))
    return round(promoted / yiban, 3) if yiban else None


def load(db):
    jev = list(db["hotlist_jev_sentiment"].find({"origin": "replay"}))
    ok = [d for d in jev if d.get("status") == "ok" and d.get("answers")]
    dates = sorted({d["tradingDate"] for d in ok})
    frames = {(f["tradingDate"], f["slotTime"]): f for f in db["snapshot_frames"].find(
        {"type": "half_hour", "tradingDate": {"$in": dates}})}
    return jev, ok, dates, frames


def stage_agreement(ok):
    agree = sum(1 for d in ok if EN2CN.get(d["answers"]["stage"]["choice"]) == d.get("ruleStage"))
    conf = defaultdict(Counter)
    for d in ok:
        jev_s = EN2CN.get(d["answers"]["stage"]["choice"])
        conf[d.get("ruleStage")][jev_s] += 1
    return agree, len(ok), conf


def intraday_lookahead(ok, frames, dates):
    """heating_30m 分组 vs 下一槽炸板率变化；retreat_eod 高分组 vs 尾盘退潮兑现。"""
    by_slot = {(d["tradingDate"], d["slotKey"]): d for d in ok}
    heat_next, cool_tail = [], {"hit": 0, "miss": 0}
    for d in ok:
        date, slot = d["tradingDate"], d["slotKey"]
        if slot not in SLOTS[:-1]:
            continue
        i = SLOTS.index(slot)
        nxt = frames.get((date, SLOTS[i + 1]))
        cur = frames.get((date, slot))
        if nxt and cur:
            zb_delta = ((_market_of(nxt).get("zhabanRate") or 0) - (_market_of(cur).get("zhabanRate") or 0))
            heat_next.append((d["answers"]["heating_30m"]["noul"], zb_delta))
        heat = d["answers"]["heating_30m"]["noul"]
    hi = [dz for hz, dz in heat_next if hz > 0.6]
    lo = [dz for hz, dz in heat_next if hz < 0.4]
    retreat_calls = [d for d in ok if d["answers"]["retreat_eod"]["noul"] > 0.6
                     and d["slotKey"] in ("10:30", "11:30", "13:30", "14:00")]
    for d in retreat_calls:
        tail = by_slot.get((d["tradingDate"], "15:00"))
        tail_stage = tail["ruleStage"] if tail else None
        morning = [x for x in ok if x["tradingDate"] == d["tradingDate"] and x["slotKey"] == "09:30"]
        base = HEAT_ORDINAL.get(morning[0]["ruleStage"]) if morning else None
        if tail_stage and base is not None:
            ok_hit = HEAT_ORDINAL.get(tail_stage, 0) > base or tail_stage == "退潮"
            cool_tail["hit" if ok_hit else "miss"] += 1
    return {"heat_hi_mean_zb_delta": round(statistics.mean(hi), 2) if hi else None,
            "heat_lo_mean_zb_delta": round(statistics.mean(lo), 2) if lo else None,
            "n_hi": len(hi), "n_lo": len(lo),
            "retreat_calls": len(retreat_calls), **cool_tail}


def next_day_premium(ok, frames, dates):
    """crowding 分组 vs 次日晋级率（当日各槽均值）与次日 cooling 桶增量。"""
    date_idx = {d: i for i, d in enumerate(dates)}
    by_date_slots = defaultdict(list)
    for d in ok:
        by_date_slots[d["tradingDate"]].append(d)
    hi, lo = [], []
    for date, docs in by_date_slots.items():
        nxt = dates[date_idx[date] + 1] if date_idx[date] + 1 < len(dates) else None
        if not nxt:
            continue
        promos = [_promotion_of(frames[(nxt, s)]) for s in SLOTS if (nxt, s) in frames]
        promos = [p for p in promos if p is not None]
        if not promos:
            continue
        nxt_promo = statistics.mean(promos)
        for d in docs:
            cr = d["scores"].get("crowding")
            if cr is None:
                continue
            (hi if cr > 70 else lo if cr < 40 else []).append(nxt_promo)
    return {"crowd_hi_days": len(hi), "crowd_lo_days": len(lo),
            "hi_mean_next_promo": round(statistics.mean(hi), 3) if hi else None,
            "lo_mean_next_promo": round(statistics.mean(lo), 3) if lo else None}


def main():
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)[DB]
    jev, ok, dates, frames = load(db)
    lines = ["# Jev 阶段1 回放验证报告", "",
             f"- 样本：{len(ok)} ok / {len(jev)} 总（origin=replay），窗口 {dates[0]} → {dates[-1]}（{len(dates)} 交易日）", ""]
    deg = [d for d in jev if d.get("status") == "degraded"]
    nodata = [d for d in jev if d.get("status") == "no_data"]
    err_dist = Counter((d.get("errorCode"), (d.get("errorDetail") or "")[:60]) for d in deg)
    lines += ["## 4 退化率", "",
              f"- ok {len(ok)} / degraded {len(deg)} / no_data {len(nodata)}",
              f"- 错误分布：{dict(err_dist) if err_dist else '无'}", ""]
    agree, total, conf = stage_agreement(ok)
    lines += ["## 1 档位对照（jev choice vs 规则 stage）", "",
              f"- 一致率：{agree}/{total} = {round(agree / total * 100, 1)}%",
              "- 混淆矩阵（行=规则档，列=jev 档）：", ""]
    lines.append("| 规则\\jev | " + " | ".join(STAGE_CN) + " |")
    lines.append("|---|" + "---|" * len(STAGE_CN))
    for rs in STAGE_CN:
        row = [str(conf.get(rs, Counter()).get(js, 0)) for js in STAGE_CN]
        lines.append(f"| {rs} | " + " | ".join(row) + " |")
    lines.append("")
    intra = intraday_lookahead(ok, frames, dates)
    lines += ["## 2 日内前瞻", "",
              f"- heating_30m>0.6 组 下一槽炸板率变化均值：{intra['heat_hi_mean_zb_delta']}（n={intra['n_hi']}）",
              f"- heating_30m<0.4 组：{intra['heat_lo_mean_zb_delta']}（n={intra['n_lo']}）",
              f"- retreat_eod>0.6 且尾盘退潮兑现：{intra['hit']}/{intra['retreat_calls']}", ""]
    prem = next_day_premium(ok, frames, dates)
    lines += ["## 3 次日溢价（crowding 分组）", "",
              f"- crowding>70：{prem['crowd_hi_days']} 槽，次日晋级率均值 {prem['hi_mean_next_promo']}",
              f"- crowding<40：{prem['crowd_lo_days']} 槽，次日晋级率均值 {prem['lo_mean_next_promo']}", ""]
    lat = [d.get("latencyMs") or 0 for d in ok]
    tok = [(d.get("usage") or {}) for d in ok]
    lines += ["## 附：运行质量", "",
              f"- 延迟均值 {round(statistics.mean(lat))}ms / p95 {round(sorted(lat)[int(len(lat)*0.95)])}ms",
              f"- token 合计 in {sum(t.get('input_tokens', 0) for t in tok)} / out {sum(t.get('output_tokens', 0) for t in tok)}"
              f" ≈ ${round((sum(t.get('input_tokens', 0) for t in tok)*0.042 + sum(t.get('output_tokens', 0) for t in tok)*0.42)/1e6, 3)}", ""]
    out = "docs/hotlist-jev/phase1-replay-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("report ->", out)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
