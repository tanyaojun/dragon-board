# RankTrend 早期大肉长测基线 V1 设计

日期：2026-06-07 | 状态：已确认实施

## 1. 结论

旧 `H1/H2/Q1` 三条长测基线验证的是生命周期分层买卖策略。该策略已经被连续 L1 红灯、收益表现和新样本研究共同证伪：

- 单靠 `A_MAIN/B_IGNITION` 生命周期分层买入卖出不能稳定产生收益。
- `finalSignal=buy` 不是早期大肉入口，`final=hold` 样本反而表现更好。
- 后续长测应切换到早期大肉结构，而不是继续复跑旧分层策略。

## 2. 旧基线处理

旧基线保留在文档中作为历史结论，但不再作为后续长测默认执行项：

| 旧标签 | 状态 | 原因 |
|--------|------|------|
| `H1_half_hour_current_bar` | retired | 生命周期分层策略已证伪 |
| `H2_half_hour_next_bar` | retired | 生命周期分层策略已证伪 |
| `Q1_quarter_hour_next_bar` | retired | quarter_hour 不再作为新策略主线 |

本地运行记录 `quant-board/data/reports/long_test_runs.jsonl` 可以清空，释放旧大 JSONL 占用。文档结论仍保留，避免丢失审计脉络。

## 3. 新三基线

新 baseline set 名称：

```text
early_big_move_v1
```

新策略名：

```text
ranktrend_early_big_move
```

三条基线：

| 标签 | 口径 | 用途 |
|------|------|------|
| `E1_half_hour_signal_forward40` | `half_hour`，候选召回统计，不做交易模拟 | 验证第一层硬候选是否持续召回大肉 |
| `E2_half_hour_ranked_current_bar` | `half_hour`，排序后 current_bar 模拟 | 验证实盘看到信号即时处理的乐观上限 |
| `E3_half_hour_ranked_strict_fill` | `half_hour`，同一排序，盘口/涨停/成交约束更严格 | 验证 E2 有多少来自抢跑或成交乐观偏差 |

`quarter_hour` 不进入新三主线，只作为后续压力测试或专题研究。

## 4. 候选规则

第一层硬候选：

```text
jump.direction = buy
jump.confidence >= 90
shortMomentum > 0
midMomentum > 0
longMomentum > 0
(momentumAcceleration >= 10 OR accDelta >= 8)
盘口可买
不是已封死涨停
```

第二层排序只加分，不硬过滤：

```text
stage in expansion / ignition
candidateTier in A_MAIN / B_IGNITION
当前涨幅在 3%-8.5%
direction = buy
zeroCross/MACD 确认
```

## 5. 实施边界

- 不写回 RankTrend 默认参数。
- 不自动下单。
- 不把新策略命名为 final buy。
- 不把 `finalSignal=buy`、`direction=buy`、`zeroCross/MACD` 作为硬前置。
- 宝鼎科技 `2026-05-21 09:30 002552` 必须作为回归样本保留：不能因 `final=hold / direction=hold / zeroCross=hold` 被排除。
