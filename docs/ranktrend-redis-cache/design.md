# RankTrend Redis Cache Design

## Goal

用 Redis 稳定 RankTrend、量比和热度相关的历史输入读模型，减少行情列表【变化%】和【置信度】在刷新阶段时隐时现。SQLite 仍是正式事实源，Redis 只做可丢弃、可重建的 read-through cache。

## Current Findings

- 本机 Redis 服务存在且运行中：Windows Service `Redis`，`Automatic`，监听 `127.0.0.1:6379`。
- `redis-cli` 不在 PATH，自动化测试不能依赖 `redis-cli`。
- RankTrend 的【变化%】和【置信度】依赖当前榜单和历史 frame bundle 的 `hotlist`，不是裸 `snapshot_frames` 表。
- 量比依赖历史日级/分时 `stock_rows.volume` 和当前成交量、交易分钟进度，不能长期缓存最终 `volumeRatio`。
- 热度依赖当前 merged stock 的平台排名、资金、量比、题材和涨停扩展，不能把最终 `hotness` 当跨轮次权威缓存。
- UI 闪烁根因有两层：后端快照读慢会拖慢 `signal-enriched`；前端 `base-merge` 到 `signal-enriched` 的两阶段发布会产生中间态。

## Architecture

### Backend Cache

QuantBoard 后端新增 `SnapshotRedisCache`：

- Redis-first：命中 Redis 直接返回缓存响应。
- Miss：调用现有 repository 从 SQLite/归档读模型读取，成功后写 Redis。
- Fail-open：Redis 连接、读写、反序列化失败时直接回 SQLite，不影响 API。
- 不改变事实源：GET miss 后仍只从现有 repository 读取；`backup_only` ingest 不回填 Redis。

缓存覆盖正式快照读 API：

- `GET /api/snapshots/frames`
- `GET /api/snapshots/records`
- `GET /api/snapshots/stock-rows`
- `GET /api/snapshots/sector-rows`

缓存的是接口响应读模型，不缓存 `rankChange`、`finalConfidence`、`volumeRatio`、`hotness` 这类最终计算值。

### Key Namespace

Redis 与 TradingAgents、HelloBigA 等项目共享时必须隔离。Key 使用可配置前缀：

```text
{prefix}:snapshot:{resource}:v1:{resolved_dataset_id}:{query_hash}
```

默认前缀：

```text
hellobiga:dragon-board:local
```

`query_hash` 来自规范化后的完整查询参数。CSV 参数排序去重，空值规则固定，必须使用 resolved dataset id。

### Reverse Index

为避免范围查询缓存旧列表，写 response key 时同步登记反向索引：

```text
{prefix}:snapshot:index:dataset:{dataset_id}
{prefix}:snapshot:index:date:{dataset_id}:{snapshot_type}:{trading_date}
{prefix}:snapshot:index:snapshot:{dataset_id}:{snapshot_id}
```

`POST /api/snapshots/ingest` SQLite commit 成功后按相关索引删除 response keys。不能只按 dataset 粗删作为常规路径；粗删只作为失效元数据不足时的兜底。

### Frontend Stability

前端在 `base-merge` 阶段必须显式继承上一轮 RankTrend 展示字段：

- `rankTrend`
- `rankTrendCoverageWarning`
- `rankChange`
- `finalSignal`
- `finalConfidence`
- `macdCross`
- `directionConfidence`
- `accelerationConfidence`
- `crossConfidence`

`signal-enriched` 有新结果时覆盖；没有新结果时保留旧值并标记 stale/coverage warning，不清空 UI 字段。

## Configuration

```text
QUANT_BOARD_REDIS_URL=redis://127.0.0.1:6379/0
QUANT_BOARD_REDIS_KEY_PREFIX=hellobiga:dragon-board:local
QUANT_BOARD_SNAPSHOT_CACHE_ENABLED=1
QUANT_BOARD_SNAPSHOT_CACHE_TTL_SECONDS=300
QUANT_BOARD_SNAPSHOT_EMPTY_CACHE_TTL_SECONDS=10
QUANT_BOARD_SNAPSHOT_CACHE_CONNECT_TIMEOUT_SECONDS=0.2
QUANT_BOARD_SNAPSHOT_CACHE_SOCKET_TIMEOUT_SECONDS=0.2
```

## Acceptance Criteria

- 同参数 `frames` 请求第一次走 repository，第二次 Redis 命中。
- `records`、`stock-rows`、`sector-rows` 同样支持 hit/miss。
- SQLite ingest 成功后，相关 dataset/date/snapshot 索引下缓存失效。
- `backup_only` ingest 不回填 Redis。
- Redis 不可用时 API 仍回 SQLite 并返回正常响应。
- 不同 namespace 下相同 dataset/snapshot 查询互不影响。
- 前端 `base-merge` 不再清空已有【变化%】和【置信度】展示字段。
