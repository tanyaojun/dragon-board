# Jump 当前帧修复计划

**目标：** 让 RankTrend Jump 检测与本轮分析、变化%使用同一条包含当前帧的排名序列。

**范围：** 仅修复 `RankTrendAnalyzer` 到 `RankTrendSignalService` 的序列传递；不调整 `delta=15`、共振评分、候选池或交易规则。

1. 红测：固定历史百分位 `58.8, 27.5, 29.3` 与当前 `95.2`，验证信号层传入完整序列；验证：目标 Vitest 用例先失败。
2. 实现：分析器缓存本轮完整 ranks/percentiles，并以只读方法提供给信号层；`evaluateJumpSignal` 同时取得完整 ranks；验证：目标用例通过。
3. 回归：运行 RankTrend 测试、类型检查与全量前端测试；验证：全部退出码为 0。
4. 研究：在 QuantBoard 使用 MongoDB `half_hour` 数据比较现有 Jump 与候选定义，保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`，不直接改实盘参数。
