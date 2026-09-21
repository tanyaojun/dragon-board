# operations 研究 harness 五类风险审计（2026-09-21）

> 起因：2026-09-20 P_repool_timeline_gap 中期扫描 harness 字段路径 bug（读
> `signal["observation"]`，实际结构为 `signal["rankTrend"]["observation"]`）产出
> 「lifecycle 档位 100% unknown」假阴性结论（commit 770838c9，已由 f686ada5 更正）。
> 本审计把同类风险在全部 harness 上系统性排查一遍，并沉淀公共库与 skill 纪律。
> 审计方式：4 路并行只读审计 + 2 个自查，全部结论来自 Read 原文取证（本机 rg 有
> 输出渲染 bug，"observation" 显示为 "ln"，禁用 rg 字面输出做结论）。

## 1. 审计范围

`backend/operations/` 下 46 个 .py，排除 7 个非回测运维脚本（hotlist_sentiment /
migrate_hotlist_sentiment_slot_eod / mongodb_dead_data_cleanup / schedule /
rank_field_backfill / snapshot_field_backfill / `__init__`），**审计对象 39 个**：
diagnose_* 13、evaluate_* 16、optimize_* 6、research_exit_holding、
scan_repool_sample_floor、track1_* 2。

五类风险：a 字段路径（vs DIMENSION_PATHS / engine 实际输出）；b 评估工具返回键名
（tier_forward_returns → `tiers/unknownRate/monotonicity`；tier_monotonicity_score →
`checks/passHardConstraint`）；c 幸存者偏差与帧边界样本缺失披露；d override 静默失效
（_assert_overrides_applied 逐键断言）；e 窗口纪律（WINDOWS 单一源、assert_not_frozen
无条件、oos2u 消费禁令、FINAL 冻结窗）。

## 2. 权威判据（本次核实基线，后续 harness 一律以此为准）

- **signal 顶层**：`_build_signal` 返回（engine/runtime.py:1405-1447）snapshotId/
  timestamp/tradingDate/slotTime/code/name/rank/…/candidateTier/action/…/rankTrend/
  stage/regime；**observation 挂在 `signal["rankTrend"]["observation"]`**（rankTrend
  九键 meta/technical/jump/cycle/risk/decision/observation/strategy/executionStrategy，
  runtime.py:1241-1275）。sampleQuality 在 `rankTrend.meta.sampleQuality`（status ∈
  ok/degraded/insufficient，runtime.py:1249）。`rankTrend.trendReversal` 由 replay 循环
  逐信号注入（runtime.py:994/998）。
- **维度档位唯一读取器**：`research/tier_monotonicity.py` 的 `tier_signal_of` +
  DIMENSION_PATHS（:23-32）。resonance → `rankTrend.resonance.signalTier`，其余七维 →
  `rankTrend.observation.<dim>.signalTier`。根包 `__init__.py` 的 sys.modules 别名使
  `backend.analysis.ranktrend.tier_monotonicity` 等价同模块（**单一源成立**，旧 import
  路径不算问题）。
- **tier_forward_returns 返回**（:171-179）：horizon/tiers/unknownRate/frameCount/
  indexedFrameCount/bucketBaselines/monotonicity；tiers[tier] = {count,
  meanFutureReturn, excessMeanFutureReturn, directionAccuracy, excessDirectionAccuracy,
  bucketBaselineAccuracy, bucketBaselineMean}。键名 `tiers`（不是 byTier）。帧边界/
  缺股/坏 rank 样本直接跳过（不计 count），样本缺失只能从 count 对照看出。
- **tier_monotonicity_score**（:261-276）：score/meanFutureReturn/passHardConstraint/
  spearmanRankCorr/reversals/unknownRate/checks。
- **tier_discrimination**（:279-334）：sMinusC/aMinusC/tierSpread/saDirectionAccuracy/
  saExcessAccuracy/cDirectionAccuracy/deVsC/positiveMonotonic。
- **窗口**：`backend/optimization/data_windows.py` WINDOWS 八窗；final=08-01~08-14
  冻结（assert_not_frozen，purpose != "report" 即 raise）；oos2u=09-13~09-30 批次终判
  专属（消费禁令是 2026-09-16 起的文档纪律，代码不强制）。
- **load_frames 权威实现**：optimize_resonance_parameters.py:171-177（MongoRepository +
  dragonboard_live + half_hour + projection=ranktrend）。

## 3. 审计矩阵（39 文件 × 5 类）

图例：✅ PASS｜❌ FAIL（会产出错误数据/结论）｜⚠️ RISK（结构性风险，当前无误）｜— N.A.

| 文件 | a 路径 | b 键名 | c 偏差披露 | d override | e 窗口 | 关键备注 |
|---|---|---|---|---|---|---|
| diagnose_atr_discrimination | ✅ | ✅ | ✅ | — | ⚠️ | WINDOWS 取自 evaluate_ts_factor_weights 二手副本；unknownRate 用 raw 口径与 saEx forward 口径混用（各自留痕） |
| diagnose_batch_data_quality | — | — | ✅ | — | ✅ | 只读帧数/覆盖盘点；WARMUP_FRAMES=29 硬编码文档口径 |
| diagnose_cost_sensitivity | — | ✅ | — | ⚠️ | ❌ | 默认空日期=全量加载（含 FINAL）；deepcopy DEFAULT_TRADE_CONFIG 无逐键断言 |
| diagnose_dual_strength_syna | ✅ | ✅ | ✅ | — | ⚠️ | 继承 regime_saex 的本地 WINDOWS 副本；assert purpose="report" 守卫被豁免；generatedAt 硬编码 2026-09-10 |
| diagnose_gate_flip_rate | ✅ | ✅ | ✅ | — | ❌ | 无 WINDOWS/守卫，默认空日期全量 |
| diagnose_lifecycle_gate_score | ✅ | ✅ | ✅ | — | ✅ | import 上游私有函数 _build_lookup/_percentile/_spearman（私有耦合） |
| diagnose_regime_risk_activity | ✅ | — | ✅ | ✅ | ✅ | **override 三层断言正面样板**（make_config L113-131） |
| diagnose_regime_saex_decomposition | ✅ | ⚠️ | ✅ | — | ⚠️ | L64 读不存在的 `monotonicity.hardOrderViolations`（恒 None）；本地 WINDOWS 字面量副本 |
| diagnose_resonance_vote_structure | ✅ | ✅ | ✅ | — | ✅ | 空窗 ZeroDivisionError（响亮失败）；文案字符串作分组键（脆弱） |
| diagnose_signal_return_gap | ✅ | ✅ | ✅ | — | ❌ | 默认 --end 2026-08-14 覆盖 FINAL，无守卫 |
| diagnose_tier_discrimination | ✅ | ✅ | ✅ | — | ❌ | 默认 --end 2026-08-14 覆盖 FINAL，无守卫 |
| diagnose_trend_reversal_jump | ✅ | ✅ | ✅ | — | ❌ | 默认 --end 2026-08-14 覆盖 FINAL；分桶 `or 0` 把 None 混入低档桶 |
| diagnose_weak_regime_sampling | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | regime 缺失静默归 normal 桶（伪装缺失模式）；`__dict__` 合并构造无断言；默认窗 03-27~07-31 安全 |
| evaluate_cs_strengths | ✅ | — | ✅ | ✅ | ✅ | signalTiers 与 saEx 来自两次独立 replay（等价对照覆盖） |
| evaluate_cs_tier_thresholds | ✅ | — | ✅ | ✅ | ✅ | — |
| evaluate_dimension_voting_power | ✅ | — | ✅ | ⚠️ | ⚠️ | 无 override 断言（含 monkeypatch 索引无生效性断言）；assert_not_frozen 在 resume 缓存命中分支内；无 windowsConsumed 标注 |
| evaluate_jump_confirm_parameters | ✅ | ✅ | ✅ | ✅ | ✅ | **锚漂移 RuntimeError 即停正面样板**；docstring 完整记录 direction 枚举断线修复代际 |
| evaluate_lifecycle_dimension | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | A 组 list override 无断言；assert_not_frozen 在 resume 分支内；无 windowsConsumed |
| evaluate_lifecycle_gate_form | ✅ | — | ✅ | ⚠️ | ⚠️ | 无 override 断言（锚链间接覆盖但 anchorChain 只落盘不 raise）；assert_not_frozen 在 resume 分支内 |
| evaluate_ma_factor_contribution | ✅ | ✅ | ✅ | ⚠️ | ✅ | 无 override 断言；baseline desc「四因子」已过期（22.8 落默认后为五因子）；本地 WINDOWS 字面量（有意截断防 oos2u，有注释）；无 windowsConsumed |
| evaluate_regime_risk_thresholds | ✅ | ✅ | ✅ | ✅ | ✅ | **范式标杆之一**（override 断言+regime 线序 fail-fast+锚漂移先落盘再停） |
| evaluate_resonance_participation | ✅ | ✅ | ✅ | ✅ | ✅ | anchorChain 全窗 all() 单窗误报（synergy_tier 的 anchor_chain_of 修复未跟进） |
| evaluate_strategy_signal_fit | ✅ | ✅ | ✅ | — | ❌ | 默认 --start 04-15 --end 08-14 覆盖 FINAL，无守卫；_load_frames 为权威实现同构副本 |
| evaluate_synergy_tier_thresholds | — | ✅ | ✅ | ✅ | ✅ | **纪律最完整样板**（锚漂移 SystemExit、anchor_chain_of 只断言已跑窗、from_patch list 形状守卫留痕） |
| evaluate_track2_candidates | — | ✅ | ✅ | ⚠️ | ✅ | **无 override 断言且无 baseline 锚**；fund10 已落默认（config.py:104=10.0）→ fund10_over2 trial 该轴非扰动，重跑判定卡失真（B-202610 前置修复项）；`if "frames" not in entry` 恒真脆弱写法；WINDOWS 从 data_windows 派生含 oos2u（批次终判豁免路径） |
| evaluate_trend_leftover_parameters | ✅ | ✅ | ✅ | ✅ | ✅ | 对照组确认无误；docstring 承诺「锚不复现即停」未代码化；anchorChain 全窗 all() 误报；「from_patch 零校验」文档已过期（config.py:503-517 已有 len 校验） |
| evaluate_ts_factor_weights | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | **WINDOWS 手写三窗字面量源头**（:56-60，oos2=09-01~09-12 与权威同名不同义），下游 vp_amount/vp_signal/track1_dimension/atr 诊断反向 import；assert_not_frozen 在 resume 分支内；proposal 组手写 override 无断言 |
| evaluate_vp_amount_ratio | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| evaluate_vp_signal_parameters | ✅ | ✅ | ✅ | ✅ | ✅ | docstring 锚文本仍写 pre-fund10 代际（代码是 post-fund10），文档陈旧 |
| optimize_core_signal_parameters | ✅ | ❌ | ✅ | ✅ | ❌ | **b 类 FAIL：_fmt 在 focus_dim="volumePrice" 时打印 result["resonance"] 冒充（:122），evaluate 返回无 volumePrice 键（:112-118）**；默认窗覆盖 FINAL 无守卫；docstring 报告名漂移 |
| optimize_gate_denoise_parameters | ✅ | ✅ | ✅ | ✅ | ✅ | evaluate_gate 为 5 个下游共享，纪律状态外溢 |
| optimize_lifecycle_thresholds | ✅ | ✅ | ⚠️ | ✅ | ❌ | `excessMeanFutureReturn or 0` 伪装缺失参与单调性；load_frames 硬编码 04-15~08-14 覆盖 FINAL；docstring "h8" 实际 horizon=1 |
| optimize_ranktrend_parameters | ✅ | ✅ | ✅ | ✅ | ❌ | 默认 --end 2026-08-14 覆盖 FINAL，无守卫 |
| optimize_resonance_parameters（自查） | ✅ | ✅ | ✅ | ⚠️ | ❌ | 默认 04-15~08-14 覆盖 FINAL 且无 assert_not_frozen（evaluate 用于参数决策）；sys.path 硬编码；phase3/4 无 override 断言（dataclass kwargs 构造有 fail-fast 等价保护） |
| optimize_trend_factor_parameters | ✅ | ✅ | ✅ | ✅ | ✅ | 旧 optimize 系中窗口纪律最完整 |
| research_exit_holding | ✅ | — | ⚠️ | ⚠️ | ❌ | 匹配不到信号/netReturn None 静默 continue 无计数；TradeSimulator patch 裸 dict 合并无断言；默认 --end 2026-08-14 覆盖 FINAL |
| scan_repool_sample_floor（自查） | ✅ | ✅ | ✅ | ✅ | ✅ | 2026-09-20 修复后的路径正确；resume 无 schema 版本校验（公共库已解决） |
| track1_dimension_power | ✅ | ✅ | ✅ | ✅ | ✅ | `_save` 只剥 `__out__`（无 `__frames__` 键暂无泄漏，公共库统一兜底） |
| track1_lifecycle_gate_trade | — | ✅ | ✅ | ✅ | ✅ | 代码层无 30 笔降级门槛（M2 仅文档纪律）；报告无 windowsConsumed 元数据 |

## 4. FAIL 明细（3 项）

### 4.1 b 类：optimize_core_signal_parameters.py — focus 明细错位
- `evaluate()`（:88-118）计算了 volumePrice 统计并计入 score，但返回 dict 只含
  synergy/rankTrend/resonance；`_fmt()`（:121-126）在 focus_dim="volumePrice" 时打印
  `result["resonance"]` 的数值并标注 `focus[volumePrice]`。当前 PARAM_TRIALS 7 个
  trial 全部 focus_dim="volumePrice" → 控制台与报告的量价维明细**实为共振维数据**。
- score 本身正确（:97-98 focus 从 vp 计算）。
- 历史污染对照：阶段 8.2 表格为 trend/resonance focus（当时 _fmt 分支正确）、阶段 9.2
  只引用 synergy 主读数——**历史文档无污染**；风险在现状重跑。
- 处置：报告与 skill 均已标注；该脚本重跑前必须修（或由公共库指标装配替换）。

### 4.2 e 类：8 文件默认窗覆盖 FINAL 冻结窗且无 assert_not_frozen
diagnose_cost_sensitivity、diagnose_gate_flip_rate（默认空日期=全量）、
diagnose_signal_return_gap、diagnose_tier_discrimination、diagnose_trend_reversal_jump、
evaluate_strategy_signal_fit、optimize_core_signal_parameters、
optimize_ranktrend_parameters、optimize_lifecycle_thresholds（load_frames 硬编码）、
research_exit_holding、optimize_resonance_parameters——**11 个**。
- 全部写就于 2026-08-19 冻结令之前，历史跑数属于 overfitting-audit.md §4.3/§5 已记录的
  「8 月污染」范围，**不构成新发现的历史违规**；但代码现状默认值+无守卫，**任何一次
  现状重跑即违规**。
- 处置：重跑前必须显式改窗或补 `assert_not_frozen`（公共库 load_frames 已内置守卫，
  迁移后自动解决）。

### 4.3 c 类：optimize_lifecycle_thresholds.py — `or 0` 伪装缺失
- `float(x.get("excessMeanFutureReturn") or 0)`（:50-52）把 None/缺失 excess 按 0 参与
  单调性判定，违反 fail-visible 口径（对照 tier_monotonicity 的 None 传播语义）。
- 影响面有限（A/B/C 档在 lifecycle 维常态有值），但属「伪装缺失」结构模式。

## 5. RISK 明细（按主题分组）

### 5.1 WINDOWS 手写副本（同名不同义）——最需警惕的系统性风险
- `evaluate_ts_factor_weights.py:56-60` 手写三窗字面量（decision/oos1/**oos2=09-01~
  09-12**），与 data_windows 权威 oos2=09-01~09-30 **同名不同义**；下游
  evaluate_vp_amount_ratio、evaluate_vp_signal_parameters、track1_dimension_power、
  diagnose_atr_discrimination 反向 import 该副本（4 文件）。
- `diagnose_regime_saex_decomposition.py:42-46` 另一份本地副本（被
  diagnose_dual_strength_syna 继承）。
- 截断是写就当时有意为之（09-13 后帧当时未落库，后续成为 oos2u 禁令区）——**无 oos2u
  污染**；但报告读者按"oos2"名义解读会错认覆盖范围（实际未含 09-13 后）。
- 教训：与字段路径 bug 同型——复制权威定义替代 import，权威演进时静默漂移。
  evaluate_track2_candidates 的 `WINDOWS = {k: data_windows.WINDOWS[k] for k in ...}`
  派生写法是正面样板（:51-59）。

### 5.2 assert_not_frozen 在 resume 缓存命中分支内（守卫失效面）
evaluate_ts_factor_weights（:375-382）、evaluate_dimension_voting_power（:327-334）、
evaluate_lifecycle_dimension（:392-399）、evaluate_lifecycle_gate_form（:253-260）。
2026-09-15 review I2 已把 cs 系/jump 系/vp 系/track1 系改为无条件执行，上述 4 文件未
回改。scan_repool_sample_floor 为无条件执行（正面样板）。

### 5.3 override 无逐键断言（from_patch 静默忽略面）
from_patch 对未知字段 `if hasattr(...)` 无 else 静默忽略（config.py:408-409）。以下
6 文件走 from_patch 却无 `_assert_overrides_applied`：
evaluate_ma_factor_contribution、evaluate_track2_candidates、
evaluate_dimension_voting_power、evaluate_lifecycle_dimension、
evaluate_lifecycle_gate_form、evaluate_ts_factor_weights（proposal 组）。
diagnose_cost_sensitivity（deepcopy DEFAULT_TRADE_CONFIG）、research_exit_holding
（TradeSimulator patch 裸 dict 合并）同病。dataclass kwargs 直接构造的 optimize_*
（TypeError fail-fast）有等价保护。
正面样板：diagnose_regime_risk_activity 三层断言、evaluate_regime_risk_thresholds
（断言+regime 线序 fail-fast）、evaluate_jump_confirm（锚漂移 RuntimeError 即停）、
evaluate_synergy_tier_thresholds（锚漂移 SystemExit + anchor_chain_of 只断言已跑窗）。

### 5.4 锚纪律不一致
- 漂移即停已代码化：evaluate_synergy_tier_thresholds（SystemExit）、
  evaluate_regime_risk_thresholds（AssertionError）、evaluate_jump_confirm（RuntimeError）。
- 承诺未代码化：evaluate_trend_leftover_parameters docstring 说「锚不复现即停」，
  run_window 无检查；evaluate_lifecycle_gate_form 的 anchorChain 只落盘不 raise。
- 全窗 all() 误报：evaluate_resonance_participation（:286-291）、
  evaluate_trend_leftover_parameters（:379-384）单窗/渐进 resume 时把未跑窗当「锚不
  复现」误报（false alarm 方向，不掩盖真漂移）。
- evaluate_track2_candidates（B-202610 判定器）**无 baseline 锚**。

### 5.5 windowsConsumed / M3 折扣标注不统一
缺失：evaluate_ma_factor_contribution、evaluate_track2_candidates、
evaluate_dimension_voting_power、evaluate_lifecycle_dimension、
evaluate_lifecycle_gate_form、track1_lifecycle_gate_trade 及 diagnose 系多数。
消费 oos2 的判定性 harness（track2/dimension_power/lifecycle 系）均有 docstring 折扣
声明；缺的是机器可读的 `windowsConsumed` 元数据（跨 harness 汇总审计时不可见）。

### 5.6 其他结构性备注
- M2 样本门槛（30 笔降级）仅在 track1_dimension_power 代码化；
  track1_lifecycle_gate_trade 无（文档纪律不强制）。
- diagnose_weak_regime_sampling regime 缺失静默归 normal 桶（对照 `<missing>` 如实
  计数惯例，属伪装缺失模式；当前 replay regime 恒非空无实效）。
- 私有函数 import：diagnose_lifecycle_gate_score 用 tier_monotonicity 的
  _build_lookup/_percentile/_spearman（重构时静默漂移）。
- sys.path/REPORT_DIR 硬编码绝对路径 `D:\dragon-board\quant-board` 普遍存在（36/39）。
- 文档漂移：evaluate_vp_signal_parameters 锚文本（pre-fund10）、
  optimize_lifecycle_thresholds "h8"（实际 h1）、optimize_core_signal 报告名、
  evaluate_trend_leftover 「from_patch 零校验」（已加 len 校验）、
  evaluate_ma_factor baseline「四因子」（22.8 后为五因子）、
  diagnose_dual_strength generatedAt 硬编码。
- evaluate_track2_candidates `if "frames" not in entry:` 恒真 + `# type: ignore`（靠
  巧合正确，未来改动会 NameError——响亮失败，可接受但应重构）。

## 6. 历史结论污染对照（阶段 0-26 × L1 ledger × overfitting-audit）

| 审计发现 | 历史结论影响 | 依据 |
|---|---|---|
| a 类字段路径（本次事故型） | **零同类历史污染**：39 文件无一处 signal["observation"] 顶层错读；P_repool 事故是孤例（已更正） | 4 路审计逐文件取证 |
| optimize_core_signal b 类错位 | 阶段 8.2（trend/resonance focus，_fmt 分支当时正确）、阶段 9.2（仅 synergy 主读数）未引用错位明细 → 无污染 | 长测文档 §8.2/§9.2 表格列口径 |
| 11 文件默认窗覆盖 FINAL | 历史 769 帧跑数（阶段 7-11，08-17~19）属 overfitting-audit §4.3/§5 已记录的 8 月污染，非新发现；冻结后（阶段 12+）harness 全部显式传窗或 import WINDOWS，无 FINAL 违规 | overfitting-audit.md §4/§5；阶段 12+ 各 docstring |
| WINDOWS 副本 oos2=09-01~09-12 | 阶段 12-26 的"oos2"读数实际只覆盖 09-01~09-12；09-13 后帧当时未落库，oos2u 禁令（09-16 设立）未被触碰 → 无 oos2u 污染，但引用这些阶段"oos2"读数时须按 09-12 截断口径理解 | evaluate_ts_factor_weights:56-60 及下游；data_windows.py:33-36 |
| fund10 已落默认 × evaluate_track2 | 阶段 20（09-13 跑）当时默认仍为 20.0，fund10_over2 是真实扰动 → 历史判定卡有效；**B-202610 批次复跑前必须修**（否则 P1 复验 trial 退化为单轴扰动，判定卡失真） | 长测文档 §25.7（09-15 落默认）与 §20（09-13 跑）时序 |
| maWeight=0.37 落默认 × evaluate_ma_factor | 阶段 17（09-12 跑）当时仍四因子 → 历史结论有效；批次复跑前 baseline 语义需更新 | 长测文档 §22.8（09-13 落默认）时序 |
| resume 分支守卫缺失 ×4 | 4 文件均为全窗首跑产出（非 resume 恢复），守卫当时实际执行 → 无历史污染 | 各阶段执行记录 |

**结论：本次审计未发现「已污染历史文档结论」的新案例；P_repool 假阴性仍是唯一事故。
所有 FAIL 均为「现状重跑会污染」型，已给出前置修复项（§7）。**

## 7. 处置与衔接

### 7.1 立即（本次落地）
- 公共库 `backend/operations/harness_common.py`：load_frames（内置 assert_not_frozen
  无条件执行）+ 信号访问器（sample_status_of / dimension_tier_of 统一走
  tier_signal_of）+ 指标装配（status_buckets/tier_summary/sa_excess）+ 报告落盘
  （schemaVersion 校验 resume、剥 `__frames__`、写 windowsConsumed/nature）+
  已知答案校验器（mini replay 结构断言）——五类风险各对应一个能力。
- scan_repool_sample_floor.py 改造为第一个使用者（双窗读数回归不变）。
- skill 扩充：harness 工程范式 8 项 → 13 项（新增字段路径单一源、已知答案校验、
  分析脚本键名复核、结论×机制交叉验证、WINDOWS 派生而非复制、resume 守卫无条件）。

### 7.2 B-202610 批次执行前必须修（前置修复项）
1. evaluate_track2_candidates：补 baseline 锚 + override 断言；fund10_over2 trial 相对
   新默认（10.0）重新定义扰动轴或显式标注「fund 轴已落默认，本 trial 仅测 over 轴」。
2. evaluate_ma_factor_contribution：baseline desc 更新为五因子口径（或固定 patch 复现
   四因子基线）。
3. optimize_core_signal_parameters：修 _fmt/evaluate 返回缺 volumePrice 键后再跑。

### 7.3 下一批改造（不阻塞批次）
- WINDOWS 二手副本 5 处改为 data_windows 派生写法（evaluate_ts_factor_weights 为源头）。
- assert_not_frozen 提出缓存命中分支（4 文件）。
- 锚纪律统一为「漂移即落盘+停」+ anchor_chain_of 只断言已跑窗（3 文件）。
- windowsConsumed 元数据补齐（6 文件）。
- 旧 optimize_*（2026-08 中旬 5 文件）重跑前补守卫（公共库迁移时自动解决）。

### 7.4 本批改动的行为变化披露（review 2026-09-21 补）
- **load_frames 冻结守卫 fail-fast 影响面**：harness_common.load_frames 内联
  assert_not_frozen 后，仍保留默认 `--end 2026-08-14` 的未迁移 harness
  （optimize_ranktrend_parameters、optimize_core_signal_parameters）按历史命令行重跑
  会**当场 raise**——这是 e 类 FAIL 修复的本意，不是故障；重跑请显式
  `--end 2026-07-31` 或分窗加载。转发函数支持 `purpose="report"` 透传（仅最终报告
  呈现允许加载含 FINAL 帧的窗口）。769 帧全窗（04-15~08-14）的 phase3/4 历史结论
  逐位复现通道随冻结纪律关闭（历史结论以文档记录为准）。
- optimize_resonance_parameters 默认 `--end` 修为 2026-07-31（decision 窗）。
- scan_repool_sample_floor：报告新增 `schemaVersion`（repool-scan-v2），旧格式缓存
  resume 被拒绝时全新跑并 stderr 提示；windowsConsumed 改为跨进程并集（resume 不再
  丢失历史消费记录）。

## 8. Review 修复记录（2026-09-21，同日）

本批改动提交前经自查 + 独立 review 代理双重审查，修复：

1. **Critical（渐进 resume 假 0，改造前已潜伏）**：scan_repool run_window 中
   baseline_status 只在 floor5 实跑时填充——baseline trial 已缓存而后续 trial 缺失的
   resume 场景下，newlyJudged 会被空对照伪装成全 0（「无新增样本」假结论）。修复：
   检测到 baseline 已缓存且存在缺失 trial 时重算 baseline status map（replay 确定
   性，读数与首跑逐位一致，仅不重复落盘）。新增 tests/test_scan_repool_resume.py
   三用例防线（含出池回池合成场景）。
2. **Important**：load_resume 丢失旧 windowsConsumed → 并入 `__consumed__`，save 时
   与本进程消费窗取并集；known_answer 校验器的 `from_patch({"minSampleCount": 3})`
   是死参数（字段不存在、from_patch 静默忽略——恰是审计 d 类模式）→ 改裸构造
   `RankTrendConfig()`；结构断言补齐 rankTrend 九键（+jump/executionStrategy）；
   resume 被 schema 拒绝/文件损坏时 stderr 显式提示（不再无声丢弃缓存）。
3. **Minor**：测试名名实对齐（test_known_answer_confirms_top_level_structure）；
   load_resume 的 `**cached` 展开顺序（防手编文件覆盖内部键）；模块 docstring 能力
   分组数与实际一致；立项文档 §6 标题重复 typo 顺手修复。

## 9. 审计方法备注

- 4 路并行子代理逐文件 Read 取证（总计 39 文件），关键 FAIL（optimize_core_signal
  _fmt）与判据（DIMENSION_PATHS / tier_forward_returns 返回键 / WINDOWS /
  ALL_STANDARD_WINDOWS 引用）由主代理二次 Read 实锤复核。
- rg 输出渲染 bug（"observation"→"ln"）实测确认存在；全部结论以 Read/python 原文为准。
- 本文档为审计快照；后续修复以 git 记录为准，本节不逐项回填。
