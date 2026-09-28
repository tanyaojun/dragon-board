# 注册 QuantBoard After Market 计划任务（幂等，可重复执行以重建任务）。
#
# 盘后链（backend/operations/schedule.py run_after_market_once，mongodb 后端）：
#   hotlistSentiment -> mongodbBackup（交易日 light / 周五 full -> verify -> prune -> 周五 push R2）
#   -> snapshotArchiveR2（2026-09-28：四类型快照日归档 parquet 进 R2，T-1 幂等；
#      历史回填用 backend.cli snapshot-archive-backfill）
# 任一步失败以非零码退出，任务计划历史可见；结果摘要落盘
# data/backups/mongodb/after_market.log（失败另存完整 JSON）。
#
# 2026-09-28 触发时间 15:30 -> 18:00：15:30 是 daily 快照采集窗口，18:00 保证
# 备份与归档拿到全天完整数据（含 daily 与 15:30 半小时槽）。
#
# 2026-09-16 起备份并入本任务；旧的 QuantBoard-LightBackup / QuantBoard-FullBackup
# 独立任务由本脚本幂等清理。
#
# 用法（需要当前用户权限，无需管理员）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_after_market_task.ps1

$ErrorActionPreference = 'Stop'

$taskName = 'QuantBoard After Market'
$quantBoardRoot = Split-Path -Parent $PSScriptRoot  # scripts/ 的上级 = quant-board
$pythonExe = Join-Path $quantBoardRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
    throw "python.exe not found: $pythonExe"
}

$action = New-ScheduledTaskAction -Execute $pythonExe `
    -Argument '-m backend.cli after-market-once' `
    -WorkingDirectory $quantBoardRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 18:00
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

# 清理已被取代的独立备份任务（备份已并入 After Market 盘后链）
foreach ($legacy in 'QuantBoard-LightBackup', 'QuantBoard-FullBackup') {
    if (Get-ScheduledTask -TaskName $legacy -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $legacy -Confirm:$false
        Write-Host "removed legacy task '$legacy'"
    }
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'QuantBoard 盘后链（18:00）：热榜情绪计算 + MongoDB 备份（交易日 light / 周五 full，含 verify/prune/周五 R2 push）+ 四类型快照 R2 日归档' `
    | Out-Null

Write-Host "registered task '$taskName'"
Write-Host "  action : $pythonExe -m backend.cli after-market-once"
Write-Host "  workdir: $quantBoardRoot"
Write-Host "  trigger: daily 18:00 (StartWhenAvailable, 电池/错过窗口补跑)"
