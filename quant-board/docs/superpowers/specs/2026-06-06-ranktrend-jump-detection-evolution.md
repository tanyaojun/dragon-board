# RankTrend 内生阈值跳跃检测——策略演进全记录

日期：2026-06-06 | 版本：v1.0 | 状态：研究回测初步通过，待样本外验证

## 1. 起点：方向性缺陷（胜率 37%）

旧版四层框架（compose_decision → compose_strategy → entry_signal → execution）产出 37% 方向精度，
持续低于 50% 随机基准。根因不是参数问题，而是公式缺陷：

**排名百分位上升 ≠ 价格方向。** 热度可以转化为买入，也可以转化为卖出。

尝试过但证实无效的修复：
- MACD 金叉门禁 + finalSignal 过滤：交易从 119 降到 20 笔，回撤收窄，但本质是幸存者偏差
- 531K 参数搜索空间 / 50 TPE trials：零 walk-forward 正收益段
- 热榜情绪替换 market_regime()：只改变入场权限，不改变方向判断公式

## 2. 认知跃迁：计算门槛本身就是错的

实盘中存在大量高确定性交易机会，这些票在连板前共同特征：

- 排名大幅上升
- 多周期动量同时 BUY
- MACD 金叉
- 置信度 > 80%

与 K 线形态、量价关系、市场情绪、题材周期均无直接关系。

当前策略的问题不是门槛高低，而是**计算门槛这个方向本身是错误的**。
compose_decision（加权评分）→ compose_strategy（分层）→ entry_signal（确认）这条链路
把原始信号层层衰减，最终漏掉了最好的交易。

**正确方向：当四个原始信号同时触发时直接入场，不需要中间层计算。**

## 3. 核心创新：内生阈值排名跳跃检测

学术来源：Zhao, Hong & Linton (2024) "Jump vs Burst" 论文。

### 原理

传统固定窗口采样对噪声敏感——来回震荡会被误判为信号。
内生阈值方法持续追踪累计排名百分位变化，当 |累计变化| > delta 时触发事件。

**关键洞察：波动爆发（来回震荡）的累计变化互相抵消，达不到阈值；只有不可逆的趋势性移动才会触发。**

### 算法

```
1. 取 N 个半小快照帧的排名百分位序列 [p0, p1, p2, ...]
2. 设定参考点 ref = p0，阈值 delta（代码默认 10%，本轮回测经 delta 扫描优化为 15%）
3. 遍历每个帧：
   cum_change = p_i - ref
   if abs(cum_change) > delta:
       触发事件：direction = surge/collapse
       重置参考点 ref = 最近3帧均值（防止极端值误触反向事件）
4. sustained 判断：至少两次同向事件才视为"持续"
5. 置信度 = min(累计 overshoot, 样本置信度)
```

## 4. 回测结果演进

全部在同一数据集上回测，34 个交易日。

回测参数：`dataset_id=dragonboard_live`, `snapshot_type=half_hour`, `strategy_version=ranktrend_simple_backtest_v1`, `executionMode=current_frame`（当前帧成交，不等 next_bar）。无 `config_hash`/`random_seed`（未接入优化 runner，为手动 notebook 式回测）。

| 阶段 | 改动 | 收益 | 胜率 | 笔数 | Sharpe |
|------|------|------|------|------|--------|
| 起点 | 固定窗口多周期动量 (delta=10, 旧四层框架) | +3.2% | 35% | 17 | 0.05 |
| P1 | 内生阈值跳跃检测替换固定窗口 (delta=10) | +18.5% | 32% | 31 | 0.09 |
| P2 | 持续出场 + 临时位置过滤（已废弃） | +32.2% | 41% | 29 | 0.16 |
| P3 | 股价同向确认 + -5%硬止损 | +78.0% | 61% | 28 | 0.35 |
| P4 | delta=15 最优 + 参考点3帧均值修复 | +78.3% | 63% | 24 | 0.39 |
| P5 | 涨停板过滤（主板10%/双创20%/北交30%） | **+55.1%** | **78.9%** | **19** | **0.654** |

关键解读：
- P1→P2：临时位置过滤曾压缩尾部噪声，但会把 RankTrend 趋势判断退化为静态名次筛选，已从正式方案中移除
- P2→P3：股价同向确认过滤"排名涨但股价不涨"的假信号，胜率+20pp；止损保护尾部风险
- P3→P5：delta 扫描找到最优 15%（非默认 10%），涨停板过滤排除买不到的票，交易压缩到每月 19 笔

## 5. 最终策略规则

### 入场条件（六条件 AND）

1. **内生阈值跳跃**：jump.event == "jump" AND direction == "buy" AND sustained == true
2. **多周期动量和加速度共振**：technical.signals.direction == "buy" AND technical.signals.acceleration == "buy"
3. **股价同向确认**：change > 0（排除了排名涨但股价不涨的假信号）
4. **涨停板过滤**：change < limit_pct - 0.3（距涨停 0.3% 以内视为封板，排除）
5. **MACD 金叉**：technical.macd.cross == "golden"
6. **跳跃置信度 > 85**：jump.confidence >= 85

### 出场条件（四条件 OR + 硬止损）

1. **排名持续崩塌**：jump.event == "jump" AND direction == "sell" AND sustained == true
2. **退出热榜池**：股票不在当前帧的股票列表中
3. **MACD 死叉**：technical.macd.cross == "death"
4. **排名大幅下降**（fallback）：rawChange < -80
5. **硬止损**：浮动亏损 < -5%（无论信号如何，立即平仓）

### 仓位管理

- 每日最多开 1 仓（T+1 市场规则）
- 同时最多持有 3 只
- 当前帧价格成交（看到信号就买，不等 next_bar）

## 6. 代码位置

| 文件 | 改动 |
|------|------|
| `quant-board/backend/analysis/ranktrend.py` | 新增 `detect_rank_jumps()` + `RankTrendConfig.jumpDeltaPct` 字段 |
| `quant-board/backend/analysis/ranktrend_simple_backtest.py` | 新建，完整独立回测引擎（~300 行） |

## 7. 遗留风险

1. **样本量小**：34 个交易日，19 笔交易，统计显著性不足
2. **未做 walk-forward**：在同一时间段内优化 delta 并评估，存在过拟合风险
3. **涨停板买入可行性**：距涨停 0.3% 的阈值是经验值，实际排队成交率未知
4. **滑点和冲击成本**：仅扣了 0.11% 手续费，未模拟实盘滑点
5. **前端已部分同步**（2026-06-06）：`jumpDetector.ts` 已 1:1 移植 Python 算法（12/12 测试通过），`jumpSignalService.ts` 已实现入场/出场条件判断，`RankTrendSignalService` 已集成跳跃检测，DataTable 已新增"信号"列。实盘渲染验证仍有待完成。

## 8. 2026-06-06 成交延迟审计记录

对 `dragonboard_live / half_hour / delta=15` 复跑后确认：

- `current_frame` 口径可复现 19 笔、约 +56.05% 简单收益和 -7.68% 最大回撤，但当前代码下胜率为 73.68%，不是 78.9%。
- `totalReturn` 是 19 笔 `netReturn` 直接相加，不是真实仓位权益曲线收益。
- 同一批 19 笔交易中，仅把入场价改为下一帧价格，收益从 +56.05% 降到 +14.03%；仅把出场价改为下一帧价格，收益为 +43.16%；入场和出场都用下一帧价格时收益为 +1.52%。
- 收益对成交延迟极敏感，主要原因是信号后一帧入场价快速抬升，典型如江波龙下一帧入场价高约 10.91 个百分点。
- `next_bar` 不等价于实盘真相；半小时 bar 下，下一帧可能已经涨停或错过可成交窗口。后续应使用“信号帧之后的可成交模型”：当前帧信号、盘口 ask/bid 优先、涨停/跌停可成交检查、滑点、容量约束、T+1、最大持仓 bars 和真实权益曲线。

## 9. 2026-06-06 TPE 研究入口与复跑记录

已新增轻量研究入口，不写回默认参数、不做自动下单，只服务实盘验证和复盘：

- CLI：`python -m backend.cli research-ranktrend-jump --dataset-id <dataset> --snapshot-type half_hour --trials <N>`
- API：`POST /api/research/ranktrend-jump`
- 策略名：`ranktrend_jump`
- 目标函数：`ranktrend_jump`，以收益为主，同时惩罚最大回撤、成交样本过少和盘口缺失回退依赖。
- 搜索空间：`jumpDeltaPct` 支持连续 TPE 范围，默认 `8.0 ~ 22.0`，`delta=15` 只作为候选区间内的研究值，不自动固化。
- 固定追溯字段：`dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed=20260430`。
- 执行口径：当前 bar 信号成交、A 股 T+1 卖出限制、`maxHoldingBars=40`、真实仓位权益曲线、涨跌停检查、盘口对手价、成交量/盘口参与率约束。

盘口缺失回退分三档：

| 模式 | 含义 |
|------|------|
| `strict_fill` | 缺买一/卖一直接不成交，最保守 |
| `blocked_fill` | 同样阻断缺盘口，用于审计“无盘口则不可交易”口径 |
| `fallback_penalized` | 允许快照价回退，但增加额外滑点并在 summary 中报告回退占比 |

快速复跑样本：`dataset_id=ds_9ee63c5ea0f34eb3`，`snapshot_type=half_hour`，2026-05-06 至 2026-05-29，180 帧原始样本，运行时剔除 4 个空热榜帧，`trials=4`，`fillFallbackMode=fallback_penalized`。

结果：

- `runId=opt_f222b9445a844820`
- `configHash=87c54c25d39cbe887f17659a3663bffd2480088a814cabe8c8ce73bc65e8dd79`
- 最优 `jumpDeltaPct=13.6223`
- validation `totalReturn=-1.09%`
- validation `realizedReturn=-0.83%`
- `winRate=46.15%`
- `tradeCount=13`
- `maxDrawdown=-2.39%`
- 盘口快照价回退率 `4.21%`，回退次数 4
- walk-forward 分段 4 个，正收益分段占比 `25%`

解读：

- 这次快速样本没有支持“delta 已可固化”的结论；summary 风险为 `medium`，主要风险来自 walk-forward 正收益分段偏低。
- 盘口缺失回退不是这次结果的主要风险（4.21%），但仍需要在实盘观察里记录每笔候选是否有买一/卖一、是否涨停封单。
- 全量 `dragonboard_live` 直接跑 `trials=6 + walk-forward` 超过 5 分钟未完成，后续复跑应先限制日期窗口或使用派生研究数据集，再逐步扩大样本。

MongoDB 恢复后按同一命令再次复跑：

- `runId=opt_509cac20437a4553`
- `configHash=87c54c25d39cbe887f17659a3663bffd2480088a814cabe8c8ce73bc65e8dd79`
- 最优 `jumpDeltaPct=13.6223`
- validation `totalReturn=-1.09%`，`realizedReturn=-0.83%`
- `winRate=46.15%`，`tradeCount=13`，`maxDrawdown=-2.39%`
- 盘口快照价回退率 `4.21%`，回退次数 4
- walk-forward 分段 4 个，正收益分段占比 `25%`

复跑结论：结果与 `opt_f222b9445a844820` 完全一致，说明本组负收益不是 Mongo 异常或随机种子漂移造成，也不是持仓缺 RankTrend signal 时退出检查修复的主因；主要仍来自该小样本 validation 段和严格成交/权益曲线口径。

## 10. 2026-06-07 早期大肉结构研究补充

新增专题记录：`quant-board/docs/superpowers/specs/2026-06-07-ranktrend-early-big-move-structure.md`。

本轮 half_hour 样本确认：`jump buy 高置信 + 动量加速度抬升 + short/mid/long 同步转正 + 盘口可买` 是有效的早期大肉候选结构。候选数 1524，后续 40 bars 正收益概率 84.8%，后续 40 bars 最大涨幅 >= 10% 的比例为 30.6%，平均最大涨幅 8.08%，中位最大涨幅 4.49%。

关键口径调整：

- `finalSignal=buy` 不能作为早期入口前置；当前样本里 `final=hold` 的 40 bars 大肉率为 31.4%，高于 `final=buy` 的 26.0%。
- `stage` 比 `MACD/zeroCross` 更适合做优先级排序；`expansion` 大肉率 37.9%，`ignition` 32.8%，`cooling` 21.5%。
- `candidateTier` 有参考价值但不能硬过滤；`A_MAIN` 大肉率 42.4%，`B_IGNITION` 32.9%，`N_NEUTRAL` 26.8%。
- 当前涨幅 `6%-8.5%` 的样本大肉率 39.9%，说明点火经常已经有明显异动，不能简单用低位过滤。

建议后续规则改为两层：第一层召回早期大肉候选，第二层按 `stage`、`candidateTier`、当前涨幅位置、`direction` 和 `zeroCross/MACD` 排序。第二层只排序，不把这些解释字段变成硬门禁。
