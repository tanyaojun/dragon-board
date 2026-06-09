# RankTrend Hotlist Recall Research Design

日期：2026-06-09 | 状态：待评审

## 1. 背景

`ranktrend_early_big_move_v3_lifecycle_fusion` 当前 live 候选入口，对 jump / fusion 前置门槛使用了较强的硬过滤：

- `jump.confidence >= 90`
- `jump.direction == buy`
- `short > 0 && mid > 0 && long > 0`
- `acceleration >= 10 || accDelta >= 8`
- `change < 6`
- `sampleQuality.status == ok`
- `cycle.decision.action != veto`
- `candidateTier == A_MAIN` 或 `B_IGNITION && mid >= 20 && zeroCross == buy`

最近实盘观察表明，问题重点已经不在生命周期辅助策略，而在：

1. `jump confidence` 的阈值和定义过于固定，无法准确覆盖热榜盘中“技术买点先出现、jump 确认稍慢”的股票
2. `fusion` 前置结构过于“教科书化”，更偏向爆发延续模型，不完全贴合热榜模式里常见的“稳步抬升 + 多信号共振”买点

用户已经明确：下一步研究以“召回优先”为主目标，不再以固定 `90` 或人工想象的结构分层直接定义下一版规则。

## 2. 目标

本轮研究要回答两个核心问题：

1. `jump confidence` 的最优有效区间是什么，是否有足够证据支持替换当前固定 `90`
2. `fusion` 为什么会系统性偏离热榜买点，哪些前置结构应保留、降级为排序项，或改写为更贴近热榜模式的验证项

研究结果必须建立在“热榜买点型正样本”框架上，而不是直接用全市场收益或主观印象拍板。

## 3. 非目标

- 不直接修改 live 自动入池逻辑
- 不自动写回 Python / TypeScript / CLI / 前端默认参数
- 不把生命周期辅助策略重新作为本轮主问题
- 不先以回测收益、胜率、回撤作为唯一优化目标
- 不在没有验证前新增新的正式候选分层定义

## 4. 研究口径

### 4.1 主目标：召回优先

本轮评估优先级固定为：

1. 优先召回盘中真实热榜强票
2. 再控制新增噪音
3. 最后才看收益类指标

这意味着本轮“最优值”不是简单的 PnL 最大值，而是：

- 能召回更多热榜买点型正样本
- 同时把误召回控制在可接受范围
- 新增候选仍然具备可解释结构

### 4.2 正样本定义：热榜买点型

正样本不直接等于“后续涨停”或“未来收益高”，而是优先定义为人工可复核的盘中买点锚点。

首批锚点样本的最小合同必须至少包含：

- `code`
- `tradingDate`
- `slotTime`
- `snapshotType`
- `label`
- `evidence`
- `annotator`
- `status`

其中：

- `status=confirmed`：确认纳入首批统计
- `status=borderline`：保留观察，但不进入首批阈值搜索主统计
- `status=exclude`：明确排除，不参与统计

首批 `confirmed` 正样本必须满足以下最小规则：

1. 盘中被明确标注为“值得买的热榜买点”
2. 当时至少满足以下四项中的三项：
   - `direction.signal == buy`
   - `acceleration.signal == buy`
   - `zeroCross.signal == buy`
   - `macd.cross == golden`
3. 信号后 `1-8` 个 bars 内，不出现“最大回撤先达到 -5% 且最高涨幅始终 < +3%”这类强反证

最终评估时，再叠加两类结果标签：

- `后续涨停型`：信号后 `1-4` 个 bars 内触板/涨停
- `短线爆发型`：信号后 `1-8` 个 bars 内最高涨幅 `>= +6%`

未满足上述结果标签的样本，不自动从锚点集中删除；但必须在报告中单独标识为 `no_breakout_confirmation`。

### 4.3 样本来源：人工锚点优先

正样本先从人工锚点构建，再扩展到最近一周 `dragonboard_live` 热榜覆盖样本。

首批人工锚点至少包括：

- `600186` `2026-06-09 10:00`
- `600186` `2026-06-09 10:30`
- `600183` `2026-06-09 10:00`
- `600183` `2026-06-09 10:30`
- `002156` 用户明确指出的盘中较好买点 bars

其中：

- `600186` / `600183` 四个样本进入首批 `confirmed`
- `002156` 在具体 bar 位确认前，只能以 `borderline` 状态登记，不进入首批主统计

允许后续补充更多人工锚点，但首批研究必须先围绕这些样本收口。

## 5. 数据范围

- 数据集：`dragonboard_live`
- 默认快照口径：`half_hour`
- 主研究窗口：最近一周，重点覆盖 `2026-06-09`
- 研究输出必须区分：
  - `人工锚点样本`
  - `扩展热榜覆盖样本`

说明：

- 这里的“扩展样本”不是全 A 股全市场，而是 `dragonboard_live` 在最近一周实际覆盖到的热榜股票样本
- 报告中不得把这部分结论表述成“全市场统计”

## 6. 研究方法

### 6.1 阶段 A：人工锚点逐 bar 归因

对每个人工锚点 bar，逐项拆出：

- jump 原始字段：
  - `event`
  - `direction`
  - `confidence`
  - `sustained`
  - `magnitude`
  - `overshoot`
  - `eventCount`
  - `surgeCount`
  - `collapseCount`
- technical 信号：
  - `direction.signal`
  - `acceleration.signal`
  - `zeroCross.signal`
  - `macd.cross`
- 动量结构：
  - `short`
  - `mid`
  - `long`
  - `acceleration`
- 周期 / 风险 / 分层：
  - `cycle.stage`
  - `cycle.decision.action`
  - `candidateTier`
  - `sampleQuality.status`

目标是先解释“这根 bar 为什么在盘感上像买点，却没有进入候选”。

### 6.2 阶段 B：热榜买点模板抽象

基于人工锚点，抽象出热榜买点型样本的共同特征，不先定义正式规则，只形成研究标签。

候选标签至少包括：

- `technical_buy_alignment`
  含义：`direction / acceleration / zeroCross / macd` 中多项同步偏多
- `progressive_rank_lift`
  含义：排名百分位持续抬升，但单次 overshoot 不一定极端
- `non-explosive_but_valid`
  含义：买点成立时 `acceleration` 可能不足 `10`，但结构已成
- `early_hotlist_ignition`
  含义：更像热榜早期启动，而不是中后段扩散/加速确认

这些标签用于扩展验证，不直接变成 live 条件。

### 6.3 阶段 C：`jump confidence` 阈值搜索

`jump confidence` 阈值搜索只针对“固定 baseline jump 定义”的信号做扫描，不与 `jumpDeltaPct` 混合统计。

必须显式拆成两类研究结果：

1. `confidence interval scan`
   - 固定 baseline signal
   - 只比较 `min_jump_confidence`
2. `jump definition replay study`
   - 单独研究 `jumpDeltaPct` 或其它会改变 jump event/direction 的因素
   - 不得与 confidence 区间结果混在同一张“最优阈值”表里

对最近一周样本做区间扫描，不再只比 `90 / 85 / 80` 三档。

建议扫描：

- 主扫描区间：`70-95`
- 粒度：`2.5` 或 `5`

每个候选阈值至少输出：

- 人工锚点召回数 / 召回率
- 扩展热榜覆盖样本召回数 / 召回率
- 新增候选数
- 新增候选中“后续涨停型 / 短线爆发型”占比
- 噪音候选数
- 被召回样本的 jump 结构分布

其中噪音候选定义必须显式写死：

- 被召回
- 不属于人工锚点
- 不命中 `后续涨停型`
- 不命中 `短线爆发型`
- 且没有 `technical_buy_alignment` 标签

本轮输出目标不是单点神值，而是：

- 最优区间
- 稳定区间
- 明显过严区间

### 6.4 阶段 D：`fusion` 偏离热榜模式的结构归因

围绕人工锚点和扩展样本，统计 fusion 各前置项对热榜买点的误伤情况：

- `short_mid_long_positive`
- `acceleration_ge_10_or_accdelta_ge_8`
- `change_lt_6`
- `sample_quality_ok`
- `cycle_not_veto`
- `tier_gate`

重点不是“哪项失败次数最多”，而是：

- 哪项最常拦住人工锚点
- 哪项最常拦住扩展样本中的热榜买点标签
- 哪项属于真实质量过滤
- 哪项更像过于教条的前置确认

归因报告必须显式区分以下原因类型，禁止混写：

- `true_gate_block`
- `field_missing`
- `replay_missing`
- `candidate_tier_side_effect`
- `sample_quality_side_effect`

同时必须把以下混杂项作为强制分层统计输出：

- `candidateTier`
- `cycle.stage`
- `cycle.decision.action`
- `sampleQuality.status`

说明：

- 本轮不把生命周期辅助策略当成主优化对象
- 但必须把 `candidateTier/stage` 作为混杂项控制，否则不能把失败直接归咎于 fusion gate

### 6.5 阶段 E：候选优化方案生成

只有在阶段 A-D 完成后，才允许提出 fusion 优化候选。

每个候选方案必须写明：

- 修改的是哪条前置结构
- 它为何偏离热榜模式
- 放宽后新增召回的样本结构
- 噪音增加情况
- 是否更适合改成排序项，而非继续做硬 veto

## 7. 允许提出的优化类型

本轮允许的优化类型仅限以下三类：

1. `硬门槛 -> 候选召回 + 二次排序`
2. `硬门槛 -> 结构标签/解释项`
3. `固定阈值 -> 数据驱动阈值区间`

本轮不允许：

- 直接凭经验新增新的正式分层系统
- 在未验证前删除大量前置条件
- 把一个人工样本直接推广成正式全局规则

## 8. 输出物

本轮研究至少要产出以下内容。

### 8.1 热榜买点型正样本集

内容至少包括：

- 股票代码
- 日期 / bar 时间
- 人工锚点来源
- 当时技术信号
- jump / fusion 拦截原因
- 后续表现标签

### 8.2 `jump confidence` 阈值扫描报告

至少包含：

- 扫描区间与粒度
- 各阈值的召回/噪音统计
- 人工锚点命中情况
- 推荐区间与不推荐区间

说明：

- `推荐区间 / 不推荐区间` 可以由代码基于预设统计规则产出，也可以由研究者基于报告人工判定
- 但最终输出必须明确标注：`derived_by=rule` 或 `derived_by=manual_review`

### 8.3 `fusion` 热榜适配归因报告

至少包含：

- 人工锚点逐项失败拆解
- 扩展样本中各 gate 的误伤分布
- 建议保留的结构
- 建议降级为排序项的结构
- 不建议再用拍脑袋定义的分层项

## 9. 成功标准

本轮研究成功的最低标准是：

1. 给出一版可复核的“热榜买点型正样本”定义与样本表
2. 用样本证据说明 `jump confidence=90` 是否过严，并给出推荐区间
3. 用样本证据说明 `fusion` 哪些前置结构偏离热榜模式
4. 输出的优化建议全部可追溯到样本和统计，不再依赖主观拍板

## 10. 风险与边界

- 人工锚点数量初期有限，不能把早期结论包装成最终真理
- `002156` 的具体 bar 位可能需要额外由用户确认或由图像/记录补充
- 当前 live 数据里 `accDelta` 缺失比例高，相关结论必须单独标注
- 当前研究仍以 `half_hour` 为默认口径，不能直接外推到 `quarter_hour`
- `dragonboard_live` 是热榜覆盖样本，不是全市场全量样本，所有扩展统计都要按这个范围解释
- 后续报告必须单独输出 `样本缺行 / signal_missing / replay_missing` 占比，避免把数据缺口误算成 gate 误伤

## 11. 下一步交付

Spec 通过后，下一阶段实现应先做 research-only 工具链，不直接改 live：

1. 构建人工锚点样本输入格式
2. 扩展 shadow audit，支持阈值扫描与样本标签输出
3. 生成 `jump confidence` 区间扫描报告
4. 生成 `fusion` 热榜适配归因报告
5. 最后才讨论是否形成新的候选召回方案
