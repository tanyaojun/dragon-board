# 单一事实源架构：北极星、双源盘点与收敛路线

> 状态：2026-09-21 首版。盘点基于当日源码逐行核实（file:line 证据见 §3 表格）；配套门禁规则见 `skills/single-source-of-truth/SKILL.md`，入口已挂 `AGENTS.md` §11 设计必查清单。
> 触发：2026-09-21 用户复盘裁决——09-19 自治池与 09-21 池源替换两轮方案仍遗留「前端自成体系」，前后端两池并存彻底暴露框架性问题；确立「后端权威、前端消费」北极星并制度化。
> 前序 spec：`docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`、`docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md`。

## 1. 北极星

池 membership、快照生产、业务口径和分析算法的单一事实源在 QuantBoard 后端；Dragon Board 前端是消费与展示端。前端只保留两类自持能力：实时行情展示链与降级只读观察面（必须打标，不得长成第二事实源）。

三条执行立场（完整规则见 skill）：

1. 新算法、新口径、新采集能力默认落在后端；前端自建任何数据生产/计算前先回答「后端有没有、该不该由后端有」。
2. 允许的双源只限保留面与已登记收敛路径的迁移面；必须声明权威侧与消费侧，统一登记 §3 表格。
3. 最小化修改原则保护「可验证、可回退」，不保护「回避架构裁决」；架构级根因允许架构级目标，仍用最小步切片执行。

## 2. 教训背景（为什么需要这份文档）

2026-09-18 至 09-21 两池对账三轮返工：

1. 09-19 自治池（采集器直抓 8 平台）解决「帧池锁定前端启动时点、浏览器离线池死」，但前端独立热榜合并池原样保留——双源架构未动，只把其中一侧变得自治。
2. 验收「列表 ⊆ 帧池」盘后实测失败（48 missing / 42 extra），处理方式是 §7.5 口径修正（把不可达验收改宽为「同源性验证」），而非回溯双源架构。
3. 09-21 池源替换（`mergeData` 单点切帧池）才真正消除池双源，实测列表与收盘帧 239/239 精确一致。

根因复盘：09-19 spec 自己写下了时点差（§1 事实 4：前端池随加载时点变化）与白名单差（§2.2）两个事实，却没有推出「零前端改动下精确对账原理性不可达」；「前端零改动」进非目标静默通过，设计期无任何门禁强制回答「本方案是消除还是保留双源」。本文件与配套 skill 就是补这道门禁。同理教训：热榜综合评分 2026-08-24 前端回滚恢复本地计算、快照 analyze 产物曾空置一个多月（2026-09-10 复盘），都是双源/口径分裂的同类病例。

## 3. 双源盘点表（2026-09-21，源码逐行核实）

| # | 维度 | 前端位置 | 后端位置 | 状态 | 权威侧 | 收敛路径 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 8 平台热榜抓取 | `src/services/adapters.ts:53-269`（仅适配/格式化，经 proxy-server `routes/quantBoardProxy.js:7-34` 转发 8000） | `quant-board/backend/market_proxy/hotlists.py:33-120` + `api/market_data_routes.py:129,146` | ✅ 已收敛 | 后端 | — |
| 2 | 列表池 membership | `dataLoader/DataLoaderFacade.ts` mergeData（帧池优先 + 降级 provenance 打标） | snapshot frames（采集器槽位池，`snapshot_collector/`） | ✅ 已收敛（2026-09-21） | 后端 | 09-21 池源替换 spec |
| 3 | RankTrend golden | `RankTrendAnalyzer.ts:75,438` 只消费 analyze API；`rankTrend/*` 仅投影/应用层，零算法残留 | `analysis/ranktrend/engine.py`（`api/ranktrend_routes.py:405`） | ✅ 已收敛 | 后端 | — |
| 4 | 热榜情绪（逐日全市场） | `hotlist/hotlistSentimentApi.ts:2` 薄客户端（TS 算法已删） | `analysis/hotlist/sentiment.py:1` 唯一权威口径 | ✅ 已收敛 | 后端 | — |
| 5 | 正式快照生产 | `snapshot/facade.ts:26` sweep 默认关；`runtime.ts:1321` 仅补传/备份回放 | `snapshot_collector/service.py:778,652` 直写 MongoDB；`main.py:674` ingest 路由=手工/诊断；after-save 钩子 `data/repositories/snapshot_post_save.py` | ✅ 已收敛 | 后端 | — |
| 6 | 五维综合评分 compScore/compRank | `dataLoader/ComprehensiveRankEngine.ts:97-170`（mergeData 链活跃，`StockMergeCoordinator.ts:88`） | `analysis/ranktrend/ranking/comprehensive_rank.py:53`（`providers.py:1047` 快照链调用） | ⚠️ 双实现并存（迁移面） | 待裁决（§5 P1） | P1 |
| 7 | 个股热度 hotness | `hotness/StockHotnessCalculator.ts:11-20`（8 分量加权）+ `dataLoader/StockHotnessService.ts:5` | 无对应实现 | ⚠️ 前端独有（迁移面候选） | 前端（暂） | P2 |
| 8 | 实时行情 | `websocket.ts:94-103`（ws://127.0.0.1:8765/ws/quotes → `QuoteService`/`RealtimeQuoteCoordinator`） | `python-bridge/main.py:666-667`（WS 生产）；`market_proxy/quotes.py`（HTTP 兜底+采集链 in-process） | 🔵 保留面 | — | 长期保留（用途不同） |
| 9 | 题材热度 heat | `theme/ThemeHeatFeed.ts` 消费 `/api/themes/heat` | `analysis/theme/heat.py:8`（题材人气聚合） | ✅ 后端唯一 | 后端 | —（互补领域） |

补注：

- 个股热度（逐股 8 分量）、题材热度（逐题材人气聚合）、热榜情绪（逐日全市场）是互补的不同领域，不是同一计算的两套实现（已核实）。
- 研究/回测链对 market_proxy 行情的直接消费未确认（grep 无命中）；已确认的消费方是前端 HTTP 兜底与采集链 in-process 直取。
- 前端 HTTP 行情兜底（`/api/quotes/tencent` → market_proxy）与 WS 链同属行情域，源同后端，不构成双事实源。

## 4. 保留面白名单

- **实时行情 WS 链**（python-bridge → 前端）：秒级渲染时效 vs 研究链批量用途不同；market_proxy HTTP 作为兜底与采集源，两者同源不同链，长期保留。
- **降级只读观察面**：后端 8000 不可用时前端回退（如热榜合并池），必须 provenance 打标 + 注脚如实透出 + 恢复后切回权威源（09-21 池源替换实现即为范式）。
- 保留面新增必须登记本表并说明用途差异理由；「临时先在前端算一版」不是保留面。

## 5. 收敛路线图

**P1（当前唯一活跃双源）：五维综合评分 compScore/compRank。**

- 背景：2026-08-24 前端显式回滚恢复本地实时计算（`StockMergeCoordinator.ts:84-88` 注记），回滚理由是「后端快照/analyze 覆盖不全 → 历史无记录股票无排名」。
- 现状变化：09-21 池源替换后，列表 = 帧池全集，帧行自带后端 golden compRank——回滚理由已部分消解；但新约束出现：帧槽 30 分钟一档，前端本地算可秒级跟随热榜轮动，后端口径有 ≤30min 排名滞后。
- 待裁决权衡：**口径唯一**（后端权威，前端删算法消费帧行/analyze 产物，代价是排名时效降级）vs **排名时效**（前端保留本地实时算，登记为保留面，代价是永久双实现与代际差，靠 `poolSource` provenance 区分）。
- 未裁决前维持现状；裁决后立项（立项时按 skill 三问出 spec）。任何一侧都不得在无登记的情况下静默改动口径。

**P2：hotness 个股热度后端化评估。**

- 仅当快照链/研究链需要该口径时立项（当前无消费方证据，避免过度设计）；否则保留为前端展示层计算，本表登记为前端独有领域。

**持续：文档口径权威顺序执行（§6）。**

## 6. 文档口径权威顺序

冲突裁决顺序：**源码与测试 > `AGENTS.md` 现行口径 > 专题文档 > `CLAUDE.md`**。

已知漂移记录（2026-09-21 发现，当日修复）：`CLAUDE.md` 三处仍写「TS 是 Python 移植的 golden 标准 / rankTrend golden 标准模块」（:79、:157、:197），与 `AGENTS.md` §4.2 现行口径（Python `engine.py` 为生产事实标准、TS 只消费）直接矛盾；快照写库段仍写「正式快照写库必须走 ingest」，与 collector 直写主产、ingest=手工/诊断的现状矛盾。已按 `AGENTS.md` 口径做最小同步；`CLAUDE.md` 与 `AGENTS.md` 结构差异较大，整体重建留待用户决策。

## 7. 维护规则

- 任何双源状态变化（新增、收敛、裁决）必须当次更新 §3 表格，与代码改动同批提交。
- 新方案设计按 skill 三问回答后，若产生新迁移面，先登记本表再实施。
- 本表是双源唯一权威登记处；发现未登记双源先补登记，再决定动不动代码。
