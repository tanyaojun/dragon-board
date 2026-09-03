# heatLevel 落库与热度口径统一迁移设计（theme-heat-level-v1）

> 日期：2026-09-03 · 状态：**已批准（2026-09-03，brainstorming 流程，设计 6 节经用户逐节确认）；2026-09-03 双 subagent 对抗性评审（设计 + 计划）后有条件修订：补 B9/B10、修 §4.2 残留歧义结论、§5 风险补 3 项**
> 触发：`2026-09-02-kpl-hotness-formula-migration.md`（theme-market-v2 迁移）残留 5 项 TODO 的处理。
> 关联文档：`quant-board/docs/theme-rotation/2026-09-02-kpl-hotness-formula-migration.md`、
> `quant-board/docs/theme-rotation/2026-08-06-theme-momentum-redesign.md`。
> 归属：QuantBoard 题材模块方案 + Dragon Board 前端消费适配，文档目录沿用 `quant-board/docs/theme-rotation/`。

## 1. 核心目标（5 句话以内）

1. heatLevel（0-100 rank 百分位）成为题材热度**相对分**的单一事实源：heat 引擎生成 → sector row 落库 → 投影读出 → momentum/trend/rotation/backtest/前端统一消费。
2. heatScore（KPL 人气总和，绝对值）只保留给"人气量级"场景（DragonBreathPanel 3000/1500、原始展示）。
3. 落库行携带口径标记（复用 `metadata.factorVersion`），消费端按行口径决定 heatScore 回退，替代 `>100` 启发式，消除 M1 边界窗口。
4. 前端约 12 处按 0-100 设计的阈值消费点从绝对值 heatScore 切换到 heatLevel，分级语义恢复；缺失值传播不伪装 0。
5. momentum 量纲常量参数化并按 heatLevel 百分位语义标注，数值沿用，上线后按真实数据核定。

## 2. 已确认决策（brainstorming 2026-09-03 逐项确认）

| # | 决策点 | 选择 |
| --- | --- | --- |
| D1 | 数值 heatLevel 落库字段名 | **复用 `heatLevel` 字段落数值**（与 2026-09-02 文档原意一致）。代价已知：与前端浏览器路径历史字符串档位标签（"热门/活跃/温/冷/冰"）撞名，前端 TS 类型临时放宽 `string \| number \| null`，混合窗口由 `_num_or_none`（字符串解析失败 → 缺失）+ 口径标记兜底。 |
| D2 | TODO 4 前端处理范围 | **系统性切换**：后端 heat API factor 输出 heatLevel，前端全部 0-100 消费点（约 12 处，超出原文档点名的 4 个文件）统一切换；DataLayer 缺失传播不伪装 0；含 playwright 真实浏览器验收。 |
| D3 | momentum 重校准方式 | 常量参数化 + 语义注释改为 heatLevel 百分位差值，**数值沿用（15/20/15）**，首轮真实数据观察后再核定；不拍新魔法数。`THEME_MOMENTUM_VERSION` 从 `theme-momentum-v1` bump 到 `v2`（消费对象从 heatScore 序列换为 heatLevel 序列，输出量纲有变；已核实该常量仅 momentum.py 自身返回值引用、无测试/下游断言，bump 无破坏）。 |
| D4 | golden 版本 | trend golden bump **v14**（heatLevel 纳入白名单比对）；heat golden bump **v3**（factor 输出加 heatLevel，heat 公式不变，`factorVersion` 保持 `theme-market-v2`）。 |
| D5 | 实施分批 | 阶段 A 后端（可独立上线）→ 阶段 B 前端 → 阶段 C 文档收口；A 上线后前端未切也不变差。 |

## 3. 事实核查（设计依据，2026-09-03 源码核实）

1. **`heat_level` 持久层字段现状**：`backend/data/supabase_schema.sql:188`（varchar(40)）、`backend/data/models/models.py:191`（String(40)）已存在，但现存语义是**前端浏览器快照路径写入的字符串档位标签**（`src/services/snapshot/builders.ts:842`、`src/services/sectorAnalyzer.ts:85`），不是 0-100 数值。collector 生产路径（`factor_to_sector`）从不写它。当前主库 MongoDB schemaless 透传（`mongo_repository.py:1268-1270`），新落数值零 schema 成本。
2. **collector 落库行已携带口径标记**：`snapshot_collector/service.py:102` 把 heat 快照 `factorVersion`（`theme-market-v2`）写进 sector row `metadata.factorVersion`；`SECTOR_FACTOR_FIELDS`（`snapshot_derivation/projection.py:15-32`）白名单含 metadata。4 个消费点（trend/momentum/rotation/backtest）尚未读它，仍用 `>100` 启发式（`trend.py:445`、`momentum.py:115,276`、`rotation/factors.py:64`、`backtest_service.py:224`）。
3. **前端失真面约 12 处**：`stockThemeMeta.ts:34-48`（热度档位）、`ThemeStockProjector.ts:25-27,51`（角色 70/45/20）、`factors.ts:117`（clamp 输入是绝对值）、`StockHotnessCalculator.ts:163`（`themeHeat*0.55`）、`BattlefieldBuilder.ts:175,254,355`（55/75/60）、`ReviewComposer.ts:98`（≥60）、`ThemeAlertEngine.ts:101`（75/70）、`ThemeCorrelationPanel.vue:885`（≥65）、`ThemeRiskDashboard.vue:426`（≥75）、`ThemeFacade.ts:289-290`（图标 80/60/40）、`dragon/helpers.ts:270`（×0.24）。当前所有热门题材被误判"热门/core/高危"，分级完全失效。根因：`/api/themes/heat` 只输出绝对值 heatScore，无相对分。前端 `factorVersion` 只透传展示，无版本分支逻辑。
4. **momentum 常量全部消费 heatScore 序列差值**：`/15.0`（`momentum.py:139,144`）、`drawdown/20.0`（:167）、`THEME_JUMP_HEAT_DELTA=15`（:19,:173）输入均为 `build_theme_strength_series` 收集的 heatScore 序列（:95-125），序列当前过滤 `heat > 100.0` → 新口径下热门题材全部缺席，动量序列基本为空。
5. **trend 现有 heatLevel 内存附加**：`trend.py:450-462` `_attach_heat_levels`（rank1 → 100，`round((1-(rank-1)/N)*100, 1)`），仅 themeContext 路径调用（:292），不落库；`_ts_heat_level`（:433-447）已优先读 factor `heatLevel` key，key 显式 None 不回退（审计 M3）。
6. **golden 现状**：`tests/fixtures/theme_trend_ts_golden_v13.json` 无 heatLevel；校验是字段白名单比对（`tests/test_theme_trend.py:32-62`），heatLevel 即使存在也不会被比对。fixture 路径硬编码在测试内，无代码版本常量。heat golden `theme_heat_market_golden_v2.json` 锁定 `factorVersion: theme-market-v2`。
7. **研究集合无 heatLevel/口径字段**：`mongo_research_repository.py:751-775` `_factor_doc` 有 heatScore（缺失转 0.0）、rank、qualityFlags，无 heatLevel、无 factorVersion；`backtest_service._persisted_heat_level` 消费的是研究帧 factor。
8. **hotThemes 读侧投影白名单**：`mongo_repository.py:243` 与 SQL `snapshot_repository.py:392-415` 含 `heatScore`/`metadata`，不含 `heatLevel`。
9. **fail-visible 基线**：KPL 缺失时 heatScore=None、rankEligible=false、flags `kpl_hotness_unavailable`，不伪装 0（2026-09-02 文档）；`DataLayer.ts:299` `themeHeat ?? 0` 与 `snapshot/builders.ts:807` `Number(item.themeHeat) || 0` 是现存伪装 0 点，本次一并修正。

## 4. 设计

### 4.1 数据流

```text
heat.py 引擎（新增：factor 输出 heatLevel，rank 百分位，共享纯函数生成）
  → GET /api/themes/heat 快照（前端相对分唯一来源；AI: heatScore=2000, heatLevel=96.3；POWER: null, null）
  → factor_to_sector 落库 sector row.heatLevel（数值或 None）+ metadata.factorVersion（已有）
  → hotThemes 投影白名单加 heatLevel（Mongo/SQL 读侧）
  → momentum 序列 / trend._build_factor / rotation.strength_score / backtest 统一按消费规则吃 heatLevel
  → 前端数据链 ThemeHeatApiFactor.heatLevel → themeScore/themeHeat → 12 处阈值恢复语义；缺失传播
```

### 4.2 消费统一规则（替代 `>100` 启发式）

对任一题材因子/落库行：

1. `heatLevel` key 存在 → 数值直接用（0-100）；显式 `None` = 诚实缺失，**不回退**。
2. key 不存在（旧数据）→ 看 `metadata.factorVersion`：`theme-market-v1` 或无标记且 `heatScore <= 100` → heatScore 可当相对分回退；`theme-market-v2` → **不回退**，缺失。
3. `heatScore > 100` → 无论标记一律缺失（最后兜底）。

M1 边界窗口（旧 0-100 残留 + 新绝对值 ≤100 的跨帧歧义）按行口径直接消除，不再依赖跨帧 baseline 启发式；heat.py 现有 `kpl_hotness_baseline_reset`（`heat.py:205,245-246`）保留为快照层环比保护，与行级口径标记互补。

**残留歧义（显式接受，含边界修正）**：无 `metadata.factorVersion` 标记且 `heatScore <= 100` 的行无法区分 v1 归一分还是 v2 小题材绝对值——本设计将其按 v1 语义回退，与现有 `>100` 启发式行为一致，不劣化现状。不为此回写历史行。

无标记行的两个实际来源与收敛方式（2026-09 评审 H2 修正：原"随 collector 行累积自然消亡"结论对快照 context 行**不成立**）：

- **持久层历史行**（Mongo/SQL 已落库的旧 sector row）：确实只随 collector 新行按 `snapshot_id` 累积自然消亡，回放窗口外不可见。
- **快照 context 行（每帧重建，不会自然消亡）**：浏览器正式快照构建时，`buildContext.ts` 每帧从 `dataLayer.getHotThemes()` 与 `themeHeatFeed.getSnapshot()` 重新拼装 `hotThemes` / `themeHeatFactors` context 行——只要前端还在产快照，无标记行就会**每帧重新生成**，不会随时间消亡。因此设计新增 **B9**：`buildContext.ts` 统一给两类 context 行写入 `metadata.factorVersion`（快照有 `factorVersion` 用之，缺失按 `theme-market-v2` 兜底标记）；hotThemes 行的 `heatLevel` 字符串档位标签（"热门/活跃/温/冷/冰"）与数值语义撞名（D1），context 行改落 `heatLevelScore` 数值（无值不写 key），字符串标签不再进入落库 sector row。B9 上线后，新产出的快照 context 行全部带标记，无标记来源仅剩存量持久层历史行，残留歧义按第 2 条规则处理。

### 4.3 后端改动清单

| # | 改动 | 位置 |
| --- | --- | --- |
| B1 | heatLevel 生成抽共享纯函数 `attach_heat_levels(factors)`（公式同 `trend.py:450-462`）；heat 快照输出调用；trend 改 import 消重复 | 新 `backend/analysis/theme/heat_level.py`；`heat.py`、`trend.py` |
| B2 | `factor_to_sector` 落库 `heatLevel`（透传 factor 值，数值或 None，key 缺失时不伪造） | `snapshot_collector/service.py:95-131` |
| B3 | hotThemes 读侧投影白名单加 `"heatLevel"` | `mongo_repository.py:243` 一带（提取为模块级常量 `HOT_THEME_FRAME_FIELDS`）。SQL 读侧 `local_sector_to_bundle_dict`（`snapshot_repository.py:1288`）已含 `heatLevel` 且 None 剥离，无需改；`snapshot_repository.py:392-415` 是写侧列清单，随 B8 的 `_sector_model` 覆盖 |
| B4 | 消费点按 4.2 规则改造：`trend._ts_heat_level` 回退分支、`trend._build_factor`（透传 heatLevel + metadata 进 factor）、`momentum.build_theme_strength_series`（吃 heatLevel）、`rotation/factors.strength_score`、`backtest_service._persisted_heat_level` | `trend.py`、`momentum.py`、`rotation/factors.py`、`backtest_service.py` |
| B5 | 研究集合 `_factor_doc` 加 `heatLevel` + `factorVersion`（Mongo schemaless 零成本；历史研究帧按缺失回退） | `mongo_research_repository.py:751-775`、对应 SQL/备份映射 |
| B6 | momentum 参数化：`THEME_RELATIVE_MOMENTUM_SCALE=15.0`（替换 :139,:144 字面量 `/15.0`）、`THEME_DRAWDOWN_SCALE=20.0`（:167）、`THEME_JUMP_HEAT_DELTA=15` 保留；docstring 语义改为 heatLevel 百分位差值；数值沿用 | `momentum.py:14-22,139,144,167` |
| B7 | stock row `themeHeat` 落库语义切换（绝对值 → heatLevel 相对分或缺失，统一走 `resolve_heat_level(sector)` 派生）。**不加行级口径标记**（2026-09 计划评审确认偏离原设想）：stock row 无通用 metadata dict（仅 `volumeRatioMeta`），新增标记需扩 normalizer 字段白名单且值语义已单一（相对分或缺失），口径歧义在 sector 行 `metadata.factorVersion` 层消解即可 | `projection.py:583-592` 派生块 + `SECTOR_FACTOR_FIELDS` 白名单放行 `heatLevel` |
| B8 | SQL/Supabase 备份 `_sector_model` / homomorphic 写侧：数值 `heatLevel` 写 varchar(40) 列前统一转 `str`（`_heat_level_text` helper，`str(float(v))` 产出 `'96.3'` 形态）；读侧 `local_sector_to_bundle_dict` 原样回字符串，消费端 `resolve_heat_level` 规则 1 可解析；字符串档位标签（历史浏览器行）原样透传不解析 | `snapshot_repository.py:1498`、`supabase_homomorphic.py:911`（读侧 `:1099` 与列名清单 `:190` 不动） |
| B9 | 快照 context 行口径标记 + 数值化（评审 H2 新增）：`buildContext.ts` 给 `hotThemes` / `themeHeatFactors` 两类 context 行统一写 `metadata.factorVersion`（快照 `factorVersion` 缺失时按 `theme-market-v2` 兜底）；hotThemes 行 `heatLevel` 改落数值（来源 `heatLevelScore`，无值不写 key），消除字符串档位标签进入落库 sector row 的路径。`metadata` 经浏览器构建链 `buildSectorMetadata` 透传已核实可达 | `src/services/snapshot/buildContext.ts` |
| B10 | 回测执行信号 `themeHeat` 透传字段口径切换（评审 M4 新增）：`backtest_service._theme_execution_signals`（:1249-1251,:1286）与 `_confluence_execution_signals`（:1322-1325）的 `raw_theme_heat = factor.get("heatScore")` 改走 `resolve_heat_level(factor)`（缺失回退 stock/signal 行 themeHeat 的行为保留），透传值从绝对值变为 0-100 相对分或 0.0 | `backtest_service.py:1249-1251,1286,1322-1325` |

### 4.4 前端改动清单（Dragon Board src/）

数据链（缺失传播，fail-visible）：

- `ThemeHeatApiFactor` 类型加 `heatLevel: number | null`（`src/services/theme/types.ts`）。
- `ThemeStockProjector.ts:87` `themeScore ← factor.heatLevel`（不再用绝对值 heatScore；绝对值仍在 factor 上供展示）。
- `ThemeRuntimeCoordinator.ts:128` `themeHeat: main?.themeScore || 0` → 显式缺失传播（去 `|| 0`）；`deriveThemeHeatLevel` 输入即 heatLevel。
- `DataLayer.ts:299` `themeHeat ?? 0` → 显式缺失判断，`themeHeat` 缺失保持 undefined。
- `snapshot/builders.ts:842` 浏览器 sector row 构建点只透传数值 heatLevel（非数值不写）；`:807` stock row `themeHeat` 伪装 0 修正；`:838-841` strength/heatScore 绝对值保留。
- `snapshot/buildContext.ts`（B9）：`hotThemes` / `themeHeatFactors` 两类 context 行统一写 `metadata.factorVersion`（缺失按 `theme-market-v2` 兜底）；hotThemes 行 `heatLevel` 从字符串档位标签改落数值（来源 `heatLevelScore`，无值不写 key）。已核实 `buildSectorMetadata`（`builders.ts:179-190`）透传 `payload.metadata`，标记可达落库 sector row。
- `SnapshotSectorRow.heatLevel` 类型过渡期放宽 `string | number | null`（`src/services/snapshot/types.ts:192`）。

12 处阈值消费点切换（输入换 heatLevel 后原 0-100 阈值语义恢复，多数只改取值字段）：

- `stockThemeMeta.ts`（档位）、`ThemeStockProjector.ts`（角色）、`ThemeFacade.ts:289`（图标）、`ThemeAlertEngine.ts:101`、`ThemeCorrelationPanel.vue:885`、`ThemeRiskDashboard.vue:426`、`ReviewComposer.ts:98`、`BattlefieldBuilder.ts:175,254,341,355`、`dragon/helpers.ts:270`。
- `StockHotnessCalculator.ts:162-163`（themeSupportScore）：`themeHeat <= 0` 无信号判断改显式 null/undefined 判断（rank 末位 heatLevel>0 是真实冷，不是无信号）；**>100 旧口径绝对值按缺失处理**（0-100 区间守卫，评审 M5：防历史绝对值行经 `themeHeat*0.55` 恒饱和到 100）。
- `BattlefieldBuilder.ts:427`：`stock.themeHeat || 0` → `stock.themeHeat ?? 0`（null 与 0 分流，加权合成项语义）。
- `factors.ts:117`：clamp 输入换 heatLevel（`Math.min(100)` 保留无害；`|| 0` → `?? 0` 防 NaN）。

不动：`DragonBreathPanel.vue:877,1126-1127` 3000/1500（绝对值口径正确）；heatScore 原始展示点（null 显示 "--"，2026-09-02 文档既有要求）。

### 4.5 golden 与测试策略（TDD）

- **trend golden v14**：新建 fixture（v13 输入不变，kplHots 保持），`expected.factors[].heatLevel` 纳入 `factor_fields` 白名单并写期望值；`tests/test_theme_trend.py` 路径 + caseId 更新。
- **heat golden v3**：新建 fixture（v2 不可变），factor 期望加 heatLevel；`factorVersion` 保持 `theme-market-v2`。
- **TDD 顺序**（先失败测试后实现）：
  1. heat.py factor 输出 heatLevel（golden v3 锁定）；
  2. collector contract 扩展：factor_to_sector 落库 heatLevel（`test_theme_heat_collector_contract.py`）+ **`SECTOR_FACTOR_FIELDS` 白名单放行断言**（评审 H1：白名单在派生层剥字段，落库透传与白名单放行必须同批改，否则端到端断言永远落空）；
  3. 消费规则测试：v1 行回退 heatScore / v2 行不回退 / heatLevel 显式 None 不回退（扩展 `test_theme_trend_heat_level.py`、`test_theme_momentum_series.py`、`test_theme_rotation_factors.py`、`test_theme_backtest.py`）;
  4. momentum 序列吃 heatLevel 后动量序列恢复（热门题材不再全部缺席）；
  5. 前端单测扩展：ThemeHeatFeed / ThemeRuntimeCoordinator / ThemeStockProjector / StockHotnessCalculator / **buildContext（B9 口径标记 + heatLevel 数值化）**。
- **验证命令**：
  - 后端：`cd quant-board && ./.venv/Scripts/python.exe -m pytest`（全量，含 2026-09-02 文档列出的 8 个 theme 测试文件；`./` 前缀在 PowerShell 与 bash 下均可执行）。
  - 前端：`pnpm test` + `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
  - 浏览器：playwright-cli 验收题材热度分级、DragonBreathPanel、ThemeMomentumPanel 渲染与控制台无错（阶段 B 交付前）。

### 4.6 分阶段实施

- **阶段 A（后端，可独立上线）**：B1-B8 + golden v14/v3 + 后端 pytest 全绿。A 上线后前端未切换也维持现状（不变差）。
- **阶段 B（前端）**：4.4 全部 + 单测 + vue-tsc + playwright 验收。
- **阶段 C（文档收口）**：新增实施记录文档（本目录）；同步 `quant-board/docs/mongodb-migration-plan.md`、`architecture.md`、`api-cli.md`（落库字段/API 输出变更）；2026-09-02 文档残留 TODO 清单标注完成去向。

## 5. 风险与边界

1. **heatLevel 对题材总数 N 敏感**（评审 M2）：rank 百分位分母是 `ranked_total`（rank>0 的 factor 数），N 随当日有热度题材数波动，N 小则百分位步长大（N=10 时每名 10 分），跨日 heatLevel 差值含"N 变化"噪声；momentum 阈值语义漂移 → 已参数化，上线后观察核定（D3）。首日验证加一项：对比当日 ranked_total 与 heatLevel 分布。
2. **`heatLevel` 字段双语义过渡期**：历史浏览器字符串行 vs 新数值行 → `_num_or_none` 挡字符串 + 口径标记兜底；前端类型过渡期放宽。
3. **stock row themeHeat 落库语义变更**：历史行绝对值 vs 新行相对分；无标记旧行按"缺失"原则回放，不跨口径比値。
4. **前端 hotness 分布变化**：themeHeat 从"绝对值 clamp 100"变"真实相对分"，StockHotnessCalculator 输出分布变化 → 上线首日人工验证（AGENTS §11）；themeSupportScore 已加 >100 缺失守卫与 null 分流（§4.4），历史绝对值行不会恒饱和。
5. **momentum 跳变与排名跳变同源放大**（评审 M1）：`THEME_JUMP_HEAT_DELTA=15` 原按 0-100 归一分差值校准，切到 rank 百分位后，同源数据（rank 变化）会同时驱动 jump 信号与 rank_jump 信号，两条信号可能同帧重复触发。数值沿用不重校（D3），上线首日观察 jump 与 rank_jump 的重叠率，重叠异常升高时再核该常量。
6. **confluence 75 分门槛实际放宽**（评审 M3）：`_persisted_heat_level` 修正后，热度分量从"绝对值 clamp 100 恒满分"变为真实 0-100 相对分，`hotlist_theme_confluence` 的 `confluence_score >= 75` 触发率会**下降**（这是纠偏，不是回归），执行信号数量与回测结论会随之变化。上线首日对比切换前后同数据集的 confluence 触发率，确认变化方向与幅度符合预期。
7. **不做的事**：不新增 MongoDB 集合/API；不引入独立进程；不改 heat 公式与 `FACTOR_VERSION`；不做 shadow/live 双跑（阶段 A 直接生产小范围观察）；不回滚历史落库行。

## 6. 必查清单（AGENTS.md §11）

- [x] 核心目标 5 句话以内（§1）。
- [x] 无质量门禁/阻断：heatLevel 缺失只降级 + 标记，原始 heatScore 照落库；只有全源无数据才采集失败。
- [x] 无 shadow/live 分阶段验证；阶段 A 即生产小范围观察，首日人工验证 MongoDB 实际落库 heatLevel 值。
- [x] 无独立守护进程/计划任务。
- [x] 无新增 MongoDB 集合/API；仅扩展现有快照/研究集合字段与 `/api/themes/heat` 输出。
- [x] 条件判断语义书面化（4.2 三条规则），code review 逐行比对"存在/缺失/None"三分支。
- [x] 无新环境变量。
- [x] 首日人工验证计划：核对 `snapshot_sector_rows` 新行 heatLevel 为数值且与 rank 百分位一致、`/api/themes/heat` factor 带 heatLevel、前端分级不再全判"热门"。
- [x] 首日人工验证补充（2026-09 评审 M1/M2/M3/H2）：
  - 快照 context 行核验：新落库 hot_theme 行 `metadata.factorVersion` 存在（B9 生效），`heatLevel` 全为数值或缺失（无字符串档位标签混入）；
  - ranked_total 与 heatLevel 分布对照（风险 1）；
  - momentum jump 信号与 rank_jump 信号重叠率（风险 5）；
  - confluence 75 分触发率切换前后对比（风险 6）。
