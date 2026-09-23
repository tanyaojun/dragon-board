# 批次 2 判定卡 + 阶段 A 收口汇总（8 参数族全扫描）

> 2026-09-23。批次 2 数据：`exit-scan-batch2-metrics.tsv` / `-reason-buckets.tsv` /
> `-window-buckets.tsv`；批次 1 见 `exit-scan-batch1-verdict.md`。
> 全部 16 trial http_200；基线校验锚全程通过；窗口口径同批次 1
> （decision 04-15~07-31 / FINAL 冻结只报告 / oos1 08-15~08-31 / oos2 09-01~09-30）。

## 批次 2 五族判定

### breakevenTrailing + threshold（默认 off）→ **PASS_CANDIDATE（批次 2 最佳）**

| 档位 | 全窗 wrxpf | ret | maxDD | decision | oos1 | oos2 |
| --- | --- | --- | --- | --- | --- | --- |
| 0.02 | 0.5881 | +8.54% | -7.04% | 1.5171（≡基线） | 0.0127 | 0.3455 |
| 0.04 | 0.5638 | +7.83% | -7.57% | 1.5171（≡基线） | 0（≡基线） | 0.3643 |
| 0.06 | 0.5672 | +8.24% | -7.98% | 1.5171（≡基线） | 0（≡基线） | 0.6304 |

- 三档全面优于基线（0.4824 / +6.46% / -8.46%）且**平缓无尖峰**——批次 2 形态最稳。
- 机理（reason 分桶）：保本线触发后以"盘中止损"名义在保本价离场——盘中止损片段
  12→22 笔但均亏 -0.053→-0.030（大亏单提前变保本小亏）；"生命周期B反对"片段 5→2。
- 与批次 1 takeProfit 同模式：decision 窗零变化，改善全部来自 8 月中后 oos。

### useAtrStops + atrStopMultiplier（默认 off）→ **REJECT（负贡献 + 档位不活跃）**

- 1.5 档 0.5222 唯一略优于基线，但 ret +5.73% / maxDD -9.09% 均劣于基线；
- **2.0/2.5/3.0 三档逐位完全相同**（0.5022）：multiplier≥2 后 ATR 线恒低于固定 -5% 线，
  从未成为生效退出线——ATR 仅通过 intrabar 盘中线接线到 v3 锚（`_intrabar_exit_trigger`），
  宽松档位下被固定线覆盖。

### weakStateExit / signalExitDelayBars / minHoldingBars → 对 v3 锚零影响（两类死因）

- 三族 × 所有档位与基线**逐位完全一致**（minHoldingBars 4 档 pf 仅差 0.0001）。
- **未接线类（weakStateExit / signalExitDelayBars）**：消费点全在对照组 else 分支
  （execution.py:172-183 / 192-194）；v3 锚走专属退出决策
  `_ranktrend_early_big_move_v2_exit_decision`（execution.py:1006，仅 5 条规则：
  热榜缺失3bar / 止损 / 生命周期B反对且未盈利 / 排名大幅下降+MACD死叉 / 最大持有），
  不经过这些代码路径。且语义前提也不成立：weakStateExit 的作用是"替换
  D_EXIT_RISK 档位退出为弱势退出"，而 v3 专属决策里没有 D_EXIT_RISK 规则可替换；
  signalExitDelayBars 抑制的 signal_exit 集合（D_EXIT_RISK/final sell/C_CROWDED/
  排名恶化/synergy）在 v3 专属决策里同样不存在。
- **冗余档位类（minHoldingBars）**：该参数消费点在策略分叉**之前**
  （execution.py:128-130），对 v3 是接线的；无感原因是档位被 T+1 + 实际持仓
  分布掩护——基线 51 片段最短 holdingBars=3（half_hour 下 T+1 禁当日卖出，
  最短持仓天然 ≥3），minHoldingBars=1/2 完全冗余、=4 仅推迟那 1 笔最短片段
  （pf 差 0.0001 与此吻合）。
- 结论：weakStateExit / signalExitDelayBars 若要在 v3 锚上启用，需 B 阶段先把
  v3 专属退出决策接上这些机制（且 weakStateExit 的 zljzb 口径归属仍待确认）；
  minHoldingBars 已接线但 half_hour+T+1 下档位需 >3 才有意义。zljzb 口径问题
  降级为次要。

## 阶段 A 收口：Top3 卖点候选（按效应量排序，待用户决策）

| # | 候选 | 全窗 wrxpf | ret | maxDD | 形态 | 主要风险 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | takeProfit 0.06 | **0.9348** | +12.83% | **-4.72%** | 单调（0.06>0.09>关） | 改善全在 8 月中后 oos；decision 窗零参与 |
| 2 | maxHoldingBars 16 | 0.6473 | +7.04% | **-4.48%** | 全表最强单调（16>24>30>40>56） | 入场混合效应（rts 43→45） |
| 3 | breakeven 0.02 | 0.5881 | +8.54% | -7.04% | 三档平缓无尖峰 | 同 tp：oos 驱动 |

- **共同警示（三次独立复现）**：全部有效档在 decision 窗（4-7 月）与基线逐位相同，
  改善 100% 来自 8 月中旬后样本外——v3 默认参数是平衡市形态，8-9 月冲高回落市
  才激活保护线。落默认前应接受"平衡市零成本、高波动市保护"定位。
- 43 笔全窗过 30 笔门槛；按窗全部 n<30（insufficient 披露）。
- **扫描不自动写回默认**（纪律）；一次一候选。

## 死参数/REJECT 清单（避免后续浪费算力）

stopLoss（非单调）、useAtrStops（负贡献+档位不活跃）、weakStateExit /
signalExitDelayBars / minHoldingBars（未接线 v3，零影响）。

## B 阶段建议（A 结果归因 → 用户裁决批次内容）

- **B1 trailing stop 证据链完整（三重）**：① tp0.06 效应量最大=兑现机制有效；
  ② be 三档平缓=浮盈保护有效；③ 最大持有桶 65% 胜率=浮盈普遍存在但无兑现路径。
  trailing stop（峰值回撤兑现）是 tp+be 的统一动态形式，B1 优先级确认。
- **B2 断板卖出前提已核实**：`TradeSimulator._quote()`（execution.py:1038-1055）
  已消费 limitUpPrice/fengdan，signal 组装侧原料就绪；但归因证据弱于 B1
  （信号类退出桶合计仅 7/51 片段小亏）。
- 建议批次 3 组合验证（各 ~40 分钟）：tp0.06 × be0.02、tp0.06 × be0.02 × mh16。
