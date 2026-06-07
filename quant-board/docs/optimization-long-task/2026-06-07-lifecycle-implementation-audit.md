# RankTrend 生命周期实现审计

## 结论

生命周期分层实现不能继续被当成可靠买卖标签。它在 V3 主线里有解释价值，但目前更适合作为 RankTrend 路径上下文和排序辅助，而不是硬入场、硬过滤或独立买卖系统。

本次审计只读代码和已落库回测，不修改策略代码，不新增默认规则。

## 审计范围

代码入口：

- `src/services/rankTrend/attentionCycleAnalyzer.ts`
- `src/services/rankTrend/candidateTierComposer.ts`
- `src/services/RankTrendAnalyzer.ts`
- `quant-board/backend/analysis/ranktrend.py`
- `quant-board/backend/core/backtest/execution.py`
- `quant-board/backend/core/backtest/strategy.py`

回测证据：

- 4 月 V3 current-bar / 30 bars：`bt_a80a2e51db204882`
- 5 月 V3 current-bar / 30 bars：`bt_24bce043660b48ec`
- 5 月 A_MAIN 风险过滤：`bt_6880bb325d604045`
- 5 月 B_LONG 过滤：`bt_1d12cc19e20d492e`

## 实现审计发现

### 1. 生命周期阶段本体仍含固定位置阈值

Python 与 TS 的生命周期阶段判断都使用了固定分位和固定名次条件，例如：

- warm / hot 区域依赖 `currentPercentile`、`bestRecentRank`
- hot streak 依赖高热区连续次数
- reversal 依赖从近期最好名次回撤

这类阈值本身不是错误，但它们不是纯粹的 RanTrend 动量加速度模型。若把阶段名直接理解为“主升/点火确定成立”，会把排名位置、历史高热停留和趋势结构混在一起。

### 2. 阶段归一化存在强状态惯性

`normalize_stage` / `normalizeAttentionStage` 会把 raw stage 平滑成最终 stage。好处是减少抖动，坏处是：

- 一旦进入 `expansion` 或 `crowded`，短期走弱不一定立刻反映；
- 假主升可能被继续保留为 `expansion`;
- `rawStage` 与 `stage` 不一致时，交易层如果只看 `stage` 会漏掉路径风险。

V3 4 月+5 月已成交样本中，`rawStage != stage` 的 3 笔全部盈利，说明“不一致”不是简单坏信号，但也证明单点 stage 不能解释全部路径。

### 3. Python 回测主链和 TS golden 已出现候选分层合同漂移

TS `composeCandidateTier` 使用 `market_regime` 控制 A/B 分层，Python `compose_strategy` 当前使用 `hotlistSentiment` 控制 A/B 放行：

- TS：`regime.state` 参与弱势/退潮判断；
- Python：`hotlist_stage`、`hotlist_risk` 控制 A_MAIN / B_IGNITION；
- Python 的 `market_regime(frame)` 仍计算，但候选分层实际主要消费热榜情绪。

这不必然是 bug，但它已经不是纯 TS golden 复刻。后续必须明确：Python 回测策略使用的是“RankTrend + 热榜情绪”版本，而不是纯前端 golden 分层。

### 4. A_MAIN / B_IGNITION 对生命周期阶段依赖过硬

Python 候选分层链路：

```text
A_MAIN:
  stage == expansion
  momentum.mid >= tierAMainMidMomentumMin
  momentum.short >= tierAMainShortMomentumMin
  trend_buy
  hotlist 高潮/发酵 且非高风险
  divergence severity 不高

B_IGNITION:
  stage == ignition
  momentum.short >= tierBIgnitionShortMomentumMin
  momentum.acceleration >= tierBIgnitionAccelMin
  hotlist 高潮/发酵/启动
  pressure 不高
```

因此 `stage` 一旦判错，A/B/C/D 会同时错。当前 V3 入场又依赖 `candidateTier in A_MAIN/B_IGNITION`，所以生命周期并非只是展示字段，而是实质参与入场候选生成。

### 5. 当前测试覆盖不足以证明生命周期实现可靠

TS 生命周期测试只有少量边界样例：

- cooling -> ignition
- 高热回撤 reversal
- 单个高热快照不误判 reversal

Python 侧有一个 crowded/rawStage 持续性的边界测试，以及若干候选分层阈值测试。缺口：

- 没有真实交易路径上的 TS/Python 全量对齐测试；
- 没有覆盖 A_MAIN 假主升路径；
- 没有覆盖强 long B_IGNITION 假突破；
- 没有验证 `rawStage/stage/transition/entryAdvice` 对后验收益的解释力。

## 回测证据

### V3 原始 4 月 + 5 月

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 27 | 74.1% | +158,615.21 | +3.33% |
| A_MAIN | 17 | 76.5% | +113,687.83 | +3.83% |
| B_IGNITION | 10 | 70.0% | +44,927.38 | +2.50% |
| stage=expansion | 17 | 76.5% | +113,687.83 | +3.83% |
| stage=ignition | 10 | 70.0% | +44,927.38 | +2.50% |
| long >= 10 | 20 | 90.0% | +136,626.74 | +4.03% |
| long < 10 | 7 | 28.6% | +21,988.47 | +1.34% |
| final=buy | 5 | 60.0% | +602.29 | -1.26% |
| final!=buy | 22 | 77.3% | +158,012.92 | +4.38% |

解释：

- `expansion/ignition` 并非无效，主线收益确实来自这两个阶段。
- 但 `entryAdvice=preferred` 并不强于 `watch`，不能当强买点。
- `final=buy` 和 MACD golden 继续表现偏弱，不能恢复成入场硬确认。
- `long >= 10` 很强，但硬过滤真实复跑失败，因为会改变资金和排序路径。

### 失败复跑给出的反证

A_MAIN 风险过滤 5 月略增 totalReturn，但 4 月明显变差，且 B 侧贡献恶化。B_LONG 过滤更明确失败：

| Window | Strategy | Run ID | totalReturn | winRate | stops |
| --- | --- | --- | ---: | ---: | ---: |
| 4 月 | V3 原始 | `bt_a80a2e51db204882` | +6.76% | 90.00% | 1 |
| 4 月 | B_LONG 过滤 | `bt_3a6339356fe44ef2` | +3.64% | 80.00% | 2 |
| 5 月 | V3 原始 | `bt_24bce043660b48ec` | +14.81% | 64.71% | 3 |
| 5 月 | B_LONG 过滤 | `bt_1d12cc19e20d492e` | +5.33% | 56.25% | 5 |

关键原因不是 `long` 特征完全无效，而是硬过滤改变了排序、现金、仓位空位和后续可买票，导致：

- 弱 B 小亏被删除；
- 强 long 假突破如 `603993`、`000657` 被买入；
- `603459 红板科技` 这类低 long 但中周期和加速度极强的大肉被间接错过。

## 风险分级

| 风险 | 级别 | 说明 |
| --- | --- | --- |
| 生命周期阶段被当成买卖事实 | 高 | 目前 evidence 不支持恢复旧生命周期买卖系统 |
| TS/Python 候选分层合同漂移 | 高 | Python 回测使用 hotlistSentiment，TS 使用 market_regime |
| `stage` 掩盖 `rawStage` 路径抖动 | 中高 | 假主升可能被最终 stage 平滑成 expansion |
| `entryAdvice` 被误当强买点 | 中 | preferred 不强于 watch |
| 用静态硬过滤优化生命周期 | 高 | A_MAIN / B_LONG 真实复跑均不稳定 |

## 审计结论

生命周期实现不是完全错误，但当前使用方式过重。

应保留：

- `rawStage`
- `stage`
- `transition`
- `metrics.rankVelocity`
- `metrics.rankAcceleration`
- `metrics.drawdownFromPeak`
- `hotZoneStreak`

但它们只能作为路径解释、排序降权、风险标签和报告诊断，不能作为默认硬买卖系统。

下一轮正确方向不是继续修补生命周期分层，而是做“去生命周期硬门槛”的对照审计：

```text
入场主轴:
  jump 高置信
  多周期动量同步转正
  动量加速度突然抬升
  可成交性

生命周期:
  不制造买点
  不硬过滤
  只参与排序降权和风险解释
```

## 下一步验证建议

1. 新增 research-only 对照策略，不覆盖 V3：
   - 不依赖 `candidateTier=A_MAIN/B_IGNITION` 作为硬门槛；
   - 使用 early big move 第一层结构；
   - 生命周期只作为排序项或 report-only 字段。
2. 增加 TS/Python 生命周期对齐测试：
   - 至少覆盖大肉、假主升、强 long 假突破、低 long 大肉四类路径。
3. 给回测报告新增生命周期审计诊断：
   - 按 `rawStage/stage/transition/entryAdvice` 聚合胜率、收益、止损数；
   - 标记 `rawStage != stage`；
   - 标记 `stage` 与后验收益冲突的样本。
4. 不再新增生命周期静态硬过滤，除非通过 4 月、5 月、全量三组真实复跑。
