# heatLevel 落库迁移实施记录（2026-09-03）

- 设计/计划：`2026-09-03-heatlevel-persistence-migration-design.md` / `2026-09-03-heatlevel-persistence-migration-plan.md`（双 subagent 对抗性评审修订版）
- 执行方式：executing-plans 内联逐任务 TDD（RED 签名比对 → 实现 → GREEN → 定向回归 → 每任务一 commit）
- 前置口径：`05dbe86`（题材热度口径切换为 KPL 人气总和，`heatScore` = 人气绝对值）；本迁移在此之上落库 `heatLevel` = 0-100 rank 百分位相对分

## 统一消费规则（design §4.2 三分支）

唯一实现：`backend/analysis/theme/heat_level.py` 的 `resolve_heat_level`。

1. heatLevel key 存在 → 数值直接用（含 SQL varchar 数字串回退）；
2. key 缺失 → `heat_caliber_of` 判口径（`""`/`v1` 且 `heatScore <= 100` 回退旧 0-100 口径；`v2` 返回 None）；
3. `heatScore > 100` 恒缺失（v2 绝对值不伪装相对分）；输出 clamp [0,100]。

缺失热度显式 None/null，不伪装 0 度"冰"（前端同步遵守：`null` 不参与阈值比较，展示降级 `--`）。

## 阶段 A 改动清单（后端，Task 1-12）

| Commit | Task | 内容 |
| --- | --- | --- |
| `ae64e35` | 1 | 新增 `heat_level.py` 共享模块（rank 百分位生成 + §4.2 口径三分支解释 + 口径常量） |
| `e51219b` | 2 | heat 引擎 factor 输出 `heatLevel`（rank 百分位）+ heat golden v3 |
| `c6cfc87` | 3 | trend 接入 `_ts_heat_level` 委托 + `_build_factor` 透传 + `ThemeFactorFrame` 两字段（heatLevel/heatFactorVersion） |
| `57af939` | 4 | trend golden bump v14（heatLevel 纳入白名单比对；v13 不可变） |
| `bc7a775` | 5 | collector `factor_to_sector` 落库 heatLevel（数值/显式 None/缺 key 三态）+ 派生白名单 `SECTOR_FACTOR_FIELDS` 放行（H1 同批改） |
| `7389e47` | 6 | Mongo hotThemes 读侧投影白名单 `HOT_THEME_FRAME_FIELDS` 放行 heatLevel |
| `b8e8da8` | 7 | momentum 序列/角色判定消费 heatLevel + 量纲常量参数化（D3，`THEME_MOMENTUM_VERSION` bump） |
| `2703e2d` | 8 | rotation 强度因子/引擎热度读点统一走 `resolve_heat_level` |
| `3b7b6e5` | 9 | backtest 执行信号热度分量/themeHeat 透传按 heatLevel 口径消费（B10，显式 None 判断） |
| `2d58126` | 10 | 研究集合 `_factor_doc` 落 heatLevel + 行级热度口径标记 |
| `a02e787` | 11 | 派生投影透传 sector heatLevel + stock row `themeHeat` 改相对分口径（B7，resolve 派生） |
| `eff22ac` | 12 | SQL/Supabase `heat_level` varchar 数值写入统一转文本 |

Task 13 为阶段 A 收口验证（专项 pytest 全绿），无独立代码 commit。

## 阶段 B 改动清单（前端，Task 14-16）

| Commit | Task | 内容 |
| --- | --- | --- |
| `e217a7a` | 14 | 数据链切换：`ThemeFactorSnapshot.heatLevel: number \| null`、`ThemeHeatApiFactor.heatLevel` 必填、`ThemeStockExposure.themeScore`、`ThemePanelSummary.heatLevelScore` 新增；feed `toRuntimeFactor` 透传；projector 角色/原因/曝光分切换；coordinator `themeHeat/themeLevel` 派生；DataLayer `updateStockThemes` 缺失不伪装 0；stockThemeMeta null 守卫；facade 档位标签/图标/色从 `heatLevelScore` 派生；`MergedStock.themeHeat?: number \| null` 等 4 处类型放宽 |
| `02392e0` | 15 | 12 处 0-100 阈值消费点切换：`config/factors.ts` themeHeat、`StockHotnessCalculator.themeSupportScore`（缺失热度置 null，不参与 0.55 权重）、`BattlefieldBuilder`（:165/:254/:341/:355/:427）、`ThemeAlertEngine`、`ThemeCorrelationPanel`、`ThemeRiskDashboard`；**保留绝对值消费**：DragonBreathPanel 3000/1500 阈值、:351 排序、ThemeCorrelationPanel strength、RiskDashboard 模板展示 |
| `21ee7b6` | 16 | 快照行类型（`SnapshotStockRow.themeHeat?: number \| null`、`SnapshotSectorRow.heatLevel?: string \| number \| null` 过渡放宽）+ builders 落库点（stock row `finiteNumberOrNull`、sector row 只落数值 heatLevel）+ buildContext context 行每帧重建统一带 `metadata.factorVersion`（B9，快照缺失时 `theme-market-v2` 兜底）+ hotThemes 行 heatLevel 从 `heatLevelScore` 数值化（无值不写 key，旧字符串档位标签剔除，tri-state） |

Task 17 为阶段 B 收口与浏览器验收，Step 3 无修复需求，无独立 commit。

## golden

- trend golden v14（`57af939`）：heatLevel 纳入白名单比对；v13 不可变。
- heat golden v3（`e51219b`）：factor 输出含 heatLevel；v2 不可变。

## 执行期偏差记录（均已在对应 commit message 或计划中显式记录）

1. **B7 设计偏离（plan :1207，设计阶段确认）**：stock row 不加行级口径标记——stock row 无通用 metadata dict（仅 `volumeRatioMeta`），`themeHeat` 值由 `resolve_heat_level(sector)` 派生，口径歧义在 sector 行 `metadata.factorVersion` 层消解。已回写 design B7（本批文档收口）。
2. **Task 8（前一 session）**：计划 rotation 测试 row 缺 `change` 字段，补齐后 RED 签名与预期一致。
3. **Task 9（前一 session）**：计划伪代码 clamp 顺序缺陷——`_heat_score_number` 不得 clamp（绝对值入参），仅输出 `heatLevel` clamp，按 design §4.2 修正。
4. **Task 15**：`ThemeV3Engines.test.ts` 基础夹具缺 heatLevel 致 `theme_strength_surge` 运行时失败 → 夹具补 `heatLevel: 80`（夹具不在 vue-tsc 范围，仅运行时暴露）。
5. **Task 15**：`ThemeCorrelationPanel.vue:68` 模板消费的是组件内 `allThemes` 映射对象而非 `ThemePanelSummary` 原始行 → 映射中补 `heatLevelScore: theme.heatLevelScore` 透传。
6. **Task 16**：计划 3c 的 `...(theme.heatLevelScore != null ? { heatLevel: ... } : {})` 写法被前置 `...theme` 展开覆盖——旧字符串档位标签仍透传（hasOwnProperty 恒 true）→ 改为先解构剔除旧 `heatLevel` key 再按 `heatLevelScore` 数值条件写入，与计划测试及 design §4.2 tri-state 意图一致。

## 验证结果

按用户指示全程执行专项测试、不跑全量套件（后端全量 pytest 曾在 `test_archive_research.py` 挂起，为已知环境问题）。

- 阶段 A（Task 1-12）：每任务 TDD RED→GREEN；Task 13 收口跑阶段 A 触达模块专项 pytest 全绿（heat/trend/momentum/rotation/backtest/collector/projection/repository/backup 等专项文件）。
- 阶段 B Task 14-16：每任务定向 vitest 全绿（theme 109 用例、snapshot 12 文件 73 用例、hotness、config/factors、dragon、dataLoader 消费方 8 文件 109 用例、ExtraDataProjector、golden fixture）+ `pnpm exec vue-tsc --noEmit -p tsconfig.app.json` 零错误。
- Task 17 Step 1 收口：专项测试集全绿 + `vue-tsc` 零错误 + `pnpm build` 成功（14.83s）。
- Task 17 Step 2 浏览器验收（playwright，后端 8000 + 前端 5173 在线，用户重启服务加载新代码后）：
  1. `/api/themes/heat` 245 factor 中 heatLevel 有值 239→245（预热完成），五档分布 50/49/49/49/48（rank 百分位预期均匀层次）；`factorVersion=theme-market-v2`；`heatScore` 保持 KPL 人气绝对值（3537~750897，median ≈ 49.6k），与 heatLevel（0.4~100）解耦。
  2. DragonBreathPanel 热度数值保持绝对值量级（运行态 `heatScore=750897` 等），3000/1500 阈值消费点未改（专项测试锁定）。
  3. 多轮浏览器会话 0 console error / 0 pageerror。
  4. 运行态 `dataLayer.getStocks()` 188/203 个股 `themeHeat` 有值（94.7~100 数值）且 `themes[].heatScore` 同源透传（188/188）；档位标签 `热门` 与数值 `heatLevelScore` 并存；缺失热度显示 `--`、无「冰/冷」伪装（tri-state 降级路径，旧数据轮验证）。

## 首日人工验证清单（design §6，待上线日填写）

- [ ] `snapshot_sector_rows` 新落库 hot_theme 行 heatLevel 为数值且与 rank 百分位一致。
- [ ] `/api/themes/heat` factor 带 heatLevel；前端分级不再全判"热门"。
- [ ] 快照 context 行核验：新落库 hot_theme 行 `metadata.factorVersion` 存在（B9 生效），`heatLevel` 全为数值或缺失（无字符串档位标签混入）。
- [ ] ranked_total 与 heatLevel 分布对照（风险 1）。
- [ ] momentum jump 信号与 rank_jump 信号重叠率（风险 5）。
- [ ] confluence 75 分触发率切换前后对比（风险 6）。

实际观察结果：待上线日填写。
