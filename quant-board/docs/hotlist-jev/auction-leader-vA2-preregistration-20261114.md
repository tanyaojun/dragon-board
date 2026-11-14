# 竞价龙头打标链 vA2 预登记（2026-11-14）：选龙双源（KPL 推送 ∪ 韭研涨停分组龙一/二/三）

> 状态：裁决冻结（2026-11-14 用户三点确认）；代码落地与本文同轮（红线 5）。
> 基线 = `auction-leader-vA1-preregistration-20261113.md`（vA1 已于 11-13 真实开火
> 12 条 live doc：7 个股 + 5 板块）。vA1 未覆盖的骨架（09:26 挂链/退避/六件套/补源/
> 结算/幂等/单只重跑/relay rv-auction）全部沿用，本文只登记增量与换代。
> 真实 jev 开火仅走 `--confirm-budget` / 预登记日包络挂链（AGENTS §1.2-7）；
> 一切自动化测试 mock jev，禁真调用。

## 1. 动机

vA1 选龙单源 = 09:15「竞价看龙头」推送（典型 7–10 股），只覆盖 KPL 直播编辑视角；
昨日资金主战场（韭研涨停打标链各板块龙一/二/三）不在推送内时，晨间链对昨日主线
龙头的当日封板/身位判定整段缺席。用户裁决（2026-11-14）：**加上 jiuyan 涨停打标链，
各板块（涨停家数 ≥3 家）的龙一/二/三**。

## 2. 裁决记录（2026-11-14 用户确认）

- B1 **阈值 = 官方封板口径涨停家数 ≥3 家**（含 3；「超过3家以上」裁决为 ≥3）。
- B2 **家数口径 = 官方封板口径，不含炸板股**：韭研触板分组 − THS 15:00 炸板池
  （含尾盘回封补证，`_reseal_verdict` 单源）− ST/北交所剔除（`_official_exclude`）。
  实现复用 `jiuyan_board_info` 的 zhaban/excluded 旗标（单一事实源，禁第二套二分）。
  **THS 炸板池缺失 → 封板家数不可验证 → jiuyan 源整源缺席**（宁缺毋猜，不回退触板
  口径——回退会把炸板股混入，违反 B2），`jiuyanDragonState.reason=ths_pool_missing` 留痕。
- B3 **推送缺席日照跑 jiuyan 单源**（vA1 A4「推送缺席=零调用」收窄为「双源均缺席=
  零调用」）：推送**验证后**缺席（归档成功无条目/历史日不可回放）且 T−1 龙股在场 →
  照常投喂，`auctionPushState.reason` 留痕；**晨间取数 fetch_failed 仍 ok=False 交
  3×5min 退避**（即使 jiuyan 源在场也先重试，瞬时抖动不吃掉推送样本；重试耗尽当日
  双源皆失，与 vA1 同）。
- B4 **时点 = T−1 final**（09:26 当日 final 未生成，与 A4b 板块映射同因同窗）；
  龙序复用 `dragon_rows`/`jiuyan_board_dragons` 单一事实源（高度 M 降序 + 封板时间
  升序，与 relay 题材梯队表/涨停复盘「领涨」同口径）。**龙序不排除炸板股**（B2 只
  约束板块达标家数）：炸板高位股仍是昨日高度龙，其「炸板」事实行内标注，当日封板
  判定恰需覆盖断板反包/弱转强场景。
- B5 **题集换代 vA2**：身位题判据「同板推送股」→「同板入选股」（双源后推送股不再是
  同板对比全集），证据枚举与硬规则①补「昨日韭研龙序行」；封板题/催化题/板块两题
  原文不动。hash 变 → 跨代不可比，vA1 的 12 条 live doc 不与 vA2 混算模型指标；
  基础率锚是结局统计（非模型答案），vA1 已结算样本可入 vA2 锚人群（按源构成披露）。
- B6 双源并集按 code 去重：推送股保留推送 pct/概念桥映射（A4b 不变），龙序并列披露；
  jiuyan 单源股板块归属 = 龙序主板（多板龙序按**封板家数降序 → 组名升序**确定性取主，
  A4b 同序无推送桥），`boardMapping.pickedBy=dragon_t1`。

## 3. 选龙合同（A4e，替代 vA1 A4 单源条款）

```
roster = push_stocks(当日 09:15 推送) ∪ jiuyan_dragons(T−1 final)
jiuyan_dragons = { 龙一/二/三(b) : b ∈ T−1 final 分组, sealed_n(b) ≥ 3 }
sealed_n(b) = |{ s ∈ b.stocks : ¬zhaban(s) ∧ ¬excluded(s) }|   # jiuyan_board_info 旗标
```

- 每股结构化 `selectionSources ⊆ {auction_push, jiuyan_dragon_t1}`、`dragonRoles`
  （全部龙序成员：{board, role, boards, days, time, sealedN, zhaban?}，确定性序）。
- 非题材行政桶剔除（`digest.is_not_a_theme`，含「其他」桶）对双源同规，仅日志留痕。
- 推送 pct 仅推送源有；jiuyan 单源股 `auctionPct=None`（09:15 试盘价不可得，不伪造）。
- 历史日 backfill：推送不可回放，但 jiuyan T−1 final + bid 日档在库 → **backfill 可跑
  jiuyan 单源**（sampleOrigin=backfill，不得当前瞻结论；腾讯补源仅当日窗，历史日
  榜外股六件套缺席留痕）。

## 4. 题集 vA2（冻结全文见 `backend/analysis/hotlist/auction_leader_ammo.py`）

- `auction_seat_durability`：instructions 证据枚举「昨日梯队/结构行、**昨日韭研龙序行**、
  同板**入选股**间竞价高开与竞价额对比、热度排名行、题材热度行、板块判定行」；
  硬规则①点名事实集补「韭研龙序」；硬规则②/criteria 中「同板其他推送股」→「同板其他
  入选股」。其余措辞不动。
- `auction_leader_seal_today` / `leader_catalyst_hardness` / 板块两题：原文不动
  （板块两题与催化题仍 import v17 单一事实源）。
- `QUESTION_SET_VERSION_AUCTION_LEADER = "vA2"`；
  `AMMO_VERSION_AUCTION_LEADER = "2026-11-14a"`（语料供给 + 题面措辞换代）；
  hash 登记 `tests/hotlist/test_jev_version_stamps.py`。

## 5. 语料合同（增量）

- 新增行 `auction_dragon_line`：「昨日（T−1）韭研涨停分组龙序：X板龙一（N天M板，
  封板 hh:mm，板涨停 K 家）、Y板龙二（…）」；炸板股龙序行内标「炸板」（触板时点）；
  显式 boards=1 标「首板」（与 relay `_range_height_text` 同口径，review N1）；
  字段缺位 = 缺位字段不出现；无龙序（纯推送股）整行缺席。过 `test_narrative_hygiene`。
- `auction_board_structure_line`：「推送 N 只」→「入选 N 只」（双源成员全集）。
- `auction_base_rate_line`：锚行补人群构成「n 样本：推送 a/韭研龙 b」（双源股归韭研龙
  桶；vA1 旧档无 selectionSources 按推送计）。锚计算口径不变（滚动直算防 look-ahead）。
- 板块级叙事补板内龙序行（成员 dragonRoles 中本板条目）；jiuyan 单源板无推送行
  （整行缺席）。个股级行序：板块归属 → 推送行（run 注入）→ 龙序行 → 竞价行 → …。
- 其余复用 vA1 §4（六件套/补源/T−1 语料/龙虎 T−1/证据块），零新采集。

## 6. 预算与频控（红线 7/9）

- 调用包络 = Σ(入选板块数 + 入选股数)/日。**实测（2026-11-14，生产库只读，官方封板
  口径 ≥3）**：近 6 交易日达标板 4–10 个（均值 6.8）、龙股 12–30 只（均值 20.5）；
  11-14 当日 roster = 推送 7 ∪ T−1(11-13) 龙 15（重叠 1）= **21 股**；「其他」行政桶
  剔除后典型 **≈30 调用/日，峰值 ≤45**（vA1 典型 14–20）。tokens 上限仍以
  `estimate_tokens` 干跑估算写入挂链日志；`--max-leaders` 截断护栏沿用。
- 外部取数：直播晨间 1 次/日（st=100）不变；**jiuyan 源零新增外呼源**——
  `jiuyan_board_info`/`jiuyan_board_dragons` 全为库内读（jiuyan_action T−1 final +
  snapshot_frames T−1 15:00 THS 池）；回封补证走既有 `_daily_bars`：**本地 vipdoc 优先**，
  陈旧补尾受既有 `bars_need_upto` 声明约束（晨间链未声明 → 不补尾）；**本地缺文件股
  回退既有线上 mootdx 日线**（既有源非新源：进程内缓存 + 全节点不可用 5min 负缓存，
  日量 ≤ T−1 炸板池命中数，实测约 13/日；晨间链与读口 API 同此预算，review M1 修订）；
  竞昨比原料 ≤**入选股数**/日（原 ≤推送股数）；腾讯竞价补源窗 [09:25,09:30)、
  ≤3 批/日、每批 1 条批量 URL 不变（缺码集扩至双源 roster；09:30 后重试槽补源失效
  为 vA1 既有约束，不变）。无新增 socket/轮询源。
- 结算零 token（16:10 挂链）与验收口径沿用 vA1 §5；**pilot eval 按 questionSetVersion
  分代评估**（vA1 样本量 7 股/1 日，单独披露不混算）。

## 7. 存储与 API 合同（增量）

- leader doc 增 `selectionSources`/`dragonRoles`；sector doc `segmentRows` 增
  `sources`/`dragonRole`（本板龙序）；`boardMapping.pickedBy` 新值 `dragon_t1`。
- run 结果增 `jiuyanDragonState`（{t1Date, countCaliber:"sealed_official", minSealed:3,
  t1Final, thsPoolFound, boardsQualified:[{board,sealedN,touchN}], dragonN, reason?}）
  与 `selection`（{pushN, jiuyanN, overlapN, unionN}）；stdout 标记行合同不变
  （ok/skippedReason/errorCode 语义沿用，调度解析零改动）。
- `GET /api/hotlist-jev/auction-leaders` 行源 = labels ∪ 推送 roster ∪ **jiuyan 龙
  roster**（读口按需调同一 `jiuyan_dragon_roster` 实现，禁第二套；日期集 = live 归档
  日 ∪ labels 日，单 date 模式即该日；计算失败 `nodeFilter.dragonRosterError` 留痕
  不阻断 labels 清单）；行增 `selectionSources`/`dragonRoles` 透传。读口 per-request
  逐日重算（与 limitup 读口既有模式同款，日线进程内缓存；无结果缓存，进程重启后
  首轮轮询集中计算，review N6 披露）。
- relay rv-auction：行增「韭研龙」源徽章（title 披露龙序）；「推送缺席」徽章仅对
  推送源行显示（jiuyan 单源股推送缺席是预期态，不告警）。

## 8. 失败模式（fail-visible，增量）

- T−1 final 缺席 → jiuyan 源缺席 + `reason=t1_final_missing`，推送源照跑；
- THS 炸板池缺失/降级 → jiuyan 源缺席 + `reason=ths_pool_missing`（B2 宁缺毋猜）；
- 无 T−1 交易日 → `reason=no_prev_date`；
- 推送验证缺席 + jiuyan 在场 → 跑 jiuyan 单源（B3）；双源均缺席 →
  skippedReason=auction_push_missing + 双状态留痕，零调用；
- push fetch_failed → ok=False 退避重试（不论 jiuyan 是否在场，B3）；
- jiuyan 源个股三层证据缺失 → 封板题程序门 insufficient 同 vA1（置信门不放宽）；
- 读口 jiuyan roster 计算失败 → dragonRosterError 留痕，labels/推送 roster 不受阻。

## 9. 影响文件与验证

- `backend/analysis/hotlist/auction_leader_ammo.py`（vA2 题面/龙序行/锚构成/板结构行）
- `backend/operations/auction_leader_label.py`（jiuyan_dragon_roster/并集/双源留痕）
- `backend/api/hotlist_jev_auction_routes.py`（行源 ∪ jiuyan roster/字段透传）
- `backend/relay_page/index.html`（rv-auction 源徽章）
- `scripts/auction_leader_pilot_eval.py`（evaluate 分代披露 byQuestionSetVersion，B5）
- 本文 + vA1 文档取代注记；`tests/hotlist/test_jev_version_stamps.py`、
  `tests/hotlist/test_narrative_hygiene.py`、`tests/operations/test_auction_leader_label.py`、
  `tests/api/test_auction_leader_route.py`、`tests/hotlist/test_relay_page_auction_leaders.py`
- 验证：`pytest tests/operations/test_auction_leader_label.py tests/api/test_auction_leader_route.py
  tests/hotlist/test_jev_version_stamps.py tests/hotlist/test_narrative_hygiene.py
  tests/hotlist/test_relay_page_auction_leaders.py tests/operations/test_auction_leader_schedule_parse.py`
  （全 mock jev 零网络）+ 当日 `--dry-run` 零调用核对双源叙事。