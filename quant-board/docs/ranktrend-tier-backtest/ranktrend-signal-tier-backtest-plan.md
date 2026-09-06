# RankTrend 五维信号阈值参数搜索回测方案

> 命名注记（2026-09-06，WP3.1）：本文"四维"为历史命名；当前口径为 **5 投票维（res/rank/vp/cs + 热榜情绪）+ 1 环境门（lifecycle）**，lifecycle 不进投票、以 veto/降档影响合成。

> 主题：共振/趋势/量价/周期四维观察信号 + synergy 四维合并档位的参数阈值治理与回测优化
> 状态：**已落地**（§3–§5 已全部实现并通过 golden；本文保留方案原文，就地标注实现位置与核对行号；核对日期 2026-08-15）
> 前置文档：`ranktrend-observation-discrete-tiers-design.md`（档位规则）、`ranktrend-factor-calibration-plan.md`（参数抽取）
> 落位：QuantBoard 后端 `backend/analysis/ranktrend/` + `backend/optimization/` + `backend/core/backtest/`（生产）
> 配套：行情主页【四维】列前端方案见 `ranktrend-four-dimension-column-plan.md`

## 1. 背景与目标

1. 现状：五维 `signalTier`（共振/趋势/量价/周期/synergy 合并）已由 Python golden 生产，但所有阈值均为**拍脑袋硬编码**（§2 清单），未进 `RankTrendConfig`、未进优化搜索空间、未接入交易决策。
2. 问题：阈值无法回测调参；`synergy.signalTier` 作为"四维信号合并产生的最终买卖信号"尚未进入 `TradeSimulator` 的买卖规则；档位规则有效性（S>A>B>C 收益单调性）从未被验证。
3. 目标（用户已确认）：
   - **观察回测 + 接入交易**：既验证档位→未来收益单调性，又把 `synergy.signalTier` 接入买卖决策；
   - **单调性为约束 + 交易收益为目标**：搜索主目标用风险调整后收益，档位单调性作硬性验收约束；
   - 全部阈值参数化进 `RankTrendConfig`，默认值 = 当前硬编码值（golden 不漂移）。
4. 约束：不改动现有输出合同的已有字段语义；`signalTier` 在 API 单股链路**已生产**（§2.1），对**回测 replay 链路**而言为新增字段（§2.3）；不引入新数据源。

## 2. 现状还原（关键行号基于当前代码）

### 2.1 五维 signalTier 生产位置与硬编码阈值

> 行号已按 2026-08-15 代码核对更新；**全部硬编码阈值均已参数化进 `RankTrendConfig`（§3.1，engine.py:130-138）**，下表"硬编码阈值"为参数化前的原始值。

| 维度 | 函数 | 位置（当前） | 硬编码阈值（拍脑袋，现已参数化） |
|---|---|---|---|
| 共振 | `_resonance_tier` | `engine.py:1260` | `reversalPenalty≥0.6`、`jumpFreshness≥0.5`、`persistence≥0.6` |
| 共振（新入榜） | `analyze_rank_resonance` 内联 | `engine.py:1309`（A 判定 L1341） | `entryStrength≥0.3`（A）、`jumpFreshness≥0.5 and entryStrength>0`（S） |
| 趋势 | `_rank_trend_tier` | `engine.py:1082` | `\|combinedScore\|≥0.5`（S）、`≥0.25`（A） |
| 量价 | `_volume_price_tier` | `volume_price.py:109` | 关键词/象限状态机（无数值阈值，见 §2.2） |
| 周期 | `_lifecycle_tier` | `engine.py:1097` | stage/action 状态机（无数值阈值，见 §2.2） |
| 四维合并 | `_synergy_tier` | `volume_price.py:240`（组装下沉后由 routes 移入） | 前置硬分支：`lc_tier==E`→E（周期否决）、`vp_tier==E`→D（量价出货）；否则投票：`vote_sum≥2 且 lc_tier==A`→S、`≥2`→A、`==1`→B、`≤−1`→D、其余→C；周期 B/D 时 S/A 降档 |

### 2.2 量价/周期的"非数值阈值"说明

- **量价**：档位由 `reasons` 关键词（"对倒出货"/"过度放量"/"缩量涨停"）与 `quadrant`（rise_volume/rise_shrink/fall_volume/fall_shrink/normal）状态机决定，无连续阈值。其**底层判定阈值**（`volumePriceOverVolumeRatio=2.5`、`volumePriceAbnormalFundRatio=20.0`、`volumePriceShrinkRatio=0.95`、`volumePriceMildRatio=1.05`）**已进 `RankTrendConfig`**（`engine.py:88-91`），可随 config 参与回测。
- **周期**：档位由 `stage`/`action` 状态机决定，无连续阈值；底层生命周期判定阈值（`lifecycleVelocityMin` 等）已进 config。周期档位本身不参与数值搜索，但其 `stage` 输出受已 config 化的底层参数影响。
- 结论：**数值搜索只针对共振/趋势/合并三组的档位阈值**；量价/周期档位阈值作为状态机逻辑保持现状，其底层参数已可搜索。

### 2.3 回测链路缺口（关键发现）

> 以下三项缺口均为方案撰写时点的现状，**已全部修复（2026-08-15 核对）**，标注修复位置：

1. ~~**replay 信号不含 volumePrice/synergy**~~ → **已修复**：组装下沉为 engine 层 `assemble_observation`（`volume_price.py:287`，`engine.py:1752-1754` 在 `_build_signal` 内调用；`_build_signal` 当前 `engine.py:1687`），`ranktrend_routes.py:384-385` 改为调用同一函数（原 API 层组装 `ranktrend_routes.py:384-409` 已删重复），replay 与单股 API 同源同构，`replay()` 输出已含 `synergy.signalTier`。
2. ~~**交易链路不消费 signalTier**~~ → **已修复**：`strategy.py` 旧 `_entry_signal`（`:343-364`）/`_exit_signal`（`:366-379`）已随交易引擎重构；synergy 门实现在 `execution.py`（入场过滤 L173-177、D/E 卖出门 L114/L1012，辅助函数 `_synergy_tier_of` L357、`_synergy_allowed_tiers` L362、`_synergy_exit_on_danger` L372）。
3. ~~**阈值未参数化**~~ → **已修复**：全部档位阈值进 `RankTrendConfig`（`engine.py:130-138`），`from_patch` 可覆盖（L141-159），并带约束校验 `_validate_tier_constraints`（L160），已进搜索空间（`search_space.py:44-56`）。

## 3. 前置改动（实现回测的前提，属于本方案实施范围）

### 3.1 阈值参数化：`RankTrendConfig` 新增字段（A 类可调）

> ✅ **已实现**：字段定义 `engine.py:130-138`，`from_patch` 覆盖与约束校验（`_validate_tier_constraints`，engine.py:160）。默认值 = 当前硬编码值，保证 golden 不漂移。前缀约定 `tier*`（与现有 `tierAMain*` 风格一致）：

| 字段名 | 默认值 | 消费位置 |
|---|---|---|
| `tierResonanceReversalPenaltyMin` | `0.6` | `_resonance_tier` 首条（reversal 否决） |
| `tierResonanceJumpFreshnessMin` | `0.5` | `_resonance_tier` 第二条（Jump 事件）+ 新入榜 S |
| `tierResonancePersistenceMin` | `0.6` | `_resonance_tier` 第三条（buy+persistence） |
| `tierResonanceEntryStrengthMin` | `0.3` | 新入榜 A 判定（`engine.py:1341`） |
| `tierRankTrendStrongMin` | `0.5` | `_rank_trend_tier` S |
| `tierRankTrendConfirmMin` | `0.25` | `_rank_trend_tier` A |
| `tierSynergyVoteStrong` | `2` | `_synergy_tier` vote_sum≥2（S/A 分界） |
| `tierSynergyVoteWeak` | `1` | `_synergy_tier` vote_sum==1（B） |
| `tierSynergyVoteReverse` | `-1` | `_synergy_tier` vote_sum≤−1（D） |

> 周期 B/D 时 S/A 降档为设计文档 §7 的**固定规则**，本轮不参数化（如需放开开关，另行走规则变更流程 + 回测验收）。

> 约束校验（`from_patch` 内）：`0 < tierRankTrendConfirmMin < tierRankTrendStrongMin <= 1`、`tierSynergyVoteReverse <= tierSynergyVoteWeak < tierSynergyVoteStrong`（weak **严格小于** strong，防止 `v==weak` 分支被 `v>=strong` 吞掉而不可达）、`0 <= tierResonance*Min <= 1`；不满足时 `from_patch` 抛错（回测 trial 记 failed，防止非法阈值污染）。

### 3.2 组装下沉：replay 信号含 synergy.signalTier

> ✅ **已实现**：`assemble_observation`（`volume_price.py:287`）由 `engine.py:1752-1754` 在 `_build_signal` 内调用；`_synergy_tier` 落在 `volume_price.py:240`；`ranktrend_routes.py:384-385` 改调用同一函数（API 层重复组装已删除）。replay 与单股 API 同源同构。

把 `ranktrend_routes.py:384-409`（撰写时点）的组装逻辑（`compute_volume_price_score` + `compute_synergy_state` + `_synergy_tier` + 写入 `observation`）下沉为 engine 层纯函数/方法，在 `_build_signal` 内对每个 signal 调用，使 `replay()` 输出与 API 单股链路**同源同构**：

- 新函数（engine.py 或 volume_price.py）：`assemble_observation(analysis, stock, config)` → 返回补全后的 `observation`（volumePrice/synergy + 各维 signalTier/tierReasons）。
- `_synergy_tier` 从 `ranktrend_routes.py` 移入 engine（或 volume_price.py），签名改为接收 `config`（读 `tierSynergy*`）。
- `ranktrend_routes.py` 改为调用 engine 的组装函数（**删除重复组装**，消除两处漂移风险）。
- 单股 API 与回测 replay 的输出合同对齐；`_analyze_frames` 的 `full_history` 轻量分支不受影响。

### 3.3 synergy 接入交易决策（可开关，防止默认行为漂移）

> ✅ **已实现**：买卖门实现在 `backend/core/backtest/execution.py`（入场过滤 L173-177、D/E 卖出门 L114/L1012；辅助 `_synergy_tier_of` L357 / `_synergy_allowed_tiers` L362 / `_synergy_exit_on_danger` L372）。两个开关为**纯交易层参数**（不在 `RankTrendConfig`，由 `to_trade_config` 透传进 trade_config），**默认关闭**（默认策略行为与现状一致，golden 回测不漂移）。

- 新增 config 字段（交易层，随搜索空间可调，见 §4.1）：
  - `synergyEntryTierMin: str = "none"`（`none`=不启用；`s`=仅 S；`a`=S/A 允许入场）
  - `synergyExitOnDanger: bool = False`（D/E 档强制卖出）
- 入场追加门：`synergy.signalTier ∈ 允许集合` 时才能 buy（`execution.py:177`，与现有 `finalSignal==buy` + `candidateTier` 条件**取交集**，不是替代）；
- 出场追加门：`synergy.signalTier in (D,E)` 且开启时 → sell（`execution.py:114`/`1012`，原因注明"四维合并档位 D/E"）。
- 说明：`synergy.signalTier` 读取路径 `signal.rankTrend.observation.synergy.signalTier`（§3.2 下沉后 replay 信号已含）。

> 设计取舍：**交集模式**（signalTier 只做过滤/门）而非"signalTier 替代 finalSignal"——保留现有 `decision.final` 交易语义，避免 golden 交易口径被整体替换；用户后续如需"档位直接决定买卖"可再加策略变体。

## 4. 搜索空间设计

### 4.1 新增搜索参数（追加进 `default_search_space()`）

```python
{
    # ── 共振档位阈值 ──
    "tierResonanceReversalPenaltyMin": [0.5, 0.6, 0.7],
    "tierResonanceJumpFreshnessMin": [0.4, 0.5, 0.6],
    "tierResonancePersistenceMin": [0.5, 0.6, 0.7],
    "tierResonanceEntryStrengthMin": [0.2, 0.3, 0.4],
    # ── 趋势档位阈值 ──
    "tierRankTrendStrongMin": [0.4, 0.5, 0.6],
    "tierRankTrendConfirmMin": [0.2, 0.25, 0.3],
    # ── 四维合并投票阈值（from_patch 强校验 weak < strong，
    #    有效组合 (weak, strong) ∈ {(1,2),(1,3),(2,3)}；strong=3 时 v==2 既不满足 S/A 也不满足 B/D，按规则落 C，属上调强买门槛后的预期语义）──
    "tierSynergyVoteStrong": [2, 3],
    "tierSynergyVoteWeak": [1],  # 固定默认值：避免笛卡尔积产生 weak==strong 必死组合（from_patch 强校验 weak < strong）
    "tierSynergyVoteReverse": [-1, 0],
    # ── 交易接入开关 ──
    "synergyEntryTierMin": ["none", "a"],   # 先扫 none(基线) vs a(S/A 入场)，s 单独验证
    "synergyExitOnDanger": [False, True],
}
```

> 白名单（已核对，与实现一致）：`_STRATEGY_SCALAR_KEYS`（`search_space.py:257-261`）按 `isinstance(f.default, (int, float, bool))` 从 `RankTrendConfig` 字段自动生成。**`synergyEntryTierMin`/`synergyExitOnDanger` 是交易层参数（不在 `RankTrendConfig`）**，天然不进 `_STRATEGY_PARAM_KEYS`（`search_space.py:270`）→ `to_trade_config` 对它们**透传保留**，正好进入 `trade_config` 供 `execution.py`（§3.3）读取，**这是期望行为，不要追加进 `_STRATEGY_PARAM_KEYS`**；若误追加，`to_trade_config` 会将其 pop，交易门将永远读不到而失效（`search_space.py:54` 注释已明确"交易层参数，to_trade_config 透传"）。

### 4.2 组合规模与搜索方法

- 全空间名义规模：3⁶ × 2 × 1 × 2 × 2 × 2 = **11664**（vote 三元组已收敛 `weak=[1]`，8 种笛卡尔组合中 `weak==strong` 的 2 种必死组合被剔除，剩余组合全部通过 `from_patch` 强校验，无 trial 浪费），grid 仍不可行，推荐 optuna。
- 分阶段搜索（推荐，控制成本）：
  - **Phase A 单维敏感性**：固定其它为默认值，每次只扫 1 个参数 3 候选值 → 11 组 × 3 = 33 次 trial，产出每参数的敏感性报告（参数值 → 单调性/收益），识别高敏感与冗余参数。
  - **Phase B 联合搜索**：Phase A 剔除冗余参数后，用 optuna（`method: "optuna_tpe"`）联合搜索剩余参数，`max_trials` 200-500。
  - **Phase C 交互确认**：`synergyEntryTierMin`/`synergyExitOnDanger` 只做 2-4 组合离散扫描（因为开关影响交易结构，不适合连续采样），与 Phase B 最优阈值组合交叉验证。
- 数据：历史快照，`snapshot_type=half_hour`（默认口径），dataset 选取 ≥2 周交易日样本；train/validation 按 `split_frames`（`validation_mode: "chronological"`、ratio 0.3、warmup 40 帧）。

## 5. 目标函数设计（单调性约束 + 交易收益）

### 5.1 新增档位单调性统计模块（观察回测）

> ✅ **已实现**：新文件 `backend/analysis/ranktrend/tier_monotonicity.py`（纯函数，analysis 层）。

新文件 `backend/analysis/ranktrend/tier_monotonicity.py`（纯函数，就近放 analysis 层）：

```python
def tier_forward_returns(
    signals: list[dict], frames: list[dict],
    horizon: int = 3,          # 未来 N 帧（1/3/8 对应短/中/长）
) -> dict[str, Any]:
    """按 signalTier 分层统计未来 horizon 帧的相对排名收益均值/方向精度/样本数。"""

def tier_monotonicity_score(stats: dict[str, Any]) -> dict[str, Any]:
    """单调性得分与硬约束判定。"""
```

输出结构（每档位 + 合计）：

```json
{
  "horizon": 3,
  "tiers": {
    "S": {"count": 35, "meanFutureReturn": 0.021, "directionAccuracy": 0.66},
    "A": {"count": 120, "meanFutureReturn": 0.012, "directionAccuracy": 0.58},
    "B": {"count": 180, "meanFutureReturn": 0.004, "directionAccuracy": 0.51},
    "C": {"count": 400, "meanFutureReturn": -0.002, "directionAccuracy": 0.47},
    "D": {"count": 90, "meanFutureReturn": -0.015, "directionAccuracy": 0.38},
    "E": {"count": 12, "meanFutureReturn": -0.02, "directionAccuracy": 0.4},
    "unknown": {"count": 8, "meanFutureReturn": null, "directionAccuracy": null}
  },
  "monotonicity": {
    "spearmanRankCorr": 0.92,      # 档位序(S>A>B>C)与收益序的 Spearman 相关
    "reversals": [],               # 反转档位对（如 B 收益 > A）
    "passHardConstraint": true
  }
}
```

- 收益口径：该股该帧 signalTier 在**未来 N 帧**的 `relative rank return`（相对排名变化或相对收益，与设计文档 §9 一致）；directionAccuracy = buy 类档位（S/A/B）中实际上涨比例。
- `unknown` 档：不参与单调性计算，但计入占比（验收：`unknown` 占比 < 5%）。

### 5.2 objective 扩展：`tier_risk_adjusted`

> ✅ **已实现**：`backend/optimization/objective.py`（`score` L14、`tier_risk_adjusted` 分支 L33-40、`tier_penalty` L45、`score_trial` L71；phase 分数注入 tierStats L130-132）。

在 `backend/optimization/objective.py` 增加 objective 名（不经 `objective_for_phase` 改写）：

```python
def score(result, objective, request):   # 现有签名扩展 request
    if objective == "tier_risk_adjusted":
        base = risk_adjusted(result)          # totalReturn - drawdown*1.5 + sharpe*0.02
        tier_stats = result.get("tierStats")  # 由 trial 注入（见 §5.3）
        penalty = 0.0
        if tier_stats and tier_stats["monotonicity"]["passHardConstraint"] is False:
            penalty += 0.5                    # 硬约束违约重罚
        if tier_stats and tier_stats["tiers"].get("S", {}).get("count", 0) < 30:
            penalty += 0.2                    # S 样本不足
        unknown_rate = tier_stats["unknownRate"]  # unknown 占比
        if unknown_rate >= 0.05:
            penalty += unknown_rate * 1.0
        return base - penalty
```

- `score_trial`（`objective.py:71`）签名不变，`request` 已传入；`tierStats` 由 trial 评估时注入 `train_eval`/`validation_eval` 结果（见 §5.3）。
- **硬约束**（设计文档 §9 验收标准，任一不满足则整 trial 标记 `tierConstraintFailed=true`，可入选但显著降分并在报告突出）：
  1. S 档样本数 ≥ 30 且 S>A>B>C 收益单调不反转（Spearman>0 且无相邻反转）；
  2. D/E 档收益显著低于 C（D 或 E 的 meanFutureReturn < C 的 −0.005）；
  3. S/A 档方向精度 ≥ 60%（S/A 合并口径）；
  4. unknown 占比 < 5%。

### 5.3 trial 接入（`trial.py` 改动）

> ✅ **已实现**：phase 评估后对 `phase_signals` 调 `tier_forward_returns` 写入 `metrics["tierStats"]`；`score_trial` 合并 train/validation 的 tierStats 计算（`objective.py:130-132` 注入）。

- `TrialExecutor.evaluate_phase`：`replay` 后对 `phase_signals` 调 `tier_forward_returns(signals, phase_frames, horizon)`（horizon 用 request 的 `tier_horizon`，默认 3），结果写入 `metrics["tierStats"]` 与 `phase_eval`。
- `objective.score_trial` 读取 `train_eval["metrics"]["tierStats"]` / validation 同，合并后按 §5.2 计算。
- `trial` 结果增加 `tierMonotonicity` 摘要（train/validation 各一份），便于报告与排序解释。

## 6. 回测流程

```
历史快照 frames（half_hour，≥2 周交易日，含 change/volumeRatio/zlje/zljzb 字段）
  → split_frames（chronological，ratio 0.3，warmup 40）
  → 每 trial：
      RankTrendConfig.from_patch({**base_strategy_config, **to_strategy_config(params)})
      → engine.replay(signal_frames)          # §3.2 下沉后信号含 synergy.signalTier
      → TradeSimulator().run(phase_frames, phase_signals, trade_config)   # §3.3 门生效
      → tier_forward_returns(...)             # 单调性统计
      → objective.score_trial(...)            # tier_risk_adjusted
  → grid/random/optuna 搜索（§4.2 分阶段）
  → walk-forward 复核 top trials（样本外单调性 + 收益）
  → 报告落 quant-board/data/reports/（敏感性报告 + 最优参数 + 单调性/收益对照表）
```

**基线对照**：始终包含一个 `synergyEntryTierMin="none"` 且所有 tier 阈值为默认值的 trial（即现状参数组合）作为基线，搜索结果必须**显著优于基线**（risk_adjusted 提升且单调性达标）才采纳，防止"参数搜索制造过拟合收益"。

## 7. 验收标准

| 阶段 | 内容 | 验收命令/标准 | 落地状态 |
|---|---|---|---|
| 1 | 阈值参数化 + 组装下沉 + 交易接入（默认关闭） | `cd quant-board; .\.venv\Scripts\python.exe -m pytest` 全绿；**golden case 全绿**（`tests/test_ranktrend_golden_alignment.py`，默认 config 行为不变） | ✅ 已完成 |
| 2 | 单测：每档每阈值至少 1 输入样例 + 边界（等于阈值/略低于）+ 非法阈值 from_patch 报错 | pytest 新增用例全绿 | ✅ 已完成 |
| 3 | 单调性模块单测：构造已知档位收益序列，验证 Spearman/硬约束判定 | pytest 新增用例全绿 | ✅ 已完成 |
| 4 | objective `tier_risk_adjusted` 单测：硬约束违约/unknown 占比/样本不足惩罚生效 | pytest 新增用例全绿 | ✅ 已完成 |
| 5 | 回测运行（Phase A/B/C） | 产出 `quant-board/data/reports/` 敏感性报告 + 最优参数报告，满足 §5.2 硬约束且优于基线 | ⏳ 待办（后续长期回测计划） |
| 6 | 参数采纳后：更新 golden case + 提升 `ranktrend_version`/`strategy_version` | 按 `ranktrend-golden.md` 第 6 节变更管理；历史回测不覆盖 | ⏳ 待办 |
| 7 | 文档同步 | `ranktrend-golden.md` 配置节 + 输出合同节 + `backtest-policy.md` + `architecture.md` | ⏳ 待办（golden 已补档位字段说明，其余随参数采纳同步） |

## 验收口径声明（2026-09-06，WP3.1）

- **h1 降级为诊断口径**（本征尺度）：h1 帧间噪音敏感度过高，不再作为策略/门控验收的唯一依据。
- **策略/门控验收口径 = h4/h8（日内多档）+ 持有到收盘（hold-to-close）**：
  - h4/h8：`tier_forward_returns(horizon=4/8)` 与 `OutcomeEvaluator.evaluate(horizons=[1,3,5,10])` 并行输出。
  - hold-to-close：`OutcomeEvaluator.evaluate(..., include_hold_to_close=True)`，entry 帧 → 同 tradingDate 尾帧强制出场。
- **成本敏感性**：近盈亏平衡结论（four_dim pf 1.0377，lifecycle-layer-rearchitecture §7）引用前必须附
  `diagnose_cost_sensitivity` 弹性表；`fallbackSlippageRate` 自本声明起显式定值 0.001
  （此前运行时默认 0，快照退化成交未计罚金——口径切换点，历史数字不回改）。
- 8 月冻结纪律适用：口径切换不重算历史结论，仅声明切换点与新旧口径映射。

## 8. 实施步骤（建议顺序，均为小步可回退）

1. ✅ **RankTrendConfig 扩展**：新增 §3.1 字段 + `from_patch` 约束校验；默认值=旧硬编码。pytest + golden 零漂移。
2. ✅ **档位函数接 config**：`_resonance_tier`/`_rank_trend_tier`/`_lifecycle_tier`/`_volume_price_tier` 接收 `RankTrendConfig` 读取 `tier*`；`_synergy_tier` 移入 `volume_price.py:240` 并读 config。pytest + golden。
3. ✅ **组装下沉**：新增 `assemble_observation`（`volume_price.py:287`），`_build_signal` 接入（`engine.py:1752-1754`）；`ranktrend_routes.py:384-385` 删重复组装改调用。pytest + golden（API 输出逐字段一致）。
4. ✅ **交易接入**：`execution.py` 增加 `synergyEntryTierMin`/`synergyExitOnDanger` 门（默认关闭）。pytest（含默认关闭回归）。
5. ✅ **单调性模块**：新建 `tier_monotonicity.py` + 单测。
6. ✅ **objective/trial 接入**：`tier_risk_adjusted` + tierStats 注入 + 单测。
7. ✅ **搜索空间**：§4.1 追加（`search_space.py:44-56`）；`synergyEntryTierMin`/`synergyExitOnDanger` 为交易层参数经 `to_trade_config` 透传（白名单核对见 §4.1 注）。`default_search_space()` 单测。
8. ⏳ **回测运行与校准**（Phase A/B/C），产出报告，按 §7 验收——纳入长期回测计划。
9. ⏳ **参数采纳 + golden 更新 + 文档同步**——随长期回测计划推进。

## 9. 风险与回退

- **默认行为漂移**：所有新字段默认值=旧硬编码；`synergyEntryTierMin` 默认 `"none"`、`synergyExitOnDanger` 默认 `False` → 交易链路行为不变。缓解：每阶段跑 golden 对比。
- **组装下沉导致 API 输出漂移**：`assemble_observation` 逻辑必须与 routes.py 现组装**逐字段一致**；阶段 3 验收含 API 输出字段级 diff（可加一条断言 observation 结构与下沉前一致的测试）。
- ~~**str 字段不进自动白名单**~~ → **已闭环**：`synergyEntryTierMin`/`synergyExitOnDanger` 是交易层参数（不在 `RankTrendConfig`），`to_trade_config` 对非策略白名单参数**透传保留**进 trade_config 供 `execution.py` 读取（§4.1 注）。曾担心的"漏加白名单导致参数丢失"经核对不存在——透传即期望行为。
- **单调性样本不足**：S 档/未知档样本可能 <30 或 unknown>5%，此时按 §5.2 惩罚并**不得据此采纳参数**（回到设计讨论），不以整体收益掩盖。
- **搜索过拟合**：train/validation 拆分 + walk-forward + 基线对照三重防线；参数采纳必须同时满足样本外单调性与收益提升。
- **量价/周期档位不参与数值搜索**：其底层参数（`volumePrice*`、`lifecycle*`）已在 config 可搜索；若需要改量价/周期档位的**离散映射**（如把 rise_shrink 从 C 改 B），属于规则语义变更，走离散档位设计文档的规则变更流程（单测 + 回测验收），不在本方案数值搜索范围内。
- **回退**：全部改动集中在 config 字段、档位函数取值与组装位置，`git revert` 即可恢复；无数据迁移、无 API 合同字段删除（signalTier 仍为可选新增）。

## 10. 变更管理

- 实现前在 `ranktrend-golden.md` 输出合同节补充 `observation.*.signalTier`/`tierReasons` 与 `resonance.signalTier` 字段说明（A 类可调参数入配置节）。
- `strategy_version` / `ranktrend_version` 提升遵循 `ranktrend-golden.md` 变更管理流程。
- 回测/前端口径变化同步检查 `backtest-policy.md` 与 `architecture.md`。
- 本方案为过程文档，**已落地并归档**到 `quant-board/docs/ranktrend-tier-backtest/` 专题目录（连同档位设计/参数抽取/四维列/jump 共振研究等四维信号方案文档）。
