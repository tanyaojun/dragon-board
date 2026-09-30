# RankTrend 202610 复跑批次方案（B-202610）

**分册登记（2026-09-27）**：本批扩展为两波总方案——**Wave 2 = ThemeTrend 终判分册**（`docs/theme-module/2026-09-27-themetrend-october-batch-plan.md`，约 10 月下旬，消费 09-28 起 theme 域未消费帧，与本批 oos2u 止于 09-30 无冲突）。两域共享批次日历 / 数据落地检查点 / 资源纪律 / 消费台账 / 产物格式（总方案 §7.7 等条款对分册同样生效），判定口径与候选集按域分册不合并。

**状态**：口径已裁决（A2/B13 定案）。**✅ 正式复跑已于 2026-09-30 完成（用户裁决提前于原定 10/3 执行）**——9 月最后交易日收盘后确认数据前提（9 月全月 206 帧/21 交易日 + EOD 情绪齐）后按 §9.5 执行序全量跑毕；正式读数与裁决见长测文档**阶段 27** + 批次报告 `data/reports/b-202610/batch-summary-formal.md`（各 `*-formal.json`）；核心结论：第四代正式四窗锚 decision 0.1323/oos1 0.0862/oos2 0.0841/oos2u 0.0534（passHard 全 True，注册表 accedac2）；R1-R6 全部保持；O3 vsB_070 PASS_CANDIDATE 进用户决策队列；N8 floor3 落默认提案条件具备；O6 x30 提案重出（C4 待补）；N1 vr 紧侧 monitor_only 立项建议；O7/O8/O10 维持挂起。
**2026-09-25 演练存档**：9 月尚余 09-28/29/30 三个交易日（此前"9/24 为最后交易日"系误记），演练以"数据质量门禁检查 + 引擎性能验证 + 历史遗留问题处理"为目标完成 T1-T6；演练读数中 decision/oos1 为封闭窗（正式跑逐位复现确认），oos2/oos2u 占位读数已由正式全月读数取代。
**2026-09-25 增补**：批次清单扩充——新增 R6 / O9-O11 / N8-N14 与阶段 0 前置修复（0.4-0.6）。来源 = 9/16 方案定稿后 9/17-9/25 四条证据线（卖点扫描阶段 A/B 收口、harness 39 文件审计、P_repool 中期扫描、引擎性能优化收口）+ L1 台账缺口核对，增补依据与明确排除项见 §9；观察池 YAML 已同步登记。
**性质**：系统性复跑方案——终结"边开发边回测"的碎片化模式。本批**零默认值预判、零代码结构改动**，全部产出为判定与登记；唯一允许的代码动作是 harness 的 trial 行追加（前置修复 0.4 属守卫/口径修正，不改引擎行为）。
**事实源**：`ranktrend-longterm-backtest-plan.md` 阶段 0-26 写入的结论与锚读数（本方案不依赖 `data/reports/` 本地报告产物）。
**统一流程**：`skills/ranktrend-signal-research/SKILL.md`（合并原 `ranktrend-tier-longterm-test` 与 `four-dim-algorithm-research`）。

## 1. 批次定位

阶段 0-26 的实践模式是"开发一个 harness → 跑一批 → 写一个阶段"，判定口径散落在 16 处"遗留与复核触发"小节。2026-09-15 Jump 确认门修复（§26.7）使生产默认整体迁移到新代际——全部已落默认项与观察池候选的既有证据都属于断线代际，10 月复跑实质是**新代际上的全量重审**，正好作为批次化复跑模式的第一个批次。

批次目标（三件事）：

1. 在 Jump 修复新代际上完成**已落默认栈复核 + 观察池裁决 + 待立项评估**；
2. 产出**单一批次判定报告**（不再逐 harness 散落）；
3. 首次落盘**锚注册表 + 结构化观察池**（平台化最小集，见 §8）。

## 2. 口径裁决（本轮定案）

### 2.1 A2 复跑窗口口径

依据：§21.6"10 月上旬以 9 月全月为窗口复验（Track 2 判定卡）"、§25.6.4/§26.10.6 窗口消费折扣（M3）"最终裁决窗用 09-13 之后未消费帧"、§14.1 warm-up 口径（`get_technical_min_samples`≥30 → 前 29 帧不产出信号，引擎设计行为非数据缺失）。

| 项 | 裁决 |
|---|---|
| oos2 主窗 | **2026-09-01 ~ 09-30（half_hour 全月）**，与文档"9 月全月复验"表述一致 |
| oos2u 裁决子窗 | **2026-09-13 ~ 09-30（未消费帧）**，oos2 的内嵌子窗（非独立第三窗） |
| 判定读数 | 判定卡 OOS 判定读数**以 oos2u 为准**；oos2 全月读数带"含已消费帧"折扣标记作参考披露；两者冲突以 oos2u 为准并在批次报告标注 |
| warm-up | 9 月窗前 29 帧不产出信号，不计判定样本；批次报告披露有效帧数/交易日数（判定卡 C2 样本量披露项） |
| 槽位情绪缺口 | 9/1-9/2 无槽位情绪文档（EOD stale 回退）帧**不剔除、打标记**（fail-visible，不阻断） |
| **oos2u 消费禁令** | **自 2026-09-16 起生效**：09-13 之后产生的帧为最终裁决窗，除本批次执行外不得对其跑结论性扫描（只读数据质量盘点不受限）；jump-fix baseline（9/15，oos2 口径至 09-12）未触及这些帧，当前严格未消费 |
| 其余窗口 | decision = 04-15~07-31（655 帧）、oos1 = 08-15~08-31、8 月 FINAL（08-01~08-14）冻结纪律均不变，`assert_not_frozen` 无条件执行 |

### 2.2 B13 双强共振统计口径

依据：§15.4 正式判定"缺复核"（三窗有效样本 283 < 触发线 500；方向证据不支持降级——meanRet csA≥csC 三窗一致），文档原文给出两个选项："后续复扫改为三窗合并滚动统计（合并 283+新累积），或接受该观察项长期挂起为低优先级"。

**裁决：采纳"三窗合并滚动统计"**，拒绝长期挂起（OOS 双强共现速率约 3.6/日，自然累积到 500 需一年以上，挂起等于观察项死亡）。

- **合并口径**：合并样本 = 历史 283（决策窗 233 + OOS-1 32 + OOS-2 18）+ 各批复跑新增双强样本（synergy=A 档内 rt=A×cs=A 交叉，非共现全集，§15.1 口径），每批自动重算 meanRet(csA−csC) 方向差与合并 n；
- **代际边界**：降级命题是结构性质（非参数敏感），跨代际合并方向证据可接受，但批次报告须披露样本代际构成；**转正式证伪（关闭观察项）的三条件 = 合并 n≥500 ∧ Jump 修复新代际子样本 n≥200 ∧ 方向仍不支持降级**——防止用断线代际样本关门；
- **用途边界**：合并统计仅服务"双强降级"命题的观察/证伪，**不用于任何参数晋升**；晋升仍走 Track 2 判定卡单窗样本外判定。

## 3. 窗口定义（B-202610 版）

```text
decision : 2026-04-15 ~ 2026-07-31   （655 帧，in-sample 锚定窗）
oos1     : 2026-08-15 ~ 2026-08-31   （110 帧；08-01~08-14 FINAL 冻结不变）
oos2     : 2026-09-01 ~ 2026-09-30   （全月，含已消费帧 → 折扣标记）
oos2u    : 2026-09-13 ~ 2026-09-30   （未消费帧 → 判定卡 OOS 判定读数以此为准）
warm-up  : 各窗前 29 帧无信号（引擎设计行为），不计判定样本，披露有效交易日数
```

## 4. 批次执行清单

### 阶段 0｜批次前准备（半天）

> **执行状态（2026-09-16）**：0.2/0.3 已完成——窗口常量已推进（`data_windows.py` WINDOWS 单一事实源新增 decision/oos1/oos2/oos2u 四窗，TDD 7 passed；`evaluate_track2_candidates` 已改用单一源 + C2 判定读数切换 oos2u）；锚注册表 `config/ranktrend-anchors.json`、观察池 `config/ranktrend-observation-pool.yaml`、盘点脚本 `operations/diagnose_batch_data_quality.py` 已落地。0.1 三项已出中期版（`data/reports/batch-data-quality.json`）：9/1-9/2 槽位情绪缺文档已闭合（集合中两日有文档，内容是否 EOD 回退版待批次核）、LOW 帧日 8 个（04-15 首批日 + 7 月股灾月 6 日 + 9/11 收 6 帧，与 §20 一致）、ATR oos1 unknown 67.7% 与 §26.7 逐位复现；9-16 之后帧的全月版 10 月复跑同一脚本。
>
> **执行状态增量（2026-09-25）**：0.1-0.3 维持；**0.4 三项前置修复已完成**（TDD，新增 tests/test_track2_candidates_harness.py / test_ma_factor_contribution_harness.py / test_core_signal_parameters_harness.py 共 20 用例全绿，相邻 harness 测试 48 passed 无回归；commit f25aae8b + 0cd9ae1f）：① evaluate_track2_candidates 补 BASELINE_ANCHORS（gen-2026-10-b202610 decision 0.1323/oos1 0.0862，trial 级即时 raise）+ `_assert_overrides_applied` 逐键断言（决策五权重归一化字段豁免值比较）+ fund10_over2 重定义为仅 over 轴 + 新增 fund10_revert 对照臂（O2 baselineNote 落地）+ **缓存 overrides 一致性校验**（trial 定义变更后旧口径缓存作废重跑，防冒充）；② evaluate_ma_factor_contribution baseline 更正五因子口径 + 补 override 守卫 + oos2 截断口径源码标注；③ optimize_core_signal_parameters evaluate 返回体补 volumePrice 键 + `_fmt` 维度映射缺键 fail-fast（修复 resonance 冒充量价）。**执行注意**：守卫实测发现 from_patch 对决策五权重有归一化语义（patch 0.25 → 实际 0.2841），守卫对 `_DECISION_WEIGHT_FIELDS` 豁免值比较只断言字段存在。0.5 观察池补登记已完成。**0.6 已完成（2026-09-25，9 月全月版）**：全窗 1041 帧（04-15~09-24）；oos2 全月 176 帧/18 交易日（warm-up 后有效 147）；oos2u 90 帧/9 交易日（warm-up 至 09-16，有效 61——判定样本量披露）；LOW 日 8 个与中期版一致；**情绪覆盖闭合**（sentimentMissingOnFrameDays=[]，9/1-9/2 stale 回退问题已不存在，无需打标记）；ATR/amount 两项随专脚本在批次执行中留痕。盘点脚本修复：load_frames 内联冻结守卫后全窗只读盘点需 purpose="report"（0cd9ae1f）。产物：`data/reports/b-202610/batch-data-quality.json`。

1. 数据质量只读盘点（不阻断，打标记）：ATR unknown 率（§26.10.4）、amount 可算率（§26.6）、槽位情绪覆盖、缺帧清单、warm-up 有效帧数——作为批次报告第一章；
   > **演练执行（2026-09-25）**：五项全部产出（`data/reports/b-202610/batch-data-quality.json` + atr/vp-amount 四个 dryrun JSON）。全窗 1041 帧（04-15~09-24，**9 月尚缺 28/29/30 三个交易日**）；oos2 全月演练口径 176 帧/18 交易日、oos2u 90 帧/9 日（warm-up 至 09-16，有效 61）；LOW 日 8 个与中期版一致；**情绪覆盖闭合**（sentimentMissingOnFrameDays=[]）。**ATR（N3 判据）**：oos2 演练窗 unknown 65.35% > 50% 硬判据 → 维持"数据不足不开发"，N3 立项不成立；根因不变（gapResets 64012 vs missingBars 313）。**口径澄清**：L1 §26.7"oos 两窗覆盖已修复至 98%+"指 high/low 字段覆盖率（实测 97.97% 逐位吻合），**不是 unknown 率**——本行原文表述已修正。**amount**：decision 6.12%（逐位复现）/ oos2 演练窗 95.52% 健康。ATR/amount 诊断脚本原样 `python -m` 只出截断口径且 vp_amount 锚失配——已随锚单一事实源 + WINDOWS 派生化根治（89c4fd68）。
2. 窗口常量推进：oos2 按 §2.1 定案更新（ WINDOWS 单点修改 + 全部受影响锚声明失效）；
3. 建立锚注册表 `anchors.json` 与结构化观察池 `observation-pool.yaml`（首次落地，见 §8）；
4. **批次前置修复三项**（2026-09-21 harness 审计 §7.2，`harness-audit-20260921.md`）：
   - `evaluate_track2_candidates`（本批判定器）：补 baseline 锚断言 + `_assert_overrides_applied` 逐键断言；fund10_over2 trial 的 AbnormalFundRatio 轴已落默认（10.0=现值）不再是扰动轴，须重定义扰动轴或显式标注"本 trial 仅测 over 轴"，否则 O2 判定卡失真；
   - `evaluate_ma_factor_contribution`：baseline desc 仍写"四因子"（maWeight 0.37 已于 §22.8 落默认）——更正五因子口径，或固定 patch 复现四因子基线（R3/R4 回退判读依赖 baseline 语义正确）；
   - `optimize_core_signal_parameters`：`_fmt` 在 focus_dim="volumePrice" 时打印 resonance 冒充、evaluate 返回缺 volumePrice 键；
   - 关联违规（审计 A3，未列入前置三项）：`optimize_lifecycle_thresholds` 的 `excessMeanFutureReturn or 0` 把缺失伪装成 0 参与单调性判定——**批次涉及 lifecycle 阈值重扫（O6/N10）前必须修**；
5. **观察池补登记**：exit-rules-scan 阶段 C 第 3 项遗留动作（trailing 重扫/断板观察/tp×be 落默认复核原不在 YAML）+ L1 台账缺口项，已于 2026-09-25 登记进 `config/ranktrend-observation-pool.yaml`（R6/O9-O11/N9-N14；N8 复用已有 P_repool_timeline_gap 条目）；
6. **数据质量盘点补充两项标记**：① 采集池代际——9 月内快照采集池改造（超集切换）前后池构成差异，批次报告披露切换日期与影响帧范围；② 历史读数口径——operations 下 5 处 WINDOWS 手写副本的"oos2"为 09-01~09-12 截断口径（evaluate_ts_factor_weights 源头 + 4 反向 import 文件 + diagnose_regime_saex 本地副本），批次报告引用历史"oos2"读数时按截断口径解读（审计 §5.1/D1）。

### 阶段 1｜新代际锚建立

> **执行状态（2026-09-16）**：decision/oos1 两窗锚已预建——decision 0.1323（与 §26.7 单窗锚逐位复现，代际无漂移 ✓）/ oos1 0.0862（vs fund10 代际 0.0880，−2.0%），passHard 双窗 True，已录入锚注册表 gen-2026-10-b202610（commit 83bd7d0d）。**oos2/oos2u 待 10 月批次填充**。附带产出：阶段 20 trial 表 8 trial × 两窗新代际读数已入缓存（`data/reports/track2-candidates.json`），C2 均因 oos2u 缺数据不可判（OBSERVE 占位，不构成判定）。
>
> **执行状态（2026-09-25，演练完成）**：evaluate_track2_candidates 四窗 26 runs 全部执行完毕（decision/oos1 口径变更 trial 按 overrides 一致性校验重跑；jump25_fresh06/persist_on/ma_join/ma_full 走锚逐位复现背书的缓存）。**第四代锚：decision 0.1323 / oos1 0.0862（封闭窗，正式锚）+ oos2 全月演练 0.0998 / oos2u 0.0812（占位，10/3 全月重跑后更新）**——decision/oos1 baseline 于当前引擎（9/23 性能优化后）重跑逐位复现，代际无漂移 ✓；oos2/oos2u passHard=False（9 月窗单调性边缘失效为 fund10 代际以来既有口径延续）。锚注册表 currentGeneration=gen-2026-10-b202610（演练口径警示已写入注册表）。**Track 2 判定卡首产出（13 trial）**：无 REJECT（C3 决策窗全过）；PASS_CANDIDATE 1 项（O3_vsb070）、其余 OBSERVE——判定卡明细与关键读数见 `data/reports/b-202610/batch-summary.json`（fund10_revert：C1 −6.95% + C4 strong −22.8% → fund10 保持，oos1/oos2u 回退口径转正 +3.9%/+4.8% 作观察披露；fund10_over2/O2：C1 +2.65% 未过线 + C2 双 OOS 负 → 不重提 Track 1；jump25_fresh06/O4：C1 +6.05% 过线但 C2 三 OOS 全负；combo_p1：C1 +9.45% decision 叠加有效但 OOS 全负；persist_on：C1 −11.3% + C4 strong −25.4% → 维持不采纳；ma_join/R4：C1 −0.23% 无红灯、C5 翻转率无异常 → ma_join 保持）。跨窗净效应：Jump 修复 + fund10 组合 decision 大幅正迁移、oos1 轻微回落、9 月演练窗 saEx 回落且 passHard 边缘失效——弱市窗口信号质量衰减为代际对照章必披露项。**引擎性能实测（演练验证）**：单 trial decision ~118s / oos1 ~14s / oos2 ~28s / oos2u ~13s，13 trial 四窗全量 ~35 分钟，与引擎优化收口预算一致。

- baseline（当前默认栈全开：fund10 + 0.75 票权 + 五因子 p2_aggressive 权重 + ma_join + Jump 修复门）三窗全量 replay；
- 逐位记录 decision/oos1/oos2 读数 → **第四代锚**（此前：22.8 代 0.0939/0.0854/0.0737 → 23.9.1 代 0.1044/0.0918/0.0933 → fund10 代 0.1120/0.0880/0.0951 → 26.7 jump-fix 仅 decision 单窗 0.1323）；
- 与 fund10 代际锚对照，量化 Jump 修复的跨窗净效应（decision +18.1% 已知，oos 两窗未知）；
- 本阶段结论即 §26.5 已落默认组合在新代际的复现校验。

### 阶段 2｜已落默认栈逐项复核（回退 trial 设计）

结构性差异：这些项已在默认栈里，隔离其持续贡献用"**单项还原**"对照（patch = 还原旧值），而非晋升期的 baseline vs 候选。

| # | 项 | 回退 trial | 判定与回退条件 | 出处 |
|---|---|---|---|---|
| R1 | fund10（AbnormalFundRatio 20→10） | 还原 20.0 | 9 月窗判定卡推翻 → 还原 20.0 | §25.6.1/§25.7 |
| R2 | combo_three_quarter（res/rank/cs 票权 ×0.75） | 还原 1.0 | 三窗判定卡复现方可保持；**oos2 passHard 边缘失效为第一观察项** | §23.9.1 |
| R3 | 五因子权重 p2_aggressive（0.06/0.04/0.24/0.29/0.37） | 还原 0.24/0.20/0.16/0.20/0.20 | 9 月全月判定卡 + S+A 触发率监控（持续 <3.5% 评估 buyScoreThreshold 微调）+ retreat 桶 −0.045 代价监控 | §22.8/§22.6 |
| R4 | ma_join 五因子合同 | maWeight→0 | §21.6 三条回退触发核对：① 9 月窗 synergy saEx 低于旧 baseline 口径（绝对差<0）且 10 月窗连续为负；② WP3.2 翻转率异常上升（veto/bd > 旧口径 +0.01）；③ 交易层复核负偏离 | §21.6 |
| R5 | Jump 确认门修复 | （无回退项） | 以阶段 1 跨代际对照替代；三窗确认降级率与 saEx 收益 | §26.7 |
| R6 | 卖点默认 tp0.06×be0.02（takeProfit 9.99→0.06 + breakevenTrailing 0.02，2026-09-23 落默认，阶段 A 终局 wrxpf 0.9756=基线 2.02 倍） | 还原 takeProfit=9.99 + breakevenTrailing=False | 9 月窗 Track 1 复核（wrxpf + 30 笔门槛，隔离 runner `exit-scan-trial-runner.py`）；**decision 窗逐位=还原口径属预期**（市场状态依赖四次复现，改善全部来自 8 月中旬后样本外），判定看 oos2/oos2u 保护效应延续性；显著负偏离才评估回退 | exit-rules-scan-plan 阶段 A 终局（commit b251cf1c）；2026-09-25 增补 |

注：R6 为 trade 层参数（`V5_LIFECYCLE_FUSION_TRADE_DEFAULTS`），不影响信号层 saEx 锚（gen-2026-10-b202610 预建于 9/16，在其落默认之前，代际关系不受影响）；落默认时间晚于本方案定稿，故为增补项。

> **阶段 2 演练执行（2026-09-25）**：R2/R3 回退 trial 已并入 track2 判定卡（`R2_revert_combo_three_quarter`/`R3_revert_ts_weights`）四窗跑完——**R2 保持**（回退 C1 −11.1% + C4 strong −36.8% + C5 翻转率违反，oos1 +22.2%/oos2u +1.35% 局部转正不改判定）；**R3 保持**（回退 C1 −0.83% + C4 strong −20.6%，oos2u +3.82% 局部转正观察披露）；R1 保持（见阶段 1 fund10_revert 判定卡）；R4 保持（ma_join C1 −0.23% 无红灯）；R5 见阶段 1 跨代际对照；**R6 保持**（隔离 runner 回退复核：decision 窗两栈 36 笔逐位相同——市场状态依赖第五次复现；oos2 演练窗默认栈 12 笔 wrxpf 0.3473/sum −5.7%/maxDD −1.86% vs 回退栈 11 笔 0.1064/**−21.6%**/−2.39%，oos2u 同向——tp×be 保护效应延续，回退不成立；**披露：9 月窗 11-12 笔未达 M2 30 笔门槛，判定强度受限，10/3 全月重跑复核**）。四项判定卡 C4 的 strong 桶全线下降（−9.6%~−36.8%）为 9 月演练窗共性现象，代际对照章统一披露。

Track 1 交易复核只对判定卡亮红灯的项跑（wrxpf 主窗 + 30 笔门槛 + 入场集合漂移卡）。落默认决策归用户，本批只产出"保持/回退"建议。

### 阶段 3｜观察池裁决（全部候选在新代际重判）

| # | 候选 | 复核动作与触发条件 | 出处 |
|---|---|---|---|
| O1 | p2（vp 短路 off × veto 0.75，观察池最高优先） | 9 月全月 saEx 复现 + oos2u 交易层改善扩样保持 → 重提 Track 1 复核 | §24.5 |
| O2 | fund10+over2（观察池最高优先） | 新月度窗口 C2 通过；对照基线明确标注为 **fund10 回退口径**（§25.3 已示其在 fund10 落默认后基线漂移失效，重判必须换基线） | §20.3/§25.3 |
| O3 | vsB_070（B 档票强度 0.8→0.7） | 9 月全月复验同批裁决（Track 1 中性 +0.9% 在案） | §26.10.1 |
| O4 | jump25+fresh06 | 与 O2 同批复验 | §19.4 P1 |
| O5 | buyThr=0.18 | 9 月样本扩展复扫（两窗同向一窗反向在案；与 crossSection 复核、双强验证同批） | §13.3/§16.4 |
| O6 | MidLongCommitmentMin 剂量曲线 | 9 月全月重扫——oos2（9/1~9/12）+3.5~+7.1% 信号若在全月复现且 decision 窗读数抬升，按 Track 2 流程重出提案 | §23.7 |
| O7 | crossSection A 档复核 | A 档样本 >500 + 新窗口 synergy 稳定 >0.05（§11.5 触发线） | §10.4/§11.5 |
| O8 | 双强共振 rt=A×cs=A | 按 §2.2 合并滚动统计口径重算（合并 283+9 月新增），报告披露合并 n、代际构成与方向一致性；证伪三条件见 §2.2 | §15.4 |
| O9 | trailing stop 修正档位重扫 | 批次 4 四档 (activate,drawdown)=(0.06,0.6)~(0.03,0.3) 与 tp×be 基线逐位零增量系**档位设计失误**（be0.02 已在场，dd 0.3~0.6 需峰值 +43%~+150%，远超窗口最大浮盈）；有意义空间 dd 0.03~0.08 × activate 0.04/0.05（3-5 trial）；**是否批准重扫待用户决策**；若上线需与 tp×be 同窗对比 | exit-scan-batch4-verdict / exit-rules-scan-plan 批次 4 小节；2026-09-25 增补 |
| O10 | 断板卖出 breakBoardExit 触发观察 | B2 已实现+单测、默认关；阶段 A 全窗 43 笔持仓 0 触发（样本不存在≠无效，fail-visible 不下结论）；批次复跑顺带核对 9 月窗是否出现"断板" reason 桶，出现即自动进入分桶观察 | exit-scan-batch4-verdict；2026-09-25 增补 |
| O11 | volumePriceMildRatio 1.05 | L1 §14.4 OBSERVE（−2.7/+7.7/+14.7% 跨窗矛盾），原登记无复验安排——本批补登记做轻量复扫或维持挂起裁决（低优先） | L1 §14.4；2026-09-25 增补 |

> **阶段 3 演练执行（2026-09-25）**：O2/O3/O4/O5 已并入 track2 判定卡四窗跑完——**O3_vsb070 = PASS_CANDIDATE**（C1 +5.97% ∧ C2 三 OOS 全正 oos1 +15.89%/oos2u +6.4%/oos2 +4.71% ∧ C3 保持；C4 strong/retreat −9.6% 未过非否决项；按流程进用户决策队列，先补 9 月窗 Track 1 复核终判 wrxpf + 30 笔门槛——§26.4 decision 窗 Track 1 +0.9% 中性在案为旧口径证据）；O2 不重提（C1 +2.65% 未过线 + C2 双 OOS 负）；O4 OBSERVE（C1 +6.05% 过线但 C2 三 OOS 全负）；O5 维持 OBSERVE（C1 −2.27% 未过线）。**O6 触发成立且放大**（专项缩围重扫：9 月全月收紧侧单调 x1.25→x3 +2.5%→+8.1%，x2 恰复现历史 +7.1% 上限；oos2u 更强 x2 +10.7%/x3 +13.3%；decision 抬升 x3 +3.9% 过 C1 线——§23.7 两条复核触发前提均成立，**10/3 全月重跑后重出 Track 2 判定卡提案**）；**O7 触发不成立维持挂起**（csA 样本仅 decision 单窗 >500，9 月两窗 A 档内 synergy saEx −0.030/−0.149 推翻"稳定>0.05"；附带发现 cs 维 A 档自身 excessDirAcc 四窗 ≈0，信息量在交叉项非单维档位）；**O8 方向翻转、维持挂起**（§2.2 合并口径 n=283+149=432 未达 500，新代际子样本 149 未达 200，但 4 窗中 3 窗 meanRet(csA−csC)<0 开始支持降级——历史口径三窗一致不支持；新代际 decision 双强样本 233→91 缩水系 Jump 确认门真实拦截，代际构成已披露；10/3 建议标注"方向证据转向，n 齐后优先重判"）。产物：`data/reports/b-202610/dryrun-progress.md`（T1-T6 全录）。

### 阶段 4｜待立项评估

| # | 事项 | 动作 | 出处 |
|---|---|---|---|
| N1 | jumpConfirm 两参 5 档扫描 | 门修复后剂量才有意义，新代际首批扫描（评估立项） | §26.10.2 |
| N2 | 交易层口径课题批四项（weak/reverse 线、regimeStrongScore、decisionReversal*、momentumScoreThreshold） | saEx 盲区三案同构，工具已备（`track1_lifecycle_gate_trade --extra-arm` / `track1_dimension_power`），一次跑完 | §26.8 |
| N3 | P6-a ATR | 9 月全月 unknown 率重测（阶段 0 盘点产出）后决定是否立项（unknown>50% 硬判据） | §26.10.4 |
| N4 | MA 替换触发检查 | decision 窗复验转正 ≥+3% 即走 PASS_CANDIDATE（macdWeight→0） | §20.5 |
| N5 | MA 金叉事件级加分项评估 | 事件级用法（非权重、非 trend_buy 接线位）从未评估 | §17.7/§19.4 P3 |
| N6 | regime 门禁扩展消费非 strong 状态时 α/迟滞重扫 | 条件触发型，本批仅核对触发条件是否成立 | §12.4 |
| N7 | res NaN median 拦截帧 H2 线索 | 代码级修复候选（非阈值空间），只登记不实施 | §25.6.5 |
| N8 | P_repool_timeline_gap oos2u 终判 | 已立项（观察池 P_repool_timeline_gap 条目）：中期双窗方向性支持 floor3（insufficient 14.2%→8.3%，A 档质量不劣于基线，H0 被双窗数据推翻）；终判 = 补 h8 口径 + B 档样本量核对 + 幸存者偏差标注 + oos2u A 档优势稳定性；天然 saEx 盲区候选（样本集扩张而非阈值迁移）→ Track 2 判定卡 + 盲区检查 + **Track 1 终判（wrxpf + 30 笔门槛）**全链必跑；通过则 degradedSampleFloor 3 落默认（一次一候选 + strategy_version 提升）；参数 α（window_size 50→280）视 β 终判结果决定 | ranktrend-repool-timeline-gap-research-proposal §5/§8；2026-09-25 增补 |
| N9 | 组 5 参数 rolling walk-forward 重验 | L1 §6 挂起项：9 月数据累积后对组 5（G1-G7/方向 A-C，含 regimeGateStrongBan 等）重新走 rolling walk-forward（A/B 纪律）；含 WP1c lookahead 修复（2026-09-06）后的组 5 参数结论重验；momentumDirectionThreshold 0.2 / momentumSignalShareMin 0.6 定值窗口含 8 月冻结帧的轻量复核并入本项；工作量较大，批次评估立项（可拆下一批） | L1 §6；2026-09-25 增补 |
| N10 | lifecycleConfirmFrames（K）结论滚动重验 | L1 §7 挂起项：K=1 证伪结论待 9 月数据按 §6 滚动重验（轻量） | L1 §7；2026-09-25 增补 |
| N11 | takeProfit 0.04/0.05 边界复核（可选） | 批次 1 判定卡建议的 2 trial 轻量确认更紧档峰值位置（0.06 单调方向与 oos 双窗支持已足够支撑落默认，不构成阻塞） | exit-scan-batch1-verdict / exit-rules-scan-plan GAP-2；2026-09-25 增补 |
| N12 | HighRisk pressure 门变活跃核对 | 条件触发型：门 0.75 现基本不触发；若 risk 链改动致变活跃 → 重扫 HighRisk 三参数 + riskPressureWeights；批次仅核对触发条件（与 N6 同类） | L1 §11 复核触发②/§23.4；2026-09-25 增补 |
| N13 | crossSectionPersistFrames 重评 | H1 成立、H2 证伪，0=关闭；"待投票语义拆分后重评"——前置条件（投票语义拆分）未立项，本批仅登记维持关闭，长期挂起 | L1 §8 / longterm §18；2026-09-25 增补 |
| N14 | strong 双峰"分状态门控"设计评审 | P3 前置标定（strong 线位移动分离塌陷/强劲双峰）的服务对象（serve P4 分状态门控，长测 §14.4 后续课题）；设计类课题，批次评估是否立项 | ranktrend-param-gap-scan-plan P3 关联课题；2026-09-25 增补 |
| N15 | jev 涨停驱动分类扩窗复验（搭车支线，**非 RankTrend 链**） | **⛔ 用户裁决暂缓（2026-09-30，B-202610 收官当日）：方向未定，不执行扩窗**——非成本原因，用户尚未决定是否往该方向投入；登记保留不删除（脚本幂等可续跑，数据/词表/叙事模板均在），重启时点与是否重定义（如 Noul 轴砍掉/改造）由用户后续单独裁决。原方案存档：10/3 复跑数据落库后扩窗 2026-05-06→09-30 重打（首验 08-11→09-24 已 9,223 标签），判据=扩窗后 Kruskal p<0.05 且连板率排序方向与首验一致才升 PASS_CANDIDATE，必带混杂标注；成本 ≈$0.5-1 | hotlist-jev/phase3-driver-report.md；2026-09-28 增补，2026-09-30 暂缓 |

> **阶段 4 演练执行（2026-09-25）**：**N1 完成**——jumpConfirm 两参 5 档 × 三窗 27 runs，Jump 门修复后剂量首次有意义（不再是断线代际逐位=baseline）：**jumpConfirmVolumeRatioMin 紧侧三窗全正**（vr1.25 +1.59/+1.97/+5.21%；vr1.5 +0.53/+8.70/+5.41%）为 N1 首批最有意义剂量信号，chg 轴跨窗方向不干净，两轴松侧无收益；monitor_only 性质，10/3 全月重跑后出正式判定卡。**N8 演练完成**——oos2u floor3 insufficient 15.47%→9.59%（−5.88pp）复现中期方向，h8 口径 `--horizon` 透传可行无阻断，终判链 10/3 剩 Track 1（wrxpf+30 笔）等项。N2-N7 未在演练队列（N2 交易层四课题、N4/N5 MA 系、N6/N7 条件型留 10/3）。

> **N15 增补背景（2026-09-28）**：jev（Cloudflare 结构化判别模型）三期实验后首现真信号——涨停驱动七类打标（9,223 标签/0 退化/重打稳定 100%）与次日连板率分组 **Kruskal p=0.0007、极差 19.5pct**（重组并购 21.3% > 订单业绩 14.3% > 蹭概念 11.6% > 产品事件 4.1% > 资金接力 1.8%），催化-主业匹配度 Noul 轴分布过窄不足 → 判 INSUFFICIENT。本项为**独立观察面候选支线**：判定产物只落 `hotlist-jev/` 文档线，**不进观察池、不进 L1 台账、不参与 RankTrend 判定卡**；若扩窗复验 PASS_CANDIDATE，接入方式（是否/如何进观察面）另行单独立项走一次一候选。匹配度 Noul 轴分布过窄（p25-p75=0.63-0.82 无梯度），扩窗版砍掉或改造后再验。

### 阶段 5｜批次收口

1. 单一批次报告：`data/reports/b-202610/`（判定卡汇总表 + trial 明细 + 数据质量章 + 代际对照章 + oos2/oos2u 双披露章）；
2. 长测文档追加"阶段 27：9 月全月复验批次 B-202610"（含证伪/否定结论）；
3. L1 台账（`ranktrend-l1-param-ledger.md`）、观察池 YAML、锚注册表三件同步；
4. 台账落痕顺带核对：P1-b persist 交叉对照 trial（crossSectionPersistFrames 置 3，gap-scan 方案 P1-b）结果在台账侧无记载，收口时核对是否实际执行；
5. 全程纪律：8 月 FINAL 冻结、一次一候选落默认（每项独立 commit）、判定卡自动产出、负贡献即回退。

## 5. 判定与落默认纪律（本批适用）

1. **Track 2 判定卡**（信号层）：C1 决策窗 saEx 相对 ≥+3%；C2 至少一个 OOS 窗同向为正（OOS 集合 = {oos1, oos2}，oos2 判定读数取 oos2u）；C3 passHard 不降（一票否决）；C4 regime 四桶降幅 ≤0.01；C5 翻转率升幅 ≤0.01。C1∧C2∧C3 = PASS_CANDIDATE。
2. **saEx 盲区检查**：只迁移负票/中性档的阈值线 saEx 结构性不可见——候选先过三层判定语义（真惰性 / saEx 盲区 / saEx 活跃），盲区候选直接走 Track 1 终判（阶段 24 e1a 首例拦截：saEx 三窗全正但交易层 −32%）。
3. **Track 1 交易复核**（交易层终判）：wrxpf = winRate×profitFactor 主窗复核 + 30 笔样本门槛 + 入场集合漂移卡。
4. **六类判定**：PASS_CANDIDATE（进用户决策队列）/ OBSERVE（观察池登记，绑定代际与触发条件）/ REJECT / 证伪 / 冗余 / 缺复核。
5. **落默认流程**：用户决策 → 一次一候选（独立 commit）→ TDD → 端到端锚逐位复现 → TS 合同同步 → 回退路径写明 → 首日人工验证。
6. **优化结果永不自动写回默认值**；本批零默认值预判，全部变更走用户决策。

## 6. 产出物清单

| 产出物 | 位置 | 说明 |
|---|---|---|
| 批次判定报告 | `data/reports/b-202610/` | 判定卡汇总 + trial 明细 + 数据质量章 + 代际对照 + oos2/oos2u 双披露 |
| 锚注册表 | `quant-board/config/` 或 docs 就近 | 第四代锚读数 + 历史三代（见 §8 结构） |
| 结构化观察池 | 同上 | O1-O8 状态机 + 触发条件 + 代际绑定 |
| 长测文档阶段 27 | `ranktrend-longterm-backtest-plan.md` | 本批结论固化（含证伪记录） |
| L1 台账补记 | `ranktrend-l1-param-ledger.md` | §23.9.1 临时默认补记（挂起至本批）等 |

## 7. 风险与诚实边界

1. **统计效力**：本批实质只有 1 个全新 OOS 窗（9 月），判定卡 C2 统计效力薄；warm-up 后 9 月有效交易日约 15-16 天，须逐项披露样本量；
2. **循环性**：已落默认项的"落默认后复核"天然存在"用同一段数据验证自己"的循环——以回退 trial 设计（R1-R4）+ oos2u 未消费子窗缓解，不能消除，批次报告如实标注；
3. **代际断裂**：阶段 0-26 全部观察池证据属断线代际，本批为首次新代际全量重判；O2 等候选的对照基线必须显式声明（fund10 回退口径），否则被已落默认的 fund10 污染；
4. **执行成本（2026-09-24 引擎性能优化收口后更新，handoff 文档实测）**：全窗 dry-run 单 trial 318-380s（≈5.3-6.3 分钟，含 ~70s frames 加载）；持久化全窗 run 839s≈14 分钟（内存充裕时段）；6-trial 批量 `--batch --dry-run --local-frames` 实测 581s≈9.7 分钟。信号缓存仅 trade_config 恒定时命中，B-202610 多为 strategy 层参数扫描基本无缓存命中，按"每 trial dry-run 5.3-6.3 分钟 / 持久化 ~14 分钟 + 首次 frames 加载"估算。**判定留痕口径**：dry-run summary JSON（`<runid>-summary.json`）即可作 trial 证据；持久化落库 run 仅 Track 1 完整交易复核需要时使用。报告产物不作为对照物——对照物是文档代际锚；
5. **引擎版本注记**：批次执行引擎为 9/23 性能优化后引擎（a50ab16d + f5930be6），与 exit-scan 锚逐位一致三重实证；对本批代际锚的关系由阶段 1 锚复现自然校验（decision 0.1323 逐位复现在案），批次报告注明引擎版本；
6. **市场状态依赖披露义务**：卖点默认 tp×be 的全部改善来自 8 月中旬后样本外（decision 窗逐位=基线，四次独立复现）——批次报告判定卡须携带该披露，decision 窗零改善属预期非失效信号；
7. **执行资源纪律**（2026-09-23 内存冻结事故沉淀）：多 trial 扫描一律走 CLI/隔离 runner（`--batch` 范式），禁止经 8000 API 连续跑批；禁止并行 ≥2 个回测进程；交易时段（9:30-11:30 / 13:00-15:00）不排大批次、不重启 8000。

## 8. 平台化挂钩（本批沉淀 / 批次后立项）

本批只落地平台化最小集（遵循 AGENTS.md §10 反过度设计：不新增 MongoDB 集合/API、不搞守护进程）：

**本批沉淀**：

1. **锚注册表**（`anchors.json`，一个 JSON）：`{代际名, config_hash, git commit, 三窗读数, 适用范围, 失效原因}`，harness 启动自动校验当前基线代际、失配显式标记；
2. **结构化观察池**（`observation-pool.yaml`，一个 YAML）：`{候选, 状态, 证据指针, 触发条件, 代际绑定, 对照基线}`，批次 runner 从观察池直接生成执行清单，终结 16 处散落小节的人工汇总；
3. **数据质量前置报告**：复用现有 diagnose 脚本拼只读入口，五项盘点打标记；
4. **批次报告归档**：`data/reports/<batch-id>/` 目录纪律，归档最小集 = 判定卡汇总 + 锚读数 + trial 参数 + 代码版本。

**批次后立项**（不在本批关键路径）：公共 harness 库抽取（范式 8 项：WINDOWS import 零日期字面量、`_assert_overrides_applied` 逐键断言、`assert_not_frozen` 无条件执行含 resume 路径、trial 级缓存 resume、`_save` 剥离 `__frames__`、锚 trial 级即时 raise、`--extra-trial/--extra-arm`、M2 样本门槛）、判定卡单一实现、Track 1/Track 2 候选级统一 runner（一 trial 出双轨）、窗口 registry 带消费状态、月度批次自动汇总。
> 2026-09-21 更新：公共 harness 库已提前落地（`backend/operations/harness_common.py`，commit ec46ef5e，39 文件审计产物，五类风险各对应一能力）；批次内新/改 harness 应基于公共库。其余（判定卡单一实现、统一 runner 等）维持批次后立项，见 §9.3。

## 9. 2026-09-25 增补：9 月长测收尾项全量清点（批次清单扩充依据）

本方案 2026-09-16 定稿后，9/17-9/25 四条证据线继续产出结论与遗留项；另对 L1 参数台账（`ranktrend-l1-param-ledger.md`）全量核对，发现少量 9/16 版未承接的挂起项。本节为增补依据存档；**执行清单以 §4 各表（含新增 R6/O9-O11/N8-N14）与观察池 YAML 为准**。

### 9.1 四条证据线状态与贡献

| 证据线 | 文档 | 状态（截至 09-25） | 对本批的贡献 |
|---|---|---|---|
| 卖点规则扫描阶段 A/B | exit-rules-scan-plan.md + 4 个 batch verdict | 阶段 A 终局（tp0.06×be0.02 组合最优，9/23 落默认）；阶段 B 收口（B1 trailing / B2 断板默认关，golden 不漂移，全量 pytest 2572 passed） | R6（tp×be 代际复核）、O9（trailing 重扫，待用户决策）、O10（断板观察）、N11（tp 0.04/0.05 可选）、市场状态依赖披露义务（§7.6）、死参数排除清单（§9.3）、隔离 runner 纪律（§7.7） |
| harness 39 文件×5 类风险审计 | harness-audit-20260921.md | 审计完成；公共库 harness_common.py 落地（ec46ef5e，范式 8→13 项）；**3 FAIL 前置修复均未做**（git 核实 09-25） | 阶段 0 前置修复三项（0.4）、A3 or-0 违规（O6/N10 前置）、WINDOWS oos2 截断口径解读（0.6②）、D 类改造批不阻塞（§9.3） |
| P_repool_timeline_gap 研究 | ranktrend-repool-timeline-gap-research-proposal.md | 已立项（9/20）；A1 盘点完成；中期双窗方向性支持 floor3，oos2u 未触碰；首轮假阴性事故已修复闭合（770838c9→f686ada5） | N8（oos2u 终判全链）；代际纪律——本课题证据代际随批次重判更新 |
| 引擎性能优化 | engine-perf-optimization-handoff.md | 收口（a50ab16d+f5930be6+b71ab521，4 硬门槛全过） | 执行预算更新（§7.4：小时级→分钟级）、dry-run 留痕口径、禁并行/交易时段纪律（§7.7）、引擎版本注记（§7.5） |

### 9.2 L1 台账缺口核对结论（9/16 版未承接项 → 增补去向）

| 项点 | L1 出处 | 处置 |
|---|---|---|
| 组 5 参数 rolling walk-forward 重验 + WP1c 修复后结论重验 | §6 | → N9 |
| lifecycleConfirmFrames（K）证伪结论滚动重验 | §7 | → N10 |
| crossSectionPersistFrames"待投票语义拆分后重评" | §8 | → N13（登记维持关闭） |
| HighRisk pressure 门变活跃时重扫 | §11 | → N12（条件核对） |
| volumePriceMildRatio 1.05 OBSERVE 无复验安排 | §14.4 | → O11 |
| momentumDirectionThreshold 0.2 / momentumSignalShareMin 0.6 定值窗口含 8 月冻结帧"待复核" | §2b | 轻量核对，并入 N9（非独立 trial） |
| strong 双峰"分状态门控"设计评审课题 | gap-scan-plan P3 | → N14 |

B-202610 其余"9 月复验/10 月"表述（§23.9.1 补记、buyScoreThreshold、ma_join/ma_replace、MidLongCommitmentMin、vsB_070、fund10+over2、组合 p2、jumpConfirm 重扫、ATR 重测、交易层四课题、双强合并统计、H2 NaN median 线索、组 5 以外的 walk-forward 项）经逐一核对均已被 9/16 版 R1-R5/O1-O8/N1-N7 承接，无重复登记。

### 9.3 明确排除项（不纳入本批）

- **zljzb 资金流口径归属**：weakStateExit 对 v3 锚结构性零影响（未接线 v3），口径确认挂起，仅未来接线 v3 时有意义；
- **死参数/REJECT 排除清单**（后续任何卖点/参数扫描不再花算力）：stopLoss（非单调，默认 -0.05 维持）、useAtrStops（负贡献 + multiplier≥2.0 不活跃）、weakStateExit / signalExitDelayBars（未接线 v3 锚逐位零影响）、minHoldingBars（half_hour+T+1 下档位 ≤4 无意义）、maxHoldingBars（与 tp×be 组合 REJECT，截断盈利尾巴，已收口）；
- **adjustment-fq-plan.md**：整体已作废（2026-08-23，前提系读图错误，复权口径实际无分裂），四条待决策项全部失效，不纳入；
- **审计 D 类改造批**（不阻塞本批，批次后执行）：WINDOWS 手写副本 5 处派生化、resume 守卫 4 文件（evaluate_ts_factor_weights / evaluate_dimension_voting_power / evaluate_lifecycle_dimension / evaluate_lifecycle_gate_form）、锚纪律统一"漂移即落盘+停"3 文件、windowsConsumed 6 文件补齐、旧 optimize_* 5 文件守卫（公共库迁移时自动解决）。

### 9.4 增补后批次规模概览

- 阶段 0：6 项（新增前置修复 0.4、观察池补登记 0.5、盘点补充 0.6）；
- 阶段 1：不变（decision/oos1 锚已预建，oos2/oos2u 待批次填充）；
- 阶段 2：R1-R6（+1，tp×be trade 层复核）；
- 阶段 3：O1-O11（+3，其中 O9 待用户决策批准、O10 仅核对、O11 低优先）；
- 阶段 4：N1-N14（+7，其中 N8 为重点终判项，N9 可拆下一批，N11-N14 为轻量/条件型）；
- 阶段 5：+台账落痕核对 1 件。


### 9.5 10/3 正式复跑执行建议（演练产出）

- **顺序与预算**（串行，总 ~4.5-5 小时）：数据质量盘点全月版（~10 分钟）→ track2 判定卡四窗全 trial（~40 分钟）→ N1 27 runs（~50 分钟）→ O8 双强合并（~10 分钟）→ O7 csA 统计（~6 分钟）→ O6 剂量先 --only 缩围、判定卡候选再补全量（~45 分钟）→ N8 oos2u h1+h8 + decision/oos1 h8 补齐（~30 分钟）→ R6 重导 frames 至 09-30 + batch（~15 分钟）→ O3 终判 Track 1（wrxpf+30 笔，9 月窗）→ 批次收口（阶段 27 文档 + L1/观察池/锚三件同步）。
- **缓存纪律**：data/reports/ 下所有含 oos2 窗缓存的历史报告一律不 resume（旧窗 09-09/09-12 截断口径会按窗名冒充全月缓存）——全部用新 `--out`；`b-202610/*-dryrun.json` 保留作演练对照，不作正式读数。
- **锚**：9 月全月（约 206 帧）落库后 oos2/oos2u 锚重跑更新锚注册表 JSON——全部 harness 经 `baseline_anchor()` 自动跟随，无需改代码；decision/oos1 演练读数即正式。
- **判定卡对象**（按优先级）：O6 MidLong 收紧档（触发已成立，优先重出提案）→ O3 vsB_070 终判 → N1 vr 紧侧 → N8 终判全链 → R6 维持默认复核收口。
- **待办移交**：diagnose_regime_saex_decomposition 本地 WINDOWS 副本仍为 09-09 截断（不在本批队列）；evaluate_lifecycle_dimension 的 BASELINE_ANCHOR 死常量（22.8 代际）无校验逻辑，建议切注册表 baseline_anchor()。
