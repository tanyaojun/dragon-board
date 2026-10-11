# -*- coding: utf-8 -*-
"""炸板股归因打标（StepA 试点，2026-10-11 用户开火；预登记 docs/hotlist-jev/jev-relay-zhaban-preregistration.md §八）。

- 对象：当日 THS 15:00 炸板池个股，逐股 jev 单题（QUESTIONS_ZHABAN.zhaban_cause）打标；
- 集合：hotlist_jev_zhaban_labels，_id={date}:{code}，幂等跳过 status=ok（--force 重放）；
- 原料：THS 炸板池 item（open_num/time_preview/change_rate/换手/流通市值）派生触板轨迹
  + 韭研板块语境（所属板块今日涨停/炸板家数、板块最高板）+ 个股位置（昨日板数）；
- fail-visible：THS 池缺失日整日跳过（fail-visible 打印，不伪造）；判据锚=可数证据。

CLI：python -m backend.operations.jev_zhaban_label --zhaban-day 2026-09-18 [--zhaban-day ...] [--dry-run] [--force]
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from backend.analysis.hotlist.jev_relay_ammo import (
    QUESTION_SET_VERSION_ZHABAN,
    QUESTIONS_ZHABAN,
    ZHABAN_AMMO_VERSION,
)
from backend.operations.jev_label_jiuyan import (
    DEFAULT_DATASET_ID,
    _dispatch_jev,
    _jiuyan_board_count,
    limitup_sequence_line as _limitup_sequence_line,
    parse_jev_response,
    ths_positions,
)
from backend.operations.jev_relay_index import _pool_of, _ths_failed_snapshot

COLLECTION = "hotlist_jev_zhaban_labels"

_TOUCH_LIMITS = {"GEM": 19.8, "STAR": 19.8}  # 其余（HS 主板）9.8；ST 由名称判定 4.8


def _touch_limit(item: dict[str, Any]) -> float:
    mt = str(item.get("market_type") or "")
    if "ST" in str(item.get("name") or "").upper():
        return 4.8
    return _TOUCH_LIMITS.get(mt, 9.8)


def _touch_profile(item: dict[str, Any]) -> dict[str, Any]:
    """time_preview 分钟涨幅轨迹 → 触板轨迹要素（首触/末触/触板时长/炸板后趋势）。"""
    tp = item.get("time_preview") or []
    limit = _touch_limit(item)
    hits = [k for k, v in enumerate(tp) if isinstance(v, (int, float)) and v >= limit]
    out: dict[str, Any] = {"first_min": None, "last_min": None, "minutes": 0, "tail_slope": None,
                           "max_gain": max((v for v in tp if isinstance(v, (int, float))), default=None)}
    if hits:
        out["first_min"], out["last_min"], out["minutes"] = hits[0], hits[-1], len(hits)
    if len(tp) >= 10 and isinstance(tp[-1], (int, float)) and isinstance(tp[-10], (int, float)):
        out["tail_slope"] = round(tp[-1] - tp[-10], 1)  # 末 10 分钟涨幅变化：正=回封尝试，负=单边走弱
    return out


def _sector_context(db: Any, date: str, code: str, pool: dict[str, dict]) -> dict[str, Any]:
    """板块语境：所属板块（韭研池归属）、板块内今日触板家数/最高板；全市场触板概况。"""
    entry = pool.get(code) or {}
    board = entry.get("board") or ""
    in_board = [c for c, e in pool.items() if e.get("board") == board]
    board_max = max((_day_eff_boards(e) for e in pool.values() if e.get("board") == board), default=0)
    return {"board": board, "board_touch": len(in_board), "board_max": board_max,
            "pool_total": len(pool)}


def _day_eff_boards(entry: dict[str, Any]) -> int:
    b = entry.get("boards")
    return int(b) if b else 1


def build_zhaban_narrative(db: Any, date: str, item: dict[str, Any],
                           pool: dict[str, dict], zhaban_items: list[dict],
                           dataset_id: str = DEFAULT_DATASET_ID) -> str:
    code = str(item.get("code") or "")[-6:]
    name = item.get("name") or code
    prof = _touch_profile(item)
    sec = _sector_context(db, date, code, pool)
    # 昨日板数 + 板块昨日触板对照（②）
    prev_dates = _prev_dates(db, date, 1)
    prev_boards = None
    board_prev_touch = None
    if prev_dates:
        prev_pool = _pool_of(db, prev_dates[-1])
        prev_boards = (prev_pool.get(code) or {}).get("boards")
        if prev_pool:
            board_prev_touch = sum(1 for e in prev_pool.values() if e.get("board") == sec["board"])
    pos_txt = (f"昨日 {prev_boards} 板" if prev_boards else "昨日未涨停/首板")
    traj = prof

    def _num(v, fmt):
        """THS 字段缺失/非数值写「不可考」，不编 0（review I-2：None 进格式串即 TypeError/伪 0）。"""
        return format(v, fmt) if isinstance(v, (int, float)) else "不可考"

    tail_raw = traj["tail_slope"]
    tail_txt = (f"{'回封尝试' if tail_raw >= 0 else '单边走弱'}（{tail_raw:+.1f}）"
                if isinstance(tail_raw, (int, float)) else "不可考（轨迹不足 10 分钟）")  # review M2：None≠回封尝试
    traj_txt = ("触板轨迹：首次触板 开盘后第 {first} 分钟、末次触板 第 {last} 分钟、触板合计 {mins} 分钟、"
                "开板次数 {open} 次（{reopen}）、最高涨幅 {maxg}%、炸板后末 10 分钟 {tailtxt}"
                ).format(first=traj["first_min"] if traj["first_min"] is not None else "?",
                         last=traj["last_min"] if traj["last_min"] is not None else "?",
                         mins=traj["minutes"], open=item.get("open_num"),
                         reopen="反复开板" if (item.get("open_num") or 0) >= 2 else "一次性",
                         maxg=_num(traj["max_gain"], "+.1f"), tailtxt=tail_txt)
    mcap = item.get("currency_value")
    pos_txt_full = (f"个股位置：{pos_txt}；今日最高涨幅 {_num(traj['max_gain'], '+.1f')}%；"
                    f"收盘 {_num(item.get('change_rate'), '+.1f')}%；换手 {_num(item.get('turnover_rate'), '.1f')}%；"
                    f"流通市值 {round(mcap / 1e8, 1) if isinstance(mcap, (int, float)) else '不可考'} 亿")
    # P1-2 高位锚直供（预登记 jev-ammo-p1-preregistration.md §二）：昨日 THS 连板梯队，
    # 首板也收录（one 桶），补「韭研 num 首板不标→高位不可判」的洞；判据零改动。
    ths_prev = ths_positions(db, prev_dates[-1], dataset_id).get(code) if prev_dates else None
    if ths_prev and ths_prev.get("continueDay"):
        # THS continue_day 实为「2连板」字符串（603337/002584 实证），剥后缀统一口径；
        # 剥后非纯数字（「首板」「2天2板」等异形）→ 如实原样展示不套模板（review P2-4）
        cd = str(ths_prev["continueDay"]).replace("连板", "").strip()
        core = (f"昨日{cd}连板" if cd.isdigit()
                else f"THS 原值「{str(ths_prev['continueDay']).strip()}」")
        ths_txt = (f"昨日身位（THS 连板梯队）：{core}"
                   f"（梯队 {ths_prev.get('ladder') or '?'} · 首封 {ths_prev.get('firstSeal') or '?'}）")
    elif prev_dates:
        ths_txt = "昨日身位（THS 连板梯队）：未收录（昨日未涨停或 THS 池缺口，fail-visible）"
    else:
        ths_txt = "昨日身位（THS 连板梯队）：上一交易日不可考（fail-visible）"
    # 板序（①近 10 日 ○● 涨停轨迹，TDX 同源）
    try:
        seq_txt = _limitup_sequence_line(date, code, name, 10)
    except Exception as e:  # noqa: BLE001 — fail-visible
        seq_txt = f"板序：计算失败 {e}"
    # 板块语境（②板块昨日触板对照）
    board_zhaban = sum(1 for i in zhaban_items
                       if str(i.get("code") or "")[-6:] in {c for c, e in pool.items() if e.get("board") == sec["board"]})
    prev_cmp = f"、昨日触板 {board_prev_touch} 家" if board_prev_touch is not None else ""
    if sec["board"]:
        sec_txt = (f"板块语境：所属「{sec['board']}」今日触板 {sec['board_touch']} 家{prev_cmp}、"
                   f"其中今日炸板 {board_zhaban} 家、板块内最高板 {sec['board_max']} 板；"
                   f"全市场今日触板 {sec['pool_total']} 家、炸板 {len(zhaban_items)} 家")
    else:
        sec_txt = (f"板块语境：韭研触板池未收录该股（板块不可考）；"
                   f"全市场今日触板 {sec['pool_total']} 家、炸板 {len(zhaban_items)} 家")
    # 大盘（③15:00 帧 indices 现成）
    idx_txt = "大盘：不可考（帧缺失）"
    fr = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"indices.sh": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    sh = ((fr or {}).get("indices") or {}).get("sh") or {}
    ch = sh.get("change")
    if isinstance(ch, (int, float)):
        idx_txt = f"大盘：上证今日 {ch:+.2f}%"
    return (f"{date} 交易日 · 炸板股归因（个股单题）\n"
            f"个股：{name}({code})\n{traj_txt}\n{pos_txt_full}\n{ths_txt}\n{seq_txt}\n{sec_txt}\n{idx_txt}")


def _prev_dates(db: Any, date: str, n: int) -> list[str]:
    return _trading_dates_before(db, date, n)


def _trading_dates_before(db: Any, date: str, n: int) -> list[str]:
    from backend.operations.jev_label_jiuyan import trading_dates_before
    return trading_dates_before(db, date, n)


def run_zhaban_label_day(db: Any, dates: list[str], *, dry_run: bool = False,
                         dataset_id: str = DEFAULT_DATASET_ID, force: bool = False) -> None:
    col = db[COLLECTION]
    for date in dates:
        items, found = _ths_failed_snapshot(db, date, dataset_id)
        if not found:
            print(f"[zhaban] {date} THS 炸板池缺失/降级，整日跳过（fail-visible）")
            continue
        pool = _pool_of(db, date)
        if not pool:
            print(f"[zhaban] {date} 韭研池缺失，整日跳过（fail-visible）")
            continue
        done = skipped = fired = 0
        for item in items:
            code = str(item.get("code") or "")[-6:]
            if not code:
                continue
            _id = f"{date}:{code}"
            if not force and col.find_one({"_id": _id, "status": "ok"}):
                done += 1
                continue
            try:
                narrative = build_zhaban_narrative(db, date, item, pool, items, dataset_id)
                if dry_run:
                    print(f"[dry] {_id} {item.get('name')} narrative_chars={len(narrative)}")
                    print(narrative)
                    continue
                env, ms = _dispatch_jev(narrative, QUESTIONS_ZHABAN)
                parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_ZHABAN))
                ans = (parsed.get("answers") or {}).get("zhaban_cause") or {}
                doc = {"_id": _id, "origin": "zhaban_label_pilot", "tradingDate": date,
                       "code": code, "name": item.get("name"),
                       "status": "ok" if parsed["ok"] else "degraded",
                       "questionSetVersion": QUESTION_SET_VERSION_ZHABAN,
                       "ammoVersion": ZHABAN_AMMO_VERSION,
                       # answers 原样落库（P0-2）：模型自报 confidence 此前未落库，自此保全
                       "answers": parsed.get("answers"),
                       "openNum": item.get("open_num"), "changeRate": item.get("change_rate"),
                       "touchProfile": _touch_profile(item),
                       "zhabanCause": ans.get("choice"),
                       "zhabanCauseProbabilities": ans.get("probabilities"),
                       "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                       "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                       "responseRaw": None if parsed["ok"] else env,
                       "narrative": narrative,
                       "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
                col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                fired += 1
                print(f"[zhaban] {_id} {item.get('name')} → {doc['zhabanCause']} ok={parsed['ok']} "
                      f"tokens={(parsed.get('usage') or {}).get('input_tokens', 0) + (parsed.get('usage') or {}).get('output_tokens', 0)}")
            except Exception as exc:  # noqa: BLE001 — 单股隔离（review I-2，对齐批次C I3 先例）：原料异常落 degraded 不炸整日
                col.replace_one({"_id": _id}, {
                    "_id": _id, "origin": "zhaban_label_pilot", "tradingDate": date,
                    "code": code, "name": item.get("name"), "status": "degraded",
                    "errorCode": "narrative_build_failed",
                    "errorDetail": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "questionSetVersion": QUESTION_SET_VERSION_ZHABAN,
                    "ammoVersion": ZHABAN_AMMO_VERSION,
                    "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, upsert=True)
                print(f"[zhaban] {_id} {item.get('name')} 单股异常降级（{type(exc).__name__}: {str(exc)[:120]}）")
        print(f"[zhaban] {date} 完成：新打 {fired} / 幂等跳过 {done} / 池 {len(items)} 家")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--zhaban-day", dest="zhaban_day", action="append", default=[],
                    help="炸板打标交易日（可多次）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    run_zhaban_label_day(db, args.zhaban_day, dry_run=args.dry_run, force=args.force)
