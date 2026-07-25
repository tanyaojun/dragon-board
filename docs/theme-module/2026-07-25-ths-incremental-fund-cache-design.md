# THS 主力资金增量缓存修订设计

## 状态

本设计替代已否决的通达信逐笔资金 WebSocket 方案，并修正此前 THS 增量缓存方案的两个缺陷：

1. 旧方案只描述首次补齐，没有定义首轮完成后的盘中持续刷新。
2. 旧 `/api/quotes/ths-money-flow` 会在缓存未命中时同步等待一批单票请求，仍可能造成长请求超时和批量缺失。

## 目标

- 行情列表“主力净额”和题材面板“主力资金”只消费同一份 THS 缓存记录。
- 首屏立即显示 Redis last-good；从未采集的股票显示 `--`，后台分批补齐。
- 首轮补齐后调度器继续运行，盘中按优先级持续刷新动态资金数据。
- THS 单票失败、限流或暂时不可用时保留最近成功值，不清空、不写零、不阻塞页面。
- 不恢复 `/api/quotes/eastmoney`，不显示“资金数据降级”。
- `tools/THSBigOrder/**` 的 THS 单票主链改读 QuantBoard FastAPI；分钟线改读 python-bridge 的 mootdx 分时接口并废弃腾讯分钟线。普通行情、涨停池和 Longhu 等其它来源仍暂时使用 legacy proxy。

## 非目标

- 不再使用 `python-bridge` 逐笔成交计算主力资金。
- 不扫描约 4,000 只题材映射股票作为盘中资金采集全集。
- 不要求所有股票在同一个 HTTP 请求内完成刷新。
- 不把 THS 运行态资金缓存作为 QuantBoard 正式回测资金口径。

## 数据范围

资金订阅集合是以下代码的去重并集：

1. Dragon Board 当前行情列表股票。
2. 当前展开题材的成分股。
3. 用户关注或其它明确登记的资金订阅股票。

题材映射全集只用于股票与题材归属，不进入默认盘中刷新队列。行情列表约 200 余只与题材映射约 4,000 余只不得比较行数，也不得作为同一覆盖率门禁。

QuantBoard 必须维护服务端资金 owner 作为 P1 基础集合，不能把队列生命周期绑定到浏览器连接。正常启动从 Redis 恢复 owner；全新或被清空的 Redis 没有 owner 时，调度器保持空闲，首个 Dragon Board 连接提交当前实际行情列表 `marketCodes` 后立即持久化为 P1。浏览器只提交当前可见、搜索结果和展开题材等 P0 优先级提示；浏览器断开后 P0 提示被清理，但已持久化的 P1 owner 和后台调度器继续运行。资金链不再通过 proxy startup bundle 恢复 owner。

## 数据口径

THS 上游使用现有 `mainMonitorDetail` 数据：

```text
主力净额 = title.mainbuy - title.mainsell
```

金额统一转换为元。每条缓存记录至少包含：

```text
code
zlje
sessionDate
source = ths_main_monitor
moneyFlowSource = ths_main_monitor
sourceTs
updatedAt
version
```

无法解析 `mainbuy`、`mainsell` 或 `sessionDate` 的响应不得覆盖 last-good。缺失值保持空，不得转换为 `0`。

## 架构

```text
THS mainMonitorDetail 单票接口
        ↓ 小批量、低并发
QuantBoard THS service
      ↙                ↘
FastAPI 单票/批次路由   生命周期内刷新调度器（直接调用 service）
      ↓                ↓
tools/THSBigOrder      Redis THS last-good 唯一缓存
        ↓
QuantBoard 本地资金 WebSocket 增量推送
      ↙                              ↘
行情列表主力净额                 题材主力资金聚合
```

职责边界：

- QuantBoard THS service：请求 THS、校验响应、解析金额和交易日期，并提供单票与最多 5 只的低并发加载能力。
- FastAPI：暴露兼容单票 `/api/big-order/ths-detail` 和批次 `/api/big-order/ths-fund-batch`，供 `tools/THSBigOrder`、诊断和外部调用；不承担全市场长请求。
- QuantBoard 调度器：维护订阅集合、优先级、到期时间、失败退避和持续轮转，进程内直接调用 THS service，不通过本机 HTTP 回环。
- Redis：保存每只股票最近成功记录、版本和服务端 owner，不使用短 TTL 删除 last-good。
- Dragon Board：提交 P0 可见优先级提示、接收首帧缓存和后续增量，不直接轮询 THS。
- `python-bridge`：继续提供价格、涨幅、成交量和成交额，不再提供资金字段。
- `python-bridge` 分时：修复 `/api/quotes/minute`，使用 mootdx `Quotes.minutes(symbol, date)` 和 TDX 标准交易日历选择权威日期；交易日盘中选择当天并允许 1..240 个有序点，收盘后和非交易日选择最近已完成交易日并期望 240 点，停牌或上游不完整时结构化标记 `complete=false`，不补造点。不再调用底层 `get_minute_time_data` 后自行假定“今天”。`vol` 按手处理，累计成交量保持手，累计成交额按 `price × vol × 100` 元累加。
- bridge 分时请求必须与行情批量拉取共用 `fetch_lock`；锁内执行 `ensure_client()` 和 `Quotes.minutes()`，不得并发使用同一 TDX 连接造成协议响应串包。
- `tools/THSBigOrder` 必须把 THS 明细的权威 `sessionDate` 与 bridge 分时点日期逐次比对；即使 bridge HTTP 请求成功，日期不一致、混入多个日期或无法推断日期也按分钟源失败处理，绝不能写入 minute last-good。若已有同一权威日期且仍在期限内的 minute last-good，可继续按 stale 展示。
- `tools/THSBigOrder` 的 last-good 期限只能依据权威 `sessionDate` 与当前自然日的关系及日内时段判断，不得使用 `DayOfWeek`、周六/周日或自维护节假日推断交易日。当前日期会话盘中上限 5 分钟，已完成历史会话上限 7 天；THS 大单明细的盘中/盘后 UI stale 也必须使用同一日期关系，不能硬编码周末。
- Snapshot collector：不读取本运行态缓存，不把 THS 行写入正式 `stock_rows`、`sector_rows` 或回测质量合同。
- `proxy-server`：不再承载 THS `mainMonitorDetail` 或腾讯分钟线；旧 `/api/big-order/ths-detail`、`/api/quotes/tencent/minute`、对应 OpenAPI/cache TTL/测试在迁移完成后删除。腾讯批量基础行情和其它 legacy 路由按独立任务逐步迁移和瘦身，本次不扩大范围。

## FastAPI 适配接口约束

批次接口每次最多接受 5 只股票，并发只允许 1 或 2。它只负责当前小批次，不得等待整个行情股票集合。超时只作用于单只上游请求；任一股票超时不得中断同批其它股票，也不得中断后续队列。调度器复用同一 service 的批次加载方法，不请求 FastAPI 自身。

单票接口保持现有工具需要的 envelope 与原始 THS `data`，并提供权威 `sessionDate`、`fetchedAt`、`servedAt` 和 `data.dragonMeta.cache.uiStale`；批次接口返回标准化的 `zlje` 行和逐票失败。两条路由必须共用请求、校验和错误分类，不能形成两套 THS 解析口径。单票 raw payload last-good 与 dashboard `theme-fund:v3` 分离；上游失败时可返回同一 `sessionDate` 的 raw stale，不能用只有 `zlje` 的资金行冒充大单明细。

THS service 还必须拥有进程级共享请求门控：FastAPI 单票、FastAPI 批次和 scheduler 直接调用共用同一个 semaphore、`cooldownUntil` 和有效并发。scheduler 检测到系统性限流后更新共享门控，外部工具和诊断路由在冷却期也不得绕过暂停继续请求 THS。

旧实现中的以下行为不恢复：

- 前端把 20 只股票作为一个长请求并同步等待全部缓存未命中。
- 请求局部的后台刷新集合，导致多个请求重复刷新同一股票。
- 连续失败后跳过整个剩余队列。
- 60 秒有效、300 秒后删除的资金缓存。
- 20 秒单批超时失败后丢弃该批全部可用结果。

小批次必须返回逐股票结果和失败项，成功股票立即入库，失败股票由调度器独立重试。

## 首次加载

1. QuantBoard 启动时从 Redis owner 恢复行情股票 P1 集合；owner 为空时不猜测股票池，也不读取 proxy startup bundle，等待首个 Dragon Board `marketCodes` 注册实际行情集合。
2. 浏览器提交行情股票集合和 P0 优先级集合；前者更新服务端 owner，后者只影响当前连接的优先级。
3. QuantBoard 立即返回 Redis 中已有的 last-good，不等待上游。
4. 缓存缺失股票进入最高优先级首次补齐队列。
5. 当前表格前排股票、搜索结果和展开题材股票先补齐，其余行情股票随后补齐。
6. 每个小批次完成后立即写 Redis 并推送增量，不能等待首轮全部完成。
7. 首轮完成后股票自动进入盘中持续刷新队列，调度器不得停止。

服务端已有 owner 时必须在浏览器连接前恢复；仅在 Redis 全新或被清空时允许首个浏览器 `marketCodes` 建立 P1 基础集合。建立后 owner 独立持久化，后续浏览器订阅只能更新实际行情集合和调整优先级，断开连接不得清空 P1。

## 盘中持续刷新

刷新使用按 `nextRefreshAt` 排序的到期优先队列，而不是固定全量定时任务。

| 优先级 | 股票范围 | 目标刷新间隔 |
| --- | --- | --- |
| P0 | 当前表格可见、搜索结果、当前展开题材股票 | 30 秒 |
| P1 | 行情已加载但当前不可见的其余股票 | 180 秒 |

默认执行参数：

- 每批 5 只。
- THS 并发 2。
- 每完成两个 P0 批次，至少处理一个已到期 P1 批次，防止低优先级饥饿。
- 每次成功写入后重新计算该股票的 `nextRefreshAt`。
- 调度间隔加入少量随机抖动，避免形成固定请求节奏。
- 股票退出订阅集合后保留缓存，但停止盘中高频刷新。

P0 必须来自真实 UI 状态：主表按滚动容器计算当前可见行，主搜索框提交当前匹配代码，题材股票分页/搜索提交当前页代码；离开页面、清空搜索或关闭面板时必须清理对应 P0 owner。固定“榜首 50 只”只能作为首屏尚未测量出可见行前的临时种子，不能替代真实可见集合。

根据实测，THS 单票响应约为 0.27 至 1.54 秒。并发 2 时，约 220 只股票完成一轮需要约 80 至 150 秒，因此不能把全部股票设置为 15 或 30 秒刷新。

## 交易时间策略

交易日判断只使用通达信标准交易日历，不硬编码周末或节假日。

该约束适用于本资金链新增或修改的所有运行时代码，包括 QuantBoard scheduler、python-bridge、Dragon Board 前端和 `tools/THSBigOrder`。日历不可用时暂停上游刷新并保留 last-good，不允许回退到 `DayOfWeek`、自然日周末判断或自定义节假日表。

```text
09:15-09:30  返回最近交易日缓存，低频探测当天 THS sessionDate
09:30-11:30  P0 30 秒，P1 180 秒
11:30-13:00  暂停连续轮转，保留上午 last-good
13:00-15:00  P0 30 秒，P1 180 秒
15:00以后   对当前订阅集合执行一轮收盘刷新并冻结 sessionDate
非交易日    读取最近交易日缓存；仅对从未采集的 owner 股票执行一次低速冷补齐，不持续轮转
```

若 THS 返回的 `sessionDate` 仍是上一交易日，记录可以作为 last-good 返回，但不得标记为当日已刷新。非交易日冷补齐必须接受 THS 返回的最近交易日总额，否则新缓存命名空间在周末切换时会永久为空。

## 限流与失败处理

单股票失败只影响该股票：

```text
第 1 次失败：30 秒后重试
第 2 次失败：60 秒后重试
第 3 次失败：120 秒后重试
后续失败：最多退避到 300 秒
```

检测到系统性限流、验证码或连续批次上游失败时：

1. 全局暂停新请求 30 秒。
2. 并发从 2 降为 1。
3. Redis last-good 继续提供服务。
4. 连续 3 个批次全部成功后恢复并发 2。
5. 不清空队列，不跳过尚未处理股票。

THS service 和 FastAPI 必须返回机器可判定的逐票错误码：`ths_rate_limited`、`ths_captcha_required`、`ths_timeout`、`ths_upstream_unavailable`、`ths_invalid_payload`。前两类和同批全部为 `ths_upstream_unavailable` 触发全局暂停；超时、非法单票 payload 和局部上游失败只触发单票退避。

## 一致性

- 行情列表和题材聚合以 `code + version` 读取同一 Redis 行。
- 题材服务不得再次请求 THS，只聚合缓存中的 `zlje`。
- 每个 WebSocket subscriber 的资金读取/推送范围是其 `marketCodes ∪ priorityCodes`；只有 `marketCodes` 持久化为 P1，题材分页等 `priorityCodes` 只作为连接级 P0，断开时清理。
- 题材服务在资金版本变化时只重算资金聚合并失效展开股票缓存，不得因每个五股 patch 重新抓取 4,000 只腾讯行情。
- 前端收到同一股票低版本数据时必须拒绝覆盖高版本数据。
- 新缓存使用独立命名空间，不读取旧 `tdx_transaction` 行；不再接受 bridge、逐笔累计或其它来源覆盖 THS 缓存。
- 运行态 THS 资金不得进入 snapshot collector、MongoDB 正式快照或 QuantBoard 正式回测；正式资金流仍只接受 `broker_l2` 或 `official_l2`。

## 状态与展示

- 有 last-good：继续显示最近成功值。
- 从未采集：显示 `--`。
- 刷新失败：保留旧值，不显示“资金数据降级”。
- 非交易日：显示最近交易日 THS 值。
- 题材主力资金只聚合已有股票资金，不把缺失股票当作零；同时在内部保留已覆盖数量和总数量供诊断。

## 验收标准

1. 冷缓存启动后，P0 股票优先出现资金值，P1 股票随后逐批补齐。
2. 首轮完成后继续观察 10 分钟，P0 股票至少更新多次，P1 股票按轮转刷新，不出现“填满后静止”。
3. THS 单股票失败不影响同批成功股票，也不清除旧值。
4. 模拟 THS 系统性限流后，并发降为 1；恢复后自动回到 2。
5. 行情列表与题材面板对同一股票显示相同 `code + version + zlje`。
6. 页面刷新或浏览器关闭不会停止 QuantBoard 后台刷新器，P0 代码只降级为 P1。
7. bridge 或前端重连不会把 THS last-good 改成零或空。
8. 非交易日显示最近交易日资金，且 `sessionDate` 正确。
9. 运行期间没有 `/api/quotes/eastmoney` 请求，没有 THS 全量长请求。
10. `tools/THSBigOrder` 的 THS 单票主请求只访问 FastAPI `8000`；分钟线只访问 bridge `8765`，不再出现腾讯分钟线域名或 `/api/quotes/tencent/minute`；工具的普通行情、涨停池和 Longhu 请求仍访问 legacy proxy `3000`。
11. Snapshot collector 生成的正式 stock rows 不含 `ths_main_monitor` 资金字段。
12. 同一资金 patch 到达后，行情行、已展开题材股票行和题材聚合在节流窗口内使用同一最新版本，且不会触发全市场行情重抓。
13. `proxy-server` 不再注册或文档化 THS `mainMonitorDetail` 路由；QuantBoard 调度器的 THS 刷新在停止 3000 后仍可工作。
14. 交易日盘中 bridge 分时返回当天 1..240 个真实点；收盘后/非交易日返回最近已完成交易日且正常股票为 240 点。价格有效、累计量额单调，成交额单位为元，不伪造缺失点。
15. `tools/THSBigOrder` 拒绝成功但日期不同于 THS 权威 `sessionDate` 的分钟响应，不缓存该响应；同日期未过期缓存可 stale，跨日或过期缓存必须显示缺失/失败。
16. 本资金链改动范围内运行时代码扫描不到 `DayOfWeek.Saturday/Sunday`、`getDay()`、`Sat/Sun` 等交易日推断。

## 回退边界

上线前保留开关，可停止 THS 后台刷新器但继续读取 Redis last-good。回退不得恢复 Eastmoney 或 TDX 资金 fallback，也不得清空 Redis 资金缓存。

当前 Redis 使用 RDB 快照而非 AOF，不能承诺进程异常退出前的最后一次资金更新全部落盘。验收时必须记录资金行/version/owner，执行 `BGSAVE` 并确认 `LASTSAVE` 前进，再重启 Redis 核对同一记录；若要求分钟级更新零丢失，再单独评估启用 AOF，不能在本设计中默认其已开启。
