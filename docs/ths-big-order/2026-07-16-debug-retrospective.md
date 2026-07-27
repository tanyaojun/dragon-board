# THSBigOrder 双数据源调试复盘

> 日期：2026-07-16
>
> 范围：`tools/THSBigOrder`、`tools/THSBigOrder.Tests`
>
> 结论：Longhu 无实时大单的核心原因是分页请求参数与真实上游合同不一致；界面上的三条线和切源不刷新则是两个独立问题。

## 1. 最终结论

本轮实际遇到了四类问题，不能合并成一个“接口不可用”：

1. 首张全空截图请求的是 `999999`。该代码在通达信中通常表示上证指数，THSBigOrder 只校验“六位数字”，因此跟随通达信时会把指数当个股请求，得到空大单和失败分时。
2. Longhu POST 可以成功，但 `st=300/400/500` 不按请求数量稳定返回。`st=500` 时曾出现 `List=26、Total=17044`，旧逻辑据此错误结束或判定失败。
3. 腾讯分钟接口返回了 15:01 之后的记录，解析器把第一条盘后记录当成整个分钟源无效，白色价格线因此消失，红绿大单点只能退化贴在蓝色大单均线上。
4. 数据源切换会启动完整异步刷新，但加载期间仍保留旧列表、旧红绿点和旧蓝线，视觉上像“没有刷新”；快速来回切换还需要阻止前一数据源的迟到结果覆盖当前选择。

这四类问题分别位于输入代码、Longhu 分页、腾讯分钟解析和 UI 异步投影层。排查时必须逐层取证，不能只看“代理可用”或“HTTP 200”。

## 2. Longhu 分页根因

### 2.1 真实上游合同

Longhu 请求必须使用以下核心表单字段：

```text
POST https://apphwhq.longhuvip.com/w1/api/index.php

Order=0
st=200
a=GetMainMonitor_w30
c=StockYiDongKanPan
PhoneOSNew=1
DeviceID=<同一次全量加载内复用>
VerSion=5.17.0.4
Index=<当前偏移>
Money=0
apiv=w36
StockID=<六位代码>
IsBS=0
```

这里的“已验证合同”目前只完整落在 C# direct 路径。当前 `proxy-server/routes/bigOrder.js` 仍使用 GET query 请求上游，并且每次 `/main-monitor` 调用都会重新生成 DeviceID；C# proxy 分页逐页调用该路由，因此 proxy 路径尚未做到“POST 表单 + 同轮 DeviceID 复用”。后续 Redis 改造必须在 proxy 内统一纠正，不能把当前 fallback 当成已同构。

真实单行结构是：

```text
[tradetype, unixTimestamp, volume, money, price, datetime]
```

### 2.2 关键实测

上游的 `st` 不是一个可任意放大的稳定页大小：

| 请求 `st` | 实际表现 |
|---:|---|
| 100 | 通常返回 100 |
| 150 | 通常返回 150 |
| 200 | 通常返回 200 |
| 300 | 曾只返回约 30 |
| 400 | 曾只返回约 18 |
| 500 | 曾返回 0~26 |

异常短页时 `errcode` 仍可能为 `"0"`，`Total` 仍可能是完整当日总数，例如：

```text
st=500
List.Count=26
Total=17044
```

因此以下判断在该接口上是错误的：

```text
List.Count < requestedPageSize  => 已到最后一页
```

如果用它作为成功终止条件，会只返回前 26 条；如果同时要求累计数量等于 `Total`，又会把真实成功响应误判成截断失败。代理若继续使用 `st=500`，会重复同一个错误，不能成为有效降级。

### 2.3 最终修复规则

当前 C# Longhu 客户端采用：

- 固定 `PageSize=200`。
- direct 同一次全量加载复用一个 `DeviceID`；当前 proxy 尚未满足此项。
- 下一页偏移使用实际 `List.Count` 累加。
- 有 `Total` 时，只在累计数量达到 `Total` 后成功。
- 未达到 `Total` 却出现短页，判定为截断，不返回部分数据。
- `Total` 在分页中变化、累计超过 `Total`、缺少 `Total` 且连续满页超过 200 页，均判定失败。
- 合法 `Total=0/List=[]` 是成功空数据。
- 非空列表中可以跳过个别坏行；如果全部行都无效，则整页失败。
- 分页保持串行。曾尝试 4 路和 2 路并发，真实上游出现限流/失败并转入更慢的代理链路，已撤销。

当 `Total=17044` 时，冷启动约需 86 页。这个事实也是后续 Redis 方案必须解决的核心，而不是只把 500 改成 200 就结束。

## 3. 本轮源码改动记录

### 3.1 Longhu 数据源

- 新增 `DataSources/LonghuBigOrderSourceClient.cs`。
- 支持真实 Longhu POST 表单和本地 `/api/big-order/main-monitor` 路径。
- 按 `Total` 做完整性校验，不返回中途部分数据。
- 启用 TLS 1.2。

限制：本地 proxy 路径仍是 GET 上游且逐页更换 DeviceID，属于下一步必须处理的遗留合同，不应被描述为与 direct 等价。

### 3.2 Payload 解析

- `ThsPayloadParser` 新增 `ParseLonghuOrder()` / `ParseLonghuOrders()`。
- 支持真实 6 元素数组和早期分析阶段的 7 元素紧凑数组。
- `tradetype` 仅接受整数 `1..4`：

| Longhu tradetype | `BigOrderItem.Type` | 显示 | 方向 |
|---:|---:|---|---|
| 1 | 1 | 被动卖 | `IsSell` |
| 2 | 2 | 主动买 | `IsBuy` |
| 3 | 3 | 被动买 | `IsBuy` |
| 4 | 4 | 主动卖 | `IsSell` |

### 3.3 Provider 混合模式

- 默认保持 THS 大单。
- THS 模式：orders、主力摘要、THS `pricechange` 全部来自 THS。
- Longhu 模式：orders 来自 Longhu；主力摘要、股票 fallback、THS `pricechange` 仍来自 THS。
- THS orders、Longhu orders、THS summary 分开保存 last-good，禁止跨数据源复用旧 orders。
- quote、minute、limit-up 仍按物理数据源共享同股 last-good。

### 3.4 三条分时线

最终图表合同：

| 颜色 | 含义 | 数据源 |
|---|---|---|
| 白色 | 实际分钟成交价 | 腾讯分钟；不足时用 THS `pricechange` 仅作白线 fallback |
| 蓝色 | 累计大单均价 | 当前选中大单 orders |
| 黄色 | 全市场分时均价/VWAP | 腾讯分钟累计成交额和成交量 |

红绿大单点必须锚定白色价格线。腾讯分钟解析会忽略 15:00 之后的数据，但交易时段内的结构错误、时间倒序和累计值倒退仍会失败。

### 3.5 数据源切换

ComboBox 切换后立即：

- 清空旧 `_allData` / `_filteredData`。
- 清空表格、统计、红绿点和蓝色大单均线。
- 保留当前白色价格线和黄色分时均线作为市场背景。
- 强制刷新当前股票。
- 使用刷新 generation/cancellation，忽略前一数据源的迟到结果。

这样既不会在 Longhu 约 10 秒的加载期显示 THS 旧数据，也不会因快速切回 THS 被迟到的 Longhu 结果覆盖。

## 4. 验证与回归测试

已覆盖的关键行为：

- Longhu direct 真实请求字段、TLS、同轮 DeviceID 复用。
- `Index=0/200` 的 201 条分页。
- 缺少 `Total` 的最大页数保护。
- `Total` 变化、超量、截断、空列表、全坏行。
- direct 中页失败时不返回部分数据。
- THS/Longhu 混合路由和 last-good 隔离。
- 三条线、白线单独可画、红绿点锚定白线。
- 腾讯分钟忽略 15:00 后记录。
- 切源加载期立即清旧 orders，保留白/黄线。
- 快速切源时迟到结果不能覆盖当前数据源。

最终目标测试为 63 项中的 61 项通过；剩余 2 项是既有固定日期涨停夹具失败，与 Longhu 和图表改动无关。THSBigOrder Release 验证构建为 0 warning / 0 error。

## 5. 后续排查同类问题的顺序

1. 先记录实际股票代码、数据源、请求参数和响应 `Total/List.Count`，不要只记录 HTTP 状态。
2. 对分页接口分别验证 `st=100/150/200/300/400/500`，不能假设服务端遵守请求页大小。
3. 终止条件优先使用服务端总量或明确游标；短页只能在已验证合同下使用。
4. 检查 direct 与 proxy 是否真的走不同实现。代理复用同一错误参数时不构成降级。
5. 大结果集先评估冷启动页数、稳态新增量和上游风控，再决定是否并发。Longhu 已证明不适合并发分页。
6. UI 异步刷新必须区分“请求没发出”“请求仍在运行”“旧投影未清理”和“迟到结果覆盖”。
7. 图表缺线时分别检查源数据、解析器过滤、序列构建和绘制层，不能从最终颜色反推数据源。

## 6. 相关文档

- [THS L2 API 分析](../API/ths-l2-api-analysis.md)
- [双数据源设计](../superpowers/specs/2026-07-16-thsbigorder-dual-source-design.md)
- [Longhu 实施记录](../superpowers/plans/2026-07-16-thsbigorder-longhu-source.md)
- [BigOrder Redis 缓存设计](big-order-redis-cache-design.md)
