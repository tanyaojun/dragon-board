# -*- coding: utf-8 -*-
"""M1 检验三关（ranktrend-phase-acceptance-design.md §5 M1 出口判据的实现）。

① 稳定性：帧级翻转率（unknown 转移不计分母）。
② 滞后性：对称互相关 lag∈[-5,+5]——c(k)=corr(phase(t), ret(t+k))；argmax>0=相位领先
   收益 k 步（有预测价值，好），argmax<0=相位落后收益（坏，设计判据：落后 ≤3 交易日
   才可跟随）；无正相关（c_max≤0）直接不合格。
③ 区分度：帧级池等权样本为主（~1071 样本，I3），日级为敏感性对照（抑制帧间自相关的
   保守复核）；scipy.stats.mannwhitneyu（tie 校正内置，M2）。
方向纪律（I2）：pass 必须 offenseMean > defenseMean；月度方向一致数自动汇总；
样本不足月进 skippedMonths（fail-visible，不静默）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scipy.stats import mannwhitneyu


def flip_rate(labels: list[str]) -> float:
    """相邻帧标签翻转率（unknown 转移不计分子分母）。"""
    flips = 0
    total = 0
    for a, b in zip(labels, labels[1:]):
        if a == "unknown" or b == "unknown":
            continue
        total += 1
        if a != b:
            flips += 1
    return flips / total if total else 0.0


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


def lag_check(daily: dict[str, str], rets: dict[str, float], max_lag: int = 5) -> dict:
    """对称互相关：c(k)=corr(phase(t), ret(t+k))，k∈[-max_lag,+max_lag]。

    k>0：相位领先收益（预测属性，好）；k<0：相位落后收益（跟随属性差，坏）。
    acceptable = 存在正相关 ∧ argmax ≥ -3（落后不超过 3 步）。
    注：lag 单位为"有效样本步"（跨周末/缺档日有失真，报告披露）。
    """
    days = sorted(daily)
    xs, ys = [], []
    for d0 in days:
        if d0 in rets and daily[d0] in ("offense", "defense"):
            xs.append(1.0 if daily[d0] == "offense" else 0.0)
            ys.append(float(rets[d0]))
    idx = {d: i for i, d in enumerate(days)}
    # 按日索引配对 phase(t) 与 ret(t+k)：k>0 相位领先收益，k<0 相位落后收益
    corr_by_lag: dict[int, float] = {}
    for k in range(-max_lag, max_lag + 1):
        px: list[float] = []
        py: list[float] = []
        for i, d in enumerate(days):
            j = i + k
            if not (0 <= j < len(days)):
                continue
            dj = days[j]
            if d in rets and dj in rets and daily[d] in ("offense", "defense"):
                px.append(1.0 if daily[d] == "offense" else 0.0)
                py.append(float(rets[dj]))
        corr_by_lag[k] = round(_pearson(px, py), 4)
    best = max(corr_by_lag, key=lambda k: corr_by_lag[k])
    c_max = corr_by_lag[best]
    return {"corrByLag": corr_by_lag, "argmaxLag": best, "maxCorr": c_max,
            "acceptable": (c_max > 0) and (best >= -3), "n": len(xs)}


def monthly_discrimination(phase_by_day: dict[str, str], rets: dict[str, float]) -> dict:
    """按自然月：offense vs defense 收益 Mann-Whitney（scipy，双尾）+ 方向判据。

    pass = offenseMean > defenseMean（方向）∧（p<0.05 或 |均值差|≥2%）。
    返回 {months, skippedMonths(两侧不足 2), directionConsistentMonths}。
    """
    by_month: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day, phase in phase_by_day.items():
        r = rets.get(day)
        if r is None or phase not in ("offense", "defense"):
            continue
        by_month[day[:7]][phase].append(float(r))
    rows, skipped, consistent = [], [], 0
    for month in sorted(by_month):
        a, b = by_month[month].get("offense", []), by_month[month].get("defense", [])
        if len(a) < 2 or len(b) < 2:
            skipped.append(month)
            continue
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        if ma > mb:
            consistent += 1
        p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
        rows.append({"month": month, "nOffense": len(a), "nDefense": len(b),
                     "offenseMean": round(ma, 5), "defenseMean": round(mb, 5),
                     "meanDiff": round(ma - mb, 5), "p": round(p, 5),
                     "pass": (ma > mb) and ((p < 0.05) or (abs(ma - mb) >= 0.02))})
    return {"months": rows, "skippedMonths": skipped, "directionConsistentMonths": consistent}


def frame_pool_returns(frames: list[dict], horizon: int) -> dict[int, float]:
    """帧级池等权 h{horizon} 前向收益：帧 i 的持仓池在帧 i+horizon 的价格变化均值。

    返回 {帧下标: 池收益}（按时间排序后下标）；池=该帧 stocks 全体（与交易池不同口径，
    M1 为市场层方向证据，报告披露）。
    """
    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    prices = {i: {str(s.get("code")): float(s["price"]) for s in (fr.get("stocks") or []) if s.get("price")}
              for i, fr in enumerate(ordered)}
    out: dict[int, float] = {}
    for i in range(len(ordered) - horizon):
        base, nxt = prices.get(i, {}), prices.get(i + horizon, {})
        rets = [nxt[c] / p - 1 for c, p in base.items() if c in nxt and p > 0]
        if rets:
            out[i] = sum(rets) / len(rets)
    return out


def daily_forward_returns(frames: list[dict], horizon: int) -> dict[str, float]:
    """日级敏感性对照：每日末槽（排序后该日最后一帧）池等权 h{horizon} 前向收益。"""
    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    per_frame = frame_pool_returns(ordered, horizon)
    last_of_day: dict[str, int] = {}
    for i, fr in enumerate(ordered):
        last_of_day[str(fr.get("tradingDate") or "")] = i
    return {day: per_frame[i] for day, i in last_of_day.items() if i in per_frame}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 检验三关")
    parser.add_argument("--frames", default="data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v2.json")  # Q1 定义 v2 同步
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-quality-v2.json")  # Q1 v2：防默认覆写 v1 历史产物
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    frame_rets_h1 = frame_pool_returns(ordered, 1)
    frame_rets_h8 = frame_pool_returns(ordered, 8)

    report: dict = {"frameCount": len(ordered), "candidates": {}}
    for key, cand in labels.get("candidates", {}).items():
        frame_labels = [x["phase"] for x in cand.get("frameLabels", [])]
        daily = cand.get("dailyByMajority") or {}
        # 帧级区分度（主证据，I3）：标签按 (day,slot) 重排后与排序帧同下标对齐
        # （打标顺序源自帧文件顺序，两处同键稳定排序 → 对齐成立）
        lab_ordered = sorted(cand.get("frameLabels", []),
                             key=lambda x: (x["tradingDate"], x["slotTime"]))
        pseudo_daily: dict[str, str] = {}
        pseudo_rets: dict[str, float] = {}
        for i, ret in frame_rets_h1.items():
            phase = lab_ordered[i]["phase"] if i < len(lab_ordered) else "unknown"
            if phase in ("offense", "defense"):
                k = f"{lab_ordered[i]['tradingDate']}#f{i}"
                pseudo_daily[k] = phase
                pseudo_rets[k] = ret
        frame_disc = monthly_discrimination(pseudo_daily, pseudo_rets)
        daily_rets_h1 = daily_forward_returns(frames, 1)
        daily_rets_h8 = daily_forward_returns(frames, 8)
        report["candidates"][key] = {
            "flipRate": round(flip_rate(frame_labels), 4),
            "lag": lag_check(daily, daily_rets_h1),
            "discriminationFrameH1": frame_disc,
            "discriminationDailyH1": monthly_discrimination(daily, daily_rets_h1),
            "discriminationDailyH8": monthly_discrimination(daily, daily_rets_h8),
        }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
