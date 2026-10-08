# EOD 情绪规则链全面梳理与优化方案（2026-10-08）

> 触发：用户裁决「先不跑存量历史情绪文档，对 EOD 情绪规则逻辑进行全面梳理，给出优化意见和方案」。
> 接续关系：本文不重复 10-05 GLM a1 研讨（glm53-eodrule-a1）、10-06 amountVsSame 评估、10-06 T1 预测评审
> 已覆盖的内容，只在其基础上立案新发现与遗留项。当日上下文：10-08 已落地 map_stage 中段方向感知
> （emotion-score-map-stage-direction-preregistration.md）与 hero 改 jev 优先。

## 一、链路现状全图（七层）

| 层 | 实现 | 关键事实（读码/实测核实） |
| --- | --- | --- |
| 1 生产 | `run_for_date_slots` 逐槽 + 收尾 EOD | EOD=锚定 15:00 帧**单槽截面重算**（非全天聚合）；EOD slope 的 history 严格早于 15:00 槽（防同帧 slope=0，刻意设计） |
| 2 证据 | `collect_slot_evidence` | 与 jev 轨道同源；含昨日同期成交额、displayStatus join、涨停结构 |
| 3 评分 | `compute_emotion_score` | 8 维**等权**（_WEIGHTS 全 1），score=有效维简单平均；_CALIB 分位校准（4 维 1067 槽 / trin 1052 / yh 1066 / limitStruct 仅 198 槽 18.6% 覆盖 / amountVsSame 设计值） |
| 4 映射 | `map_stage` | 75/60/40 函数内硬编码；[40,60) 已接 slope<0→退潮（10-08 预登记 A） |
| 5 确认 | `stage_confirm.confirm_stage` | **每日重置**；首槽截面直接确认；候选连续 2 槽才切换、回摆清空 |
| 6 诊断 | pathDiag / activeDims / ecosystemBreak / legacyCascadeStage | pathDiag（dayHigh/dayLow/drawdownFromHigh/bounceFromLow）**明确不进档位链**，只做裁决原料；legacy 双轨留档 |
| 7 消费 | ①hero（现 jev 优先）②sentiment_2b 相位（EOD≥60）③脉拍四带 ④regime `REGIME_STAGE_ADJUST` 查表 ⑤runtime 类别门控（退潮/冰点→D_EXIT_RISK 等，缺失 fail-open）⑥日度一句话 ⑦C9 深谷(<25)/C10 高峰(≥75) 账本 | 决策面全部消费**规则** stage/score；显示面 hero 已切 jev |

## 二、新发现（按优先级）

### P1-1（已发生，需立即裁决）amountVsSame 第八维已自动激活，与 10-06 评估「暂不启用」矛盾

- **实证**：2026-10-08 EOD `amountVsSame` dim 已生效——raw=17.5pp（今日 vs 09-30 放量），sub=67.5，**activeDims=8**，skippedDims=[]；09-30 及之前全部 skipped（昨日无 totalAmount 帧）。
- **影响**：今日 score 44.8=8 维均值；7 维口径应为 **41.6**（被拉高 3.2 分）。与 10-06 模拟完全吻合（「深谷 +3.2/高峰 −3.0，20 次阈值穿越全部指向中位」的尾部稀释器）。今日档位/相位/分带恰好未穿越阈值，但 C9/C10/深谷账本的系统性稀释风险已在评估报告量化。
- **根因**：评分维无门控——`amount_pct is not None` 即激活（emotion_score.py `_sub("amountVsSame", ...)`）；代码注释（10-05 方向二 §六#8）预期「10-09 激活」，10-06 评估（更晚）建议「暂不启用、只记录」（建议 2 已落地为 record_amount_vs_same 步，建议 1 未落地为门控）。**两份文档结论相反，代码静默跟随了更早的一份。**
- **连带**：跨日代际混用——09-30 是 7 维分、10-08 起 8 维分，日度一句话的近 20 日分位锚、哨兵分歧、prev-EOD 对比在代际边界上不同质（activeDims 字段已为此设计，但消费方未分段）。

### P1-2 EOD 档位方向输入=末步差分，存在「尾盘反抽日」残余缺口；pathDiag 闲置

- EOD slope = 15:00 − 14:30（末步）。全天单边下行但尾盘 30 分钟反抽 +1 分的日 子，slope>0 → 仍判「启动」——与 10-08 修复同族的残余面。
- **pathDiag 已有现成日级方向量**（drawdownFromHigh/bounceFromLow，逐 EOD 落库）却按 2026-10-05 设计「不进档位链」。09-24 经典分歧日（59.7→24.6→50.6）在旧 slope 口径下 EOD slope=−2.3 判退潮 ✓，但「跌一天尾盘拉回」型仍无解。

### P1-3 map_stage ≥60 段方向盲区（同族问题上一档）

- [60,75) 区间 slope 不参与：score 62 从 75 峰回落（slope −13）仍判「发酵」。与已修的 40-60 问题同构，只是档位高一档；regime 调整 +5 vs −6 的口径差在边界 60 处跳变（59.9/−20→退潮 −6，60/−20→发酵 +5）。

### P2-4 校准时效机制缺失

- _CALIB 冻结于 2026-09-30（1067 槽）；无重校准节奏、无分布漂移检测；limitStruct 198 槽/18.6% 覆盖自证待重校。十月情绪结构若漂移，分位锚失真不可见。

### P2-5 等权 8 维的族间失衡（诊断先行，不直接调权）

- 风险族 2.5 维（riskShare/riskRowsPct/炸板率入 limitStruct）vs 攻击族 1 维（attackShare）；trin 与 upRatio 部分共线。今日实证：risk 族三 sub（64.4/71.7/炸板侧）齐高压分而 attack 44.9——分数被风险族主导。调权是高影响动作（T5/T6 已证明档位迁移对门控的放大效应），必须先诊断后动。

### P2-6 确认链首槽直接确认语义

- 每日重置 + 首槽直接确认：09:30 单帧（样本最少）即成「确认档」。节后首日 09:30=61.6 直接确认发酵；若昨日退潮今日高开，第一槽即翻档，confirmSlots=2 对首槽无保护。

### P2-7 显示层/决策层双轨合同未文档化

- hero 已 jev 优先，但 regime/门控/脉拍/相位全部仍消费规则 stage/score。哨兵分歧监控已存在（只告警不改判），但「显示 jev、决策规则」的合同未在任何文档声明——用户视角可能误读 jev 档位驱动交易链（§1.2#5 同步义务）。

### P3（登记不立案）

- REGIME_STAGE_ADJUST 裸常量无出处注释（config 可覆盖且在优化搜索空间，GLM a1 已点名）；
- runtime allow 门 hotlist 缺失 fail-open=True（缺失放行 vs 阻断的哲学选择，已有研讨记录）；
- EOD 文档与 15:00 槽文档内容重复（alias 语义，下游已各自处理，无需动）；
- map_stage 边界 75/60/40 硬编码（GLM a1 点名；若 P1-2/P1-3 立案则随预登记一并常量化+出处化）。

## 三、优化方案（菜单，全部预登记制）

| # | 事项 | 方案 | 时机 | 成本 |
| --- | --- | --- | --- | --- |
| A | **P1-1 第八维门控**（需先裁决） | 二选一：①按 10-06 评估加显式 skip 门（冻结至 ≥20 日样本重校准后再启）；②若裁决有意激活，则更新评估文档结论 + 接受尾部稀释 + C9/C10 账本口径重登记 | **立即**（每日都在写 8 维分） | ①≈10 行 + 测试；②纯文档 |
| B | P1-2 EOD 方向输入升级 | EOD 档位的方向量从末步 slope 升级为 pathDiag 组合（如 drawdownFromHigh≤−8 → 退潮、bounceFromLow≥+8 → 启动修复，阈值预登记冻结后回放）；盘中槽保持末步差分（响应性） | 短期 | 预登记+回放+单测 |
| C | P1-3 ≥60 段方向 | [60,75) 接强负 slope（如 <−10 → 退潮）消除 60 边界跳变；与 B 同份预登记合并回放 | 与 B 合并 | 同上 |
| D | P2-4 校准时效 | 月度滚动重校准 + 分位漂移告警（P10-P95 偏移>10 分触发）挂盘后链 advisory 步；limitStruct 满 500 槽后随批重校 | 中期 | 中 |
| E | P2-5 维度诊断 | 方差分解 + 「与 jev 档位一致率」敏感性分析诊断脚本（零写库零调用），有实证再谈权重 | 中期 | 低 |
| F | P2-6 首槽语义 | 首槽继承昨日 EOD 确认档为初始态（预登记+回放）；或维持现状仅文档披露 | 低优 | 低 |
| G | P2-7 双轨合同 | 在 jev-daily-line-design 或独立小节声明「显示层 jev 优先 / 决策层规则优先 / 哨兵分歧只告警」三原则 + hero tooltip 补一句 | 立即 | 极低 |

## 四、建议裁决顺序与执行记录

**执行记录（2026-10-08）**：A-① 已裁决执行（用户「先A」）：第八维冻结门落地
（`emotion_score._AMOUNT_VS_SAME_ENABLED=False`）+ 今日全天（10 槽+EOD）重算回 7 维
（EOD 44.8→41.6，stage 启动→退潮，与 jev day_stage/旧级联三方一致）；旧 8 维文档快照归档
`data/backups/hotlist_sentiment_8dim_20261008.json`；接线守卫测试 monkeypatch 开门验证不回归。
日度一句话/带/相位合同验证不变。B+C 已裁决接续执行。

**B+C 执行记录（2026-10-08）**：预登记 emotion-score-map-stage-bc-preregistration.md（判定线冻结
于回放前：EOD path={dd}，≥60 段 dd≤−8 或 slope<−10 →退潮，中段 dd≤−8 补充 slope<0，
bounce 不入映射〔锄案例 09-24 裁决 dd 优先〕）；回放 114 日：迁移 8 天（启动→退潮 5 +
发酵→退潮 3，其它零触碰），阈值平台稳定（−6/−8 同结果、−10/−15 腰斩），V 型披露面 16 天；
实现 map_stage path 参数 + EOD 接线（pathDiag 前移，盘中槽零行为变化）；今日重算验证
41.6/slope−14.1/dd−23.4 → 退潮不漂移；tests/hotlist 296 过 + 后端全量 3356 过。

1. ~~今天先裁 A~~（✅ 已执行，见执行记录）
2. ~~B+C 合并预登记~~（✅ 已执行，见执行记录）
3. D/E/F/G 排入常态节奏。
