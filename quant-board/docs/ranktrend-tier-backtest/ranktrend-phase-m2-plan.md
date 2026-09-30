# M2 分相位验收框架——实施计划（相位-收益地图 + 北极星读数 + 极简月度监控）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.（若项目无对应技能注册，按主代理串行 + 任务间检查点执行。）

**Goal:** 落地 M2 三件套——分相位读数 harness（`phase_northstar.py`：相位 × 交易/权益切片 → 北极星机械线自动产出）、相位-收益地图（gen7 默认栈全窗基线文档）、极简月度监控脚本（`phase_monitor_monthly.py`）——使后续 M3 相位适配与月度监护有可执行的对照物。

**Architecture:** 复用 M1 链（`phase_label_run` 标签 / `phase_trade_slice.round_trips_of`/`wrxpf_of`）与批次 Runner 产物（1-summary.json 的 roundTripTrades + equityCurve 1071 点，帧对齐）；`phase_northstar` 负责把 equity 曲线按相位切段算段内回撤/暴露、把 roundTrip 交易按相位分桶出 wrxpf；`phase_monitor_monthly` 每月一条命令（重打标 → 重切片 → 三监督线），产出单 JSON + stderr 摘要，人工看。全程只读（Mongo find + 本地产物），不碰引擎/config，不占 8000。

**Tech Stack:** Python 3.13（quant-board .venv，scipy 1.14.1）、pymongo、pytest。

**范围裁定：** 本计划只做 M2 框架 + 基线地图 + 监控脚本；M3 适配候选（差相位降仓开关等）与任何默认值变更不在本计划。北极星判据按设计 §3 原文（好相位 wrxpf≥0.78+60 笔+回撤 10%；差相位防守线优于满仓）。

**裁决背景（M1 报告 §4，commit b626f825）：** 用户裁决不等 10 月扩窗复判，sentiment_2b（emotionScore.score 两档，offense≥50/defense<50）直接升格 M2 相位定义基准；证据状态（显著月不足）作为已知风险携带——月度监控发现划分不稳（方向翻转/显著月消失）即触发标签重打+地图重算。

**已锁定数据事实（2026-09-30 实测）：**

| 事实 | 值 |
|---|---|
| 标签产物 | `data/reports/phase-monitor/phase-labels-v1.json`，sentiment_2b 含 frameLabels(1071)/dailyByMajority(113)/dailyByPrevDay(113) |
| 交易产物 | `data/reports/b-202610/t6-runs-formal/1-summary.json`：roundTripTrades=54（字段 entryTradingDate/entryTime/regime/netReturn 齐）；**equityCurve=1071 点（snapshotId/tradingDate/slotTime/equity/cash/marketValue/positionCount），与帧一一对齐**；2-summary（回退栈）同构 |
| frames gzip | `exit-frames-...-20260327-20260930.json.gz` 1071 帧，stocks[].code/price |
| M1 链 API | `phase_labeler.phase_from_sentiment_score(score, hi, lo)` / `phase_label_run.CANDIDATES` / `phase_trade_slice.{round_trips_of, wrxpf_of, slice_trades}` |

---

## Task 1: 北极星读数 harness `phase_northstar`（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_northstar.py`
- Create: `quant-board/tests/research/test_phase_northstar.py`

- [ ] **Step 1: 写失败测试**（完整代码，逐字）

```python
# -*- coding: utf-8 -*-
"""M2 北极星读数 harness 测试：相位×交易切片 / 相位×权益段切片 / 机械线判定。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_northstar import (
    equity_phase_slices,
    evaluate_northstar,
    worst_drawdown,
)


def _mk_equity(points: list[tuple[str, str, float]]) -> list[dict]:
    return [{"tradingDate": d, "slotTime": s, "equity": e, "marketValue": mv}
            for (d, s, e), mv in zip(points, [0.0] * len(points))]


def test_worst_drawdown_window():
    eq = [100.0, 110.0, 99.0, 105.0, 120.0]
    assert worst_drawdown(eq) == min(0.0, (99 - 110) / 110)  # -0.1


def test_equity_phase_slices():
    daily = {"2026-05-06": "offense", "2026-05-07": "offense", "2026-05-08": "defense"}
    eq = _mk_equity([
        ("2026-05-06", "15:00", 100.0), ("2026-05-07", "15:00", 110.0),
        ("2026-05-08", "15:00", 99.0), ("2026-05-09", "15:00", 108.0),
    ])
    out = equity_phase_slices(eq, daily)
    # offense 段 = 05-06/07 两点；defense 段 = 05-08 一点（05-09 无标签不入段）
    assert out["offense"]["equityPoints"] == 2
    assert out["defense"]["equityPoints"] == 1
    assert out["unknownPoints"] == 1
    # 段内收益：offense 100→110 = +10%（两点才有 segReturn；单点 None）
    assert out["offense"]["segReturn"] == 0.10
    assert out["defense"]["segReturn"] is None


def test_equity_phase_slices_maxdd():
    daily = {"2026-05-06": "defense", "2026-05-07": "defense"}
    eq = _mk_equity([("2026-05-06", "15:00", 110.0), ("2026-05-07", "15:00", 99.0)])
    out = equity_phase_slices(eq, daily)
    assert out["defense"]["maxDD"] == (99 - 110) / 110


def test_evaluate_northstar_mechanical_lines():
    """好相位线：wrxpf≥0.78 ∧ 笔数≥60 ∧ 段内 maxDD≤10%；差相位防守线：段内回撤/净损优于满仓对照。"""
    by_phase = {
        "offense": {"trades": 61, "wrxpf": 0.80, "sumNetReturn": 0.30, "winRate": 0.5, "profitFactor": 1.6},
        "defense": {"trades": 10, "wrxpf": 0.30, "sumNetReturn": -0.20},
    }
    slices = {
        "offense": {"maxDD": -0.05, "equityPoints": 100, "segReturn": 0.10},
        "defense": {"maxDD": -0.08, "equityPoints": 60, "segReturn": -0.04},
    }
    full = {"maxDD": -0.12, "segReturn": -0.02}  # 满仓穿越对照
    out = evaluate_northstar(by_phase, slices, full)
    assert out["offense"]["line"] == {"wrxpf": True, "trades": True, "maxDD": True}
    assert out["offense"]["pass"] is True
    # 防守线：回撤浅于满仓（-0.08 > -0.12）或净损小（-0.04 > -0.02 不成立）→ pass=True（回撤项成立）
    assert out["defense"]["pass"] is True
    assert out["defense"]["defenseLine"] == {"ddBetter": True, "lossBetter": False}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/research/test_phase_northstar.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**（完整代码，逐字）

```python
# -*- coding: utf-8 -*-
"""M2 北极星读数 harness（ranktrend-phase-acceptance-design.md §3 分相位双线）。

好相位（offense，进攻职责）：wrxpf ≥ 0.78 ∧ 累计笔数 ≥ 60 ∧ 段内 maxDD ≤ 10%。
差相位（defense，防守职责）：不设 wrxpf 线；段内回撤或净损优于满仓穿越（二者其一）。
neutral：防守线宽松版同款计算，单列不判 pass（M3 适配的观察面）。
全部机械线自动产出；读数判定≠验收判定（验收走月度走廊，连续 3 期达线）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.operations.phase_trade_slice import round_trips_of, slice_trades

OFFENSE_LINE = {"wrxpf": 0.78, "trades": 60, "maxDD": -0.10}  # maxDD 为负值，段内 ≥ -0.10 为过


def worst_drawdown(equities: list[float]) -> float:
    """峰谷最大回撤（负数；空/单点 → 0.0）。"""
    peak = float("-inf")
    dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            dd = min(dd, (e - peak) / peak)
    return dd


def equity_phase_slices(equity_curve: list[dict], daily: dict[str, str]) -> dict:
    """equityCurve（帧对齐 1071 点）按入场日相位切段：每段 segReturn/段内 maxDD/点数。

    unknown 日不入任何段（fail-visible：unknown 点数单列）。
    """
    buckets: dict[str, list[float]] = {}
    unknown_points = 0
    for pt in equity_curve:
        day = str(pt.get("tradingDate") or "")
        phase = daily.get(day, "unknown")
        if phase == "unknown":
            unknown_points += 1
            continue
        buckets.setdefault(phase, []).append(float(pt.get("equity") or 0.0))
    out: dict = {"unknownPoints": unknown_points}
    for phase, eq in sorted(buckets.items()):
        out[phase] = {
            "equityPoints": len(eq),
            "segReturn": round(eq[-1] / eq[0] - 1, 4) if len(eq) >= 2 else None,
            "maxDD": round(worst_drawdown(eq), 4) if len(eq) >= 2 else None,
        }
    return out


def evaluate_northstar(by_phase: dict, slices: dict, full_window: dict) -> dict:
    """机械线判定（单期读数，非走廊判定）。

    by_phase: 相位桶交易读数（slice_trades 输出）；slices: equity_phase_slices 输出；
    full_window: {"maxDD", "segReturn"} 满仓穿越对照（equity_curve 全窗两指标）。
    """
    out: dict = {}
    for phase, tr in sorted(by_phase.items()):
        sl = slices.get(phase) or {}
        entry: dict = dict(tr)
        entry["maxDD"] = sl.get("maxDD")
        entry["segReturn"] = sl.get("segReturn")
        entry["equityPoints"] = sl.get("equityPoints")
        if phase == "offense":
            line = {
                "wrxpf": (tr.get("wrxpf") or 0) >= OFFENSE_LINE["wrxpf"],
                "trades": (tr.get("trades") or 0) >= OFFENSE_LINE["trades"],
                "maxDD": (sl.get("maxDD") is not None) and (sl["maxDD"] >= OFFENSE_LINE["maxDD"]),
            }
            entry["line"] = line
            entry["pass"] = all(line.values())
        elif phase in ("defense", "neutral"):
            dd_better = (sl.get("maxDD") is not None and full_window.get("maxDD") is not None
                         and sl["maxDD"] > full_window["maxDD"])
            loss_better = (tr.get("sumNetReturn") is not None and full_window.get("segReturn") is not None
                           and tr["sumNetReturn"] > full_window["segReturn"])
            entry["defenseLine"] = {"ddBetter": dd_better, "lossBetter": loss_better}
            entry["pass"] = dd_better or loss_better
        out[phase] = entry
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="M2 分相位北极星读数（只读）")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--candidate", default="sentiment_2b")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-northstar-v1.json")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    trades = round_trips_of(summary)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    cand = labels["candidates"][args.candidate]
    daily = cand["dailyByMajority"]
    equity_curve = summary.get("equityCurve") or []
    daily_final = dict(daily)  # equity 段用 dailyByMajority（equity 无"入场时点"语义，段=日切片）

    by_phase = slice_trades(trades, daily_final, "phase")
    slices = equity_phase_slices(equity_curve, daily_final)
    full_eq = [float(pt.get("equity") or 0.0) for pt in equity_curve]
    full_window = {
        "maxDD": round(worst_drawdown(full_eq), 4) if len(full_eq) >= 2 else None,
        "segReturn": round(full_eq[-1] / full_eq[0] - 1, 4) if len(full_eq) >= 2 else None,
    }
    report = {
        "meta": {
            "candidate": args.candidate,
            "thresholds": cand.get("thresholds"),
            "summaryFile": Path(args.summary).name,
            "labelsGeneratedAt": (labels.get("meta") or {}).get("generatedAt"),
            "tradeCount": len(trades),
            "equityPoints": len(equity_curve),
        },
        "fullWindow": full_window,
        "byPhase": by_phase,
        "equitySlices": slices,
        "northstar": evaluate_northstar(by_phase, slices, full_window),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过，再跑实数据**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_northstar.py -v`
Expected: **4 passed**

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_northstar`
Expected: stdout `tradeCount: 54`、equityPoints 1071；northstar.offense（26 笔 wrxpf 0.3407）与 defense（8 笔）读数与 M1 报告 §1.5 一致；JSON 落盘。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_northstar.py tests/research/test_phase_northstar.py
git commit -m "feat(ranktrend): M2 北极星 harness——相位×交易/权益切片+机械线判定（TDD）"
```

## Task 2: 相位-收益地图文档（gen7 基线）

**Files:**
- Create: `quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-map-baseline.md`

- [ ] **Step 1: 跑 northstar 实数据（Task 1 已产出 phase-northstar-v1.json）并写地图文档**

结构（数字全部来自 phase-northstar-v1.json 与 M1 报告，逐格填入，无占位）：

```markdown
# 相位-收益地图（gen7 基线，2026-09-30）

**相位定义**：sentiment_2b（emotionScore.score 两档，offense ≥50 / defense <50；用户 2026-09-30 裁决立项，M1 报告 §4）。
**对照物**：gen7 默认栈（vsB_070 + floor3 + midlong x30，锚 0.1472/0.1016/0.0981/0.0698）× B-202610 隔离 runner 全窗 dry-run（1-summary，bt_cd0ba11b698e4ebd）。
**用途**：M3 一切相位适配的对照基线；月度监控的 diff 对象。**读数属第四代 runner 口径**（frames 至 09-30，信号缓存与情绪文档 route B 重算后状态），引用注明。

## 1. 全窗对照
| 指标 | 满仓穿越 |
|---|---|
| maxDD / segReturn | （northstar.fullWindow 两值） |

## 2. 分相位地图
| 相位 | 交易 | wrxpf | sumNetReturn | 段内 maxDD | 段内收益 | 北极星 |
|---|---|---|---|---|---|---|
| offense | | | | | | （机械线逐项） |
| defense | | | | | | （防守线两项） |
| unknown/未覆盖 | （如实列出） |

## 3. M1 已知风险携带
（显著月不足 1<2 / 交易层与帧级方向相反（defense wrxpf 更高）54 笔薄样本 /
 3-6 月数据杂乱（52 合成帧）与 7-9 月齐全的分段不对称）

## 4. 变更规则
相位定义变更 = 标签重打（phase_label_run）+ 地图重算（phase_northstar）+ 本文档升版本号。
```

- [ ] **Step 2: Commit**

```bash
git add docs/ranktrend-tier-backtest/ranktrend-phase-map-baseline.md
git commit -m "docs(ranktrend): 相位-收益地图 gen7 基线（sentiment_2b × B-202610 runner 全窗）"
```

## Task 3: 极简月度监控 `phase_monitor_monthly`（TDD + 首跑）

**Files:**
- Create: `quant-board/backend/operations/phase_monitor_monthly.py`
- Create: `quant-board/tests/research/test_phase_monitor_monthly.py`

- [ ] **Step 1: 写失败测试**（完整代码，逐字）

```python
# -*- coding: utf-8 -*-
"""M2 月度监控测试：三监督线读数组装 + 走廊状态机（不写 Mongo，纯函数）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_monitor_monthly import build_supervision, corridor_state


def test_build_supervision_lines():
    """三监督线：S+A 触发率(<3.5% 预警)/insufficient 占比(回弹预警)/北极星单期读数。"""
    sup = build_supervision(
        sa_trigger_rate=0.032,
        insufficient_share=0.088,
        northstar_pass={"offense": True, "defense": True},
    )
    assert sup["saTriggerRate"]["value"] == 0.032
    assert sup["saTriggerRate"]["alert"] is True          # <3.5% 触发 R3 预警线
    assert sup["insufficientShare"]["value"] == 0.088
    assert sup["insufficientShare"]["alert"] is False      # <15%（floor5 原水平）不预警
    assert sup["northstar"]["pass"] == {"offense": True, "defense": True}


def test_corridor_state_three_strikes():
    """走廊：连续 3 期 offense 达线 → 达成；中断即清零重计。"""
    hist = [{"offense": True, "defense": True},
            {"offense": True, "defense": False},
            {"offense": True, "defense": False},
            {"offense": True, "defense": True}]
    state = corridor_state(hist)
    assert state["offenseStreak"] == 4      # 4 期连续
    assert state["offenseAchieved"] is True  # ≥3 达成
    assert state["defenseStreak"] == 1
    assert state["defenseAchieved"] is False


def test_corridor_state_resets_on_false():
    hist = [{"offense": True}, {"offense": True}, {"offense": False}, {"offense": True}]
    state = corridor_state(hist)
    assert state["offenseStreak"] == 1
    assert state["offenseAchieved"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_monitor_monthly.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**（完整代码，逐字）

```python
# -*- coding: utf-8 -*-
"""M2 极简月度监控（ranktrend-phase-acceptance-design.md §5 月度监控节）。

每月数据落库后一条命令：重打标（扩窗 frames）→ 重切片（上月新交易并入）→ 三监督线落盘。
产出单 JSON + stderr 摘要，人工看；无判定卡、无 trial、无三件同步。
监督线：① S+A 触发率（R3 verdictRule：持续 <3.5% 评估 buyScoreThreshold 微调）
② insufficient 占比（floor3 后基线 ~9.4%，回弹 >15% 预警）
③ 北极星单期读数 + 走廊状态（连续 3 期达线=达成）。
只读：Mongo find（hotlist_sentiment/snapshot_frames 计数）+ 本地产物；不占 8000。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def build_supervision(sa_trigger_rate: float, insufficient_share: float, northstar_pass: dict) -> dict:
    return {
        "saTriggerRate": {"value": sa_trigger_rate, "alert": sa_trigger_rate < 0.035},
        "insufficientShare": {"value": insufficient_share, "alert": insufficient_share > 0.15},
        "northstar": {"pass": northstar_pass},
    }


def corridor_state(history: list[dict]) -> dict:
    """走廊状态机：逐相位连续达线期数；≥3 → achieved。history 按时间升序。"""
    out: dict = {}
    for key in ("offense", "defense"):
        streak = 0
        for rec in history:
            if rec.get(key) is True:
                streak += 1
            else:
                streak = 0
        out[f"{key}Streak"] = streak
        out[f"{key}Achieved"] = streak >= 3
    return out


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="M2 月度监控（只读）")
    parser.add_argument("--month", required=True, help="监控月份 YYYY-MM（数据应已落库）")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path(f"data/reports/phase-monitor/monthly-{args.month}.json")

    # ① 情绪覆盖：本月 hotlist_sentiment half_hour 文档数与交易日数（缺档→fail-visible）
    from pymongo import MongoClient
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    month_prefix = f"{args.month}"
    sent_docs = db["hotlist_sentiment"].count_documents(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "tradingDate": {"$regex": f"^{month_prefix}"}})
    month_days = db["hotlist_sentiment"].distinct(
        "tradingDate", {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
                        "tradingDate": {"$regex": f"^{month_prefix}"}})

    # ② 标签 freshness：labels 是否含本月（不含 → 提示需扩窗重打标，不自动跑）
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    cand = labels["candidates"]["sentiment_2b"]
    labeled_days = sorted(cand["dailyByMajority"])
    fresh = bool(labeled_days and labeled_days[-1] >= f"{args.month}-28")

    # ③ 三监督线（S+A 触发率与 insufficient 占比从最近 runner summary 或大盘统计读入；
    #    M2 首期允许 stub=None→监控 JSON 如实记 null，人工补读）
    northstar_file = Path("data/reports/phase-monitor/phase-northstar-v1.json")
    ns = json.loads(northstar_file.read_text(encoding="utf-8")) if northstar_file.exists() else {}
    ns_pass = {k: (ns.get("northstar", {}).get(k, {}).get("pass")) for k in ("offense", "defense")}

    sup = build_supervision(
        sa_trigger_rate=None,        # 首期无自动源：如实 null（月度监控说明人工补读位置）
        insufficient_share=None,
        northstar_pass=ns_pass,
    )

    report = {
        "meta": {"month": args.month, "generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "gitCommit": _git_commit()},
        "coverage": {"sentimentDocs": sent_docs, "tradingDays": len(month_days),
                     "labelsFresh": fresh,
                     "labelsNote": "labels 未覆盖本月→先跑 phase_label_run 扩窗重打标（命令见 M1 报告 §2.5）" if not fresh else None},
        "supervision": sup,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[monthly] -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过 + 首跑**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_monitor_monthly.py -v`
Expected: **3 passed**

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_monitor_monthly --month 2026-09`
Expected: exit 0；JSON 落 `data/reports/phase-monitor/monthly-2026-09.json`；`labelsFresh=True`、coverage.sentimentDocs>0、supervision.saTriggerRate.value=null（首期 stub 如实记录）。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_monitor_monthly.py tests/research/test_phase_monitor_monthly.py
git commit -m "feat(ranktrend): M2 极简月度监控——三监督线+走廊状态机+标签 freshness 检查（TDD）"
```

## Task 4: M2 收口文档（框架落成记录 + 移交 M3）

**Files:**
- Create: `quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-m2-closure.md`

- [ ] **Step 1: 写收口文档**（结构固定，数字从产物读）

```markdown
# M2 分相位验收框架收口（2026-09-30）

## 1. 交付物
（northstar harness / 地图基线文档 / 月度监控——各自路径 + 测试数 + 首跑读数摘要）

## 2. 北极星首期读数
（phase-northstar-v1.json：offense 机械线三项逐值、defense 防守线两项、fullWindow 对照；
  明确写"单期读数≠验收——走廊需连续 3 期"）

## 3. 已知风险与监护触发器
（M1 证据不足携带 / 划分不稳→重打标+地图重算 / S+A<3.5% 与 insufficient>15% 两条预警线的动作指引）

## 4. M3 移交
（对照物=地图基线；候选顺序：差相位降仓开关 → 好相位放宽 → 卖点按相位重审 → O8 相位收尾；
  M3 立项走 writing-plans 另出计划）
```

- [ ] **Step 2: Commit**

```bash
git add docs/ranktrend-tier-backtest/ranktrend-phase-m2-closure.md
git commit -m "docs(ranktrend): M2 分相位验收框架收口——北极星首期读数+监护触发器+M3 移交"
```

## 验证总表

| 项 | 验证 |
|---|---|
| Task 1 | 4 passed；实跑 phase-northstar-v1.json 与 M1 报告 §1.5 读数一致（26/8 笔、wrxpf 同值） |
| Task 2 | 地图文档数字逐格来自产物，无占位 |
| Task 3 | 3 passed；首跑 monthly-2026-09.json 落盘、labelsFresh=True |
| Task 4 | 收口文档含移交与触发器 |
| 纪律 | 全程只读、无引擎/config 改动、产物不入 git、每任务独立 commit |

## M3 移交说明（本计划范围外）

M3 立项条件已由用户裁决提前满足（北极星框架落成即立项）；候选顺序按设计 §5：① 差相位降仓/空仓开关（直接兑现防守线）② 好相位入场放宽/加码 ③ 卖点按相位重审（吸收卖点课题）④ O8 双强相位收尾。**M3 的任何默认值变更仍走一次一候选 + 用户决策。**
