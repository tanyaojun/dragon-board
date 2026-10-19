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

## 服务定义与启停偏好

- 服务定义外置在 `config/services.json`（P1.1）：路径/参数/端口/依赖顺序/`externalPolicy`
  （`managed` 托管清理 / `reuse` 复用外部实例如 Redis / `refuse` 只提示不清理如 MongoDB）。
  文件缺失或解析失败时回退内嵌默认，不影响启动。
- 用户启停偏好持久化到 `%LOCALAPPDATA%\DragonBoardLauncher\state.json`（P1.2）：
  launcher 重启后核心服务始终随 StartAll 启动，展示/辅助服务（前端/量化面板/语音）
  按上次偏好恢复；手动停止的服务不会被无条件重新拉起。
- 阶段名与 `services.json` stages 顺序一致：基础设施 → 实时数据源 → 量化后端 → 快照采集。

## 日志策略（P2.1）

- 每服务日志策略在 `config/services.json` 的 `logPolicy` 配置（`level`：`all` / `errors-only` /
  `filter-access`；`suppressHealth`：是否抑制健康检查行）。缺省按旧 `logOnlyErrors` 字段兜底。
  - `errors-only`：stdout 全忽略，仅错误/警告落盘（如行情桥的 INFO 轮询噪音）；
  - `filter-access`：过滤 uvicorn 访问日志行与 proxy 每请求行（默认服务用）；
  - `all`：全量落盘（Mongo/Redis 等低频服务）。
- 子进程输出经**异步队列**消费（P2.1b）：输出回调只入队，后台线程批量写日志文件，
  高吞吐 stdout/stderr 不阻塞子进程管道；launcher 退出时刷完队列剩余行。
- 落盘仍按天分文件 + 10MB 轮转 gzip + 30 天清理（`LogFile.cs`）。

## 操作按钮

顶部按钮栏与托盘菜单：

- **核心启动**：按依赖顺序启动核心服务（Mongo/Redis → 代理/行情桥 → Quant API → 采集），并清除"手动停止"标记。
- **全部停止**：停止全部服务，并把全部服务标记为"手动停止"，避免轮询自动重启拉起。
- **全部重启**：先停止全部，再启动核心并恢复上次偏好的展示/辅助服务（等价"全部停止 + 核心启动 + 恢复偏好"）。
- **打开看板 / 打开量化**：打开 Dragon Board（5173）/ QuantBoard（5174）页面。
- **自启**：切换开机自启动。
- 每个服务卡片右侧有单服务"启动/停止"按钮；单服务停止同样标记"手动停止"。

## 核心启动顺序

启动管理器会按依赖分阶段自动启动核心服务。每个阶段必须通过就绪检查，才会启动下一阶段：

1. `27017` MongoDB、`6379` Redis：持久化和缓存基础设施，最先启动。
2. `3000` 本地代理、`8765` 行情桥：快照采集的数据源，随后启动，并分别检查 `/health`。
3. `8000` Quant API：先启动，只提供业务 API 与回测，不再启动采集 scheduler。
4. `8001` 快照采集服务：后启动，独立进程 `backend.collector_main:app`，是快照采集唯一生产者；以
   `/api/health` 健康契约（`status/restartable/recommendedAction/reason`）判活，不再解析内部字段猜语义。
   进程内直连行情/热榜/涨停池服务，不依赖 Quant API；Redis 单实例锁
   （`snapshot-collector:instance-lock:<dataset>`，值为 `v2:<token>:<pid>:<进程创建时间>`）防止重复实例：
   持有者已终止（退出码判定）或 PID 被复用（创建时间比对）时残留锁会被原子清理重抢。

   采集健康探针区分硬故障与业务进度提示：HTTP 异常、调度器未启用/未运行、最近异常属于硬故障，
   会自动重启；盘中长时间未采集、收盘仍无采集记录属于业务进度提示，只展示并记录日志，不触发
   自动重启（漏槽是数据可用性问题，重启无法补采，反而可能引发锁竞争和重启风暴）。

   存活判定以 HTTP 健康契约为准（2026-10-19 复盘）：端口探测（netstat/TCP 表 + 500ms 连接回退）
   在 TCP 表损坏时会对活着的 8001 连续假阴性，只要能拿到服务自报状态就按运行中处理，绝不因端口
   探测失败对健康实例做停启式重启。

`5173` 龙头看板、`5174` 量化面板和 `32145` 本地语音属于展示或辅助服务，最后按需手动启动，不影响快照调度。`8081` Mongo Express、`8082` Redis Commander 仅在打开数据库/缓存管理页时启动，也不进入核心启动链。

## 服务存活判定（通用，2026-10-19 复盘）

除 8001 走健康契约外，其余服务的存活判定统一为"快速端口探测 + 强证据深探测复核"（`Core/ServiceLivenessResolver.cs`）：

1. 快速探测（TCP 表命中 / 5173、5174 的 500ms 连接）说在跑 → 在跑；
2. 说没跑，但存在"本该在跑"的强证据（跟踪的子进程仍存活，或本会话曾观察到它在跑）→ 用 2s 超时做一次深探测复核；
3. 深探测也失败才认死，并清掉"曾观察到在跑"，后续轮询回到快速路径（不给真正的冷启动加延迟）。

为什么必须复核：`IsPortOpen` 是启发式（TCP 表 + 500ms 连接）。机器负载高、Windows TCP 表损坏（LISTENING 行缺失）或服务事件循环被同步长任务堵住（accept 队列不消费）时，活着的服务会被连续判成"已停止"，表现为盘中状态红点/在线数抖动、3 秒后又自己变"运行中"（用户反馈的"掉线又自动恢复"）；更重的后果是假阴性让"启动"按钮变可点，点下去时服务其实活着 → 新实例绑不上端口 → `[Errno 10048]` 自杀（2026-10-14 13:37:26 量化后端 API 实证）。

配套可观测性：

- 服务状态跳变（运行中↔已停止）会写入启动器日志（此前完全无痕，"掉线又自动恢复"无法取证）；
- 子进程退出日志现在带退出码并区分"管理器主动停止"与"未请求停止（自行结束/被外部杀）"（2026-10-12 09:23、10-13 13:20、10-18 10:53 三例旧日志无法归因）。

注意：启动器只对 8001（健康契约）与 MongoDB/Redis（可达性）做自动拉起；3000/8000/8008/32145/5173/5174 的**真实退出不会自动重启**（只在启动器启动时按上次的启用集恢复），需要人工点"启动"或重启管理器。

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
