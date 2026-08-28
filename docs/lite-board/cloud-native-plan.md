# Dragon Board Cloud Lite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单台 Linux VPS 上交付不依赖 MongoDB、Redis、Windows 行情桥的行情主页和五维信号服务，并通过同一套 Flutter 代码生成 Android 与 iOS 原生客户端。

**Architecture:** `lite-board/` 是独立云端运行包。Collector 是 SQLite 唯一写者，FastAPI 只读窄事实表和对象 manifest；raw、完整信号解释、诊断和历史 bundle 进入本机对象仓库并备份到 S3 兼容对象存储。Lite 对外第五维 canonical 名称为 `heat`，QuantBoard golden 仍输出 `crossSection` 时只在适配层做显式映射。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、stdlib `sqlite3`、httpx、gzip/zstd（二选一，以压测结果冻结）、systemd、Nginx/Caddy、Flutter/Dart、Android Gradle、iOS Xcode/TestFlight。

---

## 0. 设计合同与范围冻结

**Files:**
- Modify: `docs/lite-board/cloud-native-design.md`
- Modify: `README.md`
- Create: `lite-board/README.md`
- Create: `lite-board/pyproject.toml`
- Create: `lite-board/.env.example`
- Test: `lite-board/tests/test_contract_metadata.py`

- [ ] **Step 1: 固定 Lite 合同入口和运行边界**

  在 `lite-board/README.md` 写明 Lite 不导入 `quant-board/backend/data` 的 Mongo repository，不启动 Redis、`python-bridge` 或 TdxL2Helper；仅通过 HTTPS 暴露 `/api/v1`。在 `README.md` 的项目树和文档入口增加 `lite-board/`、`docs/lite-board/cloud-native-design.md` 和本计划链接。

- [ ] **Step 2: 固定版本元数据和五维命名**

  在 `lite-board/.env.example` 固定 `LITE_SCHEMA_VERSION`、`LITE_ENGINE_VERSION`、`LITE_STRATEGY_VERSION`、`LITE_CONFIG_HASH`、`LITE_HEAT_MAPPING_VERSION`、`LITE_LOOKBACK_DAYS`、`LITE_OBJECT_CHUNK_BYTES=8388608`。`heat` 是唯一对外第五维；不得在 API 响应中同时输出一个独立的 `crossSection` 维度。

- [ ] **Step 3: 写合同失败用例并运行**

  `lite-board/tests/test_contract_metadata.py` 校验每个信号响应都携带 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`engine_version`，并校验 `crossSection` 输入只映射为 `heat`。

  Run: `cd lite-board; python -m pytest tests/test_contract_metadata.py -q`

  Expected: 首次运行因包和模型尚未创建而失败；该失败用于锁定合同，不得跳过。

## 1. SQLite 窄事实库与对象仓库

**Files:**
- Create: `lite-board/backend/storage/migrations/001_initial.sql`
- Create: `lite-board/backend/storage/sqlite.py`
- Create: `lite-board/backend/storage/object_store.py`
- Create: `lite-board/backend/storage/manifest.py`
- Create: `lite-board/backend/storage/retention.py`
- Create: `lite-board/tests/test_sqlite_schema.py`
- Create: `lite-board/tests/test_object_store.py`
- Create: `lite-board/tests/test_storage_recovery.py`

- [ ] **Step 1: 建立迁移表和窄表**

  在 `001_initial.sql` 创建 `schema_migrations`、`frames`、`stock_rows`、`source_runs`、`signal_rows`、`objects`、`object_chunks` 和 `backup_batches`。`signal_rows` 只包含 `heat_direction/heat_score/heat_tier` 等核心筛选字段以及 `detail_object_id`；禁止 `*_json` 大字段。复合主键事实表使用 `WITHOUT ROWID`，并建立 frame 唯一键、`(frame_id, code)`、`(code, captured_ts)` 和分页查询索引。

- [ ] **Step 2: 实现 SQLite 连接和短事务**

  `sqlite.py` 每次连接执行 `PRAGMA foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout` 和受控 `synchronous`；提供 `run_write_transaction(callback)`、只读连接和在线 backup API。写事务只接受窄行和 manifest，不接受原始 payload 或完整信号 JSON。

- [ ] **Step 3: 实现对象原子写入**

  `object_store.py` 将数据写入 `data/objects/staging/`，完成 fsync、压缩、`logical_bytes/stored_bytes` 和 SHA-256 校验后原子 rename 到 `raw/` 或 `derived/`。对象超过 `LITE_OBJECT_CHUNK_BYTES` 时写入固定 chunk，并在 `objects/object_chunks` 登记每块哈希。客户端不得传入文件系统路径。

- [ ] **Step 4: 实现 manifest、orphan 和保留策略**

  `manifest.py` 只在最终对象存在后提交 `objects` 行；事务失败留下 `orphaned` 状态并记录原因。`retention.py` 仅允许删除 `verified` 且超过宽限期、完成哈希和引用校验的对象；SQLite 热窗口和算法回看窗口不能被清理任务绕过。

- [ ] **Step 5: 先写失败测试再实现**

  测试覆盖：大对象不进入 SQLite；rename 后 SQLite 事务失败产生可查询 orphan；chunk 数、总字节数和哈希可重算；在线 backup 恢复后行数、frame 数和 manifest 一致；并发读期间写事务不产生锁死。

  Run: `cd lite-board; python -m pytest tests/test_sqlite_schema.py tests/test_object_store.py tests/test_storage_recovery.py -q`

  Expected: 全部 PASS，并输出 SQLite pragma、对象大小、chunk 校验和恢复行数摘要。

## 2. 采集器与数据源适配

**Files:**
- Create: `lite-board/backend/collector/calendar.py`
- Create: `lite-board/backend/collector/run.py`
- Create: `lite-board/backend/collector/quality.py`
- Create: `lite-board/backend/collector/adapters/base.py`
- Create: `lite-board/backend/collector/adapters/hotlists.py`
- Create: `lite-board/backend/collector/adapters/quotes.py`
- Create: `lite-board/backend/collector/adapters/funds.py`
- Create: `lite-board/backend/collector/scheduler.py`
- Create: `lite-board/tests/test_collector_partial_failure.py`
- Create: `lite-board/tests/test_collector_idempotency.py`
- Create: `lite-board/tests/fixtures/providers/*.json`

- [ ] **Step 1: 定义交易日历和采集槽位**

  `calendar.py` 统一 Asia/Shanghai 时间，生成 `half_hour` 默认槽位并处理午休、节假日、迟到槽位和补采。每个槽位生成稳定 `run_id` 和 `dataset_id/snapshot_type/trading_date/slot_time` 幂等键。

- [ ] **Step 2: 实现适配器的超时和健康合同**

  每个适配器实现 `fetch(context) -> RawPayload`、`normalize(raw) -> NormalizedRows`、`health(raw_or_error) -> SourceHealth`。固定连接/读取超时、有限重试、指数退避、429/验证码识别和 last-good；腾讯接口的真实 URL、同花顺资金口径和授权方式必须来自配置与 fixture，不得以人工请求代替验证。

- [ ] **Step 3: 接入 fail-visible 采集写入**

  `run.py` 保存任何可用原始响应到对象仓库，再以短事务写 frame、窄 stock rows、source runs 和 manifest。单源失败只设置质量位图；仅所有来源没有任何原始记录时才使用 `no_data`。缺失字段保持 `NULL`，不得用 `0` 填充。

- [ ] **Step 4: 实现单实例调度**

  `scheduler.py` 使用文件锁或 SQLite lease 防止第二个 collector；进程重启后从已提交槽位恢复，不依赖内存 last-good。系统性限流进入可观测退避状态，不通过重启规避上游限制。

- [ ] **Step 5: 验证异常和幂等**

  `test_collector_partial_failure.py` 证明八个平台中部分失败仍保存其余排名、原始对象和结构化原因；`test_collector_idempotency.py` 证明重复 run 不产生重复 frame/stock rows，payload hash 不同则标记冲突而不覆盖。

  Run: `cd lite-board; python -m pytest tests/test_collector_partial_failure.py tests/test_collector_idempotency.py -q`

  Expected: PASS；测试输出应包含保存的源数量、失败源代码、frameKey 和冲突键。

## 3. RankTrend 适配与“热度”第五维

**Files:**
- Create: `lite-board/backend/signals/contracts.py`
- Create: `lite-board/backend/signals/ranktrend_adapter.py`
- Create: `lite-board/backend/signals/service.py`
- Create: `lite-board/backend/signals/quality.py`
- Create: `lite-board/tests/fixtures/ranktrend/*.json`
- Create: `lite-board/tests/test_heat_mapping.py`
- Create: `lite-board/tests/test_ranktrend_golden.py`

- [ ] **Step 1: 固定输入字段和来源声明**

  适配层明确 RankTrend 所需的 `avgRankNum`、`volumeRatio`、`zlje/zljzb`、`amount` 历史、`price_changes`、市场中位数和样本质量；缺失字段返回 `degraded/insufficient` 与位置，不用零值伪造。

- [ ] **Step 2: 实现 canonical heat 映射**

  `ranktrend_adapter.py` 将 golden 的 `observation.crossSection` 一对一映射为 `heat`，同步映射 `direction/score/signalTier/status/reasons/sampleQuality`；映射版本写入响应元数据。适配层不改变公式、阈值、投票权重或第五维数量。

- [ ] **Step 3: 实现信号核心与详情外置**

  `service.py` 只把五维方向、分值、档位、overall status 和 `detail_object_id` 写入 SQLite；完整 reasons、因子轨迹和历史样本写入 `signal_detail` 对象。计算失败保留 frame 和可计算维度，单维不可用不清空其他维度。

- [ ] **Step 4: Golden 回归和质量测试**

  `test_heat_mapping.py` 断言 API 永远使用 `heat` 且不会出现第二个 `crossSection` 维度；`test_ranktrend_golden.py` 使用固定 fixture 对比 QuantBoard golden 输出，并覆盖空数据、NaN、时间乱序、样本不足和缺字段。

  Run: `cd lite-board; python -m pytest tests/test_heat_mapping.py tests/test_ranktrend_golden.py -q`

  Expected: PASS；golden 差异为 0，降级用例返回结构化缺口而非空结果。

## 4. FastAPI、认证和受限读取

**Files:**
- Create: `lite-board/backend/api/app.py`
- Create: `lite-board/backend/api/auth.py`
- Create: `lite-board/backend/api/models.py`
- Create: `lite-board/backend/api/routes/home.py`
- Create: `lite-board/backend/api/routes/stocks.py`
- Create: `lite-board/backend/api/routes/objects.py`
- Create: `lite-board/backend/api/routes/health.py`
- Create: `lite-board/tests/test_api_home.py`
- Create: `lite-board/tests/test_api_objects.py`
- Create: `lite-board/tests/test_api_auth.py`

- [ ] **Step 1: 建立版本化 API 和响应模型**

  `app.py` 只挂载 `/api/v1`。所有响应包含 `requestId`、`serverTime`、合同版本、`frameKey` 和质量状态；Pydantic 模型拒绝未知 dimension 名称，canonical 第五维只能是 `heat`。

- [ ] **Step 2: 实现首页和股票详情窄读**

  `home.py` 只查询最新 frame、`stock_rows` 和 `signal_rows` 核心列，强制 `limit` 上限和排序白名单；`stocks.py` 返回 `detail_object_id`，不在 SQL 查询中组装完整历史 JSON。

- [ ] **Step 3: 实现对象按需读取**

  `objects.py` 只接受已鉴权的 `object_id`，校验 manifest 状态、ETag、SHA-256、最大字节数、最大 chunk 数和 HTTP Range；禁止任意路径、SQL、全历史 bundle 和无界解压响应。对象缺失返回结构化 `object_unavailable`，不能返回空对象伪装成功。

- [ ] **Step 4: 实现单用户 token 流程**

  `auth.py` 使用短期 access token 和可撤销 refresh token；数据库只保存 refresh token 哈希。Flutter 使用系统安全存储，API 日志不得记录 token 或上游敏感头。

- [ ] **Step 5: 验证 API 边界**

  测试覆盖：首页与信号使用同一 `frameKey`；部分源失败仍返回可用行和原因；对象 Range/chunk、ETag、大小上限和 401/403；`crossSection` 输入只出现在适配器内部，不出现在 Lite 响应。

  Run: `cd lite-board; python -m pytest tests/test_api_home.py tests/test_api_objects.py tests/test_api_auth.py -q`

  Expected: PASS；超限请求返回 413/416 或结构化 400，未授权返回 401/403。

## 5. 备份、归档、恢复和运维

**Files:**
- Create: `lite-board/backend/backup/backup_job.py`
- Create: `lite-board/backend/backup/restore.py`
- Create: `lite-board/backend/backup/verify.py`
- Create: `lite-board/backend/cli.py`
- Create: `lite-board/deploy/systemd/dragon-lite-api.service`
- Create: `lite-board/deploy/systemd/dragon-lite-collector.service`
- Create: `lite-board/deploy/systemd/dragon-lite-backup.service`
- Create: `lite-board/deploy/systemd/dragon-lite-backup.timer`
- Create: `lite-board/deploy/nginx/dragon-lite.conf`
- Create: `lite-board/deploy/env/dragon-lite.env.example`
- Create: `lite-board/tests/test_backup_restore.py`
- Create: `lite-board/tests/test_retention_guard.py`

- [ ] **Step 1: 实现一致性备份批次**

  `backup_job.py` 使用 SQLite online backup API 生成 `sqlite_backup` 对象，同时冻结并上传对象 manifest、chunk 清单和 `backup_batches` 元数据。上传前后校验 SHA-256、逻辑字节数、存储字节数、frame/stock/signal 行数和 manifest 引用数。

- [ ] **Step 2: 实现 staging 恢复和原子切换**

  `restore.py` 下载到独立 staging 目录，先校验数据库、对象 manifest、对象哈希和引用完整性，再切换数据目录；任何校验失败不得覆盖当前运行事实。恢复后 collector 能继续生成下一个连续 slot。

- [ ] **Step 3: 实现 retention 守卫**

  `verify.py` 在清理前检查热窗口、`lookback_days + safety_days`、对象引用、冷对象回读和质量缺口；只允许清理已 verified 且超宽限期对象。归档缺口必须让 API 返回 `degraded/insufficient` 与缺口位置。

- [ ] **Step 4: 配置 systemd 和公网入口**

  API 以非 root 用户监听 `127.0.0.1`，collector 使用单实例锁，backup 使用 timer；Nginx/Caddy 只开放 443、强制 HTTPS、设置安全头和限流，关闭 8000/8001/8765/8900 公网访问。日志采用 journald 或轮转，secret 通过 root-readable 文件注入。

- [ ] **Step 5: 验证崩溃、备份和恢复**

  测试覆盖备份上传中断、对象缺块、数据库哈希不符、恢复中断、清理误删保护和 systemd 重启；恢复后的 frame、stock rows、signal rows、对象 manifest 和下一采集槽位必须连续。

  Run: `cd lite-board; python -m pytest tests/test_backup_restore.py tests/test_retention_guard.py -q`

  Expected: PASS；损坏备份拒绝切换，恢复成功后行数/哈希摘要与备份批次一致。

## 6. Flutter 原生 Android/iOS 客户端

**Files:**
- Create: `mobile/dragon_board_app/pubspec.yaml`
- Create: `mobile/dragon_board_app/lib/main.dart`
- Create: `mobile/dragon_board_app/lib/api/api_client.dart`
- Create: `mobile/dragon_board_app/lib/api/models.dart`
- Create: `mobile/dragon_board_app/lib/auth/token_store.dart`
- Create: `mobile/dragon_board_app/lib/features/home/home_screen.dart`
- Create: `mobile/dragon_board_app/lib/features/stock/stock_detail_screen.dart`
- Create: `mobile/dragon_board_app/lib/features/signals/signal_detail_screen.dart`
- Create: `mobile/dragon_board_app/lib/storage/cache_store.dart`
- Create: `mobile/dragon_board_app/test/api_models_test.dart`
- Create: `mobile/dragon_board_app/test/offline_state_test.dart`
- Create: `mobile/dragon_board_app/integration_test/auth_refresh_test.dart`

- [ ] **Step 1: 初始化 Flutter 工程和依赖**

  使用稳定 Flutter SDK 创建 Android/iOS 工程；依赖只包含 HTTPS 客户端、JSON 序列化、系统安全存储和受控本地缓存。不得引入 MongoDB、Redis 或算法运行库。

- [ ] **Step 2: 实现 typed API 模型**

  `models.dart` 严格解析 `/api/v1` 合同，使用 `heat` 字段；显示 `capturedAt`、`staleAge`、质量状态、缺失字段和 `detail_object_id`。未知合同版本进入可见降级状态，不静默解析为旧字段。

- [ ] **Step 3: 实现认证、缓存和弱网状态**

  `api_client.dart` 处理 access/refresh、401 重试一次、ETag/Range 对象读取和最大响应大小；`token_store.dart` 使用 Keychain/Keystore；`cache_store.dart` 只缓存最近主页/详情并带时间戳，离线时明确显示 stale。

- [ ] **Step 4: 实现首页、详情和五维卡片**

  首页只展示窄响应；股票详情按需读取信号对象。客户端不计算 `avgRankNum`、`compRank`、heat 或任何五维分值，不把 `insufficient/unavailable` 显示为 hold/0。

- [ ] **Step 5: 验证 Android 和 iOS 构建**

  Run: `cd mobile/dragon_board_app; flutter test`

  Expected: Dart 单测 PASS。

  Run: `cd mobile/dragon_board_app; flutter build appbundle --release`

  Expected: 生成签名配置要求的 AAB；未配置签名时必须明确失败，不得把 debug APK 当发布包。

  Run on macOS: `cd mobile/dragon_board_app; flutter build ipa --release`

  Expected: 生成可上传 TestFlight 的 archive/IPA；Windows 环境只验证 Dart、Android 和合同，不宣称 iOS 构建通过。

## 7. 集成验收、发布和文档同步

**Files:**
- Modify: `docs/lite-board/cloud-native-design.md`
- Verify: `docs/lite-board/refactor-plan.md`
- Modify: `lite-board/README.md`
- Create: `lite-board/tests/integration/test_end_to_end_contract.py`
- Create: `lite-board/deploy/scripts/provision_vps.sh`
- Create: `lite-board/deploy/scripts/smoke_check.sh`

- [ ] **Step 1: 核验旧方案作废标记**

  确认 `docs/lite-board/refactor-plan.md` 顶部保留 `Obsolete` 标记并指向 `cloud-native-design.md`、本计划；不删除旧材料，不让实施者误把旧 MongoDB/Redis 方案当现行合同。

- [ ] **Step 2: 编写端到端合同测试**

  `test_end_to_end_contract.py` 启动临时 SQLite、对象仓库、collector fixture 和 FastAPI TestClient，验证“部分源失败 -> 保存 raw -> 提交窄 frame -> 计算 heat -> API 首页 -> 对象详情 -> 备份恢复”的完整链路，检查 frameKey、哈希、缺失原因和历史连续性。

- [ ] **Step 3: 编写 VPS 配置和冒烟脚本**

  `provision_vps.sh` 只创建明确的 `/opt/dragon-lite`、`/var/lib/dragon-lite` 和非 root 服务用户，安装固定依赖、迁移 schema、写入 systemd/Nginx 配置并启用 timer；`smoke_check.sh` 检查 HTTPS、健康端点、认证、最新 frame、对象 Range 和备份状态。脚本不得删除非目标目录。

- [ ] **Step 4: 执行发布前验证**

  Run: `cd lite-board; python -m pytest -q`

  Expected: Lite 后端全量测试 PASS，失败数为 0。

  Run: `cd lite-board; python -m backend.cli verify --database data/lite.db --objects data/objects`

  Expected: 输出 schema、frame、stock、signal、object、chunk、hash 和 orphan 计数，`status=ok`。

  Run on VPS: `bash deploy/scripts/smoke_check.sh https://<configured-host>`

  Expected: HTTPS、401、home、heat、object Range、ready、backup 验收全部 PASS；任何一项失败都不得进入 APK/TestFlight 分发。

- [ ] **Step 5: 记录发布回滚点**

  发布包保留 schema 版本、engine/config hash、SQLite backup batch id、对象 manifest batch id 和 Flutter build number。回滚先停止 collector，再切换已验证的整批数据库+对象目录，最后恢复 API；禁止只回滚 SQLite 而遗漏对象。

## 8. 计划自审

- [ ] 逐项对照设计文档：SQLite 窄表、对象 manifest/chunk、原子写入、冷热策略、恢复校验、fail-visible、API 限制、Flutter 原生构建和 systemd 均有对应任务。
- [ ] 扫描本计划不得出现占位词或未定义的“稍后补充”步骤；所有验证命令都标明运行目录和预期结果。
- [ ] 检查 `crossSection` 只在 QuantBoard 适配说明和测试输入中出现；Lite schema、API、Flutter 模型统一使用 `heat`。
- [ ] 检查计划未要求修改根 `src/**`、QuantBoard Mongo 主链或用户现有的 `src/stores/ui.ts` 无关改动。
- [ ] 实施前执行一次 `git status --short`，确认主工作区仍只包含用户原有改动和本计划/设计文档；不自动回滚或覆盖其他文件。
