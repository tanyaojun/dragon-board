# 题材动量（Theme Momentum）v2 重构设计：独立第四维板块动量

> 日期：2026-08-06 · 状态：**已批准（2026-08-06，brainstorming 流程）**
> 触发：2026-08-04 题材/板块轮动引擎 + 题材动量（板块共振）上线实盘观察数日，用户反馈三条，方向性推翻"题材动量并入个股共振"的旧设计。
> 关联文档：`quant-board/docs/theme-rotation/2026-08-04-theme-rotation-engine-design.md`、`docs/theme-module/2026-08-04-theme-momentum-resonance-design.md`。
> 归属：QuantBoard 题材模块方案，文档目录沿用 `quant-board/docs/theme-rotation/`。
> 2026-08-06 补充：**结构迁移**——`backend/analysis/theme/` 与 `backend/analysis/ranktrend/` 包归拢，下文所有代码路径均已使用新结构（旧路径 `backend.analysis.theme_heat` 等保留薄 stub 兼容）。

## 1. 核心目标（5 句话以内）

1. 把题材动量从"个股共振的有限调节项"中完全解耦，提升为与 RANKTREND OBSERVATION 三轨（共振/技术/阶段）并列的**第四个独立维度**。
2. 题材动量描述**题材/板块作为整体的上涨/下跌强度与扩散状态**，不再照搬个股生命周期分层（ice/emerging/expanding/climax/cooling）。
3. 时间尺度改为**日线级主口径 + 半小时槽位日内状态辅口径**双层，匹配"题材周期 1-3 天至半个月"的现实尺度。
4. 题材动量与个股动量是两个维度：个股动量看单股关注度路径，题材动量看板块内部赚钱效应扩散/收敛，两者不互相调节。
5. 前端增加观察舱第 4 轨 + 新建 ThemeMomentumPanel 题材动量视图（SectorRotation 旧面板删除）；后端是唯一生产者，前端只消费。

## 2. 已确认决策（brainstorming 2026-08-06 逐项确认）

| # | 决策点 | 选择 |
| --- | --- | --- |
| D1 | 第四维形态 | 观察舱第 4 轨 + 独立题材动量面板（新建 ThemeMomentumPanel，删除旧 SectorRotation） |
| D2 | 共振解耦程度 | 完全解耦：不再调节共振分数；`resonance.theme` 移除题材动量融合 |
| D3 | 时间尺度 | 日线聚合 + 槽位日内状态双层 |
| D4 | 动量本体数据源 | 成分股平均涨幅（trimmedMeanChange/change）按交易日合成日线收益序列 |
| D5 | 旧 lifecycle 去留 | 废弃状态机；rotationState 改为方向标签（mainline/inflow/outflow/neutral） |
| D6 | 面板信息密度 | 全字段排行榜 + 行展开 |
| D7 | 验证深度 | 单测 + 回放对比 + 首日观察；不做回测 A/B（theme-confluence 保持 follow-up） |
| D8 | 模块组织 | 重构现有 `theme/momentum.py`（原 theme_momentum.py）为 v2（新增 `theme/daily_series.py`）；不新建独立包、不并入 theme_rotation |
| D9 | 只读 API | 新增 `GET /api/theme-momentum/summary`（复用 theme-rotation/summary 的 Redis 缓存模式） |
| D10 | rotationState 收敛 | 4 个方向标签：mainline / inflow / outflow / neutral，不再有非相邻跳变钳制 |
| D11 | 结构归拢（用户追加） | `backend/analysis/theme/` 与 `backend/analysis/ranktrend/` 包；去前缀命名；旧路径 stub 兼容 |

## 3. 问题诊断（对照用户三条反馈，逐条对源码）

### 3.1 反馈①：题材动量应独立，现与共振混在一起

- 现状代码：`quant-board/backend/analysis/theme/momentum.py`（原 theme_momentum.py）的 `fuse_theme_resonance()` 把题材动量折进个股共振分数：
  `adjustment = clamp((themeMomentumScore-50)*roleWeight*0.3, -15, 15)` + `lifecycleBonus/Penalty`，最后 `finalResonanceScore = clamp(baseScore + adjustment + ...)`（momentum.py 融合段）。
- 前端：`RankTrendObservationPanel.vue` 三轨为 `resonance/technical/lifecycle`（RankTrendObservationPanel.vue tracks 定义），题材动量只作为共振轨里的一行 factor（`label: '题材动量'`），没有独立观察位。
- **结论**：题材动量被"个股共振"语义吞没，对实盘观察没有独立指导作用。

### 3.2 反馈②：题材周期不应照搬个股生命周期，横切面太短

- 现状代码：`theme/rotation/lifecycle.py` 状态机（ice/emerging/expanding/climax/cooling/neutral）+ `theme/trend.py` `_infer_lifecycle` 都是"heat/momentum/breadth/fund 阈值 → 单态标签"的个股分层思路。
- 窗口：`window_slots=8` ≈ 4 小时（theme/rotation/config.py），即题材"生命周期"在 4 小时窗口内判定。
- 用户实盘：一个题材周期可能 1-3 天，也可能半个月，半小时 bar 的固定状态机与题材周期尺度错配，状态频繁跳变且不可解释。
- **结论**：固定 6 态状态机 + 4 小时窗口不适合题材周期；题材动量应是连续维度，周期判定放日线级。

### 3.3 反馈③：题材动量与个股动量是两个维度，不该同构

- 现状代码：`theme/momentum.py` v1 的 `_theme_momentum_for` 公式结构（relativeMomentum/acceleration/persistence/jumpFreshness/reversalPenalty → 加权得分）是 `ranktrend/engine.py analyze_rank_resonance` 的**逐行镜像**，只是输入从"个股关注度百分位序列"换成"题材 heatScore 序列"。
- **结论**：个股动量描述"单只股票在热榜池中的关注度路径"，题材动量应描述"板块整体赚钱效应的扩散/收敛"，两者数学结构同构导致语义错位（"不伦不类"）。

## 4. 调研依据（2026-08-06 联网检索，可引用）

> 检索说明：SSRN/Wiley/聚宽/雪球均被反爬或地域限制拦截；可靠来源为 OpenAlex API（摘要全文）与 Crossref API（题录+摘要），国内社区仅作语义参考。

### 4.1 国外学术（行业动量奠基与风险管理）

| 文献 | 结论 | 对本设计的启示 |
| --- | --- | --- |
| Moskowitz & Grinblatt (1999), *Do Industries Explain Momentum?*, J. Finance 54(4):1249-1290，被引 1869 | 行业层面存在强烈且普遍的动量效应；买入过去赢家行业/卖出输家行业显著获利，且**解释了大部分个股动量异象** | 板块动量是独立于个股动量的有效维度，且应"横截面相对强弱"（过去收益排序）为核心 |
| George & Hwang (2004), *The 52-Week High and Momentum Investing*, J. Finance 59(5):2145-2176，被引 846 | 当前价距 52 周高点的接近度（nearness to 52-week high）解释动量利润的很大部分，预测力**优于过去收益** | 题材动量应含"板块距年内高点的接近度"（创新高 vs 反弹区分） |
| Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, J. Finance 48(1):65-91 | 经典多期动量：按过去 3-12 个月收益排序做多赢家/做空输家 | 多窗口（5/10/20 日）动量组合是板块动量基础 |
| Grobys (2016), *Risk-Managed Industry Momentum and Momentum Crashes*, SSRN 2844140；Grobys (2017), *Risk-Managed 52-Week High Industry Momentum*, SSRN 2903989 | 行业动量存在崩溃风险，需风险管理（波动率调整/52 周高点门禁） | 板块动量必须配拥挤度门禁 + 反转惩罚，防止追高崩溃 |
| Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, JFE 104(2):228-250 | 时序动量：资产自身过去收益预测未来收益 | 板块自身 N 日动量（时间序列视角）作为横截面 RPS 的补充 |

### 4.2 中国 A 股实证（板块动量更短更依赖量能）

| 文献 | 结论 | 对本设计的启示 |
| --- | --- | --- |
| Wang & Wu (2024), *Industry momentum and trading volume: evidence from China*, Managerial Finance | 中国存在显著行业动量；**高成交量行业有动量、低成交量行业没有**；高成交量行业动量策略超额收益更高 | 量能/成交额占比是 A 股板块动量的关键维度，不可省略 |
| Boubaker, Du & Liu (2021), *Industry momentum with correlation consolidation: evidence from China*, J. Asset Management 23:73-82 | 中国行业动量与板块内相关性整合相关 | 板块内部一致性（correlation/breadth）是动量质量的调节因素 |
| 仓库既有调研记录（theme-momentum-resonance-design.md §2） | A 股行业动量月度 IC≈3.03%（申万金工 2026-02）；**扩散期比美股更短**（金融研究 2022）；龙头带动跟风补涨存在动量溢出但拥挤后期断裂（华福金工 2026-05）；题材周期为"龙头启动→板块共振→全面扩散→退潮分化" | ①短窗口权重应高于美股惯例；②龙头带动 = 动量溢出，拥挤后期断裂 = 必须拥挤门禁；③题材周期是 1-3 天~半个月的日线级现象 |

### 4.3 综合结论

> 主流板块动量 = **横截面相对基准（RPS/距 52 周高）** × **多窗口动量（短中长）** × **整体性因子（宽度/一致性/龙头/量能/资金）** × **风险门禁（拥挤/反转）**。
> A 股特性：扩散期短（短窗权重大）、高成交量板块动量更强（量能不可省）、拥挤后期断裂（门禁必须）。
> 与个股动量关系：个股动量解释不了行业动量（Moskowitz & Grinblatt），两者是**并行维度**，不应互相调节——与用户反馈③一致。

## 5. 指标体系（设计 Part 1）

### 5.1 日线序列构造（`theme/daily_series.py` 新增）

- **输入**：`snapshot_sector_rows`（hot_theme）+ `snapshot_stock_rows`（涨停/连板），按 `trading_date` 聚合。
- **收益序列**：每个交易日取收盘槽（15:00 或当日最后一槽）的 `change`（成分股平均涨幅 trimmedMeanChange），累乘合成板块日线"虚拟收益指数"：
  `Index_t = Π(1 + change_t)`，用于 RPS、距年内高点、多窗口动量。
- **辅助日线**：日 ztCount（涨停家数，取当日最大或收盘）、日 breadthScore、日 mainNetInflow（累计）、日成交额占比（板块成交/全市场成交）。
- **容错**：交易日历桥不可用时工作日启发回退（复用 `theme/rotation/history.py` 的 `previous_trading_day` 模式）；漏采日显式缺槽，不补零。

### 5.2 六维因子（日线主口径，0-100）

| 维度 | 公式 | 权重 | 依据 |
| --- | --- | --- | --- |
| 板块 RPS | 日收益 5/10/20 日涨幅在全体板块横截面的百分位排名（0-100），短窗加权（5日×0.5 + 10日×0.3 + 20日×0.2） | 0.25 | Moskowitz & Grinblatt 1999；A股扩散期短→短窗权重大 |
| 距年内高点 | 虚拟收益指数当前值 / 数据窗内 max(Index) 的接近度（0-100） | 0.15 | George & Hwang 2004（52周高，数据不足降级为年内高点） |
| 多窗口动量 | 5/10/20 日收益率的加权符号强度（50 + 加权收益率×系数），含时序方向 | 0.20 | Jegadeesh & Titman 1993；MOP 2012 |
| 整体性 | 宽度（上涨占比）× 一致性（同向占比）× 龙头（涨停/连板高度/晋级率）复合，复用 theme/heat.py 的 breadth/correlation/leadership 日聚合 | 0.20 | Boubaker 2021；华福 2026-05；主题炒作周期实证 |
| 资金量能 | 主力净流入强度 + 板块成交额占比（高成交量板块动量更强） | 0.15 | Wang & Wu 2024 |
| 拥挤度风险（惩罚） | crowdingRisk 日值 + 量比高分位 + 板块内配对相关性 → 负向扣分（动量崩溃门禁） | 门禁 | Grobys 2016/2017 |

`themeMomentumScore = Σ(wᵢ·scoreᵢ) − crowdingPenalty`（0-100），其中五个正向维度的原始权重和 = 0.95（RPS 0.25 + 距高 0.15 + 动量 0.20 + 整体性 0.20 + 资金量能 0.15），拥挤惩罚为独立扣分项（0-15）；实现时按"可用维度集合"重新归一化权重（复用 `theme/rotation/factors.py` 的 `combine_scores` 模式），避免缺维度时总分被稀释。
`direction = up / neutral / down`（按 score 相对 50 与动量方向判定）

### 5.3 展示标签（非状态机）

`phaseLabel ∈ {启动, 扩散, 过热, 退潮, 中性}`：由分数区间 + 拥挤度派生，**仅展示解释，不进任何合同/回测/决策**。题材周期 1-3 天~半个月，不做固定状态机、不做非相邻跳变钳制。

### 5.4 槽位日内辅口径

每半小时：`intraday = {shortChange, ztDelta, inflowDelta}`（当前槽 vs 前 1/3 槽），仅作日线动量的日内快照，不判定生命周期。

## 6. 数据流与输出合同（设计 Part 2）

### 6.1 数据流

```text
snapshot_sector_rows（hot_theme）+ snapshot_stock_rows（涨停/连板）  ← 已落库
        │  theme/daily_series.py：按 trading_date 聚合，收盘槽 change 累乘合成虚拟收益指数
        ▼
theme/momentum.py v2（纯函数）
        ├─ 日线主口径：RPS(5/10/20) / 距年内高点 / 多窗口动量 / 整体性 / 资金量能 / 拥挤惩罚
        ├─ 槽位辅口径：intraday {shortChange, ztDelta, inflowDelta}
        └─ 每股投影：analysis.themeMomentum（只读）
        │
        ▼
写入 frame.themeMomentumContext（camelCase）
        │
        ▼
GET /api/theme-momentum/summary（新增只读 API，复用 theme-rotation/summary 的 Redis 缓存模式）
        │
        ▼
TS 消费：OBSERVATION 第4轨 + ThemeMomentumPanel 面板（新建）
```

### 6.2 输出合同（camelCase，新增字段不覆盖旧字段）

```jsonc
// frame.themeMomentumContext（帧级，市场视角）
{
  "version": "theme_momentum_v2",
  "factors": [{
    "themeId": "BKAI", "themeName": "人工智能",
    "score": 78, "direction": "up", "phaseLabel": "扩散",
    "rps": {"d5": 92, "d10": 85, "d20": 70},
    "nearHigh": 76,                        // 距年内高点接近度
    "windowMomentum": {"d5": 4.2, "d10": 8.1, "d20": 12.5},
    "breadth": 68, "flowVolume": 72, "crowdingPenalty": 8,
    "intraday": {"shortChange": 6.5, "ztDelta": 3, "inflowDelta": 0.82},
    "reasons": ["RPS 20日 92 分位", "板块成交占比前5%", "涨停家数环比+3"]
  }],
  "qualityFlags": [], "computedAt": 1785835800000
}

// 每股 analysis.themeMomentum（第4轨数据源，只读，不参与 decision）
{ "status": "ok", "themeId": "BKAI", "themeName": "人工智能",
  "score": 78, "direction": "up", "role": "core", "phaseLabel": "扩散",
  "reasons": ["板块整体动量 up，该股为核心跟随"] }
```

> 键名硬约束：全部 camelCase；`themeMomentumContext` 与 `themeMomentum` 为**新字段**，不覆盖/不修改现有 `rotationSummary`、`resonance`、`themeContext`。历史已落库旧帧不回滚，消费点按新合同兜底。

### 6.3 与 theme_rotation 的关系（D5/D10）

- **废弃** `lifecycle` 状态机（ice/emerging/expanding/climax/cooling/neutral 不再产出）。
- **rotationState 改为方向标签**：`mainline / inflow / outflow / neutral`，由新日线动量 + 资金 + 拥挤度派生（主线=动量 Top3 且资金集中 Top3 且不拥挤；流入/流出按方向；其余 neutral）。不再有"非相邻跳变钳制"。
- `theme/rotation` 引擎保留 rotationScore/rotationSummary（市场阶段/主线）能力，但其 lifecycle 字段停止消费；题材动量 v2 不引用它。

## 7. 前端（设计 Part 3）

1. **OBSERVATION 第4轨**：`RankTrendObservationPanel.vue` tracks 增加 `{ id: 'theme', index: '04', label: '题材动量' }`；`OBSERVATION_WINDOW_BARS` 增加 `theme: 15`；渲染 `analysis.themeMomentum`（分数/方向/角色/phaseLabel/reasons，`insufficient` 显示原因）。
2. **ThemeMomentumPanel.vue 新建**：全字段题材动量排行榜 + 行展开——列：题材名/动量分/方向/phaseLabel/RPS(5,10,20)/距年内高点/涨停/资金量能/拥挤扣分；行展开显示多窗口动量/整体性/龙头与涨停/日内状态 + reasons。旧 SectorRotation.vue（轮动状态列表）删除，App.vue 题材 tab 打开 ThemeMomentumPanel。
3. **DataTable.vue**：共振 tooltip 移除内嵌"题材动量"段（随解耦），不再从 `resonance.theme` 展示题材动量。
4. **视觉方向**：沿用现有暗色数据工作台风格；第4轨与三轨视觉层级一致，用独立强调色区分"板块视角"；面板排行用方向色（up 红涨/down 绿跌，沿用 A 股配色），拥挤度用警示色。

## 8. 错误处理、测试与实施任务（设计 Part 4）

### 8.1 fail-visible 错误处理

| 场景 | 行为 |
| --- | --- |
| 题材日线序列 < 5 日 | 该题材 RPS/动量维度 `null + reason`（如 `rps_history_insufficient`），可算部分保留，不补零 |
| 全市场横截面 < 20 板块 | `cross_section_insufficient` 标记，保留可算部分 |
| 板块成交额缺失（资金 provider 失败） | `flow_volume_unavailable`，资金量能维度降级并从权重剔除 |
| 距年内高点数据不足 250 日 | 降级为"数据窗内高点"，reasons 标注 `near_high_window_limited` |
| 引擎异常 | 不阻断快照入库；写入 frame.metadata.derivation.qualityIssues（沿用 theme/rotation service 模式） |
| 解耦回归 | `resonance.score` 不再被题材调节；旧帧已落库数据不回滚，消费点按新合同兜底 |

### 8.2 测试

- **golden 单测**：固定 30 帧日线序列 → 期望 RPS/距高点/动量/score/direction/phaseLabel；边界（日线不足、横截面不足、全 NaN、拥挤惩罚封顶、direction 翻转）。
- **A 股特性用例**：高成交量板块动量更强（Wang & Wu 2024）；短窗权重大（扩散期短）。
- **回放对比**：`theme/momentum_validation.py` 升级为"旧 v1 融合 vs v2 独立维度"的排序位移统计，回答"v2 是否系统性改变题材排序、方向是否与市场一致"。
- **前端**：面板源码结构测试 + Playwright 真实渲染（第4轨切换、排行渲染、行展开、无控制台错误、无横向溢出）。

### 8.3 实施任务（TDD，7 个）

1. `theme/daily_series.py` 日线聚合（收益序列/辅助日线/交易日历容错）——**已完成（Task 1）**
2. `theme/momentum.py` v2 纯函数（六维 + intraday + phaseLabel；移除 fuse 融合）
3. analyze 接入（frame.themeMomentumContext + 每股 analysis.themeMomentum；resonance 回归纯六因子）
4. theme/rotation 收敛（废弃 lifecycle，rotationState 改方向标签；下游消费审计）
5. 前端第4轨 + DataTable tooltip 移除
6. ThemeMomentumPanel.vue 新建（全字段排行 + 行展开）+ 删除 SectorRotation.vue + `GET /api/theme-momentum/summary`
7. 回放对比 + 首日观察清单 + 文档同步（architecture/api-cli/theme-module README）

## 9. 风险与边界

- **日线数据量**：需 20+ 个交易日的 sector rows 才能算满 20 日 RPS；52 周高需 250 日，迁移期用"已有数据可算部分 + 缺失标记"，不伪造（降级为年内高点/数据窗高点）。
- **权重主观性**：默认权重来自调研共识，先出"可解释"版本，回放敏感性验证后再固化。
- **不引入新依赖**：状态标签用规则+阈值，不上 HMM/ML。
- **兼容性**：新字段全部可选扩展；`resonance.theme` 移除调节后，历史已落库数据的消费点按 Task 4 兜底，不回滚旧帧。
- **与 theme_rotation 边界**：`rotationSummary`（市场阶段/主线）语义保留，题材动量 v2 只补充"板块整体动量"这一缺失维度；lifecycle 状态机废弃。

## 10. 必查清单（AGENTS.md §11）

- [x] 核心目标 5 句话以内（见 §1）。
- [x] 无质量门禁/阻断：日线不足只打标记不阻断，原始数据照存。
- [x] 不引入分阶段 shadow/live 双跑；上线走"小范围观察 + 首日人工验证"（Task 7）。
- [x] 无独立守护进程/计划任务；全部集成 analyze 路由与既有 collector 生命周期。
- [x] 不新增 MongoDB 集合；仅新增 1 个只读 API。
- [x] 条件判断语义逐条书面化，code review 逐行比对"任一/全部/至少"。
- [x] 参数进 config 有默认值，默认值语义为"调研共识 + 可解释优先"。
- [x] 首个上线日人工验证清单见 Task 7。
