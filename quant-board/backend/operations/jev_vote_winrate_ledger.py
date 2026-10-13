# -*- coding: utf-8 -*-
"""方向判读 v4-material(b 代) 两周验证台账（2026-10-13 用户裁决：挂调度跑半个月，无增量则撤）。

- 判读源：hotlist_jev_vote_confirm_pilot（slotTime=11:00，questionSetVersion=v4-material，
  ammoVersion=2026-10-13b）——即调度 jevVoteRecheck 每日产出；
- T+1 验证：判读日次一交易日的 15:00 帧 change 优先，掉榜股 TDX 日线补全（无偏全池）；
- 对照线：规则线（判读日 15:00 快照 snapshot_analysis synergy 档 → synergy_direction 查表），
  同股同场同一把尺子；
- 计分（冻结）：buy 对=t1>0；sell 对=t1<0；hold 对=|t1|<5；insufficient/缺验证值不计；
- 产出：hotlist_jev_vote_winrate_ledger（SUMMARY 单文档+逐日 docs）；纯读+小写，零 jev 调用。
- 裁决（2026-10-27 或判读满 10 个交易日）：V4 累计胜率 > 规则线累计胜率 → 有增量保留；
  否则从调度撤除 vote 判读。

CLI：python -m backend.operations.jev_vote_winrate_ledger [--start 2026-10-13]
"""
from __future__ import annotations

import argparse
import time
from typing import Any

LEDGER_COL = "hotlist_jev_vote_winrate_ledger"
VERIFY_START = "2026-10-13"
VERIFY_DEADLINE = "2026-10-27"  # 两周验证截止（10 个交易日）
EXPECTED_AMMO = "2026-10-13b"


def _trading_dates(db: Any, dataset_id: str) -> list[str]:
    return sorted({str(f["tradingDate"]) for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": "15:00"},
        {"tradingDate": 1}) if f.get("tradingDate")})


def _next_trading_day(db: Any, dataset_id: str, date: str) -> str | None:
    dates = [d for d in _trading_dates(db, dataset_id) if d > date]
    return dates[0] if dates else None


def _t1_change(db: Any, dataset_id: str, code: str, date: str,
               next_day: str, t1_frame: dict[str, Any]) -> float | None:
    """次一交易日收盘涨幅：15:00 帧 change 优先，缺失走 TDX 日线（收盘/收盘-1）。"""
    v = t1_frame.get(code)
    if isinstance(v, (int, float)):
        return v
    from backend.operations.jev_label_jiuyan import _daily_bars
    bars = _daily_bars(code)
    days = {b.get("date"): float(b.get("close")) for b in (bars or [])
            if b.get("date") in (date, next_day) and b.get("close")}
    if date in days and next_day in days and days[date]:
        return round((days[next_day] / days[date] - 1) * 100, 2)
    return None


def _score(direction: str, t1: float | None) -> bool | None:
    if direction not in ("buy", "sell", "hold") or t1 is None:
        return None
    if direction == "buy":
        return t1 > 0
    if direction == "sell":
        return t1 < 0
    return abs(t1) < 5.0


def build_ledger(db: Any, dataset_id: str = "dragonboard_live",
                 start: str = VERIFY_START) -> dict[str, Any]:
    col = db["hotlist_jev_vote_confirm_pilot"]
    out: dict[str, Any] = {"v4": {"n": 0, "win": 0}, "rule": {"n": 0, "win": 0}, "days": []}
    for doc in col.find({"slotTime": "11:00", "questionSetVersion": "v4-material",
                         "ammoVersion": EXPECTED_AMMO, "status": "ok"}):
        date = doc.get("tradingDate")
        code = str(doc.get("code"))
        if not date or date < start:
            continue
        next_day = _next_trading_day(db, dataset_id, date)
        if next_day is None:
            continue  # T+1 未到，pending
        f13 = db["snapshot_frames"].find_one(
            {"datasetId": dataset_id, "type": "half_hour",
             "tradingDate": next_day, "slotTime": "15:00"}, {"snapshotId": 1})
        t1_frame = {str(r["code"]): r.get("change") for r in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "snapshotId": str(f13["snapshotId"])},
            {"code": 1, "change": 1})} if f13 else {}
        t1 = _t1_change(db, dataset_id, code, date, next_day, t1_frame)
        s = _score(doc.get("voteDirection"), t1)
        rule_dir = doc.get("synergyDirection")
        rs = _score(rule_dir, t1)
        day = next((x for x in out["days"] if x["date"] == date), None)
        if day is None:
            day = {"date": date, "nextDay": next_day, "n": 0, "win": 0,
                   "ruleN": 0, "ruleWin": 0}
            out["days"].append(day)
            out["days"].sort(key=lambda x: x["date"])
        if s is not None:
            out["v4"]["n"] += 1
            out["v4"]["win"] += int(s)
            day["n"] += 1
            day["win"] += int(s)
        if rs is not None:
            out["rule"]["n"] += 1
            out["rule"]["win"] += int(rs)
            day["ruleN"] += 1
            day["ruleWin"] += int(rs)
    v4, rule = out["v4"], out["rule"]
    out["summary"] = {
        "deadline": VERIFY_DEADLINE, "expectedAmmo": EXPECTED_AMMO,
        "v4Rate": round(v4["win"] / v4["n"] * 100, 1) if v4["n"] else None,
        "ruleRate": round(rule["win"] / rule["n"] * 100, 1) if rule["n"] else None,
        "delta": (round((v4["win"] / v4["n"] - rule["win"] / rule["n"]) * 100, 1)
                  if v4["n"] and rule["n"] else None),
        "verdict": None,
    }
    d = out["summary"]["delta"]
    if d is not None:
        out["summary"]["verdict"] = "有增量（保留）" if d > 0 else "无增量（撤除 vote 判读）"
    return out


def persist(db: Any, ledger: dict[str, Any]) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db[LEDGER_COL].replace_one(
        {"_id": "SUMMARY"},
        {"_id": "SUMMARY", "origin": "vote_winrate_ledger", **ledger["summary"],
         "v4": ledger["v4"], "rule": ledger["rule"], "computedAt": now}, upsert=True)
    for day in ledger["days"]:
        db[LEDGER_COL].replace_one(
            {"_id": f"DAY:{day['date']}"},
            {"_id": f"DAY:{day['date']}", "origin": "vote_winrate_ledger", **day,
             "computedAt": now}, upsert=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="v4-material(b) 两周验证台账")
    ap.add_argument("--dataset-id", default="dragonboard_live")
    args = ap.parse_args()
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    ledger = build_ledger(db, args.dataset_id)
    persist(db, ledger)
    s = ledger["summary"]
    print(f"[winrate] 累计 V4: {s['v4Rate']}% ({ledger['v4']['n']} 例) | "
          f"规则线: {s['ruleRate']}% ({ledger['rule']['n']} 例) | Δ {s['delta']}pct"
          f" | 判定: {s['verdict']} | 截止 {s['deadline']}")
    for day in ledger["days"]:
        r4 = round(day["win"]/day["n"]*100, 1) if day["n"] else "-"
        rr = round(day["ruleWin"]/day["ruleN"]*100, 1) if day["ruleN"] else "-"
        print(f"  {day['date']} (T+1={day['nextDay']}): V4 {day['win']}/{day['n']}={r4}%"
              f" | 规则 {day['ruleWin']}/{day['ruleN']}={rr}%")


if __name__ == "__main__":
    main()
