"""KPL 爆发指纹隔离探针（2026-11-17 预登记，docs/kpl-socket/
burst-fingerprint-isolation-probe-preregistration-20261117.md）。

议题：生产会话 ~60s 被 10054 爆发指纹重置（README §3.4 / sub-registry §7.1.1），
短会话限制退订。本探针隔离主导族：S0 globals-only / S1 +2103×42 页 /
S2 +per-stock 2203/2013 / S3 full 对照。固定 kaoff/direct/registry/unique_id，
唯一变量=订阅面族；死因分类（rst_10054 vs errresp vs eof_clean）进 summary。

预算纪律（AGENTS §1.2-9）：单会话禁重连（_run_loop 覆写）；变体间冷却 ≥180s；
总会话 ≤14；direct only（211/402 日预算不动）。真实连接只走预登记+用户批准。

用法（11-18 竞价窗，先 :8002 POST stop 单实例）：
  # 取池（生产存活时，只读）：
  .\\.venv\\Scripts\\python.exe scripts\\probe_kpl_burst_surface.py --dump-pool
  # 开火完整矩阵（每变体 3 会话）：
  .\\.venv\\Scripts\\python.exe scripts\\probe_kpl_burst_surface.py \\
      --variants S0,S1,S2,S3 --sessions-per-variant 3 --pool 000001,000002,... --tag b1
  # 收盘前 S0 shakedown（单会话，无需池）：
  .\\.venv\\Scripts\\python.exe scripts\\probe_kpl_burst_surface.py --variants S0 --sessions-per-variant 1 --tag shake
"""
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
COOLDOWN_S = 180.0   # 预登记 §3 硬预算：变体间冷却 ≥180s
MAX_SESSIONS = 14    # 预登记 §3：4 变体 ×3 + 2 重试预留
OBSERVE_S = 120.0    # 预登记 §3：盖过生产典型死亡点 ~60s + 长寿右删失

# 变体订阅面配置（唯一变量=族；其余控制变量固定）。daban_list_pids 空=无 2103 页；
# zt/theme False=无 per-stock。S2/S3 per-stock 池由 --pool 受控注入（_pool_stock_ids 覆写）。
_ALL_PIDS = (0, 8, 6, 1, 2, 3)
VARIANT_SURFACE = {
    "S0": dict(daban_subs=True, daban_list_pids=(), zt_reason_subs=False, theme_subs=False),
    "S1": dict(daban_subs=True, daban_list_pids=_ALL_PIDS, zt_reason_subs=False, theme_subs=False),
    "S2": dict(daban_subs=True, daban_list_pids=(), zt_reason_subs=True, theme_subs=True),
    "S3": dict(daban_subs=True, daban_list_pids=_ALL_PIDS, zt_reason_subs=True, theme_subs=True),
}
_PER_STOCK_VARIANTS = ("S2", "S3")


class ProbeSurfaceCollector(KplCollectorService):
    """生产 collector + 受控订阅面（按变体配置族）+ 单会话禁重连 + 死因分类。

    与 probe_kpl_sub_batch.ProbeCollector 区别：那个禁用基础面+前插探针项（测
    211/402 语义）；本探针保留生产基础面构建路径（6c-6g），按变体开关族，测的是
    生产爆发面本身的风控指纹。per-stock 池用 _pool_stock_ids 覆写受控注入（S2/S3），
    不依赖 2103 pid=1 实时响应（隔离变量）。"""

    def __init__(self, codec, variant: str, pool=None, reconnect=False, staged=False, **kw):
        if variant not in VARIANT_SURFACE:
            raise ValueError(f"unknown variant {variant!r}（仅 S0/S1/S2/S3）")
        surface = VARIANT_SURFACE[variant]
        if variant in _PER_STOCK_VARIANTS and not pool:
            raise ValueError(f"{variant} 需 --pool 受控池（per-stock 订阅面）")
        self._reconnect = bool(reconnect)
        # 分波订阅模式（KPL_SUB_STAGED 同款）：历史探针件——「爆发体积阈值」假设
        # 2026-11-18 已证伪（真凶=3101 错通道+3001 跑步机，README §3.7），本模式
        # 保留作历史复现工具，不再作为根因验证路径。
        kw["sub_staged"] = bool(staged)
        # 控制变量固定（消除 610/211 因素，唯一变量=订阅面族）
        kw.setdefault("ka_mode", "off")
        kw.setdefault("sub_batch_mode", "direct")
        kw.setdefault("sub_registry_enabled", True)
        kw.setdefault("sub_unique_id", True)
        kw.setdefault("daban_lhb", False)
        kw.setdefault("lhb_realtime", False)
        kw.setdefault("stock_detail_subs", False)
        kw.setdefault("human_delay", True)
        kw.setdefault("enforce_trading_hours", False)
        super().__init__(codec, daban_list_pages=7, **surface, **kw)
        self._variant = variant
        self._probe_pool = list(pool or [])

    def _pool_stock_ids(self):
        # S2/S3：受控池（隔离变量，不依赖 2103 实时响应）；S0/S1 无 per-stock 不用池
        if self._variant in _PER_STOCK_VARIANTS:
            return list(self._probe_pool)
        return super()._pool_stock_ids()

    def _run_loop(self):
        if self._reconnect:
            # 重连模式：生产同款 _run_loop（螺旋退避连续重连）——验证 rst_10054
            # 是否重连累积驱动（非盘中驱动）。死因分类已由生产 _run_loop 落地。
            return super()._run_loop()
        # 单会话禁重连（预登记 §3 预算纪律）+ 死因分类（同生产 _classify_death_cause）
        self._session_no += 1
        self._stats["sessions"] += 1
        t0 = time.time()
        death_exc = None
        try:
            self._session()
        except Exception as exc:   # fail-visible：探针会话异常不重开
            death_exc = exc
            self._err(f"probe session: {type(exc).__name__}: {exc}")
        self._stats["last_session_s"] = round(time.time() - t0, 1)
        cause = self._classify_death_cause(death_exc)
        self._last_death_cause = cause
        self._death_cause_counts[cause] = self._death_cause_counts.get(cause, 0) + 1
        self._emit(KplEvent(type="session_death", ts=time.time(),
                            session=self._session_no, cause=cause,
                            session_s=self._stats["last_session_s"],
                            err_code=self._session_err_code))
        self._status = "stopped"


def _frame_family(cmd) -> str:
    """按 cmd 族分组帧计数（隔离分析用）。"""
    if cmd == daban.CMD_DABAN_STOCK_LIST:
        return "2103_pages"
    if cmd == proto.CMD_HQ_REASONS:
        return "2203_perstock"
    if cmd == proto.CMD_STOCK_RELATED_THEME:
        return "2013_perstock"
    if cmd in (proto.CMD_GROUP_QUOTAS, proto.CMD_HQ_ID_LIST):
        return "3001_3006"
    if isinstance(cmd, int) and 2100 <= cmd <= 2126:
        return "globals"
    return f"other_{cmd}"


def run_session(idx: int, variant: str, codec, observe_s: float, tag: str, pool,
                reconnect=False, stock_ids=None, priority_ids=None, staged=False) -> dict:
    TMP.mkdir(exist_ok=True)
    dump = TMP / f"kplburst_{tag}_frames_s{idx}_{variant}.hex"
    os.environ["KPL_DEBUG"] = str(dump)
    svc = ProbeSurfaceCollector(
        codec, variant, pool=pool, reconnect=reconnect, staged=staged,
        device_id=os.environ.get("KPL_DEVICE_ID")
        or os.environ.get("QUANT_BOARD_KPL_APP_DEVICEID", ""),
        user_id=os.environ.get("KPL_USER_ID", "0"),
        token=os.environ.get("KPL_TOKEN", ""),
        stock_ids=stock_ids or ["801044"])
    if stock_ids:
        # 复现生产全量行情宇宙（3001/3006）：priority_ids 设优先块（分块轮询）
        svc.set_subscriptions(list(stock_ids), list(priority_ids or []))
    print(f"[s{idx}] variant={variant} pool={len(pool or [])} quotes={len(stock_ids or ['801044'])} "
          f"observe={observe_s}s reconnect={reconnect} staged={staged} dump={dump.name}", flush=True)
    t0 = time.time()
    svc.start()
    if reconnect:
        # 重连模式：跑满 observe_s 总时长（多会话累积），不提前退出
        time.sleep(observe_s)
    else:
        # 单会话：自然死亡（rst_10054 ~60s）提前结束；长寿（eof_clean）等满窗
        deadline = time.time() + observe_s
        while time.time() < deadline and svc.is_running() and svc._status != "stopped":
            time.sleep(1)
    svc.stop()
    if svc._thread is not None:
        svc._thread.join(timeout=15)
    events = list(svc._history)
    # 按族帧计数（C 帧=本端发送，从转储直读）
    frame_family = {}
    if dump.exists():
        for line in dump.read_text().splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            d, _ts, hx = parts
            if d != "C":
                continue
            try:
                fr = proto.parse_incoming(bytes.fromhex(hx))
            except Exception:
                continue
            fam = _frame_family(fr.get("cmd"))
            frame_family[fam] = frame_family.get(fam, 0) + 1
    summary = {
        "session": idx, "variant": variant, "tag": tag,
        "wall_s": round(time.time() - t0, 1),
        "session_s": svc._stats.get("last_session_s"),
        "setup_s": svc._stats.get("last_setup_s"),
        "death_cause": svc._last_death_cause,
        "death_cause_counts": dict(svc._death_cause_counts),
        "sessions_n": svc._stats.get("sessions", 0),
        "reconnect": reconnect,
        "err_code": svc._session_err_code,
        "session_death": [e for e in events if e["type"] == "session_death"],
        "frame_family": frame_family,
        "push_events": {t: sum(1 for e in events if e["type"] == t)
                        for t in ("stock_quotes", "daban", "zd_stat", "market_overview",
                                  "plate_strength", "zt_reasons", "theme_heat")},
        "unsub_sent_n": svc._stats.get("unsub_sent_n", 0),
        "staged_released_n": svc._stats.get("staged_released_n", 0),
        "staged_dropped_n": svc._stats.get("staged_dropped_n", 0),
        "staged": staged,
        "registry": svc._sub_registry.stats(),
        "server_errors": [e.get("server") for e in events if e["type"] == "error"],
        "ka_mode": svc._ka_mode, "sub_batch_mode": svc._sub_batch_mode,
        "pool_n": len(pool or []),
        "dump": str(dump),
    }
    (TMP / f"kplburst_{tag}_summary_s{idx}_{variant}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (TMP / f"kplburst_{tag}_events_s{idx}_{variant}.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    print(f"[s{idx}] done session_s={summary['session_s']} death={summary['death_cause']} "
          f"err_code={summary['err_code']} frames={frame_family} "
          f"unsub={summary['unsub_sent_n']}", flush=True)
    return summary


def dump_pool() -> int:
    """只读取 :8002 涨停池（pid=1）成员，打印逗号分隔 id（生产存活时运行）。"""
    import urllib.request
    url = "http://127.0.0.1:8002/api/kpl/daban-list?pid_type=1"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("items") or (data.get("data") or {}).get("items") or []
    ids = []
    for it in items:
        sid = str(it.get("stock_id") or "").strip()
        if sid and sid not in ids:
            ids.append(sid)
    print(",".join(ids))
    print(f"# pool_n={len(ids)}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="S0,S1,S2,S3", help="逗号分隔变体（S0/S1/S2/S3）")
    ap.add_argument("--sessions-per-variant", type=int, default=3)
    ap.add_argument("--observe-s", type=float, default=OBSERVE_S)
    ap.add_argument("--cooldown-s", type=float, default=COOLDOWN_S)
    ap.add_argument("--tag", default="b1", help="证据文件名轮次标签（防跨轮覆盖）")
    ap.add_argument("--pool", default="", help="per-stock 受控池（逗号分隔 id，S2/S3 必需）")
    ap.add_argument("--dump-pool", action="store_true", help="只读 :8002 涨停池打印 id 后退出")
    ap.add_argument("--reconnect", action="store_true",
                    help="生产同款连续重连（螺旋退避）模式：验证 rst_10054 是否重连累积驱动"
                         "（非盘中驱动）；observe-s 为总运行时长，死因取累计计数")
    ap.add_argument("--staged", action="store_true",
                    help="分波订阅模式（历史件；体积阈值假设已证伪，README §3.7）")
    ap.add_argument("--stock-ids-file", default="",
                    help="JSON {stock_ids,priority_ids}：复现生产全量 3001/3006 行情宇宙"
                         "（默认仅 1 板块，与生产差异是隔离 confound）；"
                         "来源 GET :8002/api/kpl/subscription-ids")
    args = ap.parse_args()
    if args.dump_pool:
        return dump_pool()
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    pool = [s.strip() for s in args.pool.split(",") if s.strip()]
    total = len(variants) * args.sessions_per_variant
    if total > MAX_SESSIONS:
        print(f"预算硬限：总会话 {total} > {MAX_SESSIONS}（预登记 §3）", file=sys.stderr)
        return 2
    for v in variants:
        if v not in VARIANT_SURFACE:
            print(f"非法变体 {v!r}（仅 S0/S1/S2/S3）", file=sys.stderr)
            return 2
        if v in _PER_STOCK_VARIANTS and not pool:
            print(f"{v} 需 --pool（先 --dump-pool 取池）", file=sys.stderr)
            return 2
    stock_ids = priority_ids = None
    if args.stock_ids_file:
        payload = json.loads(Path(args.stock_ids_file).read_text(encoding="utf-8"))
        stock_ids = payload.get("stock_ids") or None
        priority_ids = payload.get("priority_ids") or None
    codec = PCEmulatorCodec()   # pc 白盒轨（默认，无模拟器依赖）
    summaries = []
    idx = 0
    for vi, variant in enumerate(variants):
        for _ in range(args.sessions_per_variant):
            idx += 1
            if idx > 1:
                print(f"[cooldown] {args.cooldown_s}s ...", flush=True)
                time.sleep(args.cooldown_s)
            summaries.append(run_session(idx, variant, codec, args.observe_s, args.tag, pool,
                                         reconnect=args.reconnect, staged=args.staged,
                                         stock_ids=stock_ids, priority_ids=priority_ids))
    out = TMP / f"kplburst_{args.tag}_run.json"
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
    # 裁决矩阵速览（预登记 §2.3）：各变体 session_s/death_cause 中位
    print("\n[裁决速览] variant | sessions | session_s 中位 | death_cause 分布", flush=True)
    for v in variants:
        vs = [s for s in summaries if s["variant"] == v]
        ss = sorted(s["session_s"] or 0 for s in vs)
        med = ss[len(ss) // 2] if ss else 0
        causes = {}
        for s in vs:
            causes[s["death_cause"]] = causes.get(s["death_cause"], 0) + 1
        print(f"  {v} | {len(vs)} | {med} | {causes}", flush=True)
    print(f"[run] summaries → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())