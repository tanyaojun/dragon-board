#!/usr/bin/env bash
# 卖点扫描第二批 v2（阶段 A1 后半）：useAtrStops / breakevenTrailing / weakStateExit /
# signalExitDelayBars / minHoldingBars（默认档=基线 bt_8d451aab2e834c7e 不重跑）
# v2 加固（2026-09-22 首跑全灭复盘）：
#   - 每个 trial 记录 HTTP 状态码；非 200 响应另存 error 文件供诊断
#   - 每个 trial 前探活后端（/docs），不健康则等待至多 30 分钟
#   - manifest 增加 http_code 列
set -u
OUT="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest"
MANIFEST="$OUT/exit-scan-batch2-manifest.tsv"
API="http://127.0.0.1:8000"
BT_ENDPOINT="$API/api/backtests/rank-trend"
BASE='{"dataset_id":"dragonboard_live","snapshot_type":"half_hour","start_date":"2026-03-27","end_date":"2026-09-21","strategy_name":"ranktrend_early_big_move_v3_lifecycle_fusion","random_seed":20260430,"trade_config":'

wait_backend() {
  local i
  for i in $(seq 1 60); do
    local code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$API/docs" 2>/dev/null)
    [ "$code" = "200" ] && return 0
    sleep 30
  done
  return 1
}

run_trial() {
  local param="$1" value="$2" patch="$3"
  if ! wait_backend; then
    echo -e "${param}\t${value}\tBACKEND_DOWN\t0\tskip" >> "$MANIFEST"
    return 1
  fi
  local start=$(date +%s)
  local resp="$OUT/.batch2-resp.json"
  local body="${BASE}${patch}}"
  local code=$(curl -s --max-time 3000 -w "%{http_code}" -o "$resp" -X POST "$BT_ENDPOINT" \
    -H "Content-Type: application/json" -d "$body")
  local rid=$(grep -oE 'bt_[a-z0-9]+' "$resp" 2>/dev/null | head -1)
  local elapsed=$(( $(date +%s) - start ))
  echo -e "${param}\t${value}\t${rid}\t${elapsed}\thttp_${code}" >> "$MANIFEST"
  if [ "$code" != "200" ] || [ -z "$rid" ]; then
    cp "$resp" "$OUT/.batch2-error-${param}-${value}.json" 2>/dev/null
  fi
  echo "done: ${param}=${value} -> ${rid} (http ${code}, ${elapsed}s)"
}

echo -e "param\tvalue\trun_id\telapsed_s\thttp_code" > "$MANIFEST"
# useAtrStops + atrStopMultiplier（默认 off=基线）
run_trial atrStopMultiplier 1.5 '{"useAtrStops":true,"atrStopMultiplier":1.5}'
run_trial atrStopMultiplier 2.0 '{"useAtrStops":true,"atrStopMultiplier":2.0}'
run_trial atrStopMultiplier 2.5 '{"useAtrStops":true,"atrStopMultiplier":2.5}'
run_trial atrStopMultiplier 3.0 '{"useAtrStops":true,"atrStopMultiplier":3.0}'
# breakevenTrailing + threshold（默认 off=基线）
run_trial breakevenThreshold 0.02 '{"breakevenTrailing":true,"breakevenThreshold":0.02}'
run_trial breakevenThreshold 0.04 '{"breakevenTrailing":true,"breakevenThreshold":0.04}'
run_trial breakevenThreshold 0.06 '{"breakevenTrailing":true,"breakevenThreshold":0.06}'
# weakStateExit + zljzb 阈值（默认 off=基线；观察级口径）
run_trial weakStateExitZljzb -3 '{"weakStateExit":true,"weakStateExitZljzb":-3}'
run_trial weakStateExitZljzb -5 '{"weakStateExit":true,"weakStateExitZljzb":-5}'
run_trial weakStateExitZljzb -8 '{"weakStateExit":true,"weakStateExitZljzb":-8}'
# signalExitDelayBars（默认 0=基线）
run_trial signalExitDelayBars 1 '{"signalExitDelayBars":1}'
run_trial signalExitDelayBars 2 '{"signalExitDelayBars":2}'
run_trial signalExitDelayBars 3 '{"signalExitDelayBars":3}'
# minHoldingBars（默认 0=基线）
run_trial minHoldingBars 1 '{"minHoldingBars":1}'
run_trial minHoldingBars 2 '{"minHoldingBars":2}'
run_trial minHoldingBars 4 '{"minHoldingBars":4}'
echo "batch2 all done" >> "$MANIFEST"
