#!/usr/bin/env bash
# 卖点扫描第三批（阶段 A 收口组合验证）：批次 1/2 Top 候选的组合
#   trial 1: tp0.06 × breakeven0.02（兑现 + 保本，机理不同可叠加）
#   trial 2: tp0.06 × breakeven0.02 × maxHoldingBars 16（+限时）
# 复用批次 2 v3 加固：http_code 入 manifest、错误响应落盘、trial 前探活。
set -u
OUT="D:/dragon-board/quant-board/docs/ranktrend-tier-backtest"
MANIFEST="$OUT/exit-scan-batch3-manifest.tsv"
API="http://127.0.0.1:8000"
BT_ENDPOINT="$API/api/backtests/rank-trend"
BASE='{"dataset_id":"dragonboard_live","snapshot_type":"half_hour","start_date":"2026-03-27","end_date":"2026-09-21","strategy_name":"ranktrend_early_big_move_v3_lifecycle_fusion","random_seed":20260430,"trade_config":'

wait_backend() {
  local i
  for i in $(seq 1 60); do
    local code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$API/api/backtests/checkpoints?limit=1" 2>/dev/null)
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
  local resp="$OUT/.batch3-resp.json"
  local body="${BASE}${patch}}"
  local code=$(curl -s --max-time 3000 -w "%{http_code}" -o "$resp" -X POST "$BT_ENDPOINT" \
    -H "Content-Type: application/json" -d "$body")
  local rid=$(grep -oE 'bt_[a-z0-9]+' "$resp" 2>/dev/null | head -1)
  local elapsed=$(( $(date +%s) - start ))
  echo -e "${param}\t${value}\t${rid}\t${elapsed}\thttp_${code}" >> "$MANIFEST"
  if [ "$code" != "200" ] || [ -z "$rid" ]; then
    cp "$resp" "$OUT/.batch3-error-${param}-${value}.json" 2>/dev/null
  fi
  echo "done: ${param}=${value} -> ${rid} (http ${code}, ${elapsed}s)"
}

echo -e "param\tvalue\trun_id\telapsed_s\thttp_code" > "$MANIFEST"
run_trial combo tp0.06_be0.02 '{"takeProfit":0.06,"breakevenTrailing":true,"breakevenThreshold":0.02}'
run_trial combo tp0.06_be0.02_mh16 '{"takeProfit":0.06,"breakevenTrailing":true,"breakevenThreshold":0.02,"maxHoldingBars":16}'
echo "batch3 all done" >> "$MANIFEST"
