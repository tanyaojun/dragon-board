# -*- coding: utf-8 -*-
"""jev 方向独立裁决线（v3-gate）生产 runner。

预登记：docs/hotlist-jev/jev-direction-standalone-preregistration.md（判据单一事实源 =
backend/analysis/hotlist/jev_direction_ammo.py，VERBATIM 锁定测试 tests/hotlist/test_jev_direction_gate.py）。

判读时点：盘中 11:00 槽帧落盘即判读（scheduler run_direction_loop 11:08 触发，advisory 语义）。
原料：跨日出现序列（引擎同源）+ Position Stats 日级锚现算 + 量价行 + Market Gate 相位带 as-of。
人口：当日 ≥4 槽出现、前三交易日连续在榜、主力字段非空、序列 ≥10 点。
落库：hotlist_jev_direction，_id={date}:11:00:{code}:DIR（单题集，2026-10-13 用户裁决
      variant 收敛：A/B 一致率 70-82% 高度重叠+B 成本 4×，B 拆分层退役留档）；
      隔日验证列由 backfill_direction_verify 回填（T+1 最后一槽 change）。
红线：--fire 需 JEV_CF_TOKEN/JEV_TYPESAFE_KEY；测试零真实调用零网络。
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.analysis.hotlist.jev_direction_ammo import (
    AMMO_VERSION,
    DIRECTION_SLOT,
    QUESTION_SET_VERSION,
    QUESTIONS_A,
    band_of,
    questions_hash,
)

DEFAULT_DATASET_ID = "dragonboard_live"
DIRECTION_SNAPSHOT_TYPE = "half_hour"
HOT_ZONE = 80
SERIES_MIN_POINTS = 10
SERIES_WINDOW_DAYS = 10  # 10 交易日全槽窗口 ≈ ≥30 次出现（§二「最近 ~30 次」按次数截断的更严格等价）
TOKEN_FUSE = 1_500_000
_TZ = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(_TZ).isoformat(timespec="seconds")


# ── 帧基础设施 ──────────────────────────────────────────────

def _slot_frame(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": slot},
        sort=[("timestamp", -1)])


def _frame_rows(db: Any, date: str, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, dict]:
    f = _slot_frame(db, date, slot, dataset_id)
    if not f:
        return {}
    return {str(r["code"]): r for r in db["snapshot_stock_rows"].find(
        {"datasetId": dataset_id, "snapshotId": str(f["snapshotId"])})}


def _day_slot_frames(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[tuple[str, str]]:
    return [(str(f["slotTime"]), str(f["snapshotId"])) for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": d}).sort([("slotTime", 1)])]


def _trading_dates_with_slot(db: Any, slot: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    return sorted({f["tradingDate"] for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": slot},
        {"tradingDate": 1}) if f.get("tradingDate")})


def _pct_rank(rank: Any, total: int) -> float | None:
    if not isinstance(rank, (int, float)) or not total:
        return None
    return round((total - rank + 1) / total * 100, 2)


def _r2(v: Any) -> Any:
    return round(v, 2) if isinstance(v, (int, float)) else v


def _f(v: Any, suffix: str = "") -> str:
    if not isinstance(v, (int, float)):
        return "missing"
    return f"{round(v, 2)}{suffix}"


def _limit_flag(code: str, chg: Any) -> tuple[str, str]:
    """板块涨跌停旗标（口径与引擎 volume_price._daily_limit_pct 逐字对齐）。"""
    v = str(code)[-6:]
    lim = 19.8 if v.startswith(("300", "301", "688", "689")) else \
        29.8 if v.startswith(("8", "4", "9")) else 9.8
    up = isinstance(chg, (int, float)) and chg >= lim
    dn = isinstance(chg, (int, float)) and chg <= -lim
    return "yes" if up else "no", "yes" if dn else "no"


def _sentiment_asof(db: Any, d: str, slot: str) -> dict | None:
    doc = db["hotlist_sentiment"].find_one(
        {"datasetId": DEFAULT_DATASET_ID, "snapshotType": DIRECTION_SNAPSHOT_TYPE,
         "tradingDate": d, "slotTime": {"$lte": slot}},
        sort=[("slotTime", -1)])
    if not doc:
        return None
    es = doc.get("emotionScore") or {}
    score = es.get("score")
    return {"score": score, "band": band_of(score), "stage": doc.get("stage"),
            "riskLevel": doc.get("riskLevel"), "slotTime": doc.get("slotTime")}


# ── 判读日上下文 ────────────────────────────────────────────

def setup_day(db: Any, d: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    dates = _trading_dates_with_slot(db, DIRECTION_SLOT)
    if d not in dates:
        raise LookupError(f"{d} 无 {DIRECTION_SLOT} 帧（未采集或非交易日）")
    idx = dates.index(d)
    prev10 = dates[max(0, idx - 10):idx]
    next_day = dates[idx + 1] if idx + 1 < len(dates) else None
    cur = _frame_rows(db, d, DIRECTION_SLOT, dataset_id)
    d3 = prev10[-3] if len(prev10) >= 3 else None
    d3_close = _frame_rows(db, d3, "15:00", dataset_id) if d3 else {}
    diffs = []
    for code, r in cur.items():
        p_now = _pct_rank(r.get("rank"), len(cur))
        r3 = d3_close.get(code)
        if p_now is None or not r3:
            continue
        p3 = _pct_rank(r3.get("rank"), len(d3_close))
        if p3 is not None:
            diffs.append(p_now - p3)
    diffs.sort()
    n = len(diffs)
    ctx = {"dates": dates, "prev10": prev10, "next_day": next_day, "cur": cur,
           "pool": len(cur),
           "mm": round(diffs[n // 2], 2) if n else None,
           "up_share": round(len([x for x in diffs if x > 0]) / n * 100, 1) if n else None,
           "sent": _sentiment_asof(db, d, DIRECTION_SLOT),
           "series_days": [x for x in _trading_dates_with_slot(db, "09:30") if x < d][-SERIES_WINDOW_DAYS:],
           "prev3": prev10[-3:]}
    return ctx


# ── 原料组装（预登记 §二 原料合同） ──────────────────────────

def build_attention_series(db: Any, code: str, ctx: dict, dataset_id: str = DEFAULT_DATASET_ID) -> list[dict]:
    pts = []
    for dd in ctx["series_days"]:
        for slot, sid in _day_slot_frames(db, dd, dataset_id):
            r = db["snapshot_stock_rows"].find_one(
                {"datasetId": dataset_id, "snapshotId": sid, "code": code},
                {"rank": 1, "change": 1})
            if not r or r.get("rank") is None:
                continue
            n = db["snapshot_stock_rows"].count_documents(
                {"datasetId": dataset_id, "snapshotId": sid})
            p = _pct_rank(r["rank"], n)
            if p is not None:
                pts.append({"d": dd, "slot": slot, "rank": r["rank"], "pct": p,
                            "chg": _r2(r.get("change"))})
    return pts


def position_stats(series_pts: list[dict], cur_pct: float | None, prev10: list[str]) -> dict:
    by_day: dict[str, float] = {}
    for p in series_pts:
        by_day[p["d"]] = p["pct"]
    dl = [by_day.get(d) for d in prev10]
    dl = [p for p in dl if p is not None]
    day3_net = (cur_pct - dl[-3]) if (cur_pct is not None and len(dl) >= 3) else None
    pool_pk = dl + ([cur_pct] if cur_pct is not None else [])
    dd10 = round(max(pool_pk) - cur_pct, 2) if (pool_pk and cur_pct is not None) else None
    streak = 0
    for p in reversed(dl):
        if p is not None and p >= HOT_ZONE:
            streak += 1
        else:
            break
    by_day_keys = {p["d"] for p in series_pts}
    ims = 0
    for d in reversed(prev10):
        if d in by_day_keys:
            ims += 1
        else:
            break
    return {"current": cur_pct, "day3_net": round(day3_net, 2) if day3_net is not None else None,
            "drawdown10": dd10, "hot_streak": streak, "in_market_streak": ims}


def build_state(db: Any, code: str, d: str, ctx: dict,
                dataset_id: str = DEFAULT_DATASET_ID) -> tuple[str, dict, dict]:
    row = ctx["cur"].get(code)
    if not row:
        raise LookupError(f"{code} 不在判读帧")
    series = build_attention_series(db, code, ctx, dataset_id)
    cur_pct = _pct_rank(row.get("rank"), ctx["pool"])
    series.append({"d": d, "slot": DIRECTION_SLOT, "rank": row.get("rank"),
                   "pct": cur_pct, "chg": _r2(row.get("change"))})
    if len(series) < SERIES_MIN_POINTS:
        raise LookupError(f"{code} 出现序列仅 {len(series)} 点，不足判读")
    ps = position_stats(series, cur_pct, ctx["prev10"])
    ser_lines = [f"{p['d']} {p['slot']}: rank {p['rank']} = percentile {p['pct']}, "
                 f"change {_f(p['chg'])}%" for p in series]
    chg, vr = row.get("change"), row.get("volumeRatio")
    zlje, zljzb = row.get("zlje"), row.get("zljzb")
    up, dn = _limit_flag(code, chg)
    sent = ctx["sent"] or {}
    head = f"{d} {DIRECTION_SLOT} (intraday) · {code} {row.get('name') or ''}".rstrip()
    blocks = {
        "series": (["[Attention Series · last appearances across days and slots, time-ascending; "
                    "percentile 0-100 = attention rank, higher = hotter; LAST line = current "
                    "intraday reading]"] + ser_lines),
        "pos": (["[Position Stats · changes in percentile points, positive = attention rising; "
                 "drawdown = distance below peak]",
                 f"current percentile: {_f(cur_pct)}",
                 f"3-trading-day net percentile change: {_f(ps['day3_net'])}",
                 f"drawdown from the 10-day peak: {_f(ps['drawdown10'])}",
                 f"hot-zone streak (consecutive trading days ending yesterday with percentile >= "
                 f"{HOT_ZONE}): {ps['hot_streak']}",
                 f"consecutive in-market days: {ps['in_market_streak']}"]),
        "vp": (["[Volume-Price]",
                f"change: {_f(chg)}% · volume ratio (vs 5-day same-time avg): {_f(vr)}"
                f" · main-force net flow: {_f(None if zlje is None else zlje / 1e8)} (100M CNY)"
                f" · main-force net ratio: {_f(zljzb, '%')}"
                f" · turnover: {_f(row.get('turnoverRate'), '%')}"
                f" · limit-up: {up} · limit-down: {dn}"]),
        "gate": (["[Market Gate · environment for BUY decisions]",
                  f"hot-list sentiment phase band: {sent.get('band') or 'missing'} "
                  f"(score {_f(sent.get('score'))}; fixed phase lines: cold <40 / weak 40-60 / "
                  f"strong 60-75 / peak >=75) · market stage: {sent.get('stage') or 'missing'} "
                  f"(as of {sent.get('slotTime')})",
                  f"pool median 3-trading-day percentile change: {_f(ctx['mm'])}",
                  f"pool breadth (stocks with rising 3-day percentile): "
                  f"{_f(ctx['up_share'], '%')}"]),
        "mkt": (["[Market Context]",
                 f"pool size: {ctx['pool']} · market median 3-trading-day percentile change: "
                 f"{_f(ctx['mm'])}"]),
    }
    return head, blocks, {"pos": ps, "series_points": len(series), "sentiment": sent,
                          "mm": ctx["mm"], "up_share": ctx["up_share"]}


# ── 人口（与实验口径一致） ───────────────────────────────────

def build_direction_population(db: Any, d: str, ctx: dict,
                               dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    by_day_cache = {dd: set() for dd in ctx["series_days"]}
    for dd in ctx["series_days"]:
        for slot, sid in _day_slot_frames(db, dd, dataset_id):
            for code in db["snapshot_stock_rows"].distinct(
                    "code", {"datasetId": dataset_id, "snapshotId": sid}):
                by_day_cache[dd].add(code)
    today_slots = [(s, sid) for s, sid in _day_slot_frames(db, d, dataset_id) if s <= DIRECTION_SLOT]
    today_seen: dict[str, set] = {}
    for s, sid in today_slots:
        for code in db["snapshot_stock_rows"].distinct(
                "code", {"datasetId": dataset_id, "snapshotId": sid}):
            today_seen.setdefault(code, set()).add(s)
    picked = []
    excluded: dict[str, int] = {}
    for code, r in ctx["cur"].items():
        chg = r.get("change")
        if not isinstance(chg, (int, float)) or r.get("zlje") is None or r.get("zljzb") is None:
            excluded["mainforce_missing"] = excluded.get("mainforce_missing", 0) + 1
            continue
        if len(today_seen.get(code, set())) < 4:
            excluded["slots_lt4"] = excluded.get("slots_lt4", 0) + 1
            continue
        # prev3 日期若不在 series_days 键集（missed-slot 等），按「无法验证连续在榜」排除该股
        if not all(code in by_day_cache.get(dd, set()) for dd in ctx["prev3"]):
            excluded["streak_unverifiable"] = excluded.get("streak_unverifiable", 0) + 1
            continue
        picked.append(code)
    # 排除留痕（AGENTS 4.0）：每日一页汇总文档，不做个股级排除文档（避免爆量）
    try:
        db["hotlist_jev_direction"].replace_one(
            {"_id": f"{d}:{DIRECTION_SLOT}:__population__"},
            {"origin": "direction_gate", "datasetId": dataset_id,
             "tradingDate": d, "slotTime": DIRECTION_SLOT,
             "code": "__population__", "pool": ctx["pool"], "population": len(picked),
             "excluded": excluded,
             "computedAt": _now_iso()}, upsert=True)
    except Exception:
        pass  # 落档失败不影响人口本身（advisory），但 print 保底可见
    return sorted(picked)


# ── 调用与落库 ──────────────────────────────────────────────

def _dispatch_jev(state: str, questions: dict) -> tuple[dict, int]:
    from backend.services.jev.jev_sentiment_compute import _dispatch_jev as impl
    return impl(state, questions)


def _ask(state: str, questions: dict) -> tuple[dict, dict, int]:
    env, ms = _dispatch_jev(state, questions)
    from backend.services.jev.jev_client import parse_jev_response
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    key = next(iter(questions))
    ans = (parsed.get("answers") or {}).get(key) or {}
    out = {"ok": parsed.get("ok"), "choice": ans.get("choice"),
           "confidence": ans.get("confidence"), "probabilities": ans.get("probabilities"),
           "usage": parsed.get("usage"), "errorCode": parsed.get("errorCode"), "latencyMs": ms}
    return out, env, ms


def run_direction_day(db: Any, d: str, *, fire: bool = False,
                      cap: int | None = None, token_fuse: int | None = None,
                      dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """判读一个判读日（单题集 A：1 调用/股）。"""
    col = db["hotlist_jev_direction"]
    qhash = questions_hash(QUESTIONS_A)
    fuse = TOKEN_FUSE if token_fuse is None else token_fuse
    used = 0
    stats = {"ok": 0, "degraded": 0, "error": 0, "skip": 0}
    try:
        ctx = setup_day(db, d, dataset_id)
    except LookupError as e:
        print(f"[direction] {d} {e}")
        return {**stats, "error": str(e)}
    codes = build_direction_population(db, d, ctx, dataset_id)
    if cap:
        codes = codes[:cap]
    print(f"[direction] {d} 池 {ctx['pool']} 人口 {len(codes)} | sentiment "
          f"{ctx['sent'].get('band') if ctx['sent'] else None}")

    def _work(code: str) -> tuple[str, dict, int, int]:
        head, blocks, meta = build_state(db, code, d, ctx, dataset_id)
        rec = {"origin": "direction_gate", "datasetId": dataset_id,
               "tradingDate": d, "slotTime": DIRECTION_SLOT,
               "code": code, "name": ctx["cur"][code].get("name"),
               "ammoVersion": AMMO_VERSION, "questionSetVersion": QUESTION_SET_VERSION,
               "questionSetHash": qhash, "meta": meta,
               "computedAt": _now_iso()}
        state_a = "\n".join([head, *blocks["series"], *blocks["pos"], *blocks["vp"],
                             *blocks["gate"], *blocks["mkt"]])
        a, env_a, _ = _ask(state_a, QUESTIONS_A)
        rec.update({"status": "ok" if a.get("ok") else "degraded",
                    "direction": a.get("choice"), "confidence": a.get("confidence"),
                    "probabilities": a.get("probabilities"),
                    "questionsRaw": QUESTIONS_A, "narrative": state_a,
                    "responseRaw": env_a, "usage": a.get("usage"),
                    "errorCode": a.get("errorCode"), "latencyMs": a.get("latencyMs")})
        tok = sum((a.get("usage") or {}).values())
        return code, rec, 1, tok

    todo = []
    for code in codes:
        _id = f"{d}:{DIRECTION_SLOT}:{code}:DIR"
        if col.find_one({"_id": _id, "status": "ok"}):
            stats["skip"] += 1
            continue
        todo.append(code)
    if not fire:
        for code in todo[:5]:
            print(f"[direction] dry-run {d}:{code}")
        print(f"[direction] dry-run 共 {len(todo)} 例（fire=False 不调用）")
        stats["dry_run_pending"] = len(todo)
        return stats

    def _safe_work(code: str):
        try:
            return _work(code)
        except Exception as exc:  # 单股失败不炸批次（fail-visible 落档）
            return code, {"origin": "direction_gate", "datasetId": dataset_id,
                          "tradingDate": d,
                          "slotTime": DIRECTION_SLOT, "code": code,
                          "ammoVersion": AMMO_VERSION,
                          "questionSetVersion": QUESTION_SET_VERSION,
                          "questionSetHash": qhash,
                          "status": "error", "errorCode": "build_state_failed",
                          "errorDetail": str(exc)[:300],
                          "computedAt": _now_iso()}, 0, 0

    fuse_tripped = False
    for code in todo:
        if used >= fuse:
            print(f"[direction] 熔断：{used} >= {fuse}，剩余 {len(todo) - todo.index(code)} 例未判读")
            fuse_tripped = True
            break
        c, rec, calls, tok = _safe_work(code)
        rec["questionSetHash"] = qhash
        col.replace_one({"_id": f"{d}:{DIRECTION_SLOT}:{c}:DIR"}, rec, upsert=True)
        used += tok
        stats[rec["status"] if rec["status"] in ("ok", "degraded", "error") else "degraded"] += 1
        print(f"[direction] {d} {c} → {rec.get('direction')} conf={rec.get('confidence')} "
              f"tok={tok}(cum={used})")
    stats["tokens"] = used
    if fuse_tripped:
        stats["fuse_tripped"] = True
    print("FINAL[direction]:", stats)
    return stats


def backfill_direction_verify(db: Any, dates: list[str],
                              dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """隔日验证列回填（T+1 最后一槽 change + 判读时点起收益）。盘后链/CLI 调用。"""
    col = db["hotlist_jev_direction"]
    dates_all = _trading_dates_with_slot(db, DIRECTION_SLOT)
    n = 0
    for d in dates:
        idx = dates_all.index(d) if d in dates_all else None
        if idx is None:
            continue
        nd = dates_all[idx + 1] if idx + 1 < len(dates_all) else None
        if not nd:
            continue
        last_slot = max((s for s, _ in _day_slot_frames(db, nd, dataset_id)), default=None)
        if not last_slot:
            continue
        nd_rows = _frame_rows(db, nd, last_slot, dataset_id)
        cur_rows = _frame_rows(db, d, DIRECTION_SLOT, dataset_id)
        for doc in col.find({"tradingDate": d, "verify": {"$exists": False}}):
            code = doc["code"]
            r = nd_rows.get(code)
            if not r:
                continue
            verify = {"next_day_slot": last_slot, "next_day_change": _r2(r.get("change"))}
            cur_price = (cur_rows.get(code) or {}).get("price")
            px = r.get("price")
            if isinstance(px, (int, float)) and isinstance(cur_price, (int, float)) and cur_price:
                verify["ret_since_signal"] = round((px - cur_price) / cur_price * 100, 2)
            col.update_one({"_id": doc["_id"]}, {"$set": {"verify": verify}})
            n += 1
    print(f"[direction] verify 回填 {n} 条（{dates}）")
    return {"backfilled": n}


def fire_token_guard() -> bool:
    """--fire 的 token 预检（纯函数可测）：有 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY 才允许真实调用。"""
    return bool((os.environ.get("JEV_CF_TOKEN") or "").strip()
                or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip())


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI 参数定义（scheduler 子进程命令的兼容性回归测试锚点）。"""
    ap = argparse.ArgumentParser(description="jev direction gate runner (v3-gate)")
    ap.add_argument("--day", required=True)
    ap.add_argument("--fire", action="store_true")
    ap.add_argument("--dry", action="store_true", help="等价 fire=False（零调用）")
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--token-fuse", type=int, default=None)
    ap.add_argument("--verify", action="store_true", help="回填隔日验证列后退出")
    return ap


def _main() -> None:
    args = build_arg_parser().parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    fire = args.fire and not args.dry
    if args.verify:
        backfill_direction_verify(db, [args.day])
        return
    if fire and not fire_token_guard():
        raise SystemExit("--fire 需环境变量 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY")
    out = run_direction_day(db, args.day, fire=fire,
                            cap=args.cap, token_fuse=args.token_fuse)
    if out.get("error"):
        # 整日失败（如 11:00 帧缺失）必须非零退出，否则 scheduler 把失败记成 ok（review R4）
        raise SystemExit(f"direction day failed: {out['error']}")


if __name__ == "__main__":
    _main()
