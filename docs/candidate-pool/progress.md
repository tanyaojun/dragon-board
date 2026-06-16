# 候选池工作台进度记录

## Session: 2026-05-17

### Phase 1: 需求与现状固化

- **Status:** complete
- **Started:** 2026-05-17 10:10:25 +08:00
- Actions taken:
  - 读取 `planning-with-files` skill。
  - 执行 session catchup 检查，无输出。
  - 确认用户选择：方案 B（自选股 + 候选池分层）。
  - 确认用户选择：方案 A（规则解释型 AI 分析）。
  - 梳理自选股、右键菜单、TradeJournalPanel、journal API、Mongo repository、RankTrend、ThemeTrend、DragonReview、DragonBreath 相关代码。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/findings.md`
  - `docs/candidate-pool/progress.md`
  - `docs/candidate-pool/candidate-pool-workbench-design.md`

### Phase 2: 方案设计

- **Status:** complete
- Actions taken:
  - 设计候选池工作台版方案。
  - 明确自选股与候选池的边界。
  - 明确规则解释型分析引擎的输入、输出和评分维度。
  - 明确右键入口、候选池面板、状态流转、存储/API、测试验收和分阶段实施建议。
- Files created/modified:
  - `docs/candidate-pool/candidate-pool-workbench-design.md`

### Phase 3: 第一批 MVP 实施计划

- **Status:** complete
- Actions taken:
  - 写入第一批实现计划，明确服务层、右键入口、候选池面板和验证命令。
  - 确认本批不接外部 LLM，不写入自选股存储，不扩大刷新机制改动。
- Files created/modified:
  - `docs/candidate-pool/implementation-plan.md`

### Phase 4: 第一批 MVP 实施

- **Status:** complete
- Actions taken:
  - 新增 `CandidateAnalysisService`，生成规则评分、等级、入池理由、交易假设、买入前提、失效条件、风险提示和 `signalsSnapshot.candidateAnalysis`。
  - 新增 `CandidateJournalService`，负责候选列表、右键股票入池、重复未复盘候选检测、状态更新和自选股同步添加。
  - 行情列表右键菜单新增“加入候选池”，组件层只调用候选服务，不直接拼 journal API。
  - 新增 `CandidatePoolPanel`，支持候选列表、状态过滤、规则分析详情和状态推进。
  - App 下拉菜单新增“候选池”，保留原自选股和交易日记入口。
  - 补齐 QuantBoard journal 创建接口 `review_tags` 字段，避免创建候选时丢失分级/题材标签。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateAnalysisService.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateAnalysisService.test.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/common/DataTable.vue`
  - `src/components/common/__tests__/DataTable.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `src/App.vue`
  - `quant-board/backend/api/journal_routes.py`
  - `quant-board/docs/api-cli.md`
  - `quant-board/tests/test_trade_journal.py`

### Phase 5: Review 修复

- **Status:** complete
- Actions taken:
  - `CandidateJournalService.addCandidateFromStock` 增加股票代码校验，避免空代码候选误查全量 journal 或写入无效记录。
  - `CandidatePoolPanel.updateStatus` 增加失败提示和更新中禁用状态，后端不可用或状态更新失败时不再静默失败。
  - 复核 `RefreshManager` 当前实现，确认已不再通过全局 scheduler `stopAll()` 误停共享刷新任务。
- Files created/modified:
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

### Phase 6: 候选池工作台可用化

- **Status:** complete
- Actions taken:
  - `CandidateJournalService` 新增 `getOpenCandidateForStock`，供行情右键菜单识别已入池股票。
  - `CandidateJournalService` 新增 `reanalyzeCandidate`，用最新行情上下文重算候选分析，并对比入池快照生成分数变化、状态标签和原因。
  - 候选池面板新增统计概览：今日新增、观察/候选、触发跟踪、待复盘、平均评分、当前风险。
  - 候选池详情新增“入池快照 / 当前重分析 / 状态变化”对比视图，并展示当前评分拆解、条件变化原因和当前风险。
  - 行情列表右键菜单新增已入池识别：未入池显示“加入候选池”，已入池显示“查看候选详情”。
  - 右键新增候选成功后自动打开候选池并定位新记录；候选池已打开时会重新加载并选中新候选。
  - `App.vue` 增加 `candidate-pool:open` 事件桥接，统一由候选池面板处理定位。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/common/DataTable.vue`
  - `src/components/common/__tests__/DataTable.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `src/App.vue`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 7: 交易假设编辑与复盘闭环

- **Status:** complete
- Actions taken:
  - `CandidateJournalService` 新增 `updateCandidateThesis`，封装入池理由、交易假设、买入前提、失效条件、人工决策和未执行原因的轻量保存。
  - `CandidateJournalService` 新增 `writeBackCurrentAnalysis`，允许用户把当前重分析结果写回 `signalsSnapshot.candidateAnalysis` 与 `reviewTags`。
  - `CandidateJournalService` 新增 `saveCandidateReview`，保存复盘结果、模型结果、执行结果和复盘结论，并将候选标记为已复盘。
  - 候选池详情新增“假设编辑”和“复盘闭环”工作区，替代旧面板式手工字段堆叠。
  - 候选池筛选新增“待复盘”，统计新增触发率、失效率、复盘胜率。
  - 修复外部右键打开指定候选时被旧状态筛选挡住的问题，打开目标候选会切到“全部状态”并重载定位。
  - 修复复盘结果仍为 `pending` 时被误标记为 `reviewed` 的问题，只有明确复盘结果才推进为已复盘。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 8: 视觉与端到端交互验证

- **Status:** complete
- Actions taken:
  - 使用本机已运行的 Dragon Board 前端 `http://127.0.0.1:5173` 和 QuantBoard 后端 `http://127.0.0.1:8000` 进行 Playwright 验证。
  - 验证主页面加载、行情列表右键菜单、右键“加入候选池”、候选池自动打开并选中新候选。
  - 验证候选池详情里的“保存假设”“写回当前分析”“保存复盘”三条写入链路均返回 journal API `200`。
  - 验证 `reviewOutcome=pending` 保存后，候选状态仍保持开放状态，没有再误改为 `reviewed`。
  - 验证桌面宽屏和 900px 窄屏候选池弹层可读、可编辑，候选池自身无横向溢出。
  - 清理 Phase 8 过程中创建的临时 journal 记录，避免污染候选池样本。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 9: 旧入口与历史交易日志收敛

- **Status:** complete
- Actions taken:
  - 将 `docs/candidate-pool/task_plan.md` 补充 Phase 9-Phase 14，明确后续候选池操作、统计、规则增强、自动发现和 E2E 回归阶段。
  - 将 `TradeJournalPanel.vue` 从“候选与交易假设”收敛为“历史交易日志”。
  - 历史交易日志默认新建 `tradeType=entry` 交易记录，出场记录继续使用 `trade_type=exit`。
  - 历史交易日志加载时分别查询 `entry` 和 `exit`，合并排序，并过滤 `tradeType=thesis`，避免候选池记录污染历史交易列表。
  - 删除旧面板中候选研究式的可见输入：抓取信号、入池理由、交易假设、买入前提、失效条件、市场环境、题材地位、个股角色、人工决策、未执行原因、预期持仓天数。
  - App 下拉菜单入口从“交易日记”改为“历史交易日志”，候选相关工作流继续走“候选池”。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`
  - `src/App.vue`
  - `src/components/panels/TradeJournalPanel.vue`
  - `src/components/panels/__tests__/TradeJournalPanel.test.ts`

### Phase 10: 候选池操作补全

- **Status:** complete
- Actions taken:
  - `CandidateJournalService` 增加 `deleteCandidate`，删除前校验 `tradeType=thesis`，避免误删历史交易日志。
  - `CandidateJournalService` 增加 `addCandidateToFavorites`，统一候选池加入自选股入口。
  - 候选池详情区增加快捷操作：加入自选、股票详情、排名趋势、删除候选。
  - App 增加 `rank-trend:open` 事件桥接，候选池可直接打开对应股票的 RankTrend 面板。
  - 候选列表增加评分排序、等级排序、更新时间排序、风险筛选和题材关键词筛选。
  - 候选池列表数量改为展示筛选后数量和总数，快捷操作区补齐按钮布局和删除态样式。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`
  - `src/App.vue`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`

### Phase 11: 候选质量统计与复盘分析

- **Status:** complete
- **Started:** 2026-05-17 14:35:49 +08:00
- Actions taken:
  - 读取 `docs/candidate-pool/task_plan.md` 与进度记录，确认 Phase 11 成功标准。
  - 先补 RED 测试，锁定候选质量统计服务与候选池面板的 Phase 11 合同。
  - 新增 `CandidateQualityStatsService`，基于候选重分析结果计算漏斗、命中率、失效率、触发率、平均跟踪天数、复盘分布和质量拆解。
  - 候选池面板接入质量统计，新增候选漏斗、题材/RankTrend/等级/资金拆解和复盘结果分布。
  - 在方案文档补充候选统计口径，明确不与历史交易日志盈亏统计混用。
  - 清理组件内旧统计派生字段，候选质量指标统一由 `CandidateQualityStatsService` 生成。
  - 根据用户反馈恢复候选池“左侧候选目录 + 右侧详情容器”主布局，Phase 11 统计改为右侧详情内的紧凑候选质量小节。
  - 运行候选池完整定向测试、类型检查和前端构建，均通过。
- Files created/modified:
  - `src/services/candidate/CandidateQualityStatsService.ts`
  - `src/services/candidate/__tests__/CandidateQualityStatsService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/candidate-pool-workbench-design.md`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 12: 规则分析增强

- **Status:** complete
- **Started:** 2026-05-17 18:57:52 +08:00
- Actions taken:
  - 先补 RED 测试，锁定结构化证据、扣分项、条件组、结构化风险和重分析变化归因合同。
  - `CandidateAnalysisService` 增加 `evidence`、`penalties`、`structuredThesis`、`structuredRisks`，按 RankTrend、题材、龙头/地位、情绪、资金流输出可解释证据。
  - 对 RankTrend 缺失、题材缺失、情绪缺失、资金字段 NaN/缺失、低样本量、资金转负、拥挤和 D_EXIT_RISK 输出结构化风险，不再只依赖文本风险提示。
  - `CandidateJournalService` 增强入池快照与当前重分析对比，按评分维度归因改善/走弱，并识别新增风险、风险解除和缺样本。
  - 候选池详情区在原“左目录 + 右详情容器”布局内补充证据项、扣分项、结构化条件和结构化风险展示，没有再改主布局。
  - 更新方案文档，明确 Phase 12 结构化字段仍存放于 `signalsSnapshot.candidateAnalysis`，不新增后端表字段。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateAnalysisService.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateAnalysisService.test.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/candidate-pool-workbench-design.md`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 13: 自动候选发现

- **Status:** complete
- **Started:** 2026-05-17 19:25:00 +08:00
- Actions taken:
  - 先补 RED 测试，锁定自动候选发现服务和候选池面板的人工确认合同。
  - 新增 `CandidateDiscoveryService`，基于当前行情样本复用规则分析引擎生成建议入池清单。
  - 推荐结果按评分排序，默认过滤低分样本，限制推荐数量，并输出原因、风险、等级、重复候选状态和预期跟踪天数。
  - 自动发现服务只产出建议，不写 journal；候选池面板点击“确认入池”后才调用 `CandidateJournalService.addCandidateFromStock`。
  - 增加冷却时间控制，非强制刷新时复用上次推荐，避免面板打开和刷新过程反复打扰。
  - 候选池右侧详情容器增加“建议入池”紧凑区，保留左侧候选目录 + 右侧详情主布局。
  - 按新增视觉合同补齐高对比金融配色 token、数据字体 token 和统计卡顶部状态线。
- Files created/modified:
  - `src/services/candidate/CandidateDiscoveryService.ts`
  - `src/services/candidate/__tests__/CandidateDiscoveryService.test.ts`
  - `src/services/candidate/types.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/candidate-pool-workbench-design.md`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 14: 端到端测试与回归固化

- **Status:** complete
- **Started:** 2026-05-17 20:20:00 +08:00
- Actions taken:
  - 用单元测试先复现候选池读取未限定 `trade_type=thesis` 的问题，确认历史交易可能混入候选池。
  - `CandidateJournalService.listCandidates()` 查询固定带 `trade_type=thesis`，并对后端误返回的非候选记录做防御性过滤。
  - 安装并接入 `@playwright/test`，新增 `test:e2e` 脚本。
  - 将旧 Vite 示例 E2E 替换为候选池真实回归：右键入池、查看详情、编辑假设、写回分析、保存复盘、历史交易日志隔离。
  - E2E 使用路由 mock 覆盖行情、RankTrend、题材、journal、stock names 和快照读口，不依赖本机代理或 QuantBoard 实例。
  - 增加重复候选、服务失败提示、删除候选，以及宽屏/窄屏截图回归。
  - Playwright 配置保留默认浏览器行为，同时支持 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 以便本机复用系统 Chrome。
- Files created/modified:
  - `e2e/vue.spec.ts`
  - `package.json`
  - `package-lock.json`
  - `playwright.config.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 15: 生产化联调与真实使用闭环

- **Status:** in_progress
- **Started:** 2026-05-17 22:08:00 +08:00
- Actions taken:
  - 用户确认 `HotStockEventMonitorPanel.vue` 与对应测试是面板样式美化改动，本阶段明确避开。
  - 读取候选池计划、进度、方案文档和候选分析/发现服务，确认 Phase 15 应先做真实使用稳定性收口。
  - 补充 Phase 15 计划，成功标准从继续堆功能改为真实行情、真实 journal、异常提示和自动推荐质量校准。
  - 先补 RED 测试，复现候选发现冷却期内切换行情样本或推荐参数后仍复用上一批推荐的问题。
  - `CandidateDiscoveryService` 增加缓存 key，按股票代码集合、`minScore` 和 `limit` 隔离冷却缓存；重复候选标记仍允许冷却期即时刷新。
  - 追加空行情回归测试，确保无行情样本时继续返回 `skippedReason=empty`，不被冷却缓存误标为 `cooldown`。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`
  - `src/services/candidate/CandidateDiscoveryService.ts`
  - `src/services/candidate/__tests__/CandidateDiscoveryService.test.ts`

## 2026-05-17 Phase 16 异动雷达与候选池桥接

- **Started:** 2026-05-17 22:32:00 +08:00
- Actions taken:
  - 用户确认 `HotStockEventMonitorPanel.vue` 是“异动雷达”，不是历史交易日志。
  - Phase 16 成功标准定为：异动雷达负责盘中线索发现，候选池负责正式候选与交易假设，历史交易日志只保留真实交易记录。
  - 补充 `docs/candidate-pool/task_plan.md` Phase 16，明确“龙头复盘候选”和“候选池开放候选”需要分开表达。
  - 先补 RED 测试，锁定“异动雷达”命名、入口文案、候选池 journal 桥接和不得使用历史交易日志语义。
  - `HotStockEventMonitorPanel.vue` 标题、关闭提示、分类 aria 统一为“异动雷达”，顶栏入口和刷新任务描述同步改名。
  - 异动卡片保留龙头复盘候选标识为“龙头复盘”，新增正式候选池标识“已入候选池”，后者只来自 `CandidateJournalService.listCandidates({ limit: 200 })` 的开放 thesis 记录。
  - 个股异动卡片新增“加入候选池 / 查看候选”动作，创建成功后通过 `candidate-pool:open` 打开候选池并定位候选；失败时 toast 提示，不影响异动雷达刷新。

## 2026-06-14 Phase 17 交易池 V1 前端投影层

- **Status:** complete
- Actions taken:
  - 读取 `docs/candidate-pool/` 下候选池工作台、双池设计和 Trading Pool V1 实施计划，确认 V1 只做前端投影，不触碰后端/API/库表和真实历史交易日志。
  - 使用 TDD 先补 `TradingPoolAnalysisService` 失败测试，锁定状态词、真实 RankTrend 嵌套路径、买点共振、自动出池、降级、信号过期和恢复规则。
  - 新增 `TradingPoolAnalysisService`，输出交易池 rows、staleCount、exitedCount，并显式读取 direction、jumpConfidence、MACD、acceleration、zeroCross、momentumSyncBroken、lifecycleAction。
  - 在 `CandidatePoolPanel.vue` 增加“候选池 / 交易池”标签页；交易池视图只消费已加载的 `trade_type=thesis` 候选记录生成只读投影。
  - 使用 `dragon-board:trading-pool:v1:previous-rows` 保存 session 级上一轮交易池 rows，支持信号过期保留上一状态和本会话内“已介入”UI 状态。
  - 补充候选池面板源码契约测试，锁定交易池 tab、sessionStorage、只读投影和状态展示文案。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/TradingPoolAnalysisService.ts`
  - `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 17 Review Fixes

- Actions taken:
  - 修正 `rankTrend: undefined` 的数据质量边界，避免误判为 fresh。
  - 为交易池增加手动刷新入口，并在切换到交易池标签时触发一次重算。
  - 将交易池重算限制在交易池激活态，避免候选池标签页空耗重算。
  - 将交易池 sessionStorage 写入从候选池 deep watch 改为交易池激活态和刷新触发。
  - 补充空候选、无效代码、兼容字段 fallback、非激活态和刷新门控的定向测试。
  - 将交易池面板契约测试从内部变量名扫描收敛为 UI 文案、thesis 数据边界和历史交易日志隔离断言。
  - 运行 `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot`，29 项通过。

## 2026-06-14 Phase 18 交易池 V2 journal 持久化层

- **Status:** complete
- Actions taken:
  - 新增 `docs/candidate-pool/trading-pool-persistence-v2-plan.md`，冻结 V2 最小落地范围：复用 MongoDB `trade_journal`，不新增集合，不写 `favorite_data`，不污染历史 `entry/exit`。
  - QuantBoard journal API 和 `TradeJournal` 模型支持顶层 `candidateEntryId` / `candidate_entry_id`，Mongo repository 支持按 `candidateEntryId` 过滤。
  - `CandidateJournalService` 新增 `listTradingPoolEntries()`、`createTradingPoolEntry()`、`updateTradingPoolEntry()`，统一写入 `trade_type=trading_pool` 与 `signalsSnapshot.tradingPool`。
  - `CandidatePoolPanel.vue` 交易池 tab 读取持久化 trading-pool 记录；刷新交易池和标记“已介入”会 upsert 对应 journal 记录，sessionStorage 仅保留为前端临时兜底。
  - 同步 `candidate-pool-trading-pool-design.md` 与 QuantBoard `api-cli.md` 的 V2 数据合同说明。
- Files created/modified:
  - `docs/candidate-pool/trading-pool-persistence-v2-plan.md`
  - `docs/candidate-pool/candidate-pool-trading-pool-design.md`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`
  - `quant-board/backend/api/journal_routes.py`
  - `quant-board/backend/data/models.py`
  - `quant-board/backend/data/mongo_research_repository.py`
  - `quant-board/tests/test_trade_journal.py`
  - `quant-board/tests/test_mongo_research_repository.py`
  - `quant-board/docs/api-cli.md`
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

## Test Results

| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| 文档目录检查 | `docs/candidate-pool/` | 业务专题目录存在 | 已创建 | 通过 |
| 候选池前端单元测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 9 tests passed | 9 tests passed | 通过 |
| 前端类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Journal 后端契约测试 | `.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py` | 4 passed | 4 passed | 通过 |
| Review 修复回归测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 5 tests passed | 5 tests passed | 通过 |
| Phase 6 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增行为测试失败 | 5 failed / 5 passed，失败点为缺少公开查询、重分析、统计和事件桥接 | 通过 |
| Phase 6 候选池定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 12 tests passed | 12 tests passed | 通过 |
| Phase 6 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 6 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 7 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增行为测试失败 | 4 failed / 6 passed，失败点为缺少 `updateCandidateThesis`、`writeBackCurrentAnalysis`、`saveCandidateReview` 和面板入口 | 通过 |
| Phase 7 定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 10 tests passed | 10 tests passed | 通过 |
| Phase 7 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 15 tests passed | 15 tests passed | 通过 |
| Phase 7 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 7 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 7 Review 修复 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增回归测试失败 | 2 failed / 10 passed，失败点为 pending 复盘误提交 `status: reviewed`、外部打开候选未清空筛选 | 通过 |
| Phase 7 Review 修复定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 12 tests passed | 12 tests passed | 通过 |
| Phase 7 Review 修复候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 17 tests passed | 17 tests passed | 通过 |
| Phase 7 Review 修复类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 7 Review 修复前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 8 浏览器冒烟 | Playwright 打开 `http://127.0.0.1:5173` | 首页非空、无框架错误覆盖 | 行情总览和行情行正常渲染，截图已保存至临时目录 | 通过 |
| Phase 8 候选池桌面视觉 | Playwright 1366x768 打开候选池 | 弹层可读、列表和详情可操作 | 候选池覆盖层、统计卡片、详情、假设编辑和复盘区均可见 | 通过 |
| Phase 8 右键端到端 | 右键行情行 `601991` 并点击“加入候选池” | 创建候选、打开面板、选中新记录 | journal `POST` 成功，`candidate-pool:open` 事件携带 `candidateId`，面板选中新候选 | 通过 |
| Phase 8 编辑与复盘 | 保存假设、写回当前分析、保存 pending 复盘 | 三次 `PUT` 成功，pending 不推进 reviewed | journal 记录保持 `status=observe`、`reviewOutcome=pending`，备注持久化 | 通过 |
| Phase 8 窄屏视觉 | Playwright 900x700 | 候选池自身无横向溢出，内容可读可编辑 | `panelScrollWidth=panelClientWidth=892`，当前活动候选数 1 | 通过 |
| Phase 8 临时数据清理 | 删除 Playwright 创建的 journal 记录 | 测试样本不残留 | `DELETE /api/journal/entries/tj_ae476469f99b471f` 返回 deleted | 通过 |
| Phase 9 RED 验证 | `pnpm exec vitest run src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 新增历史日志契约测试失败 | 先后失败于旧标题、默认 `thesis`、候选研究字段残留 | 通过 |
| Phase 9 候选池/交易日志定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 20 tests passed | 5 files / 20 tests passed | 通过 |
| Phase 9 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 9 旧文案扫描 | `rg -n "候选与交易假设|新增候选|编辑候选|暂无候选|市场环境|题材地位|个股角色|人工决策|未执行原因|预期持仓天数|captureSignals|stockOptions|tradeType:\s*'thesis'|trade_type:\s*'thesis'" src\components\panels\TradeJournalPanel.vue src\App.vue` | 无命中 | exit 1，无匹配 | 通过 |
| Phase 10 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增操作契约测试失败 | 失败点为缺少删除候选、加入自选、RankTrend 事件桥接和列表控制 | 通过 |
| Phase 10 候选池/交易日志定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 24 tests passed | 5 files / 24 tests passed | 通过 |
| Phase 10 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 10 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 11 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增统计合同测试失败 | 失败点为缺少 `CandidateQualityStatsService` 和面板候选质量视图 | 通过 |
| Phase 11 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 26 tests passed | 6 files / 26 tests passed | 通过 |
| Phase 11 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 11 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 11 布局回归修复 | `pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts --reporter=dot` | 7 tests passed | 2 files / 7 tests passed | 通过 |
| Phase 12 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增结构化分析合同测试失败 | 5 failed / 18 passed，失败点为缺少结构化证据、风险、条件和归因展示 | 通过 |
| Phase 12 结构化分析定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 23 tests passed | 3 files / 23 tests passed | 通过 |
| Phase 12 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 31 tests passed | 6 files / 31 tests passed | 通过 |
| Phase 12 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 12 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 13 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增自动发现合同测试失败 | 失败点为缺少 `CandidateDiscoveryService` 和候选池建议入池区 | 通过 |
| Phase 13 服务/面板定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 12 tests passed | 2 files / 12 tests passed | 通过 |
| Phase 13 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 35 tests passed | 7 files / 35 tests passed | 通过 |
| Phase 13 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 13 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 14 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts --reporter=dot` | 新增 thesis 隔离测试失败 | 2 failed / 12 passed，失败点为候选查询未带 `trade_type=thesis` 且未过滤历史交易 | 通过 |
| Phase 14 候选服务隔离回归 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts --reporter=dot` | 14 tests passed | 14 tests passed | 通过 |
| Phase 14 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 36 tests passed | 7 files / 36 tests passed | 通过 |
| Phase 14 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 14 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 14 E2E 回归 | `$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='C:\Program Files\Google\Chrome\Application\chrome.exe'; pnpm exec playwright test e2e/vue.spec.ts --project=chromium --reporter=line` | 2 tests passed | 2 tests passed，截图写入 `test-results/**` | 通过 |
| Phase 14 diff 检查 | `git diff --check` | exit 0 | exit 0 | 通过 |
| Phase 15 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts --reporter=dot` | 新增冷却缓存隔离测试失败 | 1 failed / 3 passed，失败点为切换行情集合和参数后仍返回 `skippedReason=cooldown` | 通过 |
| Phase 15 候选发现缓存隔离回归 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts --reporter=dot` | 4 tests passed | 4 tests passed | 通过 |
| Phase 15 空行情 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts --reporter=dot` | 新增空行情语义测试失败 | 1 failed / 4 passed，失败点为空行情第二次发现被标为 `cooldown` | 通过 |
| Phase 15 自动发现边界回归 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateDiscoveryService.test.ts --reporter=dot` | 5 tests passed | 5 tests passed | 通过 |
| Phase 15 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts --reporter=dot` | 40 tests passed | 7 files / 40 tests passed | 通过 |
| Phase 15 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 15 diff 检查 | `git diff --check` | exit 0 | exit 0 | 通过 |
| Phase 16 RED 验证 | `pnpm exec vitest run src/components/panels/__tests__/HotStockEventMonitorPanel.test.ts --reporter=dot` | 新增语义和候选池桥接测试失败 | 2 failed / 3 passed，失败点为仍叫“异动提醒”且缺少 candidate journal 桥接 | 通过 |
| Phase 16 面板语义 RED 验证 | `pnpm exec vitest run src/components/panels/__tests__/HotStockEventMonitorPanel.test.ts --reporter=dot` | 入口仍未统一时失败 | 1 failed / 4 passed，失败点为 `App.vue` 仍显示“异动监控” | 通过 |
| Phase 16 异动雷达定向测试 | `pnpm exec vitest run src/components/panels/__tests__/HotStockEventMonitorPanel.test.ts --reporter=dot` | 5 tests passed | 5 tests passed | 通过 |
| Phase 16 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/TradeJournalPanel.test.ts src/components/panels/__tests__/HotStockEventMonitorPanel.test.ts src/services/refresh/__tests__/RefreshTaskRegistry.test.ts --reporter=dot` | 49 tests passed | 9 files / 49 tests passed | 通过 |
| Phase 16 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 16 浏览器冒烟 | Playwright + 系统 Chrome 打开 `http://127.0.0.1:5173` 并点击“异动雷达” | 面板标题、Tab、空态或候选动作区域可渲染，无框架错误覆盖 | 面板可见，标题“异动雷达”，Tab 完整，截图 `C:\Users\Think\AppData\Local\Temp\dragon-phase16-event-radar.png`；真实启动层仍卡在平台数据加载 15%，属 Phase 15 数据链路风险 | 通过 |
| Phase 17 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot` | 缺少 `TradingPoolAnalysisService` 时失败 | Failed to load url `../TradingPoolAnalysisService` | 通过 |
| Phase 17 服务规则测试 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot` | 9 tests passed | 9 tests passed | 通过 |
| Phase 17 面板 RED 验证 | `pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增交易池契约测试失败 | 1 failed / 14 passed，失败点为缺少“交易池”视图与 session 投影 | 通过 |
| Phase 17 服务/面板聚焦测试 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 24 tests passed | 2 files / 24 tests passed | 通过 |
| Phase 17 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 17 前端构建 | `pnpm build` | exit 0 | exit 0，保留既有 `dataLoader.ts` 动静态混用 warning | 通过 |
| Phase 17 diff 检查 | `git diff --check` | exit 0 | exit 0 | 通过 |
| Phase 17 浏览器验收 | Playwright + 系统 Chrome 打开 `http://127.0.0.1:5173`，进入候选池并切换“交易池” | 渲染交易池视图，展示观察买点、已退出、信号过期三类状态 | 交易池表格展示 3 只样本：长电科技=观察买点，ST洲际=已退出，再升科技=信号过期；截图 `output/playwright/candidate-pool-trading-browser.png` | 通过 |
| Phase 18 后端 journal 契约 | `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py tests/test_mongo_research_repository.py -q` | exit 0 | 27 passed，保留既有 FastAPI on_event warning | 通过 |
| Phase 18 前端 service/panel 测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | exit 0 | 2 files / 39 tests passed | 通过 |
| Phase 18 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 19 强共振召回 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot` | 新增楚江新材型、泰晶科技型、高 Jump 弱共振、双风险测试失败 | 4 failed / 14 passed，失败点为缺少 finalConfidence、buyVotes、source、riskFlags 和状态分层 | 通过 |
| Phase 19 交易池强共振定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/panels/__tests__/candidatePoolTradingPool.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/common/__tests__/DataTable.test.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts --reporter=dot` | exit 0 | 5 files / 59 tests passed | 通过 |
| Phase 19 RankTrend 回归 | `pnpm test:ranktrend` | exit 0 | 21 files / 219 tests passed | 通过 |
| Phase 19 RankTrend 类型检查 | `pnpm typecheck:ranktrend` | exit 0 | exit 0 | 通过 |
| Phase 19 应用类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 19 浏览器验收 | Playwright CLI 打开 `http://127.0.0.1:5173`，检查主表与候选池交易池 tab | 主表表头显示 `Jump置信`，交易池 tab 显示统计、筛选和空态 | 表头已显示 `Jump置信`；交易池 tab 渲染 `总数/观察/准备/介入/退出/过期`、决策筛选与空态；当前本地 journal 无 thesis，未出现交易池行；保留既有行情/情绪 abort warning | 通过 |
| Phase 19 Code Review 修正 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/panels/__tests__/candidatePoolTradingPool.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/common/__tests__/DataTable.test.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts --reporter=dot`; `pnpm test:ranktrend`; `pnpm typecheck:ranktrend`; `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`; `git diff --check` | exit 0 | 5 files / 64 tests passed；RankTrend 21 files / 221 tests passed；类型检查和 diff 检查 exit 0 | 通过 |
| Phase 19 000988 Jump 兜底修正 | `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot`; `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts src/components/panels/__tests__/candidatePoolTradingPool.test.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts --reporter=dot` | RED: 候选池矩阵 Jump 已过但 RankTrend 路径缺失时误判 `已退出/exit` | GREEN: 服务单测 22 tests passed；定向回归 5 files / 65 tests passed | 通过 |

## 2026-06-16 Phase 20 交易池实时投影接入

- **Status:** complete
- **Started:** 2026-06-16
- **Actions taken:**
  - 根因诊断：6月15日强情绪日零票入池，数据管道只走 thesis 日记，不走 DataLayer 八平台热榜 200+ 只实时投影。
  - 编写设计方案与实施计划，经 subagent 交叉评审修复全部 Critical 问题。
  - TDD：先写 4 个实时投影管道测试（RED），再实现 types + TradingPoolInput 扩展与合并逻辑（GREEN）。
  - `TradingPoolSource` 新增 `'live_projection'`；`TradingPoolInput` 新增 `liveStocks` 可选字段；thesis 候选优先去重。
  - `CandidatePoolPanel.vue` 导入 `dataLayer`，`tradingPoolEvaluation` 传入 `dataLayer.getStocks()` 中带 `rankTrend` 的热榜股票。
  - 新增 `isResonanceObserve()` 9条件判定函数，含 7 个边界测试。
  - `tradingPoolSourceLabel` 新增 `'live_projection' → '热榜实时'` 映射。
  - DataTable tooltip 四层结构（综合判断/Jump/共振/交易池）和交易池面板字段此前已实现，本次确认无需改动。
- **Files created/modified:**
  - `docs/candidate-pool/2026-06-16-trading-pool-live-data-integration-design.md`
  - `docs/candidate-pool/2026-06-16-trading-pool-live-data-integration-plan.md`
  - `src/services/candidate/types.ts`
  - `src/services/candidate/TradingPoolAnalysisService.ts`
  - `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - `src/services/candidate/CandidatePoolStatusProjector.ts`
  - `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
- **Verification:** `pnpm test` 104 files / 783 tests passed；`pnpm test:ranktrend` 21 files / 221 tests passed；`pnpm typecheck:ranktrend` exit 0；`vue-tsc --noEmit` exit 0。
- **Deferred:** 配置统一化（spec 7.0 / design Phase 3），后续单独出计划。

## 2026-06-16 Phase 21 交易池统一合同与 B+D 评分分轨

- **Status:** complete
- **Started:** 2026-06-16
- **Actions taken:**
  - 统一交易池四轨道 source 合同：`thesis`、`live_projection`、`persisted`、`manual`；`jump_blocked_resonance` 仅保留兼容输入，不再输出。
  - 将交易池状态机收敛为评分驱动：lifecycle veto > limitUp > stale > 已介入保持/退出 > score-based status。
  - `limitUp` 由 `jumpSignalService` 产出，经 `rankTrend.jump.limitUp` 传播到 `TradingPoolSignalSnapshot`，交易池层不自行按涨幅推断。
  - `analyzeTradingPoolCandidate` 只读 `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.scoring/weights`；旧单体阈值保留但不参与决策。
  - DataTable-facing 语义从 BuyVotes “共振评级”改为“共振评分”。
  - Code review 后复用 `decideTradingPoolStatus` 内部一次性计算的 `scoringBreakdown`，未知 source 兜底为 `unknown`。
- **Files created/modified:**
  - `src/types/rankTrendLiveStrategy.ts`
  - `src/config/rankTrendLiveStrategyConfig.ts`
  - `src/services/rankTrend/jumpSignalService.ts`
  - `src/services/candidate/types.ts`
  - `src/services/candidate/TradingPoolAnalysisService.ts`
  - `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - `src/services/rankTrend/__tests__/jumpSignalService.test.ts`
- **Verification:** `pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/services/rankTrend/__tests__/jumpSignalService.test.ts --reporter=dot` → 2 files / 41 tests passed；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` → exit 0。

## Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 无 | 无 | 1 | 无 |
| 2026-05-17 | `CandidateStockLike` 带索引签名导致 `MergedStock` 类型不可赋值 | 运行 `vue-tsc` 定位到 `CandidateJournalService.ts` | 改为交叉类型 `& Record<string, any>` 后类型检查通过 |
| 2026-05-17 | journal 创建接口不接收 `review_tags`，候选标签会丢失 | 阅读 `quant-board/backend/api/journal_routes.py` 和模型契约 | 为 `CreateJournalEntryRequest` 补 `review_tags` 并写后端测试 |
| 2026-05-17 | 空股票代码可能误查全量 journal 或写入无效候选 | 先补失败测试 | 入池前校验 `stockCode`，无效则抛出 `候选股代码无效` |
| 2026-05-17 | 状态推进失败时面板无反馈 | 先补失败测试 | `updateStatus` 加 try/catch、错误提示和 `updatingStatus` 禁用 |
| 2026-05-17 | 候选池已打开时，右键新增候选可能无法定位到新记录 | 定向测试后人工复核事件流 | 入池事件带 `candidateId`，面板找不到目标时重新加载列表并再次定位 |
| 2026-05-17 | Phase 7 面板与服务缺少轻量编辑、写回分析和复盘保存合同 | 先补 RED 测试 | 新增候选服务更新 API，并在候选池详情页接入轻量表单 |
| 2026-05-17 | 外部打开指定候选可能被候选池旧状态筛选挡住 | 先补 RED 测试 | `openCandidate` 在指定目标时切到“全部状态”并重载定位 |
| 2026-05-17 | 保存 pending 复盘会误把候选标为 reviewed | 先补 RED 测试 | `saveCandidateReview` 仅在复盘结果非 pending 时提交 `status: reviewed` |
| 2026-05-17 | Phase 8 诊断脚本直出页面文本被 PowerShell GBK 编码卡住 | 重新运行诊断 | 设置 `PYTHONIOENCODING=utf-8` 并输出结构化字段 |
| 2026-05-17 | Phase 8 初次复测时 `601991` 存在临时已复盘记录，导致右键再次新增 | 检查 journal 后端数据 | 删除临时记录后重跑真实新增链路，确认新建、打开、编辑、复盘和清理均通过 |
| 2026-05-17 | Phase 9 初次收敛后旧交易日志面板仍保留候选研究字段 | 先补 RED 契约测试 | 删除旧面板可见候选研究输入，保留后端兼容字段默认值和历史记录展示能力 |
| 2026-05-17 | Phase 10 初次构建新增 `RankTrendPanel` 动静态混用 warning | 查看 Vite 输出 | App 改为静态导入 `RankTrendPanel`，消除新增 warning，仅保留既有 ThemeFacade warning |
| 2026-05-17 | Phase 11 复盘结果分布初版按数量排序，待复盘会压过已复盘结果 | 定向测试定位 | 复盘结果分布改为固定语义顺序：成功、部分兑现、失败、未触发、待复盘 |
| 2026-05-17 | Phase 11 质量统计大面板破坏原“左目录右容器”工作台结构 | 用户截图反馈后复核 `CandidatePoolPanel.vue` 模板层级 | 新增布局回归测试，把统计改为右侧详情内紧凑小节，恢复主结构 |
| 2026-05-17 | Phase 12 归因文案中中文维度出现多余空格，例如“题材 走弱” | 定向测试定位 | 增加维度变化格式化函数，仅英文 RankTrend 保留空格，中文维度直接拼接 |
| 2026-05-17 | Phase 13 面板定向测试出现新增视觉 token 合同失败 | 系统化调试定位到测试文件新增 `--candidate-font-data` 等断言，而非 Phase 13 逻辑失败 | 补齐高对比金融配色、数据字体 token 和 `stat-card::before` 状态线 |
| 2026-05-17 | Phase 14 `CandidateJournalService.listCandidates()` 未带 `trade_type=thesis`，历史交易可能混入候选池 | 先补 RED 测试复现 | 查询固定附加 `trade_type=thesis`，并在前端服务层过滤非 thesis 记录 |
| 2026-05-17 | Node Playwright runner 未安装，`pnpm exec playwright` 先解析到 Python CLI 且无 `test` 命令 | 检查 `@playwright/test` 依赖和命令解析 | 安装 `@playwright/test` 并新增 `test:e2e` 脚本 |
| 2026-05-17 | `pnpm exec playwright install chromium` 超时，Node Playwright 自带 Chromium 未就绪 | 检查本机 `ms-playwright` 与系统 Chrome | 配置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`，本机使用系统 Chrome 完成 E2E 验证 |
| 2026-05-17 | Phase 14 E2E 初版菜单定位被图标文本和同名按钮干扰 | 读取 Playwright error-context | 定位收敛到 `.context-menu`、`.dropdown-menu`、`.candidate-toolbar` 和具体卡片容器 |
| 2026-05-17 | Phase 14 复盘保存测试被前一次“写回当前分析”的异步响应重置表单 | 查看失败现场快照 | 等待写回按钮完成 enable 后再操作复盘区，并限定复盘卡片内控件 |
| 2026-05-17 | Phase 15 候选发现冷却缓存只按时间判断，切换行情样本或推荐参数时可能返回上一批推荐 | 先补 RED 测试复现 | 缓存 key 纳入股票代码集合、`minScore` 和 `limit`；仅 key 一致时复用分析结果 |
| 2026-05-17 | Phase 15 空行情样本第二次发现会被冷却逻辑覆盖为 `cooldown` | 追加 RED 测试复现 | 空样本判断前置到冷却复用之前，保证面板能区分无数据和冷却复用 |
| 2026-05-17 | Node Playwright 托管 Chromium 缺失，无法直接启动浏览器冒烟 | 读取 launch 错误 | 复用系统 Chrome `C:\Program Files\Google\Chrome\Application\chrome.exe` 完成 Phase 16 冒烟 |
| 2026-05-17 | 浏览器冒烟时真实页面停在启动层“加载平台数据 15%”，顶栏按钮被 `v-show` 隐藏 | 检查 DOM、样式和控制台 | 记录为 Phase 15 真实数据链路风险；Phase 16 仅临时显示主 App 验证面板渲染和交互入口 |
| 2026-06-14 | Phase 17 交易池手动“已介入”状态会被实时重算覆盖 | 自审 `tradingPoolRows` 和 `previousTradingPoolRows` 数据流 | 面板层保留 session 中上一状态为“已介入”的 UI 投影，不写后端 |
| 2026-06-15 | 000988 华工科技候选池严格通过，但 tooltip 显示交易池“自动出池” | RED 用例复现 `jump_confidence.actual=95` 未被交易池读取，缺失 Jump 被 `?? 0` 当成低 Jump | 交易池读取候选池规则矩阵 Jump 当前值作为兜底；强制出池只在 Jump 确有数值且低于 75 时触发 |

## 5-Question Reboot Check

| Question | Answer |
|----------|--------|
| Where am I? | Phase 21 交易池统一合同已完成，四轨道来源、评分状态机、涨停分轨、阈值真源和 tooltip 评分语义已收敛 |
| Where am I going? | 交易池持久化 V2/面板展示细节或真实浏览器验收 |
| What's the goal? | 将手工候选/交易假设升级为候选池工作台，并让交易池用统一评分合同跟踪买点 |
| What have I learned? | 见 `findings.md` |
| What have I done? | Phase 1-21 全部完成：右键入池、规则分析、候选池面板、状态推进、journal 标签入库、统计概览、当前重分析、已入池识别、候选详情定位、假设编辑、分析写回、复盘保存、Phase 8 端到端交互、Phase 9 历史交易日志收敛、Phase 10 候选删除/快捷操作/筛选排序、Phase 11 候选漏斗/质量拆解/命中率/失效率/平均跟踪、Phase 12 结构化证据/扣分项/条件组/风险/变化归因、Phase 13 自动建议入池/重复候选识别/人工确认/冷却控制、Phase 14 Playwright E2E/历史交易隔离、Phase 15 候选发现冷却缓存隔离、Phase 16 异动雷达命名收敛/候选池桥接、Phase 17 交易池 V1 前端投影、Phase 18 交易池 V2 journal 持久化、Phase 19 交易池强共振自动入池/最终置信度/买入票数/风险标签/来源识别、Phase 20 交易池实时投影接入/DataLayer 管道打通/强共振观察分类、Phase 21 交易池统一合同/B+D 混合评分/涨停分轨 |
