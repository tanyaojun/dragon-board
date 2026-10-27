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
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

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

def get_sector_ranking(date: str) -> Dict[str, Any]:
    """按日取板块强度排行全量（Type=1+Date 分页取齐）。

    返回 {"ok": True, "date": ..., "items": [...]}；上游/业务错误抛 KplRankingError。
    """
    cached = _cached(f"ranking:{date}")
    if cached is not None:
        return cached
    items: List[Dict[str, Any]] = []
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
        rows = data.get("list") or []
        # 盘前/未生成时上游会返回「全零行」（plate_id="0"、名称空）——过滤，
        # 否则引导把垃圾行当有效数据、真正有数的旧日期被跳过（2026-10-27 实测）
        rows = [r for r in rows
                if isinstance(r, list) and r and str(r[0] or "").isdigit()
                and len(str(r[0])) == 6 and str(r[1] or "").strip()]
        items.extend(parse_ranking_row(r) for r in rows)
        if len(rows) < _RANKING_PAGE_SIZE:
            break
    payload = {"ok": True, "date": date, "items": items}
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
    _check_errcode(data)
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


def get_daban_list_history(date: str, pid_type: int, page: int = 0,
                           page_size: int = 100) -> Dict[str, Any]:
    """按日取打板个股列表历史收盘帧（App 市场情绪·股票列表的日期回看读口）。

    合同（2026-10-27 逆向自 BiddingZTlQuotaPresenter.a0 → ox0.L2 → j00.P1 → qg.q1）：
    POST apphis ``a=HisDaBanList&c=HisHomeDingPan``，``Day=date``、``PidType``（8=竞价
    0=即将涨停 6=风向标）、``Type=18``（orderType App 基线，与 socket 2103 一致）、
    ``Order=1``、``Is_st/Filter/FilterMotherboard/FilterGem/FilterTIB=0``、``Index/st`` 分页；
    凭据走 mapping_refresh 公共出口。2026-10-27 晚实测上游返回 errcode 1020 参数出错
    （游客/现役/socket 凭据、apiv w21-w48、Day/Date/Isst 变体、三域名全试均 1020；
    同通道 RealRankingInfo/DaBanList errcode=0）——上游口径变更待查，此处如实透出。
    """
    page = max(page, 0)
    page_size = max(1, min(page_size, _STOCKS_MAX_PAGE_SIZE))
    key = f"hisban:{pid_type}:{date}:{page}:{page_size}"
    cached = _cached(key)
    if cached is not None:
        return cached
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    data = _post_form(
        _HOST_HISTORY,
        {"a": "HisDaBanList", "c": "HisHomeDingPan", "Day": date,
         "PidType": pid_type, "Type": 18, "Order": 1, "Is_st": 0,
         "Index": page * page_size, "st": page_size,
         "Filter": 0, "FilterMotherboard": 0, "FilterGem": 0, "FilterTIB": 0,
         "apiv": "w48", "VerSion": "6.3.20.2", "PhoneOSNew": 1, "Red": 0, **creds},
        _UA_STOCKS)
    _check_errcode(data)
    rows = data.get("list") or []
    if not rows and page == 0:
        # 首页即空不伪装（与 sector-stocks 同款：逐日回退日期由前端驱动）
        raise KplRankingError("empty_list_check_credentials", pid_type=pid_type, date=date)
    items = [_parse_daban_history_row(r) for r in rows if isinstance(r, list) and r]
    payload = {"ok": True, "date": date, "pid_type": pid_type,
               "page": page, "page_size": page_size,
               "has_more": len(items) >= page_size, "items": items,
               "day": data.get("day", date)}
    _store(key, payload)
    return payload


def get_daban_head_info(date: str) -> Dict[str, Any]:
    """按日取打板头统计（App 市场情绪页头的今/昨涨停·封板率·跌停绝对值来源）。

    合同（2026-10-27 逆向自 ox0：API_HISTORY + a=HisDaBanHeadInfo&c=HisHomeDingPan，
    Day=date；预期字段 todayZT/yesterdayZT/todayFB/yesterdayFB/todayDT/yesterdayDT，
    响应结构未经真实样本核对——当晚上游风控 1020 拿不到样本，接入前须同屏核对）。
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
