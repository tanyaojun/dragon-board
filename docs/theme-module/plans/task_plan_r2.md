# Phase R2 实施计划：rotation_regime 阈值化 + 判定链稳定性定版

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 MainlineScore 日间稳定性三候选（EMA/累计霸榜/滞回）与 rotation_regime 三态划分纯函数（正式落位 `analysis/theme/`），用真实数据完成"稳定性 × 次期收益"双指标对比、regime 逐日序列与阈值敏感性、regime × market_phase 联合分布、引擎口径对照，产出 R2 findings 报告与定版提案。

**Architecture:** 延续 R1 模式——纯函数 TDD（已知答案校验）+ 只读研究 runner（复用 R1 runner 的数据加载函数），不碰生产链路。

**Tech Stack:** Python 3 / pymongo（经 `MongoRepository`）/ pytest。资源纪律同 R1：只读、单进程、本地 JSON 输出。

**设计依据:** `docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md` §5.3/§6.1；R1 findings `2026-09-26-phase-r1-findings.md` §3/§8（稳定性 Jaccard 0.0604~0.0925、修正后的相位假设）。

**计划前置事实（2026-09-26 生产库实测，写码前已验证）：**
- `marketPhase` 真值在 **half_hour 15:00 帧**（窗内 53 帧：cooling 28 / chaos 7 / rising 2 / climax 1 / falling 1 / None 14）；daily 帧的 rotationSummary.marketPhase 恒 unknown（37/43）不可用——联合分布用 half_hour 15:00 口径。
- `rotationSummary.mainLines`（引擎口径主线列表，可为空）与 `mainlineConcentration` 在 half_hour 帧可用；9-10 样例 mainLines=[]（引擎判定当日无主线）。
- 题材级 `rotationState` 六值枚举（cooling/emerging/inflow/mainline/neutral/outflow）仅落 half_hour；15:00 槽约 37 天有值；daily 类型全缺。
- daily sector rows `change` 覆盖 100%（13,433 行）——次期收益原料直接可用。
- R1 runner `load_close_slot_series/_sorted_rows` 可复用（`from backend.operations.diagnose_theme_rotation_r1 import ...`，同目录研究脚本互相 import）。
- 全窗可用 54 天（7-10/7-24 幽灵日无行）；mainline_scores 得分键=entityKey ID，稳定性对比在 ID 空间内自洽。

**数据窗:** 全窗 2026-07-06 ~ 2026-09-24（54 天）；弱势段 2026-09-01 ~ 09-24（18 天）。

**非目标:** limitSummary 覆盖修复（Phase 1 解锁项，另案）；判定链接线 projection；Phase 1 情绪门控；权重矩阵（R1 已证权重不解决稳定性，本计划固定默认权重，权重定版留 R3）。

---

## File Structure

```text
quant-board/
├── backend/analysis/theme/mainline_stability.py      # 新建：稳定性三候选纯函数
├── backend/analysis/theme/rotation/regime.py         # 新建：rotation_regime 三态纯函数
├── backend/operations/diagnose_theme_regime_r2.py    # 新建：R2 只读 runner
├── tests/test_theme_mainline_stability.py            # 新建：三候选已知答案校验
├── tests/test_theme_rotation_regime.py               # 新建：regime 已知答案校验
├── data/reports/theme-r2-regime.json                 # 运行产物（gitignore）
docs/theme-module/
└── 2026-09-26-phase-r2-findings.md                   # 新建：R2 报告 + 定版提案
```

---

### Task 1: 稳定性三候选 `mainline_stability.py`

**Files:**
- Create: `quant-board/backend/analysis/theme/mainline_stability.py`
- Test: `quant-board/tests/test_theme_mainline_stability.py`

- [ ] **Step 1.1: 写失败测试**

创建 `quant-board/tests/test_theme_mainline_stability.py`：

```python
"""MainlineScore 稳定性三候选已知答案校验（Phase R2）。"""

from backend.analysis.theme.mainline_stability import (
    ema_toplists,
    hysteresis_toplists,
    window_toplists,
)


def _two_days():
    return {
        "d1": {"A": 100.0, "B": 50.0},
        "d2": {"A": 0.0, "B": 100.0},
    }


class TestEmaToplists:
    def test_ema_flips_leader_with_lag(self):
        out = ema_toplists(_two_days(), alpha=0.5, k=2)
        # d1: A=100,B=50 → [A,B]；d2: A=50,B=75 → [B,A]（EMA 引入滞后）
        assert out["d1"] == ["A", "B"]
        assert out["d2"] == ["B", "A"]

    def test_first_seen_theme_uses_raw_score(self):
        out = ema_toplists({"d1": {"A": 10.0}, "d2": {"A": 20.0, "B": 15.0}}, alpha=0.5, k=2)
        # d2: A smooth=15, B 首见=15 → 并列，按 sorted 稳定序（A 先入 smooth）
        assert len(out["d2"]) == 2

    def test_none_score_skipped(self):
        out = ema_toplists({"d1": {"A": None, "B": 5.0}}, alpha=0.5, k=2)
        assert out["d1"] == ["B"]


class TestWindowToplists:
    def test_persistence_counting(self):
        scores = {
            "d1": {"A": 30.0, "B": 20.0, "C": 10.0},
            "d2": {"A": 30.0, "B": 20.0, "C": 10.0},
            "d3": {"B": 100.0, "C": 20.0, "A": 5.0},
        }
        out = window_toplists(scores, window=3, broad_k=2, k=2)
        # 近 3 日 Top2 计数：A=2,B=3,C=1 → d3 名单 [B, A]（计数优先，并列/次序按当日分）
        assert out["d3"][0] == "B"
        assert "A" in out["d3"]

    def test_window_truncates_history(self):
        scores = {f"d{i}": {"A": 10.0} for i in range(1, 6)}
        out = window_toplists(scores, window=2, broad_k=1, k=1)
        assert all(v == ["A"] for v in out.values())

    def test_empty_day_yields_empty_list(self):
        out = window_toplists({"d1": {}}, window=3, broad_k=2, k=2)
        assert out["d1"] == []


class TestHysteresisToplists:
    def test_member_survives_dip_within_exit_rank(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0, "D": 10.0},
            "d2": {"B": 90.0, "C": 60.0, "A": 30.0, "D": 10.0},  # A 跌到 rank3（k=3 边界内）
            "d3": {"B": 90.0, "C": 60.0, "D": 30.0, "A": 10.0},  # A 跌到 rank4（>k，<=exit_rank=4）
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        # d3: A rank4 > k=3 但 <= exit_rank=4 → A 仍在滞回名单
        assert "A" in out["d3"]
        assert out["d3"][0] == "B"

    def test_member_exits_beyond_exit_rank(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0},
            "d2": {"B": 90.0, "C": 60.0, "D": 30.0, "E": 20.0, "A": 5.0},  # A rank5 > exit 4
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        assert "A" not in out["d2"]

    def test_newcomer_enters_on_strong_day(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0},
            "d2": {"A": 90.0, "X": 80.0, "B": 60.0, "C": 30.0},  # X rank2 进列
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        assert "X" in out["d2"]
```

- [ ] **Step 1.2: 运行确认失败**

```powershell
cd D:\dragon-board\quant-board
./.venv/Scripts/python.exe -m pytest tests/test_theme_mainline_stability.py -v
```

预期：FAIL（ModuleNotFoundError）。

- [ ] **Step 1.3: 实现**

创建 `quant-board/backend/analysis/theme/mainline_stability.py`：

```python
"""MainlineScore 日间稳定性三候选（Phase R2 研究纯函数）。

R1 实测：单日横截面 percentile 无平滑时 Top3 日间 Jaccard 仅 0.0604~0.0925
（四组权重均然）——稳定性问题在合成方式而非权重。本模块提供三个统一接口
的平滑候选，输入统一为逐日分数 {date: {themeKey: score}}，输出逐日 TopK
名单 {date: [themeKey]}：
  ema_toplists       分数 EMA 平滑后排序（滞后换头）
  window_toplists    近 N 日 TopK 霸榜计数排序（累计确认）
  hysteresis_toplists 双阈值滞回进出（粘性名单，长度可 >k）
fail-visible：缺日/空日输出空名单或按可得数据递推，不伪造、不中断。
研究参数（alpha/window/exit_rank）由 R2 runner 敏感性对比后提案定版。
"""

from __future__ import annotations

from typing import Any


def _top_k(scores: dict[str, Any], k: int) -> list[str]:
    valid = [(t, float(s)) for t, s in scores.items() if s is not None]
    ranked = sorted(valid, key=lambda kv: kv[1], reverse=True)
    return [t for t, _ in ranked[:k]]


def ema_toplists(
    scores_by_day: dict[str, dict[str, Any]], *, alpha: float = 0.5, k: int = 3
) -> dict[str, list[str]]:
    """分数 EMA：smooth_t = alpha*score_t + (1-alpha)*smooth_{t-1}，题材级逐日递推。

    首见题材初值=当日原分；当日缺分的题材沿用昨日 smooth 参与排序。
    """
    smooth: dict[str, float] = {}
    out: dict[str, list[str]] = {}
    for d in sorted(scores_by_day):
        for t, s in scores_by_day[d].items():
            if s is None:
                continue
            prev = smooth.get(t)
            smooth[t] = float(s) if prev is None else alpha * float(s) + (1 - alpha) * prev
        out[d] = _top_k(smooth, k)
    return out


def window_toplists(
    scores_by_day: dict[str, dict[str, Any]],
    *,
    window: int = 5,
    broad_k: int = 10,
    k: int = 3,
) -> dict[str, list[str]]:
    """近 window 日每日 Top(broad_k) 霸榜次数计数，按计数降序（并列按当日分数）取前 k。"""
    days = sorted(scores_by_day)
    daily_tops = [set(_top_k(scores_by_day[d], broad_k)) for d in days]
    out: dict[str, list[str]] = {}
    for i, d in enumerate(days):
        counts: dict[str, int] = {}
        for j in range(max(0, i - window + 1), i + 1):
            for t in daily_tops[j]:
                counts[t] = counts.get(t, 0) + 1
        cur = scores_by_day[d]

        def _sort_key(t: str) -> tuple[int, float]:
            s = cur.get(t)
            return (counts[t], float(s) if s is not None else float("-inf"))

        ranked = sorted(counts, key=_sort_key, reverse=True)
        out[d] = ranked[:k]
    return out


def hysteresis_toplists(
    scores_by_day: dict[str, dict[str, Any]],
    *,
    k: int = 3,
    exit_rank: int = 5,
) -> dict[str, list[str]]:
    """双阈值滞回：新进需当日原始 rank<=k；在列者当日原始 rank>exit_rank 才退出。

    输出为完整滞回名单（长度可 >k），按当日原始 rank 升序。
    """
    out: dict[str, list[str]] = {}
    held: list[str] = []
    for d in sorted(scores_by_day):
        ranked = _top_k(scores_by_day[d], len(scores_by_day[d]))
        rank_of = {t: i + 1 for i, t in enumerate(ranked)}
        held = [t for t in held if rank_of.get(t, 10**9) <= exit_rank]
        for t in ranked[:k]:
            if t not in held:
                held.append(t)
        out[d] = sorted(held, key=lambda t: rank_of.get(t, 10**9))
    return out
```

- [ ] **Step 1.4: 运行确认通过**

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_theme_mainline_stability.py -v
```

预期：9 用例全 PASS。

- [ ] **Step 1.5: Commit**

```powershell
git -C D:\dragon-board add quant-board/backend/analysis/theme/mainline_stability.py quant-board/tests/test_theme_mainline_stability.py
git -C D:\dragon-board commit -m "feat(theme): MainlineScore 稳定性三候选——EMA/累计霸榜/滞回（Phase R2）"
```

---

### Task 2: rotation_regime 三态 `rotation/regime.py`

**Files:**
- Create: `quant-board/backend/analysis/theme/rotation/regime.py`
- Test: `quant-board/tests/test_theme_rotation_regime.py`

- [ ] **Step 2.1: 写失败测试**

创建 `quant-board/tests/test_theme_rotation_regime.py`：

```python
"""rotation_regime 三态划分已知答案校验（Phase R2，设计文档 §5.3）。"""

from backend.analysis.theme.rotation.regime import (
    classify_regime,
    regime_sequence,
    transition_counts,
)


class TestClassifyRegime:
    def test_fast_and_scattered_is_chaotic(self):
        # R1 实测 7-8 月形态：rot 0.89-0.93 / entropy 0.96
        assert classify_regime(0.89, 0.96) == "chaotic"

    def test_slow_and_concentrated_is_concentrated(self):
        # R1 实测 9 月形态：rot 0.45 / entropy 0.84
        assert classify_regime(0.45, 0.84) == "concentrated"

    def test_fast_and_concentrated_is_rotating(self):
        assert classify_regime(0.80, 0.80) == "rotating"

    def test_slow_and_scattered_merged_into_chaotic(self):
        assert classify_regime(0.30, 0.95) == "chaotic"

    def test_boundary_inclusive_on_hi_thresholds(self):
        # rot==rot_hi 记快；entropy==entropy_hi 记散（>= 语义）
        assert classify_regime(0.70, 0.84) == "rotating"
        assert classify_regime(0.45, 0.90) == "chaotic"

    def test_missing_inputs_return_none(self):
        assert classify_regime(None, 0.9) is None
        assert classify_regime(0.5, None) is None


class TestRegimeSequence:
    def test_sequence_and_missing_days(self):
        metrics = {
            "d1": {"rot_speed": 0.9, "entropy": 0.96},
            "d2": {"rot_speed": None, "entropy": 0.9},
            "d3": {"rot_speed": 0.4, "entropy": 0.8},
        }
        seq = regime_sequence(metrics)
        assert seq == {"d1": "chaotic", "d2": None, "d3": "concentrated"}


class TestTransitionCounts:
    def test_transition_matrix_counts(self):
        seq = {"d1": "chaotic", "d2": "chaotic", "d3": "concentrated", "d4": None, "d5": "concentrated"}
        counts = transition_counts(seq)
        assert counts == {("chaotic", "concentrated"): 1}
```

- [ ] **Step 2.2: 运行确认失败**

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_regime.py -v
```

预期：FAIL（ModuleNotFoundError）。

- [ ] **Step 2.3: 实现**

创建 `quant-board/backend/analysis/theme/rotation/regime.py`：

```python
"""rotation_regime 三态划分（Phase R2 研究纯函数，设计文档 §5.3 轮动维）。

两轴双阈值：rot_speed（轮动速度）× entropy（排名熵，滚动窗口频率熵）。
  chaotic      快+散（rot>=rot_hi 且 entropy>=entropy_hi）；慢+散归并于此（无主线语义）
  concentrated 慢+聚（rot<rot_hi 且 entropy<entropy_hi）
  rotating     快+聚（rot>=rot_hi 且 entropy<entropy_hi，主线内快速轮动）
R1 实证锚点：7-8 月 rot 0.89-0.93/entropy 0.96（chaotic 形态）；9 月 rot 0.45/entropy 0.84
（concentrated 形态）。阈值默认为研究初始值，R2 runner 做 3×3 敏感性。
regime 只描述轮动状态本身，不预设好坏；与 market_phase 的联合分布由 runner 输出。
"""

from __future__ import annotations

from typing import Any

REGIME_CHAOTIC = "chaotic"
REGIME_CONCENTRATED = "concentrated"
REGIME_ROTATING = "rotating"

DEFAULT_ROT_HI = 0.70
DEFAULT_ENTROPY_HI = 0.90


def classify_regime(
    rot_speed: float | None,
    entropy: float | None,
    *,
    rot_hi: float = DEFAULT_ROT_HI,
    entropy_hi: float = DEFAULT_ENTROPY_HI,
) -> str | None:
    """单日两轴指标 → 三态标签；任一缺失返回 None（不伪造）。"""
    if rot_speed is None or entropy is None:
        return None
    fast = rot_speed >= rot_hi
    scattered = entropy >= entropy_hi
    if fast and scattered:
        return REGIME_CHAOTIC
    if not fast and not scattered:
        return REGIME_CONCENTRATED
    if fast:
        return REGIME_ROTATING
    return REGIME_CHAOTIC


def regime_sequence(
    daily_metrics: dict[str, dict[str, Any]],
    *,
    rot_hi: float = DEFAULT_ROT_HI,
    entropy_hi: float = DEFAULT_ENTROPY_HI,
) -> dict[str, str | None]:
    """逐日三指标 {date: {rot_speed, entropy}} → {date: regime|None}。"""
    return {
        d: classify_regime(m.get("rot_speed"), m.get("entropy"), rot_hi=rot_hi, entropy_hi=entropy_hi)
        for d, m in daily_metrics.items()
    }


def transition_counts(seq: dict[str, str | None]) -> dict[tuple[str, str], int]:
    """相邻可计算日的态转移计数（None 日断开不计）。键按字典序输出。"""
    days = sorted(seq)
    counts: dict[tuple[str, str], int] = {}
    prev: str | None = None
    for d in days:
        cur = seq[d]
        if cur is None:
            prev = None
            continue
        if prev is not None and prev != cur:
            counts[(prev, cur)] = counts.get((prev, cur), 0) + 1
        prev = cur
    return dict(sorted(counts.items()))
```

- [ ] **Step 2.4: 运行确认通过**

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_regime.py tests/test_theme_mainline_stability.py -v
```

预期：17 用例全 PASS。

- [ ] **Step 2.5: Commit**

```powershell
git -C D:\dragon-board add quant-board/backend/analysis/theme/rotation/regime.py quant-board/tests/test_theme_rotation_regime.py
git -C D:\dragon-board commit -m "feat(theme): rotation_regime 三态划分——rot×entropy 双轴阈值（Phase R2）"
```

---

### Task 3: R2 runner `diagnose_theme_regime_r2.py`

**Files:**
- Create: `quant-board/backend/operations/diagnose_theme_regime_r2.py`

- [ ] **Step 3.1: 实现 runner**

创建 `quant-board/backend/operations/diagnose_theme_regime_r2.py`：

```python
"""Phase R2：rotation_regime 阈值化 + 判定链稳定性双指标定版实证（只读，不写库）。

① 稳定性 × 次期收益双指标：无平滑 + EMA/累计/滞回三候选（默认权重），
   各配置 Top3 日间 Jaccard、Top1 切换率、Top3 组合 T+1 超额收益均值与胜率
② rotation_regime 逐日序列（rot 近 5 日均值 × entropy 近 10 日频率熵滚动）：
   默认阈值 + 3×3 阈值敏感性（各态天数分布与转移次数）
③ regime × market_phase 联合分布（half_hour 15:00 帧 rotationSummary.marketPhase）
④ 引擎口径对照：half_hour 15:00 帧 rotationSummary.mainLines 空值率、
   rotationState=mainline 题材集与判定链 Top3 的日间重合
⑤ 抖动率按月分解（Top1 切换率 / Top3 Jaccard，无平滑 vs 最优平滑配置）

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_regime_r2
      [--start 2026-07-06] [--end 2026-09-24]
      [--out data/reports/theme-r2-regime.json]

资源纪律：只读、无 optimization API、单进程本地计算；探索性描述统计，
样本 54 天，非正式判定。
fail-visible：缺日/缺帧/缺字段如实打标（None/insufficient），不伪造 0，不中断。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

from backend.analysis.theme.mainline_assignment import mainline_scores
from backend.analysis.theme.mainline_stability import (
    ema_toplists,
    hysteresis_toplists,
    window_toplists,
)
from backend.analysis.theme.rotation.measures import rank_entropy, rotation_speed
from backend.analysis.theme.rotation.regime import regime_sequence, transition_counts
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.diagnose_theme_rotation_r1 import (
    DATASET_ID,
    TOP_N,
    _sorted_rows,
    load_close_slot_series,
)

ENTROPY_WINDOW = 10   # 排名熵滚动窗口（交易日）
ROT_WINDOW = 5        # 轮动速度滚动均值窗口
REGIME_GRID = {
    "entropy_hi": [0.85, 0.90, 0.95],
    "rot_hi": [0.60, 0.70, 0.80],
}
SMOOTH_CONFIGS = {
    "none": None,
    "ema_a05": {"kind": "ema", "alpha": 0.5},
    "window_n5": {"kind": "window", "window": 5, "broad_k": TOP_N},
    "hysteresis_k3_exit5": {"kind": "hysteresis", "k": 3, "exit_rank": 5},
}


def build_score_series(series: dict[str, Any]) -> dict[str, dict[str, float]]:
    """逐日收盘槽 → {date: {entityKey: MainlineScore}}（默认权重；insufficient 日 = {}）。"""
    return {
        d: {
            k: v["score"]
            for k, v in mainline_scores(info["rows"]).items()
            if v.get("score") is not None
        }
        if info["status"] == "ok"
        else {}
        for d, info in series["series"].items()
    }


def apply_smooth(
    scores_by_day: dict[str, dict[str, float]], config: dict[str, Any] | None
) -> dict[str, list[str]]:
    if config is None:
        return {d: sorted(scores_by_day[d], key=lambda t: scores_by_day[d][t], reverse=True)[:3]
                for d in scores_by_day}
    kind = config["kind"]
    if kind == "ema":
        return ema_toplists(scores_by_day, alpha=config["alpha"], k=3)
    if kind == "window":
        return window_toplists(scores_by_day, window=config["window"], broad_k=config["broad_k"], k=3)
    if kind == "hysteresis":
        return hysteresis_toplists(scores_by_day, k=config["k"], exit_rank=config["exit_rank"])
    raise ValueError(f"unknown smooth kind: {kind}")


def top3_jaccard_and_switch(toplists: dict[str, list[str]]) -> dict[str, Any]:
    days = sorted(toplists)
    jac, switches, comparable = [], 0, 0
    prev_top1 = None
    for a, b in zip(days, days[1:]):
        sa, sb = set(toplists[a]), set(toplists[b])
        union = sa | sb
        if union:
            jac.append(1 - len(sa & sb) / len(union))
        if sb:
            comparable += 1
            cur = toplists[b][0]
            if cur != prev_top1:
                switches += 1
            prev_top1 = cur
    return {
        "top3_jaccard_mean": round(fmean(jac), 4) if jac else None,
        "top1_switch_rate": round(switches / comparable, 4) if comparable else None,
        "n_transitions": len(jac),
    }


def next_day_excess(
    toplists: dict[str, list[str]],
    scores_by_day: dict[str, dict[str, float]],
    change_by_day: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Top3 组合 T+1 等权 change 超额（相对全题材均值）；T 日名单用 T+1 日收益评估。"""
    days = sorted(toplists)
    excess: list[float] = []
    for i, d in enumerate(days[:-1]):
        nxt = days[i + 1]
        chg = change_by_day.get(nxt) or {}
        picks = [t for t in toplists[d] if t in chg]
        if not picks or not chg:
            continue
        pick_mean = fmean(chg[t] for t in picks)
        all_mean = fmean(chg.values())
        excess.append(pick_mean - all_mean)
    if not excess:
        return {"status": "insufficient", "reason": "no_evaluable_days", "n": 0}
    return {
        "status": "ok",
        "n": len(excess),
        "mean_excess": round(fmean(excess), 4),
        "win_rate": round(sum(1 for x in excess if x > 0) / len(excess), 4),
        "max": round(max(excess), 4),
        "min": round(min(excess), 4),
    }


def build_change_by_day(series: dict[str, Any]) -> dict[str, dict[str, float]]:
    """每日 {entityKey: change}（收盘槽横截面，fail-visible：缺 change 的行跳过）。"""
    out: dict[str, dict[str, float]] = {}
    for d, info in series["series"].items():
        if info["status"] != "ok":
            continue
        chg = {
            str(r.get("entityKey")): float(r["change"])
            for r in info["rows"]
            if isinstance(r.get("change"), (int, float))
        }
        if chg:
            out[d] = chg
    return out


def rolling_daily_metrics(
    series: dict[str, Any],
    scores_by_day: dict[str, dict[str, float]],
    toplists: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """regime 输入：rot=近 ROT_WINDOW 日 Jaccard 均值；entropy=近 ENTROPY_WINDOW 日霸榜频率熵。"""
    days = sorted(series["series"])
    daily_rot: dict[str, float | None] = {}
    for a, b in zip(days, days[1:]):
        sa = set(toplists.get(a) or [])
        sb = set(toplists.get(b) or [])
        union = sa | sb
        daily_rot[b] = (1 - len(sa & sb) / len(union)) if union else None
    metrics: dict[str, dict[str, Any]] = {}
    for i, d in enumerate(days):
        lo_r = max(0, i - ROT_WINDOW + 1)
        rot_vals = [daily_rot[x] for x in days[lo_r : i + 1] if daily_rot.get(x) is not None]
        lo_e = max(0, i - ENTROPY_WINDOW + 1)
        counts: dict[str, int] = {}
        for x in days[lo_e : i + 1]:
            for t in toplists.get(x) or []:
                counts[t] = counts.get(t, 0) + 1
        ent = rank_entropy(counts)
        metrics[d] = {
            "rot_speed": round(fmean(rot_vals), 4) if rot_vals else None,
            "entropy": ent.get("normalized"),
        }
    return metrics


def market_phase_alignment(
    repo: MongoRepository, start: str, end: str, regime_seq: dict[str, str | None]
) -> dict[str, Any]:
    """regime × marketPhase 联合计数（half_hour 15:00 帧 rotationSummary.marketPhase）。"""
    joint: dict[str, dict[str, int]] = {}
    mainlines_empty = 0
    mainlines_total = 0
    for doc in repo.db["snapshot_frames"].find(
        {
            "tradingDate": {"$gte": start, "$lte": end},
            "slotTime": "15:00",
            "type": "half_hour",
            "datasetId": DATASET_ID,
        },
        {"tradingDate": 1, "rotationSummary.marketPhase": 1, "rotationSummary.mainLines": 1},
    ):
        d = str(doc.get("tradingDate"))
        rs = doc.get("rotationSummary") or {}
        phase = rs.get("marketPhase")
        ml = rs.get("mainLines")
        reg = regime_seq.get(d)
        if reg is not None:
            bucket = joint.setdefault(reg, {})
            bucket[str(phase)] = bucket.get(str(phase), 0) + 1
        if ml is not None:
            mainlines_total += 1
            if not ml:
                mainlines_empty += 1
    return {
        "joint_regime_x_phase": joint,
        "mainlines_empty_ratio": round(mainlines_empty / mainlines_total, 4) if mainlines_total else None,
        "mainlines_total": mainlines_total,
    }


def engine_mainline_overlap(
    repo: MongoRepository, start: str, end: str, toplists: dict[str, list[str]]
) -> dict[str, Any]:
    """引擎口径对照：half_hour 15:00 sector rows rotationState=mainline 题材集 vs 判定链 Top3。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end, entity_type="hot_theme",
        snapshot_type="half_hour", sort="asc",
    )
    by_day: dict[str, set[str]] = {}
    for r in res["rows"]:
        if str(r.get("slotTime")) != "15:00" or r.get("rotationState") != "mainline":
            continue
        k = r.get("entityKey")
        if k is not None:
            by_day.setdefault(str(r.get("tradingDate")), set()).add(str(k))
    overlaps: list[float] = []
    for d, engine_set in sorted(by_day.items()):
        ours = set(toplists.get(d) or [])
        if not ours:
            continue
        overlaps.append(len(engine_set & ours) / max(len(engine_set | ours), 1))
    return {
        "engine_mainline_days": len(by_day),
        "overlap_jaccard_mean": round(fmean(overlaps), 4) if overlaps else None,
        "n_compared": len(overlaps),
    }


def monthly_jitter(
    toplists: dict[str, list[str]], start: str, end: str
) -> dict[str, dict[str, Any]]:
    out = {}
    for month, (a, b) in {
        "2026-07": ("2026-07-06", "2026-07-31"),
        "2026-08": ("2026-08-01", "2026-08-31"),
        "2026-09": ("2026-09-01", "2026-09-24"),
    }.items():
        if end < a or start > b:
            continue
        sub = {d: v for d, v in toplists.items() if a <= d <= b}
        if sub:
            out[month] = top3_jaccard_and_switch(sub)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-r2-regime.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    series = load_close_slot_series(repo, args.start, args.end)
    if series["status"] != "ok":
        print(json.dumps(series, ensure_ascii=False, indent=2))
        return 2
    scores_by_day = build_score_series(series)
    change_by_day = build_change_by_day(series)

    stability = {}
    toplists_by_cfg = {}
    for name, cfg in SMOOTH_CONFIGS.items():
        toplists = apply_smooth(scores_by_day, cfg)
        toplists_by_cfg[name] = toplists
        stability[name] = {
            **top3_jaccard_and_switch(toplists),
            "next_day_excess": next_day_excess(toplists, scores_by_day, change_by_day),
        }

    # regime：用默认配置（none）名单计算滚动三指标；平滑对 regime 的影响留 R3
    metrics = rolling_daily_metrics(series, scores_by_day, toplists_by_cfg["none"])
    regime_seq = regime_sequence(metrics)
    regime_days: dict[str, int] = {}
    for v in regime_seq.values():
        if v is not None:
            regime_days[v] = regime_days.get(v, 0) + 1
    threshold_sensitivity = []
    for eh in REGIME_GRID["entropy_hi"]:
        for rh in REGIME_GRID["rot_hi"]:
            seq = regime_sequence(metrics, rot_hi=rh, entropy_hi=eh)
            dist: dict[str, int] = {}
            for v in seq.values():
                if v is not None:
                    dist[v] = dist.get(v, 0) + 1
            threshold_sensitivity.append({
                "entropy_hi": eh, "rot_hi": rh, "days": dist,
                "transitions": sum(transition_counts(seq).values()),
            })

    report = {
        "window": {"start": args.start, "end": args.end},
        "stability_vs_excess": stability,
        "regime_sequence": regime_seq,
        "regime_days_default": regime_days,
        "regime_transitions_default": transition_counts(regime_seq),
        "threshold_sensitivity": threshold_sensitivity,
        "market_phase_alignment": market_phase_alignment(repo, args.start, args.end, regime_seq),
        "engine_mainline_overlap": engine_mainline_overlap(repo, args.start, args.end, toplists_by_cfg["none"]),
        "monthly_jitter_none": monthly_jitter(toplists_by_cfg["none"], args.start, args.end),
        "monthly_jitter_best_smooth": monthly_jitter(toplists_by_cfg["hysteresis_k3_exit5"], args.start, args.end),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, s in stability.items():
        print(f"[{name}] {s['top3_jaccard_mean']} switch={s['top1_switch_rate']} excess={s['next_day_excess'].get('mean_excess')} win={s['next_day_excess'].get('win_rate')}")
    print(f"[regime] days={regime_days} transitions={report['regime_transitions_default']}")
    print(f"report -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3.2: 验证**

```powershell
./.venv/Scripts/python.exe -c "import backend.operations.diagnose_theme_regime_r2 as m; print('import ok')"
```

加合成数据冒烟（内联）：`apply_smooth` 三配置在两天合成分数上的行为、`next_day_excess` 构造两天 change 的手算超额、`rolling_daily_metrics` 小样窗口。

- [ ] **Step 3.3: Commit**

```powershell
git -C D:\dragon-board add quant-board/backend/operations/diagnose_theme_regime_r2.py
git -C D:\dragon-board commit -m "feat(theme): Phase R2 regime 阈值化与稳定性双指标 runner（只读）"
```

---

### Task 4: 真实数据运行 + 核对

- [ ] **Step 4.1: 确认 MongoDB 在线后运行**

```powershell
./.venv/Scripts/python.exe -m backend.operations.diagnose_theme_regime_r2
```

预期：退出码 0，输出 4 行稳定性摘要 + regime 分布 + 报告路径。

- [ ] **Step 4.2: 核对清单（对照已知事实）**

- `stability_vs_excess` 4 配置齐全；`none` 的 top3_jaccard_mean 应接近 R1 的 0.09 量级（口径差异：R1 用权重 4 组 Top10 单日 Jaccard 均值，此处 Top3 单日）
- 平滑配置的 jaccard 应普遍高于 none（否则平滑失效，需查实现）
- `next_day_excess.status` 应为 ok 且 n≈50 上下；mean_excess 正负如实记录，**不得以正负判定配置优劣之外的含义**
- `regime_days_default` 三态合计 = 可计算天数（54 - 首日窗口不足）；chaotic 集中在 7-8 月、concentrated 集中在 9 月（与 R1 分月分解一致）
- `threshold_sensitivity` 9 组；极端阈值组（0.60/0.95 与 0.80/0.85）的态分布应显著不同（敏感性存在性验证）
- `market_phase_alignment.joint_regime_x_phase` 中 cooling 应主要落在 concentrated（若否，如实记录并讨论）
- `engine_mainline_overlap.engine_mainline_days` ≈ 37（rotationState 15:00 half_hour 覆盖）；jaccard 如实记录
- `monthly_jitter_none` 三月齐全，8 月 top1_switch_rate 最高（R1 已证 =1.0）

- [ ] **Step 4.3: 异常处置**

- 任何 KeyError/TypeError：先查 series/frames 实际字段（`type:"daily"` vs half_hour 的 rotationSummary 结构差异），修复 runner 后重跑；不得伪造数据。
- 若 `engine_mainline_overlap` 为空（rotationState 无 mainline 值的天数不足）：输出 insufficient 说明，不阻断其余统计。

---

### Task 5: R2 findings 报告 + 定版提案 + 提交

**Files:**
- Create: `docs/theme-module/2026-09-26-phase-r2-findings.md`

- [ ] **Step 5.1: 撰写报告（数据来自 Task 4 JSON）**

结构：①稳定性 × 次期收益四配置对照表与定版建议（一次一候选：建议配置 + 理由 + 观察项）②regime 三态逐日序列与默认阈值下的分布、转移矩阵、3×3 敏感性结论（阈值是否稳健）③regime × market_phase 联合分布（验证/修正 R1 的相位假设："快轮动↔活跃、慢轮动+集中↔退潮"）④引擎口径对照（mainLines 空值率、mainline 重合度）⑤抖动率按月分解（none vs 最优平滑）⑥局限与 Phase 1/R3 输入。

- [ ] **Step 5.2: Commit**

```powershell
git -C D:\dragon-board add docs/theme-module/2026-09-26-phase-r2-findings.md
git -C D:\dragon-board commit -m "docs(theme): Phase R2 实证报告——regime 阈值化/稳定性定版提案/联合分布"
```

---

## Self-Review 记录

- **Spec 覆盖**：findings §8 四项输入——①稳定性三候选+双指标（Task 1+3）②regime 阈值化+3×3 敏感性（Task 2+3）③mainline 抖动率正式量化（Task 3 monthly_jitter + engine overlap）④market_phase 联合分布（Task 3，half_hour 口径修正）全部有承载；limitSummary 修复在非目标声明（Phase 1 解锁项）。
- **无占位符**：全部代码完整；接口事实（marketPhase half_hour 口径、rotationState 枚举、change 100%）实测固化于计划头部。
- **类型一致性**：`apply_smooth` 统一返回 {date: [themeKey]}，Task 3 各消费函数一致；regime 序列值域 {chaotic, concentrated, rotating, None} 与测试一致；`top3_jaccard_and_switch` 返回键被 stability/monthly_jitter 共用。
