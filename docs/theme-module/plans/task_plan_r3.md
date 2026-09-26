# Phase R3 实施计划：轮动补涨策略变体对照回测（SG1/SG2/SG3）

- 日期：2026-09-26
- 前置裁决（第四轮用户裁决，已回写设计文档 cdbb9f21）：①轮动信号与回测**消费引擎 mainline 口径**（`rotationSummary.mainLines`）；②regime 重构为引擎权威口径（`rotation/regime.py` 的 `top1_streaks` + `rotation_state_context`，已完成）；③随后进入 R3。
- 设计依据：`docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md` §5.3/§5.4/§6.1 Phase R3。
- 纪律：TDD（RED→GREEN）；一次一候选落默认（本轮只做对照回测，不改任何默认参数与既有三策略行为）；fail-visible（缺失打标不伪造）；扫描资源纪律（非交易时段、单进程串行、不做参数扫描）。

## 接口事实（2026-09-26 代码 + MongoDB 双证，勿凭记忆修改）

1. **回测主链**：`backtest_service.run_theme_trend(payload)`（backtest_service.py:717）→ `strategy_name` 白名单 `THEME_STRATEGY_NAMES`（core/backtest/strategy.py:96-118，新增 key 自动进 `SUPPORTED_STRATEGY_NAMES`）→ `ThemeTrendPythonEngine().replay_sequence(frames)` → `_theme_execution_signals(frames, factors, exposures, strategy_name)`（backtest_service.py:1243，tier 决策：crowding≥75→C_CROWDED；rotationState∈{mainline,inflow}+暴露→A_MAIN；inflow→B_IGNITION；outflow→D_EXIT_RISK）→ `TradeSimulator().run(frames, execution_signals, trade_config)`（core/backtest/execution.py）。
2. **进场规则**：execution.py:730 `strategy_key == "theme_rotation"` 分支（tier∈{A_MAIN,B_IGNITION} 且 regime≠weak）。新变体复用同一规则——**变体差异全部在 tier 生成层（候选池构造），进场规则统一**。
3. **引擎 mainline**：half_hour 15:00 帧 `rotationSummary.mainLines`（结构 `[{themeId, themeName, rotationScore, rotationState, rankChange}]`）。实测 2026-07-06~09-24 共 53 帧，**非空仅 8 天**——mainLines 空 = 引擎判定"当日无主线"，是有语义的状态而非数据缺失；mainLines 非空名单即主线确认的候选题材。
4. **market_phase**：同 half_hour 15:00 帧 `rotationSummary.marketPhase`，53 帧非空 39（daily 帧恒 unknown，勿用）。
5. **题材级 rotationState**：仅 half_hour sector rows（124,054 行覆盖 72%），daily 全缺。SG2 取每日 15:00 槽（该日缺 15:00 槽则该日 None 打标，不做日内回退——第一版口径，保持日频确定性）。
6. **daily 题材行**（dragonboard_live，7-06~09-24）：13,433 行；rank/change 100%；mainNetInflow 70.8%（7-21~7-29 整段缺，3916 行）；heatLevel 25.6%。SG1 的 change 序列、SG3 的 mainNetInflow 序列由此构建（R1 runner `load_close_slot_series` 同口径：`type=daily` 必带）。
7. **RRG 基础**：`analysis/theme/daily_series.py` `virtual_index(changes)`（累乘虚拟指数）已有；基准 = 全题材等权日 change 均值合成基准指数。
8. **regime context**（本轮 Task A 产出）：`rotation/regime.py` `top1_streaks({date: theme|None})` + `rotation_state_context(state, phase, streak)`（headStable = streak ≥ 3 默认）。用于**分层评估**，第一版不进 hybrid 门控条件。
9. **trade 默认参数**：新变体走 `DEFAULT_TRADE_CONFIG`（`trade_defaults_for_strategy` 不加专属默认），保证与 baseline 公平对照。
10. **frames bundle 结构**（mongo_repository.py:292-322 实证）：`run_theme_trend` 用默认 `projection="full"`，bundle 含 `entities` = 该帧全部 sector rows 原始 dict（rotationState/rank/tradingDate/slotTime 齐全）与 `hotThemes` 视图——SG2 序列与 mainLines 直接从 frames 提取，无需二次查询。
11. **SG 输出合同**（三信号统一）：`{date: bool | None}`——True=当日触发；False=可判定但未触发；**None=不可判定（数据缺失/序列断链），不伪造 False**。

## 非目标

- 不改既有三策略（theme_rotation / leader_theme_confirmation / hotlist_theme_confluence）的任何行为与默认参数；
- 不接线 MainlineScore 判定链（第四轮裁决降级，§5.5）；
- 不做参数扫描（hysteresis k/exit_rank、SG 阈值敏感性另批）；
- 不动 RankTrend golden 链、快照写入链与前端；
- SG 算子只做研究信号，不自动写回任何默认值。

## Task 1：SG 三信号算子（TDD）

**文件**：`backend/analysis/theme/rotation/signals.py`（新建）；测试 `quant-board/tests/test_theme_rotation_signals.py`（新建，已知答案校验）。

1. `rrg_quadrants(changes, benchmark_changes) -> list[str | None]`：
   - RS 线 = 题材虚拟指数（virtual_index）/ 基准虚拟指数；RS 动量 = RS 日差分；
   - 象限：leading（RS≥1 且动量≥0）/ weakening（RS≥1 且动量<0）/ lagging（RS<1 且动量<0）/ improving（RS<1 且动量≥0）；
   - 首日无动量 → None；输入长度为 0 或不一致 → 全 None（不抛异常，返回长度=min 长度，多余丢弃并声明）。
2. `sg1_rrg_migration_flags(quadrants_by_day) -> {date: bool | None}`：
   - 触发 =（lagging→improving）或（weakening→leading）的迁移日；
   - None 日断链（与 top1_streaks 同口径）；断链后首个已知日 → None（前一日象限不可知）。
3. `sg2_rotation_switch_flags(state_by_day) -> {date: bool | None}`：
   - 触发 =（outflow→inflow）或（neutral→inflow）的首日切换；None 日断链。
4. `sg3_inflow_turn_positive_flags(inflow_by_day, *, positive_min_days=1) -> {date: bool | None}`：
   - 触发 = 连续为负（≤0）后首次满足"连续 positive_min_days 天 >0"的首日；None 日断链（缺失段内不可判定）。
5. 语义统一：日期按字典序累计；空输入返回 {}。
6. 测试用例每函数 ≥6 个：已知答案迁移序列、None 断链、首日不可判定、空输入、边界（RS 恰=1、inflow 恰>0）、参数化 positive_min_days=2。

**验收**：`./.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_signals.py -q` 全绿；theme 域回归无破坏。

## Task 2：回测变体接线（TDD）

**文件**：`backend/core/backtest/strategy.py`（白名单 +2）、`backend/services/backtest_service.py`（SG 预计算 + `_theme_execution_signals` 分支）、`backend/core/backtest/execution.py:730`（进场分支扩三 key）、测试 `quant-board/tests/test_theme_backtest.py`（追加合同用例）。

1. `strategy.py` `THEME_STRATEGY_DEFINITIONS` 新增：
   - `theme_rotation_chase`（轮动补涨策略）：SG1/SG2/SG3 任一触发驱动进场，补涨语义不给 A_MAIN；
   - `theme_state_hybrid`（状态门控混合策略）：当日引擎 mainLines 非空且题材∈名单 → 主线确认规则；mainLines 空（引擎判定无主线日）→ SG 驱动补涨规则。
2. `backtest_service.run_theme_trend`：strategy_name ∈ {chase, hybrid} 时调用新私有方法 `_theme_sg_inputs(dataset_id, frames)`：
   - 从 frames 提取每日 15:00 槽题材 rotationState（SG2 序列）与 mainLines/marketPhase（仅 15:00 帧有）；
   - 查 daily sector rows（`type="daily"` 硬过滤，复用 R1 口径）构建 change/mainNetInflow 日序列与全题材等权基准；
   - 调 Task 1 三算子 → `sg_flags[theme][date] = {"sg1": …, "sg2": …, "sg3": …}`、`mainline_names[date] = list[str] | None`；
   - theme_rotation 不触发该预计算（零开销，既有行为不变）。
3. `_theme_execution_signals` 增加可选参数（默认 None，既有三策略行为不变）：
   - chase 分支 tier 决策：crowding≥75→C_CROWDED、rotationState=="outflow"→D_EXIT_RISK 沿用；SG 任一 True 且 rotationState 非 outflow → B_IGNITION（补涨语义不给 A_MAIN）；否则 N_NEUTRAL；
   - hybrid 分支：当日 mainLines 非空时，题材∈名单走既有 theme_rotation 规则（可给 A_MAIN），不在名单 N_NEUTRAL；mainLines 为空（无主线日）→ chase 规则；mainLines 该日缺失记录（None）→ 按"无主线日"处理并打 `missing_mainlines` 标记；
   - SG 触发来源写 themeReasons（如 `sg1:rrg_migration`），保证回测 trades 可归因。
4. `execution.py:730` 进场分支：`strategy_key == "theme_rotation"` → `strategy_key in {"theme_rotation", "theme_rotation_chase", "theme_state_hybrid"}`（进场规则统一，注释声明变体差异在候选池层）。
5. 测试：①既有三策略在无 SG 参数时输出与重构前一致（回归保护）；②chase：构造 SG 触发帧断言 tier=B_IGNITION、未触发 N_NEUTRAL、outflow D_EXIT_RISK 优先；③hybrid：mainLines 日走主线规则、空日走 SG 规则；④新 strategy_name 经 run_theme_trend 全链跑通（小合成 frames）。

**验收**：pytest 新用例 + `tests/test_theme_backtest.py` 全绿；全量 pytest 无回归。

## Task 3：R3 对照回测 runner + 真实数据运行

**文件**：`backend/operations/diagnose_theme_r3_variants.py`（新建，只读研究 runner，范式同 diagnose_tier_discrimination.py）；产物 `data/reports/theme-r3-variants.json`（gitignore，不提交）。

1. 三变体同一回测窗（2026-07-06~09-24，dataset=dragonboard_live，snapshot_type=half_hour，同一 random_seed）逐个调 `run_theme_trend`（串行、单进程；每次调用间 gc.collect()；run 记录落库属回测主链正常产物，run_id 记入报告）；
2. 汇总输出：三变体 totalReturn/maxDrawdown/winRate/tradeCount/profitFactor/ equityCurve 关键点对照表；
3. 分层评估：trades 按 entryTradingDate 的市场状态分组（marketPhase × rotationState × headStable，regime context 用 `rotation/regime.py` 新口径 + Top1 streak 由 daily rank Top10 序列计算），输出各组 n/winRate/avgNetReturn；
4. 附加诊断：三 SG 触发日分布（按月）、hybrid 门控日分布（主线确认日 vs 补涨日）、mainLines 空值率复核；
5. fail-visible：某变体 0 笔交易/某状态组 n<3 时如实输出 insufficient，不输出 0 收益伪装。

**验收**：runner 真实数据跑通，三变体 metrics + 分层表落 JSON；交易时段纪律核对（2026-09-26 为周六）。

## Task 4：findings 报告 + 文档同步 + 记忆

1. `docs/theme-module/2026-09-26-phase-r3-findings.md`：三变体对照结论（核心问题："主线不明环境下轮动补涨是否占优"）、SG 触发分布、分层评估、样本量声明（54 天探索性）、局限；
2. 设计文档 §6.1 R3 段标注完成状态与结论摘要；
3. 更新持久记忆 `themetrend-upgrade-plan.md`；
4. 提交分组：Task 1 信号算子 / Task 2 变体接线 / Task 3 runner / Task 4 报告，各自独立 commit 可回退。

## 风险与回退

- **mainLines 仅 8 天非空** → hybrid 的主线确认臂交易机会可能极少（预期内：这正是"主线不明"实证）；若主线臂 0 交易，如实报告并降级结论强度；
- **SG3 的 mainNetInflow 7 月下旬整段缺** → 7 月下旬 SG3 恒 None（不影响 SG1/SG2 触发）；
- **回测三次 frames 装载内存**：half_hour 全窗 frames 估算数百 MB 级，串行 + gc 可控；若 RSS 异常立即中止（吸取 2026-09-23 事故教训）；
- **新变体落库 run 记录**：带 strategy_name 可识别，不影响既有 run；回退 = git revert 对应提交（SG 算子为纯新增文件，无既有行为耦合）。
