# 第4课市场周期 P3：relay 题集融合 7→10（v8）预登记（提案，2026-11-12）

> 关联：`market-cycle-preregistration-20261112.md` §八 P3。
> **批准判据表 ≠ 批准动代码；实施另行立项审批**。**红线 §1.2#7：批准额度 ≠ 批准开火**。
> 状态：用户已裁决 Q-A/Q-B/Q-C（见 §二）；实施计划与 pilot 开火仍须逐次确认。

## 一、定位（用户裁决：融合，非观察层）

- **落点 = relay 题集 7→10**（`QUESTIONS_RELAY` v7.1→v8），不是独立 P3 叙事集合。
- **融合 = 补维度，等同于加语料**：把 market_cycle 状态机输出（态/事件/锚/天花板）作为**新语料段**喂进 relay 叙事，新增 3 题消费它。
- **状态机仍是离散态+事件唯一权威**（红线 §1.2#1）；jev 只补状态机不产的维度，**不改判 state/事件、不改既有 7 题 criteria**。
- **不全量回填**：先观察几天（pilot），可能再修改完善；历史档保持 v7.1。

## 二、裁决记录（2026-11-12）

| # | 裁决 |
|---|---|
| Q-A | 加进 relay 题集 7→10；**不全量回填，先观察几天**，可能还需修改完善 |
| Q-B | 补维度，等同于加语料（jev 不改判 state） |
| Q-C | 认可 3 题：`turn_quality` / `cycle_intensity` / `risk_ahead` |

## 三、新增 3 题（choice，criteria 逐选项判据，对标 relay v7.1 形态）

> 主锚=新语料段【市场情绪周期】（态/事件/锚/天花板）；缺原料→`insufficient_evidence`。答案带 confidence/probabilities（沿 relay 既有形状）。

| qid | 互补维度 | choice 选项 | 第4课判据 |
|---|---|---|---|
| `turn_quality` | 转折质量（状态机测到 wzs/突破，测不到质量） | confirmed / pending / false / not_in_window / insufficient_evidence | 高位缓和看2天（断板震荡2天/反包）；一字突破更易成功 |
| `cycle_intensity` | 周期强度（状态机给离散态，jev 给程度） | strong / moderate / weak / insufficient_evidence | 赚钱效应勇猛精进 vs 亏钱效应蛰伏；恐慌缓和细微程度 |
| `risk_ahead` | 前瞻风险（状态机判当下，jev 看未来1–2日） | high_collapse / space_compress / none / insufficient_evidence | 崩塌看1天（连板后直接跌停）或2天（无跌停连续崩塌无承接）；压缩与崩塌相伴 |

- 既有 7 题（relay_index/relay_phase/relay_momentum/ladder_health/leader_strength/money_effect/theme_pulse）**criteria 不动**。
- `QUESTION_SET_VERSION_RELAY` v7.1→**v8**；跨代不可比（历史 v7.1 档不回填）。

## 四、新语料段（market_cycle 单源，叙事卫生 §1.2#8）

- 来源单源 `hotlist_jev_market_cycle {date}:MARKET_CYCLE`：`state`/`events[]`/`anchor`(两轨龙一+命运)/`ceiling`(maxBoard/≥3板家数)。
- 新叙事段【市场情绪周期】只放数据事实：当前态 + daysInState + 当日事件标记 + 两轨龙一命运 + 天花板高度。
- **缺数据整行不投喂**：market_cycle 档缺失→该段缺席 + 结构化 `cycleCorpusMissing` 落库，3 题落 `insufficient_evidence`（fail-visible，不伪判）。
- 新叙事行过 `tests/hotlist/test_narrative_hygiene.py` 黑名单；禁开发注释/口径注进叙事。

## 五、关键依赖解环（实施前必须裁决的技术点）

**成环**：现盘后链 `market_cycle` 硬约束在 `relay_index` **之后**（reference 需当日 relay 档，`schedule.py:1050`）；而 relay v8 要读当日 market_cycle 语料 → 循环依赖。

**解环提案（Option A，拆分+重排）**：
- market_cycle **确定性部分**（anchor/ceiling/events/state，纯函数、零 token、不依赖 relay）**移到 relay_index 之前**；reference 暂缺（fail-visible）。
- relay_index 读 market_cycle 确定性档作语料。
- relay_index 之后**补刷 market_cycle reference**（单日轻量 `$set reference`，或复用 `replay_state` 单日）。
- 链序变为：`theme_cycle → market_cycle(确定性) → relay_index(v8) → market_cycle.reference 补刷 → relay_band`。

**否决项**：relay 读 D-1 market_cycle（陈旧，当日态错位）；relay 内联重算 market_cycle（违反单源、重复计算）。

## 六、版本兼容与 relayIndex 稳定性风险

- 新语料段进入 relay 叙事后，**既有 7 题读的是整段叙事**，relay_index/relay_phase 等可能被新语料**轻微扰动**（即便 criteria 不动）。
- 缓解：新语料段**独立成段、明确标注仅供新增 3 题**；pilot 观察既有 7 题（尤其 relayIndex）是否漂移，漂移显著则回退或隔离语料。
- 历史 v7.1 档不回填；前端判定明细按 `questionSetVersion` 区分代际（v8 才有 3 新题）。

## 七、pilot 方案（先观察几天，不全量回填）

- 实施挂链后，**新交易日**自然用 v8（10 题）；观察 **3–5 个交易日**。
- 每日 tokens：现 relay ~8.2k input + 新语料段/3 题 ≈ **+1–2k → ~9–10k/日**；3–5 日 ≈ **3–5 万 tokens**（开火前逐次确认，§1.2#7）。
- 观察点：①3 新题判定是否贴合盘感；②既有 relayIndex/relay_phase 是否漂移；③语料卫生/缺料 fail-visible。
- pilot 不达预期→修改完善（改 criteria/语料=再换代 v8.x）或回退 v7.1；**不急于全量回填**。

## 八、验收门（P3 / relay v8）

1. choice 题模式：jev 永不生成措辞（沿 relay 既有 score/choice，无自由文本）。
2. 新语料段过 `test_narrative_hygiene.py` 黑名单；缺料整行不投喂 + 结构化字段。
3. 既有 7 题 criteria 零改动；状态机 state/事件不被 jev 改判。
4. 解环后链序正确（market_cycle 确定性在 relay 前，reference 补刷在后）。
5. 测试零真 jev 调用（全 monkeypatch/fixture）。
6. pilot 3–5 日用户盘感裁决通过 → 才考虑后续（是否回填另行裁决）。

## 九、实施计划（批准后另行立项，此处仅登记）

1. market_cycle 拆分确定性/reference + 链序重排（§五 Option A）。
2. relay 叙事加【市场情绪周期】语料段（单源 + 卫生）。
3. `QUESTIONS_RELAY` +3 题、版本 v8、解析/落库 3 新答案字段。
4. 前端判定明细/tooltip 适配 v8（3 新题）+ 代际区分。
5. 测试（零真 jev）+ 叙事卫生。
6. 挂链 pilot，观察 3–5 日。

## 十、风险与教训对照

- **措辞漂移**（2026-10-03）→ choice/score，无自由措辞。
- **双权威**（§1.2#1）→ 状态机唯一权威，jev 补维度不改判。
- **relayIndex 漂移**→ 新语料独立成段 + pilot 观察既有 7 题。
- **误烧 token**（2026-10-03）→ pilot 逐次开火确认，测试全 mock，不全量回填。
- **循环依赖**→ §五 解环提案，实施前裁决。
