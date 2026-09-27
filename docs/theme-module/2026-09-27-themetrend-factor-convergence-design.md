# ThemeTrend 因子口径收敛设计（联动/持续进因子 · 先验通道取舍 · 动量 v2 入回测链）

- 日期：2026-09-27
- 状态：三方向已获用户确认（2026-09-27）；**本批实施完成**（TaskA v2 存储接线+回填 54 研究日、TaskB 边际研究 runner+findings、TaskC 双源登记，2026-09-27）；参数裁决全部归 Phase 4 三窗终判。findings：`2026-09-27-factor-marginal-findings.md`
- 关联：`2026-09-26-themetrend-v12-upgrade-design.md`（§5 分层架构）、`plans/task_plan_phase4.md`、`skills/single-source-of-truth/SKILL.md`
- 定位：不推翻 v12 信号合同与既有结论；一切新权重/新口径先研究验证、参数默认 0/关接线、一次一候选落默认

## 1. 事实基础（2026-09-27 代码查实）

1. **两套体系不在同一决策点**：rotation 四组因子 → rotationScore → rotationState 六值 → candidateTier → TradeSimulator 进出场 → PnL（唯一交易驱动）；v12 六因子合成分（`trend.py:676`）只落题材级 signal rows 的 score/confidence/themeSupportScore（归因展示通道），不进交易路径（个股执行信号 confidence=暴露分，仓位不消费 confidence）。故第 2 项不是"二选一"，重构为：**数值先验通道归属** + **原料重复计算收敛**两个可裁决问题。
2. **联动度/持续性现行算法**（`heat.py:104,193`）：correlationScore = max(#涨,#跌)/#非零×100（零参数，仅捕捉同向不捕捉幅度联动）；persistenceScore = min(连续热门桶数×20, 100)（乘数 20/封顶 100）。两者自 7-06 起 100% 落库。
3. **rotationScore 未历史落库**：仅存在于 frames rotationSummary.mainLines（引擎主线日，8 天非空）；历史逐题材回放需引擎逐槽回放（保护核心，本批不做）。
4. **动量 v2**：`compute_theme_momentum_v2` 纯函数（rps d5/d10/d20、near_high、window_momentum、breadth、flow_volume、crowding 惩罚 + intraday 辅口径；维度缺失 None + reason，可用维度 <3 不产分）；生产消费仅 `theme_momentum_routes`（面板）。序列构建 `build_daily_series`（自带收盘槽选择 15:00+ / 11:30-13:00 回退）。
5. **数据口径**：daily 类型 sector rows = 245 题材 × 每日收盘槽一行（15:30 为主，7 月上旬 11 日仅 15:00）；amountRatio 恒缺失 → v2 的 flow_volume 在日线源上不可用（预期行为，fail-visible）。

## 2. 方案

### 2.1 第 1 项：联动度/持续性进策略因子（先研究、默认 0 接线）

- 区分度研究：T+1 change 五分位 + IC + **边际 IC**（对 v12 六维合成分残差化，rank 回归残差法）——进合成的唯一理由是增量信息，裁决标准与 Phase 3（D2/D3/F1）一致。
- 持续性算子二选一同面板裁决：persistenceScore（槽位霸榜连续）vs D3 top_membership_streak（日线动量 Top 分位连续，`factor_series.py`）——防止未来双持续性因子重复计分。
- 联动度备选口径同面板对照：现行方向一致性 vs 幅度联动（成员收益横截面相关/相对全池 beta），数据同为 quote changes。
- 接线形态（过验后 Phase 4 裁决数值）：`ThemeTrendConfig` 新增 `correlationScoreWeight`/`persistenceScoreWeight` **默认 0.0**；合成式归一化语义（重新归一 vs 允许和>1）在接线时定版，防分数量纲漂移。

### 2.2 第 2 项：先验通道取舍 + 原料单源收敛

- 数值先验通道 ablation：候选 = v12 六维合成分 / 动量 v2 score（/rotationScore 待引擎回放后补），同面板测区分度与边际贡献；胜者占据 score/confidence/themeSupportScore 通道，败者降级诊断字段。**消费侧改动，不动 rotation 引擎核心**；若 v12 合成分胜出不构成改 rotationState 判定的理由。
- 原料单源收敛：breadth/crowding/fund 在 heat.py（瞬时）与 rotation/factors.py（robust-z）双管线各算一遍——登记进 `docs/single-source-of-truth-architecture.md` 盘点表；权威侧=引擎（与 §5.3/§5.5 裁决一致），heat.py 侧保留兼容展示、退役路径随 Phase 4 裁决定。
- rotationScore 历史回放（引擎逐槽 replay harness）登记为 Phase 4 前置任务，不阻塞本批。

### 2.3 第 3 项：动量 v2 接入回测链（三步，复用 theme_daily_factors 基建）

1. **存储接线（本批实施）**：`daily_factors_service` 同一调度同一集合，factors 字典新增 `momentumV2` 子结构（score/direction/rps/nearHigh/windowMomentum/breadth/flowVolume/crowdingPenalty/qualityFlags）；序列源 = daily 类型 sector rows（245 题材全覆盖，面板 half_hour 源仅 Top~60）；逐目标日截断序列调用纯函数；v2-only 题材产行（拥挤字段 None + 标记）。回填全历史。
2. **研究（本批实施）**：v2 综合分 + 子维度进区分度面板（与 2.1 同一 runner），基准 = 现行槽位 momentumScore。
3. **消费接线（默认关，Phase 4 终判）**：过验后经 theme_daily_factors join 进信号合成层；形态二选一留终判——合成分新维度（权重默认 0）或槽位 momentumScore 替换候选（一次一候选单独裁决）。

## 3. 本批实施范围

| 项 | 内容 | 产出 |
|---|---|---|
| A | v2 存储接线 + 全历史回填（factors_daily 装配 + 服务合并写） | theme_daily_factors 含 momentumV2 |
| B | 边际 IC 帮手（rank_ic 扩展，TDD）+ 区分度研究 runner（联动/持续/D3 对照/v2 六维/先验两方 ablation） | 报告 JSON + findings 文档 |
| C | 双源盘点表补登（breadth/crowding/fund 双管线）+ rotationScore 回放登记 | 盘点表更新 |

## 4. 验证

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_daily_factors.py tests/test_rank_ic_marginal.py
.\.venv\Scripts\python.exe -m backend.operations.diagnose_theme_factor_marginal   # 只读 runner，非交易时段
```

## 5. 非目标

- 不动 rotation v2 引擎核心与 mainline 判定；不改 v12 既有六维权重默认值；不落任何新默认（全部归 Phase 4 一次一候选）；
- 不做 rotationScore 引擎回放 harness（登记 Phase 4 前置）；
- 不改前端面板消费路径（v2 面板口径不动）。
