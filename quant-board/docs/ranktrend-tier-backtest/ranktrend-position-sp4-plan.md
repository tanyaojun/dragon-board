# 仓位管理专项 SP4 实施计划——相位源切换至 jev 同槽序列档（研究态）

**日期**：2026-10-01
**性质**：writing-plans 产出（章程 §3.1 相位源演进条款 + jev 设计文档 §13 授权的实施计划）。
**状态**：待用户放行执行（设计文档修订已完成：hotlist-jev-emotion-observe-design.md §13 相位源授权条款；章程 §3.1 已加演进注记）。
**范围**：① labels v3（jev 派生相位标签，冻结纪律）；② 引擎载体 `source="jev_seq_slot"`（两因子制 + fallback 链）；③ 地图 v3 与北极星口径 v3；④ 脉拍接线；⑤ 10-12 月样本外走廊与晋升。
**非目标**：前日 day_stage 反向课题（显著 p=0.02 方向反转——如需反向信号另立专项验证）；day_temperature 落库补齐（jev 实现侧待办，移交观察轨道）；champion ladder v1 的分数表变更（jev 源用两因子制，独立版本线）；上移加仓（维持否定收口）；提交 SP1-SP3 相关的未决 review 事项。

---

## 证据基线（T-jev 口径对比，产物 jev-phase-caliber.json；956 帧全窗）

| 口径 | nOff/nDef | meanDiff | p | 结论 |
|---|---|---|---|---|
| C1 规则前日分 ≥60（现行） | 269/687 | −0.026% | 0.244 | 帧级无分离力 |
| **C4 jev 同槽 sequence_stage** | 181/774 | **+0.095%** | **0.0013** | 全窗显著、方向正确、8/9 两月连显著 → **相位源候选** |
| C2 jev 前日 day_stage | 543/413 | −0.066% | 0.020 | 方向反转（反向指标），**不作相位源** |

映射（预登记）：start/ferment/climax→offense；ice/retreat→defense。已知边界：LLM 非确定性（同日重放档位可能漂移→标签落库即冻结）；jev 文档缺失/degraded→fallback 链；9 月分歧可见后的选择偏差→样本外硬门槛。

## T1 labels v3：jev 派生相位标签（TDD）

| # | 改动 | 要点 |
|---|---|---|
| T1.1 | 测试先行：`tests/operations/test_jev_phase_label_run.py` | 映射正确性；缺槽/降级/no_data 排除并计数（fail-visible）；`_id` 幂等；冻结 meta（generatedAt/gitCommit/model/jenv 版本） |
| T1.2 | 新 CLI `backend/operations/jev_phase_label_run.py` | 读 `hotlist_jev_sentiment` kind=slot status=ok 的 sequence_stage → 两档映射 → 标签 JSON `{date|slot: offense/defense}` + fallback 段（规则 v2 标签，源标记 source=rules）；产物 `data/reports/phase-monitor/phase-labels-jev-v3.json`；**落库即冻结**（重算=显式 --force 新版本号） |
| T1.3 | fallback 语义（预登记） | jev 标签缺失槽 → 回退规则前日口径标签（labels v2 dailyByPrevDay），标签行带 `source: rules`；归因分源计数 |

**验收**：pytest 全绿；labels v3 覆盖率报告（jev 直读率/回退率逐月）。

## T2 引擎载体：`source="jev_seq_slot"`（两因子制）

| # | 改动 | 要点 |
|---|---|---|
| T2.1 | 测试先行：`tests/backtest/test_phase_jev_source.py` | 三因子解析（offense/defense/unknown）、fallback 链（jev 缺→规则标签→unknown）、golden 锚（无键逐位不变）、归因（entryPhase.source/label/fallback）、同槽 as-of 语义 |
| T2.2 | `execution.py`：`_phase_exposure_factor` 加 `jev_seq_slot` 分支 | config：`{"source": "jev_seq_slot", "phaseLabels": {"date|slot": 两档}, "fallbackLabels": {date: 两档}, "offenseFactor": 1.0, "defenseFactor": 0.3, "unknownFactor": 1.0}`；查 `(date, slotTime)` → 命中按档取因子；未命中→fallbackLabels[date]；再未命中→unknownFactor |
| T2.3 | 归因 | entryPhase.source/label/fallbackUsed 字段（SP1 透传链自动到达成交行） |

**初始臂参数（预登记，依据 C4 证据方向）**：offenseFactor=1.0（序列上行帧级占优）、defenseFactor=0.3（谨慎对齐阶梯③的防守系数）、unknownFactor=1.0（缺标签放行不错杀）。**验收**：`pytest tests/backtest -q` 全绿。

## T3 地图 v3 与北极星口径 v3

- `jev_phase_label_run` 产物喂 `phase_northstar` 变体（或诊断脚本先手）：labels v3 下的分相位北极星角色表 + 帧级分离度，与 v2（规则口径）并列对照；
- `ranktrend-phase-map-baseline.md` 增补 v3 段（v1/v2 对照保留）；
- 台账 jev 行状态更新（候选→在跑走廊）。

**验收**：v3 读数落档，口径切换的成本/收益表（覆盖率、一致率、分离度、角色表）齐全。

## T4 脉拍接线

- `--arm-config` 注入 jev 臂（`source="jev_seq_slot"` + `phaseLabels` 由 labels v3 文件注入——扩展 build_arm_trade_configs 支持从 labels 文件读 phaseLabels/fallbackLabels）；
- 归因分源计数入挑战者行。

**验收**：交易时段外实跑一轮含 jev 臂的脉拍，报告含分源归因。

## T5 样本外走廊与晋升（10-12 月，持续）

- jev 臂 vs champion（ladder v1）逐月 A/B；晋升门槛=章程 §6（≥2 样本外脉拍月同向 + ≥30 笔 + 回撤改善 + 用户终审）；
- tripwire：jev 臂连续 2 月劣于 champion → 自动退池；LLM 档位漂移监测（每月抽 3 日重放比对，漂移率 >10% → 标签冻结完整性告警）；
- 晋升议题（翻默认）届时另立提案。

## 回退风险

- **标签非确定性**：LLM 重放漂移——落库即冻结 + 每月漂移抽检（T5）；
- **jev 源中断**（token 失效/余额/API 故障）：fallback 链到规则口径，体系不停摆；中断日计 fallbackUsed 归因；
- **单窗证据 + 选择偏差**：9 月分歧可见后才提出 jev 候选——样本外走廊是唯一解药，晋升门槛不可协商；
- **接线风险**：新 source 分支与既有 prev_eod/slot_then_prev_eod 互斥由 mode/source 分支保证，golden 锚兜底。

## 执行顺序

T1 → T2 → T3 → T4 → T5（T1 是 T2 的数据前置；全程不碰 jev_client/观察轨道代码；不碰 ladder v1 配置）。

---

**状态头（2026-10-01 执行记录）**：
- **交接**：SP5（jev 日级情绪叙事研究——温度机会轴 × 拥挤风险轴）交接文档已产出 → `ranktrend-position-sp5-plan.md`（含前序结论总账、用户四点裁决、按轴配读数方法论、T1-T5 草案），下一对话以此开启。
- **独立 code review 已完成**（reviewer，结论：无 Blocker，OK with notes）：引擎路径（两因子制/golden 锚/映射/冻结/注入语义）交叉验证成立；Important 1-3 已修复（①attribution_stats jev 分源分支 + sourceAttribution 计数，不再把 jev 笔误计 missing；②schedule 臂清单改为从登记配置回填，删除过期常量；③diagnose_jev_seq_backtest 修复 arms 双重嵌套 bug + 增加自检：归因全零/配置未达模拟器 → 退出码 3 产物标 INVALID）；Minors 已修 P2-4/P2-5，其余（P2-6/7/8/9/10）登记待办不阻塞。
- **事故复盘**：全窗对照首次运行三臂全同，根因 = 诊断脚本 arms 双重嵌套（`{"phaseExposureControl": {"phaseExposureControl": ...}}`）→ 引擎读 mode=None 全部按 off 放行；debug 探针 payloadCtrlKeys=['phaseExposureControl'] 为铁证。并发运行还产生了孤儿进程（Windows 下工具超时不杀子进程），抢核加剧超时——已清理，后续长任务一律 nohup+日志轮询不依赖工具超时。
- **既有对照数字（零重跑，来自 m3-ladder-compare.json / t6 1-summary）**：全窗 baseline 54 笔 sumNetReturn +21.67% maxDD -4.87%；champion ladder③ 34 笔 +26.71% maxDD -3.98%。唯一缺口 = jev_seq_v1 臂全窗读数（单臂 ~15-30 分钟，待用户批准后单独跑）。
- **全窗三臂对照（2026-10-01，进程清查后干净重跑，产物 jev-seq-backtest.json，自检退出码 0）**：baseline 54 笔 +21.67% mdd -4.87%（与 t6 正式基线逐项一致，管线交叉验证）；champion ladder③ 35 笔 +61.56% wr 51.4% PF 1.81 mdd -1.66%（拦 19 笔弱势带，α 集中在拦损）；jev_seq_v1 54 笔 +22.71% mdd -2.46%（全 54 笔 direct 归因，defense 降仓三成：收益 +1.04pp、回撤减半 -2.41pp，增量集中在 5 月 +0.95pp）。champion 支配性最强；jev 首参数组 = 温和回撤缓解器。**对账结论（修正上轮误引）**：此前引用的 m3“decision 34 笔 +26.71%”实为该产物 oos2 样本外子窗数（非全窗）；正式全窗 ladder 证据 = 台账 C7 行“③ 全窗 +49.1% vs 基线 +21.7%”；本轮 +61.56% 与 +49.1% 的残差属 eod 数据代际/harness 差异，三臂内部一致性（同窗同种子同进程）不受影响，jev 对照以本轮为准。诚实边界：jev 标签 in-sample，样本外以 T5 走廊 10 月脉拍为准。
- **9 月短窗三臂对照（2026-10-01，门禁评审 GO 后执行，产物 jev-seq-backtest-sep.json，自检退出码 0）**：窗口 08-20→09-30；baseline 14 笔 -19.12% mdd -4.72%；champion ladder③ 6 笔 -17.71% mdd -1.63%（拦 8 笔弱势带）；jev_seq_v1 14 笔 -19.03% mdd -2.16%（全 direct 归 14/14，defense 0.3 只降仓不拦截）。读数：champion 仍最优（收益+回撤双优）；jev 首参数组（防守三成）以损失 +0.09pp 的代价换来回撤减半（-2.56pp），属温和首读非惊喜；基线 9 月切片 -18.03% 与脉拍完全一致（管线交叉验证）。诚实边界：jev 标签派生自同窗数据（in-sample），样本外以 T5 走廊 10 月脉拍为准。
- **T1 完成**：`backend/operations/jev_phase_label_run.py` + 6 测试；生产产物 `phase-labels-jev-v3.json` v1（1070 标签/113 日，offense 195/defense 875，degraded 1 如实排除；fallback 112 日源=规则 v2 前日口径）；冻结纪律生效（覆写需 --force 版本自增）。
- **T2 完成**：`execution.py` `_jev_phase_factor` 两因子制 + source=jev_seq_slot 分支（分数轴字段置空不伪造；phaseLabel/fallbackUsed 归因仅 jev 源携带）；6 测试含 golden 锚。
- **T3 完成**：帧级分离度证据已存档（jev-phase-caliber.json）；地图台账 T-jev 行更新；v3 角色表读数由 T5 走廊脉拍自然产出。
- **T4 完成**：build_arm_trade_configs jev_labels 注入 + `--jev-labels` 参数（缺失 fail-visible 记入 meta）+ 臂配置换血：jev_seq_v1 上岗（offense 1.0 / defense 0.3 / unknown 1.0），slot_v1 达标收口移入排队档；台账预算测试同步。
- **T5 走廊程序（进行中）**：① 每交易日后 `jev_sentiment_replay --days 1` → 月初 `jev_phase_label_run --force`；② 每月首个交易日跑 `phase_pulse --month YYYY-MM`（臂自动从登记配置读）→ 首读 2026-10；③ 月度漂移抽检（人工程序）；④ 晋升门槛=章程 §6。
- **移交项**：~~day_temperature 落库补齐~~（**勘误关闭**：字段一直在库，eod scores.day_temperature/day_crowding 113/113 全覆盖，T-jev 误诊为读错字段名）；C2 前日 day_stage 反向指标课题；评审 P2-6/7/8/9/10（phaseExitCoupling jev 注记已有 docstring、next_version 损坏归档、逐月覆盖率、多槽同日测试、C4 标定口径注记）。

## 排队候选预登记：jev_band_v1（槽级温度带阶梯，T-jev2 达标产出，2026-10-01）

排序：jev_seq_v1 走廊出结果后顶替上场（挑战者预算 ≤2）。
- **源**：jev 槽文档 `scores.temperature`（同槽 as-of，冻结标签，1070 文档 100% 覆盖）；
- **阈值（冻结自标定窗样本分位数，禁止按月重标定）**：温度 ≤24.9（Q1）→ factor 0.3；>24.9 → 1.0；缺标签 → 1.0 放行（最小干预：只砍证据最弱的冷槽）；
- **证据**：T-jev2 槽温 Q4 vs Q1 +0.206pp p=2e-05（全场最强帧级信号，方向热→强；与 champion 前日水平轴方向相反但共存不矛盾：champion=前日水平防透支，槽温=同槽动量确认）；
- **已知风险**：与规则分 Spearman 0.717（大部分共享信息，增量在同槽时点）；阈值 in-sample；载体需新增 source=jev_temp_band（jev_seq_slot 分带变体，入队时设计实现）；
- **晋升门槛**：章程 §6（≥2 样本外月同向 + ≥30 笔 + 回撤改善 + 用户终审）。
