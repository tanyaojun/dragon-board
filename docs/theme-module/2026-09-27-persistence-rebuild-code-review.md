# persistenceScore 重建立项 Code Review（Commit A/B/C/D + Minor 修复）

- 日期：2026-09-27（重跑结论落档后复审）
- 范围：提交 `80c7cbee`（heat.py 管道修复）/ `ef82ea45`（日级 level_streak + theme_daily_factors 接线）/ `224506da`（runner candidate + 文档）/ `f43ddb05`（生产形态缺口修复 + 重跑结论）+ 本次 Minor 修复提交
- 审查方式：全量 diff 人工审读 + 生产数据实证查证（Mongo 27017）+ 专项回归 145 用例
- 对标先例：`2026-09-26-r2-r3-phase1-code-review.md`

## 1. 审查结论

**0 Critical / 0 Important / 2 Minor（本次已修）/ 3 观察项（登记不修）**

## 2. 发现与处置

### Minor 1（已修）：build_heat_level_streak_values 空输入无标记

- 现象：空输入返回 `({}, [])`，与同族 `build_momentum_v2_daily_values` 的 `momentum_v2_no_series` 不一致；stock rows 有、sector rows 全缺时 streak 维度静默空，服务层 qualityFlags 收不到任何信号。
- 违反：AGENTS.md §4.0 fail-visible（质量检查职责是暴露、聚合、上报；不得静默转成"没有数据"）。
- 修复：空输入返回 `["heat_level_streak_no_series"]`，docstring 同步；RED→GREEN（`test_empty_reported`）。

### Minor 2（已修）：heat_level_streak_insufficient 标记无测试覆盖

- 现象：`merge_heat_level_streak_into_rows` 的 None → 标记逻辑与 momentumV2 同型且实现正确，但无任何测试断言该路径（streak=None 落库 + 去重）。
- 修复：补 2 个用例（`test_none_streak_marks_insufficient_not_fabricates`、`test_insufficient_marker_deduplicated`）。

### 观察 3（登记不修）：heat.py previous_count 无上界 clamp

- 脏大值（如 999999）会写入 metadata 续传；但公式 `min(计数×20, 100)` 已封顶分数，且有封顶 known-answer 测试（prev count 6 + heatLevel 90 → 100），无实际危害。metadata 传播大值属理论风险，若后续日级/日内双口径收敛时再统一 clamp。

### 观察 4（登记不修）：level_streak 非数值输入 TypeError

- `v >= threshold` 对字符串抛 TypeError；与同族 `positive_streak`（`value > threshold`）既有语义一致，且实际调用链（`resolve_heat_level` → float|None）已保证类型。通用纯函数不重复造类型防御。

### 观察 5（登记不修）：31 个中文退化键 streak-only 行

- 早期落库 daily sector rows 的 entityKey 退化为题材中文名（'AI'/'AI硬件'等， mappings 无对应 themeId），与 momentumV2 同样接纳为新建行（crowding_unobservable）；runner 双键索引（themeId/themeName）可正常消费。属既有口径一致行为，不新造过滤。

## 3. 实证查证通过项

1. **题材键口径**：生产 daily hot_theme rows 13,503 行全部无 `themeId` 字段、entityKey 唯一标识；`themeId or entityKey` 回退与 `daily_series.py:84` 一致；245/276 entityKey 与 mappings themeId 空间重合（31 个为中文退化键，见观察 5）；
2. **行唯一性**：Sep 窗口 (entityKey, tradingDate) 重复组 = 0，slotTime 全部 15:30（收盘槽）——`heat_level_by_theme[theme][day]` 无静默覆盖风险；
3. **as-of 语义**：streak 目标日值只依赖 ≤目标日序列（level_streak 按日期序推进），与 momentumV2 截断语义同族；
4. **补算零漂移**：13,188 行补算前后，60 行抽样既有 factors 字段（amountShare/momentumV2/qualityFlags 等）逐字节一致；
5. **回测 PnL 不变**：persistenceScore 0 vs 100 极端值下 tier/confidence/tradeSimulation 逐条一致（合同测试）；
6. **auto 自愈**：complete 条件含 `factors.heatLevelStreak` $exists，与 momentumV2 同型（缺维度旧日期自动补算，不依赖一次性回填）。

## 4. 重跑结论回顾（2026-09-27）

- heatLevelStreak 本窗 54 天仅 **15 天可评估**（7/8 月 heatLevel 落库率 0% → v1 回退值 <70 → streak 无横截面变异；9 月 14 天）；
- 9 月：pooled IC +0.004（icNeg 0.5）、边际 IC +0.004（≈0）、Q5−Q1 −0.323（稀疏 n 下大幅倒挂）；
- **裁决：不进 combine**（与 D3 同族）；Q5−Q1 负向登记 10 月未消费窗复验（若复现，与 D2/Phase 1 动量反转同批归档"退潮预警"语义）；
- persistenceScore 历史恒 0 复证修复前状态（修复前后对照组成立）；
- 接线归 Phase 4 终判（`ThemeTrendConfig.persistenceScoreWeight` 默认 0，golden 不变）。

## 5. 验证命令（quant-board 目录）

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_theme_daily_factors.py tests/test_theme_factor_series.py tests/test_theme_heat_engine.py tests/test_theme_trend.py tests/test_theme_backtest.py tests/test_theme_trend_heat_level.py tests/test_theme_heat_collector_contract.py tests/test_theme_heat_service.py tests/test_theme_momentum_daily_series.py
# 145 passed
```
