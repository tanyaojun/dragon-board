# RankTrend 生命周期分层彻底重构设计方案

> 状态：**brainstorming 草案（待用户确认关键决策）** · 2026-08-16
> 触发：用户战略判断——"生命周期分层阶段状态机是最大瓶颈，简单以 A/B 入场、D 退场、其他观望
> 的定义不匹配 RankTrend 四维信号分析，达不到整体提升交易胜率和盈亏比目标，方案需彻底重构"

## 1. 最初的生命周期分层方案（现状还原）

### 1.1 设计源头（docs/superpowers/specs/2026-06-05-strategy-decision-wiring-design.md）
- 分层由 `compose_strategy()` 产出的 `candidateTier` 驱动，分 5 档：
  `A_MAIN`（扩散期动量确认）/ `B_IGNITION`（点火冲击）/ `C_CROWDED`（拥挤高位）/
  `D_EXIT_RISK`（反转/冷却风险）/ `N_NEUTRAL`（观望）
- **入场规则（AND）**：`candidateTier in {A_MAIN, B_IGNITION}` 才有入场资格 + `final_signal` 确认
- **退场规则**：`D_EXIT_RISK` 或 `C_CROWDED ∧ acceleration ≤ 0`
- 分层阈值硬编码（`momentum["mid"] >= 4` 等），不可配置

### 1.2 已知缺陷（docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md）
- "A_MAIN 分层本质是'排名趋势处于扩散期'，不是'技术指标看涨'"（L1 方向精度 39% < 随机 50%）
- **"生命周期分层实现不能继续被当成可靠买卖标签……不适合作为硬入场、硬过滤或独立买卖系统"**
- `stage` 一旦判错，A/B/C/D 同时错（档位强依赖生命周期阶段）
- 审计给出的正确方向：**入场主轴 = jump 高置信 + 多周期动量同步转正 + 动量加速度抬升 + 可成交性；
  生命周期不制造买点、不硬过滤、只参与排序降权和风险解释**

### 1.3 代码现状（engine.py + execution.py 状态机）

```
cycle stage（5 态，raw_stage 基于 percentile/velocity/accel/hot/drawdown）
  └─ lifecycle_decision → action（veto/caution/allow/exit_watch）+ lifecycle tier（S/A/B/C/D/E）
       └─ compose_analysis_candidate_tier（engine.py:1544）
            ├─ veto → N_NEUTRAL（阻止进入 A/B 候选池）
            ├─ reversal/cooling + 弱动量/风险压力 → D_EXIT_RISK
            ├─ crowded / 高位动量减速 → C_CROWDED
            ├─ expansion + mid/short 动量 + trend_buy + 非弱市 → A_MAIN
            ├─ ignition + short/accel 动量 → B_IGNITION
            └─ 其它 → N_NEUTRAL
       └─ entry_advice（engine.py:853）
            ├─ transition ∈ {cooling→ignition, ignition→expansion} → preferred
            ├─ stage == reversal → blocked
            ├─ stage ∈ {cooling, crowded} → avoid
            └─ 其它 → watch
  └─ execution._entry_candidates（交易层映射）
       ├─ 入场：candidateTier ∈ {A_MAIN, B_IGNITION}（+策略 final_signal 确认）
       ├─ 退出：D_EXIT_RISK / C_CROWDED∧accel≤0 / final sell / rank>50 / synergy 风控
       └─ 其他：观望
```

## 2. 瓶颈分析（证据链）

### 2.1 生命周期"阶段"本身无方向预测力（阶段 3/6 研究实证）
| 信号 | h8 winRate | 结论 |
|---|---|---|
| 全体基线 | 0.5076 | — |
| cycle stage=reversal（高位回落） | 0.4973 | 无预测力 |
| expansion→reversal 周期回落 | 0.4898 | 弱（卖出侧有效） |
| D_EXIT_RISK 状态（低分位） | 0.5264 | **预测反弹**（均值回归） |
| **D→B_IGNITION 档位跃迁** | 0.5198 | **唯一有效状态机信号**（质变） |

### 2.2 "A/B 入场、D 退场、其他观望"的简单映射不匹配四维信号
- **A_MAIN 入场档 h8 0.514 < S/A 基线 0.5272**（策略-信号匹配度评估 s7）——分层过滤掉了最强的
  synergy S/A 信号（S/A 中仅 65% 进 A_MAIN 候选，见 s7 Jaccard 0.60）
- **D_EXIT_RISK 退出在均值回归区过早离场**（D 档未来反弹 0.5264）——"D 退场"语义与数据相反
- 生命周期五态是**排名动力学标签**（路径解释），不是**方向信号**——用它硬驱动买卖必然错配
- 四维 synergy 档位（S/A/B，阶段 3 验收：单调 excess 0.088/0.039/-0.006）才是方向信号，
  却被生命周期候选池硬门槛截断

### 2.3 最强单因子从未进交易链路
- 资金净流入 zljzb>5：h8 **0.5538**（全维度最强，n=30358）——量价维度拐点研究（74e9f41）
- 放量上涨 + 资金流入：0.5487
- 这些因子在现有分层（动量 + 生命周期阶段）中没有独立入口

### 2.4 结论：瓶颈 = "生命周期状态机充当方向信号"
生命周期（stage → candidateTier → 交易）把**路径上下文**当**方向信号**用：
- 买点由"生命周期阶段 + 动量"决定，丢弃了四维 synergy 的方向投票
- 卖点由"生命周期回落"决定，但回落档预测反弹（均值回归）
- 与 6-07 审计结论一致，且被后续研究反复证实

## 3. 重构目标与设计原则

**目标**：让交易决策回到"四维信号方向 + 资金确认"主轴，生命周期降级为环境门与风险解释；
  消除"生命周期阶段当方向信号"的结构性错配，为胜率/盈亏比提升腾出空间。

**设计原则**（延续项目硬约束）：
1. 生命周期**不制造买点、不硬过滤**（6-07 审计方向）；保留 veto/exit_watch 风控与排序降权
2. 入场主轴 = **synergy 档位（S/A，四维投票，阶段 3 验证单调）+ 资金确认（zljzb）** +
   可成交性；candidateTier 降为报告/诊断字段（不再驱动交易）
3. 退出主轴 = **final sell + 弱势状态（fall_volume / zljzb 强流出）+ 价格止损**；
   D_EXIT_RISK 档位退出按 3c311e3 已证与弱势状态同帧等效，可保留或移除（见方案）
4. 默认参数不变 → 零行为变化（新策略 `rank_trend_four_dim` 作为研究对照，不覆盖现有策略）
5. TDD：先研究对照策略验证（h8 统计 + 交易模拟），后决定是否替换默认

## 4. 重构候选方案（待用户决策）

### 方案 A：生命周期降级 + synergy 入场（推荐，最小破坏渐进）
- 新增策略 `rank_trend_four_dim`（研究对照，默认不覆盖现有策略）：
  - **入场**：synergy tier ∈ {S, A}（四维投票方向一致）∧ zljzb ≥ 0（资金不流出）∧ 可成交
  - **退出**：final sell / fall_volume / zljzb < -5 / 价格止损止盈 / maxHoldingBars
  - **生命周期**：仅 veto 一票否决 + stage 排序降权（报告中展示，不硬过滤）
  - candidateTier 保留输出（诊断），不参与交易映射
- 验证：h8 统计对照（synergy S/A 0.5272 + 资金 0.5460 → 期望 ~0.55）+ 交易模拟 winRate×pf
- 影响面：新增策略 + 测试，现有策略零改动

### 方案 B：彻底移除生命周期硬门槛（激进）
- 同方案 A，且 **D_EXIT_RISK / C_CROWDED 退出从现有默认策略中移除**，退出统一为
  final sell + 弱势状态 + 价格止损
- 影响面：默认策略行为变更，需 golden 对齐 + 全量测试更新 + 前端展示口径变更
- 风险：默认策略回测结果变化大，需样本外复核

### 方案 C：保留分层但重定义档位语义（保守）
- candidateTier 档位语义重定义为四维信号聚合（A=四维 S/A 票 ≥2，D=弱势状态），
  生命周期 stage 只作 reasons 说明
- 影响面：compose_analysis_candidate_tier 重构，破坏面介于 A/B 之间

## 5. 关键决策点（待用户确认）

1. **生命周期角色**：完全移除 vs 降级为环境门+风险解释（推荐后者，保留 veto/风控）
2. **入场主轴**：synergy S/A + 资金 zljzb（推荐）vs 仅资金 vs 仅 synergy
3. **实施路径**：新增研究对照策略（方案 A，推荐，零风险渐进）vs 直接替换默认（方案 B）
4. **资金阈值**：zljzb ≥ 0（不流出）vs zljzb > 5（强流入，n 更少更纯）

## 6. 实施路线（确认方案后展开 writing-plans）

1. TDD 研究对照策略 `rank_trend_four_dim`（入场/退出纯函数 + 单测）
2. h8 统计对照（synergy+资金 vs 现有 A_MAIN 候选）——真实数据
3. 交易模拟对照（winRate×pf vs rank_trend_candidate 基线 0.123 / trj 0.537）
4. 达标（winRate×pf 显著 > 基线）→ 按方案 A/B/C 决定默认策略切换；未达标 → 归档证伪
5. 全量 pytest + golden 对齐 + 文档更新
