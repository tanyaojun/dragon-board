# 共振强度数据链路核查发现

## 已知背景

- 2026-07-28 11:30 槽位已用盘后当前缓存代理补齐排名字段，并写入可恢复审计记录。
- 此前根因包括 collector/builder 丢弃八平台原始名次及榜单总数。
- 当前页面已观察到共振强度发生变化，但仍需证明链路和公式整体正确。

## 2026-07-28 定时刷新归零事故

- 用户观察：页面首屏加载时“共振强度”存在非零值；约数分钟后的自动刷新后，同列全部显示 `0%`。
- 设计合同规定当前帧缺失、时间乱序、低样本量或横截面有效样本不足时，所有受影响结果必须降级为 `resonance.status='insufficient'` 与分数 `0`。
- 因此本轮优先沿定时刷新调用顺序核查当前行情、Mongo rank-series 和 `applyJumpSignals()` 的输入/输出，不将表格的 `0%` 视为单纯展示问题。
- 初步代码取证：`DataTable.vue` 直接显示 `_resonancePct` 或 `rankTrend.resonance.score`；`RankTrendSignalService` 在每轮 `getRankTrends()` 后调用 `applyJumpSignals()` 与 `applyResonanceFinals()`。全表归零的根因位于该服务或其输入序列，不在表格格式化层。
- `applyResonanceFinals()` 仅当至少 20 只股票同时覆盖 `latestAnalysisFrameKeys` 的最后四帧且样本质量非 insufficient 时才计算共享中位数；否则把所有 fresh code 传入 `marketSampleCount < 20` 的 `analyzeRankResonance()`，按合同统一写为 `0`。当前根因假设聚焦“自动刷新当前帧与历史帧的代码/时序错配”。
- 自动刷新事实：`DataLoaderFacade` 每分钟行情刷新后在未重拉平台榜单时执行 `refreshRankTrendSignals()`；此外有 30 分钟独立信号刷新。`RankTrendAnalyzer.shouldAppendCurrentFrame()` 在当前榜单总数与最新 Mongo 帧 `totalCount` 不同时强制追加 `current:*`。截图当前榜单为 219，而本日自然采集帧曾为 221，已确认会走该分支；尚需运行态证明它如何使市场共同样本不足。
- 另一个待验证风险：`normalizeRankSeriesResponse()` 以 `snapshotId` 聚合 API bars，却使用 `tradingDate + slotTime` 作为分析 frame key；若同一槽位存在多个 snapshotId，`buildSnapshotsMap()` 会按相同 date key 覆盖，可能使 `latestAnalysisFrameKeys` 与单股序列不一致。
- 当前运行中 Mongo API 的最新正式 `half_hour` frame 为 `2026-07-28 14:30`，`stockRowCount=212`。正式快照与页面实时榜单数量天然不必相同，因此不能用总数差异作为“当前帧必然无效”的修复依据；需直接统计 rank-series 最后四个 frame 的共同覆盖。
- **高置信度根因候选（运行态证据）**：以最新 212 个真实代码请求 `rank-series`，响应聚合出 491 个 frame，且存在 85 组同一 `code + tradingDate + slotTime` 的重复 bar。自动刷新走 `enforceLiveTimeline=true`，重复时间戳会触发“历史快照时间乱序或重复”，所有股票 `sampleQuality=insufficient`，继而共振全表归零；启动缓存路径不启用该严格门禁，因此表现为首屏正常、自动刷新后归零。待确认这些重复是否位于最近 50 个市场帧，并追溯其 snapshotId 来源。
- 上述候选已被反证：重复 bar 全部位于 5 月，最近 50 个 frame 从 `2026-06-29 15:00` 到 `2026-07-28 14:30`，没有任何重复组触及该窗口；不能把旧重复槽位作为本次修复原因。
- 新的重点：自动刷新对每股调用 `hasMissingIntermediateFrames()`，该检查使用完整 per-code 50-bar 序列，而非最近稳定市场窗口。股票正常进出热榜会天然缺少某些公共 frame，必须实测是否被该逻辑错误地统一标记为 insufficient。
- 真实统计：212 只当前代码中，138 只在完整 per-code 50-bar 序列存在中间缺槽，78 只缺少最近 9 个槽位之一，但 185 只完整覆盖最近 4 个槽位。该检查会错误扩大个股降级范围，却不能单独解释“全表归零”；必须继续检查共同的市场时间轴门禁。
- **已确认根因**：rank-series 是“每股最近 50 次出现”的并集，当前 212 只代码产生的最后 50 个 union frame 从 `2026-06-29 15:00` 延续到 `2026-07-28 14:30`，并含 `2026-07-03 15:00 -> 2026-07-28 09:30` 的 25 天断层。该断层不是 Mongo 全市场缺槽，而是稀疏 per-code 采样并集缺少中间 frame；`getRankTrends()` 错将其 `slice(-50)` 用作全市场时间轴，自动刷新启用严格门禁后令所有结果 `sampleQuality=insufficient`，共振统一归零。启动缓存路径关闭严格门禁，故首屏正常。
- 修复边界：全市场质量只能使用最新连续的市场 frame 后缀；不能以 per-code 联集中的旧稀疏点宣告市场缺槽。每股完整历史仍保留给技术计算和既有个股质量逻辑。

## 发现

### 设计合同

- 排名路径唯一输入是每帧 `avgRankNum` 升序横截面重排后的关注度排名/百分位。
- `rank`、`compRank`、`compScore`、资金、换手和成交额不得进入共振方向或分数。
- 固定参数为短周期 3 bars、中周期 8 bars、路径 8 bars、Jump 衰减 3 bars。
- 成熟路径由相对动量、加速度、持续性、Jump 新鲜度和反转惩罚组成；新入榜使用当前关注度强度和 Jump 新鲜度。
- 当前帧缺失、时间乱序、低样本或横截面不足时必须 `resonance.status=insufficient` 且 `decision.final=hold/0`。
- 共振是 Dragon Board live-only 观察层，设计明确不进入 QuantBoard Python golden/replay。Python collector/MongoDB 的责任是完整保存计算原料，而不是复算页面共振。

### 工作区状态

- collector、snapshot builder、RankTrendAnalyzer、resonanceAnalyzer、DataLoader 等链路文件均有未提交修改；本次以当前工作区为待审实现，不覆盖既有改动。

### 初步实现链路

1. Python collector 从启动缓存或八平台 fallback 生成股票行和 `rankProvenance`。
2. builder 将排名字段写入 `snapshot_frames` / `snapshot_stock_rows`。
3. Dragon Board 通过 RankTrend series API 请求 `rank_basis=attention`；Mongo repository 按每个 `snapshotId` 的 `avgRankNum` 重排。
4. `RankTrendAnalyzer` 组装每股历史关注度排名/百分位序列并检测时间轴质量。
5. `RankTrendSignalService.applyJumpSignals()` 先完成 Jump，再用同轮市场中位数调用 `analyzeRankResonance()`，覆盖唯一 `decision.final` 并投影页面字段。
6. `DataTable.vue` 从 `_resonancePct` 或 `rankTrend.resonance.score` 展示共振强度。

### 待重点确认

- 历史序列已包含当前槽位时，当前内存帧是否会被重复追加。
- `_resonancePct` 是原始 0-100 分数还是又做一次横截面百分位转换。
- Mongo attention query 对同分 `avgRankNum` 的排名语义和前端当前帧排序是否一致。
- 新增时间轴门禁是否与交易日跨日、午休和非交易时段槽位规则一致。

### 已确认的计算投影

- `precomputeDisplayFields()` 将 `_resonancePct` 和 `_resonanceRawScore` 都直接赋值为 `rankTrend.resonance.score`；表格未进行第二次百分位转换。
- `DataTable.vue.getResonanceCellValue()` 优先读 `_resonancePct`，缺失时回退同一 `resonance.score`，显示值来源单一。
- `shouldAppendCurrentFrame()` 比较当前关注度排名集合、股票总数与最新历史帧；完全相同则不追加，排名或集合变化才追加内存当前帧。
- 当前帧排序与 Mongo attention 排序都以 `avgRankNum` 升序、代码作为并列次序，初看口径一致，需继续核对 repository 实现全文。
- 成熟路径现在要求 8 个变化区间，即 9 个百分位点；这与短/中/路径窗口“8 bars”的数学含义一致。

### 已确认的公式实现

- `relativeMomentum = clamp((shortChange - marketMedianShortChange) / 15, -1, 1)` 与设计一致。
- `acceleration = clamp((shortChange - midChange * 3/8) / 15, -1, 1)` 与设计一致。
- 持续性使用最近 8 个相邻变化；Jump 新鲜度为 `exp(-barsSinceLatestJump/3)`；反转惩罚权重为 0.6/0.4，均与设计一致。
- `buy/sell` 使用方向化后的动量和加速度镜像计分；反向 Jump 才覆盖基础方向，同向 Jump 只贡献新鲜度。
- 分数权重 0.35/0.25/0.20/0.20/-0.20 与设计一致，最终 clamp 到 0-100。
- 新入榜分数为 0.70 当前关注度强度 + 0.30 Jump 新鲜度，不按历史长度折分。

### 输入质量机制

- 全市场时间轴不连续会把样本状态置为 `insufficient`；单股在公共帧之间漏帧也会单独置为 `insufficient`。
- 市场基准只收集最新四个公共 frame key 全部存在且样本非 insufficient 的股票，少于 20 只则所有共振返回样本不足。

### Mongo attention rank 读模型

- repository 先取每只请求股票最近 `window_bars` 次有效 `avgRankNum` 记录，再对这些记录涉及的每个完整 `snapshotId` 查询全帧有效 `avgRankNum` 行。
- 每帧按 `avgRankNum ASC, code ASC` 排序，`attentionIndex + 1` 为关注度名次，`totalCount` 为该帧有效均榜行数；不会在请求代码子集内错误排名。
- 前端百分位公式为 `((totalCount - rank + 1) / totalCount) * 100`，排名越靠前百分位越高，符合设计中的正向关注度变化。
- attention 模式要求 MongoDB；无 codes 或非 MongoDB 会结构化失败，不会静默回退综合排名。

### 需实测的窗口风险

- Mongo 查询按“每股最近 50 次出现”取样，多股合并后的公共快照集合可能超过 50 个槽位。前端会把该并集作为公共时间轴，需验证合法的股票进出榜不会造成全局/个股时间轴误判或异常放大查询结果。

### 均榜原料公式前后端对齐

- Python collector 与 TypeScript `ComprehensiveRankEngine` 使用同一八个平台顺序和字段映射。
- 权重完全一致：KPL 1.0、TDX 0.9、THS 0.85、东方财富 0.75、大智慧 0.7、淘股吧 0.4、雪球 0.35、财联社 0.35。
- 两端都只对当时 `platformTotal > 0` 的平台计入总权重；上榜使用 `rank/total*100`，未上榜使用 100 分惩罚；`platforms` 只统计有效原始名次。
- Python frame 的 `rankProvenance` 保存上述榜单总数、权重、字段映射、999 默认名次和公式版本，具备未来复算条件。
- 从“综合名次”改为“均榜关注度名次”后，共振频率降低在业务上可预期：资金、换手、成交额的高频变化已被剥离，输入只随八平台榜单位置变化。

### 当前服务进程

- proxy 3000、Quant API 8000、bridge 8765 均在监听。
- Quant API PID 19516 启动于 2026-07-28 12:00:23，晚于本轮排名合同修复，已排除“仍是上午旧进程”这一历史问题。
- `/api/snapshot-collector/status` 当前只返回持久化 collector run state：`mode=idle, lastRunAt=null`；该结果不能单独代表 scheduler 生命周期状态，需要读取 FastAPI 根健康信息和 Mongo 运行记录。

### 当前 scheduler 证据（12:27）

- `enabled=true`、`running=true`、`dataset_id=dragonboard_live`、`poll_seconds=1.0`。
- `last_poll_at` 持续更新，`error_count=0`、`last_error=null`、`overdue_missing_slots=[]`、`in_flight_slots=[]`。
- Quant API 12:00 重启后处于午休，尚未遇到新槽位，因此 `last_run_at=null`、`collection_count=0` 是符合时序的；下一次半小时槽位为 13:30。

### 今日 frame 初查

- 正式 frames API 返回 2026-07-28 `half_hour` 共 5 个 frame（上午 09:30、10:00、10:30、11:00、11:30）。
- frames API 默认携带完整题材实体，输出过大；collector runs API 不支持 tradingDate 参数，因此后续改用 Mongo 只读聚合做精确逐槽统计。

### 今日 Mongo 逐槽审计

- 09:30/10:00/10:30/11:00/11:30 五个槽位均存在，frame `stockRowCount` 与实际 stock rows 分别为 211/207/207/208/215，全部一致，未漏槽也未漏行。
- 09:30 至 11:00 为修复前采集：五个派生排名字段完整，但八个平台原始名次全部缺失，frame 无 `rankProvenance`。
- 11:30 已按授权用盘后当前缓存代理回填：13 个排名字段缺失均为 0，frame 有 `weighted_platform_percentile_v1` provenance，并保留 `rank_fields_backfilled_from_after_hours_current_cache` 和精确 caveat/auditId。
- 五个 collector run 都是 completed；旧 run 的 source health 没有 provenance，符合当时旧进程行为。
- 12:00 重启后尚未产生新半小时槽位，因此当前只能证明代码/只读 provider 合同，生产自然落库需在 13:30 后验收。

### 当前真实启动缓存只读验证

- `StartupBundleStockProvider` 返回 `healthOk=true`、221 行，13 个排名字段缺失均为 0。
- `avgRankNum/platforms` 按 provenance 逐行重算不一致数为 0。
- 八榜有效名次数分别为 99/99/50/100/86/30/49/100，与 `platformTotals` 完全一致。
- provenance 的公式版本、平台总数、权重、字段映射和默认名次均完整，证明 12:00 新进程已加载修复代码，真实 startup bundle 分支可产出完整原料。

### 当前真实 context 的 builder/quality 演练

- 221 行 provider 输入经 `build_ingest_payload()` 后仍为 221 行，frame `stockRowCount=221`。
- builder 后 13 个排名字段缺失均为 0；record payload 和 frame metadata 均保存同一份 provenance。
- `evaluate_quality()` 返回 `ok=true`、`blockingIssues=[]`、`warnings=[]`。
- 演练全程只读真实缓存，未执行 ingest、未改 MongoDB。

### 运行态 rank-series 统计

- 当前请求 221 只股票，Mongo 返回 217 条非空 series；4 只当前股票没有任何历史有效 `avgRankNum`。
- 最近四个槽位为 10:00/10:30/11:00/11:30，共有 156 只股票四帧齐全，显著高于市场基准最低 20 只。
- 所有返回 bar 的 `rank/totalCount` 均为有效正整数且 `rank <= totalCount`，读模型没有产生非法百分位输入。

### 待确认的高风险问题

- `window_bars=50` 按每股最近 50 次出现截取，221 股合并后公共 frame 并集达到 498 个，横跨 2026-04-21 至 2026-07-28。前端当前没有在 series 模式下再截取最近 50 个市场帧，可能把很久以前的缺槽带入全局时间轴门禁，并增加不必要计算量。
- scheduler 的 collector service 直接调用 repository 写入，FastAPI `/api/snapshots/ingest` 才显式调用 `_invalidate_snapshot_cache_after_ingest()`。需确认 scheduler 写入后是否另有 Redis generation/index 失效，否则 rank-series 可能在 TTL 内继续读旧槽位。

### 已确认 Critical：scheduler 写库未失效 RankTrend Redis 缓存

- `snapshot_collector/service.py`、`service_factory.py`、`scheduler.py` 均无 snapshot cache generation/index 失效调用。
- 只有 FastAPI `/api/snapshots/ingest` 成功后调用 `_invalidate_snapshot_cache_after_ingest()`；scheduler 直接 repository 保存，绕过该入口。
- 正常快照缓存默认 TTL 为 7200 秒。结果是新槽位已写入 MongoDB 后，`ranktrend:rank-series` 仍可能命中旧响应最长 2 小时。
- 页面当前帧排名变化仍能让共振分数变化，因此该缺陷会被“页面已经动了”掩盖，但历史槽位链仍不完整。

### Critical 修复状态

- 已将缓存失效实现下沉为 `snapshot_cache.invalidate_snapshot_cache_after_ingest()`，FastAPI ingest 与 collector 共用。
- `SnapshotCollectorService` 只在 repository 成功保存且 `deduped=false` 后调用；dry-run/blocked/提前 dedupe 不触发。
- 缓存回归测试已按 RED（构造器不支持回调）→ GREEN（1 passed）完成。
- 13:00 自然调度实证：half_hour 221/221 行、13 个排名字段零缺失、公式零偏差、provenance 完整；Redis generation 从 0 增至 3（三种 13:00 快照）。
- 修复后首次 rank-series 请求 `cache.hit=false` 且最新 bar 为 13:00，第二次同参数 `cache.hit=true` 且仍包含 13:00。

### 已确认 Important：per-code 并集污染全市场时间轴

- 498 个公共 frame 中存在 47 处旧时间戳非递增或历史缺槽；现有全局门禁会令全部股票 `insufficient`。
- 最近 50 个市场帧（2026-06-29 13:00 至 2026-07-28 11:30）按理论槽位检查为 0 个异常。
- 不能全局裁掉每股 series：现有合同明确 `window_bars` 是单票窗口，稀疏股票要保留自己的历史并接受个股缺帧检查。
- 修复为只用最近 `getMaxStableBars()` 个公共帧计算全市场样本质量；每股技术/Jump 序列与个股中间缺帧检查仍使用完整 per-code 窗口。
- 回归测试已按 RED（健康股票被旧稀疏帧污染为 insufficient）→ GREEN（status=ok）完成。

### 13:00 生产验收

- scheduler 自然触发 half_hour/hourly/quarter_hour 三个槽位，全部完成；`collection_count=3`、`error_count=0`、`overdue_missing_slots=[]`。
- half_hour frame 与 stock rows 都是 221 行；13 个排名字段缺失均为 0，`avgRankNum/platforms` 公式不一致为 0。
- source health 的 startup bundle 为 ok、221 行且带 provenance；run status 为 completed。
- 唯一 warning 是 `quote_provider_partial`，排名链未受影响，按“保存并打标”规则正常落库。
- Quant API 已在 12:54:24 重启加载本次修复；启动管理器停止旧进程后 30 秒内未自动拉起，最终由同一 uvicorn 命令手动隐藏启动，后续需单独检查启动管理器拉起周期。
