# THSBigOrder 排查发现

## 2026-07-16

- 截图显示应用连接到 `tdxw（内存）`，状态为“数据不可用: 分时”，买入、卖出、净买均为 0。
- `tools/THSBigOrder` 存在尚未提交的相关改动：
  - `MainForm.Designer.cs`
  - `MainForm.cs`
  - `Parsing/ThsPayloadParser.cs`
  - `Program.cs`
  - `THSBigOrderDataProvider.cs`
  - 新增 `DataSources/LonghuBigOrderSourceClient.cs`
- 同时存在未跟踪设计文档 `docs/superpowers/specs/2026-07-16-thsbigorder-dual-source-design.md`。
- 这些文件的修改时间与截图日期相同，近期改动是当前首要调查方向，但尚未证明是根因。
- 工作区根目录确认是 `D:\dragon-board`。
- 截图中的当前代码为 `999999`，且“跟随通达信”已勾选。现有数据提供器仅校验六位数字，因此 `999999` 会通过输入校验并进入所有远端数据源。
- `999999` 不是正常沪深股票代码，可能来自通达信内存跟随逻辑的错误读取；这是目前更靠近数据源上游的首要假设。
- 当前双数据源改动默认仍选择 THS，因此新增龙虎解析器本身不会直接影响截图中的默认 THS 请求路径。
- 截图的“数据不可用: 分时”由 `SourceStatusFormatter` 根据 `Minute` transport 生成；该提示不代表大单数据源一定成功，只说明 transport 汇总中明确失败的是分时层。
- 本地代理正在监听 `127.0.0.1:3000`，不是“代理没启动”。
- 真实端点对比：
  - `THS ths-detail + 002963`：HTTP 200，响应约 10 KB，含股票名、价格和逐笔列表。
  - `THS ths-detail + 999999`：HTTP 200，但股票名为空、价格 `-`、主买卖 0、列表为空。
  - `Tencent minute + 002963`：HTTP 200，响应约 22 KB，含完整分钟点。
  - `Tencent minute + 999999`：HTTP 200 degraded，错误为 `invalid tencent minute payload`。
- 上述响应与截图完全一致，已确认截图的直接原因是应用向各数据源请求了 `999999`。
- 通达信通常使用 `999999` 表示上证指数，因此这不一定是随机内存垃圾，也可能是用户当前查看指数时被“跟随通达信”同步进来。THSBigOrder 只校验六位数字，没有区分个股与指数，导致指数代码覆盖当前个股并产生全空数据。
- Claude Code 的双数据源实现还存在独立问题：龙虎 `all-day` 对正常代码 `002963` 当前实测返回空列表；新客户端把所有异常吞掉后继续返回 Missing，UI 缺少根因信息。
- 进一步复测龙虎接口：
  - `main-monitor + 002963` 返回 7 条。
  - `main-monitor + 600519` 返回 100 条。
  - `all-day + 600519` 返回 28 条。
  因此龙虎代理总体可用，`002963 all-day` 空结果会由单页 fallback 补上。
- 当前 THSBigOrder 主项目 `Release` 构建成功（0 warning / 0 error）。
- 当前 THSBigOrder.Tests 构建失败：`THSBigOrderDataProvider` 新增 `longhuSource` 构造参数后，测试辅助方法仍按旧四参数签名调用，错误为 CS7036。这证明上一轮改动没有完成基本回归验证。
- 双数据源设计文档与实现也不完全一致：文档写“直连优先、代理 fallback”和 ComboBox，实现中的龙虎客户端却两条路径都只走代理，UI 使用两个 Button。
- `999999` 被接受的问题在最后一个已提交版本中已经存在，因此它不是 Claude Code 本轮新增的代码行；但本轮改动没有识别或防护这个真实入口问题。

## Longhu 分页真实合同

- Longhu 上游对 `st` 并非任意上限都稳定：实测 `100/150/200` 能按请求数量返回，`300/400/500` 分别可能只返回约 `30/18/0~26` 条，但 `Total` 仍是当日真实总量（例如 `17044`）。
- 因此“`List.Count < st` 表示最后一页”在 `st > 200` 时不成立，会把成功响应误判为末页或截断。
- 当前 C# 客户端固定 `PageSize=200`，以 `Total` 为主终止条件：
  - 累计数量达到 `Total` 才成功；
  - 未达到 `Total` 却返回短页时判定为截断失败；
  - `Total` 分页中变化、累计超过 `Total`、超过最大页数均失败。
- Longhu 真实单行是 6 元素数组：`[tradetype, unix, volume, money, price, datetime]`。
- 完整全日数据量可达 1~2 万条；`Total=17044` 时约需 86 个串行分页请求。并发分页实测会触发上游限流/异常，不能用并发提高速度。

## Redis 方案关键发现

- 只在代理 `/main-monitor` 上加缓存不能解决问题：当前 WinForms Longhu 客户端正常路径先直连上游，会绕过代理缓存。
- 只缓存分页也不够：首次 miss 或 TTL 到期仍可能重新触发约 86 个上游请求。
- Longhu 数据按“最新在前”返回且提供单调增长的 `Total`，适合缓存完整全天快照，并在刷新时先取头页，用 `newTotal - cachedTotal` 计算新增条数，再读取覆盖新增量和重叠校验所需的少量页。
- RankTrend Redis 的“事实源不变、Redis fail-open、namespace 隔离、缓存诊断元数据”可复用；但 BigOrder 是实时、TTL 驱动数据，不需要 ingest 反向索引失效。
- THS 主力资金现有“Redis 启用时优先、未启用时进程内回退、stale 立即返回、后台刷新、并发 2、连续失败熔断 5”更适合实时大单链路。
- 现有 `cache.enabled() ? cache : runtimeCache` 不能覆盖 Redis 启动后断线；BigOrder 方案需要 L1 进程缓存 + L2 Redis facade，两层写入、逐层读取和统一 single-flight。
- 推荐正常请求只经过本地 proxy：L1/L2 新鲜命中直接返回；stale 命中立即返回并后台刷新；proxy 完全不可用时 WinForms 只用同源同股且有时限的 last-good，不自动直连 Longhu。
- proxy 成为大单正常入口后，不能继续用 `DataTransport.ProxyFallback`，否则 UI 会永久显示“代理降级: 大单”；方案需增加 `ProxyPrimary` 正常态。
- 当前 proxy Longhu 上游仍是 GET 且每个分页请求生成新 DeviceID；“POST + 同轮 DeviceID”只在 C# direct 路径成立，Redis 实现必须先修正 proxy 合同。
- `Total delta` 增量依赖 prepend-only，现有样本尚不足以证明历史行永不修订/重排；方案增加实施前实测门禁、增量页 Total 稳定校验和轮转历史页审计。
- 自然日 key 会导致周末重复冷重建；Longhu 改用 row `sessionDate` + `latest` 指针，空结果不能覆盖非空指针。
- 全天列表是 MB 级大对象，不能复用默认 500 entries 的无字节预算 L1；方案增加专用 entry/byte 上限、money allowlist 和最多 4 个冷重建排队。
- 增量必须显式 fail-closed：默认 `off`；`prepend-device-snapshot` 与 `prepend-logical` 的 Total 变化测试合同分开，不能同时要求接受和拒绝。
- 既有实测表明 2 路并发会触发 Longhu 风控，因此完整、头部和历史审计统一全局并发 1。
- 全源 breaker 只统计 403/429/网络/系统性 5xx；短页、Total 漂移和单股 errcode 只进入 `{stock,money}` 冷却。
- 冷 miss、头刷和历史审计必须共用一个最多 4 项的有界调度队列，否则不同股票 stale 后台任务仍会无界积压。

## 2026-07-16 外部对抗性审计核验

核验依据包括当前 design/plan、同目录过程记录，以及
`THSBigOrderDataProvider.cs`、`LonghuBigOrderSourceClient.cs`、
`MarketSourceContracts.cs`、`proxy-server/routes/bigOrder.js`、
`proxy-server/helpers/proxyCache.js` 和 `src/services/big-order/BigOrderService.ts`。

| 审计项 | 判定 | 核验结论 |
|---|---|---|
| C1 客户端 15 秒超时与 proxy 冷启动冲突 | 成立 | Provider 当前共享 `HttpClient.Timeout=15s`；proxy 聚合 86 页后才响应时，单请求可能需要 17~30 秒，原验收标准不可达。修订为 Longhu 聚合请求专用 60 秒客户端、8 秒排队上限、45 秒完整重建上限。 |
| C2 findings/progress 与 design/plan 三处矛盾 | 成立 | design/plan 未实际落地“全局并发 1、两级失败归因、显式增量模式”，但 progress 错误写成“已处理”。必须同步正文并更正进度记录。 |
| I1 增量失败后续动作不明确 | 成立 | “放弃本次增量”没有定义是否/何时完整重建。修订为不覆盖缓存、记录单 key 失败；连续 2 次或交易时段数据年龄超过 60 秒时请求一次受冷却保护的完整重建。 |
| I2 envelope 缺 `sessionDate` | 成立 | C# 跨日 last-good 无可靠数据来源；不能用 `fetchedAt` 代替交易日。 |
| I3 技术 stale 直接映射 UI stale 会闪烁 | 成立 | 6 秒轮询与 10 秒 fresh TTL 会常态命中 SWR stale。修订为 `cache.stale` 只表示缓存层状态，UI 使用 `uiStale`/`fetchedAt` 年龄阈值。 |
| I4 `latest` 指针任务顺序靠后 | 成立 | Longhu session key 读取依赖指针，必须并入冷启动/读路径 Task 2。 |
| I5 20 秒完整重建预算不足 | 成立 | 86 页的页间延迟本身可达 8.6~17.2 秒，再加 RTT 后可能超过 20 秒。修订为 45 秒上限，并要求记录 elapsed/pages。 |
| I6 历史审计触发机制未定义 | 成立 | 不能新增 `setInterval` 守护任务；修订为搭普通请求/刷新便车，满足 5 分钟间隔时低优先级入同一调度器，队列忙则跳过。 |
| I7 旧路由 money allowlist | 部分成立 | “实测允许值”缺证据，且把开放 numeric 合同收紧为 400 会破坏兼容。新专用端点固定 `money=0`；旧端点保持当前 numeric 透传合同，不新增 allowlist 拒绝。 |

其余 Minor 均按合同缺口处理：写死各 mode 的 `Total` 规则、定义空结果 key、补盘前/节假日策略、处理 `currentTotal < T0`、使用 `min(20,cachedRows)`、明确 L1 字节估算只在写入时执行一次、补同批部署顺序、简化 canonical latest key、同步旧双源文档并显式升级 THS key 到 v2。

## 2026-07-17 语音增量播报补充

- 用户明确要求：Redis 增量刷新后，THSBigOrder 语音应播报本轮所有新增且符合语音条件的大单，不能继续只取最近两条。
- 当前 `VoiceService.SpeakAsync()` 每次先调用 `SpeakAsyncCancelAll()`；如果调用方对多条新增订单逐条调用，后续播报会取消前一条，因此仅移除“两条限制”仍会丢播报。
- `MainForm.CheckAndAnnounce()` 实际还有两层截断：只看 `_filteredData.Take(10)`，命中第一条 marker 后立即 `return`。用户感知为“只播最近两条”是刷新间隔、单条 return 和取消队列共同造成的结果。
- 不能在 `_filteredData` 上做增量差分，否则修改金额阈值、买卖页签或特殊 marker 筛选会把历史数据误判为新增。应先在完整 `_allData` 上识别新增，再应用当前 `OrderFilter`。
- `BigOrderItem` 没有可靠上游唯一 ID，且 Longhu 已确认允许合法重复成交。推荐使用 `Time/Type/Volume/Amount/Price` 指纹的历史最大出现次数，而不是布尔 `HashSet`；重复数从 2 增到 3 可识别 1 条，短暂删除再恢复不会重播。
- 语音关闭期间也应推进快照基线，否则重新勾选会补播关闭期间历史。首次加载、切股、切源和跨交易日只建基线；旧订单 marker 后续变化不追溯播报。
- 同一刷新批次应合并为一次 `SpeakAsync`，保留点火/砸盘/买活跃/承接好及既有优先级；普通刷新不取消语音，仅切股、切源、关闭语音和退出允许取消旧队列。
- 复核发现 THS 也必须提供权威 `sessionDate`。THS 订单时间可能只有 HH:mm:ss，不能用 `DateTime.Today` 或 proxy 自然日猜测；应由 proxy 从显式交易日、pricechange/分时完整日期或完整 order 日期推导，无法确认则不推进语音/跨日 last-good。
- 仅“关闭期间继续 Observe”不足以保证不补播：关闭期间零刷新或请求跨越重新开启时仍可能漏过基线。重新开启后增加一轮 accepted snapshot barrier。
- 特殊 marker 筛选必须影响播报类型：筛选“买活跃”时，双 marker 订单不能按默认优先级播成“点火”。
- 为验证原始 CancelAll 根因，`VoiceService` 需要可注入 `ISpeechQueue`；纯文本测试不能证明普通 batch 没有取消前序语音。
- THS `sessionDate` 仅进入 scope 仍不够：现有 parser 对 HH:mm:ss 使用 `DateTime.Today`，而订单指纹包含 `Time.Ticks`。必须把 order 时间也规范化到权威交易日，否则跨午夜会把全天历史判为新增。
- re-enable barrier 只能在可信日期完整快照成功建立基线后清除；先收到 `sessionDate=null` 时必须继续保持。

## 2026-07-18 marker 口径研究

- 当前 `CalculateMarkers` 的点火/砸盘触发仅使用单笔金额、前 50 秒全部大单平均金额和 2 倍阈值；买活跃/承接好仅比较事件前后 6 秒的单一 Type 金额，没有价格冲击、订单流失衡、连续性、反向成交吸收或回撤验证。
- 本地 `proxy-server/data/big-order/2026-07-17/` 当前可读样本为 13 只候选股、43,657 条逐笔，单股 39 至 19,044 条不等；金额中位数约 30 至 57 万，固定 300 万在不同股票上对应的尾部分位差异明显。
- 本地样本只有一个交易日且来自候选池，存在交易日、行情环境和选股偏差，不能据此宣称得到稳定的全市场阈值。
- Longhu 行只有秒级时间、Type、成交量、成交额和成交价，没有委托单 ID、成交序号、盘口深度或队列变化；同一秒可有多笔记录。因此只能做时间窗口归因，不能证明某一买单逐笔吃掉了此前十笔卖单。
- `Type=2` 为主动买、`Type=4` 为主动卖；`Type=3` 表示主力被动买、即卖方主动成交时主力在买盘承接。承接应联合卖方压力、被动买金额和价格抗跌/恢复判断，不能只看事件后 `Type=3` 是否超过 100 万。
- Cont、Kukanov、Stoikov《The Price Impact of Order Book Events》（arXiv:1011.6402，期刊 DOI `10.1093/jjfinec/nbt003`）基于 50 只 NYSE 股票指出：短时间价格变化主要由最优买卖价上的订单流失衡驱动，价格变化与 OFI 近似线性，斜率与市场深度成反比；单独成交量关系更噪声、更不稳健。工程含义是 marker 必须同时看方向失衡和价格响应，不能只看单笔金额。
- Bouchaud、Farmer、Lillo 等《How markets slowly digest changes in supply and demand》（arXiv:0809.0822）总结：大额意图通常拆分成多笔执行，使订单流成为持续的长记忆过程。Lillo/Farmer《The long memory of the efficient market》（arXiv:cond-mat/0311053）也实证订单符号具有长记忆。工程含义是连续同向成交和方向纯度应作为点火/砸盘的重要条件。
- Large《Measuring the resiliency of an electronic limit order book》（DOI `10.1016/j.finmar.2006.09.001`）对应的微观结构概念是流动性冲击后的订单簿恢复。当前数据没有盘口深度，只能用卖压后的低价格冲击、被动买吸收和随后价格恢复构造“成交级韧性代理”。
- Easley、López de Prado、O'Hara《Flow Toxicity and Liquidity in a High-Frequency World》（DOI `10.1093/rfs/hhs053`）强调买卖成交量失衡可刻画有毒订单流；本项目不应直接照搬 VPIN，但可借鉴等成交额窗口和方向失衡，而不是只用固定秒数窗口。
- 对本地单日样本的描述性重放显示，当前规则产生约 584 次点火、565 次砸盘；增加 10 秒连续性、70% 主动方向纯度、至少 3bp 同向价格冲击、后 10 秒保留一半冲击和 20 秒冷却后，`3 笔均不低于 500 万且合计不低于 1500 万`只剩 12/7 次，`3 笔均不低于 300 万且合计不低于 1000 万`为 26/22 次。该结果只证明旧规则过宽，不代表新阈值已被收益或人工标签验证。
- 2026-07-18 继续执行前复核时，归档目录已从先前 13 只扩为 17 只；首轮重放还发现至少一条不是预期 6 列结构的记录。后续统计必须显式报告并跳过结构、时间、价格或金额非法行，不能静默把坏行当作零值参与阈值标定。
- 扩展重放最终统计为 17 只、95,274 条原始记录、95,150 条有效记录和 124 条无效占位；无效行主要是 `["", "1970-01-01 08:00:00"]`。旧规则触发 1,153/1,156 次点火/砸盘；固定 500 万高置信规则触发 25/12 次。新增股票和样本量约翻倍解释了相对首轮 13 只统计的增长。
- 用户继续补充后，7/17 归档扩大为 28 只、169,870 条原始、169,623 条有效和 247 条无效占位；旧规则为 1,869/2,025，高置信固定 500 万规则为 31/25。该日大盘显著下跌，卖侧旧信号更多；它适合压力场景验证，但不能据此放宽卖侧阈值或证明常态行情效果。
- 用实际 Release 编译产物的 `CalculateMarkers` 重放 28 只归档，最终得到 24 次点火、23 次砸盘、5 次买活跃、0 次承接好。与早期 Node 31/25 的差异来自生产实现的按秒 VWAP、自适应 P90和完整确认窗口，不把描述脚本数字当最终合同。
- 23 个砸盘事件多数满足卖压笔数/金额，且多例具有 `Type=3` 吸收或 500 万以上主动买反击；`承接好=0` 的最终限制来自价格恢复。最高恢复率约 47.7%，没有事件达到批准的 50%，因此不为制造信号把阈值降到 45%。
- detector 预筛优化前全样本算法耗时约 3.2 秒、单股最慢 684ms；把 500 万绝对门槛前移后，输出不变。最终 Release 重放 28 只 detector 合计 997ms、单股最慢 363ms；PowerShell 解压、JSON 和对象构造不计入该 detector 计时。
- 自审发现 `+8秒` 即确认会让尚未关闭的窗口后续升级 marker 并可能重复播报；最终合同要求数据最新成交时间越过候选 `+10秒` 后才冻结结果，仍使用 `+8~10秒` 内最后有效成交确认价格。
- 带“后续 8 至 10 秒价格保留”的 marker 是延迟确认事件：展示行可能早已进入快照，后续才获得 marker。现有只识别新增订单指纹且禁止旧行 marker 变化重播的跟踪合同会漏播，实施时必须改为已确认 marker 指纹并保证状态迁移只播一次。

## 2026-07-18 历史日期 API 探测

- 当前项目公开代理合同只接受 `stockCode`：THS `/api/big-order/ths-detail` 和 Longhu `/api/big-order/longhu/all-day` 都没有交易日参数。
- 以 `600584`、目标日 `2026-07-16` 做只读上游对照：Longhu 基线返回 20 行、`Total=19044`、行日期 `2026-07-17`；增加 `Date=2026-07-16` 或 `TradeDate=20260716` 后仍返回相同 `Total` 和 `2026-07-17`，说明参数被静默忽略。
- THS 直连基线曾超时；`date=2026-07-16` 的成功响应包含 3,673 行，但权威行日期仍是 `2026-07-17`，说明该参数也被忽略。`date=20260716` 再次超时，不能作为支持历史查询的证据。
- `bigOrderArchive.load()` 只会扫描本地日期目录并返回该股票最近一份已归档快照；它能恢复已采集历史，但不能向上游补抓尚未归档的日期。
- 因此当前不能增加一个会把指定日期误映射到最近交易日的主界面筛选。未来有多个本地归档交易日后，可以另做“本地归档回放”入口，并强制返回请求日期与 `sessionDate` 完全一致；这不能解决追溯补齐过去 20 日数据的问题。
- 对 2026-07-17 归档与本地 THS 明细做逐笔键匹配（股票、时间、金额、价格）：前 8 只股票共匹配 6,812 笔，其中 6,763 笔（99.3%）的 Longhu Type 与 THS `nature` 映射一致；冲突主要来自同秒同金额同价重复成交，键不唯一或两源排序差异。扩大样本前暂把映射视为“高置信工程假设”，不写成上游官方合同。
