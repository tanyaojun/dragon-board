#!/usr/bin/env bash
# 批次 4 补漏：trailing a0.03_d0.3（批量模式被停时未完成）+ 断板 minBars 1（MemoryError 失败）。
# 串行老模式（单进程单 trial），跑完更新 manifest。
set -u
OUT="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest"
RUNNER="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest/exit-scan-trial-runner.py"
FRAMES="D:/dragon-board/quant-board/data/exit-scan-frames-dragonboard_live-half_hour-20260327-20260921.json.gz"
BASE='{"dataset_id":"dragonboard_live","snapshot_type":"half_hour","start_date":"2026-03-27","end_date":"2026-09-21","strategy_name":"ranktrend_early_big_move_v3_lifecycle_fusion","random_seed":20260430,"trade_config":'
MANIFEST="$OUT/exit-scan-batch4-manifest.tsv"

run_trial() {
  local param="$1" value="$2" patch="$3"
  local payload="$OUT/.batch4d-payload.json"
  local ridfile="$OUT/.batch4d-runid.txt"
  rm -f "$ridfile"
  printf '%s%s}\n' "$BASE" "$patch" > "$payload"
  local start=$(date +%s)
  (cd D:/dragon-board/quant-board && ./.venv/Scripts/python.exe "$RUNNER" "$payload" "$ridfile" --local-frames "$FRAMES") || true
  local rid=$(cat "$ridfile" 2>/dev/null)
  local elapsed=$(( $(date +%s) - start ))
  echo -e "${param}\t${value}\t${rid}\t${elapsed}" >> "$MANIFEST"
  echo "done: ${param}=${value} -> ${rid} (${elapsed}s)"
}

run_trial trailing "a0.03_d0.3" '{"trailingStopActivateGain":0.03,"trailingStopDrawdown":0.3}'
run_trial breakBoardMinBars 1 '{"breakBoardExit":true,"breakBoardMinBars":1}'
echo "batch4 truly all done" >> "$MANIFEST"
