"""阶段多帧确认滞回规则——历史回放（只读，不写库）。

对每个交易日的槽位文档 stage 序列（各槽截面判定真值）重放 confirmSlots=2 滞回确认，
统计截面切换次数 vs 确认后切换次数，验证立项报告目标（确认切换减少 ≥40%）。

规则与 docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md §5.2 一致。
跑法：cd quant-board && PYTHONPATH=. ./.venv/Scripts/python.exe operations/replay_stage_confirm.py
"""
from __future__ import annotations

from collections import defaultdict

from pymongo import MongoClient


def replay(seq: list[str], confirm_slots: int = 2) -> tuple[int, int, list[str]]:
    """返回 (截面切换数, 确认后切换数, 确认序列)。seq 为按时间升序的槽位 stage 序列。"""
    if len(seq) < 2:
        return 0, 0, list(seq)
    confirmed = [seq[0]]
    pending: str | None = None
    pending_n = 0
    switches_raw = 0
    switches_conf = 0
    for i in range(1, len(seq)):
        if seq[i] != seq[i - 1]:
            switches_raw += 1
        if seq[i] == confirmed[-1]:
            pending, pending_n = None, 0  # 规则4：候选期间截面变回原确认 → 候选清空（抖动吸收）
        else:
            if pending == seq[i]:
                pending_n += 1
            else:
                pending, pending_n = seq[i], 1
            if pending_n >= confirm_slots:
                confirmed.append(seq[i])
                switches_conf += 1  # 规则3：连续复现达标 → 确认切换
                pending, pending_n = None, 0
            else:
                confirmed.append(confirmed[-1])  # 规则3：未达标 → 保持 + pending 标注
    return switches_raw, switches_conf, confirmed


def main() -> None:
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client["dragon_board_quant"]
    docs = db["hotlist_sentiment"].find(
        {"_id": {"$regex": "^dragonboard_live:half_hour:"}, "slotTime": {"$ne": "EOD"}},
        {"_id": 1, "tradingDate": 1, "slotTime": 1, "stage": 1},
    )
    by_date: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for d in docs:
        parts = str(d["_id"]).split(":")
        if len(parts) >= 5:  # 标准 HH:MM 槽位
            by_date[d["tradingDate"]].append((str(d["slotTime"]), str(d.get("stage") or "")))
    dates = sorted(by_date)[-30:]  # 近 30 个交易日
    total_raw = total_conf = 0
    print(f"replay days={len(dates)} confirmSlots=2")
    print(f"{'date':<12}{'slots':>6}{'raw_sw':>8}{'conf_sw':>9}  stages(first->last)")
    for date in dates:
        rows = sorted(by_date[date])
        seq = [s for _, s in rows]
        raw_sw, conf_sw, confirmed = replay(seq, 2)
        total_raw += raw_sw
        total_conf += conf_sw
        mark = " *" if raw_sw > conf_sw else ""
        print(f"{date:<12}{len(seq):>6}{raw_sw:>8}{conf_sw:>9}  {seq[0]}→{seq[-1]}{mark}")
    reduction = (1 - total_conf / total_raw) * 100 if total_raw else 0.0
    print(f"\nTOTAL raw_switches={total_raw} confirmed_switches={total_conf} reduction={reduction:.1f}%")
    print(f"target: reduction >= 40% -> {'PASS' if reduction >= 40 else 'REVIEW'}")


if __name__ == "__main__":
    main()
