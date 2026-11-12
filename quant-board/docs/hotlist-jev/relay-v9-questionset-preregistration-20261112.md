# relay 题集 v9 优化预登记（提案，2026-11-12）

> 关联：`market-cycle-p3-narrative-preregistration-20261112.md`（v8 市场周期融合）。
> **批准判据表 ≠ 批准动代码；实施另行立项审批**。**红线 §1.2#7：批准额度 ≠ 批准开火**。
> 状态：用户已裁决方向（见 §二）；**相位量化阈值（§四）为提案，须逐项批准后实施**。

## 一、定位

v8 融合后周期判定已由「market_cycle 状态机 + 3 新题」承担。v9 目标：**去重 + 聚焦接力独有微观 + 相位状态机化**。
- 删与题材龙头/周期锚重复的题；relay_index 降观察（不碰判据）；relay_phase 重定义为「jev 判读 + 状态机骨架」。
- **状态机（market_cycle）仍是周期唯一权威**；relay_phase 是接力生态当日读数，与周期态**互补可背离**，不改判 state。

## 二、裁决记录（2026-11-12）

| # | 裁决 |
|---|---|
| 删题 | 删 `theme_pulse`、`leader_strength`（与题材龙头/周期锚重复无增益）；**保留 ladder_health** |
| relay_index | **甲**：仍算仍落库，仅定位降观察；大盘 wzs/分带照旧用 relayIndex，**不碰判据** |
| 叙事 | **删题不删叙事**：theme_evolution_line / leader_profile_lines 保留（板块龙头页 + 其余题结构参照） |
| 相位 | **方案 D**：jev 判读 + 状态机骨架（量化判据 + 连续性 + 消歧序） |
| 昨日相位 | **软参照**：jev 可背离，非硬约束 |
| days-in-phase | **落库 + 进语料判据**；**不上前端** |

## 三、题集变更（10 → 8）

- **删**：`theme_pulse`、`leader_strength`（均无判据依赖，只供前端展示）。
- **降观察**：`relay_index`（仍在题集、仍落库 relayIndex；前端标「观察」，不当头条）。
- **保留**：`relay_phase`(重定义)、`relay_momentum`、`ladder_health`、`money_effect` + `turn_quality`/`cycle_intensity`/`risk_ahead`。
- 版本 `QUESTION_SET_VERSION_RELAY` v8→**v9**；跨代不可比，历史 v8 档不回填（先观察）。
- 前端移除「题材脉络/龙头强度」KPI 卡 + 监控表列；relayIndex 标观察位。

## 四、relay_phase 重定义（方案 D 核心；量化阈值为提案，待逐项批准）

> 主锚不变：【三日晋级链】【近10日连板轨迹】【今日炸板面】【高位股多日轨迹】；【板块接力链】【龙头结构】结构参照。
> 判据全部锚定叙事已有的**近20日分位刻度**（晋级率/炸板家数/断板中位/隔日溢价 P20/P50/P80），去模糊词。
> **消歧优先序（保守优先，同 ladder_health 哲学）：collapse > divergence > relay_heat**；launch/bottoming 独立判。

| 相位 | 量化判据（提案） |
|---|---|
| **collapse 退潮崩塌** | 龙头断板/大面 + 高位批量断板（轨迹断板≥2只）+ 亏钱主导（断板中位≤P20 或 大面占断板≥30%）；或炸板极端（炸板家数≥P80 且 反复开板占比≥50% 且 高位分歧炸为主）；涨停家数与高度同步回落 |
| **divergence 高位分歧** | 最高梯队仍在（最高板≥参照中位）但晋级率回落（<P50 或 较昨日 −5pct）；断板亏钱扩散（断板中位转负 或 大面增多）或 中位断层（二板/三板+比率<0.5）；或炸板恶化（反复开板≥P80 或 昨日池批量今炸 或 高位分歧炸占比升高） |
| **relay_heat 接力顺畅** | 晋级率≥P50；梯队不断层（二板/三板+比率≥0.5）；断板可控（断板中位≥P50 或 隔日溢价≥P50）且大面<10%；炸板健康（炸板家数≤P50 且 反复开板≤P50 且 无高位批量炸）；龙头封板稳固 |
| **launch 启动/首板堆积** | 首板占比≥75%（或较昨日 +10pct）；新题材批量（top3 重合≤1 且 新鲜度高）；晋级率尚低（≤P50）但断板可控（断板中位≥P20）+ 炸板可控（≤P50）；高度低位（最高板≤参照中位） |
| **bottoming 冰点出清** | 高度压平（最高板≤P20）；首板为主（首板占比≥80%）；接力近停滞（晋级率≤P20）；但亏钱收敛（断板中位较昨日回升 或 大面较昨日减少） |
| **insufficient_evidence** | 晋级率/断板/炸板面/梯队证据缺失 |

## 五、状态连续性（软参照 + days-in-phase）

- **叙事新增行**：`昨日相位：{relayPhase} · 已持续 {daysInPhase} 日`（读前一日 RELAY 档；缺→整行缺席 fail-visible）。
- **instructions 增**：「相位有惯性，昨日相位作软参照——无明确反转证据倾向延续，证据明确反转可背离；周期态（【市场情绪周期】段）是背景，相位是接力生态当日读数，允许背离」。
- **daysInPhase 落库**：jev 判出当日 relayPhase 后**后验确定性计算**：
  `daysInPhase = 1 if 今日相位 != 昨日相位 else 昨日daysInPhase + 1`（纯函数，零 token）。
- **进语料判据**：daysInPhase 通过「昨日相位·已持续N日」行供 jev 判读；**不上前端**。
- 无循环依赖：D 日叙事读 D-1 已落库档；D 日 daysInPhase 在判后计算。

## 六、relay_index 观察项（甲）落法

- 题集保留 relay_index、落库保留 relayIndex；**大盘 wzs（weak_to_strong）/分带（relay_band）/market_cycle reference 判据与坐标系零改动**。
- 前端 relayIndex 标「观察」位（不再当头条）；KPI 头条让位相位/周期。
- 不新增判据、不废弃 relayIndex。

## 七、叙事变更汇总

- **增**：昨日相位·已持续N日 行（§五）。
- **保留**：theme_evolution_line / leader_profile_lines / ladder_structure_line（删题不删叙事）。
- **删**：无（不删叙事行）。
- 新叙事行过 `test_narrative_hygiene.py` 黑名单。

## 八、验收门（v9）

1. 题集 8 题；删 theme_pulse/leader_strength；relay_index 仍在（观察）。
2. relay_phase 量化判据 + 消歧序 + 软参照连续性；daysInPhase 落库 + 进语料（不上前端）。
3. 大盘 wzs/分带/market_cycle reference 判据零改动（relayIndex 坐标系不变）。
4. 既有 relay_momentum/ladder_health/money_effect + 3 新题 criteria 零改动。
5. 叙事卫生黑名单；测试零真 jev（全 mock）。
6. pilot 观察（先不回填）：相位判定贴合盘感 + 连续性合理 + relayIndex 无异常漂移。

## 九、实施计划（批准后另行立项）

1. `jev_relay_ammo.py`：删 2 题、relay_phase 重定义（量化 criteria + 消歧 + 软参照 instructions）、版本 v9。
2. `jev_relay_index.py`：昨日相位行 + daysInPhase 后验计算落库；删 themePulse/leaderStrength 字段。
3. 前端：删题材脉络/龙头强度 KPI + 监控表列；relayIndex 标观察。
4. 测试：题集结构/相位量化/连续性/daysInPhase/链序；零真 jev。
5. 挂链 pilot 观察。

## 十、待裁决项（量化阈值）

- §四 5 相位量化阈值（P20/P50/P80 分位选择、首板占比 75%/80%、大面 30%/10%、晋级率 −5pct 等）逐项批准或调整。
- 消歧序 collapse > divergence > relay_heat 认可？
- daysInPhase 首日/缺昨日档 → 1（fail-visible）认可？

## 十一、风险与教训对照

- **判据漂移**（措辞漂移教训）→ 量化分位锚定，去模糊词。
- **双权威**（§1.2#1）→ 周期态唯一权威，相位互补可背离不改判。
- **relayIndex 误废**→ 甲方案保留计算与判据，仅降观察位。
- **误烧 token**（§1.2#7）→ pilot 逐次开火确认，测试全 mock，不回填。