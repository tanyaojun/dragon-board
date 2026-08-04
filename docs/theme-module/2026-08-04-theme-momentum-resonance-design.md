# RankTrend OBSERVATION 共振路径增加题材动量（板块共振）设计

日期：2026-08-04
状态：待用户 review
归属：题材模块方案（跨 RankTrend 共振消费），沿用 `docs/theme-module/` 目录

## 1. 核心目标（5 句话以内）

1. 为 RankTrend OBSERVATION 共振路径增加"题材动量（板块共振）"维度，把单股共振升级为"个股 × 题材 × 市场"三重视角。
2. 题材动量由 Python 侧从已落库的 `snapshot_sector_rows` 因子序列计算，前端只消费，不保留第二份实现。
3. 题材动量以"有限调节项 + 生命周期门禁"方式并入现有共振分数，不重排既有六因子、不破坏 stock-level 共振语义。
4. 数据不足时保留原共振分数并输出结构化原因，不归零、不伪造（fail-visible）。
5. 用现有 theme-confluence 回测链 + golden case 验证调节项方向与幅度，冻结后再上 live 观察层。

## 2. 背景与依据

- 现状共振 = 单股关注度百分位相对热榜池市场中位数的六因子共振（短 3 / 中 8 / 路径 8 / Jump 衰减 3），见 `quant-board/backend/analysis/ranktrend.py` `analyze_rank_resonance`。
- 现状题材模块已有：全市场题材映射（MongoDB）、5 分钟热度因子、每半小时 `snapshot_sector_rows`（`entityType=hot_theme`，含 heatScore/momentumScore/breadth/fund/leadership/correlation/crowding/persistence/rotationState/metadata）。
- 现状缺口：`momentumScore` 是单帧点值（`50 + 平均涨幅*8 + 热度差*1.5`），非多帧相对动量；`theme_trend.py` 注释明确"跨帧热度趋势/动量背离为预留项"；analyze 路由 `projection="ranktrend"` 显式置空 sectors/hotThemes，共振链路拿不到题材维度。
- 外部实证：A 股行业动量是低相关增量因子（申万金工，2026-02，月度 IC≈3.03%，高动量组内因子形成"共振"）；A 股行业动量月度显著、扩散期比美股更短（金融研究，2022）；龙头带动跟风补涨存在动量溢出但拥挤后期会断裂（华福金工，2026-05）；主题炒作周期为"龙头启动→板块共振→全面扩散→退潮分化"（龙头扩散效应研究）。结论：题材动量有实证基础，但必须配横截面相对基准、拥挤/反转惩罚和生命周期状态。

## 3. 非目标

- 不新增 MongoDB 集合、不新增 API、不新增 CLI。
- 不重排/重写现有个股共振六因子公式与 golden case。
- 不把 ThemeTrend 变成独立买入信号（沿用"ThemeTrend 只辅助、不独立制造买入"合同）。
- 不把题材动量并入 QuantBoard golden/replay 主链的 `decision`；仅扩展 live analyze 输出与展示（与现有 resonance 定位一致）。
- 不做参数搜索式调参；权重为固定常量，方向用回测验证。

## 4. 总体数据流

```text
MongoDB snapshot_sector_rows（hot_theme，已落库，含每帧题材因子）
        |
        +-- analyze 路由（_load_frames_for_analysis 窗口 30 帧）
        |     +-- 新纯函数 analysis/theme_momentum.py
        |     |     +-- 每帧题材动量（六因子镜像 + 市场题材中位数）
        |     |     +-- 每股题材暴露（主题材 + 角色 + 贡献）
        |     +-- 输出 frame.themeContext + stock.analysis.resonance.theme
        |
        +-- TS 消费
              +-- RankTrendObservationService（透传 theme 上下文）
              +-- OBSERVATION 共振轨展示题材因子行
              +-- DataTable tooltip 题材段
```

## 5. 题材动量算法合同（Python 纯函数，`analysis/theme_momentum.py`）

### 5.1 输入

每帧的 `hotThemes`（即 `snapshot_sector_rows` 中 `entityType=hot_theme` 的行），每题材至少包含：

```text
themeId / themeName / heatScore / rank / crowdingRisk / rotationState /
qualityFlags / metadata（quoteCoverage、fundCoverage、trimmedMeanChange）
```

题材强度序列 `S_t(i) = heatScore`（仅 `rankEligible` 且 heatScore 为有限数的题材入序列；否则该帧该题材视为缺槽并打标记）。

### 5.2 参数（固定常量，不进 TypeScript）

```text
shortWindowBars = 3
midWindowBars = 8
pathWindowBars = 8
jumpDecayBars = 3
jumpRankSlots = 3          # 单帧排名提升 >= 3 视为题材 Jump
jumpHeatDelta = 15         # 单帧 heatScore 提升 >= 15 视为题材 Jump
themeCrossSectionMin = 20  # 与个股共振 marketSampleCount 对齐
themeSeriesMinBars = 9     # 短/中/路径窗口所需（与个股 RESONANCE_MIN_SERIES_POINTS 对齐）
```

### 5.3 公式（镜像 `analyze_rank_resonance`，输入换成题材强度序列）

```text
themeShortChange  = S_t(i) - S_t(i-3)
themeMidChange    = S_t(i) - S_t(i-8)
marketThemeMedianShortChange = 当前帧与 i-3 帧共同 rankEligible 题材的
                              themeShortChange 中位数（< 20 个 => 横截面不足）
themeRelativeMomentum = clamp((themeShortChange - marketThemeMedianShortChange) / 15, -1, 1)
themeAcceleration     = clamp((themeShortChange - themeMidChange * 3 / 8) / 15, -1, 1)
themePersistence      = 最近 8 个相邻变化中与当前方向同向的比例
themeJumpFreshness    = exp(-barsSinceLatestJump / 3)
                        （题材 Jump：单帧 rank 提升 >= 3 或 heatScore 提升 >= 15）
themeReversalPenalty  = clamp(0.6 * 方向切换率 + 0.4 * (历史峰值 - S_t(i)) / 20, 0, 1)
                        + (rotationState in {cooling, outflow, divergence} ? 0.2 : 0)，封顶 1.0

方向判定与方向翻转（与个股共振 analyze_rank_resonance 完全一致）：
themeDirectionScore   = themeRelativeMomentum + themeAcceleration + 0.2 * pathDirection * persistence
themeDirection        = buy（> 0.1）/ sell（< -0.1）/ hold（其余）
directionalMomentum   = -themeRelativeMomentum if themeDirection == "sell" else themeRelativeMomentum
directionalAcceleration = -themeAcceleration if themeDirection == "sell" else themeAcceleration
themeMomentumScore    = round(100 * clamp(0.35*pos(directionalMomentum)
                        + 0.25*pos(directionalAcceleration)
                        + 0.2*persistence + 0.2*jumpFreshness - 0.2*reversalPenalty, 0, 1))
themeLifecycle        = rotationState（mainline/quick/inflow/outflow/cooling/neutral）
```

注意：`pos(x) = max(0, x)`；方向翻转意味着当 `themeDirection=sell` 时，负向相对动量被翻转为正贡献，与源码 [ranktrend.py:1226-1234](D:/dragon-board/quant-board/backend/analysis/ranktrend.py:1226) 的口径一致，不能用 `pos(themeRelativeMomentum)` 简写替代。

### 5.4 质量标记（不阻断，保存 + 标记）

```text
theme_series_insufficient        # 该题材有效序列 < 9 bars 或中间缺槽
theme_cross_section_insufficient # 市场题材横截面 < 20 个
theme_mapping_missing            # 个股无任何题材映射
theme_quote_coverage_low         # 沿用 sector row qualityFlags
fund_flow_unavailable            # 沿用 sector row qualityFlags
crowding_risk_missing            # 主题材 crowdingRisk 缺失/非有限数，生命周期惩罚跳过并标记
```

命中 `theme_series_insufficient` 或 `theme_cross_section_insufficient` 时：`resonance.theme.status='insufficient'`，保留原因列表，**不参与分数调节**，原共振分数原样保留。

## 6. 个股题材暴露合同

对每只共振股票，主题材选择按以下优先级（与 `theme_trend._stock_theme` 的 `mainTheme` 优先口径一致）：

1. `stock.mainTheme` 存在且在帧内 hotThemes 中可按名称/ID 匹配 → 直接采用；
2. 否则取"所属题材中 heatScore 最高者"；
3. 均不匹配 → 题材暴露 `None`（`theme_mapping_missing`）。

然后：

```text
role       = leader（leadStatus 含"龙"或 themeRole=leader 或联动角色=leader）
             | core（题材 heatScore>=70 且 change>=5）
             | follower（题材 heatScore>=45 且 change>0）
             | independent | noise（复用 theme_trend._ts_role_for 口径）
roleWeight = leader 1.0 / core 0.82 / follower 0.62 / independent 0.38 / noise 0.15
themeContribution = 沿用既有 themeContribution 概念（无则按 roleWeight 推算）
```

role 判定约束：`stock.themeRole` 是股票级字段，仅当"匹配题材 == mainTheme（或股票只属单一题材）"时才直接复用；否则回退到 heatScore/change 规则，避免角色与匹配题材错配。阈值来源：`theme_trend._ts_role_for`（[theme_trend.py:374-386](D:/dragon-board/quant-board/backend/analysis/theme_trend.py:374)），leader/core/follower/independent/noise 的 heat/change 边界与既有研究链一致。

## 7. 共振融合合同（并入 `resonance.theme` + 有限调节）

### 7.1 调节项

```text
adjustment = clamp((themeMomentumScore - 50) * roleWeight * 0.3, -15, 15)
lifecycleBonus  = themeLifecycle in {mainline, expansion, ignition} 且 role in {leader, core} ? +5 : 0
lifecyclePenalty = themeLifecycle in {crowded, divergence, cooling, reversal} 且 role != leader
                   ? -min(10, crowdingRisk / 10) : 0
finalResonanceScore = clamp(baseScore + adjustment + lifecycleBonus + lifecyclePenalty, 0, 100)
```

adjustment 保留浮点精度（不做前置 round，最终 `finalResonanceScore` 四舍五入到整数）；`crowdingRisk` 缺失/非有限数时 `lifecyclePenalty=0` 并打 `crowding_risk_missing` 标记，不把"未知"当作"不拥挤"。

融合输出（`resonance` 与 `resonance.theme`）额外包含：

```text
resonance.baseScore                 # 调节前原始共振分数（始终可见，供审计与前端对比）
resonance.theme.themeMomentumDirection  # buy / sell / hold
resonance.theme.adjustment          # 实际生效调节值（含生命周期加减，浮点）
```

### 7.2 行为约束

- `direction` 不因题材调节改变（题材只调强度与标签，不反转方向）。
- `decision.final` 继续由共振方向/分数覆盖（沿用 `_apply_resonance_final`，不新增机制）。
- 题材数据不足：`status='insufficient'` + reasons，baseScore 原样输出；**任何情况下不因题材数据把共振归零**。
- 任一条件判断语义（"全部/任一/至少"）在 code review 时必须对照本文逐行比对，禁止 `any`/`all` 语义偏差（AGENTS.md 复盘必查项）。

## 8. 数据流改造

### 8.1 Python analyze 链路

1. `mongo_repository.py` / `repository.py`：`projection="ranktrend"` 分支保留股票最小投影，同时把该窗口的 sector rows（`entityType=hot_theme`）挂到 `frame["hotThemes"]`（不再置空）。数据量：200 帧 × ~239 题材，内部读口可接受。
2. `ranktrend_routes.py`：`_to_engine_frame` 把 `hotThemes` 带入引擎帧；`_analyze_frames` 逐帧调用 `theme_momentum` 纯函数，输出：
   - 帧级 `themeContext`：`{ factors: [每题材动量摘要], marketThemeMedianShortChange, themeSampleCount }`
   - 每股 `analysis.resonance.theme`：`{ status, themeId, themeName, role, roleWeight, themeMomentumScore, themeLifecycle, adjustment, reasons }`
3. 无新 API / 无新 CLI / 无新 MongoDB 集合；analyze 响应为向后兼容的字段扩展。

### 8.2 TS 消费

1. `src/services/rankTrend/types.ts`：`RankTrendResonance` 增加可选 `theme?: RankTrendThemeResonance`。
2. `RankTrendObservationService.ts`：透传 `resonance.theme` 与帧 `themeContext`，纯展示投影，不计算。
3. `RankTrendObservationPanel.vue` 共振轨：增加"题材动量 / 题材生命周期 / 个股角色 / 题材贡献 / 调节值"因子行；`insufficient` 显示结构化原因。
4. `DataTable.vue` 共振 tooltip：增加题材段（题材动量、角色、调节值），数据不足显示"题材数据不足 + 原因"。

## 9. 回测与验证

### 9.1 本期验证（不触碰 live 默认）

- 回放级多帧滚动对比（`theme_momentum_validation.compare_theme_momentum_rolling`）：逐帧统计调节方向/幅度分布、按生命周期分桶的调节均值、排序位移与不足计数，回答"调节是否系统性改变排序、方向是否与生命周期一致"。
- golden case 固定输入输出（含题材方向 buy/sell/hold、mainTheme 优先、全 NaN、拥挤缺失等边界），TS/Python 共用。
- 结论只能生成候选参数，不写回 Python/TS 默认值、API、CLI 或文档默认值。
- 官方 `POST /api/backtests/theme-confluence` 的"实验组"需回测引擎支持按题材动量调节候选排序，属独立研究任务，列为 live 观察后的 follow-up（P1），不因本期未做而声称已完成交易结果验证。

### 9.2 golden case

- 固定 30 帧 stock + theme 序列，分别给出"题材动量强/弱、生命周期主升/拥挤/冷却、角色龙头/跟风、题材数据不足"的预期输出；TS/Python 共用同一套 case。
- Python 侧生成 golden，TS 只做消费契约校验（沿用 P2 已反转的 golden 方向）。

### 9.3 上线观察（不做 shadow/live 双跑大工程）

- analyze 输出带 `themeContext` 后直接小范围观察：第一个完整交易日核对
  1. `snapshot_sector_rows` 连续无漏槽（MongoDB 直查，不看 API status）；
  2. analyze 返回 `themeContext` 非空、`resonance.theme.status` 分布合理；
  3. 共振分布与旧版对比：全表不出现异常归零，`insufficient` 只出现在真实缺槽场景；
  4. 前端共振轨题材因子行渲染、tooltip 无横向溢出、控制台无错误（Playwright 验收）。

## 10. 影响文件

```text
新增：
  quant-board/backend/analysis/theme_momentum.py         # 纯函数 + 单测
  quant-board/backend/tests/test_theme_momentum.py
  quant-board/backend/tests/test_theme_resonance_fusion.py
修改：
  quant-board/backend/data/mongo_repository.py           # ranktrend projection 带 hotThemes
  quant-board/backend/data/repository.py                 # 同上（SQLite 镜像路径）
  quant-board/backend/api/ranktrend_routes.py            # _to_engine_frame / _analyze_frames
  quant-board/backend/tests/test_ranktrend_analyze_api.py
  src/services/rankTrend/types.ts                        # RankTrendThemeResonance
  src/services/rankTrend/RankTrendObservationService.ts  # 透传展示
  src/components/panels/RankTrendObservationPanel.vue    # 共振轨题材因子行
  src/components/common/DataTable.vue                    # tooltip 题材段
  相关 __tests__（观察服务/面板/DataTable）
文档：
  quant-board/docs/architecture.md                       # analyze 响应字段
  quant-board/docs/api-cli.md                            # analyze 响应字段
  docs/theme-module/README.md                            # 索引
```

## 11. 必查清单（AGENTS.md §11 逐条确认）

- [x] 核心目标 5 句话以内说清楚（见 §1）。
- [x] 无质量门禁/阻断：题材不足只降级标记，不归零、不伪造、不阻断原共振。
- [x] 不引入分阶段 shadow/live 双跑；上线走"小范围观察 + 首日人工验证"。
- [x] 无独立守护进程/计划任务；全部集成 analyze 路由与既有 collector 生命周期。
- [x] 不新增 MongoDB 集合 / API / CLI；复用 `snapshot_sector_rows` 与 theme-confluence 研究链。
- [x] 条件判断语义逐条书面化，code review 逐行比对"任一/全部/至少"。
- [x] 无新增环境变量；权重为 Python 固定常量。
- [x] 首个上线日人工验证清单见 §9.3。

## 12. 风险与回退

- 双动量同质化/过拟合：个股与题材都用动量结构，调节幅度受限（±15）且方向用 theme-confluence 回测验证；golden case 固定。
- 板块动量拥挤后期失效：用生命周期门禁 + 反转惩罚通道对冲（实证：2026 年溢出链曾断裂）。
- 5 分钟热度 vs 半小时槽位粒度错配：题材动量只在半小时槽位序列上计算，不混用 5 分钟 bucket；`computedAt` 差异记录在 metadata 供审计。
- 题材序列缺槽：`theme_series_insufficient` 降级，不补零、不回填。
- 回退：纯字段扩展，TS/Python 均可逐文件回退；`theme` 字段为可选，旧消费方不受影响。

## 13. 待确认决策点

1. 融合方式：推荐"基分保留 + 有限调节（§7.1）"；备选 A：六因子权重重排（更强但破坏既有 golden 语义）；备选 B：纯展示不融合（最小改动，先看分布再决定）。
2. 题材强度序列：推荐 `heatScore`（全题材稳定字段）；备选：heat+breadth+资金 composite（信息更多但缺字段时降级面更大）。
3. 主题材选择：推荐"所属题材中 heatScore 最高者"；备选：`mainTheme` 字段优先。
4. 设计文档位置：现放 `docs/theme-module/`；如需归入 `docs/ranktrend/` 可调整。
