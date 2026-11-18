# -*- coding: utf-8 -*-
"""题材层「板块龙头隔日连板」投喂 runner（2026-10-20，L3 语料落地后的判据层首版）。

定位：每条投喂 = **当日一个板块的龙头**（不是每只涨停股）。目标题（v5 四题）= 题材炒作深度/题材延续性/次日该龙头是否继续
封板，证据 = 结构事实（触板−炸板二分 + 真连板 + 封板时间 + 板块家数 + 跟风/昨日延续）
+ 同桶历史基准率 + 题材证据块（韭研产业树催化原文 + 开盘啦题材事件/新闻/日历）。

**v12 A2 拆题（2026-10-28 用户裁决，预登记 theme-leader-v12 §2.3）**：每板块拆为——
①板块级 doc（`_id={date}:board:{board}`，`docKind="sector"`）：深度/延续两题，叙事=
双龙一并列结构行（主板/双创分轨，每板块 ≤2 龙一）；②个股级 doc（`_id={date}:{code}`，
`docKind="leader"`）：续板/空间两题，每轨龙一各一次。每日预算包络 = Σ板块(1+轨数)。

花 token 的口子只有一个：`run()` 里的 `_dispatch_jev`；`--dry-run` / `--estimate` 全程零调用，
用于人工过目「将来真正下发的文本」与成本估算。真实开火必须 `--confirm-budget`
（AGENTS §1.2-7：真实调用只走预登记 + 预算确认路径）。

存储：`hotlist_jev_theme_leader_labels`，龙头 doc `_id={date}:{code}`（一股一条）、
板块 doc `_id={date}:board:{board}`（v12 起）；与驱动链（`hotlist_jev_driver_labels`）
**分集合存放**：题集/判据代际不同，跨集混读会掩盖代际漂移。

用法：
  # 零 token：看当天会投喂哪些龙头、文本长什么样、大概烧多少 token
  ./.venv/Scripts/python.exe -m backend.operations.theme_leader_label --date 2026-10-20 --dry-run
  # 真开火（需预算批准）
  ./.venv/Scripts/python.exe -m backend.operations.theme_leader_label --date 2026-10-20 --confirm-budget
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_event_digest as digest
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID

logger = logging.getLogger(__name__)
from backend.analysis.hotlist.jev_lhb_ammo import collect_lhb_facts
from backend.analysis.hotlist.theme_leader_ammo import (
    market_summary_line,
    AMMO_VERSION_THEME_LEADER,
    QUESTION_SET_HASH_THEME_LEADER,
    QUESTION_SET_VERSION_THEME_LEADER,
    QUESTIONS_THEME_LEADER,
    THEME_LEADER_KEYS,
    apply_evidence_gate,
    base_rate_line,
    baseline_line,
    board_ladder_line,
    board_zhaban_line,
    bid_line,
    board_dt_line,
    build_leader_narrative,
    build_sector_narrative,
    combo_key,
    driver_cross_line,
    headroom_anchor_line,
    kpl_live_line,
    lhb_line,
    lhb_forecast_line,
    lhb_realtime_line,
    plate_series_line,
    popularity_rank_line,
    rank_sentinel_warnings,
    regulatory_risk_line,
    risk_profile_line,
    sector_judgment_line,
    structure_facts_line,
    limitup_reason_line,
    plate_strength_line,
    rebound_popularity_line,
    structure_line,
    structure_line_dual,
    zt_gene_line,
    seal_quality_line,
    theme_heat_line,
    notice_count_line,
)
from backend.operations.leader_wzs import COLLECTION as WZS_COLLECTION
from backend.operations.theme_cycle import COLLECTION as CYCLE_COLLECTION
from backend.operations.theme_leader_baseline import (
    board_count_history, build_rows, day_leader_rows)
from backend.operations.theme_leader_seal_stats import live_base_rate
from backend.services.jev.jev_client import parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev

# P1-1 改道（2026-11-07 用户裁决先调研，5 探针实证后定案）：jev 平台（jev-1.14.0）
# answer schema 服务端锁死（{type,choice,confidence,probabilities}，题面硬性要求也吐不出
# reason），state 头/尾注均被忽略，questions 附加键顶层 422/题内被忽略，text 题型 400。
# → 模型自证理由不可行，改由**程序侧**读叙事「结构基线」行计算档位偏离并打标
# （auditFlag=deviation_from_anchor，纯落库审计元数据：不覆盖答案、不进门、不改状态）。
# 原因透传（answerReasons）保留：平台未来若放开 answer schema 零改动接住。
_ANCHOR_ORDER = ("verylow_lt25", "low_25_45", "mid_45_65", "high_ge65")


def _rate_bucket(rate: float) -> str:
    """基准率 → 档位桶（与续板题四桶边界一致：<25 / 25-45 / 45-65 / ≥65）。"""
    return ("verylow_lt25" if rate < 25 else "low_25_45" if rate < 45
            else "mid_45_65" if rate < 65 else "high_ge65")


def _anchor_deviation_audit(narrative: str | None, choice: str | None) -> tuple[str | None, str | None]:
    """程序侧偏离审计：规则①中枢（最细同桶，样本<8 回退按连板高度桶）与模型档位比对。

    偏离≥1 档 → ("deviation_from_anchor", 说明)；同档/无基线行/insufficient/未答 → (None, None)。
    """
    if not narrative or not choice or choice == "insufficient" or choice not in _ANCHOR_ORDER:
        return None, None
    # 2026-11-17b：叙事桶键中文化后前缀改「同结构」（括号内容通配不受影响）；
    # src 审计标签保持内部术语「同桶」（结构化字段，不进叙事）。
    m = re.search(r"结构基线：同结构\[[^\]]+\] 历史次日连板率 ([\d.]+)%（(\d+) 样本）", narrative)
    src = "同桶"
    if not m or int(m.group(2)) < 8:
        m2 = re.search(r"按连板高度\[[^\]]+\] ([\d.]+)%（(\d+) 样本）", narrative)
        if not m2:
            return None, None
        m, src = m2, "按连板高度"
    rate = float(m.group(1))
    bucket = _rate_bucket(rate)
    if bucket == choice:
        return None, None
    return ("deviation_from_anchor",
            f"模型 {choice} vs {src}中枢 {rate}%（{_rate_bucket(rate)}）")

COLLECTION = "hotlist_jev_theme_leader_labels"
DRIVER_LABEL_COLLECTION = "hotlist_jev_driver_labels"
ORIGIN = "theme_leader_label_v1"
# v12 A2 拆题：板块级/个股级题面子集与 docKind（预登记 §2.3）
SECTOR_QUESTIONS = ("theme_speculation_depth", "theme_continuation")
# v17（预登记 v17 §2.3）：个股级扩为四题——续板/空间 + 催化硬度/身位稳固度
# （同调用判答零额外调用次数）；事件日 +rebound 共五题。
LEADER_QUESTIONS = ("leader_nextday_continue", "leader_headroom",
                    "leader_catalyst_hardness", "leader_seat_durability")
# v14（P3 工作流 B，B1:A 事件门）：人气成色题仅弱转强事件股判答——非事件日叙事
# 不含本题零额外调用（预算预登记 §四）；事件门数据单源 hotlist_jev_leader_wzs
REBOUND_QUESTION = "leader_rebound_popularity"
LEADER_QUESTIONS_REBOUND = LEADER_QUESTIONS + (REBOUND_QUESTION,)
DOC_KIND_SECTOR = "sector"
DOC_KIND_LEADER = "leader"


def fetch_driver_label(db: Any, date: str, code: str) -> dict | None:
    """打标交叉源（AMMO 2026-10-27b）：当日该股打标行，final 优先、同槽取最新 computedAt。
    phase_band_daily（日级哨兵，无个股 code）按 code 过滤天然排除。查不到返回 None
    （叙事出 fail-visible 缺席行）。查询保持平坦等值（find 全取后 Python 侧过滤排序），
    兼容测试假库，也对真 Mongo 正确。"""
    docs = [d for d in (db[DRIVER_LABEL_COLLECTION].find(
              {"tradingDate": date, "code": str(code)}) or [])
            if d.get("labelSlot") in ("final", "midday")
            and d.get("origin") != "phase_band_daily"]
    if not docs:
        return None
    final = [d for d in docs if d.get("labelSlot") == "final"]
    return max(final or docs, key=lambda d: str(d.get("computedAt") or ""))


# ── v12 新原料（AMMO 2026-10-28a；预登记 §4.1/§4.3） ──

# 强度行专属桥（与 digest.ALIASES 分离：强度行只匹配 KPL 一级，语料匹配用层2 标签）。
# 仅实测定 verified 条目可入（预登记 §9），key=归一后的韭研板块名。
_STRENGTH_BOARD_ALIASES: dict[str, tuple[str, ...]] = {
    # 2026-11-02 用户裁决（KPL 板块行情实证，见 match_board_strength 内注释）
    "AI影视传媒": ("AI应用",),
}

def fetch_plate_strength(date: str) -> dict:
    """KPL 板块强度排行（G2，预登记 §4.3）：一次取数全板块共用（与 market_line 同哲学）。

    走 `kpl_ranking_service.get_sector_ranking`（Type=1+Date 按日查史，已通接口，TTL 缓存）。
    失败 fail-visible 返回 {ok:False, reason}，不阻断标注链、不伪装成功。非 jev 调用、
    不花 token；网络异常仅影响本行（fail-visible 行文由 plate_strength_line 承担）。
    """
    try:
        from backend.services.kpl_ranking_service import get_sector_ranking
        payload = get_sector_ranking(date)
    except Exception as exc:  # noqa: BLE001 — 上游/网络异常不阻断标注链（fail-visible）
        return {"ok": False, "reason": f"fetch_failed: {exc}"}
    if not isinstance(payload, dict) or not payload.get("ok"):
        return {"ok": False, "reason": f"payload_not_ok: {payload}"}
    return {"ok": True, "items": payload.get("items") or []}


def match_board_strength(strength_payload: dict, board: str) -> dict:
    """韭研板块名 → KPL **一级**排行行匹配 v2（2026-10-28 用户裁决：不匹配二级板块）。

    匹配次序（全部归一化后）：①精确；②尾缀剥离（KPL「机器人概念」↔韭研「机器人」，
    2026-10-28 实测样本核对）；③双向包含（len≥2）；④共享子串锚（复用
    `theme_event_digest` 泛词黑名单口径，单一事实源）。未命中 = {ok:False,
    reason:"unmatched"}（fail-visible，不猜语义——别名表预留结构，仅实测定verified
    条目可入，预登记 §9）。匹配 = {ok:True, rank/total/name/strength/pct}（排名=一级
    序位，1 起）。
    """
    if not strength_payload.get("ok"):
        return {"ok": False, "reason": strength_payload.get("reason") or "unavailable"}
    items = strength_payload.get("items") or []
    if not str(board or "").strip():
        return {"ok": False, "reason": "unmatched"}
    base = digest.normalize_name(board)
    if not base:
        return {"ok": False, "reason": "unmatched"}
    suffix_re = re.compile(r"(?:概念|板块|指数)$")
    base_stripped = suffix_re.sub("", base) or base

    def _norm(name: str) -> str:
        return suffix_re.sub("", digest.normalize_name(name) or "")

    pool = [(i + 1, it, _norm(str(it.get("name") or ""))) for i, it in enumerate(items)
            if _norm(str(it.get("name") or ""))]
    # ① 精确（归一含尾缀剥离）
    for rank, it, nm in pool:
        if nm == base_stripped:
            return _strength_hit(rank, items, it)
    # ② 双向包含（len≥2，本名优先于别名——与 match_industry 同哲学）
    if len(base_stripped) >= 2:
        for rank, it, nm in pool:
            if len(nm) >= 2 and (base_stripped in nm or nm in base_stripped):
                return _strength_hit(rank, items, it)
    # ③ 别名（单一事实源=digest.ALIASES，仅用户裁决过的等价对；行内披露「别名表」）
    alias_keys = [a for a in digest.board_keywords(board)
                  if a not in (base, base_stripped)]
    # 强度行专属桥（2026-11-02 用户裁决，KPL 板块行情实证）：韭研「AI影视/传媒」
    # 32 家（AI漫剧/短剧）归 KPL **一级**「AI应用」——其层2「AI视频」23 家（+9.19%）
    # 即这批股；而「文化传媒」仅 2 家涨停，旧④共享子串「传媒」为误配（读数失真）。
    # 强度行只匹配一级（2026-10-28 裁决），层2「AI视频」不可作强度锚；
    # 语料匹配仍走 digest.ALIASES→AI视频（层2 标签粒度），两桥粒度不同互不冲突。
    alias_keys = list(alias_keys) + [
        a for a in _STRENGTH_BOARD_ALIASES.get(base_stripped, ())
        if a not in alias_keys]
    for rank, it, nm in pool:
        if any(len(a) >= 2 and (a in nm or nm in a) for a in alias_keys):
            return _strength_hit(rank, items, it, alias_used=True)
    # ④ 共享子串锚（泛词黑名单口径复用 digest 单一实现）
    for rank, it, nm in pool:
        if len(nm) >= 2 and digest._shared_anchor(base_stripped, nm):
            return _strength_hit(rank, items, it)
    return {"ok": False, "reason": "unmatched"}


def _strength_hit(rank: int, items: list, it: dict, alias_used: bool = False) -> dict:
    return {"ok": True, "rank": rank, "total": len(items),
            "name": str(it.get("name") or ""), "strength": it.get("strength"),
            "pct": it.get("pct"), "aliasUsed": alias_used,
            "plate_id": str(it.get("plate_id") or "")}


# ── KPL 直播播报（G1，2026-10-28 用户裁决接入） ──
_AI_GEN_NOTE = "（该内容由AI大模型根据行情自动生成）"
# 2026-10-30f：大盘综述判别词（空板块名条目命中即不进板块播报；近 5 日归档实测全命中为指数综述）
_MARKET_WRAP_RE = re.compile(
    r"三大指数|上证指数|深证成指|创业板指|沪深京三市|沪深两市|北证50|两市成交|全市场")


def fetch_live_commentary(st: int = 60) -> dict:
    """KPL 直播解说流（G1）：`get_live_commentary`（实时，仅标注时点可得），

    失败 fail-visible 返回 {ok:False, reason}；非 jev 调用、不花 token；一次取数全板块
    共用（与板块强度同哲学）。历史日不可回放由 `live_entries_for_board` 结构化降级。
    """
    try:
        from backend.services.kpl_ranking_service import get_live_commentary
        return get_live_commentary(st=st)
    except Exception as exc:  # noqa: BLE001 — 上游/网络异常不阻断标注链（fail-visible）
        return {"ok": False, "reason": f"fetch_failed: {exc}"}


LIVE_ARCHIVE_COLLECTION = "kpl_live_daily"


def get_live_for_label(db: Any, date: str) -> dict:
    """标注用直播流（P1-2 日归档）：历史日归档优先 → 当日恒实时取数 + merge-union → 缺席降级。

    归档集合 `kpl_live_daily`（_id=date）：挂链（17:30，2026-10-30 改时）标注当日时实时取数并落库，此后
    回填/复盘/评估读归档——**存的是标注时点当日文本**，无 look-ahead；历史日无归档
    → {ok: False, reason}（fail-visible，不把今天直播冒充历史语料）。
    2026-11-13 A7：落库改 merge-union（kpl_live_archive.merge_live_archive 单实现），
    晨间 09:26 归档的 09:15 竞价推送条目不被本路径覆盖；返回 items 为合并后全量。
    """
    col = db[LIVE_ARCHIVE_COLLECTION]
    doc = col.find_one({"_id": str(date)}) or {}
    if str(date) != time.strftime("%Y-%m-%d"):
        # 历史日：归档优先（零外呼）；无归档 → 结构化降级（实时流不可回放）
        if doc.get("items"):
            return {"ok": True, "items": doc["items"], "notice": doc.get("notice"),
                    "fromArchive": True}
        return {"ok": False,
                "reason": f"实时流不可回放（标注日 {date} 非当日且无直播归档，历史日无直播归档）"}
    # 当日恒取数 + merge-union（2026-11-13 review blocker 修复）：晨间 09:26 归档只覆盖
    # 晨间窗，若命中归档早退则盘中播报与 15:00 大盘综述静默丢失。
    # A7 语义 = 17:30 仍取数仍写、不覆盖晨间条目（merge 单实现）。
    payload = fetch_live_commentary()
    if not payload.get("ok"):
        if doc.get("items"):
            return {"ok": True, "items": doc["items"], "notice": doc.get("notice"),
                    "fromArchive": True, "liveFetchFailed": payload.get("reason")}
        return payload
    items = payload.get("items") or []
    item_today = [it for it in items
                  if time.strftime("%Y-%m-%d", time.localtime(it["ts"])) == str(date)]
    if item_today:
        # A7（2026-11-13 预登记 auction-leader-vA1）：merge-union 共享写口——
        # 晨间归档（09:15 竞价推送条目）不被 17:30 全量取数覆盖；单实现两调用点
        from backend.services.kpl_live_archive import merge_live_archive
        merged = merge_live_archive(db, str(date), payload)
        return {"ok": True, "items": merged["items"],
                "notice": merged.get("notice"), "fromArchive": False}
    return {"ok": False,
            "reason": f"实时流不可回放（标注日 {date} 非当日且无直播归档，历史日无直播归档）"}


def fetch_plate_zt_history(plate_id: str, label_date: str,
                           window_days: int = 5) -> dict:
    """板块涨停家记录（P1-1/G3）：层2 一枪全史 → ≤标注日近 N 个记录日。

    **层2 仅记录有涨停家/爆发日**——记录间缺口=上游缺记≠零涨停（2026-10-29 反查
    实证固化，原「待上游确认」结案：10-16 缺口日 HisDaBanList 实证机器人链 3 只涨停
    股在场而层2 无记录，见 data/backups/kpl-corpus-probe-20261029-l3l2/）——渲染层
    显式标注缺口率，不伪装连续序列；失败 fail-visible 结构化。
    """
    try:
        from backend.services.kpl_ranking_service import get_plate_daily_history
        payload = get_plate_daily_history(plate_id)
    except Exception as exc:  # noqa: BLE001 — 上游漂移/网络异常不阻断（fail-visible）
        return {"ok": False, "reason": f"fetch_failed: {exc}"}
    if not payload.get("ok"):
        return {"ok": False, "reason": "payload_not_ok"}
    past = [r for r in (payload.get("items") or [])
            if str(r.get("date") or "") <= str(label_date)]
    return {"ok": True, "zt_rows": past[-window_days:]}


def live_entries_for_board(live_payload: dict, board: str,
                           date: str) -> tuple[list[dict], dict]:
    """直播流 → 该板块相关播报条目（关键词口径复用 digest.board_keywords 单一实现）。

    - **实时流仅标注时点可得**：窗口内无标注日条目（回填历史日）→ meta.unavailable
      结构化降级（不把今天的播报冒充历史日语料，防 look-ahead 泄漏）；
    - 匹配：条目日=标注日；有板块名条目按 plate 双向包含或正文含关键词；空板块名条目
      仅当正文含关键词且**非大盘综述**（_MARKET_WRAP_RE，2026-10-30f 用户指示：
      整个交易日的全市场播报不贴进板块语料）；
    - 剥离「（该内容由AI大模型根据行情自动生成）」尾注（非播报内容）。
    返回 (entries 升序, meta={total, window 或 unavailable})。
    """
    if not live_payload.get("ok"):
        return [], {"unavailable": live_payload.get("reason") or "unavailable"}
    items = live_payload.get("items") or []
    if not items:
        return [], {"unavailable": "empty_stream"}
    day_items = [it for it in items
                 if time.strftime("%Y-%m-%d", time.localtime(it["ts"])) == str(date)]
    if not day_items:
        return [], {"unavailable": "实时流不可回放，历史日无直播归档"}
    # 2026-10-30f（用户指示）：只收板块相关的时间点语料。大盘综述（空板块名 + 指数/成交
    # 综述词）不进板块播报——这类条目（09:15 开盘/11:30 午盘/15:00 收盘/盘中综述）覆盖
    # 全市场，文本含板块词只是顺带提及，且盘面/总结已由 market_line 与盘面总结行承载；
    # 判别词表由近 5 日归档实测（空板块 71 条中命中 21 条，全部为指数综述；未命中者
    # 均为真实板块/个股播报，如「羊年概念…」「竞价看龙头：…」）。meta 统计（全窗
    # 条数/窗口）用过滤前全量，口径不变
    tmin = min(it["time"] for it in day_items)
    tmax = max(it["time"] for it in day_items)
    meta = {"total": len(day_items), "window": f"{tmin}~{tmax}"}
    day_items = [it for it in day_items
                 if str(it.get("plate_name") or "").strip()
                 or not _MARKET_WRAP_RE.search(str(it.get("comment") or ""))]
    base = digest.normalize_name(board)
    keys = [k for k in digest.board_keywords(board)
            if len(k) >= 2 and digest._CJK_RE.search(k)]   # 纯拉丁/数字锚不得关联（digest 同规）
    entries: list[dict] = []
    for it in day_items:
        plate = digest.normalize_name(str(it.get("plate_name") or ""))
        comment = str(it.get("comment") or "").replace(_AI_GEN_NOTE, "").strip()
        norm_c = digest.normalize_name(comment)
        # 2026-10-30e：plate 命中同步用 keys（后缀桥/别名含其中，如冰雪经济↔冰雪产业），
        # 不再只双向包含 base
        plate_hit = bool(plate and len(plate) >= 2
                         and any(k in plate or plate in k for k in keys))
        text_hit = bool(norm_c and any(k in norm_c for k in keys))
        if plate_hit or text_hit:
            entries.append({"time": it.get("time"), "comment": comment})
    entries.reverse()   # ts 降序 → 升序（旧→新，与家数序列同向）
    return entries, meta


def market_summary_entry(live_payload: dict, date: str) -> dict | None:
    """直播流 → 当日 15:00 收盘总结条目（AMMO 2026-10-30e，用户指示）。

    判定：标注日条目中 time=="15:00" 且 plate_name 空（收盘总结为全市场条目，
    10-29 实测归档在场）；取时间最晚一条，剥离 AI 生成尾注。无归档/非当日/无该
    条目 → None（盘面总结为补充行，缺席不出行，不伪装；直播可用性由 live_line 披露）。
    """
    if not live_payload.get("ok"):
        return None
    day_items = [it for it in live_payload.get("items") or []
                 if time.strftime("%Y-%m-%d", time.localtime(it["ts"])) == str(date)]
    cands = [it for it in day_items
             if str(it.get("time") or "") == "15:00" and not str(it.get("plate_name") or "").strip()]
    if not cands:
        return None
    it = max(cands, key=lambda x: x.get("ts") or 0)
    comment = str(it.get("comment") or "").replace(_AI_GEN_NOTE, "").strip()
    return {"time": it.get("time"), "comment": comment} if comment else None


def fetch_lhb_facts(date: str) -> dict:
    """龙虎榜事实（AMMO 2026-10-30a）：一次取数全日共用，单一源=jev_lhb_ammo.collect_lhb_facts。

    与方向线 task-6 同源（禁第二套取数）；失败/未生成均为结构化降级（collect 内部已
    逐端点捕获，行文由 lhb_line 承担），非 jev 调用、不花 token。主榜（HisBeOnTheLHB）
    生成系统性晚于 17:30 挂链（2026-11-11 实证，约 17:00 生成的是席位榜）：主榜缺席时
    lhb_line 出 C 席位/机构兜底行（已取得事实不丢弃），doc.lhbState 留痕（A），B 补齐链
    主榜到达后定向重跑；三源全空才断言「无上榜」，不伪装（§1.2-8 / §5.4）。
    """
    try:
        return collect_lhb_facts(date)
    except Exception as exc:  # noqa: BLE001 — 双端点均异常的兜底（collect 内部已各端点捕获）
        return {"ok": False, "date": date, "degraded": True,
                "reason": f"fetch_failed: {exc}"}


def _lhb_state_payload(facts: dict | None, *, line_rendered: bool) -> dict | None:
    """A（2026-11-11 用户裁决）：龙虎榜缺席结构化留痕（§1.2-8 落库层 fail-visible）。

    叙事整行缺席不再只活在内存：主榜可用性/端点成功标志/结构化空态/席位机构计数/
    降级原因/出行状态随 doc 落库，供审计、前端展示与补齐链（B）pending 检测。
    facts=None（未传入）→ None。
    """
    if facts is None:
        return None
    f = facts
    return {
        "mainAvailable": bool(f.get("groups") or f.get("stocks")),
        "listOk": bool(f.get("list_ok")),
        "stockOk": bool(f.get("stock_ok")),
        "emptyStructured": bool(f.get("empty_structured")),
        "orderSignCount": int(f.get("order_sign_count") or 0),
        "seatN": len(f.get("stock_board") or {}),
        "agencyN": len(f.get("agency") or {}),
        "degraded": bool(f.get("degraded")),
        "reason": f.get("reason"),
        "lineRendered": bool(line_rendered),
    }


def _lhb_codes_roles(codes: list[str], roles_in: list[tuple[str, str | None]]) -> tuple[list[str], dict[str, str]]:
    """龙虎榜行过滤入参组装（AMMO 2026-10-30a）：相关代码去重 + 身位映射。

    `codes` = 额外相关代码（板内封板成员）；`roles_in` = [(code, 身位|None)]，身位缺省
    「相关个股」。统一取后 6 位（兼容带交易所前缀的代码）。
    """
    roles: dict[str, str] = {}
    ordered: list[str] = []
    for code, role in roles_in:
        k = str(code or "")[-6:]
        if not k:
            continue
        if k not in ordered:
            ordered.append(k)
        if role:
            roles.setdefault(k, role)
    for c in codes:
        k = str(c or "")[-6:]
        if k and k not in ordered:
            ordered.append(k)
    return ordered, roles


def fetch_reason_corpus(db: Any, date: str) -> dict[str, dict]:
    """当日涨停原因伴生语料映射 code → item（2026-11-11 用户裁决改源：单一事实源
    `kpl_daban_pool.reason_items`，2203 推送 collector 盘中即落库）。

    取数走存档器读口 `load_reason_corpus`（禁止第二套解析/第二份库；原 jiuyan
    expound 源已随本裁决淘汰，回退靠 git），一次取全日共用（与基因/热度同哲学）。
    **返回形状（2026-11-11 ①升级）**：dict[code → dict]，只透传**非空**字段（缺位键
    不出现）：`zt` = 异动解析全文（标题+概念解析完整正文，仅折叠换行/多空白为单空格，
    不截断不删节；标题中的「；」分隔保留原样）+ `plate`（热点摘引）+ `rank`/
    `rank_total`（>0 才带）+ `rank_top`（Top 榜名单）+ `zt_group`（涨停梯队串）+
    `fx`/`jc`/`jj`/`pledge`（风险画像族）；`zt_tag` 为数值 tag 无文案映射（实测样本=0）
    → **只透传落库已有，不渲染**（映射实测确认后二次裁决）。降级/异常/空映射 →
    空映射（涨停原因行整段缺席，缺席状态由 load_reason_corpus 结构化 degraded 载荷
    承载，不伪装无原因）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_reason_corpus
        corpus = load_reason_corpus(db, date)
    except Exception:      # 读口异常不阻断投喂：整行缺席，异常不打断整轮
        return {}
    if not corpus.get("ok"):
        logger.warning("reason_corpus degraded date=%s reason=%s",
                       date, corpus.get("reason"))
        return {}

    def _fold(v: Any) -> str:
        return re.sub(r"\s+", " ", str(v or "")).strip()

    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if not code or code in out:
            continue
        fields: dict[str, Any] = {}
        for key in ("zt", "plate", "zt_group", "fx", "jc", "jj", "pledge"):
            val = _fold((item or {}).get(key))
            if val:
                fields[key] = val
        for key in ("rank", "rank_total"):
            v = (item or {}).get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                fields[key] = int(v)
        top = [str(x).strip() for x in ((item or {}).get("rank_top") or [])
               if str(x).strip()]
        if top:
            fields["rank_top"] = top
        if fields:
            out[code] = fields
    return out


def reason_entries_for_leaders(rows: list[dict],
                               reasons: dict[str, dict]) -> list[dict]:
    """涨停原因/热度排名/风险画像三行共用的条目（预登记 §4.1，2026-10-28 用户裁决收窄）：
    **仅待判龙一自身**（2026-11-11 ①条目形状 dict 升级：{"label", "item"}）。

    `rows` = 同板块分轨龙一行（main 优先）；板块成员原因不列（板内同伴由既有「板内
    解析/板内同伴驱动」行承载，不重复）。无该股语料 → item=None（三行各自整段缺席，
    AGENTS §1.2-8）。单一事实源 = `fetch_reason_corpus`（kpl_daban_pool.reason_items）。
    """
    entries: list[dict] = []
    solo = len(rows) == 1   # 2026-11-17 语料精简：单龙一不出重复前缀（同基因条目）
    for row in rows:
        code = str(row.get("code") or "")[-6:]
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        entries.append({"label": "" if solo else f"{seg_cn} {row.get('name') or code}",
                        "item": reasons.get(code)})
    return entries
def fetch_gene_corpus(db: Any, date: str) -> dict[str, dict]:
    """当日涨停基因语料映射 code → gene_item（单一事实源 `kpl_daban_pool.gene_items`）。

    取数走存档器读口 `load_gene_corpus`（禁止第二套解析/第二份库），一次取全日共用。
    未落库/降级/该日无档 → 空映射（调用方出「不可考」行，fail-visible，不伪装无基因）；
    语料条数不完整不影响出已覆盖的股（覆盖度由 gene_pending_n 另行可见）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_gene_corpus
        corpus = load_gene_corpus(db, date)
    except Exception:      # 读口异常不阻断投喂：按「不可考」出行，异常本身上抛会打断整轮
        return {}
    if not corpus.get("ok"):
        return {}
    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if code and code not in out:
            out[code] = item
    return out


def gene_entries_for_leaders(rows: list[dict],
                             genes: dict[str, dict]) -> list[dict]:
    """涨停基因行条目（2026-11-08a）：**仅待判龙一自身**（与涨停原因行同口径）。

    板块成员基因不列——基因是「这只股的历史打板确定性」，板块问题（深度/延续）由结构
    行承载，不重复；无该股语料 → item=None（zt_gene_line 整段缺席，§1.2-8）。
    2026-11-17 语料精简：单龙一（len(rows)==1）label 置空——待判龙头行已锚定
    身份，叙事不出「主板龙一 X」重复前缀；双龙一（板块级）保留轨别前缀。
    """
    entries: list[dict] = []
    solo = len(rows) == 1
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        entries.append({"label": "" if solo else f"{seg_cn} {row.get('name') or code}",
                        "item": genes.get(code)})
    return entries


# 封板质量只看这几列（quotas 具名字段，语义见 kpl_daban_protocol.DABAN_QUOTA_NAMES；
# warn_tag/back_zt/stock_tag/financing_tag 语义未破译或未定，本行不消费）
# 2026-11-08c 纯语料补行：+ zt_time/last_zt_time（首板/回封时点，epoch 秒，
# 消费方 ammo._seal_time_seg 转 Asia/Shanghai HH:MM）
_POOL_QUALITY_FIELDS = ("zt_tur", "max_zt_tur", "real_float", "real_turnover",
                        "main_net", "amount", "price", "pool_state", "last_seen_ts",
                        "zt_time", "last_zt_time")   # 2026-11-08c：+首板/回封时点（纯语料补行）


def fetch_theme_heat(db: Any, date: str) -> dict[str, Any]:
    """2013 题材库热度语料 → {"items": {code: {"name","themes"}}, "degraded": None|原因}。

    单一事实源 = `kpl_daban_pool.theme_items`（走存档器读口 `load_day(lane="theme")`，
    与 2203/gene 通道同库同款合同）；一次取全日共用。
    降级（日档缺失/语料未落库/读口异常）→ items 空映射 + `degraded` 带结构化原因
    （与封板质量行同款评审口径：「读不到」不得让下游伪装成「今日不在涨停池」）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_theme_corpus
        corpus = load_theme_corpus(db, date)
    except Exception:      # 读口异常不阻断投喂：带原因降级（fail-visible）
        return {"items": {}, "degraded": "load_error"}
    if not corpus.get("ok"):
        return {"items": {},
                "degraded": str(corpus.get("reason") or "no_theme_corpus")}
    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if code and code not in out:
            out[code] = {"name": item.get("name"),
                         "themes": list(item.get("themes") or [])}
    return {"items": out, "degraded": None}


def theme_heat_entries_for_leaders(rows: list[dict], corpus: dict[str, Any]) -> list[dict]:
    """题材热度行条目（2026-11-08d）：**仅待判龙一自身**（与基因/封板质量同口径）。

    板块成员不列（题材热度是个股题材库画像，板块问题由结构/板块强度行承载）；
    `poolMissing` = 语料整体降级原因，仅当语料在场且查无此股时才算真不在池
    （与封板质量行同款评审口径）。themes=None（缺该股）与 []（题材库为空）分开。
    """
    items = corpus.get("items") or {}
    degraded = corpus.get("degraded")
    entries: list[dict] = []
    solo = len(rows) == 1   # 2026-11-17 语料精简：单龙一不出重复前缀（同基因条目）
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        hit = items.get(code)
        entries.append({"label": "" if solo else f"{seg_cn} {row.get('name') or code}",
                        "themes": (hit or {}).get("themes"),
                        "poolMissing": None if hit else degraded})
    return entries


def fetch_notice_corpus(db: Any, date: str) -> dict[str, Any]:
    """公告计数语料 → {"items": {code: item}, "degraded": None|原因}。

    单一事实源 = `kpl_daban_pool.notice_items`（走 load_day(lane="notice")）；与 gene 通道
    同款懒取落库（每轮限量、pending_n 暴露覆盖度），降级带结构化原因（fail-visible）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_notice_corpus
        corpus = load_notice_corpus(db, date)
    except Exception:
        return {"items": {}, "degraded": "load_error"}
    if not corpus.get("ok"):
        return {"items": {},
                "degraded": str(corpus.get("reason") or "no_notice_corpus")}
    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if code and code not in out:
            out[code] = item
    return {"items": out, "degraded": None}


def notice_entries_for_leaders(rows: list[dict], corpus: dict[str, Any]) -> list[dict]:
    """公告计数行条目：仅待判龙一自身（与基因/封板质量/题材热度同口径）。"""
    items = corpus.get("items") or {}
    degraded = corpus.get("degraded")
    entries: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        hit = items.get(code)
        entries.append({"label": f"{seg_cn} {row.get('name') or code}",
                        "item": hit,
                        "poolMissing": None if hit else degraded})
    return entries


def fetch_pool_quality(db: Any, date: str) -> dict[str, Any]:
    """当日涨停池量价语料 → {"items": {code: {"item","frameAt"}}, "degraded": None|原因}。

    单一事实源 = `kpl_daban_pool` 日档 items（走存档器读口 `load_day(lane="pool")`，
    与 /daban-list 同源，禁止第二套解析）；一次取全日共用。
    降级（日档缺失/读口异常/当日池空）→ items 空映射 + `degraded` 带结构化原因
    （评审 2026-11-08 P1：「读不到」必须原样透出，不得让下游伪装成「今日不在涨停池」），
    不阻断投喂。`frameAt` = 该股最后一帧的采集时刻（Asia/Shanghai），由 ops 层算好，
    让 ammo 保持确定性纯函数（不依赖时区/时钟）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_day
        payload = load_day(db, date, lane="pool")
    except Exception:      # 读口异常不阻断投喂：带原因降级（fail-visible）
        return {"items": {}, "degraded": "load_error"}
    if not payload.get("ok"):
        return {"items": {},
                "degraded": str(payload.get("reason") or "no_archive")}
    if payload.get("empty"):
        # 「采集成功且池为空」也是降级（对 THS 侧封板的龙头是两源矛盾），不冒充「不在池」
        return {"items": {}, "degraded": "pool_empty"}
    out: dict[str, dict] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("stock_id") or "")[-6:]
        if not code or code in out:
            continue
        out[code] = {"item": {k: item.get(k) for k in _POOL_QUALITY_FIELDS},
                     "frameAt": _frame_hhmm(item.get("last_seen_ts"))}
    return {"items": out, "degraded": None}


def _frame_hhmm(ts: Any) -> str | None:
    """采集帧时间戳（epoch 秒，collector 本地时区）→ "HH:MM"；不可解析 → None。"""
    try:
        val = float(ts)
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return datetime.fromtimestamp(val, TZ_SHANGHAI).strftime("%H:%M")


def seal_quality_entries_for_leaders(rows: list[dict],
                                     quality: dict[str, dict]) -> list[dict]:
    """封板质量行条目（2026-11-08b）：**仅待判龙一自身**（题集 v16 判据引用源口径）。

    `unsealed=True`（断板反包候选，题面续板⑤）= 该股今日未封板 → 行内明示本行不适用，
    不拿往期封单冒充当日封板质量；`poolMissing` = 涨停池语料整体降级原因（评审 P1：
    「读不到」≠「不在池」，两者在行内分开表述）——仅当语料在场且查无此股时才算真不在池。
    """
    items = quality.get("items") or {}
    degraded = quality.get("degraded")
    entries: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        hit = items.get(code) or {}
        entries.append({"label": f"{seg_cn} {row.get('name') or code}",
                        "stockId": code,
                        "item": hit.get("item"),
                        "frameAt": hit.get("frameAt"),
                        "unsealed": row.get("leaderSealedToday") is False,
                        # 2026-11-18 天普案：停牌/数据洞三态透传（叙事分支用）
                        "dayStatus": row.get("dayStatus"),
                        "poolMissing": None if hit else degraded})
    return entries


# ── 2026-11-11 语料缺口补全（①→④）：bid/zb/dt 三通道 + 2112/3004/3101 落库 +
#    个股详情四通道（2014/2202/2030/2010）。全部走存档器读口单一事实源，一次取全日共用。

def fetch_daban_lanes(db: Any, date: str) -> dict[str, Any]:
    """bid/zb/dt 三通道日档 → {"bid": {code: item}, ..., "bidLane": "ok"|"missing"...}。

    单一事实源 = `load_day(lane=bid/zb/dt)`；lane 状态："ok"（采集成功，含「采集成功
    且池为空」空档），“missing:<原因>”（无档/读口异常，结构化原因透出）。条目归一
    code（后 6 位）→ 2103 具名字段 dict（bidding_pct/bidding_amount/zt_time/open_time
    等，原样不换算）。读口异常不阻断投喂（对应 lane 置 missing）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_day
    except Exception:      # 模块不可达（极端）：三通道全部置 missing，不阻断投喂
        return {"bid": {}, "zb": {}, "dt": {}, "bidLane": "missing:import_error",
                "zbLane": "missing:import_error", "dtLane": "missing:import_error"}
    out: dict[str, Any] = {}
    for lane in ("bid", "zb", "dt"):
        try:
            payload = load_day(db, date, lane=lane)
        except Exception:
            payload = {"ok": False, "reason": "load_error"}
        items: dict[str, dict] = {}
        if payload.get("ok"):
            for it in payload.get("items") or []:
                code = str((it or {}).get("stock_id") or "")[-6:]
                if code and code not in items:
                    items[code] = it
            out[f"{lane}Lane"] = "ok"
        else:
            out[f"{lane}Lane"] = f"missing:{payload.get('reason') or 'no_archive'}"
        out[lane] = items
    return out


def bid_entries_for_leaders(rows: list[dict], lanes: dict[str, Any]) -> list[dict]:
    """竞价承接行条目：仅待判龙一自身（与基因/封板质量同口径）。item=None = 缺该股。"""
    bid_items = lanes.get("bid") or {}
    entries: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")[-6:]
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        entries.append({"label": f"{seg_cn} {row.get('name') or code}",
                        "item": bid_items.get(code)})
    return entries


def zhaban_detail_for_board(row: dict, lanes: dict[str, Any]) -> list[dict]:
    """板内炸板明细条目：row.boardCodes ∩ zb_items → [{name, zt_time, open_time}]。

    板块成员取自结构行 boardCodes（触板未封二分口径）；时刻字段原样透传（渲染层
    _hhmm_from_ts 归一，不可读缺席）。
    """
    zb_items = lanes.get("zb") or {}
    detail: list[dict] = []
    for c in row.get("boardCodes") or []:
        it = zb_items.get(str(c)[-6:])
        if isinstance(it, dict):
            detail.append({"name": it.get("name") or str(c)[-6:],
                           "zt_time": it.get("zt_time"),
                           "open_time": it.get("open_time")})
    return detail


def dt_names_for_board(row: dict, lanes: dict[str, Any]) -> tuple[list[str], bool]:
    """板内跌停名单 + lane 可用性：(names, lane_ok)。lane ok 且板内无成员 → ([], True)。"""
    lane_ok = lanes.get("dtLane") == "ok"
    dt_items = lanes.get("dt") or {}
    names: list[str] = []
    for c in row.get("boardCodes") or []:
        it = dt_items.get(str(c)[-6:])
        if isinstance(it, dict):
            names.append(str(it.get("name") or str(c)[-6:]))
    return names, lane_ok


def fetch_lhb_forecast_corpus(db: Any, date: str) -> dict[str, Any]:
    """2112 上榜预测落库语料 → {"items": {code: item}, "laneOk": bool}（单一事实源
    `load_lhb_forecast`，fc_ 前缀日档）。降级（无档/未落库/读口异常）→ 空映射 +
    laneOk=False（上榜预测行整行缺席，不伪装空榜）。"""
    try:
        from backend.services.kpl_daban_archiver import load_lhb_forecast
        corpus = load_lhb_forecast(db, date)
    except Exception:
        return {"items": {}, "laneOk": False}
    if not corpus.get("ok"):
        logger.warning("lhb_forecast_corpus degraded date=%s reason=%s",
                       date, corpus.get("reason"))
        return {"items": {}, "laneOk": False}
    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if code and code not in out:
            out[code] = item
    return {"items": out, "laneOk": True}


def fetch_lhb_realtime_corpus(db: Any, date: str) -> dict[str, Any]:
    """3004/3101 实时龙虎榜落库语料 → {"items": {code: item}, "laneOk": bool}（单一
    事实源 `load_lhb_realtime`，rt_ 前缀日档）。降级语义同上榜预测行。"""
    try:
        from backend.services.kpl_daban_archiver import load_lhb_realtime
        corpus = load_lhb_realtime(db, date)
    except Exception:
        return {"items": {}, "laneOk": False}
    if not corpus.get("ok"):
        logger.warning("lhb_realtime_corpus degraded date=%s reason=%s",
                       date, corpus.get("reason"))
        return {"items": {}, "laneOk": False}
    out: dict[str, dict] = {}
    for item in corpus.get("items") or []:
        code = str((item or {}).get("stock_id") or "")[-6:]
        if code and code not in out:
            out[code] = item
    return {"items": out, "laneOk": True}


def _scope_entries(ordered_codes: list[str], roles: dict[str, str],
                   items: dict[str, dict]) -> list[dict]:
    """龙虎榜行同款相关个股集合 → 上榜预测/实时榜条目（身位标签 + 归一 item）。"""
    return [{"label": f"{roles.get(k, '相关个股')} {k}", "item": (items or {}).get(k)}
            for k in ordered_codes]


def fetch_stock_detail_corpus(db: Any, date: str) -> dict[str, Any]:
    """个股详情四通道（2014/2202/2030/2010）落库语料 →
    {"items": {code: {"bdo"|"bf"|"abn"|"rplate": item}}, "lanes": {lane: "ok"|"missing:<原因>"}}。

    单一事实源 = `load_stock_detail_corpus(lane=...)`；lane 状态口径与 fetch_daban_lanes
    同款（"ok" 含空档；降级不伪装）。读口异常不阻断投喂（对应 lane 置 missing）。
    """
    try:
        from backend.services.kpl_daban_archiver import load_stock_detail_corpus
    except Exception:
        return {"items": {}, "lanes": {k: "missing:import_error"
                                       for k in ("bdo", "bf", "abn", "rplate")}}
    out: dict[str, Any] = {"items": {}}
    lanes_state: dict[str, str] = {}
    per_lane: dict[str, dict[str, dict]] = {k: {} for k in ("bdo", "bf", "abn", "rplate")}
    for lane in ("bdo", "bf", "abn", "rplate"):
        try:
            payload = load_stock_detail_corpus(db, date, lane=lane)
        except Exception:
            payload = {"ok": False, "reason": "load_error"}
        if payload.get("ok"):
            for it in payload.get("items") or []:
                code = str((it or {}).get("stock_id") or "")[-6:]
                if code:
                    per_lane[lane][code] = it
            lanes_state[lane] = "ok"
        else:
            lanes_state[lane] = f"missing:{payload.get('reason') or 'no_archive'}"
    for code in {c for m in per_lane.values() for c in m}:
        out["items"][code] = {lane: per_lane[lane][code]
                              for lane in ("bdo", "bf", "abn", "rplate")
                              if per_lane[lane].get(code)}
    out["lanes"] = lanes_state
    return out


def detail_lines_for_leader(row: dict, detail_corpus: dict[str, Any],
                            theme_heat_corpus: dict[str, Any]) -> dict[str, str | None]:
    """个股级四条详情通道叙事行（2014/2202/2030/2010）一次性拼装（纯函数）。

    返回 {"ztBigOrder", "bfReason", "abnormalPrice", "relatedPlate"}；lane 降级或
    缺该股 → 对应行 None（整行缺席，AGENTS §1.2-8）。板块归属行的已知题材 = 题材
    热度语料该股 themes 名称集 + 待判板块名（避免与题材热度行重复）。
    """
    code = str(row.get("code") or "")[-6:]
    seg = row.get("segment")
    seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
    label = f"{seg_cn} {row.get('name') or code}"
    det = (detail_corpus.get("items") or {}).get(code) or {}
    lanes = detail_corpus.get("lanes") or {}
    heat = ((theme_heat_corpus.get("items") or {}).get(code) or {}).get("themes") or []
    known = [str((t or {}).get("name") or "").strip() for t in heat if (t or {}).get("name")]
    entries = [{"label": label}]
    from backend.analysis.hotlist import theme_leader_ammo as _ammo
    return {
        "ztBigOrder": (_ammo.zt_big_order_line(
            [{**entries[0], "item": det.get("bdo")}])
            if lanes.get("bdo") == "ok" else None),
        "bfReason": _ammo.bf_reason_line(
            [{**entries[0], "item": det.get("bf")}]),
        "abnormalPrice": (_ammo.abnormal_price_line(
            [{**entries[0], "item": det.get("abn")}])
            if lanes.get("abn") == "ok" else None),
        "relatedPlate": (_ammo.related_plate_line(
            [{**entries[0], "item": det.get("rplate"), "knownThemes": known,
              "board": str(row.get("board") or "")}])
            if lanes.get("rplate") == "ok" else None),
    }


def fetch_regulatory_corpus(db: Any, date: str) -> dict:
    """监管风险语料（2026-11-15 预登记）：kpl_daban_pool reg_ 前缀日档 →
    {"byCode", "laneOk", "reason", "states"}。单一事实源 load_regulatory_corpus；
    读口异常不阻断投喂（laneOk=False，叙事行缺席 + 结构化留痕）。竞价链复用本函数。"""
    try:
        from backend.services.kpl_daban_archiver import load_regulatory_corpus
        corpus = load_regulatory_corpus(db, date)
    except Exception:
        return {"byCode": {}, "laneOk": False, "reason": "import_error", "states": {}}
    if not corpus.get("ok"):
        return {"byCode": {}, "laneOk": False,
                "reason": corpus.get("reason") or "no_archive", "states": {}}
    return {"byCode": corpus.get("by_code") or {}, "laneOk": True, "reason": None,
            "states": corpus.get("states") or {}}


def _resume_date_from_regulatory(recent: list[dict] | None, date: str) -> str | None:
    """停牌复牌日单源=监管语料 recent 组（2026-11-18 天普案；review M2 修复）。

    上游 List_His 原序无排序保证（kpl_regulatory_risk 按原序构建）：按
    abnormal_date 最大（≤date）选取最近一次停牌记录的 resume_date，不依赖
    列表顺序——多次停牌股不得取陈旧复牌日；缺则 None（不可考，不伪造）。
    """
    cands = [x for x in recent or []
             if isinstance(x, dict) and x.get("suspended_flag") and x.get("resume_date")
             and (x.get("abnormal_date") or "") <= date]
    if not cands:
        return None
    return max(cands, key=lambda x: x.get("abnormal_date") or "").get("resume_date")


def regulatory_entries_for_codes(codes: list[str], roles: dict[str, str],
                                 corpus: dict) -> list[dict]:
    """相关个股集合 → 监管风险行 entries（身位标签 + reg_by_code 索引项；无命中缺席）。"""
    by = (corpus or {}).get("byCode") or {}
    return [{"label": roles.get(k, "相关个股"), "code": k, "hit": by[k]}
            for k in codes if by.get(k)]


def _regulatory_state(corpus: dict, entries: list[dict]) -> dict:
    """regulatoryState 结构化留痕（审计/前端用，不进叙事）。"""
    return {"laneOk": bool((corpus or {}).get("laneOk")),
            "reason": (corpus or {}).get("reason"),
            "hitCodes": [str((e or {}).get("code") or "") for e in entries or []]}


# 代际来源：`live` = 当日挂链（17:30，2026-10-30 改时；前瞻样本）；`backfill` = 事后补跑历史日。
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
        line = "交易日轴：不可算"
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
        line = "交易日轴：" + " · ".join(found)
        if srcs - {"bridge"}:
            # 2026-10-24d review 处置：非 bridge 源结果**不缓存**——bridge 恢复后重算即升级，
            # 缓存会把 weekday 启发行固化整天；重算成本 ≤15 次缓存查表，不值得换质量损失
            line += "（节假日顺延未经验证）"
        else:
            _FWD_AXIS_CACHE[date] = line
    else:
        line = "交易日轴：不可算"
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
# v17 个股级 2→4 题（+催化硬度/身位稳固度，输出再增两答）：固定开销预标 2,200/3,300
# （预登记 v17 §4；叙事另增板块判定/基础率两行 ≈80 字）。**首个 v17 status=ok 日后
# 必须逐条补账 _REAL_COST_LEDGER_V17**（v5 §14.2 纪律：不补账=护栏失去校准依据）。
TOKENS_PER_CHAR_LOW, TOKENS_PER_CHAR_HIGH = 0.80, 1.05
TOKENS_FIXED_LOW = 2200
TOKENS_FIXED_HIGH = 3300
# v17 板块判定行注入预算预留（字符上界）：构建时板块 doc 尚未标注（同轮先板块后个股），
# 标注时注入的行最长 ≈70 字，按 120 字预留进整日护栏（上界口径，不虚报）。
SECTOR_JUDGMENT_RESERVE_CHARS = 120
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
    """当日各板块龙头结构事实行（v17 三链合一换源，2026-11-09 用户裁决）。

    候选「谁」单源 = **当日板块节点档**（hotlist_jev_sector_nodes v5，空间龙一
    main 轨折叠单龙）——龙一只算一次落一次库，本链不再自推。day_leader_rows(
    space_mode) 同参重算仅用于**取结构事实行**（gain10/leaderSealedToday/prevPeers/
    ladderShape 等打标语料必需字段），按 (board, code) 过滤只保留与节点档一致的行。

    fail-visible（不回退自推导——回退等于两口径复活）：
    - 节点档缺失/非 ok/非 v5 → (None, meta)，meta.reason 区分 sector_nodes_missing /
      sector_nodes_not_ok / sector_nodes_version（调用方跳过当日并披露）。
    - 节点档龙头无事实行（韭研盘后重采修正漂移）→ 该板块**跳过不打标**，
      meta.driftBoards 披露（不伪造事实行）。
    - 事实行多余板块/个股（推导与节点档不一致）→ 丢弃，meta.droppedBoards 披露。
    - THS 池缺失（rows=None）原语义不变。

    2026-11-01 用户裁决（窗位 k=T−S−1，近 3 封板日池）由 day_leader_rows 同参保留；
    2026-10-27 空间龙一规则不变（历史基线窗口仍走默认 streak 口径，样本不漂移）。
    """
    node_doc = db["hotlist_jev_sector_nodes"].find_one({"_id": f"{date}:SECTOR_NODES"})
    if node_doc is None:
        return None, {"reason": "sector_nodes_missing"}
    if node_doc.get("status") != "ok":
        return None, {"reason": "sector_nodes_not_ok", "status": node_doc.get("status")}
    # 版本契约常量单点（P2-9 评审）：与 SECTOR_NODE_VERSION 同步升代，禁止旧代档冒充新口径
    from backend.analysis.hotlist.sector_nodes import SECTOR_NODE_VERSION
    if str(node_doc.get("version") or "") != SECTOR_NODE_VERSION:
        return None, {"reason": "sector_nodes_version", "version": node_doc.get("version")}
    node_leaders: dict[str, dict[str, Any]] = {}
    for r in node_doc.get("rows") or []:
        lead = r.get("leader") or {}
        if not lead.get("code"):
            continue
        node_leaders[str(r.get("board"))] = {
            "code": str(lead["code"]), "name": lead.get("name"),
            "streak": lead.get("streak"), "time": lead.get("time"),
            # 2026-11-18 天普案：续断三态/区间高度单源=节点档（day_status_of），
            # 旧档无 dayStatus 键→不覆盖（历史口径不变，fail-visible）
            "dayStatus": lead.get("dayStatus"),
            "leaderSealedToday": lead.get("leaderSealedToday"),
            "poolDay": lead.get("poolDay"), "days": lead.get("days"),
            "boards": lead.get("boards")}
    prev_dates = trading_dates_before(db, date, 3, dataset_id)
    rows, meta = day_leader_rows(db, date, dataset_id,
                                 prev_date=prev_dates[-1] if prev_dates else None,
                                 space_mode=True, pool_dates=prev_dates)
    meta = dict(meta or {})
    if rows is None:
        return None, meta
    out: list[dict] = []
    matched: set[str] = set()
    dropped: list[str] = []
    for r in rows:
        b = str(r.get("board") or "")
        lead = node_leaders.get(b)
        if lead is None:
            dropped.append(f"{b}:{r.get('code')}")
            continue
        if str(r.get("code")) == lead["code"]:
            # 2026-11-18：节点档带 dayStatus（新代）→ 续断/区间高度以节点单源覆盖
            # day_leader_rows 池二分 bool（停牌被伪装断板反包候选事故）；
            # leaderSealedToday 三态 None 也覆盖（suspended/unknown 不伪装 False）。
            if lead.get("dayStatus") is not None:
                for _k in ("dayStatus", "leaderSealedToday", "poolDay", "days", "boards"):
                    r[_k] = lead.get(_k)
            out.append(r)
            matched.add(b)
        else:
            # 同板块非节点龙一的推导行（含 growth 轨）丢弃——节点单龙为准，逐行留痕
            dropped.append(f"{b}:{r.get('code')}!={lead['code']}")
    drift = sorted(b for b in node_leaders if b not in matched)
    if dropped:
        meta["droppedBoards"] = dropped
    if drift:
        meta["driftBoards"] = drift
    return out, meta


def reconcile_superseded_leaders(db: Any, date: str, rows: list[dict] | None) -> dict:
    """单一龙头不变式对账（2026-10-24 双龙头事故后加）：同 (date, board[, segment]) 只留现任推导龙一。

    成因：15:35 final 快照与盘后重采之间推导会变（韭研盘后修正板数/分组），8001 重启
    触发幂等重跑补标新任龙头（如 10-23 大业股份）后，旧任龙头行（赛福天）无人退位，
    双行并存冒充双龙头。对账把同 board 下 code∉现任 的历史行显式退位（leaderSuperseded/
    supersededBy/supersededAt），**不删除**（真实调用成本留审计，Mongo 可查）；
    幂等（已退位且 supersededBy 相同则不重盖）。rows=None/空（THS 池缺失推导不可得）
    → 不动历史（fail-visible，不猜现任）。

    v12 分轨语义（预登记 §2.2）：①带 segment 的 v12 行按 (board, segment) 分组对账；
    ②**存量 legacy 行（无 segment，v11 及以前）不自动退位**——仅当同 (date, board)
    已存在分轨现任（v12 行）且其 code 不在现任集合时才退位（supersededBy=该板块
    现任之一）；③板块级 doc（docKind=sector，code=None）永不退位。同日重跑时旧任
    龙头 doc 若仍为现任（同 _id）由 replace_one 原位换代，不经本函数。
    """
    if not rows:
        return {"superseded": 0, "boards": 0, "details": []}
    col = db[COLLECTION]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    ok_filter = {"status": {"$in": ["ok", "degraded"]},
                 "leaderSuperseded": {"$ne": True}, "docKind": {"$ne": DOC_KIND_SECTOR}}
    # ① 分轨现任：v12 行带 segment，按 (board, segment) 对账
    seg_groups: dict[tuple[str, str], set[str]] = {}
    board_current: dict[str, set[str]] = {}
    for r in rows:
        b, c = str(r["board"]), str(r["code"])
        board_current.setdefault(b, set()).add(c)
        seg = r.get("segment")
        if seg:
            seg_groups.setdefault((b, str(seg)), set()).add(c)
    details: list[dict] = []
    total = 0
    for (board, seg), current in sorted(seg_groups.items()):
        cur = sorted(current)
        res = col.update_many(
            {"tradingDate": date, "board": board, "segment": seg,
             "code": {"$nin": cur}, **ok_filter},
            {"$set": {"leaderSuperseded": True, "supersededBy": cur[0],
                      "supersededAt": now}})
        if res.modified_count:
            total += res.modified_count
            details.append({"board": f"{board}[{seg}]", "currentLeader": cur[0],
                            "superseded": res.modified_count})
    # ② legacy 行（无 segment）：仅当该板块已有 v12 分轨现任且 legacy code 不在现任时退位
    # ③ 推导行本身全部无 segment（旧调用方/测试夹具）→ 回退 §18.2 原板级对账语义
    if not seg_groups:
        for board in sorted(board_current):
            cur = sorted(board_current.get(board) or set())
            if not cur:
                continue
            res = col.update_many(
                {"tradingDate": date, "board": board,
                 "code": {"$nin": cur, "$ne": None}, **ok_filter},
                {"$set": {"leaderSuperseded": True, "supersededBy": cur[0],
                          "supersededAt": now}})
            if res.modified_count:
                total += res.modified_count
                details.append({"board": board, "currentLeader": cur[0],
                                "superseded": res.modified_count})
    else:
        for board in sorted({b for b, _s in seg_groups}):
            cur = sorted(board_current.get(board) or set())
            if not cur:
                continue
            res = col.update_many(
                {"tradingDate": date, "board": board, "segment": {"$exists": False},
                 "code": {"$nin": cur, "$ne": None}, **ok_filter},
                {"$set": {"leaderSuperseded": True, "supersededBy": cur[0],
                          "supersededAt": now}})
            if res.modified_count:
                total += res.modified_count
                details.append({"board": f"{board}[legacy]", "currentLeader": cur[0],
                                "superseded": res.modified_count})
    if total:
        print(f"{date} 龙头对账：退位 {total} 行（推导已不再指向；"
              f"{'；'.join(d['board'] + '→' + d['currentLeader'] for d in details)}）")
    return {"superseded": total, "boards": len(seg_groups) or len(board_current),
            "details": details}


def build_one(db: Any, date: str, row: dict, rows_baseline: list[dict],
              dataset_id: str = DEFAULT_DATASET_ID,
              board_history: dict[str, list[tuple[str, int]]] | None = None,
              strength_match: dict | None = None,
              reason_entries: list[tuple[str, str | None]] | None = None,
              gene_entries: list[dict] | None = None,
              theme_heat_entries: list[dict] | None = None,
              notice_entries: list[dict] | None = None,
              seal_quality_entries: list[dict] | None = None,
              series_line: str | None = None,
              segment: str | None = None,
              live_line: str | None = None,
              lhb_facts: dict | None = None,
              rebound_line: str | None = None,
              cycle: dict | None = None,
              bid_line: str | None = None,
              dt_line: str | None = None,
              detail_lines: dict[str, str | None] | None = None,
              regulatory_line: str | None = None,
              regulatory_state: dict | None = None,
              sector_judgment: dict | None = None,
              base_rate_stats: dict | None = None) -> dict:
    """组装一条**个股级**投喂（叙事 + 附带元数据），零网络零模型（v17 四题）。

    2026-11-11 语料缺口补全新增入参（均 None 不出行）：`bid_line`（竞价承接行）、
    `dt_line`（板内跌停行）、`detail_lines`（个股详情四通道行 dict：
    ztBigOrder/bfReason/abnormalPrice/relatedPlate，detail_lines_for_leader 产出）、
    热度排名/风险画像两行由 reason_entries 直接派生（单一事实源），不另传入参。
    v17 新增入参：`sector_judgment`（板块级 doc answers，板块判定行 join；同轮标注
    时由 run() 在标注前注入，构建时仅库读兜底）、`base_rate_stats`（续板基础率锚
    统计，live_base_rate 产出）；均 None 不出行（旧调用形状不变）。
    **2026-11-17 语料精简（用户裁决）**：龙头题面零消费行删除——market_line/
    market_summary/forecast_line/realtime_lhb_line 入参已删（盘面事实/盘面总结/
    上榜预测/实时龙虎榜不再进龙头叙事；板块级 build_sector_one 不受影响，
    fc_items/rt_items 落库不动）；家数序列缺席/周期缺席留结构化字段
    boardHistoryState/cycleState（fail-visible，叙事不占字）。
    """
    # boardCodes 缺失/为空时传 None（空集会把 L2 全过滤掉，属危险默认；显式回退全量口径+披露）
    sealed = frozenset(row.get("boardCodes") or ())
    block = digest.build_theme_evidence_block(db, board_name=row["board"], date=date,
                                              leader_code=str(row.get("code") or ""),
                                              sealed_codes=sealed or None)
    # 打标交叉（AMMO 2026-10-27b）：零调用 join 打标链当日该股行（final>midday）
    driver_doc = fetch_driver_label(db, date, str(row.get("code") or ""))
    # 龙虎榜事实行（AMMO 2026-10-30a）：待判龙一优先 + 板内封板成员，lhb_facts=None 不出行
    lhb_codes, lhb_roles = _lhb_codes_roles(
        [str(c) for c in (row.get("boardCodes") or [])],
        [(str(row.get("code") or ""), "待判龙一")])
    lhb_facts_line = (lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles)
                      if lhb_facts is not None else None)
    narrative = build_leader_narrative(
        date=date,
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
        seal_quality_line=seal_quality_line(seal_quality_entries or []),
        plate_strength=plate_strength_line(strength_match) if strength_match is not None else None,
        series_line=series_line,
        live_line=live_line,
        baseline=baseline_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        headroom=headroom_anchor_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        driver_cross=driver_cross_line(driver_doc),
        gene_line=zt_gene_line(gene_entries or []),
        theme_heat_line=theme_heat_line(theme_heat_entries or []),
        notice_count_line=notice_count_line(notice_entries or []),
        reason_line=limitup_reason_line(reason_entries or []),
        bf_reason_line=(detail_lines or {}).get("bfReason"),
        popularity_rank_line=popularity_rank_line(reason_entries or []),
        risk_line=risk_profile_line(reason_entries or []),
        regulatory_line=regulatory_line,
        abnormal_price_line=(detail_lines or {}).get("abnormalPrice"),
        related_plate_line=(detail_lines or {}).get("relatedPlate"),
        zt_big_order_line=(detail_lines or {}).get("ztBigOrder"),
        bid_line=bid_line,
        dt_line=dt_line,
        lhb_facts_line=lhb_facts_line,
        rebound_line=rebound_line,
        evidence_block=block["text"],
        leader_name=str(row.get("name") or ""),
        leader_code=str(row.get("code") or ""),
        segment=row.get("segment"),
        # v15 P1（2026-11-17 收窄）：结构事实行只留周期状态+未封板场景标记
        facts_line=structure_facts_line(row, cycle),
        # v17：续板基础率锚行（先验底单一事实源）+ 板块判定行（A2 跨题修复）
        base_rate_line=base_rate_line(base_rate_stats),
        sector_judgment_line=sector_judgment_line(sector_judgment),
    )
    return {"docKind": DOC_KIND_LEADER, "narrative": narrative, "evidence": block,
            "regulatoryState": regulatory_state,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_facts_line is not None),
            # 2026-11-17 语料精简：叙事不再投喂的缺席状态留结构化字段（fail-visible）
            "boardHistoryState": ("missing" if board_history is not None
                                  and not board_history.get(row["board"]) else None),
            "cycleState": (cycle or {}).get("state") or None,
            # v17：板块判答注入状态（构建时仅库读兜底；同轮注入由 run() 标注前终裁）
            "sectorJudgmentState": ("injected" if "板块判定：" in narrative else None),
            "driverCross": {"found": bool(driver_doc),
                            "labelSlot": (driver_doc or {}).get("labelSlot"),
                            "questionSetVersion": (driver_doc or {}).get("questionSetVersion")},
            "chars": len(narrative),
            "estimatedTokens": estimate_tokens(len(narrative))}


def build_sector_one(db: Any, date: str, board_rows: list[dict],
                     rows_baseline: list[dict],
                     dataset_id: str = DEFAULT_DATASET_ID,
                     market_line: str | None = None,
                     board_history: dict[str, list[tuple[str, int]]] | None = None,
                     strength_match: dict | None = None,
                     reason_entries: list[dict] | None = None,
                     series_line: str | None = None,
                     live_line: str | None = None,
                     market_summary: str | None = None,
                     lhb_facts: dict | None = None,
                     dt_line: str | None = None,
                     regulatory_line: str | None = None,
                     regulatory_state: dict | None = None,
                     forecast_line: str | None = None,
                     realtime_lhb_line: str | None = None) -> dict:
    """组装一条**板块级**投喂（v12 A2 拆题：深度/延续题每板块一次，预登记 §2.3）。

    `board_rows` = 该板块分轨龙一行（≤2，main 优先）；基线/梯队/炸板面以首轨龙一为参照行
    （分轨锚缺位如实，历史窗人群不随规则换代）；无空间锚行与个股打标交叉行（见
    `build_sector_narrative` docstring）。零网络零模型。
    """
    from backend.operations.jev_label_jiuyan import market_facts_line

    if not board_rows:
        raise ValueError("build_sector_one: board_rows 不能为空")
    if market_line is None:
        market_line = market_facts_line(db, date, dataset_id)
    ref = board_rows[0]
    sealed = frozenset(ref.get("boardCodes") or ())
    # 龙虎榜事实行（AMMO 2026-10-30a）：双龙一（轨别身位）+ 板内封板成员
    lhb_codes, lhb_roles = _lhb_codes_roles(
        [str(c) for c in (ref.get("boardCodes") or [])],
        [(str(r.get("code") or ""),
          {"main": "主板龙一", "growth": "双创龙一"}.get(r.get("segment"), "龙一"))
         for r in board_rows])
    lhb_facts_line = (lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles)
                      if lhb_facts is not None else None)
    block = digest.build_theme_evidence_block(db, board_name=ref["board"], date=date,
                                              leader_code="",
                                              sealed_codes=sealed or None)
    narrative = build_sector_narrative(
        date=date,
        market_line=market_line,
        forward_axis=forward_date_axis_line(date),
        structure=structure_line_dual(
            board=ref["board"], board_n=ref["boardN"], leader_rows=board_rows,
            prev_board_n=ref.get("prevBoardN"), prev_peers=ref.get("prevPeers"),
            prev_total=ref.get("prevTotal"), prev_still=ref.get("prevStill"),
            history=board_history.get(ref["board"], []) if board_history is not None else None),
        ladder_line=board_ladder_line(ref),
        zhaban_line=board_zhaban_line(ref),
        dt_line=dt_line,
        plate_strength=plate_strength_line(strength_match) if strength_match is not None else None,
        series_line=series_line,
        live_line=live_line,
        market_summary=market_summary,
        baseline=baseline_line(rows_baseline, ref, BASELINE_MIN_SAMPLES),
        reason_line=limitup_reason_line(reason_entries or []),
        popularity_rank_line=popularity_rank_line(reason_entries or []),
        risk_line=risk_profile_line(reason_entries or []),
        regulatory_line=regulatory_line,
        forecast_line=forecast_line,
        lhb_facts_line=lhb_facts_line,
        realtime_lhb_line=realtime_lhb_line,
        evidence_block=block["text"],
        board=str(ref["board"]),
    )
    return {"docKind": DOC_KIND_SECTOR, "narrative": narrative, "evidence": block,
            "regulatoryState": regulatory_state,
            "lhbState": _lhb_state_payload(lhb_facts, line_rendered=lhb_facts_line is not None),
            "driverCross": None,
            "chars": len(narrative),
            "estimatedTokens": estimate_tokens(len(narrative))}


def estimate_tokens(chars: int) -> dict:
    """字符 → token 估算（区间 + 护栏用上界）。非真 tokenizer，仅用于预算护栏与排序。"""
    low = int(chars * TOKENS_PER_CHAR_LOW) + TOKENS_FIXED_LOW
    high = int(chars * TOKENS_PER_CHAR_HIGH) + TOKENS_FIXED_HIGH
    return {"low": low, "high": high, "budgetGuard": high}


# ── v17 板块判定行注入（预登记 v17 §2.4-1，修复 A2 跨题引用悬空）──

def _inject_sector_judgment_line(narrative: str, line: str) -> str:
    """把板块判定行插到叙事固定位置：基线（+基础率锚）（+结构事实）块之后、空间锚前。

    与 build_leader_narrative 的装配位置一致（标注时注入与构建时注入同形）；
    基线行恒在（build_leader_narrative 无条件 append），防御性找不到时原样返回。
    """
    lines = narrative.split("\n")
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("结构基线：")), None)
    if idx is None:
        return narrative
    j = idx + 1
    while j < len(lines) and lines[j].startswith(("续板基础率", "结构事实：")):
        j += 1
    lines.insert(j, line)
    return "\n".join(lines)


def _strip_sector_judgment_line(narrative: str) -> str:
    """剔除叙事中的板块判定行（review m1：force 重跑板块 ok→degraded/insufficient
    时清理构建期预载注入的陈旧判答行；无行时原样返回）。"""
    return "\n".join(ln for ln in narrative.split("\n")
                     if not ln.startswith("板块判定："))


def _resolve_sector_judgment_state(col: Any, date: str, board: str,
                                   narrative: str) -> str:
    """板块判答注入状态（结构化留痕，fail-visible；叙事整行缺席时审计唯一可观测源）。

    injected=行在场；sector_degraded=板块 doc 存在但 degraded；sector_insufficient=
    板块 doc ok 但两题均 insufficient（无判答可注）；sector_missing=无板块 doc。
    """
    if "板块判定：" in narrative:
        return "injected"
    sec = col.find_one({"_id": f"{date}:board:{board}"})
    if not sec:
        return "sector_missing"
    if sec.get("status") != "ok":
        return "sector_degraded"
    return "sector_insufficient"


def _label_one(db, col, date: str, built: dict,
               baseline_meta: dict,
               sample_origin: str = SAMPLE_ORIGIN_LIVE) -> tuple[bool, int]:
    """单条真实 jev 调用（唯一花 token 的路径）。返回 (ok, tokens)。

    v12 A2 拆题：按 built["docKind"] 分流——板块级 doc 只发板块题子集（深度/延续），
    个股级 doc 只发个股题子集（v17 四题：续板/空间/催化硬度/身位稳固度，事件日
    +rebound 五题）；证据门只门对应子集（预登记 §2.3）。
    """
    doc_kind = built.get("docKind", DOC_KIND_LEADER)
    questions = built.get("questions") or QUESTIONS_THEME_LEADER
    narrative = built["narrative"]
    env, ms = _dispatch_jev(narrative, questions)
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    raw_answers = parsed.get("answers") or {}
    # v2 确定性门（v5 起全题门；v12 拆题后按子集门）：证据缺失（语料未采集/板块未映射/
    # 无正文且无事件）→ 判定题强制 insufficient，模型原答原样存 `modelAnswers`/`gate`
    # （不丢真实输出；避免"无证据"与"模型上调"混在一批数字里）。只在调用成功时过门：
    # 调用 degraded（无答案）走原路径，不得把"没答上来"写成 insufficient。
    answers, gate = apply_evidence_gate(raw_answers, built.get("evidence") or {},
                                        keys=tuple(questions)) if parsed["ok"] else \
        (raw_answers, {"applied": False, "reason": None})
    cont = answers.get("leader_nextday_continue") or {}
    depth = answers.get("theme_speculation_depth") or {}
    contn = answers.get("theme_continuation") or {}
    head = answers.get("leader_headroom") or {}
    hard = answers.get("leader_catalyst_hardness") or {}
    seat = answers.get("leader_seat_durability") or {}
    # P1-1 改道（2026-11-07）：reason 协议注经 5 探针实证无效已撤；审计改程序侧偏离标记。
    # 模型若附 reason（平台未来放开）仍容错透传落库（P2-2 旧行为不变）。
    answer_reasons = {str(k): str(v.get("reason")) for k, v in answers.items()
                      if isinstance(v, dict) and v.get("reason")}
    audit_flag, audit_note = (
        _anchor_deviation_audit(narrative, cont.get("choice"))
        if doc_kind == DOC_KIND_LEADER else (None, None))
    if doc_kind == DOC_KIND_SECTOR:
        rows = built.get("rows") or []
        if not rows:
            raise ValueError("_label_one: sector doc 缺 rows")
        ref = rows[0]
        doc = {
            "_id": f"{date}:board:{ref['board']}", "origin": ORIGIN,
            "tradingDate": date, "docKind": DOC_KIND_SECTOR,
            "code": None, "name": None, "board": ref["board"],
            "segmentRows": [{"segment": r.get("segment"), "code": r.get("code"),
                             "name": r.get("name"), "gain10": r.get("gain10"),
                             "leaderSealedToday": r.get("leaderSealedToday")}
                            for r in rows],
        }
    else:
        row = built["row"]
        doc = {
            "_id": f"{date}:{row['code']}", "origin": ORIGIN, "tradingDate": date,
            "docKind": DOC_KIND_LEADER,
            "code": row["code"], "name": row.get("name"), "board": row["board"],
        }
        # v12 分轨：main/growth；None（夹具/未知前缀）不写键（P2-5：真 Mongo $exists:False
        # 不匹配 null 字段，写 None 会成对账死角）
        if row.get("segment"):
            doc["segment"] = row["segment"]
        # 2026-11-17 语料精简：叙事不再投喂的缺席状态结构化留痕（§1.2-8 落库层
        # fail-visible）：家数序列缺席/周期缺席审计可观测，不占叙事字
        doc["boardHistoryState"] = built.get("boardHistoryState")
        doc["cycleState"] = built.get("cycleState")
    doc.update({
        "ammoVersion": AMMO_VERSION_THEME_LEADER,
        # A（2026-11-11 用户裁决）：龙虎榜缺席结构化留痕（叙事整行缺席时审计/补齐链
        # 唯一可观测源；§1.2-8 落库层 fail-visible）
        "lhbState": built.get("lhbState"),
        # 2026-11-15：监管风险 lane 状态留痕（审计/前端用，不进叙事）
        "regulatoryState": built.get("regulatoryState"),
        "questionSetVersion": QUESTION_SET_VERSION_THEME_LEADER,
        "questionSetHash": QUESTION_SET_HASH_THEME_LEADER,
        "structure": {k: (built.get("rows") or [built["row"]])[0].get(k) for k in (
            "streak", "time", "boardN", "othersN", "ladderFollowers", "prevPeers",
            "prevBoardN", "prevTotal", "prevStill", "zhabanN", "prevZhabanN", "ladderShape",
            "secondStreak",
            # 2026-10-27 空间龙一规则：10日涨幅 + 未封板标记（断板反包候选）
            "gain10", "leaderSealedToday",
            # 2026-11-18 天普案：续断三态/区间高度/复牌日留结构化载荷（审计/前端）
            "dayStatus", "poolDay", "days", "boards", "resumeDate")},
        "baselineBucket": json.dumps(
            {k: (built.get("rows") or [built["row"]])[0].get(k)
             for k in ("streak", "boardN", "time")},
            ensure_ascii=False, sort_keys=True),
        # 真实的同桶查键（"streak3|n5-7|early<=10:00"）：评估时直接用，不必再从结构重算；
        # `baselineBucket` 只是原始结构审计字段，两者别混（混用会静默退化成只按连板高度对照）。
        # v12 板块级 doc 以首轨（main 优先）龙一为参照行。
        "baselineKey": combo_key((built.get("rows") or [built["row"]])[0]),
        "baselineMeta": baseline_meta,
        # 打标交叉源审计（AMMO 2026-10-27b；板块级无此行=None）：found/槽位/打标链题集版本；
        # 叙事行本身在 narrative
        "driverCross": built.get("driverCross"),
        "evidenceState": built["evidence"]["state"],
        "evidenceIndustry": (built["evidence"].get("industry") or {}).get("name"),
        "evidenceEventTitles": [e.get("title") for e in built["evidence"].get("events") or []],
        # 2026-11-02 用户报障：题材新闻命中只活在叙事文本里，结构化层不可见
        # （KPL 研讨会新闻含亚玛顿关联股，evidenceEventTitles=[]/kwordTags=[] 看似「没关联」）
        # ——镜像题材新闻命中标题（含 Kword 空、标题锚命中的条目），与事件徽章同口径
        "evidenceNewsTitles": [n.get("title") for n in built["evidence"].get("news") or []],
        # v3/v4：L2 板内解析可用性 + Kword 题材标签（开盘啦新闻流），前端分层展示用
        "evidenceBoardResolved": bool(built["evidence"].get("boardResolved")),
        "evidenceKwordTags": list(built["evidence"].get("kwordTags") or []),
        "evidenceMissing": bool((built.get("evidence") or {}).get("evidenceMissing")),
        "evidenceMissingReason": (built.get("evidence") or {}).get("evidenceMissingReason"),
        "narrative": narrative, "questionsRaw": questions,
        "answers": answers,            # 落库口径 = 过门后的答案（消费端单一事实源）
        "modelAnswers": raw_answers,   # 模型原答（审计用；不得被消费端当口径）
        "gate": gate,                  # {applied, reason, label, modelChoice, modelProbabilities}
        "answerReasons": answer_reasons,   # P2-2：结构化引用说明（模型产出才非空；容错透传）
        # P1-1 改道：程序侧偏离审计（auditFlag=deviation_from_anchor；None=同档或无基线行）
        "auditFlag": audit_flag, "auditNote": audit_note,
        "leaderNextdayContinue": cont.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "leaderNextdayProbabilities": (cont.get("probabilities")
                                       if doc_kind == DOC_KIND_LEADER else None),
        # v5：题材层三层判断（catalystStage 已被深度题取代；旧代文档仍带 catalystStage 字段）；
        # v12 拆题：板块级 doc 只落深度/延续，个股级 doc 只落续板/空间（其余=None）
        "themeSpeculationDepth": depth.get("choice") if doc_kind == DOC_KIND_SECTOR else None,
        "themeContinuation": contn.get("choice") if doc_kind == DOC_KIND_SECTOR else None,
        "leaderHeadroom": head.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        # v17 两新题便捷字段（全答仍在 answers；旧代/板块级=None）
        "leaderCatalystHardness": hard.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        "leaderSeatDurability": seat.get("choice") if doc_kind == DOC_KIND_LEADER else None,
        # v17：板块判答注入状态（injected/sector_degraded/sector_insufficient/
        # sector_missing；叙事整行缺席时审计唯一可观测源，fail-visible）
        "sectorJudgmentState": (built.get("sectorJudgmentState")
                                if doc_kind == DOC_KIND_LEADER else None),
        # v14（P3 工作流 B）：人气成色便捷字段（全答仍在 answers；非事件日/旧代=None）
        "leaderReboundPopularity": ((answers.get(REBOUND_QUESTION) or {}).get("choice")
                                    if doc_kind == DOC_KIND_LEADER else None),
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
    })
    old = col.find_one({"_id": doc["_id"]}) or {}
    for k, v in old.items():
        # auditFlag/auditNote：本轮标记优先；本轮无标记时旧值带走——但上一轮的瞬时
        # 机审标记（missing_reason/deviation_from_anchor）除外（应随本轮重评；
        # v12 两案等人工复盘标记继续防抹）
        if k.startswith("outcome") or (k in ("auditFlag", "auditNote")
                                       and audit_flag is None
                                       and old.get("auditFlag") not in (
                                           "missing_reason", "deviation_from_anchor")):
            doc[k] = v   # 结局/复盘标记是事实性字段，重跑重建必须原样带走（v12 两案标记防抹）
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
        reason = str(meta.get("reason") or "")
        if reason.startswith("sector_nodes"):
            # v17 三链合一门控（2026-11-09 用户裁决）：节点档缺失/非 ok/非 v5 → 拦停，
            # 不回退自推导（回退等于两口径复活）；scheduler 限次退避重试会补跑。
            print(f"{date} 板块节点档不可用（{reason}: "
                  f"{meta.get('status') or meta.get('version') or '文档缺失'}），"
                  f"跳过打标（fail-visible，不回退自推导）")
            return {"ok": False, "date": date,
                    "error": {"code": reason, "detail": {k: v for k, v in meta.items() if k != "reason"}}}
        print(f"{date} 当日 THS 封板池缺失（无法做触板−炸板二分），跳过（fail-visible）")
        return {"ok": False, "date": date, "error": {"code": "ths_pool_missing"}}
    for _k in ("driftBoards", "droppedBoards"):
        if meta.get(_k):
            print(f"{date} {_k}: {meta[_k]}（节点档为准，fail-visible 披露）")
    if not rows:
        print(f"{date} 当日无封板板块（韭研 final 文档缺或全炸板），跳过（披露）")
        return {"ok": True, "date": date, "leaders": 0, "skippedReason": "no_leaders"}
    rows = sorted(rows, key=lambda r: (-(r["boardN"]), str(r.get("time") or "99:99")))
    rows_full = list(rows)           # 全量推导行（对账用，不受 codes/boards 过滤影响）
    # P2-6/P0 伴生（review）：空间模式降级披露进 stdout（spaceErrors=整板块跳过、
    # spaceTrackGaps=整轨降级、limitDownExcluded=断板跌停剔除、
    # lowHeightBrokenExcluded=首板断板跟风剔除）——不让降级静默
    for _k in ("spaceErrors", "spaceTrackGaps", "limitDownExcluded",
               "lowHeightBrokenExcluded"):
        if meta.get(_k):
            print(f"{date} {_k}: {meta[_k]}")
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
    excluded = [r for r in rows if digest.is_not_a_theme(r["board"])]
    excluded_boards = sorted({r["board"] for r in excluded})
    if excluded:
        print(f"{date} 排除非题材行政桶 {len(excluded)} 只龙头（{'、'.join(excluded_boards)}）"
              f"——不纳入 jev 判定（v3 收紧；v5 起不落库不显示，仅日志留痕）")
        rows = [r for r in rows if not digest.is_not_a_theme(r["board"])]
    if reconcile_only:
        # 零调用对账（手工对账历史日/存量幽灵行）：只做退位，不标注不花 token
        rec = reconcile_superseded_leaders(db, date, rows_full)
        return {"ok": True, "date": date, "reconcileOnly": True,
                "leaders": plan_leaders_total, "reconcile": rec}
    rows_baseline, baseline_meta = baseline_rows_for(db, date, dataset_id=dataset_id)
    col = db[COLLECTION]
    done_docs = list(col.find({"tradingDate": date, "status": "ok"},
                              {"code": 1, "board": 1, "docKind": 1}))
    done = {str(d.get("code")) for d in done_docs if d.get("code")}
    done_boards = {str(d.get("board")) for d in done_docs
                   if d.get("docKind") == DOC_KIND_SECTOR and d.get("board")}
    # v17：板块判答预载（库读兜底：重跑/板块 doc 已 ok 场景构建时即可注入；同轮新跑
    # 板块 doc 尚未标注，由下方标注循环先板块后个股在标注前注入，预登记 v17 §2.4-1）
    sector_answers_by_board: dict[str, dict] = {}
    for d in col.find({"tradingDate": date, "docKind": DOC_KIND_SECTOR, "status": "ok"}):
        if d.get("board"):
            sector_answers_by_board[str(d["board"])] = d.get("answers") or {}
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
    # v12 新原料（AMMO 2026-10-28a）：KPL 板块强度 + 直播播报（各一次取数全板块共用）
    # 涨停原因映射（2026-11-11 改源：单一事实源 kpl_daban_pool.reason_items，一次取全日共用）
    strength_payload = fetch_plate_strength(date)
    live_payload = get_live_for_label(db, date)
    # 15:00 收盘总结（AMMO 2026-10-30e）：一次提取全板块/全个股共用（与直播同源）
    market_summary = market_summary_line(market_summary_entry(live_payload, date))
    reasons = fetch_reason_corpus(db, date)
    # 龙虎榜事实（AMMO 2026-10-30a）：一次取数全日共用（与板块强度/直播同哲学）
    lhb_facts = fetch_lhb_facts(date)
    # A（2026-11-11）：主榜缺席结构化日志（fail-visible；叙事整行缺席按 §1.2-8，
    # 留痕双保险 = doc.lhbState 落库 + 本日志；补齐链 B 按 lhbState 探测补跑）
    if not (lhb_facts.get("groups") or lhb_facts.get("stocks")):
        logger.warning(
            "lhb_facts 主榜缺席 date=%s list_ok=%s stock_ok=%s empty_structured=%s "
            "seat_n=%s agency_n=%s reason=%s",
            date, lhb_facts.get("list_ok"), lhb_facts.get("stock_ok"),
            lhb_facts.get("empty_structured"), len(lhb_facts.get("stock_board") or {}),
            len(lhb_facts.get("agency") or {}), lhb_facts.get("reason"))
    # 涨停基因语料（AMMO 2026-11-08a）：一次取全日共用（个股级叙事行，板块级不消费）
    gene_corpus = fetch_gene_corpus(db, date)
    # 封板质量（2026-11-08b / 题集 v16）：同一日档 items 的量价字段，一次取全日共用
    pool_quality = fetch_pool_quality(db, date)
    # 题材库热度语料（AMMO 2026-11-08d）：2013 订阅落库，一次取全日共用（个股级，板块级不消费）
    theme_heat = fetch_theme_heat(db, date)
    # 公告计数语料（AMMO 2026-11-08e）：懒取落库，一次取全日共用（个股级，板块级不消费）
    notice_corpus = fetch_notice_corpus(db, date)
    # 2026-11-11 语料缺口补全（①→④，全部一次取全日共用，降级不阻断投喂）：
    # bid/zb/dt 三通道（②，日档已落库）+ 2112/3004/3101 落库（③）+ 个股详情四通道（④）
    lanes_corpus = fetch_daban_lanes(db, date)
    fc_corpus = fetch_lhb_forecast_corpus(db, date)
    rt_corpus = fetch_lhb_realtime_corpus(db, date)
    detail_corpus = fetch_stock_detail_corpus(db, date)
    # 监管风险语料（2026-11-15 预登记）：一次取全日共用（个股+板块两级叙事行）
    reg_corpus = fetch_regulatory_corpus(db, date)
    # 2026-11-18 天普案：停牌复牌日单源=监管语料（与监管风险行同源），仅
    # dayStatus=suspended 行携带，供叙事「预计复牌 X」（缺则不可考，不伪造）。
    for _r in rows or []:
        if _r.get("dayStatus") == "suspended":
            _recent = ((reg_corpus.get("byCode") or {}).get(str(_r.get("code"))) or {}).get("recent") or []
            _r["resumeDate"] = _resume_date_from_regulatory(_recent, date)
    # v17：续板基础率锚先验底（滚动直算，窗 2026-10-23~当日之前，防 look-ahead；
    # 无已结算行=None → 锚行整行缺席，fail-visible）
    base_rate_stats = live_base_rate(db, before=date)
    by_board: dict[str, list[dict]] = {}
    for r in rows:
        by_board.setdefault(str(r["board"]), []).append(r)
    # v12 A2：板块级 todo（全量跑=过滤后全部板块；单只重跑=选中行所在板块且尚无板块 doc；
    # force=全部重标含板块 doc）
    selected_boards = set(by_board)
    sector_todo_boards = (({str(r["board"]) for r in todo} if codes else selected_boards)
                          - (set() if force else done_boards))
    if codes and not force:
        # P2-4（review）：单只重跑同时自愈该日 degraded 板块 doc——否则「龙头全 ok 但
        # 板块 doc degraded」的档 codes 永远修不了（只能全量跑自愈）
        sector_todo_boards |= {
            str(d.get("board")) for d in col.find(
                {"tradingDate": date, "docKind": DOC_KIND_SECTOR, "status": "degraded"})
            if d.get("board")}
    built_all: list[dict] = []
    live_cache: dict[str, tuple[list[dict], dict]] = {}
    series_cache: dict[str, str | None] = {}
    rank_hist_cache: dict[str, dict] = {}
    # v14 事件门缓存（每交易日一份弱转强文档，个股循环共用；B1:A）
    wzs_cache: dict[str, dict] = {}

    def _live(board: str) -> tuple[list[dict], dict]:
        if board not in live_cache:
            live_cache[board] = live_entries_for_board(live_payload, board, date)
        return live_cache[board]

    def _rank_hist_map(day: str) -> dict:
        # P1-1/P2-1：层1 按日全板块行（强度/主力净额 raw[8] 推断口径）——按日缓存共用
        if day not in rank_hist_cache:
            try:
                payload = fetch_plate_strength(day)
                rank_hist_cache[day] = {
                    str(it.get("name") or ""): it
                    for it in (payload.get("items") or [])}
            except Exception:  # noqa: BLE001 — 失败日行如实缺席（行内「?」）
                rank_hist_cache[day] = {}
        return rank_hist_cache[day]

    def _series_line(board: str, smatch: dict | None) -> str | None:
        # P1-1：锚=强度行匹配到的一级板块（未匹配→不出行，由强度行披露）
        if not (isinstance(smatch, dict) and smatch.get("ok") and smatch.get("plate_id")):
            return None
        pid = smatch["plate_id"]
        if pid not in series_cache:
            # 层1 连续段：韭研日轴（复用 trading_dates_before 单一实现）近 N 日 + 当日
            kname = str(smatch.get("name") or "")
            days = trading_dates_before(db, date, 5, dataset_id) + [date]
            zt = fetch_plate_zt_history(pid, date, window_days=len(days))
            zt_rows = zt.get("zt_rows") or [] if zt.get("ok") else []
            zt_err = None if zt.get("ok") else str(zt.get("error") or "unknown")  # P2-11
            rank_rows = []
            for d in days:
                it = _rank_hist_map(d).get(kname)
                if it is None:
                    continue   # 该日层1 无数据（未生成/失败）→ 缺日如实，不插值
                rank_rows.append({"date": d, "strength": it.get("strength"),
                                  "main_net": it.get("main_net"),
                                  # §9.6 哨兵原料：方向/量级自洽检查需 pct/amount
                                  "pct": it.get("pct"), "amount": it.get("amount")})
            series_cache[pid] = plate_series_line(
                rank_rows, zt_rows, plate_name=kname, label_date=date,
                zt_fetch_error=zt_err,
                # §9.7 缺口率：窗口交易日数（韭研日轴，与层1 连续段同日历）；
                # review P1-1 修复：声明窗口首日，层2 先过滤再计数，不把展示切片数当窗口记录数
                trading_days=len(days), window_first_date=days[0])
            # 口径哨兵（§9.6 漂移监视）只进结构化日志，不进 jev 语料（AGENTS §1.2-8）
            sentinel = rank_sentinel_warnings(rank_rows, zt_rows)
            if sentinel:
                logger.warning("kpl 层1 口径哨兵越界 date=%s board=%s: %s",
                               date, kname, ";".join(sentinel))
        return series_cache.get(pid)

    for b in sorted(sector_todo_boards):
        brows = by_board.get(b) or []
        if not brows:
            continue
        le, lm = _live(b)
        smatch = match_board_strength(strength_payload, b)
        brows_codes, brows_roles = _lhb_codes_roles(
            [str(c) for c in (brows[0].get("boardCodes") or [])],
            [(str(r.get("code") or ""),
              {"main": "主板龙一", "growth": "双创龙一"}.get(r.get("segment"), "龙一"))
             for r in brows])
        dt_names, dt_ok = dt_names_for_board(brows[0], lanes_corpus)
        reg_entries = regulatory_entries_for_codes(brows_codes, brows_roles, reg_corpus)
        built = build_sector_one(
            db, date, brows, rows_baseline, dataset_id, market_line,
            board_history=board_history,
            strength_match=smatch,
            reason_entries=reason_entries_for_leaders(brows, reasons),
            series_line=_series_line(b, smatch),
            dt_line=board_dt_line(dt_names, dt_ok),
            forecast_line=lhb_forecast_line(
                _scope_entries(brows_codes, brows_roles, fc_corpus.get("items") or {}),
                lane_ok=bool(fc_corpus.get("laneOk"))),
            realtime_lhb_line=lhb_realtime_line(
                _scope_entries(brows_codes, brows_roles, rt_corpus.get("items") or {}),
                lane_ok=bool(rt_corpus.get("laneOk"))),
            live_line=kpl_live_line(le, board=b, total=lm.get("total", 0),
                                    window=lm.get("window", ""),
                                    unavailable=lm.get("unavailable")),
            market_summary=market_summary,
            regulatory_line=regulatory_risk_line(reg_entries),
            regulatory_state=_regulatory_state(reg_corpus, reg_entries),
            lhb_facts=lhb_facts)
        built["rows"] = brows
        built["questions"] = {k: QUESTIONS_THEME_LEADER[k] for k in SECTOR_QUESTIONS}
        built_all.append(built)
    for row in todo:
        rb = str(row["board"])
        le, lm = _live(rb)
        smatch = match_board_strength(strength_payload, rb)
        # v14 事件门（B1:A）：当日弱转强事件单源 hotlist_jev_leader_wzs（按日缓存，
        # 缺文档/缺事件=非事件日，本题不判答零额外调用）；周期背景单源 theme_cycle
        ev_doc = wzs_cache.get(date)
        if ev_doc is None:
            ev_doc = db[WZS_COLLECTION].find_one({"tradingDate": date}) or {}
            wzs_cache[date] = ev_doc
        events_hit = [e for e in (ev_doc.get("events") or [])
                      if str(e.get("code")) == str(row.get("code"))
                      and str(e.get("board")) == rb]
        pool_row_hit = next((p for p in (ev_doc.get("poolRows") or [])
                             if str(p.get("code")) == str(row.get("code"))), None)
        cyc = db[CYCLE_COLLECTION].find_one(
            {"tradingDate": date, "board": rb,
             "segment": row.get("segment") or "main"}) or {}
        event = events_hit[0] if events_hit else None
        rebound_line = rebound_popularity_line(
            event, pool_row_hit, board_n=row.get("boardN"), cycle=cyc or None)
        row_codes, row_roles = _lhb_codes_roles(
            [str(c) for c in (row.get("boardCodes") or [])],
            [(str(row.get("code") or ""), "待判龙一")])
        dt_names, dt_ok = dt_names_for_board(row, lanes_corpus)
        reg_entries = regulatory_entries_for_codes(row_codes, row_roles, reg_corpus)
        built = build_one(
            db, date, row, rows_baseline, dataset_id,
            board_history=board_history,
            strength_match=smatch,
            reason_entries=reason_entries_for_leaders([row], reasons),
            gene_entries=gene_entries_for_leaders([row], gene_corpus),
            theme_heat_entries=theme_heat_entries_for_leaders([row], theme_heat),
            notice_entries=notice_entries_for_leaders([row], notice_corpus),
            seal_quality_entries=seal_quality_entries_for_leaders([row], pool_quality),
            series_line=_series_line(rb, smatch),
            segment=row.get("segment"),
            bid_line=bid_line(bid_entries_for_leaders([row], lanes_corpus)),
            dt_line=board_dt_line(dt_names, dt_ok),
            detail_lines=detail_lines_for_leader(row, detail_corpus, theme_heat),
            regulatory_line=regulatory_risk_line(reg_entries),
            regulatory_state=_regulatory_state(reg_corpus, reg_entries),
            live_line=kpl_live_line(le, board=rb, total=lm.get("total", 0),
                                    window=lm.get("window", ""),
                                    unavailable=lm.get("unavailable")),
            lhb_facts=lhb_facts,
            rebound_line=rebound_line,
            cycle=cyc or None,
            sector_judgment=sector_answers_by_board.get(rb),
            base_rate_stats=base_rate_stats)
        built["row"] = row
        built["questions"] = {k: QUESTIONS_THEME_LEADER[k]
                              for k in (LEADER_QUESTIONS_REBOUND
                                        if event else LEADER_QUESTIONS)}
        if event:
            built["reboundEvent"] = event
        built_all.append(built)
    tokens = sum(b["estimatedTokens"]["budgetGuard"] for b in built_all)
    # v17：待注入板块判定行的预算预留（构建时板块 doc 尚未标注，标注时注入；
    # 上界口径 SECTOR_JUDGMENT_RESERVE_CHARS，不虚报；charsTotal 仍为构建时口径）
    pending_inject = sum(1 for b in built_all
                         if b["docKind"] == DOC_KIND_LEADER
                         and "板块判定：" not in b["narrative"]
                         and str(b["row"]["board"]) in sector_todo_boards)
    tokens += int(pending_inject * SECTOR_JUDGMENT_RESERVE_CHARS * TOKENS_PER_CHAR_HIGH)
    plan = {"ok": True, "date": date, "leaders": len(rows),
            "leadersTotal": plan_leaders_total, "todo": len(todo),
            "sectorDocs": len(sector_todo_boards),
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
            if b["docKind"] == DOC_KIND_SECTOR:
                head = f"板块级 {b['rows'][0]['board']}（双龙一并列）"
            else:
                head = (f"个股级[{b['row'].get('segment')}] {b['row']['board']} / "
                        f"{b['row']['name']}（{b['row']['code']}）")
            print(f"\n===== {head} "
                  f"{b['chars']} 字 ≈ {b['estimatedTokens']['low']}-{b['estimatedTokens']['high']} tokens")
            print(b["narrative"])
        print("\n[dry] 零 jev 调用（未花 token）")
        return plan
    if not built_all:
        rec = reconcile_superseded_leaders(db, date, rows_full)
        print(f"{date} 无需投喂（{len(done)} 只龙头 + {len(done_boards)} 板块 doc 已 status=ok，幂等跳过）")
        return {**plan, "labeled": 0, "reconcile": rec}
    if not confirm_budget:
        raise SystemExit(
            f"预算护栏：本次将真实调用 jev {len(built_all)} 次"
            f"（{date}；{len(todo)} 龙头 doc + {len(sector_todo_boards)} 板块 doc，v12 拆题包络），"
            f"估算 ≤{tokens} tokens（叙事 {plan['charsTotal']} 字，上界口径）。"
            f"确认预算请加 --confirm-budget；先看文本用 --dry-run。")
    n_ok = n_used = transport_fails = 0
    for i, b in enumerate(built_all, 1):
        if b["docKind"] == DOC_KIND_LEADER:
            # v17：标注前先剔除构建期预载注入的判定行、再按本轮缓存重注（review m1：
            # force 重跑板块 ok→degraded/insufficient 时陈旧判答不得残留，状态与档况
            # 一致）；位置与构建时装配一致（基线块后、空间锚前）；幂等
            rb = str(b["row"]["board"])
            narr = _strip_sector_judgment_line(b["narrative"])
            sj_line = sector_judgment_line(sector_answers_by_board.get(rb))
            if sj_line:
                narr = _inject_sector_judgment_line(narr, sj_line)
            if narr != b["narrative"]:
                b["narrative"] = narr
                b["chars"] = len(narr)
                b["estimatedTokens"] = estimate_tokens(b["chars"])
            b["sectorJudgmentState"] = _resolve_sector_judgment_state(
                col, date, rb, b["narrative"])
        ok, used = _label_one(db, col, date, b, baseline_meta,
                              sample_origin=sample_origin)
        n_ok += 1 if ok else 0
        n_used += used
        if b["docKind"] == DOC_KIND_SECTOR:
            sb = str(b["rows"][0]["board"])
            if ok:
                # v17：缓存板块判答（供同轮后序同板块个股叙事注入；从落库 doc 读，
                # 与消费端单一事实源同口径=过门后 answers）
                sec_doc = col.find_one({"_id": f"{date}:board:{sb}"}) or {}
                sector_answers_by_board[sb] = sec_doc.get("answers") or {}
            else:
                # review m1：板块重标失败 → 清预载缓存，个股侧剔除残留判定行
                sector_answers_by_board.pop(sb, None)
        if b["docKind"] == DOC_KIND_SECTOR:
            head = f"板块级 {b['rows'][0]['board']}"
        else:
            head = f"{b['row']['board']}/{b['row']['name']}"
        print(f"[{i}/{len(built_all)}] {date} {head}"
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
        # 结果行加唯一标记（2026-11-02 修复）：stdout 前部有降级披露行（P2-6，含 Python
        # dict 单引号文本，如 `limitDownExcluded: {'其他': ...}`）——调度侧旧的「首个 {
        # 截取」会截到披露行 → JSON 解析失败 → 结局回填（settle）被整体跳过
        # （10-29/10-30 两日结局漏回填的根因）。标记行=调度侧唯一机读接口。
        print("THEME_LEADER_RESULT_JSON:" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()