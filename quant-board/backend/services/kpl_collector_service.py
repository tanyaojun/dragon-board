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
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from backend.services import kpl_daban_protocol as daban
from backend.services import kpl_lhb_protocol as lhb
from backend.services import kpl_socket_protocol as proto

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
        daban_subs: bool = True,
        daban_market_type: int = 1,
        daban_list_pids: Optional[Tuple[int, ...]] = (8, 0, 6, 1, 2, 3),
        daban_list_page_size: int = 30,
        daban_list_pages: int = 7,
        daban_lhb: bool = False,
        lhb_realtime: bool = False,
        lhb_realtime_count: int = 120,
        zt_reason_subs: bool = True,
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
        self._zt_reason_lock = threading.Lock()
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
        return {
            "ok": True, "pid_type": key, "items": items,
            "max_size": max_size, "date": ordered[-1].get("date", ""),
            "pages": len(pages), "pages_expected": expected_pages,
            "pages_missing": sorted(set(range(expected_pages)) - present),
            "pages_meta": pages_meta,
            "ts": latest, "raw_len": sum(p.get("raw_len", 0) for p in ordered),
        }

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

    def _drain_zt_reason_subs(self, sock: Any, next_seq: Any) -> None:
        """发送待订阅 2203 帧（仅会话线程调用；异常 fail-visible 不杀会话）。

        边界：sendall 失败时剩余 pending 不重入队（本会话丢失），下一会话
        6g 全量补订自愈（2026-11-08 评审 P2，随 P0 每会话重建订阅修复）。"""
        if not self._zt_reason_subs:
            return
        with self._zt_reason_lock:
            pending = list(self._pending_zt_reason)
            self._pending_zt_reason = []
        if not pending:
            return
        ext = bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_REASONS)
        for sid in pending:
            req = proto.build_hq_req_pb(sid)
            enc = self._codec.enc(req)
            frame = proto.build_frame(proto.CMD_HQ_REASONS, next_seq(), enc or req,
                                      d=0, encrypted=bool(enc), pkg=proto.PKG_ROUTE, ext=ext)
            self._dbg("C", frame)
            try:
                sock.sendall(frame)
            except OSError as exc:
                self._err(f"2203 subscribe send failed ({sid}): {exc}")
                return

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

    def set_subscriptions(self, stock_ids: List[str], priority_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """动态更新订阅清单（下一个 3001 构造即生效，轮询间隔 ~2s）。

        priority_ids：优先块（顶级板块等高频行情），轮询时与普通块交替发——
        单请求 id 数超 ~241 会被服务器 1106 拒绝（2026-10-27 实测），故分块。
        fail-visible：空清单拒绝（保留现有订阅），变更结构化返回供调用方透出。
        """
        ids = [str(s).strip() for s in (stock_ids or []) if str(s).strip()]
        if not ids:
            return {"ok": False, "reason": "empty stock_ids rejected", "count": len(self._stock_ids)}
        self._stock_ids = ids
        self._sub_prio_all = [str(s).strip() for s in (priority_ids or []) if str(s).strip()]
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
            "zt_reasons_subscribed": len(self._zt_reason_subscribed),
            "anti_cheat_rounds": self._stats.get("anti_cheat_rounds", 0),
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

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self._session_no += 1
            self._stats["sessions"] += 1
            try:
                self._session()
            except (ssl.SSLError, OSError, socket.timeout) as exc:
                self._err(f"session#{self._session_no} network: {type(exc).__name__}: {exc}")
            except SignSvcError as exc:
                self._err(f"session#{self._session_no} signsvc: {exc}")
                # signsvc 故障重试间隔拉长
                self._stop.wait(5.0)
                continue
            except AntiCheatError as exc:
                # 261 无法作答 → 不发假答案，直接断连重建（App 同款行为）；
                # 退避拉长到 5s：若 261 周期性下发，2s 快速重连会刷屏（评审 R1-P2）
                self._err(f"session#{self._session_no} anti_cheat: {exc}")
                self._status = "reconnecting"
                self._stop.wait(5.0)
                continue
            except Exception as exc:  # 未知异常也必须 fail-visible
                self._err(f"session#{self._session_no} unexpected: {type(exc).__name__}: {exc}")
            if self._stop.is_set():
                break
            self._status = "reconnecting"
            self._stop.wait(2.0)
        self._status = "stopped"

    def _dbg(self, direction: str, data: bytes) -> None:
        if not os.environ.get("KPL_DEBUG"):
            return
        with open(os.environ["KPL_DEBUG"], "a") as f:
            f.write(f"{direction} {int(time.time())} {data.hex()}\n")

    def _session(self) -> None:
        self._status = "connecting"
        seq = [0]  # 会话内递增 seq（重复 seq 会被服务器 110/2000 拒绝并断连）

        def next_seq() -> int:
            seq[0] += 1
            return seq[0]

        sock = self._tls_connect()
        self._rx = bytearray()   # 新会话新流：残帧缓冲必须清零
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
            # 拟人延迟：服务器对 <1s 完成认证+订阅的连接做机器人检测并 ~6s 即断连
            # （实测 collector adb 链路 5-8s 完成 → 75-160s 会话；服务 <1s → 6s 会话）
            if self._human_delay:
                time.sleep(1.2)
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
            if self._human_delay:
                time.sleep(0.6)
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
            if self._human_delay:
                time.sleep(0.8)
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
                if self._human_delay:
                    time.sleep(0.3)
                self._dbg("C", gq_frame)
                sock.sendall(gq_frame)
            # 6b) 3006 个股行情订阅：HQStockIdListReq{f1 repeated stockIds}（个股实时价）。
            #     与 3001 同款分块（单请求 id 超 ~241 会被 1106 拒绝；2026-10-27 实测：
            #     精选板块引导后 id≈500 单帧全发即触发 server error 1106）
            ext6 = bytes([0x02]) + struct.pack(">H", proto.CMD_HQ_ID_LIST)
            for chunk in self._chunks(list(self._stock_ids)):
                hq = b"".join(proto.pb_bytes(1, sid.encode()) for sid in chunk)
                enc_hq = self._codec.enc(hq)
                hq_frame = proto.build_frame(proto.CMD_HQ_ID_LIST, next_seq(), enc_hq or hq, d=0,
                                             encrypted=bool(enc_hq), pkg=proto.PKG_ROUTE, ext=ext6)
                self._dbg("C", hq_frame)
                sock.sendall(hq_frame)
            # 6c) 打板/情绪订阅（service_hq_daban.proto，2026-10-27 逆向）：
            #     2114/2115/2118/2119 发 QxMarketEnergyReq{type}；2116/2126 空 Req；
            #     2120/2121 发 QxZtSituationStockReq{bsType}。逐 cmd 一帧，同 0x40 通道与 ext 路由头。
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
                    enc_db = self._codec.enc(req_pb)
                    ext_db = bytes([0x02]) + struct.pack(">H", sub_cmd)
                    db_frame = proto.build_frame(sub_cmd, next_seq(), enc_db or req_pb, d=0,
                                                 encrypted=bool(enc_db), pkg=proto.PKG_ROUTE, ext=ext_db)
                    if self._human_delay:
                        time.sleep(0.3)
                    self._dbg("C", db_frame)
                    sock.sendall(db_frame)
                # 6d) 2103 打板个股列表订阅：每页签按 index 偏移逐页一帧（推送页固定 30 行，
                #     count=200 实测无效——见 __init__ 注释）；Resp.pidType+index 回带区分页归属
                for pid in self._daban_list_pids:
                    for page in range(self._daban_list_pages):
                        req_pb = daban.build_daban_stock_list_req_pb(
                            pid, index=page * self._daban_list_page_size,
                            count=self._daban_list_page_size)
                        enc_db = self._codec.enc(req_pb)
                        ext_db = bytes([0x02]) + struct.pack(">H", daban.CMD_DABAN_STOCK_LIST)
                        db_frame = proto.build_frame(daban.CMD_DABAN_STOCK_LIST, next_seq(),
                                                     enc_db or req_pb, d=0, encrypted=bool(enc_db),
                                                     pkg=proto.PKG_ROUTE, ext=ext_db)
                        if self._human_delay:
                            time.sleep(0.3)
                        self._dbg("C", db_frame)
                        sock.sendall(db_frame)
            # 6e) 2112 会不会上龙虎榜预测订阅（2026-10-29 逆向）：0x40 通道同 daban 家族，
            #     ForecastLHBReq 基线 count=30/sortType=1/quotaType=0（LhbWillStockModel.k(2112)）；
            #     开关独立于 daban_subs（与打板/情绪订阅解耦）
            if self._daban_lhb:
                req_lhb = daban.build_forecast_lhb_req_pb()
                enc_lhb = self._codec.enc(req_lhb)
                ext_lhb = bytes([0x02]) + struct.pack(">H", daban.CMD_FORECAST_LHB)
                lhb_frame = proto.build_frame(daban.CMD_FORECAST_LHB, next_seq(),
                                              enc_lhb or req_lhb, d=0, encrypted=bool(enc_lhb),
                                              pkg=proto.PKG_ROUTE, ext=ext_lhb)
                if self._human_delay:
                    time.sleep(0.3)
                self._dbg("C", lhb_frame)
                sock.sendall(lhb_frame)
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
                    enc_rl = self._codec.enc(req_rl)
                    ext_rl = bytes([0x02]) + struct.pack(">H", lhb_cmd)
                    rl_frame = proto.build_frame(lhb_cmd, next_seq(),
                                                 enc_rl or req_rl, d=0, encrypted=bool(enc_rl),
                                                 pkg=proto.PKG_ROUTE, ext=ext_rl)
                    if self._human_delay:
                        time.sleep(0.3)
                    self._dbg("C", rl_frame)
                    sock.sendall(rl_frame)
            self._emit(KplEvent(type="status", ts=time.time(), status="streaming",
                                session=self._session_no))
            # 6g) 2203 涨停原因试点：每会话重建订阅——服务器 TTL≈60-90s，重连后原订阅面已失效，
            # 跨会话去重会让第二会话起一帧不发、推送静默停流（2026-11-08 评审 P0）：先清
            # 已订阅集合再全量补订；页帧到达后的新增成员由 _dispatch 自动入队，drain 在收流循环内
            if self._zt_reason_subs:
                with self._zt_reason_lock:
                    self._zt_reason_subscribed.clear()
                    self._pending_zt_reason.clear()
                self._queue_zt_reason_new(self._pool_stock_ids())
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
            while not self._stop.is_set():
                try:
                    fr = self._read_frame(sock)
                except socket.timeout:
                    fr = "timeout"  # 哨兵：本轮无数据，不是断连；保活块仍然执行
                now = time.time()
                if now - last_keepalive > 1:
                    # 保活交替: 每 8 tick 一次 610 AuthReq 原样重发（签名绑定初始
                    # challenge/curTime）/ 其余 tick 3001 分块轮询（下一块）
                    hb_flip[0] += 1
                    if hb_flip[0] % 8 == 1:
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
                # 2203 待订阅帧 drain（新入池成员数秒内补订，不占保活节奏）
                self._drain_zt_reason_subs(sock, next_seq)
                if fr == "timeout":
                    continue
                if fr is None:
                    # 服务器断开 → 返回触发重连
                    self._err(f"session#{self._session_no} closed by server")
                    return
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
            self._emit(KplEvent(type="zt_reasons", ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp", **data))
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
            self._emit(KplEvent(type=event_type, ts=time.time(), cmd=cmd,
                                source="push" if fr.get("fmt") == "push" else "resp", **data))
            return
        # 其他 cmd：fail-visible 记录原始帧（截断）
        self._emit(KplEvent(type="raw", ts=time.time(), cmd=cmd,
                            payload_hex=payload[:64].hex(), payload_len=len(payload)))
