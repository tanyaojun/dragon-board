# 竞价龙头第三源预登记（2026-11-15）：竞价试盘强度板块前三（严格档，并集补充）

> 状态：裁决冻结（2026-11-15 用户三点确认）；代码落地与本文同轮（红线 5）。
> 基线 = `auction-leader-vA2-preregistration-20261114.md` / vA3（题集现行代际）。
> 双源骨架（09:26 挂链/退避/六件套/补源/结算/幂等/单只重跑/relay rv-auction）全部沿用，
> 本文只登记第三源增量。真实 jev 开火仅走 `--confirm-budget` / 预登记日包络挂链
> （AGENTS §1.2-7）；一切自动化测试 mock jev，禁真调用。
> 规则档来源：`auction-trial-premium-100d-evaluation-20261115.md` §2.1 公式 / §9 规则档
> （100 交易日 9464 行描述性拟合；2026-11-15 修订版数字）。

## 1. 动机

双源（KPL 09:15 推送 ∪ 韭研 T−1 龙一/二/三）覆盖「编辑视角 + 昨日主线」，但**当日竞价
试盘资金行为**不在选龙依据内。100 日评估发现联合最优组合：**中热 2-5亿板块 × 个股
mid50_95 × 资金撤减 ≈ 47.3% 可买封板 + 41.7% 隔日溢价**（n=129，§5），且 mid50_95
天然零一字（可买）。用户裁决：把「竞价试盘强度板块前三」作为**第三选龙源**，并集补充
进 live 锚人群（非替换），直接 live（不做影子期）。

## 2. 裁决记录（2026-11-15 用户确认）

- C1 **直接 live**：预登记 + `--confirm-budget` 后直接进 live 锚，不做影子期。
- C2 **严格档**：仅 **中热 2-5亿板块 × 个股 mid50_95 × 资金撤减**，每板按 `jj_ratio`
  降序取前三（评估联合最优 ~47% 可买封板 + ~40% 溢价；候选实测 ≈1–3 只/日，§6）。
  不采用 top95（近半一字买不到）、不采用热/过热板（出货特征）、不采用 maintain 姿态。
- C3 **root 粗桶**：第三源个股 doc 板块 = jiuyan root（`boardSource=jiuyan_root_trial`），
  与强度计算端到端同口径（`jiuyan_board.board_index` > 板块名称桥 > 近 60 日打标分组
  兜底，与线上读口 `get_auction_trial` / 评估脚本同链单源）。

## 3. 选龙合同（第三源，并集补充）

```
board_amt(date, board) = Σ jj_amount（该日该 root 板全部试盘股；缺值按 0 计）
合格股 = board_tier(board_amt) == 中热 2-5亿（2e8 ≤ Σ < 5e8）
       ∧ tier_jj(row) == mid50_95（50 ≤ jj_ratio < 95）
       ∧ posture(row) == decrease（last_amount < first_amount，两者非缺）
roster = 每 root 板合格股按 jj_ratio 降序前 max_per_board=3
每日软上限 max_total=6（超限按全局 jj_ratio 降序截断，truncatedN 记账）
live 锚 = push ∪ jiuyan_dragon ∪ roster（by_code 去重，selectionSources 累积）
```

- `jj_ratio = jj_percent / denom × 100`；denom = pre_percent（PRESEAL）否则 limit
  （bre.tier_jj 同锚；limit/preseal 口径 `bre.row_basis` 单源，含 ST pre_percent 探测
  + stock_names 名称补正 `bre.st_name_fix`，与评估脚本 main 同口径）。
- 每股结构化：新股 `selectionSources=["auction_trial_strength"]`、
  `boardSource="jiuyan_root_trial"`、`board=root 板名`、`pct=None`、`dragonRoles=[]`、
  `boardMapping.pickedBy="trial_root_strength"`、`trialStrength={boardAmt, btier,
  jjRatio, jjtier, posture, rank, boardTrialN}`；与双源重叠股**追加源标签 + 强度载荷，
  保留双源 board/龙序/pct，叙事不变**。
- **仅产 leader doc，不新增 sector doc**（控预算、避板块口径 `_id` 冲突）；trial 龙头
  `sectorJudgmentState=sector_missing`（root 板无 ABM 板块判答，fail-visible，即使
  root 板名与 ABM 板名巧合也不注入）。
- **同板竞价对比 peers 限同口径**：root trial 股互为 peers，不与 ABM 双源股混比
  （sector doc 成员/peers 均按 boardSource 隔离；双源内部 peers 行为不变）。
- 非题材行政桶剔除（`digest.is_not_a_theme`）对第三源同规；`--max-leaders` 截断护栏
  沿用；第三源软上限 CLI `--trial-max`（缺省 6）。
- **第三源不单独触发**：双源均缺席/全排除时沿用既有 skip（并集补充语义，不兜底选龙）。
- **调度不变**：09:26 挂链 + 退避沿用，run() 内集成；stdout 标记行合同不变。

## 4. 语料合同（增量，ammoVersion 换代，题面不动）

- 新增行 `auction_board_strength_line`（仅第三源 leader）：
  「板块竞价强度：{root板} 试盘竞价成交 Σ{amount}，强度档 {btier}，板内试盘 {n} 只」。
- 新增行 `auction_trial_selection_line`（仅第三源 leader）：
  「竞价强度入选：jj_ratio {x}%（{jjtier}），资金姿态撤减，板内强度排名 {rank}」。
- 两行只放数据事实（§1.2-8）；缺数据整行缺席；过 `test_narrative_hygiene` 黑名单。
  双源 leader 叙事不变（已有 `auction_trial_line` 照旧）。
- `AMMO_VERSION_AUCTION_LEADER = "2026-11-15b"`（语料供给换代）；
  **`QUESTION_SET_VERSION` 保持 vA3、questionSetHash 不动**（题面源无关，选源不改题义；
  vA3「板块聚合留 vA4」指板级判答聚合，非本选源）；版本戳登记
  `tests/hotlist/test_jev_version_stamps.py`。
- 基础率锚第三桶：`auction_seal_base_rate` 增 `nTrial`，构成互斥优先级
  **jiuyan_dragon > auction_push > auction_trial_strength**（trial 桶 = 仅竞价强度源股；
  `source_bucket` 单源，锚计算与 pilot eval 构成披露共用）；锚行补「推送 a/韭研龙 b/
  竞价强度 c」。锚计算口径不变（滚动直算防 look-ahead，`BASE_RATE_START` 沿用）。
- **dry-run/历史日回读**：live 窗采集缺席（dry-run/窗外/历史日）时读 `auction_trial_raw`
  日档（纯库读零外呼零写），强度选龙与试盘语料可回放；日档亦缺 → 第三源整源缺席。
  回读态 `trialState.source=archive`（fail-visible 留痕）。

## 5. 存储与 API 合同（增量）

- leader doc 增 `trialStrength`（trial 源股；旧档缺 → None）；`selectionSources` 新值
  `auction_trial_strength`；`boardSource` 新值 `jiuyan_root_trial`；`boardMapping.pickedBy`
  新值 `trial_root_strength`。
- run 结果增 `trialStrengthState`（{state: ok/absent, date, mappedN, unmappedN,
  hotBoards:[{board,amt,n}], selectedN, reason?, cap?, truncatedN?}）与
  `selection.trialN/overlapTrialN`（trial_new 在场时 unionN 重算为最终候选数）。
- `GET /api/hotlist-jev/auction-leaders` 行源 = labels ∪ 推送 roster ∪ jiuyan 龙 roster
  ∪ **trial roster**（读口按需调同一 `trial_strength_roster` 实现，trial_rows 从
  `auction_trial_raw` 日档加载，禁第二套；软上限同 6）；`selectionSources`/`trialStrength`
  透传；双源缺档行合并披露（N3 同款）；计算失败 `nodeFilter.trialRosterError` 留痕不阻断。
- relay rv-auction：行增「竞价强度」源徽章（title 披露 jj_ratio/板内排名，esc 注入）；
  第三源股推送缺席不告警（预期态，pushBad 仅推送源行）。
- pilot eval：`evaluate` 增 `bySelectionSource`（互斥优先级同锚；第三源构成披露）。

## 6. 预算与频控（红线 7/9）

- **零新增外呼源**：第三源复用 run() 既有试盘采集（WzsLinker api-auction.php，09:25–09:30
  窗裸读≤1 + 陈旧补拉≤1，勘察台账 §6.4 不变）；root 映射全库内读（jiuyan_board/桥/
  打标分组，300s 进程内缓存）；读口纯读零外呼。
- **调用包络（100 归档日 dry-run 实测，2026-11-15）**：第三源每日入选分布
  {0:33, 1:35, 2:14, 3:11, 4:3, 5:3, 6:1}，**均值 1.29 只/日，峰值 6**（cap 截断仅 1 日），
  0 候选日 33/100。总包络 = 双源 ~30（峰≤45）+ 第三源典型 1–3 → **典型 ≈31–33 调用/日，
  峰值 ≤51**（双源峰 45 + trial 帽 6）。tokens 上限仍以 `estimate_tokens` 干跑估算写入
  挂链日志；`--max-leaders` / `--trial-max` 双护栏。
- 结算零 token（16:10 挂链）与验收口径沿用；pilot eval 按 selectionSources 披露第三源
  构成（跨代际仍按 questionSetVersion 分代，vA3 内第三源不另起代际——题面未变）。

## 7. 失败模式（fail-visible，增量）

- trial_rows 缺/空（取数失败/窗外/dry-run 且无日档）→ 第三源整源缺席 +
  `trialStrengthState.reason=no_trial_rows`，**双源不受影响**（不兜底选龙）。
- 未分板块（14.5% 传统行业）→ 排除并计 `unmappedN`（无 root 节点不算强度）。
- 无中热板 / 无合格股 → 0 候选 + `reason=no_qualified`（非错误）。
- `jj_percent`/`first_amount`/`last_amount` 缺 → 严格筛自然排除（no_ratio/no_data
  不进档，不伪装 0）。
- 超软上限 → 全局 jj_ratio 降序截断 + `cap`/`truncatedN` 记账。
- 日档回读失败 → `trialState.archiveReadError` 留痕，第三源缺席不阻断。
- 读口 trial roster 计算失败 → `nodeFilter.trialRosterError` 留痕，labels/推送/jiuyan
  roster 不受阻。
- **时点披露**：09:26 试盘板快照可能略未定格（end_time 晚于采集时点）→ 强度为时点
  快照；`jj_*` 为 end_time 快照非统一 09:25 冻结值（评估文档 §2.1 口径警示）。

## 8. 验收（2026-11-15 实测）

- TDD：`tests/hotlist/test_auction_strength.py`（22 例：纯函数边界/严格筛前三/
  root 全链/软上限/ST 补正/跨日覆盖回归/fail-visible/NaN 消毒/桥降级留痕/负 cap）+
  ops/route/hygiene/版本戳/relay 守卫增量全过；auction 既有套件无回归。
- **历史日 dry-run 逐日比对**：100 归档日 roster 候选 == 评估脚本严格组合
  （中热×mid50_95×撤减，每板前三）**100/100 吻合**（cap 截断日为子集关系）。
- **单一事实源验证**：评估脚本 refactor（纯函数下沉 auction_strength）前后全窗
  `--offline --simulate` 输出**逐位一致**；随后修复 hist 跨日覆盖 bug（见 §9），
  数字微调已同步评估文档（结论方向不变）。
- 端到端 dry-run（2026-11-13，离线护栏）：trialN=2、overlapTrialN=1，零 jev 零写零外呼。
- 真实开火仅用户授权 + `--confirm-budget` + 本文日包络；结算 16:10 沿用。

## 9. 同轮修复与 refactor（登记）

- **桥接 helpers 下沉**：`_bridge_maps/_bridge_lookup/_bridge_hist/_norm_bk` 自
  `api/hotlist_jev_auction_routes.py` 移入 `services/jev/jiuyan_board.py`（签名/行为
  不变，路由改 import 单源），消除 analysis→api 耦合（AGENTS §2.2 三层分离）。
- **hist 跨日覆盖 bug 修复**：`assign_root_boards` 全窗运行时，同 code 某日桥 miss 进
  hist 后旧实现连带覆盖该 code 其他日期已有 direct/bridge 归属的行——修复后 hist 仅
  兜底本行仍无归属者（单日/全窗口径一致；回归测试锁定）。评估文档数字已同步
  （hist 命中 887→500，中热 n 1608→1624，严格组合 47.3%/41.7% 不变）。
- **bre 单源扩展**：`row_basis`（limit/preseal/ST 探测）与 `st_name_fix`（名称补正）
  提取为共享函数，load_rows / 评估 main / 第三源 roster 共用（禁第二套）。

## 10. 影响文件与验证

- `backend/analysis/hotlist/auction_strength.py`（新：纯函数 + assign_root_boards + roster）
- `backend/services/jev/jiuyan_board.py`（桥接下沉 + reset 扩桥缓存）
- `backend/api/hotlist_jev_auction_routes.py`（桥 import 单源 / 行源 ∪ trial roster / 透传）
- `backend/operations/auction_leader_label.py`（第三源并集 / 隔离 / 软上限 / 锚第三桶 / 日档回读）
- `backend/analysis/hotlist/auction_leader_ammo.py`（两新行 / ammoVersion / 锚行三桶）
- `backend/relay_page/index.html`（rv-auction 竞价强度徽章）
- `scripts/auction_trial_base_rate_eval.py`（row_basis/st_name_fix 单源）
- `scripts/auction_trial_premium_eval.py`（import 单源 / board_map 委托）
- `scripts/auction_leader_pilot_eval.py`（bySelectionSource 披露）
- 本文 + 评估文档修订；`tests/hotlist/test_auction_strength.py`（新）、
  `tests/operations/test_auction_leader_label.py`、`tests/api/test_auction_leader_route.py`、
  `tests/hotlist/test_narrative_hygiene.py`、`tests/hotlist/test_jev_version_stamps.py`、
  `tests/hotlist/test_relay_page_auction_leaders.py`、`tests/conftest.py`（腾讯离线守卫）
- 验证：`pytest tests/hotlist/test_auction_strength.py tests/hotlist/test_auction_trial_premium_eval.py
  tests/operations/test_auction_leader_label.py tests/api/test_auction_leader_route.py
  tests/hotlist/test_jev_version_stamps.py tests/hotlist/test_narrative_hygiene.py
  tests/hotlist/test_relay_page_auction_leaders.py tests/hotlist/test_auction_trial_line.py
  tests/operations/test_auction_leader_schedule_parse.py`

## 11. 三路 subagent code review 与修复（2026-11-15，用户授权）

fresh-context 只读评审×3（算法正确性 / 合同展示 / 测试文档红线，correctness 路
429 配额中断后 resume 续跑完成）：无 P0；3 P1 + 9 P2 全部核实并同轮修复（TDD 先红后绿）：

- **P1-1 读口 missing_by_key 快照过期**（contract+correctness 独立互证）：jiuyan 新增
  缺档行未注册快照 → jiuyan∩trial 股静默丢第三源披露。修：jiuyan append 同步注册；
  补 `test_trial_merge_into_jiuyan_only_missing_row`。
- **P1-2 codes 早退截断 trial-only 单股重跑**（两路互证）：早退改 `if not rows and not codes`，
  并集后补同款 skip（含 trialStrengthState）；全日无 codes/双源全缺语义不变；重跑路由
  文案同步（不再称「双源名单」）。补 codes 重跑/未命中两例。
- **P1-3 新夹具漏 mock 腾讯补源**（tests-docs）：`_trial_strength_setup` 窗内未 mock
  `get_auction_snapshot_tencent` → 4 例可真连 qt.gtimg.cn。修：夹具补离线 mock；
  **根治**：conftest 增腾讯离线硬守卫（qt/ifzq.gtimg.cn，与 jev/THS 守卫同款，
  覆盖既有 3 例同款泄漏而不改其断言）。
- **P2 批次**：路由残留 `import time` 删；行政桶剔除后 by_code 同步剔除（防 overlap
  吞合法 trial 候选，补回归例）；fnum/bre.posture 非有限值消毒（NaN 板额污染/误纳入，
  补 4 例；真实归档无 NaN，评估数字不变）；roster 桥降级 `bridgeDegraded` 留痕（补例）；
  run() roster 包 try/except（与读口对称，补例）；负 max_total 钳 0（补例）；
  FakeCol 补 $lt/$regex/$ne/$nin/$exists + 未知算子显式 raise；archiveReadError 补测试；
  评估文档两处修订残留同步（§0-4 ≈47–49%、§11 验证记录 hist 修复前时点注）。
- 验证：auction 全套（AS 22 + ops 61 + route 28 + hygiene/版本戳/relay/premium/line/
  schedule/board_map/push_parse/trial_fetch）全过；全量 pytest 5322 过，仅 3 个用户
  监管 WIP 既有守卫失败 + 2 个数据依赖型既有环境失败（research 空窗期望但本地测试库
  有帧；backtest 顺序偶发、api+backtest 三连过单跑全过，均非本轮引入）。
