# -*- coding: utf-8 -*-
"""vA3 竞价试盘基率 60 日复校（B 轨道，2026-11-14 用户裁决：先 A 后 B，C 等本结果）。

口径与 vA3 预登记 §1 完全一致（可比性优先）：
- 样本 = auction_trial_raw 全量日档（60 交易日 5520 行，2026-11-14 用户裁决回填）；
- PRESEAL（校准人群）= pre_percent ≥ 限价×0.99（昨涨停，与待判龙头人群同构）；
- 封板（结局）= percent ≥ 限价×0.99；限价按代码前缀：30/68→20、北交所→30、其余 10
  （ST 5% 无法从代码判定，沿用 10 日校准同口径，误差进脚注不进结论）；
- 档位与预登记 §1.1–1.4 一一对应；另附五档形态分布×封板率（C 轨道判别力预览）。

用法：./.venv/Scripts/python.exe scripts/auction_trial_base_rate_eval.py [--from X --to Y]
（零外呼纯库内计算；输出 stdout 表格，人工誊入评估文档。）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import (  # noqa: E402
    get_runtime_mongodb_database,
)
from backend.operations.auction_trial_fetch import COLLECTION_TRIAL_RAW  # noqa: E402


def limit_pct(code: str) -> float:
    """涨跌幅限制（按代码前缀；review finding-6：900=沪市 B 股 10%，北交所 43/83/87/92）。
    ST 5% 无法从代码判定——pre_percent∈[4.9,5.1] 探测（review finding-5 附带修：
    PRESEAL 行昨涨停时该探测可靠，非 PRESEAL 行维持代码口径）。"""
    if code[:2] in ("43", "83", "87", "92"):
        return 30.0
    if code[:2] in ("30", "68"):
        return 20.0
    return 10.0


def _rate(sub: list[dict], pre: bool = False) -> str:
    s = [r for r in sub if not pre or r["preseal"]]
    if not s:
        return "-"
    missing = sum(1 for r in s if r["sealed"] is None)
    scored = [r for r in s if r["sealed"] is not None]
    if not scored:
        return f"缺结局 {missing}"
    k = sum(1 for r in scored if r["sealed"])
    base = f"{k}/{len(scored)} = {k / len(scored) * 100:.0f}%"
    return base + (f"（缺结局 {missing}）" if missing else "")

def load_rows(db, d_from: str | None, d_to: str | None) -> list[dict]:
    out = []
    for doc in db[COLLECTION_TRIAL_RAW].find({}, {"rows": 1, "tradingDate": 1}):
        d = str(doc.get("tradingDate") or doc["_id"])
        if d_from and d < d_from or d_to and d > d_to:
            continue
        for code, r in (doc.get("rows") or {}).items():
            lim = limit_pct(code)
            if 4.9 <= (r.get("pre_percent") or -1) <= 5.1:
                lim = 5.0            # ST 探测（昨涨停 5% 板，代码口径不可判）
            row = {"date": d, "code": code, "limit": lim, **r}
            # review finding-4：percent 缺位 ≠ 未封板（§4.0 缺失不伪装 0/负结局），
            # sealed=None → 缺结局计数，不进分母
            row["preseal"] = (r.get("pre_percent") or 0) >= lim * 0.99
            row["sealed"] = (None if r.get("percent") is None
                             else r["percent"] >= lim * 0.99)
            out.append(row)
    return out


def time_t(r: dict) -> int | None:
    et = str(r.get("end_time") or "")
    if ":" not in et:
        return None
    hh, mm, _ = et.split(":")
    return int(hh) * 60 + int(mm)


def tier_end(r: dict) -> str:
    t = time_t(r)
    if t is None:
        return "time_missing"
    if t >= 9 * 60 + 25:
        return "full_match"
    return "no_cancel_win" if t >= 9 * 60 + 20 else "cancel_win"


def tier_jj(r: dict) -> str:
    """强度档（review finding-5）：分母 = 限价（PRESEAL 行用 pre_percent——昨涨停时
    pre=limit 且 ST 探测已修 limit；非 PRESEAL 行用代码口径 limit，防昨涨幅≠限价
    的行比值污染）。"""
    jp = r.get("jj_percent")
    denom = r.get("pre_percent") if r["preseal"] else r.get("limit")
    if jp is None or not denom:
        return "no_ratio"
    x = jp / denom * 100
    return "top95" if x >= 95 else ("mid50_95" if x >= 50 else "low_lt50")


def settlement_tier(r: dict) -> str:
    """vA3 五档近似复算（判别力预览；与题面判据同锚：end 三档 × jj 强度 + 姿态合读）。"""
    t = tier_end(r)
    j = tier_jj(r)
    if t == "full_match" and j == "top95":
        return "hard_oneword"
    if t == "no_cancel_win":
        return "no_cancel_settle"
    if t != "cancel_win":
        return "other"
    jp, pp = r.get("jj_percent"), r.get("pre_percent")
    if jp is not None and pp and jp / pp * 100 >= 50:
        return "cancel_strong"
    if jp is not None and jp < 0:
        return "cancel_weak"
    return "cancel_neutral"


def posture(r: dict) -> str:
    f, l = r.get("first_amount"), r.get("last_amount")
    if f is None or l is None:
        return "no_data"
    return "maintain" if l >= f else "decrease"


def report(rows: list[dict], title: str) -> None:
    pre = [r for r in rows if r["preseal"]]
    n_pre = len(pre)
    print(f"\n== {title} ==  rows={len(rows)}  PRESEAL={n_pre}")
    print(f"基率: ALL {_rate(rows)}  PRESEAL {_rate(rows, True)}")
    print("\n[1.1] end_time 三档 × 封板率 (ALL | PRESEAL)")
    for t in ("full_match", "no_cancel_win", "cancel_win"):
        sub = [r for r in rows if tier_end(r) == t]
        print(f"  {t:16s} {_rate(sub)}  |  {_rate(sub, True)}")
    print("\n[1.2] jj/限价 档 × 封板率 (ALL | PRESEAL)")
    for j in ("top95", "mid50_95", "low_lt50"):
        sub = [r for r in rows if tier_jj(r) == j]
        print(f"  {j:10s} {_rate(sub)}  |  {_rate(sub, True)}")
    cw = [r for r in rows if tier_end(r) == "cancel_win"]
    cw_p = [r for r in cw if r.get("jj_percent") is not None and r.get("pre_percent")]

    def _jratio(r):
        denom = r["pre_percent"] if r["preseal"] else r["limit"]   # 同 tier_jj 口径
        return r["jj_percent"] / denom * 100

    print("\n[1.3] 可撤窗撤单内二阶 (PRESEAL)")
    print(f"  试盘负涨幅      {_rate([r for r in cw_p if r['jj_percent'] < 0], True)}")
    print(f"  0–50% 限价      {_rate([r for r in cw_p if 0 <= _jratio(r) < 50], True)}")
    print(f"  ≥50% 限价       {_rate([r for r in cw_p if _jratio(r) >= 50], True)}")
    for lo, hi in (("09:00", "09:17"), ("09:17", "09:19"), ("09:19", "09:20")):
        lo_t = int(lo[:2]) * 60 + int(lo[3:5])
        hi_t = int(hi[:2]) * 60 + int(hi[3:5])
        sub = [r for r in cw if time_t(r) is not None and lo_t <= time_t(r) < hi_t]
        print(f"  撤单时点 {lo[3:]}–{hi[3:]}  {_rate(sub, True)}")
    print("\n[1.4] 资金姿态 × end 三档 封板率 (PRESEAL)")
    for t in ("full_match", "no_cancel_win", "cancel_win"):
        sub = [r for r in rows if tier_end(r) == t]
        print(f"  {t:16s} 维持 {_rate([r for r in sub if posture(r) == 'maintain'], True)}"
              f"  撤减 {_rate([r for r in sub if posture(r) == 'decrease'], True)}")
    print("\n[C 预览] 五档形态分布 × 封板率 (ALL | PRESEAL)")
    for t in ("hard_oneword", "no_cancel_settle", "cancel_weak", "cancel_neutral",
              "cancel_strong", "other"):
        sub = [r for r in rows if settlement_tier(r) == t]
        print(f"  {t:18s} n={len(sub):4d}  {_rate(sub)}  |  {_rate(sub, True)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="d_from", default=None)
    ap.add_argument("--to", dest="d_to", default=None)
    args = ap.parse_args()
    db = get_runtime_mongodb_database()
    rows = load_rows(db, args.d_from, args.d_to)
    report(rows, "60 日全窗（2026-08-14..2026-11-13）")
    report([r for r in rows if r["date"] >= "2026-11-02"], "10 日窗（2026-11-02..11-13，与 vA3 预登记同窗复算）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
