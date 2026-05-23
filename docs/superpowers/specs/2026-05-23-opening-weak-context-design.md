# 竞价弱转强前日弱势上下文设计

日期：2026-05-23

## 结论

V4 下一步采用“TDX 自选股候选池 + 前日弱势上下文合同”的方案。现有 `TDX自选股` 已经能读取通达信 `T0002\blocknew` 下用户勾选的 `.blk` 文件，并订阅这些股票的 L1 行情；本阶段不新增第二套股池选择器，也不做全市场高频扫描。

新增能力分两层：

1. 股池层继续复用 `StockPoolSource.TdxBlock`、`BlockFileParser` 和已选 `.blk` 文件，确保检测对象来自用户当前 TDX 自选股。
2. 检测层新增可选的 `previousWeakScore`、`previousWeakSignals`、`previousWeakSource` 上下文。该上下文可作为 `strong_open_board_attempt` 的弱势前置条件和评分因子。字段缺失时保持现有行为不变。

## 背景和边界

现有竞价弱转强已经完成 `09:25` 竞价基线、`09:30-09:35` 检测窗口、TS/C# 共享 fixture、桌面语音、proxy 缓存和 Dragon Board 主表徽标。当前偏差在于“前一日弱”仍只停留在文档增强项里，检测器只能根据当日竞价价弱、官方开盘价弱或竞价后段抬升判断弱势前置。

用户确认可以接入“TDX自选股”作为上游数据。本设计中的 TDX 自选股不是新行情源，而是现有 `.blk` 文件候选池。

本阶段不做：

- 不新增 QMT、真 L2、十档、逐笔或选股通主判断。
- 不新增全市场高频扫描。
- 不把 `python-bridge` 改成策略引擎。
- 不新增第二套股票池 UI。
- 不要求历史数据库。没有前日上下文时只能降级，不硬造结论。

## 方案权衡

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 复用 TDX 自选股 `.blk` 并补上下文合同 | 改动小，符合用户已有工作流，早盘采样压力可控 | 只能覆盖用户选中的候选池 | 选择 |
| 新增独立“弱转强候选池” | 可单独维护候选名单 | 与现有 TDX 自选股重复，增加 UI 和配置复杂度 | 不选 |
| 全市场扫描后筛弱势 | 覆盖更广 | 早盘 L1 采样压力大，违背当前“不默认全市场高频扫描”边界 | 不选 |

## 数据合同

在 TS/C# 共享 quote 和 signal 合同中新增可选字段：

| 字段 | 类型 | 含义 |
|------|------|------|
| `previousWeakScore` | number / decimal | 前日弱势评分，建议 `0-100` |
| `previousWeakSignals` | string[] | 弱势来源标签，例如 `tdx_block_candidate`、`manual_watchlist`、后续 `failed_limit_up` |
| `previousWeakSource` | string | 上下文来源，例如 `tdx_block` |

规则新增字段：

| 字段 | 默认值 | 含义 |
|------|--------|------|
| `previousWeakScoreMin` | `30` | 作为弱势前置条件的最低分 |

评分新增因子：

| factor | 分数 | 说明 |
|--------|------|------|
| `previousWeakContext` | `12` | `previousWeakScore >= previousWeakScoreMin` 时加入 |

风险新增项：

| riskFlag | 场景 |
|----------|------|
| `previous_context_missing` | 当前需要上下文解释但没有任何前日弱势字段；第一阶段只作为复盘风险，不直接否定已有命中 |

字段缺失时必须保持兼容：旧 fixture、旧 proxy 缓存和旧桌面事件都能继续解析。

## 桌面端接入

桌面端是 TDX 自选股的主落点。设计上新增一个轻量上下文提供器，例如 `OpeningWeakContextStore`：

```text
MainForm 加载 TDX 自选股 .blk
  └─ LoadSelectedBlockCodes 得到 codes
       └─ OpeningWeakContextStore.ReplaceTdxBlockPool(codes)

L1EventEngine 生成 OpeningWeakToStrongQuote
  └─ 从 OpeningWeakContextStore 查询 code 上下文
       └─ 填入 previousWeakScore / previousWeakSignals / previousWeakSource

OpeningWeakToStrongDetector
  └─ previousWeakScore >= previousWeakScoreMin 可满足 weakPrecondition
```

第一阶段的上下文生成保持保守：被用户放入 TDX 自选股候选池，只能说明“人工候选/观察池”，不能等同于真实前日烂板或炸板。因此默认分数建议为 `30`，只让它成为弱势前置的最低有效证据，不单独制造强信号。后续若接入前日炸板、断板、长上影、尾盘漏单等结构化数据，再把分数提高并补充更具体的 `previousWeakSignals`。

当股票池来源切到 `八平台热榜` 时，不写入 `tdx_block` 上下文，避免把热榜池误当 TDX 自选股弱势上下文。

## Web 端接入

Web 端先只扩展合同和检测器，不新增 TDX `.blk` 读取能力。原因是浏览器端没有稳定访问用户本机通达信目录的权限，强行实现会引入新的本地文件服务或上传流程，超出本阶段范围。

Web 检测器如果收到 `previousWeakScore` 字段，则与 C# 使用同一规则；如果没有收到，则保持当前行为。

## 检测规则变化

`strong_open_board_attempt` 的弱势前置条件从：

```text
auctionPct <= auctionWeakMaxPct
或 officialOpenPct <= auctionWeakMaxPct
```

扩展为：

```text
auctionPct <= auctionWeakMaxPct
或 officialOpenPct <= auctionWeakMaxPct
或 previousWeakScore >= previousWeakScoreMin
```

这只影响“有弱势前置的开盘抢筹冲板”。普通无上下文、无当日竞价弱势的开盘冲板仍不得强播。

## 测试策略

共享 fixture 增加两类样例：

1. `strong_open_board_attempt`：当日竞价和官方开盘不弱，但 quote 带 `previousWeakScore`，满足近涨停和放量门槛，应命中。
2. 普通开盘冲板：没有当日弱势，也没有 `previousWeakScore`，仍应返回 `weak_precondition_missing`。

验证命令：

```powershell
pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
```

## 交付标准

完成后应满足：

1. 桌面端 `TDX自选股` 加载后，候选股 quote 带 `previousWeakScore` 上下文。
2. TS/C# 检测器都支持 `previousWeakScore` 作为弱势前置条件。
3. 有上下文的抢筹冲板能命中 `strong_open_board_attempt`。
4. 无上下文的普通抢筹冲板仍被拒绝。
5. 旧数据和旧 signal 缓存兼容。
6. 文档同步更新 `docs/yidong-jingling` 计划、发现和进度。
