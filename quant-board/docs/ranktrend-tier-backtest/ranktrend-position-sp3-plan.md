# 仓位管理专项 SP3 实施计划——入场节点精化（2D 阶梯 / slot 级 as-of / 转折点披露）

**日期**：2026-10-01
**性质**：writing-plans 产出（章程 `ranktrend-position-management-charter.md` §4 SP3 的任务级计划）。
**状态**：待用户放行执行（前置：SP1+SP2 已实现并通过脉拍实测，工作区未提交待 review——提交拆分由用户另行决定，不阻塞本计划评审）。
**范围**：① SP2 遗留观察臂执行（SP2-REBAL-ADD-OBS）；② 2D 节点表（水平带×Δ 方向）证据重推导 → 达标才建 ladder2d 载体；③ slot 级 as-of 情绪增量检验 → 达标才建 source 开关；④ 转折点 corroborate 披露（只读，不作控制面）；⑤ 脉拍接线与收口。
**非目标**：上移加仓引擎化（SP2-REBAL-ADD-OBS 证据达标才另立提案）；champion ladder v1 变更（2D 是新版本线，同期只动一条）；任何默认值翻开关；转折点进控制面。

---

## 代码/数据事实基线（2026-10-01 核实）

| 事实 | 位置/来源 | SP3 含义 |
|---|---|---|
| Δscore 已入归因：`entryPhase.deltaScore`（前日分−前前日分，严格前日链，任一缺失→None） | execution.py `_phase_context` | 2D 的 Δ 维数据已随每笔成交行落盘 |
| 四带解析已单一源：`_band_of_score` | execution.py | 2D 键构造复用 |
| ladder 载体只认分数单维：`ladder: [[上界, factor]...]` | execution.py `_phase_exposure_factor` | 2D 需新 mode（`ladder2d`），不动 1d 语义 |
| hotlist_sentiment 每 slot 一档：09:30–15:00 十档 + EOD，均带 `emotionScore` + `stageConfirmState` | Mongo（9 月实测） | slot 级 as-of 数据就绪；确认状态可作披露 |
| 脉拍只装 EOD：`load_eod_scores` 过滤 `slotTime: "EOD"` | phase_pulse.py | slot 级需新装载器（体积 113 日×10 档，注入可控） |
| limitSummary 在 15:30 日帧（炸板=failed/冲板=rushing/回落=drawdown、涨停池枚举）；**11 个回退日 15:00 帧无 limitSummary** | diagnose_theme_rotation_r1.py 先例 | 转折点数据源；缺帧 insufficient 计数（fail-visible 先例） |
| P2-b 证据边界：「L低×升 +3.68%」是**入场时点**矩阵，基于旧 50 边界 | M4 提案 §2/p2-analysis.json | 2D 必须按 v2 边界 + Δ 全量重推导，不得复用旧矩阵定 cell |

## T0 SP2 遗留：上移加仓观察臂执行（SP2-REBAL-ADD-OBS）

编写并运行 `backend/operations/diagnose_band_upgrade_add.py`（SP2 计划 T2.4 已登记未执行，如实承接）：

- 口径：54 笔基线 roundTrip × labels-v2 带路径——「入场带=冷10-40 且持仓期当前帧带升入 强60-80/极热≥80」段 vs 「入场冷带未升级」段的 forward 收益（帧级池等权 + 交易层双口径）；
- 判据（预登记）：升级段 forward 期望显著为正且 ≥ 未升级对照（Mann-Whitney 或均值差，沿 phase_quality_report 口径）→ 才允许 SP4 提出上移加仓引擎提案；不达标 = 否定结论入档；
- 产物：`data/reports/phase-monitor/band-upgrade-add.json` + 结论转录地图基线 §7。

**验收**：脚本可复跑、产物落盘、台账行更新。

## T1 2D 矩阵重推导（证据门，不建载体）

编写 `backend/operations/diagnose_phase_2d_matrix.py`（只读，沿 downgrade-rule-variants 惯例）：

- 维度：水平带（v2 四带，前日定相）× Δ 方向（`deltaScore = prev − prev2`，严格前日链；`up: Δ ≥ deltaUpMin`，`down: 其余`；诊断输出 Δ∈{0, 5, 10, 15} 多阈值切分供选型）；
- 双口径：帧级池等权 forward return（主证据，1071+ 帧）+ 交易层 54 笔（方向确认）；
- 逐月分解（≥2 独立月同向为预登记门槛）+ 全窗 Mann-Whitney/均值差（沿 phase_quality_report 规则）。

**里程碑门（预登记，章程 §1「不硬造」）**：存在 ≥1 个 (带,Δ) cell 满足「双月同向 ∧（p<0.05 ∨ 均值差 ≥2%）」→ 产出 cell 表提案（因子一次一档）进台账并解锁 T2；**全部不达标 = SP3 以否定结论收口**（T2 不动工，这是正式产出不是失败）。

**验收**：产物 JSON + 月度分解表落盘；cell 表提案（或不达标结论）写入地图基线 §7。

## T2 ladder2d 载体（gate：T1 达标）

```python
trade_config["phaseExposureControl"] = {
    "mode": "ladder2d",   # 与 ladder 互斥（mode 二选一，同键不同值）
    "cells": {"强60-80|up": 1.0, "强60-80|down": 0.3, ...},   # 键=T1 预登记 cell 表
    "deltaUpMin": 0.0,    # up 判定阈（T1 选型后冻结）
    "fallbackLadder": [[40, 1.0], [60, 0.0], [999, 0.3]],     # 缺分/缺 prev2/未命中 cell 时回退 1d 阶梯
    "eodScores": {...},
}
```

| # | 改动 | 要点 |
|---|---|---|
| T2.1 | 测试先行：`tests/backtest/test_phase_ladder2d.py` | cell 命中/未命中回退 fallbackLadder/缺 prev2 回退/夹界 [0,1]/mode 互斥/与 ladder1d 同配置不串扰；**golden 锚：无键逐位不变**；归因断言（entryPhase.ladderKey） |
| T2.2 | `execution.py`：`_phase_exposure_factor` 加 ladder2d 分支 | band=`_band_of_score(prev)`、delta=prev−prev2（严格前日链，prev2 缺→回退）、key 命中 cells→factor，未命中→fallbackLadder 解析；**`_phase_context` 增加 `ladderKey` 字段**（ladder/ladder2d 命中键，供脉拍分 cell 统计） |
| T2.3 | 归因联动 | entryPhase.ladderKey 随 SP1 透传链自动到达成交行；attribution_stats 增 `byLadderKey` 计数 |

**验收**：`pytest tests/backtest -q` 全绿（既有 ladder ③ 全部测试不破）。

## T3 slot 级 as-of 增量检验（证据先行，载体后置）

T3.1 诊断：`backend/operations/diagnose_slot_asof.py`（只读）——装载全 slot 文档，对每个入场帧 (date, slot) 取同日严格更早最近档 score（`slot_then_prev_eod`：同日无档回退前日 EOD），对比 prev-EOD 口径的定相差异率 + 两口径帧级 forward 区分度（逐月）。

**里程碑门**：slot 口径区分度不劣于 prev-EOD 且至少一月显著更优 → 解锁 T3.2；否则否定结论收口（M1 lag=−1「跟随确认」形态下此路可能本就不成立，诚实记录）。

T3.2 载体（gate：T3.1 达标）：`phaseExposureControl.source: "prev_eod"（默认）|"slot_then_prev_eod"` + `slotScores: {date: {slot: score}}`；分数解析统一走 `_strict_prev_score` 形态的 slot 感知版本；归因 entryPhase 增 `source/usedSlot`；脉拍装载器扩 slot 文档。

**验收**：T3.1 产物 + （若达标）pytest 全绿 + golden 锚。

## T4 转折点 corroborate 披露（只读，随时可做）

`backend/operations/diagnose_phase_turning_points.py`：limitSummary（15:30 帧优先，15:00 回退，缺帧 insufficient 计数——沿 diagnose_theme_rotation_r1 先例）逐日导出 炸板率/最高连板/涨停家数 → 与带转移日（→弱/→冷，自 downgrade-rule-variants 行数据）对齐，统计转移前 1-3 日指标读数 vs 常态基线。

- **披露不控制**：结论字段进脉拍报告 `turningPoints` 段（后端 only，前端本期不加）；章程 §3.3 节点语义的 corroborate 输入，供阶梯边界/双确认条款的证据补充；
- **验收**：产物 JSON + 地图基线 §7 附一行结论（如「炸板率>40% 前置 →冷 转移 X/Y 次」或 insufficient）。

## T5 脉拍接线与收口

- `--arm-config` 注入 ladder2d/slot 臂（配置经既有注入器自动携带 eodScores/slotScores）；归因 byLadderKey 进挑战者行；
- 收口：quant-board 全量 pytest + 根前端 pnpm test + vue-tsc + 交易时段外实跑一轮多臂脉拍；
- 四文件同步：章程状态头、地图台账、本计划状态头、（若 T3 达标）月度监控说明。

## 回退风险

- **T1/T3 证据门是本计划的主保护**：两处都可能否定收口（不建载体），禁止门未过先写引擎代码；
- **T2**：ladder2d 与 1d 同键不同 mode，互斥由解析分支保证；回退=无键即旁路；fallbackLadder 保证缺数据时退化到 champion 行为；
- **T3**：slotScores 注入体积（~1200 键）远小于优化任务载荷，资源纪律不变；slot 文档缺档回退 prev-EOD（fail-visible 计数）；
- **T4**：纯只读诊断，零引擎风险。

## 执行顺序

T0（独立，可立即）→ T1（证据）→ 门 → T2 → T3.1（证据）→ 门 → T3.2 → T4（独立）→ T5。T1 与 T0 可并行；T2 动 execution.py 期间不并行其他引擎改动（写冲突纪律）。

---

**状态头**：T0-T5 全部未启动；SP2-REBAL-ADD-OBS 与 2D 证据门是本计划两个预定收口点（否定结论同样是正式产出）；放行后按序执行，每任务完成在本行追加记录。
