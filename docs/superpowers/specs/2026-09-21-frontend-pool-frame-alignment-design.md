# 前端列表池对齐后端快照帧池（池源替换）设计

> 状态：设计已确认（2026-09-21 用户确认：语义 = 列表池 membership 等于后端最新 half_hour 帧池；实现架构 = 方案 A 池源替换；四节设计整体确认）
> 触发：2026-09-21 用户裁决——「PLATFORM_CACHE_TTL_MS = 30 分钟——前端列表池是带缓存层的合并视图，其时点与采集时点天然错位，这个问题需要解决，前端列表池需和后端完全一致」
> 前序：`docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`（后端自治池已上线并实测验收；本 spec 取代其「前端零改动」非目标）
> 依据：`AGENTS.md` §4.1/§10、`skills/fail-visible-data-pipelines/SKILL.md`、2026-09-21 全交易日实测证据（本文 §1）

## 1. 背景与根因（实测证据）

2026-09-19 立项的自治池已解决「快照帧池锁定在前端最后启动时点」的问题，但面板「全池状态结构」（快照池口径）与行情列表（前端实时池口径）仍存在不可对账窗口：

| # | 事实 | 位置 |
| --- | --- | --- |
| 1 | 前端列表池 membership 来自 8 平台热榜合并池，带 30min 懒 TTL 缓存，时点与采集槽位天然错位 | `src/services/dataLoader/constants.ts:17`（`PLATFORM_CACHE_TTL_MS = 1800000`）、`src/services/dataLoader/PlatformHotlistService.ts:66` |
| 2 | 前端合并池额外做 stock_names 白名单过滤，比后端自治池多一层裁剪——即使时点同步，membership 仍存在算法性差异，「完全一致」在数据源同步路线上原理性不可达 | `PlatformHotlistService.loadActiveStockCodes` |
| 3 | 8 平台热榜源分钟级轮动（盘后仍持续），前端加载时点不同则进出榜不同 | 2026-09-21 实测：盘后重载列表 245 只 vs 收盘帧 241 只，48 missing / 42 extra；同源校验证明差异全部来自时点与白名单，非数据错误 |
| 4 | 列表池 membership 单点：`mergeData()` 入口 `getAllHotCodes()`（8 平台并集 ∩ 白名单），下游行情补齐/合并/热度/量比/信号全部围绕这组 codes 运行 | `src/services/dataLoader/DataLoaderFacade.ts:874` |

用户裁决的对账终点是「列表 = 帧池」：列表的股票集合直接采用后端最新 half_hour 帧池，不再由前端热榜合并池决定。

## 2. 目标与非目标

**目标**

- 前端列表池（`dataLayer.getStocks()`）membership **等于**后端最新 half_hour 帧池（`dragonboard_live` 正式读口径）。
- 价格/成交量仍走实时行情链（帧池只提供 membership 与种子字段，不是行情源）。
- 面板「全池状态结构」与列表计数同槽同池，天然可对账；池差异注脚只在降级/槽位滞后时如实出现。
- 池来源全程可观察：`{ source, slotTime, degradeReason? }` provenance 打标（`frame-pool` | `hotlist-merged` | `startup-bundle`）。
- 后端不可用/无帧时回退现行为（热榜合并池），fail-visible 不静默。

**非目标**

- 不改采集器与 QuantBoard 后端任何代码（复用现有 `/api/snapshots/frames`、`/api/snapshots/stock-rows` 读通道，不新增 API/集合）。
- 不改 RankTrend 信号计算与个股热度算法（TS golden 不动）。
- 不改 startup-bundle 写入路径（采集器 snapshotContext 与 bundle_first 回退模式不受影响）。
- 不删除 `PLATFORM_CACHE_TTL_MS` 热榜缓存（platformData 仍服务平台状态与行字段展示），只是 membership 不再依赖其新鲜度。
- 不做历史帧回补。

## 3. 架构与数据流改造点（全部在根项目 `src/`）

1. **新增 `src/services/dataLoader/framePoolSource.ts`**：
   - 读最新帧池：先 `snapshotBackendRead.listSnapshotFrames({ type: 'half_hour', tradingDate: <今日>, sort: 'desc', limit: 1 })` 取最新槽（slotTime/poolComposition/stockRowCount），再 `listSnapshotStockRows({ type: 'half_hour', tradingDate, slotTime, limit: 500 })` 取该槽全量行。
   - 交易日用 `toLocalTradingDate`（`src/services/snapshot/identity.ts:27`），不新造解析。
   - 产出 `{ codes: Set<string>, slotTime, tradingDate, rowsByCode }`；HTTP 失败/当日无帧/空 rows 一律返回结构化 null（含 reason），不抛异常。
2. **`mergeData()` 池源切换**（`DataLoaderFacade.ts` mergeData 入口）：
   - `allCodes` 优先取帧池 codes；`platformData` 行过滤到帧池范围。
   - 帧池中无热榜行的股票以帧行做种子进入合并链：名称/compRank 取帧行（compRank 为后端 golden 值，直接采用），价格/成交量由实时行情链覆盖，热度/量比/信号照常计算。
   - 种子行构建细节（字段映射、缺字段回退）在实施计划阶段按 `SnapshotStockRow` 实际字段落定。
3. **降级 fail-visible**：帧池不可用（请求失败/当日无帧/空 codes）→ 回退现行为（热榜合并池）+ provenance 打 `{ source: 'hotlist-merged', degradeReason }`；启动快路径打 `startup-bundle`；帧池成功打 `frame-pool` + slotTime。不允许静默吞掉后伪装一致。
4. **刷新时机**：现有 30min 到期检查 `maybeRefreshPlatformCache` 处同步探测新槽（比对当前 provenance.slotTime 与最新帧 slotTime），有新帧即以帧池重建列表。热榜平台加载链保留。
5. **白名单语义变化（明确的行为变化）**：`loadActiveStockCodes` 白名单不再裁剪列表池 membership（帧池股票全量展示）；白名单仍可用于 platformData 行字段处理的场合。这是「完全一致」的隐含项。
6. **启动路径**：startup-bundle 首屏快发布保持现状（首屏速度优先，打 `startup-bundle` 标），其后的后台刷新立即切帧池——不一致窗口仅启动后数秒。
7. **信号链兼容**：`startSignalAutoRefresh` / `RankTrendSignalService` 的重算发布路径 map 现有 stocks，membership 天然保持；实施时以测试验证不引入 membership 漂移。
8. **面板注脚**（`DragonBreathPanel.vue` `hotListPoolGapNote`）：语义更新——同槽一致时不再显示两池差异；仅当列表处于降级源或槽位落后 sentiment 最新槽时，如实显示「列表池来源/槽位」。对该文件（含用户未提交改动）做最小增量编辑，不覆盖、不回退现状。

## 4. 错误处理与 fail-visible 边界

| 场景 | 行为 | 不允许的行为 |
| --- | --- | --- |
| 后端 8000 不可用 | 回退热榜合并池 + `hotlist-merged` + degradeReason 透出 | 静默回退且注脚消失 |
| 当日无帧（如非交易日早间） | 回退热榜合并池 + 如实标注 | 显示空列表或旧帧冒充最新 |
| 帧池 rows 为空 / 翻页异常 | 同上按不可用处理 | 用不完整 codes 裁剪池 |
| 帧池滞后 sentiment 最新槽（前端未刷新） | 注脚如实显示列表所在槽位 | 伪造一致 |
| 帧池种子行字段稀疏（无平台 rank） | compRank 用后端 golden；行情实时补齐；热度/信号照常算 | 用估算值伪装平台排名 |
| 翻日边界（跨零点/周末） | `toLocalTradingDate` 统一口径，非交易日自然落「当日无帧」回退 | 用昨日帧冒充今日 |

## 5. 测试策略（TDD：先写测试锁行为，再改代码）

- `framePoolSource` 单测（mock `snapshotBackendRead`）：正常两步读取 / frames 空 / stock-rows 空 / HTTP 抛错 / 跨交易日，均返回结构化结果或 null+reason。
- `mergeData` 帧池模式：membership = 帧池 codes（含帧独有股票的种子行）；实时行情覆盖种子价格；降级回退 + provenance 打标；existingMap 兼容。
- 信号链回归：信号重算/热度重算的 publish 路径不改变 membership。
- 现有 `DataLoaderFacade` / `PlatformHotlistService` 测试适配不回归；`DragonBreathPanel` 注脚源断言测试同步更新（保留用户未提交断言语义）。
- 验证命令：`pnpm test`（相关子集）+ `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` + `pnpm test:ranktrend`（确认 golden 无漂移）。

## 6. 风险与回退

| 风险 | 处理 |
| --- | --- |
| 列表池规模波动（帧池 ~240-250 vs 现列表 ~245） | 量级相同；实测验收对账 |
| 种子行字段稀疏影响排序观感 | compRank 用后端 golden；实施计划中明确字段映射与回退 |
| 后端不可用成为常态 | 回退路径 = 现行为，无功能损失 |
| 帧池模式引入首屏后短暂不一致 | 启动快路径保持 + provenance 如实打标 |
| 紧急回退 | 池源切换为单一入口（`mergeData` 一处），git revert 即可；帧池失败自动回退已内建 |

## 7. 交付物清单（文件级预估）

- 新增 `src/services/dataLoader/framePoolSource.ts`（帧池读取 + 结构化降级）
- 修改 `src/services/dataLoader/DataLoaderFacade.ts`（mergeData 池源切换、maybeRefreshPlatformCache 新槽探测、provenance 打标）
- 修改 `src/services/DataLayer.ts` 或其投影（池来源状态的最窄内存状态位；若现有订阅结构可承载则不加新方法，实施计划定）
- 修改 `src/components/panels/DragonBreathPanel.vue`（注脚语义，最小增量）
- 测试：`src/services/dataLoader/__tests__/framePoolSource.test.ts`、`DataLoaderFacade.test.ts` 增补、`DragonBreathPanel.test.ts` 同步
- 文档：本 spec 实施状态回填；如对账语义变化影响 `docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md` 的验收口径，同批补一行交叉引用
