# MongoDB 全市场题材热度替代 JXBK 设计

## 1. 结论

废弃 `localhost:5000` JXBK 作为题材动态数据依赖，由 QuantBoard 后端统一计算全市场题材热度：MongoDB `themes/theme_stock_mappings` 提供题材事实映射，腾讯提供唯一基础行情，东财只提供资金字段。Dragon Board 前端通过公开 API 消费统一结果，backend snapshot collector 直接复用同一服务生成并写入完整 `snapshot_sector_rows`。

本设计同时修复两条链：

1. Dragon Board `sectorAnalyzer.ts` 与 `src/services/theme/**` 的题材运行态、详情加载、轮动、预警和浏览器触发快照。
2. `quantboard-backend-snapshot-collector` 工作树中的独立 backend collector，使其不再写入 `sectorRows=[]`。

## 2. 已确认现状与根因

### 2.1 MongoDB theme 只提供静态事实

当前正式入口为：

```text
ThemeDataService
  -> GET /api/themes/mapping
  -> MongoThemeRepository.get_mapping()
  -> themes + theme_stock_mappings
```

2026-06-21 本机实际数据为：

- 239 个题材；
- 12219 条题材—股票映射；
- 4167 只去重股票。

这些集合包含题材名称、股票关系、标签和原因，不包含实时题材热度。

### 2.2 前端动态链仍依赖 JXBK 5000 端口

旧链路为：

```text
sectorAnalyzer
  -> ThemeFacade
  -> ThemeRuntimeCoordinator
  -> JxbkThemeFeed
  -> apiService theme context
  -> http://localhost:5000
```

`ThemeFactorEngine` 虽然能在无 JXBK block 时使用成分股行情计算部分分数，但 `DataLayer` 股票池主要来自八平台热榜，不能覆盖 MongoDB 映射的全市场股票。直接删除 5000 调用会造成严重的热榜抽样偏差。

### 2.3 backend collector 从未生成 sector 上下文

collector 已有 `ThemeMappingProvider`，但 `_create_providers()` 实际只装配 `ProxyHotlistProvider` 和 `ProxyQuoteProvider`。此外，现有 builder 只把 `MarketDataContext.sectors` 原样转换为 `sectorRows`，没有题材聚合器。

因此当前 `sectorRows=0` 的根因不是 MongoDB 写入失败，而是采集上下文没有生成任何 sector。

### 2.4 数据源实测

2026-06-21 经本机 `proxy-server:3000` 验证：

| 来源 | 样本 | 返回 | 耗时 | 结论 |
| --- | ---: | ---: | ---: | --- |
| 腾讯基础行情 | 3 | 3 | 约 0.8 秒 | 正常 |
| 腾讯基础行情 | 50 | 50 | 约 0.45 秒 | 正常 |
| 东财资金字段 | 3 | 3 | 约 4.4 秒 | 正常，无 fallback/stale |
| 东财资金字段 | 50 | 50 | 约 4 秒 | 正常，50 只有资金字段 |

腾讯响应可提供价格、涨跌幅、成交量、成交额、换手率和量比；资金字段为零。东财当前可提供 `f62/f66/f69/f184`，但本设计不使用其价格、涨跌幅等基础字段。

## 3. 目标与非目标

### 3.1 目标

- 基于 MongoDB 映射覆盖的全部有效 A 股计算题材热度，不使用热榜股票作为计算母集。
- 每 5 分钟刷新一次全市场题材热度并缓存。
- 前端和 backend collector 使用同一 Python 计算引擎与字段合同。
- UI 只裁剪展示数量；正式快照保存全部题材结果。
- `half_hour`、`daily` collector 快照写入非空、可审计的 `snapshot_sector_rows`。
- 数据源缺失、覆盖不足、陈旧和时间偏差均结构化表达。

### 3.2 非目标

- 不恢复或仿造 JXBK 5000 接口。
- 不把合成题材指标描述成 KPL/JXBK 原始板块指标。
- 不让 Dragon Board 浏览器直连 MongoDB。
- 不把动态热度写回 `themes/theme_stock_mappings`。
- 不改变 RankTrend 独立产生候选信号的硬约束。
- 不在本轮引入新的行情供应商或大型依赖。

## 4. 方案比较

### 4.1 前端与 collector 分别计算

优点是单侧改动直观；缺点是会重复抓取 4167 只股票，TS/Python 权重与边界容易漂移，同一时点可能产生不同 `sectorRows`。不采用。

### 4.2 proxy-server 伪造 JXBK 兼容接口

优点是前端改动较少；缺点是把题材算法塞进 HTTP 代理层，并继续混淆真实来源。collector 仍需要复制或调用该业务逻辑。与目录职责冲突，不采用。

### 4.3 QuantBoard 统一 ThemeHeatService

MongoDB 提供映射，proxy-server 提供分批行情，QuantBoard 负责聚合、质量门禁、缓存和统一因子计算。前端通过 API 消费，collector 通过服务调用。该方案边界清楚、可复用、可测试，作为最终方案。

## 5. 总体架构

```text
MongoDB themes + theme_stock_mappings
                  |
                  +-- 全部有效股票代码
                  v
proxy-server
  +-- 腾讯基础行情：50 只/批，有限并发
  +-- 东财资金字段：50 只/批，有限并发
                  |
                  v
QuantBoard ThemeHeatService（5 分钟缓存）
  +-- 映射索引与行情覆盖率
  +-- 题材市场聚合
  +-- 统一 ThemeFactor 计算
  +-- 结构化质量结果
        |
        +-- GET /api/themes/heat
        |     +-- Dragon Board ThemeHeatFeed
        |           +-- ThemeRuntimeStore
        |           +-- ThemeStockProjector
        |           +-- DataLayer.hotThemes
        |           +-- 页面/预警/轮动/浏览器快照
        |
        +-- GET /api/themes/heat/{theme_id}/stocks
        |     +-- sectorAnalyzer.loadSectorStocks()
        |
        +-- backend snapshot collector
              +-- MarketDataContext.sectors
              +-- builder
              +-- half_hour/daily snapshot_sector_rows
```

## 6. 后端组件边界

### 6.1 纯计算引擎

建议新增 `quant-board/backend/analysis/theme_heat.py`，职责仅为：

- 接收标准化题材、成分股、基础行情、资金字段及可选涨停/热榜增强数据；
- 计算题材聚合指标、因子、排名和质量标记；
- 不访问 HTTP、MongoDB 或进程缓存；
- 输出确定性结果，便于 Python 单测和 TS/Python golden 对齐。

现有 `analysis/theme_trend.py` 中与 TypeScript runtime factor 对齐的私有逻辑应迁移或委托给该公开纯函数，避免 collector 再实现第三套公式。ThemeTrend 研究链继续消费快照 rows，不反向承担实时采集职责。

### 6.2 运行编排服务

建议新增 `quant-board/backend/services/theme_heat_service.py`：

- 一次调用 `MongoThemeRepository.get_mapping()`，构建 `theme -> codes` 与 `code -> themes` 索引；
- 根据 mapping version 失效映射缓存；
- 以 50 只股票为一批抓取行情；
- 腾讯和东财按独立 provider、独立覆盖率处理；
- 对失败批次最多重试一次，不重复完整全市场请求；
- 合并并发刷新请求，避免多个页面或 collector 同时触发重复计算；
- 按 5 分钟 bucket 缓存结果；
- `force=true` 时跳过因子缓存，但仍复用 proxy-server 合法的短 TTL 响应缓存；
- 返回 factors、可查询的成分行情索引、全局质量摘要和数据源元信息。

默认批量参数：

```text
batch_size = 50
max_concurrency = 3
failed_batch_retries = 1
cache_ttl = 5 minutes
```

参数作为稳定运行时配置放在 QuantBoard `config/` 或 settings，不放入类型文件。

### 6.3 数据源 provider

现有 collector 的 `ProxyQuoteProvider` 不再承担全市场题材行情。新增或拆分：

- `TencentBasicQuoteProvider`：只接受并输出腾讯基础行情字段；
- `EastmoneyFundFlowProvider`：只接受并输出东财资金字段；
- `MongoThemeUniverseProvider`：一次性读取完整 mapping，不逐股票执行 `get_stock_themes()`。

provider 输出必须携带：

```text
source
requestedCount
returnedCount
coverageRatio
startedAt
completedAt
failedBatches
stale
```

东财响应里的基础行情字段在 provider 边界即丢弃，不能进入后续 merge。

### 6.4 API

新增路由模块并由 FastAPI 注册：

```text
GET /api/themes/heat
GET /api/themes/heat/{theme_id}/stocks
```

摘要接口返回全部题材 factors，但不返回全部 4167 只股票明细。详情接口从同一 5 分钟缓存按题材读取成分股，支持 `limit`、`offset` 与明确排序字段。

成功响应至少包含：

```json
{
  "ok": true,
  "data": {
    "computedAt": 1782018300000,
    "cacheBucket": "2026-06-21T14:25+08:00",
    "factorVersion": "theme-market-v1",
    "mappingVersion": "theme-v8-test",
    "factors": [],
    "quality": {},
    "sources": {}
  }
}
```

MongoDB 或腾讯主源失败时返回非成功 HTTP 状态和结构化错误；如果存在最后成功缓存，可在 `staleData` 中显式附带，但不能把响应伪装成 `ok=true`。

### 6.5 collector 接入

collector 在保留热榜 stock rows 的同时，调用 `ThemeHeatService` 取得全市场 factors。它不把全部 4167 只行情写成 stock rows，仅把它们作为题材聚合输入。

每个 factor 转为 `MarketDataContext.sectors` 条目：

```text
entityType = hot_theme
code        = themeId
name        = themeName
rank        = factor rank
```

现有 builder 继续负责统一生成 `SnapshotSectorRow`。若 builder 当前会把缺失数值强制变成零，应调整为保留“不适用/不可用”的语义。

## 7. 前端组件边界

### 7.1 ThemeHeatFeed

建议新增 `src/services/theme/ThemeHeatFeed.ts`：

- 通过 `apiService` 调用 QuantBoard 题材热度 API；
- 合并并发刷新；
- 保存最近成功摘要及明确 stale 状态；
- 按题材加载详情成分行情；
- 把远端 factor 合同转为前端 `ThemeFactorSnapshot`；
- 不实现全市场算法，不请求 4167 只行情。

### 7.2 ThemeRuntimeCoordinator 与 ThemeFacade

运行态继续以 `ThemeRuntimeCoordinator.refreshRuntime()` 和 `themeFacade` 为权威入口，但默认 factor 来源改为 `ThemeHeatFeed`。

刷新成功后统一执行：

1. 更新 `ThemeRuntimeStore.factors`；
2. 使用 `ThemeStockProjector` 对当前前端股票池生成个股暴露；
3. 更新轮动、事件和质量摘要；
4. 同步 `DataLayer.hotThemes`；
5. 按需同步当前股票的题材暴露。

这会修复现有普通 `refreshRuntime()` 不保证更新 `DataLayer.hotThemes`、导致浏览器快照取得旧热门题材的问题。

### 7.3 sectorAnalyzer 兼容边界

`sectorAnalyzer` 继续保留公开 API，但只做 adapter：

- `triggerHeatCalculation()` 委托 `ThemeFacade`；
- `loadSectorStocks()` 委托 `ThemeHeatFeed` 详情接口；
- `preloadTopSectors()` 只预取当前 Top N 详情；
- `forceRefreshJxbk()` 保留旧名称作为 deprecated wrapper，内部执行 market aggregate 强制刷新；
- stats 明确返回 `themeHeatSource=market_aggregate`，不再报告 JXBK 为正式来源。

`JxbkThemeFeed` 不再进入正式刷新路径。若仍有旧控制台或测试依赖，可暂时保留文件和兼容方法，但不得再访问 5000。

### 7.4 UI 与旧合同

正式运行态新增 `market_aggregate` 来源。旧 `getJxbkBlocks()` 可短期作为展示兼容 adapter，把 factor 摘要投影为旧块结构，但：

- 不进入正式快照事实字段；
- 不生成 `jxbk_missing`；
- 不把缺失资金或机构字段伪装成真实零值；
- 面板数据源文案应改为“MongoDB 题材映射 + 腾讯行情 + 东财资金”。

## 8. 题材计算合同

### 8.1 基础聚合

每个题材基于全部有效成分股计算：

- `mappedStockCount`；
- `quoteCoveredCount` 与 `quoteCoverageRatio`；
- `fundCoveredCount` 与 `fundCoverageRatio`；
- 去极值后的平均涨跌幅；
- 上涨、涨幅不低于 5%、涨停股票比例；
- 截断异常值后的平均量比；
- 主力净流入合计与资金流为正的股票比例；
- 涨停数、龙头增强信息；
- 成分股方向一致性。

热榜和涨停池只能作为 leadership 增强数据，不能决定题材成分母集。

### 8.2 组件和权重

延续当前主体权重：

```text
breadthScore      36%
fundScore         22%
leadershipScore   28%
correlationScore  14%
+ persistence bonus
- crowding penalty
```

所有组件按比例或标准化指标计算，避免成分数量较多的题材天然得分更高。

`momentumScore` 改由当前平均涨幅、强势股比例和相对上一轮 5 分钟结果的变化构成，不再引用 JXBK strength/change。

### 8.3 资金降级

资金覆盖率分级：

- 不低于 80%：正常使用 22% `fundScore` 权重；
- 50%–80%：使用有效样本计算并标记 `fund_flow_partial`；
- 低于 50%：`fundScore` 不可用，标记 `fund_flow_unavailable`。

`fundScore` 不可用时，breadth、leadership、correlation 的 36:28:14 权重按总和 78 归一化。不能把缺少资金数据解释为资金净流入为零。

## 9. 质量门禁

### 9.1 全局腾讯覆盖率

- 不低于 95%：正常；
- 85%–95%：允许计算，标记 `quote_coverage_partial`；
- 低于 85%：拒绝生成新的有效题材排名。

### 9.2 单题材腾讯覆盖率

- 不低于 80%：正常参与排名；
- 50%–80%：参与计算并标记 `theme_quote_coverage_low`；
- 低于 50%：保留审计 row，但不参与有效排名，`heatScore` 保持不可用而不是伪造为 0。

### 9.3 质量标记

正式合同至少支持：

```text
quote_coverage_partial
theme_quote_coverage_low
quote_stale
fund_flow_partial
fund_flow_unavailable
mapping_empty
low_sample
invalid_number
source_time_skew
persistence_history_insufficient
```

原 `jxbk_missing` 不再适用于新主链。

### 9.4 失败行为

- MongoDB mapping 失败：API 结构化失败，不回落 IndexedDB、静态 JSON 或旧 SQLite。
- 腾讯主源失败或覆盖低于门槛：不发布新有效排名。
- 东财资金失败：按无资金权重降级，结果标记 degraded。
- frontend 可展示最后成功缓存，但必须显示 stale 和失败原因。
- collector 的股票快照可继续按现有门禁保存；题材失败必须记录 `theme_heat_blocked`，不得产出伪造 sector rows。

## 10. `SnapshotSectorRow` 合同

正式题材 row 使用：

```text
entityType = hot_theme
entityKey  = theme.id
entityName = theme.name
```

核心字段：

```text
rank
heatScore
momentumScore
breadthScore
fundScore
leadershipScore
correlationScore
crowdingRisk
persistenceScore
change
mainNetInflow
volumeRatio
ztCount
leaderCount
themeQualityFlags
```

`metadata` 保存：

```text
factorVersion
mappingVersion
quoteSource=tencent
fundSource=eastmoney
mappedStockCount
quoteCoveredCount
quoteCoverageRatio
fundCoveredCount
fundCoverageRatio
computedAt
cacheBucket
degraded
```

UI 可展示 Top N，但每个正式 snapshot 应保存所有映射有效的题材 row，包括因覆盖不足而不可排名的审计 row。

## 11. 缓存、一致性与性能

- 计算缓存以 5 分钟 bucket 和 mapping version 为键。
- 同一进程同一 bucket 的并发请求合并为一个任务。
- 8000 API 与 8001 shadow collector 可各自维护进程内缓存，但必须使用相同代码、配置、factorVersion 和来源合同。
- 正式 snapshot row 保存 `computedAt/cacheBucket/factorVersion`，便于比较两个进程的采样差异。
- proxy-server 的短 TTL 缓存可减少 8000/8001 同时请求造成的上游重复流量。
- 50 只一批、并发 3 的目标是让约 84 个批次在 5 分钟窗口内完成，同时避免一次 URL 过长和代理突发压力。

## 12. 测试与验收

### 12.1 后端测试

- 纯计算：空题材、低样本、异常数值、不同题材规模、资金缺失、覆盖不足、拥挤风险。
- provider：50 只分批、并发上限、失败批次单次重试、腾讯/东财字段隔离。
- service：映射缓存、5 分钟缓存、并发合并、强制刷新、stale 错误。
- API：摘要、详情、分页、结构化失败。
- collector contract：provider -> ThemeHeatService -> context -> builder -> normalizer。
- MongoDB integration：`frame.sectorRowCount` 与实际 `snapshot_sector_rows` 数量一致。
- TS/Python golden：固定输入的字段、质量标记和排名对齐。

### 12.2 前端测试

- 不再调用 5000；
- factors 正确进入 runtime store；
- `DataLayer.hotThemes` 每次成功刷新同步；
- stale/失败不会覆盖最近成功结果；
- 详情按题材 API 加载；
- `sectorAnalyzer` 旧公开 API 正确委托。

### 12.3 验证命令

根项目至少运行：

```powershell
pnpm exec vitest run src/services/theme src/services/__tests__/themeLegacyAdapters.test.ts src/services/snapshot
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
pnpm build
```

QuantBoard 工作树至少运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_*.py tests/test_theme_*.py tests/test_mongo_theme_repository.py -q
```

涉及面板和详情行为，必须使用 Playwright 验证真实页面、手动刷新、错误状态、横向溢出和控制台错误。

### 12.4 现场验收

1. 非交易时段完成 API 连通、批次覆盖率和 dry-run 验证。
2. shadow collector 保持 `dataset_id=dragonboard_backend_shadow`。
3. 连续两个完整交易日审计 `half_hour/daily`：sector rows 非空、数量稳定、覆盖率达标、frame count 一致。
4. 与前端同时间 bucket 的 Top 题材、分数和 factorVersion 对比。
5. 审计通过后才能讨论切换正式 dataset，不以单测或单次盘中样本替代真实交易日门禁。

## 13. 实施边界与顺序

collector 实现目前只存在于 `D:\dragon-board-worktrees\quantboard-backend-snapshot-collector` 分支，因此跨前后端实现应在该工作树完成，避免在 main 上为尚未合并的 collector 建立并行版本。

建议分为四个可独立验证阶段：

1. 后端纯引擎、双行情 provider、缓存服务和 API。
2. collector 接入、sector rows 合同和 MongoDB 集成验证。
3. Dragon Board `ThemeHeatFeed/ThemeFacade/sectorAnalyzer` 迁移及前端测试。
4. 浏览器验收、shadow 两交易日审计和切换评估。

每阶段均保持旧 5000 路径不再被正式主链调用；删除遗留配置和兼容代码只处理因本次迁移明确变成孤儿的部分，不做无关重构。
