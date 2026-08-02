# proxy-server → QuantBoard Python 迁移计划

> 目标：把 `proxy-server`（Node/Express）的外部数据接口整体迁移到 QuantBoard Python 后端
> （`backend/market_proxy/**`），akshare 能覆盖的用 akshare，覆盖不了的用 httpx 直连原上游
> 并自行实现解析。前端 `/api` 消费合同尽量保持不变，逐步删除 proxy-server 路由，
> 最终 Node proxy 只保留 QuantBoard 转发（或整体停用）。

## 约束

- **不使用东方财富（东财）接口**：akshare 的 `*_em` 系列（行情、涨停池、热榜、盘口）全部排除；
  proxy 现有的 `/api/eastmoney/hot` 是否继续直连东财需用户确认（它是现役热榜平台之一）。
- 响应 JSON 结构尽量与 proxy 现状一致（`data.diff / data.info / List / items` 等），
  前端 apiService 只改 baseURL 指向和个别 akshare 源的字段映射。
- fail-visible：任一上游失败时保留 last-good/降级结构，不返回伪造空值；只有全源失败才报无数据。
- 每批交付必须跑：quant-board `pytest`、proxy-server `node --test`（未删路由时）、前端相关 Vitest、vue-tsc、
  真实浏览器验证（Playwright）。

## 现状接口清单

### A. 数据源代理（迁移目标）

| 路由 | 上游 | akshare 替代 | 迁移方式 |
|---|---|---|---|
| `/api/market/overview` | THS 10jqka real_index_data | `stock_zh_index_spot_sina()` ✅ | akshare，形态转换 |
| `/api/quotes/tencent`、`/api/quotes/sina` | 腾讯/新浪逐批 | `stock_zh_a_spot_tx()`（全市场 49s） | 后台周期缓存，前端读缓存 |
| `/api/quotes/tencent/spk` | 腾讯盘口 | 无 | httpx 直连复刻 |
| `/api/limitup/10jqka` | THS 涨停池 | 无（东财排除） | httpx 直连复刻 |
| `/api/limitup/ths/pools` | THS 细分涨停池 | 无 | httpx 直连复刻 |
| `/api/limitup/detail` | THS（已 deprecated） | 无 | 复刻或直接删除 |
| `/api/surge-stock/performance` | 选股宝 | 无 | httpx 直连复刻 |
| `/api/sentiment/composite` | 聚合 overview/limitup/surge | - | 复刻聚合 |
| `/api/xueqiu/hot` | 雪球（需 cookie） | 无 | httpx 直连复刻 |
| `/api/cls/hot` | 财联社（sign） | 无 | httpx 直连复刻 |
| `/api/ths/hot` | 同花顺 | 无 | httpx 直连复刻 |
| `/api/kpl/hot` | 开盘啦 | 无 | httpx 直连复刻 |
| `/api/tdx/hot` | 通达信 | 无 | httpx 直连复刻 |
| `/api/tgb/hot` | 淘股吧 | 无 | httpx 直连复刻 |
| `/api/dzh/hot` | 大智慧 | 无 | httpx 直连复刻 |
| `/api/eastmoney/hot` | 东财 emappdata | 东财（被排除） | **待用户确认** |
| `/api/xuangubao/events` | 选股宝事件 | 无 | httpx 直连复刻 |
| `/api/big-order/*` | THS 大单监控/龙虎榜 | 无 | httpx 复刻 + 归档/采集/缓存 |
| `/api/theme/:id`、`/api/themes/batch` | 开盘啦题材（deprecated） | 前端已用 QuantBoard themes | 直接删除 |

### B. 本地服务/编排（另议或保留）

| 路由 | 说明 | 建议 |
|---|---|---|
| `/api/tdx-blocks*` | 通达信本地板块文件扫描 | 可搬 Python（读本地文件），或保留 |
| `/api/notifications/*` | 飞书事件雷达 | 保留 proxy 或搬 Python |
| `/api/local-voice/*` | Windows 本地语音 | 保留 proxy |
| `/api/opening-signals*` | 本地开盘信号存储 | 保留或搬 Python |
| `/api/cache/startup-bundle` | Redis 启动缓存 | 保留（或 QuantBoard 侧等价） |
| `/api/snapshots/remote/*` | 快照远端 bundle（死代码，未挂载、无引用） | ✅ Batch 4 已删除 |
| `/api` catch-all | 转发 QuantBoard :8000 | 迁移完成后保留为兜底，或前端直指 :8000 |

## 目标结构

```text
quant-board/backend/market_proxy/
├── __init__.py
├── router.py            # FastAPI 路由汇总（挂载 /api 同路径）
├── cache.py             # 进程内/Redis 缓存（复刻 proxyCache 语义：ttl/stale/last-good）
├── response.py          # 降级响应（sendDegraded 等价）+ attachCacheMeta
└── providers/
    ├── indices.py       # akshare 指数（新浪）
    ├── quotes.py        # akshare 腾讯全市场 + 腾讯/新浪逐批 httpx 复刻
    ├── limitup.py       # THS 涨停池/细分池 httpx 复刻
    ├── hotlists.py      # 八平台热榜 httpx 复刻（含 CLS sign、雪球 cookie）
    ├── xuangubao.py     # 事件/昨日涨停
    └── big_order.py     # THS 大单监控/龙虎榜 + 归档采集
```

## 批次与验收

### Batch 1：akshare 直接覆盖（指数 + 行情）

- 新增 `GET /api/market/overview`（akshare 新浪指数，内存缓存 10s，输出转现有合同）。
- 新增行情缓存：后台任务每 60–300s 拉 `stock_zh_a_spot_tx()`，内存 last-good；
  `GET /api/quotes/tencent|sina` 改为读该缓存并映射 `zsz/ltsz/pe_ttm/pn → f20/f21/f9/f23`。
- 前端：`apiService` 的 market/quote context 指向 8000；`QuoteService` 字段映射同步。
- proxy：删除 `/api/market/overview`、`/api/quotes/tencent`、`/api/quotes/sina` 路由
  （`/api/sentiment/composite` 同步改源）。
- 验收：pytest + 前端 Vitest/vue-tsc + Playwright 验证行情页指数、市值、PE/PB 渲染。

### Batch 2：热榜 + 涨停池 + 昨日涨停 + 情绪

- Python 复刻 8 平台热榜、THS 涨停池（10jqka + pools + detail）、surge-stock、sentiment/composite。
- 前端 `platform/limitup/breath` context 指向 8000；响应合同不变。
- proxy：删除对应路由。
- 验收：pytest（含上游 mock）+ 浏览器验证热榜/涨停池/情绪面板。

### Batch 3：选股宝事件 + 大单/龙虎榜 + 题材删除

- Python 复刻 xuangubao/events、big-order（main-monitor/all-day/longhu 归档与盘后采集）。
- 删除 deprecated 题材路由（前端确认无引用）。
- proxy：删除对应路由。
- 验收：pytest + 大单面板浏览器验证 + 归档目录抽查。

### Batch 4：服务类收尾

- ✅ 2026-08-01 与用户确认：proxy-server 保留为「本地服务壳 + `/api` 转发」（方案 A），
  前端/采集器 baseURL 与启动器均不改；QuantBoard 快照采集器仍以 `http://127.0.0.1:3000`
  为入口（startup-bundle/热榜/行情/涨停池经 proxy 转发到 8000），因此 proxy 不可整体停用。
- ✅ 死代码清理（无引用即删）：`/api/quotes/tencent/spk`（前端无引用）、
  `proxy-server/snapshotRemoteRoutes.js`（未挂载的遗留 WebDAV 实现）、
  `helpers/http.js` 中已无引用工具（cleanCode/parseCodeList/getMarketPrefix/delay）。
- ✅ 保留项（内部工具链，待用户后续确认）：`/api/big-order/longhu/*` 盘后归档/采集、
  tools 下 C# 项目（DragonBoardLauncher/VoiceWorker 在用，THSBigOrder/TdxL2Helper/YiDongJingLing 未删）。
- 验收：proxy `node --test` + 前端 Vitest/vue-tsc + quant-board pytest + 真实冒烟（详见下方进度）。

## 回滚

- 每批删除 proxy 路由前，先在 QuantBoard 完成同路径接口并联调通过；
  proxy 路由删除用 git 可回退（不动用户未提交文件之外的内容）。
- 若上游不可用，后端返回与现状一致的降级结构，前端不空白。

## 进度

- ✅ Batch 1（2026-08-01）：
  - QuantBoard 新增 `backend/market_proxy/quotes.py`（腾讯全市场行情周期缓存，last-good）、
    `backend/market_proxy/indices.py`（新浪指数概览，10s 缓存）、
    `backend/api/market_data_routes.py`（`/api/quotes/tencent|sina`、`/api/market/overview`），
    已在 `main.py` 挂载并启动后台刷新任务。
  - proxy-server：删除 `/api/quotes/tencent`、`/api/quotes/sina`、`/api/market/overview` 实现，
    加入 `/api/market/`、`/api/quotes/` 转发前缀；`/api/sentiment/composite` 的 overview 腿改指 :8000；
    同步清理 quotes 路由单元测试与两条缓存键测试。
  - 验证：quant-board pytest 1100 passed；proxy `node --test` 117 passed；
    前端 QuoteService/QuoteHttpFeed 14 tests + vue-tsc 通过；真实接口冒烟
    （overview 返回 562 个新浪指数，quotes 路由可用、缓存为空时返回空 diff）。
- ✅ Batch 2（2026-08-01）：
  - QuantBoard 新增 `backend/market_proxy/hotlists.py`（八平台热榜 httpx 直连 + 60s TTL + last-good）、
    `limitup.py`（THS 涨停池/细分池，浏览器 UA，30s 缓存）、`surge.py`（选股宝异动）、
    `sentiment.py`（情绪聚合，单腿失败降级），路由统一挂在 `backend/api/market_data_routes.py`。
  - 雪球 cookie 统一放 `quant-board/.env.local`（settings 自动加载）。
  - proxy-server：删除 `routes/hotlists.js`、`routes/market.js`（含 limitup/detail deprecated 路由），
    新增 8 平台 + limitup/surge/sentiment 转发前缀；`tdx.js` 对 `/api/tdx/hot` 放行转发；
    openapi/docs/缓存路由测试同步清理。
  - 验证：quant-board pytest 1113 passed；proxy `node --test` 109 passed；
    前端 PlatformHotlist/LimitUpFeed/ThsLimitUpEventFeed 17 tests 通过；
    真实冒烟：THS 热榜 100 行、大智慧 100 行、东财 100 行、选股宝 2 行、雪球 100 行、
    涨停池 98 只、8 个细分池全部可取。
- ✅ 热榜链路加固（2026-08-02，P0/P1/P2/P3）：
  - 根因：慢上游（eastmoney/tdx/cls 实测 8~27s）超过前端 8s 硬超时，且前端把超时 abort 一律当“取消”不重试；
    迁移后只有进程内 60s 缓存，刷新页面反复触发慢上游，出现 5~6/8 平台空榜。
  - P0 前端：`apiService` 区分“超时中断（可重试）”与“调用方取消（不重试）”，每次尝试独立 AbortController；
    PLATFORM 超时 8s→15s。
  - P1 后端：`HotlistService` 上游失败重试 1 次；失败降级结果负缓存 15s；缓存 TTL 从抓取完成时刻起算；
    httpx 超时 8s→12s。
  - P2 共享缓存：新增 `backend/market_proxy/cache.py`，热榜成功/失败结果写入 Redis
    （key `market:hotlist:{platform}:v1`，成功 TTL 60s、失败 15s），跨进程/跨刷新共享；Redis 故障自动回退不阻断。
  - P2 后台预取：`HotlistService` 内置 asyncio 调度器（启动即预取一轮，之后周期刷新），
    八平台排名写入 Redis，前端刷新直接命中缓存实现首屏零等待；间隔默认 **600s（10 分钟）**，
    可用环境变量 `QUANT_BOARD_HOTLIST_REFRESH_INTERVAL_SECONDS` 调整（最小 60s）；
    挂载于 `backend/main.py` 生命周期（startup 启动 / shutdown 停止），单平台失败不中断整体（fail-visible）。
  - P3 fail-visible：前端 adapter 不再 `catch → []` 伪装缺失，降级信封抛结构化 `PlatformLoadError`；
    平台加载状态（成功/失败+原因）经 `DataLayer.updatePlatformStatus` 发布，状态栏失败平台显示“失败”，
    具体原因可经 `dataLoader.getPlatformCacheDiagnostics()` 查询。
  - P3 失败判定加固：单次失败不再直接显示“失败”，失败平台每 1 分钟自动重试（`PLATFORM_RETRY_INTERVAL_MS`），
    连续 3 次失败（`PLATFORM_FAILURE_THRESHOLD`）才显示“失败”，期间显示“重试中”；任何一次成功即恢复并清零计数。
  - 验证：quant-board pytest 1139 passed；前端 825 passed + vue-tsc 通过；
    浏览器 8/8 平台全量显示且无 AbortError；Redis 负缓存跨实例 0ms 命中；状态栏失败态显示验证通过。
- ✅ Batch 3（2026-08-01）：
  - QuantBoard 新增 `backend/market_proxy/longhu.py`（龙虎榜 GetMainMonitor_w30 分页/重建/缓存/熔断）、
    `xuangubao.py`（选股宝事件双 host + 类型过滤 + 提取），路由挂到 market_data_routes。
  - proxy-server：删除 `routes/xuangubao.js`、`routes/deprecated.js`（题材路由无引用），
    bigOrder.js 移除 main-monitor/all-day（转发），新增 `/api/big-order/`、`/api/xuangubao/` 前缀；
    保留 longhu 盘后归档/采集路由（内部工具链，Batch 4 再定）。
  - 验证：quant-board pytest 1122 passed；proxy `node --test` 99 passed；
    真实冒烟：xuangubao events 50 行、longhu all-day 367 行（002297，合同匹配）。
- ✅ Batch 1-3 并行 code review + 修复（2026-08-01）：
  - Batch 1：修复 tqdm 静默模块路径（`akshare.stock.stock_zh_a_tx`）、空缓存时行情路由伪装成功
    （改为显式 `ok:false/degraded:true` 降级，仍保留 `rc:0/data.diff` 兼容前端）、
    `sh/sz/bj` 前缀 codes 被 400 拒绝（改用 `normalize_stock_code`，上限 120）。
  - Batch 2：八平台 GET/POST 分组与前端调用核对一致（eastmoney/tdx POST、其余 GET）；
    CLS 签名、雪球 cookie 加载、涨停池/情绪降级结构核对通过；测试 13 passed。
  - Batch 3：longhu 分页短页未校验（补 `truncated Longhu page response`，fail-visible）、
    big-order 路由 `int` 参数 422（改 `_coerce_int` 安全转换）、`_extract_events` 的 `data:null` 回退修正。
  - 收尾：`server.js` 启动横幅与实际路由对齐；`openapi.js` 清理迁移后空 tag（hotlists/quotes）；
    `/api/market/overview` 失败返回 503 + `staleData`（旧 proxy 为 200 degraded，已在 api-cli.md 注明）。
  - 验证：quant-board pytest 1129 passed；proxy `node --test` 99 passed；
    前端 QuoteHttpFeed/apiService 24 passed + 大单/事件 28 passed；vue-tsc 通过。
  - 未做项（Batch 4 收尾时补）：真实浏览器 Playwright 页面验收；`longhu._all_day_cache` 容量上限。
- ✅ Batch 4（2026-08-01）：
  - 确认最终形态：proxy-server 保留为本地服务壳 + `/api` 转发；前端/采集器/启动器不改。
  - 删除死代码：`/api/quotes/tencent/spk`、`snapshotRemoteRoutes.js`、`helpers/http.js` 未引用工具；
    `openapi.js`/`server.js` 横幅同步清理；`docs/snapshot-backup-architecture.md` 更新说明。
  - 保留：`/api/big-order/longhu/*` 盘后归档/采集、八平台本地服务（tdx-blocks/notifications/local-voice/opening-signals/startup-cache/tdx/:entry）。
  - 验证：proxy `node --test` 99 passed；前端 Vitest 926 passed + vue-tsc 通过；quant-board pytest 1129 passed。
