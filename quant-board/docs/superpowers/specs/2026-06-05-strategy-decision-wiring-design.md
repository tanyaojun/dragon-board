# RankTrend 策略信号链路修复：compose_decision 接入交易决策

## 背景

排查发现当前 `rank_trend_candidate` 策略存在架构性缺陷：

- `compose_decision()` 使用用户配置的 MACD(21,34,13)+动量(3,5,8,13,21)+权重(0.3/0.25/0.2/0.25)+阈值(0.12/-0.12) 合成 `finalSignal`，但 `TradeSimulator._entry_candidates()` 从不读取此字段
- 实际买卖决策仅由 `compose_strategy()` 产出的 `candidateTier` 驱动，其中分层阈值（如 `momentum["mid"] >= 4`）全部硬编码，不可配置
- 这解释了 L1 方向精度仅 39%（低于随机 50%）：A_MAIN 分层本质是"排名趋势处于扩散期"，不是"技术指标看涨"

## 目标

1. `compose_decision.final.signal` 成为入场/出场的**主驱动信号**
2. `candidateTier` 降级为**语境过滤**（A_MAIN/B_IGNITION 才有入场资格）
3. `compose_strategy()` 中所有硬编码分层阈值改为 `RankTrendConfig` 可配参数
4. 不改动 `compose_decision()` 和 `compose_strategy()` 的计算内核，只改消费侧

## 设计

### 入场规则（AND 逻辑）

```
if compose_decision.final.signal != "buy":  → hold (不买)
if candidateTier not in {A_MAIN, B_IGNITION}: → hold
if regime == "retreat": → hold
if B_IGNITION 且非连续确认: → watch
→ buy, 按 confidence 排序
```

### 出场规则

原有规则叠加 `final.signal == "sell"`：

```
任一满足即卖出:
  - compose_decision.final.signal == "sell"
  - candidateTier == "D_EXIT_RISK"
  - candidateTier == "C_CROWDED" && momentum.acceleration <= 0
  - rank > 50
  - holdingBars >= maxHoldingBars
  - grossReturn <= stopLoss
  - grossReturn >= takeProfit
```

### 可配置分层阈值

在 `RankTrendConfig` 新增 7 个字段，替换 `compose_strategy()` 硬编码：

```python
# compose_strategy 分层阈值（所有硬编码值替换为配置字段）
tierAMainMidMomentumMin: float = 4.0
tierAMainShortMomentumMin: float = -1.0
tierAMainDivergenceSeverityMax: float = 0.7

tierBIgnitionShortMomentumMin: float = 3.0
tierBIgnitionAccelMin: float = 0.5
tierBIgnitionRiskPressureMax: float = 0.65

tierCrowdedLongMomentumMin: float = 4.0
tierCrowdedAccelMax: float = 0.0
tierCrowdedRiskPressureMin: float = 0.45

tierExitRiskShortMomentumMax: float = -2.0
tierExitRiskAccelMax: float = -2.0
tierExitRiskPressureMin: float = 0.55
```

### 影响文件

| 文件 | 改动 |
|---|---|
| `quant-board/backend/analysis/ranktrend.py` | `RankTrendConfig` 加字段；`compose_strategy()` 用配置替换硬编码 |
| `quant-board/backend/core/backtest/execution.py` | `_entry_candidates()` 加 `finalSignal` 过滤；`TradeSimulator.run()` 出场加 `finalSignal == "sell"` |
| `quant-board/backend/core/backtest/strategy.py` | `_entry_signal()` / `_exit_signal()` 同步 `finalSignal` 逻辑 |
| `quant-board/tests/test_quant_board.py` | 新策略逻辑集成测试 |
| `quant-board/tests/test_money_flow_quality_gate.py` | 分层阈值配置化测试 |

### 不改动

- `compose_decision()` 计算逻辑
- `compose_strategy()` 分层判定逻辑（只换参数来源）
- `RankTrendPythonEngine.replay()` 信号生成流程
- `TradeSimulator` 的撮合、T+1、手续费、滑点等基础设施

## 验证

1. `cd quant-board && .venv/Scripts/python.exe -m pytest` — 所有现有测试通过
2. 新 checkpoint 复跑：`run-longtest-baselines --checkpoint-id checkpoint_2026-06-05_strategy_fix`
3. 对比修复前后 H1/H2/Q1 绩效和 L1 方向精度变化
4. 确认交易数合理下降、方向精度改善
