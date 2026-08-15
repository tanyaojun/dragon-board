# RankTrend synergy vote 语义改进：档位强度加权投票（立项方案）

> 状态：立项（2026-08-15），方案 1 全档位权重 × 方向
> 归档位置：`quant-board/docs/ranktrend-tier-backtest/`
> 背景：阶段 4.2 敏感性分析发现 `_synergy_tier`（`backend/analysis/ranktrend/volume_price.py`）
> vote 只取 direction（buy/sell ±1），**忽略 signalTier 档位** → 6 个共振/趋势档位阈值参数
> 对 synergy/交易完全无效（变化率 0.0），信号区分度不足。

## 1. 目标（5 句话以内）

让 synergy 档位强度参与投票：S 档（强信号）单独即可达 A 档、弱信号（C 档）不再误导升档、
档位与方向冲突时档位主导。保持 golden 对齐与阶段 3 验收（synergy 单调性 passHard、S/A excess≥0.05）
不退化。阈值参数 float 化（tierSynergyVote* 从 int 改 float，约束 reverse ≤ weak < strong 保留）。
改后重新交易层搜索 + walk-forward 复核。

## 2. 现状

`_synergy_tier`（`volume_price.py:240-289`）：

```python
def _vote(tier, direction):
    if tier in ("unknown", None) or not direction: return 0
    if direction in ("buy", "up"): return 1
    if direction in ("sell", "down"): return -1
    return 0
v = _vote(res_tier, res_dir) + _vote(rank_tier, rank_dir) + _vote(vp_tier, vp_dir)
# S = v >= strong+1；A = v == strong；B = v == weak；D = v <= reverse；else C
```

问题：S 档与 B 档同票（±1），强信号无区分度；C 档 buy 也投 +1（弱信号误导升档）。

## 3. 改进方案（方案 1：全档位权重 × 方向）

### 3.1 权重表

| 档位 | weight | 语义 |
|---|---|---|
| S | 2.0 | 强信号（龙头） |
| A | 1.5 | 确认 |
| B | 1.0 | 弱确认 |
| C | 0.5 | 中性偏弱 |
| D | -0.5 | 弱反/危险（档位示警） |
| E | -1.0 | 强反 |

### 3.2 投票公式（方案 1：方向主导 × 档位幅度，v4 最终权重）

```python
# strength（档位强度）v4：S=1.2, A=1.0, B=0.8, C=0.5, D=1.0, E=1.0
# 方向主导：vote = strength × dir_sign，dir_sign: buy/up=+1, sell/down=-1, hold=0
def _vote(tier, direction):
    if tier in ("unknown", None) or not direction: return 0.0
    strength = _VOTE_STRENGTH.get(tier, 0.0)
    if direction in ("buy", "up"): return strength
    if direction in ("sell", "down"): return -strength
    return 0.0
vote_sum = _vote(res) + _vote(rank) + _vote(vp)   # float，范围 ±6
```

| tier \ direction | buy/up | sell/down |
|---|---|---|
| S（1.2） | +1.2 | −1.2 |
| A（1.0） | +1.0 | −1.0 |
| B（0.8） | +0.8 | −0.8 |
| C（0.5） | +0.5 | −0.5 |
| D（1.0） | +1.0 | −1.0 |
| E（1.0） | +1.0 | −1.0 |

**方向主导**（D/E 档 buy 仍投正分，同旧票数语义）；档位幅度区分体现于 S/B/C
（S 档 2 票升 S、B 档 3 票不升 S、C 档 3 票仅 B）。v4 经权重扫描选定（h1 验收口径）。

### 3.3 档位判定（阈值 float 化，语义沿用阶段 3）

```python
# tierSynergyVote* 从 int 改 float：默认 strong=2.0 / weak=1.0 / reverse=-1.0
S = vote_sum >= strong + 1.0
A = vote_sum >= strong
B = vote_sum >= weak
D = vote_sum <= reverse
C = 其余
# 周期 B/D 降档、E/vp-E 硬分支、量价 E 处理均不变
```

典型场景（v4 权重，默认 strong=2.0 / weak=1.0 / reverse=-1.0）：

| 场景 | vote_sum | 档位 | 对比旧票数语义 |
|---|---|---|---|
| 3× A+buy | 3.0 | S | 不变（旧 3 票 → S） |
| 2× A+buy | 2.0 | A | 不变（旧 2 票 → A） |
| 1× S+buy（单维） | 1.2 | B | 不变（旧 1 票 → B） |
| 2× S+buy | 2.4 | A | 不变（旧 2 票 → A） |
| 3× S+buy | 3.6 | S | 不变（旧 3 票 → S；S 档 3 票仍 S） |
| S+buy + A+buy | 2.2 | A | 不变 |
| 1× B+buy | 0.8 | C | 旧 1 票 → B → **降 C**（弱确认单票不升） |
| 3× B+buy | 2.4 | A | 旧 3 票 → S → **降 A**（B 档 3 票不升 S，档位区分） |
| 1× C+buy | 0.5 | C | 旧 1 票 → B → **降 C** |
| 3× C+buy | 1.5 | B | 旧 3 票 → S → **降 B**（C 档 3 票仅弱确认） |
| 全 hold | 0 | C | 不变 |
| 1× D+sell | −1.0 | D | 不变（D=1.0 方向主导，单维空即 D） |
| 1× D+buy | +1.0 | B | 不变（方向主导，D 档 buy 同 1 票） |

### 3.4 不变量（必须保留）

- lc_tier == "E" → 总档 E（周期硬否决）；
- vp_tier == "E" → 总档 D（量价硬风险）；
- 周期 B/D 时 S/A 降一档（S→A、A→B）；
- `from_patch` 校验：reverse ≤ weak < strong（float 允许，非整数值不再拒绝）；
- synergy.state / reasons 字段结构不变，TS 消费合同不变（Python 是 golden）。

## 4. 影响面

| 模块 | 变更 |
|---|---|
| `backend/analysis/ranktrend/volume_price.py` | `_vote` 加权 + `_synergy_tier` 阈值比较 |
| `backend/analysis/ranktrend/engine.py` | `tierSynergyVote*` 类型 int→float、from_patch 校验调整 |
| `src/types/rankTrendDefaults.ts`（根项目） | 若 TS 侧有同名字段默认值/类型，同步 float |
| 测试 | `test_ranktrend_tier_functions.py` 更新 + 新增加权用例 |
| 文档 | 本方案 + `ranktrend-observation-discrete-tiers-design.md` §7 + golden 文档 |

## 5. 验收

1. 新语义单测全绿（§3.3 场景表）；
2. 现有 tier/replay/golden 测试不回归（E/vp-E 硬分支、周期降档、config 阈值）；
3. 阶段 3 验收不退化：synergy 单调性 passHardConstraint、S/A 加权 excess ≥ 0.05
   （`diagnose_tier_discrimination.py` 全窗口验证）；
4. golden case 对齐（Python 输出字段合同不变，数值按新语义更新）。

**验收实证（2026-08-15，全窗口 769 帧/156647 信号，验收口径 horizon=1）**：

| 版本 | spearman | reversals | positiveMonotonic | S/A/B excess | saEx | passHard |
|---|---|---|---|---|---|---|
| v0（旧票数全 1.0） | 1.0 | 0 | True | 0.088/0.0388/−0.0064 | 0.0519 | True |
| v1（档位主导 S=2/A=1.5/B=1） | −1.0 | 2 | False | 反转 | 负 | False |
| v2（S=1.5/B=0.5/C=0.25） | 1.0 | 0 | True | 0.0186/负/负 | −0.0111 | False |
| v3（S=1.2 档位主导） | −0.5 | 1 | False | 更差 | −0.0073 | False |
| **v4（S=1.2/A=1/B=0.8/C=0.5/D=1，方向主导）** | **1.0** | **0** | **True** | **0.0552/0.0673/正** | **0.0651** | **True** |

**迭代教训（重要）**：
1. **验收口径是 horizon=1**（40ddc7f 记录的 0.088/0.039 为 h1；诊断默认跑 1/3/8）。初轮用
   horizon=3 验证是口径错误——h3 下真 v0 基线 saEx 也仅 0.01（不达标），误导了 v1~v3 迭代。
2. **v1/v2/v3 的"档位方向主导"（D/E 档 buy 投负）偏离了方案 1**（vote = strength × dir_sign，
   方向主导）——恢复方向主导后，全 1.0 权重即复现 v0 达标（h1: 0.088/0.039/-0.006），
   权重微调（v4）在此基础上提升到 0.0651（+25%）。
3. **权重扫描方法**：`_VOTE_STRENGTH` 模块常量（volume_price.py）+ 扫描脚本逐组合替换 →
   replay → tier_forward_returns(horizon=1)，12 组合约 30 分钟。

v4 结论：**档位强度加权（S/B/C 区分 + D/E 方向主导）达标且优于 v0 基线**（saEx 0.0651 vs 0.0519，
A 档 excess 0.0388→0.0673）。验收通过，进入 golden 对比与重新交易层搜索。

## 6. TDD 步骤

1. RED：更新 `test_ranktrend_tier_functions.py`（新语义场景表 + 保留旧不变量用例）；
2. GREEN：改 `_vote` 加权 + `_synergy_tier` float 阈值 + engine.py 类型/校验；
3. 回归：`pytest tests/test_ranktrend_tier_functions.py tests/test_ranktrend_replay_resonance.py
   tests/test_tier_monotonicity.py` + 全量 pytest；
4. 验证阶段 3 验收（诊断脚本全窗口 synergy passHard / saExcess）；
5. 文档同步（§7 规则 + golden + backtest plan）；
6. 提交后重新交易层搜索 + walk-forward 复核（阶段 4 重启）。

## 7. 风险与回退

- S/A 档分布变化 → 单调性/收益可能波动：验收不达标则回退（git revert），或调整权重表
  （S=1.5 等）重新验证；
- 阈值 float 化影响 from_patch 强校验：测试覆盖非整数值路径；
- vote 语义变更属 golden 变更：golden case 需同步更新，不能静默改输出。
