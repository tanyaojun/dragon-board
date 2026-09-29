# Jev 热榜情绪双问题观察轨道 — 实施计划

> **For agentic workers:** 按 Task 顺序执行，每 Task 先写失败测试（TDD）再实现；测试数据只入 `dragon_board_test`，真调用 jev 仅限 Task 6/8 显式步骤。

**Goal:** 落地 `hotlist-jev-emotion-observe-design.md`：jev 从纯原始证据（零规则输出）回答「当前帧五档判定 + 当日连续帧序列判定」两问，盘后固定日级总体；结论经读 API 展现在前端 DragonBreath 热榜情绪面板，供用户盘中对照论证。

**Architecture:** 8001 collector `_run_post_persist_chain` 第 4 步（gate 默认关）→ 证据聚合（纯函数）→ 叙事字符串 → `services/jev/jev_client.call_jev`（/ai/run，timeout 30s）→ `hotlist_jev_sentiment` 槽位/eod 文档；8000 evaluate/series 路由；前端类型+客户端+面板双轨展示；最近 3 交易日回放 runner 保证上线即有数据。

**Tech Stack:** Python 3 / FastAPI / MongoDB / pytest（FakeMongo + monkeypatch，不触网）/ Vue 3 + TS / Vitest / Playwright。

**Spec:** `quant-board/docs/hotlist-jev/hotlist-jev-emotion-observe-design.md`（2026-10-08 方向重置版，D1-D4 已拍板）

**工作区纪律:** 执行前 `git status --short` 核对；只 `git add <明确文件路径>`；禁 `git add -A`/`reset --hard`/`checkout --`；不碰用户未提交文件。

---

## 关键合同（全 Task 共同遵守）

- **零规则输出进输入**：聚合器/叙事/服务层一律不读 `hotlist_sentiment`；叙事中不得出现规则 stage/summary/signals。
- **questions 常量冻结**：`JEV_SLOT_QUESTIONS`（frame_stage/sequence_stage 两个 choice + temperature/crowding 两个 score）、`JEV_DAY_QUESTIONS`（day_stage/day_pattern 两个 choice + day_temperature/day_crowding 两个 score）；**无任何 noul 问**（测试冻结断言）。
- **score 锚点**：0-100 十档 `["0","11","22","33","44","56","67","78","89","100"]`（与 `jev_client.SCORE_ANCHORS` 同源，注释互指，勿单方修改；answers.scores 按 idx/(N-1)×100 由 `parse_jev_response` 还原）。
- **五档 choice criteria**（frame_stage/sequence_stage/day_stage 共用文案）：ice 冰点：赚钱效应殆尽，涨停稀少跌停增多，普遍观望 / start 启动：从弱势基线开始修复，试错资金进场，局部热点出现 / ferment 发酵：赚钱效应扩散，涨停与连板增多，热点扩散 / climax 高潮：全面亢奋，涨停潮普涨，拥挤明显 / retreat 退潮：从强势转弱，高位股集体走弱，炸板增多。
- **day_pattern 七类**：steady_strong 全天强势主导（多数时段发酵/高潮）/ steady_weak 全天弱势主导（多数时段退潮/冰点）/ rally_fade 冲高回落 / low_recover 低开修复 / wide_swing 强弱多次交替 / narrow_range 窄幅平淡 / unclear 证据不足无法归纳。
- **聚合器口径**：涨停行 = `price >= limitUpPrice*0.999`（无价格证据不进涨停桶，按 pct 归桶不伪造）；breadth 五桶互斥 limitUp/up5(≥5%)/up0/down0/down5(≤-5%)；`indices.change` 为涨跌额点数（帧现口径，无百分比，叙事标「点」）；zlje 合计单位元、叙事换算亿（1 位小数）；昨日涨停承接复用 `analysis/hotlist/sentiment.py::build_yesterday_hot_limit_evidence(yesterday_rows, rows, None)`。
- **文档三态**：`ok` / `degraded`（errorCode/errorDetail + responseRaw，绝不伪造档位/0 分）/ `no_data`（帧或行全缺时显式落库）。gate 关闭 → `{"written": False, "skipped": True, "reason": "jev_disabled"}`，不写文档不告警。
- **_id**：槽位 `{datasetId}:half_hour:{tradingDate}:{slotTime}`；eod `{datasetId}:half_hour:{tradingDate}:eod`。`replace_one(upsert=True)` 幂等。

---

### Task 0: 前置核对

- [ ] `git status --short` 干净基线（除用户已有修改）；`cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/hotlist/test_jev_state.py tests/hotlist/test_jev_client.py -q` → 7 passed。

### Task 1: questions 常量 + 证据聚合器（TDD）

**Files:** Modify `backend/analysis/hotlist/jev_state.py`；Test `tests/hotlist/test_jev_state.py`（追加）

- [ ] 失败测试要点：
  - `collect_slot_evidence(frame=_frame(), rows=..., yesterday_rows=..., analysis_by_code=..., slot_time="10:30")` 返回 shape：`indices/limit/breadth/fund/turnover/yesterdayLimit/lifecycle/leaders/reasons/quality`（合同见「关键合同·聚合器口径」）。
  - fail-visible：frame=None → `quality.degradedSources` 含指数与涨停缺失项，`limit` 相关键缺省不伪造 0；rows 无 zlje → `fund.zljeSum is None` 且 `zljeMissing==len(rows)`；yesterday_rows=[] → `yesterdayLimit is None`。
  - 涨停桶：price≥limitUpPrice*0.999 进 limitUp；无价格证据的高涨幅行只进 up5。
  - `JEV_SLOT_QUESTIONS`/`JEV_DAY_QUESTIONS`：恰好 4 问；type 集合 = {choice, score}；全库断言无 `"noul"` 键。
- [ ] RED 确认 → 实现聚合器与常量 → GREEN。
- [ ] Commit：`feat(hotlist-jev): 证据聚合器与双问题常量（观察轨道 v3）`

### Task 2: 槽位/日级叙事构建器（TDD）

**Files:** Modify `backend/analysis/hotlist/jev_state.py`；Test `tests/hotlist/test_jev_state.py`（追加）

- [ ] 失败测试要点：
  - `build_slot_jev_state(trading_date, slot_time, current=<evidence>, priors=[<evidence>...])`：含头部/【当前帧证据】/【当日已走帧证据】/【数据质量】四段；压缩行格式含「涨停 68」「最高 6 板」「炸板率 15%」「主力净额 +2.1亿」「新进 22」「昨涨停承接均 +1.2%」「点火 18」；缺源项写「缺失」并在质量段列出；`len ≤ 4000`。
  - `build_day_jev_state(trading_date, evidences)`：逐帧行 + 【当日累计】（最末帧 new/dropped/zljeSum + 全日 maxBoard 峰值）+【数据质量】；`len ≤ 6000`；空列表防御（"无帧证据"）。
  - **零规则输出断言**：两个 builder 签名无规则文档参数；输出不含「确认阶段」「规则摘要」标记词。
- [ ] RED → 实现（压缩行格式函数 `format_evidence_line` 供槽位与日级共用）→ GREEN。
- [ ] Commit：`feat(hotlist-jev): 槽位/日级叙事构建器（观察轨道 v3）`

### Task 3: 编排服务（TDD，mock call_jev 不触网）

**Files:** Create `backend/services/jev/jev_sentiment_compute.py`；Test Create `tests/hotlist/test_jev_sentiment_compute.py`

- [ ] 实现要点：
  - 取数（直查快照库，不读规则文档）：当前槽 `snapshot_frames`（type=half_hour+tradingDate+slotTime）+ `snapshot_stock_rows`（by snapshotId）+ `MongoRepository(db).load_snapshot_analysis(dataset_id, snapshotId)`（code→analysis，生命周期取 `analysis.displayStatus.stage`）；priors = 同日 slotTime < 当前槽的帧逐个同口径聚合（升序）；昨日行 = 上一交易日最新 half_hour 帧行（小 helper，3 查询）。
  - `compute_and_upsert_for_slot(db, *, dataset_id, snapshot_type="half_hour", trading_date, slot_time, origin="collector", dry_run=False) -> dict`：gate 关 → skipped（最先判，取数前）；当前帧/行全缺 → no_data 文档（detail 记 frame/rows 存在性）；token 缺失 → degraded 文档 `errorCode="missing_token"`；调用 `call_jev(account, token, state=narrative, questions=JEV_SLOT_QUESTIONS, timeout=30)` → `parse_jev_response` → upsert 文档（合同见 design §6）。返回 `{"written","status","errorCode"?,"reason"?}`。
  - `compute_and_upsert_for_day(db, *, dataset_id, snapshot_type="half_hour", trading_date, origin, dry_run)`：全槽升序聚合 → 0 槽 no_data；否则 `build_day_jev_state` → eod 文档（answers 含 day_stage/day_pattern）。
  - `run_jev_post_persist(db, *, dataset_id, snapshot_type, trading_date, slot_time)`：half_hour→slot、daily→day、其他 → skipped；异常向上抛由调用方（链）捕获。
  - 配置：`_jev_config()` 读 `JEV_SENTIMENT_ENABLED`（默认 false）/`JEV_CF_TOKEN`/`JEV_CF_ACCOUNT`（默认 `921cf15176f84c90ea49865334af32c6`）。
- [ ] 失败测试要点（FakeMongo 模式 + monkeypatch `call_jev`）：
  - ok 路径：文档字段合同（kind/origin/evidenceRaw/narrativeRaw/questionsRaw/responseRaw/answers/scores/usage/latencyMs/model/status="ok"）；**文档无规则档位字段**（无 stage/ruleStage 键）。
  - degraded：mock 返回 `{"success":False,"errors":[{"message":"HTTP 402"}]}` → status=degraded、errorCode=http_error、responseRaw 落库、无伪造 answers。
  - no_data：无帧 → no_data 文档 + reason。
  - gate 关 → 不写文档、返回 skipped。
  - 幂等：同输入两次调用集合内仍 1 条且内容一致。
  - day 路径：多槽聚合 → eod 文档 answers 含 day_stage。
- [ ] RED → 实现 → GREEN：`./.venv/Scripts/python.exe -m pytest tests/hotlist/test_jev_sentiment_compute.py -q`
- [ ] Commit：`feat(hotlist-jev): 双问题编排服务（观察轨道 v3）`

### Task 4: 采集链挂接（TDD）

**Files:** Modify `backend/snapshot_collector/service.py`（`_run_post_persist_chain` 末尾追加第 4 步）；Test Modify `tests/snapshot_collector/test_snapshot_collector_post_persist.py`

- [ ] 失败测试要点：gate 关 → 无 jev 写、无新增 warning（默认环境）；gate 开 + ok → 文档落库、无 warning；gate 开 + jev 抛异常 → 仅追加 `hotlist_jev_failed:` warning，前置步骤产物完好；`five_minutes`/`quarter_hour` → 不触发。
- [ ] RED → 实现（try/except 包裹，异常仅 `warnings.append(f"hotlist_jev_failed: {exc}")` + logging，degraded/no_data 亦追加对应 warning）→ GREEN。
- [ ] Commit：`feat(hotlist-jev): 采集后处理链挂接 jev 观察步（gate 默认关）`

### Task 5: API evaluate + series（TDD）

**Files:** Create `backend/api/hotlist_jev_routes.py`；Modify `backend/main.py`（import + include_router）；Test Create `tests/hotlist/test_hotlist_jev_api.py`

- [ ] 合同：
  - `POST /api/hotlist-jev/evaluate`：body `{tradingDate, scope: "slot"|"day", slotTime?, datasetId="dragonboard_live"}`；**不受 gate 限制**（显式意图）；scope=slot 且无 slotTime → 取当日最新已采槽；origin="manual"；同步返回 compute 结果（含 status）；Mongo 异常 503；scope=slot 缺 slotTime 且当日无帧 → 404 `{"ok":false,"errorCode":"no_slot"}`。
  - `GET /api/hotlist-jev/series`：`?dataset_id=&date=YYYY-MM-DD`（缺省取集合内最新 tradingDate）→ `{"ok":true,"date":...,"slots":[...升序],"eod":{...}|null,"degradedCount":n}`；无任何文档 → `{"ok":true,"date":null,"slots":[],"eod":null}`（不报错不伪造）。v1 无缓存。
- [ ] 测试：TestClient + monkeypatch repository_factory db（仿 `test_hotlist_sentiment_api.py` 模式）；evaluate slot/day 往返；series 字段透传与空态。
- [ ] Commit：`feat(hotlist-jev): evaluate/series 读写 API（观察轨道 v3）`

### Task 6: 最近 3 交易日回放 runner

**Files:** Create `backend/operations/jev_sentiment_replay.py`

- [ ] CLI：`--days 3 --dry-run`（默认 3）；日期 = `snapshot_frames`（type=half_hour）最新 N 个 tradingDate；逐日逐槽 `compute_and_upsert_for_slot(origin="replay")` + 日级 `compute_and_upsert_for_day(origin="replay")`；`--days`/`--start`/`--end` 可选覆盖；token 缺失 fail-fast 提示 `JEV_CF_TOKEN`。
- [ ] dry-run 本地验证（不触网）：打印日期/槽位/叙事字节数，无异常退出。
- [ ] Commit：`feat(hotlist-jev): 最近 3 日回放 runner（观察轨道 v3）`

### Task 7: 前端类型 / 客户端 / 面板双轨展示（TDD）

**Files:** Create `src/types/hotlistJev.ts`、`src/services/hotlist/hotlistJevApi.ts`；Modify `src/components/panels/DragonBreathPanel.vue`；Test 面板组件测试（仿现有 DragonBreathPanel 测试模式）

- [ ] 类型：`HotlistJevStatus = 'ok'|'degraded'|'no_data'`、`HotlistJevDoc`（slotTime/kind/answers{frame_stage?/sequence_stage?/day_stage?/day_pattern?}/scores{temperature?/crowding?}/status/errorCode/errorDetail/quality）、series 响应。字段全部可选（旧/缺数据不报错）。
- [ ] 客户端：`fetchHotlistJevSeries(datasetId, date?)` → GET `/api/hotlist-jev/series`（仿 `hotlistSentimentApi.ts` 的 fetch/错误处理模式）。
- [ ] 面板：
  - 顶部情绪卡并列 jev 判定：`sequence_stage` 主值（标「jev 日内序列」）、`frame_stage` 次值（标「jev 当前帧」，两者不同时并列显示）；温度/拥挤分数；五档中文映射与配色沿用现有情绪档样式。
  - 日内轨迹第二标记层：每槽 jev 判定（与规则确认阶段不同时并排小标），degraded 槽显示「jev 降级」、缺槽不伪造。
  - eod 存在时：日级块（day_stage/day_pattern 中文映射/日级温度/拥挤）。
  - degraded/no_data 如实标注（title 含 errorCode/errorDetail 摘要）。
- [ ] 测试：渲染断言（双轨并列、降级标注、空数据不报错）+ vue-tsc 通过：`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- [ ] Commit：`feat(frontend): DragonBreath 面板并列展现 jev 双问题判定`

### Task 8: 全量验证 + 3 日实跑 + 浏览器验收 + 文档同步

- [ ] 后端全量：`cd quant-board && ./.venv/Scripts/python.exe -m pytest -q` → exit 0。前端：`pnpm test` + vue-tsc → exit 0。
- [ ] 3 日实跑（真调用，≈$0.003；本机 shell 取 token 不入仓）：
  ```bash
  export JEV_CF_TOKEN=$(python -c "import json;print(json.load(open(r'C:\Users\Think\.pi\agent\models.json',encoding='utf-8'))['providers']['cloudflare']['apiKey'])")
  cd /d/dragon-board/quant-board && ./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 3
  ```
  验收：3 天 ×（≤10 槽 + eod）文档齐全（按实际已采槽）；degraded 清单与成本（usage token 合计）打印。
- [ ] Playwright 真实浏览器验收（主代理执行，按 `skills/playwright-cli/SKILL.md` + `skills/e2e-verification/SKILL.md`）：桌面+移动视口；双轨并列与分歧可辨；degraded 标注；控制台无新增错误；截图存测试产物目录不入仓。
- [ ] 文档同步：`docs/single-source-of-truth-architecture.md` §3 新增一行（规则轨道 vs jev 轨道 = **并列观察者**，保留面，裁决=用户盘中论证，无预设权威）；`quant-board/docs/architecture.md`/`api-cli.md`/`AI_COLLABORATION.md` 各加小节；旧 `hotlist-jev-sentiment-design.md` 头部加一行取代注记（指向新 design）。
- [ ] 最终 `git status --short` + `git diff --stat` 人工核对；分别报告主工作区状态。

---

## Self-Review 记录

1. **Spec 覆盖**：D1（10 槽）→ Task 3 priors/Task 6 日期源均按 half_hour；D2（面板论证）→ Task 7 + Task 8 浏览器验收；D3（最近 3 日）→ Task 6/8；D4（零规则输出）→ Task 1/2/3 各自断言冻结。
2. **Fail-visible**：三态文档合同 + 聚合器 degradedSources + 叙事缺源如实 + 链路异常仅 warning，全部有对应测试。
3. **零预测**：questions 常量测试断言无 noul；叙事无未来数据输入（priors 严格 slotTime < 当前槽）。
4. **类型一致性**：aggregator evidence dict 键与叙事格式函数、文档 evidenceRaw、TS 类型三处对齐；`parse_jev_response` 输出 {ok,model,answers,scores,usage,latencyMs,errorCode,errorDetail} 直接映射文档字段。
5. **回退**：gate=JEV_SENTIMENT_ENABLED=false 即全链静默关闭；collection 独立可 drop 不伤规则轨道；前端 jev 区块数据缺失时正常渲染规则轨道原貌。
