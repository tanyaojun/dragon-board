# 题材动量（板块共振）设计/计划对抗性审计报告

日期：2026-08-04
审计对象：
- [设计文档](2026-08-04-theme-momentum-resonance-design.md)
- [实施计划](plans/2026-08-04-theme-momentum-resonance-plan.md)
审计方法：逐条挑战设计假设，对照源码事实验证声称，按 AGENTS.md §11 复盘必查清单逐项复核，识别设计-计划-源码三方不一致处。

---

## 审计结论（先行的）

**设计文档整体结构扎实、fail-visible 原则贯彻到位、AGENTS.md §11 复盘教训吸收充分。但存在 2 个关键级（Critical）和 4 个重要级（Important）问题需要修复后才能进入实现。**

最严重的问题：
1. **设计公式与个股共振源码合同不一致**——设计写 `pos(relMom)`，源码是 `pos(directional_momentum)` 含方向翻转，计划虽正确实现了源码口径但设计文档有误导性。
2. **主题材选择未实现 `mainTheme` 优先**——设计与已有 `theme_trend.py` 都用 `mainTheme` 优先，计划实现只用 `heatScore` 最高，会导致角色-题材错配。
3. **核心验证机制（theme-confluence 回测）被计划明确排除**——设计 §9.1 的基线对比回测未进入任何 Task，替代方案只能做单帧排序对比，无法验证交易结果改善。

---

## 一、关键级发现（Critical）

### C1. 设计公式 `pos(relMom)` 与个股共振源码公式不一致

**发现位置**：设计 §5.3 公式 vs 个股共振源码 [ranktrend.py:1226-1234](D:/dragon-board/quant-board/backend/analysis/ranktrend.py:1226)

**问题**：设计文档写：

```text
themeMomentumScore = round(100 * clamp(0.35*pos(relMom) + 0.25*pos(accel) + ...))
```

暗示 `pos(relMom) = max(0, relativeMomentum)`。但个股共振源码实际逻辑是：

```python
# ranktrend.py:1226-1233
directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
directional_acceleration = -acceleration if direction == "sell" else acceleration
raw_score = (
    0.35 * _positive(directional_momentum)   # ← 不是 pos(relative_momentum)
    + 0.25 * _positive(directional_acceleration)
    ...
)
```

即：当方向判定为 sell 时，负的相对动量被翻转为正贡献。这与 `pos(relMom)`（负值直接截断为 0）有本质区别。

**计划实现是正确的**——`_theme_momentum_for` 正确地复制了方向翻转逻辑（`directional_momentum = -relative_momentum if direction == "sell"`）。但**设计文档的公式符号具有误导性**，未来读者会误以为公式更简单。

**影响**：如果有开发者仅按设计文档实现（不读源码），会写出错误的公式。golden case 如果用设计文档的 `pos()` 语义生成预期值，会与计划实现的输出冲突。

**建议**：修正设计 §5.3 公式，把 `pos(relMom)` 改为 `pos(directional_momentum)`，并补充方向判定规则（`direction_score > 0.1 → buy, < -0.1 → sell`）和方向翻转说明。

---

### C2. 主题材选择未实现 `mainTheme` 优先，与设计和已有代码均矛盾

**发现位置**：设计 §6 vs 计划 Task 2 `stock_theme_exposure` vs 已有 [theme_trend.py:531-538](D:/dragon-board/quant-board/backend/analysis/theme_trend.py:531)

**问题**：设计 §6 明确规定：

> 取所属题材中 heatScore 最高者为主题材（**mainTheme 字段存在且可匹配时优先**）

已有 `theme_trend.py` 的 `_stock_theme`（line 531-538）也实现了 `mainTheme` 优先：

```python
explicit = _name(stock.get("mainTheme") or stock.get("themeName"))
# ...
theme_name = explicit or _name(first.get("name") or first.get("themeName"))
```

但计划 Task 2 的 `stock_theme_exposure` 实现中，**完全没有检查 `mainTheme` 字段**：

```python
candidates = [
    theme for theme in valid
    if any(_matches_theme(value, theme) for value in stock_theme_values)
]
primary = max(candidates, key=lambda theme: _num(theme.get("heatScore"), -1.0))
```

只取 heatScore 最高，忽略了 `mainTheme`。这会造成：某只股票 `mainTheme="人工智能"`、`themes=["人工智能", "半导体"]`，但某帧"半导体"heatScore 高于"人工智能"，则匹配到错误的题材。

**连锁问题**：`_role_for` 检查 `stock.themeRole`，但 `themeRole` 是股票级别的字段，当匹配的题材与 `mainTheme` 不一致时，`themeRole` 可能对应的是 `mainTheme` 的角色而非实际匹配题材的角色，造成角色标签错配。

**建议**：
1. `stock_theme_exposure` 增加 `mainTheme` 优先逻辑：先检查 stock 的 `mainTheme` 字段，在 `hotThemes` 中按名称匹配，命中则直接选为 `primary`；未命中或缺失时才按 heatScore 最高降级。
2. `_role_for` 中 `stock.themeRole` 的使用需要加校验：如果匹配的题材不是 `mainTheme`，`stock.themeRole` 不应直接复用，应回退到基于 heatScore 和 change 的规则判定。

---

## 二、重要级发现（Important）

### I1. 核心验证机制（theme-confluence 回测对比）被计划排除

**发现位置**：设计 §9.1 vs 计划 Task 7 范围说明

**问题**：设计 §9.1 明确要求用 `POST /api/backtests/theme-confluence` 做基线 vs 实验对比：

> 基线：现合同候选排序；实验：候选排序叠加题材动量调节。指标：stability / totalReturn / maxDrawdown / profitFactor。

但计划 Task 7 的范围说明将此事完全排除：

> 官方 POST /api/backtests/theme-confluence 的"实验组"需要回测引擎支持按题材动量调节候选排序，属于独立研究任务，不在本计划内改回测主链。

替代方案 `theme_momentum_validation.py` 只做**单帧排序位移对比**（`baseScore` vs `fusedScore` 的 rank shift），无法回答"题材动量调节是否改善交易结果"这个核心问题。

**影响**：设计声称的"回测验证权重与方向，冻结 golden case 后再上 live"无法实现。上线后如果发现调节方向错误（例如在拥挤期反而给了正向调节），只能靠首日人工观察发现，存在滞后风险。

**建议**：
1. 如果 theme-confluence 回测引擎改造确实成本过高，应在设计文档中明确降级为"单帧排序验证 + 首日观察"，并把回测验证列为 P1 follow-up。
2. 另一种可行方案：在 Task 7 的 `compare_theme_momentum_ranking` 基础上，对多帧序列做滚动排序对比，至少回答"调节是否系统性地改变排序"和"调节方向是否与 lifecycle 一致"。
3. 最低要求：在设计文档中将 §9.1 的"回测验证"降级表述与计划对齐，避免设计与计划口径不一致。

---

### I2. `fuse_theme_resonance` 覆盖原共振对象，丢失"调节前"基准

**发现位置**：计划 Task 4 Step 3 路由集成代码 vs 设计 §7.2

**问题**：计划的路由集成代码用 `fuse_theme_resonance` 的返回值直接覆盖 `analysis["resonance"]`：

```python
analysis["resonance"] = resonance
exposure = stock_theme_exposure(stock, frame.get("hotThemes") or [])
analysis["resonance"] = fuse_theme_resonance(resonance, exposure, frame_momentum)
```

融合后，原始的 `resonance.score` 被修改后的 `fused.score` 取代。虽然 `fuse_theme_resonance` 用 `dict(base_resonance or {})` 做了浅拷贝，但：

1. API 消费者无法区分"原始共振分数"和"题材调节后分数"——只能看到一个最终值。
2. 设计 §7.2 说"保留原共振分数"，但从 API 响应中不可见调节前的值。
3. 调试/审计时无法快速判断调节幅度是否合理。

**建议**：融合结果中保留 `baseScore`（调节前原始共振分数），使 `score` 为调节后、`baseScore` 为调节前。或在 `resonance.theme` 中显式记录 `baseScoreBeforeAdjustment`。设计 §7.1 的 `finalResonanceScore = clamp(baseScore + adjustment + ...)` 本身就隐含了 baseScore 应该可见的意图。

---

### I3. 主题材模糊名称匹配存在假阳性风险

**发现位置**：计划 Task 1 `_is_same_theme_name`

**问题**：模糊匹配规则：

```python
shorter, longer = sorted((left_name, right_name), key=len)
return len(shorter) >= 3 and shorter in longer and len(shorter) / len(longer) >= 0.75
```

以下边界场景会出问题：
- "云计算"（3 字）in "云计算安全"（5 字），3/5=0.6，不匹配。❌ 漏匹配——这是合理的（保守）。
- "新能源车"（4 字）in "新能源汽车"（5 字），4/5=0.8，匹配。✓
- "人工智能"（4 字）vs "人工钻石"（4 字）：等长不走 shorter/longer 分支，走 `left_name == right_name`，不匹配。✓
- "芯片概念"（4 字，去掉"概念"后"芯片"2 字）vs "芯片"（2 字，去掉后仍"芯片"2 字）：shorter="芯片" len=2 < 3，不匹配。❌ 漏匹配！
- "区块链"（3 字）vs "区块链技术"（5 字，去后缀仍 5 字）：3/5=0.6，不匹配。❌ 漏匹配，但这是同名题材的不同命名变体。

`_normalize_theme_name` 去掉了"概念板块"、"概念"、"板块"后缀，但"区块链"和"区块链技术"的差异是"技术"后缀，不会被 strip。这会导致同一题材的不同命名变体匹配失败。

**影响**：个股 `themes` 中的题材名可能与 sector rows 中的 `themeName` 因后缀差异而匹配失败，导致 `exposure = None`（无题材暴露），退化为 `theme_mapping_missing`。在 A 股题材命名不规范的环境下，这种假阴性可能相当频繁。

**建议**：
1. 在 `_normalize_theme_name` 中增加常见后缀列表：`"技术"、"产业"、"经济"、"行业"、"主题"` 等。
2. 在 golden case 中增加名称变体匹配测试（含后缀差异、简繁差异）。
3. 考虑在 MongoDB 的 sector rows 中增加 `aliases` 字段（不做为本次范围，但记录为已知限制）。

---

### I4. 缺少对"全 NaN heatScore"帧的测试覆盖

**发现位置**：计划 Task 1 测试用例

**问题**：现有测试覆盖了：
- `test_series_keeps_only_rank_eligible_finite_heat`（部分 NaN）✓
- `test_momentum_series_insufficient_cross_section`（横截面不足）✓
- `test_momentum_series_skips_short_history_theme`（缺槽）✓

但缺少以下边界测试：
1. **所有题材 heatScore 均为 NaN**：此时 `short_changes` 为空，`market_median = None`，`cross_section_ok = False`。验证输出 `qualityFlags = ["theme_cross_section_insufficient"]`，且融合返回 `insufficient`。
2. **前 8 帧有数据、第 9 帧起全 NaN**：已建立的序列会在缺槽后自然退出 `prefix_by_theme`（因为 `prefix` 不再增长），但应验证是否正确降级。
3. **`crowdingRisk` 为 NaN**：`_num` 默认返回 0，导致 `lifecyclePenalty = 0`。0 和"未知"语义不同，应该标记。

**建议**：补充上述 3 个边界测试。

---

## 三、设计-计划一致性问题

### A1. 设计 §5.2 参数 `themeSeriesMinBars = 9`，计划用 `THEME_MID_WINDOW_BARS + 1 = 9`

一致。✓ 但设计注释写"与个股 RESONANCE_MIN_SERIES_POINTS 对齐"，源码 [ranktrend.py:1083](D:/dragon-board/quant-board/backend/analysis/ranktrend.py:1083) 确认 `RESONANCE_MIN_SERIES_POINTS = RESONANCE_MID_WINDOW_BARS + 1`。✓

### A2. 设计 §5.3 reversalPenalty 的 `rotationState` 加成

设计写 `rotationState in {cooling, outflow, divergence} ? 0.2 : 0`。
计划 `REVERSAL_LIFECYCLES = {"cooling", "outflow", "divergence"}`。一致。✓

### A3. 设计 §7.1 `adjustment = clamp(round(...), -15, 15)`

设计写 `round()` 在 clamp 之前。
计划 `_clamp((momentum["score"] - 50.0) * exposure["roleWeight"] * THEME_ADJUSTMENT_SCALE, -THEME_ADJUSTMENT_MAX, THEME_ADJUSTMENT_MAX)` **没有 `round()`**。

计划在输出时对 `adjustment + lifecycle_bonus - lifecycle_penalty` 整体做 `round(..., 2)`。这意味着调整值可以是浮点数（如 12.73），而设计暗示应为整数。

**差异程度**：微小。不影响计算正确性，但 golden case 数值可能有 ±0.5 的舍入差异。

**建议**：统一口径——要么设计去掉 `round()`，要么计划加上。推荐保持浮点精度（去掉设计中的 `round()`），因为融合后的最终分数会再做 `round(..., 0)`。

### A4. 计划 Task 5 `RankTrendThemeResonance` 类型缺少 `themeMomentumDirection` 字段

计划 Task 5 Step 3 的 TypeScript 接口定义了 `themeMomentumDirection?: 'buy' | 'sell' | 'hold'`，但设计 §7 的融合合同中未提及此字段透传。实际上 Python `_theme_momentum_for` 返回了 `direction` 字段（在 plan Task 1 第 308 行），也写入了融合输出的 `themeMomentumDirection`（plan Task 2 Step 3 第 589 行）。设计文档应补充此字段说明。

---

## 四、AGENTS.md §11 复盘必查清单逐项复核

| # | 检查项 | 设计 | 计划 | 判定 |
|---|--------|------|------|------|
| 1 | 核心目标 5 句话以内说清楚 | §1 正好 5 句 | 复述 | ✓ 通过 |
| 2 | 无质量门禁/阻断 | fail-visible，不足降级不归零 | 实现正确 | ✓ 通过 |
| 3 | 不引入分阶段 shadow/live 双跑 | §9.3 小范围观察 | Task 9 首日验证 | ✓ 通过 |
| 4 | 无独立守护进程/计划任务 | 集成 analyze 路由 | 同设计 | ✓ 通过 |
| 5 | 不新增 MongoDB 集合/API/CLI | §3 非目标明确列出 | 复用现有 | ✓ 通过 |
| 6 | 条件判断语义逐条书面化 | 质量标记列表有语义 | code review 提及 | ⚠️ 部分：`_role_for` 的 `>=` 阈值语义未书面化解释 |
| 7 | 环境变量默认值生产安全 | 权重为 Python 常量 | 同设计 | ✓ 通过 |
| 8 | 首日人工验证清单 | §9.3 有 4 项 | Task 9 复述 | ✓ 通过 |

**第 6 项补充**：`_role_for` 中 leader/core/follower/independent/noise 的判定阈值（heatScore >= 70/45/20、change >= 5/0/-5）是直接从 `theme_trend.py:_ts_role_for` 复制的阈值。这些阈值在 theme_trend 上下文中可能合理，但用于共振融合时应显式说明选择依据（为什么 leader 要求 heatScore >= 70 而非 >= 60？为什么 follower 下限是 45？）。建议在设计 §6 或计划注释中补充阈值来源说明。

---

## 五、源码事实校验

### 5.1 设计声称"projection='ranktrend' 显式置空 sectors/hotThemes"——确认

- [mongo_repository.py:185](D:/dragon-board/quant-board/backend/data/mongo_repository.py:185)：`sector_rows_by_snapshot = {} if projection == "ranktrend" else ...` ✓
- [mongo_repository.py:192-196](D:/dragon-board/quant-board/backend/data/mongo_repository.py:192)：`hotThemes = []` ✓
- [repository.py:587](D:/dragon-board/quant-board/backend/data/repository.py:587)：`if projection != "ranktrend":` 守卫 sector query ✓
- [repository.py:607-612](D:/dragon-board/quant-board/backend/data/repository.py:607)：`hotThemes = []` ✓

### 5.2 设计声称"个股 momentumScore 是单帧点值 (50 + 平均涨幅*8 + 热度差*1.5)"——确认

- [theme_heat.py:182-184](D:/dragon-board/quant-board/backend/analysis/theme_heat.py:182)：`int(_clamp(round(50 + trimmed_mean_change * 8 + (float(heat_score) - previous_heat_score) * 1.5)))` ✓

### 5.3 设计声称"theme_trend.py 注释明确跨帧热度趋势/动量背离为预留项"——确认

- [theme_trend.py:560](D:/dragon-board/quant-board/backend/analysis/theme_trend.py:560)（`_build_exposure` 附近）：`reasons` 列表不含跨帧动量项 ✓

### 5.4 计划声称"repository.py 的 themes_json/theme_role/theme_contribution/lead_status 均为 SnapshotStockRowModel 现有列"——需验证

计划 Task 3 Step 4 声称这些是现有数据库列。但当前 `repository.py:571-583` 的 ranktrend 分支中 stock item 不包含这些字段。需要确认 `SnapshotStockRowModel` 是否真的有这些列。

**建议**：实现前用 `grep` 确认 `SnapshotStockRowModel` 的定义包含 `themes_json`、`theme_role`、`theme_contribution`、`lead_status` 列。如果不存在，需要先做数据库 migration。

---

## 六、测试覆盖缺口

| 场景 | 设计提到 | 计划测试 | 缺口 |
|------|---------|---------|------|
| 题材序列足够、横截面足够 | ✓ | Task 1 `test_momentum_series_mirrors_resonance_bounds` | ✓ |
| 横截面不足 | ✓ | Task 1 `test_momentum_series_insufficient_cross_section` | ✓ |
| 题材缺槽/短历史 | ✓ | Task 1 `test_momentum_series_skips_short_history_theme` | ✓ |
| 个股无题材映射 | ✓ | Task 2 `test_fusion_missing_mapping_keeps_base_score` | ✓ |
| 横截面不足导致 insufficient | ✓ | Task 2 `test_fusion_insufficient_when_cross_section_bad_keeps_base_score` | ✓ |
| 调节边界和方向不变 | ✓ | Task 2 `test_fusion_adjustment_bounded_and_direction_preserved` | ✓ |
| 生命周期惩罚（跟风+cooling） | ✓ | Task 2 `test_fusion_lifecycle_penalty_for_follower_in_cooling` | ✓ |
| 题材方向 = sell | ✗ | ✗ | **缺失** |
| 题材方向 = hold | ✗ | ✗ | **缺失** |
| 全 NaN heatScore | ✗ | ✗ | **缺失** |
| 生命周期奖励（龙头+mainline） | ✗ | ✗ | **缺失** |
| reversalPenalty rotationState 加成 | ✗ | ✗ | **缺失** |
| Jump 检测 — rank 缺值只用 heatScore | ✗ | ✗ | **缺失** |
| Jump 检测 — rank Jump 触发 | ✗ | ✗ | **缺失** |
| 模糊名称匹配假阳性/假阴性 | ✗ | ✗ | **缺失** |
| `mainTheme` 优先选择 | ✓（设计） | ✗（计划未实现） | **关键缺失** |

---

## 七、架构与性能关注点

### 7.1 Sector rows 全量加载性能

计划 Task 3 移除 `projection="ranktrend"` 对 sector rows 的跳过逻辑。当前 analyze 窗口为 30 帧（`ANALYZE_MAX_TRACK_WINDOW = 30`），每帧 ~239 个 hot_theme sector rows，加上行业板块 sector rows。预计额外数据量：

- MongoDB：30 × (239 hot_themes + ~30 sectors) × ~400 bytes/row ≈ 3.2 MB（可接受，但会增加 ~50-100ms 查询时间）
- SQLite：同上，ORM 映射开销更大

**建议**：在 Task 3 实现后，对 analyze API 做一次简单延时对比（改动前 vs 改动后），记录在 commit message 或 Task 9 验证中。

### 7.2 `compute_theme_momentum_series` 每帧 O(themes²) 分析

`compute_theme_momentum_series` 对每帧遍历所有符合条件的题材并计算动量。30 帧 × 239 题材 × 约 20 次浮点运算 ≈ 143K 次运算。计算量可忽略不计，但函数当前是同步的，在 FastAPI 的 `run_in_executor` 线程池中运行。如果 analyze 并发度高（默认 `max_concurrency=2`），影响有限。

### 7.3 analyze 响应体积膨胀

`themeContext.factors` 包含**所有题材的动量分数**（按 score 降序），每帧 239 个对象的 JSON 数组：

```json
"factors": [
  {"themeId": "T0", "status": "ok", "score": 85, "direction": "buy", ...},
  ... × 239
]
```

每个 factor 对象约 200 bytes → 239 × 200 ≈ 48 KB/帧。对于 analyze API（典型返回 1-5 帧），额外体积 48-240 KB。对于网络传输而言可接受，但前端展示只需要 top-N（如前 10 题材）。建议 `themeContext.factors` 默认只返回 top 10，或增加 `?theme_limit=N` 参数。

---

## 八、风险补充（设计 §12 未覆盖）

1. **`_is_same_theme_name` 假阴性风险**：A 股题材命名高度不规范，同一题材在 stock.themes 和 sector_rows.themeName 中可能以不同变体出现（"AI概念" vs "人工智能"、"新能源" vs "新能源车"）。当前纯字符串匹配无法处理语义等价。（严重程度：中，影响个股题材暴露覆盖率）

2. **`crowdingRisk` 为 0 的二义性**：0 可能表示"不拥挤"或"数据缺失"。`_num` 对 NaN 默认返回 0，导致 `lifecyclePenalty = 0`。如果某题材 `crowdingRisk` 字段缺失（NaN），会被静默当作"不拥挤"，跳过生命周期惩罚。（严重程度：低-中，因为 lifecycle 状态本身已提供拥挤信号）

3. **heatScore 跨帧可比性假设**：题材 heatScore 的绝对值受市场整体热度影响（普涨日所有题材 heatScore 偏高）。通过横截面中位数差分（`themeShortChange - marketThemeMedianShortChange`）可以部分消除，但前提是横截面足够大且分布稳定。当横截面 < 20 个题材时直接降级 insufficient，这是正确的保守策略。

4. **`mainTheme` 字段在 MongoDB 中的覆盖率未知**：设计假设 `mainTheme` 字段存在，但未说明该字段的填充逻辑和覆盖率。如果 `mainTheme` 在大部分 stock rows 中为空，则 §6 的"mainTheme 优先"退化为 heatScore 最高，实际行为与计划当前实现一致。

---

## 九、建议修改清单

### 设计文档修改（`2026-08-04-theme-momentum-resonance-design.md`）

| 优先级 | 修改项 | 位置 |
|--------|--------|------|
| Critical | 修正 §5.3 公式：`pos(relMom)` → `pos(directional_momentum)`，补充方向判定与翻转规则 | §5.3 |
| Critical | §6 补充"mainTheme 不存在时降级为 heatScore 最高"的显式降级逻辑 | §6 |
| Important | §9.1 降级表述：如果 theme-confluence 回测不进入本期范围，明确说明降级方案和 follow-up 计划 | §9.1 |
| Important | §7.1 融合合同中增加 `baseScore` 字段，使调节前原始分数在 API 响应中可见 | §7.1 |
| Minor | §7 融合合同补充 `themeMomentumDirection` 字段说明 | §7 |
| Minor | §6 角色判定阈值补充来源说明（与 `theme_trend.py:_ts_role_for` 对齐） | §6 |

### 实施计划修改（`plans/2026-08-04-theme-momentum-resonance-plan.md`）

| 优先级 | 修改项 | 位置 |
|--------|--------|------|
| Critical | Task 2 `stock_theme_exposure` 实现增加 `mainTheme` 优先逻辑 | Task 2 Step 3 |
| Critical | Task 2 `_role_for` 增加主题材匹配校验：当匹配题材非 mainTheme 时，不使用 stock.themeRole | Task 2 Step 3 |
| Important | Task 2 Step 1 增加测试：`test_exposure_main_theme_priority`、`test_fusion_direction_sell`、`test_fusion_direction_hold`、`test_fusion_lifecycle_bonus_leader_mainline` | Task 2 Step 1 |
| Important | Task 1 Step 1 增加测试：`test_momentum_series_all_nan_heat`、`test_momentum_series_jump_by_rank`、`test_momentum_series_jump_missing_rank` | Task 1 Step 1 |
| Important | Task 3 实现前确认 `SnapshotStockRowModel` 有 `themes_json/theme_role/theme_contribution/lead_status` 列 | Task 3 新增 Step 0 |
| Minor | Task 1 Step 3 代码：`_is_same_theme_name` 的 `_normalize_theme_name` 后缀列表增加 `"技术"、"产业"、"经济"、"行业"` | Task 1 Step 3 |
| Minor | Task 5 Step 1 测试中 `pnpm test --` 语法验证是否与 Vitest 兼容 | Task 5 Step 1 |
| Minor | Task 9 增加"analyze 响应延时对比（改动前 vs 改动后）"验收项 | Task 9 Step 4 |

---

## 十、正面评价

以下方面设计/计划做得很好，值得肯定：

1. **AGENTS.md §11 复盘教训吸收充分**：无质量门禁、无分阶段验证、无独立守护进程、无新集合/API/CLI、环境变量零新增、首日人工验证清单。每一项都直接回应了 Backend Snapshot Collector 的复盘教训。

2. **Fail-visible 原则贯彻彻底**：题材数据不足时保留原共振分数、输出结构化原因、不归零不伪造——从设计到计划到测试用例，这条原则被反复验证。

3. **向后兼容设计**：`theme` 字段为可选、旧消费方不受影响、可逐文件回退。这是生产安全的扩展策略。

4. **与个股共振的结构对齐**：题材动量使用与个股共振相同的窗口参数（3/8/8/3）、相同的因子权重（0.35/0.25/0.2/0.2/-0.2）、相同的横截面最小样本数（20）。这种对齐降低了理解成本和参数漂移风险。

5. **风险意识充分**：设计 §12 识别了双动量同质化、拥挤后期失效、粒度错配、缺槽四大风险，并给出了对应的缓解措施。

6. **测试驱动流程完整**：每个 Task 都有"写失败测试 → 确认失败 → 实现 → 确认通过 → Commit"的 TDD 循环，符合项目 TDD 要求。

---

## 附录：审计验证轨迹

审计过程中核验的源码文件：

| 文件 | 行号 | 核验内容 |
|------|------|---------|
| `quant-board/backend/analysis/ranktrend.py` | 1080-1084 | 共振参数常量 |
| `quant-board/backend/analysis/ranktrend.py` | 1087-1088 | `_positive` 函数 |
| `quant-board/backend/analysis/ranktrend.py` | 1127-1255 | `analyze_rank_resonance` 完整公式 |
| `quant-board/backend/analysis/ranktrend.py` | 1218-1234 | 方向判定与方向翻转逻辑 |
| `quant-board/backend/analysis/theme_heat.py` | 180-186 | momentumScore 公式 |
| `quant-board/backend/analysis/theme_trend.py` | 374-386 | `_ts_role_for` 角色判定 |
| `quant-board/backend/analysis/theme_trend.py` | 531-538 | `_stock_theme` mainTheme 优先 |
| `quant-board/backend/data/mongo_repository.py` | 170-210 | `load_frame_bundles` ranktrend 分支 |
| `quant-board/backend/data/repository.py` | 555-624 | SQLite 镜像路径 |
| `quant-board/backend/api/ranktrend_routes.py` | 198-270 | `_analyze_frames` 当前流程 |
| `quant-board/backend/api/ranktrend_routes.py` | 273-287 | `_apply_resonance_final` |
