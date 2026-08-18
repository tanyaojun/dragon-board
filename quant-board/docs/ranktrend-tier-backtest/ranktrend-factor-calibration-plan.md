# RankTrend 因子参数抽取与校准计划

> 主题：RankTrend 四维观察信号 + 决策链路的硬编码参数治理、统一入口管理、回测调参打通
> 状态：计划稿（未实现）
> 范围：`engine.py` / `volume_price.py` / `ranktrend_routes.py` 全部 magic number 抽取
> 前置结论：核心算法结构不动，只治理"未经校准的经验参数"（见前序讨论）

## 1. 背景与目标

1. 现状：RankTrend 算法存在大量硬编码 magic number（归一化除数 `/15`、`/8`、权重 `0.35/0.25/...`、阈值 `0.95/1.05/2.5/20` 等），散落在 `engine.py`、`volume_price.py`、`ranktrend_routes.py`。
2. 问题：这些参数无法通过回测调参（不在 `RankTrendConfig`、不在搜索空间白名单），调参只能改源码；且改了也无法锁定基线、无法复现。
3. 目标：**所有参数抽成命名常量，统一入口管理**（单一 config 对象），回测/优化可逐参数搜索覆盖。
4. 约束：抽取后默认行为与现状**逐字段一致**（golden case 不漂移）；不改变算法结构；不引入新依赖。
5. 验收：无裸 magic number；默认 config 与现状 golden 全绿；新参数可被 `search_space` 覆盖并被优化 runner 消费。

## 2. 现状：参数入口机制与缺口

### 2.1 现有入口（已经存在，但覆盖面窄）

```
search_space (search_space.py)
  → candidates()/suggest_params()  → params(dict)
  → to_strategy_config(params)     → 白名单 _STRATEGY_PARAM_KEYS 过滤
  → strategy_config = {**base, **to_strategy_config(params)}   (trial.py:28)
  → RankTrendConfig.from_patch(strategy_config)                (trial.py:138)
  → RankTrendPythonEngine(config).replay(...)
```

- `RankTrendConfig`（`engine.py:41`）：dataclass，约 30 字段，`from_patch` 按字段名 `setattr` 覆盖。
- `_STRATEGY_PARAM_KEYS`（`search_space.py:240`）：手工维护的 23 个 strategy 参数白名单，决定哪些 params 进 strategy_config（其余进 trade_config）。
- `default_search_space()`（`search_space.py:22`）：当前只覆盖 MACD、buyScoreThreshold、6 个 tier 阈值 + 交易层参数。

### 2.2 缺口（四类）

1. **dataclass 收容不全**：engine.py 内大量 magic number 未进 `RankTrendConfig`，因此无法 `from_patch` 覆盖。
2. **白名单手工维护**：新增字段必须同时改 `_STRATEGY_PARAM_KEYS`，漏改则参数被 `to_trade_config` 错误流到交易层或被丢弃。
3. **volume_price.py 完全独立**：量价/协同的所有常量都是模块级，未进任何 config。
4. **`ranktrend_routes.py` 的量价修正权重** `RESONANCE_VOLUME_PRICE_WEIGHT = 0.15` 硬编码。
5. **⚠️ tier 阈值重复硬编码**：`compose_analysis_candidate_tier`（engine.py:1296-1322）内 `-2/0.55/4/0.45/4/-1/0.7/3/0.5/0.65` 与 `compose_strategy` 已 config 化的 `tierAMain*` / `tierBIgnition*` / `tierCrowded*` / `tierExitRisk*` 字段**完全同值**，同一套阈值写了两遍，一遍进 config、一遍裸写。抽取时须合并为同一组 config 字段。

## 3. 参数分类原则

不是所有"数字"都该进可搜索空间。抽取时按三类处理，避免无意义组合爆炸：

| 类别 | 定义 | 处理 | 例子 |
|---|---|---|---|
| **A. 可调算法参数** | 影响信号强弱/方向/分层，需回测校准 | 进 `RankTrendConfig` + 进白名单 + 进搜索空间 | 权重、阈值、归一化除数、窗口 BAR 数、加减分系数 |
| **B. 结构常量** | 交易所规则/数据口径，不因调参变化 | 抽成命名常量，集中管理，**不进**搜索空间 | 板块涨跌停前缀 `300/688/8/4/9`、涨跌停幅度 `9.8/19.8/29.8`、最小样本数、历史窗口 |
| **C. 展示标签** | 文案/枚举，非数值参数 | 保持现状，不动 | `_resonance_label` 档位文案、`entry_advice` bias 文案 |

> 用户要求"所有参数都不能硬编码，全部抽出来定义成常量统一入口管理"——A 类进 config（可调），B 类抽成模块级命名常量（集中管理），C 类本就不算参数。三者都满足"有名字、有归属、无裸数字"，但只有 A 类进回测搜索。

## 4. 统一参数模型设计

### 4.1 扩展 `RankTrendConfig`（首选，破坏性最小）

- **继续使用现有 dataclass**，按维度用**前缀命名**分组（与现有 `tierAMainMidMomentumMin`、`directionWeight` 风格一致）。
- 每个新字段**默认值 = 当前硬编码值**，保证默认行为不变。
- 分组前缀约定：

| 前缀 | 维度 |
|---|---|
| （无，已有） | decision / momentum / macd / tier |
| `momentum*` / `shock*` / `pathCommitment*` / `macd*` | 技术信号层 |
| `fallback*` | 技术信号兜底 |
| `decision*` | 决策层 |
| `resonance*` | 共振 |
| `lifecycle*` | 生命周期观察/决策 |
| `cycle*` / `cycleStage*` | 周期状态机/置信度 |
| `risk*` | 风险 |
| `regime*` | 市场环境 |
| `volumePrice*` / `synergy*` | 量价/四象协同 |

- 若字段数超过 ~80 导致 dataclass 不可维护，再拆分到 `backend/analysis/ranktrend/config.py`，engine.py 保留 `from .config import RankTrendConfig` 兼容 re-export（判断标准：字段 >80 或单组 >15）。

### 4.2 单一事实来源（消除白名单不同步）

将 `_STRATEGY_PARAM_KEYS` 从手工 tuple 改为**从 dataclass 自动生成**：

```python
import dataclasses
from backend.analysis.ranktrend.engine import RankTrendConfig

# 标量字段（f.default 为 int/float/bool）自动入白名单
_SCALAR_KEYS = tuple(
    f.name
    for f in dataclasses.fields(RankTrendConfig)
    if isinstance(f.default, (int, float, bool))
)
# 复合字段（list/dict，用 field(default_factory=...) 定义）需手工维护：
# 注意 dataclasses 中 default_factory 字段的 f.default 是 MISSING（非 list），
# isinstance(f.default, (int,float,bool)) 为 False，会被上面的过滤自动排除。
_STRATEGY_PARAM_KEYS = _SCALAR_KEYS + (
    "momentumPeriods",
    "momentumWeights",
    "buyThresholds",
    "sellThresholds",
)
```

说明：
- **关键坑**：`RankTrendConfig` 里 `momentumPeriods`/`momentumWeights`/`buyThresholds`/`sellThresholds` 用 `field(default_factory=lambda: [...])` 定义，其 `f.default` 是 `dataclasses.MISSING`，不是 list。若只按 `isinstance(f.default, (int,float,bool))` 过滤，这些字段会被误排除——而 `momentumPeriods` 当前就在白名单里（`search_space.py:241`），自动化后消失会使其无法搜索，且被 `to_trade_config` 错误改道到 trade_config。
- 因此复合字段须单独列白名单（`_STRATEGY_PARAM_KEYS = _SCALAR_KEYS + (...)`），其搜索用 `search_space` 的 choices 列表整体覆盖。
- 新增标量字段自动进白名单，消除手工同步；新增复合字段须显式追加到上面的 tuple。
- `requireMacdGoldenCross`（bool）自动可搜（search space 用 `[true, false]` choices）。

## 5. 参数清单（系统盘点版，覆盖 engine.py + volume_price.py + ranktrend_routes.py）

> 类型列：A=可调算法参数（进 config+搜索）；B=结构常量（抽命名常量，不搜索）；⚠️=与已 config 化字段重复，须合并。所有行号基于当前代码。
> 说明：A/B 类 magic number 已逐函数盘点；`analyze_risk` 的逐项加减分系数、`cycle_confidence` 的四组判定阈值属同质参数组，以"主系数 + 实现阶段逐条命名"方式列出（见各小节注），非逐数字枚举。C 类展示标签见 §5.13。

### 5.1 技术信号层（momentum_profile / rank_shock / rank_path_commitment / calculate_macd / momentum_data / analyze_momentum_signals）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `momentumShortPeriods` | `[1, 3, 5]` | A | engine.py:218 |
| `momentumMidPeriods` | `[5, 8, 13]` | A | engine.py:219 |
| `momentumLongPeriods` | `[13, 21]` | A | engine.py:220 |
| `momentumCompositeWeights` | `[0.35, 0.4, 0.25, 0.2]`（short/mid/long/accel） | A | engine.py:226 |
| `shockLookback` | `10`（生产值，engine.py:225 调用 `rank_shock(percentiles, 10)`；函数默认参数 `5` 为死代码兜底） | A | engine.py:225,237 |
| `shockZScoreClamp` | `5`（clamp −5..5） | A | engine.py:249 |
| `pathCommitmentWindow` | `8` | A | engine.py:267 |
| `pathCommitmentWeights` | `[0.45, 0.45, 0.1]` | A | engine.py:279 |
| `macdGoldenStrongGapMin` | `0.2` | A | engine.py:197 |
| `macdGoldenGapScaleRatio` | `0.18` | A | engine.py:197 |
| `macdDeathGapScaleRatio` | `0.12` | A | engine.py:203 |
| `macdDeathStrongGapMin` | `0.18` | A | engine.py:203 |
| `macdRawScoreWeights` | `[0.7, 0.3]`（strong_gap/impulse） | A | engine.py:201,207 |
| `momentumScoreThreshold` | `35`（±35） | A | engine.py:300 |
| `momentumConfidenceSlope` | `0.45` | A | engine.py:301 |
| `momentumSignalShareMin` | `0.6` | A | engine.py:331,333 |
| `momentumDirectionThreshold` | `0.2` | A | engine.py:331,333 |
| `momentumDirectionShareBoost` | `[0.5, 0.5]` | A | engine.py:326 |
| `momentumLongWindowSize` | `2` | A | engine.py:327 |
| `momentumLongOpposeThreshold` | `0.25` | A | engine.py:328,329 |
| `momentumLongAgreeThreshold` | `0.15` | A | engine.py:335 |
| `momentumLongAgreeBonus` | `2.5` | A | engine.py:368 |
| `momentumAccelShareBoost` | `[0.7, 0.3]` | A | engine.py:341 |
| `momentumAccelThreshold` | `0.18` | A | engine.py:343,345 |
| `momentumZeroConfirmThreshold` | `0.15` | A | engine.py:358,361 |
| `momentumZeroWeights` | `[0.7, 0.3]` | A | engine.py:360,363 |
| `momentumZeroStrongConfirmThreshold` | `0.15` | A | engine.py:364 |
| `momentumZeroStrongConfirmBonus` | `5` | A | engine.py:365 |
| `movingAverageShortPeriod` | `5`（ma5） | A | engine.py:375 |
| `movingAverageLongPeriod` | `10`（ma10） | A | engine.py:376 |
| `cycleRankShockLookback` | `5`（velocities[-5:]） | A | engine.py:256 |
| `volumePriceNormalRatio` | `2.0`（量比正常上限，原硬编码 vr<=2.0） | A | engine.py RankTrendConfig（2026-08-17 参数化） |
| `atrPeriod` | `14`（ATR 简单均值周期） | A | engine.py RankTrendConfig（2026-08-17） |
| `atrRefPeriod` | `20`（close 参考均值周期） | A | engine.py RankTrendConfig |
| `atrChannelK` | `2.0`（通道倍数/偏离阈值） | A | engine.py RankTrendConfig |
| `atrDeepDeviation` | `3.0`（S 档绝对偏离阈值） | A | engine.py RankTrendConfig |
| `atrMaxHistoryBars` | `60`（历史 bar 截断窗口） | A | engine.py RankTrendConfig |
| `atrGapResetBars` | `2`（缺席帧断档重置阈值；跨日不恒重置） | A | engine.py RankTrendConfig |
| `atrAggregateByDay` | `False`（是否按日聚合） | A | engine.py RankTrendConfig |
| `atrBucketBySlot` | `False`（是否按 slot 分桶聚合） | A | engine.py RankTrendConfig |
| `crossSectionStrongMin` | `85`（A 档 percentile 下限） | A | engine.py RankTrendConfig（2026-08-17 方向 A） |
| `crossSectionStrongDeltaUp` | `5`（A 档 delta 上升确认） | A | engine.py RankTrendConfig |
| `crossSectionMidMin` | `50`（B 档中位下限） | A | engine.py RankTrendConfig |
| `crossSectionMidDeltaUp` | `15`（B 档 delta 显著上升） | A | engine.py RankTrendConfig |
| `crossSectionWeakMax` | `15`（D 档 percentile 上限） | A | engine.py RankTrendConfig |
| `crossSectionWeakDeltaDown` | `-5`（D 档 delta 下降确认） | A | engine.py RankTrendConfig |
| `crossSectionMidMax` | `50`（C 档中位上限） | A | engine.py RankTrendConfig |
| `crossSectionMidDeltaDown` | `-15`（C 档 delta 显著下降） | A | engine.py RankTrendConfig |

> MACD `hist = 2*(dif−dea)` 的 `2` 与 EMA `multiplier = 2/(period+1)` 的 `2` 均为标准公式系数，属数学定义，不需抽取（加注释说明即可）。

### 5.2 排名跳跃检测 `detect_rank_jumps`（engine.py:444-533）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `jumpDeltaPct` | `15`（已有 config 字段；函数默认参数 `10.0` 为死代码兜底，实际调用传 15） | A | engine.py:447 + config |
| `jumpResetLookback` | `3` | A | engine.py:487 |
| `jumpSustainCount` | `2`（surge/collapse ≥2） | A | engine.py:503 |
| `jumpMagFactorScale` | `2`（mag/(delta×2)） | A | engine.py:508 |
| `jumpOvershootFactorScale` | `1`（overshoot/delta） | A | engine.py:509 |
| `jumpSustainBonus` | `0.20` | A | engine.py:510 |
| `jumpConfidenceBase` | `55` | A | engine.py:511 |
| `jumpConfidenceSlope` | `25` | A | engine.py:511 |
| `jumpConfidenceOvershootSlope` | `15` | A | engine.py:511 |
| `jumpConfidenceSustainSlope` | `20` | A | engine.py:511 |

### 5.3 信号兜底 `fallback_signals`（engine.py:394-441）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `fallbackDirectionWeights` | `[0.4, 0.3, 0.2, 0.1]`（display/price/capital/volume） | A | engine.py:401 |
| `fallbackAccelWeights` | `[0.55, 0.25, 0.2]` | A | engine.py:402 |
| `fallbackZeroWeights` | `[0.5, 0.35, 0.15]` | A | engine.py:403 |
| `fallbackCapitalWeights` | `[0.6, 0.4]`（zlje/zljzb） | A | engine.py:400 |
| `fallbackDirectionThreshold` | `0.2` | A | engine.py:404 |
| `fallbackAccelThreshold` | `0.18` | A | engine.py:411 |
| `fallbackZeroDisplayMin` | `0.15` | A | engine.py:420 |
| `fallbackZeroPriceMin` | `0` | A | engine.py:420 |
| `fallbackZeroVolumeMin` | `-0.2` | A | engine.py:420 |
| `fallbackMomentumWeights` | `[0.45, 0.35, 0.2]` | A | engine.py:440 |

### 5.4 决策层 `compose_decision`（engine.py:913-949）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `decisionMinAgreement` | `2`（buy_count≥2） | A | engine.py:931 |
| `decisionMaxOpposition` | `1`（sell_count≤1） | A | engine.py:931,936 |
| `decisionConfidenceBase` | `50` | A | engine.py:943 |
| `decisionConfidenceSlope` | `25`（×abs(combined)） | A | engine.py:943 |
| `decisionAgreementSlope` | `15`（×agreement） | A | engine.py:943 |
| `decisionMarginSlope` | `10`（×tanh） | A | engine.py:943 |
| `decisionConfidenceMin/Max` | `50 / 95` | A | engine.py:943 |
| `decisionRiskPenaltyWeights` | `[11, 9, 5]`（overheat/divergence/synergy） | A | engine.py:945 |
| `decisionReversalFinalConfCap` | `62` | A | engine.py:948 |
| `decisionReversalPressureMin` | `0.78` | A | engine.py:946 |
| `decisionReversalOverheatMin` | `0.7` | A | engine.py:946 |
| `decisionReversalMarginMax` | `0.05` | A | engine.py:946 |

> 已有字段：`directionWeight/accelerationWeight/crossWeight/macdWeight/buyScoreThreshold/sellScoreThreshold/requireMacdGoldenCross` 保留不动。

### 5.5 共振 `analyze_rank_resonance`（engine.py:1077-1252）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `resonanceShortWindowBars` | `3` | A | engine.py:1077 |
| `resonanceMidWindowBars` | `8` | A | engine.py:1078 |
| `resonancePathWindowBars` | `8` | A | engine.py:1079 |
| `resonanceMinMarketSampleCount` | `20` | B | engine.py:1081 |
| `resonanceMomentumScale` | `15` | A | engine.py:1189 |
| `resonanceAccelerationScale` | `15` | A | engine.py:1190 |
| `resonancePathDirectionWeight` | `0.2` | A | engine.py:1215 |
| `resonanceDirectionThreshold` | `0.1` | A | engine.py:1216 |
| `resonanceWeights` | `[0.35, 0.25, 0.2, 0.2, 0.2]` | A | engine.py:1225-1230 |
| `resonanceReversalSwitchWeight` | `0.6` | A | engine.py:1210 |
| `resonanceReversalDrawdownWeight` | `0.4` | A | engine.py:1210 |
| `resonanceReversalDrawdownScale` | `20` | A | engine.py:1210 |
| `resonanceJumpFreshnessDecay` | `3` | A | engine.py:1214 |
| `resonanceEntryStrengthScale` | `25` | A | engine.py:1151 |
| `resonanceNewEntryWeights` | `[0.7, 0.3]` | A | engine.py:1152 |

> 已有字段 `jumpDeltaPct` 保留不动。

### 5.6 生命周期观察/决策（compose_observation_scores / lifecycle_decision）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `lifecycleWeights` | `[0.35, 0.25, 0.2, 0.2]` | A | engine.py:977-981 |
| `lifecycleMomentumWeights` | `[0.3, 0.45, 0.25]`（short/mid/accel） | A | engine.py:966-969 |
| `lifecycleMomentumScales` | `[15, 15, 8]` | A | engine.py:967-969 |
| `stageFitness` | `{expansion:1.0, ignition:0.8, crowded:0.35, cooling:0.2, reversal:0.0}` | B | engine.py:952 |
| `lifecycleMidLongCommitmentMin` | `15` | A | engine.py:724 |
| `lifecycleAccelCommitmentMin` | `8` | A | engine.py:724 |
| `lifecycleWeakPathCommitmentMax` | `0.45` | A | engine.py:726 |
| `lifecycleVelocityMin` | `18` | A | engine.py:727,737 |
| `lifecycleAccelMin` | `12` | A | engine.py:728,738 |
| `lifecycleLowVisibilityPathMax` | `0.7` | A | engine.py:736 |
| `lifecycleLowVisibilityMomentumMin` | `18` | A | engine.py:739-741 |
| `lifecycleHighRiskPressureMin` | `0.75` | A | engine.py:717 |
| `lifecycleHighRiskDivergenceMin` | `0.8` | A | engine.py:717 |
| `lifecycleHighRiskOverheatMin` | `0.7` | A | engine.py:717 |

### 5.7 周期状态机（cycle_metrics / raw_stage / normalize_stage / cycle_confidence）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `cycleMetricsWindow` | `8`（rank_window/percentile_window） | A | engine.py:571-572 |
| `cycleHotRankMax` | `10`（rank≤10） | A | engine.py:575 |
| `cycleHotPercentileMin` | `88`（percentile≥88） | A | engine.py:575 |
| `cycleStageWarmPercentileMin` | `65` | A | engine.py:601 |
| `cycleStageWarmBestMax` | `25` | A | engine.py:601 |
| `cycleStageHotPercentileMin` | `85` | A | engine.py:602 |
| `cycleStageHotBestMax` | `10` | A | engine.py:602 |
| `cycleStageRecoveryAccelMin` | `-1.2` | A | engine.py:603,626 |
| `cycleStageRecoveryPercentileMin` | `50` | A | engine.py:603,626 |
| `cycleStageRecoveryBestMax` | `30` | A | engine.py:603,626 |
| `cycleStageExpansionPercentileMin` | `70` | A | engine.py:604 |
| `cycleStageExpansionAccelMin` | `-1` | A | engine.py:604 |
| `cycleStageExpansionBestMax` | `20` | A | engine.py:604 |
| `cycleStageCrowdedHotMin` | `3` | A | engine.py:605 |
| `cycleStageCrowdedBestMax` | `5` | A | engine.py:605 |
| `cycleStageCrowdedDrawdownMax` | `1` | A | engine.py:605 |
| `cycleStageCrowdedVelocityMax` | `1` | A | engine.py:605 |
| `cycleStageReversalDrawdownMin` | `2` | A | engine.py:606,627 |
| `cycleStageReversalAccelMax` | `-1` | A | engine.py:606,627 |
| `cycleStageReversalHotMin` | `2` | A | engine.py:606 |
| `cycleStageSevereVelocityMax` | `-1` | A | engine.py:628 |
| `cycleStageSevereAccelMax` | `-2.5` | A | engine.py:628 |
| `cycleStageSevereDrawdownMin` | `3` | A | engine.py:628 |
| `cycleStageCoolingReadyPercentileMax` | `72` | A | engine.py:629,660 |
| `cycleStageCrowdedCarryPercentileMin` | `82` | A | engine.py:630 |
| `cycleStageCrowdedCarryBestMax` | `12` | A | engine.py:630 |
| `cycleConfidenceBase` | `50` | A | engine.py:678 |
| `cycleConfidenceStep` | `10` | A | engine.py:678 |
| `cycleConfidenceMin/Max` | `50 / 90` | A | engine.py:678 |

> `cycle_confidence`（engine.py:674-677）四组判定阈值，逐条列出（命名 `cycleConf*`）：
>
> | 字段名 | 当前值（按 cooling/ignition/expansion/crowded/reversal 五态） |
> |---|---|
> | `cycleConfRegionPercentileMax` | cooling `<60` / ignition `50≤p<80` / expansion `≥60` / crowded `≥82 or best≤10` / reversal `≥70 or best≤20` |
> | `cycleConfMomentumAccelMin` | ignition `≥−0.8` / expansion `≥−0.2` |
> | `cycleConfMomentumPercentileMin` | cooling `<60` / crowded `≥80` |
> | `cycleConfMomentumHotMin` | crowded `hot≥2` |
> | `cycleConfPersistenceHotMax` | cooling/ignition `hot≤1` / expansion `hot≤2` |
> | `cycleConfPersistenceHotMin` | crowded/reversal `hot≥2` |
> | `cycleConfPersistenceBestMax` | reversal `best≤10` |
> | `cycleConfDrawdownMax` | cooling `≤1 or p<60` / ignition `==0` / expansion/crowded `≤1` |
> | `cycleConfDrawdownMin` | reversal `≥1` |
> | `cycleConfVelocityMax` | cooling `≤0` / crowded `velocity≤0` / reversal `velocity≤0` |
> | `cycleConfAccelMax` | reversal `accel<−1` |

> 另 `replay` / `replay_frame_at` 的 `window_size=50`（engine.py:1366,1455）为历史窗口，B 类结构常量，命名 `replayWindowSize`。

### 5.8 风险 `analyze_risk`（engine.py:795-849）

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `riskPressureWeights` | `[0.58, 0.42]`（overheat/divergence） | A | engine.py:843 |
| `riskOverheatOffset/Scale` | `45 / 30` | A | engine.py:841 |
| `riskDivergenceOffset/Scale` | `40 / 30` | A | engine.py:842 |
| `riskStageOverheatMult` | `{ignition:0.3, expansion:0.55, crowded:0.85, reversal:1, cooling:0.3}` | B | engine.py:839 |
| `riskStageDivergenceMult` | `{ignition:0.35, expansion:0.65, crowded:0.9, reversal:1, cooling:0.35}` | B | engine.py:840 |
| `riskOverheatPenalties` | `[1.2, 12, 1.5, 4, 15, 5, 10, 18]` | A | engine.py:798-812 |
| `riskDivergencePenalties` | `[+10, +25, +18, +15, +8, +12, +12, −15, −10, −6]`（10 项，含符号：前三组为背离加分、后三组为流入减分） | A | engine.py:816-835 |

> `analyze_risk` 的逐项加减分系数（`overheat += max(0,percentile−70)*1.2` 等）共 17 项，实现时按语义逐条命名 `riskOverheat*` / `riskDivergence*`，此处列出主系数，实现阶段以实际行号为准确认。

### 5.9 候选池分层（compose_strategy 已 config 化 + compose_analysis_candidate_tier 重复硬编码）

⚠️ **`compose_analysis_candidate_tier`（engine.py:1296-1322）的硬编码阈值与 config 字段完全同值，须合并为同一组：**

| config 字段（compose_strategy 已用） | 硬编码值（compose_analysis_candidate_tier） |
|---|---|
| `tierExitRiskShortMomentumMax=-2` / `tierExitRiskAccelMax=-2` / `tierExitRiskPressureMin=0.55` | `short≤-2 or accel≤-2 or pressure≥0.55` |
| `tierCrowdedLongMomentumMin=4` / `tierCrowdedAccelMax=0` / `tierCrowdedRiskPressureMin=0.45` | `long≥4 and (accel≤0 or pressure≥0.45)` |
| `tierAMainMidMomentumMin=4` / `tierAMainShortMomentumMin=-1` / `tierAMainDivergenceSeverityMax=0.7` | `mid≥4 and short≥-1 and moneyRisk<0.7` |
| `tierBIgnitionShortMomentumMin=3` / `tierBIgnitionAccelMin=0.5` / `tierBIgnitionRiskPressureMax=0.65` | `short≥3 and accel≥0.5 and pressure<0.65` |

处理：`compose_analysis_candidate_tier` 改用 config 字段，删除裸写阈值。另 `compose_analysis_candidate_tier` 内的 `weak_market` 由 `regime_data["state"] in ("weak","retreat")` 判定，无数值参数。

### 5.10 市场环境 `market_regime`（engine.py:852-910）

已有模块级命名常量（保留，B 类）：

| 常量 | 当前值 | 位置 |
|---|---|---|
| `REGIME_STAGE_ADJUST` | `{高潮:8, 发酵:5, 启动:0, 退潮:-6, 冰点:-8}` | engine.py:852 |
| `REGIME_STRONG_SCORE` | `70` | engine.py:853 |
| `REGIME_NORMAL_SCORE` | `50` | engine.py:854 |
| `REGIME_WEAK_SCORE` | `30` | engine.py:855 |
| `REGIME_LIMIT_UP_CHANGE` | `9.8` | engine.py:856 |
| `REGIME_LIMIT_UP_BASE_SHARE` | `0.08` | engine.py:857 |

函数体内仍需抽取的 magic number（A 类）：

| 字段名 | 当前值 | 位置 |
|---|---|---|
| `regimeBaseScore` | `50` | engine.py:874 |
| `regimeUpShareOffset` | `0.5` | engine.py:879 |
| `regimeUpShareSlope` | `40` | engine.py:879 |
| `regimeUpShareClamp` | `[-20, 20]` | engine.py:879 |
| `regimeLimitShareSlope` | `80` | engine.py:884 |
| `regimeLimitShareClamp` | `[-15, 25]` | engine.py:884 |
| `regimeActiveVolumeRatioMin` | `1.2` | engine.py:888 |
| `regimeActiveShareOffset` | `0.35` | engine.py:889 |
| `regimeActiveShareSlope` | `10` | engine.py:889 |
| `regimeActiveShareClamp` | `[-5, 7]` | engine.py:889 |
| `regimeMoneyShareOffset` | `0.5` | engine.py:893 |
| `regimeMoneyShareSlope` | `20` | engine.py:893 |
| `regimeMoneyShareClamp` | `[-10, 10]` | engine.py:893 |

> `REGIME_*` 状态阈值（70/50/30）介于 A/B 之间：市场强/中/弱分界是业务口径，建议 B（命名常量），若要调再升 A。

### 5.11 量价 `volume_price.py`

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `volumePriceBase` | `50` | A | volume_price.py:157 |
| `volumePriceDirectionBuckets` | 八档 `[15,12,10,8,6,4,2,1]` 及阈值 `[limit,7,5,3,2,1,0.5,0]` | A | :63-85 |
| `volumePriceOverVolumeRatio` | `2.5` | A | :34 |
| `volumePriceAbnormalFundRatio` | `20.0` | A | :35 |
| `volumePriceShrinkRatio` | `0.95` | A | :126,139 |
| `volumePriceMildRatio` | `1.05` | A | :128,137 |
| `volumePriceVolumeScores` | 量价交叉档 `[25,20,15,10,5,−5,−10,−15,−20]` | A | :127-142 |
| `volumePriceFundScores` | 资金 `×3 / 10+(r−20)×0.5 / |r|×3 / min15 / ±5` | A | :148-155 |
| `synergyLowVp` | `40` | A | :220 |
| `synergyHighVp` | `75` | A | :221 |
| `synergyFundSuspectRatio` | `20`（复用 `volumePriceAbnormalFundRatio`） | A | :211 |
| `limitUp20Prefixes` | `(300, 301, 688, 689)` | B | :30 |
| `limitUp30Prefixes` | `(8, 4, 9)` | B | :31 |
| `limitUpPct` | `{20:19.8, 30:29.8, 10:9.8}` | B | :44-48 |

### 5.12 路由层 `ranktrend_routes.py`

| 字段名 | 当前值 | 类型 | 位置 |
|---|---|---|---|
| `resonanceVolumePriceWeight` | `0.15` | A | :476 |
| `resonanceVolumePriceVetoScore` | `40`（vp≤40 且 buy → hold，可复用 `synergyLowVp`） | A | :505 |
| `marketMedianLookback` | `3`（`index−3`） | B | :529 |
| `marketMedianMinWindow` | `4`（`len(window)<4`） | B | :533 |
| `marketMedianMinSample` | `20`（`len(changes)<20`，同 `resonanceMinMarketSampleCount`） | B | :541 |

### 5.13 C 类展示标签（不抽取，仅登记避免误判为遗漏）

以下为**展示层** magic number，属 C 类（文案/枚举分界），**不进入 config、不参与搜索**，实现时保持现状或在离散化方案（`ranktrend-observation-discrete-tiers-design.md`）中由 `signalTier` 取代：

| 常量 | 当前值 | 位置 |
|---|---|---|
| `_resonance_label` 档位分界 | `85/67/50/27`（非常强/强/中等/较弱/非常弱） | engine.py:1088-1097 |
| `STAGE_FITNESS`（已列 §5.6，B 类，不搜索） | `{expansion:1.0, ignition:0.8, crowded:0.35, cooling:0.2, reversal:0.0}` | engine.py:952 |
| `compose_strategy` 的 hotlist 阶段字符串 | `退潮/冰点/高潮/发酵/启动` | engine.py:1029,1039-1040 |
| `REGIME_STAGE_ADJUST` 的情绪阶段 key | `高潮/发酵/启动/退潮/冰点` | engine.py:852 |

> 这些数值/枚举若被误当成可调参数抽进 config，会制造无意义组合爆炸；登记在此仅为"无裸数字"审计的完整性，不改变抽取范围。

## 6. 回测调参链路打通

抽取完成后，链路自动成立：

```
新增字段进 RankTrendConfig（默认值=旧硬编码）
  → from_patch 自动可覆盖（无需改）
  → _STRATEGY_PARAM_KEYS 自动生成（4.2 改造后，标量字段自动入白名单）
  → default_search_space()/前端 search_space 引用该 key
  → 优化 runner 逐 trial 覆盖
```

需要同步改动的文件（实现阶段）：

| 文件 | 改动 |
|---|---|
| `backend/analysis/ranktrend/engine.py` | dataclass 加字段 + 函数签名接入 config + 替换硬编码 + **合并 compose_analysis_candidate_tier 的重复 tier 阈值** |
| `backend/analysis/ranktrend/volume_price.py` | 常量迁入 config / 命名常量，函数接收 config |
| `backend/api/ranktrend_routes.py` | `RESONANCE_VOLUME_PRICE_WEIGHT` 等改为读 config |
| `backend/optimization/search_space.py` | `_STRATEGY_PARAM_KEYS` 自动化 + `default_search_space()` 扩充共振/量价/风险/生命周期参数候选值 |
| 各调用点 | `compute_volume_price_score` / `compute_synergy_state` 调用处传入 config |

搜索空间扩充建议（`default_search_space()` 新增 A 类关键参数，每参数 3 个候选值控制组合规模）：

```python
{
  # 共振
  "resonanceMomentumScale": [10, 15, 20],
  "resonanceAccelerationScale": [10, 15, 20],
  "resonanceJumpFreshnessDecay": [2, 3, 5],
  # 量价
  "volumePriceOverVolumeRatio": [2.0, 2.5, 3.0],
  "volumePriceAbnormalFundRatio": [15, 20, 25],
  # 生命周期
  "lifecycleMidLongCommitmentMin": [10, 15, 20],
  # 决策
  "decisionConfidenceSlope": [20, 25, 30],
  "decisionMinAgreement": [1, 2, 3],
}
```

> 注意：list 类字段（`resonanceWeights`、`riskPressureWeights`、`lifecycleWeights` 等）不进标量白名单，其搜索用 `search_space` 的 choices 列表整体覆盖（`normalize_search_space` 已支持 `[list, list, ...]` 作为 choices），或放入 `base_strategy_config` 覆盖——需在 Phase 5 验证 choices-of-list 在 `candidate_at_index`/`suggest_params` 的兼容性。

## 7. 参数校准方法（抽取后的下一步）

参数统一入口只是前提，校准是目标。三类方法按成本递增：

1. **分位数归一化（优先，解决尺度拍脑袋）**：`resonanceMomentumScale=15`、`resonanceAccelerationScale=15`、`lifecycleMomentumScales=[15,15,8]` 这些除数，改用历史快照该指标的实际分布分位数（如 90% 分位）作为 scale，使 `clamp(x/scale, −1, 1)` 的 −1..1 真正对应"极端/正常"。**注意**：数据驱动 scale 会破坏 golden 可复现性，须作为 config 可选开关（默认用固定值，校准模式用分位数），校准结果回填为固定值再锁 golden。
2. **单因子敏感性/留一法（其次）**：对每个 A 类参数，固定其它参数，单变量扫描（如 ×0.5 / ×1 / ×2），看 `candidateTier` 分层比例、方向精度、未来 N 帧收益的边际变化，识别高敏感参数与冗余参数。
3. **权重网格搜索（最后）**：对 `resonanceWeights`、`lifecycleWeights`、`decisionWeights` 用优化 runner 的 `search_space` 做 grid/optuna，目标函数用回测方向精度 + 收益单调性（对齐前序 `ranktrend-observation-discrete-tiers-design.md` 第 9 节回测方案）。

校准产出：每个 A 类参数给出一张"敏感性报告"（参数值 → 目标函数），落 `quant-board/data/reports/`，不落库。

## 8. 实施步骤与验收命令

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | 清单已完整（本稿第 5 节，约 120 项）；实现前用 grep 对第 5 节行号做一次快速复核 | 行号与清单一致 |
| 2 | `RankTrendConfig` 扩展：A 类进 dataclass、B 类抽模块级命名常量，默认值=旧值 | `cd quant-board; .\.venv\Scripts\python.exe -m pytest` 全绿 |
| 3 | engine.py 函数接入 config，替换硬编码；**合并 compose_analysis_candidate_tier 重复 tier 阈值**；golden 对比确认默认行为不变 | golden case 全绿（`ranktrend-golden.md` 验收标准） |
| 4 | volume_price.py / ranktrend_routes.py 接入 config | pytest 全绿 + 量价 golden 对照 |
| 5 | `_STRATEGY_PARAM_KEYS` 自动化 + `default_search_space()` 扩充 | 单元测试：新增标量字段自动入白名单；最小 search_space 跑一次优化确认参数进入 strategy_config |
| 6 | 参数校准（第 7 节）：分位数/敏感性/网格，产出报告 | 报告满足敏感性/单调性验收，或给出参数修订结论 |
| 7 | 文档同步 | 更新 `ranktrend-golden.md` 配置节、`backtest-policy.md`、`architecture.md` |

## 9. 风险与回退

- **默认行为漂移**：字段默认值必须逐字对齐旧硬编码，否则 golden 漂移。缓解：每阶段跑 golden 对比，字段级 diff。
- **list 字段搜索兼容性**：`choices` 为 list 的搜索空间在 grid/optuna 采样的兼容性需 Phase 5 专门验证，不通过则 list 字段仅走 base_strategy_config 覆盖。
- **白名单自动化误纳**：`requireMacdGoldenCross`（bool）自动入白名单后，若 search space 未提供会走 `to_trade_config` 兜底——需确认 bool 字段不在 search space 时不影响基线（`to_strategy_config` 只映射 params 里出现的 key，不出现则无影响）。
- **合并 tier 阈值的行为一致性**：`compose_analysis_candidate_tier` 改用 config 字段后，须确认与 `compose_strategy` 的判定语义一致（两者除了阈值同值外，判定逻辑有细微差异：candidate_tier 用 `money_risk < 0.7`，strategy 用 `risk["divergence"]["severity"] < config.tierAMainDivergenceSeverityMax`，须逐条比对，不合并判定逻辑本身）。
- **回退**：全部改动集中在 config 字段与函数内部取值，`git revert` 即可恢复；无数据迁移、无 API 合同变化（输出字段不变，只改内部取值来源）。

## 10. 变更管理

- 实现前在 `ranktrend-golden.md` 配置节补充新增字段说明（A 类可调参数）。
- `strategy_version` / `ranktrend_version` 提升遵循 `ranktrend-golden.md` 变更管理流程。
- 校准后参数若变更默认值，必须同批更新 golden case 并重新跑 Layer 1/2 长测基线（`ranktrend-golden.md` 第 6 节）。
- 本计划为过程文档，落地验收后归档到 `quant-board/docs/` 专题目录，不在根目录新增过程文件。

## 12. 口径统一定义（2026-08-17 审计修正，G5-G7）

> 审计发现：趋势维度的 momentum/MA/MACD/zeroCross 全部计算在**排名百分位时序（percentiles）**
> 上，价格时序（change/close）只进量价（单帧）与 fallback（样本不足降级）。以下口径正式统一。

### 12.1 G5：MACD 金死叉 = 排名百分位 MACD（严格定义）

- `calculate_macd(percentiles, config)`——输入是**个股排名百分位时序**（0-100），非价格；
- **金叉/死叉语义**：dif（percentile 快 EMA−慢 EMA）上穿/下穿 dea，`hist = 2*(dif−dea)`；
- 含义：**排名动能的二次加速**，不是价格 MACD 黄金交叉——排名上升≠价格上涨；
- 已知偏差（不修，文档明确）：全市场普涨时个股排名不动但价格涨，排名 MACD 无反应；
  价格 MACD 不在本版本实现范围（趋势价格维另见 priceMomentum 观察，阶段 11 G1）。

### 12.2 G6：样本门槛口径统一（momentum 可计算 vs MACD 预热分离）

- **momentum 可计算门槛**：`get_momentum_min_samples = max(momentumPeriods)+1`（默认 14 帧）
  ——sampleQuality.ok 判定用此（阶段 2 修复，避免 50 帧窗口下 ok 占比被 MACD 预热压到 ~46%）；
- **MACD 预热**：`get_macd_min_samples`（fast+slow+signal 周期和）——仅控制 MACD 可用性，
  由 `_macd_diagnostics.hasStableObservationBars` 单独暴露（fail-visible），不进 sampleQuality；
- 统一结论：**趋势信号以 momentum 门槛为准，MACD 预热是附加诊断，不混入质量判定**。

### 12.3 G7：市场环境 = 热榜横截面 median 口径（明确边界）

- 市场环境唯一来源：`frame_cross_section`（八平台热榜合并 avgRankNum 的横截面 percentile）
  → 市场 median = 当前帧 percentile 中位数 / 短变化 = 当前帧 vs 前 3 帧 percentile 变化中位数；
- **无大盘指数**（指数数据未进快照）、**无全市场涨跌家数**——市场环境仅反映"热榜内部热度分布"，
  不代表全市场；结论引用时不得外推为大盘环境（阶段 10 crossSection 同源）。
