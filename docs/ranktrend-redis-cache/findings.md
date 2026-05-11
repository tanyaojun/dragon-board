# RankTrend Redis Cache Findings

## Redis Environment

- Windows 服务名：`Redis`
- 状态：`Running`
- 启动类型：`Automatic`
- 监听：`127.0.0.1:6379`
- `redis-cli` 不在 PATH，测试不应依赖 CLI。

## Backend Review Findings

- Redis cache 可行，但必须是 read-through cache，SQLite 仍是事实源。
- 失效不能只按 dataset 或 snapshot_id 粗删；范围查询需要反向索引。
- `backup_only` 写入不能刷新 Redis，因为 GET 正式读口仍以 SQLite 为主。
- `stock-rows` / `sector-rows` 可能返回 `sqlite`、`parquet_archive` 或 `mixed`，archive/restore 相关操作也需要后续纳入失效。
- Key 必须使用 resolved dataset id，不能用请求里的空 dataset id。

## Frontend Review Findings

- Redis 不能替代前端中间态保留策略。
- 当前常规 refresh 会通过 existingMap 浅拷贝保留旧字段，但这不是显式合同。
- 新入榜、离榜再回榜、`updateStockSignals(rankTrend: null)` 仍有清空风险。
- `rankChange/finalConfidence/volumeRatio/hotness` 不应作为长期最终值缓存。

## Calculation Inputs

- RankTrend：当前 rankMap + 历史 frame bundle hotlist。
- 量比：当前 volume + 历史 daily/intraday stock rows volume + 当前交易分钟进度。
- 热度：当前 merged stock 的平台排名、覆盖度、资金、换手、量比、题材/涨停扩展。

