# 通达信逐笔资金 WebSocket Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以单笔成交额大于或等于 30 万元的通达信逐笔成交为唯一行情/题材主力资金源，通过 QuantBoard Redis 与 WebSocket 向两个消费者提供同一版本的数据。

**Architecture:** `python-bridge` 计算 `tdx_transaction` 日内累计值并将独立资金订阅池的增量推给 QuantBoard。QuantBoard 持久化最近交易日资金、冻结收盘值、聚合题材并向浏览器推送快照/增量；浏览器保留现有桥接行情连接，但资金字段只接受 QuantBoard 资金流。

**Tech Stack:** Python 3.12、FastAPI WebSocket、mootdx、Redis、Vue 3、TypeScript、Vitest、pytest

---

### Task 0: 统一交易日历真相源

- [x] `python-bridge /api/calendar` 只返回 `mootdx.utils.holiday` 的通达信标准日历结果。
- [x] QuantBoard snapshot collector 通过 bridge 日历判断交易日，删除近似节假日表和 `weekday()` 判断。
- [x] 前端删除周末/硬编码节假日 fallback；bridge 日历未知时按暂停处理，不猜测交易日。
- [x] 日历不可用时停止资金回填、盘后冻结和快照调度，保留 Redis last-good。

## 文件结构

- Modify: `python-bridge/big_order_calculator.py` — 30 万门槛、交易日累计和确定性去重。
- Modify: `python-bridge/main.py` — 独立资金订阅池与资金帧协议，不改变普通行情订阅池。
- Modify: `python-bridge/test_quote_snapshot_api.py` — 桥接资金订阅和非交易时段合同。
- Create: `quant-board/backend/theme_fund_cache.py` — 每代码 Redis last-good、按交易日冻结值和版本。
- Create: `quant-board/backend/theme_fund_stream.py` — 生命周期内订阅桥接、聚合客户端订阅、重连和广播。
- Modify: `quant-board/backend/theme_heat_service.py` — 删除 THS 拉取队列，仅读统一资金缓存。
- Modify: `quant-board/backend/api/theme_heat_routes.py` — 资金快照 REST 兼容与资金 WebSocket。
- Modify: `quant-board/backend/main.py`、`quant-board/backend/settings.py` — 启停资金流和桥接 URL 配置。
- Remove during implementation: `quant-board/backend/theme_fund_scheduler.py` — 删除由本次改造淘汰的 THS HTTP 刷新任务。
- Modify: `quant-board/backend/snapshot_collector/providers.py`、`quant-board/backend/snapshot_collector/service.py` — 快照资金改读同一缓存，不再请求 THS。
- Create: `quant-board/tests/test_theme_fund_cache.py`、`quant-board/tests/test_theme_fund_stream.py` — 缓存与流测试。
- Modify: `quant-board/tests/test_theme_heat_service.py`、`quant-board/tests/test_snapshot_collector_*.py` — 唯一数据源合同。
- Create: `src/services/themeFundStream.ts` — 浏览器侧 QuantBoard 资金 WebSocket 客户端。
- Modify: `src/services/websocket.ts` — 普通桥接连接不再向业务层发布资金字段。
- Modify: `src/services/dataLoader/QuoteHttpFeed.ts`、`src/services/dataLoader/QuoteService.ts` — 删除资金 HTTP 轮询并合并统一流。
- Modify: `src/services/apiService.ts` — REST 仅保留显式恢复调用，不参与刷新。
- Modify: relevant `__tests__/*.test.ts` — 无轮询、同版本、重连快照测试。
- Modify: `quant-board/docs/api-cli.md`、`docs/theme-module/progress.md` — 同步数据源和非交易日合同。

### Task 1: 固定 30 万逐笔口径

**Files:**
- Modify: `python-bridge/big_order_calculator.py`
- Test: `python-bridge/test_big_order_calculator.py`

- [ ] **Step 1: 写失败测试，覆盖阈值边界和方向**

```python
def test_main_money_uses_trades_at_or_above_300k():
    calculator = BigOrderCalculator(BigOrderConfig(threshold_wan=30))
    frame = calculator.process_ticks("000001", [
        {"time": "09:30:01", "price": 10, "vol": 299, "buyorsell": 0},
        {"time": "09:30:02", "price": 10, "vol": 300, "buyorsell": 0},
        {"time": "09:30:03", "price": 10, "vol": 400, "buyorsell": 2},
    ]).to_money_flow_frame(calculator.config)
    assert frame.zlje == -10
    assert frame.moneyFlowSource == "tdx_transaction"
```

- [ ] **Step 2: 运行测试并确认旧默认/分类逻辑失败**

Run: `python -m unittest python-bridge/test_big_order_calculator.py -v`

- [ ] **Step 3: 将主力净额定义为所有 `>= threshold_wan` 主动成交的净额**

保留现有字段合同，但不要再用 `threshold / 5` 的“大单”共同组成主力。默认配置改为：

```python
big_order_threshold_wan: float = float(os.getenv("TDX_BIG_ORDER_THRESHOLD_WAN", "30"))
```

中性方向只计 `activeAmount`，不进入 `zlje`。去重键必须包含交易日，避免跨日同一时间/价格/手数碰撞。

- [ ] **Step 4: 运行桥接计算测试**

Run: `python -m unittest python-bridge/test_big_order_calculator.py -v`
Expected: all tests pass.

### Task 2: 分离行情订阅池与资金轮转池

**Files:**
- Modify: `python-bridge/main.py`
- Test: `python-bridge/test_quote_snapshot_api.py`

- [ ] **Step 1: 写失败测试，证明资金订阅不会扩大普通行情池**

```python
async def test_money_flow_pool_is_independent_from_quote_pool():
    bridge = TdxL2Bridge(BridgeConfig())
    bridge.set_money_flow_pool(["000001", "600000"])
    assert bridge.aggregate_money_flow_pool() == ["000001", "600000"]
    assert bridge.aggregate_pool() == []
```

- [ ] **Step 2: 为桥接协议加入 `set_money_flow_pool`**

QuantBoard 连接发送：

```json
{"type":"set_money_flow_pool","codes":["000001","600000"]}
```

桥接使用独立游标按 `TDX_BIG_ORDER_CODES_PER_CYCLE` 轮转，不把 4,000 只映射股票加入报价/深度抓取。资金帧包含：

```json
{
  "code":"000001",
  "zlje":12.5,
  "zljzb":3.2,
  "moneyFlowSource":"tdx_transaction",
  "moneyFlowEstimated":false,
  "tradingDate":"2026-07-24",
  "sourceTs":1784883600000
}
```

- [ ] **Step 3: 修复桥接全量状态遗漏累计资金的问题**

`full_state.moneyFlow` 必须来自 `big_order.get_frames(requested_codes)`，而非仅来自本轮新增 `big_order_frames`。盘后轮询可以降低频率，但不得清空已累计值。

- [ ] **Step 4: 运行桥接协议测试**

Run: `python -m unittest python-bridge/test_quote_snapshot_api.py -v`
Expected: WebSocket route、独立订阅池、full state last-good tests pass.

### Task 3: 建立 QuantBoard 资金 Redis 真相源

**Files:**
- Create: `quant-board/backend/theme_fund_cache.py`
- Create: `quant-board/tests/test_theme_fund_cache.py`

- [ ] **Step 1: 写失败测试，覆盖周末、冻结值和 Redis 冷缺失**

```python
def test_weekend_reads_latest_final_trading_day(fake_redis):
    cache = ThemeFundCache(fake_redis, prefix="test")
    cache.put(row("000001", "2026-07-24", zlje=12.5), is_final=True)
    assert cache.get_latest(["000001"], as_of=date(2026, 7, 25))["000001"]["zlje"] == 12.5

def test_cold_weekend_cache_does_not_treat_recent_ticks_as_full_day(fake_redis):
    cache = ThemeFundCache(fake_redis, prefix="test")
    assert cache.get_latest(["000001"], as_of=date(2026, 7, 25)) == {}
```

- [ ] **Step 2: 实现专用 Redis Hash 与最近交易日索引**

使用专用键，不复用 snapshot response cache：

```text
{prefix}:theme-fund:v2:latest                  # code -> row JSON
{prefix}:theme-fund:v2:date:2026-07-24        # code -> final row JSON
{prefix}:theme-fund:v2:latest-final-date       # scalar YYYY-MM-DD
{prefix}:theme-fund:v2:version                 # INCR version
```

`v2` 对应“金额单位为元、0 买/1 卖、单笔成交额不低于 30 万元”的资金合同；`v1` 不再读取，避免旧单位和旧买卖方向污染盘后冻结值。

资金值不设置短 TTL；历史交易日键按明确保留期清理。Redis 不可用时进程内 last-good 继续服务，写失败不删除旧值。

- [ ] **Step 3: 实现冻结规则**

只允许将来源为 `tdx_transaction`、日期为最近交易日且源时间不倒退的记录写为最终值。周末/节假日读取 `latest-final-date`，不以自然日构造空键。

- [ ] **Step 4: 运行缓存测试**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests\test_theme_fund_cache.py -q`
Expected: all tests pass.

### Task 4: QuantBoard 订阅桥接并向浏览器广播

**Files:**
- Create: `quant-board/backend/theme_fund_stream.py`
- Create: `quant-board/tests/test_theme_fund_stream.py`
- Modify: `quant-board/backend/api/theme_heat_routes.py`
- Modify: `quant-board/backend/main.py`
- Modify: `quant-board/backend/settings.py`
- Modify: `quant-board/requirements.txt`

- [ ] **Step 1: 写失败测试，覆盖快照、增量、重连和订阅合并**

```python
def test_stream_persists_before_broadcasting(fake_cache, fake_bridge):
    stream = ThemeFundStream(cache=fake_cache, bridge=fake_bridge)
    stream.accept_bridge_message({"type": "money_flow_patch", "items": [tdx_row("000001")]})
    assert fake_cache.latest["000001"]["moneyFlowSource"] == "tdx_transaction"
    assert stream.pending_patch()[0]["code"] == "000001"
```

- [ ] **Step 2: 实现生命周期订阅器**

新增设置：

```python
theme_fund_bridge_ws_url: str = "ws://127.0.0.1:8765/ws/quotes"
theme_fund_stream_enabled: bool = True
theme_fund_reconnect_max_seconds: float = 30.0
```

订阅器启动后连接桥接，发送当前资金池，接收 `full_state.moneyFlow` 与 `money_flow_patch.items`，校验来源、日期和时间顺序后先写缓存再广播。连接失败指数退避，已有缓存始终可读。

- [ ] **Step 3: 新增浏览器资金 WebSocket**

端点：`/api/themes/fund-stream`。客户端首条消息发送 codes 和可选 version；服务端先返回 `fund_full_state`，之后返回 `fund_patch`。客户端订阅集合变化时更新代码，服务端合并所有客户端集合并转发给桥接。

- [ ] **Step 4: 保留只读 REST 恢复端点**

`GET /api/themes/fund-rows?codes=...` 只读缓存，不排队、不请求任何上游；返回行带 `tradingDate`、`version`、`isFinal` 和 `moneyFlowSource=tdx_transaction`。

- [ ] **Step 5: 运行资金流测试**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests\test_theme_fund_cache.py tests\test_theme_fund_stream.py -q`
Expected: all tests pass.

### Task 5: 题材与快照统一读取缓存并删除 THS 刷新器

**Files:**
- Modify: `quant-board/backend/theme_heat_service.py`
- Remove: `quant-board/backend/theme_fund_scheduler.py`
- Modify: `quant-board/backend/snapshot_collector/providers.py`
- Modify: `quant-board/backend/snapshot_collector/service.py`
- Modify: `quant-board/backend/main.py`
- Test: `quant-board/tests/test_theme_heat_service.py`
- Test: `quant-board/tests/test_snapshot_collector_providers.py`
- Test: `quant-board/tests/test_snapshot_collector_service.py`

- [ ] **Step 1: 将现有测试改成唯一缓存来源合同并确认失败**

```python
def test_theme_and_market_rows_share_same_tdx_version(service):
    row = service.get_fund_rows(["000001"])["000001"]
    snapshot = service.get_snapshot()
    assert snapshot["fundRowsByCode"]["000001"]["version"] == row["version"]
    assert row["moneyFlowSource"] == "tdx_transaction"
```

- [ ] **Step 2: 删除 THS provider、pending queue 和 scheduler 调用**

`ThemeHeatService` 注入 `ThemeFundCache`，`get_fund_rows` 只调用缓存。题材聚合使用同一行的 `zlje` 映射到 `mainNetInflow`，缺失保持 `None`。快照采集器也只读该缓存，不恢复 Eastmoney 或 THS fallback。

- [ ] **Step 3: 删除过期来源标记**

源码运行路径不得再产生 `theme_fund_ths`、`ths_cache`、`ths_l2` 或 `/api/quotes/eastmoney` 资金来源。`tools/THSBigOrder/**` 不在搜索清理范围内，也不修改其 THS 单票客户端。

- [ ] **Step 4: 运行 QuantBoard 相关回归**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests\test_theme_heat_service.py tests\test_theme_heat_providers.py tests\test_snapshot_collector_providers.py tests\test_snapshot_collector_service.py -q`
Expected: all tests pass; THS fund provider tests are removed or replaced by cache-provider tests.

### Task 6: 前端资金改为 QuantBoard 增量流

**Files:**
- Create: `src/services/themeFundStream.ts`
- Create: `src/services/__tests__/themeFundStream.test.ts`
- Modify: `src/services/websocket.ts`
- Modify: `src/services/__tests__/websocketMoneyFlow.test.ts`
- Modify: `src/services/dataLoader/QuoteHttpFeed.ts`
- Modify: `src/services/dataLoader/QuoteService.ts`
- Modify: `src/services/dataLoader/__tests__/QuoteHttpFeed.test.ts`
- Modify: `src/services/dataLoader/__tests__/QuoteService.test.ts`
- Modify: `src/services/apiService.ts`

- [ ] **Step 1: 写失败测试，证明正常刷新不请求资金 REST**

```typescript
it('does not poll fund rows during full quote refresh', async () => {
  await feed.fetchFullData(['000001'], true)
  expect(getQuotes).not.toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ source: 'themeFundCache' }),
  )
})
```

- [ ] **Step 2: 实现独立资金 WebSocket 客户端**

连接 `ws://127.0.0.1:8000/api/themes/fund-stream`，发送行情可见代码集合，处理 `fund_full_state` 和 `fund_patch`。只接受 `moneyFlowSource === 'tdx_transaction'` 且版本不倒退的行，将 `zlje/zljzb/cddje/cddjzb` 合并到现有股票状态。

- [ ] **Step 3: 阻止直接桥接资金覆盖统一缓存**

`src/services/websocket.ts` 继续处理行情、深度和逐笔，但不再从桥接 `full_state.moneyFlow` / `money_flow_patch` 向业务层发资金字段。行情 WebSocket 健康状态不与资金流连接状态混为同一个 fallback 标记。

- [ ] **Step 4: 删除周期资金 HTTP 调用**

`QuoteHttpFeed.fetchFullData()` 只加载 HTTP 行情补充字段，不再请求 `themeFundCache` 或 `thsMoneyFlow`。REST `/fund-rows` 只由资金 WebSocket 断线恢复逻辑显式调用一次，不能被刷新调度器调用。

- [ ] **Step 5: 运行前端单元测试和类型检查**

Run: `pnpm exec vitest run src/services/__tests__/themeFundStream.test.ts src/services/__tests__/websocketMoneyFlow.test.ts src/services/dataLoader/__tests__/QuoteHttpFeed.test.ts src/services/dataLoader/__tests__/QuoteService.test.ts src/components/panels/__tests__/ThemePanelsDataContract.test.ts`

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

Expected: all tests pass; typecheck exits 0.

### Task 7: 文档、运行验收和浏览器验收

**Files:**
- Modify: `quant-board/docs/api-cli.md`
- Modify: `docs/theme-module/progress.md`
- Modify: `docs/theme-module/plans/2026-07-25-ths-incremental-fund-cache-plan.md`

- [ ] **Step 1: 将旧 THS 增量计划标记为已被本计划替代**

旧计划不能继续描述当前运行架构。API 文档写明资金流协议、Redis last-good、周末最近交易日和冷缺失行为。

- [ ] **Step 2: 运行完整目标回归**

Run: `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests\test_theme_fund_cache.py tests\test_theme_fund_stream.py tests\test_theme_heat_service.py tests\test_snapshot_collector_providers.py tests\test_snapshot_collector_service.py -q`

Run: `pnpm exec vitest run src/services/__tests__/themeFundStream.test.ts src/services/__tests__/websocketMoneyFlow.test.ts src/services/dataLoader/__tests__/QuoteHttpFeed.test.ts src/services/dataLoader/__tests__/QuoteService.test.ts src/components/panels/__tests__/ThemePanelsDataContract.test.ts`

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

Run: `git diff --check`

- [ ] **Step 3: 重启并验证真实链路**

重启 `8765` bridge、`8000` QuantBoard、`3000` proxy 和根 Vite。确认浏览器 Network 中资金没有周期 REST 请求，`fund-stream` 持续收到增量；在周末/非交易时段确认资金行来自最近交易日冻结值。

- [ ] **Step 4: 按项目要求执行 Playwright 验收**

检查行情列表“主力净额”和题材面板“主力资金”对同一股票值一致、缺失为 `--`、无“资金数据降级”、控制台无错误。保存必要的桌面截图到测试产物目录，不提交截图。

## 计划自审

- 设计范围全部有对应任务：30 万口径、唯一数据源、Redis、周末冻结、冷缺失、WebSocket、THS 移除、`THSBigOrder` 排除。
- 未引入独立守护进程；订阅器随 FastAPI 生命周期启动和停止。
- 没有以题材映射行数作为行情覆盖率门禁；资金池与行情池分离。
- 实施期间不自动提交或推送；工作区已有同一任务修改必须原位演进，不回滚用户内容。
