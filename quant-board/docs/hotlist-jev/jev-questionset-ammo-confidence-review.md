# jev 题目集原料与置信度全景梳理（2026-10-11）

> 定位：全题目集「原料还差什么 / 置信度离 90 有多远 / 怎么优化」的一次性母文档。
> 数据来源：`scripts/jev_confidence_landscape.py`（2026-10-11 首跑，只读，零 jev 调用），
> 产出落 `data/reports/jev-confidence-landscape-20261011.md`；代码行号为当日工作区实况。
> 配套测试：`tests/hotlist/test_jev_confidence_landscape.py`（8 用例，纯函数零 IO）。

---

## §〇 结论先行

1. **「全题集 confidence≥90」不可达，也不应追求。** 2026-10-11 首次全景实测：现行代
   choice 主流题 top 概率 P50 集中在 0.44-0.81；全场最高的是个股相位分线题（topP50=0.93），
   最低的是日内槽 frame_stage（confP50=0.44）。日级温度/拥挤 score 题的分布天然分散
   （topP50 0.22-0.30、hstd≈1.5-1.9），这是「10 档锚上表达不确定」的协议设计，
   不是缺陷。把所有题推到 90+ 只会制造过自信伪影——**无锚旧代 crowding 的 confP50 高达
   0.95，但逃生率 79.5%（365 槽里 290 个 insufficient_evidence）**：模型最自信的代，
   恰是判据引用了叙事没有的证据、大量拒答的时代。
2. **正确目标形态**（本文档建议）：证据满窗日主流题 conf/top P50 ≥70-80；F2 校准单调
   （confidence≥0.7 桶的人工裁决正确率 > 低置信桶）；结构性贫料场景（09:30 开盘槽、
   帧分辨极限形态、贴线触发档）的低置信作为犹豫信号透出（阈值 60%），不消灭。
3. **置信度与证据充足度实测单调**：v2.5 frame_stage 按槽位切片，15:00 收盘槽
   confP50=0.60/P90=0.898 显著高于日内各槽（0.36-0.51）；判据最可数化、锚最密的
   stock_phase_position 全场置信最高（topP50 0.93）。**提置信的第一杠杆是补证据与
   可数化判据，不是要求模型自信。**
4. **confidence 至今未校准**：模型自报字段，从未验证「conf≥0.9 是否 90% 判对」
   （F2 需 ≥100 条现行代裁决，现 52 条且 41 条窗外旧代，
   `jev-temp-crowding-confidence-deepening.md` §四）。且**打标/Q5/cycle/relay/zhaban
   五条链落库时把 confidence 丢了**（只提取 choice+probabilities），score 直方图也只
   在 sentiment/crowding_pilot 两集合可读——「哪些题置信高」此前是笔糊涂账，本次
   统计是第一份台账。
5. **原料缺口分三层**（§二 逐题对照）：可补原料解决的（除权假阴、zhaban 高位锚、
   relay 龙头档案依赖）、需判据改造的（crowd_clearing 无可数回落定义、day_pattern
   缺槽位级归一）、结构性补不齐的（cycle_stage 需未存数据、日内帧分辨极限）。
   对应优化方案按 P0（零 token）/P1（补原料，烧 token 须预登记）/P2（改门）分层，
   见 §五。**除 P0 已落地项外全部待用户裁决，本文档不实施。**

---

## §一 题目集全景（9 套 25 题）

### A. 情绪链（`hotlist_jev_sentiment`，QUESTION_SET_VERSION v2.5，jev_state.py:86）

一次调用共享同一份叙事；槽级叙事截 4000 字符（jev_state.py:606）、EOD 截 6000（:640）。

| 组 | 题 | 类型/答案空间 | 定义 |
|---|---|---|---|
| 槽级 4 题 | frame_stage | choice 五档 ice/start/ferment/climax/retreat | jev_state.py:89-94；判据 `_STAGE_CRITERIA_V2` :45-51 全绑近 20 日分位 |
| | sequence_stage | choice 五档（结合当日已走帧序列） | 同上 |
| | temperature | score 十档锚 SCORE_ANCHORS_10 | jev_state.py:15、:70-71 |
| | crowding | choice 六层（v2.5 增 crowd_clearing） | `_CROWDING_CRITERIA_V2` :56-68 |
| EOD 4 题 | day_stage | choice 五档 | jev_state.py:96-109、:53-54 |
| | day_pattern | choice 八类（v2.5 增 late_rescue） | `_DAY_PATTERN_CRITERIA` :24-34 |
| | day_temperature | score 十档 | :105 |
| | day_crowding | choice 六层 | :107-108 |

### B. 打标链（`hotlist_jev_driver_labels`，v3.1，jev_driver_ammo.py:124）

| 组 | 题 | 答案空间 | 定义 |
|---|---|---|---|
| 个股 4 题（一 call） | driver_type | 七类驱动 | jev_driver_ammo.py:30-39 |
| | catalyst_depth | 六桶（动词七级+T1-T3 证据分级+并购路由） | :40-55 |
| | catalyst_freshness | 四类（纯日期锚 ≤2 交易日） | :56-64 |
| | buy_side_logic | 四类买盘 | :65-71 |
| Q5 日级哨兵（独立 call） | phase_band | 四档 cold/weak/strong/insufficient | :75-82；runner jev_label_jiuyan.py:888-917（只喂盘面事实行，防锚定污染 :7/:367） |
| 个股相位分线 v0.5（合并同 call） | stock_phase_position | 五层 divergence/climax/ferment/start/insufficient | jev_driver_ammo.py:88-115；runner :920-1009 |

### C. 连板接力（`hotlist_jev_relay_index`，v3，jev_relay_ammo.py:20）

七题一 call（jev_relay_ammo.py:34-100）：relay_index（score）、relay_phase（choice 六相位）、
relay_momentum（choice 五）、ladder_health（choice 五，判据绑量化比率 :66-67）、
leader_strength（score）、money_effect（choice 四）、theme_pulse（choice 四）。
叙事七段（jev_relay_index.py:457-475）。

### D. 炸板归因（`hotlist_jev_zhaban_labels`，v1，jev_relay_ammo.py:105-119）

单题 zhaban_cause 五桶 high_divergence/sector_collapse/chase_fail/broad_market/insufficient；
叙事原料六块（jev_zhaban_label.py:72-127）。

### E. 外围试点

| 题 | 状态 | 定义 |
|---|---|---|
| cycle_stage 七段 | 挂起（四轮不过 4/5 线） | jev_driver_ammo.py:144-158；runner jev_label_jiuyan.py:857-885 |
| crowding_score / day_crowding_score 双轨 pilot | S1 方差 FAIL，S2 待 10 月富弹药终判 | jev_crowding_score_pilot.py:61-75 |
| daily_shape 日度一句话 | 规则模板拼句，jev 只判 choice 七类、<5 槽规则兜底 | jev_daily_line.py:53-76、:139-140 |

### 调用与解析通道（全部题目集共享）

- 双通道：`_dispatch_jev`（jev_sentiment_compute.py:32-40）官方直连优先、CF 网关回退；
  重试 (2.0, 5.0)s（jev_client.py:29）。
- 协议三原语 choice/score/noul；score 返回「锚点概率加权期望+legend+全档位分布+confidence」，
  归一公式 `score/(len(legend)-1)*100`（jev_client.py:139-148）。
- **confidence 与 probabilities 均为模型自报，代码零计算**（jev_client.py:149 原样透传）。

---

## §二 逐题原料对照与缺口（三档分类）

> 档位定义：A=补原料可实质提升；B=需判据/题目改造（改门）；C=结构性补不齐，
> 低置信即如实表达。同一题可能跨档（原料补一部分、判据再改一部分）。

### A. 情绪链（槽级+EOD 8 题）

**现有原料**（jev_state.py:418-538 当前帧证据节，全清单）：
指数与量能（4 指数+两市额 vs 昨日同期）、涨停/炸板（ztCount/板高分布/炸板率/封板率，
09:30 伪 0 注记 :449-452）、sealQuality 封板质量（一字秒板/硬板/开板重封/重封率/历史封板
成功率）、drawdown 触板回撤池、涨跌五桶、热榜 TRIN（含涨跌向成交额）、主力资金
（zljeSum）、新进淘汰、昨日涨停今日表现、池内生命周期六态、行级 strongMoney/risk、
焦点个股 top8、涨停原因 top5；头部+近 20 日分位锚段+当日已走帧压缩行+数据质量声明。
EOD 另有逐帧证据+当日累计（新进/淘汰/主力净额合计/最高板峰值/两市额 vs 昨日全天）。
2026-10-02 起 sealQuality/drawdown 已接线（阶段 3 弹药，此前的「贫料环境」已翻页）。

| 题 | 档 | 缺口 |
|---|---|---|
| temperature / day_temperature | C 为主 | score 协议本意=用分布表达不确定；hstdP50 1.51-1.97 是健康离散。原料侧仅剩边际项：主力资金 zlje 缺失率 ~219/228 帧（arsenal 审计）——补采 ROI 低；**不应**以规则分校准温度（meanAbsDiff≈13 是口径差非误差，REVERSE 信号在身） |
| frame_stage / sequence_stage / day_stage | A(小)+C | 判据已满锚（五档全绑近 20 日分位）。日内槽置信 0.36-0.51 的主因=**槽位证据天然少于收盘**（15:00 槽 0.60 对比）；10:00-10:30 反而是日内低点（0.36-0.38），与开盘后锚参照弱有关。可做：锚段补「同槽位历史分布」（现锚只有日级分位，无槽位级——day_pattern P5 已登记同款缺口，9 月 11:00 在场率仅 7/21）；属 P1 预登记项 |
| crowding / day_crowding | B | 判据硬伤：crowd_clearing「触及（≥p80）」允许贴线单轴触发、「明显回落」无可数定义（方案 B 观测量预登记在案，glm53-crowding-a1:26/56/83）；v2.5 逃生率仍 45.1%（102/226 insufficient_evidence）——炸板/涨停证据帧间缺口是主因（genuine 双零日），原料补齐方向=THS 限流漏采冷却重采（b5d4ac36 已优化，剩余间歇缺口） |
| day_pattern | B+C | 帧分辨极限：late_rescue 置信 0.26-0.30 是 30 分钟槽判「尾盘偷袭」的极限（2/21 摇摆是设计必然）；判据包 v2.6 已冻结但**激活前置=槽位级归一参照表**（强帧≠日级 p50，9 月同槽位在场率 11:00 仅 7/21，数据考古可行性未评，day-pattern-p5 §八） |

### B. 打标链（个股 4 题+Q5+相位）

**现有原料**（build_pilot_narrative，jev_label_jiuyan.py:568-610 八块）：
①盘面事实行 market_facts_line（:366-409，涨停/跌停/炸板率/回撤/连板梯队/最高板各带
近 20 日分位+池内涨跌比）；②个股行（韭研 day/num/涨停时间/热榜排名）；③THS 身位块
（连板天数/首封/板块/主力净额，:578-586，100% 覆盖）；④TDX 20 日个股位置行（距高点/
窗口涨幅/低点距今/近 5 日贡献/量能 vs 前 3 日均量，jev_driver_ammo.py:188-226）；
⑤板序 ○● 行（近 10 日序列/断板反包，:229-254）；⑥当日板型行（5 分钟线机械判定
一字/秒板/炸板回封/烂板，:257-293）；⑦板块地位（韭研板块涨停家数+封板序）；
⑧韭研解析全文（expound，缺失 fail-visible）。

| 题 | 档 | 缺口 |
|---|---|---|
| catalyst_depth | A | 实测 topP50 0.66、骑墙 39.9%——离散度来自「韭研解析的信息密度」本身：解析缺收入占比/订单金额时六桶边界模糊。**原料缺口=解析质量而非弹药字段**（T1-T3 分级已入题干）；改善路径在采集侧（jiuyan expound 全文已直供）而非叙事侧，无低成本动作 |
| driver_type | A | topP50 0.66、骑墙 43.8%。七类中 capital_flow/concept_stretch 边界互渗（资本接力 vs 蹭概念）。可数化方向=Q4 判据已有「身位+板块涨停家数+封板时间」锚，但 capital_flow 判据本身是排除式定义（「无明确新催化」）——**排除式判据天然低置信**，改门属 P2 |
| catalyst_freshness | A | unclear 8.0-9.2% 压线登记。纯日期锚已最优；剩余 unclear=解析无日期，原料侧无解（解析作者不写日期）。**注意：runner 未落 probabilities（jev_label_jiuyan.py:673-674 只存 choice），置信现状首次才可测——本次统计 noProb=n 全量** |
| buy_side_logic | — | topP50 0.79/骑墙 18.3%，四类判据锚结构化身位，现状健康 |
| Q5 phase_band | — | topP50 0.78-0.81；「40-60 判低一档」被裁定为哨兵价值非缺陷（review §十五登记不动）。强/非强两档一致 18/21 |
| stock_phase_position | A(残) | **全场置信最高 topP50 0.93**——三轴可数判据+判例锚定的示范。残留：除权日 prev_close 失真可致板序假阴（jev_driver_ammo.py:232 已登记）；深物业A ferment 复核未裁决；divergence 判别力深验未做 |

### C. 连板接力（7 题）

**现有原料**（build_relay_narrative 七段，jev_relay_index.py:513-531）：盘面事实+今日炸板面
（zhaban_face_line：炸板家数分位/反复开板占比/昨日池股今日炸分层/炸板收盘中位/
大面/代表 top3/炸板归因分布聚合/**较昨日增减**——2026-10-15 诊断补供，炸板与反复开板
家数昨日→今日直给，criteria「较昨日收敛/恶化」此前无可比数）→ 晋级断板与隔日溢价 →
梯队结构（首板/二板/三板+/二板÷三板+ 比率）→ 三日晋级链+题材演化（三日链行尾
**边际对比**：昨日池今日晋级率 vs 前日池昨日晋级率直给，2026-10-15 诊断补供）→
题材梯队表 top5（消费 driver 标签聚合）→
龙头档案（最高板+身位/板序/板型三行）→ 近 10 日轨迹+防锚定参照段（显式标注
「非今日证据」）。

| 题 | 档 | 缺口 |
|---|---|---|
| relay_phase | B | divergence 38/60 中心化（collapse→divergence 粒度偏细，phase2-report §五登记 4 周复查）；topP50 0.66 骑墙 40%。判据侧次级缺口已补（§九第二批）：断板亏钱「扩散/增多」与首板占比「明显升高」的昨日可比数、反复开板分位于 2026-10-16 直供叙事 |
| relay_index / leader_strength | A(观测) | score 题分布未落库（runner 只存归一分 jev_relay_index.py:505/510），hstd 不可测；ρ=0.895 与规则轨相关超带，长期观察 ≥40 交易日复测 |
| relay_momentum | B | **2026-10-15 逃生诊断（§九）**：全库 43/107（40%）insufficient_evidence，仅次于 weakening（45%）；「近1月仅 2 次」是展示窗口假象。根因=两个主锚的「较昨日对比」全库从未组装（分位/均值只给绝对位置）+ criteria 合取项引用未供给证据；判据零改动，语料侧已补（§九） |
| ladder_health / money_effect / theme_pulse | — | probabilities 历史文档未落库（P0-2/P0-3 起新文档有 `answers` 包可测，存量不可回补）；判据侧 ladder_health 已绑量化阈值、theme_pulse 已定连续 ≥3 日门槛（phase2 修正项） |
| 跨轨依赖 | A | 题材梯队表消费 hotlist_jev_driver_labels 的 freshness/driver 聚合——打标链某日未跑则该段降级；龙头档案同理。**当日炸板归因打标（hotlist_jev_zhaban_labels）同属跨轨依赖，2026-10-15 发现调度链反序致 relay 叙事恒未见当日归因，已修（§九）** |

### D. 炸板归因（zhaban_cause）

**现有原料**（build_zhaban_narrative，jev_zhaban_label.py:72-127）：THS 触板分钟轨迹
（首触/末触/时长/末 10 分钟斜率）+ 昨日板数/今日最高/收盘/换手/流通市值 + 板序 ○● +
板块语境（今日触板家数/昨日对照/今日炸板家数/板块最高板）+ 大盘 indices + open_num。

| 题 | 档 | 缺口 |
|---|---|---|
| zhaban_cause | A+B(残) | 实测 topP50 0.71/骑墙 25%/逃生 9.8%；chase_fail 84.7% 塌缩已定性「launch/relay_heat 相位下结构本就单一」（扩试点 5/5 vs 2/2 无交叉过门）。残留原料缺口：①韭研 num 首板不标→高位锚缺（THS continueDay 可直供替代）；②韭研触板池漏收（佰奥智能案例）；③sector_collapse 桶七日 0 只未激活（板块昨日缩容对照已有，等真实板块退潮日验证）；④09-18 类 indices 空帧 |

### E. 外围

| 题 | 档 | 缺口 |
|---|---|---|
| cycle_stage | C | 拐点日 100% 出错且不随判据迭代收敛；冰点 vs 杀跌区分需**未存数据三件套**：量能方向（帧 indices/moneyFlow 无存量，KPL 有）、全市场涨跌家数（marketStats 全零）、大面规模——采集增强前该题不可靠（review §十二 V4）。试点 8 天 topP50 0.81 说明「自信地错」风险真实存在 |
| crowding_score pilot | C(待终判) | confP50 0.39/topP50 0.22——score 轴区分度问题（S1 std=6.2 FAIL），非原料问题；S2 待 10 月富弹药 |
| daily_shape | — | 规则模板+jev choice 七类、<5 槽不烧 jev；锚 <8 样本返 None 护栏已有 |

---

## §三 置信度机制与全景实测（2026-10-11 首次统计）

### 3.1 机制

- confidence/probabilities **全部模型自报**，`parse_jev_response` 原样透传（jev_client.py:149），
  代码零计算零修改；score 归一分公式 `score/(len(legend)-1)*100`（:139-148）。
- score 题分布是主数据：E[anchor]/9×100≈落库分（deepening §〇.1 实测 6.28→69.8 vs 69.7）。
- 骑墙阈值 60%（top 概率，复核工作台同口径）。

### 3.2 全景观测（现行代；完整表见 data/reports/jev-confidence-landscape-20261011.md）

| 集合 | 题 | n | confP50 | topP50 | top<60% | 逃生% | 备注 |
|---|---|---|---|---|---|---|---|
| sentiment v2.5 | frame_stage | 226 | 0.44 | 0.55 | 58.4% | 0 | 日内槽 0.36-0.51、15:00 槽 0.60 |
| | crowding | 226 | 0.73 | 0.78 | 21.7% | **45.1%** | 逃生主因=帧间涨停/炸板证据缺口 |
| | temperature | 226 | 0.50 | 0.28* | 99.6%* | 0 | *score 题看 hstdP50=1.57 |
| | day_pattern | 23 | 0.38 | 0.47 | 78.3% | 0 | EOD n 尚小 |
| driver v3.1 | driver_type | 153 | 未落 | 0.66 | 43.8% | 0 | confidence 五链未落库 |
| | catalyst_depth | 153 | 未落 | 0.66 | 39.9% | 0.7% | |
| | buy_side_logic | 153 | 未落 | 0.79 | 18.3% | 0 | |
| | stock_phase_position | 294 | 未落 | **0.93** | 10.9% | 2.0% | 全场最高（9/30 五轮试点） |
| | phase_band | 21+2 | 未落 | 0.78-0.81 | 9.5% | 0 | |
| relay v2 | relay_phase | 60 | 未落 | 0.66 | 40.0% | 0 | divergence 38/60 中心化 |
| zhaban v1 | zhaban_cause | 1484 | 未落 | 0.71 | 25.0% | 9.8% | chase_fail 84.7% 塌缩已定性 |
| crowding pilot | crowding_score | 30 | 0.39 | 0.22* | 100%* | 0 | *hstdP50=1.93；S1 FAIL 待 S2 |
| cycle pilot | cycle_stage | 8 | 未落 | 0.81 | 12.5% | 0 | 「自信地错」风险（拐点日） |

历史对照（贫料教训的量化实锤）：(no-stamp) 旧代 crowding confP50 **0.95** 但逃生
**79.5%**（无锚代判据超证据，模型高置信拒答）；v2.5 满锚后代 confP50 0.73、逃生 45.1%。

### 3.3 本次统计暴露的结构性缺口（解析层，非模型行为）

> **2026-10-11 更新**：下列 1-3 的向前修复已随 P0-2/P0-3 落地（五链新文档带 `answers` 原样包，
> 见 §五/§七）；本节描述的是历史文档的存量状态，不可回补。

1. **五条链落库丢 confidence**：driver（jev_label_jiuyan.py:669-677/908-909）、cycle（:876）、
   relay（jev_relay_index.py:505-512）、zhaban（jev_zhaban_label.py:174-175）只提取
   choice+probabilities，confidence 字段未落；responseRaw 成功时为 None——历史文档已不可回补，
   只能向前补。
2. **freshness 无 probabilities**（jev_label_jiuyan.py:673-674）；**relay momentum/ladder/
   money/theme 四题无 probabilities**（jev_relay_index.py:508-512）；**relay 两个 score 题
   无直方图**（:505/510 只存归一分）。
3. sentiment/crowding_pilot 两集合 answers 原样落库，confidence/分布可读——口径不统一本身
   是观测债。

### 3.4 与「≥90」的距离读数

- choice 题里距 0.9 最近的是 stock_phase（topP90=1.0、P50 0.93）与 buy_side（P90 0.98）——
  即**可数化判据+结构化身位锚的题已经在 P90 尾部达到 90+**；
- 判据排除式/语义式的题（driver_type、catalyst_depth、relay_phase）P50 卡 0.66 附近，
  P90 0.95+——**尾部能到、中位靠原料与判据**；
- score 题（温度/拥挤/接力指数）协议上就不该用「top≥0.9」衡量，等价口径是 hstd 收窄
  （原料越足 hstd 越小：冒烟 19-32 → 有证据 14-26，crowding reevaluation §四）。

---

## §四 「置信度 ≥90」可达性分析

**可达（补原料+可数化后 P50 进 0.7-0.9 带）**：stock_phase_position（已达成，示范样本）、
buy_side_logic、phase_band、zhaban_cause（高位锚补齐后）、ladder_health/theme_pulse
（判据已量化）。共同点：判据引用叙事中**已有的可数证据**+结构化锚直供。

**部分可达（P50 0.6-0.75，P90 尾部 90+）**：driver_type/catalyst_depth（受解析信息密度
上限约束）、relay_phase（粒度改造后）、frame/sequence_stage（槽位级锚补充后）、
Q5（40-60 带结构分歧=哨兵价值，不应推高）。

**不可达也不应追求**：
- score 题的「top≥0.9」——协议用分布表达不确定，等价口径是 hstd，且「原料越足 hstd 越窄」
  已实测；强行收窄=要求模型隐藏不确定。
- 09:30 开盘槽、10:00-10:30 锚弱槽——证据物理性不足；正确姿势=透出低置信+数据质量注记
  （已有 09:30 伪 0 注记先例，jev_state.py:449-452）。
- late_rescue/贴线 crowd_clearing/真实冰点日 cycle——形态分辨极限或稀缺事件样本不足。
- **一切未过 F2 校准的「高置信」**：confidence≥0.9 目前没有任何证据等于 90% 正确率；
  无锚代 0.95 置信+79.5% 逃生是反面教材。

---

## §五 优化方案（P0/P1/P2 + 待裁决）

### P0 零 token（本轮已落地 / 立即可做）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| P0-1 | 置信度全景统计脚本+测试 | ✅ 本轮落地 | scripts/jev_confidence_landscape.py（8 测试绿）；建议月度复跑对新增量 |
| P0-2 | 五链落库补 confidence 字段 | ✅ 2026-10-11 落地 | 实施形态=五链 runner doc 增 **`answers` 原样包**（对齐情绪链先例，confidence/缺失 probabilities/score 直方图/未来字段一次保全；显式 conf 字段仅 `stockPhaseConfidence`——单题 $set 路径写整包会覆盖主 call 五题包故单列）。只向前生效，历史不可回补；不改判据不动题目 |
| P0-3 | freshness/relay 四题补 probabilities、relay score 题补直方图落库 | ✅ 2026-10-11 落地（随 P0-2 answers 包一并保全） | 统计脚本提取器已升级：blob 优先/字段回退（旧文档行为不变），新文档全量可测含 score 直方图 hstd |
| P0-4 | F2 校准样本扩容 | 待执行（人工裁决，非代码） | 复核工作台现行代裁决 52→≥100 条后才能回答「conf≥0.9 是否可信」——**这是「期望置信度 90」的前提验证，优先级高于一切原料改造** |
| P0-5 | 锚供给监控 C2 告警 | ✅ 2026-10-11 落地 | `evaluate_anchor_escape_alert`（jev_sentiment_compute.py）：单日槽位逃生率（crowding=insufficient_evidence 的现行代 ok 槽占比）>25% 连续 2 日→logging.warning+EOD doc 嵌 `anchorEscapeRate`/`anchorEscapeAlert`；**只上报不阻断**（评估自身异常也不影响主链路）；基线只算现行代戳文档 |

### P1 补原料（烧 token，须预登记+预算确认后实施）

| # | 项 | 受益题 | 预估 | 验证门 |
|---|---|---|---|---|
| P1-1 | 除权日 prev_close 修正（板序假阴根治） | stock_phase/zhaban/relay 龙头档案 | 数据层修复零调用；回放对照若干天 | ✅ 2026-10-11 落地（方案定案见 jev-ammo-p1-preregistration.md §一+附录：百度除权日程×交易所公式；AMMO_VERSION→2026-10-11a；不整月重跑） | 除权股板序行逐位复核（603337 冒烟已过，2-3 只抽验待续） |
| P1-2 | zhaban 高位锚：THS continueDay 直供替代韭研 num | zhaban_cause high_divergence 桶 | 试点 2-3 日 ≈2 万 tokens | ✅ **试点收官**（2026-10-11 两日开火，用户逐次确认）：09-17 divergence 日 20 只（20,470 tok）+ 09-21 relay_heat 日 25 只（25,225 tok）合计 45 只 ≈4.6 万；机制验证两日复证通过（昨日 2 板→high_divergence 0.71、昨日首板→chase_fail、未收录如实）；分离门方向正确（5% vs 0%，与扩试点带相容）；本窗零归因翻转（旧代经板序已判对），增量定位=首板盲区区分+除权备份（P1-1 复合）；ZHABAN_AMMO_VERSION=2026-10-11a 落默认随日常运行。详见预登记 §二执行记录 | 无遗留（可选追加：锚人群最富日 09-08 13/4 行为增量检验） |
| P1-3 | 槽位级历史参照锚（同槽位 ztCount/炸板率分位） | frame/sequence_stage、day_pattern v2.6 激活前置 | **前置考古已完成（2026-10-11，§七）：结论=当前不可行**——帧在场率已修复（20-21/21）但盘中槽位有效 ztCount 仅 7-16/21（伪 0/双零缺口），直接算同槽位分位会触伪 0 红线（p20 被压到 0）；前置条件转移到 P1-4（盘中 limitSummary 缺口甄别与补齐），暂缓 | P5 预登记既有门 |
| P1-4 | THS 间歇缺口冷却重采补齐 | crowding 逃生率 45.1%→观测下降 | 采集侧零 jev 调用 | ✅ 2026-10-11 收口（零施工）：前向已自愈（10-08/09 全槽健康，持续观察交 P0-5 告警）；历史不可重建（backfill_limit_evidence 探针结论「THS 历史=EOD 语义」）；P1-3 解锁路径=盘中有效样本自然积累 ≈2026-11-10 | 逃生率月度对比 |

### P2 判据改造（改门，须用户逐项点头，预登记冻结后 pilot）

| # | 项 | 受益题 | 既有方案 |
|---|---|---|---|
| P2-1 | crowd_clearing「明显回落」可数化（≥1 个观测量定义） | crowding/day_crowding | 方案 B 观测量预登记在案（glm53-crowding-a1） |
| P2-2 | relay_phase collapse/divergence 粒度合并或判据细化 | relay_phase 中心化 | phase2-report §五 4 周复查（到期跑本统计脚本对拍） |
| P2-3 | driver_type capital_flow 排除式定义改锚定式 | driver_type 骑墙 43.8% | 需先积累 capital vs concept 分歧样本 |
| P2-4 | cycle_stage 采集三件套（量能方向/涨跌家数/大面规模） | cycle_stage 复活前置 | 采集增强 ROI 先行评估（KPL 有量能方向存量可回补） |

### 明确不做（反面清单）

- 不以规则情绪分校准 jev 温度零点（口径差非误差，REVERSE 信号在身）。
- 不删 insufficient_evidence 逃生口或施压模型提置信（无锚代 0.95/79.5% 教训）。
- 不给 score 题加「必须 top≥0.9」类验收（协议本意=分布表达不确定）。
- 不回填 7/8 月 406 份无戳文档的 confidence 观测（跨代不可比，fail-visible 留档）。

---

## §六 复跑与维护

- 统计脚本：`./.venv/Scripts/python.exe scripts/jev_confidence_landscape.py --out data/reports/jev-confidence-landscape-<date>.md`
- 建议节奏：月度或判据代际升级后复跑，与上一份对拍（版本段自动隔离）。
- 本文档结论的消费方：复核工作台（F2 校准）、锚供给监控（P0-5）、后续判据改门预登记引用。

---

## §七 实施记录（2026-10-11 P0 批次）

**范围**：§五 P0-2/P0-3/P0-5（用户指令「按本文档编写 plan 开始实施」；P0-4 为人工裁决、
P1 烧 token/改原料代际须预登记、P2 改门须逐项点头，均未实施）。零 jev 调用、判据零改动。

### 改动清单

| 文件 | 改动 |
|---|---|
| backend/operations/jev_label_jiuyan.py | `_label_one` doc 增 `answers` 原样包；合并路径增 `stockPhaseConfidence`；`run_stock_phase_pilot` $set payload 增 `stockPhaseConfidence`（不写整包防覆盖主 call）；`run_phase_band_day`/`run_cycle_stage_day` doc 增 `answers` |
| backend/operations/jev_relay_index.py | relay doc 增 `answers`（七题 confidence/momentum 等四题 probabilities/两 score 题直方图自此保全） |
| backend/operations/jev_zhaban_label.py | zhaban doc 增 `answers` |
| backend/services/jev/jev_sentiment_compute.py | 新增 `ANCHOR_ALERT_ESCAPE_RATE=0.25` + `evaluate_anchor_escape_alert`（纯读）；`compute_and_upsert_for_day` 成功路径评估告警并嵌入 `anchorEscapeRate`/`anchorEscapeAlert` 字段；告警触发时 logging.warning，评估异常仅告警不影响主链路 |
| scripts/jev_confidence_landscape.py | 提取器升级：`blob_or_field`/`score_blob_or_field`（answers 包优先，旧文档字段回退行为不变）；`field_view` 支持可选 conf_field |
| tests/hotlist/test_jev_confidence_landscape.py | +5 用例（blob 优先/缺题回退/conf 字段/score 直方图 hstd/driver 五题全含） |
| tests/hotlist/test_jev_anchor_escape_alert.py | 新建 7 用例（连续 2 日判定/阈值严格大于/无 ok 槽/无前日/现行代基线/EOD 集成嵌入且不阻断） |

验证：`pytest tests/hotlist/` 347 passed（原 335 + 新增 12）。

### P1-3 前置考古结论（槽位级在场率，只读实测）

窗口 2026-09-03 → 2026-10-09（21 交易日，ok 槽文档口径）：

| slot | 在场/21 | 有效 ztCount>0 /21 |
|---|---|---|
| 09:30 | 21/21 | 12/21 |
| 10:00 | 21/21 | 16/21 |
| 10:30 | 21/21 | 12/21 |
| 11:00 | 21/21 | 9/21 |
| 11:30 | 21/21 | 10/21 |
| 13:00 | 20/21 | 9/21 |
| 13:30 | 20/21 | 10/21 |
| 14:00 | 20/21 | 7/21 |
| 14:30 | 20/21 | 8/21 |
| 15:00 | 21/21 | 21/21 |

两个读数：①**帧在场率已修复**（THS 风控优化+回填后 20-21/21，此前登记的「11:00 仅 7/21」
已被后续修复覆盖，引用前须当日复测的纪律再次验证）；②**盘中槽位有效 ztCount 仅 7-16/21**
（伪 0/双零缺口集中在中午后），同槽位分位锚若直接计算会把 p20 压到 0（伪 0 红线）。
**结论：P1-3 当前不可行，前置条件=盘中 limitSummary 缺口甄别与补齐（并入 P1-4 范畴）**；
顺带解释了日内槽位置信低的一部分——不是锚段（日级 15:00 满窗健康）弱，是盘中帧证据本身缺。

### 未实施项（保持登记，等各自门）

- P0-4 F2 校准：人工裁决 52→≥100 条——**2026-10-11 用户裁定本人执行**（工作台调研事实：
  裁决存 phase_monitor kind=review_items，53 条存量全部 legacyCriteria 窗外，现行代需新增
  ≥100 条；工作台在 jev 第 7 页签，POST /review-ruling 回填）。
- P1-2 zhaban 高位锚直供：烧 token 试点（≈2 万），须预登记+预算确认——**代码已落地待开火**。
- P2-1..4 判据改造：改门须用户逐项点头。

---

## §八 实施记录（2026-10-11 P1 批次，同日第二轮）

**范围**：用户指令「P0-4 我来做，你做 P1-1/P1-2/P1-4」。预登记
`jev-ammo-p1-preregistration.md`（含方法切换附录）。零 jev 调用；判据/题目零改动。

| 项 | 结论 | 关键落地 |
|---|---|---|
| P1-1 除权修正 | ✅ 落地 | 因子源三级实测定案=**百度除权日程 × 交易所公式**（东财被墙/腾讯 hfq 非事件链皆实证弃用，见预登记附录）；`_div_event_list`（按日缓存）+`_adj_prev_series`（交易所公式参考价）→ ammo `sequence_line/position_line/_prev_close_of_date` 逐链消费，带「除权修正已应用」注记，无事件/取数失败=原口径字节不变；AMMO_VERSION→**2026-10-11a**；603337 真实冒烟过 |
| P1-2 zhaban 高位锚 | ✅ 代码落地，**试点待开火** | `build_zhaban_narrative` 增「昨日身位（THS 连板梯队）」行（ths_positions 昨日 15:00 帧，首板也收录）；ZHABAN_AMMO_VERSION=**2026-10-11a** 戳；试点设计 2-3 日 ≈2 万 tokens 预登记 §二，待用户点头 |
| P1-4 盘中缺口 | ✅ 收口（零施工） | 前向已自愈实证（10-08/09 全槽健康）+历史不可重建（既有探针）+P1-3 自然积累解锁（≈11-10）；观察义务移交 P0-5 C2 告警 |

改动文件：`jev_driver_ammo.py`（因子纯函数层+AMMO_VERSION）、`jev_label_jiuyan.py`
（`_div_num/_div_event_list/_adj_prev_series` + 三壳 wiring）、`jev_relay_ammo.py`
（ZHABAN_AMMO_VERSION）、`jev_zhaban_label.py`（昨日身位行+戳）、
`test_jev_dividend_adjust.py`（新 11 用例）、`test_jev_label_raw_material.py`（戳/桩同步）。
验证：hotlist 358 passed（含新 11 例）+ snapshot_collector 557 passed；akshare 真实冒烟
（603337 除权事件命中+修正注记）。待办抽验：2-3 只近期除权股板序行逐位人工复核。

---

## §九 实施记录（2026-10-15 relay_momentum 逃生诊断批次）

**触发**：用户报 10-15 连板情绪【边际】=insufficient_evidence，「历史仅两次（另有 9-21）」，
要求归因是否喂给 jev 的语料不足。**判据/题目零改动，questionSetVersion 维持 v3**（纯语料补供）。

### 诊断结论（结论先行）

1. **「历史仅两次」是展示窗口假象**：relay 页默认区间=近1月（09-16~10-15，16 日），窗口内
   确仅 09-21/10-15 两次；**全库 107 ok 日 insufficient_evidence 43 天（40%）**，仅次于
   weakening 48 天（45%），accelerating 仅 15 天。分月：5月 9/18、6月 15/21、7月 9/20、
   8月 7/17 → 9月 2/20、10月 1/5（前期过半逃生，近期改善）。
2. **两日不是缺料环境**：10-15/09-21 叙事各段原料齐全（炸板面/三日链/晋级断板均无
   「不可算/缺失」标记）。缺料组的量化对照：炸板面写「不可算」的 17 天 insufficient 率
   **65%**（11/17），炸板面齐全的 88 天 **36%**（32/88）——缺该段确近翻倍推高逃生，
   但两日均在齐全组。
3. **根因一（语料，结构性）**：relay_momentum 主锚之二「今日炸板面较昨日增减」**全库
   107 天从未组装**——zhaban_face_line 只给今日家数+近20日分位+均值，昨日家数与增减量
   缺席（数据现成：分位计算本身已回溯扫 20 天帧）。criteria 的 accelerating「炸板面收敛
   （炸板与反复开板较昨日减少）」/holding「增减不明显」因此永不可验证。
4. **根因二（语料，跨段心算）**：主锚之一「昨日池今日 vs 前日池昨日晋级率」分散在三段
   （段1 晋级与断板 / 段2 三日链 / 段5 轨迹）且同日家数口径不一（10-14：轨迹 36 vs 晋级段
   39；10-13：67 vs 71），模型须自行跨段算术。ladder_health 早有「数据已算好，勿自行心算」
   的预量化行，momentum 题无对应物。
5. **根因三（调度链反序，用户线索实证）**：`schedule.py` 盘后链 `_run_relay_index_step`
   排在 `_run_zhaban_label_step` **之前**，而 relay 叙事「今日炸板面」段消费当日炸板归因
   打标（hotlist_jev_zhaban_labels）。10-14：relay 16:27:47 出数、归因 16:29:36~16:36:53
   才落库 → 叙事恒写「未覆盖（0/24，归因证据缺失）」；10-15：relay 16:18:48、归因
   16:20:33~16:21:45 → 「未覆盖（0/7）」。步骤 docstring「relay 叙事炸板归因缺口补全」
   的目的被顺序抵消。09-21 叙事显示「覆盖 25/25」系 10-11 手动重放时归因已先行补打。
6. **两日分野**：10-15 证据真冲突（晋级率 18.3%→15.4%、二板/三板+ 1.25→0.56、断板大面
   20/33、隔日溢价 -5.3% vs 炸板面 7 家 P0 十七日最低、最高板 9→11、家数 36→36 持平），
   题目无「混合」档 → p(weakening)=0.36 vs p(insufficient)=0.37、conf=0.21 纯两可；
   09-21 晋级链全面向好（22.2%→27.7%、涨停 77→101 创峰值、轨迹晋级 13%→22%→28%），但
   accelerating 的炸板面合取项不可验证（当日 25 家 P62 高于均值，无法排除较昨日恶化），
   叠加高度口径冲突（盘面事实/轨迹「最高 5 板」vs 龙头档案「国芳集团 9板」）→ 逃生。
   另：45 天有 confidence 样本中 33 天 conf<0.5，多方向日 p(insufficient) 居次席
   （0.35-0.59）——该题长期两可，10-15 只是掷硬币掷到逃生面。
7. **归因排序**（AGENTS §1.2 规则六）：① 语料供给=根因一/二/三（已修）；② 题目设计=
   criteria 合取项引用未供给证据 + insufficient 描述「对比证据缺失」与供给现状互相强化
   （**未动，待用户裁决**：合取项降级为可选或增冲突裁决档）；③ 协议解析无关
   （10-15 answers/probabilities 完整落库，conf=0.21 是模型真实不确定）。

### 落地项（3 项，零 jev 调用）

| 项 | 形态 | 测试 |
|---|---|---|
| 炸板面较昨日增减 | `zhaban_face_line` 行尾增「较昨日：炸板 X→Y 家（±N）· 反复开板 X→Y 家（±N）」；昨日帧缺失/降级→「不可算（昨日 THS 炸板池缺失/降级）」，不伪 0 | 新 2 例（对比在场/昨日帧缺失不伪造）+ 存量 13 例 |
| 三日链边际对比 | `three_day_chain_line` 行尾增「边际对比：昨日池今日晋级率 Z%（N→M） vs 前日池昨日 W%（N→M），±pct」；与 relay_flow_line 同源同式（p1z∩p0z/p1z），两行数字必然一致；昨日涨停池被清空→「不可算（昨日涨停池为空）」 | 新 2 例（对比数值/伪 0 红线） |
| 调度链序修正 | `schedule.py` 盘后链 zhabanLabel 步移至 relayIndex 之前（call/steps/results 三处同步）+ 注释说明依赖；test_operations_schedule 链序断言更新并锁死 | 33 passed（含链序断言） |

**真实库 dry-run 核对**（10-15，只读零调用）：炸板面行尾="较昨日：炸板 24→7 家（-17）·
反复开板 9→4 家（-5）"，归因覆盖因标签已在库显示 6/7（生产态经链序修复后当日即可见）；
三日链行尾="边际对比：昨日池今日晋级率 15.4%（39→6） vs 前日池昨日 18.3%（71→13），
-2.9pct"；叙事 3157 字符（原 ~2900，token 增幅 ~5%，预算内）。

**存量与边界**：10-15 现库 RELAY 文档叙事仍含旧缺口（归因未覆盖+两对比锚缺席），
--force 重判可补齐但=真实 jev 调用，须走预登记+预算确认开火路径（AGENTS §1.2-7），
**本轮不开火**；历史文档不可回补。判据侧改造（根因二/题目设计）未动，等用户裁决。

### 第二批（2026-10-16 二级审计补供，relay_phase 次级判据）

**触发**：用户追问「除炸板归因外，接力相位三日链/晋级断板都组装进叙事里了吗」。
**段级审计**：7 段在全库 107/107 天恒在场（今日炸板面 105/107，缺 2 天为 10-10 StepB
上线前旧文档），relay_phase 三主锚（三日晋级链/近10日轨迹/今日炸板面含归因）全部在场。
**二级审计**（判据引用 vs 叙事直给）发现 3 处「绝对值在、昨日对比缺」的半缺口，均在
relay_phase 次级判据（OR 链次要位），故 relay_phase 逃生率仅 16/107（15%），远低于
relay_momentum 的 40%——同类缺陷放在主锚才致命：

| 项 | 形态 | 测试 |
|---|---|---|
| 断板亏钱较昨日 | `relay_flow_line` 增「较昨日断板：中位 A%→B%、大面 X→Y 只」（昨日断板=前日涨停池−昨日涨停池，亏钱=D-2→D-1 收盘；抽出 `_broken_stats` 纯函数，今日值输出字节不变）；无前日交易日/前日 final 缺失/TDX 缺失→对应不可算，昨日 0 只=合法零值照写；前日触板口径日挂（前日触板口径）注记 | 新 3 例（对比数值/无前日/TDX 缺失不可算）+ 存量 |
| 首板占比较昨日 | `ladder_structure_line` 首板占比挂（昨日 X%）（原只有二板/三板+ 比率有昨日值）；昨日梯队缺失→不挂后缀，不伪 0% | 新 2 例（数值/伪 0 红线） |
| 反复开板分位 | `zhaban_face_line` 同一 20 日回溯顺带算反复开板家数分位（原炸板家数有 P 分位、反复开板只有绝对值，判据「处参照高位/低位」无尺子）；历史不足 5 日→不可算 | 新 1 例（双 P0）+ 扩 1 例 |

**验证**：4 文件 67 passed（test_jev_relay_index 18 例，含新 6 例）。**真实库 dry-run**
（只读零调用）：10-15="较昨日断板：中位 -3.59%→-6.24%、大面 18→20 只"（断板亏钱确实
在扩散，divergence 判据现有可比数）、首板占比 67%（昨日 65%）、反复开板 P12、
较昨日炸板 24→7；09-21="较昨日断板：中位 +0.32%→+0.8%、大面 2→2 只"（基本持平）、
反复开板 P69、较昨日炸板 25→25、首板占比 71%（昨日 80%）、边际对比 +3.1pct。
**09-21 逃生谜团解释**：晋级链全面向好（+3.1pct）但 zhaban 较昨日当时不可验证、
且反复开板 P69 偏高（无法排除较昨日恶化），模型无法确认 accelerating 的炸板面合取项
→ 只能逃生。新 ammo 下该日图像完整可判。注：09-21 重建叙事的部分数字与库内存量
略有差异（THS 池回填导致二分池变化），属数据驱动非缺陷。

### 第三批（2026-10-16 开火执行：归因缺口补救重跑，用户选项 2 裁决）

**背景**：调度链反序致 10-14/10-15 生产日 relay 叙事恒未见当日归因；10-12/10-13 归因
从未产出（10-12 手动补跑时 step 未挂链；10-13 relay 16:23 出数早于挂链提交 21:10）。
用户裁决 A+B 全跑（预算 ≈65K tokens）。

**执行**（真实调用，预登记=本文档+当日对话预算确认；环境密钥取自 .env.local）：

| 步 | 命令 | 结果 |
|---|---|---|
| B-1 | `jev_zhaban_label --zhaban-day 2026-10-12` | 新打 25 只全 ok，≈25.2K tokens |
| B-2 | `jev_zhaban_label --zhaban-day 2026-10-13` | 新打 19 只全 ok，≈19.9K tokens |
| A+B | `jev_relay_index --relay-day {10-12,10-13,10-14,10-15} --force` | 4 天全部 ok，≈22.9K tokens |

**合计 ≈68.0K tokens**（45.1K label + 22.9K relay；label 单次实测 ~1024，预估 972 偏乐观）。

**核验**（四天叙事五件套全在场）：归因覆盖 25/25、19/19、23/24、6/7（原均 0/N）；
较昨日炸板/较昨日断板/首板占比昨日/反复开板分位/边际对比全部落位。
**核心问题日 10-15：momentum insufficient_evidence → weakening（conf 0.71）**，
指数 32.1→30.7；四天 momentum 全部给出方向（weakening/accelerating/weakening/weakening，
conf 1.0/0.85/1.0/0.71），无一日逃生。

### 附带发现（未修，待用户裁决）：indices 点位/百分比单位错位

开火前 dry-run 发现 zhaban 叙事「大盘：上证今日 -19.19%」类荒谬值，追根因：

- 上游 `MarketOverviewService`（akshare-sina）产出双字段：`change`=涨跌额（**点位**）、
  `changePct`=涨跌幅（**百分比**）（market_proxy/indices.py:145-146）；
- 采集端 `ServerMarketEvidenceProvider._normalize_indices`（providers.py:2291-2293）
  **只保留 change（点位）**写帧（其 docstring 注明不带 changePct 是为让 rotation 引擎
  `_market_change` 免疫，golden 零漂移）；
- 消费端 jev_zhaban_label.py:150 读 `sh.change` 按 `%` 格式化 → **点位被当成百分比呈现**。

实证：帧值 09-29 sh +9.04 / 09-30 +12.54 / 10-08 -30.97 / 10-12 -19.19 / 10-13 +2.26 /
10-14 -32.80 / 10-15 -60.75——全部符合点位量级（10-08 中证1000 -160.86 点≈-2.5% 与当日
retreat 叙事吻合；10-15 中证1000 -221.76 点≈-3.4% 与当日池内涨跌比 0.82/大面 20 只吻合）。
**污染实证**：10-12 两只 label（海南橡胶、三柏硕）被判 broad_market，其叙事大盘行均为
伪造的「-19.19% 暴跌」（真实约 -0.5%）；10-08 一只 broad_market 同源可疑。全期 broad_market
仅此 3 例，模型对该垃圾值整体鲁棒（10-14/15 更夸张的 -32.80%/-60.75% 下仍 0 例）但非免疫。

影响面：zhaban label 叙事大盘行（broad_market 判据）；另 indices 还被情绪链
（jev_state `_INDEX_KEYS`）与题材轮动引擎（`_market_change`，均点位值跨指数求均值，
口径本身也可疑）消费——**均只读不写，修复无回写风险**。

**建议修法（最小，未实施）**：① providers `_normalize_indices` 增补
`out[alias] = {"change": 点位, "changePct": 百分比}`（rotation 引擎只取 change 键，
新增键免疫；tests/market/test_server_limit_summary.py:125 golden 需同步）；② 消费端
优先读 `changePct`，缺失（历史帧）→ 诚实写「不可考（帧仅有点位变动）」而非伪造暴跌。
修后受影响 label（09-29 起已打标日）可 `--force` 幂等重跑（~1K tokens/只）。
**时效**：若今日 10-16 盘后链尚未跑，修在 16:00 前可保当日 label 干净。

### 第四批（2026-10-16 指数单位错位修复执行，TDD）

**修复形态**（用户裁决「请修复」；判据/题目零改动）：

| 端 | 文件 | 形态 |
|---|---|---|
| 采集 | `snapshot_collector/providers.py` `build_server_indices` | `change`（涨跌额=点位）必落；`changePct`（涨跌幅=百分比）伴生落（上游未给则只落点位）；docstring 补双字段口径。rotation 引擎只取 change 键→新增键免疫 |
| 消费 | `operations/jev_zhaban_label.py` 大盘行 | 优先 `changePct` 按 % 呈现；存量帧纯点位 → **带单位诚实呈现**「上证今日 -60.75 点（涨跌幅缺失，点位口径）」——保留可观测数据不丢弃（fail-visible），对齐情绪链证据行「点」口径；既非帧缺失也不伪装百分比 |

**消费方全扫描结论**：指数点位被当 `%` 格式化的**仅 zhaban 一处**。情绪链
（jev_state.py:360/420）明示「点」口径正确；vote/heat_volume 的 `change` 是个股行字段
（百分比语义，projection `change=pctChange`），非指数；rotation `_market_change` 只取
点位均值做方向信号（跨指数量纲混合系预存设计，非百分比伪造，不在本批范围）。

**验证**：TDD 三例（采集 golden 双字段/消费优先 changePct/存量帧不伪造百分比）+
五测试目录回归 **2044 passed**（market/hotlist/snapshot_collector/theme/operations）；
真实库 dry-run：10-15 帧渲染由伪造「-60.75%」→「-60.75 点（涨跌幅缺失，点位口径）」。

**部署注意（未执行，需用户/运维）**：snapshot_collector 是长驻服务（8001），
**代码改动需重启才生效**——重启前新帧仍只落点位（消费端已诚实降级，无污染）；
重启后新帧双字段齐全，label 大盘行恢复真实百分比。10-16 帧尚未落库、盘后链未跑，
今日生产不受影响。

**遗留选项（待裁决）**：09-29 起已打标 label 中，broad_market 共 3 例（10-08 一只可疑、
10-12 两只已证伪，均见第三批记录）。可按日 `--force` 重跑刷新（整日池 ≈8-32 只/日，
~1K tokens/只）；最小集=10-12（25 只 ≈25K，大概率翻 2 只）+ 10-08（32 只 ≈32K）。
