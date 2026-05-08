# QMT / miniQMT L2 接入计划

更新时间：2026-05-08

## 目标

Dragon Board 的实时盘口和 QuantBoard 的正式资金流回测，优先使用合法 QMT / miniQMT Level2 数据。TDX L1 五档资金流只保留为降级展示，不再作为正式回测硬信号。

## 分阶段落地

1. 环境探针：`python python-bridge/l2/probe_qmt_l2.py --codes 000001.SZ,600000.SH`
2. Provider：`python-bridge/l2/QmtL2Provider` 通过 `xtquant.xtdata` 获取 `l2quoteaux` 和 `l2transactioncount`
3. Bridge：启用 `L2_PROVIDER=qmt`、`QMT_L2_ENABLED=1` 后，WebSocket 输出 `money_flow_patch` 和 QMT 十档盘口
4. 前端：`qmt_l2` 资金流直接替换 TDX 估算；估算资金流仅显示轻量标识
5. QuantBoard：正式资金流策略开启 `require_formal_money_flow` 后，拒绝 `estimated_l1`

## 环境变量

```powershell
$env:L2_PROVIDER = "qmt"
$env:QMT_L2_ENABLED = "1"
$env:QMT_L2_CODE_LIMIT = "80"
$env:QMT_L2_POLL_INTERVAL_MS = "600"
$env:QMT_L2_REQUIRE_OFFICIAL = "1"
```

## 验收口径

- 有 QMT L2 权限时，至少一只股票返回 `moneyFlowSource=qmt_l2`
- 十档不足 10 档时，不标记为高可信十档
- QMT 不可用时，bridge 保持现有 TDX L1 fallback
- QuantBoard 正式资金流回测默认不接受 `estimated_l1`
