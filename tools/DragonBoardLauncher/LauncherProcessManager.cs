using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

namespace DragonBoardLauncher;

internal sealed class LauncherProcessManager
{
    private static readonly IReadOnlyDictionary<int, Uri> ReadinessUris =
        new Dictionary<int, Uri>
        {
            [8000] = new("http://127.0.0.1:8000/api/health"),
            [3000] = new("http://127.0.0.1:3000/health"),
            [8765] = new("http://127.0.0.1:8765/health")
        };

    private readonly string _root;
    private readonly IReadOnlyDictionary<string, ManagedService> _services;
    private readonly Action<string> _log;
    private readonly HashSet<string> _starting = new(StringComparer.Ordinal);
    private Process? _mongoExpressProcess;
    private Process? _redisCommanderProcess;

    // 子进程输出异步队列（P2.1b）：输出回调只入队，后台消费线程批量写日志，
    // 避免高吞吐 stdout/stderr 在 Process 读取线程上同步落盘拖慢管道。
    // 有界容量（5000 行）防止极端高吞吐（如子进程疯狂刷错误）时内存无限增长；
    // 满时 TryAdd 失败丢弃新行，保证不阻塞子进程输出回调。
    private const int LogQueueCapacity = 5000;
    private readonly System.Collections.Concurrent.BlockingCollection<string> _logQueue = new(
        new System.Collections.Concurrent.ConcurrentQueue<string>(), LogQueueCapacity);
    private readonly CancellationTokenSource _logCts = new();
    private readonly Thread _logThread;

    public LauncherProcessManager(
        string root,
        IReadOnlyDictionary<string, ManagedService> services,
        Action<string> log)
    {
        _root = root;
        _services = services;
        _log = log;
        _logThread = new Thread(LogDrainLoop)
        {
            IsBackground = true,
            Name = "launcher-child-log"
        };
        _logThread.Start();
    }

    /// <summary>后台日志消费循环：批量取出子进程输出行并写日志（每批最多 100 行）。</summary>
    private void LogDrainLoop()
    {
        var batch = new List<string>(100);
        try
        {
            while (!_logCts.IsCancellationRequested)
            {
                batch.Clear();
                try
                {
                    // 阻塞取一条；取消时抛 OperationCanceledException 退出循环。
                    batch.Add(_logQueue.Take(_logCts.Token));
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                // 非阻塞把剩余可立即取到的行收进同一批。
                while (batch.Count < 100 && _logQueue.TryTake(out var line))
                    batch.Add(line);

                foreach (var line in batch)
                {
                    try { _log(line); }
                    catch { /* 日志写入失败不影响后续 */ }
                }
            }

            // 取消后把队列剩余行写完，避免丢失尾部日志。
            while (_logQueue.TryTake(out var remaining))
            {
                try { _log(remaining); }
                catch { }
            }
        }
        catch
        {
            // 消费线程异常不阻塞启动器主体
        }
    }

    private void EnqueueChildLog(string serviceName, string line)
    {
        try
        {
            // TryAdd：有界队列满时立即失败（丢弃该行），不阻塞子进程输出回调。
            if (!_logQueue.TryAdd($"[{serviceName}] {line}"))
            {
                // 队列已满：丢弃，避免子进程高吞吐输出阻塞管道。
            }
        }
        catch (InvalidOperationException)
        {
            // 队列已关闭（停止时）：丢弃，不阻塞子进程输出回调
        }
    }

    public void StartAll()
    {
        // 阶段名与 LauncherServices.CoreStartupStages 顺序对齐（P1.1 修正：
        // 基础设施→实时数据源→量化后端→快照采集，原"快照采集/量化后端"顺序写反）。
        // stages 阶段数来自 services.json 可配置；超出内置名单时回退"阶段 N"。
        var stageNames = new[] { "基础设施", "实时数据源", "量化后端", "快照采集" };
        var collectorPendingWait = false; // 锁冲突豁免：collector 等待锁释放，不宣告就绪
        for (var index = 0; index < LauncherServices.CoreStartupStages.Length; index++)
        {
            var stage = LauncherServices.CoreStartupStages[index];
            var stageName = index < stageNames.Length ? stageNames[index] : $"阶段 {index + 1}";
            var stagePorts = string.Join(", ", stage.Select(key => _services[key].Port));
            _log(
                $"核心启动阶段 {index + 1}/{LauncherServices.CoreStartupStages.Length}: " +
                $"{stageName}（端口 {stagePorts}）。");
            foreach (var key in stage)
                StartService(_services[key]);

            if (WaitForServices(stage, TimeSpan.FromSeconds(30))) continue;

            // 仅 collector 独占阶段：若存在"启动失败 wait"（锁冲突）标记，不中止启动链，
            // 交由后台 guard/RestartPolicy 在锁 TTL 过期后自动拉起（P0 防风暴设计）。
            // 其它阶段无失败标记概念，超时仍按真实故障中止。
            if (stage.SequenceEqual(new[] { "collector" }) &&
                SnapshotCollectorProbe.TryReadStartupFailure() is not null)
            {
                _log(
                    $"{_services["collector"].Name}(8001) 正在等待锁释放，" +
                    "将由自动重启机制接管，不中止后续启动。");
                collectorPendingWait = true;
                continue;
            }

            var unavailable = stage
                .Where(key => !IsServiceReady(_services[key]))
                .Select(key => $"{_services[key].Name}({_services[key].Port})");
            _log($"核心启动错误: 依赖未就绪，已中止后续服务: {string.Join(", ", unavailable)}");
            return;
        }

        if (collectorPendingWait)
        {
            _log("核心启动完成（快照采集服务等待锁释放中，稍后由自动重启机制接管）。");
        }
        else
        {
            _log("核心启动完成: MongoDB、Redis、代理、行情桥、快照采集和 Quant API 均已就绪。");
        }
        _log("展示与辅助服务最后按需启动: 龙头看板 5173、量化面板 5174、本地语音 32145；不阻塞快照调度。");
    }

    private bool WaitForServices(IEnumerable<string> keys, TimeSpan timeout)
    {
        var pending = keys.ToArray();
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (pending.All(key => IsServiceReady(_services[key]))) return true;
            Thread.Sleep(250);
        }

        return pending.All(key => IsServiceReady(_services[key]));
    }

    private static bool IsServiceReady(ManagedService service)
    {
        if (!IsServiceRunning(service)) return false;
        if (service.Port == 8001)
            return SnapshotCollectorProbe.GetHealthAsync().GetAwaiter().GetResult().IsHealthy;
        if (!ReadinessUris.TryGetValue(service.Port, out var uri)) return true;

        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            using var response = client.GetAsync(uri).GetAwaiter().GetResult();
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    public void StopAll()
    {
        StopService(_services["quant-ui"]);
        StopService(_services["quant-api"]);
        StopService(_services["collector"]);
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services[LauncherServices.VoiceServiceKey]);
        StopService(_services["proxy"]);
        StopService(_services["redis"]);
        StopService(_services["mongo"]);
    }

    /// <summary>
    /// 单次健康恢复执行（不含冷却/计数——冷却与连续失败上限由 Core.RestartPolicy
    /// 在调用方统一管理，避免双层计数导致健康恢复后重启被永久拦截）。
    /// 端口关闭→启动；端口被占用但探针不健康→先停再启。
    /// 调用方必须已确认服务不健康（guard + policy 已通过）。
    /// </summary>
    public void EnsureHealthy(string key)
    {
        if (!_services.TryGetValue(key, out var service)) return;

        var portOpen = LauncherPorts.IsPortOpen(service.Port);
        if (portOpen)
        {
            _log($"{service.Name} 健康检查失败但端口 {service.Port} 仍被占用，先停止再重启。");
            StopService(service);
            Thread.Sleep(800);
        }
        StartService(service);
    }

    public void StartService(ManagedService service)
    {
        // 同一服务启动中禁止再次发起（UI 置灰之外的第二道保险，防止双 PID）。
        if (!_starting.Add(service.Name))
        {
            _log($"{service.Name} 正在启动中，忽略重复启动请求。");
            return;
        }
        try
        {
            if (service.IsVoiceWorker && !IsCurrentVoiceWorkerHealthy(service))
            {
                _log($"{service.Name} 正在运行旧版本，准备重启。");
                StopVoiceWorkerProcesses(service);
            }

            if (IsServiceRunning(service))
            {
                // 检查是已知进程还是孤儿进程（重启后残留）
                var trackedAlive = service.Process is { HasExited: false };
                if (trackedAlive)
                {
                    _log($"{service.Name} 已在端口 {service.Port} 运行。");
                    return;
                }
                // 孤儿进程处理：按 externalPolicy 决定清理/复用/仅提示。
                switch (service.ExternalPolicy)
                {
                    case ServiceExternalPolicy.Reuse:
                        // 外部实例（Windows 服务/Session 0 自启/手动启动）不自动清理：
                        // 直接复用，避免启动管理器自动重启用户正在使用的实例。
                        // 用户显式点"停止"时 StopService 才会优雅关闭。
                        _log($"{service.Name} 已在端口 {service.Port} 运行，直接复用现有实例（跳过重复启动）。");
                        return;

                    case ServiceExternalPolicy.Refuse:
                        // 外部进程占用：只显示占用信息，不杀不清理（Safety 原则）。
                        // 例外：占用进程可执行文件路径与本服务配置完全一致（如
                        // D:\APP_SOFT\MongoDB\bin\mongod.exe），判定为"启动器上次拉起的
                        // 自家残留"，接管复用以便后续可停止；路径不同（用户自建实例）
                        // 仍按外部进程 refuse。
                        service.AdoptedExe = null; // 本分支重算接管标记，先清残留
                        var refusePids = LauncherPorts.GetPidsByPort(service.Port);
                        var serviceExe = Path.GetFullPath(service.FileName);
                        var adopted = false;
                        foreach (var pid in refusePids)
                        {
                            try
                            {
                                using var proc = Process.GetProcessById(pid);
                                var procExe = proc.MainModule?.FileName;
                                if (!string.IsNullOrWhiteSpace(procExe) &&
                                    string.Equals(
                                        Path.GetFullPath(procExe),
                                        serviceExe,
                                        StringComparison.OrdinalIgnoreCase))
                                {
                                    service.Process = Process.GetProcessById(pid);
                                    service.AdoptedExe = Path.GetFullPath(procExe);
                                    _log(
                                        $"{service.Name} 端口 {service.Port} 被启动器上次拉起的进程占用" +
                                        $"（PID {pid}），已接管复用（可正常停止）。");
                                    adopted = true;
                                    break;
                                }
                            }
                            catch
                            {
                                // MainModule 不可读（权限/已退出）或进程退出，忽略该 PID
                            }
                        }
                        if (adopted) return;

                        _log(
                            $"{service.Name} 端口 {service.Port} 被外部进程占用" +
                            (refusePids.Count > 0 ? $"（PID {string.Join(", ", refusePids)}）" : "") +
                            "，按 refuse 策略不自动清理，请手动确认后处理。");
                        return;

                    default: // Managed：清理孤儿进程后重启
                        _log($"{service.Name} 端口 {service.Port} 被未知进程占用，尝试清理...");
                        break;
                }
                var pids = LauncherPorts.GetPidsByPort(service.Port);
                foreach (var pid in pids)
                    KillProcessTree(pid, $"端口 {service.Port} (孤儿清理)");
                Thread.Sleep(800);
                // 清理后重新检查：仍被占用时，只要实例可用就直接复用（例如以 Windows 服务/
                // 提权方式运行的实例，普通权限 taskkill 会拒绝访问，但实例本身工作正常）。
                if (LauncherPorts.IsPortOpen(service.Port))
                {
                    var usable = service.Port == 8001
                        ? SnapshotCollectorProbe.GetHealthAsync().GetAwaiter().GetResult().IsHealthy
                        : true;
                    if (usable)
                    {
                        _log($"{service.Name} 已在端口 {service.Port} 运行，直接复用现有实例（跳过重复启动）。");
                        return;
                    }
                    _log(
                        $"{service.Name} 端口 {service.Port} 被不可用进程占用，清理失败（可能权限不足），" +
                        "请手动关闭占用进程后重试。");
                    return;
                }
            }

            if (!Directory.Exists(service.WorkingDirectory))
            {
                _log($"{service.Name} 工作目录不存在: {service.WorkingDirectory}");
                return;
            }

            var fileName = service.FileName;
            var arguments = service.Arguments;
            if (Path.IsPathRooted(fileName) &&
                !File.Exists(fileName) &&
                !string.IsNullOrWhiteSpace(service.FallbackFileName))
            {
                _log($"{service.Name} 可执行文件缺失: {fileName}; 改用 {service.FallbackFileName}。");
                fileName = service.FallbackFileName;
                arguments = service.FallbackArguments ?? service.Arguments;
            }

            var info = CreateHiddenProcessInfo(fileName, arguments, service.WorkingDirectory);

            if (service.EnvVars != null)
                foreach (var kv in service.EnvVars)
                    info.Environment[kv.Key] = kv.Value;
            if (service.IsVoiceWorker)
                LoadVoiceWorkerEnv(info);

            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            var logPolicy = service.LogPolicy;
            process.OutputDataReceived += (_, e) =>
            {
                if (string.IsNullOrWhiteSpace(e.Data)) return;
                // ErrorsOnly：stdout 全忽略（如行情桥的 INFO 轮询噪音）。
                if (logPolicy.ErrorsOnly) return;
                if (ShouldSuppressChildOutput(e.Data, logPolicy)) return;
                EnqueueChildLog(service.Name, e.Data);
            };
            process.ErrorDataReceived += (_, e) =>
            {
                if (string.IsNullOrWhiteSpace(e.Data)) return;
                if (logPolicy.ErrorsOnly && !LooksLikeErrorOutput(e.Data)) return;
                if (ShouldSuppressChildOutput(e.Data, logPolicy)) return;
                EnqueueChildLog(service.Name, e.Data);
            };
            process.Exited += (_, _) => _log($"{service.Name} 已退出。");

            if (!process.Start())
            {
                _log($"启动 {service.Name} 失败。");
                return;
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            service.Process = process;
            service.PortOwnerProcess = null;
            service.AdoptedExe = null; // 新拉起进程非接管，清 Refuse 接管标记
            _log($"已启动 {service.Name}，PID={process.Id}。");
            // 后台跟踪实际监听进程（uvicorn 启动慢，可能远超 5 秒），不阻塞后续核心服务启动。
            _ = Task.Run(() => TrackPortOwner(service));
        }
        catch (Exception ex)
        {
            _log($"启动 {service.Name} 失败: {ex.Message}");
        }
        finally
        {
            _starting.Remove(service.Name);
            // Redis 等服务的 RDB 文件可能被 SYSTEM 权限污染（历史遗留，
            // 如 RedisService.exe install 装成服务、或以管理员身份跑过一次），
            // 导致后续以普通用户启动时 BGSAVE 无法覆盖。启动/复用后检查所有者，
            // 异常时自动提权修复（takeown + icacls）。
            try { EnsureDumpRdbAccessible(service); }
            catch { /* 权限检测失败不阻塞启动流程 */ }
        }
    }

    /// <summary>
    /// 记录实际监听端口的进程（uvicorn 在 Windows 上会 spawn 子进程承载真 server：
    /// launcher 拉起的引导进程不监听端口）。仅对 uvicorn 类服务（命令含 "uvicorn"）
    /// 执行，后台跟踪，最多等待 20 秒（量化后端启动较慢，5 秒窗口会误报）；
    /// 单进程服务（监听 PID == 引导 PID）不记录。
    /// PortOwnerProcess 只用于停止时优先终止，不替换 service.Process（引导进程
    /// 仍为托管对象，负责生命周期与输出）。
    /// 身份校验：候选监听进程必须满足"父进程链包含引导进程"（uvicorn spawn 的
    /// 子进程，父进程是 launcher 拉起的引导进程）。
    /// 不能用 MainModule.FileName 比对——venv python.exe 是系统 python 的重定向器，
    /// 实际二进制路径与 service.FileName（venv 路径）不一致。
    /// </summary>
    private void TrackPortOwner(ManagedService service)
    {
        if (!service.Arguments.Contains("uvicorn", StringComparison.OrdinalIgnoreCase))
            return; // 非 spawn 型服务不处理

        try
        {
            var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(20);
            while (DateTime.UtcNow < deadline)
            {
                var pids = LauncherPorts.GetPidsByPort(service.Port);
                if (pids.Count > 0)
                {
                    var guidedPid = service.Process is { HasExited: false } ? service.Process.Id : 0;
                    if (pids.Contains(guidedPid))
                        return; // 单进程：引导进程即监听者

                    foreach (var ownerPid in pids)
                    {
                        if (IsDescendantOf(ownerPid, guidedPid))
                        {
                            try
                            {
                                service.PortOwnerProcess = Process.GetProcessById(ownerPid);
                                _log(
                                    $"{service.Name} 实际监听进程 PID={ownerPid}" +
                                    (guidedPid > 0 ? $"（引导进程 PID={guidedPid}）" : "") + "。");
                            }
                            catch
                            {
                                // 进程瞬间退出，跳过该 PID
                            }
                            return;
                        }
                    }

                    _log(
                        $"{service.Name} 端口 {service.Port} 监听进程与引导进程无父子关系，不记录为托管。" +
                        $"（端口 PID: {string.Join(", ", pids)}，引导 PID: {guidedPid}）");
                    return;
                }
                Thread.Sleep(500);
            }

            _log($"{service.Name} 启动后 20 秒内未检测到端口 {service.Port} 监听进程，无法跟踪实际监听进程。");
        }
        catch (Exception ex)
        {
            _log($"跟踪 {service.Name} 端口监听进程失败: {ex.Message}");
        }
    }

    /// <summary>判断 candidatePid 是否是指定引导进程（或其后代）的子进程。</summary>
    private static bool IsDescendantOf(int candidatePid, int ancestorPid)
    {
        if (ancestorPid <= 0) return false;
        try
        {
            var seen = new HashSet<int> { candidatePid };
            var parent = ParentPidOf(candidatePid);
            while (parent > 0 && seen.Add(parent))
            {
                if (parent == ancestorPid) return true;
                parent = ParentPidOf(parent);
            }
            return false;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>查询指定进程的父进程 PID（PowerShell Get-CimInstance，进程退出返回 0）。</summary>
    private static int ParentPidOf(int pid)
    {
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments =
                    "-NoProfile -Command \"(Get-CimInstance Win32_Process -Filter 'ProcessId=" +
                    pid + "').ParentProcessId\"",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true
            };
            using var process = Process.Start(info);
            if (process == null) return 0;
            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(3000);
            var trimmed = output.Trim();
            return int.TryParse(trimmed, out var parentPid) ? parentPid : 0;
        }
        catch
        {
            return 0;
        }
    }

    public void StopService(ManagedService service)
    {
        try
        {
            if (service.Port == 27017)
                StopMongoExpress();

            if (service.Port == 6379)
            {
                StopRedisCommander();
                StopRedisService();
            }

            if (service.IsVoiceWorker)
            {
                StopVoiceWorkerProcesses(service);
                return;
            }

            // 只停止启动器自己拉起的进程树。
            StopStartedProcess(service);

            // 端口清理按 externalPolicy：
            // - Refuse：外部进程不杀（Safety 原则），仅停自家托管进程；
            // - Managed：连同占用端口的孤儿进程一并清理，避免残留。
            if (service.ExternalPolicy == ServiceExternalPolicy.Refuse)
                return;

            var pids = LauncherPorts.GetPidsByPort(service.Port);
            foreach (var pid in pids)
            {
                KillProcessTree(pid, $"端口 {service.Port}");
            }
        }
        catch (Exception ex)
        {
            _log($"停止 {service.Name} 失败: {ex.Message}");
        }
    }

    public void StopStartedProcesses()
    {
        StopMongoExpress();
        StopRedisCommander();
        // 用 StopService 而非 StopStartedProcess，确保端口占用的孤儿进程也会被杀掉
        StopService(_services["quant-ui"]);
        StopService(_services["quant-api"]);
        StopService(_services["collector"]);
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services[LauncherServices.VoiceServiceKey]);
        StopService(_services["proxy"]);
        StopService(_services["redis"]);
        StopService(_services["mongo"]);
        ShutdownLogQueue();
    }

    /// <summary>停止后台日志消费线程（launcher 退出时），把队列剩余行刷完。</summary>
    private void ShutdownLogQueue()
    {
        try
        {
            _logQueue.CompleteAdding();
            _logCts.Cancel();
            if (_logThread.IsAlive && !_logThread.Join(2000))
            {
                // 消费线程未及时退出（极端情况），后台线程随进程退出
            }
        }
        catch
        {
            // 清理失败不阻塞退出
        }
    }

    public void StartRedisCommander()
    {
        if (_redisCommanderProcess is { HasExited: false }) return;
        if (LauncherPorts.IsPortOpen(8082))
        {
            _log("Redis Commander 已在端口 8082 运行。");
            return;
        }

        try
        {
            var rcBin = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "npm",
                "node_modules",
                "redis-commander",
                "bin",
                "redis-commander.js");
            var info = CreateHiddenProcessInfo(
                "node",
                $"\"{rcBin}\" --redis-host 127.0.0.1 --redis-port 6379 --port 8082 --address 127.0.0.1",
                _root);

            _redisCommanderProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
            _redisCommanderProcess.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[Redis Commander] {e.Data}"); };
            _redisCommanderProcess.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[Redis Commander] {e.Data}"); };
            _redisCommanderProcess.Start();
            _redisCommanderProcess.BeginOutputReadLine();
            _redisCommanderProcess.BeginErrorReadLine();
            _log("已启动 Redis Commander (8082)，PID=" + _redisCommanderProcess.Id + "。");
        }
        catch (Exception ex)
        {
            _log($"启动 Redis Commander 失败: {ex.Message}");
        }
    }

    public void StartMongoExpress()
    {
        if (_mongoExpressProcess is { HasExited: false }) return;
        if (LauncherPorts.IsPortOpen(8081))
        {
            _log("Mongo Express 已在端口 8081 运行。");
            return;
        }

        try
        {
            var meApp = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "npm",
                "node_modules",
                "mongo-express",
                "app.js");
            var info = CreateHiddenProcessInfo("node", $"\"{meApp}\"", _root);
            info.Environment["ME_CONFIG_MONGODB_URL"] = "mongodb://localhost:27017";
            info.Environment["ME_CONFIG_MONGODB_ENABLE_ADMIN"] = "true";
            info.Environment["VCAP_APP_HOST"] = "127.0.0.1";
            info.Environment["ME_CONFIG_SITE_SESSIONSECRET"] = "dragon-board-me";

            _mongoExpressProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
            _mongoExpressProcess.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[Mongo Express] {e.Data}"); };
            _mongoExpressProcess.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[Mongo Express] {e.Data}"); };
            _mongoExpressProcess.Start();
            _mongoExpressProcess.BeginOutputReadLine();
            _mongoExpressProcess.BeginErrorReadLine();
            _log("已启动 Mongo Express (8081)，PID=" + _mongoExpressProcess.Id + "。");
        }
        catch (Exception ex)
        {
            _log($"启动 Mongo Express 失败: {ex.Message}");
        }
    }

    public static bool IsServiceRunning(ManagedService service)
    {
        if (service.IsVoiceWorker)
            return VoiceWorkerProbe.IsHealthy();

        if (service.Port is 5173 or 5174)
            return LauncherPorts.IsTcpListeningOn("127.0.0.1", service.Port);

        return LauncherPorts.IsPortOpen(service.Port);
    }

    /// <summary>
    /// 检查服务配置的 RDB 文件（如 Redis dump.rdb）所有者是否正常；所有者异常
    /// （如被 SYSTEM 接管）时自动提权修复。根治"SYSTEM 权限 dump.rdb 导致
    /// BGSAVE 覆盖失败"的问题（2026-08-14 复盘）。
    /// </summary>
    private void EnsureDumpRdbAccessible(ManagedService service)
    {
        var path = service.DumpRdbPath;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return;

        string? owner;
        try
        {
            owner = new FileInfo(path).GetAccessControl()
                .GetOwner(typeof(System.Security.Principal.NTAccount))
                ?.ToString();
        }
        catch
        {
            return; // 无法读取 ACL（文件被占用/已删除），跳过不阻塞启动
        }

        if (string.IsNullOrWhiteSpace(owner))
            return;

        var expected = service.DumpRdbOwner;
        if (string.IsNullOrWhiteSpace(expected))
            expected = System.Security.Principal.WindowsIdentity.GetCurrent().Name;

        if (string.Equals(owner, expected, StringComparison.OrdinalIgnoreCase))
            return; // 所有者正常，无需修复

        _log(
            $"{service.Name} 检测到 {Path.GetFileName(path)} 所有者异常" +
            $"（当前 {owner}，期望 {expected}），自动提权修复权限...");
        RunDumpRdbFix(path, expected);
    }

    /// <summary>用户取消过 UAC 提权后，本进程生命周期内不再重复弹窗。</summary>
    private static bool _dumpRdbFixDeclined;

    /// <summary>
    /// cmd /c 拼接注入防护：path/owner 只允许不含 cmd 元字符的文本
    /// （& | &lt; &gt; ^ ( ) % ! " 等会改变命令解析）。配置受信，但防御纵深
    /// 防配置被篡改或特殊账户名导致注入。含元字符时跳过修复并记录。
    /// </summary>
    private static bool IsSafeAclArgument(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return false;
        foreach (var ch in value)
        {
            if (ch == '&' || ch == '|' || ch == '<' || ch == '>' ||
                ch == '^' || ch == '(' || ch == ')' || ch == '%' ||
                ch == '!' || ch == '"')
                return false;
        }
        return true;
    }

    /// <summary>用 UAC 提权执行 takeown + icacls，把 RDB 文件所有者与访问权限改回指定账户。</summary>
    private void RunDumpRdbFix(string path, string owner)
    {
        if (_dumpRdbFixDeclined)
            return; // 用户已取消过提权，本进程生命周期不再重复弹 UAC
        // 注入防护：非法参数直接跳过修复（权限问题保留，不引入命令注入面）
        if (!IsSafeAclArgument(path) || !IsSafeAclArgument(owner))
        {
            _log($"dump.rdb 权限修复参数含不安全字符，跳过（path={path} owner={owner}）。");
            return;
        }
        // 三条命令串成一条 cmd：先取所有权（/a 交给 Administrators），再重置 ACL，
        // 最后给目标账户完全控制。takeown/icacls 需要管理员权限，故 runas 提权。
        var command =
            $"takeown /f \"{path}\" /a && " +
            $"icacls \"{path}\" /reset && " +
            $"icacls \"{path}\" /grant \"{owner}:(F)\"";
        var info = new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = $"/c {command}",
            Verb = "runas",
            UseShellExecute = true,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden
        };
        try
        {
            using var process = Process.Start(info);
            if (process is null)
            {
                _log("无法启动 dump.rdb 权限修复进程。");
                return;
            }
            process.WaitForExit(20000);
            if (process.ExitCode == 0)
                _log("dump.rdb 权限修复完成（takeown + icacls）。");
            else
            {
                _dumpRdbFixDeclined = true; // 非 0 退出：多半是用户取消，不再重复弹
                _log($"dump.rdb 权限修复命令退出码 {process.ExitCode}（可能用户取消了 UAC 提权）。");
            }
        }
        catch (System.ComponentModel.Win32Exception ex) when (ex.NativeErrorCode == 1223)
        {
            // ERROR_CANCELLED（1223）：用户在 UAC 弹窗点了"否"。
            _dumpRdbFixDeclined = true; // 用户明确拒绝，本进程生命周期不再重复弹窗
            _log("用户取消了 UAC 提权，dump.rdb 权限未修复（不影响其余服务启动）。");
        }
        catch (Exception ex)
        {
            _log($"dump.rdb 权限修复失败: {ex.Message}");
        }
    }

    private static ProcessStartInfo CreateHiddenProcessInfo(
        string fileName,
        string arguments,
        string workingDirectory)
    {
        return new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory,
            CreateNoWindow = true,
            UseShellExecute = false,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
    }

    private void LoadVoiceWorkerEnv(ProcessStartInfo info)
    {
        var envPath = Path.Combine(_root, "tools", "VoiceWorker", ".env.local");
        var values = EnvFileLoader.Load(envPath);
        if (values.Count == 0) return;

        foreach (var kv in values)
            info.Environment[kv.Key] = kv.Value;

        _log($"本地语音服务已加载环境变量: {envPath} ({values.Count} 项)。");
    }

    private void StopMongoExpress()
    {
        if (_mongoExpressProcess is not { HasExited: false }) return;
        try
        {
            _mongoExpressProcess.Kill(entireProcessTree: true);
            _mongoExpressProcess.WaitForExit(3000);
            _log("Mongo Express 已停止。");
        }
        catch (Exception ex)
        {
            _log($"停止 Mongo Express 失败: {ex.Message}");
        }
    }

    private void StopRedisCommander()
    {
        if (_redisCommanderProcess is not { HasExited: false }) return;
        try
        {
            _redisCommanderProcess.Kill(entireProcessTree: true);
            _redisCommanderProcess.WaitForExit(3000);
            _log("Redis Commander 已停止。");
        }
        catch (Exception ex)
        {
            _log($"停止 Redis Commander 失败: {ex.Message}");
        }
    }

    private void StopRedisService()
    {
        // 优先级：redis-cli 优雅关闭（不依赖进程权限，可停 Session 0/服务方式实例）
        // → sc 停止 Windows 服务 → taskkill 兜底。
        if (TryShutdownRedisViaCli()) return;
        TryStopRedisScService();
    }

    private bool TryShutdownRedisViaCli()
    {
        var redisDir = _services["redis"].WorkingDirectory;
        var redisCli = Path.Combine(redisDir, "redis-cli.exe");
        if (!File.Exists(redisCli))
            redisCli = "redis-cli";

        try
        {
            var info = new ProcessStartInfo
            {
                FileName = redisCli,
                // 关闭时默认 SAVE（落盘 dump.rdb），让预热缓存（量比 daily / RankTrend
                // frame_bundles）持久化，重启后首屏直接命中，无需等待预热重跑。
                // 此前用 "shutdown nosave" 会丢弃内存缓存，导致 RDB 冷启动容灾失效。
                Arguments = "-p 6379 shutdown",
                WorkingDirectory = redisDir,
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            using var process = Process.Start(info);
            if (process == null)
                return false;

            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit(5000);
            if (process.ExitCode == 0)
            {
                _log("已通过 redis-cli 请求停止 Redis。");
                WaitForPortClosed(6379, TimeSpan.FromSeconds(3));
                return true;
            }

            var detail = string.IsNullOrWhiteSpace(error) ? output : error;
            if (string.IsNullOrWhiteSpace(detail))
                _log("redis-cli 停止 Redis 未成功（可能已停止、未运行或需密码认证）。");
            else
                _log($"redis-cli 停止 Redis 未成功: {TrimDetail(detail)}");
        }
        catch (Exception ex)
        {
            _log($"redis-cli 停止 Redis 失败: {ex.Message}");
        }
        return false;
    }

    private void TryStopRedisScService()
    {
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = "sc.exe",
                Arguments = "stop Redis",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            using var process = Process.Start(info);
            if (process == null)
                return;

            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit(5000);
            if (process.ExitCode == 0)
            {
                _log("已请求停止 Redis Windows 服务。");
                WaitForPortClosed(6379, TimeSpan.FromSeconds(3));
            }
            else if (!string.IsNullOrWhiteSpace(output) || !string.IsNullOrWhiteSpace(error))
                // 不输出 sc.exe 原始内容：控制台代码页输出按 UTF-8 读取会变乱码，
                // 非零状态通常是"非服务方式运行或服务未注册"，无需展开原始文本。
                _log("停止 Redis Windows 服务返回非零状态（可能非服务方式运行或服务未注册）。");
        }
        catch (Exception ex)
        {
            _log($"停止 Redis Windows 服务失败: {ex.Message}");
        }
    }

    private static void WaitForPortClosed(int port, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (!LauncherPorts.IsPortOpen(port)) return;
            Thread.Sleep(150);
        }
    }

    private static bool LooksLikeErrorOutput(string text)
    {
        return ContainsAny(text,
            "ERROR", "WARNING", "WARN", "Exception", "Traceback",
            "错误", "警告", "异常", "失败");
    }

    /// <summary>
    /// 按服务日志策略过滤子进程输出，防止单日日志被访问日志刷爆：
    /// - FilterAccess：过滤 uvicorn/fastapi 访问日志行与 proxy-server 每请求行；
    /// - All：不过滤访问日志（全量落盘）；
    /// - suppressHealth：额外抑制健康检查请求行（GET /health、GET /api/health）。
    /// 错误/警告/异常行不受影响（由 LooksLikeErrorOutput 保底）。
    /// </summary>
    private static bool ShouldSuppressChildOutput(string text, ServiceLogPolicy policy)
    {
        var trimmed = text.Trim();
        if (trimmed.Length == 0) return false;

        // 错误/警告绝不丢：先排除再判断噪音，避免把异常内容过滤掉。
        if (LooksLikeErrorOutput(trimmed)) return false;

        // 健康检查行：suppressHealth 时抑制（含错误行已在上面放行，这里只过滤正常健康检查）。
        if (policy.SuppressHealth &&
            (trimmed.Contains("GET /api/health", StringComparison.Ordinal) ||
             trimmed.EndsWith("GET /health", StringComparison.Ordinal)))
            return true;

        // 仅 FilterAccess 级别过滤访问日志；All 级别全量保留。
        if (policy.Level != ServiceLogLevel.FilterAccess)
            return false;

        // uvicorn 访问日志：INFO:     127.0.0.1:53390 - "GET /api/health HTTP/1.1" 200 OK
        if (trimmed.StartsWith("INFO:", StringComparison.Ordinal) &&
            trimmed.Contains("HTTP/1.1\"", StringComparison.Ordinal))
            return true;

        // proxy-server 每请求日志：[HH:mm:ss] METHOD /path
        if (Regex.IsMatch(trimmed, @"^\[\d{2}:\d{2}:\d{2}\] (GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS) "))
            return true;

        return false;
    }

    private static bool ContainsAny(string text, params string[] needles)
    {
        return needles.Any(needle => text.Contains(needle, StringComparison.OrdinalIgnoreCase));
    }

    private static string TrimDetail(string text)
    {
        const int maxChars = 200;
        var value = text.Trim();
        return value.Length <= maxChars ? value : value[..maxChars] + "...";
    }

    private void StopStartedProcess(ManagedService service)
    {
        try
        {
            // 先终止实际监听端口的进程（uvicorn spawn 的真 server 子进程），
            // 再终止 launcher 拉起的引导进程，避免 reloader 残留拉起新 worker。
            // 安全：Kill 前重新验证 owner 仍是引导进程的后代且仍监听本服务端口，
            // 防止启动后 PID 被 OS 复用给无关进程导致误杀（TOCTOU）。
            var owner = service.PortOwnerProcess;
            service.PortOwnerProcess = null;
            var guidedPid = service.Process is { HasExited: false } ? service.Process.Id : 0;
            if (owner is { HasExited: false } &&
                IsDescendantOf(owner.Id, guidedPid) &&
                LauncherPorts.GetPidsByPort(service.Port).Contains(owner.Id))
            {
                try
                {
                    owner.Kill(entireProcessTree: true);
                    owner.WaitForExit(3000);
                    _log($"已停止 {service.Name} 实际监听进程。");
                }
                catch (Exception ex)
                {
                    _log($"停止 {service.Name} 实际监听进程失败: {ex.Message}");
                }
            }
            else if (owner is { HasExited: false })
            {
                _log(
                    $"{service.Name} 实际监听进程 PID={owner.Id} 已不满足托管条件" +
                    "（父进程链或端口监听变化，疑似 PID 复用），跳过直接终止，仅停引导进程树。");
            }

            if (service.Process is { HasExited: false })
            {
                // Refuse 接管的外部进程（自家残留）：终止前核对 exe 路径仍匹配，
                // 防 PID 复用后误杀其它进程；不匹配则仅提示不杀。
                if (!string.IsNullOrWhiteSpace(service.AdoptedExe))
                {
                    try
                    {
                        var exe = service.Process.MainModule?.FileName;
                        var stillMatches = !string.IsNullOrWhiteSpace(exe) &&
                            string.Equals(
                                Path.GetFullPath(exe),
                                service.AdoptedExe,
                                StringComparison.OrdinalIgnoreCase);
                        if (!stillMatches)
                        {
                            _log(
                                $"{service.Name} 接管进程 PID={service.Process.Id} 可执行文件已变化，" +
                                "跳过终止（疑似 PID 复用，请手动处理）。");
                            return;
                        }
                    }
                    catch
                    {
                        // MainModule 不可读（权限/已退出），按不匹配处理不杀
                        _log($"{service.Name} 接管进程 PID={service.Process.Id} 无法核对可执行文件，跳过终止。");
                        return;
                    }
                }

                service.Process.Kill(entireProcessTree: true);
                service.Process.WaitForExit(3000);
                _log($"已停止 {service.Name} 进程树。");
            }
        }
        catch (Exception ex)
        {
            _log($"停止 {service.Name} 进程树失败: {ex.Message}");
        }
        finally
        {
            service.Process = null;
            service.PortOwnerProcess = null;
            service.AdoptedExe = null;
        }
    }

    private void StopVoiceWorkerProcesses(ManagedService service)
    {
        StopStartedProcess(service);
        StopVoiceWorkerExecutableProcesses(service);

        if (VoiceWorkerProbe.IsHealthy())
        {
            if (VoiceWorkerProbe.Shutdown())
                _log("已请求本地语音服务自退出。");
            Thread.Sleep(500);
        }

        if (VoiceWorkerProbe.IsHealthy())
            _log("本地语音服务仍在运行，请检查是否有其它 VoiceWorker 实例。");
    }

    private void StopVoiceWorkerExecutableProcesses(ManagedService service)
    {
        var voiceWorkerBin = Path.GetFullPath(Path.Combine(
            service.WorkingDirectory,
            "tools",
            "VoiceWorker",
            "bin"));
        var currentPaths = GetCurrentVoiceWorkerExecutablePaths(service)
            .Select(Path.GetFullPath)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        foreach (var process in Process.GetProcessesByName("VoiceWorker"))
        {
            try
            {
                var path = process.MainModule?.FileName;
                if (string.IsNullOrWhiteSpace(path))
                {
                    continue;
                }

                var fullPath = Path.GetFullPath(path);
                if (!currentPaths.Contains(fullPath) &&
                    !fullPath.StartsWith(voiceWorkerBin + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                process.Kill(entireProcessTree: true);
                process.WaitForExit(3000);
                _log($"已停止 {service.Name} 进程树，PID={process.Id}。");
            }
            catch (Exception ex)
            {
                _log($"停止 {service.Name} 进程失败: {ex.Message}");
            }
            finally
            {
                process.Dispose();
            }
        }
    }

    private static IEnumerable<string> GetCurrentVoiceWorkerExecutablePaths(ManagedService service)
    {
        yield return service.FileName;
        yield return Path.Combine(
            service.WorkingDirectory,
            "tools",
            "VoiceWorker",
            "bin",
            "Debug",
            "net8.0-windows10.0.19041.0",
            "VoiceWorker.exe");
    }

    private static bool IsCurrentVoiceWorkerHealthy(ManagedService service)
    {
        var health = VoiceWorkerProbe.GetHealth();
        if (!health.IsHealthy)
        {
            return true;
        }

        var processPath = health.ProcessPath;
        if (string.IsNullOrWhiteSpace(processPath))
        {
            return false;
        }

        var fullPath = Path.GetFullPath(processPath);
        var currentPaths = GetCurrentVoiceWorkerExecutablePaths(service)
            .Select(Path.GetFullPath)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        return currentPaths.Contains(fullPath);
    }

    private void KillProcessTree(int pid, string label)
    {
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                Arguments = $"/PID {pid} /T /F",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            using var process = Process.Start(info);
            if (process == null)
                return;

            var output = process.StandardOutput.ReadToEnd();
            var error = process.StandardError.ReadToEnd();
            process.WaitForExit(5000);
            if (process.ExitCode == 0)
            {
                _log($"已终止{label}进程树，PID={pid}。");
            }
            else
            {
                // 非零通常表示权限不足（如 Session 0 系统级进程）或进程已退出；
                // 明示出来，避免面板按钮"无反应"。
                var reason = string.IsNullOrWhiteSpace(error) ? output.Trim() : error.Trim();
                _log(
                    string.IsNullOrWhiteSpace(reason)
                        ? $"无法终止{label}进程树，PID={pid}（taskkill 退出码 {process.ExitCode}）。"
                        : $"无法终止{label}进程树，PID={pid}（taskkill 退出码 {process.ExitCode}）: {TrimDetail(reason)}");
            }
        }
        catch (Exception ex)
        {
            _log($"无法终止{label}进程树，PID={pid}: {ex.Message}");
        }
    }
}
