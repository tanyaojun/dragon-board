# 前端完整快照采集能力 FastAPI 迁移设计

日期：2026-07-29
状态：已按用户确认升级为完整快照迁移，待书面复核与 subagent 评审

## 1. 背景

`dragonboard_live` 最近完整交易日快照表明：`volume`、`turnover` 已落库，
但 `zlje`、`zljzb`、`volumeRatio`、`pe`、`pb`、`cirMV`、`totalMV`
在 `snapshot_stock_rows` 中整列缺失。MongoDB repository 不裁剪动态字段，丢失发生在
collector 的来源采集与 builder 合并之前。

Dragon Board 正式快照原由浏览器定时生产，除行情列表外还包含市场宽度、情绪、顶层资金、指数、
涨停汇总、昨日涨停表现、题材和轮动派生结果。backend collector 上线后只接管了局部 provider/builder，
原浏览器快照生产链不再能保证正式入库，造成的缺口不只是七个个股字段。本设计因此升级为：
由 QuantBoard FastAPI 采集全部原始事实，由 Python 派生层按现有 TypeScript golden 生成五种快照，
backend collector 成为正式快照唯一生产者。

## 2. 目标与非目标

### 目标

- FastAPI 统一编排八平台热榜、腾讯/Sina 行情、startup cache、THS 主力监控、python-bridge 报价/深度、
  涨停池、指数、市场宽度、题材和板块等全部正式快照原始输入。
- 建立 `MarketFactBundle -> SnapshotDerivationService -> SnapshotBundle` 两层合同，不把原始事实与派生结论混为一层。
- 迁移 `five_minute/quarter_hour/half_hour/hourly/daily` 五种快照生产能力；`half_hour` 继续是 RankTrend 默认口径。
- Dragon Board 前端与 backend collector 消费同一份行情事实合同；前端只读取和展示正式快照，不再定时生产或重放正式入库。
- 修复七个缺失字段进入 `snapshot_stock_rows` 的链路，并保留字段级来源和缺失原因。
- 完整保留现有 `record/frame/stockRows/sectorRows` 事实，包括市场统计、情绪、顶层资金、指数、
  涨停汇总、昨日涨停、题材、轮动与分析字段。
- 完善 collector run、frame 和公开诊断 API 的字段覆盖率日志。
- 对 collector 上线以来的正式快照执行有证据的历史字段恢复。
- 删除 proxy-server 中已经迁移的行情列表 API，不保留双链或兼容路由。

### 非目标

- 不借迁移重新设计 RankTrend、情绪、涨停汇总、轮动、生命周期、风险轨或共振算法口径；Python 以当前 TypeScript 为 golden。
- 不把 python-bridge 的五档 L1 描述为官方 L2，也不伪造 bridge 资金流能力。
- 不恢复东财/Sina 资金流或 `estimated_l1` 正式资金流。
- 不要求历史缺失字段达到 100% 恢复；没有时点证据的字段必须保持缺失。
- 不迁移或重构与正式快照无关的异动、通知、本地语音等功能。涨停池属于快照原始输入，必须纳入 FastAPI adapter，
  但只有新 adapter 验收通过后才能删除旧 proxy 消费路径。

## 3. 架构

在 `quant-board/backend/market_data/` 建立原始事实模块，在 `quant-board/backend/snapshot_derivation/` 建立无 I/O 的快照派生层：

```text
八榜 / 腾讯 / Sina / THS / bridge / 涨停池 / 指数 / 市场宽度 / 题材
                                 |
                                 v
                         MarketFactService
                                 |
                         MarketFactBundle
                                 |
                                 v
                    SnapshotDerivationService
             情绪 / 市场统计 / 涨停汇总 / 轮动 / 资金
                                 |
                         SnapshotBundle
                                 |
                                 v
                    SnapshotCollectorService
                                 |
           record + frame + stockRows + sectorRows -> MongoDB

`GET /api/market-data/table` 只是 `MarketFactBundle` 的行情列表读模型，不再代表整个迁移边界。
```

适配器只负责请求、解析、单位归一化和 `SourceHealth`；`MarketFactService` 负责代码集合、逐字段来源优先级、
缺失语义和聚合质量信息。`SnapshotDerivationService` 不请求网络、不读数据库，只按快照类型与算法版本将
`MarketFactBundle` 投影为完整 `SnapshotBundle`。HTTP route 只序列化读模型，collector 直接调用同一 Python service，
不通过 HTTP 调本机。

FastAPI 自己维护聚合 startup cache。前端不再上传已经合并的 bundle，也不再消费独立
startup-cache API。缓存 fresh TTL 保持 300 秒，stale 窗口保持 1800 秒；缓存是显式
`stale` 的启动基线，不是当前行情事实源。

`GET /api/market-data/table` 的缓存行为固定为：无显式 `codes` 时，fresh cache 直接返回，stale cache
立即返回显式 stale 数据并触发一次进程内 single-flight 后台刷新；没有缓存时同步采集。有显式
`codes` 时必须先检查缓存覆盖，只有每个请求 code 都存在且其必需字段可按原状态返回时才能命中；
否则本请求同步补采缺码，并将补采结果与缓存行合并后返回，不得因 fresh/stale cache 提前返回而漏股票。collector 不走
HTTP 缓存捷径，始终同步刷新各来源，但可把同交易日 cache 当作 stale 基线。这样前端首屏与
collector 仍使用同一合同，同时不会让 collector 把缓存静默当成目标槽位实时事实。

异步资源按执行上下文隔离：FastAPI lifespan 创建并关闭只属于应用事件循环的
`MarketDataRuntime`、`AsyncClient` 和 single-flight task map；同步 collector 通过
`collect_market_table_sync()` 在 worker thread 内创建一次性事件循环和本轮依赖，完成后关闭，
不得跨线程或跨事件循环复用 async singleton。引入 lifespan 时必须把 `main.py` 现有 startup/shutdown
中的 collector、stock-name、theme mapping、theme fund 和旧存储任务全部原样迁入，并保证每个 runner
启动、停止各一次；不得让 lifespan 替换语义禁用现有后台任务。

`tradingDate` 同时决定采集模式。仅上海时区当前交易日允许 live adapters；历史日期只能读取
目标日期 archive/cache。`GET /api/market-data/table` 对历史日期无证据时返回空 rows 和结构化
原因，不得回退当前行情。现有 `/api/snapshot-collector/backfill-slots` 只允许当前交易日；旧日
恢复必须走有证据 repair/import 链。

ThemeHeat 不再调用待删除的 proxy quotes。它与 `MarketFactService` 共享低层
`TencentQuoteAdapter`，但保持自己的全市场 code universe、计算和缓存职责；不得把八榜股票池
误当全市场。涨停字段由 FastAPI 内部的 limit-up adapter 继续消费 proxy-server 未删除的独立
market API，并合入统一 rows。`snapshot_collector_proxy_base_url` 在该辅助来源迁移前保留，不能因
删除 quotes 路由而提前删除。

## 4. 统一字段合同

FastAPI 使用扁平 `camelCase`，与 MongoDB 快照合同保持一致：

```json
{
  "capturedAt": 1785256200000,
  "rows": [],
  "sourceHealth": [],
  "qualityIssues": []
}
```

每个 `MarketStockFactRow` 包含可采集或可直接聚合的事实：

- 标识与题材：`code`、`name`、`themes`、`sectorLabel`、`mainTheme`
- 行情：`price`、`change`、`pctChange`、`speed`、`amount`
- 平台排名：`emRank`、`thsRank`、`kplRank`、`tdxRank`、`xqRank`、`clsRank`、
  `tgbRank`、`dzhRank`
- 排名聚合：`platforms`、`rank`、`avgRank`、`avgRankNum`、`compRank`、`compScore`、`fundPenetration`
- 资金与热度：`zlje`、`zljzb`、`moneyFlow`、`volume`、`volumeRatio`、`turnover`、`turnoverRate`、`heat`、`hotness`
- 大单与人气：`cddje`、`cddjzb`、`bigMoney300`、`institutionBuy`、`popularity`、`popularityChange`
- 估值市值：`pe`、`pb`、`cirMV`、`totalMV`、`totalMarketValue`
- 现有快照兼容行情：`open`、`high`、`low`、`preClose`、`amplitude`
- 盘口深度：`bid1Price`、`bid1Volume`、`ask1Price`、`ask1Volume`、`depth10`、`spread`、`bid10Total`、
  `ask10Total`、`depthImbalance`、`tickBuyVolume`、`tickSellVolume`、`tickBuyCount`、`tickSellCount`、
  `lastTradePrice`、`lastTradeVolume`
- 涨停事实：`limitUpPool`、`reason`、`firstZtTime`、`lastZtTime`、`boardHeight`、
  `highDays`、`fengdan`、`maxFengdan`、`maxDrawdown`
- 资金溯源：`moneyFlowSource`、`moneyFlowEstimated`、`capitalFlowSource`、
  `capitalFlowConfidence`
- 溯源：`fieldMeta`

派生后的 `SnapshotStockRow` 在上述事实基础上保留当前 TypeScript 合同全部字段：

- 领涨/题材：`leadStatus/leadTimes/lianbanStr/themeContribution/themeRole/themeExposureWeight/themeRiskFlags/isNew/themeHeat/themeLevel`。
- RankTrend 与信号：`rankChange/directionSignal/directionConfidence/accelerationSignal/accelerationConfidence/crossSignal/crossConfidence/finalSignal/finalConfidence/jumpDirection/jumpConfidence/macdCross/resonanceIntensity`。
- 现有兼容别名：`money_flow_source/money_flow_estimated/capital_flow_source/capital_flow_confidence`；别名与 camelCase 必须值一致，在下游完成合同升级前不得擅自删除。

顶层 `MarketFactBundle` 另含 `marketBreadth/limitFacts/indices/themes/sectors/sourceHealth/qualityIssues`。
迁移基线不能只看当前 TypeScript interface，因为旧 builder 还可能动态产生未声明字段。实现前先生成
`SnapshotFactInventory`，取以下三者并集：`src/services/snapshot/types.ts` 合同、五种 TypeScript builder
对固定 fixture 的真实输出 key、MongoDB 现存有效文档 key。每个 key 必须分类为保留、有证据改名或明确废弃；
默认是保留。迁移前后对 `SnapshotStockRow` 和 `SnapshotSectorRow` 并集全字段做等价回归测试，
不以本文分类清单代替可执行契约。

`rank`/`compScore`/`fundPenetration` 保留现有排名事实；`pctChange`/`amount`、题材标签、热度和市值别名保留
现有快照合同。`resonanceIntensity`、`rankTrendStrength`、`lifecycleOpportunity` 属于派生结果，
不进入 `MarketStockFactRow`；其中现有 `SnapshotStockRow` 已声明的字段必须由后端派生并入库，
未属于正式快照合同的分析字段仍留在下游分析读模型。`pe/pb` 当前不一定显示在行情表，
但仍属于快照采集合同。

### 4.1 单位

| 字段 | 统一单位 |
| --- | --- |
| `volume` | 股；腾讯原始 `parts[6]` 为手，乘 100；Sina 股数保持不变 |
| `turnover` | 元；腾讯优先取 `parts[35]` 第三段原始成交额 |
| `zlje`、`cirMV`、`totalMV` | 人民币元 |
| `change`、`speed`、`turnoverRate`、`zljzb` | 百分数值，`2.35` 表示 `2.35%` |
| `volumeRatio`、`pe`、`pb` | 无量纲倍数 |
| 八平台排名 | 正整数 |

腾讯原始 `parts[44]/parts[45]` 为亿元，FastAPI 只乘一次 `100000000` 得到
`cirMV/totalMV`。不得先构造已换算 `f20/f21` 再二次换算。适配器测试必须以原始
`qt.gtimg.cn` 行 fixture 为输入，不以当前 proxy 的中间 `f*` 对象猜单位。

### 4.2 缺失与零值

合同字段始终存在，允许值为 `null`。来源明确返回的 `0` 是真实零值；缺失、非法或过期
不得转换为 `0`。`fieldMeta` 固定为 `Record<fieldName, FieldMeta>`，每个合同字段的 metadata 至少记录：

```json
{
  "status": "fresh",
  "source": "tencent",
  "observedAt": 1785256200000,
  "reason": null
}
```

`status` 为 `fresh`、`stale`、`missing` 或 `invalid`。历史恢复时，`fresh` 表示证据相对目标
快照时点有效，不表示相对当前墙钟时间新鲜；同时增加 `backfillMethod`、`evidenceRef` 和
`restoredAt`。

`QualityIssue` 结构固定为 `code/source/field/location/affectedScope/detail`；`detail` 必须为可
序列化审计信息，不得把不同来源错误塞成无结构字符串。

### 4.3 完整快照合同

`MarketFactBundle` 必须保留本轮所有可证明输入，不因某个派生算法不可计算而删除原始事实：

- `stocks`：八榜排名、个股行情、估值、市值、资金、盘口、涨停和题材事实。
- `marketBreadth`：上涨、下跌、平盘、涨停、跌停家数与全市场成交额。
- `limitFacts`：涨停池明细、连板高度、开板/回封、炸板、封板率、昨日涨停股表现。
- `indices`：上证、沪深 300、中证 500、中证 1000、大盘股和微盘股表现。
- `themes/sectors`：题材、板块、成分关系、热度因子与流入事实。
- `sourceHealth/fieldMeta/qualityIssues`：来源时点、覆盖率、新鲜度、缺失位置和结构化原因。

`SnapshotBundle` 严格对应现有 MongoDB 四类事实：

- `record.payload`：当前快照类型应保留的 hotlist、sectors、marketStats、sentiment、moneyFlow、
  indices、limitSummary、rotationSummary 及算法 metadata。
- `frame`：`marketStats/sentiment/moneyFlow/indices/limitSummary/rotationSummary`，以及
  `metadata.collector` 和 `metadata.derivation`。
- `stockRows`：现有 `SnapshotStockRow` 全部事实字段与本次七个缺失字段，不允许 Pydantic 静默丢弃 extra。
- `sectorRows`：`sector/hot_theme/rotation_main_line` 三类实体及现有全部因子字段。

五种快照的语义不得拉平：

| 类型 | 正式输出 |
| --- | --- |
| `five_minute` | 轻量 record；不生成正式 frame/stockRows/sectorRows |
| `quarter_hour` | 日内行情、情绪、市场统计、资金、涨停汇总和行投影 |
| `half_hour` | 与 quarter-hour 同域，但保持 RankTrend 默认槽位和样本口径 |
| `hourly` | 日内事实 + 阶段连板/炸板 + 轮动摘要 |
| `daily` | 收盘全量：情绪历史/因子、指数、昨日涨停、完整资金、涨停和轮动结果 |

`metadata.derivation` 固定保留 `algorithmVersion/configHash/inputEvidence/derivedAt/qualityIssues`。
某个派生域输入不足时，该域为 `null` 并记录不可计算原因；不得使用 `0`、`50`、
`start/启动`、`震荡` 或空对象伪装结果。

## 5. 数据流与来源优先级

1. 读取同交易日 startup cache 作为显式 stale 基线。
2. 八个平台热榜并行采集；成功平台使用实时结果，失败平台可保留该平台同交易日缓存排名。
3. 合并实时、缓存和显式 `codes` 参数得到代码集合；显式代码即使不在八榜也必须查询并返回。
4. 分批请求腾讯行情；只对缺失代码或失败批次请求 Sina。
5. Sina 只补其真实具备的名称、价格、涨跌、成交量和成交额；其它字段保持 `null`。
6. 从资金缓存读取同交易日有效 `zlje`；缺失代码按每批最多 5 只、并发最多 2 调用
   `ThsMainMonitorService.load_batch` 刷新，校验 `sessionDate/sourceTs` 后写回缓存。
7. cache-only 或刷新失败值只能标记 stale/missing；仅当同交易日、同累计窗口的 `zlje`
   与 `turnover` 都有效时计算
   `zljzb = zlje / turnover * 100`，并标记为派生字段。
8. 采集涨停池/连板/炸板/昨日涨停原始事实、指数、市场宽度、题材、板块和成分关系。
9. 合并全部事实与逐字段溯源为 `MarketFactBundle`；行情读模型可更新 FastAPI startup cache，
   但快照 collector 不把读模型 cache 静默当成当前槽位事实。
10. `SnapshotDerivationService` 按目标类型生成市场统计、情绪、顶层资金、指数投影、涨停汇总、昨日涨停和轮动。
11. collector 将完整 `SnapshotBundle` 原子写入 record/frame/stockRows/sectorRows，并记录每个事实域和派生域覆盖率。

`avgRank/avgRankNum/compRank` 严格移植 `ComprehensiveRankEngine.ts` 的平台权重、缺榜惩罚、
资金穿透、归一化和排序规则；八平台解析严格对齐 `src/services/adapters.ts`。TS/Python 读取同一
共享 golden，任何排序或分数偏差均阻断迁移，不改变 RankTrend 输入口径。

情绪、涨停汇总、轮动、frame 和行投影以 `src/services/snapshot/builders.ts`、
`DragonBreathAnalyzer`、当前题材/轮动服务的 TypeScript 输出为 golden。迁移先冻结输入 fixture 和现有输出，
再移植 Python；不允许以“同类算法”代替逐字段等价。唯一例外是现有 `|| 0/50`、默认“启动/震荡”
对缺失的伪装：这些不进 golden，统一改为 `null + qualityIssues`。

逐字段优先级：

```text
排名：实时平台 > 同交易日缓存(stale) > null
行情：腾讯实时 > Sina 实时 > 同交易日缓存(stale) > null
资金：THS Main Monitor > 同交易日缓存(stale) > null
```

源码核对确认：当前 python-bridge snapshot API 不输出正式资金流，collector 也主动丢弃
bridge HTTP money fields；当前 mootdx 运行时不支持逐笔接口。因此本次资金流由 FastAPI 内
现有 THS 正式服务提供。bridge 只承担已验证的报价/深度能力；未来只有在 bridge 提供可验证
的正式资金合同后，才可作为同一资金适配器的候选来源。

这里“THS 可持久化来源”仅表示允许按来源事实持久化 `zlje`，不等于正式 L2 资格。THS 行必须
保持 `moneyFlowSource=capitalFlowSource=ths_main_monitor`、`moneyFlowEstimated=false`，不得
伪装 `official_l2`；现有 backtest `broker_l2/official_l2` 白名单和 formal L2 coverage 口径不变。

## 6. 失败与持久化语义

- 任一来源存在可持久化原始记录时，必须生成并保存已有事实；股票行为空但指数、市场宽度、涨停、sector/theme 等
  原始记录存在时，仍保存 record/frame/sector rows 和结构化原因。
- 八榜部分失败、腾讯部分失败、Sina 字段不足、THS 限流或 bridge 离线都只能形成
  `qualityIssues`，不得阻断已有数据写库。
- 缺失字段以 `null + fieldMeta` 保存；stale 数据保留数值但必须显式标记。
- 质量异常不得让读取 API、回放或 UI 返回整体空结果。
- 情绪、轮动或涨停汇总等任一派生域不可计算时，只将该域设为 `null`；原始事实和其他可计算域继续入库。
- 只有 stocks、quotes、depth、money flow、limit facts、indices、market breadth、themes、sectors 等全部可持久化原始记录
  均为空时，本轮才为 `no_data` 且不写事实集合；错误诊断仍写 run 日志。
- 程序异常或 MongoDB 写入失败为 `failed`，不属于数据质量门禁。

collector builder 不再维护第二套来源合并规则，只消费 `MarketFactBundle` 和
`SnapshotDerivationService`。同一采集时点只生成一份事实 bundle，中命多个槽位时按各自类型独立生成快照，
不重复请求上游。`five_minute` 只写轻量 record；其余四类写完整四集合。MongoDB repository 必须通过
真实 round-trip 证明顶层派生域、行字段和 metadata 未被固定投影裁剪。
各类型槽位必须调用现有共享交易日历/时间表配置，不在 collector 内复制时刻字面量；历史恢复也使用同一槽位解析器。

## 7. 采集日志与公开诊断

复用 `snapshot_collector_runs`，不新增运行日志集合。每次运行记录：

- `runId`、`snapshotId`、slot、开始/结束时间和状态
- 每个来源的请求数、返回数、覆盖率、延迟、fresh/stale 状态、失败批次和错误码
- 每个原始事实域 `stocks/marketBreadth/limitFacts/indices/themes/sectors` 的记录数、时点、覆盖率和证据状态
- 每个派生域 `marketStats/sentiment/moneyFlow/indices/limitSummary/rotationSummary` 的
  `computed/missing/invalid/stale`、算法版本、输入证据和不可计算原因
- 每个合同字段的 `validCount`、`missingCount`、`invalidCount`、`staleCount`、
  `trueZeroCount`、`coverageRatio` 和 `sourceCounts`
- 聚合后的结构化 `qualityIssues`
- `persistence`：是否尝试写入、是否成功/幂等、各集合实际写入数量和 MongoDB 错误类型

运行状态为：

- `completed`：有数据并已保存，允许有质量问题
- `deduped`：已有快照，记录 `collectionSkippedReason=existing_snapshot`
- `dry_run`：已采集和统计，但未写事实集合
- `no_data`：所有来源均无可持久化原始记录，事实集合不写但 run 诊断保留
- `failed`：程序或持久化异常

不再用 `blocked` 表示字段缺失或覆盖率不足。

`no_data` 在 scheduler/API/backfill 汇总中是已观察但无事实可写的非异常结果，不增加 scheduler
`error_count`；`failed` 才表示程序或持久化错误。

frame 通过现有 Mongo 固定投影可保留的 `metadata.collector` 保存 `collectorRunId`、
`fieldCoverage`、`sourceHealth` 和 `qualityIssues`；逐行具体原因保存在
`snapshot_stock_rows.fieldMeta`。`metadata.derivation` 保存派生算法和输入证据；不得将不可计算原因只留在进程日志。
应用日志输出带 `runId` 的单行结构化 JSON，
确保 MongoDB 异常时仍有进程级证据。

公开诊断接口：

- `GET /api/snapshot-collector/runs`：分页运行摘要
- `GET /api/snapshot-collector/runs/{runId}`：完整来源、字段覆盖率和写入结果
- `POST /api/snapshot-collector/audit`：按日期、快照、字段和来源汇总
- `GET /api/market-data/table`：返回本次聚合的 `sourceHealth` 与 `qualityIssues`
- 现有 snapshot frames/records/stock-rows/sector-rows 读口必须返回已存事实和派生诊断，不以任一域质量不足整体置空。

## 8. 历史字段恢复

现有 `/api/snapshot-collector/backfill-slots` 会重新请求当前上游，必须拒绝非当前交易日，禁止
用于旧字段恢复；`run_once` 和 market-data service 也必须在入口防止历史日期调用 live adapters。
新增独立、幂等的历史修复 service/CLI，范围从首个 `dragonboard_live` 正式 collector run
到 FastAPI 完整快照合同切换前的最后一帧。修复对象不只是七个行字段；对市场宽度、指数、涨停事实、
题材和可重算派生域同样执行证据 inventory。只有目标日期/时点输入齐全时才重算对应派生域；
缺少时保持 `null/unrecoverable`，不用当前结果或邻近槽位补齐。

证据等级：

1. `exact_archive`：对应交易日、股票和时点的原始响应。
2. `derived_historical`：只使用对应时点历史输入，按固定公式重建。
3. `unrecoverable`：没有合法证据，保持 `null` 并记录原因。

当前本地目录共有 720 个文件项，其中 719 个非空 gzip，另有 1 个零字节临时文件；有效目录
只覆盖 `2026-07-20`、`2026-07-27`、`2026-07-28`，不是连续逐日、更不是逐槽归档。修复前
必须输出 gzip/schema/checksum、事件时间范围和逐槽可覆盖 inventory。MongoDB 已保存的槽位
`volume/turnover` 可作为派生输入；龙虎/大单文件只有在字段语义验证一致后才能使用。

THS 明细固定规则：只接受有限正数 `money`；`tradetype="1"` 记正流入、`tradetype="2"` 记负
流出；其它值标记 invalid 且不参与金额。事件日期取 archive `sessionDate`，时间优先 `otime`、
回退 `ctime`，目标 slot 采用 `event_time <= slot_time`。只有归档中存在稳定且唯一的源事件 ID 时才以
`sessionDate + code + sourceEventId` 判重，同 ID 后续项标记 duplicate 且不再累计；无源 ID 时不得以时间、金额、
买卖方向组合猜测重复，同秒同额多笔全部累计。缺时间、越界和可证重复记录进入 inventory 异常明细；
收盘累计值必须与 archive title 的 `mainbuy-mainsell` 对账，不一致时标记 invalid 并不得用 title 覆盖明细。

逐字段规则：

- `zlje`：从同交易日 THS 明细按目标槽位截止时间累计；只有收盘总额证据时只修复收盘帧。
- `zljzb`：仅由同槽位有效 `zlje` 和 `turnover` 推导。
- `volumeRatio`：复用现有 Dragon Board 量比公式，使用目标槽位 volume 和历史成交量；
  样本不足或单位不一致时保持缺失。
- `pe/pb/cirMV/totalMV`：只接受带明确历史日期/时点的归档或历史接口；禁止当前值、
  最近值和无日期静态股本。
- 已存在的有限数值不覆盖，只处理缺失或非法字段。

若历史接口需要联网查询，必须显式传入目标交易日期/时点，并保存原始响应或其不可变归档
引用与校验摘要。只返回当前值、无法证明目标日期或响应不可审计的接口不得进入修复来源。

修复先生成只读预检报告，再以条件更新应用；支持中断重跑。每次执行写入 `migration_audit`，
记录修改摘要、证据引用和运行 ID。修复后重算 frame 字段覆盖率，并报告每个日期和字段的
恢复数与不可恢复数。

## 9. proxy-server 收口

FastAPI、前端和 collector 同批切换后，只对已由 FastAPI adapter 接管且全仓零消费者的路由逐文件删除：

- `proxy-server/routes/hotlists.js`
- `proxy-server/routes/quotes.js`
- `proxy-server/routes/startupCache.js`
- 对应测试、server 注册、接口清单、OpenAPI 条目和只服务这些接口的缓存常量

`/api/tdx/hot` 随八榜删除；保留的 `/api/tdx/:entry` 必须显式拒绝保留字 `hot`，避免通配路由
继续代理旧能力，其它 entry 保持不变。前端行情列表直接使用 FastAPI
上下文，不通过 proxy-server 的 QuantBoard 反代。运行时不保留旧路由、双读、双写或
兼容 fallback；回退依赖 Git 回退整个变更，不依赖第二套在线 API。

涨停池是正式快照输入：本次必须新增 FastAPI limit-fact adapter 并将 collector 切换到该 adapter。如其底层仍需调用
proxy-server 的无状态原始来源，该路由暂时保留；只有外部源请求/解析已真正迁入 FastAPI 且通过等价测试后才删除，
不为“proxy 零路由”目标牺牲快照事实。

## 10. TDD 与验收

实现按 RED -> GREEN -> REFACTOR 推进。后端测试至少覆盖：

- 五种快照类型共享 TypeScript/Python golden，逐字段对比 `record/frame/stockRows/sectorRows`；`five_minute` 不伪造 frame。
- `marketStats/sentiment/moneyFlow/indices/limitSummary/rotationSummary` 全部有独立 fixture，某一域缺输入不得清空其它域。
- `SnapshotStockRow` 和 `SnapshotSectorRow` 现有全字段通过合同测试，禁止 Pydantic extra 静默裁剪。
- 市场宽度、指数、涨停明细/连板/炸板/昨日涨停、题材/板块原始事实均有 adapter 合同和部分失败测试。

- 腾讯原始 `parts[]` fixture 的 volume/turnover/市值单位只转换一次，Sina 按代码/批次局部回退。
- 腾讯 `volumeRatio/pe/pb` 覆盖有效、缺失、真实零和 `fieldMeta.source=tencent`。
- Sina 不具备的字段为 `null`。
- 八榜部分失败仍返回并保存已有股票。
- startup cache 数据始终显式 stale。
- fresh/stale cache 缺少显式 `codes` 中任一股时同步补采缺码，不得提前返回漏股。
- THS 分批刷新遵守 5 只/批、并发 2 和 session/window 校验；cache-only 明确 stale。
- 真实零、缺失、非法和 stale 可区分。
- 七字段进入 `snapshot_stock_rows`，run/frame 日志覆盖字段统计。
- stocks/quotes/depth/money-flow/limit-facts/indices/market-breadth/themes/sectors 任一类单独存在仍保存；只有全来源无可持久化记录时为 `no_data`，且 scheduler/API 不报程序错误。
- 历史修复拒绝当前值和无时点证据，不覆盖已有有效值。
- 历史 market-data/backfill 不调用 live adapters；归档 inventory 和 TS/Python 量比 golden 对齐。
- frame `metadata.collector` 经真实 Mongo repository 写入/读取 round-trip 后仍完整。
- 排名/分数/资金穿透、涨跌/成交额别名、热度/题材/市值别名、OHLC、盘口、涨停、资金溯源和 sector facts 在迁移前后逐字段等价，不因删除旧 builder 合并链丢失。
- ThemeHeat 使用共享 Tencent adapter 的全市场模式，`/api/themes/heat` 与 collector sector 链不回归。
- 任意显式代码查询不依赖当日八榜，`window.dataLoader.getQuotes(codes)` 保持等价能力。
- 唯一 lifespan 中新行情 runtime 与现有 collector、stock-name、theme mapping、theme fund、旧存储 runner 均有对称启停测试。
- 同一时点命中多种快照类型时只采集一次 `MarketFactBundle`，但分别生成类型正确的 payload 和幂。
- quarter-hour、half-hour、hourly、daily 的完整 Mongo repository round-trip 保留六个顶层派生域、全行字段和两类 metadata。

前端测试至少覆盖：

- 行情列表只请求 `/api/market-data/table`。
- 不再请求八榜、quotes、startup-cache 或 bridge 行情接口。
- `apiService`、`DragonBreathAnalyzer`、旧 `Adapters`、E2E mocks 和 `window.dataLoader` 公共方法
  均切到或投影自同一 market-data 合同，不留下旁路消费者。
- `null` 显示为缺失符号，不显示成 `0`。
- 排名聚合和现有分析层继续消费统一行合同。
- 正式快照页面只读取 FastAPI/MongoDB bundle；浏览器定时快照生产、正式 backend ingest 和 ingest replay 全部停止。
- 浏览器分析器可保留为展示期临时计算和 golden 标准，但不能再影响正式快照是否入库。

验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest

cd ..\proxy-server
npm test

cd ..
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
pnpm build
python -m unittest discover python-bridge -p "test_*.py"
```

生产验收还必须执行：

- `rg` 确认旧行情列表 API 已无前端、collector 和 proxy-server 引用。
- 启动 FastAPI、proxy-server 和 Dragon Board，使用 Playwright 检查真实字段、缺失显示和
  浏览器控制台。
- 直接执行一个正式 collector 槽位并查询 MongoDB；不设置 shadow 前置阶段。
- 验证七字段、六个顶层派生域、三类 sector entity、全行合同、`fieldMeta`、run detail 和 frame 摘要一致。
- 分别触发 five-minute、quarter-hour、half-hour、hourly、daily 的至少一个正式槽位，核对类型差异而不只核对记录数。
- 运行历史修复预检、应用和修复后审计。
- 第一个完整交易日人工核对所有正式槽位，而不是只看 scheduler `running=true`。

验收不设置覆盖率硬门禁，但腾讯健康时五个行情扩展字段覆盖率必须与腾讯实际返回覆盖率
一致；THS 有返回时 `zlje/zljzb` 有效覆盖率必须大于零并与 THS 返回数一致。所有未覆盖值
必须为 `null` 且原因可通过公开 API 查询。

## 11. 文档同步

实施时同步更新：

- `quant-board/docs/architecture.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/mongodb-migration-plan.md`
- `quant-board/docs/AI_COLLABORATION.md`
- 本专题的实施计划、进度和审计记录

文档必须明确 FastAPI 是全部快照原始事实的唯一编排层、backend collector 是正式快照唯一生产者、
五种类型的差异、前端正式写入入口关闭、proxy-server 已迁移路由的精确删除边界、历史恢复证据边界，
以及 THS `ths_main_monitor` 与 `official_l2` 的能力区别。
