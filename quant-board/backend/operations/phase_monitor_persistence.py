# -*- coding: utf-8 -*-
"""phase_monitor Mongo 落库（前端可见化数据源，设计 ranktrend-phase-frontend-design.md §3）。

单一集合 phase_monitor 两类文档：kind=northstar（基线读数，_id=northstar:<key>）/
kind=monthly（逐月监督，_id=monthly:<YYYY-MM>）。幂等 upsert——重跑 CLI 即迁移/刷新。
落库失败不中断研究链（本地 JSON 仍是即时产物，fail-visible 打印警告）。
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
