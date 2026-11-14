# -*- coding: utf-8 -*-
"""监管风险语料手动补采 CLI（2026-11-15 预登记 theme-leader-regulatory-risk §3）。

与 DabanPoolArchiver regulatory lane 共用同一写路径（archive_regulatory_corpus），
单写者合同=同通道写方仅一个归档函数；日槽自动采集由 archiver 承载，本 CLI 用于
历史回填/运维补采。频控预算同 archiver：kpl_api_calls calls.regulatory 计数 + 日预算上限。

CLI：
  python -m backend.operations.kpl_regulatory_collect [--date YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.kpl_theme_store import COLLECTION_API_CALLS, record_api_calls
from backend.services.kpl_daban_archiver import (
    TZ_SHANGHAI, archive_regulatory_corpus, latest_regulatory_day)
from backend.services.kpl_regulatory_risk import (
    REGULATORY_EXPECTED_CALLS, collect_regulatory)


def _budget() -> int:
    return max(1, int(os.environ.get("KPL_REGULATORY_DAILY_CALL_BUDGET", "10")))


def _used(db, key: str) -> int:
    doc = db[COLLECTION_API_CALLS].find_one({"_id": key}, {"calls": 1}) or {}
    return int((doc.get("calls") or {}).get("regulatory") or 0)


def collect_once(*, db=None, date: str | None = None, dry_run: bool = False) -> dict:
    """拉取 + 落库监管风险五组。返回结构化统计；全源失败=降级不是成功（§4.0）。

    review M2/m1 修：日期格式+历法校验先于发弹；预算门控先于发弹（预留预期发数，
    与 archiver 同款）；dry-run 同样计数（频控观测不失真）但不写库。
    """
    if date is not None:
        try:
            datetime.strptime(str(date), "%Y-%m-%d")
        except (ValueError, TypeError):
            return {"ok": False, "reason": "invalid_date", "date": date}
    if db is None:
        db = get_runtime_mongodb_database()
    budget = _budget()
    # 发弹前预算门控：key=date 或最近监管档日（HQ current 的代理）或当日
    pre_key = str(date or latest_regulatory_day(db)
                  or datetime.now(TZ_SHANGHAI).date().isoformat())
    used = _used(db, pre_key)
    if used + REGULATORY_EXPECTED_CALLS > budget:
        return {"ok": False, "reason": "budget_exhausted", "used": used,
                "budget": budget, "date": pre_key}
    payload = collect_regulatory(date)
    target = str(payload.get("date") or "")
    calls = int(payload.get("calls") or 0)
    # 发弹后按真实 target 复核（pre_key 与 HQ current 不一致的边角）：
    # 超预算则只计数不写库（计数=真实上游负载，观测不失真）
    if target and _used(db, target) + calls > budget:
        for _ in range(calls):
            record_api_calls(db, target, ("regulatory",))
        return {"ok": False, "reason": "budget_exhausted", "used": _used(db, target),
                "budget": budget, "date": target, "calls": calls}
    if target:
        for _ in range(calls):
            record_api_calls(db, target, ("regulatory",))
    if dry_run:
        return {"ok": True, "dry_run": True, "date": target, "calls": calls,
                "states": payload.get("states"),
                "codes": len(payload.get("by_code") or {}),
                "group_n": {k: (len(v) if isinstance(v, list) else None)
                            for k, v in (payload.get("groups") or {}).items()}}
    if not target:
        return {"ok": False, "reason": "no_date", "calls": calls,
                "states": payload.get("states")}
    result = archive_regulatory_corpus(db, payload)
    return {**result, "calls": calls}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KPL 监管风险语料补采（严重异动/重点监控）")
    ap.add_argument("--date", default=None, help="历史日 YYYY-MM-DD；缺省=当日 HQ current")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计不写库")
    args = ap.parse_args(argv)
    result = collect_once(date=args.date, dry_run=args.dry_run)
    print("REGULATORY_COLLECT_RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
