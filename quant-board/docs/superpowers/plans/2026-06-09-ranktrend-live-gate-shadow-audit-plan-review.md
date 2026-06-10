# RankTrend Live Gate Shadow Audit — 设计与实施计划审计

日期：2026-06-09 | 审计对象：[设计文档](../specs/2026-06-09-ranktrend-live-gate-shadow-audit-design.md) + [实施计划](2026-06-09-ranktrend-live-gate-shadow-audit-implementation-plan.md)

## 审计结论总述

设计文档方向正确，实施计划结构合理，但存在 **4 个实质性问题**，其中问题 1（变体不正交）和问题 3（jump 翻转未建模）是结构性缺陷，不改会导致 shadow audit 归因结论严重失真。

## 审计后修订决议

以下修订项已被采纳，并应同步落入
[2026-06-09-ranktrend-live-gate-shadow-audit-implementation-plan.md](2026-06-09-ranktrend-live-gate-shadow-audit-implementation-plan.md)：

1. **变体正交化**
   - 单变量变体只允许改一项参数。
   - 保留一个 `recall_first` 组合变体作为召回上限对照。

2. **jump / fusion 双层拆分**
   - 审计输出必须分开报告：
     - `jump gate` 是否通过
     - `fusion gate` 是否通过
   - 归因时明确区分“死在 jump 层”还是“死在 fusion 层”。

3. **delta 变体单独重放**
   - 所有 `delta` 相关变体必须重新回放 `RankTrendPythonEngine.replay_frame_at()`。
   - 不允许复用 baseline signal 中已有的 `jump` 结果去伪装 `delta=10/12.5` 的审计。

4. **移除无效的 accDelta 变体**
   - 当前实盘数据上 `accDelta` 普遍缺失，原 `accdelta_optional` 变体没有增量信息。
   - 本轮改为在报告 `meta` 中显式声明“当前 acceleration gate 实际主要依赖 acceleration 字段”，不再单独把它作为 shadow 变体。

5. **delta 中间值改为 12.5**
   - 原计划中的 `13.6` 缺少直接业务依据。
   - 本轮先使用 `12.5` 作为 `15 -> 10` 的中间值对照。

6. **执行顺序调整**
   - 先修文档与计划，再进入 Subagent-Driven coding。
   - Subagent 执行必须以修正后的 implementation plan 为唯一任务源，不再沿用旧计划草稿。

---

## 问题 1：Shadow 变体不正交，无法做独立归因

**严重程度：结构性缺陷，必须在 Task 1 之前修复**

设计文档 Section 6 定义了 5 组独立控制的变量（delta、confidence、change、sampleQuality、accDelta），但实施计划 Task 1 Step 4 的 `DEFAULT_SHADOW_VARIANTS` 把多组变量揉进了单个变体：

```python
# 标注为 "delta=10"，实际同时改了 5 个参数
ShadowVariant(key="delta_10", label="delta=10",
    jump_delta_pct=10.0,           # 改了 delta
    min_jump_confidence=80.0,      # 改了 confidence
    require_change_lt_6=False,     # 改了 change
    allow_degraded_sample=True,    # 改了 sampleQuality
    require_tier_gate=False)       # 改了 tier
```

这导致归因把"放宽 delta → 多召回 N 只票"和"放宽 confidence → 多召回 M 只票"混在一起，无法区分每个参数的独立贡献。

同样的混叠出现在 `delta_13_6` 和 `change_as_rank_only` 变体中。

### 改法

每个变体只控制一个参数，另加一个 `recall_first` 组合变体：

```python
DEFAULT_SHADOW_VARIANTS = (
    ShadowVariant(key="baseline", label="baseline"),
    # 单变量对照，每个只改一项
    ShadowVariant(key="delta_10", label="delta=10", jump_delta_pct=10.0),
    ShadowVariant(key="delta_13_6", label="delta=13.6", jump_delta_pct=13.6),
    ShadowVariant(key="confidence_85", label="jump>=85", min_jump_confidence=85.0),
    ShadowVariant(key="confidence_80", label="jump>=80", min_jump_confidence=80.0),
    ShadowVariant(key="change_no_gate", label="change不硬拦", require_change_lt_6=False),
    ShadowVariant(key="allow_degraded", label="允许degraded", allow_degraded_sample=True),
    ShadowVariant(key="tier_no_gate", label="不卡tier", require_tier_gate=False),
    ShadowVariant(key="accdelta_optional", label="accDelta缺失不否决"),
    # 组合变体：全放，用于验证上限
    ShadowVariant(key="recall_first", label="召回优先全放",
        jump_delta_pct=10.0, min_jump_confidence=80.0,
        require_change_lt_6=False, allow_degraded_sample=True,
        require_tier_gate=False),
)
```

这样归因报告才能说清楚：delta=10 单独解了多少票、confidence=80 单独解了多少票、tier 放行解了多少票，以及叠加后的组合效果。

---

## 问题 2：Jump gate 和 Fusion gate 被混为一层

**严重程度：影响归因精度，应在 Task 1 修复**

设计文档 Section 5 正确识别了两层硬闸——[jumpSignalService.ts](</d:/dragon-board/src/services/rankTrend/jumpSignalService.ts:87>) 和 [fusionStrategy.ts](</d:/dragon-board/src/services/rankTrend/fusionStrategy.ts:38>)——但实施计划 `_evaluate_variant` 只实现了融合层的简化版判断，漏掉了 jump 入场层的独立检查。

实施计划中缺失的 jump 层检查项：

| 检查项 | 来源 | 状态 |
|--------|------|------|
| `jump.event == "jump"` | jumpSignalService.ts | 未实现 |
| `jump.sustained == true` | jumpSignalService.ts | 未实现 |
| `direction.signal == "buy"` | jumpSignalService.ts | 未实现 |
| `acceleration.signal == "buy"` | jumpSignalService.ts | 未实现 |
| `change > 0` | jumpSignalService.ts | 未实现 |
| 涨停检查 | jumpSignalService.ts | 未实现 |
| `MACD cross == golden` | jumpSignalService.ts | 未实现 |

2026-06-09 重放分析已确认 `600186` 的 MACD cross 在落库 frame 中是 `"none"`。即使 jump confidence 过了融合层，**MACD 金叉这条也会在 jump 层单独拦下它**。漏掉这层意味着 shadow audit 会低估漏票严重程度，把"被两层同时否决"的票错归为"只被融合层否决"。

### 改法

`_evaluate_variant` 拆成两阶段：先跑 jump gate checks，标记通过/失败；再跑 fusion gate checks。两层分开输出，归因时区分"死在 jump 层"和"死在 fusion 层"。

---

## 问题 3：jump direction 翻转场景未建模

**严重程度：结构性缺陷，直接影响 002156 类样本的归因真实性**

设计文档 Section 5.1 明确写了 `jump.direction == buy` 是 jump 入场硬门槛。但不同 `jump_delta_pct` 会改变 jump 检测的完整结果——包括 direction、confidence、sustained。

2026-06-09 重放分析已确认：`002156 通富微电` 在 delta=10 时 jump 是 buy / 78.5，但 delta=15 时直接翻成 sell / 84.2。**这不是 confidence 差一点的问题，而是 jump 语义本身被不同 delta 翻转了。**

实施计划 `evaluate_shadow_variants` 对所有变体传入同一个 signal 对象，等于假设 jump 检测结果不随 delta 变化。当变体调了 `jump_delta_pct` 但 signal 里的 jump 字段还是 baseline delta 跑出来的结果时，实际上没测到 delta 变化对 jump 方向/置信度的真实影响。

### 改法（二选一）

- **方案 A（推荐）**：delta 类变体单独调用 `RankTrendPythonEngine.replay_frame_at(frames, index, window_size=50, jump_delta_pct=variant.jump_delta_pct)`，获取该 delta 下的真实 signal。这是最接近实盘语义的做法。
- **方案 B**：在 `ShadowVariant` 加 `requires_separate_replay: bool` 标记，delta 类变体标记为 True，审计服务分两轮处理：不需要单独回放的用同一个 signal 跑，需要单独回放的用不同 delta 各自回放。

---

## 问题 4：accDelta 可选变体存在逻辑等价 bug

**严重程度：变体无增量信息，可移除或重新定义**

实施计划 Task 1 Step 4 的 `acceleration_or_accdelta` 检查：

```python
"passed": (
    acceleration >= 10                                          # 分支 A
    or (acc_delta is not None and acc_delta >= 8)               # 分支 B
    or (acc_delta is None
        and variant.treat_missing_acc_delta_as_optional
        and acceleration >= 10)                                 # 分支 C ≡ 分支 A
)
```

分支 C 的条件 `acc_delta is None and acceleration >= 10` 被分支 A 的 `acceleration >= 10` 完全覆盖。因此 `accdelta_optional` 变体在 acceleration >= 10 时与 baseline 等价，在 acceleration < 10 且 accDelta 缺失时与 baseline 等价，**永远不会产生增量召回**。

重放分析已确认实盘 stock row 中 `accDelta` 字段普遍缺失。这个变体在当前数据上对归因无贡献。

### 改法（二选一）

- **方案 A**：去掉该变体，改为在审计报告的 meta 中直接声明"实盘 accDelta 字段缺失，当前 acceleration gate 实际只依赖 acceleration >= 10"。
- **方案 B**：如果确需验证 accDelta 的独立贡献，先补一帧存在 accDelta >= 8 的真实数据作为 golden case，再跑对比。但从当前数据分布来看，这个验证可能在近期快照上无法闭环。

---

## 其他次要发现

| # | 发现 | 位置 | 建议 |
|---|------|------|------|
| 5 | `delta=13.6` 无业务依据 | Task 1 Step 4 `delta_13_6` 变体 | 换成 Python 研究侧常用值，或 delta=15 到 delta=10 之间的中点 12.5 |
| 6 | 测试未覆盖空 frame、stock_row 缺失 rankTrend、jump 为 null 等边界 | Task 1 Step 1-2 测试 | 补充至少 3 条边界测试：空 frame 列表、rankTrend 字段缺失、jump 对象为 null |
| 7 | replay 一致性未验证 | Task 2 `_replay_frame_signals` | 增加一个前置验证步骤：对 600186 的 2026-06-09 10:30 frame，确认 `RankTrendPythonEngine.replay_frame_at()` 产出的 signal 与手工重放一致 |
| 8 | `focus_codes` 默认值硬编码 `["600186", "002156"]` | Task 3 CLI wiring | 当前可接受，但应在文档中说明这两个是近期漏票样本的临时固定，后续应改为无默认值或从配置读取 |

---

## 修复顺序建议

```
问题 1（变体不正交）
  └─ 先修，因为所有后续归因都依赖变体定义
问题 3（jump 翻转未建模）
  └─ 紧随问题 1，决定方案 A 还是 B
问题 2（两层 gate 混为一层）
  └─ 在问题 1/3 的基础上拆分 gate checks
问题 4（accDelta 逻辑等价）
  └─ 可选，影响面最小
次要问题 5-8
  └─ 在 Task 1-3 实现过程中逐条关闭

## 对实施计划的最低要求

在进入编码前，实施计划至少应满足以下条件：

- `DEFAULT_SHADOW_VARIANTS` 已改成正交定义
- `delta_10 / delta_12_5` 被标记为需要单独 replay
- `evaluate_shadow_variants()` 的输出结构已预留 `jump` 与 `fusion` 两层 checks
- `accdelta_optional` 已从默认变体矩阵移除
- 服务层测试已覆盖：
  - `600186` 类样本：baseline miss，但 `delta/change/tier` 放宽后可召回
  - `002156` 类样本：不同 delta 下 `jump.direction` 可翻转
  - `focusFindings` 中同一帧同时展示 jump/fusion 两层结果
```

## 设计文档评估

[设计文档](../specs/2026-06-09-ranktrend-live-gate-shadow-audit-design.md) 本身结构完整、目标清晰：

- Section 3（非目标）的边界划分正确，research-only 定位可执行
- Section 5（审计基线）对 live 代码的引用准确，两层硬闸的识别正确
- Section 6（Shadow 变量矩阵）的 5 组变量选择合理，基本覆盖了重放分析暴露的问题域
- Section 7（二次排序诊断）的方向正确——把 stage/tier/direction/zeroCross/MACD 从硬过滤降级为排序因子
- Section 8（输出结构）的三层设计（逐票归因、召回变化表、排序建议表）可以直接回答最初的三个问题

设计文档无需大改。上述 4 个问题属于实施计划层面的翻译偏差，而非设计层面的方向错误。
