# 行情列表五维信号 jev 复核双题集 正式预登记（2026-10-12 用户五裁决后落方案）

> 性质：**新题集双立**（非改门）。状态：判据文本已按 2026-10-12 五裁决修订，**待用户逐字确认后冻结**；
> 冻结以开火时 `_questions_hash` 为准（开火后只能文档向代码回写，反向改代码=作废 pilot）。
> 本文件同时是 jev 叙事平台正式立项后第一个按新定位立项的批次（见 §〇）。
> 历史依据链：cycle v5 收官（b83e4c79 + 1da62694，pilot A 三门全过）→ 用户裁决项目定位升级 →
> 用户 2026-10-12 指令「行情列表五维信号采用 jev 叙事模型」→ 本预登记。

---

## §〇 正式立项章

- **立项裁决（2026-10-11，用户）**：jev 从「热榜行情情绪面板局部展示研究结论」正式升格为
  **jev 叙事平台**，覆盖 10-01「主线放弃、保留打辅助」旧定位。本批为按新定位立项的第一个批次。
- **调用纪律四段范式**（用户原话正面确认）：预算报备 → 基于假设前提试跑 → 获得正向结论 →
  才批量覆盖。落地形态=预登记冻结（判据全文+预算双口径）→ 用户点头开火 → pilot 判定
  （机器侧门+用户人工盘感终验）→ 落生产。逐项点头，不可批量，不可跳步。
- **本批边界**：只做 pilot（落临时试点集合+对照台账）。生产化接线（接行情列表展示层）另行预登记。
  jev 与规则投票引擎=并列观察者：引擎不是 golden，jev 判读不回写引擎、不进候选池、不进交易路径。
  不碰 `analysis/ranktrend/**`（结构重设计 W0/W1 是另一条线）；不碰并行会话未提交文件
  （relay_page/index.html、api/hotlist_jev_routes.py、snapshot_collector/providers.py、slots.py
  及 relay/slots 测试与文档）。测试零真实 jev 调用零网络。

## §一 用户五裁决回执（2026-10-12）与本文件落法

| # | 裁决 | 落法 |
| --- | --- | --- |
| 1 | insufficient 逃生口改用风险度 risk_flag 代替 | 两题集 choice 删 insufficient，回到三态/五态纯净判层；**riskFlag 为 runner 侧结构化字段**（数据完备度预检，见 §二·四/§三·四）：数据性不足不进人口不调用（防模型瞎猜，比逃生口更强——逃生口是事后标注，预检是不进人口）；判读性含糊由 probabilities 平铺+confidence 低值如实表达（cycle v5 09-30 实证 jev 诚实平铺 0.33/0.32/0.23 不硬编）。台账按 riskFlag 分层披露 |
| 2 | 对照锚定义认可 | A：jev choice ↔ synergy 档位映射方向（S/A/B→buy、C→hold、D/E→sell）；B：jev choice ↔ 规则 stage 直接比对。机械可算出 agree/diverge 台账 |
| 3 | 槽位口径 half_hour 15:00 认可；daily 15:30 帧字段缺失用 half_hour 15:00 帧补齐 | pilot 主口径=half_hour 15:00 单帧（原料实测饱满）；**EOD 补齐读法**落为弹药层纯函数（daily 15:30 帧为基准、行情字段从同日 half_hour 15:00 补齐、补齐来源注记），供后续 EOD 视角使用。理由与边界见 §四（引擎档位不可跨帧拼接；存量 daily 帧写库修复涉 snapshot 链，不在本批） |
| 4 | 抽样上限与 150k 熔断认可 | 见 §六 |
| 5 | jev 返回全保留（此前只留 score/choice 丢置信度） | 落库合同见 §八：answers 原样包（type/choice/confidence/probabilities 全保留）+ confidence 升顶层可索引 + responseRaw ok/degraded 一律存完整 envelope（修 cycle pilot「ok 时 responseRaw=None」口子）。`jev_client.py` 是 N15 保留件零改动（parse 本就 answers 原样返回），全保留落在 runner 落库层 |

## §二 题集 A：vote_confirm（方向投票 jev 二次确认）

### §二·一 对象与人口

- 对象：行情列表单股 @ **half_hour 15:00**（当日收盘槽）。
- 人口：synergy 档 ∈ {S, A, B, D}（有方向票者）。E（环境门否决）不进 A（归 B 语境）；C（无明确方向）不进。

### §二·二 叙事原料清单（全部可数，缺口 fail-visible 注记）

源：`snapshot_analysis`（逐股五维载荷，与规则链/情绪链同源 join）+ `snapshot_stock_rows`。

1. 头行：日期/槽位/代码/名称；
2. 四维读数块：
   - 共振：signalTier/direction/score/tierReasons/status（status=insufficient 如实标注）；
   - 趋势：signalTier/direction/score/signedScore/tierReasons + 技术面 MACD·MA 金叉死叉事件；
   - 热度：signalTier/percentile/percentileDelta（档位自带符号 A/B 正 C/D 负）；
   - 量价：signalTier/direction/quadrant/tierReasons（unknown 如实标注）；
3. 原始证据行：涨幅、量比、主力净额（zlje，缺如实注记）、换手、当日排名轨迹一行（10 槽 rank+涨幅）；
4. 环境门注记行：生命周期 stage + veto 布尔（**只注记不投票**——阶段判定是题集 B 对象，防口径串题）；
5. 待复核判读块（明标「规则投票，仅供复核」）：四维各自方向 + synergy 档位。

### §二·三 判据（冻结件候选，逐字=将来代码文本；`QUESTION_SET_VERSION_VOTE_CONFIRM = "v1"`）

**instructions**：

> 以下是行情列表某股票当日收盘槽的方向投票读数：四维信号（共振/趋势/热度/量价）各自的档位、方向、分数与理由，以及原始行情证据行（涨幅/量比/主力净额/换手/当日排名轨迹）与环境门注记。请判断：该股当日方向投票整体应读作 buy、sell 还是 hold？判定以「给出明确方向的维数与档位强度对比」为主锚（buy 维与 sell 维各几票、最高档位在哪侧），并用原始证据行校验方向一致性。特别注意：①档位 unknown 或数据不足的维不计票（叙事中已如实标注）；②环境门只注记不参与投票；③原始证据与投票读数明显矛盾时（如读数偏多但当日放量下跌、排名大幅回落，或读数偏空但缩量上涨、排名大幅走高），以原始证据为准。只依据所给信息判断，不预测后市。

**criteria**：

- `buy`：多方：≥2 个有向维（共振/趋势/量价）方向为 buy，且无 A/S 档 sell 反票；热度档 A/B 正票可作佐证；原始证据行同向（涨幅为正、排名走高、主力未大幅流出）
- `hold`：观望：有向维方向互相冲突（buy 与 sell 各 ≥1）且无更高档位一侧主导；或全部有向维方向为 hold/unknown；原始证据行无方向（涨跌互现、排名横走）
- `sell`：空方：≥2 个有向维方向为 sell；或任一维 A/S 档 sell 反票未被足够档位的 buy 票覆盖；或量价档 E（出货硬风险）；原始证据行同向（放量下跌、排名大幅回落、主力净流出）

### §二·四 预检与 riskFlag（runner 侧，开火前冻结）

- `data_insufficient`（**不调用**，落 riskFlag 文档留痕）：有效档位维（signalTier≠unknown 的维）<2；
- `partial`（仍调用）：有效维 2-3，或证据行有缺（reasons 列明缺哪行，如 `zlje_missing`/`volume_ratio_missing`）；
- `ok`：四维全可算且证据行齐。
- riskFlag 结构：`{level, reasons[]}`；台账按 level 分层披露，partial 样本不进主判定门统计（只登记）。

### §二·五 对照锚（机械可算，冻结）

jev choice ↔ synergy 映射方向（S/A/B→buy、C→hold、D/E→sell）逐股比对 → agree/diverge 台账；
diverge 例逐条归因三分法（①原料缺口 ②判据措辞 ③解析层）。jev 分歧不是失败（并列观察者），
分歧例=诊断价值所在+人工盘感抽验对象。

## §三 题集 B：lifecycle_recheck（环境门阶段诊断复核）

### §三·一 对象与人口

- 对象：非 cooling 股 @ half_hour 15:00（ignition/expansion/crowded/reversal）。cooling 为默认态
  低信息量，不进 pilot（生产化再议抽样对照）。三日人口实测：09-07=21、09-18=53、09-30=64。

### §三·二 叙事原料清单

1. 头行；当日逐槽排名/涨幅轨迹行（10 槽）；
2. 生命周期度量块（全部可数）：rankVelocity、rankAcceleration、hotZoneStreak、bestRecentRank、
   drawdownFromPeak、rankPathCommitment、动量短/中/长与加速度、riskPressure；
3. 前一交易日阶段行（缺前日帧 → fail-visible 注记）；
4. 待复核判读块（明标「规则判读，仅供复核」）：规则 stage + action（allow/caution/veto）+ 理由；
5. **不含四维投票档位**（防方向票锚定阶段判定——题目间口径隔离）。

### §三·三 判据（冻结件候选，逐字=将来代码文本；`QUESTION_SET_VERSION_LIFECYCLE_RECHECK = "v1"`）

**instructions**：

> 以下是行情列表某股票的生命周期判定原料：当日逐槽排名轨迹、生命周期度量（排名速度/加速度/热区停留天数/近期最佳名次/距峰回撤/排名路径承诺度）、动量与风险读数、前一交易日阶段，以及规则判读块（仅供复核）。请判断：该股当前处在自身行情生命周期的哪一段？判段以「排名轨迹的位置与走向」为主锚（当日名次在窗口内的位置、全天走高还是走低、较昨日升降），并用动量与风险读数校准。特别注意：①点火与扩散的分界在启动的新鲜度（排名刚自低位起升 vs 已在高位持续走强）；②拥挤与反转的分界在高位是否出现回落证据（仍在高位区停留但未回落=拥挤，已自峰回撤且动能转负=反转）；③降温是既无低位起升也无高位滞留/回落证据的默认态。只依据所给信息判断，不预测后市。

**criteria**（分档语义与规则 `raw_stage/normalize_stage` 对齐，只锚叙事可数读数，不引规则内部阈值数字）：

- `ignition`：点火：排名自低位明显起升（速度与加速度同为正，当前分位尚不高/近期最佳名次尚浅/热区停留少）
- `expansion`：扩散：排名在较高位置持续走强（速度为正且当前分位高，加速度或热区停留或最佳名次佐证延续）
- `crowded`：拥挤：排名停留高位区多日但已无上升动能（速度趋平或转负）且距峰回撤很小——高位滞留
- `reversal`：反转：自近期峰值明显回撤（距峰回撤读数抬升）且动能转负（速度为负或加速大幅下行）——高位回落
- `cooling`：降温：排名处于中低位且无起升证据，高位滞留与回落证据均不满足

### §三·四 预检与 riskFlag

- `data_insufficient`（不调用）：当日轨迹槽 <5 或生命周期度量块不可算；
- `partial`（仍调用）：缺前日阶段行/个别度量缺失（reasons 列明）；
- `ok`：轨迹+度量+前日阶段齐。

### §三·五 对照锚与系统性分歧源登记（跑前冻结，防过度解读）

jev choice ↔ 规则 stage 逐股比对 → agree/diverge 台账；**diverge 例=诊断对象**（人工盘感终验）。
已知系统性分歧源（登记，不判错）：规则 `normalize_stage` 是带前一槽位阶段的状态机滞回，
jev 是当日截面判读——「滞回分歧」（规则沿袭前值、截面证据支持另一段）与「证据分歧」在台账分列。

## §四 槽位口径与 EOD 补齐读法（裁决 3 落法）

- **实测依据**：daily 15:30 帧行情字段稀疏（09-30 实测 261 股 change/volumeRatio/amount 全 0/null、
  量价档 261/261 unknown——历史采集模式所致）；half_hour 15:00 帧饱满（change 缺 2/255、
  量比缺 4/255、zlje 缺 7/255、量价档可算 251/255）。→ pilot 主口径 = **half_hour 15:00 单帧**。
- **EOD 补齐读法**（纯函数入弹药层，带单测）：以 daily 15:30 帧为基准，行情字段（change/volumeRatio/
  zlje/turnoverRate/amount）缺失处从同日 half_hour 15:00 帧补齐，补齐字段带来源注记。
- **边界一（同帧一致性）**：引擎五维档位不可跨帧拼接——15:30 的共振档与 15:00 的量价档从未在
  任何一次引擎运行中共存，拼出的「投票」不是引擎真实输出。补齐只针对行情原始字段（叙事原料层），
  不拼接引擎档位。生产 EOD 视角若要量价档可算，正确修法是**入库/分析前**补齐行情字段再跑引擎，
  属 snapshot 链改动（另行预登记，本批不碰）。
- **边界二**：存量 daily 15:30 帧的写库修复不在本批（涉存储红线+并行会话在改 snapshot_collector 文件）。

## §五 落地形态与版本戳

| 件 | 位置 |
| --- | --- |
| 题目常量+叙事组装纯函数+EOD 补齐读法（零 IO） | `backend/analysis/hotlist/jev_vote_ammo.py`（新，沿 jev_driver_ammo/jev_relay_ammo 归档模式） |
| runner（取数+预检+编排+落库） | `backend/operations/jev_vote_confirm.py`（新，复用 `_dispatch_jev` 等共享件） |
| pilot 集合 | `hotlist_jev_vote_confirm_pilot` / `hotlist_jev_lifecycle_recheck_pilot`，`_id={date}:15:00:{code}:VOTE\|LC` |
| 文档盖戳 | ammoVersion + questionSetVersion + questionSetHash + questionsRaw + riskFlag + answers 原样包 |
| 版本戳 | `QUESTION_SET_VERSION_VOTE_CONFIRM="v1"`、`QUESTION_SET_VERSION_LIFECYCLE_RECHECK="v1"`（独立戳，cycle v5 旧债不重犯） |
| 测试 | 弹药纯函数单测（叙事行/预检/补齐读法/对照锚映射）+ runner fixture 判读；零真实调用零网络 |

## §六 Pilot 设计（三日样本惯例，抽样上限已冻结）

- **样本日**：2026-09-07 / 09-18 / 09-30（三日 half_hour 15:00 帧与逐股 analysis 存量实测在库：240/240/255 股）。
- **抽样上限（冻结，确定性排序防挑样）**：
  - A 每日 ≤12 股：buy 侧（S/A/B）按「最高档位数降序→共振分数降序→代码升序」取 ≤8；
    sell 侧（D）按「量价 E 短路优先→代码升序」取 ≤4；
  - B 每日 ≤8 股：点火/扩散优先全量至 ≤5，剩余名额给拥挤/反转（按 stage+代码升序）；
- **预算双口径**：
  1. 单 call 实测外推：A ≈1.7-2.2k tokens/call、B ≈1.6-2.1k tokens/call → pilot 预估 ≈**105-130k tokens**；
  2. 人口全量反算：三日 A 400 股 + B 138 股 ≈ **1.0M tokens**（不采用，仅作口径警示）；
- **熔断**：硬顶 **150k tokens**，超限即停并汇报（usage 逐 call 累计，runner 打印）。

## §七 验证门（跑前冻结，cycle v5 同构）

1. **门1 叙事完整性**：两题集叙事块全呈现；缺口（量价 unknown、zlje 缺失、前日帧缺）fail-visible 注记
   如实出现，无伪装零值；riskFlag 分层如实落库；
2. **门2 人工盘感抽验**：每题集 ≥5 例（含全部 diverge 例）交用户对照行情盘感，无「明显读错证据」判例；
3. **门3 escape 率**：riskFlag=data_insufficient 占人口比例 ≤10%（两题集同线；打标链 unclear 6.4% 为参照）；
4. **附加产出（只登记不设门）**：agree/diverge 台账 + 分歧归因三分法（原料/判据/解析）+
   B 题集滞回分歧/证据分歧分列；jev 与引擎分歧本身不判失败（并列观察者定位）。

## §八 落库合同（裁决 5「全保留」落地）

- `answers`：parse 原样包（type/choice/confidence/probabilities 全字段保留，不裁剪）；
- 顶层便捷字段（可索引）：A：`voteDirection`/`voteConfidence`/`voteProbabilities`；
  B：`lcStage`/`lcConfidence`/`lcProbabilities`（confidence 升顶层，修旧账）；
- `responseRaw`：**ok 与 degraded 一律存完整 envelope**（修 cycle pilot「ok 存 None」口子）；
- `usage`/`latencyMs`/`model`/`computedAt` 照旧；`questionsRaw` 全文入档（复现审计）。

## §九 回退

题集常量、runner、pilot 集合全部独立新增，`git revert` 单笔即回退；不触碰存量集合、引擎代码、
jev_client/jev_sentiment_compute（N15 保留件）。

## §十 执行记录

- [x] **判据逐字确认（用户）**：2026-10-12 五裁决（risk_flag 代逃生口/对照锚/half_hour 15:00+补齐读法/
  抽样上限与 150k 熔断/全保留）→ 判据文本修订后用户回「确认」冻结；代码判据与本文档 §二·三/§三·三
  程序化逐字比对通过（VERBATIM OK）。
- [x] **代码+测试落地（零调用零网络）**：
  - 新增 `backend/analysis/hotlist/jev_vote_ammo.py`（题目常量/叙事组装/riskFlag 预检/对照锚/确定性抽样/EOD 补齐读法，零 IO）；
  - 新增 `backend/operations/jev_vote_confirm.py`（取数+预检+抽样+编排+落库；默认 dry-run 零调用，`--fire` 且有 token 才真实调用；TOKEN_FUSE=150_000/次运行）；
  - 新增 `tests/hotlist/test_jev_vote_confirm.py`（22 测全 fake：判据冻结/独立戳/预检/抽样/补齐/叙事 fail-visible/人口分类/落库合同全保留/熔断/dry-run 零调用）；
  - 全仓 pytest：**3478 passed**（基线 3456+22）；唯一失败
    `tests/market/test_server_limit_summary.py::test_provider_passes_collector_pool_subset`
    为并行会话在改 snapshot_collector/providers.py+slots.py 的在途改动所致（排除本批文件重跑同样失败），登记不碰；
  - 真实库 dry-run（只读零调用）人口实测：A 三日 buy/sell=42/105、58/70、38/87（合计 400，与存量档案一致）；
    B 三日人口 21/51/64（09-18 预检不足 2 落 partial 前留痕，合计 138）——与 §六预算人口完全吻合；
  - 真实叙事抽检修三处口径：zlje 原始单位=元（叙事折亿）、量价 direction 取值域 up/down/neutral
    （按引擎 _vote 投票语义归一 up→buy/down→sell/neutral→hold）、技术面事件 golden/dead/none 中文映射。
- [ ] 开火批准（用户）：
- [x] **pilot 执行（2026-10-12 用户「开跑」批准）**：双题集三日一并开火，**60/60 call 全部 ok、
  零 degraded**，实耗 **83,297 tokens**（A 49,500 + B 33,797；预估 105-130k 内，150k 熔断未触发）。
  落库 hotlist_jev_vote_confirm_pilot 36 文档 + hotlist_jev_lifecycle_recheck_pilot 24 ok+2 留痕。
- [x] **门1 叙事完整性 ✅**：60 例叙事全呈现；缺口 fail-visible 如实注记（特发信息 09-07 前半日
  5 槽行缺逐槽标缺、万科A 主力净额缺标注）；riskFlag：A data_insufficient 0/400、B 2/138=1.4%。
- [x] **门3 escape 率 ✅**：A 0%、B 1.4%，均 ≤10%（choice 无逃生口，按 riskFlag 口径）。
- [x] **对照台账（机器侧，判定门②人工盘感抽验待用户）**：
  - **A：agree 27/36（75%）、diverge 9**。9 例精确分型：
    - **8 例同型=量价 E 硬风险短路层**：引擎 D（映射 sell）vs jev buy（conf 0.13-0.86）。共同形态：
      涨停/近涨停+放量+主力净流入，量价档 E=「硬风险：对倒出货/过度放量」短路成 D——
      **对照锚把「硬风险止损语义」与「方向投票语义」混在同一 D 档**（corpus 已知 vp E→直接 D
      结构短路的直接暴露）。归因=①对照锚定义副作用+②sell 侧抽样刻意优先 vp-E 例（设计使然的
      探测层，非全人口 agree rate 推断口径）；jev 依据叙事中 E 档 tierReasons 与判据 sell 第三条
      仍读 buy，说明「方向语义 vs 风险语义同档打架」——**v2 议题候选：对照锚拆「方向 D」与
      「硬风险 D」两列，台账单列 vp-E 短路层**（本批判据已冻结不改，登记不重烧）。
    - **1 例反向（长城军工 09-07）**：引擎 B 弱买 vs jev sell（conf 0.35，probs sell 0.57）——
      共振S+趋势A+热度B 面板偏多，但原始证据缩量下跌 -2.59%/量比 0.79/净额仅 0.101亿，
      jev 按判据③「矛盾以原始证据为准」读 sell。判据③的直接用例，交人工盘感。
  - **B：agree 19/24（79.2%）、diverge 5**（滞回分歧/证据分歧分列）：
    - 特发信息 09-07：规则 **reversal+veto** vs jev crowded conf 0.14 平铺——前半日 5 槽行缺
      （fail-visible）+前日反转，原料半缺低置信不确认；veto 分歧例，重点交盘感；
    - 桂林旅游 09-18：规则 expansion vs jev ignition 0.56——「新鲜度」边界（排名 62→44 走高但
      动量全负+距峰回撤 15 位），排名轴/价格轴双轴分歧教科书例；
    - **华瓷股份 09-30：规则 expansion(放行) vs jev reversal 0.81 高置信——全天跌停（十槽全
      -10%）但 rankVelocity=+0.714/加速度 +4.57（普跌日「跌得少」被排名速度当「走强」）**。
      jev 按判据②「自峰回撤+动能转负」判 reversal，与盘感应一致——本批 jev 复核价值最高判例；
    - 多氟多 09-30：规则 ignition(0.90) vs jev reversal 0.39 低置信平铺——排名 162→104 缓升、
      价格微跌，诚实模糊日；
    - **云南锗业 09-30：规则 ignition(0.80) vs jev reversal 0.49——潜在 jev 误读例**（速度 6.13/
      加速度 4.15/距峰回撤仅 3 位/动量全正/风险压强 0.008，规则证据极强，jev reversal 判据依据
      不足），门②人工盘感的重点检验对象。
- [ ] **门2 人工盘感终验（待用户）**：抽验清单已列出（分歧全量 9+5 + 一致高置信抽 5）。
- [ ] 台账与分歧归因产出：机器侧完成（本节），v2 议题（对照锚拆双列）登记待裁决。
