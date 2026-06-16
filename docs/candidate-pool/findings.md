# 候选池工作台调研发现

## Requirements

- 用户确认自选股功能已可用。
- 用户希望把“候选与交易假设”从低效手工表单升级，融入自选股能力，但最终采用自选股与候选池分层。
- 用户纠正术语：不是“周旋股”，统一为“候选股/候选池”。
- 用户选择方案 2：候选池工作台版。
- 用户选择第一版 AI 能力方案 A：规则解释型，不接外部大模型。
- 用户要求使用 `planning-with-files` 保存详细方案文档。

## Research Findings

- `src/components/panels/TradeJournalPanel.vue` 已接 `/api/journal/entries`、`/api/journal/stats`，并已支持候选状态、交易假设、买入前提、失效条件、模型结果、执行结果等字段。
- `TradeJournalPanel.vue` 的主要问题是 UI 以手工表单为中心，字段多、视觉割裂、缺少自动分析和工作台视图。
- `quant-board/backend/api/journal_routes.py` 已包含候选闭环字段、`status` filter 和 Mongo repository 检查。
- `quant-board/backend/data/models.py` 中 `TradeJournal` dataclass 已支持候选闭环字段，并做 camelCase 文档映射。
- `quant-board/backend/data/mongo_research_repository.py` 已有 `save_journal_entry`、`list_journal_entries`、`count_journal_entries`、`update_journal_entry`、`get_journal_stats`。
- `src/stores/favorite.ts` 是自选股与本地板块的唯一运行时 store，持久化 key 为 `favorite_data`，适合继续保留轻量收藏职责。
- `src/components/common/DataTable.vue` 已有右键菜单，当前支持加入自选、加入板块、复制代码、查看题材、查看详情、排名趋势，是加入候选池入口的自然位置。
- `src/services/rankTrend/compat.ts` 提供 `getRankTrendAnalysis()`，可从当前股票读取 RankTrend 分析。
- `src/services/theme/ThemeFacade.ts` 提供题材因子、个股题材暴露、轮动摘要、热题材等运行时能力。
- `src/services/dragon/DragonReviewService.ts` 提供最新龙头复盘、真龙、高标、关注池等信息。
- `src/services/DragonBreathAnalyzer.ts` 提供市场情绪。
- 现有 `DataLayer` 保存当前行情和题材投影，候选分析应作为只读消费者，不把业务规则塞回 `DataLayer`。

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| 新增 `CandidateAnalysisService` | 把规则解释型候选分析从 UI 和 store 中剥离，便于测试 |
| 候选池正式存储继续走 QuantBoard journal API | 与既有候选/假设字段合同一致，避免新增本地双轨 |
| 自选股 store 不承载候选状态 | Pinia 自选只做本地轻量关注，候选生命周期属于 journal |
| 右键菜单调用候选服务而不是直接写 API payload | 保持 DataTable 只负责交互入口，业务分析集中到服务层 |
| 第一版不自动批量扫描全市场入池 | 控制范围，先解决“发现后快速入池 + 自动分析” |

## Phase 20 Findings (2026-06-16)

- DataTable `confidence` 列 tooltip 此前已实现四层结构（综合判断/Jump跃迁/共振评级/交易池动作），`getTradingPoolActionPreview` 和 `getConfidenceTitle` 已覆盖规格 9 的全部要求，本次无需改动。
- 交易池面板字段（来源/状态/综合/Jump/票数/MACD/风险/原因/操作）和筛选控件（决策/状态下拉）此前已在 Phase 17-19 中实现，本次无需改动。
- `tradingPoolSourceLabel` 此前对未识别来源默认返回 `'实时投影'`，本次新增明确的 `'live_projection' → '热榜实时'` 映射。
- 实时投影行没有 `candidateEntryDecision`，`getEntryDecision` 对 `live_projection` 来源返回 null，`isJumpBlockedOnly` 和 `hasNonJumpHardBlock` 自然返回 false，不会误阻断。
- `analyzeTradingPoolCandidate` 的 `resolvedSignals` 会在 `decision === 'stale'` 时强制覆盖 `dataQuality` 为 `'stale'`，因此无信号的实时投影行最终 dataQuality 为 `'stale'` 而非 `'missing'`，这是已有逻辑链的预期行为。
- 配置统一化（spec 7.0 / design Phase 3）涉及 `rankTrendLiveStrategyConfig` 预设中新增 `tradingPool` 阈值节，需要与现有 V5/Fusion 策略配置文件对齐，本次延后单独出计划。

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 术语误写为“周旋股” | 已统一为“候选股/候选池” |
| 当前工作区已有刷新机制未提交内容 | 方案文档明确不纳入本任务，不触碰相关文件 |

## Resources

- `src/components/panels/TradeJournalPanel.vue`
- `src/components/common/DataTable.vue`
- `src/stores/favorite.ts`
- `quant-board/backend/api/journal_routes.py`
- `quant-board/backend/data/models.py`
- `quant-board/backend/data/mongo_research_repository.py`
- `src/services/rankTrend/compat.ts`
- `src/services/theme/ThemeFacade.ts`
- `src/services/dragon/DragonReviewService.ts`
- `src/services/DragonBreathAnalyzer.ts`
- `docs/superpowers/plans/2026-05-14-short-term-candidate-thesis-loop-plan.md`

## Visual/Browser Findings

- 用户截图显示现有“候选与交易假设”面板是大面积白底表单，左侧列表空，右侧字段堆叠，依赖手工输入股票代码、名称、状态、理由、假设、买入前提、失效条件等。
- 用户截图反映核心痛点不是字段缺失，而是入口、自动化、分析表达和工作流体验不足。
