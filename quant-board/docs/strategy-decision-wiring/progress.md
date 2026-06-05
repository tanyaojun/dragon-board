# 策略信号链路修复 进度

## Session: 2026-06-05

### Phase 0: 诊断与设计

- **Status:** complete
- 确认 `compose_decision` 被架空，`candidateTier` 驱动所有交易
- 确认 `compose_strategy()` 分层阈值全部硬编码
- 输出 design spec: `quant-board/docs/superpowers/specs/2026-06-05-strategy-decision-wiring-design.md`
- 用户批准 A+B+C 三个方向合并方案
- 创建 planning-with-files 三文件

### Phase 1: RankTrendConfig + compose_strategy 去硬编码

- **Status:** pending

### Phase 2: 策略层接入 finalSignal

- **Status:** pending

### Phase 3: 交易执行器接入 finalSignal

- **Status:** pending

### Phase 4: 测试补齐

- **Status:** pending

### Phase 5: Checkpoint 复跑 + 对比

- **Status:** pending

## 5-Question Reboot Check

| Question | Answer |
| --- | --- |
| Where am I? | 策略信号链路修复项目启动。Phase 0 诊断与设计已完成。 |
| Where am I going? | 实现 A+B+C 三个方向：compose_decision 作主信号、candidateTier 作语境过滤、分层阈值可配置化。 |
| What's the goal? | 用户配置的 MACD/动量参数真正驱动买卖，A_MAIN 分层降级为准入资格，提升 L1 方向精度。 |
| What have I learned? | compose_decision 完整的加权合成逻辑已存在但从未被使用。修复成本低（不改计算内核，只改消费侧）。 |
| What have I done? | 完成代码追踪诊断、输出设计 spec、创建 planning-with-files。 |
