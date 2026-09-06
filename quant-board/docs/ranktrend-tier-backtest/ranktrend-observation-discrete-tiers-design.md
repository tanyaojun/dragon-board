# RankTrend 四维观察信号离散规则评分设计方案

> 命名注记（2026-09-06，WP3.1）：本文"四维"为历史命名；当前口径为 **5 投票维（res/rank/vp/cs + 热榜情绪）+ 1 环境门（lifecycle）**，lifecycle 不进投票、以 veto/降档影响合成。

> 主题：【共振】【趋势】【量价】【周期】四维观察信号评分算法优化
> 状态：**已实现**（阶段 3 三方向修复 + vote v4 语义校准已落地，见 `ranktrend-signal-tier-backtest-plan.md` §3-§5；2026-08-16 按生命周期区分度结论补充注记）
> 范围：四维一次做完（共振 / 趋势 / 量价 / 周期 + 四维合并）
> 落位：Python golden `quant-board/backend/analysis/ranktrend/`（生产）+ Dragon Board 前端展示（消费）

## 1. 背景与目标

1. 现状：四维观察信号全部由 Python golden 生产连续线性加权分（0-100），前端 `DataTable.vue` 只消费展示。
2. 问题：连续分存在伪精度、阈值断点跳变、因子线性相加隐含独立假设、维度间信息重叠等缺陷（详见第 3 节）。
3. 目标：每个维度输出**离散信号档位**（规则可解释、可回测），同时**保留连续分**作为排序键与审计字段，形成混合式评分。
4. 约束：不改动现有输出合同的已有字段语义；只在 `observation.*` 上**新增** `signalTier` 相关字段；不引入新数据源，规则全部基于现有字段。
5. 验收：每档规则可在历史快照上回测命中率/收益分布；golden case 全绿；前端展示档位徽章后行为可解释。

## 2. 现状还原（四维评分链路）

数据流：Python `POST /api/ranktrend/analyze`（`backend/api/ranktrend_routes.py`）→ `RankTrendPythonEngine._build_signal`（`engine.py:1484`）→ 各维度分数写入 `analysis.observation.*` → 前端 `RankTrendObservationService` / `DataTable.vue` 只读展示。

| 维度 | 生产位置 | 现算法（连续线性） | 现输出 |
|---|---|---|---|
| 共振 | `engine.py:1124 analyze_rank_resonance` | `0.35·relMomentum + 0.25·acceleration + 0.2·persistence + 0.2·jumpFreshness − 0.2·reversalPenalty`（clamp 0-100）；新入榜：`0.7·entryStrength + 0.3·jumpFreshness` | `direction` + `score` + 5 档 `label` + 因子明细 |
| 趋势 | `engine.py:955 compose_observation_scores` | `signedScore = decision.base.combinedScore`（clamp −1..1），`score = abs(signedScore)×100` | `direction`(buy/sell/hold) + `score` |
| 量价 | `volume_price.py:100 compute_volume_price_score` | `50 + 方向分(±15 八档) + 量价交叉(−20..+25) + 资金(±15)`（clamp 0-100） | `score` + `direction` + `quadrant` + `breakdown` + `reasons` |
| 周期 | `engine.py:955 compose_observation_scores` | `0.35·stageFitness + 0.25·pathCommitment + 0.2·momentumConfirmation + 0.2·riskSafety`（clamp 0-100） | `stage` + `score` + `veto` + `reasons` + `factors` |

四象协同 `observation.synergy`（`volume_price.py:202 compute_synergy_state`）已是规则式，是本方案的先例与对齐对象。

## 3. 连续线性评分的问题清单

| # | 问题 | 证据 | 后果 |
|---|---|---|---|
| P1 | 伪精度 | `score` 0-100 连续输出 | 78 与 79 无语义差别，但被当作精确值；用户无法回答"为什么是 78" |
| P2 | 阈值断点跳变 | `_resonance_label`：67.4→"强"，66.9→"较弱" | 0.5 分跨档，展示误导 |
| P3 | 线性相加隐含独立假设 | 各因子直接加权求和 | 互斥强信号（如"缩量涨停 +8" vs "过度放量 −20"）只表现为数值，无优先级/否决语义 |
| P4 | 分数分布集中、区分度低 | `_positive()` 截断 + `abs()` 归一 | 中位分集中在 40-70，排序分层不稳 |
| P5 | 维度间信息重叠 | `_apply_resonance_final`（`ranktrend_routes.py:502`）把量价修正渗透进 `resonance.score` | 四维不正交，"共振列"已含量价影响 |
| P6 | 方向与分数脱节 | buy+51 与 buy+88 规则层无区别 | 只有 label 区分，决策层未消费强度 |

## 4. 设计原则

1. **正交因子原则**：每维只消费本维真正独立的因子，不重复计数、不重算已综合的原始字段。这是本稿相对初稿的核心优化（详见第 5 节各维说明）。
2. **统一档位语义**：全维度 + 四维合并共用同一套档位枚举（第 5 节），前端只需实现一套徽章，认知负担最小。
3. **否决/硬风险优先**：规则按优先级求值，硬否决（周期 veto）、硬风险（量价出货）优先于普通档位，命中即返回。
4. **方向与强度分离**：每维档位 = 方向（buy/sell/hold 或阶段）+ 强度档；合并层只用方向 + 周期环境门。
5. **连续分降级为排序键**：同档位内用 `score` 排序（tie-break），避免离散化丢失排序能力。
6. **样本不足不伪装**：`insufficient` / 数据缺失时 `signalTier: "unknown"` + 结构化原因，**不归零、不阻塞**（遵循 fail-visible-data-pipelines）。
7. **维度正交**：`signalTier` 由本维原始因子直接推导，不引用其它维度的修正分；`resonance.signalTier` 只用排名动量因子，不受量价修正影响。

## 5. 统一档位模型

全维度与四维合并共用一套枚举，语义全局一致：

```text
S       = 强信号 / 唯一性场景（事件驱动 Jump、强趋势）
A       = 确认信号（方向确认且路径/量能/资金支持）
B       = 弱确认 / 待观察（方向确认但支持不足）
C       = 中性（无明确方向）；缩量涨停封板买不进也落 C（信号真但不可交易）
D       = 反向 / 衰竭 / 回避（sell、反转、冷却、拥挤）
E       = 硬风险（周期一票否决、量价对倒出货）
unknown = 样本不足或数据缺失（保留结构化 reasons，不归零）
```

每维输出：`signalTier`（档位）+ `direction`（沿用现有方向字段）+ `tierReasons`（命中规则原文）。

## 6. 各维离散规则定义

所有阈值均为**建议初值**，与现有常量对齐；上线前须用第 9 节回测方案校准。

### 6.1 共振（resonance）

正交因子：`direction`（综合方向，已吸收 relMomentum/acceleration 的方向面）、`persistence`（路径质量）、`jump`（事件）、`reversalPenalty`（反转风险）。**不再重复使用 relativeMomentum 与 direction 做双重条件**（初稿问题：direction 本身已含 relMomentum）。

```
优先级从高到低：
1. status == insufficient                    → unknown（reasons 沿用现有）
2. reversalPenalty ≥ 0.6                     → D（反转风险否决，reasons 注明"路径反复/回撤，反转惩罚高"）
3. jump.event == "jump" 且 direction == buy
   且 jumpFreshness ≥ 0.5                    → S（Jump 事件驱动，排名跳跃式上升）
4. direction == buy 且 persistence ≥ 0.6     → A（方向确认 + 路径持续）
5. direction == buy                          → B（方向确认但路径持续不足）
6. direction == hold                         → C（中性）
7. direction == sell                         → D（共振衰竭/反向）
```

说明：新入榜路径（`historyState == new_entry`）的因子退化为 `entryStrength` 与 `jumpFreshness`，规则 4/5 合并为 `entryStrength ≥ 0.3 → A`，否则 `B`（`entryStrength` 沿用 `clamp((percentile−50)/25, 0, 1)`）。
排序键：`resonance.rawScore`（量价修正前，`_apply_resonance_final` 已保留）。

### 6.2 趋势（rankTrend）

正交因子：`decision.base.signal`（综合方向，`compose_decision` 已含 buy_count≥2 门槛）+ `combinedScore`（加权强度）。**初稿问题**：`base.signal` 本身已综合 direction/acceleration/zeroCross/macd 四分量，再拆开数"三证据"是重复计数；本稿直接用强度分层。

```
1. base.signal == hold                        → C（中性）
2. base.signal == sell                        → D（趋势转弱/反向）
3. base.signal == buy:
   a. |combinedScore| ≥ 0.5                   → S（强趋势，加权强度远超阈值）
   b. |combinedScore| ≥ 0.25                  → A（趋势确认）
   c. 其余（0.12 ≤ |combinedScore| < 0.25）    → B（弱趋势，勉强越过 buyScoreThreshold=0.12）
```

说明：`base.signal == buy` 已保证 `combinedScore ≥ buyScoreThreshold(0.12)`，故 buy 分支强度区间为 [0.12, 1]。阈值 0.5/0.25 为建议初值，用第 9 节回测校准。
排序键：`observation.rankTrend.score`。

### 6.3 量价（volumePrice）

正交因子：`quadrant`（方向 × 放缩量）、`breakdown`（direction/volume/fund 三分）、`reasons` 关键标志（缩量涨停/对倒出货/过度放量）。**初稿问题**：重新硬编码 `chg>0 / vr>1.05` 分支，而 `compute_volume_price_score` 已算好 quadrant/breakdown/reasons；本稿直接消费，不再重算原始字段。

```
1. 数据不足（chg/vr 缺失）                       → unknown（reasons 沿用"量价数据不足"）
2. reasons 含 "对倒出货" 或 "过度放量"            → E（硬风险优先，hardWarn=true）
3. reasons 含 "缩量涨停"                         → C（缩量涨停封板买不进，信号真但不可交易，降出强档）
4. quadrant == rise_volume 且 breakdown.fund > 0 → A（放量上涨 + 资金流入，量价资金三确认）
5. quadrant == rise_volume                       → B（放量上涨，量价配合）
6. quadrant == rise_shrink 或 normal             → C（缩量上涨/常态，无量虚涨风险）
7. quadrant == fall_volume 或 fall_shrink        → D（放量下跌=风险 / 缩量下跌=无量阴跌）
```

说明：`breakdown.fund` 的符号即资金净流入/流出方向。**硬风险（规则 2）优先于强信号**——`compute_volume_price_score` 中"缩量涨停"（vr≤0.95 且 limit_up）与"对倒出货"（zljzb>20）可同时命中 reasons，此时必须以 E 为准，不得漏判出货风险。规则 2 与 3~7 互斥，命中即返回。`breakdown` 三分保留为审计。
修订说明（2026-08）：缩量涨停曾映射 S"封板惜售唯一性强信号"，但缩量涨停 = 一字/秒板封死买不进，从执行角度不可交易；已降为 C（量价分缩量涨停 +25→+8），放量涨停（有换手可排单）保持 A/B。
排序键：`volumePrice.score`。

### 6.4 周期（lifecycle）

正交因子：`cycle.stage`（5 态）+ `cycle.decision.action`（veto/caution/allow/exit_watch）+ `entryAdvice.bias`。**初稿问题**：cooling 阶段 `action=caution` 但 `entryAdvice.bias=avoid`（`engine.py:681`），初稿映射到 C（中性）语义错误；本稿 cooling 映射 D（回避）。

```
1. 数据不足 / lifecycle 不可用                   → unknown（reasons 沿用现有）
2. action == veto                               → E（硬否决，保持现有一票否决语义）
3. action == allow 且 stage ∈ {ignition, expansion} → A（优选路径）
4. action == caution 且 stage ∈ {ignition, expansion} → B（低可见度点火/假突破，谨慎观察）
5. action == exit_watch（stage == crowded）      → D（拥挤，退出观察）
6. stage == cooling                             → D（冷却，entryAdvice=avoid，回避）
7. 其它                                         → C（中性）
```

说明：`lifecycle.veto` 字段保留；`score`（机会成熟度）保留为排序键。档位规则与 `compose_strategy` 的 A_MAIN/B_IGNITION 候选池分层不冲突——前者是观察信号、后者是候选池分层。

> **2026-08-16 注记（生命周期区分度结论，见 `ranktrend-lifecycle-threshold-optimization-design.md` §8.2）**：
> 生命周期档位（A/B/C/D/E）是**环境状态标记，不是方向预测力**。坐标下降搜索证明：A 档
> （allow+ignition/expansion，样本 21475）h8 excess 0.0092 **反低于** B 档（caution，样本 1877）
> 0.0228，且该关系是分位结构性差异（A 高分位混杂被均值回归拉低），阈值不可调。因此：
> - **前端展示**：周期列改为"环境门标签"（stage 中文 + 环境色 + veto 角标），**不做方向色徽章**
>   （见 `ranktrend-four-dimension-column-plan.md` §2.1）；
> - **四维合并**：周期仍只作环境门（§7 规则 1/5，veto 否决 / caution/回避 降档），不参与方向投票；
> - **单维验收豁免**：§9 单调性验收对生命周期维度不适用（无 S 档、A/B 区分受分位结构限制），
>   生命周期验收以"环境门正确性"（veto 是否生效、回避是否降档）为准。

## 7. 四维合并（观察信号总档）

合并语义：**周期是环境门（是否允许入场），共振/趋势/量价是方向信号（投票）**，二者角色不同，不可混同计票。

```
0. 方向归一（各维 direction 值域不同，先统一为 buy/sell/hold）：
   共振 direction: buy/sell/hold（analyze_rank_resonance 直接输出）
   趋势 direction: buy/sell/hold（decision.base.signal 直接输出）
   量价 direction: up→buy, down→sell, neutral→hold（volume_price.py 输出 up/down/neutral，须映射）

1. 周期 tier == E（veto）                  → 总档 E（硬否决，reasons 注明周期否决）
2. 量价 tier == E                          → 总档 D（硬风险警示：对倒出货/过度放量，不否决但强降档）
3. 档位强度加权投票（vote 语义改进 2026-08-15，v4 最终权重：方向主导 × 档位幅度）：
   strength：S=1.2 / A=1.0 / B=0.8 / C=0.5 / D=1.0 / E=1.0
   vote = strength × dir_sign(direction)，dir_sign: buy/up=+1, sell/down=-1, hold=0（弃权）
   方向主导（D/E 档 buy 仍投正分，同旧票数语义）；档位幅度区分体现于 S/B/C：
   第 5 维热度（技术字段 crossSection，UI 展示名「热度」；默认参与，config.tierSynergyCrossSectionVote=1.0，2026-08-17 用户决策）：
     cs 票 = CS_STRENGTH(cs_tier) × 权重，CS_STRENGTH：A=+1.0 / B=+0.5 / C=-0.5 / D=-1.0
   第 6 维 priceMomentum / 第 7 维 priceRankDivergence：
     tierSynergyPriceMomentumVote=0 / tierSynergyDivergenceVote=0（观察因子，默认不参与投票）
   vote_sum = vote(共振) + vote(趋势) + vote(量价) + cs 票（+ pm 票 / dv 票 当对应权重 > 0）
4. 档位判定（按优先级，阈值 config.tierSynergyVote*，默认 strong=2.0/weak=1.0/reverse=-1.0）：
   a. vote_sum ≥ strong + 1                → S（高票一致强买，如三维 A/buy 或三维 S/buy）
   b. vote_sum ≥ strong                     → A（方向一致强买，如两维 A/buy）
   c. vote_sum ≥ weak                       → B（方向分歧，弱买，如一维 A/buy）
   d. vote_sum ≤ reverse                    → D（反向，如一维 D/sell）
   e. 其余                                  → C（无明确方向）
5. 周期环境修正：周期 tier == B（caution）或 D（cooling/crowded 回避）时，
   4a/4b 的 S/A 降一档（S→A，A→B）；B/C/D 不降
```

说明：
- 周期无 buy/sell 方向，故不参与投票，只作环境门（veto 否决 / caution/回避 降档 / allow 放行）。
- 量价 `direction` 是 `up/down/neutral` 而非 `buy/sell/hold`，第 0 步先归一，否则投票语义错误。
- 档位加权核心语义：S=1.2/B=0.8/C=0.5 在**票数内**区分强度（B 档 3 票仅 A、C 档 3 票仅 B、
  弱确认单票不升 B），D/E=1.0 保持方向主导（单维空即 D）——权重经 h1 验收口径扫描选定
  （saEx 0.0651 ≥ 0.05、passHard=True，优于全 1.0 基线 0.0519）。
- `vote_sum` 覆盖范围：三维 ±6 + 热度 ±1（第 5 维默认开）；+3.0（三 A/buy）为 S，−1.0（单 D/sell）为 D，0 为中性或对冲。
  热度 B 档（+0.5）可把 2.6 分（A/B/B 三票）抬到 3.1 达 S 线——实例：江西铜业 600362
  共振 A·涨(+1.0) + 趋势 B·涨(+0.8) + 量价 B·涨(+0.8) + 热度 B(+0.5) = 3.1 ≥ 3.0 → S，
  周期 D（拥挤/回避）降一档 → 最终 A（买入，tierReasons 含"方向一致强买（档位加权高分）；周期 D 环境降档"）。
- `synergy.state` 文本字段保留不变，`synergy.signalTier` 为新增总档。
- 同档内排序用各维连续分，权重未定，待第 9 节回测校准后确定（不沿用杜撰权重）。

## 8. 输出合同变更

- **新增字段**（均为可选，旧字段与语义完全不动）：

| 位置 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `analysis.resonance` | `signalTier` | string enum | S/A/B/C/D/unknown |
| `analysis.resonance` | `tierReasons` | string[] | 命中规则原文 |
| `observation.rankTrend` | `signalTier` | string enum | S/A/B/C/D/unknown |
| `observation.rankTrend` | `tierReasons` | string[] | 同上 |
| `observation.volumePrice` | `signalTier` | string enum | S/A/B/C/D/E/unknown |
| `observation.volumePrice` | `tierReasons` | string[] | 同上 |
| `observation.lifecycle` | `signalTier` | string enum | A/B/C/D/E/unknown |
| `observation.lifecycle` | `tierReasons` | string[] | 同上 |
| `observation.synergy` | `signalTier` | string enum | S/A/B/C/D/E/unknown |
| `observation.synergy` | `tierReasons` | string[] | 同上 |

> **字段归属说明**：`resonance` 是 `analysis` 的**顶层字段**（`ranktrend_routes.py:384 analysis["resonance"] = resonance`），不是 `observation` 子字段；`observation` 是 `analysis` 下的独立子对象（`ranktrend_routes.py:392 analysis.setdefault("observation", {})`），其下只有 `rankTrend` / `lifecycle` / `volumePrice` / `synergy`。故 `resonance.signalTier` 落在 `analysis.resonance.*`，其余四维落在 `observation.*`。

- **不改动**：`score`、`direction`、`label`、`stage`、`quadrant`、`breakdown`、`reasons`、`decision.*`、`strategy.*` 等全部现有字段与语义。
- 快照落库：`signalTier` 为派生展示字段，默认不写入 `snapshot_stock_rows`；如需落库须同步 `supabase_schema.sql` 与 `snapshot_repository.py` 映射（默认不落库，避免污染快照合同）。
- TS 消费：`src/services/rankTrend/types.ts` 的 `RankTrendAnalysisResult.observation` 补充可选字段；`DataTable.vue` 共振/趋势/量价三列改为"方向箭头 + 档位徽章 + 连续分"，**周期列改为环境门标签**（stage 中文 + 环境色 + veto 角标，不做方向徽章——2026-08-16 优化，见 `ranktrend-four-dimension-column-plan.md` §2.1）；新增【四维】synergy 总档列置末。

## 9. 回测验证方案（证明规则有效性）

目标：验证"档位越高，后续收益/命中率越好"的单调性，避免拍脑袋规则上线。

1. 数据：现有历史快照（默认 `half_hour`，dataset 选取 ≥2 周交易日样本）。
2. 方法：对每帧每股票计算四维 `signalTier` + 四维合并总档，统计各档位在**未来 N 帧**（N=1/3/8，对应短/中/长）的相对排名收益均值、方向精度（buy 档中实际上涨比例）、样本数。
3. 验收标准（建议初值，可调整）：
   - S 档样本数 ≥ 30 且未来收益 > A 档 > B 档 > C 档（单调递减或至少不反转）；
   - D/E 档收益显著低于 C 档（负收益或明显偏低）；
   - S/A 档方向精度 ≥ 60%；
   - `unknown` 档占比 < 5%（否则说明样本门限过严）。
   - **生命周期维度豁免**（2026-08-16 结论）：lifecycle 合法档位 A/B/C/D/E（无 S），A/B 区分
     受分位结构限制（坐标下降证明不可调），单调性验收对该维度不适用；以"环境门正确性"
     （veto 生效 / caution、cooling 回避降档）为准。阶段 3 实际验收口径：**synergy 合并档**
     S/A/B excess 单调（0.088/0.039/-0.006，passHard=True）达标，单维不强制。
4. 工具：沿用 QuantBoard 回测主链（`backend/core/backtest`）或直接对 frames API 输出做统计脚本；结果报告到 `quant-board/data/reports/`，不落库。
5. 回退判定：任一维度档位单调性不成立，则该维规则回到设计讨论，不以其它维度的"整体效果"掩盖。

## 10. 实施步骤与验收命令

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | 在 `engine.py` / `volume_price.py` 增加 `_tier_*` 纯函数与 `signalTier`/`tierReasons` 组装，接入 `compose_observation_scores` 与 `ranktrend_routes.py` | `cd quant-board; .\.venv\Scripts\python.exe -m pytest` 全绿 |
| 2 | 补充单元测试：每维每档规则至少 1 个输入样例 + 互斥分支 + insufficient 用例（含 `unknown` 不归零断言） | pytest 新增用例全绿 |
| 3 | TS 类型补充（`src/services/rankTrend/types.ts`） | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` |
| 4 | `DataTable.vue` 四列方向 + 连续分展示，档位仅用于 tooltip/诊断 | `pnpm test` + 浏览器验收（Playwright，检查方向/分值渲染、unknown 显示 `--`、不渲染各维徽章、控制台无错误） |
| 5 | 回测验证（第 9 节），产出档位收益/命中率报告 | 报告满足验收标准或给出规则修订结论 |
| 6 | golden case 更新 + 版本提升 | 按 `ranktrend-golden.md` 变更管理：更新 case、提升 `ranktrend_version`、重跑 golden 测试、历史回测不覆盖 |

## 11. 风险与回退

- **规则表维护成本 / 组合爆炸**：档位规则每维 ≤ 7 条、互斥分支，单维可控；四维合并规则 ≤ 5 条。新增规则必须走同一套单测 + 回测验收。
- **离散化导致排序退化**：同档股票多 → 必须保留连续分 tie-break（设计原则 5）。
- **golden 合同扩展影响回测/快照**：只新增可选字段、不动旧字段语义，历史回测与快照兼容；`signalTier` 默认不落库。
- **阈值敏感**：所有阈值为初值（趋势 0.5/0.25、共振 persistence 0.6、反转惩罚 0.6 等），第 9 节回测不通过即回退到设计讨论，不强行上线。
- **回退路径**：删除 `signalTier` 组装代码 + 前端退回连续分展示即可恢复现状；无数据迁移、无合同破坏。

## 12. 变更管理

- 实现前必须先在 `quant-board/docs/ranktrend-golden.md` 输出合同一节补充 `observation.signalTier` 字段说明。
- 回测/前端口径变化同步检查 `quant-board/docs/backtest-policy.md` 与 `quant-board/docs/architecture.md`。
- `strategy_version` / `ranktrend_version` 提升遵循 `ranktrend-golden.md` 第 6 节变更管理流程。
- 本设计稿为过程文档，实现验收后归档到 `quant-board/docs/` 对应专题目录，不在根目录新增过程文件。

---

## 附：本稿相对初稿的规则优化点（供 review）

1. **统一档位枚举**：初稿各维档位集合不一（共振 A+/A/B/C/D、趋势 A/B/C/D、量价 A+/A/B/C/D/E、周期 A/B/C/D/E、合并 S/A/B/C/D/E），前端需处理 7 种值；本稿统一为 `S/A/B/C/D/E/unknown`，前端一套徽章。
2. **消除重复计数（趋势）**：初稿把 `base.signal` 拆成 direction/acceleration/macd 三证据再数一遍，忽略 `compose_decision` 已含 buy_count≥2 门槛与加权强度；本稿直接用 `base.signal`（方向）+ `combinedScore`（强度）分层。
3. **消除重算原始字段（量价）**：初稿硬编码 chg/vr 分支，重复 `compute_volume_price_score` 已算好的 quadrant/breakdown/reasons；本稿直接消费这三个语义化输出。
4. **消除方向冗余（共振）**：初稿用 `direction == buy 且 relativeMomentum > 0` 双重条件，但 direction 已综合 relMomentum；本稿只用 `direction` + `persistence` + `jump` + `reversalPenalty`。
5. **修正 cooling 映射（周期）**：初稿把 cooling 映射到 C（中性），但 `entryAdvice.bias=avoid`、`action=caution`，本稿映射 D（回避）。
6. **反转风险语义化（共振）**：初稿 `reversalPenalty≥0.6` 作"降一档"，与 Jump 事件档模糊叠加；本稿改为明确的 D 档否决（规则 2，优先于事件档）。
7. **合并规则公式化**：初稿"同向票数"未区分周期无方向；本稿明确周期=环境门、共振/趋势/量价=方向投票，票数规则可计算（buy=+1/sell=−1/hold=0）。
