# 量比计算优化进度

## 2026-05-18

- 创建专题目录 `docs/volume-ratio/`。
- 落地 `task_plan.md`、`findings.md`、`progress.md`。
- 明确本轮最小闭环：结构化量比结果、统一更新服务、实时更新后 stale/重算链路。
- TDD RED：为 `VolumeRatioCalculator` 增加 capped/suspicious 结构化诊断测试，初次运行失败，原因是 `calculateVolumeRatio` 尚不存在。
- TDD GREEN：新增 `calculateVolumeRatio` 结构化 API，旧 `calculateVolumeRatioValue` 保持兼容；`VolumeRatioCalculator.test.ts` 已通过。
- TDD RED：新增 `VolumeRatioUpdateService.test.ts`，初次运行失败，原因是统一服务文件不存在。
- TDD GREEN：新增 `VolumeRatioUpdateService`，可批量读取历史、调用结构化计算器并写回 `volumeRatio` / `volumeRatioMeta`；单测已通过。
- TDD RED：新增 `DataLayer` 实时成交量变更后量比 stale 测试，初次运行失败，原因是元信息仍保持 `fresh`。
- TDD GREEN：`DataLayer` 在实时投影更新成交量时仅标记 `volumeRatioMeta.status = stale`，不计算量比；`DataLayer.test.ts` 已通过。
- 接入 `DataLoaderFacade.updateVolumeRatios` 到 `VolumeRatioUpdateService`；`DataLoaderFacade.test.ts` 已通过。
- TDD RED：新增实时 flush changed codes 回调测试，先失败于 `onQuoteFlushed` 不存在。
- TDD GREEN：`RealtimeQuoteCoordinator` 支持 `onQuoteFlushed`，`DataLoaderFacade` 收到 changed codes 后调用统一量比服务。
- TDD RED：新增启动合并阶段写入 `volumeRatioMeta` 测试，先失败于只有裸 `volumeRatio`。
- TDD GREEN：`VolumeRatioUpdateService.enrichStocks` 在发布基础榜单前补齐结构化量比元信息，避免额外 `DATA.MERGED`。
- UI 防护：`DataTable` 对 stale/suspicious/unavailable 量比分别显示 `*`、`!` 和 `-`，并提供 title 诊断信息。
- 验证通过：定向 Vitest 4 个文件共 48 个测试通过；`vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过。
- TDD RED：新增 `StartupBundleService` 启动缓存 hydrate 测试，覆盖已有 `volumeRatioMeta.status = fresh` 和旧缓存裸 `volumeRatio` 两种场景，初次运行失败，原因是缓存量比仍被原样恢复。
- TDD GREEN：`StartupBundleService.read()` 在返回 bundle 前统一将缓存恢复出的量比元信息标记为 `stale`，旧裸量比补充 `volumeRatioMeta.status = stale` 和 `reason = startup_cache_hydrated`。
- 验证通过：量比相关定向 Vitest 5 个文件共 51 个测试通过；`vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过。
- TDD RED：新增 `VolumeRatioTrust.test.ts`，初次运行失败，原因是 `VolumeRatioTrust` helper 不存在。
- TDD GREEN：新增 `getTrustedVolumeRatio`，兼容无元信息的旧裸量比；当存在元信息时，只有 `fresh` 状态参与下游强信号。
- TDD RED/GREEN：RankTrend 状态分层、RankTrend 主计算、市场环境统计、个股速度预警、题材因子和题材关联度均补充可疑封顶量比测试，并接入 `getTrustedVolumeRatio`。
- TDD RED/GREEN：新增 `StockMergeCoordinator.test.ts`，移除合并器内裸量比计算，保证结构化量比只由 `VolumeRatioUpdateService` 补齐。
- 验证通过：量比相关扩展定向 Vitest 13 个文件共 107 个测试通过；`vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过。
- Review 修复 RED：补充实时量比刷新合并测试、题材质量标记原始非法量比测试、候选池/热榜兜底状态可信量比测试，初次运行均按预期失败。
- Review 修复 GREEN：实时 TDX flush 进入 `DataLoader` 待刷新 code 队列并 1 秒合并重算，避免 50ms 级别反复读取历史快照；候选池和热榜兜底状态改用 `getTrustedVolumeRatio`；题材质量标记恢复对原始 `stock.volumeRatio` 的非法数值检测。
- 验证通过：review 修复定向 Vitest 4 个文件共 59 个测试通过。

## 待验证

- 后续如需继续扩大范围，可审查快照导出、报表展示等非实时策略链路是否也需要保留 `volumeRatioMeta`。
