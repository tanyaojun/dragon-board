# THSBigOrder 双数据源切换设计

> 日期：2026-07-16 | 状态：已实现
> 分页纠偏：真实上游稳定页大小为 200，原设计中的 500 已被实测否定。详见 [THSBigOrder 双数据源调试复盘](../../ths-big-order-debug/2026-07-16-debug-retrospective.md)。
>
> 架构演进：本文记录已经落地的 direct-first 双源基线。后续 [BigOrder Redis TTL 缓存设计](../../ths-big-order-debug/big-order-redis-cache-design.md) 完成后，Longhu 正常链路将改为 proxy-primary，direct POST 只保留诊断用途；在 Redis 改造实际完成前，不把目标态写成已实现。

## 目标

为 `tools/THSBigOrder` WinForms 工具新增双数据源支持：
- **THS大单**：现有数据源（10jqka.com.cn，ths-detail API）
- **龙虎大单**：新数据源（longhuvip.com，main-monitor API）

当前已实现版本为直连公共 API 优先，`proxy-server:3000` 作为 fallback。该口径只描述 Redis 改造前的现状。

## 核心设计：混合模式

龙虎大单（main-monitor）只提供逐笔大单数据，不提供主力资金摘要和分时涨跌幅。切换为龙虎大单时采用混合策略：

| 数据 | 龙虎大单 | THS大单 |
|---|---|---|
| 逐笔大单 (orders) | LonghuBigOrderSourceClient | ThsBigOrderSourceClient |
| 主力摘要 (mainFunds) | 回退 ThsBigOrderSourceClient | ThsBigOrderSourceClient |
| 分时价格 (prices) | 回退 ThsBigOrderSourceClient | ThsBigOrderSourceClient |

## 涉及文件

| 文件 | 改动 |
|---|---|
| `DataSources/LonghuBigOrderSourceClient.cs` | **新增**：直连 longhuvip.com + proxy fallback |
| `Parsing/ThsPayloadParser.cs` | **新增** `ParseLonghuOrder()` 和 `ParseLonghuOrders()` 方法 |
| `THSBigOrderDataProvider.cs` | **新增** `DataSource` 枚举 + 路由逻辑 |
| `MainForm.Designer.cs` | **新增** `cboDataSource` ComboBox（输入框右侧） |
| `MainForm.cs` | **新增**切换事件 → 全量刷新 |

## UI 变更

在 `txtStockCode` 右侧新增 ComboBox：
- 宽度约 85px，选项顺序：`龙虎大单` / `THS大单`
- 默认 `THS大单`
- 切换时触发完整刷新（数据+图表+统计）
- 切换时取消上一来源尚未播放的语音；新来源首份完整快照只建立基线，不播报历史订单。

## Redis 改造后的语音增量合同

双数据源基础版本的语音逻辑只检查最近 10 条、命中一条就返回，并且后一次 `SpeakAsync` 会取消前一次。Redis 改造后 proxy 返回全天完整快照，WinForms 必须在当前股票、来源和交易日内识别本轮新增订单：

- 首次加载、切股、切源和跨交易日只建立基线。
- THS 与 Longhu 都必须提供权威 `sessionDate`；无法确认交易日时不猜测、不播报。
- 筛选条件变化不把历史订单重新视为新增。
- 只播现有四类 marker：点火、砸盘、买活跃、承接好。
- 特殊 marker 筛选非空时播报类型服从该筛选；无特殊筛选时才按既有优先级。
- 同一轮全部新增有效信号按时间顺序合成一个语音批次，不再固定只播最近两条或最新 N 条。
- 重新开启语音后的第一份成功快照只重建基线，覆盖关闭期间没有刷新或请求迟到的情况。
- 具体重复订单计数、语音关闭和队列取消合同以 [BigOrder Redis TTL 缓存设计](../../ths-big-order-debug/big-order-redis-cache-design.md#64-winforms-增量语音播报) 为准。

## 数据流与错误处理

- THS 模式只加载现有 `ThsBigOrderSourceClient`，不额外请求 Longhu。
- 龙虎模式并发加载 Longhu orders 和 THS summary；最终只替换 `Orders`，保留 THS 的 `MainFunds`、`Prices`、`StockFallback`。
- Longhu direct 请求 `https://apphwhq.longhuvip.com/w1/api/index.php` 的 `GetMainMonitor_w30`。
- direct 抛出网络、HTTP、JSON 或业务错误时，由现有 `LoadDirectFirstAsync` 调用代理 `/api/big-order/main-monitor`。
- direct 和 proxy 均按 200 条分页，并以响应 `Total` 为完整性边界；分页中途失败时整次请求失败，不返回部分数据。
- 空 `List` 是成功的空数据，不吞异常、不伪装为请求成功。
- 非空 `List` 若没有任何有效行，视为响应结构错误并触发 fallback。
- `MarketSourceTransports.BigOrder` 和 `BigOrderFreshness` 以当前选中的 orders 数据源为准。
- Longhu orders 与 THS orders 分开缓存；THS summary、quote、minute、limit-up 按物理数据源共享 stale fallback。

Redis 改造后的目标差异：

- Longhu orders 正常请求只调用 proxy 结构化全天端点，由 proxy 完成 POST、固定 DeviceID、串行分页和缓存。
- C# 不再自动执行 Longhu direct → proxy fallback；proxy 失败时只允许使用同 `sessionDate`、同股票、同源且有时限的 last-good。
- 正常 proxy 结果使用 `ProxyPrimary`，不能显示成“代理降级”。
- Longhu 聚合请求使用独立 60 秒客户端；其它现有数据源仍保持 15 秒。

## tradetype 映射（假设对齐）

| tradetype | BigOrderItem.Type | 显示 | 方向 |
|---|---|---|---|
| 1 | 1 | 被动卖 | IsSell |
| 2 | 2 | 主动买 | IsBuy |
| 3 | 3 | 被动买 | IsBuy |
| 4 | 4 | 主动卖 | IsSell |
