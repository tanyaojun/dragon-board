# RankTrend 早期大肉结构研究记录

日期：2026-06-07 | 状态：研究结论已形成，待二级过滤与样本外验证

## 1. 结论

当前 half_hour 样本显示，`jump buy 高置信 + 动量加速度抬升 + short/mid/long 同步转正 + 盘口可买` 是有效的早期大肉候选结构。

但它不能直接作为最终买入规则。更稳妥的口径是两层：

1. 第一层生成早期大肉候选。
2. 第二层按阶段、候选分层、当前涨幅位置和辅助确认排序，不做过硬过滤。

核心变化是：不要再等待 `finalSignal=buy` 才入场。当前样本中 `final=hold` 反而更接近早期大肉结构。

## 2. 样本条件

基础条件：

```text
jump.direction = buy
jump.confidence >= 90
shortMomentum > 0
midMomentum > 0
longMomentum > 0
momentumAcceleration 抬升
盘口可买
不是已封死涨停
```

本轮统计条件描述为：

```text
jump buy 高置信 + 动量加速度抬升 + short/mid/long 同步转正 + 盘口可买
```

## 3. 总体结果

| 指标 | 结果 |
|------|------|
| 候选数 | 1524 |
| 后续 40 bars 正收益概率 | 84.8% |
| 后续 40 bars 最大涨幅 >= 10% | 30.6% |
| 后续 40 bars 平均最大涨幅 | 8.08% |
| 后续 40 bars 中位最大涨幅 | 4.49% |

解释：

- 该结构能稳定捕捉到后续上涨概率较高的早期异动。
- 大肉率约 30.6%，说明它是候选生成器，不是最终交易规则。
- 候选数 1524 偏大，后续必须增加二级排序和实盘观察分层。

## 4. 典型样本：宝鼎科技

样本：

```text
2026-05-21 09:30 002552 宝鼎科技
```

当时信号：

| 字段 | 值 |
|------|----|
| jump | 94.2 |
| momentum | (18.7, 12.8, 14.3) |
| acc | 27.2 |
| direction | hold |
| zeroCross | hold |

后续表现：

| 窗口 | 最大涨幅 |
|------|----------|
| max10 | 18.46% |
| max20 | 28.76% |
| max40 | 50.49% |

宝鼎科技说明：过硬依赖 `finalSignal=buy`、`direction=buy`、`zeroCross/MACD` 会漏掉最关键的早期点火样本。

## 5. 关键发现

### 5.1 final buy 不是好入口

`final=hold` 的样本比 `final=buy` 更像早期大肉：

| finalSignal | 后续 40 bars 大肉率 |
|-------------|----------------------|
| hold | 31.4% |
| buy | 26.0% |

结论：`finalSignal=buy` 不能作为早期大肉入口前置条件。它更适合做确认或后续状态解释。

### 5.2 阶段比 MACD/zeroCross 更有用

| stage | 后续 40 bars 大肉率 |
|-------|----------------------|
| expansion | 37.9% |
| ignition | 32.8% |
| cooling | 21.5% |

结论：阶段应进入优先级排序；`zeroCross/MACD` 只做确认，不做硬门禁。

### 5.3 候选分层有参考，但不能硬套

| candidateTier | 后续 40 bars 大肉率 | 平均最大涨幅 |
|---------------|----------------------|--------------|
| A_MAIN | 42.4% | 11.03% |
| B_IGNITION | 32.9% | 待补充 |
| N_NEUTRAL | 26.8% | 待补充 |

结论：`A_MAIN` 和 `B_IGNITION` 应加权排序，但不能排除全部 `N_NEUTRAL`，否则会漏掉尚未被分层模型识别的早期票。

### 5.4 涨幅位置不是越低越好

当前涨幅 `6%-8.5%` 的样本，大肉率为 `39.9%`，高于低位样本。

结论：大肉点火经常已经有明显异动，不应因为已经涨了 5、6 个点就直接排除。当前涨幅更适合作为优先级特征，而不是简单低位过滤。

## 6. 建议规则

### 第一层：早期大肉候选

硬条件：

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

说明：

- 第一层只负责召回早期结构。
- 不要求 `finalSignal=buy`。
- 不要求 `direction=buy`。
- 不要求 `zeroCross/MACD` 已确认。

### 第二层：优先级排序

排序加分从高到低：

```text
stage in expansion / ignition
candidateTier in A_MAIN / B_IGNITION
当前涨幅在 3%-8.5%
direction = buy
zeroCross/MACD 确认
```

说明：

- 第二层只排序，不做硬过滤。
- `direction=buy` 是加分项，不是必需项。
- `zeroCross/MACD` 是确认项，不是入场前置。
- 该排序应保留宝鼎科技这类 `direction=hold`、`zeroCross=hold` 但 jump 和动量已经很强的样本。

## 7. 非目标

本轮不做以下事情：

- 不把该结构直接写成最终自动买入规则。
- 不写回 RankTrend 默认参数。
- 不用 `finalSignal=buy` 反向覆盖当前结论。
- 不把 `A_MAIN/B_IGNITION` 写成唯一允许层。
- 不根据单一 half_hour 样本宣称已经可实盘自动化。

## 8. 下一步验证

1. 对第一层候选做样本外验证，至少按交易日做 chronological split。
2. 为第二层排序建立 score breakdown，输出每个加分项和总分。
3. 复核盘口可买定义，区分有买一/卖一、涨停封单、快照价回退和容量约束。
4. 单独统计 `final=hold` 中的优质样本，确认是否存在可解释的共性。
5. 回放宝鼎科技、江波龙等典型样本，检查是否会被新版排序靠前召回。

## 9. 实施提醒

后续如进入代码实现，应优先落在 QuantBoard 研究链路或 RankTrend 信号服务的公开口径中，并补最小测试：

- 候选生成：覆盖 `final=hold` 仍可入选。
- 排序：覆盖 `stage/candidateTier/change/direction/zeroCross` 只加分不硬过滤。
- 执行现实性：覆盖封死涨停不可买、盘口缺失回退、低样本量原因输出。
