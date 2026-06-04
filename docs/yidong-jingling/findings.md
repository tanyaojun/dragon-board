# 异动精灵调研发现

更新时间：2026-06-03

## 当前有效结论

异动精灵是实盘盯盘提醒工具，不是策略研究平台。“竞价弱转强”只按五个固定实盘时间点验收：

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
09:25 candidate 不播
09:35 trendWeak / 10:00 optionalFinalStatus 不作为硬阻断
```

## 业务边界

- `09:20` 只记录初始基线，包括价格、涨幅、成交额/量。
- `09:25` 只比较 `09:20 -> 09:25` 的量价关系，输出候选成立或失败；候选可展示但不语音。
- `09:30` 只比较 `09:25 -> 09:30` 是否出现跳空高开缺口；只有 `gapAlert` 可播。
- `09:35` 只判断 `09:30 -> 09:35` 是否高开高走、承接强、快速上攻；只有 `trendConfirm` 可播。
- `10:00` 只做可选最终状态和备注，不影响 `09:30/09:35` 已发生播报。
- 股票池只表示用户选择的监听范围，不自动转译为量化前弱因子。

## 已废弃历史口径

下列内容曾出现在早期调研、评审或实现记录中，现在全部废弃，不得作为后续实现依据：

- `09:24` 临门基线或 `09:24:50-09:25:10` 作为弱转强必要检查点。
- `variant/score/confidence/factors/riskFlags/riskPenalty` 模式族评分主链。
- `previousWeakScore/previousWeakSource/previousWeakSignals` 前弱上下文主链。
- `auction_gap_delayed_board`、盘后或 `15:00` 延迟确认。
- `09:35-10:00` 状态机主链、`pending/watch/confirmed/failed/watch_only` 语音优先级。
- `dryRun`、演练模式、质量门禁、流动性分层 `review_only` 作为播报前置条件。
- proxy `voiceOwner` 作为桌面端语音授权门槛；桌面端以本地语音策略为准，proxy 只做同步记录。

## L1 能力边界

- 当前已跑通的是 `7709 / L1 + 标准五档 + 本地 WebSocket`。
- 即将开板、盘口买卖压等规则只能按 L1 五档聚合盘口估算，不代表真 L2 十档、逐笔委托或完整队列。
- 真 L2、逐笔、主力资金、主动买卖盘等能力不在异动精灵当前承诺范围内。

## 有效文档入口

- 当前弱转强合同：`docs/yidong-jingling/opening-weak-to-strong-plan.md`
- 桌面异动规则：`docs/yidong-jingling/event-rule-logic.md`
- 使用说明：`docs/yidong-jingling/usage.md`
- 黑盒 fixture：`docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json`
