# -*- coding: utf-8 -*-
"""复盘日报（jev daily recap）：两页复盘事实 + 情绪锚点 → 单 call 语料包 → 归层 → 模板成文 → 落库。

设计/预登记：quant-board/docs/hotlist-jev/jev-daily-recap-design.md（2026-10-31 用户裁决）。
- 语料拼装/题目/模板/机械判全部在 services/jev/jev_daily_recap_corpus（单一实现，本模块零重复）；
- 两页复盘均 noData → 不出语料包不烧 jev（贫料不开火，errorCode=no_material）；
- dry（缺省）零真调用零写库（skippedJev=true，答案=机械判）；--apply 才真调用+upsert；
- 幂等：当日 ok 文档已存在自动跳过（--force 重算）；排程链接线在 pilot 门判通过后另行提交；
- pytest 一律 mock call_jev/FakeDb，禁真调用（硬红线 §1.2#7）。

用法（quant-board 目录；pilot 期人工开火记账）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_daily_recap --date 2026-10-31 [--apply] [--force]
  ./.venv/Scripts/python.exe -m backend.operations.jev_daily_recap --start 2026-10-20 --end 2026-10-31 [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import band_of_score
from backend.operations.jev_daily_line import (
    QUESTION_SET_VERSION_DAILY_LINE,
    _jev_credentials,
    eod_percentile,
)
from backend.operations.phase_pulse import PULSE_BAND_LABELS, load_eod_scores
from backend.services.jev import jev_daily_recap_corpus as corpus
from backend.services.jev.jev_client import dispatch_jev_call, parse_jev_response
from backend.services.jev.jev_dieban_review import collect_dieban_review
from backend.services.jev.jev_rise_review import collect_rise_review
from backend.operations.jev_relay_index import _promotion_stats
from backend.operations.theme_leader_label import (
    LIVE_ARCHIVE_COLLECTION,
    _AI_GEN_NOTE,
    _MARKET_WRAP_RE,
)

COLLECTION = "hotlist_jev_daily_recap"

# 题目集 v2（2026-10-31 用户裁决）：4 道计划题；环境题删（EOD/连板情绪链已回答），
# 主攻方向由语料层机械派生（corpus.derive_focus_direction）
_QUESTION_KEYS = ("plan_bias", "play_style", "avoid_focus", "key_watch")


# ---------------------------------------------------------------- 语料 v2 增补（2026-10-31 用户裁决）

KPL_WRAP_TIME = "15:00"          # 收盘大盘综述播报时点
RELAY_COLLECTION = "hotlist_jev_relay_index"


def load_kpl_wrap(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """KPL 直播 15:00 大盘综述（kpl_live_daily 日归档，17:30 挂链落库；零模型调用）。

    归档缺/当日无综述条 → ok:false + degraded 登记（fail-visible，不拿其他时点冒充综述）。
    原文剔除 AI 生成标注尾注后原样入语料（不做任何改写）。
    """
    degraded: list[dict[str, str]] = []
    try:
        doc = db[LIVE_ARCHIVE_COLLECTION].find_one({"_id": str(date)}) or {}
    except Exception as exc:  # noqa: BLE001 — 归档读失败显式降级
        return {"ok": False, "reason": f"archive_read_failed: {exc}"}, [
            {"source": "kpl_wrap", "reason": f"archive_read_failed: {exc}", "action": "corpus_absent"}]
    items = doc.get("items") or []
    hits = [str(it.get("comment") or "").strip() for it in items
            if str(it.get("time") or "") == KPL_WRAP_TIME and _MARKET_WRAP_RE.search(str(it.get("comment") or ""))]
    if not hits:
        reason = "archive_missing" if not items else f"no_{KPL_WRAP_TIME}_wrap_in_archive"
        degraded.append({"source": "kpl_wrap", "reason": reason, "action": "corpus_absent"})
        return {"ok": False, "reason": reason}, degraded
    comment = hits[-1]
    if comment.endswith(_AI_GEN_NOTE):
        comment = comment[: -len(_AI_GEN_NOTE)].rstrip()
    return {"ok": True, "time": KPL_WRAP_TIME, "comment": comment,
            "fromArchive": True}, degraded


def load_relay_judgment(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """连板情绪判定结果（hotlist_jev_relay_index，_id={date}:RELAY；只读引用不重算不建第二事实源）。

    只喂结构化档位（指数/相位/边际/梯队/钱效/题材/龙头强度），不喂模型生成的 narrative 原文
    （防模型输出回流污染语料）。缺档/非 ok → ok:false + degraded。
    """
    degraded: list[dict[str, str]] = []
    try:
        doc = db[RELAY_COLLECTION].find_one({"_id": f"{date}:RELAY"}) or {}
    except Exception as exc:  # noqa: BLE001 — 读失败显式降级
        return {"ok": False, "reason": f"relay_read_failed: {exc}"}, [
            {"source": "relay_judgment", "reason": f"relay_read_failed: {exc}", "action": "corpus_absent"}]
    if doc.get("status") != "ok":
        reason = "relay_doc_missing" if not doc else f"relay_status_{doc.get('status')}"
        degraded.append({"source": "relay_judgment", "reason": reason, "action": "corpus_absent"})
        return {"ok": False, "reason": reason}, degraded
    answers = doc.get("answers") or {}
    picked: dict[str, Any] = {}
    for key in ("relay_phase", "relay_momentum", "ladder_health",
                "money_effect", "theme_pulse"):
        a = answers.get(key) or {}
        picked[key] = a.get("choice")
    leader = answers.get("leader_strength") or {}
    idx_score = answers.get("relay_index") or {}
    return {"ok": True,
            "index": doc.get("relayIndex"),
            "indexScore": idx_score.get("score"),
            "answers": picked,
            "leaderStrengthScore": leader.get("score"),
            "questionSetVersion": doc.get("questionSetVersion")}, degraded


# ---------------------------------------------------------------- 数据装载（monkeypatch 边界）

def _get_db() -> Any:
    from backend.data.repositories import repository_factory

    return repository_factory.get_runtime_mongodb_database()


def load_emotion(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """情绪链锚点（只读引用，不重算不建第二事实源）：EOD/分位/带/daily_line 句与形态。"""
    degraded: list[dict[str, str]] = []
    eod_scores = load_eod_scores(date)
    eod = eod_scores.get(date)
    eod = eod if isinstance(eod, (int, float)) and not isinstance(eod, bool) else None
    if eod is None:
        degraded.append({"source": "emotion", "reason": "missing_eod_score", "action": "anchor_absent"})
    prior = [(d, s) for d, s in sorted(eod_scores.items())
             if d < date and isinstance(s, (int, float)) and not isinstance(s, bool)]
    raw_prior = sum(1 for d in eod_scores if d < date)
    if raw_prior > len(prior):
        degraded.append({"source": "emotion", "reason": f"prior_eod_none_dropped: {raw_prior - len(prior)}",
                         "action": "excluded_from_percentile"})
    pct = eod_percentile([s for _, s in prior[-20:]], eod) if (eod is not None and prior) else None
    if eod is not None and pct is None:
        degraded.append({"source": "emotion", "reason": "eod20d_sample_small", "action": "percentile_unavailable"})
    band_tag = band_of_score(eod) if eod is not None else None
    line_doc = None
    try:
        line_doc = db["phase_monitor"].find_one({"_id": f"line:{date}"}) if eod is not None else None
    except Exception:  # noqa: BLE001 — advisory 参照缺失不阻断日报
        line_doc = None
    line_parts = ((line_doc or {}).get("parts") or {})
    if line_doc is None and eod is not None:
        degraded.append({"source": "emotion", "reason": "daily_line_doc_missing", "action": "sentence_absent"})
    return {
        "eod": eod,
        "prevEod": prior[-1][1] if prior else None,
        "prevEodDate": prior[-1][0] if prior else None,
        "eod20dPercentile": pct,
        "bandTag": band_tag,
        "bandLabel": PULSE_BAND_LABELS[band_tag][0] if band_tag else None,
        "dailyLineSentence": (line_doc or {}).get("sentence"),
        "dailyShape": line_parts.get("shape"),
        "dailyLineTemplateVersion": (line_doc or {}).get("meta", {}).get("templateVersion"),
        "dailyLineQuestionSetVersion": QUESTION_SET_VERSION_DAILY_LINE,
    }, degraded


# ---------------------------------------------------------------- 主流程

def load_eod_judge(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """EOD 情绪结构化判定（hotlist_sentiment half_hour EOD 档，与 load_eod_scores 同源自洽）。

    注意：库内另存在 snapshotType=daily 聚合档（10-30：score 50.8/stage 启动），与 half_hour
    EOD 档（43.0/退潮）口径不一致——已知边界登记设计文档 §10 待专查；本 loader 取 half_hour
    EOD（与 emotion.eod 同源，避免语料内自相矛盾）。
    """
    try:
        doc = db["hotlist_sentiment"].find_one(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
             "slotTime": "EOD", "tradingDate": str(date)}) or {}
    except Exception as exc:  # noqa: BLE001 — 读失败显式降级
        return {"ok": False, "reason": f"eod_read_failed: {exc}"}, [
            {"source": "eod_judge", "reason": f"eod_read_failed: {exc}", "action": "corpus_absent"}]
    if not doc:
        degraded = [{"source": "eod_judge", "reason": "eod_doc_missing", "action": "corpus_absent"}]
        return {"ok": False, "reason": "eod_doc_missing"}, degraded
    score = (doc.get("emotionScore") or {}).get("score")
    return {"ok": True, "score": score, "stage": doc.get("stage"),
            "riskLevel": doc.get("riskLevel")}, []


def load_theme_boards(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """题材龙头方向块（hotlist_jev_theme_leader_labels 板块级 doc，延续性/投机阶段档位）。

    进攻/回避名单由消费方机械派生（strong_extend→进攻候选；ending→回避候选），loader 只读档。
    全天无板块档（链未跑/当日无题材）→ ok:false + degraded，不伪造空名单。
    """
    try:
        docs = list(db["hotlist_jev_theme_leader_labels"].find(
            {"tradingDate": str(date), "docKind": "sector"}))
    except Exception as exc:  # noqa: BLE001 — 读失败显式降级
        return {"ok": False, "reason": f"theme_read_failed: {exc}"}, [
            {"source": "theme_boards", "reason": f"theme_read_failed: {exc}", "action": "corpus_absent"}]
    if not docs:
        degraded = [{"source": "theme_boards", "reason": "theme_sector_docs_missing",
                     "action": "corpus_absent"}]
        return {"ok": False, "reason": "theme_sector_docs_missing"}, degraded
    boards = []
    for d in docs:
        a = d.get("answers") or {}
        boards.append({
            "board": d.get("board"),
            "continuation": (a.get("theme_continuation") or {}).get("choice"),
            "depth": (a.get("theme_speculation_depth") or {}).get("choice"),
        })
    boards.sort(key=lambda b: str(b.get("board") or ""))
    return {"ok": True, "boards": boards}, []


def load_market_amount(db: Any, date: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """量能锚点：优先全市场口径（market_daily_amount 参考集合，TDX 综指单源），
    参考集合缺日/读失败 → 回退池内口径（EOD 档 metrics.comparison 今日/昨日合计，同口径对比）。

    回退带 caliber 标注（market/pool）：10-30 实测两口径方向可能相反（池内 -2% vs
    全市场 +7.6%，池成分换手导致）——判据语义（量能维持=change1d<0）两口径通用，
    但投喂必须让模型知道口径。
    """
    try:
        from backend.services.jev.jev_sentiment_compute import load_market_daily_amount_map

        amount_map = load_market_daily_amount_map(db)
        if str(date) in amount_map:
            prior = [d for d in amount_map if d < str(date)]
            if prior:
                prev_date = max(prior)
                today, yesterday = amount_map[str(date)], amount_map[prev_date]
                change1d = round((today / yesterday - 1) * 100, 2) if yesterday else None
                return ({"ok": True, "caliber": "market", "todayTurnover": today,
                         "yesterdayTurnover": yesterday, "change1d": change1d,
                         "prevDate": prev_date}, [])
    except Exception:  # noqa: BLE001 — 全市场口径不可用静默回退池内（degraded 由池内分支登记）
        pass
    try:
        doc = db["hotlist_sentiment"].find_one(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
             "slotTime": "EOD", "tradingDate": str(date)}) or {}
    except Exception as exc:  # noqa: BLE001 — 读失败显式降级
        return {"ok": False, "reason": f"amount_read_failed: {exc}"}, [
            {"source": "market_amount", "reason": f"amount_read_failed: {exc}", "action": "corpus_absent"}]
    cmp_ = ((doc.get("metrics") or {}).get("comparison") or {})
    today = (cmp_.get("today") or {}).get("totalTurnover")
    yesterday = (cmp_.get("yesterday") or {}).get("totalTurnover")
    if today is None:
        degraded = [{"source": "market_amount", "reason": "turnover_missing",
                     "action": "corpus_absent"}]
        return {"ok": False, "reason": "turnover_missing"}, degraded
    return {"ok": True, "caliber": "pool", "todayTurnover": today, "yesterdayTurnover": yesterday,
            "change1d": cmp_.get("totalChange1d"),
            "mainNetAmount": (cmp_.get("today") or {}).get("mainNetAmount")}, []


def load_promotion(db: Any, date: str, prev_date: str | None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """晋级率锚点（复用连板情绪链 _promotion_stats 单一算式：昨日封板池→今日晋级/断板）。

    只喂数值不喂代码名单（token 纪律）；prev_date 缺（如首日/停市日）→ 显式降级不硬算。
    """
    if not prev_date:
        degraded = [{"source": "promotion", "reason": "prev_trading_date_unknown",
                     "action": "corpus_absent"}]
        return {"ok": False, "reason": "prev_trading_date_unknown"}, degraded
    try:
        stats = _promotion_stats(db, prev_date, str(date), "dragonboard_live")
    except Exception as exc:  # noqa: BLE001 — 算式异常显式降级
        return {"ok": False, "reason": f"promotion_failed: {exc}"}, [
            {"source": "promotion", "reason": f"promotion_failed: {exc}", "action": "corpus_absent"}]
    if stats.get("ok") is not True:
        degraded = [{"source": "promotion", "reason": f"promotion_unavailable: {stats.get('reason')}",
                     "action": "corpus_absent"}]
        return {"ok": False, "reason": f"promotion_unavailable: {stats.get('reason')}"}, degraded
    return {"ok": True, "rate": stats.get("rate"), "baseCount": len(stats.get("base") or []),
            "promotedCount": len(stats.get("promoted") or []),
            "brokenCount": len(stats.get("broken") or []),
            "denom": stats.get("denom")}, []


def run_daily_recap_for_date(date: str, *, apply: bool = False,
                             force: bool = False, db: Any = None) -> dict[str, Any]:
    """产出当日复盘日报。apply=False：零 jev 调用零写库（机械判答案，skippedJev 标注）。"""
    db = db if db is not None else _get_db()

    if apply and not force:
        try:
            existing = db[COLLECTION].find_one({"_id": date, "ok": True})
        except Exception:  # noqa: BLE001 — 幂等检查失败不阻断（靠 upsert 幂等兜底）
            existing = None
        if existing is not None:
            return {"ok": True, "skipped": True, "reason": "already_ok_doc",
                    "date": date, "persistedId": existing.get("_id")}

    rise = collect_rise_review(db, date)
    dieban = collect_dieban_review(db, date)
    facts = corpus.collect_review_facts(rise, dieban)
    if facts["rise"]["noData"] and facts["dieban"]["noData"]:
        return {"ok": False, "errorCode": "no_material",
                "message": (f"{date} 上涨/下跌复盘原料均缺失（贫料不开火：不出语料包不烧 jev；"
                            f"fail-visible，不伪造），见 degraded"),
                "degradedSources": facts["degradedSources"]}

    emotion, emotion_degraded = load_emotion(db, date)
    kpl_wrap, kpl_degraded = load_kpl_wrap(db, date)
    relay_judgment, relay_degraded = load_relay_judgment(db, date)
    eod_judge, eod_degraded = load_eod_judge(db, date)
    theme_boards, theme_degraded = load_theme_boards(db, date)
    market_amount, amount_degraded = load_market_amount(db, date)
    promotion, promo_degraded = load_promotion(db, date, emotion.get("prevEodDate"))
    degraded: list[dict[str, str]] = (list(facts["degradedSources"]) + emotion_degraded
                                      + kpl_degraded + relay_degraded
                                      + eod_degraded + theme_degraded
                                      + amount_degraded + promo_degraded)

    state = corpus.build_state(date, facts, emotion,
                               kpl_wrap=kpl_wrap, relay_judgment=relay_judgment,
                               eod_judge=eod_judge, theme_boards=theme_boards,
                               market_amount=market_amount, promotion=promotion)
    questions = corpus.build_questions(state)
    rule_answers = {q: corpus.RULES[q](state) for q in _QUESTION_KEYS}

    jev_meta: dict[str, Any] | None = None
    usage: dict[str, Any] = {}
    skipped_jev = False
    persist_failed = False
    if not apply:
        slots = dict(rule_answers)
        sources = {q: "rule_dry" for q in _QUESTION_KEYS}
        skipped_jev = True
    else:
        account, token = _jev_credentials()
        if not token:
            degraded.append({"source": "jev", "reason": "missing_jev_token", "action": "rule_fallback"})
            slots = dict(rule_answers)
            sources = {q: "rule_fallback" for q in _QUESTION_KEYS}
        else:
            slots: dict[str, str | None] = dict(rule_answers)   # 兜底值，jev 有效答案逐题覆盖
            sources = {q: "rule_fallback" for q in _QUESTION_KEYS}
            try:
                # 通道选择统一走 dispatch_jev_call（单一事实源）：.env.local 配有
                # JEV_TYPESAFE_KEY 时优先官方直连（可经代理）。2026-10-31 实测：
                # 直写 call_jev（CF 网关）撞上游区域封锁，全部回退机械判。
                envelope, latency_ms = dispatch_jev_call(state=state, questions=questions)
                parsed = parse_jev_response(envelope, latency_ms, expected_keys=set(_QUESTION_KEYS))
            except Exception as exc:  # noqa: BLE001 — 解析层意外炸穿降级兜底，不丢当日日报
                parsed = {"ok": False, "errorCode": "call_parse_exception",
                          "errorDetail": f"{type(exc).__name__}: {str(exc)[:150]}"}
            if parsed.get("ok"):
                usage = parsed.get("usage") or {}
                jev_meta = {"latencyMs": parsed.get("latencyMs"), "model": "typesafe/jev"}
                answers = parsed.get("answers") or {}
                for q in _QUESTION_KEYS:
                    answer = ((answers.get(q) or {}).get("choice"))
                    answer = str(answer) if answer is not None else None
                    choices = _question_choices(questions, q)
                    if answer == "insufficient_evidence":
                        slots[q] = None          # 该槽「未判定」，成文事实段不依赖档位
                        sources[q] = "jev_insufficient"
                        degraded.append({"source": q, "reason": "insufficient_evidence",
                                         "action": "slot_unjudged"})
                    elif answer in choices:
                        slots[q] = answer
                        sources[q] = "jev"
                    else:
                        degraded.append({"source": q, "reason": f"invalid_choice: {answer!r}",
                                         "action": "rule_fallback"})
            else:
                degraded.append({"source": "jev",
                                 "reason": f"{parsed.get('errorCode')}: {str(parsed.get('errorDetail') or '')[:120]}",
                                 "action": "rule_fallback"})

    text = corpus.compose_recap_text(date, state, slots)
    report: dict[str, Any] = {
        "_id": date,
        "date": date,
        "ok": True,
        "summary": facts,
        "emotion": emotion,
        "kplWrap": kpl_wrap,
        "relayJudgment": relay_judgment,
        "eodJudge": eod_judge,
        "themeBoards": theme_boards,
        "marketAmount": market_amount,
        "promotion": promotion,
        "ruleAnswers": rule_answers,
        "answers": {q: {"choice": slots.get(q), "source": sources[q]} for q in _QUESTION_KEYS},
        "text": text,
        "questionsRaw": questions,
        "templateVersion": corpus.RECAP_TEMPLATE_VERSION,
        "questionSetVersion": corpus.QUESTION_SET_VERSION_RECAP,
        "jev": jev_meta,
        "usage": usage,
        "skippedJev": skipped_jev,
        "degraded": degraded,
        "generatedAt": _now_iso(),
    }
    if apply:
        try:
            db[COLLECTION].replace_one({"_id": date}, report, upsert=True)
            persisted: Any = date
        except Exception as exc:  # noqa: BLE001 — 落库失败显式登记，stdout 仍可回收（fail-visible）
            persisted = None
            degraded.append({"source": "persistence", "reason": f"persist_failed: {exc}",
                             "action": "stdout_only"})
            persist_failed = True
        report["persistedId"] = persisted
    result = {"ok": True, "report": report}
    if persist_failed:
        result["persistFailed"] = True   # 退出码可见：main() 对该日 exit 1（评审 Minor-2）
    return result


def _question_choices(questions: dict[str, Any], q: str) -> tuple[str, ...]:
    return tuple((questions.get(q) or {}).get("criteria") or ())


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _dates_between(start: str, end: str) -> list[str]:
    try:
        d0, d1 = _date.fromisoformat(start), _date.fromisoformat(end)
    except ValueError as exc:
        raise SystemExit(f"--start/--end 需 YYYY-MM-DD：{exc}") from exc
    if d1 < d0:
        raise SystemExit("--start 不得晚于 --end")
    out = []
    cur = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="复盘日报（jev daily recap，默认 dry 零调用）")
    parser.add_argument("--date", help="YYYY-MM-DD（与 --start/--end 二选一）")
    parser.add_argument("--start", help="区间回填起点 YYYY-MM-DD（配 --apply 为真实调用；缺省 dry 逐日打印机械判）")
    parser.add_argument("--end", help="区间回填终点 YYYY-MM-DD（配 --apply 为真实调用；缺省 dry 逐日打印机械判）")
    parser.add_argument("--apply", action="store_true",
                        help="真实调用 jev 并落库 hotlist_jev_daily_recap；缺省只算机械判+成文（零调用零写库）")
    parser.add_argument("--force", action="store_true", help="当日已有 ok 文档仍重算（幂等跳过的逃生口）")
    args = parser.parse_args()
    if not args.date and not (args.start and args.end):
        parser.error("需要 --date 或 --start/--end")
    dates = [args.date] if args.date else _dates_between(args.start, args.end)
    exit_code = 0
    for d in dates:
        result = run_daily_recap_for_date(d, apply=args.apply, force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("persistFailed"):
            exit_code = 1
        elif not result.get("ok") and result.get("errorCode") != "no_material":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
