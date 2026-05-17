# 候选池工作台整改优化任务计划

## Goal

把现有“候选与交易假设”从手工表单升级为候选池工作台：自选股保留轻量关注，候选池承载交易假设、规则解释型 AI 分析、状态跟踪和复盘闭环。

## Current Phase

Phase 14 complete

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

- [x] 启动前端工作台，检查候选池弹层在桌面宽屏和较窄视口下的可读性
- [x] 验证右键入池、查看候选、编辑假设、写回分析、保存复盘的端到端交互
- [x] 根据实际视觉问题复核布局密度、按钮层级和滚动区域
- **Status:** complete

### Phase 9: 旧入口与历史交易日志收敛

- [x] 将 `TradeJournalPanel.vue` 明确收敛为“历史交易日志”，不再承载候选股入池、候选假设编辑和规则分析入口
- [x] App 下拉入口改为“历史交易日志”，候选相关工作流统一进入 `CandidatePoolPanel.vue`
- [x] 历史交易日志默认只新建真实交易记录，默认 `trade_type=entry`，出场仍使用 `trade_type=exit`
- [x] 历史交易日志列表过滤掉候选池 `trade_type=thesis` 记录，避免候选样本污染交易复盘
- [x] 保留历史交易日志的买卖方向、价格、数量、出场、盈亏、标签、截图和复盘能力
- **Status:** complete

### Phase 10: 候选池操作补全

- [x] 候选池详情补齐删除候选能力，带确认反馈，不误删历史交易日志
- [x] 候选池详情补齐加入自选股、打开股票详情、打开 RankTrend/排名趋势上下文的快捷操作
- [x] 候选列表支持按评分、等级、题材、风险、更新时间、待复盘状态排序和筛选
- [x] 对重复候选、删除失败、服务不可用提供清晰错误提示
- **Status:** complete

### Phase 11: 候选质量统计与复盘分析

- [x] 增加候选漏斗统计：观察、候选、触发、跟踪、已复盘、成功、失败、未触发
- [x] 增加按题材、RankTrend 分层、规则评分等级、资金状态的候选质量拆解
- [x] 增加候选命中率、失效率、平均跟踪天数和复盘结果的工作台指标
- [x] 将统计口径写入文档，避免与历史交易日志盈亏统计混淆
- **Status:** complete

### Phase 12: 规则分析增强

- [x] 强化规则解释：把 RankTrend、题材、龙头/地位、情绪、资金流拆成证据项和扣分项
- [x] 增加入池快照与当前重分析的变化归因：哪些条件改善、走弱、失效或缺样本
- [x] 明确触发条件、买入前提、失效条件的结构化字段，减少纯文本维护成本
- [x] 对空数据、NaN、低样本量和缺字段给出结构化风险提示
- **Status:** complete

### Phase 13: 自动候选发现

- [x] 基于当前行情列表和规则分析引擎生成“建议入池”候选清单
- [x] 推荐结果必须人工确认后入池，不自动写入 journal
- [x] 推荐清单展示推荐原因、评分、风险、重复候选状态和预期跟踪天数
- [x] 控制推荐数量和频率，避免刷新过程频繁打扰用户
- **Status:** complete

### Phase 14: 端到端测试与回归固化

- [x] 固化候选池右键入池、查看详情、编辑假设、写回分析、保存复盘的 Playwright 脚本
- [x] 增加历史交易日志与候选池分离的端到端回归：候选记录不出现在历史交易列表
- [x] 补充窄屏、宽屏、服务失败、重复候选、删除候选等关键场景截图验证
- [x] 更新进度文档和验收清单，形成后续重构基线
- **Status:** complete

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
| Phase 8 Playwright 诊断输出被 GBK 编码卡住 | 1 | 改用 `PYTHONIOENCODING=utf-8` 并减少页面文本直出后继续验证 |
| Phase 8 临时验证数据导致 `601991` 已复盘记录不再算开放候选 | 1 | 清理临时 journal 记录后，用真实右键新增链路重新验证 |
| Phase 14 Node Playwright 未安装浏览器 | 1 | 安装 Chromium 超时后，配置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 允许本机使用系统 Chrome 验证 |
| Phase 14 候选池列表可能混入历史交易日志 | 1 | `CandidateJournalService.listCandidates()` 查询固定带 `trade_type=thesis`，并防御性过滤非 thesis 记录 |

## Notes

- 本目录是业务专题文档目录，避免在根目录新增过程文件。
- Phase 8 验证截图保存在本机临时目录 `C:\Users\Think\AppData\Local\Temp\dragon-candidate-phase8\`，不作为仓库产物提交。
- 窄屏 900px 下候选池浮层自身无横向溢出；页面级 `documentScrollWidth` 大于视口来自底层行情宽表的既有横向滚动。
