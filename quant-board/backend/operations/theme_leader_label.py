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
    build_leader_narrative,
    combo_key,
    structure_line,
)
from backend.operations.theme_leader_baseline import build_rows, day_leader_rows
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
    """当日各板块龙头结构事实行；None = 当日 THS 池缺失（不可二分，fail-visible）。"""
    prev_dates = trading_dates_before(db, date, 1, dataset_id)
    return day_leader_rows(db, date, dataset_id, prev_dates[-1] if prev_dates else None)


def build_one(db: Any, date: str, row: dict, rows_baseline: list[dict],
              dataset_id: str = DEFAULT_DATASET_ID,
              market_line: str | None = None) -> dict:
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
        structure=structure_line(
            board=row["board"], board_n=row["boardN"], leader=row,
            followers_ge_ladder=row["ladderFollowers"], prev_board_n=row.get("prevBoardN"),
            prev_peers=row.get("prevPeers")),
        baseline=baseline_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
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
            "streak", "time", "boardN", "othersN", "ladderFollowers", "prevPeers", "prevBoardN")},
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
        # 结局字段故意留空：次日收盘后由评估脚本回填（label 时点不可见，防 look-ahead）
        "outcomeSealedNextDay": None,
    }
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    from backend.analysis.hotlist.jev_driver_ammo import _usage_tokens
    return bool(parsed["ok"]), _usage_tokens(parsed.get("usage"))


def run(date: str, *, dry_run: bool = False, confirm_budget: bool = False,
        max_leaders: int | None = None, boards: set[str] | None = None,
        force: bool = False, dataset_id: str = DEFAULT_DATASET_ID,
        sample_origin: str = SAMPLE_ORIGIN_LIVE,
        codes: set[str] | None = None) -> dict:
    """当日投喂主流程。dry_run 全程零 jev 调用。"""
    db = _db()
    rows, meta = leaders_for(db, date, dataset_id)
    if rows is None:
        print(f"{date} 当日 THS 封板池缺失（无法做触板−炸板二分），跳过（fail-visible）")
        return {"ok": False, "date": date, "error": {"code": "ths_pool_missing"}}
    if not rows:
        print(f"{date} 当日无封板板块（韭研 final 文档缺或全炸板），跳过（披露）")
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders"}
    rows = sorted(rows, key=lambda r: (-(r["boardN"]), str(r.get("time") or "99:99")))
    plan_leaders_total = len(rows)   # 过滤前总数（codes/boards 过滤后 leaders 仅选中数，P2 修复防误读）
    if boards:
        rows = [r for r in rows if r["board"] in boards]
    if codes:
        # 单只重跑（页面【重跑】按钮）：只重建/调用命中的龙头，tokens 成本 ≈1 次调用
        # （2026-10-20 加，配合 POST /theme-leaders/rerun；不过滤会整日重跑烧 30K+）
        rows = [r for r in rows if r["code"] in codes]
    # v3 门控收紧（用户 2026-10-22 裁决）：非题材粗分桶（公告/其他/新股/大消费/大农业/
    # 医药医疗/医疗医药…）**不纳入 jev 判定范围**。归因实测：这些桶门控率 100%、
    # 模型原答 49/49 自判 insufficient（均值 1.00）——调用纯属浪费 token。
    # v5 起排除行**不落库不显示**（用户 2026-10-23 裁决：换代后旧字段/空档位行污染前端；
    # 排除事实只留运行日志），库内只有真实判定的 ok/degraded 行。
    excluded = [r for r in rows if digest.normalize_name(r["board"]) in digest.NOT_A_THEME]
    excluded_boards = sorted({r["board"] for r in excluded})
    if excluded:
        print(f"{date} 排除非题材粗分桶 {len(excluded)} 只龙头（{'、'.join(excluded_boards)}）"
              f"——不纳入 jev 判定（v3 收紧；v5 起不落库不显示，仅日志留痕）")
        rows = [r for r in rows if digest.normalize_name(r["board"]) not in digest.NOT_A_THEME]
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
    built_all: list[dict] = []
    for row in todo:
        built = build_one(db, date, row, rows_baseline, dataset_id, market_line)
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
        print(f"{date} 无需投喂（{len(done)} 只已 status=ok，幂等跳过）")
        return {**plan, "labeled": 0}
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
            return {**plan, "labeled": i, "ok": n_ok, "degraded": i - n_ok,
                    "tokensUsed": n_used, "aborted": "channel_unreachable",
                    "remaining": len(built_all) - i,
                    "error": {"code": "jev_channel_unreachable",
                              "message": f"连续 {transport_fails} 次调用零 usage 失败，已中止；"
                                         "检查 jev 通道（JEV_TYPESAFE_PROXY 代理/CF 令牌）后 --force 重跑"}}
    return {**plan, "labeled": len(built_all), "ok": n_ok,
            "degraded": len(built_all) - n_ok, "tokensUsed": n_used}


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
    args = ap.parse_args()
    out = run(args.date, dry_run=args.dry_run, confirm_budget=args.confirm_budget,
              max_leaders=args.max_leaders, force=args.force,
              sample_origin=args.sample_origin,
              boards={b.strip() for b in args.boards.split(",") if b.strip()} if args.boards else None,
              codes={c.strip() for c in args.codes.split(",") if c.strip()} if args.codes else None)
    if not args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()