# 双题集生产化预登记 · 第一步：9-10 月全量回填（2026-10-12 用户裁决开立）

> 性质：**生产观察轨道登记 + 全量回填执行**。判据/对照锚/落库合同零改动（同 hash 同代际，
> v1 判据跨批次累计可比）。用户指令即开火批准：「维持jev强，上生产登记，先全量跑9-10月，
> 已跑幂等跳过」。

## §〇 登记依据（验收链全景）

1. **3 日 pilot**（09-07/18/30，60 例，83,297 tok）：三门全过，用户裁决「从行情数据结果上看，
   jev 判定比规则判定强太多」（jev-vote-confirm-lifecycle-recheck-preregistration.md §十）；
2. **10 日扩窗**（09-18～10-09，104 例，新采 89,241 tok）：门①③过，台账 A agree 75.0%
   （买侧 40/40 全一致，分歧全部集中在量价红牌层）、B agree 72.5%（11 例分歧中 10 例=
   规则放行 vs jev 反转），用户再裁决「**维持 jev 强**」（§十一）；
3. 本登记 = 生产化第一步：把抽样验收升级为**全量观察轨道**，先回填 9-10 月全量台账；
   展示层接线（行情列表 UI）另行预登记。

## §一 全量口径（冻结）

- **窗口**：2026-09-01～10-12 内全部 23 个交易日（half_hour 15:00 帧存在日；9 月 21 日+
  10 月 2 日，数据实测 230-255 股/日全覆盖）；
- **人口（不抽样）**：A = synergy 档 ∈ {S,A,B,D} 全量 **3131 股·日**；B = 非 cooling 全量
  **1044 股·日**；合计 **4175 call**；
- **幂等**：已跑 ok 文档（A 76 + B 48 = 124 例）done-skip 自动跳过，**新采 ≈4051 call**；
  失败/degraded 文档不视为已完成，重跑自动补齐；落库 replace_one 幂等，重复执行零副作用；
- **帽位**：全量口径显式放大至人口上限（`--vote-cap-buy/sell 200`、`--lc-cap-igex 100/
  --lc-cap-total 200`，实测最大单日人口 buy 58/sell 140/B 86）；默认帽（8/4/8）仅 pilot
  抽样用，生产回填不适用。**（LC 帽位已被 §六·产·七修「取消抽样帽」取代，2026-10-14）**

## §二 预算与执行参数（冻结）

- **预算**：新采 ≈4051 call × ≈1.38k ≈ **559 万 tokens**；CF 通道单价 ≈$0.0001/次，
  实际成本 ≈ **$0.41**（与 v2.5 九月全窗重跑 91 万 tok 同一成本量级做法）；
- **熔断**：`--token-fuse 6000000` 显式放宽（pilot 默认 150k/次不变——护栏语义=单次运行
  熔断线随批次预算走，预算在预登记报备）；
- **并发**：`--workers 4`（jiuyan 先例默认 2，取 4 保守；pymongo replace_one 线程安全）；
  预计耗时 ≈35-45 分钟；
- **串行/缺省路径零变化**：不传参数时 workers=1、fuse=150k，与 pilot 行为逐字节一致。

## §三 产出（跑后回填 §四）

- 全量台账：agree/diverge 按日披露；分层重点=**A 量价红牌层**（引擎 sell vs jev buy 的
  结构层，扩窗 24 例中 16 例分歧）与 **B 规则放行-jev 反转层**（扩窗 11 例分歧中 10 例）；
- riskFlag/escape 统计；degraded/失败清单（幂等补齐）；
- 9-10 月全量台账落集合：hotlist_jev_vote_confirm_pilot / hotlist_jev_lifecycle_recheck_pilot
  （集合名沿用 pilot 命名，生产展示层接线时另行正式命名迁移——本批不改名避免破坏对照）。

## §四 边界

- jev 与规则投票引擎 = **并列观察者**（2026-10-08 裁决不变）：不回写引擎、不进候选池、
  不进交易路径；全量台账是观察证据，不是权威判定；
- 展示层接线（行情列表 UI 呈现 jev 读数/置信度/分歧标记）**另行预登记**；
- 测试零真实调用零网络不变。

## §五 执行记录

- [x] **开火（2026-10-12，分三段幂等续跑）**：A 批 3131/3131 全量 ok（首段 1h 超时断在 09-15，
  幂等续跑补采 1455 例零重复计费）；B 批 966 新采+48 跳过=1014 ok。**零 degraded、零 no_frame**。
  总耗 **≈566 万 tokens**（预估 559 万 ✓；成本 ≈$0.57 量级）。
- [x] **全量台账（9-10 月，4145 ok + 30 留痕）**：
  - **A（3131 例）：agree 2598 = 83.0%**。分层：
    - 买侧（引擎 buy）**816/839 = 97.3%** 一致；
    - 卖侧按量价档分层：**D 档 1209/1210 = 100% 一致**（真看空完全合拍）、B/A 档 100%、
      **E 红牌档 319/737 = 43%**——全部 533 例分歧中 418 例集中在红牌层（引擎硬风险语义压成
      sell vs jev 读方向，pilot 阶段已定性的结构面全量版）；C 档 68%；
    - 分歧型：sell→buy 358、sell→hold 152、buy→sell 15、buy→hold 8；
    - 置信带：高 2210 / 中 601 / 低 320。
  - **B（1014 例 ok）：agree 723 = 71.3%**。分歧 291 例最大族：
    - **「规则放行 vs jev 反转」103 例**（expansion→reversal 52 + ignition→reversal 51，
      华瓷股份模式的全量版）；
    - 相邻段分歧：reversal→crowded 70、expansion→ignition 23；反向（规则反转 jev 扩散）30；
    - 置信带：高 379 / 中 410 / 低 225。
  - **门3 escape ✅**：B data_insufficient 30/1044 = **2.9%** ≤10%；A 0%。
- [x] degraded/失败与补齐：零 degraded；首段超时断点由幂等续跑补齐，零重复计费。
- [x] **门②用户验收（2026-10-12 裁决）：「维持 jev 强，全量版验收通过」**——9-10 月全量台账
  正式验收。至此双题集验收链闭环：3 日 pilot（60 例）→ 10 日扩窗（104 例）→ **9-10 月全量
  （4145 例）三轮均裁决 jev 读数强于规则读数**；两大系统性分歧面（量价红牌层 418 例、
  规则放行-jev 反转层 103 例）全量验证与抽样轮结论一致。
- [ ] 下一步（待用户指令）：①挂自动链（每日收盘后全量台账 ≈6000 tok/天）；②展示层接线预登记
  （行情列表 UI 呈现 jev 读数/置信度/分歧标记）。

## §六·产 帧级口径修正案（2026-10-12 用户裁决，二修定案：每日两帧=上午收盘 11:30 + 下午收盘 15:00）

> 演进：原口径只跑 15:00 一帧 → 一修「每帧落库后即跑」（10 帧/日）→ **用户二修定案：
> 每帧跑不合理、只跑 15:00 也不对，每日两帧=上午收盘 + 下午收盘各一次**。
> 判据/对照锚/落库合同零改动（_id 本含槽位，多帧天然共存）；用户指令即开火批准。

- **口径（定案）**：每日跑 **11:30 帧（上午收盘定格）+ 15:00 帧（全天定格）** 各一次全量判读。
  11:30 帧当日轨迹恰好 5 槽，B 题集预检线（≥5 槽，**已被六修取代**）正好放行——上午收盘即有生命周期复核。
- **实现**：runner 增 `--slot`（帧级参数化，默认 15:00 保持回填兼容）+ `--watch` 常驻轮询
  （槽表=WATCH_SLOTS(11:30,15:00)，每 60s 检查，帧级运行标记防重；帧未落库/非交易日
  no_frame 零成本跳过；进程重启无损）。**不碰 snapshot_collector 采集进程**。
- **盘中/上午帧原料演化（fail-visible 预期行为）**：11:30 帧共振维需 ≥9 棒日内历史，
  当日仅 5 棒 → 共振 status=insufficient 如实标注（趋势/热度/量价三维照常判，
  预检「有效维 ≥2」仍过）——上午帧天然缺共振维，属原料事实不伪装。
- **预算（每日两帧）**：≈360 call/日 ≈ **50 万 tok/日 ≈ $0.036/日**（较一修每帧方案省 7 倍）。
- **挂载方式**：`python -m backend.operations.jev_vote_confirm --watch --workers 4 --token-fuse 6000000 --include-cooling`
  由计划任务/Launcher 拉起常驻；kill 即停，重启无损。
- **B 预检线六修（2026-10-12 用户裁决「LC 几十只无判定」）**：68 只午后上榜股
  （当日轨迹 1-4 槽）被「轨迹槽 ≥5」预检线全挡——逐一核实其**跨日度量 100% 可算、
  引擎 stage 全部有值**，判段原料基本齐备；预检线 5→2（有走向变化点即可判，缺槽在轨迹行
  如实标缺，riskFlag=partial 列「当日轨迹仅N槽」）；**10-09 15:00 帧已补**：65/68 例
  ok（首跑帽 200 截断 44 例，放大帽幂等续跑补齐），LC 覆盖 247/250=98.8%，余 3 只
  当日轨迹 <2 槽（尾盘进池极端例）真·原料不足如实留痕；VOTE 250/250。
- **A 人口含 E 档（五修，2026-10-12 用户裁决「扩到②」）**：36 只 synergy E（环境门一票否决）
  股 VOTE 显示 `--` 逐一核实后用户裁决纳入全量人口——判据环境门「只注记不投票」，jev 方向
  读数独立成立，「周期否决 × 方向偏多」= 观察否决是否误杀的样本；对照锚 E→sell；判据零改动。
  **10-09 15:00 帧 E 档 36 例已补**（5.7 万 tok），VOTE 覆盖 **250/250=100%**。
- **A 人口全量覆盖（四修，2026-10-12 用户裁决「250 只池 VOTE 只有 172 只参与」）**：
  `--include-neutral` 扩 A 人口至全量——synergy C 档（无方向票）也全量判读（判据 hold 段现成：
  「全部有向维 hold/unknown→观望」，判据零改动）；C 档无帽全采，对照锚 C→hold；E 档仍归
  B 语境（环境门否决）。**10-09 11:30 帧已补齐**：C 档 49 例 ok（7.8 万 tok），VOTE 覆盖
  221/238（S/A/B/C/D 全判；17 例 synergy E 归 B 语境不重复判）。
- **B 人口全量覆盖（三修，2026-10-12 用户裁决「周期字段大部分股票没数据」）**：pilot 口径
  B 只判非 cooling（当日列表 ~250 只仅 ~25% 有值）——生产展示语义要求每只股都有周期判读，
  `--include-cooling` 扩人口至全量（cooling 判据段现成：降温=「中低位且无起升证据」，
  判据零改动）；缺省仍为 pilot 口径（已验收对照台账不混代）。**10-09 11:30 帧已按全量口径
  补齐**：新采 cooling 128 例 ok（21 万 tok），非 cooling 72 例幂等跳过，合计 200/238 ok
  （32 例当日轨迹/度量不足如实留痕 fail-visible）——周期字段覆盖率 200/238=86%，
  剩余 32 例为原料真不足（不伪装）；A 题集 172 例照旧。
- **开放项（待指令）**：11:30 帧的 9-10 月历史回填（23 日 ≈4140 call ≈ 570 万 tok ≈ $0.41）。

### §六·产·执行记录

- [x] runner 帧级参数化+watch 轮询（二修槽表=11:30/15:00）+帧标记（测试：slot 参数化含数据真源
  断言/槽位推导 6 例/标记往返，29 passed；人口构建全链 slot 传参——修正「数据来自 15:00 帧
  却贴新槽标签」的错标缺陷）；
- [x] **原料跨日化（b 代，VOTE_AMMO_VERSION→2026-10-12b，用户裁决：原料不能只取日内帧）**：
  叙事增「近10日排名轨迹」行（同 slot 历史帧定格，缺行 fail-visible）——判据「多日/峰值」
  引用获得可数锚（铁律 3/4 补原料方向修复，判据文本零改动 hash 不变）；旧 4145 例盖
  2026-10-12a 留档不回写，跨代对照按戳分段；预算影响 <10%（+150 字符/股）；测试 4 例
  （渲染/缺日/人口携带/戳顺延）33 passed，真实库冒烟 10 日点全渲染；
- [x] **挂链定案（2026-10-12 用户三修裁决：两轮复跑对比收盘帧远好于午盘→每日只跑一次 15:00，
  按 EOD 情绪分/连板指数同款挂盘后链）**：schedule.py `run_after_market_once` 增
  `jevVoteRecheck` 步（advisory 语义同 jevDailyLine：失败/跳过不翻转整体 ok 不参与 stopped_at；
  门控=当日 15:00 帧已落库，非交易日零成本跳过；子进程 jev_vote_confirm 全量口径
  --include-neutral/--include-cooling/--workers 4/--token-fuse 6M，runner done-skip 幂等，
  timeout 1800s）；**--watch 常驻模式弃用**（轮询方案被定时链取代，代码保留不删）；
  11:30 历史回填随午盘口径废弃而取消；
- [x] 10-09 两帧复跑（b 代原料+全量人口）：11:30 帧 A 221/238 + B 200/238（午盘口径验证后
  废弃，存量留档）；15:00 帧 A 214 ok（含 4 例网络抖动幂等补齐）+ B 182 ok（≈63 万 tok），
  跨代对照 A 131/133、B 44/49 判读不变（b 代跨日行未带偏判读）；两帧低一致率判例
  （cooling→reversal 万科A/泸州老窖有据、格力电器存疑；A 卖侧量价 A/B/C 档逆判）已交用户
  盘感验收，裁决「收盘帧远好于午盘」；

### §六·产·七修 取消抽样帽（2026-10-14 用户裁决「帽子盖的是自己的眼睛，毫无实际意义」）

> 触发事实：10-14 面板「热榜股总数 244 / VOTE 方向复核 235 / LC 生命周期复核 200」差异归因
> 复查时发现——LC 的 200 不是覆盖上限而是**抽样帽**（`--lc-cap-total 200`，pilot 期按当时
> 人口上限 B≤86/日 定值、三修纳入 cooling 后人口涨到 244/日却未同步放大），
> `sample_lifecycle` 分组把 cooling 排末位 → 每日被砍的 44 只全是 cooling 大盘蓝筹
> （601188/601288/601318/601398/601566/601899…），10-09 当天已撞过一次（首跑帽 200
> 截断 44 例，手工放大帽补齐到 247/250），但固化值没改，于是 10-13 起每天都在重复截断。
> 用户裁决：取消帽子设计。

- **改动（判据/对照锚/落库合同零改动，同 hash 同代际可累计）**：
  - `backend/analysis/hotlist/jev_vote_ammo.py`：删 `sample_lifecycle` 及 v4 代起已死的
    `vote_buy_sort_key`/`vote_sell_sort_key`/`VOTE_DIMS`/`TIER_RANK`（抽样专用件随帽一并退役）；
  - `backend/operations/jev_vote_confirm.py`：`run_lifecycle_day` 去 `cap_igex/cap_total`
    参数，人口=候选全量；删 `--lc-cap-igex/--lc-cap-total` CLI；watch kwargs 清帽；
  - `backend/operations/schedule.py`：盘后链子进程去帽参数（原 `--lc-cap-igex 100
    --lc-cap-total 200` 弃用）；
  - 测试：抽样帽测试退役，新增 `test_run_lifecycle_no_cap_full_population`
    （12 候选 > 旧帽 8 仍全采，回归钉死无帽）；schedule 命令断言加"帽参数不在 cmd"。
- **10-14 补跑（用户指令即开火批准）**：`--lifecycle-day 2026-10-14 --slot 15:00
  --include-cooling --workers 4 --token-fuse 6000000 --fire` → **新采 40 例全 ok、零 degraded、
  64,781 tokens**（200 例已跑幂等跳过 + 4 例 data_insufficient 留痕零调用）；
  LC 覆盖 244/244 = 100%（240 ok + 4 留痕），面板「LC 生命周期复核」200 → **240**、
  未复核 40 → **0**；紫金矿业 601899 补齐 LC=cooling（conf 0.69，与规则 stage 一致）。
- **遗留（本次不改，另行登记）**：VOTE 判读时点仍硬编码 11:00（`DIRECTION_SLOT`），
  与面板默认 15:00 帧不同池——10-14 的 61 只「VOTE 未复核」= 11:00 后进榜股
  （000063 中兴通讯 13:00 才进榜即此因）；KPI 的 `vote.ok` 是文档级计数（含 52 份
  已跌出 15:00 榜的文档）而行级 `unreviewed` 是行级计数，两者不可加。是否把 VOTE
  判读时点对齐 15:00 需走预登记（11:00 as-of 是 v4 冻结计分口径）。

### §六·产·八修 共振维独立判读试点落地（2026-10-14，前端就地改造【共振】列）

- **读口合同扩展（`backend/services/jev/jev_quotes_review.py`，只读零写入）**：新增第三题集
  `hotlist_jev_resonance_recheck_pilot` 的 join——行级 `jev.res`（direction/confidence/score/
  riskLevel）+ `jev.resAgree`（对照锚=同帧引擎共振 direction）、`summary.resonance`
  （ok/degraded/insufficient/buy/sell/hold/modelInsufficient/unreviewed）+ `summary.resAgree`/
  `resDiverge`、`resonanceSlots`、`resonanceSlotNote`（所选帧无判读时的结构化说明）、
  `docs.res`（with_docs=1 全保留，含 bars/engine* 对照锚快照）。**帧锁定与 LC 同规**
  （跨槽拼接禁令）：判读帧=序列末项，换帧读数即换原料；所选帧无判读→读数缺失如实 null。
- **前端（`backend/relay_page/index.html`，不新增列）**：【共振】列有判读→jev 读数
  （走强/同步/走弱徽标 + 强度分带色数值），无判读→回落引擎档位徽标（试点未开火期间不退化成
  全 '--'）；表头 title 说明双源、tooltip 给全量（引擎档位 + jev 读数 + 对照锚一致/分歧/锚缺失）；
  新增「RES 共振复核」KPI 卡与 `jev共振` 筛选、`res` 排序键；行展开增第三张 lg-card
  （读数摘要：方向/强度/置信/出现次数/引擎对照锚 + 请求/响应/原始 JSON）。列数仍 17，colspan 不变。
- **判据/开火状态未变**：题集与预登记见 `docs/hotlist-jev/jev-resonance-recheck-preregistration.md`，
  **判据待用户逐字确认，未确认前零开火**（当前库里 RES 集合为空，面板读数全走回落分支）。

### §六·产·十修 摘除 jevVoteRecheck 自动调度步（2026-10-15 用户裁决「v4 挂自动调度可以删掉了，浪费 token」）

**裁决**：自动链每日 15:00 跑 VOTE（v4-material 全池 11:00 时点）+ LC（全量冷却含）
≈500 call/日、熔断线 600 万 tok/日，属链上最贵一步；用户判定浪费，摘除。

**改动（判据/锚/落库合同零改动，runner 全部保留）**：
- `backend/operations/schedule.py`：删 `_run_jev_vote_recheck_step` 函数、
  `_JEV_VOTE_RECHECK_TIMEOUT_SECONDS` 常量、`run_after_market_once` 的调用点与
  `steps`/`results` 两处 `jevVoteRecheck` 键；`_run_vote_winrate_ledger_step`
  docstring 去掉「jevVoteRecheck 之后跑」引用（本步零 jev 调用零成本，保留作裁决门）；
- `tests/platform/test_operations_schedule.py`：删 3 个专测（skipped_when_frame_missing /
  dry_run / runs_full_population），新增 `test_after_market_chain_has_no_jev_vote_recheck_step`
  摘除回归（`not hasattr(schedule, "_run_jev_vote_recheck_step")`），steps 断言去键，
  新增 `"jevVoteRecheck" not in result["results"]` 断言；35 → 33 passed。

**保留不变**：
- 判读能力全在 `backend/operations/jev_vote_confirm.py`，手动 `--fire` 路径照旧
  （需要时显式开火，仍走 AGENTS §1.2-7 预登记+用户批准）；
- `voteWinrateLedger` 步（纯读+小写，零 jev 调用）保留，裁决门 2026-10-27 不变
  （「V4 累计胜率 > 规则线 → 保留，否则撤 vote 判读」）——它只对**已落档**判读生效，
  摘除自动判读后不再有链上新数据驱动，等手动跑或恢复采集链再结算；
- `--watch` 常驻模式此前已弃用（轮询方案被定时链取代，代码保留不删），本次不动。

**影响面**：盘后链少一步，每日链上 jev 调用从 ≈500 call 降到 0（jevDailyLine 一句话
仍为零成本小调用，不在此列）。面板读数、读口、台账全部只读存量，无回写无迁移。
