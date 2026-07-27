# THSBigOrder 会话日期选择实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 THSBigOrder 的日期控件严格驱动同一交易日的分钟线、大单均线、大单点和列表，并通过本地归档可靠查看历史交易日。

**Architecture:** `python-bridge` 使用 mootdx 上交所交易日历解析请求日期并返回指定会话日分钟数据。QuantBoard 只读服务按数据源、股票和会话日精确读取 gzip 归档；WinForms 将解析后的会话日作为单次请求的不可变输入，历史模式停止自动刷新和语音，Provider 与图表均拒绝跨日数据。

**Tech Stack:** Python/FastAPI/mootdx、Python gzip/JSON、C# .NET WinForms、Newtonsoft.Json、现有 C# 测试 runner。

---

## 文件边界

- 修改 `python-bridge/main.py`：日期解析及 `/api/quotes/minute?code=&date=`，不改变实时 L1/L2 能力边界。
- 修改 `python-bridge/test_quote_snapshot_api.py`：交易日历、指定历史分钟和日历失败。
- 新增 `quant-board/backend/big_order_archive_service.py`：归档路径校验、gzip 读取和 payload 验证。
- 新增 `quant-board/backend/api/big_order_history_routes.py`，修改 `quant-board/backend/main.py`：只读归档 API。
- 新增 `quant-board/backend/tests/test_big_order_archive_service.py`，修改 `quant-board/docs/api-cli.md`、`quant-board/docs/architecture.md`：API 合同和测试。
- 修改 `tools/THSBigOrder/DataSources/MarketSourceContracts.cs`、`TdxMinuteSourceClient.cs`，新增 `BigOrderHistorySourceClient.cs`：带会话日的加载请求和历史归档客户端。
- 修改 `tools/THSBigOrder/THSBigOrderDataProvider.cs`：实时/历史分流、按日期缓存和同日校验。
- 修改 `tools/THSBigOrder/MainForm.Designer.cs`、`MainForm.cs`、`Controls/BigOrderChartControl.cs`：日期控件、历史模式和最终图层防线。
- 修改 `tools/THSBigOrder.Tests/Program.cs`：客户端、Provider、表单与图表回归测试。
- 修改 `docs/ths-big-order/session-date-selection-design.md`：实现后只同步实际端点和验证结果。

### Task 1: 交易日历与指定日期分钟线

**Files:**
- Modify: `python-bridge/main.py: resolve_minute_session_date and /api/quotes/minute`
- Modify: `python-bridge/test_quote_snapshot_api.py`

- [ ] **Step 1: 写失败测试**

```python
def test_requested_non_trading_day_resolves_to_previous_sse_session(monkeypatch):
    monkeypatch.setattr(main, "_is_trading_day_cached", lambda value: value.date() == date(2026, 7, 24))
    assert main.resolve_requested_session_date("20260725") == "20260724"

def test_requested_session_fails_when_calendar_is_unavailable(monkeypatch):
    monkeypatch.setattr(main, "_is_trading_day_cached", lambda value: None)
    with pytest.raises(RuntimeError, match="TDX trading calendar unavailable"):
        main.resolve_requested_session_date("20260724")
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m unittest python-bridge/test_quote_snapshot_api.py`

Expected: 因 `resolve_requested_session_date` 尚不存在而失败。

- [ ] **Step 3: 最小实现**

新增 `resolve_requested_session_date(value: str) -> str`：向前最多 370 天调用既有 `_is_trading_day_cached`，返回最近上交所交易日；日历返回 `None` 时抛出 `TDX trading calendar unavailable`，不猜测周末或节假日。

分钟端点有 `date=yyyyMMdd` 时必须调用 `quote_client.minutes(symbol=..., date=session_date)`，无日期时保持当前交易时段的 `minute()` 行为。响应 `data.date` 返回实际会话日，日历失败映射为 `trading_calendar_unavailable`。

- [ ] **Step 4: 验证**

Run: `python -m unittest python-bridge/test_quote_snapshot_api.py`

Expected: 指定历史日期走 `minutes(..., date='YYYYMMDD')`；当天盘中仍走 `minute()`；全部通过。

- [ ] **Step 5: 提交**

```powershell
git add python-bridge/main.py python-bridge/test_quote_snapshot_api.py
git commit -m "feat: support dated mootdx minute data"
```

### Task 2: QuantBoard 历史归档 API

**Files:**
- Create: `quant-board/backend/big_order_archive_service.py`
- Create: `quant-board/backend/api/big_order_history_routes.py`
- Create: `quant-board/backend/tests/test_big_order_archive_service.py`
- Modify: `quant-board/backend/main.py`
- Modify: `quant-board/docs/api-cli.md`, `quant-board/docs/architecture.md`

- [ ] **Step 1: 写失败测试**

```python
def test_loads_exact_longhu_gzip_archive(tmp_path):
    write_gzip_json(tmp_path / "longhu/2026-07-24/002297.money0.json.gz", {
        "sessionDate": "2026-07-24", "stockCode": "002297", "data": {"List": []}
    })
    assert BigOrderArchiveService(tmp_path).load("longhu", "002297", date(2026, 7, 24))["sessionDate"] == "2026-07-24"

def test_missing_archive_raises_structured_not_found(tmp_path):
    with pytest.raises(BigOrderArchiveError, match="archive_not_found"):
        BigOrderArchiveService(tmp_path).load("ths", "002297", date(2026, 7, 24))
```

- [ ] **Step 2: 运行失败测试**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_big_order_archive_service.py -q`

Expected: 因归档服务不存在而失败。

- [ ] **Step 3: 最小实现**

根路径固定为 `quant-board/data/big-order`。只接受 `source in {'longhu', 'ths'}`、六位数字 `stockCode`、ISO `sessionDate`。Longhu 只读 `longhu/<yyyy-MM-dd>/<code>.money0.json.gz`，并校验顶层 `sessionDate`/ `stockCode`；THS 只读 `ths/<yyyy-MM-dd>/<code>.json.gz`，并校验 `title`、`list`、`pricechange`。不遍历邻近日期。

路由为：

```text
GET /api/big-order/history?source=longhu|ths&stockCode=002297&sessionDate=2026-07-24
```

归档缺失返回 `404 / archive_not_found`，gzip、JSON 或字段不合法返回 `422 / archive_invalid`；成功时返回 `{ "ok": true, "data": ... }`。

- [ ] **Step 4: 验证**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest backend/tests/test_big_order_archive_service.py -q`

Expected: Longhu、THS、错误代码、股票或日期不匹配均通过。

- [ ] **Step 5: 提交**

```powershell
git add quant-board/backend/big_order_archive_service.py quant-board/backend/api/big_order_history_routes.py quant-board/backend/main.py quant-board/backend/tests/test_big_order_archive_service.py quant-board/docs/api-cli.md quant-board/docs/architecture.md
git commit -m "feat: expose archived big-order history"
```

### Task 3: C# 会话日期加载与数据一致性

**Files:**
- Modify: `tools/THSBigOrder/DataSources/MarketSourceContracts.cs`
- Modify: `tools/THSBigOrder/DataSources/TdxMinuteSourceClient.cs`
- Create: `tools/THSBigOrder/DataSources/BigOrderHistorySourceClient.cs`
- Modify: `tools/THSBigOrder/THSBigOrderDataProvider.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写失败测试**

```csharp
var result = await minute.LoadDirectAsync("002297", new DateTime(2026, 7, 24), CancellationToken.None);
AssertTrue(handler.Records.Any(x =>
    x.Uri.PathAndQuery == "/api/quotes/minute?code=002297&date=20260724"),
    "dated minute request");
```

补充断言：两种源分别请求 `/api/big-order/history?source=...&stockCode=...&sessionDate=2026-07-24`；`archive_not_found` 为失败且不使用实时缓存；分钟、大单、订单和价格任一日期与目标会话不符时，订单、均线和事件点均为空。

- [ ] **Step 2: 运行失败测试**

Run: `dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release`

Expected: 带日期加载签名和历史 API 合同失败。

- [ ] **Step 3: 最小实现**

新增不可变 `MarketLoadRequest`，包含 `StockCode`、`RequestedDate` 和 `SessionDate`，不将日期放入 Provider 共享状态。分钟客户端带 `date=yyyyMMdd`，并验证解析结果日期与 `SessionDate` 相等。

历史客户端将 Longhu payload 交给 `ParseLonghuBigOrderSource`，THS payload 交给 `ParseBigOrderSource`。Provider 在 `SessionDate == DateTime.Today` 时使用现有实时源，否则只读归档 API；缓存键包含数据源、股票和会话日期。当前行情、换手、量比和涨停仍保持现有当前请求。把 `RejectStaleBigOrderSession` 改为比较请求会话日，并校验分钟、订单和价格日期。

- [ ] **Step 4: 验证**

Run: `dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release`

Expected: 当前、历史分钟、两种归档、缺归档和跨日拒绝用例通过。

Run: `dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore`

Expected: `0 Error(s)`。

- [ ] **Step 5: 提交**

```powershell
git add tools/THSBigOrder/DataSources/MarketSourceContracts.cs tools/THSBigOrder/DataSources/TdxMinuteSourceClient.cs tools/THSBigOrder/DataSources/BigOrderHistorySourceClient.cs tools/THSBigOrder/THSBigOrderDataProvider.cs tools/THSBigOrder.Tests/Program.cs
git commit -m "feat: load session-consistent big-order data"
```

### Task 4: WinForms 日期控件与历史查看模式

**Files:**
- Modify: `tools/THSBigOrder/MainForm.Designer.cs`
- Modify: `tools/THSBigOrder/MainForm.cs`
- Modify: `tools/THSBigOrder/Controls/BigOrderChartControl.cs`
- Modify: `tools/THSBigOrder.Tests/Program.cs`

- [ ] **Step 1: 写失败测试**

```csharp
form.SessionDate = new DateTime(2026, 7, 24);
await form.RefreshStockAsync("002297", true);
AssertTrue(!form.AutoRefreshEnabled && !form.VoiceEnabled, "history mode pauses refresh and voice");
AssertEqual(new DateTime(2026, 7, 24), form.VisibleChartSessionDate, "chart session date");
```

覆盖默认今天和最大今天、切换源/股票/日期取消旧请求、非交易日控件回写为 bridge 返回会话日、切回今天恢复用户原自动刷新/语音选择、图表只保留与分钟会话日相同的订单点和蓝线。

- [ ] **Step 2: 运行失败测试**

Run: `dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release`

Expected: 日期控件和历史模式合同失败。

- [ ] **Step 3: 最小实现**

在数据源下拉框右侧新增 `DateTimePicker`，设置 `Format = Custom`、`CustomFormat = "yyyy/MM/dd"`、`MaxDate = DateTime.Today`，默认今天。日期、源、代码变化共用 `RefreshCoordinator` 的新 generation，并在开始新请求时清空旧图层和列表。

历史模式保存原有复选框值，停止定时器并关闭语音；切回今天恢复保存的选择。历史请求失败必须呈现 `归档不存在`、`交易日历不可用` 或 `数据日期不匹配`，不能显示其他日期。图表继续以同日校验作最后防线，订单点不得回退绑定蓝线。

- [ ] **Step 4: 自动化及窗口验收**

Run: `dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release`

Expected: 全部通过。

Run: `dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore`

Expected: `0 Error(s)`。

Run: `Start-Process -FilePath tools\THSBigOrder\bin\Release\net8.0-windows\THSBigOrder.exe`

Expected: 控件位于数据源右侧；已有归档日期的白线、蓝线、红绿点、列表同日；无归档显示明确失败且不回退；切回今天恢复自动刷新和语音。

- [ ] **Step 5: 提交**

```powershell
git add tools/THSBigOrder/MainForm.Designer.cs tools/THSBigOrder/MainForm.cs tools/THSBigOrder/Controls/BigOrderChartControl.cs tools/THSBigOrder.Tests/Program.cs docs/ths-big-order/session-date-selection-design.md
git commit -m "feat: add THS big-order session date picker"
```

### Task 5: 最终复核

**Files:**
- Modify: `docs/ths-big-order/session-date-selection-design.md` only if implementation changed a documented API detail.

- [ ] **Step 1: 运行全量相关验证**

```powershell
python -m unittest python-bridge/test_quote_snapshot_api.py
Push-Location quant-board; .\.venv\Scripts\python.exe -m pytest; Pop-Location
dotnet run --project tools\THSBigOrder.Tests\THSBigOrder.Tests.csproj -c Release
dotnet build tools\THSBigOrder\THSBigOrder.csproj -c Release --no-restore
git diff --check
```

Expected: 每项退出码为 0，且 `git diff --check` 无空白错误。

- [ ] **Step 2: 人工复核**

确认历史 API 未回退日期、实时模式未伪称 L2、顶部行情仍为当前值、历史模式不触发自动刷新或语音；确认 `git status --short` 只包含计划所需文件。

- [ ] **Step 3: 最终文档提交**

```powershell
git add docs/ths-big-order/session-date-selection-implementation-plan.md docs/ths-big-order/session-date-selection-design.md
git commit -m "docs: record THSBigOrder session-date implementation"
```

## 计划自审

- 日期控件、上交所交易日历、当天/历史分流、两种历史数据源、严格失败、同日图表、历史模式均有对应任务。
- 不包含历史 K 线、历史顶部行情、回测或 L2 能力扩展。
- API、桌面请求和测试字段统一为 `source`、`stockCode`、`sessionDate`、`MarketLoadRequest`。
- 每个阶段均按失败测试、最小实现、命令验证和独立提交收束。
