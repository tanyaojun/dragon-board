# Jev 阶段3 涨停驱动分类验证报告

- 标签 9223（ok），有次日匹配 6345，窗口 2026-08-11 → 2026-09-24

## 驱动类型分布 × 次日表现

| 驱动类型 | n | 次日连板率 | 次日 pct 均值 | 中位 |
|---|---|---|---|---|
| ma_restructure | 314 | 21.3% | 1.49 | 0.18 |
| order_earnings | 600 | 14.3% | 1.15 | 0.64 |
| concept_stretch | 2522 | 11.6% | 0.49 | 0.04 |
| industry_cycle | 441 | 8.2% | 0.76 | 0.44 |
| policy | 113 | 6.2% | 0.24 | 0.01 |
| product_event | 2133 | 4.1% | 0.1 | -0.07 |
| capital_flow | 222 | 1.8% | -0.17 | -0.13 |

- Kruskal-Wallis（≥8 样本组）：p=0.0007
- 连板率极差：19.5pct（{'product_event': 4.1, 'order_earnings': 14.3, 'concept_stretch': 11.6, 'industry_cycle': 8.2, 'ma_restructure': 21.3, 'capital_flow': 1.8, 'policy': 6.2}）

## 催化-主业匹配度（Noul）分组

- 高匹配(>0.7) n=3787：次日 pct 均值 0.42%
- 低匹配(<0.3) n=105：次日 pct 均值 -0.02%
- 差值 0.44pct，Mann-Whitney p=0.3039
- Noul 分布：mean=0.7 p25=0.63 p50=0.74 p75=0.82 min=0.18 max=0.92

## 连板（昨日也有 reason）vs 首板分层

- 连板: n=4546 次日连板率 7.2% pct均值 0.12%
- 首板: n=1799 次日连板率 14.0% pct均值 1.33%

## 稳定性抽检

- 未执行（--stability 开启）

## 判定依据

- ✓ 样本≥800
- ✓ 驱动分组 极差≥15pct 且 p<0.05
- ✗ 匹配度 高低差≥2pct 正向 且 p<0.05

注：核心驱动分组信号真实（阈值 2 过），个别轴不足——候选扩窗复验，非 REJECT。

## 判定：INSUFFICIENT