# jev 方向线原料审计与补齐方案（2026-10-13）

> 背景：v3-gate 止损回退后重梳。用户裁决的工作顺序：**先梳理喂给 jev 的判据有哪些、哪些没有、没有的怎么补，补齐才开跑**——禁止再「一上来开炮、有偏差不反思、陷自我假设」。
> 本审计只梳理「喂什么」，不碰判据文本；判据修订等补齐落地后另行预登记（改门须用户点头）。
> 丰度标杆：relay v3 连板指数题集（10-12 实例，questionSetVersion=v3）——同市场、同日期，叙事七段全事实，jev 答案高置信且相对正确。

## 0. 审计结论（一句话）

**方向线 10-12 版的原料不是「数据不够」，是「只吃了渣」。** `snapshot_stock_rows` 单帧个股行有 **70+ 字段**，方向线实喂 6 个（change/volumeRatio/zlje/zljzb/turnoverRate/rank）；帧层 `limitSummary`（连板梯队/炸板/大面/封板质量）、`marketStats`（全市场涨跌家数）一直在采但零投喂；韭研 final 打标、relay v3 已算好的事实段（摆动锚/晋级链/题材演化）全部未接。当初的「原料单一化」原则做成了「原料贫瘠化」——判据要求模型从 40-100 行名次分位里「自行读出」周期位置和板型，正是铁律 5（原料缺衍生列，模型替算必错）与周期判段四轮挂起的同款死法。

## 1. 判据引用 × 原料矩阵

方向线判据（QUESTIONS_A，git fd3baed5）instructions 逐句拆解，对照 10-12 实喂与库/链实际资产：

| # | 判据引用（原文锚） | 10-12 实喂 | 库/链实际已有 | 差距判定 | 补法（级） |
|---|---|---|---|---|---|
| 1 | multi-day same-direction movement across the series | 槽级分位原始行（10 日全槽 40-100 行） | 同左（唯一真原料） | 缺日终折叠，模型自行心算 | 日终折叠列：每日最后槽 pct+方向符号（B） |
| 2 | a jump AGAINST the prevailing direction vetoes | 无（模型自行读行） | 同左 | 缺跳变标记 | 相邻日反向跳变标记列（B） |
| 3 | volume ratio above 1 but not above 2.5 / >2.5 distribution | volumeRatio | volumeRatio + **volumeRatioMeta**（5 日同时段均量基数） | 基数未透出，模型不知分母 | 透出 meta（A） |
| 4 | net ratio above +20% blow-off / about -10% distribution | zlje/zljzb | + **moneyFlow/capitalFlowConfidence/fundPenetration** | 0.0/0.0 脏数据 6.5% 无标记（R3 前置） | 0.0 当 missing + 透出 confidence（A） |
| 5 | limit-up flag = untradeable（涨停日判读垃圾根因） | 自算涨跌幅≥限幅 flags | **firstZtTime/lastZtTime/fengdan/sealQuality/boardHeight**（一字/秒板/烂板/反复开板全可判） | 板型零投喂——涨停日 hold 错重灾区的根因 | 板型三件套+封板质量（A） |
| 6 | Gate1 生命周期五档（ignition/expansion/crowded/reversal/retreat）**要求 jev 自判** | 5 个分位现算量（day3_net/drawdown10/hot_streak/in_market_streak） | **limitSummary.continuousBoards**（连板梯队逐日）、韭研涨停池（晋级/断板可现算）、driver 线板序 | **最大缺口**：让模型从 5 个数字自判周期=周期判段题从七段叙事退化的同款事故 | 连板高度轨迹+近 N 日晋级/断板历史（A+B） |
| 7 | Gate2 情绪相位带（40/60/75） | band+score+stage+as-of | hotlist_sentiment 全轨迹 | 已够（stage 是规则标签，仅披露） | 维持 |
| 8 | outpaces the market baseline（mm） | mm（池中位 3 日分位变化） | + **marketStats.upCount/downCount**（全市场涨跌家数——「冰点 vs 杀跌需未存数据」的误判，其实在采） | 原始家数未喂，mm 是分位口径不是家数口径 | 补 up/down 原始家数+涨跌比（A） |
| 9 | 5+ consecutive falling percentile days | 无 | 现算 | 缺计数列 | 连续下跌日计数（B） |
| 10 | shallow drawdown / deep 15+ drawdown | drawdown10 | 同左 | 阈值「浅/深」无数值（措辞级） | 维持（补齐后判据层议） |
| 11 | decaying velocity（crowded 判据） | 无 | 现算 | 缺速度列（台账 1/275 触发，低价值） | 速度列（B，低优先） |
| 12 | 判据未引用的市场层上下文 | 仅 band+mm+pool | relay v3 事实段七段（炸板面/晋级链/梯队量化/三日链/题材演化/龙头档案/摆动锚） | 方向线市场层=裸奔 | 拆段复用 relay 事实段（A，见 §4 黑名单拆段纪律） |

## 2. 数据资产三层清单（2026-10-13 库内实证）

### 帧层（snapshot_frames，每 half_hour 帧）
- `marketStats`：totalVolume/totalAmount/**upCount/downCount/flatCount**——全市场涨跌家数（A 级可喂）
- `limitSummary`：**continuousBoards**（连板梯队：一板/二板/三板+家数）、**zhaban**（炸板家数/炸板率）、**drawdown**（大幅回撤池）、**sealQuality**（封板质量）、thsPools（同花顺池交叉）、source/capturedAt
- `indices`：sh/hs300/zz1000/zz500/totalAmount
- `sentiment`、`moneyFlow`（帧级，当前空——C 级待确认）

### 个股层（snapshot_stock_rows，70+ 字段）
**可喂白名单（采集原始事实）**：
- 板型/封板：`firstZtTime` `lastZtTime` `fengdan`（封单）`boardHeight`（板高）`limitUpPool`
- 位置：`highDays` `highPrice` `high` `lowPrice` `amplitude` `speed`（涨速）
- 盘口：`depth10` `ask1Price/ask1Volume` `bid1Price/bid1Volume`（L2 能力边界内五档）
- 资金：`fundPenetration`（zlje/cirMV，原始比值）`moneyFlowEstimated`
- 平台多源热度：`dzhRank` `kplRank` `thsRank` `xqRank` `clsRank` `emRank` `tgbRank` `tdxRank`（各平台原始排名，非引擎综合）
- 题材归类：`sectorLabel` `mainTheme` `themes`（韭研板块归类=采集事实）
- 质量自标：`qualityFlags` `missingFields`（fail-visible 透出）
**黑名单（引擎/jevu 判断产物，禁喂）**：
- `compScore` `compRank`（五维综合排名，providers.py:1025 实证=引擎 golden）
- `leadStatus` `themeRole`（ranktrend engine runtime 透出）
- `avgRankNum`（rank 输入量，慎用——它是排名的原料不是结论，默认黑名单）
- 引擎 tiers/finalSignal/synergy 投票、cycle 阶段标签（本就不在行内，防回归）

### 日级层
- `jiuyan_action`（韭研 final：涨停池+fields 打标+龙序）——涨停池家数/晋级/断板可现算
- `hotlist_sentiment`（情绪分轨迹，Gate2 已用）
- `hotlist_jev_relay_index`（relay v3 叙事七段+答案）——**叙事的事实段可拆段复用，答案段与「周期定位参照」段禁喂**（见 §4）

## 3. 补齐方案三级

### A 级：零新采集，接现成字段/现成组装（优先做，成本≈0）
1. 板型三件套：firstZtTime/lastZtTime/fengdan + limitSummary.sealQuality → 判据「limit-up untradeable」从一句 flag 升级为「一字板/秒板/烂板/反复开板」可判（治涨停日 hold 错重灾区）
2. 连板高度：boardHeight + limitSummary.continuousBoards 逐日 → Gate1 生命周期自判的原料底座
3. 市场涨跌家数：marketStats.upCount/downCount → 「冰点 vs 杀跌」区分的真正原料（当初误判为未存数据）
4. 题材归类：sectorLabel/mainTheme/themes + 韭研 fields → 个股题材地位与连续性
5. 平台多源 rank + volumeRatioMeta + fundPenetration → 量价块的基数与多源交叉
6. relay v3 事实段拆段复用（§4 纪律）→ 市场层从裸奔到七段

### B 级：现算衍生列（零外部依赖，一次实现）
1. 日终折叠序列（每日最后槽 pct + 方向符号）+ 反向跳变标记（判据 #1/#2）
2. 连续下跌日计数（判据 #9）
3. 近 N 日晋级/断板历史：从韭研涨停池+连续 frames 现算（D-1 池→D0 表现，relay v3 同款算法可平移）
4. 摆动锚：涨停家数序列的峰值/谷值距今天数（relay v3 已有实现，平移到个股分位序列）
5. 题材连续性：top3 题材在榜天数（relay v3 同款）
6. 速度列（低优先，台账 1/275 触发）

### C 级：需补采/依赖他线补齐（不阻塞 A/B，登记后做）
1. 炸板归因打标（relay v3 自报「未覆盖 0/25」——需先补 relay 侧归因采集，方向线才能吃）
2. THS 交叉完整覆盖（10-12 晋级按触板口径的降级日）
3. 帧级 moneyFlow（当前空集合语义，待确认采集路径）
4. 龙虎榜/大单（未采，方向线要不要吃需预登记论证）

## 4. 黑名单与 relay 叙事拆段纪律（防循环=handoff「零引擎判断产物」的真正执行）

**禁喂清单**（任何线的判断产物都不喂，包括我们自己）：
- 引擎：tiers/finalSignal/synergy 投票/compScore/compRank/leadStatus/themeRole/cycle 阶段标签
- jevu 情绪线：槽位 stage/temperature/crowding 答案、EOD 答案
- relay v3：answers 全部字段 + 叙事中「【周期定位参照】」段（内含情绪线槽位答案 retreat/climax·late_seal_weakness）+「近5日 EOD 叙事」段（含 EOD 答案）
- driver 打标：driver_type/catalyst_depth/catalyst_freshness/buy_side_logic/stock_phase 结论

**relay v3 叙事可复用段**（纯事实组装，拆段验收后才能喂）：盘面事实、今日炸板面、晋级与断板、梯队结构量化、三日晋级链、题材演化、龙头档案（个股位置/板序/当日板型）、近11日连板轨迹、摆动锚。

## 5. 与 relay v3 丰度对标（同日 10-12）

| relay v3 事实段 | 方向线 10-12 对应 | 差距 |
|---|---|---|
| 盘面事实（涨停/跌停/炸板率/回撤家数+各自分位+池涨跌比） | 仅 band+mm+pool | 缺 6 项 |
| 今日炸板面（分位/反复开板/昨日池今日炸/大面/代表股） | 零 | 全缺 |
| 晋级与断板（分层晋级率/断板中位/隔日溢价） | 零 | 全缺 |
| 梯队结构量化（首板占比/二板三板+比率） | 零 | 全缺 |
| 三日晋级链 | 零 | 全缺 |
| 题材演化（top3/重合/连续性+近5日榜+梯队表） | 零 | 全缺 |
| 龙头档案+摆动锚 | 仅分位序列 | 缺板型/轨迹/锚 |

## 6. 开跑前检查清单（全部打勾才允许预登记开火）

1. [ ] 原料块 ≥8 块：序列（日终折叠）/位置（连板轨迹+晋级断板）/量价（含板型）/市场（涨跌家数+情绪带）/题材（归类+连续性）/摆动锚/炸板面（若 C 级就绪）/质量自标
2. [ ] 判据每条引用可指到具体字段名——**不允许「模型自行从行里读」**（#1/#2/#6 现喂方式的病根）
3. [ ] 黑名单字段零出现（含 relay 叙事拆段后机器验收：grep 禁词+人工抽 1 日）
4. [ ] 0.0/0.0 脏数据清洗落地（zlje/zljzb 双 0 → missing，R3 前置）
5. [ ] pilot 预登记：样本窗口（≥2 种市况）、数值化门判据、人工抽验 ≥10、成本估算（按新原料块重估 input tokens）、回退方式（AMMO_VERSION 戳+git）
6. [ ] 裁决数据协议：规则线（synergy_direction 查表）vs jev 线同股同场收益对比表为第一交付物——先于任何判据迭代

## 7. 与三条在途线的关系

- **relay v3**：本审计的事实段复用来源；其炸板归因缺口（C 级）补好后方向线才能吃全
- **规则线**：对比基准（synergy_direction），黑名单防喂
- **driver 打标线**：其板型/封板时间等**原始字段**可喂，**打标结论**禁喂（§4）
