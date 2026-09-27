# 因子口径收敛批 Findings（联动/持续 · 先验通道 · 动量 v2 入链）

- 日期：2026-09-27
- 设计：`2026-09-27-themetrend-factor-convergence-design.md`；runner：`backend/operations/diagnose_theme_factor_marginal.py`（只读）；报告：`data/reports/theme-factor-marginal.json`
- 窗口：2026-07-06 → 09-24，54 个评估日、247 题材键（**已消费窗口，全部结论探索性，正式裁决归 Phase 4 三窗**）

## 1. 头号发现：persistenceScore 是"出生即死"的算子（Critical 数据缺陷）

- 实测 daily 收盘槽 13,433 行、half_hour 抽样 9,800 行，`persistenceScore` **全部为 0.0**——研究 runner 中该因子 IC=None（全天并列）。
- 根因（代码查实，`heat.py`）：**双重缺陷**——①写侧把计数器放进 `metadata.consecutiveHotBuckets`（heat.py:283），读侧却读顶层 `previous_factor.get("consecutiveHotBuckets")`（heat.py:192），路径错位恒取 None；②递增逻辑整体缺失（读 prev 后直接 ×20，无任何 +1 判定）。
- 含义：①路径修复单独无效（prev 恒 0，结果仍恒 0）；②修复 = 重定义"热门桶"递增语义（连续 N 槽 heatScore≥阈值？连续 N 日在榜？）——**属口径裁决而非顺手改码**，按一次一候选登记为独立研究项；③该缺陷自 v1 起存在，所有历史回测不含持续性因子效应（与 Phase 2"拥挤门禁形同虚设"同类：既有结论无需回溯修订，但因子从未生效）。
- **用户裁决待办**：是否立项重建持续性算子（含语义定版 + TDD 重建 + 重跑边际研究）。

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
3. persistenceScore 重建：独立立项待用户裁决（语义定版前置）；
4. 先验通道：本窗 v12 合成分胜出；rotationScore 回放后三方终判；
5. v2 score：不作为同向先验入链；"弱势段反转/退潮预警"语义与 D2 同批另立。

## 7. 复现

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_factor_marginal
# 报告落 data/reports/theme-factor-marginal.json
```
