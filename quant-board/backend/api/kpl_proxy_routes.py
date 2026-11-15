# -*- coding: utf-8 -*-
"""KPL 实时行情代理路由（:8000 → KPL 服务 :8002）。

- GET  /api/kpl/status       → 透传 :8002 状态（fail-visible：服务不可用返回结构化 502）
- POST /api/kpl/start|stop   → 透传采集启停
- WS   /ws/kpl-quotes        → 双向中继 :8002 的行情事件流到浏览器

KPL 服务本体在 backend/serve_kpl_socket.py（:8002，独立进程，避免 adb/signsvc
依赖影响主后端生命周期）；本路由只做转发，不承载采集逻辑。
pytest 纪律：本路由的测试仅 mock 上游，不触发真实连接。
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from backend.core.settings import get_settings
from backend.services import kpl_ranking_service, kpl_stock_fengkou
from backend.services.kpl_ranking_service import KplRankingError
from backend.api.lhb_fallback import walk_back

router = APIRouter(prefix="/api/kpl", tags=["kpl-socket"])

_UPSTREAM_HTTP = "http://127.0.0.1:8002"
_UPSTREAM_WS = "ws://127.0.0.1:8002/ws/kpl-quotes"
_VOICE_WORKER = "http://127.0.0.1:32145"   # tools/VoiceWorker（本地常驻语音进程）


def _voice_offline(exc: Exception) -> JSONResponse:
    """连接层失败（拒连/超时）：fail-visible 200 + offline（前端提示启动命令并自动重试）。"""
    return JSONResponse(content={"ok": False, "offline": True,
                                 "reason": f"voice_worker_offline: {type(exc).__name__}"})


def _voice_bad_response(detail: str) -> JSONResponse:
    """在线但响应异常（非 2xx/非 JSON）：不误标 offline（避免误导排障方向）。"""
    return JSONResponse(content={"ok": False, "reason": f"voice_worker_bad_response: {detail}"})

# 共享 AsyncClient（2026-10-27）：每请求新建会在事件循环里同步加载 Windows 证书库
# ≈2s/发——:8000 KPL 路由每发中招，:8008 更被多页签轮询拖成事件循环瘫痪
_SHARED_CLIENT: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(trust_env=False)
    return _SHARED_CLIENT


@router.get("/status")
async def status() -> JSONResponse:
    return await _proxy_get("/api/kpl/status")


@router.post("/start")
async def start() -> JSONResponse:
    return await _proxy_post("/api/kpl/start")


@router.post("/stop")
async def stop() -> JSONResponse:
    return await _proxy_post("/api/kpl/stop")


@router.post("/subscriptions")
async def subscriptions(request: Request) -> JSONResponse:
    """更新 :8002 订阅清单（body: {"stock_ids": [...]}），透传采集服务。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    r = await _get_client().post(_UPSTREAM_HTTP + "/api/kpl/subscriptions", json=body or {},
                                 timeout=10)
    return JSONResponse(content=r.json(), status_code=r.status_code)


_DATE_LEN = 10


def _validate_date(date: str) -> Optional[JSONResponse]:
    """历史读口必须显式给日期（实时走 WS 不经此口），格式 YYYY-MM-DD。"""
    if not date or len(date) != _DATE_LEN or date[4] != "-" or date[7] != "-":
        return JSONResponse(
            content={"ok": False, "degraded": True,
                     "reason": "invalid_or_missing_date: 实时请走 WS，历史需 date=YYYY-MM-DD"},
            status_code=400)
    return None


@router.get("/daban-prev-day-basis")
def daban_prev_day_basis(date: str = "", codes: str = ""):
    """竞昨比原料（昨收/昨量）：date 前最近一根日K，腾讯 ifzq 逐股，按日缓存 12h。

    竞昨比=竞价成交量/昨日成交量×100%；竞价成交量=竞价成交额/(竞价价×100)，
    竞价价=昨收×(1+竞价涨幅/100)。同步 def：批量逐股拉取（首次≤数百发）入线程池，
    不阻塞事件循环。缺股以 missing 显式透出（fail-visible）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    code_list = [c for c in (codes or "").split(",") if c.strip()]
    if not code_list:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "missing_codes"},
            status_code=400)
    try:
        return JSONResponse(
            content=kpl_ranking_service.get_daban_prev_day_basis(date, code_list))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/live-stocks-meta")
def live_stocks_meta(date: str = "", codes: str = ""):
    """直播个股表 meta（地位/换手/连板/概念，KPL 成分股口径 ZhiShuStockList_W8）。

    解说/雷达消息流上游不带这四列（此前前端硬编码 "--"）；本口按日惰性后台构建
    板块宇宙 code→meta 索引（TTL 1800s，排行→逐板块扫页，全局 2s/发纪律下
    ~80发≈160s，增量写入渐进可用）：building=True 时返回已命中部分（前端轮询
    渐进渲染）；missed=不在任何 KPL 板块宇宙（如实透出，不伪装）。同步 def：
    读口本身零外呼（查进程内索引），不阻塞事件循环。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    code_list = [c for c in (codes or "").split(",") if c.strip()]
    if not code_list:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "missing_codes"},
            status_code=400)
    return JSONResponse(
        content=kpl_ranking_service.get_live_stocks_meta(code_list, date))


@router.get("/plate-tree")
async def plate_tree() -> JSONResponse:
    """板块树（二级目录映射）：透传 :8002 的 2301 快照懒下载读口。"""
    return await _proxy_get("/api/kpl/plate-tree")


@router.get("/daban-list")
async def daban_list(pid_type: int = 8) -> JSONResponse:
    """2103 打板个股列表快照（KPL App 打板页签）：pid_type 8=集合竞价 / 0=即将涨停 /
    6=风向标 / 1=涨停池 / 2=炸板池 / 3=跌停池。

    数据源=socket 2103 订阅推送的最近快照（collector 缓存），非历史回看——历史走 /daban-list-history。
    """
    return await _proxy_get(f"/api/kpl/daban-list?pid_type={pid_type}")


def _load_daban_lane_day(date: str, *, lane: str) -> JSONResponse:
    """kpl_daban_pool 日档读口公共段（daban-pool/bidding/zhaban/dt）：日期校验 + 存储护栏 + load_day。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    if get_settings().storage_backend != "mongodb":
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "storage_backend_disabled"},
            status_code=502)
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.kpl_daban_archiver import load_day

    return JSONResponse(content=load_day(get_runtime_mongodb_database(), date, lane=lane))


@router.get("/daban-pool")
def daban_pool(date: str = "") -> JSONResponse:
    """涨停池（2103 pidType=1）按日存档读口（2026-11-07 涨停行情历史回放）。

    数据源=本地 MongoDB kpl_daban_pool（DabanPoolArchiver 按日 upsert 的合并快照），
    与实时读口 /daban-list 同构（items 字段一致，前端零转换渲染）。上游 HisDaBanList
    白名单不认页签参数、实证返回默认集合非涨停池——无档返回结构化
    {ok:false, degraded:true, reason:'no_archive'}（fail-visible，不回退默认集合冒充）。
    storage_backend 非 mongodb 同样结构化降级。
    """
    return _load_daban_lane_day(date, lane="pool")


@router.get("/daban-lead")
def daban_lead(date: str = "") -> JSONResponse:
    """板块身位（龙头三合一）按日存档读口（2026-11-10 用户需求「当日实时身位 + 落库」）。

    数据源=本地 MongoDB kpl_daban_pool lead_ 前缀字段（DabanPoolArchiver 每轮在涨停池
    通道后计算落库：候选池=当日封板池∪近3交易日封板池，按 plate_id 分组，龙一=三合一
    空间龙一（rank_board_stocks_seal 单源），龙二..N=dragon_rows 口径补位；断板候选
    sealed_today=False、跌停剔除/缺日/缺 gain 全部结构化披露）。背景：KPL 官方当日
    身位无上游面（层3 ZhiShuStockList_W8 当日盘中 1020 实测四形态；3001 quotas 无
    身位列；GetSection SectionID 属文章卡 id 空间），旧 live-stocks-meta 盘中回退
    上一交易日=混日误读，板块行情页领涨列改读本口。
    无档返回结构化 no_lead_corpus（fail-visible，不回退别日冒充）。
    """
    return _load_daban_lane_day(date, lane="lead")


@router.get("/daban-bidding")
def daban_bidding(date: str = "") -> JSONResponse:
    """集合竞价（2103 pidType=8）按日存档读口（2026-11-08 历史回放）。

    数据源=本地 MongoDB kpl_daban_pool 同日档的 bid_ 前缀字段（用户裁决：不另建数据集），
    DabanPoolArchiver 单循环多通道按日 upsert；载荷映射为与 /daban-list 同构
    （items/ts/max_size/…），前端零转换渲染。无档返回结构化
    {ok:false, degraded:true, reason:'no_archive'}（fail-visible，不回退默认集合冒充）。
    storage_backend 非 mongodb 同样结构化降级。
    """
    return _load_daban_lane_day(date, lane="bid")


@router.get("/daban-zhaban")
def daban_zhaban(date: str = "") -> JSONResponse:
    """炸板池（2103 pidType=2）按日存档读口（2026-11-08 历史回放）。

    数据源=本地 MongoDB kpl_daban_pool 同日档的 zb_ 前缀字段（用户裁决：与涨停池同
    数据集，不新增）；成员口径=当日曾炸板全集（回封后掉出仍留档，回封语义由涨停池
    通道 sealed 承载），字段随最新帧刷新，无 pool_state。载荷与 /daban-list 同构。
    无档/无数据返回结构化降级（fail-visible，不伪装空列表）。
    """
    return _load_daban_lane_day(date, lane="zb")


@router.get("/daban-dt")
def daban_dt(date: str = "") -> JSONResponse:
    """跌停池（2103 pidType=3）按日存档读口（2026-11-08 历史回放）。

    数据源=本地 MongoDB kpl_daban_pool 同日档的 dt_ 前缀字段（用户裁决：与涨停池同
    数据集，不新增）；与涨停池同款收盘态标注——items 内 pool_state：'sealed'=收盘
    仍跌停 / 'broken'=曾入池后掉出即打开跌停未回封（字段为其最后封住时快照）。
    载荷与 /daban-list 同构；无档/无数据返回结构化降级（fail-visible）。
    """
    return _load_daban_lane_day(date, lane="dt")


@router.get("/daban-reasons")
def daban_reasons(date: str = "") -> JSONResponse:
    """2203 涨停原因语料按日读口（2026-11-08，jev 投喂原料）。

    数据源=本地 MongoDB kpl_daban_pool 同日档的 reason_ 前缀字段（用户裁决：不另建
    数据集），2026-11-10 起由 collector（:8002）推送即落库（单写者）；items = 2203 原文
    字段（zt/fx/zt_group/theme/plate/tp/rank 等，不改写不拼接），日期跟随涨停池快照
    交易日（周末/盘前推送的是上一交易日详情）。无档 → no_archive；日档在但语料未
    落库 → no_reason_corpus（fail-visible，不伪装空语料）。
    """
    return _load_daban_lane_day(date, lane="reason")


@router.get("/daban-genes")
def daban_genes(date: str = "") -> JSONResponse:
    """涨停基因（溢价基因）语料按日读口（2026-11-08，题材龙头语料投喂 jev）。

    数据源=本地 MongoDB kpl_daban_pool 同日档的 gene_ 前缀字段（用户裁决：不另建
    数据集），由 DabanPoolArchiver 每轮限量逐股懒取 apphq `StockL2Data/GetZhangTingGene`
    落库（协议层 backend/services/kpl_stock_gene.py）。item 结构：{stock_id,
    gene{zt_count, premium5_count, next_day_red_pct, first_seal_pct, first_broken_pct,
    lianban_pct}, raw 六元数组原样, window_note, fetched_date/same_day 时点标记,
    fetched_at, source}。fail-visible：无档 → no_archive；日档在但语料未落库 →
    no_gene_corpus；pending_n>0 = 涨停池成员尚有未拉的股；backfill_n>0 = 回填条目
    （值含抓取日之后信息，不得当该日盘后已知信息用）。
    """
    return _load_daban_lane_day(date, lane="gene")


@router.get("/regulatory")
def regulatory(date: str = "") -> JSONResponse:
    """监管风险（严重异动/重点监控）按日读口（2026-11-15 预登记 theme-leader-regulatory-risk）。

    数据源=本地 MongoDB kpl_daban_pool reg_ 前缀字段（DabanPoolArchiver regulatory
    lane 每日 17:00 收盘槽单写者；CLI 补采同写路径）。date 空=最新监管档日。
    groups 五列表（today/tomorrow/recent/monitor_current/monitor_history；
    None=端点缺失，[]=真零）+ by_code 代码索引 + states 逐端点 ok/reason。
    无档 → 结构化 no_archive（fail-visible，不伪装空列表）。
    """
    # 空 date=最新档（先判空再校验，避免 _validate_date 把空串当非法）
    if date:
        bad = _validate_date(date)
        if bad is not None:
            return bad
    if get_settings().storage_backend != "mongodb":
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "storage_backend_disabled"},
            status_code=502)
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.kpl_daban_archiver import (
        latest_regulatory_day, load_regulatory_corpus)
    db = get_runtime_mongodb_database()
    day = date or latest_regulatory_day(db)
    if not day:
        return JSONResponse(content={"ok": False, "degraded": True, "reason": "no_archive"})
    return JSONResponse(content=load_regulatory_corpus(db, day))


@router.get("/lhb-forecast")
async def lhb_forecast() -> JSONResponse:
    """2112 会不会上龙虎榜预测快照（task-4）：透传 :8002 collector 读口。

    无快照（未开 daban_lhb/未收到帧）返回结构化降级载荷（fail-visible）。
    """
    return await _proxy_get("/api/kpl/lhb-forecast")


@router.get("/lhb-realtime")
async def lhb_realtime() -> JSONResponse:
    """3004/3101 RealtimeLHB 快照（task-4）：透传 :8002 collector 读口（同上降级规则）。"""
    return await _proxy_get("/api/kpl/lhb-realtime")


@router.get("/zt-reasons")
async def zt_reasons() -> JSONResponse:
    """2203 涨停原因推送快照（试点，2026-11-08）：透传 :8002 collector 读口。

    订阅面=涨停池（2103 pid=1）成员，随入池自动补订；无快照结构化降级（fail-visible）。
    消费端：涨停池页个股列表【涨停原因】tooltip 大段详情。
    """
    return await _proxy_get("/api/kpl/zt-reasons")


@router.get("/zt-reasons/detail")
def zt_reason_detail(date: str = "", stock_id: str = "") -> JSONResponse:
    """涨停原因全文·历史档案单股读口（GetDayZhangTing，2026-11-08 浏览器验收补链）。

    背景：2203 推送只覆盖当日盘中实时态；历史/存档态（如周末看上一交易日）tooltip
    大段详情走本读口单股懒取（前端渲染队逐发，服务端 _post_form 全局 ≥2s 限频兜底）。
    端点无 Date 参数，返回该股最近涨停日条目，按展示日期过滤（不匹配透出 matched_date
    不伪装）。缺参 422；上游异常结构化降级（fail-visible）。消费端：涨停池页 tooltip。
    """
    bad = _validate_date(date)
    if bad is not None:
        return bad
    sid = str(stock_id or "").strip()
    if not sid.isdigit() or not 5 <= len(sid) <= 6:
        return JSONResponse(status_code=422, content={
            "ok": False, "degraded": True, "reason": "invalid_stock_id",
            "note": "必传 stock_id=5-6 位数字代码（单股粒度懒取）"})
    from backend.services import kpl_zt_reason_history as zt_his
    result = zt_his.get_stock_zt_reason(date, sid)
    status_code = 200 if result.get("ok") else 502
    return JSONResponse(content=result, status_code=status_code)


@router.get("/lhb-history")
def lhb_history(date: str = ""):
    """HisBeOnTheLHB 历史龙虎榜读口（task-4）：a=OnTheLHBList 分组榜单 + 个股行。

    同步 def（理由同 daban_list_history）：上游限频分钟级 1 发，30s TTL 缓存内直回。
    必传 date（无默认回看，缺参返 422 结构化降级，fail-visible）。
    """
    from backend.services import kpl_lhb_history as lhb_his
    if not date:
        return JSONResponse(status_code=422, content={
            "ok": False, "degraded": True, "reason": "missing_date",
            "note": "必传 date=YYYY-MM-DD（历史榜单按日拉取，无默认回看）"})
    try:
        raw_list = lhb_his.fetch_his_lhb_list(date)
        raw_stock = lhb_his.fetch_his_lhb_stock(date)
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "degraded": True, "reason": "upstream_error",
            "note": str(exc)[:200]})
    return JSONResponse(content={
        "ok": True, "date": date,
        "list": lhb_his.parse_his_lhb_list(raw_list),
        "stocks": lhb_his.parse_his_lhb_stock(raw_stock),
    })


@router.get("/lhb-sale")
async def lhb_sale(date: str = "", type_: int = 0) -> JSONResponse:
    """营业部成交榜读口（GetBusinessList，applhb 域）：按日全市场营业部买/卖额聚合。

    同步 def（同 lhb_history 理由）：上游限频分钟级，30s TTL 缓存内直回。
    必传 date（缺参返 422 结构化降级）；当日盘前/盘中 list=[] 属结构化空态
    （营业部榜约 17:00 盘后生成），显式 note 提示不伪装。
    """
    from backend.services import kpl_lhb_sale as lhb_sale_svc
    if not date:
        return JSONResponse(status_code=422, content={
            "ok": False, "degraded": True, "reason": "missing_date",
            "note": "必传 date=YYYY-MM-DD（营业部榜按日拉取，无默认回看）"})

    def _fetch(d: str):
        return lhb_sale_svc.parse_lhb_sale(lhb_sale_svc.fetch_lhb_sale(d, type_))

    try:
        parsed = await walk_back(date, _fetch, lambda p: not p["rows"])
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "degraded": True, "reason": "upstream_error",
            "note": str(exc)[:200]})
    if not parsed["rows"]:
        parsed["note"] = "该日期及回看 10 日营业部榜均为空（盘前/盘中查当日属正常：榜约 17:00 盘后生成；非交易日亦空），非降级"
    return JSONResponse(content=parsed)


# /lhb-stock-board、/lhb-agency 聚合读口曾随席位前五上线删除；2026-10-30 晚恢复
# /lhb-stock-board（code review 后用户实测：当日左列表应显实际上榜 83 只=KPL App 同源，
# 原先用 2112 预测池 30 只被席位过滤剩 17 属读数入口错误）；/lhb-agency 保持删除
# （服务层 GetStockList/GetAgencyListV2 fetch/parse 保留，jev_lhb_ammo 直用）。
@router.get("/lhb-stock-board")
async def lhb_stock_board(date: str = "") -> JSONResponse:
    """营业部个股榜读口（GetStockList，applhb 域）：当日实际上榜名单（KPL App 龙虎榜同源）。

    合同同 lhb_sale（README §13）：同步 def + 上游 30s TTL；缺 date 422；
    上游异常 502 结构化降级。消费 code/name/buy_in/turnover/increase_amount；
    JoinNum 语义待证不渲染。
    """
    from backend.services import kpl_lhb_sale as lhb_sale_svc
    if not date:
        return JSONResponse(status_code=422, content={
            "ok": False, "degraded": True, "reason": "missing_date",
            "note": "必传 date=YYYY-MM-DD（个股榜按日拉取，无默认回看）"})

    def _fetch(d: str):
        return lhb_sale_svc.parse_lhb_stock_list(lhb_sale_svc.fetch_lhb_stock_list(d))

    try:
        parsed = await walk_back(date, _fetch, lambda p: not p["rows"])
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "degraded": True, "reason": "upstream_error",
            "note": str(exc)[:200]})
    if not parsed["rows"]:
        parsed["note"] = "该日期及回看 10 日上榜名单均为空（~17:00 盘后生成/非交易日，非降级）"
    return JSONResponse(content=parsed)


@router.get("/daban-list-history")
async def daban_list_history(date: str = "", pid_type: int = 8) -> JSONResponse:
    """按日打板个股列表历史收盘帧（HisDaBanList HTTP，App 市场情绪·日期回看同款读口）。

    上游白名单参数（2026-10-28 实测）：仅 Day+五件套+凭据，不认页签/分页参数，
    返回默认集合；故无 page 透传（历史模式前端单发不轮询）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    if pid_type not in (0, 1, 2, 3, 4, 5, 6, 7, 8):
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "invalid_pid_type"},
            status_code=400)
    try:
        return JSONResponse(
            content=kpl_ranking_service.get_daban_list_history(date, pid_type))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/daban-head")
async def daban_head(date: str = "") -> JSONResponse:
    """按日打板头统计（HisDaBanHeadInfo HTTP）：今/昨涨停·封板率·跌停绝对值，KPI 三卡昨日侧来源。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    try:
        return JSONResponse(content=kpl_ranking_service.get_daban_head_info(date))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/voice/status")
async def voice_status() -> JSONResponse:
    """VoiceWorker 状态探测（tools/VoiceWorker 本地 32145）。

    连接失败 → 200+offline（不报 500，前端自动重试）；在线但非 2xx/非 JSON → bad_response。
    """
    try:
        resp = await _get_client().get(f"{_VOICE_WORKER}/status", timeout=2.0)
    except Exception as exc:
        return _voice_offline(exc)
    if resp.status_code >= 400:
        return _voice_bad_response(f"http_{resp.status_code}")
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.post("/voice/speak")
async def voice_speak(request: Request) -> JSONResponse:
    """语音播报转发（VoiceWorker POST /speak；text 上限 200 字，这里先截一层）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"ok": False, "reason": "invalid_json"}, status_code=400)
    text = str(body.get("text") or "").strip()
    if not text:
        return JSONResponse(content={"ok": False, "reason": "empty_text"}, status_code=400)
    payload = {"text": text[:200]}
    for key in ("rate", "volume", "voice"):
        if body.get(key) is not None:
            payload[key] = body[key]
    try:
        resp = await _get_client().post(f"{_VOICE_WORKER}/speak", json=payload, timeout=5.0)
    except Exception as exc:
        return _voice_offline(exc)
    if resp.status_code >= 400:
        return _voice_bad_response(f"http_{resp.status_code}")
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.post("/voice/stop")
async def voice_stop() -> JSONResponse:
    """清空 VoiceWorker 播报队列。"""
    try:
        resp = await _get_client().post(f"{_VOICE_WORKER}/stop", timeout=3.0)
    except Exception as exc:
        return _voice_offline(exc)
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.get("/live")
def live(st: int = 30) -> JSONResponse:
    """直播解说流（KPL App 直播页同源 ZhiBoContent，需 App 凭据；15s TTL 缓存）。

    同步 def：service 层是同步 urllib + 2s 节流 sleep，FastAPI 自动入线程池，
    不阻塞事件循环（同 daban_prev_day_basis 既有裁决）。凭据仅进请求参数（公共出口），
    不落日志不返回；fail-visible 结构化错误。
    """
    try:
        return JSONResponse(content=kpl_ranking_service.get_live_commentary(st=st))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/radar")
def radar(st: int = 60) -> JSONResponse:
    """市场雷达/直播流（KPL 层1 a=Radar c=HomeDingPan，仅实时；5s TTL 缓存）。同步 def 理由同 /live。"""
    try:
        return JSONResponse(content=kpl_ranking_service.get_market_radar(st=st))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/sector-ranking")
async def sector_ranking(date: str = "") -> JSONResponse:
    """按日板块强度排行（KPL 层1 RealRankingInfo Type=1+Date，历史回看读口）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    try:
        return JSONResponse(content=kpl_ranking_service.get_sector_ranking(date))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/sector-stocks")
async def sector_stocks(plate: str = "", date: str = "", page: int = 0) -> JSONResponse:
    """按日板块成分股（KPL 层3 ZhiShuStockList_W8，历史回看读口；page=每页100 只的分页序号）。

    分页契约（2026-10-27 用户裁决）：真·按页取数——一页 = 一次上游请求
    （st=page_size&Index=page*page_size），切板块/翻页各只发一枪，30s TTL 按
    (plate,date,page) 缓存；total 不可知，前端用 has_more 翻页。
    """
    bad = _validate_date(date)
    if bad is not None:
        return bad
    if not plate:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "missing_plate"},
            status_code=400)
    if page < 0:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "invalid_page"},
            status_code=400)
    try:
        return JSONResponse(content=kpl_ranking_service.get_sector_stocks(plate, date, page=page))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/fengkou/observation")
def fengkou_red_observation(date: str = "") -> JSONResponse:
    """最强风口红名观察日档（预登记 2026-11-15；只读，不进锚人群）。

    date 缺省=最新一篇；无档时结构化 degraded 返回（fail-visible 读口，不硬门禁）。
    doc 字段：probes（多时点快照含降级原因）/ redUnion（跨时点并集含首末时点、
    T−1 在池标记）/ nextDay（T+1 收盘涨幅含 missing）/ quality / obsState。
    """
    from backend.operations import fengkou_red_observer
    date = (date or "")[:10]
    if date:
        bad = _validate_date(date)
        if bad is not None:
            return bad
    if get_settings().storage_backend != "mongodb":
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "storage_backend_disabled"},
            status_code=502)
    try:
        from backend.data.repositories.repository_factory import (
            get_runtime_mongodb_database)
        db = get_runtime_mongodb_database()
        doc = (db[fengkou_red_observer.OBS_COLLECTION].find_one({"_id": date})
               if date else
               db[fengkou_red_observer.OBS_COLLECTION].find_one(sort=[("_id", -1)]))
    except Exception as exc:  # noqa: BLE001 — 读口降级结构化透出
        return JSONResponse(content={"ok": False, "degraded": True,
                                     "reason": "observation_db_error",
                                     "error": f"{type(exc).__name__}: {exc}"[:200]},
                            status_code=200)
    if not doc:
        return JSONResponse(content={"ok": False, "degraded": True,
                                     "reason": "no_observation_doc",
                                     "date": date or None},
                            status_code=200)
    doc = dict(doc)
    doc["date"] = str(doc.pop("_id"))
    return JSONResponse(content={"ok": True, **doc})


@router.get("/fengkou")
def fengkou(date: str = "", time: str = "") -> JSONResponse:
    """最强风口个股强度榜（apphq StockFengKData/GetFengKListBest，2026-11-15 逆向）。

    数据源=KPL App「最强风口」H5 页（web2/strongestTuyere.html）同款读口：
    实时 date 空（Time=time 参数透传，App 时间滑条 HHMM）；历史 date=YYYY-MM-DD
    （→ Day=YYYYMMDD 走 apphis，H5 原合同；2026-11-15 实测 apphis 1020，合同待有效
    凭据核实，fail-visible）。**端点要求登录态**（1001）：凭据只进 quant-board/.env.local
    （QUANT_BOARD_KPL_APP_USERID/_DEVICEID/_TOKEN），失效时换绑后重启后端即可。
    参数校验：非法 time/date 直接 422 拒绝，不触上游（频控红线 9：垃圾值换真实上游调用
    =风控记录，缓存键即原始入参不可作绕 TTL 通道）。频控预算：
    服务层 30s TTL + 无重试循环；前端 60s 轮询 → ≤1 发/分钟。
    协议层/行语义见 backend/services/kpl_stock_fengkou.py 模块头。
    """
    time_hhmm = (time or "")[:4]
    if time_hhmm and not re.fullmatch(r"\d{4}", time_hhmm):
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "invalid_time",
                     "error": "time 须为 HHMM 四位数字（App 时间滑条口径）"},
            status_code=422)
    date = (date or "")[:10]
    if date:
        bad = _validate_date(date)
        if bad is not None:
            return bad
    return JSONResponse(content=kpl_stock_fengkou.get_fengkou(time_hhmm=time_hhmm,
                                                              date=date))


async def _proxy_get(path: str) -> JSONResponse:
    try:
        # trust_env=False：忽略系统代理，防止 Clash 全局模式劫持 127.0.0.1（同 relay_page 教训）
        r = await _get_client().get(_UPSTREAM_HTTP + path, timeout=10)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"kpl_upstream_unavailable: {exc}"},
            status_code=502,
        )


async def _proxy_post(path: str) -> JSONResponse:
    try:
        r = await _get_client().post(_UPSTREAM_HTTP + path, timeout=10)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"kpl_upstream_unavailable: {exc}"},
            status_code=502,
        )


@router.websocket("/ws/kpl-quotes")
async def ws_quotes(ws: WebSocket) -> None:
    """:8000 浏览器连接 ↔ :8002 KPL 服务 双向中继。"""
    await ws.accept()
    try:
        async with websockets.connect(_UPSTREAM_WS, open_timeout=10) as upstream:
            async def pump_upstream():
                while True:
                    msg = await upstream.recv()
                    await ws.send_text(msg if isinstance(msg, str) else msg.decode())

            async def pump_downstream():
                while True:
                    msg = await ws.receive_text()
                    await upstream.send(msg)

            done, pending = await asyncio.wait(
                [asyncio.create_task(pump_upstream()), asyncio.create_task(pump_downstream())],
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            exc = next((t.exception() for t in done if t.exception()), None)
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                raise exc
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
