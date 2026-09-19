# 快照采集池单一事实源（自治热榜池）设计

> 状态：设计已确认（2026-09-19 用户逐项确认：对齐口径 = 采集池为前端池超集；实现路径 = 单一事实源纯自治池；四节设计整体确认）；实施完成（2026-09-20，提交链 300aad60..bd6e96d2 及后续 Task 5 健壮性修复与文档同步提交，实施计划与审查记录见 quant-board/docs/snapshot-collector/2026-09-20-pool-autonomous-source-implementation-plan.md）
> 触发：2026-09-19 用户裁决——「采集池实时跟随前端池」必须彻底解决，正式立项
> 依据：`AGENTS.md §4.0`、`skills/fail-visible-data-pipelines/SKILL.md`、仓库代码与 MongoDB 实测证据（本文 §2）

## 1. 背景与根因（实测证据）

热榜情绪面板「全池状态结构」（快照池口径）与行情列表「周期」列（前端实时池口径）出现计数不可对账（实测案例：2026-09-18 面板点火 2 = 002050+301487，列表点火 3 = 002050+002192+603138，交集仅 002050；同一股票两边判定同源 `cycle.stage` 无矛盾，差异全部来自池 membership 与时点）。

根因链（全部经代码与库数据核实）：

| # | 事实 | 代码位置 |
| --- | --- | --- |
| 1 | 采集器股票池主来源 = proxy startup-bundle 缓存（前端启动时写入），bundle 成功时完全取代热榜 fallback 池 | `quant-board/backend/snapshot_collector/providers.py` `collect_market_context`（`ctx.stocks = rows` / `if ctx.stocks: continue`） |
| 2 | 前端只在启动加载流程写 bundle（BREATH.UPDATED 一次 + 信号增强完成后）；盘中 30 分钟周期只刷行情与信号，不重拉热榜、不重写 bundle | `src/services/dataLoader/DataLoaderFacade.ts`（`writeStartupBundle` 调用点、`startSignalAutoRefresh`） |
| 3 | 因此快照帧池锁定在「前端最后启动时点」的池；盘后/页面重载后进出榜的股票当日永不进帧 | 实测：002192 最后帧 2026-08-25、603138 最后帧 2026-09-15，两股 2026-09-18 全天 stock-rows = 0，但前端列表有 |
| 4 | 前端列表池随页面加载时点变化（截图时 278 只 vs 收盘帧 240 只） | 同上 |
| 5 | 采集器已具备自治构建全池的完整能力：`ProxyMergedHotlistProvider` 逐平台抓取 → code 归并 → `_rank_rows`（avgRankNum 加权 + `compute_comprehensive_scores` 五维 golden compRank），但现状仅作 bundle 缺失时的 fallback | `providers.py:744-1004` |

## 2. 关键核实（支撑"单一事实源"可行性）

**前端池 ⊆ 后端自治池在数据源层面天然成立**：

1. 前端 `Adapters[platform].getHotList()` 与后端 `ProxyMergedHotlistProvider._fetch_platform` 请求**同一个 proxy 接口** `/api/{platform}/hot`（eastmoney/tdx 同为 POST 且 payload 一致），双方均不裁剪条数（`src/services/adapters.ts` vs `providers.py:799-804`）。
2. 前端在 platformHotlistService 层额外做 stock_names 白名单过滤（`loadActiveStockCodes`）——只会让前端池更小，不影响超集方向。
3. 合并键一致：双方均按 6 位 code 归并；rank 字段映射同构（`_HOTLIST_RANK_FIELDS`）。

**口径切换点（须记录）**：现状快照行 `compRank` 来自前端本地计算（bundle 携带）；纯自治后统一为后端 golden（`compute_comprehensive_scores`）。口径更统一，但存在历史/新快照的代际差，靠 `poolSource` provenance 与文档区分。

## 3. 目标与非目标

**目标**

- 每槽快照池 = 采集器直连 `market_proxy` 热榜服务（`backend.market_proxy.hotlists` 进程内单例；HTTP proxy 仅 CLI/手动回退）实时合并八平台全量（下称"自治池"），不依赖前端浏览器在线。
- 任何时刻前端行情列表中的股票必然 ∈ 最近快照池（超集方向恒成立）；反向差异（自治池有、页面未显示的新进榜股）由面板注脚透出（2026-09-19 已交付的 `hotListPoolGapNote`，双向对账语义已覆盖）。
- 池构成可观察：每行 `poolSource` provenance；`SourceHealth.details.poolComposition` 记录各平台条数 / failedPlatforms / 池规模。
- 提供配置开关，可一键回退旧行为。

**非目标**

- 不回补历史缺失帧（股票行不在库中，无法凭空补数据；历史分析序列随未来帧自然补齐）。
- 不做前端周期刷新、不重写 bundle 写入逻辑（前端零改动；bundle 降级为只供 `snapshotContext`）。
- 不改 analyze 引擎、面板注脚、sentiment join（2026-09-19 已交付部分保持不动）。
- 不引入新的 MongoDB 集合 / API（复用现有帧入库与 health 通道）。

## 4. 架构与数据流改造点

1. **provider 路由重写**（`providers.py collect_market_context` / `collect_market_context_async`）：
   - `ProxyMergedHotlistProvider` 升为主池来源：`ctx.stocks = merged_rows`，并据此生成 `active_codes`。
   - `StartupBundleStockProvider` 降为 context 来源：只消费其 `snapshotContext`；其 `stocks` 不再作为主池。自治池全平台失败（池为空）时，用 bundle 行兜底入库并打 `poolSource: bundle_fallback`（fail-visible：bundle 是可用的数据源，不构成"全源无数据"；见 §5）；bundle 也不可用才如实报告本轮无数据。
   - `TencentBasicQuoteProvider` / `BridgeQuoteProvider` / `MarketFundCacheProvider` / `ThemeMappingProvider` / `ProxyLimitUpProvider` 的 `active_codes` 语义不变（现在等于自治池 codes，兜底时为 bundle codes）。
2. **配置开关**：`collector.pool_source_mode`：`autonomous`（默认，纯自治）| `bundle_first`（回退旧行为：bundle 优先、缺失才 fallback）。读取路径与现有 settings 一致；改配置重启采集进程即回退。
3. **provenance 与池构成**：
   - 每行注入 `poolSource: "autonomous"`（回退模式下 bundle 行为 `"bundle_fallback"`，便于区分代际）。
   - `SourceHealth(source="merged_hotlist_proxy").details.poolComposition` = `{platformTotals, failedPlatforms, poolSize, mode}`；`StartupBundleStockProvider` health 仅描述 snapshotContext 可用性。
4. **snapshotContext 缺失降级**：`autonomous` 模式下 context 缺失不阻断采集（`MarketFactBundle.snapshot_context` 置空 + frame `warnings` 打标 `snapshot_context_missing`）；`bundle_first` 回退模式维持现状语义。

## 5. 错误处理与 fail-visible 边界（对照 §4.0 / fail-visible skill）

| 场景 | 行为 | 不允许的行为 |
| --- | --- | --- |
| 8 平台全部失败 | bundle 行兜底入库（`poolSource: bundle_fallback`）；bundle 也不可用才如实报告本轮无数据（唯一允许不写入的情形）。兜底池在 bundle 先于 merged 时正常获得下游行情/题材/涨停补齐；provider 顺序反转时由循环后安全网兜底（字段诚实缺省） | 有一方可数据源时静默丢帧 |
| 部分平台失败 | 照常采集可用平台，`failedPlatforms` 记入 health（现有行为） | 因个别平台失败丢弃整帧 |
| 前端离线 / bundle 缺失 | `autonomous` 模式无影响；context 缺失打标降级 | 阻断采集或伪造 context |
| 行情/资金补齐失败 | 字段如实缺失/为 0，quote 覆盖率 <80% 打 warning（现有行为） | 用估算值伪装 |
| 新进股票（历史无序列） | analyze 走单点序列 → `sampleQuality=insufficient` → 面板「无阶段」格如实体现 | 伪装成某个 lifecycle 阶段 |

## 6. 测试策略

pytest（quant-board 现有结构，就近放置）：

- 自治池为主池：bundle stocks 不入主池、merged 行全量入池、`active_codes` 来自自治池（行情/资金 provider 按自治池 codes 拉取）。
- 自治池全平台失败：bundle 行兜底入库且 `poolSource: bundle_fallback`；bundle 也不可用时如实无数据。
- 回退开关：`bundle_first` 模式恢复旧行为（bundle 优先、merged 仅 fallback）。
- 部分平台失败仍采集 + `poolComposition.failedPlatforms` 记录；全平台失败如实无数据。
- `snapshotContext` 缺失：`autonomous` 模式照常入库 + `warnings` 含 `snapshot_context_missing`。
- provenance：每行 `poolSource` 值正确；两模式代际可区分。

## 7. 实测验收（下一交易日）

1. 页面加载后逐股核对「行情列表 ⊆ 收盘帧池」（脚本抽帧比对，不再出现"列表有、快照无"）。
2. 面板「全池状态结构」与列表对账：差异只剩「自治池有、页面未显示」方向，且注脚可解释。
3. 采集时延与 analyze 耗时在现有预算内（池规模 +10~15%）。
4. `poolComposition` 在 health/审计通道可见，platformTotals 与 proxy 实际返回一致。
5. 盘后重载页面（时点差最大场景）复验 1/2。

## 8. 风险与回退

| 风险 | 处理 |
| --- | --- |
| compRank 口径代际差（前端本地 → 后端 golden） | `poolSource` provenance 区分；文档记录；面板/列表展示差异由对账注脚兜底 |
| 池变大导致 analyze/写入量增加（约 +10~15%） | 验收第 3 条实测确认；超预算再评估 analyze 分批（不在本 spec 范围） |
| 新进股票周期判定走 insufficient →「无阶段」格占比上升 | 这是 fail-visible 的诚实表现（历史序列随未来帧补齐后自然收敛） |
| 采集器直连 hotlist 服务失败 | 进程内单例已有缓存→Redis→single-flight→last-good 链；HTTP proxy 仅作 CLI 回退 |
| 需要紧急回退 | `collector.pool_source_mode=bundle_first` 重启采集进程 |

## 9. 交付物清单（文件级预估）

- `quant-board/backend/snapshot_collector/providers.py`（路由重写 + provenance + poolComposition）
- `quant-board/backend/snapshot_collector/service.py`（兜底/标记注入点，如归一化层需要）
- 配置项 `collector.pool_source_mode` 的定义位置在 writing-plans 阶段按现有 settings 结构确定（`snapshot_collector/service_factory.py` 或 `quant-board/config/`）
- pytest 测试文件（就近放置）
- 文档：本 spec 实施状态回填、`quant-board/docs/snapshot-collector/` 立项记录、`quant-board/docs/architecture.md` 采集口径段落同步
