# -*- coding: utf-8 -*-
"""日度情绪一句话（jev daily line）：当日 slot 情绪曲线 → jev 归层形态 → 版本化模板拼句。

设计/预登记：quant-board/docs/hotlist-jev/jev-daily-line-design.md（2026-10-08 用户裁决）。
- 语料包 = state（可数事实 + 近 20 日分位锚）+ 单道 choice 题（判据只引用 state 已有字段，v2.1 教训）；
- 句子 = 模板 × 槽位值，jev 永不生成措辞（2026-10-03 措辞漂移教训）；
- 带标签/入场笔数 = 引擎 band_of_score 与脉拍 tradeCount 单一事实源，不让 jev 重判；
- jev 失败/缺席/无效答案 → 规则机械判 shape 兜底 + shapeSource/degradedReasons 标注
  （fail-visible，不阻断句子产出，不伪造 jev 来源）；
- 纪律：不带 --apply 时零真实调用、零写库；pytest 一律 mock，禁真调用（硬红线 §1.2#7）。

用法（quant-board 目录，盘后链 jevDailyLine 步以 --apply 子进程调用）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_daily_line --date 2026-10-08 [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import band_of_score
from backend.operations.phase_monitor_persistence import persist_daily_line
from backend.operations.phase_pulse import PULSE_BAND_LABELS, load_eod_scores
from backend.services.jev.jev_client import DEFAULT_ACCOUNT_ID, call_jev, parse_jev_response

MIN_INTRADAY_SLOTS = 5     # 盘中槽少于此数：原料不足，shape=unknown 且不烧 jev（省预算+避免超证据判读）
RANGE_FLAT_THRESHOLD = 8.0  # 日内振幅低于此分值 → 窄幅震荡（与题目 criteria 同数，改一处须同步文档）

# 句子模板（单一事实源；改措辞必须升版本并登记 jev-daily-line-design.md §3）
SENTENCE_TEMPLATE_VERSION = 1
# 题集代际戳（I15 对齐：DAILY_SHAPE_QUESTION 判据/口径换代必须动戳，跨代不可比）。
QUESTION_SET_VERSION_DAILY_LINE = "v1"

SHAPE_CHOICES = ("高开低走", "低开高走", "冲高回落", "探底回升", "单边走强", "窄幅震荡", "insufficient_evidence")
SHAPE_UNKNOWN = "unknown"

# 句内带词（展示字典，键=引擎 BAND_TAGS 单一事实源；PULSE_BAND_LABELS 是带展示名，
# 句子需要「××带」形态，另立字典并测试键集合同步，不手抄阈值）
SENTENCE_BAND_WORDS = {
    "冷10-40": "低温带",
    "弱势40-60": "弱势带",
    "强60-80": "高温带",
    "极热≥80": "极热带",
}


# ---------------------------------------------------------------- 题料包（questions）

def _daily_shape_question() -> dict[str, Any]:
    """单道 choice 题：判据只引用 state.curves 已有特征字段（v2.1 教训：零语料外证据）。"""
    return {
        "daily_shape": {
            "type": "choice",
            "instructions": (
                "根据今日热榜情绪分曲线特征（开盘/收盘/峰值/谷值的日内位置 openPos/closePos "
                "与时刻序位 peakPos/troughPos、振幅 range），今日全天情绪路径属于哪种形态？"
                "只描述当日已发生曲线，不预测后市。"
            ),
            "criteria": {
                "高开低走": "开盘分处日内振幅前30%（openPos≥0.7）且收盘处后35%（closePos≤0.35）且峰值出现在前半段（peakPos≤0.5）",
                "低开高走": "开盘处后30%（openPos≤0.3）且收盘处前35%（closePos≥0.65）且谷值出现在前半段（troughPos≤0.5）",
                "冲高回落": "开盘不在极端高位（openPos<0.7）且峰值在前半段（peakPos≤0.5）且收盘落到下半区（closePos≤0.5）",
                "探底回升": "开盘不在极端低位（openPos>0.3）且谷值在前半段（troughPos≤0.5）且回升收在上半区（closePos≥0.5）且收盘不在峰值位（closePos<0.9）",
                "单边走强": "一路走高：收盘与峰值均在日内尾段（closePos≥0.9 且 peakPos≥0.9）且较开盘显著走高（closePos−openPos≥0.3）且开盘不在低位（openPos>0.3）",
                "窄幅震荡": f"日内振幅过窄（range<{RANGE_FLAT_THRESHOLD:g}分），方向特征不可辨",
                "insufficient_evidence": "曲线槽位不足或关键字段缺失（通常不应落入：state 已给出全部特征值）",
            },
        }
    }


DAILY_SHAPE_QUESTION = _daily_shape_question()


# ---------------------------------------------------------------- 纯函数：事实 / 机械判 / 拼句

def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def collect_curve_facts(slot_scores: dict[str, float], eod_score: float | None) -> dict[str, Any]:
    """当日盘中 slot 情绪曲线事实（纯函数）。slot_scores={slotTime: score}，不含 EOD 槽。

    EOD 是 15:00 槽的衍生锚，只作 close（来源标注 closeSource），不入序列——重复计入会污染 min/max。
    fail-visible：非数值槽丢弃计数、槽不足、缺 EOD 全部结构化登记，缺失保持缺失不伪造 0。
    """
    degraded: list[dict[str, str]] = []
    items = sorted((str(t), s) for t, s in slot_scores.items() if _num(s) is not None)
    dropped = len(slot_scores) - len(items)
    if dropped:
        degraded.append({"source": "slots", "reason": f"non_numeric_scores: {dropped}", "action": "dropped"})
    close = _num(eod_score)
    close_source = "eod" if close is not None else ("last_slot" if items else None)
    if close is None:
        degraded.append({"source": "eod", "reason": "missing_eod_score",
                         "action": "close_last_slot_fallback" if items else "close_unavailable"})
        if items:
            close = items[-1][1]
    facts: dict[str, Any] = {
        "slots": [{"slotTime": t, "score": s} for t, s in items],
        "slotsCount": len(items),
        "open": items[0][1] if items else None,
        "openSlot": items[0][0] if items else None,
        "close": close,
        "closeSource": close_source,
        "peak": None, "peakTime": None, "trough": None, "troughTime": None,
        "range": None, "openPos": None, "closePos": None, "peakPos": None, "troughPos": None,
        "degradedSources": degraded,
    }
    if not items:
        return facts
    values = [s for _, s in items]
    peak = max(values)
    trough = min(values)
    facts["peak"] = peak
    facts["peakTime"] = items[values.index(peak)][0]
    facts["trough"] = trough
    facts["troughTime"] = items[values.index(trough)][0]
    rng = peak - trough
    facts["range"] = round(rng, 2)
    if rng > 0:
        facts["openPos"] = round((items[0][1] - trough) / rng, 3)
        facts["closePos"] = round(((close - trough) / rng) if close is not None else None, 3)
        facts["peakPos"] = round(values.index(peak) / (len(values) - 1), 3) if len(values) > 1 else None
        facts["troughPos"] = round(values.index(trough) / (len(values) - 1), 3) if len(values) > 1 else None
    return facts


def rule_shape(facts: dict[str, Any]) -> str:
    """形态机械判（规则兜底 + jev 一致率对照基线；判据与 DAILY_SHAPE_QUESTION criteria 同数）。

    顺序即优先级：窄幅 → 高开低走 → 低开高走 → 冲高回落 → 单边走强 → 探底回升 → unknown。
    （单边走强先于探底回升：收在峰值位的 V 型反弹归单边走强；探底回升=回升但不收峰值位。）
    """
    if facts.get("slotsCount", 0) < MIN_INTRADAY_SLOTS:
        return SHAPE_UNKNOWN
    rng = facts.get("range")
    if rng is None:
        return SHAPE_UNKNOWN
    if rng < RANGE_FLAT_THRESHOLD:
        return "窄幅震荡"
    op, cp, pp, tp = facts.get("openPos"), facts.get("closePos"), facts.get("peakPos"), facts.get("troughPos")
    if None in (op, cp, pp, tp):
        return SHAPE_UNKNOWN
    if op >= 0.7 and cp <= 0.35 and pp <= 0.5:
        return "高开低走"
    if op <= 0.3 and cp >= 0.65 and tp <= 0.5:
        return "低开高走"
    if op < 0.7 and pp <= 0.5 and cp <= 0.5:
        return "冲高回落"
    if op > 0.3 and cp >= 0.9 and pp >= 0.9 and cp - op >= 0.3:
        return "单边走强"
    if op > 0.3 and tp <= 0.5 and cp >= 0.5 and cp < 0.9:
        return "探底回升"
    return SHAPE_UNKNOWN


def _eod_gap_days(prev_eod_date: str | None, today: str) -> int | None:
    if not prev_eod_date:
        return None
    try:
        return (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(prev_eod_date, "%Y-%m-%d")).days
    except ValueError:
        return None


def calendar_flag(prev_eod_date: str | None, today: str) -> str | None:
    """节后首日标签：与上一 EOD 交易日间隔 ≥4 天（跨周末=3 天不触发）。数据缺失返回 None。"""
    gap = _eod_gap_days(prev_eod_date, today)
    return "节后首日" if gap is not None and gap >= 4 else None


def eod_percentile(prior_scores: list[float], today: float) -> float | None:
    """当日 EOD 在近 20 日窗口的分位（%）；样本 <8 返回 None（v2.2 教训：锚窗口不足不硬给）。"""
    if len(prior_scores) < 8:
        return None
    below = sum(1 for s in prior_scores if s < today)
    return round(below / len(prior_scores) * 100, 1)


def build_sentence(parts: dict[str, Any]) -> str:
    """模板 v1：{calendar}{情绪}{shape}收{bandWord}，策略基线{action}。shape=unknown 省略形态子句。"""
    calendar = str(parts.get("calendarFlag") or "")
    shape = parts.get("shape")
    shape_part = str(shape) if shape and shape != SHAPE_UNKNOWN else ""
    band = str(parts.get("bandWord") or "")
    action = str(parts.get("action") or "")
    return f"{calendar}情绪{shape_part}收{band}，策略基线{action}"


def action_label(trade_count: int | None) -> str:
    if trade_count is None:
        return "读数暂缺"
    if trade_count <= 0:
        return "无入场"
    return f"入场{trade_count}笔"


# ---------------------------------------------------------------- 数据装载（可 monkeypatch 边界）

def _get_db() -> Any:
    from backend.data.repositories import repository_factory

    return repository_factory.get_runtime_mongodb_database()


def load_day_slot_scores(db: Any, date: str) -> dict[str, Any]:
    """当日非 EOD 槽原始情绪分 {slotTime: raw}（EOD 槽排除，理由见 collect_curve_facts）。

    原样透传不预过滤：非数值/缺分槽由 collect_curve_facts 统一 _num 计数并登记
    non_numeric_scores（fail-visible）——loader 若先过滤，该登记在生产路径永不可达。
    """
    out: dict[str, Any] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "slotTime": {"$ne": "EOD"}, "tradingDate": date},
        {"slotTime": 1, "emotionScore.score": 1},
    ):
        out[str(doc.get("slotTime"))] = (doc.get("emotionScore") or {}).get("score")
    return out


def load_month_trade_count(db: Any, month: str) -> int | None:
    """当月脉拍 tradeCount（phase_monitor pulse 文档；缺失返回 None，拼句如实标注）。"""
    try:
        doc = db["phase_monitor"].find_one({"_id": f"pulse:{month}"}, {"report.tradeCount": 1})
    except Exception:  # noqa: BLE001 — 带内 advisory 数据缺失不阻断句子
        return None
    tc = ((doc or {}).get("report") or {}).get("tradeCount")
    return tc if isinstance(tc, int) and not isinstance(tc, bool) else None


def _jev_credentials() -> tuple[str, str]:
    from backend.core.settings import get_settings

    get_settings()  # 确保 .env.local 已入 environ
    return os.environ.get("JEV_CF_ACCOUNT") or DEFAULT_ACCOUNT_ID, os.environ.get("JEV_CF_TOKEN") or ""


# ---------------------------------------------------------------- 主流程

def run_daily_line_for_date(date: str, *, apply: bool = False) -> dict[str, Any]:
    """产出当日一句话。apply=False：零 jev 调用零写库（规则 shape + 拼句，skippedJev 标注）。"""
    db = _get_db()
    eod_scores = load_eod_scores(date)
    eod = _num(eod_scores.get(date))
    if eod is None:
        return {"ok": False, "errorCode": "no_eod",
                "message": f"{date} 无 EOD 情绪文档（非交易日或盘后链 hotlistSentiment 未落）"}
    slot_scores = load_day_slot_scores(db, date)
    facts = collect_curve_facts(slot_scores, eod)
    degraded: list[dict[str, str]] = list(facts.get("degradedSources") or [])

    prior = [(d, s) for d, s in sorted(eod_scores.items()) if d < date and _num(s) is not None]
    raw_prior_count = sum(1 for d in eod_scores if d < date)
    if raw_prior_count > len(prior):
        degraded.append({"source": "reference",
                         "reason": f"prior_eod_none_dropped: {raw_prior_count - len(prior)}",
                         "action": "excluded_from_percentile"})
    prev_date = prior[-1][0] if prior else None
    reference = {
        "prevEodDate": prev_date,
        "prevEod": prior[-1][1] if prior else None,
        "prevEodGapDays": _eod_gap_days(prev_date, date),
        "eod20dPercentile": eod_percentile([s for _, s in prior[-20:]], eod),
        "eod20dSample": min(len(prior), 20),
    }
    if reference["eod20dPercentile"] is None:
        degraded.append({"source": "reference", "reason": "eod20d_sample_small", "action": "percentile_unavailable"})
    calendar = calendar_flag(prev_date, date)
    band_tag = band_of_score(eod)
    band_label = PULSE_BAND_LABELS[band_tag][0]
    band_word = SENTENCE_BAND_WORDS[band_tag]
    trade_count = load_month_trade_count(db, date[:7])
    rule = rule_shape(facts)

    jev_meta: dict[str, Any] | None = None
    skipped_jev = False
    if facts["slotsCount"] < MIN_INTRADAY_SLOTS:
        degraded.append({"source": "daily_shape", "reason": f"insufficient_slots: {facts['slotsCount']}<{MIN_INTRADAY_SLOTS}",
                         "action": "skip_jev"})
        shape, shape_source = SHAPE_UNKNOWN, "rule"
    elif not apply:
        shape, shape_source = rule, "rule"
        skipped_jev = True
    else:
        account, token = _jev_credentials()
        if not token:
            degraded.append({"source": "daily_shape", "reason": "missing_jev_token", "action": "rule_fallback"})
            shape, shape_source = rule, "rule_fallback"
        else:
            state = {
                "date": date,
                "curve": {k: facts[k] for k in
                          ("slotsCount", "open", "close", "closeSource", "peak", "peakTime",
                           "trough", "troughTime", "range", "openPos", "closePos", "peakPos", "troughPos")},
                "reference": reference,
                "context": {"calendarFlag": calendar, "bandTag": band_tag, "bandLabel": band_label,
                            "monthPulseTradeCount": trade_count},
                "degradedSources": degraded,
            }
            try:
                envelope, latency_ms = call_jev(account, token, state=state, questions=DAILY_SHAPE_QUESTION)
                parsed = parse_jev_response(envelope, latency_ms, expected_keys={"daily_shape"})
            except Exception as exc:  # noqa: BLE001 — 共享解析层意外炸穿降级兑底（评审 P3 加固），不丢当日句子
                parsed = {"ok": False, "errorCode": "call_parse_exception",
                          "errorDetail": f"{type(exc).__name__}: {str(exc)[:150]}"}
            if parsed.get("ok"):
                answer = ((parsed.get("answers") or {}).get("daily_shape") or {}).get("choice")
                if answer in SHAPE_CHOICES and answer != "insufficient_evidence":
                    shape, shape_source = str(answer), "jev"
                    jev_meta = {"latencyMs": parsed.get("latencyMs"), "model": "typesafe/jev"}
                else:
                    degraded.append({"source": "daily_shape",
                                     "reason": f"{'insufficient_evidence' if answer == 'insufficient_evidence' else 'invalid_choice'}: {answer!r}",
                                     "action": "shape_unavailable" if answer == "insufficient_evidence" else "rule_fallback"})
                    shape = SHAPE_UNKNOWN if answer == "insufficient_evidence" else rule
                    shape_source = "jev" if answer == "insufficient_evidence" else "rule_fallback"
                    if answer == "insufficient_evidence":
                        jev_meta = {"latencyMs": parsed.get("latencyMs"), "model": "typesafe/jev"}
            else:
                degraded.append({"source": "daily_shape",
                                 "reason": f"{parsed.get('errorCode')}: {str(parsed.get('errorDetail') or '')[:120]}",
                                 "action": "rule_fallback"})
                shape, shape_source = rule, "rule_fallback"

    sentence = build_sentence({"calendarFlag": calendar, "shape": shape, "bandWord": band_word,
                               "action": action_label(trade_count)})
    report: dict[str, Any] = {
        "date": date,
        "sentence": sentence,
        "parts": {"calendarFlag": calendar, "shape": shape, "bandTag": band_tag,
                  "bandLabel": band_label, "bandWord": band_word, "action": action_label(trade_count)},
        "shapeSource": shape_source,
        "ruleShape": rule,
        "jev": jev_meta,
        "skippedJev": skipped_jev,
        "degraded": degraded,
        "curve": {k: facts[k] for k in facts if k != "degradedSources"},
        "reference": reference,
        "meta": {"templateVersion": SENTENCE_TEMPLATE_VERSION,
                 "questionSetVersion": QUESTION_SET_VERSION_DAILY_LINE,
                 "generatedAt": datetime.now().isoformat(timespec="seconds")},
    }
    if apply:
        persisted = persist_daily_line(report)
        if persisted is None:
            degraded.append({"source": "persistence", "reason": "persist_failed", "action": "stdout_only"})
        report["persistedId"] = persisted
    return {"ok": True, "report": report}


def main() -> int:
    parser = argparse.ArgumentParser(description="日度情绪一句话（jev daily line，默认 dry 零调用）")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true",
                        help="真实调用 jev 并落库 phase_monitor line:<date>；缺省只算规则+拼句（零调用零写库）")
    args = parser.parse_args()
    result = run_daily_line_for_date(args.date, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
