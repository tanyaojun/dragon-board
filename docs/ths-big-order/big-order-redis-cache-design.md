# BigOrder Redis TTL 缓存改造设计

> 日期：2026-07-16
>
> 状态：方案（已合并外部对抗性审计修订）
>
> 目标：降低 THS/Longhu 上游请求频率和 Longhu 全量分页风控风险，同时保持数据可解释、可降级、可测试。

## 1. 核心目标

1. WinForms 正常流量统一进入本地 `proxy-server`，不再用“直连失败后才走代理”绕过缓存。
2. Redis 是可丢弃、可重建的实时读缓存，不是大单事实库；使用 L1 进程缓存 + L2 Redis，Redis 运行中断线时仍可退回 L1。
3. Longhu 冷启动只做一次完整串行分页；通过 prepend-only 验证门禁后，后续根据 `Total` 增量刷新，稳态通常只访问一个头页。
4. stale 数据可以立即返回并后台刷新；上游失败时不清空已有同股同源数据。
5. 任何不完整或无法校验的分页结果都不能覆盖完整缓存。
6. WinForms 对完整 orders 快照做本地增量识别，只播报本轮新增且符合当前筛选条件的“点火/砸盘/买活跃/承接好”，不固定截断条数，也不重播历史数据。

## 2. 方案对比

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 仅缓存 `/main-monitor` 分页 | 改动最小，重复相同页可命中 | TTL miss 后仍需约 86 个上游请求；WinForms 直连会绕过缓存 | 不采用为主方案 |
| 全天快照 + 经验证的增量头部刷新 | 首次全量，之后通常 1 页；切源和重复刷新快速；复用现有 Redis | 必须先验证 DeviceID 快照和 prepend-only 合同 | 推荐 |
| 独立后台采集器/订阅器 | UI 完全不触发上游，可集中限流 | 新增股票订阅、生命周期、调度和空闲清理，超过当前需求 | 暂不采用 |

## 3. 推荐架构

```text
THSBigOrder.exe
  │
  ├─ THS orders/summary ───────► proxy /api/big-order/ths-detail
  │                                  │
  │                                  ├─ L1 ProcessMemoryCache
  │                                  ├─ L2 Redis
  │                                  └─ stale + 后台刷新
  │
  └─ Longhu orders ────────────► proxy /api/big-order/longhu/all-day
                                     │
                                     ├─ L1/L2 全天完整快照
                                     ├─ fresh hit：0 次上游
                                     ├─ stale：立即返回 + 增量刷新
                                     └─ cold miss：st=200 串行全量
```

职责边界：

- WinForms 只消费结构化 proxy 响应和维护短期同股同源 last-good，不连接 Redis。
- `proxy-server` 是唯一正常上游入口，负责缓存、分页、限流、熔断和响应元数据。
- L1/L2 都只缓存完整验证过的结果；两层写入、逐层读取，由同一个 single-flight facade 控制上游 loader。
- Longhu direct POST 保留给测试和人工诊断，不作为自动 fallback。
- C# 新增正常态 `DataTransport.ProxyPrimary`。大单 fresh 结果显示“代理通道: 大单”，不能继续标记成 `ProxyFallback`/“代理降级”。
- proxy 内所有 Longhu 上游请求统一改为 POST `application/x-www-form-urlencoded`；一次分页聚合复用同一个 DeviceID。
- proxy 的 `refresh.newRows` 只用于缓存诊断，不作为语音播报真相源。WinForms 必须以已经通过 generation 校验、实际绑定到当前界面的完整 orders 快照做本地增量识别。

## 4. 与现有两套 Redis 方案的关系

| 既有方案 | 可复用部分 | BigOrder 不照搬的部分 |
|---|---|---|
| THS L2 主力资金 | 短 TTL、stale 立即返回、后台刷新、低并发、连续失败熔断 | 主力资金按股票独立取一条摘要；Longhu 需要维护同股完整全天列表和增量合并 |
| RankTrend Redis | Redis 不是事实源、namespace 隔离、序列化失败 fail-open、响应携带 cache 诊断 | RankTrend 通过 ingest 反向索引精确失效；BigOrder 没有写入事件，使用日期隔离和 TTL，不建反向索引 |

BigOrder 缓存的是上游原始/规范化读模型，不缓存 UI 统计、蓝线、红绿点或点火/砸盘结果。客户端每次仍从 orders 重算展示，避免缓存派生值与筛选条件错位。

## 5. API 与兼容策略

### 5.1 新增 THSBigOrder 专用端点

```text
GET /api/big-order/longhu/all-day?stockCode=000938&money=0
```

响应使用结构化 envelope：

```json
{
  "ok": true,
  "source": "longhu-big-order-all-day",
  "stockCode": "000938",
  "sessionDate": "2026-07-16",
  "fetchedAt": 1784210400000,
  "servedAt": 1784210408000,
  "data": {
    "List": [],
    "Total": 17044,
    "errcode": "0",
    "dragonMeta": {
      "cache": {
        "store": "redis",
        "hit": true,
        "stale": false,
        "ageSeconds": 8,
        "uiStale": false,
        "upstreamCalled": false,
        "ttlSeconds": 10
      },
      "refresh": {
        "mode": "cache-hit",
        "inProgress": false,
        "pagesFetched": 0,
        "newRows": 0
      }
    }
  }
}
```

`sessionDate` 是 orders 所属交易日，不能用 `fetchedAt` 推断。Longhu 取最新合法 row 的完整日期；THS detail 也必须在 proxy envelope 中返回 `sessionDate`，权威顺序为上游显式交易日、`pricechange`/分时序列中的完整日期、带完整日期的 order row。不得用代理自然日、`cacheDate` 或 C# `DateTime.Today` 猜测。THS order 只有 HH:mm:ss 时，解析后的 `BigOrderItem.Time` 必须规范化为 `sessionDate.Date + timeOfDay`；原始 order 自带完整日期但与权威日期冲突时，该行视为无效。这样同一交易日缓存跨午夜重复解析时，订单指纹不会整体变化。无法确认日期时返回 `null` 并附诊断原因，WinForms 可以显示数据，但不得用该快照推进跨日 last-good 或语音 tracker。`fetchedAt` 表示缓存中数据最后成功接触上游的时间，`servedAt` 表示本次响应时间。

`cache.stale` 只表示数据已经越过 Redis/L1 的 fresh TTL，属于 SWR 技术状态；它不能直接映射为 WinForms 的 `DataFreshness.Stale`。proxy 根据 `servedAt - fetchedAt` 和当前时段计算 `cache.ageSeconds/uiStale`：

- 交易时段：年龄超过 30 秒才 `uiStale=true`。
- 盘前和午间休市：年龄超过 300 秒才 `uiStale=true`。
- 收盘后/周末：同 `sessionDate` 数据年龄超过 12 小时才 `uiStale=true`。

这样 6 秒轮询命中 10 秒 TTL 后的短暂 SWR stale 时，UI 不会在“代理通道”和“数据陈旧”之间闪烁；上游长期失败时仍会按真实数据年龄提示陈旧。

### 5.2 旧路由保持兼容

- `/api/big-order/main-monitor` 保持顶层 Longhu 原始字段，不包 envelope；内部增加短 TTL 分页缓存。
- `/api/big-order/all-day` 保持 `{ List: [...] }` 兼容合同，内部委托同一全天快照服务。
- 旧 `/main-monitor?limit=500` 可以继续接受，但服务端必须拆成最多 200 条的上游子请求，不能把 `st=500` 原样发给 Longhu。
- 新 `/longhu/all-day` 只允许 `money=0`，THSBigOrder 的 30/50/100/300/500/700/1k 筛选继续在本地完整 orders 上完成，避免放大缓存 key。
- 旧路由继续保持当前 numeric `money` 透传合同，不新增 allowlist 或 400 拒绝；现有前端 `BigOrderService.fetchAllDay()` 仍会把调用方传入的 number 传给 `/all-day`。
- 只有 canonical `money=0` 使用新的全天快照和 `latest` 指针；旧路由的其它 `money` 只走兼容分页路径，不得写入或覆盖 canonical 全天快照。
- 旧调用方不需要同步升级；THSBigOrder 新客户端只使用结构化新端点。

## 6. Longhu 全天快照与增量刷新

### 6.1 实施前合同门禁

增量方案不能只凭一次样本假设上游 append-only。实现前必须完成三项实测：

1. 对比 GET 与 POST，确认正式路径固定使用 POST 表单和精确字段。
2. 固定 DeviceID 连续分页，观察活跃股票在 15 秒内的 `Total` 是否保持同一快照；如果保持，记录为 snapshot token 合同。
3. 对同股连续采样，验证当 `newTotal > oldTotal` 时：

```text
newList[delta : delta + oldTotal] == oldList
delta = newTotal - oldTotal
```

至少覆盖高活跃、低活跃股票和早盘/午后。只有该门禁通过，才能启用任一增量模式。

运行模式必须显式且 fail-closed：

```text
BIG_ORDER_LONGHU_INCREMENTAL_MODE=off | prepend-device-snapshot | prepend-logical
```

- 默认 `off`：不做 delta 合并，按 300 秒冷却进行受控完整重建。
- `prepend-device-snapshot`：自动化 fixture 覆盖了 prepend-only 和固定 DeviceID 合同；只有真实盘中门禁通过后才允许 delta 合并，完整重建中 Total 变化直接失败。
- `prepend-logical`：自动化 fixture 覆盖了 prepend-only 的逻辑偏移路径；只有真实盘中门禁通过后才允许启用，允许 Total 增长并用逻辑偏移重试。
- 不能根据单次运行结果自动从 `off` 升级；启用必须有 API 分析文档和回归 fixture 证据。

在 `prepend-logical` 模式：

- prepend-only 门禁通过时，使用逻辑快照偏移：首次记录目标 `T0`，抓取旧快照逻辑偏移 `O` 时，按当前总量估计请求 `Index = O + (currentTotal - T0)`。
- 每页响应若 `Total` 与请求前估计不同，用新差值重试该逻辑页，单页最多 2 次。
- 如果任一页出现 `currentTotal < T0`，当前逻辑快照尝试立即失败，不能产生负偏移或继续合并。
- 完整重建总预算 45 秒；该上限覆盖 `Total≈17044` 时约 86 页的 100~200ms 页间延迟和 RTT 余量。仍无法稳定时不写缓存，返回已有 stale；无 stale 返回 degraded。
- 45 秒预算使用 `AbortController` 贯穿当前完整重建的所有上游请求；预算耗尽时中止活动请求，不能只停止 await 而让后台分页继续占用 scheduler。

在默认 `off` 模式，或 prepend-only 门禁失败时：

- 禁用 delta 合并。
- 冷启动/完整重建使用固定 DeviceID 且要求 Total 稳定；最多重启 2 次、所有尝试共享 45 秒总预算。
- 仍不稳定时不写缓存，返回 stale/degraded。
- 交易时段完整重建最短间隔设为 300 秒，其余请求只返回 stale 并等待下一次受控重建。
- 非交易时段（收盘后、周末）完整重建最短间隔为 6 小时：闭市数据不再变化，stale 命中不允许整夜重复全量分页；配合收盘后 1800s/604800s TTL，每晚最多 1~2 次自愈性重建。
- 不得为了“实时”恢复并发分页。

启用任一增量模式后，因完整性失败触发的 full rebuild 也受单 key 60 秒最短间隔保护；默认 `off` 仍使用更保守的 300 秒间隔。

### 6.2 冷启动

1. proxy 使用 POST 表单，固定上游 `st=200`。
2. 单次加载复用同一 `DeviceID`。
3. 从 `Index=0` 串行请求，页间保留 100~200ms 间隔。
4. `Total` 必须存在；`off` / `prepend-device-snapshot` 模式下，同一完整重建内所有页的 `Total` 必须严格一致，变化即硬失败。
5. 仅在累计行数等于 `Total` 后写入 Redis。
6. DeviceID 不能提供稳定快照但 prepend-only 已验证时，按 6.1 的逻辑偏移构造目标 `T0` 快照。
7. 失败条件按 mode 区分：
   - `off` / `prepend-device-snapshot`：中页 Total 变化、短页截断、超量或解析全坏时不写。
   - `prepend-logical`：`currentTotal < T0`、单逻辑页超过 2 次重试、总预算超过 45 秒、偏移/重叠校验失败、短页截断、超量或解析全坏时不写；正常 Total 增长不算失败。

冷 miss 采用同步交付，不增加 202/轮询状态机：

- `LonghuRequestScheduler` 最多等待 8 秒进入执行。
- 完整重建最多执行 45 秒。
- WinForms Longhu 聚合请求使用独立 `HttpClient`，超时 60 秒；现有 quote/minute/THS 等共享客户端继续保持 15 秒。
- 因此设计上限为 53 秒，小于客户端 60 秒。排队或重建预算超限时，接口必须在预算内返回 stale/degraded，不能让无接收者的请求继续占用队列。

### 6.3 稳态增量

通过 prepend-only 门禁后，缓存 value 保存：

```text
sessionDate
stockCode
money
total
list                  # 最新在前的完整数组
fetchedAt
headFingerprint       # 前若干行序列指纹，仅用于校验
integrityMode          # full / incremental-verified
```

刷新步骤：

1. 请求 `Index=0&st=200`，读取 `newTotal`。
2. 如果 `newTotal == cachedTotal`，比较头部序列；一致则只更新成功刷新时间。
3. 如果 `newTotal > cachedTotal`，计算 `delta = newTotal - cachedTotal`。
4. 获取足以覆盖 `delta + overlapProbe` 的头部页，`overlapProbe = min(20, cachedRows.Count)`。
5. `prepend-device-snapshot` 要求所有增量页的 `Total` 与头页一致；`prepend-logical` 允许后续页 `Total` 增长，并按 `Index = logicalOffset + (currentTotal - headTotal)` 重算偏移后重试同一逻辑页，单页最多重试 2 次。两种模式遇到 `Total` 下降都立即失败。
6. 校验新响应在偏移 `delta` 处的连续序列与旧缓存前 `overlapProbe` 行一致。
7. 校验通过后，仅把前 `delta` 行插入旧列表；缓存总量更新为 `newTotal`。
8. `Total` 下降、sessionDate 变化或重叠不一致时立即请求一次受冷却保护的完整串行重建。
9. 固定快照模式的 `Total` 变化，或 logical 模式的下降、重试超限，以及任一模式的短页、重叠失败或结果不完整，都先保留旧缓存；连续 2 次增量失败，或交易时段 `fetchedAt` 年龄超过 60 秒时，请求一次受冷却保护的完整重建。完整重建失败仍不得覆盖旧缓存。
10. 任一完整或增量成功都会清零该 key 的增量失败计数。

该算法不依赖“单行一定唯一”。偏移由 `Total` 差确定，重叠使用连续原始数组序列比较，避免简单哈希去重误删同秒同价同量的合法重复成交。

即使门禁通过，也增加低频历史漂移审计：

- 不新增 `setInterval`、守护进程或独立计划任务。普通 `loadAllDay`/stale 刷新发现距上次历史审计已满 5 分钟时，才把一个轮转历史页作为最低优先级任务送入同一 scheduler。
- 审计任务与缓存对应最多 200 行比较；队列忙或已满时直接跳过，本次用户请求不等待。
- 发现深层修订/重排时标记缓存 stale，并触发受冷却保护的完整重建。
- 收盘后的第一次普通请求触发一次完整对账；如果收盘后没有请求，不额外启动定时任务。对账成功后 `integrityMode=full`。

### 6.4 WinForms 增量语音播报

当前语音逻辑同时存在三个漏播点：

1. 只检查 `_filteredData` 最新 10 条。
2. 命中第一条后立即 `return`，一轮刷新最多提交一条。
3. `VoiceService` 每次调用 `SpeakAsyncCancelAll()`，后提交的语音会取消前一条。

Redis 改造后 proxy 返回的仍是完整全天快照，不应把“完整快照”直接当作“本轮新增”。WinForms 增加独立的 `BigOrderAnnouncementTracker`，合同如下：

- scope 由 `stockCode + dataSource + sessionDate.Date` 构成；tracker 内部只比较日期部分并忽略 `DateTime.Kind`。首次加载、切换股票、切换 THS/Longhu 或交易日变化时，只用当前完整列表建立基线，返回 0 条播报候选。`sessionDate` 不可信或缺失时不推进 tracker、不播报。
- tracker 在每个已通过 `RefreshCoordinator` generation 校验的完整快照上运行。迟到响应、失败/Missing 响应和未绑定到界面的响应不能推进基线。
- 即使语音关闭，也继续推进已接受快照的观察基线；此外，语音从关闭切换为开启时设置 re-enable barrier，下一份具有可信 `sessionDate` 且完整 orders 成功 Observe 的 accepted snapshot 强制重建当前 scope 基线并返回 0 条，完成后才清除 barrier。日期缺失、Failed/Missing、迟到或无法 Observe 的响应都必须保留 barrier。这样即使关闭期间没有成功刷新，或关闭时发出的请求在重新开启后才完成，也不会补播关闭期间的历史。
- 增量识别在完整 `_allData` 上进行，不能在 `_filteredData` 上做差分。识别出新订单后，再按当前金额阈值、买/卖页签和特殊标记筛选；用户改变筛选条件本身不能让旧订单重新变成“新增”。
- 单行没有可靠全局唯一 ID，不能继续使用“时间+类型+金额”的 `HashSet`。使用 `Time ticks + Type + Volume + Amount + Price` 构成订单指纹，并保存每个指纹在当前 scope 历史上见过的最大出现次数。
- 指纹采用出现次数而不是集合布尔值：同秒、同价、同量的合法重复成交增加一条时，仍能识别并播报新增的那一个；历史修订导致行暂时消失后再出现时，不因计数下降而重播。
- marker 规则以 `big-order-event-attribution-design.md` 为准：完整列表每次重算窗口归因，确认窗口必须在最新成交时间严格越过候选 `+10秒` 后才冻结；确认后的 marker 行才进入 tracker 语音候选，附加 marker 只写回对应点火/砸盘行。
- 点火/砸盘使用 10 秒连续订单流、同向主动纯度、3bp 价格冲击和 8~10 秒至少 50% 价格保留；买活跃/承接好分别只归属于已确认点火/砸盘事件，不再采用旧的单笔金额或前后 6 秒比较规则。
- 四类语音条件保持现状，不扩大为所有普通大单播报。未选择特殊 marker 筛选时，单条优先级为 `点火 > 砸盘 > 买活跃 > 承接好`；特殊筛选非空时，announcement 类型必须与当前筛选同名。例如同一新增订单同时是“点火”和“买活跃”，当前筛选为“买活跃”时必须播“买活跃”，不能因全局优先级改播“点火”。
- 同一轮的全部候选按成交时间从早到晚组成一个文本批次，一次提交给 `SpeechSynthesizer`；不得按条调用后互相 `CancelAll`，也不得固定 `Take(2)`/`Take(10)`。
- 不设置数量上限。若一轮有多条新增信号，全部进入该批次；后续刷新产生的新批次由 synthesizer 顺序排队。
- 股票/数据源切换、关闭语音和窗体退出时允许取消旧 scope 尚未播放的队列，避免切换后继续播报上一只股票；普通定时刷新不能取消已排队的新单。

推荐接口保持最小：

```csharp
IReadOnlyList<BigOrderItem> Observe(
    string stockCode,
    BigOrderDataSource dataSource,
    DateTime sessionDate,
    IReadOnlyList<BigOrderItem> currentOrders);

void VoiceService.AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements);
void VoiceService.CancelPending();
```

`VoiceService` 通过最小 `IBigOrderVoice` 接口注入 `MainForm`，内部再依赖可替换的 `ISpeechQueue` 适配器封装 `SpeechSynthesizer.SpeakAsync/CancelAll`，便于自动验证 FIFO 和取消行为而不驱动真实扬声器。`BigOrderAnnouncement` 承载股票名、成交时间、主语音类型、金额和同一事件的附加 marker；格式化仍由 `VoiceService` 负责。`MainForm` 的固定顺序是：完整 `_allData` 计算 marker → tracker 识别新增 → 对新增应用当前 `OrderFilter` → 按特殊筛选/默认优先级映射 announcement → 单批次提交。不能在 marker 计算前 Observe，也不能把 UI 筛选或业务 marker 规则塞入语音服务。

## 7. Cache key 与 TTL

统一复用现有 `PROXY_REDIS_URL`、`PROXY_REDIS_KEY_PREFIX`、`ProxyRedisCache` 和 `ProcessMemoryCache`。新增轻量 `LayeredProxyCache` facade：

- L1 读取 `ProcessMemoryCache`，命中直接返回。
- L1 miss 后读取 L2 Redis。
- L2 命中时回填 L1。
- loader 成功后同时写 L1/L2；任一层写失败不影响响应。
- facade 自己维护 `pending`，保证跨两层仍只有一个 loader。
- `cache.store` 返回实际命中的 `memory` 或 `redis`。

```text
big-order:ths-detail:v2:{cacheDate}:{stockCode}
big-order:longhu:page:v2:{sessionDate}:{stockCode}:{money}:{index}:{limit}
big-order:longhu:all-day:v2:{sessionDate}:{stockCode}:{money}
big-order:longhu:latest:v1:{stockCode}
big-order:longhu:empty:v1:{cacheDate}:{stockCode}:0
```

Longhu `sessionDate` 优先取最新合法 row 的 datetime 日期，并要求同一快照所有行属于同一日期。`latest` 指针保存最近完整快照的 `sessionDate`：

- 盘前、周末和节假日先通过指针读取上一交易日完整快照并标记 stale，不按自然日重复冷重建。
- 新头页出现新日期后，创建新的 session key 并更新指针。
- `Total=0/List=[]` 没有可解析日期时写入基于上海自然日的 `empty` 短 TTL key，但不能覆盖指向非空完整快照的 `latest` 指针。
- canonical 全天快照只支持 `money=0`，因此 `latest` 不再包含冗余 money 维度。
- `latest` 指针 TTL 为 7 天；canonical 读请求先用该指针解析 sessionDate，指针缺失时先取头页再建立 key。
- 旧路由的非零 `money` 不使用 canonical `latest`；保持兼容分页行为。

THS detail 数据量小、TTL 短，可继续使用 Asia/Shanghai `cacheDate` 隔离跨日 stale。

建议 TTL：

| 数据 | 时段 | fresh TTL | stale TTL |
|---|---|---:|---:|
| THS detail | 交易时段 | 3s | 180s |
| Longhu all-day | 盘前 09:00~09:30 | 60s | 300s |
| Longhu page | 交易时段 | 10s | 120s |
| Longhu all-day | 交易时段 | 3s | 300s |
| Longhu all-day | 午间休市 | 60s | 900s |
| Longhu all-day | 收盘后/周末 | 1800s | 604800s |
| 合法空结果 | 交易时段 | 5s | 30s |

表中的 stale TTL 是当前时段的刷新/可用性策略窗口，不代表全天快照的物理删除时间。`all-day:v2` 在 L1/L2 统一物理保留 7 天，确保周末、节假日和跨自然日仍能通过 `latest` 找到上一交易日；命中后仍按当前时段、`sessionDate`、`fetchedAt` 和 `uiStale` 决定是否探测、刷新及向客户端标记陈旧。交易时段 `prepend-logical` 增量模式下，technical stale 请求会等待一次有界增量刷新并返回合并结果；增量失败才回退旧值，上游失败不得删除完整快照。

第一版不引入交易日历。工作日法定节假日按非交易时段处理：优先返回 `latest` 指向的上一交易日 stale，最多每 60 秒做一次低成本头页探测；空头页不能触发全天冷重建或覆盖 `latest`。

THSBigOrder 当前自动刷新间隔是 3 秒；交易时段 Longhu/THS fresh TTL 同步为 3 秒，stale 请求在增量模式下等待一次最新页合并，不再固定返回一轮旧快照。

完整 Longhu list 可能达到 1~3 MB。第一阶段不引入压缩，使用 BigOrder 专用容量：

- all-day L1：`maxEntries=24`、`maxBytes=96MB`、单 value 最大 8MB。
- page L1：`maxEntries=128`、`maxBytes=32MB`、单 value 最大 1MB。
- Redis all-day 单 value 最大 8MB，公共 page 缓存单 value 最大 1MB。
- `ProcessMemoryCache` 的 `maxBytes/maxValueBytes` 是可选能力，默认 `Infinity`，不改变其它缓存调用方。BigOrder 写入时只执行一次 `Buffer.byteLength(JSON.stringify(value), 'utf8')`，把结果保存在 entry 上；淘汰时直接扣减已记录字节数，不在每次读取时重复序列化。
- 构建 all-day 时不重复写内部 200 条子页；只有公共 `/main-monitor` 请求才进入 page cache。
- 超过单 value 上限时仍返回本次数据，但不写对应缓存层并记录诊断。

### 7.1 本地永久归档（2026-07-17 新增需求）

全天快照除 L1/L2 缓存外，作为数据资产永久保存到本地文件；Redis 仍保持"可丢弃、可重建的读缓存"定位，永久资产以磁盘文件为准。

- 落点：`proxy-server/data/big-order/{sessionDate}/{stockCode}.money{money}.json.gz`，内容为 `{sessionDate, stockCode, money, fetchedAt, data:{List,Total,errcode}}` 的 gzip JSON。目录在 `.gitignore` 中，不提交仓库。
- 触发：完整重建或增量合并成功、快照写入缓存的同一时刻异步归档；不新增守护进程、定时任务或质量门禁（完整性校验已由缓存写入前置条件承担）。
- 覆盖语义：同一 `{sessionDate, stock, money}` 临时文件 + rename 原子覆盖；收盘后最后一次重建自然成为该股当日终稿。合法空结果和无法解析 sessionDate 的结果不归档。
- 失败语义：归档失败只记 `[龙虎缓存] 快照归档失败` 日志，绝不影响接口响应和缓存写入。
- 体量：单股全天 gzip 后约 60~100KB；按每日 20 只股票估算约 1~2MB/天、每年 <0.5GB，可无限期保留。
- 冷启动回填（2026-07-17 二次补充）：`loadAllDay` 冷 miss 时先读本地归档最近一个交易日快照，命中则以 stale 身份写回 L1/L2 并恢复 `latest` 指针，立即可读；周末回填后 0 上游，工作日按现有 stale/探测机制自然校准。归档缺失或损坏时照旧全量冷重建。
- QuantBoard 入库（仍是非目标）：不写 MongoDB；将来需要时从归档目录离线导入。

### 7.2 收盘后候选池采集（2026-07-17 新增需求）

覆盖"exe 没有打开查看过的股票"：当日进入候选池/交易池的股票（通常 ≤5 只）收盘后自动采集归档。

- 登记：盘中调用 `POST /api/big-order/longhu/collect-list {stockCodes}` 登记当日清单；六位代码校验、去重、单日上限 20 只，落盘 `data/big-order/collect-list/{date}.json`，proxy 重启不丢。
- 自动触发：proxy 主进程内 `setInterval(60s).unref()` worker（参照 `eventRadarBackgroundWorker` 先例，不是独立进程），工作日 15:10~16:00 窗口对当日清单逐只执行 `loadAllDay`（走同一调度器、并发 1、同一归档器），每天最多一轮。
- 手动兜底：`POST /api/big-order/longhu/collect`（可带 stockCodes）立即采集并返回逐只报告；命中缓存时无上游成本，重复执行代价趋近于零。
- 无质量门禁：采到即归档，单只失败记日志跳过，不重试到死、不阻断。
- 清单来源接线：候选池自动/手动入池逻辑在 Dragon Board 前端（`src/services/candidate/**`），入池时应调用 collect-list 登记；前端接线为独立改动，接线前可手动登记。

## 8. 风控保护

### 8.1 请求合并

- 相同 `{sessionDate/latest, stock, money}` 的并发 miss 只允许一个 loader。
- `LayeredProxyCache.pending` 负责两级缓存之上的单进程请求合并。
- 所有 Longhu 上游工作统一进入 `LonghuRequestScheduler`，全局 running=1、queued distinct jobs 最大 4、等待超时 8 秒。
- 优先级：用户冷 miss > stale 后台头刷 > 历史审计。
- 队列已满时历史审计直接丢弃；stale 头刷不再入队并继续返回 stale；用户冷 miss 返回 `big_order_refresh_busy` degraded。
- 相同 key/type 的后台头刷和审计去重，不能因不同请求对象重复排队。
- 当前本地部署只有一个 proxy 进程，不引入分布式锁；如果以后多实例部署，再增加 Redis `SET NX PX` 锁。

### 8.2 限流与熔断

参考 THS 主力资金链路：

- 所有 Longhu 上游请求由同一个有界 scheduler 执行，并发固定为 1；完整重建、头部刷新、历史审计都不能并行访问上游或绕过队列。
- 分页串行，页间延迟 100~200ms。
- 全源 breaker：HTTP 403/429、DNS/连接失败、单个上游请求的网络超时和连续 5xx 计数；连续 3 次后全源熔断 60s。
- 单 key 冷却：`errcode != 0`、短页截断、Total 漂移、sessionDate/重叠校验失败只影响 `{stock,money}`；连续 3 次后该 key 冷却 60s。
- 服务自身 45 秒完整重建预算耗尽属于单 key 完整性/成本失败，不计入全源 breaker。
- 全源成功请求清零全源失败计数；单 key 完整/增量成功只清零该 key 计数。

## 9. stale 与失败语义

优先级：

```text
ProcessMemory fresh
  > Redis fresh（并回填 ProcessMemory）
  > ProcessMemory stale
  > Redis stale（并回填 ProcessMemory）
  > 上游同步加载
  > degraded
```

规则：

- Redis 连接、读写或反序列化失败必须 fail-open 到 L1/上游，不阻断接口。
- 上游失败不能删除完整缓存。
- 无 stale 时返回结构化 degraded，不返回伪装成功的空列表。
- WinForms 收到 degraded 时只允许使用响应/缓存明确提供的同 `sessionDate/cacheDate`、同股票、同数据源且未超过本地最大陈旧时间的 last-good；交易时段最多 5 分钟，收盘后最多 12 小时。
- WinForms 不能把 `dragonMeta.cache.stale` 直接映射为 `DataFreshness.Stale`；结构化 Longhu 响应使用 `cache.uiStale`，并保留 `fetchedAt` 供诊断和防御性复核。
- Longhu 聚合端点使用独立 60 秒 `HttpClient`；其它现有数据源继续使用 15 秒客户端，不能为了冷启动整体放宽所有请求超时。
- WinForms 不因 proxy 失败自动直连 Longhu，避免缓存失效时形成第二波上游请求。
- `ProxyPrimary` 是正常传输状态；只有真实 direct 失败后走备用代理的 quote/minute 等来源才使用 `ProxyFallback`。
- 如果首次启动时 proxy 不可用且本地没有 last-good，Longhu 明确显示不可用。这是用可用性换取上游风控边界的有意选择，不能静默改回自动直连。

## 10. THS detail 同步改造

当前 `/api/big-order/ths-detail` 只使用进程内 `runtimeCache`。改造为：

- 使用同一 `LayeredProxyCache`，而不是简单的 `cache.enabled() ? cache : runtimeCache`。
- key 显式升级为 `big-order:ths-detail:v2:{cacheDate}:{stockCode}`，避免与旧 key 混用。
- stale 命中立即响应并后台刷新，不让 UI 等待慢上游。
- 保持现有 envelope 和 `dragonMeta.cache`，C# 无需改变 THS payload 字段解析。

这与 `/api/quotes/ths-money-flow` 已验证的模式一致，但单股 detail 不需要批量 worker。

## 11. 可观测性

每次结构化响应记录：

- `cache.store/hit/stale/upstreamCalled/ttlSeconds`
- `refresh.mode`：`cold-full`、`incremental-head`、`full-rebuild`、`historical-audit`、`cache-hit`
- `refresh.inProgress`、单 key `incrementFailureCount`
- `refresh.pagesFetched/newRows/total/elapsedMs`
- `fetchedAt/servedAt`

日志只记录刷新失败、熔断开关和完整重建，缓存 hit 不逐次刷屏。

## 12. 验收标准

1. 同股首次 Longhu 冷 miss 在“排队不超过 8 秒 + 重建不超过 45 秒 + 客户端 60 秒”合同内完成全量分页或明确返回 stale/degraded；不能因共享 15 秒超时必然失败。
2. `Total=17044` 的缓存新增 10 条后，只抓取头页并合并为 17054 条。
3. `st=500` 上游短页行为不再影响系统，因为内部上游页大小始终为 200。
4. 两个并发冷请求只执行一次完整 loader。
5. 增量模式下 stale 请求等待一次有界最新页刷新并返回 fresh；增量失败时保留 stale 快照。
6. Redis 启动后再断线时仍可退回进程内缓存；proxy 继续工作且不会因 Redis miss 额外放大上游请求。
7. 上游失败且有 stale 时不清空列表；无 stale 时返回 degraded。
8. 新交易日不能命中前一日缓存。
9. 快速切换 THS/Longhu 不产生额外全量上游分页，旧源迟到结果不能覆盖当前 UI。
10. 旧 `/main-monitor` 和 `/all-day` 响应主体兼容测试继续通过。
11. 公共 `limit=500` 请求不会向上游发送 `st>200`，而是内部拆页后返回最多 500 条。
12. fresh 大单状态显示“代理通道: 大单”，不显示“代理降级: 大单”；stale/failed 仍按现有优先级显示。
13. 周末/节假日读取最近 sessionDate 的 stale，不触发按自然日重复全量分页。
14. L1 总字节和队列上限生效，构造大量 stock/money 请求不能无界占用内存或排队。
15. 默认增量模式为 `prepend-logical`；Total 漂移、重叠校验、短页和预算失败时 fail-closed，并回退完整重建或 stale 快照。
16. 多股票同时 stale 时 Longhu 上游最大并发仍为 1。
17. 单股短页/Total 漂移不会触发全源 breaker；403/429 等系统性错误会。
18. 冷 miss、头刷和历史审计共用最多 4 个排队项；大量不同股票 stale 不能产生无界后台队列。
19. envelope 明确返回 `sessionDate`；C# 跨日 last-good 测试不使用 `fetchedAt` 猜交易日。
20. 10 秒 technical stale 不直接导致 UI stale；交易时段数据年龄超过 30 秒才显示“数据陈旧”。
21. 旧 `/main-monitor`、`/all-day` 不因 Redis 改造新增 money allowlist；非零 money 不得污染 canonical `money=0` 快照。
22. 历史审计和收盘对账只搭普通请求便车，不新增独立 timer。
23. `currentTotal < T0`、短缓存 overlap、空结果 key 和盘前时段均有回归测试。
24. 本地发布按同批顺序执行：停止旧 exe/proxy，更新并启动兼容旧路由的新 proxy，再启动使用新结构化端点的 exe；不得让旧逐页 C# fallback 长时间与新 10 秒 page cache 混跑。
25. 首次加载、切股、切源和 `sessionDate` 变化只建立语音基线，不播报当前全天历史。
26. 同一 scope 第二次快照新增 3 条符合语音条件的订单时，按时间顺序播报 3 条；不得只取最新两条、最新十条或命中第一条后返回。
27. 同秒同类型同价同量的合法重复订单从 2 条增加到 3 条时，只播报新增的 1 条；行暂时消失后恢复不重播。
28. 调整金额阈值、买卖页签或特殊标记筛选不播历史；之后新订单按调整后的当前筛选条件决定是否播报。
29. 语音关闭期间仍推进基线，重新开启不补播关闭期间订单；关闭、切股、切源和退出会取消旧队列。
30. marker 重算使旧订单新获得“买活跃/承接好”时不追溯播报；只有本轮新增订单可播。
31. 同一刷新批次只调用一次语音批次入口，普通刷新不调用 `SpeakAsyncCancelAll()`；连续刷新产生的批次顺序排队且不互相取消。
32. THS 和 Longhu envelope 都提供权威 `sessionDate`；THS 无法确认交易日时不使用 `DateTime.Today` 猜测，也不推进语音基线。
33. 语音关闭期间没有任何成功刷新，或关闭时请求在重新开启后才完成时，re-enable 后第一份 accepted snapshot 仍只重建基线、不播报。
34. 同一新增订单同时具有 FundMarker 和 BuyMarker 时，特殊筛选非空则播筛选同名类型；无特殊筛选才应用默认优先级。
35. fake speech queue 证明：每批一次 SpeakAsync、普通批次 cancel=0、两个批次 FIFO、显式 CancelPending cancel=1、Dispose 会取消并释放。
36. 同一 THS payload 在不同服务器自然日解析时，只有时分秒的 order 都使用权威 `sessionDate.Date`，订单指纹和增量结果不变。
37. re-enable 后先收到 `sessionDate=null` 的快照时 barrier 保持；随后第一份可信日期完整快照仍只建基线，下一轮真实新增才播。

## 13. 非目标

- 不把 Redis 引入 WinForms。
- 不建立线上/数据库形态的大单历史库；全天快照按 §7.1 以本地 gzip 文件永久归档并支持冷启动回填（2026-07-17 需求变更），QuantBoard 入库仍是非目标。
- 不新增独立守护进程；收盘后候选池采集是 proxy 主进程内的 60 秒 tick worker（§7.2，2026-07-17 需求变更），与 Collector 复盘"集成到主进程"的要求一致。
- 不做全市场大单采集；采集范围限定当日登记清单，单日上限 20 只。
- 不并发抓取 Longhu 分页。
- 不修改 Longhu `tradetype` 业务映射。
- 不扩大现有语音业务范围为“所有大单均播报”。
