# 候选池工作台整改优化任务计划

## Goal

把现有“候选与交易假设”从手工表单升级为候选池工作台：自选股保留轻量关注，候选池承载交易假设、规则解释型 AI 分析、状态跟踪和复盘闭环。

## Current Phase

Phase 8

## Phases

### Phase 1: 需求与现状固化

- [x] 明确自选股与候选池采用分层方案 B
- [x] 明确第一版 AI 能力采用规则解释型方案 A
- [x] 梳理现有自选股、右键菜单、TradeJournalPanel、journal API、RankTrend/ThemeTrend/龙头/情绪能力
- [x] Document findings in findings.md
- **Status:** complete

### Phase 2: 方案设计

- [x] 定义候选池工作台产品形态
- [x] 定义候选分析引擎边界
- [x] 定义右键入口、面板、存储、测试验收
- [x] 写入详细方案文档
- **Status:** complete

### Phase 3: 方案评审

- [x] 用户审阅 `candidate-pool-workbench-design.md`
- [x] 根据反馈收敛范围和优先级
- [x] 决定是否进入实施计划
- **Status:** complete

### Phase 4: 实施计划

- [x] 使用实施计划技能拆分 TDD 任务
- [x] 明确第一批提交边界
- [x] 明确验证命令和手工验收路径
- **Status:** complete

### Phase 5: 第一批 MVP 实施

- [x] 新增 `CandidateAnalysisService`，生成确定性规则评分、解释、风险和信号快照
- [x] 新增 `CandidateJournalService`，封装 journal API、重复候选检测、右键入池、状态更新
- [x] 行情列表右键菜单增加“加入候选池”
- [x] 新增 `CandidatePoolPanel`，提供列表、过滤、详情和状态推进
- [x] App 下拉菜单接入候选池面板，同时保留原自选股与交易日记入口
- [x] 补齐 journal 创建接口的 `review_tags` 入库契约
- **Status:** complete

### Phase 6: 候选池工作台可用化

- [x] 候选池面板增加统计概览、今日新增、状态分布、平均评分和当前风险概览
- [x] 候选详情区区分“入池快照”和“当前重分析”，展示分数变化、建议状态和条件变化原因
- [x] 候选服务提供当前重分析能力，复用实时行情和既有 RankTrend/题材/龙头/情绪上下文
- [x] 行情列表右键菜单识别已入池股票，支持直接查看候选详情
- [x] 更新进度文档并运行候选池定向测试、类型检查和构建
- **Status:** complete

### Phase 7: 交易假设编辑与复盘闭环

- [x] 在候选池详情中提供轻量编辑，不回退到旧表单堆字段
- [x] 支持重新分析并可选择写回候选记录
- [x] 增加待复盘筛选、复盘结果、执行结果和模型结果的工作台入口
- [x] 汇总候选触发率、失效率、复盘胜率等基础统计
- **Status:** complete

### Phase 8: 视觉与交互验证

- [ ] 启动前端工作台，人工检查候选池弹层在桌面宽屏和较窄视口下的可读性
- [ ] 验证右键入池、查看候选、编辑假设、写回分析、保存复盘的端到端交互
- [ ] 根据实际视觉问题收敛布局密度、按钮层级和滚动区域
- **Status:** pending

## Key Questions

1. 候选池是否替代自选股？
   - 已答复：不替代。采用“自选股 + 候选池分层”。
2. 第一版是否接外部大模型？
   - 已答复：不接。先做规则解释型 AI 分析。
3. 第一版是否重做 QuantBoard 后端候选生成？
   - 建议：不重做。先复用现有 `/api/journal` 作为正式存储，候选分析在 Dragon Board 前端服务层完成。
4. 当前刷新机制未提交改动是否纳入本任务？
   - 不纳入。它们属于独立工作区改动，方案只记录并避开。

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| 自选股和候选池分层 | 收藏关注与交易研究样本语义不同，混合会污染复盘样本 |
| 第一版做规则解释型 AI 分析 | 可测试、确定性强、直接复用现有 RankTrend/ThemeTrend/龙头/情绪/资金流能力 |
| 不推翻 `/api/journal` | 后端候选字段、状态过滤和 Mongo repository 已基本可用，重写存储收益低 |
| 新增候选池工作台而不是继续堆 TradeJournalPanel | 当前面板以手工表单为中心，无法承载自动分析、状态看板和复盘视图 |
| 右键行情列表加入候选池 | 符合实际使用路径：发现股票时立即入池并冻结信号快照 |
| 创建候选时同步保留 review_tags | 候选分级、RankTrend 档位和题材标签后续会用于过滤和复盘统计，创建时不能丢失 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| 无 | 1 | 无 |

## Notes

- 本目录是业务专题文档目录，避免在根目录新增过程文件。
- 当前工作区存在刷新机制相关未提交改动：`src/App.vue`、`src/components/panels/SettingsPanel.vue`、`src/services/RefreshManager.ts`、`docs/refresh-mechanism/`、`src/services/__tests__/RefreshManager.test.ts`、`src/services/refresh/`。候选池方案不修改这些文件。
