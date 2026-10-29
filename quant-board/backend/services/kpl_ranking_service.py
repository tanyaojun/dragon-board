# -*- coding: utf-8 -*-
"""KPL 精选板块 HTTP 直连数据层（层1 板块强度排行 + 层3 成分股），供历史回看读口使用。

端点合同（2026-10-25 实测打通，证据 data/backups/kpl-corpus-probe-20261025/，
合同文档 docs/hotlist-jev/socket-push-handoff-20261026.md §五）：

- 层1 排行：POST ``apphwhq.longhuvip.com/w1/api/index.php``（历史 ``apphis`` 同构），
  ``a=RealRankingInfo&c=ZhiShuRanking&ZSType=7``，实时 ``Type=2`` / 按日查史
  ``Type=1&Date=YYYY-MM-DD``（实测 ≥2.4 年）；POST + Token=0/UserID=0 免凭据，UA=``ad``；
  ``st`` 最大 80，``Index`` 分页（每日约 240 板块 = 3 发）。
- 层3 成分股：POST ``apphis.longhuvip.com/w1/api/index.php``，
  ``a=ZhiShuStockList_W8&c=ZhiShuRanking&old=1&Date=…&PlateID=801xxx&Type=6&Order=1``
  + 现役 KPL 凭据（``mapping_refresh.KPL_APP_BASE_PARAMS`` 公共出口，禁另拷；
  零凭据返空）；UA=``Dalvik/2.1.0 (Linux; U; Android 9; …)``。

字段语义：排行 19 列与成分股 70 列仅部分有权威释义（Gitee mikasama/add_system），
解析器只映射已对齐字段，未对齐的列原样保留在 ``raw``（fail-visible：不伪装、不丢弃）；
带「推断」注释的字段待与 KPL App 同屏核对（kpl-socket README §四 同款纪律）。

纪律：单发间隔 ≥2s（handoff §六，禁连发）；30s TTL 缓存兜页面轮询；
pytest 全 mock HTTP，不发真实请求。
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

REQUEST_TIMEOUT_SECONDS = 15
_MIN_INTERVAL_SECONDS = 2.0  # 单发间隔纪律（禁连发）
_CACHE_TTL_SECONDS = 30.0
_RANKING_PAGE_SIZE = 80
_RANKING_MAX_PAGES = 5  # 240 板块 = 3 发；上限 5 防失控翻页
_STOCKS_MAX_PAGE_SIZE = 200  # 单页上限护栏（前端一批 100；2026-10-27 实测 st 无 80 上限）

_HOST_REALTIME = "https://apphwhq.longhuvip.com/w1/api/index.php"
_HOST_HISTORY = "https://apphis.longhuvip.com/w1/api/index.php"
_UA_RANKING = "ad"
_UA_STOCKS = "Dalvik/2.1.0 (Linux; U; Android 9; HPB-AN00 Build/PQ3A.190605.003)"

_lock = threading.Lock()
_last_request_at = 0.0
_cache: Dict[str, tuple] = {}  # key -> (expires_at, payload)


class KplRankingError(RuntimeError):
    """结构化业务错误：errcode≠0 / 凭据返空 / 上游不可达（fail-visible）。"""

    def __init__(self, reason: str, **detail: Any):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail

    def to_payload(self) -> Dict[str, Any]:
        return {"ok": False, "degraded": True, "reason": self.reason, **self.detail}


# ── HTTP 层（测试 mock 点） ─────────────────────────────────────────────────

def _post_form(url: str, params: Dict[str, Any], ua: str) -> dict:
    """POST form + JSON 解析；HTTP 层异常抛 KplRankingError（结构化）。"""
    global _last_request_at
    with _lock:
        wait = _MIN_INTERVAL_SECONDS - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()
    body = urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"User-Agent": ua,
                 "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise KplRankingError(f"upstream_http_{exc.code}", url=url) from exc
    except Exception as exc:
        raise KplRankingError(f"upstream_unreachable: {type(exc).__name__}: {exc}", url=url) from exc


def _cached(key: str) -> Optional[Dict[str, Any]]:
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _store(key: str, payload: Dict[str, Any]) -> None:
    _cache[key] = (time.time() + _CACHE_TTL_SECONDS, payload)


# ── 解析（纯函数） ──────────────────────────────────────────────────────────

def parse_ranking_row(row: List[Any]) -> Dict[str, Any]:
    """排行行 19 列 → 已对齐字段 + raw 原样保留。

    已对齐（Gitee 释义 + 2026-10-25 样本核对）：[0]板块代码 [1]名称 [2]强度
    [3]涨幅% [5]成交额 [8]主力净额(推断,样本为负值) [9]量比(推断)。
    """
    def _num(v: Any) -> Any:
        return v

    return {
        "plate_id": str(row[0]) if len(row) > 0 else "",
        "name": str(row[1]) if len(row) > 1 else "",
        "strength": _num(row[2]) if len(row) > 2 else None,
        "pct": _num(row[3]) if len(row) > 3 else None,
        "amount": _num(row[5]) if len(row) > 5 else None,
        "main_net": _num(row[8]) if len(row) > 8 else None,   # 推断
        "volume_ratio": _num(row[9]) if len(row) > 9 else None,  # 推断
        "raw": row,
    }


def parse_stock_row(row: List[Any]) -> Dict[str, Any]:
    """成分股行 70 列 → 已对齐字段 + raw 原样保留（未对齐列不猜语义）。

    已对齐（2026-10-25 样本 kpl_plate_stocks.json 核对）：
    [0]代码 [1]名称 [4]概念 [5]现价 [6]涨幅% [7]成交额 [8]换手%
    [11]主力买(推断) [12]主力卖(推断) [13]主力净(推断, 11-12 自洽)
    [21]量比(推断，样本 1.14045/4.54973 量级自洽) [23]连板状态（"5天3板"/"6连板"）
    [24]地位（"龙一"~"龙N"）。
    封单额 / 涨停时间列未对齐，不在映射内（前端显示 "--"，不猜数）。
    """
    return {
        "code": str(row[0]) if len(row) > 0 else "",
        "name": str(row[1]) if len(row) > 1 else "",
        "concept": str(row[4]) if len(row) > 4 else "",
        "price": row[5] if len(row) > 5 else None,
        "pct": row[6] if len(row) > 6 else None,
        "amount": row[7] if len(row) > 7 else None,
        "turnover": row[8] if len(row) > 8 else None,
        "main_buy": row[11] if len(row) > 11 else None,   # 推断
        "main_sell": row[12] if len(row) > 12 else None,  # 推断
        "main_net": row[13] if len(row) > 13 else None,   # 推断
        "volume_ratio": row[21] if len(row) > 21 else None,  # 推断（样本 1.14045/4.54973 量级自洽）
        "board_status": str(row[23]) if len(row) > 23 else "",
        "rank_title": str(row[24]) if len(row) > 24 else "",
        "raw": row,
    }


def _check_errcode(data: dict) -> None:
    """KPL 业务错误：errcode≠0 → 结构化异常（照抄韭研 errCode=9 教训：不信 msg 只看码）。"""
    code = data.get("errcode")
    if code in (0, "0", None):
        return
    raise KplRankingError("kpl_errcode", errorCode=str(code),
                          error=str(data.get("errmsg") or "")[:120])


# ── 公共读口 ────────────────────────────────────────────────────────────────

def _parse_sons(pages: List[dict]) -> Dict[str, Any]:
    """排行响应的 list_son/list_soninfo → 二级板块读数（2026-10-28 反汇编 APP 显示逻辑实测）。

    App 精选板块的子板块行不是客户端按强度过滤，而是服务端直接下发：
    ``list_son``=获得子板块行的父板块 id 列表、``list_soninfo``=子板块行（同 19 列格式），
    实测两者等长按位配对（2026-10-28 10:35 样本：list_son=[801159]、list_soninfo=[智元机器人]，
    与 App 同屏一致；同期排行宇宙内 40+ 一级板块有树子板块但仅此 1 个拿到 son）。
    配对规则：等长 → 按位 zip 成 {parent_id: [子板块行]}；不等长 → 不猜配对，
    结构化透出 sons_unpaired（fail-visible，不伪装成「无子板块」）。
    """
    parents: List[str] = []
    rows: List[List[Any]] = []
    for data in pages:
        for p in (data.get("list_son") or []):
            sp = str(p)
            # 不去重：合同=等长按位配对，去重会破坏与 list_soninfo 的对位（多父/重复场景待真实样本验证）
            if sp:
                parents.append(sp)
        rows.extend(r for r in (data.get("list_soninfo") or [])
                    # 同主列表同款垃圾行过滤（plate_id 非 6 位数字/名称空）
                    if isinstance(r, list) and len(r) >= 2
                    and len(str(r[0] or "")) == 6 and str(r[0] or "").isdigit()
                    and str(r[1] or "").strip())
    if not parents and not rows:
        return {"sons": {}}
    if len(parents) != len(rows):
        return {"sons": {},
                "sons_unpaired": {"parents": parents, "row_count": len(rows),
                                  "note": "list_son 与 list_soninfo 长度不等，放弃按位配对"}}
    sons: Dict[str, List[Dict[str, Any]]] = {}
    for pid, row in zip(parents, rows):
        sons.setdefault(pid, []).append(parse_ranking_row(row))
    return {"sons": sons}


def get_sector_ranking(date: str) -> Dict[str, Any]:
    """按日取板块强度排行全量（Type=1+Date 分页取齐）+ 二级板块（list_son）。

    返回 {"ok": True, "date": ..., "items": [...], "sons": {parent_id: [子板块行]}}；
    上游/业务错误抛 KplRankingError。"""
    cached = _cached(f"ranking:{date}")
    if cached is not None:
        return cached
    items: List[Dict[str, Any]] = []
    pages: List[dict] = []
    for page in range(_RANKING_MAX_PAGES):
        data = _post_form(
            # 2026-10-27 实测：排行（含 Type=1+Date 查史）走 apphwhq；apphis 同参数返空
            # （survey §9.2「apphis 亦可」当日复测不成立），层3 成分股仍走 apphis。
            _HOST_REALTIME,
            {"Index": page * _RANKING_PAGE_SIZE, "Order": 1, "PhoneOSNew": 2,
             "Type": 1, "Date": date, "VerSion": "5.13.0.1", "ZSType": 7,
             "a": "RealRankingInfo", "apiv": "w35", "c": "ZhiShuRanking",
             "st": _RANKING_PAGE_SIZE, "Token": "0", "UserID": "0"},
            _UA_RANKING)
        _check_errcode(data)
        pages.append(data)
        rows = data.get("list") or []
        # 盘前/未生成时上游会返回「全零行」（plate_id="0"、名称空）——过滤，
        # 否则引导把垃圾行当有效数据、真正有数的旧日期被跳过（2026-10-27 实测）
        rows = [r for r in rows
                if isinstance(r, list) and r and str(r[0] or "").isdigit()
                and len(str(r[0])) == 6 and str(r[1] or "").strip()]
        items.extend(parse_ranking_row(r) for r in rows)
        if len(rows) < _RANKING_PAGE_SIZE:
            break
    payload = {"ok": True, "date": date, "items": items, **_parse_sons(pages)}
    if items:
        _store(f"ranking:{date}", payload)  # 空 items 不缓存：异常空态不得被 TTL 钉住
    return payload


def get_sector_stocks(plate_id: str, date: str, page: int = 0, page_size: int = 100) -> Dict[str, Any]:
    """按日取板块成分股（层3 ZhiShuStockList_W8，现役凭据走公共出口）。

    真·按页取数（2026-10-27 用户二次裁决，推翻「整单拉取+切片」方案）：
    一页 = 一次上游请求（``st=page_size&Index=page*page_size``，实测 st 无 80 上限、
    Index 按行偏移续接不重叠）。切板块/翻页各只发一枪（30s TTL 按 (plate,date,page)
    缓存），首屏不再等全量名单。total 不可知（全量需扫完），前端用 has_more 翻页。
    """
    page = max(page, 0)
    page_size = max(1, min(page_size, _STOCKS_MAX_PAGE_SIZE))
    key = f"stocks:{plate_id}:{date}:{page}:{page_size}"
    cached = _cached(key)
    if cached is not None:
        return cached
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    data = _post_form(
        _HOST_HISTORY,
        {"Type": 6, "Order": 1, "Index": page * page_size,
         "st": page_size, "PlateID": plate_id, "Date": date,
         "a": "ZhiShuStockList_W8", "c": "ZhiShuRanking", "PhoneOSNew": 2,
         "old": 1, "apiv": "w21", "VerSion": "5.13.0.0", **creds},
        _UA_STOCKS)
    try:
        _check_errcode(data)
    except KplRankingError as exc:
        if str((exc.detail or {}).get("errorCode")) == "1020":
            # 2026-10-29 判别探针（data/backups/kpl-corpus-probe-20261029-l3l2/，
            # probe1~probe3）：历史日（10-27/10-28）同参数/凭据/host 70s 间隔连发全部
            # OK；版本矩阵（5.23.0.4/w44、6.3.20.2/w48）、换 host、白名单化简均不影响
            # ——1020 非参数错亦非限频，主因=当日盘前/数据未生成（与排行端点盘前
            # 「全零行」同源现象，仅表象不同）。结构化为 date_state 供消费方区分重试
            # 策略，不伪装成空成分股、不误报凭据失效。
            raise KplRankingError(
                "upstream_1020_date_state",
                plate_id=plate_id, date=date,
                note="1020 多义（参数/日期未生成/限频）；2026-10-29 判别实证历史日可用，"
                     "当日盘前主因=数据未生成，盘后重试") from exc
        raise
    rows = data.get("list") or []
    if not rows and page == 0:
        # 现役凭据失效时该端点返空列表而非 errcode（handoff §一 实测）——
        # 首页即空视为结构化错误，不伪装成「无成分股」（前端据此逐日回退日期）
        raise KplRankingError("empty_list_check_credentials",
                              plate_id=plate_id, date=date)
    items = [parse_stock_row(r) for r in rows if isinstance(r, list) and r]
    payload = {"ok": True, "date": date, "plate_id": plate_id,
               "page": page, "page_size": page_size,
               "has_more": len(items) >= page_size,
               "items": items}
    _store(key, payload)
    return payload


# 历史行统一列位 → 语义名（2026-10-27 逆向自 qg.q1 历史行解析器 × assets/PatternDynamicQuota
# 列目录：历史 HTTP 行与 socket 2103 的 protobuf quotas 排布不同——row[0]=代码、row[1]=名称、
# row[2]=labelType(int)、row[3]=板块标签，row[i]（i≥4）直接按统一数组位（arrayPosition）取值，
# 与 App 渲染层 PatternTitleVisibleArrayPosition 列序同源。列位 10 无目录名不映射（fail-visible）。
_DABAN_HIST_POS_NAMES: Dict[int, str] = {
    4: "pct",               # 涨幅（App 竞价页签改叫实时涨幅）
    5: "speed",             # 涨速
    6: "zt_time",           # 涨停时间
    7: "open_time",         # 开板时间
    8: "zt_tur",            # 封单
    9: "state",             # 状态（连板状态：4连板/昨日首板…）
    11: "plate",            # 板块
    12: "main_net",         # 主力净额
    13: "amount",           # 成交额
    14: "real_turnover",    # 实际换手
    15: "real_float",       # 实际流通
    16: "zt_reason",        # 涨停原因
    17: "price",            # 价格
    18: "zt_buy_amount",    # 涨停委买额
    19: "bidding_pct",      # 竞价涨幅
    20: "bidding_net",      # 竞价净额
    21: "bidding_turnover", # 竞价换手
    22: "bidding_amount",   # 竞价成交额
    23: "max_zt_tur",       # 最大封单
    25: "last_zt_time",     # 最后涨停时间
    28: "amplitude",        # 振幅
    29: "turnover_rate",    # 换手率
    30: "volume_ratio",     # 量比
    31: "total_mv",         # 总市值
    32: "float_mv",         # 流通市值
}


def _maybe_num(v: Any) -> Any:
    """可转数字则转（排序/聚合用），否则原样（App 侧常带「亿/万」单位）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return f if math.isfinite(f) else v


_HISBAN_NOTE = ("上游该端点为严格白名单参数（仅 Day+全局五件套+凭据），不认页签参数——"
                   "返回默认集合，页签过滤待 MITM 抓包对照")


def _parse_daban_history_row(row: List[Any]) -> Dict[str, Any]:
    """历史收盘帧行 → 命名字段（列语义按 _DABAN_HIST_POS_NAMES，未对齐位原样保留 raw）。

    注意：行内列语义来自反编译推断（qg.q1 × PatternDynamicQuota），上游 1020 期间
    拿不到真实样本逐列核对——接入消费前须与 App 历史页同屏核对（kpl-socket README 纪律）。
    """
    item: Dict[str, Any] = {
        "stock_id": str(row[0]) if len(row) > 0 else "",
        "name": str(row[1]) if len(row) > 1 else "",
        "label_type": row[2] if len(row) > 2 else None,
        "stock_tag": str(row[3]) if len(row) > 3 else "",
    }
    for i, v in enumerate(row):
        name = _DABAN_HIST_POS_NAMES.get(i)
        if name is not None:
            item[name] = _maybe_num(v) if isinstance(v, str) else v
    item["raw"] = row
    return item


def get_daban_list_history(date: str, pid_type: int = 8) -> Dict[str, Any]:
    """按日取打板个股列表历史收盘帧（App 市场情绪·股票列表的日期回看读口）。

    合同（2026-10-27 逆向自 BiddingZTlQuotaPresenter.a0 → ox0.L2 → j00.P1 → qg.q1；
    2026-10-28 实测修订）：POST apphis ``a=HisDaBanList&c=HisHomeDingPan&Day=date`` +
    全局五件套（DeviceID/apiv/PhoneOSNew/VerSion/Red）+ 凭据。**实测该端点为严格
    白名单参数——Day 之外多传任何键（PidType/Type/Order/Is_st/Index/st/Filter 家族
    全部）一律 1020 参数出错；裸参数实测返回真数据（行格式=统一数组位，见
    _parse_daban_history_row）**。因此 pid_type 在此不透传上游（仅作路由/前端语义），
    返回的是上游默认集合；页签过滤参数待 MITM 抓包对照真实 App 请求后补。
    上游限频（约分钟级 1 发，超频 1020/空列表抖动），30s TTL 缓存按日共享（三页签
    同日共用一份，30s 内最多 1 发上游）。无分页（Index/st 不被接受）。
    空列表=上游限频窗口/数据未生成的瞬时态（errcode=0）：抛结构化错误让前端横幅透出
    （fail-visible，不伪装成「无数据」）；历史模式为单发不轮询，重拉需切换日期/重进页签。
    """
    key = f"hisban:{date}"
    cached = _cached(key)
    if cached is not None:
        return {"ok": True, "date": date, "pid_type": pid_type,
                "items": cached["items"], "day": cached["day"],
                "note": _HISBAN_NOTE}
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    data = _post_form(
        _HOST_HISTORY,
        {"a": "HisDaBanList", "c": "HisHomeDingPan", "Day": date,
         "apiv": "w48", "VerSion": "6.3.20.2", "PhoneOSNew": 1, "Red": 0, **creds},
        _UA_STOCKS)
    _check_errcode(data)
    rows = data.get("list") or []
    if not rows:
        # 空列表不伪装（fail-visible）：异常空态不进缓存；历史模式单发不轮询，
        # 重拉需切换日期/重进页签（无自动重试）
        raise KplRankingError("upstream_empty_list", pid_type=pid_type, date=date,
                              note="上游返回空列表（限频窗口内瞬时态），重拉需切换日期/重进页签")
    entry = {"items": [_parse_daban_history_row(r) for r in rows if isinstance(r, list) and r],
             "day": data.get("day", date)}
    _store(key, entry)
    return {"ok": True, "date": date, "pid_type": pid_type,
            "items": entry["items"], "day": entry["day"],
            "note": _HISBAN_NOTE}


def get_daban_head_info(date: str) -> Dict[str, Any]:
    """按日取打板头统计（App 市场情绪页头的今/昨涨停·封板率·跌停绝对值来源）。

    合同（2026-10-27 逆向自 ox0：API_HISTORY + a=HisDaBanHeadInfo&c=HisHomeDingPan，
    Day=date）。响应结构已按 2026-10-23 真实样本核对：raw.nums.{tZhangTing,lZhangTing,
    tDieTing,lDieTing(int)、tFengBan,lFengBan(float 封板率%)}，t=查询日、l=前一交易日。
    上游限频（约分钟级 1 发，超频返 1020），30s TTL 缓存兜页面轮询。
    """
    key = f"hishead:{date}"
    cached = _cached(key)
    if cached is not None:
        return cached
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    data = _post_form(
        _HOST_HISTORY,
        {"a": "HisDaBanHeadInfo", "c": "HisHomeDingPan", "Day": date,
         "apiv": "w48", "VerSion": "6.3.20.2", "PhoneOSNew": 1, "Red": 0, **creds},
        _UA_STOCKS)
    _check_errcode(data)
    payload = {"ok": True, "date": date, "raw": data}
    _store(key, payload)
    return payload


# ── 市场雷达/直播流（2026-10-28）：a=Radar&c=HomeDingPan（apiv=w38，仅实时） ──
# 反汇编来源：apifox 社区接口文档（239636155）+ 2026-10-28 直连实测（apphwhq 域，
# 无 Token/UserID 亦可）；响应 {list:[...], num, date, time, ttag, errcode}，
# list 项字段：time(epoch 秒)/status/stock_name/stockid/plate_type/status_color/
# zf/content/content2/LBstatus。上游每页上限约 15 条（st=60 仍返 15），Index 翻页。
# 直播页顶部长篇官方解说未见于该接口，另源未定位（不猜数）；status_color 实测仅见 1。
_RADAR_TTL_SECONDS = 5.0   # 直播流要求新鲜：5s 兜前端 8s 轮询，不共用 30s 缓存
_RADAR_PAGE_MAX = 60


def parse_radar_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """单条雷达事件归一化：无 stockid 或时间非法返回 None（由调用方计入 skipped）。"""
    try:
        ts = int(float(raw.get("time") or 0))
    except (TypeError, ValueError):
        return None
    code = str(raw.get("stockid") or "").strip()
    if not code or ts <= 0:
        return None
    status = str(raw.get("status") or "").strip()
    lt = time.localtime(ts)
    return {
        "id": f"{ts}:{code}:{status}",          # 会话内去重键（同秒同股同状态=同事件）
        "ts": ts,
        "time": time.strftime("%H:%M:%S", lt),
        "status": status,
        "code": code,
        "name": str(raw.get("stock_name") or "").strip(),
        "lb_status": str(raw.get("LBstatus") or "").strip(),
        # status_color：实测仅见 1（涨停系红）；其余值语义未知，透出原始值不猜色
        "color": _maybe_num(raw.get("status_color")),
        "zf": _maybe_num(raw.get("zf")) if str(raw.get("zf") or "").strip() else None,
        "content": str(raw.get("content") or "").strip(),
        "content2": str(raw.get("content2") or "").strip(),
        "plate_type": _maybe_num(raw.get("plate_type")),
    }


def get_market_radar(st: int = 60) -> Dict[str, Any]:
    """市场雷达/直播流（层1 Radar，仅实时；历史口径未验证不提供）。

    返回 {"ok": True, "date": ..., "items": [...], "skipped": n}；items 按 ts 降序。
    5s TTL 缓存；空 items 不缓存（异常空态不得被 TTL 钉住，fail-visible）。
    上游/业务错误抛 KplRankingError。
    """
    st = max(1, min(int(st), _RADAR_PAGE_MAX))
    key = f"radar:{st}"
    cached = _cached(key)
    if cached is not None:
        return cached
    data = _post_form(
        _HOST_REALTIME,
        {"a": "Radar", "c": "HomeDingPan", "apiv": "w38", "Index": 0,
         "st": st, "PhoneOSNew": 1, "VerSion": "5.16.0.5",
         "DeviceID": KPL_APP_BASE_PARAMS["DeviceID"]},
        _UA_RANKING)
    _check_errcode(data)
    rows_raw = data.get("list") or []
    items = [r for r in (parse_radar_row(x) for x in rows_raw if isinstance(x, dict)) if r]
    items.sort(key=lambda r: r["ts"], reverse=True)
    payload = {"ok": True, "date": str(data.get("date") or ""),
               "items": items, "skipped": len(rows_raw) - len(items)}
    if items:
        _cache[key] = (time.time() + _RADAR_TTL_SECONDS, payload)
    return payload


# ── 直播解说流（2026-10-28）：a=ZhiBoContent&c=ConceptionPoint（apphwhq，需 App 凭据） ──
# 反汇编路径：网页版 www.kaipanla.com/page/szlive.html + js/part/szlive.js（实时走
# pchq 域需登录态 1016/1001）→ 实测 apphwhq.longhuvip.com 同参数 + KPL_APP_BASE_PARAMS
# 凭据可用，返回与 App 直播页逐字一致（2026-10-28 样本 .tmp_review/zhibo_raw.json）。
# 响应 {List:[...], Notice, Status, Time, date, ttag, errcode}；List 项：ID/UID/Time(epoch)/
# Comment/Type/PlateCode/PlateName/PlateJE/PlateZDF/Stock=[[code,name,pct],...]/DisStock/
# ThemeInfo/Interpretation/IsChart/Image/UserName。内容=AI 大模型根据行情自动生成（App 同款标注）。
# 历史变体 c=HisConceptionPoint+Date（网页版走 pchis 域）未验证——v1 仅实时，不猜数。
# 凭据仅进请求参数（mapping_refresh 公共出口），不入库不落日志（红线 §1.2.3）。
_LIVE_TTL_SECONDS = 15.0   # 解说频率约分钟级，15s 兑前端轮询
_LIVE_PAGE_MAX = 60


def parse_live_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """单条直播解说归一化：无 Time/Comment 返回 None（调用方计入 skipped）。"""
    try:
        ts = int(float(raw.get("Time") or 0))
    except (TypeError, ValueError):
        return None
    comment = str(raw.get("Comment") or "").strip()
    if ts <= 0 or not comment:
        return None
    stocks = []
    for s in (raw.get("Stock") or []):
        if isinstance(s, (list, tuple)) and len(s) >= 2 and str(s[0] or "").strip():
            stocks.append({"code": str(s[0]).strip(), "name": str(s[1]).strip(),
                           "pct": _maybe_num(s[2]) if len(s) > 2 else None})
    return {
        "id": f"zb:{raw.get('ID') or ts}",
        "ts": ts,
        "time": time.strftime("%H:%M", time.localtime(ts)),
        "comment": comment,
        "type": _maybe_num(raw.get("Type")),
        "plate_code": str(raw.get("PlateCode") or "").strip(),
        "plate_name": str(raw.get("PlateName") or "").strip(),
        "plate_pct": _maybe_num(raw.get("PlateZDF")) if str(raw.get("PlateZDF") or "").strip() else None,
        "stocks": stocks,
        "user": str(raw.get("UserName") or "").strip(),
    }


def get_live_commentary(st: int = 30) -> Dict[str, Any]:
    """直播解说流（App 直播页同源；仅实时，历史变体未验证不提供）。

    返回 {"ok": True, "date": ..., "notice": ..., "items": [...], "skipped": n}；
    items 按 ts 降序。15s TTL 缓存；空 items 不缓存（fail-visible）。
    上游/业务错误抛 KplRankingError；凭据仅走请求参数，不落库不落日志。
    """
    st = max(1, min(int(st), _LIVE_PAGE_MAX))
    key = f"zhibo:{st}"
    cached = _cached(key)
    if cached is not None:
        return cached
    data = _post_form(
        _HOST_REALTIME,
        {"a": "ZhiBoContent", "c": "ConceptionPoint", "Index": 0, "st": st,
         "VerSion": "5.23.0.4", "PhoneOSNew": 1, "apiv": "w44",
         **{k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "Token", "DeviceID")}},
        _UA_STOCKS)
    _check_errcode(data)
    rows_raw = data.get("List") or []
    items = [r for r in (parse_live_row(x) for x in rows_raw if isinstance(x, dict)) if r]
    items.sort(key=lambda r: r["ts"], reverse=True)
    payload = {"ok": True, "date": str(data.get("date") or ""),
               "notice": str(data.get("Notice") or ""),
               "items": items, "skipped": len(rows_raw) - len(items)}
    if items:
        _cache[key] = (time.time() + _LIVE_TTL_SECONDS, payload)
    return payload


# ── 板块日度历史（层2，2026-10-28 接入：题材龙头链板块序列行原料，P1-1） ──
# 实测（2026-10-28，801159 机器人概念 Count=303 全史）：行=Date/ZTNum(当日板块涨停数)/
# QD(强度)/LZInfo(龙头梯队串「code,名,N连板;…」KPL 预计算)/LZInfo_ZF/IsBoom/Title(催化)。
# 参数对版本敏感：VerSion 5.13.0.0 组合返空，5.23.0.4+apiv w44 实测有数——上游漂移频繁，
# 失败抛 KplRankingError 由调用方 fail-visible。历史不变 → 12h TTL。
_PLATE_HIST_TTL_SECONDS = 12 * 3600.0


# ── 直播个股 meta 索引（2026-10-29：直播表 地位/换手/连板/概念 四列补齐） ──
# 解说（ZhiBoContent.Stock=[code,name,pct]）与雷达（Radar：stockid/name/status/LBstatus）
# 消息流上游**不带** 地位/换手/概念，解说也不带连板——此前前端右栏个股表这四列硬编码 "--"。
# 唯一 KPL 口径来源=板块成分股接口（ZhiShuStockList_W8，parse_stock_row [8]换手 [23]连板
# [24]地位 [4]概念）。本索引按日惰性后台构建：排行（RealRankingInfo，30s TTL 共享缓存）→
# 逐板块翻页扫成分股（每板块间节流）→ code→meta。命中即查表；不在任何板块宇宙的个股
# 如实 missed（前端显示 "--"，不伪装）；building 期间返回已构建部分（fail-visible 渐进可用）。
# 盘前/未生成：排行全零行被过滤后 items 空——记 error 态不伪装成 done 空 index
# （2026-10-29 层3 判别探针同源结论），盘中数据生成后下次调用自动重建。
_STOCKS_META_TTL_SECONDS = 1800.0     # 地位/概念盘中缓变；连板由雷达实时 lb_status 优先，容忍 30 分钟粒度
_STOCKS_META_RETRY_SECONDS = 60.0     # error 态重建最小间隔（上游不可用/盘前时防 sig 变化放大为无上限重试）
_STOCKS_META_KEEP_DATES = 5           # 进程内保留最近 N 个日期，超出淘汰非 building 项（防跨交易日累积）
_STOCKS_META_PLATE_SLEEP = 0.0        # 增量节流由 _MIN_INTERVAL_SECONDS=2s 全局纪律兜底（禁连发），板块间不另加睡
_stocks_meta_lock = threading.Lock()
_stocks_meta_cache: Dict[str, Dict[str, Any]] = {}


def _build_stocks_meta(date: str) -> None:
    """后台线程构建（get_live_stocks_meta 拉起）：排行 → 逐板块成分股 → code→meta。

    单板块失败不中断（failed_plates 计数透出，fail-visible）；排行失败 → error 态。
    增量写入：每板块完成即持锁合并进索引——全局 2s/发纪律下全宇宙 ~80 发≈160s，
    前端轮询 10s 内即见强度最高板块的首批 meta，不等全量构建完成。
    """
    with _stocks_meta_lock:
        entry = _stocks_meta_cache.setdefault(
            date, {"state": "building", "index": {}, "failed_plates": [],
                   "built_at": time.time(), "error": None})
        index: Dict[str, Dict[str, Any]] = entry.setdefault("index", {})
        failed: List[str] = entry.setdefault("failed_plates", [])
    try:
        ranking = get_sector_ranking(date)
        plates = [it for it in (ranking.get("items") or []) if it.get("plate_id")]
        if not plates:
            # 盘前/未生成：排行全零行被过滤后为空——不得伪装成「done 空 index」
            # （2026-10-29 层3 判别探针同源结论），error 态让下次调用自动重建
            raise KplRankingError("ranking_empty（盘前/数据未生成，fail-visible）")
        for it in plates:
            pid = str(it["plate_id"])
            page = 0
            plate_hits: Dict[str, Dict[str, Any]] = {}
            try:
                while True:
                    resp = get_sector_stocks(pid, date, page=page)
                    for s in resp.get("items") or []:
                        code = str(s.get("code") or "")
                        if not code or code in index or code in plate_hits:
                            continue      # 强度高的排行板块优先（遍历序=强度降序）
                        plate_hits[code] = {
                            "rank_title": s.get("rank_title") or "",
                            "turnover": s.get("turnover"),
                            "board_status": s.get("board_status") or "",
                            "concept": s.get("concept") or "",
                            "plate_id": pid,
                        }
                    if not resp.get("has_more"):
                        break
                    page += 1
            except KplRankingError:
                failed.append(pid)
            if plate_hits:                # 增量合并：一个板块完成立即可被读口命中
                with _stocks_meta_lock:
                    for c, m in plate_hits.items():
                        index.setdefault(c, m)
    except KplRankingError as exc:
        with _stocks_meta_lock:
            entry.update({"state": "error", "built_at": time.time(),
                          "last_attempt_at": time.time(), "error": str(exc)})
        return
    except Exception as exc:               # 非业务异常兜底：不得让 entry 永远钉在 building
        with _stocks_meta_lock:
            entry.update({"state": "error", "built_at": time.time(),
                          "last_attempt_at": time.time(),
                          "error": f"build_crash: {type(exc).__name__}: {str(exc)[:120]}"})
        return
    with _stocks_meta_lock:
        entry.update({"state": "done", "built_at": time.time(),
                      "last_attempt_at": time.time(), "error": None})


def get_live_stocks_meta(codes: List[str], date: str) -> Dict[str, Any]:
    """直播个股表 meta（地位/换手/连板/概念，KPL 成分股口径）。

    索引未建/过期 → 起后台线程构建，立即返回 building=True + 已命中部分（前端
    轮询渐进渲染）；done → hits + missed（missed=不在任何 KPL 板块宇宙，如实透出）。
    零网络阻塞调用方（构建全程后台线程）。stale 旧索引在重建完成前继续可用。
    """
    uniq: List[str] = []
    for c in codes or []:
        c = str(c or "").strip()
        if c and c not in uniq:
            uniq.append(c)
    with _stocks_meta_lock:
        if len(_stocks_meta_cache) > _STOCKS_META_KEEP_DATES:   # 跨日淘汰（review P2-4）
            keep = sorted(
                (d for d, e in _stocks_meta_cache.items()
                 if e.get("state") != "building"),
                key=lambda d: (_stocks_meta_cache[d].get("built_at") or 0))
            for d in keep[:max(0, len(keep) - (_STOCKS_META_KEEP_DATES - 1))]:
                _stocks_meta_cache.pop(d, None)
    need_build = False
    with _stocks_meta_lock:
        entry = _stocks_meta_cache.get(date) or {}
        fresh = (time.time() - entry.get("built_at", 0)) < _STOCKS_META_TTL_SECONDS
        index = dict(entry.get("index") or {})
        state = entry.get("state")
        error_cooldown = (
            state == "error"
            and (time.time() - entry.get("last_attempt_at", 0)) < _STOCKS_META_RETRY_SECONDS)
        if state is None or (state == "done" and not fresh) or (
                state == "error" and not error_cooldown):
            _stocks_meta_cache[date] = {"state": "building", "index": index,
                                        "built_at": time.time(),
                                        "last_attempt_at": time.time()}
            entry = _stocks_meta_cache[date]
            need_build = True
        hits = {c: index[c] for c in uniq if c in index}
        building = entry.get("state") == "building"
        missed = [c for c in uniq if c not in index] if not building else []
        payload = {"ok": True, "date": date, "building": building,
                   "hits": hits, "missed": missed,
                   "failedPlates": entry.get("failed_plates") or [],
                   "indexSize": len(index),
                   "error": entry.get("error")}
    if need_build:
        # 线程必须在锁外 start：同步/重入执行下构建函数结尾要拿同一把非重入锁，
        # 锁内 start 会死锁（2026-10-29 测试死锁实录）；锁外 start 生产同样缩短持锁时间
        threading.Thread(target=_build_stocks_meta, args=(date,),
                         daemon=True, name=f"kpl-stocks-meta-{date}").start()
    return payload


def get_plate_daily_history(plate_id: str, limit: int = 60) -> Dict[str, Any]:
    """板块日度历史（层2 ZhiShuKLine/GetDayBaseFaceListZDEvnArt，单发全量窗口）。

    返回 {"ok": True, "plate_id": ..., "items": [{date, zt_num, qd, lz_info, lz_info_zf,
    is_boom, title}, ...]}（date 升序）；上游/业务错误抛 KplRankingError。LZInfo 原样
    保留（KPL 预计算梯队串，消费方交叉披露不替换自算口径——单一事实源红线）。
    缺口语义（2026-10-29 反查实证固化，原「待上游确认」结案）：ZTNum 仅记录有涨停家/
    爆发日，记录间缺口=上游缺记而非零涨停——反查 10-16 缺口日 HisDaBanList 实证
    机器人链 3 只涨停股在场而层2 无记录（data/backups/kpl-corpus-probe-20261029-l3l2/）。
    """
    limit = max(1, min(int(limit), 100))
    key = f"plthist:{plate_id}:{limit}"
    cached = _cached(key)
    if cached is not None:
        return cached
    data = _post_form(
        _HOST_HISTORY,
        {"a": "GetDayBaseFaceListZDEvnArt", "c": "ZhiShuKLine", "StockID": str(plate_id),
         "IsBoom": 0, "Index": 0, "st": limit,
         "VerSion": "5.23.0.4", "PhoneOSNew": 1, "apiv": "w44",
         **{k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}},
        _UA_STOCKS)
    _check_errcode(data)
    rows = data.get("List") or data.get("list") or []
    items = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("Date"):
            continue
        items.append({
            "date": str(r["Date"]),
            "zt_num": r.get("ZTNum") if isinstance(r.get("ZTNum"), (int, float)) else None,
            "qd": r.get("QD") if isinstance(r.get("QD"), (int, float)) else None,
            "lz_info": str(r.get("LZInfo") or ""),
            "lz_info_zf": r.get("LZInfo_ZF"),
            "is_boom": r.get("IsBoom"),
            "title": str(r.get("Title") or "")[:120],
        })
    items.sort(key=lambda x: x["date"])
    payload = {"ok": True, "plate_id": str(plate_id), "items": items, "count": len(items)}
    if items:
        _cache[key] = (time.time() + _PLATE_HIST_TTL_SECONDS, payload)
    return payload


# ── 竞昨比原料（2026-10-28）：昨日日K（昨收/昨量），腾讯 ifzq 逐股 ─────────────
# 背景：2103 竞价 quotas（28 位实测）不含竞价成交量与昨日成交量；竞昨比
# （竞价成交量/昨日成交量×100%）按如下口径派生：
#   竞价成交量(手) = 竞价成交额 / (竞价价×100)，竞价价 = 昨收×(1+竞价涨幅/100)
#   昨收用 qfq 前复权价=除权基准价（与 App 竞价涨幅分母同口径）；量列不复权。
#   昨日成交量 = date 前最近一根日K 量（手，腾讯/东财同单位，2026-10-28 双源核对）。
_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_BASIS_FETCH_TIMEOUT = 10.0
_BASIS_TTL_SECONDS = 12 * 3600.0     # date 未跨交易日则昨收/昨量不变，长 TTL
_BASIS_FAIL_RETRY_SECONDS = 600.0    # 单股失败 10 分钟后允许重试（新股/瞬时网络错）
_BASIS_MAX_CODES = 800
_BASIS_CONCURRENCY = 8
_basis_lock = threading.Lock()
_basis_cache: Dict[str, Dict[str, Any]] = {}   # date → {"map": {code: basis}, "failed": {code: ts}}


def _tencent_symbol(code: str) -> str:
    """裸代码 → 腾讯 ifzq 符号（param 必须带交易所前缀，裸码返回 param error——实测 2026-10-28）。"""
    code = str(code).strip()
    if code[:2] in ("sh", "sz", "bj"):
        return code
    if code[:1] == "6" or code[:1] == "9":
        return "sh" + code
    if code[:1] in ("0", "2", "3"):
        return "sz" + code
    if code[:1] in ("4", "8"):
        return "bj" + code
    return "sz" + code


def _fetch_tencent_prev_bar(code: str, date: str) -> Dict[str, Any]:
    """腾讯 ifzq 日K：取 date 之前最近一根日K。返回 {prev_date, prev_close, prev_volume_shou}。"""
    d = datetime.strptime(date, "%Y-%m-%d").date()
    start = (d - timedelta(days=20)).strftime("%Y-%m-%d")
    sym = _tencent_symbol(code)
    url = (f"{_TENCENT_KLINE_URL}?param={sym},day,{start},{date},20,qfq")
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                 "Chrome/126.0 Safari/537.36",
                                  "Referer": "https://gu.qq.com/"},
                     trust_env=False, timeout=_BASIS_FETCH_TIMEOUT)
    resp.raise_for_status()
    node = ((resp.json() or {}).get("data") or {}).get(sym) or {}
    rows = node.get("qfqday") or node.get("day") or []
    bars = [r for r in rows if isinstance(r, list) and len(r) > 5 and str(r[0]) < date]
    if not bars:
        raise KplRankingError("no_prev_kline", code=code, date=date)
    last = bars[-1]
    return {"prev_date": str(last[0]),
            "prev_close": float(last[2]),
            "prev_volume_shou": float(last[5])}


def get_daban_prev_day_basis(date: str, codes: List[str]) -> Dict[str, Any]:
    """按日批量取竞昨比原料（昨收/昨量）。date 前最近一根日K；结果按日缓存 12h
    （date 未跨交易日则不变）。失败单股记 failed 时间戳（10 分钟内不重试，防轮询打爆），
    以 missing 显式透出（fail-visible，不伪装补齐）。"""
    if not date:
        raise KplRankingError("missing_date")
    uniq = []
    seen = set()
    for c in codes or []:
        c = str(c).strip()
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    if not uniq:
        raise KplRankingError("missing_codes", date=date)
    if len(uniq) > _BASIS_MAX_CODES:
        raise KplRankingError("too_many_codes", date=date, count=len(uniq),
                              note=f"单次上限 {_BASIS_MAX_CODES}")
    with _basis_lock:
        entry = _basis_cache.setdefault(date, {"map": {}, "failed": {}})
    now = time.time()
    need = [c for c in uniq
            if c not in entry["map"]
            and not (entry["failed"].get(c, 0) > now - _BASIS_FAIL_RETRY_SECONDS)]
    if need:
        def _one(code: str):
            try:
                return code, _fetch_tencent_prev_bar(code, date)
            except Exception as exc:
                return code, exc
        with ThreadPoolExecutor(max_workers=_BASIS_CONCURRENCY) as pool:
            for code, res in pool.map(_one, need):
                if isinstance(res, Exception):
                    entry["failed"][code] = now
                else:
                    entry["map"][code] = res
                    entry["failed"].pop(code, None)
    basis = {c: entry["map"][c] for c in uniq if c in entry["map"]}
    missing = [c for c in uniq if c not in entry["map"]]
    return {"ok": True, "date": date, "basis": basis, "missing": missing,
            "source": "tencent_ifzq"}
