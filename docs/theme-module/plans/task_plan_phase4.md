# ThemeTrend v12 升级 Phase 4 汇合实施计划

- 日期：2026-09-27
- 状态：**接线层已完成**（theme_daily_factors 落库链路 + 条件层机制接线默认关，2026-09-27）；**`persistenceScoreWeight` 已接线并定版 Path B 原料**（默认 0.0 + 日级 heatLevelStreak 注入通道，2026-09-27，见 §5.1-2）；**终判跑批待 10 月批次合流**（等未消费帧）
- 关联：`docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md`（§5.1 存储、§5.3 门控、§6.1 双轨路径）；纪律沿用 `skills/ranktrend-signal-research/SKILL.md`

## 1. 目标

两轨过验项（情绪相位门控 Phase 1、拥挤度分位口径 Phase 2）的机制与存储已接线（默认关，零行为变化）。Phase 4 剩余工作 = 用 10 月批次新增的**未消费帧**跑 v12 三窗回测，对门控/阈值参数做终判裁决，一次一候选落默认，产出题材域首份成册 verdict 文档。当前 7-06→9-25 全部帧已被 Phase 1/2/3 + R1/R2/R3/R3b 消费，直接终判违反"最终裁决窗用未消费帧（M3）"纪律，故跑批与 10 月批次合流（hybrid 月度复验、D3 复验同批）。

## 2. 已完成接线层（2026-09-27）

| 件 | 落地 | 测试 |
|---|---|---|
| theme_daily_factors 落库 | `backend/analysis/theme/factors_daily.py`（纯函数装配）+ `backend/data/repositories/theme_daily_factor_repository.py`（upsert/查询）+ `backend/services/theme/daily_factors_service.py`（收盘槽取数、自动 catch-up、Redis 缓存）+ `daily_factors_scheduler.py`（每日 18:30，仅 mongodb 后端，挂 main.py lifespan） | `tests/test_theme_daily_factors.py` 13 用例 |
| 条件层机制接线（默认关） | `backtest_service._theme_gating_inputs`（15:00 帧 marketPhase + 因子分位读取）+ `_theme_execution_signals` 门控块（降可信+打标，tier 不变，可叠加）+ `run_theme_trend` payload 开关 | `tests/test_theme_gating.py` 12 用例 + `test_theme_backtest.py` 29 用例回归全绿 |

- payload 开关（全部默认关）：`sentimentGatingEnabled`、`crowdingPercentileEnabled`、`sentimentGatingPhases`（提案默认 cooling/ice）、`sentimentGatingConfidencePenalty`（提案 10.0）、`crowdingPercentileHighThreshold`（提案 90.0）、`crowdingPercentileConfidencePenalty`（提案 10.0）。
- `persistenceScoreWeight`（默认 0.0，`run_theme_trend`/`run_theme_confluence` payload 均可传）：v12 六维合成分附加项，**附加项语义、不重新归一**。**原料 = 注入的日级 `heatLevelStreak`**（2026-09-27 Path B 裁决：weight>0 时服务读 theme_daily_factors 经 `replay_sequence(daily_factors=...)` 注入，默认路径零 IO；in-frame 多帧 persistenceScore 经实测 99.3% 恒 92.0 已弃用，详见 §5.1-2）。量纲 = 日计数（非 0-100）。非法/负/非有限值回落 0.0（fail-visible）；weight>0 而原料未注入/键未中/值 None 分别显式打标，不静默按 0。
- 提案默认值**不是落默认**：仅显式开关打开时生效，数值待 P4-3 扫描 + P4-5 裁决。
- 调度器 status 经 main.py 状态端点 `themeDailyFactors` 键暴露（fail-visible 观察口）。

## 3. 剩余阶段（10 月批次合流后执行）

> **执行方案已定稿落盘（2026-09-27，D1-D3 已裁决）**：`docs/theme-module/2026-09-27-themetrend-october-batch-plan.md`（B-202610 ThemeTrend 分册，Wave 2）。裁决结果：D1 替换口径移出本批（S2 = 并列门控）；D2① 75 硬层已参数化（`crowdedHardLayerThreshold`，信号层+执行层六消费点单旋钮，逐位不变测试钉住）、D2② 60 起扣移出（v2 分数不在回测合成分，扫它对 PnL 零效应）；D3 终判窗纳入 09-28~09-30。批次日历 / 窗口定义 / 共享数据检查点 / 扫描通道与量纲重推后的候选集均以该文档为准；本节保留扫描清单原文备查。

- **P4-1 数据积累确认**：调度器自动积累 theme_daily_factors（检查 status 的 lastResult）；10 月复市后确认新帧入库量（≥10 个交易日做初判，量足再终判）。
- **P4-2 三窗划分定版**：已消费窗（7-8 月、9 月）打折标注，10 月为未消费终判窗（M3）；具体边界在跑批方案中按窗口推进 + 极端行情月感知定版。
- **P4-3 参数扫描**（隔离 runner、单 trial、本地 frames、一律 dry-run）：
  1. 情绪门控：phases ∈ {cooling / cooling+ice / cooling+ice+chaos} × penalty ∈ {5, 10, 15, 20}；
  2. 拥挤度分位：threshold ∈ {80, 90, 95} × 替换 vs 并列瞬时口径 × penalty ∈ {5, 10, 15}；
  3. 75 硬层 / 60 起扣形同虚设修正：阈值重定 ∈ {35, 45, 55}（crowdingRisk 量纲 daily max 24.8 / half_hour max 71.08，与阈值差一个数量级——Phase 2 实测）；
  4. **persistenceScoreWeight ∈ {0, 0.25, 0.5, 1.0}**（2026-09-27 量纲重推；终值仍归本阶段扫描 + P4-5 裁决）。**原料已定版 Path B**：注入的日级 `heatLevelStreak`（连续 N 日 heatLevel ≥ 70，theme_daily_factors.factors 键），与 D3 同面板对照防双持续性重复计分；heat.py 日内粒度 consecutiveHotBuckets 仅实时观察不进扫描；in-frame 多帧 persistenceScore 经实测 15:00 收盘帧 99.3% 恒 92.0 已弃用（详内 §5.1-2）。**量纲推导**：heatLevelStreak 为日计数（全库实测 n=12,462：>0 仅 8.4%，正值段 p50=3 / p75=7 / p90=10 / max=15）——w=0.25 时 p75 长档 +1.8 分（微弱）、w=1.0 时 p75 +7 分 / max +15 分（接近 momentum 量级 25 分），原 {0,0.03,0.05,0.08} 按 0-100 因子定、max 长档仅 +1.2 分，扫描无意义；w≥2.0 会使 1% 长档主导合成分（max +30），仅作边界点不进主网格。合成式归一化语义已定版为「附加项、不重新归一」；扫描通道 = 显式 `parameterGrid`（优化器注入已接，2026-09-27，默认网格不含此参）。
- **P4-4 三窗回测重跑**：过验项开启 + 参数扫描结果，按 market_phase × rotation_regime（引擎 rotationState + Top1 稳定性）分层评估。
- **P4-5 落默认裁决 + verdict 存档**：一次一候选；verdict 文档对标 RankTrend 域 `exit-scan-batch*-verdict.md`，落 `docs/theme-module/`。

## 4. 验证命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_daily_factors.py tests/test_theme_gating.py tests/test_theme_backtest.py
# 回测一律 dry-run（扫描资源纪律）：
.\.venv\Scripts\python.exe -m backend.cli run-theme-trend --dry-run ...
```

## 5. 未决问题

- 拥挤度分位"替换还是并列瞬时口径"（Phase 2 留待三窗裁决）；
- persistenceScore 重建后 heatLevelStreak 边际研究**已重跑**（2026-09-27，结论 findings §1：本窗无增量不进 combine；Q5−Q1 −0.323 负向随 10 月未消费窗复验）；
- 另批不阻塞本计划：D2 夏普动量反转语义、SG3 15:00 口径、腾讯日 K 回溯交叉验证、D3/F1 10 月复验、hybrid 月度复验（10 月批次）；
- MainlineScore 合成层结构改造（暂缓项）不进本批次，待后续候选再议。

### 5.1 2026-09-27 接线后新登记（P4-1/P4-3 前必须处置）

1. **`crowdingPercentile` 跨 2026-07-06 存在口径切换（新发现，Mongo 实测）**：调度器 lookback（`daily_factors_service` window×2+buffer）已把 `theme_daily_factors` 自动回溯到 **2026-05-06 起 96 个交易日、21,269 行**（远超本计划记录的「54 研究日 13,188 行」）。但 07-06 之前 `amountShare` 全 None（`amount_unobservable`，stock rows amount 字段 7 月上旬才起落库），`crowdingPercentile` 退化为 `turnoverMeanPct` 单侧（实测 5944/5944 行 `cp == turnoverMeanPct`）；07-06 之后为 `amountSharePct` + `turnoverMeanPct` 等权（`factors_daily.combine_equal_weight`）。Phase 2 研究窗自 07-06 起、未覆盖该混合段。**P4-3/P4-4 若直接用长窗会把口径切换当成因子信号**——处置二选一：①拥挤度分位序列截窗到 07-06；②`factors_daily` 对单侧退化加显式口径标记（如 `crowding_percentile_turnover_only`），扫描时按标记分层。
2. **`persistenceScoreWeight` 原料裁决：Path B 已实施（2026-09-27 用户确认）**：合成项改吃**注入的日级 `heatLevelStreak`**（`replay_sequence` 新参 `daily_factors={trading_date: {theme_key: {factor_name: value}}}`，`run_theme_trend`/`run_theme_confluence` 在 weight>0 时经新帮手 `_theme_daily_persistence_inputs` 读库注入，默认路径零 IO）。**弃用 in-frame 多帧 `persistenceScore`**：实测全研究窗（07-06~09-24，125,034 行/509 帧）复刻该公式得 15:00 收盘帧 **99.3% 恒 92.0**（公式 d=5 饱和 + half_hour 同日题材集只增不减、同日掉出=0/进入=91），横截面零方差不可作因子，且编码的是「几点进当日采集池」这一采集伪影。键对齐实测：theme_daily_factors 按 themeId+themeName 存，half_hour 因子只有 entityKey/entityName，**entityName∩themeName=245/245 完全对齐、∩themeId=0** → 双键中 themeName 是唯一有效对齐键。fail-visible 三态：weight>0 时 `persistence_daily_source_not_provided`（调用方未注入）/`persistence_daily_key_missing`（该主题-日期无行）/`persistence_daily_value_insufficient`（行在但值 None）；flag 仅在有话可说时挂 `signals[].qualityFlags`，默认路径 dict 逐位不变。**两个待办（2026-09-27 当日已解决）**：①~~优化器路径未接注入~~ **已接**：`optimization_service.run_theme_trend` 新增 `_grid_requests_daily_factors` 探测（list choices / range spec 两态），搜索空间含 >0 权重时才一次性装载、全 trial 复用、逐 trial 透传；默认网格不含此参、零 IO（负向控制测试钉住）；装载帮手已迁至 `daily_factors_service.load_daily_persistence_inputs`（唯一无环归宿：该模块本就模块级依赖 backtest_service，反向模块级导入会成环；backtest/optimization 均函数级延迟导入）；typed 路径同步补 `ThemeSignalRow.qualityFlags` 字段（原先 `_to_typed_result` 字段白名单会静默丢标，fail-visible 失效——已堵）；`theme_research_service` 维持不接注入（无消费方传 >0 权重，flag 如实打标，接线待有消费方再议）。**登记待办（code review M-4）**：research 持久层（`theme_research_repository` SQL 白名单 / `mongo_research_repository._theme_signal_doc`）尚无 `qualityFlags` 字段，typed 修复只到内存/API 层——将来 research 路径接注入前必须先补持久层字段，否则 fail-visible 在落库处断一截。②~~量纲重推~~ **已重推并登记**：候选改为 `{0, 0.25, 0.5, 1.0}`（推导见 P4-3-4），终值仍归 10 月扫描 + P4-5 裁决。
3. **`theme_search_space()` 存在静默丢参（新发现，代码查实）**：`optimization/search_space.py:theme_search_space()` 声明了 `momentumWeight`/`breadthWeight`/`fundWeight`/`leadershipWeight`/`correlationWeight`/`persistenceWeight` 六个权重键，但 `ThemeTrendConfig` **无对应字段**，`optimization_service` 走 `ThemeTrendConfig.from_patch` 时被 `hasattr` 静默忽略——这些参数从未真正进入引擎。因默认网格若新增键会改变既有优化行为，本次**未**把 `persistenceScoreWeight` 加进默认 `theme_search_space()`；P4-3 扫描一律经显式 `parameterGrid` 传入（现有 `test_theme_optimization_report_includes_parameter_sensitivity` 范式），保持默认路径零行为变化。历史主题优化报告若含上述六键，其「参数敏感度」结论对该六键无效。
4. **heatLevel 落库缺口导致 streak 维度部分日期不可评估（新发现）**：2026-09-22 `heatLevelStreak` 仅 9/245 行有值（当日 heatLevel 未落库 → `resolve_heat_level` 回退值 <70 → streak≈0），与 findings §1「7/8 月落库率 0%」同源。10 月复验前需确认 collector 侧 heatLevel 落库是否已稳定。
