# 预登记：跌停复盘·全市场逐股明细（2026-10-20）

> 用户指令（2026-10-20）：「第2项，请立项执行」——即上一轮交付的遗留项：把**
> 全市场逐股**跌停名单落库，替换「采集池口径 + 全市场家数」的混合展示。
> 依赖 skill：`skills/fail-visible-data-pipelines/SKILL.md`（已读）。

## 1. 目标与不做

**目标**：任一交易日都能给出**全市场逐股跌停名单**（代码/名称/跌幅/价/封板信息/连跌天数），
供【跌停复盘】页直接展示；口径与家数 KPI 同源可对账。**对账式（2026-10-20 评审后精确化）**：
`count`（家数，EM 自报 tc 或池行数）≥ `rowsReturned`（池实际返回条目 = `len(rows) + badRows`）
≥ `len(rows)`（解析成功行）。无坏行且不截断时三者相等；坏行日 `count > len(rows)` 由 `badRows`
披露；截断日 `count > rowsReturned` 且 `truncated=true`（**不可用 `count - len(rows) > 0` 判截断**）。

**不做**：
- 不改 `market_daily_limit_down`（家数参考集合）的既有合同与优先级，只**新增**逐股集合；
- 不重算/不回改 `snapshot_stock_rows`、THS 回撤池等既有口径；
- 不引入第二个「连跌」定义（连跌仍由逐日回溯统一计算，EM 自报 `days` 只作原始字段透传）；
- 不动 jev 模型链、不触发任何模型调用。

## 2. 数据源与优先级（单一事实源）

| 源 | 覆盖 | 角色 | 备注 |
| --- | --- | --- | --- |
| `em_pool` | 近 30 自然日（东财窗口） | **主源**（权威） | `push2ex getTopicDTPool` 逐股载荷：`c/n/p/zdp/hs/amount/ltsz/pe/hybk/days/oc/lbt/fund/fba` |
| `market_quotes_snapshot` | 仅当日（Redis 行情快照） | 当日兜底源 | `full_market_dieban_rows_from_quotes`：`f12/f14/f2/f3/f5/f8/f9/f20/f21`，判定走 `core/limit_rules`；全行畸形 → 不可算（不写 0） |
| `tdx_local_bars` | 本地日线全历史（离线） | 窗口外回填源 | `market_dieban_tdx` 两道闸（跌幅线 + 收盘价 == 精确跌停价）；名称取 `stock_names` |

- 优先级 `em_pool` > `market_quotes_snapshot` > `tdx_local_bars`；**低级源永不覆盖高级源**
  （`SOURCE_RANK` 单一实现，家数参考集合同规）。
- **EM 空池二义性闸**：窗口内空池必须 EM 显式自报 `tc == 0` 才认合法 0（限流/软拦截同样返
  「HTTP 200 + 空池」，据此写 0 即是 §4.0 的零披露伪 0）；否则判不可用、降级到快照/本地日线。
- **逐股与家数解耦**（窗口边界必需）：家数已是 EM 权威的日期，逐股仍可由本地日线补（EM 窗口
  滑出后逐股只能靠本地日线）；两源**各自自洽**、来源各自标注，偏差打印留档。
- 采集池（250 只热榜池）与 THS 大幅回撤池**不是**全市场源，只在页面作为并集补充
  （明细更全：换手/量比/主力净额/日内回撤），逐行标来源，不并入 `count`。

## 3. 存储

新集合 `market_daily_limit_down_stocks`（一天一文档）：

```json
{"_id": "2026-10-19", "source": "em_pool", "fetchedAt": "...",
 "count": 22, "total": 22, "truncated": false,
 "rows": [{"code": "000949", "name": "新乡化纤", "pctChange": -9.95, "price": 5.79,
           "amount": 445659200, "turnoverRate": 4.51, "floatMarketCap": 9591143962.92,
           "pe": 13.92, "industry": "化学纤维", "emStreakDays": 1, "openNum": 16,
           "lastSealTime": "14:54:06", "raw": {"fund": 3517425, "fba": 69854613}}]}
```

- `rows` 逐股；`count` = EM 自报 `tc`（截断时 > `len(rows)`，同时 `truncated=true`）。
- TDX 文档 `source=tdx_local_bars`，`count == len(rows)`（同一扫描结果，不与家数表漂移）。

## 4. fail-visible 合同

1. 某日**无逐股文档** → 读口 `fullMarket.rowsMissing=<原因>`，页面 KPI 副行明示「逐股明细缺，
   仅采集池 Y 只」；不把采集池名单当全市场（§4.0）。
2. `truncated=true`（EM 池条目 > 返回条数）→ 页面标「已截断 total>rows」，家数仍按 `tc`。
3. EM 某日池为空 → 逐股文档 `count=0, rows=[]`（**真读数**，不是缺口）。
4. TDX 覆盖闸不足（窗边缘）→ 该日**不写逐股文档**、不写家数（沿用既有规则）。
5. 单行解析失败（缺 code/价格/跌幅）→ 跳过该行并计数 `badRows`，其余行照写；
   若全行解析失败 → 不写文档（与「真的 0 家」区分）。
6. 页面读口异常/降级沿用上一轮的 banner 机制，不新增静默分支。

## 5. 连跌口径（统一）

逐日回溯的「跌停集合」= 该日**逐股文档 rows 的 code 集**（有则用）+ 该日**采集池行**跌停 code 集；
两者都是同一权威阈值线（`core/limit_rules.is_limit_down_pct`）。`stats.streakDays` 暴露
「全市场逐股日数 / 采集池日数」，页面注记回溯覆盖，不混用两个定义。

## 6. 验收

| # | 检查 | 通过标准 |
| --- | --- | --- |
| A1 | 逐股 vs 家数对账（EM 日） | 无坏行时 `count == len(rows)`；坏行日 `count > len(rows)` 且 `badRows > 0`；截断日 `count > rowsReturned` 且 `truncated=true` |
| A2 | 逐股 vs 家数对账（TDX 日） | `count == len(rows)`，且与 `market_daily_limit_down` 同日 count 相等 |
| A3 | 覆盖（窗口内交易日） | EM 窗口(09-19~10-19) 与 TDX 回填段(01-01~09-18) 全覆盖；缺口逐日打印，不写 0 |
| A4 | 读口 | `GET /api/hotlist-jev/dieban-review` 返回 `fullMarket.rowsCount/rowsDocCount/rowsSource/rowsSourceLabel/rowsTruncated/rowsBad/rowsMissing/crossSource/countDisputed`；无文档日 `rowsMissing='no_rows_doc'`+`degraded` |
| A5 | 页面 | 明细含全市场股（如 10-19 新乡化纤 000949，采集池外）；来源列区分「全市场逐股/采集池快照/THS回撤池」 |
| A6 | 精度对照 | EM 与 TDX 双源日的家数偏差打印（沿用既有对账输出，不设通过门限，仅留档） |
| A7 | 测试 | 新增单测：EM 载荷解析（含截断/坏行/空池二义性闸）、TDX 逐股扫描（两道闸/覆盖闸/权威家数不覆盖）、优先级不覆盖、读口合并与 rowsMissing/countDisputed、页面守卫（非空洞：行为探针 + 真实函数体切片） |

## 7. 回退

- 纯新增集合 + 新增字段：`git revert` 代码即可；集合可保留（读口不再引用）或按 AGENTS §1.2.4
  用 `mongoexport` 归档后单集合 drop（本次不 drop）。
- 不修改既有 `market_daily_limit_down` 文档结构；EM/TDX 家数回填行为与现在一致。

## 8. 执行顺序

1. 代码 + 单测（全 mock，零外呼）；
2. `tdx` 逐股回填 dry-run → 核对逐日行数/缺口 → `--apply`；
3. `em` 逐股回填 dry-run（窗口内 ~20 日，节流 1.5s+抖动）→ 核对 → `--apply`；
4. 读口/页面实测（10-19 应出现池外股）+ 全量 hotlist 测试。

## 9. 执行与验收记录（2026-10-20，当日完成）

1. 代码+单测：`market_dieban_pool`（EM 逐股载荷解析/截断/坏行、源优先级、快照逐股兜底、
   `rows_for_date`）、`market_dieban_tdx`（`scan_rows` 与家数同源派生、`names_from_db`、
   `scan_counts` 改薄壳）、`backfill_limit_down_tdx`（逐股与家数解耦 + 跨源对账打印）、
   `jev_dieban_review`（逐股合并/`rowsMissing`/跨源连跌并集/`crossSource`）、relay_page（KPI 全市场
   主值 + 逐股覆盖副行/来源徽标/EM 封板字段展开/跨源横幅文案）。测试全 mock 零外呼，本轮新增
   用例 29 例（pool +7、tdx +2、页面守卫 +5、读口新文件 15），`tests/hotlist` 基线 770 →
   **799 passed**（2026-10-20 评审复算实测；初版误记为 14 例/785）。评审修复轮再加 10 例
   （pool +5 / 读口 +5）→ `tests/hotlist` **809 passed**。
2. TDX 逐股回填：`--start 2026-01-01 --end 2026-09-18 --apply` → 首轮写 115 日（另 3 日家数已
   EM 权威被跳过；2331 行是 118 日的扫描统计）；末棒 2026-10-19；扫描口径
   （`universe_hits` 去重后）宇宙 6043 只 / 命中日线 5636 只 / 目录内文件 5665（同码跨市场多计）
   / 目录外文件 4217 / 宇宙内缺日线 407。
3. EM 逐股回填：`--start 2026-09-19 --end 2026-10-19 --apply` → **15 日 / 223 行**落库，
   每日 `count == len(rows)`（无截断、无坏行）。连同 3 日边界日，逐股 `em_pool` 共 15 日、
   家数 `em_pool` 共 18 日。
4. **缺口发现与修复**：09-16/17/18 家数为 EM 权威（当时窗口内取得）但 EM 窗口已滑出 →
   逐股改由 TDX 补齐（工具改造：逐股与家数解耦），最终 **133/133 交易日全覆盖、零缺口**
   （日轴实际范围 **2026-03-27 ~ 2026-10-19**，`snapshot_frames` 轴如此；01-01~03-26 无帧故不在轴内）。
5. 跨源对账留档（A6）：09-16 家数(EM) 0 vs TDX 逐股 4 行、09-17 1 vs 2、09-18 0 vs 1
   ——与 F7 既有结论一致（TDX 重算 +1.65 均值偏高：除权巧合/北交所缺口/池剔除口径），
   两源各自自洽、显式标注不互改；家数仍以 EM 为权威。
6. 跨源披露（结构化，fail-visible）：家数源 ≠ 逐股源且数值不同 → `fullMarket.crossSource=true`
   + `degraded:[{scope:'full_market_rows_cross_source'}]`，页面横幅提示「勿把行数当家数相减」。
7. 读口实测（10-19）：`fullMarket.count=22 = rowsCount=22 = rowsDocCount=22`（EM 源），
   8 只池外股并入（新乡化纤 000949 等），负反馈名单 28→39，连跌≥2 4→5（跨源并集回溯，
   回溯上限 10 日：21 日逐股覆盖 / 19 日采集池覆盖 / 21 日槽覆盖）。
8. **跨源披露**：家数存疑日（逐股多于家数）→ `fullMarket.countDisputed` +
   `degraded:full_market_count_disputed`，且**剔出同源分位窗**（10-19 实测 `historyExcluded
   =[2026-09-16/17/18]`，分位窗 17→14 日，分位 ≈86 极高）；仅跨源但数值一致 →
   `full_market_rows_cross_source`（只提示不做差）。

## 10. 评审与修复轮（2026-10-20，3 个只读 reviewer lane）

- **lane A（后端数据管道）0 blocker / 1 major / 4 minor / 3 nit**；**lane B（服务+路由+页面）
  0 blocker / 3 major**；**lane C（独立复算）1 blocker / 2 major / 6 minor**。
- 已修（本轮）：EM 空池二义性闸；`count/rowsReturned/len(rows)` 三读数精化与读口 `rowsCount`
  语义（截断日不再把家数当行数）；快照全坏行不可算；逐股补拉熔断；快照逐股源登记；
  `reset_em_throttle_state` 清客户端单例；TDX「EM 权威家数不被覆盖」用例真的覆盖该分支
  （补前置棒使 D1 入 counts）；**页面/注释/文档「全市场逐股未落库」漂移（blocker，§1.2-5）**；
  跨源不做差、负差不再印出；`negN` 不用 `||` 吞真 0；池口径统计与并集判定分域
  （`limitDownPool`）；家数存疑剔出分位窗；`oneWordLimitDown` 未知→`null` 不写 `false`；
  连跌回溯切片到 `STREAK_LOOKBACK`；槽覆盖披露 + `degraded:streak_lookback`；
  逐日 15:00 行与逐股/家数一样进 120s 缓存（负缓存用哨兵，缺文档日不再每次读库）；
  空表文案区分「读口不可用」与「当日无数据」；板块筛选陈旧时清空；页面守卫改真实函数体切片
  + `diebanBanner/diebanHint` 纳入骨架断言。
- 存量数据处置：09-16/17/18 已落库的 EM 家数（0/1/0）**不篡改**（无逐日原始载荷可裁决真伪，
  改数等于伪造）；改为读口 `countDisputed` + 剔出分位窗 + 页面「家数存疑」标注，等 EM 原始
  载荷归档后再决定是否降级为缺口。
- 未修（列残余风险，见 design §5）：`limit_down_count` 在既有消费方（`jev_label_jiuyan` 两处）
  无 120s 缓存，60s 轮询下仍可能每分钟重试一次外呼；EM 原始载荷未归档（`p/tc/lbt` 语义仅有
  当日实测样本）；全市场逐股**回撤**名单未落库。
