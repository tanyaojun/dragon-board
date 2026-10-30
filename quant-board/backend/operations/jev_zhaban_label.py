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
import os
import time
from typing import Any

from backend.analysis.hotlist.jev_relay_ammo import (
    QUESTION_SET_VERSION_ZHABAN,
    QUESTIONS_ZHABAN,
    ZHABAN_AMMO_VERSION,
)
from backend.core.limit_rules import limit_threshold_pct
from backend.operations.jev_label_jiuyan import (
    DEFAULT_DATASET_ID,
    _dispatch_jev,
    _jiuyan_board_count,
    limitup_sequence_line as _limitup_sequence_line,
    parse_jev_response,
    ths_positions,
)
from backend.operations.jev_label_jiuyan import _ths_failed_items, _tdx_daily_client
from backend.operations.jev_relay_index import _pool_of, _range_num_txt

COLLECTION = "hotlist_jev_zhaban_labels"

_SH_PCT_CACHE: dict[tuple, tuple] = {}
_SH_INDEX_LDAY = ("sh", "sh000001")     # 上证指数本地日线（vipdoc/sh/lday/sh000001.day）
_SH_INDEX_ONLINE = "999999"            # mootdx index_bars 的上证综指符号


def _sh_index_change_pct(db: Any, date: str,
                         dataset_id: str = DEFAULT_DATASET_ID) -> tuple[float | None, str | None]:
    """上证指数当日涨跌幅（炸板链大盘行的历史补数，2026-10-20）。

    缺陷：历史 15:00 帧缺 `indices.sh`，67 个打标日里 84.5%（1438/1701）的炸板文档被迫写
    「大盘：不可考（帧缺失）」——`broad_market`（大盘拖累）判据在这部分样本上等于没有输入。
    但**指数涨跌幅是客观事实、可从日线重算**（AGENTS §4.0：不得因为帧缺就冒充「没有」）。
    回退链（逐级，行内必须标实际用的源，禁把重算值伪装成帧值）：
      ① 15:00 帧 `indices.sh.changePct`（relay/情绪链同源，首选）；
      ② 本地 vipdoc `sh000001.day` 日线重算（close vs 前收，零外呼、可复现）；
      ③ 线上 mootdx `index_bars(999999)` 日线重算（本地未落当日棒时兜底）。
    全缺 → (None, None)：调用方如实写「不可考（帧与日线皆缺）」，不补 0。
    """
    key = (dataset_id, date)
    if key in _SH_PCT_CACHE:
        return _SH_PCT_CACHE[key]
    result: tuple[float | None, str | None] = (None, None)
    rows: list[tuple[str, float]] = []
    try:  # ② 本地日线（全历史、零外呼）
        from backend.operations.market_dieban_tdx import read_lday, resolve_root
        root, _ = resolve_root()
        if root:
            path = os.path.join(root, "vipdoc", _SH_INDEX_LDAY[0], "lday",
                                f"{_SH_INDEX_LDAY[1]}.day")
            for rec in read_lday(path, 400):
                raw = str(rec[0])
                if len(raw) == 8:
                    rows.append((f"{raw[:4]}-{raw[4:6]}-{raw[6:]}", float(rec[4]) / 100.0))
            pct = _pct_of_date(rows, date)
            if pct is not None:
                result = (pct, "本地日线重算")
    except Exception:  # noqa: BLE001 — 本地不可用不算失败，继续线上
        rows = []
    if result[0] is None:
        try:  # ③ 线上指数日线
            client = _tdx_daily_client()
            if client is not None:
                df = client.index_bars(symbol=_SH_INDEX_ONLINE, frequency=9, start=0, offset=300)
                online = []
                if df is not None and len(df) > 0:
                    for _, r in df.iterrows():
                        online.append((f"{int(r['year']):04d}-{int(r['month']):02d}-"
                                       f"{int(r['day']):02d}", float(r["close"])))
                pct = _pct_of_date(online, date)
                if pct is not None:
                    result = (pct, "线上指数日线重算")
        except Exception:  # noqa: BLE001 — 线上失败保持 (None, None)，调用方 fail-visible
            result = (None, None)
    _SH_PCT_CACHE[key] = result
    return result


def _pct_of_date(rows: list[tuple[str, float]], date: str) -> float | None:
    """(date, close) 升序序列里求 date 相对前一交易日收盘的涨跌幅（%）；缺当日/缺前一日 → None。"""
    for i, (d, close) in enumerate(rows):
        if d == date:
            if i == 0 or close <= 0:
                return None
            prev = rows[i - 1][1]
            if prev <= 0:
                return None
            return (close - prev) / prev * 100
    return None


def _touch_limit(item: dict[str, Any]) -> float:
    """触板判定线（§1.2-1 单一事实源）——委托 `core/limit_rules`：9.8/19.8/29.8。

    2026-10-20 撤销本模块的硬编码副本（原 `_TOUCH_LIMITS = {"GEM":19.8,"STAR":19.8}` +
    默认 9.8 + ST 名称→4.8），三处与既有裁决冲突：
    1. ST ±5% 特判已由 2026-10-05 「阈值公共函数，禁硬编码副本」裁决废除（2026-09 新规
       主板 ST 亦 ±10%）——本模块是漏网副本；
    2. 北交所 30% 未覆盖（落到默认 9.8 → 北交所 +10% 就被判成触板）；
    3. 阈值只按 `market_type`（HS/GEM/STAR）分支，与板籍前缀口径（688/30/43/8/92）双源。
    触板轨迹（首触/末触/时长/开板次数）的上游数值，口径漂移会直接改写炸板归因。

    审查 P1-2（2026-10-20）：改委托后必须先把 code 归一成裸 6 位——`limit_ratio` 对任何
    带前缀的字符串（`sz300001`/`bj830799`）都会落到主板 0.10，则 20cm 股按 9.8 判触板，
    首触/开板次数全错（旧实现按 `market_type` 分支，天然不受 code 形状影响，故此处是新风险）。
    同模块 `run_zhaban_label_day` 落库键也用 `[-6:]`，口径一致。
    """
    return limit_threshold_pct(str(item.get("code") or "").strip()[-6:])


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
    prev_entry = {}
    board_prev_touch = None
    if prev_dates:
        prev_pool = _pool_of(db, prev_dates[-1])
        prev_entry = prev_pool.get(code) or {}
        if prev_pool:
            board_prev_touch = sum(1 for e in prev_pool.values() if e.get("board") == sec["board"])
    # 昨日身位文案补跨度（2026-10-16 口径一致化）：「昨日 4 板」→「昨日 7天4板」，
    # 与涨停复盘高度列/relay 梯队表同规；M 缺失（韭研首板口径）→ 首板，不伪造天数
    pos_txt = (f"昨日 {_range_num_txt(prev_entry)}" if prev_entry.get("boards")
               else "昨日未涨停/首板")
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
        ths_txt = "昨日身位（THS 连板梯队）：未收录"
    else:
        ths_txt = "昨日身位（THS 连板梯队）：上一交易日不可考"
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
        sec_txt = (f"板块语境：该股板块不可考；"
                   f"全市场今日触板 {sec['pool_total']} 家、炸板 {len(zhaban_items)} 家")
    # 大盘（③15:00 帧 indices 现成；帧缺 → 指数日线重算，见 _sh_index_change_pct）
    idx_txt = "大盘：不可考"
    fr = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"indices.sh": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    sh = ((fr or {}).get("indices") or {}).get("sh") or {}
    pct = sh.get("changePct")
    change = sh.get("change")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        idx_txt = f"大盘：上证今日 {pct:+.2f}%"
    elif isinstance(change, (int, float)) and not isinstance(change, bool):
        # 存量帧只落 change=涨跌额（点位）：按 % 呈现即伪造暴跌（2026-10-16 单位错位排查，
        # 10-12 两只 label 因「上证 -19.19%」假暴跌误判 broad_market，真实约 -0.5%）。
        # fail-visible：点位是真实可观测数据不丢弃，带单位呈现（对齐情绪链证据行「点」口径），
        # 缺的涨跌幅明示缺失，由模型按 conditional 判据自行裁量
        idx_txt = f"大盘：上证今日 {change:+.2f} 点"
    else:
        # 帧无 indices：用指数日线重算（2026-10-20 补数，历史 84.5% 的「不可考」由此可修）
        pct2, src = _sh_index_change_pct(db, date, dataset_id)
        if isinstance(pct2, (int, float)) and not isinstance(pct2, bool):
            idx_txt = f"大盘：上证今日 {pct2:+.2f}%"

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
        items_map, found = _ths_failed_items(db, date, dataset_id)
        items = list(items_map.values())
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
