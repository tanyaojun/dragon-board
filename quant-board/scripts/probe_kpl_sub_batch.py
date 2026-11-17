# -*- coding: utf-8 -*-
"""KPL 订阅协议探针（预登记开火路径；2026-11-17 用户批准「211开火」+
下午盘「实施待办项：402 探针 P3 / P4 保活 A/B / 批内盘中推送交付」）。

合同唯一来源：docs/kpl-socket/sub-registry-refactor-plan.md §7/§7.1。
预算硬限（AGENTS §1.2-9 / 方案 §5）：
- 单次开火 ≤9 会话；每会话新增帧 ≤12；会话间冷却 ≥180s；当日 211 总帧 ≤60；
  402/0x50 首射 ≤2 帧。无重试循环（会话失败不重开，冷却后下一变体）。
- 单实例纪律（README §5.3）：开火前 :8002 生产采集必须已 stop
  （POST /api/kpl/stop），探针结束后恢复（POST /api/kpl/start）。
- 证据：KPL_DEBUG 帧转储 + 事件/摘要 JSONL 落仓库根 tmp/（gitignore），
  用完即删；结论回填方案 §1.3/§7.1/§11 与 README §3.5。

变体：
  control/plain/gcm/multi/dmulti —— 211 受理矩阵（已裁决，见 §1.3）
  pushbatch/pushdirect —— 盘中推送交付：2114/2115/2116 三项，211 vs direct 对照
  unsub —— P3：direct 订 2114+2116 → 20s 后只退 2114（生产 _drain_unsub 路径）
           → 差分验证：2114 推送停 / 2116 继续 + kind5 ack 形态
  ka610/kaoff —— P4 A/B：同配置唯一变量 ka_mode，观察窗 120s 计寿命/推送量

实现：100% 复用生产 KplCollectorService 会话链（260/610/602/23xx/3001/3006 +
拟人延迟 + 211 信封构造 + 注册表 ack 捕获 + 熔断 + 402 退订），仅子类注入
受控订阅面（daban/语料/详情开关全关，_pending_setup_frames 首 drain 前插探针项）。
pytest 不得 import 本模块（开火工具，非测试；红线 README §六）。

用法：
  .\\.venv\\Scripts\\python.exe scripts\\probe_kpl_sub_batch.py --tag r3 \\
      --variants pushbatch,pushdirect [--observe-s 90]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import settings  # noqa: F401,E402  # 导入即载入 .env.local 凭据
from backend.services import kpl_daban_protocol as daban  # noqa: E402
from backend.services import kpl_socket_protocol as proto  # noqa: E402
from backend.services.kpl_collector_service import KplCollectorService, KplEvent  # noqa: E402
from backend.services.kpl_pcemu import PCEmulatorCodec  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]   # 仓库根 d:/dragon-board
TMP = ROOT / "tmp"
COOLDOWN_S = 180.0   # 方案 §7 硬预算：探针间隔 ≥180s（螺旋实锤冷却值）


def _ext(cmd: int) -> bytes:
    return bytes([0x02]) + cmd.to_bytes(2, "big")


def make_items(variant: str) -> list:
    """P1 plain/gcm：2114+2116 两项；multi/dmulti：5 项（已裁决）；
    pushbatch/pushdirect：2114/2115/2116 三项 hqDaban 族（盘中推送交付）；
    unsub/ka610/kaoff：2114+2116 两项（差分退订 / 保活 A/B 同构订阅面）。"""
    if variant in ("multi", "dmulti"):
        return [
            {"cmd": daban.CMD_DABAN_STOCK_LIST,
             "req": daban.build_daban_stock_list_req_pb(8, index=0, count=30),
             "ext": _ext(daban.CMD_DABAN_STOCK_LIST), "priority": True},
            {"cmd": daban.CMD_ZD_STAT, "req": daban.build_market_energy_req_pb(1),
             "ext": _ext(daban.CMD_ZD_STAT)},
            {"cmd": daban.CMD_MARKET_OVERVIEW, "req": daban.build_empty_req_pb(),
             "ext": _ext(daban.CMD_MARKET_OVERVIEW)},
            {"cmd": proto.CMD_HQ_REASONS, "req": proto.build_hq_req_pb("000001"),
             "ext": _ext(proto.CMD_HQ_REASONS)},
            {"cmd": proto.CMD_STOCK_RELATED_THEME, "req": proto.build_hq_req_pb("000001"),
             "ext": _ext(proto.CMD_STOCK_RELATED_THEME)},
        ]
    if variant in ("pushbatch", "pushdirect"):
        return [
            {"cmd": daban.CMD_ZD_STAT, "req": daban.build_market_energy_req_pb(1),
             "ext": _ext(daban.CMD_ZD_STAT)},
            {"cmd": daban.CMD_MARKET_OVERVIEW, "req": daban.build_empty_req_pb(),
             "ext": _ext(daban.CMD_MARKET_OVERVIEW)},
            {"cmd": 2116, "req": daban.build_empty_req_pb(), "ext": _ext(2116)},
        ]
    # 2114 QxMarketEnergyReq{type=1} + 2116 空 Req（P1 基线 / unsub / ka A/B）
    return [
        {"cmd": daban.CMD_ZD_STAT, "req": daban.build_market_energy_req_pb(1),
         "ext": _ext(daban.CMD_ZD_STAT)},
        {"cmd": 2116, "req": daban.build_empty_req_pb(), "ext": _ext(2116)},
    ]


class ProbeCollector(KplCollectorService):
    """生产 collector + 受控订阅面注入（每会话首 drain 前插，只发探针项）。

    预算纪律（2026-11-17 首轮探针复盘）：_run_loop 覆写为**单会话**——
    生产重连链会在观察窗内自动重开多会话，每会话再发一帧 211，使实际
    会话数超预登记上限（首轮 6 会话/5 帧，披露于方案 §10）。探针一律
    单会话，失败不重开，冷却后下一变体。"""

    def __init__(self, codec, items, unsub_plan=None, **kw):
        super().__init__(codec, **kw)
        self._probe_items = items
        self._probe_injected = False
        # P3 退订计划：(延迟秒, subIds)——读循环启动后计时，到点把 ids 入
        # _pending_unsub + mark_unsub_sent（与 _sync_unsub_surface 同款语义），
        # 后续由生产 _drain_unsub 真实路径发出（防抖/频控/回队全继承）。
        self._unsub_plan = unsub_plan
        self._unsub_t0 = None
        self._unsub_fired = False

    def _run_loop(self):
        self._session_no += 1
        self._stats["sessions"] += 1
        t0 = time.time()
        try:
            self._session()
        except Exception as exc:   # fail-visible：探针会话异常不重开
            self._err(f"probe session: {type(exc).__name__}: {exc}")
        self._stats["last_session_s"] = round(time.time() - t0, 1)
        self._status = "stopped"

    def _session(self):
        self._probe_injected = False
        super()._session()

    def _drain_setup_subs(self, sock, next_seq):
        if not self._probe_injected:
            self._pending_setup_frames[0:0] = [dict(it) for it in self._probe_items]
            self._probe_injected = True
        super()._drain_setup_subs(sock, next_seq)

    def _drain_unsub(self, sock, next_seq):
        if self._unsub_plan is not None:
            if self._unsub_t0 is None:
                self._unsub_t0 = time.time()
            delay, ids = self._unsub_plan
            if not self._unsub_fired and time.time() - self._unsub_t0 >= delay:
                entries = [e for e in self._sub_registry.entries()
                           if e.sub_id in ids and e.state == "acked"]
                self._pending_unsub.extend(ids)
                self._sub_registry.mark_unsub_sent(entries)
                self._unsub_fired = True
                self._emit(KplEvent(type="probe_unsub_fired", ts=time.time(),
                                    sub_ids=ids, acked_entries=len(entries)))
        super()._drain_unsub(sock, next_seq)


# 每变体默认观察窗（--observe-s 显式覆盖）：推送交付/退订差分需盘中推送样本；
# P4 寿命对照窗 120s（生产会话寿命典型 57-80s，README §9.5，窗要盖过典型死亡点）
_OBSERVE_DEFAULTS = {"pushbatch": 90.0, "pushdirect": 90.0, "unsub": 90.0,
                     "ka610": 120.0, "kaoff": 120.0}
_DIRECT_VARIANTS = ("control", "dmulti", "pushdirect", "unsub", "ka610", "kaoff")


def run_session(idx: int, variant: str, codec, observe_s: float, tag: str) -> dict:
    TMP.mkdir(exist_ok=True)
    dump = TMP / f"kplprobe_{tag}_frames_s{idx}_{variant}.hex"
    os.environ["KPL_DEBUG"] = str(dump)
    items = make_items(variant)
    svc = ProbeCollector(
        codec, items,
        unsub_plan=((20.0, [daban.CMD_ZD_STAT]) if variant == "unsub" else None),
        device_id=os.environ.get("KPL_DEVICE_ID")
        or os.environ.get("QUANT_BOARD_KPL_APP_DEVICEID", ""),
        user_id=os.environ.get("KPL_USER_ID", "0"),
        token=os.environ.get("KPL_TOKEN", ""),
        stock_ids=["801044"],
        # 订阅面最小化：只留探针项（新增帧预算内）
        daban_subs=False, daban_lhb=False, lhb_realtime=False,
        zt_reason_subs=False, theme_subs=False, stock_detail_subs=False,
        sub_batch_mode=("direct" if variant in _DIRECT_VARIANTS else "211"),
        # U2 实弹定案（2026-11-17）：item.data 必须 GCM（codec=1），明文→2008 断连
        sub_batch_codec=(0 if variant in ("plain", "control") else 1),
        unsub_enabled=(variant == "unsub"),
        ka_mode=("off" if variant == "kaoff" else "610"),
        human_delay=True, auth_phase_delay=5.0, auth_phase_jitter=3.0,
        loop_send_grace_s=0.0, enforce_trading_hours=False)
    print(f"[s{idx}] variant={variant} items={len(items)} observe={observe_s}s "
          f"dump={dump.name}", flush=True)
    t0 = time.time()
    svc.start()
    time.sleep(observe_s)
    svc.stop()
    if svc._thread is not None:
        svc._thread.join(timeout=15)
    events = list(svc._history)
    entries = [{"cmd": e.cmd, "seq": e.seq, "sub_id": e.sub_id,
                "topic": (e.topic or b"").hex(), "state": e.state,
                "batch_seq": e.batch_seq, "lane": e.lane}
               for e in svc._sub_registry.entries()]
    # 帧计数（保活 A/B 的 610 重发量 / 402 首射 / 110 拒绝通知，从转储直读）
    frame_counts = {}
    if dump.exists():
        for line in dump.read_text().splitlines():
            d, _ts, hx = line.split(" ", 2)
            try:
                fr = proto.parse_incoming(bytes.fromhex(hx))
            except Exception:
                continue
            key = f"{d}_{fr.get('cmd')}"
            frame_counts[key] = frame_counts.get(key, 0) + 1
    summary = {
        "session": idx, "variant": variant, "tag": tag,
        "wall_s": round(time.time() - t0, 1),
        "session_s": svc._stats.get("last_session_s"),
        "setup_s": svc._stats.get("last_setup_s"),
        "batch_frames_sent": svc._stats.get("batch_frames_sent", 0),
        "batch_fallback": [e for e in events if e["type"] == "batch_fallback"],
        "batch_ack": [e for e in events if e["type"] == "sub_batch_ack"],
        "sub_ack": [e for e in events if e["type"] == "sub_ack"],
        "errors": [e for e in events if e["type"] == "error"],
        "server_errors": [e.get("server") for e in events if e["type"] == "error"],
        "push_events": {t: sum(1 for e in events if e["type"] == t)
                        for t in ("quotes", "stock_quotes", "daban", "zd_stat",
                                  "market_overview", "plate_strength", "zt_reasons",
                                  "theme_heat", "raw")},
        "registry": svc._sub_registry.stats(),
        "entries": entries,
        "frame_counts": frame_counts,
        "ka_mode": svc._ka_mode,
        "unsub": [e for e in events if e["type"] in
                  ("probe_unsub_fired", "sub_unsub", "sub_unsub_ack", "sub_unsub_dropped")],
        "daban_push_timeline": [{"ts": e["ts"], "cmd": e.get("cmd"),
                                 "source": e.get("source")}
                                for e in events if e["type"] in
                                ("daban", "zd_stat", "market_overview", "plate_strength")],
        "last_error": svc._last_error,
        "dump": str(dump),
    }
    (TMP / f"kplprobe_{tag}_summary_s{idx}_{variant}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (TMP / f"kplprobe_{tag}_events_s{idx}_{variant}.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    print(f"[s{idx}] done session_s={summary['session_s']} "
          f"batch_ack={len(summary['batch_ack'])} sub_ack={len(summary['sub_ack'])} "
          f"fallback={len(summary['batch_fallback'])} "
          f"errors={summary['server_errors'][:2]}", flush=True)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observe-s", type=float, default=None,
                    help="显式覆盖每变体默认观察窗（push/unsub 90s，ka 120s，其余 45s）")
    ap.add_argument("--variants", default="control,gcm",
                    help="逗号分隔变体序列，≤9 个（方案 §7.1 下午盘预算）")
    ap.add_argument("--tag", default="r3", help="证据文件名轮次标签（防跨轮覆盖）")
    ap.add_argument("--cooldown-s", type=float, default=COOLDOWN_S)
    args = ap.parse_args()
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    if len(variants) > 9:
        print("预算硬限：单次开火 ≤9 会话（方案 §7.1）", file=sys.stderr)
        return 2
    codec = PCEmulatorCodec()   # 懒初始化，pc 白盒轨（默认，无模拟器依赖）
    summaries = []
    for i, variant in enumerate(variants, 1):
        if i > 1:
            print(f"[cooldown] {args.cooldown_s}s ...", flush=True)
            time.sleep(args.cooldown_s)
        obs = args.observe_s if args.observe_s is not None else \
            _OBSERVE_DEFAULTS.get(variant, 45.0)
        summaries.append(run_session(i, variant, codec, obs, args.tag))
    out = TMP / f"kplprobe_{args.tag}_run.json"
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[run] summaries → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())