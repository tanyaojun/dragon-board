# 四维信号系统防过拟合审计报告

> 状态：2026-08-19 首版（本轮研究优化后过拟合风险盘点）；A-E 加固逐项落地（见 §6 进度）
> 归档位置：`quant-board/docs/ranktrend-tier-backtest/`

## 1. 审计背景

四维信号系统（实际 synergy 5 维投票 + 3 观察因子 + 4 门控/确认项）经阶段 7-11 及
2026-08-17~19 系列研究优化后，存在过拟合风险。本报告盘点全部因子/参数，按防过拟合
流程逐项检查，并给出加固方案（A-E）。

## 2. 因子清单

### 2.1 synergy 投票 5 维（`compute_synergy_state`，档位 S/A/B/C/D）

| 维度 | 输入因子 | 数据来源 | 状态 |
|---|---|---|---|
| resonance 共振 | direction/acceleration/cross/macd 子分数、Jump 事件、freshness/entryStrength/persistence | 阶段 7 参数化 | 投票 |
| rankTrend 趋势 | momentumProfile（短/中/长/加速度）→ 强/确认档 | 阶段 8 参数化 | 投票 |
| volumePrice 量价 | volumeRatio/量能/资金比/amountRatio（G3 新增） | 阶段 9 + G3 | 投票 |
| lifecycle 生命周期 | 阶段权重 × 动量承诺/能见度/风险 | 阶段 6 重构 | 投票 |
| crossSection 横截面 | percentile 绝对值 + delta（强/中/弱 3 态） | 阶段 10 + G2 | 投票（默认 1.0） |

### 2.2 观察 3 项（不进投票，实证负贡献关闭）

| 因子 | 状态 | 关闭依据 |
|---|---|---|
| priceMomentum 价格动量 | `tierSynergyPriceMomentumVote=0.0` | G1 实证负贡献（−32%） |
| priceRankDivergence 价格-排名背离 | 4 态档位映射（数据驱动）vote=0 | 与排名信息冗余 |
| dv_tier 量名背离 | `tierSynergyDivergenceVote=0.0` | 实证负贡献（−25%） |

### 2.3 门控/确认 4 项

| 项 | 参数 | 依据 |
|---|---|---|
| regime 环境门 | strong 禁 A/B（banStrongA/B=True） | 数据修正（strong 负贡献） |
| Jump 确认 | jumpConfirmChangeMin=3.0 / VolumeRatioMin=1.0 | G4 |
| weak 放开 | regimeGateStrongBan 分支 | 弱市选强（weak B +0.077） |
| retreat 风控禁 | 恒禁 | 风险风控 |

## 3. 参数清单（195 字段，三层）

### L1 自由参数（被数据调过 ≈50，高风险）

- **共振 12**（阶段 7）：resonance* windowBars/scale/weights、jumpDeltaPct=15/jumpResetLookback=3/jumpSustainCount=2
- **核心信号 ~10**（阶段 8）：momentumAccelThreshold、momentumPeriods、tier* 档位阈值
- **量价 7**（阶段 9）：volumePrice*（5 档扫描）
- **横截面 8**（阶段 10）：crossSectionStrongMin=85/MidMin=50/WeakMax=15/delta 阈值
- **本轮 ~15**（G1-G7/方向）：amountRatio 3（Period=5/High=1.5/Low=0.5）、背离 2、regime 门控 3、投票权重 3（cs=1.0/dv=0/pm=0）、jumpConfirm 2

### L2 结构参数（移植/重构定值未扫 ≈60，中风险）

- **cycle* 50 个**（周期识别阈值）——`ba6e301` 生命周期 51 字段参数化"零行为变化"（原硬编码值）
- lifecycle* 12、tier* 阈值 15+

### L3 golden 移植（未动 ≈85，低风险）

momentum/macd 基础 22、ATR 6、decision 10、risk 4、resonance 基础权重等

## 4. 防过拟合流程检查（10 项）

| # | 原则 | 现状 | 评级 |
|---|---|---|---|
| 1 | 自由度 vs 样本 | L1 ~50 自由参数 / 769 帧（81 交易日）≈ 1.6 日/参数 | 🔴 严重 |
| 2 | 样本外纪律 | 7 月股灾排除 ✅、8 月独立复核 ✅ | 🟡 |
| 3 | 8 月窗口纯净性 | **8 月已反复用于 G1-G7 + 方向 A/B/C 决策**——已从验证集变调参集 | 🔴 最实质 |
| 4 | 多档位扫描单调性 | 阶段 7/8/9 5 档扫描 + 峰值稳定性 ✅ | 🟢 |
| 5 | 翻案记录 | 9.4→9.5 明确作废 ✅ | 🟢 |
| 6 | walk-forward 滚动 | 仅单次 train=537/validation=232 切分 | 🟡 未滚动 |
| 7 | 不写回默认值 | 参数研究只产报告（用户决策）✅ | 🟢 |
| 8 | 机理合理性 | 每因子有语义 ✅ | 🟢 |
| 9 | 小样本决策 | A 档 n=264/466 做过档位映射与双强观察（未落地） | 🟡 |
| 10 | 阈值扫描完整性 | **amountRatio 3 参数未扫描直接定值** | 🟡 |

## 5. 核心结论

1. **最大风险是 8 月窗口污染**——同一窗口既调参又验证，最可信独立证据已消耗。
2. 自由参数 50 个/81 日确实过参数化，但多数决策是"关闭"（vote=0）——保守方向，风险低于预期。
3. **cycle 50 阈值无调参记录**——自由度假象（未验证也未优化），属"未审计区"。
4. **amountRatio 阈值未扫描**直接定值 1.5/0.5——唯一未扫新参数。

## 6. 加固方案（A-E，逐项落地）

| 项 | 内容 | 状态 |
|---|---|---|
| A | 8 月冻结为最终验证集——参数决策禁用 8 月数据 | ☐ |
| B | 滚动 walk-forward：4-5 月 train / 6 月 val / 7 月 test | ☐ |
| C | amountRatio 3 参数 5 档扫描（冻结前窗口） | ☐ |
| D | cycle 50 阈值审计：区分结构定义 vs 可调参数 | ☐ |
| E | L1 参数定值档案（commit/数据窗口/样本外状态） | ☐ |

## 7. 定值档案（E 落地后填充）

见 §7 附表（`ranktrend-l1-param-ledger.md`）。
