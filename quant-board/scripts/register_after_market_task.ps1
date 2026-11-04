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
# 2026-11-04 触发时间 16:00 -> 17:00（用户裁决）：
#   韭研异动解析盘后持续补充名单——15:35/16:00 版可能不完整（当日实测 15:35 版仅 44 只、
#   晚间补齐到 136；THS 独立口径涨停 116+炸板 32），16:00 链 jiuyanLabel 据此打标锁死
#   半截名单且 relay 叙事/归因等下游全部基于不完整名单。17:00 触发 + 链首预检
#   run_jiuyan_preflight：远端探针 vs 落库对账，不一致先幂等重采补齐（零 jev token），
#   补齐后仍不一致拦停链（stoppedAt=jiuyanPreflight），不烧不完整投喂。
#   代价：盘后读数/脉拍句子晚 ≈1 小时（相对 16:00 时代）。
#
# 2026-10-08 触发时间 18:00 -> 16:00（用户裁决，盘后读数/脉拍句子提前可用）：
#   half_hour 最后槽 15:00/EOD ≈15:05 落库，daily 型唯一槽 15:30 ≈15:40 落库，
#   16:00 触发留 ≈20 分钟缓冲；R2 归档为 T-1 口径无当日竞态；脉拍门控所需的
#   当日 EOD 情绪文档由本链 hotlistSentiment 步自行产出，链内自洽。
#   残余风险：15:30 daily 槽采集若超时溢出到 16:00 之后，当日 dump 可能晚见该帧，
#   由次日 T-1 归档与 8 天全量补跑（_maybe_force_full_catch_up）自愈，不需人工介入。
#
# 2026-10-12 新增 relayIndex 步（用户裁决，盘后链内、jiuyanLabel 之后）：连板情绪指数
#   日判定（jev_relay_index --relay-day 当日，七题一 call ≈5.5k tokens/日）；门控与
#   jiuyanLabel 同源（当日 jiuyan final + 15:00 盘面帧，缺料跳过）；幂等（RELAY 文档已 ok
#   自动跳过）；advisory 语义（失败/跳过不翻转整体 ok）。此前该判定无自动调度、靠手动逐日跑，
#   2026-10-12 因 VPN 断连致 final 缺失漏跑一次（手动补打后裁决挂链）。
#
# 2026-10-13 新增 zhabanLabel 步（用户裁决，relay 叙事炸板归因缺口补全）：当日 THS 炸板池
#   逐股单题打标（jev_zhaban_label --zhaban-day，池峰值 ~40 只串行，幂等 status=ok 跳过）。
#   2026-10-15 修链序：zhabanLabel 必须排在 relayIndex 之前——relay 叙事「今日炸板面」段
#   消费当日归因打标（hotlist_jev_zhaban_labels），反序则当日归因永远赶不上叙事组装
#   （10-14/10-15 实证：relay 16:18-16:27 出数、归因 16:20-16:36 才落库，叙事恒写
#   「未覆盖（0/N，归因证据缺失）」）。
#
# 2026-10-19 新增 relayBand 步（用户裁决 A+A1：分带表零人工挂链）：relayIndex 之后，重算
#   分带实测表 data/backups/relay-band-table.json（页面【分带观察】读数）。**零模型调用**
#   （只读 Mongo + 本地通达信全历史，实测 5–9 分钟）。门控自愈式：产物 window.end < 最新
#   ok 判定日才重算（已覆盖当天零成本跳过）；门控查询失败按 skipped 处理（与兄弟 advisory 步
#   一致，不同 fail-open——此时子进程读 Mongo 也会失败）。产物写临时文件、成功退出后原子替换
#   ——刷新期间旧表完整可读；A1 策略=全窗就地重建，审计靠产物 generatedAt/relayGeneration/provenance。
#   advisory 语义（失败不翻转整体 ok）。
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
$trigger = New-ScheduledTaskTrigger -Daily -At 17:00
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
    -Description 'QuantBoard 盘后链（17:00，含 jiuyan 名单一致性预检）：热榜情绪计算 + MongoDB 备份（交易日 light / 周五 full，含 verify/prune/周五 R2 push）+ 四类型快照 R2 日归档 + 涨停/炸板打标 + 分带表重算（零模型调用）+ 脉拍等 advisory 步' `
    | Out-Null

Write-Host "registered task '$taskName'"
Write-Host "  action : $pythonExe -m backend.cli after-market-once"
Write-Host "  workdir: $quantBoardRoot"
Write-Host "  trigger: daily 17:00 (StartWhenAvailable, 电池/错过窗口补跑)"
