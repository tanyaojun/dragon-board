# 板块节点 v1 预登记（sector-nodes，2026-10-24）

> 立项：用户 2026-10-24「连板情绪分析能清晰判断每日情绪节点位置，板块级如何设计节点判断页」
> 方法论：《第5课：板块弱转强：一套高胜率交易系统》（姚世跃）；方案经计划审批（确定性规则先行、
> 双锚先行指数留缺口两裁决）。
> 状态：**v1 已批准实施**（批准计划=批准下述判据表）；改动判据须新代际 v2 + 用户逐条批准。

## 一、定位与哲学

- 大盘级「节点」列（弱/弱转强/强，`analysis/hotlist/weak_to_strong`，relayIndex≤40→≥50+结构确认）
  下沉到**板块-日**粒度；同为**确定性口径**（零 token、可全历史回填、可回测），非 jev 模型判。
- 方法论锚（PDF）：板块效应锚=①板块指数涨跌 ②涨停数量；题材周期锚=龙头续板/断板。
  v1 落地锚②+龙头锚；**锚①板块指数无现成数据源，fail-visible 占位「未接入」**，二期独立立项
  （TDX 880xxx 指数或成分股聚合，用户裁决：双锚先行）。
- 核心纪律照搬大盘弱转强：**转折强才是真强**——昨日非弱势（非转弱/退潮）不贴弱转强标
  （延续强归主升/发酵，防标签通胀）；全部判据只用池内可数证据；fail-visible 不伪 0。

## 二、数据源（全部既有单源，零新增采集）

| 原料 | 单源 | 说明 |
|---|---|---|
| 板块封板家数/龙一/梯队形态/次高连板 | `theme_leader_baseline.day_leader_rows` | 每板块一行：boardN、leader（rank_board_stocks 龙一）、ladderShape（首/2/3板+）、secondStreak |
| 板内断板面 | 同上 prevTotal−prevStill | 2026-10-24d 同名成员口径（迁移不减负） |
| 板内炸板面 | 同上 zhabanN/prevZhabanN | 韭研曾触板−THS 炸板二分同口径 |
| 家数 20 日序列/分位锚 | `board_count_history`（day_leader_rows 同实现） | 严格早于当日，缺口日不插值 |
| 晋级（板块归属） | `jev_relay_index._promotion_stats` + prev pool board 归属 | v4 停牌跳过续算口径 |
| 龙头续板/断板 | `jev_label_jiuyan.day_status_of` | 停牌不算断板（v4 用户裁决）；昨日龙一→今日状态 |
| 板块指数涨跌 | **无（二期）** | 行内显式「未接入」，不伪装 |

## 三、节点判据表（v1，优先级从高到低，命中即定档）

记号：n0=今日家数、n1=昨日同名板块家数（None=不可考：板块改名/昨日池缺失）、n2=前日；
promN=今日晋级家数（昨日封板今日仍封，板块归属）、leaderState=昨日龙一今日状态
（sealed/broken/suspended/unknown/none，词表=`day_status_of` 单源）、
pct(n)=n 处近 20 日家数分位（样本<10 不可算）。

| 优先级 | 节点 | 判据（全部可数） |
|---|---|---|
| 1 | **弱转强 wzs** | 昨日节点∈{转弱,退潮} 且 n1 已知 且 n0≥n1 且 promN≥1 且（leaderState=sealed 或 首板家数≥昨日首板×2） |
| 2 | **退潮 collapse** | n1≥2 且 2×n0≤n1（腰斩）且 leaderState=broken 且 promN=0 |
| 3 | **冰点 ice** | n0=0，或（n0≤1 且 leaderState=broken 且 promN=0） |
| 4 | **转弱 weakening** | n1≥3 且（leaderState=broken 或 n0<n1），未命中 1-3 |
| 5 | **主升 mainline** | pct(n0)≥0.8 且 pct(n1)≥0.8（连续两日高位）且 leaderState=sealed 且 二板以上晋级≥1；分位样本<10 降级为 n0≥5 且 n1≥5（注记「分位降级」） |
| 6 | **发酵 fermenting** | n2 已知 且 n0>n1>n2 连续两日递增 且 n0≥2 |
| 7 | **冒头 brewing** | n2 已知 且 n2≤1 且 n0≥3 |
| 8 | 平淡 normal | 其余 |

- 昨日节点来源：逐日顺序计算时取上一步结果；单日重算读昨日落库文档（`hotlist_jev_sector_nodes`）；
  昨日文档缺失 → 弱转强不贴标，注记「昨日节点不可考」（同大盘 weak_to_strong 首判处理）。
- leaderState=suspended/unknown → 按不可考处理（不算断板也不算续板），涉龙头的分支不命中并注记。
- **今日原料不可考 → 整日降级**：status=degraded 落痕、rows 节点=unknown「不可判」、
  n0=None（家数/梯队/炸板面均不落伪 0）——封板集合不可二分 ≠ 0 家冰点。两种根因同款
  降级并带注记：①THS 池缺失（day_leader_rows 返回 None，回填首跑实测 5 个历史缺口日
  曾误判全冰点，已修 2026-10-24）；②**韭研 final 缺失/为空但 THS ok**（day_leader_rows
  返回空列表不报错，operations 层查 meta.jiuyanFinalFound 后置 None——审计 P2-2 修复，
  2026-10-24；生产两路径被门控/回填日期源挡住，触达面=手工 --day 无 final 日）。
- promN 不可算（晋级链原料缺失）→ 涉 promN 的分支不命中并注记，不伪 0。
- 板块覆盖 = 今日 rows ∪ 昨日 rows ∪ 前日 rows（三日窗口；「昨日/前日有今日无」的板块
  必须在场——退潮/冰点正是它们，n0=0 的行 leader=None、炸板面=0。超三日无封板的
  板块不出行：节点语义弱且长尾噪声大；家数 21 日序列仍取 21 日供分位锚）。
- n1/n2 的 0 与 None 严格区分：参照日池 ok 且板块无封板 → 0（合法零）；参照日池缺失/
  THS 缺失 → None（不可考，涉判据不命中并注记）。

## 四、行 schema（`hotlist_jev_sector_nodes`，`_id={date}:SECTOR_NODES`）

rows[] 每板块：board / count / prevCount / prev2Count / countSeries(≤21 日) /
countPct / prevCountPct / pctDegraded / leader{code,name,streak,time} / prevLeader /
leaderState / promN / promGe2 / ladderShape / secondStreak / zhabanN / prevZhabanN /
brokenN / indexAnchor(=null，恒「未接入」) / node / prevNode / basis[]（命中条件句）/
notes[]（降级与缺失注记）。日级：version（SECTOR_NODE_VERSION）、computedAt、
degraded[]（THS 池缺失整日降级等）、meta。

## 五、接线与消费

- 盘后链：`schedule.run_after_market_once` 在 relayIndex 步后挂 `sectorNodes` 步
  （子进程 `python -m backend.operations.sector_nodes --day`，advisory 失败不翻转，
  门控与 relay index 同源 `_should_run_phase_band`）。
- 读口：`GET /api/hotlist-jev/sector-nodes?date=&days=`（序列节点分布 + 单日全行）。
- 前端：连板指数组新子页签「板块节点」（rv-nodes）：KPI 节点分布 chips（点击筛选）+
  主表 + 行展开明细卡（家数序列 mini-bar、依据全文、注记）。
- 回填：`--backfill --from --to` 全历史（4 月起 ≈130 交易日，纯本地零 token）。

## 六、已知局限（如实登记）

1. 板块名逐日精确匹配（单源纪律）：板块改名 → 昨日家数/晋级/龙头断板对该板块不可考，
   行内注记，不拼接近似名。
2. 晋级板块归属用韭研首个板块口径（relay_structure 同款）：跨板块股只归首板块；
   板块改名日晋级可能落在旧名行。
3. **晋级归属静默丢弃（审计 P3，2026-10-24 登记）**：`_promotion_by_board` 对不在昨日
   韭研 pool 的 promoted 股（封板但未上韭研热榜）跳过不计，promN 偏小 → 退潮更易命中、
   弱转强更难命中；relay_structure 同款口径，观察其影响面再定是否 v2 补「池外晋级」口径。
4. 板块指数锚缺席：转弱/退潮的家数+龙头判据可能漏掉「指数涨但家数未起」的弱转强变体
   （PDF 盘中强势股翻红口径），二期补锚后回看。
5. 盘中信号（强势股集体翻红、成交额重注）v1 不判，收盘定档——与大盘节点收盘定档同哲学。
6. **双日期源（审计 P3 观察项，2026-10-24 登记）**：prev/prev2 取自 `trading_dates_before`
   （snapshot_frames），backfill/board_count_history 日期源是 jiuyan_action final；某日
   两源不同步时 n1/n2 键错位（当前同生率高、33 日回填实测未发生，观察）。
7. **参照日缺失注记 elif 链（审计 P3，2026-10-24 登记）**：昨日池缺失时前日缺失不再单独
   注记；判据侧 n2=None 已防护不误判，仅注记不全（展示层信息量损失，不影响定档正确性）。

## 七、二期待裁项

- TDX 880xxx 板块指数接入（名称映射模糊匹配 245 题材）或成分股涨幅中位数替代。
- 盘中翻红信号列（快照帧 09:30/10:00 槽）。
- jev 板块节点题（LLM 对照）：若规则试点与盘感分歧，走预登记+预算报备流程再立项。
- **弱转强首板分支的数学平凡真（审计 P3，2026-10-24 登记）**：昨日首板=0 时
  `首板≥昨日×2` 恒真，龙头确认被架空（龙头断板也可贴弱转强标）。回填 33 日实测
  2 次「昨日首板=0」命中（09-30 机器人、10-13 大消费）均为今日首板 ≥3 的健康换血，
  病态情形未发生；属判据冻结边缘语义，v2 若收紧（如要求 prev_first≥1 或加「今日首板
  ≥3」下限）须走新代际+用户逐条批准。

## 八、验收

- pytest 专项：逐档规则 fixture + fail-visible（缺池/缺龙头/缺晋级链不伪 0）+ 回填幂等。
- 回填冒烟后 API 抽查对账（家数 vs 韭研池、节点 vs 人工盘感抽验）。
- 浏览器验收用户本人做。

## 九、勘误（冻结件回改登记）

- **2026-10-24 审计勘误（P2-1）**：本文 §三记号行与弱转强/主升判据初稿把龙头续板写作
  `leaderState=continued`，实现词表沿 `day_status_of` 单源实为 `sealed`（语义同=续板，
  非改门），判据文本已回改逐字对齐代码——教训同 jev P0-1：判据冻结件必须逐字=代码文本，
  修代码时同步回改冻结件。
