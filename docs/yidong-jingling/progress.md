# 异动精灵 V1 进度记录

## 2026-06-02 V7 盯盘工具回归本位

- **目标：** 竞价弱转强链路从"研究型质量门禁"回归"盯盘提醒工具"，语音主链只保留 6 类硬阻断，质量信息降级为风险标签。
- **产品原则沉淀：**
  - 语音主链只解决盘中及时提醒，不承载量化研究。
  - 质量信息只做标签（风险字段、日志、导出），不做默认禁播。
  - dryRun 只保留为人工显式演练模式 + 时间戳不可信自动保护。
  - proxy 降级为跨端去重同步，桌面版本地播报优先。
- **V7 Phase 1：文档和设置口径收敛**
  - `opening-weak-to-strong-plan.md`：新增 V7 产品原则章节，更新 dry-run 口径和离线矩阵。
  - `event-rule-logic.md`：竞价弱转强拆为"硬阻断 / 风险标签 / 语音控制"三层。
  - `usage.md`：明确桌面语音优先本地播报，proxy 只做跨端去重。
- **V7 Phase 2：桌面端语音链路瘦身**
  - `MainForm.ReportOpeningSignalsAndAnnounceAsync`：改为本地播报优先（fire-and-forget），proxy 上报异步补充不阻塞。
  - `SettingsForm`：热榜语音提示改为"仅过滤语音，不过滤异动列表"。
  - `EventVoicePolicy`：已符合 V7 口径（仅处理语音模式、preopen 候选不播、dryRun 不播），无需修改。
- **V7 Phase 3：检测器硬阻断复核**
  - TS/C# `RiskFlag` 函数：覆盖/画像/金额类风险从 medium/-35 收敛为 low/-5~-10，只保留时间错位类为 medium/-35。
  - 共享 fixture 新增 3 个 V7 验收用例：低覆盖仍可播、缺画像仍可播、时间错位 dryRun。
  - 受影响 fixture 用例（`auction-coverage-low-dry-run`、`auction-coverage-rounded-low-dry-run`、`auction-amount-missing-downgraded`、`amount-regressed-downgraded`）期望值同步更新。
- **V7 Phase 4：跨端 proxy 角色降级**
  - 桌面端不等待 proxy `voiceOwner` 授权（Phase 2 已实现）。
  - 网页端 `resolveVoiceOwner` 已符合：proxy 在线时尊重仲裁，离线时降级为 `'web'` 本地播报。
  - proxy `shouldGrantVoice` 已正确：dryRun/preopen_candidate/failed 不授权语音。
- **验证：**
  - TS opening 链路 7 files / 51 tests passed。
  - C# `YiDongJingLing.Tests` 48 tests passed。
  - proxy opening signal 11 tests passed。
  - `vue-tsc` typecheck 通过。
  - `dotnet build -c Release` 0 warning / 0 error。
  - `pnpm build` 通过。
  - `git diff --check` 通过。

## 2026-05-30 V5 后优化：参数化 + 代码审查修复 + 热榜语音过滤

- **目标：** 基于市场研究校准评分参数，修复 P0/P1 代码问题，新增热榜前 N 名语音过滤。
- **使用流程：**
  - 使用 `superpowers:brainstorming` 做诊断和方案设计。
  - 使用 `planning-with-files:plan-zh` 组织任务规划。
  - 使用 `/code-review` 做变更审查并修复发现的问题。
- **市场研究：**
  - 搜索同花顺、通达信、东方财富、淘股吧、雪球、BigQuant 等平台的集合竞价特征。
  - 核心发现：量能相对放大 > 绝对金额；高开 2.5%-5% 是黄金区间；跳空是最强信号。
  - 16 个评分因子全部从硬编码提取为 `OpeningWeakToStrongRules` 可配置字段，默认值基于研究校准。
- **P0 修复：**
  - 移除 `AuctionLateLiftAmountDeltaMin` / `AuctionLateLiftLateAmountDeltaMin` 从 ConfigHash，加废弃注释。
  - `low_open_red_reversal` 硬编码 `auctionPct <= 0` 改为使用 `auctionWeakMaxPct`。
  - C# `previousWeakSource` factor 只在非空时添加，与 TS 一致。
- **P1 修复：**
  - 16 个评分因子参数化，从 fixture JSON 统一加载。
  - TS 时间解析从 3 层回退简化为单一路径，删除 ~40 行。
  - `riskFlag` 函数从 12 行 case-by-case 简化为 3 分类。
  - 画像缺失扣分从 -35 降至 -10。
  - `riskFlags.Length > 0 ? "watch"` 闸门移除，confidence 纯分数决定。
- **热榜语音过滤：**
  - `AppSettings` 新增 `HotlistTopVoiceCount`（默认 0=不限）。
  - `MainForm` 新增 `_orderedHotlistCodes`，按平台覆盖数降序排列。
  - `ApplyHotlistTopVoiceFilter` 在语音播报前过滤非前 N 名股票。
  - 设置页语音播报区域新增输入框，仅在八平台热榜时可见。
- **代码审查修复（Medium/Low）：**
  - M1：废弃字段在 TS/C# 双端加 `@deprecated` / `<summary>` 标记。
  - M2：`secondsOfDay` 对畸形时间戳输出 `console.warn`。
  - M3：`ApplyHotlistTopVoiceFilter<T>(ref T)` 简化为 `ApplyHotlistTopVoiceFilter(IList<EventRecord>)`。
  - L1：热榜播报行从 `Enabled=false` 改为整行 `Visible=false`。
- **文档同步：** 更新 `opening-weak-to-strong-plan.md`、`findings.md`、`progress.md`、`task_plan.md`。
- **验证：**
  - C# 53 tests passed。TS 7 files / 48 tests passed。
  - `vue-tsc` typecheck 通过。`pnpm build` 通过。`dotnet build -c Release` 0 warnings/0 errors。

## 2026-05-25 V6 竞价弱转强盘中确认闭环

- **目标：** 按用户反馈，把 V6 从“盘后/人工复盘字段”修正为 `09:20-10:00` 盘中确认闭环；异动精灵/异动雷达服务盘中行动提示，不把人工复盘作为信号前置条件。
- **已实现：**
  - 文档 V6 主线改为：`09:20-09:25` 保存不可撤单阶段量价证据，`09:25:00-09:29:59` 输出严格候选 `preopen_candidate`，`09:30-09:35` 升级 `pending`，`09:35-10:00` 自动更新 `confirmed/failed`。
  - TS/C# `OpeningWeakToStrongSignal` 增加 `intradayStatus/intradayOutcome/intradayStatusAt/intradayPrice/intradayPct/intradayAmount/intradayNote`。
  - TS/C# 检测器同一 `opening_weak_to_strong` 信号支持 9:25 早期候选、9:30 开盘承接、盘中确认成功和跌破支撑失败更新；确认成功必须已通过 `09:30-09:35` 的 `pending` 开盘承接，早期候选不能绕过开盘验证直接确认。
  - Web 实时缓冲和 proxy canonical 选择改为盘中结果优先，允许 `failed` 覆盖早先 `strong/pending`；语音按行动阶段授权，但 2026-06-02 已修正为 `preopen_candidate` 只记录不播，`pending/confirmed` 才可获得语音授权。
  - 桌面端 `L1EventEngine` 不再用同股同日首发锁压住盘中确认/失败更新；CSV 导出追加盘中状态列。
  - V6 不新增规则字段；`09:25:10` 候选窗口、`10:00` 收口和 `+1.0pct` 盘中确认推进作为状态机常量，不进入 `configHash`，规则指纹保持 `owts-08f44efb`。
- **验证：**
  - RED：新增 TS fixture/buffer/proxy/C# 测试后，先失败于盘中窗口和状态更新缺失。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts`：2 files / 10 tests passed。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts`：6 files / 40 tests passed。
  - `node --test proxy-server/__tests__/openingSignals.test.mjs proxy-server/__tests__/docs.test.mjs`：9 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：All YiDongJingLing tests passed。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warning / 0 error。
  - `pnpm build`：通过。
  - `git diff --check`：通过。
- **Agent review 状态：** 已尝试启动只读 Agent 评审，但当前 sub-agent thread limit reached；待释放线程后补做提交前 code review。
- **Agent review 收口：**
  - Critical 修复 1：V6 状态机常量不进入 TS/C# 规则对象和 `configHash`，规则指纹恢复 `owts-08f44efb`。
  - Critical 修复 2：`preopen_candidate` 不能在 `09:35-10:00` 绕过 `pending` 直接升级为 `confirmed`。
  - Important 修复 1：proxy `voiceOwner` 改为只在“本次上报成为 canonical 且 canonical 非 failed/watch”时授权，补 `failed` 先入库、迟到 `strong/pending` 不授权语音的回归测试。
  - Important 修复 2：桌面端 `EventDeduper` 记录弱转强盘中状态优先级，允许 `pending -> confirmed/failed` 在 30 秒冷却内继续发出，补回归测试。
  - Important 修复 3：OpenAPI `opening-signals` schema 补齐 `intradayStatus/intradayOutcome/intradayStatusAt/intradayPrice/intradayPct/intradayAmount/intradayNote`，并补文档测试。
  - Minor 补强：补 `09:25:10` 边界、候选不直达确认、`configHash` 保持旧值回归测试；CSV 导出按列名断言盘中状态列和值对齐。
- **最终验证：**
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts`：6 files / 40 tests passed。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs`：10 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：All YiDongJingLing tests passed。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warning / 0 error。
  - `pnpm build`：通过。
  - `git diff --check`：通过。

## 2026-05-24 V5 竞价弱转强实现落地

- **目标：** 按 V5 方案把竞价弱转强从固定成交额阈值驱动，改为 `09:20-09:25` 不可撤单阶段双基线和量价协同驱动。
- **改动：**
  - 共享 fixture 增加 V5 强播、降级、拒绝样例，并为保留强信号的旧样例补齐 `09:20/09:24/09:25` 量价过程。
  - TS/C# `OpeningAuctionStateStore` 显式输出 `09:20` 初始基线、`09:24` 临门基线、`09:25` 确定基线。
  - `minCurrentAmount/minAmountDelta` 不再硬拒绝强播；新增 `openingLiquidityMinAmount=500万` 最低流动性保护，旧阈值保留为评分增强。
  - `auction_late_lift` 改用相对价格抬升、相对成交额放大和临门确认；新增 `auctionAmountLiftRatio/lateAmountLiftRatio/priceVolumeConfirmed` 等复盘字段。
  - 缺竞价画像、缺 09:20 初始基线或竞价量价未确认都只作为风险扣分；真实弱竞价、强开盘的 `auction_gap_reversal` / `low_open_red_reversal` 不再被量价核心一票否决。
  - V5 规则指纹更新为 `owts-08f44efb`，TS/C# hash 字段集合同步。
- **验证：**
  - RED：`pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts` 先失败于 V5 新口径。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts`：3 files / 13 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：All YiDongJingLing tests passed。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：通过。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs`：8 tests passed。
  - `pnpm build`：通过。
- **复核修正：**
  - 只读 code review 发现 `HasOpeningCoreEvidence` 使用绝对值会把下跌/缩量误判为核心证据；后续 2026-06-02 已彻底移除该主链硬门槛。
  - 复核发现 `priceVolumeConfirmed` 未强制 `09:24-09:25` 临门确认；后续 2026-06-02 已调整为仅约束 `auction_late_lift` 子形态，不再阻断开盘跳变转强。
  - 复核后重跑 TS opening 链路、桌面测试和类型检查均通过。

## 2026-06-02 集合竞价量价硬门槛修正

- **目标：** 修正竞价弱转强被 `09:20->09:25`、`09:24->09:25` 量价确认过度卡死的问题。
- **改动：**
  - 移除 `auction_price_volume_core_missing` 对主信号的 high/-100 一票否决。
  - 将 `auction_price_volume_unverified` 调整为低风险小扣分。
  - 共享 fixture 更新弱竞价、强开盘但竞价量价未确认的样例，预期为 `auction_gap_reversal` / `strong`。
  - `auction_coverage_low` 不再触发 `dryRun`；覆盖率不足只保留风险提示，时间戳不可信仍保持 dryRun。
  - `preopen_candidate` 候选阶段不再授予语音；候选仍可展示/上报，真正播报等 `09:30-09:35` 开盘承接转强。
  - `preopen_candidate` 不再只认竞价量价齐升：若 09:25 基准偏弱，且有最低流动性或昨日弱势上下文，也会作为无声 `auction_gap_reversal` 观察候选，并标记 `auction_price_volume_unverified`。
  - 桌面端新增拒绝原因 telemetry：`detector_rejected` 和 `event_suppressed_duplicate_or_lower_priority` 写入 `logs/yidong-jingling/opening-weak-to-strong/*.jsonl`，保留 `invalidReason`、关键涨幅、跳变、成交额和风险标记。
- **验证：**
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts`：9 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：All YiDongJingLing tests passed，包含拒绝原因 telemetry 用例。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj`：0 warnings, 0 errors。

## 2026-05-24 V6-A 复盘字段方案启动

- **目标：** 把 V6 先收敛为“实盘复盘闭环 + 流动性分层观测”，避免在缺少真实样本前继续堆强播阈值。
- **流程：**
  - 使用 `planning-with-files` 继续在 `docs/yidong-jingling/` 维护计划、发现和进度。
  - 使用 `executing-plans` 执行前先审查计划；按流程从 `main` 切出 `codex/yidong-jingling-v6-review-fields` 分支。
  - 安排三个只读 Agent 做交叉评审：规则口径、实现影响、测试验收。
- **评审结论：**
  - V6-A1 只补实时信号复盘字段和流动性分层观测字段。
  - `liquidityTier` 固定为 `review_only`，不得影响 `triggered/variant/confidence/score/dryRun/riskFlags`。
  - 不新增规则字段，不改变 V5 `configHash`。
  - 桌面 CSV 导出和 proxy 上报必须验证新字段透传。
  - `09:35/收盘 outcome 写回` 进入 V6-A2，不在本轮把检测器扩成复盘存储系统。
- **已更新：**
  - `docs/yidong-jingling/opening-weak-to-strong-plan.md`
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
- **验证：** 文档和评审阶段，尚未改生产代码。

## 2026-05-24 V6-A1 复盘字段实现

- **目标：** 在不改变竞价弱转强触发、评分、语音、高亮和 `configHash` 的前提下，补齐实时信号复盘字段和流动性分层观测字段。
- **已实现：**
  - TS/C# `OpeningWeakToStrongSignal` 同步增加 `lateBaseline*`、`auctionAmountDelta`、`lateAmountDelta`、`liquidityTier*` 等 V6-A1 字段。
  - C# `OpeningWeakToStrongResult -> OpeningWeakToStrongSignal` 映射补齐新字段，避免 positional record 错位。
  - 桌面 CSV 导出新增 `09:20/09:24/09:25` 基线、价量增量、放大比、量价确认和流动性分层列。
  - proxy 生产路由保持宽进宽出，新增测试证明 `canonicalSignal`、`reportsBySource` 和 `/today` 返回保留 V6-A1 字段。
- **验证：**
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts` 4 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 全部通过。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs` 6 tests passed。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts` 13 tests passed。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs` 8 tests passed。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` 0 warning / 0 error。
  - `pnpm build` 通过。
  - `git diff --check` 通过。
- **待办：** 等待提交前只读 Agent code review 结论，若有 Critical/Important 反馈则修复后重跑相关验证。

## 2026-05-25 V6-A1 code review 收口

- **Agent code review：** Critical 无；Important 指出 TS `OpeningWeakToStrongSignal` 将 `liquidityTier*` 定义为可选，而 C# 信号合同为必填，存在合同漂移风险。
- **处理结果：**
  - TS `OpeningWeakToStrongSignal` 的 `liquidityTier/liquidityTierMode/liquidityTierBasis/liquidityTierThresholds/liquidityTierVersion` 改为必填。
  - 补强桌面上报 payload、CSV 导出、proxy 透传和 OpenAPI 文档断言，覆盖 `liquidityTierBasis/liquidityTierThresholds`。
- **最终验证：**
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts` 15 tests passed。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 全部通过。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs` 8 tests passed。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` 0 warning / 0 error。
  - `pnpm build` 通过。
  - `git diff --check` 通过。

## 2026-05-24 V5 竞价弱转强交叉评审和计划

- **目标：** 按用户要求，在动代码前安排 Agent 交叉评审 V5 方案和实施计划，重点解决“固定成交额阈值过于保守，强播应更看重 09:20-09:25 量价关系抬升”的规则问题。
- **使用流程：**
  - 使用 `planning-with-files` 继续把方案、发现和进度落在 `docs/yidong-jingling/`。
  - 使用 `superpowers:dispatching-parallel-agents` 安排三个只读 Agent 并行评审：规则口径、实现影响、测试验收。
  - 暂停生产代码修改，先完成 V5 方案和任务计划沉淀。
- **评审结论：**
  - V5 不需要重写检测器，应把现有 `auctionProfile` 升级为显式 `09:20` 初始基线 + `09:25` 确定基线。
  - `minCurrentAmount=3000万`、`minAmountDelta=2000万`、`auctionLateLiftAmountDeltaMin=800万`、`auctionLateLiftLateAmountDeltaMin=500万` 不再作为强播核心，只做最低流动性保护、风险或评分增强。
  - 强播核心改为不可撤单阶段量价协同、临门确认、09:25 不明显回落、09:30-09:35 开盘承接。
  - V5 实现必须先补共享 fixture RED 用例，再同步 TS/C# 检测器、hash、导出和文档。
- **已更新：**
  - `docs/yidong-jingling/opening-weak-to-strong-plan.md`
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
- **验证：** 方案评审和文档阶段，未修改生产代码，未运行测试。

## 2026-05-24 异动规则文档和设置页注解

- **目标：** 将所有桌面端 L1 异动类型的判断和计算逻辑沉淀为文档，并在设置页“异动类型”列表的事件名后展示简要规则注解。
- **使用流程：**
  - 使用 `planning-with-files` 将产物落在 `docs/yidong-jingling/` 专题目录。
  - 使用 `superpowers:test-driven-development` 先补 RED 测试，再实现 GUI 注解。
- **改动：**
  - 新增 `docs/yidong-jingling/event-rule-logic.md`，覆盖全部 `L1EventType` 的数据字段、公式、阈值来源、去重影响和特殊边界。
  - 设置页左侧异动类型从纯事件名改为“事件名 - 简要规则”，例如“封涨停板 - 涨停价+买一封单”。
  - 注解只影响 `ToString()` 显示，配置保存仍按 `L1EventType.ToString()`，不破坏既有设置文件。
  - 新增测试 `Settings form annotates event type options`，锁定每个设置页事件项都带规则注解。
- **验证：**
  - RED：`dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 先失败于 `all options include rule notes`。
  - GREEN：`dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` 失败：默认 Release 输出被当前运行中的 `YiDongJingLing (19068)` 锁定，未强制结束用户进程。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release -p:OutputPath=D:\dragon-board\.tmp\YiDongJingLing-build\` 通过，0 warnings / 0 errors。
  - `git diff --check` 通过。

## 2026-05-22 V3 代码审查修复

- **目标：** 修复竞价弱转强首版实现中的高风险缺口，重点是跨日状态、Web 实时链路可靠性、proxy dry-run 合并和 bridge 采样时间。
- **使用流程：**
  - 使用 `superpowers:using-superpowers`、`superpowers:receiving-code-review`、`superpowers:test-driven-development`。
  - 使用 `planning-with-files` 更新专题进度。
- **修复内容：**
  - TS/C# 竞价基线加入交易日维度，避免隔夜运行复用昨日 `09:25` 基线。
  - 桌面端 `L1EventEngine` 的 `OpeningWeakToStrong` 触发状态改为按交易日记录，避免次日同股信号被昨日状态压住。
  - 桌面端 `EventDeduper` 允许同股同批保留 `OpeningWeakToStrong` 和一个普通最高优先级事件，避免竞价信号被快速拉升等事件吞掉。
  - Web `OpeningRealtimeEventBuffer` 支持同日 `watch -> strong/critical` 升级，不再首个弱信号后永久丢弃更强信号。
  - Web `HotStockEventMonitorService` 在选股通/同花顺 HTTP feed 离线时仍保留 WebSocket 推导出的本地 opening 信号，避免主数据源被辅助源拖住。
  - Web `OpeningRealtimeEventBridge` 从 `preClose/code/name` 推导 `limitUpPrice`，让真实 quote path 可命中 `strong_open_board_attempt`。
  - Web 上报 proxy 失败时，仍把本地强信号写入异动雷达并允许网页端本地语音降级播报。
  - proxy canonical 选择优先真实信号，避免 dry-run 高分信号遮蔽后续实盘信号。
  - `python-bridge` 使用批次 fetch 开始时间作为 quote `capturedAt/sourceTs`，并用采样周期起止判断是否覆盖 `09:24:50-09:25:10` 强制窗口，降低慢批次错过窗口的风险。
- **新增/扩展测试：**
  - TS 检测器跨日基线污染测试。
  - TS realtime buffer 跨日再次触发和同日信号升级测试。
  - Web bridge proxy 失败降级、真实 quote path 推导涨停价测试。
  - Web monitor HTTP feed 离线仍展示 opening 信号测试。
  - C# 检测器跨日基线、桌面 engine 跨日触发状态、EventDeduper 保留 opening 信号测试。
  - proxy dry-run 被真实信号替换测试。
  - python-bridge 采样窗口覆盖和 quote capture 时间测试。
- **验证：**
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts src/components/common/__tests__/DataTable.test.ts`：33 项通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `pnpm build`：通过。
  - `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs`：8 项通过。
  - `python -m py_compile python-bridge\main.py`：通过。
  - `python python-bridge\test_monitor.py`：4 项通过。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

## 2026-05-22 V3 竞价弱转强实现落地

- **目标：** 按用户确认开工，把“竞价弱转强”同时落到网页板异动雷达、桌面版 `YiDongJingLing.exe` 和 Dragon Board 主行情表。
- **使用流程：**
  - 使用 `superpowers:subagent-driven-development` 做实现阶段协调。
  - 使用 `superpowers:test-driven-development` 约束新检测器、proxy API、Web 事件桥和桌面上报路径。
  - 使用 `planning-with-files` 同步计划、发现和进度。
  - 安排子 Agent 对 Web/proxy 链路和桌面链路做只读交叉复核，并按复核结果补齐缺口。
- **核心改动：**
  - 新增共享 golden fixture：`docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json`。
  - 新增 TS 检测器和 C# 检测器，统一支持 `auction_gap_reversal`、`low_open_red_reversal`、`strong_open_board_attempt`，并输出 `score/confidence/factors/riskFlags`。
  - `python-bridge` 在 `09:24:50-09:25:10` 强制广播 quote patch，payload 增加 `capturedAt/bridgeTs`、采样统计和 `lastPriceSource`，且不再把 `last_close` fallback 当成有效当前价。
  - `proxy-server` 新增 `/api/opening-signals` 和 `/api/opening-signals/today`，只缓存和仲裁已生成信号，不采样行情、不计算策略。
  - 网页端新增 `OpeningRealtimeEventBridge`，监听 WebSocket `FULL_STATE/QUOTE_PATCH`，命中后 POST proxy，进入 `HotStockEventMonitorService`，并按 `voiceOwner=web` 控制本地语音。
  - 桌面端新增 `OpeningSignalReporter`，`OpeningWeakToStrong` 命中后上报 proxy，只有 `voiceOwner=desktop` 时播报；proxy 不可用时降级本地播报并记录日志。
  - `DataTable.vue` 只读 `/api/opening-signals/today`，在名称列显示“竞强”徽标，并做行级高亮。
- **仍需实盘确认：**
  - 第一轮早盘仍需在 `09:24:50-09:25:10` 观察 100-300 只监控池的 `capturedAt/bridgeTs` 覆盖率。
  - `dryRun` 开关 UI 尚未完成；目前检测器和 proxy 合同支持 `dryRun` 字段，默认实盘路径按正常信号执行。
- **验证：**
  - `python -m py_compile python-bridge/main.py`：通过。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts`：5 项通过。
  - `pnpm exec vitest run src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/components/common/__tests__/DataTable.test.ts`：26 项通过。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `node --test __tests__\openingSignals.test.mjs`：5 项通过。
  - `node --test __tests__\docs.test.mjs`：2 项通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `pnpm build`：通过。
  - `git diff --check`：通过。

## 2026-05-22 子 Agent 方案交叉评审

- **目标：** 按用户要求使用 `superpowers:subagent-driven-development` 思路，安排子 Agent 对 V3 竞价弱转强方案做交叉评审。
- **评审方式：**
  - 行情数据可行性：检查 `python-bridge`、WebSocket、桌面 quote 字段和 09:25 采样链路。
  - 规则口径：检查模式族、误报控制、评分和风险标记。
  - 三端架构：检查网页板、桌面版、主表、proxy、DataLayer、QuantBoard 边界。
  - 测试验收：检查统一 fixture、dry-run、早盘联调、日志和离线矩阵。
- **结论：**
  - 四个评审均为“有条件通过”。
  - 最大风险是仅监听 `QUOTE_PATCH` 不能证明 09:25 每只票都被采到，需要强制采样或强制快照。
  - proxy 事后去重不能阻止网页和桌面重复语音，需要 `voiceOwner` 仲裁。
  - `strong_open_board_attempt` 需要弱转强前置条件，否则容易漂成普通开盘冲板。
  - TS/C# 必须共用一份 golden fixture，不能只靠口头同口径。
  - 第一轮实盘应先 dry-run，只记录不播报不强高亮。
- **已更新：**
  - `docs/yidong-jingling/opening-weak-to-strong-plan.md`
  - `docs/superpowers/specs/2026-05-22-opening-weak-to-strong-design.md`
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
- **验证：** 文档方案阶段，未改生产代码。

## 2026-05-22 竞价弱转强规则族复核

- **目标：** 回应用户提醒，避免把 `002552 宝鼎科技` 单一样例写死成全部“竞价弱转强”规则。
- **使用流程：**
  - 使用 `superpowers:brainstorming` 做规则抽象。
  - 使用 `planning-with-files` 同步发现、方案、任务计划和 Superpowers 规格文档。
  - 联网检索官方交易规则、短线社区和量化文章口径，按来源可靠性分层采纳。
- **结论：**
  - 官方规则只用于确认时间窗口、撤单边界、开盘价口径和集合竞价成交价原则。
  - 游资/社区经验可归纳为“预期差 + 放量承接 + 板块/地位确认”，不能照搬成硬公式。
  - V3 方案改为模式族：`auction_gap_reversal`、`low_open_red_reversal`、`strong_open_board_attempt` 第一版可做；前日分歧修复、竞价尾盘抬升作为增强或后续扩展。
  - 共享信号合同增加 `variant`、`score`、`confidence`、`factors`、`riskFlags`，用评分分层控制语音和主表高亮。
- **已更新：**
  - `docs/yidong-jingling/opening-weak-to-strong-plan.md`
  - `docs/superpowers/specs/2026-05-22-opening-weak-to-strong-design.md`
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
- **验证：** 文档方案阶段，未改生产代码。

## 2026-05-22 网页板数据源复核

- **目标：** 核查用户提醒的“网页板当前是选股通 HTTP 轮询，和桌面版 python-bridge WebSocket 不同”，确认 V3 技术可行路径。
- **使用流程：**
  - 使用 `superpowers:brainstorming` 做数据源方案收束。
  - 使用 `superpowers:dispatching-parallel-agents` 并行复核 HTTP 事件源、python-bridge 实时链路和方案文档风险。
  - 使用 `planning-with-files` 同步方案、发现和任务计划。
- **结论：**
  - 选股通/同花顺 HTTP feed 是事件历史和涨停池结果源，不能作为 `opening_weak_to_strong` 主检测源。
  - 当前网页板事件雷达默认轮询是 `30_000ms`，不是 3 秒；`3_000ms` 只出现在语音批量 flush 等链路，不能当行情采样频率。
  - 网页板 V3 第一版必须使用 `python-bridge` WebSocket 的 `FULL_STATE` / `QUOTE_PATCH` 实时 L1 行情，和桌面版统一主数据源。
  - 网页检测器应直接读取 `webSocketService` 的 `QuotePatch` / `getQuotesBatch()`，不要从当前 DataLayer 实时投影反推 `open/preClose`。
  - `proxy-server` 只做信号缓存、去重和主表展示同步，不做行情采样或弱转强推导。
- **已更新：**
  - `docs/yidong-jingling/opening-weak-to-strong-plan.md`
  - `docs/superpowers/specs/2026-05-22-opening-weak-to-strong-design.md`
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
- **验证：** 文档方案阶段，未改生产代码；已运行 `git diff --check`，通过。

## 2026-05-22 Superpowers 三端方案确认

- **目标：** 按用户确认，把“竞价弱转强”从桌面端优先方案重梳为网页板、桌面版、Dragon Board 主界面同时落地的 V3 第一版方案。
- **使用流程：**
  - 使用 `superpowers:brainstorming` 收束设计。
  - 使用 `planning-with-files` 同步 `task_plan.md`、`findings.md`、`progress.md` 和专题方案文件。
- **决策：**
  - 采用“共享信号合同 + TS/C# 独立检测 + proxy 本地缓存去重 + Dragon Board 主表消费信号”的架构。
  - 网页板异动雷达通过 TypeScript 检测实时 L1 报价，进入现有异动雷达列表和本地语音链路。
  - 桌面版 `YiDongJingLing.exe` 通过纯 C# 独立检测并使用 VoiceWorker 语音提醒。
  - Dragon Board 主界面通过 `DataTable.vue` 展示“竞价弱转强”徽标或短时行高亮，不承担检测逻辑。
- **产出：**
  - 新增 `docs/superpowers/specs/2026-05-22-opening-weak-to-strong-design.md`。
  - 更新 `docs/yidong-jingling/opening-weak-to-strong-plan.md`，纳入网页板、桌面版、代理缓存和主表信号。
  - 更新 `docs/yidong-jingling/task_plan.md`，V3 阶段拆为共享合同、桌面端、网页板、代理缓存、主表、实盘联调。
  - 更新 `docs/yidong-jingling/findings.md`，记录三端范围和共享信号合同。
- **验证：** 文档设计阶段，未改生产代码，未运行构建。

## 2026-05-22 开盘竞价弱转强方案

- **目标：** 基于用户对 `002552 宝鼎科技` 样例的修正，制定“不接 QMT L2、不做真十档，只用 mootdx L1 抓 09:25 到 09:30 弱转强跳空”的落地方案。
- **发现：**
  - 核心信号不是固定高开，而是 `09:25` 竞价最后价偏弱到 `09:30-09:35` 连续竞价快速上移。
  - `09:25` 竞价最后价需要实盘采样，盘后分钟线不能可靠补齐。
  - 现有 `YiDongJingLing` 已有行情桥、事件去重、语音和表格高亮链路，适合最小增量实现。
- **产出：**
  - 新增 `docs/yidong-jingling/opening-weak-to-strong-plan.md`。
  - 在 `task_plan.md` 增加 V3 开盘竞价弱转强阶段计划。
  - 在 `findings.md` 增加 V3 关键发现。
- **验证：** 文档方案阶段，未改生产代码，未运行构建。

## 2026-05-20 TDX 雷达设置迁移项

- **目标：** 按 TDX 市场雷达设置页，把现有行情桥可稳定提供的数据尽量迁移为桌面版可配置规则。
- **改动：**
  - 新增可配置阈值：涨幅突破、跌幅突破、5 分钟涨跌幅、成交额门限、买卖挂单额门限、开盘跳空幅度、长阳/长阴实体幅度。
  - 新增事件类型：大幅跳水、出现大买挂盘、出现大卖挂盘、低开长阳、高开长阴。
  - 快速拉升/快速跳水扩展到 5 分钟窗口；成交额跨档改为使用设置页门限；大买/大卖挂盘按买一/卖一挂单金额计算。
  - 设置页增加“异动参数”区域，参数保存到 `AppSettings` 并在 `MainForm` 中同步到 `L1EventRules`。
  - 本地行情历史缓存扩展到 6 分钟，确保 5 分钟快涨/快跌规则在实盘路径可触发。
  - 启动基线会吸收已经成立的低开长阳/高开长阴形态，避免工具启动后把存量形态误报为新增异动。
  - 补充测试覆盖新增规则、5 分钟快涨、开盘形态基线吸收、设置克隆。
- **验证：**
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet publish ... -o tools\YiDongJingLing\publish\win-x64`：用户关闭运行实例后已成功发布。

## 2026-05-20 设置页同步消息与飞书机器人

- **目标：** 在设置页增加“同步消息”勾选框，并复用网页版“异动雷达”的飞书聊天机器人发送能力。
- **改动：**
  - `AppSettings` 增加 `SyncMessages`，设置窗保存/加载该开关。
  - 设置页“股票池、窗口与行情桥”区域增加“同步消息”复选框。
  - 新增 `EventRadarMessageNotifier`，把桌面版 L1 异动转换为代理 `/api/notifications/event-radar/events` 接口兼容 payload。
  - `MainForm` 在异动去重后、语音播报旁异步同步消息；代理未运行时尝试启动 `proxy-server`，失败只写诊断日志。
  - 使用说明补充飞书配置前置条件和代理端冷却/批量窗口语义。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

## 2026-05-20 TDX 自选股切回保留修复

- **目标：** 修复从 `八平台热榜` 切回 `TDX自选股` 时，原先勾选的 `.blk` 文件可能被空列表覆盖的问题。
- **改动：**
  - `MainForm` 增加 TDX 列表加载状态，只有 `.blk` 列表完成加载后才允许用当前勾选项覆盖 `SelectedBlockFiles`。
  - 切回 `TDX自选股` 并订阅前，如果列表尚未加载，会先扫描 `blocknew` 目录，恢复旧勾选再读取股票池。
  - 增加纯函数测试，覆盖“列表未加载时保留旧 `.blk` 选择”和“列表已加载时保存新选择”。
- **验证：**
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - 发布覆盖 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe` 时失败：目标 exe 正在被其它进程占用，未强制结束用户进程。

## 2026-05-20 设置置顶取消与八平台热榜股票池

- **目标：** 修复设置窗口反选“窗口置顶”后主窗体覆盖设置窗的问题，并增加股票池来源二选一。
- **改动：**
  - 设置页移除“窗口置顶”，启动、保存设置和主窗体应用设置时都强制 `TopMost=false`，兼容旧配置但不再启用置顶。
  - “监控板块”页增加“股票池来源”下拉：`TDX自选股` / `八平台热榜`。
  - 新增 `HotlistPoolLoader`，复用本地 `proxy-server` 的八个平台热榜接口，归一化 A 股 6 位代码并过滤港股/指数样式代码。
  - 新增 `ProxyProcessManager`，热榜来源下如果 3000 端口未运行，会尝试后台启动 `proxy-server/server.js`；不启动 Dragon Board 前端。
  - 更新 `docs/yidong-jingling/usage.md` 与 `task_plan.md`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行，随后关闭烟测实例；`startup-error.log` 未刷新。

## 2026-05-20 设置窗容器高度补丁

- **目标：** 修复设置窗右侧容器过小导致新功能和行情桥输入框不可见的问题。
- **改动：**
  - 设置窗扩大到 `860x740`，最小尺寸调整为 `820x700`。
  - 右侧设置组改为“股票池、窗口与行情桥”，第一行直接显示股票池来源下拉。
  - 保存设置时如果股票池来源变化，会立即刷新监控池并重新订阅。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 发布版启动烟测通过，`startup-error.log` 未刷新。


## Session: 2026-05-20

### V2 Phase 1-4：实盘盯盘体验落地

- **状态：** implemented
- **目标：** 按用户要求不中途停顿，完成 V2 金融风格、连接状态、语音噪音控制和托盘效率能力。
- **已执行：**
  - `MainForm` 改为证券终端式深色金融风格：低眩光背景、细网格、紧凑行高、A 股红涨绿跌、强弱事件行色。
  - 异动页尾部状态栏增加：监控数、行情桥状态、记录数、今日累计、最近行情、交易时段、语音模式。
  - 行情桥断开或连接失败后进入自动重连，使用退避时间避免重复刷屏。
  - 最近行情时间超过 30 秒时在状态栏显示延迟秒数，交易时段显示连续竞价或休市/集合。
  - 设置页增加语音模式：只播强信号、播报全部、静音；默认弱盘口信号只入列表不播报。
  - 最小化窗口进入托盘，托盘菜单支持显示窗口、静音/恢复、退出。
  - 双击异动列表复制股票代码。
  - 导出记录改为带表头的 CSV 或制表符文本。
- **文件修改：**
  - `tools/YiDongJingLing/MainForm.cs`
  - `tools/YiDongJingLing/SettingsForm.cs`
  - `tools/YiDongJingLing/Settings/AppSettings.cs`
  - `tools/YiDongJingLing/Events/EventVoicePolicy.cs`
  - `tools/YiDongJingLing.Tests/Program.cs`
- **待验证：**
  - 已完成，见下方 V2 Phase 5 验收记录。

### V2 Phase 5：验收发布

- **状态：** complete
- **已执行：**
  - 运行全部 `YiDongJingLing.Tests` console-style 测试。
  - 运行 Release 构建。
  - 发布 win-x64 self-contained 单文件到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
  - 启动烟测正式 exe，进程保持运行，`startup-error.log` 未更新。
  - 发布过程中一度发现旧 `publish\win-x64\YiDongJingLing.exe` 进程占用文件；确认进程后未强杀用户进程，先发布到临时目录验证，旧进程退出后再正式覆盖 `publish\win-x64`，并清理临时目录。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：19 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行，`startup-error.log` 未更新。

### V2 规划：金融风格和实盘盯盘方向

- **状态：** planned
- **目标：** 将第二版定义为“实盘盯盘可用版”，并把窗体显示风格改为金融终端风格。
- **用户补充：**
  - 窗体显示风格要改成金融风格。
- **已执行：**
  - 在 `docs/yidong-jingling/findings.md` 补充 V2 金融风格设计约束。
  - 在 `docs/yidong-jingling/task_plan.md` 新增 V2 任务计划。
  - V2 范围暂定为：金融风格主窗体、稳定连接和状态可见、语音噪音控制、托盘和盘中操作效率、验收发布。
- **设计口径：**
  - 高密度、低眩光、证券终端式工具栏和状态栏。
  - A 股语义红涨绿跌。
  - 异动列表数字右对齐、强弱事件行色区分。
  - 弱盘口信号不应在视觉或语音上压过封板、开板、快速拉升等强信号。

### Phase 6-7：VoiceWorker 语音链路修复

- **状态：** complete
- **目标：** 修复设置页语音选择保存后不可用的问题，并复用已有 `tools/VoiceWorker`。
- **发现：**
  - `YiDongJingLing` 直接引用 `System.Speech`，设置页只能看到 Desktop SAPI 声音，无法使用 VoiceWorker 已支持的 OneCore 声音。
  - 设置页“测试”按钮会把临时设置写入主播报器；取消后配置文件不保存，但内存播报器可能仍保留临时声音。
- **已执行：**
  - `SpeechAnnouncer` 改为通过 `http://127.0.0.1:32145/` 调用 `VoiceWorker` 的 `/status`、`/speak`、`/test`、`/stop` 接口。
  - GUI 打开设置或播报时，如果 VoiceWorker 未运行，会优先启动 `tools\VoiceWorker\bin\Release\...\VoiceWorker.exe`，缺失时回退 `dotnet run --project tools\VoiceWorker\VoiceWorker.csproj`。
  - 移除 `YiDongJingLing.csproj` 对 `System.Speech` 的直接依赖。
  - 设置页文案改为“VoiceWorker 本地语音”；测试语音只使用当前控件值，不污染主设置。
  - 增加测试覆盖：选中的声音名会随 `/speak` 请求发送给 VoiceWorker。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：16 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet build tools\VoiceWorker\VoiceWorker.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ...`：成功。
  - 启动烟测新版 exe：进程保持运行，`startup-error.log` 未更新。
  - VoiceWorker 状态烟测：返回 `Microsoft Kangkang`、`Microsoft Yaoyao` 可选声音。

### Phase 6-7：Review 问题修复

- **状态：** complete
- **目标：** 修复 code review 中发现的股票名称、设置取消、跨档播报和 TDX 目录定位问题。
- **已执行：**
  - 股票名称解析改为优先使用通达信 `.tnf` 缓存，行情桥 fallback 仅接受非数字、非代码形态名称，避免把 `volunit` 等数字字段缓存成名称。
  - 设置窗口改为编辑 `AppSettings` 副本，点击“取消”不会污染主窗口内存配置，也不会在后续关闭时被意外保存。
  - 大幅拉升和成交额跨档改为同次只触发最高新跨越档位，例如 9% 直接报“涨幅突破 9%”，10 亿直接报“成交额突破 10亿”。
  - “打开 TDX 目录”改为从 `T0002\blocknew` 向上解析真实 TDX 根目录，不再多退到 `D:\APP_SOFT`。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：15 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，`startup-error.log` 未更新。

### Phase 6-7：GUI 体验补齐二轮

- **状态：** complete
- **目标：** 修复用户实测反馈的“加载板块”交互不符合预期，并检查完善真实使用主路径。
- **发现：**
  - 顶部“加载板块”当前只读取已勾选列表，不会打开 `.blk` 文件选择器，用户初次打开会误以为功能无效。
  - 切换监控池后没有主动清理行情/事件状态，可能保留上一批股票的本地状态。
  - 若已连接行情桥后重新加载板块，当前实现没有立即重新下发订阅。
  - 行情桥启动按钮立即检查端口，可能在 bridge 尚未完成启动时显示“未就绪”。
  - 行情桥或语音后台线程日志需要确保回到 UI 线程。
- **已执行：**
  - 顶部“加载板块”改为打开 `.blk` 文件多选对话框，默认进入当前 `blocknew` 目录。
  - 选择 `.blk` 后自动刷新板块列表、勾选文件、保存配置、统计股票数。
  - 已连接行情桥时，重新加载板块会立即向 bridge 下发新订阅池。
  - 手工换池会清空旧行情状态、规则状态、去重冷却和当前异动列表，避免旧池信号混入新池。
  - 板块文件变化时，如果变化文件属于已选监控池，会重载股票池并更新订阅，不清空当前异动列表。
  - “监控板块”页新增“加载选中”按钮，顶部按钮和板块页形成一致操作路径。
  - 启动行情桥后最多等待约 6 秒检测端口，避免刚启动就显示未就绪。
  - `TdxBridgeClient` 连接时清空旧缓存，收到非法 JSON 或关闭帧时输出状态提示。
  - 语音选择无效声音时回退默认声音，停止播报使用 `SpeakAsyncCancelAll`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：6 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

### Phase 6-7：GUI 体验补齐三轮

- **状态：** complete
- **目标：** 修复用户指出的列表标题、股票名称、语音播报名称和独立设置界面问题。
- **已执行：**
  - 异动列表增加顶部标题和摘要区，并强制显示表格列头。
  - 增加 `StockNameResolver`，从通达信 `T0002\hq_cache\shs.tnf/szs.tnf/bjs.tnf` 读取本地股票名称作为行情桥名称缺失时的兜底。
  - 行情事件进入规则引擎前补齐股票名称，表格“名称”列和语音播报都会优先使用股票名称。
  - 设置从主 Tab 拆成独立 `SettingsForm`，顶部新增“设置”按钮；设置窗体包含异动类型、语音、语速、音量、透明度、置顶和行情桥地址。
  - 设置窗体内保留语音测试和停止按钮。
  - 顶部按钮重新排布，避免最小窗口宽度下越界。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：新增 TNF 名称解析测试，全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

### Phase 7：启动诊断和发布目录整理

- **状态：** complete
- **目标：** 解决双击 `YiDongJingLing.exe` 没反应时无错误提示的问题，并把可双击发布包放到清晰目录。
- **发现：**
  - 双击打不开的根因是启动阶段恢复已选 `.blk` 时触发 `CheckedListBox.ItemCheck`，此时窗口句柄尚未创建，事件处理里的 `BeginInvoke` 抛出 `InvalidOperationException`。
  - 旧发布流程曾把 self-contained 展开包输出到 `bin` 目录，导致 `tools/YiDongJingLing` 下文件数量非常多。
- **已执行：**
  - 给 `Program.Main` 增加顶层异常捕获，启动失败时写入 `%APPDATA%\DragonBoard\YiDongJingLing\startup-error.log` 并弹窗提示。
  - 修复启动加载板块时的 WinForms 句柄时序问题，加载期间屏蔽勾选事件的延迟 UI 更新，加载完成后统一刷新摘要。
  - 重新运行核心测试和 Release 构建。
  - 重新发布 win-x64 self-contained 单文件到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
  - 使用 `dotnet clean` 清理 Debug/Release/runtime 构建产物；按项目禁止递归删除规则，未使用 `Remove-Item -Recurse` 强删历史发布残留。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行 4 秒以上，未生成新的 `startup-error.log`。

### Phase 7：股票名称解析修复

- **状态：** complete
- **目标：** 修复异动列表“名称”列和语音播报仍显示股票代码的问题。
- **发现：**
  - 本机 `D:\APP_SOFT\TDX\T0002\hq_cache\shs.tnf/szs.tnf/bjs.tnf` 存在且可读。
  - 真实 `.tnf` 记录仍为 `0x32` 起、每条 `0x168` 字节、代码在记录开头，但股票名称字段起始偏移是 `0x1f`，原实现使用 `0x1e`，会先读到 `00` 导致名称为空。
- **已执行：**
  - 将 `StockNameResolver` 的通达信 `.tnf` 名称字段偏移修正为 `0x1f`。
  - 增加本机 TDX 缓存可用时的名称解析验证，覆盖 `600580`、`002594` 等真实代码。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过，包含本机真实 TDX 名称缓存测试。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，未生成新的 `startup-error.log`。

### Phase 7：异动列表和监控池收敛整改

- **状态：** complete
- **目标：** 修复列表表头不可见、缺少成交量、加载少量股票却显示全市场异动，以及同股多事件刷屏的问题。
- **发现：**
  - 异动页原先使用多个 Dock 控件叠加并手动 `BringToFront`，在大窗口下容易让表格盖住标题/列头区域。
  - GUI 只在连接行情桥时发送订阅池，接收 `full_state/quote_patch/depth_patch` 后没有按当前监控池二次过滤；如果 bridge 推来全量状态，GUI 会把全市场都评估成异动。
  - 事件记录没有携带成交量字段，列表和导出都无法展示成交量。
  - 同一股票同一批次可能同时触发成交额、盘口买卖压等多条弱信号，列表体验会显得像重复刷屏。
- **已执行：**
  - 异动页改为三段式布局：顶部摘要、中央表格、底部状态栏，避免表头被遮挡。
  - 表格列按用户要求固定为：时间、异动类型、股票代码、股票名称、涨跌幅、最新价、成交量、成交额、异动详情。
  - `MainForm` 维护当前监控代码集合，接收行情时只处理 `_watchedCodes` 内的股票。
  - `EventRecord` 增加 `Volume`，`L1EventEngine` 将行情成交量写入事件，列表和导出同步展示。
  - `EventDeduper` 改为同一股票同一批事件只保留最高优先级事件，减少同股刷屏。
  - 清空/加载后的摘要文案改为“等待监控池内 N 只股票的异动”，明确显示范围。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过，新增成交量和同股同批收敛测试。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，未生成新的 `startup-error.log`。

### Phase 0：方案文档

- **状态：** complete
- **目标：** 将“异动精灵”第一版方案落成文档，明确 L1 可做能力、边界、实现阶段和验收方式。
- **已执行：**
  - 使用 `planning-with-files` skill 的文件化规划方式。
  - 按项目规则将规划文件放入 `docs/yidong-jingling/`，没有在根目录新增过程文件。
  - 检查真实通达信目录 `D:\APP_SOFT\TDX\T0002\blocknew`，确认存在 `.blk` 文件。
  - 读取 `2B.blk` 样本，确认文本格式为一行一个 7 位通达信代码。
  - 复核 `python-bridge/README.md`，确认当前可用能力是 L1 + 标准五档 + WebSocket。
  - 复核 `tools/VoiceWorker/README.md`，确认本地语音可用能力。
  - 创建 V1 任务计划、调研发现和进度记录。
- **文件创建：**
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
  - `docs/yidong-jingling/progress.md`

### Phase 1-5：V1 MVP 实现

- **状态：** complete
- **目标：** 创建可构建的 Windows GUI 工具，完成 `.blk` 解析、L1 行情模型、异动规则、去重和语音播报闭环。
- **已执行：**
  - 恢复用户指定的 `CLAUDE.md`、`README.md`、`README.zh.md`。
  - 创建 `tools/YiDongJingLing` WinForms 项目。
  - 创建 `tools/YiDongJingLing.Tests` console-style 测试项目，沿用仓库 `VoiceWorker.Tests` 的轻量测试风格。
  - 实现 `.blk` 文件扫描和解析，支持 7 位通达信代码归一、重复过滤、非法行记录、指数/板块过滤。
  - 实现 `TdxBridgeClient`，支持连接 `ws://127.0.0.1:8765/ws/quotes`、订阅股票池、处理 `full_state`、`quote_patch`、`depth_patch` 和 `heartbeat`。
  - 实现 L1 事件规则：封涨停、打开涨停、逼近涨停、封跌停、打开跌停、逼近跌停、封单增强/变弱、大幅拉升、快速拉升、快速跳水、翻红、翻绿、创日内新高/低、成交额跨档、成交增量加速、盘口买压/卖压、买卖价差异常。
  - 实现同股同类事件冷却、同批事件优先级排序、批量语音文案合并。
  - 实现 WinForms 主界面：异动列表、监控板块、设置、联动、诊断。
  - 实现 GUI 内置 Windows `System.Speech` 本地语音队列，支持启停、语速、音量、语音选择、测试播报。
  - 实现行情桥启动辅助，可从 GUI 启动 `python-bridge/main.py`。
- **文件创建：**
  - `tools/YiDongJingLing/YiDongJingLing.csproj`
  - `tools/YiDongJingLing/Program.cs`
  - `tools/YiDongJingLing/MainForm.cs`
  - `tools/YiDongJingLing/ProjectRootLocator.cs`
  - `tools/YiDongJingLing/Blocks/BlockFileParser.cs`
  - `tools/YiDongJingLing/Blocks/BlockFileScanner.cs`
  - `tools/YiDongJingLing/MarketData/QuoteSnapshot.cs`
  - `tools/YiDongJingLing/MarketData/QuoteStateStore.cs`
  - `tools/YiDongJingLing/MarketData/TdxBridgeClient.cs`
  - `tools/YiDongJingLing/Events/EventRecord.cs`
  - `tools/YiDongJingLing/Events/L1EventRules.cs`
  - `tools/YiDongJingLing/Events/L1EventEngine.cs`
  - `tools/YiDongJingLing/Events/EventDeduper.cs`
  - `tools/YiDongJingLing/Speech/SpeechAnnouncer.cs`
  - `tools/YiDongJingLing/Settings/AppSettings.cs`
  - `tools/YiDongJingLing/Diagnostics/BridgeProcessManager.cs`
  - `tools/YiDongJingLing.Tests/YiDongJingLing.Tests.csproj`
  - `tools/YiDongJingLing.Tests/Program.cs`

## 验证记录

| 验证项 | 输入 | 预期 | 实际 | 状态 |
|--------|------|------|------|------|
| 通达信 blocknew 目录 | `D:\APP_SOFT\TDX\T0002\blocknew` | 目录存在 | 存在 | 通过 |
| `.blk` 样本读取 | `2B.blk` | 可读取股票代码 | 读到 `0300834`、`0002082` 等 | 通过 |
| 文档落点 | `docs/yidong-jingling/` | 不污染根目录 | 已按专题目录创建 | 通过 |
| 核心逻辑测试 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | `.blk` 解析、封板/开板、急拉/跳水、去重播报通过 | 4 项 PASS | 通过 |
| Debug 构建 | `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Debug` | 0 errors | 0 warnings, 0 errors | 通过 |
| Release 构建 | `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` | 0 errors | 0 warnings, 0 errors | 通过 |

## 错误记录

| 时间 | 错误 | 处理 |
|------|------|------|
| 2026-05-20 | 一条 PowerShell 搜索 `1xxxxxx` 前缀的管道命令语法失败 | 该命令只用于补充边界样本，已有样本足够确认 `.blk` 文本格式，未重复执行同一失败命令。 |
| 2026-05-20 | `dotnet test` 对当前 console-style 测试项目只还原项目，不执行断言 | 改用 `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 作为真实验证命令。 |
| 2026-05-20 | 初次测试中去重播报排序预期与实现优先级不一致 | 规则实现以快速拉升优先于逼近涨停，修正测试预期后通过。 |

## 追加记录

| 时间 | 内容 | 状态 |
|------|------|------|
| 2026-05-20 | 按 L1 买一/卖一封单口径新增“即将打开涨停”“即将打开跌停”预警，并接入设置项、去重优先级和语音强信号。 | complete |
| 2026-05-20 | 修复封单金额少乘 100 的单位问题，并防止行情桥重连时重复启动多个 python-bridge 进程。 | complete |
| 2026-05-23 | 补齐竞价弱转强量价核心：`09:20-09:25` 序列画像、`auction_late_lift` 正式 variant、无量抬价/放量不涨/高位回落风险降级，并用 TS/C# 共享 fixture 验证。 | complete |
| 2026-05-23 | 补做 V2 提交后 code review，发现桌面端 `ConfigHash` 未纳入新增量价阈值；按 TDD 增加回归测试并修复。 | complete |
| 2026-05-23 | 按文档审计偏差修复弱转强落地：补 TS/C# 复盘字段透传、金额倒退风险降级、主表轮询服务边界、桌面导出弱转强专有字段。 | complete |
| 2026-05-23 | 曾按 Superpowers 规格落地 TDX 自选股前日弱势上下文；后续已废弃 `.blk` 候选池自动注入 `tdx_block`，股票池仅保留为监听范围。 | superseded |
| 2026-05-24 | 续修竞价弱转强覆盖率门禁：低覆盖/陈旧报价曾降为 `watch + dryRun`；2026-06-02 已修正为低覆盖仅标风险，陈旧报价仍 dry-run。 | complete |
| 2026-06-02 | 按“异动精灵是盘中盯盘工具，不是量化回测平台”的定位重梳理语音链路，新增 V7 计划：语音主链只保留用户设置、冷却、时间窗口、有效 09:25 基线和严重行情错误；质量门禁、复盘字段、telemetry、proxy 同步降级为旁路能力。 | planned |

## V4 验证记录

| 验证项 | 命令 | 结果 |
|--------|------|------|
| TS 检测器 RED | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts` | 新增 `auction_late_lift` 用例先失败，确认测试覆盖缺口。 |
| TS opening 链路 | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts` | 5 files / 20 tests passed。 |
| TS 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | 通过。 |
| 桌面端测试 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | All YiDongJingLing tests passed。 |
| V2 补审 RED | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | 新增 `Opening weak-to-strong config hash includes auction price-volume rules` 先失败，确认桌面端 hash 漏项。 |
| V2 补审 GREEN | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | All YiDongJingLing tests passed。 |
| V2 补审 TS opening 链路 | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts` | 5 files / 20 tests passed。 |
| V2 补审 TS 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | 通过。 |
| 文档偏差修复桌面端 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | All YiDongJingLing tests passed，包含导出弱转强复盘字段测试。 |
| 文档偏差修复 Web 链路 | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts src/components/common/__tests__/DataTable.test.ts` | 7 files / 36 tests passed。 |
| 文档偏差修复 proxy | `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs` | 8 tests passed。 |
| 文档偏差修复类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | 通过。 |
| 文档偏差修复构建 | `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`；`pnpm build` | 桌面端 0 warnings/0 errors；前端生产构建通过。 |
| 文档偏差修复空白检查 | `git diff --check` | 通过。 |
| TDX 上下文 Web 链路 | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts src/components/common/__tests__/DataTable.test.ts` | 7 files / 36 tests passed。 |
| TDX 上下文桌面端 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | All YiDongJingLing tests passed，包含 TDX 上下文触发 `strong_open_board_attempt` 和导出字段测试。 |
| TDX 上下文 proxy | `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs` | 8 tests passed。 |
| TDX 上下文类型与构建 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`；`pnpm build` | 类型检查通过；桌面端 0 warnings/0 errors；前端生产构建通过。 |
| 覆盖率门禁 TS/Web | `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts src/services/hotlist/__tests__/HotStockEventSpeechService.test.ts src/components/common/__tests__/DataTable.test.ts` | 7 files / 37 tests passed。 |
| 覆盖率门禁桌面端 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` | All YiDongJingLing tests passed；桌面端 0 warnings/0 errors。 |
| 覆盖率门禁 proxy/构建 | `node --test proxy-server\__tests__\openingSignals.test.mjs proxy-server\__tests__\docs.test.mjs`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；`pnpm build`；`git diff --check` | proxy 8 tests passed；类型检查通过；前端生产构建通过；空白检查通过。 |

## 5 问恢复检查

| 问题 | 答案 |
|------|------|
| 我在哪里？ | Phase 1-5 V1 MVP 已实现并通过核心测试/构建。 |
| 我要去哪里？ | 下一步是真实行情桥联调、GUI 手工冒烟、最小化到托盘和使用说明。 |
| 目标是什么？ | 独立 Windows GUI 使用通达信 `.blk` 和 L1 行情监控异动并语音播报。 |
| 学到了什么？ | `.blk` 可解析，现有 bridge 支持 L1 + 五档；console-style 测试需要用 `dotnet run` 执行真实断言。 |
| 做了什么？ | 创建文档、实现 WinForms GUI、解析器、行情桥客户端、L1 规则、去重和语音播报。 |
