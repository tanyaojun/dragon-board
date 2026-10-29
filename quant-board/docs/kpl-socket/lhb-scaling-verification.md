# KPL 龙虎榜资金字段缩放口径交叉验证（2026-10-29，task-3）

## 结论（裁决）

**×10000 缩放假设证伪：KPL 龙虎榜全部 int64 资金/市值/成交额字段 = 元原样，无缩放。**

## 证据链（2026-10-28 收盘日，样本 603696 安记食品）

对照源：KPL `OnTheLHBStock`（apphis 历史行，22 列 raw）vs 东方财富公开数据（akshare）。

| 字段 | KPL raw | 东财公开值 | 倍率 | 裁决 |
|------|---------|-----------|------|------|
| [6] 成交额（市场总额） | 562678136 | 562678137（市场总成交额） | 1.0（差1=四舍五入） | 元原样 ✓ |
| [12] cirMarket 流通市值 | 3365712000 | 3.365712e9 | 1.0 精确 | 元原样 ✓ |
| [13] ttlMarket 总市值 | 3365712000 | 3.365712e9 | 1.0 精确 | 元原样 ✓ |
| [5] 换手率 | 16.38 | 16.3775 | 1.0 | %原样 ✓ |
| [3] 收盘价 / [4] 涨跌幅 | 14.31 / -10 | 14.31 / -10.0 | 1.0 | 原样 ✓ |
| [8] mainNetAmount | -27469779 | 主力净流入 -27969780.0 | 1.0（差0.18%） | 元原样 ✓ |
| [9] mainBuy | 49176780 | （无独立同口径源） | — | 见口径注 |
| [10] mainSell | -76646559 | （无独立同口径源） | — | 见口径注 |

自洽校验：mainBuy(49176780) + mainSell(-76646559) = -27469779 = mainNetAmount ✓。

## 口径注（重要，避免误消费）

1. **KPL mainNetAmount/mainBuy/mainSell ≠ 交易所龙虎榜席位买卖额**。东财龙虎榜席位
   净买额 -9964364.31、买入总额 31387663.02、卖出总额 41352027.33 与 KPL raw 不成任何
   整数倍。KPL 口径 = **盘中主力大单资金流统计**（与东财个股资金流「主力净流入」同族，
   大单阈值细节造成 ~0.2% 差异：-27469779 vs -27969780）。
2. **消费建议**：与 2112 ForecastLHBResp.Item.mainNetAmount/mainBuy/mainSell（实时盘中
   同族）可比；与交易所龙虎榜席位数据不可直比，做 JE 语料时标注「主力资金口径」。
3. mainSell 为负值（卖出记负号），净额 = mainBuy + mainSell，**不是** mainBuy − mainSell。
4. [14] realCirMarket = 1423696176 ≈ 42.3% × 流通市值（真实自由流通盘，元）。
5. hotVal/hotChange（KPL 自有热度值）：整数原样，无外部独立源，不缩放。

## 复验路径

- KPL 侧样本：`quant-board/.tmp_review/lhbhis_probe_results.jsonl`（tag=stock_full，
  2026-10-28）；2112 实时帧：`.tmp_review/lhb2112_probe_events.jsonl`。
- 东财侧：`akshare.stock_lhb_detail_em(start_date='20261028', end_date='20261028')`、
  `akshare.stock_individual_fund_flow(stock, market)`（120 日窗口内含当日）。
- 解析层已同步：`kpl_lhb_history.py`/`kpl_daban_protocol.py` 注释（raw=元原样，无转换层）。
