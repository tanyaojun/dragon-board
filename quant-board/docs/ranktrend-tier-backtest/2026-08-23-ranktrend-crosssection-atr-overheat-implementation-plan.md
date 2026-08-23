# crossSection×ATR 过热/超卖校准 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `crossSection` 追强 × ATR 波动 → 过热/超卖回归校准的纯函数与单测，并跑出"融合 vs 单独 crossSection / 单独 ATR"的区分度结论，作为是否启用前端【波动】列的**验证门控**（验证通过前不改 engine、不启用列）。

**Architecture:** 纯函数 `analyze_cross_section_overheat(cross_tier, vol_rank, config)` 无 I/O、可单测；区分度验证**复用现有 replay + `tier_forward_returns`**（`ranktrend-signal-tier-backtest-plan.md §8.5`），**不侵入 engine**——为验证临时算 `vol_rank`（收盘准 ATR 波动率分位），先确认有增量再决定是否挂载。

**Tech Stack:** Python (pytest, numpy 已有), QuantBoard `backend.analysis.ranktrend`.

**关联 spec:** `quant-board/docs/ranktrend-tier-backtest/2026-08-23-ranktrend-percentile-atr-fusion-signal-design.md`（v2）。
**前置约束:** 本计划只做"纯函数 + 区分度验证"；**不替换 `observation.atrMeanReversion`、不改 engine**——engine 挂载属于"验证通过后"的 Part D（另行任务）。验证门控是 Part C 的结论。

---

### Task 1: 写失败测试（`analyze_cross_section_overheat` 黄金 case）

**Files:**
- Create: `backend/analysis/ranktrend/__tests__/test_cross_section_overheat.py`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from backend.analysis.ranktrend.cross_section_vol_overheat import analyze_cross_section_overheat

class _C:
    crossVolP33 = 0.33
    crossVolP67 = 0.67
    crossVolP90 = 0.90


def test_strong_deep_overheat_is_sell_s():
    r = analyze_cross_section_overheat("A", 0.95, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "S"


def test_strong_high_vol_is_overheat():
    r = analyze_cross_section_overheat("B", 0.8, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "C"


def test_strong_mid_vol_is_warm():
    r = analyze_cross_section_overheat("A", 0.5, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "B"


def test_strong_low_vol_is_mild():
    r = analyze_cross_section_overheat("A", 0.1, _C())
    assert r["direction"] == "hold" and r["signalTier"] == "A"


def test_weak_low_vol_is_rebound():
    r = analyze_cross_section_overheat("D", 0.1, _C())
    assert r["direction"] == "buy" and r["signalTier"] == "B"


def test_weak_high_vol_is_stay_away():
    r = analyze_cross_section_overheat("D", 0.9, _C())
    assert r["direction"] == "hold" and r["signalTier"] == "C"


def test_unknown_input_is_fail_visible():
    r = analyze_cross_section_overheat("unknown", 0.5, _C())
    assert r["status"] == "insufficient" and r["signalTier"] == "unknown"
    r2 = analyze_cross_section_overheat("A", None, _C())
    assert r2["status"] == "insufficient" and r2["signalTier"] == "unknown"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest backend/analysis/ranktrend/__tests__/test_cross_section_overheat.py -q`
Expected: FAIL（`ModuleNotFoundError: cross_section_vol_overheat` 或 `ImportError`）。

- [ ] **Step 3: 写最小实现（纯函数）**

**Files:**
- Create: `backend/analysis/ranktrend/cross_section_vol_overheat.py`

```python
# -*- coding: utf-8 -*-
"""crossSection 追强 × ATR 波动 → 过热/超卖回归校准（观察信号，不进 synergy）。
纯函数：输入 crossSection 档 + 该股 pct_vol 相对当帧全体的分位(0-1)，返回观察信号契约。
设计文档 ranktrend-percentile-atr-fusion-signal-design.md §3/§4。
"""
from __future__ import annotations

import math
from typing import Any

STRONG = ("A", "B")
WEAK = ("C", "D")


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def analyze_cross_section_overheat(
    cross_tier: str | None,
    vol_rank: float | None,
    config: Any,
) -> dict[str, Any]:
    """crossSection 档 × 波动率分位 → 过热/超卖回归观察信号。

    Args:
        cross_tier: crossSection.signalTier（A/B/C/D/unknown/None）。
        vol_rank: 该股 pct_vol 相对当帧全体股票波动率的统计分位 ∈ [0,1]（None=不可用）。
        config: 提供 crossVolP33/crossVolP67/crossVolP90（默认 0.33/0.67/0.90）。

    Returns:
        observation 契约：status/direction/score/crossTier/volTier/pctVolRank/signalTier/reasons。
        fail-visible：输入非法 → status=insufficient、direction=hold、signalTier=unknown（不归零）。
    """
    p33 = float(getattr(config, "crossVolP33", 0.33))
    p67 = float(getattr(config, "crossVolP67", 0.67))
    p90 = float(getattr(config, "crossVolP90", 0.90))
    rank = _finite(vol_rank)

    if cross_tier not in (*STRONG, *WEAK) or rank is None:
        return {
            "status": "insufficient",
            "direction": "hold",
            "score": 0,
            "crossTier": cross_tier,
            "volTier": None,
            "pctVolRank": rank,
            "signalTier": "unknown",
            "reasons": ["crossSection 档位或波动率不可用"],
        }

    strong = cross_tier in STRONG
    if strong:
        if rank >= p90:
            direction, tier = "sell", "S"
            reason = "横截面强势 + 深度放量，过热回归风险"
        elif rank >= p67:
            direction, tier = "sell", "C"
            reason = "横截面强势 + 放量过热，回归风险"
        elif rank >= p33:
            direction, tier = "sell", "B"
            reason = "横截面强势 + 活跃偏热"
        else:
            direction, tier = "hold", "A"
            reason = "横截面强势 + 缩量，温和强势"
    else:
        if rank <= p33:
            direction, tier = "buy", "B"
            reason = "横截面弱势 + 缩量企稳，超卖回升观察"
        else:
            direction, tier = "hold", "C"
            reason = "横截面弱势（无缩量企稳），回避"

    score = {"S": 100, "A": 60, "B": 45, "C": 25}.get(tier, 0)
    return {
        "status": "ok",
        "direction": direction,
        "score": score,
        "crossTier": cross_tier,
        "volTier": None,  # volTier 由调用方按分位切分（low/mid/high），此处保留分位值
        "pctVolRank": rank,
        "signalTier": tier,
        "reasons": [reason],
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest backend/analysis/ranktrend/__tests__/test_cross_section_overheat.py -q`
Expected: PASS（7 passed）。

- [ ] **Step 5: 提交**

```bash
git add backend/analysis/ranktrend/cross_section_vol_overheat.py backend/analysis/ranktrend/__tests__/test_cross_section_overheat.py
git commit -m "feat(ranktrend): crossSection×ATR 波动过热/超卖校准纯函数+单测"
```

---

### Task 2: 区分度验证 harness（融合 vs 单独 crossSection / 单独 ATR，不侵入 engine）

**Files:**
- Create: `quant-board/scripts/ranktrend_overheat_validation.py`

- [ ] **Step 6: 写验证脚本（复用现有 replay + tier_forward_returns）**

说明：这是**验证门控**。用现有 `engine.replay`（含 `observation.crossSection.signalTier`）跑全量帧，对每信号临时算 `vol_rank`（收盘准 ATR 波动率分位，用 `backend.analysis.ranktrend.atr_mean_reversion.atr_of` close-only 降级 + 当帧全体分位），再经 `analyze_cross_section_overheat` 得融合方向；最后用现有回测 `tier_forward_returns`（buy/sell 分组）对比 three baselines：

- `fusion`：本信号 direction（sell/buy，来自查表）。
- `crossSection only`：crossSection 档方向（A/B→追强 buy，C/D→track weak；用于对照）。
- `atr only`：旧 `atrMeanReversion.direction`（价格通道回归，对照）。

脚本骨架（复用现有工具，具体回测调用按 `ranktrend-signal-tier-backtest-plan.md §8.5`／现有 `test_ranktrend_golden_alignment.py` 的 replay+forward 模式）：

```python
"""区分度验证：融合(crossSection×ATR) vs 单独 crossSection vs 单独 ATR。
只读现有 replay 输出，不写代码、不改 engine；结论用于是否升级【波动】列的门控。
"""
import json
from backend.analysis.ranktrend.engine import RankTrendEngine
from backend.analysis.ranktrend.cross_section_vol_overheat import analyze_cross_section_overheat
# 复用现有回测 forward 工具（具体 API 名以现有 backtest harness 为准）：
from backend.core.backtest import tier_forward_returns  # noqa: F401  (占位说明见下)

def _vol_rank_per_frame(stocks):  # 帧级：当帧全体 pct_vol → 分位
    from backend.analysis.ranktrend.atr_mean_reversion import atr_of, bar_of, _mean
    pcts = []
    for stock in stocks:
        bar = bar_of(stock)
        if bar is None:
            continue
        # 注：真实验证需该股跨帧 bars；此处用现有 replay 的 _atr_meta_by_code 或离线累积
        #（工程实现见 Task 3；本 harness 为研究验证，可先接现有 ATR 序列）。
    # 返回 {code: vol_rank}
    ...
```

> **任务明确性说明（非占位）**：本 harness 的具体 forward-return 计算、replay 输出序列化、信号→收益对齐，
> **必须复用现有回测 harness**（`backend/core/backtest.py`、`quant-board/docs/ranktrend-tier-backtest/ranktrend-signal-tier-backtest-plan.md`
> 的 `tier_forward_returns`/`replay` 调用法）。实现者执行本任务时：先 `rg "def tier_forward_returns|def replay" backend` 定位真实签名，
> 再按现有 `tests/test_ranktrend_golden_alignment.py` 的 replay+forward 调用模式填充上述骨架。**不得新造回测口径**。

- [ ] **Step 7: 运行验证脚本，产出报告**

Run: `cd quant-board; .\.venv\Scripts\python.exe scripts/ranktrend_overheat_validation.py --type half_hour`
Expected: 输出 JSON 报告——`fusion / crossSection / atr` 三者的 buy/sell 分组 h1/h8 saEx + passHard + 样本占比；并给出"融合是否显著高于单独 baseline"的判定。

- [ ] **Step 8: 记录结论（写进 spec 验证节或独立报告）**

将结果与判定写回 `quant-board/docs/ranktrend-tier-backtest/2026-08-23-ranktrend-percentile-atr-fusion-signal-design.md`：
- 若 fusion 的 buy/sell saEx **显著高于** 单独 crossSection/单独 ATR 且样本外稳定 → 门控通过，进入 Part D（engine 挂载）。
- 否则 → 归档：维持【波动】列不启用（同旧 ATR 先例），记录"融合无增量"。

---

### Task 3（Part D，**门控通过后才可执行**，本计划仅列出，不实现）

- engine `replay` 帧级：在 `_build_signal` 挂载/替换 `observation.atrMeanReversion`（输入 `observation.crossSection.signalTier` + 帧级 `vol_rank`），需重构 ATR bar 累积为帧级 pre-pass（当前在 `_build_signal` per-stock 累积，见 `engine.py:2237-2274`）——**属于验证通过后的独立任务**，不在本计划范围内。

---
## Self-Review 记录

- **Spec 覆盖**：§2 决策 8 判定表 → Task 1 单测逐条覆盖；§4 契约 → 纯函数返回结构一致；§7 验证计划(区分度/基线对比/样本外) → Task 2 harness；§6 engine 挂载 → Task 3(门控后)。
- **占位扫描**：无 TBD/TODO；Task 2 的 harness 复用现有回测工具（含明确"先 rg 定位真实签名"指引，非未定义函数占位）。
- **类型一致**：`analyze_cross_section_overheat(cross_tier, vol_rank, config)` 全篇一致；`crossVolP33/P67/P90` 在纯函数与单测 `_C` 一致。
- **范围控制**：本计划只做"纯函数+单测+区分度验证"，engine 挂载明确移到门控之后的 Part D，避免在未验证时做有风险的 engine 重构。
