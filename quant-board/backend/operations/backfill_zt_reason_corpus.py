# -*- coding: utf-8 -*-
"""2203 涨停原因语料 HTTP 历史档案链回填（GetDayZhangTing，按股单发 ≥2s 全局限频）。

背景（2026-11-09 收盘复盘）：socket 2203 只覆盖当日盘中实时态（订阅面=涨停池成员），
当日 collector 会话抖动（sessions 681 / errors 1563，WinError 10054 重连循环，平均
会话 ~23s 远低于健康区间 75-160s）导致 2203/2013 全天零到流，jev 投喂原料缺口。
回填走 docs/kpl-socket/README.md §11.7 已固化的 HTTP 档案链：

- POST apphis GetDayZhangTing（kpl_zt_reason_history.fetch_stock_zt_reason_raw）：
  无 Date 参数，返回该股最近涨停日条目（List 自带 Date），按池快照交易日过滤匹配；
- Reason 全文与 socket 2203 zt 字段同源（301697 双源一致实测），映射 zt；
  GNSM/Boom_ZS/SCLT/ZSCode 原文经 _REASON_FIELDS 透传（原料在、可追溯、不改写）；
- 逐条 item.source='http_GetDayZhangTing'，doc 级 reason_source 同值；
- 无该日条目（matched_date≠交易日）不伪装，记 skipped（fail-visible）。

纪律：真实 HTTP 调用仅限运维补拉路径（kpl_zt_reason_history._pytest_guard 兜底 +
_post_form 全局 ≥2s 单发间隔）；pytest 注入 fetcher 全 mock（红线 7）；默认 dry-run
（照常拉取+导出原文，不写库），--apply 才落库；落库走 archive_reason_corpus 既有
合同（stock_id 并集、字段随新帧刷新、跨日残留 skip），重跑幂等安全。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.backfill_zt_reason_corpus \
      --date 2026-11-09                # dry-run：拉取+导出原文+打印报告，不写库
  ... --apply                          # 实际落库
  ... --limit 5                        # 试运行限发数
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.services.kpl_daban_archiver import archive_reason_corpus
from backend.services.kpl_zt_reason_history import (
    fetch_stock_zt_reason_raw,
    fetch_stock_zt_reason_realtime,
    parse_zt_reason_history,
)

SOURCE_RT = "http_GetKLineZhangTing"      # 实时端点（当日条目即时同步，2026-11-09 实测）
SOURCE_HIST = "http_GetDayZhangTing"      # 历史档案链（当日条目 T+1 滞后，回看用）
DEFAULT_RAW_OUT_DIR = Path("data/backups")


def pick_pool_members(db: Any, date: str) -> Dict[str, Any]:
    """日档涨停池（pool 通道）成员 stock_id 列表（2203 订阅面=涨停池成员，同口径）。

    fail-visible：无日档 / 无成员结构化返回，不猜。
    """
    row = db["kpl_daban_pool"].find_one({"_id": date}) or {}
    items = row.get("items") or []
    sids = [str(m.get("stock_id") or "").strip() for m in items]
    sids = [s for s in sids if s]
    if not sids:
        return {"ok": False, "reason": "no_pool_members", "date": date, "members": []}
    return {"ok": True, "date": date, "members": sids}


def build_reason_snapshot(date: str, results: Dict[str, Dict[str, Any]], *,
                          fetch_ts: float, source: str = SOURCE_RT) -> Dict[str, Any]:
    """回填解析结果 → archive_reason_corpus 快照载荷（2203 合同 shape，逐条带来源）。

    results: {stock_id: parse_zt_reason_history 输出}；仅收 matched 有当日条目的股，
    无匹配/空的由调用方记 skipped，不进载荷（不伪装）。
    """
    reasons: Dict[str, Dict[str, Any]] = {}
    for sid, out in results.items():
        items = out.get("items") or []
        if not out.get("ok") or not items:
            continue
        it = items[0]   # 按 Date 过滤后该日条目（parse 已过滤，取首条原文）
        reasons[sid] = {
            "zt": it.get("reason"),
            "gns": it.get("gns"),
            "boom_zs": it.get("boom_zs"),
            "sclt": it.get("sclt"),
            "zs_codes": it.get("zs_codes"),
            "matched_date": it.get("date"),
            "source": source,
            "ts": fetch_ts,
        }
    return {"ok": True, "date": date, "reasons": reasons, "count": len(reasons)}


def run_backfill(db: Any, date: str, *, fetcher: Callable[[str], Dict[str, Any]],
                 limit: Optional[int] = None, apply: bool = False,
                 now: Optional[Any] = None,
                 source: str = SOURCE_RT) -> Dict[str, Any]:
    """按股回填单日涨停原因语料：拉取 → 过滤匹配 → archive_reason_corpus 落库。

    fetcher 注入（生产=fetch_stock_zt_reason_raw；pytest=mock，红线 7）。
    apply=False 不写库（dry-run 只出报告）；matched/skipped/failures 全量结构化透出。
    """
    picked = pick_pool_members(db, date)
    if not picked["ok"]:
        return {**picked, "apply": apply, "fetched_n": 0, "matched_n": 0}
    members: List[str] = picked["members"]
    if limit:
        members = members[:max(1, int(limit))]
    fetch_ts = time.time()
    results: Dict[str, Dict[str, Any]] = {}
    skipped: Dict[str, str] = {}
    failures: Dict[str, str] = {}
    raw: Dict[str, Any] = {}
    for sid in members:
        try:
            raw_data = fetcher(sid)
            raw[sid] = raw_data
        except Exception as exc:   # 网络/errcode 异常逐股隔离（fail-visible 不中断批次）
            failures[sid] = str(getattr(exc, "error", "") or exc)[:160]
            continue
        out = parse_zt_reason_history(raw_data, date)
        results[sid] = out
        if not (out.get("items") or []):
            skipped[sid] = str(out.get("note")
                               or f"无 {date} 条目（matched_date={out.get('matched_date') or '无'}）")
    report: Dict[str, Any] = {
        "date": date, "apply": apply,
        "members_n": len(members), "fetched_n": len(raw),
        "matched_n": sum(1 for o in results.values() if o.get("items")),
        "skipped": skipped, "failures": failures,
        "_raw": raw,   # 上游原文（main 导出用；不进打印/落库载荷）
    }
    # ok 语义（评审 MINOR）：ok=本轮有匹配产出（matched_n>0）；全批失败/无条目时
    # ok=False，调用方/调度可用 rc 判定「本轮无产出」，不伪装成功
    report["ok"] = report["matched_n"] > 0
    snapshot = build_reason_snapshot(date, results, fetch_ts=fetch_ts, source=source)
    if apply and snapshot["reasons"]:
        arch = archive_reason_corpus(db, snapshot, now=now, source=source)
        report["archive"] = arch
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="2203 涨停原因语料 HTTP 历史档案链回填（GetDayZhangTing）")
    parser.add_argument("--date", required=False, default=None,
                        help="池快照交易日 YYYY-MM-DD（默认=库内最近含成员日档）")
    parser.add_argument("--limit", type=int, default=None, help="限发股数（试运行）")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run 不落库）")
    parser.add_argument("--raw-out", default=None,
                        help="上游原文 JSON 导出路径（默认 data/backups/kpl-zt-reason-backfill-<date>/raw_responses.json）")
    parser.add_argument("--mode", choices=("rt", "hist"), default="rt",
                        help="rt=GetKLineZhangTing 实时端点（默认，当日条目即时同步）；"
                             "hist=GetDayZhangTing 历史档案链（当日 T+1 滞后，回看用）")
    args = parser.parse_args(argv)

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.kpl_daban_archiver import latest_archived_pool_day

    db = get_runtime_mongodb_database()
    date = args.date or latest_archived_pool_day(db)
    if not date:
        print("no archived pool day；用 --date 显式指定")
        return 2
    source = SOURCE_RT if args.mode == "rt" else SOURCE_HIST
    fetcher = fetch_stock_zt_reason_realtime if args.mode == "rt" else fetch_stock_zt_reason_raw
    print(f"backfill zt-reason corpus date={date} mode={args.mode} source={source} "
          f"limit={args.limit} apply={args.apply}")
    report = run_backfill(db, date, fetcher=fetcher,
                          limit=args.limit, apply=args.apply, source=source)
    print(json.dumps({k: v for k, v in report.items() if k not in ("skipped", "_raw")},
                     ensure_ascii=False, indent=2, default=str))
    if report.get("skipped"):
        print(f"skipped（无该日条目，不伪装）: {len(report['skipped'])}")
        for sid, note in list(report["skipped"].items())[:10]:
            print(f"  {sid}: {note}")
        if len(report["skipped"]) > 10:
            print(f"  ... 共 {len(report['skipped'])}")
    # 原文导出（原料全保留，含 GNSM/Boom_ZS/SCLT 未透传前全文）
    if report.get("fetched_n"):
        out_path = (Path(args.raw_out) if args.raw_out
                    else DEFAULT_RAW_OUT_DIR / f"kpl-zt-reason-backfill-{date}")
        out_path.mkdir(parents=True, exist_ok=True)
        raw_file = out_path / "raw_responses.json"
        raw_file.write_text(json.dumps(report.get("_raw") or {}, ensure_ascii=False),
                            encoding="utf-8")
        print(f"raw responses exported: {raw_file}")
    # rc 语义（评审 MINOR）：ok=有匹配产出 → 0；无产出（全失败/全无当日条目/无池成员）→ 1，
    # 调度接入方可用 rc 判定本轮无产出，不伪装成功
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
