# RankTrend 生命周期分层阈值数据驱动优化设计方案

> 状态：**brainstorming 草案（待用户确认关键决策）** · 2026-08-16
> 触发：用户判断——"生命周期策略重构不彻底，阶段分层定义还是在之前方案上修改；彻底重构需要
> 根据回测数据优化各个分层阈值，使阶段分层达到最优状态。之前没做是因为历史数据不够 + 方案明确
> 定义不作为买卖投票信号；现在生命周期已纳入四维信号（lifecycle tier 参与 synergy 投票），
> 这个前提可以打破"

## 1. 现状：生命周期分层的硬编码阈值清单（从未数据优化）

### 1.1 raw_stage（engine.py:765-787，5 态初判）
| 判定 | 硬编码阈值 |
|---|---|
| warm（热度） | `current_percentile >= 65 or best <= 25` |
| hot_zone（热区） | `current_percentile >= 85 or best <= 10` |
| recovery（回升） | `velocity > 0 and accel >= -1.2 and (percentile >= 50 or best <= 30 or hot >= 1)` |
| expansion（扩散） | `velocity > 0 and percentile >= 70 and (accel >= -1 or hot >= 1 or best <= 20)` |
| crowded（拥挤） | `hot_zone and (hot >= 3 or best <= 5) and drawdown <= 1 and (velocity <= 1 or accel < 0)` |
| reversal（高位反转） | `warm and drawdown >= 2 and (velocity < 0 or accel < -1) and (hot >= 2 or best <= 10)` |

### 1.2 normalize_stage（engine.py:790-837，状态机平滑）
| 判定 | 硬编码阈值 |
|---|---|
| recovery | 同 raw（50/30/1/-1.2） |
| weakening（转弱） | `velocity < 0 or accel < -1 or drawdown >= 2` |
| severe（严重） | `velocity < -1 or accel < -2.5 or drawdown >= 3` |
| cooling_ready | `percentile < 72 or hot <= 1` |
| crowded_carry | `percentile >= 82 or best <= 12 or hot >= 2` |
| 状态转移表 | ignition/expansion/crowded/reversal/cooling × raw 分支（8+ 条规则） |

### 1.3 cycle_confidence（engine.py:840-850）
每态 region/momentum/persistence/draw 阈值（60/80/82/70、-0.8/-0.2、hot 1/2 等）。

### 1.4 entry_advice（engine.py:853-868）
transition 偏好映射（cooling→ignition / ignition→expansion → preferred 等）。

**关键点**：这些阈值（65/25/85/10/50/30/70/20/3/5/1/2/1/-1.2/-2.5/72/82/12…）全部是
启发式硬编码，**从未用回测数据优化过**。生命周期 tier（由 stage 派生）现参与四维 synergy
投票（`_synergy_tier` 的 lc_tier 环境修正），stage 阈值直接影响交易入场——优化前提已成立。

## 2. 现有证据：生命周期层在四维中的短板

阶段 3 语义校准诊断（769 帧 / 156647 信号，h8 excess）：

| 维度 | S/A/B excess | 问题 |
|---|---|---|
| lifecycle（现状阈值） | 无 S / +0.055 / +0.097 | **S 档无样本**、A/B 无区分（+0.055 vs +0.097 反转） |
| rankTrend | +0.064 / +0.037 / -0.013 | 达标 |
| volumePrice | 无 S / +0.013 / +0.025 | A<B 反转 |
| synergy（合并） | +0.088 / +0.039 / -0.006 | 达标（靠其他三维） |

**lifecycle 是四维中最弱的投票输入**（无 S 档、A/B 不单调）——stage 阈值优化的空间明确。

## 3. 重构目标与设计原则

**目标**：参数化生命周期分层全部硬编码阈值 + 用回测数据搜索最优阈值，使 stage 分层达到
数据驱动的最优状态，提升 lifecycle tier 在四维投票中的方向贡献（excess 单调、S 档有样本）。

**设计原则**：
1. 阈值全部参数化进 RankTrendConfig（`cycleRawStage*` / `cycleNormalize*` / `cycleConfidence*`），
   默认值 = 当前值 → **零行为变化基线**；
2. 搜索结果是候选参数，**不自动写回默认**（项目硬约束：优化结果只产候选）；
3. 评估以**信号层 lifecycle tier 区分度**为主（快、可解释、可对比阶段 3 诊断），
   交易 winRate×pf 为最终验证；
4. TDD：参数化先落地（行为不变回归测试），搜索脚本独立（只读评估）；
5. 生命周期仍保持"环境门 + 投票输入"角色（重构方案 A/B 已定），不恢复硬买卖标签。

## 4. 参数化清单（约 20 个阈值）

```python
# raw_stage
cycleRawWarmPercentileMin: float = 65.0      # warm: percentile >= X or best <= ...
cycleRawWarmBestRankMax: float = 25.0
cycleRawHotZonePercentileMin: float = 85.0
cycleRawHotZoneBestRankMax: float = 10.0
cycleRawRecoveryVelocityMin: float = 0.0     # recovery: velocity > X
cycleRawRecoveryAccelMin: float = -1.2
cycleRawRecoveryPercentileMin: float = 50.0
cycleRawRecoveryBestRankMax: float = 30.0
cycleRawRecoveryHotMin: float = 1
cycleRawExpansionPercentileMin: float = 70.0
cycleRawExpansionAccelMin: float = -1.0
cycleRawExpansionHotMin: float = 1
cycleRawExpansionBestRankMax: float = 20.0
cycleRawCrowdedHotMin: float = 3
cycleRawCrowdedBestRankMax: float = 5
cycleRawCrowdedDrawdownMax: float = 1.0
cycleRawCrowdedVelocityMax: float = 1.0
cycleRawReversalDrawdownMin: float = 2.0
cycleRawReversalAccelMax: float = -1.0
cycleRawReversalHotMin: float = 2
cycleRawReversalBestRankMax: float = 10.0
# normalize_stage
cycleNormWeakeningAccelMax: float = -1.0
cycleNormSevereAccelMax: float = -2.5
cycleNormSevereDrawdownMin: float = 3.0
cycleNormCoolingReadyPercentileMax: float = 72.0
cycleNormCrowdedCarryPercentileMin: float = 82.0
cycleNormCrowdedCarryBestRankMax: float = 12.0
# entry_advice 转移表保持（不参数化，由 stage 优化间接覆盖）
```

## 5. 数据驱动优化设计

### 5.1 优化目标（信号层，主）
对每套阈值参数，replay 全窗口（769 帧）→ 计算 lifecycle tier 分布与 h8 excess：
- **目标 1（主）**：lifecycle S/A/B 档 excess **单调**（S > A > B，spearman 正）且
  S 档样本 ≥ 500（解决"无 S 档"短板）；
- **目标 2（辅助）**：synergy 合并档位保持阶段 3 达标（S/A excess ≥ 0.05 单调）；
- 若信号层达标，再交易模拟验证 winRate×pf（对照当前 four_dim 默认 0.362）。

### 5.2 搜索空间与方法
- ~27 个阈值，每个候选 2-3 档（当前值 ± 偏移）→ 组合爆炸，不适合全网格；
- 推荐**坐标下降**（逐阈值小步调，可解释、快：每轮 ~27 次 replay，每次 ~90s ≈ 40 分钟/轮，
  3-5 轮收敛）+ 灵敏度排序（先优化影响最大的 percentile 阈值）；
- 备选：optuna TPE（全局，但 27 维 × 90s/trial 成本高，需先粗筛维度）。

### 5.3 验收
- 信号层：lifecycle S/A/B excess 单调 + S 样本 ≥ 500（对比现状：无 S、A/B 反转）；
- 交易层：最优阈值组合 winRate×pf ≥ 当前 four_dim 0.362（同窗对比），或至少不劣化；
- 全量 pytest + golden 对齐（阈值默认值不变 → golden 不受影响；优化结果只产候选）。

## 6. 实施路线（确认后展开 writing-plans）

1. **参数化**（TDD）：raw_stage/normalize_stage/cycle_confidence 阈值全部迁入
   RankTrendConfig，默认值 = 当前值，零行为变化回归测试；
2. **搜索脚本**（backend/operations/）：坐标下降评估 lifecycle tier 区分度（复用
   diagnose_tier_discrimination 的 excess 计算），输出候选阈值 JSON；
3. **最优落地**：候选阈值作为可选配置（`RankTrendConfig(cycleRaw*=...)`），golden 对齐 +
   全量 pytest；
4. **前端核对/展示增强**：策略描述核对（rank_trend_candidate 已更新）+ 前端展示
   （生命周期 stage 分布/阈值说明）——用户指定重构后端完成后做。

## 7. 风险与边界
- 生命周期阈值优化可能过拟合单窗口 → 候选需 walk-forward 复核（复用 four_dim 复核模式）；
- 阈值改动影响 lifecycle tier → synergy 投票 → 交易，波及面大 → 参数化先零行为落地，
  搜索候选隔离验证；
- cycle_confidence 阈值较少被消费（仅 confidence 字段），可后置或跳过。
