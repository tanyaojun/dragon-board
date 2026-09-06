# 门控翻转率基线（WP2 前，2026-08 冻结段）

- 生成：`python -m backend.operations.diagnose_gate_flip_rate --dataset dragonboard_live --start 2026-08-01 --end 2026-08-31`
- 生成日期：2026-09-06；完整报告 JSON：`data/reports/gate_flip_rate_dragonboard_live_2026-08-01_2026-08-31.json`（运行产物，不入库）
- 样本：frameCount=202 / signalCount=45686 / codes=1813 / comparable_pairs=43873 / missing_fields=0
- 总翻转率：veto=0.1376（6037 次） / bd_downgrade=0.0834（3661 次） / regime_state=0.0010（45 次）
- per-code Top-10（veto）：

| code | veto 翻转次数 |
|---|---|
| 603986 | 91 |
| 002156 | 86 |
| 300308 | 86 |
| 000636 | 85 |
| 688825 | 83 |
| 600584 | 82 |
| 600667 | 82 |
| 000938 | 80 |
| 600176 | 80 |
| 600522 | 80 |

- stage 分布（桶内翻转率，veto / bd_downgrade）：
  - morning（≤10:30）：veto=0.1389 / bd_downgrade=0.0800
  - mid（11:00-13:30）：veto=0.1224 / bd_downgrade=0.0987
  - late（≥14:00）：veto=0.1083 / bd_downgrade=0.1177
- 备注：WP2（K/α/迟滞扫描）完成后用同参数段重跑对比。**口径声明：本基线生成于 WP1c
  （情绪注入 as-of 时点化）合入之后、WP2 之前——情绪注入 lookahead 已修复，门控状态未做
  去噪；与计划模板初稿"WP1c 前 lookahead 未修复"的假设不同，引用时按本声明口径。**
