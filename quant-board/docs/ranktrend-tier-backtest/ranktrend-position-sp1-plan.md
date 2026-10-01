# 仓位管理专项 SP1 实施计划——证据框架工程位

**日期**：2026-10-01
**性质**：writing-plans 产出（章程 `ranktrend-position-management-charter.md` §4 SP1 的任务级计划）。
**状态**：待用户放行执行。
**目标**：① per-trade 归因字段（隔离 runner 侧，golden 逐位不变）；② Q1 定义变更 50→60 落地（§11 清单）；③ 假设族预登记入 C-台账；④ 标签重打 + 地图重算 v2 仪式。
**非目标**：SP2 出场耦合/动态调仓实现；SP3 2D ladder；任何默认值变更（ladder champion v1 不动）；`todayAdvice` 阶梯文案（40/60 独立版本线不动）；重导 frames 之外的数据工程。

---

## T1 定义变更 50→60（二档 offense≥60 / defense<60）

TDD 顺序：先改测试期望，再改实现。

| # | 文件 | 改动 |
|---|---|---|
| T1.1 | `quant-board/tests/hotlist/test_hotlist_sentiment_phase_history.py` | 期望 threshold==60.0；补边界用例（59.9→defense、60→offense） |
| T1.2 | `quant-board/backend/operations/phase_label_run.py` | `CANDIDATES["sentiment_2b"]` = `{"hi": 60.0, "lo": 60.0}`；docstring「hi=50/lo=50」同步 + 注记「2026-10-01 章程 Q1 裁决：边界 50→60，与四带强带下沿嵌套对齐」 |
| T1.3 | `quant-board/backend/operations/phase_pulse.py` | `PULSE_THRESHOLD = 60.0`（口径源注释同步） |
| T1.4 | `quant-board/backend/api/hotlist_routes.py` | `_PHASE_THRESHOLD = 60.0` + 注释更新（M2 裁决定义行） |
| T1.5 | `quant-board/backend/core/backtest/execution.py` | `reduce_offense/reduce_defense` 分支默认 `threshold` 50.0→60.0（口径一致；研究开关默认 off，golden 不受影响）；`tests/backtest/test_phase_exposure_control.py` 对应用例同批更新 |
| T1.6 | 根前端 `src/components/panels/HotlistEmotionPanel.vue` | `PHASE_THRESHOLD = 50`→`60`（~L2403，口径锚注释同改）；L536 文案「≥50 进攻/<50 防守」→「≥60 进攻/<60 防守」；`src/types/phaseMonitor.ts` L3 口径锚注释；`src/services/hotlist/__tests__/phaseApi.test.ts` mock threshold 60.0 |

**验收**：
```powershell
cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/hotlist tests/backtest/test_phase_exposure_control.py -q
cd d:\dragon-board; pnpm test; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

## T2 per-trade 归因字段（引擎 + 脉拍，golden 逐位不变）

| # | 改动 | 要点 |
|---|---|---|
| T2.1 | `execution.py`：抽 `_phase_context(ctrl, trading_date) -> dict` | 返回 `{prevDate, prevScore, prev2Score, deltaScore, phase, band, factor}`；`_phase_exposure_factor` 保持原签名改为薄包装（既有测试不破）；**mode=off 也解析 prevScore/prev2Score**（eodScores 缺失→null，fail-visible 不伪造）；deltaScore=前日分−前前日分（任一缺失→null）；band 四带标签（冷/弱/强/极热，按 10-40/40-60/60-80/≥80，分数缺失→null） |
| T2.2 | 买入建仓 position dict 增 `entryPhase` 子文档 | `{factor, prevDate, prevScore, deltaScore, band, phase}`（ctrl 缺失且无 eodScores→整字段 null）；`entryAtr`：`useAtrStops` 历史可用时记入场时 ATR，否则 null（跟随 `exitTpMultiplier` 先例，L407 一带） |
| T2.3 | 卖出 trade dict（L345）与 trade_events（L347）拷贝 `entryPhase`/`entryAtr` | 字段从 pos 透传 |
| T2.4 | `_round_trip_trades` 无需改 | `**first` 展开自动携带；openPositions 天然携带 |
| T2.5 | `phase_pulse.py`：基线臂 trade_config 注入 `{"phaseExposureControl": {"mode": "off", "eodScores": {...}}}` | mode=off → factor 恒 1.0，**行为与空 config 逐位相同**（硬断言测试锚）；报告新增 `attribution` 段：`{availableTrades, missingEntryPhase, byBand: {band: {trades, factorSet}}, byPhase}`；A/B 两臂归因同装配。注：dryRun 隔离 runner，config 多键仅影响 run 溯源 hash 不影响生产 |
| T2.6 | 新增 `tests/backtest/test_phase_attribution.py`（TDD 先写） | ① off+eodScores vs 空 config：roundTripTrades 逐位相同（golden 锚，除 entryPhase 字段本身）；② ladder 臂：entryPhase.factor/band 正确（40-60 阻断笔不产生 trade；60+ 笔 factor=0.3）；③ 缺前日分→prevScore=null 交易照常；④ trade_events/openPositions 携带；⑤ deltaScore 正确性与缺失路径；⑥ pulse attribution 段装配（复用 build_pulse_report 单测模式） |

**验收**：
```powershell
cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/backtest -q   # 132 回归基线全绿
```

## T3 重打标签 + 地图重算仪式（操作步，依赖 T1；交易时段外执行）

1. 重导扩窗 frames gzip：`tmp-exit-frames-export.py`（git b251cf1c 恢复临时副本），dataset/snap_type/end=执行当日（M1 报告 §2.5 扩窗执行序：不得只重跑检验脚本）；
2. `python -m backend.operations.phase_label_run --frames <新gz> --out data/reports/phase-monitor/phase-labels-v2.json`；
3. `python -m backend.operations.phase_northstar --labels <v2> --out .../phase-northstar-v2.json`（thresholds 从 labels 读，T1.2 自动生效）；
4. `ranktrend-phase-map-baseline.md` 升 v2：定义行改 60、保留 v1 对照段（注明旧读数基于 50 边界）、转录 v2 关键读数 + meta（generatedAt/gitCommit/帧数）；
5. C-台账读数重述：C1（进攻相位降仓）offense 段笔数/收益按新边界重述，旧值注记保留。

**验收**：labels-v2 meta 完整、月度帧分布转录；northstar-v2 与 v1 的差异段（offense/defense 笔数迁移量）在地图 v2 文档可见。

## T4 假设族预登记（文档步）

`ranktrend-phase-map-baseline.md` §6 新增「仓位专项假设族（章程 §5 challenger 池）」小节，初始登记（全部 pending，同时在跑 ≤2）：

| 登记号 | 臂 | 依据窗证据 | 预期裁决窗 |
|---|---|---|---|
| SP2-EXIT-strong-tighten | 强带 60-80 出场收紧（TP/BE/持有） | 分带机制（强带 +1.01%/笔、退出以最大持有为主） | 2026-10/11 脉拍 |
| SP2-REBAL-v1 | 持仓中带下移减仓（只减不加；强/极热→弱=减半、→冷=清仓、冷带豁免） | folk 兑现 + Baker-Wurgler 情绪高位后续收益差 | 2026-10/11 脉拍 |
| SP3-LADDER-2D | 水平带×Δ 双维阶梯 v2 | P2-b 二维矩阵（L低×升 +3.68%） | 2026-11+ |
| SP4-VOL-SIM | vol 轴 frame-level 模拟（观察池，不出开关） | Moreira-Muir（正）/Cederburg（反） | 报告制 |
| （已在跑）C6/C7/C8 | 弱势带回避 / ladder③ / cold_tp_widen | 台账既有 | 照旧 |

**验收**：小节落盘且与章程 §4/§5 一致。

## T5 收口验证

```powershell
cd quant-board; .\.venv\Scripts\python.exe -m pytest          # 全量
cd d:\dragon-board; pnpm test; pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
# 交易时段外试跑一轮脉拍验证归因段实际产出（dryRun 隔离进程）：
cd quant-board; .\.venv\Scripts\python.exe -m backend.operations.phase_pulse --month 2026-10
```

四文件同步：章程状态头（SP1 状态）、地图台账（v2 + 假设族）、本计划状态头、月度监控说明（若 T3 发现 labelsFresh 逻辑受影响则同批更新）。

## 回退风险与顺序

- **执行顺序**：T1 → T2 → T3 → T4 → T5（T1/T2 代码面相互独立，T3 依赖 T1，T4 纯文档随时）。
- **回退**：T1=常量还原 + 标签重打（幂等）；T2=引擎改动有 golden 锚测试（off+eodScores 逐位相同）兜底，回退=移除字段透传；T3 产物本地易失不进 git，文档转录是唯一持久面——回退时地图文档 v1 段仍在。
- **风险注记**：T1.5 改 reduce_* 默认阈值只影响未显式传 threshold 的研究臂（生产默认 off 无影响）；T2.5 基线臂注入 eodScores 改变 run 溯源 hash（dryRun 隔离口径，报告 meta 已带 trade_config 说明）；脉拍 A/B 与归因装配失败走既有 degraded 路径不阻断基线读数。

---

**状态头**：SP1 已执行完毕（2026-10-01）——T1 定义 50→60 六面落地（后端 246 passed + 根前端 1130 passed + vue-tsc 0 错）；T2 归因字段落地（entryPhase/entryAtr 透传 + golden 锚，tests/backtest 151 passed）；T3 仪式完成：labels-v2（1071 帧全 113 日，offense 226/defense 845）+ northstar-v2（offense@60 +3.67%/16 笔未过，defense@60 +18.0%/38 笔双项过）+ 地图基线升 v2 保留 v1 对照；**注：国庆假期无新交易数据，frames 复用 v1 同源 gz 未重导**；T4 假设族预登记落地图基线 §7；T5 收口：目标面 388 passed + 脉拍 2026-09 实跑验证归因段端到端（基线 11 笔/ladder 臂 4 笔全带标签，缺失 0；A/B 读数与台账 9 月首点一致 −18.03%→−12.53%）。**全量 pytest 的 30 个先存历史失败已收口（2026-10-01，worker 子代理 + 父代理收尾）：29 个由 worker 修（14 个测试文件，零生产代码：锚单一源断言+gen7 值哨兵 / 票值算术冻结夹具沿 eabf4b44 先例 / floor3 边界同步）；第 30 个（golden 对齐）由父代理重建快照收口——diff 审查 35 处差异全部落在四个已解释来源（gen7 三默认足迹 29 + SP1 entryAtr/entryPhase null 键 6），零未解释漂移。全量终态 2995 passed / 0 failed。**未提交，待用户 review。**评审已回（2026-10-01，独立 reviewer 子代理）：可保留、无 Critical；Important#1（_phase_context 缺分日回跳与 factor 严格前日语义分歧）已修（严格前日键 + prevDate 锚日总落盘 + byPhase 补齐 + golden 锚扩 tradeEvents/权益曲线 + 阻断笔用例，tests/backtest 153 passed）；Minor 6 项已全部处置（northstar 参数化/quality+trade_slice --out 升 v2/注释口径/ab_compare docstring）。**
