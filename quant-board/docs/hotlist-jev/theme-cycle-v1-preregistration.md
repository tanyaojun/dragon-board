# 题材周期 预登记（theme-cycle，2026-10-25；v2 代际同日修订）

> 方法论来源：《第3课：题材周期：一切题材炒作都适用的简单模式》（用户 2026-10-25 立项）。
> 改门：本文件为判据冻结件，与 `analysis/hotlist/theme_cycle.py::classify_board_cycle` 逐字对齐
> （P0-1 纪律：修代码必须同步回改冻结件）；改判据=新代际（THEME_CYCLE_VERSION 递增）+用户批准。

## 〇、v1→v2 代际修订（2026-10-25 同日，用户裁定）

**v1 对象定义错误（用户复核推翻）**：v1 误用韭研 action 当日分组名（机器人/冰雪经济/公告…）
为对象——该分组是**板块式归类**，输出与板块节点（sector_nodes）大面积重叠，且题材的事件性
丢失；用户裁定 **题材≠板块**：

| | 板块 | 题材 |
|---|---|---|
| 驱动 | 产业链内部驱动（板块整体上涨→龙头带动跟风） | 外部事件驱动（新闻/小作文/流量热度推动个股异动） |
| 生命周期 | 长期分类标签 | 事件生灭：爆发→发酵→高潮→退潮→消亡 |
| 边界 | 产业链内 | 可横跨多板块；同一板块可先后承载多个题材事件 |
| 覆盖 | 板块节点（sector_nodes 家数锚） | 本模块（v2 起） |

- v1 产物（33 日回填，对象=韭研分组）已 `mongodump` 归档
  `data/backups/theme-cycle-v1-jiuyan-group-archive-20261025/` 后 drop（单一事实源，无备份集合）。
- 判据状态机骨架（§三）对象无关、**零改动**复用；对象定义/取数层重建，THEME_CYCLE_VERSION v1→v2。

## 一、定位与哲学

- **题材级、以龙头为锚的四阶段炒作周期状态机**：主升浪→转弱势→弱转强→终结者。
- 核心命题（方法论原文）：**题材的锚点是龙头，盯住龙头的演变就能掌控题材周期的演变**；
  龙头不死题材不止，龙头歇菜题材不再；弱转强只有两条路——人气股反包、连板的标杆
  （≥3 板，1-2 板可能只是补涨）；低位首板逆势刚不能刺激弱转强。
  「跟强不跟弱，个股概念只跟随最强势的题材」用于**个股主题材辨识**（展示层，后续功能），
  不是题材聚合的前提（见 §二.2）。
- 确定性规则、零 token、可全历史回填；fail-visible：缺料=不可判（unknown），绝不伪装。
- **题材与板块不同维度，不互为对照**（v1 的 sectorNode 对照列删除）；大盘弱转强三态保留语境列。

## 二、数据源（全部既有单源，零新增采集）

### 二.1 题材对象与成分

| 原料 | 来源 | 用途 |
|---|---|---|
| `themes` | MongoDB（longhuvip 题材库，251 题材 id→name） | 题材名单与名字 |
| `theme_stock_mappings` | MongoDB（13580 行，themeId+stockCode+stockTags+stockReason） | 个股→题材归属（一股可映射多题材） |
| `sealed_and_info` | theme_leader_baseline | 当日封板集合（韭研触板−THS 炸板二分，剔 ST/北交所） |
| `jiuyan_streak_map` | jev_label_jiuyan | 个股真连板高度 |
| `day_status_of` | jev_label_jiuyan | 龙一续断（停牌不算断板） |
| `snapshot_stock_rows` | snapshot 帧行 | 当日八合一热榜在榜 code 集（精英过滤证据 A） |
| `_daily_bars` | jev_label_jiuyan | 恐慌崩塌注记跌幅 |
| `weak_to_strong.classify_day` | analysis/hotlist | 大盘弱转强三态语境列（**不进判据**） |

### 二.2 题材聚合规则（v2 冻结）

- **题材独立聚合、重叠计入**：一只封板股映射到 K 个题材 → K 个题材各自计入该股。
  题材行的封板集合、家数、龙一均在该题材成分内独立统计（一个题材的强弱不因成分股
  被别的题材共享而失真）。个股主题材辨识（跟强不跟弱）留展示层，不在此裁剪。
- **题材龙一**：题材内封板股按 `rank_board_stocks`（真连板最高→封板时间最早）。
- **行集门槛**：当日题材封板 **≥2 家** 出行；昨日已有 cycleState 的题材链延续出行
  （今日 1 家/0 家照常演化 weakening/terminator）。单股首日题材不出行（方法论：
  1-2 板可能只是补涨，单股首板无周期语义）。
- **未映射股**：`theme_stock_mappings` 无该 code → 不进任何题材行，
  `meta.unmappedN/unmappedCodes`（截断 30）披露，不伪装、不静默丢弃。
- **前视局限**：映射无历史（每日 08:30 刷新当前归属），历史回填日按**当前批次映射**
  归属；`meta.mappingBatchAt`（mappings.updatedAt 最大值）披露批次。

### 二.3 与反包池的关系（v1 裁定沿用）

本判据「反包」=**周期成员状态转移**（c∈周期成员 ∧ 昨日未封 ∧ 今日封板），窗口=周期全长，
非 rewrap_pool 5 日窗的第二套反包率；全市场反包池当日名单（`build_rewrap_pool.rewrapCodes`）
仅作展示徽标（inMarketRewrapPool），不参与判定。

## 三、判据表（v2；与 classify_board_cycle 逐字对齐，v1 §三骨架零改动）

### 三.0 周期状态字典（跨日递归，文档行内透传）

```
cycleState = {
  cycleN: int                # 周期序号（题材内从 1 起）
  stage: str                 # 当前档
  leaderCode/leaderName: str # 现任龙一
  peakStreak: int            # 周期内最高真连板
  membersPeak: {code: int}   # 周期内曾封板股 → 曾达最高真连板（精英判定的「曾≥2板」证据）
  brokenElite: [code]        # 周期内曾真连板≥2 且当前断板的股（反包候选池，题材内版）
  weakDays: int              # 连续转弱可判交易日数（终结窗计时；wzs/新周期清零）
}
```

### 三.1 阶段枚举（7 态，2026-10-25 拍板）

| 档 | 中文 | 方法论对应 |
|---|---|---|
| unknown | 不可判 | —（缺料，fail-visible） |
| wzs | 弱转强 | 弱转强（新龙再崛起） |
| terminator | 终结者 | 终结者（再无新龙崛起） |
| weakening | 转弱势 | 转弱势（真金的考验） |
| main_surge | 主升浪 | 主升浪（龙头角逐） |
| emerging | 启动 | 主升浪前夜（角逐未成形） |
| normal | 平淡 | —（无周期无封板） |

### 三.2 关键子判定（先于档位判定）

**机械反包**（周期成员状态转移）：股 c 满足 `c ∈ membersPeak ∧ c ∉ 昨日题材封板集 ∧
c ∈ 今日题材封板集`。记事件 rewrap；若 `membersPeak[c] ≥ 2` 且今日热榜在榜 → **精英反包**
（事件 rewrap_elite）；`membersPeak[c] ≥ 2` 但热榜不可考 → 精英降级（按精英处理 +
注记「热榜不可考，精英降级高度代理」）；`membersPeak[c] = 1` → 普通反包（rewrap_plain，
**只记事件不改档**）。

**新连板标杆**：今日题材封板股中存在 `jiuyan_streak_map ≥ 3` 且非周期现任龙一续板的股。
1-2 板只算补涨，不触发（方法论原文）。

**龙一续断**：当日龙一 = 题材内 rank_board_stocks 首位；周期现任龙一（prev.leaderCode）
今日状态 = day_status_of（池权威+日线补洞；停牌 suspended / 不可考 unknown 均不算断板）。

### 三.3 档位判定（classify_board_cycle 优先级实现顺序）

设 `prev = 昨日 cycleState`，`elite_or_benchmark_today` = 今日出现精英反包 或 新连板标杆。

0. **unknown**：今日封板集合不可考（THS 池缺失 / 韭研 final 缺失）→ 全题材 unknown；
   昨日 cycleState 原样透传，`weakDays` **不推进**（不可判日暂停计时），注记根因。
1. **新周期开启（relaunch / burst）**：`prev` 无周期或 `prev.stage == "terminator"`，
   且今日题材有封板，且 `elite_or_benchmark_today`：
   → `cycleN = (prev.cycleN or 0) + 1`，stage=**main_surge**，leader=触发股，
   事件 burst + relaunch（prev 为 terminator 时注记「终结后新周期（源起弱转强）」）；
   **relaunch 时 membersPeak/brokenElite 重置**（同题材名≠同题材周期）。
2. **弱转强 wzs**：`prev.stage == "weakening"` 且 `elite_or_benchmark_today`：
   → stage=**wzs**，weakDays=0，leader=触发股（精英反包股或新标杆股），
   事件 wzs（记录触发路径 rewrap_elite / new_benchmark）。
3. **终结者判定 terminator**：`prev.stage == "weakening"` 且 `prev.weakDays + 1 >= 3`
   且非 `elite_or_benchmark_today` → stage=**terminator**，事件 end（周期 N 归档）。
   终结窗 N=3 = 自进入转弱起 3 个**可判**交易日无精英反包无新标杆（缺料日暂停计时）。
   terminator 为**终态**：此后无封板日维持 terminator；出 1-2 板封板（非精英非标杆）
   记事件 plain_attempt 不改档（长尾冷却归档登记为已知局限）。
4. **转弱势 weakening**：周期龙一今日 `day_status_of == "broken"` 且 `prev.stage != "terminator"`
   （终态下 broken 是常态不再转弱）：→ stage=**weakening**，weakDays =（昨日已是
   weakening 则 +1，否则 1），事件 leader_break，龙一（若 membersPeak≥2）并入 brokenElite。
5. **主升浪 main_surge**：周期龙一今日 sealed 且真连板 ≥2：
   → stage=**main_surge**，事件 continue（prev=="wzs" 注记「新龙续板，弱转强确认」；
   prev=="emerging" 事件 burst「周期开启」）；龙一接位：当日龙一 sealed 且更高 → 周期锚跟随。
   **prev.stage=="terminator"（终态下龙一复活 ≥2 板）→ cycleN+1 开新周期，事件 relaunch，
   membersPeak/brokenElite 重置。**
   龙一 sealed 但真连板 <2（断板后普通反包/停牌回封）：prev∈{weakening,terminator} →
   事件 plain_attempt 不改档维持原档（weakening 时 weakDays 续计）；prev∈{main_surge,
   emerging,wzs} → 维持原档注记，不推进终结窗。
6. **启动 emerging / 常规开周期**：今日题材有封板，prev **无周期**（未达条 1）：龙一真连板
   ≥2 → stage=**main_surge**（burst「周期开启（龙一 2 板角逐成形）」）；≤1 或不可算 →
   stage=**emerging**（burst「周期开启（角逐未成形）」）；均 cycleN+1。
   prev=="weakening"（转弱中仅首板回升）不入本条：补涨语义 plain_attempt、维持 weakening
   （weakDays 续计）。prev=="terminator" 且未达条 1 → plain_attempt、维持 terminator。
7. **平淡 normal / 周期中无封板兜底**：无周期且今日无封板 → normal。周期进行中无封板：
   weakening → weakDays 续计维持；terminator → 终态维持；main_surge/emerging/wzs 且
   龙一 suspended/unknown → 维持原档注记（停牌不算断板，不推进终结窗）。

### 三.4 注记（不改档，fail-visible 透出）

- **妖股形态**：周期龙一真连板 ≥5 续板 且 今日题材封板 ≤3 家 → 注记「妖股形态：龙一
  N 板独走（题材封板仅 M 家），脱离题材效应」（阈值草案，盘感校准候选）。
- **人气股崩塌（恐慌蔓延警示）**：brokenElite 中今日有 bars 的股，中位涨跌幅 ≤ −5%
  或 收盘跌幅 ≤ −9.9% 家数 ≥2 → 注记（−9.9% 判跌停不含 20cm/ST，登记局限）。
- **语境列**：marketState=大盘弱转强三态（弱/弱转强/强/中性 None）。只展示，判据零消费。

## 四、行 schema（`hotlist_jev_theme_cycle`，`_id={date}:THEME_CYCLE`）

```
{ _id, kind: "theme_cycle", tradingDate, version: "v2", status, computedAt,
  marketState: {state, idx, hit} | null,
  rows: [{ theme, stage, stageCn, cycleN, prevStage,
           leader: {code,name,streak} | null, leaderState,
           boardN, boardCodes, ladderShape, secondStreak,
           events: [{type, stocks:[{code,name,streak}], note}],
           rewrapElite: [...], rewrapPlain: [...], newBenchmark: [...],
           basis: [...], notes: [...],
           todaySealed: [code],           # 次日反包判定「昨日未封」依据
           cycleState: {...}| null }],
  degraded: [...],
  meta: {thsFound, prevDate, prevFound, hotlistFound, rewrapPoolN,
         mappingBatchAt, mappedN, unmappedN, unmappedCodes} }
```

## 五、接线与消费

- 落库：operations/theme_cycle.py `settle_day`（幂等 replace_one，升序回填成链）。
- 盘后链：schedule.py themeCycle 步（sectorNodes 后，advisory，同门控；链序保证题材
  龙一 status 依赖的日线/池原料就绪）。
- 读口：`GET /api/hotlist-jev/theme-cycle?date=&days=`（8000）。
- 前端：8008 relay 工作台「题材周期」子页签（rv-cycle）：主表（题材/周期档/cycleN/
  龙一/事件/依据）+ 展开卡（事件流/精英反包/新标杆/普通反包）。

## 六、已知局限（如实登记）

1. **映射前视**：theme_stock_mappings 无历史，回填日按当前批次归属（meta.mappingBatchAt
   披露）；映射每日 08:30 刷新，题材名录变更（新题材/改名）跨日不可考。
2. **重叠计入**：一股多题材时题材间共享成员，跨题材比较（家数/反包）含重复计数，
   题材内纵向轨迹不受影响。
3. **巨无霸概念**：成分大的题材（人工智能等）几乎每日 ≥2 家封板，其周期长期处于
   活跃档——题材内纵向轨迹仍有效（周期号/龙头演化），跨题材横向比较时须知情。
4. 妖股/崩塌阈值（≥5 板+≤3 家；−5%/−9.9%）为草案值，盘感校准=新代际。
5. terminator 终态无冷却归档：长尾 dead 题材维持 terminator 显示（v2 可加 ≥N 日
   无封板归档 normal）。
6. 热榜在榜证据取 15:00 收盘帧口径（盘中化另行立项）；热榜行缺失日精英降级+注记。
7. 崩塌注记跌停判定 −9.9% 不含 20cm/ST 差异。
8. 板块（产业链）维度的龙头锚周期不在本模块——板块节点（家数锚）覆盖；若未来要
   板块龙头锚周期须另立对象（v1 教训：两者混用=与板块节点重叠）。

## 七、验收

- 单元测试：判据表 §三 逐条场景（v1 33 用例骨架沿用，operations 层换题材聚合 mock）。
- 回填对账：09-01~10-24 重建后逐日 ok/degraded 清单；机器人等题材纵向轨迹走查
  （大业股份所在题材的全周期），题材≠板块的行集差异抽查。
- 浏览器验收：用户本人做（8008「题材周期」子页签）。

## 八、勘误（冻结件回改登记）

- 2026-10-25 v1→v2：对象定义重建（§〇），判据骨架零改动；THEME_CYCLE_VERSION v1→v2。
