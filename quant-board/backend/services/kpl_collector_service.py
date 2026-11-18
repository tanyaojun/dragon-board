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
from backend.services.kpl_sub_registry import SubEntry, SubRegistry
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
        daban_subs: bool = True,
        daban_market_type: int = 1,
        daban_list_pids: Optional[Tuple[int, ...]] = (8, 0, 6, 1, 2, 3),
        daban_list_page_size: int = 30,
        # P1 收敛（2026-11-17 用户裁决「按股票代码落库」）：非竞价池 1 页/池——归档层
        # 本就按 stock_id 并集落库（全日成员覆盖），涨停时间倒序下进池瞬间必在页首，
        # 1 页即可捕获全部进池成员；同刻池深度快照无消费者。
        # **例外 pid=8 竞价池保持 _daban_list_pages 页（默认 7）**：竞价池非「进池即
        # 页首」成员表（按委买类排序，小委买股恒沉尾部），且竞价链 universe
        # （派生源/序列 n≈78-114）直接依赖其页深——1 页会把 universe 砍到 ≤30
        # （§7.12 宇宙漂移恶化）。11-18 实测后若竞页面深可降（委买额排序头部
        # 覆盖足够）再收敛。回滚 KPL_DABAN_LIST_PAGES。
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
        # 2026-11-10 探针 E1-E4 曾定性「0x40 帧只许 setup 窗口内发送，窗外→1002」——
        # 2026-11-18 源码定案证伪：E1-E4 队列尾同样带 3101 错通道帧，1002 真凶是它
        # 而非时间窗（README §3.7）。inline 保留纯因 App qn0.z() 零节流同款且实弹稳定。
        # True = 全部订阅内联回 setup（含 2203/2013 全量），读循环期不再发任何 0x40 帧
        # （会话内新入池成员等下一会话 6g 重建；注意：App 实际允许会话中屏 onResume
        # 随时发订阅，未来重启用 zt/theme/detail 循环期发送需重评估此门禁）。
        setup_inline_subs: bool = False,
        # 交易时段门控（2026-11-11 防患设备风控累积）：非交易时段不建连，_run_loop
        # 进入 idle_offhours 每分钟复查，下一时段自动恢复。夜间 7×24 TTL 重连的
        # 纯空转连接是风控打标的累积来源，砍掉后日常连接数降一个数量级。
        enforce_trading_hours: bool = True,
        # 订阅注册表化 + 211 批量增强（2026-11-17 P0-P3，方案唯一来源
        # docs/kpl-socket/sub-registry-refactor-plan.md）：
        # sub_registry_enabled：220 选择性重发开关（False=全量重发旧行为；
        #   注册表观测始终在，单一事实源不双轨）
        # sub_batch_mode：direct=单帧（现状逐字节）| 211=SubReqs 批量信封
        #   （探针 U1-U8 钉死前默认 direct；会话级熔断自动回退）
        # sub_batch_codec：item.data 编码 0=明文 pb / 1=GCM（U2 待探针）
        # unsub_enabled：402/pkg 0x50 退订（探针 P3 钉死前默认关）
        sub_registry_enabled: bool = True,
        sub_batch_mode: str = "direct",
        sub_batch_codec: int = 1,   # U2 实弹定案（2026-11-17）：item.data 必须 GCM，
                                    # 明文（0）→ ErrResp 2008 杀连，默认 1 为安全值
        sub_batch_max_items: int = 10,
        sub_batch_ack_timeout_s: float = 10.0,
        unsub_enabled: bool = False,
        ka_mode: str = "none",   # 2026-11-18 定案默认：App 无周期保活（源码 C2）；off=3001 轮转跑步机（根因①）
        sub_unique_id: bool = False,
        sub_staged: bool = False,
        # 2026-11-18 复盘更正：停顿覆盖旋钮。生产 100ms=实弹验证保守档；App 实际
        # 零节流连发（qn0.z()），0.3s 旧档无源码依据。当初「贴沿 20s 窗口」动机
        # 已证伪（真凶=3101 错通道），留值纯因实弹稳定。
        drain_pause: Optional[tuple] = None,
    ):
        if ka_mode not in ("610", "off", "none"):
            raise ValueError(f"ka_mode 非法值 {ka_mode!r}（仅支持 610|off|none）")
        if sub_staged and setup_inline_subs:
            raise ValueError("sub_staged 与 setup_inline_subs 不兼容（分波依赖读循环 drain 架构）")
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
        # drain 帧间停顿（实验旋钮）；保活模式。2026-11-18 源码定案默认 none：
        # App 无周期保活（610 仅 userAuth 一次、无 Timer，独立审计 C2 实锤）；
        # off=3001 轮转跑步机（根因①）。历史注：P4「off 更贴 App」是 3 id 小面
        # 实验，动态面未复验即失效（README §3.7）；610→1106 为小面受控结果。
        # 2026-11-18 定案默认 100ms（实弹验证档；App 实际零节流连发，0.3s 旧档无源码依据）
        self._drain_pause = tuple(drain_pause) if drain_pause else (0.1, 0.05)
        self._ka_mode = ka_mode
        self._setup_inline_subs = bool(setup_inline_subs)
        self._retry_fail_count = 0        # App ReconnectManager.c：重连失败计数（退避梯索引）
        # App 忠实移植（§15）：服务端主动断连计数（SocketRepository.b）+ 上次时刻
        # （>10min 衰减）；健康长会话归零（App u()/j()，PC 适配判据 >=60s）。
        self._server_disconnect_count = 0
        self._last_server_disconnect_ts = 0.0
        # 死因分类观测：区分爆发指纹 RST(10054) / ErrResp 杀连(1106/1002/2008) /
        # 干净 EOF / 网络/auth/反作弊失败，供隔离探针与退避决策（README §3.4）。
        self._last_death_cause = ""
        self._death_cause_counts: Dict[str, int] = {}
        self._session_err_code: Optional[int] = None   # 本会话最近 ErrResp code（每会话复位）
        self._session_streaming = False                # 本会话是否进入收流（setup 早退判别）
        # 分波订阅（历史件，KPL_SUB_STAGED 默认关）：iso1「爆发窗体积阈值
        # ~110-130 帧/窗」模型已证伪（真凶=3101 错通道+3001 跑步机，README §3.7）：
        # 订阅爆发 rst_10054 曾被归因为**爆发窗体积阈值**触发（阈值 ∈ ~110-130 帧/窗，
        # staged1 三会话收敛；非会话累计——累计 ~300 帧存活 130s）。分波把初始
        # 爆发压到阈值下，wave2/3 漏斗错峰补齐；会话死亡未释放波次随会话作废。
        self._sub_staged = bool(sub_staged)
        self._staged_waves: List[Dict[str, Any]] = []
        self._staged_t0 = 0.0
        # 漏斗轮转游标（方案 A，用户裁决 2026-11-17）：跨会话持久，全池 ~300 ids
        # 约 2 会话轮完，单股 per-stock 刷新周期 ~3min
        self._staged_pool_cursor = 0
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
        # 2026-11-10 重排：daban 家族（21xx/2103/2112/3004/3101）不再在 setup 内联发送，
        # 改为入队由读循环限流续发（_drain_setup_subs）——见 _session 6c 注释
        self._pending_setup_frames: List[Dict[str, Any]] = []
        # 订阅注册表（2026-11-17 P1，App qn0.e 同款语义，单一事实源替代旧
        # _resub_cache）：已发订阅原料 + ack attr2/attr3 回填 + 220 选择性重发
        # + 402 退订 diff + 211 批跟踪；会话重建时 clear_session（App qn0.f）
        self._sub_registry = SubRegistry()
        self._sub_registry_enabled = bool(sub_registry_enabled)
        mode = str(sub_batch_mode or "direct").strip().lower()
        if mode not in ("direct", "211"):
            raise ValueError(f"sub_batch_mode 非法值 {sub_batch_mode!r}（仅 direct|211）")
        self._sub_batch_mode = mode
        if int(sub_batch_codec) not in (0, 1):
            raise ValueError(f"sub_batch_codec 非法值 {sub_batch_codec!r}（仅 0|1）")
        self._sub_batch_codec = int(sub_batch_codec)
        self._sub_batch_max_items = max(1, int(sub_batch_max_items))
        self._sub_batch_ack_timeout_s = max(1.0, float(sub_batch_ack_timeout_s))
        self._batch_broken = False   # 会话级熔断：批 ack 超时/ErrResp → 本会话回退单帧
        self._unsub_enabled = bool(unsub_enabled)
        # per-stock 唯一 subId hint（KPL_SUB_UNIQUE_ID，方案 §12）：默认关沿用 cmd
        # （App w30 同款，多股共享 subId）；开启后会话内单调递增 unique hint。
        self._sub_unique_id = bool(sub_unique_id)
        self._sub_id_hint_next = self._SUB_ID_HINT_BASE   # _session 复位
        self._pending_unsub: List[int] = []   # 待退订 subId（2026-11-18 防抖已拆：整队分块一次发）
        # 402 已发帧 seq→subIds（2026-11-17 P3' 实弹：kind5 ack payload=28B 不透明
        # 状态块非 UnsubIdReq 回声，App qn0.d/q 同款按 seq 从原请求取 subIds）
        self._unsub_seq_ids: Dict[int, List[int]] = {}
        self._unsub_frames_sent = 0   # 会话级 402 帧计数（_session 复位，m6）
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
            # 竞价过程事实序列（2026-11-16 用户裁决：页面实时看竞价过程→事实采集落库）
            "bid_series_ok": 0, "bid_series_fail": 0,
            # 09:15/09:25 集合竞价价格+涨幅存档（2026-11-18 用户裁决：3006 现有流）
            "auct15_ok": 0, "auct25_ok": 0, "auct_fail": 0,
            "last_error": ""}
        # 09:15/09:25 快照首帧去重（跨日重置；单写者=本采集线程）
        self._auct_date: str = ""
        self._auct15: set = set()
        self._auct25: set = set()
        # 竞价序列：2026-11-18 窗门控+节流已拆，pid=8 推送即全量落库（§3.9）
        # 龙虎榜快照缓存（task-4 读口）：2112/3004 均**空帧抑制**（同 2103 规：空 items
        # 不覆盖非空快照，仅刷 ts + last_empty_seen；2112 以 total=0 为语义清空）
        self._lhb_forecast_snap: Optional[Dict[str, Any]] = None
        self._lhb_realtime_snap: Optional[Dict[str, Any]] = None
        self._daban_lists: Dict[int, Dict[int, Dict[str, Any]]] = {}   # pidType → {index: 页快照}
        # 板块(801044/885423) + 个股(000001 平安银行)：3001 同时承载板块与个股行情订阅
        self._default_stock_ids = list(stock_ids or ["801044", "885423", "000001"])
        self._stock_ids = list(self._default_stock_ids)
        # 行情订阅面来源（2026-11-18 用户裁决：只进不出累积器是 rst_10054 残余根因
        # ——浏览器 relay 页板块树 merge 717 板块+31 股后永不衰减，852 id×2cmd/会话
        # 全量重发 vs App 离屏即清；ws 全断开时回落默认面，修 SubSource 透出）
        self._sub_source = "default"
        # 末帧归因环（2026-11-18）：1002/杀连时看最后发的是哪类帧
        self._sent_cmd_log: List[Dict[str, Any]] = []
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

    def _capture_auction_price(self, quotes: Dict[str, Any]) -> None:
        """3006 现有流归档 09:15/09:25 价格+涨幅（2026-11-18 用户裁决，零新增订阅）。

        09:15 窗 [09:15,09:25) 首帧=竞价价/涨幅；09:25 窗 [09:25,09:30) 首帧=开盘价/涨幅
        （真 09:25 撮合终值，掉池股亦有）。缩放协议锚（反编译 Hq.java descriptor +
        DataStyleHelper 核实）：price uint32 ×10000→元（App S0=i/10000.0f）；
        incRate proto **float**，本身即百分数（App b() 直显 "#0.00"+"%"，不缩放——
        2026-11-18 复核推翻早期 ×100 错锚，未 live 前修正，零污染）。
        启动晚于 09:25 → s0915 缺席（fail-visible，不拿 09:25 值冒充 09:15）。"""
        from datetime import datetime, timedelta, timezone
        now = time.time()
        dt = datetime.fromtimestamp(now, timezone(timedelta(hours=8)))
        hm = dt.hour * 3600 + dt.minute * 60 + dt.second
        if not (9 * 3600 + 15 * 60 <= hm < 9 * 3600 + 30 * 60):
            return
        date = dt.strftime("%Y-%m-%d")
        if date != self._auct_date:
            self._auct_date = date
            self._auct15 = set()
            self._auct25 = set()
        new15: Dict[str, dict] = {}
        new25: Dict[str, dict] = {}
        for it in (quotes or {}).get("items") or []:
            code = str(it.get("stock_id") or "")[-6:]
            if not code:
                continue
            rec: Dict[str, Any] = {"ts": now}
            try:
                p = float(it.get("price"))
                if p > 0:
                    rec["price"] = round(p / 10000.0, 4)
            except (TypeError, ValueError):
                pass
            try:
                pct = float(it.get("inc_rate"))   # float 原值即百分数，不缩放
                rec["pct"] = round(pct, 4)
            except (TypeError, ValueError):
                pass
            if not ({"price", "pct"} & rec.keys()):
                continue   # price/inc_rate 全缺帧不占首帧名额（fail-visible 不伪存）
            if hm < 9 * 3600 + 25 * 60:
                if code not in self._auct15:
                    self._auct15.add(code)
                    new15[code] = rec
            elif code not in self._auct25:
                self._auct25.add(code)
                new25[code] = rec
        if new15 or new25:
            self._persist_auction_price(date, new15, new25)

    def _persist_auction_price(self, date: str, new15: dict, new25: dict) -> None:
        try:
            db = self._corpus_db()
            if db is None:
                raise RuntimeError("corpus_db_unavailable")
            from backend.services.kpl_daban_archiver import archive_auction_price
            r = archive_auction_price(db, date, s0915=new15, s0925=new25)
            if not r.get("ok"):
                raise RuntimeError(str(r.get("reason")))
            self._corpus_persist_stats["auct15_ok"] += r.get("n15", 0)
            self._corpus_persist_stats["auct25_ok"] += r.get("n25", 0)
        except Exception as exc:  # noqa: BLE001 — 落库失败不阻断收流（fail-visible）
            self._corpus_persist_stats["auct_fail"] += 1
            self._corpus_persist_stats["last_error"] = f"auction_price:{type(exc).__name__}"

    def _persist_corpus(self, lane: str, payload: Dict[str, Any]) -> None:
        """单条推送即时落库（线程内同步写，单写者=本采集线程；失败不阻断收流）。

        lane="theme" → archive_theme_corpus；"reason" → archive_reason_corpus；
        2026-11-11 ③扩展："fc" → archive_lhb_forecast（2112），"rt" →
        archive_lhb_realtime（3004/3101）；④扩展："bdo"/"bf"/"abn"/"rplate" →
        archive_stock_detail_corpus（个股详情四通道，订阅默认关）。
        跨日残留/无交易日/空 payload 由归档函数结构化拒绝（不猜不补）。
        """
        from backend.services.kpl_daban_archiver import (
            archive_bidding_series,
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
               "rplate": lambda db, snap: archive_stock_detail_corpus(db, snap, lane="rplate"),
               "bid_series": archive_bidding_series}
        events = {"theme": "theme_heat_persist", "reason": "zt_reasons_persist",
                  "fc": "lhb_forecast_persist", "rt": "lhb_realtime_persist",
                  "bdo": "stock_detail_persist", "bf": "stock_detail_persist",
                  "abn": "stock_detail_persist", "rplate": "stock_detail_persist",
                  "bid_series": "bidding_series_persist"}
        try:
            # 2026-11-11 评审 nit-6：lane 校验入 try（拼错 lane 走 fail 计数不杀会话）
            if lane not in fns:
                raise ValueError(f"unknown corpus lane: {lane}")
            if lane == "bid_series":
                # 竞价序列日期源=自身合并快照（pid=8 自带 date；早盘 pid=1 池可能无日期，
                # 不能拿池快照当唯一日期源）
                date = str((payload or {}).get("date") or "")
            else:
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

    # App ReconnectManager 忠实移植（§15，替换 §14 拍脑袋 2·2^n/<60s/120s）：
    # 退避梯 j={0,1,2,4,8,15,30}s（App j 数组，末项 WorkRequest.DEFAULT_BACKOFF_DELAY=30000），
    # ±20% 抖动（App v()）；服务端主动断开 base 3s、从未 auth 且断连计数>3 → 60s
    # （App r()/a.d）；服务端断连计数 >10min 间隔衰减（App SocketRepository.i）。
    _APP_RETRY_LADDER_S = (0.0, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
    _APP_RETRY_JITTER = 0.2
    _APP_SERVER_REJECT_BASE_S = 3.0
    _APP_SERVER_REJECT_DEGRADE_S = 60.0
    _APP_SERVER_DISCONNECT_DECAY_S = 600.0
    # PC 适配：App auth-success≈健康长会话（故归零）；PC auth 后仍 ~60s 被杀，
    # 归零判据用健康长会话 >=60s（仅 auth 归零会致每次快重连螺旋）。
    _APP_HEALTHY_SESSION_S = 60.0

    # 211 可批白名单（U1 实弹：仅 hqDaban 全局族受理；2103 列表页/2203/2013/
    # detail per-stock 批内逐项拒 2000+无 topic。仅 2114/2115/2116 经探针验证，
    # 其余同族推定；flag 默认 direct 不启用，白名单为灰度前置硬护栏，review M2）。
    _BATCHABLE_CMDS = frozenset(daban.DABAN_SUB_CMDS)
    # per-stock 唯一 subId hint 基址（方案 §12）：高于 cmd 域（max cmd ~0x0C1D），
    # 避免与全局族 subId=cmd 撞；会话内单调递增，每股独立 subId → 402 精准退单股。
    _SUB_ID_HINT_BASE = 0x4000

    # ---- 订阅注册表化 + 211 批量增强（2026-11-17 P0-P3）----

    def _sub_batch_active(self) -> bool:
        """211 批量信封是否生效：flag=211 且未熔断且非 inline 模式
        （setup_inline_subs 模式始终单帧，方案 §4 P3；「0x40 窗口合同」动机已证伪，
        README §3.7）。"""
        return (self._sub_batch_mode == "211" and not self._batch_broken
                and not self._setup_inline_subs)

    def _batch_fallback(self, reason: str) -> None:
        """会话级熔断：本会话后续订阅回退单帧 drain（fail-visible 事件+计数）。
        触发源：批 ack 超时 / 批 ack 解析失败 / 未决批期间收 ErrResp。
        新会话复位（探针未钉死前不跨会话持久化熔断态）。"""
        if self._batch_broken:
            return
        self._batch_broken = True
        self._stats["batch_fallback_n"] = self._stats.get("batch_fallback_n", 0) + 1
        self._err(f"211 batch fallback to direct: {reason}")
        self._emit(KplEvent(type="batch_fallback", ts=time.time(), reason=reason,
                            session=self._session_no,
                            unacked=self._sub_registry.unacked_batches()))

    def _drain_send(self, sock: Any, next_seq: Any, items: List[Dict[str, Any]],
                    lane: str, *, block_pause: bool = False) -> int:
        """订阅帧发送统一出口（drain 四队列共用；2026-11-17 P3）。

        items=[{cmd, req, ext, key?, priority?, plain?}]。direct 模式逐帧
        （帧序/拟人停顿/enc 回退）；211 模式打包 ≤max_items 项/批信封。
        plain 项走 0x30 普通通道不入注册表（3101，README §3.7）。发送成功后
        register 入注册表（P1 单一事实源）。返回已发项数；OSError 附
        sent_count 上抛，调用方 fail-visible 后 fail-fast 结束会话重连
        （2026-11-18 拆 _sock_dead 静默门禁）。"""
        sent = 0
        try:
            direct_items = list(items)
            if self._sub_batch_active():
                # M2 白名单分流：仅 hqDaban 全局族入批，其余（2103 页/per-stock/
                # detail/lhb）恒 direct——批内必拒通道不得入批（U1 裁决）。
                batchable = [it for it in items if it["cmd"] in self._BATCHABLE_CMDS]
                direct_items = [it for it in items if it["cmd"] not in self._BATCHABLE_CMDS]
                if batchable and self._sub_batch_codec == 1:
                    # m1 预检 enc：任一项失败→熔断+全部回退 direct，绝不产出
                    # codec=0 明文项（U2 实弹：明文→2008 杀连）。
                    if any(not self._codec.enc(it["req"]) for it in batchable):
                        self._stats["batch_enc_fallback_n"] = \
                            self._stats.get("batch_enc_fallback_n", 0) + 1
                        self._batch_fallback("batch_enc_failed")
                        direct_items, batchable = list(items), []
                if batchable:
                    entries = [SubEntry(cmd=it["cmd"], req=it["req"], ext=it["ext"],
                                        seq=0, lane=str(it.get("lane") or lane),
                                        key=str(it.get("key") or ""),
                                        priority=bool(it.get("priority")))
                               for it in batchable]
                    for chunk in self._sub_registry.plan_batches(
                            entries, next_seq, max_items=self._sub_batch_max_items):
                        batch_seq = next_seq()
                        specs = []
                        for spec in chunk:
                            data, codec = spec["data"], 0
                            if self._sub_batch_codec == 1:
                                data, codec = self._codec.enc(spec["data"]), 1  # 预检已保非空
                            specs.append({**spec, "data": data, "codec": codec})
                        pb = proto.build_sub_reqs_pb(specs)
                        enc = self._codec.enc(pb)
                        frame = proto.build_frame(
                            proto.CMD_SUB_BATCH, batch_seq, enc or pb, d=0,
                            encrypted=bool(enc), pkg=proto.PKG_ROUTE,
                            ext=bytes([0x02]) + struct.pack(">H", proto.CMD_SUB_BATCH))
                        self._dbg("C", frame)
                        if sent:
                            self._human_pause(*self._drain_pause)   # 批帧间拟人停顿
                        sock.sendall(frame)
                        now = time.time()
                        chunk_entries = [s["_entry"] for s in chunk]
                        for s, e in zip(chunk, chunk_entries):
                            e.seq = int(s["seqId"])
                            e.sent_at = now
                            self._sub_registry.register(e)
                        self._sub_registry.bind_batch(batch_seq, chunk_entries)
                        self._sub_registry.track_batch(batch_seq, len(chunk), now)
                        self._stats["batch_frames_sent"] = \
                            self._stats.get("batch_frames_sent", 0) + 1
                        sent += len(chunk)
            for it in direct_items:
                enc = self._codec.enc(it["req"])
                seq = next_seq()
                plain = bool(it.get("plain"))
                # 2026-11-18 源码定案：plain 项（3101 一次性查询）走 0x30 普通通道
                # 无 ext 路由头、不入注册表（App e((byte)3) 同款；0x40 通道发 3101
                # = ErrResp 1002 杀连）
                frame = proto.build_frame(it["cmd"], seq, enc or it["req"], d=0,
                                          encrypted=bool(enc),
                                          pkg=proto.PKG_AUTH if plain else proto.PKG_ROUTE,
                                          ext=b"" if plain else it["ext"])
                self._dbg("C", frame)
                if sent and not block_pause:
                    self._human_pause(*self._drain_pause)   # 帧间拟人停顿（节奏实验旋钮）
                sock.sendall(frame)
                if not plain:
                    self._sub_registry.register(SubEntry(
                        cmd=it["cmd"], req=it["req"], ext=it["ext"], seq=seq,
                        lane=str(it.get("lane") or lane), key=str(it.get("key") or ""),
                        priority=bool(it.get("priority")), sent_at=time.time()))
                else:
                    self._stats["plain_req_sent"] = self._stats.get("plain_req_sent", 0) + 1
                sent += 1
                if block_pause:
                    self._human_pause(*self._drain_pause)   # detail 块尾停顿（flush 合同）
            return sent
        except OSError as exc:
            exc.sent_count = sent   # 调用方 drop 计数/回队用
            raise

    def _flush_pending_inline(self, sock: Any, next_seq: Any, lane: str) -> None:
        """setup_inline_subs 模式：待发订阅帧 setup 内一次性连发（App qn0.z()
        连接后一次性全发 b 队列同款，零分波）。历史注：当初「0x40 帧窗口关闭后
        发送→1002」的动机已证伪——11-18 源码定案 ErrResp 1002 真凶=3101 错用
        0x40 通道（README §3.7），E1-E4 探针结论同为该误归因；inline 保留纯因
        App 同款且实弹稳定。OSError 直接上抛交给 _run_loop 重连链（此时
        连接已死，继续 setup 无意义，fail-visible 由 network 错误日志承载）。"""
        if lane == "setup":
            items = list(self._pending_setup_frames)
            self._pending_setup_frames = []
            for it in items:
                enc = self._codec.enc(it["req"])
                # pkg=0x40 订阅路由（2026-11-10 根因修复：daban 族帧此前漏传 pkg，
                # build_frame 默认 0x30 鉴权通道 + ext 路由头=非法帧，服务器杀连）；
                # plain 项（3101）走 0x30 普通通道（2026-11-18 源码定案，不入注册表）
                seq = next_seq()
                plain = bool(it.get("plain"))
                frame = proto.build_frame(it["cmd"], seq, enc or it["req"], d=0,
                                          encrypted=bool(enc),
                                          pkg=proto.PKG_AUTH if plain else proto.PKG_ROUTE,
                                          ext=b"" if plain else it["ext"])
                self._human_pause(*self._drain_pause)
                self._dbg("C", frame)
                sock.sendall(frame)
                if plain:
                    self._stats["plain_req_sent"] = self._stats.get("plain_req_sent", 0) + 1
                    continue
                self._sub_registry.register(SubEntry(
                    cmd=it["cmd"], req=it["req"], ext=it["ext"], seq=seq,
                    lane="setup", priority=bool(it.get("priority")),
                    sent_at=time.time()))
            return
        if lane == "detail":
            # 2026-11-11 评审 major-2：setup_inline_subs=True 时详情四通道改 setup
            # 内联发送（同 2203/2013 的 zt_reason/theme lane）。「窗口关闭后 0x40→1002」
            # 动机已证伪（真凶=3101 错通道，README §3.7）。OSError 上抛交 _run_loop 重连链。
            for dl, dcmd in self._detail_lane_cmds.items():
                with self._detail_locks[dl]:
                    batch = list(self._pending_detail[dl])
                    self._pending_detail[dl].clear()
                for sid in batch:
                    req = self._detail_req_for(dcmd, sid)
                    enc = self._codec.enc(req)
                    seq = next_seq()
                    dext = self._stock_sub_ext(dcmd)   # per-stock 唯一 subId hint（§12）
                    frame = proto.build_frame(dcmd, seq, enc or req, d=0,
                                              encrypted=bool(enc), pkg=proto.PKG_ROUTE,
                                              ext=dext)
                    self._dbg("C", frame)
                    sock.sendall(frame)
                    self._sub_registry.register(SubEntry(
                        cmd=dcmd, req=req, ext=dext, seq=seq,
                        lane=f"detail:{dl}", key=sid, sent_at=time.time()))
                    self._human_pause(*self._drain_pause)
            return
        lock, pending_ref = ((self._zt_reason_lock, self._pending_zt_reason) if lane == "zt_reason"
                             else (self._theme_lock, self._pending_theme))
        with lock:
            batch = list(pending_ref)
            pending_ref.clear()
        cmd = proto.CMD_HQ_REASONS if lane == "zt_reason" else proto.CMD_STOCK_RELATED_THEME
        for sid in batch:
            req = proto.build_hq_req_pb(sid)
            enc = self._codec.enc(req)
            ext = self._stock_sub_ext(cmd)   # per-stock 唯一 subId hint（§12）
            seq = next_seq()
            frame = proto.build_frame(cmd, seq, enc or req, d=0,
                                      encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=ext)
            self._human_pause(*self._drain_pause)
            self._dbg("C", frame)
            sock.sendall(frame)
            self._sub_registry.register(SubEntry(
                cmd=cmd, req=req, ext=ext, seq=seq, lane=lane, key=sid,
                sent_at=time.time()))

    def _drain_setup_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待发 setup 订阅帧（daban 家族 21xx/2103/2112/3004/3101，2026-11-10 重排）。

        历史注：当年「setup 结束后 ~1s 被上游 RST」的误归因已证伪——真凶=队列尾
        3101 错用 0x40 通道（README §3.7，2026-11-18 源码定案）。2026-11-18 拆
        门控：整队一次发完（帧间拟人停顿保留）；sendall 失败 fail-fast 结束会话
        重连重建（拆 _sock_dead）；inline 模式循环期不再静默（新入池成员续发）。
        plain 项（3101）必须透传（独立 review blocker-1：丢键=杀连帧型复活）。"""
        if not self._pending_setup_frames:
            return
        batch = self._pending_setup_frames   # 2026-11-18 拆 8 帧/tick 限流：整队一次发完
        self._pending_setup_frames = []
        items = [{"cmd": it["cmd"], "req": it["req"], "ext": it["ext"],
                  "priority": it.get("priority"),
                  "key": it.get("key"), "lane": it.get("lane"),
                  # 2026-11-18 独立 review blocker-1 修复：plain 必须透传——丢键则
                  # 3101 在非 inline/staged 路径以 0x40+ext 发出，复活 1002 杀连帧型
                  "plain": it.get("plain")} for it in batch]   # m4：保留 key/lane
        try:
            self._drain_send(sock, next_seq, items, "setup")
        except OSError as exc:
            sent = getattr(exc, "sent_count", 0)
            dropped = len(batch) - sent + len(self._pending_setup_frames)
            self._stats["setup_send_drops"] = self._stats.get("setup_send_drops", 0) + dropped
            fail_cmd = items[min(sent, len(items) - 1)]["cmd"] if items else 0
            self._err(f"setup subscribe send failed (cmd={fail_cmd}): {exc} "
                      f"(sent={sent} dropped={dropped}, fail-fast reconnect)")
            self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                lane="setup", cmd=fail_cmd,
                                sent=sent, dropped=dropped, session=self._session_no,
                                error=str(exc)))
            raise   # 2026-11-18 拆 _sock_dead：send 失败=连接已死，结束会话重连重建
        # 队深观测随 drain 递减（评审 P2：否则 status 读到的是会话初队深非当前队深）
        self._stats["queued_setup_subs"] = len(self._pending_setup_frames)

    def _stock_sub_ext(self, cmd: int) -> bytes:
        """per-stock 订阅 ext attr2（subId hint）。唯一 hint 模式（KPL_SUB_UNIQUE_ID）
        会话内单调递增，使服务端授予每股独立 subId → 402 可精准退单股（方案 §12）；
        否则沿用 cmd（App w30 同款，多股共享 subId，402 仅全局族可用）。
        仅改 ext hint，帧头 cmd 与 req{stockId} 不变 → 推送按 topic 路由不受影响。"""
        hint = self._next_sub_id_hint() if self._sub_unique_id else cmd
        return bytes([0x02]) + struct.pack(">H", hint)

    def _next_sub_id_hint(self) -> int:
        v = self._sub_id_hint_next
        self._sub_id_hint_next += 1
        if self._sub_id_hint_next > 0x7FFF:   # Short 正域上限（理论上 ~110/会话远不及）
            self._sub_id_hint_next = self._SUB_ID_HINT_BASE
        return v

    def _drain_zt_reason_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待订阅 2203 帧（仅会话线程调用）。2026-11-18 拆门控：整队一次
        发完（帧间拟人停顿保留）；sendall 失败 fail-visible 后 fail-fast 结束
        会话重连，下一会话 6g 全量补订自愈。"""
        if not self._zt_reason_subs:
            return
        with self._zt_reason_lock:
            pending = list(self._pending_zt_reason)
            self._pending_zt_reason = []
        if not pending:
            return
        batch = pending   # 2026-11-18 拆 8 帧/tick 限流：整队一次发完（帧间拟人停顿保留）   # 回队头保序，下一 tick 续发
        items = [{"cmd": proto.CMD_HQ_REASONS, "req": proto.build_hq_req_pb(sid),
                  "ext": self._stock_sub_ext(proto.CMD_HQ_REASONS), "key": sid} for sid in batch]
        try:
            self._drain_send(sock, next_seq, items, "zt_reason")
        except OSError as exc:
            sent = getattr(exc, "sent_count", 0)
            dropped = len(batch) - sent
            self._stats["zt_reason_send_drops"] = self._stats.get("zt_reason_send_drops", 0) + dropped
            fail_sid = batch[min(sent, len(batch) - 1)] if batch else ""
            self._err(f"2203 subscribe send failed ({fail_sid}): {exc} "
                      f"(sent={sent} dropped={dropped}, fail-fast reconnect)")
            self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                lane="zt_reason", cmd=proto.CMD_HQ_REASONS,
                                sent=sent, dropped=dropped, session=self._session_no,
                                error=str(exc)))
            raise   # 2026-11-18 拆 _sock_dead：send 失败=结束会话重连重建

    def _queue_detail_new(self, stock_ids: List[str]) -> int:
        """四通道新入池成员入队订阅（去重；会话线程 drain 块发）。开关关 → 零动作。

        2026-11-18 用户裁决删每 lane 硬帽：全量新成员入队（超限永不采集=
        数据拒绝，§4.0）；块发后静默 flush 合同不变。"""
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
        """发送待订阅 2013 帧（与 _drain_zt_reason_subs 同款：整队一次发完，
        send 失败 fail-fast 重连，下一会话 6g 全量补订自愈）。"""
        if not self._theme_subs:
            return
        with self._theme_lock:
            pending = list(self._pending_theme)
            self._pending_theme = []
        if not pending:
            return
        batch = pending   # 2026-11-18 拆 8 帧/tick 限流：整队一次发完（帧间拟人停顿保留）
        items = [{"cmd": proto.CMD_STOCK_RELATED_THEME, "req": proto.build_hq_req_pb(sid),
                  "ext": self._stock_sub_ext(proto.CMD_STOCK_RELATED_THEME), "key": sid} for sid in batch]
        try:
            self._drain_send(sock, next_seq, items, "theme")
        except OSError as exc:
            sent = getattr(exc, "sent_count", 0)
            dropped = len(batch) - sent
            self._stats["theme_send_drops"] = self._stats.get("theme_send_drops", 0) + dropped
            fail_sid = batch[min(sent, len(batch) - 1)] if batch else ""
            self._err(f"2013 subscribe send failed ({fail_sid}): {exc} "
                      f"(sent={sent} dropped={dropped}, fail-fast reconnect)")
            self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                lane="theme", cmd=proto.CMD_STOCK_RELATED_THEME,
                                sent=sent, dropped=dropped, session=self._session_no,
                                error=str(exc)))
            raise   # 2026-11-18 拆 _sock_dead：send 失败=结束会话重连重建

    # 详情四通道发送语义（2026-11-11 探针 K1/K3/I1 定案）：服务器对 detail 订阅的
    # 响应是「静默期 flush」——订阅帧连续发送期间零响应，发送停止后 <1s 内全量
    # 批回（K1：10 帧块停发后 0.3s 即回 19 帧；K3：124 帧连发 50s 后 0.1s 内
    # 批回 142 帧）。因此 drain 整队列块发（一次调用发完 pending，随后读循环
    # 自然静默 → flush）。2026-11-18 用户裁决删每 lane 15 只硬帽：超限成员
    # 永不采集=数据拒绝（§4.0）；全量入队，块长由池深决定（跨会话续发自愈）。

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
        send 失败 fail-fast 结束会话重连，下一会话 6g 全量补订自愈。
        setup_inline_subs=True 时 setup 队列已由 6h _flush_pending_inline 内联
        发完；循环期新入池成员仍由本函数续发（2026-11-18 拆 inline 循环期静默，
        App 屏 onResume 随时可发订阅）。"""
        if not self._stock_detail_subs:
            return
        for lane, cmd in self._detail_lane_cmds.items():
            with self._detail_locks[lane]:
                batch = list(self._pending_detail[lane])
                self._pending_detail[lane] = []
            items = [{"cmd": cmd, "req": self._detail_req_for(cmd, sid),
                      "ext": self._stock_sub_ext(cmd), "key": sid} for sid in batch]
            try:
                self._drain_send(sock, next_seq, items, f"detail:{lane}",
                                 block_pause=True)
            except OSError as exc:
                sent = getattr(exc, "sent_count", 0)
                rest = batch[sent:]
                with self._detail_locks[lane]:
                    self._pending_detail[lane][:0] = rest
                self._stats["detail_send_drops"] = \
                    self._stats.get("detail_send_drops", 0) + len(rest)
                fail_sid = batch[min(sent, len(batch) - 1)] if batch else ""
                self._err(f"detail {lane} subscribe send failed ({fail_sid}): {exc} "
                          f"(sent={sent} dropped={len(rest)}, fail-fast reconnect)")
                self._emit(KplEvent(type="subscribe_send_dropped", ts=time.time(),
                                    lane=lane, cmd=cmd, sent=sent,
                                    dropped=len(rest), session=self._session_no,
                                    error=str(exc)))
                raise   # 2026-11-18 拆 _sock_dead：send 失败=结束会话重连重建

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
        self._sub_source = "dynamic"
        return {"ok": True, "count": len(self._stock_ids),
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
            # 订阅注册表/211 批量/402 退订观测（2026-11-17 P0-P3，fail-visible）
            "sub_registry": self._sub_registry.stats(),
            "sub_registry_enabled": self._sub_registry_enabled,
            "sub_batch_mode": self._sub_batch_mode,
            "sub_batch_active": self._sub_batch_active(),
            "batch_frames_sent": self._stats.get("batch_frames_sent", 0),
            "batch_fallback_n": self._stats.get("batch_fallback_n", 0),
            "unsub_enabled": self._unsub_enabled,
            "unsub_sent_n": self._stats.get("unsub_sent_n", 0),
            "unsub_pending_n": len(self._pending_unsub),
            "ka_mode": self._ka_mode,
            "sub_unique_id": self._sub_unique_id,
            # 分波订阅观测（2026-11-17 iso1 体积阈值定案；KPL_SUB_STAGED 默认关）
            "sub_staged": self._sub_staged,
            "staged_pending_n": sum(len(w.get("frames") or []) for w in self._staged_waves)
                                + sum(w.get("remaining") or 0 for w in self._staged_waves
                                      if w.get("kind") == "perstock"),
            "staged_released_n": self._stats.get("staged_released_n", 0),
            "staged_dropped_n": self._stats.get("staged_dropped_n", 0),
            "staged_pool_cursor": self._staged_pool_cursor,
            "staged_funnel_batches": self._stats.get("staged_funnel_batches", 0),
            # 订阅构成观测（2026-11-11 行业页签空态排查）：hy=881 行业板块数，
            # 页面引导/补引导是否落地一眼可核（fail-visible，不藏状态）
            "subscriptions": {
                "count": len(self._stock_ids),
                "source": self._sub_source,
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
            # 重连螺旋防线观测（2026-11-10）：连续短命会话退避秒数 + 当前连击数
            "reconnect_backoff_s": self._stats.get("reconnect_backoff_s"),
            "retry_fail_count": self._retry_fail_count,
            # App 忠实移植观测（§15）：服务端断连计数 + 本次退避决策依据死因
            "server_disconnect_count": self._server_disconnect_count,
            "last_backoff_cause": self._stats.get("last_backoff_cause"),
            # 死因分类观测：爆发指纹 RST(10054) vs ErrResp 杀连 vs 干净 EOF；退避决策底座
            "last_death_cause": self._last_death_cause,
            "death_cause_counts": dict(self._death_cause_counts),
            "last_session_err_code": self._session_err_code,
            "last_err_resp": self._stats.get("last_err_resp"),
            "sent_cmd_log": list(self._sent_cmd_log[-12:]),
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

    def subscriber_count(self) -> int:
        """当前事件订阅者数（ws 客户端）；0 = 无浏览器在听（回落判据）。"""
        with self._subs_lock:
            return len(self._subs)

    def reset_subscriptions_to_default(self) -> Dict[str, Any]:
        """行情订阅面回落默认（2026-11-18 用户裁决，App 同款离屏生命周期）。

        根因：relay 页 merge 进来的板块/个股 id 只进不出，浏览器关闭后仍每会话
        全量重发（852 id×2cmd），构成 rst_10054 残余超支。浏览器 ws 全断开时由
        serve 层调用本方法；页面重开时自会重新 POST。默认面=构造参数（3 id）。
        fail-visible：结构化返回变更前后，不掭不假。
        """
        with self._subs_lock:
            before = {"count": len(self._stock_ids), "prio": len(self._sub_prio_all)}
            self._stock_ids = list(self._default_stock_ids)
            self._sub_prio_all = []
            self._resplit()
            self._sub_source = "default"
            after = {"count": len(self._stock_ids), "prio": 0}
        return {"ok": True, "before": before, "after": after,
                "default_ids": list(self._default_stock_ids)}

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

    def _classify_death_cause(self, exc: Optional[BaseException]) -> str:
        """会话死因分类（2026-11-17 纯观测，零行为变更）。

        区分爆发指纹 RST(10054) / ErrResp 杀连(1106/1002/2008) / 干净 EOF /
        网络/auth/反作弊失败，供隔离探针（README §3.4 爆发指纹议题）与**死因感知
        退避**（§14，App ReconnectManager 对齐）提供实证底座。

        判据优先级：异常类型/winerror → 本会话 ErrResp code →
        setup 早退 → 干净 EOF。（drain send 失败已改 fail-fast 上抛，走异常分类。）10054=服务器 RST；1106/1002=ErrResp 杀连；2008=明文
        211 lethal；eof_clean=无错误码服务器关连（干净轮换）。历史注：「爆发指纹主导」
        归因已证伪（10054=3001 跑步机超支、1002=3101 错通道，README §3.7）。
        """
        if exc is not None:
            winerr = getattr(exc, "winerror", None)
            if isinstance(exc, ConnectionResetError) or winerr == 10054:
                return "rst_10054"
            if winerr == 10053:
                return "abort_10053"
            if isinstance(exc, SignSvcError):
                return "signsvc"
            if isinstance(exc, AntiCheatError):
                return "anti_cheat"
            if isinstance(exc, socket.timeout):
                return "timeout"
            return f"network:{type(exc).__name__}"
        # 无异常 = _session 正常 return（服务器关连 / setup 早退 / ErrResp 后关连）
        code = self._session_err_code
        if code is not None:
            return f"errresp_{code}"
        if not self._session_streaming:
            return "setup_fail"
        return "eof_clean"

    @staticmethod
    def _is_server_reject(cause: str) -> bool:
        """服务端拒绝类死因（App f6127a==20 「服务器主动断开」）：风控 RST/ErrResp 杀连。
        这类退避走 App r()：base 3s + 螺旋，连续 >3 降级 60s。"""
        return cause == "rst_10054" or cause.startswith("errresp_")

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

        窗口：09:00-11:30、13:00-15:35（2026-11-17 用户裁决 09:15→09:00：序列
        首帧基线须覆盖 09:15:00 竞价起点——09:15 建连+订阅爆发时序使首 tick 恒晚
        ~1min，涨停开盘股拉升段被跳过（11-17 对拍 first比 2-3.5× 实证）；09:00
        建连给竞价池订阅留 15min 预热；下午收盘 15:30——交易所规则
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
        return (9 * 60 <= hm < 11 * 60 + 30) or (13 * 60 <= hm < 15 * 60 + 35)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            # 交易时段门控：非交易时段不建连（idle_offhours，每分钟复查；
            # 状态与事件均 fail-visible，页面/日志可感知挂起与恢复）
            if self._enforce_trading_hours and not self._in_trading_session():
                if self._status != "idle_offhours":
                    self._status = "idle_offhours"
                    self._emit(KplEvent(type="status", ts=time.time(), status="idle_offhours",
                                        note="非交易时段，采集挂起（不建连；09:00/13:00 自动恢复）"))
                if self._stop.wait(60.0):
                    break
                continue
            if self._status == "idle_offhours":
                self._emit(KplEvent(type="status", ts=time.time(), status="trading_session_start",
                                    note="进入交易时段，采集恢复"))
            self._session_no += 1
            self._stats["sessions"] += 1
            t_session = time.time()
            backoff = 0.0   # App 梯从 0 起（§15）；signsvc/anticheat 下方设 5s 地板
            death_exc: Optional[BaseException] = None   # 死因观测：捕获会话异常（不改退避）
            try:
                self._session()
            except (ssl.SSLError, OSError, socket.timeout) as exc:
                death_exc = exc
                self._err(f"session#{self._session_no} network: {type(exc).__name__}: {exc}")
            except SignSvcError as exc:
                death_exc = exc
                self._err(f"session#{self._session_no} signsvc: {exc}")
                # signsvc 故障重试间隔拉长
                backoff = 5.0
            except AntiCheatError as exc:
                death_exc = exc
                # 261 无法作答 → 不发假答案，直接断连重建（App 同款行为）；
                # 退避拉长到 5s：若 261 周期性下发，2s 快速重连会刷屏（评审 R1-P2）
                self._err(f"session#{self._session_no} anti_cheat: {exc}")
                backoff = 5.0
            except Exception as exc:  # 未知异常也必须 fail-visible
                death_exc = exc
                self._err(f"session#{self._session_no} unexpected: {type(exc).__name__}: {exc}")
            finally:
                # 会话时长观测（2026-11-09 抖动根因验证）：在重连退避之前记录，否则
                # backoff 会被算进会话时长污染 §3.4 时长档对照（评审 MINOR）
                self._stats["last_session_s"] = round(time.time() - t_session, 1)
                # 死因分类观测（2026-11-17 纯观测，零行为变更）：独立于下方退避计算，
                # 只记录+发事件，不改变重连时机/螺旋阈值（爆发指纹议题实证底座）。
                cause = self._classify_death_cause(death_exc)
                self._last_death_cause = cause
                self._death_cause_counts[cause] = self._death_cause_counts.get(cause, 0) + 1
                self._emit(KplEvent(type="session_death", ts=time.time(),
                                    session=self._session_no, cause=cause,
                                    session_s=self._stats["last_session_s"],
                                    err_code=self._session_err_code,
                                    ))
            # App ReconnectManager 忠实移植（§15，替换 §14 拍脑袋 2·2^n/<60s/120s）：
            # backoff = 梯[min(fail,6)]±20% + server_extra；fail++；健康长会话(>=60s)归零。
            # server_extra：服务端主动断开(rst_10054/errresp_*) +3s；从未 auth(未 streaming)
            #   且服务端断连计数>3 → +60s（App r()/a.d）。干净/网络 → 仅梯（首 retry ~0s）。
            # PC 适配：App auth-success 归零（App auth≈健康）；PC auth 后仍 60s 被杀，故
            #   归零用健康长会话>=60s；「从未 auth」用 per-session _session_streaming。
            # 实证底座：冷却 3min 后单会话 6s→67.6s。App 梯封顶 30s(+3s=33s) < 旧 120s，
            #   首 retry ~0s < 旧 2s——对 PC 不可信指纹防护可能偏弱，须探针验证后加载生产。
            cause = self._last_death_cause
            healthy = self._stats["last_session_s"] >= self._APP_HEALTHY_SESSION_S
            # 2026-11-18 修复：eof_clean=服务端计划内 TTL 轮转（非失败），App 同款
            # 秒级重连——不计 fail、不进退避梯（归零后梯[0]=0 + jitter≤0.3s）。
            # 此前 41s TTL 会话低于 60s 健康阈 → fail 累积爬梯至 35s，会话间
            # ~35s 数据空窗（利用率 ~55%，11-18 盘中实弹观测）。真失败类死因
            # （rst/errresp/网络）退避语义不变。
            if cause == "eof_clean":
                self._retry_fail_count = 0
                # 权衡注（独立 review note-4）：EOF/拒绝交替序列下 sd_count 每次被
                # EOF 清零，「>3 且从未 auth→+60s」降级永不累积，每次拒绝只拿梯[0]+3s。
                # 与「计划内轮转非失败」语义自洽（App 亦仅在 ErrResp 置 state=20 增 b）。
                self._server_disconnect_count = 0
            if healthy:
                # App u()/j() resetFailCount：健康长会话证明恢复（PC 适配判据）
                self._retry_fail_count = 0
                self._server_disconnect_count = 0
            server_active = self._is_server_reject(cause)
            now = time.time()
            if server_active:
                if now - self._last_server_disconnect_ts > self._APP_SERVER_DISCONNECT_DECAY_S:
                    self._server_disconnect_count = 0   # App i()：>10min 间隔衰减
                self._server_disconnect_count += 1      # App i()：服务端断连计数
                self._last_server_disconnect_ts = now
            base = self._APP_RETRY_LADDER_S[
                min(self._retry_fail_count, len(self._APP_RETRY_LADDER_S) - 1)]
            if base > 0:
                jittered = base * (1.0 + random.uniform(-self._APP_RETRY_JITTER,
                                                        self._APP_RETRY_JITTER))
            else:
                jittered = random.uniform(0.0, 0.3)     # App v()：j3==0 → nextInt(301)ms
            server_extra = 0.0
            if server_active:
                server_extra = self._APP_SERVER_REJECT_BASE_S
                if not self._session_streaming and self._server_disconnect_count > 3:
                    server_extra = self._APP_SERVER_REJECT_DEGRADE_S
            backoff = max(jittered + server_extra, backoff)   # backoff=signsvc/anticheat 5s 地板或 0
            if cause != "eof_clean":                          # eof_clean=计划内轮转，不消耗 fail 计数
                self._retry_fail_count += 1                   # App v()：c++
            self._stats["reconnect_backoff_s"] = round(backoff, 3)
            self._stats["last_backoff_cause"] = cause
            if self._stop.is_set():
                break
            self._status = "reconnecting"
            self._stop.wait(backoff)
        self._status = "stopped"

    def _dbg(self, direction: str, data: bytes) -> None:
        if direction == "C" and len(data) >= 9:
            # 末帧归因环（2026-11-18）：帧头=[pkg 1][len 4][seq 2][cmd 2]，cmd 在 [7:9]
            cmd = int.from_bytes(data[7:9], "big")
            self._sent_cmd_log.append({"cmd": cmd, "ts": time.time()})
            if len(self._sent_cmd_log) > 40:
                del self._sent_cmd_log[:-40]
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
            if seq[0] >= 32767:   # App t31.c 同款：≥Short.MAX_VALUE 回绕到 1
                seq[0] = 1
            return seq[0]

        sock = self._tls_connect()
        self._rx = bytearray()   # 新会话新流：残帧缓冲必须清零
        self._session_err_code = None   # 死因观测：本会话 ErrResp code 复位
        self._session_streaming = False  # 死因观测：收流标志复位
        # 分波订阅：上会话未释放波次随会话作废（下会话重建；fail-visible 计数）
        if self._staged_waves:
            dropped = sum(len(w.get("frames") or []) for w in self._staged_waves)
            dropped += sum(w.get("remaining") or 0 for w in self._staged_waves
                           if w.get("kind") == "perstock")
            self._stats["staged_dropped_n"] = self._stats.get("staged_dropped_n", 0) + dropped
        self._staged_waves = []
        self._staged_t0 = time.time()
        self._pending_setup_frames = []   # 新会话重建订阅面：上会话残留待发帧作废
        self._sub_registry.clear_session()   # App qn0.f：断线清空注册表（c/d/e）
        self._batch_broken = False   # 熔断会话级复位（新会话重新尝试 211，若 flag 开）
        self._pending_unsub = []     # 退订队随会话重建作废（订阅面本就要全量重建）
        self._unsub_seq_ids = {}
        self._unsub_frames_sent = 0
        self._sub_id_hint_next = self._SUB_ID_HINT_BASE   # 唯一 hint 会话级复位（§12）
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
                if fr.get("cmd") == proto.CMD_CHALLENGE:
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
            # 2026-11-18 用户裁决拆 auth_phase_delay：App qn0:375 收 260 challenge
            # 即调 userAuth 零延迟（源码实锤）；旧「auth 耗时与会话时长单调相关」
            # 是证伪建模时代产物（会话死因真凶=3101 错通道+3001 跑步机，§3.7）。
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
                if fr.get("fmt") == "echo" and fr.get("cmd") == proto.CMD_AUTH:
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
                if fr.get("cmd") == proto.CMD_ERROR:
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
                gq_seq = next_seq()
                gq_frame = proto.build_frame(proto.CMD_GROUP_QUOTAS, gq_seq, enc_gq or gq, d=0,
                                             encrypted=bool(enc_gq), pkg=proto.PKG_ROUTE, ext=ext3)
                self._human_pause(0.3, 0.15)
                self._dbg("C", gq_frame)
                sock.sendall(gq_frame)
                # 内联订阅也入注册表（2026-11-17 探针实弹：ack attr3 topic 与推送 ext
                # 逐字节匹配；3001/3006 不登记则 topic 命中率观测永远缺口）
                self._sub_registry.register(SubEntry(
                    cmd=proto.CMD_GROUP_QUOTAS, req=gq, ext=ext3, seq=gq_seq,
                    lane="setup", key=",".join(chunk), sent_at=time.time()))
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
                hq_seq = next_seq()
                hq_frame = proto.build_frame(proto.CMD_HQ_ID_LIST, hq_seq, enc_hq or hq, d=0,
                                             encrypted=bool(enc_hq), pkg=proto.PKG_ROUTE, ext=ext6)
                self._human_pause(0.3, 0.15)
                self._dbg("C", hq_frame)
                sock.sendall(hq_frame)
                self._sub_registry.register(SubEntry(
                    cmd=proto.CMD_HQ_ID_LIST, req=hq, ext=ext6, seq=hq_seq,
                    lane="setup", key=",".join(chunk), sent_at=time.time()))
            # 分波订阅（KPL_SUB_STAGED=1）：wave2 收集非竞价 2103 页 + lhb 帧
            staged_wave2_frames: List[Dict[str, Any]] = []
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
                    # P1 例外（见 __init__ 注）：仅 pid=8 竞价池保页深，其余池 1 页
                    n_pages = self._daban_list_pages if pid == 8 else 1
                    for page in range(n_pages):
                        req_pb = daban.build_daban_stock_list_req_pb(
                            pid, index=page * self._daban_list_page_size,
                            count=self._daban_list_page_size)
                        frame = {
                            "cmd": daban.CMD_DABAN_STOCK_LIST, "req": req_pb,
                            "ext": bytes([0x02]) + struct.pack(">H", daban.CMD_DABAN_STOCK_LIST),
                            # 2026-11-17 订阅爆发时序修复：竞价池（pid=8）页前插。
                            # 根因：原排序在情绪帧之后（setup 队列第 9-15 位），
                            # drain 速率 8 帧/迭代×4 队列×0.3s 拟人停顿 → 订阅帧
                            # 落地会话 ~15-40s，服务端初始页推送（仅订阅后到达）
                            # 实测 ~40-50s，与 ~50s 会话寿限贴线 → 序列首 tick
                            # 恒晚（11-17 实证 09:15:57）。前插后首迭代即发
                            # （~2-5s），每个短命会话都收到竞价池初始爆发。
                            "priority": pid == 8,
                        }
                        if self._sub_staged and pid != 8:
                            staged_wave2_frames.append(frame)   # 分波：非竞价页入 wave2(+15s)
                        else:
                            self._pending_setup_frames.append(frame)
                if not self._sub_staged:
                    # 稳定前插：pid=8 页保持页序移至 setup 队列最前（其余帧序不变）
                    self._pending_setup_frames.sort(key=lambda f: not f.get("priority"))
            # 6e) 2112 会不会上龙虎榜预测订阅（2026-10-29 逆向）：0x40 通道同 daban 家族，
            #     ForecastLHBReq 基线 count=30/sortType=1/quotaType=0（LhbWillStockModel.k(2112)）；
            #     开关独立于 daban_subs（与打板/情绪订阅解耦）
            if self._daban_lhb:
                lhb_frame = {
                    "cmd": daban.CMD_FORECAST_LHB, "req": daban.build_forecast_lhb_req_pb(),
                    "ext": bytes([0x02]) + struct.pack(">H", daban.CMD_FORECAST_LHB),
                }
                if self._sub_staged:
                    staged_wave2_frames.append(lhb_frame)   # 分波：lhb 非关键延后
                else:
                    self._pending_setup_frames.append(lhb_frame)
            # 6f) 3004 RealtimeLHB 订阅（0x40 通道 ext 路由头）+ 3101 当日区间单发
            #     （2026-11-18 源码定案：App MainIndexQuotationInfoPresenter L288/
            #     RealTimeChartsPresenter L288 发 3101 用 e((byte)3)→pkg=0x30 普通请求帧
            #     （ux0.p()=(f11466a<<4) 反编译实锶），从不走 0x40 订阅通道；我们旧版
            #     把 3101 当 0x40 订阅发→服务器拒收 ErrResp 1002 杀连（每会话必死，
            #     被 rst_10054 跑步机长期掩盖）。3101=一次性查询：不注册表、不 402 退订。
            #     Req 基线见 kpl_lhb_protocol.REALTIME_LHB_BASELINE，App 原 UI count=1，
            #     采集放宽 30）
            if self._lhb_realtime:
                req_sub = lhb.build_realtime_lhb_req_pb(count=self._lhb_realtime_count)
                reqs_lhb = [(lhb.CMD_REALTIME_LHB_SUB, req_sub, False),
                            (lhb.CMD_REALTIME_LHB_RANGE,
                             lhb.build_realtime_lhb_req_pb(
                                 count=self._lhb_realtime_count,
                                 start_time=925, end_time=int(time.strftime("%H%M"))),
                             True)]   # True=plain 0x30 单发（App 同款）
                for lhb_cmd, req_rl, plain in reqs_lhb:
                    lhb_frame = {
                        "cmd": lhb_cmd, "req": req_rl,
                        "ext": bytes([0x02]) + struct.pack(">H", lhb_cmd),
                        "plain": plain,
                    }
                    if self._sub_staged:
                        staged_wave2_frames.append(lhb_frame)   # 分波：lhb 非关键延后
                    else:
                        self._pending_setup_frames.append(lhb_frame)
            if self._sub_staged:
                # wave2（+15s）：非竞价 2103 页 + lhb 帧（「37 帧阈值」模型已证伪，
                # README §3.7；staged1 稳定性观测保留作历史参考）
                self._staged_waves.append({
                    "release_at": self._staged_t0 + self._STAGED_WAVE2_S,
                    "failsafe_at": self._staged_t0 + self._STAGED_FAILSAFE_S,
                    "kind": "pages", "frames": staged_wave2_frames,
                })
            # 6g-pre) 内联模式下（「0x40 只许 setup 窗口内」的 E1-E4 结论已证伪，
            # 真凶=3101 错通道，README §3.7；inline 保留=App 同款）
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
            pool_ids = self._pool_stock_ids()
            if self._zt_reason_subs:
                with self._zt_reason_lock:
                    self._zt_reason_subscribed.clear()
                    self._pending_zt_reason.clear()
                if not self._sub_staged:
                    self._queue_zt_reason_new(pool_ids)   # staged: 池 ids 入 wave3(+90s)
                if self._setup_inline_subs:
                    self._flush_pending_inline(sock, next_seq, "zt_reason")
            if self._theme_subs:
                with self._theme_lock:
                    self._theme_subscribed.clear()
                    self._pending_theme.clear()
                if not self._sub_staged:
                    self._queue_theme_new(pool_ids)   # staged: 池 ids 入 wave3(+90s)
                if self._setup_inline_subs:
                    self._flush_pending_inline(sock, next_seq, "theme")
            # 6h) 个股详情四通道（2026-11-11 ④，默认关）：每会话重建订阅（同 2203/2013
            # 服务器 TTL 同源；跨会话去重会让第二会话起一帧不发、推送静默停流）
            if self._stock_detail_subs:
                for lane in self._detail_lane_cmds:
                    with self._detail_locks[lane]:
                        self._detail_subscribed[lane].clear()
                        self._pending_detail[lane].clear()
                self._queue_detail_new(pool_ids) if not self._sub_staged else None   # staged: wave3
                if self._setup_inline_subs:
                    # 2026-11-11 评审 major-2：inline 模式下详情订阅同 2203/2013
                    # 改 setup 窗口内内联发送（否则 6h 只入队、循环期永久静默）
                    self._flush_pending_inline(sock, next_seq, "detail")
            if self._sub_staged:
                # wave3 漏斗（方案 A，用户裁决 2026-11-17）：per-stock 2203/2013/
                # detail 池 ids 经持久游标轮转切片，每窗 ≤BATCH ids（~40 帧，
                # 「阈值 65% 边际」模型已证伪，README §3.7），批间隔 ≥35s；全池
                # ~300 ids 约 2 会话轮完。staged1 历史观测：全池一次性释放
                # （714 ids→354 帧→rst@+48s，当年归因超阈，实为跑步机+3101）。
                if pool_ids and (self._zt_reason_subs or self._theme_subs
                                 or self._stock_detail_subs):
                    n_pool = len(pool_ids)
                    remaining = (n_pool - self._staged_pool_cursor % n_pool) % n_pool or n_pool
                    self._staged_waves.append({
                        "kind": "perstock",
                        "next_at": self._staged_t0 + self._STAGED_WAVE3_S,
                        "pool": list(pool_ids), "remaining": remaining,
                        "zt": bool(self._zt_reason_subs), "theme": bool(self._theme_subs),
                        "detail": bool(self._stock_detail_subs),
                    })
            # setup 打点在 6g（2203/2013 订阅入队）之后：口径=「连接到内联订阅链
            # （3001/3006）全部完成」；daban 家族已重排为读循环续发，不占此口径
            # （实弹口径见 _drain_setup_subs 注释）
            self._stats["last_setup_s"] = round(time.time() - t_setup, 1)
            self._session_streaming = True   # 死因观测：进入收流（区分 setup 早退）
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
                # 2026-11-18 用户裁决拆门控：loop_send_grace 5s 纯读宽限拆除——
                # App qn0.z() 连接/auth 后即发订阅，无宽限期。
                if self._ka_mode != "none" and now - last_keepalive > 1:
                    # 保活交替: 每 8 tick 一次 610 AuthReq 原样重发（签名绑定初始
                    # challenge/curTime）/ 其余 tick 3001 分块轮询（下一块）
                    # ka_mode=none（2026-11-18 用户裁决，rst_10054 根因二）：纯读不发——
                    # 3001 轮转保活在 3 id 小面上无雷（P4 A/B 口径），但动态面长到
                    # 852 id 后每 6s 全量重订阅一轮（1s/chunk×6），21s 会话内 3000+
                    # 订阅单元，构成 rst_10054 主超支。App 从不用重订阅当心跳；
                    # none=会话由服务端 TTL 轮转+重连兜底（App 同款）。
                    # 注：none 下 last_keepalive 不更新（首个 tick 后本分支短路，
                    # 零发送零开销）
                    hb_flip[0] += 1
                    if hb_flip[0] % 8 == 1 and self._ka_mode == "610":
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
                # 211 批 ack 超时熔断（2026-11-17 P3）：超时无 ack → 本会话回退单帧
                self._check_batch_timeouts(now)
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
                # 分波订阅到点释放（KPL_SUB_STAGED=1；iso1 体积阈值定案，+150s failsafe）
                self._release_staged_waves(now)
                self._drain_detail_subs(sock, next_seq)
                self._drain_zt_reason_subs(sock, next_seq)
                self._drain_theme_subs(sock, next_seq)
                self._drain_setup_subs(sock, next_seq)
                self._drain_unsub(sock, next_seq)   # 402 退订（flag 门控；防抖已拆，整队分块发）
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

    def _handle_resub_nt(self, payload: bytes, *, dec_payload: bytes) -> None:
        """cmd 220 ResubNt：服务端订阅注册表失效通知（App qn0.j 同款语义）。

        2026-11-17 注册表化 P1：topics 非空 → 按 ack attr3 topic 选择性重发；
        无任何匹配 → 降级全量（fallback_all，fail-visible 计数）；
        sub_registry_enabled=False → 全量（旧行为过渡开关）。重发条目置 stale
        移出活跃注册表（App j 同款），drain 重发后重新 register；重发帧重建 seq
        （App x() 每次 write 生成新帧同款）。pid=8 priority 前插保持。"""
        topics = proto.parse_resub_topics(dec_payload or payload)
        entries, mode = self._sub_registry.on_resub(
            topics if self._sub_registry_enabled else [])
        if not self._sub_registry_enabled:
            mode = "all_legacy"   # n3：过渡全量仅重发 ACKED 条目（略窄于旧 _resub_cache
                                  # 含 pending；220 生产从未观测，影响可忽略）
        if not entries:
            self._stats["resub_events"] = self._stats.get("resub_events", 0) + 1
            self._emit(KplEvent(type="resub_nt", ts=time.time(), ok=False,
                                reason="no_cached_subs", topics=topics, mode=mode))
            return
        requeued = [{"cmd": e.cmd, "req": e.req, "ext": e.ext,
                     "key": e.key, "lane": e.lane,   # m4：保留 key/lane，重发后 unsub diff 不漏项
                     **({"priority": True} if e.priority else {})} for e in entries]
        self._pending_setup_frames[0:0] = requeued
        self._stats["resub_events"] = self._stats.get("resub_events", 0) + 1
        self._stats["resub_requeued"] = self._stats.get("resub_requeued", 0) + len(requeued)
        self._emit(KplEvent(type="resub_nt", ts=time.time(), ok=True,
                            requeued=len(requeued), topics=topics, mode=mode))

    def _check_batch_timeouts(self, now: float) -> None:
        """211 批 ack 超时检查（读循环每 tick 调用；单独成方法供 mock 测试）。"""
        if not self._sub_batch_active():
            return
        timed_out = self._sub_registry.timed_out_batches(
            now, self._sub_batch_ack_timeout_s)
        if timed_out:
            self._batch_fallback(f"batch_ack_timeout:{timed_out[:3]}")

    def _capture_sub_ack(self, fr: Dict[str, Any]) -> None:
        """echo/unsub_ack → 注册表（2026-11-17 P1，App qn0.o/q 同款）。

        权威 sub_id=ack ext attr2（服务端分配）、topic=attr3 原始字节；
        非订阅 ack（auth/行情等无登记 seq）跳过不计 orphan；ext 解析失败
        fail-visible 计数不吞。211 批 ack 逐项展开（qn0.o）；402 退订 ack
        按 subIds 清注册表（qn0.q）。"""
        cmd = fr["cmd"]
        seq = fr.get("seq")
        payload = fr.get("payload", b"")
        attrs: Dict[int, Any] = {}
        ext = fr.get("ext") or b""
        if ext:
            try:
                attrs = proto.parse_ext_attrs(ext)
            except proto.FrameDecodeError:
                self._sub_registry.mark_ext_parse_error()
        sub_id = attrs.get(2)
        topic = attrs.get(3)
        if cmd == proto.CMD_SUB_BATCH:
            dec = self._dec_if_flags(payload, fr)
            try:
                items = proto.parse_sub_reqs_pb(dec)
            except Exception as exc:
                self._err(f"211 batch ack parse error: {exc}")
                self._emit(KplEvent(type="sub_batch_error", ts=time.time(),
                                    seq=seq, reason=f"parse error: {exc}"))
                self._batch_fallback("batch_ack_parse_error")
                return
            res = self._sub_registry.on_ack(seq, sub_id=sub_id, topic=topic,
                                            sub_reqs=items, now=time.time())
            self._emit(KplEvent(type="sub_batch_ack", ts=time.time(), **res))
            return
        if cmd == proto.CMD_UNSUB and fr.get("fmt") == "unsub_ack":
            # m5：seq 映射优先（裁决：payload 恒为 28B 不透明状态块，宽容 parse_pb
            # 可能从 blob 提取垃圾 f1 varint 误清条目）；无映射再试 payload 解析。
            sub_ids = self._unsub_seq_ids.pop(seq, []) if seq is not None else []
            if not sub_ids:
                dec = self._dec_if_flags(payload, fr)
                try:
                    sub_ids = proto.parse_unsub_id_req_pb(dec)
                except Exception:
                    sub_ids = []
            if not sub_ids:
                self._stats["unsub_ack_unmatched_n"] = \
                    self._stats.get("unsub_ack_unmatched_n", 0) + 1
            removed = self._sub_registry.on_unsub_ack(sub_ids)
            self._emit(KplEvent(type="sub_unsub_ack", ts=time.time(),
                                sub_ids=sub_ids, removed=removed))
            return
        if seq is None or not self._sub_registry.has_pending_seq(seq):
            return   # 非订阅 ack（610/602/3001 等）：无登记条目，不入 orphan
        res = self._sub_registry.on_ack(seq, sub_id=sub_id, topic=topic,
                                        now=time.time())
        if res.get("kind") == "ack":
            self._emit(KplEvent(type="sub_ack", ts=time.time(), **res))

    # ---- 402 退订（2026-11-17 P2，flag 门控默认关；探针 P3 钉死前不启用）----

    _UNSUB_MAX_IDS = 20       # 单帧 subIds 上限（超出下一帧续发）
    _UNSUB_MAX_FRAMES = 20    # 会话级 402 帧预算上限（方案 §5，review m6；off 长寿会话防超）

    def _sync_unsub_surface(self) -> None:
        """池成员收缩 → 402 退订计划（2103 pid=1 页更新后调用）。

        只处理 per-stock 通道（2203/2013/detail 四 lane）；列表型订阅
        （3001/3006）不参与 diff（新帧覆盖语义）。只取 sub_id 已回填条目
        （服务端未分配 subId 无法按 id 退订，留待会话重建自然失效）。
        空帧抑制保旧页 → keep 面保守偏大，不误退（fail-visible 由 stats 承载）。"""
        if not self._unsub_enabled:
            return
        keep = set(self._pool_stock_ids())
        lanes: List[Tuple[str, int]] = [
            ("zt_reason", proto.CMD_HQ_REASONS),
            ("theme", proto.CMD_STOCK_RELATED_THEME),
        ] + [(f"detail:{dl}", c) for dl, c in self._detail_lane_cmds.items()]
        for lane_prefix, cmd in lanes:
            cands = self._sub_registry.unsub_candidates(lane_prefix, cmd, keep)
            for e in cands:
                if e.sub_id not in self._pending_unsub:
                    self._pending_unsub.append(e.sub_id)
            self._sub_registry.mark_unsub_sent(cands)

    # 分波订阅波次参数（历史件；KPL_SUB_STAGED 默认关）
    # 阈值窗模型已证伪（真凶=3101 错通道+3001 跑步机，README §3.7）：当年认为
    # rst_10054 由 ~110-130 帧/爆发窗触发；波次时刻表压进会话寿命内的约束保留。
    _STAGED_WAVE2_S = 15.0          # wave2：非竞价 2103 页 + lhb 帧（~37 帧阈值内）
    _STAGED_WAVE3_S = 45.0          # wave3 漏斗首批（+45s，与 wave2 错开半窗）
    _STAGED_WAVE3_BATCH_IDS = 50    # 每窗 ids（staged2 实测 ~1.5 帧/id → ~75 帧；窗内总量 ≤~135）
    _STAGED_WAVE3_SPACING_S = 45.0  # 批间隔（锚定实际释放时刻，防停顿后连发并窗）
    _STAGED_FAILSAFE_S = 150.0      # pages 波到点强制清空（防漏，fail-visible）

    def _release_staged_waves(self, now: float) -> None:
        """分波订阅到点释放（KPL_SUB_STAGED=1 时读循环每 tick 调用）。

        阈值窗模型已证伪（真凶=3101 错通道+3001 跑步机，README §3.7）：当年认为
        rst_10054 由爆发窗体积触发（~110-130 帧/窗）。pages 波到点整体释放；per-stock 波为漏斗：
        每窗最多 _STAGED_WAVE3_BATCH_IDS 个 ids 经持久游标 _staged_pool_cursor
        轮转取片（zt/theme/detail 同片同步），批间隔 ≥35s（锚定实际释放时刻，
        防停顿后多批连发并窗超阈），全池轮完即收（staged_cycle_done 事件）。
        会话死亡未完成轮转计 staged_dropped_n（fail-visible，下会话续游标）。"""
        if not self._staged_waves:
            return
        released = 0
        for wave in list(self._staged_waves):
            if wave.get("kind") == "perstock":
                if now < wave["next_at"] or wave["remaining"] <= 0:
                    continue
                pool = wave["pool"]
                n_pool = len(pool)
                batch = min(self._STAGED_WAVE3_BATCH_IDS, wave["remaining"])
                start = self._staged_pool_cursor % n_pool
                ids = pool[start:start + batch]
                if len(ids) < batch:   # 尾部回绕接片首
                    ids = ids + pool[:batch - len(ids)]
                self._staged_pool_cursor = (self._staged_pool_cursor + batch) % n_pool
                ids_n = 0
                for flag, fn in ((wave["zt"], self._queue_zt_reason_new),
                                 (wave["theme"], self._queue_theme_new),
                                 (wave["detail"], self._queue_detail_new)):
                    if flag and ids:
                        fn(list(ids))
                        ids_n += len(ids)
                wave["remaining"] -= batch
                wave["next_at"] = now + self._STAGED_WAVE3_SPACING_S
                released += ids_n
                self._stats["staged_funnel_batches"] = self._stats.get(
                    "staged_funnel_batches", 0) + 1
                self._emit(KplEvent(type="staged_release", ts=time.time(),
                                    kind="perstock", ids=ids_n, batch=batch,
                                    at_s=round(now - self._staged_t0, 1)))
                if wave["remaining"] <= 0:
                    self._staged_waves.remove(wave)
                    self._emit(KplEvent(type="staged_cycle_done", ts=time.time(),
                                        cursor=self._staged_pool_cursor,
                                        at_s=round(now - self._staged_t0, 1)))
                continue
            # pages 波：到点整体释放（release_at）或 failsafe 强制清空
            if now < wave["release_at"] and now < wave["failsafe_at"]:
                continue
            frames = wave.get("frames") or []
            if frames:
                self._pending_setup_frames.extend(frames)
            self._staged_waves.remove(wave)
            released += len(frames)
            self._emit(KplEvent(type="staged_release", ts=time.time(),
                                kind=wave.get("kind"), frames=len(frames), ids=0,
                                at_s=round(now - self._staged_t0, 1)))
        if released:
            self._stats["staged_released_n"] = self._stats.get("staged_released_n", 0) + released

    def _drain_unsub(self, sock: Any, next_seq: Any) -> None:
        """发送 402/pkg 0x50 UnsubIdReq 退订帧。2026-11-18 用户裁决拆防抖：
        整队按单帧协议上限（_UNSUB_MAX_IDS）分块一次发完，无 ≥5s 间隔/≤1 帧/tick
        限制（App 屏 onPause 即发 402，无防抖）；会话级帧预算（红线 10 频控预算）
        保留。send 失败 fail-fast 结束会话重连。"""
        if not self._unsub_enabled or not self._pending_unsub:
            return
        while self._pending_unsub:
            if self._unsub_frames_sent >= self._UNSUB_MAX_FRAMES:
                return   # 会话级帧预算耗尽（m6，频控预算非门控）；余量下一会话重建
            ids = self._pending_unsub[:self._UNSUB_MAX_IDS]
            self._pending_unsub = self._pending_unsub[self._UNSUB_MAX_IDS:]
            req = proto.build_unsub_id_req_pb(ids)
            enc = self._codec.enc(req)
            unsub_seq = next_seq()
            frame = proto.build_frame(proto.CMD_UNSUB, unsub_seq, enc or req, d=0,
                                      encrypted=bool(enc), pkg=proto.PKG_UNSUB)
            self._dbg("C", frame)
            try:
                sock.sendall(frame)
            except OSError as exc:
                self._pending_unsub[:0] = ids   # 回队头留痕（会话即将结束重建）
                self._err(f"402 unsub send failed: {exc}")
                self._emit(KplEvent(type="sub_unsub_dropped", ts=time.time(),
                                    sub_ids=ids, session=self._session_no, error=str(exc)))
                raise   # 2026-11-18 拆 _sock_dead：fail-fast 重连
            self._unsub_frames_sent += 1
            self._unsub_seq_ids[unsub_seq] = list(ids)   # kind5 ack 按 seq 回填 subIds
            self._stats["unsub_sent_n"] = self._stats.get("unsub_sent_n", 0) + 1
            self._emit(KplEvent(type="sub_unsub", ts=time.time(), sub_ids=ids,
                                session=self._session_no))

    def _dispatch(self, fr: Dict[str, Any], *, sender: Any = None, next_seq: Any = None) -> None:
        if fr.get("fmt") == "heartbeat":
            # kind1 心跳（pkg 0x10）：App SocketReaderThread msg22 同款 skip，
            # 无 cmd 键，计数不路由（review M1：避免 fr["cmd"] KeyError 杀会话）
            self._stats["heartbeat_n"] = self._stats.get("heartbeat_n", 0) + 1
            return
        cmd = fr["cmd"]
        payload = fr.get("payload", b"")
        # 订阅注册表观测（2026-11-17 P1）：echo/unsub_ack 捕获 attr2/attr3；
        # 推送 topic 命中率只记录不改路由（dispatch 仍按 cmd，方案 §4 P1）
        if fr.get("fmt") in ("echo", "unsub_ack"):
            self._capture_sub_ack(fr)
        elif fr.get("fmt") == "push":
            self._sub_registry.on_push_topic(fr.get("ext_raw") or b"")
        if cmd == proto.CMD_RESUB_NT:
            self._handle_resub_nt(payload, dec_payload=self._dec_if_flags(payload, fr))
            return
        if cmd == proto.CMD_ERROR:
            err = proto.parse_err_resp(payload)
            self._session_err_code = err.get("code")   # 死因观测（纯记录，不改路由）
            # 2026-11-18 根因定位：ErrResp msg 全文透出 status.last_err_resp
            # （独立字段：close 消息会覆盖 last_error）
            self._stats["last_err_resp"] = f"code={err.get('code')} msg={err.get('msg')!r}"
            self._err(f"server error: {err}")
            self._emit(KplEvent(type="error", ts=time.time(), server=err))
            # 211 熔断：未决批期间收 ErrResp → 本会话回退单帧（保守归因，
            # 探针未钉死前不拿生产会话赌批信封语义）
            if self._sub_batch_active() and self._sub_registry.unacked_batches():
                self._batch_fallback(f"server_error:{err}")
            return
        if cmd == proto.CMD_ERROR_NT:
            # 110 错误通知通道（2026-11-17 211 探针实弹定案）：payload=ErrResp
            # {code,msg} GCM 加密；批量被拒项逐项下发 2000（非致命，会话存活）。
            # fail-visible 解析上报，不静默当 raw；无 seq 无法归因到项，只计数。
            dec = self._dec_if_flags(payload, fr)
            err = proto.parse_err_resp(dec)
            self._session_err_code = err.get("code")   # 死因观测（纯记录）
            self._stats["err_nt_n"] = self._stats.get("err_nt_n", 0) + 1
            self._err(f"server error nt(110): {err}")
            self._emit(KplEvent(type="error", ts=time.time(), server=err, channel=110))
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
            self._capture_auction_price(quotes)
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
                if int(data.get("pid_type", 0) or 0) == 8 and new_items:
                    # 竞价过程事实序列（2026-11-16 事实采集裁决；2026-11-18 用户裁决
                    # 拆窗门控+节流）：pid=8 推送即全量落库，无 09:15-09:27 粗门、无
                    # ≥5s 节流（§4.0 数据链禁硬门禁：全量保存；竞价语义窗过滤由消费层
                    # derive_trial_rows_from_series 自带 [09:15,09:27) tick 过滤 +
                    # early/lateTicksFiltered 计数承担）。失败不阻断收流。
                    try:
                        self._persist_corpus("bid_series", self.get_daban_list(8))
                    except Exception as exc:   # noqa: BLE001 — 落库失败不阻断收流
                        self._corpus_persist_stats["bid_series_fail"] = \
                            self._corpus_persist_stats.get("bid_series_fail", 0) + 1
                        self._err(f"bid_series persist failed: {exc}")
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
                # 402 退订 diff（2026-11-17 P2，flag 门控）：pid=1 页更新后
                # 池成员收缩 → 已 ack 且 key 不在保留面的 per-stock 订阅入退订队
                try:
                    if int(data.get("pid_type", 0)) == 1:
                        self._sync_unsub_surface()
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
