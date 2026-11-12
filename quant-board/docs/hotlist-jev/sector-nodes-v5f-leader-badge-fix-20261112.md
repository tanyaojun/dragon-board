# 板块节点 v5f：龙头列徽章口径修复（2026-11-12 用户截图裁决）

> 状态：已实施 + 近月窗口回填完成。消费页：`backend/relay_page/index.html` 板块节点表。
> 上游口径：v5 空间龙一（`sector-nodes-v5-leader-unify-preregistration.md`）不变，本次只修展示与台账事实键。

## 一、问题（用户 2026-11-12 截图）

1. 龙头列未封板空间龙一显「断板反包」琥珀徽章占高度位——用户判不正确，应显区间高度「N天M板」。
2. 龙头列「断板」徽章部分错误：浙文影业（今日未封）断板正确；日出东方（4 板、今日封板）
   被贴断板，应为续板。同形错误：天普股份 2 板、福莱新材 2 板、日海智能 2 板均被贴断板。
3. 同根因自相矛盾：依据列「龙头断板（天普股份（2 板））」拿**今日**龙一名描述**昨日**龙一状态。

## 二、根因

- `leaderState` 口径 = 「昨日龙一今日状态」（`_leader_states` → `day_status_of`），供节点判据
  （退潮/转弱/弱转强的龙头续断分支）。v5 改空间龙一后今/昨龙一常不同股（光伏：今=日出东方、
  昨=闽发铝业），前端把 `leaderState` 贴在今日龙一名旁 → 误标。
- 未封龙一 `streak=null`，前端高度位回落琥珀徽章，区间高度事实（韭研 num）未进台账 → 无料可显。
- `classify_board_day` 续/断 basis 文案消费 `leader`（今日龙一）而非状态主语（昨日龙一）。

## 三、裁决与口径（本次固定）

1. **龙头列续/断徽章只看今日龙一自身状态**：台账新增 `leader.dayStatus`
   （`day_status_of` 单源：池权威 + 日线补洞，停牌不算断板 v4）。
   sealed 且真连板 ≥2 → 「续」；sealed 首板 → 不贴；broken → 「断板」；suspended → 「停」；
   unknown → 「?」。旧档无 `dayStatus` 回落 `leaderSealedToday`/`streak` 推导（fail-visible）。
2. **未封龙一高度位 = 区间高度 N天M板**：台账新增 `leader.days/boards`
   （`_jiuyan_days_boards` 单源解析韭研 num；封板龙一=当日 num，断板龙一=最近封板日 `poolDay`
   num，tooltip 披露截至日）。num 不可解析 → 「高度不可考」灰字，不伪造板数；
   「断板反包」琥珀徽章从龙头列删除（候选语义进「断板」徽章 tooltip）。
   连板语义仍一律 `streak`（2026-10-16 口径修正不复活）。
3. **`leaderState` 保留**：节点判据不变；展开卡披露改名「昨日龙一今日状态」（主语明确）。
   续/断 basis 文案主语改昨日龙一（`classify_board_day(prev_leader=…)`）；未封昨龙一 basis
   披露区间高度（`_leader_desc`：streak 缺 → N天M板 → 板数不可考 三级回落）。
4. 龙一只算一次落一次库：`dayStatus/days/boards` 在 settle 链计算落台账，读口不重推。

## 四、改动面

- `backend/operations/theme_leader_baseline.py`：space_mode 候选/行携带 `days/boards`（num 单源解析）。
- `backend/operations/sector_nodes.py`：`_leader_day_states` 共享实现（昨龙一状态与今日龙一
  `dayStatus` 共用，禁双实现；`bars_need_upto` 声明当日防本地末棒落后误判停牌）；settle 注入 `dayStatus`。
- `backend/analysis/hotlist/sector_nodes.py`：`_LEADER_LEDGER_KEYS` 扩容；`classify_board_day`
  增 `prev_leader`（判据不变，仅文案主语）；`_leader_desc` 区间高度回落。
- `backend/relay_page/index.html`：`renderNodes` 龙头列高度/徽章新口径；展开卡主语改名。
- 测试：`tests/hotlist/test_sector_nodes.py`（+4）、`test_sector_nodes_leader_state.py`（新）、
  `test_relay_page_sector_nodes.py`（新，前端守卫）、`tests/operations/test_leader_range_height.py`（新）、
  `test_sector_agg_attach.py`（桩 seam 迁到共享 `_leader_day_states`）。

## 五、回填与验证

- 回填：`python -m backend.operations.sector_nodes --backfill --from 2026-10-12 --to 2026-11-11`
  （23 交易日全 ok、无降级；幂等覆盖，节点分布与旧档一致）。窗口外旧档：徽章回落推导、
  未封高度显「高度不可考」（不伪造），如需可再扩窗回填。
- 验证：`pytest tests/hotlist tests/operations tests/api` = 1854 passed / 6 skipped；
  node 沙箱以真实落库 doc 跑 `renderNodes`：日出东方 4板+续、天普股份 2板+续、
  浙文影业 5天5板+断板、阳光照明 12天7板+断板、光洋股份 3板+续、青山纸业首板无徽章、
  依据主语=先导基电、展开卡披露保留 —— ALL PASS。
- 页面服务 `serve_relay_page` 为 FileResponse 每请求读盘、读口实时查 Mongo → 无需重启，刷新即生效。

## 六、残留与已知局限

- 区间高度 N 截至 `poolDay`（最近封板日韭研 num），非滚动至今日；tooltip 已披露。
  若用户裁决要「N 滚动至今日」，需另立口径（M 不变、N 加 poolDay→今日交易日数），不在本次范围。
- 窗口外旧档无 `dayStatus`：停牌中的未封龙一会被回落推导贴「断板」（极罕见）；扩窗回填可消除。
- `_adj_prev_series` 除权事件源（百度）404 时 adj 回落原始收盘（既有局限，非本次引入）。
