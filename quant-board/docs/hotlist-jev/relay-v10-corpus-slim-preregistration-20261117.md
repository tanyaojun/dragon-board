# relay 语料 v10 精简预注册（2026-11-17，用户裁决「全部修复」）

> 关联：`relay-v9-questionset-preregistration-20261112.md`（v9 删题）、
> `jev-relay-v7-preregistration.md`（v7 全语料盘点）。
> 裁决：2026-11-17 用户审阅 2026-11-17 当日语料（约 5100 字符）后批准 A/B/C/D/E 全部项，
> 含**细化推翻 v9 §七「删题不删叙事」**——被删题（theme_pulse/leader_strength）专属的
> 孤儿证据段随 v10 撤出 relay 语料（题材龙头链自有供给，不受影响）。
> **追加裁决（同日）：删除「周期强度」题（cycle_intensity）**——周期强度已由 market_cycle
> 状态机离散态+事件承载，补维度无增益；题集 8→7，落库删 cycleIntensity 字段（历史档不回改），
> 前端删周期强度列/KPI 卡（16→15 列）；【市场情绪周期】叙事段保留（turn_quality/risk_ahead 仍消费）。
> 红线 §1.2#7：本文档批准 ≠ 批准开火；测试全 mock，历史日不回填。

## 一、变更清单

### A 类：§1.2-8 开发注释/口径注清理（卫生修复）

| # | 原文 | 处置 |
|---|---|---|
| A1 | `今日 relayIndex 待落库（形态随收盘评分定档）` | 删（首判流程注，对 jev 零信息量）；保留结构预检事实 |
| A2 | `·龙一=板块节点空间龙一档`（题材梯队表图例，含黑名单词「节点」） | 删；定义只留本文档与代码注释。回退注记精简为缺位事实「·龙一档缺失」/「·龙一档缺该板块」 |
| A3 | 同桶基线`（窗口 …）`统计窗口注 | 随 B1 整段删除 |
| A4 | 反包行`· 候选池含停牌复牌未分辨`静态口径注 | 移结构化：`build_rewrap_pool` 输出增 `poolCaveat` 字段，随池快照落库（读口可审计），叙事不再携带 |
| A5 | 板序`（●=涨停，末位今日）`解码图例 | relay 侧经 `legend=False` 参数去除；图例一次性进 relay_index instructions。共享函数缺省行为不变（炸板链零漂移） |
| A6 | 弱转强基线`（一日游为主，次日回踩常见）`解读句 | 随 D2 删除 |

### B 类：v9 删题后的孤儿证据（8 题判据零引用）

| # | 段 | 处置 |
|---|---|---|
| B1 | 同桶隔日连板基线（v7 D5 为 theme_pulse 供给） | relay 叙事整段删；`relayStructure.mainline.sustain` 结构化桶键**保留**（前端/审计消费）；题材龙头链同桶供给不动 |
| B2 | 题材证据块（催化原文/未映射/无匹配×6） | 改为**仅渲染事件命中**：消费 `build_theme_evidence_block` 结构化 `events`/`calendar` 命中（单源匹配不二次实现），无命中整块缺席（§1.2-8）；语料未采集保留例外事实行「题材事件：语料未采集」 |
| B3 | 题材梯队表`新鲜N/延续N/N标·驱动主类 X` + 龙二/龙三 | relay 侧只留龙一+家数+昨日家数；打标聚合与 label_docs 查询删除（题材链自有供给） |

### C 类：逐字重复去重

| # | 重复 | 处置 |
|---|---|---|
| C1 | 龙头档案头行 ≈ 龙头结构·总龙头行 | 标签（label/freshness，struct 已有）并入总龙头行；档案头行删，个股位置/板序/板型保留（v9 保留裁决不变） |
| C2 | 主线板块行（被板块接力链主线行+升位关系全覆盖） | 叙事行删；`relayStructure.mainline` 保留；不可算披露走 struct.degraded + 升位关系行 |
| C3 | 炸板归因打标个股开板次数（与反复开板代表重复） | 归因分布只留高位分歧股名，去 `(N次)`；次数单源=反复开板代表 |
| C4 | 盘面事实`（交叉 …）`THS×韭研校验分布（8 题零消费） | `market_facts_line` 增 `ths_cross=True` 缺省参数，relay 传 False；**其余调用方输出字节级不变**（遵守「market_facts_line 共用坐标系一行不改」红线的缺省兼容路径）。梯队分布本体保留（含未标高度披露，梯队量化段不重复承载） |

### D 类：低价值细节

| # | 项 | 处置 |
|---|---|---|
| D1 | 摆动锚（峰/谷可从轨迹表读出，判据零引用） | relay 轨迹行不再拼 `swing_summary_line`；函数本体保留（market_facts 同算法参照） |
| D2 | 弱转强参照静态历史基线 + 今日反包率 vs 基线对比 | 删（反包率+20日分位已在反包修复行；wzs 分类器是确定性代码不读叙事）；保留昨日 relayIndex 分区 + 结构预检/确认行（relay_momentum.reversing 证据） |
| D3 | 反包代表 3 只、冲刺未封代表 3 只 | 删（判据消费率/计数不消费股名）；明细仍在池快照结构化字段 |
| D4 | 个股位置/板序/当日板型 | **不动**（v9 保留裁决，relay_index 观察位背景消费） |

### E 类：判据-证据错位修复

- `relay_phase.collapse`「高位批量断板（轨迹断板≥2只）」→ 显式点名
  「【三日晋级链】高位股轨迹断板≥2只」。今日【高位股多日轨迹】段只覆盖真连板≥4，
  区间高位股断板轨迹实际在三日晋级链段——旧措辞按段名找证据会落空。
- relay_index instructions 增板序图例句（A5 配套）。

### F 类：删 cycle_intensity 题（同日追加裁决）

- 题集删 `cycle_intensity`（8→7）；其余 7 题判据/枚举零变动。
- 落库删 `cycleIntensity` 字段（同 v9 删 leaderStrength/themePulse 口径）；历史档字段保留不回改。
- 前端 relay 页：删周期强度列（表头 16→15，colspan 同步）、KPI 卡、MC_INTENSITY_CN 词表；
  旧代档无融合题值仍显 —（代际区分非缺判）。
- 【市场情绪周期】叙事段保留：turn_quality/risk_ahead 主锚不变；状态机仍是周期唯一权威。

## 二、代际与存储

- `QUESTION_SET_VERSION_RELAY` v9 → **v10**（criteria 一处 + instructions 一处变更 + 删 cycle_intensity）。
- 题数 8→7（删 cycle_intensity）；其余档位枚举不变；SCORE_ANCHORS_10 不变；大盘 wzs/分带/market_cycle
  reference 判据与坐标系零改动（relayIndex 仍算仍落库）。
- 历史 v9 档不回填、不回改；新旧代对比须注记代际。
- `anchorGapsDerived` 标记表同步：删「主线板块：不可算」针（行已删，披露走 struct）；
  「题材证据」标记改作用域「题材事件」（仅语料未采集时针）。
- 结构化字段只增不删：`poolCaveat`（rewrap 池）；`relayStructure` 全字段保留。

## 三、前端同步核对（§1.2-5）

- relay 页（`backend/relay_page/index.html`）消费 `relayStructure`（主线/龙一/升位关系
  渲染走 struct，不走叙事行）与 narrative 原文展示（懒拉日志卡）——删叙事行不破坏渲染。
- 周期强度列/KPI 卡/词表随删题同步移除（16→15 列，colspan 同步）；缺位徽标泛型渲染
  anchorGaps/anchorGapsDerived 名单，无硬编码段名依赖。
- 题材证据窄徽章（事件格）消费题材链自有 corpusState，与 relay 叙事无关。
- 结论：前端仅删周期强度列/卡（F 类），其余零代码改动；展示随叙事原文自然更新。

## 四、验收门

1. 2026-11-17 型语料重建：A/B/C/D 目标串缺席；事件命中行/总龙头标签行/结构预检行在场。
2. 全叙事过 `test_narrative_hygiene.FORBIDDEN` 黑名单（新增 relay 全行覆盖测试，
   补「节点」漏网教训）。
3. 共享函数缺省输出字节级不变：market_facts_line（其他链）/limitup_sequence_line（炸板链）。
4. 题集 7 题（删 cycle_intensity）、v10 戳、collapse 判据点名三日链；version stamps 测试更新；
   relay 页 15 列/colspan/词表零残留断言。
5. 测试零真 jev（全 mock/fixture）；不回填历史日。
6. 预期收益：~1000 字符/日（约 20%），删项均为判据零消费或重复供给。
7. **实测（2026-11-17 生产库只读重建，不调 jev 不落库）**：原语料 ~5100 字符 →
   **3684 字符（−28%）**；删项零残留、FORBIDDEN 黑名单零命中；当日题材事件无命中
   整块缺席（原「无匹配」×6 行撤出）；弱转强/反包/晋级/梯队/锚/周期各主锚事实在场。

## 五、风险与回退

- 判据漂移：E 类仅消歧措辞，阈值零变动；relay_index 观察位不受影响。
- 误删证据：反包率/分位、昨日分区、结构预检、归因分布计数、龙一家数全部保留。
- 回退靠 git（§1.2#2），不做库内备份；历史档 questionSetVersion 天然分代。

## 六、独立评审处置（2026-11-17，fresh-context reviewer，只读）

结论「需修复后提交」，发现全部修复：

| 级 | 发现 | 处置 |
|---|---|---|
| P1 | poolCaveat 未透出 HTTP 读口（A4 披露只完成一半） | `api/hotlist_jev_limitup_routes.py` rewrap 投影增 `poolCaveat`；读口合同测试补断言 |
| P2 | 重跑分支「重跑重评 X，**节点**以收盘定档 Y 为准」含 FORBIDDEN 词（存量文本，本轮全叙事覆盖声明未盖该分支） | 措辞去「节点」；同步 jev-weak-to-strong-day-study.md §语料行分歧注记；分歧注记测试锁新措辞 + 过黑名单 |
| nit1 | 模块 docstring 8 题→7 题 | 已改 |
| nit2 | version stamps 注释「题数 8 不变」 | 已改 8→7 |
| nit3 | theme_ladder_lines/sector_relay_lines/leader_profile_lines 陈旧 docstring | 已同步 v10 口径 |
| nit4 | _FACTS_CACHE 注解/注释滞后于 4 元组键 | 已改 tuple[str,str,str,bool] |
| nit5 | 龙一档回退注记无测试锁定 | 新增 test_v10_ladder_anchor_fallback_notes（表头/逐板块两路） |

评审同时核对通过：A–F 全项落地、fail-visible 各路径、共享函数缺省字节级零漂移、
单一事实源、前端 15 列同步、代际纪律、测试零真 jev。