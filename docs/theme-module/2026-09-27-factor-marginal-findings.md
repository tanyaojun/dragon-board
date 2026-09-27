# 因子口径收敛批 Findings（联动/持续 · 先验通道 · 动量 v2 入链）

- 日期：2026-09-27
- 设计：`2026-09-27-themetrend-factor-convergence-design.md`；runner：`backend/operations/diagnose_theme_factor_marginal.py`（只读）；报告：`data/reports/theme-factor-marginal.json`
- 窗口：2026-07-06 → 09-24，54 个评估日、247 题材键（**已消费窗口，全部结论探索性，正式裁决归 Phase 4 三窗**）
- **状态更新（2026-09-27 当日）**：§1 persistenceScore 已立项重建（heat.py 管道修复提交 `80c7cbee`、日级 heatLevelStreak 算子提交 `ef82ea45`），runner candidate 已就位；本报告数据仍为重建前窗口（persistenceScore 恒 0），**heatLevelStreak 边际结论待 Mongo 27017 可用后重跑补录**。

## 1. 头号发现：persistenceScore 是"出生即死"的算子（**已立项重建**，2026-09-27 当日）

- 实测 daily 收盘槽 13,433 行、half_hour 抽样 9,800 行，`persistenceScore` **全部为 0.0**——研究 runner 中该因子 IC=None（全天并列）。
- 根因（代码查实，`heat.py`）：**双重缺陷**——①写侧把计数器放进 `metadata.consecutiveHotBuckets`（heat.py:283），读侧却读顶层 `previous_factor.get("consecutiveHotBuckets")`（heat.py:192），路径错位恒取 None；②递增逻辑整体缺失（读 prev 后直接 ×20，无任何 +1 判定）。
- **重建结论（用户已裁决 Q1=c/Q2=c/Q3，计划 `plans/task_plan_persistence.md`）**：
  1. Q3（已提交 `80c7cbee`）：heat.py 路径修复 + 递增/重置逻辑（上一帧 heatLevel ≥ 70 → 计数+1，否则归 0；prev 缺失/heatLevel 缺失分别打 `persistence_history_insufficient`/`persistence_previous_unobserved`，fail-visible）。架构事实：previous_factor 供给 = `heat_service._last_success`（同进程相邻刷新，300s TTL 桶内缓存命中不重算；collector 独立进程重启即断链）→ 日内槽位粒度约 5 桶饱和，**仅作实时观察**；
  2. Q1=c 主口径（已提交 `ef82ea45`）：日级 `factor_series.level_streak`（连续 N 日 heatLevel ≥ 70）入 `theme_daily_factors.factors.heatLevelStreak`（momentumV2 同型接线，auto 模式自愈补算）。与 D3（截面 Top 成员连续）**不同型**，同面板对照防双持续性重复计分；
  3. Q2=c：日级算子原料 = 已落库 daily sector rows 的 heatLevel（`resolve_heat_level` 统一消费规则），54 天历史窗口即时可算，无回填依赖。
- **修复前后对照**：历史 Mongo 数据恒 0（该因子从未生效）——回测 PnL 不变合同测试钉住（`test_theme_backtest.py::test_theme_backtest_pnl_invariant_to_persistence_score`：persistenceScore 0 vs 100 极端值下 tier/confidence/成交逐条一致），既有回测结论无需回溯修订；
- **重跑待办**：`heatLevelStreak` candidate 已入 runner（`diagnose_theme_factor_marginal.py` CANDIDATES + load_stored_factors 投影），边际结论待管理员启动 MongoDB 27017 后重跑补录（见 §6 与 §7 状态标注）。

## 2. 联动度（correlationScore）：数据健康、无增量信息

- 分布健康（1,896 个不同值），但 pooled IC −0.005（零附近）、**边际 IC −0.001**（51 天有值）；分月 +0.046 → +0.004 → −0.057 与动量衰减梯度同构，无独立方向。
- **结论**：现行"方向一致性"口径在 T+1 前向上不构成对 v12 六维的增量——进合成分的证据不足。备选口径（成员收益横截面相关/beta）若要研究，需另批（本窗无信号支持优先级）。

## 3. D3 动量连续性（可用的持续性替代口径）：同样无边际

- `top_membership_streak`（日线 momentumScore Top 五分位连续保持）pooled IC +0.025、**边际 IC −0.009**；分月 +0.133 → +0.002 → −0.034——7 月有信息、8-9 月消失，与动量衰减同构。
- **结论**：persistenceScore 重建前后，D3 是唯一可用的持续性口径，但本窗无边际信息；持续性方向整体搁置观察，等 10 月样本。

## 4. 数值先验通道 ablation：v12 合成分 vs 动量 v2（rotationScore 登记待回放）

| 先验 | pooled IC | 分月（7/8/9） |
|---|---|---|
| v12 六维合成分 | **+0.047** | +0.186 / +0.024 / −0.041 |
| 动量 v2 score | −0.050 | −0.011 / −0.022 / −0.107 |

- v12 合成分呈已知"动量有效性随情绪衰减"梯度（与 Phase 1/3 互证）；v2 score 在弱势段**反向加深**（9 月 −0.107）——与 Phase 1 cooling 期动量反转、Phase 3 D2 夏普动量反向同族。
- **本窗裁决倾向**：先验通道由 v12 合成分占据（方向正确且幅度更高）；v2 score 在弱势段是**反转信号**而非同向先验——其价值候选是"退潮预警"语义（与 D2 反转语义观察项同批归档），不作为同向因子入链。
- rotationScore：历史未落库（仅 mainLines 8 天），逐槽引擎回放 harness 登记为 Phase 4 前置；回放完成后三方对照出终判。

## 5. 动量 v2 子维度速览

- v2Breadth 边际 IC −0.083（52 天）——唯一 |边际|>0.05 的非主因子候选（宽度在合成分之外的负向增量），登记观察项；
- v2WindowMomentum 边际 +0.002、v2NearHigh 边际 −0.010——无增量；
- v2FlowVolume 全窗不可用（amountRatio 恒缺失 → 序列打 amount_ratio_missing，符合设计预期）；
- v2 得分覆盖率随历史成熟：7 月 69% → 8 月 99% → 9 月 100%（Task1 回填后 54 天 13,188 行含 momentumV2）。

## 6. 汇合裁决清单（供 Phase 4，一次一候选）

1. 拥挤度分位（crowdingPercentile）：边际 IC −0.063 持续为负向增量（8/9 月 IC −0.083/−0.092）——维持 Phase 2 过验项地位，进 Phase 4 参数扫描；
2. 联动度/持续性/D3：均无边际信息，**不进 combine**，机制保留；
3. persistenceScore 重建：**已实施**（Q3 heat.py 管道修复提交 `80c7cbee`；日级 heatLevelStreak 算子提交 `ef82ea45`）——runner candidate 已就位，**边际结论待 Mongo 重启后重跑补录**；接线归 Phase 4 终判（`ThemeTrendConfig.persistenceScoreWeight` 默认 0，golden 不变）；
4. 先验通道：本窗 v12 合成分胜出；rotationScore 回放后三方终判；
5. v2 score：不作为同向先验入链；"弱势段反转/退潮预警"语义与 D2 同批另立。

## 7. 复现

```powershell
cd quant-board
# 注意：persistenceScore 重建后重跑需 Mongo 27017 运行（当前会话启动服务
# 权限不足，报告数据停留在重建前窗口——heatLevelStreak 结论 pending，
# 不伪造、不用重建前恒 0 数据代替新算子结论）。
.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_factor_marginal
# 报告落 data/reports/theme-factor-marginal.json
```
