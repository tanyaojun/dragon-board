# 题材/板块轮动引擎 实施代码评审

> 日期：2026-08-04 · 评审对象：提交区间 `9f43686..b011f0b`（10 个 Task / 10 个提交，45 文件，+2561 / -328）
> 评审基线：对照 `2026-08-04-theme-rotation-engine-audit.md`（对抗性审计）与 plan，逐项核验修复与残留。
> 验证命令：见 §5，全部通过。

---

## 1. 结论摘要

**实现质量显著高于计划初稿，基本达到可交付状态。** 上一轮对抗性审计的 **4 个阻塞 + 8 个高危 + 12 个中危全部处理**，其中绝大部分是真修（源码级），少数为显式降级/文档化；且文档同步、测试更新完整。**当前无阻塞项。**

仍需人工确认的残留风险（均非阻塞）：
- **R1（中）**：`rotationSummary.inflowThemes/outflowThemes` 只含 themeId，前端面板"流入/流出题材"列表显示的是 `BKAI` 这类代码而非中文名。
- **R2（中）**：后端采集链仍无 `indices` 生产者，"相对大盘超额"因子在标准后端路径下恒缺（已显式降级并打 reasons，但该因子实际是死的）。
- **R3（中）**：`market_phase_for` 的 `cooling` 判定排在 `rising` 之前——强势主线市场若同时有 ≥35% 题材在 cooling，会被标成 `cooling` 而非 `rising`。
- **R4（中）**：H5 下游消费者（`BattlefieldBuilder`/`CandidateAnalysis*`）未逐个回归核对新 rotationSummary 形状（undefined 字段替代原 0/占位值）。
- **R5（低-中）**：面板拉取后端轮动硬编码 `type: 'half_hour'`，quarter_hour 会话展示的是 half_hour 轮动。
- **R6（低）**：引擎按 `themes` 列表 + `mainTheme` 归一化归集股票的修复（审计 9.3-③）**没有用真实中文题材名 + 后缀差异的用例覆盖**（测试里 `themes` 用的是 `BKAI` 这类 ID）。

---

## 2. 审计发现 → 实施核验对照表

### 2.1 阻塞级（上一轮 CRITICAL）

| 编号 | 问题 | 实施核验 | 判定 |
|---|---|---|---|
| C1 | `rotationSummary` snake_case vs camelCase 端到端断裂 | `MarketRotationSummary.to_camel_dict()`（models.py:68-82）输出 camelCase；`service._apply` 用它写 frame（service.py:104） | ✅ 修复 |
| C2 | lifecycle 词汇与 `theme_trend.LIFECYCLES` 不兼容，回测"同源"失效 | `LIFECYCLES` 扩展 `ice/emerging/expanding/climax/inflow/outflow`（theme_trend.py:15-25）；`_ts_persisted_rotation` 优先消费落库值 + `rotationState_local_fallback` 标记（theme_trend.py:382-412） | ✅ 修复 |
| C3 | 前端 mainLines 双重断裂（backendRead 剥字段 + 删本地计算） | `backendRead.ts` 不再剥 `mainLines`（保留 rotationSummary 或 null）；测试断言更新（backendRead.test.ts:301）；面板 `loadBackendRotation()` → `setBackendRotationSummary`（SectorRotation.vue:338-346） | ✅ 修复 |
| C4 | 市场阶段 `cooling` 不可达 | `market_phase_for` 新增 cooling 分支（lifecycle.py:140-147）；engine 计算 `cooling_theme_ratio`/`negative_inflow_theme_ratio`（engine.py:389-396） | ✅ 修复 |

### 2.2 高危级（上一轮 HIGH）

| 编号 | 问题 | 实施核验 | 判定 |
|---|---|---|---|
| H1 | 跨日基线未实现 | `history.previous_trading_day` 用交易日历（`trading_calendar.is_trading_day`）+ 桥不可用时工作日启发回退（history.py:16-31/57）；engine evidence 输出 `crossDayBaseline` | ✅ 修复 |
| H2 | Supabase 备份同构被破坏 | `supabase_schema.sql` 加 9 列；`supabase_homomorphic.py` 的 `REQUIRED_TABLE_COLUMNS`/`_sector_to_row`/`_sector_from_row` 同步双向映射（reasons/factor_breakdown 为 jsonb） | ✅ 修复 |
| H3 | rotationSummary 覆盖迁移期混排 | 前端 adapter 用 `backend.algorithmVersion` 门禁，无版本则返回 null（backendRotationAdapter.ts:16）；service 只覆盖 frame 顶层、不动 `themeContext.rotationAnalysis`（service.py:103-104）；`repository.py` 引擎帧不被旧 `rotation_main_line` 行顶掉（repository.py:645-650） | ✅ 修复 |
| H4 | `rotation_main_line` 读取合并冲突 | 见上 H3 第三点（SQLite 读路径 guard） | ✅ 修复 |
| H5 | 下游消费者未审计（adapter 造 0 值） | adapter `statusFromBackend` 全部 `undefined` 而非 0（backendRotationAdapter.ts:72-79）；`RegimeClassifier.ts` 用 `?? 0` 加固；`rotationService.ts` 只保存后端提供的字段（M11） | ⚠️ 大部分修复，残留 R4 |
| H6 | flow 持续性因子恒 0 + 计划自相矛盾 | engine 从历史 inflow 序列算 streaks 并传给 `flow_score`（engine.py:202/215）；不再读 `row.positiveInflowStreak` | ✅ 修复 |
| H7 | 计划内引擎测试 2/3 必失败 | 测试改为自洽（history 含 BKAG；`rotation_speed == 8`），已通过 | ✅ 修复 |
| H8 | 主线判定与设计不符 | engine 用 heat z-score 排名 + 资金集中度排名双 Top-N（`min_mainline_z_rank`/`min_mainline_concentration_rank`，engine.py:320-356） | ✅ 修复 |
| H9 | 晋级率 `_num(leadStatus)` 恒 False + 分母为全市场 | 字符串比较 `str(leadStatus) == "涨停"`（factors.py:187）；`_filter_theme_stocks` 按主题过滤上一槽股票（engine.py:87-96/217） | ✅ 修复 |

### 2.3 中危级（上一轮 MEDIUM）

| 编号 | 判定 |
|---|---|
| M1 `min_factors_for_score` 死配置 | ✅ `combine_scores(scores, weights, min_factors)` 生效（factors.py:297-309，engine.py:244） |
| M2 `prev_lifecycle` 未用（状态机无连续性） | ✅ 转移钳制：非相邻跳变钳到相邻中间态（lifecycle.py:69-94） |
| M3 `market_phase_for` fallthrough 全 chaos | ✅ 新增 `neutral` 分支（speed<40 且无主线，lifecycle.py:161-166） |
| M4 history limit 截断 + timestamp join | ✅ `limit=None` 按日期范围取数；stock rows 按最近槽 `slot_time` 关联（history.py:64-88） |
| M5 运行时 N-1 滞后未标注 | ✅ `evidence.historyLagSlots: 1`（engine.py:439） |
| M6 API `$exists` 恒真 | ✅ 改为 `rotationSummary.algorithmVersion: {$exists: True}`（routes.py:26-27） |
| M7 API 测试在 pytest 下 500 | ✅ 测试用 monkeypatch 替换 `get_runtime_mongodb_database`（test_theme_rotation_api.py:44-46） |
| M8 `SnapshotBundle` 导入错误 | ✅ 改为 `from backend.snapshot_derivation.models import SnapshotBundle`（test_theme_rotation_service.py:6） |
| M9 theme_momentum 词汇交集有限 | ⚠️ `LIFECYCLE_BOOST/PENALTY` 扩展，但新增的 `expanding/climax` 是 lifecycle 词、不是 rotationState 词，永不匹配（见 R7） |
| M10 adapter 造 0 值/假数 | ✅ `undefined` 保持缺失（backendRotationAdapter.ts:72-79） |
| M11 rotationService localStorage 未处理 | ✅ 只保存后端提供字段，不写占位值（rotationService.ts:87-99） |
| M12 把已有 rotationState 覆成 None | ✅ 仅非 None 时覆盖；否则打 `rotation_history_insufficient`（service.py:76-82） |

### 2.4 因子原料缺口（审计 §9）

| 缺口 | 实施核验 | 判定 |
|---|---|---|
| §9.3-① indices 无生产者 → 超额因子恒缺 | 未补 indices provider；engine `_market_change` 对非 dict 返回 None，excess 显式缺失并进 reasons | ⚠️ 降级（残留 R2） |
| §9.3-② positiveInflowStreak 无生产者 | engine 从历史序列算 streaks 传给 flow_score | ✅ 修复 |
| §9.3-③ stock rows 无 themeIds → 归集失效 | engine `_stock_theme_labels` 读 `themes` 列表 + `mainTheme`，`_normalize_theme_label` 归一化匹配（engine.py:66-96/166-168） | ✅ 修复 |
| §9.5 晋级率分母 | `_filter_theme_stocks` 按主题过滤 | ✅ 修复 |

---

## 3. 实施中发现的新问题 / 残留（按严重度）

### R1（中）inflow/outflow 题材列表只显示 themeId
- 现象：engine `inflow_themes`/`outflow_themes` 是 `[s.theme_id]`（engine.py:429-432）；前端 adapter 用 `{themeId: id, themeName: id}` 建状态（backendRotationAdapter.ts:23-27）→ 面板"流入/流出"列表显示 `BKAI` 而非 `人工智能`。
- 影响：UI 辨识度下降；主线列表正常（mainLines 带 themeName）。
- 建议：engine 输出 `[{themeId, themeName}]` 对象，或 adapter/面板用 sector rows/主题映射补中文名。

### R2（中）"相对大盘超额"因子在后端采集路径实际是死的
- 现象：后端采集链仍无 indices provider（`collect_market_context` 路由无 indices，`_normalize_quote_stats` 只含 totalVolume/upCount 等）；`_market_change` 对非 dict 返回 None。
- 影响：`strength` 组里 excess 子因子（设计权重 0.15）恒缺失 → 权重被重归一化，可解释性降低。
- 建议：要么后续补 indices provider，要么从设计因子表删掉该因子并明确降级，避免"设计了但永远不算"。

### R3（中）`cooling` 判定先于 `rising`，可能误标强势主线市场
- 现象：`market_phase_for` 顺序 climax → **cooling** → ice → rising（lifecycle.py:132-167）。当 cooling_theme_ratio≥0.35 时直接返回 cooling，即便 board=8、主线≥1。
- 影响：轮动市中"新旧题材交替、35% 题材降温"同时存在强势主线时，市场被标 `cooling`（前端映射 `falling`）——与设计"退潮=亏钱效应+晋级率降"的口径有偏差。
- 建议：把 cooling 判定放到 rising 之后，或冷却条件叠加"无稳定主线"约束；阈值 0.35/0.50 属拍脑袋，建议上线后敏感性复核。

### R4（中）H5 下游消费者未逐个回归
- 现象：`BattlefieldBuilder.ts`（:222/253/344-345）、`CandidateAnalysisService.ts:419`、`CandidateDiscoveryService.ts:223`、`ThemeRiskDashboard.vue` 等读 `rotationSummary.mainLines`/`factor.rotationState`，本次只显式加固了 `RegimeClassifier.ts`。
- 影响：adapter 把 `rankChange/persistentDays/strengthScore` 等置 `undefined`（原本地引擎给的是计算值），这些消费方的分支可能拿 `undefined` 走默认路径。当前测试未覆盖它们。
- 建议：对这些消费方做一次"无 rotationSummary / 字段 undefined"形态的对照检查，必要时补单测。

### R5（低-中）面板硬编码 `type: 'half_hour'`
- 现象：`SectorRotation.vue:339`、`SectorPanel.vue:344` `listSnapshotFrames({ type: 'half_hour', ... })`。
- 影响：quarter_hour 会话下面板展示的是 half_hour 轮动。
- 建议：跟随当前 snapshot_type（从 snapshot 上下文取）或默认口径明确标注。

### R6（低）名称归一化归集修复缺少真实语义用例
- 现象：`test_engine_sufficient_history_mainline` 的 `_stock("600001", 8, "涨停", ["BKAI"])`，`themes` 是主题 ID；而真实 stock rows 的 `themes` 是中文名（可能带"概念/板块"后缀）。
- 影响：`_stock_theme_labels`/`_normalize_theme_label` 的归一化路径没有被"人工智能概念板块 vs 人工智能"这类真实差异用例覆盖。
- 建议：补一个主题名为"人工智能概念板块"、sector entityName 为"人工智能"的用例，锁定归一化行为。

### R7（低）theme_momentum 新增词表里 `expanding/climax` 是死条目
- 现象：`LIFECYCLE_BOOST` 加 `expanding`、`LIFECYCLE_PENALTY` 加 `climax`（theme_momentum.py:38-40），但 theme_momentum 读的是 `rotationState`（值域 mainline/inflow/outflow/cooling/emerging/neutral），`expanding/climax` 永不出现。`emerging`/`outflow` 有效。
- 影响：无害但无效；语义上 engine 的"expanding 且非主线"对应 rotationState=`inflow`，若想让 theme_momentum 对发酵题材加分，应加 `inflow` 而非 `expanding`。

### R8（低）engine.compute 在事件循环内同步执行
- 现象：`enrich_bundle` 把 `history.load` 放 `to_thread`，但 `engine.compute` 同步跑在事件循环（service.py:55-62）。
- 影响：8 槽 × 约 60 题材的纯计算通常 <50ms，风险低；但主题数或历史变大后可能阻塞 loop。
- 建议：compute 也包一层 `asyncio.to_thread`（引擎无 I/O，纯函数线程安全）。

### R9（低）`quickRotation` 恒空
- 现象：adapter `quickRotation: []`（backendRotationAdapter.ts:30）；旧本地引擎会填"快速轮动"列表。
- 影响：任何仍消费 `quickRotation` 的 UI 显示为空。后端引擎无对应概念，建议文档标注已废弃该维度。

---

## 4. 建议修复优先级

1. **R1**（前端名称显示）——改 engine 输出 `[{themeId, themeName}]` 或 adapter 补名，改动小收益直接。
2. **R3**（cooling/rising 顺序）——调 `market_phase_for` 分支顺序 + 补单测。
3. **R4**（H5 消费方回归）——人工逐一对 BattlefieldBuilder/CandidateAnalysis 检查 undefined 形态。
4. **R6**（归一化用例）——补真实中文名差异用例，锁死 §9.3-③ 修复。
5. **R2**（indices/超额因子）——删因子或补 provider，避免"设计了但永远不算"。
6. **R5/R7/R8/R9**——低优先，可并入后续。

---

## 5. 验证记录

| 命令 | 结果 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_*.py tests/test_theme_rotation_collector_integration.py -q` | **29 passed** |
| `.venv/Scripts/python.exe -m pytest tests/test_theme_trend_engine.py tests/test_theme_support.py tests/test_theme_momentum.py tests/test_snapshot_collector_service.py -q` | **108 passed** |
| `.venv/Scripts/python.exe -m pytest tests/test_theme_rotation_api.py -q` | **2 passed** |
| `pnpm exec vitest run backendRotationAdapter / ThemeV3Engines / backendRead` | **18 passed（3 files）** |
| `pnpm exec vue-tsc --noEmit -p tsconfig.app.json` | **0 错误** |

未执行（需真实环境）：真机采集一次槽位后在 MongoDB 抽查 `snapshot_sector_rows` 新字段非空、frame `rotationSummary` 为 camelCase、Supabase 备份列有值、Playwright 打开 SectorRotation 面板。

---

## 6. 值得肯定的点

- **审计闭环做得很扎实**：上一轮 4 CRITICAL + 8 HIGH + 12 MEDIUM 逐条有源码级修复或显式降级，且都写了对应测试；设计文档新增 §11 实施偏差记录，文档（architecture/api-cli/database-migration-plan）同步更新。
- **fail-visible 贯穿**：sector_rows 空输入显式标注（service.py:40-43）、历史不足打 `rotation_history_insufficient`（service.py:79-82）、异常不阻断入库（service.py:64-65）、缺失保持 undefined（adapter）。
- **跨日基线 + 交易日历容错**：`history.py` 桥不可用时工作日启发回退，节假日多查无害，思路正确。
- **Supabase 同构**补列 + 双向映射 + `REQUIRED_TABLE_COLUMNS` 联动，符合 AGENTS.md 4.2。

---

## 7. 结论

**可合入，无阻塞项。** 建议合入前或合入后尽快处理 R1/R3/R4；R6 补一个测试锁定归一化；R2/R5/R7/R8/R9 列入后续迭代。

## 8. 修复记录（2026-08-04 第二轮）

以下问题已修复并提交（含两项缓存建议）：

| 编号 | 修复 |
| --- | --- |
| R1 | engine `inflowThemes/outflowThemes` 输出 `[{themeId, themeName}]`；adapter 兼容旧字符串并修正 `summary.topInflow/topOutflow` 取中文名 |
| R2 | v1 明确“板块超额”恒降级（无 indices provider），设计文档 §4.1/§12 标注；reasons 已带 `excess` 缺失标记 |
| R3 | `market_phase_for` cooling 判定移至 rising 之后 + 新增“强势主线不被误标退潮”用例 |
| R4 | 逐一代查 BattlefieldBuilder/Candidate*/ThemeRiskDashboard/ThemeCorrelationPanel：undefined 字段仅影响展示/跳过分支，无数值计算路径；未新增测试（代码核验足够） |
| R5 | 面板轮动数据源类型改用 `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`，并显示轮动数据 `slotTime` |
| R6 | 新增 `人工智能概念板块` vs `人工智能` 归一化用例锁定 §9.3-③ 修复 |
| R7 | `theme_momentum` 词表按 rotationState 值域修正（`inflow` 替代 `expanding`，移除 `climax`），测试同步 |
| R8 | `engine.compute` 经 `asyncio.to_thread` 移出事件循环 |
| R9 | `quickRotation` 维度废弃，adapter 空数组 + 设计文档标注 |
| 缓存① | `GET /api/theme-rotation/summary` 接入 Redis read-through（TTL 60s 可配），注册 dataset/date 索引，ingest 联动失效 |
| 缓存② | 前端面板展示轮动数据 `slotTime`/computedAt，最新槽无结果回退旧槽时打“旧槽位”标记 |
