# ThemeTrend v12 升级 Phase 4 汇合实施计划

- 日期：2026-09-27
- 状态：**接线层已完成**（theme_daily_factors 落库链路 + 条件层机制接线默认关，2026-09-27）；**终判跑批待 10 月批次合流**（等未消费帧）
- 关联：`docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md`（§5.1 存储、§5.3 门控、§6.1 双轨路径）；纪律沿用 `skills/ranktrend-signal-research/SKILL.md`

## 1. 目标

两轨过验项（情绪相位门控 Phase 1、拥挤度分位口径 Phase 2）的机制与存储已接线（默认关，零行为变化）。Phase 4 剩余工作 = 用 10 月批次新增的**未消费帧**跑 v12 三窗回测，对门控/阈值参数做终判裁决，一次一候选落默认，产出题材域首份成册 verdict 文档。当前 7-06→9-25 全部帧已被 Phase 1/2/3 + R1/R2/R3/R3b 消费，直接终判违反"最终裁决窗用未消费帧（M3）"纪律，故跑批与 10 月批次合流（hybrid 月度复验、D3 复验同批）。

## 2. 已完成接线层（2026-09-27）

| 件 | 落地 | 测试 |
|---|---|---|
| theme_daily_factors 落库 | `backend/analysis/theme/factors_daily.py`（纯函数装配）+ `backend/data/repositories/theme_daily_factor_repository.py`（upsert/查询）+ `backend/services/theme/daily_factors_service.py`（收盘槽取数、自动 catch-up、Redis 缓存）+ `daily_factors_scheduler.py`（每日 18:30，仅 mongodb 后端，挂 main.py lifespan） | `tests/test_theme_daily_factors.py` 13 用例 |
| 条件层机制接线（默认关） | `backtest_service._theme_gating_inputs`（15:00 帧 marketPhase + 因子分位读取）+ `_theme_execution_signals` 门控块（降可信+打标，tier 不变，可叠加）+ `run_theme_trend` payload 开关 | `tests/test_theme_gating.py` 12 用例 + `test_theme_backtest.py` 29 用例回归全绿 |

- payload 开关（全部默认关）：`sentimentGatingEnabled`、`crowdingPercentileEnabled`、`sentimentGatingPhases`（提案默认 cooling/ice）、`sentimentGatingConfidencePenalty`（提案 10.0）、`crowdingPercentileHighThreshold`（提案 90.0）、`crowdingPercentileConfidencePenalty`（提案 10.0）。
- 提案默认值**不是落默认**：仅显式开关打开时生效，数值待 P4-3 扫描 + P4-5 裁决。
- 调度器 status 经 main.py 状态端点 `themeDailyFactors` 键暴露（fail-visible 观察口）。

## 3. 剩余阶段（10 月批次合流后执行）

- **P4-1 数据积累确认**：调度器自动积累 theme_daily_factors（检查 status 的 lastResult）；10 月复市后确认新帧入库量（≥10 个交易日做初判，量足再终判）。
- **P4-2 三窗划分定版**：已消费窗（7-8 月、9 月）打折标注，10 月为未消费终判窗（M3）；具体边界在跑批方案中按窗口推进 + 极端行情月感知定版。
- **P4-3 参数扫描**（隔离 runner、单 trial、本地 frames、一律 dry-run）：
  1. 情绪门控：phases ∈ {cooling / cooling+ice / cooling+ice+chaos} × penalty ∈ {5, 10, 15, 20}；
  2. 拥挤度分位：threshold ∈ {80, 90, 95} × 替换 vs 并列瞬时口径 × penalty ∈ {5, 10, 15}；
  3. 75 硬层 / 60 起扣形同虚设修正：阈值重定 ∈ {35, 45, 55}（crowdingRisk 量纲 daily max 24.8 / half_hour max 71.08，与阈值差一个数量级——Phase 2 实测）；
  4. **persistenceScoreWeight ∈ {0, 0.03, 0.05, 0.08}**（2026-09-27 persistenceScore 重建立项登记；接线形态 = `ThemeTrendConfig` 新参数默认 0 + v12 合成分新增项，**合成式归一化语义待本阶段定版**；候选原料=trend.py 六维合成分之外的日级 `heatLevelStreak`（连续 N 日 heatLevel ≥ 70，theme_daily_factors.factors 键），与 D3 同面板对照防双持续性重复计分；heat.py 日内粒度 consecutiveHotBuckets 仅实时观察不进扫描）。
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
