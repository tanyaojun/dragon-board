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
