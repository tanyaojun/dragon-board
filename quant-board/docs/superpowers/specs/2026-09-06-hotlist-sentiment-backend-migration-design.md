# 热榜情绪计算后端化——前端只消费生产数据设计

状态：已批准（2026-09-06，brainstorming 结论 + 用户确认"前端 TS 计算逻辑要删除"）

## 动机

热榜情绪当前存在三条链路分叉，同一交易日可能产出不同结论：

1. **前端完整版**（`src/services/hotlist/HotListSentimentAnalyzer.ts`，1341 行）：5 证据 evaluator + resolveStage 级联 + 8 状态分类，仅用于 DragonBreathPanel 展示。
2. **后端简化复算**（`backend/operations/hotlist_sentiment.py`）：EOD 入库生产链，`_resolve_stage` 是聚合阈值级联，与前端完整版口径不同——生产库里的数据不是前端展示的口径。
3. **引擎消费**（`backend/analysis/ranktrend/trend/risk.py` `market_regime`）：读库中 `hotlistSentiment.stage/riskLevel`，regime 门控打分直接受链路 2 的简化口径影响。

用户决策（2026-09-06）：**前端 TS 计算逻辑全部删除，前端只消费后端生产数据**。全系统收敛为单一实现、单一口径。

附带发现：`/api/hotlist-sentiment` 后端路由已存在（`backend/api/hotlist_routes.py` 的 `POST /ingest`），但 proxy-server 的 `QUANT_BOARD_PREFIXES` 未转发该前缀（`proxy-server/routes/quantBoardProxy.js`），DragonBreathPanel 历史注释里的 404 死链至今真实存在。本次一并修复。

## 范围

- 新建 `backend/analysis/hotlist/sentiment.py`：`compute_hotlist_sentiment` 纯函数，作为唯一权威实现（前端展示、EOD 入库、引擎 provider 三方共同消费）。
- `backend/operations/hotlist_sentiment.py` 简化版逻辑改为调用新纯函数（消除后端内部双口径）。
- 新增读口 `GET /api/hotlist-sentiment/series`（lazy compute + upsert），挂现有 `hotlist_routes.py` router。
- proxy-server `QUANT_BOARD_PREFIXES` 增加 `/api/hotlist-sentiment/`。
- 前端删除 `HotListSentimentAnalyzer.ts` 及其测试，新增薄 API client + 类型契约，DragonBreathPanel 切换。

## 非范围

- 不改 `market_regime` 的打分权重（REGIME_STAGE_ADJUST 等）。
- 不解决回测 lookahead（日粒度情绪按 tradingDate 注入当日全部帧的未来函数）——那是 WP1c 时点查询的课题。
- 不做槽位级（intraday 多帧）情绪落库——WP1b 另立。
- 不改 `src/types/emotion.ts` 统一情绪中心（独立模块，不依赖被删文件）。
- 不改 DragonBreathPanel 池列表的实时行展示（那是数据加载，不是情绪计算）。

---

## 1. 后端纯函数——`backend/analysis/hotlist/sentiment.py`

新目录 `analysis/hotlist/`，符合 backend 分层约束（算法 → `analysis/`）。

### 1.1 签名与输入

```python
def compute_hotlist_sentiment(
    rows: list[dict],            # 当日热榜池行（已 join displayStatus，见 1.2）
    yesterday_rows: list[dict],  # 前一交易日行
    day_before_rows: list[dict], # 前两交易日行
    frame_evidence: dict,        # frame.limitSummary 市场证据
) -> dict:
```

纯函数：不做任何 I/O，不持有 db 句柄，同输入恒同输出。缺失/NaN/空池/时间乱序按 fail-visible 处理——输出结构化标注（`statusSourceCounts`、`missingEvidence`），不伪造状态、不静默补默认值。

### 1.2 行数据契约

- 每行 = `snapshot_stock_rows` 行 + join `snapshot_analysis` 的 `displayStatus`（8 状态后端 golden 已有 `compute_display_status` 生产链）。
- 无 `displayStatus` 的行走 TS `getFallbackHistoricalStatus` 等价口径（moneyWeak = `zlje<0 || zljzb<=-8 || (cddje<0 && cddjzb<=-3)`，与 operations 现版一致），并以 `statusSourceCounts = {displayStatus: N, fallback: M}` 标注来源分布。
- `frame_evidence` 来自 `frame.limitSummary`（`snapshot_derivation/projection.py` 已物化：continuousBoards/zhaban/yesterdayZt/thsPools）。映射到 TS 版 `DragonBreathMarketDataLike`（ztCount/zhaban/limitData/maxContinuousDays/thsLimitUpPools）时如遇字段缺口，实施时以 limitSummary 实际字段为准补齐；缺失证据降级为 `missingEvidence` 标注，不伪造。

### 1.3 输出 schema（现有库文档 schema 的超集）

必含现有字段（保持引擎 `market_regime` 读 `stage`/`riskLevel` 不受影响）：

```json
{
  "stage": "高潮", "riskLevel": "低", "confidence": 78, "summary": "…",
  "metrics": { "poolSize": 218, "allPoolUpRatio": 0.48, "hotTrin": 0.82,
               "retentionRate1d": 0.73, "limitIntersectionRate": 0.18, "…": 0 },
  "turnover": { "…": "同现有 schema" },
  "signals": ["…"], "warnings": ["…"],

  "layers":        { "top20": {…}, "top50": {…}, "top100": {…}, "all": {…} },
  "comparison":    { "totalChange1d": null, "top100RetainRateFromYesterday": 0.7, "…": null },
  "limitEvidence": { "market": {…}, "intersection": {…}, "yesterdayHotLimit": {…} },
  "statusSourceCounts": { "displayStatus": 180, "fallback": 38 },
  "missingEvidence": []
}
```

TS 完整版移植清单：5 证据 evaluator（tapeStrength/moneyAcceptance/opportunityExpansion/riskPressure/continuity）、resolveStage 级联（退潮→高潮→发酵→启动→冰点，级联短路语义保持）、8 状态分类、top20/50/100/all 四层 metrics、三日 comparison、limitEvidence 三组、turnover 进出明细。

## 2. operations 统一——消除后端内部双口径

`backend/operations/hotlist_sentiment.py` 改造：

- `_fallback_status_label` / `_resolve_stage` / `_compute_metrics` 的状态与阶段判定逻辑删除，`build_hotlist_sentiment_document` 改为编排：取数 → join displayStatus → 调 `compute_hotlist_sentiment` → 落现有库 schema。
- `HotListSentimentBackfillService` 的取数/回填调度骨架不变（`run_for_date` / `run_for_latest_day` / EOD 调度点 `operations/schedule.py` 不动）。
- **口径升级说明**：EOD 入库从简化级联升级为完整版级联，新写入文档的阶段分布可能与历史简化口径有差异；引擎 provider 读的是同一字段，regime 门控行为随之对齐完整版。历史文档不批量重算（如需重算走既有 backfill 服务显式执行）。

## 3. 读口 API——`GET /api/hotlist-sentiment/series`

挂现有 `hotlist_routes.py` router（prefix 已是 `/api/hotlist-sentiment`）。

```
GET /api/hotlist-sentiment/series?dataset_id=dragonboard_live&snapshot_type=half_hour&days=3
```

- 返回最近 N 个 trading_date 的情绪文档，升序，前端 DragonBreathPanel 直接消费（今天+昨日+前日）。`days` 默认 3，上限 30（超限按 30 截断）。
- lazy compute 并发安全：多请求同时触发时重复计算无害，`replace_one` upsert 幂等，无需加锁。
- **lazy compute**：最新交易日若无库行 → 取当日最新帧 + 前两日 rows + join displayStatus + frame.limitSummary → `compute_hotlist_sentiment` → upsert → 返回；第二次请求直接读库（幂等）。
- 编排逻辑放 `backend/services/theme/`（新建 `hotlist_sentiment_compute.py`），`hotlist_sentiment_service.py` 保持纯存储封装（upsert/get_by_date/单例/provider 不动）。
- fail-visible：无帧/空行时返回 `{"ok": false, "degraded": true, "reason": "…"}` 结构化错误，不返回伪造的情绪文档；HTTP 200 + degraded 标记（与 proxy 降级风格一致）。

## 4. proxy-server 转发修复

`proxy-server/routes/quantBoardProxy.js` 的 `QUANT_BOARD_PREFIXES` 数组增加 `'/api/hotlist-sentiment/'`。注意与既有 `'/api/sentiment/'`（全市场情绪）不冲突——前缀不同。该端点为 lazy-compute 读口，**不加入** `CACHEABLE_RESOURCES`（首次请求触发计算，缓存会导致依赖的帧数据更新后返回过期情绪）。

## 5. 前端改造——删除计算，只消费

| 动作 | 对象 |
|---|---|
| 删除 | `src/services/hotlist/HotListSentimentAnalyzer.ts`（1341 行计算逻辑 + `persistHotListSentiment` 死代码） |
| 删除 | `src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts`（golden 先提取，见 §7） |
| 新增 | `src/types/hotlistSentiment.ts`：后端响应类型契约（`HotListStatusLabel` / `HotListDayMetrics` / `HotListLayerSet` / `TurnoverResult` / `HotListLimitEvidence` / `HotListSentimentResult` 等迁移自被删文件；只定义类型，不含任何计算） |
| 新增 | `src/services/hotlist/hotlistSentimentApi.ts`：薄 API client，`fetchHotlistSentimentSeries(days)` → 类型化返回；**无前端兜底计算**——后端错误/降级时返回错误态，面板展示错误提示与数据缺失标注 |
| 改造 | `src/components/panels/DragonBreathPanel.vue`：导入切换 + `loadHotListSentiment`（L1292-1358）重写为调 API client，三日序列全部来自后端 |

保留：DragonBreathPanel 池列表实时行展示（dataLayer 数据加载，非情绪计算）、`src/types/emotion.ts`（独立统一情绪中心）。

## 6. 实时性行为变化（用户已确认）

- 迁移前："今天"情绪 = DataLayer 实时行瞬时值（秒级），但与库内 EOD 数据口径不同。
- 迁移后："今天"情绪 = 最新已采集帧口径（half_hour 最多延迟 30 分钟，收盘后为 EOD），与引擎/回测/历史完全同口径。
- 面板应在 UI 上标注数据时点（slotTime），让"这是 10:30 帧的结论"可见。

## 7. 测试策略（TDD 顺序）

1. **golden fixture 提取（删除前）**：从 `HotListSentimentAnalyzer.test.ts` 现有用例提取代表性 case 的输入（rows/marketData）与期望输出（stage/statusCounts/layers 关键字段），固化为 `quant-board/tests/fixtures/hotlist_sentiment/golden_*.json`。覆盖：各阶段判定边界、fallback 与 displayStatus 混合来源、空池、资金字段缺失、limitEvidence 缺失。
2. **Python 纯函数 golden 对齐**：`quant-board/tests/test_hotlist_sentiment_compute.py` 加载 fixture 断言 `compute_hotlist_sentiment` 输出一致（红 → 移植实现 → 绿）。
3. **operations 统一回归**：现有 `test_hotlist_sentiment_backfill.py` 适配新编排；`build_hotlist_sentiment_document` 输出仍满足现有库 schema 断言。
4. **API 测试**：`test_hotlist_sentiment_api.py` 扩展 series 端点——lazy compute 幂等（二次调用读库不再计算）、days 窗口排序、无帧 degraded 结构、空行 degraded 结构。
5. **前端 API client 测试**：`src/services/hotlist/__tests__/hotlistSentimentApi.test.ts`——正常解析、degraded 错误态透传、无兜底计算。
6. **验证命令**：`quant-board` 目录用 `.venv\Scripts\python.exe -m pytest tests/test_hotlist_sentiment_compute.py tests/test_hotlist_sentiment_backfill.py tests/test_hotlist_sentiment_repo.py tests/test_hotlist_sentiment_api.py`（全量 pytest 有挂起问题，先 collect-only 再跑相关子集）；根项目 `pnpm test -- hotlistSentiment` + `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。

## 8. 文档同步

- 本 spec 落盘即主文档；实施完成后在 `docs/热榜情绪分析器方案.md` 头部追加"已迁移后端"注记与 spec 链接。
- `AGENTS.md` 第 3 节 backend 分层示例无需改动（`analysis/hotlist/` 符合"算法 → analysis/"既有约束）。
- 实施记录（迁移后删除清单、行为变化）追加到本 spec 末尾"实施记录"节。

## 9. 风险与回退

- **口径切换风险**：EOD 新入库数据口径从简化版升级为完整版，阶段分布可能变化。缓解：golden fixture 锁住完整版行为；历史文档不重算，回退 = revert operations 改动（入库回到简化口径，schema 不变，引擎消费不断裂）。
- **前端实时性降级**：≤30 分钟延迟。缓解：面板标注 slotTime。
- **frame.limitSummary 字段缺口**：limitEvidence 部分组可能算不出来。缓解：fail-visible 标注，不伪造；实施时以实际字段为准。
- **删除面大**（1341 行 + 测试）：golden fixture 先行，TS 实现删除后如需回退，git revert 一次提交即可恢复。

## 10. 实施顺序概要

1. golden fixture 提取（从现有 TS 测试）。
2. `analysis/hotlist/sentiment.py` 纯函数 + golden 对齐测试（TDD）。
3. operations 统一 + 回归适配。
4. service compute 编排 + series API + API 测试。
5. proxy 转发前缀。
6. 前端类型契约 + API client + client 测试。
7. DragonBreathPanel 切换 + 类型检查。
8. 删除 TS 计算与旧测试。
9. 文档注记 + 全量相关验证。

---

## 11. 实施记录（2026-09-06 完成）

- **提交链**：`fba8964d`..`88c91c81`（BASE 885d3bb6，共 10 个提交，逐任务 TDD + 审查）。
- **删除清单**：`src/services/hotlist/HotListSentimentAnalyzer.ts`（1341 行计算逻辑 + 死代码 persistHotListSentiment）、`src/services/hotlist/__tests__/HotListSentimentAnalyzer.test.ts`（19 个 it，18 个 case 提取为 golden fixture 后删除）。
- **新增清单**：`backend/analysis/hotlist/sentiment.py`（913 行纯函数，18 case golden 全量对齐 `quant-board/tests/fixtures/hotlist_sentiment/golden_cases.json`）；`GET /api/hotlist-sentiment/series`（lazy compute 最新日 + 缺失日 fail-visible 标注，days 默认 3 cap 30）；`backend/services/theme/hotlist_sentiment_compute.py`（读口编排：displayStatus join + limitSummary→market_data 映射）；proxy 前缀 `/api/hotlist-sentiment/`（不入 CACHEABLE_RESOURCES）；前端 `src/types/hotlistSentiment.ts` + `src/services/hotlist/hotlistSentimentApi.ts`（薄 client，无兜底计算，missingDays 透传）。
- **行为变化**：① 前端"今天"情绪从 DataLayer 实时行秒级瞬时值 → 最新已采集帧口径（half_hour 最多延迟 30 分钟），与引擎/回测/历史完全同口径，面板标注数据时点（slotTime）与窗口缺失日；② EOD 入库口径从简化级联升级为完整版级联（历史文档不重算，需要时走既有 backfill 服务显式执行）；③ DragonBreathPanel 旧 daily 帧查询/30min LRU 缓存删除，改为 series 读口 + 30 分钟节流。
- **实施裁决**：① client additive 扩展 `missingDays`（spec §5 数据缺失标注要求，缺失日 reason 逐日透传）；② 全窗口缺失（ok + items 全 missing）时面板错误态保留缺失明细；③ cap-30 测试改真断言（种子 35 天，`== 30`）；④ proxy 前缀边界回归用例（`hotlist-sentimentx` 不误转发）。
- **遗留观察项（首个上线日人工验证）**：① `_build_market_data_like` 映射零测试覆盖，须对照真实 `frame.limitSummary` 字段核对 ztCount/maxContinuousDays 推导；② `run_for_date` 与 `_compute_and_persist` 各多一次 `trading_dates` 投影查询（低频路径性能项，暂不收敛）；③ series 成功路径浏览器端到端（后端 8000 与 proxy 3000 需重启到含新路由的实例）。
