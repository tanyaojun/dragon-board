# -*- coding: utf-8 -*-
"""连板指数分带 × 隔日接力结果 诊断（只读库+TDX 日线，零 jev 调用，2026-10-11）。

问题（用户）：relay 指数能否像热榜情绪分一样找出「毒带」——某分带内隔日打板接力
稳定亏钱。本脚本不调任何 jev 模型，是月度复验工具（读数文档
docs/hotlist-jev/jev-relay-band-toxic-diagnostic.md，11 月底复验跑本脚本即可复现）：

- 结果口径（D=判定日，N=次一交易日，N2=次次日，快照交易日轴）：
  晋级率   = |pool(D)∩pool(N)| / |pool(D)|            （韭研 final 池）
  高位晋级 = pool(D) 中 ≥2板者 N 仍涨停占比            （韭研 boards）
  溢价A    = pool(D) 各股 D→N 收盘涨跌中位             （昨日板隔日兑付=接力溢价主口径）
  溢价B    = pool(N) 各股 N→N2 收盘涨跌中位            （隔日新板的再隔日兑付=实操「明天打板」）
  大面占比 = pool(D) 中 D→N ≤ -5% 占比
  除权修正 = 复用生产 _adj_prev_series（交易所公式 + 可信带回退，与弹药同口径）
- 分带：<25 / 25-40 / 40-60 / ≥60（与热榜情绪分同切口）+ 三分位稳健带 + Δidx 方向
  + 五区赔率表（绿灯≥60/半绿55-60/黄灯25-55/回避40-60∧T≥56叠加/红灯<25）
- 对照：同日 EOD day_temperature 同口径分带（两者须做条件拆分）；
  另看 relay_phase / money_effect 分类型档位的切分力
- 弹药代际：叙事「不可算」计数分层（≤2=全弹药），防薄弹药代污染分带结论

CLI：
  python scripts/jev_relay_band_diagnostic.py             # 全窗口
  python scripts/jev_relay_band_diagnostic.py --days 8    # 冒烟（最近 8 个判定日）
"""
from __future__ import annotations

import argparse
import sys
import threading
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BANDS = [(0, 25), (25, 40), (40, 60), (60, 101)]
BAND_TXT = {b: (f"{lo}-{hi}" if hi <= 100 else f"≥{lo}") for b in BANDS for lo, hi in [b]}
# 五区赔率表固定切口（2026-10-11 定版；回避为黄灯/半绿区上的温度叠加切分，非互斥分区）
ZONE_GREEN = ("绿灯 ≥60", lambda o: o["idx"] >= 60)
ZONE_SEMI = ("半绿 55-60", lambda o: 55 <= o["idx"] < 60)
ZONE_MID = ("黄灯 25-55", lambda o: 25 <= o["idx"] < 55)
ZONE_AVOID = ("回避 40-60∧温≥56", lambda o: 40 <= o["idx"] < 60
              and o.get("temp") is not None and o["temp"] >= 56)
ZONE_RED = ("红灯 <25", lambda o: o["idx"] < 25)

_BARS_LOCK = threading.Lock()
_BARS_CACHE: dict[str, list[dict]] = {}
_BAR_OFFSET = 150  # main() 里按最早判定日动态放大（覆盖 2026-05 起 ≈115 根，150 为冒烟下限）


def _bars_long(code: str) -> list[dict]:
    cached = _BARS_CACHE.get(code)
    if cached is not None:
        return cached
    from backend.operations.jev_label_jiuyan import _tdx_daily_client
    bars: list[dict] = []
    client = _tdx_daily_client()
    if client is not None:
        try:
            with _BARS_LOCK:
                df = client.bars(symbol=code, frequency=9, start=0, offset=_BAR_OFFSET)
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    bars.append({"date": f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}",
                                 "close": float(r["close"])})
                bars.sort(key=lambda b: b["date"])
        except Exception:
            bars = []
    _BARS_CACHE[code] = bars
    return bars


def _link_pct(code: str, d0: str, d1: str) -> float | None:
    """D→N 收盘涨跌%——除权修正复用生产 _adj_prev_series（交易所公式+可信带回退，
    配股混合事件自动回退原前收，与弹药口径一致）；缺任一日/基价非法 → None。"""
    from backend.operations.jev_label_jiuyan import _adj_prev_series
    bars = _bars_long(code)
    idx = {b["date"]: i for i, b in enumerate(bars)}
    if d0 not in idx or d1 not in idx or idx[d1] <= idx[d0]:
        return None
    adj = _adj_prev_series(d1, code, bars) or {}
    ret = 1.0
    for i in range(idx[d0] + 1, idx[d1] + 1):
        base = adj.get(bars[i]["date"], bars[i - 1]["close"])
        if (not isinstance(base, (int, float)) or isinstance(base, bool) or base <= 0):
            return None
        ret *= bars[i]["close"] / base
    return round((ret - 1) * 100, 2)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    return round(s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2, 2)


def _rank(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_rank(xs), _rank(ys))


def _num(v) -> float | None:
    """数值判定（bool 显式排除——True 不得当 1.0 混进统计）。"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def band_of(v) -> tuple[int, int] | None:
    v = _num(v)
    if v is None:
        return None
    for lo, hi in BANDS:
        if lo <= v < hi:
            return (lo, hi)
    return None


def main() -> None:
    global _BAR_OFFSET
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="只取最近 N 个判定日（冒烟用，0=全窗口）")
    args = ap.parse_args()

    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()

    all_relay = list(db["hotlist_jev_relay_index"].find(
        {}, {"tradingDate": 1, "status": 1}).sort("tradingDate", 1))
    skipped = [str(r["tradingDate"]) for r in all_relay if r.get("status") != "ok"]
    relay = list(db["hotlist_jev_relay_index"].find(
        {"status": "ok"},
        {"tradingDate": 1, "relayIndex": 1, "relayPhase": 1, "moneyEffect": 1,
         "questionSetVersion": 1, "narrative": 1}).sort("tradingDate", 1))
    no_idx = [str(r["tradingDate"]) for r in relay if _num(r.get("relayIndex")) is None]
    relay = [r for r in relay if _num(r.get("relayIndex")) is not None]
    if skipped or no_idx:
        print(f"[fail-visible] 跳过非 ok 判定日 {len(skipped)} 个{skipped}；"
              f"ok 但无指数 {len(no_idx)} 个{no_idx}")
    if args.days:
        relay = relay[-args.days:]
    if not relay:
        print("无可用判定日（fail-visible），退出")
        return
    dates = [r["tradingDate"] for r in relay]

    # TDX 棒数按最早判定日动态放大（~每年 250 根 + 余量），滚动窗口不再静默丢早期样本
    span_days = (_date.today() - _date(int(dates[0][:4]), int(dates[0][5:7]), int(dates[0][8:]))).days
    _BAR_OFFSET = max(150, min(800, int(span_days * 0.75) + 60))

    # 交易日轴（快照帧）+ 次日/次次日映射
    axis = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour"}, {"tradingDate": 1})
        if r.get("tradingDate")})
    nxt = {d: axis[i + 1] for i, d in enumerate(axis[:-1])}

    _pool_cache: dict[str, dict[str, dict]] = {}

    def pool(d: str | None) -> dict[str, dict]:
        if not d:
            return {}
        if d not in _pool_cache:
            doc = db["jiuyan_action"].find_one({"_id": f"{d}:final"})
            out: dict[str, dict] = {}
            for fl in (doc or {}).get("fields") or []:
                for s in fl.get("stocks") or []:
                    code = str(s.get("code") or "")[-6:]
                    if code and code not in out:
                        out[code] = s
            _pool_cache[d] = out
        return _pool_cache[d]

    # EOD 温度（bool 显式排除）
    temps: dict[str, float] = {}
    for e in db["hotlist_jev_sentiment"].find(
            {"kind": "eod", "status": "ok", "tradingDate": {"$in": dates}},
            {"tradingDate": 1, "scores.day_temperature": 1}):
        t = _num((e.get("scores") or {}).get("day_temperature"))
        if t is not None:
            temps[e["tradingDate"]] = float(t)

    # 股票全集 = 判定日池 ∪ 其次日池（溢价B 需要）
    codes_all: set[str] = set()
    for d in dates:
        codes_all |= set(pool(d))
        codes_all |= set(pool(nxt.get(d)))
    print(f"判定日 {len(dates)} 个（{dates[0]}..{dates[-1]}），池内去重股票 {len(codes_all)} 只，"
          f"逐只拉 TDX 日线（offset={_BAR_OFFSET}）…")
    for i, c in enumerate(sorted(codes_all), 1):
        _bars_long(c)
        if i % 200 == 0:
            print(f"  TDX 进度 {i}/{len(codes_all)}")
    ok_n = sum(1 for c in codes_all if _BARS_CACHE.get(c))
    print(f"TDX 有棒 {ok_n}/{len(codes_all)} 只（缺棒股溢价行按缺失计，fail-visible）")

    obs: list[dict] = []
    for r in relay:
        d = r["tradingDate"]
        n, n2 = nxt.get(d), nxt.get(nxt.get(d))
        nar = r.get("narrative") or ""
        row = {"d": d, "ver": r.get("questionSetVersion"), "idx": _num(r["relayIndex"]),
               "temp": temps.get(d), "phase": r.get("relayPhase"),
               "money": r.get("moneyEffect"), "n_pool": len(pool(d)),
               # 弹药代际：叙事内「不可算」计数（≤2=全弹药，>2=薄弹药代，分带结论分层防混读）
               "degraded": nar.count("不可算")}
        p = pool(d)
        if n and p:
            pn = pool(n)
            row["promo"] = len(set(p) & set(pn)) / len(p) * 100
            hi = [c for c in p if (_jiuyan_boards(p[c]) or 0) >= 2]
            row["hi_n"] = len(hi)
            row["hi_promo"] = (len([c for c in hi if c in pn]) / len(hi) * 100) if hi else None
        else:
            row["promo"] = row["hi_promo"] = None
            row["hi_n"] = 0
        if n and p:
            pcts = [v for v in (_link_pct(c, d, n) for c in p) if v is not None]
            row["cov"] = len(pcts)
            row["premA"] = _median(pcts)
            row["premA_mean"] = round(sum(pcts) / len(pcts), 2) if pcts else None
            row["bigface"] = (sum(1 for v in pcts if v <= -5) / len(pcts) * 100) if pcts else None
        else:
            row["cov"] = row["premA"] = row["premA_mean"] = row["bigface"] = None
        # 溢价B：N 日新板 → N2 兑付（实操「隔日打板」）
        if n and n2 and pool(n):
            pcts_b = [v for v in (_link_pct(c, n, n2) for c in pool(n)) if v is not None]
            row["premB"] = _median(pcts_b) if pcts_b else None
        else:
            row["premB"] = None
        obs.append(row)

    # Δidx（相邻判定日，自然日间隔 ≤5 天才算，跨假期断层不计）
    for i, o in enumerate(obs):
        o["didx"] = None
        if i == 0:
            continue
        prev = obs[i - 1]
        d0 = _date(int(prev["d"][:4]), int(prev["d"][5:7]), int(prev["d"][8:]))
        d1 = _date(int(o["d"][:4]), int(o["d"][5:7]), int(o["d"][8:]))
        if (d1 - d0).days <= 5:
            o["didx"] = o["idx"] - prev["idx"]

    def fmt_row(o: dict) -> str:
        promo = f"{o['promo']:.0f}" if o.get("promo") is not None else "?"
        hip = f"{o['hi_promo']:.0f}" if o.get("hi_promo") is not None else "?"
        pa = f"{o['premA']:+.1f}" if o.get("premA") is not None else "?"
        pb = f"{o['premB']:+.1f}" if o.get("premB") is not None else "?"
        bf = f"{o['bigface']:.0f}" if o.get("bigface") is not None else "?"
        t = f"{o['temp']:.0f}" if o.get("temp") is not None else "?"
        cov = o.get("cov")
        cov_txt = f"{cov:>2}" if isinstance(cov, int) else " ?"
        dx = f"{o['didx']:+.1f}" if o.get("didx") is not None else "  ?"
        return (f"{o['d'][5:]} v{o['ver'] or '?'} idx{o['idx']:5.1f} Δ{dx:>5} T{t:>3} {str(o.get('phase') or '?'):<10} | "
                f"晋级{promo:>3}% 高位晋级{hip:>3}%({o.get('hi_n', 0):>2}) | "
                f"溢价A{pa:>6}% B{pb:>6}% 大面{bf:>3}% 覆盖{cov_txt}/{o['n_pool']} 降级{o.get('degraded', 0)}")

    print("\n== 逐日明细（D 判定 → N/N2 实测）==")
    for o in obs:
        print(fmt_row(o))

    def agg_table(key_fn, key_name: str, rows: list[dict]) -> None:
        print(f"\n== 分带表（按{key_name}，D 日分带 → 次日实测均值）==")
        print(f"{'带':>12} {'n':>3} {'晋级率':>7} {'高位晋级':>8} {'溢价A(日中位均)':>12} {'溢价B(日中位均)':>12} "
              f"{'大面%':>6} {'A<0天':>7}")
        groups: dict = {}
        for o in rows:
            k = key_fn(o)
            if k is not None:
                groups.setdefault(k, []).append(o)
        mean = lambda vs: round(sum(vs) / len(vs), 1) if vs else float("nan")
        for k in sorted(groups, key=lambda x: (x is None, x)):
            g = groups[k]
            promo = mean([o["promo"] for o in g if o.get("promo") is not None])
            hip = mean([o["hi_promo"] for o in g if o.get("hi_promo") is not None])
            pa = mean([o["premA"] for o in g if o.get("premA") is not None])
            pb = mean([o["premB"] for o in g if o.get("premB") is not None])
            bf = mean([o["bigface"] for o in g if o.get("bigface") is not None])
            negA = sum(1 for o in g if (o.get("premA") or 0) < 0)
            kname = {b: BAND_TXT[b] for b in BANDS}.get(k, str(k))
            print(f"{kname:>12} {len(g):>3} {promo:>6}% {hip:>7}% {pa:>+11}% {pb:>+11}% {bf:>5}% {negA}/{len(g)}")

    have = [o for o in obs if o.get("premA") is not None or o.get("promo") is not None]
    agg_table(lambda o: band_of(o["idx"]), "relayIndex", have)
    agg_table(lambda o: band_of(o.get("temp")), "EOD温度分", have)
    agg_table(lambda o: o.get("phase"), "relay_phase", have)
    agg_table(lambda o: o.get("money"), "money_effect", have)

    idxs = sorted(o["idx"] for o in have)
    if len(idxs) >= 6:
        q1, q2 = idxs[len(idxs) // 3], idxs[len(idxs) * 2 // 3]
        print(f"\n三分位切点 idx = {q1:.1f} / {q2:.1f}")
        agg_table(lambda o: "低三分位" if o["idx"] <= q1 else ("中三分位" if o["idx"] <= q2 else "高三分位"),
                  "relayIndex三分位", have)
    else:
        print("\n三分位：样本不足 6 天跳过（fail-visible）")
    agg_table(lambda o: ("Δidx<0" if o["didx"] < 0 else "Δidx≥0") if o.get("didx") is not None else None,
              "Δidx方向(环比判定日)", have)

    # 五区赔率表（2026-10-11 定版，全样本含 v1 判定；回避为温度叠加切分非互斥分区）
    def odds_table(title: str, rows: list[dict]) -> None:
        print(f"\n== 五区赔率表（{title}）==")
        print(f"{'区':>16} {'n':>3} {'均值':>7} {'正/负':>6} {'赢日均':>7} {'输日均':>7} {'大面%':>6}")
        mean = lambda vs: round(sum(vs) / len(vs), 2) if vs else float("nan")
        for name, pred in (ZONE_GREEN, ZONE_SEMI, ZONE_MID, ZONE_AVOID, ZONE_RED):
            g = [o for o in rows if pred(o) and o.get("premA") is not None]
            if not g:
                print(f"{name:>16} {0:>3}    -      -       -       -       -")
                continue
            pos = [o["premA"] for o in g if o["premA"] > 0]
            neg = [o["premA"] for o in g if o["premA"] <= 0]
            bf = mean([o["bigface"] for o in g if o.get("bigface") is not None])
            print(f"{name:>16} {len(g):>3} {mean([o['premA'] for o in g]):>+6}% "
                  f"{len(pos):>3}/{len(neg):<3} {mean(pos):>+6}% {mean(neg):>+6}% {bf:>5}%"
                  + ("   逐日: " + " ".join(f"{o['d'][5:]}:{o['premA']:+.1f}" for o in g)
                     if len(g) <= 16 else ""))

    odds_table(f"全样本 n={len(have)}（含 v1 判定）", have)

    def _corr_line(xs, ys, label):
        print(f"{label} pearson={_pearson(xs, ys):.3f} spearman={_spearman(xs, ys):.3f} (n={len(xs)})")

    print()
    pairs = [(o["idx"], o["premA"]) for o in obs if o.get("premA") is not None]
    _corr_line([a for a, _ in pairs], [b for _, b in pairs], "corr(relayIndex, 溢价A)")
    pairs_b = [(o["idx"], o["premB"]) for o in obs if o.get("premB") is not None]
    _corr_line([a for a, _ in pairs_b], [b for _, b in pairs_b], "corr(relayIndex, 溢价B)")
    pairs_p = [(o["idx"], o["promo"]) for o in obs if o.get("promo") is not None]
    _corr_line([a for a, _ in pairs_p], [b for _, b in pairs_p], "corr(relayIndex, 晋级率) ")
    pairs_d = [(o["didx"], o["premA"]) for o in obs
               if o.get("didx") is not None and o.get("premA") is not None]
    _corr_line([a for a, _ in pairs_d], [b for _, b in pairs_d], "corr(Δidx, 溢价A)     ")
    tpairs = [(o["temp"], o["premA"]) for o in obs
              if o.get("premA") is not None and o.get("temp") is not None]
    _corr_line([a for a, _ in tpairs], [b for _, b in tpairs], "corr(EOD温度, 溢价A) ")

    # 条件拆分：温度中性带内 relay 指数是否再切分；反之亦然
    mean = lambda vs: round(sum(vs) / len(vs), 2) if vs else float("nan")
    mid_temp = [o for o in obs if o.get("temp") is not None and 40 <= o["temp"] < 60
                and o.get("premA") is not None]
    if len(mid_temp) >= 6:
        med = sorted(o["idx"] for o in mid_temp)[len(mid_temp) // 2]
        lo = [o["premA"] for o in mid_temp if o["idx"] < med]
        hi = [o["premA"] for o in mid_temp if o["idx"] >= med]
        print(f"\n温度 40-60 带内（n={len(mid_temp)}，idx 切点 {med:.1f}）："
              f"idx<切点 溢价A均值 {mean(lo)}%（n={len(lo)}） vs idx≥切点 {mean(hi)}%（n={len(hi)}）")
    mid_idx = [o for o in obs if band_of(o["idx"]) == (40, 60) and o.get("premA") is not None]
    if len(mid_idx) >= 6:
        tvals = sorted(o["temp"] for o in mid_idx if o.get("temp") is not None)
        if len(tvals) >= 6:
            medt = tvals[len(tvals) // 2]
            lo = [o["premA"] for o in mid_idx if (o.get("temp") is not None and o["temp"] < medt)]
            hi = [o["premA"] for o in mid_idx if (o.get("temp") is not None and o["temp"] >= medt)]
            print(f"relay 40-60 带内（n={len(mid_idx)}，温度切点 {medt:.0f}）："
                  f"T<切点 {mean(lo)}%（n={len(lo)}） vs T≥切点 {mean(hi)}%（n={len(hi)}）")

    # 候选毒带逐月一致性（0-25 冰点带与 40-60 双假说并列，防单假说过拟合）
    for band, name in (((0, 25), "0-25冰点带"), ((40, 60), "40-60带")):
        by_month: dict[str, list[float]] = {}
        for o in obs:
            if band_of(o["idx"]) == band and o.get("premA") is not None:
                by_month.setdefault(o["d"][:7], []).append(o["premA"])
        if by_month:
            seg = "；".join(f"{m} {round(sum(v)/len(v),1)}%(n={len(v)},负{sum(1 for x in v if x < 0)})"
                            for m, v in sorted(by_month.items()))
            print(f"[relayIndex {name}] 逐月溢价A均值：{seg}")
    by_month_t: dict[str, list[float]] = {}
    for o in obs:
        if band_of(o.get("temp")) == (40, 60) and o.get("premA") is not None:
            by_month_t.setdefault(o["d"][:7], []).append(o["premA"])
    if by_month_t:
        seg = "；".join(f"{m} {round(sum(v)/len(v),1)}%(n={len(v)},负{sum(1 for x in v if x < 0)})"
                        for m, v in sorted(by_month_t.items()))
        print(f"[EOD温度 40-60带] 逐月溢价A均值：{seg}")

    # 弹药代际分层（回补后防混读）：叙事「不可算」≤2=全弹药，>2=薄弹药
    full_ammo = [o for o in obs if o.get("degraded", 0) <= 2]
    thin_ammo = [o for o in obs if o.get("degraded", 0) > 2]
    print(f"\n弹药代际：全弹药 {len(full_ammo)} 天 / 薄弹药 {len(thin_ammo)} 天"
          + (f"（薄弹药日 {' '.join(o['d'][5:] for o in thin_ammo[:12])}...)" if thin_ammo else ""))
    agg_table(lambda o: band_of(o["idx"]), "relayIndex(全弹药)", full_ammo)
    if len(thin_ammo) >= 5:
        agg_table(lambda o: band_of(o["idx"]), "relayIndex(薄弹药)", thin_ammo)

    v3 = [o for o in obs if o.get("ver") == "v3"]
    if len(v3) < len(obs):
        print(f"\n（v3-only n={len(v3)}）")
        agg_table(lambda o: band_of(o["idx"]), "relayIndex(v3 only)", v3)
        odds_table(f"v3-only n={len(v3)}", v3)


def _jiuyan_boards(stock: dict) -> int | None:
    from backend.operations.jev_label_jiuyan import _jiuyan_board_count
    return _jiuyan_board_count(stock)


if __name__ == "__main__":
    main()
