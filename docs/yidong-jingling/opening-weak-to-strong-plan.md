# 竞价弱转强收敛设计

更新时间：2026-06-03

## 当前有效口径

异动精灵的“竞价弱转强”是实盘盯盘提醒，不是策略研究平台。主链只看固定实盘时间点：

```text
09:20 baselineCaptured
09:25 auctionConditionPassed / auctionConditionFailed
09:30 gapAlert / noGap（兼容阶段名，含义为开盘承接转强）
09:35 trendConfirm / trendWeak
10:00 optionalFinalStatus
```

语音只认：

```text
09:30 gapAlert 可播
09:35 trendConfirm 可播
09:25 candidate 不播
09:35 trendWeak / 10:00 optionalFinalStatus 不作为硬阻断
```

`10:00` 只是最终状态更新和备注，不是弱转强提醒的必要条件，也不得影响 `09:30` 或 `09:35` 已经发生的播报。

## 时间点合同

| 时间 | 事件 | 判断 | 产品动作 |
|------|------|------|----------|
| `09:20` | `baselineCaptured` | 记录价格、涨幅、成交额/量，作为不可撤单阶段起点。 | 内部基线，不展示为异动，不语音。 |
| `09:24:50-09:25:10` | 内部临门基线 | 覆盖行情桥广播转发延迟，记录临近集合竞价结束前的价格、涨幅和成交额，用于尾段抢筹确认。 | 内部基线，不作为独立 checkpoint，不展示为异动，不语音。 |
| `09:25` | `auctionConditionPassed` / `auctionConditionFailed` | 同时对比 `09:20 -> 临门基线` 总量价和 `09:24:50 -> 临门基线` 尾段量价，确认是否满足弱转强候选基础条件。 | 可展示“竞价弱转强候选/候选不成立”，不语音。 |
| `09:30` | `gapAlert` / `noGap` | 对比临门竞价和开盘第一窗口，判断是否相对竞价明显改善、未继续杀破竞价价且成交额承接。`gapAlert` 仅作为兼容阶段名，不再表示必须跳空高开。 | `gapAlert` 进入语音链路；`noGap` 只记录。 |
| `09:35` | `trendConfirm` / `trendWeak` | 判断 `09:30 -> 09:35` 是否承接延续、站上或守住开盘承接区并继续优于临门竞价涨幅。 | `trendConfirm` 提示“开盘反攻确认”；`trendWeak` 只更新状态。 |
| `10:00` | `optionalFinalStatus` | 汇总当前价格和状态。 | 只做状态更新/复盘备注，不播报，不阻断。 |

## 正式信号合同

跨 TS、C#、proxy 的正式 `OpeningWatchSignal` 只保留 10 个字段：

| 字段 | 说明 |
|------|------|
| `stage` | 当前时间点事件。 |
| `status` | 与 `stage` 同口径的当前状态。 |
| `code` / `name` | 股票代码和名称。 |
| `time` | 当前时间点报价时间。 |
| `price` / `pct` | 当前观察价格和涨幅。 |
| `amount` | 当前成交额。 |
| `voiceEligible` | 是否允许进入语音链路；只有 `gapAlert` 和 `trendConfirm` 为 `true`。 |
| `reason` | 面向盯盘的短解释。 |

`signalType`、`tradingDate`、`triggerAt`、`auctionFinalPrice`、`auctionPct`、`officialOpen`、`firstWindowPrice`、`jumpPctPoint`、`baselineQuality`、`ruleVersion`、`configHash` 等只允许作为内部 detector/debug/telemetry/export 字段存在，不进入 proxy OpenAPI 的正式 `signal` 合同，也不参与语音仲裁。

`variant`、`score`、`confidence`、`factors`、`riskFlags`、`riskPenalty`、`previousWeakScore`、`intradayStatus` 属于旧评分/状态机合同。当前 TS/C# 主链、fixture、proxy OpenAPI 和语音链路不得输出或依赖这些字段；只有历史日志或历史 Git 记录里可能看到。

## 明确保留与废弃

- `09:24` 临门基线恢复为内部量价辅助基线，只参与 `09:25` 候选成立/失败判断；它不是独立 checkpoint，不参与语音仲裁，也不恢复旧状态机。
- 不再把 `score/confidence/factors/riskPenalty` 作为提醒主链。
- 不再把 `previousWeakScore` 或用户自选池语义当作量化前置条件。
- 不再新增或维护 `auction_gap_delayed_board`、收盘/`15:00` 延迟确认这类越界分支。
- 不再把 `09:35-10:00` 设计成主状态机；`10:00` 只是可选更新。

## 组件职责

| 组件 | 职责 |
|------|------|
| `OpeningAuctionStateStore` | 保存 `09:20` 初始基线和 `09:25` 确认基线。 |
| `OpeningWeakToStrongDetector` | 输出五个时间点的 `stage` 信号。 |
| `OpeningRealtimeEventBuffer` | 把 `stage` 信号转换成本地异动事件，并按阶段去重。 |
| `HotStockEventSpeechService` / `EventVoicePolicy` | 只按 `voiceEligible + stage` 判断语音资格。 |
| `proxy-server /api/opening-signals` | 保存跨端信号和来源，不引入评分仲裁。 |
| 桌面和网页 UI | 展示候选、跳空、趋势确认和最终备注，不解释成策略研究结果。 |

## 验收命令

```powershell
pnpm test src/services/hotlist/__tests__
node proxy-server/__tests__/openingSignals.test.mjs
node proxy-server/__tests__/docs.test.mjs
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

黑盒验收只看四个实盘提醒点和一个可选最终状态是否输出正确 PASS/FAIL，不再要求人工逐行审计评分因子。
