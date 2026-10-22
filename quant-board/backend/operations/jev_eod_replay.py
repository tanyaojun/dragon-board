# -*- coding: utf-8 -*-
"""日级 EOD 指定日期重放（2026-10-22 第二轮裁决：只跑 10-20/10-21）。

- 默认 dry-run：只打印计划，不调 jev；
- `--apply`：先导出旧 EOD 文档到 `data/backups/`（JSON 文件，非业务库集合），
  再调用生产入口 `compute_and_upsert_for_day(origin="replay")` 覆盖；
- token 缺失直接退出，不落 degraded 文档（重放授权明确要求真实调用）。

用法：
    python -m backend.operations.jev_eod_replay --dates 2026-10-20 2026-10-21
    python -m backend.operations.jev_eod_replay --dates 2026-10-20 2026-10-21 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

_BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"


def export_eod_docs(db: Any, dates: list[str], *, dataset_id: str = "dragonboard_live",
                    out_dir: Path = _BACKUP_DIR) -> Path:
    """旧 EOD 文档导出为 JSON 文件（mongoexport 等价物；不建业务库备份集合）。"""
    docs = list(db["hotlist_jev_sentiment"].find(
        {"kind": "eod", "datasetId": dataset_id, "tradingDate": {"$in": dates}}))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"jev-eod-replay-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(docs, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    return path


def _close_frame_present(db: Any, date: str, dataset_id: str) -> bool:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"}) is not None


def _existing_eod_brief(db: Any, date: str, dataset_id: str) -> dict[str, Any]:
    """dry-run 展示现有 EOD 代际/覆盖，避免重复 --apply 烧调用而不自知。"""
    doc = db["hotlist_jev_sentiment"].find_one(
        {"_id": f"{dataset_id}:half_hour:{date}:EOD"}) or {}
    coverage = doc.get("frameCoverage") if isinstance(doc.get("frameCoverage"), dict) else {}
    return {
        "status": doc.get("status"),
        "questionSetVersion": doc.get("questionSetVersion"),
        "corpusCaliberVersion": doc.get("corpusCaliberVersion"),
        "hasCloseFrame": coverage.get("hasCloseFrame"),
        "dayTemperature": (doc.get("scores") or {}).get("day_temperature"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="指定日期日级 EOD 重放（真实 jev，需确认预算）")
    parser.add_argument("--dates", nargs="+", default=["2026-10-20", "2026-10-21"])
    parser.add_argument("--dataset-id", default="dragonboard_live")
    parser.add_argument("--apply", action="store_true", help="调真实 jev 并覆盖（缺省只打印计划）")
    args = parser.parse_args()

    # settings 导入即加载 .env.local（JEV_CF_TOKEN 等）；必须在计算前
    import backend.core.settings  # noqa: F401
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.jev.jev_sentiment_compute import compute_and_upsert_for_day

    token = os.environ.get("JEV_CF_TOKEN", "").strip()
    typesafe = os.environ.get("JEV_TYPESAFE_KEY", "").strip()
    if args.apply and not (token or typesafe):
        raise SystemExit("JEV_CF_TOKEN / JEV_TYPESAFE_KEY 缺失：重放要求真实调用，拒绝落 degraded")

    db = get_runtime_mongodb_database()
    print(f"重放日期：{args.dates}；dataset={args.dataset_id}；"
          f"通道={'typesafe' if typesafe else 'cloudflare' if token else '无'}")
    for date in args.dates:
        has_close = _close_frame_present(db, date, args.dataset_id)
        existing = _existing_eod_brief(db, date, args.dataset_id)
        print(f"  {date} 15:00 帧={'有' if has_close else '缺'}"
              f"{'（将显式降级）' if not has_close else ''}"
              f"；现有 EOD status={existing['status'] or '无'}"
              f" qver={existing['questionSetVersion'] or '无'}"
              f" corpus={existing['corpusCaliberVersion'] or '无'}"
              f" 收盘帧={existing['hasCloseFrame']}"
              f" day_temp={existing['dayTemperature']}")
    if not args.apply:
        print("dry 模式（--apply 才会调真实 jev 并覆盖；先导出旧文档到 data/backups/）")
        return

    backup = export_eod_docs(db, args.dates, dataset_id=args.dataset_id)
    print(f"旧 EOD 已导出：{backup}")
    for date in args.dates:
        result = compute_and_upsert_for_day(
            db, dataset_id=args.dataset_id, trading_date=date, origin="replay")
        doc = db["hotlist_jev_sentiment"].find_one(
            {"_id": f"{args.dataset_id}:half_hour:{date}:EOD"}) or {}
        usage = doc.get("usage") or {}
        print(f"  {date} status={result.get('status')} "
              f"day_temp={(doc.get('scores') or {}).get('day_temperature')} "
              f"usable={doc.get('frameCoverage', {}).get('hasCloseFrame')} "
              f"version={doc.get('questionSetVersion')} "
              f"tokens_in={usage.get('input_tokens')} tokens_out={usage.get('output_tokens')}")


if __name__ == "__main__":
    main()