#!/usr/bin/env bash
# 批次 4 收尾：剩余 3 trial 回老模式（每 trial 独立进程，20 分钟/个，确定性最高）。
# 背景：批量+信号缓存在全窗实测反而慢（trial1 20min / trial2 31min），已停；
# cProfile 小窗口的"信号占 60-75%"不能外推全窗。
set -u
OUT="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest"
RUNNER="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest/exit-scan-trial-runner.py"
FRAMES="D:/dragon-board/quant-board/data/exit-scan-frames-dragonboard_live-half_hour-20260327-20260921.json.gz"
BASE='{"dataset_id":"dragonboard_live","snapshot_type":"half_hour","start_date":"2026-03-27","end_date":"2026-09-21","strategy_name":"ranktrend_early_big_move_v3_lifecycle_fusion","random_seed":20260430,"trade_config":'
MANIFEST="$OUT/exit-scan-batch4-manifest.tsv"

run_trial() {
  local param="$1" value="$2" patch="$3"
  local payload="$OUT/.batch4c-payload.json"
  local ridfile="$OUT/.batch4c-runid.txt"
  printf '%s%s}\n' "$BASE" "$patch" > "$payload"
  local start=$(date +%s)
  (cd D:/dragon-board/quant-board && ./.venv/Scripts/python.exe "$RUNNER" "$payload" "$ridfile" --local-frames "$FRAMES") || true
  local rid=$(cat "$ridfile" 2>/dev/null)
  local elapsed=$(( $(date +%s) - start ))
  echo -e "${param}\t${value}\t${rid}\t${elapsed}" >> "$MANIFEST"
  echo "done: ${param}=${value} -> ${rid} (${elapsed}s)"
}

run_trial trailing "a0.04_d0.4" '{"trailingStopActivateGain":0.04,"trailingStopDrawdown":0.4}'
run_trial breakBoardMinBars 1 '{"breakBoardExit":true,"breakBoardMinBars":1}'
run_trial breakBoardMinBars 3 '{"breakBoardExit":true,"breakBoardMinBars":3}'
echo "batch4 all done" >> "$MANIFEST"
