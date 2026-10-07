# RankTrend 个股生命周期分层 · 推理语料包（2026-10-07 组装）

**用途**：投喂强推理模型（本轮主=GPT-OSS-120B 脚本通道，备=Claude Opus 4.x 手动投喂），对**个股生命周期分层算法**（5 态定义 + 状态机 + 决策层 + 门控消费）做深度归因与优化研讨。

**触发命题（用户 2026-10-07）**：生命周期分层的算法定义和算法，回测证明只能作为环境门，对 胜率×收益率 的贡献率几乎没有，而且从未优化过——投喂推理模型，看能否深入推理从而优化算法。

**语料组装时的命题修正（须随语料告知模型，防其基于错误前提推理）**：

- 「从未优化过」需精确化：
  1. **51 个阈值已参数化**（2026-08-16 commit `ba6e301`，默认值=原硬编码值）并做过**一次坐标下降搜索**（commit `ada4a27`，~20 次 replay）——**否定性结论**：best=baseline，A/B 档 excess 反转属「分位结构性差异，阈值不可调」（§4.1-E）；
  2. `lifecycle_decision` 的 **13 个输入阈值**在长测阶段 23 B 组扫过（逐档读数未入本语料，见 §7）；
  3. **门控干预形态**（否决/降档 hard→soft→off、剂量曲线）在阶段 24（2026-09-14）三轴扫描+Track 1 交易复核——结论：hard 全线为峰，软化在交易层 wrxpf −32% 被否决（§4.3-C）。
- **从未被做过的**：5 态定义本身、状态机转移结构、输入特征集、决策层语义的**结构级重设计**。这是本轮推理的真实空间。
- GPT-OSS 已知幻觉率高（crowding 审定 5 幻觉全弃先例，`jev-sentiment-questionset-review.md` §十六）→ 语料自包含 + 模型输出全部按「假设」处理，逐条人工核对后才可能进入验证。

**边界**：本包只做语料预处理，不改任何生产代码与判据；模型输出不构成改动授权；任何采纳的改动走正常流程（参数化 diff → replay/回测验证 → 用户裁决）。

---

## §0 任务卡（投喂开场，粘给模型）

你是量化交易系统评审专家。下面是一套 A 股短线系统里「个股生命周期分层」算法的完整语料（代码逐字 + 全部已知实证 + 历史裁决）。它目前的角色是**环境门**（风险否决/降档），多轮回测证明它对方向信号（胜率×收益率）几乎没有正向贡献。你的任务：

1. **归因诊断**：为什么 5 态分层对方向几乎没有贡献？按固定顺序归因并排序：
   ①**原料/输入**（它只吃注意力排名序列——是输入本身无方向信息，还是有用原料没喂进去？）
   → ②**定义/判据设计**（5 态划分、阈值、状态机滞回、决策层语义）
   → ③**下游消费形态**（档位映射、门控形态、伪方向序）
   → 最后才是 ④**整体重设计**。
   每条归因必须引用语料证据（§编号），禁止无证据断言。
2. **优化提案 ≤5 条**，分级给出：
   - **L1 参数/阈值级**（现有 replay harness 即可验证）——注意 §4.1-E 已证伪「单纯调 raw_stage 阈值」，若你仍提阈值级提案，必须说明为何能绕开「分位结构性差异」根因，否则不要提；
   - **L2 结构级**（特征增删 / 状态机改造 / 决策层语义调整——需预登记 + 专项 harness）；
   - **L3 重设计级**（换状态轴、换分层本体——需先立项论证，只给论证不给实现）。
   每条提案必须包含：具体改法（伪代码或伪判据）、预期改变 §4 中哪些历史读数、验证设计（窗口/样本量/判定线）、失效风险与回退方式、**为什么它不在 §4.3 已证伪清单里**。
3. **反面检查**：显式列出你认为语料证据不足、内部矛盾、或需要先补数据/读代码才能判断的点（没有就写「无」）。

**反幻觉铁律**：
- 只允许使用本语料推理；引用结论必须标注 §编号；
- 禁止编造字段名、数字、外部文献、本语料没有的代码；不确定就写「未知/证据不足」；
- 若你认为语料内部自相矛盾，显式指出（会被逐条人工核对，抓出真矛盾有额外价值）；
- 禁止朝已知结论拟合：优化目标是「结构信号区分度 + 门控效率」，不是「把某个历史读数调好看」；
- 市况依赖是本系统多次复现的教训（§4.4）：任何提案必须回答「它在强情绪期和退潮期分别会怎样」。

---

## §1 系统与数据上下文

| 项 | 事实 |
|---|---|
| 引擎 | QuantBoard Python RankTrend 引擎（`quant-board/backend/analysis/ranktrend/`，golden 生产事实标准）；TS 前端有同构实现，本语料只给 Python 侧 |
| 数据 | 盘中快照帧，`snapshot_type=half_hour`（每交易日约 10 帧，09:30–15:00 每半小时）；回测数据集 `dragonboard_live` |
| 池规模 | 热榜池每帧 ≈200 只（769 帧 / 156,647 信号 ≈ 204 只/帧） |
| 证据窗口 | decision 2026-04-15~07-31 / oos1 08-15~08-31 / oos2 09-01~09-12（三窗是本系统既有锚体系） |
| 生命周期角色 | **环境门**（+设计文档称「投票输入」，但**代码事实：`_synergy_tier` 票和=res+rank+vp+cs+pm+dv，无 lifecycle 加性正票项**——lifecycle 以门控修正参与：E 否决/B·D 降档，均负向语义。用户已裁决：不恢复硬买卖标签）；另有一个**市场级**环境门（`market_regime` 读热榜情绪 stage 高潮/发酵/启动/退潮/冰点）与本个股级门正交，勿混 |
| 词表 | 路径 5 态：`ignition`(点火)/`expansion`(扩散)/`crowded`(拥挤)/`reversal`(反转)/`cooling`(冷却)；候选分层：A_MAIN/B_IGNITION/C_CROWDED/D_EXIT_RISK/N_NEUTRAL；lifecycle signalTier：A/B/C/D/E（无 S） |

### §1.1 输入序列构造（生命周期唯一的原料）

每帧对每只股票：取该股在**当帧热榜**里的注意力排名 `rank` 与其百分位 `percentile`，滚动最近 **50 帧**（`window_size=50` 默认）拼成两条序列 `ranks[]` / `percentiles[]` 喂给生命周期分析。**关键实现原文**（`engine/primitives.py:64`）：

```python
def percentile_rank(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100
```

排名来自（`engine/primitives.py:70`，注意 docstring 最后一句）：

```python
def attention_rank_lookup(stocks: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    """旧 TS attention 口径：趋势核心因子是 avgRankNum 均榜百分位重排后的序号。

    过滤 avgRankNum > 0，按 (avgRankNum, code) 升序重排；综合排名只决定池子大小
    （哪些股票进池），不参与趋势百分位计算。
    """
    valid: list[tuple[str, float]] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        if not code:
            continue
        avg = stock.get("avgRankNum")
        try:
            avg = float(avg)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(avg) or avg <= 0:
            continue
        valid.append((code, avg))
    valid.sort(key=lambda item: (item[1], item[0]))
    return {code: index + 1 for index, (code, _avg) in enumerate(valid)}, len(valid)
```

序列拼装（`engine/runtime.py:1074` 摘录）：

```python
for offset, historical in enumerate(history):
    ...
    attention_ranks, attention_total = attention_rank_lookup(historical.get("stocks") or [])
    rank = attention_ranks.get(code)
    if rank is None:
        continue
    ranks.append(rank)
    percentiles.append(percentile_rank(rank, attention_total))
```

**输入语义要点（推理必读）**：

1. `percentile` 方向：100 = 榜单第 1 名；`percentile≥88` ⇔ 名次进入全池前 ~12%（池 200 时约前 25 名）；`rank≤10` 是绝对名次口径。**热区判定 = `rank <= 10 or percentile >= 88`（两个口径 OR）**。
2. **缺帧直接跳过、不插值**：股票若干帧不在热榜（出入池），序列在时间上不规则——`velocity`（相邻序列元素之差）可能跨交易日比较。这是已知结构特性（回池 gap 有专项研究 P_repool_timeline_gap，结论：中期扫描 floor3 方向性支持 insufficient 14.2%→8.3%）。
3. **池总规模 total 逐帧时变**：`percentile` 是相对量，`rank` 是绝对量——算法里两种口径混用（见 §2.2）。
4. 回测/replay 链路序列末项就是当帧真值；live 链路有「权威 pct 复制尾」差异（对回测证据无影响）。
5. **同一 `_replay_stock` 里其实已经收集了 `price_changes`、`amount_history`（个股涨跌幅与成交额序列），但 cycle（生命周期）一个都没吃**——它的全部原料就是 `ranks[]`/`percentiles[]` 两条序列。

---

## §2 算法定义（源码逐字）

> 全部源码来自 `backend/analysis/ranktrend/trend/lifecycle.py`、`trend/technical.py`（辅助量）、`engine/runtime.py`（组装），与 `engine/config.py` 默认值。逐字引用（个别长行因排版折行/合并，逐 token 语义未动；`lifecycle_decision` 末尾 `evidence` 字典有排版压缩，键值未动）。

### §2.1 导出量（metrics，全部只由 ranks/percentiles 尾窗计算）

`cycle_metrics_window`（`lifecycle.py:47`，取尾部 ≤8 帧）：

```python
def cycle_metrics_window(rank_window: list[float], percentile_window: list[float]) -> dict[str, Any]:
    current_rank = rank_window[-1] if rank_window else 999
    hot_streak = 0
    for rank, percentile in zip(reversed(rank_window), reversed(percentile_window)):
        if rank <= 10 or percentile >= 88:
            hot_streak += 1
        else:
            break
    best = min(rank_window) if rank_window else current_rank
    count = len(percentile_window)
    velocity = percentile_window[-1] - percentile_window[-2] if count >= 2 else 0
    previous_velocity = percentile_window[-2] - percentile_window[-3] if count >= 3 else 0
    return {
        "rankVelocity": velocity,
        "rankAcceleration": velocity - previous_velocity,
        "rankShock": cycle_rank_shock(percentile_window),
        "hotZoneStreak": hot_streak,
        "bestRecentRank": best,
        "drawdownFromPeak": max(0, current_rank - best),
        "rankPathCommitment": rank_path_commitment(percentile_window),
    }
```

`cycle_rank_shock`（`technical.py:174`，末位速度对末 5 个速度差的 z 分数，不截断）：

```python
def cycle_rank_shock(percentiles: list[float]) -> float:
    count = len(percentiles)
    if count < 6:
        return 0.0
    recent = [percentiles[j] - percentiles[j - 1] for j in range(count - 5, count)]
    current = recent[-1]
    mean = average(recent)
    variance = average([(value - mean) ** 2 for value in recent])
    std = math.sqrt(variance)
    return 0.0 if not math.isfinite(std) or std < 1e-6 else (current - mean) / std
```

`rank_path_commitment`（`technical.py:188`，承接度 ∈[0,1]）：

```python
def rank_path_commitment(percentiles: list[float]) -> float:
    if len(percentiles) < 4:
        return 0.5
    window = percentiles[-8:]
    total_improvement = max(0.0, window[-1] - window[0])
    if total_improvement <= 0:
        return 0.0
    steps = [window[index] - window[index - 1] for index in range(1, len(window))]
    positive_steps = [step for step in steps if step > 0]
    last_step = max(0.0, steps[-1] if steps else 0.0)
    pre_breakout_improvement = sum(positive_steps[:-1])
    positive_step_share = len(positive_steps) / max(1, len(steps))
    pre_breakout_share = pre_breakout_improvement / max(total_improvement, 1)
    last_step_dominance = last_step / max(total_improvement, 1)
    return clamp(
        positive_step_share * 0.45 + pre_breakout_share * 0.45 + (1 - last_step_dominance) * 0.1,
        0,
        1,
    )
```

**单位注意**：`velocity/acceleration/shock` 是**百分位点**单位；`bestRecentRank/drawdownFromPeak/hotZoneStreak` 是**绝对名次**单位（drawdown=从近 8 帧最好名次退步的格数）——同一算法内两套口径混用，且名次类阈值对池规模时变敏感。

### §2.2 raw_stage —— 5 态初判（`lifecycle.py:77`）

```python
def raw_stage(
    history_length: int, current_percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> str:
    """5 态初判（阈值数据驱动优化设计 2026-08-16：全部阈值参数化，默认值=原硬编码，零行为变化）。"""
    c = config or RankTrendConfig()
    if history_length < 2:
        return "cooling"
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    warm = current_percentile >= c.cycleRawWarmPercentileMin or best <= c.cycleRawWarmBestRankMax
    hot_zone = current_percentile >= c.cycleRawHotZonePercentileMin or best <= c.cycleRawHotZoneBestRankMax
    recovery = velocity > c.cycleRawRecoveryVelocityMin and accel >= c.cycleRawRecoveryAccelMin and (
        current_percentile >= c.cycleRawRecoveryPercentileMin or best <= c.cycleRawRecoveryBestRankMax or hot >= c.cycleRawRecoveryHotMin
    )
    expansion = velocity > c.cycleRawRecoveryVelocityMin and current_percentile >= c.cycleRawExpansionPercentileMin and (
        accel >= c.cycleRawExpansionAccelMin or hot >= c.cycleRawExpansionHotMin or best <= c.cycleRawExpansionBestRankMax
    )
    crowded = hot_zone and (hot >= c.cycleRawCrowdedHotMin or best <= c.cycleRawCrowdedBestRankMax) and (
        drawdown <= c.cycleRawCrowdedDrawdownMax and (velocity <= c.cycleRawCrowdedVelocityMax or accel < 0)
    )
    reversal = warm and drawdown >= c.cycleRawReversalDrawdownMin and (
        velocity < 0 or accel < c.cycleRawReversalAccelMax
    ) and (hot >= c.cycleRawReversalHotMin or best <= c.cycleRawReversalBestRankMax)
    if reversal:
        return "reversal"
    if crowded:
        return "crowded"
    if expansion and warm:
        return "expansion"
    if recovery:
        return "ignition"
    return "cooling"
```

判级顺序：reversal > crowded > expansion > ignition > cooling（自上而下短路）。

### §2.3 normalize_stage —— 状态机平滑（`lifecycle.py:114`）

```python
def normalize_stage(
    previous: str | None, raw: str, current_percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> str:
    """状态机平滑（阈值参数化，默认值=原硬编码，零行为变化）。"""
    c = config or RankTrendConfig()
    if not previous:
        return raw
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    recovery = velocity > c.cycleRawRecoveryVelocityMin and accel >= c.cycleRawRecoveryAccelMin and (
        current_percentile >= c.cycleRawRecoveryPercentileMin or best <= c.cycleRawRecoveryBestRankMax or hot >= c.cycleRawRecoveryHotMin
    )
    weakening = velocity < 0 or accel < c.cycleNormWeakeningAccelMax or drawdown >= 2
    severe = velocity < -1 or accel < c.cycleNormSevereAccelMax or drawdown >= c.cycleNormSevereDrawdownMin
    cooling_ready = current_percentile < c.cycleNormCoolingReadyPercentileMax or hot <= 1
    crowded_carry = current_percentile >= c.cycleNormCrowdedCarryPercentileMin or best <= c.cycleNormCrowdedCarryBestRankMax or hot >= 2
    if previous == "ignition":
        if raw in ("expansion", "crowded"):
            return "expansion"
        if raw in ("reversal", "cooling"):
            return "cooling" if weakening else "ignition"
        return "ignition"
    if previous == "expansion":
        if raw == "crowded":
            return "crowded"
        if raw == "reversal":
            return "crowded" if crowded_carry and not severe else "reversal" if severe or weakening else "crowded"
        if raw == "cooling":
            return "reversal" if severe or weakening else "expansion"
        return "expansion"
    if previous == "crowded":
        if raw == "reversal":
            return "reversal"
        if raw == "cooling":
            return "cooling" if cooling_ready else "reversal"
        if raw in ("expansion", "ignition"):
            return "reversal" if weakening else "crowded"
        return "crowded"
    if previous == "reversal":
        if raw in ("cooling", "reversal"):
            return raw
        return "cooling" if recovery else "reversal"
    if previous == "cooling":
        if raw in ("cooling", "reversal") or not recovery:
            return "cooling"
        if raw == "expansion" and current_percentile < 72 and hot == 0:
            return "ignition"
        if raw == "crowded":
            return "expansion"
        return raw
    return raw
```

**注意**：`cooling→ignition` 分支里的 `current_percentile < 72` 和 `severe` 分支里的 `velocity < -1`、`weakening` 的 `drawdown >= 2` 是**残留硬编码字面量**（不在 51 个参数化字段内，见 §2.7 表末「残留硬编码」行）。

### §2.4 cycle_confidence —— 阶段置信度（`lifecycle.py:170`）

```python
def cycle_confidence(
    stage: str, percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> float:
    """阶段置信度（阈值参数化，默认值=原硬编码，零行为变化；每态区域/动量/持续性/回撤阈值）。"""
    c = config or RankTrendConfig()
    velocity = metrics.get("rankVelocity", 0)
    accel = metrics.get("rankAcceleration", 0)
    hot = metrics.get("hotZoneStreak", 0)
    best = metrics.get("bestRecentRank", 999)
    drawdown = metrics.get("drawdownFromPeak", 0)
    if stage == "cooling":
        region = percentile < c.cycleConfCoolingRegionPctMax
        momentum = velocity <= 0 or percentile < c.cycleConfCoolingMomentumPctMax
        persistence = hot <= c.cycleConfCoolingPersistenceHotMax
        draw = drawdown <= c.cycleConfCoolingDrawdownMax or percentile < c.cycleConfCoolingRegionPctMax
    elif stage == "ignition":
        region = percentile >= c.cycleConfIgnitionRegionPctMin and percentile < c.cycleConfIgnitionRegionPctMax
        momentum = velocity > 0 and accel >= c.cycleConfIgnitionMomentumAccelMin
        persistence = hot <= c.cycleConfIgnitionPersistenceHotMax
        draw = drawdown == 0
    elif stage == "expansion":
        region = percentile >= c.cycleConfExpansionRegionPctMin
        momentum = velocity > 0 and accel >= c.cycleConfExpansionMomentumAccelMin
        persistence = hot <= c.cycleConfExpansionPersistenceHotMax
        draw = drawdown <= c.cycleConfExpansionDrawdownMax
    elif stage == "crowded":
        region = percentile >= c.cycleConfCrowdedRegionPctMin or best <= c.cycleConfCrowdedRegionBestMax
        momentum = percentile >= c.cycleConfCrowdedMomentumPctMin and (velocity <= 0 or hot >= c.cycleConfCrowdedMomentumHotMin)
        persistence = hot >= c.cycleConfCrowdedPersistenceHotMin
        draw = drawdown <= c.cycleConfCrowdedDrawdownMax
    else:  # reversal
        region = percentile >= c.cycleConfReversalRegionPctMin or best <= c.cycleConfReversalRegionBestMax
        momentum = velocity <= 0 or accel < -1
        persistence = hot >= c.cycleConfReversalPersistenceHotMin or best <= c.cycleConfReversalPersistenceBestMax
        draw = drawdown >= c.cycleConfReversalDrawdownMin
    return clamp(50 + int(region) * 10 + int(momentum) * 10 + int(persistence) * 10 + int(draw) * 10, 50, 90)
```

### §2.5 决策层：entry_advice + lifecycle_decision（`lifecycle.py:208-321`）

```python
def entry_advice(stage: str, transition: str) -> dict[str, Any]:
    if transition in ("cooling->ignition", "ignition->expansion"):
        bias = "preferred"
    elif stage == "reversal":
        bias = "blocked"
    elif stage in ("cooling", "crowded"):
        bias = "avoid"
    else:
        bias = "watch"
    reasons = {
        "preferred": "处于优选阶段路径，可作为情绪周期主观察对象。",
        "watch": "处于可跟踪阶段，但还不是优选出手路径。",
        "avoid": "处于冷却或拥挤阶段，宜观察不宜积极出手。",
        "blocked": "处于反转阶段，应优先回避。",
    }
    return {"bias": bias, "allowed": bias == "preferred", "reason": reasons[bias]}


def lifecycle_decision(
    raw: str,
    stage: str,
    transition: str,
    confidence: float,
    metrics: dict[str, Any],
    risk: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    c = config or RankTrendConfig()
    reasons: list[str] = []
    action = "caution"
    risk = risk or {}
    divergence = risk.get("divergence") if isinstance(risk.get("divergence"), dict) else {}
    overheat = risk.get("overheat") if isinstance(risk.get("overheat"), dict) else {}
    risk_pressure = float(risk.get("pressure") or 0)
    divergence_severity = float(divergence.get("severity") or 0)
    overheat_severity = float(overheat.get("severity") or 0)
    discovery_reasons: list[str] = []
    high_risk_conflict = risk_pressure >= c.lifecycleHighRiskPressureMin or (divergence_severity >= c.lifecycleHighRiskDivergenceMin and overheat_severity >= c.lifecycleHighRiskOverheatMin)
    rank_path = float(metrics.get("rankPathCommitment", 0.5))
    momentum = momentum if isinstance(momentum, dict) else {}
    momentum_short = float(momentum.get("short") or 0)
    momentum_mid = float(momentum.get("mid") or 0)
    momentum_long = float(momentum.get("long") or 0)
    momentum_acceleration = float(momentum.get("acceleration") or 0)
    mid_long_committed = momentum_mid >= c.lifecycleMidLongCommitmentMin and momentum_long >= c.lifecycleMidLongCommitmentMin and momentum_acceleration >= c.lifecycleAccelCommitmentMin
    weak_path_commitment = (
        rank_path < c.lifecycleWeakPathCommitmentMax
        and float(metrics.get("rankVelocity") or 0) > c.lifecycleVelocityMin
        and float(metrics.get("rankAcceleration") or 0) > c.lifecycleAccelMin
        and not mid_long_committed
        and stage in ("ignition", "expansion")
    )
    low_visibility_ignition = (
        stage == "ignition"
        and transition == "cooling->ignition"
        and int(metrics.get("hotZoneStreak") or 0) == 0
        and rank_path < c.lifecycleLowVisibilityPathMax
        and float(metrics.get("rankVelocity") or 0) > c.lifecycleVelocityMin
        and float(metrics.get("rankAcceleration") or 0) > c.lifecycleAccelMin
        and momentum_short >= c.lifecycleLowVisibilityMomentumMin
        and momentum_mid >= c.lifecycleLowVisibilityMomentumMin
        and momentum_acceleration >= c.lifecycleLowVisibilityMomentumMin
    )
    if stage == "reversal" or raw == "reversal":
        action = "veto"
        reasons.append("生命周期进入反转路径，辅助决策一票否决。")
    elif weak_path_commitment:
        action = "caution"
        reasons.append("生命周期B识别到最后一跳过强但整段承接不足，按假突破路径谨慎观察。")
    elif low_visibility_ignition:
        action = "caution"
        reasons.append("生命周期B识别到低可见度首段点火，承接尚未扩散，防止抢占后续高质量仓位。")
    elif high_risk_conflict and stage in ("ignition", "expansion"):
        action = "veto"
        reasons.append("生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。")
    elif stage == "crowded":
        action = "exit_watch"
        reasons.append("生命周期进入拥挤路径，持仓后应进入退出观察。")
    elif stage in ("ignition", "expansion"):
        action = "allow"
        reasons.append("生命周期处于点火或扩散路径，允许 RankTrend 主结构继续进入候选评估。")
    else:
        reasons.append("生命周期仍在冷却路径，辅助决策保持谨慎。")
    if "->" in transition:
        reasons.append(f"阶段路径：{transition}。")
    if stage in ("ignition", "expansion") and float(metrics.get("rankVelocity") or 0) > 0:
        discovery_reasons.append("生命周期存在漏选研究价值：点火/扩散路径仍在改善，但不得绕过 RankTrend 主结构直接制造买入。")
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "discovery": {"action": "research_watch" if discovery_reasons else "none", "reasons": discovery_reasons},
        "evidence": { "rawStage": raw, "stage": stage, "transition": transition,
            "rankVelocity": metrics.get("rankVelocity", 0), "rankAcceleration": metrics.get("rankAcceleration", 0),
            "drawdownFromPeak": metrics.get("drawdownFromPeak", 0), "hotZoneStreak": metrics.get("hotZoneStreak", 0),
            "rankPathCommitment": rank_path, "momentumShort": momentum_short, "momentumMid": momentum_mid,
            "momentumLong": momentum_long, "momentumAcceleration": momentum_acceleration,
            "riskPressure": risk_pressure, "divergenceSeverity": divergence_severity, "overheatSeverity": overheat_severity },
    }
```

决策动作 4 态：`veto`（一票否决）/ `caution`（谨慎，含 B 识别两条路径）/ `allow`（放行）/ `exit_watch`（退出观察）。`risk`/`momentum` 由 `analyze_cycle_with_risk`（`runtime.py:751`）注入——即**决策层是唯一能吃到风险与动量画像的层，5 态本体吃不到**。

### §2.6 主流程 analyze_cycle（`lifecycle.py:9`，逐帧滚动执行）

```python
def analyze_cycle(ranks: list[float], percentiles: list[float], config: RankTrendConfig | None = None) -> dict[str, Any]:
    previous_stage = None
    current_stage = None
    current_raw = None
    previous_normalized = None
    metrics = {}
    for index in range(len(percentiles)):
        window_start = index - 7 if index >= 7 else 0
        metrics = cycle_metrics_window(ranks[window_start : index + 1], percentiles[window_start : index + 1])
        raw = raw_stage(index + 1, percentiles[index], metrics, config=config)
        normalized = normalize_stage(current_stage, raw, percentiles[index], metrics, config=config)
        previous_stage = current_raw
        previous_normalized = current_stage
        current_raw = raw
        current_stage = normalized
    stage = current_stage or "cooling"
    raw = current_raw or "cooling"
    transition = stage if not previous_normalized or previous_normalized == stage else f"{previous_normalized}->{stage}"
    confidence = cycle_confidence(stage, percentiles[-1] if percentiles else 0, metrics, config=config)
    metric_values = metrics or {"rankVelocity": 0, "rankAcceleration": 0, "rankShock": 0, "hotZoneStreak": 0, "bestRecentRank": ranks[-1] if ranks else 999, "drawdownFromPeak": 0, "rankPathCommitment": 0.5}
    return {
        "rawStage": raw, "stage": stage, "previousStage": previous_normalized, "transition": transition,
        "confidence": confidence, "metrics": metric_values,
        "entryAdvice": entry_advice(stage, transition),
        "decision": lifecycle_decision(raw, stage, transition, confidence, metric_values, config=config),
    }
```

主流程注意：状态机对**全序列逐步重放**（每步只用尾 8 帧窗口），最终 stage 由整条路径累积决定；序列不足 2 点 → 直接 `cooling`。

### §2.7 阈值总表（config 默认值=原硬编码，`engine/config.py:351-402`）

| 组 | 字段=默认值 |
|---|---|
| raw·warm | `cycleRawWarmPercentileMin=65.0`，`cycleRawWarmBestRankMax=25.0` |
| raw·hot_zone | `cycleRawHotZonePercentileMin=85.0`，`cycleRawHotZoneBestRankMax=10.0` |
| raw·recovery | `VelocityMin=0.0`，`AccelMin=-1.2`，`PercentileMin=50.0`，`BestRankMax=30.0`，`HotMin=1` |
| raw·expansion | `PercentileMin=70.0`，`AccelMin=-1.0`，`HotMin=1`，`BestRankMax=20.0` |
| raw·crowded | `HotMin=3`，`BestRankMax=5.0`，`DrawdownMax=1.0`，`VelocityMax=1.0` |
| raw·reversal | `DrawdownMin=2.0`，`AccelMax=-1.0`，`HotMin=2`，`BestRankMax=10.0` |
| normalize | `WeakeningAccelMax=-1.0`，`SevereAccelMax=-2.5`，`SevereDrawdownMin=3.0`，`CoolingReadyPercentileMax=72.0`，`CrowdedCarryPercentileMin=82.0`，`CrowdedCarryBestRankMax=12.0` |
| conf·cooling | `RegionPctMax=60.0`，`MomentumPctMax=60.0`，`PersistenceHotMax=1`，`DrawdownMax=1.0` |
| conf·ignition | `RegionPctMin=50.0`，`RegionPctMax=80.0`，`MomentumAccelMin=-0.8`，`PersistenceHotMax=1` |
| conf·expansion | `RegionPctMin=60.0`，`MomentumAccelMin=-0.2`，`PersistenceHotMax=2`，`DrawdownMax=1.0` |
| conf·crowded | `RegionPctMin=82.0`，`RegionBestMax=10.0`，`MomentumPctMin=80.0`，`MomentumHotMin=2`，`PersistenceHotMin=2`，`DrawdownMax=1.0` |
| conf·reversal | `RegionPctMin=70.0`，`RegionBestMax=20.0`，`PersistenceHotMin=2`，`PersistenceBestMax=10.0`，`DrawdownMin=1.0` |
| **残留硬编码（参数面外）** | 热区 `rank<=10 or percentile>=88`（cycle_metrics_window）；`cooling→ignition` 分支 `pct<72`；normalize `weakening` 的 `drawdown>=2`、`severe` 的 `velocity<-1`；conf reversal 的 `accel < -1`；置信结构 `50+4×10, clamp[50,90]` |
| 决策层 13 阈值 | `lifecycleMidLongCommitmentMin=45.0`，`lifecycleAccelCommitmentMin=8.0`，`lifecycleWeakPathCommitmentMax=0.45`，`lifecycleVelocityMin=18.0`，`lifecycleAccelMin=12.0`，`lifecycleLowVisibilityPathMax=0.7`，`lifecycleLowVisibilityMomentumMin=18.0`，`lifecycleHighRiskPressureMin=0.75`，`lifecycleHighRiskDivergenceMin=0.8`，`lifecycleHighRiskOverheatMin=0.7`，`lifecycleConfirmFrames=1`，`lifecycleVetoVoteStrength=1.5`，`lifecycleDowngradePenalty=0.5` |
| 门控形态开关（阶段 24） | `lifecycleVetoGateMode="hard"`（hard/soft/off），`lifecycleVetoPathMode="all_soft"`，`lifecycleDowngradeGateMode="hard"`（默认均 hard=现行为） |
| 观察分权重 | `lifecycleWeights=[0.35,0.25,0.2,0.2]`（stageFitness/pathCommitment/momentumConfirmation/riskSafety），`lifecycleMomentumWeights=[0.3,0.45,0.25]`，`lifecycleMomentumScales=[15.0,15.0,8.0]`，`lifecycleStageFitness=[1.0,0.8,0.35,0.2,0.0]`（expansion/ignition/crowded/cooling/reversal） |

### §2.8 signalTier 映射与观察分（`runtime.py:368/383`）

```python
def _lifecycle_tier(stage: str, action: str) -> tuple[str, list[str]]:
    """周期离散档位（signalTier）。规则见 docs §6.4。"""
    if action == "veto":
        return "E", ["生命周期一票否决"]
    if action == "allow" and stage in ("ignition", "expansion"):
        return "A", ["优选路径"]
    if action == "caution" and stage in ("ignition", "expansion"):
        return "B", ["低可见度点火/假突破，谨慎观察"]
    if action == "exit_watch":
        return "D", ["拥挤，退出观察"]
    if stage == "cooling":
        return "D", ["冷却，回避"]
    return "C", ["中性"]
```

观察分（展示面，0-100；阶段 23.3 已裁「signal-neutral 展示层冗余」）：`score = 0.35×stageFitness + 0.25×pathCommitment + 0.2×momentumConfirmation + 0.2×riskSafety`（`compose_observation_scores`，veto 不清零只警示）。

---

## §3 消费链（生命周期结果被谁吃、怎么吃）

### #1 总档合成 `_synergy_tier`（`ranking/volume_price.py`）——环境门主体

七维投票合成（resonance/rankTrend/volumePrice/crossSection/priceMomentum/**divergence**…），生命周期以 `lc_tier` 参与（**门控修正，无加性正票**，见 §1 勘误注记），**两处结构短路**（默认 hard）：

> **divergence 维语义补记（Opus 审定轮 2026-10-07，源 `volume_price.py:348` docstring + `config.py:154`）**：dv=`priceRankDivergence` 第 7 维（2026-08-18 量名背离——confirm_up 一致强 / **rank_lead 关注度先行** / confirm_down / **price_lead_warn 出货预警**），已接线为加性投票（`v += strength × tierSynergyDivergenceVote`）但**默认权重 0.0=纯观察维、当前不进票**（config:154 原文「0=观察；数据验证后定默认」；对照 cs=0.75 在票、pm=0.0 实证负贡献关闭）。即「注意力×价格背离」已有专门观察维——任何「把价格/资金信息引入生命周期」的提案必须先与该维做冗余面测定（原文语料漏展其语义，Opus P2 提案踩此坑，见 §11/§11.1）。

- `lc_tier=="E"` → 直接返回 `"E"`（「周期一票否决」，票值无关短路，位阶最高）；
- `lc_tier∈{B,D}` → 已达 S/A 的帧**降一档**（S→A、A→B）。

摘录（阶段 24 已参数化，默认 hard=现行为）：

```python
    lc_e_negative_vote = False
    if lc_tier == "E":
        if veto_mode == "hard" or (veto_mode == "soft" and _lc_veto_keep_hard(c, lc_veto_path)):
            return "E", ["周期一票否决"]
        if veto_mode == "soft":
            lc_e_negative_vote = True
    ...
    def _ladder(vote_sum: float) -> tuple[str, list[str]]:
        if vote_sum >= c.tierSynergyVoteStrong + 1:
            return "S", ["方向一致强买（档位加权高分）"]
        if vote_sum >= c.tierSynergyVoteStrong:
            return "A", ["方向一致强买"]
        if vote_sum >= c.tierSynergyVoteWeak:
            return "B", ["方向分歧，弱买"]
        if vote_sum <= c.tierSynergyVoteReverse:
            return "D", ["反向"]
        return "C", ["无明确方向"]
```

当前票权下 max vote = res 0.75×1.2 + rank 0.75×1.2 + vp 1.0×1.2 + cs 0.75×1.0 = **3.75**（A 线 2.0 / S 线 3.0 / D 线 −1.0）。veto 是离散 0/1 跳变（E 强制封顶），降档是 −1 档跳变，均无剂量曲线（阶段 24 扫描后维持 hard，§4.3-C）。

### #2 候选池 `compose_strategy` / `compose_analysis_candidate_tier`（`runtime.py`）

- `decision.action == "veto"` → 候选锁 `N_NEUTRAL`（「生命周期辅助决策一票否决，阻止进入 A/B 候选池」）；
- 候选分层对 stage **硬依赖**（6-07 审计原话：「stage 一旦判错，A/B/C/D 会同时错」）：

```text
A_MAIN:      stage == expansion  且 momentum.mid≥tierAMainMidMomentumMin 且 momentum.short≥tierAMainShortMomentumMin
             且 trend_buy 且 allow_a_main（热榜情绪高潮/发酵且非高风险）且 divergence severity 不高
B_IGNITION:  stage == ignition   且 momentum.short≥tierBIgnitionShortMomentumMin 且 momentum.acceleration≥tierBIgnitionAccelMin
             且 allow_b_ignition（高潮/发酵/启动）且 pressure 不高
C_CROWDED:   stage == crowded（或长动量高位+加速度衰竭/风险压力）
D_EXIT_RISK: stage ∈ {reversal, cooling} 且短动量/加速度/风险压力转弱
```

- 市场级门先于个股级：热榜情绪 `退潮/冰点` → 直接 D_EXIT_RISK 或暂停入场；`高潮/发酵` 才放行 A/B（§1 的 market_regime 门，正交）。
- 阶段 6 业务口径（用户裁决 2026-08-15）：A_MAIN/B_IGNITION 的 action=watch，不作为默认策略入场投票。

### #3 交易层（`core/backtest/execution.py:805` 摘录）

入场三锁（全部满足才可买）：`synergy tier ∈ {S,A}` + `zljzb ≥ 0` + `lifecycle.veto` 非否决：

```python
        lifecycle = (signal.get("rankTrend") or {}).get("observation", {}).get("lifecycle") or {}
        if lifecycle.get("veto"):
            return False
```

出场腿：synergy tier 进 D/E 时按 `synergyExitOnDanger`/`downgradeSteps` 计数退出（环境门价值的可能主通道，saEx 类信号层指标测不到，只能 Track 1 交易模拟）。

### #4 确认链 WP2a（`runtime.py:1152`）

veto/B/D 降档可配 K 帧确认，默认 `lifecycleConfirmFrames=1`（直通）；K=2/3 已被阶段 12 证伪（§4.3-D）。

### 展示面

主表【周期】列 = `cycle.stage` 的纯投影（点火/扩散/拥挤/反转/冷却五词，后端单源词表），样本质量灰框承载质量标注。用户三项展示裁决（2026-09-19/20）：排序按 stage 序数聚簇（点火>扩散>拥挤>反转>冷却）；`样本不足` 行归末组；不改判定只立项研究。展示与交易消费同源不同义——改 stage 定义会同时改这两面。

---

## §4 实证全景（全部已归档读数）

### §4.1 负向证据：对方向几乎无贡献（多轮独立实证同向）

| # | 证据 | 读数 | 来源 |
|---|---|---|---|
| A | 阶段 3 语义校准（769 帧 / 156,647 信号，h8 excess；h8=8 帧后视） | lifecycle 维度**无 S 档**；A +0.055 < B +0.097（**反转**）；对照 rankTrend 维 S/A/B=+0.064/+0.037/−0.013 达标；synergy 合并 S/A/B=+0.088/+0.039/−0.006 达标（靠其他三维）——**lifecycle 是四维中最弱投票输入**。**勘误注记（Opus 审定轮 2026-10-07）：三数均为 S/A/B 档位 excess（原档表列头「S/A/B excess」），非三窗读数；B 档负值=弱趋势档单调梯度末端，与「达标」不矛盾** | 主计划 §5.4（commit `40ddc7f`） |
| B | 生命周期分层 vs RankTrend 匹配度（阶段 6 s7，h8 口径） | A_MAIN h8 0.514 < S/A 基线 0.5272；D 状态 h8 0.5264（**预测反弹**，均值回归）；stage=reversal 0.4973（**无预测力**）；唯一有效状态机信号 D→B 跃迁 0.5198 | rearchitecture 文档 §2.1 |
| C | **6-07 实现审计** | 「生命周期分层实现不能继续被当成可靠买卖标签……不适合作为硬入场、硬过滤或独立买卖系统」；V3 4+5 月 27 笔：A_MAIN 17 笔 76.5%/+3.83%、B_IGNITION 10 笔 70.0%/+2.50%，但 entryAdvice=preferred **不强于** watch；rawStage≠stage 的 3 笔全部盈利 | `docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md` |
| D | 层 1 事件级区分度（阶段 23.2） | A 档 +0.036 / +0.030 / **−0.0006**（逐窗衰减，oos2 转负）；D/E/B 档 saEx=None（统计退化） | 长测计划 §23.2 |
| E | **阈值坐标下降搜索**（2026-08-16 commit `ada4a27`，10 参数×2-3 档 ≈20 次 replay） | **best=baseline**——stage 阈值调整无法改变 A/B excess 关系（评估集读数 A 0.0092 < B 0.0228 同向反转）。**根因**：A 档（21,475 样本，覆盖全部 allow×ignition/expansion 帧）高分位混杂、excess 被均值回归拉低；B 档（1,877 样本）低分位 excess 天然高——**分位结构性差异，阈值不可调** | threshold-optimization-design §8.2 |
| F | 静态硬过滤复跑失败（2026-05） | B_LONG 过滤（按生命周期 long 特征硬过滤）：4 月 totalReturn +6.76%→+3.64%、5 月 +14.81%→+5.33%，双月恶化；A_MAIN 风险过滤同样不稳定 | 6-07 审计回测证据 |

### §4.2 正向证据：环境门价值真实

| # | 证据 | 读数 |
|---|---|---|
| G | **整维归零对照**（阶段 23.8 no_lc_gate，门控干预全拆） | synergy saEx 三窗 **−61.0% / −48.8% / −49.4%**——环境门是当前 saEx 第一支柱（实测于落默认前 1.0 票权基线，锚 22.8） |
| H | 触发结构（阶段 23.2，rawHits 口径） | veto 触发 8.4%（其中 stage=reversal 驱动 **8816/11003**，HighRisk 压力路径占其余）；B/D 降档实际改判 4.3%；合计 ~12.7% 帧被环境门改判。lc 档位分布：D 76.4%（cooling 主导）/ A 13.9% / E 8.4% / B 1.2%，**无 S 档** |
| I | 门控翻转率基线（2026-08 冻结段：202 帧 / 45,686 信号 / 43,873 可比对） | veto 翻转率 0.1376（6037 次）、bd_downgrade 0.0834（3661 次）；per-code top 翻转 ~80-91 次/月（603986 等）。**口径注记（Opus 审定轮 2026-10-07）：本行是相邻帧「翻转率」（comparable-pair 分母），H 行 8.4% 是「触发率」（decision 窗 rawHits）——两口径两窗不可直除对账，Q8 误伤估计前先对账** |
| J | 新基线锚（阶段 24 锚 1 = 当前默认配置三窗 saEx） | decision 0.1044 / oos1 0.0918 / oos2 0.0933 |
| K | 「环境门有价值」与「分层无方向贡献」**同时成立、互不矛盾**；且干预价值可能集中在负向过滤（veto 否决+降档），但两者相对贡献**从未分离**（23.8 是一起拆的）。存在真实张力：D 档帧预测反弹（§4.1-B）→ cooling 降档对入场排序可能是负价值——c 组裁决读数见 §4.3-C | gate-redesign-proposal §2.3 |

### §4.3 已证伪方向清单（提案不得撞枪口，除非有新结构理由并显式论证）

| # | 已证伪 | 证据 |
|---|---|---|
| A | **单纯调 raw_stage/normalize 阈值** | §4.1-E 坐标下降 best=baseline + 分位结构性根因。**命题域注记（Opus 审定轮 2026-10-07）：扫描实测覆盖 10 参数（threshold-optimization-design §8.2 原文「10 参数 × 2-3 候选」）**——残留硬编码（§2.7 表末）与未扫参数上的「不可调」是构成性根因（tier 构成由分位带决定）的外推论证，非全空间实测；动这些字面量的提案仍须按 §0 任务卡论证为何绕开根因 |
| B | **用 lifecycle.score 连续分替代标签做门控** | 方案 B 前置验证：score 五分位桶 saEx = +0.037/+0.000/−0.011/+0.007/+0.037（U 形，spearman −0.1，首末桶差 −0.0004）——连续分没有标签没有的方向内容，FAIL |
| C | **软化门控形态**（veto 转负票/降档转惩罚） | 阶段 24：veto 剂量轴 b0-b3 软化使 decision 单调受损，b2/b3 零效应；降档 penalty U 型峰=1.0（数学等价 hard），c1 关降档非甜点；路径分流 d1/d2 三窗逐位零效应；唯一 saEx 假阳组合 p2/e1a 在 Track 1 交易复核被否决：主窗 wrxpf 0.470→0.319（**−32%**）、maxDD −18%→−32%（oos2 +64% 仅 22 笔小样本）。**三处 0/1 干预均为数据验证后的局部最优，维持 hard** |
| D | **多帧确认链**（K=2/3） | 阶段 12：veto 翻转率 0.127→0.023→0.010，decision saEx 0.0811→0.0539→0.0454 单调恶化、OOS 两窗一致受损——被滤掉的「单帧噪声 veto」里含真实信息 |
| E | **生命周期硬买卖标签/静态硬过滤** | §4.1-C/F 审计+复跑 |
| F | **伪方向序 A>B>C>D>E 当方向标尺** | §4.1-A/B/D；已裁决降级为展示投影，保留环境/风险标签价值 |

### §4.4 指标口径卡与系统性教训

- **saEx** = S/A 两档合并加权 excessDirectionAccuracy（`sa_excess_of`）——**B/C/D/E 档完全不在统计集**，凡只迁移负票/中性档的改动 saEx 结构性不可见（方法论主发现，`ranktrend-l1-param-ledger.md`:367）。
- **wrxpf** = winRate × profitFactor（交易层终判指标）；**h8** = 8 帧后视窗口的区分度读数（不同实验里分别以超额/准确率形态出现，精确定义见 §7 缺口）。
- 信号层达标线（历史）：synergy S/A excess ≥ 0.05 且 S/A/B 正单调；交易层：连续两 walk-forward 窗 wrxpf ≥ 0.78。
- **市况依赖教训**（本系统多次复现）：低开回避条款 7-9 月有效、4-6 月高涨期反向；量能轴 9 月有效 8 月失效；卖点规则市况依赖四次复现。任何生命周期改动同样必须分市况检验。
- 归因顺序纪律（AGENTS.md §1.2.6）：偏差先查 ①原料 → ②判据设计 → ③协议/解析 → 最后才是方案重设计。

---

## §5 硬约束（提案必须遵守）

1. **golden 锁基线**：引擎 golden 以 `analysis/ranktrend/engine.py` 为准；任何阈值改动走「参数化、默认值=原值、零行为变化」，新值只作候选配置验证，**不自动写回默认**（一次一候选、用户裁决后落默认）。
2. **角色裁决**：生命周期保持「环境门 + 投票输入」，不恢复硬买卖标签（§4.3-E/F）。
3. **评估链**：信号层（tier 区分度/excess 单调性，769 帧全窗 replay）→ 判定卡三窗（decision/oos1/oos2）→ **Track 1 交易模拟（wrxpf）终判**（saEx 对出场通道盲区，§3#3）。
4. **fail-visible**：缺数据/低样本/类型残缺必须显式暴露，不得用 0 或空结果伪装。
5. **改动透明可回退**：config diff 优先；config_hash 区分代际；禁版本化文件名。
6. **禁拟合**：不朝已知标签日/已知好读数调参；新特征走「分位化→次日后验对齐→数据里找自然分界→逐月验稳定」，并检验市况适用域。

---

## §6 未决问题（推理主目标，逐条归因后提案）

- **Q1 输入瓶颈**：生命周期只吃注意力排名序列（7 个导出量）。这是「方向贡献≈0」的第一嫌疑：排名轨迹衡量的是「注意力位置与动量」，与「明天能不能赚钱」之间隔着价格行为/资金行为。同一 `_replay_stock` 里现成有 `price_changes`（涨跌幅序列）、`amount_history`（成交额序列），frame 里还有 `volumeRatio/zlje/zljzb`（量比/主力净额/主力净比）——**原料在窗内但没喂给生命周期**。请评估：若引入，哪些原料最可能有增量信息（排序并给理由）？会不会与现有 volumePrice 维度（已吃量价）冗余？
- **Q2 状态机语义**：normalize_stage 的滞回设计（audit 发现 3：一旦进入 expansion/crowded，短期走弱不一定立刻反映；假主升可能被保留为 expansion；rawStage≠stage 时交易层只看 stage 会漏路径风险——而 rawStage≠stage 的 3 笔已成交样本全部盈利）。滞回的收益（去抖）与代价（掩盖转折）如何量化？5 态划分本身（ignition/expansion 只隔一个 `pct≥70` 边界；crowded 要求「高位+滞涨」与 reversal 的「高位+回撤」只差 drawdown 1 格）是否有结构性问题？
- **Q3 A 档均值回归混杂**：A 档=全部 allow×ignition/expansion 帧（21,475 样本），高分位帧被均值回归拖累（§4.1-E 根因）。「高位 allow」是否应从 A 剥离（例如 expansion 内部再分层）？如何设计才能不退化成已证伪的静态硬过滤（§4.3-E）？
- **Q4 D 档的反弹信息**：D 状态 h8 0.5264 预测反弹（均值回归区）——负向门里含正向信息。出场侧（exit_watch/降档）与「深谷后修复」类研究（系统另一轨道：EOD 情绪深谷状态跟随）是否可对齐？这属于生命周期本体优化还是消费侧优化？
- **Q5 时间不规则性**：缺帧跳过不插值 → velocity/acceleration 可能跨缺口（甚至跨日）比较，hot streak/best/drawdown 的「8 帧」语义在缺帧下漂移。是否需要时间加权/缺口标记/最大间隔截断？注意与回池 gap 专项（P_repool_timeline_gap）结论的衔接。
- **Q6 绝对名次 vs 相对分位**：`rank≤10/best≤5/drawdown≥2` 等名次口径阈值在池规模时变（~200 但有波动）下是否稳健？ percentile 类阈值与之并存的双口径是否有系统性偏置（大池日 vs 小池日判层不一致）？
- **Q7 窗口依据**：序列窗 50 帧、metrics 尾 8 帧、rank_path_commitment 权重（0.45/0.45/0.1）、shock 的 5 差窗口——全部无实证标定记录。哪些值得进灵敏度扫描，哪些预期冗余？
- **Q8 门控效率**：现状 12.7% 帧被环境门改判、veto 翻转率 13.76%（月内 per-pair）。在「保护价值不可丢（§4.2-G）」前提下，是否存在**同等保护、更少误伤**的重构空间（例如按 veto 驱动路径 reversal vs highrisk 差异化——注意阶段 24 d1/d2 分流本身零效应，但那是在「hard 形态不变」前提下的分流）？

---

## §7 诚实缺口（本语料没有的，按「未知」处理，禁止臆测）

1. `sa_excess_of` / `tier_forward_returns` 的精确公式与超额基线口径（`backend/operations/optimize_resonance_parameters.py`）——h8 读数的精确单位与基线未入语料。
2. 阶段 23 B 组（lifecycle_decision 13 阈值扫描）的逐档读数（长测计划 §23）——本语料只登记「扫过、门控形态不在其参数空间」。
3. 5 态 stage 全池分布（ignition/expansion/crowded/cooling/reversal 各占比）未入语料（只有 lc tier 分布 §4.2-H）。
4. 逐股真实序列样例（含判层转折点的前后文）未附——如推理需要，可从 replay 导出补充。
5. TS 前端同构实现（`attentionCycleAnalyzer.ts` 等）与 Python 的现状一致性状态未入语料（golden 主链以 Python 为准）。

---

## §8 输出格式合同

1. **理解复述**（≤10 条，每条标 §来源）——这是承重墙自查，先做；
2. **归因诊断**（§0 任务 1）：给主因排序，多因并存时说明各自证据强度；
3. **优化提案**（≤5 条，按 §0 分级 L1/L2/L3）：每条含改法/预期读数变化/验证设计/失效风险/回退/不撞 §4.3 的论证/市况适用域回答；
4. **证据不足与矛盾清单**（没有写「无」）；
5. 明确声明哪些提案只是「值得预登记验证的假设」，不要把假设写成结论。

---

## §9 投喂模板与用法

### §9.1 system 文本（存为 `lifecycle-review-system.txt`）

```text
你是量化系统评审专家。遵守项目归因纪律：模型/规则输出与预期偏差时，归因顺序固定
①原料/输入供给 → ②判据与算法定义 → ③下游消费形态 → 最后才是方案重设计。
禁止无数据支撑的方案重设计；所有优化方向必须给出验证方法（replay/回测/样本需求）与回退方式。
不做正收益拟合（用户裁决：拟合是弯路）；改动必须透明可回退。
反幻觉：只允许使用用户提供的语料推理，引用须标 §编号；禁止编造字段/数字/文献；
不确定写「未知/证据不足」；发现语料内部矛盾要显式指出。
```

### §9.2 user 文本骨架（存为 `lifecycle-review-prompt.txt`）

```text
以下是 A 股短线系统「个股生命周期分层」算法的完整语料（代码逐字 + 全部已知实证）。
请按语料 §0 任务卡与 §8 输出格式合同作答（本轮先只答：理解复述 + 归因诊断 +
提案前请先完成证据不足清单）。

【语料】
<粘贴本文档 §1-§8 全文（§0 任务卡含在语料内，位于最前）>
```

（GPT-OSS 脚本一问一答无多轮追问，建议第一轮只要 1+2+4 项；看到归因质量后再用第二轮投喂 §0 任务 2 专要提案，可附上第一轮输出摘录。）

### §9.3 执行命令（GPT-OSS-120B 脚本通道）

```bash
# 令牌：env CLOUDFLARE_API_KEY 或 quant-board/.env.local（脚本自动回落）
python scripts/gptoss_questionset_review.py \
  --system lifecycle-review-system.txt \
  --prompt lifecycle-review-prompt.txt \
  --out gptoss-lifecycle-a1.md --effort high --timeout 600
```

成本量级：语料 ≈18-22k input tokens（约为 EOD 包 2 倍）+ 2-6k output，单次 ≈$0.01-0.1（workers-ai 计费口径，估算值）。

### §9.4 审定纪律（沿用两轮先例）

1. **承重墙抽验**：模型复述里的代码行为/阈值数字/字段名逐字对照本仓库（`lifecycle.py`/`config.py`）——crowding 审定 4/4 逐字通过才可信其归因；
2. 幻觉条目**全弃**（crowding 先例：5 幻觉全弃、真归因 1 条采纳）；
3. 模型提案 = 假设，进入验证须：预登记（考题/窗口/判定线/样本量）→ 用户点头 → 只读 replay → Track 1 → 用户裁决；
4. 语料-代码漂移若被模型抓出（EOD 轮先例：抓出 2 处），主会话核实后当轮勘误本文件。

### §9.5 Opus 4.x 备选投喂

全文（§0-§8）直接粘贴即可，长上下文无压力；建议要求「先承重复述、再归因、最后提案」三段输出，并给反幻觉同款 system。若 GPT-OSS 一轮后归因深度不足（只复述不深挖），换 Opus 是正确升级路径。

---

## §10 组装来源

| 材料 | 路径 |
|---|---|
| 算法源码 | `quant-board/backend/analysis/ranktrend/trend/lifecycle.py`、`trend/technical.py`、`engine/primitives.py`、`engine/runtime.py`、`engine/config.py`、`ranking/volume_price.py`、`core/backtest/execution.py` |
| 合同文档 | `docs/ranktrend/lifecycle-layering-contract.md` |
| 证据文档 | `quant-board/docs/ranktrend-tier-backtest/ranktrend-lifecycle-gate-redesign-proposal.md`（§2 证据链+§8 阶段24结论）、`ranktrend-lifecycle-threshold-optimization-design.md`（§8 参数化+否定性搜索）、`gate-flip-baseline-2026-08.md`、`ranktrend-longterm-backtest-plan.md`（§12/23/24）、`ranktrend-l1-param-ledger.md`（saEx 方法论） |
| 审计 | `docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md` |
| 语料范式 | `quant-board/docs/hotlist-jev/reasoning-corpus-eod-emotion.md`（§7 审定流程与反幻觉纪律） |

---

## §11 审定战报（2026-10-07，Opus 4.8 首轮，用户直投全文）

**执行事实**：用户跳过 GPT-OSS 脚本通道，将本包全文直接投喂 Opus 4.8，一轮出齐 §8 合同全部四件（复述/归因/提案/反面检查）；输出全文由用户贴回主会话，本节为审定归档。

**审定结论：通过**——复述承重墙 10/10 逐字对上（含 rank≤10⇔pct≥95.5@池200 等算术复算），归因与提案层零硬幻觉；反面检查 9 项证据不足清单与 §7 一一对应属实。首轮质量即达 EOD 轮 GLM 接地通道水平。

**语料勘误 4 处（模型反面检查抓出→主会话对照源码/原档核实→当轮修正，正文已带标注）**：

1. **B3→§4.1-A（真勘误）**：rankTrend「+0.064/+0.037/−0.013」三数是 **S/A/B 档位 excess**（threshold-optimization-design §2 表列头原文），非三窗读数——B 档负值是弱趋势档单调梯度末端、与「达标」不矛盾。原表述歧义。
2. **B2→§1/§3#1（真勘误，价值最高）**：「环境门+投票输入」的「投票」系设计文档措辞；**代码事实无 lifecycle 加性正票项**（票和=res+rank+vp+cs+pm+dv）——模型归因 ③「方向通道被构造锁定为 {0、−1 档、veto}，连续/分级方向贡献机制根本不存在」获代码级实锤。
3. **B1→§4.3-A（精度收窄）**：坐标下降实测覆盖 **10 参数**（原档 §8.2），「阈值不可调」在残留硬编码与未扫参数上是构成性根因外推——§4.3-A 命题域已收窄并保留防线。
4. **B5→§4.2-I（口径注记）**：8.4% 触发率（decision 窗 rawHits）vs 13.76% 相邻帧翻转率（2026-08 冻结段 comparable-pair）两口径两窗，不可直除；Q8 误伤估计前须对账。

（B4 滞回证据反向：语料本就两面呈现的已知张力（§4.1-C），不修。）

**主会话补刀（模型没接上的两处）**：

1. **P2 主断言与既有维度相抵**：P2 称「注意力×价格交互是现有七维都没有的角度」——但第七维 **dv=priceRankDivergence**（量名背离：rank_lead 关注度先行 / price_lead_warn 出货预警，加性投票）正是该角度，语料原文漏展其语义（模型在 A1 诚实标注需读码，不算幻觉）。P2 的真实残差收窄为「交互证据从加性投票位移到 lifecycle 决策层作风险证据」的接线位置差异，**立项前置=读 divergence 实现做冗余面测定**。
2. **P4-阶段 2 前提被 c 组先验压低**：阶段 24 降档轴 U 型峰=1.0（≡hard），端点（含 c1 关降档）劣于 hard——降档腿在 saEx/decision 面正贡献已有强先验；P4 的真实增量在出场腿（saEx 盲区）。且阶段 1 分解的 c1/a0/a2 读数在长测计划 §24.3 存档，**先考古再决定是否重跑**。

**提案裁定与建议顺序（全部=假设，进验证须预登记+用户点头）**：

| 提案 | 裁定 | 要点 |
|---|---|---|
| P1 双口径统一 | ✅ 可预登记 | 诊断步先行（total 分布未知）；不承诺修复 A/B excess，攻击的是扫描未触碰的尺度混杂变量 |
| P2 交互证据进决策层 | ⚠️ 先读 dv 维 | 冗余面测定是硬前置；原料排序①price_changes 合理 |
| P3 时间正规化 | ✅ 可预登记 | NaN 比较全 False→静默滑 cooling 的语义坑核实为真；自带 §4.3-D 防线（veto 保留率监控） |
| P4 分解+低位豁免 | ✅ 阶段1 先考古存档；阶段2 前提偏负 | 出场腿是真实增量面 |
| P5 双轴重设计 | ✅ 论证级合规 | 前置四项设计完整；「与 U 形证据一致的非单调离散门」论证成立 |

建议顺序：P4-阶段1（考古 §24.3 为主，近零成本）→ P1 诊断步 → P3 → P2 读码冗余面 → P5 前置四项（stage×分位列联/互信息可直接从 replay 导出）。

### §11.1 主会话考古补记（2026-10-07，"先2后1"第①批执行完毕）

**P4-阶段1 两腿分解（长测计划 §24.3 存档直读，零计算）**：

- **降档腿边际** = c1（降档关闭、其余 hard）：decision −39.4% / oos1 −34.4% / oos2 −5.8%（rel）——**降档正价值确认**，原档已裁决「cooling 降档非负价值」，§4.2-K 张力就此关闭；
- **veto 腿无独立关断臂存档**（a3=新基线 gate_off 全计划 grep 零命中）；总门=旧票权 a1−a2 = −61.0%/−48.8%/−49.4%；跨基线粗估 veto 腿≈总门−降档腿（a1/a0 水平差 ~10% 注意），精确分解补一次 a3 replay（harness `evaluate_lifecycle_gate_form.py` 现成）；
- **P4-阶段2 门槛在信号面 FAIL**——其前提「降档腿≈0 或为负」被 c1 直接否定；残余=「低位 cooling 定向豁免」（c1 是全关、定向子集未被测）弱先验未测，优先级降为最低。

**P2 的 dv 维读码（Opus A1 读码义务代做）**：`trend/price_rank_divergence.py` = priceDir×rankDir **单帧**交叉四态（confirm_up=A / rank_lead=B 关注度先行 / confirm_down=C / price_lead_warn=D 出货预警）；消费权重 `tierSynergyDivergenceVote` **默认 0.0=纯观察维不进票**（config:154「0=观察」；对照 cs=0.75 在票、pm=0.0 负贡献关闭）。P2 同族残差四处：①位置条件（pct≥88；dv 无位置语义）②amount 腿（dv 无成交额）③多帧窗（8 帧符号一致 vs 单帧）④消费位置（lifecycle 决策层谓词 vs 观察维）。旁证：§24.4 Track 1 实测 vp E→D 短路真保护（放开新增 20 笔 wr/pf 更差、主窗 wrxpf −32%）。
**P2 后续路径**：预登记须含「与 dv 触发集重叠率/增量检验」步骤；若 P2 触发集 ⊆ dv 高分位 rank_lead/price_lead_warn 且无增量 → 并入 dv 语义扩展（位置条件化+amount 腿）而非新机制。

**Opus 第二轮提示词已组装**：`lifecycle-stage-opus-round2-prompt.md`（范围收窄为 P1/P3 预登记合同；本节两块考古事实作为「已核实事实」写入提示词，附审定回执 B1-B5）。

### §12 行为步执行报告（2026-10-07，用户令「开跑」；判定线按合同冻结）

**执行链**：诊断脚本 `backend/operations/diagnose_lifecycle_scale_gap.py`（P1+P3 双 schema 一次 pass，951 帧 04-15~09-11；自证 inline vs analyze_cycle 2000 抽样零 mismatch、vs 引擎真 replay 653/653 全中）→ config plumbing（`lifecycleRankScaleMode`/`lifecycleTimeGapStrictness`，默认零行为，TDD 16 用例+回归 54 过）→ trial runner `evaluate_lifecycle_scale_gap_trials.py`（5 trial × 3 窗）→ Track 1（`track1_lifecycle_gate_trade.py --extra-arm` G1 臂）。产物：`data/reports/lifecycle-scale-gap-diagnosis.json` / `lifecycle-scale-gap-trials.json` / `track1-g1-*.json`（本地不入库）。

**诊断步读数（跑数前预声明：主判定 population=decision 窗、序列≥2 股帧）**：

- **P3 诊断门 PASS**：ER=P(gap_origin|velocity>18)/P(gap_origin)=**3.33**（聚块 bootstrap 95%CI [3.18,3.49]）；P(gap|vel>18)=41.8% vs 基础 P(gap)=12.5%；四窗全部 3.18~3.58 同向（OOS 复现）；下行尾更富集（4.10）；G2（同日非相邻）同量级 3.27。**gap 差分集中驱动状态跃迁**：crowded→reversal 帧 gap 占比 25.9%（2.1× 基础率）、cooling→expansion 17.2%，hold 帧 12.5%=基础率。veto/bd 帧 gap 占比 10.4%/13.1%≈基础率（门控触发本身不偏 gap）。
- **P1 诊断门 PASS（谓词线）**：drawdown 谓词跨 T 三分位分歧 7.2~9.0%（大池桶最高）、best_le_30 3.1%；但被状态机+决策层吸收，末态分歧仅 stage 1.38% / veto 0.60% / bd 0.99%（低于其线）。**结构发现：decision 窗 18.2% 帧 T<75（p5=0），5-9 月无小池日**——4 月与后期名次阈值语义系统性不同。
- **P2 路径关闭（证据级）**：诊断证实 price/amount 原料在窗；dv 维（单帧价×排名四态）默认 0 权重=纯观察。P2 的 dv 重叠率检验仍欠，维持另批。

**行为步 trial（三窗 synergy saEx；veto/bd=触发率 rel）**：

| trial | decision | oos1 | oos2 | veto_rel(dec) | bd_rel(dec) | 判定 |
|---|---|---|---|---|---|---|
| a0 今日基线 | 0.1472 | 0.1016 | 0.1071 | — | — | 锚漂移登记↓ |
| L1 hotzone_pct_only | 0.1472 | 0.1016 | 0.1071 | 0.000 | 0.000 | **零效应**（热区名次臂在当前代际冗余：池≥75 时 pct≥88 臂恒覆盖 rank≤10，小池帧又不产信号） |
| L2 pct_full | 0.1427 | 0.1049 | 0.1071 | −0.9% | −0.1% | 带内 PASS 但 decision −3.1% 贴容差、无收益信号→**推荐不晋升** |
| G1 cross_day | 0.1450 | 0.0983 | **0.1172** | **−6.8%** | +1.0% | **PASS**（相对线全过；oos2 +9.4% 线索单窗不作定据） |
| G2 non_adjacent | 0.1457 | 0.0965 | 0.1172 | −6.9% | +1.1% | **FAIL**（oos1 贴线差 0.0001）→ 按合同 G3 不试 |

**Track 1 交易复核（G1）**：decision 主窗 166→172 笔，wrxpf 0.4104→**0.4140**（+0.9%）、winRate 0.4759→0.4884、maxDD −22.8%→−22.3%、totalReturn −0.84pp；oos2 80→76 笔 wrxpf −3.8%。两窗小样本噪声量级=**交易层中性，不劣于基线**（合同④过线）。顺带：e1a/p2 臂今日读数仍差（0.2541），阶段 24 OBSERVE 维持。

**基线漂移登记（重要）**：冻结绝对锚 0.1044/0.0918/0.0933 不可复现（今日 0.1472/0.1016/0.1071）——10 月初帧字段大回填（open/amount/zlje 等补齐 96.9-97.1%，e77907bb/cacf4ab8 代际）改变 fallback 输入 → saEx 基线整体上移；baseline wrxpf 亦然（0.4104 vs 存档 0.4702）。**判定改同代际相对线（容差不变 −0.005/−0.003），冻结绝对线双列披露**；此为跑后登记的口径修订，原因数据代际非调线。

**结论与待用户裁决**：
1. **G1（lifecycleTimeGapStrictness="cross_day"）达到提交门槛**：信号层 saEx 容差内、veto 误伤 −6.8%（三窗一致、可归因=跨日跳变驱动的 reversal 误判被消除）、交易层中性。收益是**质性**的（动量证据纯度：velocity>18 帧里 42% 的跨日假动量不再进判据），不是盈利提升——是否落默认由用户裁决（落默认需另补：数据回填代际复验 + 前端 temporalGap 展示消费 + golden 用例重录）。
2. L2 存档不晋升；L1 零效应（热区名次臂冗余=可登记结构事实，未来清理须用户裁决）；G2/G3 终止。
3. P1 的「换算后跨池一致性收敛」未在本轮测量（行为步只验了 no-regression），若用户要 L2 的收益证据需补一致性复测——但 L2 的 saEx 成本已见，预期不晋升。
4. 默认配置零漂移已验（专项 16 用例 + 回归 54 + 全量 pytest 见提交记录）。

### §12.1 落默认执行（2026-10-07，用户裁决「必须落，先 G1 再看 G2」）

用户裁决理由：热榜环境门否决太多，早有错判误杀嫌疑。执行清单（全部完成）：

1. **config 默认值**：`lifecycleTimeGapStrictness` off→**cross_day**（注释登记判定依据）；`lifecycleRankScaleMode` 保持 mixed（未落默认）。
2. **测试**：默认断言更新 + 新增「默认配置+跨日键自动生效」「off 诊断臂保留」用例（18/18 过）。
3. **golden 重录**：真行为变化版 diff 逐字段审查——gap 帧输出 metrics 动量分量 null+temporalGap 标记、假降温修复（cooling→expansion 沿袭真实路径）、risk overheat 中性化（35→15）、backtestSimulation 交易记录 stage 标注传导；全部在 G1 语义预期内，无开关重跑 11/11 逐位过。
4. **途中修复两处**：①`json.dump(allow_nan=False)` 遇 gap 帧 NaN 截断快照 → `analyze_cycle` 输出层统一 `_evidence_num`（NaN→null，不伪装 0）；②`analyze_risk` 直吃 metrics 算术炸 None → 防御下沉 risk 入口统一 `neutralize_gap_metrics`（None/NaN 双态→0），撤 runtime 单点中性化；③golden 测试 monkeypatch lambda 签名补 `**kwargs`。
5. **前端消费**（展示同步义务）：`types.ts` cycle.metrics 增 temporalGap + 动量字段 number|null；DataTable 周期列 tooltip 增「跨日缺口帧：动量证据缺失」标注（fail-visible）；vue-tsc 干净 + vitest 1172 全过。
6. **台账**：L1 ledger §18 登记（参数/判定依据/回退路径/新基线锚 0.1450/0.0983/0.1172/G2 重开条件）。
7. **G2 待办**：oos1 贴线差 0.0001 FAIL 不自动翻案；「再看 G2」= 待 G1 新代际复扫，须重新预登记（G1 改变基线后 G2 的剂量语义也要重估：G1 已消跨日差分，G2 剩余增量=同日非相邻对）。
8. Redis analyze 缓存清理 + 8000/8001 重启生效（见提交记录）。

### §11.2 第二轮审定（2026-10-07，P1/P3 预登记合同；输出归档 `lifecycle-stage-opus-round2-output.md`）

**审定结论：通过，零硬幻觉**。

1. **算术抽验 12/12**：no-regression 三线（锚−0.005 → 0.0994/0.0868/0.0883）与均值线（(0.1044+0.0918+0.0933)/3=0.0965，−0.003=0.0935）；c1 oos2 −5.8% rel≈−0.0054 绝对；T=200 换算六值（(201−R)/2 与 `percentile_rank` 公式逐位一致）；drawdown 1 格=0.5 pct 点；0.12T+1≥10（T≥75）/0.15T+1≥10（T≥60）覆盖方向论证正确；stage 2% 线=bd 足印 4.3% 之半；veto 1%≈8.4% 的 12% rel；「10 个 BestRankMax 字段」计数精确（§2.7 实数恰 10）；best_le 键集 {5,10,12,20,25,30} 与 config 默认值集一致；best 谓词 pct 形态（帧内 rank↔pct 严格单调 ⇒ min(rank) 帧=max(pct) 帧）成立。
2. **事实引用 8/8**：c1 三窗/e1a −32%/§4.3-D 签名 0.127→0.023（−82%）/D→B 0.5198/P_repool 14.2%→8.3%/8.4%·4.3%·0.1376·0.0834/oos2 22 笔教训全部与语料一致。
3. **B9 依赖①预解（主会话代码核实，合同可解除阻断）**：frames 逐帧带 `tradingDate`/`slotTime`——`runtime.py:1024-1025`（WP1c as-of 注入自身在逐帧读）+ `execution.py:350/360/497` 消费同一 frames 列表；`runtime.py:1294` 注释另证引擎已有跨日边界意识（「跨 tradingDate **不**恒重置——half_hour 每天仅 10-11 帧」）。写 loader 时终确认即可，不得再以帧序猜跨日边界（合同原文防线保留）。
4. **A4 回退必要性精确化**：stage/rawStage 纯函数可离线复算（`analyze_cycle` 不吃 risk/momentum）；veto/bd 末态吃 decision（risk/momentum 注入）→「flag=on +1 replay」对 outcomes 的 veto/bd 字段必要——合同按最保守路径预登记成本，正确非冗余。
5. **harness 盘点核实**：`diagnose_gate_flip_rate.py` 无 config 参数（只跑默认）——A8/B8「缺什么」栏判断准确。
6. 小注（非否决）：A2 的 replay 确定性论证更准引用=b2/b3/c3/d1/d2「逐位=baseline」（d1/d2 单独不足）；B5 momentum 项在 NaN 比较语义下自然 False，无需额外代码路径。

**主会话增量裁定（执行编排）**：①P1/P3 诊断步共享「1 次默认 replay 导出」——两薄脚本共用 loader，合并执行省 1 次 replay（合同 A7/B7 的 3-5+4-6 次 → 合计约 7-10 次）；②建议 P3 诊断先行：ER 检验最便宜，且「18/12 跨缺口假设」若成立会反向约束 P2 交互量设计（交互量也须时间正规化），先出数再定 P2 预登记。**开跑等用户裁决**（判定线已按合同冻结，跑后不得回看调线）。

### §13 Q1 诊断战报 + 预登记合同（2026-10-07，用户令「进入 Q1」；步骤 0+1 纯本地零调用）

**Q1 命题**（§6 主线）：price_changes/amount_history 已逐帧采集并传入 `_build_signal`，但 `analyze_cycle`
不消费——原料在窗未喂。G1 落默认后跨日步动量证据置缺，价量是独立来源的合法补位证据。

**诊断产出**（`backend/operations/diagnose_lifecycle_q1_price_volume.py`，全窗 2026-04-15~10-07，
21.5 万序列步/33,743 跨日步；JSON `data/reports/lifecycle-q1-price-volume-diagnosis{,-vr}.json`）：

- **D1 靶子规模**：跨日步占 15.7%（33,743），排名大跳（|Δpct|≥10）≈2.1 万步（可复算：drop 靶 11,334
  + spike 有价格方向 9,075 + spike 价平 ≈443 ≈ 20,852）——非边角料。
- **D2 可填充率**：跨日步价格证据 100% 可用、volumeRatio 口径 77.3% 可用。
- **D3 价格方向分辨力（核心效度）**：跨日排名大跌步价升组后续回升 +5.36 分位点 vs 价跌组 +3.55，
  差 **+2.31 [CI 1.86~2.76]**（code 聚块 bootstrap 10k，seed 20261007）；大升方向 +2.04 显著；
  同日对照 +2.48 同量级=**普适的价×排名时序背离证据**（非跨日特异）。注记：绝对回升含均值回归基线，
  分辨力看差值；fwd 含日内恢复效应。
- **D4 量口径裁定**：amount 粗算量比有日内时点污染（当日累计 vs 昨日尾盘累计基准），**禁用**；
  volumeRatio 干净口径：价升组 1.18 vs 价跌组 0.77，价跌组 p25=0.02 极端缩量左尾（一字板形态）。
- **D5 dv 重叠率（步骤 0）**：Q1 靶子步几乎全部落入 dv 枚举档（A/B/C/D 四态+unknown 档；drop 靶内
  5,459 price_lead_warn + 5,320 confirm_down + 555 unknown）——**Q1 不新造价×排名因子**；
  dv 三缺口=Q1 全部增量（效度未验证→D3 补上 / 权重 0.0 纯观察 / 无量输入）。
- **D6 dv 现状缺陷**：dv 无 temporalGap 防御，跨日步 rankDir=隔夜跳变（18,253 步 rank_down）；
  接线时必须一并修（诊断脚本 dv 复刻自证 430 抽样零 mismatch）。

**预登记合同**：`lifecycle-q1-preregistration.md`（2026-10-07 起草，判定线冻结于跑数前）。
设计要点收窄为三件：**机制一**=gap 帧价量虚拟动量证据（`lifecycleGapPriceVolumeMode` off/direction_gate，
价跌一律 −P、价升须 volumeRatio≥vrGate 放量确认的非对称门——D4 数据形态直接映射；P 分位当量
{3,5,8}×vrGate{1.0,1.5,2.0} 九臂；hot_streak/best/drawdown 不动、acceleration/shock 不伪造、
metrics 增 gapPriceVolumeProxy 来源标记 fail-visible）；**机制二**=dv 效度化接线（前置修 temporalGap
防御 + 权重 {0.25,0.5,0.75} 臂，cs 同量级封顶）。判定=同代际相对线（沿用 G1 容差）+Track1 中性线
+G1 收益侵蚀监控（veto 回升 >3.4pp 相对须显式交裁）+分辨力不反转检验；13 剂量臂冻结，全 FAIL=
阴性结果登记不硬上。流程：合同 → 用户过目 → Opus 审定 → 用户裁决开跑。

**Opus 审定（2026-10-07，有条件通过）→ 合同 v1.1（R1-R9 全落实）→ 用户令「修正后开跑」**：
硬事实逐位核过（D2/D3/D4/D6/D7 全对、算术抽验通过）。必改九项：**R1 注入人群冻结**=跨日步∧
|Δpct|≥10（与 D3 证据人群严格对齐，不做全跨日外推）；**R2 信号面补提交线**=三窗均值 ≥+0.002 且
≥1 窗 ≥+0.003（全臂未达=零效应阴性登记不提交）+负效应线（均值 <−0.003 止损）；**R3** D1 靶数改
可复算口径 ≈2.1 万；**R4** 分辨力不反转线按机制重定义（C-c 臂在注入人群内复算 / C-a 臂不适用）；
**R5** Track1 补 oos2/g1era 披露窗（oos2 <−0.005 须交裁）+maxDD ≤ 基线；**R6** 补考题/成本（14 次
replay ≈1.5h 本地零调用）/harness 清单（evaluate_lifecycle_scale_gap_trials / track1_lifecycle_gate_trade
/ diagnose_lifecycle_q1_price_volume）/市况分桶（market_regime state 仅报告列）/依赖声明（C-11）；
**R7** frozen=midgap∪oos1=全 8 月口径（对账 0.1376/0.0834，语料 §6-I）；**R8** C-c1 字面矛盾修复
（证据可用步 proxy 驱动不沿袭 / 证据缺步维持 G1 沿袭）；**R9** 臂数=13 剂量臂+1 基线臂=14 次 replay。
建议级采纳 6 项（3.4% rel 单位统一/机械化选臂规则/S·A 档计数变化披露/proxy 按 drop·spike 分列/
P 与 lifecycleVelocityMin=18 关系注记——P∈{3,5,8} 均 <18，proxy 不制造高阈值触发、效应走低阈值
路径/golden 措辞对齐）+D5 措辞修正。R2/R4/R5 判定线增补随 v1.1 冻结（当前未跑数，不构成跑后调线）。
**开跑授权（用户 2026-10-07「请按审定回执意见修正，然后开跑」）覆盖=接线→专项测试→trial→判定
→登记→提交；落默认仍须用户裁决（C-4.5）。**

**Q1 trial 收官（2026-10-07 深夜，全臂 FAIL=阴性登记零默认改动；台账 §22）**：合同 v1.1 判定线跑满 15 臂（14 冻结臂+机械化选臂组合臂因 ca_best=None 不触发）。**C-a（dv 权重 0.25/0.5/0.75）三臂全灭**：decision 窗 saEx 相对基线 −0.0095/−0.0202/−0.0301 破无害线、S/A 帧 1229→2079/2812/3683 单调膨胀（+68%~+200%）=「扩档拉动」非判别改善、Track1 wrxpf −0.10~−0.12+maxDD 恶化 4.9-8.0pp——**D3 单帧效度显著 ≠ 进 synergy 投票有增益（稀释+扩容负效应），dv 保持观察位，「效度验证→给权重」路径证伪**。**C-c（direction_gate 九臂）无害线全过、提交线全 FAIL=零效应**：mean 相对改善最高 +0.00136（vr15）< +0.002；Track1 全过（wrxpf −0.0028 容差内、maxDD 22.31%→21.73% 微改善、笔数 172 不变）；veto 侵蚀 +0.46~0.49% << 3.4% 交裁线，翻转分列 added 主落 drop 桶（68%=价跌步 −P 判 reversal 方向正确）、released 85% 人群外=normalize 状态机传导。**两大结构事实**：①P 剂量轴退化（P∈{3,5,8} 读数逐位同——±P 只经符号起作用，recovery 需 accel≥−1.2 而 proxy 步 accel 恒 NaN=红线②结构性代价，+P 点不着点火路径）——未来重开剂量面须先解 accel 置缺与点火判据相容；②gap 补位证据「无害但无效」——价量方向代理能精准挡掉一部分假信号（Track1 亏损微改善）但不足以把判据变准。**Q1 主线闭环**：原料→诊断→预登记→Opus 审定→trial→阴性登记，全程零默认改动、双开关即回基线。runner 跑后修正两 verdict bug（maxDD 负数域直比/flip 分列键反解，读数零影响）；首轮跑完在最终序列化崩掉（flip 记录 tuple 键）Track1 全失重跑一轮=checkpoint 逐臂落盘机制立项理由。
