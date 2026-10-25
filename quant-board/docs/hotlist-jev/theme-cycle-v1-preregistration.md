# 题材周期 v1 预登记（theme-cycle，2026-10-25）

> 立项：用户 2026-10-25「按你推荐方案执行」——重立方案草案
> （theme-cycle-v1-reproposal-20261025.md）七项待裁定全部按推荐落定：
> ①终结窗 N=3 ②EOD 定档+事件流帧级时点 ③N5/N10 双窗只作对照列不进门
> ④人气股池扫描近 60 交易日 ⑤回填起点 2026-07-01 ⑥妖股阈值=龙头≥5 板且
> 题材内封板≤3 ⑦relay 工作台新子页签 rv-themeCycle。
> 状态：**v1 已批准实施**；改动判据须新代际 v2 + 用户逐条批准。
> 前提：KPL 题材数据治理完成（f9c96482+6975a23c）——mainTheme 跟强不跟弱已重算、
> familyLinks 18 对、非题材剔除 3 条。

## 一、定位与哲学

- 对象=**KPL 题材**（外部事件驱动视角）；与板块节点（产业链内部驱动视角，
  家数锚八档）并存互为对照，两套语言不合并、不互写判据（题材≠板块，用户裁定）。
- 方法论（第3课）锚=**龙头轨迹**：启动→主升浪（龙头角逐）→转弱势（龙头断板
  真金考验）→弱转强（人气股反包/新标杆，两路）| 终结者（再无新龙崛起）。
  确定性规则、零 token、可全历史回填。
- 判据全部可数；fail-visible 不伪 0（原料缺失=unknown；昨日档不可考→弱转强
  不贴标，防标签通胀——板块节点/大盘弱转强同哲学）。

## 二、判定原料（单一事实源，零新增采集）

| 原料 | 单源 | 说明 |
|---|---|---|
| 题材内涨停名单 | `snapshot_stock_rows` 当日最新槽：`mainTheme=题材 ∧ leadStatus=涨停` | THS 池口径；mainTheme 治理后 90.3% 判出，None 行不入任何题材 |
| 题材当日涨停数 n0 | 上名单计数 | KPL `ztCount`（sector_rows）作对照列（口径差如实并排） |
| 真连板 | `jiuyan_streak_map` | 不可算=None 不猜 |
| 龙头 | 名单内真连板最高→`firstZtTime` 最早 | 爆发日=最先涨停即龙头（用户裁定） |
| 龙头续板/断板 | `day_status_of` | 停牌不算断板（v4 用户裁决，板块节点同源） |
| 人气股池 | 近 60 交易日 `mainTheme=题材 ∧ leadStatus=涨停 ∧ boardHeight≥2` 的 code 并集 | 断板不删（第3课语义）；窗口池口径注记（非「本周期起点后」精确池，§六.3） |
| 家族挂靠 | 治理层 `familyLinks` 18 对 | mainTheme 判定已含，题材归属自动生效，本层零额外逻辑 |
| 连板高度 | `boardHeight`（stock rows 现成） | 梯队/妖股判据用 |

## 三、题材活跃域

- 进入条件：当日题材内涨停 ≥1 或近 3 交易日有涨停（三日窗口并集——「昨日有今日无」
  的退潮/终结题材必须在场；超三日无涨停不出行）。
- 涨停家数历史（N5/N10 对照列与三日窗口）从本集合历史文档 rows[].count 读
  （回填升序天然成链；单日重算读历史文档，同板块节点）。

## 四、状态机判据表（v1，优先级从高到低，命中即定档）

记号：n0=今日题材内涨停家数（None=不可考）、n1=昨日；leaderState=昨日龙头今日
状态（`day_status_of` 词表）；maxStreak=今日名单内最高真连板；pool=人气股池；
prevStage/prevWeakDays/cycleN 来自昨日落库行（回填升序天然成链）。

| 优先级 | 阶段 | 判据 |
|---|---|---|
| 0 | unknown 不可判 | n0=None（当日 stock rows 缺失/mainTheme 判定率不足）不伪 0 |
| 1 | **弱转强 wzs** | prevStage=weakening 且今日命中两路之一：①**人气股反包**=pool∩今日封板 且该股昨日未封；②**新连板标杆**=名单内存在真连板≥3 的股。昨日档不可考→不贴标注记 |
| 2 | **终结 terminator** | prevStage=weakening 且 prevWeakDays≥N−1（N=3）且今日无反包、无新标杆、无新启动（n0<4）。终结后再出 n0≥4 或新标杆 → **新周期**（cycleN+1，归 emerging/mainline 按龙头成形） |
| 3 | **转弱 weakening** | leaderState=broken（真金考验）。今日同时 n0≥4 → 注记「高量换血」不改档 |
| 4 | **主升 mainline** | leaderState=sealed 且龙头真连板≥2（龙头角逐进行中）；对照列 n5Pct/n10Pct（家数近 5/10 日分位，≥0.8 高位标记，不进门） |
| 5 | **启动 emerging** | n0>3（≥4 只，用户裁定「超过 3 只」）且未命中 mainline（龙头未成形/换血：含全是首板场景 maxStreak=1）；爆发日龙头=firstZtTime 最早 |
| 6 | 平淡 normal | 其余（n0≤3 且无周期进行中） |

- **周期计数**：terminator 判死后题材再出 n0≥4/新标杆 → cycleN+1 新周期
  （「同题材名≠同题材周期」）；weakening 内复活（wzs）=同周期延续。
- **cycleState**：每行落 {cycleN, weakDays}；weakening 日 weakDays=prev+1，
  wzs/mainline/emerging 日 weakDays=0；回填升序递归成链（板块节点 prev_node 同式）。
- 首日（昨日无文档）：prevStage=None → wzs/terminator 不贴标注记；leaderState
  由 day_status_of 照常判（昨日名单可考即可）。

**注记（不改档，fail-visible 透出）**：
- 恐慌蔓延：pool 股今日跌停 ≥2 只 或 中位跌幅 ≤−5%（**当日 stock rows pctChange
  口径**——2026-10-25 实施时由日线改快照行：同语义当日跌幅、免逐码日线网络链，
  判据冻结件随代码回改登记）；
- 妖股形态：龙头真连板≥5 且当日题材内封板 ≤3（摆脱板块独走）。

**事件流（行内 events[]，每事件带帧级时点）**：
爆发（emerging 首日）/续板（龙头 sealed，带 firstZtTime）/断板（broken）/
反包（反包股名单+封板时间）/新标杆（≥3 板名单）/恐慌/妖股/终结/新周期。
EOD 定档+事件时点=封板时刻（用户裁定②推荐形态）。

## 五、行 schema（`hotlist_jev_theme_cycle`，`_id={date}:THEME_CYCLE`）

rows[] 每题材：theme / stage / prevStage / cycleN / weakDays / count / prevCount /
countSeries(≤11 日) / n5Pct / n10Pct / kplZtCount（对照列） /
leader{code,name,streak,time,boardHeight} / prevLeader / leaderState /
maxStreak / popularN / rewrapCodes / benchmarkCodes / events[] / basis[] /
notes[]。日级：version（THEME_CYCLE_VERSION）、computedAt、degraded[]、meta。

## 六、已知局限（如实登记）

1. 题材归属=mainTheme 单源：mainTheme=None 行（9.7%）不入任何题材，个别日
   名单偏小（basis/notes 不伪装）；5-6 月原料断档日主名单不可回放（T1 已标注）。
2. 涨停口径=THS 池 leadStatus，与 KPL ztCount（题材成分口径）存在口径差，
   对照列如实并排不混用。
3. 人气股池=近 60 日窗口池，非「本周期起点后」精确池：跨周期老人气股可能触发
   反包路径（第3课人气股池本身断板不删，语义接近；精确池留 v2）。
4. 题材改名（KPL 官方改名）：昨日档按题材名精确匹配，改名日周期链断（板块节点
   同哲学，不拼接近似名）。
5. EOD 定档：盘中状态不判（同日转换以事件封板时点承载，用户裁定②）。
6. N5/N10 对照列样本 <5/10 日时分位不可算，如实 None。
7. **跨题材龙头迁移（回填实测发现，10-21 机器人案例）**：龙头股当日 mainTheme 判到
   更强题材（跟强不跟弱）→ 本题材名单内无此股，但 leaderState 判其全市场状态
   （sealed）→ 出现「龙头状态=续板但名单无龙头」的组合，当日判平淡。两轴背离
   如实透出（leader/leaderState/名单三字段并排可审计）；题材内精确龙头状态留 v2。
8. **弱事件题材被吸收（回填实测发现，俄乌重建 10-22 案例）**：事件型题材若涨停股
   同时挂多个题材且他题材更强，mainTheme 归强 → 本题材名单空、周期不出行——
   跟强不跟弱口径对「缺乏独立强度的事件题材」的系统性影响。缓解=KPL ztCount
   对照列并排监控（口径差可见）；v2 可议名单放宽口径（须用户裁决）。
9. 长假期问断（冰雪经济 9 月→10 月案例）：转弱未满终结窗即遇长假/长期无涨停 →
   平淡延续沉没，再活跃按新周期（cycleN 不加）——9-09 转弱与 10-13 再启动之间
   无 terminator 判死。第3课「终结者」语义的长期沉没形态是否需显式判死留 v2。

## 七、验收

- pytest 专项：逐档规则 fixture + fail-visible（缺名单/缺龙头/缺昨日档不伪 0）+
  周期成链（weakDays 递归/cycleN+1）+ 回填幂等。
- 回填后案例反验：机器人 10-16~10-23 全周期走查（大业 6 板龙头轨迹）、冰雪经济
  退潮终结、俄乌重建 10-22 启动；与板块节点 wzs 名单交叉对照（分歧点登记）。
- 浏览器验收用户本人做。
