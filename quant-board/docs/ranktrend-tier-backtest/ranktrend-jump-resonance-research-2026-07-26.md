# RankTrend Jump 与共振强度研究（2026-07-26）

## 结论

1. 当前 Jump 的方向语义正确：最近一次越过阈值的百分位事件上升为 `buy`，下降为 `sell`。本次误导来自前端漏传当前帧，不是阈值定义本身。
2. 当前共振分数不适合直接作为交易强度：`final`、`direction`、`acceleration` 与 Jump 都来自同一排名路径，线性累加会重复计权；它没有横截面基准、路径持续性、反转惩罚或样本质量上限。
3. 共振已作为 Dragon Board 的 live-only 观察信号接入唯一 `finalSignal`、候选池观察标记和 tooltip；不进入 QuantBoard golden/replay，不启动回测、参数搜索或自动下单。交易池不重复使用该 final 的连续评分，只保留独立执行证据。

## 已验证事实

- 数据集：`dragonboard_live`，`snapshot_type=half_hour`，区间 2026-03-27 至 2026-07-23，2290 帧、492580 条股票行。
- 002298 在 2026-07-23 的历史末三帧为 `97/233 -> 175/240 -> 165/232`（百分位 `58.8 -> 27.5 -> 29.3`）。旧序列最后事件为 `sell`；并入当前约 `11/209`（95.2）后最后事件为 `surge 55.4`，方向为 `buy`。
- MongoDB 历史行中的旧 `jumpDirection=sell` 是漏当前帧版本写入的历史字段，不可用作新逻辑的标签或回测真值。
- 研究 API 已能访问 MongoDB；一次 8-trial 同步 TPE 请求超过 120 秒未返回，未取得 `run_id`，因此本文件不把它当回测结果。

## 候选口径

Jump 保留为“事件检测”，不要兼任全部强度定义：

```text
jump_direction = latest_threshold_event.direction
jump_size      = latest_event.magnitude
jump_freshness = exp(-bars_since_latest_event / 3)
```

新增独立的排名共振特征，并按方向分别统计：

```text
relative_momentum = short_percentile_change - market_median_short_change
acceleration      = short_change - mid_change / (mid_bars / short_bars)
persistence       = directional_bars / observed_bars
reversal_penalty  = direction_switches + drawdown_from_recent_peak
quality_cap       = min(1, valid_bars / required_bars) * data_freshness
```

候选分数只组合尽量正交的维度，不再把同源置信度相加：

```text
resonance_buy = quality_cap * clamp(
    0.35 * normalized(relative_momentum)
  + 0.25 * normalized(acceleration)
  + 0.20 * persistence
  + 0.20 * normalized(jump_size * jump_freshness)
  - 0.20 * reversal_penalty,
  0, 1)
```

`MACD`、价格和资金流保留为独立确认/风险门槛，不作为上述排名共振的重复加分项。资金流若只来自 `estimated_l1`，只能观察，不能进入正式结论。

## 实盘观察口径

- 每个交易日人工检查 MongoDB 快照的帧数和股票行数，并核对 `stock_name` 且 `Active=true` 的白名单是否生效；采集器只负责保存和打标，不以质量门禁丢弃已采数据。
- 观察 `002298` 等代表性个股的六因子、`finalSignal`、候选池观察标记及实际排名路径是否一致；样本不足必须显示 `hold / 0`，不回退旧 final。
- 记录反向 Jump、排名反转和数据缺失时的解释字段，确认 tooltip、候选池和 `finalSignal` 始终读取同一份 `rankTrend.resonance`。
- 交易池继续按 Jump、MACD、方向、加速度和零轴穿越等独立执行证据决策；不将新的 final 或共振分数重复加权进交易评分。

## 参考

- Jegadeesh, N. and Titman, S. (1993), Returns to Buying Winners and Selling Losers. *Journal of Finance*. DOI: `10.1111/j.1540-6261.1993.tb04702.x`。
- Asness, C., Moskowitz, T. and Pedersen, L. (2013), Value and Momentum Everywhere. *Journal of Finance*. DOI: `10.1111/jofi.12007`。

上述文献支持使用横截面相对动量和时间序列持续性，但研究对象是收益/价格因子；热榜排名是注意力代理变量，必须以本项目 MongoDB 样本单独验证，不能直接套用其参数。
