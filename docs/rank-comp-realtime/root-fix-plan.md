# 均榜/综合 999·-- 排查与回滚记录（前后端分离迁移撤销）

> 目录：`docs/rank-comp-realtime/`。来源：HANDOFF.md 遗留待办 + 2026-08-24 用户决策。
> **最终状态：已回滚前后端分离迁移（2026-08-24 晚）**。本文件替代原 HANDOFF.md。

## 0. 最终结论（先看这个）

**综合排名（compRank/avgRankNum）恢复前端本地实时计算，撤销 8-23 前后端分离迁移**：

- 前端 `ComprehensiveRankEngine`（`rankMergedStocks`）恢复为迁移前完整版（`b5cd1a7^`），`StockMergeCoordinator.merge` 恢复调用——八平台加权算均榜 + 五维算综合，**全部热榜股票都有排名**（浏览器实测 211/211 有 compRank 与 avgRankNum，无 999/--）。
- 后端 analyze 不再注入 compRank（`ranktrend_routes.py`、`api-cli.md` 恢复 HEAD 原样）；`comprehensive_rank.py` golden 保留（采集落库/回测/历史消费仍用），G2/G3/G4 信号后端化、五维 UI 改动保留。

**为什么回滚**（用户判定）：迁移把 compRank 输入绑定到后端快照/analyze，而热榜股票池是**实时动态变化**的——历史无快照记录的股票（新上市/今日新进热榜）会没有综合排名（曾实测 45 只、7 只无排名）。五维信号缺历史序列算不出来可接受，但综合排名是纯当前截面计算，不该因无历史记录而缺失。前端本地实时计算天然覆盖全部热榜股票（附件 HTML 原始逻辑即是如此）。

## 1. 排查过程摘要

- 现象：均榜 999、综合 "--"。
- 初判：startup-bundle 为 null（Redis 空）→ 前端 fallback。追查发现 bundle 是前端自写缓存、写入被拒，真断点是前端 `mergeSignalEnrichmentByCode` 漏复制 compRank/avgRankNum。
- 修复尝试（先后两版，均已回滚）：
  1. "后端快照权威行注入 compRank/avgRankNum"：快照只覆盖 221/224 只 → 45 只无排名（覆盖退化）。
  2. "前端实时算均榜 + analyze 用当前帧输入算 compRank"：历史无序列股票仍被 analyze 输出层过滤 → 7 只无 compRank。
- 用户判定：迁移本身设计缺陷（综合排名依赖后端快照/analyze，未考虑热榜池动态变化）→ 要求回滚迁移。
- 最终：恢复前端本地计算（ComprehensiveRankEngine.rankMergedStocks），全部热榜股票有排名。

## 2. 迁移相关提交（供回滚审计）

- `0ea572b`：后端 `comprehensive_rank.py` golden 生产（**保留**，采集/回测用）
- `b82835a`：StockMergeCoordinator 改继承后端 compRank（**已撤销**：恢复 `rankMergedStocks` 调用）
- `98ab74b`：采集器 providers.py 接线（**保留**，快照落库 compRank）
- `b5cd1a7`：删 ComprehensiveRankEngine 大部分（**已撤销**：恢复完整版）
- `990c69d`：当前帧 percentile 权威化（**保留**，信号计算修复，独立于综合排名）

## 3. 验证结果（新鲜）

- 前端 `pnpm test`：116 文件 / 945 用例全绿（theme 2 个 unhandled error 为既有全量并发 flaky，单跑全绿）
- `vue-tsc` 通过；后端 `test_ranktrend_analyze_api.py` 18 passed（HEAD 基线）
- 浏览器实测：211/211 热榜股票有 compRank 与 avgRankNum，均榜/综合全部显示真实值

## 4. 遗留/风险

- `python-bridge`（8765）进程在但端口未监听（用户环境进程，未擅自重启，行情实时链路待用户处理）。
- 8000 存在重复 uvicorn 进程（含我重启的 bash-8 与一个来源不明进程），8001 也有两个 collector 进程——建议用户统一用 DragonBoardLauncher 重启以收敛。
- 后端 `comprehensive_rank.py` golden 仍在（采集/回测消费），与前端本地计算并存；若后续要彻底移除需评估快照字段消费方。

## 1. 目标（5 句话以内）

1. 前端均榜（avgRankNum）/综合（compRank）不再依赖浏览器自写 startup-bundle 才能显示正确值。
2. 后端 analyze 对当前帧注入**权威口径** compRank（用最近快照帧的五维输入重算，不再用前端残缺值）。
3. 后端 analyze 对当前帧注入权威 avgRankNum（来自最近快照帧），前端回填。
4. 前端信号合并路径（mergeSignalEnrichmentByCode）不再丢失 compRank/avgRankNum/展示字段。
5. 恢复浏览器 startup-bundle 可写（写入校验需要 compRank>0，修好后自然恢复）。

## 2. 根因（2026-08-24 已浏览器实测闭环）

- MongoDB `dragonboard_live` 今日快照完整（采集器正常）；analyze 响应含 compRank（cache miss/hit 均实测）。
- 前端页面自动流程（`enrichSignalsInBackground` → 版本变化 → `mergeSignalEnrichmentByCode`）合并时**漏复制** `compRank`、`avgRankNum` 及多个 `_` 展示字段（`_rankTrendPct`/`_volumePriceScore`/`_lifecycle*`/`_synergy*`）。
- 实测证据：`rankTrend.meta.compRank=142` 存在而 `stock.compRank` undefined；手动回填后 UI 立即显示；`_resonancePct` 有值（被复制）而 `_rankTrendPct` 无（未复制）。
- 后端 `_inject_current_frame_comp_rank` 用**前端传来的 currentFrame.stocks**（avgRankNum=999、字段残缺）算 compRank → 数值失真。
- 浏览器自写 bundle 校验要求每只股票 `compRank>0`，compRank 未回填 → 写入被拒 → Redis 恒空 → 下次启动 fallback 999。

## 3. 改动清单

### 后端 `quant-board/backend/api/ranktrend_routes.py`
1. 新增 `_load_authoritative_rank_rows(repo, dataset_id, snapshot_type) -> dict[code, row]`：
   `repo.load_frame_bundles(dataset_id, snapshot_type, sort="desc", limit=1)` 取最近快照帧 rows（含 avgRankNum/zljzb/fundPenetration/turnoverRate/turnover）。
2. 改造 `_inject_current_frame_comp_rank(result, current_frame, authoritative_rows)`：
   - 用**权威行全集**调 `compute_comprehensive_scores`（全局基线 + 稳定序号）；
   - 对响应当前帧每只股票：`meta.compRank`、`meta.avgRankNum` 从权威行按 code 注入（缺失不注入，fail-visible）。
3. `_analyze_frames` 删除 current-frame compRank 计算与注入（统一由 _inject 处理，避免两处口径）。
4. `analyze_ranktrend`：`current_frame` 存在时统一加载权威行（`asyncio.to_thread`）并传入 _inject；cache hit/miss 同路径。

### 前端 `src/services/dataLoader/RankTrendSignalService.ts`
5. `precomputeDisplayFields`：新增 `avgRankNum` 回填（`meta.avgRankNum` finite 且 >0 时写 `stock.avgRankNum`）。

### 前端 `src/services/dataLoader/DataLoaderFacade.ts`
6. `mergeSignalEnrichmentByCode`：补全合并字段（compRank、avgRankNum、_rankTrendPct/_rankTrendDirection/_lifecycle*/_volumePrice*/_synergy* 等），与 `precomputeDisplayFields` 输出保持同步（注释 + 测试锁定）。

### 测试
7. `quant-board/tests/test_ranktrend_analyze_api.py`：
   - 方案 A 测试：断言 meta.avgRankNum 注入；compRank 断言适配权威行口径（FakeRepo 提供 rows）。
   - cache hit 测试：补 `create_repository` monkeypatch 返回 FakeRepo（权威行来源）。
8. 前端测试：`RankTrendSignalService.test.ts` 补 avgRankNum 回填；`DataLoaderFacade.test.ts` 补 merge 保留 compRank/avgRankNum 断言（若现有结构允许）。

### 文档
9. `quant-board/docs/api-cli.md`：analyze 合同补 `meta.compRank`（权威口径）+ `meta.avgRankNum` 说明。
10. 本计划归档：完成后把 HANDOFF.md 结论并入 `docs/rank-comp-realtime/`，删除工作区 HANDOFF.md。

## 4. 验证命令

```powershell
# 后端
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_analyze_api.py tests/test_comprehensive_rank.py tests/test_providers_comprehensive_rank.py
# 前端
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
# 浏览器实测（playwright）：综合列显示数字、均榜非 999、五维度正常、无控制台错误
```

## 5. 风险与回退

- compRank 数值口径变化（前端输入 → 权威快照行），属预期行为变更；golden 公式不变，仅输入源权威化。
- 观察面板单股 analyze 也会走 _inject，多一次最近帧读（limit=1，轻量）；如实测开销大可后续加短 TTL 缓存。
- 回退：本改动为增量修改，`git diff` 可单独回退 ranktrend_routes.py / 前端两文件。
