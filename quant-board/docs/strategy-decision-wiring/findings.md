# 策略信号链路修复 研究发现

## 核心发现

### F1: compose_decision 被架空

[execution.py:227-258](quant-board/backend/core/backtest/execution.py#L227-L258) — `_entry_candidates()` 是唯一决定买入的函数。对于 `rank_trend_candidate` 策略，它只检查 `candidateTier ∈ {A_MAIN, B_IGNITION}` 和 `regime != "weak"`，从不读取 `compose_decision.final.signal`。

`compose_decision()` 使用用户配置的 MACD/动量权重和阈值合成信号，写入每个信号的 `rankTrend.decision.final` 字段，但**没有任何代码消费它**。

### F2: 分层阈值全部硬编码

[ranktrend.py:664-697](quant-board/backend/analysis/ranktrend.py#L664-L697) — `compose_strategy()` 中的动量门槛是写死的：
- `momentum["mid"] >= 4` → A_MAIN
- `momentum["short"] >= 3` → B_IGNITION
- `momentum["long"] >= 4` → C_CROWDED
- `momentum["short"] <= -2` → D_EXIT_RISK

这些阈值不在 `RankTrendConfig` 中，用户无法调整。

### F3: 生命周期阶段驱动分层，分层驱动交易

热榜排名百分位的速度和加速度 → `raw_stage()` / `normalize_stage()` → 生命周期阶段 → `compose_strategy()` → `candidateTier` → 买卖。

MACD/动量参数只通过 `momentumProfile` 间接影响分层，且受硬编码阈值限制。

### F4: 这解释了 L1 方向精度 39%

A_MAIN 被标记为"主升"不是因为 MACD 金叉，而是因为"排名在涨 + 处于扩散期"。这两个条件和技术指标看涨的相关性不高，导致 A_MAIN 信号的下一 bar 上涨概率仅 39%，低于 50% 随机基准。

### F5: compose_decision 与 compose_strategy 的输出不一致

同一只股票可能同时：
- `candidateTier == "A_MAIN"`（生命周期分层说买）
- `compose_decision.final.signal == "sell"`（MACD/动量合成说卖）

当前架构下前者胜出。修复后后者应至少能阻止买入。

## 证据来源

- `quant-board/backend/analysis/ranktrend.py` — 信号生成、分层、决策合成
- `quant-board/backend/core/backtest/execution.py` — 交易执行
- `quant-board/backend/core/backtest/strategy.py` — 策略信号生成
- `quant-board/backend/services.py` — 回测编排
