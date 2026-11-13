# 板块节点 v5 预登记：板块龙一口径统一（2026-11-09）

## 裁决

**用户裁决（2026-11-09 盘后）**：板块龙一三处口径不一致（以商业航天板块为实证）：

| 消费链 | 11-09 商业航天龙一 | 口径 |
|---|---|---|
| 涨停打标链（driver_labels） | 顺灏股份（002565） | `day_leader_rows(space_mode=True)` 空间龙一 |
| 题材龙头链（theme_leader_label） | 顺灏股份（002565） | `day_leader_rows(space_mode=True)` 空间龙一 |
| **板块节点（sector_nodes）** | **润贝航科（001316）** | `day_leader_rows()` 默认真连板口径 ← 异类 |

统一方向：**板块节点改用空间龙一**（与另两链同参），三处龙一单源同一只股。

## 变更内容

1. `operations/sector_nodes.py settle_day`：today/prev/prev2 三处 `day_leader_rows`
   全部切 `space_mode=True, pool_dates=<该日前 3 个交易日>`（与题材龙头链
   `leaders_for` 同参：韭研 final 日轴升序取 3 日回溯池）。
2. 分轨折叠：space_mode 下每板块 ≤2 行（main/growth，v12），节点表只出一只龙一——
   `_collapse_segment_rows` 主板轨优先，纯双创板块取 growth 行。
3. 版本号 `SECTOR_NODE_VERSION` v4→v5；节点判据（NODE_ORDER/判档条款）本身不动，
   但判据里引用的龙头续断（day_status_of）随之按空间龙一判，节点档可能重判。

## 被覆盖的旧裁决

2026-10-27 预登记 §21.6：空间龙一「仅当日标注链启用，sector_nodes 等维持 streak
口径（历史样本人群不随规则换代漂移）」。本次用户裁决显式覆盖该条；板块节点文档
自 v5 起为空间龙一，历史 v4 及以前档保持 streak 口径（version 字段如实区分，
不回填改史）。

## 已知影响（fail-visible）

- 节点档可能变化：空间龙一断板日仍在池（leaderSealedToday=False），其 streak=None
  → 龙头断板判定与真连板口径不同，wzs/退潮/冰点/转弱引用龙头续断的板块可能改档。
- TDX 10 日涨幅拉不到的板块：沿用 day_leader_rows 空间模式既定行为——该板块跳过 +
  `meta.spaceErrors` 披露（不降级旧规则）。
- 台账/读口消费（`/api/hotlist-jev/theme-leaders` 行源 join）因三处龙一统一，
  (date, code) 命中率上升。

## 已知局限（评审补充，如实登记）

1. **交易日轴差**：settle_day 的 `trading_dates_before` 来自 jev_label_jiuyan
   （snapshot_frames half_hour 轴），题材龙头链 `leaders_for` 同函数但韭研 final 轴
   语义——单侧数据缺日时两处池日期可能分叉，表现为 leaders_for driftBoards → 当日
   打标链跳过（fail-visible，不产错标）。轴统一留待后续裁决。
2. **历史可见性收窄**：theme-leaders 读口行源=节点档，≈2026-10-24 之前的无档日期
   不再返回行，仅 `nodeFilter.datesWithoutSectorNodes` 计数披露（裁决预期）。
3. **leader 台账事实键**：gain10/leaderSealedToday/segment/poolDay（histStreak 是
   pool 候选内部键，不入行，已从扩容清单移除）。

## 回退

git 回退本提交；板块节点集合按 `version` 字段区分代际，重跑幂等覆盖当日档。

---

## v5.1 增补（同日，三链合一落地）

用户裁决：涨停打标链、板块节点、题材龙头打标三链合一——龙一只算一次落一次库，
三处打同一只龙头标，不再各自推导。落地内容：

1. **龙一台账行扩容**：assemble_rows 的 leader dict 携带空间龙一完整事实字段
   （gain10/leaderSealedToday/segment/poolDay/histStreak）——一次计算全字段，
   下游零重复推导。
2. **新增共享读口**（operations/sector_nodes.py）：`ledger_leaders(db, date)`
   （档缺失/非 ok/非 v5 → None，消费方 fail-visible 不回退）与
   `reanchor_dragons`（梯队表/领涨列龙一重锚，龙二三 dragon_rows 补位）、
   `anchor_rows_to_ledger`（advisory 事实行锚定过滤）。
3. **题材龙头打标候选换源**（theme_leader_label.leaders_for）：候选=当日节点档
   v5 龙（main 轨单龙，growth 轨不再打标）；day_leader_rows 同参重算仅取结构
   事实行按 (board, code) 过滤；节点档缺失/非 ok/非 v5 → 拦停不回退自推导；
   drift/dropped 逐项披露。reconcile 现任基线随之锚定节点档。
4. **盘后链链序**：sectorNodes 从 relayIndex 后提前到 phasePulse/jiuyanLabel 之前。
5. **梯队表/领涨列龙一重锚**：relay 题材梯队表、limitup 读口「领涨」列龙一槽位
   =节点档龙一；龙二三 dragon_rows 补位（排除同 code）；断板反包龙一（今日未封）
   如实注记；档缺失回退原口径 + 表头注记。
6. **下游 advisory 锚定**：leader_wzs / theme_cycle / sector_pulse（昨日龙一）在
   有 v5 档时按档过滤龙一行，无档（深历史回填）保持原推导并如实披露未锚定；
   theme_cycle 的 ledgerAnchor 随 inputs 落痕。sector_pulse 的 _day_pool_direct
   （boardCodes 封板池，非龙一身份）不变。
7. **读口**：/api/hotlist-jev/theme-leaders 出全部有龙头节点行（四节点过滤废除，
   打标范围与台账一致），nodeFilter 改为 nodeDist/labelMissingRows/labelOrphanRows/
   datesWithoutSectorNodes/nodeDocsTruncated。

**打标范围变化**：growth 轨不再打标（主轨单龙）；行政桶排除不变。**token 影响**：
日常调用数不变；重采漂移日对账补标 1-2 次（≈10K）；2026-11-09 验证重跑候选与
已打标 (date, code) 全一致，幂等零消耗（relay --force 重验梯队表产生一次 relay
相位判定 ≈9K tokens，如实记入当日成本）。

## 2026-11-13 用户裁决 B 方案（根因修）：每股每日单板块归属

**现象/根因**：space_mode 候选池=当日封板池∪近 3 日同名板块封板池，无单归属约束 →
迁移股（韭研逐日换板块）在旧/新板块候选池同时排第一 → 一股两板块龙头（11-12 实证：
天普股份 半导体+AI硬件、闽发铝业 光伏+其他）；节点判据消费错误龙头（旧板借别板续板
判「龙头续板」），投喂链同股同日重复烧 jev（`_id={date}:{code}` 后写覆盖，label board
落旧板）。缺陷在候选池归属层，消费侧去重（A 方案）治标不治本，用户裁决 B。

**三口径（用户确认默认）**：① 单归属复用首板块约定（`_pool_of`/`_promotion_by_board`
同源，不新造口径）：当日在池取当日首个出现板块，当日缺席取最近在池日首板块；
② 断板反包本意保留（断板龙一仍留归属板块在列，`dayStatus=broken` 下游消费），
`classify_board_day` 判据表零改动——纠正的是其输入；③ 历史不自动重放：新落档
`meta.leaderAttribution`（version=`single-board-20261113` + `multiBoard` 归属裁决留痕，
fail-visible），历史档无此键=裁决前口径，重放另裁（rerun 路径现成）。

**落地**：`theme_leader_baseline.day_leader_rows` 仅 space_mode 启用（今日 `boards_of`
单归属过滤 + 往日并集按归属过滤；历史 streak 口径不漂移，预登记哲学）；`sector_nodes`
settle_day meta 透传。读口/投喂链/前端零改动，继承纠正后台账（「龙一只算一次」延伸为
「只算一次、只归属一板」，同股同日重复投喂源头消失）。测试
`tests/hotlist/test_leader_single_board_attribution.py`（迁移股只当选新板/断板龙一留
归属板/同日多板取首板/历史口径不漂移）；广域回归 2040 passed；11-12 只读回放：
半导体→天普、AI硬件→超颖电子（当日成员另选）、其他→常铝股份，龙头码当日唯一。
