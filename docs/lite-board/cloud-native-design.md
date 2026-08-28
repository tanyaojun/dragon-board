# Dragon Board Cloud Lite 设计方案

> 状态：设计基线 v1（2026-08-28）
> 
> 目标：将行情主页与五维信号部署到不依赖 MongoDB、Redis 和本地 Windows 行情桥的云服务器，并提供可安装的 Flutter Android/iOS 客户端。

## 1. 设计结论

采用“单 VPS、双核心进程、定时备份任务、SQLite 单写者、Flutter 原生客户端”的最小生产架构：

- 本机 QuantBoard：继续承担回测、因子研究、参数搜索和 golden 验证。
- 云端 Lite：承担热榜/行情/资金采集、五维信号计算、只读 API 和运行监控。
- Flutter：独立 Android/iOS 客户端，只消费版本化 HTTPS API，不复制信号算法。
- Nginx 或 Caddy：终止 TLS、认证前置、限流和安全响应头。
- SQLite：唯一云端结构化事实库和查询索引；Redis、MongoDB、IndexedDB 不进入云端运行链路。
- 对象存储：保存 SQLite 在线备份、raw/derived 对象归档和恢复校验清单，防止 VPS 磁盘成为唯一副本。

旧方案 `docs/lite-board/refactor-plan.md` 作废，仅保留为历史审计材料。

## 2. 目标与非目标

### 2.1 目标

1. 手机端能查看最新行情主页、综合排名和五维信号明细。
2. 云端采集失败、字段缺失、延迟和样本不足必须可见，不得伪造为零值或空成功。
3. 云端信号与本机 QuantBoard 固定 golden 版本可复现、可比较、可回滚。
4. API、采集器和数据库可在单台 Linux VPS 上自动重启和恢复。
5. Android APK/AAB 与 iOS TestFlight/私有分发使用同一 Flutter 代码库。

### 2.2 非目标

- 云端回测、优化、参数搜索、交易执行和 L2 行情。
- 云端运行 MongoDB、Redis、python-bridge 或 TdxL2Helper。
- 在 Flutter 客户端实现 RankTrend 或综合排名算法。
- v1 提供公开用户注册、社交功能和多租户权限体系。
- 将手机 App 当作可靠的后台定时任务或交易执行器。

## 3. 运行架构

```text
Flutter Android/iOS
        |
      HTTPS
        |
Nginx/Caddy: TLS + 认证 + 限流 + 安全头
        |
FastAPI API（单 worker、只读数据库）
        |                         |
SQLite（WAL，窄事实表）     本机对象仓库
        ^
        |
Collector（唯一写者、交易日历调度）
        |
八平台热榜 / 腾讯行情 / 资金源

Backup timer -> SQLite 在线备份 + 对象 manifest/对象归档 -> S3 兼容对象存储
```

### 3.1 进程边界

| 进程 | 权限 | 职责 |
|---|---|---|
| `dragon-lite-api` | SQLite 只读 | API、静态健康信息、信号投影 |
| `dragon-lite-collector` | SQLite 读写 | 采集、标准化、质量标记、写入、信号派生 |
| `dragon-lite-backup` | 读取备份副本 | 在线备份、哈希校验、上传和保留清理 |

API 和 collector 不共享必须持久化的进程内状态。所有 last-good 数据、源状态和信号状态均落盘。

### 3.2 部署边界

- API 和 collector 使用同一发布包，但由不同 systemd unit 管理。
- collector 必须有单实例锁；API 固定单 worker，避免多个内存缓存和 SQLite 写冲突。
- FastAPI 只监听 `127.0.0.1`；公网入口只能是 Nginx/Caddy 的 443 端口。
- VPS 使用非 root 用户、独立数据目录和最小文件权限。
- systemd、日志轮转、防火墙、TLS 和备份均属于 v1 必需项，不是可选增强。

## 4. 数据采集与一致性

### 4.1 采集 run

每个采集槽位有唯一 `run_id`，并使用 Asia/Shanghai 交易日历：

1. 并行请求八个平台热榜；
2. 对热榜代码去重、规范化并保留平台排名事实；
3. 批量拉取行情和资金，记录各源时间、覆盖率和错误；
4. 计算 `avgRankNum`、`compScore`、`compRank`；
5. 原始响应和规范化大对象先写入对象仓库并完成 fsync、大小和 SHA-256 校验，再在一个小型 SQLite 事务中写入 frame、stock rows、source runs 和对象 manifest；
6. 事务提交后读取历史序列计算五维信号；
7. 信号核心字段和对象引用单独提交。信号计算失败不能回滚已经保存的原始 frame；未被 manifest 引用的对象进入可观测的 orphan 清理队列，不得立即删除。

采集器必须处理交易日、午休、节假日、槽位过期、重复运行和补采。所有时间同时保存调度时间、源时间和实际写入时间。

### 4.2 数据源适配器

每个来源实现统一接口：

```text
fetch(context) -> RawPayload
normalize(raw) -> NormalizedRows
health(raw/error) -> SourceHealth
```

适配器必须支持连接超时、读取超时、有限重试、指数退避、429/验证码识别、熔断、last-good 和源恢复。上游接口、字段语义、单位和授权方式必须用固定 fixture 测试，不以一次人工请求作为“已验证”。

同花顺资金源需要明确是网页资金流、估算 L1 还是合法 L2，输出中必须保留 `source`、`confidence`、`sessionDate` 和 `sourceTs`。如果云端 IP 无法稳定访问某一源，不能用空值冒充正常生产，必须显示该源不可用并保留其他来源数据。

## 5. SQLite 与对象仓库数据模型

SQLite 是单机小库，定位为“可筛选事实、幂等键、质量摘要和对象清单”，不是大对象仓库。禁止把完整热榜响应、完整行情响应、完整五维结果、历史 bundle 或无界诊断 JSON 写入 SQLite；任何 JSON 列都必须有明确上限（默认 16 KiB），超出部分外置。

对象仓库分为本机文件层和远端备份层：本机 `data/objects/` 用于低延迟读取，S3 兼容对象存储用于跨磁盘灾备。对象写入 `staging/` 后完成 fsync、字节数和 SHA-256 校验，再原子 rename 到 `raw/` 或 `derived/`；SQLite 只在最终路径存在后登记 manifest。rename 成功但事务失败会留下可审计 orphan，保留宽限期后才可清理。

### 5.1 SQLite 窄表

```text
frames
  id, dataset_id, snapshot_type, trading_date, slot_time,
  scheduled_ts, captured_ts, committed_ts, run_id,
  schema_version, engine_version, strategy_version, config_hash,
  capture_mode, quality_status, quality_summary_json,
  normalized_object_id, diagnostic_object_id,
  raw_object_count, derived_object_count

stock_rows
  frame_id, code, name, captured_ts,
  em_rank, ths_rank, kpl_rank, tdx_rank, xq_rank, cls_rank, tgb_rank, dzh_rank,
  platform_count, avg_rank_num, comp_score, comp_rank,
  price, change, volume, amount, volume_ratio, turnover_rate,
  pe, pb, total_market_value, circulating_market_value,
  zlje, zljzb, fund_penetration, high, low, open, pre_close,
  quality_mask, source_mask

source_runs
  run_id, source, requested_count, returned_count, coverage_ratio,
  started_ts, finished_ts, status, error_code, error_message, raw_object_id

signal_rows
  frame_id, code, signal_version,
  resonance_direction, resonance_score, resonance_tier,
  rank_trend_direction, rank_trend_score, rank_trend_tier,
  heat_direction, heat_score, heat_tier,
  volume_price_direction, volume_price_score, volume_price_tier,
  lifecycle_direction, lifecycle_score, lifecycle_tier,
  overall_status, compute_status, sample_quality_code,
  detail_object_id, compute_error_code
```

`quality_mask`、`source_mask` 使用受控枚举或位图，不用每行无界 JSON；字段缺失位置和完整诊断写入对象。`quality_summary_json` 只允许有界摘要，完整源状态从 `source_runs` 读取。

唯一约束必须包含 `dataset_id + snapshot_type + trading_date + slot_time`；股票行必须有 `(frame_id, code)` 唯一约束。建议对大表使用 `WITHOUT ROWID`（适用于复合主键表），并建立 `(dataset_id, snapshot_type, trading_date, slot_time)`、`(code, captured_ts)`、`(frame_id, comp_rank)` 索引；索引必须以实际查询计划和磁盘预算压测后冻结。

### 5.2 对象 manifest 与分块

```text
objects
  object_id, kind, dataset_id, run_id, frame_id,
  object_key, content_type, compression,
  logical_bytes, stored_bytes, sha256, schema_version,
  chunk_count, backup_batch_id, created_ts, retention_class, status

object_chunks
  object_id, chunk_no, object_key, byte_size, sha256,
  PRIMARY KEY (object_id, chunk_no)
```

`kind` 至少区分 `raw_source`、`normalized_frame`、`signal_detail`、`diagnostic`、`sqlite_backup`。默认使用 gzip 或 zstd（由部署环境基准测试决定）；压缩前后字节数、算法和 schema 版本都必须记录。超过可配置阈值（默认 8 MiB）的对象拆为固定大小 chunk，并在 manifest 中记录总大小、chunk 数和每块哈希；压缩后仍过大的对象也必须分块，不能以单个超大 HTTP 响应返回。

本机布局建议为 `data/objects/{raw,derived,backup,staging}/YYYY/MM/DD/...`，`object_key` 使用受控字符集，禁止由客户端直接拼接路径。对象状态至少包含 `staged`、`committed`、`orphaned`、`verified`、`deleted`；只有 `verified` 且超过保留宽限期的对象才允许清理。

### 5.3 写入、读取和冷热策略

- 采集先落对象，再以小事务写 manifest 和窄行；事务内禁止写入大 JSON 或上传远端对象。
- 主页只查最新 frame 与窄 `stock_rows`；五维摘要只查 `signal_rows` 核心字段。详情按 `detail_object_id` 读取，服务端流式解压并限制单对象大小、chunk 数和并发数。
- 历史分析按 `(dataset_id, snapshot_type, trading_date, slot_time, code)` 分段查询；需要完整解释时按 object id 分页或 Range 读取，禁止 Flutter 传 SQL 或触发无界全历史组装。
- SQLite 保留近期热窗口和算法所需的最小回看窗口；老旧 raw/derived 对象转远端对象存储。清理前必须完成 manifest、对象哈希、行数/帧数和可恢复索引校验，并保留冷对象回读路径。
- 回看窗口由 `lookback_days + safety_days` 配置并写入采集元数据；在窗口外计算历史信号时先从对象仓库分段回放，不能因归档把序列静默截断。任何无法回读的片段必须返回 `degraded/insufficient` 和缺口位置。
- SQLite 使用 WAL、`busy_timeout`、显式短事务和定期 checkpoint；备份使用 SQLite 在线 backup API 或等价一致性快照，禁止直接复制正在写入的主库文件。每个备份批次同时登记数据库快照、对象 manifest、总字节数/行数和哈希；恢复必须整批校验通过后再切换，禁止只恢复数据库而遗漏对象。

### 5.4 缺失值合同

- 缺失、无效、真实零值和未计算值必须区分；缺失不得转换为 `0`。
- 一个平台失败不删除其他平台排名；一个字段缺失不阻断同一行其他字段写入。
- 原始响应只要有任何来源记录就必须保存并登记，即使规范化字段不完整；全源无原始记录时 run 才允许标记为 `no_data`。
- 对象上传失败不能回滚已保存的 SQLite 事实；manifest 状态和结构化错误必须可查询，详情 API 返回缺失对象而不是空对象。
- API 必须同时返回原始可用数据、可计算信号、缺失字段、对象状态和结构化原因。

## 6. 五维信号生产合同

### 6.1 独立算法包

从 QuantBoard RankTrend golden 中提取 lite 所需的生产函数，建立独立 `lite_ranktrend` 包。不得复制整个研究目录，也不得在客户端保留第二份算法实现。

提取范围固定为：

- 共振 `resonance`
- 排名趋势 `rankTrend`
- 热度 `heat`
- 量价 `volumePrice`
- 生命周期 `lifecycle`

如果当前 golden 中存在额外观察因子，必须在配置中明确启用/禁用，不得因“拷贝方便”悄悄改变投票或档位语义。

每个信号返回：

```json
{
  "direction": "buy|sell|hold|null",
  "score": 0,
  "signalTier": "S|A|B|C|D|E|unknown",
  "status": "ok|degraded|insufficient|unavailable",
  "reasons": [],
  "sampleQuality": {},
  "engineVersion": "...",
  "configHash": "..."
}
```

`insufficient` 和 `unavailable` 必须保留原因，不得降级成 `hold/0` 后隐藏状态。

### 6.2 版本与一致性

本机研究输出和云端生产输出必须携带 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash` 和 `engine_version`。上线前运行固定 golden fixtures；升级算法时先双跑对比，再切换默认版本，保留旧版本回滚能力。

维度命名以 `heat`（热度）为 Lite 对外 canonical 名称，不再把它描述为“横截面”维度。若当前 QuantBoard golden 或历史数据仍输出 `crossSection`，只能在云端适配层做显式一对一映射（`crossSection -> heat`），并在 schema/engine 元数据中记录映射版本；不得同时把两者计为两个维度，也不得借改名之机改变计算公式、阈值或投票权重。

## 7. API 合同

所有接口使用 `/api/v1`，响应包含 `requestId`、`serverTime` 和合同版本。

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/home?limit=...&sort=...`
- `GET /api/v1/stocks/{code}`
- `GET /api/v1/stocks/{code}/signals`
- `GET /api/v1/objects/{object_id}`（鉴权、大小上限和 Range/chunk 读取）
- `GET /api/v1/status`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

`home` 返回同一 `frameKey` 下的股票、综合排名、五维摘要、采集时间、源健康、质量标记和最大数据年龄，不加载 raw 或完整信号 JSON。详情接口返回核心字段、`detail_object_id` 和历史样本质量；客户端需要解释时再通过对象接口按需读取。对象接口必须支持最大字节数、Range/chunk、ETag 和内容哈希校验，拒绝无界全历史读取。

认证采用短期 access token + 可撤销 refresh token；token 只保存哈希，Flutter 使用系统安全存储。v1 默认单用户，不开放注册。接口设置最大 `limit`、响应压缩、ETag 和基础请求限流。

## 8. Flutter 客户端

目录为 `mobile/dragon_board_app/`，与根 Vue 前端和云端 Python 代码独立。

客户端职责：

- 原生列表、排序筛选、股票详情和五维卡片；
- typed API models 和合同版本检查；
- access/refresh token 安全存储；
- 最近一次主页/详情缓存；
- 弱网、离线、认证过期和服务降级状态；
- Android AAB/APK 签名构建；
- iOS archive、TestFlight 和私有分发构建。

客户端不计算 `avgRankNum`、`compRank` 或五维信号。所有行情卡片显示 `capturedAt`、`staleAge` 和质量状态，避免用户把旧数据误认为实时数据。

推送通知、后台定时刷新和交易操作不属于 v1 的默认承诺；若以后增加，单独设计 FCM/APNs 和权限策略。

## 9. 安全、运维与灾备

- 仅开放 443；SSH 使用密钥和来源限制；关闭公网 8900 等内部端口。
- 上游 cookie、API key 和对象存储密钥只通过 root-readable secret 文件或环境注入。
- API 记录结构化审计日志，但不记录 token 和上游敏感头。
- `/health/live` 只检查进程；`/health/ready` 检查数据库、最新成功采集和磁盘空间。
- `/status` 暴露各源最近成功时间、覆盖率、连续失败次数、当前 frame 和信号计算状态。
- SQLite 每日在线备份，保留多代；上传前后校验 SHA-256，manifest 与对象按同一备份批次登记，定期执行恢复演练。
- 设置 SQLite 热数据、raw/derived 本地对象和远端对象的分层保留周期及磁盘容量告警；任何清理都必须先完成 manifest、哈希、行数校验和可恢复索引验证。
- 监控 collector 停止、连续失败、数据过期、源覆盖率下降、磁盘不足和备份失败。

## 10. 验收标准

### 后端与数据

- 干净环境可启动 API、collector 和 backup 三个服务。
- 部分源失败时仍保存并返回其他源数据和结构化原因。
- 全源无原始记录时才报告 `no_data`。
- 同一 frame 的主页与信号 `frameKey` 一致。
- SQLite 重启、重复采集、并发读写和迁移后无重复行或孤儿行。
- 大对象不进入 SQLite：原始响应、完整信号解释和历史 bundle 均能通过 manifest 找到；对象写入中断会留下可诊断 orphan，不损坏已提交事实。
- 压缩、分块、Range 读取和对象哈希校验通过；超过阈值的对象不会触发单个超大 SQLite 行或无界 API 响应。
- 归档/恢复后 frame、股票行数、信号序列和缺失片段校验一致；无法回读的片段显式标记 `degraded/insufficient`。
- lite 与 QuantBoard golden fixture 输出一致。
- 源 429、验证码、超时、空响应和旧缓存场景均有测试。

### 安全与部署

- HTTP 自动跳转 HTTPS，未授权 API 返回 401/403。
- 限流可以阻断高频请求，但不影响正常手机刷新。
- API/collector 崩溃后 systemd 自动恢复，且不会启动第二个 collector。
- 从对象存储备份恢复后能继续产生连续 frame 和信号。

### Flutter

- Android 真机安装、登录、刷新、详情、离线缓存和 token 过期流程通过。
- iOS TestFlight 安装、登录、刷新、后台切换和网络切换流程通过。
- 375px 等效窄屏和大字体下无关键信息遮挡。
- API 降级、样本不足和过期数据在客户端可见。
