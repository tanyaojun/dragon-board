# 分相位验收长测计划——实施计划（Phase 0 封存 + M1 相位定义）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 执行旧长测体系封存（观察池/L1/长测文档三处），并完成 M1 相位定义——用情绪连续评分与市场情绪值两套候选给历史全窗打相位标签，经检验三关（稳定性/滞后性/区分度）出 M1 报告与出口判据判定。

**Architecture:** 封存为纯文档动作；M1 为只读研究链——`phase_labeler`（纯函数标签器，TDD）→ `phase_label_run`（全窗打标落盘）→ `phase_trade_slice`（54 笔交易按相位切片）→ `phase_quality_report`（前向收益 + 检验三关），全部走 Mongo 只读 + 本地 frames gzip，不占 8000、不碰引擎与默认值。

**Tech Stack:** Python 3.13（quant-board .venv）、pymongo、pytest；数据源 Mongo `dragon_board_quant`（hotlist_sentiment / snapshot_frames）+ 本地 `data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz`（1071 帧全窗）。

**范围裁定（设计文档 §6）：** 本计划只覆盖封存 + M1。M2（分相位验收框架/相位-收益地图）与 M3（相位适配）在 M1 出口判定后**另立计划**——M1 结果直接决定 M2 切片维度与 M3 候选顺序，现在写任务级是空中楼阁。

**已锁定的数据事实（写代码前不需要再盘点）：**

| 事实 | 值 |
|---|---|
| 情绪连续分 | Mongo `hotlist_sentiment`，过滤 `{datasetId:'dragonboard_live', snapshotType:'half_hour'}`，字段 `emotionScore.score`（0-100，dict 内层），1184 文档/113 日全覆盖，自 2026-04-15；EOD 文档（slotTime='EOD'）同样带 score |
| 帧级市场情绪 | frames 自带 `marketStats.emotionValue`（小数，如 −0.0115），全窗 1071 帧可用 |
| 交易层 join 键 | `t6-runs-formal/1-summary.json` 的 trades 带 `entryTradingDate`、`entryTime`（ms 纪元）、`regime`（入场时引擎 regime，现成）、`netReturn` |
| 帧标识 | 帧 dict 顶层 `tradingDate` + `slotTime`（"HH:MM"） |

---

## Phase 0：旧体系封存（三个任务，纯文档）

### Task 1: 观察池 YAML 归档结案

**Files:**
- Modify: `quant-board/config/ranktrend-observation-pool.yaml`

- [ ] **Step 1: 确认无代码消费者**

Run: `cd /d/dragon-board/quant-board && rg -l "observation-pool" backend/ scripts/ tests/`
Expected: 无输出（B-202610 批次为人工执行，无 runner 解析此文件）。若有输出，停下向用户报告再继续。

- [ ] **Step 2: 文件头加封存横幅**

在 `schema: ranktrend-observation-pool/v1` 行之前插入：

```yaml
# ============================================================================
# 【已封存 2026-09-30】旧月度批次体系观察池——用户裁决推倒重来，本文件转历史档案。
# 新体系：docs/ranktrend-tier-backtest/ranktrend-phase-acceptance-design.md（分相位验收）。
# 停止新增登记；各项终态见各条目 sealedNote。重启任何观察项需另立计划。
# ============================================================================
sealed: '2026-09-30'
sealedRedirect: ../docs/ranktrend-tier-backtest/ranktrend-phase-acceptance-design.md
```

- [ ] **Step 3: 每个条目加一行 sealedNote（插在各自 `status:` 行之后）**

```yaml
    sealedNote: 转默认值变更史（L1 §17），复核职能随体系封存
```
（适用于 R1_fund10 / R2_combo_three_quarter / R3_ts_weights_p2aggressive / R4_ma_join / R5_jump_fix / R6_exit_tp_be / O3_vsb070 / O6_midlong_commitment_dose / P_repool_timeline_gap，共 9 项 in_default）

```yaml
    sealedNote: 被新计划 M3 吸收（相位视角收尾）——见 ranktrend-phase-acceptance-design.md
```
（适用于 O8_dual_strength / N2_trade_layer_topics）

```yaml
    sealedNote: 随体系封存归档（2026-09-30），重启需另立计划
```
（适用于 O1_p2 / O2_fund10_over2 / O4_jump25_fresh06 / O5_buyThr018 / O7_cs_a_tier / O9_trailing_rescan / O10_break_board_watch / O11_mild_ratio_105 / N1_jump_confirm_scan / N3_atr_discrimination / N4_ma_replace_trigger / N5_ma_cross_event / N6_regime_gate_alpha_hysteresis / N7_res_nan_median_h2 / N9_group5_walkforward / N10_confirm_frames_k / N11_tp_finer_boundary / N12_highrisk_pressure_gate / N13_persist_reeval / N14_strong_bimodal_gating）

- [ ] **Step 4: Commit**

```bash
git add config/ranktrend-observation-pool.yaml
git commit -m "docs(ranktrend): 观察池封存归档——全部条目终态 sealedNote（体系切换）"
```

### Task 2: L1 台账与长测文档封存注记

**Files:**
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`（文首标题后）
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`（文首标题后 + §27.9）

- [ ] **Step 1: L1 台账文首加注记**

在 `# 一级参数台账`（首个标题行）之后插入：

```markdown
> **【已封存 2026-09-30】**复核登记职能随旧月度批次体系封存——本文转为**默认值变更史**（§1-§17 即完整历史，不再新增复核章节）。新体系：`ranktrend-phase-acceptance-design.md`。
```

- [ ] **Step 2: 长测文档文首加注记**

在 `# 四维信号长期回测计划与性能优化方案` 标题行之后插入：

```markdown
> **【已封存 2026-09-30】**阶段 0-27 为历史档案，不再新增阶段。后续研究走分相位验收体系：`ranktrend-phase-acceptance-design.md`（M1-M3 + 极简月度监控）；引擎侧默认值基准仍以 `config/ranktrend-anchors.json`（gen-2026-09-30-midlong-x30）为准。
```

- [ ] **Step 3: 修正 §27.9 中 b-202611 指针**

将 §27.9 第一段中 `B-202611 阶段计划：\`ranktrend-b-202611-plan.md\`（同目录）` 替换为 `B-202611 阶段计划（当日废弃并删除，git 3ba3c8b3 留档；后继为分相位验收体系 \`ranktrend-phase-acceptance-design.md\`）`。

- [ ] **Step 4: Commit**

```bash
git add docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md
git commit -m "docs(ranktrend): L1 台账与长测文档封存注记（转历史档案，指向分相位新体系）"
```

---

## M1：相位定义（研究链，只读）

**候选范围注记（对设计 §5 候选清单的落地裁定）**：设计列了四个候选，v1 打标进三个——情绪连续分（sentiment_v1 三档 / sentiment_2b 两档）、帧自带市场情绪值（breadth_v1）；regime 四桶不单独打标，用 trades 自带 `regime` 字段在交易层切片中直接验证（零成本、避免为帧级 regime 重跑 replay）。**limitSummary 与 ThemeTrend 拥挤度不进 v1**：前者是服务端现算无历史落档，后者 theme_daily_factors 仅回填 60 日（月度区分度需 ≥2 月，勉强不够）——两者作为 M2 月度监控的增量输入候选，M1 报告诚实边界中披露。另 breadth_v1 为盘点新发现的帧级信号（设计清单外增补，覆盖全窗 1071 帧）。

### Task 3: 相位标签器 phase_labeler（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_labeler.py`
- Test: `quant-board/tests/research/test_phase_labeler.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 相位标签器测试（ranktrend-phase-acceptance-design.md §5 M1）。

纪律：as-of 无未来函数；信号缺失 → unknown（fail-visible 不伪造）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_labeler import (
    daily_phase_from_frames,
    load_sentiment_scores,
    phase_from_emotion_value,
    phase_from_sentiment_score,
)


def test_phase_from_sentiment_score_three_buckets():
    assert phase_from_sentiment_score(69.7, hi=55.0, lo=40.0) == "offense"
    assert phase_from_sentiment_score(48.3, hi=55.0, lo=40.0) == "neutral"
    assert phase_from_sentiment_score(13.6, hi=55.0, lo=40.0) == "defense"
    assert phase_from_sentiment_score(None, hi=55.0, lo=40.0) == "unknown"


def test_phase_from_emotion_value():
    assert phase_from_emotion_value(0.02, hi=0.005, lo=-0.005) == "offense"
    assert phase_from_emotion_value(0.0, hi=0.005, lo=-0.005) == "neutral"
    assert phase_from_emotion_value(-0.0115, hi=0.005, lo=-0.005) == "defense"
    assert phase_from_emotion_value(None, hi=0.005, lo=-0.005) == "unknown"


def test_load_sentiment_scores_filters_half_hour_and_eod():
    docs = [
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "snapshotType": "half_hour",
         "emotionScore": {"score": 65.6}},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "snapshotType": "daily",
         "emotionScore": {"score": 99.0}},   # 非 half_hour：整体排除
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "snapshotType": "half_hour",
         "emotionScore": None},               # 无连续分：该键值为 None（unknown 语义）
        {"tradingDate": "2026-09-30", "slotTime": "EOD", "snapshotType": "half_hour",
         "emotionScore": {"score": 48.3}},   # EOD 进独立键
    ]
    frame_scores, eod_scores = load_sentiment_scores(docs)
    assert frame_scores[("2026-09-30", "10:00")] == 65.6
    assert frame_scores[("2026-09-30", "09:30")] is None
    assert eod_scores["2026-09-30"] == 48.3


def test_daily_phase_from_frames_majority_and_missing():
    frames = [
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:30", "phase": "defense"},
        {"tradingDate": "2026-10-09", "slotTime": "09:30", "phase": "unknown"},
    ]
    daily = daily_phase_from_frames(frames)
    assert daily["2026-09-30"] == "offense"   # 众数；平票取更保守（defense 优先于 offense）
    assert daily["2026-10-09"] == "unknown"   # 全 unknown → unknown（不伪造）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/research/test_phase_labeler.py -v`
Expected: FAIL（ModuleNotFoundError: phase_labeler）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 相位标签器（ranktrend-phase-acceptance-design.md §5 M1）。

候选相位信号 → 帧级/日级相位标签（offense/neutral/defense/unknown）。
纪律：as-of 无未来函数（只消费当前帧及之前可得数据）；缺信号 → unknown（fail-visible）；
相位定义（阈值/档数）变更 = 标签全量重打（轻量代际纪律，设计文档 §5 纪律新增条）。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

# 保守序：平票时防守侧优先（宁可少进攻不可漏防守）
_TIE_BREAK = {"defense": 0, "neutral": 1, "offense": 2}


def phase_from_sentiment_score(score: float | None, *, hi: float, lo: float) -> str:
    """情绪 route B 连续分（0-100）→ 相位：score≥hi 进攻 / <lo 防守 / 其间中性。"""
    if score is None:
        return "unknown"
    if score >= hi:
        return "offense"
    if score < lo:
        return "defense"
    return "neutral"


def phase_from_emotion_value(value: float | None, *, hi: float, lo: float) -> str:
    """帧自带 marketStats.emotionValue（市场宽度情绪小数）→ 相位，同三段规则。"""
    if value is None:
        return "unknown"
    if value >= hi:
        return "offense"
    if value < lo:
        return "defense"
    return "neutral"


def load_sentiment_scores(docs: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], float | None], dict[str, float | None]]:
    """hotlist_sentiment 文档 → 帧级 (tradingDate, slotTime)→score 与日级 EOD→score 两张表。

    内化 snapshotType 过滤（非 half_hour 的重复文档整体排除——同槽多版本以列表后序为准，
    调用方 Mongo 查询同样带过滤，双保险）；emotionScore 为 dict（route B 结构，score-v1）
    或 None（旧文档/重算未覆盖）。
    """
    frame_scores: dict[tuple[str, str], float | None] = {}
    eod_scores: dict[str, float | None] = {}
    for d in docs:
        st = d.get("snapshotType")
        if st not in (None, "half_hour"):
            continue
        date, slot = str(d.get("tradingDate") or ""), str(d.get("slotTime") or "")
        es = d.get("emotionScore")
        score = float(es["score"]) if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        if slot == "EOD":
            eod_scores[date] = score
        elif slot:
            frame_scores[(date, slot)] = score
    return frame_scores, eod_scores


def daily_phase_from_frames(frames: list[dict[str, Any]]) -> dict[str, str]:
    """帧级相位 → 日级相位（日内众数；平票取保守序靠前；全 unknown → unknown）。"""
    by_day: dict[str, Counter] = {}
    for f in frames:
        day, phase = str(f.get("tradingDate") or ""), str(f.get("phase") or "unknown")
        if day:
            by_day.setdefault(day, Counter())[phase] += 1
    daily: dict[str, str] = {}
    for day, counter in by_day.items():
        if set(counter) == {"unknown"}:
            daily[day] = "unknown"
            continue
        counted = {p: c for p, c in counter.items() if p != "unknown"}
        top = max(counted.values())
        daily[day] = sorted((p for p, c in counted.items() if c == top), key=lambda p: _TIE_BREAK.get(p, 9))[0]
    return daily
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_labeler.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_labeler.py tests/research/test_phase_labeler.py
git commit -m "feat(ranktrend): M1 相位标签器——情绪连续分/市场情绪值双候选三档（TDD，fail-visible）"
```

### Task 4: 全窗打标脚本 phase_label_run

**Files:**
- Create: `quant-board/backend/operations/phase_label_run.py`

- [ ] **Step 1: 实现打标 CLI（读 Mongo + 本地 frames gz，输出标签 JSON）**

```python
# -*- coding: utf-8 -*-
"""M1 全窗打标：候选相位定义 × 全窗帧 → 帧级+日级标签 JSON。

用法（quant-board 目录）：
  ./.venv/Scripts/python.exe -m backend.operations.phase_label_run \
      --frames data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz \
      --out data/reports/phase-monitor/phase-labels-v1.json

只读：Mongo hotlist_sentiment（half_hour 口径）+ 本地 frames gzip；不占 8000。
候选定义（v1，M1 检验对象）：
  sentiment_v1 : emotionScore.score，hi=55 / lo=40
  sentiment_2b : emotionScore.score 两档，hi=50 / lo=50（offense≥50）
  breadth_v1   : marketStats.emotionValue，hi=0.005 / lo=-0.005
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.phase_labeler import (
    daily_phase_from_frames,
    load_sentiment_scores,
    phase_from_emotion_value,
    phase_from_sentiment_score,
)

CANDIDATES = {
    "sentiment_v1": ("sentiment", {"hi": 55.0, "lo": 40.0}),
    "sentiment_2b": ("sentiment", {"hi": 50.0, "lo": 50.0}),
    "breadth_v1": ("emotion_value", {"hi": 0.005, "lo": -0.005}),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 相位打标（只读）")
    parser.add_argument("--frames", required=True, help="本地 frames gzip 路径")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    print(f"[phase-label] frames={len(frames)}", file=sys.stderr)

    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    docs = list(db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ))
    frame_scores, eod_scores = load_sentiment_scores(docs)
    print(f"[phase-label] sentiment docs={len(docs)} days_eod={len(eod_scores)}", file=sys.stderr)

    report: dict = {"candidates": {}}
    for key, (source, thr) in CANDIDATES.items():
        labeled = []
        for fr in frames:
            day, slot = str(fr.get("tradingDate") or ""), str(fr.get("slotTime") or "")
            if source == "sentiment":
                phase = phase_from_sentiment_score(frame_scores.get((day, slot)), **thr)
            else:
                mv = ((fr.get("marketStats") or {}).get("emotionValue"))
                phase = phase_from_emotion_value(mv if isinstance(mv, (int, float)) else None, **thr)
            labeled.append({"tradingDate": day, "slotTime": slot, "phase": phase})
        daily = daily_phase_from_frames(labeled)
        daily_eod = {d: phase_from_sentiment_score(s, **thr) for d, s in eod_scores.items()} \
            if source == "sentiment" else {}
        report["candidates"][key] = {
            "source": source, "thresholds": thr,
            "frameLabels": labeled, "dailyByMajority": daily, "dailyByEod": daily_eod,
        }
        dist = Counter(x["phase"] for x in labeled)
        print(f"[phase-label] {key}: 帧分布={dict(dist)} 日数={len(daily)}", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(f"[phase-label] -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 跑通并检查产出**

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_label_run --frames data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz --out data/reports/phase-monitor/phase-labels-v1.json`
Expected: stderr 打出三候选的帧分布（各 1071 帧计入，分布非全 unknown；sentiment 两候选 unknown 帧仅限 04-15 前不存在——实际 04-15 起全覆盖应为 0 或极少）；JSON 落盘。

- [ ] **Step 3: Commit**

```bash
git add backend/operations/phase_label_run.py
git commit -m "feat(ranktrend): M1 全窗打标脚本——三候选定义帧级+日级标签（只读 CLI）"
```

### Task 5: 交易层相位切片 phase_trade_slice（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_trade_slice.py`
- Test: `quant-board/tests/research/test_phase_trade_slice.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 交易层相位切片测试：54 笔历史交易按入场日相位 + 入场时 regime 双口径切片。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_trade_slice import wrxpf_of, slice_trades


TRADES = [
    {"entryTradingDate": "2026-05-06", "regime": "strong", "netReturn": 0.10},
    {"entryTradingDate": "2026-05-07", "regime": "strong", "netReturn": -0.05},
    {"entryTradingDate": "2026-07-29", "regime": "retreat", "netReturn": -0.08},
]


def test_wrxpf_of_basic():
    m = wrxpf_of([{"netReturn": 0.1}, {"netReturn": -0.05}])
    assert m["trades"] == 2
    assert m["winRate"] == 0.5
    assert m["profitFactor"] == 2.0
    assert m["wrxpf"] == 1.0
    assert m["sumNetReturn"] == 0.05


def test_wrxpf_of_empty():
    assert wrxpf_of([])["wrxpf"] is None


def test_slice_trades_by_daily_phase():
    daily = {"2026-05-06": "offense", "2026-05-07": "offense", "2026-07-29": "defense"}
    out = slice_trades(TRADES, daily=daily, phase_key="phase")
    assert out["offense"]["trades"] == 2
    assert out["defense"]["trades"] == 1
    assert out["defense"]["sumNetReturn"] == -0.08


def test_slice_trades_by_regime_field():
    out = slice_trades(TRADES, daily=None, phase_key="regime")
    assert out["strong"]["trades"] == 2
    assert out["retreat"]["sumNetReturn"] == -0.08
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_trade_slice.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 最小实验：历史交易按相位切片读数（设计文档 §5 M1 首步）。

双口径：① 入场日相位（daily 标签 join entryTradingDate）② 入场时引擎 regime
（trade.regime 现成字段，作为 regime 四桶候选的交易层直接证据）。
"""
from __future__ import annotations

import json
from pathlib import Path


def wrxpf_of(trades: list[dict]) -> dict:
    rets = [float(t.get("netReturn") or 0) for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    win_rate = len(wins) / len(rets) if rets else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    return {
        "trades": len(rets),
        "winRate": round(win_rate, 4) if win_rate is not None else None,
        "profitFactor": round(pf, 4) if pf is not None and pf != float("inf") else None,
        "wrxpf": round(win_rate * pf, 4) if (win_rate is not None and pf is not None and pf != float("inf")) else None,
        "sumNetReturn": round(sum(rets), 4),
        "maxSingleLoss": round(min(rets), 4) if rets else None,
    }


def slice_trades(trades: list[dict], daily: dict[str, str] | None, phase_key: str) -> dict:
    """phase_key='phase'（用 daily 标签）或 'regime'（用 trade 自带字段）。"""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        if phase_key == "phase":
            label = (daily or {}).get(str(t.get("entryTradingDate") or ""), "unknown")
        else:
            label = str(t.get("regime") or "unknown")
        buckets.setdefault(label, []).append(t)
    return {k: wrxpf_of(v) for k, v in sorted(buckets.items())}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="M1 交易层相位切片")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-trade-slice-v1.json")
    args = parser.parse_args()

    trades = json.loads(Path(args.summary).read_text(encoding="utf-8")).get("trades") or []
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    report: dict = {"tradeCount": len(trades), "byCandidate": {}, "byRegime": slice_trades(trades, None, "regime")}
    for key, cand in labels.get("candidates", {}).items():
        report["byCandidate"][key] = slice_trades(trades, cand.get("dailyByMajority"), "phase")
        report.setdefault("byCandidateEod", {})[key] = slice_trades(trades, cand.get("dailyByEod"), "phase")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过，再跑实数据**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_trade_slice.py -v`
Expected: 4 passed

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_trade_slice`
Expected: stdout 打出 54 笔的三候选切片 + regime 切片读数（每桶 trades/wrxpf/sumNetReturn）。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_trade_slice.py tests/research/test_phase_trade_slice.py
git commit -m "feat(ranktrend): M1 交易层相位切片——54 笔按入场相位×regime 双口径（TDD）"
```

### Task 6: 检验三关 phase_quality_report（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_quality_report.py`
- Test: `quant-board/tests/research/test_phase_quality_report.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 检验三关测试：翻转率 / 滞后性 / 区分度（手工 Mann-Whitney U）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_quality_report import (
    flip_rate,
    mannwhitneyu,
    monthly_discrimination,
)


def test_flip_rate():
    labels = ["offense", "offense", "defense", "defense", "offense", "unknown", "offense"]
    # 6 对相邻转移中，含 unknown 的 2 对不计分母 → 4 对有效，其中 2 对翻转 → 0.5
    rate = flip_rate(labels)
    assert abs(rate - 0.5) < 1e-9


def test_mannwhitney_u_separates():
    a = [0.05, 0.06, 0.07, 0.08, 0.09]
    b = [-0.05, -0.04, -0.03, -0.02, -0.01]
    u, p = mannwhitneyu(a, b)
    assert u == 25.0  # 完全分离
    assert p < 0.05


def test_monthly_discrimination_requires_two_months():
    daily = {
        "2026-05-04": "offense", "2026-05-05": "offense", "2026-05-06": "defense",
        "2026-06-01": "offense", "2026-06-02": "defense", "2026-06-03": "defense",
    }
    rets = {"2026-05-04": 0.05, "2026-05-05": 0.06, "2026-05-06": -0.05,
            "2026-06-01": 0.04, "2026-06-02": -0.06, "2026-06-03": -0.04}
    rows = monthly_discrimination(daily, rets)
    # 两月各有 offense/defense 样本 → 每月一行
    assert len(rows) == 2
    assert all(r["offenseMean"] > r["defenseMean"] for r in rows)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_quality_report.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 检验三关：稳定性（帧级翻转率）/ 滞后性（相位切换 vs 收益拐点 lag）/ 区分度（月度
Mann-Whitney offense vs defense，手工实现免 scipy 依赖）。

出口判据（设计文档 §5 M1）：区分度 = 好相位日收益高于差相位（p<0.05 或均值差≥2%）
且方向在 ≥2 个独立月份一致；滞后 ≤3 交易日。
前向收益口径：日级池等权 h1/h8——当日末槽（15:00）持仓池在 1/8 帧后的价格变化均值。
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def flip_rate(labels: list[str]) -> float:
    """相邻帧标签翻转率（unknown 参与位置但转移不计入分子分母）。"""
    flips = 0
    total = 0
    for a, b in zip(labels, labels[1:]):
        if a == "unknown" or b == "unknown":
            continue
        total += 1
        if a != b:
            flips += 1
    return flips / total if total else 0.0


def mannwhitneyu(a: list[float], b: list[float]) -> tuple[float, float]:
    """手工 Mann-Whitney U（正态近似，无 tie 校正——日级样本量下足够判 p<0.05）。"""
    n, m = len(a), len(b)
    ranked = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    rank_sum_a = 0.0
    for i, (v, g) in enumerate(ranked, start=1):
        if g == 0:
            rank_sum_a += i
    u1 = rank_sum_a - n * (n + 1) / 2
    u = max(u1, n * m - u1)
    mu = n * m / 2
    sigma = math.sqrt(n * m * (n + m + 1) / 12)
    z = (u - mu) / sigma if sigma else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))  # 双尾
    return u, p


def monthly_discrimination(daily: dict[str, str], rets: dict[str, float]) -> list[dict]:
    """按自然月分组：offense vs defense 日收益 Mann-Whitney + 均值差。"""
    by_month: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day, phase in daily.items():
        r = rets.get(day)
        if r is None or phase not in ("offense", "defense"):
            continue
        by_month[day[:7]][phase].append(float(r))
    rows = []
    for month in sorted(by_month):
        a, b = by_month[month].get("offense", []), by_month[month].get("defense", [])
        if len(a) < 2 or len(b) < 2:
            continue
        u, p = mannwhitneyu(a, b)
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        rows.append({"month": month, "nOffense": len(a), "nDefense": len(b),
                     "offenseMean": round(ma, 5), "defenseMean": round(mb, 5),
                     "meanDiff": round(ma - mb, 5), "u": u, "p": round(p, 5),
                     "pass": (p < 0.05) or (abs(ma - mb) >= 0.02)})
    return rows


def daily_forward_returns(frames: list[dict], horizon: int) -> dict[str, float]:
    """帧序列按时间排序 → 每日末槽（最大 slotTime）池等权 h{horizon} 前向收益。"""
    frames = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    prices: dict[int, dict[str, float]] = {}
    for i, fr in enumerate(frames):
        prices[i] = {str(s.get("code")): float(s["price"]) for s in (fr.get("stocks") or []) if s.get("price")}
    last_slot_by_day: dict[str, int] = {}
    for i, fr in enumerate(frames):
        last_slot_by_day[str(fr.get("tradingDate") or "")] = i  # 排序后自然取到当日末槽
    out: dict[str, float] = {}
    for day, i in last_slot_by_day.items():
        j = i + horizon
        if j >= len(frames):
            continue
        base, nxt = prices.get(i, {}), prices.get(j, {})
        rets = [nxt[c] / p - 1 for c, p in base.items() if c in nxt and p > 0]
        if rets:
            out[day] = sum(rets) / len(rets)
    return out


def lag_check(daily: dict[str, str], rets: dict[str, float], max_lag: int = 5) -> dict:
    """滞后性：相位二值序列（offense=1/defense=0）与次日收益序列在 lag 0..max_lag 的
    Pearson 相关 argmax——argmax>0 表示相位落后于收益（坏），≤3 交易日可接受。"""
    days = sorted(daily)
    xs, ys = [], []
    for d0, d1 in zip(days, days[1:]):
        if d0 in rets and daily[d0] in ("offense", "defense"):
            xs.append(1.0 if daily[d0] == "offense" else 0.0)
            ys.append(rets[d0])
    def corr(x: list[float], y: list[float]) -> float:
        n = len(x)
        if n < 3:
            return 0.0
        mx, my = sum(x) / n, sum(y) / n
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
        return num / den if den else 0.0
    lags = {}
    for lag in range(max_lag + 1):
        x, y = (xs, ys) if lag == 0 else (xs[: len(xs) - lag], ys[lag:])
        lags[lag] = corr(x, y)
    best = max(lags, key=lambda k: lags[k])
    return {"corrByLag": {k: round(v, 4) for k, v in lags.items()}, "argmaxLag": best,
            "acceptable": best <= 3, "n": len(xs)}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 检验三关")
    parser.add_argument("--frames", default="data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-quality-v1.json")
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    rets_h1 = daily_forward_returns(frames, 1)
    rets_h8 = daily_forward_returns(frames, 8)

    report: dict = {"h1Days": len(rets_h1), "h8Days": len(rets_h8), "candidates": {}}
    for key, cand in labels.get("candidates", {}).items():
        frame_labels = [x["phase"] for x in cand.get("frameLabels", [])]
        daily = cand.get("dailyByMajority") or {}
        report["candidates"][key] = {
            "flipRate": round(flip_rate(frame_labels), 4),
            "lag": lag_check(daily, rets_h1),
            "discriminationH1": monthly_discrimination(daily, rets_h1),
            "discriminationH8": monthly_discrimination(daily, rets_h8),
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

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_quality_report.py -v`
Expected: 3 passed

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_quality_report`
Expected: stdout 打出三候选的翻转率/lag/月度区分度表；exit code 0。注意 h1 前向收益覆盖 04-15~09-29（末帧无次日），h8 相应少 1 日。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_quality_report.py tests/research/test_phase_quality_report.py
git commit -m "feat(ranktrend): M1 检验三关——翻转率/滞后 lag/月度 Mann-Whitney 区分度（TDD）"
```

### Task 7: M1 报告与出口判据判定

**Files:**
- Create: `quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-m1-report.md`

- [ ] **Step 1: 汇总三份产物写报告**

读 `data/reports/phase-monitor/` 下三份 JSON，按模板写报告（每节填实际读数，不留占位）：

```markdown
# M1 相位定义报告（填执行日期）

## 1. 候选与读数
（逐候选写实际数字：帧分布 / 翻转率 / lag argmax / 月度区分度表 / 54 笔交易切片 + regime 切片；
  三候选 = sentiment_v1 / sentiment_2b / breadth_v1，另加 trade.regime 口径的交易层直接证据）

## 2. 出口判据判定
- 区分度：（写明哪候选过 p<0.05 或均值差≥2%，方向是否 ≥2 独立月份一致）
- 滞后：（写 argmax 值，是否 ≤3 交易日）
- 结论：（二选一：存在合格划分 → 定相位定义 v1 并冻结；全部不成立 → 实盘体感未被数据支持，
  按设计 §5 M1 失败分支处置，写明备选方向）

## 3. 诚实边界
（多重检验高估 / 54 笔交易层样本薄 / 情绪覆盖自 04-15 / h1 口径=末槽到次日首槽 /
  limitSummary 与 ThemeTrend 拥挤度未进 v1 的原因）
```

- [ ] **Step 2: 若判定"存在合格划分"，冻结相位定义 v1**

在报告 §2 明确：采用哪个候选、阈值、档数（2 或 3），并注明"冻结一个季度，变更=标签全量重打+地图重算"。

- [ ] **Step 3: Commit**

```bash
git add docs/ranktrend-tier-backtest/ranktrend-phase-m1-report.md
git commit -m "docs(ranktrend): M1 相位定义报告——出口判据判定（相位 v1 冻结 / 失败结论）"
```

- [ ] **Step 4: 里程碑门**

M1 出口后：合格 → 向用户汇报并提议立项 M2 计划（writing-plans 另出）；失败 → 向用户汇报失败结论与备选方向。**两者都是计划的正式产出，不擅自重启或改判。**

---

## M2 / M3 里程碑门（本计划范围外，触发条件）

- **M2 立项条件**：M1 判定"存在合格划分"。产出物：分相位读数 harness（切片维度=相位）+ 相位-收益地图（gen7 基线）+ 月度监控脚本。另立 plan 文档。
- **M3 立项条件**：M2 地图落定。产出物：差相位降仓开关 → 好相位放宽 → 卖点按相位重审（吸收卖点课题）→ O8 双强相位收尾，一次一候选。另立 plan 文档。
- **月度监控**：随 M2 定型；M1 期间不跑（M1 自身即覆盖历史全窗）。

## 验证总表（执行完成的定义）

| 项 | 验证 |
|---|---|
| Phase 0 封存 | 三份文档 git log 各一笔；观察池含 sealed 横幅与全部 sealedNote |
| Task 3-6 | 三份专项测试全绿（4+4+3 passed）；三个 CLI 实跑 exit 0 且产物落盘 |
| Task 7 | M1 报告含实际读数与出口判据判定，无 TBD |
| 纪律 | 全程只读（无引擎/config 改动）；每任务独立 commit |
