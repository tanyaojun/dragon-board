# 题材/板块轮动引擎（后端重写）设计方案

> 日期：2026-08-04 · 状态：**已实施**（2026-08-04 按审计修订后的计划完成编码，见 §10 与 §11）· 前端只消费后端结果，不再本地计算轮动逻辑

## 1. 背景与问题

现有轮动逻辑在前端 `src/services/theme/ThemeRotationEngine.ts` + `ThemeFactorEngine.ts`，本质是
"当日截面因子 + 上一期内存分析"的两步循环：

- `ThemeFactorEngine` 计算截面因子（breadth/funds/leadership/correlation/persistence/heat）。
- `ThemeRotationEngine` 用因子 + `previous`（内存里的上一期 RotationAnalysis）产出
  `rotationState/rankChange/persistentDays/isMainLine/rotationSpeed/marketPhase`。
- `persistenceScore` 又反过来依赖 `rotationAnalysis.mainLines.persistentDays` —— 循环依赖。

缺陷清单：

1. **无持久化历史**：`previous` 是进程内存态，重启/补采即断，无法回测、无法审计。
2. **因子少且粗糙**：只用 heat/netInflow/momentum/rankChange；没有 资金加速度、板块宽度趋势、
   涨停晋级/连板梯队、拥挤度变化、相对大盘超额、板块成交额占比、主线集中度。
3. **状态判定是硬编码启发式**：`isMainLine = persistentDays>=2 && heat>=70 && inflow>=0`；
   `rotationSpeed = 平均|rankChange|×18`，无理论依据、无量纲校准。
4. **生命周期口径混乱**：前端本地判定只有粗标签；后端 `theme_trend` 另有 8 态词表
   （ignition/expansion/mainline/crowded/divergence/cooling/reversal/neutral），两套不互通。
5. **前端计算不可回测**：轮动结果只进浏览器内存/本地存储，RankTrend/ThemeTrend 回测拿不到。
6. **后端采集链 sector rows 的 rotationState 普遍缺失**：纯后端采集路径（theme_heat →
   factor_to_sector）不写轮动状态（仅浏览器 JSON 导入路径可透传前端值）；而
   `theme_support.py` / `theme_trend.py` / `theme_momentum.py` 都消费它 → 题材策略缺原料。

> 事实修正（2026-08-04 外部审计 A1-A5，见 §10）：①"rotationState 恒缺 0%/从未写入"表述过强——
> 前端 builders → 后端 importers 的 JSON 导入路径可写入；准确表述是"后端自产因子不带
> rotationState"。②前端真正本地推导在 `ThemeFactorEngine.rotationState()`，`ThemeRotationEngine`
> 只是消费。③localStorage 轮动历史写方是 `rotationService.ts`，不在 `ThemeRotationEngine.ts`。
> ④消费者至少 4 个：`theme_support`/`theme_trend`/`theme_momentum`/前端各面板。
> ⑤`snapshot_derivation/projection.py` 已把前端 `rotationAnalysis` 透传为 frame.rotationSummary。

## 2. 设计目标与原则

- **单一事实源**：后端 `ThemeRotationEngine` 是 rotationState/rotationSummary 唯一生产者，
  写入 `snapshot_sector_rows` 与 `frame.rotationSummary`；前端只读。
- **持久化可回测**：只依赖 `snapshot_sector_rows`/`snapshot_stock_rows` 的跨槽位历史序列，
  不依赖进程内存；任意时刻可对任意日期区间重放。
- **无循环依赖**：截面强度因子（theme_heat）与轮动因子（rotation）解耦——
  rotation 引擎只消费 截面因子 + 历史序列，产出独立状态；不再反向改因子。
- **可解释**：每个主题输出 `reasons[]`（结构化原因数组）+ 各因子子分数，供 UI/回测解释。
- **降级可见**：历史不足（补采/新主题）→ 输出 `null + reason`，不伪造状态。

## 3. 数据输入（全部来自已落库事实）

| 输入 | 来源 | 说明 |
| --- | --- | --- |
| 当日截面因子 | `snapshot_sector_rows`（hot_theme） | heatScore/momentumScore/breadthScore/fundScore/leadershipScore/correlationScore/crowdingRisk/persistenceScore/change/mainNetInflow/volumeRatio/ztCount/leaderCount/rank |
| 历史序列 | 同 dataset 同 snapshot_type 的 sector rows（按 slot 升序，默认回看 N=8 槽≈4 小时或跨日） | 动量/加速度/拥挤变化/资金趋势 |
| 涨停/连板结构 | `snapshot_stock_rows`（按 themes 聚合） | boardHeight/highDays/firstZtTime/fengdan → 板块最高连板、涨停晋级率、梯队 |
| 大盘环境 | `frame.indices` / RankTrend `market_regime` | 题材相对大盘超额、情绪周期基准 |
| 昨日涨停表现 | `frame.limitSummary.yesterdayZt`（缺失则降级） | 亏钱效应/溢价 |

## 4. 因子体系

所有子分数统一 0–100；最终 `rotationScore = Σ wᵢ·scoreᵢ`，权重默认值见下表（可配置）。

### 4.1 强度/动量（Strength & Momentum）— 权重 0.30

| 因子 | 定义 | 公式/数据 |
| --- | --- | --- |
| 当日强度 | 题材当日综合强度 | 已有 heatScore |
| 横向相对强度 | 相对全市场题材的 z-score | `(heat - 全市场中位数) / 全市场MAD`，映射到 0-100 |
| 纵向动量 | heat 的 1/3/5 槽变化斜率 | `slope(heat[-5:])`，线性回归斜率归一化 |
| 涨停动能 | 涨停家数 + 环比变化 | `ztCount` 及 `ztCount - ztCount[-1]`，横向比多少、纵向看变化 |
| 板块超额 | 题材 change − 大盘 change | 用 `frame.indices` 主要指数均值；**v1 显式降级**：后端采集链暂无 indices provider（`collect_market_context` 只路由 stocks/quotes/depth/money_flow/themes/limit_up），无 indices 时该因子 None 并从 strength 权重中剔除，reasons 标注 `excess_unavailable`，不伪造 |

### 4.2 资金（Flow）— 权重 0.25

| 因子 | 定义 | 公式/数据 |
| --- | --- | --- |
| 主力净流入 | 当日 mainNetInflow | 已有 |
| 流入加速度 | 1/3 槽累计变化 | `ΣΔ mainNetInflow` 最近 3 槽 |
| 资金集中度 | 题材流入 / 全市场题材流入总额 | 占比 z-score |
| 资金持续性 | 连续为正的槽数 | `persistentInflowDays` |

### 4.3 宽度/结构（Breadth & Structure）— 权重 0.20

| 因子 | 定义 | 公式/数据 |
| --- | --- | --- |
| 板块宽度 | 涨跌/强势/涨停占比 | 已有 breadthScore + 变化 |
| 晋级率 | 昨日涨停今日连板占比 | stock_rows boardHeight 跨槽聚合（缺昨日则降级） |
| 梯队完整性 | 最高连板 + 次高连板差值 | 板块 max boardHeight / 次高 |
| 龙头集中度 | leaderCount 占比 | 龙头数 / 成分数 |

### 4.4 拥挤/风险（Crowding & Risk）— 权重 0.15

| 因子 | 定义 | 公式/数据 |
| --- | --- | --- |
| 拥挤度 | 已有 crowdingRisk + correlationScore | 板块内配对相关性（涨跌幅/换手/量） |
| 拥挤变化 | 1/3 槽 crowdingRisk 变化 | 加速上升 = 过热预警 |
| 量能偏离 | volumeRatio 高分位占比 | `P90(volumeRatio)` 归一化 |

### 4.5 轮动位置/生命周期（Lifecycle & Rotation）— 权重 0.10

| 因子 | 定义 | 公式/数据 |
| --- | --- | --- |
| 状态连续性 | 与上一槽状态一致程度 | 状态机转移打分 |
| 轮动速度贡献 | 主题 rank 相对全市场的波动 | rankChange 归一化 |

## 5. 状态机

### 5.1 主题生命周期 `lifecycle`

五状态 + `neutral` 兜底（对齐市场共识的情绪周期）：

| 状态 | 判定（默认阈值，可配） | 典型证据 |
| --- | --- | --- |
| `ice` 冰点 | heat<35 且 momentum<40 | 无涨停/负资金 |
| `emerging` 萌芽 | momentum 加速 + heat 40-60，持续 1-2 槽 | 首现涨停、资金由负转正 |
| `expanding` 发酵 | heat≥60 且 inflow 持续≥2 槽且拥挤<70 | 晋级率升、宽度升 |
| `climax` 高潮 | heat≥80 且拥挤≥75 或 最高连板≥7 | 梯队完整、量能过热 |
| `cooling` 退潮 | momentum<35 或 连续 2 槽 inflow<0 | 晋级率降、溢价转负 |
| `neutral` 中性 | 其余（数据不足以落入五态） | 观察 |

**转移约束**：state 转移必须相邻（ice↔emerging↔expanding↔climax↔cooling，cooling→emerging 视为反转）；
非相邻跳变（如 ice→climax）钳制到相邻中间态并在 reasons 标注 `transition_clamped`，避免单槽任意跳变。

### 5.2 轮动状态 `rotationState`

在 lifecycle 之上叠加方向与主线性：

- `mainline`：expanding/climax 且 横向相对强度 z-score 前列（默认 Top3）且 资金集中度 Top3。
- `inflow`：expanding 但非主线（跟随）。
- `outflow`：momentum 转负但未到 cooling。
- `cooling`：lifecycle==cooling。
- `emerging`：lifecycle==emerging（新机会观察）。
- `neutral`：其余。

### 5.3 市场阶段 `marketPhase`（市场级）

用全市场聚合：连板空间（最高板）、轮动速度、主线集中度、涨停家数：

| 阶段 | 判定 |
| --- | --- |
| `ice` 冰点 | 最高连板≤3 且涨停家数低 |
| `chaos` 混沌轮动 | 轮动速度快（rank turnover 高）且无稳定主线 |
| `rising` 主线上升 | 最高连板 7-9 且有稳定 mainline |
| `climax` 高潮 | 最高连板≥10 或主线拥挤≥80 |
| `cooling` 退潮 | 主题 cooling/outflow 占比≥35% 或 主题内负流入占比≥50%（v1 不用昨日溢价，缺数据降级） |
| `neutral` 平稳 | 最高板 4-6、轮动慢（rotationSpeed<40）、无主线 |

`rotationSpeed` = 全市场主题 rank turnover（`Σ|rankChange| / N`）映射 0-100，另输出
`mainlineConcentration`（Top3 heat 占比）区分"抱团（低轮动）"与"发散（高轮动）"。

**跨日基线（已确认选择①的实现口径）**：历史窗口默认 8 槽，查询范围从当前交易日回溯到
前一交易日（用交易日历 `is_trading_day` 定位），按 `timestamp` 升序取当前槽之前最近 8 槽；
开盘首批槽用前一交易日收盘槽做基线，避免首 90 分钟整片 null。

## 6. 输出合同

### 6.1 sector_rows（每主题新增字段）

```json
{
  "rotationState": "mainline",
  "lifecycle": "expanding",
  "rotationScore": 78,
  "rankChange": -3,
  "heatTrend": 12.5,
  "flowTrend": 0.82,
  "breadthTrend": 6.2,
  "crowdingTrend": 3.1,
  "mainlineConcentrationRank": 2,
  "reasons": ["连续2槽资金流入", "涨停家数环比+4", "相对强度前3"],
  "factorBreakdown": {"strength": 82, "flow": 74, "breadth": 70, "crowding": 45, "lifecycle": 68}
}
```

### 6.2 frame.rotationSummary（市场级）

```json
{
  "marketPhase": "rising",
  "rotationSpeed": 42,
  "mainlineConcentration": 0.36,
  "maxBoardHeight": 8,
  "mainLines": [{"themeId":"BKAI","themeName":"人工智能","rotationScore":78,"rotationState":"mainline","rankChange":-2}],
  "inflowThemes": [],
  "outflowThemes": [],
  "suggestion": "主线上升期：跟踪人工智能等主线",
  "computedAt": 1785835800000,
  "algorithmVersion": "theme_rotation_v2",
  "evidence": {"framesUsed": 8, "qualityIssues": [], "historyLagSlots": 1}
}
```

> **键名硬约束（审计 C1）**：`rotationSummary` 落库必须序列化为 **camelCase**（与设计合同一致，
> 也与现有前端透传的旧行格式一致），禁止把 snake_case dataclass 原样写入。`marketPhase/
> rotationSpeed/mainlineConcentration/maxBoardHeight/mainLines/inflowThemes/outflowThemes/
> computedAt/algorithmVersion/evidence`。

### 6.3 前端消费

- `SectorRotation.vue` / `ThemeFacade` 改为读后端 `GET /api/snapshots/sector-rows` 或新增
  `GET /api/theme-rotation/summary?dataset_id=&snapshot_type=`（返回最新 frame.rotationSummary +
  各主题 rotationState）。
- 删除 `ThemeRotationEngine.ts` 的本地计算与 localStorage 轮动历史；`ThemeFactorEngine` 的
  rotationState/persistence 改为直接透传后端值。
- `quickRotation`（“快速轮动/一日游”）维度在后端引擎 v1 不生产，前端 adapter 保持空数组；
  该维度视为已废弃，后续有明确口径时再恢复。

## 7. 实施计划（TDD）

### Phase A：因子与历史序列（`quant-board/backend/analysis/theme_rotation/`）

- `models.py`：输出合同 dataclass。
- `factors.py`：从 sector_rows 历史序列计算 4.1–4.4 因子（纯函数）。
- `lifecycle.py`：5.1–5.3 状态机（纯函数）。
- `engine.py`：`ThemeRotationEngine.compute(sector_rows_history, stock_rows_history, indices, yesterday_zt) -> ThemeRotationOutput`。
- 测试：golden 用例（构造 8 槽历史 → 期望状态/分数/原因）；边界（历史<3 槽 → null+reason、
  全源缺失、退潮判定、连板数据缺失降级）。

### Phase B：接入采集主链

- `snapshot_collector`：每个槽位入库前调用引擎，把 rotationState/lifecycle/rotationScore/reasons
  写入 sector_rows，rotationSummary 写入 frame；`metadata.derivation` 记录 `algorithmVersion=theme_rotation_v2`。
- 补采/回填时历史不足 → 显式降级标记，不伪造。

### Phase C：API 与前端

- 新增 `GET /api/theme-rotation/summary`（或复用 sector-rows）。
- 前端 `SectorRotation.vue`/`ThemeFacade` 改读后端；删除 TS 本地轮动计算与 localStorage。
- 浏览器真实渲染验证（Playwright）：面板展示后端 rotationState/rotationSummary。

### Phase D：ThemeTrend/RankTrend 消费对齐

- `theme_trend.py` 改为直接消费 sector_rows 的 rotationState/lifecycle（去掉 `_ts_rotation_state`
  的本地重推导）；`theme_support.py` 增加 lifecycle/rotationScore 可选证据。
- 回测 golden 回归：构造含/不含 rotationState 的帧，确认信号路径一致。

## 8. 风险与边界

- **数据粒度**：半小时间隔的历史序列对"日线级主线"有效，但对"日内脉冲轮动"可能过密；
  默认回看 8 槽（≈4h），跨日时按交易日分组避免隔夜噪声。
- **连板/晋级数据依赖**：需要 stock_rows 的 themes+boardHeight 聚合；缺昨日涨停数据时
  晋级率/亏钱效应因子显式降级（reasons 标注），不阻断其他因子。
- **权重主观性**：默认权重来自调研共识，需用历史回放做敏感性验证后再固化；
  先出"可解释"版本，再谈优化。
- **不引入重型依赖**：状态机用规则+阈值（可配 config），不上 HMM/ML（除非回放证明必要）。

## 9. 待确认的关键选择

1. **历史窗口**：默认 8 槽（≈4h）还是 当日全部槽位 + 前一日收盘？影响跨日主线判定。
2. **连板/晋级数据**：是否接受"先做 0-1 版（不含连板梯队），连板数据验证后再加"，
   还是第一版就要求连板聚合（需要额外回放 stock_rows 的板高）？
3. **输出落点**：rotationState 直接写进 sector_rows（回测同源），还是只放 frame.rotationSummary
   + 新 API（sector_rows 由读口派生）？

## 10. 外部审计与修订记录（2026-08-04）

审计报告：`quant-board/docs/theme-rotation/2026-08-04-theme-rotation-engine-audit.md`（未修改业务代码）。

已确认并修订的审计项：

- **C1（camelCase）**：`MarketRotationSummary.to_camel_dict()` 序列化落库，消费端全读 camelCase。
- **C2（生命周期词汇）**：`theme_trend.LIFECYCLES` 扩展新词表；`_build_factor`（回测重放路径）
  优先透传落库 lifecycle，`_infer_lifecycle` 增加新词汇映射。
- **C3（mainLines 被 backendRead 剥掉）**：backendRead 停止剥除 `rotationSummary.mainLines`。
- **C4（market cooling 不可达）**：`market_phase_for` 增加 cooling/neutral 分支。
- **H1（跨日基线）**：`history.py` 用交易日历回溯前一交易日；上一槽股票按 slot_time 精确查询。
- **H2（Supabase 同构）**：`supabase_schema.sql` + `supabase_homomorphic` 同步新列与映射。
- **H3（迁移期混排）**：`rotationSummary.algorithmVersion` 标识引擎版本，消费端按版本分支。
- **H4（rotation_main_line 覆盖）**：当前 API 走 Mongo 透传路径不受影响；SQLite 旧路径仅在
  rotationSummary 无 `algorithmVersion` 时才合并 `rotation_main_line` 行（历史兼容）。
- **H5（下游消费者）**：Task 9 增加全量消费者兼容审计（Battlefield/Regime/Candidate 等）。
- **H6（flow 持续性恒 0）**：streak 由 engine 从历史序列计算后传入 `flow_score`，不读行字段。
- **H7（计划内测试必失败）**：测试夹具与断言已对齐（BKAG 补历史、rotation_speed=8）。
- **H8（主线判定）**：按设计实现"横向 z-score Top3 **且** 资金集中度 Top3"双条件。
- **H9（晋级率字符串 bug）**：`leadStatus` 改为字符串比较，分母改为主题内昨日涨停。
- **9.3 硬缺口**：①indices 无生产者 → 板块超额显式降级（reasons 标注）；②flow streak 由
  引擎计算；③stock rows 无 themeIds → 引擎按 `themes` 列表 + `mainTheme` 归一化归集。

## 11. 实施记录与偏差（2026-08-04）

已按 `2026-08-04-theme-rotation-engine-plan.md` 全部 Task 落地，提交记录见 Git 历史
（`feat(theme-rotation):` / `refactor(theme):` 前缀）。实现与设计/计划的偏差（均已随测试固化）：

1. **晋级率断言口径**：`breadth_score` 复合分为加权平均，主题内晋级率子分命中 100 上限后
   复合分不可能 ≥100；测试改为“晋级子分参与加权且显著高于降级路径”的对照断言，语义不变。
2. **lifecycle ice 判定顺序**：设计 §5.1 的 ice 为 `heat<ice_heat 且 momentum<ice_momentum`
   （AND），实现按此先于 cooling 分支判定；计划初版用 OR 且排在 cooling 之后，与设计矛盾，已修正。
3. **跨日基线的交易日历容错**：`history.previous_trading_day` 在交易日历桥不可用时退化为
   工作日启发（节假日多查无害，日期范围内无数据即空槽），保证跨日基线不阻断。
4. **引擎 trend 字段 None 安全**：上一槽缺 `breadthScore` 等字段时 trend 计算返回 None
   而不是 `round(None)` 抛错（真实数据常见缺字段）。
5. **`fuse_theme_resonance` 调用约定**：该函数签名实为 `(base, exposure, frame_momentum)`，
   计划内示例参数顺序有误，测试按真实签名调用。

## 12. 第二轮修复记录（2026-08-04，code review + 缓存建议）

对照 `2026-08-04-theme-rotation-engine-code-review.md` 与缓存建议的修复：

- **读口 TTL cache**：`GET /api/theme-rotation/summary` 接入现有 Redis read-through
  （`snapshot_cache`，TTL 默认 60s，可配 `QUANT_BOARD_THEME_ROTATION_CACHE_TTL_SECONDS`），
  并把响应 key 注册到 dataset/date 索引，采集落库（ingest）时随现有失效链路清除。
- **前端防旧标记**：面板展示轮动数据的 `slotTime`（含 computedAt tooltip）；最新槽位无引擎
  结果、回退展示上一槽数据时打 `旧槽位` 标记（fail-visible，不静默）。
- **R1**：engine 的 `inflowThemes/outflowThemes` 输出 `[{themeId, themeName}]` 对象，
  adapter 兼容旧字符串形态，面板列表显示中文名。
- **R3**：`market_phase_for` 的 cooling 判定移到 rising 之后，有稳定主线时不再误标退潮。
- **R4**：逐一代查 H5 消费方——`BattlefieldBuilder` 的 persistentDays 归一化为数字、
  主线判定走 `factor.rotationState`（后端值）；candidate 三服务仅透传 rotationSummary；
  ThemeRiskDashboard/ThemeCorrelationPanel 仅展示。未发现 undefined 参与数值计算的路径。
- **R5**：面板轮动数据源类型改用 `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`（非硬编码），
  并在轮动数据 badge 上显示槽位时间。
- **R6**：新增真实中文名 + 后缀差异用例（`人工智能概念板块` vs `人工智能`）锁定归一化。
- **R7**：`theme_momentum` 词表按 rotationState 值域修正——BOOST 有效新词
  `emerging/inflow`（`inflow` 替代死词 `expanding`），PENALTY 移除死词 `climax`。
- **R8**：`engine.compute` 经 `asyncio.to_thread` 移出事件循环（纯函数，线程安全）。
- **R2**：v1 明确“板块超额”恒降级（后端采集链无 indices provider），见 §4.1 与 §12 说明；
  后续补 indices provider 时再启用。
- **R9**：`quickRotation` 维度废弃，前端空数组 + 文档标注。
