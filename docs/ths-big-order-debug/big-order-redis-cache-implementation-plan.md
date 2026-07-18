# BigOrder Redis TTL Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **执行约束：** 后续实现应使用 TDD；本计划不授权提交、推送或修改无关文件。

**Goal:** 让 THSBigOrder 的 THS/Longhu 大单正常流量统一经过 proxy Redis 缓存，以 Longhu 全天快照增量刷新代替每轮全量分页，并让 WinForms 只播报本轮新增的有效语音信号。

**Architecture:** `proxy-server` 复用现有 `ProxyRedisCache` 与 `ProcessMemoryCache`。Longhu 新增独立全天快照服务和结构化端点；WinForms 改为 proxy-first/only，proxy 不可用时只使用有时限的同股同源 last-good。WinForms 在已接受的完整 orders 快照上维护按股票/来源/交易日隔离的出现次数基线，再把本轮新增订单交给现有筛选和 marker 规则生成单批次语音。

**Tech Stack:** Node.js、Express、Redis 4.x、Node test runner、C# .NET Framework 4.8、Newtonsoft.Json。

## 2026-07-18 完成度审计

下表是本轮复核后的权威状态；下方逐步 checkbox 保留原始 TDD 执行清单，不能用未回填的历史方框否定本表和对应测试证据。

| Task | 状态 | 证据 / 说明 |
|---|---|---|
| 1 真实合同 | 自动化合同完成，生产实测门禁保留 | POST、`st=200`、DeviceID、短页/Total/超量/逻辑偏移均有 fixture；prepend-only 的生产启用仍需盘中证据，因此默认 `off`。 |
| 2 冷启动 | 完成 | 三次尝试共享 45 秒 deadline；稳定快照与 logical offset 均覆盖。 |
| 3 增量刷新 | 自动化合同完成，生产实测门禁保留 | delta/overlap、合法重复、短页、Total 超量/漂移、连续失败/60 秒年龄重建、独立低优先级审计均覆盖；真实 prepend-only 仍未在盘中启用。 |
| 4 TTL/风控 | 完成 | L1/L2、7 天物理保留、单值上限、容量跳过诊断、源 breaker、单 key 冷却和有界 scheduler 均覆盖。 |
| 5 结构化端点 | 完成 | canonical envelope、动态 TTL/refresh 诊断、OpenAPI schema 与旧路由兼容测试通过；THS 的 `refresh` 按实际响应保持可选。 |
| 6 THS detail | 完成 | Redis 优先、权威 `sessionDate`、null fail-closed 和 order 日期规范化已覆盖。 |
| 7 WinForms 缓存入口 | 完成 | proxy-primary、独立 60 秒客户端、同 sessionDate last-good 和跨日拒绝测试通过。 |
| 8 增量语音 | 完成 | occurrence tracker、FIFO batch、筛选/marker、null/re-enable、切源/跨日/Kind 边界测试通过。 |
| 9 文档 | 完成 | API、design、plan、OpenAPI 与部署顺序已同步。 |
| 10 自动验证 | 完成（2026-07-18 新鲜验证） | proxy `npm test` 133/133、C# runner 72/72、Release build 0 warning/0 error、目标回归 57/57、`git diff --check` 通过。 |
| 11 本地永久归档 | 完成（2026-07-17 新增需求） | 设计 §7.1；`bigOrderArchive.js` 写通式归档 + 冷启动回填 + `bigOrderArchive.test.mjs` 11 项测试。 |
| 12 收盘后候选池采集 | 完成（2026-07-17 新增需求） | 设计 §7.2；`bigOrderCollector.js`（登记/列出/逐只采集/定时worker）+ POST `/collect-list`、`/collect` 端点 + 测试。 |

Task 10 中的“人工盘中验收”是部署后的观察清单：需要真实交易流量和扬声器，不能由 fixture 伪造，也不阻塞代码实施完成。若观察失败，应按新缺陷重新进入 RED→GREEN，而不是把生产门禁自动切到增量模式。

---

## 文件边界

- Create: `proxy-server/services/longhuBigOrderCache.js`

  负责 Longhu 上游 200 条分页、完整重建、增量刷新、校验和熔断。
- Create: `proxy-server/services/bigOrderArchive.js`

  全天快照本地永久归档（设计 §7.1）：gzip 文件、原子覆盖、失败只告警、冷启动回填。
- Create: `proxy-server/services/bigOrderCollector.js`

  收盘后候选池采集（设计 §7.2）：登记/列出/逐只采集/定时 worker；无质量门禁，单只失败不阻断。
- Create: `proxy-server/__tests__/bigOrderArchive.test.mjs`

  覆盖归档写入/回填、原子覆盖、失败语义、服务集成触发和采集登记/执行。
- Modify: `proxy-server/routes/bigOrder.js`

  注册新端点，给 THS detail/旧 Longhu 路由接入缓存服务。
- Modify: `proxy-server/helpers/proxyCache.js`

  增加 BigOrder TTL 常量和复用现有两种 cache 的 `LayeredProxyCache`，不复制 Redis client。
- Modify: `proxy-server/openapi.js`

  记录新端点、缓存元数据和旧端点兼容边界。
- Create: `proxy-server/__tests__/longhuBigOrderCache.test.mjs`

  覆盖冷启动、增量、stale、风控和完整性。
- Create: `proxy-server/__tests__/proxyCache.test.mjs`

  覆盖 L1/L2 逐层读取、回填、双写、Redis 运行中失败和 single-flight。
- Modify: `proxy-server/__tests__/thsBigOrder.test.mjs`

  覆盖 THS Redis 优先和旧路由兼容。
- Modify: `tools/THSBigOrder/DataSources/LonghuBigOrderSourceClient.cs`

  消费结构化全天端点，正常路径不再分页直连。
- Modify: `tools/THSBigOrder/DataSources/ThsBigOrderSourceClient.cs`

  解析 THS envelope 的权威 `sessionDate`，把正常 proxy 大单映射为 `ProxyPrimary`。
- Modify: `tools/THSBigOrder/DataSources/MarketSourceContracts.cs`

  新增 `ProxyPrimary`，状态文本区分正常代理通道和真正的 proxy fallback。
- Modify: `tools/THSBigOrder/THSBigOrderDataProvider.cs`

  大单源改用 proxy 正常入口，本地 last-good 增加交易日和最大陈旧时间。
- Modify: `tools/THSBigOrder/Models/MarketSnapshot.cs`

  把结构化响应的 `sessionDate` 传到已绑定快照，供跨日 last-good 和语音 scope 使用。
- Modify: `tools/THSBigOrder/Parsing/ThsPayloadParser.cs`

  使用权威 THS `sessionDate` 规范化只有时分秒的 order 时间，禁止 `DateTime.Today` 进入稳定订单指纹。
- Create: `tools/THSBigOrder/BigOrderAnnouncementTracker.cs`

  只负责完整 orders 快照的 scope 基线和重复计数增量识别，不依赖 UI 控件或 `SpeechSynthesizer`。
- Modify: `tools/THSBigOrder/VoiceService.cs`

  增加 `IBigOrderVoice`、可注入 `ISpeechQueue`、批次播报和显式取消入口；普通批次不再调用 `SpeakAsyncCancelAll()`。
- Modify: `tools/THSBigOrder/MainForm.cs`

  在 generation 校验后的快照绑定流程中观察增量、应用现有筛选和四类 marker，并在切股/切源/关闭语音时处理基线与队列。
- Modify: `tools/THSBigOrder.Tests/LonghuFeatureTests.cs`

  更新 proxy-first、stale 和切源缓存回归测试。
- Modify: `tools/THSBigOrder.Tests/Program.cs`

  注册新增的 transport、proxy-first、sessionDate 和 bounded stale 测试。
- Modify: `docs/API/ths-l2-api-analysis.md`

  固化 POST、200 条稳定页大小、预算和旧 money 合同。
- Modify: `docs/superpowers/specs/2026-07-16-thsbigorder-dual-source-design.md`
- Modify: `docs/superpowers/plans/2026-07-16-thsbigorder-longhu-source.md`

  区分“已实现的 direct-first 基线”和“Redis 改造后的 Longhu proxy-primary 目标”，避免两套架构口径互相覆盖。

## Task 1：实测并锁定 Longhu 真实合同

- [ ] 增加只读诊断脚本或测试 fixture，比较 GET/POST，正式服务只允许 POST form。
- [ ] 固定 DeviceID 连续分页，记录活跃股票在 15 秒窗口内 `Total` 是否固定。
- [ ] 对连续两次全量/头页样本验证 `newList[delta:] == oldList` 的 prepend-only 合同。
- [ ] 将实测结果补入 `docs/API/ths-l2-api-analysis.md`；若门禁失败，在实现中保持增量关闭。
- [ ] 在 `longhuBigOrderCache.test.mjs` 写失败测试：公共调用请求 500 条时，服务内部只能发送 `st=200` 的子请求并聚合，不能把 `st=500` 发给上游。
- [ ] 写失败测试：201 条数据使用 `Index=0/200`，同次完整重建复用 DeviceID。
- [ ] 写失败测试：所有上游请求都是 POST `application/x-www-form-urlencoded`，表单字段与 direct 合同一致。
- [ ] 写失败测试：`off` / `prepend-device-snapshot` 模式下，未达到 `Total` 的短页、分页中 `Total` 变化、累计超过 `Total` 均拒绝写缓存。
- [ ] 写失败测试：`prepend-logical` 模式下，Total 增长按逻辑偏移重试后可以成功；`currentTotal < T0`、同一逻辑页变化超过 2 次或所有尝试共享的 45 秒预算耗尽时失败。
- [ ] 写失败测试：默认 `off` 模式不执行增量合并，且不能在运行中自动升级模式。
- [ ] 运行：

```powershell
node --test proxy-server/__tests__/longhuBigOrderCache.test.mjs
```

预期：因 `longhuBigOrderCache.js` 尚不存在而失败。

## Task 2：实现冷启动完整快照

- [ ] 新建 `longhuBigOrderCache.js`，导出：

```js
export function createLonghuBigOrderService({
  plainClient,
  layeredCache,
  now,
  delayMs = 150,
}) {}
```

- [ ] 服务公开：

```js
await service.loadAllDay({ stockCode, money: 0 })
await service.loadPage({ stockCode, money: 0, index: 0, limit: 100 })
```

- [ ] 冷启动固定上游 `st=200`、串行分页、复用 DeviceID，仅完整结果写：

```text
big-order:longhu:all-day:v2:{sessionDate}:{stockCode}:{money}
```

- [ ] 实现固定 DeviceID 的 POST form 分页。
- [ ] DeviceID 不固定快照但 prepend-only 门禁通过时，实现 `Index = logicalOffset + (currentTotal - T0)` 的逻辑快照；`currentTotal < T0` 立即失败，单页最多重试 2 次，完整重建总预算 45 秒。
- [ ] 用同一个 `AbortController` 把 45 秒 deadline 传给本次完整重建的每个 POST；预算耗尽时中止活动上游请求、拒绝写缓存并释放 scheduler slot。
- [ ] 从配置读取 `BIG_ORDER_LONGHU_INCREMENTAL_MODE`，默认 `off`；只接受 `off/prepend-device-snapshot/prepend-logical`。
- [ ] 在本任务实现 canonical session 读路径，而不是推迟到 THS 任务：
  - `big-order:longhu:latest:v1:{stockCode}` 只指向 `money=0` 的最近完整非空快照。
  - 先读 `latest` 再读 `all-day:v2:{sessionDate}:...`；指针缺失才取头页解析 sessionDate。
  - 无可解析日期的 `Total=0/List=[]` 写 `empty:v1:{cacheDate}:{stockCode}:0` 短 TTL，不能覆盖非空 `latest`。
- [ ] 写失败测试：周末/节假日优先读上一 `sessionDate` stale；空头页不触发完整重建、不覆盖 `latest`。
- [ ] 写失败测试：`off/prepend-device-snapshot` 的分页中 `Total` 变化是硬失败；`prepend-logical` 只允许按合同处理增长。
- [ ] 运行 Task 1 测试，预期全部通过。

## Task 3：实现增量头部刷新

- [ ] 写失败测试：旧缓存 `Total=17044`，新头页 `Total=17054`，只新增 10 条且只请求 1 个上游页。
- [ ] 写失败测试：`Total` 未变且头部序列一致，不重建全量。
- [ ] 写失败测试：`Total` 下降或偏移 `delta` 后的 20 行重叠不一致，触发完整重建。
- [ ] 写失败测试：`prepend-device-snapshot` 任一增量页 `Total` 变化时不合并；`prepend-logical` 允许增长并按逻辑偏移重试，但下降或同一逻辑页变化超过 2 次时不合并。失败均不更新 `fetchedAt`，并增加单 key 增量失败计数。
- [ ] 写失败测试：连续 2 次增量失败，或交易时段缓存年龄超过 60 秒时，请求一次受冷却保护的完整重建；完整重建失败仍保留旧缓存。
- [ ] 写失败测试：增量模式的 full rebuild 同 key 60 秒内最多一次；默认 `off` 模式仍为 300 秒。
- [ ] 写失败测试：prepend-only 门禁关闭时不执行 delta 合并，只按 300 秒冷却进行完整重建。
- [ ] 实现 `delta + min(20, cachedRows.Count)` 覆盖页读取、连续原始数组重叠校验和前缀合并。
- [ ] 禁止按单行 hash 去重，避免误删合法重复成交。
- [ ] 历史审计不使用 `setInterval`：普通 load/stale refresh 发现距上次审计满 5 分钟时，最低优先级入同一 scheduler；队列忙时跳过，用户请求不等待。
- [ ] 收盘后的第一次普通请求触发一次完整对账；没有请求时不启动独立任务。
- [ ] 运行：

```powershell
node --test proxy-server/__tests__/longhuBigOrderCache.test.mjs
```

预期：增量、重建和重复行测试通过。

## Task 4：接入 TTL、stale 和风控

- [ ] 在 `PROXY_CACHE_TTLS.bigOrder` 增加 `longhuPage`、`longhuAllDay`、`longhuEmpty`。
- [ ] 在 `proxyCache.js` 为 `LayeredProxyCache` 写失败测试：L1 miss/L2 hit 会回填 L1；L2 运行中抛错会退回 L1；成功 loader 同时写两层。
- [ ] 写失败测试：L1 stale 与 L2 fresh 同时存在时必须选择 L2 fresh。
- [ ] 写失败测试：fresh hit 不访问上游；两个并发 miss 只执行一个 loader。
- [ ] 写失败测试：stale 立即返回并启动一次后台刷新。
- [ ] 写失败测试：Redis 不可用时使用 `ProcessMemoryCache`。
- [ ] 写失败测试：所有 Longhu 上游操作共享全局 semaphore，两只股票同时 stale 时最大并发仍为 1。
- [ ] 写失败测试：冷 miss、头刷、历史审计共用一个最多 4 项的有界队列；构造大量不同股票 stale 时队列不增长。
- [ ] 写失败测试：队列满时审计丢弃、头刷继续返回 stale、冷 miss 返回 `big_order_refresh_busy`。
- [ ] 写失败测试：连续 3 次 403/429/网络失败后触发全源 breaker 60 秒。
- [ ] 写失败测试：连续 3 次短页/Total 漂移/单股 errcode 只冷却对应 `{stock,money}`，其它股票仍可刷新。
- [ ] 写失败测试：单次 45 秒重建预算耗尽只进入对应 key 冷却，不增加全源 breaker 计数；单个 POST 网络超时才计入全源失败。
- [ ] 实现 `LayeredProxyCache.pending` 和 `LonghuRequestScheduler`：running=1、queued=4、等待 timeout=8s、三档优先级、同 key/type 去重。
- [ ] 为 BigOrder 创建专用 L1：all-day 24 entries/96MB，page 128 entries/32MB。
- [ ] 扩展 `ProcessMemoryCache` 构造参数 `maxBytes/maxValueBytes/estimateSize`，默认无限制以保持既有调用方行为；BigOrder 每次写入只做一次 `Buffer.byteLength(JSON.stringify(value), 'utf8')` 并把字节数保存在 entry，读取不重复 stringify。
- [ ] 写失败测试：L1/L2 单 value 超限时跳过对应写入但仍返回成功响应。
- [ ] 写失败测试：统一队列超过 4 或等待超过 8 秒时按任务类型返回/丢弃，不继续排队。
- [ ] 运行目标 proxy 测试。

## Task 5：新增结构化端点并保护旧合同

- [ ] 在 `bigOrder.js` 新增：

```text
GET /api/big-order/longhu/all-day
```

- [ ] 写路由测试断言 `ok/source/stockCode/sessionDate/fetchedAt/servedAt/data.List/data.Total` 和 `dragonMeta`。
- [ ] `dragonMeta.cache` 增加 `ageSeconds/uiStale`，`dragonMeta.refresh` 增加 `inProgress`；technical `cache.stale=true` 且年龄仅 12 秒时，交易时段 `uiStale` 仍为 false。
- [ ] 写路由测试：新端点只允许 `money=0`；旧路由保持当前 numeric money 兼容，不新增 allowlist 400。非零 money 不写 canonical `latest/all-day`。
- [ ] 让旧 `/api/big-order/all-day` 在 `money=0` 时委托 canonical 服务并继续返回未包裹的 `{ List }`；非零 money 走兼容串行分页器，不读写 canonical `latest/all-day`。
- [ ] 让旧 `/api/big-order/main-monitor` 使用页缓存，继续返回未包裹的 Longhu 顶层字段。
- [ ] 锁定旧路由错误合同：400 继续使用 bad-request envelope；上游失败继续 HTTP 200 degraded envelope，不伪装原始成功。
- [ ] 更新 `openapi.js` 和 docs 测试。
- [ ] 运行：

```powershell
node --test proxy-server/__tests__/longhuBigOrderCache.test.mjs proxy-server/__tests__/thsBigOrder.test.mjs proxy-server/__tests__/docs.test.mjs
```

## Task 6：THS detail 改为 Redis 优先

- [ ] 写失败测试：注入可用 Redis cache 时 `/ths-detail` 使用 Redis，第二次请求不访问上游。
- [ ] 写失败测试：Redis stale 立即返回并后台刷新；Redis disabled 或运行中断线时使用 runtime cache。
- [ ] 写失败测试：THS envelope 的 `sessionDate` 优先取上游显式交易日，其次取 `pricechange`/分时完整日期，再取带完整日期的 order row；只有 HH:mm:ss 时返回 null，不能使用服务器自然日猜测。
- [ ] 把 route cache 从固定 `runtimeCache` 改成同一 `LayeredProxyCache`。
- [ ] THS key 显式升级为 `big-order:ths-detail:v2:{cacheDate}:{stockCode}`；本任务不再承载 Longhu `latest` 读路径。
- [ ] 在 THS 结构化 envelope 中返回 `sessionDate` 和日期诊断；无法确认日期仍可返回数据，但 C# 不得把它存为跨日 last-good 或推进语音 tracker。
- [ ] 更新 THS parser/client：权威日期存在时，所有只有 HH:mm:ss 的 order 统一写成 `sessionDate.Date + parsedTimeOfDay`；原始完整日期与权威日期冲突的行跳过并记录 issue。写测试把进程“当前自然日”改成不同夹具语境后重复解析同一 payload，断言 order `Time`、指纹和增量识别结果不变。
- [ ] 运行 `thsBigOrder.test.mjs`。

## Task 7：WinForms 使用缓存入口

- [ ] 更新 C# 测试：Longhu 正常刷新只调用 `/api/big-order/longhu/all-day`，不调用直连 POST。
- [ ] 更新 C# 测试：THS orders 和 Longhu 模式下的 THS summary 正常刷新都先调用 proxy `/api/big-order/ths-detail`；quote/minute/limit-up 保持现有 direct-first/fallback。
- [ ] 为 Longhu 聚合端点使用独立 `HttpClient`，`Timeout=60s`；现有共享客户端继续 15 秒。写测试确保不能通过整体放宽 `_httpClient.Timeout` 解决。
- [ ] 更新测试：`cache.stale` 不直接映射 `DataFreshness.Stale`；交易时段使用 `cache.uiStale`，12 秒 technical stale 仍为 Fresh，超过 30 秒才为 Stale。
- [ ] 更新测试：fresh THS/Longhu 大单使用 `ProxyPrimary`，状态文本为“代理通道: 大单”；不得显示“代理降级: 大单”。
- [ ] 更新 `SourceStatusFormatter` 优先级：`Failed/Missing > Stale > ProxyFallback > ProxyPrimary > Direct`。
- [ ] 更新测试：proxy 失败时不自动直连 Longhu；last-good 必须显式匹配 envelope `sessionDate`、股票和数据源，不能用 `fetchedAt.Date` 猜交易日；跨日/跨源不可复用。
- [ ] 修改 `LonghuBigOrderSourceClient` 和 `ThsBigOrderSourceClient` 解析新 envelope，把可靠交易日传入 `BigOrderSourceData.SessionDate`；不得把 `DateTime.Today` 当 fallback。
- [ ] 在 `MarketSnapshot` 增加可空 `BigOrderSessionDate`，由 Provider 从本轮 orders 源传入；last-good 和语音只在该值存在时执行跨日匹配。
- [ ] 为大单 orders/summary 增加明确的 proxy-primary 加载路径；不得继续复用 `LoadDirectFirstAsync`。quote/minute/limit-up 保持原行为。
- [ ] 修改成功缓存判断，使 `Direct`、`ProxyPrimary`、`ProxyFallback` 都是可保存的完整成功结果。
- [ ] 保留 direct 方法供独立诊断测试，但不进入正常自动 fallback。
- [ ] 运行：

```powershell
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release --no-restore
```

预期：BigOrder/Longhu/切源相关测试通过；既有固定日期涨停夹具若仍失败，应单独记录。

## Task 8：WinForms 只播报本轮新增信号

- [ ] 在 `tools/THSBigOrder.Tests/LonghuFeatureTests.cs` 先写失败测试，直接测试 `BigOrderAnnouncementTracker`：
  - 第一次 `Observe("002963", Ths, 2026-07-17, fullList)` 返回空，只建立基线。
  - 同 scope 下一份完整列表新增 3 条时返回 3 条，并按时间从早到晚排列。
  - 完全相同的 `Time/Type/Volume/Amount/Price` 从 2 次增加到 3 次时只返回 1 条；之后暂时降回 2 次再恢复 3 次时返回 0 条。
  - 股票、数据源或 `sessionDate` 任一变化时，新 scope 第一次观察返回空。
- [ ] 运行测试并确认 RED：当前没有 `BigOrderAnnouncementTracker`。
- [ ] 新建 `tools/THSBigOrder/BigOrderAnnouncementTracker.cs`：

```csharp
internal sealed class BigOrderAnnouncementTracker
{
    public IReadOnlyList<BigOrderItem> Observe(
        string stockCode,
        BigOrderDataSource dataSource,
        DateTime sessionDate,
        IReadOnlyList<BigOrderItem> currentOrders);

    public void Reset();
}
```

  指纹精确包含 `Time.Ticks/Type/Volume/Amount/Price`；状态保存每个指纹在当前 scope 见过的最大次数，不因当前快照数量下降而回退。scope 变化时用当前完整列表建立新基线并返回空。
- [ ] 重跑 tracker 测试并确认 GREEN。
- [ ] 为 `VoiceService` 增加可测试的文本构建函数和批次入口：

```csharp
internal enum BigOrderAnnouncementType { Ignite, Smash, BuyActive, GoodSupport }

internal sealed class BigOrderAnnouncement
{
    public BigOrderAnnouncementType Type { get; set; }
    public double Amount { get; set; }
}

internal interface IBigOrderVoice
{
    bool Enabled { get; set; }
    void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements);
    void CancelPending();
}

internal interface ISpeechQueue : IDisposable
{
    void SpeakAsync(string text);
    void CancelAll();
}

internal static string BuildBatchText(IReadOnlyList<BigOrderAnnouncement> announcements);
public void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements);
public void CancelPending();
```

  `BuildBatchText` 按输入顺序生成“点火 500万，砸盘 800万，买活跃，承接好”；生产 `SystemSpeechQueue` 只封装 `_synth.SpeakAsync()` 和 `_synth.SpeakAsyncCancelAll()`。`AnnounceBatch` 每轮最多调用一次 `queue.SpeakAsync(batchText)`，不能调用 `CancelAll()`。只有 `CancelPending()` 和 `Dispose()` 可以取消队列。
- [ ] 写失败测试并验证：
  - 四类文本和金额格式保持现状。
  - 三条输入全部出现在一个 batch text 中且顺序不变。
  - 空输入不提交语音。
- [ ] 为 `VoiceService` 注入 fake `ISpeechQueue`，写失败测试证明：一个 batch 只调用一次 SpeakAsync 且 cancel=0；连续两个 batch 的文本按 FIFO 提交且 cancel 仍为 0；`CancelPending()` 只调用一次 CancelAll；`Dispose()` 会 CancelAll 后 Dispose。
- [ ] 修改 `MainForm.BindSnapshot()`，固定执行顺序：先对完整 `_allData` 调用 `CalculateMarkers`，再用可信 `BigOrderSessionDate.Date` 调 tracker，之后只对 tracker 返回的新订单调用 `OrderFilter.Apply(newOrders, _currentMoney, _orderSide, _specialFilter)`，最后映射并提交 batch。`BigOrderSessionDate` 缺失时跳过 Observe/播报。
- [x] 只把筛选后具有 marker 的新增订单映射为 announcement。`_specialFilter` 为空时单条优先级保持 `点火 > 砸盘 > 买活跃 > 承接好`；非空时只生成与 `_specialFilter` 同名的 announcement。按时间从早到晚一次调用 `AnnounceBatch`。删除 `_filteredData.Take(10)`、首条 `return` 和 `_announcedItems` 清空/重播逻辑。
- [x] marker 采用事件归因：按 `big-order-event-attribution-design.md` 的连续订单流、方向纯度、价格冲击/保留和确认窗口规则生成点火/砸盘；买活跃/承接好只附着已确认主事件，不挂到后续普通订单。
- [x] 语音关闭时仍推进 tracker 基线但不提交 batch；`chkVoice` 从关闭变为开启时设置 re-enable barrier。只有下一份“generation 有效 + Fresh/Stale 完整 orders + 可信 `BigOrderSessionDate` + `tracker.Reset()/Observe` 成功”的 accepted snapshot 才只建基线并清除 barrier。日期缺失、Failed/Missing、迟到或 Observe 失败都保留 barrier。`chkVoice` 关闭、股票代码/热榜切股、数据源切换和窗体退出时调用 `CancelPending()`。切股/切源后的首份快照由新 scope 自动建立基线，不播全天历史。
- [ ] 保留现有勾选语音的测试播报行为，但测试播报不能改变订单 tracker 基线。
- [ ] 增加 MainForm 回归测试：
  - 初次绑定有历史信号不播。
  - 后续一次新增 3 条有效信号，提交一个包含 3 条的批次。
  - 调整金额/买卖/特殊筛选后不播旧单；之后新单按当前筛选条件播。
  - 特殊筛选“买活跃”下，同时具有“点火+买活跃”的新增订单播“买活跃”；清空特殊筛选后同类新单按默认优先级播“点火”。
  - 语音关闭期间有正常刷新时新增订单不播，重新打开后不补播。
  - 语音关闭期间零刷新，以及关闭时请求在重新开启后才完成，两种情况下 re-enable 后第一份 accepted snapshot 都只建基线；再新增一条才播。
  - re-enable 后先绑定一份 `BigOrderSessionDate=null` 的可显示快照时不清除 barrier；随后第一份可信日期完整快照仍只建基线。
  - 旧订单 marker 重算后变化不播。
  - 切股、切源和迟到响应不播旧 scope。
- [ ] 让 `VoiceService` 实现 `IBigOrderVoice`，并把 `MainForm` 的内部测试构造函数扩展为可注入 `IBigOrderVoice`；测试使用 recording fake 断言批次数量、文本候选和取消次数，不实际调用扬声器。生产无参构造仍创建真实 `VoiceService`。
- [ ] tracker 内部把传入日期立即归一化为 `sessionDate.Date`，scope 比较不受时间分量或 `DateTime.Kind` 影响；补同日不同 Kind/时间分量不重建基线的测试。
- [ ] 运行：

```powershell
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release --no-restore
dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore
```

预期：增量语音、Longhu、切源和构建全部通过；不得以只检查最新 N 条或限制播报数量换取测试通过。

## Task 9：同步合同文档与部署顺序

- [ ] 更新 `docs/API/ths-l2-api-analysis.md`：POST、`st<=200`、全量 45 秒预算、专用 60 秒客户端、旧 numeric money 合同。
- [ ] 更新双数据源 design/plan：保留“当前已实现 direct-first”历史事实，同时明确 Redis 改造完成后 Longhu 正常链路变为 proxy-primary、direct 仅诊断。
- [ ] 同步语音合同：首次/切股/切源只建基线、完整列表差分、当前筛选、四类 marker、单批次全量播报。
- [ ] 更新 `proxy-server/openapi.js`：Longhu/THS 新 envelope 的 `sessionDate/uiStale`，THS 日期不可确认时为 null，旧路由 money 合同不收紧。
- [ ] 记录本地同批部署顺序：
  1. 停止旧 exe 和 proxy。
  2. 更新并启动保留旧路由兼容的新 proxy。
  3. 构建并启动使用 `/longhu/all-day` 的新 exe。
  4. 不允许旧逐页 C# proxy fallback 与新 10 秒 page cache 长时间混跑，避免混龄页触发 `Total changed during pagination`。
- [ ] 运行 docs 测试和 Markdown 链接检查。

## Task 10：完整验证

- [ ] Proxy 目标测试：

```powershell
node --test proxy-server/__tests__/longhuBigOrderCache.test.mjs proxy-server/__tests__/thsBigOrder.test.mjs proxy-server/__tests__/docs.test.mjs
```

- [ ] Proxy 全量测试：

```powershell
cd proxy-server
npm test
```

- [ ] C# 测试和构建：

```powershell
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release --no-restore
dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore
```

- [ ] 静态检查：

```powershell
git diff --check -- proxy-server tools/THSBigOrder tools/THSBigOrder.Tests docs/ths-big-order-debug
git status --short
```

- [ ] 人工盘中验收：首次冷加载记录页数；10 秒内重复刷新确认 0 上游；出现新单后确认只抓头页；快速切源确认列表、红绿点和蓝线立即切换且无迟到覆盖。
- [ ] 人工验证首次冷 miss 的端到端耗时小于 60 秒；若超过 45 秒重建预算，必须在客户端超时前收到 stale/degraded，而不是 15 秒 `TaskCanceledException`。
- [ ] 人工验证 6 秒轮询下 technical stale 不引起状态栏闪烁；断开上游超过 30 秒后才显示“数据陈旧: 大单”。
- [ ] 人工盘中制造或等待一轮出现 3 条以上有效新信号，确认只播本轮新增、全部按时间顺序播出；重复刷新不重播。
- [ ] 人工确认切股、切源、重新打开语音时不补播全天历史，普通定时刷新不会取消上一批尚未播完的新单。
- [ ] 人工确认 THS 与 Longhu 状态都显示正确交易日；THS 日期无法确认的诊断样本不会触发语音或跨日 last-good。
