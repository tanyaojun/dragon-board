# -*- coding: utf-8 -*-
# QuantBoard 服务一键启动（幂等：端口已监听则跳过）。
# 登录自启：schtasks /tn DragonBoard-Services（onlogon）。
# 手动：powershell -ExecutionPolicy Bypass -File scripts\start_relay_services.ps1

$py = "D:\dragon-board\quant-board\.venv\Scripts\python.exe"
$wd = "D:\dragon-board\quant-board"

function Test-Port($port) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false }
}

function Start-ServiceIfDown($port, $name, $argList) {
    if (Test-Port $port) {
        Write-Host "[skip] $name :$port 已在运行"
    } else {
        Write-Host "[start] $name :$port ..."
        Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $wd -WindowStyle Hidden
    }
}

Start-ServiceIfDown 8000 "backend-main" @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000','--no-access-log')
Start-ServiceIfDown 8001 "collector" @('-m','uvicorn','backend.collector_main:app','--host','127.0.0.1','--port','8001')
Start-ServiceIfDown 8008 "relay-page" @('-m','uvicorn','backend.serve_relay_page:app','--host','127.0.0.1','--port','8008')

# 等待就绪并回显状态
Start-Sleep -Seconds 6
foreach ($p in 8000, 8001, 8008) {
    $up = Test-Port $p
    Write-Host ("{0} -> {1}" -f $p, $(if ($up) { "UP" } else { "DOWN（10s 后复检一次）" }))
    if (-not $up) { Start-Sleep -Seconds 10 }
}
