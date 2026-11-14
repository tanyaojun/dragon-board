from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.data.repositories import repository_factory
from backend.data.archive.service import ArchiveService
from backend.data.backup.mongodb_backup import get_mongodb_backup_service
from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day
from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day_cached

_TZ = ZoneInfo("Asia/Shanghai")

_PULSE_OUT_DIR = Path("data/reports/phase-monitor")
_PULSE_TIMEOUT_SECONDS = 2700  # SP2-B：多臂脉拍（基线+champion+≤2 挑战者）由 900 提升至 45min
_JIUYAN_PREFLIGHT_MAX_REPAIRS = 2  # 预检补齐重试上限（采集本身幂等，重试防网络抖动）
_JEV_DAILY_LINE_TIMEOUT_SECONDS = 600  # 日度一句话：单次 jev 调用（client 内部 60s）+ 规则/落库，600s 冗余
_RELAY_INDEX_TIMEOUT_SECONDS = 600  # 连板指数：单次 jev 调用（七题一 call，实测 <1s）+ 原料拼装/落库，600s 冗余
_RELAY_BAND_TIMEOUT_SECONDS = 900  # 分带表重算：本地通达信全历史 ×约3000 只（实测 5–9 分钟），15min 冗余
# 2026-11-03 修复：d4b8de5a 误删该常量定义但 _run_relay_band_step 仍在使用，
# 当日 16:00 盘后链 NameError 中断；按 ee3bc290 原值恢复。
# 480s 覆盖最坏情况：每源 = 间隔 20s + HTTP 20s + 退避 60s + 重试间隔 20s + HTTP 20s = 140s，
# 3 源 = 420s（2026-10-20 review P1：原 300s 核算漏了重试迭代内的间隔，限流日会撞穿），
# +60s 落库/拼装冗余。逐段先落库（jiuyan_theme_collect），超时被杀只丢未抓的源。
# 实测 errCode=9 是短时限流，退避太短等于白打；见 theme-leader-nextday-preregistration §5.3
_THEME_COLLECT_TIMEOUT_SECONDS = 480
# KPL 采集子进程超时（最坏 11 调用 × (3s 间隔+请求) + 1 次退避 20s ≈ 80s，留 3 倍余量）
_KPL_COLLECT_TIMEOUT_SECONDS = 480  # 最坏 41 调用×(3s 间隔+RTT)+20s 退避（review 2026-11-02 Nit：240 贴限）
# 龙头级投喂（每日 1 call/龙头，实测 13 只 13 次调用 <2s/次 + 基线/取数）：1800s 冗余
_THEME_LEADER_TIMEOUT_SECONDS = 1800
_THEME_LEADER_RESULT_MARKER = "THEME_LEADER_RESULT_JSON:"   # 子进程结果行标记（机读接口，2026-11-02）
_THEME_LEADER_SETTLE_TIMEOUT_SECONDS = 300   # 结局回填：纯读库+写字段
# 龙虎榜补齐（B，2026-11-11 用户裁决）：HisBeOnTheLHB 主榜凌晨批处理生成（11-11 夜
# 实测：23:42 仍结构化空态，00:08 到达，窗口 (23:42, 00:12]）——00:30 凌晨同夜补齐
# + 07:10 次晨保险两时点，零 token 探针 + 有新数据才定向重跑；lookback 自愈。
_LHB_BACKFILL_LOOKBACK = 5
# 上游分钟级限频先例（kpl_lhb_history 文档串，红线 9）：多日探针间留间隔；
# 预算 = 4 端点/探针日 × 有 pending 的日数（无 pending 日不探针），仅 00:30/07:10 两时点
_LHB_BACKFILL_PROBE_GAP_S = 3.0
_ARMS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "phase_pulse_arms.json"


def _pulse_arms_args() -> list[str]:
    """SP2-B：排程脉拍多臂参数（挑战者臂经 config/phase_pulse_arms.json 登记；预算≤2）。

    配置文件缺失/解析失败 → 回退默认两臂（baseline,champion，fail-visible 不阻断排程）。
    """
    try:
        raw = json.loads(_ARMS_CONFIG_PATH.read_text(encoding="utf-8"))
        names = [k for k, v in raw.items() if isinstance(v, dict) and isinstance(v.get("trade_config"), dict)]
        challengers = [k for k in names if k not in ("baseline", "champion")]
        if len(challengers) > 2:
            challengers = challengers[:2]  # 预算截断（超出者不进排程，fail-visible 于日志）
            print(f"[schedule] 挑战者臂超预算，仅取前 2：{challengers}", file=sys.stderr)
        return ["--arms", ",".join(["baseline", "champion", *challengers]),
                "--arm-config", str(_ARMS_CONFIG_PATH)]
    except FileNotFoundError:
        print(f"[schedule] 臂配置缺失，回退默认两臂：{_ARMS_CONFIG_PATH}", file=sys.stderr)
        return []
    except Exception as exc:  # noqa: BLE001 — 排程步不因臂配置畸形阻断
        print(f"[schedule] 臂配置解析失败，回退默认两臂：{exc}", file=sys.stderr)
        return []


def _should_run_phase_pulse(db: Any, today: str, dataset_id: str, snapshot_type: str) -> tuple[bool, str]:
    """脉拍门控：当日有 EOD 情绪文档才跑（非交易日/数据未落 → 跳过，不烧算力不覆盖旧档）。"""
    try:
        doc = db["hotlist_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": snapshot_type, "tradingDate": today, "slotTime": "EOD"},
            {"_id": 1},
        )
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        return False, f"gate check failed: {exc}"
    if not doc:
        return False, f"no EOD doc for {today}（非交易日或数据未落）"
    return True, ""


def run_jiuyan_preflight(today: str) -> dict[str, Any]:
    """盘后链预检（2026-11-04 用户裁决）：韭研远端名单数 vs 落库 final 一致性。

    背景：韭研异动解析盘后持续补名单，15:35 采集版可能不完整（当日实测 44 只、
    晚间 136；THS 独立口径涨停 116+炸板 32）——名单不完整不得打标（不完整投喂
    会烧 token 且下游叙事/归因全部基于残名单）。

    规则：**非交易日直接跳过**（2026-11-07 事故：周六预检仍探针+重采，把韭研「最近
    交易日」(11-06) 名单落到 11-07 名下产生 42 只残档；韭研端点非交易日返回最近
    交易日名单，采了必错档）。交易日：探针 count-pc（零 jev token，韭研额度内）
    对落库 `jiuyan_action {date}:final` 的 counts.all；不一致 → 幂等重采补齐
    （collect_and_store，零 jev token）再核；补齐后仍不一致 → ok=False
    （链 stoppedAt=jiuyanPreflight 拦停，人工介入）；探针失败/载荷缺 all/
    补齐后复核不可知 → ok=True + 结构化 warning
    （远端不可知 ≠ 确认不一致，不能拦住备份链，fail-visible 待人工关注）。
    """
    trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
    if not trading:
        # 同 mongodbBackup 步口径：非交易日跳过并记录判定来源（bridge→cache→weekday）
        return {"ok": True, "date": today, "skipped": "non_trading_day",
                "calendarSource": cal_source,
                "note": "非交易日不探针不采不拦链（韭研非交易日返回最近交易日名单，采了必错档）"}
    from backend.operations.jiuyan_auth import resolve_auth
    from backend.operations.jiuyan_collect import collect_and_store
    from backend.operations.jiuyan_fetch import fetch_count
    db = repository_factory.get_runtime_mongodb_database()

    def _stored_all() -> int | None:
        doc = db["jiuyan_action"].find_one({"_id": f"{today}:final"}, {"counts.all": 1})
        return (doc.get("counts") or {}).get("all") if doc else None

    def _probe() -> dict[str, Any]:
        auth = resolve_auth(date=today)
        if not auth.get("ok"):
            return {"ok": False, "authFailed": True,
                    "error": {"code": "jiuyan_preflight_auth_failed", "message": str(auth)[:200]}}
        probe = fetch_count(today, session_cookie=auth["session"],
                            token=auth["token"], timestamp=auth["timestamp"])
        if not probe.get("ok") and probe.get("authFailed"):
            # authFailed 自愈（同调度支线口径）：会话/token 缓存过期 → 强制重登重铸再试一次
            auth = resolve_auth(date=today, force_refresh=True)
            if not auth.get("ok"):
                return {"ok": False, "authFailed": True,
                        "error": {"code": "jiuyan_preflight_auth_failed",
                                  "message": f"自愈后仍失败: {str(auth)[:150]}"}}
            probe = fetch_count(today, session_cookie=auth["session"],
                                token=auth["token"], timestamp=auth["timestamp"])
        return probe

    repairs: list[dict[str, Any]] = []
    try:
        stored = _stored_all()
        probe = _probe()
        if not probe.get("ok"):
            return {"ok": True, "date": today, "checked": False,
                    "storedCountsAll": stored,
                    "warning": {"code": "jiuyan_preflight_probe_failed",
                                "message": str(probe.get("error") or probe)[:200]},
                    "note": "远端名单数不可知，链继续（不拦备份链）；名单完整性未验证，fail-visible"}
        remote = probe.get("all")
        if remote is None:
            # 探针 ok 但载荷无 all（parse_count_response 缺失时不伪造 0）→ 远端不可知，
            # 同探针失败口径：不拦链、不重采，fail-visible（否则会空转重采并误拦停）
            return {"ok": True, "date": today, "checked": False,
                    "storedCountsAll": stored,
                    "warning": {"code": "jiuyan_preflight_probe_incomplete",
                                "message": "探针响应缺 all 字段，远端名单数不可知"},
                    "note": "远端名单数不可知，链继续（不拦备份链）；名单完整性未验证，fail-visible"}
        for attempt in range(1, _JIUYAN_PREFLIGHT_MAX_REPAIRS + 1):
            if stored is not None and remote is not None and stored >= remote:
                return {"ok": True, "date": today, "checked": True,
                        "remoteCountsAll": remote, "storedCountsAll": stored,
                        "repairs": repairs,
                        "note": "落库名单数 ≥ 远端探针数，一致（≥ 容忍源端晚回缩的重复去重）"}
            # 不一致（远端更多 / 落库缺失）→ 幂等重采补齐
            recollect = collect_and_store(today, "final", db=db)
            repairs.append({"attempt": attempt, "before": stored, "remote": remote,
                            "ok": bool(recollect.get("ok")),
                            "stocks": recollect.get("stocks"),
                            "error": recollect.get("error")})
            if not recollect.get("ok"):
                break
            stored = _stored_all()
            probe = _probe()
            if not probe.get("ok") or probe.get("all") is None:
                # 补齐后复核不可知（探针失败/载荷缺 all）≠ 确认不一致：重采本身已按
                # 当时源端数据落库，不拦链，结构化 warning 待人工关注（同顶层口径）
                return {"ok": True, "date": today, "checked": True,
                        "remoteCountsAll": remote, "storedCountsAll": stored,
                        "repairs": repairs,
                        "warning": {"code": "jiuyan_preflight_repair_verify_unknown",
                                    "message": f"补齐后复核不可知: {str(probe.get('error') or probe)[:120]}"},
                        "note": "重采已落库（当时源端数据），复核对账未完成，链继续，需人工关注"}
            remote = probe.get("all")
        return {"ok": False, "date": today, "checked": True,
                "remoteCountsAll": remote, "storedCountsAll": stored,
                "repairs": repairs,
                "error": {"code": "jiuyan_preflight_inconsistent",
                          "message": f"补齐 {_JIUYAN_PREFLIGHT_MAX_REPAIRS} 次后远端={remote} 落库={stored} 仍不一致，名单不完整不得打标，链拦停待人工"}}
    except Exception as exc:  # noqa: BLE001 — 预检自身异常不拦链（不可校验 ≠ 不一致，fail-visible）
        return {"ok": True, "date": today, "checked": False, "repairs": repairs,
                "warning": {"code": "jiuyan_preflight_error",
                            "message": f"{type(exc).__name__}: {exc}"[:200]},
                "note": "预检自身异常，链继续；名单完整性未验证，需人工关注"}


def _run_phase_pulse_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """M3 盘面脉拍（advisory 步，2026-10-01）：子进程隔离跑当月至今相位快照。

    - 门控=当日 EOD 情绪文档存在（is_trading_day 日历之外的更强校验：数据真落了才跑）；
    - 子进程=独立 python 引擎（与备份链进程内存隔离，8.5GB 扫描事故纪律），超时 900s；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（研究证据链，非生产数据链）；
    - 结果：data/reports/phase-monitor/pulse-<month>.json + Mongo phase_monitor（pulse:<month>），
      前端相位页签"本月至今"卡直接读。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    month = today[:7]
    out_path = _PULSE_OUT_DIR / f"pulse-{month}.json"
    cmd = [
        sys.executable, "-m", "backend.operations.phase_pulse",
        "--month", month, "--end", today, "--out", str(out_path),
        *_pulse_arms_args(),
    ]
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),  # SP2-B 修复：原 parents[1]=backend/ 导致 ModuleNotFoundError，排程脉拍从未能运行
            capture_output=True,
            text=True,
            timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "phase_pulse_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "phase_pulse_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    # SP2-B：Mongo 入库为准（前端走 board API 读 Mongo；本地 JSON 仅为即时产物）。
    # phase_pulse.main 内 persist_pulse 幂等 upsert pulse:<month>；此处校验 updatedAt 新鲜度。
    mongo_fresh = False
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc_m = db["phase_monitor"].find_one({"_id": f"pulse:{month}"}, {"updatedAt": 1})
        updated = str((doc_m or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    summary: dict[str, Any] = {}
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8"))
        ab = doc.get("ab") or {}
        summary = {
            "month": doc.get("month"),
            "tradeCount": doc.get("tradeCount"),
            "netReturnSaved": (ab.get("delta") or {}).get("netReturnSaved"),
        }
    except Exception as exc:  # noqa: BLE001 — 摘要解析失败不影响脉拍本体已落库
        summary = {"parseError": str(exc)}
    # 评审 P1-2：记录的臂清单从脉拍参数回填（单一事实源=config 登记文件），不再维护过期常量
    pulse_args = _pulse_arms_args()
    arms_record = "baseline,champion"
    if len(pulse_args) >= 2 and pulse_args[0] == "--arms":
        arms_record = pulse_args[1]
    result = {"ok": True, "month": month, "out": str(out_path), "summary": summary,
              "mongoFresh": mongo_fresh, "arms": arms_record}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor pulse:<month> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    return result


def _should_run_phase_band(db: Any, today: str) -> tuple[bool, str]:
    """相位哨兵门控：当日韭研 final 名单 + 15:00 盘面帧都存在才跑（缺一→哨兵无原料，跳过）。"""
    try:
        jy = db["jiuyan_action"].find_one({"_id": f"{today}:final"}, {"_id": 1})
        fr = db["snapshot_frames"].find_one(
            {"type": "half_hour", "tradingDate": today, "slotTime": "15:00",
             "limitSummary.zhaban.ztCount": {"$gt": 0}}, {"_id": 1})
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        return False, f"gate check failed: {exc}"
    if not jy:
        return False, f"no jiuyan final for {today}"
    if not fr:
        return False, f"no 15:00 frame metrics for {today}"
    return True, ""


def _run_phase_band_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """Q5 相位哨兵（advisory 步，2026-10-03）：日级独立调用判当日盘面档位。

    - 门控=当日 jiuyan final + 15:00 盘面帧（原料齐才跑，非交易日/缺料跳过）；
    - 子进程=jev_label_jiuyan --phase-band-day（幂等：当日 PHASE 文档已 ok 自动跳过）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（哨兵证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_label_jiuyan", "--phase-band-day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "phase_band_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "phase_band_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    phase_band = None
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{today}:PHASE"},
                                                       {"phaseBand": 1, "computedAt": 1})
        phase_band = doc.get("phaseBand") if doc else None
        updated = str((doc or {}).get("computedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "date": today, "phaseBand": phase_band, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "PHASE 文档 computedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    if mongo_error:
        result["mongoWarning"] = f"mongo 校验异常（advisory 不翻转）：{mongo_error}"
    return result


def jiuyan_theme_collect_enabled() -> bool:
    """题材/事件语料采集开关（L3，2026-10-20；默认开，`JIUYAN_THEME_COLLECT_ENABLED=0` 可关）。"""
    return os.environ.get("JIUYAN_THEME_COLLECT_ENABLED", "1") != "0"


def _maybe_launch_stocktree_weekly(today: str) -> dict[str, Any]:
    """V3-1 全成分周频刷新守卫（2026-10-25 用户拍板「每周日全量」的等价实现）。

    周日无交易日挂链 → 改为交易日 16:10 守卫：距 `jiuyan_industry_stocks` 最新
    成功批次 ≥7 自然日（或从未拉过）则 Popen 挂跑全量，节假日自动顺延补拉。
    Popen 不等待：108 次 × 20s 间隔 ≈ 36min+ 远超任何步骤超时；断点续拉保证
    被杀后下一守卫窗口续上。开关 `JIUYAN_STOCKTREE_WEEKLY_ENABLED=0` 可关。
    """
    if os.environ.get("JIUYAN_STOCKTREE_WEEKLY_ENABLED", "1") == "0":
        return {"ok": True, "skipped": True, "reason": "disabled"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        from backend.operations import jiuyan_theme_store as _ts
        batch = _ts.latest_industry_stocks_batch(db)
    except Exception as exc:  # noqa: BLE001 — advisory 守卫，失败结构化返回
        return {"ok": False, "error": {"code": "stocktree_guard_failed",
                                       "message": f"{type(exc).__name__}: {exc}"}}
    if batch:
        try:
            age = (datetime.strptime(today, "%Y-%m-%d")
                   - datetime.strptime(str(batch), "%Y-%m-%d")).days
        except ValueError:
            age = 99
        if age < 7:
            return {"ok": True, "skipped": True, "reason": f"fresh_batch:{batch}"}
    log_path = Path(__file__).resolve().parents[2] / "logs" / f"stocktree-{today}.log"
    # 在途互斥（review P2）：当日日志已存在（手工挂跑进行中/已跑）不再 Popen——
    # 完成态由上方批次年龄判定覆盖，这里拦的正是 in-flight 窗口（双进程并发会
    # 双倍速率撞 errCode=9 + 同日志互写）。
    if log_path.exists():
        try:
            if datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%Y-%m-%d") == today:
                return {"ok": True, "skipped": True,
                        "reason": f"in_flight_or_done_today:{log_path.name}"}
        except OSError:
            pass
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 动态预算（review P3-1）：16:10 collect_once 已用 N 次计入同一账本，固定
    # 120 在 N 大时会把周刷挤成连续顺延——传「当日已用 + 108 全量 + 2 重试余量」。
    try:
        used = _ts.calls_recorded(db, today)
    except Exception:  # noqa: BLE001 — 计数失败不拦刷新，回落静态预算
        used = 0
    cmd = [sys.executable, "-m", "backend.operations.jiuyan_theme_collect",
           "--stock-tree", "--date", today, "--budget", str(used + 110)]
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parents[2]),
                             stdout=fh, stderr=subprocess.STDOUT)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "stocktree_launch_failed",
                                       "message": f"{type(exc).__name__}: {exc}"}}
    return {"ok": True, "launched": True, "lastBatch": batch, "log": str(log_path.name)}


def theme_leader_label_enabled() -> bool:
    """题材层龙头投喂开关（2026-10-20 用户裁决每日自动投喂；默认开）。"""
    return os.environ.get("THEME_LEADER_LABEL_ENABLED", "1") != "0"


def _parse_theme_leader_stdout(stdout: str | None,
                               marker: str | None = None) -> tuple[dict | None, str]:
    """结果 JSON 提取（2026-11-02 修复；2026-11-11 抽出供补齐链复用）。

    子进程以 `THEME_LEADER_RESULT_JSON:` 标记行输出结果（单行）；旧逻辑「首个 { 截取」
    会被 stdout 前部的降级披露行（P2-6，含 Python dict 单引号文本）截中 → parse_failed
    → 结局回填被整体跳过（10-29/10-30 两日结局漏回填的根因）。兼容回退：从后往前
    找首行可解析 dict。
    """
    result = None
    parse_error = "result JSON line not found in stdout"
    for line in reversed((stdout or "").splitlines()):
        cand = line.strip()
        _marker = marker or _THEME_LEADER_RESULT_MARKER
        if cand.startswith(_marker):
            cand = cand[len(_marker):].strip()
        if not cand.startswith("{"):
            continue
        try:
            result = json.loads(cand)
            break
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
            continue
    return result, parse_error


def run_theme_leader_label_once(today: str | None = None, *,
                                dry_run: bool = False) -> dict[str, Any]:
    """题材层「板块龙头隔日连板」投喂（17:30 调度，2026-10-20 挂链；
    2026-10-30 用户裁决改时）。

    与个股驱动链的关系：完全独立集合（`hotlist_jev_theme_leader_labels`）、独立题集代际，
    每条 = 一个**板块龙头**（不是每只涨停股），**1 call/龙头/日**（≈13–20 次/日，
    实测 2026-10-19：13 次真调用 29,014 tokens）。

    门控：开关（`THEME_LEADER_LABEL_ENABLED`）→ 交易日（非抛错日历：bridge 宕机不丢一天）→
    子进程自身幂等（`_id={date}:{code}` 已 `status=ok` 跳过，重跑不重复烧 token）。
    时点 17:30：晚于 16:10 的题材语料刷新（当日晚于收盘的催化正文先进库）、15:35 收盘
    名单采集；15:35 名单完整性由 17:00 盘后链预检 run_jiuyan_preflight 补齐保障（2026-11-04）。
    龙虎榜主榜（HisBeOnTheLHB）生成系统性晚于 17:30（2026-11-11 实证：17:30~21:37 仍空，
    次晨已完整；约 17:00 生成的是席位榜）——当日主榜事实行由 C 席位/机构兜底 + B 补齐链
    （run_theme_leader_lhb_backfill_once，00:30/07:10）保障，不再依赖挂链时点（§5.4）。

    预算语义（§1.2-7）：本步属**预登记日包络**下的常态挂链（2026-11-11 实测 22 doc/日
    ≈112k tokens；旧 ≈29k 为 13 龙头旧口径），故直接带 `--confirm-budget`；无包络的路必须走 CLI 人工批准。

    advisory 语义：失败/跳过不翻转调用方整体 ok。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "date": today}
    if not theme_leader_label_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled", "date": today}
    try:
        trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        return {"ok": False, "date": today,
                "error": {"code": "theme_leader_gate_failed", "message": f"{type(exc).__name__}: {exc}"}}
    if not trading:
        return {"ok": True, "skipped": True, "reason": "non_trading_day", "date": today,
                "calendarSource": cal_source}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.theme_leader_label",
             "--date", today, "--confirm-budget"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_THEME_LEADER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "date": today,
                "error": {"code": "theme_leader_timeout",
                          "message": f"timeout {_THEME_LEADER_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "date": today,
                "error": {"code": "theme_leader_failed",
                          "message": (proc.stderr or proc.stdout or "")[-400:]}}
    # 结果 JSON 提取（2026-11-02 修复；2026-11-11 抽出 _parse_theme_leader_stdout 复用）
    result, parse_error = _parse_theme_leader_stdout(proc.stdout)
    if result is None:
        return {"ok": False, "date": today,
                "error": {"code": "theme_leader_parse_failed", "message": parse_error}}
    out: dict[str, Any] = {"ok": bool(result.get("ok")), "date": today,
                           "leaders": result.get("leaders"), "labeled": result.get("labeled"),
                           "degraded": result.get("degraded"), "tokensUsed": result.get("tokensUsed"),
                           "estimatedTokensBudgetGuard": result.get("estimatedTokensBudgetGuard"),
                           "questionSetVersion": result.get("questionSetVersion")}
    # 同一步顺带回填**近期未封**的次日结局（零 token，只读库 + 写 outcome 字段）：
    # 否则 pilot 会只攒标签不攒结局，20 日门槛永远算不出来（2026-10-20 加）。
    settled = _settle_recent_theme_leader_days(today)
    if settled:
        out["settledRecentDays"] = settled
    return out


def _settle_recent_theme_leader_days(today: str, lookback: int = 5) -> list[dict[str, Any]]:
    """回填近 `lookback` 个交易日里**仍未封**（`outcomeSealedNextDay` 缺失/None）的结局。

    - 自愈语义：某天因次日 THS 池缺失/采集中断而没封上，之后任一次挂链都会补（不靠人记得手跑）；
    - 已封的日子不重算（幂等，省进程）；零模型调用（只读库 + 写 outcome 字段）；
    - 单日失败只记该日结果，不翻转本步 ok（advisory）。
    """
    results: list[dict[str, Any]] = []
    try:
        db = repository_factory.get_runtime_mongodb_database()
        from backend.operations.theme_leader_baseline import trading_dates
        days = [d for d in trading_dates(db, "2000-01-01", today) if d < today][-lookback:]
        col = db["hotlist_jev_theme_leader_labels"]
        for day in days:
            pending = col.count_documents({"tradingDate": day,
                                           "status": "ok",
                                           # v12 拆题：板块级 doc（code=None）无结局可回填，不进 pending
                                           "code": {"$ne": None},
                                           "outcomeSealedNextDay": None})
            # 后日（T+2）打板溢价 pending（2026-10-26 用户口径裁定：打板=T+1 入场无浮盈，
            # 博弈 T+2 溢价）：T+1 已封但 outcomeDay2 未回填的日子——注意 T+2 晚场景
            # pending=0 而 pending_day2>0，两判都要过才算无事可做。
            pending_day2 = col.count_documents({
                "tradingDate": day, "status": {"$in": ["ok", "degraded"]},
                "code": {"$ne": None},
                "outcomeSealedNextDay": True,
                "outcomeDay2.date": {"$exists": False}})
            if not pending and not pending_day2:
                continue
            if pending:
                proc = subprocess.run(
                    [sys.executable, "scripts/theme_leader_pilot_eval.py",
                     "--date", day, "--write-outcome"],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=_THEME_LEADER_SETTLE_TIMEOUT_SECONDS,
                )
                lines_ = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
                head = [ln for ln in lines_ if "→ 次日" in ln] or lines_[-1:]
                results.append({
                    "ok": proc.returncode == 0, "date": day, "pending": pending,
                    "summary": head[0] if head else "",
                    # 成功时不把 stderr 噪声（如政策提示 banner）当 error 上抛，避免把正常当故障看
                    "error": ((proc.stderr or "")[-200:] or None) if proc.returncode else None})
            if pending_day2:
                # day2 已收盘的日子本步结算 outcomeDay2；未到/pending 留给后续挂链自愈。
                # advisory，失败不翻转本步 ok。
                proc2 = subprocess.run(
                    [sys.executable, "scripts/theme_leader_pilot_eval.py",
                     "--date", day, "--write-day2"],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=_THEME_LEADER_SETTLE_TIMEOUT_SECONDS,
                )
                lines2 = [ln for ln in (proc2.stdout or "").splitlines() if ln.strip()]
                head2 = [ln for ln in lines2 if "→ 后日" in ln] or lines2[-1:]
                results.append({
                    "ok": proc2.returncode == 0, "date": day, "pending": pending_day2,
                    "step": "day2_premium", "summary": head2[0] if head2 else "",
                    "error": ((proc2.stderr or "")[-200:] or None) if proc2.returncode else None})
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        results.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return results


# ── 竞价龙头晨间链（vA1，2026-11-13 预登记 auction-leader-vA1；09:26 挂链） ──
_AUCTION_LEADER_TIMEOUT_SECONDS = 900
_AUCTION_LEADER_SETTLE_TIMEOUT_SECONDS = 300


def auction_leader_label_enabled() -> bool:
    """竞价龙头晨间投喂开关（A5：默认开，镜像 THEME_LEADER_LABEL_ENABLED）。"""
    return os.environ.get("AUCTION_LEADER_LABEL_ENABLED", "1") != "0"


def run_auction_leader_label_once(today: str | None = None, *,
                                  dry_run: bool = False) -> dict[str, Any]:
    """竞价龙头晨间投喂（09:26 调度；9:25 竞价冻结 + archiver ≤60s 轮询 lag）。

    门控：开关 → 交易日 → 子进程幂等；预算语义同 17:30 链（预登记日包络挂链
    直接带 --confirm-budget；无包络的路走 CLI 人工批准）。advisory：失败不翻转调用方 ok。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "date": today}
    if not auction_leader_label_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled", "date": today}
    try:
        trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        return {"ok": False, "date": today,
                "error": {"code": "auction_leader_gate_failed",
                          "message": f"{type(exc).__name__}: {exc}"}}
    if not trading:
        return {"ok": True, "skipped": True, "reason": "non_trading_day", "date": today,
                "calendarSource": cal_source}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.auction_leader_label",
             "--date", today, "--confirm-budget"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_AUCTION_LEADER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "date": today,
                "error": {"code": "auction_leader_timeout",
                          "message": f"timeout {_AUCTION_LEADER_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "date": today,
                "error": {"code": "auction_leader_failed",
                          "message": (proc.stderr or proc.stdout or "")[-400:]}}
    from backend.operations.auction_leader_label import RESULT_MARKER
    result, parse_error = _parse_theme_leader_stdout(proc.stdout, marker=RESULT_MARKER)
    if result is None:
        return {"ok": False, "date": today,
                "error": {"code": "auction_leader_parse_failed", "message": parse_error}}
    return {"ok": bool(result.get("ok")), "date": today,
            "leaders": result.get("leaders"), "okCount": result.get("okCount"),
            "degraded": result.get("degraded"), "tokensUsed": result.get("tokensUsed"),
            "estimatedTokensBudgetGuard": result.get("estimatedTokensBudgetGuard"),
            "skippedReason": result.get("skippedReason"),
            "questionSetVersion": result.get("questionSetVersion")}


def run_auction_leader_settle_once(today: str | None = None) -> dict[str, Any]:
    """竞价龙头当日结局回填（16:10 挂链，零 token；lookback 5 日自愈）。

    outcomeSealedToday = 当日 daban pool 封板成员（THS 交叉披露）；当日 + 历史
    pending 日都补（进程重启/采集中断自愈）；单日失败只记该日结果（advisory）。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    results: list[dict[str, Any]] = []
    try:
        db = repository_factory.get_runtime_mongodb_database()
        from backend.operations.theme_leader_baseline import trading_dates
        days = [d for d in trading_dates(db, "2000-01-01", today) if d <= today][-5:]
        col = db["hotlist_jev_auction_leader_labels"]
        for day in days:
            pending = col.count_documents({"tradingDate": day, "docKind": "leader",
                                           "outcomeSealedToday": None})
            if not pending:
                continue
            proc = subprocess.run(
                [sys.executable, "scripts/auction_leader_pilot_eval.py",
                 "--date", day, "--write-outcome"],
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_AUCTION_LEADER_SETTLE_TIMEOUT_SECONDS,
            )
            lines_ = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
            head = [ln for ln in lines_ if "→ 当日" in ln] or lines_[-1:]
            results.append({"ok": proc.returncode == 0, "date": day, "pending": pending,
                            "summary": head[0] if head else "",
                            "error": ((proc.stderr or "")[-200:] or None)
                            if proc.returncode else None})
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        results.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": all(r.get("ok") for r in results) if results else True,
            "date": today, "settledDays": results}


def theme_leader_lhb_backfill_enabled() -> bool:
    """龙虎榜补齐开关（B，2026-11-11 用户裁决；默认开，随投喂总开关门控）。"""
    return os.environ.get("THEME_LEADER_LHB_BACKFILL_ENABLED", "1") != "0"


def run_theme_leader_lhb_backfill_once(today: str | None = None, *,
                                       lookback: int = _LHB_BACKFILL_LOOKBACK,
                                       dry_run: bool = False) -> dict[str, Any]:
    """龙虎榜语料补齐（B，2026-11-11 用户裁决；scheduler 00:30 凌晨 + 07:10 次晨）。

    背景：HisBeOnTheLHB 交易所分组榜凌晨批处理生成，系统性晚于 17:30 挂链（11-11 夜
    实测：23:42 仍结构化空态，00:08 到达，窗口 (23:42, 00:12]；次晨 07:22 已完整）——
    17:30 链拿不到主榜，按 §1.2-8 整行缺席。本链 = 零 token 探针 + 有新数据才定向重跑：
    - pending 检测：doc.lhbState.mainAvailable=False（A 留痕）；legacy doc（无 lhbState）
      按叙事缺「龙虎榜：」行判；**status=degraded 无条件 pending**（调用失败档需重标，
      含补齐自身失败留下的档——否则失败重跑把 ok 档写成 degraded 后永久搁浅）；
    - 探针：collect_lhb_facts(day) 每 pending 日一次（4 HTTP 端点，30s TTL；多日间隔
      _LHB_BACKFILL_PROBE_GAP_S，上游分钟级限频先例，红线 9）；无 pending 日不探针；
    - 重跑条件：主榜到达（groups/stocks 非空）；legacy doc 另席位/机构榜到达也触发
      （C 兜底行对它是新语料）；已有 lhbState 的 doc 席位-only 增量**不触发**
      （兜底行可能已出，等主榜到达一次补齐，防双烧 token）；degraded pending 无条件
      触发（修复路径；通道挂时 runner 零 usage 快速中止不烧 token，但会把首 2 档写成
      degraded——故通道中止后本次调用不再发后续子进程，下一时点再试）；
    - 定向重跑：pending 龙头 --codes + 独立 pending 板块 --boards（≤2 子进程，
      --force --confirm-budget；codes 链顺带重建其板别 sector doc，板粒度；
      outcome* 事实字段由 runner 原样带走）；
    - 预算（§1.2-7）：重跑属 2026-11-11 用户裁决补齐包络（每 pending 日 ≤1 日包络，
      探针缺席零消耗）；预登记见 theme-leader-nextday-preregistration §5.4。
    自愈：lookback 个交易日，任一时点失败/缺席由后续时点自动补（与结局回填同哲学）。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    if not theme_leader_label_enabled() or not theme_leader_lhb_backfill_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled", "date": today}
    db = repository_factory.get_runtime_mongodb_database()
    from backend.operations.theme_leader_baseline import trading_dates
    try:
        days = [d for d in trading_dates(db, "2000-01-01", today) if d <= today]
    except Exception:  # noqa: BLE001 — advisory：日历失败退回仅今日，不翻转整链
        days = []
    if today not in days:
        try:
            trading, _src = is_trading_day_cached(
                datetime.strptime(today, "%Y-%m-%d").date())
        except Exception:  # noqa: BLE001
            trading = False
        if trading:
            days.append(today)
    days = sorted(set(days))[-lookback:]
    col = db["hotlist_jev_theme_leader_labels"]
    from backend.analysis.hotlist.jev_lhb_ammo import collect_lhb_facts
    out_days: list[dict[str, Any]] = []
    tokens_total = 0
    all_ok = True
    probed = False
    for day in days:
        docs = [d for d in col.find({"tradingDate": day})
                if d.get("status") in ("ok", "degraded")]
        pending, legacy, degraded = [], [], []
        for d in docs:
            if d.get("status") == "degraded":
                pending.append(d)
                degraded.append(d)
                continue
            st = d.get("lhbState")
            if isinstance(st, dict):
                if not st.get("mainAvailable"):
                    pending.append(d)
            elif "龙虎榜：" not in (d.get("narrative") or ""):
                pending.append(d)
                legacy.append(d)
        if not pending:
            out_days.append({"date": day, "pending": 0, "action": "skip",
                             "skipReason": "no_pending"})
            continue
        if probed:
            time.sleep(_LHB_BACKFILL_PROBE_GAP_S)   # 限频间隔（红线 9）
        probed = True
        try:
            facts = collect_lhb_facts(day)
        except Exception as exc:  # noqa: BLE001 — 探针失败结构化跳过，下一时点补
            out_days.append({"date": day, "pending": len(pending),
                             "pendingLegacy": len(legacy), "action": "skip",
                             "skipReason": f"probe_failed: {type(exc).__name__}: {exc}"})
            continue
        main_now = bool(facts.get("groups") or facts.get("stocks"))
        seat_now = bool(facts.get("stock_board") or facts.get("agency"))
        probe = {"mainAvailable": main_now,
                 "seatN": len(facts.get("stock_board") or {}),
                 "agencyN": len(facts.get("agency") or {}),
                 "listOk": bool(facts.get("list_ok")),
                 "stockOk": bool(facts.get("stock_ok")),
                 "emptyStructured": bool(facts.get("empty_structured")),
                 "reason": facts.get("reason")}
        need_rerun = main_now or (bool(legacy) and seat_now) or bool(degraded)
        if not need_rerun:
            out_days.append({"date": day, "pending": len(pending),
                             "pendingLegacy": len(legacy), "probe": probe,
                             "action": "skip", "skipReason": "lhb_data_not_available"})
            continue
        if dry_run:
            out_days.append({"date": day, "pending": len(pending),
                             "pendingLegacy": len(legacy), "probe": probe,
                             "action": "would_rerun"})
            continue
        # 定向重跑：pending 龙头（--codes，顺带重建其板别 sector doc）+
        # 独立 pending 板块（--boards，codes 链未覆盖的板别）
        leader_codes = sorted({str(d["code"]) for d in pending
                               if d.get("docKind") == "leader" and d.get("code")})
        covered_boards = {str(d["board"]) for d in pending
                          if d.get("docKind") == "leader" and d.get("board")}
        sector_boards = sorted({str(d["board"]) for d in pending
                                if d.get("docKind") == "sector" and d.get("board")}
                               - covered_boards)
        extra_runs: list[list[str]] = []
        if leader_codes:
            extra_runs.append(["--codes", ",".join(leader_codes)])
        if sector_boards:
            extra_runs.append(["--boards", ",".join(sector_boards)])
        if not extra_runs:
            extra_runs.append([])   # 防御：pending 无 code/board（异常形状）→ 全日重跑
        runs: list[dict[str, Any]] = []
        channel_down = False
        for extra in extra_runs:
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "backend.operations.theme_leader_label",
                     "--date", day, "--force", "--confirm-budget", *extra],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=_THEME_LEADER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                runs.append({"ok": False, "args": extra,
                             "error": f"timeout {_THEME_LEADER_TIMEOUT_SECONDS}s"})
                all_ok = False
                continue
            if proc.returncode != 0:
                runs.append({"ok": False, "args": extra,
                             "error": (proc.stderr or proc.stdout or "")[-400:]})
                all_ok = False
                continue
            result, parse_error = _parse_theme_leader_stdout(proc.stdout)
            if result is None:
                runs.append({"ok": False, "args": extra, "error": parse_error})
                all_ok = False
                continue
            used = int(result.get("tokensUsed") or 0)
            tokens_total += used
            runs.append({"ok": bool(result.get("ok")), "args": extra,
                         "labeled": result.get("labeled"), "tokensUsed": used,
                         **({"aborted": result["aborted"]} if result.get("aborted") else {})})
            if not result.get("ok"):
                all_ok = False
            if result.get("aborted") == "channel_unreachable":
                # 通道挂：零 usage 快速中止已把首 2 档写 degraded——不再发后续子进程
                # （避免逐日扩散降级），下一时点探针+重跑自愈
                channel_down = True
                break
        out_days.append({"date": day, "pending": len(pending),
                         "pendingLegacy": len(legacy), "probe": probe,
                         "action": "rerun", "runs": runs})
        if channel_down:
            for rest in days[days.index(day) + 1:]:
                out_days.append({"date": rest, "action": "skip",
                                 "skipReason": "channel_unreachable_abort"})
            break
    return {"ok": all_ok, "date": today, "days": out_days, "tokensUsed": tokens_total}


def run_theme_corpus_collect_once(today: str | None = None, *,
                                  dry_run: bool = False,
                                  collectors: tuple[str, ...] = ("kpl", "jiuyan")) -> dict[str, Any]:
    """题材语料采集调度入口（2026-10-23 v4 换源：事件层唯一权威源=开盘啦）。

    - `kpl`：开盘啦题材事件（InfoList+新事件详情）+ 题材新闻流（Kword 标签+ZSName 板块
      +新题正文补拉）+ 前瞻日历（`kpl_theme_collect`，日预算
      `KPL_THEME_DAILY_CALL_BUDGET`，默认 40，2026-11-02 正文预登记 §四）；
    - `jiuyan`：韭研产业树正文刷新（`jiuyan_theme_collect`，无 KPL 对应物，保留）。

    时点（snapshot_collector/scheduler 挂链）：盘前 08:45 事件层（kpl）；
    盘中 11:45 KPL 刷新（2026-11-02 用户裁决 B：当日新闻流尽早进语料）；
    收盘后 16:10 kpl 刷新 + 韭研产业树正文。门控 = 开关 → 交易日；
    各采集器互相独立，任一失败只降级该采集器（§4.0 fail-visible）。advisory 步。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "date": today}
    if not jiuyan_theme_collect_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled", "date": today}
    try:
        # 研究证据链用非抛错日历（bridge 宕机 → cache → 周内启发），不因 python-bridge 不在而丢一整天语料
        trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        return {"ok": False, "date": today,
                "error": {"code": "theme_gate_failed", "message": f"{type(exc).__name__}: {exc}"}}
    if not trading:
        return {"ok": True, "skipped": True, "reason": "non_trading_day", "date": today,
                "calendarSource": cal_source}

    results: dict[str, Any] = {}
    ok_all = True
    for collector in collectors:
        if collector == "kpl":
            cmd = [sys.executable, "-m", "backend.operations.kpl_theme_collect", "--date", today]
            timeout = _KPL_COLLECT_TIMEOUT_SECONDS
            parse_key = "kpl"
        elif collector == "jiuyan":
            cmd = [sys.executable, "-m", "backend.operations.jiuyan_theme_collect", "--date", today]
            timeout = _THEME_COLLECT_TIMEOUT_SECONDS
            parse_key = "jiuyan"
        else:
            results[collector] = {"ok": False, "error": {"code": "unknown_collector"}}
            ok_all = False
            continue
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parents[2]),
                # Windows 默认 GBK 解码会把中文输出读崩（实测 UnicodeDecodeError），显式 utf-8
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            results[parse_key] = {"ok": False,
                                  "error": {"code": "theme_collect_timeout",
                                            "message": f"timeout {timeout}s"}}
            ok_all = False
            continue
        if proc.returncode != 0:
            results[parse_key] = {"ok": False,
                                  "error": {"code": "theme_collect_failed",
                                            "message": (proc.stderr or proc.stdout or "")[-400:]}}
            ok_all = False
            continue
        # 结果 JSON 提取（2026-11-02 加固，与 theme_leader 同模式）：子进程以
        # THEME_COLLECT_RESULT_JSON: 标记行输出；兼容回退=倒序找首行可解析 dict。
        # 防「首个 { 截取」被未来含 { 的诊断行截中（theme_leader 10-29/10-30 结局
        # 漏回填的同类隐患，此处预防性关闭）。
        result = None
        parse_error = "result JSON line not found in stdout"
        for line in reversed((proc.stdout or "").splitlines()):
            cand = line.strip()
            if cand.startswith("THEME_COLLECT_RESULT_JSON:"):
                cand = cand[len("THEME_COLLECT_RESULT_JSON:"):].strip()
            if not cand.startswith("{"):
                continue
            try:
                result = json.loads(cand)
                break
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
                continue
        if result is None:
            results[parse_key] = {"ok": False,
                                  "error": {"code": "theme_collect_parse_failed",
                                            "message": parse_error}}
            ok_all = False
            continue
        results[parse_key] = {"ok": bool(result.get("ok")),
                              "degraded": result.get("degraded") or [],
                              "callsUsedToday": result.get("callsUsedTodayAfter")
                              or result.get("callsUsedToday"),
                              "skippedByBudget": result.get("skippedByBudget") or [],
                              "stats": result}
        ok_all = ok_all and bool(result.get("ok"))
    # V3-1 全成分周频守卫（16:10 交易日挂链；Popen 挂跑不阻塞本步）
    results["stock_tree_weekly"] = _maybe_launch_stocktree_weekly(today)
    return {"ok": ok_all, "date": today, "collectors": results}


def _run_jiuyan_label_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """个股驱动打标日增量（advisory 步，2026-10-03 用户裁决挂链）。

    - 门控与相位哨兵同源（当日 jiuyan final + 15:00 盘面帧）；
    - 子进程=jev_label_jiuyan --start/--end 当日（幂等：已 ok 标签自动跳过，用户裁决挂链）；
    - 2026-11-03 用户裁决：午盘只采名单不投喂不打标，本步=当日唯一投喂口；
      「单日每股只投喂一次」幂等判据保留，供历史 midday 档回填与手动重跑兼容。
    - 2026-11-13 用户裁决：final 投喂收窄为各板块龙一/二/三（dragon_rows 单源 top=3），
      跟风股不投喂（没参考价值且烧 token；≈21 万 tokens/交易日为收窄前全量历史口径）。
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（证据链积累，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)  # 同一原料门控
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    try:
        cmd = [sys.executable, "-m", "backend.operations.jev_label_jiuyan",
               "--start", today, "--end", today,
               # 批次C I13：预算护栏常态确认——本步挂链本身经 2026-10-03 用户裁决批准
               # （≈21万 tokens/日为收窄前全量历史口径；收窄后仅投喂板块龙一/二/三，2026-11-13 裁决）
               "--confirm-budget"]
        # F2 门控（融合总纲）：个股相位分线附带打标默认关，环境变量 JIUYAN_STOCK_PHASE_ENABLED=1
        # 且用户明确批准 token 成本后才可开启（≈3-5 万 tokens/日合并口径；开启前零额外调用）
        if os.environ.get("JIUYAN_STOCK_PHASE_ENABLED") == "1":
            cmd += ["--with-stock-phase"]
        proc = subprocess.run(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "jiuyan_label_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "jiuyan_label_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    labeled = None
    degraded = None
    verify_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        docs = list(db["hotlist_jev_driver_labels"].find(
            {"tradingDate": today, "origin": {"$ne": "phase_band_daily"}}, {"status": 1}))
        labeled = sum(1 for d in docs if d.get("status") == "ok")
        # 2026-10-05 批次A I5：降级面结构化回传，不再只留在子进程 stdout（fail-visible）
        degraded = len(docs) - labeled
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        verify_error = f"verify_failed: {exc}"
    result: dict[str, Any] = {"ok": True, "date": today,
                              "labeledToday": labeled, "degradedToday": degraded}
    if verify_error:
        result["verifyError"] = verify_error
    return result


def _run_relay_index_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """连板情绪指数日判定（advisory 步，2026-10-12 用户裁决挂链）。

    - 门控与 jiuyanLabel 同源（当日 jiuyan final + 15:00 盘面帧）；
    - 子进程=jev_relay_index --relay-day 当日（幂等：当日 RELAY 文档已 ok 自动跳过，七题一 call ≈5.5k tokens/日）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（叙事证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)  # 同一原料门控
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_relay_index", "--relay-day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_RELAY_INDEX_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "relay_index_timeout", "message": f"timeout {_RELAY_INDEX_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "relay_index_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    # 手动先跑/重复触发的日常场景：子进程幂等跳过（stdout「已判（…），跳过」）不重写文档，
    # computedAt 不刷新是预期行为，不报 mongoWarning（防天天误报）。
    # 匹配收窄到「已判」：缺料路径 stdout 也是「…跳过」（jev_relay_index「韭研 final 缺失，跳过」
    # 且 returncode 同为 0），宽匹配会把没判出伪装成良性跳过（review P1）
    idempotent_skip = "已判" in (proc.stdout or "")
    mongo_fresh = False
    relay = None
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["hotlist_jev_relay_index"].find_one(
            {"_id": f"{today}:RELAY"}, {"relayIndex": 1, "relayPhase": 1, "status": 1, "computedAt": 1})
        relay = {"index": doc.get("relayIndex"), "phase": doc.get("relayPhase"),
                 "status": doc.get("status")} if doc else None
        updated = str((doc or {}).get("computedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "date": today, "relay": relay, "mongoFresh": mongo_fresh}
    if idempotent_skip:
        result["idempotentSkip"] = True
    if not mongo_fresh and not idempotent_skip:
        result["mongoWarning"] = "RELAY 文档 computedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    if relay is not None and relay.get("status") not in ("ok", None):
        result["relayStatusWarning"] = f"RELAY 文档 status={relay.get('status')}（degraded 落库，advisory 不翻转）"
    if mongo_error:
        result["mongoWarning"] = f"mongo 校验异常（advisory 不翻转）：{mongo_error}"
    return result


_SECTOR_NODES_TIMEOUT_SECONDS = 300  # 板块节点：纯本地（韭研池×THS 二分×TDX 日线回溯），无模型调用


def _run_sector_nodes_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """板块节点日判定（advisory 步，2026-10-24 v1 挂链，预登记 sector-nodes-v1）。

    - 纯本地确定性判定（analysis/hotlist/sector_nodes 判据表，零 token）；
    - 门控与 relayIndex 同源（当日韭研 final + 15:00 盘面帧，_should_run_phase_band）；
    - v5.1 链序（2026-11-09 三链合一）：提前到 phasePulse/jiuyanLabel 之前——龙一只算
      一次落一次库，题材龙头打标/梯队表/下游 advisory 全部消费本档（昨日节点仍读昨日
      文档成链，升序回填天然满足）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_band(db, today)  # 同 relayIndex 原料门控
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.sector_nodes", "--day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_SECTOR_NODES_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "sector_nodes_timeout",
                                       "message": f"timeout {_SECTOR_NODES_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "sector_nodes_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    try:
        summary = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — 摘要解析失败不影响步成功（advisory）
        summary = {"ok": True, "parseWarning": "stdout 摘要不可解析"}
    return {"ok": True, "date": today, "summary": summary}


_LEADER_WZS_TIMEOUT_SECONDS = 900    # 龙头弱转强单日：TDX 覆盖式日线首拉数百 code，15min 冗余
_THEME_CYCLE_TIMEOUT_SECONDS = 600   # 状态机单日步进：重算龙一行（日线缓存大部分命中）


def _run_leader_wzs_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """龙头弱转强单日落库（advisory 步，P2 Q6:A 挂链，预登记 v5 P1）。

    - 纯本地确定性（观察池+①②事件流，零 token，hotlist_jev_leader_wzs）；
    - 链序在 jiuyanLabel 之后（当日 final + THS 池已落）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok；回填脚本可随时
      幂等补齐（--refresh）。"""
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
    if not trading:
        # 2026-11-07 实证：周六链跑本步产出 {tradingDate: 11-07, status: degraded} 残档
        # （非交易日无原料）；兄弟步均有当日原料数据门控，本步补齐交易日显式门控
        # （同 mongodbBackup 口径，记录 calendarSource）。
        return {"ok": True, "skipped": True, "reason": "non_trading_day", "date": today,
                "calendarSource": cal_source}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.leader_wzs", "--day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_LEADER_WZS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "leader_wzs_timeout",
                                       "message": f"timeout {_LEADER_WZS_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "leader_wzs_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    try:
        summary = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — 摘要解析失败不影响步成功（advisory）
        summary = {"ok": True, "parseWarning": "stdout 摘要不可解析"}
    return {"ok": True, "date": today, "summary": summary}


def _run_theme_cycle_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """题材周期状态机单日步进（advisory 步，P2 立项 v2 Q6:A 挂链）。

    - 链序硬约束：在 sectorNodes 之后（消费当日节点）且 leaderWzs 之后
      （消费当日 leaderRebound/benchmarkAdvance 事件）；
    - 纯本地确定性（零 token，hotlist_jev_theme_cycle，升序链读前一日库态）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok。"""
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.theme_cycle", "--day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_THEME_CYCLE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "theme_cycle_timeout",
                                       "message": f"timeout {_THEME_CYCLE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "theme_cycle_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    try:
        summary = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — 摘要解析失败不影响步成功（advisory）
        summary = {"ok": True, "parseWarning": "stdout 摘要不可解析"}
    return {"ok": True, "date": today, "summary": summary}


_MARKET_CYCLE_TIMEOUT_SECONDS = 600   # 事件流+状态机单日步进（TDX 日线缓存大部分命中）


def _run_market_cycle_step(today: str, dry_run: bool = False,
                           defer_reference: bool = False) -> dict[str, Any]:
    """市场情绪周期单日步进（advisory 步，第4课 P2 挂链）。

    - v8 解环（Option A）：确定性步在 relayIndex 之前（relay v8 叙事需当日 market_cycle 语料）；
      defer_reference=True 时 relay 参照留 None，relay 后由 _run_market_cycle_reference_step 补刷；
    - 纯本地确定性（零 token，hotlist_jev_market_cycle，事件流+状态机，读前一日库态）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok。"""
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.market_cycle", "--day", today]
            + (["--defer-reference"] if defer_reference else []),
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_MARKET_CYCLE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "market_cycle_timeout",
                                       "message": f"timeout {_MARKET_CYCLE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "market_cycle_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    try:
        summary = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — 摘要解析失败不影响步成功（advisory）
        summary = {"ok": True, "parseWarning": "stdout 摘要不可解析"}
    return {"ok": True, "date": today, "summary": summary}


def _run_market_cycle_reference_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """市场情绪周期 reference 补刷（v8 解环 Option A，advisory 步）。

    链序硬约束：在 relayIndex 之后——读当日 relay 档补 market_cycle 并列参照（事件/锚/态不动）。
    纯本地确定性（零 token）；失败/跳过不翻转 after-market 整体 ok。"""
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.market_cycle",
             "--day", today, "--refresh-reference"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_MARKET_CYCLE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "market_cycle_ref_timeout",
                                       "message": f"timeout {_MARKET_CYCLE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "market_cycle_ref_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    try:
        summary = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — 摘要解析失败不影响步成功（advisory）
        summary = {"ok": True, "parseWarning": "stdout 摘要不可解析"}
    return {"ok": True, "date": today, "summary": summary}


def _run_relay_band_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """分带表重算（advisory 步，2026-10-19 用户裁决 A+A1 挂链）。

    - 背景：分带表是页面常驻读数，生成长期靠人工手跑 → 序列前进、表停在旧日，滞后警告
      天天亮（2026-10-19 实证：序列已到 10-19、表止于 10-16）；本步把它从「人工动作」变成
      盘后链的一环（与 2026-10-12 relayIndex 挂链同因同法）。
    - 门控=**自愈式**：产物 `window.end` < 最新 ok 判定日才重算（产物缺失/损坏同样重算）——
      已覆盖当天则零成本跳过，advisory 步不空转 5–9 分钟。
    - 子进程=scripts/jev_relay_band_diagnostic.py --emit-json（**零模型调用**：只读 Mongo +
      本地通达信日线），产物写临时文件、成功退出后原子替换（刷新期间旧表完整可读）。
    - A1 产物策略：**全窗就地重建**，审计靠产物自带 generatedAt / relayGeneration / bars
      provenance + 本步结果（失败回退只靠 git / 产物重建，不建平行备份集合）。
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok、不参与 stopped_at（研究证据链）。
      门控查询失败也按 skipped 返回（与 11 个兄弟 advisory 步一致；且此时子进程读 Mongo 同样
      会失败，fail-open 只会白起一次进程——2026-10-19 评审 F1）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "date": today}
    from backend.services.jev.relay_band import (
        read_artifact_window_end,
        relay_band_table_path,
        run_band_refresh_sync,
    )

    table = relay_band_table_path()
    artifact_end = read_artifact_window_end(table)
    latest_judged: str | None = None
    gate_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        # 口径与脚本取数一致（scripts/jev_relay_band_diagnostic.py：status=ok 且 relayIndex 非空
        # 才算可判定日）；只看 status 会在「ok 但缺 relayIndex」的退化日上每晚白跑一次（评审 uncertain 2）
        latest_judged = max(
            (str(row.get("tradingDate"))
             for row in db["hotlist_jev_relay_index"].find(
                 {"status": "ok", "relayIndex": {"$ne": None}}, {"tradingDate": 1})
             if row.get("tradingDate")), default=None)
    except Exception as exc:  # noqa: BLE001 — 门控失败：与兄弟步一致按跳过处理（fail-visible 记原因）
        gate_error = f"gate error: {exc}"
    if gate_error is not None:
        return {"ok": True, "skipped": True, "reason": gate_error,
                "date": today, "artifactEnd": artifact_end}
    if latest_judged is None:
        return {"ok": True, "skipped": True, "reason": "no ok relay judgment",
                "date": today, "artifactEnd": artifact_end}
    if artifact_end and artifact_end >= latest_judged:
        return {"ok": True, "skipped": True,
                "reason": f"up_to_date ({artifact_end} >= {latest_judged})",
                "date": today, "artifactEnd": artifact_end, "latestJudged": latest_judged}

    result = run_band_refresh_sync(timeout=_RELAY_BAND_TIMEOUT_SECONDS)
    result["date"] = today
    result["latestJudged"] = latest_judged
    result["artifactEndBefore"] = artifact_end
    result["reason"] = ("artifact_missing_or_unreadable" if not artifact_end
                        else f"stale ({artifact_end} < {latest_judged})")
    return result


def _run_deep_valley_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """C9 深谷状态月度复验（advisory 步，2026-10-03 协议 §十四/M4 §8）。

    - 门控=当日 EOD 情绪文档存在（复用脉拍门控：deep_valley 读同一序列）；
    - 子进程=deep_valley_revalidate --month 当月 --apply（幂等 upsert phase_monitor c9:<month>，
      深谷日样本 + 3 日反弹 + 池代理随交易日自愈补全）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（C9 候选证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    month = today[:7]
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.deep_valley_revalidate",
             "--month", month, "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "deep_valley_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "deep_valley_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    summary: dict[str, Any] = {}
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["phase_monitor"].find_one({"_id": f"c9:{month}"}, {"summary": 1, "updatedAt": 1})
        updated = str((doc or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        summary = (doc or {}).get("summary") or {}
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "month": month, "summary": summary, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor c9:<month> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    if mongo_error:
        result["mongoWarning"] = f"mongo 校验异常（advisory 不翻转）：{mongo_error}"
    return result


def _run_calib_drift_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """校准漂移监控（advisory 步，2026-10-08 D 项，emotion-score-calib-monitor-design.md）。

    - 门控=当日 EOD 情绪文档存在（与脉拍同门控）；
    - 子进程=emotion_score_calib_monitor --date --apply（滚动窗口分位漂移 vs _CALIB 锚，
      |漂移|>10 告警落库 phase_monitor calib_drift:<month>；只探测不重写评分口径）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（校准健康监控，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.emotion_score_calib_monitor",
             "--date", today, "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "calib_drift_timeout", "message": "timeout 300s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "calib_drift_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    alert_count = None
    mongo_warning: str | None = None
    month = today[:7]
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["phase_monitor"].find_one({"_id": f"calib_drift:{month}"},
                                            {"updatedAt": 1, "report.alerts": 1})
        updated = str((doc or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        alert_count = len((((doc or {}).get("report") or {}).get("alerts")) or [])
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态，异常串入 mongoWarning（对齐兄弟步）
        mongo_warning = f"phase_monitor calib_drift:{month} updatedAt 校验失败: {exc}"
    result: dict[str, Any] = {"ok": True, "date": today, "month": month,
                              "alertCount": alert_count, "mongoFresh": mongo_fresh}
    if mongo_warning:
        result["mongoWarning"] = mongo_warning
    elif not mongo_fresh:
        result["mongoWarning"] = "phase_monitor calib_drift:<month> updatedAt 未刷新（advisory 不翻转）"
    return result


def _run_amount_vs_same_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """两市额同期比 vsSamePct 只记录不评分（advisory 步，2026-10-06 评估报告建议 2 落地）。

    - 门控=当日 EOD 情绪文档存在（与 deepValley 同门控：非交易日/无 EOD 则跳过）；
    - 子进程=record_amount_vs_same --apply（TDX 增量同步 market_daily_amount + 全量幂等重算
      vsSamePct/设计曲线 sub——**只存不评分**，供第八评分维 ≥20 交易日分布校准）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（校准数据积累，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.record_amount_vs_same", "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "amount_vs_same_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "amount_vs_same_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    tail = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        record = json.loads(tail[0].removeprefix("[record] "))
    except Exception:  # noqa: BLE001 — 摘要解析失败不回滚已写数据
        record = {"raw": tail[0][:200]}
    return {"ok": True, "record": record}


_ZHABAN_LABEL_TIMEOUT_SECONDS = 1200  # 炸板归因：当日炸板池逐股一 call（串行），池峰值 ~40 只冗余
_INDUSTRY_ALIAS_TIMEOUT_SECONDS = 120  # 桥重建：纯本地词表×108 产业 suggest，秒级，120s 冗余


def _run_zhaban_label_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """炸板股归因打标（2026-10-13 用户裁决挂链：relay 叙事炸板归因缺口补全，对连板情绪判定关键）。

    - 门控=当日 half_hour 15:00 帧已落库（THS 炸板池来源；帧未落库/非交易日 → skipped，零成本；
      THS 池缺失日 runner 自身 fail-visible 整日跳过，双保险）；
    - 子进程=jev_zhaban_label --zhaban-day 当日（炸板池逐股单题；幂等 status=ok 跳过，重跑零重复计费）；
    - **advisory 语义**：失败/跳过不翻转 after_market 整体 ok、不参与 stopped_at
      （jev=并列观察者，观察证据链非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    try:
        db = repository_factory.get_runtime_mongodb_database()
        frame = db["snapshot_frames"].find_one(
            {"datasetId": dataset_id, "type": "half_hour",
             "tradingDate": today, "slotTime": "15:00"}, {"snapshotId": 1})
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        return {"ok": True, "skipped": True, "reason": f"gate error: {exc}"}
    if not frame:
        return {"ok": True, "skipped": True, "reason": "15:00 frame missing (非交易日/采集延迟)"}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_zhaban_label",
             "--zhaban-day", today],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_ZHABAN_LABEL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "zhaban_label_timeout", "message": f"timeout {_ZHABAN_LABEL_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "zhaban_label_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    return {"ok": True, "runStartedAt": run_started_at.isoformat(),
            "stdoutTail": (proc.stdout or "")[-300:]}


def _run_industry_alias_bridge_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """jiuyan↔KPL 板块名称桥日终重建（advisory 步，2026-11-14 用户裁决实施治理闭环）。

    - 子进程=industry_alias --rebuild-daban：themes 名录 ∪ 打板页题材词表
      （auction_trial_raw 全日档 bk_name）幂等重建 auto 映射（manual 行不动，
      纯本地零上游零模型调用）；unmapped 清单 stdout 披露（人工裁决候选）；
    - 门控=交易日（非交易日跳过，零成本）；
    - **advisory 语义**：失败/跳过不翻转 after_market 整体 ok、不参与 stopped_at
      （消费方=竞价试盘页等展示层归属兑底，非生产数据链；读口另有实时 suggest
      兜底，桥重建滞后天级不影响当日展示）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        trading, _cal = is_trading_day_cached(datetime.now(_TZ).date())
    except Exception as exc:  # noqa: BLE001 — 门控失败按跳过处理（fail-visible）
        return {"ok": True, "skipped": True, "reason": f"gate error: {exc}"}
    if not trading:
        return {"ok": True, "skipped": True, "reason": "non_trading_day"}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.services.theme.industry_alias",
             "--rebuild-daban"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_INDUSTRY_ALIAS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "industry_alias_timeout",
                                       "message": f"timeout {_INDUSTRY_ALIAS_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "industry_alias_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    tail = (proc.stdout or "")[-300:]
    mapped = unmapped_n = None
    try:
        import json as _json
        summary = _json.loads(proc.stdout or "{}")
        mapped = summary.get("mapped")
        unmapped_n = len(summary.get("unmapped") or [])
    except Exception:
        pass
    return {"ok": True, "runStartedAt": run_started_at.isoformat(),
            "mapped": mapped, "unmapped": unmapped_n, "stdoutTail": tail}


def _run_jiuyan_root_bridge_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """产业树一级→粗桶对照层日终重建（advisory 步，2026-11-14 用户裁决实施）。

    - 子进程=jiuyan_industry_root --rebuild-root：成分股历史打标链归属投票
      （近 60 日，票按同义主名合并）幂等重建 auto_vote 行（Top1 占比≥0.40，
      manual 不动，低置信回退+unmapped 披露）；纯本地零上游零模型调用；
    - 门控=交易日；**advisory 语义**同 alias 步（消费方=竞价试盘页展示层，
      滞后天级由 level-1 原值兑底，不阻断）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    try:
        trading, _cal = is_trading_day_cached(datetime.now(_TZ).date())
    except Exception as exc:  # noqa: BLE001 — 门控失败按跳过处理（fail-visible）
        return {"ok": True, "skipped": True, "reason": f"gate error: {exc}"}
    if not trading:
        return {"ok": True, "skipped": True, "reason": "non_trading_day"}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.services.jev.jiuyan_industry_root",
             "--rebuild-root"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_INDUSTRY_ALIAS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "jiuyan_root_timeout",
                                       "message": f"timeout {_INDUSTRY_ALIAS_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "jiuyan_root_failed",
                                       "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mapped = unmapped_n = None
    try:
        import json as _json
        summary = _json.loads(proc.stdout or "{}")
        mapped = len(summary.get("added") or []) + len(summary.get("changed") or [])
        unmapped_n = len(summary.get("unmapped") or [])
    except Exception:
        pass
    return {"ok": True, "runStartedAt": run_started_at.isoformat(),
            "mapped": mapped, "unmapped": unmapped_n,
            "stdoutTail": (proc.stdout or "")[-300:]}


def _run_jev_daily_line_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """日度情绪一句话（advisory 步，2026-10-08 预登记 jev-daily-line-design.md）。

    - 门控=当日 EOD 情绪文档存在（与脉拍同门控：非交易日/无 EOD 则跳过）；
    - 子进程=jev_daily_line --date --apply（单次 jev choice 调用；失败/缺 token → 规则兑底不阻断，
      句子仍落库；设计见文档，模板措辞由版本化模板控制，jev 只归层不写句）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（前端展示增强链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001 — 门控查询失败按跳过处理（fail-visible 记原因）
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_daily_line", "--date", today, "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_JEV_DAILY_LINE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "jev_daily_line_timeout", "message": f"timeout {_JEV_DAILY_LINE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "jev_daily_line_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    sentence: str | None = None
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["phase_monitor"].find_one({"_id": f"line:{today}"}, {"updatedAt": 1, "report.sentence": 1})
        updated = str((doc or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        sentence = ((doc or {}).get("report") or {}).get("sentence")
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "date": today, "sentence": sentence, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor line:<date> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    if mongo_error:
        result["mongoWarning"] = f"mongo 校验异常（advisory 不翻转）：{mongo_error}"
    return result


def _run_peak_revalidate_step(today: str, dry_run: bool = False) -> dict[str, Any]:
    """C10 高峰兑现月度复验（advisory 步，2026-10-04 立项，镜像 deepValley 步）。

    - 门控=当日 EOD 情绪文档存在（与 deepValley 同源门控）；
    - 子进程=peak_revalidate --month 当月 --apply（幂等 upsert phase_monitor c10:<month>，
      高峰日 ≥75 涨停池缺口分组读数随交易日自愈补全；方案=ranktrend-c10-peak-exit-plan.md）；
    - **advisory 语义**：失败/跳过不翻转 after-market 整体 ok（C10 候选证据链，非生产数据链）。
    """
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run"}
    settings = get_settings()
    dataset_id = settings.archive_auto_dataset_id
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    try:
        db = repository_factory.get_runtime_mongodb_database()
        should, reason = _should_run_phase_pulse(db, today, dataset_id, snapshot_type)
    except Exception as exc:  # noqa: BLE001
        should, reason = False, f"gate error: {exc}"
    if not should:
        return {"ok": True, "skipped": True, "reason": reason}
    month = today[:7]
    run_started_at = datetime.now(_TZ)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.peak_revalidate",
             "--month", month, "--apply"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, timeout=_PULSE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": {"code": "peak_revalidate_timeout", "message": f"timeout {_PULSE_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "error": {"code": "peak_revalidate_failed", "message": (proc.stderr or proc.stdout or "")[-400:]}}
    mongo_fresh = False
    summary: dict[str, Any] = {}
    mongo_error: str | None = None
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["phase_monitor"].find_one({"_id": f"c10:{month}"}, {"summary": 1, "updatedAt": 1})
        updated = str((doc or {}).get("updatedAt") or "")
        mongo_fresh = bool(updated) and updated >= run_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        summary = (doc or {}).get("summary") or {}
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        mongo_error = str(exc)
    result: dict[str, Any] = {"ok": True, "month": month, "summary": summary, "mongoFresh": mongo_fresh}
    if not mongo_fresh:
        result["mongoWarning"] = "phase_monitor c10:<month> updatedAt 未刷新（mongo 入库校验失败，advisory 不翻转）"
    if mongo_error:
        result["mongoWarning"] = f"mongo 校验异常（advisory 不翻转）：{mongo_error}"
    return result


def run_mongodb_snapshot_archive_once(*, dry_run: bool = False) -> dict[str, Any]:
    """盘后快照日归档到 R2（mongodb 后端，2026-09-28）。

    按 ``archive_auto_snapshot_types`` 逐类型归档**最近已收盘交易日**（严格早于
    今日）：当日 15:30 任务触发时 daily:15:30 槽可能仍在采集，归档当日会把
    不完整帧固化进 manifest 并被幂等去重永久跳过；归档 T-1 无此竞态。
    每类型独立成败（fail-visible）：单类型失败不阻断其它类型，整体 ok 汇总。
    Mongo 保留不动（归档只进 R2，见 ArchiveService.backup_mongodb_snapshot_day_to_object）。
    """
    from backend.data.archive.service import ArchiveService

    settings = get_settings()
    snapshot_types = [item.strip() for item in settings.archive_auto_snapshot_types.split(",") if item.strip()]
    today = datetime.now(_TZ).strftime("%Y-%m-%d")
    db = repository_factory.get_runtime_mongodb_database()
    per_type: dict[str, Any] = {}
    ok = True
    service = ArchiveService(db)
    for snapshot_type in snapshot_types:
        try:
            latest_date = db["snapshot_frames"].find_one(
                {"datasetId": settings.archive_auto_dataset_id, "type": snapshot_type, "tradingDate": {"$lt": today}},
                sort=[("tradingDate", -1)],
                projection={"tradingDate": 1, "_id": 0},
            )
            trading_date = str((latest_date or {}).get("tradingDate") or "")
            if not trading_date:
                per_type[snapshot_type] = {"ok": True, "skipped": True, "reason": "no_snapshot_frames"}
                continue
            result = service.backup_mongodb_snapshot_day_to_object(
                db,
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                dry_run=dry_run,
            )
            per_type[snapshot_type] = {**result, "tradingDate": trading_date}
            skipped_reason = str(result.get("reason") or "")
            if not result.get("ok") and skipped_reason not in ("already_archived",):
                ok = False
        except Exception as exc:
            per_type[snapshot_type] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            ok = False
    return {
        "ok": ok,
        "dryRun": dry_run,
        "datasetId": settings.archive_auto_dataset_id,
        "snapshotTypes": per_type,
        "archivedBefore": today,
    }


def run_after_market_once(
    *,
    archive_limit: int | None = None,
    backup_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, Any] = {}

    settings = get_settings()
    if settings.storage_backend == "mongodb":
        # 盘后链预检（2026-11-04 用户裁决）：jiuyan 名单数与落库一致才往下跑；不一致先
        # 幂等重采补齐，补齐仍失败 → 拦停（stoppedAt=jiuyanPreflight），不烧不完整投喂。
        # pytest 环境跳过（§1.2-7 测试禁真调用：预检会真调 auth/浏览器铸造；
        # run_jiuyan_preflight 自身单测走全 monkeypatch，不受此守卫影响）。
        if not dry_run and not os.environ.get("PYTEST_CURRENT_TEST"):
            preflight = run_jiuyan_preflight(datetime.now(_TZ).strftime("%Y-%m-%d"))
            results["jiuyanPreflight"] = preflight
            if not preflight.get("ok"):
                return {"ok": False, "stoppedAt": "jiuyanPreflight",
                        "results": results,
                        "startedAt": started_at,
                        "finishedAt": datetime.now(timezone.utc).isoformat()}
        snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
        try:
            hotlist_result = run_hotlist_sentiment_for_latest_day(
                repository_factory.get_runtime_mongodb_database(),
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                dry_run=dry_run,
            )
        except Exception as exc:
            hotlist_result = {
                "ok": False,
                "error": {
                    "code": "hotlist_sentiment_after_market_failed",
                    "message": str(exc),
                },
                "datasetId": settings.archive_auto_dataset_id,
                "snapshotType": snapshot_type,
            }
        # 备份链独立于 hotlistSentiment 结果：hotlist 失败也继续备份（快照数据可能已入库）
        backup_result = run_mongodb_backup_once(dry_run=dry_run)
        # R2 快照归档链独立于备份链：备份失败也尝试归档（两条链互不覆盖，各自 fail-visible）
        archive_result = run_mongodb_snapshot_archive_once(dry_run=dry_run)
        hotlist_ok = bool(hotlist_result.get("ok"))
        backup_ok = bool(backup_result.get("ok"))
        archive_ok = bool(archive_result.get("ok"))
        stopped_at = None
        if not hotlist_ok:
            stopped_at = "hotlistSentiment"
        elif not backup_ok:
            stopped_at = "mongodbBackup"
        elif not archive_ok:
            stopped_at = "snapshotArchiveR2"
        today = datetime.now(_TZ).strftime("%Y-%m-%d")
        # ★ 龙一单源（2026-11-09 用户裁决三链合一 v5.1）：sectorNodes 从 relayIndex 后
        # 提前到打标前——龙一只算一次落一次库（空间龙一 main 轨折叠+事实字段扩容），
        # 下游题材龙头打标（17:30 scheduler）/涨停打标叙事/梯队表/leaderWzs/themeCycle/
        # sectorPulse 全部消费本档，不再各自重推（漂移由 leaders_for 过滤+披露兜底）。
        sector_nodes_result = _run_sector_nodes_step(today, dry_run=dry_run)
        # 盘面脉拍（M3 advisory 步）：EOD 刷新后数据齐，子进程隔离跑当月至今相位快照；
        # 失败/跳过只记结果不翻转整体 ok，也不参与 stopped_at（研究证据链，非生产数据链）
        pulse_result = _run_phase_pulse_step(today, dry_run=dry_run)
        jiuyan_label_result = _run_jiuyan_label_step(today, dry_run=dry_run)
        # 链序硬约束：zhabanLabel 必须先于 relayIndex——relay 叙事「今日炸板面」段消费
        # 当日炸板归因打标（hotlist_jev_zhaban_labels status=ok），反序则当日归因永远赶不上
        # 叙事组装（2026-10-14/10-15 实证：relay 16:18-16:27 出数、归因 16:20-16:36 才落库，
        # 叙事恒写「未覆盖（0/N，归因证据缺失）」，zhabanLabel 步的补全目的被顺序抵消）。
        zhaban_label_result = _run_zhaban_label_step(today, dry_run=dry_run)
        # 市场情绪周期·确定性步（v8 解环 Option A）：在 relayIndex 之前——relay v8 叙事需当日
        # market_cycle 语料；reference 暂缺（defer），relay 后补刷。纯确定性零 token。
        market_cycle_result = _run_market_cycle_step(today, dry_run=dry_run, defer_reference=True)
        relay_index_result = _run_relay_index_step(today, dry_run=dry_run)
        # 市场情绪周期·reference 补刷（v8 解环）：relay 落库后读当日 relay 档补并列参照
        market_cycle_ref_result = _run_market_cycle_reference_step(today, dry_run=dry_run)
        # 龙头弱转强（advisory，P2 Q6:A）：观察池+①②事件流单日落库（零 token）
        leader_wzs_result = _run_leader_wzs_step(today, dry_run=dry_run)
        # 题材周期状态机（advisory，P2）：链序在 sectorNodes/leaderWzs 之后
        theme_cycle_result = _run_theme_cycle_step(today, dry_run=dry_run)
        # 分带表重算（advisory）：链序在 relayIndex 之后——门控比对「最新 ok 判定日」与
        # 产物 window.end，当日新判定刚落库时自愈补齐（零模型调用，产物原子替换）
        relay_band_result = _run_relay_band_step(today, dry_run=dry_run)
        phase_band_result = _run_phase_band_step(today, dry_run=dry_run)
        deep_valley_result = _run_deep_valley_step(today, dry_run=dry_run)
        peak_revalidate_result = _run_peak_revalidate_step(today, dry_run=dry_run)
        jev_daily_line_result = _run_jev_daily_line_step(today, dry_run=dry_run)
        calib_drift_result = _run_calib_drift_step(today, dry_run=dry_run)
        amount_vs_same_result = _run_amount_vs_same_step(today, dry_run=dry_run)
        # jiuyan↔KPL 板块名称桥日终重建（advisory，2026-11-14 治理闭环；映射消费
        # =竞价试盘页等展示层，滞后天级由读口实时 suggest 兑底）
        industry_alias_result = _run_industry_alias_bridge_step(today, dry_run=dry_run)
        # 产业树一级→粗桶对照层日终重建（advisory，同日实施；投票按同义主名合并）
        jiuyan_root_result = _run_jiuyan_root_bridge_step(today, dry_run=dry_run)
        return _result(
            ok=hotlist_ok and backup_ok and archive_ok,
            started_at=started_at,
            steps=["hotlistSentiment", "mongodbBackup", "snapshotArchiveR2", "sectorNodes", "phasePulse", "jiuyanLabel", "zhabanLabel", "marketCycle", "relayIndex", "marketCycleRef", "leaderWzs", "themeCycle", "relayBand", "phaseBand", "deepValley", "peakRevalidate", "jevDailyLine", "calibDriftMonitor", "amountVsSameRecord", "industryAliasBridge", "jiuyanRootBridge"],
            results={
                "hotlistSentiment": hotlist_result,
                "mongodbBackup": backup_result,
                "snapshotArchiveR2": archive_result,
                "phasePulse": pulse_result,
                "jiuyanLabel": jiuyan_label_result,
                "zhabanLabel": zhaban_label_result,
                "relayIndex": relay_index_result,
                "sectorNodes": sector_nodes_result,
                "leaderWzs": leader_wzs_result,
                "themeCycle": theme_cycle_result,
                "marketCycle": market_cycle_result,
                "marketCycleRef": market_cycle_ref_result,
                "relayBand": relay_band_result,
                "phaseBand": phase_band_result,
                "deepValley": deep_valley_result,
                "peakRevalidate": peak_revalidate_result,
                "jevDailyLine": jev_daily_line_result,
                "calibDriftMonitor": calib_drift_result,
                "amountVsSameRecord": amount_vs_same_result,
                "industryAliasBridge": industry_alias_result,
                "jiuyanRootBridge": jiuyan_root_result,
            },
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at=stopped_at,
        )

def run_mongodb_backup_once(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """盘后 MongoDB 备份链：创建（交易日 light / 周五 full）→ verify → prune →（周五）push R2。

    独立于 hotlistSentiment：任一步失败结构化记录并使整体失败（非零退出可见），
    但不回滚其它步骤已完成的事实。
    """
    now = now or datetime.now(_TZ)
    is_friday = now.weekday() == 4
    summary: dict[str, Any] = {"ok": True, "friday": is_friday, "tradingDate": now.date().isoformat()}
    if dry_run:
        return {**summary, "skipped": True, "reason": "dry_run"}
    trading, cal_source = is_trading_day_cached(now.date())
    if not trading:
        # 2026-10-23 加固：bridge 日历不可用时（tdx.com.cn 掐 TLS 握手致 /api/calendar 503），
        # raising 版 is_trading_day 在本步 try 外裸抛 TradingCalendarUnavailable，
        # 盘后任务整体退出码 1 且不落任何日志/备份（fail-visible 缺口）。
        # 改用 cached 版降级（bridge → 本地缓存 → 工作日启发），并记录判定来源可追溯。
        return {**summary, "skipped": True, "reason": "non_trading_day", "calendarSource": cal_source}

    service = get_mongodb_backup_service()
    strategy = "full_dump" if is_friday else "light_dump"
    if not is_friday:
        strategy, catch_up = _maybe_force_full_catch_up(service, now)
        summary["lastFullBackup"] = catch_up
    summary["strategy"] = strategy
    try:
        created = service.create_full_backup() if strategy == "full_dump" else service.create_light_backup()
    except Exception as exc:
        return {**summary, "ok": False, "failedStep": "create", "error": {"code": "backup_create_exception", "message": str(exc)}}
    if not created.get("ok"):
        return {**summary, "ok": False, "failedStep": "create", "error": created.get("error")}
    backup_id = created["backupId"]
    summary["backupId"] = backup_id

    verify = service.verify_backup(backup_id)
    if not verify.get("ok"):
        return {**summary, "ok": False, "failedStep": "verify", "error": verify.get("error")}

    prune = service.prune_local_backups(dry_run=False)
    summary["pruneDeleted"] = len(prune.get("deleted") or [])
    if not prune.get("ok"):
        return {**summary, "ok": False, "failedStep": "prune", "error": prune.get("error")}

    if strategy == "full_dump":
        # 周五全量与断档补跑全量都立即上云（push 失败使整体失败可见）
        try:
            pushed = service.push_backup(backup_id)
        except Exception as exc:
            pushed = {"ok": False, "error": {"code": "backup_push_exception", "message": str(exc)}}
        summary["push"] = {
            "ok": bool(pushed.get("ok")),
            "fileCount": len(pushed.get("files") or []),
            **({} if pushed.get("ok") else {"error": pushed.get("error")}),
        }
        if not pushed.get("ok"):
            return {**summary, "ok": False, "failedStep": "push"}
    return summary


def _result(
    *,
    ok: bool,
    started_at: str,
    steps: list[str],
    results: dict[str, Any],
    archive_limit: int | None,
    backup_limit: int | None,
    dry_run: bool,
    stopped_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "dryRun": dry_run,
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "archiveLimit": archive_limit,
        "backupLimit": backup_limit,
        "steps": steps,
        "results": results,
    }
    if stopped_at:
        payload["stoppedAt"] = stopped_at
    return payload


def _maybe_force_full_catch_up(service: Any, now: datetime) -> tuple[str, dict[str, Any]]:
    """非周五交易日检查最近全量：距上次成功 full 超过 8 天则强制补 full。

    背景：周五停机错过全量时，周末补跑因非交易日跳过、当周只剩 light，
    R2 侧全量断档一整周。远端 R2 是唯一完整视图（本地 light 保留期短于
    全量周间隔）；未配置 R2 时无法可靠判断，保持 light 并结构化记录原因。
    返回 (strategy, lastFullBackup 摘要)。
    """
    info: dict[str, Any] | None = None
    try:
        info = service.latest_full_backup_info()
    except Exception as exc:
        return "light_dump", {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if info and info.get("createdAt"):
        created = info["createdAt"]
        age_days = (now.astimezone(timezone.utc) - created).total_seconds() / 86400.0
        detail = {
            "ok": True,
            "backupId": info.get("backupId"),
            "source": info.get("source"),
            "createdAt": created.isoformat(),
            "ageDays": round(age_days, 2),
        }
        if age_days >= 8:
            detail["fullCatchUp"] = {"reason": "last_full_older_than_8_days"}
            return "full_dump", detail
        return "light_dump", detail
    if getattr(service, "object_store", None) is not None:
        # 配置了 R2 却查不到任何全量：尚未有上云全量，补一次
        return "full_dump", {"ok": True, "fullCatchUp": {"reason": "no_full_backup_found"}}
    return "light_dump", {"ok": True, "skipped": True, "reason": "full_history_unavailable_without_object_store"}


def _first_snapshot_type(raw: str) -> str:
    items = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return items[0] if items else "half_hour"