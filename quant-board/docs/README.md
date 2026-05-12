# QuantBoard 文档中心

QuantBoard 是 `dragon-board` 的量化回测与参数研究子项目。首期目标不是另起一套策略体系，而是把 `dragon-board` 已经稳定运行的 `rankTrend` TypeScript 分析链迁移到 Python 后端，形成可导入数据、可复现回测、可比较优化、可通过前端查看结果的个人量化研究平台。

## 首期结论

- `src/services/rankTrend/*` 与 `src/services/RankTrendAnalyzer.ts` 是首期唯一 golden 标准。
- QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
- Dragon Board 根项目只提供实时看板、快照数据和 TypeScript golden 导出，不承载回测平台职责。
- Python 端必须先复刻 `rankTrend` 输出合同，再开发策略、回测和优化。
- 默认 `snapshot_type` 为 `half_hour`。`quarter_hour` 只作为可选细颗粒度样本，不是默认口径。
- 存储主链采用 SQLite 主库 + Supabase 备份库；详细实施、同步和恢复规则以 [database-migration-plan.md](database-migration-plan.md) 为准。
- 所有回测、优化、API、CLI、前端展示都要保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`，保证结果可追溯。
- 资金流来源必须可追溯：正式资金流回测只接受 `broker_l2` 或 `official_l2`，`estimated_l1` 默认只能作为观察指标。

## 文档索引

| 文档 | 用途 |
| --- | --- |
| [user-manual.md](user-manual.md) | 面向日常使用的操作手册：启动、导入、回测、报告、优化与常见问题 |
| [architecture.md](architecture.md) | 总体架构、模块边界、数据库表与数据流 |
| [database-migration-plan.md](database-migration-plan.md) | SQLite 主库 + Supabase 备份库并行实施计划、同步合同和恢复规则 |
| [mongodb-migration-plan.md](mongodb-migration-plan.md) | 拟执行的 MongoDB 全量主库迁移方案，覆盖快照库、研究库、题材库和股票基础库 |
| [data-ingestion.md](data-ingestion.md) | SQLite 快照库派生研究数据集、历史 JSON 迁移和质量门禁 |
| [ranktrend-golden.md](ranktrend-golden.md) | TypeScript golden 标准、输出合同、验收基线 |
| [ranktrend-python-port.md](ranktrend-python-port.md) | Python 移植步骤、数值对齐、测试策略 |
| [backtest-policy.md](backtest-policy.md) | 当前回测统一口径：5 天/40 bars、MACD 辅助定位、T+1、收益字段 |
| [backtest-engine.md](backtest-engine.md) | 事件驱动回测引擎、撮合、持仓、绩效指标 |
| [optimization.md](optimization.md) | 参数搜索、目标函数、实验记录与防过拟合 |
| [search-methods.md](search-methods.md) | 四个正式参数搜索方法的计算口径、结果字段和使用方法 |
| [api-cli.md](api-cli.md) | FastAPI 与 CLI 接口草案 |
| [frontend.md](frontend.md) | 前端页面、交互、结果展示与联调约定 |
| [development-roadmap.md](development-roadmap.md) | 分阶段落地路线和验收清单 |
| [AI_COLLABORATION.md](AI_COLLABORATION.md) | AI 协作硬约束和交接规范 |

## 推荐实现顺序

1. 数据导入：从 SQLite 正式快照事实表生成 QuantBoard 研究数据集；历史 JSON 只作为迁移辅助。
2. Golden 用例：从 TypeScript `rankTrend` 产出固定输入与期望输出，写入 `golden_ranktrend_cases`。
3. Python 移植：逐模块复刻 technical、cycle、risk、decision、candidate tier。
4. 回测引擎：只消费 Python rankTrend 输出，所有回测、优化和交易模拟都在 QuantBoard Python 后端执行。
5. API 与 CLI：先覆盖导入、golden 校验、单次回测、回测列表、报告读取。
6. 优化：基于回测引擎做网格搜索和随机/局部搜索，记录每次实验。
7. 前端：用静态报告和 API 结果展示数据集、回测任务、权益曲线、交易列表、参数对比。

## 当前项目骨架

```text
quant-board/
  backend/
    main.py
    settings.py
    data/
      database.py
      models.py
  config/
  data/
    snapshots/
    staging/
    warehouse/
    reports/
  docs/
  tests/
  requirements.txt
```

已有后端表模型包括：

- `datasets`
- `snapshot_records`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `golden_ranktrend_cases`
- `backtest_runs`
- `optimization_runs`
- `sync_outbox`

这些表可以作为首期实现基础。新增代码时优先补齐导入、计算、回测服务层，不要为了前端演示绕过数据表合同。

## 统一默认值

首期默认配置：

```yaml
snapshot_type: half_hour
strategy_name: rank_trend_candidate
strategy_version: 0.1.0
initial_capital: 100000
random_seed: 20260430
target_holding_days: 5
max_holding_bars: 40
macd: 21/34/13
```

详细口径以 [backtest-policy.md](backtest-policy.md) 为准。核心约束：MACD 只作为辅助观察信号，不是独立买卖触发器；交易持仓最多 5 天、40 个半小时 bars。

`quarter_hour` 的使用条件：

- 用户显式选择；
- 数据覆盖满足质量门禁；
- 回测报告中明确写入 `snapshot_type=quarter_hour`；
- 不能把 quarter_hour 优化出的参数直接覆盖 half_hour 默认参数。

## 开发约束

- 只把 TypeScript `rankTrend` 当 golden；回测、优化和交易模拟口径以 QuantBoard Python 后端为准。
- 数据质量门禁失败时返回结构化原因，不静默降级为可交易结果。
- 任何优化结果都只能作为候选参数，必须经过固定样本外验证。
- 对 Python 初学者友好：新增模块要有清晰命名、少量必要注释、可运行测试。
- 文档变更优先更新本目录，避免把过期说明散落到 backend/frontend。
- 修改存储、同步、快照入库、数据库表字段、API/CLI 合同或恢复策略时，必须同批更新对应文档，尤其是 [database-migration-plan.md](database-migration-plan.md)。
