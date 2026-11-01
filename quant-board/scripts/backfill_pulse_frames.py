# -*- coding: utf-8 -*-
"""V4-E pulse 帧序列 lc5 回填（sector-nodes-v4e-intraday-vol-preregistration §五）。

对每个有 sector-nodes 文档的交易日 d（05-07~10-30），用本地 vipdoc fzline/lc5
（5 分钟线，用户已下载至 2026-10-30，零网络）重建 8 个 30 分钟帧，补入
`hotlist_jev_sector_pulse` doc.frames[frameKey]：

- 成员口径 = sector_pulse._frozen_union（以 d 为 today，昨日封窗 N10 冻结）；
- 帧数据与 live 帧同构：复用 sector_pulse._pulse_stats / _member_amounts /
  _board_vol_ratio（伪 quotes_map=帧末 close/昨收/帧末累计 amount），口径一致；
- 量比递推：昨日 doc.frames 同帧 boards（先旧后新回填，昨日先就位）；
- fail-visible：成员缺 lc5 → 缺报价口径披露；昨收不可考 → 成员整体剔除
  （amounts 不存，次日量比少一个样本，missingN 如实披露）；不铸 0；
- 幂等：doc 存在时只补缺失帧键（live 帧优先不覆盖）；doc 不存在则建
  backfillOnly 档（顶层读数不伪造）。

用法（默认 dry-run 只打印摘要；--apply 才写库）：
    cd quant-board
    .venv/Scripts/python.exe -X utf8 scripts/backfill_pulse_frames.py --apply
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import datetime

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.path.insert(0, ".")

from backend.data.repositories.repository_factory import (  # noqa: E402
    get_runtime_mongodb_database)
from backend.operations.jev_label_jiuyan import (  # noqa: E402
    trading_dates_before, _local_root)
from backend.operations.sector_pulse import (  # noqa: E402
    COLLECTION_PULSE, COLLECTION_NODES, PULSE_VERSION, _FRAME_KEYS,
    _board_vol_ratio, _frozen_union, _member_amounts, _pulse_stats)
from backend.operations.jev_label_jiuyan import _daily_bars  # noqa: E402  (日线尾棒备用)

LC_DT = np.dtype([("date", "<u2"), ("time", "<u2"), ("open", "<f4"), ("high", "<f4"),
                  ("low", "<f4"), ("close", "<f4"), ("amount", "<f4"), ("vol", "<u4"),
                  ("rsv", "<u4")])
BOUNDS = np.array([1000, 1030, 1100, 1130, 1330, 1400, 1430, 1500])
_MARKET = (("60", "sh"), ("68", "sh"), ("00", "sz"), ("30", "sz"))


def prev_date_of(db, d: str) -> str | None:
    prevs = trading_dates_before(db, d, 1)
    return prevs[-1] if prevs else None


def lc5_path(code: str) -> str | None:
    digits = "".join(ch for ch in str(code) if ch.isdigit())[-6:]
    if len(digits) != 6:
        return None
    for prefix, market in _MARKET:
        if digits.startswith(prefix):
            return f"{_local_root()}/vipdoc/{market}/fzline/{market}{digits}.lc5"
    return None


def agg_lc5_frames(code: str) -> dict[str, tuple[np.ndarray, np.ndarray]] | None:
    """{day: (帧末累计 amount[8], 帧末 close[8])}；文件缺/空 → None。"""
    import os
    path = lc5_path(code)
    if not path or not os.path.exists(path):
        return None
    try:
        raw = np.fromfile(path, dtype=LC_DT)
    except Exception:
        return None
    if len(raw) == 0:
        return None
    num = raw["date"].astype(np.int64)
    y = num // 2048 + 2004
    m = (num % 2048) // 100
    dd = (num % 2048) % 100
    day_str = np.char.add(np.char.add(
        np.char.add(y.astype("<U4"), "-"), np.char.zfill(m.astype("<U2"), 2)), "-")
    day_str = np.char.add(day_str, np.char.zfill(dd.astype("<U2"), 2))
    t = raw["time"].astype(np.int64)
    hhmm = (t // 60) * 100 + t % 60
    slot = np.clip(np.searchsorted(BOUNDS, hhmm, side="left"), 0, 7)
    uniq_days, day_idx = np.unique(day_str, return_inverse=True)
    keys = day_idx * 8 + slot
    amt_sum = np.bincount(keys, weights=raw["amount"].astype(np.float64),
                          minlength=len(uniq_days) * 8).reshape(-1, 8)
    cum = np.cumsum(amt_sum, axis=1)
    close_last = np.full(len(uniq_days) * 8, np.nan)
    last_pos = np.nonzero(np.diff(keys, append=len(keys) + 1))[0]
    close_last[keys[last_pos]] = raw["close"].astype(np.float64)[last_pos]
    close_last = close_last.reshape(-1, 8)
    return {str(d): (cum[i], close_last[i]) for i, d in enumerate(uniq_days)}


def main() -> int:
    ap = argparse.ArgumentParser(description="V4-E pulse 帧 lc5 回填（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="实写 MongoDB（缺省 dry-run）")
    args = ap.parse_args()
    db = get_runtime_mongodb_database()
    all_dates = trading_dates_before(db, "2026-10-31", 300)          # 旧→新
    date_set = set(all_dates)
    dates = [d for d in all_dates
             if db[COLLECTION_NODES].find_one({"_id": f"{d}:SECTOR_NODES"}, {"_id": 1})]
    # 需要昨收的日期 = 回填日期 ∪ 其昨日
    need_prev = {prev_date_of(db, d) for d in dates} - {None}
    need_days = set(dates) | need_prev
    print(f"回填交易日: {len(dates)}（{dates[0]}~{dates[-1]}）  需 lc5 日: {len(need_days)}")

    # 成员码全集
    union_cache: dict[str, tuple[dict[str, set[str]], str | None]] = {}
    need_codes: set[str] = set()
    for d in dates:
        members, root = _frozen_union(db, d)
        union_cache[d] = (members, root)
        if root:
            continue
        for codes in members.values():
            need_codes |= codes
    print(f"成员码: {len(need_codes)}")

    t0 = time.time()
    code_data: dict[str, dict | None] = {}
    miss = 0
    for k, code in enumerate(sorted(need_codes)):
        data = agg_lc5_frames(code)
        if data is None:
            miss += 1
        code_data[code] = data
        if (k + 1) % 400 == 0:
            print(f"  ..lc5 {k + 1}/{len(need_codes)}  缺={miss}  {time.time()-t0:.0f}s")
    print(f"lc5 就绪: 缺失/空={miss}/{len(need_codes)}  {time.time()-t0:.0f}s")

    # 逐日回填（旧→新，量比递推依赖昨日帧先就位；dry-run 用内存缓存递推）
    n_docs_new = n_docs_patched = n_frames = 0
    frame_stat = {"prevMiss": 0, "lc5Miss": 0}
    backfilled: dict[str, dict] = {}   # {date: frames} 内存递推（dry-run 不落库也能算量比）
    for d in dates:
        members, root = union_cache[d]
        prev = prev_date_of(db, d)
        # 昨收（prev 日 15:00 帧末 close）
        y_close: dict[str, float] = {}
        for code in need_codes:
            cd = code_data.get(code)
            if cd and prev in cd:
                c = float(cd[prev][1][7])
                if c == c and c > 0:
                    y_close[code] = c
        existing = db[COLLECTION_PULSE].find_one({"_id": f"{d}:PULSE"}) or {}
        frames_existing = existing.get("frames") or {}
        new_frames: dict[str, dict] = {}
        prev_frames = dict(backfilled.get(prev, {}))
        if prev:
            prev_doc = db[COLLECTION_PULSE].find_one({"_id": f"{prev}:PULSE"},
                                                     {"frames": 1}) or {}
            prev_frames.update(prev_doc.get("frames") or {})
        for fi, key in enumerate(_FRAME_KEYS):
            if key in frames_existing:
                continue                     # live 帧优先，不覆盖
            boards = {}
            for board, codes in sorted(members.items()):
                pseudo = {}                  # 伪 quotes_map {code: (帧末价, 昨收, 帧末累计额)}
                amounts = {}
                for code in sorted(codes):
                    cd = code_data.get(code)
                    if not cd or d not in cd:
                        continue             # 缺 lc5 → 缺报价口径披露
                    cum, closes = cd[d]
                    c = float(closes[fi])
                    if c != c or c <= 0:
                        continue             # 帧末价不可考
                    yc = y_close.get(code)
                    if yc is None:
                        continue             # 昨收不可考 → 成员整体剔除（amounts 不存，
                                             # 次日量比少一个样本；missingN 如实披露）
                    a = float(cum[fi])
                    pseudo[code] = (c, yc, a)
                    amounts[code] = a
                if not pseudo:
                    frame_stat["lc5Miss"] += 1
                    boards[board] = {"memberN": len(codes), "quotedN": 0,
                                     "missingN": len(codes), "pctMean": None,
                                     "pctMedian": None, "redRatio": None,
                                     "amountSum": None, "amountQuotedN": 0,
                                     "amountMissingN": 0, "amounts": {},
                                     "volRatioMedian": None, "volRatioQuotedN": 0}
                    continue
                stats = _pulse_stats(pseudo, codes)
                vol_med, vol_n = _board_vol_ratio(
                    (prev_frames.get(key) or {}).get("boards"), board, amounts)
                stats.update({"amounts": amounts, "volRatioMedian": vol_med,
                              "volRatioQuotedN": vol_n})
                if prev_frames.get(key) is None:
                    frame_stat["prevMiss"] += 1
                boards[board] = stats
            new_frames[key] = {
                "at": f"{d}T{key}:00", "src": "lc5_backfill",
                "volBasis": "prev_frame" if key in prev_frames else "prev_frame_missing",
                "boards": boards,
            }
        if not new_frames:
            continue
        n_frames += len(new_frames)
        backfilled[d] = new_frames
        if existing:
            n_docs_patched += 1
        else:
            n_docs_new += 1
        if not args.apply:
            continue
        if existing:
            set_doc = {f"frames.{k}": v for k, v in new_frames.items()}
            db[COLLECTION_PULSE].update_one({"_id": f"{d}:PULSE"},
                                            {"$set": set_doc})
        else:
            doc = {"_id": f"{d}:PULSE", "kind": "sector_pulse",
                   "version": PULSE_VERSION, "date": d,
                   "backfillOnly": True,
                   "note": "V4-E lc5 回填帧档：顶层实时读数不伪造，仅 frames",
                   "computedAt": datetime.now().isoformat(timespec="seconds"),
                   "frames": new_frames}
            db[COLLECTION_PULSE].insert_one(doc)
    verb = "已写" if args.apply else "dry-run（加 --apply 实写）"
    print(f"\n{verb}: 新建档 {n_docs_new}  补帧档 {n_docs_patched}  帧数 {n_frames}")
    print(f"统计: 昨日同帧缺失(量比不可考){frame_stat['prevMiss']}  全缺lc5板块{frame_stat['lc5Miss']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
