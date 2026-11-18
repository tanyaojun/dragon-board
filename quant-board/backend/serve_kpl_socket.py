# -*- coding: utf-8 -*-
"""KPL 实时行情 WebSocket 服务（:8002，独立于 :8000 主后端，避免互相影响）。

- GET  /kpl          → 浏览器实时面板（backend/kpl_page/index.html）
- WS   /ws/kpl-quotes → 订阅采集服务广播的行情/状态/错误事件流
- GET  /api/kpl/status → 采集服务状态（sessions/pushes/errors/last_error，fail-visible）
- POST /api/kpl/start → 启动采集线程（幂等）
- POST /api/kpl/stop  → 停止采集线程

启动：.\\.venv\\Scripts\\python.exe -m uvicorn backend.serve_kpl_socket:app --host 127.0.0.1 --port 8002
依赖（双轨，KPL_CODEC 切换）：pc（默认）= unicorn 本机模拟 libauthSign（kpl_pcemu/，
工件在 data/kpl_pcemu/，scripts/extract_kpl_pcemu.py 提取，不依赖 adb/模拟器）；
adb = 模拟器在线 + signsvc（/data/local/tmp/signsvc.dex）兼容兑底轨。
未就绪时页面显示结构化错误而非空白（fail-visible）。
身份：KPL_USER_ID/KPL_TOKEN 只从环境变量读（凭据不入仓，AGENTS.md 红线 3）；
默认游客 userId=0 可收行情但服务器会话更短；正式账户值放 .env.local / 环境变量注入。

pytest 纪律：本模块的测试不得启动真实采集线程/真实 signsvc —— 全部用 FakeCodec + 不调用 start()。
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from backend.core import settings as _settings  # noqa: F401  # 导入即载入 .env.local（KPL_* 凭据正式唯一来源）
from backend.services.kpl_collector_service import KplCollectorService, SignSvcAdbCodec
from backend.services.kpl_pcemu import PCEmulatorCodec

app = FastAPI(title="KPL Quotes Relay", docs_url=None, redoc_url=None)

_PAGE = Path(__file__).parent / "kpl_page" / "index.html"

_ADB_PATH = os.environ.get("KPL_ADB_PATH", r"D:/Android/Sdk/platform-tools/adb.exe")
_ADB_DEVICE = os.environ.get("KPL_ADB_DEVICE", "emulator-5554")
_SIGNVC_SHELL = os.environ.get(
    "KPL_SIGNVC_SHELL",
    'su -c "export LD_LIBRARY_PATH=/data/app/com.aiyu.kaipanla-MibnEsTYjx-z7wDAymTrqQ==/lib/x86_sig; '
    'export CLASSPATH=/data/local/tmp/signsvc.dex; '
    '/system/bin/app_process32 /system/bin com.yzj.kaipanh.newindex.data.SignSvc"',
)
_DEVICE_ID = (
    os.environ.get("KPL_DEVICE_ID")
    or os.environ.get("QUANT_BOARD_KPL_APP_DEVICEID", "")
).strip()   # 两支统一 strip：空白字符串不得当作「已配置」（评审 P2）
if not _DEVICE_ID:
    logging.getLogger(__name__).warning(
        "KPL DeviceID 缺失（KPL_DEVICE_ID / QUANT_BOARD_KPL_APP_DEVICEID 均未配置）："
        "WBE 签名将用空设备指纹，登录态校验端点可能拒绝——请把模拟器提取的 DeviceID "
        "写入 quant-board/.env.local（提取路径见 mapping_refresh.py 注释）")  # fail-visible

# 龙虎榜采集开关（task-4）：默认开（2112 预测 + 3004/3101 实时）。
# 显式关闭：KPL_DABAN_LHB=0 / KPL_LHB_REALTIME=0（切换需重启进程）。
def _env_flag(name: str, *, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "off", "no")


_DABAN_LHB = _env_flag("KPL_DABAN_LHB")
_LHB_REALTIME = _env_flag("KPL_LHB_REALTIME")
# 2203 个股涨停原因推送试点（2026-11-08，涨停池页 tooltip 详情）：默认开，
# 显式关闭 KPL_ZT_REASON_SUBS=0（切换需重启进程）；订阅面=涨停池成员自动跟随。
_ZT_REASON_SUBS = _env_flag("KPL_ZT_REASON_SUBS")
# 显式关闭 KPL_THEME_SUBS=0（切换需重启进程）；订阅面=涨停池成员自动跟随（2026-11-08 题材库）。
_THEME_SUBS = _env_flag("KPL_THEME_SUBS")
# 个股详情四通道订阅（2026-11-11 ④，实弹开火开关）：默认关（纪律：实弹开火需
# 用户预登记+预算确认，AGENTS §1.2-7）；显式开启 KPL_STOCK_DETAIL_SUBS=1
# （切换需重启进程）；订阅面=涨停池成员自动跟随（bdo=2014/bf=2202/abn=2030/
# rplate=2010，频控预算=池成员×4 帧/会话，每 lane 每 tick 1 帧 + 0.3s 拟人停顿）。
_STOCK_DETAIL_SUBS = os.environ.get("KPL_STOCK_DETAIL_SUBS", "0").strip().lower() in (
    "1", "true", "on", "yes")
# 订阅注册表化 + 211 批量增强（2026-11-17 P0-P3，方案唯一来源
# docs/kpl-socket/sub-registry-refactor-plan.md）：
# KPL_SUB_REGISTRY=0 → 220 全量重发旧行为（注册表观测始终在）；默认开。
# KPL_SUB_BATCH=direct|211 → 订阅帧形态；默认 direct（现状逐字节），211 需探针
#   U1-U8 钉死 + 用户批准后灰度；会话级熔断自动回退单帧。
# KPL_SUB_BATCH_CODEC=0|1 → 211 item.data 明文/GCM（U2 实弹定案：必须 GCM，默认 1）。
# KPL_UNSUB_ENABLED=1 → 402/pkg 0x50 退订（需先 KPL_SUB_UNIQUE_ID=1 使 per-stock
#   subId 唯一，否则冲突护栏使 per-stock 退订为安全空操作；方案 §12）。
# KPL_KA_MODE=610|off|none → 保活模式。2026-11-18 源码定案默认 none：App 无周期
#   保活（610 仅 userAuth 一次、无 Timer/schedule，独立审计 C2 源码实锤）；
#   off=3001 轮转跑步机（852 面下每 6s 全量重订阅，rst_10054 根因①）。
#   历史注：P4「off 更贴 App」结论是小面（3 id）实验，动态面未复验即失效；
#   「全订阅面爆发指纹→10054 主导」已证伪（真凶=3101 错通道，README §3.7）。
_SUB_REGISTRY = _env_flag("KPL_SUB_REGISTRY")
# 分波订阅（历史件：iso1「体积阈值」动机已证伪，真凶=3101 错通道，README §3.7；
# wave1=critical，wave2/3 (+15s/+45s) 错峰补齐，+150s failsafe）。
# 2026-11-18 独立 review major-2 修复：默认必须 0——_env_flag 缺省"1"会与
# setup_inline_subs 默认 1 互斥（服务类 ValueError），干净环境启动即崩。
_SUB_STAGED = _env_flag("KPL_SUB_STAGED", default="0")
# 2103 竞价池（pid=8）页数：竞价链 universe 依赖页深，默认保持 7；非竞价池
# 恒 1 页（P1 收敛，README §3.6）。回滚口=本 env（仅作用于 pid=8）。
_DABAN_LIST_PAGES = int(os.environ.get("KPL_DABAN_LIST_PAGES", "7"))
_SUB_BATCH_MODE = os.environ.get("KPL_SUB_BATCH", "direct").strip().lower()
if _SUB_BATCH_MODE not in ("direct", "211"):
    raise RuntimeError(f"KPL_SUB_BATCH 非法值 {_SUB_BATCH_MODE!r}（仅支持 direct|211）")
_SUB_BATCH_CODEC_RAW = os.environ.get("KPL_SUB_BATCH_CODEC", "1").strip()
if _SUB_BATCH_CODEC_RAW not in ("0", "1"):
    raise RuntimeError(f"KPL_SUB_BATCH_CODEC 非法值 {_SUB_BATCH_CODEC_RAW!r}（仅 0|1）")
_SUB_BATCH_CODEC = int(_SUB_BATCH_CODEC_RAW)   # U2 实弹：明文=2008 杀连，默认 1；m2 值域 fail-fast
_UNSUB_ENABLED = os.environ.get("KPL_UNSUB_ENABLED", "0").strip().lower() in (
    "1", "true", "on", "yes")
_KA_MODE = os.environ.get("KPL_KA_MODE", "none").strip().lower()   # 2026-11-18 定案默认 none
if _KA_MODE not in ("610", "off", "none"):
    raise RuntimeError(f"KPL_KA_MODE 非法值 {_KA_MODE!r}（仅支持 610|off|none）")
# KPL_SUB_UNIQUE_ID=1 → per-stock 订阅 ext attr2 用会话内唯一 subId hint（base 0x4000）
#   而非 cmd，使服务端授予每股独立 subId → 402 精准退单股（方案 §12，探针裁决后启用）。
_SUB_UNIQUE_ID = os.environ.get("KPL_SUB_UNIQUE_ID", "0").strip().lower() in (
    "1", "true", "on", "yes")
# 3004 单帧拉取条数（2026-10-30 用户裁决 30→120，覆盖实际上榜全名单 ~83 只；
# 切换需重启进程；开火验证记录见 docs/kpl-socket/README.md §13.2）
_LHB_REALTIME_COUNT = int(os.environ.get("KPL_LHB_REALTIME_COUNT", "120"))
# 身份凭据只从环境变量读（不入仓；正式值在 quant-board/.env.local，游客 userId=0 可收
# 行情但会话寿命较短；进程环境已设同名变量时以环境变量优先——settings 加载器不覆盖）
_USER_ID = os.environ.get("KPL_USER_ID", "0")
_TOKEN = os.environ.get("KPL_TOKEN", "")

# 双轨 codec：pc（默认，unicorn 本机模拟）| adb（signsvc 兼容兑底）。
# 切换需重启进程；codec 构造无副作用（懒初始化在首次调用时）。
_CODEC_MODE = os.environ.get("KPL_CODEC", "pc").strip().lower()
if _CODEC_MODE == "adb":
    _codec = SignSvcAdbCodec(_ADB_PATH, _ADB_DEVICE, _SIGNVC_SHELL)
elif _CODEC_MODE == "pc":
    _codec = PCEmulatorCodec(assets_dir=os.environ.get("KPL_PCEMU_ASSETS"))
else:
    raise RuntimeError(f"KPL_CODEC 非法值 {_CODEC_MODE!r}（仅支持 pc|adb）")

# auth 相位延迟（2026-11-09 会话抖动根因修复）：§3.4 实证 auth 耗时决定会话档位
# （<1s→~6s 断；~1-2s→15-25s 拟人档；adb 5-8s→75-160s）。默认 5.0 对齐 adb 档
# （实际 5.0+U(0,3.0)s）；置 0 = 回退旧拟人档（auth 相位仅剩 U(0,3)s 抖动）。
# 切换需重启进程。
_AUTH_PHASE_DELAY = float(os.environ.get("KPL_AUTH_PHASE_DELAY", "5.0"))

# 构造无副作用，饿汉单例避免懒初始化竞态
_service_lock = asyncio.Lock()
_service = KplCollectorService(
    _codec,
    device_id=_DEVICE_ID, user_id=_USER_ID, token=_TOKEN,
    daban_lhb=_DABAN_LHB, lhb_realtime=_LHB_REALTIME,
    lhb_realtime_count=_LHB_REALTIME_COUNT,
    zt_reason_subs=_ZT_REASON_SUBS, theme_subs=_THEME_SUBS,
    stock_detail_subs=_STOCK_DETAIL_SUBS,
    stock_detail_max_stocks=int(os.environ.get("KPL_DETAIL_MAX_STOCKS", "15") or 15),
    # 2026-11-18：订阅 setup 内联连发（App qn0.z() 同款）。历史注：「0x40 时间窗」
    # 动机已证伪（真凶=3101 错用 0x40 通道，README §3.7），inline 保留纯因 App 同款。
    setup_inline_subs=_env_flag("KPL_SETUP_INLINE_SUBS"),
    # 行情面硬帽：生产禁用（0=不限）——截断致 relay 页板块行情缺推；总量卫生实验旋钮
    quote_face_cap=int(os.environ.get("KPL_QUOTE_FACE_CAP", "0") or 0),
    # KPL_DRAIN_PAUSE_MS=100 → (0.1, 0.05)：实弹验证保守档（App 实际零节流连发）
    **({"drain_pause": (float(os.environ["KPL_DRAIN_PAUSE_MS"]) / 1000,
                        float(os.environ["KPL_DRAIN_PAUSE_MS"]) / 2000)}
        if os.environ.get("KPL_DRAIN_PAUSE_MS") else {}),
    auth_phase_delay=_AUTH_PHASE_DELAY,
    loop_send_grace_s=float(os.environ.get("KPL_LOOP_SEND_GRACE", "5")),
    # 交易时段门控（2026-11-11）：非交易时段不建连（防风控打标累积），默认开；
    # 显式关闭 KPL_ENFORCE_TRADING_HOURS=0（切换需重启进程）
    enforce_trading_hours=_env_flag("KPL_ENFORCE_TRADING_HOURS"),
    # 订阅注册表化 + 211 批量 + 402 退订（2026-11-17，切换需重启进程）
    sub_registry_enabled=_SUB_REGISTRY,
    sub_batch_mode=_SUB_BATCH_MODE,
    sub_batch_codec=_SUB_BATCH_CODEC,
    sub_batch_max_items=int(os.environ.get("KPL_SUB_BATCH_MAX_ITEMS", "10") or 10),
    sub_batch_ack_timeout_s=float(os.environ.get("KPL_SUB_BATCH_ACK_TIMEOUT", "10") or 10),
    unsub_enabled=_UNSUB_ENABLED,
    ka_mode=_KA_MODE,
    sub_unique_id=_SUB_UNIQUE_ID,
    sub_staged=_SUB_STAGED,
    daban_list_pages=_DABAN_LIST_PAGES)


def _get_service() -> KplCollectorService:
    return _service


@app.get("/kpl")
def page() -> FileResponse:
    return FileResponse(_PAGE, media_type="text/html")


@app.get("/api/kpl/status")
def status() -> JSONResponse:
    svc = _get_service()
    return JSONResponse(content={"ok": True, "codec": _CODEC_MODE, **svc.status()})


@app.get("/api/kpl/subscription-ids")
def subscription_ids() -> JSONResponse:
    """只读暴露 3001/3006 行情订阅宇宙（零行为变更观测，2026-11-17）：
    供爆发指纹探针复现生产全量行情面（探针默认仅 1 板块，与生产 331 ids 差异
    是隔离实验的关键 confound）。返回 stock_ids + priority_ids（优先块）。"""
    svc = _get_service()
    return JSONResponse(content={"ok": True,
                                 "stock_ids": list(svc._stock_ids),
                                 "priority_ids": list(svc._sub_prio_all)})


@app.post("/api/kpl/start")
async def start() -> JSONResponse:
    svc = _get_service()
    async with _service_lock:
        if not svc.is_running():
            svc.start()
    return JSONResponse(content={"ok": True, **svc.status()})


@app.post("/api/kpl/stop")
async def stop() -> JSONResponse:
    svc = _get_service()
    async with _service_lock:
        svc.stop()
    return JSONResponse(content={"ok": True, **svc.status()})


@app.get("/api/kpl/plate-tree")
def plate_tree() -> JSONResponse:
    """板块树读口（二级目录映射）：2301 快照懒下载解析，version 变化才重新拉取。"""
    return JSONResponse(content=_get_service().get_plate_tree())


@app.get("/api/kpl/lhb-forecast")
def lhb_forecast() -> JSONResponse:
    """2112 会不会上龙虎榜预测快照（task-4）：无快照返回结构化降级（fail-visible）。"""
    return JSONResponse(content=_get_service().get_lhb_forecast())


@app.get("/api/kpl/lhb-realtime")
def lhb_realtime() -> JSONResponse:
    """3004/3101 RealtimeLHB 快照（task-4）：无快照返回结构化降级（fail-visible）。"""
    return JSONResponse(content=_get_service().get_lhb_realtime())


@app.get("/api/kpl/zt-reasons")
def zt_reasons() -> JSONResponse:
    """2203 涨停原因推送快照（试点）：{stock_id → 原因详情}，订阅面=涨停池成员。

    无快照（采集未运行/未到流）返回结构化降级载荷（fail-visible）。
    """
    return JSONResponse(content=_get_service().get_zt_reasons())


@app.get("/api/kpl/theme-heat")
def theme_heat() -> JSONResponse:
    """2013 题材库热度快照读口（题材龙头语料第 2 项，2026-11-08）。"""
    return JSONResponse(content=_get_service().get_theme_heat())


@app.get("/api/kpl/daban-list")
def daban_list(pid_type: int = 8) -> JSONResponse:
    """2103 打板个股列表快照（最近一次订阅推送缓存）：pid_type 8=集合竞价 / 0=即将涨停 / 6=风向标。

    无快照（采集未运行/未订阅/非交易时段首拉）返回结构化降级载荷（fail-visible）。
    """
    return JSONResponse(content=_get_service().get_daban_list(pid_type))


@app.post("/api/kpl/subscriptions")
async def subscriptions(request: Request) -> JSONResponse:
    """更新 3001/3006 订阅清单（body: {"stock_ids": [...], "priority_ids": [...]}，
    priority_ids=优先块成员（轮询更频）；单请求 id 超 ~241 会被服务器 1106 拒绝，
    采集器内部自动分块轮询。merge=true 时与现有清单求并（补引导不抹别页订阅）。

    下一个 3001 轮询即生效（~2s）；空清单拒绝并结构化返回（fail-visible）。
    """
    svc = _get_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = svc.set_subscriptions((body or {}).get("stock_ids") or [],
                                   (body or {}).get("priority_ids") or [],
                                   merge=bool((body or {}).get("merge")))
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(content={"ok": result.pop("ok", False), "subscriptions": result,
                                 **svc.status()}, status_code=status_code)


@app.websocket("/ws/kpl-quotes")
async def ws_quotes(ws: WebSocket) -> None:
    """事件流转发：服务广播队列 → 浏览器。队列溢出/断连都 fail-visible 上报。"""
    await ws.accept()
    svc = _get_service()
    if not svc.is_running():
        # 页面显式按钮触发 start；连接时自动启动一次（首次体验友好）
        async with _service_lock:
            if not svc.is_running():
                svc.start()
    q = svc.subscribe()
    try:
        while True:
            try:
                event = await asyncio.to_thread(q.get, timeout=1.0)
            except queue.Empty:
                # 心跳 keepalive，防止代理空闲断开
                await ws.send_json({"type": "ping", "ts": time.time()})
                continue
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        svc.unsubscribe(q)
        # 行情订阅面回落默认（2026-11-18 用户裁决）：浏览器全断开 = App 离屏
        # （qn0 f() 清 d/e 同款）；否则 merge 进来的 852 id 每会话全量重发
        # （3001+3006 ×2cmd），构成 rst_10054 残余超支。页面重开自会重新 POST。
        # 回落仅动态面在位时触发（default 面不重置不刷写）；KPL_SUB_IDLE_RESET=0
        # 可关（需重启，兼容 headless 长听场景）。
        if (_env_flag("KPL_SUB_IDLE_RESET")
                and svc.subscriber_count() == 0):
            reset = svc.reset_subscriptions_to_default()
            if reset.get("before", {}).get("count", 0) != reset.get("after", {}).get("count", 0):
                logging.getLogger(__name__).info(
                    "行情订阅面回落默认：%s → %s", reset.get("before"), reset.get("after"))
