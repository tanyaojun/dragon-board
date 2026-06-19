"""MongoDB 定时备份入口，供 Windows 任务计划程序调用。

交易日 15:30 → 轻量备份（snapshot/backtest 集合）
周五 16:00  → 全量备份（所有集合）

用法：
  python scripts/scheduled_backup.py          # 自动根据当前时间判断备份类型
  python scripts/scheduled_backup.py --full   # 强制全量
  python scripts/scheduled_backup.py --light  # 强制轻量
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.data.mongodb_backup import get_mongodb_backup_service
from backend.data.mongodb_migration import get_mongodb_database
from backend.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day

TZ = ZoneInfo("Asia/Shanghai")
LOG_FILE = _project_root / "data" / "backups" / "mongodb" / "scheduled_backup.log"


def _log(msg: str) -> None:
    ts = datetime.datetime.now(TZ).isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _is_friday(dt: datetime.datetime) -> bool:
    return dt.weekday() == 4  # Monday=0, Friday=4


def run() -> int:
    now = datetime.datetime.now(TZ)
    today = now.date()

    if not is_trading_day(today):
        _log(f"{today.isoformat()} 非交易日，跳过备份")
        return 0

    is_friday = _is_friday(now)
    hour = now.hour

    # 周五 16:00 档位强制全量
    if is_friday and hour >= 16:
        mode = "full"
    elif hour >= 15:
        mode = "light"
    else:
        _log(f"{today.isoformat()} {now.strftime('%H:%M')} 未到备份时间窗口，跳过")
        return 0

    # CLI 参数覆盖自动判断
    if "--full" in sys.argv:
        mode = "full"
    elif "--light" in sys.argv:
        mode = "light"

    _log(f"开始 {mode} 备份 交易日={today.isoformat()} 周五={is_friday}")

    settings = get_settings()
    db = get_mongodb_database(
        settings.mongodb_uri,
        settings.mongodb_database,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
    )
    service = get_mongodb_backup_service()

    if mode == "light":
        result = service.create_light_backup(db)
    else:
        result = service.create_full_backup(db)

    if not result.get("ok"):
        _log(f"备份失败: {result.get('error')}")
        return 1

    verify = service.verify_backup(result["backupId"])
    if not verify.get("ok"):
        _log(f"备份校验失败: {verify.get('error')}")
        return 1

    backup_id = result["backupId"]
    doc_count = result.get("manifest", {}).get("docCounts", {}).get("snapshot_stock_rows", 0)
    _log(f"{mode} 备份成功 backupId={backup_id} stockRows={doc_count}")

    # 清理过期备份
    prune = service.prune_local_backups(dry_run=False)
    if prune.get("deleted"):
        _log(f"清理过期备份 {len(prune['deleted'])} 个: {[d['backupId'] for d in prune['deleted']]}")
    else:
        _log("无过期备份需清理")

    # 周五全量备份后上传到云存储
    if mode == "full":
        try:
            push = service.push_backup(backup_id)
            if push.get("ok"):
                _log(f"云备份上传成功 backupId={backup_id}")
            else:
                _log(f"云备份上传失败: {push.get('error')}")
        except Exception as exc:
            _log(f"云备份上传异常: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(run())
