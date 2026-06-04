# 异动精灵进度记录

更新时间：2026-06-03

## 2026-06-03 五时间点收敛

目标：把竞价弱转强从“模式族评分 + 风险字段 + 状态机 + 复盘解释”收敛回实盘盯盘提醒。

当前验收口：

```text
09:20 baselineCaptured
09:25 auctionConditionPassed / auctionConditionFailed
09:30 gapAlert / noGap
09:35 trendConfirm / trendWeak
10:00 optionalFinalStatus
```

语音口径：

- `gapAlert` 可播。
- `trendConfirm` 可播。
- `auctionConditionPassed/auctionConditionFailed` 只展示不播。
- `noGap/trendWeak/optionalFinalStatus` 只更新状态，不作为硬阻断。

已完成：

- TS 检测器主链收敛为固定检查点输出，不再输出评分、置信度、因子、风险标签或前弱上下文。
- C# 检测器主链收敛为固定检查点输出，删除延迟确认、盘中状态机和旧评分分支。
- TS/C# fixture 改为黑盒 PASS/FAIL 验收，覆盖 `09:25` 不播、`09:30` 有缺口播、`09:35` 强确认播、`10:00` 不影响早盘播报。
- TS、C#、proxy/语音链路统一只按 `stage in gapAlert/trendConfirm` 授权语音。
- 跨交易日检查已补强：没有当日 `09:25` 确认基线时，`09:30` 不会自举产生 gap。
- 文档入口已清理为当前口径，历史过程记录仅保留废弃说明。

废弃：

- `09:24` 临门基线。
- `variant/score/confidence/factors/riskFlags/riskPenalty` 评分主链。
- `previousWeakScore` 前弱前置。
- `auction_gap_delayed_board` 和 `15:00` 延迟确认。
- `09:35-10:00` 主状态机。
- `dryRun`、质量门禁、proxy 授权播报作为语音前置。

## 当前验证命令

```powershell
pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts
node --test proxy-server/__tests__/openingSignals.test.mjs proxy-server/__tests__/docs.test.mjs
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
```

## 历史记录处理

2026-05 至 2026-06 初的 V3-V9 过程记录包含大量已废弃探索，例如模式族评分、复盘字段、流动性分层、状态机确认和延迟上板。为避免误导后续实现，旧过程不再保留为可执行计划；如需追溯，请使用 Git 历史查看。
