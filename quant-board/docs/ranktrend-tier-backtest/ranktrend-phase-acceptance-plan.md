# 分相位验收长测计划——实施计划（Phase 0 封存 + M1 相位定义）【修订版 v2，2026-09-30】

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.（注：若本仓无对应技能注册，按项目惯例以主代理串行执行 + 任务间检查点替代，M7。）

**Goal:** 执行旧长测体系封存（观察池/L1/长测文档/SKILLS 四处），并完成 M1 相位定义——用情绪连续评分与市场情绪值两套候选给历史全窗打相位标签，经检验三关（稳定性/滞后性/区分度）出 M1 报告与出口判据判定。

**Architecture:** 封存为纯文档动作；M1 为只读研究链——`phase_labeler`（纯函数标签器，TDD）→ `phase_label_run`（全窗打标落盘）→ `phase_trade_slice`（54 笔 roundTrip 交易按相位切片）→ `phase_quality_report`（帧级+日级前向收益、检验三关），全部走 Mongo 只读 + 本地 frames gzip，不占 8000、不碰引擎与默认值。

**Tech Stack:** Python 3.13（quant-board .venv，scipy 1.14.1 已实测在 venv）、pymongo、pytest；数据源 Mongo `dragon_board_quant`（hotlist_sentiment）+ 本地 `data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz`。

**修订记录（v2，响应审计 ranktrend-phase-acceptance-audit.md）：** C1 测试数据/跳月披露重写；C2 交易口径改 roundTripTrades；C3/C4 编辑锚点修正；I1 滞后检验改对称互相关；I2 pass 加方向；I3 区分度主证据升帧级；I4 rg Expected 修正；I5 数据事实表按三重复测修正（审计 1073/120/7 与本仓 json.load 全量 1071/113/0 不符，分歧注记+复测防线）；I6 新增 SKILLS 封存任务；I7 前视披露+前日标签变体；M1 缺失计数；M2 mannwhitneyu 切 scipy；M3 产物溯源元数据；M5 引用修正；M6 平票用例；M8/M9 注记。三份内嵌代码已在仓库外临时目录真实跑绿后定稿。

**范围裁定（设计 §5 与文首"取代"声明）：** 本计划只覆盖封存 + M1。M2（分相位验收框架/相位-收益地图）与 M3（相位适配）在 M1 出口判定后**另立计划**。

**已锁定的数据事实（2026-09-30 三重实测：导出 stdout + json.load 全量 + Mongo 只读 count；执行时若复测数字变动，以复测为准并停下核对）：**

| 事实 | 值 |
|---|---|
| 帧全窗 | **1071 帧 / 113 交易日**（首帧 2026-04-15；文件名 "20260327" 为数据集窗口参数非实际首帧）。其中 **52 帧为 daily 回填合成**（captureMode=synthesized，donor 元数据在 marketContext.metadata.backfill）——合成帧的 emotionValue/price 与真实槽可比性在 M1 报告披露 |
| 情绪连续分 | Mongo `hotlist_sentiment`，`{datasetId:'dragonboard_live', snapshotType:'half_hour'}`，字段 `emotionScore.score`（0-100，dict 内层），**1184 文档/113 日全覆盖（04-15 起，与帧日集完全重合，有帧无情绪日=∅）**；EOD 文档同带 score。注：1184 为 2026-09-30 时点数（AI_COLLABORATION 记 1182 为重算时点，引用注明时点，M8） |
| 帧级市场情绪 | frames 自带 `marketContext.marketStats.emotionValue`（小数；**嵌套两层**，顶层无 marketStats——Task 5 实跑实测 205/1071 帧有效，其余为 None→unknown，breadth_v1 弱候选如实暴露）；无 slotTime="EOD" 帧（实测 0） |
| 交易层 join 键 | `t6-runs-formal/1-summary.json`：**roundTripTrades=54 笔（与 tradeCount 口径一致）**，带 entryTradingDate/entryTime(ms)/regime/netReturn（实测字段齐）；`trades` 数组 65/61 行为含分片记录的另一口径，不消费 |
| 帧标识 | 帧 dict 顶层 `tradingDate` + `slotTime`（存在非标槽如 09:03/14:31——h1/h8 按 +1/+8 帧序非严格日间隔，报告披露） |

---

## Phase 0：旧体系封存（四个任务，纯文档）

### Task 1: 观察池 YAML 归档结案

**Files:**
- Modify: `quant-board/config/ranktrend-observation-pool.yaml`

- [ ] **Step 1: 确认无代码解析消费**

Run: `cd /d/dragon-board/quant-board && rg -l "observation-pool" backend/ scripts/ tests/`
Expected: **实测 2 处命中（均为文档性引用，放行）**——`tests/research/test_track2_candidates_harness.py`（docstring 提及 O2 baselineNote）、`backend/operations/scan_repool_sample_floor.py`（注释提及路径）。若出现新的解析消费（`yaml.load`/`safe_load`/程序读取该文件路径）才停下向用户报告。

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

### Task 2: L1 台账、长测文档与 §27.9 指针封存注记

**Files:**
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`（文首标题后）
- Modify: `quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`（文首标题后 + §27.9）

- [ ] **Step 1: L1 台账文首加注记（锚点=实际标题）**

在实际标题行 `# RankTrend L1 自由参数定值档案` 之后插入：

```markdown
> **【已封存 2026-09-30】**复核登记职能随旧月度批次体系封存——本文转为**默认值变更史**（§1-§17 即完整历史，不再新增复核章节）。新体系：`ranktrend-phase-acceptance-design.md`。
```

- [ ] **Step 2: 长测文档文首加注记**

在 `# 四维信号长期回测计划与性能优化方案` 标题行之后插入：

```markdown
> **【已封存 2026-09-30】**阶段 0-27 为历史档案，不再新增阶段。后续研究走分相位验收体系：`ranktrend-phase-acceptance-design.md`（M1-M3 + 极简月度监控）；引擎侧默认值基准仍以 `config/ranktrend-anchors.json`（gen-2026-09-30-midlong-x30）为准。
```

- [ ] **Step 3: 修正 §27.9 指针（先确认实际文本再替换）**

Run: `grep -n "B-202611 阶段计划" docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`
Expected: L3564 附近一行含 `**B-202611 阶段计划**：\`ranktrend-b-202611-plan.md\`（同目录）`（注意粗体星号）。

将该片段（含 `**`）替换为：`**B-202611 阶段计划**（当日废弃并删除，git 3ba3c8b3 留档；后继为分相位验收体系 \`ranktrend-phase-acceptance-design.md\`）`。

- [ ] **Step 4: Commit**

```bash
git add docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md
git commit -m "docs(ranktrend): L1 台账与长测文档封存注记（转历史档案，指向分相位新体系）"
```

### Task 3: SKILLS.md 与研究 skill 正文封存同步（I6）

**Files:**
- Modify: `D:\dragon-board\SKILLS.md`（§2.4 ranktrend-signal-research 条目）
- Modify: `D:\dragon-board\skills\ranktrend-signal-research\SKILL.md`（frontmatter description + Overview 触发条件）

- [ ] **Step 1: SKILLS.md §2.4 条目追加封存说明**

在 ranktrend-signal-research 条目描述末尾追加一句（不动其余文字）：

```markdown
**【2026-09-30 体系切换】月度复验批次模式（阶段 0-27 + B-202610 范式）已封存**——判定卡唯一收口/观察池状态机/锚代际推进仪式/月度三件同步废止；现行章程见 quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-acceptance-design.md（分相位验收 M1-M3 + 极简月度监控）。golden 锁基线/参数化不漂移/fail-visible/资源纪律/一次一候选落默认等条款**仍然有效**。
```

- [ ] **Step 2: skill 正文 frontmatter 与触发条件同步**

`skills/ranktrend-signal-research/SKILL.md`：
1. frontmatter `description` 末尾追加：`；2026-09-30 起月度批次模式已封存，现行章程为分相位验收体系（ranktrend-phase-acceptance-design.md），参数化/golden/资源纪律条款仍有效`；
2. 「月度复验批次」触发条件小节开头插入一行引用块：

```markdown
> **【已封存 2026-09-30】**本节批次模式已被分相位验收体系取代（设计文档见 quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-acceptance-design.md）。以下内容保留作历史范式参考；两轨判定语义（Track A/Track B）与全部前置纪律仍适用于新体系内的参数/因子研究。
```

3. 顺带校正：SKILL.md 中"阶段 0-26"表述改为"阶段 0-27"。

- [ ] **Step 3: Commit**

```bash
cd /d/dragon-board && git add SKILLS.md skills/ranktrend-signal-research/SKILL.md
git commit -m "docs(skills): ranktrend 研究流程封存同步——批次模式标注废止，纪律条款保留（体系切换）"
```

---

## M1：相位定义（研究链，只读）

**候选范围注记（对设计 §5 候选清单的落地裁定）**：设计列了四个候选，v1 打标进三个——情绪连续分（sentiment_v1 三档 / sentiment_2b 两档）、帧自带市场情绪值（breadth_v1）；regime 四桶不单独打标，用 trades 自带 `regime` 字段在交易层切片中直接验证（零成本、避免为帧级 regime 重跑 replay）。**limitSummary 与 ThemeTrend 拥挤度不进 v1**：前者服务端现算无历史落档，后者 theme_daily_factors 仅回填 60 日（月度区分度需 ≥2 月）——两者作为 M2 月度监控的增量输入候选，M1 报告诚实边界披露。breadth_v1 为盘点新发现的帧级信号（设计清单外增补，全窗覆盖）。

### Task 4: 相位标签器 phase_labeler（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_labeler.py`
- Test: `quant-board/tests/research/test_phase_labeler.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 相位标签器测试（ranktrend-phase-acceptance-design.md §5 M1）。

纪律：标签本身 as-of（只用当前帧及之前可得数据）；信号缺失 → unknown（fail-visible）。
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


def test_daily_phase_from_frames_majority_tie_and_missing():
    frames = [
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:30", "phase": "defense"},
        {"tradingDate": "2026-10-09", "slotTime": "09:30", "phase": "unknown"},
    ]
    daily = daily_phase_from_frames(frames)
    assert daily["2026-09-30"] == "offense"   # 众数
    assert daily["2026-10-09"] == "unknown"   # 全 unknown → unknown（不伪造）


def test_daily_phase_tie_breaks_conservative():
    """平票（offense 1 : defense 1）取防守侧——宁可少进攻不可漏防守。"""
    frames = [
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "phase": "defense"},
    ]
    assert daily_phase_from_frames(frames)["2026-09-30"] == "defense"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m pytest tests/research/test_phase_labeler.py -v`
Expected: FAIL（ModuleNotFoundError: phase_labeler）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 相位标签器（ranktrend-phase-acceptance-design.md §5 M1）。

候选相位信号 → 帧级/日级相位标签（offense/neutral/defense/unknown）。
纪律：标签计算 as-of（单帧标签只用当前帧信号；日级众数含日末槽，对"日中入场"存在
轻微前视——交易层切片另提供前日标签变体 dailyByPrevDay，M1 报告诚实边界披露）；
缺信号 → unknown（fail-visible 不伪造）；相位定义（阈值/档数）变更 = 标签全量重打。
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

    内化 snapshotType 过滤（非 half_hour 整体排除——同槽多版本以列表后序为准，调用方
    Mongo 查询同样带过滤，双保险）；emotionScore 为 dict（route B，score-v1）或 None。
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


def shift_daily_to_prev(daily: dict[str, str], ordered_days: list[str]) -> dict[str, str]:
    """日级标签前移一日（严格 as-of 变体）：entry 日用前一交易日的日级相位。

    ordered_days = 全窗升序交易日列表（调用方从帧提取），首日无前日 → unknown。
    """
    prev_of: dict[str, str] = {}
    for i, day in enumerate(ordered_days):
        prev_of[day] = daily.get(ordered_days[i - 1], "unknown") if i > 0 else "unknown"
    return prev_of
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_labeler.py -v`
Expected: **5 passed**

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_labeler.py tests/research/test_phase_labeler.py
git commit -m "feat(ranktrend): M1 相位标签器——双候选三档+平票保守+前日变体（TDD，fail-visible）"
```

### Task 5: 全窗打标脚本 phase_label_run

**Files:**
- Create: `quant-board/backend/operations/phase_label_run.py`

- [ ] **Step 1: 实现打标 CLI（读 Mongo + 本地 frames gz，输出含溯源元数据的标签 JSON）**

```python
# -*- coding: utf-8 -*-
"""M1 全窗打标：候选相位定义 × 全窗帧 → 帧级+日级标签 JSON（含溯源元数据，M3）。

用法（quant-board 目录）：
  ./.venv/Scripts/python.exe -m backend.operations.phase_label_run \
      --frames data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz \
      --out data/reports/phase-monitor/phase-labels-v1.json

只读：Mongo hotlist_sentiment（half_hour 口径）+ 本地 frames gzip；不占 8000。
候选定义（v1，M1 检验对象）：
  sentiment_v1 : emotionScore.score，hi=55 / lo=40（三档）
  sentiment_2b : emotionScore.score 两档，hi=50 / lo=50（offense≥50）
  breadth_v1   : marketContext.marketStats.emotionValue，hi=0.005 / lo=-0.005
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.phase_labeler import (
    daily_phase_from_frames,
    load_sentiment_scores,
    phase_from_emotion_value,
    phase_from_sentiment_score,
    shift_daily_to_prev,
)

CANDIDATES = {
    "sentiment_v1": ("sentiment", {"hi": 55.0, "lo": 40.0}),
    "sentiment_2b": ("sentiment", {"hi": 50.0, "lo": 50.0}),
    "breadth_v1": ("emotion_value", {"hi": 0.005, "lo": -0.005}),
}


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 相位打标（只读）")
    parser.add_argument("--frames", required=True, help="本地 frames gzip 路径")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    days = sorted({str(fr.get("tradingDate") or "") for fr in frames if fr.get("tradingDate")})
    print(f"[phase-label] frames={len(frames)} days={len(days)}", file=sys.stderr)

    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    docs = list(db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ))
    frame_scores, eod_scores = load_sentiment_scores(docs)
    missing_days = [d for d in days if not any(k[0] == d for k in frame_scores)]
    print(f"[phase-label] sentiment docs={len(docs)} eod_days={len(eod_scores)} 有帧无情绪日={missing_days}", file=sys.stderr)

    report: dict = {
        "meta": {  # 溯源元数据（M3）：复测对账用
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "gitCommit": _git_commit(),
            "framesFile": Path(args.frames).name,
            "frameCount": len(frames),
            "tradingDays": len(days),
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "sentimentDocCount": len(docs),
            "daysWithoutSentiment": missing_days,
            "synthesizedFrames": sum(1 for fr in frames if fr.get("captureMode") == "synthesized"),
        },
        "candidates": {},
    }
    for key, (source, thr) in CANDIDATES.items():
        labeled = []
        for fr in frames:
            day, slot = str(fr.get("tradingDate") or ""), str(fr.get("slotTime") or "")
            if source == "sentiment":
                phase = phase_from_sentiment_score(frame_scores.get((day, slot)), **thr)
            else:
                mv = ((fr.get("marketContext") or {}).get("marketStats") or {}).get("emotionValue")
                phase = phase_from_emotion_value(mv if isinstance(mv, (int, float)) else None, **thr)
            labeled.append({"tradingDate": day, "slotTime": slot, "phase": phase})
        daily = daily_phase_from_frames(labeled)
        daily_eod = {d: phase_from_sentiment_score(s, **thr) for d, s in eod_scores.items()} \
            if source == "sentiment" else {}
        report["candidates"][key] = {
            "source": source, "thresholds": thr,
            "frameLabels": labeled,
            "dailyByMajority": daily,
            "dailyByPrevDay": shift_daily_to_prev(daily, days),
            "dailyByEod": daily_eod,
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
Expected: stderr 首行 `frames=1071 days=113`；`有帧无情绪日=[]`（2026-09-30 三重复测口径——若复测非空，按数据事实表防线停下核对）；三候选帧分布非全 unknown；meta 含 gitCommit/synthesizedFrames=52。JSON 落盘。

- [ ] **Step 3: Commit**

```bash
git add backend/operations/phase_label_run.py
git commit -m "feat(ranktrend): M1 全窗打标脚本——三候选帧级+日级+前日标签（含溯源元数据）"
```

### Task 6: 交易层相位切片 phase_trade_slice（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_trade_slice.py`
- Test: `quant-board/tests/research/test_phase_trade_slice.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 交易层相位切片测试：54 笔 roundTrip 交易按入场相位 + 入场 regime 双口径切片。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_trade_slice import round_trips_of, slice_trades, wrxpf_of


TRADES = [
    {"entryTradingDate": "2026-05-06", "regime": "strong", "netReturn": 0.10},
    {"entryTradingDate": "2026-05-07", "regime": "strong", "netReturn": -0.05},
    {"entryTradingDate": "2026-07-29", "regime": "retreat", "netReturn": -0.08},
    {"entryTradingDate": "2026-07-30", "regime": "retreat", "netReturn": None},  # 缺失：计数不伪装
]


def test_wrxpf_of_basic_and_missing():
    m = wrxpf_of(TRADES)
    assert m["trades"] == 3            # 只计有效 netReturn
    assert m["missingNetReturn"] == 1  # 缺失显式计数（fail-visible，M1）
    assert m["winRate"] == round(1 / 3, 4)
    assert m["profitFactor"] == round(0.10 / 0.13, 4)  # grossWin 0.10 / grossLoss 0.13
    assert m["wrxpf"] == round((1 / 3) * (0.10 / 0.13), 4)
    assert m["sumNetReturn"] == -0.03


def test_wrxpf_of_empty():
    assert wrxpf_of([])["wrxpf"] is None


def test_round_trips_of_prefers_roundtrip_array():
    summary = {"roundTripTrades": [{"netReturn": 0.1}], "trades": [{"netReturn": 0.2}, {"netReturn": 0.3}]}
    assert len(round_trips_of(summary)) == 1  # 口径=roundTripTrades（54），不用含分片的 trades（65）


def test_slice_trades_by_daily_phase():
    daily = {"2026-05-06": "offense", "2026-05-07": "offense", "2026-07-29": "defense"}
    out = slice_trades(TRADES, daily=daily, phase_key="phase")
    assert out["offense"]["trades"] == 2
    assert out["defense"]["trades"] == 1
    assert out["defense"]["sumNetReturn"] == -0.08


def test_slice_trades_by_regime_field():
    out = slice_trades(TRADES, daily=None, phase_key="regime")
    assert out["strong"]["trades"] == 2
    assert out["retreat"]["trades"] == 1
    assert out["retreat"]["sumNetReturn"] == -0.08
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_trade_slice.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 最小实验：历史 roundTrip 交易按相位切片读数（设计 §5 M1 首步）。

样本口径（C2 裁定）：消费 summary.roundTripTrades（=tradeCount=54，与文档"54 笔"一致）；
summary.trades（65/61 行）含退出分片/强平记录，不消费。
双口径：① 入场日相位（daily 标签 join entryTradingDate；另出前日标签 dailyByPrevDay
严格 as-of 变体）② 入场时引擎 regime（trade.regime 现成字段）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def round_trips_of(summary: dict) -> list[dict]:
    """样本口径唯一入口：roundTripTrades 优先，无则回退 trades（并在读数中注明）。"""
    rt = summary.get("roundTripTrades")
    if isinstance(rt, list) and rt:
        return rt
    return summary.get("trades") or []


def wrxpf_of(trades: list[dict]) -> dict:
    """netReturn 缺失的条目不计入收益统计，missingNetReturn 显式计数（fail-visible）。"""
    rets: list[float] = []
    missing = 0
    for t in trades:
        nr = t.get("netReturn")
        if isinstance(nr, (int, float)):
            rets.append(float(nr))
        else:
            missing += 1
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    win_rate = len(wins) / len(rets) if rets else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    return {
        "trades": len(rets),
        "missingNetReturn": missing,
        "winRate": round(win_rate, 4) if win_rate is not None else None,
        "profitFactor": round(pf, 4) if pf is not None and pf != float("inf") else None,
        "wrxpf": round(win_rate * pf, 4) if (win_rate is not None and pf is not None and pf != float("inf")) else None,
        "sumNetReturn": round(sum(rets), 4),
        "maxSingleLoss": round(min(rets), 4) if rets else None,
    }


def slice_trades(trades: list[dict], daily: dict[str, str] | None, phase_key: str) -> dict:
    """phase_key='phase'（用 daily 标签 join entryTradingDate）或 'regime'（trade 自带字段）。"""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        if phase_key == "phase":
            label = (daily or {}).get(str(t.get("entryTradingDate") or ""), "unknown")
        else:
            label = str(t.get("regime") or "unknown")
        buckets.setdefault(label, []).append(t)
    return {k: wrxpf_of(v) for k, v in sorted(buckets.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 交易层相位切片")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-trade-slice-v1.json")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    trades = round_trips_of(summary)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    report: dict = {
        "tradeCount": len(trades),
        "sampleSource": "roundTripTrades" if summary.get("roundTripTrades") else "trades(fallback)",
        "byCandidate": {},
        "byCandidatePrevDay": {},
        "byRegime": slice_trades(trades, None, "regime"),
    }
    for key, cand in labels.get("candidates", {}).items():
        report["byCandidate"][key] = slice_trades(trades, cand.get("dailyByMajority"), "phase")
        report["byCandidatePrevDay"][key] = slice_trades(trades, cand.get("dailyByPrevDay"), "phase")
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
Expected: **5 passed**

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_trade_slice`
Expected: stdout `"tradeCount": 54`（roundTripTrades 口径）+ 三候选切片（byCandidate/byCandidatePrevDay）+ byRegime 读数，各桶 trades/wrxpf/sumNetReturn/missingNetReturn（若 missingNetReturn>0 如实保留并写入报告）。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_trade_slice.py tests/research/test_phase_trade_slice.py
git commit -m "feat(ranktrend): M1 交易层相位切片——roundTrip 54 笔口径+前日变体+缺失计数（TDD）"
```

### Task 7: 检验三关 phase_quality_report（TDD）

**Files:**
- Create: `quant-board/backend/operations/phase_quality_report.py`
- Test: `quant-board/tests/research/test_phase_quality_report.py`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M1 检验三关测试：翻转率 / 对称互相关滞后 / 帧级+日级区分度（scipy mannwhitneyu）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_quality_report import (
    flip_rate,
    lag_check,
    monthly_discrimination,
)


def test_flip_rate():
    labels = ["offense", "offense", "defense", "defense", "offense", "unknown", "offense"]
    # 6 对相邻转移中，含 unknown 的 2 对不计分母 → 4 对有效，其中 2 对翻转 → 0.5
    rate = flip_rate(labels)
    assert abs(rate - 0.5) < 1e-9


def test_monthly_discrimination_pass_and_direction():
    """两侧各 ≥2 才产行；方向反指的月份 pass 必须 False（I2）；样本不足月进 skipped。"""
    daily = {
        "2026-05-04": "offense", "2026-05-05": "offense", "2026-05-06": "defense", "2026-05-07": "defense",
        "2026-06-01": "offense", "2026-06-02": "offense", "2026-06-03": "defense", "2026-06-04": "defense",
        "2026-07-01": "defense", "2026-07-02": "defense", "2026-07-03": "offense", "2026-07-04": "offense",
        "2026-08-01": "offense",  # 8 月单侧 → skipped
    }
    rets = {
        "2026-05-04": 0.05, "2026-05-05": 0.06, "2026-05-06": -0.05, "2026-05-07": -0.04,
        "2026-06-01": 0.04, "2026-06-02": 0.05, "2026-06-03": -0.06, "2026-06-04": -0.04,
        "2026-07-01": 0.07, "2026-07-02": 0.08, "2026-07-03": -0.05, "2026-07-04": -0.06,  # 7 月方向反指
        "2026-08-01": 0.01,
    }
    out = monthly_discrimination(daily, rets)
    rows = out["months"]
    assert len(rows) == 3                      # 8 月 skipped
    assert out["skippedMonths"] == ["2026-08"]
    assert out["directionConsistentMonths"] == 2  # 5/6 月 offense>defense，7 月反指不计
    may = next(r for r in rows if r["month"] == "2026-05")
    assert may["offenseMean"] > may["defenseMean"] and may["pass"] is True
    july = next(r for r in rows if r["month"] == "2026-07")
    assert july["offenseMean"] < july["defenseMean"] and july["pass"] is False  # 反指拦截


def test_lag_check_semantics():
    """相位领先收益 2 步 → argmax=+2 且 acceptable；相位落后 4 步 → argmax=-4 不合格。"""
    days = [f"2026-06-{d:02d}" for d in range(1, 11)]
    phase_seq = ["offense"] * 5 + ["defense"] * 5  # 块状非周期，避免偶数 lag 歧义
    daily = dict(zip(days, phase_seq))

    # 领先 2 步：ret(t) 由 phase(t-2) 决定 → c(+2)=1 唯一最大
    rets = {days[i]: (0.01 if phase_seq[i - 2] == "offense" else -0.01) for i in range(2, 10)}
    out = lag_check(daily, rets)
    assert out["argmaxLag"] == 2 and out["acceptable"] is True

    # 落后 4 步：ret(t) 由 phase(t+4) 决定 → c(-4)=1 唯一最大，滞后 4>3 不合格
    # （构造纪律：rets 必须覆盖全部天——lag_check 配对要求 phase(t) 与 ret(t+k) 双存在，
    #   覆盖不足会把 c(-4) 截到 n<3 归零，argmax 假移位；尾部天给微噪声防常数列）
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]
    phase_seq = ["offense"] * 6 + ["defense"] * 6
    daily = dict(zip(days, phase_seq))
    rets2 = {}
    for i, d in enumerate(days):
        if i + 4 < len(days):
            rets2[d] = 0.01 if phase_seq[i + 4] == "offense" else -0.01
        else:
            rets2[d] = 0.001 * (1 if i % 2 == 0 else -1)
    out2 = lag_check(daily, rets2)
    assert out2["argmaxLag"] == -4 and out2["acceptable"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./.venv/Scripts/python.exe -m pytest tests/research/test_phase_quality_report.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现**

```python
# -*- coding: utf-8 -*-
"""M1 检验三关（ranktrend-phase-acceptance-design.md §5 M1 出口判据的实现）。

① 稳定性：帧级翻转率（unknown 转移不计分母）。
② 滞后性：对称互相关 lag∈[-5,+5]——c(k)=corr(phase(t), ret(t+k))；argmax>0=相位领先
   收益 k 步（有预测价值，好），argmax<0=相位落后收益（坏，设计判据：落后 ≤3 交易日
   才可跟随）；无正相关（c_max≤0）直接不合格。
③ 区分度：帧级池等权样本为主（~1071 样本，I3），日级为敏感性对照（抑制帧间自相关的
   保守复核）；scipy.stats.mannwhitneyu（tie 校正内置，M2）。
方向纪律（I2）：pass 必须 offenseMean > defenseMean；月度方向一致数自动汇总；
样本不足月进 skippedMonths（fail-visible，不静默）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scipy.stats import mannwhitneyu


def flip_rate(labels: list[str]) -> float:
    """相邻帧标签翻转率（unknown 转移不计分子分母）。"""
    flips = 0
    total = 0
    for a, b in zip(labels, labels[1:]):
        if a == "unknown" or b == "unknown":
            continue
        total += 1
        if a != b:
            flips += 1
    return flips / total if total else 0.0


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


def lag_check(daily: dict[str, str], rets: dict[str, float], max_lag: int = 5) -> dict:
    """对称互相关：c(k)=corr(phase(t), ret(t+k))，k∈[-max_lag,+max_lag]。

    k>0：相位领先收益（预测属性，好）；k<0：相位落后收益（跟随属性差，坏）。
    acceptable = 存在正相关 ∧ argmax ≥ -3（落后不超过 3 步）。
    注：lag 单位为"有效样本步"（跨周末/缺档日有失真，报告披露）。
    """
    days = sorted(daily)
    xs, ys = [], []
    for d0 in days:
        if d0 in rets and daily[d0] in ("offense", "defense"):
            xs.append(1.0 if daily[d0] == "offense" else 0.0)
            ys.append(float(rets[d0]))
    idx = {d: i for i, d in enumerate(days)}
    # 按日索引配对 phase(t) 与 ret(t+k)：k>0 相位领先收益，k<0 相位落后收益
    corr_by_lag: dict[int, float] = {}
    for k in range(-max_lag, max_lag + 1):
        px: list[float] = []
        py: list[float] = []
        for i, d in enumerate(days):
            j = i + k
            if not (0 <= j < len(days)):
                continue
            dj = days[j]
            if d in rets and dj in rets and daily[d] in ("offense", "defense"):
                px.append(1.0 if daily[d] == "offense" else 0.0)
                py.append(float(rets[dj]))
        corr_by_lag[k] = round(_pearson(px, py), 4)
    best = max(corr_by_lag, key=lambda k: corr_by_lag[k])
    c_max = corr_by_lag[best]
    return {"corrByLag": corr_by_lag, "argmaxLag": best, "maxCorr": c_max,
            "acceptable": (c_max > 0) and (best >= -3), "n": len(xs)}


def monthly_discrimination(phase_by_day: dict[str, str], rets: dict[str, float]) -> dict:
    """按自然月：offense vs defense 收益 Mann-Whitney（scipy，双尾）+ 方向判据。

    pass = offenseMean > defenseMean（方向）∧（p<0.05 或 |均值差|≥2%）。
    返回 {months, skippedMonths(两侧不足 2), directionConsistentMonths}。
    """
    by_month: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day, phase in phase_by_day.items():
        r = rets.get(day)
        if r is None or phase not in ("offense", "defense"):
            continue
        by_month[day[:7]][phase].append(float(r))
    rows, skipped, consistent = [], [], 0
    for month in sorted(by_month):
        a, b = by_month[month].get("offense", []), by_month[month].get("defense", [])
        if len(a) < 2 or len(b) < 2:
            skipped.append(month)
            continue
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        if ma > mb:
            consistent += 1
        p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
        rows.append({"month": month, "nOffense": len(a), "nDefense": len(b),
                     "offenseMean": round(ma, 5), "defenseMean": round(mb, 5),
                     "meanDiff": round(ma - mb, 5), "p": round(p, 5),
                     "pass": (ma > mb) and ((p < 0.05) or (abs(ma - mb) >= 0.02))})
    return {"months": rows, "skippedMonths": skipped, "directionConsistentMonths": consistent}


def frame_pool_returns(frames: list[dict], horizon: int) -> dict[int, float]:
    """帧级池等权 h{horizon} 前向收益：帧 i 的持仓池在帧 i+horizon 的价格变化均值。

    返回 {帧下标: 池收益}（按时间排序后下标）；池=该帧 stocks 全体（与交易池不同口径，
    M1 为市场层方向证据，报告披露）。
    """
    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    prices = {i: {str(s.get("code")): float(s["price"]) for s in (fr.get("stocks") or []) if s.get("price")}
              for i, fr in enumerate(ordered)}
    out: dict[int, float] = {}
    for i in range(len(ordered) - horizon):
        base, nxt = prices.get(i, {}), prices.get(i + horizon, {})
        rets = [nxt[c] / p - 1 for c, p in base.items() if c in nxt and p > 0]
        if rets:
            out[i] = sum(rets) / len(rets)
    return out


def daily_forward_returns(frames: list[dict], horizon: int) -> dict[str, float]:
    """日级敏感性对照：每日末槽（排序后该日最后一帧）池等权 h{horizon} 前向收益。"""
    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    per_frame = frame_pool_returns(ordered, horizon)
    last_of_day: dict[str, int] = {}
    for i, fr in enumerate(ordered):
        last_of_day[str(fr.get("tradingDate") or "")] = i
    return {day: per_frame[i] for day, i in last_of_day.items() if i in per_frame}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 检验三关")
    parser.add_argument("--frames", default="data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-quality-v1.json")
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    ordered = sorted(frames, key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    frame_rets_h1 = frame_pool_returns(ordered, 1)
    frame_rets_h8 = frame_pool_returns(ordered, 8)

    report: dict = {"frameCount": len(ordered), "candidates": {}}
    for key, cand in labels.get("candidates", {}).items():
        frame_labels = [x["phase"] for x in cand.get("frameLabels", [])]
        daily = cand.get("dailyByMajority") or {}
        # 帧级区分度（主证据，I3）：标签按 (day,slot) 重排后与排序帧同下标对齐
        # （打标顺序源自帧文件顺序，两处同键稳定排序 → 对齐成立）
        lab_ordered = sorted(cand.get("frameLabels", []),
                             key=lambda x: (x["tradingDate"], x["slotTime"]))
        pseudo_daily: dict[str, str] = {}
        pseudo_rets: dict[str, float] = {}
        for i, ret in frame_rets_h1.items():
            phase = lab_ordered[i]["phase"] if i < len(lab_ordered) else "unknown"
            if phase in ("offense", "defense"):
                k = f"{lab_ordered[i]['tradingDate']}#f{i}"
                pseudo_daily[k] = phase
                pseudo_rets[k] = ret
        frame_disc = monthly_discrimination(pseudo_daily, pseudo_rets)
        daily_rets_h1 = daily_forward_returns(frames, 1)
        daily_rets_h8 = daily_forward_returns(frames, 8)
        report["candidates"][key] = {
            "flipRate": round(flip_rate(frame_labels), 4),
            "lag": lag_check(daily, daily_rets_h1),
            "discriminationFrameH1": frame_disc,
            "discriminationDailyH1": monthly_discrimination(daily, daily_rets_h1),
            "discriminationDailyH8": monthly_discrimination(daily, daily_rets_h8),
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
Expected: **3 passed**

Run: `./.venv/Scripts/python.exe -m backend.operations.phase_quality_report`
Expected: stdout 打出三候选的翻转率/lag（对称 −5..+5）/帧级+日级区分度表（含 skippedMonths 与 directionConsistentMonths）；exit 0。帧级区分度为出口判据主证据（~1071 样本按月分组）；日级为敏感性对照。同日内 ~10 帧收益自相关会使帧级 p 偏乐观——两口径同读、报告披露。

- [ ] **Step 5: Commit**

```bash
git add backend/operations/phase_quality_report.py tests/research/test_phase_quality_report.py
git commit -m "feat(ranktrend): M1 检验三关——对称互相关滞后+帧级主证据区分度+方向判据（TDD）"
```

### Task 8: M1 报告与出口判据判定

**Files:**
- Create: `quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-m1-report.md`

- [ ] **Step 1: 汇总三份产物写报告（每节填实际读数，不留占位）**

```markdown
# M1 相位定义报告（填执行日期）

## 1. 候选与读数
（逐候选写实际数字：帧分布 / 翻转率 / lag 对称互相关表与 argmax / 帧级+日级月度区分度表 /
  54 笔 roundTrip 交易切片（byCandidate / byCandidatePrevDay / byRegime 三表））

## 2. 出口判据判定
- 区分度：（哪候选帧级主证据过 p<0.05 或均值差≥2%，directionConsistentMonths 是否 ≥2，
  日级敏感性是否同向）
- 滞后：（argmaxLag 值与符号语义；落后是否 ≤3 步；maxCorr 是否 >0）
- 结论：（二选一：存在合格划分 → 定相位定义 v1 并冻结；全部不成立 → 实盘体感未被数据
  支持，按设计 §5 M1 失败分支处置，写明备选方向）

## 3. 诚实边界
（多重检验高估 / 54 笔交易层样本薄 / 情绪覆盖自 04-15 且 1184 为时点数 / h1=+1 帧非严格
  次日首槽（非标槽与日界）/ 52 个 daily 回填合成帧可比性 / 帧级收益同日自相关使 p 偏乐观 /
  日级众数标签对日中入场的前视（byCandidatePrevDay 为严格 as-of 对照）/ limitSummary 与
  ThemeTrend 拥挤度未进 v1 的原因）
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

- **M2 立项条件**：M1 判定"存在合格划分"。产出物：分相位读数 harness + 相位-收益地图（gen7 基线）+ 月度监控脚本。另立 plan 文档。**M2 前置核查（M9）**：`evaluate_gate` 实际定义于 `backend/operations/optimize_gate_denoise_parameters.py`（非公共库），复用面立项时核实。
- **M3 立项条件**：M2 地图落定。产出物：差相位降仓开关 → 好相位放宽 → 卖点按相位重审（吸收卖点课题）→ O8 双强相位收尾，一次一候选。另立 plan 文档。
- **月度监控**：随 M2 定型；M1 期间不跑（M1 自身覆盖历史全窗）。

## 验证总表（执行完成的定义）

| 项 | 验证 |
|---|---|
| Phase 0 封存 | 四份文档（观察池/L1/长测/SKILLS+skill）各一笔 commit；观察池含 sealed 横幅与全部 sealedNote |
| Task 4-7 | 三份专项测试全绿（5+5+3 passed）；三个 CLI 实跑 exit 0 且产物落盘（标签 JSON 含溯源 meta） |
| Task 8 | M1 报告含实际读数与出口判据判定，无占位 |
| 纪律 | 全程只读（无引擎/config 改动）；每任务独立 commit |
