# -*- coding: utf-8 -*-
"""生产库修复：为 THS 池缺失交易日补 15:00 快照帧 `limitSummary.thsPools`（2026-11 用户批准）。

背景：leader_wzs 回填中 19 个交易日降级「当日 THS 池缺失，封板不可二分」——
- 3 天（2026-07-06/07/09）完全缺 half_hour/15:00 帧 → 插入最小 schema 忠实帧；
- 16 天（2026-07-30..09-23）15:00 帧为旧 schema（只有 poolCounts，无 pools.*.items、无 ok），
  读口 `jev_label_jiuyan._ths_failed_items` 只认 `ok=true 且 pools.failed.items` → 补丁 `$set`。

修复后逐日校验 `theme_leader_baseline.sealed_and_info` 返回非 None（封板集合可考），
供后续 `scripts/backfill_leader_wzs.py --refresh` 重跑。

写库边界：只写 `dragon_board_quant.snapshot_frames`（经 get_runtime_mongodb_database），
只动 `limitSummary.thsPools`（补丁）或新建帧（snapshotId upsert 幂等）；
不碰 dragon_board_test、Redis、jiuyan_action、其它集合与帧字段。

用法：
  python scripts/backfill_ths_pools_2026Q3.py                # 默认 19 个缺失日
  python scripts/backfill_ths_pools_2026Q3.py --dates 2026-07-06,2026-07-07
  python scripts/backfill_ths_pools_2026Q3.py --verify-only  # 只跑 sealed_and_info 校验

限速：LimitUpService(min_request_gap_ms=2000)——每池请求间 ≥2s（硬边界）；
失败重试 ≤2 次（每次重试换新实例，绕过 30s TTL 内 degraded 负缓存）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.market_proxy.limitup import LimitUpService

# 2026-07-06..09-23 leader_wzs 降级「当日 THS 池缺失，封板不可二分」的 19 个交易日
DEFAULT_DATES = [
    "2026-07-06", "2026-07-07", "2026-07-09", "2026-07-30", "2026-07-31",
    "2026-08-05", "2026-08-06", "2026-08-13", "2026-08-14", "2026-08-19",
    "2026-08-21", "2026-08-24", "2026-08-26", "2026-08-27", "2026-09-02",
    "2026-09-03", "2026-09-09", "2026-09-11", "2026-09-23",
]

_REQUEST_GAP_MS = 2000.0     # 硬边界：每请求间 ≥2s
_RETRIES = 2                 # 失败重试 ≤2 次
_INTER_DATE_SLEEP_S = 2.0


def slot_epoch_ms(date: str) -> int:
    """当日 15:00 Asia/Shanghai 的 epoch 毫秒（健康帧 timestamp 同口径，见 2026-10-23 帧）。"""
    dt = datetime.strptime(date, "%Y-%m-%d").replace(
        hour=15, minute=0, second=0, microsecond=0, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(dt.timestamp() * 1000)


def backfill_marker() -> dict:
    """fail-visible 落痕：历史补采，非当时采集。"""
    return {"backfilledAt": datetime.now(timezone.utc).isoformat(),
            "note": "历史补采，非当时采集"}


async def fetch_pools(date8: str) -> dict:
    """带重试取 THS 池（进程内直连 LimitUpService，date 参数支持历史）。"""
    last_exc: Exception | None = None
    for attempt in range(1 + _RETRIES):
        if attempt:
            await asyncio.sleep(_INTER_DATE_SLEEP_S)
        # 每次重试换新实例：degraded 结果也会进 30s TTL 缓存，旧实例会原样重放
        svc = LimitUpService(min_request_gap_ms=_REQUEST_GAP_MS)
        try:
            body = await svc.get_ths_pools(date8)
            if isinstance(body, dict) and body.get("ok") and not body.get("degraded"):
                return body
            last_exc = RuntimeError(
                f"response not ok: degraded={body.get('degraded') if isinstance(body, dict) else None} "
                f"errors={body.get('errors') if isinstance(body, dict) else body}")
        except Exception as exc:  # noqa: BLE001 — 单日异常如实记录，不中断整批
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def validate_pools(body: dict) -> str | None:
    """每日校验：pools 至少含 failed 与 one（THS 历史可能只留部分池）；items 空=合法（当日无炸板）。"""
    pools = body.get("pools") or {}
    for key in ("one", "failed"):
        pool = pools.get(key)
        if not isinstance(pool, dict) or not pool.get("ok"):
            return f"pool '{key}' missing or not ok (have: {sorted(pools)})"
    return None


def _derive_counts(body: dict) -> dict:
    """failedCount/rushingCount/drawdownCount 按对应池 items 数派生（对齐
    snapshot_collector.providers.build_server_limit_summary：缺失时派生，不伪 0）。"""
    pools = body.get("pools") or {}
    return {k: len(((pools.get(k) or {}).get("items")) or [])
            for k in ("failedCount", "rushingCount", "drawdownCount")}


def backfill_date(db, date: str, body: dict) -> tuple[str, str]:
    """写库：帧存在→只 $set limitSummary.thsPools；缺失→插入最小帧（upsert 键 snapshotId）。"""
    patched = dict(body)
    patched.update(_derive_counts(body))
    patched["_backfilled"] = backfill_marker()
    query = {"datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": date, "slotTime": "15:00"}
    existing = db["snapshot_frames"].find_one(
        query, {"snapshotId": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    if existing:
        sid = str(existing["snapshotId"])
        db["snapshot_frames"].update_one(
            {"snapshotId": sid}, {"$set": {"limitSummary.thsPools": patched}})
        return "patch", sid
    sid = f"half_hour:{date}:15:00"
    doc = {
        "datasetId": "dragonboard_live",
        "snapshotId": sid,
        "type": "half_hour",
        "tradingDate": date,
        "slotTime": "15:00",
        "timestamp": slot_epoch_ms(date),
        "limitSummary": {"thsPools": patched},
    }
    db["snapshot_frames"].update_one(
        {"snapshotId": sid}, {"$setOnInsert": doc}, upsert=True)
    return "insert", sid


async def run_backfill(db, dates: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, date in enumerate(dates):
        if i:
            await asyncio.sleep(_INTER_DATE_SLEEP_S)
        rec: dict = {"date": date}
        try:
            body = await fetch_pools(date.replace("-", ""))
            verr = validate_pools(body)
            if verr:
                raise RuntimeError(verr)
            mode, sid = backfill_date(db, date, body)
            rec.update({
                "mode": mode, "snapshotId": sid,
                "pools": {k: len(v.get("items") or []) for k, v in
                          (body.get("pools") or {}).items()},
            })
            print(f"[backfill] {date} {mode} {sid} pools={rec['pools']}", flush=True)
        except Exception as exc:  # noqa: BLE001 — 失败不中断后续日期
            rec["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[backfill] {date} FAILED {rec['error']}", flush=True)
        out.append(rec)
    return out


def verify_sealed(db, dates: list[str]) -> list[dict]:
    """校验 sealed_and_info 非 None（封板集合可考）；不可考日期如实记失败（不造数）。"""
    from backend.operations.theme_leader_baseline import sealed_and_info
    out: list[dict] = []
    for date in dates:
        try:
            sealed, _info, meta = sealed_and_info(db, date)
            if sealed is None:
                rec = {"date": date, "sealed": None,
                       "reason": meta.get("reason") or str(meta)}
                print(f"[verify] {date} UNSEALED-ABLE {rec['reason']}", flush=True)
            else:
                rec = {"date": date, "sealed": len(sealed)}
                print(f"[verify] {date} sealed={len(sealed)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            rec = {"date": date, "sealed": None,
                   "reason": f"{type(exc).__name__}: {exc}"}
            print(f"[verify] {date} FAILED {rec['reason']}", flush=True)
        out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dates", default=None,
                    help="逗号分隔 YYYY-MM-DD；缺省为预登记 19 日")
    ap.add_argument("--verify-only", action="store_true",
                    help="跳过取池写库，只跑 sealed_and_info 校验")
    args = ap.parse_args()
    dates = ([d.strip() for d in args.dates.split(",") if d.strip()]
             if args.dates else DEFAULT_DATES)
    db = get_runtime_mongodb_database()
    print(f"target db: {db.name}, dates: {len(dates)}", flush=True)

    backfilled: list[dict] = []
    if not args.verify_only:
        backfilled = asyncio.run(run_backfill(db, dates))

    verified = verify_sealed(db, dates)
    summary = {"backfilled": backfilled, "verified": verified,
               "verifyOnly": args.verify_only}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    bad = [r for r in verified if r.get("sealed") is None]
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
