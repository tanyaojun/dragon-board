# -*- coding: utf-8 -*-
"""分带表（relay-band）刷新**单一事实源**（2026-10-19）。

分带实测读数产物 `data/backups/relay-band-table.json` 由离线诊断脚本
`scripts/jev_relay_band_diagnostic.py --emit-json <PATH>` 生成（**零模型调用**：只读
Mongo + 本地通达信日线，全窗约 5–9 分钟）。本模块统一三件事，供两个调用方共用：

1. `backend/api/hotlist_jev_routes.py`：页面【分带观察】一键刷新（异步 `Popen` + 轮询）；
2. `backend/operations/schedule.py`：16:00 盘后链 advisory 步（同步 `subprocess.run`）。

统一的内容 = ①产物/日志路径解析（env 可覆盖，默认落 `quant-board/data/backups/`）；
②刷新命令拼装（**写临时文件 → 成功退出才 `os.replace` 原子替换**，刷新期间旧表始终
完整可读）；③产物窗口读取（滞后判定用）。

fail-visible（AGENTS §4.0）：失败保留旧表、撤掉半成品、原样透出 returncode/日志尾部，
**不用 0/空表冒充**；本模块不抛异常给调用方的公开入口都返回结构化结果。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

RELAY_BAND_TABLE_ENV = "QUANT_BOARD_RELAY_BAND_TABLE"
RELAY_BAND_TABLE_DEFAULT = "data/backups/relay-band-table.json"
RELAY_BAND_REFRESH_LOG_ENV = "QUANT_BOARD_RELAY_BAND_REFRESH_LOG"
RELAY_BAND_REFRESH_LOG_DEFAULT = "data/backups/relay-band-refresh.log"
RELAY_BAND_SCRIPT_REL = "scripts/jev_relay_band_diagnostic.py"

_BAND_REFRESH_LOG_TAIL_CHARS = 400


def quant_board_root() -> Path:
    """quant-board/ 根（本文件 = backend/services/jev/relay_band.py）。"""
    return Path(__file__).resolve().parents[3]


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else quant_board_root() / path


def relay_band_table_path() -> Path:
    """分带表产物路径（默认 `quant-board/data/backups/relay-band-table.json`）。"""
    return _resolve(os.environ.get(RELAY_BAND_TABLE_ENV) or RELAY_BAND_TABLE_DEFAULT)


def relay_band_refresh_log_path() -> Path:
    """刷新日志路径（子进程 stdout+stderr 全量落盘，失败时供页面看原因）。"""
    return _resolve(os.environ.get(RELAY_BAND_REFRESH_LOG_ENV) or RELAY_BAND_REFRESH_LOG_DEFAULT)


def relay_band_script_path() -> Path:
    return quant_board_root() / RELAY_BAND_SCRIPT_REL


def tmp_artifact_path(target: Path, token: str) -> Path:
    """临时产物路径（token 用 pid，防并发复用同一临时文件）。"""
    return target.with_name(target.name + f".tmp{token}")


def smoke_artifact_path(target: Path, days: int) -> Path:
    """`--days N` 冒烟跑的**独立**产物路径（2026-10-19 评审 F5）。

    原因：`--days N` 只截断末尾 N 个判定日，但产物 `window.end` 仍是全量最后一个判定日——
    若冒烟结果落到正式产物路径，页面会显示「只有 N 天」的表，而盘后链门控会认为已覆盖最新
    判定日而**永久跳过**全窗重建。冒烟产物一律另存一份，不污染正式读数。
    """
    return target.with_name(f"{target.stem}-days{days}{target.suffix}")


def band_refresh_command(tmp: Path, days: int = 0) -> list[str]:
    """诊断脚本命令行（days>0 只取最近 N 个判定日，冒烟用）。"""
    args = [sys.executable, str(relay_band_script_path()), "--emit-json", str(tmp)]
    if days:
        args += ["--days", str(days)]
    return args


def read_artifact_window_end(path: Path | None = None) -> str | None:
    """读产物 `window.end`（缺失/损坏/非字符串 → None；滞后判定与门控用，不抛）。"""
    target = path or relay_band_table_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    window = payload.get("window") if isinstance(payload, dict) else None
    end = window.get("end") if isinstance(window, dict) else None
    return str(end) if end else None


def replace_artifact(tmp: Path, target: Path) -> dict[str, Any]:
    """成功退出后原子替换正式产物（失败返回结构化 error，旧表不动）。"""
    try:
        os.replace(tmp, target)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 — 交由调用方上报
        return {"ok": False, "error": f"artifact_replace_failed: {exc}"}


def discard_tmp(tmp: Path) -> None:
    """撤掉半成品临时文件（失败路径；不得把半成品当结果留下）。"""
    try:
        if tmp.exists():
            os.remove(tmp)
    except Exception:  # noqa: BLE001 — 清理失败不影响结果上报
        pass


def _log_tail(log: Path) -> str:
    try:
        return log.read_text(encoding="utf-8", errors="replace")[-_BAND_REFRESH_LOG_TAIL_CHARS:]
    except Exception:  # noqa: BLE001
        return ""


def run_band_refresh_sync(*, days: int = 0, timeout: int = 900) -> dict[str, Any]:
    """同步重算分带表（16:00 盘后链 advisory 步用）。

    返回结构化结果（不抛）：`{ok, days, returncode, error, durationSec, logPath,
    stdoutTail, artifactPath, artifactMtime?, windowEnd?}`。失败保留旧表、撤掉半成品。
    """
    started = datetime.now()
    # days>0 是冒烟跑（截断窗口），产物另存，绝不覆盖正式读数（评审 F5）
    target = smoke_artifact_path(relay_band_table_path(), days) if days else relay_band_table_path()
    log = relay_band_refresh_log_path()
    tmp = tmp_artifact_path(target, str(os.getpid()))
    script = relay_band_script_path()
    if not script.exists():
        return {"ok": False, "error": f"script_missing: {script}", "artifactPath": str(target)}
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"log_dir_failed: {exc}", "artifactPath": str(target)}

    def _elapsed() -> float:
        return round((datetime.now() - started).total_seconds(), 1)

    # 日志 open/close 也包在 try 内：本函数对调用方承诺「不抛结构化结果」（advisory 步
    # 在盘后链上是裸调用，抛出去会中断整条链）。
    try:
        log_fh = open(log, "w", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "days": days, "error": f"log_open_failed: {exc}",
                "logPath": str(log), "artifactPath": str(target), "durationSec": _elapsed()}
    try:
        with log_fh as fh:
            proc = subprocess.run(  # noqa: S603 — 固定脚本 + 固定参数
                band_refresh_command(tmp, days), cwd=str(quant_board_root()),
                stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
    except subprocess.TimeoutExpired:
        discard_tmp(tmp)
        return {"ok": False, "days": days, "error": f"band_refresh_timeout: {timeout}s",
                "logPath": str(log), "artifactPath": str(target), "durationSec": _elapsed()}
    except Exception as exc:  # noqa: BLE001 — 起进程/写日志失败也要结构化（advisory 不翻转整体）
        discard_tmp(tmp)
        return {"ok": False, "days": days, "error": f"spawn_failed: {exc}",
                "logPath": str(log), "artifactPath": str(target), "durationSec": _elapsed()}

    base: dict[str, Any] = {"days": days, "returncode": proc.returncode, "logPath": str(log),
                            "artifactPath": str(target), "durationSec": _elapsed()}
    if proc.returncode != 0:
        discard_tmp(tmp)
        return {**base, "ok": False, "error": f"script_exit_{proc.returncode}",
                "stdoutTail": _log_tail(log)}
    if not tmp.exists():
        return {**base, "ok": False, "error": "artifact_missing", "stdoutTail": _log_tail(log)}
    replaced = replace_artifact(tmp, target)
    if not replaced.get("ok"):
        discard_tmp(tmp)   # 四个分支都要撤半成品（评审 F3：Windows 读口共享冲突会让替换反复失败）
        return {**base, "ok": False, "error": replaced["error"], "stdoutTail": _log_tail(log)}
    result = {**base, "ok": True}
    try:
        result["artifactMtime"] = target.stat().st_mtime
        result["windowEnd"] = read_artifact_window_end(target)
    except Exception:  # noqa: BLE001 — 溯源失败不影响“已成功替换”的事实
        pass
    return result