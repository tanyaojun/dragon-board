# -*- coding: utf-8 -*-
"""连板指数「炸板面改门」判定卡（2026-10-11 StepB，预登记 jev-relay-zhaban-preregistration.md）。

对比三组判定 vs T+1 实测生态：
- v1：归档 data/backups/relay_index_v1_20261011.json（改门前，15 日）
- v2：归档 data/backups/relay_index_v2_20261011.json（62 日；v3 --force 落库按同 _id
  覆写库内 v2，基线只能读归档——data/backups 文件对照，不进业务库）
- v3：库内 questionSetVersion=v3（炸板归因注入，60 日，当前代）
判别口径（T+1 relayIndex 变化方向，v2 序列内相邻日）：
- divergence/collapse → T+1 idx 下降 = 命中
- relay_heat/launch → T+1 idx 上升或 ±5 内 = 命中
- holding 相位/不判方向不计
另验炸板面单独前导力：当日炸板分位/反复开板占比 与 T+1 idx 变化的分桶均值。

只读库 + 归档文件，不调模型。CLI：python -m backend.operations.jev_relay_zhaban_verdict
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

BACKUPS = Path(__file__).resolve().parents[2] / "data/backups"


def _load_archive(name: str) -> dict[str, dict[str, Any]]:
    p = BACKUPS / name
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("status") == "ok":
            out[d["tradingDate"]] = d
    return out


def _pearson(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def run() -> None:
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    v1 = _load_archive("relay_index_v1_20261011.json")
    v2 = _load_archive("relay_index_v2_20261011.json")
    v3rows = list(db["hotlist_jev_relay_index"].find(
        {"status": "ok", "questionSetVersion": "v3"},
        {"tradingDate": 1, "relayIndex": 1, "relayPhase": 1}).sort("tradingDate", 1))
    v3 = {r["tradingDate"]: r for r in v3rows if r.get("relayIndex") is not None}
    # T+1 相邻日历 = 三代并集：v3 --force 覆写后库内 v2 只剩例外日，逐代相邻对必须
    # 用并集日历，否则 v1/v2 组在 v3 覆写日全部断链（2026-10-11 首跑「样本不足」教训）
    all_dates = sorted(set(v1) | set(v2) | set(v3))
    nxt = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    def phase_hit(phase: str | None, idx_d: float, idx_n: float | None) -> bool | None:
        if phase is None or idx_n is None:
            return None
        delta = idx_n - idx_d
        if phase in ("divergence", "collapse"):
            return delta < 0
        if phase in ("relay_heat", "launch"):
            return delta >= -5
        return None  # bottoming 无方向预期

    def eval_set(judge: dict[str, dict[str, Any]], label: str) -> None:
        hits, total = 0, 0
        xs, ys = [], []
        detail = []
        for d, r in judge.items():
            nd = nxt.get(d)
            if nd is None or nd not in judge:
                continue
            h = phase_hit(r.get("relayPhase"), r["relayIndex"], judge[nd].get("relayIndex"))
            if h is not None:
                total += 1
                hits += 1 if h else 0
                detail.append((d, r.get("relayPhase"), round(judge[nd].get("relayIndex") - r["relayIndex"], 1), h))
            xs.append(r["relayIndex"])
            ys.append(judge[nd].get("relayIndex") - r["relayIndex"])
        corr = _pearson(xs, ys)
        rate = f"{hits}/{total} = {round(hits / total * 100)}%" if total else "样本不足"
        print(f"[{label}] 相位→T+1方向命中: {rate} | corr(relayIndex, ΔT+1)={corr:.3f}" if total else f"[{label}] 样本不足")
        for d, ph, delta, h in detail:
            print(f"    {d} {ph:<12} ΔT+1={delta:+} {'✓' if h else '✗'}")

    print("== 判定卡：炸板面改门 v1/v2/v3（T+1 relayIndex 方向口径）==")
    eval_set(v1, "v1 归档（改门前）")
    same = {d: v2[d] for d in v1 if d in v2}
    eval_set(same, "v2 同窗（v1 的 15 日）")
    eval_set(v2, "v2 全窗口（归档基线）")
    eval_set(v3, "v3 全窗口（炸板归因注入）")
    v2_same = {d: v2[d] for d in v3 if d in v2}
    eval_set(v2_same, "v2 同窗（v3 覆盖日）")
    # 炸板面单独前导力（Δidx 口径）：走 v3 当前代窗口
    dates = sorted(v3)
    zhaban_rows = list(db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": {"$in": dates}},
        {"tradingDate": 1, "limitSummary.thsPools": 1}).sort("timestamp", -1))  # review M5：同日多帧取最新
    per_day = {}
    for fr in zhaban_rows:
        tp = ((fr.get("limitSummary") or {}).get("thsPools") or {})
        its = ((((tp.get("pools") or {}).get("failed") or {}).get("items")) or []) if (tp.get("ok") and not tp.get("degraded")) else None
        if its is not None and fr["tradingDate"] not in per_day:  # 降序遍历：首见=最新帧
            per_day[fr["tradingDate"]] = its
    all_n = [len({str(i.get("code") or "")[-6:] for i in its}) for its in per_day.values()]
    hi_ratio = []
    deltas = []
    tags = []
    for d in dates[:-1]:
        nd = nxt.get(d)
        if d not in per_day or nd is None or nd not in v3:
            continue
        its = per_day[d]
        codes = {str(i.get("code") or "")[-6:] for i in its}
        n = len(codes)
        hi = sum(1 for i in its if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2)
        ratio = hi / n if n else 0
        delta = v3[nd].get("relayIndex") - v3[d].get("relayIndex")
        if delta is None:
            continue
        hi_ratio.append(ratio)
        deltas.append(delta)
        tags.append((d, n, ratio, delta))
    if len(hi_ratio) >= 6:
        med = sorted(hi_ratio)[len(hi_ratio) // 2]
        low = [dv for r, dv in zip(hi_ratio, deltas) if r <= med]
        high = [dv for r, dv in zip(hi_ratio, deltas) if r > med]
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else float("nan")
        print(f"\n== 炸板面前导力（v3 全窗口 {len(hi_ratio)} 对，Δidx 口径）==")
        print(f"反复开板占比 ≤中位({med:.0%})：T+1 Δidx 均值 {avg(low)}（n={len(low)}）")
        print(f"反复开板占比 >中位      ：T+1 Δidx 均值 {avg(high)}（n={len(high)}）")
        print(f"corr(反复开板占比, ΔT+1)={_pearson(hi_ratio, deltas):.3f}")
        for d, n, r, dv in tags:
            print(f"    {d} 炸板{n:>3} 反复开板{r:>5.0%} ΔT+1={dv:+.1f}")





# ── v2 重验（2026-10-11 用户裁决 a+b）：T+1 实测生态口径 + 残差分析 ──────────
# 口径缺陷自查结论（预登记 §六）：Δidx 方向被指数均值回归污染（corr≈-0.8）。
# 本轮：a) 主指标换 T+1 实测生态（晋级率变化 Δpromote / 涨停家数变化 ΔztCount）；
#       b) 残差分析：控制当日 idx 水平（分位桶去均值）后看炸板面变量的增量解释力。


def run_ecosystem() -> None:
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    rows = list(db["hotlist_jev_relay_index"].find(
        {"status": "ok"}, {"tradingDate": 1, "relayIndex": 1, "relayPhase": 1,
                           "questionSetVersion": 1}).sort("tradingDate", 1))
    by_date = {r["tradingDate"]: r for r in rows if r.get("relayIndex") is not None}
    dates = sorted(by_date)
    # 晋级率（韭研触板池口径）：|T∩T+1| / |T|
    def promote(d: str, d_next: str) -> float | None:
        def pool(x):
            doc = db["jiuyan_action"].find_one({"_id": f"{x}:final"})
            return {str(s.get("code") or "")[-6:] for fl in (doc or {}).get("fields") or []
                    for s in fl.get("stocks") or [] if s.get("code")}
        p, q = pool(d), pool(d_next)
        if not p:
            return None
        return len(p & q) / len(p)
    # ztCount
    def zt(d: str) -> float | None:
        from backend.operations.jev_label_jiuyan import market_metrics
        m = market_metrics(db, d)
        return m.get("ztCount") if isinstance(m, dict) else None
    # 炸板面变量
    def zhaban_vars(d: str) -> dict | None:
        fr = db["snapshot_frames"].find_one(
            {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d, "slotTime": "15:00"},
            {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
        tp = ((fr or {}).get("limitSummary") or {}).get("thsPools") or {}
        if not tp or not tp.get("ok") or tp.get("degraded"):
            return None
        its = (((tp.get("pools") or {}).get("failed") or {}).get("items")) or []
        codes = {str(i.get("code") or "")[-6:] for i in its if i.get("code")}
        n = len(codes)
        hi = sum(1 for i in its if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2)
        return {"n": n, "hi_ratio": hi / n if n else 0.0}
    # 逐日三元组：Δpromote / Δzt / 炸板变量 / idx
    obs = []
    arch = _load_archive("relay_index_v1_20261011.json")   # v1 相位基线（仅存归档）
    arch2 = _load_archive("relay_index_v2_20261011.json")  # v2 相位基线（v3 落库覆写，仅存归档）
    for i, d in enumerate(dates[:-1]):
        dn = dates[i + 1]
        pv = [x for x in dates if x < d]
        if not pv:
            continue
        pr = promote(d, dn)
        pr_prev = promote(pv[-1], d)
        if pr is None or pr_prev is None:
            continue
        z1, z0 = zt(d), zt(dn)
        zb = zhaban_vars(d)
        if zb is None:
            continue
        obs.append({"d": d, "ver": by_date[d].get("questionSetVersion"),
                    "phase": by_date[d].get("relayPhase"),
                    "phase_v1": (arch.get(d) or {}).get("relayPhase"),
                    "phase_v2": (arch2.get(d) or {}).get("relayPhase"),
                    "idx": by_date[d].get("relayIndex"),
                    "dpromote": pr - pr_prev,
                    "dzt": (z1 - z0) if (z1 is not None and z0 is not None) else None,
                    **zb})
    print(f"== 生态口径重验：T+1 实测（{len(obs)} 对；库内当前代=v3，基线相位读归档）==")
    if len(obs) < 8:
        print("样本不足"); return
    # a) 相位命中（Δpromote 口径）三代并列
    v3obs = [o for o in obs if o["ver"] == "v3"]
    v1_same = [o for o in obs if o.get("phase_v1")]
    v2_same = [o for o in obs if o.get("phase_v2")]
    print(f"相位→Δpromote 命中：v1基线(同窗) {_eval(v1_same, key='phase_v1')}"
          f" | v2基线(同窗) {_eval(v2_same, key='phase_v2')} | v3 {_eval(v3obs)}")
    print(f"相位→ΔztCount 命中：v1基线 {_zt_eval(v1_same, 'phase_v1')}"
          f" | v2基线(同窗) {_zt_eval(v2_same, 'phase_v2')} | v3 {_zt_eval(v3obs, 'phase')}")
    # b) 炸板面前导力（Δpromote 口径——无均值回归污染）
    for var in ("hi_ratio", "n"):
        xs = [o[var] for o in obs]
        ys = [o["dpromote"] * 100 for o in obs]
        print(f"corr({var}, Δpromote×100) = {_pearson(xs, ys):.3f}")
    med_hi = sorted(o["hi_ratio"] for o in obs)[len(obs) // 2]
    lowp = [o["dpromote"] * 100 for o in obs if o["hi_ratio"] <= med_hi]
    highp = [o["dpromote"] * 100 for o in obs if o["hi_ratio"] > med_hi]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else float("nan")
    print(f"反复开板占比≤中位({med_hi:.0%})：Δpromote 均值 {avg(lowp)}pp（n={len(lowp)}） | >中位：{avg(highp)}pp（n={len(highp)}）")
    # c) 残差分析：控制 idx 水平（三分位桶去均值）后，炸板面对 Δidx 的增量解释
    idxs = sorted(o["idx"] for o in obs if o["idx"] is not None)
    def idx_bucket(x):
        q1, q2 = idxs[len(idxs)//3], idxs[len(idxs)*2//3]
        return 0 if x <= q1 else (1 if x <= q2 else 2)
    resid = []
    for o in obs:
        if o["idx"] is None:
            continue
        peers = [x["idx"] for x in obs if x["idx"] is not None and idx_bucket(x["idx"]) == idx_bucket(o["idx"])]
        bucket_mean = sum(peers) / len(peers)
        resid.append((o, o["idx"] - bucket_mean))
    for var in ("hi_ratio", "n"):
        corr = _pearson([r[0][var] for r in resid], [r[1] for r in resid])
        print(f"残差 corr({var}, Δidx | idx桶) = {corr:.3f}")


def _eval(obs, key="phase") -> str:
    h = t = 0
    for o in obs:
        ph = o.get(key)
        if ph in ("divergence", "collapse"):
            t += 1; h += 1 if o["dpromote"] < 0 else 0
        elif ph in ("relay_heat", "launch"):
            t += 1; h += 1 if o["dpromote"] >= 0 else 0
    return f"{h}/{t} = {round(h/t*100)}%" if t else "样本不足"


def _zt_eval(obs, key: str) -> str:
    """ΔztCount 口径相位命中（divergence/collapse→跌、heat/launch→不跌）。"""
    h = t = 0
    for o in obs:
        ph = o.get(key)
        if ph not in ("divergence", "collapse", "relay_heat", "launch") or o["dzt"] is None:
            continue
        t += 1
        expect_down = ph in ("divergence", "collapse")
        h += 1 if (o["dzt"] < 0) == expect_down else 0
    return f"{h}/{t} = {round(h/t*100) if t else '-'}%"


if __name__ == "__main__":
    run()
    run_ecosystem()
