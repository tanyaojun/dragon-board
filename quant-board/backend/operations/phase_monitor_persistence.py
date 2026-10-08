# -*- coding: utf-8 -*-
"""phase_monitor Mongo 落库（前端可见化数据源，设计 ranktrend-phase-frontend-design.md §3）。

单一集合 phase_monitor 多类文档（各 persist_* 函数负责，幂等 upsert）：
kind=northstar（基线读数，_id=northstar:<key>）/ kind=monthly（逐月监督，_id=monthly:<YYYY-MM>）/
kind=pulse（盘面脉拍，_id=pulse:<YYYY-MM>）/ kind=divergence（哨兵分歧，_id=divergence:<YYYY-MM>）/
kind=daily_line（日度情绪一句话，_id=line:<YYYY-MM-DD>，jev-daily-line-design.md）。
落库失败不中断研究链（调用方自身产物仍是即时交付，fail-visible 打印警告）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def persist_northstar(report: dict[str, Any], *, key: str) -> str | None:
    """北极星基线落库（_id=northstar:<key>，如 northstar:gen7-sentiment2b）。失败返回 None。"""
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"northstar:{key}", "kind": "northstar", "key": key,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 研究链不因落库失败中断
        print(f"[phase-monitor-persist] northstar 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None


def persist_monthly(report: dict[str, Any]) -> str | None:
    """月度监督落库（_id=monthly:<YYYY-MM>，report.meta.month 必填）。失败返回 None。"""
    month = str((report.get("meta") or {}).get("month") or "")
    if not month:
        print("[phase-monitor-persist] monthly 落库跳过：report.meta.month 缺失", file=sys.stderr)
        return None
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"monthly:{month}", "kind": "monthly", "month": month,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 研究链不因落库失败中断
        print(f"[phase-monitor-persist] monthly 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None


def persist_pulse(report: dict[str, Any]) -> str | None:
    """盘面脉拍落库（_id=pulse:<YYYY-MM>，report.month 必填，重跑覆盖=最新脉拍）。失败返回 None。"""
    month = str(report.get("month") or "")
    if not month:
        print("[phase-monitor-persist] pulse 落库跳过：report.month 缺失", file=sys.stderr)
        return None
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"pulse:{month}", "kind": "pulse", "month": month,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 研究链不因落库失败中断
        print(f"[phase-monitor-persist] pulse 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None


def persist_daily_line(report: dict[str, Any]) -> str | None:
    """日度情绪一句话落库（_id=line:<YYYY-MM-DD>，report.date 必填，重跑覆盖=当日最新）。失败返回 None。

    消费方：GET /api/phase-monitor/board → dailyLine；前端热榜情绪 hero 区。
    设计/预登记：jev-daily-line-design.md（2026-10-08）。
    """
    date = str(report.get("date") or "")
    if not date:
        print("[phase-monitor-persist] daily_line 落库跳过：report.date 缺失", file=sys.stderr)
        return None
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"line:{date}", "kind": "daily_line", "date": date,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 证据链不因落库失败中断
        print(f"[phase-monitor-persist] daily_line 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None


def persist_calib_drift(report: dict[str, Any]) -> str | None:
    """校准漂移监控落库（_id=calib_drift:<YYYY-MM>，report.month 必填，月度幂等 upsert）。失败返回 None。

    消费方：月度重校准例检/告警排查（emotion-score-calib-monitor-design.md）；advisory 证据链。
    """
    month = str(report.get("month") or "")
    if not month:
        print("[phase-monitor-persist] calib_drift 落库跳过：report.month 缺失", file=sys.stderr)
        return None
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"calib_drift:{month}", "kind": "calib_drift", "month": month,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 证据链不因落库失败中断
        print(f"[phase-monitor-persist] calib_drift 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None


def persist_divergence(report: dict[str, Any]) -> str | None:
    """分歧哨兵落库（_id=divergence:<YYYY-MM>，report.month 必填）。失败返回 None。"""
    month = str(report.get("month") or "")
    if not month:
        print("[phase-monitor-persist] divergence 落库跳过：report.month 缺失", file=sys.stderr)
        return None
    try:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        doc = {"_id": f"divergence:{month}", "kind": "divergence", "month": month,
               "report": report, "updatedAt": _now()}
        db["phase_monitor"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return doc["_id"]
    except Exception as exc:  # noqa: BLE001 — 研究链不因落库失败中断
        print(f"[phase-monitor-persist] divergence 落库失败（不阻断）: {exc}", file=sys.stderr)
        return None
