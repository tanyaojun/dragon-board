# jev 方向独立裁决线（v3-gate）预登记与基线报告

> 冻结日期：2026-10-13 · 状态：判据冻结（buy 专项开放）· 实验台账：~300 例 / 1100+ 次真实调用
> 定位文件：本文件为 jev 方向线（区别于规则线）的判据单一事实源；改动判据/门/计分任何一项都须用户点头（改门）。

## 一、定位与三原则

规则打分（RankTrend 五维引擎）与 jev 判定是两条不重复的线，**原料一样**，实盘对比收益定优劣。jev 线三原则：

1. **原料单一化**：dragon-board 只做刻度转换+基准对齐+描述统计；档位/score/方向标签/阶段标签等引擎判断产物一个不给；
2. **算法精简化**：判据=原料证据的语义读法锚（教学「怎么读」），不教合并公式、不喂计算结果；
3. **结果具象化**：buy / sell / hold / insufficient + 置信 0-1，与规则线在「方向」这个共同语义上对比。

**历史教训（本文件吸收）**：v1 复核题集=规则结论文字化（循环论证，83% 一致率是假验证）；v2 纯原料无读法=瞎猜；五维信号结构性过拟合（同一热度分位序列被四维重复投票）。本版判读时点=盘中 11:00 帧（帧落盘即判读），验证=隔日涨幅——不用盘后 daily 帧反推。

## 二、原料合同（全部描述统计，零引擎判断产物）

| 块 | 字段 | 说明 |
| --- | --- | --- |
| A 跨日出现序列 | 该股最近 ~30 次在榜出现（日期+槽、名次、分位、涨幅），时间升序；末行=判读时点 | 与引擎 `_build_code_attention_series` 同源口径（half_hour 帧流）；分位=(池-名次+1)/池×100 |
| B Position Stats | 当前分位、3 交易日净变（今日点 vs D-3 日终分位）、10 日峰回撤（max−current）、热区停留（连续日终分位≥80 天数）、连续在榜天数 | 全部从序列现算，**不透传引擎 cycle.metrics/crossSection（帧窗语义陷阱，见审计 A-1）** |
| C 量价行 | 涨幅、量比（vs 5 日同时段）、主力净额（亿）、净占比（%）、换手、涨停/跌停旗标（板块口径与引擎 `_daily_limit_pct` 一致） | 判读帧原始行 |
| D Market Gate | 热榜情绪相位带（`hotlist_sentiment` as-of 判读时点最新槽：score+band+stage）+ 全池 median 3 日分位净变 + 全池上涨占比 | 相位带=固定分线查表（见 §四），非引擎判断 |
| E Market Context | 池规模、池 median 3 日分位净变 | 相对强弱基准 |

fail-visible：缺值一律 `missing`，不伪造 0；个股缺行跳过披露；判读序列 <10 点跳过。

## 三、环境门（buy 前提，两道）

### 门 1 生命周期分层（个股层，jev 自判）

- 通过：ignition/expansion 位置（连续在榜、分位从低位/中部上行、回撤浅）；
- 失败：crowded（热区长留+动能衰减）或 reversal/retreat（3 日净变明显为负+回撤≥15 分位，或连续 5+ 分位下跌日）→ 禁 buy，最多 hold，有崩塌证据可 sell。

### 门 2 热榜情绪相位带（市场层，固定分线查表）

相位轴主定义=热榜情绪分（emotionScore），**40/60/75 三条分线切四带**（出处：`emotion_score.py map_stage` + W4 复核裁决「40-60 实质退潮」+ C9/C10 深谷/高峰线）：

| 带 | 分线 | buy 门 |
| --- | --- | --- |
| 冷带 | <40 | **禁** |
| 弱带 | 40–60 | **禁**（W4 裁决：实质退潮，弱势带逐月皆亏）|
| 强带 | 60–75 | **放行** |
| 高峰 | ≥75 | **禁**（拥挤 blow-off top）|

as-of 语义：判读时点取当日 ≤11:00 最新情绪槽文档，无未来函数。`riskLevel` 全样本无区分度未用；`stage`（五档状态）仅披露不作门（score+固定分线更干净）。

### 门的实测行为（四情绪日 100 例）

| 判读日 | as-of 分 | 带 | B3 buy | 隔日池均值 |
| --- | --- | --- | --- | --- |
| 09-10 | 29.6 | 冷 | 0 | -2.38%（拦对）|
| 09-16 | 76.5 | 高峰 | 0 | +0.16%（拦对）|
| 09-17 | 50.7 | 弱 | 0 | +1.28%（拦对）|
| 09-18 | 64.4 | 强 | 6 | +2.38%（放行 ✓）|

## 四、计分口径（冻结）

- 判读时点：盘中 11:00 槽帧落盘即判读；
- 验证：**隔日涨幅**（T+1 最后一槽 change；掉榜股不计分）；
- buy 对=隔日涨 / sell 对=隔日跌 / **hold 遇 |隔日|≥5% 算错**（用户裁决：判读要给方向）；
- 置信校准：高置信组正确率应显著高于低置信组，否则置信视为无效。

## 五、判据冻结件（EN 主版 VERBATIM；改动=改门须用户点头）

#### 题 A · 综合方向（生产主判读，单题集）（key=`direction`，type=choice）

AMMO_VERSION=2026-10-13b（variant 收敛：吸收 B3 合成语义「量价无方向不否决轨迹方向，只降置信」）。

**instructions（VERBATIM）**：

```
You are given descriptive raw data for one stock from a hot-list attention ranking system — NO pre-computed tiers, signals, or conclusions. Data: [Attention Series] the stock's last appearances across days and intraday slots (percentile 0-100, higher = hotter; last line = current intraday reading); [Position Stats] day-level anchors; [Volume-Price] today's intraday price-volume-capital row; [Market Gate] the market environment for buy decisions (hot-list sentiment score, market stage, pool breadth); [Market Context] pool median 3-trading-day percentile change (the stock only counts as strong if it OUTPACES this baseline). Task: judge the stock's short-term directional state AS OF THIS INTRADAY MOMENT: buy / sell / hold / insufficient, with a confidence between 0 and 1. Reading guide: (1) A trend requires a multi-day same-direction movement across the series — a single-bar spike is not a trend; judge the swing across days, not the noise between consecutive appearances; a jump AGAINST the prevailing multi-day direction vetoes that direction; a choppy back-and-forth path reduces confidence. (2) Volume-price confirmation: price up on expanding volume (ratio above 1 but not above 2.5) confirms; volume ratio above 2.5 on an up day is distribution suspicion; an abnormally HIGH net ratio (above +20%) is blow-off/wash-trading suspicion, NOT bullish; a strongly negative net ratio (about -10% or worse) suggests distribution; price down on expanding volume is the strongest sell evidence; a limit-up flag is a real but untradeable signal (never buy evidence); a limit-down flag means panic selling; price-volume evidence showing no clear direction does NOT block a trajectory-based direction — it only lowers the confidence. (3) insufficient is ONLY for unavailable data (a too-short series or missing market context); conflicting evidence means hold. Lower confidence when evidence conflicts or fields are missing. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — lifecycle position: the stock must sit in an ignition/expansion position (appearing consistently, percentile rising from a low or mid base, shallow drawdown); a crowded position (long hot-zone stay with decaying velocity) or a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days) FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — market sentiment PHASE BAND, by the fixed phase lines given in [Market Gate] (cold <40 / weak 40-60 / strong 60-75 / peak >=75): buy is allowed ONLY in the strong band; in the peak band (>=75, crowded blow-off top), the cold band (<40) and the weak band (40-60, materially a retreat phase) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence.
```

**criteria（VERBATIM）**：

- `buy`：Multi-day percentile rise outpacing the market baseline; volume-price confirming; BOTH environment gates pass (ignition/expansion lifecycle position AND sentiment phase band = strong).
- `sell`：Multi-day percentile fall/collapse with market-relative weakness; and/or price down on expanding volume; and/or net outflow or abnormally negative net ratio; and/or reversal/retreat phase with collapse evidence.
- `hold`：Evidence mixed or conflicting, magnitudes too weak, OR a failed buy gate without sell evidence.
- `insufficient`：ONLY data unavailability. Never for conflicting evidence.

#### 【退役 2026-10-13】题 B1 · 轨迹方向（variant B 拆分层）（key=`trend_direction`，type=choice）

**instructions（VERBATIM）**：

```
You are given a stock's cross-day attention rank percentile series (last appearances across days and slots, time-ascending; the LAST line is the current intraday reading) plus day-level position stats and the market baseline. All changes are in percentile points, positive = attention rising; drawdown is the distance below the peak. Judge ONLY the attention-momentum direction of the STOCK ITSELF: buy / sell / hold, confidence between 0 and 1. buy requires ALL of: a multi-day same-direction rise across the series, outpacing the market median 3-trading-day change (compare directly), and NOT a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days — NEVER buy). sell: sustained multi-day fall or collapse, or clear market-relative weakness. hold: mixed, weak, or conflicting evidence. Lower your confidence when evidence conflicts or key fields are missing.
```

**criteria（VERBATIM）**：

- `buy`：Multi-day percentile rise outpacing the baseline, no reversal/retreat phase.
- `sell`：Sustained multi-day fall/collapse or market-relative weakness.
- `hold`：Mixed, weak, or conflicting evidence.

#### 【退役 2026-10-13】题 B2 · 量价方向（variant B 拆分层）（key=`vp_direction`，type=choice）

**instructions（VERBATIM）**：

```
You are given ONLY price-volume-capital data for one stock at this intraday moment: change%, volume ratio (vs 5-day same-time-of-day average), main-force net flow (100M CNY; positive = inflow), main-force net ratio (%), turnover%, limit-up/down flags. Judge ONLY the price-volume direction: buy / sell / hold, confidence between 0 and 1. buy: price up on expanding volume (ratio above 1 but not above 2.5 — above 2.5 on an up day is distribution suspicion) with positive net flow and net ratio NOT above +20% (above +20% is blow-off/wash-trading suspicion, NOT bullish); a limit-up flag alone is a real but untradeable signal — do NOT count it as buy. sell: price down on expanding volume, or net ratio about -10% or worse, or the limit-down flag. hold: mild moves, shrinking volume without limit-up, or contradictory signals.
```

**criteria（VERBATIM）**：

- `buy`：Up on healthy expanding volume with positive, sane net ratio.
- `sell`：Down on expanding volume, strong outflow, or limit-down.
- `hold`：Mild or contradictory price-volume signals.

#### 【退役 2026-10-13】题 B3 · 合成裁决（synthesis rules 语义已吸收进题 A）（key=`final_direction`，type=choice）

**instructions（VERBATIM）**：

```
Two independent judgments were made on the same stock at this intraday moment: JUDGMENT 1 read the cross-day attention trajectory; JUDGMENT 2 read the price-volume data. Their choices and confidences are below, with the position stats, market gate and market context. Output the FINAL call: buy / sell / hold / insufficient, confidence between 0 and 1. Apply the synthesis rules IN ORDER: (1) a judgment of hold means that layer found NO direction — it is NOT a vote against the other layer's direction. (2) If one layer gives a direction and the other holds, FOLLOW the directional layer (the holding layer neither confirms nor opposes), with confidence equal to the directional layer's confidence reduced somewhat (unconfirmed). (3) If both give the SAME direction, follow it with confidence equal to the higher of the two, raised if both are high. (4) If they give OPPOSITE directions, this is a true conflict: hold, UNLESS one side's confidence clearly dominates (difference of 0.4 or more), in which case follow the dominant side with reduced confidence. (5) a limit-up flag means a real but untradeable signal — never the final buy. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — lifecycle position: the stock must sit in an ignition/expansion position (appearing consistently, percentile rising from a low or mid base, shallow drawdown); a crowded position (long hot-zone stay with decaying velocity) or a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days) FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — market sentiment PHASE BAND, by the fixed phase lines given in [Market Gate] (cold <40 / weak 40-60 / strong 60-75 / peak >=75): buy is allowed ONLY in the strong band; in the peak band (>=75, crowded blow-off top), the cold band (<40) and the weak band (40-60, materially a retreat phase) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence. (6) insufficient ONLY for unavailable data. Never hold merely because the two layers differ in strength.
```

**criteria（VERBATIM）**：

- `buy`：Directional layer says buy and the other holds or agrees, or the buy side clearly dominates a conflict — AND both environment gates pass (ignition/expansion position AND sentiment phase band = strong).
- `sell`：Directional layer says sell and the other holds or agrees, or the sell side clearly dominates a conflict — veto phase with collapse evidence also sells.
- `hold`：True opposite-direction conflict without a dominant side, both layers hold, a failed buy gate without sell evidence, or a veto blocking buy.
- `insufficient`：Data unavailable only.

## 六、基线成绩单（三批 ~300 例，2026-10-13）

### 批 1 退潮日 10-09（弱带 as-of 55.7/退潮 stage，n=98 计分）

- A 总正确 59%，方向判断 59 例（buy 6 对 33%、sell 53 对 81% 中位 +4.90%）；
- B3 v1（旧合成）总 64%；**B3 v2 新合成（hold≠反对票）把 buy 覆盖从 3 放开到 11、正确率 33%→55%**；
- 结论：合成规则修正成立（10 例重叠子集 4 例 hold 拉回改给方向）。

### 批 2 四情绪日（09-10/16/17/18，n=99 计分）

- A 77% / B3 72%；门行为四带全验证（§三表）；
- sell 本批 60%（无单边退潮，sell 样本少）；hold 错例集中在弱/冷带的 |≥5%| 行情。

### 批 3 强带扩样本（09-14/18/21/22，n=98 计分）

- **A buy：12 例对 67%，中位 +1.44%，累计 +6.9pct，四日稳定**——当前体系最好的 buy 形态；
- B3 buy v2 迭代判据（floor≥90+surge pacing）**证伪**：09-18 拟合日 100% → 扩日 37%、累计 -13pct，过拟合；已回滚（§五为回滚后冻结版）；
- sell/hold 跨日稳定。

### 跨批结论（冻结基线）

| 信号 | 稳定性 | 基线水平 |
| --- | --- | --- |
| sell | **稳定**（退潮日 80-84%，全场景可做）| 主力信号 |
| hold | 口径已定，行为符合设计 | 震荡市主形态 |
| buy | **开放专项**（见 §七）| 强带日 A 口径 67%（+6.9pct/12 例）为当前最好 |

## 七、开放专项登记（buy）

- 现状：判据层暂无跨日稳定的 buy 增量；floor/surge 闸门在 09-18 拟合日有效、扩日证伪（过拟合教训：小样本调参禁入判据）；
- 待解：强带日 buy 错例的跨日共性（当前样本 19 buy 不够）；需跨月累积强带判读样本（每日 11:00 帧判读可挂自动链后自然积累）；
- 重启条件：强带 buy 样本 ≥50 例后再做判据迭代；迭代仍须「拟合日之外验日」协议。

## 八、variant 取舍与执行架构

- **variant A（综合题）与 B（拆分+合成）并列保留**：A 在无单边退潮市况更稳（批 2 77%），B 在退潮日更稳（批 1 64% vs 59%）且分层置信可审计；两者方向一致率 70-82%；
- 实验脚本（判据冻结件载体）：`quant-board/.tmp_pilot_gate.py`（原料组装 build_state + QUESTIONS_A/B1/B2/B3）；执行入口 `python .tmp_pilot_gate.py [--day=YYYY-MM-DD] [--dry]`；逐例落盘 `.tmp/pilot_gate_v2/`；
- 生产化（正式 runner/题集入库/盘后链挂载/前端读口）为下一代码批次，另行提交；本预登记冻结的是判据文本与实验合同。

### variant 收敛裁决（2026-10-13，用户「执行」）

**单题集 = A 主判读，B 拆分层退役留档**。理由：三批实验 A/B 方向一致率 70-82% 高度重叠；B 成本 4×；B 增量仅退潮日 sell 覆盖更广（84% vs 80%，正确率相近非更准）。A 的 instructions 已吸收 B3 合成实验的唯一增量语义——「量价无方向不否决轨迹方向，只降置信」。B1/B2/B3 判据全文留档于本文件 §五（退役标注）与 git 734492a6。落库收敛为单文档 `_id={date}:11:00:{code}:DIR`，成本 1 调用/股。

## 九、验证与红线

- 判据 VERBATIM 锁定：生产化时题目文本以本文件 §五逐字比对（同 v1 时代 TEST 判据锁定法）；
- 自动化测试零真实 jev 调用零网络；真实调用只走预登记+用户开火（本预登记的实验已按此执行：370+400+50+300 次，全部用户逐批开火）；
- 台账：`.tmp/pilot_ab10.json`、`.tmp/pilot_ab100_merged.json`、`.tmp/pilot_gate/`、`.tmp/pilot_gate_v2/`、`.tmp/pilot_buyiter/`（gitignore 内，判读全文+state+验证列）。
