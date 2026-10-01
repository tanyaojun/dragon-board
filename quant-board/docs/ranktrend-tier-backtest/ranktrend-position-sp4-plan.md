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
- **T1 完成**：`backend/operations/jev_phase_label_run.py` + 5 测试；生产产物 `phase-labels-jev-v3.json` v1（1070 标签/113 日，offense 195/defense 875，degraded 1 如实排除；fallback 112 日源=规则 v2 前日口径）；冻结纪律生效（覆写需 --force 版本自增）。
- **T2 完成**：`execution.py` `_jev_phase_factor` 两因子制（phaseLabels 直读 → fallbackLabels[date] → unknownFactor 放行）+ `_phase_exposure_factor`/`_phase_context` source=jev_seq_slot 分支（分数轴字段置空不伪造；phaseLabel/fallbackUsed 归因仅 jev 源携带，其他 source 逐位不变）；6 测试含 golden 锚。
- **T3 完成**：帧级分离度证据已存档（jev-phase-caliber.json）；地图台账 T-jev 行更新为 SP4 已落地；v3 角色表读数由 T5 走廊脉拍自然产出（attribution 分源）。
- **T4 完成**：`build_arm_trade_configs` jev_labels 注入（配置内键优先、文件覆盖，同 slotScores 语义）+ `--jev-labels` 参数（缺失 fail-visible 记入 meta）+ 臂配置换血：**jev_seq_v1 上岗（offense 1.0 / defense 0.3 / unknown 1.0），slot_v1 达标收口移入排队档（与 rebal_v1 同队）**；台账预算测试同步更新。
- **T5 走廊程序（进行中）**：① 每交易日后跑 `jev_sentiment_replay --days 1` 积累当日 jev 文档 → 月初重跑 `jev_phase_label_run --force` 版本自增；② 每月首个交易日跑 `phase_pulse --month YYYY-MM`（ Arms=baseline,champion,exit_v1,jev_seq_v1 自动从登记配置读）→ 首读 2026-10；③ 月度漂移抽检：抽 3 日用 evaluate API 重算与落库 sequence_stage 比对，漂移率 >10% 告警（人工程序，暂不建自动化）；④ 晋升门槛=章程 §6（≥2 样本外月同向 + ≥30 笔 + 回撤改善 + 用户终审），jev 臂连续 2 月劣于 champion 自动退池。
- **移交项**：day_temperature 落库补齐（jev 观察轨道待办）；C2 前日 day_stage 反向指标课题（如需反向信号另立验证）。
