# DragonBoardLauncher 启动器

这是 Dragon Board 的 WinForms 启动管理器。目录管理目标是：开发者看源码清楚，普通用户双击入口清楚，不再从 `bin` 子目录里猜哪个 exe 最新。

## 用户入口

日常只认根目录这个文件为“最新可运行版本”：

```powershell
tools\DragonBoardLauncher\DragonBoardLauncher.exe
```

这个 exe 由 `RootSingleFile` 发布配置生成，是 framework-dependent 单文件发布产物。它不把 .NET 运行时打进 exe，体积较小，但要求本机已安装 .NET 8 Desktop Runtime。

用户不要进入 `bin`、`obj`、`publish` 目录寻找启动器。

## 目录规范

```text
tools\DragonBoardLauncher\
├── *.cs                         # WinForms 启动器源码
├── DragonBoardLauncher.csproj    # .NET 项目文件
├── DragonBoardLauncher.exe       # 用户双击入口，本地轻量发布产物，不提交 Git
├── Properties\PublishProfiles\   # 发布配置
├── bin\                          # dotnet build/publish 输出缓存，不手工管理
└── obj\                          # dotnet 中间缓存，不手工管理
```

管理规则：

- 根目录 `.cs` 文件和 `.csproj` 是源码，应该提交。
- `DragonBoardLauncher.exe` 是本地可运行产物，不提交 Git。
- `bin`、`obj` 只给 .NET 工具链使用，不作为用户入口，不手动挑选里面的 exe。
- 不把 `dll`、`deps.json`、`runtimeconfig.json` 这类生成物放回源码根目录。

## 开发验证

开发时仍然分别验证 Debug、Release 和最终发布，但只有最终发布会刷新根目录 exe：

```powershell
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Debug
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
dotnet publish tools\DragonBoardLauncher\DragonBoardLauncher.csproj -p:PublishProfile=RootSingleFile
```

## 核心启动顺序

启动管理器会按依赖分阶段自动启动核心服务。每个阶段必须通过就绪检查，才会启动下一阶段：

1. `27017` MongoDB、`6379` Redis：持久化和缓存基础设施，最先启动。
2. `3000` 本地代理、`8765` 行情桥：快照采集的数据源，随后启动，并分别检查 `/health`。
3. `8000` Quant API：最后启动核心服务；FastAPI startup 会在这里启动快照 scheduler，并检查 `/api/health` 中的启用状态、运行状态和轮询心跳。

`5173` 龙头看板、`5174` 量化面板和 `32145` 本地语音属于展示或辅助服务，最后按需手动启动，不影响快照调度。`8081` Mongo Express、`8082` Redis Commander 仅在打开数据库/缓存管理页时启动，也不进入核心启动链。

任一核心阶段在 30 秒内未就绪时，管理器会记录错误并停止启动下游，避免依赖尚未可用就启动 scheduler。

## 发布结论

发布完成后，只看这一处：

```powershell
tools\DragonBoardLauncher\DragonBoardLauncher.exe
```

如果 `bin\Release` 下同时出现 `net8.0-windows`、`publish` 或 `win-x64` 等目录，它们只是构建过程产物，不代表多个可选版本。

## 清理缓存

一般不需要手动删除 `bin` 或 `obj`。如果需要清理构建缓存，使用 .NET 清理命令，不要在资源管理器里手动挑文件：

```powershell
dotnet clean tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Debug
dotnet clean tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
```
