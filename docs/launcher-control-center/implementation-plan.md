# Dragon Board Launcher Control Center — 整改实施计划

> 状态：2026-08-05 起草，待评审。目标架构见 `design.md`（已重写为现状基线 + 目标架构）。
> 本文按 P0/P1/P2 拆分，每项含影响文件、验证命令与验收口径。评审通过后按阶段实施，
> 每阶段独立可验证、可回退。**不进入大规模实现，直到本计划被确认。**
>
> **实施进度（2026-08-06）：P0（健康契约 + 防风暴 + 内核抽取）、P1（services.json 外置 +
> DesiredState + 双进程适配）、P2（日志策略配置化 + 管道异步化 + 内核单测 24 个 + 文档同步）
> 均已实施并验证。剩余可选项见"未决问题"。

## 阶段总览

| 阶段 | 主题 | 目标 | 预估影响 |
|---|---|---|---|
| P0 | 健康契约 + 重启防风暴 + 内核/UI 解耦 | 根治 2026-08-05 锁风暴事故根因，让编排逻辑可测试 | 启动器 Core/ 新增；collector_main/main health 契约；api-cli.md |
| P1 | 服务定义外置 + DesiredState + 依赖图 | 消灭硬编码与"端口占用即强杀"边界，支持按需恢复 | services.json；LauncherServices 改造；state.json |
| P2 | 日志策略配置化 + 测试补全 + 文档同步 | 消除日志管道阻塞风险，建立回归防线 | 日志层改造；Tests 源码；design/README 同步 |

---

## P0 — 健康契约 + 重启防风暴 + 内核/UI 解耦

### P0.1 后端健康契约化

- **目标**：8001 `/api/health` 与 8000 `/api/health` 统一返回
  `{status, restartable, recommendedAction, reason, detail}`；锁冲突返回 `restartable=false, action=wait`。
- **影响文件**：
  - `quant-board/backend/collector_main.py`（health 端点改造）
  - `quant-board/backend/main.py`（8000 health 对齐，`snapshotCollector` 状态块兼容保留）
  - `quant-board/docs/api-cli.md`（新增 health 契约章节）
  - `quant-board/tests/test_snapshot_collector_health.py`（新增契约断言）
- **验证**：
  ```powershell
  cd quant-board
  .\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_health.py tests/test_snapshot_collector_api.py -q
  ```
- **验收**：锁冲突时 health 明确 `restartable=false/recommendedAction=wait`；数据源失败 `action=alert`；调度器停摆 `action=restart`。

### P0.2 启动器编排内核抽取（Core/）

- **目标**：新建 `tools/DragonBoardLauncher/Core/`，把 `LauncherForm.cs` 中的重启决策、健康轮询调度、
  状态管理抽到无 UI 依赖的内核；`LauncherForm` 只订阅事件渲染。
- **影响文件**：
  - 新增 `Core/ServiceDefinition.cs`、`Core/ServiceStateMachine.cs`、`Core/Orchestrator.cs`、
    `Core/HealthProbe.cs`、`Core/ProcessSupervisor.cs`
  - 改 `LauncherForm.cs`（变薄：只保留 UI/托盘/日志订阅）
  - 改 `LauncherProcessManager.cs`（拆分到 ProcessSupervisor/Orchestrator）
  - `SnapshotCollectorProbe.cs` 改为消费 P0.1 契约（不再解析 enabled/running/last_error 猜语义）
- **验证**：
  ```powershell
  dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
  ```
- **验收**：编译通过；启动器行为与现状等价（除重启决策输入改为契约字段）。

### P0.3 重启策略内核化（防风暴）

- **目标**：指数退避 + 冷却 + 最大次数 + 防风暴锁；决策输入 = 后端 `restartable/recommendedAction`。
- **影响文件**：`Core/Orchestrator.cs`（新增）、`LauncherForm.cs`（移除 EnsureHealthy 内联逻辑）
- **验证**：`dotnet build` + 手工：锁冲突时不杀不重启；连续失败进入冷却。
- **验收**：2026-08-05 场景（探针误判→强杀→锁残留）不再复现；`last_error` 类软故障只 alert 不重启。

---

## P1 — 服务定义外置 + DesiredState + 依赖图

### P1.1 services.json 外置服务定义

- **目标**：服务元数据从 `LauncherServices.cs` 移到 `config/services.json`，支持 `${repoRoot}` 变量插值、
  `externalPolicy: managed|reuse|refuse`、每服务 `logPolicy`/`restart`。
- **影响文件**：
  - 新增 `config/services.json`
  - 改 `LauncherServices.cs`（改为加载配置 + 默认值回退）
  - 改 `ManagedService.cs`（加 externalPolicy/logPolicy/restart 字段）
- **验证**：`dotnet build` + 启动器正常列出 9 服务 + 2 辅助进程。
- **验收**：Redis 为 `reuse`；Mongo/未知进程为 `refuse`（占用只显示 PID，不 taskkill）；路径无 `D:\APP_SOFT` 硬编码。

### P1.2 DesiredState 持久化

- **目标**：用户启停偏好持久化，launcher 重启按上次状态恢复；修复 3.2 阶段命名错位。
- **影响文件**：
  - 新增 `state.json` 读写（`%LOCALAPPDATA%\DragonBoardLauncher\state.json`）
  - 改 `Core/Orchestrator.cs`（按 DesiredState 恢复）
  - 改 `LauncherServices.cs`（修正 stageNames 与 CoreStartupStages 命名错位，或改依赖图）
- **验证**：手动停 frontend → 重启 launcher → frontend 保持停止。
- **验收**：`StartAll` 走依赖图 DAG；`StopAll` 按逆序；阶段命名与实际服务一致。

---

## P2 — 日志策略配置化 + 测试补全 + 文档同步

### P2.1 日志/管道改造

- **目标**：每服务日志策略进 services.json（`level/suppressHealth`）；Process 输出回调改异步队列。
- **影响文件**：
  - 改 `LauncherProcessManager.cs`（输出回调异步化）
  - 改 `LogFile.cs`（事件驱动，保留轮转 + gzip）
  - `config/services.json`（每服务 logPolicy）
- **验证**：`dotnet build`；高吞吐下启动器 UI 不卡顿、日志不丢行。
- **验收**：proxy 每请求行、uvicorn 访问日志按策略过滤；错误/警告永不丢；管道不阻塞子进程。

### P2.2 测试补全（内核单测）

- **目标**：给 Orchestrator/StateMachine/重启策略/DesiredState 写单测（fake probe/process），补齐
  `DragonBoardLauncher.Tests` 源码。
- **影响文件**：`tools/DragonBoardLauncher.Tests/**`（新增测试源码 + csproj 引用 Core）
- **验证**：
  ```powershell
  dotnet test tools\DragonBoardLauncher.Tests\DragonBoardLauncher.Tests.csproj
  ```
- **验收**：覆盖：锁冲突不重启、软故障只 alert、指数退避、DesiredState 恢复、外部进程 refuse 策略。

### P2.3 文档同步

- **目标**：`docs/launcher-control-center/design.md` 保持为现状基线；`tools/DragonBoardLauncher/README.md`
  补日志/配置说明；`quant-board/docs/api-cli.md` 已含 health 契约（P0.1）。
- **影响文件**：`docs/launcher-control-center/design.md`、`tools/DragonBoardLauncher/README.md`
- **验收**：文档与代码口径一致，无过期描述。

---

## 未决问题（评审时确认）

1. **服务定义配置位置**：`config/services.json`（仓库内，随代码走）还是用户级（`%LOCALAPPDATA%`）？
   建议仓库内 + 允许本地覆盖。
2. **Mongo 外部策略**：现为"端口占用→taskkill"。改为 `refuse` 后，用户手动起的 mongod 将不被杀；
   但 launcher 托管的 mongod 需要 tracked-PID 匹配才能停。是否接受？（建议接受，符合 Safety 原则）
3. **P2 子项目源头精简**（uvicorn --no-access-log、proxy 日志降级、行情桥 WARNING 节流）是否纳入本计划，
   还是另立任务？**（2026-08-06 已实施 uvicorn --no-access-log，8000/8001 启动参数与文档命令同步；
   proxy 日志降级与行情桥 WARNING 节流仍为可选项）**
4. **state.json 存放位置**：`%LOCALAPPDATA%`（用户态，跨仓库安全）还是仓库 `.local`（随项目，便于备份）？

## 评审记录

| 日期 | 结论 |
|---|---|
| 2026-08-05 | 起草，待评审 |
| 2026-08-06 | P0/P1/P2 全部实施验证：健康契约、防风暴重启、双进程适配、日志策略配置化、管道异步化、24 个内核单测、文档同步 |
| 2026-08-06 | 可选项补充：uvicorn `--no-access-log` 源头精简已实施（services.json + 文档命令同步，提交 6098749 后追加） |
