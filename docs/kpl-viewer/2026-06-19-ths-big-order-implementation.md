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

## 完成判定

- 新 THS 路由、涨停缓存和旧 KPL 路由兼容测试全部通过。
- THSBigOrder 测试入口全部通过，Release 构建成功。
- 002297 固定 fixture 合同、当日动态涨停股、普通非涨停股、非法代码及代理离线/恢复路径完成验收。
- 界面在三档 DPI 下无关键遮挡或未处理异常。
- 竞价、真实 L2 和私有指标没有被误实现或误描述。
- 最终提交不包含用户已有 TdxL2Helper 改动、`.superpowers/`、构建产物或过程文件。
