# RankTrend Engine 拆分设计

## 目标

将 `quant-board/backend/analysis/ranktrend/engine.py` 从约 2470 行的多职责文件拆分为可独立理解和测试的模块，同时保持 Python RankTrend golden 输出、API、replay、backtest 行为不变。

## 现状与约束

- `engine.py` 同时承载配置、数学原语、技术指标、生命周期、风险、共振、观察组装和 replay 编排。
- 仓库内已有代码直接从 `backend.analysis.ranktrend.engine` 导入大量函数，因此不能一次性删除旧导入路径。
- Python engine 是生产 golden；本次只做结构重构，不调整默认参数、字段合同或评分公式。
- 质量异常仍须 fail-visible，不能因拆分而恢复零值伪造或数据硬门禁。

## 模块边界

### `config.py`

负责 `RankTrendConfig`、配置 patch 类型转换、tier 约束校验和样本数阈值。

### `primitives.py`

负责 `clamp`、有限数判断、均值、归一化、百分位、EMA、移动平均等无领域状态的纯函数。

### `technical.py`

负责 MACD、动量 profile、动量信号、技术 fallback 信号和技术分析入口。

### `lifecycle.py`

负责周期指标、阶段判定、生命周期决策、生命周期 tier 与候选层分析。

### `risk.py`

负责风险分析、市场 regime、displayStatus 相关的纯计算辅助。

### `observation.py`

负责共振、观察维度、synergy/tier 组装及最终信号融合。

### `engine.py`

只保留 `RankTrendPythonEngine`、replay 状态管理和跨模块编排。为兼容既有调用方，旧公开符号在文件末尾通过显式 re-export 保留。

## 迁移策略

1. 先为每个目标模块建立从旧文件导出的兼容接口，避免一次移动导致循环依赖。
2. 按“无状态纯函数优先、状态编排最后”的顺序迁移：配置/原语 → 技术 → 生命周期/风险 → 观察 → Engine。
3. 每次迁移后运行对应 pytest；使用 golden/现有 API 测试确认输出 JSON 深度相等。
4. 发现循环依赖时只允许依赖下层模块，禁止新模块反向 import `engine.py`；需要类型时使用局部导入或 `TYPE_CHECKING`。
5. 完成后扫描 `engine.py`，确保仅保留 Engine 类、必要的私有编排辅助和兼容 re-export。

## 验证标准

- 现有 RankTrend、API、回测、tier 测试全部通过。
- 新增模块级纯函数测试至少覆盖配置转换、技术指标、生命周期/风险和观察组装的公开入口。
- `vue-tsc` 不受影响，Python `compileall` 通过。
- `git diff --check` 通过，且不产生额外运行产物。
- 不改变任何默认参数、输出字段名、字段类型、排序规则和质量标记语义。
