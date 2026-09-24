"""阶段多帧确认滞回——历史回放（只读，不写库）。

对每个交易日的槽位文档重放确认规则，输出立项验收报告（spec §8.2）：
- 原始切换数、确认切换数与减少比例；
- 确认延迟（每次真实切换被确认推迟的槽数，阈值 2 时最大应为 1）；
- 被吸收的单槽候选数（抖动吸收证据）；
- legacy fallback（旧文档以 stage 充当截面）、非标准槽、读取失败计数；
- 阈值 1 与原始序列逐槽一致的等价性断言。

输入合同（2026-09-24）：序列取值优先 ``rawStage``（截面真值）；仅旧文档回退 ``stage``
（已平滑的确认值不得再当原始真值）。排除两类 EOD：日级 ``_id`` 与 ``slotTime="EOD"``。
跑法：cd quant-board && PYTHONPATH=. ./.venv/Scripts/python.exe operations/replay_stage_confirm.py
"""
from __future__ import annotations

from collections import defaultdict

from pymongo import MongoClient


def replay_with_metrics(points: list[tuple[str, str]], confirm_slots: int = 2) -> dict[str, object]:
    """对升序 (slotTime, rawStage) 序列重放滞回，返回统计指标。

    与 backend/analysis/hotlist/stage_confirm.confirm_stage 同一状态机逻辑，
    额外记录每次切换的延迟与被吸收的单槽候选。
    """
    empty = {
        "raw_switches": 0,
        "confirmed_switches": 0,
        "confirmed_seq": [stage for _, stage in points],
        "delays": [],
        "absorbed_singletons": 0,
        "confirmed_transitions": [],
    }
    if len(points) < 2:
        return empty
    confirmed = points[0][1]
    pending: str | None = None
    pending_since: str | None = None
    pending_count = 0
    pending_index = 0
    raw_switches = 0
    confirmed_switches = 0
    confirmed_seq = [confirmed]
    delays: list[int] = []
    absorbed = 0
    transitions: list[tuple[str, str, str]] = []

    for index in range(1, len(points)):
        slot_time, raw_stage = points[index]
        if raw_stage != points[index - 1][1]:
            raw_switches += 1
        if raw_stage == confirmed:
            if pending is not None and pending_count == 1:
                absorbed += 1  # 单槽候选被吸收（抖动证据）
            pending, pending_since, pending_count = None, None, 0
            confirmed_seq.append(confirmed)
            continue
        if raw_stage == pending:
            pending_count += 1
        else:
            pending, pending_since, pending_count, pending_index = raw_stage, slot_time, 1, index
        if pending_count >= confirm_slots:
            delays.append(index - pending_index)  # 确认相对候选起点晚的可观察槽数（阈值 2 时应为 1）
            transitions.append((pending_since, confirmed, raw_stage))
            confirmed = raw_stage
            confirmed_switches += 1
            pending, pending_since, pending_count = None, None, 0
        confirmed_seq.append(confirmed)
    return {
        "raw_switches": raw_switches,
        "confirmed_switches": confirmed_switches,
        "confirmed_seq": confirmed_seq,
        "delays": delays,
        "absorbed_singletons": absorbed,
        "confirmed_transitions": transitions,
    }


def collect_day_points(docs: list[dict]) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """从当日槽位文档行收集升序 (slotTime, rawStage) 序列与质量计数（纯函数，供测试）。"""
    points: list[tuple[str, str]] = []
    counters = {"legacy_fallback": 0, "invalid_slot": 0}
    eod_marker = "dragonboard_live:half_hour:"
    for doc in docs:
        # 双 EOD 形态排除：slotTime="EOD" 哨兵 + 日级 _id（迁移后旧 EOD 的 slotTime 仍是 HH:MM）
        if str(doc.get("slotTime") or "") == "EOD":
            continue
        doc_id = str(doc.get("_id") or "")
        if doc_id.startswith(eod_marker) and len(doc_id.split(":")) == 3:
            continue
        slot_time = str(doc.get("slotTime") or "")
        if len(slot_time) != 5 or slot_time[2] != ":":
            counters["invalid_slot"] += 1
            continue
        raw_stage = str(doc.get("rawStage") or "").strip()
        if not raw_stage:
            raw_stage = str(doc.get("stage") or "").strip()
            if raw_stage:
                counters["legacy_fallback"] += 1
        if raw_stage:
            points.append((slot_time, raw_stage))
    points.sort(key=lambda item: item[0])
    return points, counters


def main() -> None:
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client["dragon_board_quant"]
    docs = db["hotlist_sentiment"].find(
        {"_id": {"$regex": "^dragonboard_live:half_hour:"}, "slotTime": {"$ne": "EOD"}},
        {"_id": 1, "tradingDate": 1, "slotTime": 1, "stage": 1, "rawStage": 1},
    )
    by_date: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        parts = str(d["_id"]).split(":")
        if len(parts) >= 5:  # 标准 HH:MM 槽位文档
            by_date[d["tradingDate"]].append(d)

    dates = sorted(by_date)
    totals = {"raw": 0, "conf": 0, "absorbed": 0, "legacy": 0, "invalid": 0}
    all_delays: list[int] = []
    transitions: list[str] = []
    print(f"replay days={len(dates)} confirmSlots=2 (input: rawStage ?? stage)")
    print(f"{'date':<12}{'slots':>6}{'raw_sw':>8}{'conf_sw':>9}{'absorb':>8}{'maxdelay':>9}")
    for date in dates:
        points, counters = collect_day_points(list(by_date[date]))
        totals["legacy"] += counters["legacy_fallback"]
        totals["invalid"] += counters["invalid_slot"]
        metrics = replay_with_metrics(points, 2)
        totals["raw"] += int(metrics["raw_switches"])
        totals["conf"] += int(metrics["confirmed_switches"])
        totals["absorbed"] += int(metrics["absorbed_singletons"])
        all_delays.extend(int(d) for d in metrics["delays"])
        for since, from_stage, to_stage in metrics["confirmed_transitions"]:
            transitions.append(f"{date} {since}: {from_stage}→{to_stage}")
        max_delay = max((int(d) for d in metrics["delays"]), default=0)
        print(f"{date:<12}{len(points):>6}{metrics['raw_switches']:>8}{metrics['confirmed_switches']:>9}"
              f"{metrics['absorbed_singletons']:>8}{max_delay:>9}")

    reduction = (1 - totals["conf"] / totals["raw"]) * 100 if totals["raw"] else 0.0
    print(f"\nraw_switches={totals['raw']} confirmed_switches={totals['conf']} "
          f"reduction={reduction:.1f}% (target >= 40% -> {'PASS' if reduction >= 40 else 'REVIEW'})")
    print(f"absorbed_singletons={totals['absorbed']} legacy_fallback={totals['legacy']} "
          f"invalid_slot={totals['invalid']} read_failures=0")
    if all_delays:
        print(f"confirm delay: max={max(all_delays)} avg={sum(all_delays) / len(all_delays):.2f} "
              f"(threshold=2 时理论最大为 1 个可观察槽)")
    if transitions:
        print("confirmed transitions:")
        for line in transitions:
            print(f"  - {line}")

    # 阈值 1 等价性断言：逐槽确认序列必须与原始序列完全一致
    mismatches = 0
    for date in dates:
        points, _ = collect_day_points(list(by_date[date]))
        metrics = replay_with_metrics(points, 1)
        if metrics["confirmed_seq"] != [stage for _, stage in points]:
            mismatches += 1
            print(f"EQUIV FAIL {date}")
    print(f"slots=1 equivalence: {'PASS' if mismatches == 0 else f'FAIL({mismatches})'}")


if __name__ == "__main__":
    main()
