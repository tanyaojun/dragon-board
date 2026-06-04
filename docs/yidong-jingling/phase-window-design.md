# 竞价弱转强窗口阈值设计

> 更新时间：2026-06-04

## 目标

消除竞价弱转强检测中所有固定秒点（如 `09:30:00`、`09:35:00`），改为**设置面板可配置的统一窗口阈值**。网络延迟、行情桥广播转发延迟、系统响应慢等因素不再造成误杀。

## 核心变化

### 一个可配置参数：窗口阈值

| 参数名 | 类型 | 意义 | 默认值 |
|---|---|---|---|
| `checkpointWindowThresholdSeconds` | int (秒) | 开盘承接、反攻确认、最终状态的宽限窗口 | 30 |

### 四个阶段的判定方式

| 阶段 | 锚点 | 窗口区间 | 备注 |
|---|---|---|---|
| 临门基线 | 09:24:50-09:25:10 | 固定窗口，不受阈值影响 | 设计之初为延迟设计的独立窗口，保留不变 |
| 开盘承接 | 09:30:00 | 09:30:00 ～ 09:30:00 + 阈值 | 锚点 + [0, 阈值] |
| 反攻确认 | 09:35:00 | 09:35:00 ～ 09:35:00 + 阈值 | 锚点 + [0, 阈值] |
| 最终状态 | 10:00:00 | 10:00:00 ～ 10:00:00 + 阈值 | 锚点 + [0, 阈值] |

窗口阈值默认 30 秒，用户可在设置面板中修改。

### 检测器行为规则

**开盘承接窗口（09:30:00 ～ 09:30:00 + 阈值）：**
- 窗口内第一笔有效报价就开始判断，不等到 09:30:00 整秒。
- 如果某笔报价较临门基线明显改善（改善幅度、成交额承接均达标）→ `gapAlert`。
- 如果窗口内先出 `noGap`（不达标），后续同一窗口内**可以升级**为 `gapAlert`。
- 窗口内已出 `gapAlert` 不重复播报。
- 到窗口结束仍无 `gapAlert` → 最终记为 `noGap`。

**反攻确认窗口（09:35:00 ～ 09:35:00 + 阈值）：**
- 窗口内第一笔有效报价就开始判断。
- 如果承接延续、价格趋势继续走强 → `trendConfirm`。
- 如果窗口内先出 `trendWeak`，后续同一窗口内**可以升级**为 `trendConfirm`。
- 窗口内已出 `trendConfirm` 不重复播报。
- 到窗口结束仍无 `trendConfirm` → 最终记为 `trendWeak`。

**最终状态窗口（10:00:00 ～ 10:00:00 + 阈值）：**
- 沿用当前逻辑，只做状态更新，不播报。

**关键保证：**
1. 临门基线 `09:24:50-09:25:10` 不受阈值影响，保留原始设计。
2. 语音规则不变：只有 `gapAlert` 和 `trendConfirm` 可播。
3. `configHash` 纳入 `checkpointWindowThresholdSeconds`，日志可反查。
4. 桌面版本地语音优先，不受 proxy 阻断。

## 影响文件清单

### 1. 类型层

**`src/services/hotlist/openingWeakToStrongTypes.ts`**
- `OpeningWeakToStrongRules` 接口新增 `checkpointWindowThresholdSeconds?: number`

**`src/services/hotlist/openingWeakToStrongConfig.ts`**
- `DEFAULT_OPENING_WEAK_TO_STRONG_RULES` 补充默认值 `checkpointWindowThresholdSeconds: 30`
- 规则版本号升级为 `opening-weak-to-strong.v2`

### 2. TS 检测器

**`src/services/hotlist/OpeningWeakToStrongDetector.ts`**
- 删除 `GAP_ALERT_TIME`、`TREND_CONFIRM_TIME`、`OPTIONAL_FINAL_TIME`、`CHECKPOINT_GRACE_SECONDS` 等固定常量
- `evaluate()` 中用锚点 + 阈值构造 `isInWindow()` 判断
- `noGap→gapAlert`、`trendWeak→trendConfirm` 窗口内升级逻辑
- `isCheckpointTime()` / `isCheckpointWindow()` 合并

### 3. C# 检测器

**`tools/YiDongJingLing/Events/OpeningWeakToStrongDetector.cs`**
- OpeningWeakToStrongRules record 新增 `CheckpointWindowThresholdSeconds`
- `FromJson()`、`ConfigHash()` 同步
- evaluate() 中 09:30/09:35/10:00 改为窗口判断，不再用精确秒点
- 窗口内升级逻辑

### 4. C# 引擎注入

**`tools/YiDongJingLing/Events/L1EventEngine.cs`**
- `OpeningRules` 改为从外部注入，不再 private static 硬编码

### 5. 桌面设置页

**`tools/YiDongJingLing/Settings/AppSettings.cs`**
- 新增 `CheckpointWindowThresholdSeconds: int = 30`

**`tools/YiDongJingLing/SettingsForm.cs`**
- 在异动参数区域新增"竞价弱转强"分组
- 添加一个 `NumericUpDown` 控件：**窗口阈值（秒）**，范围 0-120，默认 30
- 保存/加载时读写 AppSettings 对应字段
- 底部附带说明文字：影响开盘承接、反攻确认、最终状态的宽限窗口

**`tools/YiDongJingLing/MainForm.cs`**
- 启动时从 AppSettings 构建 OpeningWeakToStrongRules，注入引擎
- 设置保存后通过 `_eventEngine.UpdateOpeningRules(rules)` 同步
- `IsOpeningAuctionCoverageWindow()`（09:24:50-09:25:10）不受影响
- `IsOpeningAuctionSampleTelemetryWindow()`（09:20:00-09:25:10）不受影响
- `IsOpeningWeakToStrongPreopenWindow()`（09:25:00-09:29:59）不受影响

### 6. python-bridge 采样窗口

**`python-bridge/main.py`**
- `is_opening_sampling_window()` 的固定结束时间 09:25:10 延至 09:36:00
- 确保开盘承接和反攻确认期间行情桥仍发全量（不做 diff 压缩）

### 7. 文档同步

- `docs/yidong-jingling/usage.md`：更新竞价弱转强说明 + 窗口阈值设置说明
- `docs/yidong-jingling/opening-weak-to-strong-plan.md`：更新点合同表
- `docs/yidong-jingling/findings.md`：新增 2026-06-04 结论
- `docs/yidong-jingling/event-rule-logic.md`：更新竞价弱转强段落

### 8. 测试

- `src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts`：窗口内延迟命中、窗口内升级用例
- `tools/YiDongJingLing.Tests/Program.cs`：C# 端同步
- `python-bridge/test_monitor.py`：确认采样窗口范围

## 验证清单

```powershell
pnpm test src/services/hotlist/__tests__
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
node proxy-server/__tests__/openingSignals.test.mjs
node proxy-server/__tests__/docs.test.mjs
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
cd python-bridge && python -m pytest test_monitor.py -v
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
```

## 回退方案

设置面板恢复窗口阈值到 30 秒即可，不改代码不重启。
