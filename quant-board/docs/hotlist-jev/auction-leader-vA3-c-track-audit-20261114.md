# vA3 C 轨道条款审计（2026-11-14，B 轨道 60 日基率复校后触发）

> 性质：条款审计轮（C 轨道）。结论：**条款零改动、无 vA3.1 换代必要**——三项审计
> 全部「维持现状」，候选议题全部被 60 日证据或题面现状消解。本文档同时固化
> vA3 运行期判别力基线（供周一实跑后首日样本对照）。
> 依据：`auction-leader-vA3-base-rate-60d-evaluation-20261114.md`（B 轨道）、
> `scripts/auction_trial_base_rate_eval.py`、供给-引用对齐回归测试
> （`test_auction_trial_line.py::test_vA3_c_audit_trial_supply_alignment`）。

## 1. 审计一：叙事字段引用审计（删 token 候选）

试盘行 9 个渲染字段（start/end、试盘涨幅、竞价成交、换手、首开/首加/最大/最终）
**全部有判据引用**：封板题引 7 项、形态题 instructions 供给清单显式声明全 9 项
（含「首加额/最大额/最终额、竞价成交/换手」）。当初候选 `jj_turnover` 被两题引用；
`circulated_value`/`price`/`bk_name`/`percent` 本就不渲染（raw 日档全量自持）。

**结论：无删减候选，试盘行 token 成本（约 60–100 字/行）维持。**

## 2. 审计二：试盘负涨幅阈值稳定性（判据锚 0 边界）

可撤窗 end 时点涨幅分桶封板率（60 日 PRESEAL，n=4452 全体 / PRESEAL 子集）：

| 分桶 | 封板率 |
|---|---|
| 负涨幅 | **6%** |
| 0–10% | 10% |
| 10–25% | 10% |
| 25–50% | 27% |
| ≥50% | 49% |

0 边界是自然低谷边界（负 6% vs 邻桶 10%），50% 强度阈值同样有支持（27%→49%
跳变）。**结论：试盘负涨幅负证据（cancel_weak 档）阈值不调。**

## 3. 审计三：五档档序与题面偏置（cancel_strong × no_cancel_settle 合读）

60 日判别力矩阵（PRESEAL，vA3 运行期基线）：

| 档 | n | 封板率 |
|---|---|---|
| hard_oneword | 304 | 78% |
| cancel_strong | 195 | 49% |
| no_cancel_settle | 300 | 43% |
| cancel_neutral | 749 | 16% |
| cancel_weak | 543 | 6% |

（口径修订后数字，见 base-rate-60d-evaluation §尾修订记；修订前 77/48/43/16/5。）

- 档间区分度显著（首尾 72pp），裁决②（cancel_neutral/strong 保留分档）获
  33pp 直接支持；
- 新观察：cancel_strong (49%) ≥ no_cancel_settle (43%)——已核对题面，五档描述
  **完全中性、无档位优劣排序**（no_cancel_settle 定义「试盘涨幅未顶死或试盘有
  反复」，cancel_strong 定义「撤单+高强度」，无强弱措辞）→ 判据无需微调；
  该观察记入本基线，供周一实跑答案分布对照。

**结论：无 vA3.1 候选条款，vA3 hash 不变。**

## 4. 固化与后续

- 供给-引用对齐回归测试已入 `test_auction_trial_line.py`（9 字段渲染⊆形态题
  供给清单 + **结局字段防 look-ahead 泄漏**：percent/收盘/流通市值/现价/板块
  禁入试盘行叙事——天普 11-12 池漏档同级防线）；
- 周一 11-16 实跑后：vA3 首日样本量 ≥10 只目标不变；答案五档分布与本基线
  （77/48/43/16/5%）对照，偏离 >20pp 或某档 n=0 时触发重评（红线 6 归因顺序）；
- 60 日新校准数已入题面卫生黑名单（`test_narrative_hygiene`）。
