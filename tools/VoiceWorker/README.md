# VoiceWorker

Dragon Board 本地常驻语音进程，用于热榜异动播报。它不依赖 PowerShell，使用 Windows `System.Speech.Synthesis.SpeechSynthesizer` 发声。

## 启动

```powershell
dotnet run --project tools\VoiceWorker\VoiceWorker.csproj
```

默认监听：

```text
http://127.0.0.1:32145/
```

可通过环境变量或参数修改：

```powershell
$env:VOICE_WORKER_URL='http://127.0.0.1:32145/'
dotnet run --project tools\VoiceWorker\VoiceWorker.csproj

dotnet run --project tools\VoiceWorker\VoiceWorker.csproj -- --url=http://127.0.0.1:32145/
```

## 接口

- `GET /health`
- `GET /status`
- `POST /speak`，请求体：`{"text":"中南文化即将打开涨停"}`
- `POST /test`
- `POST /stop`

`proxy-server` 会把 `/api/local-voice/*` 转发到该进程。VoiceWorker 离线时，前端会降级到浏览器语音兜底。
