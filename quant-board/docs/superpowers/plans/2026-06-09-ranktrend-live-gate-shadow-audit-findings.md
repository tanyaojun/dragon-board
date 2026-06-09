# RankTrend Live Gate Shadow Audit Findings

日期：2026-06-09

## 结论先行

- 最近一周 `dragonboard_live / half_hour / 2026-06-03 ~ 2026-06-09` 的审计结果表明，`ranktrend_early_big_move_v3_lifecycle_fusion` 当前 live 前置门槛确实存在“召回偏保守”问题，但不是所有高频失败项都适合从硬过滤降级。
- 真正有证据支持“从硬 veto 改成候选召回 + 二次排序”的，优先是：
  - `jump_confidence`
  - `tier_gate`
- `change_lt_6` 只适合降级成排序惩罚项，不适合单独直接放开。
- `jump_direction_buy`、`jump_sustained`、`short_mid_long_positive`、`acceleration_ge_10` 更像主结构确认，不建议直接从硬 gate 降级。

## 审计范围与证据

- 数据集：`dragonboard_live`
- 快照口径：`half_hour`
- 时间窗口：`2026-06-03 ~ 2026-06-09`
- 重点交易日：`2026-06-09`
- 审计产物：
  - [focus report](d:/dragon-board/quant-board/data/reports/ranktrend-live-gate-focus-2026-06-03_2026-06-09.json)
  - [full report](d:/dragon-board/quant-board/data/reports/ranktrend-live-gate-full-2026-06-03_2026-06-09.json)

执行命令：

```powershell
.\.venv\Scripts\python.exe -m backend.cli audit-ranktrend-live-gates `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --start-date 2026-06-03 `
  --end-date 2026-06-09 `
  --focus-code 600186 `
  --focus-code 002156 `
  --output d:\dragon-board\quant-board\data\reports\ranktrend-live-gate-focus-2026-06-03_2026-06-09.json
```

补充说明：

- `full report` 由 `RankTrendLiveGateAuditService` 直接生成，用于统计最近一周全部 focus 样本的失败分布与 shadow recall 情况。
- `meta.accDeltaPresentRatio=0.0`，说明当前 live 数据里 `accDelta` 基本缺失，`acceleration gate` 实际主要依赖 `acceleration`。

## 最近一周总览

- `focusCount=10898`
- `baselineTriggeredCount=0`
- `2026-06-05`：仅 `recall_first=7`
- `2026-06-08`：仅 `recall_first=2`
- `2026-06-09`：`recall_first=5`，其中 `delta_10=1`

最近一周 baseline miss 的主失败项：

- jump 层：
  - `jump_event_is_jump`: 3158
  - `jump_direction_buy`: 2659
  - `jump_confidence`: 2191
  - `jump_sustained`: 2039
  - `technical_direction_buy`: 325
  - `macd_golden`: 203
- fusion 层：
  - `short_mid_long_positive`: 9529
  - `acceleration_ge_10`: 1036
  - `sample_quality_ok`: 162
  - `tier_gate`: 98
  - `change_lt_6`: 68

判断原则：

- 高频失败不等于应该放宽。
- `jump_direction_buy`、`jump_sustained`、`short_mid_long_positive` 这类项虽然出现很多，但更像主结构没站稳，不属于“只差一脚”的召回问题。

## 2026-06-09 重点样本

当天 baseline 全部未触发，但 shadow 只召回了 5 个样本：

| 时间 | 代码 | 名称 | baseline jump | baseline fusion | 首个 jump 失败 | 首个 fusion 失败 | 召回变体 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10:00 | 600176 | 中国巨石 | true | false | - | `change_lt_6` | `recall_first` |
| 10:00 | 600183 | 生益科技 | false | false | `jump_confidence` | `change_lt_6` | `recall_first` |
| 13:30 | 300433 | 蓝思科技 | false | true | `jump_confidence` | - | `delta_10`, `recall_first` |
| 14:30 | 300975 | 商络电子 | true | false | - | `change_lt_6` | `recall_first` |
| 14:30 | 600111 | 北方稀土 | false | false | `jump_confidence` | `tier_gate` | `recall_first` |

其中最干净的证据样本：

- `300433 蓝思科技 13:30`
  - baseline fusion 已通过
  - 只差 `jump_confidence`
  - `delta_10` 单独就能召回
  - 这是最强的 `jump_confidence` 过严证据
- `600111 北方稀土 14:30`
  - 主要卡在 `jump_confidence + tier_gate`
  - 其他 fusion 结构基本成立
  - 这是 `tier_gate` 过严的较干净证据
- `600183 生益科技 10:00`
  - 同时卡在 `jump_confidence + change_lt_6`
  - 说明 `change_lt_6` 更适合做排序惩罚，而不是单独直接放开

## 为什么 600186 / 002156 不是“单条 gate 误杀”的好证据

### 600186 莲花控股

`2026-06-09` 共命中 10 帧，失败模式很稳定：

- jump 首个失败：`jump_confidence` × 10
- fusion 首个失败：
  - `acceleration_ge_10` × 7
  - `short_mid_long_positive` × 3

这说明它不是“只差一条硬 gate”的干净样本，而是：

- jump 层置信度不过
- fusion 层动量结构也没稳定站住

因此不适合拿它作为“放宽单条 hard veto”的主证据。

### 002156 通富微电

`2026-06-09` 共命中 10 帧，失败模式也比较一致：

- jump 首个失败：`jump_sustained` × 10
- fusion 首个失败：
  - `short_mid_long_positive` × 7
  - `acceleration_ge_10` × 3

这说明它的问题不在“某个排序项过严”，而在：

- jump 结构本身没有持续成立
- fusion 动量结构也没有同步确认

因此它更像“主结构未确认”，不应作为降低硬 gate 的核心依据。

## 推荐的 hard veto 降级候选

### 候选 1：`jump_confidence`

建议：

- 不直接删掉
- 从 hard veto 改成 `candidate_recall_flag`
- 进入 shadow 候选池后再做二次排序

证据：

- `300433 蓝思科技 13:30` 是最干净样本
- `600111 北方稀土 14:30`、`600183 生益科技 10:00` 也都说明这条门槛偏紧

排序建议：

- `jump_confidence >= 90` 仍然最高权重
- `80 <= jump_confidence < 90` 允许召回，但在排序上明显降级

### 候选 2：`tier_gate`

建议：

- 保留 baseline 不变
- 在 recall-first 候选池中允许 `tier_gate` 失败但打负分

证据：

- `600111 北方稀土 14:30` 是较干净样本
- 当天它的 fusion 结构大体成立，只是 tier 不够强

排序建议：

- `A_MAIN` 保持最高优先级
- `B_IGNITION` 且 `mid >= 20 + zeroCross=buy` 次之
- 其他 tier 不直接 veto，但需要更强的 jump/technical 佐证才能前排

### 候选 3：`change_lt_6`

建议：

- 不直接从 hard gate 删除
- 更适合降级成排序惩罚项

原因：

- `600176`、`300975` 被召回时，通常还伴随其他质量问题
- `600183` 也不是纯 `change_lt_6` 单点问题

更稳的做法：

- `change >= 6` 不直接 veto
- 但在候选排序里显式扣分，防止追高

## 当前不建议放开的项

- `jump_direction_buy`
- `jump_sustained`
- `short_mid_long_positive`
- `acceleration_ge_10`

原因：

- 这些项更接近“主结构确认”而不是“边缘排序条件”
- 一旦直接降级，很容易把大量并不成熟的盘中票召回进来，噪音会明显放大

## 下一步最合适的方案

当前最稳妥的是研究链先行，不动 live 主链：

1. 保持 baseline live gate 不变。
2. 在 shadow audit / report 层新增 `soft recall score`。
3. 只把 `jump_confidence`、`tier_gate`、`change_lt_6` 作为“候选召回 + 二次排序”实验项。
4. 用最近一周继续观察：
   - 召回数增加多少
   - 真实强票命中率是否改善
   - 噪音票是否明显上升

## 验证证据

相关测试通过记录：

- `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_live_gate_shadow_audit.py -q`
- `.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -q`

本轮 findings 只沉淀审计结论，不修改 live 自动入池逻辑。

## 后续研究方向

本文件记录的是第一轮 live gate shadow audit 发现，主要回答 hard veto 分布和典型阻断点；它不等同于最终热榜买点归因结论，也不直接推出 live 自动入池规则。

后续研究主线以 `quant-board/docs/superpowers/specs/2026-06-09-ranktrend-hotlist-recall-research-design.md` 为准：

- `jump confidence=90` 是否过严，需要通过 `confidenceThresholdScan` 单独做 baseline jump 定义下的区间扫描。
- `jumpDeltaPct`、`delta_10`、`delta_12_5`、`recall_first` 等会改变 jump 定义或 replay 结果的研究，必须单独进入 `jumpDefinitionReplaySummary`，不能和 confidence 阈值混成一个“最优参数”。
- `fusion` 误伤归因必须区分 `true_gate_block`、`field_missing`、`replay_missing`、`candidate_tier_side_effect`、`sample_quality_side_effect`，并按 `candidateTier`、`cycle.stage`、`cycle.decision.action`、`sampleQuality.status` 控制混杂项。
- 当前“扩展样本”只代表 `dragonboard_live` 最近一周热榜覆盖范围，不代表全市场扫描。
