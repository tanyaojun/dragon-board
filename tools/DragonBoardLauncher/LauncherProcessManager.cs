using System.Diagnostics;
using System.Text;

namespace DragonBoardLauncher;

internal sealed class LauncherProcessManager
{
    private static readonly IReadOnlyDictionary<int, Uri> ReadinessUris =
        new Dictionary<int, Uri>
        {
            [3000] = new("http://127.0.0.1:3000/health"),
            [8765] = new("http://127.0.0.1:8765/health")
        };

    private readonly string _root;
    private readonly IReadOnlyDictionary<string, ManagedService> _services;
    private readonly Action<string> _log;
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
        var stageNames = new[] { "基础设施", "实时数据源", "快照调度" };
        for (var index = 0; index < LauncherServices.CoreStartupStages.Length; index++)
        {
            var stage = LauncherServices.CoreStartupStages[index];
            var stagePorts = string.Join(", ", stage.Select(key => _services[key].Port));
            _log(
                $"核心启动阶段 {index + 1}/{LauncherServices.CoreStartupStages.Length}: " +
                $"{stageNames[index]}（端口 {stagePorts}）。");
            foreach (var key in stage)
                StartService(_services[key]);

            if (WaitForServices(stage, TimeSpan.FromSeconds(30))) continue;

            var unavailable = stage
                .Where(key => !IsServiceReady(_services[key]))
                .Select(key => $"{_services[key].Name}({_services[key].Port})");
            _log($"核心启动错误: 依赖未就绪，已中止后续服务: {string.Join(", ", unavailable)}");
            return;
        }

        _log("核心启动完成: MongoDB、Redis、代理、行情桥和 Quant API 均已就绪。");
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
        if (service.Port == 8000)
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
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services[LauncherServices.VoiceServiceKey]);
        StopService(_services["proxy"]);
        StopService(_services["redis"]);
        StopService(_services["mongo"]);
    }

    public void StartService(ManagedService service)
    {
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
                // 孤儿进程：杀掉后重新启动
                _log($"{service.Name} 端口 {service.Port} 被未知进程占用，尝试清理...");
                // Redis 优先尝试 Windows 服务停止
                if (service.Port == 6379)
                {
                    try
                    {
                        var sc = Process.Start(new ProcessStartInfo("sc.exe", "stop Redis")
                        {
                            CreateNoWindow = true, UseShellExecute = false,
                            RedirectStandardOutput = true, RedirectStandardError = true,
                        });
                        sc?.WaitForExit(5000);
                    }
                    catch { }
                }
                var pids = LauncherPorts.GetPidsByPort(service.Port);
                foreach (var pid in pids)
                    KillProcessTree(pid, $"端口 {service.Port} (孤儿清理)");
                Thread.Sleep(800);
                // 清理后重新检查，仍占用则放弃
                if (LauncherPorts.IsPortOpen(service.Port))
                {
                    _log($"{service.Name} 端口 {service.Port} 清理失败（可能权限不足），请手动关闭占用进程后重试。");
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
            process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[{service.Name}] {e.Data}"); };
            process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) _log($"[{service.Name}] {e.Data}"); };
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

            StopStartedProcess(service);

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
                _log("已请求停止 Redis Windows 服务。");
            else if (!string.IsNullOrWhiteSpace(output) || !string.IsNullOrWhiteSpace(error))
                _log($"停止 Redis Windows 服务返回: {(output + error).Trim()}");
        }
        catch (Exception ex)
        {
            _log($"停止 Redis Windows 服务失败: {ex.Message}");
        }
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
                _log($"已终止{label}进程树，PID={pid}。");
            else
                _log($"无法终止{label}进程树，PID={pid}: {(output + error).Trim()}");
        }
        catch (Exception ex)
        {
            _log($"无法终止{label}进程树，PID={pid}: {ex.Message}");
        }
    }
}
