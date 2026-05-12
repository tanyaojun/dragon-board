# Dragon Board Launcher Control Center Design

## Goal

把现有 WinForms 启动器升级为 Dragon Board 本地服务控制中心，统一监控 Redis、Proxy、Dragon Board 前端、Python Bridge、QuantBoard API 和 QuantBoard UI。

## Scope

- 保留 `tools/DragonBoardLauncher` WinForms/.NET 8 工程。
- 不引入 WPF、Electron 或 WebView。
- 不改 Dragon Board 前端、QuantBoard 后端和 Redis 配置。
- 关闭窗口默认最小化到托盘，显式退出才关闭启动器。

## Services

| 服务 | 端口 | 类型 | 启动方式 |
|---|---:|---|---|
| Redis | 6379 | Windows Service | `sc start Redis` / `sc stop Redis` |
| DragonBoard Proxy | 3000 | Process | `node server.js` |
| DragonBoard Frontend | 5173 | Process | `npm run dev -- --host 127.0.0.1` |
| Python Bridge | 8765 | Process | `python python-bridge/main.py` |
| QuantBoard API | 8000 | Process | `.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` |
| QuantBoard UI | 5174 | Process | `npm run dev -- --host 127.0.0.1 --port 5174` |

## UI

- 右下角贴边打开，窗口尺寸约 `520x680`。
- 深色控制台风格，服务使用卡片行展示。
- 顶部显示整体健康摘要，例如 `Core 5/6 Online`。
- 服务卡片显示名称、端口、PID、状态和操作按钮。
- 底部保留最近日志。
- 托盘图标常驻，双击显示或隐藏。
- 全局快捷键 `Ctrl + Alt + D` 显示或隐藏窗口。
- 失焦后如果贴近右边缘，自动收起成窄条；鼠标移入自动展开。

## Actions

- `Start Core`：启动 Redis、Proxy、Frontend、Bridge、Quant API。
- `Start All`：启动全部服务。
- `Stop Managed`：停止启动器自己拉起的进程，不杀外部进程。
- `Health Check`：刷新端口、PID、Redis 服务和 Quant API cache 状态。
- `Auto Start`：切换当前用户 Windows 登录自启动。
- `Open Board`：打开 `http://127.0.0.1:5173`。
- `Open Quant`：打开 `http://127.0.0.1:5174`。

## Safety

- Redis 使用 Windows 服务命令控制，不通过端口 PID kill。
- 普通进程停止时优先停止当前启动器拉起的 process tree。
- 对外部占用端口只显示 PID 和进程名，不默认杀掉。
- 全局热键注册失败只记录日志，不影响启动器使用。

## Validation

- `dotnet build tools/DragonBoardLauncher/DragonBoardLauncher.csproj`
- 手工检查：
  - Redis 状态显示正确。
  - `Ctrl+Alt+D` 可显示/隐藏。
  - 关闭窗口进入托盘。
  - 自启动开关可写入/删除 HKCU Run。
  - 六个服务端口状态和 PID 显示正确。
