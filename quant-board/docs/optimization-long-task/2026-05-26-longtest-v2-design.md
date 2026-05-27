# RankTrend 长测方案 V2 设计文档

## 目的

将当前线性流水线式长测方案（checkpoint → 优化 → 等条件 → 采用）重构为四层分层决策框架，每层有独立的衡量指标、进入条件和输出结论。核心原则：**不纯研究，每一层都要能和实盘对齐**。

## 背景

### 当前方案的五个痛点

1. **缺少止损机制**：只有"满足条件→采用"路径，没有"判定策略无效→转向"
2. **边界模糊**：回测 checkpoint、优化搜索、质量诊断、参数采用四件事的触发条件交叉
3. **节奏与实盘脱节**：每周跑 checkpoint 但不给实盘决策指导
4. **阈值无校准**：okShare 60%、34 快照门槛基于 MACD 公式推导，非真实热榜换手率校准
5. **实盘路径和回测验收路径不一致**：用户用 current_bar 交易，但正式验收基线 H2 用 next_bar

### V1 方案关键数据（2026-05-26）

| 指标 | H1 (current_bar) | H2 (next_bar) | Q1 (quarter_hour) |
|---|---|---|---|
| 总收益 | +3.98% | -4.04% | -2.10% |
| Sharpe | -0.5615 | -1.121 | -0.5124 |
| 交易数 | 65 | 80 | 153 |
| okShare | 48.58% | 48.58% | 52.36% |
| researchGrade | degraded | degraded | degraded |

用户实盘参数：current_bar、maxPositions=5、3-5 天持仓、MACD(21,34,13)+多周期动量(3,5,8,13,21)。

## 架构：四层决策框架

```
Layer 1 (信号有效性)         half_hour 主口径，每期 checkpoint
    ↓ 绿灯
Layer 2 (执行质量)           H1 vs H2 偏差，每期 checkpoint
    ↓ 绿灯
Layer 3 (实盘对齐)           候选池执行记录 × 回测信号，每期 checkpoint
    ↓ 绿灯
Layer 4 (参数优化)           连续 2 期绿灯 + 间隔 ≥ 10 交易日 → 点火
```

每层独立判断，不串扰。任何一层红灯 → 暂停下游，输出结构化警告。

---

## Layer 1：信号有效性

### 问题

不看赚不赚钱，先看信号本身有没有信息量。

### 主口径

half_hour（对齐用户实盘周期），quarter_hour 仅作压力对照。

### 指标与门槛

| 指标 | 计算方式 | 绿灯门槛 |
|---|---|---|
| 分层比例 | (A_MAIN + B_IGNITION) / 总信号 | 2% ~ 15% |
| 分层方向精度 | A_MAIN 信号出现后下一 bar 价格上涨比例 | > 50% |
| 层级区分度 | A_MAIN 精度 - N_NEUTRAL 精度 | > 5pp |
| 价格质量 | allZeroPriceFrames 帧数、crossMarketZeroPriceRows 行数 | 全零帧不增，跨市场占比不恶化 |

### 决策规则

```
全绿 → Layer 1 OK
分层异常（A+B 爆增/暴跌）→ 市场极端事件，暂停后续决策
方向精度 < 50%   → 信号接近随机，仅观察
层级区分度 < 5pp → 策略在当前市场失效警告
```

### 对照口径

quarter_hour 同指标计算：若 half_hour 有效但 quarter_hour 反向 → 策略对时间粒度敏感，记录为策略设计发现，不阻塞决策。

---

## Layer 2：执行质量

### 问题

信号有了，但执行能到位吗？current_bar 入场的乐观偏差你能不能接受？

### 数据

H1（current_bar / 用户实盘路径） vs H2（next_bar / 保守路径）

### 指标与门槛

| 指标 | 计算方式 | 绿灯门槛 |
|---|---|---|
| 执行偏差 | totalReturn(H1) - totalReturn(H2) | < 10pp |
| 偏差方向 | H1 ≥ H2 是否持续 | 大部分 checkpoints 为真 |
| 交易数偏差 | tradeCount(H2) - tradeCount(H1) | < H1 的 30% |
| 回撤差异 | maxDrawdown(H1) - maxDrawdown(H2) | < 5pp |

### 解读

```
H1 > H2 且偏差稳定(< 10pp)
  → current_bar 有可预测时间优势 → 绿灯

H1 > H2 但偏差过大(> 10pp)
  → 乐观偏差严重，实盘可能无法复现 → 黄灯

H1 < H2（next_bar 反超 current_bar）
  → 当前 bar 入场在追高/抢跑 → 红灯
```

---

## Layer 3：实盘对齐

### 问题

回测模型有没有骗你？你的真实交易和回测信号是不是在赚/亏同样的东西？

### 数据来源

- **源 A**：回测信号（每次 checkpoint 自动产出）
- **源 B**：候选池 trade_journal 执行记录（已存在 `trade_journal` 集合，需补充执行字段）

### trade_journal 新增字段

在现有的 `CreateJournalEntryRequest` / `UpdateJournalEntryRequest` 和 `TradeJournal` 模型中新增：

| 字段 | 类型 | 含义 |
|---|---|---|
| `entryPrice` | float | 实际买入价 |
| `entryTime` | str (ISO 8601) | 实际买入时间 |
| `exitPrice` | float | 实际卖出价 |
| `exitTime` | str (ISO 8601) | 实际卖出时间 |
| `stopLossPrice` | float | 设置的止损线 |
| `takeProfitPrice` | float | 设置的止盈线 |
| `positionPct` | float | 仓位占比 |

候选池面板（`CandidatePoolPanel.vue`）复盘卡片内新增"执行记录"区域。

### 对齐报告（每次 checkpoint 输出）

```
数据覆盖: 本期候选 N 只 / 已执行 M 只 / 回测信号推送 K 只
标的重合度: 交集 L 只 / 交集加权收益 / 回测同等标的收益 / 偏差
执行偏差: 平均入场延迟(X bar) / 止盈止损差异 / 偏差盈亏影响
结论: □ 模型可信 □ 存在系统偏差 □ 模型失配
```

### 决策

```
连续 2 期 ✅ → Layer 3 绿灯
出现 1 次 🚨（模型失配）→ 暂停优化，排查信号/执行/数据不一致
出现 ⚠️（系统偏差）→ Layer 4 优化仅作参考
```

---

## Layer 4：参数优化

### 触发条件

```
Layer 1 ✅ + Layer 2 ✅ + Layer 3 ✅ 连续 2 次 checkpoint
AND 上次优化距今 ≥ 10 个 half_hour 交易日
→ 启动新优化
```

### 搜索空间（V2 扩展）

V1 只搜索交易管理层参数。V2 首次纳入用户"拍脑袋"的策略层参数：

**策略层（新增）：**

| 参数 | 搜索范围 | 用户当前值 |
|---|---|---|
| MACD fast | [13, 17, 21, 26, 34] | 21 |
| MACD slow | [26, 34, 42, 55] | 34 |
| MACD signal | [8, 9, 13] | 13 |
| 动量周期组 | [[3,5,8], [5,8,13], [5,10,20], [8,13,21], [3,5,8,13,21]] | [3,5,8,13,21] |

**交易管理层（维持）：**

| 参数 | 搜索范围 |
|---|---|
| maxPositions | [3, 4, 5, 6, 8] |
| takeProfit | [0.08, 0.10, 0.12, 0.14, 0.16] |
| stopLoss | [-0.04, -0.06, -0.08, -0.10] |

### 优化方法

| 口径 | 方法 | 用途 |
|---|---|---|
| half_hour, current_bar | TPE, 72 trials | 主线搜索（对齐用户实盘） |
| half_hour, next_bar | 对 top 3 交叉验证 | 排除乐观偏差 |
| quarter_hour, next_bar | 对 top 3 压力测试 | 排除粒度敏感 |

### 采用规则

```
从 top 3 候选参数中筛选:
  ✅ 主线 validation Sharpe > 0 且 > 当前默认参数
  ✅ next_bar 交叉验证 totalReturn 不转负
  ✅ quarter_hour 压力测试回撤不恶化 > 5pp

全部满足 → 标记"可采纳"，输出对比表（默认 vs 候选 × 三线）
          → 用户决定实盘是否切换
不满足   → "当前默认参数仍是最优"
```

### 止损机制（新增）

```
连续 3 轮 Layer 4 优化（≥ 30 个交易日跨度）:
  所有 trial validation Sharpe < 当前默认参数
  AND 当前默认参数 H2 仍为负收益
→ 触发策略复审：输出"当前搜索空间内无法找到优于默认的参数"
→ 建议结构性调整（扩大搜索空间、引入正交因子过滤、调整策略逻辑）
```

---

## 实施路径

### Phase A：Layer 3 数据结构（最小改动）

1. `trade_journal` 集合新增 7 个执行字段（后端 models + API request）
2. 候选池面板新增"执行记录"区域（前端 CandidatePoolPanel.vue）

### Phase B：Layer 1-2 指标计算（回测侧）

3. 新增 `compute_signal_efficacy()` — 计算分层比例、方向精度、层级区分度
4. 新增 `compute_execution_quality()` — 计算 H1 vs H2 偏差指标
5. 扩展 `summarize_longtest_baseline` — 追加 Layer 1-2 字段到 checkpoint JSONL

### Phase C：Layer 3 对齐报告（新增 API）

6. 新增 `GET /api/backtests/alignment?checkpoint_id=xxx` — 交叉对比 journal 和回测信号
7. 集成到 `run-longtest-baselines` — checkpoint 完成时自动输出对齐摘要

### Phase D：Layer 4 优化扩展

8. 扩展优化搜索空间 — 纳入策略层参数
9. 新增 `optimize-ranktrend` 的分阶段验证（主线 → 交叉 → 压力）
10. 新增止损机制 — 连续不达标的结构化告警

### Phase E：CLI 和文档

11. 扩展 `run-longtest-baselines` CLI 支持四层报告输出
12. 同步 `api-cli.md`、`AI_COLLABORATION.md`

---

## 未纳入的设计项（留待后续）

- 自动止损/止盈执行（当前为人工判断）
- 实时信号推送与回测信号的时间戳精确对齐
- 多策略组合（RankTrend × 资金流 × 题材）的联合优化
- 候选池自动发现规则（已存在 CandidateDiscoveryService，暂不纳入长测链路）
