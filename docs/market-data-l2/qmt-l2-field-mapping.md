# QMT L2 字段映射

更新时间：2026-05-08

## 标准输出

### Depth10Book

```json
{
  "code": "000001",
  "bids": [{ "price": 10.1, "volume": 1200 }],
  "asks": [{ "price": 10.11, "volume": 900 }],
  "provider": "qmt",
  "depthLevelCount": 10,
  "sourceTs": 0,
  "timestamp": 0
}
```

### MoneyFlowFrame

```json
{
  "code": "000001",
  "zlje": 0,
  "zljzb": 0,
  "cddje": 0,
  "cddjzb": 0,
  "moneyFlowSource": "qmt_l2",
  "moneyFlowEstimated": false,
  "capitalFlowSource": "broker_l2",
  "capitalFlowConfidence": "high"
}
```

## 当前映射策略

- `l2quoteaux` 用于十档盘口。
- `l2transactioncount` 用于大单/超大单统计和资金流字段。
- QMT 不同版本字段名可能不同，首期 provider 兼容常见英文驼峰、下划线和 Dragon Board 既有字段名。
- 实盘联调后，如果本机返回字段与当前兼容集合不一致，只更新本映射和 `QmtL2Provider`，不改前端资金流合同。

## 来源分层

- `broker_l2`：券商/QMT Level2 数据，可进入正式资金流回测。
- `official_l2`：官方授权 Level2 数据，可进入正式资金流回测。
- `estimated_l1`：L1 五档或分时估算，只能作为观察指标。
