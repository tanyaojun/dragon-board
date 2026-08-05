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

    public LauncherProcessManager(
        string root,
        IReadOnlyDictionary<string, ManagedService> services,
        Action<string> log)
    {
        _root = root;
        _services = services;
        _log = log;
    }

    public void StartAll()
    {
        // 阶段名与 LauncherServices.CoreStartupStages 顺序对齐（P1.1 修正：
        // 基础设施→实时数据源→量化后端→快照采集，原"快照采集/量化后端"顺序写反）。
        // stages 阶段数来自 services.json 可配置；超出内置名单时回退"阶段 N"。
        var stageNames = new[] { "基础设施", "实时数据源", "量化后端", "快照采集" };
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

            var unavailable = stage
                .Where(key => !IsServiceReady(_services[key]))
                .Select(key => $"{_services[key].Name}({_services[key].Port})");
            _log($"核心启动错误: 依赖未就绪，已中止后续服务: {string.Join(", ", unavailable)}");
            return;
        }

        _log("核心启动完成: MongoDB、Redis、代理、行情桥、快照采集和 Quant API 均已就绪。");
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
                        var refusePids = LauncherPorts.GetPidsByPort(service.Port);
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
            process.OutputDataReceived += (_, e) =>
            {
                if (string.IsNullOrWhiteSpace(e.Data)) return;
                // 只留错误日志的服务（如行情桥）忽略 stdout，避免日志文件被 INFO 轮询刷爆
                if (service.LogOnlyErrors) return;
                if (ShouldSuppressChildOutput(e.Data)) return;
                _log($"[{service.Name}] {e.Data}");
            };
            process.ErrorDataReceived += (_, e) =>
            {
                if (string.IsNullOrWhiteSpace(e.Data)) return;
                if (service.LogOnlyErrors && !LooksLikeErrorOutput(e.Data)) return;
                if (ShouldSuppressChildOutput(e.Data)) return;
                _log($"[{service.Name}] {e.Data}");
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
            _log($"已启动 {service.Name}，PID={process.Id}。");
        }
        catch (Exception ex)
        {
            _log($"启动 {service.Name} 失败: {ex.Message}");
        }
        finally
        {
            _starting.Remove(service.Name);
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
                Arguments = "-p 6379 shutdown nosave",
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
    /// 过滤子进程高频噪音输出，防止单日日志被访问日志刷爆：
    /// 1. uvicorn/fastapi 访问日志行：INFO: 127.0.0.1:53390 - "GET /api/health HTTP/1.1" 200 OK；
    /// 2. proxy-server 每请求日志行：[06:14:11] GET /health、[09:30:47] GET /api/snapshots/frames?...。
    /// 错误/警告/异常行不受影响（由 LooksLikeErrorOutput 保底），启动器自身日志也不受影响。
    /// </summary>
    private static bool ShouldSuppressChildOutput(string text)
    {
        var trimmed = text.Trim();
        if (trimmed.Length == 0) return false;

        // 错误/警告绝不丢：先排除再判断噪音，避免把异常内容过滤掉。
        if (LooksLikeErrorOutput(trimmed)) return false;

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
            if (service.Process is { HasExited: false })
            {
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
