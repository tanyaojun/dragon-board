# rankTrend Golden 标准

## 结论

RankTrend golden 以 Python `quant-board/backend/analysis/ranktrend/engine.py` 为生产事实标准。Dragon Board TS 前端只消费
`POST /api/ranktrend/analyze` 与 `GET /api/snapshots/frames`（每帧附 regime）的输出，不再保留本地 golden 链算法实现。

Golden 来源（唯一）：

- `quant-board/backend/analysis/ranktrend/engine.py`

TS 消费契约仍为 `RankTrendAnalysisResult`（见 `src/services/rankTrend/types.ts`），但该合同现在由 Python 输出定义。

## 当前分析顺序（Python 事实标准）

当前 RankTrend 的共享分析顺序以 `ranktrend.py` 的 `RankTrendPythonEngine._build_signal` 为准：

```text
technical -> cycle -> risk -> cycle(with risk) -> decision -> strategy
```

Python Golden replay 也必须对齐这条纯分析链，不再消费 `hotlistSentiment` 注入口径。

## 默认配置

首期 Python 默认值必须来自 TypeScript `DEFAULT_RANK_TREND_RUNTIME_CONFIG`：

| 参数 | 默认值 |
| --- | --- |
| `momentumPeriods` | `[3, 5, 8, 13, 21]` |
| `momentumWeights` | `[0.15, 0.2, 0.25, 0.25, 0.15]` |
| `buyThresholds` | `[5, 8, 13, 21, 34]` |
| `sellThresholds` | `[-5, -8, -13, -21, -34]` |
| `macdFast` | `13` |
| `macdSlow` | `21` |
| `macdSignal` | `8` |
| `requireMacdGoldenCross` | `false`（TS 默认配置无此隐式买入门） |
| `directionWeight` | `0.3` |
| `accelerationWeight` | `0.25` |
| `crossWeight` | `0.2` |
| `macdWeight` | `0.25` |
| `buyScoreThreshold` | `0.12` |
| `sellScoreThreshold` | `-0.12` |

五维观察档位阈值（`ranktrend-tier-backtest/ranktrend-signal-tier-backtest-plan.md` §3.1 参数化，默认值 = 旧硬编码，golden 不漂移）：

| 参数 | 默认值 | 消费位置 |
| --- | --- | --- |
| `tierResonanceReversalPenaltyMin` | `0.6` | `_resonance_tier` 首条（reversal 否决） |
| `tierResonanceJumpFreshnessMin` | `0.5` | `_resonance_tier` 第二条（Jump）+ 新入榜 S |
| `tierResonancePersistenceMin` | `0.6` | `_resonance_tier` 第三条（buy+persistence） |
| `tierResonanceEntryStrengthMin` | `0.3` | 新入榜 A 判定 |
| `tierRankTrendStrongMin` | `0.5` | `_rank_trend_tier` S |
| `tierRankTrendConfirmMin` | `0.25` | `_rank_trend_tier` A |
| `tierSynergyVoteStrong` | `2` | `_synergy_tier`：`v>=strong 且 lc_tier=="A"`→S，`v>=strong`→A（int） |
| `tierSynergyVoteWeak` | `1` | `_synergy_tier` vote_sum==1（B，int） |
| `tierSynergyVoteReverse` | `-1` | `_synergy_tier` vote_sum≤−1（D，int） |

> `from_patch` 强校验（不满足抛 ValueError，回测 trial 记 failed）：`0 < tierRankTrendConfirmMin < tierRankTrendStrongMin <= 1`、`tierSynergyVoteReverse <= tierSynergyVoteWeak < tierSynergyVoteStrong`（weak 严格小于 strong）、`0 <= tierResonance*Min <= 1`。

交易层 synergy 门参数（不进 `RankTrendConfig`，经 `to_trade_config` 透传进 trade_config，由 `TradeSimulator` 消费，默认关闭）：

| 参数 | 默认值 | 语义 |
| --- | --- | --- |
| `synergyEntryTierMin` | `"none"` | `none`=不启用；`s`=仅 S 入场；`a`=S/A 入场（与现有入场条件取交集） |
| `synergyExitOnDanger` | `false` | D/E 档强制卖出 |

默认快照：

```text
DEFAULT_RANK_TREND_SNAPSHOT_TYPE = half_hour
```

> 注意：TypeScript golden 标准使用 `macdFast=13, macdSlow=21, macdSignal=8` 作为 RankTrend 算法层的默认值。QuantBoard 回测引擎的 `DEFAULT_BACKTEST_STRATEGY_CONFIG` 使用 `21/34/13` 作为生产默认值。两者是不同层次的配置 — golden 测试验证的是算法移植正确性，回测默认值反映的是当前实盘参数选择。修改任意一侧时应同时检查另一侧是否需要同步，并在对应文档（`backtest-policy.md`）中记录。

## 输出合同

Python rankTrend 输出应对齐 `RankTrendAnalysisResult`：

```json
{
  "meta": {
    "code": "600000",
    "currentRank": 12,
    "currentPercentile": 94.5,
    "change": 3.2,
    "rawChange": 5,
    "updateTime": 1777557600000,
    "sampleQuality": {}
  },
  "technical": {
    "movingAverage": {},
    "macd": {},
    "signals": {},
    "momentumScore": 0,
    "momentumProfile": {}
  },
  "cycle": {},
  "risk": {},
  "decision": {},
  "strategy": {}
}
```

### meta

- `code`
- `currentRank`
- `currentPercentile`
- `change`
- `rawChange`
- `updateTime`
- `sampleQuality`

### technical

- `movingAverage.ma5`
- `movingAverage.ma10`
- `movingAverage.trend`
- `macd.dif`
- `macd.dea`
- `macd.histogram`
- `macd.cross`
- `macd.rawScore`
- `macd.confirmed`
- `signals.direction`
- `signals.acceleration`
- `signals.zeroCross`
- `momentumScore`
- `momentumProfile`

### cycle

- `rawStage`
- `stage`
- `previousStage`
- `transition`
- `confidence`
- `metrics.rankVelocity`
- `metrics.rankAcceleration`
- `metrics.rankShock`
- `metrics.hotZoneStreak`
- `metrics.bestRecentRank`
- `metrics.drawdownFromPeak`
- `entryAdvice`

### risk

- `overheat`
- `divergence`
- `pressure`
- `synergy`

### decision

- `base.signal`
- `base.confidence`
- `base.combinedScore`
- `base.scoreMargin`
- `final.signal`
- `final.confidence`

### strategy

- `regime`
- `momentum`
- `candidateTier`
- `action`
- `reasons`

> **边界说明：** `ThemeCandidateSupport`（`mainTheme`、`themeHeat`、`themeContribution`、`themeRole`、`themeSupportScore`、`themeRiskFlags`、`themeReasons`）是回测引擎层面的信号富化字段，写入 `backtest_signals`，**不属于 RankTrend golden 输出合同**。Golden 测试不验证题材字段，题材因子不能绕过 RankTrend 独立制造买入信号。

### observation / resonance 档位字段（回测方案 §3.2 组装下沉后）

`rankTrend.observation.*` 与 `rankTrend.resonance` 输出五维离散档位（`ranktrend-tier-backtest/ranktrend-observation-discrete-tiers-design.md`）：

- `rankTrend.resonance.signalTier` / `tierReasons`：共振档位（`_resonance_tier` 产出；新入榜分支内联）。
- `rankTrend.observation.rankTrend.signalTier` / `tierReasons`：趋势档位（`_rank_trend_tier`）。
- `rankTrend.observation.lifecycle.signalTier` / `tierReasons`：周期档位（`_lifecycle_tier`）。
- `rankTrend.observation.volumePrice.signalTier` / `tierReasons`：量价档位（`_volume_price_tier`）。
- `rankTrend.observation.synergy.signalTier` / `tierReasons`：四维合并档位（`_synergy_tier`，组装下沉前仅在 API 单股链路生产，下沉后 replay 信号亦含）。

档位枚举：`S / A / B / C / D / E / unknown`（`unknown` = 样本不足/数据缺失，前端显示 `--`，不归零、不伪装）。API 与 replay 由 `assemble_observation`（`backend/analysis/ranktrend/volume_price.py`）统一组装；replay 链路无横截面 resonance 时共振维缺票（vote=0），属已知限制。

## Golden case 类型

建议维护三类 case：

1. 单函数 case
   - technical、cycle、risk、decision、candidate tier 分开验证。
   - 适合定位数值差异。

2. 端到端 case
   - 输入一组快照序列和当前 rank map。
   - 期望完整 `RankTrendAnalysisResult`。

3. 边界 case
   - 样本不足；
   - MACD 最小样本；
   - 排名缺失；
   - 恢复快照排除；
   - 半小时默认、quarter_hour 显式选择。

## Golden case 存储

使用已有表：

```text
golden_ranktrend_cases
```

字段建议：

```json
{
  "id": "rt_technical_macd_golden_001",
  "name": "MACD 金叉确认",
  "dataset_id": "fixture_ranktrend_001",
  "input_json": {
    "config": {},
    "snapshots": [],
    "rankMap": {}
  },
  "expected_json": {
    "technical": {},
    "decision": {},
    "strategy": {}
  }
}
```

## 比较规则

浮点数允许容差：

- 排名、计数、枚举、布尔值必须完全一致。
- 百分位、分数、置信度默认容差 `1e-6`，如 Python 与 JS 浮点差异明显，可放宽到 `1e-4`，但必须记录原因。
- `reasons` 文案首期建议完全一致；如果 Python 文案后续本地化调整，至少要保证 reason code 一致。

## 当前比较摘要

Golden validate 走归一化摘要比较时，当前至少覆盖以下字段：

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

其中 `cycle` 与 `decision` 的嵌套摘要同时进入：

- `POST /api/golden/import` 的 expected 标准化
- `POST /api/golden/validate` 的 actual 标准化
- `expectedPreview / actualPreview` 页面预览

## 生成流程

golden case 由 Python 端生成：对固定输入跑 `RankTrendPythonEngine`，输出 `RankTrendAnalysisResult` 合同 JSON 存入
`golden_ranktrend_cases`；TS 消费侧以该合同做契约校验。旧的 DragonBoard 控制台导出流程
（`window.quantBoardExportRankTrendGolden`）已随 `src/services/quantBoardGolden/**` 删除，不再使用。

### 手工模块导出

当前 QuantBoard API 支持把 TypeScript 导出的 JSON 直接导入同一个 `caseId`：

```http
POST /api/golden/import
```

请求体示例：

```json
{
  "caseId": "rank_trend_default",
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "source": "ts_golden_import",
  "payload": {
    "signals": []
  }
}
```

`payload.signals` 可以是 TypeScript 原始 `rankTrend` 输出，也可以是已归一化后的 expected 列表。后端会保存到 `golden_ranktrend_cases.expected_json`，之后 `POST /api/golden/validate` 用同一 `caseId` 做 Python 对齐校验。

注意：`/api/golden/baseline` 保存的是 Python 当前输出，只能用于临时回归，不是正式 TypeScript golden。

## Python 自基线与 TS Golden 的区别

| 类型 | 来源 | 用途 | 是否可作为跨语言验收 |
| --- | --- | --- | --- |
| Python 自基线 | `POST /api/golden/baseline` | 检查 Python 后续代码是否漂移 | 否 |
| TS Golden | DragonBoard TypeScript 导出后 `POST /api/golden/import` | 比较 Python 当前输出与 TypeScript 期望输出 | 是 |

页面上看到 `source=python_current_output` 时，即使 `passed=true`，也只能说明 Python 对自身没有漂移。

## 验收标准

Python 移植进入回测前必须满足：

- 默认配置与 TypeScript 一致。
- `snapshot_type` 默认是 `half_hour`。
- golden case 全部通过。
- 样本不足 case 能返回 `insufficient` 或 `degraded`。
- `quarter_hour` case 只有显式选择时生效。
- 没有任何测试以 Dragon Board 根项目浏览器内回测输出作为期望值。

## 变更管理

如果 dragon-board TypeScript rankTrend 后续变化：

1. 更新 golden case。
2. 提升 Python `strategy_version` 或 `ranktrend_version`。
3. 重新跑 Python golden 测试。
4. 已有历史回测保持旧版本结果，不覆盖。

## 与 V2 四层框架的关系

`strategy.candidateTier` 是 Golden 输出合同中的关键字段。V2 长测框架的四层决策链路对 golden 输出的消费关系如下：

| V2 层 | 消费的 Golden 字段 | 用途 |
|---|---|---|
| Layer 1（信号有效性） | `strategy.candidateTier` | 分层比例、方向精度、二项检验、层级区分度 |
| Layer 2（执行质量） | `decision.combinedScore`、`strategy.candidateTier` | H1/H2 偏差诊断，间接反映信号稳定性 |
| Layer 3（实盘对齐） | 回测信号 + trade_journal | 交叉比对，不直接消费 golden 输出 |
| Layer 4（参数优化） | Layer 1-3 结论 | 触发条件判定，不直接消费 golden 输出 |

Layer 1 的 `compute_signal_efficacy()` 从 `candidateTier` 读取 `A_MAIN` 和 `N_NEUTRAL` 分层，计算方向精度、二项检验和层级区分度。

Layer 2 的执行偏差诊断通过 H1/H2 绩效对比间接受 `decision.combinedScore` 和 `strategy.candidateTier` 影响——如果这两个字段的算法语义或值域发生变化，同样需要重新建立 Layer 2 基线。

如果 RankTrend 算法变更导致 `candidateTier` 输出合同的字段名、值域或语义发生变化，需要同时：
1. 更新 golden case
2. 检查 `compute_signal_efficacy()` 和 `compute_execution_quality()` 是否需要适配
3. 重新跑长测 checkpoint 建立新的 Layer 1 和 Layer 2 基线

`sampleQuality` 字段的 `tier` 子字段在较早版本的信号中有使用，但当前代码统一从顶层 `candidateTier` 读取。Golden case 应该继续验证两者的一致性。
