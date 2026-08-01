# RankTrend 三轨观察面板设计

## 目标

主行情表并列展示三套独立观察体系，避免用“共振强度”代替排名趋势技术信号和生命周期风险信号：

- `共振强度`：相对市场的排名路径共振强度。
- `排名趋势`：四项排名技术证据形成同向趋势的强度。
- `生命周期`：当前阶段的机会成熟度，并显式保留风险影响。

保留现有 tooltip 作为鼠标悬停快速结论；点击三个字段分别打开右侧观察舱的对应分析轨。

## 主表列调整

删除：

- `变化%`
- `跃迁度`

新增或保留：

| 列 | 建议宽度 | 单元格格式 | 点击行为 |
| --- | ---: | --- | --- |
| 共振强度 | 84px | `↑53%`、`↓61%`、`—5%` | 打开共振路径轨 |
| 排名趋势 | 84px | `↑72%`、`↓64%`、`—8%` | 打开技术结构轨 |
| 生命周期 | 96px | `点火 68%`、`扩散 86%` | 打开生命周期风险轨 |

买入/向上使用 A 股红色，卖出/向下使用绿色，观望使用灰色。生命周期使用阶段色：点火金、扩散红、拥挤橙、反转绿、冷却灰。

## 三项指标合同

### 共振强度

沿用现有 `resonanceAnalyzer` 合同，不修改计算公式：

```text
score = 100 * clamp(
    0.35 * positive(directionalMomentum)
  + 0.25 * positive(directionalAcceleration)
  + 0.20 * persistence
  + 0.20 * jumpFreshness
  - 0.20 * reversalPenalty,
  0,
  1
)
```

方向来自相对动量、加速度、路径持续性和反向 Jump 覆盖规则。

### 排名趋势强度

复用现有四项技术信号连续分和运行时权重：

```text
technicalNetScore =
    directionScore * directionWeight
  + accelerationScore * accelerationWeight
  + zeroCrossScore * crossWeight
  + macdRawScore * macdWeight

rankTrendStrength = round(abs(technicalNetScore) * 100)
```

默认权重为方向一致性 30%、多周期加速度 25%、零线交叉 20%、MACD 25%。方向继续使用现有共识合同：至少两项同向、反向不超过一项，并达到买入 `+0.12` 或卖出 `-0.12` 阈值；否则为观望。

该百分比表示“同向技术强度”，不是统计置信概率。冲突信号通过有符号加权自然抵消。

### 生命周期机会成熟度

```text
lifecycleOpportunity = round(100 * clamp(
    0.35 * stageFitness
  + 0.25 * pathCommitment
  + 0.20 * momentumConfirmation
  + 0.20 * riskSafety,
  0,
  1
))
```

阶段适配度：

| 阶段 | stageFitness |
| --- | ---: |
| expansion / 扩散 | 1.00 |
| ignition / 点火 | 0.80 |
| crowded / 拥挤 | 0.35 |
| cooling / 冷却 | 0.20 |
| reversal / 反转 | 0.00 |

其余因子：

- `pathCommitment`：复用现有 `cycle.metrics.rankPathCommitment`，范围 `0..1`。
- `momentumConfirmation`：复用现有生命周期 `midLongCommitted` 的证据尺度，并强调中周期确认：

  ```text
  shortConfirmation = clamp(momentum.short / 15, 0, 1)
  midConfirmation = clamp(momentum.mid / 15, 0, 1)
  accelerationConfirmation = clamp(momentum.acceleration / 8, 0, 1)

  momentumConfirmation =
      0.30 * shortConfirmation
    + 0.45 * midConfirmation
    + 0.25 * accelerationConfirmation
  ```

  不得使用买卖票数替代连续值。
- `riskSafety = 1 - risk.pressure`。

生命周期 `veto` 不覆盖或清零实际成熟度，只显示明确警示及原因，保留所有底层证据。

## Tooltip

悬停三个指标中的任意一个，显示同一份快速 tooltip：

1. 观察结论：三项当前结果。
2. 共振路径：相对市场、速度、持续性、Jump、反转惩罚和市场中位数。
3. 技术结构：MACD、方向一致性、多周期加速度和零线交叉。
4. 阶段与风险：阶段、机会成熟度、过热和资金背离。
5. 候选池：当前准入状态与第一失败原因。

候选池说明仅存在于 tooltip，不进入观察舱。

## 右侧观察舱

观察舱为覆盖式右侧抽屉：桌面宽约 `720px`，最大不超过视口宽度 `46%`；窄屏接近全宽。打开时不改变主表列宽、排序和滚动位置。

交互：

- 点击 `共振强度`：打开 `resonance` 轨。
- 点击 `排名趋势`：打开 `technical` 轨。
- 点击 `生命周期`：打开 `lifecycle` 轨。
- 抽屉打开时点击另一股票或另一指标，直接切换股票和轨道。
- 关闭按钮或 `Esc` 关闭；点击抽屉外部不关闭。
- 抽屉内允许切换三轨。

顶部仅显示股票和三项观察摘要，不显示候选池：

```text
久其软件 002279
共振 ↑53%   技术 ↑72%   生命周期 点火 68%
```

### 共振路径轨

- 最近 9 帧关注度百分位折线（共振显示窗口固定 9 帧，与 `MIN_SERIES_POINTS=9` 对齐）。
- 同帧市场中位路径虚线。
- Jump 事件标记。
- 相对动量、加速度、持续性、Jump 新鲜度和反转惩罚贡献条。

### 技术结构轨

- MACD DIF、DEA 和柱体。
- 金叉/死叉位置。
- 方向一致性、多周期加速度、零线交叉和 MACD 四项连续强度矩阵。

### 生命周期风险轨

- 冷却、点火、扩散、拥挤、反转阶段轨道。
- 机会成熟度四因子贡献。
- 过热风险和资金背离风险刻度及主要证据。

### 时间轴

底部保留证据时间轴，显示窗口按轨道分别设定（`OBSERVATION_WINDOW_BARS`）：

| 轨道 | 显示窗口 | 依据 |
| --- | ---: | --- |
| 共振路径 | 9 帧 | 短窗 3 / 中窗 8 / 路径持续性 8，最小可算 9 |
| 技术结构 | 22 帧 | MACD 与动量最小可计算窗口（当前默认 22） |
| 阶段与风险 | 15 帧 | 生命周期动量确认因子（mid 动量 + 加速度）可算窗口 |

默认选择最新帧。切换轨道时优先保留当前选中帧（同 frame key），超出新轨道窗口则回退到该轨道最新帧；各轨道在窗口内回看该帧及其历史前缀，未达本轨道可算窗口的早期帧按轨道单独降级并给出结构化原因。

## 数据边界

- 观察舱通过公开观察服务读取数据，组件不得直接调用后端 API。
- 不修改 `DataLayer` 职责，不写回候选池、交易池、快照或 RankTrend 当前结果。
- 当前帧三项结果必须与主表和 tooltip 一致。
- 历史风险必须使用对应帧的资金和量比字段，市场基准必须使用对应帧横截面数据。
- 缺字段时按轨道局部降级并显示结构化原因；不得把缺失静默转换为 0，不得阻止其他有效轨道展示。

## 验收

- 主表删除 `变化%`、`跃迁度`，三项指标并列且含义明确。
- 三个字段悬停显示同一 tooltip，候选池说明只在 tooltip 中。
- 三个字段点击分别打开正确轨道，切换股票不关闭抽屉。
- 排名趋势和生命周期分数可由公开因子回算。
- 当前帧主表、tooltip、观察舱数值一致。
- 历史帧不混用当前资金或当前市场基准。
- 缺失数据主动暴露，其他可用证据继续显示。
- 桌面和窄屏无溢出，浏览器无观察舱新增错误。

## 实现落地记录（2026-08-01 补充）

审查后对观察舱做了 6 项对齐修复：

1. **历史帧市场基准改为按帧真实横截面**：观察服务不再用当前内存股票列表近似，改为按观察窗口日期范围读取快照 stock rows，按 `avgRankNum` 升序重排计算每帧全市场关注度百分位，再取中位数；短周期变化只统计两帧都存在的股票。读取失败时降级并给出 `market_cross_section_unavailable`，不静默回退。
2. **生命周期轨增加 15-bar 可算窗口降级**：新增 `LIFECYCLE_MIN_SAMPLES=15`，低于该窗口的历史帧不产出 `observation.lifecycle`，并给出 `lifecycle_sample_insufficient` 结构化原因。
3. **技术结构轨补齐金叉/死叉位置标记**：MACD 图在 `cross=golden/death` 的帧位置渲染金叉/死叉标记点。
4. **生命周期阶段轨改为动态列**：移除硬编码 9 列，按轨道窗口帧数横向自适应并支持横向滚动。
5. **历史帧不再复用当前 regime**：历史帧按中性市场环境计算生命周期分层，并给出 `historical_regime_unavailable` 结构化原因，避免当前市场环境污染历史结论。
6. **历史帧 Jump 独立重算**：历史帧用该帧前缀调用 `detectRankJumps`（阈值 15）独立检测，不再用当前分析的事件索引近似，并把 `jump` 写回该帧供共振轨标记。

7. **市场横截面读取瘦身（fields 投影）**：修复“`market_cross_section_unavailable: signal is aborted without reason`”——原实现按日期范围整批读取全字段 stock rows（每行 107 字段、约 23KB），观察窗口 2 千多行即约 21.8MB，超过前端 15s 读超时被中止。`GET /api/snapshots/stock-rows` 新增 `fields` 投影参数，观察服务只请求 `tradingDate/slotTime/code/avgRankNum` 四个字段，响应缩至约 300KB；Mongo/SQLite 两个仓库与 Redis 缓存 key 同步支持。读取失败时仍按原设计降级并暴露 `market_cross_section_unavailable`。

以上修复均有邻近 Vitest 覆盖（`RankTrendObservationService.test.ts`、`RankTrendObservationPanel.test.ts`），`observation.lifecycle` 类型调整为可选以支持生命周期轨独立降级；后端投影行为由 `quant-board/tests/test_mongo_repository.py` 与 `test_quant_board.py` 覆盖。
