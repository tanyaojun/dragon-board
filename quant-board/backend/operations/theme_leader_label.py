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
from backend.analysis.hotlist.jev_lhb_ammo import collect_lhb_facts
from backend.analysis.hotlist.theme_leader_ammo import (
    market_summary_line,
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
    build_sector_narrative,
    combo_key,
    driver_cross_line,
    headroom_anchor_line,
    kpl_live_line,
    lhb_line,
    plate_series_line,
    structure_facts_line,
    limitup_reason_line,
    plate_strength_line,
    rebound_popularity_line,
    structure_line,
    structure_line_dual,
    zt_gene_line,
    seal_quality_line,
)
from backend.operations.leader_wzs import COLLECTION as WZS_COLLECTION
from backend.operations.theme_cycle import COLLECTION as CYCLE_COLLECTION
from backend.operations.theme_leader_baseline import (
    board_count_history, build_rows, day_leader_rows)
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
    m = re.search(r"结构基线：同桶\[[^\]]+\] 历史次日连板率 ([\d.]+)%（(\d+) 样本）", narrative)
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
LEADER_QUESTIONS = ("leader_nextday_continue", "leader_headroom")
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
    """标注用直播流（P1-2 日归档）：归档优先 → 当日实时（取后归档）→ 历史日缺席降级。

    归档集合 `kpl_live_daily`（_id=date）：挂链（17:30，2026-10-30 改时）标注当日时实时取数并落库，此后
    回填/复盘/评估读归档——**存的是标注时点当日文本**，无 look-ahead；历史日无归档
    → {ok: False, reason}（fail-visible，不把今天直播冒充历史语料）。
    """
    col = db[LIVE_ARCHIVE_COLLECTION]
    doc = col.find_one({"_id": str(date)}) or {}
    if doc.get("items"):
        return {"ok": True, "items": doc["items"], "notice": doc.get("notice"),
                "fromArchive": True}
    if str(date) != time.strftime("%Y-%m-%d"):
        # 实时流只含当日条目，历史日外呼必空——直接降级，不浪费上游请求
        return {"ok": False,
                "reason": f"实时流不可回放（标注日 {date} 非当日且无直播归档，历史日无直播归档）"}
    payload = fetch_live_commentary()
    if not payload.get("ok"):
        return payload
    items = payload.get("items") or []
    item_today = [it for it in items
                  if time.strftime("%Y-%m-%d", time.localtime(it["ts"])) == str(date)]
    if item_today:
        col.replace_one({"_id": str(date)},
                        {"_id": str(date), "items": items,
                         "notice": payload.get("notice"), "itemCount": len(items),
                         "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S")},
                        upsert=True)
        return payload
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
    逐端点捕获，行文由 lhb_line 承担），非 jev 调用、不花 token。挂链 17:30（2026-10-30
    用户裁决改时）晚于榜生成（约 17:00 盘后），当日事实行当日可得；上游延迟未生成时
    为结构化空态——行内显式披露，不伪装成「无上榜」。
    """
    try:
        return collect_lhb_facts(date)
    except Exception as exc:  # noqa: BLE001 — 双端点均异常的兜底（collect 内部已各端点捕获）
        return {"ok": False, "date": date, "degraded": True,
                "reason": f"fetch_failed: {exc}"}


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


def expound_map(db: Any, date: str) -> dict[str, tuple[str, str | None]]:
    """当日全市场涨停原因映射（裁决③，预登记 §4.1）：code → (name, reason|None)。

    单一事实源 = `jev_label_jiuyan.expound_reason()`（expound 缺失回退 reason 键，
    与打标链读口同源，禁第二套解析）；查一次全日共用（与 market_line 同哲学）。
    文档缺失/无字段 → 空映射（调用方出 fail-visible 不可考，不伪装）。
    """
    from backend.operations.jev_label_jiuyan import expound_reason
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"},
        {"fields.stocks.code": 1, "fields.stocks.name": 1,
         "fields.stocks.expound": 1, "fields.stocks.reason": 1}) or {}
    out: dict[str, tuple[str, str | None]] = {}
    for field in doc.get("fields") or []:
        for st in field.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            if code and code not in out:
                out[code] = (str(st.get("name") or ""), expound_reason(st))
    return out


def reason_entries_for_leaders(rows: list[dict], expounds: dict[str, tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """涨停原因行条目（预登记 §4.1，2026-10-28 用户裁决收窄）：**仅待判龙一自身**。

    `rows` = 同板块分轨龙一行（main 优先）；板块成员原因不列（板内同伴由既有「板内
    解析/板内同伴驱动」行承载，不重复；大板块全列会把叙事撑爆且非本题重点）。
    原因缺失逐项 None（limitup_reason_line 出不可考，fail-visible）。
    """
    entries: list[tuple[str, str | None]] = []
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        name, reason = expounds.get(code, (str(row.get("name") or ""), None))
        entries.append((f"{seg_cn} {name}", reason))
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
    行承载，不重复；无该股语料 → item=None（zt_gene_line 出「不可考」）。
    """
    entries: list[dict] = []
    for row in rows:
        code = str(row.get("code") or "")
        seg = row.get("segment")
        seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(seg, "龙一") if seg else "龙一"
        entries.append({"label": f"{seg_cn} {row.get('name') or code}",
                        "item": genes.get(code)})
    return entries


# 封板质量只看这几列（quotas 具名字段，语义见 kpl_daban_protocol.DABAN_QUOTA_NAMES；
# warn_tag/back_zt/stock_tag/financing_tag 语义未破译或未定，本行不消费）
_POOL_QUALITY_FIELDS = ("zt_tur", "max_zt_tur", "real_float", "real_turnover",
                        "main_net", "amount", "price", "pool_state", "last_seen_ts")


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
                        "poolMissing": None if hit else degraded})
    return entries


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

    2026-10-27 空间龙一规则（用户裁决，预登记 §21.6）：space_mode=True，排序=
    10日涨幅→连板高度→首封；基线/历史窗口仍走默认 streak 口径（样本人群不随规则
    换代漂移）。
    2026-11-01 用户裁决：早间 T+1 收紧由 v5 预登记裁决 4 取代——候选池严格回溯
    3 个封板日（窗位 k=T−S−1，k∈{0,1,2}，k≥3 出池），与盯盘清单同窗（单一事实
    源，龙一是同一批事实行）；height≥2 与未跌停条件保留（day_leader_rows 内过
    滤）。断板反包候选=隔日弱转强的实质根因修复（首板混入/徽标措辞/窗外滞留）
    均不受影响。
    """
    prev_dates = trading_dates_before(db, date, 3, dataset_id)
    return day_leader_rows(db, date, dataset_id,
                           prev_date=prev_dates[-1] if prev_dates else None,
                           space_mode=True, pool_dates=prev_dates)


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
              market_line: str | None = None,
              board_history: dict[str, list[tuple[str, int]]] | None = None,
              strength_match: dict | None = None,
              reason_entries: list[tuple[str, str | None]] | None = None,
              gene_entries: list[dict] | None = None,
              seal_quality_entries: list[dict] | None = None,
              series_line: str | None = None,
              segment: str | None = None,
              live_line: str | None = None,
              market_summary: str | None = None,
              lhb_facts: dict | None = None,
              rebound_line: str | None = None,
              cycle: dict | None = None) -> dict:
    """组装一条**个股级**投喂（叙事 + 附带元数据），零网络零模型（v12 续板/空间题）。"""
    from backend.operations.jev_label_jiuyan import market_facts_line

    if market_line is None:
        market_line = market_facts_line(db, date, dataset_id)
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
        seal_quality_line=seal_quality_line(seal_quality_entries or []),
        plate_strength=plate_strength_line(strength_match) if strength_match is not None else None,
        series_line=series_line,
        live_line=live_line,
        baseline=baseline_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        headroom=headroom_anchor_line(rows_baseline, row, BASELINE_MIN_SAMPLES),
        market_summary=market_summary,
        driver_cross=driver_cross_line(driver_doc),
        gene_line=zt_gene_line(gene_entries or []),
        reason_line=limitup_reason_line(reason_entries or []),
        lhb_facts_line=(lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles)
                        if lhb_facts is not None else None),
        rebound_line=rebound_line,
        evidence_block=block["text"],
        leader_name=str(row.get("name") or ""),
        leader_code=str(row.get("code") or ""),
        segment=row.get("segment"),
        # v15 P1：结构事实行（周期/封板/高度/梯队，程序直读；Q8:A 校准参考不仲裁）
        facts_line=structure_facts_line(row, cycle),
    )
    return {"docKind": DOC_KIND_LEADER, "narrative": narrative, "evidence": block,
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
                     reason_entries: list[tuple[str, str | None]] | None = None,
                     series_line: str | None = None,
                     live_line: str | None = None,
                     market_summary: str | None = None,
                     lhb_facts: dict | None = None) -> dict:
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
        plate_strength=plate_strength_line(strength_match) if strength_match is not None else None,
        series_line=series_line,
        live_line=live_line,
        market_summary=market_summary,
        baseline=baseline_line(rows_baseline, ref, BASELINE_MIN_SAMPLES),
        reason_line=limitup_reason_line(reason_entries or []),
        lhb_facts_line=(lhb_line(lhb_facts, codes=lhb_codes, roles=lhb_roles)
                        if lhb_facts is not None else None),
        evidence_block=block["text"],
        board=str(ref["board"]),
    )
    return {"docKind": DOC_KIND_SECTOR, "narrative": narrative, "evidence": block,
            "driverCross": None,
            "chars": len(narrative),
            "estimatedTokens": estimate_tokens(len(narrative))}


def estimate_tokens(chars: int) -> dict:
    """字符 → token 估算（区间 + 护栏用上界）。非真 tokenizer，仅用于预算护栏与排序。"""
    low = int(chars * TOKENS_PER_CHAR_LOW) + TOKENS_FIXED_LOW
    high = int(chars * TOKENS_PER_CHAR_HIGH) + TOKENS_FIXED_HIGH
    return {"low": low, "high": high, "budgetGuard": high}


def _label_one(db, col, date: str, built: dict,
               baseline_meta: dict,
               sample_origin: str = SAMPLE_ORIGIN_LIVE) -> tuple[bool, int]:
    """单条真实 jev 调用（唯一花 token 的路径）。返回 (ok, tokens)。

    v12 A2 拆题：按 built["docKind"] 分流——板块级 doc 只发板块题子集（深度/延续），
    个股级 doc 只发个股题子集（续板/空间）；证据门只门对应子集（预登记 §2.3）。
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
    doc.update({
        "ammoVersion": AMMO_VERSION_THEME_LEADER,
        "questionSetVersion": QUESTION_SET_VERSION_THEME_LEADER,
        "questionSetHash": QUESTION_SET_HASH_THEME_LEADER,
        "structure": {k: (built.get("rows") or [built["row"]])[0].get(k) for k in (
            "streak", "time", "boardN", "othersN", "ladderFollowers", "prevPeers",
            "prevBoardN", "prevTotal", "prevStill", "zhabanN", "prevZhabanN", "ladderShape",
            "secondStreak",
            # 2026-10-27 空间龙一规则：10日涨幅 + 未封板标记（断板反包候选）
            "gain10", "leaderSealedToday")},
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
        print(f"{date} 当日 THS 封板池缺失（无法做触板−炸板二分），跳过（fail-visible）")
        return {"ok": False, "date": date, "error": {"code": "ths_pool_missing"}}
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
    # + 涨停原因映射
    strength_payload = fetch_plate_strength(date)
    live_payload = get_live_for_label(db, date)
    # 15:00 收盘总结（AMMO 2026-10-30e）：一次提取全板块/全个股共用（与直播同源）
    market_summary = market_summary_line(market_summary_entry(live_payload, date))
    expounds = expound_map(db, date)
    # 龙虎榜事实（AMMO 2026-10-30a）：一次取数全日共用（与板块强度/直播同哲学）
    lhb_facts = fetch_lhb_facts(date)
    # 涨停基因语料（AMMO 2026-11-08a）：一次取全日共用（个股级叙事行，板块级不消费）
    gene_corpus = fetch_gene_corpus(db, date)
    # 封板质量（2026-11-08b / 题集 v16）：同一日档 items 的量价字段，一次取全日共用
    pool_quality = fetch_pool_quality(db, date)
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
        return series_cache.get(pid)

    for b in sorted(sector_todo_boards):
        brows = by_board.get(b) or []
        if not brows:
            continue
        le, lm = _live(b)
        smatch = match_board_strength(strength_payload, b)
        built = build_sector_one(
            db, date, brows, rows_baseline, dataset_id, market_line,
            board_history=board_history,
            strength_match=smatch,
            reason_entries=reason_entries_for_leaders(brows, expounds),
            series_line=_series_line(b, smatch),
            live_line=kpl_live_line(le, board=b, total=lm.get("total", 0),
                                    window=lm.get("window", ""),
                                    unavailable=lm.get("unavailable")),
            market_summary=market_summary,
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
        built = build_one(
            db, date, row, rows_baseline, dataset_id, market_line,
            board_history=board_history,
            strength_match=smatch,
            reason_entries=reason_entries_for_leaders([row], expounds),
            gene_entries=gene_entries_for_leaders([row], gene_corpus),
            seal_quality_entries=seal_quality_entries_for_leaders([row], pool_quality),
            series_line=_series_line(rb, smatch),
            segment=row.get("segment"),
            live_line=kpl_live_line(le, board=rb, total=lm.get("total", 0),
                                    window=lm.get("window", ""),
                                    unavailable=lm.get("unavailable")),
            market_summary=market_summary,
            lhb_facts=lhb_facts,
            rebound_line=rebound_line,
            cycle=cyc or None)
        built["row"] = row
        built["questions"] = {k: QUESTIONS_THEME_LEADER[k]
                              for k in (LEADER_QUESTIONS_REBOUND
                                        if event else LEADER_QUESTIONS)}
        if event:
            built["reboundEvent"] = event
        built_all.append(built)
    tokens = sum(b["estimatedTokens"]["budgetGuard"] for b in built_all)
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
        ok, used = _label_one(db, col, date, b, baseline_meta,
                              sample_origin=sample_origin)
        n_ok += 1 if ok else 0
        n_used += used
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