# THS 主力资金数据源优化方案分析（akshare 口径不可信 → L2 主源 + 种子占位）

## 状态

方案分析文档，已进入实施。

- **2026-08-08 第一步（source 契约拆分）已实施**：akshare 全市场行改
  `ths_web_seed` + `moneyFlowEstimated=true`（`akshare_fund_provider.py`）；
  `ThemeFundCache` 放开接受 `ths_main_monitor`/`ths_web_seed` 并按 source rank
  覆盖（L2 覆盖种子、种子不覆盖 L2、跨日新日期覆盖）；前端
  `moneyFlowSourcePriority` 增加 `ths_web_seed` rank 1、`marketFundStream`
  过滤收敛到 `isDashboardFundSource` 单一入口；题材资金健康标注按实际行来源
  暴露（不再把种子伪装成 `ths_main_monitor`）；快照采集器维持只接受
  `ths_main_monitor` 权威行。验证：pytest 45 项 + 前端资金链 106 项全绿。
- **待办（第二步）**：~~mainMonitorDetail 进程内调度器 + 种子预热衔接。~~（2026-08-08 已实施，见下）
- **2026-08-08 第二步（mainMonitorDetail 进程内调度器）已实施**：新增
  `backend/services/market/ths_fund_refresh_scheduler.py`，进程内直调
  `ThsMainMonitorService` 按展示池（fund-stream 在线订阅 codes）分批校准：
  每批 ≤5、并发 ≤2、180 秒轮转、单票退避 30→60→120→300 秒、系统性限流
  全局冷却 30 秒 + 并发降 1、连续 3 批成功恢复并发 2；写入
  `ThemeFundCache`（`ths_main_monitor`）覆盖 akshare 种子；已挂接
  `backend/main.py` lifespan（start/stop）并暴露 `/api/health` 的
  `thsFundRefresh` 状态。验证：调度器测试 8 项 + 全量 pytest 通过。
  简化点（后续增强）：P0/P1 可见行优先级、owner 持久化（浏览器断开后继续
  刷新）、交易日时段策略暂未实现，当前以在线订阅池为展示池。
- **2026-08-08 实时层（bridge L1 分笔自算）启用后降级为"不展示、仅诊断"**：
  曾接入前端（`fund_flow_patch` → `tdx_transaction` rank 3），实盘验证 +
  L1 完整性分析发现：`fetch_ticks` 只拉最近 `TDX_TICK_WINDOW`（默认 60）笔，
  **非全日完整分笔**，中途启动/断连/窗口溢出都会导致累计不完整甚至方向错误。
  已回滚前端接入（`tdx_transaction` 保持 rank 0，不进入资金列）；bridge
  `/health` 新增 `tick`/`fundFlow` 诊断字段（`fetchSupported/lastError/
  accumulatedCodes/lastBroadcastTs`）。资金列最终口径：**L2 主源
  （`mainMonitorDetail`，实盘验证与东财近似）+ akshare 种子兜底**。
- **待确认**：~~实时层（`tdx_transaction` 本地分笔自算）是否启用。~~
  （2026-08-08 启用后因 L1 分笔不完整而降级，不展示）

背景：akshare 同花顺主力资金数据口径与
`mainMonitorDetail` 差异过大（同股同日数值甚至符号相反），东财限流，
`mainMonitorDetail` 单票限流 30 req/min 导致全市场刷不动；此前
mainMonitorDetail 方案存在首屏大面积空白、需等待数分钟才满屏的问题。
本文核实现状链路后给出"L2 主源 + akshare 全市场种子占位 + 渐进校准"方案。

## 1. 问题与根因

### 1.1 现象

1. **akshare 主力资金"不可信"**：`ak.stock_fund_flow_individual(symbol="即时")`
   取同花顺网页"个股资金流"页面的"净额"（主力流入 − 流出），与
   `mainMonitorDetail` 的 `mainbuy − mainsell`（L2 逐笔主力监控）**口径不等价**。
   实测 300720 同日分别为 +1.245 亿 与 −0.831 亿（见
   `quant-board/docs/api-cli.md` 与 `akshare_fund_provider.py:198-201` 注释）。
   该接口单次内部逐页请求约 104 页，触发风控（验证码/限流），数据质量不可控。
2. **mainMonitorDetail 首屏空白**：限流 30 req/min、每批最多 5 只、并发 2，
   冷启动补齐 200 只约需 5–7 分钟，期间页面资金列空白。
3. **东财限流**：逐票请求受限，不能作为全市场实时源。

### 1.2 现状链路核实（代码事实）

当前生产链路（前端资金列唯一来源）：

```text
akshare stock_fund_flow_individual("即时") 全市场  ← fund_scheduler.py
→ ThemeFundCache (theme-fund:v3)                   ← fund_cache.py put_many
→ MarketFundStream WebSocket (/api/market/fund-stream)
→ src/services/marketFundStream.ts → DataLayer zlje
```

关键事实：

- `ThsMainMonitorService`（mainMonitorDetail，`ths_main_monitor_service.py`）
  **只被 FastAPI 路由调用**（`ths_main_monitor_routes.py` 的 `/ths-detail`、
  `/ths-fund-batch`），**没有调度器把它写进 `ThemeFundCache`**——L2 可信数据
  从未回流到页面资金列，只服务 `tools/THSBigOrder` 工具。
- `ThemeFundCache._parse_fund_row`（`fund_cache.py:67-73`）强制
  `source == "ths_main_monitor"` 才能写入；而 akshare 网页口径的行也标
  `source/moneyFlowSource = "ths_main_monitor"`（`akshare_fund_provider.py:222-223`）
  写入**同一个 hash**。两个不同口径共用同一 source 互相覆盖，无法区分、无法比对，
  这是"数据不可信"的另一个结构性根因。
- 前端双重过滤：`marketFundStream.ts:84` 对 `moneyFlowSource !== 'ths_main_monitor'`
  直接丢弃；`moneyFlowSourcePriority.ts` 只有 `ths_main_monitor` rank=5，其余为 0
  （`shouldApplyMoneyFlowUpdate` 一律拒绝，`websocketMoneyFlow.test.ts` 断言了
  bridge 的 `tdx_transaction` 数据被忽略）。
- mainMonitorDetail 单票服务已有：3 秒 raw 内存缓存（`load_raw`）、写 raw Redis
  （`_raw_key`，`ths-main-monitor:raw:v1:{code}`）、单票 gzip 归档、错误码分类
  （`ths_rate_limited`/`ths_captcha_required`/`ths_timeout`/`ths_upstream_unavailable`/
  `ths_invalid_payload`）、并发上限 2、冷却期（`enter_cooldown`）。
- 前端已有"估算"表达：`statusClassifier.ts:227` 识别
  `moneyFlowEstimated === true || moneyFlowSource === 'tdx_estimate'`；
  快照 builders 已带 `moneyFlowSource`/`moneyFlowEstimated` 字段。

## 2. 目标与非目标

### 目标

- 页面资金列数据源切换为 `mainMonitorDetail`（L2 口径，可信）。
- 首屏不空白：冷启动即有全市场种子值（akshare 网页口径，显式标记估算），
  盘中由 L2 逐票校准替换。
- 30 req/min 限流下 200 只展示池约 5–7 分钟全部校准；P0 可见行 30 秒内校准。
- 多源冲突/缺失显式暴露，不静默覆盖、不归零（fail-visible）。

### 非目标

- 不做全市场 L2 高频刷新（限流物理不允许）。
- 不把运行态资金写入正式快照/回测（`stock_rows`/`sector_rows`/回测口径
  仍只接受 `broker_l2`/`official_l2`，沿用 2026-07-25 设计约束）。
- 不引入付费数据源（Tushare Pro 等）作为本方案前置依赖。
- 不启用 7719 真 L2 逐笔（未完成，`AGENTS.md` 4.3 禁止描述为可用）。

## 3. 方案：数据源分层与 source 契约

### 3.1 三层来源

| 层 | 来源 | 范围 | 节奏 | source 值 | 可信度 |
| --- | --- | --- | --- | --- | --- |
| 种子 | akshare `stock_individual_fund_flow_rank("今日")`（东财排行） | 全市场 | 启动预热 + 15–20 分钟低频兜底 | `eastmoney_seed`（新，兼容存量 `ths_web_seed`） | 中（东财口径≈超大单+大单，与 L2 近似，估算） |
| 主源 | `mainMonitorDetail` | 展示池（owner 约 200–400 只） | P0 30s / P1 180s 轮转 | `ths_main_monitor` | 高（L2 口径） |
| 实时（降级） | python-bridge `tdx_fund_flow`（本地分笔自算，不展示仅诊断） | 订阅池 | 5 秒广播 | `tdx_transaction`（rank 0，不入资金列） | 低（L1 分笔不完整，不可信） |

### 3.2 source 契约（关键前提，不改必出问题）

- **拆分种子与 L2 的 source**：种子行写 `eastmoney_seed`（2026-08-08 由
  `ths_web_seed` 切换，东财口径 ≈ 超大单 + 大单净流入，与 L2 近似）+
  `moneyFlowEstimated: true`；存量 `ths_web_seed` 行保留 rank 1 兼容旧缓存；
  mainMonitorDetail 行写 `ths_main_monitor` + `moneyFlowEstimated: false`。
  种子与 L2 不得共用同一 source。
- 前端优先级（`moneyFlowSourcePriority.ts` 扩展）：
  `eastmoney_seed`/`ths_web_seed`（rank 1）<
  `ths_main_monitor`（rank 5）。低 rank 不覆盖高 rank；高 rank 到达后覆盖低 rank。
  `tdx_transaction`（L1 分笔自算）保持 rank 0，不进入资金列。
- `ThemeFundCache._parse_fund_row` 放开为接受 `eastmoney_seed`、`ths_web_seed` 与
  `ths_main_monitor` 三类行；同一 code 按 source 优先级 + `sessionDate` +
  `sourceTs` 决定是否覆盖（高 rank 覆盖低 rank；同 rank 取新）。
- 行字段增加 `qualityFlags`（可选）：种子行标记 `fund_flow_estimated`；
  双源同日同股偏差 >30% 或符号相反时标记 `fund_flow_conflict` 并保留两值
  供诊断，不归零、不静默取一。

### 3.3 后端改动点

1. **mainMonitorDetail 进程内调度器**（新建，沿 2026-07-25 设计）：
   - 进程内直接调用 `ThsMainMonitorService.load_row`，不经 HTTP 回环；
   - P0/P1 到期优先队列：P0（当前可见/搜索/展开题材）30 秒，P1 180 秒；
     每批 5 只、并发 2、失败退避（30→60→120→300 秒）、系统性限流时
     全局暂停 30 秒 + 并发降 1，连续 3 批成功恢复；
   - `load_row` 结果写 `ThemeFundCache.put`（source=`ths_main_monitor`）；
   - owner 持久化：沿用 `set_owner_codes`/`get_owner_codes`，Redis 空时
     等首个浏览器 `marketCodes` 注册，浏览器断开不清 P1 owner。
2. **冷启动种子**（解决首屏空白）：
   - 启动时东财排行接口全市场一次填充（`MarketFundScheduler._warmup_then_run`
     已有预热，provider 自请求 `push2.eastmoney.com` clist 分页，写
     `eastmoney_seed` + estimated 行）；
   - 盘中低频兜底 15–20 分钟一次（当前 5 分钟可放宽，减少风控触发）。
3. **FastAPI 路由职责收窄**：`/ths-detail`、`/ths-fund-batch` 保留给
   `tools/THSBigOrder` 与诊断，前端主链路不依赖它们补齐资金。
4. `python-bridge` 保持现状（`fund_flow_patch` 已广播）；是否纳入前端
   由 3.1 的"实时"层开关控制。

### 3.4 前端改动点

1. `marketFundStream.ts:84` 过滤条件放开：接受 `ths_main_monitor`、
   `eastmoney_seed`、`ths_web_seed`，按优先级映射。
2. `moneyFlowSourcePriority.ts` 增加 rank 映射（见 3.2）。
3. 展示：种子值带"估算"角标（`moneyFlowEstimated`，`statusClassifier.ts`
   已有识别）；L2 校准后替换并去角标；校准跳变（含符号反转）允许且打
   `fund_flow_conflict` 标记，不静默吞掉。
4. 首帧体验：WebSocket 连接后立即收到 `fund_full_state`（Redis last-good，
   冷启动时为种子行），随后 `fund_patch` 增量；**任何 HTTP 请求不得同步等
   待资金补齐**（检查并移除前端残留的同步资金请求路径，如
   `QuoteService.ts` 中 legacy HTTP 资金增强，现有测试已断言其不作为权威源）。

## 4. 限流预算与预期效果

- 30 req/min 预算内：P0 可见行约 25 只 ≈ 50 秒；全池 200 只 ≈ 5–7 分钟；
  400 只 ≈ 13 分钟（展示池上限）。
- 首屏：0 秒出布局；资金列立即显示种子值（有数不空白）；P0 行 30 秒内
  显示 L2 可信值；全池 5–7 分钟全部校准。
- 非交易时段：显示最近交易日 L2 last-good；从未采集的 owner 股票低速
  冷补（沿用 2026-07-25 设计：接受最近交易日总额，不硬编码周末/节假日）。

## 5. 验收标准

1. 冷缓存启动：首屏资金列无大面积空白（种子值 + 估算标记）。
2. P0 股票 30 秒内出现 `ths_main_monitor` 值，P1 随后逐批校准，
   首轮完成后 P0/P1 按 30s/180s 持续轮转（不出现"填满后静止"）。
3. 同一股票资金列与题材聚合显示同一 `code + version + zlje`。
4. `eastmoney_seed` 与 `ths_main_monitor` 并存不互相覆盖；校准后
   符号/数值跳变可见且带标记，不归零、不静默。
5. THS 单票失败不影响同批其余股票、不清空 last-good；系统性限流后
   并发降 1，恢复后自动回 2。
6. 页面刷新/浏览器断开不停止后台调度器；Redis last-good 不因重连变零。
7. 运行期无全市场 L2 长请求；`tools/THSBigOrder` 仍走 FastAPI 路由。
8. 正式快照 `stock_rows`/`sector_rows` 不含 `ths_web_seed`/`ths_main_monitor`
   运行态资金（沿用既有约束，`builders.ts` 已带 source 字段可核对）。

## 6. 回退边界

- 保留开关可停止 mainMonitorDetail 调度器，继续读 Redis last-good/种子行；
  回退不得恢复东财或 TDX 资金 fallback，不清空资金缓存。
- akshare 种子失败不影响 L2 校准（独立熔断，`SYSTEMIC_ERRORS` 冷却）。
- 上线首日人工验证：查 Redis `theme-fund:v3` 行数、`ths_main_monitor` 覆盖数、
  `fund_flow_conflict` 样本（遵循 AGENTS.md 第 11 节：不只看 API status）。

## 7. 风险与未决问题

- **归档路径与设计不一致（已发现）**：`ThsMainMonitorService` 单票 gzip 归档
  实际写 `quant-board/backend/services/data/big-order/ths/`，而设计文档
  （`big-order-redis-cache-design.md`）规定落 `quant-board/data/big-order/ths/`
  （已被 `.gitignore` 忽略）。已把 `backend/services/data/` 加入 `.gitignore`
  避免提交运行产物；路径本身统一为后续待办（改动需确认归档读取方）。

- **种子值跳变**：东财口径与 L2 近似（实盘验证差异远小于同花顺网页口径），
  校准跳变很小；但**存量 `ths_web_seed` 历史数据（同花顺网页口径）与 L2
  数值/符号都可能不同**，旧缓存被 L2 覆盖时仍可能出现跳变，属预期，前端
  带估算角标 + source 显示。
- **`fund_cache.py` 兼容**：`_parse_fund_row` 目前强校验 source 与 zlje 有限，
  放开 source 后需同步收紧 `sessionDate`/`sourceTs` 校验，避免种子行污染
  L2 last-good。
- **前端过滤扩散面**：`marketFundStream.ts`、`moneyFlowSourcePriority.ts`、
  `RealtimeQuoteCoordinator.ts`、`QuoteService.ts` 多处判断 `ths_main_monitor`，
  放开需集中到 `moneyFlowSourcePriority` 单一入口，避免各点口径漂移。
- **未决**：实时层（`tdx_transaction`）是否默认启用——启用则同时解决
  首屏即时值并减少 L2 限流压力，但引入自算口径与 L2 不一致的风险，需
  用户确认（2026-07-25 设计曾否决，现 bridge 已跑通，可重新评估）。

## 8. 后续落地建议（简短，不搞重型分阶段）

1. ✅ **已完成（2026-08-08）**：source 契约拆分 + 前端优先级单一入口，
   覆盖测试已扩展（`moneyFlowSourcePriority.test.ts`、`marketFundStream.test.ts`、
   `test_theme_fund_cache.py`、`test_akshare_fund_provider.py`）。
2. ✅ **已完成（2026-08-08）**：mainMonitorDetail 进程内调度器
   （`ths_fund_refresh_scheduler.py`，每批 ≤5、并发 ≤2、180s 轮转、退避/冷却），
   `backend/main.py` 挂接，调度器测试 8 项通过。
3. ✅ **已完成（2026-08-08）**：P0/P1 可见行优先级——前端 fund-stream 协议
   上报 `priorityCodes`（热榜排序前 30 只，`RealtimeQuoteCoordinator` →
   `RealtimeSubscriptionRegistry` → `marketFundStream`），后端
   `MarketFundStream` 维护 priority 并集，`ThsFundRefreshScheduler` 按
   P0 30s / P1 180s 分级轮转（P0 到期优先），测试：`test_fund_stream.py`、
   调度器 P0/P1 用例、前端 registry/marketFundStream/coordinator 用例。
4. ✅ **已完成（2026-08-08）**：owner 持久化（`MarketFundStream._persisted`）——
   浏览器断开后调度器仍按最后已知池继续刷新（`market_codes/priority_codes`
   返回持久池），新订阅无缝替换；`/api/health` 的 `thsFundRefresh` 暴露
   `ownerState`（active/persisted/none）。
5. ✅ **已完成（2026-08-08）**：交易日时段策略——`_is_trading_time`
   （周一至周五 09:30-11:30、13:00-15:00），非交易时段已初始化则暂停请求
   （保留 last-good，`_compute_wait_seconds` 休眠到下一时段开始）；**冷启动例外**：
   非交易时段且从未成功刷过（进程重启/MongoDB 空库）时允许刷一轮——THS
   接口返回最近交易日完整 L2，保证刷新页面/冷启动后首屏资金列不空
   （`_needs_cold_init`）。**非交易时段冷启动那轮只写 Redis 热缓存
   （首屏有值），不写 MongoDB**——MongoDB 只固化交易时段盘中校准数据，
   避免依赖 THS 非交易时段行为产生垃圾文档（2026-08-08 用户确认约束）。
6. ✅ **已完成（2026-08-08）**：Redis 容灾恢复（用户确认）——`theme-fund:v3`
   TTL 默认 900s → **7 天（604800s）**：冷启动 MongoDB 不可用时，Redis 里
   最近交易日 L2 行由 `get_latest` 兜底恢复（内存 miss → Redis 回填，
   fund_cache `_read_latest` 既有链路）；调度器每次写入刷新 TTL，正常运行
   永不过期；8001 快照采集器跨进程读资金也受益（非交易时段暂停后不再
   15 分钟过期）。
6. ⬜ 待办：直接生产小范围观察（首个完整交易日查 Redis/MongoDB 实际入库），不设影子/对比阶段。
