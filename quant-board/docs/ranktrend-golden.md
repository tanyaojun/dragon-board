# rankTrend Golden 标准

## 结论

QuantBoard 首期以 dragon-board 的 TypeScript `rankTrend` 为 golden 标准。Python 端不是重新设计策略，而是先复刻 golden 输出，再在此基础上做回测和优化。

Golden 来源：

- `src/type/rankTrendDefaults.ts`
- `src/services/RankTrendAnalyzer.ts`
- `src/services/rankTrend/technicalSignalAnalyzer.ts`
- `src/services/rankTrend/attentionCycleAnalyzer.ts`
- `src/services/rankTrend/riskSignalAnalyzer.ts`
- `src/services/rankTrend/resultComposer.ts`
- `src/services/rankTrend/marketRegimeAnalyzer.ts`
- `src/services/rankTrend/candidateTierComposer.ts`
- `src/services/rankTrend/statusClassifier.ts`

`ParameterOptimizer` 不属于 golden 来源。

## 默认配置

首期 Python 默认值必须来自 TypeScript `DEFAULT_RANK_TREND_RUNTIME_CONFIG`：

| 参数 | 默认值 |
| --- | --- |
| `momentumPeriods` | `[3, 5, 8, 13, 21]` |
| `momentumWeights` | `[0.15, 0.2, 0.25, 0.25, 0.15]` |
| `buyThresholds` | `[5, 8, 12, 15, 20]` |
| `sellThresholds` | `[-5, -8, -12, -15, -20]` |
| `macdFast` | `13` |
| `macdSlow` | `21` |
| `macdSignal` | `8` |
| `directionWeight` | `0.3` |
| `accelerationWeight` | `0.25` |
| `crossWeight` | `0.2` |
| `macdWeight` | `0.25` |
| `buyScoreThreshold` | `0.12` |
| `sellScoreThreshold` | `-0.12` |

默认快照：

```text
DEFAULT_RANK_TREND_SNAPSHOT_TYPE = half_hour
```

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

## 生成流程

推荐通过 DragonBoard TypeScript 端生成 golden。当前保留两条路径：

### 运行页控制台导出

这条路径不再让 QuantBoard 自动打开新页面。它要求你在已经打开的 DragonBoard 页面执行导出函数，稳定性更高。

前提：

- DragonBoard 页面在 `http://localhost:5173` 正常运行；
- 页面已刷新到包含 `src/services/quantBoardBridge.ts` 的最新代码；
- 浏览器控制台能看到 `QuantBoardBridge ready` 日志。

在 DragonBoard 页面控制台执行：

```js
await window.quantBoardExportRankTrendGolden({
  caseId: 'rank_trend_default',
  datasetId: 'ds_xxx',
  snapshotType: 'half_hour',
  limit: 500,
  sampleLimit: 500
})
```

函数会读取当前页面 origin 下的 `DragonBoardData` IndexedDB，调用 TypeScript `RankTrendReplayEngine`，并下载：

```text
rank_trend_default.half_hour.ts-golden.json
```

然后回到 QuantBoard 的 Golden 对齐页：

1. 选择这个 JSON 文件；
2. 点击 `导入 TS Golden`；
3. 点击 `执行校验`；
4. 结果里的 `source=ts_golden_import` 且 `passed=true` 时，才代表正式跨语言对齐通过。

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
- 没有任何测试以 `ParameterOptimizer` 输出作为期望值。

## 变更管理

如果 dragon-board TypeScript rankTrend 后续变化：

1. 更新 golden case。
2. 提升 Python `strategy_version` 或 `ranktrend_version`。
3. 重新跑 Python golden 测试。
4. 已有历史回测保持旧版本结果，不覆盖。
