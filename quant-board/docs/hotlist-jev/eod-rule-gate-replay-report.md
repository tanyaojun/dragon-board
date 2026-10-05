# 方向二执行报告：情绪档位切换门控传播 replay（2026-10-05）

来源：GLM-5.3 EOD 规则分研讨方向二（reasoning-corpus-eod-emotion.md §7），用户"确认请执行"。
脚本：`backend/operations/emotion_score_gate_replay.py`（只读，全程 find；参照 emotion_score_stage_adjust_diff.py 前缀重放法）。
明细：`.tmp_research/gate_replay_20261005.json`。

## 一、门级迁移矩阵（slot 级 n=1071，实际 riskLevel 口径）

| 门 | 关→开 | 开→关 | 不变 |
|---|---|---|---|
| D_EXIT_RISK | 138 | 198 | 735（325+410） |
| allow_a_main | **0** | **0** | 1071 |
| allow_b_ignition | 198 | 138 | 735 |

EOD 级（n=113）：D_EXIT_RISK 关→开 4 / 开→关 32；allow_a_main 全不变；allow_b 同 D_EXIT 镜像。

## 二、结构性发现（比矩阵本身更重要）

1. **riskLevel 全库恒"高"（1071/1071，4-9 月无例外）→ allow_a_main 是死门**：`stage∈(高潮,发酵) and risk≠高` 的 risk 条件永假，该门在整个数据集上从未开启。T6 的「放松 293」按风险无关口径统计，实际传播中 allow_a 的放松**一次都没发生**。
2. **allow_b_ignition ≡ ¬D_EXIT_RISK（镜像门）**：五档分类下两门覆盖集互为补集，矩阵逐格相同（325/410/198/138）——三道门实际只有**一道独立闸**（D_EXIT_RISK 出场风险姿态），allow_b 是它的镜像记号。
3. 推论：门控不对称讨论（Q3）的真实传播面 = D_EXIT_RISK 单闸 138 放松 / 198 收紧（slot 级），远比三门口径的 293/144 简单；「类别切换效应远超 regime ±2.44」结论不变，但载体是单闸。

## 三、对账门：PASS（带两笔登记）

| 迁移对 | replay | T6 基准 | 判定 |
|---|---|---|---|
| 放松 退潮→启动 | 153 | 153 | ✓ |
| 放松 启动→发酵 | 88 | 88 | ✓ |
| 放松 退潮→发酵 | **36** | 34 | ✗ +2 |
| 放松 启动→高潮 | 18 | 18 | ✓ |
| 放松 退潮→高潮 | **9** | （枚举遗漏） | 补登记 |
| 收紧 启动→冰点 | 123 | 123 | ✓ |
| 收紧 启动→退潮 | 15 | 15 | ✓ |
| 收紧 发酵→启动 | 6 | 6 | ✓ |

- **收紧 144 精确复现**；
- **放松实为 304 = T6 的 293 + 退潮→高潮 9（T6 枚举漏计，≈号下的真实遗漏）+ 退潮→发酵 +2（population drift）**；
- 退潮→发酵按日分布：4/20(1) 5/13(1) 5/28(1) 9/14(8) 9/17(5) 9/22(5) 9/28(2) 9/29(10) 9/30(3)——+2 最可能=T5 时点后 09-30 恢复重算的文档增量（覆写注记同源），具体槽位需 T5 明细对账，非关键路径。

## 四、锚定门：PASS

09-24：10 槽+EOD 全部 旧=退潮→新=启动，每槽门变化=[D_EXIT_RISK 解除, allow_b 开启]——与 GLM 预期「旧档触发收紧/D_EXIT_RISK、新档开 allow_b_ignition」逐字一致。09-29：10 槽+EOD 全部 退潮→发酵，同款门变化。

## 五、regime state（70/50/30）跨线矩阵——scope 登记为另批

market_regime 需完整 frame（stocks 行级五因子），snapshot_frames 为瘦文档（仅 _id/snapshotId/slotTime），完整重放需全窗 dry-run 装配链（T6 §4 原文即此路径）——**另批执行**，本报告以 stage 分量 Δ 分布（T6 已有：+≤5 桶 24 天/+≤8 桶 21 天/+>8 桶 9 天/−侧 23 天）为代理上界。

## 六、三项零成本缺口比对（GLM 证据不足清单 #1/#8/#9）

### #1 09-24 逐槽 dims/skippedDims（规则轨）
- **limitStruct 在 4/10 槽缺失：11:00、11:30、14:00、15:00**——**EOD 锚定帧（15:00）在缺**：EOD 50.6 是 6 维归一化产物，而 13:30 的 24.6 是 7 维（limitStruct 在场）——**两个关键分数的维度基底不同**；
- amountVsSame 全槽 skip（见 #8）；diagnostics 全空（无结构化诊断行——limitStruct 缺失未产生诊断标注，fail-visible 缺口）；
- **Q1 裁决被阻塞**：GLM 决策树节点 1b 出口命中（"系统性缺失→分数是残缺维归一化产物，补齐/标注后才可裁决"）——09-24 分歧的最终归因须待 limitStruct 缺失处理（补数或标注）。

### #8 amountVsSame skipped 率
- **1071/1071 = 100.0%**（9 月单独 206/206）——该维**从未参与过打分**，八维实际全程七维；其校准表为设计值、从未被数据检验；
- **⚠ 10-09 维度基数跳变预警**：totalAmount 随 live 采集 10-09 起自带（§十三已验证），该维将首次激活——有效维 7→8，等权平均的分数基数变化使 **10-09 前后的规则分不可直接比**（同 jev 轨道 questionSetVersion 断层的规则版）。10-08 前需决定消费方标注方式（skippedDims 已 fail-visible 落库，但下游是否感知待查）。

### #9 jev 轨道对 09-24 的判读（v2.5 重算语料）
- frame_stage：10 槽 = retreat×6 / start×3 / ferment×1；温度 32.4-51.3，15:00 冲 68.1；
- EOD：day_stage=**ferment**、day 温度 **59.9**；
- **两轨对照**：规则轨 EOD=启动 50.6、jev=ferment 59.9——**两轨都不同意用户盘感的"退潮"**（jev 甚至比规则再偏强一档）。Q1 节点 2c 的 T+1 后验仍缺，但两轨截面语义一致指向"当日非退潮"→ 强化 GLM 的**语义错配假设**（用户"退潮"≈路径回落语义 S2，两轨 EOD 标签均为截面/全天汇总语义）→ 支持方向一（路径诊断字段）的价值。

## 七、待裁决

1. 方向一启动与标注样本来源（≥8-10 分歧行，日常盘感复核积累）；
2. **10-09 维度基数跳变的消费方标注**（本报告 §六 #8 预警——10-08 前需定）；
3. Q1 裁决先处理 limitStruct 缺失（#1）——补数（THS 当日 4 槽盘中 limit 块不可回补，EOD 锚定帧能否补需查 15:00 帧 limitSummary 实况）或标注带缺口裁决；
4. riskLevel 恒"高"的代码级归因（级联 risk 逻辑为何 4-9 月无一天非高——是真行为还是默认值缺陷，独立小课题）。

## 八、追加执行（2026-10-05 晚，用户"确认请执行"批次的 ③④ + ①② 落地）

### ③ Q1 limitStruct 只读试算（零写库）

09-24 15:00 帧在场 limitSummary（ztCount=51/maxBoard=6/rate=16.39/seal✓，e77907bb 帧回填晚于 T5 重算的时序错位）喂 compute_emotion_score：
- 库内 6 维 score=50.6 → 试算 7 维（limitStruct sub=71.2 在场）score=**53.6**（Δ+3.0），档位不变（启动）；
- **裁决定案（带缺口）**：无论 6 维还是 8 维态，09-24 均判启动且方向向上——补数让分数离"退潮"更远；叠加 jev 轨道 ferment/59.9，**两轨三读数（50.6/53.6/59.9）一致不支持用户盘感"退潮"标签** → Q1 归因定案=**语义错配**（用户"退潮"=路径回落语义 S2，系统 EOD 标签=截面语义），正解=方向一路径诊断字段（已落地，见下）。不做历史重算。
- 全库 limitStruct skip 48.6%（520/1071）：登记为 T5 时序注记，不回写（回写=重算半库+T5/T6 基线漂移，limitStruct 仅 1/8 权重，收益不抵）。

### ④ riskLevel 恒"高"归因（侦察定案）

- 机制：`_resolve_risk_level`（sentiment.py:1078）——"高" ⟸ risk_pressure=severe（riskShare≥0.35）或 (high+continuity weak)；
- 实测：**riskShare 全库 min=0.578 / 中位 0.925 / max=0.988，≥0.35 占比 100%** → severe 恒真 → riskLevel 恒"高"是**判据阈值与数据分布的错配**（0.35/0.2 为 TS 移植设计值，而热榜池风险行占比天然 58-99%），**非代码缺陷**；
- 与审计 B3 同根因（riskRowsPct P10=84.7 系统性高位→高潮压制条款删除）——同一口径在两处的第二次显形；
- **影响面**：allow_a_main 死门（`risk≠高` 永假）→ 高潮/发酵的 A 类主池门历史上从未因情绪开启，实际门控=D_EXIT_RISK 单闸+fail-open；
- **处置：不改判据**（sentiment.py 为 golden 对齐文件，riskLevel 在 golden 守护清单，动阈值=红线级 T5 工程且须 golden 重锚+replay）；登记为已知行为，修复与否留用户裁决（修复路径=阈值重标定预登记+golden 重锚）。

### ①+② 落地（TDD，hotlist 专项 288 过+面板 28 过+vue-tsc 干净）

- `emotionScore.activeDims`（=8−skipped）：维度基数戳，10-09 amountVsSame 激活 7→8 后跨日可比性按此分段（历史文档缺键=旧代 fail-visible）；
- `emotionScore.pathDiag`（dayHigh/dayLow/drawdownFromHigh/bounceFromLow/points，score=None→null）：方向一路径诊断，**不进 map_stage/档位/regime/门控链**；
- limitStruct skip 诊断行 `emotion_limitstruct_unavailable:limitSummary 缺失（涨停结构维跳过）`（独立 if 不遮蔽 slope 链）；
- 前端：HotListEmotionScore 类型加两可选字段；hero 分数 tooltip 补「有效维 x/8」+「日内高点/低点（自高点/自低点）」段——**10-09 跳变的消费方标注=activeDims 进 tooltip，路径语义=盘面上可读**；
- 测试：新增 3（activeDims 三态/pathDiag 方向语义/诊断行有无）+ 修 1 fixture（diagnostics 默认空锁 schema 测试补 limitSummary）；实现中拦下自伤一次（诊断 elif 遮蔽 slope 链）。

### 生效与遗留

- 8001（写口）与 8000（lazy compute/API）需重启加载；Redis analyze 键清缓存；
- 遗留：regime state 矩阵（装配链，另批）；盘感分歧行标注 ≥8-10 例（日常积累）；riskLevel 修复决策（用户）；`emotion-limitup-code-audit-20261005.md` 待读（是否与 limitStruct 时序错位相关，未查）。
