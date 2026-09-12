# RankTrend 生命周期分层合同

## 目标

RankTrend 主表展示必须区分三件事：

1. 生命周期候选分层：由历史排名轨迹、技术动量、市场环境和资金背离风险计算。
2. 展示状态：由后端 `compute_display_status` 独家生产（lifecycle.stage 主轴 + 样本/资金/风险修正层），前端只消费不分类。
3. 实时风险：由当前涨幅、量比、换手和资金状态触发，不应覆盖生命周期原始结论。

## 分层含义

### 生命周期候选分层

- `A_MAIN`：主升候选。表示排名轨迹进入扩散阶段，中周期动量和技术信号成立。
- `B_IGNITION`：点火候选。表示短周期注意力开始启动，但仍需后续快照确认扩散。
- `C_CROWDED`：拥挤候选。表示长期热度高位或生命周期拥挤。
- `D_EXIT_RISK`：退出风险。表示注意力或资金进入转弱路径。
- `N_NEUTRAL`：中性观察。表示未形成明确机会或风险分层。

### 展示状态（2026-09-10 二次口径统一：displayStatus 退役为 stage 纯投影）

> ⚠️ 本节取代同日早先的"8 类级联"口径（旧方案见 `docs/superpowers/specs/2026-09-10-display-status-lifecycle-alignment-design.md` §3，**已废弃**）。
> 生效契约：`docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`。

展示状态由后端 `compute_display_status` 独家生产，且**只是 `cycle.stage` 的投影**：

```json
{ "stage": "crowded", "label": "拥挤", "tooltip": "注意力拥挤高位，追高风险上升。" }
```

- `stage ∈ {ignition, expansion, crowded, reversal, cooling}` 或 `null`（缺失/非法）；
- `label ≡ STAGE_LABELS[stage]`（**后端单源词表**：点火 / 扩散 / 拥挤 / 反转 / 冷却），`stage=null` → `无阶段`；
- cooling 且强资金 + 量能承接 → **仅 tooltip 追加**"资金承接仍强。"，**不改变 label/stage、不进任何计数**；
- **没有分类层**：不存在 8 类 label/classKey/`RISK_LABELS`/`RISK_CLASS_KEYS`，不存在样本门/风险修正层/兜底类。

**为什么删除分类层**（spec §10.1 论证 + 实测）：978 帧 / 220,736 行证明 8 类**无法反推** stage ——
`样本不足` 跨 4 个 stage、`转弱预警` 跨 3 个，而 `主升确认`/`资金背离`/`新入观察` 从未出现；
即 8 类的信息量**低于** 5 态。把一等字段（`cycle.stage` / `synergy.state` / `meta.sampleQuality` /
`zlje`+`signalTier`）复制成第二套状态分类就是病灶本身。

**计数与恒等式**（替代旧"对账关系"，`quant-board/tests/test_display_status_reconciliation.py`）：

```
stageCounts:        { ignition, expansion, crowded, reversal, cooling, unknown }
statusSourceCounts: { displayStatus, fallback }
```

- 恒等式：`sum(stageCounts) == 全池行数`；每行 `label == STAGE_LABELS[cycle.stage]`；
- `unknown` = stage 缺失/非法（含 analyze 未产出、由 `_insufficient_entries` 补的"无阶段"行），
  **以及 fallback 行的展示桶**——无投影记录的行一律归 `unknown` 桶（2026-09-12 code review 修正：
  `derive_fallback_row_signals` 启发式判出的 crowded/cooling 只作规则输入，不进展示分布，
  `statusSourceCounts` 也必须计 `fallback` 而非 `displayStatus`）；
- **样本质量差的股票计入其 stage 桶**，不从分布里挖掉；质量由周期列灰框
  （`meta.sampleQuality.status === 'insufficient'`）承载；
- `stageMissing` 计数**已删除**（分类层消亡）—— 阶段缺失直接体现为 `stageCounts.unknown`；
- 旧 `statusCounts`（8 类）字段已删除，读口不做兼容（唯一消费者是自家前端，同批改完）。

**规则引擎的等价内联（用户裁决 B1）**：`backend/analysis/hotlist/sentiment.py` 仍需「昨强 / 强资 / 拥挤 / 风险」
四个业务判据。它们不再叫分类，但**判据逐条等价**：

| 旧 8 类 | 现在的等价判据 |
| --- | --- |
| 强资确认 | `stage == cooling` 且强资金（`zlje>0 且 zljzb≥8`）且量能承接（`signalTier ∈ {A,B}`） |
| 高位拥挤 | `stage == crowded` |
| 转弱预警 / 资金背离 | `stage == reversal`，或 `cooling` 且非强资，或资金背离（`synergy.state=存疑 且 zljzb≤0`） |
| 昨强（主升确认+点火观察+强资确认） | `stage ∈ {ignition, expansion}` 或强资判据 |
| 新入观察 / 样本不足 | `unknown`（旧口径里两者都不是 lifecycle 阶段） |

无 join 记录时（golden fixture 这类只有行情字段的输入）由 `derive_fallback_row_signals` 按上表等价补齐；
因此规则输出（`stage` / `riskLevel` / `signals` / `warnings` / `confidence`）与旧口径**完全一致**。
**桶位与规则输入解耦**（2026-09-12 code review 修正）：fallback 行的展示桶归 `unknown`，
启发式判出的 crowded/cooling 仍按判据进 `crowdedShare` / `strongMoneyShare`（B1 等价不受影响）；
`strongMoneyShare` 按构造 ⊆ cooling 判定行（`derive_row_flags` 与计量层双重 `stage == cooling` 门控），
保证 `activeOpportunityShare = ignition + expansion + 强资` 对同一行不双计。
`signals`/`warnings` 的**文案**仍含旧措辞（如"强资确认与点火观察…"），本轮不动（纯展示文本、不参与判据）。

**fallback 与 unknown 的区别**：`statusSourceCounts.fallback` = 该行**没有任何 `displayStatus` 投影记录**
（旧缓存/离线）；`unknown` = 有投影但 stage 缺失。两者都 fail-visible，不隐藏、不伪装。

**历史口径混排（U2-b，仍然适用）**：`snapshot_analysis.displayStatus` / `hotlist_sentiment` EOD 是逐帧落库的
历史值，改造后需重跑（`snapshot-analysis-backfill --apply` + `hotlist-sentiment-recompute --days 0 --apply`）；
未重算的历史帧仍带旧结构，跨缓存对比不可比。

后端缺失（旧缓存/离线）时前端展示 `未知`（classKey `stage-none`），不伪造本地结论。

### 实时风险

**已随分类层删除**（2026-09-10）：`getRankTrendDisplayBreakdown().riskLabel` 现固定为 `'--'`。
风险不再由展示层二次分类表达 —— 周期列显示 `cycle.stage` 的对应词，行内 tooltip 提供 stage 说明与
（cooling 且强资金承接时的）资金承接提示。

实时风险只解释当前交易状态，不代表生命周期分层已经反转。

## 主表展示口径

主表【状态】优先展示生命周期候选标签，例如：

- `主升候选`
- `点火候选`
- `拥挤候选`
- `退出风险`
- `中性观察`

tooltip 必须同时展示：

- 样本质量
- 周期阶段
- 生命周期标签
- 原始分层 key
- 展示状态
- 实时风险

例如：`A_MAIN + 高位拥挤风险` 应解释为“仍是主升候选，但当前追高风险较高”，不能简单理解为主升失效。

## 数据链路约束

`/api/ranktrend/rank-series` 只返回历史排名序列，不返回历史资金、量比和题材字段。因此：

- 生命周期轨迹只基于历史排名序列。
- 当前资金和量能只参与展示状态与实时风险。
- 不能用展示状态是否为 `主升确认` 判断历史上是否出现过 `A_MAIN`。

QuantBoard frame bundle 必须同时提供：

- `rows`
- `hotlist`
- `stocks`

其中 `stocks` 与 `rows/hotlist` 同步，供 Python 回测和 RankTrend 回放引擎消费。
