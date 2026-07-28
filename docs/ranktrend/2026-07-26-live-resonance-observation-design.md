# 实盘排名共振观察设计

## 目标与边界

以正交的排名证据替换 Dragon Board 的唯一 `finalSignal` 与“共振强度”展示，供实盘人工判断。`finalSignal`、候选池观察标记和 tooltip 必须来自同一个 `resonance` 结果；不自动下单、不做回测或参数搜索。

排名路径的唯一输入是“均榜关注度排名”：每帧按 `avgRankNum` 升序重排全部热榜股票，再换算为横截面百分位。不得直接使用 `rank`、`compRank` 或 `compScore`，因为后两者已混入主力资金、换手和成交额。`compRank` 只作为 tooltip 的“关注-资金一致性”诊断，不进入共振方向或分数。

交易池仍是唯一买卖决策点，但不再把 `finalSignal/finalConfidence` 纳入它的线性评分。它继续只消费 Jump、MACD、方向、加速度、零轴、生命周期和风险等原始执行证据，因此观察层的 final 改变不会直接改变交易池 `enter/exit`。

## 单一合同

不新增 `executionFinal`、`legacy_fallback` 或第二套特征层。`decision.final` 是唯一最终信号；`resonance` 是它唯一的解释来源。

```ts
{
  decision: {
    final: { signal: 'buy' | 'sell' | 'hold', confidence: number }
  },
  resonance: {
    status: 'ok' | 'insufficient'
    direction: 'buy' | 'sell' | 'hold'
    score: number // 0-100，仅用于观察排序；insufficient 时为 0
    label: '非常强' | '强' | '中等' | '较弱' | '非常弱' | '样本不足'
    relativeMomentum: number
    acceleration: number
    persistence: number // 0-1
    jumpFreshness: number // 0-1
    reversalPenalty: number // 0-1
    historyState: 'established' | 'new_entry'
    marketMedianShortChange: number
    reasons: string[]
  }
}
```

样本不足、时间乱序、当前帧缺失、横截面有效样本不足时，唯一 final 固定为 `hold/0`，`resonance.status='insufficient'` 且给出结构化原因；不回退旧 `composeDecision()` 结果。

## 计算与顺序

固定观察参数：短周期 3 bars、中周期 8 bars、路径窗口 8 bars、Jump 新鲜度衰减常数 3 bars。参数为模块私有常量，不作为交易参数暴露。

分析分两阶段执行：

1. 对每只股票收集包含当前帧且带帧身份的完整关注度 `ranks/percentiles`，检测本轮 Jump。横截面基准固定取“当前帧及其前 3 个市场帧”；只保留四帧全部存在、样本质量为 `ok/degraded` 的股票，至少 20 只才计算短周期百分位变化的横截面中位数。中位数在同一截面内共享，不是逐股字段。全市场时间轴质量只检查最近 `getMaxStableBars()` 个公共市场帧，避免单票 per-code 窗口带入的久远稀疏帧污染全市场；个股自己的中间缺帧仍按完整 per-code 窗口单独标记 `insufficient`。
2. 对每只股票使用同一份 Jump 和横截面基准计算 `resonance`，再写入唯一 `decision.final`。方向由相对动量、加速度和路径持续性决定；同向 Jump 仅增加新鲜度，反向 Jump 才覆盖为其反向方向。
3. 当前帧首次进入热榜而没有历史关注度位置时，明确标记 `historyState='new_entry'`。它以当前关注度百分位计算新入榜动量；不伪造“此前末位”排名，也不因历史长度对分数作乘法扣减。该状态只表示尚未形成持续性证据，不改变交易池独立决策。

```text
relativeMomentum = clamp((shortChange - marketMedianShortChange) / 15, -1, 1)
acceleration = clamp((shortChange - midChange * 3 / 8) / 15, -1, 1)
persistence = 同方向相邻变化数 / 有效相邻变化数
jumpFreshness = exp(-barsSinceLatestJump / 3)
reversalPenalty = clamp(0.6 * directionSwitchRate + 0.4 * percentileDrawdown / 20, 0, 1)
buyRaw = 0.35*positive(relativeMomentum) + 0.25*positive(acceleration)
       + 0.20*persistence + 0.20*jumpFreshness - 0.20*reversalPenalty
score = round(100 * clamp(buyRaw, 0, 1))

newEntryStrength = clamp((currentAttentionPercentile - 50) / 25, 0, 1)
newEntryRaw = 0.70*newEntryStrength + 0.30*jumpFreshness
newEntryScore = round(100 * clamp(newEntryRaw, 0, 1))
```

卖出方向按上述特征的负向镜像解释，不把买入 score 取反。无 Jump 的持续上涨可以是 `buy`；没有证据时才为 `hold`。

## 消费边界

- 主看板 `finalSignal`、候选池 `candidateResonanceObserve`、表格共振强度和 tooltip 读取同一个 `rankTrend.resonance`。候选池观察门槛使用 `status=ok`、`direction=buy`、`score>=85`，不再叠加旧 final/votes/Jump 门槛。
- `DataTable` 的“共振强度”与 tooltip 仅呈现 `resonance` 的六项因子、横截面基准和样本状态；交易池评分只能以独立标识呈现，不能作为共振 tooltip 的内容。
- 交易池 `computeResonanceScore()` 删除 `finalSignal/finalConfidence` 因子，并维持其余原始执行信号与风险门槛。为现有输入补稳定性回归测试，明确观察 final 的变化不直接驱动交易池状态。
- Dragon Board Fusion V5 当前不读 `decision.final`，保持不变。QuantBoard 仍以现有 Python golden 的 `decision.final` 执行；本轮 live-only resonance 不导出到 QuantBoard golden/replay，不触发其策略语义变化。

## 实盘验证与验收

1. 002298 的完整当前帧序列给出 `direction=buy`，且持续上升即使没有新的 Jump 也不会被强制为 `hold`。
2. 相同绝对涨幅、不同市场相对动量的股票分数不同；高反转、低样本或缺当前帧的股票被惩罚/标记，不能显示“非常强”。
3. `finalSignal`、候选观察标记、共振强度与 tooltip 指向同一 `resonance`；tooltip 不创建交易池条目。
4. 只改 `decision.final/resonance` 的对照输入不改变交易池 `enter/exit`。浏览器确认桌面与移动端 tooltip 无溢出、无控制台错误。
5. 仅改变资金、换手或成交额而保持八平台排名不变时，关注度 RankTrend 与 resonance 不变；当前首次进入热榜前 50 的股票不因历史缺席被按样本长度折分。

## 本次验证记录

- `pnpm exec vitest run src/services/dataLoader/__tests__/PlatformHotlistService.test.ts`：2/2 通过；MongoDB 白名单不可用时不请求平台，空名称或 `active=false` 的记录不进入热榜。
- `pnpm test:ranktrend`：22 个测试文件、231 个用例通过；包含 002298 当前帧 Jump 与共振方向回归。
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：退出码 0。
- `git diff --check`：无空白错误；合同扫描确认仅在设计文字中出现“不得创建 `executionFinal`”，代码没有第二个 final，且 QuantBoard golden/replay 未引用 `resonance`。
- 实测 208 只代码、50 bars、`rank_basis=attention` 的 MongoDB 查询在复合索引建成后为 1.36 秒（建索引前为 18.4 秒）。浏览器实盘验收确认三列可快速完成；tooltip 的“市场中位数（同帧共享）”现只使用当前和此前 3 个共同市场帧，缺任一帧的股票不参与基准。
