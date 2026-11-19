# 竞价龙头调度器三缺陷修复方案（D1+D2+D3，用户裁决 2026-11-19「A+B+C 全做」）

> 新对话实施入口文档。先读：`AGENTS.md`（§0/§1.2/§4.0）、
> `docs/hotlist-jev/auction-trial-direct-probe-preregistration-20261116.md` 增补一/二/三、本文件全文。

## 0. 事故定案（证据，2026-11-19）

- :8001（`backend/collector_main`，Redis 单实例锁）是 **scheduler 唯一宿主**；:8000 不跑 scheduler。
- 12:33:10 launcher 全栈重启 → 12:33:40 第一个 tick 即补跑（status：`attempt=1, leaders=2, okCount=2, tokensUsed=11234`）→ 12:35:49/50 落库 2 个新 leader：`002122 ST亚洲（机器人）`、`600156 华升股份（算力）` → 前端算力板出现「晨间 002197 + noon 600156」双龙头。
- 机制三缺陷：
  - **D1** `scheduler.py` `state = {"date": trading_date, "done": set()}`（~L629）纯内存 → 任何重启后 `first_run=True`；`_auction_leader_last` 同为内存 → `retry_due` 也失真。
  - **D2** 槽条件只有 `now.time() >= _AUCTION_LEADER_LABEL_AT`（~L695）**无上界** → 任何时刻重启都补跑（noon 投喂 + 烧 jev token）。
  - **D3** run 内 `todo = selection − 当日 ok-docs`（`auction_leader_label.py` ~L920-924）逐股幂等，但**选择每次重算** → 晨间跑后数据被修正（本日 case：TDX open_pct ~10:3x 回填，jj_percent 不再吃成员制早退值）→ per-board top1 漂移 → 新 top1 作为新增 doc 落库（加法漂移）。

## 1. 修法

### A. 日级 run 状态持久化（治 D1）
- 状态doc（至少）：`{_id: "auction_leader_label:<date>", firstRunAt, attempts, lastOk, lastResult(截断), lastAt, updatedAt}`。
- 落库通道（已勘察定案）：无可复用通道（missed-slot 走的 `record_run` 是快照槽专用；
  无 `kpl_collector_events`）→ 新集合，且因三链 helper 化共用**单一集合**
  `hotlist_jev_label_run_state`（方案原文单链集合名 `hotlist_jev_auction_leader_run_state`
  不采纳），doc `_id="{chain}:{date}"`，单写者=scheduler，遵守 §1.2-1/4。
- 判定改造：`first_run` = 「持久化层无当日 ok/已跑标记」（内存 `state["done"]` 降级为缓存）；`retry_due` 用持久化 `attempts/lastOk/lastAt`。写入时机：每次执行 run 前后（before: attempts+1 预写；after: lastOk/lastResult/lastAt）。
- **同构推广（建议同轮）**：`theme_leader_label`（~L768）、`fengkou_red_obs`（~L740）是同款内存 first_run/retry 模式 → helper 化（`_persisted_first_run(key,date)` / `_persisted_retry_due(key,date,…)）一次落地三链；若求最小改动则只修 auction 链、其余列残留，二选一在实施时定（推荐 helper 化，改动等价）。

### B. 窗上界（治 D2）
- 新常量 `_AUCTION_LEADER_WINDOW_END = datetime.time(9, 35)`（首跑 09:25:20 + retry_after 5min 的重试 09:30:20 在窗内；09:35:20 的第二次重试出窗）。
- 门控：执行条件加 `and now.time() < _AUCTION_LEADER_WINDOW_END`；**窗外一律不跑**（含重启后 first_run 场景），并落结构化披露：run_state doc 标 `abandoned_window`（或复用 missed-slot 事件通道），`logger.info` 留痕。
- `_AUCTION_LEADER_MAX_ATTEMPTS=3` 语义不变（含被窗拒绝的记账）；实际窗内最多 2 次尝试（09:25:20 / 09:30:20）。重试日 ≥09:30 出 MBL 窗 → MBL 审计 `skipped_out_of_window` 披露（既有行为，不放宽，维持预登记）。
- 不放宽 MBL 窗、不动 vA1 题集/投喂语义（本次只动调度层）。

### C. 当日选择冻结（治 D3）
- 新集合 `hotlist_jev_auction_leader_selections`：`{_id: "<date>", rows: [{code, board, boardSource, selectionSources, trialStrength, pct…}], unionN, slot, frozenAt}`。单写者=label run；§1.2-1 唯一源。
- `run()` 改造：选择段前先读冻结档——
  - 有 → 直接以冻结 rows 为人群（板籍/来源/trialStrength 快照原样），**不再重算 union/排名**；派生字段（jj_percent、ammo、basis 等）重试时照常取最新库值（人群冻结、数据新鲜，兼得）。
  - 无 → 正常选择，**成功执行后写冻结档**（首跑即冻结）。
  - `dry_run` 不写冻结档；`force` 单股重跑保持现语义（可跑任意 code，不受冻结限制，返回态披露 `forcedOutsideSelection`）。
- settle（16:10）与锚行/复盘链不读冻结档，不受影响。
- 冻结的意义：晨内重试即使 open_pct 等数据在 09:25:20→09:30:20 之间补齐变化，人群也不再漂移；数据修正只能影响次日选择（这正是 09:26 deadline 的本意）。

## 2. 实施顺序
1. `backend/snapshot_collector/scheduler.py`：A 持久化 helper + B 窗门控 + `_AUCTION_LEADER_WINDOW_END`。
2. `backend/operations/auction_leader_label.py`：C 冻结读写（load/save + run 选择段改造 + 返回态增 `selectionFrozen: bool`）。
3. 测试（新增 `tests/operations/test_auction_label_scheduler_state.py`，风格对齐 `test_auction_label_parallel.py` 的假库/monkeypatch harness）：
   - A：持久化 ok 标记在场时，内存 state 清空（模拟重启）→ 不再 first_run；lastOk=false + retry 间隔满足 → 才重试。
   - B：模拟 `now=09:36` → 不执行 + abandoned 披露落库；`now=09:30:20` 重试在窗内可执行。
   - C：冻结档在场时，人为篡改底层选择原料（如 open_pct 变化）→ 重试人群不变、不加新股；首跑写档；dry_run 不写；force 不受限并披露。
4. 文档同轮（§1.2-5）：预登记文件追加「增补四：调度器三缺陷定案与 A+B+C 修复」+ 本方案文件若实现有出入同步修正。

## 3. 待用户裁决（开工前问清）

> 2026-11-19 实施时按方案内建默认落地，裁决记录：
> 1. 今日 12:35 两个 noon doc（002122/600156）：**本轮未处置**（与实施无依赖，doc 自带
>    computedAt=12:35 可辨；待用户裁决导出归档后单文档 drop 或保留审计）。
> 2. A 落库通道：勘察后无可复用通道 → 新集合，三链 helper 化故共用单一集合
>    `hotlist_jev_label_run_state`（`_id="{chain}:{date}"`），单链集合名不采纳。
> 3. 同构推广：三链 helper 化一次做完（方案推荐项）。
> 4. lastResult 存结构化 dict（非 JSON 串）；codes 单股重跑不写冻结档；force 绕过冻结档
>    重算人群且不覆写，forcedOutsideSelection 相对重算人群披露。

## 4. 生效与实弹验证

> 2026-11-19 已实施，详见预登记增补四
> （`auction-trial-direct-probe-preregistration-20261116.md`）；测试
> `tests/operations/test_auction_label_scheduler_state.py` 12 例 + auction/theme/fengkou
> 既有套件全绿。
- **重启 :8001**（槽间隙执行、零推送损失；:8002 推送不在该进程）。注意：当前 8001 进程还缓存着 1+2 之前的旧 label/scheduler 代码，本轮 A+B+C 落地后必须重启才全部生效（1+2 + A+B+C 一并载入）。
- 实弹判据（11-20）：
  - 09:25:20 首跑触发；`selections` 冻结档当日落库；leader computedAt ≤09:26。
  - 首跑后人为/自然重启 :8001 → **不再补跑**（run_state ok 标记在场）。
  - 重试（若首跑失败）09:30:20 在窗内、人群=冻结档；09:35 后不再执行。
  - timings 逐相在场（1+2 并行相）；mblState ok/parallel_pending；plateSrcN 回退计数可见。
  - `status` 端点 `/api/snapshot-collector/scheduler/status` 的 `auctionLeader.attempt` 跨重启不回退（持久化生效）。

## 5. 验证命令
```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m pytest tests/operations/test_auction_label_scheduler_state.py tests/operations/test_auction_label_parallel.py tests/operations/test_auction_leader_label.py tests/api/test_auction_leader_route.py -q
.\.venv\Scripts\python.exe -m pytest            # 全量（~17min），提交前必跑
# 重启 8001 后：
curl http://127.0.0.1:8001/api/snapshot-collector/scheduler/status
```

## 6. 边界与红线核对清单
- 单写者：run_state/selections 只有 scheduler/label run 写；drop/清理只走显式单集合操作 + 先导出归档（§1.2-4）。
- fail-visible：窗外放弃、冻结档缺席（首跑前）、run_state 读写失败都结构化披露，不静默。
- 测试禁真 jev/真网络（§1.2-7），全 monkeypatch/假库。
- 不动 vA1 题集、不动 MBL 窗、不动 _in_auction_window 定义。
- 临时产物放 `tmp/` 用完即删；提交只 add 明确路径。
