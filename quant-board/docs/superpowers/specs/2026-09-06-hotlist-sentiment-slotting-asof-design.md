# 热榜情绪槽位级落库与时点查询（WP1b + WP1c）设计

状态：待批准（2026-09-06）
前置：依赖 WP1a（`backend/analysis/hotlist/sentiment.py` 纯函数 + `services/theme/hotlist_sentiment_compute.py` 编排，spec `2026-09-06-hotlist-sentiment-backend-migration-design.md`）实施完成。

## 动机

1. **回测 as-of 数据完整性**：hotlist_sentiment 目前每天一份 EOD 文档。WP1a 的 series 读口只 lazy-compute 最新交易日，历史槽位情绪无从查起——回测时点化需要每槽都有文档，不能依赖"前端打开过页面"。
2. **lookahead 未来函数**：`backend/analysis/ranktrend/engine/runtime.py` `_ensure_hotlist_sentiment`（L958-984）按 `frame["tradingDate"]` 取日粒度文档后赋给**当日全部帧**（L977）——日内 10:30 的帧用收盘后才确定的情绪做 regime 门控。L1 档案组 5 的 `regimeGateStrongBan`/`banStrongA`/`banStrongB` 结论是在被污染的 regime 数据上验证的。
3. `hotlistSentimentStatus` 已有 "ok"/"missing" 语义（runtime.py L978），"stale" 顺着该字段扩展。

## 用户已定决策（2026-09-06）

- EOD 终值文档保留现 `_id`（兼容现消费方）；槽位文档 `_id` 追加 `:{slot}` 后缀。
- 采集时机挂 snapshot_collector 既有槽位生命周期——不加守护进程、不加新集合、不加常规 API（AGENTS.md 第 10 节清单）。
- 历史回填复用 `HotListSentimentBackfillService`（改为按帧遍历）。
- regime 门控重验是"9 月数据累积后"的研究任务（L1 档案 §6 触发条件），**不进本轮编码**。

## 范围 WP1b：槽位级落库

### b1. 文档 schema 与索引（库合同变化，需同步 database-migration-plan.md）

- 槽位文档：`_id = {dataset_id}:{snapshot_type}:{trading_date}:{slot}`（slot 为 "HH:MM"），`slotTime = slot`，与 EOD 同 collection `hotlist_sentiment`，正文 schema 与 WP1a 输出一致。
- EOD 文档：`_id` 不变；`slotTime` 从来源帧的 "HH:MM"（operations L219 现值）改为哨兵 `"EOD"`。
- 唯一索引 `(datasetId, snapshotType, tradingDate)`（`data/migrations/mongodb_migration.py` L190-196）重建为 `(datasetId, snapshotType, tradingDate, slotTime)`。
- 存量迁移：一次性脚本把存量 EOD 文档 `slotTime` 置 `"EOD"`（每天 1 份，量小；脚本先查后改、失败不动原索引）。
- `get_by_date` 增加哨兵条件，精确命中 EOD 文档——现消费方零感知。

### b2. collector 挂载（不加新进程）

- 挂载点：`backend/snapshot_collector/service.py` `_persist_one` 内 save 成功且 `run_status=="completed"` 之后（L531-539 cache 失效旁）——该处 `dataset_id/snapshot_type/trading_date/slot_time/derived.stock_rows/frame` 全部入参齐备。
- 编排：`services/theme/hotlist_sentiment_compute.py` 新增 per-slot 入口 `compute_and_upsert_for_slot(dataset_id, snapshot_type, trading_date, slot_time, frame, stock_rows)`：当前帧 rows + 前两日 rows（查库，复用 WP1a 取数方法）+ join displayStatus + frame.limitSummary → `compute_hotlist_sentiment` → 构造槽位 `_id` → upsert。
- **无质量阻断**：取数或计算异常 → 记 warning、帧采集照常成功返回；该槽情绪缺失由 WP1c 的 stale/missing 语义兜底，不阻断、不伪造。
- 幂等：`replace_one` upsert，同槽重跑安全；collector 重启补采同槽不产生重复文档。

### b3. 历史回填

- `HotListSentimentBackfillService` 增加按帧遍历模式：对每个 trading_date 遍历当日全部槽位帧，逐槽计算并 upsert 槽位文档；既有 EOD 模式保留。
- 两条模式都调 WP1a 纯函数（WP1a 已把 EOD 入库切到纯函数，槽位复用同一计算链）。

## 范围 WP1c：时点查询消 lookahead

### c1. 存储读口

- `HotListSentimentService.get_as_of(dataset_id, snapshot_type, trading_date, slot_time) -> tuple[dict | None, str]`，返回 `(doc, status)`：
  1. 当日槽位文档中 `slotTime <= 给定 slot_time` 的最新一份（"HH:MM" 零填充字符串比较成立；当日槽位查询不含 "EOD" 哨兵文档）→ status `"ok"`；
  2. 当日无合格槽位 → 前一交易日 EOD 文档（前一交易日复用 WP1a 已转公开的 trading_dates 序列）→ status `"stale"`；
  3. 均无 → `(None, "missing")`。
- 性能：provider 闭包内按 tradingDate 缓存当日槽位文档列表 + 前日 EOD（内存），逐帧调用只做内存选择——库查询 O(天数) 而非 O(帧数)。

### c2. 引擎注入改造（lookahead 修复本体）

- `make_hotlist_sentiment_provider` 工厂签名不变（`dataset_id, snapshot_type`），其闭包合同 `(trading_date)` → `(trading_date, slot_time)`，返回 `(doc, status)`。
- `_ensure_hotlist_sentiment`：逐帧调 `provider(frame["tradingDate"], frame["slotTime"])`，`frame["hotlistSentiment"]` / `frame["hotlistSentimentStatus"]`（"ok"/"stale"/"missing"）分别赋值；删除按日共享同一 doc 的 `by_key` 逻辑。frame 自带 `slotTime`（runtime.py L1277 已读该键）。
- 三个 provider 注入方（回测 `core/backtest/engine.py` L24-29、`services/backtest_service.py` L849-853、live `api/ranktrend_routes.py` L787-792）只是传参，代码预计不动——实际改动集中在 `hotlist_sentiment_service.py`（闭包实现）与 `runtime.py`（注入逻辑）；写计划时逐一核实。
- `main.py` L931 链路不注入 sentiment（恒中性），不动。

### c3. market_regime stale 透传

- `trend/risk.py` `market_regime`：`frame.get("hotlistSentimentStatus") == "stale"` 时在 reasons 追加标注（如"情绪数据为前日 stale 口径"）；**不改打分**。

### c4. regime 门控重验（后续研究任务，非本轮编码）

- 按 `docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md` §6：9 月数据累积后对档案组 5（`regimeGateStrongBan`/`banStrongA`/`banStrongB`）重走 rolling walk-forward（A/B 纪律、golden 不破坏）。
- 本轮仅在该档案"组 5"条目加注"lookahead 已修复、待数据积累重验"。

## 非范围

- 不改 `market_regime` 打分权重与 `REGIME_STAGE_ADJUST`。
- 不批量重算历史槽位文档（如需走 backfill 显式执行）。
- 不新增集合、守护进程、常规 API（series 读口已由 WP1a 覆盖）。
- `main.py:931` 链路不动。

## 测试策略（TDD）

1. WP1b：collector 挂载测试（成功后槽位文档 upsert、计算异常不阻断帧返回）；`_id`/`slotTime` 格式；`get_by_date` 哨兵语义；索引迁移脚本（先查后改）；回填按帧遍历（多槽日产出 N 份槽位文档 + 1 份 EOD）。
2. WP1c：`get_as_of` 选择逻辑（当日 ≤slot 最新、stale 回退前日 EOD、双 missing）；`_ensure_hotlist_sentiment` 同日多帧注入不同 doc + "stale" 状态；`market_regime` stale reasons 不改分。
3. 验证：`quant-board` 目录 pytest 相关子集（先 `--collect-only`，全量有挂起问题）。

## 文档同步

- `quant-board/docs/database-migration-plan.md`：索引重建、`_id` 合同、存量迁移脚本。
- `quant-board/docs/architecture.md`：情绪链路时点化描述。
- `ranktrend-l1-param-ledger.md`：组 5 加注重验待办。
- `quant-board/docs/api-cli.md`：核对是否涉及（无新 API，预计仅核对）。

## 风险与回退

- collector 每槽 +1 次情绪计算（轻量纯函数）+ 前两日 rows 查询——量级可接受；计算异常不阻断采集。
- 索引迁移：脚本先查存量再重建，失败保留原索引可回退。
- 回退：revert collector 挂载与 `_ensure_hotlist_sentiment` 改动即可回到日粒度注入；已落库槽位文档留存无害（EOD 兼容路径不受影响）。
- 首个上线日人工验证 MongoDB 槽位文档数（每交易日 ≤ 槽位数 11）。
