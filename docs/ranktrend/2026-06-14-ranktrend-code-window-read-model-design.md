# RankTrend Code-Window Read Model Design

**Goal:** 让 RankTrend 按 `datasetId + snapshotType + code` 读取单票历史窗口，而不是按最近全局快照帧截断样本。

**Architecture:** RankTrendAnalyzer 先拿当前榜单的最新 rankMap，再按每个 `code + snapshotType` 向 QuantBoard 读取该票自己的历史 bars。后端读模型返回的是“按 code 分组的历史序列”，前端/分析器按特征窗口直接计算 MACD、动量和零线交叉；样本质量只看该票实际拿到的 bars 数，不再受最近 50 个全局帧影响。

**Tech Stack:** TypeScript、Vue 3、FastAPI、SQLite/MongoDB 仓库层、Vitest、Pytest。

---

## 现状问题

- 当前 `RankTrendAnalyzer` 取历史时，实际依赖的是最近 50 个全局快照帧。
- 这会让“最近 50 帧里是否命中该票”错误地替代“这只票自己的历史 bars 是否足够”。
- 结果是：像 600601 这种库内有 189 条 `half_hour` bars 的票，仍可能只拿到 6 条有效样本。
- 样本质量、MACD 可计算性、稳定观察窗口被混成同一个门槛。

## 设计目标

1. 历史读取以 `code + snapshotType` 为主键。
2. 数据获取按“单票历史窗口”进行，不再按全局 frame 数截断。
3. 区分两类阈值：
   - `minComputableBars`：够不够算出值
   - `stableBars`：够不够进入稳定观察和入池判断
4. 当 bars 已经足够计算时，必须产出 MACD/动量/零线交叉结果。
5. 样本质量失败时返回结构化原因，不允许静默吞掉或假装没算。

## 建议口径

### 1. 单票历史窗口

每个 code 都独立取历史：

```text
key = (datasetId, snapshotType, code)
```

读取结果是该票最近 N 条快照中的 rank 序列，而不是最近 N 个全市场 frame 的交集。

### 2. 统一窗口策略

当前分析链可用一个“最大所需窗口”驱动一次取数：

- MACD：`minComputableBars = macdSlow`
- 动量：`minComputableBars = max(momentumPeriods) + 1`
- 零线交叉：`minComputableBars = 2`

稳定观察窗口建议单独定义：

- MACD：`stableBars = 30`（约 2 个交易日的半小时线，确保 EMA 序列收敛）
- 动量：`stableBars = 50`（需覆盖最长动量周期 21 + 足够的历史对比基线）
- 零线交叉：`stableBars = 8`（覆盖 DIF/DEA 金叉死叉的最小确认窗）

以上数值与 `src/services/rankTrend/utils.ts:getTechnicalMinSamples` 现有硬编码下限 `30` 对齐，stableBars 取其与各特征所需窗口的最大值。单票最终请求窗口取这些稳定窗口的最大值。

### 3. 计算与稳定分离

RankTrendAnalyzer 里要明确两件事：

- `bars >= minComputableBars` 时，功能必须能算出值
- `bars < stableBars` 时，结果可以降级，但不能把“可计算”伪装成“算不出”

样本质量建议基于：

- 实际 bars 数
- 是否覆盖各特征的稳定窗口
- 是否发生回退 / 截断 / 缺失

### 4. 后端读模型

QuantBoard 现有 `rank-series` 读口需要改成按 code 返回历史序列，支持：

- `datasetId`
- `snapshotType`
- `codes`
- `windowBars`
- 可选日期和 capture mode 过滤

返回值建议以 code 为主键，包含：

- `code`
- `bars`
- `totalCount`
- `latestSnapshotId`
- `latestTradingDate`
- `latestSlotTime`

这样 RankTrendAnalyzer 不再需要先读全局 frames 再筛 code。

### 5. 前端分析链

RankTrendAnalyzer 的职责变成：

- 读当前榜单的最新 rankMap
- 按 code 拉历史窗口
- 用每个 code 自己的历史序列计算技术信号
- 把 sampleQuality 写回 stock row

`technicalSignalAnalyzer`、`jumpDetector`、`resultComposer` 的公式不改，只改喂进去的历史窗口来源。

## 非目标

- 不改 RankTrend 的信号公式本身
- 不改 candidate tier 规则
- 不改 Jump 的方向语义（`jumpDetector`、`jumpSignalService` 的公式和阈值保持不变）
- Jump 信号链路（`RankTrendSignalService`、`jumpDetector`、`jumpSignalService`）的调用方需适配新的 per-code 历史窗口入参，但不改变其内部计算逻辑
- 不新增新的交易信号
- 不把回测、优化或策略默认值塞回 Dragon Board

## 影响面

- `src/services/RankTrendAnalyzer.ts`
- `src/services/apiService.ts`
- `src/services/snapshot/types.ts`
- `quant-board/backend/data/repository.py`
- `quant-board/backend/data/mongo_repository.py`
- `quant-board/backend/main.py`
- RankTrend 相关测试

## 验收标准

1. 600601 在当前库内有足够 bars（≥189 条 `half_hour`）时，按 code 读取历史窗口可以拿到连续最近 bars，数量不受最近 50 个全局帧限制。
2. MACD 在 bars ≥ `macdSlow`（当前默认 26）时一定产出非零 DIF/DEA/histogram 值；`cross` 字段按金叉/死叉实际穿越状态判定。
3. 样本质量只反映该票自己的历史覆盖（实际 bars 数 vs 各特征所需窗口），不再反映最近 50 个全局 frame 的命中数。
4. 旧的 RankTrend 计算结果在单票 bars ≥ `getTechnicalMinSamples(config)` 时，技术指标数值（MACD DIF/DEA/histogram/cross、动量 rawScore/signal）与改造前一致（差异 < 1e-6）。
5. 单票 bars 不足 `minComputableBars` 时返回结构化降级原因（`sampleQuality.reason`），不静默产出全零值。
6. 后端 `/api/ranktrend/rank-series` 响应同时包含 `series`（per-code 窗口）和 `frames`（兼容现有消费方），且 `series` 中每个 code 的 bars 按时间升序排列。

## 测试策略

- 后端：补 repo / API 用例，验证按 code 返回的历史序列是最近窗口而不是全局 frame 截断。
- 前端：补 `RankTrendAnalyzer` 用例，验证单票历史窗口足够时仍能计算出技术信号。
- 回归：用 600601 这类“库内 bars 足够但最近全局帧命中少”的票做样本，确认不再误判。
