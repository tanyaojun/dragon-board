# -*- coding: utf-8 -*-
"""板块龙头隔日连板基线（零模型调用，2026-10-20）。

回答两个问题：
1. 「板块龙头隔日继续封板」在**纯结构特征**下已经能被预测到什么程度？（给 jev 题材判定定基线）
2. 结构特征之外还剩多少方差？（=题材语料的价值上限房间）

口径（全部复用生产单一事实源，禁第二套）：
- 封板判定 = `jiuyan_board_info` 触板 − THS 炸板池二分，剔 ST/北交所（与涨停复盘同口径）；
- 连板高度 = `jiuyan_streak_map` 真连板（N==M 直取 / N>M 回溯，不可算=None）；
- 龙一 = 板块内真连板最高 → 封板时间最早（`theme_leader_ammo.rank_board_stocks`）；
- 结局 = 次一交易日该股是否仍在封板集合内（sealed）。

实现上移到 `backend/operations/theme_leader_baseline.py`（取数/龙头识别）与
`backend/analysis/hotlist/theme_leader_ammo.py`（分桶/汇总），本脚本只做 CLI：
题材层投喂 runner 用的就是同一份口径，禁止在此再写第二套。

用法：
  ./.venv/Scripts/python.exe scripts/theme_leader_sustain_baseline.py \
      --start 2026-08-01 --end 2026-10-19 [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hotlist.theme_leader_ammo import summarize_rows  # noqa: E402
from backend.data.repositories.repository_factory import get_runtime_mongodb_database  # noqa: E402
from backend.operations.theme_leader_baseline import build_rows  # noqa: E402


def build(start: str, end: str) -> dict:
    """窗口内龙头-日样本（含次日结局）。"""
    return build_rows(get_runtime_mongodb_database(), start, end)


def summarize(out: dict) -> dict:
    """基线汇总（分桶函数与投喂题集共用，见 theme_leader_ammo）。"""
    rows = out["rows"]
    summary = summarize_rows(rows)
    summary["boardContinuedDist"] = dict(Counter(r["boardContinued"] for r in rows))
    summary["skipped"] = out["skipped"]
    summary["dates"] = len(out["dates"])
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-01")
    ap.add_argument("--end", default="2026-10-19")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    out = build(args.start, args.end)
    summary = summarize(out)
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"summary": summary, "rows": out["rows"]}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()