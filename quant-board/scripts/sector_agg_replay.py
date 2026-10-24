# -*- coding: utf-8 -*-
"""V2b 翻红历史回放研究（一次性研究脚本，不进生产链、不挂盘后链）。

预登记：docs/hotlist-jev/sector-nodes-v2-aggregate-preregistration.md §五。
问题：弱转强（wzs）日的板块活跃股，盘中翻红率是否有可识别的时点特征
（如「10:00 前翻红率过半」）？——为 V2c 实时翻红采集立项提供证据。

样本：
- wzs 组：节点文档 rows[].node == "wzs" 的板块-日；
- 对照组：prevNode ∈ {weakening, collapse} 且 node != "wzs" 的板块-日
  （昨日弱势但次日未转强——wzs 判据的天然反例群）。

方法：每样本取 aggN5 成员集（重算窗口池，与落库同口径），拉 5 分钟棒
（`_intraday_bars`，TDX 线上、800 根≈16 交易日——更早样本如实剔除并披露），
回放各时点翻红率（时点收盘价 vs 当日昨收）。输出分组 × 时点的翻红率表。

用法：PYTHONPATH=. ./.venv/Scripts/python.exe scripts/sector_agg_replay.py [--days 60]
零 jev token；TDX 行情为免费公开接口（如实披露：成员去重后约数百次 client.bars）。
"""
from __future__ import annotations

import argparse
import statistics
from collections import defaultdict

# tdxpy 握手身份补丁（同 python-bridge/main.py 2026-09-23）：跳过 SetupCmd3 旧客户端
# 标识，官方主站不再软拒绝（4 字节空响应）——分钟棒只走线上（无本地 minline 读取），
# 不打补丁 _tdx_daily_client 全节点 index_bars=0（2026-10-24 回放首跑实测）。
import os
if os.getenv("TDX_KEEP_TDXPY_SETUP3", "") not in ("1", "true", "True"):
    def _setup_without_legacy_identity(self):
        from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2
        SetupCmd1(self.client).call_api()
        SetupCmd2(self.client).call_api()
    from tdxpy.hq import TdxHq_API
    TdxHq_API.setup = _setup_without_legacy_identity

from backend.analysis.hotlist.sector_nodes import WEAK_NODES
from backend.operations.jev_label_jiuyan import _daily_bars, _intraday_bars
from backend.operations.sector_nodes import (
    DEFAULT_DATASET_ID,
    _window_pool_of,
    _POOL_CACHE,
)
from backend.data.repositories.repository_factory import get_runtime_mongodb_database

COLLECTION = "hotlist_jev_sector_nodes"
TIMES = ("09:35", "10:00", "10:30", "11:00", "13:30", "14:00", "14:30", "15:00")


def _prev_close(code: str, date: str) -> float | None:
    bars = [b for b in _daily_bars(code) if b["date"] < date]
    return float(bars[-1]["close"]) if bars else None


def _curve_at(codes: set[str], date: str) -> dict[str, list[float]]:
    """成员在各时点的翻红率序列（逐成员 1=红 0=不红；缺棒/无昨收剔除）。"""
    per_time: dict[str, list[float]] = defaultdict(list)
    skipped = 0
    for code in sorted(codes):
        pc = _prev_close(code, date)
        minute_bars = [b for b in _intraday_bars(code) if b["date"] == date]
        if not minute_bars or not pc:
            skipped += 1
            continue
        for t in TIMES:
            upto = [b for b in minute_bars if b["hm"] <= t]
            if not upto:
                continue
            per_time[t].append(1.0 if upto[-1]["close"] > pc else 0.0)
    return {**{t: per_time.get(t, []) for t in TIMES}, "_skipped": [skipped]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60, help="只看最近 N 个交易日文档（分钟棒 16 日限制之外的样本本就取不到）")
    args = ap.parse_args(argv)

    db = get_runtime_mongodb_database()
    docs = list(db[COLLECTION].find({}, sort=[("tradingDate", -1)], limit=args.days))
    docs.reverse()
    wzs_curves: list[dict[str, list[float]]] = []
    ctrl_curves: list[dict[str, list[float]]] = []
    n_ok_wzs = n_ok_ctrl = 0
    skipped_far = 0
    for doc in docs:
        date = str(doc.get("tradingDate"))
        pools: list[tuple[str, dict]] = []
        # 重算 aggN5 成员集（与落库同口径：今日+最近 5 个池 ok 日）
        from backend.operations.jev_label_jiuyan import trading_dates_before
        candidates = [date] + list(reversed(
            trading_dates_before(db, date, 15, dataset_id=DEFAULT_DATASET_ID)))
        for d in candidates:
            pool = _window_pool_of(db, d, DEFAULT_DATASET_ID)
            if pool is not None:
                pools.append((d, pool))
            if len(pools) >= 5:
                break
        for r in doc.get("rows") or []:
            node, board = r.get("node"), str(r.get("board") or "")
            prev_node = r.get("prevNode")
            is_wzs = node == "wzs"
            is_ctrl = prev_node in WEAK_NODES and node not in ("wzs", "unknown")
            if not (is_wzs or is_ctrl):
                continue
            codes: set[str] = set()
            for _d, pool in pools[-5:]:
                codes |= pool.get(board, set())
            if not codes:
                continue
            curve = _curve_at(codes, date)
            if not any(curve[t] for t in TIMES):
                skipped_far += 1     # 分钟棒窗口外（>16 交易日），如实计数
                continue
            (wzs_curves if is_wzs else ctrl_curves).append(curve)
            if is_wzs:
                n_ok_wzs += 1
            else:
                n_ok_ctrl += 1
    _POOL_CACHE.clear()

    print(f"样本：wzs {n_ok_wzs} 组 / 对照 {n_ok_ctrl} 组（分钟棒窗口外剔除 {skipped_far} 组）")
    print(f"{'时点':>6} | {'wzs 翻红率':>12} | {'对照 翻红率':>12} | {'差':>8}")
    for t in TIMES:
        row = []
        for curves in (wzs_curves, ctrl_curves):
            vals = [v for c in curves for v in c[t]]
            row.append((statistics.mean(vals), len(vals)) if vals else (None, 0))
        w, c = row
        ws = f"{w[0]:.0%} (n={w[1]})" if w[0] is not None else "—"
        cs = f"{c[0]:.0%} (n={c[1]})" if c[0] is not None else "—"
        diff = f"{w[0] - c[0]:+.0%}" if (w[0] is not None and c[0] is not None) else "—"
        print(f"{t:>6} | {ws:>12} | {cs:>12} | {diff:>8}")
    # 各 wzs 样本明细（早盘时点读数，供人工抽验）
    print("\n— wzs 明细（前 12 组，10:00 翻红率）:")
    for c in wzs_curves[:12]:
        v10 = c["10:00"]
        print(f"  10:00 翻红 {sum(v10)}/{len(v10)}"
              + ("" if not v10 else f" = {sum(v10) / len(v10):.0%}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
