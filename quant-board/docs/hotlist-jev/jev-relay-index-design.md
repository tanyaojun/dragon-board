# 连板情绪指数设计草案（relay sentiment index）

> 2026-10-10 起草。目标：用 jev 叙事判定方法构建「涨停连板接力生态」的日级综合情绪指数，
> 与既有热榜温度分、情绪周期段位并列，补齐接力生态维度的空白。
> 状态：**已落地生产**（2026-10-11：v2 判据 60 日回填 → 炸板归因注入 v3 判据，用户裁决落 v3；
> 本文为设计依据存档，叙述段数/题目数以 zhaban-preregistration §九与代码为准——叙事已从六段扩为七段，
> 晋级口径已按方案A 二分修正为「触板−THS炸板池」，见 jev_relay_index._sealed_codes）。

## 1. 定位：与既有三个指数的关系（不重复建设）

| 既有资产 | 口径 | 维度 | 来源 |
|---|---|---|---|
| `day_temperature`（0-10） | 大盘热榜热度 | 全市场情绪温度 | hotlist_jev_sentiment EOD |
| `day_stage`（五档）/`cycle_stage`（试点） | 情绪周期段位 | 周期相位 | 同上 / hotlist_jev_cycle_stage_pilot |
| `phaseBand`（个股）+ 相位分线 | 个股自身趋势位置 | 个股维度 | hotlist_jev_driver_labels |

**空白**：以上都不回答「接力生态今天健不健康」——钱愿不愿意接力、接力赚不赚钱、
梯队结构是否完整、龙头地位稳不稳、题材是延续还是散乱。个股 phaseBand 聚合不出
这个答案（每只股票自己位置高 ≠ 接力生态好，高位分歧日个股分反而都高）。

**互补关系**：连板指数应与温度分同向但不雷同（预期相关 0.5-0.8）；
背离本身是信号（温度高+接力亏钱 = 高位分歧；温度低+晋级顺畅 = 修复启动）。

## 2. 原料审计（2026-10-10 实测，§1.2.6 原料先行）

### 2.1 连板梯队分布——根因已定性：10-02 风控优化砍掉了采集层连板层五池

**根因（2026-10-10 排查定性，非上游故障）**：`b5d4ac36`（2026-10-02）THS 涨停池风控
优化时，以「连板层五池零消费、仅面板透传展示用」为由把 one/two/three/four/high
从采集层砍掉（`providers.py _COLLECTOR_POOL_KEYS` 只剩 failed/rushing/drawdown）。
当时背景：9 月 limitSummary 间歇缺失根因 = THS 限流返空（HTTP 200 + 空 info）。
10-08 为节后首个交易日，自此快照帧连板层恒空。「零消费」判断在 jev 叙事/连板
指数成为新消费者后失效。

**修复（双源，Phase 0 前置工程）**：
- **主源**：jiuyan final `fields[].stocks[].day` 聚合梯队（103 天池史全量，10-09
  实测 82 只全有连板数）；`market_metrics.ladder` 改为 jiuyan 主源 + THS 交叉验证
- **THS 连板层请回采集层但仅 EOD 帧**（15:00 槽拉一次连板层五池，日增 5 发；
  服务层 250ms 节流 + 返空指数退避负缓存已在 b5d4ac36 就位，风控成本可控）
- 面板透传全 8 池行为不变；任一源缺失如实标注（fail-visible）

### 2.2 晋级率/断板亏钱——数据齐备但未组装（jiuyan 103 天池史支撑多日链）

- D-1 池 × D 日池：`今日 day≥2 数 / 昨日 day≥1 数` = 晋级率；分层晋级率（昨日 N 板今日
  N+1 板）；新面孔（今日 day=1）占比
- **三日晋级链矩阵（D-2→D-1→D0）**：前日连板股今日地位变化——继续晋级/停滞/
  断板/出清，jiuyan 103 天池史可回溯任意窗口
- 断板亏钱：昨日涨停股今日表现（TDX 日线基建已有：`_tdx_daily_client`/`_daily_bars`
  缓存，个股打标链在用）→ 中位涨跌、<-5% 家数、跌停数、隔日溢价均值
- 注意：snapshot_stock_rows 15:00 帧只有 price/zlje **没有 pct**，断板效应走 TDX 日线
  或隔日价差，不走帧字段

### 2.3 题材梯队（龙一/二/三）——纯数据可算

jiuyan final 每题材 stocks 按 `day desc, time asc`（高度优先、封板时间次之）排序即得
龙一/二/三；题材延续天数 = 同名题材在 D-1/D-2 是否在池及高度变化。

### 2.4 个股四题标签的二次利用（零边际成本）

9-01 起 23 天个股 driver/depth/freshness/buySide 已落库。按题材聚合得到：
板内新鲜度结构（fresh_catalyst 占比）、驱动结构（product_event 主导 vs concept_stretch
主导）、买方逻辑结构（sector_follow 占比高 = 板块跟风盘主导）。
**这批原料让「题材脉络」题从数据事实而非模型臆测出发。**

### 2.5 既有热榜 JEV 叙事资产（喂入连板指数叙事，2026-10-10 盘点）

- `hotlist_jev_sentiment`：EOD 64 天（7-01 起）+ slot 64 天——day_stage/day_pattern/
  温度/拥挤度结论序列可直接作为连板指数的周期坐标系输入
- 今日 slot 叙事（当日 10 槽 frame_stage/sequence_stage/temperature/crowding）
  是 EOD 接力判定的**同日证据**（日内接力节奏）
- 防锚定纪律（先例：market_facts_line Q5 防锚定污染）：叙事结论以「参照段」形式
  给出并显式标注「周期定位参照，非今日证据」；打分锚仍以客观事实+分位为主

## 3. 叙事结构（弹药六段，一段一职责）

1. **连板生态总账（当日）**：涨停/跌停/炸板家数与率、梯队分布（jiuyan 主源）、
   最高板、晋级率、断板亏钱分布、隔日溢价——每项带近 20 日分位
2. **接力生态记忆（跨日，防止退化为日内指数）**：三日晋级链矩阵（D-2→D-1→D0
   逐股地位变化）、题材主线演化表（主线题材第 N 天、昨日龙一今日地位、板内
   高度是否递进）、龙头上升轨迹（从首板到当前高度用了几天、断过几板）
3. **题材梯队表**（top5 题材）：龙一/二/三（名称+高度+封板时间）、板内新鲜度/
   驱动聚合（来自四题标签）、题材延续天数、较昨日扩容/缩容
4. **龙头档案**：最高板个股的身位（20 日位置/量能）、封板质量（首触/炸板/末封）、
   板块带动数、热榜排名、四题标签
5. **近 10 日连板轨迹**（摆动锚）：家数、最高板、晋级率、断板亏钱的逐日序列 +
   峰谷位置（复用 trajectory_line/swing_summary_line 思路，扩列晋级率）
6. **热榜叙事语境段**：今日 slot 叙事结论序列（10 槽 stage/temperature/crowding
   轨迹）+ 近 5 日 EOD 叙事结论（day_stage/温度/拥挤，一日一行）——段首标注
   「周期定位参照，非今日证据」（防锚定）；另附近 20 日连板生态极值日摘要作
   校准锚，锚定法与 day_temperature 一致（§1.2.6）

## 4. 题目集（初稿 6 题一 call，EOD 一次）

| 题 | 类型 | 判据要点 |
|---|---|---|
| `relay_index` | score 0-10 | 主线分：**以近 10-20 日接力生态轨迹为坐标系**（禁仅凭当日家数），综合晋级率位置、断板亏钱、梯队健康、龙头地位、题材脉络 |
| `relay_phase` | choice | `launch`（首板堆积/新题材启动）/`relay_heat`（晋级顺畅金字塔健康）/`divergence`（高位分歧晋级骤降）/`collapse`（龙头断板亏钱主导）/`bottoming`（高度压平接力冰点）|
| `relay_momentum` | choice | **跨日边际方向**：`accelerating` 较昨日生态强化 /`holding` 惯性延续 /`weakening` 边际退潮 /`reversing` 状态逆转——锚定接力生态记忆段的三日链与昨日池今日表现 |
| `ladder_health` | choice | `pyramid` 金字塔完整 / `fracture` 中位断层 / `inverted` 高位倒挂孤板 / `sparse` 全面稀疏 |
| `leader_strength` | score 0-10 | 龙头高度稀缺性、封板质量、辨识度、板块带动 |
| `money_effect` | choice | `strong` 晋级+溢价双正 / `neutral` / `losing` 断板大面+溢价为负 |
| `theme_pulse` | choice | `mainline_continue` 主线延续 / `rotation` 轮动换线 / `scattered` 一日游散乱 |

与既有叙事结论的联动写进判据：relay_phase 需对照热榜 day_stage——热榜 climax 且
晋级顺畅 → relay_heat；热榜 ferment/climax 但断板亏钱扩散 → divergence（分化的
判别依据是接力证据，不是热榜结论本身）。上线首日起 relay_momentum 以客观三日链
为锚；次日起同时提供昨日 relay_index 作参照（自身历史序列锚）。

与 `cycle_stage` 的分工：cycle_stage 判**大盘周期位置**（涨停家数主锚），
relay_phase 判**接力生态相位**（晋级率/断板效应主锚）——高潮日两者同向，
高位分歧日 cycle=ferment 而 relay=divergence，正是分化信号。

## 5. 存储/触发/成本/展示

- 集合 `hotlist_jev_relay_index`，`_id={date}:RELAY`，origin=`relay_index_daily`；
  字段对齐 hotlist_jev_sentiment 惯例（answers/scores/usage/model/questionsRaw/
  errorCode/narrative/computedAt）
- 触发：盘后链（jev_label_jiuyan 之后），`--relay-day` CLI 手动试点入口先行（118 行旧笔误
  `--relay-index-day` 已 2026-10-12 更正，代码自始即 `--relay-day`，无并存参数）
  - **2026-10-12 挂链落地（用户裁决）**：schedule.py `_run_relay_index_step` 进 16:00
    盘后链（steps 序列 jiuyanLabel 之后），门控与 jiuyanLabel 同源（当日 final+15:00 帧），
    幂等 + advisory 语义；CLI 参数定名 `--relay-day`。落地前无自动调度、手动逐日跑，
    因 VPN 断连致 final 缺失漏跑 10-12 一次（手动补打后裁决挂链），登记见
    scripts/register_after_market_task.ps1 头注
- 成本：1 call/日 ≈ 7-8K tokens（叙事六段全含，设计预估）≈ **$0.0003/日**，可忽略；
  2026-10-12 实测七题一 call ≈5.5k tokens（盘后链登记口径与之一致）
- 读口：`GET /api/hotlist-jev/relay-index?date=`；前端情绪面板并列第三条分线
  （相位分线、温度分线、连板指数线），涨停面板展示梯队表+龙头档案
  （§1.2.5 研究结论与前端展示同步，上线路由与面板同轮交付）

## 6. 落地路径（Phase 0 前置工程 → 回放 → 挂链）

0. **Phase 0 原料修复**：THS 连板层五池回采集层（仅 EOD 帧，日增 5 发）+
   `market_metrics.ladder` 改 jiuyan 主源双源；修复后 10-08/10-09 梯队可从 jiuyan
   回填（历史帧不动，叙事侧实时聚合）
1. **Phase 1 回放试点**：手动回放近 10-15 个交易日（约 $0.005，叙事六段全含），
   人工复核分布——已知高潮日应高分、断板日应低分；preregistration 文档先行
2. **Phase 2 对拍**：与 day_temperature/cycle_stage 相关性检查（目标 0.5-0.8；
   <0.4 判据有毛病，>0.85 重复建设需砍题）
3. **Phase 3 挂链+前端**：盘后链步骤 + API + 面板三线同轮上线
4. 全程 fail-visible：jiuyan final 缺/THS 双源皆缺/TDX 不可达 → 对应段落标
   「不可算」降级落库，不伪造不拦截

## 7. 个股打标深度的回应（用户「提问深度不满意」）

个股四题保持结构化判定**不动**：它在本方案中升格为题材脉络题的原料层（82 只/日
聚合零边际成本）。个股题集加深（如加封板质量判定、带动数判定）会引入重打成本与
口径漂移（v3 判据 2026-10-04 才定），建议指数线跑一个月后再评估是否升 v4。

## 8. 2026-10-12 用户终审与同日情绪链异常复盘

### 8.1 用户裁决（盘感终审，当日给出）

1. **10-12 判「高位分歧」更合理**：当日情绪链 EOD `day_stage` 判 climax（高潮）不被
   用户认可，relay 链 `relay_phase=divergence`（高位分歧，conf 0.94）的判定获认可。
2. **「连板情绪的题目集是所有题集里面最好的」**：relay v3 七题判据获用户跨题集最高
   评价（对照情绪槽级/EOD/打标/周期等题集）。
3. **「置信度必须可视化」**：此前页面方案几乎丢弃置信度字段，已找回（见 §8.3）。

### 8.2 异常定性（排查结论，数据链无故障）

当日观感「情绪判断很不正常」（全天退潮→14:30 翻高潮、EOD 跳高潮、与接力 chips 打架）
的归因，按原料→题目→解析→展示顺序排查：

- **原料完整**：80 帧全在、limitSummary 七键全齐、锚窗满 20 日（09-04→10-09）、
  锚逃生率 0.0、11 个情绪文档全 status=ok。不是缺料。
- **盘面本身是分歧日**：涨停 18→46 爬升、最高 10 板破近 20 日 p80（7 板）、龙头强度
  95.3 新高（高潮方向证据） vs 缩量 18%、指数普跌、大跌 68 家、炸板率 35%>p50、
  主力净流出（退潮方向证据）。五档判据在这种「高度强、广度弱」日两可。
- **模型输出低置信平铺是真实状态**：EOD day_stage 概率 ferment/climax **0.42/0.42
  完全平票**（choice=模型自选 climax，解析层无 tie-break），conf 0.27 为近 6 个交易
  日最低（基线 0.35-0.75）；day_crowding 三向 0.27/0.28/0.28（conf 0.14）；14:30
  退潮→高潮翻转 conf 0.24-0.29（对比 10-09 同样翻转 conf 0.76-0.89=真把握）。
- **前端温度双口径 bug（已修）**：槽位温度曾按 `answers.temperature.score×10` 渲染
  （0-9 档位分顶格 90），EOD 按 `scores.day_temperature`（÷9×100）渲染，同列
  「温度 0-100」两套刻度：15:00 显示 60（真实 66.2）vs EOD 69（68.8），把 +2.6 的
  真实差距放大成 9 分跳变，放大了「EOD 突跳」观感（用户裁定此项为主因）。

**遗留观察项（未立项，须预登记才可动）**：情绪链 day_stage 五档（ice/start/ferment/
climax/retreat）无「高位分歧」档，分歧日只能 ferment/climax 平票。是否引入分歧维度
属改门，需预登记+用户审批；当前以置信度可视化（红 P 值）暴露两可状态替代。

### 8.3 同日落地的前端修复（relay_page/index.html 单文件）

1. **温度口径统一**：槽位温度改读 `scores.temperature`（后端按 legend ÷(n-1)×100
   还原，与 EOD `day_temperature` 同式；601/601 槽位文档全覆盖），不再用
   `answers.temperature.score×10`。
2. **置信度 P 值芯片找回**（confChip，三级色：灰 ≥P60 正常 / 琥珀 P35-60 存疑 /
   红 <P35 两可勿当结论；旧文档缺 confidence 时缺省不显示，fail-visible）：
   - 总览：槽位行框架阶段/序列/拥挤形态、EOD 行档位/拥挤、KPI 拥挤形态/接力相位；
   - 连板指数：KPI 七卡（指数/相位/边际/梯队/钱效/题材/龙头）+ 判定明细表六列；
   - 两处 hint 注明 P 含义。
   - 涨停复盘/热榜行情页签（个股标签链）未铺，待后续。
3. 验证：node --check 语法过；8000 series/relay-index 两读口 answers.confidence
   字段实测齐备（relay_phase 0.94 等）；改 html 免重启。

### 8.4 板块领涨字段（2026-10-12 用户需求，§8.1 龙序讲解的落地）

涨停复盘列表新增【领涨】列：内容=个股所在板块的龙一/龙二/龙三。龙序规则抽为
单源函数 `dragon_rows`（jev_label_jiuyan.py，板数 num「N天M板」取 M 降序 → 封板
时间升序，num 缺失=韭研首板口径，time 缺失排序垫底输出 None）：

- `jiuyan_board_dragons`：韭研 final 按板块分组取各家 top3（final 缺失 → 空 map，
  行内空数组前端显示 '-'，降级面由既有 boardJoinDegraded 旗标注记）；
- relay `theme_ladder_lines` 同步改用 `dragon_rows`（龙序规则单一事实源）；
- limitup-labels 路由在 board join 段给每行挂 `boardDragons`（板块键=boardName，
  同出自韭研 final fields.name；韭研 final 之外的板块 → 空数组）；
- relay_page 涨停复盘表在板块列后插入领涨列（角色+名+板数，colspan 10→11）。

对拍验证（2026-10-12 实测）：62/62 行带 boardDragons，其他/AI影视/公告三板块与
relay 题材梯队表逐名一致；领涨覆盖面大于梯队表 top5（大农业/医药医疗等同样有）。
测试 +4（dragon_rows 排序/截断、jiuyan_board_dragons 分组与 final 缺失、路由挂载）。
