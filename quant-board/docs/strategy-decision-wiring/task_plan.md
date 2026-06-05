# 策略信号链路修复 实施计划

## 目标

将 `compose_decision`（MACD/动量加权合成信号）接入交易决策链路，使其成为入场/出场的主驱动信号；`candidateTier` 降级为语境过滤；分层阈值可配置化。

## 成功标准

1. 入场必须同时满足 `finalSignal == "buy"` AND `candidateTier ∈ {A_MAIN, B_IGNITION}`
2. 出场新增 `finalSignal == "sell"` 触发条件
3. `compose_strategy()` 中所有硬编码分层阈值替换为 `RankTrendConfig` 可配字段
4. 所有现有测试通过
5. 新 checkpoint 复跑，L1 方向精度有改善

## 阶段

### Phase 1: RankTrendConfig 扩展 + compose_strategy 去硬编码

- [ ] `RankTrendConfig` 新增 11 个分层阈值字段（全部带默认值，等于当前硬编码值）
- [ ] `compose_strategy()` 签名增加 `config` 参数，所有硬编码阈值替换为 `config.xxx`
- [ ] `_build_signal()` 调用 `compose_strategy()` 时传入 `self.config`

**Files:** `quant-board/backend/analysis/ranktrend.py`

**验证:**
```bash
cd quant-board && .venv/Scripts/python.exe -c "from backend.analysis.ranktrend import RankTrendConfig; c = RankTrendConfig(); assert c.tierAMainMidMomentumMin == 4.0; print('OK')"
```

### Phase 2: 策略层 _entry_signal / _exit_signal 接入 finalSignal

- [ ] `_entry_signal()`: A_MAIN/B_IGNITION 需同时满足 `decision.final.signal == "buy"`
- [ ] `_exit_signal()`: 新增 `decision.final.signal == "sell"` 触发卖出
- [ ] 保持现有 regime/rank/tier 规则不变

**Files:** `quant-board/backend/core/backtest/strategy.py`

**验证:**
```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/ -k "strategy" -v
```

### Phase 3: 交易执行器 _entry_candidates + 出场逻辑 接入 finalSignal

- [ ] `_entry_candidates()`: 增加 `finalSignal == "buy"` 过滤
- [ ] `TradeSimulator.run()` 出场条件增加 `finalSignal == "sell"`
- [ ] `_entry_reason()` 和 `_signal_explanation()` 更新描述

**Files:** `quant-board/backend/core/backtest/execution.py`

**验证:**
```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/ -k "backtest or strategy or entry" -v
```

### Phase 4: 测试补齐

- [ ] 分层阈值配置化单元测试
- [ ] finalSignal 入场/出场逻辑集成测试
- [ ] 空信号、边界值、default 兼容性测试

**Files:** `quant-board/tests/test_quant_board.py`, `quant-board/tests/test_money_flow_quality_gate.py`

**验证:**
```bash
cd quant-board && .venv/Scripts/python.exe -m pytest -v
```

### Phase 5: Checkpoint 复跑 + 对比

- [ ] 执行 `run-longtest-baselines --checkpoint-id checkpoint_2026-06-05_strategy_fix`
- [ ] 对比修复前后 H1/H2/Q1 绩效和 L1 方向精度
- [ ] 更新 findings.md 和 progress.md

**验证:** checkpoint JSONL 新增记录，方向精度改善

## 决策记录

| 决策 | 理由 |
|---|---|
| `compose_decision` 作主信号，`candidateTier` 作过滤 | 用户要求 A+B+C 三个方向合并；两者互补而非替代 |
| 分层阈值默认值等于当前硬编码值 | 最小破坏性，不改表现直到用户显式调参 |
| 不改 `compose_decision()` 和 `compose_strategy()` 计算内核 | 聚焦链路修复，不引入新的计算逻辑变更 |

## 风险

- 交易数可能大幅下降（过滤掉无技术确认的 A_MAIN）
- `finalSignal == "buy"` 频率未知，可能导致入场过少
- 回测结果可能与之前 checkpoint 不可直接对比（策略逻辑变了）
