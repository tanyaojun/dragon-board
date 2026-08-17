# 快照 high/low 数据缺口根因与修复记录（2026-08-17）

> 状态：根因已定位；A1+A3 修复已实施（待观察后续采集数据验证）；历史数据无法回补
> 关联：ATR 均值回归信号依赖 high/low（`ranktrend-atr-signal-design.md` §8 区分度验证阻断性结论，
> 数据缺口是其原因之一）

## 1. 根因（代码实证链路）

```
热榜采集（snapshot_collector/providers.py _row：code/name/rank + price/量/资金）
   └─ akshare 八平台热榜上游本身无 high/low（只有排名/价格/量/资金）── 非采集遗漏
        ↓
行情采集（BridgeQuoteProvider 通达信桥 + TencentBasicQuoteProvider 腾讯）
   └─ quotes 含 high/low；collect_market_context 用 active_codes（热榜全量 code）拉取
        ↓
快照派生（snapshot_derivation/projection.py:283-291 _enrich_stock_rows_from_quotes）
   └─ for field in ("high","low","preClose","open"): row[field] = q.get(field)  ← 补充逻辑存在
        ↓
落库：有 quote 的股票 → high/low 完整；无 quote 的股票 → 字段缺失（fail-visible，快照照常保存）
```

**覆盖不全的两个采集侧机制**：
1. **腾讯行情批次失败**：`_BatchedProxyProvider` 按 50/批拉取，批次失败默认重试 1 次后放弃
   → 该批股票无 quote；
2. **通达信桥 dead_code 挂起**：python-bridge 查询失败/无数据的代码记入 dead_code，
   30 分钟（`TDX_DEAD_CODE_RETRY_MS`）内跳过 → 该股期间无 quote。

**数据实证**：全量 769 帧仅 28% stock 有 high/low；07-20~25 按 slot 覆盖率波动
（10:00/14:00 99%，13:00 31%）；无 quote 样本同时缺 high/low/涨跌停价/turnover（字段整体缺失）。
train 段（04-15~07-07）覆盖更差（行情补充早期未覆盖全）→ 全量 28%。

## 2. 修复（A1+A3，已实施）

- **A1 腾讯批次重试增强**：`_BatchedProxyProvider.failed_batch_retries` 1→2
  （`providers.py`，降低批次失败丢股票）；
- **A3 行情覆盖率告警**：新增 `_append_quote_coverage_warning`（`providers.py`），
  collect_market_context（同步/异步）return 前计算 quotes 覆盖热榜 code 比例，
  < 80% 时记录 `quote_coverage` warning health（error 文本 + details 结构化）——
  fail-visible 暴露低覆盖率，供采集审计/监控发现；
- 测试：`test_snapshot_collector_providers.py` 新增 3 用例（低覆盖率告警/高覆盖率静默/
  空守卫），64→64 passed（采集相关 193 passed）。

## 3. 未覆盖 / 后续

- **历史数据无法回补**：已固化快照缺 high/low 的帧无法补（时点快照）；如需历史 ATR 研究，
  用日线行情源（akshare daily）按 code+date 重建投影（独立任务）；
- **桥 dead_code 恢复 30 分钟**：A1 未改桥侧（环境变量可调 `TDX_DEAD_CODE_RETRY_MS`）；
  如需更快恢复可后续调优；
- **验证**：A1+A3 上线后需观察后续采集的 quoteCoverage 指标与 high/low 覆盖率是否提升
  （第 1 个完整采集日人工核对，参照 AGENTS.md §11 复盘清单）。
