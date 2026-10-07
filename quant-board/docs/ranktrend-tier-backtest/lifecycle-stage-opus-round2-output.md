# 生命周期 P1/P3 预登记合同 · Opus 4.8 第二轮输出（2026-10-07，归档原文）

> 投喂：`lifecycle-stage-opus-round2-prompt.md`（同会话续贴）。审定见语料 §11.2。
> 本文件为模型输出逐字归档，不构成改动授权；判定线按合同冻结语义执行。

---

# P1 / P3 预登记合同（范围收窄版）

范围确认：本轮只做 P1（绝对名次阈值池规自适应化）与 P3（序列时间正规化）；P2 待 dv 重叠率/增量检验设计另批，P4-阶段2 门槛已因 c1 读数（降档腿 decision −39.4%/oos1 −34.4%/oos2 −5.8% rel，正价值确认）在信号面判 FAIL，P5 前置未跑。已吸收新事实：dv 维现状（单帧四态、票权 0.0 纯观察）、vp E→D 短路真保护旁证（e1a 主窗 wrxpf −32%）、veto 腿无独立关断臂（a3 无读数，跨基线粗估仅 ~10% 量级参照）。**两案均不依赖 a3 replay，不依赖 P2 读码结论。**

**冻结声明**：以下判定线在任何 replay 执行前冻结；跑后不得回看调线。全部内容为待验证假设，不构成改动授权。

---

## 合同 A：P1 绝对名次阈值池规自适应化（L1）

### A1. 考题（一句话，冻结）

绝对名次口径阈值（热区 rank≤10、best≤5/10/12/20/25/30、drawdown 格数）在池规模时变下是否产生跨池规模组的判层系统性分歧（末态级分歧率超线），且换算为 T=200 锚等价分位线后该分歧收敛、同时三窗 saEx 全部不低于 no-regression 线？

### A2. 门判据（全部量化）

| 线 | 定义 | 数值 | 理由 |
|---|---|---|---|
| 诊断主判定线（进行为步） | 末态 stage 分歧率 ≥2%，或 veto/bd 末态分歧率 ≥1%，或任一关键谓词在任一 T 三分位分歧率 ≥5% | 见左 | stage<2% 时下游改判上限不足 B/D 降档足印（4.3%，§4.2-H）的一半，任何读数不可分辨；veto 1% ≈ 其触发率 8.4% 的 12% rel，足以移动翻转率；谓词线取 stage 线 2.5 倍，反映 §2.3 滞回对单帧谓词翻转的阻尼 |
| no-regression 线 | 三窗 saEx 各 ≥ 锚−0.005 绝对（即 ≥0.0994/0.0868/0.0883），且三窗均值 ≥0.0965−0.003=0.0935 | 见左 | d1/d2 三窗逐位零效应（§4.3-C）表明 replay 确定性、无噪声，容差只需挡「经济上无意义的小真效应」；−0.005 略紧于史上被采信行动的最小腿部（c1 oos2 −5.8% rel ≈ −0.0054 绝对）；均值线防三窗各 −0.004 溜过 |
| veto 稳健带 | decision 窗 veto 触发率 rel 位移 ∈ [−10%, +10%] | 见左 | 出带须与三分位分歧表对账（位移应可由小池/大池日重分布解释），不可解释即否决 |
| 终止条款 | ①诊断线未达；②T 分布退化：p5–p95 ∈ [190,210] 或 T<75 帧数=0 且全部谓词分歧 <3%；③L2 否决 → 全案终止（L1 仅作归因隔离，不作落默认候选——除非诊断显示 rank 臂非冗余且 L1 自身有实质分歧收敛）；④条件步 Track 1 wrxpf 低于 §4.4 线或劣于基线 → 不提交落默认 | — | 尺度混杂不存在时 L1/L2 近 no-op；「通过」仅意味着提交用户裁决落默认（§5 golden 锁），不自动写回 |

### A3. 窗口与数据

- saEx 判定线只在三窗：decision 2026-04-15~07-31 / oos1 08-15~31 / oos2 09-01~12；全部 run 用 769 帧全窗 replay（§1、§5 评估链）。
- **追加 2026-08 冻结段（202 帧）为第四报告窗，仅作过程指标**：veto/bd 翻转率历史基线（0.1376/0.0834，§4.2-I）只在该段以 comparable-pair 口径测过，追加才能对账；该段不设 saEx 判定线，与 oos1 的帧重叠与否不影响判定（重叠帧按其口径自然计入过程指标）。
- 报告项（不设线）：A/B excess 单调性确认不恶化（§4.1-E 已证分位结构，本案不期待改变，只确认）。

### A4. 诊断步产出 schema（可直接落脚本）

数据源：1 次默认配置 replay 的导出（逐帧 history stocks + 每股每帧序列与末态），离线复算；谓词/末态复算优先直接 import lifecycle.py 纯函数（raw_stage/normalize_stage/cycle_confidence 均为纯函数，§2.2–2.4）。若 decision 层的 risk/momentum 注入与 stage 存在耦合导致离线复算不可行，回退为「flag=on 再跑 1 次 replay」取末态（成本 +1 次，预登记在此）。

```
帧级 frames:      frame_id, trade_date, window_label(decision|oos1|oos2|frozen|full),
                  regime_bucket(strong|ebb|transition), attention_total
股帧级 stock_frames: frame_id, code, rank, pct,
                  verdict_mixed{warm, hotzone, best_le(5|10|12|20|25|30), drawdown_ge(1|2|3)},
                  verdict_pct{同键}, disagree_flags, pct_direction(looser|tighter)
末态级 outcomes:  frame_id, code,
                  stage_mixed, stage_pct, rawStage_mixed, rawStage_pct,
                  tier_mixed, tier_pct, veto_mixed, veto_pct, bd_mixed, bd_pct,
                  disagree_stage, disagree_gate
聚合表1 T 分布:   window×bucket → n, mean, std, min, p5, p25, p50, p75, p95,
                  share_T_lt75, share_T_lt60
聚合表2 分歧表:   predicate × T_tercile(T1|T2|T3|all) → n, disagree_rate,
                  pct_looser_share, pct_tighter_share
聚合表3 末态分歧: outcome(stage|tier|veto|bd) × T_tercile → n, disagree_rate
```

口径注：T 三分位点在诊断 run 落档时冻结；换算锚 T=200，rank R ⇔ pct=(201−R)/2（R=5→98.0、10→95.5、12→94.5、20→90.5、25→88.0、30→85.5）；drawdown 1 格 ⇔ 0.5 pct 点（2 格=1.0、3 格=1.5）；best 谓词的 pct 形态 = max(尾 8 帧 percentiles) ≥ 对应线；T≥75 时热区 rank≤10 臂已被 pct≥88 臂覆盖（0.12T+1≥10），T≥60 时已被 pct≥85 臂覆盖（0.15T+1≥10）——rank 臂只在极小池日起作用，share_T_lt75 直接量化其存在性。

### A5. 行为改动步 trial 设计（单变量 ≤3 档）

单变量 = `lifecycleRankScaleMode`（枚举）：
- **L0 = mixed**（现状，新代码自证锚复现）；
- **L1 = hotzone_pct_only**：仅热区 rank 臂删除（热区=纯 pct 线；预期近 no-op，作小池日影响隔离档；若诊断显示 T<75 帧数=0，跳过本档省 1 次 replay）；
- **L2 = full_pct**：全部名次类阈值（§2.7 的 10 个 BestRankMax 字段 + drawdown 族含残留硬编码 ≥2 格 + 热区）换算 T=200 等价分位线。

剂量递进：L2 是唯一有实质一致性收益的档；L2 否决即全案终止。语义 tradeoff 预先声明：pct 统一后「小冷池的第 5%」与「大热池的第 5%」注意力强度不再等价（位置语义取代强度语义），后果交由 no-regression 与过程指标实证，不预设优劣。

### A6. 回退与开关

`lifecycleRankScaleMode="mixed"` 默认=原行为，零行为变化（§5 参数化路径）；回退=开关回 mixed，config diff 即回退面；config_hash 区分代际；候选值不自动写回默认。

### A7. 成本

诊断 1 次 replay + 离线复算；L0 自证 1 次；L1 条件 1 次；L2 1 次；Track 1 条件 1 次。**合计 3–5 次分钟级 replay**（坐标下降 ~20 次的 ≤25%）+ 新写薄诊断脚本 1 个（~150 行）。

### A8. 复用 harness 清单

| harness | 用在哪步 | 缺什么 |
|---|---|---|
| evaluate_lifecycle_gate_form.py | 行为步三窗 saEx + veto/bd 触发率 | 需加 lifecycleRankScaleMode 的 config plumbing（参数化路径） |
| diagnose_gate_flip_rate.py | 冻结段 comparable-pair 翻转率，对齐 0.1376/0.0834 基线；per-code 翻转方差（次级观察） | 需支持按候选 config 复跑（若现只跑默认） |
| optimize_lifecycle_thresholds.py | 复用其 config 覆盖与 replay 执行机制（不用搜索模式） | 无 |
| track1_lifecycle_gate_trade.py | 条件终判步 | 无 |
| diagnose_lifecycle_gate_score.py | 不用（本案无 score 线） | — |
| 新写 diagnose_lifecycle_scale_mix.py | A4 诊断（复用 replay loader，挂 runtime.py:1074 循环） | 新写 |

### A9. 依赖声明

无未决依赖（attention_total 由 attention_rank_lookup 返回值逐帧重算，§1.1）。**假设项**（非依赖）：replay 确定性——由 d1/d2 三窗逐位零效应（§4.3-C）推断；若 harness 实测存在非确定抖动，容差改为配对差检验并补登记，不静默沿用。

### A10. 市况分桶方案

分桶键 = market_regime 热榜情绪 stage（§1 正交市场门，按帧 join）：强情绪={高潮,发酵}，退潮={退潮,冰点}，过渡={启动}（只报告）。
- 预期：**假设**退潮期池规偏小（诊断表1直接测 T×桶，不预设结论）→ 修正集中退潮期、强情绪期近 no-op；若 T 与桶无关 → 全案趋 no-op、自然终止。
- 验证：全部主读数按桶分层输出；判定线只在全窗判；桶×窗内可比对信号 <2,000 → 只报告并标 insufficient（§4.3-C oos2 22 笔小样本教训：小样本不得单独定案）。

---

## 合同 B：P3 序列时间正规化（L2）

### B1. 考题（一句话，冻结）

跨缺口差分（跨日/同日非相邻）是否系统性污染 velocity/acceleration（velocity>18 帧中 gap 帧富集倍数 ≥1.5 且 CI 下界 >1），且将缺口差分降级为「证据不足、状态沿袭」后三窗 saEx 不低于 no-regression 线、veto/bd 触发率位移不越守卫带？

### B2. 门判据（全部量化）

| 线 | 定义 | 数值 | 理由 |
|---|---|---|---|
| 诊断主判定线（进行为步） | ER = P(gap\|velocity>18)/P(gap) ≥1.5 且按 code 聚块 bootstrap 95% CI 下界 >1.0（重抽样 1 万次，种子冻结于脚本常量） | 见左 | 富集不成立则「18/12 阈值主要选择跨缺口跳变」假设（上轮 2e）证伪，行为步无动机 |
| no-regression 线 | 与 P1 相同：三窗各 ≥0.0994/0.0868/0.0883，均值 ≥0.0935 | 同 P1 | 同 P1 确定性论证 |
| veto 守卫带 | decision 窗 veto 触发率 rel 位移 ∈ [−15%, +20%] | 见左 | 显式防 §4.3-D 变相确认链（其失败签名 veto 0.127→0.023 即 −82%）；下侧收紧、上侧放宽：c1 与 e1a 旁证均表明保护价值真实，丢 veto 是已被证伪的方向 |
| bd 守卫带 | bd 降档率 rel 位移 ∈ [−20%, +20%] | 见左 | 降档腿正价值已确认（c1：−39.4%/−34.4%/−5.8% rel），大幅丢失降档即伤保护支柱 |
| 守卫带越带处理 | 暂停并与诊断步 gap-veto/gap-bd 归因表对账：位移可由归因表定量解释 → 提交用户裁决；不可解释 → 否决 | — | 防静默滑入已证伪形态 |
| 终止条款 | ①诊断 ER 线未达；②G1 即越 no-regression → 全案终止（根因非时间污染）；③G1 过、G2 挂 → 候选=G1 提交，G3 不再试；④帧时间键不可得（依赖①）→ 诊断步 loader 扩展另行登记，本合同挂起；⑤条件步 Track 1 同 P1 | — | 剂量递进逻辑（见 B5） |

### B3. 窗口与数据

同 P1：三窗 saEx 判定线 + 769 帧全窗 + 追加 2026-08 冻结段作过程指标报告窗（理由同 P1：本案直接移动翻转率，须与 0.1376/0.0834 可比对账）。报告项（不设线，样本量预期小）：D→B 跃迁读数变化（§4.1-B 唯一有效跃迁 0.5198）——依赖未决③，见 B9。

### B4. 诊断步产出 schema（可直接落脚本）

数据源：1 次默认配置 replay 导出（序列 + metrics + 末态 + 时间键，若可得）。

```
对级 pairs(股内相邻序列元素):
  code, frame_id_prev, frame_id_cur, trade_date_prev, trade_date_cur,
  slot_prev, slot_cur, frames_apart, cross_day(bool),
  same_day_non_adjacent(bool), pct_prev, pct_cur, delta_pct, abs_delta_pct,
  gap_G1(=cross_day), gap_G2(=cross_day OR same_day_non_adjacent)
帧级 stock_frames:
  code, frame_id, window_label, regime_bucket,
  velocity, acceleration, vel_gt18(bool), vel_lt_minus18(bool),
  gap_origin_G1, gap_origin_G2, temporalGap_count_in_window,
  stage_transition_this_frame(含 D→B 分列), tier, veto, bd, veto_driver(reversal|highrisk)
聚合:
  gap_pair_share_G1/G2 (window×bucket)
  P(gap_G1|vel_gt18), P(gap_G1), ER_G1 + 聚块 bootstrap 95% CI（同法算 G2）
  abs_delta_pct 分布：gap vs non-gap（median/p90/p99）
  vel_gt18 / vel_lt_minus18 帧数及各自 gap 占比（两侧尾都看：B 识别吃正尾，reversal 只吃符号不吃幅度）
  stage 转移事件中 gap 帧占比（→reversal / →ignition / D→B 分列）
  veto(reversal 驱动) 帧中 gap 帧占比；bd 帧中 gap 帧占比（守卫带对账表）
```

### B5. 行为改动步 trial 设计（单变量 ≤3 档）

单变量 = `lifecycleTimeGapStrictness`（枚举，时间证据严度单调递增）：
- **G0 = off**（现状，新代码自证锚复现）；
- **G1 = cross_day**：跨日相邻差分无效；
- **G2 = non_adjacent**：跨日或同日非相邻（frames_apart≥2）差分无效；
- **G3 = non_adjacent_truncate**：G2 + 尾 8 帧窗在缺口处截断重开（hot_streak/best/drawdown 不再吃缺口前旧帧——覆盖「回池后 best 陈旧 → 假 drawdown → 假 reversal」路径）。

**处理语义（各档共用，冻结）**：gap 帧 velocity/acceleration/shock 置 NaN 并打 `temporalGap` 标记（不插值，fail-visible）；raw_stage 在 temporalGap 时 **raw=前帧 raw**（序列首帧 gap → 沿用现行 history_length<2→cooling），normalize 常规运行（输入相同 → 状态自然沿袭）——显式规避已核实入档的「NaN 比较全 False → 静默滑 cooling」路径；cycle_confidence 的 momentum 项按 False 处理（region/persistence/draw 照算）；evidence 序列化 NaN→null+标记，不得以 0 伪装；G1/G2 不动 streak/best/drawdown 的跨缺口累积（那是 G3 的剂量）；signalTier/门控消费面不变、5 词表不动，展示走既有样本质量灰框承载标注。
剂量递进：G3 仅在 G2 通过后触发；G1 挂全案终止。

### B6. 回退与开关

`lifecycleTimeGapStrictness=0` 默认=原行为；回退=开关回 0；config diff 即回退面；候选不自动写回默认（§5）。

### B7. 成本

诊断 1 次 + G0 自证 1 次 + G1/G2 各 1 次 + G3 条件 1 次 + Track 1 条件 1 次。**合计 4–6 次分钟级 replay** + 新写薄诊断脚本 1 个（~150 行）。

### B8. 复用 harness 清单

| harness | 用在哪步 | 缺什么 |
|---|---|---|
| evaluate_lifecycle_gate_form.py | 行为步三窗 saEx + veto/bd 触发率 + 守卫带读数 | 需加 lifecycleTimeGapStrictness plumbing + metrics 的 NaN/标记序列化 |
| diagnose_gate_flip_rate.py | 冻结段翻转率对账（veto 0.1376 / bd 0.0834） | 同 P1：候选 config 复跑支持 |
| optimize_lifecycle_thresholds.py | replay 执行机制复用 | 无 |
| track1_lifecycle_gate_trade.py | 条件终判（出场腿含 D/E 计数退出，saEx 盲区，§3#3/§4.4——P3 改 veto/bd 构成，Track 1 必跑后才可提交落默认） | 无 |
| diagnose_lifecycle_gate_score.py | 不用 | — |
| 新写 diagnose_lifecycle_temporal_gap.py | B4 诊断 | 新写；需时间键（B9 依赖①） |

### B9. 依赖声明

- **依赖未决①（阻断性）**：replay history 帧结构中时间键（trade_date/帧时隙）的可得性——§1.1 摘录仅示 `historical.get("stocks")`；主会话已核实 NaN 语义但未核实此项。落空则诊断步需 loader 扩展，另行登记，不得以帧序猜测跨日边界。
- **依赖未决③（非阻断，观察项）**：D→B 跃迁与 h8/tier 前瞻读数在清单内 harness 的可得性（§7-1 公式未入语料）；不可得则该观察项标 N/A，不影响主线判定。
- 与 P4 a3 replay 无依赖、与 P2 dv 读码结论无依赖；与 P1 正交（尺度轴 vs 时间轴），可独立预登记，各自通过后另批合并验证。

### B10. 市况分桶方案

分桶键与 P1 相同（market_regime：强情绪={高潮,发酵}，退潮={退潮,冰点}，过渡={启动}）。
- 预期：**假设**退潮期出入池频繁 → gap 对集中退潮期、修正集中退潮期；强情绪期连续在池 → gap 稀少 → 近 no-op。诊断表 gap_pair_share×bucket 直接检验，不预设结论。
- 验证：全部主读数按桶分层；判定线只在全窗判；桶×窗可比对信号 <2,000 只报告标 insufficient（同 §4.3-C 教训）；先例压低预期——P_repool 专项 gap 相关扫描方向性 insufficient（14.2%→8.3%，§1.1），本案正读数上限预期为「证据纯度提升 + 无价值损失」，不是 saEx 改善。

---

## 尾注：假设声明

- 两案的全部判定线、预期方向（退潮期集中、强情绪期近 no-op、ER 富集、T×桶关系）均为**跑前冻结的待验证假设**；B4/A4 的产出本身可能否定考题（两案的第一终止条款都是「假设不成立即弃」）。
- 「通过」的语义仅为「提交用户裁决是否落默认」，不构成任何改动授权；Track 1 条件步未跑前不得提交。
- 本轮未引用任何未核实数字；a3 粗估（~10% 量级）仅作参照且两案均不消费它。
