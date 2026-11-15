# 竞价龙头 vA4：退役 jiuyan 龙序第二源（2026-11-15 用户裁决）

> 状态：**已实施**（代码 + 测试 + 展示同轮同步）。回退靠 git，不做库内备份。
> 前代：vA3（`auction-leader-vA3-preregistration-20261114.md`）；第三源预登记
> `auction-leader-trial-strength-source-preregistration-20261115.md`（其「题面 vA3 不动」
> 仅约束该轮第三源变更，不构成本轮永久锁）。

## 1. 裁决与依据

- **用户裁决（2026-11-15）**：删除竞价龙头第二数据链 `jiuyan_dragon_t1`
  （韭研 T−1 涨停分组龙一/龙二/龙三竞价打标），理由「实测封板概率极低」。
- **实测佐证（live 已结算，样本极小仅作方向参考）**：
  `auction_push` n=6 封板 1（16.7%）；`auction_push+jiuyan_dragon_t1` n=1 封板 0（0%）。
  jiuyan 源 2026-11-14 才投产，live 结算样本不足以统计显著；裁决以用户实测观察为准，
  样本局限在此披露（fail-visible，不伪造显著性）。
- **题面分叉裁决 = A**：升 vA4 清理判据（红线 6：判据不得引用叙事没有的证据）。

## 2. 选龙口径（vA4）

`auction_push`（基源）∪ `auction_trial_strength`（第三源，严格档板块前三）。
**第三源不单独触发**：推送缺席即 skip（不兜底选龙），与 vA3 语义一致。

## 3. 移除清单

| 层 | 移除 |
| --- | --- |
| operations | `jiuyan_dragon_roster`、`JIUYAN_DRAGON_MIN_SEALED`、run() jiuyan 并集/`_dragonPrimary`/`dragonRoles`/`jiuyanDragonState`/`selection.jiuyanN/overlapN` |
| analysis/ammo | `auction_dragon_line`、两叙事 builder 的 `dragon_line` 参、锚行第二桶 `nJiuyan`、身位题 instructions「韭研龙序」判据 |
| api 读口 | jiuyan roster 缺档行并集、`dragonRosterError`、投影 `dragonRoles` |
| relay 竞价表 | 韭研龙徽章 `dragonBad`/`dragonTxt`、领涨列 `alLeadRole`/`leadCell`/`th('领涨')`、默认改封板概率降序、colspan 15→14 |
| scripts/pilot | 仅注释优先级更新（`source_bucket` 单源共用） |

## 4. 保留清单（边界）

- **板块归属 ABM**（`auction_board_map`，jiuyan T−1 涨停分组）只用于**归因**，非选龙；
  push 股仍走 `resolve_leader_board`，保留。
- **第三源 trial 全链**（`auction_strength.trial_strength_roster`、root 粗桶、徽章）保留。
- **题材表龙序列**（relay `tlRowHtml`/`labelTable`，用 `dragon_rows`）属题材链自身证据，保留。
- `SOURCE_JIUYAN_DRAGON` 常量保留：**仅历史档 `selectionSources` 读取**用。

## 5. 锚 / 桶语义（vA4）

- `source_bucket` 互斥优先级改 `auction_push > auction_trial_strength > 退役 jiuyan`；
  重叠历史档归存活源；jiuyan 单源历史档返回退役桶。
- `auction_seal_base_rate` **不计入**退役 jiuyan 单源历史档（锚只反映存活源）；
  返回 `{n, rate, nPush, nTrial, start, end}`（删 `nJiuyan`）。
- 锚行叙事：`推送 a/竞价强度 b`（删「韭研龙」）。
- pilot `bySelectionSource`：jiuyan 桶仅历史代际档可见，vA4 起不再产生（fail-visible）。

## 6. 题面 / 版本戳

- `QUESTION_SET_VERSION_AUCTION_LEADER` **vA3 → vA4**；hash 由 `_questions_hash` 重算。
- 身位题 `auction_seat_durability` instructions 删除「昨日韭研龙序行」证据项与
  「/韭研龙序」判据项；判据「至少一项」仍可由梯队领先差/同板竞价对比/热度排名满足。
- `AMMO_VERSION_AUCTION_LEADER` **2026-11-15b → 2026-11-15c**。
- 封板题不引用龙序，未改；板块两题/硬度题原文复用 v17 不变。

## 7. 历史档与回退

- 历史 vA2/vA3 档（含 `dragonRoles`/jiuyan 源）**不迁移不删除**；读口不再投影
  `dragonRoles`，relay 不再渲染；pilot 按代际分组观察（跨代不可比）。
- 回退只靠 git（本轮单提交），不做文件副本/库内备份（§1.2）。

## 8. 验证

- `tests/operations/test_auction_leader_label.py`、`tests/api/test_auction_leader_route.py`、
  `tests/hotlist/test_relay_page_auction_leaders.py`、`test_jev_version_stamps.py`、
  `test_narrative_hygiene.py` 全过；新增 vA4 守卫：推送缺席第三源不单独触发、
  `source_bucket` 退役优先级、锚不计退役单源、relay 韭研龙/领涨列不回潮、14 列 colspan。
- 删除的 jiuyan 专用测试随功能退役移除（非守卫失配，属 intentional  removal）。
