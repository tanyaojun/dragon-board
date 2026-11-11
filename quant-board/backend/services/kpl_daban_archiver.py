# -*- coding: utf-8 -*-
"""2103 打板页签按日快照存档（2026-11-07 涨停行情/集合竞价历史回放数据源）。

背景（2026-11-07 实测固化）：上游 HisDaBanList 历史端点为严格白名单参数
（仅 Day+全局五件套+凭据），不认页签参数，返回默认集合（实证 2026-11-06 为
9 只 5~6.5% 涨幅非涨停股，连板/涨停时间/封单全空）——打板页签历史帧无上游读口。
本服务在 :8000 主链周期拉取本机 :8002 collector 合并快照（2103，与实时读口
/daban-list 同构），按日合并进 MongoDB `kpl_daban_pool`（_id=交易日）：

- 涨停池通道（pidType=1，无前缀字段）：成员并集 + 收盘态标注——sealed=收盘仍封住 /
  broken=曾入池后掉出即炸板未回封（字段保留其最后封住时快照 + last_seen_ts）；
  回封自动恢复 sealed；页缺口帧跳过掉出标注防误标。
- 集合竞价通道（pidType=8，bid_ 前缀字段；2026-11-08 用户裁决：与涨停池同集合同日档，
  不另建数据集）：成员并集 + 字段随最新帧刷新（无炸板语义，不标 pool_state）。
- 炸板池通道（pidType=2，zb_ 前缀字段；2026-11-08 增补，同集合同日档）：成员并集 +
  字段随最新帧刷新，无 pool_state 标注——炸板池成员即当日曾炸板全集（回封后掉出
  仍留档，回封语义由涨停池通道 sealed 承载，两通道互为印证）。
- 跌停池通道（pidType=3，dt_ 前缀字段；2026-11-08 增补，同集合同日档）：与涨停池
  同款收盘态标注——sealed=收盘仍跌停 / broken=曾入池后掉出即打开跌停未回封
  （字段保留其最后封住时快照 + last_seen_ts；回封跌停自动恢复 sealed）；
  页缺口帧跳过掉出标注防误标。
- 涨停基因语料通道（apphq StockL2Data/GetZhangTingGene，gene_ 前缀字段；
  2026-11-08 用户需求「题材龙头语料投喂 jev」；前端暂不上）：单股粒度 HTTP 逐股懒取，
  按 stock_id 并集落库 gene_items（六元数组原样 raw + 具名字段 + window_note +
  fetched_date/same_day 时点标记）；**每轮限量 gene_limit 只**（服务端 _post_form
  全局 ≥2s 单发间隔），缺失优先、收盘后 ≥15:05 对盘中旧值刷一次终值；日期跟随涨停池
  快照交易日，全池覆盖度由 gene_pending_n 暴露（fail-visible）。
- 2013 题材库热度 / 2203 涨停原因语料通道（2026-11-10 用户裁决「推送即落库」）：
  **写入方 = collector（:8002）**——推送解析成功后在采集线程内立即写同日档
  theme_/reason_ 前缀字段（与直播文本同款时点，不等盘后轮询），本服务不再轮询这两
  通道（单写者合同：一个通道一个写者）。archive_reason_corpus / archive_theme_corpus
  归档函数保留在本模块供 collector 调用与测试。注意：非推送型语料（gene/notice 走
  HTTP 懒取）的及时性依赖本服务盘中运行（main.py startup 启动）。
- 涨停原因语料（2203 推送，reason_ 前缀字段；2026-11-08 用户需求「作为 jev 语料
  投喂」）：2026-11-10 起写入方 = collector（推送即落库），落库合同同上条：按
  stock_id 并集、字段随最新帧刷新（first_ts 首次到流）；日期跟随涨停池快照交易日，
  推送 ts 早于该日的跨日残留条目跳过不写（不污染当日档）。

各通道在同一次写里各改各的前缀字段（单写者顺序执行，无并发冲突），日档互不覆盖。
供 GET /api/kpl/daban-pool（涨停池）、GET /api/kpl/daban-bidding（集合竞价）、
GET /api/kpl/daban-zhaban（炸板池）、GET /api/kpl/daban-dt（跌停池）、
GET /api/kpl/daban-reasons（涨停原因语料）历史回放
读口消费（前端逐日回退找最近有档交易日，板块行情成分股 kplShiftDate 同款）。

纪律：storage_backend != mongodb 时禁用（不写其它后端）；pytest 经
get_runtime_mongodb_database 护栏自动落 dragon_board_test；拉取失败/空帧不写、
不覆盖既有存档（fail-visible，结构化记 status）。
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from backend.core.settings import get_settings
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.kpl_stock_gene import get_zt_gene
from backend.services.kpl_stock_notice import get_notice_count
from backend.snapshot_collector.trading_calendar import (
    TZ_SHANGHAI,
    is_trading_day_cached,
)

_COLLECTION = "kpl_daban_pool"
_UPSTREAM_POOL = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=1"
_UPSTREAM_BID = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=8"
_UPSTREAM_ZB = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=2"
_UPSTREAM_DT = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=3"

# 通道配置：prefix=日档字段前缀；mark_broken=掉出标注（涨停池/跌停池有掉出语义，
# 炸板池成员即曾炸板全集、竞价无掉出语义，均不标）
_LANES: dict[str, dict[str, Any]] = {
    "pool": {"prefix": "", "mark_broken": True},
    "bid": {"prefix": "bid_", "mark_broken": False},
    "zb": {"prefix": "zb_", "mark_broken": False},
    "dt": {"prefix": "dt_", "mark_broken": True},
}
# 读口降级 note 用的通道中文名（load_day 通用映射用）
_LANE_LABELS: dict[str, str] = {"pool": "涨停池", "bid": "集合竞价",
                               "zb": "炸板池", "dt": "跌停池"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _trading_day_context(now: datetime) -> tuple[bool, Optional[str]]:
    """交易日上下文探测（含 IO：bridge HTTP → 本地缓存 → 周一~五启发）。

    返回 (trading_today, latest_trading_day_iso)；交易日时后者为 None。**含网络探测，
    事件循环内直调会阻塞（bridge 宕机+非交易日最坏 15×2s）**——_archive_once 必须
    经 asyncio.to_thread 每轮预计算一次并当轮复用（评审 R2-P：逐 lane 直调最坏
    阻塞 ~2min 且重复探测）。
    """
    today = now.date()
    trading_today, _source = is_trading_day_cached(today)
    if trading_today:
        return True, None
    # 非交易日：向后找最近一个交易日（回溯上限 15 天，防日历异常长循环）
    probe = today - timedelta(days=1)
    for _ in range(15):
        if is_trading_day_cached(probe)[0]:
            return False, probe.isoformat()
        probe -= timedelta(days=1)
    return False, None


def freshness_error_with_context(
    snapshot_date: str,
    today: Any,
    trading_today: bool,
    latest_trading_day: Optional[str],
) -> Optional[str]:
    """快照日期新鲜度纯判定（无 IO）：给定交易日上下文返回 None=可入库，否则 skip 原因。

    - date=当日 → None；交易日 → stale_snapshot_date（只收当日）；
    - 非交易日 → date=最近交易日 → None（周末推上一交易日收盘详情），否则 stale；
    - 无已知最近交易日（日历异常）→ 保守 stale（不猜）。
    """
    date = str(snapshot_date or "").strip()
    if not _DATE_RE.fullmatch(date):
        return "invalid_snapshot_date"
    if date == today.isoformat():
        return None
    if trading_today:
        return "stale_snapshot_date"
    if latest_trading_day and date == latest_trading_day:
        return None
    return "stale_snapshot_date"


def snapshot_date_freshness_error(snapshot_date: str, now: datetime) -> Optional[str]:
    """2103 四打板通道快照日期新鲜度护栏：返回 None=可入库，否则为结构化 skip 原因。

    口径（2026-11-09 盘中错档事故固化）：快照 date 取自 2103 推送帧自带 date 字段
    （kpl_collector_service.get_daban_list 透传），上游翻日可能滞留——事故复盘：11-09
    盘前/早盘帧仍带 date=2026-11-06（KPL 服务端未翻日），当日成员被成员并集合并进
    上一交易日档，污染其收盘终态（sealed/broken 重标、字段随当日帧刷新）。

    - 交易日（含盘前）：只接受 date=当日。上一交易日档当日已在盘后落库定格，重推的
      「上一交易日详情」并回旧档无增量价值，只有翻日滞留错档风险 → 一律 skip
      （fail-visible 进 lastResult，不写、不伪装成功）。
    - 非交易日：只接受最近一个交易日（周末推送的是上一交易日收盘详情，与 reason
      通道「周末详情挂上一交易日」口径一致）。
    - 日期缺失/非 YYYY-MM-DD：invalid_snapshot_date（不猜）。

    交易日判定走 is_trading_day_cached（bridge → 本地缓存 → 周一~五启发）；**含 IO，
    勿在事件循环内直调**——_archive_once 用 to_thread 预计算上下文后走纯函数
    freshness_error_with_context；本同步封装仅供测试/脚本单次调用。仅约束
    _archive_once 自动归档链，archive_*_snapshot 纯函数与手工 ingest/回填路径不受限。
    """
    date = str(snapshot_date or "").strip()
    if not _DATE_RE.fullmatch(date):
        return "invalid_snapshot_date"
    if date == now.date().isoformat():
        return None
    trading_today, latest = _trading_day_context(now)
    return freshness_error_with_context(date, now.date(), trading_today, latest)


def archive_lane_snapshot(
    db: Any,
    snapshot: dict[str, Any],
    *,
    lane: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """把一份 2103 合并快照合并进 kpl_daban_pool 日档的指定通道（成员并集）。

    口径（2026-11-07 用户评审提出炸板缺陷后固化）：涨停池/跌停池=当前封住口径，盘中封住、
    尾盘炸板（打开跌停）未回封的股只出现在盘中帧——若按「最新一帧覆盖写」日档会丢失。故改为：
    - 入池过即留档（按 stock_id 成员并集，字段随最新帧刷新）；
    - 掉出语义通道（涨停池/跌停池，mark_broken=True）：本帧在池 → pool_state='sealed'；
      曾入池、本帧掉出 → 'broken'（涨停池=炸板未回封 / 跌停池=打开跌停未回封，字段保留
      其最后封住时快照 + last_seen_ts）；回封自动恢复 'sealed'；防误标：本帧页缺口
      （pages_missing 非空）时跳过掉出标注。
    - 无掉出语义通道（集合竞价/炸板池，mark_broken=False）：只做并集 + 字段刷新
      （竞价五件套 9:25 后冻结，成员为当日曾入列全集；炸板池回封语义由涨停池通道
      sealed 承载，两通道互为印证）。
    日档读写以「读全文 → 只改本通道前缀字段 → 字段级 $set 回写」进行（本文件 gene 通道
    同款并发合同），各通道/各写方互不覆盖。
    纯函数（db 注入，pytest 用假库）；空帧/缺日期不写（结构化返回，不伪装成功）。
    """
    cfg = _LANES[lane]
    p = cfg["prefix"]
    date = str(snapshot.get("date") or "")
    items = snapshot.get("items") or []
    if not date:
        return {"ok": False, "reason": "empty_snapshot", "lane": lane,
                "date": None, "item_n": 0}
    ts = snapshot.get("ts")
    pages_missing = snapshot.get("pages_missing") or []
    incoming: dict[str, dict[str, Any]] = {}
    for it in items:
        sid = str(it.get("stock_id") or "")
        if sid:
            incoming[sid] = it
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get(p + "items") or []:
        sid = str(m.get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    if not items:
        # 空帧（评审 P2-1）：不覆盖已有成员（fail-visible：不因一帧空把日档清空）；
        # 但源可用且池本为空（如 0 家跌停的强市日）是真实事实，首个写入记空档 + empty 标记，
        # 供读口区分「采集成功且 0 家」与「未采集」（后者才走 no_archive / 前端逐日回退）。
        if members:
            return {"ok": True, "lane": lane, "date": date, "item_n": len(members),
                    "empty": False, "note": "empty_snapshot_ignored"}
        if not snapshot.get("pages"):   # 连页都没收到：源不可用，不写、不伪装
            return {"ok": False, "reason": "empty_snapshot", "lane": lane,
                    "date": date, "item_n": 0}
        empty_doc = {
            p + "date": date, p + "ts": ts, p + "pid_type": snapshot.get("pid_type"),
            p + "items": [], p + "empty": True,
            p + "max_size": snapshot.get("max_size"), p + "pages": snapshot.get("pages"),
            p + "pages_expected": snapshot.get("pages_expected"),
            p + "pages_missing": pages_missing, p + "pages_meta": snapshot.get("pages_meta"),
            p + "raw_len": snapshot.get("raw_len"),
            p + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
        }
        # 字段级 $set（与 gene 通道同款）：只写本通道前缀字段，upsert 由过滤器
        # 等值条件带上 _id；避免整 doc 回写把 gene 语料等并行写方的字段回写冲掉（评审 R2-P1）
        db[_COLLECTION].update_one({"_id": date}, {"$set": empty_doc}, upsert=True)
        return {"ok": True, "lane": lane, "date": date, "item_n": 0, "empty": True}
    for sid, it in incoming.items():
        merged = dict(members.get(sid) or {})
        merged.update(it)
        merged["stock_id"] = sid
        merged["last_seen_ts"] = ts
        if cfg["mark_broken"]:
            merged["pool_state"] = "sealed"
        members[sid] = merged
    broken_marked = 0
    if cfg["mark_broken"] and not pages_missing:
        for sid, m in members.items():
            if sid not in incoming and m.get("pool_state") == "sealed":
                m["pool_state"] = "broken"
                broken_marked += 1
    sealed_n = sum(1 for m in members.values() if m.get("pool_state") == "sealed")
    broken_n = sum(1 for m in members.values() if m.get("pool_state") == "broken")
    lane_doc = {
        p + "date": date,
        p + "ts": ts,
        p + "pid_type": snapshot.get("pid_type"),
        p + "items": list(members.values()),   # 全量：具名字段 + quotas×28 原始数组（含未破译位）
        p + "empty": False,
        p + "max_size": snapshot.get("max_size"),
        p + "pages": snapshot.get("pages"),
        p + "pages_expected": snapshot.get("pages_expected"),
        p + "pages_missing": pages_missing,
        p + "pages_meta": snapshot.get("pages_meta"),   # 页级 order_type/sort_type/index/count/indexes
        p + "raw_len": snapshot.get("raw_len"),
        p + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    result: dict[str, Any] = {"ok": True, "lane": lane, "date": date,
                              "item_n": len(members), "broken_marked": broken_marked}
    if cfg["mark_broken"]:
        # sealed_n/broken_n 仅掉出语义通道有意义（竞价/炸板池成员无 pool_state，
        # 写 doc 与 status 载荷都不带，避免恒 0 语义噪声，评审 P2-4）
        lane_doc[p + "sealed_n"] = sealed_n
        lane_doc[p + "broken_n"] = broken_n
        result["sealed_n"] = sealed_n
        result["broken_n"] = broken_n
    db[_COLLECTION].update_one({"_id": date}, {"$set": lane_doc}, upsert=True)
    return result


def archive_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """涨停池通道（pidType=1，无前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="pool", now=now)


def archive_bid_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """集合竞价通道（pidType=8，bid_ 前缀字段）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="bid", now=now)


def archive_zb_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """炸板池通道（pidType=2，zb_ 前缀字段；2026-11-08 增补）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="zb", now=now)


def archive_dt_snapshot(db: Any, snapshot: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """跌停池通道（pidType=3，dt_ 前缀字段；2026-11-08 增补）入口；详见 archive_lane_snapshot。"""
    return archive_lane_snapshot(db, snapshot, lane="dt", now=now)


def load_day(db: Any, date: str, *, lane: str = "pool") -> dict[str, Any]:
    """按日读存档；无档/该通道无数据返回结构化降级（fail-visible，不回退默认集合冒充）。

    lane=pool：返回整日档（涨停池字段无前缀 + 竞价/炸板/跌停前缀字段 + reason_items 同 doc 可见）；
    lane=bid/zb/dt：映射为与 /daban-list 同构的载荷（items/ts/max_size/…），前端零转换渲染；
    lane=reason：2203 涨停原因语料（jev 投喂原料，见 load_reason_corpus）。
    """
    if lane == "theme":
        return load_theme_corpus(db, date)
    if lane == "lead":
        from backend.services.kpl_lead_service import load_lead_corpus
        return load_lead_corpus(db, date)
    if lane == "notice":
        return load_notice_corpus(db, date)
    if lane == "reason":
        return load_reason_corpus(db, date)
    if lane == "gene":
        return load_gene_corpus(db, date)
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date, "lane": lane}
    row.pop("_id", None)
    if lane not in _LANES:
        return {"ok": False, "degraded": True, "reason": "invalid_lane", "date": date, "lane": lane}
    p = _LANES[lane]["prefix"]
    if not row.get(p + "items"):
        # 「采集成功且池为空」（如 0 家跌停）与「未采集」严格分开（评审 P2-1）：
        # 前者 ok:true + empty:true + items:[]（不触发前端逐日回退，不伪装成降级），
        # 后者才 no_archive（前端逐日回退找最近有档交易日）。
        if row.get(p + "empty"):
            return {"ok": True, "source": "local_archive", "lane": lane, "empty": True,
                    "date": row.get(p + "date") or date, "ts": row.get(p + "ts"),
                    "pid_type": row.get(p + "pid_type"), "items": [],
                    "max_size": row.get(p + "max_size"), "pages": row.get(p + "pages"),
                    "pages_expected": row.get(p + "pages_expected"),
                    "pages_missing": row.get(p + "pages_missing"),
                    "pages_meta": row.get(p + "pages_meta"), "raw_len": row.get(p + "raw_len"),
                    "archived_at": row.get(p + "archived_at"),
                    "note": f"该日{_LANE_LABELS.get(lane, lane)}采集成功且池为空（0 家）"}
        return {"ok": False, "degraded": True, "reason": "no_archive", "date": date,
                "lane": lane,
                "note": f"日档存在但{_LANE_LABELS.get(lane, lane)}通道无数据（旧档或该页签采集未运行）"}
    if lane == "pool":
        # 涨停池读口=整日档（无前缀字段 + 其它通道前缀字段同 doc 可见，既有合同）
        return {"ok": True, "source": "local_archive", "lane": lane, "empty": False, **row}
    return {
        "ok": True, "source": "local_archive", "lane": lane, "empty": False,
        "date": row.get(p + "date"), "ts": row.get(p + "ts"),
        "pid_type": row.get(p + "pid_type"), "items": row.get(p + "items"),
        "max_size": row.get(p + "max_size"), "pages": row.get(p + "pages"),
        "pages_expected": row.get(p + "pages_expected"),
        "pages_missing": row.get(p + "pages_missing"),
        "pages_meta": row.get(p + "pages_meta"), "raw_len": row.get(p + "raw_len"),
        "archived_at": row.get(p + "archived_at"),
    }


# 2203 涨停原因语料保留字段（原文透传，不改写不拼接）：涨停原因/风险/减持/解禁/质押/
# 梯队/主题/子主题/标签/关联板块/排名/Top/消息 id；HTTP 历史档案链补录字段（2026-11-09
# 回填增补）：Reason 全文同源映射 zt（README 实测双源一致）+ GNSM/Boom_ZS/SCLT/ZSCode
# 原文 + 源标注/匹配日，组合口径（如 zt+plate）由消费方决定，落库只保证原料在且可追溯。
_REASON_FIELDS = ("zt", "fx", "jc", "jj", "pledge", "zt_group", "theme", "dd",
                  "child_theme", "label", "zt_tag", "rank", "rank_total", "rank_top",
                  "plate", "tp", "msg_id",
                  "gns", "boom_zs", "sclt", "zs_codes", "matched_date", "source")
_REASON_LANE = "reason"
_THEME_LANE = "theme"


def _ts_date(ts: Any) -> str:
    """推送 ts（unix 秒）→ 北京时间日期串；非法 ts 返空串（不猜）。"""
    try:
        return datetime.fromtimestamp(float(ts), TZ_SHANGHAI).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _reason_incoming(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """2203 快照 → {stock_id: item}（兼容 collector 读口 reasons dict 与 items list）。"""
    raw = snapshot.get("reasons")
    if raw is None:
        raw = snapshot.get("items")   # 兼容 items list 形态（2203 快照两种载荷）
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for sid, item in raw.items():
            if isinstance(item, dict) and str(sid or "").strip():
                out[str(sid).strip()] = dict(item)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                sid = str(item.get("stock_id") or "").strip()
                if sid:
                    out[sid] = dict(item)
    return out


def archive_reason_corpus(db: Any, snapshot: dict[str, Any], *,
                          now: Optional[datetime] = None,
                          source: str = "socket_2203") -> dict[str, Any]:
    """2203 涨停原因详情语料落库（2026-11-08 用户需求：作为 jev 语料投喂）。

    source：语料来源标注（doc 级 reason_source + 逐条 item.source 由调用方在载荷内带）；
    socket 推送=socket_2203（默认）；HTTP 历史档案链回填=http_GetDayZhangTing（2026-11-09
    盘中 2203 因 collector 会话抖动全天零到流后的补录路径，zt←Reason 为 README 实测
    同源映射，其余 HTTP 原文字段经 _REASON_FIELDS 透传）。

    写入 kpl_daban_pool 同日档的 reason_ 前缀字段（不另建数据集，与打板通道同步）：
    - reason_items：按 stock_id 并集，字段随最新帧刷新（留 first_ts 首次到流时间）；
    - reason_date/reason_ts/reason_count/reason_archived_at/reason_source；
    - 日期 = 调用方注入的交易日（archiver 取涨停池快照 date：周末/盘前推送的是上一
      交易日详情）；无 date → 不写（不猜）；
    - 跨日残留保护：条目 ts 转北京时间早于该日 → 跳过（skipped_stale），不污染当日档。
    纯函数（db 注入）；空快照/全陈旧不写既有语料（fail-visible 结构化返回）。
    """
    date = str(snapshot.get("date") or "")
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _REASON_LANE,
                "date": None, "item_n": 0}
    incoming = _reason_incoming(snapshot)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get("reason_items") or []:
        sid = str(m.get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    if not incoming:
        return {"ok": False, "reason": "empty_reasons", "lane": _REASON_LANE,
                "date": date, "item_n": len(members)}
    merged_n = skipped_stale = 0
    for sid, it in incoming.items():
        ts = it.get("ts")
        ts_date = _ts_date(ts)
        if ts_date and ts_date < date:
            skipped_stale += 1
            continue
        merged = dict(members.get(sid) or {})
        for f in _REASON_FIELDS:
            if f in it and it[f] not in (None, "", []):
                merged[f] = it[f]
        merged["stock_id"] = sid
        if ts:
            merged["ts"] = ts
            merged["ts_date"] = ts_date or merged.get("ts_date")
            merged.setdefault("first_ts", ts)   # 仅有效 ts 落首次到流（None 占位会堵死回填）
        members[sid] = merged
        merged_n += 1
    if not merged_n:
        return {"ok": False, "reason": "all_stale", "lane": _REASON_LANE, "date": date,
                "item_n": len(members), "skipped_stale": skipped_stale}
    doc = {
        "reason_date": date,
        "reason_source": source,
        "reason_items": list(members.values()),
        "reason_count": len(members),
        "reason_ts": max((m.get("ts") or 0) for m in members.values()),
        "reason_archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)   # 字段级 $set，同上
    return {"ok": True, "lane": _REASON_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "skipped_stale": skipped_stale}


def load_reason_corpus(db: Any, date: str) -> dict[str, Any]:
    """2203 涨停原因语料读口（jev 投喂原料）：{ok, date, items, count, ts, archived_at}。

    fail-visible：「日档不存在」（no_archive）与「日档在但语料未落库」（no_reason_corpus，
    该日 collector 未开 2203 订阅或盘中未运行）严格分开，不伪装空语料。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _REASON_LANE}
    items = row.get("reason_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_reason_corpus",
                "date": date, "lane": _REASON_LANE, "item_n": 0,
                "note": "日档存在但 2203 涨停原因语料未落库（需当日盘中运行 collector 且 KPL_ZT_REASON_SUBS≠0）"}
    return {"ok": True, "source": "local_archive", "lane": _REASON_LANE,
            "date": row.get("reason_date") or date, "items": items,
            "count": len(items), "ts": row.get("reason_ts"),
            "archived_at": row.get("reason_archived_at"),
            "corpus_source": row.get("reason_source") or "socket_2203"}


def _theme_incoming(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """2013 快照 → {stock_id: item}（兼容 themes dict 与 items list 两种载荷形态）。"""
    raw = snapshot.get("themes")
    if raw is None:
        raw = snapshot.get("items")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for sid, item in raw.items():
            if isinstance(item, dict) and str(sid or "").strip():
                out[str(sid).strip()] = dict(item)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                sid = str(item.get("stock_id") or "").strip()
                if sid:
                    out[sid] = dict(item)
    return out


def archive_theme_corpus(db: Any, snapshot: dict[str, Any], *,
                         now: Optional[datetime] = None) -> dict[str, Any]:
    """2013 题材库热度语料落库（2026-11-08 题材龙头语料第 2 项，jev 投喂原料）。

    写入 kpl_daban_pool 同日档 theme_ 前缀字段（与 reason 通道同款合同）：
    - theme_items：按 stock_id 并集（{stock_id, name, themes:[{id,name,number}], ts,
      first_ts}），字段随最新帧刷新；
    - theme_date/theme_ts/theme_count/theme_archived_at/theme_source；
    - 日期 = 调用方注入的涨停池快照交易日；无 date → 不写（不猜）；
    - 跨日残留保护：条目 ts 转北京时间早于该日 → 跳过（skipped_stale）。
    纯函数（db 注入）；空快照/全陈旧不写既有语料（fail-visible 结构化返回）。
    """
    date = str(snapshot.get("date") or "")
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _THEME_LANE,
                "date": None, "item_n": 0}
    incoming = _theme_incoming(snapshot)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get("theme_items") or []:
        sid = str(m.get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    if not incoming:
        return {"ok": False, "reason": "empty_themes", "lane": _THEME_LANE,
                "date": date, "item_n": len(members)}
    merged_n = skipped_stale = 0
    for sid, it in incoming.items():
        ts = it.get("ts")
        ts_date = _ts_date(ts)
        if ts_date and ts_date < date:
            skipped_stale += 1
            continue
        merged = dict(members.get(sid) or {})
        for f in ("stock_id", "name", "themes"):
            if f in it and it[f] not in (None, "", []):
                merged[f] = it[f]
        merged["stock_id"] = sid
        if ts:
            merged["ts"] = ts
            merged["ts_date"] = ts_date or merged.get("ts_date")
            merged.setdefault("first_ts", ts)
        members[sid] = merged
        merged_n += 1
    if not merged_n:
        return {"ok": False, "reason": "all_stale", "lane": _THEME_LANE, "date": date,
                "item_n": len(members), "skipped_stale": skipped_stale}
    doc = {
        "theme_date": date,
        "theme_source": "socket_2013",
        "theme_items": list(members.values()),
        "theme_count": len(members),
        "theme_ts": max((m.get("ts") or 0) for m in members.values()),
        "theme_archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)   # 字段级 $set
    return {"ok": True, "lane": _THEME_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "skipped_stale": skipped_stale}


def load_theme_corpus(db: Any, date: str) -> dict[str, Any]:
    """2013 题材库热度语料读口（jev 投喂原料）：{ok, date, items, count, ts, archived_at}。

    fail-visible：「日档不存在」（no_archive）与「日档在但语料未落库」（no_theme_corpus，
    该日 collector 未开 2013 订阅或盘中未运行）严格分开，不伪装空语料。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _THEME_LANE}
    items = row.get("theme_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_theme_corpus",
                "date": date, "lane": _THEME_LANE, "item_n": 0,
                "note": "日档存在但 2013 题材库语料未落库（需当日盘中运行 collector 且 KPL_THEME_SUBS≠0）"}
    return {"ok": True, "source": "local_archive", "lane": _THEME_LANE,
            "date": row.get("theme_date") or date, "items": items,
            "count": len(items), "ts": row.get("theme_ts"),
            "archived_at": row.get("theme_archived_at"),
            "corpus_source": row.get("theme_source") or "socket_2013"}


# ── 2112 上榜预测 / 3004-3101 实时龙虎榜语料通道（2026-11-11 ③）────────────
# 写入方 = collector（:8002）单写者：2112/3004/3101 推送帧解析成功后即时落库
# （与 2203/2013 推送即落库同款时点），本服务不轮询这两通道。
# 合同（沿 reason_/theme_ 先例）：同 kpl_daban_pool 日档前缀字段（fc_/rt_）、
# stock_id 并集、字段随新帧刷新（留 first_ts）、跨日残留 skip、空帧抑制
# （沿 2112 现规：空 items 不覆盖非空，fail-visible 结构化返回）；日期 = 调用方
# 注入的涨停池快照交易日。
_FC_LANE = "fc"
_RT_LANE = "rt"
# 2112 ForecastLHBResp.Item 保留字段（parse_forecast_lhb 具名字段；quota 原始值透传）
_FC_FIELDS = ("stock_name", "plate", "price", "zf", "tur_rate", "tur",
              "main_net_amount", "main_buy", "main_sell", "hot_val", "hot_change",
              "reason", "rank_state", "is_new")
# 3004/3101 RealtimeLHB items 复用 GroupStockQuotasResp.Item（quotas 原样数组，
# 缩放未破译不猜——单一事实源同 3001 约定）
_RT_FIELDS = ("name", "quotas")


def _corpus_incoming(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """items list 快照 → {stock_id: item}（兼容 dict 形态）。"""
    raw = snapshot.get("items")
    if raw is None:
        raw = snapshot.get("stocks")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for sid, item in raw.items():
            if isinstance(item, dict) and str(sid or "").strip():
                out[str(sid).strip()] = dict(item)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                sid = str(item.get("stock_id") or "").strip()
                if sid:
                    out[sid] = dict(item)
    return out


def _archive_stock_corpus(db: Any, snapshot: dict[str, Any], *, lane: str,
                          fields: tuple[str, ...], prefix: str,
                          source: str,
                          now: Optional[datetime] = None) -> dict[str, Any]:
    """单股并集语料通道通用落库（fc/rt/bdo/bf/abn/rplate 同款合同，单一实现）。

    - {prefix}items：按 stock_id 并集，whitelist 字段随新帧刷新（留 first_ts 首次到流）；
    - {prefix}date/ts/count/archived_at/source；日期 = 调用方注入交易日，无 → 不写；
    - 跨日残留：条目 ts 转北京时间早于该日 → skip（不污染当日档）；
    - 空帧抑制：空 items 不覆盖已有语料（fail-visible 结构化返回 ok False）。
    纯函数（db 注入）；字段级 $set，不整 doc 回写。
    """
    date = str(snapshot.get("date") or "")
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": lane,
                "date": None, "item_n": 0}
    incoming = _corpus_incoming(snapshot)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for m in row.get(prefix + "items") or []:
        sid = str((m or {}).get("stock_id") or "")
        if sid:
            members[sid] = dict(m)
    if not incoming:
        return {"ok": False, "reason": f"empty_{lane}_items", "lane": lane,
                "date": date, "item_n": len(members), "empty": True}
    merged_n = skipped_stale = 0
    for sid, it in incoming.items():
        ts = it.get("ts")
        ts_date = _ts_date(ts)
        if ts_date and ts_date < date:
            skipped_stale += 1
            continue
        merged = dict(members.get(sid) or {})
        for f in fields:
            if f in it and it[f] not in (None, "", []):
                merged[f] = it[f]
        merged["stock_id"] = sid
        if ts:
            merged["ts"] = ts
            merged["ts_date"] = ts_date or merged.get("ts_date")
            merged.setdefault("first_ts", ts)
        members[sid] = merged
        merged_n += 1
    if not merged_n:
        return {"ok": False, "reason": "all_stale", "lane": lane, "date": date,
                "item_n": len(members), "skipped_stale": skipped_stale}
    doc = {
        prefix + "date": date,
        prefix + "source": source,
        prefix + "items": list(members.values()),
        prefix + "count": len(members),
        prefix + "ts": max((m.get("ts") or 0) for m in members.values()),
        prefix + "archived_at": (now or datetime.now(TZ_SHANGHAI)).isoformat(),
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)
    return {"ok": True, "lane": lane, "date": date, "item_n": len(members),
            "merged_n": merged_n, "skipped_stale": skipped_stale}


def _load_stock_corpus(db: Any, date: str, *, lane: str, prefix: str) -> dict[str, Any]:
    """单股并集语料读口（fail-visible：no_archive 与 no_<lane>_corpus 严格分开）。"""
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": lane}
    items = row.get(prefix + "items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": f"no_{lane}_corpus",
                "date": date, "lane": lane, "item_n": 0}
    return {"ok": True, "source": "local_archive", "lane": lane,
            "date": row.get(prefix + "date") or date, "items": items,
            "count": len(items), "ts": row.get(prefix + "ts"),
            "archived_at": row.get(prefix + "archived_at"),
            "corpus_source": row.get(prefix + "source")}


def archive_lhb_forecast(db: Any, snapshot: dict[str, Any], *,
                         now: Optional[datetime] = None,
                         source: str = "socket_2112") -> dict[str, Any]:
    """2112 会不会上龙虎榜预测语料落库（fc_ 前缀；2026-11-11 ③）。

    写入方 = collector 推送即落库（单写者）；合同见 _archive_stock_corpus。
    """
    return _archive_stock_corpus(db, snapshot, lane=_FC_LANE,
                                 fields=_FC_FIELDS, prefix="fc_", source=source, now=now)


def load_lhb_forecast(db: Any, date: str) -> dict[str, Any]:
    """2112 上榜预测语料读口（jev 投喂原料）。"""
    return _load_stock_corpus(db, date, lane=_FC_LANE, prefix="fc_")


def archive_lhb_realtime(db: Any, snapshot: dict[str, Any], *,
                         now: Optional[datetime] = None,
                         source: str = "socket_3004") -> dict[str, Any]:
    """3004/3101 实时龙虎榜语料落库（rt_ 前缀；2026-11-11 ③）。"""
    return _archive_stock_corpus(db, snapshot, lane=_RT_LANE,
                                 fields=_RT_FIELDS, prefix="rt_", source=source, now=now)


def load_lhb_realtime(db: Any, date: str) -> dict[str, Any]:
    """3004/3101 实时龙虎榜语料读口（jev 投喂原料）。"""
    return _load_stock_corpus(db, date, lane=_RT_LANE, prefix="rt_")


# ── 个股详情四通道语料（2014 封板大单/2202 爆发原因/2030 异动提醒/2010 所属板块，
#    2026-11-11 ④；**本轮只落协议+落库+读口+叙事 mock，不实弹开火**）────────────
# 写入方 = collector（单写者，订阅面=涨停池成员，订阅开关默认关）；bdo_/bf_/abn_/
# rplate_ 前缀日档，合同同 fc_/rt_（_archive_stock_corpus 单一实现）。
_DETAIL_LANES: dict[str, dict[str, Any]] = {
    # bdo：items 明细列表原样 + 采集侧聚合。raw sum（zt_tur/buy_tur/sell_tur）仅审计
    # 保留（级值/累计 sum 无意义，向后兼容不删）；2026-11-11 裁决追加尾条派生
    # zt_tur_yuan/buy_tur_yuan/sell_tur_yuan（元口径，复用协议层
    # bdo_aggregate_last，证据见 docs/kpl-socket/detail-scaling-verification.md）
    "bdo": {"prefix": "bdo_", "source": "socket_2014",
            "fields": ("type", "zt_state", "total", "items",
                       "zt_tur", "buy_tur", "sell_tur",
                       "zt_tur_yuan", "buy_tur_yuan", "sell_tur_yuan")},
    "bf": {"prefix": "bf_", "source": "socket_2202",
           "fields": ("desc", "jump_id")},
    # abn：price 族缩放与 next_day_zf 口径 2026-11-11 阴性未钉死（当日事件推送三字段
    # 全缺位），保持 raw 透出，无派生字段（复验路径见 detail-scaling-verification.md）
    "abn": {"prefix": "abn_", "source": "socket_2030",
            "fields": ("price", "date", "next_day_price", "next_day_zf")},
    "rplate": {"prefix": "rplate_", "source": "socket_2010",
               "fields": ("plates", "indexes", "max_size")},
}


def archive_stock_detail_corpus(db: Any, snapshot: dict[str, Any], *,
                                lane: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """个股详情通道语料落库（lane=bdo/bf/abn/rplate，合同同 fc/rt）。"""
    cfg = _DETAIL_LANES[lane]
    return _archive_stock_corpus(db, snapshot, lane=lane,
                                 fields=tuple(cfg["fields"]), prefix=cfg["prefix"],
                                 source=cfg["source"], now=now)


def load_stock_detail_corpus(db: Any, date: str, *, lane: str) -> dict[str, Any]:
    """个股详情通道语料读口（lane=bdo/bf/abn/rplate）。"""
    cfg = _DETAIL_LANES[lane]
    return _load_stock_corpus(db, date, lane=lane, prefix=cfg["prefix"])


# ── 公告/新闻/研报计数语料通道（2026-11-08 题材龙头语料第 3 项）────────────
# 协议层见 backend/services/kpl_stock_notice.py（apphis CompanyNotice/GetCompanyCount，
# announcement/report/news 三计数 + 上游数据日期；计数统计窗口上游未标注 → 原样透出
# window_note 不自算）。与 gene 通道同款懒取模式：单股粒度 HTTP、_post_form 全局 ≥2s
# 限频、每轮限量、缺失优先 + 收盘后刷终值；公告标题/正文不进叙事（只出计数与日期）。
_NOTICE_LANE = "notice"


def pick_notice_targets(db: Any, date: str, *, limit: int = 6,
                        now: Optional[datetime] = None) -> dict[str, Any]:
    """挑本轮要拉公告计数的成员（与 pick_gene_targets 同款：缺失优先，收盘后刷终值）。"""
    stamp = now or datetime.now(TZ_SHANGHAI)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    members = _pool_member_ids(row)
    if not members:
        reason = "no_archive" if not row else "empty_pool"
        return {"ok": False, "reason": reason, "date": date,
                "targets": [], "pending_n": 0, "refresh_n": 0}
    done: dict[str, str] = {}
    for g in row.get("notice_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            done[sid] = str(g.get("fetched_at") or "")
    cutoff = _close_cutoff(date)
    after_close = stamp.isoformat() >= cutoff
    missing = [sid for sid in members if sid not in done]
    refresh = [sid for sid in members if sid in done and after_close and done[sid] < cutoff]
    ordered = missing + refresh
    return {"ok": True, "date": date, "targets": ordered[:max(0, int(limit))],
            "pending_n": len(missing), "refresh_n": len(refresh),
            "member_n": len(members), "notice_n": len(done), "after_close": after_close}


def archive_notice_corpus(db: Any, payload: dict[str, Any], *,
                          now: Optional[datetime] = None) -> dict[str, Any]:
    """公告计数语料落库（2026-11-08 题材龙头语料第 3 项，jev 投喂原料）。

    payload: {"date": 交易日, "notices": [get_notice_count 结果, ...]}
    与 archive_gene_corpus 同款合同（notice_ 前缀字段级 $set；仅 ok 条目并入，
    失败进 notice_failures；fetched_date/same_day 时点标记；本批无一成功且无既有
    语料 → ok False 不覆盖不伪装）。
    """
    date = str(payload.get("date") or "")
    notices = payload.get("notices") or []
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _NOTICE_LANE,
                "date": None, "item_n": 0}
    stamp = (now or datetime.now(TZ_SHANGHAI)).isoformat()
    fetched_date = stamp[:10]
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for g in row.get("notice_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            members[sid] = dict(g)
    merged_n = 0
    failures: list[dict[str, Any]] = []
    for res in (notices if isinstance(notices, list) else []):
        res = res if isinstance(res, dict) else {}
        sid = str(res.get("stock_id") or "").strip()
        if not res.get("ok"):
            failures.append({"stock_id": sid, "reason": res.get("reason") or "failed",
                             "error": str(res.get("error") or "")[:120]})
            continue
        if not sid:
            failures.append({"stock_id": "", "reason": "missing_stock_id"})
            continue
        members[sid] = {
            "stock_id": sid,
            "counts": res.get("counts") or {},
            "upstream_date": res.get("upstream_date"),
            "window_note": res.get("window_note"),
            "fetched_date": fetched_date,
            "same_day": fetched_date == date,
            "fetched_at": stamp,
            "source": "http_GetCompanyCount",
        }
        merged_n += 1
    if not merged_n and not members:
        return {"ok": False, "reason": "no_notice_fetched", "lane": _NOTICE_LANE,
                "date": date, "item_n": 0, "failures_n": len(failures)}
    pending = [sid for sid in _pool_member_ids(row) if sid not in members]
    doc = {
        "notice_date": date,
        "notice_source": "http_GetCompanyCount",
        "notice_items": list(members.values()),
        "notice_count": len(members),
        "notice_pending_n": len(pending),
        "notice_failures": failures,
        "notice_archived_at": stamp,
    }
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)   # 字段级 $set
    return {"ok": True, "lane": _NOTICE_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "failures_n": len(failures), "pending_n": len(pending)}


def load_notice_corpus(db: Any, date: str) -> dict[str, Any]:
    """公告计数语料读口：{ok, date, items, count, pending_n, backfill_n, ...}。

    fail-visible：「日档不存在」（no_archive）与「日档在但语料未落库」（no_notice_corpus）
    严格分开；backfill_n>0 = 回填条目（值含抓取日之后信息，不得当该日盘后已知信息用）。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _NOTICE_LANE}
    items = row.get("notice_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_notice_corpus",
                "date": date, "lane": _NOTICE_LANE, "item_n": 0,
                "failures": row.get("notice_failures") or [],
                "note": "日档存在但公告计数语料未落库（存档器未运行或该轮全部拉取失败）"}
    backfill_n = sum(1 for it in items if it.get("same_day") is False)
    return {"ok": True, "source": "local_archive", "lane": _NOTICE_LANE,
            "date": row.get("notice_date") or date, "items": items,
            "count": len(items), "pending_n": row.get("notice_pending_n") or 0,
            "same_day_n": len(items) - backfill_n, "backfill_n": backfill_n,
            "failures": row.get("notice_failures") or [],
            "archived_at": row.get("notice_archived_at"),
            "corpus_source": row.get("notice_source") or "http_GetCompanyCount"}


# ── 涨停基因（溢价基因）语料通道（2026-11-08 用户需求：题材龙头语料投喂 jev）────────────
# 协议层见 backend/services/kpl_stock_gene.py（apphq StockL2Data/GetZhangTingGene，
# 六元数组=涨停次数/溢价5%次数/次日红盘率%/首板封板率%/首板被板率%/连板率%，
# 上游未标注统计窗口 → 原样透出 window_note，不自算）。与 reason_items 同款：不另建
# 数据集，同一 kpl_daban_pool 日档 gene_ 前缀字段；本通道随打板通道单写者整 doc 回写。
_GENE_LANE = "gene"
_GENE_CLOSE_CUTOFF = (15, 5)   # 收盘后刷新时点 15:05：盘中先拉保可用，收盘后刷终值


def _pool_member_ids(row: dict[str, Any]) -> list[str]:
    """日档涨停池成员 stock_id（无前缀 items 字段），保持原始顺序。"""
    out: list[str] = []
    for m in row.get("items") or []:
        sid = str((m or {}).get("stock_id") or "").strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def _close_cutoff(date: str) -> str:
    """该日档的收盘后刷新截止时刻（该交易日本地 15:05，ISO 可比字符串）。

    按**日档交易日**而非当前日计算：回填历史日档时 fetched_at 天然晚于该截止点，
    不会被当轮反复刷新（每档至多一次盘中值 + 一次终值）。
    """
    return f"{date}T{_GENE_CLOSE_CUTOFF[0]:02d}:{_GENE_CLOSE_CUTOFF[1]:02d}:00+08:00"


_GENE_BACKFILL_DAYS = 10   # :8002 停推时的回填窗口（更早的档不再补，避免无意义开火）


def latest_archived_pool_day(db: Any, *, now: Optional[datetime] = None) -> Optional[str]:
    """最近一个「含涨停池成员」的日档交易日（:8002 无快照时 gene 通道的回填目标）。

    基因端点走 apphq HTTP，与采集器无关；只缺「今天是哪个交易日」这一信息。周末/盘前
    采集器重启后内存快照为空时，用库内最近的池日档补语料（fail-visible：无档返回 None，
    不猜日期）。窗口 _GENE_BACKFILL_DAYS 天，避免把很久以前的档当轮反复刷。
    """
    stamp = now or datetime.now(TZ_SHANGHAI)
    floor = (stamp.date() - timedelta(days=_GENE_BACKFILL_DAYS)).isoformat()
    row = db[_COLLECTION].find_one({"items.0": {"$exists": True}, "_id": {"$gte": floor}},
                                   sort=[("_id", -1)])
    return str(row["_id"]) if row else None


def pick_gene_targets(db: Any, date: str, *, limit: int = 6,
                      now: Optional[datetime] = None) -> dict[str, Any]:
    """挑本轮要拉基因的成员（纯函数，不写库）：缺失优先，收盘后补一次终值刷新。

    顺序：①涨停池成员中尚无 gene_items 的股（按池内顺序）→ ②收盘后（≥15:05）对盘中
    拉的旧值（fetched_at < 当日 15:05）各刷新一次。limit 控发数（协议层 _post_form 全局
    ≥2s 单发间隔，不能一轮打 30 只）。日档不存在/池为空 → targets 空 + 结构化 reason。
    """
    stamp = now or datetime.now(TZ_SHANGHAI)
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    members = _pool_member_ids(row)
    if not members:
        reason = "no_archive" if not row else "empty_pool"
        return {"ok": False, "reason": reason, "date": date,
                "targets": [], "pending_n": 0, "refresh_n": 0}
    done: dict[str, str] = {}
    for g in row.get("gene_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            done[sid] = str(g.get("fetched_at") or "")
    cutoff = _close_cutoff(date)
    after_close = stamp.isoformat() >= cutoff
    missing = [sid for sid in members if sid not in done]
    refresh = [sid for sid in members if sid in done and after_close and done[sid] < cutoff]
    ordered = missing + refresh
    return {"ok": True, "date": date, "targets": ordered[:max(0, int(limit))],
            "pending_n": len(missing), "refresh_n": len(refresh),
            "member_n": len(members), "gene_n": len(done), "after_close": after_close}


def archive_gene_corpus(db: Any, payload: dict[str, Any], *,
                        now: Optional[datetime] = None) -> dict[str, Any]:
    """涨停基因语料落库（2026-11-08 用户需求：题材龙头语料投喂 jev）。

    payload: {"date": 交易日, "genes": [get_zt_gene 结果, ...]}
    写入 kpl_daban_pool 同日档 gene_ 前缀字段（与打板通道同款「读全文 → 只改本通道字段
    → 字段级 $set 回写」，各通道/各写方互不覆盖）：
    - gene_items：按 stock_id 并集（仅 ok 条目；raw 六元数组原样 + 具名字段 + window_note
      + fetched_date/same_day 时点标记 + fetched_at + source），失败条目进 gene_failures；
    - gene_date/gene_source/gene_count/gene_pending_n/gene_failures/gene_archived_at；
      gene_pending_n = 涨停池成员中尚无基因的只数（消费方据此判语料覆盖度）。
    时点语义：端点返回「抓取时点」统计，回填历史日档（fetched_date≠交易日）的值含此后
    信息 → same_day=False，读口透出 backfill_n + note（不得当该日盘后已知信息用）。
    本批无一成功且无既有语料 → ok False（no_gene_fetched），不覆盖既有、不伪装。
    """
    date = str(payload.get("date") or "")
    genes = payload.get("genes") or []
    if not date:
        return {"ok": False, "reason": "no_pool_date", "lane": _GENE_LANE,
                "date": None, "item_n": 0}
    stamp = (now or datetime.now(TZ_SHANGHAI)).isoformat()
    fetched_date = stamp[:10]
    row = dict(db[_COLLECTION].find_one({"_id": date}) or {})
    row.pop("_id", None)
    members: dict[str, dict[str, Any]] = {}
    for g in row.get("gene_items") or []:
        sid = str((g or {}).get("stock_id") or "").strip()
        if sid:
            members[sid] = dict(g)
    merged_n = 0
    failures: list[dict[str, Any]] = []
    for res in (genes if isinstance(genes, list) else []):
        res = res if isinstance(res, dict) else {}
        sid = str(res.get("stock_id") or "").strip()
        if not res.get("ok"):
            failures.append({"stock_id": sid, "reason": res.get("reason") or "failed",
                             "error": str(res.get("error") or "")[:120]})
            continue
        if not sid:
            failures.append({"stock_id": "", "reason": "missing_stock_id"})
            continue
        item: dict[str, Any] = {
            "stock_id": sid,
            "gene": res.get("gene") or {},
            "gene_labels": res.get("gene_labels") or {},
            "raw": res.get("raw"),
            "raw_len": res.get("raw_len"),
            "window_note": res.get("window_note"),
            "fetched_date": fetched_date,
            "same_day": fetched_date == date,   # False=回填（值含抓取日之后的信息）
            "fetched_at": stamp,
            "source": "http_GetZhangTingGene",
        }
        if res.get("partial"):
            item["partial"] = True
            item["missing_fields"] = res.get("missing_fields") or []
        members[sid] = item
        merged_n += 1
    if not merged_n and not members:
        return {"ok": False, "reason": "no_gene_fetched", "lane": _GENE_LANE,
                "date": date, "item_n": 0, "failures_n": len(failures)}
    pending = [sid for sid in _pool_member_ids(row) if sid not in members]
    doc = {
        "gene_date": date,
        "gene_source": "http_GetZhangTingGene",
        "gene_items": list(members.values()),
        "gene_count": len(members),
        "gene_pending_n": len(pending),
        "gene_failures": failures,
        "gene_archived_at": stamp,
    }
    # 字段级 $set（与打板/reason 通道同款并发合同）：只写 gene_ 前缀，不整 doc 回写
    db[_COLLECTION].update_one({"_id": date}, {"$set": doc}, upsert=True)
    return {"ok": True, "lane": _GENE_LANE, "date": date, "item_n": len(members),
            "merged_n": merged_n, "failures_n": len(failures), "pending_n": len(pending)}


def load_gene_corpus(db: Any, date: str) -> dict[str, Any]:
    """涨停基因语料读口（jev 投喂原料）：{ok, date, items, count, pending_n, ...}。

    fail-visible：「日档不存在」（no_archive）与「日档在但基因语料未落库」
    （no_gene_corpus）严格分开，不伪装空语料；pending_n>0 = 涨停池成员尚有未拉的股；
    backfill_n>0 = 回填条目（值含抓取日之后信息，不得当该日盘后已知信息用）。
    """
    row = db[_COLLECTION].find_one({"_id": date})
    if not row:
        return {"ok": False, "degraded": True, "reason": "no_archive",
                "date": date, "lane": _GENE_LANE}
    items = row.get("gene_items") or []
    if not items:
        return {"ok": False, "degraded": True, "reason": "no_gene_corpus",
                "date": date, "lane": _GENE_LANE, "item_n": 0,
                "failures": row.get("gene_failures") or [],
                "note": "日档存在但涨停基因语料未落库（存档器未运行或该轮全部拉取失败）"}
    backfill_n = sum(1 for it in items if it.get("same_day") is False)
    out = {"ok": True, "source": "local_archive", "lane": _GENE_LANE,
           "date": row.get("gene_date") or date, "items": items,
           "count": len(items), "pending_n": row.get("gene_pending_n") or 0,
           "same_day_n": len(items) - backfill_n, "backfill_n": backfill_n,
           "failures": row.get("gene_failures") or [],
           "archived_at": row.get("gene_archived_at"),
           "corpus_source": row.get("gene_source") or "http_GetZhangTingGene"}
    if backfill_n:
        out["note"] = (f"{backfill_n} 条为回填抓取（fetched_date≠日档交易日）："
                       "值含抓取日之后的信息，不得当该日盘后已知信息使用")
    return out


class DabanPoolArchiver:
    """周期拉取 ：8002 涨停池/集合竞价/炸板池/跌停池快照 + 涨停基因/公告计数语料（HTTP
    逐股懒取），按日存档（main.py startup 启动，mongodb 模式专用；同一 kpl_daban_pool
    日档各改各前缀/字段）。

    2026-11-10 起单任务循环内顺序处理四打板通道，再拉本轮限量涨停基因/公告计数；
    2013 题材热度 / 2203 涨停原因语料改由 collector 推送即落库（单写者），本服务不再
    轮询。任一通道失败不阻断其它通道（各自结构化记 lastResult）。
    """

    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        database_factory: Callable[[], Any] = get_runtime_mongodb_database,
        settings: Any | None = None,
        upstream_url: str = _UPSTREAM_POOL,
        bid_upstream_url: str = _UPSTREAM_BID,
        zb_upstream_url: str = _UPSTREAM_ZB,
        dt_upstream_url: str = _UPSTREAM_DT,
        gene_fetcher: Callable[[str], dict[str, Any]] = get_zt_gene,
        gene_limit: int = 6,
        notice_fetcher: Callable[[str], dict[str, Any]] = get_notice_count,
        notice_limit: int = 6,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        current = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(TZ_SHANGHAI))
        self.enabled = current.storage_backend == "mongodb"
        self.interval_seconds = max(30, int(interval_seconds))
        self._database_factory = database_factory
        self._upstream_url = upstream_url
        self._bid_upstream_url = bid_upstream_url
        self._zb_upstream_url = zb_upstream_url
        self._dt_upstream_url = dt_upstream_url
        # 涨停基因语料（HTTP 单股粒度、协议层 ≥2s 限频）→ 每轮限量懒取，未拉满的成员
        # 留 gene_pending_n（fail-visible），供 jev 语料消费方判断覆盖度
        self._gene_fetcher = gene_fetcher
        self._gene_limit = max(1, int(gene_limit))
        # 公告计数语料（HTTP 单股粒度、协议层 ≥2s 限频）→ 与 gene 通道同款每轮限量懒取
        self._notice_fetcher = notice_fetcher
        self._notice_limit = max(1, int(notice_limit))
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "intervalSeconds": self.interval_seconds,
            "geneLimit": self._gene_limit,
            "noticeLimit": self._notice_limit,
            "lastRunAt": self._last_run_at,
            "lastResult": self._last_result,
            "lastError": self._last_error,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._archive_once()
            except asyncio.CancelledError:
                return
            except Exception as error:   # 单轮失败不退循环（fail-visible 进 status）
                self._last_error = str(error)
            await asyncio.sleep(self.interval_seconds)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        resp = await client.get(url)
        return resp.json()

    async def _archive_once(self) -> None:
        # 单写者约束：同通道写方仅本服务单实例；跨通道（含 gene 语料通道）各写各前缀字段
        # 且均为字段级 $set，互不覆盖；
        # 四通道 fetch/archive 均逐通道 try/except，任一通道失败不阻断其它通道（含 fetch 阶段）。
        self._last_run_at = self._clock().isoformat()
        results: dict[str, Any] = {}
        # 渐进发布：本轮开始即挂上空 dict，逐通道写入，避免异常时出现
        # 「lastRunAt 新、lastResult 还是上一轮」的半失真态（评审 P1-1）
        self._last_result = results
        # 交易日上下文每轮预计算一次（评审 R2-P）：is_trading_day_cached 含 bridge HTTP
        # 探测，同步直调会阻塞事件循环且逐 lane 重复探测；to_thread 预计算 + 当轮复用。
        _ctx_now = self._clock()
        trading_today, latest_trading_day = await asyncio.to_thread(
            _trading_day_context, _ctx_now)
        stale_cutoff = (_ctx_now - timedelta(days=3)).date().isoformat()
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            pool_date: str | None = None
            for key, url, fn in (
                ("pool", self._upstream_url, archive_snapshot),
                ("bid", self._bid_upstream_url, archive_bid_snapshot),
                ("zb", self._zb_upstream_url, archive_zb_snapshot),
                ("dt", self._dt_upstream_url, archive_dt_snapshot),
            ):
                try:
                    payload = await self._fetch(client, url)
                except Exception as error:   # fetch 阶段失败同样不连带其它通道（评审 M1）
                    results[key] = {"ok": False, "reason": f"fetch_failed:{error}"}
                    continue
                if not payload.get("ok"):
                    # collector 未运行/快照降级：该通道不写、不覆盖既有存档，结构化透出
                    results[key] = {"ok": False,
                                    "reason": f"collector_degraded:{payload.get('reason') or 'unknown'}"}
                    continue
                # 快照日期新鲜度护栏（2026-11-09 盘中错档事故）：date 滞留上一交易日时
                # 结构化 skip，不落库、不污染历史档；pool_date 只从新鲜 payload 取，
                # 语料通道（reason/theme/gene）随之不再被旧 date 挂错档。
                lane_date = str(payload.get("date") or "")
                freshness = freshness_error_with_context(
                    lane_date, _ctx_now.date(), trading_today, latest_trading_day)
                if freshness:
                    results[key] = {"ok": False, "reason": freshness,
                                    "date": lane_date or None}
                    continue
                if key == "pool":
                    pool_date = lane_date or None
                try:
                    # 落库阶段同样逐通道隔离（评审 P1-1）：Mongo/库工厂/脏 payload 异常
                    # 只算本通道失败，不连带后续通道全部不落库
                    results[key] = await asyncio.to_thread(fn, self._database_factory(), payload)
                except Exception as error:
                    results[key] = {"ok": False, "reason": f"archive_failed:{error}"}
            # 2013 题材库热度 / 2203 涨停原因语料（2026-11-10 裁决）：改由 collector
            # 推送即落库（单写者），本服务不再轮询这两通道；本轮结果仅标注迁移态。
            results["reason"] = {"ok": True, "note": "moved_to_collector_push_time"}
            results["theme"] = {"ok": True, "note": "moved_to_collector_push_time"}
            # 板块身位通道（2026-11-10 用户需求「当日实时身位 + 落库」，龙头三合一口径）：
            # 依赖当日池档（streak/断板候选回溯），故在 pool 通道归档成功后执行；
            # TDX 日线取数在进程内缓存（首拉冻结，与三合一链同哲学），同步计算走 to_thread。
            try:
                if pool_date:
                    from backend.services.kpl_lead_service import compute_and_archive_lead
                    results["lead"] = await asyncio.to_thread(
                        compute_and_archive_lead, self._database_factory(), pool_date)
                else:
                    results["lead"] = {"ok": False, "reason": "no_pool_date"}
            except Exception as error:
                results["lead"] = {"ok": False, "reason": f"archive_failed:{error}"}
            # 涨停基因语料（2026-11-08，题材龙头语料投喂 jev）：HTTP 单股逐发（协议层
            # _post_form 全局 ≥2s 限频），每轮限量 gene_limit 只，缺失优先、收盘后刷终值。
            # 日期来源：①当轮涨停池快照交易日 ②快照缺失（采集器未运行/周末重启）时回退
            # 库内最近含成员的日档 —— 基因端点走 apphq HTTP 不依赖采集器，仅需日档日期；
            # 两者都无才 skip（不猜日期、不错挂）。
            gene_date, gene_date_source = pool_date, "snapshot"
            try:
                db = self._database_factory()
                if not gene_date:
                    gene_date = await asyncio.to_thread(latest_archived_pool_day, db)
                    gene_date_source = "local_archive" if gene_date else "none"
                if not gene_date:
                    results["gene"] = {"ok": False, "reason": "no_pool_date"}
                else:
                    plan = await asyncio.to_thread(pick_gene_targets, db, gene_date,
                                                   limit=self._gene_limit)
                    genes = [await asyncio.to_thread(self._gene_fetcher, sid)
                             for sid in (plan.get("targets") or [])]
                    results["gene"] = await asyncio.to_thread(
                        archive_gene_corpus, db, {"date": gene_date, "genes": genes})
                    results["gene"]["date_source"] = gene_date_source
                    if plan.get("ok") is False:
                        results["gene"]["plan_reason"] = plan.get("reason")
            except Exception as error:
                results["gene"] = {"ok": False, "reason": f"archive_failed:{error}"}
            # 公告计数语料（2026-11-08 题材龙头语料第 3 项）：与 gene 块同款日期回退与
            # 每轮限量懒取；公告标题/正文不进叙事，只出计数与上游数据日期。
            try:
                notice_date, notice_date_source = pool_date, "snapshot"
                db = self._database_factory()
                if not notice_date:
                    notice_date = await asyncio.to_thread(latest_archived_pool_day, db)
                    notice_date_source = "local_archive" if notice_date else "none"
                if not notice_date:
                    results["notice"] = {"ok": False, "reason": "no_pool_date"}
                else:
                    plan = await asyncio.to_thread(pick_notice_targets, db, notice_date,
                                                   limit=self._notice_limit)
                    notices = [await asyncio.to_thread(self._notice_fetcher, sid)
                               for sid in (plan.get("targets") or [])]
                    results["notice"] = await asyncio.to_thread(
                        archive_notice_corpus, db, {"date": notice_date, "notices": notices})
                    results["notice"]["date_source"] = notice_date_source
                    if plan.get("ok") is False:
                        results["notice"]["plan_reason"] = plan.get("reason")
            except Exception as error:
                results["notice"] = {"ok": False, "reason": f"archive_failed:{error}"}
        self._last_result = results
        self._last_error = None if all(r.get("ok") for r in results.values()) \
            else ";".join(f"{k}:{r.get('reason')}" for k, r in results.items() if not r.get("ok"))


_daban_pool_archiver: Optional[DabanPoolArchiver] = None


def get_daban_pool_archiver() -> DabanPoolArchiver:
    global _daban_pool_archiver
    if _daban_pool_archiver is None:
        _daban_pool_archiver = DabanPoolArchiver()
    return _daban_pool_archiver


async def close_daban_pool_archiver() -> None:
    global _daban_pool_archiver
    if _daban_pool_archiver is not None:
        await _daban_pool_archiver.stop()
        _daban_pool_archiver = None
