# RankTrend Golden 重新对齐复盘报告

日期：2026-06-08 | 复盘范围：原始设计 + implementation plan + 当前仓库状态 | 结论：主目标已落地，正式 TS Golden 验收已通过；Implementation Plan 中“全量 pytest 绿”这一条本轮没有按字面完整收口

## 复盘对象

- 设计规格：[2026-06-07-ranktrend-golden-realignment-design.md](../specs/2026-06-07-ranktrend-golden-realignment-design.md)
- 实施计划：[2026-06-07-ranktrend-golden-realignment-implementation-plan.md](2026-06-07-ranktrend-golden-realignment-implementation-plan.md)

## 复盘方法

1. 通读 design / implementation plan，提取原始目标、非目标和 Task 1-4 验收口径。
2. 逐文件核对当前实现：
   - `src/services/RankTrendAnalyzer.ts`
   - `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
   - `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`
   - `quant-board/backend/analysis/ranktrend.py`
   - `quant-board/backend/services.py`
   - `quant-board/tests/test_ranktrend_golden_alignment.py`
   - `quant-board/tests/test_quant_board.py`
   - `quant-board/docs/ranktrend-golden.md`
3. 核对落地提交：
   - `c428302` `fix: realign ranktrend golden analysis contract`
   - `cae2204` `test: fix golden smoke input contract`
4. 重新跑当前可直接证明结论的验证命令，不沿用旧结果。

## 总结论

1. **设计主目标已经完成**：TS 主分析链、TS Golden replay、Python RankTrend 分析链现在已经重新对齐到同一份 `half_hour` Golden 合同。
2. **正式验收已经完成**：当前本地 `rank_trend_default` Golden case 重新校验结果为 `source=ts_golden_import`、`isFormalTsGolden=True`、`passed=True`、`checked=100`、`issueCount=0`。
3. **实现与计划存在一个收口偏差**：Task 4 写的是全量 `.\.venv\Scripts\python.exe -m pytest` 绿；本轮 fresh evidence 只覆盖 Golden 对齐相关定向验证，不能把“QuantBoard 全量 pytest 已绿”写成已确认事实。

## 逐项复盘

| 项目 | 原设计/计划要求 | 当前状态 | 结论 |
| --- | --- | --- | --- |
| Task 1 | TS 主分析链与 TS Golden replay 共用同一条分析顺序 | 已新增 `runRankTrendAnalysisPipeline.ts`，`RankTrendAnalyzer.ts` 与 `RankTrendGoldenReplayEngine.ts` 都已切到共享 helper | 完成 |
| Task 2 | Python Golden replay 回到纯分析口径，不再消费 `hotlistSentiment` | `ranktrend.py` 已改为 `technical -> cycle -> risk -> cycle_with_risk -> decision -> compose_analysis_candidate_tier`，Golden 对齐测试覆盖 hotlist 隔离和风险回灌 | 完成 |
| Task 3 | GoldenService 摘要升级，正式比较 `cycle / decision / risk / momentumProfile / candidateTier` | `services.py` 已扩展 `_normalize_signals()` 与 `_normalize_expected_payload()`；API smoke test 也已补 `expectedPreview / actualPreview` 断言 | 完成 |
| Task 4 | 文档同步 + 真实数据集导出 TS Golden + formal live validation 通过 | `ranktrend-golden.md` 已更新；`output/rank_trend_default.half_hour.ts-golden.json` 存在；formal validate 当前为 0 issues | 实质完成 |

## 关键落地点

### 1. TS 端已经收口为单一真相源

当前共享分析 helper 已存在：

- `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`

两个消费方都已切到同一 helper：

- `src/services/RankTrendAnalyzer.ts`
- `src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`

这对应原设计 4.1 / 4.3 与 Task 1 的核心诉求，避免了 “runtime 一套顺序、golden replay 另一套顺序” 的平行漂移。

### 2. Python 端已经回到纯分析合同

当前 Python 分析链的关键顺序是：

```text
technical -> cycle -> risk -> cycle_with_risk -> decision -> compose_analysis_candidate_tier
```

这与 design 第 5 节、Task 2 的目标一致。实现上有一个与计划不同但合理的命名偏差：

- 计划里的 helper 名字是 `compose_candidate_tier`
- 当前实际落地名字是 `compose_analysis_candidate_tier`

这个偏差不影响语义，反而更明确地区分了：

- `compose_strategy()`：旧执行/热榜语义
- `compose_analysis_candidate_tier()`：新的纯分析 Golden 语义

另外，本轮实现还额外修掉了一个比原计划更关键的真实根因：

- `RankTrendConfig.requireMacdGoldenCross` 默认值已收口为 `False`

这一步不是“顺手优化”，而是 formal live validation 从大量 `buy -> hold` 偏差收口到 0 issues 的关键条件。

### 3. GoldenService 比较摘要已经升级

`quant-board/backend/services.py` 现在已经把以下嵌套结构纳入标准化比较：

- `risk`
- `cycle.transition`
- `cycle.entryAdvice`
- `cycle.decision`
- `decision.base`
- `decision.final`

这对应 design 第 6 节与 Task 3 的核心目标，避免再出现“生命周期/决策已漂移但摘要比较没看出来”的假绿。

### 4. Golden smoke test 还做了一个必要补丁

Task 3 完成后，又额外补了一个 `cae2204` 提交。原因不是算法再漂移，而是测试输入源不再满足新 Golden 合同：

- 旧 smoke test 使用回测 API 的压缩 `run["signals"]`
- 压缩信号不包含新的 nested `cycle / decision` 摘要
- 新合同下应改为对同一批 `golden_frames` 重新 `RankTrendPythonEngine(...).replay(...)`

这一步属于**验收口径修复**，不是设计变更。

## 与原计划的偏差

### 偏差 1：Task 2 的 helper 名称与计划不同

计划写的是 `compose_candidate_tier`，实际代码是 `compose_analysis_candidate_tier`。

判断：**可接受偏差**。

原因：

- 更准确表达“纯分析候选分层”
- 明确避开旧 `compose_strategy()` 的 hotlist/execution 语义

### 偏差 2：Task 4 的“全量 pytest 绿”没有作为本轮 fresh evidence 复核

计划 Step 2 写的是：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
```

本轮 fresh verification 实际运行的是：

- `tests/test_ranktrend_golden_alignment.py`
- `tests/test_quant_board.py::test_import_backtest_optimize_and_golden`

判断：**需要如实记录的收口偏差**。

这不影响“Golden 对齐主目标已完成”的结论，但会影响“整个 QuantBoard 后端当前全绿”的表述边界。复盘里只能写：

- Golden 对齐相关验证已绿
- formal TS Golden live validation 已绿

不能写：

- QuantBoard 全量 pytest 已确认全绿

## 非目标检查

原 design 的非目标基本被遵守：

1. **未把改动扩散到回测执行层主链**
   - 本轮核心改动集中在 TS 分析链、Python 分析链、GoldenService 和测试/文档。
2. **未重建 long-test baseline**
   - 没有证据显示本轮去改 long-test 基线。
3. **未把 `quarter_hour` 提升为默认 Golden 口径**
   - 当前正式口径仍是 `half_hour`。
4. **未通过削弱 TS 合同来让 Python 通过**
   - 相反，是把 TS shared pipeline、Python pure-analysis path、Golden summary 三端都收紧了。

## 当前证据

### 提交证据

- `c428302`：主对齐提交
- `cae2204`：Golden smoke 输入合同补丁

### 文件证据

- TS shared pipeline：`src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
- TS runtime 接入：`src/services/RankTrendAnalyzer.ts`
- TS Golden replay 接入：`src/services/quantBoardGolden/RankTrendGoldenReplayEngine.ts`
- Python pure-analysis path：`quant-board/backend/analysis/ranktrend.py`
- Golden summary：`quant-board/backend/services.py`
- Golden 对齐测试：`quant-board/tests/test_ranktrend_golden_alignment.py`
- API smoke test：`quant-board/tests/test_quant_board.py`
- 文档同步：`quant-board/docs/ranktrend-golden.md`

### Fresh verification

2026-06-08 当前环境重新验证结果：

```text
pnpm test:ranktrend -- src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts
-> 16 files passed, 146 tests passed

pnpm typecheck:ranktrend
-> exit 0

cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_golden_alignment.py -q
-> 8 passed

cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py::test_import_backtest_optimize_and_golden -q
-> 1 passed
```

formal Golden validate 当前结果：

```python
GoldenService(None).validate({'caseId': 'rank_trend_default', 'tolerance': 1e-6})
```

返回摘要：

```text
passed=True
source=ts_golden_import
isFormalTsGolden=True
checked=100
issueCount=0
```

## 最终判断

如果按**设计主目标**复盘，这次 RankTrend Golden 重新对齐已经完成，且正式 live validation 已经落地闭环。

如果按**implementation plan 的每一条字面验收**复盘，还剩一个需要如实标注的边界：

- “全量 `.\.venv\Scripts\python.exe -m pytest` 绿”本轮没有作为 fresh evidence 重新确认

所以最准确的结论是：

> **RankTrend Golden 对齐主任务已完成并正式验收通过；当前未确认的是 QuantBoard 全量测试套件的仓库级绿色状态，而不是 Golden 主链本身。**
