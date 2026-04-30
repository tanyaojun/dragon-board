# rankTrend Python 移植方案

## 移植目标

Python 版 rankTrend 的首要目标是对齐 TypeScript golden，不是优化或简化算法。只有 golden 校验稳定后，才进入回测和参数优化。

## 建议目录

```text
backend/
  ranktrend/
    __init__.py
    defaults.py
    types.py
    utils.py
    technical_signal_analyzer.py
    attention_cycle_analyzer.py
    risk_signal_analyzer.py
    result_composer.py
    market_regime_analyzer.py
    candidate_tier_composer.py
    status_classifier.py
    analyzer.py
```

命名可以 Python 化，但字段输出必须保持 TypeScript 合同。

## 移植顺序

1. `defaults.py`
   - 迁移默认运行参数。
   - 默认 `snapshot_type=half_hour`。
   - 实现配置归一化。

2. `utils.py`
   - `clamp`
   - `average`
   - `normalize_signed`
   - `calculate_signal_confidence`
   - `calculate_weighted_share`
   - `get_macd_min_samples`
   - `get_technical_min_samples`

3. `technical_signal_analyzer.py`
   - 移动平均。
   - EMA/MACD。
   - 多周期动量。
   - fallback 技术信号。

4. `attention_cycle_analyzer.py`
   - 生命周期阶段。
   - raw stage 到 normalized stage。
   - entry advice。

5. `risk_signal_analyzer.py`
   - 过热风险。
   - 注意力/资金背离。
   - pressure 与 synergy。

6. `result_composer.py`
   - direction、acceleration、zeroCross、MACD 加权合成。
   - base/final decision。

7. `market_regime_analyzer.py`
   - 情绪阶段、涨跌扩散、资金正向占比、量能活跃度。

8. `candidate_tier_composer.py`
   - `A_MAIN`、`B_IGNITION`、`C_CROWDED`、`D_EXIT_RISK`、`N_NEUTRAL`。

9. `analyzer.py`
   - 读取快照序列。
   - 构建排名历史。
   - 组装完整输出。

## 字段命名

内部 Python 可使用 `snake_case`：

```python
current_percentile = 94.5
```

对外 JSON 必须使用 TypeScript 字段：

```json
{
  "currentPercentile": 94.5
}
```

建议用 Pydantic model 或专门的 `to_public_dict()` 处理，不要在业务逻辑里散落字段转换。

## 数值注意事项

### JavaScript 与 Python 舍入

TypeScript 中常见：

```ts
Number(value.toFixed(2))
```

Python 不要直接用 `round()` 期待完全一致，因为二进制浮点和银行家舍入可能造成差异。建议实现 helper：

```python
def to_fixed_number(value: float, digits: int) -> float:
    return float(f"{value:.{digits}f}")
```

### NaN 与无穷

TypeScript 使用 `Number.isFinite()`。Python 要统一过滤：

- `math.isfinite(value)`
- 非数字按默认值处理
- 不允许把 `nan` 写入报告 JSON

### MACD

EMA 初始值与 TypeScript 一致：

- 第一个 EMA 等于 `data[0]`。
- multiplier 为 `2 / (period + 1)`。
- `histogram = 2 * (dif - dea)`。

最小样本：

```text
get_macd_min_samples = max(2, macdSlow)
get_technical_min_samples = max(macdSlow, max(momentumPeriods)+1, 30)
```

当前回测平台默认 MACD 参数是 `21/34/13`。MACD 金叉/死叉只作为入场前辅助观察信号，不是独立买卖触发器；真正的交易依据仍然是多周期动量、生命周期阶段、候选池分层、市场环境、风险压力和交易风控规则。更完整口径见 [backtest-policy.md](backtest-policy.md)。

## Analyzer 输入

建议 Python analyzer 接收标准化后的快照：

```python
{
    "snapshot_id": "half_hour:2026-04-30:10:00",
    "type": "half_hour",
    "trading_date": "2026-04-30",
    "slot_time": "10:00",
    "timestamp": 1777514400000,
    "capture_mode": "real_time",
    "hotlist": [
        {"code": "600000", "name": "...", "rank": 1, "price": 10.2}
    ],
    "market_context": {}
}
```

不要直接依赖 dragon-board 浏览器对象或 Vue store。

## Analyzer 输出

返回结构：

```python
dict[str, RankTrendAnalysisResult]
```

其中 key 为股票代码，对应 TypeScript `Map<string, RankTrendResult>` 的 JSON 化形态。

## 样本不足处理

当个股有效样本不足：

- 仍可计算 fallback 技术信号；
- `sampleQuality.status` 必须是 `degraded` 或 `insufficient`；
- 策略分层不得把样本不足结果直接升级为强机会；
- 前端展示应显示样本质量。

## 测试策略

### 单元测试

每个模块至少覆盖：

- 正常样本；
- 空数组；
- 样本不足；
- 极端值；
- 与 TypeScript golden 对齐的固定输入。

### Golden 测试

测试流程：

1. 读取 `golden_ranktrend_cases` 或测试 fixture JSON。
2. 调用 Python rankTrend。
3. 使用比较器递归比较字段。
4. 枚举和字符串完全一致，浮点按容差比较。

### 端到端测试

使用一个小型 fixture 数据集：

- 至少 35 条 `half_hour` 快照；
- 至少 20 只股票；
- 包含持续上升、冲高回落、样本缺失三类路径。

## 不要做的事

- 不从 `ParameterOptimizer` 复制参数。
- 不为了让回测更好看调整 golden 算法。
- 不把 `final.signal=buy` 直接等同于开仓。
- 不在 Python 里私自把默认快照改成 `quarter_hour`。
- 不在数据不足时静默返回空结果并标记成功。

## 完成标准

进入回测开发前必须满足：

- `defaults.py` 与 TypeScript 默认参数一致。
- 所有 golden case 通过。
- Python 输出 JSON 字段和 TypeScript 合同一致。
- `half_hour` 是默认快照。
- `quarter_hour` 测试证明只有显式传入时使用。
