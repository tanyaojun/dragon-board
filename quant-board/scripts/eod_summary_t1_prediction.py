# -*- coding: utf-8 -*-
"""EOD 终值 vs 全天汇总：T+1 预测力对照实验（只读）。

预登记：quant-board/docs/hotlist-jev/eod-summary-t1-prediction-preregistration.md
- §四.9 修订 1/2：C9/Y4/Y5/Y6 自算口径、9:30 前收价 QA 过滤。
- 修订 3（2026-10-06 用户扩窗令+subagent 审查整合）：市场级量能候选 C9m/C9bm（TDX 指数 5 分钟
  线缓存）、指数级靶 Y7/Y8、池级 amount 用 turnover 等价前推全窗（实测逐行全等）、8 个脏日价格靶
  用 TDX 个股 5 分钟线修复值回填、H1 条件②重定标（原阈值在比率单位下 49/49 永真，P1-1）、
  偏相关统一同窗、bootstrap 每格独立 seed、交易日历桥接披露。
- Q2（4-15~6-30）/Q3（7-1~9-30）分季度独立成表（用户裁决 2026-10-06）。

数据源（全部只读 find，不写库不写 Redis，零模型调用）：
  dragon_board_quant.hotlist_sentiment   —— EOD/槽位情绪文档（score-v1）
  dragon_board_quant.snapshot_frames     —— sid 兜底定位
  dragon_board_quant.snapshot_stock_rows —— 价格行（price/amount/turnover）
  data/backups/eod-t1-backfill/*.json    —— TDX 补齐缓存（gitignore，生成见同目录脚本）

用法：
  .venv/Scripts/python.exe scripts/eod_summary_t1_prediction.py
"""
from __future__ import annotations

import json
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
MIN_AMOUNT_COVER = 0.8  # C9/C9b 留存股有效额覆盖率门槛（0/负额不算覆盖，07-21 伪值病灶）
BOOT_N = 1000
BOOT_SEED = 20261006
CANDIDATES = ["C1_eod", "C2_mean_all", "C3_mean_pm", "C4_tail2", "C5_first",
              "C6_slope_day", "C7_tail_lift", "C8_pm_fade",
              "C9_vol_trend", "C9b_day_vs_yday", "C9m_vol_fade", "C9bm_total_chg"]
POOL_CANDS = {"C9_vol_trend", "C9b_day_vs_yday"}
MKT_CANDS = {"C9m_vol_fade", "C9bm_total_chg"}
PRICE_TARGETS = {"Y4_gap_price", "Y5_close_ret", "Y6_gap_fade_rate"}
TARGETS = ["Y1_gap_score", "Y2_fade_score", "Y3_delta_eod", "Y4_gap_price", "Y5_close_ret",
           "Y6_gap_fade_rate", "Y7_index_gap", "Y8_index_ret"]
IDX_TARGETS = {"Y7_index_gap", "Y8_index_ret"}
Q2_END = "2026-06-30"
# 已知 2026 放假工作日（EOD 日历中的正常缺口）；此外的weekday缺口=采集停摆嫌疑，须披露
KNOWN_HOLIDAYS = {"2026-05-01", "2026-05-04", "2026-05-05", "2026-06-19", "2026-09-25",
                  "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"}

DB_URI = "mongodb://127.0.0.1:27017"
DB_NAME = "dragon_board_quant"
DATASET_ID = "dragonboard_live"
SNAPSHOT_TYPE = "half_hour"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "backups" / "eod-t1-backfill"


# ---------------------------------------------------------------- 基础统计（纯 python，无 scipy 依赖）
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


def bootstrap_ci(xs: list[float], ys: list[float], seed: str) -> tuple[float, float] | None:
    """每格独立 seed（审查 P2-5：共享 rng 会让计数格子随机漂移）。"""
    n = len(xs)
    if n < 4:
        return None
    rng = random.Random(f"{seed}|{BOOT_SEED}")
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

    注（审查 P2-6 勘误）：half_hour scope 内同槽无重复文档；跨类型并存链在
    five_minutes/quarter_hour snapshotType 下，被本函数的 snapshotType 过滤自然挡住。
    去重逻辑保留为无害防护（分数优先、computedAt 最新）。
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
                eod[d] = float(score)  # 同日多行时后写覆盖（实测同日 EOD 单行）
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


def load_sid_fallback(db, missing_pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """槽位文档缺 sid 时从 snapshot_frames 兜底定位（审查 P2-7：找回 07-06 等帧在文档缺日）。"""
    out: dict[tuple[str, str], str] = {}
    for key in missing_pairs:
        doc = db["snapshot_frames"].find_one(
            {"datasetId": DATASET_ID, "tradingDate": key[0], "slotTime": key[1]},
            {"snapshotId": 1}, sort=[("timestamp", -1)],
        )
        if doc and doc.get("snapshotId"):
            out[key] = str(doc["snapshotId"])
    return out


def load_rows_by_snapshot(db, sids: list[str]) -> dict[str, dict[str, dict]]:
    """snapshotId -> {code: {price, amount_eff}}。

    amount_eff = amount，缺则 turnover（审查 B 盘点：两者 8-9 月逐行全等 4616/4616，turnover 全窗在，
    等价前推）。0/负额不算有效（审查 P1-3：07-21 全帧零额伪值不得穿透覆盖门）。
    """
    out: dict[str, dict[str, dict]] = {}
    dup = 0
    sub_equal = 0
    sub_total = 0
    chunk = 80
    for i in range(0, len(sids), chunk):
        for row in db["snapshot_stock_rows"].find(
            {"snapshotId": {"$in": sids[i:i + chunk]}},
            {"snapshotId": 1, "code": 1, "price": 1, "amount": 1, "turnover": 1},
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
            amt, tov = row.get("amount"), row.get("turnover")
            amt = float(amt) if isinstance(amt, (int, float)) and float(amt) > 0 else None
            tov = float(tov) if isinstance(tov, (int, float)) and float(tov) > 0 else None
            if amt is not None and tov is not None:
                sub_total += 1
                if abs(amt - tov) < 1e-6:
                    sub_equal += 1
            bucket[code] = {
                "price": float(price) if isinstance(price, (int, float)) and float(price) > 0 else None,
                "amount_eff": amt if amt is not None else tov,
            }
    if dup:
        print(f"[披露] stock_rows 同码重复行 {dup} 条（取首行）")
    if sub_total:
        print(f"[披露] amount↔turnover 双字段行 {sub_total} 条，其中逐行全等 {sub_equal} 条"
              f"（{'等价前推成立' if sub_equal / sub_total > 0.99 else '等价性不成立，慎用'}）")
    return out


def load_market_cache() -> dict[str, dict]:
    """TDX 指数 5 分钟线派生日表（agent B 补齐产物；缺文件则市场级候选/靶全 None）。"""
    path = CACHE_DIR / "index_5min_daily.json"
    if not path.exists():
        print(f"[披露] 市场级缓存缺失：{path}（市场级候选/靶不可用）")
        return {}
    daily = json.loads(path.read_text(encoding="utf-8"))["daily"]
    return {k: v for k, v in daily.items() if isinstance(v.get("market_am"), (int, float))
            and isinstance(v.get("market_pm"), (int, float)) and v["market_am"] > 0 and v["market_pm"] > 0}


def load_repairs() -> dict[str, dict]:
    """8 个脏日（7 前收价污染 + 07-20 零额帧）的 TDX 修复聚合值。"""
    repairs: dict[str, dict] = {}
    for name in ("stale_days_repair.json", "zero_day_0721_repair.json"):
        path = CACHE_DIR / name
        if not path.exists():
            continue
        for d, payload in json.loads(path.read_text(encoding="utf-8"))["days"].items():
            rep = payload.get("repaired") or {}
            if isinstance(rep.get("y4_gap_price"), (int, float)):
                repairs[d] = {
                    "t1": payload.get("t1"),
                    "Y4_gap_price": rep["y4_gap_price"],
                    "Y6_gap_fade_rate": rep.get("y6_gap_fade_rate"),
                    "Y5_close_ret": rep.get("y5_close_ret"),
                    "matched": rep.get("matched"),
                }
    return repairs


# ---------------------------------------------------------------- 日级记录构建
def build_days(eod, slot_scores, sids, rows_by_snapshot, trading_dates, market, repairs):
    """交易日 → 候选 C1-C9bm 与靶 Y1-Y8（缺项 None，计数在报告层披露）。"""
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

    # 价格靶（sid 按靶放宽：Y4 需 T0 15:00+T+1 09:30，Y5 需双 15:00，Y6 需三帧，审查 P2-7）
    for i, d in enumerate(trading_dates[:-1]):
        rec = days.get(d)
        if not rec:
            continue
        t0, t1 = d, trading_dates[i + 1]
        sid015 = sids.get((t0, "15:00"))
        sid1930 = sids.get((t1, "09:30"))
        sid115 = sids.get((t1, "15:00"))
        r015 = rows_by_snapshot.get(sid015) or {} if sid015 else {}
        r1930 = rows_by_snapshot.get(sid1930) or {} if sid1930 else {}
        r115 = rows_by_snapshot.get(sid115) or {} if sid115 else {}
        if not r015:
            continue
        gaps, closes, fades = [], [], []
        for code, r in r015.items():
            p0 = r["price"]
            p1930 = (r1930.get(code) or {}).get("price")
            p115 = (r115.get(code) or {}).get("price")
            if p0 and p1930:
                gaps.append(p1930 / p0 - 1)
            if p0 and p115:
                closes.append(p115 / p0 - 1)
            if p0 and p1930 and p115:
                fades.append(1 if (p1930 / p0 - 1 >= 0.01 and p115 < p1930) else 0)
        rec["_matched_930"] = len(gaps)
        rec["_matched_1500"] = len(closes)
        # 预登记修订 2：9:30 帧前收价污染（精确相等占比>30%）→ Y4/Y6 记 None；随后用 TDX 修复值回填（修订 3）
        eq = sum(1 for c, r in r015.items()
                 if r["price"] and (r1930.get(c) or {}).get("price")
                 and abs((r1930[c]["price"]) - r["price"]) < 1e-9)
        stale = bool(gaps) and eq / len(gaps) > 0.3
        rec["_stale_open"] = stale
        rec["Y4_gap_price"] = sum(gaps) / len(gaps) if (len(gaps) >= MIN_MATCHED and not stale) else None
        rec["Y5_close_ret"] = sum(closes) / len(closes) if len(closes) >= MIN_MATCHED else None
        rec["Y6_gap_fade_rate"] = (sum(fades) / len(fades) if len(fades) >= MIN_MATCHED and not stale else None)
        # 修订 3：脏日 TDX 修复值无条件回填（07-20 零额帧日 Mongo 只有 9:30 半截值，TDX 全Session 值更优）
        if d in repairs:
            rep = repairs[d]
            rec["Y4_gap_price"] = rep["Y4_gap_price"]
            rec["Y6_gap_fade_rate"] = rep["Y6_gap_fade_rate"]
            if rep.get("Y5_close_ret") is not None:
                rec["Y5_close_ret"] = rep["Y5_close_ret"]
            rec["_repaired"] = True
        elif stale:
            print(f"[披露] {d} 前收价污染且无修复值，Y4/Y6 记缺失")

    # 指数级靶 Y7/Y8（TDX 缓存，全窗；修订 3 新增，市场级对照）
    if market:
        for i, d in enumerate(trading_dates[:-1]):
            rec = days.get(d)
            t1 = trading_dates[i + 1]
            m0, m1 = market.get(d), market.get(t1)
            if not rec or not m0 or not m1:
                continue
            if m0.get("index_close") and m1.get("index_open"):
                rec["Y7_index_gap"] = m1["index_open"] / m0["index_close"] - 1
            if m0.get("index_close") and m1.get("index_close"):
                rec["Y8_index_ret"] = m1["index_close"] / m0["index_close"] - 1

    # 池级 C9/C9b（turnover 等价前推全窗；0/负额不算覆盖 → 07-21 伪值日自然出局）
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
            have = sum(1 for c in retained if (m.get(c) or {}).get("amount_eff") is not None)
            return have / len(retained)

        if min(cover(rt15), cover(ram), cover(rpm), cover(rp15)) < MIN_AMOUNT_COVER:
            continue
        am_total = sum(((ram.get(c) or {}).get("amount_eff")) or 0 for c in retained)
        pm_start = sum(((rpm.get(c) or {}).get("amount_eff")) or 0 for c in retained)
        pm_end = sum(((rt15.get(c) or {}).get("amount_eff")) or 0 for c in retained)
        prev_total = sum(((rp15.get(c) or {}).get("amount_eff")) or 0 for c in retained)
        if am_total > 0:
            rec["C9_vol_trend"] = (pm_end - pm_start) / am_total - 1
        if prev_total > 0:
            rec["C9b_day_vs_yday"] = pm_end / prev_total - 1

    # 市场级 C9m/C9bm（TDX 指数 5 分钟线，全窗；修订 3）
    if market:
        mdates = sorted(market)
        for i, d in enumerate(mdates):
            rec = days.get(d)
            if not rec or i == 0:
                continue
            prev = market[mdates[i - 1]]
            cur = market[d]
            rec["C9m_vol_fade"] = (cur["market_pm"] / prev["market_pm"]) - (cur["market_am"] / prev["market_am"])
            rec["C9bm_total_chg"] = cur["market_total"] / prev["market_total"] - 1
    return days


# ---------------------------------------------------------------- 报告
def _fmt(v, pct=False):
    if v is None:
        return "--"
    return f"{v * 100:+.2f}%" if pct else f"{v:+.3f}"


def quarter_of(d: str) -> str:
    return "Q2(4-6月)" if d <= Q2_END else "Q3(7-9月)"


def main():
    db = MongoClient(DB_URI, serverSelectionTimeoutMS=5000)[DB_NAME]
    eod, slot_scores, sids = load_sentiment(db)
    trading_dates = sorted(eod)
    n_valid = sum(1 for d in trading_dates if len(slot_scores.get(d) or {}) >= MIN_SLOTS)
    print(f"EOD 文档 {len(trading_dates)} 日（{trading_dates[0]} → {trading_dates[-1]}）；"
          f"逐槽有效日（≥{MIN_SLOTS} 槽有分）{n_valid} 日；bootstrap n={BOOT_N}（每格独立 seed）")

    # 交易日历桥接守卫（审查 P2-9）：weekday 缺口非节假日=采集停摆嫌疑
    from datetime import date as _d, timedelta as _td
    d0, d1 = _d.fromisoformat(trading_dates[0]), _d.fromisoformat(trading_dates[-1])
    have = set(trading_dates)
    gaps = []
    cur = d0
    while cur <= d1:
        iso = cur.isoformat()
        if cur.weekday() < 5 and iso not in have and iso not in KNOWN_HOLIDAYS:
            gaps.append(iso)
        cur += _td(days=1)
    if gaps:
        print(f"[披露] 非假日 weekday 无任何文档（配对若跨这些日=把 T+2 当 T+1 的风险日）：{gaps}")

    # sid 兜底（帧在文档缺）
    missing_pairs = sorted({(d, s) for d in trading_dates for s in CANON_SLOTS
                            if (d, s) not in sids})
    fb = load_sid_fallback(db, missing_pairs)
    if fb:
        print(f"[披露] 槽位文档缺 sid、经 snapshot_frames 兜底 {len(fb)}/{len(missing_pairs)} 帧："
              f"{[f'{k[0]}{k[1]}' for k in sorted(fb)]}")
    sids = {**sids, **fb}

    market = load_market_cache()
    repairs = load_repairs()
    print(f"市场级缓存 {len(market)} 日；脏日修复值 {len(repairs)} 日：{sorted(repairs)}")

    need_sids = sorted({v for v in sids.values() if v})
    print(f"加载价格行：{len(need_sids)} 帧 …")
    rows_by_snapshot = load_rows_by_snapshot(db, need_sids)
    days = build_days(eod, slot_scores, sids, rows_by_snapshot, trading_dates, market, repairs)

    score_only = [d for d in trading_dates if d in days and days[d].get("Y3_delta_eod") is not None]
    paired = [d for d in trading_dates if d in days and days[d].get("Y5_close_ret") is not None]
    repaired_days = [d for d in trading_dates if d in days and days[d].get("_repaired")]
    print(f"配对成功：分数靶 {len(score_only)} 日；价格靶 {len(paired)} 日"
          f"（其中 TDX 修复回填 {len(repaired_days)} 日：{repaired_days}）")

    stale_unrepaired = [d for d in trading_dates if d in days and days[d].get("_stale_open")
                        and not days[d].get("_repaired")]
    if stale_unrepaired:
        print(f"[披露] 前收价污染且无修复值：{stale_unrepaired}")

    def window_for(cand: str, target: str) -> list[str]:
        if cand in MKT_CANDS or target in IDX_TARGETS:
            base = [d for d in trading_dates if d in days]
        elif cand in POOL_CANDS:
            base = paired
        elif target in PRICE_TARGETS:
            base = paired
        else:
            base = score_only
        return [d for d in base
                if (days.get(d) or {}).get(cand) is not None and (days.get(d) or {}).get(target) is not None]

    def cell(cand: str, target: str, ds_list):
        xs = [(days[d] or {}).get(cand) for d in ds_list]
        ys = [(days[d] or {}).get(target) for d in ds_list]
        r = spearman(xs, ys)
        ci = bootstrap_ci(xs, ys, f"{cand}|{target}")
        sp = tercile_spread(xs, ys)
        return r, ci, sp, len(xs)

    pct_targets = PRICE_TARGETS | IDX_TARGETS
    print("\n=== 主表：Spearman ρ [95% CI] ｜ 全窗 ===")
    col_w = 26
    print(f"{'候选':<16}" + "".join(f"{t:<{col_w}}" for t in TARGETS))
    table: dict[tuple[str, str], object] = {}
    for c in CANDIDATES:
        if not any((days.get(d) or {}).get(c) is not None for d in trading_dates):
            continue
        row_cells = []
        for t in TARGETS:
            ds_list = window_for(c, t)
            r, ci, sp, n = cell(c, t, ds_list)
            table[(c, t)] = (r, n)
            pct = t in pct_targets
            rtxt = f"{r:+.2f}" if r is not None else "  --"
            citxt = f"[{ci[0]:+.2f},{ci[1]:+.2f}]" if ci else "[ --]"
            row_cells.append(f"{rtxt}{citxt} n={n}")
        print(f"{c:<16}" + "".join(f"{cell_txt:<{col_w}}" for cell_txt in row_cells))

    # 分季度独立成表（用户裁决 2026-10-06）
    for q in ("Q2(4-6月)", "Q3(7-9月)"):
        qdays = [d for d in trading_dates if quarter_of(d) == q and d in days]
        print(f"\n=== 分季度：{q}（有效日 {len(qdays)}）Spearman ρ (n) ===")
        print(f"{'候选':<16}" + "".join(f"{t:<{col_w}}" for t in TARGETS))
        for c in CANDIDATES:
            if not any((days.get(d) or {}).get(c) is not None for d in qdays):
                continue
            row_cells = []
            for t in TARGETS:
                ds_list = [d for d in window_for(c, t) if quarter_of(d) == q]
                r, ci, sp, n = cell(c, t, ds_list)
                pct = t in pct_targets
                rtxt = f"{r:+.2f}" if r is not None else "  --"
                row_cells.append(f"{rtxt} (n={n})")
            print(f"{c:<16}" + "".join(f"{cell_txt:<{col_w}}" for cell_txt in row_cells))

    # 偏相关（统一同窗：所有候选∩Y5 可用日，审查 P1-4）
    aligned = [d for d in paired
               if all((days[d] or {}).get(c) is not None for c in ("C1_eod", "C6_slope_day", "C7_tail_lift",
                                                                   "C8_pm_fade", "C9_vol_trend",
                                                                   "C9b_day_vs_yday", "C9m_vol_fade", "C9bm_total_chg"))]
    print(f"\n=== 偏相关（统一同窗 n={len(aligned)}：控制 C1_eod 后对 Y5 的增量）===")
    for c in ("C6_slope_day", "C7_tail_lift", "C8_pm_fade", "C9_vol_trend",
              "C9b_day_vs_yday", "C9m_vol_fade", "C9bm_total_chg"):
        xs = [days[d][c] for d in aligned]
        ys = [days[d]["Y5_close_ret"] for d in aligned]
        cs = [days[d]["C1_eod"] for d in aligned]
        print(f"  {c:<16} partial ρ = {_fmt(partial_spearman(xs, ys, cs))}")

    # 市况分层×分季度：水平类对 Y5/Y8
    print("\n=== 分季度市况对照：C1_eod 对 Y5（池收益）/ Y8（指数收益）的 ρ ===")
    for t in ("Y5_close_ret", "Y8_index_ret"):
        for q in ("Q2(4-6月)", "Q3(7-9月)"):
            ds_list = [d for d in window_for("C1_eod", t) if quarter_of(d) == q]
            xs = [days[d]["C1_eod"] for d in ds_list]
            ys = [days[d][t] for d in ds_list]
            print(f"  {t}: {q}: ρ={_fmt(spearman(xs, ys))} (n={len(xs)})")

    # H1（修订 3：条件②重定标为 C9m ≤ −0.05，比率差天然居中 0；另附分位数式稳健性读法）
    print("\n=== H1（高开低走+缩量+尾盘拉升 → T+1 砸？修订 3 口径）===")
    mvals = sorted(days[d]["C9m_vol_fade"] for d in trading_dates
                   if d in days and days[d].get("C9m_vol_fade") is not None)
    q20 = mvals[int(0.2 * len(mvals))] if mvals else None
    flag_abs, flag_q, base_win = [], [], []
    for d in trading_dates:
        rec = days.get(d) or {}
        f1, f2, f3, f4 = rec.get("C5_first"), rec.get("C8_pm_fade"), rec.get("C9m_vol_fade"), rec.get("C7_tail_lift")
        if f1 is None or f2 is None or f3 is None or f4 is None:
            continue
        base_win.append(d)
        if f1 >= 60 and f2 >= 10 and f4 >= 10:
            if f3 <= -0.05:
                flag_abs.append(d)
            if q20 is not None and f3 <= q20:
                flag_q.append(d)
    print(f"  基线 {len(base_win)} 日；C9m 窗内 20 分位={q20:+.3f}")
    print(f"  触发（绝对阈值 C9m≤−0.05）：{len(flag_abs)} 日 {flag_abs}")
    print(f"  触发（分位数式 C9m≤q20）：{len(flag_q)} 日 {flag_q}")
    for name, fl in (("绝对阈值", flag_abs), ("分位数式", flag_q)):
        if len(fl) >= 8:
            for t in ("Y4_gap_price", "Y5_close_ret", "Y6_gap_fade_rate"):
                fv = [days[d][t] for d in fl if days[d].get(t) is not None]
                bv = [days[d][t] for d in base_win if days[d].get(t) is not None]
                if fv and bv:
                    fm, bm = sum(fv) / len(fv), sum(bv) / len(bv)
                    print(f"  [{name}] {t}: H1 均值 {_fmt(fm, True)} (n={len(fv)}) vs 基线 {_fmt(bm, True)} → 差 {_fmt(fm - bm, True)}")
        else:
            print(f"  [{name}] 触发 <8 日 → 样本不足结案（不追加条件，防打靶瞄准）")
            for d in fl:
                rec = days[d]
                print(f"    {d}: Y4={_fmt(rec.get('Y4_gap_price'), True)} Y5={_fmt(rec.get('Y5_close_ret'), True)} "
                      f"Y6={_fmt(rec.get('Y6_gap_fade_rate'), True)} Y7={_fmt(rec.get('Y7_index_gap'), True)}")

    # 多重比较诚实计数（每格独立 seed 后计数与打印一致）
    hits = total = 0
    boundary = []
    for c in CANDIDATES:
        for t in TARGETS:
            ds_list = window_for(c, t)
            r, ci, _, n = cell(c, t, ds_list)
            if r is None or ci is None:
                continue
            total += 1
            if abs(r) >= 0.2 and (ci[0] > 0 or ci[1] < 0):
                hits += 1
            elif abs(r) >= 0.2 and min(abs(ci[0]), abs(ci[1])) < 0.02:
                boundary.append(f"{c}|{t}")
    print(f"\n=== 多重比较诚实计数 ===")
    print(f"  |ρ|≥0.2 且 CI 不跨零：{hits}/{total} 格（随机期望 ≈{total * 0.05:.0f}）；边界格：{boundary}")


if __name__ == "__main__":
    main()
