# RankTrend Golden 重新对齐设计规格

日期：2026-06-07 | 状态：待用户审阅

## 动机

TypeScript 端和 Python 端的 RankTrend 分析链都经历了多轮迭代。当前 QuantBoard 的 Golden 校验虽然还保留了导入和校验入口，但它默认比较的字段摘要偏旧，而且 TS 主分析链、TS Golden 导出链、Python 分析链已经出现口径漂移。

这次任务的目标不是“先把页面点绿”，而是重新建立一条可解释、可复现、可持续维护的 RankTrend Golden 主链：

- 真相源仍然是 Dragon Board TypeScript `RankTrendAnalyzer` 与 `src/services/rankTrend/**`
- 正式验收样本使用当前真实数据集导出的 `half_hour` TS Golden
- 只处理纯 RankTrend 分析合同，不把回测执行层、热榜情绪执行偏置、长测基线或优化逻辑混进来

## 目标

1. 重新收口 TS 主分析链与 TS Golden 导出链，确保二者使用同一份 RankTrend 分析顺序。
2. 让 Python `backend/analysis/ranktrend.py` 重新对齐当前 TS RankTrend 输出合同。
3. 升级 Golden 校验摘要字段，覆盖当前关键的 `cycle / decision / risk / momentumProfile / candidateTier` 合同。
4. 保持 QuantBoard 现有 Golden import / validate 工作流可用。
5. 使用当前真实 `datasetId + snapshotType=half_hour` 的 TS 导出结果作为正式跨语言验收样本。

## 非目标

- 不改 `quant-board/backend/core/backtest/**` 的执行层逻辑。
- 不改 `strategy.py`、`execution.py`、`hotlist_sentiment.py` 等回测执行口径。
- 不重建 long-test baseline。
- 不顺手调整优化参数空间、目标函数或报告展示。
- 不把 `quarter_hour` 提升为默认 Golden 口径。
- 不为了让 Python 更容易通过校验而降低 TS 当前主链的合同强度。

---

## 1. 当前问题定义

### 1.1 漂移不只发生在 TS 与 Python 之间

当前存在三条需要区分的链路：

1. TS 主分析链：`src/services/RankTrendAnalyzer.ts`
2. TS Golden 导出链：`src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`
3. Python 分析链：`quant-board/backend/analysis/ranktrend.py`

这三条链当前不应再被视为天然一致。已经确认的高风险漂移点包括：

- TS 主分析链在 `risk` 生成后会再次调用 `analyzeAttentionCycle`，用于让生命周期决策吸收风险证据。
- TS Golden 导出链当前自行拼装 `technical -> cycle -> risk -> decision -> strategy`，没有保证与主分析链复用同一分析顺序。
- Python 端既要追 TS 分析输出，又不能混入执行层对 `candidateTier` 的额外消费语义。

### 1.2 现有 Golden 比较摘要偏旧

当前 `GoldenService._normalize_signals()` 主要比较：

- `candidateTier`
- `action`
- `stage`
- `regime`
- `rank`
- `confidence`
- `finalSignal`
- `technicalSignals`
- `momentumProfile`
- `risk`

这些字段对早期版本够用，但对当前 RankTrend 演进后的生命周期和决策链来说，覆盖不够完整，容易出现“合同已经漂移，但校验仍然通过”。

---

## 2. 真相源与正式验收口径

### 2.1 真相源

本次任务中，唯一正式真相源为：

- `src/services/RankTrendAnalyzer.ts`
- `src/services/rankTrend/**`

其中 `RankTrendAnalyzer` 负责：

- 快照读取与排序
- 个股历史样本拼接
- 样本质量总结
- market regime 上下文注入
- 最终 `RankTrendAnalysisResult` 组装

`src/services/rankTrend/**` 负责：

- `technical`
- `cycle`
- `risk`
- `decision`
- `candidate tier`

### 2.2 正式验收样本

正式跨语言验收使用：

- 当前真实数据集
- `snapshotType=half_hour`
- 从 Dragon Board 当前页面导出的 TS Golden JSON

这意味着本次修复是“对齐当前正在使用的 RankTrend 主链”，不是回溯去兼容旧文档或历史实验快照。

### 2.3 为什么不用 Python 自基线作为正式验收

`/api/golden/baseline` 保存的是 Python 当前输出，只能用于“Python 对自身是否漂移”的临时回归，不是正式跨语言验收。

因此这次成功标准不能是：

- `source=python_current_output` 下通过

而必须是：

- 导入 `source=ts_golden_import` 的 TS Golden 后，Python 校验通过

---

## 3. 设计方案

### 3.1 方案选择

本次采用：

- 先收口 TS Golden 生成链
- 再对齐 Python 分析链

不采用“直接把 Python 修到追现有导出结果”的方案，因为如果 TS 导出链本身已落后于主分析链，会把错误固化成正式标准。

### 3.2 核心原则

1. 先证明 TS 内部一致，再让 Python 追 TS。
2. 分析合同与执行合同分离。
3. 只改必要文件，不借机扩散到回测或优化模块。
4. Golden 对齐失败时要能报出字段路径，而不是只给一个模糊通过/失败结果。

---

## 4. TS 端收口设计

### 4.1 新增共享分析 helper

新增一个窄作用域纯函数 helper，放在 `src/services/rankTrend/` 下，职责只有一件事：

- 输入 `ranks / percentiles / stock metrics / regime / config`
- 按正式顺序产出完整分析结果片段

建议顺序固定为：

1. `technical`
2. `cycle` 第一轮
3. `risk`
4. `cycle` 第二轮（吸收 risk 证据）
5. `decision`
6. `strategy`

这个 helper 不负责：

- 读取 DataLayer
- 拉 API
- 构建样本质量
- 决定快照来源
- 更新前端信号存储

### 4.2 `RankTrendAnalyzer.ts` 的职责保持不变

`src/services/RankTrendAnalyzer.ts` 仍保持当前主入口职责：

- 组织快照历史
- 构建 `sampleQuality`
- 计算 `currentPercentile / rawChange / displayChange`
- 读取 market regime
- 组装最终 `RankTrendAnalysisResult`

变化只在于：

- 不再在文件内手写分析顺序
- 改为调用共享 helper

### 4.3 `RankTrendGoldenReplayEngine.ts` 不再维护平行逻辑

`src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts` 也改为调用同一 helper。

这样可确保：

- TS 主分析链和 TS Golden 导出链共享同一分析顺序
- 后续再修改 lifecycle / risk / decision 时，不会再次出现“主链改了、Golden 导出忘了跟”的漂移

### 4.4 TS 端不在本轮做的事

- 不重新设计 `attentionCycleAnalyzer.ts` 算法本体
- 不修改 `candidateTier` 商业语义
- 不改 UI 展示
- 不改 TS 导出文件格式，除非校验器必须依赖当前合同字段

---

## 5. Python 端对齐设计

### 5.1 对齐对象

Python 端本轮只对齐：

- `quant-board/backend/analysis/ranktrend.py`

目标是让它重新匹配 TS 的 RankTrend 分析合同，而不是去匹配回测执行层的策略消费结果。

### 5.2 允许修改的内容

- 分析顺序
- 生命周期在 risk 之后的再计算
- `decision` 组装顺序
- `strategy.candidateTier / action` 的分析层输出
- 与 TS 默认分析合同直接相关的字段归一化

### 5.3 不允许修改的内容

- `quant-board/backend/core/backtest/**`
- `quant-board/backend/operations/hotlist_sentiment.py`
- 回测引擎对 RankTrend 输出的执行解释
- 优化与报告逻辑

如果 Python 端当前分析文件中混入了执行层语义，本轮只能做“剥离回纯分析合同”的收口，不能借机重写执行层。

---

## 6. Golden 校验摘要升级

### 6.1 当前问题

现有摘要字段不够覆盖当前合同，容易漏掉：

- 生命周期阶段演进
- 生命周期决策解释
- `decision.final.confidence`

### 6.2 本轮建议纳入的字段

在不发明新合同的前提下，Golden 摘要至少升级覆盖：

- `snapshotId`
- `code`
- `candidateTier`
- `action`
- `stage`
- `regime`
- `rank`
- `confidence`
- `finalSignal`
- `technicalSignals`
- `momentumProfile`
- `risk`
- `cycle.transition`
- `cycle.entryAdvice`
- `decision.final.confidence`

如果当前 TS/Python 都已稳定提供 `cycle.decision`，则应一并纳入。

### 6.3 升级原则

- 只升级到“当前 RankTrend 运行时已经稳定存在”的字段
- 不为了更容易比较而删字段
- 不把 ThemeTrend、执行层或报告富化字段纳入 Golden 合同

---

## 7. 测试策略

### 7.1 第一层：TS 内部一致性

新增或调整 TS 测试，验证：

- 同一批 `half_hour` frames
- TS 主分析链输出
- 与 TS Golden 回放器输出

在关键字段上完全一致

目标是先证明“TS 自己只有一份真相源”。

### 7.2 第二层：Python 对齐测试

在 QuantBoard 测试中验证：

- 导入 TS Golden
- `validate-golden` 能对当前真实结构完成归一化比较
- 关键字段一致时通过
- 差异存在时能给出清晰路径

### 7.3 第三层：回归验证

除了通过与失败，还要验证：

- `sampleLimit` 仍有效
- `expectedPreview / actualPreview` 仍能工作
- 失败信息可定位到具体字段，例如：
  - `$. [12].cycle.transition`
  - `$. [12].decision.final.confidence`

---

## 8. 影响文件边界

### 8.1 TS 端

预计涉及：

- `src/services/RankTrendAnalyzer.ts`
- `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`
- `src/services/rankTrend/**` 下新增一个共享分析 helper
- 邻近 `__tests__/*.test.ts`

### 8.2 Python 端

预计涉及：

- `quant-board/backend/analysis/ranktrend.py`
- `quant-board/backend/services.py`
- `quant-board/tests/test_quant_board.py`
- 若已有更贴近 ranktrend 的测试文件，则优先补在对应测试文件

### 8.3 文档

至少同步：

- `quant-board/docs/ranktrend-golden.md`

如果 API/CLI 行为描述受影响，还应同步检查：

- `quant-board/docs/api-cli.md`
- `quant-board/docs/AI_COLLABORATION.md`

---

## 9. 风险与控制

### 9.1 风险：TS 主链与导出链不只一个漂移点

控制方式：

- 先补 TS 内部一致性测试
- 发现一个修一个，不让 Python 在 TS 未收口前被迫追逐漂移中的目标

### 9.2 风险：Python 分析链夹带执行层语义

控制方式：

- 限定修改范围只在 `analysis/ranktrend.py`
- 不把 `hotlistSentiment`、交易执行条件、回测订单逻辑纳入 Golden 对齐

### 9.3 风险：Golden 摘要增强后暴露更多历史漂移

控制方式：

- 接受先红后绿
- 把新增失败视为“之前没比出来”的真实问题
- 不回退字段覆盖范围来掩盖问题

### 9.4 风险：真实数据集样本持续变化

控制方式：

- 正式验收以当前导入的 TS Golden 文件为准，不直接依赖“实时再抓一遍就一定相同”
- 后续如果需要稳定回归，可在后续任务中再补固定 fixture；本轮不扩范围

---

## 10. 验收标准

本次任务完成需同时满足：

1. TS 主分析链与 TS Golden 导出链在同一批 `half_hour` frames 上一致。
2. 当前真实数据集导出的 TS Golden 可以成功导入 QuantBoard。
3. Python 对这份 `source=ts_golden_import` 的 TS Golden 校验通过。
4. Golden 比较摘要已覆盖当前关键 RankTrend 合同，而不只停留在旧摘要字段。
5. 本轮没有改动回测执行层、长测基线或优化口径。

---

## 11. 实施后续

本设计确认后，下一步应进入 implementation plan，按以下节奏拆解：

1. 先写 TS 内部一致性的失败测试
2. 收口 TS 共享分析 helper
3. 再写 Python Golden 失败测试
4. 对齐 Python 分析链
5. 升级 Golden 校验摘要与文档
6. 最后跑 `pnpm test:ranktrend`、`pnpm typecheck:ranktrend`、QuantBoard `pytest` 和定向 Golden 校验

本设计刻意不包含实现细节代码块；实现阶段必须按 TDD 和最小改动原则推进。
