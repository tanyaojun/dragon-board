# 异动精灵任务计划

更新时间：2026-06-03

## 当前目标

异动精灵是独立 Windows GUI 盯盘工具，通过通达信 `.blk` 股票池、八平台热榜股票池和本地 L1 行情监控盘中异动，并用本地语音播报。它不承载回测、策略研究、参数优化或 QuantBoard 职责。

## 竞价弱转强验收口

当前只认五个固定时间点：

```text
09:20 baselineCaptured
09:25 auctionConditionPassed / auctionConditionFailed
09:30 gapAlert / noGap
09:35 trendConfirm / trendWeak
10:00 optionalFinalStatus
```

语音只认：

```text
09:30 gapAlert 可播
09:35 trendConfirm 可播
```

`09:25` 候选可展示不播，`10:00` 只是可选状态更新，不影响 `09:30/09:35` 播报。

## 成功标准

1. GUI 可选择 `T0002\blocknew` 目录，列出并加载一个或多个 `.blk` 文件。
2. 能把 `.blk` 中的 7 位通达信代码解析为标准 6 位股票代码，并过滤无效项。
3. 能使用八平台热榜作为股票池来源。
4. GUI 不启动 Dragon Board 前端、不调用选股通 API 作为竞价弱转强检测源。
5. 能连接或托管启动本地通达信 L1 行情桥，持续接收指定股票池行情。
6. V1 覆盖 L1 稳定可做的核心异动：封板、开板、即将开板、逼近涨跌停、急拉、跳水、翻红翻绿、日内新高新低、成交额跨档、成交增量加速、盘口买卖压、封单变化。
7. 语音播报支持启停、语速、音量、冷却、批量合并和测试播报。
8. 竞价弱转强黑盒验收只看五时间点 PASS/FAIL，不再断言评分字段。

## 非目标

- 不实现或宣称真 L2 十档、逐笔委托、官方选股通事件。
- 不在异动精灵中加入回测、策略研究平台、候选池打分平台或 QuantBoard 职责。
- 不把用户维护的股票池自动理解成前弱量化因子。
- 不新增 `09:24` 临门基线、评分器、风险扣分、状态机确认或延迟上板分支。
- 不让 `10:00` 或盘后结果反向影响 `09:30/09:35` 播报。

## 当前状态

| 模块 | 状态 |
|------|------|
| WinForms GUI | 已实现核心盯盘界面、设置、监控板块、导出、托盘和语音。 |
| `.blk` 监控池 | 已实现解析、过滤、加载和持久化。 |
| 八平台热榜股票池 | 已接入本地 proxy 拉取和订阅。 |
| L1 行情接入 | 已接入 `python-bridge` WebSocket；真 L2 不在当前范围。 |
| 普通 L1 异动规则 | 已实现并有测试覆盖。 |
| 竞价弱转强 | 已收敛到五时间点黑盒合同。 |
| 语音链路 | 已收敛为本地策略优先，弱转强只播 `gapAlert/trendConfirm`。 |

## 当前验证命令

```powershell
pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts
node --test proxy-server/__tests__/openingSignals.test.mjs proxy-server/__tests__/docs.test.mjs
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
```

## 已废弃历史计划

2026-05 至 2026-06 初的旧计划包含 `09:24` 临门基线、模式族评分、前弱上下文、`auction_gap_delayed_board`、`15:00` 延迟确认、`dryRun`、质量门禁、流动性分层、proxy 授权播报和 `09:35-10:00` 状态机等探索。这些内容已废弃，不再作为待办或需求来源；如需考古，请使用 Git 历史。
