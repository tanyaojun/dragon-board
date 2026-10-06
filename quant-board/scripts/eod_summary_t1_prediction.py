# -*- coding: utf-8 -*-
"""EOD 终值 vs 全天汇总：T+1 预测力对照实验（只读）。

预登记：quant-board/docs/hotlist-jev/eod-summary-t1-prediction-preregistration.md
（含 §四.9 跑数前修订记录：C9/Y4/Y5/Y6 自算口径）。

数据源（全部只读 find，不写库不写 Redis，零模型调用）：
  dragon_board_quant.hotlist_sentiment   —— EOD/槽位情绪文档（score-v1）
  dragon_board_quant.snapshot_stock_rows —— 价格行（price/amount）

用法：
  .venv/Scripts/python.exe scripts/eod_summary_t1_prediction.py
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient  # noqa: E402

# ---------------------------------------------------------------- 口径常量（预登记冻结）
CANON_SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]
MORNING_SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30"]
PM_SLOTS = ["13:00", "13:30", "14:00", "14:30", "15:00"]
MIN_SLOTS = 8           # 有效日门槛：≥8 槽有分
MIN_MATCHED = 20        # 价格靶最低匹配股数
MIN_AMOUNT_COVER = 0.8  # C9 留存股 amount 覆盖率门槛
BOOT_N = 1000
BOOT_SEED = 20261006
CANDIDATES = ["C1_eod", "C2_mean_all", "C3_mean_pm", "C4_tail2", "C5_first",
              "C6_slope_day", "C7_tail_lift", "C8_pm_fade", "C9_vol_trend", "C9b_day_vs_yday"]
PRICE_TARGETS = {"Y4_gap_price", "Y5_close_ret", "Y6_gap_fade_rate"}
TARGETS = ["Y1_gap_score", "Y2_fade_score", "Y3_delta_eod", "Y4_gap_price", "Y5_close_ret", "Y6_gap_fade_rate"]

DB_URI = "mongodb://127.0.0.1:27017"
DB_NAME = "dragon_board_quant"
DATASET_ID = "dragonboard_live"
SNAPSHOT_TYPE = "half_hour"


# ---------------------------------------------------------------- 基础统计（纯 python，避免 scipy 依赖）
def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / (sxx * syy) ** 0.5


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 4:
        return None
    return _pearson(_rank(xs), _rank(ys))


def partial_spearman(xs: list[float], ys: list[float], cs: list[float]) -> float | None:
    """控制 c 后 x、y 的偏相关（秩空间线性残差化）。"""
    rx, ry, rc = _rank(xs), _rank(ys), _rank(cs)

    def resid(a: list[float], b: list[float]) -> list[float]:
        n = len(a)
        mb, ma = sum(b) / n, sum(a) / n
        sbb = sum((v - mb) ** 2 for v in b)
        beta = sum((bb - mb) * (aa - ma) for bb, aa in zip(b, a)) / sbb if sbb > 0 else 0.0
        alpha = ma - beta * mb
        return [aa - (alpha + beta * bb) for aa, bb in zip(a, b)]

    return _pearson(resid(rx, rc), resid(ry, rc))


def bootstrap_ci(xs: list[float], ys: list[float], rng: random.Random) -> tuple[float, float] | None:
    n = len(xs)
    if n < 4:
        return None
    stats = []
    for _ in range(BOOT_N):
        idx = [rng.randrange(n) for _ in range(n)]
        r = spearman([xs[i] for i in idx], [ys[i] for i in idx])
        if r is not None:
            stats.append(r)
    if len(stats) < BOOT_N * 0.8:
        return None
    stats.sort()
    return stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats))]


def tercile_spread(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 6:
        return None
    order = sorted(range(n), key=lambda i: xs[i])
    k = n // 3
    lo = [ys[i] for i in order[:k]]
    hi = [ys[i] for i in order[-k:]]
    return sum(hi) / len(hi) - sum(lo) / len(lo)


# ---------------------------------------------------------------- 数据装载（只读）
def load_sentiment(db):
    """返回 (EOD 分, 逐槽分, (date,slot)->snapshotId)。

    同槽多文档（9-28 起细粒度链并存）：优先有分者、computedAt 最新者；snapshotId 跟随入选文档。
    """
    eod: dict[str, float] = {}
    slot_best: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    sid_best: dict[tuple[str, str], tuple[str, str]] = {}

    proj = {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1, "snapshotId": 1, "computedAt": 1}
    cursor = db["hotlist_sentiment"].find(
        {"datasetId": DATASET_ID, "snapshotType": SNAPSHOT_TYPE,
         "slotTime": {"$in": CANON_SLOTS + ["EOD"]}}, proj
    )
    for doc in cursor:
        d = str(doc.get("tradingDate") or "")
        s = str(doc.get("slotTime") or "")
        if not d:
            continue
        es = doc.get("emotionScore") or {}
        score = es.get("score") if isinstance(es.get("score"), (int, float)) else None
        ca = str(doc.get("computedAt") or "")
        sid = str(doc.get("snapshotId") or "")
        if s == "EOD":
            if score is not None:
                eod[d] = float(score)  # 同日多行时后写覆盖（集合 _id 唯一，实际单行）
            continue
        key = (d, s)
        prev = sid_best.get(key)
        if sid and (prev is None or ca >= prev[1]):
            sid_best[key] = (sid, ca)
        if score is None:
            continue
        cur = slot_best[d].get(s)
        if cur is None or ca >= cur[1]:
            slot_best[d][s] = (float(score), ca)
    slot_scores = {d: {s: v[0] for s, v in byslot.items()} for d, byslot in slot_best.items()}
    sids = {k: v[0] for k, v in sid_best.items()}
    return eod, slot_scores, sids


def load_rows_by_snapshot(db, sids: list[str]) -> dict[str, dict[str, dict]]:
    """snapshotId -> {code: {price, amount}}（同码多行取首行，重复计数披露）。"""
    out: dict[str, dict[str, dict]] = {}
    dup = 0
    chunk = 80
    for i in range(0, len(sids), chunk):
        for row in db["snapshot_stock_rows"].find(
            {"snapshotId": {"$in": sids[i:i + chunk]}},
            {"snapshotId": 1, "code": 1, "price": 1, "amount": 1},
        ):
            sid = row.get("snapshotId")
            code = str(row.get("code") or "")
            if not sid or not code:
                continue
            bucket = out.setdefault(sid, {})
            if code in bucket:
                dup += 1
                continue
            price = row.get("price")
            amount = row.get("amount")
            bucket[code] = {
                "price": float(price) if isinstance(price, (int, float)) and float(price) > 0 else None,
                "amount": float(amount) if isinstance(amount, (int, float)) and float(amount) >= 0 else None,
            }
    if dup:
        print(f"[披露] stock_rows 同码重复行 {dup} 条（取首行）")
    return out


# ---------------------------------------------------------------- 日级记录构建
def build_days(eod, slot_scores, sids, rows_by_snapshot, trading_dates):
    """交易日 → 候选 C1-C9b 与靶 Y1-Y6（缺项 None，计数在报告层披露）。"""
    days: dict[str, dict] = {}
    for d in trading_dates:
        byslot = slot_scores.get(d) or {}
        if len(byslot) < MIN_SLOTS:
            continue
        sc = {s: byslot[s] for s in CANON_SLOTS if s in byslot}
        vals = list(sc.values())
        e = sc.get("15:00")
        first = sc.get("09:30")
        rec: dict = {"tradingDate": d, "slots": sc}
        rec["C1_eod"] = e
        rec["C2_mean_all"] = sum(vals) / len(vals)
        pm = [sc[s] for s in PM_SLOTS if s in sc]
        rec["C3_mean_pm"] = sum(pm) / len(pm) if pm else None
        tail = [sc[s] for s in ("14:30", "15:00") if s in sc]
        rec["C4_tail2"] = sum(tail) / len(tail) if len(tail) == 2 else None
        rec["C5_first"] = first
        rec["C6_slope_day"] = e - first if (e is not None and first is not None) else None
        rec["C7_tail_lift"] = e - min(vals) if e is not None else None
        m_vals = [sc[s] for s in MORNING_SLOTS if s in sc]
        rec["C8_pm_fade"] = first - min(m_vals) if (first is not None and m_vals) else None
        days[d] = rec

    # T+1 分数靶
    for i, d in enumerate(trading_dates[:-1]):
        rec = days.get(d)
        nxt = days.get(trading_dates[i + 1])
        if not rec or not nxt:
            continue
        e0 = rec["C1_eod"]
        nfirst = nxt["slots"].get("09:30")
        ne = nxt["C1_eod"]
        rec["Y1_gap_score"] = nfirst - e0 if (nfirst is not None and e0 is not None) else None
        rec["Y2_fade_score"] = ne - nfirst if (ne is not None and nfirst is not None) else None
        rec["Y3_delta_eod"] = ne - e0 if (ne is not None and e0 is not None) else None

    # 价格靶（T+0 15:00 池 → T+1 9:30 / 15:00 同码匹配）
    for i, d in enumerate(trading_dates[:-1]):
        rec = days.get(d)
        if not rec:
            continue
        t0, t1 = d, trading_dates[i + 1]
        sid015 = sids.get((t0, "15:00"))
        sid1930 = sids.get((t1, "09:30"))
        sid115 = sids.get((t1, "15:00"))
        if not (sid015 and sid1930 and sid115):
            continue
        r015 = rows_by_snapshot.get(sid015) or {}
        r1930 = rows_by_snapshot.get(sid1930) or {}
        r115 = rows_by_snapshot.get(sid115) or {}
        gaps, closes, fades = [], [], []
        both = 0
        eq = 0
        for code, r in r015.items():
            p0 = r["price"]
            p1930 = (r1930.get(code) or {}).get("price")
            p115 = (r115.get(code) or {}).get("price")
            if p0 and p1930:
                gaps.append(p1930 / p0 - 1)
                if abs(p1930 - p0) < 1e-9:
                    eq += 1
            if p0 and p115:
                closes.append(p115 / p0 - 1)
            if p0 and p1930 and p115:
                both += 1
                fades.append(1 if (p1930 / p0 - 1 >= 0.01 and p115 < p1930) else 0)
        rec["_matched_930"] = len(gaps)
        rec["_matched_1500"] = len(closes)
        # 预登记修订 2：9:30 帧携带前收价（精确相等占比>30%）→ 该对 Y4/Y6 不可信，记 None
        stale = bool(gaps) and eq / len(gaps) > 0.3
        rec["_stale_open"] = stale
        rec["Y4_gap_price"] = None if stale else (sum(gaps) / len(gaps) if len(gaps) >= MIN_MATCHED else None)
        rec["Y5_close_ret"] = sum(closes) / len(closes) if len(closes) >= MIN_MATCHED else None
        rec["Y6_gap_fade_rate"] = None if stale else (sum(fades) / len(fades) if both >= MIN_MATCHED else None)

    # C9 vol_trend / C9b day_vs_yday（amount 覆盖窗内有效，留存股口径）
    for i, d in enumerate(trading_dates):
        rec = days.get(d)
        if not rec or i == 0:
            continue
        prev_d = trading_dates[i - 1]
        sid_t15 = sids.get((d, "15:00"))
        sid_p15 = sids.get((prev_d, "15:00"))
        sid_am = sids.get((d, "11:30"))
        sid_pm = sids.get((d, "13:00"))
        if not (sid_t15 and sid_p15 and sid_am and sid_pm):
            continue
        rt15 = rows_by_snapshot.get(sid_t15) or {}
        rp15 = rows_by_snapshot.get(sid_p15) or {}
        ram = rows_by_snapshot.get(sid_am) or {}
        rpm = rows_by_snapshot.get(sid_pm) or {}
        retained = [c for c in rt15 if c in rp15]
        if len(retained) < MIN_MATCHED:
            continue

        def cover(m: dict) -> float:
            have = sum(1 for c in retained if (m.get(c) or {}).get("amount") is not None)
            return have / len(retained)

        if min(cover(rt15), cover(ram), cover(rpm), cover(rp15)) < MIN_AMOUNT_COVER:
            continue
        am_total = sum(((ram.get(c) or {}).get("amount")) or 0 for c in retained)
        pm_start = sum(((rpm.get(c) or {}).get("amount")) or 0 for c in retained)
        pm_end = sum(((rt15.get(c) or {}).get("amount")) or 0 for c in retained)
        prev_total = sum(((rp15.get(c) or {}).get("amount")) or 0 for c in retained)
        if am_total > 0:
            rec["C9_vol_trend"] = (pm_end - pm_start) / am_total - 1
        if prev_total > 0:
            rec["C9b_day_vs_yday"] = pm_end / prev_total - 1
    return days


# ---------------------------------------------------------------- 报告
def _fmt(v, pct=False):
    if v is None:
        return "--"
    return f"{v * 100:+.2f}%" if pct else f"{v:+.3f}"


def _regime(d: str) -> str:
    return "4-6月" if d <= "2026-06-30" else "7-9月"


def main():
    rng = random.Random(BOOT_SEED)
    db = MongoClient(DB_URI, serverSelectionTimeoutMS=5000)[DB_NAME]
    eod, slot_scores, sids = load_sentiment(db)
    trading_dates = sorted(eod)
    n_valid = sum(1 for d in trading_dates if len(slot_scores.get(d) or {}) >= MIN_SLOTS)
    print(f"EOD 文档 {len(trading_dates)} 日（{trading_dates[0]} → {trading_dates[-1]}）；"
          f"逐槽有效日（≥{MIN_SLOTS} 槽有分）{n_valid} 日；bootstrap n={BOOT_N} seed={BOOT_SEED}")

    need_sids = sorted({v for v in sids.values() if v})
    print(f"加载价格行：{len(need_sids)} 帧 …")
    rows_by_snapshot = load_rows_by_snapshot(db, need_sids)
    days = build_days(eod, slot_scores, sids, rows_by_snapshot, trading_dates)

    score_only = [d for d in trading_dates if d in days and days[d].get("Y3_delta_eod") is not None]
    paired = [d for d in trading_dates if d in days and days[d].get("Y5_close_ret") is not None]
    amount_days = [d for d in trading_dates if d in days and days[d].get("C9_vol_trend") is not None]
    print(f"配对成功：分数靶 {len(score_only)} 日；价格靶 {len(paired)} 日；"
          f"成交额窗 {len(amount_days)} 日（{amount_days[0] if amount_days else '--'} → {amount_days[-1] if amount_days else '--'}）")
    match_low = [d for d in trading_dates if d in days and (days[d].get("_matched_930") or 0) < MIN_MATCHED
                 and (days[d].get("_matched_930") or 0) > 0]
    if match_low:
        print(f"[披露] 价格靶匹配股数 <{MIN_MATCHED}：{match_low}")
    stale_days = [d for d in trading_dates if d in days and days[d].get("_stale_open")]
    if stale_days:
        print(f"[披露] 9:30 帧前收价污染（精确相等占比>30%，Y4/Y6 记缺失，预登记修订 2）：{stale_days}")
    if not all(d in days and days[d].get("C5_first") is not None for d in score_only):
        no930 = [d for d in score_only if days[d].get("C5_first") is None]
        print(f"[披露] 9:30 槽分缺失 {len(no930)} 日（C5/C6/C8、Y1/Y2 相应缺项）：{no930[:8]}{'…' if len(no930) > 8 else ''}")

    def window_for(cand: str, target: str) -> list[str]:
        if cand in ("C9_vol_trend", "C9b_day_vs_yday"):
            base = amount_days
        elif target in PRICE_TARGETS:
            base = paired
        else:
            base = score_only
        return [d for d in base
                if (days.get(d) or {}).get(cand) is not None and (days.get(d) or {}).get(target) is not None]

    print("\n=== 主表：Spearman ρ [bootstrap 95% CI] ｜ 三分位多空差 Δ (n) ===")
    col_w = 30
    print(f"{'候选':<15}" + "".join(f"{t:<{col_w}}" for t in TARGETS))
    for c in CANDIDATES:
        if not any((days.get(d) or {}).get(c) is not None for d in trading_dates):
            continue
        cells = []
        for t in TARGETS:
            ds_list = window_for(c, t)
            xs = [(days[d] or {}).get(c) for d in ds_list]
            ys = [(days[d] or {}).get(t) for d in ds_list]
            r = spearman(xs, ys)
            ci = bootstrap_ci(xs, ys, rng)
            sp = tercile_spread(xs, ys)
            pct = t in PRICE_TARGETS
            rtxt = f"{r:+.2f}" if r is not None else "  --"
            citxt = f"[{ci[0]:+.2f},{ci[1]:+.2f}]" if ci else "[ --]"
            sptxt = _fmt(sp, pct) if sp is not None else "--"
            cells.append(f"{rtxt} {citxt} Δ{sptxt} ({len(xs)})")
        print(f"{c:<15}" + "".join(f"{cell:<{col_w}}" for cell in cells))

    print("\n=== 偏相关（控制 C1_eod 后对价格靶 Y5 的增量解释）===")
    for c in ("C6_slope_day", "C7_tail_lift", "C8_pm_fade", "C9_vol_trend", "C9b_day_vs_yday"):
        base = amount_days if c in ("C9_vol_trend", "C9b_day_vs_yday") else paired
        xs, ys, cs = [], [], []
        for d in base:
            rec = days.get(d) or {}
            if rec.get(c) is not None and rec.get("Y5_close_ret") is not None and rec.get("C1_eod") is not None:
                xs.append(rec[c])
                ys.append(rec["Y5_close_ret"])
                cs.append(rec["C1_eod"])
        pr = partial_spearman(xs, ys, cs)
        print(f"  {c:<16} partial ρ = {_fmt(pr)} (n={len(xs)})")

    print("\n=== 市况分层：水平类候选对 Y5 的 ρ（防 Simpson）===")
    for c in ("C1_eod", "C2_mean_all", "C4_tail2"):
        for reg in ("4-6月", "7-9月"):
            ds_list = [d for d in paired if _regime(d) == reg and (days[d] or {}).get(c) is not None]
            xs = [days[d][c] for d in ds_list]
            ys = [days[d]["Y5_close_ret"] for d in ds_list]
            print(f"  {c:<12} {reg}: ρ={_fmt(spearman(xs, ys))} (n={len(xs)})")

    print("\n=== H1 专项（高开低走 + 缩量 + 尾盘拉升 → T+1 砸？成交额窗内）===")
    flag, base_win = [], []
    for d in amount_days:
        rec = days.get(d) or {}
        f1, f2, f3, f4 = rec.get("C5_first"), rec.get("C8_pm_fade"), rec.get("C9_vol_trend"), rec.get("C7_tail_lift")
        if f1 is None or f2 is None or f3 is None or f4 is None:
            continue
        base_win.append(d)
        if f1 >= 60 and f2 >= 10 and f3 <= -0.05 and f4 >= 10:
            flag.append(d)
    print(f"  窗口基线 {len(base_win)} 日；H1 触发 {len(flag)} 日")
    if len(flag) >= 8:
        for t in ("Y4_gap_price", "Y5_close_ret", "Y6_gap_fade_rate"):
            fv = [days[d][t] for d in flag if days[d].get(t) is not None]
            bv = [days[d][t] for d in base_win if days[d].get(t) is not None]
            if fv and bv:
                fm, bm = sum(fv) / len(fv), sum(bv) / len(bv)
                print(f"  {t}: H1 均值 {_fmt(fm, True)} (n={len(fv)}) vs 窗基线 {_fmt(bm, True)} (n={len(bv)}) → 差 {_fmt(fm - bm, True)}")
    else:
        print("  触发 <8 日 → 按预登记「样本不足」结案，不追加条件（防打靶瞄准）")
        for d in flag:
            rec = days[d]
            print(f"    {d}: Y4={_fmt(rec.get('Y4_gap_price'), True)} Y5={_fmt(rec.get('Y5_close_ret'), True)} "
                  f"Y6={_fmt(rec.get('Y6_gap_fade_rate'), True)}")

    print("\n=== 多重比较诚实计数（9 候选 × 6 靶）===")
    hits = total = 0
    for c in CANDIDATES:
        for t in TARGETS:
            ds_list = window_for(c, t)
            xs = [(days[d] or {}).get(c) for d in ds_list]
            ys = [(days[d] or {}).get(t) for d in ds_list]
            r = spearman(xs, ys)
            ci = bootstrap_ci(xs, ys, rng)
            if r is None or ci is None:
                continue
            total += 1
            if abs(r) >= 0.2 and (ci[0] > 0 or ci[1] < 0):
                hits += 1
    print(f"  |ρ|≥0.2 且 CI 不跨零：{hits}/{total} 格（纯随机期望 ≈{total * 0.05:.0f} 格）")


if __name__ == "__main__":
    main()
