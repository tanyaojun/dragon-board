#!/usr/bin/env bash
# 卖点扫描第一批（阶段 A1）：stopLoss / takeProfit / maxHoldingBars
# 每参数 4 个非默认档（默认档=基线 bt_8d451aab2e834c7e 不重跑）
# 产出：run_id 清单 exit-scan-batch1-manifest.tsv
set -u
CLI="./.venv/Scripts/python.exe -m backend.cli"
DS="--dataset-id dragonboard_live --snapshot-type half_hour --start-date 2026-03-27 --end-date 2026-09-21"
STRAT="--strategy-name ranktrend_early_big_move_v3_lifecycle_fusion --seed 20260430"
OUT="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest"
MANIFEST="$OUT/exit-scan-batch1-manifest.tsv"
echo -e "param\tvalue\trun_id\telapsed_s" > "$MANIFEST"

run_trial() {
  local param="$1" value="$2" extra="$3"
  local start=$(date +%s)
  local rid=$($CLI run-ranktrend $DS $STRAT $extra 2>/dev/null | grep -oE 'bt_[a-z0-9]+' | head -1)
  local elapsed=$(( $(date +%s) - start ))
  echo -e "${param}\t${value}\t${rid}\t${elapsed}" >> "$MANIFEST"
  echo "done: ${param}=${value} -> ${rid} (${elapsed}s)"
}

# stopLoss（v3 默认 -0.05=基线）
run_trial stopLoss -0.03 "--stop-loss-pct -0.03"
run_trial stopLoss -0.06 "--stop-loss-pct -0.06"
run_trial stopLoss -0.08 "--stop-loss-pct -0.08"
run_trial stopLoss -0.10 "--stop-loss-pct -0.10"
# takeProfit（v3 默认 9.99≈关闭=基线）
run_trial takeProfit 0.06 "--take-profit-pct 0.06"
run_trial takeProfit 0.09 "--take-profit-pct 0.09"
run_trial takeProfit 0.16 "--take-profit-pct 0.16"
# maxHoldingBars（v3 默认 30=基线）
run_trial maxHoldingBars 16 "--max-holding-bars 16"
run_trial maxHoldingBars 24 "--max-holding-bars 24"
run_trial maxHoldingBars 40 "--max-holding-bars 40"
run_trial maxHoldingBars 56 "--max-holding-bars 56"
echo "batch1 all done" >> "$MANIFEST"
