# THSBigOrder 整体升级设计

## 1. 目标

把现有 `tools/KPLViewer` 升级并完整重命名为 `tools/THSBigOrder`，以本地 `proxy-server` 为唯一数据入口，替换失效的 KPL 大单数据源，并按参考图升级为高密度大单监控终端。

成功标准：

- 目录、项目、程序集、命名空间和可执行文件统一为 `THSBigOrder`，窗口标题和产品名统一为“THS大单监控”。
- 大单明细和主力汇总来自同花顺，基础行情来自腾讯代理，涨停上下文来自同花顺涨停池。
- 不再请求东方财富，也不改变 Dragon Board 现有 KPL 大单接口的语义。
- 主界面具备顶部行情、主趋势图、资金趋势、信号点、分钟大单柱、资金热力和右侧明细。
- 数据源失败时有明确状态，不把缺失、陈旧或估算数据展示为实时精确数据。

## 2. 非目标

- 本期不实现竞价采样、竞价弱转强或竞价历史回放。
- 不实现真实 L2 十档、逐笔委托、完整盘口队列或盘口级封单变化。
- 不复刻参考软件未公开的私有指标公式。
- 不移除或改变现有 `/api/big-order/main-monitor`、`/api/big-order/all-day` KPL 兼容路由。
- 不引入大型图表框架或新的 UI 技术栈。

## 3. 命名迁移

统一迁移如下：

| 当前名称 | 目标名称 |
| --- | --- |
| `tools/KPLViewer/` | `tools/THSBigOrder/` |
| `KPLViewer.csproj` | `THSBigOrder.csproj` |
| `namespace KPLViewer` | `namespace THSBigOrder` |
| `KPLDataProvider` | `THSBigOrderDataProvider` |
| 程序集、产品、EXE | `THSBigOrder` |
| 窗口标题 | `THS大单监控` |

迁移只处理该工具自身引用，不顺手重构其它工具或 Dragon Board 主前端。

## 4. 数据架构

THSBigOrder 只访问 `http://127.0.0.1:3000`。每次刷新并行请求三条来源明确的代理接口：

1. `GET /api/big-order/ths-detail?stockCode=xxxxxx`
   - 上游：同花顺 `mainMonitorDetail`。
   - 提供：`title`、`list`、`pricechange`。
   - 用途：大单明细、名称、现价、涨幅、主买、主卖和分时涨幅。
2. `GET /api/quotes/tencent?codes=xxxxxx`
   - 提供：代理标准化的估算成交额 `f5`、成交量（手）`f6`、换手率 `f8`、量比 `f10` 及基础行情兜底。
   - `f5` 不是腾讯原始字段名语义，而是现有代理按用户确认口径生成：`f6 × 100 × f2（现价）`；桌面端直接读取，缺失或非有限值时显示 `-`。
3. `GET /api/limitup/10jqka`
   - 提供：封单额、封单量、开板次数、首次/最后涨停时间、连板高度、封板成功率、涨停类型和原因。
   - 无当前股票记录表示“非涨停池”，不是错误。

### 4.1 新代理路由

在现有大单路由模块中新增 `/api/big-order/ths-detail`，不替换旧路由。路由职责：

- 校验 `stockCode` 为六位数字。
- 以 GET 请求访问 `https://vaserviece.10jqka.com.cn/Level2/index.php?op=mainMonitorDetail&stockcode={stockCode}`，并使用固定的浏览器 User-Agent、Referer 和 JSON Accept 请求头。
- 校验上游 `errorcode`、`title` 和 `list` 基本结构。
- 按股票代码使用进程内短 TTL read-through 缓存，并允许短时间 stale fallback；此能力不依赖 Redis，代理重启后缓存自然清空。
- 缓存 value 保存真实 `fetchedAt`，每次响应另写 `servedAt`；客户端陈旧提示必须使用 `fetchedAt`。
- 返回结构化来源和缓存元信息；上游失败且无 stale 时返回 HTTP 200 degraded envelope（`ok=false/degraded=true/errorCode/data`）。

`/api/limitup/10jqka` 使用同一进程内短 TTL 缓存，但保持现有响应主体兼容。腾讯行情继续复用已有缓存。

### 4.2 客户端读模型

`THSBigOrderDataProvider` 把三路响应合并为一次不可变刷新快照：

- `StockSummary`：代码、名称、现价、涨幅、换手、量比、成交额。
- `MainFundSummary`：主买、主卖、净额、大单笔数。
- `LimitUpContext`：是否在池、封单、开板、连板、封板率、原因和时间。
- `BigOrderItem[]`：时间、金额、手数、成交价、四类性质和既有信号标记。
- `PricePoint[]`：同花顺分钟涨幅序列，以及由现价和当前涨幅反推的价格刻度。

四类性质映射固定为：

| 同花顺性质 | THSBigOrder 类型 |
| --- | --- |
| 主力主买 | 主动买 |
| 主力被买 | 被动买 |
| 主力主卖 | 主动卖 |
| 主力被卖 | 被动卖 |

## 5. 刷新、缓存和错误状态

- 默认每 6 秒刷新一次，手工刷新沿用同一流程。
- 同一时刻只允许一个刷新任务；同股票的定时重入直接跳过。切换股票时取消旧请求、递增请求代次并排队刷新最新代码，旧响应到达后必须因代码或代次不匹配而丢弃。
- 三路请求并行执行，分别记录成功、陈旧、缺失和失败状态。
- 同花顺大单失败时保留最后一次成功快照，并在界面显示“数据陈旧”和最后更新时间。
- 腾讯失败时换手、量比和成交额显示 `-`，不阻断大单列表。
- 涨停池成功但无代码时显示“非涨停池”；请求失败时显示“涨停数据不可用”。
- `proxy-server` 不在线时显示“代理服务未启动”，不回退为桌面端直连上游。
- 切换股票代码后不得显示上一只股票的缓存；只有代码一致的 stale 快照可以回退。
- 客户端先解析统一 proxy envelope，再解析业务数据；HTTP 200 degraded、合法空列表和网络连接失败是三个不同状态。

## 6. 界面设计

界面保持 WinForms 高密度暗色终端风格，并使用双缓冲自绘降低闪烁。

### 6.1 顶部信息区

分为三组：

- 股票行情：名称、代码、现价、涨幅、换手、量比、成交额。
- 主力资金：主买、主卖、净额和大单笔数。
- 涨停上下文：封单额、开板次数、连板高度、封板成功率和涨停原因摘要。

保留现有股票代码输入、通达信跟随、锁定、置顶、自动刷新、语音和分析入口。

程序图标只使用项目内 `icon.ico`，不再从外部网站下载；除本地代理外，THSBigOrder 不发起其它 HTTP 请求。

### 6.2 左侧图表区

新增一个专用双缓冲 `BigOrderChartControl`，同一时间轴分层绘制：

- 主图：分钟涨幅/价格趋势线。
- 资金线：按大单时间累计的主买金额减主卖金额。
- 信号点：现有点火、砸盘、买活跃、承接好。
- 分钟柱：按分钟聚合同花顺大单列表的买卖手数；明确属于“大单样本”，不是全市场完整成交量。
- 资金热力：按 30、50、100、300、500、700、1000 万阈值汇总买卖额和净额。

图表不展示无可靠公式的“趋势拉升”等私有指标名称。

### 6.3 右侧明细区

- 保留时间、金额、手数、均价、买卖性质、资金标记和买盘标记。
- 增加“全部 / 买盘 / 卖盘”切换，替代无真实第二来源的“渠1 / 渠2”。
- 保留金额筛选、颜色语义、排序、滚动和语音触发。
- 数据源陈旧时列表仍可查看，但标题区持续显示陈旧状态。

### 6.4 响应式桌面布局

- 默认 1280×800，左侧图表约占 72%，右侧明细约占 28%，最小窗口为 960×640。
- 宽度低于 1100 时隐藏完整涨停原因，只保留“查看原因”提示；低于 1020 时再隐藏封板成功率和最后涨停时间。窗口恢复后字段自动恢复。
- 使用 net48 应用 manifest 声明 PerMonitorV2/PerMonitor DPI awareness；字体、线宽和控件尺寸按 DPI 缩放，并验证运行中跨显示器切换。

## 7. 测试与验收

### 7.1 代理测试

- 股票代码校验。
- 同花顺成功响应透传/规范化。
- 空列表、上游错误码、结构缺失和超时。
- 缓存命中、并发请求合并和 stale fallback。
- 旧 KPL 路由回归测试，证明语义未改变。

### 7.2 C# 测试

- 四类成交性质映射。
- 手数、金额、百分比、逗号价格和日期时间解析。
- 三路数据合并及字段优先级。
- proxy HTTP 200 degraded、代理 stale 元数据和真实 `fetchedAt`。
- 非涨停池与涨停接口失败的区别。
- 陈旧快照只能回退相同股票代码。
- 刷新期间切股时旧响应不得覆盖新代码。
- 分钟柱、累计净额和阈值热力聚合。
- 既有点火、砸盘、买活跃和承接好逻辑回归。
- 金额/买卖/特殊标记组合筛选、语音跨股去重、跟随/锁定、自动刷新和分析窗输入。

### 7.3 构建与真实运行

- 运行受影响的 proxy-server Node 测试。
- Release 构建 `tools/THSBigOrder/THSBigOrder.csproj`。
- 在 `proxy-server` 在线时用固定 fixture 验证 002297 历史合同；实时 UI 验收从当日涨停池动态选择一只股票，并另选普通非涨停股和无效代码。
- 停止代理后验证明确错误状态，再恢复代理验证自动恢复。
- 检查 100%、125%、150% DPI 下的布局、文本截断、图表闪烁和窗口缩放。
- 记录实际 `DeviceDpi`、窗口尺寸和跨屏切换结果。
- 截图核对顶部信息、主图、底部聚合和右侧明细；确认没有控制台或未处理异常。

## 8. 影响范围

预计只修改：

- `proxy-server/routes/bigOrder.js`
- `proxy-server/routes/market.js`
- `proxy-server/helpers/proxyCache.js`
- `proxy-server/app.js`
- `proxy-server/server.js`
- `proxy-server/openapi.js`
- 邻近 proxy-server 测试
- `tools/KPLViewer/**` 到 `tools/THSBigOrder/**` 的迁移与升级
- `tools/THSBigOrder/app.manifest`、本地图标、过滤/刷新协调与邻近测试
- `docs/kpl-viewer/**` 正式设计和实施记录

不修改 RankTrend、QuantBoard、快照合同、DataLayer、python-bridge 或 TdxL2Helper。

## 9. 交付边界

最终交付应明确报告：

- 各字段实际来源和缓存状态。
- 成交额及分钟柱的计算口径。
- 封单是同花顺涨停池口径，不代表真实 L2 完整委托队列。
- 竞价明确未实现。
- 已运行的测试、构建与真实程序验收结果。
