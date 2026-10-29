# 连板行情页新增 & 热榜行情页删除（2026-10-29 用户裁决记录）

> 状态：**已实施**（goal `mvte4eg9-4g4sr0`）。本文是本轮「删除 + 新增」的单一决策记录，
> 供后续审计与回退溯源；历史过程文档（preregistration 等）仅在顶部加终止注记，不重写。

## 一、用户裁决链

1. **删除**：JEV 叙事工作台（:8008 relay_page）「热榜行情」页面及相关代码和 MongoDB 数据集
   （明确区别于 :5173 根工作台的八合一热榜）。
2. **新增**：「连板行情」页——左栏韭研 `fields[]` 板块目录、右栏成分股列表，展示样式参照
   KPL【板块行情】（`.kpl-layout` 左目录右列表）；数据复用韭研打标链（`jiuyan_action` 集合）
   已采集名单；**前端拉取后仅内存态动态更新，不落库、服务端不缓存**；行情接入 KPL socket。
3. **MongoDB 范围（用户裁决 A）**：6 个 `*_pilot` 集合为热榜行情页独享数据链（其他页面零引用，
   写入方为同链生产脚本）→ 归档后 drop，生产脚本顺链清理。

## 二、已删除面（代码）

| 层 | 删除内容 |
| --- | --- |
| 前端 | `relay_page/index.html`：`tab-quotes` 视图、侧栏项/面包屑、`STATE.quotes*`、loadAll quotes-review 拉取、quote 渲染块（qTier→quotesDetailHtml 全链）、quotes 专属常量（LC/RES/TRD/HEA/VPQ/TIER 及 tierB/dirB/agreeB/boardsCell/fmtYiCell） |
| 路由 | `backend/api/hotlist_jev_quotes_routes.py`（整文件）+ main.py 注册 |
| 服务 | `backend/services/jev/jev_quotes_review.py`（整文件） |
| 生产脚本 | `jev_vote_confirm.py` / `jev_vote_winrate_ledger.py` / `jev_resonance_recheck.py` / `jev_trend_recheck.py` / `jev_heat_volume_recheck.py` + 对应 4 个 ammo 层（vote/resonance/trend/heat_volume） |
| 调度 | `operations/schedule.py` 摘除 `_run_vote_winrate_ledger_step`（advisory 步）与 steps 清单项 |
| 测试 | `test_jev_vote_confirm / test_jev_vote_winrate_ledger / test_jev_vote_v4_material / test_jev_resonance_recheck / test_jev_trend_recheck / test_jev_heat_volume_recheck`（6 个整文件）+ `test_hotlist_jev_api` / `test_jev_view_date_fallback_api` 的 quotes 用例 |

## 三、MongoDB 数据集处置（先归档后 drop）

- 归档：`data/backups/mongoexport_20261029_quotes_pilot_archive/`（7 集合 8886 条 JSONL +
  `_metadata.json`；mongodump/mongoexport 本机不可用，fail-visible 记录改用 pymongo 导出）。
- 已 drop（单集合显式操作，drop 后残留校验 0）：
  `hotlist_jev_vote_confirm_pilot` / `hotlist_jev_lifecycle_recheck_pilot` /
  `hotlist_jev_resonance_recheck_pilot` / `hotlist_jev_trend_recheck_pilot` /
  `hotlist_jev_heat_recheck_pilot` / `hotlist_jev_volume_recheck_pilot` /
  `hotlist_jev_vote_winrate_ledger`（台账输出集合，无任何读取方）。
- **未触碰（共享集合）**：`hotlist_jev_sentiment`（JEV 轨道核心存储，总览/连板指数/相位/题材
  digest 共用）、`jiuyan_action`、`snapshot_frames / snapshot_stock_rows / snapshot_analysis`。

## 四、连板行情页合同（新增）

- 入口：侧栏「工作台 › 连板行情」（`lianban` 视图）；样式复用 `.kpl-layout` 左目录右列表。
- 数据：`GET /api/hotlist-jev/jiuyan-action`（复用现有读口，纯读）；60s 轮询；**仅内存态**
  （LB 纯 JS 对象，无 localStorage/IndexedDB，服务端实时透传不缓存）。
- 左栏：`fields[]` 板块目录七列（序号/板块/家数 + 节点/聚合涨幅/主力净额/成交额，
  2026-10-29 用户需求）——节点/聚合涨幅复刻板块节点模块（同源
  `/api/hotlist-jev/sector-nodes`，按 board 名匹配：`NODE_CN[node]` 徽标 +
  `aggN10.pctMean` 近10日活跃股均值）；主力净额/成交额=成员股 KPL WS 3001 quotas
  聚合（`KQ.MAIN_NET/AMOUNT`，未到流不计入不伪造）；左栏带板块搜索；点选驱动右栏。
- 右栏：成分股实时行情表，**字段与 KPL【板块行情】个股列表完全一致**（用户裁决
  2026-10-29：代码/名称/地位/现价/涨幅%/换手%/连板/主力净/主力买/主力卖/量比/成交额/概念）。
- 行情值：WS 3001 混合流 quotas 优先（`KPL.items`，与板块行情同源）→ 3006 `hq` 兑底
  价/涨幅 → 韭研盘口快照价最后兜底（fail-visible，不猜数）；地位/换手/概念：
  `live-stocks-meta` 惰性索引（与直播页共用 `LIVE.stockMeta` 单一事实源）；连板列韭研
  `num` 打标口径优先（本页核心名单），缺则回 KPL meta `board_status`。
- 行情列：KPL socket 实时推送——个股代码经 `lbCode` 归一化（实测全集带交易所前缀
  sz001219/sh603006，剥前缀取尾 6 位）后经 `kplSyncStockSubscription` 共享签名缓存
  并入订阅（与板块行情/直播页同一份记账）；渲染读 `KPL.items` quotas + `KPL.hq`
  （3006 事件写入），3s 重渲染。
  - 口径（协议测试锚）：`price` ×10000（113000=11.30 元）；`inc_rate` ×100（125→1.25%），
    涨幅越界护栏 `|pct|>21` → `'--'`（口径异常不猜数）；3006 未到流时现价兑底韭研盘口快照价
    （title 标注），涨幅如实 `'--'`（fail-visible）。
- 离开页签停轮询计时器；WS 断链沿用 `kplViewLeave`（非 kpl 组视图统一断）。

## 五、测试与守卫

- `tests/hotlist/test_relay_page_window.py` 新增连板行情静态守卫（视图/侧栏/布局/内存态/
  订阅接线/3006 口径护栏）与「热榜行情」删除回归锁（零残留）。
- pytest 全 mock（零真实 jev/KPL 调用，红线 7）。
