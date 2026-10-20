# -*- coding: utf-8 -*-
"""题材证据块预览（L3，零模型调用）：把某日各板块的「产业树催化 + 投资日历」打出来人工过目。

用法：
  ./.venv/Scripts/python.exe scripts/theme_evidence_preview.py --date 2026-10-20
  ./.venv/Scripts/python.exe scripts/theme_evidence_preview.py --date 2026-10-20 --boards 机器人,物理AI
  ./.venv/Scripts/python.exe scripts/theme_evidence_preview.py --date 2026-10-20 --top 0   # 全板块

默认取该日韭研异动板块按涨停家数前 6，逐板块打印证据块（与未来投喂 jev 的文本逐字一致）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.hotlist.theme_event_digest import (  # noqa: E402
    build_theme_evidence_block,
    corpus_state,
)
from backend.data.repositories.repository_factory import get_runtime_mongodb_database  # noqa: E402


def _top_boards(db, date: str, limit: int) -> list[str]:
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}) or \
        db["jiuyan_action"].find_one({"_id": f"{date}:midday"}) or {}
    rows = [(str(f.get("name") or ""), len(f.get("stocks") or []))
            for f in doc.get("fields") or [] if f.get("name")]
    rows.sort(key=lambda r: -r[1])
    return [n for n, _ in (rows if limit <= 0 else rows[:limit])]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--boards", default=None, help="逗号分隔；缺省按当日板块涨停家数取 top")
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--content-chars", type=int, default=260)
    args = ap.parse_args()

    db = get_runtime_mongodb_database()
    state = corpus_state(db, date=args.date)
    print(f"# 语料状态: {state}\n")
    boards = ([b.strip() for b in args.boards.split(",") if b.strip()]
              if args.boards else _top_boards(db, args.date, args.top))
    for board in boards:
        out = build_theme_evidence_block(db, board_name=board, date=args.date,
                                         content_chars=args.content_chars)
        print(f"===== {board} （{len(out['text'])} 字）")
        print(out["text"])
        print()


if __name__ == "__main__":
    main()
