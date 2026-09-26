# ThemeTrend v12.5 升级设计（方向性方案）

- 日期：2026-09-26
- 状态：设计已确认，未实施（本轮仅调研与方案，不改代码、不跑回测）
- 定位：升级现有 `theme-trend-v12` 回测骨架，补业界因子与真实数据结论存档；不推翻既有回测结论
- 关联文档：
  - `docs/theme-module/README.md`（V1→V12 演进总纲）
  - `docs/theme-module/plans/task_plan_v12.md`（v12 默认参数合同）
  - `quant-board/docs/theme-rotation/2026-08-04-theme-rotation-engine-design.md`（轮动引擎现行口径）
  - `quant-board/docs/theme-rotation/2026-08-06-theme-momentum-redesign.md`（动量 v2 现行口径）
  - `quant-board/docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md`（heatLevel 相对分口径；已声明旧题材回测数字不可沿用）

## 1. 背景与现状结论

2026-09-26 对 `quant-board` 题材域做了全量盘点，并调研了国内外板块轮动量化因子。核心结论：

1. **ThemeTrend（theme-trend-v12）不是雏形，是全链可运行但无真实数据结论的引擎**：
   - 算法层 `quant-board/backend/analysis/theme/`（约 4100 行）+ 服务层 `backend/services/theme/`（约 2650 行）+ 4 个题材 API 路由 + 回测/优化/报告/CLI 已闭环；
   - `ThemeTrendPythonEngine.replay_sequence`（`analysis/theme/trend.py`，strategyVersion=theme-trend-v12）→ `_theme_execution_signals`（`services/backtest_service.py:717,1243`）→ TradeSimulator → 优化器（CLI `run-theme-trend`/`optimize-theme-trend`）→ 报告端点，全链可运行；
   - 已进回测的题材策略 3 个：`theme_rotation` / `leader_theme_confirmation` / `hotlist_theme_confluence`（`core/backtest/strategy.py:96-118`）。
2. **真正的缺口在验证与因子质量，不在框架**：
   - 题材动量 v2（`compute_theme_momentum_v2`，日线六维）未进回测链，只供面板与 RankTrend 观察舱消费；
   - 题材域没有成册的真实数据回测结论存档（RankTrend 域有 `exit-scan-batch*-verdict.md`，题材域唯一回流代码的参数是 exit-scan-batch3 止损止盈）；
   - heatLevel 迁移（2026-09-03）后旧题材回测数字不可直接沿用，文档已自我声明需重跑；
   - 优化器以 grid/random 为主，bayesian/tpe 未接入（另立任务，见非目标）。

## 2. 业界因子调研摘要

### 2.1 国内券商金工主流框架

行业轮动模型收敛为**景气度、动量、资金流、拥挤度**四大类：

- 中信建投金融工程 2026 年投资展望：因子动量思想 + 宏观/基本面/资金面/事件动量子维度，2019 年以来年化超额 28.8%、月度胜率 73%（https://finance.sina.com.cn 相关报道）。
- 国盛证券《行业轮动的三个标尺——因子投资 2020（四）》：景气度/动量/拥挤度三因子基本不相关，动量与拥挤度信号呈明显负相关（https://www.sohu.com 国盛量化系列）。
- 拥挤度典型构建（国盛/中信建投口径）：

  ```text
  换手率分位数 = Rank(行业当日换手率 / 过去一年日换手率序列)
  拥挤度 = 等权( 换手率分位数, 波动率分位数, Beta比率 [, 成交额占比分位数] )
  ```

  拥挤度为负向因子：高动量 + 高拥挤 → 泡沫破灭风险；"换手率分位数 >99%"是典型微观拥挤预警阈值。

### 2.2 A 股动量特殊性（决定因子改造方向）

- A 股个股短期（1 个月内）反转效应显著，纯动量弱；行业动量有效性依赖市场"变盘状态"——银河金工"变盘指数"研究：变盘指数下行时动量策略占优、反转策略显著不利，20 日均线口径下结论最清晰（https://www.sohu.com 银河金工）。
- 华泰金工行业轮动系列：普通动量样本外表现不佳，需引入风险调整动量（夏普动量）与动量连续性因子增强（https://www.scribd.com 华泰金工行业轮动 4）。

### 2.3 海外学术与实战

- 行业动量学术根基：Moskowitz & Grinblatt《Do Industries Explain Momentum?》（Journal of Finance, 1999）——行业动量收益大部分来自行业特质成分而非共同风险因子，是独立收益来源（https://www.aqr.com/Insights/Research/Journal-Article/Do-Industries-Explain-Momentum）。
- Arnott, Clements, Kalesnik & Linnainmaa《Factor Momentum》：因子动量与行业动量打通，动量的动量可用于因子开关择时（https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2018/03/Juhani.pdf）。
- 实战工具 RRG（相对旋转图，StockCharts/Optuma）：板块按「相对强度比值 × 该比值的动量」投影到 Leading→Weakening→Lagging→Improving 四象限（https://articles.stockcharts.com）。

### 2.4 国内实战派（游资/情绪周期视角，非学术来源）

情绪周期量化指标体系（东方财富财富号、复盘社区共识）：涨停家数、连板高度（最高板）、炸板率、晋级率（一进二成功率）、连板梯队结构、成交额、板块轮动速度、龙头辨识度，对应情绪六阶段「启动→发酵→高潮→退潮→冰点→回暖」。

**与本项目数据的对齐**：这套指标的数据链已全部在采集（limitSummary 涨停池、热榜八平台、KPL 人气、题材映射）；`market_phase` 六态（ice/rising/climax/cooling/chaos/neutral）与实战派情绪六阶段基本同构。这是本项目区别于公开研报的独有数据优势。

## 3. 差距分析（现有实现 vs 业界可引入因子）

按"数据是否已在采集"排优先级：

### P0 —— 数据已有，可直接计算

| 候选因子 | 业界口径 | 现状差距 |
|---|---|---|
| 拥挤度业界标准口径 | 换手率/波动率/成交额一年分位数等权合成，负向因子 | 现有 crowding 只是 v2 动量惩罚项（≥60 起扣、封顶 15）+ rotation 权重 0.16，无分位数历史基线口径 |
| 风险调整动量（夏普动量） | 收益/波动，替代原始涨幅 | v2 六维全是原始 RPS/涨幅，无风险调整 |
| 动量连续性 | 动量排序持续性过滤 | v1 有 persistenceScore，v2 六维无 |
| 情绪周期条件层 | 变盘/情绪状态决定动量 vs 反转切换 | `market_phase` 已有但未作为题材因子条件变量；与既有"市场状态依赖"复现结论直接呼应 |

### P1 —— 需少量新增计算

| 候选因子 | 说明 |
|---|---|
| 炸板率/晋级率/连板梯队结构 | limitSummary 有涨停池明细，缺衍生算子；散户情绪数据中最独特的 alpha 源 |
| 板块资金流持续性 | fund_cache 双源资金已有，缺"净流入持续天数/排名变化"算子 |
| RRG 式四象限投影 | `daily_series.virtual_index` 已能合成题材虚拟指数，算 RS ratio + 动量即得象限；与现有 rotationState 四标签结构相似、口径互补 |

### P2 —— 研究项，暂缓

- 事件动量/政策催化（题材 reason 字段有原料但噪声大）；
- 景气度/基本面（月度行业配置玩法，与短线题材域不匹配）。

## 4. 设计原则（四条硬约束）

1. **不动 v12 信号合同与既有结论**：新因子全部"先研究验证、后接线"；验证不通过则机制保留、默认关闭（沿用 RankTrend 域"负贡献因子 vote=0 关闭观察"范式）。
2. **fail-visible**：任何新因子在数据缺失/历史不足/低样本时降级为显式质量标记（`insufficient`/`missing_source`），不伪造 0 或中性值，不阻断其它因子与主链（遵循 `skills/fail-visible-data-pipelines/SKILL.md`）。
3. **单一事实源**：所有因子计算在 quant-board 后端，前端只消费展示；本设计纯后端新增，不产生双源（遵循 `skills/single-source-of-truth/SKILL.md`）。
4. **一次一候选落默认**：逐因子过验证才逐个启用，不打包上线（沿用 `skills/ranktrend-signal-research/SKILL.md` 纪律）。

## 5. 三层因子架构

架构选型结论：**时间尺度分层**（用户 2026-09-26 确认）。否决扁平接入（日线因子塞进槽位级合成会因同日 48 槽共享同值产生严重自相关，回测有效样本数虚高）；吸收"门控先行"的验证顺序（情绪相位门控第一个验证）。

```text
┌─ 慢层（日线因子）─────────────────────────────┐
│ D1 拥挤度一年分位数 / D2 风险调整动量(夏普动量)  │
│ D3 动量连续性 / D4 RRG 四象限投影               │
│ 数据源：sector rows 日频历史 + virtual_index    │
│ 频率：每交易日一次，派生落库 + Redis 缓存        │
└──────────────┬────────────────────────────────┘
┌─ 快层（槽位因子）─────────────────────────────┐
│ 现有 rotation 四组因子（不动）                  │
│ + F1 资金流持续性（新增算子）                    │
│ 频率：每快照槽位（现状不变）                     │
└──────────────┬────────────────────────────────┘
┌─ 条件层（情绪门控）───────────────────────────┐
│ S1 炸板率 / S2 晋级率 / S3 连板高度与梯队        │
│ （数据可得性待 Phase 0 确认）                   │
│ market_phase × 情绪指标 → 调节快层因子权重与      │
│ 信号可信度标签；不做硬门禁（fail-visible）        │
└──────────────────────────────────────────────┘
```

### 5.1 慢层因子口径

| 因子 | 口径 | 数据源（已在采集） |
|---|---|---|
| D1 拥挤度分位数 | 优先：题材成交额占全市场比重的过去一年分位数（数据链最短）；次之：题材换手率分位数（需流通市值，Phase 0 确认可得性）；等权合成，负向因子 | sector rows 日频聚合 + 腾讯行情 |
| D2 风险调整动量 | `virtual_index` 虚拟指数上算 20/60 日夏普动量（均值/波动），替代原始涨幅排名 | `daily_series.py` 已有 |
| D3 动量连续性 | 连续 N 日维持 RPS Top 分位的持续性计数 | 动量 v2 日线序列已有 |
| D4 RRG 象限 | RS ratio = 题材指数 / 全题材等权基准；RS 动量 = ratio 5 日斜率；四象限 Leading/Weakening/Lagging/Improving | virtual_index 已有 |

**存储**：新 collection `theme_daily_factors`（themeId/date/因子值/qualityFlags），不动 `SECTOR_FACTOR_FIELDS` 落库白名单（避免快照主表膨胀）；每交易日盘后计算一次 + Redis 缓存。

**模块落位**：新建 `quant-board/backend/analysis/theme/factors_daily.py`（暂名，实施时按现有命名习惯定）；算法纯函数优先，I/O 编排放 `backend/services/theme/` 对应服务，遵守 backend 归档硬约束（算法 → analysis，服务 → services）。

### 5.2 快层扩展

- 现有 rotation 四组因子（strength .34 / flow .28 / breadth .22 / crowding .16）**全部不动**；
- 新增 F1 资金流持续性：题材净流入连续为正天数 / 净流入排名变化；数据来自 `services/theme/fund_cache.py` 双源缓存，缺的只是算子。

### 5.3 条件层（情绪门控）

- 新增情绪算子：S1 炸板率、S2 晋级率（一进二成功率）、S3 连板高度与梯队结构；**数据可得性需 Phase 0 确认**（limitSummary 涨停池明细是否含炸板/晋级字段，若无则从涨停池明细推导或接入 KPL 统计口径）；
- 门控语义：`market_phase` × 情绪指标 → 调节快层因子权重与信号可信度标签（例：climax 相位上调 crowding 权重、下调动量权重；ice 相位将动量信号标为低可信）——只影响 confidence 与标签，**不做硬门禁**；
- 实现位置：不动 rotation 引擎核心，在 v12 信号合成层注入 context（对齐 `_theme_execution_signals` 现有分层映射方式）。

## 6. 验证路径（后续研究计划，不属本轮）

```text
Phase 0  数据可得性 spike（一次性，只读）：
         炸板/晋级字段覆盖、题材流通市值数据、一年分位数的历史深度
Phase 1  条件层假设："情绪相位 × 题材动量有效性"
         （momentum_validation 范式：分组收益差 + 排序位移）
Phase 2  拥挤度口径对比：现有 crowding 惩罚 vs 业界一年分位数口径的区分度
Phase 3  D2/D3/D4/F1 逐因子区分度验证
Phase 4  过验因子进 combine → v12 三窗回测重跑 → 首份题材域 verdict 文档存档
```

纪律沿用 `skills/ranktrend-signal-research/SKILL.md`：三窗+冻结、极端行情月感知、已消费窗口打折、参数化不漂移、一次一候选落默认、扫描资源纪律（隔离 runner、单 trial、本地 frames、dry-run）。

**Phase 4 的重跑不是推翻既有结论**：heatLevel 迁移（2026-09-03）后题材域旧结论本就不可沿用（迁移设计文档已自我声明），这次重跑是补上题材域缺失的首份成册结论。

## 7. 错误处理（fail-visible 落点）

- 日线历史不足一年 → D1 返回 `insufficient` 标记，不返回 50 分中性值；
- limitSummary 缺失 → 情绪门控降级为 neutral 权重 + quality 标记，主信号链照常；
- 单因子全源无数据 → 该因子产出失败记录，其余因子不受影响；
- 测试必须证明：部分异常仍产出且带标记、异常原因可经公开 API 或界面观察、仅全源无数据才报因子失败。

## 8. 测试策略

- 因子纯函数单测：已知答案校验，沿用 `backend/operations/harness_common.py` 范式；
- fail-visible 用例：部分异常仍写入/可读/可展示，缺失不被伪造成零值；
- 回测合同测试：沿用 `quant-board/tests/test_theme_backtest.py` 模式；
- 验证 harness 脚本：隔离 runner（吸取 2026-09-23 内存冻结事故教训：单 trial、本地 frames、一律 dry-run）。

## 9. 非目标（明确不做）

- 不推翻既有回测结论；v12 默认参数合同（`docs/theme-module/plans/task_plan_v12.md`）不动；
- 不做景气度/基本面因子；
- 不接 bayesian/tpe 优化器（另立任务）；
- 不恢复前端轮动引擎（`/api/theme-rotation/summary` 前端展示缺口另案处理）；
- 本轮不改任何代码、不跑回测。

## 10. 当前状态与后续

- 2026-09-26：现状盘点 + 业界因子调研 + 分层架构设计确认，本文档落盘。未实施。
- 下一步候选（待用户拍板）：
  1. Phase 0 数据可得性 spike（只读，风险最低，建议先行）；
  2. 按 `writing-plans` 流程把 Phase 0/1 拆成可执行实施计划。
