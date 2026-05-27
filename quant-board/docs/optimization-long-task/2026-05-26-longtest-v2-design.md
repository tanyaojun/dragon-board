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
| 分层方向精度 | A_MAIN 信号出现后下一 bar 价格上涨比例 | > 55% 且二项检验 p < 0.10 |
| 层级区分度 | A_MAIN 精度 - N_NEUTRAL 精度 | > 5pp |
| 价格质量 | allZeroPriceFrames 帧数、crossMarketZeroPriceRows 行数 | 全零帧不增，跨市场占比不恶化 |

> 方向精度门槛说明：50% 是随机基准线。小样本（如 65 笔交易）下精度 55% 的二项检验 p 值约 0.22，仍不显著。设 55% 硬门槛 + p < 0.10 双重条件，确保不会被噪声误判为有效。

### 决策规则

```
全绿 → Layer 1 OK，进入 Layer 2
分层异常（A+B 爆增/暴跌）→ 市场极端事件，暂停后续决策
方向精度不达标   → 信号可能随机，仅观察
层级区分度不达标 → 策略在当前市场失效警告

连续 3 期方向精度不达标 → 触发策略结构性复审（熔断）
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
| 执行偏差 | totalReturn(H1) - totalReturn(H2) | \|偏差\| < \|H1\| 且 < 15pp（取较严者） |
| 偏差方向 | 最近 4 期 checkpoint 中 H1 ≥ H2 的比例 | ≥ 75%（4期中 ≥ 3期 H1 不劣于 H2） |
| 交易数偏差 | tradeCount(H2) - tradeCount(H1) | < H1 的 30% |
| 回撤差异 | maxDrawdown(H1) - maxDrawdown(H2) | < 5pp |

> 执行偏差相对化说明：绝对门槛 10pp 在 H1 收益很小时过于宽松（H1=+1%, H2=-9% 偏差 10pp 通过），在 H1 收益很大时过于严格。改为取 |H1| 和 15pp 的较严者：H1=+4% 时门槛为 4pp；H1=-10% 时门槛为 10pp（取绝对值后的 10pp）。

### 解读

```
H1 > H2 且偏差在门槛内
  → current_bar 有可预测时间优势 → 绿灯

H1 > H2 但偏差超门槛
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
本期执行交易 < 10 笔 → "数据不足，暂不判定" → 不阻塞 Layer 4 点火
本期 ≥ 10 笔:
  连续 2 期 ✅ → Layer 3 绿灯
  出现 1 次 🚨（模型失配）→ 暂停优化，排查信号/执行/数据不一致
  出现 ⚠️（系统偏差）→ Layer 4 优化仅作参考，偏差来源标注在报告中
```

---

## Layer 4：参数优化

### 触发条件

```
Layer 1 ✅ + Layer 2 ✅ + Layer 3 ✅ 连续 2 次 checkpoint
AND 上次优化距今 ≥ 10 个 half_hour 交易日
→ 启动新优化
```

### 搜索空间

**阶段 1（当前，< 60 个交易日）：仅交易管理层**

策略层参数（MACD、动量周期）在当前数据量下固定不变。30000 种策略参数组合 × 65 笔交易 = 极端过拟合风险。改为局部敏感度分析。

| 参数 | 搜索范围 |
|---|---|
| maxPositions | [3, 4, 5, 6, 8] |
| takeProfit | [0.08, 0.10, 0.12, 0.14, 0.16] |
| stopLoss | [-0.04, -0.06, -0.08, -0.10] |

策略层参数敏感度测试（不纳入优化搜索，仅作报告）：
- MACD fast: 当前 21，上下扰动 1-2 档观察指标变化
- MACD slow: 当前 34，同上
- 动量周期组: 当前 [3,5,8,13,21]，测试 [5,8,13] 和 [5,10,20]

**阶段 2（≥ 60 个交易日，约 7 月中）：策略层参数纳入搜索**

当样本量达到 100+ 笔交易时，再将策略层参数纳入 TPE 搜索空间（搜索范围同 V1 设计）。采用 walk-forward 而非单次切分来缓解过拟合。

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

### 止损机制（双层触发）

止损不应只看优化器能否找到更好参数，更要直接监控实盘路径盈亏。

```
条件 A（实盘路径，每期 checkpoint 自动检查）:
  当前默认参数 H1 totalReturn 连续 2 期 < 0
  AND H2 Sharpe 连续 2 期 < -1
→ 触发"实盘策略风险告警"

条件 B（优化路径，Layer 4 点火后检查）:
  连续 2 轮 Layer 4 优化（≥ 20 个交易日跨度）
  所有 trial validation Sharpe < 当前默认参数
→ 触发"搜索空间内无法找到更优参数"

条件 A OR 条件 B 满足任一 → 策略复审:
  - 检查市场状态归属（当前亏损是市场环境问题还是策略逻辑问题）
  - 检查信号有效性（Layer 1 是否同期恶化）
  - 若 Layer 1 健康但 Layer 2 偏差骤增 → 建议调整执行方式
  - 若 Layer 1 同步恶化 → 建议结构性调整（正交因子过滤、策略逻辑修改）
```

---

## 实施路径

### Phase A：Layer 3 数据结构（最小改动，0 依赖）

1. `trade_journal` 模型新增 7 个执行字段（`TradeJournal` + API request models）
2. 候选池面板新增"执行记录"区域（`CandidatePoolPanel.vue`）
3. 扩展 `UpdateJournalEntryRequest` 支持新字段写入

### Phase B：Layer 1-2 指标计算（依赖 Phase A）

4. 新增 `compute_signal_efficacy()` — 分层比例、方向精度（含二项检验）、层级区分度
5. 新增 `compute_execution_quality()` — H1 vs H2 相对偏差、方向占比、回撤差异
6. 扩展 `summarize_longtest_baseline` — 追加 Layer 1-2 字段到 checkpoint JSONL
7. Layer 1 熔断：信号方向精度连续 3 期不达标 → 结构化告警写入 checkpoint

### Phase C：Layer 3 对齐报告（依赖 Phase A+B）

8. 新增 `GET /api/backtests/alignment?checkpoint_id=xxx` — 交叉对比 journal 和回测信号
9. 集成到 `run-longtest-baselines` — checkpoint 完成时自动输出对齐摘要（含最小样本判停）
10. Layer 3 数据验证：至少 N 笔带完整执行字段的 journal 后才产出有意义报告

### Phase D：Layer 4 优化扩展（依赖 Phase C + ≥ 60 个交易日数据）

11. 阶段 1：仅搜索交易管理层参数 + 策略层敏感度报告
12. 阶段 2（≥ 60 天，约 7 月中）：策略层参数纳入 walk-forward 搜索
13. 新增双触发止损机制 — checkpoint 中自动检查条件 A，优化后检查条件 B
14. 策略复审报告模板 — 市场状态归属 + Layer 1-3 同期变化 + 建议方向

### Phase E：P1 统计与基准扩展（依赖 Phase C + ≥ 50 个交易日）

15. 市场状态分层标注 — 基于均线排列和波动率分位，分状态报告 Layer 1-3 指标
16. 基准比较 — 沪深 300/等权持仓基准引入 checkpoint 报告
17. 交易成本显式建模 — 复盘成本对总收益的扣除比例
18. 近期数据指数加权 — 对最近 10 个交易日数据加权 1.5×

### Phase F：P2 归因与合规（依赖 Phase E + ≥ 70 个交易日）

19. 收益归因 — 分解 beta/行业/alpha 贡献
20. 回测股票池去存活规则文档化
21. okShare 角色复审 — 在 Layer 1 分层指标稳定后决定保留/废弃/迁移
22. walk-forward 滚动窗口验证框架

### Phase G：CLI、文档和测试（穿插进行）

23. 扩展 `run-longtest-baselines` CLI 支持四层报告输出
24. 所有新增计算函数补单元测试
25. 同步 `api-cli.md`、`AI_COLLABORATION.md`、`task_plan.md`、`progress.md`

---

## 未纳入的设计项（留待后续）

- 自动止损/止盈执行（当前为人工判断）
- 实时信号推送与回测信号的时间戳精确对齐
- 多策略组合（RankTrend × 资金流 × 题材）的联合优化
- 候选池自动发现规则（已存在 CandidateDiscoveryService，暂不纳入长测链路）

## P0 修正记录（交叉评审后修正）

| # | 原始设计 | 问题 | 修正后 |
|---|---|---|---|
| 1 | 策略层参数立刻进入优化搜索 | 30000组合×65交易 = 极端过拟合 | 分两阶段：<60 天仅交易管理层 + 敏感度报告；≥60 天纳入 walk-forward |
| 2 | 止损只看优化器结果 | 实盘在亏但优化器找到更好的参数 → 不触发止损 | 双层：条件 A 直接监控实盘 H1/H2 盈亏；条件 B 保留优化器判断 |
| 3 | Layer 2 偏差绝对 10pp | 低收益区间过于宽松 | 相对化：取 min(\|H1\|, 15pp) |
| 4 | Layer 1 精度 50% | 无统计显著性，噪声可穿透 | 55% + 二项检验 p < 0.10；连续 3 期不达标触发熔断 |

## 交叉评审附录

评审由独立 agent 执行，提出 16 条改进建议（P0: 4, P1: 5, P2: 7）。P0 已全部修入本文。P1/P2 已纳入实施 Phase E-F 作为第二阶段任务（50+ 交易日数据量后落地）。
