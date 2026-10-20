# -*- coding: utf-8 -*-
"""15:00 帧 indices 七指数历史回填（指数日线重算，2026-10-21 用户令「情绪指数重放之前，把历史槽位缺失的数据补采全」）。

背景（只读生产库实测）：relay v7 大盘指数行（`jev_relay_index.market_index_line`）消费
15:00 帧 `indices`，但存档缺口面（40 个回放相关交易日）：
  - 4 主指数（sh/hs300/zz500/zz1000）：仅 10-16 起 3 日有 changePct；此前多数日只有 change
    点位（点位口径）；13 日整段缺失（08-18、08-20、08-25、08-28、08-31、09-01、09-04、
    09-07、09-08、09-10、09-14~09-22 间断等）；
  - indexExtra（深证成指/创业板指/科创50）：**全部缺失**（采集层 2026-10-21 起才采集）。
不补采则情绪指数回放语料的大盘行大面积「缺失/该日未采集」，`relay_index` 判据的
「与大盘热度对照锚」「broad_market 归因语料供给」在历史样本上悬空。

指数涨跌幅是客观事实、可从日线重算（AGENTS §4.0：不得因采集链缺口冒充「没有」）。
沿 `backfill_slot_pctchange` 先例：写库带 provenance（`src=tdx_daily_backfill`）、
幂等（已有 changePct 一律跳过，永不覆盖原生帧值）、`--apply` 才写库。

数据源（2026-10-21 对账：七指数 10-19 收盘与本地日线逐点一致）：
  ① 本地 vipdoc lday（sh000001/sh000300/sh000905/sh000852/sh000688/sz399001/sz399006，零外呼）；
  ② 线上 mootdx `index_bars`（本地缺当日棒时兜底；七指数符号实测均正确解析）。
写入语义：
  - 原 entry 只有 change 点位 → 保留 change，补 `changePct` + `src`（relay 显示将升级为
    带「（日线回填）」标注的百分比，点位口径不再需要——pct 来自独立日线源，非点位换算）；
  - 原 entry/indexExtra 缺失 → 创建 `{"changePct": x, "src": SOURCE}`；
  - 已有原生 changePct → 跳过（显示无标注，仍走帧值）。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.backfill_frame_indices \
      [--start 2026-06-01] [--end 2026-10-20] [--apply]
"""
from __future__ import annotations

import argparse
import os
from typing import Any

SOURCE = "tdx_daily_backfill"

# (indices 内点路径, 本地 vipdoc 市场, 指数代码)——主 4 + indexExtra 3
INDEX_SLOTS: list[tuple[str, str, str]] = [
    ("sh", "sh", "000001"),
    ("hs300", "sh", "000300"),
    ("zz500", "sh", "000905"),
    ("zz1000", "sh", "000852"),
    ("indexExtra.szcz", "sz", "399001"),
    ("indexExtra.cybz", "sz", "399006"),
    ("indexExtra.kc50", "sh", "000688"),
]


def _daily_rows_local(root: str | None, mkt: str, code: str) -> list[tuple[str, float]]:
    """本地 vipdoc 日线 [(date, close)]；root 不可用/文件缺 → []。"""
    if not root:
        return []
    from backend.operations.market_dieban_tdx import read_lday
    path = os.path.join(root, "vipdoc", mkt, "lday", f"{mkt}{code}.day")
    rows: list[tuple[str, float]] = []
    for rec in read_lday(path, 400):
        raw = str(rec[0])
        if len(raw) == 8:
            rows.append((f"{raw[:4]}-{raw[4:6]}-{raw[6:]}", float(rec[4]) / 100.0))
    return rows


def _daily_rows_online(client: Any, code: str) -> list[tuple[str, float]]:
    """线上 mootdx 指数日线 [(date, close)]；client 不可用/失败 → []。"""
    if client is None:
        return []
    try:
        df = client.index_bars(symbol=code, frequency=9, start=0, offset=400)
    except Exception:  # noqa: BLE001 — 线上失败不算致命，fail-visible 由调用方披露
        return []
    rows: list[tuple[str, float]] = []
    if df is not None and len(df) > 0:
        for _, r in df.iterrows():
            rows.append((f"{int(r['year']):04d}-{int(r['month']):02d}-"
                         f"{int(r['day']):02d}", float(r["close"])))
    return rows


def backfill_frame(frame: dict[str, Any], series: dict[str, list[tuple[str, float]]],
                   client: Any) -> tuple[dict[str, dict], list[str]]:
    """对一个 15:00 帧算回填计划：返回 ({点路径: 新entry}, 不可算槽位说明列表)。只算不写。"""
    from backend.operations.jev_zhaban_label import _pct_of_date
    idx = frame.get("indices") if isinstance(frame.get("indices"), dict) else {}
    updates: dict[str, dict] = {}
    missing: list[str] = []
    for path, mkt, code in INDEX_SLOTS:
        entry = idx.get(path) if "." not in path else (idx.get("indexExtra") or {}).get(path.split(".")[1])
        if isinstance(entry, dict) and isinstance(entry.get("changePct"), (int, float)) \
                and not isinstance(entry.get("changePct"), bool):
            continue  # 原生帧值，幂等跳过
        date = str(frame.get("tradingDate"))
        # 本地缺当日棒才查线上（本地全历史、零外呼优先）
        rows = series[(mkt, code)]
        local_dates = {d for d, _ in rows}
        pct = _pct_of_date(rows, date)
        if pct is None and date not in local_dates:
            pct = _pct_of_date(_daily_rows_online(client, code), date)
        if pct is None:
            missing.append(f"{path}（{date} 日线缺当日/前收，fail-visible）")
            continue
        new_entry = dict(entry) if isinstance(entry, dict) else {}
        new_entry["changePct"] = round(pct, 2)
        new_entry["src"] = SOURCE
        updates[path] = new_entry
    return updates, missing


def main() -> None:
    parser = argparse.ArgumentParser(description="15:00 帧 indices 七指数历史回填（指数日线重算）")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.operations.jev_label_jiuyan import _tdx_daily_client
    from backend.operations.market_dieban_tdx import resolve_root

    db = get_runtime_mongodb_database()
    q: dict[str, Any] = {"type": "half_hour", "slotTime": "15:00"}
    if args.start or args.end:
        rng: dict[str, Any] = {}
        if args.start:
            rng["$gte"] = args.start
        if args.end:
            rng["$lte"] = args.end
        q["tradingDate"] = rng
    frames = list(db["snapshot_frames"].find(q, {"tradingDate": 1, "indices": 1})
                  .sort("tradingDate", 1))
    by_date: dict[str, list[dict]] = {}
    for f in frames:
        by_date.setdefault(str(f.get("tradingDate")), []).append(f)
    if not by_date:
        print("范围内无 15:00 帧，退出")
        return
    print(f"[backfill-indices] {min(by_date)}~{max(by_date)}: {len(frames)} 帧 / "
          f"{len(by_date)} 交易日（{'APPLY' if args.apply else 'DRY-RUN'}）")

    root, _ = resolve_root()
    client = _tdx_daily_client()
    series: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for _, mkt, code in INDEX_SLOTS:
        series[(mkt, code)] = _daily_rows_local(root, mkt, code)

    from pymongo import UpdateOne

    ops: list[UpdateOne] = []
    filled = uncomputable = 0
    miss_detail: list[str] = []
    for date, day_frames in by_date.items():
        for frame in day_frames:
            updates, missing = backfill_frame(frame, series, client)  # type: ignore[arg-type]
            filled += len(updates)
            uncomputable += len(missing)
            miss_detail.extend(f"{date} {m}" for m in missing)
            for path, entry in updates.items():
                if args.apply:
                    ops.append(UpdateOne({"_id": frame["_id"]}, {"$set": {f"indices.{path}": entry}}))
    if args.apply and ops:
        for i in range(0, len(ops), 500):
            db["snapshot_frames"].bulk_write(ops[i:i + 500], ordered=False)
    print("FINAL:", {"frames": len(frames), "dates": len(by_date),
                     "slotsFilled": filled, "slotsUncomputable": uncomputable,
                     "applied": args.apply})
    if miss_detail:
        print("不可算明细（fail-visible，不补 0 不伪装）：")
        for m in miss_detail[:40]:
            print("  -", m)
        if len(miss_detail) > 40:
            print(f"  ... 共 {len(miss_detail)} 条")


if __name__ == "__main__":
    main()
