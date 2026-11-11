# -*- coding: utf-8 -*-
"""KPL socket 采集服务：后台线程维持 signsvc + TLS 会话链，解码行情事件并广播。

职责边界（2026-10-27 设计）：
- 本模块是唯一允许发起真实 KPL TLS 连接的运行时组件；pytest 不得触发（用 mock codec）。
- 加密/解密/签名全部走注入的 codec（默认 SignSvcAdbCodec → 模拟器内 signsvc 常驻进程）。
- fail-visible：连接失败 / 解码失败 / 服务器错误一律变成结构化事件广播，绝不静默丢弃；
  同时记录 last_error 供 /api/kpl/status 查询。
- 会话模型：服务器 TTL ≈ 60-90s（与心跳频率无关），连接断开后 2s 重连（app 的
  ReconnectManager 同款策略），数据流跨会话连续写入同一事件流。
- WebSocket 层（serve_kpl_socket.py）只做转发：从 subscribe() 的队列读取事件推送浏览器。

线程模型：
- 主线程（FastAPI/uvicorn）只消费事件队列，绝不阻塞在 socket 读写。
- 采集线程 _run_loop 持有 TLS socket；stop() 置位停止标志并关闭 socket。
"""
from __future__ import annotations

import os
import queue
import random
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import datetime

from backend.services import kpl_daban_protocol as daban
from backend.services import kpl_lhb_protocol as lhb
from backend.services import kpl_socket_protocol as proto
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI

# 与 .tmp_review/kpl_collector.py 一致的连接参数（实测有效组合）
DEFAULT_HOST = "124.71.0.49"
DEFAULT_PORT = 8080
TLS_SNI = "socket.kaipan.com"


class SignSvcError(RuntimeError):
    """signsvc 调用失败（含设备离线 / READY 超时 / RES null）。"""


class AntiCheatError(RuntimeError):
    """261 反作弊轮无法作答（EXEC 缺失/VM 失败/应答加密不可用）——必须断连重连。

    App 行为同款（GameClient$onChallenge$2 / qn0.g）：execEncryptedHex 返回
    Long.MIN_VALUE → 直接关 socket，不发假答案（发 0 会被服务器判作弊）。
    """


class SignSvcAdbCodec:
    """通过 adb 驱动模拟器内 signsvc 常驻进程，提供 ENC/DEC/WBE。

    WBE(challenge, deviceId, connType, curTime) → signature bytes（hex 字符串）
    ENC(plain) → GCM 密文；DEC(cipher) → 明文。失败抛 SignSvcError（fail-visible）。
    """

    def __init__(self, adb_path: str, device: str, shell_cmd: str, ready_timeout: float = 30.0):
        self._adb = adb_path
        self._device = device
        self._shell_cmd = shell_cmd
        self._ready_timeout = ready_timeout
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        # 守护读线程 + 队列：readline 在 Windows 管道上无法被超时中断，
        # 必须由后台线程读行入队，消费侧才能带 deadline 取行（防 adb 卡死永久阻塞采集线程）
        self._lines: "queue.Queue[str]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None

    def _reader_loop(self, proc: subprocess.Popen) -> None:
        """守护线程：读 signsvc stdout 入队；管道 EOF 时压入哨兵并退出。"""
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            self._lines.put(raw.decode(errors="replace"))
        self._lines.put("__EOF__")

    def _ensure_ready(self) -> subprocess.Popen:
        with self._lock:
            if self._proc is not None:
                return self._proc
            proc = subprocess.Popen(
                [self._adb, "-s", self._device, "shell", self._shell_cmd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self._lines = queue.Queue()  # 重建即重置（旧队列可能残留 EOF 哨兵）
            self._reader = threading.Thread(target=self._reader_loop, args=(proc,), daemon=True)
            self._reader.start()
            deadline = time.time() + self._ready_timeout
            while time.time() < deadline:
                try:
                    line = self._lines.get(timeout=1.0).strip()
                except queue.Empty:
                    if proc.poll() is not None:
                        raise SignSvcError("signsvc exited before READY")
                    continue
                if line == "READY":
                    self._proc = proc
                    return proc
                if line == "__EOF__":
                    raise SignSvcError("signsvc exited before READY")
            raise SignSvcError("signsvc READY timeout")

    def _cmd(self, q: str) -> str:
        for attempt in range(2):
            try:
                proc = self._ensure_ready()
                assert proc.stdin is not None
                proc.stdin.write((q + "\n").encode())
                proc.stdin.flush()
                deadline = time.time() + 15.0
                while time.time() < deadline:
                    try:
                        line = self._lines.get(timeout=1.0).strip()
                    except queue.Empty:
                        if proc.poll() is not None:
                            raise OSError("signsvc EOF (process exited)")
                        continue  # 本秒无输出，等下一轮（deadline 兑现）
                    if line == "__EOF__":
                        raise OSError("signsvc EOF (pipe closed)")
                    if line.startswith(("RESH", "RES ", "ERR")):
                        return line
                    # MARK 等杂音跳过
            except Exception:
                if attempt == 1:
                    raise SignSvcError(f"signsvc pipe broken: {q[:12]}…")
                # 重建进程后重试一次
                with self._lock:
                    try:
                        if self._proc is not None:
                            self._proc.kill()
                    except Exception:
                        pass
                    self._proc = None
        raise SignSvcError("unreachable")

    def enc(self, plain: bytes) -> Optional[bytes]:
        line = self._cmd("ENC|" + plain.hex())
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return bytes.fromhex(hx.strip())
        return None

    def dec(self, cipher_hex: str) -> Optional[bytes]:
        line = self._cmd("DEC|" + cipher_hex)
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return bytes.fromhex(hx.strip())
        return None

    def wbe(self, challenge: str, device_id: str, conn_type: str, cur_time: str) -> Optional[str]:
        line = self._cmd(f"WBE|{challenge}|{device_id}|{conn_type}|{cur_time}")
        if line.startswith("RESH "):
            _, _, hx = line.split(" ", 2)
            return hx.strip()
        return None

    def exec(self, challenge: str, d: int) -> Optional[int]:
        """EXEC|<挑战串>|<d> → RES <int>（261 反作弊轮答案，白盒 execEncryptedHex）。

        signsvc 的 RES 行直接是 int；`RES <Long.MIN_VALUE>` 由调用方按失败处理（App 同款）。
        """
        line = self._cmd(f"EXEC|{challenge}|{int(d)}")
        if line.startswith("RES "):
            try:
                return int(line[4:].strip())
            except ValueError:
                return None
        return None

    def close(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None


class KplEvent(dict):
    """结构化事件：type ∈ auth/sub/push/error/status；全部可 JSON 序列化。"""


# 3004/3101 RealtimeLHB 事件名（ServiceHqList 族，Resp 与 daban 同构但族属不同）
LHB_EVENT_NAMES: Dict[int, str] = {
    lhb.CMD_REALTIME_LHB_SUB: "realtime_lhb",
    lhb.CMD_REALTIME_LHB_RANGE: "realtime_lhb",
}


# 个股详情四通道（2026-11-11 ④，mock 全绿；实弹开火另走预登记）事件名与落库 lane 映射
DETAIL_EVENT_NAMES: Dict[int, str] = {
    proto.CMD_STOCK_RELATED_PLATE: "stock_related_plate",
    proto.CMD_STOCK_ZT_BIG_ORDER: "stock_zt_big_order",
    proto.CMD_ABNORMAL_PRICE: "abnormal_price",
    proto.CMD_BF_REASON: "bf_reason",
}

DETAIL_LANE_BY_CMD: Dict[int, str] = {
    proto.CMD_STOCK_RELATED_PLATE: "rplate",
    proto.CMD_STOCK_ZT_BIG_ORDER: "bdo",
    proto.CMD_ABNORMAL_PRICE: "abn",
    proto.CMD_BF_REASON: "bf",
}

# 解析器映射（kpl_socket_protocol 详情四通道，字段合同见各 parse docstring）
DETAIL_PARSERS: Dict[int, Any] = {
    proto.CMD_STOCK_RELATED_PLATE: proto.parse_stock_related_plate_resp,
    proto.CMD_STOCK_ZT_BIG_ORDER: proto.parse_stock_zt_big_order_resp,
    proto.CMD_ABNORMAL_PRICE: proto.parse_abnormal_price_resp,
    proto.CMD_BF_REASON: proto.parse_bf_reason_resp,
}

DABAN_EVENT_NAMES: Dict[int, str] = {
    daban.CMD_ZD_STAT: "zd_stat",
    daban.CMD_MARKET_OVERVIEW: "market_overview",
    daban.CMD_PLATE_STRENGTH: "plate_strength",
    daban.CMD_WEIGHT_PERF_V2: "weight_perf",
    daban.CMD_ZT_SITUATION_V2: "zt_situation",
    daban.CMD_ZT_STOCK_LIST: "zt_stocks",
    daban.CMD_ZT_STOCK_LIST_PB: "dt_stocks",
    daban.CMD_WIND_VANE: "wind_vane",
    daban.CMD_DABAN_STOCK_LIST: "daban_stocks",
    daban.CMD_DABAN_HEAD: "daban_head",
    daban.CMD_FORECAST_LHB: "lhb_forecast",
}


class KplCollectorService:
    """采集 + 广播服务。start() 后事件进入广播队列，WebSocket 消费者各持游标。"""

    def __init__(
        self,
        codec: Any,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        device_id: str = "",
        user_id: str = "0",
        token: str = "",
        version_name: str = "6.3.20.2",
        channel_id: int = 129,
        conn_type: int = 99,
        api_version: str = "w48",
        stock_ids: Optional[List[str]] = None,
        history: int = 200,
        human_delay: bool = True,
        # auth 相位延迟（2026-11-09 会话抖动根因修复）：§3.4 实证会话时长与 auth 阶段
        # 耗时单调相关——<1s → ~6s 即断（机器人检测）；~1-2s 拟人档 → 15-25s；
        # adb 链路（signsvc 经模拟器逐帧往返）auth 5-8s → 75-160s。pc codec 太快，
        # 原固定 1.2s 停在拟人档（实测 ~23s 会话），2203/2013 订阅爆发未完成即被断。
        # 默认 5.0+U(0,3.0) 对齐 adb 档；env KPL_AUTH_PHASE_DELAY 可覆盖（0=关闭延迟）。
        auth_phase_delay: float = 5.0,
        auth_phase_jitter: float = 3.0,
        daban_subs: bool = True,
        daban_market_type: int = 1,
        daban_list_pids: Optional[Tuple[int, ...]] = (8, 0, 6, 1, 2, 3),
        daban_list_page_size: int = 30,
        daban_list_pages: int = 7,
        daban_lhb: bool = False,
        lhb_realtime: bool = False,
        lhb_realtime_count: int = 120,
        zt_reason_subs: bool = True,
        theme_subs: bool = True,
        stock_detail_subs: bool = False,
        corpus_db_factory: Optional[Any] = None,
        # 2026-11-10 假说判别实验：读循环开始后前 N 秒纯读不发（保活/drain 全部延后），
        # 看杀连时刻落在宽限期内（=setup 打标定时处决）还是宽限期结束时（=循环期发送
        # 触发）。生产经 serve_kpl_socket env KPL_LOOP_SEND_GRACE 传 5；测试传 0。
        loop_send_grace_s: float = 0.0,
        # 2026-11-10 实弹定性（探针 E1-E4）：0x40 通道订阅帧（daban 族/2203/2013）
        # 只允许在 setup 订阅窗口内发送；窗口一关闭，任何后续 0x40 帧 → 服务器回
        # ErrResp 1002 并断连（抓包实锤，WinError 10053/10054 只是 send 撞上关闭）。
        # True = 全部订阅内联回 setup（含 2203/2013 全量），读循环期不再发任何 0x40 帧
        # （会话内新入池成员等下一会话 6g 重建，与既有合同一致）。
        setup_inline_subs: bool = False,
        # 交易时段门控（2026-11-11 防患设备风控累积）：非交易时段不建连，_run_loop
        # 进入 idle_offhours 每分钟复查，下一时段自动恢复。夜间 7×24 TTL 重连的
        # 纯空转连接是风控打标的累积来源，砍掉后日常连接数降一个数量级。
        enforce_trading_hours: bool = True,
        # 详情四通道每 lane 订阅面限量（2026-11-11 探针定案：块发后静默才触发
        # 服务器 flush，块长必须压缩到会话寿命内；env KPL_DETAIL_MAX_STOCKS）
        stock_detail_max_stocks: int = 15,
    ):
        self._codec = codec
        self._host = host
        self._port = port
        self._device_id = device_id
        self._user_id = user_id
        self._token = token
        self._version_name = version_name
        self._channel_id = channel_id
        self._conn_type = conn_type
        self._api_version = api_version
        # 拟人延迟开关（服务器对 <1s 完成认证的连接 ~6s 即断连；pytest 置 False）
        self._human_delay = human_delay
        self._auth_phase_delay = max(0.0, float(auth_phase_delay))
        self._auth_phase_jitter = max(0.0, float(auth_phase_jitter))
        self._loop_send_grace_s = max(0.0, float(loop_send_grace_s))
        # drain 帧间停顿（实验旋钮：降速到 App 逐股节奏时调大）；610 重发开关
        # （App 每连接仅认证一次，重发认证帧是异常指纹候选，实验判别用）
        self._drain_pause = (0.3, 0.15)
        self._ka_610 = True
        self._setup_inline_subs = bool(setup_inline_subs)
        self._stock_detail_max_stocks = max(1, int(stock_detail_max_stocks))
        self._DETAIL_BLOCK_MAX_STOCKS = self._stock_detail_max_stocks
        self._short_session_streak = 0   # 重连螺旋防线：连续短命会话连击数（<60s 计连击）
        self._enforce_trading_hours = bool(enforce_trading_hours)
        # 打板/情绪订阅（0x40 通道 21xx 号段）；market_type 对应 app MoodPresenterImpl 的 l（市场类型）
        self._daban_subs = daban_subs
        self._daban_market_type = daban_market_type
        # 2103 打板个股列表页签（8=集合竞价 0=即将涨停 6=风向标 1=涨停 2=炸板 3=跌停，
        # kpl_daban_protocol.DABAN_LIST_PIDS；2026-11-08 增补炸板/跌停，历史存档同入
        # kpl_daban_pool 日档 zb_/dt_ 前缀通道，不新增数据集）。
        # 2026-10-27 实测（KPL_DEBUG 帧解密核对）：请求 count=200 服务器接受但推送页固定
        # 30 行（Resp.count 恒 30，竞价页 maxSize≈183）——分页只能 index 偏移多页订阅（App
        # 翻页同款），每页一帧订阅、按 Resp.index 合并成全量快照。
        self._daban_list_pids = tuple(daban_list_pids or ())
        self._daban_list_page_size = daban_list_page_size
        self._daban_list_pages = daban_list_pages
        # 2112 会不会上龙虎榜预测订阅（2026-10-29 逆向 LhbWillStockModel 基线：count=30/
        # sortType=1/quotaType=0；0x40 通道同 daban 家族，默认关，开火验证后决定默认值）
        self._daban_lhb = bool(daban_lhb)
        # 3004/3101 RealtimeLHB 实时龙虎榜选股（ServiceHqList 族，App 基线 quotaType=6/
        # sortType=1/limitType=4/bjsType=1；默认关，独立于 daban_subs/daban_lhb）
        # count 采集放宽：App 原 UI count=1 → 2026-10-29 放宽 30 → 2026-10-30 用户裁决
        # 放宽 120（实际上榜全名单 ~83 只需一次拉全；服务器若设上限会在开火验证中暴露）
        self._lhb_realtime = bool(lhb_realtime)
        self._lhb_realtime_count = max(1, int(lhb_realtime_count))
        # 2203 个股涨停原因推送试点（2026-11-08 用户裁决）：订阅面=涨停池（2103 pid=1）
        # 快照成员，随页帧自动跟随新增成员；无退订（涨停池成员日内增量小，残留订阅代价
        # =服务器周期重推，读口按需取用；边界记录于 stock-detail-sources 文档 §四）。
        # 请求 Hq.HQReq{f1 stockId}（App 同款，StockQuotationInfoPresenter 3470-3530）。
        self._zt_reason_subs = bool(zt_reason_subs)
        self._zt_reason_snap: Dict[str, Dict[str, Any]] = {}   # stock_id → 推送解析 + ts
        self._zt_reason_subscribed: set = set()
        self._pending_zt_reason: List[str] = []
        self._sock_dead = False   # 会话内 drain 失败门禁（_session 每会话复位）
        # 2026-11-10 重排：daban 家族（21xx/2103/2112/3004/3101）不再在 setup 内联发送，
        # 改为入队由读循环限流续发（_drain_setup_subs）——见 _session 6c 注释
        self._pending_setup_frames: List[Dict[str, Any]] = []
        self._zt_reason_lock = threading.Lock()
        # 2013 个股题材库热度推送（2026-11-08 题材龙头语料第 2 项）：与 2203 完全同款
        # 模式——订阅面=涨停池（2103 pid=1）成员自动跟随、无退订、每会话重建订阅
        # （服务器 TTL 同源）；请求 Hq.HQReq{f1 stockId}，number=题材热度（float）。
        self._theme_subs = bool(theme_subs)
        self._theme_snap: Dict[str, Dict[str, Any]] = {}   # stock_id → {stock_id, themes, ts}
        self._theme_subscribed: set = set()
        self._pending_theme: List[str] = []
        self._theme_lock = threading.Lock()
        # 个股详情四通道订阅（2026-11-11 ④，2014/2202/2030/2010）：与 2203/2013 完全同款
        # 模式（订阅面=涨停池成员自动跟随、无退订、每会话重建订阅）。**默认关**——本轮
        # 只到 mock 全绿，实弹开火另走预登记 + 频控预算确认（AGENTS §1.2-9）：帧数上限
        # =涨停池成员数×4/会话（每通道每股一帧），drain 限速沿 2203/2013 现值（每 tick
        # 总预算 4 帧、帧间拟人停顿），status 经 corpus_persist 计数 fail-visible。
        self._stock_detail_subs = bool(stock_detail_subs)
        self._detail_lane_cmds: Dict[str, int] = {
            "rplate": proto.CMD_STOCK_RELATED_PLATE,     # 所属板块（Hq.HQReq）
            "bdo": proto.CMD_STOCK_ZT_BIG_ORDER,         # 封板大单（ZTBigOrderDetailReq）
            "bf": proto.CMD_BF_REASON,                   # 爆发原因（Hq.HQReq）
            "abn": proto.CMD_ABNORMAL_PRICE,             # 异动提醒（AbnormalPriceReq）
        }
        self._detail_snaps: Dict[str, Dict[str, Dict[str, Any]]] = {
            k: {} for k in self._detail_lane_cmds}
        self._detail_subscribed: Dict[str, set] = {k: set() for k in self._detail_lane_cmds}
        self._pending_detail: Dict[str, List[str]] = {k: [] for k in self._detail_lane_cmds}
        self._detail_locks: Dict[str, threading.Lock] = {
            k: threading.Lock() for k in self._detail_lane_cmds}
        # 推送即落库（2026-11-10 用户裁决，与直播文本同款时点）：2013/2203 推送解析成功
        # 后立即写 kpl_daban_pool 日档（不再等 ：8000 archiver 盘后轮询拉快照）。
        # corpus_db_factory 可注入（pytest 用假库）；默认 storage_backend=mongodb 时才
        # 启用真实落库，其它后端结构化跳过（fail-visible，不静默）。
        self._corpus_db_factory = corpus_db_factory
        self._corpus_persist_stats: Dict[str, Any] = {
            "theme_ok": 0, "theme_fail": 0, "reason_ok": 0, "reason_fail": 0,
            # 2026-11-11 ③/④：2112/3004/3101 落库计数 + 个股详情四通道计数（fail-visible）
            "fc_ok": 0, "fc_fail": 0, "rt_ok": 0, "rt_fail": 0,
            "bdo_ok": 0, "bdo_fail": 0, "bf_ok": 0, "bf_fail": 0,
            "abn_ok": 0, "abn_fail": 0, "rplate_ok": 0, "rplate_fail": 0,
            "last_error": ""}
        # 龙虎榜快照缓存（task-4 读口）：2112/3004 均**空帧抑制**（同 2103 规：空 items
        # 不覆盖非空快照，仅刷 ts + last_empty_seen；2112 以 total=0 为语义清空）
        self._lhb_forecast_snap: Optional[Dict[str, Any]] = None
        self._lhb_realtime_snap: Optional[Dict[str, Any]] = None
        self._daban_lists: Dict[int, Dict[int, Dict[str, Any]]] = {}   # pidType → {index: 页快照}
        # 板块(801044/885423) + 个股(000001 平安银行)：3001 同时承载板块与个股行情订阅
        self._stock_ids = stock_ids or ["801044", "885423", "000001"]
        self._sub_prio_all: List[str] = []   # 优先块成员（分块轮询见 _resplit）
        self._sub_prio: List[List[str]] = []
        self._sub_rest: List[List[str]] = []
        self._resplit()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._subs_lock = threading.Lock()
        self._subs: List[queue.Queue] = []
        self._history = deque(maxlen=history)
        self._status = "idle"
        self._plate_url = ""
        self._plate_version = 0
        self._plate_tree = None      # {板块id: {name/parent/flag/py}}，懒下载快照解析
        self._rx = bytearray()       # 接收缓冲（帧对齐：跨 socket.timeout 保留残帧，新会话清零）
        self._last_error = ""
        self._session_no = 0
        self._stats = {"sessions": 0, "pushes": 0, "errors": 0, "started_at": 0.0,
                       "last_setup_s": 0.0, "last_session_s": 0.0,
                       "anti_cheat_rounds": 0}

    # ---- 公共 API ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._stats["started_at"] = time.time()
        self._thread = threading.Thread(target=self._run_loop, name="kpl-collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get_plate_tree(self) -> Dict[str, Any]:
        """板块树读口（二级目录映射）：2301 快照懒下载+解析，version 变化才重新拉取。"""
        if not self._plate_url:
            return {"ok": False, "degraded": True,
                    "reason": "plate_url 尚未捕获（等待下一个会话的 2301 应答）",
                    "sessions": self._stats["sessions"]}
        if self._plate_tree is not None and self._plate_version == self._plate_tree.get("version"):
            return {"ok": True, "version": self._plate_version, "tree": self._plate_tree}
        import urllib.request
        req = urllib.request.Request(self._plate_url, headers={"User-Agent": "ad"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        tree = proto.parse_plate_snapshot(data)
        self._plate_tree = {"version": self._plate_version, "plates": tree}
        return {"ok": True, "version": self._plate_version, "tree": self._plate_tree}

    @staticmethod
    def _jsonable(obj: Any) -> Any:
        """递归净化为 JSON 可序列化载荷（读口兑底防线，2026-11-11）。

        bytes → utf-8 解码（失败 errors='replace'）；其余原样。背景：2103 f21
        packed indexes 原始 bytes 透传曾致读口 500 → :8000 代理降级
        kpl_upstream_unavailable、前端「即将涨停」页空。解析器层已修
        （_decode_packed_varints），此兑底保证任何未来漏网 bytes 不再 500。"""
        if isinstance(obj, (bytes, bytearray)):
            return bytes(obj).decode("utf-8", "replace")
        if isinstance(obj, dict):
            return {k: KplCollectorService._jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [KplCollectorService._jsonable(v) for v in obj]
        return obj

    def get_daban_list(self, pid_type: int) -> Dict[str, Any]:
        """2103 打板个股列表快照读口：按 index 合并已收到的推送页（跨页拼接成全量）。

        fail-visible：尚无任何页（采集未运行/页签未订阅/非法 pid_type）返回结构化降级
        载荷，不伪装成空列表。页缺口（如第 3 页未到流）在 pages_missing 里显式暴露。
        """
        try:
            key = int(pid_type)
        except (TypeError, ValueError):
            key = -1
        pages = self._daban_lists.get(key) or {}
        if not pages:
            return {"ok": False, "degraded": True,
                    "reason": "no_daban_list_snapshot",
                    "note": f"尚无 2103 快照（pid_type={pid_type}；订阅页签={list(self._daban_list_pids)}）",
                    "pid_type": pid_type, "running": self.is_running()}
        ordered = [pages[i] for i in sorted(pages)]
        items: List[Dict[str, Any]] = []
        for p in ordered:
            items.extend(p.get("items") or [])
        max_size = next((p.get("max_size") for p in ordered if p.get("max_size") is not None), 0)
        page_size = max(self._daban_list_page_size, 1)
        expected_pages = max(1, -(-int(max_size or 0) // page_size))
        present = {i // page_size for i in pages if isinstance(i, int) and i >= 0}
        latest = max(p.get("ts", 0.0) for p in ordered)
        # 页级元数据全量透出（order_type/sort_type/index/count/indexes），供存档层
        # 全字段落库（2026-11-07 涨停池全量存档要求）；items 内含完整 quotas×28 原始数组。
        pages_meta = [
            {k: p.get(k) for k in ("index", "count", "order_type", "sort_type",
                                    "indexes", "max_size", "date", "raw_len", "ts")}
            for p in ordered
        ]
        return self._jsonable({
            "ok": True, "pid_type": key, "items": items,
            "max_size": max_size, "date": ordered[-1].get("date", ""),
            "pages": len(pages), "pages_expected": expected_pages,
            "pages_missing": sorted(set(range(expected_pages)) - present),
            "pages_meta": pages_meta,
            "ts": latest, "raw_len": sum(p.get("raw_len", 0) for p in ordered),
        })

    def get_lhb_forecast(self) -> Dict[str, Any]:
        """2112 会不会上龙虎榜预测快照读口（task-4）。

        fail-visible：无快照（未开 daban_lhb/未收到帧）返回结构化降级载荷，
        不伪装空列表。09:35 前服务器回 total=0 属正常时段态（非降级）。
        """
        snap = self._lhb_forecast_snap
        if not snap:
            return {"ok": False, "degraded": True, "reason": "no_lhb_forecast_snapshot",
                    "note": f"尚无 2112 快照（daban_lhb={'on' if self._daban_lhb else 'off'}）",
                    "running": self.is_running()}
        return {"ok": True, **snap}

    def get_zt_reasons(self) -> Dict[str, Any]:
        """2203 涨停原因快照读口（试点）：{stock_id → 推送解析详情}。

        fail-visible：无快照（未开订阅/未到流）结构化降级，不伪装空表。
        订阅面=涨停池（2103 pid=1）成员，详情/梯队/题材字段见
        parse_hq_reasons_resp（proto 反编译合同）。
        快照时效由条目内推送 ts 自证（采集进程重启后自然清零；跨日残留
        由次日重启消除，属已知边界）。"""
        with self._zt_reason_lock:
            snap = {k: dict(v) for k, v in self._zt_reason_snap.items()}
            n_sub = len(self._zt_reason_subscribed)
        if not snap:
            return {"ok": False, "degraded": True, "reason": "no_zt_reason_snapshot",
                    "note": ("2203 订阅开关未开启（KPL_ZT_REASON_SUBS=0）"
                             if not self._zt_reason_subs else
                             "尚无 2203 快照（需当日盘中运行，订阅面=涨停池成员，进池后数秒内到流）"),
                    "running": self.is_running()}
        return {"ok": True,
                "reasons": snap,
                "count": len(snap),
                "ts": max(v.get("ts", 0) for v in snap.values()),
                "subscribed": n_sub}

    def get_theme_heat(self) -> Dict[str, Any]:
        """2013 题材库热度快照读口：{stock_id → {stock_id, themes[], ts}}。

        fail-visible：无快照结构化降级（与 2203 同款），不伪装空表。
        themes = parse_stock_related_theme_resp.items（id/name/number=题材热度）。
        """
        with self._theme_lock:
            snap = {k: {**v, "themes": list(v.get("themes") or [])}
                    for k, v in self._theme_snap.items()}
            n_sub = len(self._theme_subscribed)
        if not snap:
            return {"ok": False, "degraded": True, "reason": "no_theme_snapshot",
                    "note": ("2013 订阅开关未开启（KPL_THEME_SUBS=0）"
                             if not self._theme_subs else
                             "尚无 2013 快照（需当日盘中运行，订阅面=涨停池成员，进池后数秒内到流）"),
                    "running": self.is_running()}
        return {"ok": True,
                "themes": snap,
                "count": len(snap),
                "ts": max(v.get("ts", 0) for v in snap.values()),
                "subscribed": n_sub}

    def _pool_date_for_corpus(self) -> str:
        """推送落库用的交易日：涨停池（2103 pid=1）快照自带的 date 字段。

        无快照/无日期 → ""（调用方跳过本次落库并结构化暴露，不猜日期不错挂）。
        """
        snap = self.get_daban_list(1)
        return str(snap.get("date") or "") if snap.get("ok") else ""

    def _corpus_db(self):
        """落库连接（懒取）；不可用时返 None（fail-visible，不静默）。"""
        if self._corpus_db_factory is not None:
            return self._corpus_db_factory()
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return None   # pytest 进程内未注入假库 → 不落库（测试不碰真库）
        from backend.core.settings import get_settings
        from backend.data.repositories.repository_factory import (
            get_runtime_mongodb_database,
        )
        if get_settings().storage_backend != "mongodb":
            return None
        return get_runtime_mongodb_database()

    def _persist_corpus(self, lane: str, payload: Dict[str, Any]) -> None:
        """单条推送即时落库（线程内同步写，单写者=本采集线程；失败不阻断收流）。

        lane="theme" → archive_theme_corpus；"reason" → archive_reason_corpus；
        2026-11-11 ③扩展："fc" → archive_lhb_forecast（2112），"rt" →
        archive_lhb_realtime（3004/3101）；④扩展："bdo"/"bf"/"abn"/"rplate" →
        archive_stock_detail_corpus（个股详情四通道，订阅默认关）。
        跨日残留/无交易日/空 payload 由归档函数结构化拒绝（不猜不补）。
        """
        from backend.services.kpl_daban_archiver import (
            archive_lhb_forecast,
            archive_lhb_realtime,
            archive_reason_corpus,
            archive_stock_detail_corpus,
            archive_theme_corpus,
        )
        fns = {"theme": archive_theme_corpus, "reason": archive_reason_corpus,
               "fc": archive_lhb_forecast, "rt": archive_lhb_realtime,
               "bdo": lambda db, snap: archive_stock_detail_corpus(db, snap, lane="bdo"),
               "bf": lambda db, snap: archive_stock_detail_corpus(db, snap, lane="bf"),
               "abn": lambda db, snap: archive_stock_detail_corpus(db, snap, lane="abn"),
               "rplate": lambda db, snap: archive_stock_detail_corpus(db, snap, lane="rplate")}
        events = {"theme": "theme_heat_persist", "reason": "zt_reasons_persist",
                  "fc": "lhb_forecast_persist", "rt": "lhb_realtime_persist",
                  "bdo": "stock_detail_persist", "bf": "stock_detail_persist",
                  "abn": "stock_detail_persist", "rplate": "stock_detail_persist"}
        try:
            # 2026-11-11 评审 nit-6：lane 校验入 try（拼错 lane 走 fail 计数不杀会话）
            if lane not in fns:
                raise ValueError(f"unknown corpus lane: {lane}")
            date = self._pool_date_for_corpus()
            if not date:
                raise RuntimeError("no_pool_date")
            db = self._corpus_db()
            if db is None:
                raise RuntimeError("corpus_db_unavailable")
            result = fns[lane](db, {"ok": True, "date": date, **payload})
            if result.get("ok"):
                self._corpus_persist_stats[f"{lane}_ok"] += 1
            else:
                self._corpus_persist_stats[f"{lane}_fail"] += 1
                self._corpus_persist_stats["last_error"] = (
                    f"{lane}:{result.get('reason')}")
            self._emit(KplEvent(type=events[lane],
                                ts=time.time(), date=date,
                                ok=bool(result.get("ok")),
                                reason=str(result.get("reason") or "")))
        except Exception as exc:   # 落库失败绝不阻断收流（fail-visible 进 stats/事件）
            self._corpus_persist_stats[f"{lane}_fail"] = \
                self._corpus_persist_stats.get(f"{lane}_fail", 0) + 1
            self._corpus_persist_stats["last_error"] = f"{lane}:{exc}"
            self._err(f"{lane} push persist failed: {exc}")
            self._emit(KplEvent(type=events.get(lane, "corpus_persist_error"),
                                ts=time.time(), ok=False,
                                reason=f"persist failed: {type(exc).__name__}"))

    def _pool_stock_ids(self) -> List[str]:
        """涨停池（2103 pid=1）合并快照成员 id（跨页去重，保序）。"""
        out: List[str] = []
        for page in (self._daban_lists.get(1) or {}).values():
            for it in (page.get("items") or []):
                sid = str(it.get("stock_id") or "").strip()
                if sid and sid not in out:
                    out.append(sid)
        return out

    def _queue_zt_reason_new(self, stock_ids: List[str]) -> int:
        """新入池成员入队 2203 订阅（去重；会话线程 drain 发送）。"""
        if not self._zt_reason_subs:
            return 0
        new_ids: List[str] = []
        with self._zt_reason_lock:
            for sid in stock_ids:
                sid = str(sid or "").strip()
                if sid and sid not in self._zt_reason_subscribed:
                    self._zt_reason_subscribed.add(sid)
                    new_ids.append(sid)
                    self._pending_zt_reason.append(sid)
        if new_ids:
            self._emit(KplEvent(type="zt_reasons_status", ts=time.time(),
                                note=f"queued {len(new_ids)} new 2203 subscriptions",
                                stock_ids=new_ids))
        return len(new_ids)

    # drain 每 tick 最多发送帧数（2026-11-10 修复 10054 循环）：6g 一次性入队全池成员
    # ×2 通道 ≈170 帧，原实现零停顿一次性全发——爆发=机器指纹（§3.4 机制），服务器
    # 在 setup 刚结束时即 RST，drain sendall 撞死 socket → WinError 10054 每会话循环。
    # 限量+帧间拟人停顿对齐 setup 订阅链已验证安全节奏（0.3+U(0,0.15)s/帧）；余量
    # 回队头由下一收流 tick 续发（保活/读流不被长时间阻塞）。
    _DRAIN_TICK_FRAMES = 8

    def _flush_pending_inline(self, sock: Any, next_seq: Any, lane: str) -> None:
        """2026-11-10 setup_inline_subs 模式：把待发订阅帧在 setup 窗口内一次性
        内联发完（0x40 帧窗口关闭后发送→ErrResp 1002 断连，探针 E1-E4 实锤）。
        逐帧拟人停顿（同款节奏）；OSError 直接上抛交给 _run_loop 重连链（此时
        连接已死，继续 setup 无意义，fail-visible 由 network 错误日志承载）。"""
        if lane == "setup":
            items = list(self._pending_setup_frames)
            self._pending_setup_frames = []
            for it in items:
                enc = self._codec.enc(it["req"])
                # pkg=0x40 订阅路由（2026-11-10 根因修复：daban 族帧此前漏传 pkg，
                # build_frame 默认 0x30 鉴权通道 + ext 路由头=非法帧，服务器杀连）
                frame = proto.build_frame(it["cmd"], next_seq(), enc or it["req"], d=0,
                                          encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=it["ext"])
                self._human_pause(*self._drain_pause)
                self._dbg("C", frame)
                sock.sendall(frame)
            return
        if lane == "detail":
            # 2026-11-11 评审 major-2：setup_inline_subs=True 时详情四通道改 setup
            # 窗口内内联发送（同 2203/2013 的 zt_reason/theme lane；窗口关闭后发送
            # 0x40 帧→ErrResp 1002 断连）。OSError 上抛交 _run_loop 重连链。
            for dl, dcmd in self._detail_lane_cmds.items():
                with self._detail_locks[dl]:
                    batch = list(self._pending_detail[dl])
                    self._pending_detail[dl].clear()
                for sid in batch:
                    req = self._detail_req_for(dcmd, sid)
                    enc = self._codec.enc(req)
                    frame = proto.build_frame(dcmd, next_seq(), enc or req, d=0,
                                              encrypted=bool(enc), pkg=proto.PKG_ROUTE,
                                              ext=bytes([0x02]) + struct.pack(">H", dcmd))
                    self._dbg("C", frame)
                    sock.sendall(frame)
                    self._human_pause(*self._drain_pause)
            return
        lock, pending_ref = ((self._zt_reason_lock, self._pending_zt_reason) if lane == "zt_reason"
                             else (self._theme_lock, self._pending_theme))
        with lock:
            batch = list(pending_ref)
            pending_ref.clear()
        ext = bytes([0x02]) + struct.pack(
            ">H", proto.CMD_HQ_REASONS if lane == "zt_reason" else proto.CMD_STOCK_RELATED_THEME)
        for sid in batch:
            req = proto.build_hq_req_pb(sid)
            enc = self._codec.enc(req)
            cmd = proto.CMD_HQ_REASONS if lane == "zt_reason" else proto.CMD_STOCK_RELATED_THEME
            frame = proto.build_frame(cmd, next_seq(), enc or req, d=0,
                                      encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=ext)
            self._human_pause(*self._drain_pause)
            self._dbg("C", frame)
            sock.sendall(frame)

    def _drain_setup_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待发 setup 订阅帧（daban 家族 21xx/2103/2112/3004/3101，2026-11-10 重排）。

        原 setup 内联串行发完 ~32s 才进读循环，会话在 setup 结束后 ~1s 即被上游
        RST（last_setup_s=31.9 / last_session_s=32.8），3001 推送窗口≈0.9s → 个股
        行情全过期。重排后 daban 家族由读循环限流续发（同款 8 帧/tick + 0.3s
        拟人节奏）；sendall 失败置 _sock_dead（同 2203/2013 门禁），未发帧本会话
        丢失，下一会话重建。"""
        if self._sock_dead or self._setup_inline_subs or not self._pending_setup_frames:
            return   # setup_inline_subs 模式循环期永久静默（0x40 帧窗口外发送=1002 断连）
        batch = self._pending_setup_frames[:self._DRAIN_TICK_FRAMES]
        self._pending_setup_frames = self._pending_setup_frames[self._DRAIN_TICK_FRAMES:]
        sent = 0
        for item in batch:
            enc = self._codec.enc(item["req"])
            frame = proto.build_frame(item["cmd"], next_seq(), enc or item["req"], d=0,
                                      encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=item["ext"])
            self._dbg("C", frame)
            try:
                if sent:
                    self._human_pause(*self._drain_pause)   # 帧间拟人停顿（节奏实验旋钮）
                sock.sendall(frame)
            except OSError as exc:
                self._sock_dead = True
                dropped = len(batch) - sent + len(self._pending_setup_frames)
                self._stats["setup_send_drops"] = self._stats.get("setup_send_drops", 0) + dropped
                self._err(f"setup subscribe send failed (cmd={item['cmd']}): {exc} "
                          f"(sent={sent} dropped={dropped}, next-session rebuild)")
                self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                    lane="setup", cmd=item["cmd"],
                                    sent=sent, dropped=dropped, session=self._session_no,
                                    error=str(exc)))
                return
            sent += 1
        # 队深观测随 drain 递减（评审 P2：否则 status 读到的是会话初队深非当前队深）
        self._stats["queued_setup_subs"] = len(self._pending_setup_frames)

    def _drain_zt_reason_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待订阅 2203 帧（仅会话线程调用；异常 fail-visible 不杀会话）。

        2026-11-10 修复：限流+拟人停顿（见 _DRAIN_TICK_FRAMES 注释）；sendall 失败
        → 置 _sock_dead 本会话后续 drain 静默跳过（死 socket 重试只会刷错误），
        未发帧本会话丢失，下一会话 6g 全量补订自愈（2026-11-08 评审 P2 不变）。"""
        if not self._zt_reason_subs or self._sock_dead or self._setup_inline_subs:
            return   # 2026-11-10 时序竞争修复：不再让路 daban 页队列（2203 优先，见读循环注释）
        with self._zt_reason_lock:
            pending = list(self._pending_zt_reason)
            self._pending_zt_reason = []
        if not pending:
            return
        batch, rest = pending[:self._DRAIN_TICK_FRAMES], pending[self._DRAIN_TICK_FRAMES:]
        if rest:
            with self._zt_reason_lock:
                self._pending_zt_reason[:0] = rest   # 回队头保序，下一 tick 续发
        ext = bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_REASONS)
        sent = 0
        for sid in batch:
            req = proto.build_hq_req_pb(sid)
            enc = self._codec.enc(req)
            frame = proto.build_frame(proto.CMD_HQ_REASONS, next_seq(), enc or req,
                                      d=0, encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=ext)
            self._dbg("C", frame)
            try:
                if sent:
                    self._human_pause(*self._drain_pause)   # 帧间拟人停顿（节奏实验旋钮）
                sock.sendall(frame)
            except OSError as exc:
                self._sock_dead = True
                dropped = len(batch) - sent + len(rest)
                self._stats["zt_reason_send_drops"] = self._stats.get("zt_reason_send_drops", 0) + dropped
                self._err(f"2203 subscribe send failed ({sid}): {exc} "
                          f"(sent={sent} dropped={dropped}, next-session 6g resubscribe)")
                self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                    lane="zt_reason", cmd=proto.CMD_HQ_REASONS,
                                    sent=sent, dropped=dropped, session=self._session_no,
                                    error=str(exc)))
                return
            sent += 1

    def _queue_detail_new(self, stock_ids: List[str]) -> int:
        """四通道新入池成员入队订阅（去重；会话线程 drain 块发）。开关关 → 零动作。

        每 lane 限量 _DETAIL_BLOCK_MAX_STOCKS（2026-11-11 探针定案：块长必须压缩
        到会话寿命内，且块后静默才能触发服务器 flush）：超限成员不入队（
        _detail_subscribed 也不占用名额位，下一会话按池序重选）。"""
        if not self._stock_detail_subs:
            return 0
        queued = 0
        for lane in self._detail_lane_cmds:
            new_ids: List[str] = []
            with self._detail_locks[lane]:
                for sid in stock_ids:
                    sid = str(sid or "").strip()
                    if not sid or sid in self._detail_subscribed[lane]:
                        continue
                    if len(self._detail_subscribed[lane]) >= self._DETAIL_BLOCK_MAX_STOCKS:
                        break
                    self._detail_subscribed[lane].add(sid)
                    self._pending_detail[lane].append(sid)
                    new_ids.append(sid)
            if new_ids:
                queued += len(new_ids)
                self._emit(KplEvent(type="detail_subs_status", ts=time.time(),
                                    lane=lane, note=f"queued {len(new_ids)} new subscriptions",
                                    stock_ids=new_ids))
        return queued

    def _queue_theme_new(self, stock_ids: List[str]) -> int:
        """新入池成员入队 2013 订阅（与 2203 同款去重；会话线程 drain 发送）。"""
        if not self._theme_subs:
            return 0
        new_ids: List[str] = []
        with self._theme_lock:
            for sid in stock_ids:
                sid = str(sid or "").strip()
                if sid and sid not in self._theme_subscribed:
                    self._theme_subscribed.add(sid)
                    new_ids.append(sid)
                    self._pending_theme.append(sid)
        if new_ids:
            self._emit(KplEvent(type="theme_heat_status", ts=time.time(),
                                note=f"queued {len(new_ids)} new 2013 subscriptions",
                                stock_ids=new_ids))
        return len(new_ids)

    def _drain_theme_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待订阅 2013 帧（与 _drain_zt_reason_subs 同款限流/拟人/失败门禁：
        send 失败置 _sock_dead 静默，未发帧下一会话 6g 全量补订自愈）。"""
        if not self._theme_subs or self._sock_dead or self._setup_inline_subs:
            return   # 同 2203：不再让路 daban 页队列（2013 优先）
        with self._theme_lock:
            pending = list(self._pending_theme)
            self._pending_theme = []
        if not pending:
            return
        batch, rest = pending[:self._DRAIN_TICK_FRAMES], pending[self._DRAIN_TICK_FRAMES:]
        if rest:
            with self._theme_lock:
                self._pending_theme[:0] = rest
        ext = bytes([0x02]) + struct.pack(">H", proto.CMD_STOCK_RELATED_THEME)
        sent = 0
        for sid in batch:
            req = proto.build_hq_req_pb(sid)
            enc = self._codec.enc(req)
            frame = proto.build_frame(proto.CMD_STOCK_RELATED_THEME, next_seq(), enc or req,
                                      d=0, encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=ext)
            self._dbg("C", frame)
            try:
                if sent:
                    self._human_pause(0.3, 0.15)
                sock.sendall(frame)
            except OSError as exc:
                self._sock_dead = True
                dropped = len(batch) - sent + len(rest)
                self._stats["theme_send_drops"] = self._stats.get("theme_send_drops", 0) + dropped
                self._err(f"2013 subscribe send failed ({sid}): {exc} "
                          f"(sent={sent} dropped={dropped}, next-session 6g resubscribe)")
                self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                    lane="theme", cmd=proto.CMD_STOCK_RELATED_THEME,
                                    sent=sent, dropped=dropped, session=self._session_no,
                                    error=str(exc)))
                return
            sent += 1

    # 详情四通道发送语义（2026-11-11 探针 K1/K3/I1 定案）：服务器对 detail 订阅的
    # 响应是「静默期 flush」——订阅帧连续发送期间零响应，发送停止后 <1s 内全量
    # 批回（K1：10 帧块停发后 0.3s 即回 19 帧；K3：124 帧连发 50s 后 0.1s 内
    # 批回 142 帧；I1/生产 drain 每 tick 4 帧细水长流，tick 间 ~7-9s 间隙不足以
    # 触发 flush → 会话全程零响应）。因此：① drain 改整队列块发（一次调用发完
    # pending，随后读循环自然静默 → flush）；② 订阅面限量 _DETAIL_BLOCK_MAX_STOCKS
    # （默认 15 只/lane，60 帧×0.375s≈22s 块长，50s 短命会话内也能完成 flush；
    # env KPL_DETAIL_MAX_STOCKS 可调，未订阅成员下一会话重建时按池序重选）。
    _DETAIL_BLOCK_MAX_STOCKS = 15   # 类属性默认；实例覆盖见 __init__（env 可调）

    @staticmethod
    def _detail_req_for(cmd: int, sid: str) -> bytes:
        """详情四通道订阅 Req 构造（drain/inline flush 共用单一实现）。"""
        if cmd == proto.CMD_STOCK_ZT_BIG_ORDER:
            return proto.build_stock_zt_big_order_req_pb(sid, 0, 0)
        if cmd == proto.CMD_ABNORMAL_PRICE:
            return proto.build_abnormal_price_req_pb(sid)
        return proto.build_hq_req_pb(sid)   # 2010/2202 同 Hq.HQReq{f1 stockId}

    def _drain_detail_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待订阅详情四通道帧。2026-11-11 块发语义（探针 K1/K3/I1 定案的静默期
        flush 合同）：一次调用发完整个 pending 队列（块），随后读循环不再发 detail
        帧（新入池成员的小块同理）→ 服务器静默期触发全量批回。与 _drain_zt_reason_subs
        同款失败门禁：send 失败置 _sock_dead 静默，未发帧下一会话 6g 全量补订自愈。
        setup_inline_subs=True 时本函数永久早退，改由 6h 处 _flush_pending_inline
        在 setup 窗口内内联发送（0x40 帧窗口外发送=ErrResp 1002 断连，探针 E1-E4）。"""
        if not self._stock_detail_subs or self._sock_dead or self._setup_inline_subs:
            return
        for lane, cmd in self._detail_lane_cmds.items():
            with self._detail_locks[lane]:
                batch = list(self._pending_detail[lane])
                self._pending_detail[lane] = []
            sent = 0
            for sid in batch:
                req = self._detail_req_for(cmd, sid)
                enc = self._codec.enc(req)
                frame = proto.build_frame(cmd, next_seq(), enc or req, d=0,
                                          encrypted=bool(enc), pkg=proto.PKG_ROUTE,
                                          ext=bytes([0x02]) + struct.pack(">H", cmd))
                self._dbg("C", frame)
                try:
                    sock.sendall(frame)
                except OSError as exc:
                    self._sock_dead = True
                    rest = batch[sent:]
                    with self._detail_locks[lane]:
                        self._pending_detail[lane][:0] = rest
                    self._stats["detail_send_drops"] = \
                        self._stats.get("detail_send_drops", 0) + len(rest)
                    self._err(f"detail {lane} subscribe send failed ({sid}): {exc} "
                              f"(sent={sent} dropped={len(rest)}, next-session 6g resubscribe)")
                    self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                        lane=lane, cmd=cmd, sent=sent,
                                        dropped=len(rest), session=self._session_no,
                                        error=str(exc)))
                    return
                sent += 1
                self._human_pause(0.3, 0.15)

    def get_lhb_realtime(self) -> Dict[str, Any]:
        """3004/3101 RealtimeLHB 快照读口（task-4）：空帧抑制后最新非空帧。

        fail-visible：无快照（未开 lhb_realtime/未收到帧）返回结构化降级载荷。
        """
        snap = self._lhb_realtime_snap
        if not snap:
            return {"ok": False, "degraded": True, "reason": "no_lhb_realtime_snapshot",
                    "note": f"尚无 3004 快照（lhb_realtime={'on' if self._lhb_realtime else 'off'}）",
                    "running": self.is_running()}
        return {"ok": True, **snap}

    _CHUNK = 200  # 3001 单请求 id 上限（实测 241 可、784 → ErrResp 1106 连接错误）

    @staticmethod
    def _chunks(lst: List[str], size: Optional[int] = None):
        size = size or KplCollectorService._CHUNK
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    def _resplit(self) -> None:
        """按优先块/普通块切分订阅清单（订阅帧与保活轮询都按块发）。"""
        prio_set = set(self._sub_prio_all)
        self._sub_prio = list(self._chunks([i for i in self._stock_ids if i in prio_set]))
        self._sub_rest = list(self._chunks([i for i in self._stock_ids if i not in prio_set]))
        if not self._sub_prio:   # 无优先块时全部视为优先（保持旧行为：一清单轮询）
            self._sub_prio = list(self._chunks(list(self._stock_ids)))
            self._sub_rest = []

    def set_subscriptions(self, stock_ids: List[str], priority_ids: Optional[List[str]] = None,
                          merge: bool = False) -> Dict[str, Any]:
        """动态更新订阅清单（下一个 3001 构造即生效，轮询间隔 ~2s）。

        priority_ids：优先块（顶级板块等高频行情），轮询时与普通块交替发——
        单请求 id 数超 ~241 会被服务器 1106 拒绝（2026-10-27 实测），故分块。
        merge=True（2026-11-11 行业页签补引导）：与现有清单求并（保序去重）而非替换——
        多页签共享订阅面，替换语义会抹掉别页已订个股；默认 False 保持旧合同。
        fail-visible：空清单拒绝（保留现有订阅），变更结构化返回供调用方透出。
        """
        ids = [str(s).strip() for s in (stock_ids or []) if str(s).strip()]
        if not ids:
            return {"ok": False, "reason": "empty stock_ids rejected", "count": len(self._stock_ids)}
        prio = [str(s).strip() for s in (priority_ids or []) if str(s).strip()]
        if merge:
            old = list(self._stock_ids)
            old_set = set(old)
            ids = old + [i for i in ids if i not in old_set]
            old_prio = list(self._sub_prio_all)
            old_prio_set = set(old_prio)
            prio = old_prio + [p for p in prio if p not in old_prio_set]
        self._stock_ids = ids
        self._sub_prio_all = prio
        self._resplit()
        return {"ok": True, "count": len(ids),
                "chunks": len(self._sub_prio) + len(self._sub_rest),
                "running": self.is_running()}

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        return {
            "status": self._status,
            "last_error": self._last_error,
            "sessions": self._stats["sessions"],
            "pushes": self._stats["pushes"],
            "errors": self._stats["errors"],
            "zt_reasons": len(self._zt_reason_snap),
            "theme_heat": len(self._theme_snap),
            "zt_reasons_subscribed": len(self._zt_reason_subscribed),
            # 开关位观测（2026-11-11 ④）：详情四通道订阅是否开启 + 各 lane 待发/已订计数
            "stock_detail_subs": self._stock_detail_subs,
            "stock_detail_pending": {lane: len(self._pending_detail[lane])
                                     for lane in self._detail_lane_cmds},
            "stock_detail_subscribed": {lane: len(self._detail_subscribed[lane])
                                        for lane in self._detail_lane_cmds},
            "stock_detail_snaps": {lane: len(self._detail_snaps[lane])
                                   for lane in self._detail_snaps},
            "stock_detail_cap": self._DETAIL_BLOCK_MAX_STOCKS,
            # 订阅构成观测（2026-11-11 行业页签空态排查）：hy=881 行业板块数，
            # 页面引导/补引导是否落地一眼可核（fail-visible，不藏状态）
            "subscriptions": {
                "count": len(self._stock_ids),
                "priority": len(self._sub_prio_all),
                "hy": sum(1 for i in self._stock_ids if len(i) == 6 and i.startswith("881")),
                "sectors": sum(1 for i in self._stock_ids
                               if len(i) == 6 and i.startswith("8") and not i.startswith("881")),
                "stocks": sum(1 for i in self._stock_ids
                              if not (len(i) == 6 and i.startswith("8"))),
                "chunks": len(self._sub_prio) + len(self._sub_rest),
            },
            "corpus_persist": dict(self._corpus_persist_stats),
            "anti_cheat_rounds": self._stats.get("anti_cheat_rounds", 0),
            # 会话寿命观测（2026-11-09 抖动根因修复验证）：setup=连接到订阅完成耗时，
            # session=单会话存活时长；§3.4 时长档对照（拟人档 15-25s / adb 档 75-160s）
            "last_setup_s": self._stats.get("last_setup_s", 0.0),
            "last_session_s": self._stats.get("last_session_s", 0.0),
            "auth_phase_delay": self._auth_phase_delay,
            "loop_send_grace_s": self._loop_send_grace_s,
            # 重连螺旋防线观测（2026-11-10）：连续短命会话退避秒数 + 当前连击数
            "reconnect_backoff_s": self._stats.get("reconnect_backoff_s"),
            "short_session_streak": self._short_session_streak,
            # 交易时段门控观测（2026-11-11）：当前是否在交易窗口 + 是否启用门控
            "trading_session": (self._in_trading_session()
                                if self._enforce_trading_hours else True),
            "enforce_trading_hours": self._enforce_trading_hours,
            "uptime_s": round(time.time() - self._stats["started_at"], 1)
            if self._stats["started_at"]
            else 0,
            "running": self.is_running(),
        }

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._subs_lock:
            self._subs.append(q)
            # 新订阅者先回放最近历史（fail-visible：不丢已发生的事件）
            for ev in list(self._history):
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)

    # ---- 内部 ----

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, dict):
            return {k: KplCollectorService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [KplCollectorService._json_safe(v) for v in value]
        return value

    def _emit(self, event: KplEvent) -> None:
        event = KplCollectorService._json_safe(dict(event))
        self._history.append(event)
        with self._subs_lock:
            dead = []
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                # 溢出移除前先尽力塞一条降级事件，避免前端连接看似健康但数据已停
                try:
                    q.put_nowait({"type": "error", "ts": time.time(),
                                  "msg": "subscriber queue overflow, re-subscribe required"})
                except queue.Full:
                    pass
                self._subs.remove(q)

    def _err(self, msg: str, **extra: Any) -> None:
        self._last_error = msg
        self._stats["errors"] += 1
        self._emit(KplEvent(type="error", ts=time.time(), msg=msg, **extra))

    def _tls_connect(self) -> Optional[ssl.SSLSocket]:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            ctx.set_ciphers("ECDHE-RSA-AES128-GCM-SHA256")
        except Exception:
            pass
        # 客户端证书：服务器要求 mTLS（缺证书 → sslv3 alert handshake failure）
        cert = Path(os.environ.get(
            "KPL_CLIENT_CERT", r"D:/dragon-board/.tmp_review/client_cert.pem"))
        key = Path(os.environ.get(
            "KPL_CLIENT_KEY", r"D:/dragon-board/.tmp_review/client_key.pem"))
        if cert.exists() and key.exists():
            ctx.load_cert_chain(str(cert), str(key))
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((self._host, self._port), timeout=15)
        return ctx.wrap_socket(raw, server_hostname=TLS_SNI)

    def _read_frame(self, sock: ssl.SSLSocket) -> Optional[Dict[str, Any]]:
        """帧对齐读：超时可能发生在帧中途（头已读、体未齐）——无缓冲恢复会让流
        错位（后续帧长解析成天文数字，"frame too large" 的根因），必须把残帧状态
        存在 self._rx 里跨超时续读。对端关闭返回 None；帧长护栏异常照抛。"""
        buf = self._rx
        while True:
            if len(buf) >= 5:
                pkg = buf[0]
                ln = int.from_bytes(buf[1:5], "big")
                if ln > 8 * 1024 * 1024:
                    raise proto.FrameDecodeError(f"frame too large: {ln}B")
                if len(buf) >= 5 + ln:
                    frame = bytes(buf[:5 + ln])
                    del buf[:5 + ln]
                    if os.environ.get("KPL_DEBUG"):
                        with open(os.environ["KPL_DEBUG"], "a") as f:
                            f.write(f"S {int(time.time())} {frame.hex()}" + '\n')
                    return proto.parse_incoming(frame)
            c = sock.recv(65536)
            if not c:
                return None
            buf.extend(c)

    def _read_frame_tolerant(self, sock, deadline: float):
        """读帧容忍 socket.timeout：握手期服务器静默数秒属正常，超时继续等至 deadline。

        返回：帧 / None（对端关闭）/ "timeout"（deadline 到，由调用方走超时错误路径）。
        """
        while time.time() < deadline:
            try:
                return self._read_frame(sock)
            except socket.timeout:
                continue
        return "timeout"

    def _in_trading_session(self, ts: Optional[float] = None) -> bool:
        """A 股交易时段判断（2026-11-11 交易时段门控）。

        窗口：09:15（含集合竞价）-11:30、13:00-15:35（下午收盘 15:30——交易所规则
        调整，用户口径 2026-11-11；收盘后 5min 缓冲收尾盘推送）。
        周末不采集；法定节假日不识别（节假日会空转重连——与旧行为一致，不倒退；
        如需节假日静默由上层手动 stop）。ts 参数仅供测试注入（UTC epoch）。
        时区用 Asia/Shanghai（评审 P1：不依赖宿主机 localtime，与
        trading_calendar.TZ_SHANGHAI 同源——:8002 宿主机非 CST 时窗口不错位）。"""
        dt = datetime.datetime.fromtimestamp(ts if ts is not None else time.time(),
                                             tz=TZ_SHANGHAI)
        if dt.weekday() >= 5:   # 周六/周日
            return False
        hm = dt.hour * 60 + dt.minute
        return (9 * 60 + 15 <= hm < 11 * 60 + 30) or (13 * 60 <= hm < 15 * 60 + 35)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            # 交易时段门控：非交易时段不建连（idle_offhours，每分钟复查；
            # 状态与事件均 fail-visible，页面/日志可感知挂起与恢复）
            if self._enforce_trading_hours and not self._in_trading_session():
                if self._status != "idle_offhours":
                    self._status = "idle_offhours"
                    self._emit(KplEvent(type="status", ts=time.time(), status="idle_offhours",
                                        note="非交易时段，采集挂起（不建连；09:15/13:00 自动恢复）"))
                if self._stop.wait(60.0):
                    break
                continue
            if self._status == "idle_offhours":
                self._emit(KplEvent(type="status", ts=time.time(), status="trading_session_start",
                                    note="进入交易时段，采集恢复"))
            self._session_no += 1
            self._stats["sessions"] += 1
            t_session = time.time()
            backoff = 2.0
            try:
                self._session()
            except (ssl.SSLError, OSError, socket.timeout) as exc:
                self._err(f"session#{self._session_no} network: {type(exc).__name__}: {exc}")
            except SignSvcError as exc:
                self._err(f"session#{self._session_no} signsvc: {exc}")
                # signsvc 故障重试间隔拉长
                backoff = 5.0
            except AntiCheatError as exc:
                # 261 无法作答 → 不发假答案，直接断连重建（App 同款行为）；
                # 退避拉长到 5s：若 261 周期性下发，2s 快速重连会刷屏（评审 R1-P2）
                self._err(f"session#{self._session_no} anti_cheat: {exc}")
                backoff = 5.0
            except Exception as exc:  # 未知异常也必须 fail-visible
                self._err(f"session#{self._session_no} unexpected: {type(exc).__name__}: {exc}")
            finally:
                # 会话时长观测（2026-11-09 抖动根因验证）：在重连退避之前记录，否则
                # backoff 会被算进会话时长污染 §3.4 时长档对照（评审 MINOR）
                self._stats["last_session_s"] = round(time.time() - t_session, 1)
            # 重连螺旋防线（2026-11-10 根因复盘）：连续短命会话说明设备已被风控打标
            # 或本端异常，固定 2s 高频重连只会把风险分越拉越高（实弹验证：冷却 3min
            # 后单会话寿命 6s→67.6s）。阈值 60s（健康 TTL 档 75-160s，<60 均视为
            # 不健康——生产实测 50s 会话期若不退避，风控打标停在 ~50s 平台期不衰减）。
            # 指数退避封顶 120s；长命会话归零。
            if self._stats["last_session_s"] < 60.0:
                self._short_session_streak += 1
                backoff = max(backoff, min(2.0 * (2 ** min(self._short_session_streak, 6)), 120.0))
            else:
                self._short_session_streak = 0
            self._stats["reconnect_backoff_s"] = backoff
            if self._stop.is_set():
                break
            self._status = "reconnecting"
            self._stop.wait(backoff)
        self._status = "stopped"

    def _dbg(self, direction: str, data: bytes) -> None:
        if not os.environ.get("KPL_DEBUG"):
            return
        with open(os.environ["KPL_DEBUG"], "a") as f:
            f.write(f"{direction} {int(time.time())} {data.hex()}\n")

    def _human_pause(self, base: float, spread: float = 0.0) -> None:
        """拟人停顿：base+U(0,spread) 非均匀间隔（固定节拍是机器指纹）；
        human_delay=False（pytest）零停顿。auth 相位用大基数，订阅帧用小抖动。"""
        if not self._human_delay:
            return
        time.sleep(base + (random.uniform(0, spread) if spread > 0 else 0.0))

    def _session(self) -> None:
        self._status = "connecting"
        t_setup = time.time()
        seq = [0]  # 会话内递增 seq（重复 seq 会被服务器 110/2000 拒绝并断连）

        def next_seq() -> int:
            seq[0] += 1
            return seq[0]

        sock = self._tls_connect()
        self._rx = bytearray()   # 新会话新流：残帧缓冲必须清零
        self._sock_dead = False  # 新会话新 socket：drain 失败门禁复位
        self._pending_setup_frames = []   # 新会话重建订阅面：上会话残留待发帧作废
        try:
            sock.settimeout(2)
            # 1) 260 challenge
            deadline = time.time() + 15
            challenge = server_time = None
            while time.time() < deadline:
                fr = self._read_frame_tolerant(sock, deadline)
                if fr == "timeout":
                    break   # deadline 到 → 下方 no-challenge 路径接管（会话存活不硬死）
                if fr is None:
                    raise proto.FrameDecodeError("closed before 260")
                if fr["cmd"] == proto.CMD_CHALLENGE:
                    server_time, challenge, _ = proto.parse_challenge_260(fr["payload"])
                    break
            if not challenge:
                self._err("no 260 challenge in 15s")
                return
            self._status = "authenticating"
            # 2) WBE 签名 → 610 AuthReq
            sig_hex = self._codec.wbe(
                challenge, self._device_id, str(self._conn_type), str(server_time)
            )
            if not sig_hex:
                self._err("WBE returned empty signature")
                return
            auth_pb = proto.build_auth_req_pb(
                device_id=self._device_id,
                version_name=self._version_name,
                channel_id=self._channel_id,
                signature_hex=sig_hex,
                user_id=self._user_id,
                token=self._token,
                conn_type=self._conn_type,
                cur_time=int(server_time),
                api_version=self._api_version,
            )
            enc_body = self._codec.enc(auth_pb)
            if not enc_body:
                self._err("ENC failed for AuthReq")
                return
            auth_frame = proto.build_frame(proto.CMD_AUTH, next_seq(), enc_body, d=2, encrypted=True)
            # 拟人延迟（2026-11-09 会话抖动根因修复）：§3.4 实证 auth 阶段耗时与会话
            # 时长单调相关（<1s→~6s 断；~1-2s 拟人档→15-25s；adb 链路 5-8s→75-160s）。
            # pc codec 太快，原固定 1.2s 停在拟人档（实测 ~23s 会话，2203/2013 订阅
            # 爆发未完成即被断）；默认 5.0+U(0,3.0) 对齐 adb 档。
            self._human_pause(self._auth_phase_delay, self._auth_phase_jitter)
            self._dbg("C", auth_frame)
            sock.sendall(auth_frame)
            # 3) 610 ack（加密 AuthResp）
            deadline = time.time() + 15
            auth_ok = False
            while time.time() < deadline:
                fr = self._read_frame_tolerant(sock, deadline)
                if fr == "timeout":
                    break   # deadline 到 → 下方 no-ack 路径接管
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 610 ack")
                if fr["fmt"] == "echo" and fr["cmd"] == proto.CMD_AUTH:
                    try:
                        dec = self._codec.dec(fr["payload"].hex())
                    except SignSvcError:
                        # signsvc 在 ack 解密时崩溃：认证本身已成功（服务器已回 echo），
                        # server_ip 只是可降级字段——不杀会话，降级上报后继续订阅链
                        dec = None
                    if not dec:
                        # fail-visible：认证本身成功，但解密失败必须结构化上报，不得仍作完整成功
                        self._err("610 ack decode failed (DEC returned empty)")
                        self._emit(KplEvent(type="auth", ts=time.time(), ok=True,
                                            decode_degraded=True, server_ip="",
                                            session=self._session_no))
                    else:
                        info = proto.parse_auth_resp(dec)
                        self._emit(
                            KplEvent(type="auth", ts=time.time(), ok=True,
                                     server_ip=info.get("server_ip", ""),
                                     session=self._session_no)
                        )
                    auth_ok = True
                    break
                if fr["cmd"] == proto.CMD_ERROR:
                    err = proto.parse_err_resp(fr["payload"])
                    self._err(f"auth rejected: {err}")
                    self._emit(KplEvent(type="auth", ts=time.time(), ok=False, error=err))
                    return
            if not auth_ok:
                self._err("no 610 ack in 15s")
                return
            # 4) 602 登录态
            ls_pb = proto.build_login_state_pb(self._user_id, self._token, self._device_id)
            enc_ls = self._codec.enc(ls_pb)
            ls_frame = proto.build_frame(proto.CMD_LOGIN_STATE, next_seq(), enc_ls or ls_pb, d=0,
                                         encrypted=bool(enc_ls))
            self._human_pause(0.6, 0.3)
            self._dbg("C", ls_frame)
            sock.sendall(ls_frame)
            self._status = "subscribing"
            # 5) 2301 版本订阅（pkg 0x40 + ext 路由头 02 08fd），与 collector 一致：
            #    发 2301 → 读 ack → 发 2303+2304 → 读 ack → 发 3001 → 读 ack（不乱序）
            vr = proto.build_version_req_pb(0)
            enc_vr = self._codec.enc(vr)
            ext = bytes([0x02]) + struct.pack(">H", proto.CMD_PLATE_LIST)
            vr_frame = proto.build_frame(proto.CMD_PLATE_LIST, next_seq(), enc_vr or vr, d=1,
                                         encrypted=bool(enc_vr), pkg=proto.PKG_ROUTE, ext=ext)
            self._human_pause(0.8, 0.4)
            self._dbg("C", vr_frame)
            sock.sendall(vr_frame)
            deadline = time.time() + 10
            while time.time() < deadline:
                fr = self._read_frame_tolerant(sock, deadline)
                if fr == "timeout":
                    break   # deadline 到 → 3001 链路继续（url 未捕获则 plate-tree 上报待捕获）
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 2301 ack")
                if fr["fmt"] == "echo" and fr["cmd"] == proto.CMD_PLATE_LIST:
                    # 2301 echo 载荷含板块清单快照 url（f7，appimgcdn/plate/146_<version>.data）
                    # ——捕获供板块树下载（二级目录映射），解析失败不影响会话
                    try:
                        payload = fr.get("payload", b"")
                        if payload:
                            dec = (self._codec.dec(payload.hex())
                                   if (fr.get("flags", 0) & 1) and payload
                                   else payload)
                            info = proto.parse_version_resp(dec)
                            for u in info.get("urls", []):
                                if u.startswith("http"):
                                    self._plate_url = u
                                    self._plate_version = info.get("version", 0)
                    except Exception as exc:
                        self._err(f"2301 快照 url 捕获失败（不影响会话）: {exc}")
                    break
            # 5b) 2303+2304 订阅（app 的 AttachAppTimerTask 三件套）
            for sub_cmd, ext_bytes in (
                (proto.CMD_STOCK_LIST, bytes([0x02]) + struct.pack(">H", proto.CMD_STOCK_LIST)),
                (proto.CMD_HK_LIST, bytes([0x02]) + struct.pack(">H", proto.CMD_HK_LIST)),
            ):
                enc_sub = self._codec.enc(vr)
                sub_frame = proto.build_frame(sub_cmd, next_seq(), enc_sub or vr, d=0,
                                              encrypted=bool(enc_sub), pkg=proto.PKG_ROUTE,
                                              ext=ext_bytes)
                self._dbg("C", sub_frame)
                sock.sendall(sub_frame)
            deadline = time.time() + 10
            acks_needed = 2
            while acks_needed > 0 and time.time() < deadline:
                fr = self._read_frame_tolerant(sock, deadline)
                if fr == "timeout":
                    continue   # 服务器静默：等满 deadline，ack 计数不变
                if fr is None:
                    raise proto.FrameDecodeError("closed awaiting 2303/2304 ack")
                if fr["fmt"] == "echo" and fr["cmd"] in (proto.CMD_STOCK_LIST, proto.CMD_HK_LIST):
                    acks_needed -= 1
            # 6) 3001 订阅：按块发（优先块→普通块；单请求 ≤200 id，超限 1106）
            ext3 = bytes([0x02]) + struct.pack(">H", proto.CMD_GROUP_QUOTAS)
            for chunk in (self._sub_prio + self._sub_rest) or [self._stock_ids]:
                gq = proto.build_group_quotas_req_pb(chunk)
                enc_gq = self._codec.enc(gq)
                gq_frame = proto.build_frame(proto.CMD_GROUP_QUOTAS, next_seq(), enc_gq or gq, d=0,
                                             encrypted=bool(enc_gq), pkg=proto.PKG_ROUTE, ext=ext3)
                self._human_pause(0.3, 0.15)
                self._dbg("C", gq_frame)
                sock.sendall(gq_frame)
            # 6b) 3006 个股行情订阅：HQStockIdListReq{f1 repeated stockIds}（个股实时价）。
            #     与 3001 同款分块（单请求 id 超 ~241 会被 1106 拒绝；2026-10-27 实测：
            #     精选板块引导后 id≈500 单帧全发即触发 server error 1106）
            ext6 = bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_ID_LIST)
            # 2026-11-10 实弹定性（§3.4 铁律：会话寿命=setup 末帧+~0.9s，三组 regime 一致）：
            # 3006 分块是全 setup 唯一零停顿背靠背连发处（d94c0c83 引入；首发单帧无此问题），
            # 瞬时 3 连发=App 不可能有的指纹，服务器打标后 ~1s 处决（drain 帧/读循环只是
            # 处决时刻后的第一波受害者）。补上与 3001 同款帧间拟人停顿。
            for ci, chunk in enumerate(self._chunks(list(self._stock_ids))):
                hq = b"".join(proto.pb_bytes(1, sid.encode()) for sid in chunk)
                enc_hq = self._codec.enc(hq)
                hq_frame = proto.build_frame(proto.CMD_HQ_ID_LIST, next_seq(), enc_hq or hq, d=0,
                                             encrypted=bool(enc_hq), pkg=proto.PKG_ROUTE, ext=ext6)
                self._human_pause(0.3, 0.15)
                self._dbg("C", hq_frame)
                sock.sendall(hq_frame)
            # 6c) 打板/情绪订阅（service_hq_daban.proto，2026-10-27 逆向）：
            #     2114/2115/2118/2119/2116/2126/2120/2121 发 QxMarketEnergyReq{type}；2116/2126 空 Req；
            #     2120/2121 发 QxZtSituationStockReq{bsType}。逐 cmd 一帧，同 0x40 通道与 ext 路由头。
            #     2026-11-10 重排：不再内联发送，入 _pending_setup_frames 由读循环限流续发。
            #     实弹定性（§3.4）：setup 全串行发完 ~32s 才进读循环，而会话在 setup 结束后
            #     ~1s 即被上游 RST（last_setup_s=31.9 / last_session_s=32.8，推送窗口≈0.9s），
            #     3001 推送根本没时间到流（个股列表过期数据的直接原因）。重排后行情订阅
            #     （3001/3006，有 ack 顺序依赖必须内联）最先就绪，daban 家族由读循环以
            #     setup 同款 0.3s 拟人节奏续发；2203/2013 让路（_drain_zt_reason_subs/_drain_theme_subs）。
            if self._daban_subs:
                for sub_cmd in daban.DABAN_SUB_CMDS:
                    if sub_cmd in (daban.CMD_ZD_STAT, daban.CMD_MARKET_OVERVIEW,
                                   daban.CMD_WEIGHT_PERF_V2, daban.CMD_ZT_SITUATION_V2):
                        req_pb = daban.build_market_energy_req_pb(self._daban_market_type)
                    elif sub_cmd in (daban.CMD_ZT_STOCK_LIST, daban.CMD_ZT_STOCK_LIST_PB):
                        # bsType: 1=涨停 2=跌停（app ZhangTingStockListFragment PidType）；
                        # orderType 默认 4（a0() 的 this.q=4 基线），orderType=0 实测无响应
                        bs = 1 if sub_cmd == daban.CMD_ZT_STOCK_LIST else 2
                        req_pb = daban.build_zt_situation_stock_req_pb(bs_type=bs, order_type=4)
                    else:  # 2116/2126 空 Req
                        req_pb = daban.build_empty_req_pb()
                    self._pending_setup_frames.append({
                        "cmd": sub_cmd, "req": req_pb,
                        "ext": bytes([0x02]) + struct.pack(">H", sub_cmd),
                    })
                # 6d) 2103 打板个股列表订阅：每页签按 index 偏移逐页一帧（推送页固定 30 行，
                #     count=200 实测无效——见 __init__ 注释）；Resp.pidType+index 回带区分页归属
                for pid in self._daban_list_pids:
                    for page in range(self._daban_list_pages):
                        req_pb = daban.build_daban_stock_list_req_pb(
                            pid, index=page * self._daban_list_page_size,
                            count=self._daban_list_page_size)
                        self._pending_setup_frames.append({
                            "cmd": daban.CMD_DABAN_STOCK_LIST, "req": req_pb,
                            "ext": bytes([0x02]) + struct.pack(">H", daban.CMD_DABAN_STOCK_LIST),
                        })
            # 6e) 2112 会不会上龙虎榜预测订阅（2026-10-29 逆向）：0x40 通道同 daban 家族，
            #     ForecastLHBReq 基线 count=30/sortType=1/quotaType=0（LhbWillStockModel.k(2112)）；
            #     开关独立于 daban_subs（与打板/情绪订阅解耦）
            if self._daban_lhb:
                self._pending_setup_frames.append({
                    "cmd": daban.CMD_FORECAST_LHB, "req": daban.build_forecast_lhb_req_pb(),
                    "ext": bytes([0x02]) + struct.pack(">H", daban.CMD_FORECAST_LHB),
                })
            # 6f) 3004 RealtimeLHB 订阅 + 3101 当日区间单发（ServiceHqList 族，同 0x40 通道
            #     ext 路由头；Req 基线见 kpl_lhb_protocol.REALTIME_LHB_BASELINE，App 原 UI
            #     count=1，采集放宽 30；3101 无区间实测零应答（2026-10-29 开火），改带
            #     当日区间 0925→当前 HHMM（同 App MainIndexQuotationInfoPresenter 用法））
            if self._lhb_realtime:
                req_sub = lhb.build_realtime_lhb_req_pb(count=self._lhb_realtime_count)
                reqs_lhb = [(lhb.CMD_REALTIME_LHB_SUB, req_sub),
                            (lhb.CMD_REALTIME_LHB_RANGE,
                             lhb.build_realtime_lhb_req_pb(
                                 count=self._lhb_realtime_count,
                                 start_time=925, end_time=int(time.strftime("%H%M"))))]
                for lhb_cmd, req_rl in reqs_lhb:
                    self._pending_setup_frames.append({
                        "cmd": lhb_cmd, "req": req_rl,
                        "ext": bytes([0x02]) + struct.pack(">H", lhb_cmd),
                    })
            # 6g-pre) 2026-11-10 探针实锤：0x40 帧只许在 setup 窗口内发送，内联模式下
            # daban 家族先发（池数据+页面优先于语料订阅），再 2203/2013
            if self._setup_inline_subs and self._pending_setup_frames:
                self._flush_pending_inline(sock, next_seq, "setup")
                self._pending_setup_frames = []
                self._stats["queued_setup_subs"] = 0
            else:
                self._stats["queued_setup_subs"] = len(self._pending_setup_frames)
            # 6g) 2203 涨停原因试点：每会话重建订阅——服务器 TTL≈60-90s，重连后原订阅面已失效，
            # 跨会话去重会让第二会话起一帧不发、推送静默停流（2026-11-08 评审 P0）：先清
            # 已订阅集合再全量补订；页帧到达后的新增成员由 _dispatch 自动入队，drain 在收流循环内
            # 2026-11-10 补充：setup_inline_subs=True 时 2203/2013 改为 setup 窗口内内联发送
            # （探针实锤：窗口关闭后任何 0x40 帧→ErrResp 1002 断连），循环期仅限新入队不发送。
            if self._zt_reason_subs:
                with self._zt_reason_lock:
                    self._zt_reason_subscribed.clear()
                    self._pending_zt_reason.clear()
                self._queue_zt_reason_new(self._pool_stock_ids())
                if self._setup_inline_subs:
                    self._flush_pending_inline(sock, next_seq, "zt_reason")
            if self._theme_subs:
                with self._theme_lock:
                    self._theme_subscribed.clear()
                    self._pending_theme.clear()
                self._queue_theme_new(self._pool_stock_ids())
                if self._setup_inline_subs:
                    self._flush_pending_inline(sock, next_seq, "theme")
            # 6h) 个股详情四通道（2026-11-11 ④，默认关）：每会话重建订阅（同 2203/2013
            # 服务器 TTL 同源；跨会话去重会让第二会话起一帧不发、推送静默停流）
            if self._stock_detail_subs:
                for lane in self._detail_lane_cmds:
                    with self._detail_locks[lane]:
                        self._detail_subscribed[lane].clear()
                        self._pending_detail[lane].clear()
                self._queue_detail_new(self._pool_stock_ids())
                if self._setup_inline_subs:
                    # 2026-11-11 评审 major-2：inline 模式下详情订阅同 2203/2013
                    # 改 setup 窗口内内联发送（否则 6h 只入队、循环期永久静默）
                    self._flush_pending_inline(sock, next_seq, "detail")
            # setup 打点在 6g（2203/2013 订阅入队）之后：口径=「连接到内联订阅链
            # （3001/3006）全部完成」；daban 家族已重排为读循环续发，不占此口径
            # （实弹口径见 _drain_setup_subs 注释）
            self._stats["last_setup_s"] = round(time.time() - t_setup, 1)
            self._emit(KplEvent(type="status", ts=time.time(), status="streaming",
                                session=self._session_no))
            # 7) 收流 + 保活：3001 按块轮转（优先块与普通块交替，单请求 ≤200 id）；
            #    服务器 TTL 由重连机制兜底；610 重发每 8 tick 保留
            rot_chunks = []
            for i in range(max(len(self._sub_prio), len(self._sub_rest), 1)):
                rot_chunks.append(self._sub_prio[i % len(self._sub_prio)])
                if i < len(self._sub_rest):
                    rot_chunks.append(self._sub_rest[i])
            rot_idx = [0]
            last_keepalive = time.time()
            auth_frame_cache = [None]
            hb_flip = [0]
            # 宽限期（2026-11-10 假说判别）：期首只读不发；结束时结构化打点（fail-visible）
            t_loop = time.time()
            grace_end_fired = [False]
            while not self._stop.is_set():
                try:
                    fr = self._read_frame(sock)
                except socket.timeout:
                    fr = "timeout"  # 哨兵：本轮无数据，不是断连；保活块仍然执行
                if fr is None:
                    # 服务器断开 → 先于保活/drain 返回触发重连（关死 socket 上多发
                    # 只会撞 10054，2026-11-10 重排后 drain 前置门禁）
                    self._err(f"session#{self._session_no} closed by server")
                    return
                now = time.time()
                in_grace = (now - t_loop) < self._loop_send_grace_s
                if not in_grace and not grace_end_fired[0] and self._loop_send_grace_s > 0:
                    grace_end_fired[0] = True
                    self._stats["grace_end_pending"] = [len(self._pending_setup_frames),
                                                        len(self._pending_zt_reason),
                                                        len(self._pending_theme)]
                    self._emit(KplEvent(type="status", ts=time.time(), status="loop_grace_end",
                                        session=self._session_no,
                                        pending=[len(self._pending_setup_frames),
                                                 len(self._pending_zt_reason),
                                                 len(self._pending_theme)]))
                if in_grace:
                    if fr == "timeout":
                        continue
                    self._dispatch(fr, sender=sock.sendall, next_seq=next_seq)
                    continue
                if now - last_keepalive > 1:
                    # 保活交替: 每 8 tick 一次 610 AuthReq 原样重发（签名绑定初始
                    # challenge/curTime）/ 其余 tick 3001 分块轮询（下一块）
                    hb_flip[0] += 1
                    if hb_flip[0] % 8 == 1 and self._ka_610:
                        if hb_flip[0] == 1:
                            auth2 = proto.build_auth_req_pb(
                                device_id=self._device_id,
                                version_name=self._version_name,
                                channel_id=self._channel_id,
                                signature_hex=sig_hex,
                                user_id=self._user_id,
                                token=self._token,
                                conn_type=self._conn_type,
                                cur_time=int(server_time),
                                api_version=self._api_version,
                            )
                            enc2 = self._codec.enc(auth2)
                            if enc2:
                                auth_frame_cache[0] = proto.build_frame(
                                    proto.CMD_AUTH, next_seq(), enc2, d=2,
                                    encrypted=True, pkg=proto.PKG_AUTH)
                        if auth_frame_cache[0] is not None:
                            # seq 递增但 AuthReq 内容原样（与 kpl_collector 行为一致）
                            frame_bytes = auth_frame_cache[0]
                            frame_bytes = frame_bytes[:5] + next_seq().to_bytes(2, "big") + frame_bytes[7:]
                            self._dbg("C", frame_bytes)
                            sock.sendall(frame_bytes)
                    else:
                        if not rot_chunks:
                            rot_chunks.append(self._stock_ids)
                        chunk = rot_chunks[rot_idx[0] % len(rot_chunks)]
                        rot_idx[0] += 1
                        gq2 = proto.build_group_quotas_req_pb(chunk)
                        enc2 = self._codec.enc(gq2)
                        if enc2:
                            ka_frame = proto.build_frame(proto.CMD_GROUP_QUOTAS, next_seq(), enc2, d=0,
                                                         encrypted=True, pkg=proto.PKG_ROUTE, ext=ext3)
                            self._dbg("C", ka_frame)
                            sock.sendall(ka_frame)
                    last_keepalive = now
                # 2203/2013 待订阅帧 drain（新入池成员数秒内补订，不占保活节奏）。
                # 2026-11-10 时序竞争修复（生产实测：会话 ~50s 被 TTL/风控杀，daban 页
                # 42 帧排前导致 2203/2013 实际发出已是会话 ~35-46s，服务器响应未回会话
                # 即死，语料快照恒 0）：语料订阅排最前，三队列每 tick 各发 8 帧交错——
                # zt(30)=4 tick、theme(22)=3 tick、daban 页(42)=6 tick，全部 ~6 tick 完成
                # 2026-11-11 再修：detail 块（静默期 flush 合同，60 帧×0.375s≈22s）排
                # 首位——排在 zt/theme 后时块尾已是会话 ~55-65s，与 60-67s 会话寿命
                # 贴线竞争（13:10 生产 79.8s 会话才落地）；提前后块尾 ~25-30s，flush
                # 批回落在会话中段。代价：本 tick 内 zt/theme/setup 延后一个块长（
                # 与原顺序下块在会话中段 stall 同量级，无新增风控面）。
                self._drain_detail_subs(sock, next_seq)
                self._drain_zt_reason_subs(sock, next_seq)
                self._drain_theme_subs(sock, next_seq)
                self._drain_setup_subs(sock, next_seq)
                if fr == "timeout":
                    continue
                self._dispatch(fr, sender=sock.sendall, next_seq=next_seq)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _dec_if_flags(self, payload: bytes, fr: Dict[str, Any]) -> bytes:
        """enc 位 → 先 DEC 再解析（App 读侧 cmd 无关的条件解密；失败回退原密文）。

        服务器主动帧（pkg 0x20）该位叫 status，echo/推送帧叫 flags —— 两名都查。
        """
        enc = (fr.get("flags", 0) or fr.get("status", 0)) & 1
        if enc and payload:
            try:
                dec = self._codec.dec(payload.hex())
                if dec:
                    return dec
            except SignSvcError:
                pass   # 回退原载荷，由下游长度/解析护栏 fail-visible（不吞非 SignSvc 异常）
        return payload

    def _answer_anti_cheat(self, payload: bytes, *, sender: Any = None,
                           next_seq: Any = None) -> None:
        """261 AntiCheatChallenge → 262 应答（白盒 EXEC 注入，2026-11-08）。

        App 口径（qn0.g / GameClient$onChallenge$2，反编译源码逐字对照）：
        data = pb f1（长度<36 → 无效帧，App 丢弃且不断连）；token = data[:32] 原样回填；
        d = BE32(data[32:36])；挑战串 = US_ASCII(data[36:]) → execEncryptedHex(串, d)；
        应答 pb f1 = token + BE int32(结果)，帧 = cmd262 / pkg 0x30 / flags=(0<<3)|enc
        （d=0，与 602 同款；加密失败回退明文，App 同款 fallback）。
        EXEC 不可用 / VM 失败（Long.MIN_VALUE）→ **不发假答案**：qn0.g 对 VM 失败是静默
        丢弃（ChallengeClient 独立 socket 路径才显式断连），但不应答必然被服务器踢；本实现
        取断连——fail-visible 上报后抛 AntiCheatError 走重连链（5s 退避）。
        """
        data = proto.parse_anti_cheat_261(payload)
        if len(data) < 36:
            self._emit(KplEvent(type="anti_cheat_error", ts=time.time(),
                                reason="challenge_payload_too_short", payload_len=len(data)))
            return
        token, d, challenge = proto.anti_cheat_challenge(data)
        if "\ufffd" in challenge:   # US_ASCII 解不出的串不得拿去做白盒执行（不猜）
            self._emit(KplEvent(type="anti_cheat_error", ts=time.time(),
                                reason="challenge_not_ascii", d=d, challenge_len=len(challenge)))
            raise AntiCheatError("261 challenge is not ASCII")
        fn = getattr(self._codec, "exec", None)
        value = None
        if callable(fn):
            try:
                value = fn(challenge, d)
            except SignSvcError as exc:
                self._emit(KplEvent(type="anti_cheat_error", ts=time.time(),
                                    reason=f"signsvc: {exc}", d=d,
                                    challenge_len=len(challenge)))
                raise AntiCheatError(f"EXEC failed: {exc}")
        if value is None or value == -(2 ** 63):
            self._emit(KplEvent(type="anti_cheat_error", ts=time.time(),
                                reason="exec_unavailable" if not callable(fn) else "exec_vm_error",
                                d=d, challenge_len=len(challenge)))
            raise AntiCheatError("EXEC returned no answer (Long.MIN_VALUE/unavailable)")
        if sender is None or next_seq is None:
            self._emit(KplEvent(type="anti_cheat_error", ts=time.time(), reason="no_sender"))
            return
        ans_pb = proto.build_anti_cheat_ans_262(data, int(value))
        enc = None
        try:
            enc = self._codec.enc(ans_pb)
        except SignSvcError:
            enc = None   # 加密失败回退明文（App x() 同款 fallback，flags enc=0）
        body, encrypted = (enc, True) if enc else (ans_pb, False)
        frame = proto.build_frame(proto.CMD_ANTI_CHEAT_ANS, next_seq(), body,
                                  d=0, encrypted=encrypted)
        self._dbg("C", frame)
        sender(frame)
        self._stats["anti_cheat_rounds"] = self._stats.get("anti_cheat_rounds", 0) + 1
        self._emit(KplEvent(type="anti_cheat", ts=time.time(), ok=True,
                            value=int(value), d=d, encrypted=bool(enc),
                            token_len=len(token)))

    def _dispatch(self, fr: Dict[str, Any], *, sender: Any = None, next_seq: Any = None) -> None:
        cmd = fr["cmd"]
        payload = fr.get("payload", b"")
        if cmd == proto.CMD_ERROR:
            err = proto.parse_err_resp(payload)
            self._err(f"server error: {err}")
            self._emit(KplEvent(type="error", ts=time.time(), server=err))
            return
        if cmd == proto.CMD_ANTI_CHEAT:
            # 261 反作弊轮：读侧解密与 cmd 无关（App SocketReaderThread：flags enc=1 → DEC），
            # 解密失败回退原载荷由长度护栏 fail-visible；EXEC 注入作答（2026-11-08）
            self._answer_anti_cheat(self._dec_if_flags(payload, fr),
                                    sender=sender, next_seq=next_seq)
            return
        if cmd == proto.CMD_HQ_ID_LIST:
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"3006 push decode failed ({len(payload)}B)")
                return
            quotes = proto.parse_index_simple_quotes(dec)
            self._stats["pushes"] += 1
            self._emit(KplEvent(type="stock_quotes", ts=time.time(),
                                source="push" if fr.get("fmt") == "push" else "resp",
                                **quotes))
            return
        if cmd == proto.CMD_HQ_REASONS:
            # 2203 涨停原因推送（试点）：dec/解析 fail-visible，不静默丢弃
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"2203 push decode failed ({len(payload)}B)")
                self._emit(KplEvent(type="zt_reasons_error", ts=time.time(), cmd=cmd,
                                    reason="push decode failed", payload_len=len(payload)))
                return
            try:
                data = proto.parse_hq_reasons_resp(dec)
            except Exception as exc:
                self._err(f"2203 parse error: {exc}")
                self._emit(KplEvent(type="zt_reasons_error", ts=time.time(), cmd=cmd,
                                    reason=f"parse error: {exc}", payload_len=len(payload)))
                return
            self._stats["pushes"] += 1
            sid = str(data.get("stock_id") or "").strip()
            if sid:
                self._zt_reason_snap[sid] = {**data, "ts": time.time()}
                # 推送即落库（AGENTS §1.2-8/2026-11-10 用户裁决）：不再等盘后轮询
                self._persist_corpus("reason", {"reasons": {
                    sid: {**data, "ts": time.time()}}})
            self._emit(KplEvent(type="zt_reasons", ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp", **data))
            return
        if cmd == proto.CMD_STOCK_RELATED_THEME:
            # 2013 题材库热度推送（2026-11-08 题材龙头语料）：与 2203 分支同款
            # dec/解析 fail-visible，不静默丢弃
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"2013 push decode failed ({len(payload)}B)")
                self._emit(KplEvent(type="theme_heat_error", ts=time.time(), cmd=cmd,
                                    reason="push decode failed", payload_len=len(payload)))
                return
            try:
                data = proto.parse_stock_related_theme_resp(dec)
            except Exception as exc:
                self._err(f"2013 parse error: {exc}")
                self._emit(KplEvent(type="theme_heat_error", ts=time.time(), cmd=cmd,
                                    reason=f"parse error: {exc}", payload_len=len(payload)))
                return
            self._stats["pushes"] += 1
            sid = str(data.get("stock_id") or "").strip()
            if sid:
                self._theme_snap[sid] = {**data, "ts": time.time()}
                # 推送即落库（2026-11-10 用户裁决）：不再等盘后轮询
                self._persist_corpus("theme", {"items": [
                    {**data, "ts": time.time()}]})
            self._emit(KplEvent(type="theme_heat", ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp",
                                stock_id=sid, themes=data.get("themes") or []))
            return
        if cmd in DETAIL_EVENT_NAMES:
            # 个股详情四通道推送（2026-11-11 ④）：dec/解析 fail-visible，不静默丢弃；
            # 解析成功 → snap 更新 + 即时落库（单写者=采集线程，失败不阻断收流）
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"{cmd} detail push decode failed ({len(payload)}B)")
                self._emit(KplEvent(type="stock_detail_error", ts=time.time(), cmd=cmd,
                                    reason="push decode failed", payload_len=len(payload)))
                return
            parser = DETAIL_PARSERS[cmd]
            try:
                data = parser(dec)
            except Exception as exc:
                self._err(f"{cmd} detail parse error: {exc}")
                self._emit(KplEvent(type="stock_detail_error", ts=time.time(), cmd=cmd,
                                    reason=f"parse error: {exc}", payload_len=len(payload)))
                return
            self._stats["pushes"] += 1
            lane = DETAIL_LANE_BY_CMD[cmd]
            sid = str(data.get("stock_id") or "").strip()
            if lane == "bdo" and sid:
                # 2014 单股聚合（原始值 sum 仅审计保留，合同向后兼容；2026-11-11 实弹值裁决追加
                # 尾条派生聚合 *_yuan：zt_tur=封单额级值、buy/sell=当日累计——sum 无意义，
                # 展示口径取尾条最新态；换算单一出口=协议层 bdo_aggregate_last（复用
                # BDO_TUR_DIVISOR）。2026-11-11 评审 major-1：异形帧字段可能透传 bytes，
                # 无守卫算术会抛 TypeError 杀收流会话（重连螺旋形态，§1.2-9）——聚合失败
                # fail-visible 并按无聚合值落库；bdo_aggregate_last 防御式实现，异形帧返回
                # {} → *_yuan 缺位，叙事整股缺席（不补 0）。
                try:
                    agg = {k: sum((it.get(k) or 0) for it in (data.get("items") or [])
                                  if isinstance(it, dict))
                           for k in ("zt_tur", "buy_tur", "sell_tur")}
                    agg.update(proto.bdo_aggregate_last(data))
                except Exception as exc:
                    self._err(f"2014 aggregate failed: {exc}")
                    self._emit(KplEvent(type="stock_detail_error", ts=time.time(), cmd=cmd,
                                        reason=f"aggregate failed: {exc}"))
                    agg = {}
                data = {**data, **agg}
            if sid:
                self._detail_snaps[lane][sid] = {**data, "ts": time.time()}
                # 推送即落库（合同同 2203/2013；bdo_/bf_/abn_/rplate_ 前缀日档）
                self._persist_corpus(lane, {"items": [{**data, "ts": time.time()}]})
            else:
                # 2026-11-11 评审 minor-5：sid 缺位与 decode/parse 失败同款 fail-visible
                self._emit(KplEvent(type="stock_detail_error", ts=time.time(), cmd=cmd,
                                    reason="missing_stock_id", payload_len=len(dec)))
            self._emit(KplEvent(type=DETAIL_EVENT_NAMES[cmd], ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp",
                                **{k: v for k, v in data.items()
                                   if k not in ("type", "ts", "cmd")}))
            return
        if cmd == proto.CMD_GROUP_QUOTAS:
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"3001 push decode failed ({len(payload)}B)")
                return
            quotes = proto.parse_group_quotas(dec)
            self._stats["pushes"] += 1
            self._emit(KplEvent(type="quotes", ts=time.time(),
                                source="push" if fr.get("fmt") == "push" else "poll",
                                **quotes))
            return
        if cmd in (proto.CMD_PLATE_LIST, proto.CMD_STOCK_LIST, proto.CMD_HK_LIST):
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"{cmd} version frame decode failed ({len(payload)}B)")
                return
            info = proto.parse_version_resp(dec)
            self._emit(KplEvent(type="version", ts=time.time(), cmd=cmd, **info))
            return
        if cmd in daban.DABAN_RESP_PARSERS or cmd in lhb.LHB_RESP_PARSERS:
            parser = daban.DABAN_RESP_PARSERS.get(cmd) or lhb.LHB_RESP_PARSERS[cmd]
            dec = self._codec.dec(payload.hex()) if payload else None
            if not dec:
                self._err(f"{cmd} daban push decode failed ({len(payload)}B)")
                self._emit(KplEvent(type="daban_error", ts=time.time(), cmd=cmd,
                                    reason="push decode failed", payload_len=len(payload)))
                return
            try:
                data = parser(dec)
            except Exception as exc:  # fail-visible：解析异常不静默丢弃
                self._err(f"{cmd} daban parse error: {exc}")
                self._emit(KplEvent(type="daban_error", ts=time.time(), cmd=cmd,
                                    reason=f"parse error: {exc}", payload_len=len(payload)))
                return
            self._stats["pushes"] += 1
            if cmd == daban.CMD_DABAN_STOCK_LIST:
                # 2103 按页缓存（pidType→index→页快照）：推送页固定 30 行，读口按 index 合并。
                # 空帧抑制（2026-10-28 盘中实测）：风向标页上游在列表重建窗口高频回空帧
                # （35s 内 14 帧 Resp，12 空/2 满 25 项），无条件覆盖会让读口绝大多数时间为空；
                # 故空帧不覆盖非空页缓存（仅刷 ts + 记 last_empty_seen），真清空（盘后）随
                # 日期切换/采集重启自然重置。
                try:
                    pid = int(data.get("pid_type", 0))
                    idx = int(data.get("index", 0))
                    new_items = data.get("items") or []
                    prev = self._daban_lists.get(pid, {}).get(idx)
                    if not new_items and prev and (prev.get("items") or []):
                        kept = dict(prev)
                        kept["ts"] = time.time()
                        kept["last_empty_seen"] = time.time()
                        self._daban_lists.setdefault(pid, {})[idx] = kept
                    else:
                        self._daban_lists.setdefault(pid, {})[idx] = {**data, "ts": time.time()}
                except (TypeError, ValueError):
                    pass
                if self._zt_reason_subs:
                    # 2203 试点钩子：涨停池（pid=1）新入池成员自动补订（去重；drain 在收流循环）
                    try:
                        if int(data.get("pid_type", 0)) == 1:
                            pool_items = data.get("items") or []
                            if pool_items:
                                self._queue_zt_reason_new(
                                    [str(it.get("stock_id") or "").strip() for it in pool_items])
                    except (TypeError, ValueError):
                        pass
                if self._theme_subs:
                    # 2013 同款钩子：涨停池新入池成员自动补订题材库订阅
                    try:
                        if int(data.get("pid_type", 0)) == 1:
                            pool_items = data.get("items") or []
                            if pool_items:
                                self._queue_theme_new(
                                    [str(it.get("stock_id") or "").strip() for it in pool_items])
                    except (TypeError, ValueError):
                        pass
                if self._stock_detail_subs:
                    # 详情四通道同款钩子：涨停池新入池成员自动补订（2014/2202/2030/2010）
                    try:
                        if int(data.get("pid_type", 0)) == 1:
                            pool_items = data.get("items") or []
                            if pool_items:
                                self._queue_detail_new(
                                    [str(it.get("stock_id") or "").strip() for it in pool_items])
                    except (TypeError, ValueError):
                        pass
            event_type = DABAN_EVENT_NAMES.get(cmd) or LHB_EVENT_NAMES.get(cmd, "daban")
            if cmd == daban.CMD_FORECAST_LHB:
                # 2112 空帧抑制（同 2103/3004 规；2026-10-29 午间实测：休市推流
                # total=96/items=[]，直覆盖会冲掉盘中非空快照）：items 空 && total>0
                # 视为空推流不覆盖；total=0 才是服务端语义清空，正常覆盖
                new_fc_items = data.get("items") or []
                prev_fc = self._lhb_forecast_snap
                if (not new_fc_items and (data.get("total") or 0) > 0
                        and prev_fc and (prev_fc.get("items") or [])):
                    kept_fc = dict(prev_fc)
                    kept_fc["ts"] = time.time()
                    kept_fc["last_empty_seen"] = time.time()
                    self._lhb_forecast_snap = kept_fc
                else:
                    self._lhb_forecast_snap = {**data, "ts": time.time()}
                if new_fc_items:
                    # 推送即落库（2026-11-11 ③）：2112 非空帧即时写 fc_ 日档（单写者，
                    # 失败不阻断收流）；空帧已抑制不落库（空帧写也只是浪费一次写）
                    self._persist_corpus("fc", {"items": [
                        {**it, "ts": time.time()} for it in new_fc_items
                        if isinstance(it, dict)]})
            elif cmd in (lhb.CMD_REALTIME_LHB_SUB, lhb.CMD_REALTIME_LHB_RANGE):
                # 3004/3101 空帧抑制（同 2103 规）：空 items 不覆盖非空快照
                new_items = data.get("items") or []
                prev = self._lhb_realtime_snap
                if not new_items and prev and (prev.get("items") or []):
                    kept = dict(prev)
                    kept["ts"] = time.time()
                    kept["last_empty_seen"] = time.time()
                    self._lhb_realtime_snap = kept
                else:
                    self._lhb_realtime_snap = {**data, "ts": time.time()}
                if new_items:
                    # 推送即落库（2026-11-11 ③）：3004/3101 非空帧即时写 rt_ 日档
                    self._persist_corpus("rt", {"items": [
                        {**it, "ts": time.time()} for it in new_items
                        if isinstance(it, dict)]})
            self._emit(KplEvent(type=event_type, ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp", **data))
            return
        # 其他 cmd：fail-visible 记录原始帧（截断）
        self._emit(KplEvent(type="raw", ts=time.time(), cmd=cmd,
                            payload_hex=payload[:64].hex(), payload_len=len(payload)))
