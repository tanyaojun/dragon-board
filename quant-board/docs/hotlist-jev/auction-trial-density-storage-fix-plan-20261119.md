# 竞价试盘密度与序列存储修复实施计划（2026-11-19）

> 状态：**已实施（A/C/D + 生产迁移，2026-11-19 盘后）；B 已落地默认 off，待次日窗预登记开火**
> （本文是实施单一依据；按 §8 顺序逐件落地，同轮同步展示/测试/文档，AGENTS §1.2-5；实施记录见 §10）。
> 触发：603324 盛剑科技 11-19 早盘工作台试盘页 vs WzsLinker 对拍差异复盘。
> 关联：`auction-trial-source-survey-20261114.md`（Wzs 上游=KPL 盯盘 Type=7 服务端统计）、
> `auction-bidding-zero-trio-fix-plan-20261119.md`（trio 投影，已实施待重启）、
> `docs/kpl-socket/README.md` §3.7/§3.9/§3.10（本轮增补 §3.11 密度根因源码定案）。

## 0. 结论先行（根因三层，均已实证）

1. **密度根因（接收层，主因）**：collector 仅在 setup 发一次 2103 pid=8 请求，服务端按「请求-快照」回整页 burst，会话内无周期更新；会话 ~39s 被杀（`eof_clean`×248）→ 观测密度=每会话 1 burst（~36-37s），窗内仅 16 个观测事件（5s 理论 ~120），首帧 09:15:26 晚 25s。
   **App 源码定案（红线 9 依据，.tmp_review/jadx_out_signsvc）**：盯盘竞价页 `BiddingZTQuotaFragment`
   继承 `MVPTimerTaskFragment`→`BaseTimerTaskFragment`（默认周期 **3000ms**，`ag/cg→bg(i,3000L)`）；
   定时回调 `Xf(666)`→`Pg()`→`p.j0(firstVisible,count)`→`a0(i,i2,true)`→`y(2103,true)`
   （`SocketPresenter.y()`=`ux0.v().c(w).g(u(w)).f(true).d(k).e((byte)4)`，0x40 订阅通道重发请求）；
   滚动时 `fg(666)` 暂停、静止 `Zf(666)` 恢复。**即 App 靠 3s 定时重请求取密度，不是靠服务端周期推送**。
   我方缺这条 App 同款周期重请求 lane → 首开额/首加额/起止时点全部采样失真（603324 首帧已落峰值 1.94亿，真首开 1.54亿 在缺失窗内；首加额算成 09:17 反弹 delta 3983万，真首加 1396万 在开头几秒）。
2. **存储根因（写入层）**：`kpl_bidding_series` 单日单文档嵌入 ticks，实测 16,767,304B≈BSON 16MB 上限；tick 中位 26KB，`SERIES_MAX_TICKS=1200`×25.8KB≈31MB，注释「1200×~10KB≈12MB」估算错 → `$slice` 预算失效；午后进程 `bid_series_fail=749`（code 10334 拒写）、ok=1；11-18 档同样饱和。**密度修复（A 后 tick 量 ~2100/日）必须以存储重构为前提**。
3. **读侧旧进程（零值 trio）**：trio 投影源码 13:22-13:23 落地，:8000 启动 12:54:36 早于落地 → 运行旧链把「掉池未公布」当事实 0（603324 沪市撮合前掉池，MBL/bid 永久 0）。重启即消；投影值=掉池前虚拟观测 1419万/派生换手 1.10%（口径披露，≠Wzs 撮合终值 1925万，残留见 §7）。

语义/口径差（已登记、非 bug，本轮仅同步披露）：start/end=观测首末帧≠Wzs 试盘起止语义；circulated_value=real_float 实际流通≠Wzs 流通市值；竞价涨幅列=09:15 首帧≠Wzs end_time 快照。

## 1. 范围与非目标

**范围**：A 存储重构；B App 同款 pid8 3s 重请求 lane；C 重启+relay tooltip 投影口径同步；D 消费读口切换；测试与次日窗预登记验收；README §3.11 增补。
**非目标（残留登记 §7）**：会话 ~39s 被杀攻坚；3006 lane s0915/s0925 零捕获归因；盯盘 Type=7 撮合终值源接入（单主链裁决不变）；Wzs end_time 精确判据逆向。

## 2. 改动 A：kpl_bidding_series 逐 tick 文档化（单主链不变，单写者=collector）

契约（同集合 `kpl_bidding_series`，双形态同轮退役旧形态，红线 1）：
- **日 meta 文档** `_id=date`：`date/window/fields/last_ts/last_n/updated_at/tick_n` + 既有加字段 `open_pct/open_pct_state/prev_pct/prev_pct_state`（supplement/backfill 的 `$set` 写口零改动）。**不再含 ticks**。
- **tick 文档**：`{_id:ObjectId, date, ts, n, it:[{s,…8 字段}]}`，索引 `{date:1, ts:1}`。单 tick ≤~40KB « 16MB，append=insert_one，**无读改写、无 $slice、无 SERIES_MAX_TICKS**（常量与注释同轮删除）。
- `archive_bidding_series`：insert_one(tick) + update_one(meta, `$set` last_* / `$inc` tick_n, upsert)；失败结构化 reason+stats（fail-visible 不变）。
- `load_bidding_series`：meta=find_one(_id=date)；ticks=find({date}).sort([("ts",1),("_id",1)])；返回 `{**meta,"ticks":ticks}`（消费合同同形）；meta 与 ticks 皆无→None。同 ts 页序按 _id（页成员互斥，序不影响派生）。
- **迁移** `scripts/migrate_bidding_series_per_tick.py`：遍历含 ticks 数组的旧档（11-16..11-19 等）：①`mongoexport` 归档 `data/backups/`（红线 4）；②批量 insert tick 文档；③旧档 `$unset ticks`+`$set tick_n` 改写为 meta；④计数核对（tick_n==len(ticks)）。逐档显式操作、幂等可重跑；**先在 dragon_board_test 干跑**再生产。回退=重导入导出归档（git+归档双保险）。

## 3. 改动 B：App 同款 pid8 3s 重请求 lane（密度根因修复）

- 源码依据链见 §0.1（计划评审即红线 9 源码核对记录；README §3.11 同轮增补，含 jadx 路径与行号）。
- collector 新增 `_pid8_refresh` lane：**窗门控 [09:15,09:30)**（App「页可见且静止」语义的无头等价=竞价窗，披露）；每 **3s** 重发 pid=8 各页 2103 请求（帧形态与 setup 6d 完全同款：pkg0x40+ext `02 0837`、priority 前插逻辑复用）；帧间拟人停顿复用 C2/C3；会话重建随 setup 初始 burst 自然重置；**ErrResp 1002 → 既有 fail-fast+退避梯，不新增重试循环**。
- **频控预算（红线 10，注释入代码）**：7 页×1 帧/3s≈2.33 帧/s；窗 15min≈2100 帧/日；每页周期=App 静止刷新周期（3s），非客户端自创轮询；超预算只披露不静默。
- status 观测字段：`pid8_refresh:{enabled,frames_sent,last_ts,send_drops,window_active}`；`corpus_persist.bid_series_*` 既有。
- 开关 `KPL_PID8_REFRESH`：**实施轮默认 off** → 次日窗预登记开火（§6）验收通过后同轮翻默认 on+重启；异常（1002/rst 升级）env 关+重启即回退，**禁止盲搜参数**（红线 9）。
- 落库联动：2103 pid8 每帧即归档（既有钩子不变）→ 窗内 tick≈2100/日，逐 tick 文档无压力；derive 窗过滤/early-late 计数不变。

## 4. 改动 C：重启与披露同步（红线 5）

- 重启 :8000（落地 trio 投影：603324 jj_amount 0→14187008 src=mbl_col10_preexit、jj_turnover 0→1.0974 src=derived_cap、net=None 状态门）与 :8002（落地 A+B）。
- relay_page/index.html L10055-10066 jj 三列 tooltip 旧措辞（「MBL→bid 优先，缺位=序列末帧」）同步为投影状态机口径：`mbl_postmatch`（撮合公布）/`mbl_col10_virtual`（留池窗内虚拟）/`mbl_col10_preexit`（掉池前虚拟观测，≠撮合终值）/`derived_cap`（派生换手）/净额缺位 None 不烘 0；逐行 `jjAmountSrc/jjTurnoverSrc`  sub 行披露（与 open0925Src 同款形态）。
- 既有 start/end/first_add/circulated tooltip（L10027/10057-10066）保留不动。

## 5. 改动 D：ticks 直读点切换 load_bidding_series（合同同形，行为不变）

| 文件 | 读点 | 处理 |
|---|---|---|
| backend/operations/auction_bidding_facts.py L175 | find_one(_id=date) 取 ticks 佐证 | 改 loader |
| backend/api/hotlist_jev_auction_routes.py L570 | /auction-bidding-series 直读 | 改 loader |
| backend/services/market/trial_quote_supplement.py L53 | universe 取 ticks | 改 loader（projection 失效，全读 meta+ticks 可接受：日档 ~2100 tick×26KB≈55MB 内存瞬读？→ loader 增 `codes_only` 轻量读：find({date},{it.s:1}) 聚合 universe，避免全量 it 传输） |
| scripts/auction_window_check.py | find_one({"date":date}) | 改 loader |
| scripts/backfill_auction_price_tdx.py L79 | find ticks | 改 loader |

supplement/backfill 的 meta `$set` 写口（L78-84）零改动。derive/leader_label 已走 loader 零改动。

## 6. 测试与验收

**单元/回归（pytest 全量）**：
- test_kpl_bidding_series 改写新形态；**16MB 回归**：模拟 700 tick×26KB 连续 append 全 ok（旧形态必失败用例留作对照注释）；单 tick 超大（n=210）仍 ok；insert 失败 stats 留痕不阻断。
- 迁移测试：旧形态 fixture→迁移→tick_n 核对、幂等重跑、meta 加字段保留；test 库护栏（conftest 三断言）不变。
- derive/trio/facts/routes/leader_label 既有测试全绿（loader 合同同形）；supplement universe 轻量读测试。
- B lane 测试：mock socket，3s 节拍/窗门控/会话重置/1002 fail-fast/帧形态 pkg0x40+ext 断言（同 setup 6d 断言族）。
- relay JS：node --check 提取脚本或既有 `_relay_js_check.js` 同款校验。

**次日竞价窗预登记开火（红线 9/10，预算≤2500 帧，单窗）**：
- 开 `KPL_PID8_REFRESH=1` 重启 :8002；观察 status：1002/rst 计数 vs 基线不升级、`bid_series_fail=0`。
- `scripts/auction_window_check.py` 验收阈值更新：①首 tick ≤09:15:10；②窗内观测事件 ≥150；③gap 中位 ≤4s、max ≤15s（会话轮转上限）；④603324 类首开/首加与本地 kpl_auction_matched（KPL 直连盯盘 Type=7 终值档）对拍，纯本地零外呼（2026-11-19 全直连裁决清理 wzs）；值层收敛（首开差 ≤5%、首加同笔），档未落地结构化披露不伪 0。
- 验收通过→翻默认 on+重启+README §3.11 勾选；不通过→env off 回退，残留登记，**不盲探**。

## 7. 残留登记（不在本轮，另立预登记）

1. 会话 ~39s `eof_clean` 被杀（PC 适配残留）：B 落地后 pid8 密度不再依赖会话寿命；其余 lane 影响另评。
2. 3006 lane s0915/s0925 零捕获：TDX 开盘棒/series_first 回退已披露；归因另立。
3. 掉池股撮合终值（Wzs 1925万/0.58%）：盯盘 Type=7 HTTP 源为唯一现存源，接入需单主链裁决+频控登记，本轮不接；虚拟观测口径披露。
4. Wzs end_time/final 精确判据（服务端试盘结束统计）：勘察 §4 待窗内定案；我方观测末帧语义 tooltip 已披露。

## 8. 实施顺序与回退

1. A 存储重构 + D 读口切换 + 迁移脚本（test 库干跑）→ pytest 全绿。
2. C tooltip 同步 + 重启 :8000（trio 落地，零值消除）→ API 对拍 603324。
3. 生产迁移（export 归档→逐档改写）→ window_check 读口验证。
4. B lane（默认 off）+ 测试 → 重启 :8002 → 次日窗预登记开火验收 → 翻默认 on。
5. README §3.11 增补（源码链+预算+验收结果）同轮落。
回退：git revert；B=env off；存储=重导入 data/backups 归档；C=重启旧 commit。

## 9. 假设与默认

- 假设服务端对 2103 每页 3s 重请求与 App 同款受理（源码假设，开火验证；1002 即停）。
- 默认 storage 形态=逐 tick 文档+日 meta（技术裁决：append-only 时序标准形态，消费合同经 loader 同形，迁移有界）。
- 默认 B 先 off 后 on（预登记方法论 §3.7）；窗门控 [09:15,09:30) 为 App 页可见语义的无头等价（披露）。
- 历史已丢 tick 不可恢复（同 11-18 披露口径），当日派生首开/首加不作交易判据。

## 10. 实施记录（2026-11-19 盘后，18:49-19:30）

**顺序偏差披露**：§8 原序「生产迁移在 :8002 重启前」会有旧写者竞态（旧 collector
仍 $push 嵌入 ticks，export→$unset 间隙丢 tick）→ 实际执行：代码+测试全绿 →
停 :8002（单写者离线）→ 生产迁移 → 同批重启 :8000/:8002（新代码，B 默认 off）。
盘后 18:49 执行，竞价窗零损失；其余顺序与 §8 一致。

**落地清单**：
- A：`kpl_daban_archiver` archive/load 重构（SERIES_MAX_TICKS 删除；insert_one+
  `$inc tick_n`；load 同形 + codes_only）；迁移脚本 `scripts/migrate_bidding_series_per_tick.py`
  （预检 :8002 在位拒跑/--force；mongoexport 归档先行；幂等清部分重插；计数核对）。
- D：facts/routes/supplement/window_check/backfill 五读点切 loader；**额外发现并修复**
  routes 日期索引 `find({}, {_id:1})` 会把 tick 文档 ObjectId 混入 dates → 改
  `{it:{$exists:False}}` 只取日 meta（backfill 默认日期列表同款）。
- B：collector `_drain_pid8_refresh`（3s 节拍/窗门控/setup 同款帧形/会话重置/
  fail-fast）+ status `pid8_refresh` + serve `KPL_PID8_REFRESH` 默认 0。
- C：relay jj 换手/成交额 tooltip 投影状态机口径 + jjAmountSrc/jjTurnoverSrc sub 行
  （KPL_BID_TRIO_SRC 标签复用）；start/end/first_add/circulated tooltip 保留不动。
- 测试：test_kpl_bidding_series 改写新形态（含 700×26KB 16MB 回归/n=210 超大/
  insert 失败留痕/meta 加字段保全/loader 同形+排序/codes_only）；新增迁移测试 5 例、
  pid8 lane 测试 7 例（tests/hotlist/test_kpl_pid8_refresh.py）、supplement 轻量读例、
  relay tooltip 守卫例；共享假库 tests/series_fake.py（旧 fixture 适配新形态）；
  derive/facts/leader_label/routes/supplement/backfill 既有夹具同步新形态。
  **全量 pytest：5372 passed, 7 skipped, 0 failed**（工作区含协作者其他改动，
  基线数与 trio 轮 5502 不同源）；relay JS node --check 通过。
- 迁移：dragon_board_test 干跑+实跑验证（合成档 2099-01-01，验后显式清理）→
  生产三档（11-17:6 / 11-18:835 / 11-19:647，合 1488 tick）全 ok，归档
  `data/backups/kpl_bidding_series_legacy_dragon_board_quant_2026-11-1{7,8,9}.json`。
- 重启验证：:8002 status `pid8_refresh.enabled=false`；:8000 API 对拍 603324
  jj_amount=14187008/src=mbl_col10_preexit、jj_turnover=1.0974/src=derived_cap
  （零值 trio 消除，与 §0.3 预期逐值吻合）；/auction-bidding-series tickN=647；
  window_check --date 2026-11-19 读口验证通过（旧稀疏数据①②③ ❌ 属预期，
  密度验收待 B 开火窗）。
- 文档：README §3.11 增补（源码链逐行核对：BiddingZTQuotaFragment.java:49/495-497/
  440-450/100-104、BaseTimerTaskFragment.java:76 bg(i,3000L)、
  BiddingZTlQuotaPresenter.java:261-262/174-188、main_src SocketPresenter.java:193
  e((byte)4)；预算+预登记开火步骤）。

**待办（次日竞价窗）**：按 README §3.11 预登记开火（KPL_PID8_REFRESH=1 重启 ：8002，
预算 ≤2500 帧/单窗）→ window_check --matched 四项验收 → 通过翻默认 on+重启+勾选；
不通过 env off 回退残留登记，不盲探。

## 11. 复审轮（2026-11-19 盘后，双 fresh-context 只读 reviewer 并行）

**结果：0 blocker，7 valid non-blocker（6 修复 1 记录），2 speculative（均记录）**。
正面确认：帧形态与 setup 6d 逐字段一致、与 1002 fail-fast 链无冲突、status 五字段齐、
relay tooltip 与 derive 枚举/转义对上、README §3.11 源码行号全部实读核实、测试零真实外呼。

修复（同轮落地并补测试）：
- S1 loader 旧档透传守卫：未迁移旧嵌入档原样返回（显式 "ticks" 键不再覆盖嵌入
  数组伪装空档）；codes_only 从嵌入 ticks 派生 codes（不空宇宙）。
- S2 迁移归档完整性：`_export_legacy` 接收 expect_lines，已存在归档行数不符删旧
  重导；本轮导出失败删残留；migrate_one 二次行数校验，不符该档记失败不改写
  （红线 4）。
- S3 写路径幂等建 {date:1,ts:1} 索引（进程级缓存；全新库/重建测试库不再漏建）。
- S4 日期列举改 `{_id:{$type:"string"}}`（走 _id 天然索引，不再 $exists:false 全扫；
  routes+backfill 同改，series_fake 补 FakeObjectId 仿真与 $type 判别）。
- S5 meta $inc 失败单次 best-effort 重试，再败返回 write_failed:meta_update
  （tick 已入库不丢数据；重复 $inc 仅漂移 audit 计数，注释登记残留风险）。
- L1 pid8 部分发送成功帧计入 frames_sent（观测面不少计）+ 部分失败断言。
- L2 长寿会话 registry 增长边界入 lane 注释登记 + README §3.11 开火观察项
  （sub_registry.evicted_n）。

记录不修：S6 --matched falsy 0 分支无自动化测试（脚本级诊断，次日窗才启用）；
L2 主体（改注册语义需红线 9 源码定案，开火窗先观察）。
