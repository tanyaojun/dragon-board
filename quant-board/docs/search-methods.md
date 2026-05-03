# 参数搜索方法说明

本文说明 QuantBoard 参数优化页、API 和 CLI 当前面向用户展示的四个正式 `method`：

- `grid`
- `random`
- `bayesian`
- `tpe`

`optuna_tpe` 不是独立搜索方法。它只作为后端兼容别名保留，用于读取或复现旧实验、旧脚本里的请求；新实验、前端页面和 CLI 都应使用 `tpe`。

## 当前实现结论

| method | 用户入口 | 当前状态 | 底层算法 | 结果标识 |
| --- | --- | --- | --- | --- |
| `grid` | 前端 / API / CLI | 已实现 | 离散笛卡尔积穷举 | `optimizer=grid` |
| `random` | 前端 / API / CLI | 已实现 | 固定 seed 的离散候选随机排列后截断 | `optimizer=random` |
| `bayesian` | 前端 / API / CLI | 已实现 | Optuna `GPSampler` 高斯过程贝叶斯优化 | `optimizer=optuna_gp`, `optimizerMeta.sampler=GPSampler` |
| `tpe` | 前端 / API / CLI | 已实现 | Optuna `TPESampler` | `optimizer=optuna_tpe`, `optimizerMeta.sampler=TPESampler` |
| `optuna_tpe` | 仅后端兼容 | 已实现为别名 | 与 `tpe` 完全相同 | `optimizer=optuna_tpe`, `optimizerMeta.sampler=TPESampler` |

实现入口位于 `backend/optimization/runner.py`。正式搜索方法是四个；`optuna_tpe` 只保留在后端 schema 和 runner 中，避免旧记录或旧自动化脚本失效。

## 统一执行流程

四个正式搜索方法共享同一套 trial 执行、评分和记录链路：

1. 读取 `searchSpace` 或 `parameterGrid`，归一化为离散 choices。
2. 根据 `method` 生成一组候选参数。
3. 对每个 trial 合并基础 RankTrend 配置和交易配置。
4. 使用 `BacktestEngine` 分别执行 train 和可选 validation 回测。
5. 根据 `objective` 计算 `score` 和 `scoreDetails`。
6. 写入 trial 级 `configHash`、train/validation artifact、指标、风险和排序。
7. 对 Top trials 做 walk-forward 复核和参数稳定性分析。
8. `POST /api/optimizations/rank-trend` 立即返回 `running`，后台完成后通过 `GET /api/optimizations/{runId}` 读取结果。

当前搜索空间只支持离散 choices。连续区间、`min/max/step` 这类 range spec 暂不开放；传入 range spec 会返回结构化错误，避免把连续优化伪装成已实现能力。

## 搜索空间口径

前端表单里的 `parameterGrid` 会映射为后端 `search_space`。示例：

```json
{
  "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16]],
  "takeProfitPct": [0.08, 0.12, 0.16],
  "stopLossPct": [0.04, 0.06, 0.08],
  "maxPositions": [3, 5, 8]
}
```

后端会把每个参数都视为离散候选值。Optuna 方法不会直接在真实值上采样，而是先采样每个参数的索引：

```text
takeProfitPct__idx in [0, len(takeProfitPct) - 1]
stopLossPct__idx   in [0, len(stopLossPct) - 1]
maxPositions__idx  in [0, len(maxPositions) - 1]
```

再把索引映射回真实参数值。这样做的原因是 RankTrend 当前开放的是离散组合研究，能保持搜索空间可解释、可复现，并避免连续参数带来的边界和精度问题。

## `grid` 网格搜索

### 计算方式

`grid` 对所有参数 choices 做稳定顺序的笛卡尔积：

```text
C = P1 x P2 x ... x Pn
```

其中 `Pi` 是第 `i` 个参数的候选列表，`C` 是全部参数组合。执行顺序与搜索空间参数顺序和候选值顺序一致。

如果总组合数大于 `trials` 或 `maxTrials`，只执行前 `N` 个组合：

```text
executed = C[0:N]
N = trials 或 maxTrials
```

### 特点

- 完全可复现。
- 最适合小搜索空间和基准校验。
- 能明确知道总组合数和实际执行数。
- 参数空间稍大时成本会快速膨胀。

### 适用场景

- 第一次验证某个参数是否有效。
- 参数候选很少，例如每个参数只有 2 到 4 个值。
- 希望完整覆盖所有组合，不想让采样器跳过组合。

### 使用示例

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "method": "grid",
  "trials": 36,
  "objective": "stability",
  "parameterGrid": {
    "takeProfitPct": [0.08, 0.12, 0.16],
    "stopLossPct": [0.04, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

## `random` 随机搜索

### 计算方式

`random` 先生成和 `grid` 相同的完整离散候选组合，然后用本地随机源按 `randomSeed` 洗牌：

```text
C = P1 x P2 x ... x Pn
rng = Random(randomSeed)
shuffle(C)
executed = C[0:N]
```

### 特点

- 固定 `randomSeed` 时 trial 序列可复现。
- 对较大搜索空间更省成本。
- 不保证覆盖所有组合。
- 当前不是逐 trial 有放回采样，而是对完整候选列表洗牌后截断，因此同一次优化内不会重复执行同一个组合。

### 适用场景

- 总组合数明显大于计划 trial 数。
- 想快速获得参数空间的粗略分布。
- 需要一个比网格更快的基线方法。

### 使用示例

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "method": "random",
  "randomSeed": 20260430,
  "trials": 50,
  "objective": "risk_adjusted",
  "parameterGrid": {
    "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16]],
    "takeProfitPct": [0.08, 0.1, 0.12, 0.16],
    "stopLossPct": [0.04, 0.05, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

## `bayesian` 高斯过程贝叶斯搜索

### 计算方式

`bayesian` 使用 Optuna `GPSampler(seed=randomSeed)`。它会根据已完成 trial 的参数索引和目标分数，构建高斯过程代理模型，用代理模型估计未尝试参数组合的潜在表现，并在探索和利用之间做选择。

当前实现仍只处理离散 choices。每个参数先被转换为整数索引：

```text
xi = suggest_int("{param}__idx", 0, len(choices) - 1)
param_value = choices[xi]
```

Optuna 看到的是整数索引空间，QuantBoard trial 实际执行的是索引映射后的真实参数。

每个 trial 的目标值是 QuantBoard 的 `score`：

```text
maximize score(objective, train_metrics, validation_metrics, penalties)
```

如果 trial 执行失败，会给 Optuna 返回一个极低分数，避免失败 trial 被当成优选候选。

### 高斯过程数学口径

高斯过程贝叶斯优化的核心假设是：未知目标函数 `f(x)` 可以由一个高斯过程代理模型近似：

```text
f(x) ~ GP(m(x), k(x, x'))
```

其中：

- `x` 是参数索引向量。
- `m(x)` 是均值函数。
- `k(x, x')` 是协方差核函数。
- 已完成 trial 会形成观测集合 `D = {(x1, y1), ..., (xt, yt)}`。

每轮采样时，代理模型根据历史观测推断候选点的后验分布：

```text
p(f(x) | D)
```

采样器再根据采集函数选择下一个参数点。直观上，均值高的位置代表可能收益好，不确定性高的位置代表值得探索。GP 方法适合 trial 成本较高、参数维度不太大、希望利用历史 trial 信息的场景。

具体核函数、采集函数和内部初始化策略由 Optuna `GPSampler` 实现负责，QuantBoard 不重写这些数学细节，只负责把离散参数空间、seed、objective score 和 trial 结果传入 Optuna。

### 结果字段

`bayesian` 完成后应看到：

```json
{
  "method": "bayesian",
  "optimizer": "optuna_gp",
  "optimizerMeta": {
    "library": "optuna",
    "sampler": "GPSampler"
  }
}
```

每个 trial 会保留：

```json
{
  "optunaTrialNumber": 0,
  "optunaParams": {
    "takeProfitPct__idx": 1,
    "stopLossPct__idx": 0
  }
}
```

### 依赖要求

Optuna `GPSampler` 运行时依赖 `torch`。如果环境缺少 `torch`，`method=bayesian` 会失败并返回结构化错误。当前项目依赖已包含 `torch==2.6.0`。

### 适用场景

- 单次 trial 成本较高，不适合完整网格。
- 目标函数有一定连续性或局部规律，即相近参数组合的表现可能相关。
- 希望比随机搜索更充分利用已完成 trial。

### 使用示例

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "method": "bayesian",
  "randomSeed": 20260430,
  "trials": 36,
  "objective": "stability",
  "validationMode": "auto",
  "validationRatio": 0.3,
  "parameterGrid": {
    "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16], [5, 8, 13, 21, 34]],
    "takeProfitPct": [0.08, 0.12, 0.16],
    "stopLossPct": [0.04, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

## `tpe` TPE 搜索

### 计算方式

`tpe` 使用 Optuna `TPESampler(seed=randomSeed, n_startup_trials=startupTrials)`。

TPE 的核心思想不是直接拟合 `p(y | x)`，而是把历史 trial 按分数分成表现较好的集合和表现较差的集合，分别估计：

```text
l(x) = p(x | y is good)
g(x) = p(x | y is bad)
```

采样时倾向选择能提高 `l(x) / g(x)` 的参数点，也就是更像好 trial、较不像差 trial 的区域。

和 GP 一样，QuantBoard 当前传给 Optuna 的仍是离散参数索引：

```text
xi = suggest_int("{param}__idx", 0, len(choices) - 1)
```

### 特点

- 固定 `randomSeed` 时 trial 序列可复现。
- 对离散参数和混合参数空间更稳健。
- 相比 GP，对高维或不平滑目标通常更宽容。
- 前若干个 `startupTrials` 会以启动采样为主，用来积累初始观测。

### 结果字段

```json
{
  "method": "tpe",
  "optimizer": "optuna_tpe",
  "optimizerMeta": {
    "library": "optuna",
    "sampler": "TPESampler"
  }
}
```

### 适用场景

- 希望保留 TPE 对照实验。
- 参数空间比较离散、不平滑。
- 搜索维度较多，GP 代理模型收益不确定。

### 使用示例

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "method": "tpe",
  "randomSeed": 20260430,
  "trials": 36,
  "startupTrials": 10,
  "objective": "stability",
  "parameterGrid": {
    "takeProfitPct": [0.08, 0.1, 0.12, 0.16],
    "stopLossPct": [0.04, 0.05, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

## `optuna_tpe` 兼容别名

`optuna_tpe` 和 `tpe` 使用完全相同的后端实现：

```text
TPESampler(seed=randomSeed, n_startup_trials=startupTrials)
```

它保留的原因只有兼容性：

- 已保存的历史实验可能记录了 `method=optuna_tpe`。
- 旧自动化脚本可能仍提交 `method=optuna_tpe`。
- 读取旧结果时仍应得到相同的 `optimizer=optuna_tpe` 和 `optimizerMeta.sampler=TPESampler`。

新实验不要使用 `optuna_tpe`。前端和 CLI 不展示该入口，统一使用 `tpe`，避免把同一个算法误解成两个搜索方法。

## API 使用

提交优化任务：

```http
POST /api/optimizations/rank-trend
Content-Type: application/json
```

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "method": "bayesian",
  "randomSeed": 20260430,
  "trials": 36,
  "objective": "stability",
  "validationMode": "auto",
  "validationRatio": 0.3,
  "parameterGrid": {
    "takeProfitPct": [0.08, 0.12, 0.16],
    "stopLossPct": [0.04, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

提交成功后立即返回：

```json
{
  "runId": "opt_xxx",
  "id": "opt_xxx",
  "status": "running"
}
```

轮询状态：

```http
GET /api/optimizations/opt_xxx
```

完成后返回结果中应包含：

```json
{
  "status": "completed",
  "method": "bayesian",
  "optimizer": "optuna_gp",
  "optimizerMeta": {
    "library": "optuna",
    "sampler": "GPSampler"
  },
  "best": {},
  "trials": [],
  "results": [],
  "experiment": {},
  "walkForward": {},
  "parameterStability": {}
}
```

失败时返回：

```json
{
  "status": "failed",
  "error": {
    "code": "OPTIMIZATION_FAILED",
    "message": "..."
  }
}
```

## CLI 使用

默认同步等待完成：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli optimize-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --method bayesian `
  --trials 36 `
  --objective stability
```

只提交任务并立即返回 `runId`：

```powershell
.\.venv\Scripts\python.exe -m backend.cli optimize-ranktrend `
  --dataset-id ds_xxx `
  --method tpe `
  --trials 36 `
  --no-wait
```

`--method` 可选：

```text
grid
random
bayesian
tpe
```

## 前端使用

在 QuantBoard 轻实验台进入“参数优化”页：

1. 选择数据集和 `snapshotType`。
2. 选择 `method / 搜索方法`。
3. 设置 `trials / 试验次数`、`objective / 优化目标`、validation 和 walk-forward 参数。
4. 输入参数候选列表，例如止盈、止损、最大持仓数、动量周期组。
5. 点击“启动优化”。
6. 页面进入 `running` 状态并按 `runId` 轮询。
7. 完成后查看 `best`、trial 表格、`optimizerMeta.sampler`、风险提示和 JSON 结果。

建议日常选择顺序：

1. 先用 `grid` 在小空间做基准。
2. 搜索空间变大后用 `random` 快速摸底。
3. 用 `tpe` 保留 TPE 对照实验。
4. 用 `bayesian` 做高斯过程贝叶斯优化，观察是否比随机/TPE 更快找到稳定参数。

## 结果解读

重点字段：

| 字段 | 含义 |
| --- | --- |
| `method` | 用户提交的搜索入口 |
| `optimizer` | 后端实际优化器标识 |
| `optimizerMeta.sampler` | 具体采样器，例如 `GPSampler` 或 `TPESampler` |
| `trialCount` | 实际生成的 trial 数 |
| `completedTrialCount` | 成功完成的 trial 数 |
| `failedTrialCount` | 执行失败的 trial 数 |
| `best` | 按 objective 排序后的最佳 trial |
| `scoreDetails` | 分数拆解和惩罚项 |
| `validation` | 样本外验证结果；为空时过拟合风险更高 |
| `walkForward` | Top trials 滚动复核结果 |
| `parameterStability` | 参数稳定性统计 |

判断一次优化是否可信，不应只看 `best.score`。至少同时检查：

- validation 是否存在。
- train 和 validation 表现是否方向一致。
- `overfitRisk` 是否过高。
- walk-forward 各段是否稳定。
- 最优参数附近是否有多个相近得分的候选，而不是单点偶然最优。

## 选择建议

| 场景 | 建议 method |
| --- | --- |
| 小搜索空间、需要完整覆盖 | `grid` |
| 大搜索空间、先快速探索 | `random` |
| 需要 TPE 对照口径 | `tpe` |
| trial 成本较高，希望使用代理模型 | `bayesian` |
| 需要严格复现实验 | 任意方法都固定 `randomSeed`，优先 `grid` 或 `random` |

优化结果只产出候选参数，不会自动写回 RankTrend 默认值。任何候选参数都应经过独立样本外验证和人工评估后再采用。
