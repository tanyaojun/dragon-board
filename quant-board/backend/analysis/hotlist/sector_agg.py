# -*- coding: utf-8 -*-
"""板块活跃股聚合锚（sector-agg，V2 影子列，2026-10-24）：滚动成员并集 + 逐日横截面统计。

预登记：docs/hotlist-jev/sector-nodes-v2-aggregate-preregistration.md（成分口径 §二、
统计口径 §三，冻结；改动须用户批准）。定位：v1 节点判据的**影子证据列**——不进
classify_board_day、不改 v1 判据表；本模块为纯函数层，零 DB 零 IO，原料由
operations/sector_nodes.py 取齐传入（final 池窗口 + `_daily_bars` 日线棒）。

为什么不是「板块指数」：链式指数在成员漂移下不良定义；判据需要的是「板块今天整体
涨没涨、多少成员翻红」，逐日横截面统计即足够（预登记 §一）。前端命名一律
「活跃股聚合」，不得写「板块指数」。

fail-visible：缺棒/无昨收成员剔除统计并计 missingN（不伪装）；全缺时统计值
None 不落伪 0；窗口不足 N 日 windowDays 披露实际值。
"""
from __future__ import annotations

import statistics
from typing import Any

AGG_VERSION = "2026-10-24b"   # b=N 窗终裁单算（2026-10-24 用户裁决：题材炒作周期 5-10 天，N10 覆盖完整周期）
AGG_WINDOWS = (10,)           # 双算（5/10）影子对照取消；键名保留 aggN10 显式口径


def member_union(board: str, window_pool: list[tuple[str, dict[str, set[str]]]],
                 n: int) -> dict[str, Any]:
    """板块近 n 个可得池日的涨停股并集（含窗口内精确同名匹配）。

    window_pool：[(date, {板块名: 涨停code集})]，任意顺序，仅含**池 ok** 的交易日
    （THS/final 缺失日由 operations 层剔除，不计入窗口）。窗口 = 最新 n 个可得日；
    不足 n 日（历史头部/窗口内缺失日多）如实缩短。
    """
    days = sorted(window_pool, key=lambda x: x[0], reverse=True)[:n]
    codes: set[str] = set()
    for _, pool in days:
        codes |= pool.get(board, set())
    return {"codes": codes, "windowDays": len(days), "daysShort": len(days) < n}


def aggregate_day(*, target_date: str, members: set[str],
                  bars_by_code: dict[str, list[dict[str, Any]]],
                  window_days: int) -> dict[str, Any]:
    """成员集在 target_date 的横截面统计（预登记 §三）。

    bars_by_code：{code: 日线棒升序}，棒含 date/close；涨幅分母 = 棒序列前一根的
    close（最近收盘价口径，长期停牌取最近棒，不跳空补齐）。
    当日无棒（停牌）或首棒即当日（新上市无昨收）→ 剔除统计 + missingN 披露。
    """
    pcts: list[float] = []
    missing = 0
    for code in sorted(members):
        bars = bars_by_code.get(code) or []
        idx = next((i for i, b in enumerate(bars)
                    if str(b.get("date")) == target_date), None)
        close = bars[idx].get("close") if idx is not None else None
        prev_close = bars[idx - 1].get("close") if idx is not None and idx >= 1 else None
        if not close or not prev_close:
            missing += 1
            continue
        pcts.append((float(close) / float(prev_close) - 1) * 100)
    quoted = len(pcts)
    stats: dict[str, Any] = {"memberN": len(members), "quotedN": quoted,
                             "missingN": missing, "windowDays": window_days}
    if quoted == 0:
        stats.update({"pctMean": None, "pctMedian": None, "redRatio": None})
        return stats
    stats["pctMean"] = round(sum(pcts) / quoted, 2)
    stats["pctMedian"] = round(statistics.median(pcts), 2)
    # redRatio 语义=「红盘率」（收盘>昨收的成员占比），非盘中绿转红——键名已定型不改
    stats["redRatio"] = round(sum(1 for p in pcts if p > 0) / quoted, 3)
    return stats


def assemble_agg_rows(*, target_date: str,
                      window_pool: list[tuple[str, dict[str, set[str]]]],
                      bars_by_code: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """全部板块的聚合行（aggN10）；行覆盖 = N10 并集 ⊇ v1 三日窗口。

    今日无涨停但 N 窗内曾有涨停的板块照样出聚合行（家数=0 而聚合已翻红是弱转强
    前兆观察位，预登记 §二）；节点行 rows[] 的三日覆盖语义不受影响（影子行独立）。
    """
    days = sorted(window_pool, key=lambda x: x[0], reverse=True)
    boards = sorted({b for _, pool in days for b in pool})
    rows: list[dict[str, Any]] = []
    for board in boards:
        row: dict[str, Any] = {"board": board}
        for n in AGG_WINDOWS:
            union = member_union(board, window_pool, n)
            row[f"aggN{n}"] = aggregate_day(target_date=target_date,
                                            members=union["codes"],
                                            bars_by_code=bars_by_code,
                                            window_days=union["windowDays"])
        rows.append(row)
    return rows
