# 竞价龙头打标链 vA1 预登记（2026-11-13）

> 状态：题面冻结待批准；代码落地 P2–P4 与本文同轮（红线 5）。
> 真实 jev 开火仅走 `--confirm-budget` / 预登记日包络挂链（AGENTS §1.2-7）；
> 一切自动化测试 mock jev，禁真调用。

## 1. 目标与业务场景

KPL 大盘直播每个交易日 09:15 推送「竞价看龙头：板块+个股名单」（含个股竞价涨幅芯片）。
本链在 **09:26**（9:25 集合竞价冻结 + :8000 archiver ≤60s 轮询 lag 保障；失败限次退避）
以该推送为**选龙单源**，投喂 jev 判「竞价龙头当日封板概率 / 催化硬度 / 竞价身位」+
板块级「炒作深度 / 延续性」，补齐现有题材龙头 17:30 链拿不到的**晨间竞价时点判定**与
**T−1 龙虎主榜**消费（主榜生成窗 (23:42, 00:12]，00:30/07:10 补齐链保障次晨可得）。

与题材龙头链关系：完全独立集合 `hotlist_jev_auction_leader_labels`、独立题集代际 vA1；
复刻骨架（dry-run/estimate/confirm-budget/幂等/单只重跑/stdout 标记行）与 relay_page
展现方式（新增【竞价龙头】子视图 rv-auction），不复用选龙口（sector_nodes 为盘后产物）。

## 2. 裁决记录（2026-11-13 用户确认）

- A1 触发 09:26；每日最多 3 次、间隔 ≥5 分钟退避（镜像 17:30 链规则另立常量）。
- A2 题集删除 `leader_headroom`（空间题依赖当日封板后高度/空间锚，盘前无当日锚，
  空间判断留在 17:30 链）与 `leader_rebound_popularity`（弱转强事件门以当日收盘封板
  确认为前提，9:25 不成立）；不单独设「竞价强度」题（折入封板题判据）。
- A3 板块级两题进晨间链，沿用 v12 A2 拆题（每板块 1 调用 + 每股 1 调用）。
- A4 选龙单源 = 09:15 推送 stocks；**不允许** bid 通道兜底选龙；推送缺席日 = 当日
  无竞价龙头判定 + `auctionPushState` 结构化留痕（零调用）。
- A5 env `AUCTION_LEADER_LABEL_ENABLED` 默认 "1"（镜像 THEME_LEADER_LABEL_ENABLED）。
- A6 龙虎榜消费 **T−1** 主榜+席位+机构，行内显式标注榜单日期；当日榜整行缺席留痕。
- A7 `kpl_live_daily` 改 merge-union（共享 helper 单实现、晨间/17:30 两调用点；
  **17:30 当日恒取数 + merge，归档优先仅历史日**——2026-11-13 review blocker 修复：
  晨间档在场时早退会冻结题材语料于 09:26、丢 15:00 大盘综述），
  17:30 不再覆盖晨间归档；题材龙头直播语料供给因此可能增加 09:15 条目 →
  `AMMO_VERSION_THEME_LEADER` 换代 `2026-11-13a`（纯语料供给修复，题面 hash 不动）。
- A8 基线行不复用题材链 `baseline_line`（其口径=隔日续板率，与当日封板题不同锚）；
  晨间锚 = `auction_seal_base_rate`（已结算竞价龙头当日封板率滚动直算，防 look-ahead）；
  无已结算样本 → 锚行整行缺席，封板题锚缺席时 confidence ≤0.6（镜像 v13 规则）。

## 3. 题集 vA1（冻结全文见 `backend/analysis/hotlist/auction_leader_ammo.py`）

- 板块级（原文复用 v17，一字不改）：`theme_speculation_depth`、`theme_continuation`。
- 个股级：
  - `auction_leader_seal_today`（重写自 leader_nextday_continue）：当日封板概率四档
    （<25 / 25-45 / 45-65 / ≥65）+ insufficient；竞价五件套行=唯一量化判据源
    （缺席/不可考不得调档不得补 0）；锚偏离须点名锚行数字+锚外新证据；
    三层证据同时缺失判 insufficient（程序门同口径）。
  - `leader_catalyst_hardness`（原文复用 v17）。
  - `auction_seat_durability`（修改自 leader_seat_durability）：T−1 梯队领先差 +
    同板推送股间竞价高开/竞价额对比 + 热度排名；枚举 core/contested/relay/insufficient。
- hash：`QUESTION_SET_HASH_AUCTION_LEADER = _questions_hash(QUESTIONS_AUCTION_LEADER)`；
  版本戳登记 `tests/hotlist/test_jev_version_stamps.py`。

## 4. 语料合同（复用 + 新增 + 整行缺席）

复用（单一事实源读口，零新采集）：
- 当日 bid 日档五件套（`kpl_daban_pool` bid_items，9:25 冻结；`load_day(lane="bid")`）；
- T−1 gene/notice/题材热度/涨停原因（`kpl_daban_pool` 各语料通道读口）；
- T−1 结构事实（`day_leader_rows(T−1)` 命中 roster 代码时复用结构/梯队行；未命中=
  非昨日龙头，结构行改 T−1 池档事实：昨日封板/首封时点，高度不可考最简标注）；
- T−1 龙虎主榜+席位+机构（`collect_lhb_facts(T−1)`，行内标注榜单日期）；
- 当日题材证据块（`build_theme_evidence_block(date=当日)`，08:45 盘前事件/日历已在库）；
- 当日 09:15 推送原文+每股竞价涨幅（`auction_push_line`，新增行）。

新增行：`auction_push_line`、`auction_bid_line`（五件套+同板对比）、
`auction_structure_line`（T−1 事实）、`auction_board_structure_line`（板块级）、
`auction_base_rate_line`（锚）。全部纯数据事实，过 `test_narrative_hygiene` 黑名单。

整行缺席（§1.2-8，缺席只进 `corpusState` 结构化字段）：当日封板质量/当日梯队/
当日炸板面/当日跌停/当日涨停原因/当日龙虎榜/空间锚/隔日续板基线。

## 5. 预算与频控（红线 7/9）

- 调用包络 = Σ(板块数 + 推送股数)/日；典型推送 7–10 股 ≈ 14–20 调用/日；
  tokens 上限以 `estimate_tokens` 干跑估算写入挂链日志（`estimatedTokensBudgetGuard`）。
- 外部取数预算：直播 HTTP 晨间 1 次/日（**st=100**，2026-11-13 用户裁决：实测 st=60
  午后窗仅回溯到 09:51 覆盖不到 09:15 竞价播报；请求次数不变仅单发 payload 增大）
  + 17:30 既有 1 次/日（st=60，与晨间档 merge-union 互补全日）；
  bid/zb/dt 已订阅零新增；LHB T−1 四端点：子进程冷缓存恒 HTTP（30s TTL），
  晨间链每日新增 ≤4 次既有端点请求（有界、非新源；2026-11-13 review 修订措辞）；
  无新增 socket 订阅、无新增轮询源；重试退避上限见 A1。
- 结算零 token：16:10 挂链 `run_auction_leader_settle_once`（lookback 5 日自愈），
  `outcomeSealedToday` = 当日 daban pool **pool_state=sealed** 成员（炸板 broken 不算封板，
  与 kpl_lead_service 权威口径同；2026-11-13 review major-2 修复）；THS `sealed_and_info`
  交叉披露 `outcomeSource`/`outcomeCross`；池/THS 双缺 → None 待结算（fail-visible）；
  degraded 档不混入模型指标（单独 degradedDocs 计数，镜像题材链验收口径）。
- 验收：≥20 交易日后分档真实封板率差 ≥15pp 且 Brier 优于基础率锚
  （`scripts/auction_leader_pilot_eval.py`，镜像题材链验收口径）。

## 6. 存储与 API 合同

- 集合 `hotlist_jev_auction_leader_labels`：`_id={date}:{code}`（docKind=leader）/
  `{date}:board:{board}`（docKind=sector）；字段镜像题材链 + `auctionPushState`/
  `corpusState`/`lhbState`(T−1)/`outcomeSealedToday`/`outcomeSettledAt`/`outcomeSource`/
  `auctionSealToday`/`auctionSealProbabilities`/`auctionSeatDurability`。
- `kpl_live_daily` 增投影字段 `auctionPush`（解析 roster；单一事实源仍为直播归档 items）。
- `GET /api/hotlist-jev/auction-leaders`（date | start/end | with_narrative=1；
  500 档上限+truncated；行源 = labels ∪ auctionPush roster，缺档行 labelMissing 披露）；
  `POST /api/hotlist-jev/auction-leaders/rerun`（force 单只，computedAt 真重判校验）。
- relay_page：连板指数子视图 `rv-auction`【竞价龙头】（RELAY_VIEWS 增行），
  复刻 rv-themes 三分法/区间共用/60s 静默轮询/叙事抽屉/重跑/缺席徽章。

## 7. 失败模式（fail-visible）

推送缺席/解析全失败 → ok + skippedReason=auction_push_missing + 留痕，零调用
（标记行统一 main 打印，调度解析不误重试）；**晨间取数失败（fetch_failed）→ ok=False
交 3×5min 退避**（瞬时抖动不吃掉整天样本，2026-11-13 review major-5）；
bid 档 missing → 竞价行整行缺席 + corpusState 留痕，其余照投（**不触发重试**；
2026-11-13 review 裁决：与 §1.2-8 整行缺席哲学一致，原「bid 未刷新退避重试」措辞作废）；
非交易日/开关关 → 门控跳过；历史日 backfill → 直播不可回放同 A4，
sampleOrigin=backfill 不得当前瞻结论；板块归属 None → 个股题照投（置信门）、板块题跳过披露。