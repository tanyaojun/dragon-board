# 分相位验收前端可见化——实施计划（Phase-FE）

> **For agentic workers:** 按主代理 inline 串行执行（用户指定），每任务 TDD + 独立 commit。设计：`ranktrend-phase-frontend-design.md`（4713185a）。

**Goal:** 相位体系前端可见化三件——overview 相位 chip、第 8 页签「相位验收」（时间线+北极星+走廊+监督线）、写侧落 Mongo `phase_monitor` 集合 + 两个薄读口。

**口径锚**：sentiment_2b（offense ≥50 / defense <50）——前后端共用此唯一阈值；来源声明指向 `phase_label_run.py` CANDIDATES。

**先例（已实测确认）**：
- 后端路由测试：`tests/hotlist/test_hotlist_sentiment_api.py`——FakeMongoDb + `monkeypatch.setattr("backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db)` + `TestClient(app from backend.main)`；
- 路由注册：`backend/main.py:17` import + `:119-120` include_router；
- proxy 白名单：`proxy-server/routes/quantBoardProxy.js:8-40` QUANT_BOARD_PREFIXES（`/api/hotlist-sentiment/` 已含 :36，`/api/phase-monitor/` 需加）；
- 前端 service 测试：`src/services/hotlist/__tests__/hotlistJevApi.test.ts` vitest + `vi.stubGlobal`；
- 面板：`src/components/panels/HotlistEmotionPanel.vue`（3401 行）TABS :573-581、hero 区 :72-83、jev section :449 起、ECharts nextTick 约定 :2759 附近。

---

## Task 1: 写侧 Mongo upsert（phase_northstar + phase_monitor_monthly）

**Files:** Modify `backend/operations/phase_northstar.py`、`backend/operations/phase_monitor_monthly.py`；Test `tests/research/test_phase_monitor_persistence.py`

- [ ] Step 1 失败测试：FakeDb（replace_one 记录调用）monkeypatch `repository_factory.get_runtime_mongodb_database`，断言 `persist_northstar(report)` / `persist_monthly(report)` 各产生一次 upsert（_id=`northstar:<key>` / `monthly:<month>`，upsert=True）。
- [ ] Step 2 红确认（ImportError）。
- [ ] Step 3 实现：两脚本各加 `persist_*` 函数（`get_runtime_mongodb_database()["phase_monitor"].replace_one({"_id": ...}, doc, upsert=True)`），main() 在写本地 JSON 后调用（try/except 连接失败打印警告不中断——本地 JSON 仍是即时产物，fail-visible 不阻断研究链）。
- [ ] Step 4 绿 + Commit `feat(ranktrend): phase_monitor Mongo 落库——northstar/monthly 幂等 upsert（TDD）`。

## Task 2: GET /api/hotlist-sentiment/phase-history

**Files:** Modify `backend/api/hotlist_routes.py`；Test `tests/hotlist/test_hotlist_sentiment_phase_history.py`

- [ ] Step 1 失败测试：FakeDb.hotlist_sentiment.find 返回 EOD 文档列表（score 65.6/48.3/None 混合），断言响应 days[].phase 映射（offense/defense/unknown）、threshold=50.0、按 tradingDate 升序。
- [ ] Step 2 红。
- [ ] Step 3 实现：薄读口（无 Redis 缓存——单次 find ≤300 文档成本低，docstring 注明原因）；`_PHASE_THRESHOLD = 50.0`（注释：唯一口径源 phase_label_run.CANDIDATES sentiment_2b）。
- [ ] Step 4 绿 + Commit `feat(hotlist): phase-history 读口——EOD 序列按 sentiment_2b 映射相位（TDD）`。

## Task 3: GET /api/phase-monitor/board + proxy 白名单

**Files:** Create `backend/api/phase_monitor_routes.py`；Modify `backend/main.py`（import+include）、`../proxy-server/routes/quantBoardProxy.js`（白名单加 `'/api/phase-monitor/'`）；Test `tests/hotlist/test_phase_monitor_board.py`

- [ ] Step 1 失败测试：FakeDb.phase_monitor.find 返回 northstar×1 + monthly×2（乱序），断言 board.northstar 取基线文档、months 按月升序、空集合时 months=[] + northstar=null + 缺失原因。
- [ ] Step 2 红。
- [ ] Step 3 实现：路由文件（prefix `/api/phase-monitor`，读 `phase_monitor` 集合 find({}) 内存分组）+ main.py 注册 + proxy 一行；`node --check ../proxy-server/routes/quantBoardProxy.js` 验语法。
- [ ] Step 4 绿 + Commit `feat(phase-monitor): board 读口 + proxy 白名单（northstar/monthly Mongo 装配）`。

## Task 4: 前端 types + service

**Files:** Create `src/types/phaseMonitor.ts`、`src/services/hotlist/phaseApi.ts`；Test `src/services/hotlist/__tests__/phaseApi.test.ts`

- [ ] Step 1 失败测试（vitest + vi.stubGlobal fetch mock 响应）：fetchPhaseHistory/fetchPhaseMonitorBoard 解构与透传、fetch 非 2xx 抛错。
- [ ] Step 2 红。
- [ ] Step 3 实现：类型（PhaseKind/PhaseDayDoc/PhaseNorthstarDoc/PhaseMonthlyDoc/PhaseBoard）+ 两个 fetch 函数（循 hotlistJevApi 模式）。
- [ ] Step 4 绿（`pnpm vitest run src/services/hotlist/__tests__/phaseApi.test.ts`）+ Commit `feat(frontend): 相位体系 service 与类型（phase-history/board 读口封装）`。

## Task 5: chip + 第 8 页签「相位验收」

**Files:** Modify `src/components/panels/HotlistEmotionPanel.vue`

- [ ] Step 1 overview hero chip：`phaseChip` computed（score≥50 进攻 / <50 防守 / null 相位不可用）+ hero 区模板插入（情绪分条旁，降级态 fail-visible）。
- [ ] Step 2 TABS 加 `{ key: 'phase', label: '相位验收', icon: '🎯' }` + ViewKey 推导自动扩展。
- [ ] Step 3 phase section：① 页头口径注记（sentiment_2b、M1 证据状态一行）② 走廊进度（months pass 序列 → streak/achieved computed）③ 北极星读数卡（offense/defense 机械线逐项+满仓对照；board 缺数据降级文案）④ ECharts 时间线（x=交易日、eodScore 线 + 50 阈值 markLine + 相位着色 markArea 段）⑤ 月度 pass 表。
- [ ] Step 4 script：refs + 懒加载（首次切到 phase 页签时 fetch 两个读口；v-show 切换后 nextTick 重渲染约定循 jev 先例）。
- [ ] Step 5 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过 + Commit `feat(frontend): 相位验收第 8 页签与 overview 相位 chip（时间线/北极星/走廊/监督线）`。

## Task 6: 存量迁移 + 验证 + 收口

- [ ] Step 1 重跑 `phase_northstar` 与 `phase_monitor_monthly --month 2026-09`（幂等 upsert → Mongo phase_monitor 2 文档）；`pymongo` 只读断言。
- [ ] Step 2 专项全绿：`pytest tests/research/test_phase_monitor_persistence.py tests/hotlist/ -q` + vitest phaseApi + vue-tsc。
- [ ] Step 3 收口记录追加到 `ranktrend-phase-m2-closure.md`（前端可见化节）+ Commit `docs(ranktrend): 前端可见化收口——迁移与验证记录`。

## 诚实边界

- chip 与时间线的阈值 50 前后端各有一份常量（后端 phase-history 服务端映射、前端 chip 常量）——单一口径源声明在两处注释互指；阈值变更=两处同改+标签重打。
- 首期监督线 S+A/insufficient 为 null，前端显示"人工补读"不显示 0。
- 走廊 streak 前端计算属展示逻辑；正式语义源仍是后端 corridor_state。
