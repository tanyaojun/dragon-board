# THSBigOrder Longhu Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 THSBigOrder 增加可切换的 Longhu 大单 orders 数据源，同时保持 THS 默认行为和摘要/分时补全。

**Architecture:** 新客户端继续实现现有 `IMarketSourceClient<BigOrderSourceData>`，direct 请求 longhuvip，proxy 请求本地 main-monitor。Provider 在 THS 模式只走现有源；在 Longhu 模式并发加载 Longhu orders 与 THS summary 后按字段合并。WinForms 使用 ComboBox 切换并触发完整刷新。真实分页合同纠偏见 [调试复盘](../../ths-big-order-debug/2026-07-16-debug-retrospective.md)。

**Tech Stack:** C#、.NET Framework 4.8、WinForms、HttpClient、Newtonsoft.Json、自定义控制台测试程序。

---

> **后续演进说明：** 本计划是已经完成的 direct-first 双数据源实施记录，不是 Redis 目标态的执行计划。缓存改造完成后，Longhu 正常链路将由 `/api/big-order/longhu/all-day` proxy-primary 替代 direct/proxy 逐页 fallback；实施步骤以 [BigOrder Redis TTL Cache Implementation Plan](../../ths-big-order-debug/big-order-redis-cache-implementation-plan.md) 为准。

### Task 1: Longhu payload parser

**Files:**
- Modify: `tools/THSBigOrder.Tests/Program.cs`
- Modify: `tools/THSBigOrder/Parsing/ThsPayloadParser.cs`

- [x] 添加测试：合法紧凑数组映射 Type/Volume/Amount/Price/Time；非法字段抛 `PayloadParseException`；列表解析跳过坏行并保留好行。
- [x] 运行 `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release --no-restore`，确认因新合同未实现而失败。
- [x] 实现单行 `ParseLonghuOrder(JArray)` 和集合 `ParseLonghuOrders(JArray)`。
- [x] 重跑测试确认 parser 用例通过。

### Task 2: Longhu direct/proxy client

**Files:**
- Modify: `tools/THSBigOrder.Tests/Program.cs`
- Modify: `tools/THSBigOrder/DataSources/LonghuBigOrderSourceClient.cs`
- Modify: `tools/THSBigOrder/Program.cs`

- [x] 添加测试：direct URL/headers/transport 正确，proxy URL/transport 正确，业务错误抛异常。
- [x] 运行测试确认当前“direct 实际走 proxy”和吞异常行为导致失败。
- [x] 实现 longhuvip direct 与 `/api/big-order/main-monitor` proxy；复用 parser，保留异常给 Provider fallback。
- [x] 保留 TLS 1.2 启动设置，重跑测试。
- [x] 按 `Total` 完整分页，并验证 201 条数据使用 `Index=0/200`、direct 复用 DeviceID。

### Task 3: Provider mixed routing

**Files:**
- Modify: `tools/THSBigOrder.Tests/Program.cs`
- Modify: `tools/THSBigOrder/THSBigOrderDataProvider.cs`

- [x] 扩展测试 stubs，注入 THS 与 Longhu 两个 source。
- [x] 添加测试：默认 THS 不调用 Longhu；Longhu 模式 orders 来自 Longhu，MainFunds/Prices/StockFallback 来自 THS；transport/freshness 以 Longhu 为准。
- [x] 运行测试确认现有构造签名和合并逻辑不满足合同。
- [x] 最小实现路由与合并，不改变 quote/minute/limit-up 逻辑。
- [x] 增加 orders/summary 独立 stale、切源共享 quote stale 和 THS/Longhu orders 缓存隔离测试。
- [x] 重跑完整测试。

### Task 4: ComboBox source switch

**Files:**
- Modify: `tools/THSBigOrder.Tests/Program.cs`
- Modify: `tools/THSBigOrder/MainForm.Designer.cs`
- Modify: `tools/THSBigOrder/MainForm.cs`

- [x] 添加测试：存在 `cboDataSource`，选项为“龙虎大单/THS大单”，默认 THS；选择龙虎后更新 Provider 并刷新当前代码。
- [x] 运行测试确认双按钮草稿不满足合同。
- [x] 用 ComboBox 替换双按钮，绑定 `SelectedIndexChanged`，切换时调用完整刷新。
- [x] 重跑完整测试。

> 后续 Redis 计划补充：切换数据源时还必须取消旧来源语音队列；新来源首份全天快照只建立增量播报基线。完整实现任务见 [BigOrder Redis TTL Cache Implementation Plan](../../ths-big-order-debug/big-order-redis-cache-implementation-plan.md#task-8winforms-只播报本轮新增信号)。

### Task 5: Verification

**Files:**
- Verify: `tools/THSBigOrder/**`
- Verify: `tools/THSBigOrder.Tests/**`

- [x] 运行 `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release --no-restore`；本功能测试全部通过，套件仍有 2 个既有固定日期涨停夹具失败。
- [x] 运行 `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release --no-restore`，0 warnings / 0 errors。
- [x] 运行 `dotnet build tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release --no-restore`，0 warnings / 0 errors。
- [x] 实测 Longhu direct/proxy 盘中可返回数据；盘后 `Total=0/List=[]` 按成功空数据处理。
- [x] 检查 `git diff --check`、目标文件 diff 和工作区状态。
- [x] 经授权使用 subagent code review；首次发现 1 Critical、4 Important、1 Minor，修复后复审无剩余 Critical/Important。

本计划中的“无剩余 Critical/Important”只针对当时的双数据源代码 review，不代表后续 BigOrder Redis design/plan 已通过审计。2026-07-16 外部对抗性审计发现的缓存方案问题已单独记录并修订。
