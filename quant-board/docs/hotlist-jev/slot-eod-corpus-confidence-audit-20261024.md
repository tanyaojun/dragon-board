# 帧级情绪 × 日级 EOD 情绪：置信度透出 + 口径修正 + 语料精简 全面诊断（2026-10-24）

> 触发：用户 2026-10-24 要求参照《题材龙头页：四字段置信度 + 续板概率口径修正 + 语料精简与
> 匹配优化》（47584ad4，AMMO 2026-10-24a）的方法论，对**帧级情绪判定**（slot 4 题）与
> **日级 EOD 情绪判定**（day 4 题）的语料与题目级做全面诊断和优化。
>
> 方法与题材龙头 10-22 审计完全同法：**零模型调用**，只读 `dragon_board_quant`
> （脚本与产物：`data/backups/slot_eod_corpus_audit_20261024.py` /
> `slot-eod-corpus-audit-20261024.txt`，依 .gitignore 不入库）。
> 本文只记录归因与候选方案；**判据/语料变更须另立预注册 + 预算确认**（AGENTS §1.2-7）。
>
> 基线：本链 2026-10-22 已完成两轮口径修复（帧级 `jev-slot-corpus-caliber-fix-preregistration.md`、
> 日级 `jev-eod-corpus-caliber-audit-preregistration.md` → 题面 v2.6 + corpusCaliberVersion
> eod-2026-10-22），本轮是在该基线上的**第二轮**（题材龙头方法论回灌）。

## 0. 结论先行

两条链**题目设计层健康**（v2.6 判据与语料供给对齐已在 10-22 完成，本轮未发现新的
「判据引用语料外证据」；逃生率 0/20，锚告警无触发），剩余缺口集中在**接线层与原料层**：

| # | 发现 | 层级（§1.2-6 归因） | 优先级 | 零 token 可修？ |
|---|---|---|---|---|
| F1 | `sentiment-overview` 读口不透出 day_pattern / 日级 confidence / 日级 probabilities（市场热度计消费该读口，日级四题只有 dayStage/dayCrowding 两组） | ③协议与解析（出参接线） | P1 | ✅ 纯读出参 |
| F2 | 拥挤度黄柱数值（拥挤三层概率合计）在前端 `hotlistJevApi.ts::jevCrowdingProbability` 计算——已登记的单一事实源债（questionset-review §〇.3/§七） | ③协议与解析（口径单一事实源） | P1 | ✅ 出参+前端改消费 |
| F3 | 叙事 `[:4000]/[:6000]` **静默硬截断**：截断发生时无声丢尾，第一个被丢的就是【数据质量】段（fail-visible 违规）。实测 15:00 槽叙事 3749/4000，余量仅 251 字 ≈ 1 个压缩行——帧配置从 10 帧变 12 帧、或行文略增即触发 | ③协议与解析（防线缺失） | P1 | ✅ 截断标记化 |
| F4 | 槽级语料跨调用重复面 62.7%（参照段 11.1% + 已走帧段 51.6%）；单日全链 input ≈42K tok，已走帧段随日内线性增长（+267 字/帧）。题材龙头式精简的最大标的，但属**原料代际变更** | ①原料供给（结构冗余） | P2 | ❌ 需预登记+回放对照 |
| F5 | EOD 历史重放日（10-17~21 五日）真连板峰值=close_only（盘中峰值不可恢复，as-of 结构性）；生产日（10-22/23）盘中梯队已全捕获（13:30 峰值 6 板实测在案） | ①原料供给（结构性，已披露） | P2 登记 | 不修 |
| F6 | 代际覆盖：slot 691 篇中 v2.6 仅 20（v2.5 306 / legacy 365）；EOD 74 篇中 v2.6 仅 7（v2.5 26 / legacy 41）。重跑预算需用户裁决 | 运维 | P2 | ❌ 真实调用 |
| F7 | 置信度水位：slot 温度题 conf 0.26–0.69（四题最低）、frame_stage 0.39–0.84、crowding 0.42–0.93（最高）；day_temperature 0.24–0.56、day_pattern 0.28–0.69——与 confidence landscape 结论一致（证据充足度单调、conf≥90 不可达），非缺陷 | 观察 | P3 登记 | — |
| F8 | 「热度字段未采集」自 10-21 起每篇必现（上游 232/232 行 heat=0），已成为**常量降级噪音**（每篇叙事质量段固定 +20 字 × 全日 10 槽） | ①原料供给（上游缺口） | P3 | 打包进 F4 预登记 |

**方法论四要素在本链的对应物**：①四字段置信度→F1（日级 confidence 透出补全）；
②续板概率口径修正→F2（拥挤合计提后端）+F3（截断 fail-visible）；③语料精简→F4/F8；
④匹配收紧→本链无新闻匹配层，对应物=锚供给匹配（10-22 修复后 0/20 逃生、告警零触发，
无需新增）；「证据门强制档位冒充置信」问题两链不存在（无 gate override 实现）。

## 1. 帧级（slot）现状量化（v2.6 现行代，10-22/23 两日 20 篇）

| 维度 | 实测 |
|---|---|
| 叙事字数 | min 1226 / p50 2674 / max 3772（上限 4000，**未触**） |
| 真实 usage | input p50 4343 tok（max 5414）、output 恒 ≈211 tok |
| 结构分解 | 头行 42 + 近20日参照 301（恒定）+ 当前帧证据 ≈955 + 已走帧段 23→2435（随日内线性 +267/帧）+ 质量段 25–40 |
| 跨调用重复面 | **62.7%**（参照段 11.1% + 已走帧段 51.6%）——单日 10 槽合计 input 42,218 tok（10-22）/ 42,013 tok（10-23），其中约 6 成是同一日内重复投喂的参照段与已走帧段 |
| 置信度 | frame_stage 0.39–0.84、sequence_stage ≈同、temperature 0.26–0.69（最低）、crowding 0.42–0.93（最高）；四题 100% 带 probabilities（5/10/6 档） |
| 逃生率 | crowding=insufficient_evidence **0/20**（10-22 锚修复后无一逃生） |
| 判层分布 | frame_stage retreat×13/ice×3/ferment×2/climax×2；crowding late_seal_weakness×14——10 月下旬市况自洽 |
| 降级位 | 「热度字段未采集」20/20 必现（F8）；「真连板未采集」仅 2/20（ths_live 现查链已稳定） |
| 温度分位 | answers.temperature.percentile 注入 20/20（近20日 EOD 温度分位，口径正常） |
| 截断风险 | 15:00 槽 3749/4000（余量 251 字 ≈ 1 个压缩行）；`build_slot_jev_state` 的 `[:4000]` 是**静默**硬切，先丢【数据质量】段（F3） |

## 2. 日级（EOD）现状量化（v2.6 现行代，10-17~23 七篇）

| 维度 | 实测 |
|---|---|
| 叙事字数 | p50 3060（上限 6000，未触）；逐帧段占 **81.2%**（头+参照+覆盖+累计+质量仅 ≈600 字） |
| 真实 usage | input p50 4669 tok、output ≈250 tok |
| 帧覆盖 | hasCloseFrame 7/7；trueBoardCoverage：close_only×5（10-17~21 历史重放）、partial×2（10-22/23，盘中梯队全在） |
| 置信度 | day_stage 0.26–0.75、day_pattern 0.28–0.69、day_temperature 0.24–0.56（最低）、day_crowding 0.57–1.0（p50=1，最高）；100% 带 probabilities |
| 判层分布 | day_crowding late_seal_weakness×5/crowd_clearing×1/breadth_climax×1（逃生 0）；day_pattern wide_swing×2/rally_fade×2/low_recover×2/steady_weak×1 |
| 降级位（帧级累计） | 热度字段 70 帧、真连板 47 帧（全部来自 close_only 历史重放日）、三指数缺席 35 帧（10-20 前历史帧无 indexExtra） |
| 出参缺口 | `sentiment-overview` 只有 dayTemperature/dayStage(+P)/dayCrowding(+Ps)，**无 day_pattern、无任何 confidence**（F1）；day_pattern 前端经 JevNarrativePanel 走 /series+/range 全文档消费，正常 |

## 3. 归因（AGENTS §1.2-6 顺序）

1. **①原料/语料供给**：主要余量在 F4（跨调用重复面 62.7%，设计使然——Q1 当前帧题与
   Q2 当日序列题共用一次调用，已走帧段是 sequence_stage 的合法弹药，非错喂）与 F8（上游
   热度恒缺）。**无错供**：压缩行全部字段可追溯到某题判据或参照系（指数/涨停/连板/炸板率/
   封板率/涨跌分布/量能/新进淘汰均入判据；TRIN/主力净额/生命周期/强资风险为判据外的
   语境证据——这是「纯原始证据零规则输出」设计的有意取舍，是否瘦身属 F4 用户裁决）。
2. **②题目/判据设计**：v2.6 已删净日级语料外引用；本轮逐条复核 slot/day 八题判据的每个
   证据名词（涨停数、连板梯队、炸板率、封板率、跌停/大跌、新进资金、参照分位）在叙事中
   均有供给，**未发现新的判据-语料缺口**。day_crowding「高度刷新」判据在历史重放日
   （close_only）半盲属结构性（F5），已由覆盖度标注披露。
3. **③协议与解析层**：**本轮主发现全在这层**——F1（日级出参缺 confidence/day_pattern）、
   F2（拥挤合计口径在前端）、F3（静默截断无标记）。三者共同特征：模型侧产出正常且已落库，
   消费侧丢真值或口径漂移，与题材龙头「续板概率=1−P(缺证)」同族（口径层失真，非模型问题）。

## 4. 优化菜单（按执行门槛分级）

### A 组：零 token、纯读口/防线代码，一轮提交可完成（建议先行）

- **A1（=F1）**：`GET /api/hotlist-jev/sentiment-overview` 出参补
  `dayPattern`/`dayPatternProbability`/`dayTemperature`/各题 `confidence`（additive，
  缺失 null 不伪造）；HotlistEmotionPanel 市场热度计补置信徽章（题材龙头 confChip 同款
  三级色）——是否挂前端 chip 由用户裁决，出参补全无争议。
- **A2（=F2）**：拥挤三层概率合计提后端——`sentiment-overview`/`series` 出参加
  `crowdingProbability`（三层合计，与前端 JEV_CROWDING_LAYERS 逐字同口径），前端
  `jevCrowdingProbability` 改为优先消费后端值（旧文档无该字段回退本地计算，不破历史渲染）。
  单一事实源落库侧不动（原始 probabilities 仍是唯一事实源，合计只是展示投影）。
- **A3（=F3）**：`build_slot_jev_state`/`build_day_jev_state` 截断防线——发生截断时
  ①落库 `narrativeTruncated: true`（additive 字段）②叙事尾部显式追加「（语料超限截断，
  末段【数据质量】已丢失）」注记，让截断对模型与人同时对可见。零题面改动、零行为漂移
  （未触上限时输出逐字不变），补「revert 即红」单测。

### B 组：需预登记 + 用户裁决（原料代际，题面 v2.6 冻结不动）

- **B1（=F4）语料精简（AMMO 代际戳 slot-corpus-2026-10-xx，回放对照验收）**，候选三刀：
  1. **恒真降级位降噪（=F8）**：「热度字段未采集（焦点个股按榜单名次）」自 10-21 起恒真，
     改为仅首帧/日级披露一次，槽级压缩行与质量段不再逐篇重复。收益小（≈20 字/篇），
     但属确定性冗余，题材龙头「删确定性重复头行」同款。
  2. **已走帧压缩行瘦身**：候选删 TRIN/主力净额/生命周期/强资风险四组（判据外语境证据，
     合计约 60–70 字/行）；预期单叙事 -15~25%、日链 input -20% 左右。**风险**：这些字段
     是「纯原始证据」设计的一部分，删了可能改变 stage/temperature 落点分布——必须
     replay 对照（真实 jev，预算报备 ≈42K tok/日 × 对照日数）按四题档位一致率验收。
  3. **已走帧滑窗**：早帧压缩行为「汇总行」（峰值涨停/峰值连板/炸板率区间/量能区间），
     只保留最近 K 帧全行。收益最大（-30~50%）但行为漂移风险也最大，若做须与 2 分开
     独立对照，一轮一变量。
  - 验收基准（预登记草案）：对照日 replay 四题档位一致率 ≥90% 且 temperature 分数
    |Δ|≤5 分为过；否则回退。
- **B2（=F6）存量重跑**：9 月 v2.5 slot 306 篇 + EOD 26 篇升 v2.6 口径重跑，预算
  ≈306×4.3K + 26×4.7K ≈ **143 万 input tok**（output 计费另计，以实际 usage 报备）。
  前端混版守卫已在（CRITERIA_ERA_START=2026-09-01 过滤），不重跑也不阻塞展示；
  跨代研究统计必须按版本分段（既有纪律）。**待用户裁决**。

### C 组：登记不动

- **F5**：EOD 历史重放日真连板峰值 close_only——as-of 结构性（历史日盘中梯队不可重建，
  现查即 now-state 污染），生产日已全捕获，覆盖度标注已披露。跨代统计时注意即可。
- **F7**：置信度水位——按 confidence landscape 结论「conf≥90 不可达不应追求」，
  日级/温度题低置信是证据充足度的如实反映；F1 透出后由用户肉眼校准，不设置信门槛。

## 5. 预算与执行顺序建议

A1+A2+A3 一轮提交（纯代码+测试，零 token，≈半天）；B1 预登记后先跑 1 个对照日 replay
（真实 jev ≈42K tok input，报备后执行），过门再议 2/3 是否加刀；B2 与 B1 择机分开，
避免「语料+题面+存量」三变量混在一批。

## 6. 审计产物

- 脚本：`data/backups/slot_eod_corpus_audit_20261024.py`（只读，零 jev 调用）
- 输出：`data/backups/slot-eod-corpus-audit-20261024.txt`（两链代际/叙事/置信/降级全量读数）

## 7. 执行记录（2026-10-24，用户裁决「A组开工，B组走B1」+「出参+概览chips」）

- **A1/F1 已落地**：`sentiment-overview` 出参补 `dayPattern`/`dayPatternProbability`/四题
  `*Confidence`；前端 `HotlistSentimentOverviewEod` 类型扩展；市场热度计概览 chips 补
  「路径·形态」与「置信 Pxx%」（缺字段不渲染）。
- **A2/F2 已落地**：拥挤三层合计提后端——`hotlist_jev_routes` 新增
  `_crowding_probability_sum`（CROWDING_PROBABILITY_LAYERS 单一权威口径），`/series`、
  `/range` 每文档附 `crowdingProbability`、`/sentiment-overview` 附 `dayCrowdingProbability`；
  前端 `jevCrowdingProbability` 改后端值优先、缺字段回退本地同式合计。
- **A3/F3 已落地**：`jev_state` 新增 `NARRATIVE_TRUNCATION_MARK`/`_apply_cap`/
  `narrative_is_truncated`——截断显式注记（未超限输出逐字节不变）；compute/pilot 六处
  落库 doc 加 `narrativeTruncated`（additive）。
- **B1/F4/F8 已预登记**：`jev-slot-corpus-slim-preregistration-20261024.md`（三刀分轮 +
  对照协议 + 预算报备），**开火待用户点头**。
- 验证：pytest test_jev_state 50 / test_jev_sentiment_compute 29 / test_hotlist_jev_api 34
  全绿；vitest hotlistJevApi+HotlistEmotionPanel+JevNarrativePanel 64 全绿；vue-tsc 干净。
