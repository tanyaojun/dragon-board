# 前后端完全分离重构方案（RankTrend 四维信号）

> 2026-08-23 立项。目标：**前端零"计算结论值"算法，后端为 golden，后端产出并入库全部显示值，
> 前端只做展示格式化和 label 映射**。消除"前端自算 vs 后端生产"双轨导致的四维信号数据漂移
> 与 UI/后台不一致。
> 归档位置：`quant-board/docs/ranktrend-tier-backtest/`

## 0. 背景与根因

- 前面排查确认真根因：前端 `current_frame` 的 `rank`（随 zljzb 重算）/`avgRankNum`（随八平台
  热榜重算）是派生漂移值，污染后端 percentile 序列 → 横截面 cs_tier 漂移 → 四维档漂移。
  已修复（`backend/api/ranktrend_routes.py` 当前帧 percentile 权威化，commit `990c69d`）。
- 更深：前后端分离不彻底——前端仍自算若干"显示值"（综合排名 compScore/compRank、状态分类、
  市场分位），与后端口径不一致。

## 1. 边界（前端零计算结论值算法）

**删除（前端不再算）**：`compScore/compRank`、`avgRankNum`、`percentile`（市场分位）、
状态分类（`getRankTrendDisplayStatus`/`isHotAttention`）、置信度（孤儿 `utils`）。
**保留（纯展示格式化）**：象限标签、TierBadge 颜色/文本、从后端 state 映射 label。
**后端 golden 生产**：全部显示值计算 + 入库；前端消费后端 `rankTrend.observation/meta` 等。

## 2. 缺口清单（后端需补）

| 缺口 | 后端现状 | 补法 |
|---|---|---|
| **G1 compScore/compRank 综合排名** | 后端采集 `providers.py:986-989` 已有 `rank/compRank`（按 **avgRankNum 注意力**排序）；前端 `ComprehensiveRankEngine` 自算**五维综合** compScore/compRank（同名字段不同口径） | 后端移植 `compute_comprehensive_ranks`（五维：avgRankNum 反/zljzb/fundPenetration/turnoverRate/turnover 加权）→ 快照/analyze 产出 compScore/compRank + 入库；前端删自算改消费 |
| **G2 displayStatus 状态分类** | 后端只产 `observation.synergy.state`（启动确认/主升确认/风险升级/退潮/存疑/noData）+ 各维 `signalTier` + `strategy.candidateTier` + `meta.sampleStatus` | 后端生产 `displayStatus`（基于 synergy.state + candidateTier + sampleStatus + 资金/量能 signalTier 组合），入库；前端 `getRankTrendDisplayStatus` 改纯 label 映射 |
| **G3 市场分位 P50/70/85** | 后端无 | 后端计算全市场 turnover/volumeRatio/turnoverRate 分位，供 statusClassifier/量能判定 |
| **G4 observation 入库** | analyze 实时算 observation，未持久化 | 快照/analyze 结果持久化到 MongoDB（分析结果字段），前端读库（消除"每次实时算"与"入库稳定值"差异） |

## 3. 分阶段实施

### 阶段 1（已部分）：rank percentile 权威化
- 完成：`backend/api/ranktrend_routes.py` 当前帧 percentile 复用权威历史帧（commit `990c69d`）
- 测试：`tests/test_api_current_frame_authoritative.py`（当前帧 percentile 不随前端 rank 漂移）✅

### 阶段 2（G1）：综合排名后端化
- 后端：移植 `compute_comprehensive_ranks` 到 `backend/analysis/ranktrend/`（或采集层），
  产出 `compScore/compRank`（权威）+ 入库；
- 前端：删 `ComprehensiveRankEngine` 自算，行情列表"综合排名"列改消费后端 `compRank`；
- 测试：后端单测（五维排序与前端一致/权威）+ 前端消费测试 + golden 回归。

### 阶段 3（G2+G3）：状态分类 + 市场分位后端化
- 后端：生产 `displayStatus`（含市场分位 P50/70/85）+ 入库；
- 前端：`getRankTrendDisplayStatus` 改消费后端 `displayStatus`（纯 label 映射），删前端自算
  （percentile/status 分支）；`isHotAttention` 改消费后端 `meta.currentRank/currentPercentile`；
- 测试：后端 displayStatus 单测 + 前端映射测试 + golden。

### 阶段 4（G4）：observation 持久化入库
- 后端：analyze/快照结果持久化（MongoDB 分析结果字段），前端读库；
- 测试：入库/读库一致性。

## 4. 验收标准（每阶段）
- 前端**零计算结论值**（grep 前端自算逻辑为空）；
- 后端 golden：相同输入 → 相同显示值（入库稳定，不随刷新漂移）；
- golden 回归全绿 + 相关测试通过；
- 浏览器验收：非交易日多次刷新，四维/状态列不再漂移。

## 5. ⚠️ 未决分叉（需用户确认，阻塞阶段 2 改法）
**行情列表"综合排名"列语义**：后端将按 **avgRankNum（八平台注意力）** 或 **五维综合（compScore）**
生产唯一权威 `compRank`？
- **选项 A（注意力口径）**：后端现成（providers.py:986-989），但"综合排名"列会从"五维综合"变
  "八平台注意力排名"，**改变该列排序语义**；
- **选项 B（保持五维综合）**：后端需移植五维 compScore（G1 完整），"综合排名"列语义不变，
  但后端与 avgRankNum 双口径并存（后端为 golden）。
默认**暂按 B**（保留产品语义、后端为 golden）——待用户确认后进入阶段 2。
