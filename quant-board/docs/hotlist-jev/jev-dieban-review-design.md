# 跌停复盘页（JEV 叙事工作台）设计与口径

> 2026-10-20 用户需求：jev 叙事工作台增加【跌停复盘】页，内容包括跌停/回撤等每日负反馈股票，
> 样式与风格参照【涨停复盘】页。
> 结论先行：**页面 = 全市场逐股跌停名单 ∪ 采集池负反馈名单（跌停 / 连跌 / 一字跌停 / 大跌 /
> 触板回撤）+ 全市场跌停家数对账**；全市场逐股已于 2026-10-20 立项落库
> （`market_daily_limit_down_stocks`，133/133 交易日零缺口），缺文档日/家数存疑仍如实标注，
> 不伪造（AGENTS §4.0）。

## 1. 页面结构（与涨停复盘同源）

`quant-board/backend/relay_page/index.html` → 侧栏「工作台 › 跌停复盘」（`tab-dieban`）：

| 区块 | 内容 |
| --- | --- |
| 页头 | `h2` 跌停复盘 + 口径说明（与涨停复盘/热榜行情同款 `.page-head` + `.ph-line`） |
| banner | 盘中口径 / 降级原因 / 无数据原因（琥珀条，不做阻断） |
| KPI 条（8 卡，可点筛选） | 跌停家数（含全市场 N 家 + 源 + 同源分位）、连跌≥2（最长 K 天 + 股名）、一字跌停、大跌≤-7%（含跌停/非跌停）、下跌家数（池内涨跌比）、触板回撤（逐股数 + 均值/最深）、跌幅最深、主力净流出（合计 + 最大流出股） |
| 板块 chips | 负反馈股板块分布 Top8，点击筛选 |
| 筛选条 | 范围（负反馈全部/跌停/连跌≥2/一字跌停/大跌/触板回撤/下跌/全部个股）+ 代码名称搜索 + 板块 + 连跌天数 + 回撤幅度 + 清除 + 计数 |
| 表（可排序、行展开） | 代码/名称/板块/类型徽标/跌幅/连跌/近3日/回撤/换手/量比/主力净额/来源 |
| 行展开卡 | 左「口径与读数」（派生字段，`null`=不可算不补 0）+ 右「读口行 JSON」+ 口径 foot（跌停判定/回撤口径/全市场逐股来源链） |

样式全部复用既有类：`.kpi-strip`、`.kpi.click/.on`、`.chip`、`.lf-bar`、`.lg-row/.lg-detail`、
`.lg-card/.lg-panel/.lg-tree`。未新增主题色或表样式。

## 2. 数据口径（单一事实源 = `backend/services/jev/jev_dieban_review.py`）

| 字段 | 来源 | 口径要点 |
| --- | --- | --- |
| 个股明细（三源并集） | 全市场逐股 `market_daily_limit_down_stocks`（EM > 快照 > 本地日线，一天一文档）∪ 采集池 `snapshot_stock_rows` 当日 `half_hour` 快照（15:00 优先，盘中回落最新槽）∪ 同花顺回撤池逐股 | 采集池 250 只热榜池；同码多快照取 `snapshotId` 最大；逐行 `sources` 标来源（`full_market`/`pool`/`ths_drawdown`），并集判定用于徽标、池口径统计另由 `limitDownPool` 收口 |
| 跌停 | `core/limit_rules.is_limit_down_pct` | 板块阈值（主板 9.8 / 创业·科创 19.8 / 北交所 29.8 判定线），含 0.2pp tick 容差，**无 ST 特判**；与 `dieban_count` / 规则情绪链同一条线 |
| 一字跌停 | 快照 `high` / `price` / `limitDownPrice` | 全天最高价=跌停价（开盘即封、无逃逸）；采集池行缺 hi/limitDownPrice → `false`；全市场逐股行无盘中高低价 → `null`（不可判，**不写 false** 免把未知呈现成「确认不是一字」） |
| 大跌 | 快照 `pctChange` ≤ `DEEP_DROP_PCT=-7` | 叙事口径，与跌停分列（副行给「含跌停 / 非跌停」） |
| 连跌 | 逐日回溯同槽（15:00）跌停集合「该日全市场逐股 ∪ 采集池」（`STREAK_LOOKBACK=10`，含当日） | 不可回溯 → 该股 `streak=null`；历史一律取收盘槽，不与盘中槽混比；槽缺失会截断连跌 → `degraded:streak_lookback` + `stats.streakDays.slotDays/priorDays` 披露覆盖 |
| 近3日跌幅 | 当前价 / 3 个交易日前 15:00 价 − 1 | 基准缺失（池外新进/历史不足）→ `ret3d=null` + `degraded:ret3d` |
| 触板回撤 | `limitSummary.thsPools.pools.drawdown.items[].max_drawdown` | 同花顺大幅回撤池（当日曾触板后自高点深回撤）；负号统一换正幅值；池未采集 → `degraded`，不伪 0 |
| 日内回撤 | 快照 `(high − price)/high` | 与触板回撤语义不同，列内用浅色 + tooltip 区分 |
| 全市场跌停家数 | `operations/market_dieban_pool.limit_down_count` | 东财跌停池（近 30 自然日窗口）→ 行情快照（仅当日）→ 本地通达信日线（离线回填）→ 采集池末位降级；`source` 透传，降级时 `fullMarketScope=false` + `degraded` |
| 全市场逐股 | `market_dieban_pool.rows_for_date`（`market_daily_limit_down_stocks`） | EM 载荷解析（p 为 ×1000 定点、lbt 为 HHMMSS）或本地日线两道闸重算；源优先级 EM > 快照 > TDX；`emStreakDays` 为 EM 自报字段透传（页面连跌口径仍统一用逐日回溯）；`count`/`rowsReturned`（=len(rows)+badRows）/`truncated` 三读数并列，读口 `rowsCount`=实际行数、`rowsDocCount`=自报家数 |
| 同源分位 | `reference_counts(同源, 近 20 日)` + `percentile_fraction` | 同源样本 <10 → `percentile=null`（「分位不可算」）；**家数存疑日剔出窗**（`historyExcluded` 列明，见下节） |
| 主力净额 | 快照 `zlje` / 回撤池 `main_net_amount` | 负=净流出；缺字段 → `null`（不补 0） |

**全市场逐股明细（2026-10-20 立项后已落库，预登记 `jev-dieban-fullmarket-preregistration.md`）**：
新集合 `market_daily_limit_down_stocks`（一天一文档，source 优先级 EM > 行情快照 > 本地日线；
EM 窗口内逐日 `count == len(rows)`，窗口外由本地日线重算补齐，133/133 交易日零缺口）。读口把
逐股行并入 `stocks`（来源标 `full_market`，附 EM 封板信息 `emStreakDays/openNum/lastSealTime`）；
缺文档日 → `fullMarket.rowsMissing='no_rows_doc'` + `degraded`，页面横幅标注「名单仅采集池口径」。
**家数与逐股允许跨源**（EM 窗口滑出日：家数 EM 权威、逐股 TDX 重算，两源自洽、来源各自标注，
截断日 `rowsTruncated=true`、坏行日 `count > len(rows)` 由 `rowsBad` 披露）；**跨源且逐股多于家数**
= 家数存疑（典型 EM 空池被记 0 家，如 09-16：家数 0 vs 逐股 4）→ `fullMarket.countDisputed` +
`degraded:full_market_count_disputed`，且该日**剔出同源分位窗**（`historyExcluded` 列明）。
连跌回溯吃「全市场逐股 ∪ 采集池」并集，覆盖见 `stats.streakDays`。
**EM 空池二义性闸**：窗口内空池必须 EM 显式自报 `tc==0` 才认合法 0，否则判不可用（不伪 0）。
回撤池（THS）与采集池明细仍作补充来源（换手/量比/主力净额/日内回撤逐股更全），逐行标来源。

## 3. fail-visible 规则

1. 四源（快照行 / 回撤池逐股 / 全市场逐股 / 全市场家数）**全无** → `noData=true + reason`，页面横幅显式说明。
2. 「0 家跌停」是真读数：`noData=false`、名单为空、KPI 显示 0（不当作缺口）。
3. 回撤池未采集/上游失败 → `drawdown.itemCount=null` + `degraded:{scope:ths_drawdown_pool}`。
4. 全市场源降级到采集池 → `negative`/KPI 标「采集池口径」并进 `degraded`。
5. 读口不可用（HTTP 失败/ok=false）→ banner 「跌停复盘读口不可用：原因」，且空表文案与
   「当日无任何可用原始记录」分开（读失败不得被读成当天无负反馈）。
6. 盘中读取 → banner「盘中口径 · HH:MM（收盘后为 15:00 收盘口径）」。
7. 列表接口异常不得让整页静默：`loadAll` 的 `dieban-review` 请求自带 `catch → {ok:false, reason}`。
8. 页面 60s 轮询不放大外呼/读库：全市场跌停家数、逐股文档、逐日 15:00 采集池行各带 **120s
   进程内缓存**（键 `(dataset, date[, slot])`；含「不可算」负缓存，用哨兵区分未命中与缓存的 None），
   `limit_down_count` 的当日懒加载只在缓存过期后才可能再试；缓存只影响读，不写库、不改参考集合。
9. **读为主但非纯读**：当日收盘后首次读可能触发一次东财跌停池懒加载并 upsert 家数/逐股文档
   （1 次/日；15:05 截点 + 30 日窗口 + 429/403 冷却约束），运维/审计不得当作零副作用 GET。
10. 家数存疑日（`countDisputed`）与回溯槽缺失（`streak_lookback`）均结构化披露并在页面横幅标注。

## 4. 验证

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/hotlist/test_jev_dieban_review.py -q          # 读口 20 例
.\.venv\Scripts\python.exe -m pytest tests/hotlist/test_relay_page_window.py -q          # 页面守卫含跌停复盘 5 例
# 语法：抽取 <script> 后 node --check（同 relay_page 其他改动流程）
```

页面读口实测（2026-10-19，`dragon_board_quant`）：

- 池内跌停 14 / 全市场 22（东财跌停池，逐股 22 行同源同数）、同源分位 ≈86（极高，14 日同源窗：
  3 个家数存疑日已剔出，`historyExcluded=[2026-09-16/17/18]`）；
  8 只池外股并入（新乡化纤 000949 等），负反馈名单 28→39；
- 连跌≥2 共 5 只（跨源并集回溯；最长 3 天：东百集团）；回撤池逐股 6 只（均值 13.99%、最深 23.43%）；
- 近3日跌幅与主力净额逐股命中，池外回撤股（先锋电子等）按回撤口径单列。

## 5. 已完成 / 后续（残余风险）

**已完成**（2026-10-20）：全市场**逐股**跌停名单落库（东财跌停池逐股 + 本地日线重算回填，
`market_daily_limit_down_stocks`，133/133 交易日零缺口），读口并入名单、页面标注来源与缺口。
见预登记 `jev-dieban-fullmarket-preregistration.md` §9。

**后续（未做）**：
1. 全市场**逐股回撤**名单：现仅 THS 回撤池逐股（池覆盖有限），无逐股落库。
2. EM 上游真实载荷形态归档（`p`/`tc`/`lbt` 语义目前只有当日实测样本，无 raw 响应归档到
   `data/backups/`）——需一次预登记外呼后归档供离线核对。
3. `limit_down_count` 在**其他消费方**（`jev_label_jiuyan` 两处）无 120s 缓存，60s 轮询 +
   当日家数缺失 + EM 失败时仍可能每分钟重试一次外呼（本轮新读口已缓存，此为既有路径）。
