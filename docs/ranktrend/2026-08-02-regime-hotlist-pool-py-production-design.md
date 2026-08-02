# RankTrend regime 热榜池口径 + Python 单侧生产设计（P2）

日期：2026-08-02
状态：已与用户逐节确认，待用户 review 后进入实施计划

## 1. 背景与问题

RankTrend 观察面板暴露了两套口径并存的问题：

- **市场中位数**（marketMedianPercentile / marketMedianShortChange）来自八平台热榜池横截面：每帧按 `avgRankNum` 升序重排全部热榜股票，再取百分位分布中位数（`RankTrendObservationService.calculateMarketMedian`、`RankTrendSignalService.applyResonanceFinals`）。
- **市场环境 regime** 的主体来自全 A 统计：`marketRegimeAnalyzer` / Python `market_regime()` 使用通达信 `scglobaldata` 的涨跌家数、涨停/跌停数、成交额和情绪阶段打分，只有"热榜资金正向占比""量能活跃占比"两个因子来自热榜池。
- **生命周期分层**（candidateTier）以 regime 为硬门槛：`A_MAIN` 禁 `weak/retreat`，`B_IGNITION` 禁 `retreat`，`weak` 时买入信号降级 `N_NEUTRAL`。

在 A 股两级分化行情下，全 A 涨跌家数不能代表热榜池题材的赚钱效应：全 A 跌多涨少会把 regime 打成 weak/retreat，题材内部强赚钱效应被压掉，A/B 分层失真；反之指数平稳但热榜退潮时又会虚假放行。观察面板把"市场中位数（池内）"与"市场环境（全 A）"并排展示时方向相反是必然结果。

此外发现现存 golden 偏差：TS 与 Python 的 regime 状态阈值不一致（TS `normal>=52/weak>=35`，Python `normal>=50/weak>=25`）。

## 2. 目标与非目标

### 目标

1. regime 改为**热榜池口径五因子**，与市场中位数、生命周期分层的 universe 统一。
2. **RankTrend golden TS/Python 完全一致**：算法统一在 Python 侧生产，TS 只消费计算结果，不保留第二份实现。
3. 分层算法随 regime 口径同步优化。

### 非目标

- P2 阶段不迁移 TS live-only 观察层（resonance、jump 应用层、观察面板横截面）到 Python；该部分列入 P3。
- P2 阶段不做参数搜索式调参（防过拟合，见 5.4）。
- 不新增 regime 落库字段（按需计算 + 缓存，见 6.3）。

## 3. 已确认的设计决策

1. regime 指标组合：上涨占比 + 涨停强度 + 量能活跃 + 资金正向 + 情绪阶段参考，剔除全 A 涨跌家数/成交额主导。
2. 落地边界选 P2：Python 生产整条 golden 链输出（technical/cycle/risk/decision/observation/strategy/executionStrategy/regime/jump），TS 前端消费；resonance/jump 应用层留 TS（live-only），P3 收尾。
3. API 形态：新增 `POST /api/ranktrend/analyze` 批量分析接口 + `GET /api/snapshots/frames` 每帧附带 regime；regime 按需计算 + Redis 缓存，不新增落库字段。
4. TS 不保留第二份实现：后端不可用时前端直接显示"分析不可用"+ 结构化原因，不静默降级、不伪造结果。
5. 字段所有权矩阵确认（见 8）：jump 事件检测收敛到 Python 输出，TS 只保留应用层；observation、executionStrategy 由 Python 补齐。

## 4. P2/P3 边界与数据流

### P2（本次）

- Python 生产：meta/sampleQuality、technical、cycle、risk、decision、observation、strategy、executionStrategy、regime、jump 事件检测。
- TS 保留（live-only 观察/展示）：resonance（含市场中位数横截面计算）、jump 应用层（持仓管理/通知）、statusClassifier 展示投影、排名序列组装（供 resonance/观察轨）。
- TS 删除：全部本地 golden 链算法实现（7.1 文件清单）。

### P3（后续，方案已写入本文档 12 节）

- resonance、jump 应用层、观察面板历史帧横截面迁移到 Python，TS 彻底零算法、只做展示和 fallback 状态。
- golden 方向文档正式反转（Python 为源、TS 校验）。

### 数据流

```text
MongoDB stock rows / frames（ingest 落库，含 change/volumeRatio/zlje/zljzb/avgRankNum）
        |
QuantBoard Python 后端
  |-- POST /api/ranktrend/analyze：当前帧或历史帧批量分析（golden 链 + 五因子 regime）
  |-- GET /api/snapshots/frames：每帧附带 regime（五因子，热榜池横截面）
  '-- rank-series（已有，供 TS live-only resonance 使用）
        |  HTTP（本地 3000 -> 8000）
Dragon Board TS 前端
  |-- 实时链路：每轮调 analyze API，覆盖 stock.rankTrend；失败 -> analysisUnavailable
  |-- 观察面板：历史帧 regime 读 frame.regime，历史帧分析读 analyze API
  '-- live-only：resonance / jump 应用 / 展示投影（P3 再迁）
```

## 5. regime 五因子口径定义

### 5.1 输入

每帧热榜池股票行（stock rows 已落库字段）：`change`、`volumeRatio`、`zlje`、`zljzb`、`avgRankNum`、`firstZtTime`/`lianbanStr`（涨停判据二选一，见 5.3）。外加该帧 `sentiment`（情绪阶段参考项）。

TS 与 Python 使用同一输入合同：`{ stocks: [...], sentiment: {...} }`，单帧即可计算，不需要跨帧序列。

### 5.2 因子与权重方向（权重最终值在样本验证后冻结，不做搜索调参）

| 因子 | 计算方式 | 权重方向 |
| --- | --- | --- |
| 池内上涨占比 | `change > 0` 的池内股票占比 | 主因子，替代全 A up/down 扩散 |
| 池内涨停强度 | 涨停占比或连板高度中位数（判据见 5.3） | 主因子，替代全 A zt/dt |
| 池内量能活跃占比 | `volumeRatio >= 1.2` 占比（沿用现有） | 现有因子保留 |
| 池内资金正向占比 | `zlje > 0` 占比（沿用现有） | 现有因子保留 |
| 情绪阶段参考 | DragonBreath 阶段（高潮/发酵/启动/退潮/冰点） | 参考项，权重降低或剔除 |

全 A 的 `upCount/downCount/ztCount/dtCount/totalAmo` 从打分主体剔除；保留在输出 `reasons`/背景字段供展示，不进分数。

### 5.3 待冻结口径（样本验证时二选一，禁止两套并存）

- 涨停判据 A：`change >= 9.8`（简单、字段稳定）。
- 涨停判据 B：`firstZtTime` 非空或 `lianbanStr` 有效（严格，依赖涨停池字段完整性）。

### 5.4 防过拟合约束

- 五因子固定权重、固定阈值，冻结后不做参数搜索式调参。
- 先用真实落库样本做"全 A regime vs 池内 regime"分层差异对比 + 样本外抽查，确认方向后再冻结 golden。
- golden case 固定输入输出，TS/Python 共用同一套 case。
- 状态阈值统一一套（TS/Python 同一常量）：`strong >= 70 / normal >= 50 / weak >= 30`，`retreat` 为其余；最终值在样本验证后冻结。

## 6. API 设计

### 6.1 POST /api/ranktrend/analyze（新增）

Python 侧新 router：`backend/api/ranktrend_routes.py`。

请求：

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "codes": ["002279", "603580"],
  "frameKeys": ["2026-08-02 14:00"],
  "currentFrame": {
    "tradingDate": "2026-08-02",
    "slotTime": "14:00",
    "stocks": [
      { "code": "002279", "rank": 1, "avgRankNum": 2.5, "change": 3.2, "volumeRatio": 1.5, "zlje": 123, "zljzb": 0.2, "platforms": 5 }
    ]
  }
}
```

- `frameKeys` 省略 = 最新帧；可一次传多个历史帧（观察面板最多 22 帧批量）。
- `currentFrame` 为 live 模式：TS 上传当前内存 stocks（比落库帧新），Python 组装当前帧 + MongoDB 历史 rank series 后跑 golden 链。
- `codes` 为空 = 该帧全池。

响应：

```json
{
  "ok": true,
  "frames": [
    {
      "frameKey": "2026-08-02 14:00",
      "regime": { "state": "strong", "score": 78.2, "reasons": ["池内上涨72%", "池内涨停9%"] },
      "totalCount": 221,
      "stocks": [
        { "code": "002279", "analysis": { "meta": {}, "technical": {}, "cycle": {}, "risk": {}, "decision": {}, "observation": {}, "strategy": {}, "executionStrategy": {} } }
      ]
    }
  ],
  "source": "py_golden",
  "issues": []
}
```

### 6.2 GET /api/snapshots/frames（扩展）

响应中每个 frame 增加 `regime` 字段：Python 用该帧 stocks 横截面计算五因子，无额外 DB 成本。观察面板历史帧直接消费，不再本地计算。

### 6.3 缓存与失效

- 缓存键：`ranktrend:analyze:{dataset_id}:{snapshot_type}:{frame_key}:{codes_hash}:{stocks_version}`。
- TTL 60s（对齐前端 1 分钟刷新），复用现有 Redis snapshot cache generation/index 失效机制。
- frames 的 regime 走现有 frames 缓存，key 含帧内容，算法升级后随缓存失效自动重算。

## 7. TS 端改造

### 7.1 删除文件（本地 golden 链实现）

```text
src/services/rankTrend/runRankTrendAnalysisPipeline.ts
src/services/rankTrend/technicalSignalAnalyzer.ts
src/services/rankTrend/attentionCycleAnalyzer.ts
src/services/rankTrend/riskSignalAnalyzer.ts
src/services/rankTrend/candidateTierComposer.ts
src/services/rankTrend/executionCandidateTierComposer.ts
src/services/rankTrend/resultComposer.ts
src/services/rankTrend/observationScoreComposer.ts
src/services/rankTrend/marketRegimeAnalyzer.ts
src/services/rankTrend/jumpDetector.ts               # 检测收敛 Python，不再本地重算事件
```

以及 `src/services/rankTrend/utils.ts` 中仅供 golden 链使用的部分（MACD/动量最小窗口等；保留 resonance/jump 需要的部分）。相关 golden 链 TS 测试同步删除或改为消费契约测试。

### 7.2 保留文件（live-only / 展示）

```text
src/services/rankTrend/resonanceAnalyzer.ts           # live-only，P3 迁
src/services/rankTrend/jumpSignalService.ts           # 应用层：消费 rankTrend.jump，不再本地重算事件
src/services/rankTrend/statusClassifier.ts            # 展示投影
src/services/rankTrend/RankTrendObservationService.ts # 改为消费 Python 输出
src/services/rankTrend/types.ts                       # 契约类型保留
```

### 7.3 实时链路改造

`RankTrendAnalyzer.getRankTrends` / `RankTrendSignalService.refreshRankTrendSignals` 改为：

1. 组装 `currentFrame`（当前内存 stocks 最小字段集）+ codes + frameKeys。
2. 调用 `POST /api/ranktrend/analyze`。
3. 成功：用返回结果覆盖 `stock.rankTrend`，`source: 'py_golden'`。
4. 失败：`stock.rankTrend` 置 `analysisUnavailable` + 结构化原因，展示"分析不可用"；不调用任何本地 golden 链算法。
5. `applyResonanceFinals` 保留（live-only）：用 TS 横截面中位数覆盖 `decision.final`（观察口径），Python `decision` 作为 golden/回测标准。
6. `applyJumpSignals` 保留（live-only 应用层）：改为消费 Python 输出的 `rankTrend.jump` 事件，不再调用本地 `detectRankJumps` 重算；Jump 事件字段合同以 Python golden 输出为准。

### 7.4 观察面板改造

- 历史帧 regime 读 `frame.regime`（frames API）。
- 历史帧 technical/cycle/risk/decision/observation/strategy 调 analyze API（frameKeys 批量）。
- resonance 轨的横截面/市场中位数仍在 TS（live-only）。
- Python 不可用：面板显示"分析不可用"+ 原因，不展示伪造结果。

### 7.5 apiService

新增 `analyzeRankTrend(payload)` 方法，走 `/api/ranktrend/analyze`。

## 8. 字段所有权矩阵（P2 后）

| 字段 | 生产者 | 说明 |
| --- | --- | --- |
| meta / sampleQuality | Python | 已有 |
| technical / cycle / risk / decision | Python | 已有 |
| strategy / executionStrategy | Python | executionStrategy 需补齐进输出合同 |
| observation | Python | 需补齐（TS observationScoreComposer 的 Python 移植） |
| regime | Python | 五因子池内口径，重写 market_regime |
| jump（事件检测） | Python | 已有；TS 应用层改为消费输出 |
| resonance / 市场中位数 | TS（live-only） | P3 迁 Python |
| 展示状态 / tooltip | TS | 纯展示投影，永远留在 TS |

## 9. Python 侧补齐

1. 重写 `market_regime()`：五因子池内口径（见 5），状态阈值与 TS 统一。
2. 补齐 `observation`：移植 TS `observationScoreComposer`（stageFitness/pathCommitment/momentumConfirmation/riskSafety 四因子）。
3. 补齐 `executionStrategy`：`compose_strategy` 与 `compose_analysis_candidate_tier` 同时输出为 `executionStrategy` + `strategy`，对齐 `RankTrendAnalysisResult` 合同。
4. 新增 `backend/api/ranktrend_routes.py`：analyze API。
5. frames API 每帧附 regime。
6. golden case 由 Python 侧生成，TS 消费校验。

## 10. golden 方向反转与文档合同

P2 落地时同步更新：

- `AGENTS.md` 4.2：golden 方向从"TS 是 Python 移植的 golden 标准"改为"Python 为生产事实标准，TS 消费并校验"。
- `quant-board/docs/ranktrend-golden.md`：来源与校验方向反转。
- `quant-board/docs/ranktrend-python-port.md`：对齐目标改为 Python 自身合同。
- `quant-board/docs/AI_COLLABORATION.md`：同步口径。

## 11. 验证与回测

- Python 单测：五因子 regime golden case；observation/executionStrategy 对齐 golden case；analyze API 合同测试。
- TS 单测：消费逻辑（mock API）；"分析不可用"行为；观察面板读 `frame.regime`；删除后的契约测试清理。
- QuantBoard：新 regime + 分层回测基线，对比旧基线分层分布与 A_MAIN/B 准入变化。
- 浏览器：Playwright 验收主表/观察面板显示 Python 结果；离线场景显示"分析不可用"。
- `pnpm test:ranktrend`、`pnpm typecheck:ranktrend`、`pnpm test`、QuantBoard `pytest`。

## 12. P3 后续范围（方案写入，P2 验证后启动）

1. resonance / jump 应用层迁移 Python：前端只消费，删除 `resonanceAnalyzer`、`jumpDetector`、`jumpSignalService` 的计算实现。
2. 观察面板历史帧横截面（市场中位数）迁移 Python：frames API 或 analyze API 输出每帧横截面基准。
3. TS 端完成零算法收尾，仅剩展示与"分析不可用"状态。
4. golden 方向文档正式反转完成态确认。

## 13. 风险与回退

- **回测基线漂移**：regime 口径 + 阈值变化会改变 A/B 分层分布，QuantBoard 回测结果整体变化；P2 落地前先跑新旧基线对比，用户确认后再冻结。
- **前端可用性依赖**：实时链路依赖 Python 后端在线；按设计，后端不可用时显示"分析不可用"，不伪造结果（符合 fail-visible：保留原始排名路径与原因展示）。
- **Python 补齐工作量**：observation/executionStrategy 需移植并补 golden case，是 P2 的主要新增工作。
- **回退策略**：删除的 TS 算法文件可经 git 恢复；P2 落地分阶段（Python 补齐 + API、TS 消费切换、删除 TS 实现），每阶段可独立回退。
