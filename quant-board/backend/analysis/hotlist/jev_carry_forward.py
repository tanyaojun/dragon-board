# -*- coding: utf-8 -*-
"""连板股承接（方案 A）与解析去重压缩（方案 B）——纯函数层，无 I/O。

2026-10-20 用户裁决「采纳 A+B」后落地的判据口径，取证见
`docs/hotlist-jev/jev-midday-feed-and-reason-column-20261020.md` §3/§4 与
`docs/hotlist-jev/jev-carry-forward-preregistration-20261020.md`。

A（承接）适用条件（全部满足才算「证据未变」）：
  1. 同一 code，上一标签日距当日 ≤ `MAX_GAP_TRADING_DAYS` 个交易日；
  2. 上一标签日 status=ok，且 `answers` 里三题答案齐全；
  3. 题集代际一致（`questionSetHash` 相同）且原料代际一致（`ammoVersion` 相同）；
  4. 韭研异动解析**正文逐字相同**（`expoundSignature` 相同，归一化后 sha1）。
满足 → `driver_type` / `catalyst_depth` / `catalyst_freshness` 承接上一标签日，
**只重判 `buy_side_logic`（+ 相位分线，若开启）**——实测（339 对连板相邻日）四项里
买盘逻辑是唯一实质会变的一项（22.6% 的解析未变样本仅它变化）。

B（解析去重压缩）只作用在承接路径的叙事上：
  - 保留：解析首行（=涨停原因）、**事件型事项行**（命中 `EVENT_KEYWORDS`）；
  - 省略：非事件核实段（业务版图/沿革类长文），并在原处写明「与前一日逐字相同、已省略 N 条/M 字」。
  依据：承接路径只问 buy_side_logic，其判据只引用「解析中是否存在具体事件行」+ 板块地位/封板时间/
  连板高度（这些行一律保留）；不再被问的 depth/freshness 所需的业务版图与日期证据因此可以省略。
  实测（174 对连板且解析未变样本）事件行占正文 58%（中位 59.6%），即 B 压缩掉正文约 4 成、叙事约 2 成。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

EXPLAIN_HEADER = "韭研解析全文："

# 承接的三题（由解析正文+公司业务决定，正文未变则答案不应变）
CARRY_KEYS = ("driver_type", "catalyst_depth", "catalyst_freshness")
# 承接路径仍要重判的题（吃当日盘面/板块结构/价格位置）
REEVAL_KEYS = ("buy_side_logic",)
# 承接窗：上一标签日距今最多几个交易日（超过则题材可能已换代，必须重判）
MAX_GAP_TRADING_DAYS = 2

# 事件型事项行关键词（判 buy_side_logic「解析中存在对应的具体事件行」用；宁宽不漏）
EVENT_KEYWORDS = (
    "公告", "披露", "中标", "订单", "合同", "框架协议", "业绩", "预告", "快报", "量产",
    "投产", "开工", "扩产", "发布", "推出", "签约", "涨价", "提价", "调价", "回购",
    "增持", "重组", "收购", "并购", "参股", "投资", "设立", "认证", "送样", "定点",
    "供货", "客户", "批复", "核准", "获批", "立项", "专利", "获奖", "入选", "试点",
    "政策", "规划", "补贴", "列入", "合作", "研讨", "标准", "展会", "大会", "量产在即",
)
_EVENT_RE = re.compile("|".join(EVENT_KEYWORDS))


def _normalize_expound(text: str | None) -> str:
    """解析正文归一：逐行 strip、丢空行、丢掉行首编号（1、/1.)，其余原样（逐字比对语义）。"""
    lines = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(re.sub(r"^\d+[、.．]\s*", "", line))
    return "\n".join(lines)


def expound_signature(expound: str | None) -> str | None:
    """异动解析正文签名（sha1 前 12 位）。空解析 → None（不可比对，不承接）。"""
    norm = _normalize_expound(expound)
    if not norm:
        return None
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def expound_block(narrative: str | None) -> list[str] | None:
    """从叙事里切出「韭研解析全文：」之后的段落；无该行 → None（旧档/异常叙事）。"""
    lines = str(narrative or "").split("\n")
    try:
        idx = lines.index(EXPLAIN_HEADER)
    except ValueError:
        return None
    return lines[idx + 1:]


def doc_expound_signature(doc: dict | None) -> str | None:
    """文档的解析签名：优先落库字段 `expoundSignature`（2026-10-20 起写入），
    旧档回退「从 narrative 反解正文」——两条路径都归一到同一 sha1，跨代可比。"""
    if not doc:
        return None
    stored = doc.get("expoundSignature")
    if stored:
        return str(stored)
    block = expound_block(doc.get("narrative"))
    if not block:
        return None
    return expound_signature("\n".join(block))


def carry_decision(*, today_expound: str | None, prev_doc: dict | None,
                   today_question_set_hash: str, today_ammo_version: str,
                   gap_trading_days: int | None,
                   max_gap: int = MAX_GAP_TRADING_DAYS) -> dict:
    """A 的准入判定（纯函数）：返回 {eligible, reason, prevDate, signature, prev}。

    `reason` 命名固定（便于 fail-visible 统计与测试）：
    no_expound / no_prev_doc / gap_too_far / prev_not_ok / prev_question_set_mismatch /
    prev_ammo_mismatch / expound_changed / prev_answers_incomplete。
    """
    sig = expound_signature(today_expound)
    if not sig:
        return {"eligible": False, "reason": "no_expound", "prevDate": None, "signature": None}
    if not prev_doc:
        return {"eligible": False, "reason": "no_prev_doc", "prevDate": None, "signature": sig}
    prev_date = str(prev_doc.get("tradingDate") or "")
    if gap_trading_days is None or gap_trading_days > max_gap:
        return {"eligible": False, "reason": "gap_too_far", "prevDate": prev_date, "signature": sig}
    if str(prev_doc.get("status") or "") != "ok":
        return {"eligible": False, "reason": "prev_not_ok", "prevDate": prev_date, "signature": sig}
    if prev_doc.get("questionSetHash") and prev_doc["questionSetHash"] != today_question_set_hash:
        return {"eligible": False, "reason": "prev_question_set_mismatch",
                "prevDate": prev_date, "signature": sig}
    if prev_doc.get("ammoVersion") and prev_doc["ammoVersion"] != today_ammo_version:
        return {"eligible": False, "reason": "prev_ammo_mismatch",
                "prevDate": prev_date, "signature": sig}
    prev_sig = doc_expound_signature(prev_doc)
    if prev_sig != sig:
        return {"eligible": False, "reason": "expound_changed", "prevDate": prev_date,
                "signature": sig}
    prev_answers = prev_doc.get("answers") or {}
    missing = [k for k in CARRY_KEYS if not (prev_answers.get(k) or {}).get("choice")]
    if missing:
        return {"eligible": False, "reason": "prev_answers_incomplete",
                "prevDate": prev_date, "signature": sig, "missing": missing}
    return {"eligible": True, "reason": None, "prevDate": prev_date, "signature": sig,
            "prev": prev_doc}


def compress_narrative(narrative: str, prev_date: str) -> tuple[str, dict[str, Any]]:
    """B：承接路径叙事压缩（保留首行原因 + 事件行，省略非事件核实段并声明）。

    返回 (compressed_narrative, stats)。未生效时原样返回并给 reason（fail-visible，不静默）。
    """
    lines = str(narrative or "").split("\n")
    try:
        idx = lines.index(EXPLAIN_HEADER)
    except ValueError:
        return narrative, {"applied": False, "reason": "no_expound_block"}
    head, block = lines[:idx], lines[idx + 1:]
    body = [x for x in block[1:] if x.strip()]
    if not body:
        return narrative, {"applied": False, "reason": "empty_expound_body"}
    keep = [x for x in body if _EVENT_RE.search(x)]
    drop = [x for x in body if not _EVENT_RE.search(x)]
    if not drop:
        return narrative, {"applied": False, "reason": "no_non_event_item"}
    kept_chars = sum(len(x) for x in keep)
    dropped_chars = sum(len(x) for x in drop)
    marker = (f"韭研解析全文（正文与前一日 {prev_date} 逐字相同；仅保留事件型事项行，"
              f"非事件核实段 {len(drop)} 条/{dropped_chars} 字已省略——"
              f"driver/depth/freshness 已承接上一判定，不再重问）：")
    compressed = "\n".join([*head, marker, block[0], *keep])
    return compressed, {"applied": True, "prevDate": prev_date, "keptItems": len(keep),
                        "droppedItems": len(drop), "keptChars": kept_chars,
                        "droppedChars": dropped_chars,
                        "origChars": kept_chars + dropped_chars}
