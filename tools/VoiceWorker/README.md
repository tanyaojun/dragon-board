# VoiceWorker

Dragon Board 本地常驻语音进程，用于热榜异动播报。它不依赖 PowerShell，默认使用 Windows `System.Speech.Synthesis.SpeechSynthesizer` 发声，也可以配置火山引擎豆包语音优先播报，并在云端失败时回退本地语音。

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

`proxy-server` 会把 `/api/local-voice/*` 转发到该进程。VoiceWorker 离线时，前端不会再降级到浏览器语音。

## 火山引擎豆包语音

先在火山引擎控制台开通豆包语音合成大模型，并取得 AppID、Access Key、Resource ID 和声音 ID。免费试用额度以控制台显示为准，代码不会内置任何免费密钥。

```powershell
$env:VOICE_ENGINE='volcengine'
$env:VOLC_TTS_APP_ID='你的 AppID'
$env:VOLC_TTS_ACCESS_KEY='你的 Access Key'
$env:VOLC_TTS_RESOURCE_ID='该服务的 Resource ID'
$env:VOLC_TTS_VOICE_TYPE='声音 ID，例如 S_7BMNX9V22'
dotnet run --project tools\VoiceWorker\VoiceWorker.csproj
```

可选：

```powershell
$env:VOLC_TTS_ENDPOINT='https://openspeech.bytedance.com/api/v3/tts/unidirectional'
$env:VOLC_TTS_SPEECH_RATE='-20'
$env:VOLC_TTS_LOUDNESS_RATE='20'
```

`VOICE_ENGINE` 不设置或不是 `volcengine` 时，VoiceWorker 使用本地 SAPI。设置为 `volcengine` 但缺少密钥时，会直接使用本地 SAPI 兜底。

兼容旧变量名：`VOLC_TTS_ACCESS_TOKEN` 仍可作为 `VOLC_TTS_ACCESS_KEY` 使用。`VOLC_TTS_CLUSTER` 是旧 V1 接口字段，V3 接口不再使用。

## 验证

```powershell
dotnet build tools\VoiceWorker\VoiceWorker.csproj -c Debug
```
