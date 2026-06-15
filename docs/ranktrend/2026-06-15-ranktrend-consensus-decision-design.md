# RankTrend Consensus Decision Design

**Goal:** 将 RankTrend 的最终方向从“强单项可越过加权阈值”调整为“共识门槛决定方向、加权强度决定置信度和排序”。

**Architecture:** `resultComposer` 继续聚合方向一致性、动量加速度、零线交叉和 MACD 四个排名趋势信号。最终 `decision.final.signal` 先通过同向票数和反向票数门槛确认方向，再用现有加权分数、风险扣分和样本质量解释置信度。

**Tech Stack:** TypeScript、Vitest、Vue tooltip 展示、RankTrend golden 兼容输出。

---

## 背景

当前 `src/services/rankTrend/resultComposer.ts` 的最终判断是加权阈值模型：

- 方向一致性：`directionWeight = 0.3`
- 动量加速度：`accelerationWeight = 0.25`
- 零线交叉：`crossWeight = 0.2`
- MACD：`macdWeight = 0.25`
- 买入阈值：`buyScoreThreshold = 0.12`
- 卖出阈值：`sellScoreThreshold = -0.12`

这个模型会出现“1 个强买入 + 其它观望”直接输出买入的情况。用户在 DataTable tooltip 中看到的是四个离散信号，容易按“共振票数”理解综合判断，因此当前结果和盯盘直觉不一致。

需要保留加权模型的价值：它能表达信号强弱、排序优先级和置信度。但最终方向不应由单个强信号单独决定。

---

## 目标口径

RankTrend 最终方向采用“共识门槛 + 加权强度”：

```text
买入：
buyVotes >= 2
且 sellVotes <= 1
且 combinedScore >= buyScoreThreshold

卖出：
sellVotes >= 2
且 buyVotes <= 1
且 combinedScore <= sellScoreThreshold

否则：
hold
```

其中四个投票来源为：

1. `technical.signals.direction.signal`
2. `technical.signals.acceleration.signal`
3. `technical.signals.zeroCross.signal`
4. `technical.macd.cross` 转换后的 MACD 方向：
   - `golden` -> `buy`
   - `death` -> `sell`
   - `none` -> `hold`
   - 未识别值 -> `hold`

加权分数仍使用四个组件的 `rawScore * weight` 汇总。票数决定方向是否成立，分数决定方向强弱和置信度。

---

## 决策分层

`decision` 保留两层语义：

1. `decision.base.signal`
   - 由四个排名趋势信号的共识门槛和 `combinedScore` 共同决定。
   - 表示“技术共振方向是否成立”。
   - 单个强信号即使让 `combinedScore` 越过阈值，也不能让 `base.signal` 从 `hold` 变为 `buy` 或 `sell`。
2. `decision.final.signal`
   - 默认继承 `decision.base.signal`。
   - 继续经过现有风险保护，例如 reversal 阶段、高压力、高过热且 margin 极窄时，把弱买入翻转为 `hold`。
   - 面板、DataTable、候选池和兼容输出读取的最终方向应以这一层为准。

数据流：

```text
technical signals + MACD
  -> votes + combinedScore
  -> decision.base
  -> risk / cycle protection
  -> decision.final
```

---

## 样例验收

以下样例是本次口径的核心验收标准。

| 股票 | 方向一致性 | 动量加速度 | 零线交叉 | MACD | 预期综合判断 | 原因 |
| --- | --- | --- | --- | --- | --- | --- |
| `002747` 埃斯顿 | 观望 | 买入 | 观望 | 无 | 观望 | 买入票只有 1 个，不满足买入共识 |
| `002812` 恩捷股份 | 买入 | 卖出 | 观望 | 无 | 观望 | 多空冲突且买入票不足 2 个 |
| `002409` 雅克科技 | 卖出 | 观望 | 观望 | 无 | 观望 | 卖出票只有 1 个，不满足卖出共识 |
| `601208` 东材科技 | 买入 | 买入 | 买入 | 金叉 | 买入 | 4/4 买入强共振 |
| `002463` 沪电股份 | 卖出 | 卖出 | 卖出 | 死叉 | 卖出 | 4/4 卖出强共振 |
| `002149` 西部材料 | 观望 | 卖出 | 观望 | 死叉 | 卖出 | 2/4 卖出且无买入反对票 |

---

## 置信度口径

`decision.final.confidence` 继续表达证据强度，不等同于方向票数。

保留现有置信度主结构：

- `combinedScore` 越远离阈值，置信度越高。
- 反向权重越少，置信度越高。
- `risk.overheat`、`risk.divergence`、`risk.synergy` 继续扣减最终置信度。
- reversal 高压高过热且 margin 极窄时，仍允许把买入翻转为观望。

新增约束：

- 若共识门槛未通过，`final.signal` 必须为 `hold`。
- 未通过共识门槛时，置信度计算保持现有公式和 `baseSignal = 'hold'` 路径：`opposingWeight = Math.min(positiveWeight, negativeWeight)`。
- 未通过共识门槛时，`base.scoreMargin` 固定为 `0`，避免在没有明确方向的 `hold` 路径中暴露买入或卖出阈值余量。
- 这时 `final.confidence` 表示“证据强弱和分数距离阈值”，不表示“观望本身的确信度”。
- UI 如显示 `hold + 高置信度`，应解释为“有强单项或强分数，但共振不足”，而不是“强烈建议观望”。
- UI 如后续调整，应把“共振票数”和“加权强度”分开展示，避免把置信度误解为买卖建议。

本次不调整置信度公式，避免把方向口径和强度口径同时改动。若后续发现 `hold + 高置信度` 仍造成误读，应单独设计 UI 文案或新增 `consensus` 解释字段，而不是在本次算法修复中混入第二套置信度模型。

---

## MACD 输入边界

当前 TypeScript 类型中 `technical.macd.cross` 的稳定取值是：

- `golden`
- `death`
- `none`

`resultComposer` 的转换函数必须继续对未识别值兜底为 `hold`。这样即使历史数据、兼容数据或外部导入误传了其它字符串，也不会凭未知 MACD 值产生买入或卖出投票。

---

## 非目标

- 不改变方向一致性、动量加速度、零线交叉和 MACD 的底层计算公式。
- 不改变 RankTrend 默认运行参数和权重配置。
- 不把 Dragon Board 根项目扩展成回测平台。
- 不改 QuantBoard 存储、API、快照读写或历史窗口方案。
- 不改变候选池、交易池和生命周期分层规则；它们只消费新的 `decision.final.signal`。

---

## 影响面

主要影响：

- `src/services/rankTrend/resultComposer.ts`
- `src/services/rankTrend/__tests__/resultComposer.test.ts`

实现后必须检查：

- `src/components/common/DataTable.vue` tooltip 文案是否需要说明共识票数。
- `src/components/panels/RankTrendPanel.vue` 是否需要展示共振票数。
- `src/services/quantBoardGolden/**` 回放输出是否依赖旧 finalSignal。
- `docs/attention-manual.md` 中“综合判断怎么用”的说明是否需要更新。

本阶段先改算法合同和测试。UI 文案增强可以作为后续独立小任务。

---

## 成功标准

1. 单个强买入信号不能单独让 `decision.final.signal` 变成 `buy`。
2. 单个强卖出信号不能单独让 `decision.final.signal` 变成 `sell`。
3. 2 个同向信号、无强反向冲突且加权分数过阈值时，可以形成对应方向。
4. 4 个同向信号必须形成强方向。
5. 多空冲突时优先观望，除非同向票数和加权分数同时满足门槛。
6. 现有风险扣分和 reversal 翻转保护继续生效。
7. RankTrend 测试通过：`pnpm test:ranktrend`、`pnpm typecheck:ranktrend`。
