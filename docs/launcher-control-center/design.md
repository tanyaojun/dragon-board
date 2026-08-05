# Dragon Board Launcher Control Center Design

> 状态：2026-08-05 重写。原 design.md 为早期 6 服务版本（Redis 走 Windows Service、右侧停靠、热键），
> 与现状严重脱节，已作废。本文为**现状基线 + 目标架构**，实施进度见 `implementation-plan.md`。

## 1. Goal

把现有 WinForms 启动器升级为 Dragon Board 本地服务编排内核：统一监控 Redis、MongoDB、Proxy、
Frontend、Python Bridge、QuantBoard API、Snapshot Collector、QuantBoard UI 和 VoiceWorker 的
进程生命周期、健康状态与自动恢复；消除"端口占用即强杀"的误伤与"探针误判→锁残留→重启风暴"
类事故（见 2026-08-05 复盘）；让编排逻辑可测试、可配置、可审计。

## 2. Scope

- 保留 `tools/DragonBoardLauncher` WinForms/.NET 8 工程，不引入 WPF/Electron/WebView。
- 不动 Dragon Board 前端、QuantBoard 后端业务、Redis/MongoDB 数据与配置。
- 仅新增/调整：启动器编排内核与 UI、后端 health 契约字段（collector_main / main）、服务定义配置、文档。

## 3. 现状基线（2026-08-05 事实）

### 3.1 服务矩阵（`LauncherServices.cs` 硬编码）

| key | 名称 | 端口 | 启动方式 | 依赖 | 外部进程策略 |
|---|---|---|---|---|---|
| mongo | MongoDB 数据库 | 27017 | `D:\APP_SOFT\MongoDB\bin\mongod.exe` | — | 端口占用→taskkill |
| redis | Redis 缓存 | 6379 | `D:\APP_SOFT\redis\Redis-8.10.0\redis-server.exe redis.conf` | — | 外部实例复用；停止 redis-cli→sc→taskkill |
| proxy | 本地代理服务 | 3000 | `node server.js`（proxy-server） | node_modules、.env.local、8000(转发时) | managed |
| bridge | 通达信行情桥 | 8765 | `python python-bridge/main.py` | mootdx | managed，LogOnlyErrors |
| collector | 快照采集服务 | 8001 | venv `python -m uvicorn backend.collector_main:app` | MongoDB、Redis 锁、proxy(3000 startup-bundle)、bridge(日历) | managed + Redis 单实例锁 |
| quant-api | 量化后端 API | 8000 | venv `python -m uvicorn backend.main:app` | MongoDB、Redis | managed |
| frontend | 龙头看板前端 | 5173 | `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173` | proxy | managed |
| quant-ui | 量化面板前端 | 5174 | `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174` | 8000 | managed |
| voice | 本地语音服务 | 32145 | `tools/VoiceWorker/bin/Release/.../VoiceWorker.exe` 或 `dotnet run` | `.env.local`（launcher 注入） | managed + 探针优雅停止 |

辅助进程：Mongo Express (8081)、Redis Commander (8082)，按需启动。

### 3.2 启动链（`LauncherProcessManager.StartAll`）

4 阶段：`mongo+redis` → `proxy+bridge` → `quant-api` → `collector`；每阶段 30s 就绪检查，失败中止下游。
前端/量化面板/语音按需启动。

**已知命名混乱**：`stageNames` = [基础设施, 实时数据源, 快照采集, 量化后端]，但 `CoreStartupStages` =
[["mongo","redis"],["proxy","bridge"],["quant-api"],["collector"]] —— 阶段 3 是 quant-api 却叫"快照采集"，
阶段 4 是 collector 却叫"量化后端"，名实不符。

### 3.3 健康检查与自动重启

- UI 每 3s `RefreshStatusesAsync`：全部服务端口探测（`LauncherPorts.IsPortOpen`）+ collector 额外 `SnapshotCollectorProbe.GetHealthAsync`。
- collector 自动重启（`EnsureHealthy`）：60s 冷却 + 连续 3 次上限；端口占用且不健康→先停再启。
- `SnapshotCollectorProbe` 解析 8001 `/api/health` 的 `snapshotCollector` 字段（enabled/running/last_error）
  自行判定 hard（可重启）与 warning（Restartable=false，不重启）。fingerprint 字符串为 C# 私有约定。

### 3.4 日志

- `LogFile.cs`：按天分文件 `logs\launcher\launcher-YYYY-MM-dd.log`，10MB 轮转 gzip（`launcher-YYYY-MM-dd.N.log.gz`），30 天清理。
- 子进程输出过滤 `ShouldSuppressChildOutput`：uvicorn 访问日志行 + proxy 每请求行；`LooksLikeErrorOutput` 保底错误/警告不丢。
- bridge 用 `LogOnlyErrors`（stdout 全忽略）。
- UI 展示 `ShouldShowLog` 关键词过滤 + `BoundedLogView` 300 行/600 字符截断。

### 3.5 代码结构（现状）

```
tools/DragonBoardLauncher/
├── Program.cs                    # Mutex 单实例入口
├── LauncherForm.cs               # UI + 健康轮询 + 重启决策 + 告警指纹去重 + 日志（职责过重）
├── LauncherProcessManager.cs     # 进程生命周期、端口/孤儿处理、Redis/VoiceWorker 特殊分支
├── LauncherServices.cs           # 9 服务元数据 + 启动阶段（硬编码）
├── ManagedService.cs             # 服务模型
├── SnapshotCollectorProbe.cs     # 解析后端 health JSON，hard/warning 分类
├── VoiceWorkerProbe.cs           # voice health/shutdown
├── LogFile.cs                    # 落盘 + 轮转 + gzip
├── LauncherPorts.cs              # 端口/PID 探测（netstat）
├── BoundedLogView.cs / EnvFileLoader.cs / ProjectRootLocator.cs
└── DragonBoardLauncher.Tests/    # 有壳无源码（仅编译产物）
```

## 4. 问题诊断

### P0-1 编排内核与 WinForms UI 深度耦合，决策逻辑无法测试
`LauncherForm.cs` 同时承载：3s 轮询调度、`EnsureHealthy` 重启判定、`ReportCollectorHealth` 指纹去重、
按钮联动、托盘、日志。重启策略埋在 Form，`DragonBoardLauncher.Tests` 无源码。2026-08-05 锁风暴
（探针误判→强杀→锁残留→重启循环）无法靠现有结构加测试预防。

### P0-2 健康检查是"跨语言猜语义"，契约无定义
C# 解析 8001 health 的 `snapshotCollector` 字段自行分类，fingerprint（`hard:...`/`warn:...`）是 C# 私有约定，
Python 侧不知情。已漂移实例：`instance_lock.py` docstring 仍写"8000 与 8001 竞争同一把锁"，实际 `main.py`
已不抢锁。后端字段改动时启动器静默失效。

### P0-3 服务元数据硬编码 + 外部进程边界不统一
路径（`D:\APP_SOFT\...`、venv）、参数、阶段全在 C# 源码，调整要重编译。端口占用处理：Redis 复用、
Mongo 杀、未知进程强杀——与早期 design.md Safety 承诺（"外部占用只显示 PID 不杀"）不一致。

### P1-4 重启策略仍可能引发风暴
`last_error`（数据源暂时失败）也走"先杀再启"，而 8001 启动失败主因是 Redis 锁（等 TTL 即可），杀进程
解决不了。`restartable / recommendedAction` 应由后端健康端点契约化返回。

### P1-5 无 DesiredState 持久化
用户手动停掉某服务后，launcher 重启又无条件 `StartAll`；重启计数/冷却全内存态。

### P1-6 文档与现状脱节
`docs/launcher-control-center/design.md` 仍是早期 6 服务版（Redis 走 Windows Service、右侧停靠、热键），
不是现状基线，误导后续开发。

### P2-7 日志/管道策略散落
`LooksLikeErrorOutput`、`ShouldShowLog`、`LogOnlyErrors` 三个分散启发式；proxy 每请求一行 stdout 在
Process 事件回调里同步 `_log`，高吞吐有阻塞管道风险（行情桥 partial-data WARNING 每秒 1 条仍在落盘）。

## 5. 目标架构

```
tools/DragonBoardLauncher/
├── Core/                        # 新编排内核（纯 C#，无 WinForms 依赖，可单测）
│   ├── ServiceDefinition.cs     # 服务元数据模型（从配置加载，含 externalPolicy/logPolicy/restart）
│   ├── ServiceStateMachine.cs   # Stopped→Starting→Running→Degraded→Stopping
│   ├── Orchestrator.cs          # 依赖图启动/停止、DesiredState、防风暴重启
│   ├── HealthProbe.cs           # 消费后端契约化 health（http/port/collector/voice 探针）
│   └── ProcessSupervisor.cs     # 进程拉起/托管/孤儿识别（tracked PID 匹配）
├── Ui/                          # 薄 WinForms：卡片渲染、托盘、日志展示（只订阅内核事件）
├── config/services.json         # 服务元数据外置（路径/参数/端口/依赖/外部策略/日志策略）
├── LogFile.cs                   # 保留（已加轮转+压缩），改为事件驱动异步写
└── DragonBoardLauncher.Tests/   # 补齐内核单测源码
```

### 5.1 健康契约（后端与启动器唯一约定）

`quant-board/backend/collector_main.py` 与 `backend/main.py` 的 `/api/health` 统一返回：

```json
{
  "status": "ok" | "degraded" | "error",
  "restartable": true | false,
  "recommendedAction": "none" | "restart" | "wait" | "alert",
  "reason": "human readable reason",
  "detail": {}
}
```

- 锁冲突/启动预热等场景：`restartable=false, recommendedAction=wait`（等 TTL 过期），启动器不杀不重启。
- 数据源暂时失败（last_error 类）：`restartable=false, recommendedAction=alert`，启动器只记录不杀。
- 调度器真正停摆：`restartable=true, recommendedAction=restart`。
- C# 侧只消费该结构，不再解析 enabled/running/last_error 猜语义；fingerprint 改为契约字段。
- 契约写入 `quant-board/docs/api-cli.md`。

### 5.2 重启策略（内核化）

- 指数退避（1s→2s→4s→8s→上限 60s）+ 冷却 + 最大连续次数（可配置）。
- 决策输入 = 后端 `restartable + recommendedAction`，不是 C# 猜。
- 防风暴锁：同一服务同一时刻至多一个重启任务；全局重启速率限制（如 1 次/10s 跨服务）。

### 5.3 服务定义外置（services.json）

```json
{
  "key": "collector",
  "name": "快照采集服务",
  "port": 8001,
  "workingDirectory": "${repoRoot}/quant-board",
  "fileName": "${repoRoot}/quant-board/.venv/Scripts/python.exe",
  "arguments": "-m uvicorn backend.collector_main:app --host 127.0.0.1 --port 8001 --no-access-log",
  "fallbackFileName": "python",
  "stage": "core",
  "dependencies": ["mongo", "redis", "proxy", "bridge"],
  "externalPolicy": "managed",
  "healthProbe": { "type": "http", "uri": "http://127.0.0.1:8001/api/health", "timeoutMs": 10000 },
  "logPolicy": { "level": "filter-access", "suppressHealth": true },
  "restart": { "maxConsecutive": 3, "cooldownSeconds": 60 }
}
```

- `externalPolicy`: `managed`（launcher 拉起并托管）| `reuse`（外部实例直接复用，如 Redis）| `refuse`（发现占用只显示 PID 不杀）。
- 变量插值 `${repoRoot}` 等，消除 `D:\APP_SOFT\...` 硬编码。
- `LauncherServices.Create` 改为"加载 services.json + 默认值回退"。

### 5.4 DesiredState 持久化

- 用户启停偏好写入 `%LOCALAPPDATA%\DragonBoardLauncher\state.json`（或仓库 `.local`），launcher 重启按上次状态恢复。
- `StartAll` 改依赖图 DAG 启动（mongo/redis → proxy/bridge → quant-api → collector；frontend/quant-ui/voice 按需），
  `StopAll` 按依赖逆序。
- 修复 3.2 阶段命名错位。

### 5.5 日志/管道

- 每服务日志策略进 services.json：`level: all | errors-only | filter-access`、`suppressHealth`。
- Process 输出回调改异步队列（Channel/BlockingCollection），避免同步 `_log` 阻塞管道。
- 保留 LogFile 轮转 + gzip；UI 只订阅日志事件流。
- 子项目源头精简（2026-08-06 已实施）：uvicorn 启动参数加 `--no-access-log`（8000/8001，launcher services.json + 文档命令同步）；proxy 请求日志只保留非 2xx、行情桥 partial-data WARNING 节流仍为可选项。

## 6. 验证命令

```powershell
# 启动器
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
dotnet test tools\DragonBoardLauncher.Tests\DragonBoardLauncher.Tests.csproj

# QuantBoard 后端（健康契约改动后）
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_health.py tests/test_snapshot_collector_api.py -q

# 手工验收
# 1) collector 锁冲突时 health 返回 restartable=false/action=wait，启动器不杀进程不重启；
# 2) 手动停 frontend 后重启 launcher，DesiredState 恢复（frontend 不自动拉起）；
# 3) 外部进程占用 27017 时只显示 PID，不 taskkill。
```

## 7. 非目标 / 边界

- 不改 RankTrend golden、快照入库口径、回测/优化逻辑。
- 不引入新框架或大型依赖。
- 不把回测/优化职责搬进启动器。
- Redis/MongoDB 数据与配置不动；仅调整"启动器如何管理它们"的边界策略。
