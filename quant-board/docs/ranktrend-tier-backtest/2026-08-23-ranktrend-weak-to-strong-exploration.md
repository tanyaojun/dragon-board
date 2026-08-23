# 弱转强（Weak-to-Strong）买入机会探索（2026-08-23，探索性验证）

> 状态：**探索验证完成，结论为无增量 α（阻断性）**——用户诉求"通过热榜趋势排名分析找弱转强买入机会"，
> 经数据探索验证**不成立**。本记录为研究归档（fail-visible），不写回任何 golden 默认值。
> 脚本：`quant-board/scripts/weak_to_strong_explore.py`（复用现有 harness，未发明新收益口径）；
> 报告：`data/reports/weak-to-strong-explore.json`（运行产物，不提交）。

## 1. 背景与问题

用户想挖：**弱转强买入机会**——某股横截面 percentile 从低位（弱）开始转强（排名转升/加速）时的买入点。
这是"动量启动"语义，非均值回归；也与已验证的 crossSection 追强（高分位正 α）同向但**更低分位**。

## 2. 方法（复用现有，不造口径）

- `RankTrendPythonEngine.replay` → 每股信号（`observation.crossSection.percentile / percentileDelta`）。
- `tier_monotonicity.tier_forward_returns` 口径：前视收益 = 未来 horizon 帧 `percentileDelta`(0-1)；
  excess α = 分组均值 − 样本所在「当前 percentile 分位桶」基线均值（去趋势）。
- 分层矩阵：当前 percentile `p`（低 l<30 / 中 m 30-70 / 高 h>70）× `percentileDelta` `d`
  （负 n≤-5 / 平 f / 正 p≥5 / 强正 s≥15）；对比弱转强 `(l,p)/(l,s)` vs 对照
  `(l,n)` 弱→更弱、`(m,p)` 中位转强、`(h,p)` 高位追强。

## 3. 结果（窗口 2026-07-01~08-14，269 帧/41515 信号；excessMeanFutureReturn，>0 为正）

| 桶 | h1 exMean | h8 exMean | 说明 |
|---|---|---|---|
| **(l,p) 弱转强** | **-0.0062** | **-0.0411** | 无增量 |
| **(l,s) 弱强加速** | **-0.0012** | **-0.0218** | 无增量 |
| (l,n) 弱→更弱 | -0.0031 | +0.0148 | 低分位基线回归兜底 |
| (m,p) 中位转强 | +0.0088 | -0.0035 | h1 弱正 |
| (h,p) 高位追强 | **+0.0143** | +0.0103 | **正 α** |
| (h,s) 高位强加速 | +0.0055 | -0.0191 | — |

**单调性**：按 percentile（追强）h1/h8 均 `h > m > l`（+0.0065/+0.0107 > +0.0014/-0.0018 >
-0.0117/-0.0215）——**正 α 在高分位**；按 delta **无稳健单调正 α**（h8 负 delta 反而 +0.0232，属均值回归）。

## 4. 结论（阻断性）

1. **弱转强无增量正 α，甚至略负**：`(l,p)/(l,s)` h1/h8 的 excessMeanFutureReturn 均 ≤0，
   `positive=false`；h8 不优于任何对照。
2. **不是追强的"弱版"，而是其反例**：真正正 α 在 `(mid/high, pos)`（中/高 percentile + 转强 = 追强）；
   低分位即使 delta 转正，后继排名回升**低于同分位基线的平均反弹**。
3. **机理**：低分位 = 热点弱（不热/掉队），其"回升"已被同分位基线的**均值回归**包含，无**超额 α**；
   而"追强"（高分位持续转强）的 α 来自热点的**自我强化**（A 股涨停/散户追涨机制），是 rankTrend 唯一正 α。
4. **对 rankTrend 的 alpha 认知**：连续三次（ATR 方向回归、crossSection×ATR 融合、弱转强）均被数据否定的
   方向是"低位反转/回归/弱转强"；**唯一稳健正 α 是"追强高 percentile"**（crossSection 追强、趋势/量价方向）。

## 5. Caveats（外推谨慎）

- **单窗口**（2026-07-01~08-14）；跨期复测因长窗口 replay 超时（>2min）未完成。
- **样本量**：(l,s) h1=264 / h8=133 偏小，未做 t 检验；"不显著为正"方向可信，"负"幅度勿过度解读。
- **同域**：探索在"有 percentile 的 crossSection 域"（非全市场 benchmark）；percentile 为当帧被跟踪股票
  集合的相对强弱；若 universe 是已筛选候选池，α 相对池内而非全市场。
- `percentileDelta` 无历史时 engine 返回 `None`（按 unknown 桶，未伪造 0）。

## 6. 后续建议

- 若坚持"弱转强"逻辑：需换**信息源**（不止热榜排名——如基本面/资金/题材催化驱动的真实"弱转强"），
  当前热榜排名口径下弱转强无增量。
- 或接受 rankTrend 的 alpha 本质是**追强**：聚焦现有 crossSection 追强 + 趋势/量价/资金的**方向确认**
  （已实证 `crossSection` 追强 +237%、趋势/量价有方向区分度），而非低位反转。
