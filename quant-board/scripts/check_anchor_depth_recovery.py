# -*- coding: utf-8 -*-
"""锚深度恢复曲线复检（2026-10-02 立项，只读，零 jev API 调用）。

背景见 docs/hotlist-jev/jev-sentiment-questionset-review.md §十一：
10-09 首跑锚窗口有效样本仅 8/20（9 月 THS limitSummary 间歇失败所致），
采集链已加 THS 重试 + limit_summary_missing 帧级标记（195d405d）。
本脚本验证 10 月自愈节奏；建议 10-16 起每个周五盘后跑一次。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe scripts/check_anchor_depth_recovery.py 2026-10-16
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.jev.jev_sentiment_compute import build_history_stats_calendar


def main(trading_date: str) -> int:
    db = get_runtime_mongodb_database()

    # 1) 锚窗口：日历口径有效样本
    stats = build_history_stats_calendar(db, "dragonboard_live", trading_date)
    valid = [s for s in stats if s["ztCount"]]
    oct_days = [s for s in valid if s["date"] >= f"{trading_date[:4]}-10-01"]
    invalid = [s["date"] for s in stats if not s["ztCount"]]
    print(f"== 锚窗口（{trading_date} 视角）==")
    print(f"窗口 {stats[0]['date']} → {stats[-1]['date']}，{len(stats)} 历日，有效 {len(valid)}/{len(stats)}"
          f"（其中 10 月 {len(oct_days)}）")
    print(f"无效日 {len(invalid)} 个: {invalid or '无'}")

    # 2) 10 月帧健康率（重试收益）：15:00 槽 ztCount>0 占比 + limit_summary_missing 标记数
    month_prefix = trading_date[:7]
    frames = list(db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour",
         "tradingDate": {"$regex": f"^{month_prefix}"}},
        {"tradingDate": 1, "slotTime": 1, "limitSummary.zhaban.ztCount": 1, "qualityFlags": 1}))
    total = healthy = missing_flag = 0
    by_slot: dict[str, list[int]] = {}
    for f in frames:
        slot = str(f.get("slotTime"))
        zt = ((f.get("limitSummary") or {}).get("zhaban") or {}).get("ztCount")
        ok = isinstance(zt, (int, float)) and not isinstance(zt, bool) and zt > 0
        total += 1
        healthy += 1 if ok else 0
        if "limit_summary_missing" in (f.get("qualityFlags") or []):
            missing_flag += 1
        g = by_slot.setdefault(slot, [0, 0])
        g[0] += 1
        g[1] += 1 if ok else 0
    print(f"\n== {month_prefix} 帧健康率（重试收益）==")
    print(f"全部 half_hour 帧 {total}，limitSummary 健康 {healthy}（{round(healthy / max(total, 1) * 100, 1)}%），"
          f"limit_summary_missing 标记 {missing_flag}")
    for slot in sorted(by_slot):
        n, ok_n = by_slot[slot]
        print(f"slot {slot}: {ok_n}/{n}")
    print(f"（对照：9 月 15:00 帧健康率 8/21≈38%）")

    # 3) v2 EOD 覆盖：每月每个交易日应有 ok 文档
    eods = list(db["hotlist_jev_sentiment"].find(
        {"kind": "eod", "tradingDate": {"$regex": f"^{month_prefix}"}},
        {"tradingDate": 1, "status": 1}))
    from collections import Counter
    dist = Counter(d.get("status") for d in eods)
    print(f"\n== {month_prefix} v2 EOD 覆盖 ==")
    print(f"共 {len(eods)} 文档，status 分布 {dict(dist)}")

    # 判读
    print("\n== 判读 ==")
    a = len(valid) >= 14
    print(f"① 锚 ≥14/20（自愈中）: {'是' if a else '否'}（实际 {len(valid)}/20）")
    if total == 0:
        print("② 帧健康率: 10 月尚无帧（假期或尚未开盘）——本读数为 9 月基线，待有帧后判读")
        b = True
    else:
        b = healthy / total >= 0.6
        print(f"② 帧健康率 ≥60%（重试起效）: {'是' if b else '否'}（实际 {round(healthy / total * 100, 1)}%）")
    print(f"③ EOD 覆盖: ok={dist.get('ok', 0)}，degraded={dist.get('degraded', 0)}，no_data={dist.get('no_data', 0)}"
          f"（degraded/no_data 应与 THS 失败日对应，属数据链预期）")
    if not a or not b:
        if total == 0 and not a:
            print("注：10 月尚无帧时锚读数即 9 月基线（10-09 为 8/20），属已知既成事实非异常。")
        else:
            print("异常信号：锚恢复滞后或帧健康率未改善——排查方向：THS 源策略变化 / 8001 进程是否加载 195d405d "
                  "后代码（重启时间）/ 重试参数。只读复检不改代码，异常呈报用户裁决。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: check_anchor_depth_recovery.py <YYYY-MM-DD>（锚视角日，建议周五盘后）")
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1]))
