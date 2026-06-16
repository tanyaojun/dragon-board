# 交易池共振入池——全链路诊断与优化方向

**日期**: 2026-06-16
**状态**: 历史诊断；B+D 已按统一合同落地
**关联**: [2026-06-15 交易池强共振自动入池规格](./2026-06-15-trading-pool-resonance-auto-entry-spec.md)
**关联**: [2026-06-16 交易池实时投影接入设计方案](./2026-06-16-trading-pool-live-data-integration-design.md)
**当前口径**: 本文中的 `strongConsensus` AND 门、BuyVotes “共振评级”和涨停硬过滤均为当时诊断对象；当前实现以 [交易池统一合同](./2026-06-16-trading-pool-unified-contract.md) 的评分状态机、`共振评分` tooltip 和 `limitUp` 分轨为准。

## 1. 诊断过程

### 1.1 实测数据采集

在真实盘面（2026-06-16，A股全面上涨）使用 Playwright 采集 219 只八平台热榜股票的完整信号矩阵：

| 指标 | 数值 |
|------|------|
| 热榜覆盖 | 219 只 |
| Jump 置信度均值 | 78.5% |
| Jump 置信度 ≥ 80 | 88/219 (40.2%) |
| Jump 置信度 ≥ 85 | 59/219 (27.0%) |
| Jump 信号触发 (checkEntryConditions) | **0/219 (0%)** |
| strongConsensus 通过（估计） | **0** |
| 交易池实际入池 | **0** |

### 1.2 标本分析：华天科技 002185

以用户提供的华天科技 tooltip 数据为标本，逐层追踪判决链路：

**原始信号：**

| 维度 | 值 | 判定 |
|------|-----|------|
| 综合判断 finalSignal | buy, 80% | 买入 |
| Jump 方向 | **hold** | 非买入 |
| Jump 置信度 | **50%** | 偏低 |
| 方向一致性 | buy, 69.60% | ✓ |
| 动量加速度 | buy, 64.05% | ✓ |
| 零线交叉 | hold, 50% | ✗ |
| MACD | **金叉** | ✓ |
| BuyVotes | 3/4 | 方向+加速度+MACD |
| 生命周期 | allow | ✓ |
| 分层 | A_MAIN | ✓ |

**三层门禁判决：**

```
Jump 入口 (checkEntryConditions 6条件)
  ├─ sustainedSurge     ?
  ├─ momentumResonance  ?
  ├─ changePct > 0      ?
  ├─ 非涨停              ?
  ├─ MACD金叉/零轴上     ✓
  └─ confidence ≥ 85    ✗ (50%)
  → 未触发 ❌

交易池 (strongConsensus 8条件 AND)
  ├─ finalSignal=buy    ✓
  ├─ finalConf ≥ 85     ✗ (80%)
  ├─ buyVotes ≥ 3       ✓ (3/4)
  ├─ jumpDir=buy        ✗ (hold)
  ├─ jumpConf ≥ 80      ✗ (50%)
  ├─ trendBuyCount ≥ 2  ✓
  ├─ !candidateHardBlock ✓
  └─ macd != death      ✓
  → 降级观察 ❌

候选池 (V5/Fusion)
  ├─ Jump方向: 阻断 (hold, 要求buy)
  ├─ Jump置信度: 阻断 (50, 要求≥90)
  └─ 加速度: 阻断 (2.56, accDelta<8)
  → 被阻断 ❌
```

**矛盾：** DataTable tooltip 显示"共振评级: 强共振 (BuyVotes: 3/4)"，但三个池子全部拒绝。Tooltip 用 BuyVotes 纯计数定义共振，而判决系统用多层 AND 门定义共振——同一只票在 UI 上告诉用户"强共振"，在系统内部连观察资格都没有。

## 2. 根因分析

### 2.1 三层 AND 门夹杀模型

当前系统对一只票进入交易池需要同时通过三层全 AND 筛选：

```
八平台热榜 219 只
  │
  ├─ 第1层: checkEntryConditions (6条件 AND)
  │   通过率: 0/219 (0%)
  │   主要淘汰: sustainedSurge + momentumResonance + confidence≥85
  │
  ├─ 第2层: strongConsensus (8条件 AND)
  │   输入: 第1层通过的票 (0只)
  │   通过率: N/A
  │   主要淘汰: jumpDirection≠buy + jumpConf<80 + finalConf<85
  │
  └─ 第3层: V5/Fusion 候选池 (minJumpConfidence=90)
      输入: 第2层通过的票 (0只)
      通过率: N/A
      主要淘汰: Jump置信度<90 + accDelta<8
```

**三层 AND 叠加后，219 只热榜票中 0 只入池。**

### 2.2 Jump 方向的结构性缺陷

强情绪全面上涨市场中，大量股票的排名被整体抬升，个股之间的排名相对变化趋缓。Jump 的方向判定依赖排名变化速率——当大家都在涨的时候，大部分股票的排名不会剧烈跃迁，Jump 方向自然偏向 hold。

219 只票中 Jump 方向为 hold 的占多数（华天科技即为此类），而 jumpDirection=buy 是 `strongConsensus` 第 4 条硬要求。这意味着**在全面上涨市场中，系统倾向于认为大部分票"不够强势"**——这与市场实际情况相悖。

### 2.3 涨停过滤的自伤机制

`checkEntryConditions` 第 4 条 `changePct >= limitPct - 0.3` 将涨停和接近涨停的票系统性排除。在 150+ 涨停的市场中，排名跃迁最快、Jump 信号最强的票全部被这一条过滤掉。剩下的票（未涨停或温和上涨）Jump 天然偏低，又被第 6 条（置信度≥85）过滤。

这是一个**结构性矛盾**：Jump 信号最强的票被涨停规则删除，剩下的票 Jump 不够强被 AND 门拒绝。两条规则各自合理，叠加后产生空集。

### 2.4 共振定义的语义分裂

三个系统对"共振"给出了三种互不兼容的定义：

| 系统 | 共振定义 | 阈值 | 用途 |
|------|---------|------|------|
| DataTable tooltip | BuyVotes 纯计数 ≥ 3 | 无 | 用户看到的"强共振"标签 |
| 交易池 strongConsensus | 8 条件 AND | Jump≥80, final≥85, buyVotes≥3 | 状态机入场判决 |
| 候选池 V5/Fusion | minJumpConfidence | 90（balanced 模式） | 候选资格门禁 |

**Tooltip 给用户看"强共振"，候选池和交易池同时拒绝。这是信息架构层面的缺陷——用户接收到的信号与系统实际行为脱节。**

### 2.5 Final 置信度与 Jump 的同源性

华天科技的 finalConfidence=80%（差 5 个点过 85% 门槛）和 jumpConfidence=50%（差 30 个点过 80% 门槛），两者同源——都受排名跃迁动量不足的影响。在 `strongConsensus` 中它们被当作两个独立条件分别否决，造成"双重惩罚"效应。

## 3. 优化方向

### 3.1 方向 A：语义对齐（低风险，必须做）

**目标：** Tooltip 的共振评级不再自算一套，改为直接从交易池/候选池状态派生。

**具体改动：**
- DataTable `getTradingPoolActionPreview()` 的 `resonanceLabel` 不再用 BuyVotes 纯计数，改为：
  - 交易池状态 = 观察买点/准备介入 → "强共振"
  - 交易池状态 = 观察中 → "待确认"
  - 交易池状态 = 已退出 → 不显示共振评级
- `confidence` 列 tooltip 新增 Jump 方向展示（当前缺失）

**收益：** 消除"UI 说强共振、系统拒绝入池"的矛盾。用户看到的信息与系统决策一致。

**风险：** 消除了 tooltip 的"预告"能力——被 AND 门挡住但技术面好的票不会在 tooltip 上显示强共振。

### 3.2 方向 B：AND 门结构调整（中高风险，需讨论）

**目标：** 降低 Jump 单点失败的杀伤力，让 MACD+方向+加速度的技术共振有独立权重。

**方案 B1：加权评分替代 pure AND**

`strongConsensus` 从 8 条件 AND 改为加权评分：

| 条件 | 权重 | 说明 |
|------|------|------|
| MACD = golden | 3 | 金叉是强信号，独立加分 |
| finalSignal = buy | 2 | 综合判断方向 |
| buyVotes（每票 1 分） | 1-4 | 四维子信号投票 |
| jumpDirection = buy 且 conf ≥ 80 | 2 | Jump 共振 |
| jumpDirection = buy 且 conf ≥ 60 | 1 | Jump 弱共振（新增档位） |
| trendBuyCount ≥ 2 | 1 | 趋势方向确认 |
| 无 hardBlock | 1 | 无硬阻断 |
| 无 doubleRisk | 1 | 无双风险 |

总分 ≥ 阈值（如 7/14）→ 强共振。华天科技：MACD(3)+final(2)+buyVotes(3)+jump弱(1)+trend(1)+noBlock(1)=11分，通过。

**方案 B2：分层 AND 替代单层 AND**

| 层级 | 条件 | 通过后状态 |
|------|------|-----------|
| 硬门槛（必须全过） | lifecycle≠veto, macd≠death, !hardBlock, !doubleRisk | 基础资格 |
| 软门槛A（过 3/4） | final=buy, buyVotes≥3, trendBuyCount≥2, jumpDir=buy | 观察买点 |
| 软门槛B（过 2/4 + finalConf≥85） | 同软门槛A的条件 | 准备介入 |

**风险：** 加权评分引入了新的主观参数。分层 AND 减少了 Jump 的单点否决权但保留了方向要求。

### 3.3 方向 C：信息透明（低风险，必须做）

**目标：** 让用户看清被挡原因，不是只显示"观察中"。

**具体改动：**
- 交易池面板中状态为"观察中"的行，新增"被挡原因"列或 tooltip：
  - 列出 8 条件中哪些通过、哪些未通过
  - 例如华天科技："6/8 通过。Jump方向=hold, Jump置信度=50%"
- 候选池规则矩阵中已展示被拒原因（Jump方向/Jump置信度/加速度），交易池对标补齐

**收益：** 不改任何判定逻辑，只改信息呈现。用户不再困惑于"为什么这只票看起来很好却不在池里"。

### 3.4 方向 D：涨停票分轨处理（中风险，后续讨论）

**目标：** 涨停票不直接排除，而是走单独的观察轨道。

**具体思路：**
- 涨停票不由 `checkEntryConditions` 第 4 条直接排除
- 涨停票走"涨停观察"子轨道，标记风险标签为 `limit_up`
- 交易池中涨停票显示为"涨停观察"而非直接丢弃
- 开板后（changePct 回落）自动重新评估

**风险：** 涨停追入是高风险操作，需要更严格的 T+1 和止盈止损逻辑配合。

### 3.5 方向 E：Jump hold 不应直接否决 strongConsensus（低风险）

**目标：** Jump 方向为 hold 时，不直接否决 strongConsensus，改为降权。

**具体改动：**
- `strongConsensus` 第 4 条 `jumpDirection == null || jumpDirection === 'buy'` → 允许条件下级 relaxation
- Jump 方向为 hold 时，要求 jumpConfidence ≥ 另一个较低阈值（如 60%）作为补偿
- Jump 方向为 sell 时，仍然否决

**收益：** 华天科技这类 Jump=hold 的技术共振票不再被一条否决。风险：引入了对 Jump 方向的降级容忍。

## 4. 优先级建议

| 优先级 | 方向 | 理由 |
|--------|------|------|
| P0 立即 | 方向 A（语义对齐） | 消除用户看到的虚假信号，零风险 |
| P0 立即 | 方向 C（信息透明） | 不改逻辑只改展示，极大改善调试体验 |
| P1 讨论后决定 | 方向 E（Jump hold 降权） | 改动最小，精准解决华天科技型问题 |
| P1 讨论后决定 | 方向 B1/B2（AND 结构调整） | 系统性解决，但风险较高需谨慎 |
| P2 后续 | 方向 D（涨停分轨） | 需要配合 T+1 和风控逻辑，不宜单独推出 |

## 5. B+D 最终方案（2026-06-16 确认）

### 方案 B：离散 + 连续混合评分

**三大离散维度（天然二值/三值，不做连续映射）：**

| 维度 | buy 态 | neutral 态 | sell 态 |
|------|--------|-----------|---------|
| MACD cross | golden → **+3** | none → **0** | death → **-3** |
| Jump 方向 | buy → **+2** | hold → **0** | sell → **-2** |
| 生命周期 | allow → **0** | — | veto → **-99**（硬否决） |

**五大连续维度（0~100 置信度线性映射）：**

| 维度 | 权重 | 公式 | 得分区间 |
|------|------|------|---------|
| Jump 置信度 | 2.0 | `conf/100 × 2.0 × 5` | 0 ~ 10 |
| 综合 final 置信度 | 1.5 | `conf/100 × 1.5 × 5` | 0 ~ 7.5 |
| 方向一致性置信度 | 1.0 | `conf/100 × 1.0 × 5` | 0 ~ 5 |
| 动量加速度置信度 | 1.0 | `conf/100 × 1.0 × 5` | 0 ~ 5 |
| 零线交叉置信度 | 0.5 | `conf/100 × 0.5 × 5` | 0 ~ 2.5 |

**状态判定阈值：**

| 状态 | 条件 |
|------|------|
| 准备介入 | 总分 ≥ 20 + MACD=golden + Jump 置信度 ≥ 80% |
| 观察买点 | 总分 ≥ 15 |
| 观察中 | 总分 ≥ 8 |
| 已退出 | 总分 < 8 或 lifecycle=veto |

**华天科技试算：** MACD(+3) + Jump hold(0) + veto(0) + Jump50%(5.0) + final80%(6.0) + 方向69.6%(3.48) + 加速度64.05%(3.20) + 零线50%(1.25) = **21.93** → 观察买点

### 方案 D：涨停观察子轨道（D1）

`checkEntryConditions` 条件 4 从硬排除改为标记：

- 未涨停 → 正常通过
- 已涨停/近涨停 → 标记 `riskFlags: ['limit_up']`，状态 = `涨停观察`，decision = `watch`
- 涨停票不自动入场，需人工确认
- 开板后（changePct < 9%）自动触发重算，信号仍在可升级

### B+D 组合链路

```
八平台热榜 219 只
  │
  ├─ Jump 6条件入口（第4条改为标记）
  │    ├─ 通过 → 进入交易池评分
  │    └─ 涨停 → "涨停观察"，不自动入场
  │
  ├─ 交易池混合评分
  │    ├─ ≥20 + MACD金叉 + Jump≥80% → 准备介入
  │    ├─ ≥15 → 观察买点
  │    ├─ ≥8  → 观察中
  │    └─ <8 或 veto → 已退出
  │
  └─ 开板自动重新评分
```

## 6. 实施记录 (2026-06-16)

### 已实施：方向 A + C + E

**方向 E — Jump hold 降权 (commit: 待提交)**

- `TradingPoolThresholds` 新增 `jumpHoldMinConfidence`（recall_first: 50, balanced: 60, strict: 70）
- `strongConsensus` 的 `jumpDirectionPass`：Jump=hold 且置信度≥阈值时允许通过（sell 仍否决）
- 华天科技型的 Jump=hold 票不再被一条否决，但需要过 jumpConfidence ≥ recallJumpMin 才能完整通过 strongConsensus

**方向 A — 语义对齐 (commit: 待提交)**

- DataTable tooltip 的共振评级改为从交易池状态派生：观察买点/准备介入 → "强共振"，观察中 → "待确认"
- Tooltip 新增 Jump 方向展示（买入/卖出/观望）
- 消除了"tooltip 显示强共振但系统拒绝"的矛盾

**方向 C — 信息透明 (commit: 待提交)**

- `TradingPoolConsensusBreakdown` 类型：8 条件逐条 pass/fail + passedCount
- 交易池详情区展示 `N/8 通过` 的条件矩阵（绿色=通过/红色=失败）
- 用户可以看到每只票具体被哪些条件挡住

**验证:** 104 files / 792 tests passed, vue-tsc exit 0, RankTrend 221 tests zero regressions.
