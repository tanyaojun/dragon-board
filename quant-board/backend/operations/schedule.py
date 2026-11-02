from __future__ import annotations

import json
import os
import subprocess
import sys
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
_JEV_DAILY_LINE_TIMEOUT_SECONDS = 600  # 日度一句话：单次 jev 调用（client 内部 60s）+ 规则/落库，600s 冗余
_RELAY_INDEX_TIMEOUT_SECONDS = 600  # 连板指数：单次 jev 调用（七题一 call，实测 <1s）+ 原料拼装/落库，600s 冗余
# 午盘投喂（12:30）：单日 ≈65 只串行 2 workers，实测 3-6 分钟；留 30 分钟给 TDX/网络拖尾
_MIDDAY_LABEL_TIMEOUT_SECONDS = 1800
# 480s 覆盖最坏情况：每源 = 间隔 20s + HTTP 20s + 退避 60s + 重试间隔 20s + HTTP 20s = 140s，
# 3 源 = 420s（2026-10-20 review P1：原 300s 核算漏了重试迭代内的间隔，限流日会撞穿），
# +60s 落库/拼装冗余。逐段先落库（jiuyan_theme_collect），超时被杀只丢未抓的源。
# 实测 errCode=9 是短时限流，退避太短等于白打；见 theme-leader-nextday-preregistration §5.3
_THEME_COLLECT_TIMEOUT_SECONDS = 480
# KPL 采集子进程超时（最坏 11 调用 × (3s 间隔+请求) + 1 次退避 20s ≈ 80s，留 3 倍余量）
_KPL_COLLECT_TIMEOUT_SECONDS = 240
# 龙头级投喂（每日 1 call/龙头，实测 13 只 13 次调用 <2s/次 + 基线/取数）：1800s 冗余
_THEME_LEADER_TIMEOUT_SECONDS = 1800
_THEME_LEADER_SETTLE_TIMEOUT_SECONDS = 300   # 结局回填：纯读库+写字段
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


def jiuyan_midday_label_enabled() -> bool:
    """午盘投喂开关（2026-10-20 用户裁决挂链；默认开，`JIUYAN_MIDDAY_LABEL_ENABLED=0` 可关）。"""
    return os.environ.get("JIUYAN_MIDDAY_LABEL_ENABLED", "1") != "0"


def run_jiuyan_midday_label_once(today: str | None = None, *,
                                 dry_run: bool = False) -> dict[str, Any]:
    """午盘涨停打标（12:30 调度，2026-10-20 用户裁决）：午盘名单投喂 jev，收盘不重复投喂。

    门控：开关（`JIUYAN_MIDDAY_LABEL_ENABLED`）→ 交易日 → `{date}:midday` 存在且 `fetchedAt`
    落在午盘窗（`midday_source_state`）。最后一道是防「伪午盘」：实测 2026-10-14/16/19 采集
    进程在收盘后才启动，当日的 midday 文档是用收盘数据补写的（fetchedAt 15:20/20:04/20:23），
    拿它做午盘投喂等于把收盘数据冒充午盘证据 → 一律拒绝，交收盘链投喂。

    子进程=`jev_label_jiuyan --slot midday --confirm-budget`：
    - 幂等=当日已 status=ok 的个股自动跳过 → 16:00 收盘链不会重复投喂同一只股票；
    - advisory 语义：失败/跳过不翻转调用方整体 ok（研判证据链，非生产数据链）。
    """
    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    if dry_run:
        return {"ok": True, "skipped": True, "reason": "dry_run", "date": today}
    if not jiuyan_midday_label_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled", "date": today}
    try:
        # 非抛错日历：python-bridge 宕机时降级为 cache/周内启发，不把「桥不可用」变成「今天不投喂」
        trading, cal_source = is_trading_day_cached(datetime.strptime(today, "%Y-%m-%d").date())
        if not trading:
            return {"ok": True, "skipped": True, "reason": "non_trading_day", "date": today,
                    "calendarSource": cal_source}
        db = repository_factory.get_runtime_mongodb_database()
        from backend.operations.jev_label_jiuyan import midday_source_state
        state = midday_source_state(db, today)
    except Exception as exc:  # noqa: BLE001 — advisory 步，失败结构化返回
        return {"ok": False, "date": today,
                "error": {"code": "midday_gate_failed", "message": f"{type(exc).__name__}: {exc}"}}
    if not state["ok"]:
        return {"ok": True, "skipped": True, "date": today, "reason": state["reason"],
                "detail": state["detail"], "fetchedAt": state["fetchedAt"]}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "backend.operations.jev_label_jiuyan",
             "--start", today, "--end", today, "--slot", "midday",
             # 挂链常态预算批准（2026-10-20 用户裁决：午盘投喂 ≈65 只/日）
             "--confirm-budget"],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_MIDDAY_LABEL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "date": today,
                "error": {"code": "midday_label_timeout",
                          "message": f"timeout {_MIDDAY_LABEL_TIMEOUT_SECONDS}s"}}
    if proc.returncode != 0:
        return {"ok": False, "date": today,
                "error": {"code": "midday_label_failed",
                          "message": (proc.stderr or proc.stdout or "")[-400:]}}
    labeled = degraded = None
    verify_error: str | None = None
    try:
        docs = list(db["hotlist_jev_driver_labels"].find(
            {"tradingDate": today, "labelSlot": "midday",
             "origin": {"$ne": "phase_band_daily"}}, {"status": 1}))
        labeled = sum(1 for d in docs if d.get("status") == "ok")
        degraded = len(docs) - labeled
    except Exception as exc:  # noqa: BLE001 — advisory 步不翻转整体状态
        verify_error = f"verify_failed: {exc}"
    result: dict[str, Any] = {"ok": True, "date": today, "labeledMidday": labeled,
                              "degradedMidday": degraded, "sourceFetchedAt": state["fetchedAt"]}
    if verify_error:
        result["verifyError"] = verify_error
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


def run_theme_leader_label_once(today: str | None = None, *,
                                dry_run: bool = False) -> dict[str, Any]:
    """题材层「板块龙头隔日连板」投喂（17:30 调度，2026-10-20 挂链；
    2026-10-30 用户裁决改时）。

    与个股驱动链的关系：完全独立集合（`hotlist_jev_theme_leader_labels`）、独立题集代际，
    每条 = 一个**板块龙头**（不是每只涨停股），**1 call/龙头/日**（≈13–20 次/日，
    实测 2026-10-19：13 次真调用 29,014 tokens）。

    门控：开关（`THEME_LEADER_LABEL_ENABLED`）→ 交易日（非抛错日历：bridge 宕机不丢一天）→
    子进程自身幂等（`_id={date}:{code}` 已 `status=ok` 跳过，重跑不重复烧 token）。
    时点 17:30：晚于 16:10 的题材语料刷新（当日晚于收盘的催化正文先进库）与 15:35 收盘名单；
    晚于龙虎榜榜生成（约 17:00 盘后），当日龙虎榜事实行（AMMO 2026-10-30a）当日可得。

    预算语义（§1.2-7）：本步属**预登记日包络**下的常态挂链（用户已批准 ≈29k tokens/交易日），
    故直接带 `--confirm-budget`；无包络的路必须走 CLI 人工批准。

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
    try:
        result = json.loads(proc.stdout[proc.stdout.index("{"):])
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "date": today,
                "error": {"code": "theme_leader_parse_failed", "message": str(exc)}}
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


def run_theme_corpus_collect_once(today: str | None = None, *,
                                  dry_run: bool = False,
                                  collectors: tuple[str, ...] = ("kpl", "jiuyan")) -> dict[str, Any]:
    """题材语料采集调度入口（2026-10-23 v4 换源：事件层唯一权威源=开盘啦）。

    - `kpl`：开盘啦题材事件（InfoList+新事件详情）+ 题材新闻流（Kword 标签）+ 前瞻日历
      （`kpl_theme_collect`，日预算 `KPL_THEME_DAILY_CALL_BUDGET`，默认 20）；
    - `jiuyan`：韭研产业树正文刷新（`jiuyan_theme_collect`，无 KPL 对应物，保留）。

    时点（snapshot_collector/scheduler 挂链）：盘前 08:45 事件层（kpl）；
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
        try:
            result = json.loads(proc.stdout[proc.stdout.index("{"):])
        except (ValueError, json.JSONDecodeError) as exc:
            results[parse_key] = {"ok": False,
                                  "error": {"code": "theme_collect_parse_failed", "message": str(exc)}}
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
    - 子进程=jev_label_jiuyan --start/--end 当日（幂等：已 ok 标签自动跳过，≈21 万 tokens/交易日，用户裁决挂链）；
    - 午盘已投喂的个股（labelSlot=midday，2026-10-20 起）在本步**幂等跳过**：单日每股只投喂一次。
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
               # 批次C I13：预算护栏常态确认——本步挂链本身经 2026-10-03 用户裁决批准（≈21万 tokens/日）
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
    - 链序在 relayIndex 之后：昨日节点从昨日文档读，升序成链（盘后链逐日自然满足）；
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
        # 盘面脉拍（M3 advisory 步）：EOD 刷新后数据齐，子进程隔离跑当月至今相位快照；
        # 失败/跳过只记结果不翻转整体 ok，也不参与 stopped_at（研究证据链，非生产数据链）
        today = datetime.now(_TZ).strftime("%Y-%m-%d")
        pulse_result = _run_phase_pulse_step(today, dry_run=dry_run)
        jiuyan_label_result = _run_jiuyan_label_step(today, dry_run=dry_run)
        # 链序硬约束：zhabanLabel 必须先于 relayIndex——relay 叙事「今日炸板面」段消费
        # 当日炸板归因打标（hotlist_jev_zhaban_labels status=ok），反序则当日归因永远赶不上
        # 叙事组装（2026-10-14/10-15 实证：relay 16:18-16:27 出数、归因 16:20-16:36 才落库，
        # 叙事恒写「未覆盖（0/N，归因证据缺失）」，zhabanLabel 步的补全目的被顺序抵消）。
        zhaban_label_result = _run_zhaban_label_step(today, dry_run=dry_run)
        relay_index_result = _run_relay_index_step(today, dry_run=dry_run)
        # 板块节点（advisory，2026-10-24 v1）：纯本地确定性判定，昨日节点读昨日文档成链
        sector_nodes_result = _run_sector_nodes_step(today, dry_run=dry_run)
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
        return _result(
            ok=hotlist_ok and backup_ok and archive_ok,
            started_at=started_at,
            steps=["hotlistSentiment", "mongodbBackup", "snapshotArchiveR2", "phasePulse", "jiuyanLabel", "zhabanLabel", "relayIndex", "sectorNodes", "leaderWzs", "themeCycle", "relayBand", "phaseBand", "deepValley", "peakRevalidate", "jevDailyLine", "calibDriftMonitor", "amountVsSameRecord"],
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
                "relayBand": relay_band_result,
                "phaseBand": phase_band_result,
                "deepValley": deep_valley_result,
                "peakRevalidate": peak_revalidate_result,
                "jevDailyLine": jev_daily_line_result,
                "calibDriftMonitor": calib_drift_result,
                "amountVsSameRecord": amount_vs_same_result,
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