# 题材/板块轮动引擎 设计 & 实施计划 对抗性审计

> 日期：2026-08-04 · 审计对象：`2026-08-04-theme-rotation-engine-design.md` + `2026-08-04-theme-rotation-engine-plan.md`
> 审计方法：全部现状主张与计划内代码片段逐条对照源码核验（文件:行号留证），未修改任何业务代码。
> 结论：方案方向正确（后端单一事实源 + 落库 + 前端/theme_trend/theme_support 同源读取），但**计划目前存在 4 个阻塞级问题，实施后功能端到端不可用或口径不一致**；另有 8 个高危与若干中低危问题。建议先修阻塞项再进入实现。

---

## 0. 结论摘要

1. **4 个阻塞（CRITICAL）**：`frame.rotationSummary` 键名 snake_case vs camelCase 端到端断裂；新引擎生命周期词汇与 `theme_trend.LIFECYCLES` 不兼容导致回测路径"同源"失效；前端 `backendRead` 剥掉 `mainLines` + Task 9 删本地计算导致面板主线列表拿不到数据；市场阶段 `cooling` 在实现中不可达。
2. **8 个高危（HIGH）**：跨日基线未实现；Supabase 备份同构被破坏；rotationSummary 覆盖迁移期混排；`rotation_main_line` 读取合并冲突；下游消费者（candidate/battlefield/regime）未审计；flow 持续性因子恒 0；计划内引擎测试 2/3 必失败；主线判定与设计不符。
3. **现状描述有 5 处事实修正**：尤其是"rotationState 恒缺 0%/从未写入"过强、"生命周期只有 cooling 一个标签"不实、"localStorage 轮动历史归属 ThemeRotationEngine.ts"错误、漏掉 `theme_momentum.py` 这第 4 个消费者。
4. **三个待确认方向裁定**：
   - ① 历史窗口 8 槽 + 跨日基线：**方向同意，但 plan 的 `history.py` 没有实现跨日**，只查当日，开盘首批槽 90 分钟整片 null，与"已确认设计选择"自相矛盾。
   - ② 第一版做连板/晋级基础聚合：**同意**，但要修 `breadth_score` 里 `_num(leadStatus)` 比较字符串恒 False 的 bug，并解决 sector/stock 按 timestamp 精确 join 的降级问题。
   - ③ 输出落点写 sector_rows + frame：**同意**（回测同源），但必须补 camelCase 序列化、Supabase schema/映射同步、theme_trend 词汇兼容三步，缺一不可。

---

## 1. 现状描述核验（事实修正）

| # | 设计文档主张 | 核验结果 | 证据 |
|---|---|---|---|
| A1 | 后端 sector rows 的 `rotationState` 恒缺（0%）/ 从未被写入 | **过强，不成立**。有前端透传写入路径 + schema/repo 完整支持。准确说法是"**后端自产的 theme_heat 因子（`factor_to_sector`）不带 rotationState**"；纯后端采集帧里通常缺失（这与你抽查 2026-08-04 缺字段一致），但"0%/从未写入"表述过强 | `builders.ts:877-878` → `importers.py:143-176`；`projection.py:654-694`（数据源 `buildContext.ts:23` + `ThemeHeatFeed.ts:98`）；schema 支持 `models.py:208`、`repository.py:2417/2207`、`supabase_schema.sql:205` |
| A2 | 现状生命周期"只有 cooling 一个标签"（§1 缺陷 4） | **不实**。现状 theme_trend 有 8 态生命周期词表，只是词表不同且只落研究表不落 sector rows | `theme_trend.py:9-18` `LIFECYCLES = {ignition, expansion, mainline, crowded, divergence, cooling, reversal, neutral}`；`_infer_lifecycle` `theme_trend.py:475-505` |
| A3 | ThemeRotationEngine.ts 产出 rotationState | **不准确**。它消费 `factor.rotationState`；真正本地推导在 `ThemeFactorEngine.rotationState()` | `ThemeRotationEngine.ts:16/107`（消费）；`ThemeFactorEngine.ts:110-122`（推导） |
| A4 | 删除 ThemeRotationEngine.ts 的 localStorage 轮动历史（§6.3） | **归属错误**。localStorage 写方是 `rotationService.ts:82-111`（`hot_themes_*` 题材快照），`ThemeRotationEngine.ts` 无 localStorage | `rotationService.ts:82-111` |
| A5 | "三套系统各算各的" | **清单不完整**。至少还有第 4 个消费者 `theme_momentum.py`（读 `frame.hotThemes[].rotationState`），且 `snapshot_derivation/projection.py` 已把前端 `rotationAnalysis` 透传为 frame.rotationSummary | `theme_momentum.py:225-227`、`LIFECYCLE_BOOST/PENALTY` `:38-39`；`projection.py:425/454/475` |
| A6 | theme_support.py 消费"没人写的 rotationState" | **部分准确**。它消费 sector row（或其 `metadata.themeFactor`）的 `rotationState` 并打分；但**不消费 lifecycle/rotationScore**。Phase D 给 theme_support 加 lifecycle/rotationScore 是新功能，不是"对齐现有消费" | `theme_support.py:101-115` |
| A7 | theme_heat 已产出 13 项截面因子并落库 | **符合**。唯一细节：`change` 来自 `metadata.trimmedMeanChange` 回退，不在 factor 顶层 | `theme_heat.py:220-249`；`service.py:95-131`（`factor_to_sector`）；`projection.py:15-32/645-647` |
| A8 | stock_rows 有 boardHeight/highDays/firstZtTime/fengdan | **符合** | `models.py:134/147/149/150`；`providers.py:1144-1153`；`projection.py:578-594` |
| A9 | lifecycle / rotationScore 无人写入 sector rows | **符合**。lifecycle 只落研究表（`models.py:380/424`）；rotationScore 全仓库 0 处引用，纯新字段 | `theme_research_repository.py:79/186`；grep 零命中 |
| A10 | 计划 Task 9 面板读 `frame.rotationSummary`（经 backendRead 直接透出） | **不成立**。`backendRead.ts:102` 显式剥掉 `rotationSummary.mainLines`；且现状面板全部走本地 `themeRuntime/themeFacade/dataLayer` | `backendRead.ts:88-110`；`SectorRotation.vue:323-326`、`SectorPanel.vue:325-327` |

---

## 2. 阻塞级问题（CRITICAL，必须先修）

### C1. `frame.rotationSummary` 键名 snake_case vs camelCase 端到端断裂

- **现象**：plan `service._apply` 写 `frame["rotationSummary"] = dict(result.market.__dict__)`，而 `MarketRotationSummary` 字段全是 snake_case（`market_phase/rotation_speed/main_lines/inflow_themes/outflow_themes/computed_at/algorithm_version/max_board_height/mainline_concentration`）。但消费端全部读 camelCase：
  - 前端 `mapBackendRotationSummary` 读 `backend.marketPhase / mainLines / rotationSpeed / computedAt / algorithmVersion / mainlineConcentration / maxBoardHeight / inflowThemes / outflowThemes`（plan :2134-2220）。
  - theme_trend fallback `_ts_rotation_state` 读 `rotation.get("mainLines")`（`theme_trend.py:356`）。
  - 设计文档自身 §6.2 输出合同就是 camelCase。
  - 现状库里的 rotationSummary 是前端 rotationAnalysis 透传，本就是 camelCase——新行 snake_case 会与旧行格式混排。
- **证据**：plan models :183-196（snake_case 字段）；plan :1646 `frame["rotationSummary"] = dict(result.market.__dict__)`；前端 adapter plan :2134-2220。
- **影响**：功能端到端不可用——前端永远显示默认 phase（`accumulation`）、主线列表空。**必须在 `_apply` 处显式序列化成 camelCase（或给 dataclass 加字段别名），否则整个特性白做。**

### C2. 新引擎生命周期词汇与 `theme_trend.LIFECYCLES` 不兼容，回测"同源"失效

- **现象**：新引擎 lifecycle 词汇 = `ice/emerging/expanding/climax/cooling/neutral`（设计 §5.1）；`theme_trend.LIFECYCLES` = `ignition/expansion/mainline/crowded/divergence/cooling/reversal/neutral`（`theme_trend.py:9-18`）。`ice/emerging/expanding/climax` 不在集合内。
- **后果**：theme_trend 回测/非运行时路径 `replay`/`replay_sequence` 走 `_build_factor` → `_infer_lifecycle`（`theme_trend.py:521/526/475-505`）：`explicit in LIFECYCLES` 不命中 → 落库 lifecycle 被**重新推导**成旧词表（如 `expanding`+`mainline` → 重推导为 `mainline`；`climax` → `crowded`）。计划 Task 8 只改了运行时路径 `_theme_context_frames`（:275-276），**没改 `_build_factor` / `_infer_lifecycle` / `LIFECYCLES`**。
- **影响**：回测路径拿不到引擎同源口径，设计"回测/theme_trend/theme_support/前端全部同源读取"对回测失效。需三选一：引擎直接产出 theme_trend 词表、扩展 `LIFECYCLES`、或让 `_build_factor` 优先透传落库 lifecycle。

### C3. 前端主线列表双重断裂：`backendRead` 剥 mainLines + 删本地计算

- **现象**：
  - `backendRead.ts:102` `const { mainLines: _mainLines, ...plainRotationSummary } = ...` —— 读 frame.rotationSummary 时**显式剥掉 mainLines**（测试断言剥掉后为 `{}`，`backendRead.test.ts:283/301`）。
  - 计划 Task 9 删除 `buildThemeRotationSummary`（本地唯一能产出 mainLines 的路径），面板改读 `frame.rotationSummary`。
- **影响**：即便 C1 的 camelCase 修好，面板的 `mainLines` 依然拿不到（被剥掉）→ 主线列表空、`mainLineCount=0`、`strongCount=0`。计划 Task 9 声称"backendRead 已能拿到"与源码矛盾。**要么停剥 mainLines、要么面板改走 `GET /api/theme-rotation/summary` 的 statuses、要么在 backendRead 补回。**

### C4. 市场阶段 `cooling` 在实现中不可达

- **现象**：设计 §5.3 定义 `marketPhase ∈ {ice, chaos, rising, climax, cooling}`；plan `market_phase_for`（lifecycle.py :747-767）分支只有 climax×2 / ice / rising / chaos×2，**没有任何分支返回 `cooling`**。
- **影响**：前端 `mapMarketPhase('cooling'→'falling')`（plan :2216）永不命中；市场级退潮期无法表达。plan 风险 6 说"cooling 不作为 v1 硬输入"（指输入），但输出侧也没实现，属于设计与实现的契约缺口。需补 cooling 判定（或明确 v1 用主题 cooling 计数兜底）。

---

## 3. 高危问题（HIGH，建议实现前/实现中处理）

### H1. "跨日自然衔接"未实现：`history.py` 只查当日

- plan Task 5 `history.py`（:1440-1448）把 `trading_date` 同时作为 `start_date` 和 `end_date` 传给 repo；`mongo_repository.list_snapshot_sector_rows` 的 `start_date/end_date` 过滤的是 `trading_date` 字段（agent 核验：`_snapshot_row_query`）。因此**只能取到当日槽位**。
- 后果：每交易日开盘前 3 个半小时间槽（约 90 分钟）`min_slots_for_state=3` 不足 → `lifecycle=None + rotation_state=None`（整片 null），与"已确认设计选择 1：跨日自然衔接 / 当日首批槽用前一交易日收盘槽做基线"（plan :15）以及你在消息中确认的决策 ① 均矛盾。要支持跨日基线，`history.py` 必须把日期范围扩展回前一交易日（需要交易日历），否则只能接受首 90 分钟无状态并在文档中如实说明。

### H2. Supabase 备份同构被破坏（违反 AGENTS.md 4.2）

- `supabase_schema.sql:170-209` 的 `snapshot_sector_rows` 只有 `rotation_state` 一列，**没有** `lifecycle/rotation_score/heat_trend/flow_trend/breadth_trend/crowding_trend/mainline_concentration_rank/reasons/factor_breakdown`；`supabase_homomorphic.py:881-922 _sector_to_row` / `:1053 _sector_from_row` 是固定列映射。
- 后果：计划往 Mongo sector_rows 写的新字段在 Supabase 备份轨**静默丢弃**，恢复/读回时字段消失——违反"Supabase 必须与 MongoDB 同构"硬约束，也违反 fail-visible（静默丢字段）。plan Task 10 只更新了文档，未涉及 `supabase_schema.sql` + `_sector_to_row/_sector_from_row`。**必须同批加列与映射。**

### H3. rotationSummary 覆盖的迁移期混排

- `_apply` 无条件覆盖 `frame["rotationSummary"]`（plan :1645-1646）。部署后新帧是引擎 snake_case 值，历史帧仍是前端 camelCase 值；迁移期内 `theme_trend` fallback（读 `mainLines`）对新帧全部失效、对旧帧正常，消费端无法区分来源。建议：给 `rotationSummary` 加 `algorithmVersion` 并在消费端按版本分支；或迁移期写一个统一序列化。

### H4. `rotation_main_line` 读取合并冲突

- 现状前端 mainLines 会额外落成 `entityType="rotation_main_line"` 的 sector rows，读回时 `repository.py:638-647` 用这些行**覆盖** `rotationSummary.mainLines`。引擎把 main_lines 写进 rotationSummary 后，SQLite 读路径仍会用旧前端 `rotation_main_line` 行顶掉引擎结果。plan 未处理这一既有约定（Task 9 停止前端计算后，新行不再产生，但历史行仍在）。需确认 frames API 走的是哪条读路径，并在引擎接入时统一 mainLines 来源。

### H5. 下游消费者未审计（Task 9 只改 2 个面板）

- 消费 `themeFacade.getRotationSummary()/dataLayer.getCurrentRotation()/factor.rotationState` 的还有：`BattlefieldBuilder.ts:222/253/344-345`、`RegimeClassifier.ts:12`、`CandidateAnalysisService.ts:419`、`CandidateDiscoveryService.ts:223`、`CandidateJournalService.ts:639`、`ThemeRiskDashboard.vue:398/417/424`、`ThemeCorrelationPanel.vue:872`。
- 前端 adapter 的 mainLines 把 `rankChange/persistentDays/strength/relatedThemes/topReasons` 全置 0/占位（plan :2143-2162、`placeholderStatus` :2188-2208）——一旦这些消费者拿到 adapter 数据，选股/战场/情绪分类逻辑会回归（字段变 0、direction 恒 inflow）。计划需评估这些消费者对新 rotationSummary 形状的兼容性，否则不能只改 2 个面板。

### H6. flow 持续性因子恒 0 + 计划自相矛盾（fail-visible 违规）

- plan `flow_score` 用 `row.get("positiveInflowStreak")`（plan :1011-1014 传入），但该字段在 sector rows 无生产者（theme_heat / factor_to_sector 都不写）→ 恒 0 → `persistence_score = clamp(0*20) = 0` 混入权重。这是"缺失被当 0 伪造"，违反计划自身"数值工具：缺失保持缺失，禁止用 0 伪装"（plan :62）。
- Task 6 注明"`positiveInflowStreak/negativeInflowStreak/maxBoardHeight 在 sector row 上由 engine 输入前计算（见 Task 6 service）"，但 Task 6 `service.py` 代码**没有**算这两个字段（engine 只在 lifecycle 分支从序列算了 streaks，`flow_score` 没拿到）。应把引擎算好的 streak 传进 `flow_score`，而不是读行字段。

### H7. 计划内引擎测试 2/3 必失败（代码与测试自相矛盾）

- `test_engine_sufficient_history_mainline`（plan :1287-1305）断言 `by_key["BKAG"].rotation_state == "emerging"`：BKAG 在历史槽中不存在 → `enough_history = (0+1) < 3` → `lifecycle=None` → 第二循环 `if ... or status.lifecycle is None: continue` → `rotation_state=None`，**不等于 emerging**。
- `test_engine_rotation_score_present`（plan :1307-1318）断言 `result.market.rotation_speed == 0`：历史槽 BKAI rank=2、当前 rank=1 → `rank_change = 2-1 = 1` → `rotation_speed_score([1]) = clamp(1×8) = 8 ≠ 0`。
- 计划标注"预期 3 passed"（plan :1322）不成立。落地前需先改测试或改代码，二选一对齐。

### H8. 主线判定与设计不符

- 设计 §5.2：mainline = "expanding/climax 且 横向相对强度 z-score 前列（Top3）**且** 资金集中度 Top3"。plan engine（:1091-1099）实际按 `rotation_score` 排序取 Top3，**忽略** z-score 与资金集中度两个显式条件。且 `mainline_concentration(heats, top_n=3)` 在测试里 `[85,45]` 得 1.0，Top3 吃满无区分度。要么按设计补两个条件，要么把设计的判定句改写成实现口径。

### H9. 晋级率因子 `_num(leadStatus)` 对字符串比较恒 False

- plan `breadth_score`（:465）`prev_zt = [s for s in prev_slot_stocks if _num(s.get("leadStatus")) == "涨停" or ...]`：`leadStatus` 是字符串，`_num("涨停")` → `float()` 失败 → `None == "涨停"` 恒 False。晋级率只靠 `change >= 9.5` 兜底，"昨日涨停今日连板占比"实际没算。应改为字符串比较 `str(s.get("leadStatus") or "") == "涨停"`。

---

## 4. 中等问题（MEDIUM）

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| M1 | `min_factors_for_score=3` 是死配置：`combine_scores` 只判 `available` 为空，不判 <3；注释写"可用因子 < min 返回 None"但代码不实现 | plan :93 / :557-565 | 实现或删掉该配置 |
| M2 | `lifecycle_for` 的 `prev_lifecycle` 参数**从未被读取**——"状态机转移连续性"（设计 §4.5）承诺不成立，lifecycle 可单槽任意跳变（如 ice→climax） | plan :688-722 | 补转移约束或删除连续性设计表述 |
| M3 | `market_phase_for` 默认 fallthrough 返回 `chaos`：板高 5-6、轮动慢、无主线的平稳市场被标"混沌" | plan :767 | 给 neutral/unknown 兜底 |
| M4 | `history.py` `limit=window*60 / window*400` 静默截断；sector/stock 按精确 `timestamp` join，两集合时间戳不一致则 `prev_slot_stocks=None` → 晋级率静默降级 | plan :1448/1466 | 按槽位时间范围查询，别按行数 limit；join 容忍时间差 |
| M5 | 运行时读的是**上一落库槽**的 rotationState（N-1 滞后）：live 截面配历史状态，未显式标注 | service.enrich 读库后算 | 在 evidence/reasons 标注时滞 |
| M6 | API 路由 `"rotationSummary": {"$exists": True}` 恒真：`_frame_doc` 总写 rotationSummary（可能 `{}`），"最近一个含 rotationSummary 的 frame"语义失效 | `mongo_repository.py:1176` | 改为过滤 `rotationSummary.marketPhase` 非空 |
| M7 | API 测试在 pytest 下可能 500：`get_runtime_mongodb_database` 带 `PYTEST_CURRENT_TEST` 防护，默认库 `dragon_board_quant` 时抛 RuntimeError | `repository_factory.py:28-29` | 测试前置 mock 或只测 404 分支 |
| M8 | `test_theme_rotation_service.py` 导入 `backend.analysis.theme_rotation.models.SnapshotBundle` 不存在（在 `snapshot_derivation.models`）→ ImportError | plan :1712 | 改导入 |
| M9 | `theme_momentum` 的 `LIFECYCLE_BOOST/PENALTY` 与新词汇交集有限：`emerging/inflow/outflow` 无 boost/penalty，行为可能变化且计划未处理 | `theme_momentum.py:38-39` | 评估是否扩展 |
| M10 | 前端 adapter `placeholderStatus` 造 0 值/假 inflow/outflow 数，违反"缺失保持缺失"；设计说"删除本地计算"但 adapter 仍在造数 | plan :2188-2208 | 改为 `null` 或省略字段 |
| M11 | 计划未处理 `rotationService.ts` 的 localStorage 写入/legacy 适配路径，Task 9 清理不完整 | `rotationService.ts:53-69/82-111` | 明确取舍 |
| M12 | `rotationState` 覆盖语义：`_apply` 无条件写 `row["rotationState"] = status.rotation_state`（含 None），对历史不足的主题会把 sector row 上可能已存在的前端透传值覆成 None | plan :1627 | 仅在非 None 时覆盖，或写 qualityFlags |

---

## 5. 低危 / 建议（LOW）

- L1：大量系数未校准且无理由：`rotation_speed_score ×8`、`zt×6+Δ×10`、`persistence=streak×20`、`concentration=share×300`、`excess=(Δ)×12`、`slope×20`。设计称"无量纲校准"仍是拍脑袋系数，建议至少给一份出处/敏感性验证计划。
- L2：`_theme_key` 回退到 `themeName` 时，同名不同主题（如两个"人工智能"）在跨槽聚合会被合并。
- L3：题材数量少时 中位数+MAD 不稳定（MAD=0 时除以 1e-9 近似）。
- L4：文档 drift：设计 §5.1 五态但实现还有 `neutral`；设计 §2.3 旧 `×18` vs 新 `×8`；设计 §6.2 camelCase vs plan model snake_case（即 C1 的源头）。
- L5：`frame.rotationSummary` 覆盖前端 `rotationAnalysis` 后，`theme_trend` 运行时 fallback 读旧字段；建议迁移期保留 `themeContext.rotationAnalysis` 不动，只覆盖 frame 顶层。

---

## 6. 三个待确认方向的裁定

### ① 历史窗口：8 槽 + 跨日基线 —— 同意方向，但必须实现"跨日"

- 8 槽滚动窗口本身合理（半小时间隔对日内脉冲敏感度合适，隔夜噪声被窗口压制）。
- **但 plan 的 `history.py` 只查当日**（H1），"当日首批槽用前一交易日收盘槽做基线 / 跨日自然衔接"两个承诺都不成立。要么引入交易日历把查询范围扩到前一交易日，要么明确接受"开盘首 90 分钟无状态"并写入设计文档。**当前 plan 处于"设计决策写了、实现没跟上"的状态。**

### ② 连板/晋级：第一版做基础聚合 —— 同意，但要修两个 bug

- 方向对：stock_rows 数据已具备（boardHeight/highDays/firstZtTime/fengdan），theme_trend/theme_support/回测都在等，做成 0-1 版反而返工。
- 必须先修：`_num(leadStatus)` 字符串比较 bug（H9）；sector/stock 按 timestamp 精确 join 的降级问题（M4）；`positiveInflowStreak` 无生产者导致 flow 持续性恒 0（H6）。

### ③ 输出落点：写 sector_rows + frame —— 同意，但需配套三件事

- 同意"rotationState/lifecycle/rotationScore 写 sector_rows、rotationSummary 写 frame、全部同源读取"，避免读口派生的一致性问题。
- 但缺三件事就不可落地：
  1. **camelCase 序列化**（C1）——`_apply` 必须把 `MarketRotationSummary` 序列化成设计 §6.2 的 camelCase 键。
  2. **Supabase schema + 映射同步**（H2）——`supabase_schema.sql` 加列、`_sector_to_row/_sector_from_row` 加映射。
  3. **theme_trend 词汇兼容**（C2）——否则回测路径不认引擎的 lifecycle。

---

## 7. 建议修复顺序（最小改动路径）

1. 修 C1：给 `MarketRotationSummary` 加 camelCase 序列化（或 `_apply` 里显式转换）——一处代码，端到端打通。
2. 修 C3：决定 backendRead 是否停剥 mainLines；或面板改走 `GET /api/theme-rotation/summary`。
3. 修 C2：扩展 `theme_trend.LIFECYCLES` 或在 `_build_factor` 优先透传落库 lifecycle（并补 `_infer_lifecycle` 对新词汇的处理）。
4. 修 H1：`history.py` 引入交易日历扩展日期范围；或文档明示首槽无状态。
5. 修 H2：`supabase_schema.sql` + `supabase_homomorphic.py` 同步加列/映射。
6. 修 H7：把 plan 内 3 个引擎测试改成与代码一致（BKAG、rotation_speed 断言）。
7. 修 H6/H9：flow streak 改从序列算、晋级率改字符串比较。
8. 修 H8：mainline 判定按设计补 z-score + 资金集中度条件。
9. 评估 H5：列出全部 rotationSummary/rotationState 下游消费者，逐一定新形状的兼容性。
10. 按 AGENTS.md §8 同步 `quant-board/docs/architecture.md`、`api-cli.md`、`database-migration-plan.md`，并在设计文档 §1 修正 A1–A4 的事实表述。

---

## 8. 验证清单（修改后必跑）

```powershell
# 后端（quant-board 目录）
.\.venv\Scripts\python.exe -m pytest tests/test_theme_rotation_factors.py tests/test_theme_rotation_lifecycle.py tests/test_theme_rotation_engine.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_theme_rotation_service.py tests/test_theme_rotation_history.py tests/test_theme_rotation_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_theme_trend_engine.py tests/test_theme_support.py -q
# 前端
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
# 真机
# 1) 手动触发一次采集，Mongo 抽查 sector_rows 新字段非空、frame.rotationSummary 键为 camelCase
# 2) Supabase 备份表核对新列有值
# 3) Playwright 打开 SectorRotation 面板：marketPhase 正确映射、主线列表非空、无控制台错误
```

---

## 9. 因子原料在采集/入库链路的齐备性专项核验（重点）

> 应要求对本问题做专项确认：**引擎计算所需因子原料，数据采集与入库链路是否完全齐备**。
> 结论先行：**核心截面因子齐备，但存在 3 个硬缺口 + 2 个降级点 + 1 个因子口径 bug，不能算"完全齐备"。**

### 9.1 链路总览（collector → derive → persist → history）

```
_collect_context (service.py:264-304)
  └─ theme_heat.get_snapshot → factor_to_sector 生成 sectors  ← sectors 唯一来源（:291-295）
       ├─ 可用：market_context.sectors = [factor_to_sector(f) for f in factors]   (:291-295)
       └─ ThemeHeatUnavailable：market_context.sectors = []                        (:300)
_persist_one (service.py:306-369)
  └─ MarketFactBundle.sectors = market_context.sectors                            (:354)
  └─ derived = SnapshotDerivationService().derive(fact)                           (:359)  ← 引擎 enrich 注入点
projection.build_ingest_payload
  ├─ sector_rows：entityKey/entityName/rank + SECTOR_FACTOR_FIELDS 因子          (projection.py:620-648)
  ├─ stock_rows：raw hotlist + themes/mainTheme/themeRole/leadStatus + limit_up 字段 (projection.py:481-617)
  └─ frame.indices = market_data.get("indices")                                   (projection.py:417)
Mongo 落库：_sector_doc 全字段透传（mongo_repository.py:1187-1189）
history.py 读取：snapshot_sector_rows / snapshot_stock_rows，按 timestamp 精确 join
```

### 9.2 逐项核验表

| 引擎输入 | 所需字段 | 采集/入库链路 | 齐备性 |
|---|---|---|---|
| 主题身份 | entityKey/entityName/rank | factor_to_sector(code=themeId,name=themeName) → projection entityKey/entityName/rank | ✅ 齐备（engine `_theme_key` 走 entityKey） |
| 截面强度 | heatScore/momentumScore/breadthScore/fundScore/leadershipScore/correlationScore/crowdingRisk/persistenceScore | theme_heat → factor_to_sector → SECTOR_FACTOR_FIELDS | ✅ 齐备（依赖 theme_heat 可用） |
| 涨停动能 | ztCount/leaderCount | theme_heat → factor_to_sector（**默认 0**） | ⚠️ 有默认 0：theme_heat 无涨停数据时是 0 而非缺失 |
| 资金 | mainNetInflow | theme_heat（资金源） | ⚠️ 资金 provider 失败 → None → flow 整体降级 |
| 量能 | volumeRatio | theme_heat | ⚠️ 缺失 → crowding 量能因子 None（降级） |
| 涨跌幅 | change | factor_to_sector 回退 `metadata.trimmedMeanChange` | ✅ 齐备（trimmedMeanChange） |
| **资金持续性** | **positiveInflowStreak / negativeInflowStreak** | **无任何生产者** | ❌ **恒缺** → flow 持续性因子恒 0（H6） |
| **相对大盘超额** | **frame.indices** | **后端采集链无 indices provider** | ❌ **恒缺** → 超额因子永远 None（见 9.3-①） |
| 股票→题材归集 | stock_rows.**themeIds** | **后端 stock rows 只有 `themes`（字符串列表）+ `mainTheme`（首主题名），无 themeIds** | ❌ **引擎按 themeIds 分组永远为空**，只能靠 mainTheme 精确匹配（见 9.3-③） |
| 连板/晋级 | boardHeight/highDays/firstZtTime/fengdan | limit_up provider → projection | ⚠️ 涨停池可用时齐备；不可用则显式降级（有 qualityFlags） |
| 领涨状态 | leadStatus | `_derive_theme_role_fields`（change≥9.5→"领涨龙头"）+ 原始 hotlist + 涨跌停价派生 | ✅ 有值；但 engine `_num(leadStatus)` 比较 bug（H9） |
| 量能（股票级） | stock_rows.volumeRatio | quotes 富化（projection.py:270-272） | ⚠️ 依赖 quote provider；缺失则降级 |
| 历史槽位 | sector rows / stock rows | MongoDB，同投影字段；sector/stock 同槽 timestamp 相同（都用 `slot.timestamp_ms`） | ✅ join 成立；但 `limit=window*400` 可能截断（M4） |

### 9.3 三个硬缺口（标准后端采集路径下永远拿不到，因子静默缺失）

1. **indices 无生产者**：`collect_market_context` 的 provider 路由（providers.py:1830-1900）只覆盖 stocks/quotes/depth/money_flow/themes/limit_up，**没有 indices provider**；BridgeQuoteProvider 的 market_meta 只有 `totalVolume/totalAmount/upCount/downCount/flatCount`（`_normalize_quote_stats` providers.py:1566-1576）。frame.indices 仅在用前端 startup bundle（`snapshot_context.marketData.indices`）时才有可能。→ engine `_market_change` 返回 None，设计 §4.1"相对大盘超额"（strength 内权重 0.15）**恒缺**。
2. **positiveInflowStreak / negativeInflowStreak 无生产者**：sector rows 无任何环节写这两个字段；`flow_score` 读 `row.positiveInflowStreak` → 恒 0。engine 只在 lifecycle 分支从历史 inflow 序列重算了 streaks（plan :1041），但没传给 `flow_score`。→ 设计 §4.2"资金持续性"（flow 内权重 0.20）**恒为 0**。
3. **stock_rows 无 themeIds，引擎股票归集失效**：全仓库 `themeIds` 只在前端 TS（`src/services/ThemeDataService.ts`、`src/services/dragon/BattlefieldBuilder.ts`），后端 stock rows 只有 `themes`（ThemeMappingProvider 输出字符串列表，providers.py:1688-1692）和 `mainTheme`（投影取首主题名，projection.py:550-559）。engine `for theme_id in (stock.get("themeIds") or [])` **永远空**，只剩 `mainTheme` 精确字符串匹配 `entityName`——无 `_is_same_theme_name` 归一化、无多题材归属（股票只归第 1 个题材）。→ 当题材名与 theme_heat 主题名不一致（如"人工智能概念板块" vs "人工智能"）、或股票非首题材时，连板梯队/龙头集中度/晋级率/量能因子**静默降级**。projection 内部做题材匹配时用了 `_normalize_theme_label`（projection.py:71-76, 484/569），engine 没复用。

### 9.4 降级点（缺失时显式降级，可接受）

- stock_rows.volumeRatio 依赖 quote provider（projection.py:270-272）；缺失 → crowding 量能 None。
- boardHeight/fengdan 依赖涨停池 provider；缺失 → 连板/晋级降级（有 qualityFlags，设计已知）。
- mainNetInflow 依赖资金源；资金 provider 失败 → flow 整体 None（显式降级）。

### 9.5 因子口径 bug（非原料缺失，但结果偏差）

- **晋级率分母错误**：plan `breadth_score` 的 `promotion_score = len(当前主题连板数) / len(prev_slot_stocks 全市场昨日涨停) × 150`（plan :463-468）——分子是主题内，分母是**全市场**昨日涨停（`prev_slot_stocks` 是该槽全部股票，未按主题过滤），比值被市场分母稀释，并非设计 §4.3"昨日涨停今日连板占比"（主题内口径）。

### 9.6 建议

1. **引擎股票归集**改为读 `themes` 列表 + `mainTheme`，并复用 theme_trend 的 `_normalize_theme_name`/`_is_same_theme_name` 归一化匹配；或让 projection 给 stock rows 补 `themeIds` 字段。
2. **补 indices provider**（或让 BridgeQuoteProvider 带 indices），否则删掉/显式降级"相对大盘超额"因子并写进 reasons。
3. **flow 持续性**改为从历史 inflow 序列计算（engine 已算 streaks，传给 `flow_score` 即可），删掉对 `row.positiveInflowStreak` 的依赖。
4. **晋级率分母**改为主题内昨日涨停（按主题过滤 `prev_slot_stocks`）。
5. theme_heat 不可用（`ThemeHeatUnavailable`，service.py:300）时 sectors=[] → 引擎无输入，属"全源无数据"；需在 `frame.metadata.derivation.qualityIssues` 显式标注（计划 `_record_issue` 已覆盖，确认保留）。

---

## 10. 附：审计中确认"成立"的计划前提（避免误伤）

以下计划内"已核对"声明经源码核验**成立**，未列为问题：

- `_persist_one` 注入点在 `derive(fact)` 与 `to_ingest_bundle()` 之间真实存在（`service.py:359-360`）。
- `SnapshotBundle`（frames 为 `list[dict]`、stock_rows 可迭代、`to_ingest_bundle` 存在）；`CollectorRunRequest`/`MarketDataContext`/`QualityResult` 签名与默认值一致。
- `mongo_repository.list_snapshot_*_rows` 签名兼容 plan 的关键字调用；`entity_type="hot_theme"` 是真实约定。
- `_frame_doc` 已预留 `rotationSummary` 字段位（只存 dict）；`_sector_doc` 全字段透传，新字段能落库。
- theme_heat 13 项截面因子全部存在并落库；stock_rows 四字段齐备。
- 设计文档对 theme_trend 辅助函数（`_sector_rows`/`_sector_theme_id`/`_normalize_theme_name`/`_is_same_theme_name`/`_infer_lifecycle`/`_name`/`_num`/`ThemeTrendConfig`）的行号引用准确（`theme_trend.py:213/339/190/198/475/186/162/131`）。
