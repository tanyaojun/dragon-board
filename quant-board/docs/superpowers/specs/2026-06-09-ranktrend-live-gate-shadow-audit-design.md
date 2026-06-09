# RankTrend Live Gate Shadow Audit Design

日期：2026-06-09 | 状态：待执行

## 1. 背景

当前 Dragon Board 实盘候选入口对 `ranktrend_early_big_move_v3_lifecycle_fusion` 使用了多层前置硬门槛：

- jump 检测使用 TypeScript live 侧固定 `delta=15`
- `jump.confidence >= 90`
- `change < 6`
- `sampleQuality.status == ok`
- `candidateTier in A_MAIN / B_IGNITION`
- `B_IGNITION` 额外要求 `mid >= 20 && zeroCross == buy`
- `acceleration >= 10 || accDelta >= 8`

近期实盘观察显示，这套入口对部分盘中强票召回不足。典型现象不是生命周期辅助 veto，而是 jump / fusion 前置门槛过硬，导致技术面已经明显转强的股票仍显示“未触发”。

2026-06-09 的盘中样本说明了这一点：

- `600186 莲花控股`：direction / acceleration / zeroCross 已同步转强，但仍被 jump/fusion 硬门槛拦下
- `002156 通富微电`：用户盘中观察为较好买点，但 live 入口未召回，需要拆解是 jump 方向翻转、confidence 不足，还是后续融合门槛再次否决

本次任务不直接改 live 自动入池逻辑，先做 research-only shadow audit。

## 2. 目标

在最近一周的 `half_hour` 实盘快照上，以“召回优先”为导向，对 live 候选前置门槛做 shadow audit，回答三个问题：

1. 当前漏票主要卡在哪些硬条件
2. 哪些条件更适合从“硬 veto”降级为“候选召回 + 二次排序”
3. 如果放宽召回，新增候选主要集中在哪些结构，是否仍保持可读性

## 3. 非目标

- 不修改生命周期辅助策略主链
- 不直接改 `ranktrend_early_big_move_v3_lifecycle_fusion` live 自动入池代码
- 不写回默认参数到 Python / TypeScript golden / CLI / 前端默认值
- 不把本次审计直接包装成新的正式实盘策略
- 不先以收益率为唯一标准筛选变量；本轮先解决召回缺口

## 4. 审计范围

### 4.1 时间范围

- 主窗口：最近一周 `half_hour` 快照
- 重点交易日：`2026-06-09`
- 输出必须能单独解释 `2026-06-09` 的逐帧漏票原因

### 4.2 策略范围

- 基线对象：当前 Dragon Board live 候选入口
- 审计对象：jump / fusion 前置门槛
- 保持不变：生命周期辅助策略逻辑、trade journal 语义、候选池主状态链

### 4.3 股票范围

- 全市场最近一周 frame 级逐帧扫描
- 重点样本单独出具说明：
  - `600186`
  - `002156`

## 5. 审计基线

当前 live 基线口径按现有 TypeScript 实现定义：

### 5.1 Jump 入场硬门槛

以 [jumpSignalService.ts](</d:/dragon-board/src/services/rankTrend/jumpSignalService.ts:87>) 为准：

- `jump.event == jump`
- `jump.direction == buy`
- `jump.sustained == true`
- `direction.signal == buy`
- `acceleration.signal == buy`
- `change > 0`
- 非涨停
- `MACD cross == golden`
- `jump.confidence >= 85`
- jump 检测固定使用 `delta=15`

### 5.2 Fusion 候选硬门槛

以 [fusionStrategy.ts](</d:/dragon-board/src/services/rankTrend/fusionStrategy.ts:38>) 为准：

- `jump.direction == buy`
- `jump.confidence >= 90`
- `short > 0 && mid > 0 && long > 0`
- `acceleration >= 10 || accDelta >= 8`
- `change < 6`
- 非涨停
- `sampleQuality.status == ok`
- `cycle.decision.action != veto`
- `candidateTier == A_MAIN`
  或 `candidateTier == B_IGNITION && mid >= 20 && zeroCross == buy`

### 5.3 Python/研究侧参考口径

Python RankTrend 默认 `jumpDeltaPct = 10`，见 [ranktrend.py](</d:/dragon-board/quant-board/backend/analysis/ranktrend.py:50>)。因此本次审计需要显式比较：

- live 侧 `delta=15`
- research/golden 侧 `delta=10`

## 6. Shadow 变量矩阵

本次 shadow audit 固定基线，然后只审以下 5 组变量，不扩散到无关参数：

### 6.1 Jump Delta

- 基线：`delta=15`
- 对照：`delta=10`
- 对照：`delta=13.6` 左右的中间值

目的：

- 验证 `delta=15` 是否是近期漏票的首要来源
- 判断中间值能否比 `10` 更平衡

### 6.2 Jump Confidence

- 基线：`>= 90`
- 对照：`>= 85`
- 对照：`>= 80`

目的：

- 验证 high-confidence hard gate 是否过严
- 观察降低阈值后新增候选的结构质量

### 6.3 当前涨幅限制

- 基线：`change < 6`
- 对照：移出硬门槛，只作为排序项

目的：

- 验证“已经涨到 5%-8% 仍是早期强票”的盘感是否在最近一周成立

### 6.4 Sample Quality

- 基线：`sampleQuality == ok`
- 对照：允许 `degraded`，但输出必须打黄标

目的：

- 验证早盘或跨窗口样本不足是否正在误杀可观察票
- 不允许把 `insufficient` 直接放进候选

### 6.5 accDelta 缺失处理

- 基线：`acceleration >= 10 || accDelta >= 8`
- 对照：当 `accDelta` 缺失时，不作为额外否决项，只看 `acceleration`

目的：

- 验证 live 链路中 `accDelta` 缺失是否在无形中提高了门槛

## 7. 二次排序诊断

本轮不是只做“放宽后数量变化”，还要看新增召回票如何排序。以下字段进入二次排序诊断，但默认不作为新增硬 veto：

- `stage`
- `candidateTier`
- `direction.signal`
- `zeroCross.signal`
- `MACD cross`

排序原则：

1. `stage in ignition / expansion` 优先
2. `candidateTier in A_MAIN / B_IGNITION` 优先
3. `direction == buy` 加分
4. `zeroCross == buy` 加分
5. `MACD golden` 加分

本轮目标是验证这些字段更适合做排序，而不是继续当前这种前置过滤。

## 8. 输出结构

审计结果必须至少输出三层内容。

### 8.1 层 1：逐票漏票归因

对重点样本输出逐帧解释，至少包含：

- 时间点
- 当前 baseline 是否触发
- 放宽后的各 shadow 变体是否触发
- 卡住它的第一层硬条件
- 如果解除硬条件，应处于什么排序位置

### 8.2 层 2：召回变化表

按交易日统计：

- baseline 候选数
- 每种 shadow 变体新增候选数
- 每种 shadow 变体减少漏票数
- 新增候选的 stage / tier 分布

### 8.3 层 3：排序建议表

输出一版建议分类：

- 继续保留为硬门槛的条件
- 降级为排序项的条件
- 只作为展示解释的条件

## 9. 成功标准

本轮 success criteria 按“召回优先”定义，不以最终收益率为首要门槛。

优先级顺序：

1. 能重新召回 `600186`、`002156` 这类盘中强票，或明确证明其中某票并不应召回
2. 明显减少“技术面转强但候选池未触发”的情况
3. 新增候选主要集中在 `ignition / expansion`，而不是大量低质量噪音
4. 能形成一版清晰的“硬门槛 -> 排序项”建议

## 10. 实施边界

### 10.1 允许做的事

- 新增 research-only 审计脚本 / 服务
- 复用现有 Python RankTrend replay 能力
- 输出文档、统计表和典型样本解释

### 10.2 不允许做的事

- 不直接修改 live 候选池触发逻辑
- 不在本轮把 shadow 审计结果自动写回正式策略
- 不扩大到生命周期主链或 trade journal 语义改造

## 11. 后续顺序

如果本轮 shadow audit 结论清晰，后续正式改动顺序应是：

1. 先改 jump/fusion 召回层
2. 再补排序层
3. 最后才考虑是否把新口径并入 live 自动入池

换句话说，先把“漏掉该看的票”解决，再处理“如何在更多票里排优先级”。

## 12. 设计结论

本次最小正确路径不是直接改 live，而是：

- 先用最近一周 frame 级数据重放 baseline 与 5 组 shadow 变体
- 先定位哪些漏票来自 `delta / confidence / change / degraded / accDelta`
- 再决定哪些条件应该从硬门槛降级为排序项

这样能在不破坏当前实盘链路的前提下，先把“为什么漏票”与“放宽后会多出什么票”讲清楚。
