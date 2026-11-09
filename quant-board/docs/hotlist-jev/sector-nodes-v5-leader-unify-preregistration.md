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
