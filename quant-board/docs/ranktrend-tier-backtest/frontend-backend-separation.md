# 前后端完全分离重构方案（RankTrend 四维信号）

> 2026-08-23 立项。目标：**前端零"计算结论值"算法，后端为 golden，后端产出并入库全部显示值，
> 前端只做展示格式化和 label 映射**。消除"前端自算 vs 后端生产"双轨导致的四维信号数据漂移与 UI/后台不一致。
> 归档位置：`quant-board/docs/ranktrend-tier-backtest/`

> **⚠️ 2026-08-24 回滚公告（重要，先读）**：
> **G1（综合排名后端化）已按产品决策回滚**（`873be02`/`36d0357`）：
> - `compRank/compScore/avgRankNum` **恢复前端本地实时计算**（`ComprehensiveRankEngine.rankMergedStocks`，
>   恢复 `b5cd1a7^` 完整版）——热榜股票池是实时动态变化的，后端快照/analyze 覆盖不全导致历史无记录
>   股票无综合排名（曾实测 45 只/7 只缺失），前端本地计算天然覆盖全部热榜股票（HTML 原始逻辑）。
> - 后端 golden 保留：`backend/analysis/ranktrend/comprehensive_rank.py`（`0ea572b`）与采集器接线
>   （`98ab74b`）仍生产快照口径 `compRank/compScore` **入库**，供快照/历史回放/jump_backfill/回测消费。
> - **双权威边界（重新书面定义）**：**前端 = 实时展示口径**（当前列表，实时行情输入）；
>   **后端 = 快照/历史/回测口径**（定时采集入库）。两者公式同构但输入时点不同，**同列两个视图值
>   必然不同，这是预期设计，不是 bug**；任何"对齐 compRank/avgRankNum"的工作必须先确认面向哪个口径。
> - G2 displayStatus / G3 市场分位 / G4 observation 入库 **未回滚**，仍为后端 golden + 前端消费。
> - 2026-08-25（`1e9f254`）：新进热榜（历史无快照）股票由 current 帧注册**单点 percentile 序列**，
>   量价/横截可算，共振/趋势/周期 `sampleQuality=insufficient` 降级——新股 percentile 为**过渡值**
>   （用实时 avgRankNum，随热榜刷新可能变动），下个快照落库后转正为权威历史口径。

## 0. 背景与根因

- 前面排查确认真根因：前端 `current_frame` 的 `rank`（随 zljzb 重算）/`avgRankNum`（随八平台
  热榜重算）是派生漂移值，污染后端 percentile 序列 → 横截面 cs_tier 漂移 → 四维档漂移。
  已修复（`backend/api/ranktrend_routes.py` 当前帧 percentile 权威化，commit `990c69d`）。
- 更深：前后端分离不彻底——前端仍自算若干"显示值"（综合排名 compScore/compRank、状态分类、
  市场分位），与后端口径不一致。
- **2026-08-24 修订**：上述"更深"结论仅对**信号计算**（displayStatus/市场分位/四信号）成立；
  **综合排名（compRank/avgRankNum）已按产品决策回到前端实时计算**（见回滚公告），
  "彻底分离"的目标范围随之收窄为"信号计算后端化 + 综合排名前端实时化（后端 golden 保留供快照/回测）"。

## 1. 边界（前端零计算结论值算法）

**删除（前端不再算）**：`percentile`（市场分位）、状态分类（`getRankTrendDisplayStatus`/`isHotAttention`）、
置信度（孤儿 `utils`）。
**恢复前端本地计算（2026-08-24 回滚 G1）**：`compScore/compRank`（五维综合，`ComprehensiveRankEngine`）、
`avgRankNum`（八平台加权均榜）——实时展示口径，与后端快照 golden 并存（双权威，见回滚公告）。
**保留（纯展示格式化）**：象限标签、TierBadge 颜色/文本、从后端 state 映射 label。
**后端 golden 生产**：四信号（resonance/rankTrend/crossSection/volumePrice/lifecycle）、displayStatus、
市场分位、observation 计算 + 入库；快照口径 compRank/avgRankNum 入库（供历史/回测）。
> 注：前端仅在后端字段缺失（旧缓存/离线）时回退前端兜底展示——属 fail-visible（免阻断），
> 正常路径不计算。

## 2. 缺口清单（后端需补）

| 缺口 | 后端现状 | 补法 | 状态 |
|---|---|---|---|
| **G1 compScore/compRank 综合排名** | 后端采集 `providers.py` 已有 `rank/compRank`（按 **avgRankNum 注意力**排序）；前端 `ComprehensiveRankEngine` 自算**五维综合** | 后端移植 `compute_comprehensive_ranks`（五维：avgRankNum 反/zljzb/fundPenetration/turnoverRate/turnover 加权）→ compScore/compRank 入库；前端删自算改消费 | ⚠️ **已回滚（2026-08-24）**：前端恢复本地五维计算（实时展示口径）；后端 golden 保留入库（快照/回测口径），**双权威并存**（见回滚公告）。`0ea572b`(后端 golden) + `98ab74b`(采集接线) 保留，`b82835a`(前端删自算) 已撤销 |
| **G2 displayStatus 状态分类** | 后端产 `observation.synergy.state` + 各维 `signalTier` + `strategy.candidateTier` + `meta.sampleStatus` | 后端生产 `displayStatus`（synergy.state+candidateTier+sampleStatus+资金/量能 signalTier 组合）入库；前端 `getRankTrendDisplayStatus` 改纯 label 映射 | ✅ `b4c062d`(后端) + `c338c40`(前端优先消费) + `7243a25`(strong_money 补齐) |
| **G3 市场分位 P50/70/85** | 后端无 | 后端计算全市场 turnover/volumeRatio/turnoverRate 分位，供 statusClassifier/量能判定 | ✅ `4391de1` |
| **G4 observation 入库** | analyze 实时算 observation，未持久化 | 快照/analyze 结果持久化到 MongoDB（snapshot_analysis 集合），前端读库 | ✅ `f074442`(存储) + `cb0ec0c`(analyze 入库引擎) + `742a6fc`(前端读库) + `0f75abb`(收尾同构+读口文档) |

## 3. 分阶段实施（全部完成）

### 阶段 1（rank percentile 权威化）✅
- `backend/api/ranktrend_routes.py` 当前帧 percentile 复用权威历史帧（commit `990c69d`）
- 测试：`tests/test_api_current_frame_authoritative.py`（当前帧 percentile 不随前端 rank 漂移）✅

### 阶段 2（G1）：综合排名后端化 ✅
- 后端：`compute_comprehensive_ranks` → `backend/analysis/ranktrend/comprehensive_rank.py`，
  产出 `compScore/compRank`（权威）+ 入库（commit `0ea572b`）；
- 前端：删 `ComprehensiveRankEngine` 自算，行情列表"综合排名"列改消费后端 `compRank`
  （commit `b82835a`，`StockMergeCoordinator` 注释"不再自行计算，继承后端"）；
- 测试：后端单测（五维排序与前端一致/权威）+ 前端消费测试 + golden 回归。

### 阶段 3（G2+G3）：状态分类 + 市场分位后端化 ✅
- 后端：生产 `displayStatus`（含市场分位 P50/70/85）入库（commit `b4c062d`/`4391de1`）；
- 前端：`getRankTrendDisplayStatus` 优先消费后端 `displayStatus`（commit `c338c40`，纯 label 映射，
  后端缺失时回退兜底 = fail-visible）；`isHotAttention` 消费后端 `meta.currentRank/currentPercentile`；
- 补充：`7243a25`（G2 strong_money 强资确认后端状态，前端确定性展示）；
- 测试：后端 displayStatus 单测 + 前端映射测试 + golden。

### 阶段 4（G4）：observation 持久化入库 ✅
- 后端：`snapshot_analysis` 集合 + `analyze_snapshot_and_persist`（对快照帧全量 analyze 持久化
  observation/displayStatus/meta/resonance），读口 `GET /api/snapshots/analysis`（commit `f074442`/`cb0ec0c`/`0f75abb`）；
- 前端：`742a6fc` 读库 reader service（历史回放/对比，当前帧保持实时 analyze）；
- 测试：入库/读库一致性。

## 4. 验收标准（每阶段）——已满足
- 前端**零计算结论值**（正常路径 grep 前端自算逻辑为空）✅；
- 后端 golden：相同输入 → 相同显示值（入库稳定，不随刷新漂移）✅；
- golden 回归全绿 + 相关测试通过 ✅；
- 浏览器验收：非交易日多次刷新，四维/状态列不再漂移 ✅。

## 5. ⚠️ 未决分叉（已定案 ✅ = 选项 B → ⚠️ 2026-08-24 回滚 = 恢复前端本地计算）

**行情列表"综合排名"列语义**：
- **选项 A（注意力口径）**：后端现成（providers.py 按 avgRankNum），但"综合排名"列从"五维综合"变
  "八平台注意力排名"，改变该列排序语义。
- **选项 B（保持五维综合）**：后端移植五维 `compute_comprehensive_scores`（G1 完整），
  "综合排名"列语义不变，后端为 golden；avgRankNum（注意力）口径仍用于**横截面 percentile**
  （不在"综合排名"列）。

**2026-08-23 定案 B**：`0ea572b` 后端五维 + `b82835a` 前端消费后端——"综合排名"列保持五维语义、
后端为 golden。
**2026-08-24 回滚**（用户决策，见回滚公告）：B 的后端化**不成立**——热榜股票池实时动态变化，
后端快照/analyze 覆盖不全导致历史无记录股票无综合排名。恢复前端本地五维计算（实时覆盖全量热榜股票），
后端 golden 保留供快照/回测。**当前状态 = 选项 B 的公式 + 双权威口径**（前端实时、后端快照），
不再是"后端唯一权威"。

## 6. currentFrame / 缓存契约（2026-08-25 复盘固化）

- **缓存键规范化**（`_normalize_current_frame`）：`slotTime` 去 `current:N` 序列号；`stocks` 只保留
  `code/rank/avgRankNum` 进键（**计算输入 ⊆ 缓存键**不变式）。当前新股 percentile 计算
  （`attention_rank_lookup`）只用 `avgRankNum`（进键）→ 缓存一致性成立；`turnover/turnoverRate`
  等量能字段**不进键**，仅参与 `frame_market_percentiles`（响应辅助字段，TTL 内陈旧可接受）。
  ⚠️ 未来若让新股 percentile 依赖量能字段，必须同步进键（有契约测试锁定，见 tests）。
- **新股 percentile = 过渡值**：历史无快照的股票用 current 帧实时 `avgRankNum` 注册单点序列
  （`1e9f254`），值随热榜刷新可能变动；`sampleQuality=insufficient` 降级展示；下个快照落库后
  转正为权威历史口径。avgRankNum 全平台缺失（≤0）时新股仍不产出（fail-visible，不编造）。
- **帧级 marketMedian 与个股 percentile 不同源（预期设计）**：current 帧含量能字段时，
  `marketMedianPercentile` 用 current 帧实时 attention（前端 avgRankNum）；老股票个股
  percentile 序列用权威历史帧（修复 A）。两者时点不同是设计（marketMedian 作实时相对强弱基准）。
- **currentFrame.stocks.rank 字段语义**：前端传 `rank = compRank || rank`（五维综合排名），
  仅作缓存键身份与排序展示；后端 percentile 计算一律用 `avgRankNum`（`attention_rank_lookup`/
  `frame_cross_section`），**不读 rank 字段**——勿新增消费方误用。
