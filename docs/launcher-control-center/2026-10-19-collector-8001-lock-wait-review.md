# 2026-10-19 快照采集 8001「起不来」复盘（日志取证 + 修复）

> 对象：`logs/launcher/launcher-2026-10-19.log`（取证时 678 行 → 复看时已增长到 935 行，
> 11:02 又复现两例自杀）。
> 结论先行：8001 起不来**不是** 8001 自身启动失败，而是 launcher 误杀健康实例 +
> 残留锁判活不准 + 双实例竞争，最终等锁实例 `RuntimeError` 自杀并把 8001 标成"不可重启"。

## 1. 现象

- 当日日志尾部反复出现（10:53:23 / 11:02:23 / 11:02:38 共 3 例）：

  ```
  [快照采集服务] collector lock held elsewhere (attempt 32/32); retrying in 5s
  RuntimeError: another snapshot collector instance holds the lock for dataset
  dragonboard_live (remaining TTL 98s)
  ERROR:    Application startup failed. Exiting.
  ```

  `logs/collector-startup-failure.json` 被写成 `restartable=false /
  recommendedAction=wait`（新鲜窗口 10 分钟），期间 launcher 不会自动拉起采集。
- 当日 8001 被反复停启：10:30、10:41、10:50、10:59；每次都伴随 `collector lock held
  elsewhere` 重试串与"距上次启动不足 15s/重启冷却中"限流日志；11:03 launcher 全部停止后
  11:05:19 重启（Redis 一并重启），8001 于 11:05:47 干净拉起（锁 key 随 Redis 重启消失）。
- **当日 8 次停止的逐个归因**（`grep -n "已停止 快照采集服务 实际监听进程"`）：
  00:20:32 收盘后 StopAll；**10:30:06 唯一一次系统性误杀**（前置行
  `健康检查失败但端口 8001 仍被占用，先停止再重启` = EnsureHealthy 基于端口假阴性）；
  其余 6 次（10:41:32 / 10:47:46 / 10:50:34 / 10:59:33 / 11:03:42 / 11:08:41）
  均为人工"停止/全部停止"（前置行是 StopAll 或手动启动后的 `已在端口 8001 运行`）。
  即：掉线的**触发**只有 1 次系统性问题 + 7 次人工操作；
  掉线的**放大**全部来自强杀后的锁链缺陷（131 行等锁重试、3 次 RuntimeError 自杀）。

## 2. 证据时间线（关键行）

| 时间 | 证据 | 含义 |
|---|---|---|
| 06:57:31 | 8001 正常启动（PID 16412），此后 3.5 小时无重启 | 采集链本身健康 |
| 10:30:04 | `快照采集错误: 采集服务(8001)未运行` + `健康检查失败但端口 8001 仍被占用，先停止再重启` | **端口探测先判离线、同一轮 EnsureHealthy 又探测到占用**——同一探针数秒内自相矛盾 = 假阴性 |
| 10:30:04→10:30:22 | 杀掉健康实例 → 新实例 `attempt 1/32` 起等锁 | 强杀即锁残留 |
| 10:31:43 | 新实例拿到锁并 `Uvicorn running`（等待 ~78s） | 残留锁熬到了 TTL（120s）而非被判定清理 |
| 10:40:56~10:41:29 | 多次 `快照采集服务 已在端口 8001 运行` | 端口表（LISTENING 行）长期缺失，靠进程树回退跟踪 |
| 10:50:34 | 按钮停止实例（bootstrap 17240 / server 5752，日志无 EnsureHealthy 前置行） | launcher 日志 `已停止 … 实际监听进程` |
| 10:50:43 / 10:51:04 | **两个**等锁实例（server 5436 / 7092）各自 `attempt 1/32` | 强杀后 8001 无监听，两次启动请求都放行 → 双实例 |
| 10:51:58± | 实例 7092 在残留锁 TTL 自然到期后拿到锁并 serve 8001 | 残留锁从未被"死持有者"判定清掉 |
| 10:53:18 | 实例 5436 `attempt 32/32`（160s 预算耗尽） | 对手已持锁，自身重试必然失败 |
| 10:53:23 | `RuntimeError … remaining TTL 98s` + 写失败标记 + 退出 | 失败标记把 8001 降级为"等待"，10 分钟内不再自愈 |
| 10:57~10:59 | 7 次 `快照采集服务 已在端口 8001 运行`（重复启动请求被单实例挡下） | 端口表长期缺 LISTENING 行，跟踪靠进程树回退 |
| 10:59:33 | 再停实例 → 10:59:39 / 10:59:55 / 11:00:55 **三次**启动请求全部放行 | 等锁期不监听 8001，请求被逐个放行 |
| 11:01:03 | 11:00:55 那个实例（server 13812）拿到锁开始 serve | 又一个实例在 TTL 到期后取胜 |
| 11:02:23 / 11:02:38 | 另两个实例 `attempt 32/32` → `RuntimeError … TTL 100s / 84s` | 8001 正在服务，但日志里是两个"启动失败" |

`remaining TTL 98s` 是关键反证：等锁预算 160s > TTL 120s，若持有者已死、锁无人续期，
TTL 不可能还剩 98s —— 说明 (a) 期间有人续期（实例 7092 抢锁成功），(b) 残留锁在
5436 等待的整段时间里被判为"持有者还活着"。

## 3. 根因（三层，均已修）

### R1 存活判定唯一依赖端口探测 → 健康实例被误杀（当日 10:30 触发点）

`LauncherForm.RefreshStatusesAsync` 旧逻辑以 `IsServiceRunning`（端口探测）做门禁：
端口探测为假就不问 `/api/health`，直接按"离线"处理（`collector-offline`，restartable=true）。
而 `LauncherPorts.IsPortOpen` 依赖 netstat/TCP 表（本机 LISTENING 行确实缺失：复现命令
`netstat -ano | grep :8001` 只有 ESTABLISHED/TIME_WAIT）再回退 500ms 连接探测；TCP 表损坏
叠加 launcher 自身线程池争用时会对活着的 8001 连续假阴性，两次轮询即触发
`EnsureHealthy` → 停掉健康实例。

### R2 残留锁判活只看 PID → 强杀后的锁熬满 TTL（8001 起不来的主因）

`RedisInstanceLock.acquire()` 用 `OpenProcess` 是否成功判持有者存活。实测（本机复现）：

```
# 子进程被 kill 后父进程仍持有句柄（等价 launcher 的 Process 对象/管道）
$ python probe_pid.py <pid>
OpenProcess handle: 468              ← 旧判定：存活（错）
GetProcessTimes ok: 1 creation: 134368522690637013
GetExitCodeProcess ok: 1 exit: 1     ← 真实状态：已终止
$ tasklist /FI "PID eq <pid>"        → 无此进程
```

即被强杀的持有者会持续被误判为存活，残留锁只能等 TTL 自然过期（120s）；
PID 被系统复用时（本机 PID 非单调，例如 5436 后创建却小于 5752）同样误判。
等锁预算（32×5s=160s）本是"覆盖 TTL"的兜底，双实例竞争时后到者必然耗尽预算自杀。

### R3 双实例放行 → 必有一个输家自杀并写"不可重启"标记

8001 等锁期间不监听端口，`StartService` 的 `IsServiceRunning` 判否 + 15s 节流窗口
可被两次启动请求跨过（10:50:40 与 10:51:01 相隔 21s），于是同时存在两个等锁实例；
输家 160s 后 `RuntimeError` 退出并写 `logs/collector-startup-failure.json`
（`restartable=false`，10 分钟新鲜窗口），把 8001 的"失败"状态延长到自愈窗口之外。

### R4 采集侧超时 + 队列阻塞（另一条轴：漏采，不是端口掉线）——已修（2026-10-19 下午）

当日 6 次 `collector group of 1 slots timed out after 240.0s`（09:59 / 10:14 / 10:39 等），
落库为 `status=failed, blockingIssues=["slot_error"]`，随后被 5 分钟 grace 缺失自检
记成 `slot_missed_grace_window`（blocked，fail-visible）。

两个关键事实：

1. **看门狗预算按组大小线性放大**：`scheduler._tracked_collect_multi` 用
   `asyncio.wait_for(..., timeout=collect_timeout_seconds * len(requests))`，
   即 1 类型 240s、3 类型（11:30 那种 five+quarter+half 同刻组）**720s**。
   11:30 收盘槽实测跑了 9 分钟才结束（`in_flight` 三个快照全程占住 `_collect_sem`
   串行队列），后续 5 分钟槽无法开始 → 直接变成“slot missed”。
2. **真正的慢源只有一个（数据定位）**：当天全部 run 的 `sourceHealth.latency_ms` 显示
   `server_market_evidence` 单源 130.2 / 170.6 / 215.0 / 256.3 / **298.9s**，
   其余所有源合计 <10s。其内部链路：`ServerMarketEvidenceProvider` →
   `MarketOverviewService.get_overview()` →
   `akshare.stock_zh_index_spot_sina()`（同步 requests 抓取，**自身无超时**）+ THS 双试。
   同批 `:3000/health` 4ms、`:8000/api/kpl/hot` 0.19s，不是端口/代理饱和。

修复（已实施 + 已验）：

| 层 | 改动 | 语义 |
|---|---|---|
| `market_proxy/indices.py` | `get_overview(timeout_s=...)` 封顶；超时→返回 last-good 并标 `stale=true`+`errorCode`，无 last-good 才抛错；`timeout_backoff_s` 内不再重打上游；抓取改用专用单线程执行器 | 超时可观察、可退避、不拦死调用方；单 worker 兼作断路器（挂死期间新请求排队被取消，不堆积挂死线程/不占共享默认执行器）|
| `snapshot_collector/providers.py` | THS 每试 + indices 各分预算（下限 1s），indices 取“剩余预算”；慢源（≥5s）逐槽打 WARNING | provider 真正尊重 `timeout_ms` 合约；即使槽位组之后被看门狗取消，launcher 日志也留慢源证据；部分失败不丢可用部分（THS 超时仍保留 indices，反之依然）|

验证：

- `tests/market` + `tests/snapshot_collector` **857 passed**（新增：超时无 last-good 抛错、超时供
  stale+退避、退避窗口后恢复、单 worker 断路器、provider 按 timeout_ms 封顶、THS 超时仍保留 indices）。
- 真实上游复测（2026-10-19 12:0x，盘外）：直接调 `akshare.stock_zh_index_spot_sina()`
  快速抛 `list index out of range`（0.12s）——即上游当前另有**快失败**模式，与本次修复无关
  （该路径原本就落 `indices_failed`，不改变行为）；而**挂死**模式实测已被封顶：
  真链路（`_collect_context` 全量）总耗时 **19.3s**，其中 `server_market_evidence` **10.9s**
  （修复前同链路 130~303s），health 标 `indices_timeout: ...`，`limitSummary=True`（部分成功保留）。
- 生产生效：12:11 以受控强杀重启 8001 加载新代码（18s 恢复，锁清理日志同前）。

## 4. 修复

| 层 | 文件 | 改动 |
|---|---|---|
| R2（主因） | `quant-board/backend/snapshot_collector/instance_lock.py` | 锁值升级为 `v2:<token>:<pid>:<进程创建时间>`；判活改 `_process_identity`：Windows 用 `GetExitCodeProcess != STILL_ACTIVE` 判"真在跑"、`GetProcessTimes` 创建时间识别 PID 复用；POSIX 用 `/proc/<pid>/stat`（`Z` 即僵尸）；不可判定一律按存活（保守，绝不误清活跃锁）。清锁走 `GETDEL` 原子取走 + 取错就放回，杜绝并发误删他人新锁 |
| R1 | `tools/DragonBoardLauncher/LauncherForm.cs` + `Core/CollectorStatusResolver.cs` + `SnapshotCollectorProbe.cs`（新增 `HttpReached`） | 采集存活改以 HTTP 健康契约为准：端口探测失败也读 `/api/health`，服务自报成功即按运行中处理（能连上 8001 就证明端口在听）；只有 HTTP 也不可达才走离线拉起/标记路径 |
| R3 | `tools/DragonBoardLauncher/LauncherProcessManager.cs`（`StartService` 新增采集服务等锁重复启动守卫） | 端口关闭 + 锁等待标记新鲜 + 存在活的采集实例 = 确认在等锁 → 忽略重复启动请求并提示（标记过期或实例退出后自动恢复拉起；强制重拉先点"停止"） |
| R3 | `quant-board/backend/collector_main.py`（新增 `_collector_serving_elsewhere`） | 等锁预算耗尽时先探 8001 `/api/health`：若已被另一实例正常服务，本实例按"冗余"退出并 `_clear_startup_failure()`，不再留下 10 分钟 `restartable=false` 假标记 |
| R3（根上） | 同上 R2 | 强杀后首次 `acquire()` 即可判定残留并重抢，单实例场景不再有 120s 空窗；等锁预算保留作"判活不可判定"时的 TTL 兜底 |
| R4（旁路缺陷） | `quant-board/backend/snapshot_collector/service.py` + `slots.py`（新增 `slot_due_timestamp_ms`） | `backfill-slots`（API/CLI）按整天生成槽位，原本会把当前行情盖到未来槽位生成伪帧；现按 scheduler 同一时刻口径判定到期，未到期槽位计 `blocked: slot_not_due`（fail-visible），不再采集 |

## 5. 验证

```powershell
# 残留锁判活（含真实"杀进程但父进程持句柄"回归用例）
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/snapshot_collector/test_snapshot_collector_instance_lock.py tests/snapshot_collector/test_collector_lock_wait_budget.py -q

# 采集链全量
.\.venv\Scripts\python.exe -m pytest tests/snapshot_collector -q

# 启动器内核
cd ..
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
dotnet test tools\DragonBoardLauncher.Tests\DragonBoardLauncher.Tests.csproj
```

结果：Python 576 例（新增 8 例：残留锁判活 6 + 补采到期守卫 5 + 槽位到期口径 3
→ 含去重）通过；采集链 576 例全绿；launcher 78 例通过，0 警告 0 错误。

⚠️ 更正一条早期判断：11:10:38 那次重启看起来"零等锁重试"，但那是 Redis 在
11:04/11:10 被一并重启、锁 key 已消失的结果，**不能**归因为本次修复的功劳。
真正的生产证据看下面的受控演练。

### 5.1 生产受控演练（2026-10-19 11:51–11:52，用户批准，午休窗口无槽位）

前置：launcher 已是新构建（PID 21412，根目录 exe，11:44 启动），8001 由
引导进程 PID 2036 / server PID 20296 提供，锁 `v2:cf73c7a7…:20296:…`（TTL 61s）。

```
11:51:49  taskkill /F /T /PID 2036   → 杀掉 2036/20296/21212 整树（Redis 不动）
11:51:50  快照采集服务 已退出。
11:52:00  快照采集错误: 无法读取采集服务(8001)健康状态: 连接被拒绝
11:52:02  已启动 快照采集服务，PID=3640。（launcher 自动拉起，交易时段允许“拉起已死服务”）
11:52:04  [快照采集服务] clearing stale collector lock left by dead holder pid=20296
11:52:05  INFO:     Application startup complete.
11:52:07  INFO:     Uvicorn running on http://127.0.0.1:8001
11:52:10  快照采集恢复正常：调度器心跳和槽位完整性检查均通过。   ← health 200，总用时 21s
```

第二轮（12:11，加载 R4 修复）：同法强杀 PID 19300 整树 →
`12:11:49 clearing stale collector lock left by dead holder pid=19300` →
`12:11:53 Uvicorn running` → `12:11:54 快照采集恢复正常`，**18s 恢复**，health `ok/restartable=true`。
两轮均：0 行 `lock held elsewhere`、无 `collector-startup-failure.json`、锁值与 PID 即时换代。

结论性对比：

| 指标 | 修复前（今日同型场景） | 修复后实测 |
|---|---|---|
| 强杀后可用耗时 | 78~120s（等满 TTL），最长 10min（标记压制） | **21s** |
| `lock held elsewhere` 重试行 | 当日全天 131 行 | **0 行** |
| `collector-startup-failure.json` | 3 次写入 `restartable=false` | **未生成** |
| 新锁 | 旧 token 残喘/被误判为活 | `v2:ef9ecb12…:19300:…`，TTL 113（**新实例即时接手，未等到旧锁 61s TTL 到期**）| |
| 事后 health | degraded / restartable=false / error 12+ | **ok / restartable=true / error 0** |

关键行 `clearing stale collector lock left by dead holder pid=20296` 即 R2 修复的
生产实证：被 taskkill 且 launcher 仍持句柄的 pid 被正确判死，锁被原子清掉重抢——
这正是修复前误判而导致的 120s 空窗。

单实例不变量（防双采）同场核验（真 Redis + 真 8001，只读语义：不抢锁/不写标记）：
第二实例 `acquire()` = **False**；活持有者锁值前后**完全未改**；
`remaining_ttl()`=78s；`_collector_serving_elsewhere()` = **True**（冗余实例会走
“清标记 + 明确退出”，不再拖 10 分钟不可重启窗口）。

### 5.2 补采记录

当日补采记录（本任务执行）：09 个已到期时点、13 个 snapshotId 全部 `completed`
（5m: 10:10/10:35/10:40/10:45/11:00/11:05/11:10/11:25；15m: 10:30/10:45/11:00；30m: 10:30/11:00），
耗时 30~132s/时点；补采后审计：四类型**已过期未采 = 0**。11:30 收盘组由调度器自己采完
（11:30 开跑 → 11:39 落库，**约 9 分钟**，正好在其 720s 组预算内——这正是 R4
“大组长占串行队列”的现场实证）；无 emptyFrames、无 countDrifts、无 missingRecords
（daily 15:30 未到点，未伪造）。

⚠️ 副作用如实记录：11:20–11:30 我边跑补采边让调度器采 11:25 槽，两者争抢同一批上游源，
导致 11:25 槽被 240s 看门狗判 failed（后已补采成功）。这从反面印证了 R4 的
“竞争型超时”结论：**并发采集会互相拖死，补采与调度器不应同时压同一上游**。

清理：删除了因 11:02:38 自杀留下的过期 `logs/collector-startup-failure.json`
（其 reason 文本会一直被重复展示，10:59:37 就出现过"旧 reason + TTL 98s"的错位提示）。

真 Redis 端到端取证（用独立 key 名 `verify-20261019-lockfix`，验完清理）：

```
lock value written by child: v2:cb341f8f…:19412:134368527888213554 ttl: 118
getdel supported: True
clearing stale collector lock left by dead holder pid=19412
reclaimed=True in 0.01s; value now=v2:81a78111…:7756:134368527877022814
cleaned: None
```

即"子进程被杀、父进程仍持有句柄"的残留锁从"等满 TTL 120s"变成 **0.01s 重抢**。
另需人工验收（本次未做，涉及盘中停启）：

1. 停掉 8001 → 端口关闭 + 无标记 → launcher 两轮轮询内自动拉起；
2. 强杀 8001 进程后立即 `POST` 启动 → 首个 `attempt` 即拿到锁（不再 120s 空窗）；
3. 8001 等锁期间重复点"启动" → 只日志提示，不再叠加实例。

> 生效前提：launcher 正在运行，重新编译/发布后需关闭启动器再启动
> `tools\DragonBoardLauncher\DragonBoardLauncher.exe`（本次已 `publish` 刷新该入口，未动运行中的实例）。

## 6. 遗留 / 未做

- Python 侧输家实例（等锁预算耗尽的 redundant 实例）仍会 `RuntimeError` 退出；
  现已加“8001 已被服务则不写标记”判定，但 uvicorn 仍会打印 `Application startup failed`
  （它只在 lifespan 抛异常时退出），看起来仍像一次"启动失败"，只是不再影响自愈。
- `collector-startup-failure.json` 的 10 分钟新鲜窗口未按"持有者是否仍在采集"动态收敛。
- 端口探测假阴性本身未根治（属 Windows TCP 表损坏外部条件），只是不再作为存活唯一依据；
  且它仍是“服务已启动后 TrackPortOwner 认领监听进程”的输入（认领失败会打日志，不影响存活判定）。
- 启动器仍保留“健康失败 → stop + start”策略；自 2026-10-19 起它被两道闸保护：
  ① probe:*（探针超时/不可达）证据在 09:15–15:10 一律推迟到收盘；② 端口探测不再作为存活判据。
  但若出现“进程真的活着而契约异常”的新形态，仍可能走停启路径，需按新增 log 指纹继续观察。
- **R4（240s 组超时）已修**（见 §3 R4）：`indices.py` 超时封顶/退避/断路器 +
  provider 子步骤预算。仍建议下一步看是否把"重负载槽位延迟采集"或"给组超时设上限"
  作为第二道防线（看门狗预算仍是 `240s × 类型数`，理论上 3 类型组最长仍可占队列 12 分钟，
  只是辅以封顶后慢源已不再吃满预算）。
- 启动器侧修复（R1/R3-守卫）已**生效**：2026-10-19 11:44 用户以根目录新构建
  `tools/DragonBoardLauncher/DragonBoardLauncher.exe` 重启（PID 21412），
  新代码指纹 `TCP 表未列出端口 8001，已回退按进程树跟踪…`（`LauncherProcessManager.cs:555`）
  已在当日日志出现；Python 侧随 11:44:44 新进程一并加载。

---

## 7. 附：Redis / 短 TTL 排查结论（用户提出假设后追加，2026-10-19）

**假设**：`Redis last-good TTL 只有 10s` 是 8001 端口"启动不了 / 自动恢复不了"的主要原因。

**逐条核查（结论：不成立）**

| # | 核查点 | 证据 |
|---|---|---|
| 1 | 这个 10s TTL 是哪个键？谁在读？ | `market:overview:v1`（指数新鲜缓存，`indices.py` `_redis_set` 用 `ttl_ms/1000`=10s）。读取方只有 `MarketOverviewService`：8000 的 `GET /api/market/overview` 与采集链 `server_market_evidence` 的 `indices`。**不在** 8001 启动路径，**不在** launcher 存活/自愈判定路径 |
| 2 | 8001 启动依赖 Redis 什么？ | 只有实例锁 `snapshot-collector:instance-lock:<dataset>`，**TTL 120s**（+60s 心跳续期），与 10s 无关 |
| 3 | Redis 挂了会让 8001 起不来吗？ | 不会。`RedisInstanceLock.acquire()` 在异常时 **fail-open**（`instance_lock.py` `except → return True`）。实测：把 Redis 指到死端口跑 `_acquire_lock_with_retry`（3 次重试）→ 返回 `True`，lifespan 不抛错 |
| 4 | 自愈会不会因此变慢？ | 三次受控强杀实测恢复 **21s / 18s / 19s / 24s**，全部由"锁 TTL 判活修复 + launcher 守卫"决定，与 10s 无关（见 §5.1） |
| 5 | "长时间没采到数据"会不会引发 8001 停启？ | 不会。探针对该类情形返回 `warn:*` → `Health.Warning(... Restartable: false)` → `CollectorHealthGuard` 明确 `ShouldRestart: false`（源码注释：业务进度类告警"展示并记录日志，但不触发自动重启"） |

**但它确实牵出两个真问题（已修，记为 R5/R6）**

### R5 Redis 不可达时的 fail-open 无可见性 → 可双采

`acquire()` 异常时直接 `return True`：可用性没问题（8001 照样起），但在"另一个实例正在采"时也会放行 → **双采**（项目红线），而且 /api/health 完全看不出来。

修复：

- `instance_lock.py`：fail-open 时记 `degraded_reason`（不改变返回值语义）；
- `collector_main.py`：拿到降级锁后再查 8001 是否已被服务（`_degraded_lock_peer_running`）——已被服务则本次直接退出（`防双采退出`），否则以单实例继续；
- `/api/health`：`snapshotCollector.lockBackend = redis|degraded` + `lockError`，契约在 degraded 时给 `degraded/alert/restartable=false`（launcher 只告警，不重启风暴）。

实测（隔离实验，非生产）：Redis 指死端口 + 另起 8099 实例 →

```
collector instance lock acquire failed: Timeout connecting to server
lock backend degraded (...) and 8001 is already served by another instance; exiting this instance to avoid double collection
RuntimeError: lock backend unavailable and 8001 already served by another instance; exiting to avoid double collection
```

即"Redis 挂"不再能换出第二个采集器。单实例不变量同时复核：第二实例 `acquire()=False`、活持有者锁值前后**完全未改**。

### R6 重启/上游故障后 indices "裸取"（与 R4 同源）

10s 新鲜缓存撑不过一次进程重启，更撑不过上游故障：修复前这条路就是"直接去打上游"，而 akshare-sina 自身无超时（可 130~299s）——正是当日 6 次掉槽的那个源。

修复：

- 新增 `market:overview:last-good:v1`（TTL **300s**，只有成功取数才写），**仅在超时/报错时**启用；happy path 永不使用（8000 路由不会把旧数据当新鲜）；
- 用时带 `stale: true` + `errorCode` + `staleSeconds`，采集链升到帧级 `qualityFlags`：`indices_stale[:<age>s]` 或 `indices_missing:upstream_timeout|upstream_error`，并同步进 run doc 的 `sourceHealth[].details`。

实测（真 Redis，隔离前缀，验后清理）：

```
取数成功: stale=False items=1        新鲜缓存 TTL=10   last-good TTL=300
上游报错后: stale=True errorCode=upstream_error staleSeconds=1.1 items=1
退避内二次调用: 0.001s errorCode=upstream_timeout_backoff
```

**结论一句话**：10s TTL 不是 8001 启动/自愈的原因（启动只依赖 120s 的实例锁，且 fail-open；自愈由锁判活与 launcher 守卫决定）；它影响的是 `indices` 的"新鲜 vs 兜底"。按用户提示重审后，补上了 last-good 兜底与帧级可见性，并顺手补了 Redis 不可达时的防双采与降级可见性。当前上游 akshare-sina 在盘外仍会报错/挂住（上午 5 帧 half_hour 的 indices 都在），last-good 库需**一次成功取数**才会被填充——这属上游数据可用性，不属 8001 启停问题。

---

## 8. 附：3000/8008/8000/32145 盘中"掉线又自动恢复"排查（用户提问后追加，2026-10-19）

**结论：分两层。**显示层抖动与"假离线→重复启动"属 §3 R1 同一根因（端口探测启发式，launcher 级、对所有服务生效）；但真实进程退出各有独立原因，与 8001 的实例锁无关（这些服务不参与锁）。同时确认：**这些端口没有自动拉起**，所谓"自动恢复"来自 ①显示层 3 秒后自己翻回"运行中" ②人工点启动/重启管理器。

### 8.1 取证

读取近 8 日 `logs/launcher/*.log`，按服务名→端口映射（`config/services.json`）分类事件：只有 `已停止 X 实际监听进程` 前后 10 行内的退出才算"管理器/用户主动停"，其余算"自发退出"。

**自发退出（交易时段 09:15–15:10，已排除 StopAll 与管理器重启）**

| 日期 | 8000 量化后端 API | 3000 本地代理 | 8008 JEV 叙事工作台 | 32145 语音 |
|---|---|---|---|---|
| 10-12 | 2 | - | 1 | - |
| 10-13 | 1 | 1 | - | - |
| 10-14 | 2 | - | - | - |
| 10-16 | - | 1 | - | - |
| 10-18 | 1 | - | - | - |
| 10-19 | - | - | - | 1（管理器重启副作用） |

**已定位的两条真实崩溃链**

1. **3000 本地代理进程崩溃（Node 未捕获 rejection）** — 10-16 10:20:02：
   ```
   TypeError: fetch failed
     at async sendPayload (proxy-server/routes/notifications.js:97:22)
     at async flushPending (proxy-server/routes/notifications.js:170:7) {
     [cause]: Error: getaddrinfo ENOTFOUND open.feishu.cn
   Node.js v24.13.1
   本地代理服务 已退出。
   ```
   飞书 webhook 域名解析失败 → `flushPending` 抛错 → 定时器回调 `return flushPending()` **无人 catch** → Node 默认按致命错误退出。该次 3000 直到 15:19 才被拉起（约 5 小时不可用，因为 3000 不在自动拉起名单里）。

2. **8000 重复启动自杀（端口探测假阴性的真实伤害）** — 10-14 13:37:26：
   ```
   量化后端 API TCP 表未列出端口 8000，已回退按进程树跟踪实际监听进程 PID=18244（引导进程 PID=3292）
   [量化后端 API] ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)
   量化后端 API 已退出。
   ```
   服务活着且正在监听 8000，但 TCP 表查不到 + 500ms 连接探测失败 → 判定"未运行" → 有人（按钮/启动流程）发起启动 → 新 uvicorn 绑不上端口自杀。**这条直接坐实了 §3 R1 的假阴性不只影响 8001**，且能造成真实掉线。

**其它**：10-12 09:23:45/46（8000+8008 同秒退出）、10-13 13:20:35/36（3000+8000 同秒退出）、10-18 10:53:40（8000）无任何错误输出、无停止命令——旧日志不记退出码与"是否被请求停止"，**无法归因**（这本身是缺陷，已修）。

### 8.2 本轮修复

| # | 问题 | 修复 | 验证 |
|---|---|---|---|
| R7 | 端口探测假阴性 → 显示抖动 + 重复启动（10048） | 新增 `Core/ServiceLivenessResolver.cs`；`LauncherProcessManager.IsServiceRunning` 改为"快速探测 + 强证据（跟踪进程存活/本会话见过它运行）时 2s 深探测复核"，深探测失败才认死并清除记忆；`LauncherPorts.IsTcpListeningOn` 支持自定义超时 | `ServiceLivenessResolverTests`（4 例：探测为真不深探、无强证据不深探、深探通过判活、深探失败判死）；`dotnet test` 82 passed；真机集成核对 8000/8001/3000/32145/8008 全部快速路径 <1.5s 判活 |
| R8 | "掉线"无日志；退出原因不可归因 | 状态跳变写日志（运行中↔已停止）；`ManagedService.StopRequested` + `Exited` 打印退出码并区分"管理器主动停止"/"未请求停止" | 编译 0 警告 0 错误；82 passed |
| R9 | 3000 因未捕获 rejection 崩溃 | `notifications.js` 定时刷新改为 `flushPending().catch(...)`（保留事件待下窗口重试，不静默丢） | `notifications.test.js` 新增回归：**修复前 fail、修复后 pass**（实测两种状态），事件按预期留在 pending 待重试 |
| R10 | 8000 的 `连接程序获取失败: Database objects do not implement truth value testing` | **未改**（全仓 grep 无该文案，疑在上游产物/非本仓代码；待定位） | 需用户确认现场 |

### 8.3 未修（需拍板）

1. **非核心服务没有自动拉起**：3000/8000/8008/32145/5173/5174 真死后不会自动恢复（仅 8001 与 mongo/redis 有），10-16 的 3000 因此空置 5 小时。是否对这些服务加"进程真死→自动拉起"（含冷却/交易时段策略）需用户决定。
2. **8000 事件循环被同步长任务堵住**：`market quotes refresh timed out after 120s`、akshare 抓取无超时等同步工作跑在 async 路径上，会让服务在最需要响应时"忙而不响应"（这正是端口探测假阴性与前端 502 的土壤）。属 quant-board 内部改造，与 R4 同源但范围更大。
3. **本次改动生效方式**：根目录 `DragonBoardLauncher.exe`（双击入口，`RootSingleFile` 发布产物）当前正被运行中的管理器占用，无法覆盖发布；需先关闭管理器再 `dotnet publish -p:PublishProfile=RootSingleFile`。3000 的修复需重启本地代理服务或管理器后生效。

---

## 9. 指数源切换：akshare → 行情桥（TDX），2026-10-19

**触发**：用户判定「akshare 被风控限流」，要求"所有经过 akshare 的都要找替代源，先把指数改成行情桥"。

**当日证据**：13:00/13:05/13:10/13:30 四个槽的 run doc 里 `server_market_evidence` 一律吃满 30s 预算后 `indices_timeout`，帧 `indices=[]` 并被打上 `indices_missing:upstream_timeout`；而上游 akshare-sina 盘外/盘中均挂死（11:30 及更早的帧还有值）。

**能力核实（先验证再动手）**：TDX 与股票共用五档行情接口，指数靠 `market` 区分（沪指 market=1，深指 market=0）。用 `python-bridge/tdx_hosts.json` 的官方主站 + `main.py` 的 `TdxHq_API.setup` 补丁（只发 SetupCmd1/2，跳过旧客户端标识）实测：

```
market=1 code=000001 price=3716.02 last_close=3716.28 open=3694.12 high=3733.86 low=3692.29
market=0 code=399001 price=11754.03 last_close=11802.46
market=0 code=399006 price=2735.73 ... market=1 code=600000 price=9.82（股票同样正常）
```

即指数数据本就可达，缺的只是一个"保留市场前缀"的取数口。

**实现**

| 层 | 改动 |
|---|---|
| 行情桥 | 新增 `normalize_index_code()`（**保留 sh/sz/bj 前缀**，裸 6 位按指数惯例补：399/980/159→深，其余→沪）与 `GET /api/quotes/index-snapshot?codes=`（默认清单含 sh000001/sz399001/sz399006/sh000300/sh000905/sh000852/sh000688），返回 `code/lastPrice/preClose/changeAmount/changePct/open/high/low/volume/amount`；空结果与上游异常均 `ok=false` + `error`（fail-visible，不伪造） |
| 量化侧 | 新增 `backend/market_proxy/index_bridge_source.py`（桥→原 akshare 口径 items，含名称静态补齐）；`MarketOverviewService` 改为**源可切换**：默认 `bridge`，`akshare` 降为显式回退，另留 `bridge_then_akshare` 迁移期选项（`QUANT_BOARD_INDEX_SOURCE`，拼错显式告警）；任何源返回空 items 一律抛错，不得当成功写缓存 |
| 消费侧 | **零改动**：`build_server_indices` 仍按 code 映射 `sh/hs300/zz500/zz1000/totalAmount`，帧键位与 akshare 口径逐字一致 |

**为什么必须单开一个口**：`000001` 既是上证指数(sh) 也是平安银行(sz)，而股票口 `/api/quotes/snapshot` 为了股票场景把代码归一成纯 6 位（丢前缀）——指数走那条会拿到错误标的。

**验证**

- 桥单测 `python-bridge/test_quote_snapshot_api.py`：**40 passed**（新增 4 例：前缀归一、行→契约映射、默认清单覆盖 frame 键位、上游失败 ok=false）。
- 量化单测：`tests/market/test_index_bridge_source.py` 8 例（映射/推导/过滤/空返回抛错/HTTP 错误传播/帧键位契约等价/单市场不伪造 totalAmount）+ `test_market_data_routes.py` 6 例（默认走桥、桥失败→last-good 标 stale、无 last-good 抛错、bridge_then_akshare 回退、空结果不缓存、源解析优先级）；全量 `tests/market + tests/snapshot_collector` **884 passed**。
- **真链路端到端**（临时桥 8799 + 真 TDX + 真 Redis）：`fetch_index_items` 取到 7 个指数；`build_server_indices` 输出
  `{'sh': {'change': 5.68, 'changePct': 0.1528}, 'hs300': {...}, 'zz500': {...}, 'zz1000': {...}, 'totalAmount': {'amount': 1071028633600.0}}`；
  走完整 `MarketOverviewService(source="bridge")` → `source=tdx-bridge-index, stale=False`，并已把 **真实 TDX 值**写入 `market:overview:v1`(ttl=10) 与 `market:overview:last-good:v1`(ttl=300)——last-good 兜底库首次有真实值。
- 临时桥已关闭；生产 8765 未动。

**生效方式（需用户点按，管理器无命令行/HTTP 控制口）**

运行中的进程仍是旧代码，需重启才生效：**8765 行情桥**（新指数口）、**8001 快照采集**（新指数源）、**8000 Quant API**（`/api/market/overview` 同源）。三者都不在自动拉起名单内（只有 8001 与 mongo/redis 会自愈），因此请在管理器里点一次「全部停止 → 全部启动」（今日 11:41/12:14 已用过此法），或分别对这三个服务点「停止/启动」。

**仍未处理（akshare 面清单，待逐个决定替代源）**

- `backend/market_proxy/akshare_fund_provider.py`：同花顺网页个股资金流（`theme_fund` 回退源，默认源已是东财直连）。
- `backend/core/fund_sources.py` 的 `akshare_ths_individual` 分支与 `QUANT_BOARD_THEME_FUND_SOURCE=akshare` 回退。
- `backend/main.py` 中 akshare 相关的 pandas 弃用告警过滤与注释（无实际取数）。

---

## 10. 删除 akshare 题材回退源（用户决定，2026-10-19）

**用户指令**：第 1 项（`market_proxy/akshare_fund_provider.py`）不动；第 2、3 项（`fund_sources.py` 的 `akshare_ths_individual` 分支 + `QUANT_BOARD_THEME_FUND_SOURCE=akshare` 回退、`main.py` 的 akshare 警告过滤）删掉。

**遇到的依赖纠缠（已如实处理）**：`akshare_fund_provider.py` 自己 import 了 `FUND_SOURCE_AKSHARE_THS_INDIVIDUAL`（给自己行打源标识），所以"常量彻底删除"与"第 1 项不动"冲突。采用的处理：**常量保留为纯标识**（仅供保留模块使用，文档写明"若该模块后续删除则常量同步删除"），但把它从 `SUPPORTED_FUND_SOURCES` 与 `FUND_SOURCE_HASH` 中移除——即缓存**不再接受/路由**该源（已写入的同名行由东财行同 hash 覆盖或 TTL 淘汰），调度器也不再选中它。

**改动清单**

| 文件 | 改动 |
|---|---|
| `backend/core/fund_sources.py` | `SUPPORTED_FUND_SOURCES` 去掉 akshare；`FUND_SOURCE_HASH` 去掉 akshare→hash 路由；docstring 把 akshare 移入"已删除"清单并说明常量保留原因 |
| `backend/services/market/fund_scheduler.py` | 删 `AkshareFundProvider` 两个 import 与 `_build_default_provider()` 的源分支（现固定东财）；删 `eastmoney_mode` 三分支（固定 1800s 周期 / 1800s 冷却 / 600s 预算）；系统性错误码不再并集 akshare 命名空间 |
| `backend/services/theme/fund_cache.py` | 去 akshare 源 import 与 rank=1 条目；修正把 akshare 当活跃源的注释（`_akshare` 属性名与 `get_akshare_latest` / `theme-fund:akshare` key 名**保留**——它们是 hash 名，不是数据源） |
| `backend/core/settings.py` | `QUANT_BOARD_THEME_FUND_SOURCE` 只接受 `eastmoney`，其它值（含 akshare）**显式 WARNING + 回落默认**；删已无用的 `theme_fund_refresh_interval_seconds`（及其 env 读取、注释） |
| `backend/main.py` | 删 akshare 的 pandas `FutureWarning` 过滤器与注释、`import warnings` |
| `tests/market/test_market_fund_scheduler.py` | 删"akshare 档位"用例；系统性错误用例改用现存命名空间 `em_rate_limited`（行为断言不变）；新增"env 仍写 akshare 时不得回退旧档位"防回归用例 |

**验证**

- `tests/market + tests/snapshot_collector`：**883 passed, 1 skipped**（`test_akshare_fund_provider.py` 属第 1 项，未改动、照常通过）。
- 生产 `.env.local` 场景实测：`QUANT_BOARD_THEME_FUND_SOURCE=akshare` → `WARNING ... not in {eastmoney} (akshare fallback removed 2026-10-19); keep default eastmoney`，provider = `EastmoneyFundProvider`，档位 1800/1800/600s ✓（不再有 300s 旧档位）。
- 导入面核对：`backend.main` 正常（过滤器删除无副作用）；`SUPPORTED_FUND_SOURCES = {eastmoney_main, ths_main_monitor}`；`FUND_SOURCE_HASH` 仍把 eastmoney 路由到 `akshare` hash（key 名不变，已预热缓存不丢）。

**遗留提醒**

1. `quant-board/.env.local:88` 仍写着 `QUANT_BOARD_THEME_FUND_SOURCE=akshare`——现在只会产生一条告警并走东财，建议删掉该行（避免下次排障误以为还在用 akshare）。该文件是用户本地配置，未擅自改动。
2. 前端 `src/config/fundSources.ts` 仍声明 `AKSHARE_THS_INDIVIDUAL` 标签与"回退源"注释。保留它可继续渲染缓存里已存在的历史行，但注释已过期；是否清理待用户确认（属前端口径，未擅自改）。

### 9.1 akshare 面清理（用户指令：第 1 项不动，第 2、3 项可删）

| # | 项 | 处置 |
|---|---|---|
| 1 | `backend/market_proxy/akshare_fund_provider.py`（akshare 同花顺网页个股资金流） | **未改**：`git diff` 为空，模块与其 12 例单测原样保留 |
| 2 | `fund_sources.py` 的 `akshare_ths_individual` 题材源 + `QUANT_BOARD_THEME_FUND_SOURCE=akshare` 回退 | **已删**：见下 |
| 3 | `backend/main.py` 里 akshare 的 pandas `FutureWarning` 过滤 | **已删**：连同只被它使用的 `import warnings` |

**第 2 项的删除范围（关键是"源"删、"hash 名"留）**

| 文件 | 改动 |
|---|---|
| `backend/core/fund_sources.py` | `SUPPORTED_FUND_SOURCES` 收敛为 `{ths_main_monitor, eastmoney_main}`；`FUND_SOURCE_HASH` 去掉 akshare 路由；**保留** `FUND_HASH_AKSHARE = "akshare"`（它是 Redis key 名，改 key 等于丢掉已预热缓存）；保留 `FUND_SOURCE_AKSHARE_THS_INDIVIDUAL` 字符串常量——第 1 项模块用它给行打标识，删了会让"不动的第 1 项"直接 ImportError（本轮真实踩到：先删常量导致 `test_akshare_fund_provider.py` + `test_market_fund_scheduler.py` 收集失败，故按"第 1 项不动"回退为仅移出可路由集合） |
| `backend/services/theme/fund_cache.py` | 去掉该源 import 与 `FUND_SOURCE_RANK[...,1]`；rank 变 `{eastmoney:2, ths_main_monitor:3}`；注释同步（残留同名行因无 hash 路由而不再被接受/读取） |
| `backend/services/market/fund_scheduler.py` | 去掉 akshare provider import、`get_akshare_fund_provider`、`AKSHARE_SYSTEMIC_ERRORS` 联合、`eastmoney_mode` 三分支；`_build_default_provider()` 固定返回东财；调度器固定 1800s 周期 / 1800s 冷却 / `max(600, …)` 预算 |
| `backend/core/settings.py` | `theme_fund_source` 只接受 `eastmoney`，其它值（含 `akshare`）**显式告警并回落默认**；删除只服务旧模式的 `theme_fund_refresh_interval_seconds`（含其 env 读取） |
| `backend/main.py` | 删除 akshare 的 `warnings.filterwarnings(...)` 及其独占的 `import warnings` |
| `backend/services/theme/heat_service.py`、`quant-board/docs/api-cli.md`、`docs/theme-module/2026-08-14-fund-source-two-lines-design.md` | 文档/注释与实现同步：api-cli 改为"只有东财一个旋钮"；历史设计文档加 2026-10-19 状态横幅（正文保留历史结论）；前端 `marketFundStream.ts` 注释同步 |

**验证**

- `tests/market + tests/snapshot_collector`：**883 passed, 1 skipped**（含把已废弃的 `test_akshare_scheduler_keeps_original_profile` 改写成 `test_scheduler_ignores_removed_akshare_source_setting`：残留 env 写 akshare 时**不得**回落旧档位）。
- 第 1 项单测独立复跑：**12 passed**，且 `git diff --stat backend/market_proxy/akshare_fund_provider.py tests/market/test_akshare_fund_provider.py` 为空。
- 生产 `.env.local` 场景实测（`QUANT_BOARD_THEME_FUND_SOURCE=akshare`）：
  `WARNING … not in {eastmoney} (akshare fallback removed 2026-10-19); keep default eastmoney` →
  `theme_fund_source=eastmoney`、provider=`EastmoneyFundProvider(eastmoney_main)`、`refresh=1800 cooldown=1800 fetch_timeout=600`；
  `SUPPORTED=['eastmoney_main','ths_main_monitor']`、`FUND_SOURCE_HASH={'ths_main_monitor':'latest','eastmoney_main':'akshare'}`；
  已删除字段 `hasattr(settings,'theme_fund_refresh_interval_seconds') == False`；全仓无残留引用。

**留给用户的一行（未擅改用户配置）**：`quant-board/.env.local:88` 仍写着 `QUANT_BOARD_THEME_FUND_SOURCE=akshare`。代码现在会告警并走东财，但它已是无意义残留，建议删掉该行（删除后启动日志不再有那条 WARNING）。

**未动（明确不在本次范围）**：前端 `src/config/fundSources.ts` 的 `AKSHARE_THS_INDIVIDUAL` 常量仍被 `DataTable.vue`（行来源标注）与 `RealtimeQuoteCoordinator.ts`（拒绝把估算行进资金列的白名单）使用，用于标注/防御**历史行**；后端已不再产出该源，是否一并从前端删除由用户决定。
