# 开发路线图

## 总原则

首期按“先合同、再数据、再算法、再回测、再展示、最后优化”的顺序推进。不要为了快速看到前端图表跳过 golden 校验。

## Phase 0：文档与骨架

目标：

- 明确首期完整方案；
- 补齐 docs；
- 确认硬约束。
- 冻结 SQLite 主库 + Supabase 备份库并行实施主计划。

验收：

- README、架构、数据、golden、移植、回测、优化、API/CLI、前端、路线图、AI 协作规范齐全。
- 文档明确 QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
- 文档明确 `rankTrend` TypeScript 是 golden。
- 文档明确默认 `snapshot_type=half_hour`。
- [database-migration-plan.md](database-migration-plan.md) 成为存储迁移、同步接口、恢复流程和冲突规则的唯一主计划。

## Phase 1：数据导入

目标：

- 实现 IndexedDB JSON 导入；
- 写入标准数据表；
- 能查询数据集和快照。
- 导入链路以 SQLite 主库为准，并为 Supabase 备份镜像保留完整业务对象。

任务：

- 实现导入 service。
- 实现 schema fingerprint。
- 实现快照、股票行、板块行投影。
- 实现导入报告。
- 按 [database-migration-plan.md](database-migration-plan.md) 的写入合同保留可恢复 payload 和业务键。
- 补数据导入测试。

验收：

- 给定 fixture JSON 能导入成功。
- `datasets` 汇总统计准确。
- `snapshot_stock_rows` 可按 `dataset_id + snapshot_type + date range` 查询。
- 默认查询 `half_hour`。
- 备份镜像失败不会伪装成导入成功的完整同步，必须有结构化同步诊断。

## Phase 1.5：SQLite 主库与 Supabase 备份库并行

目标：

- 落地 SQLite 主库 + Supabase 备份库的正常写入、补偿同步、读取回退和恢复流程。

主计划：

- 具体规则、接口合同、冲突策略和验收清单统一维护在 [database-migration-plan.md](database-migration-plan.md)。
- 本路线图只记录阶段位置，不重复维护细节，避免多处口径漂移。

任务：

- SQLite 写入成功后镜像 Supabase。
- 建立 `sync_outbox` 或等价补偿机制。
- 实现 `GET /api/health` 的主备状态报告。
- 实现 `POST /api/sync/push-backup` 和 `POST /api/sync/pull-backup`。
- 实现 `POST /api/snapshots/ingest`，让 Dragon Board 正式快照进入后端主链。
- 实现 `POST /api/migrations/snapshots/import-json`，支持历史 JSON 可重复迁移。
- 覆盖 SQLite 不可用、Supabase 不可用、同键重复同步和同键冲突。

验收：

- 正常导入、Golden、回测和优化仍以 SQLite 为主链。
- Supabase 配置存在时，关键业务对象可被备份和恢复。
- SQLite 查询失败或本地缺失目标记录时，读路径能按主计划回退。
- 所有失败返回结构化原因，不用空数据伪装成功。
- 修改任何存储、同步、快照或 API/CLI 合同的代码时，同批更新对应文档。

当前进展：

- `sync_outbox` 已缩减为快照备份链路，只覆盖 `dataset_bundle`、`snapshot_ingest`；回测、优化和 Golden 保存在 research SQLite。
- `push-backup` 已先消费到期 outbox，再做 SQLite 全量补推。
- Dragon Board 已对 IndexedDB 已存在但后端 ingest 失败的快照执行后端重放。
- 历史 JSON 迁移 API 已可 dry run、幂等导入并进入 outbox 链路。
- Supabase smoke 联调入口已覆盖写读删；自动同步可配置启动并只处理到期 outbox。
- `POST /api/snapshots/ingest` 已支持 SQLite 完全不可用时写入 Supabase 并返回 `backup_only`，其他写入口的 failover 覆盖继续按 [database-migration-plan.md](database-migration-plan.md) M3 跟踪。

## Phase 2：质量门禁

目标：

- 导入和回测前都能发现不可用数据。

任务：

- 导入门禁。
- 回测门禁。
- 样本质量摘要。
- 结构化错误模型。

验收：

- 样本不足返回 `QUALITY_GATE_FAILED`。
- 恢复快照默认不进入正式回测。
- 时间乱序能被发现或排序修正并记录。

## Phase 3：Golden case

目标：

- 建立 TypeScript 到 Python 的验收基准。

任务：

- 定义 golden case JSON 格式。
- 支持导入 `golden_ranktrend_cases`。
- 编写 Python golden 比较器。
- 准备 technical、cycle、risk、decision、strategy 典型 case。

验收：

- CLI/API 可运行 golden 校验。
- 失败时给出字段路径和差异。
- 没有 case 来自 Dragon Board 根项目浏览器内回测输出。

## Phase 4：Python rankTrend 移植

目标：

- Python 输出对齐 TypeScript `RankTrendAnalysisResult`。

任务：

- 移植 defaults、utils。
- 移植 technical。
- 移植 cycle。
- 移植 risk。
- 移植 decision。
- 移植 market regime。
- 移植 candidate tier。
- 组装 analyzer。

验收：

- 所有 golden case 通过。
- 默认 `half_hour`。
- 样本不足、fallback、MACD 最小样本都有测试。

## Phase 5：回测引擎

目标：

- 基于 Python rankTrend 跑可复现回测。

任务：

- 事件循环。
- 策略接口。
- 组合与持仓。
- 撮合和交易成本。
- 权益曲线逐快照盯市。
- 指标计算。
- `backtest_runs` 持久化。

验收：

- 固定 seed 重复运行结果一致。
- 空交易无 `NaN`。
- 止损、止盈、最大持有 bars 可触发。
- 报告能通过 run id 读取。

## Phase 6：API 与 CLI

目标：

- 对外暴露可用工作流。

任务：

- 数据集 API。
- golden API。
- 回测 API。
- CLI 命令。
- 统一错误响应。

验收：

- `GET /api/health` 正常。
- CLI 能导入、校验、回测。
- API 默认 `snapshot_type=half_hour`。
- 错误结构一致。
- API 同步端点和健康检查字段与 [database-migration-plan.md](database-migration-plan.md) 保持一致。

## Phase 7：前端

目标：

- 提供可用的研究工作台。

任务：

- 数据集页面。
- golden 校验页面。
- 回测表单与报告页。
- 优化页雏形。
- 报告历史。

验收：

- 可选择数据集并运行回测。
- 权益曲线、指标、交易列表可展示。
- 质量门禁失败显示原因。
- `quarter_hour` 只能显式选择。

## Phase 8：参数优化

目标：

- 在回测稳定基础上进行参数研究。

任务：

- grid search。
- random search。
- TPE search。
- objective 评分。
- train/validation 拆分。
- `optimization_runs` 持久化。

验收：

- 固定 seed 优化结果可复现。
- 每个 trial 有回测 run id。
- validation 结果可查看。
- 过拟合风险可标记。

## Phase 9：稳定化

目标：

- 提升可靠性和长期可维护性。

任务：

- 增加 fixture 数据集。
- 补 CI。
- 增加报告导出。
- 增加性能 profiling。
- 完善文档。

验收：

- 核心测试一键通过。
- 新 AI 协作者能按 docs 继续实现。
- 历史回测结果不会被新版本覆盖。

## Phase 10：长测自动化与质量诊断

目标：建立可复现、可追溯的 RankTrend 长测基线链路。

- [x] 新增 `run-longtest-baselines` CLI，固定复跑 H1/H2/Q1 三条基线
- [x] 资金流质量字段透传，修复 `formalMoneyFlowCount=0` 误报
- [x] 非正价格诊断：分类为跨市场零行情、全零异常帧、局部 A 股零价
- [x] 显式研究过滤：`excludeNonPositivePriceRows`、`excludeCrossMarketZeroPriceRows`、`excludeAllZeroPriceFrames`
- [x] Report-only 价格质量诊断字段
- **Status:** complete

## Phase 11：V2 四层决策框架

目标：用分层决策取代线性流水线，每层独立判断。

- [x] Layer 1 信号有效性：分层比例、方向精度、二项检验、层级区分度
- [x] Layer 2 执行质量：H1 vs H2 偏差、相对阈值、黄灯警告
- [x] Layer 3 实盘对齐：trade_journal 7 个执行字段、`/api/backtests/alignment`
- [x] Layer 4 参数优化：两阶段设计、双层止损、采用规则
- [x] 交叉评审 + P0 修正
- [x] Phase A-C 实施：数据模型、Layer 1-2 计算、Layer 3 API，43 项测试
- **Status:** complete

## Phase 12：数据质量修复

目标：补齐缺失的 half_hour/quarter_hour bar。

- [x] 缺口分析：half_hour 42 条、quarter_hour 213 条
- [x] 线性插值补齐：前后双 bar 价格/成交量插值，合成 bar 标记 `captureMode: "synthesized"`
- [x] `bar_repair.py` 修复工具
- **Status:** complete

## Phase 13：待启动

目标：满 60 个交易日数据后启动 Layer 4 优化。

- [ ] 交易管理层参数搜索（maxPositions/takeProfit/stopLoss）
- [ ] 策略层参数敏感度报告
- [ ] 双触发止损机制
- [ ] Walk-forward 滚动窗口验证
- [ ] 市场状态分层标注（Phase E）
- [ ] 基准比较（Phase E）

## 当前下一步

Phase 0-12 已全部完成。后续等待数据积累：

1. 继续每周 checkpoint 复跑，观察 Layer 1-3 指标趋势
2. 满 50 个 half_hour 交易日后启动 Phase E（P1 统计/基准）
3. 满 60 个交易日后启动 Phase 13（Layer 4 参数优化）
4. 候选池 trade_journal 积累 ≥10 笔执行记录后，Layer 3 对齐报告可产出有意义的结论
