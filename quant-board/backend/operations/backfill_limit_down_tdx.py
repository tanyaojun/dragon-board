# -*- coding: utf-8 -*-
"""全市场跌停参考集合·本地日线口径回填（F7，2026-10-17）。

背景：东财跌停池只有近 30 自然日窗口，09-16 之前 84 个交易日无全市场口径（叙事回退
250 只采集池，系统性低估；诊断 §9）。本工具用本地通达信日线离线重算并写入参考集合
`market_daily_limit_down`（source=tdx_local_bars），使早期日与近期日同为「全市场口径」。

用法（Git Bash，dry-run 默认）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.backfill_limit_down_tdx \
      --start 2026-01-01 --end 2026-09-15            # 先看表
  ./.venv/Scripts/python.exe -m backend.operations.backfill_limit_down_tdx \
      --start 2026-01-01 --end 2026-09-15 --apply    # 确认后写库

规则（预登记 jev-relay-ie-fix-preregistration.md F7）：
- **绝不覆盖权威源**：已有 source ∈ {em_pool, market_quotes_snapshot} 的日期一律跳过；
- 日轴 = `snapshot_frames` 交易日在 [start, end]（与叙事同轴，不另造日历）；
- 该日全市场无可用棒、或当日有棒股数远低于峰值（读取窗边缘）→ 披露缺口，**绝不写数**；
- **0 家跌停**（覆盖足但无股跌停）是**真读数**，照写（不得当缺口）。
- 顺带对账：已有 em_pool 的日期打印 TDX 与 EM 偏差（精度留档，供 §9 复核）。
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.operations import market_dieban_pool as mdp
from backend.operations import market_dieban_tdx as tdx


def _em_compare(db: Any, counts: dict[str, int], dates: list[str]) -> list[tuple[str, int, int]]:
    """TDX 与 EM 双源日对账（不写库）：[(date, tdx, em)]。"""
    em = mdp.reference_counts(db, dates, mdp.SOURCE_EM)
    return [(d, counts[d], em[d]) for d in sorted(em) if d in counts]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    ap.add_argument("--root", default=None, help=f"本地通达信目录（默认探测，或环境变量 {tdx.ENV_ROOT}）")
    ap.add_argument("--take", type=int, default=tdx.DEFAULT_TAKE, help="每股读取的日线根数（尾部）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    args = ap.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find(
        {"datasetId": args.dataset_id}, {"tradingDate": 1})
        if r.get("tradingDate") and args.start <= str(r["tradingDate"]) <= args.end})
    col = db[mdp.COLLECTION]
    have = {str(d["_id"]): str(d.get("source") or "")
            for d in col.find({"_id": {"$in": dates}}, {"source": 1})}
    authoritative = {d for d, s in have.items() if s in (mdp.SOURCE_EM, mdp.SOURCE_SNAPSHOT)}
    todo = [d for d in dates if d not in authoritative]
    print(f"== 本地日线跌停回填 {args.start}~{args.end}：日轴 {len(dates)} 日，"
          f"权威源已覆盖 {len(authoritative)} 日（跳过），待处理 {len(todo)} 日 ==")

    root, last_bar = tdx.resolve_root([args.root] if args.root else None)
    print(f"本地通达信目录：{root or '未找到'}（末棒 {last_bar or '?'}）；"
          f"环境变量 {tdx.ENV_ROOT}={os.environ.get(tdx.ENV_ROOT) or '未设置'}")
    if not root:
        raise SystemExit("未找到可用本地日线目录 → 不回填（fail-visible，不伪 0）")
    if last_bar and last_bar < args.end:
        print(f"[警告] 目录末棒 {last_bar} 早于 --end {args.end}：该段无棒日将列缺口")

    universe = tdx.universe_from_db(db)
    counts, meta = tdx.scan_counts(dates, root=root, universe=universe, take=args.take)
    print(f"扫描：宇宙 {len(universe)} 只（目录内命中 {meta['files']}，目录外 {meta['skipped']}，"
          f"宇宙内缺日线 {meta['missing']}）；有跌停读数 {len(counts)} 日")

    for d in sorted(counts):
        old = have.get(d)
        old_txt = f"{mdp.source_label(old)}({old})" if old else "无"
        n = counts[d]
        # 池内对照（2026-10-18 review P2-2）：原先查 `reference_counts(SOURCE_POOL)`——
        # 但全库**无任何路径写 source=pool_rows 到参考集合**，该列恒为 `-`（死查询）。
        # 采集池口径的真源在 snapshot 聚合（`dieban_count`），直调以得到真实对照数。
        from backend.operations.jev_label_jiuyan import dieban_count
        cur = dieban_count(db, d, args.dataset_id)
        delta = f"{n - cur:+d}" if isinstance(cur, int) else "-"
        print(f"  [回填] {d}: TDX 全市场 {n:>3} 家 | 现状 {old_txt} "
              f"| 池内对照 {cur if cur is not None else '-'}（Δ {delta}）")

    gaps = [d for d in todo if d not in counts]
    if gaps:
        print(f"[缺口] {len(gaps)} 日无可用棒（不写 0）：{' '.join(d for d in gaps[:12])}"
              f"{' …' if len(gaps) > 12 else ''}")

    pairs = _em_compare(db, counts, dates)
    if pairs:
        ds = [t - e for _, t, e in pairs]
        print(f"对账（{len(pairs)} 个 EM 双源日）：TDX−EM 均值 {sum(ds) / len(ds):+.2f}，"
              f"极值 {min(ds):+d}..{max(ds):+d}")
        for d, t, e in pairs:
            print(f"  {d}: TDX {t} vs EM {e}（{t - e:+d}）")

    if not args.apply:
        print("dry-run 未写库；确认后加 --apply（只写权威源未覆盖的日期，绝不覆盖 em_pool）")
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    n_written = 0
    for d in sorted(counts):
        if d in authoritative:
            continue
        col.replace_one({"_id": d}, {"_id": d, "count": counts[d], "source": mdp.SOURCE_TDX,
                                     "fetchedAt": now}, upsert=True)
        n_written += 1
    print(f"[market_daily_limit_down] 已写 {n_written} 日（source={mdp.SOURCE_TDX}，"
          f"root={root}，末棒 {last_bar}，take={args.take}）")


if __name__ == "__main__":
    main()
