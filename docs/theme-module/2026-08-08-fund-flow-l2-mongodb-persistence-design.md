# 主力资金 L2 持久化到 MongoDB 方案设计（冷启动零第三方）

## 状态

**已实施（2026-08-08）**：见下方"## 9. 实施记录"。背景：东财排行接口风控确认
不可用（`RemoteDisconnected`，IP 临时封禁），akshare/Tushare 只提供东财、同花顺
两类第三方资金接口；本方案**放弃第三方全市场种子**，改为把可信的
`mainMonitorDetail`（L2）数据持久化到 MongoDB，冷启动从本地 MongoDB 恢复——
冷启动零第三方请求，口径与展示完全一致。

## 1. 目标与非目标

### 目标

- 冷启动/刷新首屏资金列有值，来源 = 最近交易日的 L2 校准数据（本地 MongoDB），
  不依赖 akshare 网页/东财排行（均有风控与口径问题）。
- 盘中 `mainMonitorDetail` 校准结果持续写入 MongoDB，跨重启、跨进程（8000/8001）
  可恢复 last-good。

### 非目标

- 不做全市场 L2 持久化（30 req/min 限流物理不可行，仅覆盖展示池 200-400 只）。
- 不引入新第三方数据源；akshare 种子层停用但保留代码与开关作回退。
- 不把运行态资金写入正式快照/回测（沿用既有约束：`stock_rows`/`sector_rows`
  只接受 `broker_l2`/`official_l2`）。
- 不做自动清理/保留策略（数据量 400 行/交易日很小，标注为后续）。

## 2. 数据链路

```
盘中：mainMonitorDetail（30 req/min）→ ThsFundRefreshScheduler（展示池分批校准）
      → ThemeFundCache（Redis + 进程内 last-good）→ 前端 fund-stream
      └──→ MongoDB fund_flow_l2（批量 upsert，异步不阻塞刷新）

冷启动：MongoDB 最近 sessionDate 的 L2 行 → ThemeFundCache.put_many（Redis）
      → 前端首屏有值（零第三方请求）
```

## 3. MongoDB 存储设计

集合：`fund_flow_l2`（复用 `backend/data/repositories/mongo_repository` 模式）

文档 schema（一行一股一日，**按 7 档存储逐笔聚合**）：

```text
{
  code: "000001",                       # 6 位代码
  sessionDate: "2026-08-07",            # 交易日期（L2 数据日期）
  tradingDate: "2026-08-07",
  source: "ths_main_monitor",           # 固定 L2 主源
  sourceTs: 1754467200000,              # 采集时间戳 ms
  updatedAt: 1754467300000,
  total: {                              # title 摘要（全天主力买卖）
    zlje: -31000000.0,                  # mainbuy − mainsell（元）
    buyAmount: 268000000.0,             # mainbuy
    sellAmount: 299000000.0,            # mainsell
  },
  buckets: [                            # 7 档逐笔聚合（数据源 mainMonitorDetail 的 list）
    { "tier": "ge_1000w",  "min": 10000000, "max": null,      "category": "超大单", "buyCount": 5,  "sellCount": 17, "buyAmount": 123000000.0, "sellAmount": 89000000.0,  "net": 34000000.0 },
    { "tier": "700_1000w", "min": 7000000,  "max": 10000000,  "category": "大单",   "buyCount": 23, "sellCount": 15, "buyAmount": 88000000.0,  "sellAmount": 72000000.0,  "net": 16000000.0 },
    { "tier": "500_700w",  "min": 5000000,  "max": 7000000,   "category": "大单",   "buyCount": 19, "sellCount": 37, ... },
    { "tier": "300_500w",  "min": 3000000,  "max": 5000000,   "category": "大单",   "buyCount": 97, "sellCount": 89, ... },
    { "tier": "100_300w",  "min": 1000000,  "max": 3000000,   "category": "中单",   "buyCount": 996, "sellCount": 974, ... },
    { "tier": "50_100w",   "min": 500000,   "max": 1000000,   "category": "小单",   "buyCount": 984, "sellCount": 1003, ... },
    { "tier": "30_50w",    "min": 300000,   "max": 500000,    "category": "小单",   "buyCount": 65,  "sellCount": 54, ... }
  ]
}
```

### 档位与分类映射（2026-08-08 确认）

| 档位 | 单笔金额区间 | 分类 |
| --- | --- | --- |
| `ge_1000w` | ≥ 1000 万 | 超大单 |
| `700_1000w` | 700–1000 万 | 大单 |
| `500_700w` | 500–700 万 | 大单 |
| `300_500w` | 300–500 万 | 大单 |
| `100_300w` | 100–300 万 | 中单 |
| `50_100w` | 50–100 万 | 小单 |
| `30_50w` | 30–50 万 | 小单 |

每档字段：`buyCount`/`sellCount`（笔数，按 `tradetype` 1=买、2=卖）、
`buyAmount`/`sellAmount`（金额）、`net`（buyAmount − sellAmount）。

- 数据源：`mainMonitorDetail` 响应 `data.list` 的逐笔（字段 `money` 单笔金额元、
  `tradetype` 1/2 买卖方向）——实测 7 档全部有数据（5 只 4419 笔，金额 16 万–2950 万）；
- 聚合：新增纯函数（如 `ths_fund_flow_buckets.aggregate_l2_buckets(rows)`），
  按上表边界对 `list` 逐笔分类求和；`load_row` 的摘要行（zlje）保持不变供
  Redis/前端，MongoDB 存完整 7 档富数据；
- 唯一索引：`{sessionDate: 1, code: 1}`（upsert 键）；
- 写入：`ThsFundRefreshScheduler` 每批校准后，用 `load_raw` 拿 `list` → 聚合
  7 档 → 批量 upsert（异步提交，不阻塞 180s 刷新循环）；Redis 行仍由
  `load_row` 摘要生成（现状不变）；
- 生命周期：不做自动清理（首版）；如需保留策略，按 `sessionDate` 保留最近
  N 个交易日，作为后续增强。

## 4. 冷启动恢复流程

1. `backend/main.py` `on_startup`：`get_ths_fund_refresh_scheduler().start()` 之前，
   先执行"MongoDB 恢复"：查 `fund_flow_l2` 最近 `sessionDate` 全部行；
2. 恢复结果投影为缓存行（`{code, sessionDate, zlje: doc.total.zlje,
   source/moneyFlowSource: doc.source, sourceTs}`）→ `ThemeFundCache.put_many`
   （进程内 last-good + Redis）；完整 7 档 `buckets` 保留在 MongoDB，冷启动
   不进 Redis（前端资金列只需 zlje 摘要）；
3. 前端首屏 `fund-stream` 直接命中（`source=ths_main_monitor`）；
4. 盘中 `ThsFundRefreshScheduler` 继续逐票校准刷新（写 Redis + MongoDB），
   与恢复值无缝衔接（同 source、同 rank）。

- 最近交易日判断：直接取"数据里最大的 `sessionDate`"，不硬编码交易日历
  （与 2026-07-25 设计一致：接受最近交易日总额，不硬编码周末/节假日）。
- **Redis TTL = 7 天（容灾窗口，2026-08-08 用户确认）**：`theme-fund:v3`
  默认 604800s（`QUANT_BOARD_THEME_FUND_CACHE_TTL_SECONDS` 可覆盖）。调度器
  每次写入刷新 TTL，正常运行永不过期；TTL 只在停止写入后生效，语义是
  **冷启动 MongoDB 不可用时 Redis last-good 的兜底恢复窗口**（跨周末/短故障）；
  进程内 last-good 不因 TTL 删除。

## 5. 种子层停用决策（2026-08-08 确认）

- `MarketFundScheduler` 的 akshare 全市场预热**默认关闭**（新增配置开关
  `QUANT_BOARD_THEME_FUND_SEED_ENABLED`，默认 `false`）；
- provider 代码（`akshare_fund_provider.py` 自请求东财 clist）保留，
  开关开启时可回退为"全市场种子占位"（`eastmoney_seed`，估算角标）；
- `eastmoney_seed`/`ths_web_seed` 的 source rank 1 与前端展示保留（兼容存量缓存）。

## 6. 范围与覆盖（fail-visible）

- 展示池（fund-stream 订阅池，约 200-400 只）：冷启动即有值，盘中持续校准；
- 全市场非展示池：无 L2 数据（限流物理约束），资金列显示 `--`，题材聚合
  打 `fund_flow_partial` 标记（不归零、不伪装）；
- 首次部署（MongoDB 无历史）：首日展示池由盘中校准补齐（约 5-7 分钟），
  补齐前显示 `--`，不阻塞其它数据。

## 7. 改动清单（已实施 2026-08-08）

| 文件 | 改动 |
| --- | --- |
| `backend/services/market/ths_fund_flow_buckets.py`（新） | 纯函数 `aggregate_l2_buckets(rows)`：按 7 档边界（1000/700/500/300/100/50/30 万）对 `mainMonitorDetail` `list` 逐笔聚合 buy/sell 笔数与金额（`tradetype` 1=买 2=卖） |
| `backend/data/repositories/fund_flow_repository.py`（新） | `fund_flow_l2` 集合 upsert（含 `total` + `buckets`）/最近 sessionDate 批量读取/唯一索引，复用 `mongo_repository` |
| `backend/services/market/ths_fund_refresh_scheduler.py` | 每批校准改用 `load_raw` 拿 `list` → `aggregate_l2_buckets` → 批量 upsert MongoDB（异步）；Redis 行仍由 `load_row` 摘要生成 |
| `backend/main.py` | `on_startup` 增加 MongoDB 恢复步骤（投影 `total.zlje` → `put_many`，再启动调度器）；关闭 akshare 种子预热 |
| `backend/core/settings.py` | 新增 `QUANT_BOARD_THEME_FUND_SEED_ENABLED`（默认 false）与 MongoDB 持久化开关 |
| `backend/services/market/fund_scheduler.py` | 种子预热受开关控制 |
| 测试 | 档位聚合纯函数（边界/买卖方向/空 list）；仓储 upsert/恢复；调度器写库；冷启动恢复（mock MongoDB）；开关关闭时无种子请求 |
| 文档 | 本方案落地状态、`api-cli.md`、`database-migration-plan.md`（新集合） |

## 8. 验收标准

1. 冷缓存启动：`fund_flow_l2` 有数据时首屏展示池资金列有值（`ths_main_monitor`，
   最近交易日），无第三方请求（`marketFundRefresh` 无 akshare 调用）；
2. 盘中校准每批写入 MongoDB，重启后恢复值 = 最近交易日 L2 值；
3. 开关 `QUANT_BOARD_THEME_FUND_SEED_ENABLED=false` 时 akshare 不产生任何请求；
4. 全市场非展示池显示 `--`/`fund_flow_partial`，不归零、不伪装；
5. MongoDB 不可用时回退为"仅盘中校准"（不阻塞启动，告警可见）。

## 9. 回退边界

- 开关关闭 MongoDB 持久化 → 回到"仅 Redis/内存 + 盘中校准"，首日冷启动
  展示池部分空白（可接受）；
- 开关开启 akshare 种子 → 恢复 `eastmoney_seed` 全市场占位（风控风险自担）；
- 不清空 `fund_flow_l2` 历史数据；MongoDB 恢复失败不影响进程启动。

## 10. 风险与未决

- **首次部署空库**：首日资金列部分空白属预期（fail-visible），可在实盘运行
  数个交易日后自然积累；
- **写入一致性**：upsert 按 `{sessionDate, code}`，同股同日多次校准取最新
  `sourceTs`（upsert 覆盖）；
- **未决**：MongoDB 集合是否需要纳入 Supabase 同构备份（`supabase_schema.sql`）
  ——建议纳入，与快照备份策略一致（实施时确认）；
- **未决**：保留策略（按 `sessionDate` 清理）是否首版实现——建议不做，
  400 行/交易日数据量可忽略。

## 11. 实施记录（2026-08-08）

按本方案第 7 节清单全部落地，测试全绿（后端全量 `1374 passed`，新增
buckets/仓储/调度器测试 22 项）。与文档的三个实现差异：

1. **调度器一次拉取双产出**（优于文档第 3 节"Redis 行仍由 load_row 生成"）：
   `ThsFundRefreshScheduler` 每只改用 `load_raw` **一次请求**，`parse_l2_summary`
   从 `data.title` 产出 Redis 摘要行、`aggregate_l2_buckets` 从 `data.list`
   产出 MongoDB 7 档——避免 `load_row` 的二次请求（30 req/min 限流下更省额度）。
2. **单票超时细粒度化**：原"批级超时 → 全局冷却"改为"每只独立 `wait_for`
   超时 → 仅该票退避"，挂起单票不再阻塞同批其它票（系统性错误仍全局冷却）。
3. **持久化开关**：MongoDB 持久化由既有 `QUANT_BOARD_STORAGE_BACKEND=mongodb`
   控制，未另设独立开关；仅新增种子开关 `QUANT_BOARD_THEME_FUND_SEED_ENABLED`
   （默认 false，`fund_scheduler.start()` 关闭时完全不发 akshare 请求）。

验收标准对照：

- [x] 1. 冷缓存启动：`restore_fund_flow_from_mongodb()`（mongodb 模式 on_startup）
  投影最近交易日 `total.zlje` → `ThemeFundCache.put_many`，无第三方请求；
- [x] 2. 盘中校准每批异步 upsert `fund_flow_l2`，重启恢复 = 最近交易日 L2 值；
- [x] 3. 种子开关默认 false，`MarketFundScheduler.start()` 不创建任务；
- [x] 4. 全市场非展示池 `--`/`fund_flow_partial`（ThemeHeatFeed 只认
  `ths_main_monitor` 行，不归零不伪装）；
- [x] 5. MongoDB 不可用/恢复失败仅告警，不阻塞启动。

未决项维持：Supabase 同构备份（`supabase_schema.sql`）未纳入，保留策略未做
（400 行/交易日可忽略），实盘数日后按第 8 节人工验收。
