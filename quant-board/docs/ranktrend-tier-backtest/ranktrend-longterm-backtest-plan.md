# 四维信号长期回测计划与性能优化方案

> 状态：待复审（未提交）
> 日期：2026-08-15
> 归档位置：本文档与四份四维信号方案文档统一存入 `quant-board/docs/ranktrend-tier-backtest/`

## 0. 背景与目标

RankTrend 四维信号（共振 / 趋势 / 量价 / 周期，合并为 `synergy` 总档）的档位阈值参数化与交易门已落地（见 `ranktrend-signal-tier-backtest-plan.md`）。目标是让四维信号作为买入/卖出的重要决策依据，并通过参数搜索引擎**持续**优化参数，最终达到：

```
winRate ≥ 0.80 且 tradeCount ≥ 60 且 profitFactor ≥ 1.3
且 validation 段 winRate ≥ 0.70 且 maxDrawdown ≤ 10%
且 walkForward 段胜率 ≥ 0.7（连续两个样本外窗口稳定）
```

基线实况（`bt_78f14b1c814e4d90`，`rank_trend_candidate` / `next_bar`，2026-04-15~08-14）：

- 胜率 **51.96%**、102 笔、总收益 +2.69%、最大回撤 -12.57%
- 对照组：`a_main_only` 56.0%（最优）、`hot_top10` 39.1%
- 信号方向精度 **37.6%**（低于随机 50%）、样本 ok 占比仅 46%

结论：**先修地基（性能 + 数据质量 + 信号区分度），再谈调参**。否则参数搜索只在噪声上过拟合。

## 1. 现状评估

### 1.1 数据层面（MongoDB）

| 项 | 实况 |
|---|---|
| 数据存量 | `dragonboard_live` 2026-03-27 ~ 08-14（约 5 个月）；`snapshot_stock_rows` 1.65GB / 57.3 万行，`snapshot_frames` 12.1MB / 2618 帧 |
| 单行结构 | 83 字段 / 3012 字节（`themes`、`platforms` 等为大字段） |
| 索引 | 股票行 9 个 + 帧 3 个，覆盖 `datasetId+snapshotId+rank`、`code+timestamp` 等查询路径 |

**问题**：`load_frames` 用 `projection="full"` 拉全部 83 字段，但引擎实际只需约 15 字段（`code/change/volumeRatio/zlje/zljzb/price/volume/turnover/rank/avgRankNum/timestamp/tradingDate` 等）→ 传输量浪费约 5 倍。

### 1.2 计算层面（回测引擎）

| 瓶颈 | 实况 |
|---|---|
| 信号重复计算（核心） | `TrialExecutor.evaluate_phase` 的 `signal_cache` 键 = `freeze(strategy_config)`；信号层参数（macd/tier 阈值）一变键就变 → 缓存全 miss → 每 trial 全量 `replay`（逐帧逐股票跑 `_build_signal` 全链纯 Python） |
| 单线程 | `jobs.py` 为 `ThreadPoolExecutor(max_workers=1)`；`replay` 是 CPU 密集，GIL 下多线程无加速 |
| 无中间缓存 | 帧、信号、中间量不跨运行复用，无 Redis |
| 无游标分批 | `_stock_rows_by_snapshot` 一次拉全窗口股票行 |

### 1.3 结论

当前架构**能跑单次回测，但无法支撑长期参数搜索**：24 trials ≈ 48 次全量 replay（1–4 小时），叠加 walk-forward 多段与周度滚动，几周即算不动且反复压库。

## 2. 性能优化方案（三层组合，分层落地）

### 2.1 方案 A — 数据访问层瘦身（最小，最先）

- `load_frames` 增加**字段白名单 projection**（只拉引擎需要的 ~15 字段），替代 `projection="full"`。
- 股票行查询改**游标分批**（`limit + batch`），避免一次全拉 57 万行到内存。
- 日期过滤补全到回测服务（优化侧已做，见 `optimization_service._build_request`）。
- Mongo 连接/服务器选择超时已调大（`connect 10000ms` / `serverSelection 15000ms`）。

### 2.2 方案 B — 信号/中间量缓存（核心收益，Redis）

- **参数分组**：搜索空间参数拆成「信号层参数」（macd/tier 阈值，决定 `replay` 输出）与「交易层参数」（stopLoss/takeProfit/maxPositions，只影响撮合）。
- 交易层参数变化时**复用已算信号**（`signal_cache` 键去掉交易层参数）。
- Redis 缓存帧 + 信号（以 `config_hash` 为键），跨优化运行复用，避免每次重算。
- 中间量（动量 / 技术 / 生命周期）按参数独立性分层缓存，能复用则复用。

### 2.3 方案 C — 多进程并行（配合 B）

- `ProcessPoolExecutor` 并行跑 trial（每个 trial 独立 replay + 撮合，无共享状态）。
- 进程数 = 可用 CPU 核数（如 4–8）。
- trial 结果聚合回主进程写库。

### 2.4 组合收益预估

A 减约 80% 传输 + B 让交易层 trial 秒级完成 + C 并行 → 24 trials 从 1–4 小时降到 **10–20 分钟**量级，且不再压垮 MongoDB。

## 3. 长期回测计划（四阶段，顺序推进，各有验收）

### 阶段 1：性能改造（让搜索跑得动）

落地 2.1–2.3 三层。

**验收**：同一优化任务（24 trials + walk-forward）耗时 ≤ 20 分钟，且 MongoDB 不再因反复全量拉取被压垮。

### 阶段 2：数据质量治理

- 排查并修复 sampleDiagnostics 的 degraded 根因：非正价格、MACD 预热不足、空热榜、`moneyFlowSource` 缺失（历史 28592 行）。
- **验收**：优化/回测窗口内 `researchGrade` 达 `research_ready`（或 degraded 占比 < 25%）。

### 阶段 3：四维信号区分度诊断

- 分层诊断共振/趋势/量价/周期各维的 `directionAccuracy`、tier 单调性、`tierDiscrimination`。
- 排查方向定义、阈值、权重，以及「量价涨停可交易性」等已改口径是否引入偏差。
- **验收**：各维 `directionAccuracy ≥ 0.55`、tierDiscrimination 呈正单调；否则先修信号算法，**暂停阶段 4**。

### 阶段 4：参数搜索 + 样本外验证 + 滚动迭代

- 4.1 交易层参数粗搜（random，win_rate + 盈亏比约束）。
- 4.2 信号层参数精搜（tpe/bayesian，围绕粗搜 best 缩窄空间）。
- 4.3 walk-forward 滚动复核 + 固定样本外窗口裁决。
- 4.4 周度滚动：新样本入库 → 重跑 → 监控参数漂移。

**验收**：满足第 0 节完整验收标准，且连续两个样本外窗口稳定。

## 4. 验收标准汇总

| 约束 | 达标线 | 防什么 |
|---|---|---|
| winRate | ≥ 0.80 | 主目标 |
| tradeCount | ≥ 60 | 小样本刷胜率 |
| profitFactor | ≥ 1.3 | 紧止损刷胜率 |
| validation winRate | ≥ 0.70 | 过拟合 |
| maxDrawdown | ≤ 10% | 高胜率偶发大回撤 |
| walkForward 段胜率 | ≥ 0.7 | 分段时间稳定性 |

## 5. 关键约束与风险

1. 优化结果只产候选参数，**永不自动写回默认值**（沿用现有硬约束）。
2. 每个 trial 保留 `dataset_id/snapshot_type/strategy_version/config_hash/random_seed` 全溯源。
3. 阶段 3 若诊断出信号算法需改，先修信号，不修地基就调参是浪费算力。
4. 纯 win_rate 目标会倾向「少而精 / 紧止损」刷胜率，必须配合 profitFactor / tradeCount 约束。
5. 阶段 1 的方案 B/C 引入 Redis 与多进程，需评估部署影响（Redis 缓存已有专题文档：仓库根目录 `docs/ranktrend-redis-cache/`，含 `design.md`/`implementation-plan.md` 等）。
