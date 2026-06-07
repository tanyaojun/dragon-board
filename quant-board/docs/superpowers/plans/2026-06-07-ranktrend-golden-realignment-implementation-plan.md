# RankTrend Golden Realignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 TS 主分析链、TS Golden 导出链和 Python RankTrend 分析链重新对齐到同一份 `half_hour` Golden 合同，并保留现有 Golden import / validate 工作流。

**Architecture:** 先在 TS 端提取共享分析 pipeline，消除 `RankTrendAnalyzer` 与 `RankTrendGoldenReplayEngine` 的顺序漂移；再在 Python 端把 Golden 回放路径切回纯分析 `market_regime` 口径，避免继续消费 `hotlistSentiment`。最后增强 `GoldenService` 的归一化摘要字段，让 `cycle / decision / risk / momentumProfile / candidateTier` 都能进入正式 diff。

**Tech Stack:** Vue 3, TypeScript, Vitest, Python, FastAPI service layer, Pytest

---

## File Map

- Create: `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
  - TS 纯分析 helper，统一 `technical -> cycle -> risk -> cycle -> decision -> strategy`
- Create: `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`
  - 锁定 TS pipeline 的二次 lifecycle 计算和 Golden replay 对齐
- Modify: `src/services/RankTrendAnalyzer.ts`
  - 改为消费共享 TS pipeline
- Modify: `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`
  - 改为消费共享 TS pipeline
- Create: `quant-board/tests/test_ranktrend_golden_alignment.py`
  - 锁定 Python Golden 回放必须走 `market_regime`，并覆盖 GoldenService 摘要与 diff 路径
- Modify: `quant-board/backend/analysis/ranktrend.py`
  - 新增纯分析 candidate tier helper；Golden 回放不再走 `hotlistSentiment` 口径
- Modify: `quant-board/backend/services.py`
  - 扩展 `_normalize_signals()` / `_normalize_expected_payload()` 输出的 Golden 摘要字段
- Modify: `quant-board/tests/test_quant_board.py`
  - 保留现有 API 级 Golden smoke test，并补断言验证 `expectedPreview / actualPreview` 携带新摘要字段
- Modify: `quant-board/docs/ranktrend-golden.md`
  - 更新当前 Golden 合同、比较字段与正式验收步骤

---

### Task 1: TS Shared Pipeline RED/GREEN

**Files:**
- Create: `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
- Create: `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`
- Modify: `src/services/RankTrendAnalyzer.ts`
- Modify: `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'

import { RankTrendGoldenReplayEngine } from '@/services/quantBoardGolden/RankTrendGoldenReplayEngine'
import { analyzeMarketRegime } from '../marketRegimeAnalyzer'
import { runRankTrendAnalysisPipeline } from '../runRankTrendAnalysisPipeline'

const regime = analyzeMarketRegime({
  breathData: {
    sentiment: { phaseName: '发酵期' },
    marketData: { ztCount: 48, dtCount: 1, upCount: 3200, downCount: 900 },
  },
  stocks: [
    { code: '000001', zlje: 1.2e8, volumeRatio: 1.8 },
    { code: '000002', zlje: 8.6e7, volumeRatio: 1.6 },
  ],
})

describe('runRankTrendAnalysisPipeline', () => {
  it('recomputes lifecycle after risk so decision evidence carries real risk pressure', () => {
    const result = runRankTrendAnalysisPipeline({
      ranks: [88, 76, 61, 44],
      percentiles: [18, 26, 39, 57],
      currentPercentile: 57,
      displayChange: 18,
      stockChange: 4.2,
      volumeRatio: 2.3,
      zlje: 1.6e8,
      zljzb: 14.5,
      regime,
    })

    expect(result.risk.pressure).toBeGreaterThan(0)
    expect(result.cycle.decision.evidence.riskPressure).toBe(result.risk.pressure)
    expect(result.cycle.decision.evidence.divergenceSeverity).toBe(result.risk.divergence.severity)
    expect(result.cycle.decision.evidence.overheatSeverity).toBe(result.risk.overheat.severity)
  })

  it('keeps golden replay aligned with runtime pipeline for cycle and final confidence', () => {
    const frames = [
      {
        snapshotId: 'half_hour:2026-06-06:09:30',
        timestamp: 1780738200000,
        tradingDate: '2026-06-06',
        slotTime: '09:30',
        type: 'half_hour',
        captureMode: 'real_time',
        stocks: [{ code: '000001', name: '测试股', rank: 88, change: 0.8, volumeRatio: 1.1, zlje: 1e7, zljzb: 1.5 }],
        marketContext: { payload: { sentiment: { phaseName: '发酵期' }, marketData: { ztCount: 48, dtCount: 1, upCount: 3200, downCount: 900 } } },
      },
      {
        snapshotId: 'half_hour:2026-06-06:10:00',
        timestamp: 1780740000000,
        tradingDate: '2026-06-06',
        slotTime: '10:00',
        type: 'half_hour',
        captureMode: 'real_time',
        stocks: [{ code: '000001', name: '测试股', rank: 76, change: 1.2, volumeRatio: 1.3, zlje: 2e7, zljzb: 2.4 }],
        marketContext: { payload: { sentiment: { phaseName: '发酵期' }, marketData: { ztCount: 48, dtCount: 1, upCount: 3200, downCount: 900 } } },
      },
      {
        snapshotId: 'half_hour:2026-06-06:10:30',
        timestamp: 1780741800000,
        tradingDate: '2026-06-06',
        slotTime: '10:30',
        type: 'half_hour',
        captureMode: 'real_time',
        stocks: [{ code: '000001', name: '测试股', rank: 61, change: 2.0, volumeRatio: 1.7, zlje: 4.6e7, zljzb: 6.8 }],
        marketContext: { payload: { sentiment: { phaseName: '发酵期' }, marketData: { ztCount: 48, dtCount: 1, upCount: 3200, downCount: 900 } } },
      },
      {
        snapshotId: 'half_hour:2026-06-06:11:00',
        timestamp: 1780743600000,
        tradingDate: '2026-06-06',
        slotTime: '11:00',
        type: 'half_hour',
        captureMode: 'real_time',
        stocks: [{ code: '000001', name: '测试股', rank: 44, change: 4.2, volumeRatio: 2.3, zlje: 1.6e8, zljzb: 14.5 }],
        marketContext: { payload: { sentiment: { phaseName: '发酵期' }, marketData: { ztCount: 48, dtCount: 1, upCount: 3200, downCount: 900 } } },
      },
    ] as const

    const helper = runRankTrendAnalysisPipeline({
      ranks: [88, 76, 61, 44],
      percentiles: [25, 37, 49, 63],
      currentPercentile: 63,
      displayChange: 14,
      stockChange: 4.2,
      volumeRatio: 2.3,
      zlje: 1.6e8,
      zljzb: 14.5,
      regime,
    })

    const signals = new RankTrendGoldenReplayEngine().replay(frames as any, {
      meta: {
        snapshotTypeUsed: 'half_hour',
        requestedSnapshotTypes: ['half_hour'],
        snapshotCount: 4,
        tradingDateCount: 1,
        tradingDateRange: { start: '2026-06-06', end: '2026-06-06' },
        delayedCount: 0,
        restoredCount: 0,
        emptyHotlistCount: 0,
        lowHotlistCount: 0,
        sampleQuality: 'degraded',
        featureCoverage: 'full',
        warnings: [],
        generatedAt: 1780743600000,
      },
      warmupCount: 1,
      windowSize: 4,
      maxSignals: 8,
    })

    const actual = signals.at(-1)?.rankTrend
    expect(actual?.cycle.transition).toBe(helper.cycle.transition)
    expect(actual?.cycle.decision.action).toBe(helper.cycle.decision.action)
    expect(actual?.decision.final.confidence).toBe(helper.decision.final.confidence)
    expect(actual?.strategy.candidateTier).toBe(helper.strategy.candidateTier)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`

Expected: FAIL，提示 `runRankTrendAnalysisPipeline` 模块不存在，或 replay engine 输出的 `cycle.decision.evidence.*` / `decision.final.confidence` 与 helper 预期不一致。

- [ ] **Step 3: 实现最小 TS 共享分析 helper，并把 runtime / golden replay 都切过去**

```ts
// src/services/rankTrend/runRankTrendAnalysisPipeline.ts
import type { RTConfigPatch } from '@/types/rankTrendDefaults'
import {
  cloneDefaultRankTrendRuntimeConfig,
  normalizeRankTrendRuntimeConfig,
} from '@/types/rankTrendDefaults'
import { analyzeAttentionCycle } from './attentionCycleAnalyzer'
import { composeCandidateTier } from './candidateTierComposer'
import { composeDecision } from './resultComposer'
import { analyzeRiskSignals } from './riskSignalAnalyzer'
import {
  analyzeFallbackTechnicalSignals,
  analyzeTechnicalSignals,
} from './technicalSignalAnalyzer'
import { getTechnicalMinSamples } from './utils'
import type {
  MarketRegimeAnalysis,
  RankTrendAnalysisResult,
} from './types'

type PipelineInput = {
  ranks: number[]
  percentiles: number[]
  currentPercentile: number
  displayChange: number
  stockChange: number
  volumeRatio: number
  zlje: number
  zljzb: number
  regime: MarketRegimeAnalysis
  configPatch?: RTConfigPatch
}

type PipelineResult = Pick<
  RankTrendAnalysisResult,
  'technical' | 'cycle' | 'risk' | 'decision' | 'strategy'
>

export function runRankTrendAnalysisPipeline(input: PipelineInput): PipelineResult {
  const config = normalizeRankTrendRuntimeConfig(
    cloneDefaultRankTrendRuntimeConfig(),
    input.configPatch ?? {},
  )
  const requiredSamples = getTechnicalMinSamples(config)
  const technical =
    input.percentiles.length >= requiredSamples
      ? analyzeTechnicalSignals(input.percentiles, config)
      : analyzeFallbackTechnicalSignals({
          percentiles: input.percentiles,
          displayChange: input.displayChange,
          stockChange: input.stockChange,
          volumeRatio: input.volumeRatio,
          zlje: input.zlje,
          zljzb: input.zljzb,
          config,
        })

  let cycle = analyzeAttentionCycle({
    ranks: input.ranks,
    percentiles: input.percentiles,
  })
  const risk = analyzeRiskSignals({
    currentPercentile: input.currentPercentile,
    technical,
    cycle,
    zlje: input.zlje,
    zljzb: input.zljzb,
    volumeRatio: input.volumeRatio,
  })
  cycle = analyzeAttentionCycle({
    ranks: input.ranks,
    percentiles: input.percentiles,
    risk: {
      pressure: risk.pressure,
      divergenceSeverity: risk.divergence.severity,
      overheatSeverity: risk.overheat.severity,
    },
  })
  const decision = composeDecision({
    technical,
    cycle,
    risk,
    config,
  })
  const strategy = composeCandidateTier({
    technical,
    cycle,
    risk,
    regime: input.regime,
  })

  return { technical, cycle, risk, decision, strategy }
}
```

```ts
// src/services/RankTrendAnalyzer.ts
import { runRankTrendAnalysisPipeline } from './rankTrend/runRankTrendAnalysisPipeline'

const { technical, cycle, risk, decision, strategy } = runRankTrendAnalysisPipeline({
  ranks: analysisRanks,
  percentiles: analysisPercentiles,
  currentPercentile,
  displayChange,
  stockChange,
  volumeRatio,
  zlje,
  zljzb,
  regime,
  configPatch: runtimeConfig,
})
```

```ts
// src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts
import { runRankTrendAnalysisPipeline } from '@/services/rankTrend/runRankTrendAnalysisPipeline'

const { technical, cycle, risk, decision, strategy } = runRankTrendAnalysisPipeline({
  ranks,
  percentiles,
  currentPercentile,
  displayChange,
  stockChange,
  volumeRatio,
  zlje,
  zljzb,
  regime,
  configPatch: this.config,
})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm test:ranktrend -- src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`

Expected: PASS，两个断言都通过，并且 replay engine 的 `cycle.decision.evidence.*` 与 helper 对齐。

- [ ] **Step 5: 运行 TS 回归并提交**

Run: `pnpm test:ranktrend`

Run: `pnpm typecheck:ranktrend`

Expected: 两个命令均 exit 0；若有失败，只修本任务引入的问题，不顺手整理无关 TS 模块。

```powershell
git add src/services/rankTrend/runRankTrendAnalysisPipeline.ts `
  src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts `
  src/services/RankTrendAnalyzer.ts `
  src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts
git commit -m "test: share ranktrend runtime and golden pipeline"
```

### Task 2: Python Golden Replay 回纯分析口径

**Files:**
- Create: `quant-board/tests/test_ranktrend_golden_alignment.py`
- Modify: `quant-board/backend/analysis/ranktrend.py`

- [ ] **Step 1: 写失败测试，锁定 Python 回放不能继续消费 hotlistSentiment**

```python
from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine


def _frame(snapshot_id: str, timestamp: int, rank: int, change: float, volume_ratio: float, zlje: float, zljzb: float) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": timestamp,
        "tradingDate": "2026-06-06",
        "slotTime": snapshot_id.rsplit(":", 1)[-1],
        "type": "half_hour",
        "captureMode": "real_time",
        "stocks": [
            {
                "code": "000001",
                "name": "测试股",
                "rank": rank,
                "change": change,
                "volumeRatio": volume_ratio,
                "zlje": zlje,
                "zljzb": zljzb,
            }
        ],
        "marketContext": {
            "payload": {
                "sentiment": {"phaseName": "发酵期"},
                "marketData": {"ztCount": 46, "dtCount": 1, "upCount": 3200, "downCount": 900},
            }
        },
        "hotlistSentiment": {"stage": "退潮", "riskLevel": "高", "confidence": 95},
    }


def test_python_replay_ignores_hotlist_sentiment_for_golden_candidate_tier() -> None:
    frames = [
        _frame("half_hour:2026-06-06:09:30", 1780738200000, 88, 0.8, 1.1, 1e7, 1.5),
        _frame("half_hour:2026-06-06:10:00", 1780740000000, 76, 1.2, 1.3, 2e7, 2.4),
        _frame("half_hour:2026-06-06:10:30", 1780741800000, 61, 2.0, 1.7, 4.6e7, 6.8),
        _frame("half_hour:2026-06-06:11:00", 1780743600000, 44, 4.2, 2.3, 1.6e8, 14.5),
    ]

    signal = RankTrendPythonEngine(RankTrendConfig()).replay(
        frames,
        warmup_count=1,
        window_size=4,
        meta={"sampleQuality": "ok", "warnings": []},
    )[-1]

    assert signal["rankTrend"]["strategy"]["regime"]["state"] == "strong"
    assert signal["candidateTier"] == "A_MAIN"
    assert signal["action"] == "focus"


def test_python_replay_rebuilds_cycle_decision_with_risk_payload() -> None:
    frames = [
        _frame("half_hour:2026-06-06:09:30", 1780738200000, 88, 0.8, 1.1, 1e7, 1.5),
        _frame("half_hour:2026-06-06:10:00", 1780740000000, 76, 1.2, 1.3, 2e7, 2.4),
        _frame("half_hour:2026-06-06:10:30", 1780741800000, 61, 2.0, 1.7, 4.6e7, 6.8),
        _frame("half_hour:2026-06-06:11:00", 1780743600000, 44, 4.2, 2.3, 1.6e8, 14.5),
    ]

    signal = RankTrendPythonEngine(RankTrendConfig()).replay(
        frames,
        warmup_count=1,
        window_size=4,
        meta={"sampleQuality": "ok", "warnings": []},
    )[-1]

    cycle = signal["rankTrend"]["cycle"]
    risk = signal["rankTrend"]["risk"]
    assert cycle["decision"]["evidence"]["riskPressure"] == risk["pressure"]
    assert cycle["decision"]["evidence"]["divergenceSeverity"] == risk["divergence"]["severity"]
    assert cycle["decision"]["evidence"]["overheatSeverity"] == risk["overheat"]["severity"]
```

- [ ] **Step 2: 运行 pytest 确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_golden_alignment.py -q`

Expected: FAIL，第一条测试应因 `candidateTier` 仍受 `hotlistSentiment=退潮/高风险` 影响而不是 `A_MAIN`。

- [ ] **Step 3: 在 Python 分析链中新增纯分析 candidate tier helper，并让 Golden replay 只走它**

```python
# quant-board/backend/analysis/ranktrend.py
def compose_candidate_tier(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    regime: dict[str, Any],
) -> dict[str, Any]:
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    weak_market = regime["state"] in ("weak", "retreat")
    trend_buy = (
        technical["signals"]["direction"]["signal"] == "buy"
        or technical["signals"]["acceleration"]["signal"] == "buy"
        or technical["macd"]["cross"] == "golden"
    )
    money_risk = risk["divergence"]["severity"]
    pressure = risk["pressure"]
    tier = "N_NEUTRAL"
    reasons: list[str] = []

    if (stage in ("reversal", "cooling")) and (
        momentum["short"] <= -2 or momentum["acceleration"] <= -2 or pressure >= 0.55
    ):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    elif stage == "crowded" or (
        momentum["long"] >= 4 and (momentum["acceleration"] <= 0 or pressure >= 0.45)
    ):
        tier = "C_CROWDED"
        reasons.append("长周期热度高位停留，追高性价比下降")
    elif (
        stage == "expansion"
        and momentum["mid"] >= 4
        and momentum["short"] >= -1
        and trend_buy
        and not weak_market
        and money_risk < 0.7
    ):
        tier = "A_MAIN"
        reasons.append("扩散阶段中周期动量确认，技术信号保持正向")
    elif (
        stage == "ignition"
        and momentum["short"] >= 3
        and momentum["acceleration"] >= 0.5
        and regime["state"] != "retreat"
        and pressure < 0.65
    ):
        tier = "B_IGNITION"
        reasons.append("点火阶段短周期冲击增强，仍需继续确认")
    elif weak_market and trend_buy:
        reasons.append("弱势/退潮环境下买入信号降级为观察")
    else:
        reasons.append("动量、阶段与风险未形成明确候选池信号")

    if regime["state"] == "strong":
        reasons.append("市场环境强，允许跟踪点火/扩散机会")
    if regime["state"] == "retreat":
        reasons.append("市场退潮，优先控制回撤风险")
    if risk["divergence"]["severity"] >= 0.6:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= 0.65:
        reasons.append("过热压力较高")
    reasons.append(
        f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} 长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}"
    )
    action = {"A_MAIN": "focus", "B_IGNITION": "watch", "C_CROWDED": "avoid", "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {"regime": regime, "momentum": momentum, "candidateTier": tier, "action": action, "reasons": reasons}
```

```python
# quant-board/backend/analysis/ranktrend.py
cycle = analyze_cycle(ranks, percentiles)
risk = analyze_risk(current_percentile, technical, cycle, fallback["zlje"], fallback["zljzb"], fallback["volumeRatio"])
cycle = analyze_cycle(ranks, percentiles, risk=risk)
decision = compose_decision(technical, cycle, risk, self.config)
strategy = compose_candidate_tier(technical, cycle, risk, regime)
```

```python
# quant-board/backend/analysis/ranktrend.py
def analyze_cycle(
    ranks: list[float],
    percentiles: list[float],
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
    return {
        "rawStage": raw,
        "stage": stage,
        "previousStage": previous_normalized,
        "transition": transition,
        "confidence": confidence,
        "metrics": metric_values,
        "entryAdvice": entry_advice(stage, transition),
        "decision": lifecycle_decision(
            raw,
            stage,
            transition,
            confidence,
            metric_values,
            risk,
        ),
    }
```

- [ ] **Step 4: 运行 pytest 确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_golden_alignment.py -q`

Expected: PASS，证明 Python Golden 回放路径已经切回 `market_regime` 口径，并保留 risk 证据。

- [ ] **Step 5: 提交 Python 分析链收口**

```powershell
git add quant-board/backend/analysis/ranktrend.py `
  quant-board/tests/test_ranktrend_golden_alignment.py
git commit -m "test: align python ranktrend golden analysis path"
```

### Task 3: GoldenService 摘要升级与 API Smoke Test

**Files:**
- Modify: `quant-board/backend/services.py`
- Modify: `quant-board/tests/test_ranktrend_golden_alignment.py`
- Modify: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: 写失败测试，锁定新摘要字段与 diff 路径**

```python
from backend.services import GoldenService


def test_golden_service_normalizes_cycle_and_decision_summary() -> None:
    normalized = GoldenService._normalize_expected_payload(
        [
            {
                "snapshotId": "half_hour:2026-06-06:11:00",
                "code": "000001",
                "candidateTier": "A_MAIN",
                "action": "focus",
                "stage": "expansion",
                "regime": "strong",
                "rank": 44,
                "confidence": 78.2,
                "rankTrend": {
                    "technical": {
                        "signals": {"direction": {"signal": "buy"}},
                        "momentumProfile": {"short": 5.0, "mid": 4.5, "long": 2.0, "acceleration": 1.2},
                    },
                    "cycle": {
                        "transition": "ignition->expansion",
                        "entryAdvice": {"bias": "preferred"},
                        "decision": {"action": "allow", "confidence": 73.0},
                    },
                    "risk": {"pressure": 0.12, "divergence": {"severity": 0.08}, "overheat": {"severity": 0.11}},
                    "decision": {
                        "base": {"signal": "buy", "confidence": 82.5},
                        "final": {"signal": "buy", "confidence": 78.2},
                    },
                },
            }
        ]
    )

    row = normalized[0]
    assert row["cycle"]["transition"] == "ignition->expansion"
    assert row["cycle"]["entryAdvice"]["bias"] == "preferred"
    assert row["cycle"]["decision"]["action"] == "allow"
    assert row["decision"]["final"]["confidence"] == 78.2


def test_golden_service_compare_reports_nested_cycle_path() -> None:
    expected = [{"cycle": {"transition": "ignition->expansion"}}]
    actual = [{"cycle": {"transition": "expansion->crowded"}}]
    issues = GoldenService._compare(expected, actual, tolerance=1e-6, strict=True)
    assert issues == ["$[0].cycle.transition: expected 'ignition->expansion' actual 'expansion->crowded'"]
```

```python
# quant-board/tests/test_quant_board.py
assert "cycle" in validated_golden.json()["expectedPreview"][0]
assert "decision" in validated_golden.json()["expectedPreview"][0]
assert "transition" in validated_golden.json()["expectedPreview"][0]["cycle"]
assert "final" in validated_golden.json()["expectedPreview"][0]["decision"]
```

- [ ] **Step 2: 运行 pytest 确认失败**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_golden_alignment.py tests/test_quant_board.py -q`

Expected: FAIL，`_normalize_expected_payload()` 还没有输出 `cycle / decision` 摘要，`expectedPreview` 断言也会失败。

- [ ] **Step 3: 实现最小 Golden 摘要升级**

```python
# quant-board/backend/services.py
@staticmethod
def _normalize_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for signal in signals:
        rank_trend = signal.get("rankTrend") or {}
        cycle = rank_trend.get("cycle") or {}
        decision = rank_trend.get("decision") or {}
        normalized.append(
            {
                "snapshotId": signal.get("snapshotId"),
                "code": signal.get("code"),
                "candidateTier": signal.get("candidateTier"),
                "action": signal.get("action"),
                "stage": signal.get("stage"),
                "regime": signal.get("regime"),
                "rank": signal.get("rank"),
                "confidence": signal.get("confidence"),
                "finalSignal": (decision.get("final") or {}).get("signal"),
                "technicalSignals": (rank_trend.get("technical") or {}).get("signals"),
                "momentumProfile": (rank_trend.get("technical") or {}).get("momentumProfile"),
                "risk": rank_trend.get("risk"),
                "cycle": {
                    "transition": cycle.get("transition"),
                    "entryAdvice": cycle.get("entryAdvice"),
                    "decision": cycle.get("decision"),
                },
                "decision": {
                    "base": decision.get("base"),
                    "final": decision.get("final"),
                },
            }
        )
    return normalized
```

```python
# quant-board/backend/services.py
normalized.append(
    {
        "snapshotId": item.get("snapshotId"),
        "code": item.get("code"),
        "candidateTier": item.get("candidateTier"),
        "action": item.get("action"),
        "stage": item.get("stage"),
        "regime": item.get("regime"),
        "rank": item.get("rank"),
        "confidence": item.get("confidence"),
        "finalSignal": item.get("finalSignal") or ((decision.get("final") or {}).get("signal")),
        "technicalSignals": item.get("technicalSignals") or technical.get("signals"),
        "momentumProfile": item.get("momentumProfile") or technical.get("momentumProfile"),
        "risk": item.get("risk") or rank_trend.get("risk"),
        "cycle": item.get("cycle")
        or {
            "transition": cycle.get("transition"),
            "entryAdvice": cycle.get("entryAdvice"),
            "decision": cycle.get("decision"),
        },
        "decision": item.get("decision")
        or {
            "base": decision.get("base"),
            "final": decision.get("final"),
        },
    }
)
```

- [ ] **Step 4: 运行 pytest 确认通过**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_golden_alignment.py tests/test_quant_board.py -q`

Expected: PASS，`expectedPreview / actualPreview` 都携带新摘要字段，并能输出嵌套字段路径。

- [ ] **Step 5: 提交 GoldenService 升级**

```powershell
git add quant-board/backend/services.py `
  quant-board/tests/test_ranktrend_golden_alignment.py `
  quant-board/tests/test_quant_board.py
git commit -m "test: expand golden summary coverage"
```

### Task 4: 文档同步与正式验收

**Files:**
- Modify: `quant-board/docs/ranktrend-golden.md`
- Review only: `quant-board/docs/superpowers/specs/2026-06-07-ranktrend-golden-realignment-design.md`

- [ ] **Step 1: 更新 Golden 文档，写清当前共享 pipeline 和新摘要字段**

```md
## 当前 TS 真相源

- `src/services/RankTrendAnalyzer.ts`
- `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
- `src/services/rankTrend/**`

TS Golden 导出链 `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts` 必须复用同一 pipeline，不能再维护平行分析顺序。

## 当前比较摘要

Golden 归一化摘要至少比较：

- `candidateTier`
- `action`
- `stage`
- `regime`
- `rank`
- `confidence`
- `finalSignal`
- `technicalSignals`
- `momentumProfile`
- `risk`
- `cycle.transition`
- `cycle.entryAdvice`
- `cycle.decision`
- `decision.base`
- `decision.final`
```

- [ ] **Step 2: 运行最终自动化验证**

Run: `pnpm test:ranktrend`

Run: `pnpm typecheck:ranktrend`

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest`

Expected: 三个命令全部 exit 0。

- [ ] **Step 3: 用当前真实数据集做正式 TS Golden 验收**

在 Dragon Board 控制台执行：

```js
await window.quantBoardExportRankTrendGolden({
  caseId: 'rank_trend_default',
  datasetId: 'ds_xxx',
  snapshotType: 'half_hour',
  limit: 500,
  sampleLimit: 100
})
```

然后在 QuantBoard `Golden 对齐` 页面：

1. `caseId` 保持 `rank_trend_default`
2. 选择刚下载的 `rank_trend_default.half_hour.ts-golden.json`
3. 点击 `导入 TS Golden`
4. 点击 `执行校验`

同时确认：

- `source=ts_golden_import`
- `isFormalTsGolden=true`
- `passed=true`
- `issueCount=0`

如果需要 CLI 复核，再运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli validate-golden --case-id rank_trend_default --tolerance 1e-6
```

Expected: `passed` 为 `true`，且 `checked` 等于本次导入样本数。

- [ ] **Step 4: 核对实现与 spec 一致并收尾提交**

Checklist:

- TS 主分析链与 TS Golden replay 已共用同一 pipeline
- Python Golden replay 不再消费 `hotlistSentiment`
- Golden 摘要覆盖 `cycle / decision / risk / momentumProfile / candidateTier`
- 没有改动 `quant-board/backend/core/backtest/**`
- 没有改动长测 baseline 或优化口径

```powershell
git add quant-board/docs/ranktrend-golden.md
git commit -m "docs: update ranktrend golden realignment contract"
```

---

## Spec Coverage Review

- TS 主分析链与 TS Golden 导出链共用顺序：Task 1
- Python 重新回到纯 RankTrend 分析合同：Task 2
- Golden 摘要字段升级：Task 3
- 正式 `half_hour` 真实数据集验收：Task 4
- 不触碰执行层、长测、优化边界：Task 2 / Task 4 checklist

## Placeholder Scan

- 本计划不含 `TODO` / `TBD` / “后续再补” 占位词。
- 文档验收命令、测试命令、手工导出命令均已写死。

## Type Consistency Review

- TS 共享 helper 统一命名为 `runRankTrendAnalysisPipeline`
- Python 纯分析候选分层 helper 统一命名为 `compose_candidate_tier`
- Golden 摘要中的嵌套键统一使用 `cycle` 与 `decision`
