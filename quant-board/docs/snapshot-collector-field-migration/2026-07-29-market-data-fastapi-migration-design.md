# 行情列表 FastAPI 统一编排与快照字段修复设计

日期：2026-07-29
状态：已完成方案确认，待书面复核

## 1. 背景

`dragonboard_live` 最近完整交易日快照表明：`volume`、`turnover` 已落库，
但 `zlje`、`zljzb`、`volumeRatio`、`pe`、`pb`、`cirMV`、`totalMV`
在 `snapshot_stock_rows` 中整列缺失。MongoDB repository 不裁剪动态字段，丢失发生在
collector 的来源采集与 builder 合并之前。

Dragon Board 行情列表当前分别从 proxy-server、startup bundle、前端合并链和实时 bridge
获取数据；backend collector 使用另一套 provider/builder，导致前端可见字段与正式快照字段
长期不一致。本设计将行情列表原始来源统一到 QuantBoard FastAPI。

## 2. 目标与非目标

### 目标

- FastAPI 统一编排八平台热榜、腾讯/Sina 行情、startup cache、THS 正式资金流和已验证的
  python-bridge 报价/深度能力。
- Dragon Board 前端与 backend collector 消费同一个 `MarketStockRow` 合同。
- 修复七个缺失字段进入 `snapshot_stock_rows` 的链路，并保留字段级来源和缺失原因。
- 完善 collector run、frame 和公开诊断 API 的字段覆盖率日志。
- 对 collector 上线以来的正式快照执行有证据的历史字段恢复。
- 删除 proxy-server 中已经迁移的行情列表 API，不保留双链或兼容路由。

### 非目标

- 不改变 RankTrend、生命周期、风险轨或共振算法口径。
- 不把 python-bridge 的五档 L1 描述为官方 L2，也不伪造 bridge 资金流能力。
- 不恢复东财/Sina 资金流或 `estimated_l1` 正式资金流。
- 不要求历史缺失字段达到 100% 恢复；没有时点证据的字段必须保持缺失。
- 不重构 proxy-server 中与行情列表无关的涨停池、异动、通知、本地语音等功能。

## 3. 架构

在 `quant-board/backend/market_data/` 建立边界清晰的行情模块：

```text
八榜 / 腾讯 / Sina / THS / bridge / Redis adapters
                         |
                         v
                  MarketDataService
                         |
                         v
                MarketTableResponse
                  /          |          \
GET /api/market-data/table  collector  startup cache
```

适配器只负责请求、解析、单位归一化和 `SourceHealth`；`MarketDataService` 负责股票池合并、
逐字段来源优先级、缺失语义和聚合质量信息。HTTP route 只序列化结果，collector 直接调用
同一个 Python service，不通过 HTTP 调本机。

FastAPI 自己维护聚合 startup cache。前端不再上传已经合并的 bundle，也不再消费独立
startup-cache API。缓存 fresh TTL 保持 300 秒，stale 窗口保持 1800 秒；缓存是显式
`stale` 的启动基线，不是当前行情事实源。

`GET /api/market-data/table` 的缓存行为固定为：fresh cache 直接返回；stale cache 立即返回
显式 stale 数据并触发一次进程内 single-flight 后台刷新；没有缓存时同步采集。collector 不走
HTTP 缓存捷径，始终同步刷新各来源，但可把同交易日 cache 当作 stale 基线。这样前端首屏与
collector 仍使用同一合同，同时不会让 collector 把缓存静默当成目标槽位实时事实。

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

每个 `MarketStockRow` 包含：

- 标识：`code`、`name`、`themes`
- 行情：`price`、`change`、`speed`
- 平台排名：`emRank`、`thsRank`、`kplRank`、`tdxRank`、`xqRank`、`clsRank`、
  `tgbRank`、`dzhRank`
- 排名聚合：`platforms`、`avgRank`、`avgRankNum`、`compRank`
- 资金行情：`zlje`、`zljzb`、`volume`、`volumeRatio`、`turnover`、`turnoverRate`
- 估值市值：`pe`、`pb`、`cirMV`、`totalMV`
- 溯源：`fieldMeta`

`resonanceIntensity`、`rankTrendStrength`、`lifecycleOpportunity` 属于分析层派生结果，
不进入原始行情合同。`pe/pb` 当前不一定显示在行情表，但仍属于快照采集合同。

### 4.1 单位

| 字段 | 统一单位 |
| --- | --- |
| `volume` | 股；腾讯手数乘 100，Sina 股数保持不变 |
| `turnover`、`zlje`、`cirMV`、`totalMV` | 人民币元 |
| `change`、`speed`、`turnoverRate`、`zljzb` | 百分数值，`2.35` 表示 `2.35%` |
| `volumeRatio`、`pe`、`pb` | 无量纲倍数 |
| 八平台排名 | 正整数 |

腾讯市值字段只在 FastAPI 转换一次，删除当前 proxy-server 与前端重复乘 `10000` 的空间。

### 4.2 缺失与零值

合同字段始终存在，允许值为 `null`。来源明确返回的 `0` 是真实零值；缺失、非法或过期
不得转换为 `0`。`fieldMeta` 至少记录：

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

## 5. 数据流与来源优先级

1. 读取同交易日 startup cache 作为显式 stale 基线。
2. 八个平台热榜并行采集；成功平台使用实时结果，失败平台可保留该平台同交易日缓存排名。
3. 合并实时与缓存股票池，得到代码集合。
4. 分批请求腾讯行情；只对缺失代码或失败批次请求 Sina。
5. Sina 只补其真实具备的名称、价格、涨跌、成交量和成交额；其它字段保持 `null`。
6. 从现有 `ThsMainMonitorService`/资金缓存读取正式 `zlje`。
7. 仅当同交易日、同累计窗口的 `zlje` 与 `turnover` 都有效时计算
   `zljzb = zlje / turnover * 100`，并标记为派生字段。
8. 合并题材、排名和字段级溯源，生成统一响应并更新 FastAPI startup cache。

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

## 6. 失败与持久化语义

- 任一来源存在股票记录时，必须生成并保存已有行。
- 八榜部分失败、腾讯部分失败、Sina 字段不足、THS 限流或 bridge 离线都只能形成
  `qualityIssues`，不得阻断已有数据写库。
- 缺失字段以 `null + fieldMeta` 保存；stale 数据保留数值但必须显式标记。
- 质量异常不得让读取 API、回放或 UI 返回整体空结果。
- 只有八榜实时来源和 startup cache 都为空、无法形成任何股票行时，本轮才为 `no_data`
  且不写快照。
- 程序异常或 MongoDB 写入失败为 `failed`，不属于数据质量门禁。

collector builder 不再维护第二套来源合并规则，只把 `MarketTableResponse.rows` 投影到
snapshot record/frame/stock rows。MongoDB `_stock_doc` 保留动态字段，无需新增裁剪映射。

## 7. 采集日志与公开诊断

复用 `snapshot_collector_runs`，不新增运行日志集合。每次运行记录：

- `runId`、`snapshotId`、slot、开始/结束时间和状态
- 每个来源的请求数、返回数、覆盖率、延迟、fresh/stale 状态、失败批次和错误码
- 每个合同字段的 `validCount`、`missingCount`、`invalidCount`、`staleCount`、
  `trueZeroCount`、`coverageRatio` 和 `sourceCounts`
- 聚合后的结构化 `qualityIssues`
- `persistence`：是否尝试写入、是否成功/幂等、各集合实际写入数量和 MongoDB 错误类型

运行状态为：

- `completed`：有数据并已保存，允许有质量问题
- `deduped`：已有快照，记录 `collectionSkippedReason=existing_snapshot`
- `dry_run`：已采集和统计，但未写事实集合
- `no_data`：所有股票池来源和缓存均为空
- `failed`：程序或持久化异常

不再用 `blocked` 表示字段缺失或覆盖率不足。

frame 同步保存 `collectorRunId`、`fieldCoverage`、`sourceHealth` 和 `qualityIssues`；逐行具体
原因保存在 `snapshot_stock_rows.fieldMeta`。应用日志输出带 `runId` 的单行结构化 JSON，
确保 MongoDB 异常时仍有进程级证据。

公开诊断接口：

- `GET /api/snapshot-collector/runs`：分页运行摘要
- `GET /api/snapshot-collector/runs/{runId}`：完整来源、字段覆盖率和写入结果
- `POST /api/snapshot-collector/audit`：按日期、快照、字段和来源汇总
- `GET /api/market-data/table`：返回本次聚合的 `sourceHealth` 与 `qualityIssues`

## 8. 历史字段恢复

现有 `/api/snapshot-collector/backfill-slots` 会重新请求当前上游，禁止用于旧字段恢复。
新增独立、幂等的历史字段修复 service/CLI，范围从首个 `dragonboard_live` 正式 collector run
到 FastAPI 新合同切换前的最后一帧。

证据等级：

1. `exact_archive`：对应交易日、股票和时点的原始响应。
2. `derived_historical`：只使用对应时点历史输入，按固定公式重建。
3. `unrecoverable`：没有合法证据，保持 `null` 并记录原因。

当前本地证据包括：THS `2026-07-20` 至 `2026-07-28` 共 720 个归档文件，以及 MongoDB
已保存的槽位 `volume/turnover`。龙虎/大单文件只有在字段语义验证一致后才能使用。

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

FastAPI、前端和 collector 同批切换后，逐文件删除：

- `proxy-server/routes/hotlists.js`
- `proxy-server/routes/quotes.js`
- `proxy-server/routes/startupCache.js`
- 对应测试、server 注册、接口清单、OpenAPI 条目和只服务这些接口的缓存常量

`/api/tdx/hot` 随八榜删除，独立 `/api/tdx/:entry` 保留。前端行情列表直接使用 FastAPI
上下文，不通过 proxy-server 的 QuantBoard 反代。运行时不保留旧路由、双读、双写或
兼容 fallback；回退依赖 Git 回退整个变更，不依赖第二套在线 API。

## 10. TDD 与验收

实现按 RED -> GREEN -> REFACTOR 推进。后端测试至少覆盖：

- 腾讯单位只转换一次，Sina 按代码/批次局部回退。
- Sina 不具备的字段为 `null`。
- 八榜部分失败仍返回并保存已有股票。
- startup cache 数据始终显式 stale。
- THS `zlje` 和同槽位 `zljzb` 派生正确。
- 真实零、缺失、非法和 stale 可区分。
- 七字段进入 `snapshot_stock_rows`，run/frame 日志覆盖字段统计。
- 只有全股票池无数据时为 `no_data`。
- 历史修复拒绝当前值和无时点证据，不覆盖已有有效值。

前端测试至少覆盖：

- 行情列表只请求 `/api/market-data/table`。
- 不再请求八榜、quotes、startup-cache 或 bridge 行情接口。
- `null` 显示为缺失符号，不显示成 `0`。
- 排名聚合和现有分析层继续消费统一行合同。

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
- 执行一个正式 collector 槽位并直接查询 MongoDB。
- 验证七字段有效数、缺失数、真实零值数、`fieldMeta`、run detail 和 frame 摘要一致。
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

文档必须明确 FastAPI 是行情列表唯一编排层、proxy-server 已删除对应 API、历史字段恢复的
证据边界，以及 python-bridge 当前不提供正式资金流的能力事实。
