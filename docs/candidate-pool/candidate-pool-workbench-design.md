# 候选池工作台整改优化方案

**日期**: 2026-05-17
**状态**: 待评审
**方案选择**: 方案 2，候选池工作台版
**AI 能力边界**: 第一版采用规则解释型，不接外部大模型

## 1. 结论

自选股和候选池不合并为一个概念。自选股保留为轻量关注和板块管理；候选池升级为正式交易研究工作台，负责入池理由、交易假设、买入前提、失效条件、状态流转、规则解释型 AI 分析和复盘样本沉淀。

第一版重点不是重写后端，而是把前端入口和工作流做对：

```text
行情列表右键发现股票
  -> 加入候选池
  -> 自动生成规则分析与信号快照
  -> 候选池工作台跟踪状态
  -> 触发/跳过/跟踪/复盘
  -> QuantBoard journal 存储沉淀样本
```

## 2. 当前问题

### 2.1 产品问题

- 当前“候选与交易假设”面板是字段堆叠表单，依赖手工输入，和真实盘中使用路径脱节。
- 候选记录入口藏在下拉菜单里，用户发现股票时不能顺手入池。
- “抓取信号”是被动按钮，不是入池时自动完成。
- 自选股、板块、候选/交易假设之间没有明确语义边界。
- 当前列表不能表达候选优先级、触发条件、风险和后续复盘状态。
- 面板视觉和交互不符合工作台型应用，应从“录表单”改为“管理候选样本”。

### 2.2 技术问题

- `TradeJournalPanel.vue` 承载了类型、API、表单、信号抓取、列表、复盘、截图等职责，文件职责偏重。
- `DataTable.vue` 右键菜单适合作为入口，但不应直接拼 journal payload。
- `favorite.ts` 已修复为自选股唯一 store，不应继续扩张成候选生命周期 store。
- `/api/journal` 后端字段合同基本可用，应复用，不新增本地候选持久化双轨。
- 候选分析缺少独立服务，导致 AI 能力无法测试、复用和解释。

## 3. 设计目标

第一版完成后应支持：

- 右键行情列表股票，选择“加入候选池”。
- 系统自动生成候选分析，包括评分、入池理由、交易假设、买入前提、失效条件、风险提示。
- 自动保存当前信号快照：行情、RankTrend、题材、龙头/地位、市场情绪、资金流。
- 候选池工作台展示候选列表、分析摘要、状态、风险、触发条件和复盘入口。
- 保留手工编辑能力，但不再以手填表单作为主体验。
- 自选股仍可独立使用，候选股可选同步加入自选，但不强制所有自选进入候选池。
- 候选记录继续走 QuantBoard `/api/journal`，为后续研究和回测留样本。

## 4. 不做什么

- 第一版不接 OpenAI 或其他外部 LLM。
- 第一版不自动交易、不生成买卖指令。
- 第一版不批量扫描全市场自动入池。
- 第一版不重写 QuantBoard journal 后端。
- 第一版不把候选状态塞进 `favorite_data`。
- 第一版不修改刷新机制相关未提交改动。
- 第一版不做复杂仓位、手续费、滑点、真实成交归因。

## 5. 概念边界

### 5.1 自选股

职责：

- 快速收藏。
- 本地分组和板块。
- 当前行情同步展示。
- 导入/导出。

不负责：

- 候选状态。
- 交易假设。
- 模型复盘。
- 样本统计。

### 5.2 候选池

职责：

- 交易研究样本。
- 入池理由和信号快照。
- 状态流转：`observe`、`candidate`、`triggered`、`tracking`、`reviewed`。
- 模型结果、执行结果、复盘结论。
- 未来进入 QuantBoard 统计验证。

候选股不等于买入建议，只表示“值得跟踪的交易假设样本”。

## 6. 用户流程

### 6.1 盘中发现

1. 用户在行情列表看到股票。
2. 右键股票。
3. 点击“加入候选池”。
4. 系统打开候选池浮层或轻量确认弹窗。
5. 系统自动完成分析草稿：
   - 入池评分。
   - 主要理由。
   - 买入前提。
   - 失效条件。
   - 风险提示。
   - 当前信号快照。
6. 用户可直接保存，也可调整状态和备注。

### 6.2 盘中跟踪

1. 打开候选池工作台。
2. 按状态、评分、题材、风险过滤。
3. 查看每只候选的分析卡。
4. 将状态从观察推进到候选、触发、跟踪或跳过。
5. 系统保留每次状态和核心字段更新。

### 6.3 盘后复盘

1. 打开候选池工作台的“复盘”视图。
2. 对已跟踪或已过期候选记录复盘。
3. 填写：
   - 复盘结果。
   - 模型结果。
   - 执行结果。
   - 复盘标签。
   - 复盘结论。
4. 后续由 QuantBoard 汇总候选质量。

## 7. 候选分析引擎

新增前端服务建议命名：

```text
src/services/candidate/CandidateAnalysisService.ts
```

### 7.1 输入

```typescript
interface CandidateAnalysisInput {
  stock: Stock
  allStocks: Stock[]
  createdFrom: 'datatable-context-menu' | 'favorite-panel' | 'manual'
  now: number
}
```

服务内部只读获取：

- `dataLayer.getStock(code)`
- `dataLayer.getStocks()`
- `getRankTrendAnalysis(stock)`
- `themeFacade.getStockExposures(code)`
- `themeFacade.getRotationSummary()`
- `dragonReviewService.getLatestReview()`
- `dragonBreathAnalyzer.getMarketSentiment()`

### 7.2 输出

```typescript
interface CandidateAnalysisResult {
  score: number
  grade: 'A' | 'B' | 'C' | 'D'
  suggestedStatus: 'observe' | 'candidate' | 'triggered'
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  riskWarnings: string[]
  strengths: string[]
  weaknesses: string[]
  evidence: CandidateRuleEvidence[]
  penalties: CandidateRuleEvidence[]
  structuredThesis: CandidateStructuredThesis
  structuredRisks: CandidateStructuredRisk[]
  tags: string[]
  signalsSnapshot: Record<string, unknown>
}
```

### 7.3 评分维度

建议 100 分制：

| 维度 | 权重 | 来源 |
|------|------|------|
| RankTrend 候选分层 | 30 | `rankTrend.strategy.candidateTier` |
| 题材共振 | 20 | `themeFacade.getStockExposures()` |
| 龙头/市场地位 | 20 | `dragonReviewService.getLatestReview()` |
| 市场情绪 | 15 | `dragonBreathAnalyzer.getMarketSentiment()` |
| 资金流与成交质量 | 15 | 当前 stock 的 `zlje`、`zljzb`、`cddje`、`volumeRatio`、`turnoverRate` |

### 7.4 分层规则

建议：

```text
A: >= 80，核心候选
B: 65-79，重点观察
C: 50-64，观察样本
D: < 50，只记录不推荐入池，除非用户强制保存
```

状态建议：

```text
score >= 75 且无重大风险 -> candidate
score >= 55 -> observe
RankTrend A_MAIN 且题材/龙头共振强 -> triggered
拥挤/退潮/资金背离 -> observe 或只提示风险，不自动 triggered
```

### 7.5 文案生成规则

文案不是 LLM 生成，而是结构化模板拼装：

```text
入池理由：
RankTrend 为 B_IGNITION，题材暴露属于机器人主线，资金流保持正向，当前属于修复期观察样本。

交易假设：
若题材继续扩散且个股排名不明显回落，未来 3-5 天存在从观察样本推进为核心候选的可能。

买入前提：
次日排名维持前排，主线题材不退潮，主力净额不转负，分时不出现放量滞涨。

失效条件：
RankTrend 降为 D_EXIT_RISK，题材进入拥挤/背离，或主力净额连续转负。
```

### 7.6 风险规则

候选分析必须显式输出风险，不允许只有乐观理由：

- RankTrend `C_CROWDED` 或 `D_EXIT_RISK`。
- 题材拥挤或背离。
- 龙头地位不明确。
- 市场情绪退潮。
- 主力净额转负。
- 量比异常但资金不配合。
- 样本质量不足或 RankTrend 缺失。

### 7.7 结构化解释字段

Phase 12 后，规则分析不再只依赖自然语言字段。`CandidateAnalysisService` 同时输出：

- `evidence`：按 RankTrend、题材、龙头/地位、情绪、资金流拆分的证据项，标记 `positive`、`neutral`、`negative` 或 `missing`。
- `penalties`：从证据项中抽取的扣分项和缺样本项，用于候选池详情区直接展示。
- `structuredThesis`：把触发条件、买入前提、失效条件拆为结构化数组，每项都有 `dimension`、`status` 和说明。
- `structuredRisks`：对 RankTrend 缺失、题材缺失、情绪退潮、资金转负、低样本量、D_EXIT_RISK 等风险输出 `code`、`level`、`dimension`、`message`。

这些字段仍保存在 `signalsSnapshot.candidateAnalysis` 内，不新增后端表字段；旧文本字段保留，作为人工编辑和兼容展示。

### 7.8 自动候选发现

Phase 13 增加 `CandidateDiscoveryService`，用于从当前行情列表中生成“建议入池”清单。

服务边界：

- 输入当前 `dataLayer.getStocks()` 行情样本，也可在测试中显式传入股票数组。
- 对每只股票复用 `CandidateAnalysisService` 生成规则分析。
- 按评分排序，默认只保留达到观察线的样本，并限制推荐数量。
- 接收当前开放候选列表，标记 `duplicate.isOpen`、候选记录 id 和状态。
- 输出推荐原因、评分、等级、风险、重复候选状态和预期跟踪天数。
- 内置冷却时间，非强制刷新时复用上次结果，避免刷新过程反复打扰用户。

硬约束：

- 自动发现只产出建议，不自动写入 `/api/journal`。
- 用户点击“确认入池”后，才调用 `CandidateJournalService.addCandidateFromStock()`。
- 已存在开放候选的股票只提示“重复候选”，不再次创建记录。

## 8. 右键入口设计

在 `DataTable.vue` 右键菜单新增：

```text
加入候选池
```

建议位置：

```text
加入自选
加入候选池
加入板块 >
---
复制代码
---
查看题材
查看详情
排名趋势
```

交互：

- 点击后调用候选池服务。
- 如果该股票今天已有未复盘候选记录，提示“已在候选池”，并打开该记录。
- 如果未存在，生成分析草稿并保存。
- 保存成功后 toast 显示评分和状态。
- 可选：成功加入候选池时自动加入自选股，默认建议开启，但实现上应作为服务参数或后续设置项，不在第一版做复杂配置。

## 9. 候选池工作台

建议新增面板：

```text
src/components/panels/CandidatePoolPanel.vue
```

不要继续把所有交互堆在 `TradeJournalPanel.vue`。旧面板可以暂时保留为详情/编辑入口，或后续逐步替换。

### 9.1 布局

推荐三栏或两栏工作台：

```text
左：状态/过滤/统计
中：候选列表
右：分析详情与操作
```

### 9.2 顶部统计

- 总候选数。
- 今日新增。
- 观察中。
- 已触发。
- 跟踪中。
- 待复盘。
- 平均评分。
- 候选命中率、失效率、触发率、平均跟踪天数。

统计口径：

- 候选统计只计算 `trade_type=thesis` 的候选研究样本，不纳入历史交易日志的 `entry` / `exit` 记录。
- 命中率等同候选复盘胜率，分子为 `review_outcome=success|partial`，分母为 `status=reviewed` 的已复盘候选。
- 失效率分子为 `review_outcome=failed|not_triggered`，分母同样为已复盘候选。
- 触发率分子为状态进入 `triggered|tracking|reviewed` 的候选，分母为候选总数。
- 平均跟踪天数按候选 `createdAt` 到 `updatedAt` 的自然日估算，最小记 1 天；这是研究样本跟踪时长，不代表真实持仓天数或交易盈亏。
- 质量拆解按题材、RankTrend 分层、规则评分等级和资金状态分组展示候选数量、均分、命中率、失效率和风险数。

### 9.3 候选列表卡片

每条候选显示：

- 股票代码/名称。
- 状态。
- 评分和等级。
- 主题材/角色。
- RankTrend 分层。
- 龙头/核心/跟随状态。
- 主要风险标签。
- 创建时间/更新时间。

### 9.4 分析详情

详情区域显示：

- 规则评分拆解。
- 入池理由。
- 交易假设。
- 买入前提。
- 失效条件。
- 风险提示。
- 证据项与扣分项。
- 结构化条件：触发条件、买入前提、失效条件。
- 结构化风险：缺样本、退潮、资金转负、RankTrend 失效等可比较风险。
- 信号快照：
  - RankTrend。
  - 题材。
  - 龙头。
  - 市场情绪。
  - 资金流。

### 9.5 操作

- 推进状态：观察 -> 候选 -> 触发 -> 跟踪 -> 复盘。
- 标记跳过。
- 编辑假设。
- 重新分析。
- 打开股票详情。
- 打开排名趋势。
- 加入自选。
- 删除候选。

## 10. 存储和 API

继续使用：

```text
GET /api/journal/entries
POST /api/journal/entries
PUT /api/journal/entries/{id}
DELETE /api/journal/entries/{id}
GET /api/journal/stats
```

第一版不需要新增后端字段。当前字段可承载：

| 候选池字段 | journal 字段 |
|------------|--------------|
| 状态 | `status` |
| 入池理由 | `entry_reason` / `entryReason` |
| 交易假设 | `trade_hypothesis` / `tradeHypothesis` |
| 买入前提 | `entry_prerequisites` / `entryPrerequisites` |
| 失效条件 | `invalidation_rules` / `invalidationRules` |
| 人工决策 | `human_decision` / `humanDecision` |
| 跳过原因 | `skip_reason` / `skipReason` |
| 复盘结果 | `review_outcome` / `reviewOutcome` |
| 模型结果 | `model_result` / `modelResult` |
| 执行结果 | `execution_result` / `executionResult` |
| 规则分析快照 | `signals_snapshot` / `signalsSnapshot` |
| 风险标签 | `review_tags` / `reviewTags` |

建议在 `signalsSnapshot` 内新增结构化子对象：

```json
{
  "candidateAnalysis": {
    "version": "candidate-rules-v1",
    "score": 78,
    "grade": "B",
    "suggestedStatus": "candidate",
    "strengths": [],
    "weaknesses": [],
    "riskWarnings": [],
    "evidence": [],
    "penalties": [],
    "structuredThesis": {
      "triggerConditions": [],
      "entryPrerequisites": [],
      "invalidationConditions": []
    },
    "structuredRisks": [],
    "scoreBreakdown": {
      "rankTrend": 24,
      "theme": 14,
      "dragon": 12,
      "sentiment": 10,
      "moneyFlow": 8
    }
  }
}
```

## 11. 前端服务拆分建议

新增：

```text
src/services/candidate/CandidateAnalysisService.ts
src/services/candidate/CandidateDiscoveryService.ts
src/services/candidate/CandidateJournalService.ts
src/services/candidate/types.ts
```

职责：

- `CandidateAnalysisService`：纯规则分析，输入股票和上下文，输出分析结果。
- `CandidateDiscoveryService`：自动扫描当前行情样本，输出人工确认的建议入池清单，不写 journal。
- `CandidateJournalService`：封装 `/api/journal` 的候选 CRUD，处理 snake_case payload。
- `types.ts`：候选分析和候选记录类型。

组件职责：

- `DataTable.vue` 只触发 `CandidateJournalService.addCandidateFromStock(stock)`。
- `CandidatePoolPanel.vue` 只消费候选服务和展示结果。
- `TradeJournalPanel.vue` 暂时保留，后续可缩为高级编辑/历史交易日志。

## 12. App 入口

建议把顶部下拉菜单“交易日记”改为“候选池”，并新增独立按钮可以后续考虑。

第一版可做：

```text
下拉菜单：
  候选池
  交易日记（如仍需保留）
```

如果要突出盘中使用，应后续增加顶部按钮：

```text
候选池（图标建议用靶心/列表/星标组合）
```

## 13. 测试策略

### 13.1 CandidateAnalysisService 单元测试

覆盖：

- RankTrend `A_MAIN` 提高评分并生成核心候选理由。
- RankTrend `B_IGNITION` 生成观察/候选理由。
- `C_CROWDED` 输出拥挤风险。
- `D_EXIT_RISK` 输出退出/失效风险。
- 题材主线和 leader 角色提高评分。
- 情绪退潮降低评分。
- 资金流为负输出风险。
- RankTrend 缺失时输出样本质量风险。

### 13.2 CandidateJournalService 单元测试

覆盖：

- 从股票生成候选 payload。
- 已存在未复盘候选时不重复创建。
- 创建成功后可选加入自选。
- API 失败时返回结构化错误。

### 13.3 DataTable 测试

覆盖：

- 右键菜单包含“加入候选池”。
- 点击后调用候选服务。
- 不直接在组件里拼复杂 journal payload。

### 13.4 CandidatePoolPanel 测试

覆盖：

- 加载候选列表。
- 状态过滤。
- 展示评分、理由和风险。
- 状态更新调用 PUT。
- 建议入池区位于右侧详情容器内。
- 推荐结果必须通过确认按钮才调用候选入池服务。

### 13.5 CandidateDiscoveryService 单元测试

覆盖：

- 从行情样本生成按评分排序的推荐清单。
- 低于最低评分线的股票不会进入建议。
- 已有开放候选时标记重复候选，不创建 journal。
- 推荐清单包含原因、风险、预期跟踪天数和候选等级。
- 冷却时间内复用上次推荐，强制刷新时重新分析。

### 13.6 验证命令

建议第一批至少运行：

```powershell
pnpm exec vitest run src/services/candidate/__tests__/*.test.ts src/components/common/__tests__/DataTable.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
pnpm build
```

如果改动涉及 QuantBoard 后端，再补：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py -q
```

## 14. 分阶段实施建议

### Phase 1: 候选分析服务

- 新增候选类型。
- 新增规则分析服务。
- 写单元测试锁定评分和文案。
- 不改 UI。

验收：

- 给定 mock 股票和上下文，能稳定输出评分、理由、假设、前提、失效条件和风险。

### Phase 2: 候选 journal 服务

- 封装 journal API。
- 实现从股票入池。
- 实现重复候选检测。
- 实现信号快照落库。

验收：

- 服务测试通过。
- 不依赖面板也能创建候选记录。

### Phase 3: 右键入口

- `DataTable.vue` 增加“加入候选池”。
- 成功后 toast 展示评分/等级。
- 已存在时打开候选池或提示。

验收：

- 从行情列表右键可以创建候选。
- 不影响加入自选、加入板块、查看详情等现有功能。

### Phase 4: 候选池工作台

- 新增 `CandidatePoolPanel.vue`。
- 接入候选列表、过滤、详情、状态流转。
- `App.vue` 下拉菜单接入“候选池”。

验收：

- 可以在工作台查看和推进候选状态。
- 可以查看自动分析详情。

### Phase 5: 旧面板收敛

- 决定 `TradeJournalPanel.vue` 是保留为交易日志，还是迁移为候选详情高级编辑。
- 删除或隐藏重复入口。

验收：

- 用户不会同时面对两个功能高度重叠的入口。

## 15. 风险和权衡

### 15.1 规则解释不是大模型

第一版叫“AI 分析”容易产生误解。它本质是规则解释型智能分析，优势是稳定、可解释、可测试。后续可以把结构化结果喂给 LLM 做自然语言增强。

### 15.2 评分不能变成买入指令

候选评分只代表“值得跟踪程度”，不是买入建议。UI 文案必须避免“推荐买入”。

### 15.3 候选样本污染

如果所有自选都自动进入候选池，会污染研究样本。因此第一版只在用户明确点击“加入候选池”时入池。

### 15.4 `TradeJournalPanel.vue` 继续膨胀

不要在旧面板上继续堆功能。候选池工作台应是新入口，旧面板逐步收敛。

## 16. 推荐第一批最小可交付

最小可交付应包含：

- `CandidateAnalysisService`。
- `CandidateJournalService`。
- DataTable 右键“加入候选池”。
- 简版 `CandidatePoolPanel`：
  - 列表。
  - 状态过滤。
  - 分析详情。
  - 状态推进。

暂不做：

- 视觉大改全部完成。
- 盘后批量复盘统计。
- 外部 LLM。
- 后端新增候选生成 API。

这样第一批能解决最核心问题：发现股票时一键入池，系统自动给出结构化分析，候选池不再靠手工录表单驱动。
