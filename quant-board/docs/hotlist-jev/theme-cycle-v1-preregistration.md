# 题材周期 v1 预登记（theme-cycle，2026-10-25）

> 方法论来源：《第3课：题材周期：一切题材炒作都适用的简单模式》（用户 2026-10-25 立项）。
> 改门：本文件为判据冻结件，与 `analysis/hotlist/theme_cycle.py::classify_board_cycle` 逐字对齐
> （P0-1 纪律：修代码必须同步回改冻结件）；改判据=新代际（THEME_CYCLE_VERSION 递增）+用户批准。

## 一、定位与哲学

- **板块级、以龙头为锚的四阶段炒作周期状态机**：主升浪→转弱势→弱转强→终结者。
  与「板块节点」（sector_nodes，家数锚 8 档）**独立并存互为对照**——两套语言不合并、
  判据互不引用（用户 2026-10-25 拍板）；仅在展示层挂同日 sector_nodes 档位对照列。
- 核心命题（方法论原文）：**题材的锚点是龙头，盯住龙头的演变就能掌控题材周期的演变**；
  龙头不死题材不止，龙头歇菜题材不再；弱转强只有两条路——人气股反包、连板的标杆
  （≥3 板，1-2 板可能只是补涨）；低位首板逆势刚不能刺激弱转强。
- 确定性规则、零 token、可全历史回填；fail-visible：缺料=不可判（unknown），绝不伪装。
- 周期语义：**同板块名≠同题材周期**（机器人 9 月/10 月两波），周期计数 cycleN 跨终结递增。

## 二、数据源（全部既有单源，零新增采集）

| 原料 | 来源 | 用途 |
|---|---|---|
| day_leader_rows | operations/theme_leader_baseline | 板块封板股名单 boardCodes、当日龙一（真连板最高→封板最早）、ladderShape |
| jiuyan_streak_map | operations/jev_label_jiuyan | 个股真连板高度（停牌跳过续算口径） |
| day_status_of | operations/jev_label_jiuyan | 龙一续断（sealed/broken/suspended/unknown；停牌不算断板） |
| snapshot_stock_rows | snapshot 帧行（datasetId+snapshotId） | 当日八合一热榜在榜 code 集（精英过滤证据 A） |
| _daily_bars | jev_label_jiuyan | 恐慌崩塌注记的个股当日涨跌幅 |
| trading_dates_before | jev_label_jiuyan | 交易日轴（终结窗计时、回填成链） |
| hotlist_jev_sector_nodes | 昨日文档只读 | 展示层对照列（**不进判据**） |
| weak_to_strong.classify_day | analysis/hotlist/weak_to_strong | 大盘弱转强三态语境列（**不进判据**） |

与反包池（rewrap_pool）的关系（用户裁定「反包人气股=反包池中的精英」的落地口径）：
- 本判据的「反包」是**周期成员状态转移**（c∈周期成员 ∧ 昨日未封 ∧ 今日封板），
  窗口=周期全长，不受 rewrap_pool 5 日回看窗限制——非第二套「反包率」口径
  （池是全市场反包率因子，率语义；本模块是板块成员轨迹，无率）。
- 全市场反包池当日名单（`build_rewrap_pool(db,date,"final").rewrapCodes`）作为**展示徽标**
  挂在精英反包行上（inMarketRewrapPool=true/false），不参与判定。

## 三、判据表（v1，优先级从高到低，命中即定档）

### 三.0 周期状态字典（跨日递归，文档行内透传）

每板块行带 `cycleState`（昨日文档读出→今日判定更新→今日文档写回）：

```
cycleState = {
  cycleN: int                # 周期序号（板块内从 1 起）
  stage: str                 # 当前档（本节枚举）
  leaderCode/leaderName: str # 现任龙一（周期内最新担任龙一且未断板的股）
  peakStreak: int            # 周期内最高真连板
  membersPeak: {code: int}   # 周期内曾封板股 → 曾达最高真连板（精英判定的「曾≥2板」证据）
  brokenElite: [code]        # 周期内曾真连板≥2 且当前断板的股（反包候选池，板块内版）
  weakDays: int              # 连续转弱可判交易日数（终结窗计时；wzs/新周期清零）
}
```

无周期 = 无 cycleState（或 stage=normal 后清空）。

### 三.1 阶段枚举（7 态，用户 2026-10-25 拍板）

| 档 | 中文 | 方法论对应 |
|---|---|---|
| unknown | 不可判 | —（缺料，fail-visible） |
| wzs | 弱转强 | 弱转强（新龙再崛起） |
| terminator | 终结者 | 终结者（再无新龙崛起） |
| weakening | 转弱势 | 转弱势（真金的考验） |
| main_surge | 主升浪 | 主升浪（龙头角逐） |
| emerging | 启动 | 主升浪前夜（角逐未成形） |
| normal | 平淡 | —（无周期无封板） |

与 sector_nodes 八档对照映射（仅展示）：main_surge↔mainline、weakening↔weakening/collapse、
wzs↔wzs、emerging↔brewing/fermenting、terminator↔ice/退潮段。两套判据互不引用。

### 三.2 关键子判定（先于档位判定）

**机械反包**（周期成员状态转移）：股 c 满足 `c ∈ membersPeak ∧ c ∉ 昨日板块封板集 ∧ c ∈ 今日板块封板集`。
记事件 rewrap；若 `membersPeak[c] ≥ 2` 且今日热榜在榜 → **精英反包**（事件 rewrap_elite）；
`membersPeak[c] ≥ 2` 但热榜不可考 → 精英降级（按精英处理 + 注记「热榜不可考，精英降级高度代理」）；
`membersPeak[c] = 1` → 普通反包（rewrap_plain，**只记事件不改档**）。

**新连板标杆**：今日板块封板股中存在 `jiuyan_streak_map ≥ 3` 且非现任龙一续板的股
（现任龙一已断板时其反包 streak 重算=1，天然走反包路不撞标杆路）。
1-2 板只算补涨，不触发（方法论原文）。

**龙一续断**：当日龙一 = day_leader_rows 行龙一；状态 = day_status_of（昨日龙一 code 今日
sealed/broken/suspended/unknown）。周期现任龙一与当日龙一可能不同（断板后新高度股接位）。

### 三.3 档位判定（classify_board_cycle 优先级实现顺序）

设 `prev = 昨日 cycleState`，`elite_or_benchmark_today` = 今日出现精英反包 或 新连板标杆。

0. **unknown**：今日封板集合不可考（THS 池缺失 / 韭研 final 缺失）→ 全板块 unknown；
   昨日 cycleState 原样透传，`weakDays` **不推进**（不可判日暂停计时，停牌哲学同款），
   注记根因。
1. **新周期开启（relaunch / burst）**：`prev` 无周期或 `prev.stage == "terminator"`，
   且今日板块有封板，且 `elite_or_benchmark_today`：
   → `cycleN = (prev.cycleN or 0) + 1`，stage=**main_surge**，leader=今日真连板最高股，
   事件 burst + relaunch（prev 为 terminator 时注记「源起弱转强/新周期」）。
   （prev 无周期且今日封板但无 elite/benchmark → 走 6/7 条 emerging/main_surge 常规开周期。）
2. **弱转强 wzs**：`prev.stage == "weakening"` 且 `elite_or_benchmark_today`：
   → stage=**wzs**，weakDays=0，leader=触发股（精英反包股或新标杆股），
   事件 wzs（记录触发路径 rewrap_elite / new_benchmark）。
3. **终结者判定 terminator**：`prev.stage == "weakening"` 且 `prev.weakDays + 1 >= 3`
   且非 `elite_or_benchmark_today` → stage=**terminator**，事件 end（周期 N 归档）。
   终结窗 N=3 = 自进入转弱起 3 个**可判**交易日无精英反包无新标杆（缺料日暂停计时）。
   terminator 为**终态**：此后无封板日维持 terminator（板块长尾冷却归档登记为已知局限）；
   出现 1-2 板封板（非精英非标杆）记事件 plain_attempt 不改档。
4. **转弱势 weakening**：周期龙一（昨日 leaderCode）今日 `day_status_of == "broken"`
   （停牌 suspended / 不可考 unknown 均不算断板）：
   → stage=**weakening**，weakDays = (prev.stage=="weakening" ? prev.weakDays+1 : 1)，
   事件 leader_break，brokenElite 并入昨日龙一（若其 membersPeak≥2）。
   龙一 sealed 但无 elite/benchmark 且 prev.stage=="weakening"（昨日 wzs 次日龙一未续）：
   同入本条（weakDays 续计）。
5. **主升浪 main_surge**：周期龙一今日 sealed 且真连板 ≥2：
   → stage=**main_surge**，事件 continue（prev.stage=="wzs" 时注记「新龙续板，弱转强确认」；
   prev.stage=="emerging" 时事件 burst「周期开启」）；龙一接位：当日龙一 sealed 且更高 →
   周期锚跟随当日龙一。
   **prev.stage=="terminator"（终态下龙一复活 ≥2 板）→ cycleN+1 开新周期，事件 relaunch
   「终态下龙一复活，新周期开启」，membersPeak/brokenElite 重置。**
   龙一 sealed 但真连板 <2（断板后普通反包/停牌回封）：prev.stage∈{weakening,terminator}
   → 事件 plain_attempt「补涨语义，不足标杆门槛」不改档维持原档（weakening 时 weakDays
   续计）；prev.stage∈{main_surge,emerging,wzs}（停牌回封等）→ 维持原档注记，不推进终结窗。
6. **启动 emerging / 常规开周期**：今日板块有封板，prev **无周期**（未达条 1 精英/标杆
   门槛）：龙一真连板 ≥2 → stage=**main_surge**（事件 burst「周期开启（龙一
   2 板角逐成形）」）；龙一真连板 ≤1 或不可算 → stage=**emerging**（事件 burst「周期开启
   （角逐未成形）」）；两者均 cycleN+1。
   prev.stage=="terminator" 且未达条 1 门槛（能到此的都 <3 板且非精英反包）不入本条：
   事件 plain_attempt「终态下封板不足 3 板新周期门槛（补涨）」、stage 维持 terminator
   （条 3 终态语义）。
   prev.stage=="weakening"（昨日转弱今日仅首板回升）不入本条：补涨语义，记事件
   plain_attempt、stage 维持 weakening（weakDays 续计），防止补涨污染周期锚。
7. **平淡 normal / 周期中无封板兜底**：无周期状态且今日无封板 → stage=normal。
   周期进行中无封板：weakening → weakDays 续计维持；terminator → 终态维持（无封板；
   题材个股退出自选过程中）；main_surge/emerging/wzs 且龙一 suspended/unknown →
   维持原档注记（停牌不算断板，不推进终结窗）。
   （main_surge/emerging/wzs 且龙一 broken 已由条 4 覆盖；龙一 sealed 但板块无封板
   数学上不可能——龙一封板即板块有封板。）

### 三.4 注记（不改档，fail-visible 透出）

- **妖股形态**：周期龙一真连板 ≥5 续板 且 今日板块封板 ≤3 家 → 注记
  「妖股形态：龙一 N 板独走（板块封板仅 M 家），脱离板块效应」（阈值草案，盘感校准候选）。
- **人气股崩塌（恐慌蔓延警示）**：brokenElite 中今日有 bars 的股，中位涨跌幅 ≤ −5%
  或 收盘跌幅 ≤ −9.9% 家数 ≥2 → 注记「人气股崩塌（中位 X%，跌停 Y 只），恐慌蔓延警示」。
  局限：−9.9% 判跌停不含 20cm 创业板/ST 5% 差异，登记已知局限。
- **对照列**：sectorNode=同日 sector_nodes 档位；marketState=大盘弱转强三态
  （弱/弱转强/强/中性 None）。均语境展示，判据零消费。

## 四、行 schema（`hotlist_jev_theme_cycle`，`_id={date}:THEME_CYCLE`）

```
{ _id, kind: "theme_cycle", tradingDate, version: THEME_CYCLE_VERSION,
  status: "ok"|"degraded", computedAt,
  marketState: {date, state, idx} | null,
  rows: [{ board, stage, cycleN, prevStage,
           leader: {code,name,streak} | null, leaderState,
           events: [{type, stocks:[{code,name,streak}], note}],
           rewrapElite: [...], rewrapPlain: [...], newBenchmark: [...],
           basis: [...], notes: [...],
           sectorNode: str|null,            # 对照列
           cycleState: {...}|null }],       # 透传给次日
  degraded: [...],
  meta: {thsFound, prevDate, prevFound, hotlistFound, rewrapPoolN} }
```

## 五、接线与消费

- 落库：operations/theme_cycle.py `settle_day`（幂等 replace_one，升序回填成链——
  昨日 cycleState 从昨日文档行读）。
- 盘后链：schedule.py sectorNodes 步后挂 themeCycle 步（advisory，门控同 sector_nodes）。
- 读口：`GET /api/hotlist-jev/theme-cycle?date=&days=`（8000）。
- 前端：8008 relay 工作台新子页签「题材周期」（rv-cycle）：主表（板块/周期档/cycleN/
  龙一/事件/依据/sectorNode 对照）+ 展开卡（周期事件时间线 + membersPeak 榜）。
- proxy-server 白名单：/api/hotlist-jev/ 前缀已覆盖，无需改。

## 六、已知局限（如实登记）

1. 板块改名日周期链断（精确匹配哲学；医疗医药/医药医疗异名双桶不拼接——
   sector_nodes 同款局限，两模块一致）。
2. 妖股/崩塌阈值（≥5 板+≤3 家；−5%/−9.9%）为草案值，盘感校准候选，校准=新代际。
3. terminator 终态无冷却归档：长尾 dead 板块维持 terminator 显示（v2 可加 ≥N 日无封板
   归档 normal）。
4. 热榜在榜证据取 15:00 收盘帧口径（盘中在榜变化不追；V2c 式盘中化另行立项）。
5. 热榜行缺失日（帧缺失）精英降级高度代理+注记，不伪判。
6. 崩塌注记跌停判定 −9.9% 不含 20cm/ST 差异。
7. 反包与反包池为两个口径（§二已裁定：周期成员轨迹 vs 全市场反包率），徽标 only。
8. 回填起点受 jiuyan_action final 覆盖（2026-05-06 起）与 snapshot_stock_rows 深度约束；
   主回填 09-01 起对齐 sector_nodes 113 日窗。

## 七、验收

- 单元测试：判据表三.2/三.3 逐条场景覆盖（含军工案例骨架：龙断→标杆接力 wzs→再断→
  终结；补涨不触发；精英降级；不可判日计时暂停）。
- 回填对账：09-01~今日逐日 ok/degraded 清单；机器人/俄乌重建/冰雪经济三案例走查
  与 sector_nodes 档位轨迹交叉对照，分歧点登记本文件勘误节。
- 浏览器验收：用户本人做（8008「题材周期」子页签）。
