from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.data.repositories import repository_factory
from backend.data.archive.service import ArchiveService
from backend.data.backup.mongodb_backup import get_mongodb_backup_service
from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day
from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day

_TZ = ZoneInfo("Asia/Shanghai")

_PULSE_OUT_DIR = Path("data/reports/phase-monitor")
_PULSE_TIMEOUT_SECONDS = 2700  # SP2-B：多臂脉拍（基线+champion+≤2 挑战者）由 900 提升至 45min
_ARMS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "phase_pulse_arms.json"


def _pulse_arms_args() -> list[str]:
    """SP2-B：排程脉拍多臂参数（挑战者臂经 config/phase_pulse_arms.json 登记；预算≤2）。

    配置文件缺失/解析失败 → 回退默认两臂（baseline,champion，fail-visible 不阻断排程）。
    """
    try:
        raw = json.loads(_ARMS_CONFIG_PATH.read_text(encoding="utf-8"))
        names = [k for k, v in raw.items() if isinstance(v, dict) and isinstance(v.get("trade_config"), dict)]
        challengers = [k for k in names if k not in ("baseline", "champion")]
        if len(challengers) > 2:
            challengers = challengers[:2]  # 预算截断（超出者不进排程，fail-visible 于日志）
            print(f"[schedule] 挑战者臂超预算，仅取前 2：{challengers}", file=sys.stderr)
        return ["--arms", ",".join(["baseline", "champion", *challengers]),
                "--arm-config", str(_ARMS_CONFIG_PATH)]
    except FileNotFoundError:
        print(f"[schedule] 臂配置缺失，回退默认两臂：{_ARMS_CONFIG_PATH}", file=sys.stderr)
        return []
    except Exception as exc:  # noqa: BLE001 — 排程步不因臂配置畸形阻断
        print(f"[schedule] 臂配置解析失败，回退默认两臂：{exc}", file=sys.stderr)
        return []


def _should_run_phase_pulse(db: Any, today: str, dataset_id: str, snapshot_type: str) -> tuple[bool, str]:
    """脉拍门控：当日有 EOD 情绪文档才跑（非交易日/数据未落 → 跳过，不烧算力不覆盖旧档）。"""
    try:
        doc = db["hotlist_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": today, "slotTime": "EOD"},
            {"_id": 1},
        )
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        return False, f"gate check failed: {exc}"
    if not doc:
        return False, f"no EOD doc for {today}（非交易日或数据未落）"
    return True, ""


def _run_phase_pulse_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """M3 盘面脉拍（advisory 步，2026-10-01）：子进程隔离跑当月至今相位快照。

    - 门控=当日 EOD 情绪文档存在（is_trading_day 日历之外的更强校验：数据真落了才跑）；
    - 子进程=独立 python 引擎（与备份链进程内存隔离，8.5GB 扫描事故纪律），超时 900s；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（研究证据链，非生产数据链）；
    - 结果：data/reports/phase-monitor/pulse-<month>.json + Mongo phase_monitor（pulse:<month>），
      前端相位页签"本月至今"卡直接读。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    month = today[:7]
    out_path = _PULSE_OUT_DIR / f"pulse-{month}.json"
    cmd = [
        sys.executable, "-m", "backend.operations.phase_pulse",
        "--month", month, "--end", today, "--out", str(out_path),
        *_pulse_arms_args(),
    ]
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),  # SP2-B 修复：原 parents[1]=backend/ 导致 ModuleNotFoundError，排程脉拍从未能运行
            capture_output=True,
            text=True,
            timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "phase_pulse_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "phase_pulse_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    # SP2-B：Mongo 入库为准（前端走 board API 读 Mongo；本地 JSON 仅为即时产物）。
    # phase_pulse.main 内 persist_pulse 幂等 upsert pulse:<month>；此处校验 updatedAt 新鲜度。
    mongo_fresh = False
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc_m = db["phase_monitor"].find_one({"_id": f"pulse:{month}"}, {"updatedAt": 1})
        updated = str((doc_m or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    summary: dict[str, Any] = {}
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8"))
        ab = doc.get("ab") or {}
        summary = {
            "month": doc.get("month"),
            "tradeCount": doc.get("tradeCount"),
            "netReturnSaved": (ab.get("delta") or {}).get("netReturnSaved"),
        }
    except Exception as exc:  # noqa: BLE001 — 摘要解析失败不影响脉拍本体已落库
        summary = {"parseError": str(exc)}
    # 评审 P1-2：记录的臂清单从脉拍参数回填（单一事实源=config 登记文件），不再维护过期常量
    pulse_args = _pulse_arms_args()
    arms_record = "baseline,champion"
    if len(pulse_args) >= 2 and pulse_args[0] == "--arms":
        arms_record = pulse_args[1]
    result = {"ok": True, "month": month, "out": str(out_path), "summary": summary,
              "mongoFresh": mongo_fresh, "arms": arms_record}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor pulse:<month> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    return result


def _should_run_phase_band(db: Any, today: str) -> tuple[bool, str]:
    """相位哨兵门控：当日韭研 final 名单 + 15:00 盘面帧都存在才跑（缺一→哨兵无原料，跳过）。"""
    try:
        jy = db["jiuyan_action"].find_one({"_id": f"{today}:final"}, {"_id": 1})
        fr = db["snapshot_frames"].find_one(
            {"type": "half_hour", "tradingDate": today, "slotTime": "15:00",
             "limitSummary.zhaban.ztCount": {"$gt": 0}}, {"_id": 1})
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        return False, f"gate check failed: {exc}"
    if not jy:
        return False, f"no jiuyan final for {today}"
    if not fr:
        return False, f"no 15:00 frame metrics for {today}"
    return True, ""


def _run_phase_band_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """Q5 相位哨兵（advisory 步，2026-10-03）：日级独立调用判当日盘面档位。

    - 门控=当日 jiuyan final + 15:00 盘面帧（原料齐才跑，非交易日/缺料跳过）；
    - 子进程=jev_label_jiuyan --phase-band-day（幂等：当日 PHASE 文档已 ok 自动跳过）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（哨兵证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_label_jiuyan", "--phase-band-day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "phase_band_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "phase_band_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    phase_band = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{today}:PHASE"},
                                                       {"phaseBand": 1, "computedAt": 1})
        phase_band = doc.get("phaseBand") if doc else None
        updated = str((doc or {}).get("computedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "date": today, "phaseBand": phase_band, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "PHASE 文档 computedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    return result


def _run_jiuyan_label_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """个股驱动打标日增量（advisory 步，2026-10-03 用户裁决挂链）。

    - 门控与相位哨兵同源（当日 jiuyan final + 15:00 盘面帧）；
    - 子进程=jev_label_jiuyan --start/--end 当日（幂等：已 ok 标签自动跳过，≈21 万 tokens/交易日，用户裁决挂链）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（证据链积累，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)  # 同一原料门控
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    try:
        cmd = [sys.executable, "-m", "backend.operations.jev_label_jiuyan",
               "--start", today, "--end", today]
        # F2 门控（融合总纲）：个股相位分线附带打标默认关，环境变量 JIUYAN_STOCK_PHASE_ENABLED=1
        # 且用户明确批准 token 成本后才可开启（≈3-5 万 tokens/日合并口径；开启前零额外调用）
        if os.environ.get("JIUYAN_STOCK_PHASE_ENABLED") == "1":
            cmd += ["--with-stock-phase"]
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "jiuyan_label_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "jiuyan_label_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    labeled = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        labeled = sum(1 for d in db["hotlist_jev_driver_labels"].find(
            {"tradingDate": today, "status": "ok", "origin": {"$ne": "phase_band_daily"}}, {"_id": 1}))
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    return {"ok": True, "date": today, "labeledToday": labeled}


def _run_deep_valley_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """C9 深谷状态月度复验（advisory 步，2026-10-03 协议 §十四/M4 §8）。

    - 门控=当日 EOD 情绪文档存在（复用脉拍门控：deep_valley 读同一序列）；
    - 子进程=deep_valley_revalidate --month 当月 --apply（幂等 upsert phase_monitor c9:<month>，
      深谷日样本 + 3 日反弹 + 池代理随交易日自愈补全）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（C9 候选证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    month = today[:7]
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.deep_valley_revalidate",
             "--month", month, "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "deep_valley_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "deep_valley_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    summary: dict[str, Any] = {}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["phase_monitor"].find_one({"_id": f"c9:{month}"}, {"summary": 1, "updatedAt": 1})
        updated = str((doc or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        summary = (doc or {}).get("summary") or {}
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "month": month, "summary": summary, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor c9:<month> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    return result


def run_mongodb_snapshot_archive_once(*, dry_run: bool = False) -> dict[str, Any]:
    """盘后快照日归档到 R2（mongodb 后端，2026-09-28）。

    按 ``archive_auto_snapshot_types`` 逐类型归档**最近已收盘交易日**（严格早于
    今日）：当日 15:30 任务触发时 daily:15:30 槽可能仍在采集，归档当日会把
    不完整帧固化进 manifest 并被幂等去重永久跳过；归档 T-1 无此竞态。
    每类型独立成败（fail-visible）：单类型失败不阻断其它类型，整体 ok 汇总。
    Mongo 保留不动（归档只进 R2，见 ArchiveService.backup_mongodb_snapshot_day_to_object）。
    """
    from backend.data.archive.service import ArchiveService

    settings = get_settings()
    snapshot_types = [item.strip() for item in settings.archive_auto_snapshot_types.split(",") if item.strip()]
    today = datetime.now(_TZ).strftime("%Y-%m-%d")
    db = repository_factory.get_runtime_mongodb_database()
    per_type: dict[str, Any] = {}
    ok = True
    service = ArchiveService(db)
    for snapshot_type in snapshot_types:
        try:
            latest_date = db["snapshot_frames"].find_one(
                {"datasetId": settings.archive_auto_dataset_id, "type": snapshot_type, "tradingDate": {"$lt": today}},
                sort=[("tradingDate", -1)],
                projection={"tradingDate": 1, "_id": 0},
            )
            trading_date = str((latest_date or {}).get("tradingDate") or "")
            if not trading_date:
                per_type[snapshot_type] = {"ok": True, "skipped": True, "reason": "no_snapshot_frames"}
                continue
            result = service.backup_mongodb_snapshot_day_to_object(
                db,
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                dry_run=dry_run,
            )
            per_type[snapshot_type] = {**result, "tradingDate": trading_date}
            skipped_reason = str(result.get("reason") or "")
            if not result.get("ok") and skipped_reason not in ("already_archived",):
                ok = False
        except Exception as exc:
            per_type[snapshot_type] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            ok = False
    return {
        "ok": ok,
        "dryRun": dry_run,
        "datasetId": settings.archive_auto_dataset_id,
        "snapshotTypes": per_type,
        "archivedBefore": today,
    }


def run_after_market_once(
    *,
    archive_limit: int | None = None,
    backup_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, Any] = {}

    settings = get_settings()
    if settings.storage_backend == "mongodb":
        snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
        try:
            hotlist_result = run_hotlist_sentiment_for_latest_day(
                repository_factory.get_runtime_mongodb_database(),
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                dry_run=dry_run,
            )
        except Exception as exc:
            hotlist_result = {
                "ok": False,
                "error": {
                    "code": "hotlist_sentiment_after_market_failed",
                    "message": str(exc),
                },
                "datasetId": settings.archive_auto_dataset_id,
                "snapshotType": snapshot_type,
            }
        # 备份链独立于 hotlistSentiment 结果：hotlist 失败也继续备份（快照数据可能已入库）
        backup_result = run_mongodb_backup_once(dry_run=dry_run)
        # R2 快照归档链独立于备份链：备份失败也尝试归档（两条链互不覆盖，各自 fail-visible）
        archive_result = run_mongodb_snapshot_archive_once(dry_run=dry_run)
        hotlist_ok = bool(hotlist_result.get("ok"))
        backup_ok = bool(backup_result.get("ok"))
        archive_ok = bool(archive_result.get("ok"))
        stopped_at = None
        if not hotlist_ok:
            stopped_at = "hotlistSentiment"
        elif not backup_ok:
            stopped_at = "mongodbBackup"
        elif not archive_ok:
            stopped_at = "snapshotArchiveR2"
        # 盘面脉拍（M3 advisory 步）：EOD 刷新后数据齐，子进程隔离跑当月至今相位快照；
        # 失败/跳过只记结果不翻转整体 ok，也不参与 stopped_at（研究证据链，非生产数据链）
        today = datetime.now(_TZ).strftime("%Y-%m-%d")
        pulse_result = _run_phase_pulse_step(today, dry_run=dry_run)
        jiuyan_label_result = _run_jiuyan_label_step(today, dry_run=dry_run)
        phase_band_result = _run_phase_band_step(today, dry_run=dry_run)
        deep_valley_result = _run_deep_valley_step(today, dry_run=dry_run)
        return _result(
            ok=hotlist_ok and backup_ok and archive_ok,
            started_at=started_at,
            steps=["hotlistSentiment", "mongodbBackup", "snapshotArchiveR2", "phasePulse", "jiuyanLabel", "phaseBand", "deepValley"],
            results={
                "hotlistSentiment": hotlist_result,
                "mongodbBackup": backup_result,
                "snapshotArchiveR2": archive_result,
                "phasePulse": pulse_result,
                "jiuyanLabel": jiuyan_label_result,
                "phaseBand": phase_band_result,
                "deepValley": deep_valley_result,
            },
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at=stopped_at,
        )

def run_mongodb_backup_once(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """盘后 MongoDB 备份链：创建（交易日 light / 周五 full）→ verify → prune →（周五）push R2。

    独立于 hotlistSentiment：任一步失败结构化记录并使整体失败（非零退出可见），
    但不回滚其它步骤已完成的事实。
    """
    now = now or datetime.now(_TZ)
    is_friday = now.weekday() == 4
    summary: dict[str, Any] = {"ok": True, "friday": is_friday, "tradingDate": now.date().isoformat()}
    if dry_run:
        return {**summary, "skipped": True, "reason": "dry_run"}
    if not is_trading_day(now.date()):
        return {**summary, "skipped": True, "reason": "non_trading_day"}

    service = get_mongodb_backup_service()
    strategy = "full_dump" if is_friday else "light_dump"
    if not is_friday:
        strategy, catch_up = _maybe_force_full_catch_up(service, now)
        summary["lastFullBackup"] = catch_up
    summary["strategy"] = strategy
    try:
        created = service.create_full_backup() if strategy == "full_dump" else service.create_light_backup()
    except Exception as exc:
        return {**summary, "ok": False, "failedStep": "create", "error": {"code": "backup_create_exception", "message": str(exc)}}
    if not created.get("ok"):
        return {**summary, "ok": False, "failedStep": "create", "error": created.get("error")}
    backup_id = created["backupId"]
    summary["backupId"] = backup_id

    verify = service.verify_backup(backup_id)
    if not verify.get("ok"):
        return {**summary, "ok": False, "failedStep": "verify", "error": verify.get("error")}

    prune = service.prune_local_backups(dry_run=False)
    summary["pruneDeleted"] = len(prune.get("deleted") or [])
    if not prune.get("ok"):
        return {**summary, "ok": False, "failedStep": "prune", "error": prune.get("error")}

    if strategy == "full_dump":
        # 周五全量与断档补跑全量都立即上云（push 失败使整体失败可见）
        try:
            pushed = service.push_backup(backup_id)
        except Exception as exc:
            pushed = {"ok": False, "error": {"code": "backup_push_exception", "message": str(exc)}}
        summary["push"] = {
            "ok": bool(pushed.get("ok")),
            "fileCount": len(pushed.get("files") or []),
            **({} if pushed.get("ok") else {"error": pushed.get("error")}),
        }
        if not pushed.get("ok"):
            return {**summary, "ok": False, "failedStep": "push"}
    return summary


def _result(
    *,
    ok: bool,
    started_at: str,
    steps: list[str],
    results: dict[str, Any],
    archive_limit: int | None,
    backup_limit: int | None,
    dry_run: bool,
    stopped_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "dryRun": dry_run,
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "archiveLimit": archive_limit,
        "backupLimit": backup_limit,
        "steps": steps,
        "results": results,
    }
    if stopped_at:
        payload["stoppedAt"] = stopped_at
    return payload


def _maybe_force_full_catch_up(service: Any, now: datetime) -> tuple[str, dict[str, Any]]:
    """非周五交易日检查最近全量：距上次成功 full 超过 8 天则强制补 full。

    背景：周五停机错过全量时，周末补跑因非交易日跳过、当周只剩 light，
    R2 侧全量断档一整周。远端 R2 是唯一完整视图（本地 light 保留期短于
    全量周间隔）；未配置 R2 时无法可靠判断，保持 light 并结构化记录原因。
    返回 (strategy, lastFullBackup 摘要)。
    """
    info: dict[str, Any] | None = None
    try:
        info = service.latest_full_backup_info()
    except Exception as exc:
        return "light_dump", {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if info and info.get("createdAt"):
        created = info["createdAt"]
        age_days = (now.astimezone(timezone.utc) - created).total_seconds() / 86400.0
        detail = {
            "ok": True,
            "backupId": info.get("backupId"),
            "source": info.get("source"),
            "createdAt": created.isoformat(),
            "ageDays": round(age_days, 2),
        }
        if age_days >= 8:
            detail["fullCatchUp"] = {"reason": "last_full_older_than_8_days"}
            return "full_dump", detail
        return "light_dump", detail
    if getattr(service, "object_store", None) is not None:
        # 配置了 R2 却查不到任何全量：尚未有上云全量，补一次
        return "full_dump", {"ok": True, "fullCatchUp": {"reason": "no_full_backup_found"}}
    return "light_dump", {"ok": True, "skipped": True, "reason": "full_history_unavailable_without_object_store"}


def _first_snapshot_type(raw: str) -> str:
    items = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return items[0] if items else "half_hour"