# 连板情绪指数 板块/龙头叙事 预注册（v6：板块接力链 + 龙头结构）

> 2026-10-19 起草并实现（用户裁决在前、实现不得偏离本文 §2/§3 的改动清单与口径）。
> 上游依据：`jev-relay-index-design.md`（§3「题材梯队/龙头上升轨迹」原规划、§9/§9.1 口径修正）、
> `jev-relay-ammo-v4-preregistration.md`（停牌分辨/高位多日轨迹，本文的**依赖项**而非范围）。
> 触发：用户 2026-10-19 指出「还差板块和龙头叙事——三日接力链主线板块是哪个、板块龙头是哪个、
> 情绪龙头、总龙头是怎么产生的」，经三轮裁决（见 §11）后落成本文。

## 1. 背景与根因（v5 语料的缺口）

v5 叙事 11 段里，板块只有 two 处：`theme_evolution_line`（今日 top3 题材家数 + 连续 top3 天数 +
近 5 日题材榜）、`theme_ladder_lines`（top5 题材的龙一/二/三 + 标签聚合）；龙头只有
`leader_profile_lines`（**只选区间高度 M 最高那一只**做档案）。于是三件事在语料里**没有证据**：

| 缺口 | 现状 | 后果 |
|---|---|---|
| 三日接力链的板块归属 | `three_day_chain_line` 是纯个股视角（D-2 top3 逐日命运），零板块字段 | 无法回答「主线板块是哪个」；`theme_pulse` 只能靠当日家数 |
| 板块龙头的跨日地位 | `theme_ladder_lines` 只列今日 top5 题材的龙序 | 主线板块可能不在家数 top5（家数多而无高位股的板块会遮住它）；板块龙一是否延续不可见 |
| 总龙头 vs 情绪龙头 | `leader_profile_lines` 只有一个「区间高度最高」口径 | 「情绪龙头（真连板最高）」与「总龙头（区间高度最高）」是否同一只不可知；总龙头怎么「长出来」不可知 |
| 龙头诞生轨迹 | `jev-relay-index-design.md` §3 原规划「龙头上升轨迹（从首板到当前高度用了几天、断过几板）」，**从未实现** | 「总龙头是怎么产生的」无证据 |

## 2. 改动清单（实现不得偏离）

### 2.1 口径锁定（用户 2026-10-19 裁决）

1. **总龙头** = 当日触板池 `_day_eff`（韭研 num「N天M板」的 **M**，区间板数）最大者，并列封板时间升序
   —— 与既有 `leader_profile_lines` 同规，**抽为单源**（`relay_structure.totalLeader` 供给本段与龙头结构段，
   禁双实现）。
2. **情绪龙头** = 当日触板池 `jiuyan_streak_map` **真连板**（int）最大者，并列 M 降序 → 封板时间升序；
   池内无任何 int streak → `null`（不可算，**不回落区间 M 冒充**）。
3. **板块龙头** = `dragon_rows(板块股票, streaks=当日 streak, top=3)` 的**龙一**，与涨停复盘「领涨」列
   同一事实源（`jev_label_jiuyan.dragon_rows`）。
4. **主线板块** = 三日链**存活股**（D-2 封板 ∧ D-1 封板 ∧ D0 封板，**停牌跳过不计断板**）归属最多的板块；
   排序键 = (存活数, 今日晋级数, D0 家数, D0 最高 M, 板块名)。存活为 0 时逐级降级：
   D-1→D0 晋级股归属 → D0 板块涨停家数，并在文本**显式写清依据**。
   文中「存活为零/均为零」只允许用于**三日链可算且结果真为零**；三日链本身不可算
   （链日无韭研 final / 历史不足 <3 日）时 `survivors`/`promoted` 落 **None**、依据键 `chain_na`、
   文本写「不可算（原因）」——**不得把缺料读成「为零」**（2026-10-19 review P1：原实现把缺料日
   渲染成「三日存活 0 只／今日晋级 0 只」并据此写依据，违反 §4.0 与本节第 9 条）。
5. **板块归属**：个股归属取 `_pool_of` 的**首个板块**（韭研 final 字段出现序）；板块家数/最高板按韭研
   **全部归属**、跨板块重复不去重（与 `theme_ladder_lines`/`theme_evolution_line` 同规，段首注一次）。
6. **总龙头诞生轨迹**：首板日 = 韭研「N天M板」的 **N** 推算（N 为**含今日**的区间跨度，故首板日 =
   **N−1 个交易日前**，即 `tradingDaysAgo = N−1`；首板股写 0 = 当日），随后**单点校验**
   该日是否真在韭研池；不可核时**按原料→口径的顺序**给原因（三种，2026-10-19 §14.6 修复）：
   ①首板日**早于韭研池史起点** → 「早于韭研池史起点（YYYY-MM-DD 起），无法校验」（原料边界）；
   ②该日**韭研 final 缺档** → 「韭研池缺失，无法校验」；③池史覆盖该日但该股不在池 →
   「不在韭研池（首板日仅为推算；或该股当日停牌）」。N 缺失才回退 60 日池史回溯（罕见路径）。
   断板次数 = 区间口径 `N − M`；当前真连板取 `streak`。**全程只读韭研池史，不读 TDX**
   —— 故回放历史日不受「日线取现在」缺陷（`_daily_bars` 按现在取棒）影响。
7. **龙头更替** = 今日总龙头 vs D-1 总龙头；不同则用 `day_status_of` 给出昨日龙头今日状态
   （sealed/broken/suspended/unknown）作为退位原因；昨日龙头今日仍封板时写「位次被超越」。
8. **泛板块降权**（实现期新增，2026-10-19 生产干跑驱动，见 §13）：韭研 `其他`/`公告`/`新股` 是
   非题材口径的兜底桶（近 60 日家数 554/402/50，天然最大）。主线选择**真题材优先**，泛板块仅在真题材
   全无证据时兜底；在文本显式披露「泛板块「X」家数/存活更多但非题材口径，已排除」。展示与统计仍如实列出
   并标「泛板块」。
9. 全部新段 fail-visible：韭研 final 缺失 / streak 不可验 / 首板日超窗 / 板块无龙头，逐项写「不可算 + 原因」，
   禁 0 或空串冒充。

### 2.2 计算层（单一事实源）

`backend/operations/jev_relay_index.py` 新增：

- `relay_structure(db, date, dataset_id) -> dict` —— **唯一计算入口**，一次算齐供叙事渲染与文档落库共用
  （防「叙事说 A、前端说 B」三处漂移）。结构：
  ```
  {"dates": {"d2","d1","d0"},
   "chain": {"ok":bool,"reason":str|null},                      # 三日链可否算（缺料 → ok=false）
   "sectors":[{name,d2{},d1{},d0{},survivors|None,survivorNames,promoted|None,
               top3Streak,dragon}],                              # 链不可算 → survivors/promoted=None
   "mainline":{name,basis,survivors|None,holdings,d0Count,d0MaxBoard,d0MaxBoardText,
               top3Streak,dragon,pseudoExcluded,chainOk},
   "mainlineDragon":{role,code,name,boards,days,streak,time}|null,
   "totalLeader":{...}, "sentimentLeader":{...}|null,
   "sameStock":bool|null, "leaderIsMainlineDragon":bool|null,
   "genesis":{firstBoardDate,tradingDaysAgo,breaks,streak,degraded}|null,
   "succession":{prevDate,prevLeader,changed,prevStatus}|null, "degraded":[reasons]}
  ```
- 辅助：`_sector_day_stat`（单板块单日家数/区间最高/真连板）、`_leader_genesis`（诞生轨迹）、
  `_sector_top3_streaks`（连续 top3 天数，**单源抽取**：原 `theme_evolution_line` 的内联闭包改调它，
  一次取数供多板块共用，原实现每板块重复 10 次查库）。
- `leader_profile_lines(..., *, total_leader=None)`：传入 struct 时直接消费（禁二次选股）；缺省时内部自算
  （口径与原实现逐字一致，直调兼容）。
- `theme_ladder_lines(db, date, top=5, mainline=None)`：主线板块**强制纳入 top5 并置顶**
  （家数多 ≠ 主线，主线可能被家数型板块遮住）。

### 2.3 叙事层（新增 2 段）

`build_relay_narrative` 新顺序：盘面事实 → 炸板面 → 晋级与断板 → 梯队量化 → 三日晋级链 → 题材演化 →
**板块接力链（三日）** → 高位股多日轨迹 → 题材梯队表 → **龙头结构** → 龙头档案 → 近10日轨迹 → 参照段。

段 A `板块接力链（三日）`（`sector_relay_lines(struct)`）：

```
板块接力链（三日 D-2→D0；主线=三日链存活股归属最多；个股归属取韭研首个板块，家数按全部归属不去重）：
· <板块>（[主线]/[泛板块]）：MM-DD n只/最高N天M板 → … → MM-DD n只/最高…｜三日存活 k 只（名字）｜今日晋级 p 只[｜连续top3 c日]｜龙一 名(N天M板·连板X)
主线板块：<X>（依据 <依据中文>；三日存活 k 只（名单）、今日 n 只·最高N天M板）[；泛板块「Y」家数/存活更多但非题材口径，已排除]；总龙头在本板块：是/否
```

- 某链日韭研 final 缺失 → 该列写「MM-DD 缺失」，该行「三日存活/今日晋级」写
  **「不可算（原因）」**（`chain.ok=false`），主线依据走 `chain_na`；**不落「0 只」**。
  只有三日链可算且真为零时才写「0 只」。缺位同时由 `anchorGapsDerived`「板块接力链」
  （探针含「三日存活 不可算」）暴露。
- 「连续top3 0日」不渲染（0 不携带信息；今日 top3 及其连续天数已由「题材演化」段给出）。

段 B `龙头结构`（`leader_structure_lines(struct)`）：

```
龙头结构（总龙头=区间高度M最高；情绪龙头=当前真连板最高；板块龙头=dragon_rows 龙一）：
· 总龙头 名(code) N天M板·真连板X·<板块>板块·封板HH:MM·板内带动P只·热榜第R名
· 情绪龙头 名(code) 真连板X·N天M板·<板块>板块·封板HH:MM      （不可算时明示）
· 一致性：总龙头与情绪龙头{为同一只 / 不同（总龙头区间高度最高、情绪龙头真连板最高）}
· 升位关系：总龙头{是 / 不是}主线板块「X」的龙一（该板块龙一为 Y）→ {由主线板块龙头升位 / 龙头与主线分离}
· 诞生轨迹：首板 MM-DD（K 个交易日前）→ 区间 N天M板（区间内断板 N-M 次）→ 当前真连板X
· 更替：MM-DD 总龙头 <旧名> → 今日{延续 / 换龙头（旧龙头今日断板/停牌跳过/仍封板·位次被超越/不可验）}
```

## 3. 题目集快照（v6，实现不得偏离）

| 项 | v5（现行） | v6（本文） |
|---|---|---|
| `QUESTION_SET_VERSION_RELAY` | `"v5"` | `"v6"` |
| 题目/档位枚举/`SCORE_ANCHORS_10` | 7 题 | **均不变** |
| `leader_strength` instructions | 龙头档案 + 近20日参照 | 同左 + **【龙头结构】总/情绪/板块三者、升位关系、龙头地位折扣、诞生轨迹为韧性证据** |
| `theme_pulse` instructions | 题材梯队表 + 题材演化 | 同左 + **【板块接力链（三日）】给出主线板块与两日家数递变/今日晋级/连续top3/升位，与【题材梯队表】【题材演化】同权参照、不作主锚、不得单独据其打分**（D3「轻引」；2026-10-19 review P1 修正：不得把未验收的新段升为主锚，避免判据权重静默迁移） |
| `relay_phase` / `relay_index` instructions | — | 各增一句「【板块接力链】与【龙头结构】是梯队健康度的结构参照，**不得单独据其打分**」（沿用 v4 高位轨迹句式，防判据权重偏移） |
| 叙事结构 | 11 段 | 同左 + **板块接力链（段 2a'，题材演化后）+ 龙头结构（段 4a，龙头档案前）** |

历史已 ok 文档（v1/v3/v5）**一律不重判**；回放另立预算确认（§5）。

## 4. 原料审计（§1.2.6 先行，2026-10-19 实测）

| 原料 | 覆盖 | 对本次改动 |
|---|---|---|
| 韭研 `jiuyan_action` final 池史 | 115+ 天（近连续） | 板块归属/家数/龙序/诞生轨迹主源；缺失日整段 fail-visible |
| 韭研 `num`「N天M板」 | 连板股均带 | 区间高度 M（龙序/总龙头）与跨度 N（首板日折算） |
| `jiuyan_streak_map`（真连板） | 依赖 THS 炸板池二分 | 情绪龙头；池缺失日全股 None → 情绪龙头不可算（如实披露） |
| `dragon_rows`（龙序单源） | 全池 | 板块龙头，与涨停复盘「领涨」列同源 |
| `day_status_of`（停牌分辨） | 依赖 TDX 日线 + 触板名单 | 更替退位原因、三日链存活口径 |
| `_pool_of` / `_boards_of` | 全池 | 家数与个股归属（**双口径**：家数按全部归属、个股取首个板块） |
| TDX 日线 `_daily_bars` | offset=60/250、取「现在」 | **本方案刻意不消费**（诞生轨迹只读韭研池史），回放历史日不受「日线取现在」缺口影响 |

## 5. 预算与执行（15 日门 + 全量 108 篇均已于 2026-10-19 开火并验收，见 §14）

- 教科书路径：先 15 日（近 15 个交易日）复核分布与 §7 验收；再决定全量 108 篇
  （参照 v4/v5 实测 650–661K tokens ≈ $0.07；v6 叙事实测 4793 字符，较 v5 约 +30% → 全量预估
  **≈ 850–900K tokens ≈ $0.09**）。
- 执行：`--relay-day <日> --force`（单进程顺序；`questionSetVersion="v6"`，`replace_one` 幂等）。
- 重试规则：网络级失败（tokens=0/degraded）同批补跑一次；已耗 token 的解析失败**不自动重试**，
  如实落 degraded（2026-10-07 纪律）。
- **零调用干跑**：`--dry-run` 不调模型，用于实现期口径复核（§13）。
- 密钥走 `.env.local`（`JEV_TYPESAFE_KEY`/`JEV_CF_TOKEN`），不落新存储。

## 6. 预期分布（开火前预判，验收对照）

- 段 A：主线板块不应再被「其他/公告」吃掉（生产 10-16 实测：其他存活最多 → 已剔除，主线落「冰雪经济」）。
- 段 B：总龙头与情绪龙头**多数日**应为同一只（区间高度与真连板同向），妖股断板日分离并显式标注。
- 诞生轨迹：区间高度 M ≥ 2 且韭研 N 可解析的龙头，首板日应落在推算位置并与池史一致；不一致必披露。
- 整体：phase 分布不塌陷；`insufficient_evidence` 率**不升**；ρ 不升。

## 7. 验收标准（全部可测，缺一不可）

**回放前（pre-replay，本轮已完成）**

1. **单源与标的自洽**：总龙头 / 情绪龙头 / 龙头档案 / `relayStructure.totalLeader` 四处为**同一标的且数值一致**；
   `relayStructure` 与叙事逐字段一致（单源，测试锁）。
   注：**最高板（真连板口径）与总龙头区间高度 M 是两个已登记口径**（设计 §9），允许不同，
   但两侧必须各自标注为「真连板」/「区间 N天M板」——不要求四处同一数值（2026-10-19 review P1-1 修正）。
2. 缺料路径（链日韭研 final 缺失 / 历史不足）写「不可算 + 原因」，禁 0 伪装（测试锁）。
3. 前端 4 子视图可切、无 JS 错误、旧代文档显「旧代未采集」；`relay_page` 全脚本 `node --check` rc=0。

**回放后（post-replay，待开火）**

4. `insufficient_evidence` 率不升（对照同窗 v5）。
5. `ρ(relay_index, day_temperature)` 不升（v5 长窗基线 0.487；>0.90 判失败）。
6. 分布不塌陷：phase ≥3 档出现，或与 v5 同窗形状同构。
7. 回放窗内 status=ok 全绿；缺料日按设计降级披露（不静默）。
8. 主线板块抽检 ≥5 日与人工核对一致（含存活 0 日降级路径、含泛板块剔除路径）。

## 8. 测试策略（全 mock，禁真实 jev 调用，AGENTS §1.2.7）

`tests/hotlist/test_jev_relay_index.py`（65 → **84** 例）：
`relay_structure` 主线=存活最多/并列降级、**链不可算 → 存活/晋级写「不可算」且行内禁 `0 只`**
（review P1 回归，断言同时覆盖有/无空格两种形态）+ 链可算真零写「0 只」、总龙头与情绪龙头同/异、
**无 int streak → sentimentLeader=None 且 sameStock=None**（不回落区间 M）、诞生轨迹 N−1 推算
（TDX 全空也可算）+ 首板股当日（`tradingDaysAgo=0`）/超窗 fail-visible、
**更替三态（延续/断板退位/sealed 位次被超越/停牌跳过）**、泛板块剔除、`theme_ladder_lines(mainline=)`
强制纳入且不重复、新段缺位归 `anchorGapsDerived` 且不抬主锚、
**v6 判据快照锁定（四题关键词 + 三题未动 + 枚举/打分锚零变动）**、叙事与落库 `relayStructure` 单源一致。

`tests/hotlist/test_jev_version_stamps.py`：`QUESTION_SET_VERSION_RELAY == "v6"`。

`tests/hotlist/test_relay_page_window.py`（+4 例，静态源码守卫 + node 纯函数探针）：
leaders 子视图接线与 ≤2 卡、只读 `relayStructure` + 旧代 fail-visible + 可重试、前端
`PSEUDO_BOARDS`/`SECTOR_BASIS_CN` 与后端**同源**、`rangeTextOf`/`streakText` 文案派生。

`tests/hotlist/test_jev_relay_index_api.py`（+1 例）：投影边界——`relayStructure` 只随单日 `day`
下发，序列行必须剔除（该文件 `FakeCol` 真按 projection 裁剪，可直接断言）。

回归：`pytest -m hotlist` 全绿；`pytest --collect-only` 无 import 破坏；调度链序断言不受影响。

## 9. 前端同步（§1.2.5，同轮交付）

- `backend/relay_page/index.html` 新增第 4 个子视图「板块与龙头」（`RELAY_VIEWS` + `rv-leaders`），**2 卡**：
  ①板块接力链（三日）表（板块/D-2/D-1/D0 家数·最高板/三日存活/今日晋级/连续top3/龙一；主线行徽标、
  泛板块徽标）②龙头结构卡（总/情绪龙头、一致性、升位关系、诞生轨迹、更替、降级披露）。
- 数据全取该日存档 `relayStructure`（与 JEV 叙事同一事实源，**前端不重算**）；v5 旧档无字段 →
  显「该日档案为 v5，未采集板块/龙头结构」+「旧代文档不回改，需重放该日」（fail-visible，不写 '-' 冒充）。
- 未预入缓存的选中行走既有 `relayDocFetch` 懒拉（失败哨兵可重试，三态不混同）。
- `GET /api/hotlist-jev/relay-index`：`day` 原样透出 `relayStructure`；`series` 投影**追加排除**
  `relayStructure`（序列只服务列表/图表，避免 400 日载荷膨胀）。既有 element id/路由/KPI 契约不动。

## 10. 明确排除（范围锁定，日后另立预注册）

1. 链长扩展（5 日/10 日链）：v4 §10 已排除，本文不重开。
2. 新增独立题目（如 `leader_structure` 档位题）：本轮用户裁决为「叙事 + 判据轻引」，不加题。
3. `leader_strength` 打分锚结构、`relay_index` 锚结构、其余 6 题档位枚举：不动。
4. 采集层（`snapshot_collector`）、存储合同（集合名/`_id`）、调度链序、`market_metrics`/ladder 口径：不动。
5. 历史文档（v1/v3/v5）不回改；未回放日的 v5 文档继续按 v5 文本被判据消费（序列对比必须按
   `questionSetVersion` 分层，relay_page 已有多版本 badge）。

## 11. 决策记录（用户 2026-10-19 裁决）

| # | 决策 | 结果 |
|---|---|---|
| D1 | 龙头体系口径 | **三个都按个股口径**（情绪龙头=当前真连板最高、总龙头=区间高度 M 最高、板块龙头=题材龙一）；不做「情绪龙头=板块」 |
| D2 | 主线/情绪龙头板块判定 | **可数口径：三日链存活股归属**（非当日家数 top1、非题材轮动引擎 MainlineScore） |
| D3 | 交付范围 | **叙事段 + 判据轻引 + 前端同步**（不加独立题目） |
| D4 | 回放范围 | 先 15 日门再全量：**两批均已于 2026-10-19 开火并通过（108/108 ok）**，见 §14 |

实现期新增（生产干跑驱动，非用户裁决）：**泛板块降权**（§2.1-8）与**首板日 N 推算**（§2.1-6）；
两者均为「让 §2.1 的可数口径成立」的必要修正，已在此登记并披露。

## 12. 回退

- 代码单 commit（文档同批），`git revert`；已落 v6 文档保留并带 `questionSetVersion="v6"`，
  前端旧代提示逻辑可直接服务未回放日；无需删库、无需数据迁移。
- 回退后调用点回到 v5 叙事（`relayStructure` 不再写入）；不重跑、不删文档。

## 13. 实现记录（2026-10-19）

- **代码**：`backend/operations/jev_relay_index.py`（`relay_structure`/`sector_relay_lines`/
  `leader_structure_lines`/`_leader_genesis`/`_sector_day_stat`/`_sector_top3_streaks`/`_leader_head_text`
  + `theme_ladder_lines(mainline=)` + `leader_profile_lines(total_leader=)` + `build_relay_narrative` 段序
  + `run_relay_index_day` 落 `relayStructure` + `_DERIVED_ANCHOR_GAPS` 两项）；
  `backend/analysis/hotlist/jev_relay_ammo.py`（v6 + 三题 instructions）；
  `backend/api/hotlist_jev_routes.py`（series 投影排除 `relayStructure`）；
  `backend/relay_page/index.html`（leaders 子视图）。
- **零调用干跑复核（生产库，2026-10-16）**：叙事 **4769** 字符、`relayStructure` **4965** 字节、
  `anchorGaps`/`anchorGapsDerived` 均为空；主线=**冰雪经济**（依据三日链存活股归属最多；
  泛板块「其他」存活/家数更多已排除）；总龙头=新华传媒(600825) 14天11板·真连板11·公告板块·板内带动4只·
  热榜第4名；情绪龙头与总龙头**为同一只**；升位关系=不是主线板块龙一 → **龙头与主线分离**；
  诞生轨迹=首板 09-21（**13** 个交易日前，N−1 口径）→ 区间 14天11板（区间内断板 3 次）→ 当前真连板 11；
  更替=10-15 总龙头澳弘电子 → 今日换龙头（旧龙头今日断板）。与同篇「高位股多日轨迹」「题材梯队表」
  「龙头档案」逐项一致（无审计 #2/#3 族自相矛盾）。
- **测试（genesis 归因修复后实测）**：`test_jev_relay_index.py` **87 passed**；`test_relay_page_window.py`
  **45 passed**（含 v6 新增 6 例：视图接线/单源+旧代可见/常量同源/链不可算静态锁/渲染真执行/纯函数）；
  `test_jev_relay_index_api.py` 4 passed（含 v6 投影边界 1 例）；`test_jev_version_stamps.py` 通过；
  `pytest -m hotlist` **718 passed**；`pytest --collect-only` **3846 collected** 无 import 破坏；
  `relay_page` 全脚本 `node --check` returncode=0。
- **10-15 抽检（review 期间零调用干跑）**：叙事 4837 字符、struct 5066 字节；主线=大消费（三日存活 2 只）、
  `sameStock=false`（总龙头与情绪龙头分离）、诞生轨迹 18 个交易日前（09-11）、两 anchor 表均空——
  与同篇盘面事实/龙头档案逐项自洽。
- **回放**：15 日门与**全量 108 篇**均已于 2026-10-19 开火并通过验收（§14；两批合计 807,887 tokens，
  108/108 ok）。历史判据代际文档（v1/v3/v5）未回改（v5 → v6 的落库文档已按设计覆盖重判）。
- **遗留**：①未回放日的「板块与龙头」页显「旧代未采集」（设计内）。②`_pool_of` 首个板块归属与
  `_boards_of` 全部归属的双口径在同篇内可能让「总龙头板块」与「主线板块最高板股」看起来不一致
  （10-16 实测：新华传媒在「公告/其他」双归属），已在段首披露口径；如日后要消除，需另立预注册做
  归属版本化。③`relayStructure` 增大约 5KB/日文档体积（实测 10-16 = 4965 字节；序列读口已排除，
  仅单日 `day` 载荷含它，108 天全量 ≈ 0.5MB）。④**查询放大（review P2，未修）**：`_sector_top3_streaks`
  被 `relay_structure` 与 `theme_evolution_line` 各调一次、`_pool_of`/`_boards_of` 对同一 `{date}:final`
  各读一次、`_promotion_stats` 重取已加载池——单日整档读较 v5 约 +30 次，**无新增外呼**（`_daily_bars`/
  除权日程均有缓存），批处理量级可忽略；日后要压沿 `_STREAK_CACHE` 先例加 (dataset,date) memo 即可。

## 14. 开火与验收执行记录（2026-10-19，用户预算确认后执行）

### 14.1 开火：15 日门

- **命令**：`python -m backend.operations.jev_relay_index --relay-day <15 个交易日> --force`
  （2026-09-18 … 2026-10-16；`questionSetVersion="v6"`；`replace_one` 幂等覆盖）
- **结果**：**15/15 `ok=True`**，无 degraded、无重试；实耗 **115,391 tokens**
  （预注册 §5 预估 ≈110K，偏差 +5%；逐日 7,411–7,800 tokens）
- **落库**：108 篇中 15 篇 `v6`（其余 93 篇仍 `v5`，待全量）；窗口 `anchorGaps` 全空
- **范围纪律**：只传显式 15 个 `--relay-day`，单进程顺序，无并行、无越窗

### 14.2 验收（零调用）——预注册 §7 post-replay 全项通过

**基线**：重放前 v5 落库态 = `data/backups/relay-v6-fullreplay-20261018-093429.log`（逐日 stdout）
+ `data/backups/hotlist_jev_relay_index_pre-longwindow-20261018-093424.jsonl`
（长窗只重放「变化日」，未在日志的 2 天由此归档补，同为 `v5`）。
**基线自校验**：未重放的 93 个对照日，DB `relayIndex` 与日志**逐日零漂移** → 基线可信，对照成立。
脚本/产物：`data/backups/relay_v6_sector_leader_acceptance.py`、
`data/backups/relay-v6-sector-leader-acceptance-<ts>.txt`（`data/backups/` 依 .gitignore 不入库）。

| §7 项 | 门槛 | 结果 |
|---|---|---|
| 7) 状态全绿 | 全部 `ok` | **15/15 ok**；版本 `{'v6': 15}`；主锚缺位 0 天（派生缺位 1 天 = 09-23「炸板面个股级」，v5 期既有缺口，非新段引入） |
| 4) IE 率不升 | 逐题 ≤ v5 | 相位 0→0、边际 0→0、梯队 0→0、钱效 0→0、题材 0→0（窗口为活跃期，两侧均无 IE；该门在本窗**弱通过**，全量回放再验） |
| 5) ρ 不升 | ≤ v5 且 <0.90 | pearson 0.721→**0.718**、spearman 0.779→**0.781**（n=15，≪0.90）；relayIndex 均值 44.3→45.4 |
| 6) 分布不塌陷 | 档位数不降 | 逐题持平：相位 3/3、边际 4/4、梯队 3/3、钱效 3/3、题材 2/2 |
| 8) 主线抽检 | ≥5 日人工核对 | 15 日逐日清单（产物 §6）；`basis` 全为 `three_day_survivors`（存活 1–4 只，无降级档）；泛板块剔除 4 天 |

**新段健康度**：`relayStructure` 覆盖 15/15；`chain.ok=False` 0 天；`genesis` 无缺；
`sentimentLeader=null` 1 天（09-23）且同日 `sameStock=null`；更替 11 天；升位分离（总龙头≠主线龙一）15 天。
**本窗无样本、仅单测覆盖的路径**：三日链不可算（缺料）、存活真为零的降级链、N 缺失走 60 日回溯。

### 14.3 附加：龙头独立口径对账（本预注册未要求，为自证实现无偏）

对 15 日**直读 `{date}:final` 原始字段**、用独立实现（不复用 `_pool_of`/`_day_eff`/
`_jiuyan_days_boards`/`_leader_*`）自算 argmax：总龙头 = M 最大 → 封板时间升序；
情绪龙头 = 真连板最大 → M 降序 → 时间升序。与被测代码落库值比对：

- **总龙头不符 0/15；情绪龙头不符 0/15**；15 日两侧**均无并列**（口径歧义为零）
- 09-23 两侧同时判「情绪龙头不可算（`null`）」，即缺料日不回落区间 M 的 fail-visible 路径
  **在真实数据上成立**（非仅单测构造）
- 抽查异动日自洽：10-16 总龙头 新华传媒(600825) 14天11板 与 新华文轩(601811) 同为 11 板，
  按「封板时间升序」(09:25 < 14:35) 取 新华传媒，独立实现同判 ✓

### 14.4 回退

`git revert` 判据与 `QUESTION_SET_VERSION_RELAY` 版本号即可；回放为 `replace_one` 幂等覆盖，
重放回 v5 需另批预算（本文 §12 已登记）。

### 14.5 全量回放（第二批 93 天）与全量验收

- **开火**：`data/backups/relay_v6_sector_leader_fullreplay.py`（显式日期表、单进程顺序、
  累计 token 上限护栏、网络级失败同批补跑一次、**已是 v6 且 ok 的日自动跳过**＝可断点续跑）
- **结果**：93/93 `ok`，无 degraded、无重试，实耗 **692,496 tokens**（24.7 min）
- **两批合计**：**108/108 ok，807,887 tokens**（15 日门 115,391 + 本批 692,496；预注册 §5 预估 850–900K）

| §7 项 | 门槛 | 全量结果（108 篇） |
|---|---|---|
| 7) 状态全绿 | 全部 ok | **108/108 ok**，版本 `{'v6': 108}`；主锚缺位 3 天（07-06/07-07/07-09，v5 期既有主锚缺口）；派生缺位 19 天 |
| 4) IE 率不升 | 逐题 ≤ v5 | 相位 3→**2**、边际 1→**0**、梯队 0→0、钱效 1→1、题材 1→1 —— **不升**（15 日门的「弱通过」此处转为实通过） |
| 5) ρ 不升 | ≤ v5 且 <0.90 | pearson 0.516→**0.500**、spearman 0.496→**0.496**（n=69，EOD 温度覆盖 69/108；§14.6 定向重放后复测）；relayIndex 均值 41.9→43.7 |
| 6) 分布不塌陷 | 档位数不降 | 相位 6/6、梯队 4/4、钱效 4/4、题材 3/3；**边际 5→4 的唯一差异是 `insufficient_evidence` 档消失（1→0 天）**，即塌陷判据不适用 |
| 8) 主线抽检 | ≥5 日 | 逐日清单见产物 §6；`basis`＝`three_day_survivors` 103 / `promoted` 3 / `chain_na` 2 |

**独立口径对账（108 天）**：**总龙头 0/108 不符、情绪龙头 0/108 不符**；唯一并列日 06-11
（情绪龙头 2 例并列），产品取 600500 与独立实现（真连板最大 → M 降序 → 时间升序）一致。
**全量产物**：`data/backups/relay-v6-sector-leader-acceptance-all-<ts>.txt`。

**fail-visible 路径在真实数据上被触发并正确披露**（15 日门无样本，本批补齐）：

- `chain.ok=False` **2 天**（05-06「2026-04-29/2026-04-30 韭研 final 缺失」、05-07「2026-04-30 韭研 final 缺失」）
  → 该两日 `mainline.basis=chain_na`，未落伪 0 ✓
- `sentimentLeader=null` **19 天**（THS 炸板池缺失 → 无可验真连板），同日 `sameStock=null` **19/19 完全一致** ✓
- `mainline.basis=promoted` **3 天**（三日链可算但存活真为零 → 降级到今日晋级股归属）✓ 降级链被真实触发
- 泛板块剔除 21 天；更替 84 天；升位分离（总龙头≠主线龙一）67 天

### 14.6 已修：`genesis.degraded` 归因顺序（2026-10-19，用户「请修复」授权）

**发现**（§14.5 全量验收）：41/108 天带 `genesis.degraded`，其中 25 天把**原料边界**写成了
「口径不一致」——违反 §1.2.6 归因顺序（先查原料再查题目/口径）。三类根因：

| 根因 | 天数 | 修复前 | 修复后 |
|---|---|---|---|
| A 快照交易日史不足（史起 2026-04-15） | 16 | 「首板日超出可取交易日史（需回溯 N 个交易日）」 | 不变（原本即正确） |
| B1 首板日早于韭研池史起点（2026-05-06） | 10 | 「…不在韭研池（…**口径不一致**）」 | 「…**早于韭研池史起点（2026-05-06 起）**，无法校验」 |
| B2 池史覆盖该日、但该股当日不在涨停池 | 15 | 同上 | 「…不在韭研池（首板日仅为推算；**或该股当日停牌**）」 |

**实现**：`_leader_genesis` B 分支改按 原料边界 → 池缺档 → 口径 三级判定，新增
`_pool_history_first_date(db)`（韭研 final 池史最早日，按 `_id` 尾「:final」取，与 `_pool_of` 同源，
仅降级路径调用 ≤1 次/日）。顺带去掉对 B2 的「口径不一致」预判（改为中性的「推算/停牌」候选）。

**测试**：新增 3 例分别锁三种归因（早于池史 / 池史内不在池 / 池当日缺档），并断言不含「口径不一致」；
`test_jev_relay_index.py` 84 → **87 passed**；`pytest -m hotlist` **718 passed**。

**定向重放**（该串进叙事=判据输入，须重放方能 code/DB 同源）：驱动
`data/backups/relay_v6_genesis_wording_rereplay.py`（范围=落库文案含「不在韭研池」的 25 天；
显式日期表、单进程、token 护栏、网络级失败同批补跑一次）→ **25/25 ok，实耗 186,780 tokens**（8.5 min；
预估 ≈19 万，偏差 −2%）。

**修复后复验**（零调用全量验收，`data/backups/relay-v6-sector-leader-acceptance-all-<ts>.txt`）：

- 落库归因分布 = B1 10 / B2 15 / A 16 / 无 67，**旧文案残留 0 天**；108 篇全 v6
- §7 各项不变向好：状态 108/108 ok；IE 相位 3→2、边际 1→0；ρ pearson 0.516→**0.500**、
  spearman 0.496→**0.496**；分布不塌陷；`basis` 存活 103 / 晋级降级 3 / `chain_na` 2
- 独立口径对账：总龙头 **0/108**、情绪龙头 **0/108** 不符
- 四批累计 token：115,391 + 692,496 + 186,780 = **994,667**（≈$0.11）
