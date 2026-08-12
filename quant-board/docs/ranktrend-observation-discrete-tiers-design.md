# RankTrend 四维观察信号离散规则评分设计方案

> 主题：【共振】【趋势】【量价】【周期】四维观察信号评分算法优化
> 状态：设计稿（未实现）
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
| 共振 | `engine.py:1124 analyze_rank_resonance` | `0.35·relMomentum + 0.25·acceleration + 0.2·persistence + 0.2·jumpFreshness − 0.2·reversalPenalty`（clamp 0-100）；新入榜：`0.7·entryStrength + 0.3·jumpFreshness` | `direction` + `score` + 5 档 `label`（≥85 非常强 / ≥67 强 / ≥50 中等 / ≥27 较弱 / 否则非常弱）+ 因子明细 |
| 趋势 | `engine.py:985 compose_observation_scores` | `signedScore = decision.base.combinedScore`（clamp −1..1），`score = abs(signedScore)×100` | `direction`(buy/sell/hold) + `score` |
| 量价 | `volume_price.py:100 compute_volume_price_score` | `50 + 方向分(±15 八档) + 量价交叉(−20..+25) + 资金(±15)`（clamp 0-100） | `score` + `direction` + `quadrant` + `breakdown` + `reasons` |
| 周期 | `engine.py:955 compose_observation_scores` | `0.35·stageFitness + 0.25·pathCommitment + 0.2·momentumConfirmation + 0.2·riskSafety`（clamp 0-100） | `stage` + `score` + `veto` + `reasons` + `factors` |

四象协同 `observation.synergy`（`volume_price.py:202 compute_synergy_state`）已是规则式：启动确认 / 主升确认 / 风险升级 / 退潮 / 存疑 / 未判定，是本方案的先例与对齐对象。

## 3. 连续线性评分的问题清单

| # | 问题 | 证据 | 后果 |
|---|---|---|---|
| P1 | 伪精度 | `score` 0-100 连续输出 | 78 与 79 无语义差别，但被当作精确值；用户无法回答"为什么是 78" |
| P2 | 阈值断点跳变 | `_resonance_label`：67.4→"强"，66.9→"较弱" | 0.5 分跨档，展示误导 |
| P3 | 线性相加隐含独立假设 | 各因子直接加权求和 | 互斥强信号（如"缩量涨停 +25" vs "过度放量 −20"）只表现为数值，无优先级/否决语义 |
| P4 | 分数分布集中、区分度低 | `_positive()` 截断 + `abs()` 归一；历史权重 0.6 时高分占比约 20%（`ranktrend_routes.py:473` 注释） | 中位分集中在 40-70，排序分层不稳 |
| P5 | 维度间信息重叠 | `_apply_resonance_final`（`ranktrend_routes.py:502`）把量价修正渗透进 `resonance.score` | 四维不正交，"共振列"已含量价影响，解释性变差 |
| P6 | 方向与分数脱节 | buy+51 与 buy+88 规则层无区别 | 只有 label 区分，决策层未消费强度 |

## 4. 方案总览：混合式离散规则评分

每个维度在现有输出旁**新增**离散档位字段，连续分保留：

```json
{
  "observation": {
    "resonance": { "score": 78, "direction": "buy", "...": "现有字段不变", "signalTier": "A", "tierReasons": ["Jump新鲜(≥0.5) 且 相对动量>0"] },
    "rankTrend": { "score": 82, "direction": "buy", "signalTier": "B", "tierReasons": ["方向 buy + 加速度 buy，MACD 未金叉"] },
    "volumePrice": { "score": 76, "signalTier": "B", "tierReasons": ["放量上涨 + 资金流入"] },
    "lifecycle": { "score": 80, "stage": "expansion", "signalTier": "A", "tierReasons": ["allow + 扩散阶段"] },
    "synergy": { "...": "现有规则式不动", "signalTier": "S" }
  }
}
```

设计原则：

1. **档位 = 方向 + 强度 + 触发理由**：每维输出 `signalTier`（强度档）+ 方向（沿用现有 `direction`）+ `tierReasons`（触发规则原文）。
2. **规则按优先级求值，互斥分支只落一档**：强信号/否决信号优先，命中即返回，避免加权求和。
3. **否决/硬警告语义**：周期 `veto`、量价出货（vr>2.5 或 zljzb>20）等硬条件优先于普通档位。
4. **连续分降级为排序键**：同档位内用 `score` 排序（tie-break），避免离散化丢失排序能力。
5. **样本不足不伪装**：`insufficient` / 数据缺失时 `signalTier: "unknown"` + `tierReasons` 结构化原因，**不归零、不阻塞**（遵循 fail-visible-data-pipelines）。
6. **维度正交**：`signalTier` 由本维原始因子直接推导，不引用其它维度的修正分；`resonance.score` 的量价修正字段保留为展示，但 `resonance.signalTier` 只用排名动量因子。

统一档位模型（每维内部使用，四维合并另有总档）：

```text
tier ∈ { A+, A, B, C, D, E, unknown }
A+ / A = 强信号（A+ 仅事件驱动/缩量涨停等唯一性场景）
B      = 确认信号
C      = 中性/弱信号
D      = 反向/衰竭信号
E      = 硬风险（出货、否决、反转，仅量价/周期使用）
unknown = 样本不足或数据缺失（保留 reasons）
```

## 5. 各维离散规则定义

所有阈值均为**建议初值**，与现有常量对齐；上线前须用第 8 节回测方案校准。

### 5.1 共振（resonance）

输入：`relativeMomentum`、`acceleration`、`persistence`、`jumpFreshness`、`reversalPenalty`、`direction`（均现有字段）。
规则按优先级：

```
1. status == insufficient                     → tier=unknown（reasons 沿用现有）
2. reversalPenalty ≥ 0.6                      → 结果降一档（最低 D，保留原因"反转惩罚高"）
3. direction == buy 且 jumpFreshness ≥ 0.5
   且 relativeMomentum > 0                    → tier=A+（Jump 事件驱动 + 动量上行）
4. direction == buy 且 relativeMomentum > 0
   且 persistence ≥ 0.6                       → tier=A（共振确认）
5. direction == buy 且 relativeMomentum > 0   → tier=B（共振初现）
6. |relativeMomentum| ≤ 0.1                   → tier=C（中性）
7. direction == sell 且 relativeMomentum < 0
   且 persistence ≥ 0.6                       → tier=D（共振衰竭确认）
8. direction == sell 或 relativeMomentum < 0  → tier=D（共振衰竭）
```

说明：新入榜路径（`historyState == new_entry`）规则 3/4/5 的输入退化为 `entryStrength` 与 `jumpFreshness`，规则 4/5 合并为 `entryStrength ≥ 0.3 → B`，否则 `C`；`entryStrength` 定义沿用 `clamp((percentile−50)/25, 0, 1)`。
排序键：`resonance.score`（保留量价修正前的 `rawScore` 供审计）。

### 5.2 趋势（rankTrend）

输入：`decision.base.signal`、`technical.signals.direction.signal`、`technical.signals.acceleration.signal`、`technical.macd.cross`（golden 合同已有字段）。
规则按证据一致性：

```
1. decision.base.signal == buy
   且 acceleration == buy 且 macd.cross == golden → tier=A（三证据共振）
2. decision.base.signal == buy
   且 (acceleration == buy 或 macd.cross == golden) → tier=B（双证据确认）
3. decision.base.signal == buy                    → tier=C（弱趋势）
4. decision.base.signal == hold                   → tier=C（中性）
5. decision.base.signal == sell
   且 (acceleration == sell 或 macd.cross == dead) → tier=D（趋势转弱确认）
6. decision.base.signal == sell                   → tier=D（趋势转弱）
```

说明：`decision.base.signal` 已综合 direction/acceleration/cross/macd 权重（见 `ranktrend-golden.md` 默认配置），本规则在其上叠加证据数量，体现"一致性强则档位高"。
排序键：`observation.rankTrend.score`。

### 5.3 量价（volumePrice）

输入：`change`、`volumeRatio(vr)`、`zlje`、`zljzb`、`direction`、`quadrant`（现有 `compute_volume_price_score` 已算好）。
规则按互斥分支（沿用现有判定函数，仅改档位语义）：

```
1. 数据不足（chg/vr 缺失）                      → tier=unknown（reasons 沿用"量价数据不足"）
2. 缩量涨停（vr≤0.95 且 limit_up）              → tier=A+（封板惜售，唯一性强信号）
3. zljzb > 20（资金对倒） 或 vr > 2.5（过度放量） → tier=E（硬风险，hardWarn=true）
4. 放量上涨（vr>1.05 且 chg>0） 且 zljzb > 0    → tier=A（量价配合 + 资金流入）
5. 放量上涨 / 温和放量（1.05≤vr≤2 且 chg>0）    → tier=B
6. 缩量上涨（非涨停）/ 常态                      → tier=C
7. 放量下跌（vr>1.05 且 chg<0）                 → tier=D（风险）
8. 缩量下跌 / 资金净流出                        → tier=D（无量阴跌）
```

说明：规则 2/3 与 4/5 互斥，命中即返回；`breakdown`（方向/量/资金分）保留为审计。
排序键：`volumePrice.score`。

### 5.4 周期（lifecycle）

输入：`cycle.stage`、`cycle.decision.action`（veto/caution/allow/exit_watch，`engine.py:699 lifecycle_decision` 已有）。
规则（状态机本身已离散，只映射档位）：

```
1. 数据不足 / lifecycle 不可用                    → tier=unknown（reasons 沿用现有）
2. action == veto                                 → tier=E（硬否决，保持现有一票否决语义）
3. action == allow 且 stage ∈ {ignition, expansion} → tier=A（优选路径）
4. action == caution                              → tier=B（谨慎）
5. action == exit_watch（stage == crowded）        → tier=D（回避/退出观察）
6. 其它（cooling 等）                             → tier=C（中性）
```

说明：`lifecycle.veto` 字段保留；`score`（机会成熟度）保留为排序键。档位规则与 `compose_strategy` 的 A_MAIN/B_IGNITION 分层不冲突，前者是观察信号、后者是候选池分层。

### 5.5 四维合并（观察信号总档）

参照 `compute_synergy_state` 模式扩展为表决式，输出到 `observation.synergy.signalTier`（synergy.state 文本保留）：

```
输入：四维 signalTier（unknown 不计入同向票数）
1. 周期 tier == E（veto）                         → 总档=E（硬否决，reasons 注明周期否决）
2. 量价 tier == E                                 → 总档=D（硬风险，reasons 注明出货/对倒；不否决，仅降档警示）
3. 同向(≥3 维 A/B 且方向一致) 且 周期 tier ∈ {A, B} → 总档=S（强一致，对应"主升确认"）
4. 同向 2 维 A/B                                  → 总档=A
5. 同向 1 维 A/B                                  → 总档=B（分歧）
6. 其余                                           → 总档=C（无明确方向）
```

方向一致性判定：以各维 `direction` 的 buy/sell/hold 为准；共振方向由 `resonance.direction` 提供，趋势/量价/周期同现有字段。
排序键：四维 `score` 加权（权重沿用现状：共振 0.35 / 趋势 0.25 / 量价 0.2 / 周期 0.2，可后续回测校准），仅用于 S/A/B/C 同档内排序。

## 6. 输出合同变更

- **新增字段**（仅 `observation.*` 内，均为可选，旧字段与语义完全不动）：

| 位置 | 字段 | 类型 | 说明 |
|---|---|---|---|
| `observation.resonance` | `signalTier` | string enum | A+/A/B/C/D/unknown |
| `observation.resonance` | `tierReasons` | string[] | 命中规则原文 |
| `observation.rankTrend` | `signalTier` | string enum | A/B/C/D/unknown |
| `observation.rankTrend` | `tierReasons` | string[] | 同上 |
| `observation.volumePrice` | `signalTier` | string enum | A+/A/B/C/D/E/unknown |
| `observation.volumePrice` | `tierReasons` | string[] | 同上 |
| `observation.lifecycle` | `signalTier` | string enum | A/B/C/D/E/unknown |
| `observation.lifecycle` | `tierReasons` | string[] | 同上 |
| `observation.synergy` | `signalTier` | string enum | S/A/B/C/D/E/unknown |
| `observation.synergy` | `tierReasons` | string[] | 同上 |

- **不改动**：`score`、`direction`、`label`、`stage`、`quadrant`、`breakdown`、`reasons`、`decision.*`、`strategy.*` 等全部现有字段与语义。
- 快照落库：`signalTier` 为派生展示字段，不强制写入 `snapshot_stock_rows`；如需落库须同步 `supabase_schema.sql` 与 `snapshot_repository.py` 映射（默认不落库，避免污染快照合同）。
- TS 消费：`src/services/rankTrend/types.ts` 的 `RankTrendAnalysisResult.observation` 补充可选字段；`DataTable.vue` 四列改为"方向箭头 + 档位徽章 + 连续分（悬停显示）"。

## 7. 前端展示映射（DataTable 四列）

| 列 | 现展示 | 改后展示 |
|---|---|---|
| 共振 | `分数%（label）` | 档位徽章（A+~D）+ 悬停显示分数/因子/tierReasons |
| 趋势 | `方向 + 分数` | 档位徽章 + 悬停显示证据组合/tierReasons |
| 量价 | `方向 + 综合评估值(0-100)` | 档位徽章 + 象限标签 + 悬停显示 breakdown/tierReasons |
| 周期 | `阶段 + 分数%` | 档位徽章 + 阶段名 + 悬停显示 action/tierReasons |

展示规则：
- `unknown` 显示 `--` + 悬停原因，不做 0 值伪装。
- `E` 档使用红色警示样式（对齐现有 `hardWarn` 视觉）。
- 档位徽章颜色统一：A+/A 绿系、B 青系、C 灰系、D/E 红系，与现有主题色一致（实现时按 `src/themes` 现有 token）。

## 8. 回测验证方案（证明规则有效性）

目标：验证"档位越高，后续收益/命中率越好"的单调性，避免拍脑袋规则上线。

1. 数据：现有历史快照（默认 `half_hour`，dataset 选取 ≥2 周交易日样本）。
2. 方法：对每帧每股票计算四维 `signalTier` + 四维合并总档，统计各档位在**未来 N 帧**（N=1/3/8，对应短/中/长）的相对排名收益均值、方向精度（buy 档中实际上涨比例）、样本数。
3. 验收标准（建议初值，可调整）：
   - S 档样本数 ≥ 30 且未来收益 > A 档 > B 档 > C 档（单调递减或至少不反转）；
   - D/E 档收益显著低于 C 档（负收益或明显偏低）；
   - A+/A 档方向精度 ≥ 60%；
   - `unknown` 档占比 < 5%（否则说明样本门限过严）。
4. 工具：沿用 QuantBoard 回测主链（`backend/core/backtest`）或直接对 frames API 输出做统计脚本；结果报告到 `quant-board/data/reports/`，不落库。
5. 回退判定：任一维度档位单调性不成立，则该维规则回到设计讨论，不以其它维度的"整体效果"掩盖。

## 9. 实施步骤与验收命令

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | 在 `engine.py` / `volume_price.py` 增加 `_tier_*` 纯函数与 `signalTier`/`tierReasons` 组装，接入 `compose_observation_scores` 与 `ranktrend_routes.py` | `cd quant-board; .\.venv\Scripts\python.exe -m pytest` 全绿 |
| 2 | 补充单元测试：每维每档规则至少 1 个输入样例 + 互斥分支 + insufficient 用例（含 `unknown` 不归零断言） | pytest 新增用例全绿 |
| 3 | TS 类型补充（`src/services/rankTrend/types.ts`） | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` |
| 4 | `DataTable.vue` 四列档位徽章展示 + 悬停 tierReasons | `pnpm test` + 浏览器验收（Playwright，检查四列渲染、unknown 显示 `--`、E 档警示样式、控制台无错误） |
| 5 | 回测验证（第 8 节），产出档位收益/命中率报告 | 报告满足验收标准或给出规则修订结论 |
| 6 | golden case 更新 + 版本提升 | 按 `ranktrend-golden.md` 变更管理：更新 case、提升 `ranktrend_version`、重跑 golden 测试、历史回测不覆盖 |

## 10. 风险与回退

- **规则表维护成本 / 组合爆炸**：档位规则每维 ≤ 8 条、互斥分支，单维可控；四维合并规则 ≤ 6 条。新增规则必须走同一套单测 + 回测验收。
- **离散化导致排序退化**：同档股票多 → 必须保留连续分 tie-break（设计原则 4）。
- **golden 合同扩展影响回测/快照**：只新增可选字段、不动旧字段语义，历史回测与快照兼容；`signalTier` 默认不落库。
- **阈值敏感**：所有阈值为初值，第 8 节回测不通过即回退到设计讨论，不强行上线。
- **回退路径**：删除 `signalTier` 组装代码 + 前端退回连续分展示即可恢复现状；无数据迁移、无合同破坏。

## 11. 变更管理

- 实现前必须先在 `quant-board/docs/ranktrend-golden.md` 输出合同一节补充 `observation.signalTier` 字段说明。
- 回测/前端口径变化同步检查 `quant-board/docs/backtest-policy.md` 与 `quant-board/docs/architecture.md`。
- `strategy_version` / `ranktrend_version` 提升遵循 `ranktrend-golden.md` 第 6 节变更管理流程。
- 本设计稿为过程文档，实现验收后归档到 `quant-board/docs/` 对应专题目录，不在根目录新增过程文件。
