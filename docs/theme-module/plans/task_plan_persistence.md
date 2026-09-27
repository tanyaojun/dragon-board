# persistenceScore 持续性算子重建实施计划

- 日期：2026-09-27（立项会话）；状态：**口径已裁决（Q1=c / Q2=c / Q3=一并修单独提交），实施中**
- 上游：`2026-09-27-factor-marginal-findings.md` §1（Critical 待裁决项）；设计 `2026-09-27-themetrend-factor-convergence-design.md` §2.1；总设计 `2026-09-26-themetrend-v12-upgrade-design.md`
- 纪律：TDD（RED→GREEN→REFACTOR）；一次一候选；fail-visible（缺测打标不伪造 0）；测试只跑专项

## 1. 口径裁决记录（2026-09-27 用户确认）

**考证结论**（git + 源码）：
- TS theme-market-v1 原语义（`ThemeFactorEngine.persistenceScore` + `ThemeRotationEngine.persistentDaysFor`）：原料=轮动 `mainLines.persistentDays`，方向相同/保持主线 → +1，掉出归 0；公式 `min(92, 18+log1p(d)×28+min(5,d)×6)`。
- Python `consecutiveHotBuckets × 20 封顶 100` 无 TS 对应物（d9c2f309 新设计），自出生即双重缺陷（写 `metadata.consecutiveHotBuckets` / 读顶层 / 无递增），全库恒 0。
- 架构事实：previous_factor 供给 = `heat_service._last_success`（同进程相邻两次真实刷新，300s TTL 桶内缓存命中不重算；collector 独立进程，重启即断链归零）→ heat.py 链路天然只产**日内/进程内**粒度持续性。

**裁决**：
1. **Q1=c 日级分位阈值连续性**：连续 N 日 `heatLevel ≥ 阈值`（默认 70，参数化）为主口径，走 `factor_series.py` 同族纯函数 + `theme_daily_factors` 落库（momentumV2 同型接线）。与 D3（截面 Top 成员连续）不同型，可同面板对照防双持续性重复计分。
2. **Q2=c 历史即时可算**：日级算子原料=已落库 daily sector rows 的 heatLevel（e51219be 起落库），54 天历史窗口立即可算，无需等积累、不逐槽重放。
3. **Q3=heat.py 一并修、单独提交**：路径错位（metadata vs 顶层）+ 递增/重置逻辑补齐，日内槽位粒度作为保留机制（实时观察用），公式不变（min(count×20,100)，注释注明 5 桶饱和、研究口径让位日级）。

## 2. 提交拆分（三个提交，各自可回退）

### 提交 A：heat.py 管道修复（bugfix，单独提交）

- 文件：`quant-board/backend/analysis/theme/heat.py`
  - 读侧改读 `previous_factor["metadata"]["consecutiveHotBuckets"]`（与写侧对齐，非数值容错归 0）；
  - 递增条件：`previous_factor.heatLevel ≥ HOT_LEVEL_THRESHOLD`（模块级常量 70.0，与日级算子默认阈值同源）→ prev+1，否则归 0；
  - prev 整体缺失 → 0（复用 `persistence_history_insufficient` flag）；
  - prev 存在但 heatLevel 非数值（None/降级帧）→ 0 + 新 flag `persistence_previous_unobserved`（fail-visible：缺测显式，不伪装）；
  - 公式不变；docstring 注明日内粒度语义与日级算子分工。
- 测试（`tests/test_theme_heat_engine.py` 就近，先 RED 后 GREEN）：
  1. metadata 路径 + 递增：prev heatLevel 85 + metadata count 2 → count 3、score 60；
  2. 归零：prev heatLevel 50 → count 0、score 0；
  3. 封顶：prev metadata count 6 + heatLevel 90 → min(7×20,100)=100；
  4. prev 缺失 → score 0 + `persistence_history_insufficient`；
  5. prev heatLevel None → score 0 + `persistence_previous_unobserved`。
- **回测 PnL 不变合同测试**（同提交）：同一批 frames 输入 trend 引擎，persistenceScore=0 vs 100 → tier/confidence/signal/进出场断言相同（仅 themeContribution 可差）。防"修 bug 改变既有结论"质疑——历史 Mongo 数据恒 0，回放结论本就不含持续性效应。
- 验证：`pytest tests/test_theme_heat_engine.py tests/test_theme_heat_collector_contract.py tests/test_theme_heat_service.py` + trend/backtest 回归（`tests/test_theme_backtest.py tests/test_theme_trend_heat_level.py` 等 trend 相关全套）。

### 提交 B：日级持续性算子入 theme_daily_factors（新语义）

- `backend/analysis/theme/factor_series.py`：新增 `level_streak(values_by_day, *, threshold=70.0)`——≥threshold 连续计数；<threshold 归 0；None/缺日断链（下个观测日重计，首个达标=1）；与 `top_membership_streak`/`positive_streak` 并列同文档string 风格。
- `backend/analysis/theme/factors_daily.py`：新增 `build_heat_level_streak_values(heat_level_by_theme, target_dates, threshold)` + `merge_heat_level_streak_into_rows`（momentumV2 同型：并入 `factors.heatLevelStreak`；缺行主题新建行、拥挤字段 None + 标记，不伪造）。
- `backend/services/theme/daily_factors_service.py`：`_load_daily_sector_rows` 投影加 `heatLevel`；提取 per-theme `{date: heatLevel|None}`；auto 模式 complete 条件加 `dates_with_factor_key(..., "factors.heatLevelStreak")`（自愈：旧日期自动补算）；调用 build+merge。
- 测试：
  - `tests/test_theme_factor_series.py`：level_streak known-answer（三连达标 1/2/3、低于阈值归 0、缺日 None 断链重计、边界 =threshold 算达标）；
  - `tests/test_theme_daily_factors.py`：build+merge 端到端（序列→streak 落 factors 键；v2-only 式新建行标记）。
- 验证：`pytest tests/test_theme_factor_series.py tests/test_theme_daily_factors.py` + `tests/test_theme_momentum_daily_series.py` 回归。

### 提交 C：边际研究重跑 + 文档收敛

- `backend/operations/diagnose_theme_factor_marginal.py`：`load_stored_factors` 增补 `heatLevelStreak`（factors 键）；CANDIDATES 增加 `heatLevelStreak`（与 d3Streak 同面板；persistenceScore candidate 保留——历史恒 0 复证"出生即死"，形成修复前后对照）。
- 重跑（Mongo 27017 需运行；非交易时段）：`.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_factor_marginal` → `data/reports/theme-factor-marginal.json`。
- 文档同批更新：
  - `2026-09-27-factor-marginal-findings.md` §1 改写为"已重建+新结论"，§6 汇合清单更新；
  - `2026-09-26-themetrend-v12-upgrade-design.md` §10 进度日志追加；
  - `plans/task_plan_phase4.md` 终判清单登记 persistenceScoreWeight 候选（默认 0 接线形态 + 合成式归一化语义待 Phase 4 定版）。

## 3. 不变量与影响面

- 不动 heat 原料层其他口径（heatLevel/momentum/crowding 等，主循环已有裁决）；
- 提交 A 后 persistenceScore 从恒 0 变真值（日内粒度）→ sector rows 落库值、themeSupportScore、trend exposure（×0.03）变化；**tier/confidence/进出场/回测 PnL 不变**（合同测试钉住；历史数据恒 0，既有回测结论无需回溯修订）；
- v12 六维合成分（trend.py `_build_signal` score）**不含** persistenceScore——接线归 Phase 4 终判（ThemeTrendConfig 新参数 `persistenceScoreWeight` 默认 0，golden 不变）；
- 不做历史回填（Q2=c：日级算子历史即时可算；heat.py 日内粒度从修复日起积累）。

## 4. 验证命令（quant-board 目录，PowerShell；只跑专项不跑全量）

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_theme_heat_engine.py tests/test_theme_heat_collector_contract.py tests/test_theme_heat_service.py
.\.venv\Scripts\python.exe -m pytest tests/test_theme_factor_series.py tests/test_theme_daily_factors.py tests/test_theme_momentum_daily_series.py
.\.venv\Scripts\python.exe -m pytest tests/test_theme_backtest.py tests/test_theme_trend_heat_level.py
.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_factor_marginal
```

## 5. 风险

- 提交 A 改变 heat 引擎输出 → 既有 golden/快照测试若 fixture 带 `metadata.consecutiveHotBuckets` 期望值需同步（已查：现有 fixture 的 previous_factors 均无该键，行为不变，回归可证）；
- Mongo 27017 偶尔停（需管理员 net start）——提交 C 重跑前确认；
- 双持续性因子（heatLevelStreak vs D3）相关性需在重跑报告中同面板观测，防重复计分。
