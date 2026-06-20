# THSBigOrder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `tools/KPLViewer` 迁移为依赖本地代理的 `tools/THSBigOrder`，接入同花顺大单、腾讯行情和同花顺涨停池，并实现参考图风格的高密度大单监控界面。

**Architecture:** `proxy-server` 新增来源明确且带缓存的同花顺大单路由，并为现有同花顺涨停池补缓存；旧 KPL 路由保持兼容。WinForms 客户端并行读取三路代理数据，解析为不可变刷新快照，再由纯聚合器生成图表序列，UI 只负责渲染和交互。

**Tech Stack:** Node.js 20、Express、Node test runner、C#、.NET Framework 4.8、WinForms、Newtonsoft.Json、System.Drawing。

---

## 执行前门禁

- 使用 `using-git-worktrees` 创建隔离工作区；当前主工作区包含用户的 TdxL2Helper 改动，执行时不得纳入提交。
- 设计与实施计划必须在创建 worktree 前提交；worktree 从包含这两份文档的 commit 创建，并先验证两份路径均存在。
- 原 `D:\dragon-board\tools\KPLViewer` 整体未被 Git 跟踪，不会自动进入 worktree。迁移任务必须先把下文列出的 9 个文件逐一复制到隔离工作区，再确认目标 `tools/THSBigOrder` 不存在。
- 禁止批量删除。目录迁移使用同一 PowerShell 会话内经过路径校验的 `Move-Item -LiteralPath`；若目标已存在，停止并报告。
- 每个生产行为先写失败测试并确认 RED，再写最小实现。
- 每次提交只暂存任务列出的明确路径。

## 文件职责

### Proxy

- Modify `proxy-server/routes/bigOrder.js`：保留旧 KPL 路由，新增 THS detail 路由和响应校验。
- Modify `proxy-server/routes/market.js`：给旧同花顺涨停池增加 read-through 缓存，不改变响应主体。
- Modify `proxy-server/helpers/proxyCache.js`：增加 THS 大单和涨停池 TTL。
- Modify `proxy-server/app.js`：为 THS 路由注入不依赖 Redis 的进程内 cache。
- Modify `proxy-server/server.js`：登记新正式路由。
- Modify `proxy-server/openapi.js`：登记参数和来源边界。
- Create `proxy-server/__tests__/thsBigOrder.test.mjs`：THS 路由、缓存、降级和旧路由兼容测试。
- Modify `proxy-server/__tests__/thsLimitupPools.test.mjs`：涨停池缓存回归测试。
- Modify `proxy-server/__tests__/docs.test.mjs`：OpenAPI 路径回归测试。

### THSBigOrder

- Move `tools/KPLViewer/` → `tools/THSBigOrder/`。
- Rename `tools/THSBigOrder/KPLViewer.csproj` → `tools/THSBigOrder/THSBigOrder.csproj`。
- Rename `tools/THSBigOrder/KPLDataProvider.cs` → `tools/THSBigOrder/THSBigOrderDataProvider.cs`。
- Create `tools/THSBigOrder/Models/MarketSnapshot.cs`：三路数据合并后的 UI 读模型和数据源状态。
- Create `tools/THSBigOrder/Parsing/ThsPayloadParser.cs`：同花顺大单、腾讯行情和涨停池纯解析。
- Create `tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs`：分钟柱、累计净额、阈值热力纯计算。
- Create `tools/THSBigOrder/Controls/BigOrderChartControl.cs`：双缓冲图表渲染。
- Create `tools/THSBigOrder/Filtering/OrderFilter.cs`：金额、买卖和特殊标记组合过滤。
- Create `tools/THSBigOrder/Refresh/RefreshCoordinator.cs`：取消旧请求、请求代次和最新代码排队。
- Create `tools/THSBigOrder/Properties/AssemblyInfo.cs`：仅配置 `InternalsVisibleTo`。
- Create `tools/THSBigOrder/app.manifest`：PerMonitorV2/PerMonitor DPI awareness。
- Modify `tools/THSBigOrder/MainForm.cs`：刷新编排、过滤、绑定、错误状态和旧交互。
- Modify `tools/THSBigOrder/MainForm.Designer.cs`：72/28 布局、顶部指标和右侧明细。
- Modify `tools/THSBigOrder/AnalysisForm.cs`、`Program.cs`、`VoiceService.cs`、`WindowSettings.cs`：命名空间和产品名迁移。
- Create `tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj`：无测试框架的 net48 控制台测试入口。
- Create `tools/THSBigOrder.Tests/Program.cs`：解析、合并、降级和聚合回归测试。

---

### Task 1: 新增同花顺大单代理合同

**Files:**
- Create: `proxy-server/__tests__/thsBigOrder.test.mjs`
- Modify: `proxy-server/routes/bigOrder.js`
- Modify: `proxy-server/helpers/proxyCache.js`
- Modify: `proxy-server/app.js`
- Modify: `proxy-server/app.js`

- [ ] **Step 1: 写 THS 成功响应与股票代码校验失败测试**

测试必须构造 `createProxyApp`，注入可控时钟的进程内 cache 和假的 `plainClient.get`。核心断言：

```js
test('THS big-order detail validates stock code and returns source payload', async () => {
  const invalid = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=abc`)
  assert.equal(invalid.status, 400)
  assert.equal((await invalid.json()).errorCode, 'invalid_stock_code')

  const response = await fetch(`${baseUrl}/api/big-order/ths-detail?stockCode=002297`)
  const body = await response.json()
  assert.equal(response.status, 200)
  assert.equal(body.source, 'ths-big-order-detail')
  assert.equal(body.stockCode, '002297')
  assert.equal(body.data.title.stockname, '博云新材')
  assert.equal(body.data.list[0].nature, '主力主买')
})
```

- [ ] **Step 2: 运行单测确认 RED**

Run: `node --test proxy-server/__tests__/thsBigOrder.test.mjs`

Expected: FAIL，原因是 `/api/big-order/ths-detail` 返回 404。

- [ ] **Step 3: 实现最小 THS 路由和上游结构校验**

在 `bigOrder.js` 增加完整 URL builder、固定请求头与校验函数：

```js
const THS_BIG_ORDER_BASE = 'https://vaserviece.10jqka.com.cn/Level2/index.php'

const THS_BIG_ORDER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  Referer: 'https://vaserviece.10jqka.com.cn/',
  Accept: 'application/json,text/plain,*/*',
}

function buildThsBigOrderUrl(stockCode) {
  const url = new URL(THS_BIG_ORDER_BASE)
  url.searchParams.set('op', 'mainMonitorDetail')
  url.searchParams.set('stockcode', stockCode)
  return url
}

function normalizeStockCode(value) {
  const code = String(value || '').trim()
  return /^\d{6}$/.test(code) ? code : ''
}

function validateThsPayload(payload) {
  if (Number(payload?.errorcode) !== 0) throw new Error(payload?.msg || 'ths error response')
  if (!payload?.title || !Array.isArray(payload?.list)) throw new Error('invalid ths big-order payload')
  return {
    fetchedAt: Date.now(),
    title: payload.title,
    list: payload.list,
    pricechange: Array.isArray(payload.pricechange) ? payload.pricechange : [],
  }
}
```

测试必须断言 fake client 收到 GET URL 的 `op=mainMonitorDetail`、`stockcode=002297` 以及上述三类请求头。

路由返回固定合同：

```js
res.json({
  ok: true,
  source: 'ths-big-order-detail',
  stockCode,
  fetchedAt: result.value.fetchedAt,
  servedAt: Date.now(),
  data: attachCacheMeta(result.value, { ...result.cache, ttlSeconds }),
})
```

缓存 key 固定为 `big-order:ths-detail:v1:${stockCode}`，TTL 配置放入 `PROXY_CACHE_TTLS.bigOrder.thsDetail`，stale TTL 为 TTL 的 6 倍。新增的 `ProcessMemoryCache` 必须实现 `get/set/remember`、并发 miss 合并和可注入 `now()`；`createProxyApp` 默认实例化并以 `runtimeCache` 传给 THS 路由，因此本地未配置 Redis 时仍能缓存。

- [ ] **Step 4: 运行单测确认 GREEN**

Run: `node --test proxy-server/__tests__/thsBigOrder.test.mjs`

Expected: PASS，成功与非法代码用例均通过。

- [ ] **Step 5: 增加缓存、并发合并、stale fallback 与旧路由兼容测试**

测试用 fake clock 依次断言：首次 miss、TTL 内 hit、两个并发 miss 合并、TTL 过期后 loader 失败返回同 key stale、超过 stale TTL 后返回 degraded。另对旧 `/api/big-order/main-monitor` 和 `/api/big-order/all-day` 分别固定成功、空结果、错误降级和分页终止，保证顶层 `{ List: [...] }` 从不被新 envelope 包裹。

```js
assert.equal(upstreamCalls, 1)
assert.equal(secondBody.data.dragonMeta.cache.hit, true)
assert.equal(staleBody.data.dragonMeta.cache.stale, true)
assert.match(kplUrl, /GetMainMonitor_w30/)
assert.deepEqual(allDayBody, { List: expectedRows })
```

- [ ] **Step 6: 再次运行 THS 路由测试**

Run: `node --test proxy-server/__tests__/thsBigOrder.test.mjs`

Expected: PASS，0 failed。

- [ ] **Step 7: 提交代理 THS 路由**

```powershell
git add proxy-server/routes/bigOrder.js proxy-server/helpers/proxyCache.js proxy-server/app.js proxy-server/__tests__/thsBigOrder.test.mjs
git commit -m "feat: add cached THS big-order route"
```

---

### Task 2: 为同花顺涨停池补缓存并更新 API 文档

**Files:**
- Modify: `proxy-server/routes/market.js`
- Modify: `proxy-server/helpers/proxyCache.js`
- Modify: `proxy-server/__tests__/thsLimitupPools.test.mjs`
- Modify: `proxy-server/__tests__/docs.test.mjs`
- Modify: `proxy-server/openapi.js`
- Modify: `proxy-server/server.js`

- [ ] **Step 1: 写旧涨停池缓存测试**

给 `createProxyApp` 注入与 Task 1 相同、带 fake clock 的 `ProcessMemoryCache`，对 `/api/limitup/10jqka?date=20260618` 连续请求两次，断言上游调用一次且响应主体仍保留 `data.info`：

```js
assert.equal(upstreamCalls, 1)
assert.equal(firstBody.data.info[0].code, '002297')
assert.equal(secondBody.data.info[0].order_amount, 45049860)
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `node --test proxy-server/__tests__/thsLimitupPools.test.mjs`

Expected: FAIL，实际上游调用次数为 2。

- [ ] **Step 3: 用现有 cache.remember 包裹 `/api/limitup/10jqka`**

缓存 key 使用 `market:ths-limitup:v1:${dateStr}`；TTL 使用 `PROXY_CACHE_TTLS.market.thsLimitUp`，stale TTL 为 TTL 的 6 倍。生产路由使用 `app.js` 注入的 `runtimeCache`，不依赖 Redis。缓存成功响应只通过 `attachCacheMeta` 增加 `dragonMeta`，不得改写 `data.info`；测试还需推进 fake clock，验证 stale 与超过 stale TTL 后的 degraded。

- [ ] **Step 4: 运行涨停池测试确认 GREEN**

Run: `node --test proxy-server/__tests__/thsLimitupPools.test.mjs`

Expected: PASS，0 failed。

- [ ] **Step 5: 写 OpenAPI 失败测试并更新文档**

先在 `docs.test.mjs` 增加：

```js
assert.ok(body.paths['/api/big-order/ths-detail'].get)
assert.equal(body.paths['/api/big-order/ths-detail'].get.parameters[0].name, 'stockCode')
```

Run: `node --test proxy-server/__tests__/docs.test.mjs`

Expected: FAIL，路径尚未登记。

然后在 `openapi.js` 新增带六位代码约束的 GET operation，并在 `server.js` 正式路由列表增加 `GET  /api/big-order/ths-detail`。

- [ ] **Step 6: 运行代理相关测试**

Run: `node --test proxy-server/__tests__/thsBigOrder.test.mjs proxy-server/__tests__/thsLimitupPools.test.mjs proxy-server/__tests__/docs.test.mjs`

Expected: PASS，0 failed。

- [ ] **Step 7: 提交缓存和文档**

```powershell
git add proxy-server/routes/market.js proxy-server/helpers/proxyCache.js proxy-server/app.js proxy-server/__tests__/thsLimitupPools.test.mjs proxy-server/__tests__/docs.test.mjs proxy-server/openapi.js proxy-server/server.js
git commit -m "feat: cache THS limit-up context"
```

---

### Task 3: 安全迁移并统一 THSBigOrder 命名

**Files:**
- Move: `tools/KPLViewer/**` → `tools/THSBigOrder/**`
- Rename: `tools/THSBigOrder/KPLViewer.csproj` → `tools/THSBigOrder/THSBigOrder.csproj`
- Rename: `tools/THSBigOrder/KPLDataProvider.cs` → `tools/THSBigOrder/THSBigOrderDataProvider.cs`
- Modify: all `tools/THSBigOrder/*.cs`
- Create: `tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj`
- Create: `tools/THSBigOrder.Tests/Program.cs`
- Create: `tools/THSBigOrder/Properties/AssemblyInfo.cs`
- Create: `tools/THSBigOrder/app.manifest`

- [ ] **Step 1: 验证迁移路径并移动目录**

先把未跟踪源文件逐一复制到隔离工作区，再在同一 PowerShell 会话执行迁移：

```powershell
$sourceWorkspace = (Resolve-Path 'D:\dragon-board\tools\KPLViewer').Path
$worktreeRoot = (Resolve-Path '.').Path
$importDir = Join-Path $worktreeRoot 'tools\KPLViewer'
if (-not $sourceWorkspace.StartsWith('D:\dragon-board\tools\KPLViewer')) { throw 'unexpected source workspace' }
if (Test-Path -LiteralPath $importDir) { throw 'worktree tools/KPLViewer already exists' }
New-Item -ItemType Directory -Path $importDir | Out-Null
$files = @(
  'AnalysisForm.cs', 'icon.ico', 'KPLDataProvider.cs', 'KPLViewer.csproj',
  'MainForm.cs', 'MainForm.Designer.cs', 'Program.cs', 'VoiceService.cs', 'WindowSettings.cs'
)
foreach ($file in $files) {
  Copy-Item -LiteralPath (Join-Path $sourceWorkspace $file) -Destination (Join-Path $importDir $file)
}
$sourceHashes = $files | ForEach-Object {
  [pscustomobject]@{ Name = $_; Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $sourceWorkspace $_)).Hash }
}
$copiedHashes = $files | ForEach-Object {
  [pscustomobject]@{ Name = $_; Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $importDir $_)).Hash }
}
if ((Compare-Object $sourceHashes $copiedHashes -Property Name,Hash).Count -ne 0) { throw 'KPLViewer import hash mismatch' }
$source = (Resolve-Path $importDir).Path
$toolsRoot = (Resolve-Path 'tools').Path
$target = Join-Path $toolsRoot 'THSBigOrder'
if (-not $source.StartsWith($toolsRoot + [IO.Path]::DirectorySeparatorChar)) { throw 'source escapes tools root' }
if (Test-Path -LiteralPath $target) { throw 'tools/THSBigOrder already exists' }
Move-Item -LiteralPath $source -Destination $target
Move-Item -LiteralPath "$target/KPLViewer.csproj" -Destination "$target/THSBigOrder.csproj"
Move-Item -LiteralPath "$target/KPLDataProvider.cs" -Destination "$target/THSBigOrderDataProvider.cs"
```

Expected: 目标目录存在，源目录不存在；没有其它目录被移动。

- [ ] **Step 2: 新建最小测试入口并确认名称测试 RED**

`THSBigOrder.Tests.csproj` 固定为 net48/x86/WinForms，并只引用生产项目：

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net48</TargetFramework>
    <UseWindowsForms>true</UseWindowsForms>
    <PlatformTarget>x86</PlatformTarget>
    <LangVersion>latest</LangVersion>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="..\THSBigOrder\THSBigOrder.csproj" />
  </ItemGroup>
</Project>
```

`Program.cs` 使用显式入口，不使用顶级语句：

```csharp
internal static class Program {
    [STAThread]
    private static int Main() {
        Run("Assembly and provider use THSBigOrder names", () => {
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Assembly.GetName().Name, "assembly");
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Namespace, "namespace");
        });
        return Environment.ExitCode;
    }
}
```

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，旧 namespace/class/assembly 仍存在。

- [ ] **Step 3: 统一项目、命名空间、类名和窗口产品名**

修改所有 C# 文件为 `namespace THSBigOrder`，`KPLDataProvider` 改为 `THSBigOrderDataProvider`，项目属性固定：

```xml
<AssemblyName>THSBigOrder</AssemblyName>
<RootNamespace>THSBigOrder</RootNamespace>
<AssemblyTitle>THSBigOrder</AssemblyTitle>
<Product>THS大单监控</Product>
<ApplicationIcon>icon.ico</ApplicationIcon>
<ApplicationManifest>app.manifest</ApplicationManifest>
```

窗口 `Name` 保持 `MainForm`，标题改为 `THS大单监控`。删除 `MainForm` 和 `AnalysisForm` 的在线图标下载回退，统一使用程序集/本地 `icon.ico`。`app.manifest` 同时声明 `dpiAware=true/pm` 和 `dpiAwareness=PerMonitorV2,PerMonitor`。在 `Properties/AssemblyInfo.cs` 添加 `[assembly: InternalsVisibleTo("THSBigOrder.Tests")]`。

- [ ] **Step 4: 运行名称测试和 Release 构建**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: PASS。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors。

- [ ] **Step 5: 确认没有生产标识残留**

Run: `rg -n "namespace KPLViewer|KPLDataProvider|Wzslinker-大单掘金|KPL_API_BASE|https?://" tools/THSBigOrder tools/THSBigOrder.Tests`

Expected: 生产代码无匹配；仅测试 fixture 中明确的本地代理 URL 可以匹配 `http://127.0.0.1:3000`。

- [ ] **Step 6: 提交命名迁移**

```powershell
git add tools/THSBigOrder tools/THSBigOrder.Tests
git commit -m "refactor: rename KPLViewer to THSBigOrder"
```

---

### Task 4: 用纯解析器建立三路数据合同

**Files:**
- Create: `tools/THSBigOrder/Models/MarketSnapshot.cs`
- Create: `tools/THSBigOrder/Parsing/ThsPayloadParser.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写四类大单和数值格式解析失败测试**

测试样本必须覆盖逗号价格、百分号、手数和完整时间：

```csharp
var item = parser.ParseOrder(JObject.Parse(@"{
  'nature':'主力主买','volume':'5,000手','avgprice':'1,215.00',
  'money':607500000,'otime':'2026-06-18 11:29:50'
}"));
AssertEqual(2, item.Type, "主动买 type");
AssertEqual(5000d, item.Volume, "volume");
AssertEqual(1215d, item.Price, "price");
AssertEqual(new DateTime(2026, 6, 18, 11, 29, 50), item.Time, "time");
```

再分别断言主力被买→3、主力主卖→4、主力被卖→1；未知性质必须返回结构化解析错误，不能默认为未知成交。

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，`ThsPayloadParser` 和读模型尚不存在。

- [ ] **Step 3: 实现最小读模型和纯解析器**

读模型至少包含：

```csharp
public enum DataFreshness { Fresh, Stale, Missing, Failed }
public sealed class ProxyEnvelope<T> {
    public bool Ok { get; set; }
    public bool Degraded { get; set; }
    public string ErrorCode { get; set; }
    public long FetchedAt { get; set; }
    public long ServedAt { get; set; }
    public T Data { get; set; }
}
public sealed class MarketSnapshot {
    public MarketSnapshot(
        string stockCode,
        StockSummary stock,
        MainFundSummary mainFunds,
        LimitUpContext limitUp,
        IReadOnlyList<BigOrderItem> orders,
        IReadOnlyList<PricePoint> prices,
        DataFreshness bigOrderFreshness,
        DataFreshness quoteFreshness,
        DataFreshness limitUpFreshness,
        DateTime bigOrderFetchedAt,
        DateTime refreshedAt) {
        StockCode = stockCode;
        Stock = stock;
        MainFunds = mainFunds;
        LimitUp = limitUp;
        Orders = orders;
        Prices = prices;
        BigOrderFreshness = bigOrderFreshness;
        QuoteFreshness = quoteFreshness;
        LimitUpFreshness = limitUpFreshness;
        BigOrderFetchedAt = bigOrderFetchedAt;
        RefreshedAt = refreshedAt;
    }
    public string StockCode { get; private set; }
    public StockSummary Stock { get; private set; }
    public MainFundSummary MainFunds { get; private set; }
    public LimitUpContext LimitUp { get; private set; }
    public IReadOnlyList<BigOrderItem> Orders { get; private set; }
    public IReadOnlyList<PricePoint> Prices { get; private set; }
    public DataFreshness BigOrderFreshness { get; private set; }
    public DataFreshness QuoteFreshness { get; private set; }
    public DataFreshness LimitUpFreshness { get; private set; }
    public DateTime BigOrderFetchedAt { get; private set; }
    public DateTime RefreshedAt { get; private set; }
}
```

- [ ] **Step 4: 增加 title、腾讯和涨停池解析测试**

使用真实结构的脱敏 fixture：`title.mainbuy="5.24亿"`、`title.mainsell="7.09亿"`、`pricechange=[{"1":"202606180930","2525646":0.5485}]`，断言：

```csharp
AssertEqual("博云新材", snapshot.Stock.Name, "name");
AssertEqual(28.36d, snapshot.Stock.Price, "price");
AssertEqual(20.56d, snapshot.Stock.TurnoverRate.Value, "turnover");
AssertEqual(0.82d, snapshot.Stock.VolumeRatio.Value, "volume ratio");
AssertEqual(3342254360d, snapshot.Stock.TotalAmount.Value, "amount");
AssertEqual(45049860d, snapshot.LimitUp.SealAmount.Value, "seal amount");
AssertEqual("首板", snapshot.LimitUp.HighDays, "high days");
AssertEqual(524000000d, snapshot.MainFunds.MainBuy, "main buy");
AssertEqual(709000000d, snapshot.MainFunds.MainSell, "main sell");
AssertEqual(-185000000d, snapshot.MainFunds.NetAmount, "main net");
AssertEqual(snapshot.Orders.Count, snapshot.MainFunds.OrderCount, "order count");
AssertEqual(new DateTime(2026, 6, 18, 9, 30, 0), snapshot.Prices[0].Time, "price point time");
AssertEqual(0.5485d, snapshot.Prices[0].ChangePercent, "price point pct");
```

成交额使用腾讯 `f5`；该字段已由代理按 `成交量（手）×100×现价` 生成。

固定腾讯代理字段合同：`f5=估算成交额`、`f6=成交量（手）`、`f8=换手率`、`f10=量比`。增加缺字段、字符串 `-`、NaN/Infinity 的 fixture，四个字段均不得把非有限值写入 `StockSummary`。

增加 proxy envelope 测试：HTTP 200 且 `ok=false/degraded=true` 必须先映射为失败状态；`ok=true` 且 `data.dragonMeta.cache.stale=true` 必须映射为 `DataFreshness.Stale`，并把顶层 `fetchedAt` 转换为 `BigOrderFetchedAt`。合法 `ok=true/list=[]` 仍是 Fresh 空列表。

`pricechange` 解析固定读取键 `1` 作为 `yyyyMMddHHmm` 时间，其余首个有限数值属性作为涨幅；缺时间、时间非法或无有限数值的点跳过并记录解析问题。`mainbuy/mainsell` 支持“万/亿”，字段缺失时为 nullable 缺失状态，不静默写 0。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有解析测试 PASS。

- [ ] **Step 6: 提交解析合同**

```powershell
git add tools/THSBigOrder/Models tools/THSBigOrder/Parsing tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: parse THS big-order snapshots"
```

---

### Task 5: 实现并行加载、同股 stale 回退和刷新互斥

**Files:**
- Modify: `tools/THSBigOrder/THSBigOrderDataProvider.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写三个并行 URL 和字段合并测试**

注入 `HttpMessageHandler`，记录 `PathAndQuery` 并返回三份 fixture。调用：

```csharp
var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
AssertSequence(new[] {
    "/api/big-order/ths-detail?stockCode=002297",
    "/api/limitup/10jqka",
    "/api/quotes/tencent?codes=002297"
}, handler.Paths.OrderBy(x => x).ToArray(), "paths");
AssertEqual("002297", snapshot.StockCode, "stock code");
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，旧 provider 仍直连 KPL/东财且没有 `LoadSnapshotAsync`。

- [ ] **Step 3: 实现代理专用 provider**

构造函数和入口固定为：

```csharp
public THSBigOrderDataProvider(HttpClient httpClient = null, string baseUrl = "http://127.0.0.1:3000")
public Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
```

内部用 `Task.WhenAll` 并行请求，并用 barrier fixture 证明三个请求在任一响应释放前都已发出。THS 大单为主数据；腾讯和涨停池各自捕获失败并写入 `DataFreshness.Failed`，不得让可选数据失败取消大单结果。所有响应先解析 `ProxyEnvelope` 或既有 quote/limit-up envelope；HTTP 200 degraded 不能当成功数据。

- [ ] **Step 4: 写同股 stale 与跨股隔离测试**

先成功加载 `002297`，再让 THS 请求失败：同代码应返回旧 orders 且 `BigOrderFreshness=Stale`。随后请求 `600519` 失败，必须抛出/返回该代码失败，不能带出 002297 数据。

```csharp
AssertEqual(DataFreshness.Stale, stale.BigOrderFreshness, "same-code stale");
AssertEqual("002297", stale.StockCode, "stale code");
AssertTrue(other.Orders.Count == 0, "no cross-code stale orders");
```

另加一组代理直接返回 HTTP 200、`ok=true`、`data.dragonMeta.cache.stale=true` 的 fixture，断言 freshness 为 Stale 且 UI 时间取缓存 `fetchedAt`；再分别覆盖网络拒绝和 Fresh 合法空列表。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: provider 合并与 stale 测试全部 PASS。

- [ ] **Step 6: 提交数据加载器**

```powershell
git add tools/THSBigOrder/THSBigOrderDataProvider.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: load THSBigOrder proxy snapshot"
```

---

### Task 6: 生成可测试的图表序列

**Files:**
- Create: `tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写分钟柱、累计净额和阈值热力测试**

给定 09:30 的主动买 100 万、被动买 50 万和主动卖 30 万，以及 09:31 的被动卖 20 万，断言：

```csharp
AssertEqual(1500000d, series.Minutes[0].BuyAmount, "09:30 buy");
AssertEqual(300000d, series.Minutes[0].SellAmount, "09:30 sell");
AssertEqual(1200000d, series.NetFlow[0].Value, "09:30 net");
AssertEqual(1000000d, series.Thresholds.Single(x => x.Amount == 1_000_000).BuyAmount, "100w buy");
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，series builder 尚不存在。

- [ ] **Step 3: 实现纯聚合器**

固定阈值为 `300000, 500000, 1000000, 3000000, 5000000, 7000000, 10000000` 元。分钟序列按交易日和分钟升序；净额为买盘（Type 2/3）减卖盘（Type 1/4）的累计值。

- [ ] **Step 4: 回归现有标记算法**

把 `CalculateMarkers` 保持为纯行为，并增加原有点火、砸盘、买活跃、承接好 fixture；不在本任务改变阈值公式。

- [ ] **Step 5: 运行全部 C# 测试**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: PASS，0 failed。

- [ ] **Step 6: 提交聚合器**

```powershell
git add tools/THSBigOrder/Analytics tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: build big-order chart series"
```

---

### Task 7: 实现双缓冲图表控件

**Files:**
- Create: `tools/THSBigOrder/Controls/BigOrderChartControl.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写图表空数据与序列绑定合同测试**

测试不比较像素，只验证无数据绘制不会抛错、设置 Snapshot 后生成三层区域：

```csharp
using (var control = new BigOrderChartControl()) {
    control.Size = new Size(1000, 650);
    control.SetSnapshot(snapshot, series);
    AssertEqual(3, control.LayoutBands.Count, "price/volume/heat bands");
    using (var bitmap = new Bitmap(1000, 650)) control.DrawToBitmap(bitmap, control.ClientRectangle);
}
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，控件不存在。

- [ ] **Step 3: 实现最小双缓冲控件**

构造函数启用：

```csharp
SetStyle(ControlStyles.AllPaintingInWmPaint |
         ControlStyles.OptimizedDoubleBuffer |
         ControlStyles.ResizeRedraw |
         ControlStyles.UserPaint, true);
```

`OnPaint` 依次绘制网格与时间轴、价格/涨幅线、累计净额线、信号点、分钟大单柱、阈值热力。空数据绘制“等待大单数据”，陈旧数据绘制右上角琥珀色“数据陈旧”。所有 `Pen`、`Brush`、`Font` 必须确定性释放。

- [ ] **Step 4: 运行图表合同测试与构建**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: PASS。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded。

- [ ] **Step 5: 提交图表控件**

```powershell
git add tools/THSBigOrder/Controls tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: render THS big-order chart"
```

---

### Task 8: 重建主界面布局并绑定快照

**Files:**
- Modify: `tools/THSBigOrder/MainForm.Designer.cs`
- Modify: `tools/THSBigOrder/MainForm.cs`
- Create: `tools/THSBigOrder/Filtering/OrderFilter.cs`
- Create: `tools/THSBigOrder/Refresh/RefreshCoordinator.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写主窗体布局合同测试**

实例化 `MainForm` 后断言：

```csharp
AssertEqual(Orientation.Vertical, form.MainSplit.Orientation, "split orientation");
AssertTrue(form.MainSplit.SplitterDistance >= form.ClientSize.Width * 0.65, "left chart share");
AssertEqual("全部", form.OrderTabs.TabPages[0].Text, "all tab");
AssertEqual("买盘", form.OrderTabs.TabPages[1].Text, "buy tab");
AssertEqual("卖盘", form.OrderTabs.TabPages[2].Text, "sell tab");
```

为测试暴露 `internal` 只读控件属性，并使用 `InternalsVisibleTo("THSBigOrder.Tests")`；不得增加测试专用可写入口。

测试项目使用 `[STAThread]` 显式 Main。`MainForm` 增加 internal 依赖注入构造函数，传入 fake provider、关闭真实 VoiceService 初始化和窗口 Load 网络行为；生产无参构造函数保持原行为。

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，旧窗口仍是 400px 单表格布局。

- [ ] **Step 3: 实现 72/28 高密度布局**

使用顶层 `TableLayoutPanel`：顶部信息区固定高度、主体 `SplitContainer` 填充、底部状态栏固定。左侧放 `BigOrderChartControl`，右侧放 tab + DataGridView；默认窗口 1280×800，最小窗口 960×640，仍允许保存/恢复窗口尺寸。

顶部新增只读标签：`lblPrice`、`lblMainBuy`、`lblMainSell`、`lblMainNet`、`lblSealAmount`、`lblOpenCount`、`lblHighDays`、`lblSealRate`、`lblLimitUpReason`、`lblFreshness`。

在 `OnClientSizeChanged` 应用固定宽度档位：宽度 `<1100` 隐藏完整 `lblLimitUpReason` 并显示短提示；宽度 `<1020` 再隐藏 `lblSealRate` 和最后涨停时间；恢复宽度后全部恢复。布局测试依次设置 1280、1080、980、1280 宽度并断言 Visible 状态可逆。

- [ ] **Step 4: 把 RefreshDataAsync 改为快照绑定**

刷新入口使用 `RefreshCoordinator` 管理代码、取消令牌和单调递增代次：

```csharp
var request = _refreshCoordinator.Begin(_currentStockCode, forceForCodeChange);
if (!request.ShouldRun) return;
try {
    var snapshot = await _dataProvider.LoadSnapshotAsync(request.StockCode, request.CancellationToken);
    if (!_refreshCoordinator.IsLatest(request.Generation, snapshot.StockCode)) return;
    BindSnapshot(snapshot);
} catch (OperationCanceledException) when (request.CancellationToken.IsCancellationRequested) {
    return;
}
```

`BindSnapshot` 一次更新顶部标签、过滤后的明细、统计、图表和状态栏。非涨停池显示“非涨停池”；涨停接口失败显示“涨停数据不可用”；腾讯失败的三个字段显示 `-`。

先写并运行竞态失败测试：002297 请求挂起时切换到 600519，完成顺序为 600519→002297，最终绑定必须保持 600519；同代码定时重入只执行一次，手工切股必须取消旧请求并运行最新代码。预期取消不得形成未处理异常，也不得把状态栏覆盖为“刷新失败”。

- [ ] **Step 5: 保留筛选、通达信跟随、置顶、自动刷新、语音和分析入口**

“全部/买盘/卖盘”只改变明细过滤，不重新请求。现有金额按钮与点火/砸盘等特殊筛选继续叠加；代码切换清除旧筛选视图，但不清除用户选择的金额阈值。

把组合过滤提取到 `OrderFilter.Apply(orders, minimumAmount, side, specialMarker)`，测试金额+买卖+点火/砸盘/买活跃/承接好的组合结果。补以下回归：

- 锁定代码时忽略通达信/剪贴板切换，解锁后接受最新代码。
- 自动刷新同代码不重入，置顶只改变 `TopMost`。
- 分析窗接收当前股票代码、名称和过滤后的订单。
- 语音去重 key 必须包含股票代码、成交时间、类型和金额，切股后相同时间/金额不得互相吞掉。

- [ ] **Step 6: 运行布局测试和 Release 构建**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: PASS。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors。

- [ ] **Step 7: 提交主界面**

```powershell
git add tools/THSBigOrder/MainForm.cs tools/THSBigOrder/MainForm.Designer.cs tools/THSBigOrder/Filtering tools/THSBigOrder/Refresh tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: build THS big-order terminal layout"
```

---

### Task 9: 代理与桌面端集成验收

**Files:**
- Modify only if verification reveals a scoped defect in files already listed above.

- [ ] **Step 1: 运行完整代理测试**

Run: `node --test proxy-server/__tests__`

Expected: 全部 PASS，0 failed。

- [ ] **Step 2: 运行全部 THSBigOrder 测试**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 输出每个测试 `PASS`，进程退出码 0。

- [ ] **Step 3: 构建 Release**

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 warnings/0 errors；若存在预先已有 warning，记录精确内容，不虚报 0 warnings。

- [ ] **Step 4: 启动代理并做接口冒烟**

启动：`npm run start`（工作目录 `proxy-server`）。

依次请求：

```powershell
Invoke-RestMethod 'http://127.0.0.1:3000/health'
Invoke-RestMethod 'http://127.0.0.1:3000/api/big-order/ths-detail?stockCode=002297'
Invoke-RestMethod 'http://127.0.0.1:3000/api/quotes/tencent?codes=002297'
Invoke-RestMethod 'http://127.0.0.1:3000/api/limitup/10jqka'
```

Expected: health ok；THS 响应 envelope、title/list/pricechange 结构合法（list 允许为空）；腾讯 `f5/f6/f8/f10` 合同可解析；当日涨停池结构合法。固定 `002297/20260618` 只用于自动测试 fixture，不作为实时成功条件。

- [ ] **Step 5: 真实运行 WinForms 并检查三类股票状态**

先从当日 `/api/limitup/10jqka` 的 `data.info` 动态选择一只有大单明细的股票作为 `CURRENT_LIMIT_UP_CODE`，记录代码、交易日期和响应时间。再运行 `tools/THSBigOrder/bin/Release/net48/THSBigOrder.exe`，检查：

- `CURRENT_LIMIT_UP_CODE`：顶部换手/量比、封单/开板/连板、主图和明细按实时响应展示。
- `600519`：普通股票大单和行情可用，涨停区显示“非涨停池”。
- 非法代码：不发上游请求，状态栏显示明确输入错误。

- [ ] **Step 6: 验证代理离线和自动恢复**

停止代理后手工刷新：同代码保留最后大单并显示“数据陈旧/代理服务未启动”；切换新代码不得展示旧股票。恢复代理后下一次刷新恢复 Fresh。

- [ ] **Step 7: 检查桌面视觉和 DPI**

在 100%、125%、150% 缩放分别记录操作系统缩放、`DeviceDpi`、窗口尺寸和截图，检查：顶部标签不重叠；1100/1020 两个宽度档位隐藏/恢复正确；右侧关键列可读；主图无明显闪烁；窗口缩放不抛异常；最小尺寸下不出现负 SplitterDistance。若有两台不同 DPI 显示器，再验证运行中跨屏切换；只有一台显示器时明确记录该项未覆盖。

- [ ] **Step 8: 审计最终 diff**

Run: `git status --short`

Expected: 只包含本计划涉及的 proxy、THSBigOrder、THSBigOrder.Tests 和文档；不得包含 `.superpowers/`、TdxL2Helper 用户改动、构建产物或临时截图。

Run: `rg -n "eastmoney|KPL_API_BASE|namespace KPLViewer|Wzslinker-大单掘金|https?://" tools/THSBigOrder`

Expected: 无品牌残留和外部 URL；只允许默认本地代理 URL `http://127.0.0.1:3000`。

- [ ] **Step 9: 最终提交（仅存在未提交的验收修复时）**

```powershell
git add -- proxy-server/app.js proxy-server/routes/bigOrder.js proxy-server/routes/market.js proxy-server/helpers/proxyCache.js proxy-server/server.js proxy-server/openapi.js proxy-server/__tests__/thsBigOrder.test.mjs proxy-server/__tests__/thsLimitupPools.test.mjs proxy-server/__tests__/docs.test.mjs tools/THSBigOrder tools/THSBigOrder.Tests docs/kpl-viewer/2026-06-19-ths-big-order-design.md docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md
git commit -m "fix: finish THSBigOrder integration"
```

若没有验收修复，不创建空提交。

---

## 2026-06-19 分时坐标与八段成交统计增量计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking。用户已明确本轮不启用 subagent。

**Goal:** 为 THSBigOrder 补齐左右价格/涨幅轴、四小时主图竖格、八个 30 分钟底部竖格，并用腾讯个股分钟累计成交额与同花顺大单逐笔生成双层金额统计。

**Architecture:** `proxy-server` 新增腾讯个股分钟分时规范化路由，桌面端继续只访问本地代理。`MarketSnapshot` 保存分钟累计成交额，纯 `BigOrderSeriesBuilder` 负责差分和八段聚合，`BigOrderChartControl` 只负责布局与绘制，避免把数据口径塞进 UI。

**Tech Stack:** Node.js ES modules、Express、`node:test`、C# net48 WinForms、Newtonsoft.Json、现有控制台测试入口。

### Task 10: 新增腾讯个股分钟分时代理

**Files:**
- Modify: `proxy-server/routes/quotes.js`
- Modify: `proxy-server/helpers/proxyCache.js`
- Create: `proxy-server/__tests__/tencentMinute.test.mjs`
- Modify: `proxy-server/__tests__/docs.test.mjs`
- Modify: `proxy-server/openapi.js`
- Modify: `proxy-server/server.js`

- [ ] **Step 1: 写腾讯分钟路由失败测试**

在 `tencentMinute.test.mjs` 构造包含 `date` 和累计值的真实结构 fixture，断言六位代码校验、沪深市场前缀、结构化分钟点和缓存元信息：

```js
test('tencent minute route normalizes cumulative turnover rows', async () => {
  let upstreamUrl = ''
  const app = createProxyApp({
    logRequests: false,
    runtimeCache: new ProcessMemoryCache(),
    clients: {
      client: {},
      plainClient: { get: async (url) => {
        upstreamUrl = String(url)
        return { data: { code: 0, data: { sz002297: { data: {
          date: '20260618',
          data: ['0930 25.70 11848 30449360.00', '0931 26.25 71011 184435426.43'],
        } } } } }
      } },
    },
  })
  const { server, baseUrl } = await listen(app)
  try {
    const response = await fetch(`${baseUrl}/api/quotes/tencent/minute?code=002297`)
    const body = await response.json()
    assert.equal(response.status, 200)
    assert.match(upstreamUrl, /code=sz002297/)
    assert.equal(body.ok, true)
    assert.equal(body.data.date, '20260618')
    assert.deepEqual(body.data.points[1], {
      time: '0931', price: 26.25, cumulativeVolume: 71011, cumulativeAmount: 184435426.43,
    })
  } finally { server.close() }
})
```

另写 `code=abc` 返回 400、上游 `code!=0` 返回 degraded、重复请求只调用一次上游、TTL 后上游失败返回 stale 的测试。

- [ ] **Step 2: 运行代理测试确认 RED**

Run: `node --test proxy-server/__tests__/tencentMinute.test.mjs`

Expected: FAIL，`/api/quotes/tencent/minute` 返回 404。

- [ ] **Step 3: 实现最小规范化路由**

在 `quotes.js` 增加并由 `registerQuoteRoutes` 注册：

```js
function normalizeSingleCode(value) {
  const code = cleanCode(value)
  return /^\d{6}$/.test(code) ? code : ''
}

function parseTencentMinutePayload(payload, stockCode) {
  if (Number(payload?.code) !== 0) throw new Error(payload?.msg || 'tencent minute error')
  const marketCode = `${stockCode.startsWith('6') ? 'sh' : 'sz'}${stockCode}`
  const source = payload?.data?.[marketCode]?.data
  if (!source || !Array.isArray(source.data)) throw new Error('invalid tencent minute payload')
  const points = source.data.map((row) => {
    const [time, price, cumulativeVolume, cumulativeAmount] = String(row).trim().split(/\s+/)
    const point = {
      time,
      price: Number(price),
      cumulativeVolume: Number(cumulativeVolume),
      cumulativeAmount: Number(cumulativeAmount),
    }
    if (!/^\d{4}$/.test(time) || !Number.isFinite(point.price) ||
        !Number.isFinite(point.cumulativeVolume) || !Number.isFinite(point.cumulativeAmount)) {
      throw new Error('invalid tencent minute row')
    }
    return point
  })
  return { date: String(source.date || ''), points }
}
```

路由使用 `runtimeCache.remember('quotes:tencent-minute:v1:' + code, { ttlSeconds, staleTtlSeconds: ttlSeconds * 6 }, loader)`，成功返回 `ok/source/stockCode/fetchedAt/servedAt/data`，失败使用 `sendDegraded`。在 `PROXY_CACHE_TTLS.quotes` 增加 `tencentMinute: 5`。

- [ ] **Step 4: 运行路由测试确认 GREEN**

Run: `node --test proxy-server/__tests__/tencentMinute.test.mjs`

Expected: 全部 PASS，0 failed。

- [ ] **Step 5: 补齐路由清单和 OpenAPI 合同**

在 `server.js` 增加 `GET  /api/quotes/tencent/minute`；在 `openapi.js` 声明必填 query 参数 `code`；在 `docs.test.mjs` 断言：

```js
assert.ok(body.paths['/api/quotes/tencent/minute'].get)
assert.equal(body.paths['/api/quotes/tencent/minute'].get.parameters[0].name, 'code')
```

- [ ] **Step 6: 运行代理完整测试并提交**

Run: `node --test proxy-server/__tests__`

Expected: 全部 PASS，0 failed。

```powershell
git add -- proxy-server/routes/quotes.js proxy-server/helpers/proxyCache.js proxy-server/__tests__/tencentMinute.test.mjs proxy-server/__tests__/docs.test.mjs proxy-server/openapi.js proxy-server/server.js
git commit -m "feat(proxy): add Tencent minute turnover route"
```

### Task 11: 把分钟累计成交额合并进桌面快照

**Files:**
- Modify: `tools/THSBigOrder/Models/MarketSnapshot.cs`
- Modify: `tools/THSBigOrder/Parsing/ThsPayloadParser.cs`
- Modify: `tools/THSBigOrder/THSBigOrderDataProvider.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写四路并行和分钟解析失败测试**

扩展 `FixtureHandler` 返回：

```json
{"ok":true,"data":{"date":"20260618","points":[
  {"time":"0930","price":25.70,"cumulativeVolume":11848,"cumulativeAmount":30449360.00},
  {"time":"0931","price":26.25,"cumulativeVolume":71011,"cumulativeAmount":184435426.43}
]}}
```

断言请求路径包含 `/api/quotes/tencent/minute?code=002297`、`PeakPending=4`、日期和累计额正确；再覆盖 degraded、非法时间、负累计额和非有限值不会进入快照。

- [ ] **Step 2: 运行 C# 测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，当前 provider 只有三路请求且 `MarketSnapshot` 没有分钟成交额。

- [ ] **Step 3: 增加分钟模型并保持构造调用显式**

在 `MarketSnapshot.cs` 增加：

```csharp
public sealed class MinuteTurnoverPoint
{
    public DateTime Time { get; set; }
    public double Price { get; set; }
    public double CumulativeVolume { get; set; }
    public double CumulativeAmount { get; set; }
}
```

`MarketSnapshot` 构造函数增加 `IReadOnlyList<MinuteTurnoverPoint> minuteTurnover` 和 `DataFreshness minuteTurnoverFreshness`，并新增同名只读属性。所有构造点明确传入值，不增加隐藏默认行为。

- [ ] **Step 4: 实现分钟 envelope 解析和四路并行**

在 parser 增加 `ParseMinuteTurnover(JObject envelope, List<string> issues)`：使用 `data.date` 的 `yyyyMMdd` 日期与 `HHmm` 拼接 `DateTime`，只保留交易时间、非负且单调不减的累计成交额。provider 增加：

```csharp
var minuteTask = TryGetJsonAsync("/api/quotes/tencent/minute?code=" + stockCode, cancellationToken);
await Task.WhenAll((Task)bigTask, quoteTask, minuteTask, limitTask).ConfigureAwait(false);
```

分钟接口是可选源：失败不阻断大单；同股 stale 回退保留缓存分钟序列，但 freshness 必须为 `Stale`，跨股不得复用。

- [ ] **Step 5: 运行 C# 测试确认 GREEN 并提交**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 全部 PASS，0 failed。

```powershell
git add -- tools/THSBigOrder/Models/MarketSnapshot.cs tools/THSBigOrder/Parsing/ThsPayloadParser.cs tools/THSBigOrder/THSBigOrderDataProvider.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat(tools): load Tencent minute turnover"
```

### Task 12: 生成八个 30 分钟双层金额序列

**Files:**
- Modify: `tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs`
- Modify: `tools/THSBigOrder/MainForm.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写边界、午休和差分失败测试**

新增测试数据覆盖 `09:30`、`09:59`、`10:00`、`11:30`、`13:00`、`14:30`、`15:00`，断言：

```csharp
AssertEqual(8, series.HalfHours.Count, "eight half-hours");
AssertEqual(184435426.43d, series.HalfHours[0].TotalAmount, "first cumulative amount");
AssertEqual(1800000d, series.HalfHours[0].BigOrderAmount, "first big-order total");
AssertEqual(0d, series.HalfHours[4].TotalAmount, "13:00 unchanged cumulative");
AssertEqual("14:30-15:00", series.HalfHours[7].Label, "last label");
```

边界规则固定为左闭右开，上午收盘点 `11:30` 计入第四格、全天收盘点 `15:00` 计入第八格；大单额固定为 `BuyAmount + SellAmount`，不使用净额。

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，`HalfHours` 尚不存在。

- [ ] **Step 3: 实现纯聚合器**

增加：

```csharp
public sealed class HalfHourAmount
{
    public string Label { get; set; }
    public double? TotalAmount { get; set; }
    public double BigOrderAmount { get; set; }
}
```

增加 `Build(IEnumerable<BigOrderItem> source, IEnumerable<MinuteTurnoverPoint> turnover, DataFreshness turnoverFreshness)`；保留现有单参数重载并转发为 Missing 分钟源，避免破坏已有分析测试。先按时间排序累计点，以当前累计额减上一有效累计额得到分钟成交额，再映射到固定八段；大单逐笔按同一边界直接求 `Amount` 总和。`turnoverFreshness` 为 Missing/Failed 时八段 `TotalAmount=null`；Fresh/Stale 的合法空源保持 `0`。

- [ ] **Step 4: 更新绑定并运行测试确认 GREEN**

`MainForm.BindSnapshot` 调用：

```csharp
bigOrderChart.SetSnapshot(snapshot,
    new BigOrderSeriesBuilder().Build(
        snapshot.Orders,
        snapshot.MinuteTurnover,
        snapshot.MinuteTurnoverFreshness));
```

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 全部 PASS，0 failed。

- [ ] **Step 5: 提交聚合改动**

```powershell
git add -- tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs tools/THSBigOrder/MainForm.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat(tools): aggregate half-hour turnover bands"
```

### Task 13: 绘制双轴、四小时网格和八段双层底栏

**Files:**
- Modify: `tools/THSBigOrder/Controls/BigOrderChartControl.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写布局和绘图合同失败测试**

为控件增加只读布局合同，测试只验证几何与刻度，不做脆弱像素比对：

```csharp
control.Size = new Size(1000, 650);
control.SetSnapshot(snapshot, series);
AssertTrue(control.LayoutBands[0].Left >= 52, "left price axis margin");
AssertTrue(control.ClientSize.Width - control.LayoutBands[0].Right >= 48, "right pct axis margin");
AssertEqual(5, control.HourGridXs.Count, "four hour cells");
AssertEqual(9, control.HalfHourGridXs.Count, "eight half-hour cells");
AssertEqual(2, control.HalfHourRows.Count, "turnover and big-order rows");
using (var bitmap = new Bitmap(1000, 650))
    control.DrawToBitmap(bitmap, control.ClientRectangle);
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，轴边距和网格合同不存在。

- [ ] **Step 3: 调整布局与统一纵轴映射**

`RebuildLayout` 使用左轴约 52px、右轴约 48px；价格主图、分钟柱和底部统计共用同一个交易时间绘图区。纵轴范围包含 `0%` 与全部有效涨幅，上下各留 5% 余量，范围不足 2% 时扩展至 2%。昨收价计算固定为：

```csharp
var previousClose = stock.Price.HasValue && stock.ChangePercent.HasValue
    ? stock.Price.Value / (1d + stock.ChangePercent.Value / 100d)
    : (double?)null;
var price = previousClose.HasValue ? previousClose.Value * (1d + percent / 100d) : (double?)null;
```

左轴按价格显示两位小数，右轴显示带符号百分比；无昨收时左轴显示 `-`。

- [ ] **Step 4: 绘制四小时和八个 30 分钟竖格**

主图区边界对应交易分钟 `0/60/120/180/240`；底部边界对应 `0/30/60/90/120/150/180/210/240`。午休通过现有 `TimeX` 压缩，不额外占宽。主图时间标签显示 `09:30`、`10:30`、`11:30/13:00`、`14:00`、`15:00`。

- [ ] **Step 5: 完全替换阈值热力绘制**

删除 `DrawThresholds` 调用和阈值色块绘制，新增 `DrawHalfHourAmounts`。每格上层绘制 `TotalAmount`，下层绘制 `BigOrderAmount`；统一使用 `万/亿` 紧凑格式，缺失总成交额显示 `-`，其余显示 `0`。两行分别使用中性灰蓝和红色强调，但保持暗色交易终端对比度。

- [ ] **Step 6: 运行测试与 Release 构建确认 GREEN**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 全部 PASS，0 failed。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors；记录实际 warning 数量。

- [ ] **Step 7: 提交图表改动**

```powershell
git add -- tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat(tools): draw intraday axes and turnover bands"
```

### Task 14: 集成、真实窗口与视觉验收

**Files:**
- Modify only if verification reveals a scoped defect in the files listed in Tasks 10-13.
- Update: `docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md`

- [ ] **Step 1: 运行完整自动化验证**

Run: `node --test proxy-server/__tests__`

Expected: 全部 PASS，0 failed。

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有测试输出 `PASS`，退出码 0。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors。

- [ ] **Step 2: 使用独立端口做实时接口冒烟**

在 `proxy-server` 目录以 `PORT=3011` 启动当前源码，避免影响用户正在运行的 3000 端口代理。请求：

```powershell
Invoke-RestMethod 'http://127.0.0.1:3011/api/quotes/tencent/minute?code=002297'
Invoke-RestMethod 'http://127.0.0.1:3011/api/big-order/ths-detail?stockCode=002297'
```

Expected: 分钟响应包含 `date`、242 个以内的有效点及单调累计成交额（腾讯同时返回 `11:30` 和 `13:00` 两个午间边界点）；大单响应可用于八段聚合。

- [ ] **Step 3: 启动真实 WinForms 并截图验收**

运行 `tools/THSBigOrder/bin/Release/net48/THSBigOrder.exe`，检查：

- 左侧价格标签可读且不覆盖曲线。
- 右侧涨幅标签与同一水平网格对齐。
- 主图恰好四个交易小时竖格，午休不占宽。
- 底部恰好八格、两行，原阈值热力不再出现。
- 第一行总和与腾讯当日累计成交额末值一致；第二行总和与同花顺大单 `Amount` 总和一致。
- 1280×800 和最小 960×640 下无裁切、负宽度或文字严重重叠。

- [ ] **Step 4: 审计 diff 和文档状态**

Run: `git status --short`

Expected: 不包含用户已有 `tools/TdxL2Helper/**`、`tools/tdx_l2_reader.py` 或其它无关改动。

Run: `git diff --check HEAD~4..HEAD`

Expected: 无空白错误。

- [ ] **Step 5: 仅在验收产生修复时提交**

```powershell
git add -- proxy-server/routes/quotes.js proxy-server/helpers/proxyCache.js proxy-server/__tests__/tencentMinute.test.mjs proxy-server/__tests__/docs.test.mjs proxy-server/openapi.js proxy-server/server.js tools/THSBigOrder/Models/MarketSnapshot.cs tools/THSBigOrder/Parsing/ThsPayloadParser.cs tools/THSBigOrder/THSBigOrderDataProvider.cs tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs tools/THSBigOrder/MainForm.cs tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md
git commit -m "fix: finish THSBigOrder intraday chart upgrade"
```

若没有验收修复，不创建空提交。

### 增量执行结果

- 代理测试：68/68 PASS，0 failed。
- THSBigOrder 测试：17/17 PASS，退出码 0。
- Release 构建：0 warnings，0 errors。
- 实时腾讯分钟接口：`002297` 返回交易日 `20260618`、242 个分钟点、末值累计成交额 `3292498651.54` 元。
- 实时同花顺大单接口：`002297` 返回 1263 条大单、241 个分时涨幅点。
- 真实 WinForms：已检查 1113×679 与最小 960×640；左价格轴、右涨幅轴、四个交易小时格、八个 30 分钟格和两层金额均可读，右侧原有金额筛选按钮保留。
- 金额对账：八段第一层合计对应腾讯末值累计成交额；八段第二层合计对应同花顺主买与主卖金额之和。
- 验收截图只保存在忽略的 `.tmp/` 中，不纳入提交。

---

## 2026-06-20 均价线与双层热力增量计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking。用户已明确本轮采用 Inline Execution，暂不启用 subagent。

**Goal:** 保持基础行情与完整分时都走腾讯代理，把主图改为共轴的“腾讯全成交累计均价（黄线）+ 同花顺大单累计成交均价（白线）”，并为底部两层八段金额增加各自独立归一化的热力填充。

**Architecture:** 不修改代理合同和 `python-bridge`。`BigOrderSeriesBuilder` 从现有腾讯分钟累计量额与同花顺大单价格/手数生成两个价格量纲的纯序列；`BigOrderChartControl` 只用这两个序列建立统一价格/涨幅轴并绘制。底部热力比例在控件中按行独立计算，缺失值与零值保持不同展示语义。

**Tech Stack:** C#、.NET Framework 4.8、WinForms、System.Drawing、现有无框架控制台测试入口。

### 文件职责

- Modify `tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs`：新增市场累计均价和大单累计加权均价两个纯序列；保留既有 `NetFlow` 数据供分析逻辑使用，但主图不再消费它。
- Modify `tools/THSBigOrder/Controls/BigOrderChartControl.cs`：两条均价线共轴绘制、腾讯价格缺失时使用 THS 涨幅兜底、双层热力比例与填充。
- Modify `tools/THSBigOrder.Tests/Program.cs`：均价公式、异常点、统一轴、兜底和双层独立归一化合同测试。
- Update `docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md`：记录本轮验证结果和仍未覆盖的真实环境项。

### Task 15: 用纯聚合器生成两条累计成交均价

**Files:**
- Modify: `tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [x] **Step 1: 写腾讯全成交累计均价失败测试**

在测试入口注册 `Run("Series builder computes Tencent market VWAP", TestMarketAveragePrices)`，fixture 使用腾讯字段的真实单位：累计成交量为“手”，累计成交额为“元”。核心断言：

```csharp
var day = new DateTime(2026, 6, 20);
var turnover = new[]
{
    new MinuteTurnoverPoint
    {
        Time = day.AddHours(9).AddMinutes(30),
        CumulativeVolume = 11848,
        CumulativeAmount = 30449360,
    },
    new MinuteTurnoverPoint
    {
        Time = day.AddHours(9).AddMinutes(31),
        CumulativeVolume = 71011,
        CumulativeAmount = 184435426.43,
    },
};
var series = new BigOrderSeriesBuilder().Build(
    new BigOrderItem[0], turnover, DataFreshness.Fresh);
AssertNear(25.70d, series.MarketAveragePrices[0].Price, 0.001d, "09:30 market VWAP");
AssertNear(25.9728d, series.MarketAveragePrices[1].Price, 0.001d, "09:31 market VWAP");
```

再加入累计手数为 `0`、累计额为负数、`NaN`、`Infinity` 和乱序输入；断言无效点被跳过，有效结果按时间升序，且午休前后仍直接使用各时点累计值，不做二次差分。

测试入口现有断言工具没有浮点误差比较；本步骤同时增加：

```csharp
private static void AssertNear(double expected, double actual, double tolerance, string label)
{
    if (Math.Abs(expected - actual) > tolerance)
        throw new InvalidOperationException(
            label + ": expected " + expected + ", actual " + actual);
}
```

- [x] **Step 2: 运行 C# 测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，`BigOrderSeries` 尚无 `MarketAveragePrices`。

- [x] **Step 3: 写同花顺大单累计加权均价失败测试**

注册 `Run("Series builder computes cumulative big-order average price", TestBigOrderAveragePrices)`；使用价格与手数差异明显的三笔订单，证明不是简单算术平均，也不是用界面四舍五入后的金额反推：

```csharp
var orders = new[]
{
    new BigOrderItem { Time = day.AddHours(9).AddMinutes(30), Price = 10, Volume = 100, Amount = 99999, Type = 2 },
    new BigOrderItem { Time = day.AddHours(9).AddMinutes(31), Price = 20, Volume = 300, Amount = 1, Type = 3 },
    new BigOrderItem { Time = day.AddHours(9).AddMinutes(32), Price = 30, Volume = 100, Amount = 1, Type = 4 },
};
var series = new BigOrderSeriesBuilder().Build(orders);
AssertNear(10d, series.BigOrderAveragePrices[0].Price, 0.0001d, "first big-order average");
AssertNear(17.5d, series.BigOrderAveragePrices[1].Price, 0.0001d, "weighted big-order average");
AssertNear(20d, series.BigOrderAveragePrices[2].Price, 0.0001d, "cumulative big-order average");
```

补充 `Price <= 0`、`Volume <= 0`、`NaN` 和 `Infinity` 输入；这些订单仍可留在其它既有统计口径中，但不得进入累计均价的分子或分母。

- [x] **Step 4: 实现最小价格序列模型和公式**

在 `BigOrderSeriesBuilder.cs` 增加：

```csharp
public sealed class AveragePricePoint
{
    public DateTime Time { get; set; }
    public double Price { get; set; }
}
```

`BigOrderSeries` 增加：

```csharp
public IReadOnlyList<AveragePricePoint> MarketAveragePrices { get; set; }
public IReadOnlyList<AveragePricePoint> BigOrderAveragePrices { get; set; }
```

腾讯市场均价只在 `turnoverFreshness` 为 `Fresh/Stale` 时生成，并且只接受有限且 `CumulativeVolume > 0`、`CumulativeAmount >= 0` 的点：

```csharp
var marketAveragePrices = hasTurnover
    ? (turnover ?? Enumerable.Empty<MinuteTurnoverPoint>())
        .Where(point => IsFinite(point.CumulativeVolume) &&
                        IsFinite(point.CumulativeAmount) &&
                        point.CumulativeVolume > 0 &&
                        point.CumulativeAmount >= 0)
        .OrderBy(point => point.Time)
        .Select(point => new AveragePricePoint
        {
            Time = point.Time,
            Price = point.CumulativeAmount / (point.CumulativeVolume * 100d),
        })
        .Where(point => IsFinite(point.Price) && point.Price > 0)
        .ToList()
    : new List<AveragePricePoint>();
```

同花顺大单均价按时间累加 `Price * Volume` 与 `Volume`，每个有效订单生成一个点：

```csharp
double weightedPrice = 0;
double cumulativeVolume = 0;
var bigOrderAveragePrices = new List<AveragePricePoint>();
foreach (var order in orders.Where(IsValidPriceVolume))
{
    weightedPrice += order.Price * order.Volume;
    cumulativeVolume += order.Volume;
    bigOrderAveragePrices.Add(new AveragePricePoint
    {
        Time = order.Time,
        Price = weightedPrice / cumulativeVolume,
    });
}
```

增加局部 `IsFinite`/`IsValidPriceVolume` 私有方法，不引入新工具类或依赖。把两个序列写入 `BigOrderSeries` 返回值；不删除 `NetFlow` 和 `Thresholds`，避免扩大本轮影响面。

- [x] **Step 5: 运行测试确认 GREEN 并提交**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有测试输出 `PASS`，退出码 0。

```powershell
git add -- tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat(tools): compute intraday average price series"
```

### Task 16: 两条均价线共用价格/涨幅轴

**Files:**
- Modify: `tools/THSBigOrder/Controls/BigOrderChartControl.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [x] **Step 1: 写统一轴和线数据合同失败测试**

给 `BigOrderChartControl.cs` 增加公开只读合同类型；它表示最终交给主图的涨幅坐标，不暴露 GDI 对象：

```csharp
public sealed class ChartLinePoint
{
    public DateTime Time { get; set; }
    public double Value { get; set; }
}
```

控件公开 `IReadOnlyList<ChartLinePoint> MarketLinePercents` 和 `BigOrderLinePercents`。构造 `StockSummary.Price=11`、`ChangePercent=10`（反推昨收 `10`）、市场均价 `10.5/11`、大单均价 `10.2/10.8`，断言：

```csharp
AssertNear(5d, control.MarketLinePercents[0].Value, 0.0001d, "market line shared percent");
AssertNear(10d, control.MarketLinePercents[1].Value, 0.0001d, "market line second percent");
AssertNear(2d, control.BigOrderLinePercents[0].Value, 0.0001d, "big-order line shared percent");
AssertNear(8d, control.BigOrderLinePercents[1].Value, 0.0001d, "big-order line second percent");
AssertTrue(control.AxisTicks.First().Percent <= 0, "axis contains zero percent");
AssertTrue(control.AxisTicks.Last().Percent >= 10, "axis contains both lines");
```

再构造腾讯市场均价空、`snapshot.Prices` 有值的情况，断言黄线回退到 THS 涨幅；腾讯均价一旦存在就不得混入 THS 点。白线只来自 `BigOrderAveragePrices`，不读取 `NetFlow`。

- [x] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，控件仍把 THS `pricechange` 画为黄线，并把 `NetFlow` 独立缩放为白线。

- [x] **Step 3: 建立昨收与价格转涨幅的单一映射**

在控件中缓存 `_previousClose`，计算优先级固定为：

```csharp
var denominator = 1d + _snapshot.Stock.ChangePercent.GetValueOrDefault() / 100d;
_previousClose = _snapshot.Stock.Price.HasValue &&
                 _snapshot.Stock.ChangePercent.HasValue &&
                 Math.Abs(denominator) > 0.000001
    ? (double?)(_snapshot.Stock.Price.Value / denominator)
    : null;
```

当昨收有效时，两个价格序列统一转换：

```csharp
var percent = (price / _previousClose.Value - 1d) * 100d;
```

黄线数据选择规则：优先 `MarketAveragePrices`；只有它为空时才使用 `_snapshot.Prices` 的 THS 涨幅。白线只使用 `BigOrderAveragePrices`。过滤所有非有限值，不把无效点传给 GDI。

- [x] **Step 4: 用两条最终线数据重建同一纵轴**

`RebuildAxisTicks` 的范围来源改为 `MarketLinePercents + BigOrderLinePercents`，继续满足现有合同：包含 `0%`；有效跨度不足 `2%` 时至少展开到 `2%`；上下增加 5% 余量。左轴价格由同一个 `_previousClose` 与 tick percent 反算，右轴显示对应涨跌幅。

当昨收不可用时，市场/大单价格不能可靠转成涨幅：主图只允许使用已有 THS 涨幅兜底绘制黄线，右轴按该涨幅读取；左轴显示 `-`。若 THS 涨幅也为空，则两条线不绘制，避免把价格值错误当成百分比。

- [x] **Step 5: 替换绘制调用并删除本轮产生的孤儿方法**

`DrawLines` 固定为：

```csharp
DrawPercentLine(graphics, _marketLinePercents.ToArray(),
    _layoutBands[0], Color.FromArgb(225, 241, 64), 2);
DrawPercentLine(graphics, _bigOrderLinePercents.ToArray(),
    _layoutBands[0], Color.FromArgb(229, 235, 246), 1);
```

删除不再被任何生产代码调用的 `DrawScaledLine`。不删除 `BigOrderSeries.NetFlow`，因为它不是本轮新增且仍可能被既有分析逻辑消费。

- [x] **Step 6: 运行测试和 Release 构建确认 GREEN**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有测试输出 `PASS`，退出码 0。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors；记录实际 warning 数量。

- [x] **Step 7: 提交共轴绘制改动**

```powershell
git add -- tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "fix(tools): align intraday average price lines"
```

### Task 17: 为底部两层金额增加独立热力

**Files:**
- Modify: `tools/THSBigOrder/Controls/BigOrderChartControl.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [x] **Step 1: 写双层独立归一化失败测试**

给控件增加只读合同 `TotalHeatRatios`（`double?`，缺失保持 `null`）和 `BigOrderHeatRatios`（`double`）。测试使用两个数量级完全不同的序列：

```csharp
var halfHours = new[]
{
    new HalfHourAmount { TotalAmount = 100000000, BigOrderAmount = 1000000 },
    new HalfHourAmount { TotalAmount = 50000000, BigOrderAmount = 4000000 },
    new HalfHourAmount { TotalAmount = 0, BigOrderAmount = 0 },
    new HalfHourAmount { TotalAmount = null, BigOrderAmount = 2000000 },
};
control.SetSnapshot(snapshot, new BigOrderSeries
{
    Minutes = new MinuteFlow[0],
    NetFlow = new NetFlowPoint[0],
    Thresholds = new ThresholdFlow[0],
    HalfHours = halfHours,
    MarketAveragePrices = new AveragePricePoint[0],
    BigOrderAveragePrices = new AveragePricePoint[0],
});
AssertNear(1d, control.TotalHeatRatios[0].Value, 0.0001d, "total row max");
AssertNear(0.5d, control.TotalHeatRatios[1].Value, 0.0001d, "total row half");
AssertNear(0d, control.TotalHeatRatios[2].Value, 0.0001d, "zero has no heat");
AssertTrue(!control.TotalHeatRatios[3].HasValue, "missing has no ratio");
AssertNear(0.25d, control.BigOrderHeatRatios[0], 0.0001d, "big row independent scale");
AssertNear(1d, control.BigOrderHeatRatios[1], 0.0001d, "big row max");
AssertNear(0.5d, control.BigOrderHeatRatios[3], 0.0001d, "big row half");
```

补充全零一行，断言所有比例为 `0` 且不发生除零；不足八格时缺位补为 `null/0`，不得越界。

- [x] **Step 2: 运行测试确认 RED**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: FAIL，控件尚未生成热力比例。

- [x] **Step 3: 实现两行独立比例计算**

在 `SetSnapshot` 中调用 `RebuildHeatRatios()`。总成交额最大值只取 `TotalAmount.HasValue && TotalAmount.Value > 0`；大单最大值只取 `BigOrderAmount > 0`。分别按本行最大值计算并限制到 `[0, 1]`：

```csharp
ratio = max > 0 ? Math.Max(0, Math.Min(1, value / max)) : 0;
```

总成交额 `null` 保持 `null`，用于区分“数据缺失 `-`”与“有效零值 `0`”。两行不共享最大值，不读取右侧金额筛选阈值。

- [x] **Step 4: 绘制暗底、从左到右填充和亮度层级**

`DrawHalfHourAmounts` 每格先绘制原有暗底，再按本格比例绘制 `cellWidth * ratio` 的前景矩形。第一层颜色以深红到亮红插值，第二层以灰白到粉红插值；`ratio == 0` 或 `null` 不绘制前景。金额文本最后绘制并继续居中，保证不被色块覆盖：

```csharp
var heatWidth = Math.Max(0, (cellWidth - 2) * (float)ratio);
if (heatWidth > 0)
    graphics.FillRectangle(heatBrush, x + 1, row.Top + 1, heatWidth, row.Height - 2);
```

颜色插值保持现有高密度暗色终端风格，不增加渐变依赖、动画、图例或配置项。

- [x] **Step 5: 运行测试和 Release 构建确认 GREEN**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有测试输出 `PASS`，退出码 0。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors。

- [x] **Step 6: 提交热力改动**

```powershell
git add -- tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat(tools): add half-hour turnover heat bands"
```

### Task 18: 集成、真实数据和 WinForms 视觉验收

**Files:**
- Modify only if verification reveals a scoped defect in Tasks 15-17 files.
- Update: `docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md`

- [x] **Step 1: 运行完整 C# 自动化验证**

Run: `dotnet run --project tools/THSBigOrder.Tests/THSBigOrder.Tests.csproj -c Release`

Expected: 所有测试输出 `PASS`，退出码 0；新增测试明确覆盖两条均价公式、无效值、共轴范围、THS 兜底、独立热力和缺失/零值区别。

Run: `dotnet build tools/THSBigOrder/THSBigOrder.csproj -c Release`

Expected: Build succeeded，0 errors；记录 warning 数量。本轮不改 proxy-server，因此无需把 Node 全量测试作为代码正确性的阻塞门禁。

- [x] **Step 2: 确认数据入口没有漂移**

Run: `rg -n "python-bridge|ws/quotes|eastmoney|DrawScaledLine" tools/THSBigOrder tools/THSBigOrder.Tests`

Expected: 不新增 python-bridge、东方财富或 WebSocket 行情依赖；`DrawScaledLine` 无匹配。基础行情仍由 `/api/quotes/tencent`，分钟仍由 `/api/quotes/tencent/minute`，同花顺只承担大单明细与涨停上下文。

- [x] **Step 3: 用独立代理端口做真实值抽样对账**

若 3011 端口已有本任务启动的旧代理，先只定位并终止该端口对应进程，不影响用户的 3000 端口。以当前 worktree 的 `proxy-server` 在 `PORT=3011` 启动，抽取一只当日有大单的股票并核对：

```text
腾讯黄线末值 = 最后一分钟累计成交额 / (最后一分钟累计成交量 × 100)
同花顺白线末值 = Σ(有效大单价格 × 有效大单手数) / Σ(有效大单手数)
```

Expected: 程序聚合结果与独立手算误差不超过 `0.001` 元；两值都处于当日有效成交价区间，不再出现把资金净额缩放成价格线的现象。

- [x] **Step 4: 启动真实 WinForms 做桌面视觉验收**

运行 Release 程序，在 1280×800 和最小 960×640 下分别检查并截图：

- 黄线是腾讯全成交累计均价，白线是同花顺大单累计成交均价；二者使用同一左价格轴和右涨幅轴，纵向高低可直接比较。
- 黄白线没有因各自最小/最大值被单独拉满主图，白线不再表示累计净流入。
- 底部第一层与第二层各自都有从左到右的热力填充，且各自最强区间达到本行最亮/最满；大额总成交行不会压暗大单行。
- 金额文本保持居中可读；`0` 只有暗底，缺失显示 `-` 且无热力。
- 既有左右轴、四小时网格、八个 30 分钟格、信号点、分钟柱和右侧筛选没有退化。

这是 WinForms 桌面控件，不适用网页 Playwright；必须以真实进程、窗口尺寸和截图作为视觉证据。

- [x] **Step 5: 审计 diff、更新结果并做最终验证**

Run: `git status --short`

Expected: 只包含 `BigOrderSeriesBuilder.cs`、`BigOrderChartControl.cs`、`THSBigOrder.Tests/Program.cs` 和本实施文档；不包含主工作区已有 TdxL2Helper、构建产物或临时截图。

Run: `git diff --check`

Expected: 无空白错误。

把自动化测试数量、构建 warning/error、真实股票代码、两条末值对账和两档窗口视觉结果写入本节下方“增量执行结果”，再按 `verification-before-completion` 重新运行最终测试与构建；不得用本计划编写前的旧结果代替。

- [x] **Step 6: 仅提交本轮明确文件**

```powershell
git add -- tools/THSBigOrder/Analytics/BigOrderSeriesBuilder.cs tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs docs/kpl-viewer/2026-06-19-ths-big-order-implementation.md
git commit -m "feat(tools): refine THSBigOrder intraday chart"
```

### 2026-06-20 增量执行结果

- THSBigOrder 测试：23/23 PASS，退出码 0。新增覆盖腾讯累计成交均价、同花顺大单手数加权均价、无效数值过滤、共轴映射、THS 涨幅兜底、双层独立归一化以及最大热力文字对比度。
- Release 构建：0 warnings，0 errors。
- 数据入口审计：基础行情仍为 `/api/quotes/tencent`，完整分时仍为 `/api/quotes/tencent/minute`，大单明细仍为 `/api/big-order/ths-detail`；未引入 `python-bridge`、东方财富或 WebSocket 行情依赖，`DrawScaledLine` 已无生产匹配。
- 实时对账股票 `002297`（交易日 `20260618`）：腾讯 242 个分钟点，黄线末值 `27.937808`；同花顺 1263 笔有效大单，白线末值 `28.119292`，有效大单价格区间 `25.69-28.36`。两值均由独立脚本按设计公式复算。
- 真实 WinForms：已检查 1280×800 与最小 960×640。黄白线共用左右轴且纵向关系与真实价格一致；两层八段热力各自独立达到满格，`0`/缺失语义保留；右侧明细、四小时网格、分钟柱和信号点未见退化。
- 视觉验收发现第二层亮粉底色与粉色金额文字对比不足；已追加失败合同并将最大热力颜色压深、文字改为近白，最终对比度测试不少于 4.5:1，复拍通过。
- 验收环境说明：用户当前 3000 端口运行的是旧代理实例，缺少腾讯分钟路由；本轮使用当前 worktree 在 3011 临时启动代理完成验收，并已停止准确 PID。实际使用新版本时需重启 3000 端口代理。
- 验收启动器、构建产物和截图只存在忽略的 `.tmp/`，不纳入提交。

---

## 完成判定

- 新 THS 路由、涨停缓存和旧 KPL 路由兼容测试全部通过。
- THSBigOrder 测试入口全部通过，Release 构建成功。
- 002297 固定 fixture 合同、当日动态涨停股、普通非涨停股、非法代码及代理离线/恢复路径完成验收。
- 界面在三档 DPI 下无关键遮挡或未处理异常。
- 分时主图显示左价格轴、右涨幅轴和四个交易小时竖格；底部显示八个 30 分钟格及成交总额/大单总额两层数据。
- 分时主图黄线为腾讯全成交累计均价，白线为同花顺大单累计成交均价；两条线共用价格/涨幅轴，不再把累计大单净额独立缩放到价格主图。
- 底部成交总额和大单总额各自在八段内独立归一化绘制热力，`0` 与缺失状态可区分。
- 八段成交总额来自腾讯个股分钟累计成交额差分，八段大单总额来自同花顺大单逐笔金额求和；两者均不使用东财。
- 竞价、真实 L2 和私有指标没有被误实现或误描述。
- 最终提交不包含用户已有 TdxL2Helper 改动、`.superpowers/`、构建产物或过程文件。
