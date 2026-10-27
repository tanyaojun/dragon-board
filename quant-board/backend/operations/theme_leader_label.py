# -*- coding: utf-8 -*-
"""题材层「板块龙头隔日连板」投喂 runner（2026-10-20，L3 语料落地后的判据层首版）。

定位：每条投喂 = **当日一个板块的龙头**（不是每只涨停股）。目标题（v5 四题）= 题材炒作深度/题材延续性/次日该龙头是否继续
封板，证据 = 结构事实（触板−炸板二分 + 真连板 + 封板时间 + 板块家数 + 跟风/昨日延续）
+ 同桶历史基准率 + 题材证据块（韭研产业树催化原文 + 开盘啦题材事件/新闻/日历）。

花 token 的口子只有一个：`run()` 里的 `_dispatch_jev`；`--dry-run` / `--estimate` 全程零调用，
用于人工过目「将来真正下发的文本」与成本估算。真实开火必须 `--confirm-budget`
（AGENTS §1.2-7：真实调用只走预登记 + 预算确认路径）。

存储：`hotlist_jev_theme_leader_labels`，`_id={date}:{code}`（一个龙头一股一条）。
与驱动链（`hotlist_jev_driver_labels`）**分集合存放**：题集/判据代际不同，跨集混读会掩盖代际漂移。

用法：
  # 零 token：看当天会投喂哪些龙头、文本长什么样、大概烧多少 token
  ./.venv/Scripts/python.exe -m backend.operations.theme_leader_label --date 2026-10-20 --dry-run
  # 真开火（需预算批准）
  ./.venv/Scripts/python.exe -m backend.operations.theme_leader_label --date 2026-10-20 --confirm-budget
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_event_digest as digest
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.theme_leader_ammo import (
    AMMO_VERSION_THEME_LEADER,
    QUESTION_SET_HASH_THEME_LEADER,
    QUESTION_SET_VERSION_THEME_LEADER,
    QUESTIONS_THEME_LEADER,
    THEME_LEADER_KEYS,
    apply_evidence_gate,
    baseline_line,
    board_ladder_line,
    board_zhaban_line,
    build_leader_narrative,
    combo_key,
    headroom_anchor_line,
    structure_line,
)
from backend.operations.theme_leader_baseline import (
    board_count_history, build_rows, day_leader_rows)
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

COLLECTION = "hotlist_jev_theme_leader_labels"
ORIGIN = "theme_leader_label_v1"
# 代际来源：`live` = 当日 16:20 挂链（前瞻样本）；`backfill` = 事后补跑历史日。
# **评估必须分开统计**：事后补跑的日子可能看到「当时还不存在」的语料（如题材料只在 10-20 采集），
# 混进前瞻样本会把泄漏当成模型能力（预登记 §11 H1 回填方案）。
SAMPLE_ORIGIN_LIVE = "live"
SAMPLE_ORIGIN_BACKFILL = "backfill"
# 结构基线回看窗（交易日）：50 日≈341 样本（2026-08 实测），足够支撑同桶率；上限防越界读全库。
BASELINE_WINDOW_TRADING_DAYS = 60
BASELINE_MIN_SAMPLES = 8          # 组合桶最小样本（与 ammo.baseline_line 一致）
# S1 板块家数趋势序列回看窗（交易日）：判据「家数扩张中/萎缩」需要形状而非两点
BOARD_HISTORY_DAYS = 5
# 前向交易日轴回看上限（自然日）：找下 2 个交易日足够（最长长假 8 天），防日历源异常时扫到天边
FORWARD_AXIS_SCAN_DAYS = 15
_FWD_AXIS_CACHE: dict[str, str] = {}
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def forward_date_axis_line(date: str, days: int = 2) -> str:
    """前向交易日轴（2026-10-24c）：延续/概率题判据的「未来 1-2 个交易日」跨周末可数。

    题材日历节的 T+n 是日历日差，周五取数时周六事件标 T+1、实际是下周一——「未来 1-2
    个交易日」需要模型自己查日历。本行直接给出下 1/下 2 个交易日与星期。日历源走
    `is_trading_day_cached` 三级降级（bridge→本地缓存→星期启发），非 bridge 源显式标注
    「节假日顺延未经验证」（fail-visible：weekday 启发会把长假当交易日）；全程找不到
    （异常）→「不可算」，不猜。
    """
    import datetime as _dt

    from backend.snapshot_collector.trading_calendar import is_trading_day_cached

    if date in _FWD_AXIS_CACHE:
        return _FWD_AXIS_CACHE[date]
    try:
        cur = _dt.date.fromisoformat(str(date))
    except ValueError:
        line = "交易日轴（前向）：不可算（日期非法，fail-visible）"
        _FWD_AXIS_CACHE[date] = line
        return line
    found: list[str] = []
    srcs: set[str] = set()
    for _ in range(FORWARD_AXIS_SCAN_DAYS):
        cur += _dt.timedelta(days=1)
        try:
            ok, src = is_trading_day_cached(cur)
        except Exception:
            break
        srcs.add(str(src))
        if ok:
            wd = _WEEKDAY_CN[cur.weekday()]
            label = "下一交易日" if len(found) == 0 else "下下交易日"
            found.append(f"{label} {cur.isoformat()}（{wd}）")
            if len(found) >= days:
                break
    if found:
        line = "交易日轴（前向）：" + " · ".join(found)
        if srcs - {"bridge"}:
            # 2026-10-24d review 处置：非 bridge 源结果**不缓存**——bridge 恢复后重算即升级，
            # 缓存会把 weekday 启发行固化整天；重算成本 ≤15 次缓存查表，不值得换质量损失
            line += f"（日历源 {'/'.join(sorted(srcs))}，节假日顺延未经验证）"
        else:
            _FWD_AXIS_CACHE[date] = line
    else:
        line = "交易日轴（前向）：不可算（日历源异常，fail-visible）"
    return line
# 字符→token 估算（中文叙事实测经验）。**护栏必须是真的上界**，故低/高界各有一组
# 「固定开销 + 每字符」参数，任一组都不得低于观测值。
#
# 校准账（22 次真实调用：2026-10-19 v1 13 次 + 2026-10-20 v2 9 次，逐条从库里
# `narrative` 长度 × `usage.input_tokens/output_tokens` 反推）：
#   拟合 total ≈ 1,386 + 0.894 × chars（v2 子样本：1,422 + 0.905 × chars）；
#   output 恒 ~143 tokens；观测区间：chars 715→2,068，chars 1,463→2,681。
#   历史教训：第一版固定开销 900（估算 24,460 vs 实耗 29,014，-16%）→ 改 1,250
#   仍低估（10-20：估算 19,483 vs 实耗 20,237，-3.9%）。**按「护栏是上界」重新定标**：
#   上界 = 1,700 + 1.05×chars（对 22 条全部覆盖，余量 +18~21%）；下界 = 1,300 + 0.80×chars。
# v5 题集 2→4 题（深度/延续性/概率/空间）：输出随题数增长，固定开销按比例上调。
# v6 题面加长（insufficient 边界收紧措辞，instructions 增 ~400 字）：2026-10-23 v6 首批
# 实测单条 residual（usage−1.05×chars）最高 2,682 > 旧 2,500，护栏低估 4%（§10.5 缺陷，
# 实测 25,381 > 护栏 24,390）——上调至 2,750 复标（test_budget_guard_* 钉住）。
TOKENS_PER_CHAR_LOW, TOKENS_PER_CHAR_HIGH = 0.80, 1.05
TOKENS_FIXED_LOW = 1800
TOKENS_FIXED_HIGH = 2750
# 连续 N 次「失败且零 usage」→ 判通道不可达并中止（单次抖动仍继续，不误杀）
_TRANSPORT_FAIL_ABORT = 2


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


def trading_dates_before(db: Any, date: str, n: int,
                         dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """date 之前 n 个交易日（升序，不含 date）。复用韭研 final 文档日轴（与承接链同源）。"""
    rows = db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$lt": date}, "_id": {"$regex": ":final$"}},
        {"tradingDate": 1})
    dates = sorted({str(d["tradingDate"]) for d in rows if d.get("tradingDate")})
    return dates[-n:] if n > 0 else dates


def baseline_rows_for(db: Any, date: str,
                      window: int = BASELINE_WINDOW_TRADING_DAYS,
                      dataset_id: str = DEFAULT_DATASET_ID) -> tuple[list[dict], dict]:
    """截至 date 前一个交易日的结构基线样本（含 outcome），供同桶基准率使用。

    **不含当日**：当日结局未知，把当日样本混进基准率会自证（look-ahead 泄漏）。
    """
    prev_dates = trading_dates_before(db, date, window, dataset_id)
    if not prev_dates:
        return [], {"start": None, "end": None, "rows": 0, "reason": "no_history"}
    # end 取 `date` 本身：build_rows 只对 `dates[:-1]` 出样本，以 date 为右边界才能把
    # 「date 的前一交易日」龙头样本收进来（其结局=今日是否仍封板，label 时点已可知，非泄漏）。
    out = build_rows(db, prev_dates[0], date, dataset_id)
    return out["rows"], {"start": prev_dates[0], "end": prev_dates[-1],
                         "rows": len(out["rows"]), "skipped": out["skipped"]}


def leaders_for(db: Any, date: str,
                dataset_id: str = DEFAULT_DATASET_ID) -> tuple[list[dict] | None, dict]:
    """当日各板块龙头结构事实行；None = 当日 THS 池缺失（不可二分，fail-visible）。

    2026-10-27 空间龙一规则（用户裁决，预登记 §21.6）：space_mode=True + 近 3 个交易日
    封板池并入候选（断板反包入口，如 10-26 大业），排序=10日涨幅→连板高度→首封；
    基线/历史窗口仍走默认 streak 口径（样本人群不随规则换代漂移）。
    """
    prev_dates = trading_dates_before(db, date, 3, dataset_id)
    return day_leader_rows(db, date, dataset_id,
                           prev_date=prev_dates[-1] if prev_dates else None,
                           space_mode=True, pool_dates=prev_dates)


def reconcile_superseded_leaders(db: Any, date: str, rows: list[dict] | None) -> dict:
    """单一龙头不变式对账（2026-10-24 双龙头事故后加）：同 (date, board) 只留现任推导龙一。

    成因：15:35 final 快照与盘后重采之间推导会变（韭研盘后修正板数/分组），8001 重启
    触发幂等重跑补标新任龙头（如 10-23 大业股份）后，旧任龙头行（赛福天）无人退位，
    双行并存冒充双龙头。对账把同 board 下 code∉现任 的历史行显式退位（leaderSuperseded/
    supersededBy/supersededAt），**不删除**（真实调用成本留审计，Mongo 可查）；
    幂等（已退位且 supersededBy 相同则不重盖）。rows=None/空（THS 池缺失推导不可得）
    → 不动历史（fail-visible，不猜现任）。
    """
    if not rows:
        return {"superseded": 0, "boards": 0, "details": []}
    col = db[COLLECTION]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    boards = {str(r["board"]) for r in rows}
    details: list[dict] = []
    total = 0
    for board in sorted(boards):
        current_codes = sorted({str(r["code"]) for r in rows if str(r["board"]) == board})
        res = col.update_many(
            {"tradingDate": date, "board": board, "code": {"$nin": current_codes},
             "status": {"$in": ["ok", "degraded"]}, "leaderSuperseded": {"$ne": True}},
            {"$set": {"leaderSuperseded": True, "supersededBy": current_codes[0],
                      "supersededAt": now}})
        if res.modified_count:
            total += res.modified_count
            details.append({"board": board, "currentLeader": current_codes[0],
                            "superseded": res.modified_count})
    if total:
        print(f"{date} 龙头对账：退位 {total} 行（推导已不再指向；"
              f"{'；'.join(d['board'] + '→' + d['currentLeader'] for d in details)}）")
    return {"superseded": total, "boards": len(boards), "details": details}


def build_one(db: Any, date: str, row: dict, rows_baseline: list[dict],
              dataset_id: str = DEFAULT_DATASET_ID,
              market_line: str | None = None,
              board_history: dict[str, list[tuple[str, int]]] | None = None) -> dict:
    """组装一条投喂（叙事 + 附带元数据），零网络零模型。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    if market_line is None:
        market_line = market_facts_line(db, date, dataset_id)
    # boardCodes 缺失/为空时传 None（空集会把 L2 全过滤掉，属危险默认；显式回退全量口径+披露）
    sealed = frozenset(row.get("boardCodes") or ())
    block = digest.build_theme_evidence_block(db, board_name=row["board"], date=date,
                                              leader_code=str(row.get("code") or ""),
                                              sealed_codes=sealed or None)
    narrative = build_leader_narrative(
        date=date,
        market_line=market_line,
        forward_axis=forward_date_axis_line(date),
        structure=structure_line(
            board=row["board"], board_n=row["boardN"], leader=row,
            followers_ge_ladder=row["ladderFollowers"], prev_board_n=row.get("prevBoardN"),
            prev_peers=row.get("prevPeers"), prev_total=row.get("prevTotal"),
            prev_still=row.get("prevStill"),
            history=board_history.get(row["board"], []) if board_history is not None else None,
            leader_sealed_today=row.get("leaderSealedToday"),
            gain10=row.get("gain10")),
        ladder_line=board_ladder_line(row),
        zhaban_line=board_zhaban_line(row),
        baseline=baseline_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        headroom=headroom_anchor_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        evidence_block=block["text"],
        leader_name=str(row.get("name") or ""),
        leader_code=str(row.get("code") or ""),
    )
    return {"narrative": narrative, "evidence": block,
            "chars": len(narrative),
            "estimatedTokens": estimate_tokens(len(narrative))}


def estimate_tokens(chars: int) -> dict:
    """字符 → token 估算（区间 + 护栏用上界）。非真 tokenizer，仅用于预算护栏与排序。"""
    low = int(chars * TOKENS_PER_CHAR_LOW) + TOKENS_FIXED_LOW
    high = int(chars * TOKENS_PER_CHAR_HIGH) + TOKENS_FIXED_HIGH
    return {"low": low, "high": high, "budgetGuard": high}


def _label_one(db, col, date: str, row: dict, built: dict,
               baseline_meta: dict,
               sample_origin: str = SAMPLE_ORIGIN_LIVE) -> tuple[bool, int]:
    """单条真实 jev 调用（唯一花 token 的路径）。返回 (ok, tokens)。"""
    narrative, questions = built["narrative"], QUESTIONS_THEME_LEADER
    env, ms = _dispatch_jev(narrative, questions)
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    raw_answers = parsed.get("answers") or {}
    # v2 确定性门（v5 起四题全门）：证据缺失（语料未采集/板块未映射/无正文且无事件）→ 判定题强制 insufficient，
    # 模型原答原样存 `modelAnswers`/`gate`（不丢真实输出；避免"无证据"与"模型上调"混在一批数字里）。
    # 只在调用成功时过门：调用 degraded（无答案）走原路径，不得把"没答上来"写成 insufficient。
    answers, gate = apply_evidence_gate(raw_answers, built.get("evidence") or {})         if parsed["ok"] else (raw_answers, {"applied": False, "reason": None})
    cont = answers.get("leader_nextday_continue") or {}
    depth = answers.get("theme_speculation_depth") or {}
    contn = answers.get("theme_continuation") or {}
    head = answers.get("leader_headroom") or {}
    doc = {
        "_id": f"{date}:{row['code']}", "origin": ORIGIN, "tradingDate": date,
        "code": row["code"], "name": row.get("name"), "board": row["board"],
        "ammoVersion": AMMO_VERSION_THEME_LEADER,
        "questionSetVersion": QUESTION_SET_VERSION_THEME_LEADER,
        "questionSetHash": QUESTION_SET_HASH_THEME_LEADER,
        "structure": {k: row.get(k) for k in (
            "streak", "time", "boardN", "othersN", "ladderFollowers", "prevPeers",
            "prevBoardN", "prevTotal", "prevStill", "zhabanN", "prevZhabanN", "ladderShape",
            "secondStreak",
            # 2026-10-27 空间龙一规则：10日涨幅 + 未封板标记（断板反包候选）
            "gain10", "leaderSealedToday")},
        "baselineBucket": json.dumps({k: row.get(k) for k in ("streak", "boardN", "time")},
                                     ensure_ascii=False, sort_keys=True),
        # 真实的同桶查键（"streak3|n5-7|early<=10:00"）：评估时直接用，不必再从结构重算；
        # `baselineBucket` 只是原始结构审计字段，两者别混（混用会静默退化成只按连板高度对照）。
        "baselineKey": combo_key(row),
        "baselineMeta": baseline_meta,
        "evidenceState": built["evidence"]["state"],
        "evidenceIndustry": (built["evidence"].get("industry") or {}).get("name"),
        "evidenceEventTitles": [e.get("title") for e in built["evidence"].get("events") or []],
        # v3/v4：L2 板内解析可用性 + Kword 题材标签（开盘啦新闻流），前端分层展示用
        "evidenceBoardResolved": bool(built["evidence"].get("boardResolved")),
        "evidenceKwordTags": list(built["evidence"].get("kwordTags") or []),
        "evidenceMissing": bool((built.get("evidence") or {}).get("evidenceMissing")),
        "evidenceMissingReason": (built.get("evidence") or {}).get("evidenceMissingReason"),
        "narrative": narrative, "questionsRaw": questions,
        "answers": answers,            # 落库口径 = 过门后的答案（消费端单一事实源）
        "modelAnswers": raw_answers,   # 模型原答（审计用；不得被消费端当口径）
        "gate": gate,                  # {applied, reason, label, modelChoice, modelProbabilities}
        "leaderNextdayContinue": cont.get("choice"),
        "leaderNextdayProbabilities": cont.get("probabilities"),
        # v5：题材层三层判断（catalystStage 已被深度题取代；旧代文档仍带 catalystStage 字段）
        "themeSpeculationDepth": depth.get("choice"),
        "themeContinuation": contn.get("choice"),
        "leaderHeadroom": head.get("choice"),
        "status": "ok" if parsed["ok"] else "degraded",
        "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
        "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
        "responseRaw": None if parsed["ok"] else env,
        "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")
            + ".%03d" % (int(time.time() * 1000) % 1000),   # 毫秒位：防同秒重跑 F6 误报
        "sampleOrigin": sample_origin,
        # 结局字段故意留空：次日收盘后由评估脚本回填（label 时点不可见，防 look-ahead）。
        # 复跑安全（2026-10-26 用户报障）：replace_one 整文档覆写会把已回填的 outcome*
        # 抹掉（结算自愈要等下一条挂链，页面复跑后立即读不到结局）——重建文档时把旧档
        # outcome* 原样带走（结局是股票事实，与模型答案无关，保留恒正确）。
        "outcomeSealedNextDay": None,
    }
    old = col.find_one({"_id": doc["_id"]}) or {}
    for k, v in old.items():
        if k.startswith("outcome"):
            doc[k] = v
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    from backend.analysis.hotlist.jev_driver_ammo import _usage_tokens
    return bool(parsed["ok"]), _usage_tokens(parsed.get("usage"))


def run(date: str, *, dry_run: bool = False, confirm_budget: bool = False,
        max_leaders: int | None = None, boards: set[str] | None = None,
        force: bool = False, dataset_id: str = DEFAULT_DATASET_ID,
        sample_origin: str = SAMPLE_ORIGIN_LIVE,
        codes: set[str] | None = None, reconcile_only: bool = False) -> dict:
    """当日投喂主流程。dry_run 全程零 jev 调用；reconcile_only 零调用只对账退位。"""
    db = _db()
    rows, meta = leaders_for(db, date, dataset_id)
    if rows is None:
        print(f"{date} 当日 THS 封板池缺失（无法做触板−炸板二分），跳过（fail-visible）")
        return {"ok": False, "date": date, "error": {"code": "ths_pool_missing"}}
    if not rows:
        print(f"{date} 当日无封板板块（韭研 final 文档缺或全炸板），跳过（披露）")
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders"}
    rows = sorted(rows, key=lambda r: (-(r["boardN"]), str(r.get("time") or "99:99")))
    rows_full = list(rows)           # 全量推导行（对账用，不受 codes/boards 过滤影响）
    plan_leaders_total = len(rows)   # 过滤前总数（codes/boards 过滤后 leaders 仅选中数，P2 修复防误读）
    if boards:
        rows = [r for r in rows if r["board"] in boards]
    if codes:
        # 单只重跑（页面【重跑】按钮）：只重建/调用命中的龙头，tokens 成本 ≈1 次调用
        # （2026-10-20 加，配合 POST /theme-leaders/rerun；不过滤会整日重跑烧 30K+）
        rows = [r for r in rows if r["code"] in codes]
    # 行政桶门控（v3 收紧用户 2026-10-22 裁决 + 2026-10-26 收窄）：公告/新股/其他/ST板块
    # **不纳入 jev 判定范围**。v3 原依据=粗分桶门控率 100%、模型 49/49 自判 insufficient；
    # 2026-10-26 用户裁决摘除四个「大X」域桶（大消费/大农业/医药医疗/医疗医药）——真实
    # 题材域，S3 补充映射上线后七桶 evidenceMissing 全 False（前提失效），10-26 大消费
    # 龙头上海九百 4 板（当日最高板）漏判实锤（预登记 §20）。
    # v5 起排除行**不落库不显示**（用户 2026-10-23 裁决：换代后旧字段/空档位行污染前端；
    # 排除事实只留运行日志），库内只有真实判定的 ok/degraded 行。
    excluded = [r for r in rows if digest.normalize_name(r["board"]) in digest.NOT_A_THEME]
    excluded_boards = sorted({r["board"] for r in excluded})
    if excluded:
        print(f"{date} 排除非题材行政桶 {len(excluded)} 只龙头（{'、'.join(excluded_boards)}）"
              f"——不纳入 jev 判定（v3 收紧；v5 起不落库不显示，仅日志留痕）")
        rows = [r for r in rows if digest.normalize_name(r["board"]) not in digest.NOT_A_THEME]
    if reconcile_only:
        # 零调用对账（手工对账历史日/存量幽灵行）：只做退位，不标注不花 token
        rec = reconcile_superseded_leaders(db, date, rows_full)
        return {"ok": True, "date": date, "reconcileOnly": True,
                "leaders": plan_leaders_total, "reconcile": rec}
    rows_baseline, baseline_meta = baseline_rows_for(db, date, dataset_id=dataset_id)
    col = db[COLLECTION]
    done = {str(d.get("code")) for d in col.find(
        {"tradingDate": date, "status": "ok"}, {"code": 1}) if d.get("code")}
    already = [r for r in rows if not force and r["code"] in done]
    todo = [r for r in rows if force or r["code"] not in done]
    if max_leaders is not None and len(todo) > max_leaders:
        print(f"{date} {len(todo)} 只龙头超上限 {max_leaders}，截断（其余记账，fail-visible）")
        todo = todo[:max_leaders]
    # 盘面事实行全日一致：只算一次（否则每股一次全市场取数，N+1 查询）
    from backend.operations.jev_label_jiuyan import market_facts_line
    market_line = market_facts_line(db, date, dataset_id)
    # S1（2026-10-24b）：近 5 日各板块封板家数序列，全日一算（逐日 day_leader_rows，
    # boardN 与结构行同源）；板块名逐日未收录/THS 池缺失日如实留缺口
    board_history = board_count_history(db, date, days=BOARD_HISTORY_DAYS, dataset_id=dataset_id)
    built_all: list[dict] = []
    for row in todo:
        built = build_one(db, date, row, rows_baseline, dataset_id, market_line,
                          board_history=board_history)
        built["row"] = row
        built_all.append(built)
    tokens = sum(b["estimatedTokens"]["budgetGuard"] for b in built_all)
    plan = {"ok": True, "date": date, "leaders": len(rows),
            "leadersTotal": plan_leaders_total, "todo": len(todo),
            "excludedNotTheme": len(excluded), "excludedBoards": excluded_boards,
            "alreadyLabeled": len(already),
            "questionSetVersion": QUESTION_SET_VERSION_THEME_LEADER,
            "questionSetHash": QUESTION_SET_HASH_THEME_LEADER,
            "baselineMeta": baseline_meta,
            "charsTotal": sum(b["chars"] for b in built_all),
            "estimatedTokensBudgetGuard": tokens}
    if dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        for b in built_all:
            print(f"\n===== {b['row']['board']} / {b['row']['name']}（{b['row']['code']}）"
                  f" {b['chars']} 字 ≈ {b['estimatedTokens']['low']}-{b['estimatedTokens']['high']} tokens")
            print(b["narrative"])
        print("\n[dry] 零 jev 调用（未花 token）")
        return plan
    if not todo:
        rec = reconcile_superseded_leaders(db, date, rows_full)
        print(f"{date} 无需投喂（{len(done)} 只已 status=ok，幂等跳过）")
        return {**plan, "labeled": 0, "reconcile": rec}
    if not confirm_budget:
        raise SystemExit(
            f"预算护栏：本次将真实调用 jev {len(todo)} 次（{date}），"
            f"估算 ≤{tokens} tokens（叙事 {plan['charsTotal']} 字，上界口径）。"
            f"确认预算请加 --confirm-budget；先看文本用 --dry-run。")
    n_ok = n_used = transport_fails = 0
    for i, b in enumerate(built_all, 1):
        ok, used = _label_one(db, col, date, b["row"], b, baseline_meta,
                              sample_origin=sample_origin)
        n_ok += 1 if ok else 0
        n_used += used
        print(f"[{i}/{len(built_all)}] {date} {b['row']['board']}/{b['row']['name']}"
              f"({'ok' if ok else 'degraded'}) used={used}")
        # 通道不可达快速中止（2026-10-20 实测：本地代理 127.0.0.1:7890 挂掉 → typesafe 通道
        # 全量 WinError 10061，继续跑只是空转；零 token 消耗但会白跑 + 掩盖故障形状）。
        # 只对「失败且零 usage」的连续两次断——单次抖动仍照旧重试，不误杀。
        transport_fails = transport_fails + 1 if (not ok and used == 0) else 0
        if transport_fails >= _TRANSPORT_FAIL_ABORT:
            rec = reconcile_superseded_leaders(db, date, rows_full)
            return {**plan, "labeled": i, "ok": n_ok, "degraded": i - n_ok,
                    "tokensUsed": n_used, "aborted": "channel_unreachable",
                    "reconcile": rec,
                    "remaining": len(built_all) - i,
                    "error": {"code": "jev_channel_unreachable",
                              "message": f"连续 {transport_fails} 次调用零 usage 失败，已中止；"
                                         "检查 jev 通道（JEV_TYPESAFE_PROXY 代理/CF 令牌）后 --force 重跑"}}
    rec = reconcile_superseded_leaders(db, date, rows_full)
    return {**plan, "labeled": len(built_all), "ok": n_ok,
            "degraded": len(built_all) - n_ok, "tokensUsed": n_used, "reconcile": rec}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm-budget", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-leaders", type=int, default=None)
    ap.add_argument("--boards", default=None, help="逗号分隔，只投喂这些板块")
    ap.add_argument("--codes", default=None,
                    help="逗号分隔，只重跑这些代码（配合 --force 单只重跑）")
    ap.add_argument("--sample-origin", default=SAMPLE_ORIGIN_LIVE,
                    choices=[SAMPLE_ORIGIN_LIVE, SAMPLE_ORIGIN_BACKFILL],
                    help="样本代际：live=当日挂链前瞻（默认）；backfill=事后补跑历史日，"
                         "评估分组统计，不与前瞻混评")
    ap.add_argument("--reconcile-only", action="store_true",
                    help="零调用：只做单一龙头对账（退位推导已不再指向的旧行），不标注")
    args = ap.parse_args()
    out = run(args.date, dry_run=args.dry_run, confirm_budget=args.confirm_budget,
              max_leaders=args.max_leaders, force=args.force,
              sample_origin=args.sample_origin, reconcile_only=args.reconcile_only,
              boards={b.strip() for b in args.boards.split(",") if b.strip()} if args.boards else None,
              codes={c.strip() for c in args.codes.split(",") if c.strip()} if args.codes else None)
    if not args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()