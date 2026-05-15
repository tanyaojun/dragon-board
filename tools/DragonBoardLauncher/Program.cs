using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Text;
using Microsoft.Win32;

namespace DragonBoardLauncher;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new LauncherForm());
    }
}

internal sealed class LauncherForm : Form
{
    private const string AutoStartName = "DragonBoardLauncher";
    private const string VoiceServiceKey = "voice";
    private const int VoiceWorkerPort = 32145;

    private readonly string _root;
    private readonly Dictionary<string, ManagedService> _services;
    private readonly System.Windows.Forms.Timer _timer;

    private readonly TextBox _log = new();
    private readonly Button _autoStartButton = new();
    private Process? _mongoExpressProcess;
    private Process? _redisCommanderProcess;

    private readonly Color _bg = Color.FromArgb(18, 20, 24);
    private readonly Color _cardBg = Color.FromArgb(29, 33, 40);
    private readonly Color _accent = Color.FromArgb(255, 176, 70);
    private readonly Color _green = Color.FromArgb(44, 210, 140);
    private readonly Color _red = Color.FromArgb(235, 75, 85);
    private readonly Color _text = Color.FromArgb(236, 240, 244);
    private readonly Color _subText = Color.FromArgb(140, 155, 170);

    // Per-service UI elements
    private readonly Dictionary<string, Label> _dots = new();
    private readonly Dictionary<string, Label> _statusLabels = new();

    public LauncherForm()
    {
        _root = FindProjectRoot();
        var quantRoot = Path.Combine(_root, "quant-board");
        var voiceWorkerExe = Path.Combine(_root, "tools", "VoiceWorker", "bin", "Release", "net8.0-windows", "VoiceWorker.exe");
        _services = new Dictionary<string, ManagedService>
        {
            ["mongo"] = new("MongoDB 数据库", 27017, @"D:\APP_SOFT\MongoDB\bin", @"D:\APP_SOFT\MongoDB\bin\mongod.exe", @"--dbpath D:\APP_SOFT\MongoDB\data --logpath D:\APP_SOFT\MongoDB\log\mongod.log --port 27017"),
            ["redis"] = new("Redis 缓存", 6379, @"D:\APP_SOFT\redis", @"D:\APP_SOFT\redis\redis-server.exe", @"D:\APP_SOFT\redis\redis.windows-service.conf"),
            ["proxy"] = new("本地代理服务", 3000, Path.Combine(_root, "proxy-server"), "node", "server.js"),
            [VoiceServiceKey] = new(
                "本地语音服务",
                VoiceWorkerPort,
                _root,
                voiceWorkerExe,
                "",
                "dotnet",
                @"run --project tools\VoiceWorker\VoiceWorker.csproj",
                isVoiceWorker: true),
            ["frontend"] = new("龙头看板前端", 5173, _root, "cmd.exe", "/c node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173"),
            ["bridge"] = new("通达信行情桥", 8765, _root, "python", "python-bridge/main.py"),
            ["quant-api"] = new(
                "量化后端 API",
                8000,
                quantRoot,
                Path.Combine(quantRoot, ".venv", "Scripts", "python.exe"),
                "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000",
                "python"),
            ["quant-ui"] = new("量化面板前端", 5174, Path.Combine(quantRoot, "frontend"), "cmd.exe", "/c node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174")
        };

        Text = "龙头看板 · 启动管理器";
        Width = 660;
        Height = 820;
        MinimumSize = new Size(600, 760);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = _bg;
        ForeColor = _text;
        Font = new Font("Microsoft YaHei UI", 9f);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;

        BuildUI();

        _timer = new System.Windows.Forms.Timer { Interval = 3000 };
        _timer.Tick += (_, _) => RefreshStatuses();
        _timer.Start();

        FormClosing += (_, _) =>
        {
            _timer.Stop();
            StopStartedProcesses();
        };
        Shown += (_, _) =>
        {
            Log("启动管理器已就绪。");
            Log($"项目目录: {_root}");
            RefreshStatuses();
        };
    }

    private void BuildUI()
    {
        var titlePanel = new Panel
        {
            Dock = DockStyle.Top,
            Height = 48,
            BackColor = Color.FromArgb(14, 16, 20)
        };
        var titleLabel = new Label
        {
            Text = "龙头看板 · 启动管理器",
            ForeColor = _accent,
            Font = new Font("Microsoft YaHei UI", 14f, FontStyle.Bold),
            Location = new Point(18, 10),
            AutoSize = true
        };
        titlePanel.Controls.Add(titleLabel);
        Controls.Add(titlePanel);

        int y = titlePanel.Bottom + 8;
        var iconKeys = new[] { "DB", "RD", "PX", "VO", "FE", "BR", "QA", "QU" };
        var keys = new[] { "mongo", "redis", "proxy", VoiceServiceKey, "frontend", "bridge", "quant-api", "quant-ui" };
        for (int i = 0; i < keys.Length; i++)
        {
            var card = BuildServiceCard(_services[keys[i]], iconKeys[i], keys[i], y);
            Controls.Add(card);
            y = card.Bottom + 6;
        }

        var btnBarY = y + 8;
        var startAllBtn = new Button
        {
            Text = "一键启动",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(110, 36),
            Location = new Point(18, btnBarY),
            BackColor = _green,
            ForeColor = Color.White,
            Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold),
            Cursor = Cursors.Hand,
        };
        startAllBtn.FlatAppearance.BorderSize = 0;
        startAllBtn.Click += (_, _) => StartAll();
        Controls.Add(startAllBtn);

        var stopAllBtn = new Button
        {
            Text = "全部停止",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(96, 36),
            Location = new Point(134, btnBarY),
            BackColor = _red,
            ForeColor = Color.White,
            Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold),
            Cursor = Cursors.Hand,
        };
        stopAllBtn.FlatAppearance.BorderSize = 0;
        stopAllBtn.Click += (_, _) => StopAll();
        Controls.Add(stopAllBtn);

        var openAppBtn = new Button
        {
            Text = "打开看板",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(86, 36),
            Location = new Point(236, btnBarY),
            BackColor = Color.FromArgb(42, 48, 58),
            ForeColor = _text,
            Font = new Font("Microsoft YaHei UI", 9f),
            Cursor = Cursors.Hand,
        };
        openAppBtn.FlatAppearance.BorderColor = Color.FromArgb(62, 70, 82);
        openAppBtn.Click += (_, _) => OpenUrl("http://127.0.0.1:5173");
        Controls.Add(openAppBtn);

        var openQBtn = new Button
        {
            Text = "打开量化",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(86, 36),
            Location = new Point(328, btnBarY),
            BackColor = Color.FromArgb(42, 48, 58),
            ForeColor = _text,
            Font = new Font("Microsoft YaHei UI", 9f),
            Cursor = Cursors.Hand,
        };
        openQBtn.FlatAppearance.BorderColor = Color.FromArgb(62, 70, 82);
        openQBtn.Click += (_, _) => OpenUrl("http://127.0.0.1:5174");
        Controls.Add(openQBtn);

        _autoStartButton.Text = IsAutoStartEnabled() ? "自启: 开" : "自启: 关";
        _autoStartButton.FlatStyle = FlatStyle.Flat;
        _autoStartButton.Size = new Size(86, 36);
        _autoStartButton.Location = new Point(420, btnBarY);
        _autoStartButton.BackColor = IsAutoStartEnabled() ? Color.FromArgb(52, 82, 62) : Color.FromArgb(42, 48, 58);
        _autoStartButton.ForeColor = _text;
        _autoStartButton.Font = new Font("Microsoft YaHei UI", 9f);
        _autoStartButton.Cursor = Cursors.Hand;
        _autoStartButton.FlatAppearance.BorderColor = Color.FromArgb(62, 70, 82);
        _autoStartButton.Click += (_, _) => ToggleAutoStart();
        Controls.Add(_autoStartButton);

        var logY = btnBarY + 48;
        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.Location = new Point(18, logY);
        _log.Size = new Size(ClientSize.Width - 36, ClientSize.Height - logY - 12);
        _log.Font = new Font("Consolas", 9f);
        _log.BackColor = Color.FromArgb(10, 12, 16);
        _log.ForeColor = Color.FromArgb(198, 210, 225);
        _log.BorderStyle = BorderStyle.FixedSingle;
        _log.Anchor = AnchorStyles.Left | AnchorStyles.Top | AnchorStyles.Right | AnchorStyles.Bottom;
        Controls.Add(_log);
    }

    private Panel BuildServiceCard(ManagedService svc, string icon, string key, int top)
    {
        var p = new Panel
        {
            Location = new Point(18, top),
            Size = new Size(ClientSize.Width - 36, 62),
            BackColor = _cardBg,
        };

        var iconPanel = new Panel
        {
            Size = new Size(36, 36),
            Location = new Point(12, 13),
            BackColor = Color.FromArgb(38, 43, 51)
        };
        iconPanel.Paint += (s, e) =>
        {
            using var brush = new SolidBrush(_accent);
            using var font = new Font("Consolas", 9f, FontStyle.Bold);
            var sz = e.Graphics.MeasureString(icon, font);
            e.Graphics.DrawString(icon, font, brush, (36 - sz.Width) / 2, (36 - sz.Height) / 2);
        };
        p.Controls.Add(iconPanel);

        var nameL = new Label
        {
            Text = svc.Name,
            ForeColor = _text,
            Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold),
            Location = new Point(58, 11),
            AutoSize = true
        };
        p.Controls.Add(nameL);

        var portL = new Label
        {
            Text = $"端口 {svc.Port}",
            ForeColor = _subText,
            Font = new Font("Consolas", 8.5f),
            Location = new Point(59, 34),
            AutoSize = true
        };
        p.Controls.Add(portL);

        var dot = new Label
        {
            Size = new Size(9, 9),
            Location = new Point(p.Width - 250, 15),
            BackColor = _subText,
            Text = ""
        };
        p.Controls.Add(dot);
        _dots[key] = dot;

        var statusL = new Label
        {
            Text = "停止",
            ForeColor = _subText,
            Font = new Font("Microsoft YaHei UI", 8.5f),
            Location = new Point(p.Width - 234, 11),
            AutoSize = true
        };
        p.Controls.Add(statusL);
        _statusLabels[key] = statusL;

        int btnBase = p.Width - 224;

        var startBtn = new Button
        {
            Text = "启动",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(66, 28),
            Location = new Point(btnBase, 31),
            BackColor = Color.FromArgb(42, 98, 72),
            ForeColor = Color.White,
            Font = new Font("Microsoft YaHei UI", 8.5f),
            Cursor = Cursors.Hand,
        };
        startBtn.FlatAppearance.BorderSize = 0;
        startBtn.Click += (_, _) => StartService(svc);
        p.Controls.Add(startBtn);

        var stopBtn = new Button
        {
            Text = "停止",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(66, 28),
            Location = new Point(btnBase + 72, 31),
            BackColor = Color.FromArgb(58, 42, 46),
            ForeColor = _text,
            Font = new Font("Microsoft YaHei UI", 8.5f),
            Cursor = Cursors.Hand,
        };
        stopBtn.FlatAppearance.BorderSize = 0;
        stopBtn.Click += (_, _) => StopService(svc);
        p.Controls.Add(stopBtn);

        if (svc.Port is 5173 or 5174 or 3000 or 8000 or 8765 or 27017 or 6379)
        {
            var openBtn = new Button
            {
                Text = "打开",
                FlatStyle = FlatStyle.Flat,
                Size = new Size(66, 28),
                Location = new Point(btnBase + 144, 31),
                BackColor = Color.FromArgb(42, 48, 58),
                ForeColor = _text,
                Font = new Font("Microsoft YaHei UI", 8.5f),
                Cursor = Cursors.Hand,
            };
            openBtn.FlatAppearance.BorderSize = 0;
            var url = svc.Port switch
            {
                5173 => "http://127.0.0.1:5173",
                5174 => "http://127.0.0.1:5174",
                8000 => "http://127.0.0.1:8000/docs",
                8765 => "http://127.0.0.1:8765/docs",
                27017 => "http://127.0.0.1:8081",
                6379 => "http://127.0.0.1:8082",
                _ => "http://127.0.0.1:3000/docs"
            };
            openBtn.Click += (_, _) =>
            {
                if (svc.Port == 6379)
                    StartRedisCommander();
                OpenUrl(url);
            };
            p.Controls.Add(openBtn);
        }

        return p;
    }

    private void StartAll()
    {
        StartService(_services["mongo"]);
        StartService(_services["redis"]);
        StartService(_services["proxy"]);
        StartService(_services[VoiceServiceKey]);
        StartService(_services["frontend"]);
        StartService(_services["bridge"]);
        StartService(_services["quant-api"]);
        StartService(_services["quant-ui"]);
        RefreshStatuses();
    }

    private void StopAll()
    {
        StopService(_services["quant-ui"]);
        StopService(_services["quant-api"]);
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services[VoiceServiceKey]);
        StopService(_services["proxy"]);
        StopService(_services["redis"]);
        StopService(_services["mongo"]);
        RefreshStatuses();
    }

    private void StartService(ManagedService service)
    {
        try
        {
            // 联动服务在主服务启动前/已运行时也要确保启动
            if (service.Port == 27017)
                StartMongoExpress();
            if (service.Port == 6379)
                StartRedisCommander();

            if (IsServiceRunning(service))
            {
                Log($"{service.Name} 已在端口 {service.Port} 运行。");
                return;
            }

            if (!Directory.Exists(service.WorkingDirectory))
            {
                Log($"{service.Name} 工作目录不存在: {service.WorkingDirectory}");
                return;
            }

            var fileName = service.FileName;
            var arguments = service.Arguments;
            if (Path.IsPathRooted(fileName) &&
                !File.Exists(fileName) &&
                !string.IsNullOrWhiteSpace(service.FallbackFileName))
            {
                Log($"{service.Name} 可执行文件缺失: {fileName}; 改用 {service.FallbackFileName}。");
                fileName = service.FallbackFileName;
                arguments = service.FallbackArguments ?? service.Arguments;
            }

            var info = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = service.WorkingDirectory,
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };

            if (service.EnvVars != null)
                foreach (var kv in service.EnvVars)
                    info.Environment[kv.Key] = kv.Value;

            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[{service.Name}] {e.Data}"); };
            process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[{service.Name}] {e.Data}"); };
            process.Exited += (_, _) => Log($"{service.Name} 已退出。");

            if (!process.Start())
            {
                Log($"启动 {service.Name} 失败。");
                return;
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            service.Process = process;
            Log($"已启动 {service.Name}，PID={process.Id}。");
        }
        catch (Exception ex)
        {
            Log($"启动 {service.Name} 失败: {ex.Message}");
        }
    }

    private void StartMongoExpress()
    {
        if (_mongoExpressProcess is { HasExited: false }) return;
        try
        {
            var meApp = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "npm", "node_modules", "mongo-express", "app.js");
            var info = new ProcessStartInfo
            {
                FileName = "node",
                Arguments = $"\"{meApp}\"",
                WorkingDirectory = _root,
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            info.Environment["ME_CONFIG_MONGODB_URL"] = "mongodb://localhost:27017";
            info.Environment["ME_CONFIG_MONGODB_ENABLE_ADMIN"] = "true";
            info.Environment["VCAP_APP_HOST"] = "127.0.0.1";
            info.Environment["ME_CONFIG_SITE_SESSIONSECRET"] = "dragon-board-me";

            _mongoExpressProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
            _mongoExpressProcess.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[Mongo Express] {e.Data}"); };
            _mongoExpressProcess.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[Mongo Express] {e.Data}"); };
            _mongoExpressProcess.Start();
            _mongoExpressProcess.BeginOutputReadLine();
            _mongoExpressProcess.BeginErrorReadLine();
            Log("已启动 Mongo Express (8081)，PID=" + _mongoExpressProcess.Id + "。");
        }
        catch (Exception ex)
        {
            Log($"启动 Mongo Express 失败: {ex.Message}");
        }
    }

    private void StopMongoExpress()
    {
        if (_mongoExpressProcess is not { HasExited: false }) return;
        try
        {
            _mongoExpressProcess.Kill(entireProcessTree: true);
            _mongoExpressProcess.WaitForExit(3000);
            Log("Mongo Express 已停止。");
        }
        catch (Exception ex)
        {
            Log($"停止 Mongo Express 失败: {ex.Message}");
        }
    }

    private void StartRedisCommander()
    {
        if (_redisCommanderProcess is { HasExited: false }) return;
        if (IsPortOpen(8082))
        {
            Log("Redis Commander 已在端口 8082 运行。");
            return;
        }

        try
        {
            var rcBin = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "npm", "node_modules", "redis-commander", "bin", "redis-commander.js");
            var info = new ProcessStartInfo
            {
                FileName = "node",
                Arguments = $"\"{rcBin}\" --redis-host 127.0.0.1 --redis-port 6379 --port 8082 --address 127.0.0.1",
                WorkingDirectory = _root,
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };

            _redisCommanderProcess = new Process { StartInfo = info, EnableRaisingEvents = true };
            _redisCommanderProcess.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[Redis Commander] {e.Data}"); };
            _redisCommanderProcess.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"[Redis Commander] {e.Data}"); };
            _redisCommanderProcess.Start();
            _redisCommanderProcess.BeginOutputReadLine();
            _redisCommanderProcess.BeginErrorReadLine();
            Log("已启动 Redis Commander (8082)，PID=" + _redisCommanderProcess.Id + "。");
        }
        catch (Exception ex)
        {
            Log($"启动 Redis Commander 失败: {ex.Message}");
        }
    }

    private void StopRedisCommander()
    {
        if (_redisCommanderProcess is not { HasExited: false }) return;
        try
        {
            _redisCommanderProcess.Kill(entireProcessTree: true);
            _redisCommanderProcess.WaitForExit(3000);
            Log("Redis Commander 已停止。");
        }
        catch (Exception ex)
        {
            Log($"停止 Redis Commander 失败: {ex.Message}");
        }
    }

    private void StopService(ManagedService service)
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

            StopStartedProcess(service);

            if (service.IsVoiceWorker)
            {
                if (IsVoiceWorkerHealthy())
                    Log("本地语音服务由外部进程占用，未按端口强制结束。");
                return;
            }

            var pids = GetPidsByPort(service.Port);
            foreach (var pid in pids)
            {
                KillProcessTree(pid, $"端口 {service.Port}");
            }
        }
        catch (Exception ex)
        {
            Log($"停止 {service.Name} 失败: {ex.Message}");
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
                Log("已请求停止 Redis Windows 服务。");
            else if (!string.IsNullOrWhiteSpace(output) || !string.IsNullOrWhiteSpace(error))
                Log($"停止 Redis Windows 服务返回: {(output + error).Trim()}");
        }
        catch (Exception ex)
        {
            Log($"停止 Redis Windows 服务失败: {ex.Message}");
        }
    }

    private void StopStartedProcesses()
    {
        StopMongoExpress();
        StopRedisCommander();
        StopStartedProcess(_services["quant-ui"]);
        StopStartedProcess(_services["quant-api"]);
        StopStartedProcess(_services["bridge"]);
        StopStartedProcess(_services["frontend"]);
        StopStartedProcess(_services[VoiceServiceKey]);
        StopStartedProcess(_services["proxy"]);
        StopStartedProcess(_services["redis"]);
        StopStartedProcess(_services["mongo"]);
    }

    private void StopStartedProcess(ManagedService service)
    {
        try
        {
            if (service.Process is { HasExited: false })
            {
                service.Process.Kill(entireProcessTree: true);
                service.Process.WaitForExit(3000);
                Log($"已停止 {service.Name} 进程树。");
            }
        }
        catch (Exception ex)
        {
            Log($"停止 {service.Name} 进程树失败: {ex.Message}");
        }
        finally
        {
            service.Process = null;
        }
    }

    private void RefreshStatuses()
    {
        var running = 0;
        foreach (var kv in _services)
        {
            var key = kv.Key;
            var svc = kv.Value;
            var isRunning = IsServiceRunning(svc);

            if (_dots.TryGetValue(key, out var dot))
            {
                dot.BackColor = isRunning ? _green : _red;
            }

            if (_statusLabels.TryGetValue(key, out var statusL))
            {
                statusL.Text = isRunning ? "运行中" : "已停止";
                statusL.ForeColor = isRunning ? _green : _red;
            }

            if (isRunning) running++;
        }

        Text = $"龙头看板 · 启动管理器  [{running}/{_services.Count} 在线]";
    }

    private static bool IsPortOpen(int port)
    {
        var properties = IPGlobalProperties.GetIPGlobalProperties();
        return properties.GetActiveTcpListeners().Any(endpoint => endpoint.Port == port)
            || properties.GetActiveTcpConnections().Any(connection =>
                connection.LocalEndPoint.Port == port &&
                connection.State is TcpState.Listen or TcpState.Established);
    }

    private static bool IsServiceRunning(ManagedService service)
    {
        if (service.IsVoiceWorker)
            return IsVoiceWorkerHealthy();

        if (service.Port is 5173 or 5174)
            return IsTcpListeningOn("127.0.0.1", service.Port);

        return IsPortOpen(service.Port);
    }

    private static bool IsVoiceWorkerHealthy()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromMilliseconds(700) };
            var response = client.GetAsync($"http://127.0.0.1:{VoiceWorkerPort}/health").GetAwaiter().GetResult();
            if (!response.IsSuccessStatusCode)
                return false;

            var body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            return body.Contains("\"service\":\"VoiceWorker\"", StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static bool IsTcpListeningOn(string host, int port)
    {
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            var task = client.ConnectAsync(host, port);
            return task.Wait(TimeSpan.FromMilliseconds(500)) && client.Connected;
        }
        catch
        {
            return false;
        }
    }

    private static IReadOnlyList<int> GetPidsByPort(int port)
    {
        var result = new List<int>();
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = "netstat.exe",
                Arguments = "-ano -p tcp",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true
            };
            using var process = Process.Start(info);
            if (process == null) return result;

            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(3000);
            foreach (var line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5 || !IsEndpointForPort(parts[1], port)) continue;
                if (int.TryParse(parts[^1], out var pid) && pid > 0 && !result.Contains(pid))
                    result.Add(pid);
            }
        }
        catch { }
        return result;
    }

    private static bool IsEndpointForPort(string endpoint, int port)
    {
        if (endpoint.EndsWith($":{port}", StringComparison.Ordinal))
            return true;

        return endpoint.Equals($"[::1]:{port}", StringComparison.OrdinalIgnoreCase)
            || endpoint.Equals($"[::]:{port}", StringComparison.OrdinalIgnoreCase);
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
                Log($"已终止{label}进程树，PID={pid}。");
            else
                Log($"无法终止{label}进程树，PID={pid}: {(output + error).Trim()}");
        }
        catch (Exception ex)
        {
            Log($"无法终止{label}进程树，PID={pid}: {ex.Message}");
        }
    }

    private void ToggleAutoStart()
    {
        try
        {
            if (IsAutoStartEnabled())
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", writable: true);
                key?.DeleteValue(AutoStartName, throwOnMissingValue: false);
                Log("已关闭 Windows 自启动。");
            }
            else
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", writable: true)
                    ?? Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", writable: true);
                key.SetValue(AutoStartName, $"\"{Application.ExecutablePath}\"");
                Log("已开启 Windows 自启动。");
            }

            var enabled = IsAutoStartEnabled();
            _autoStartButton.Text = enabled ? "自启: 开" : "自启: 关";
            _autoStartButton.BackColor = enabled ? Color.FromArgb(52, 82, 62) : Color.FromArgb(42, 48, 58);
        }
        catch (Exception ex)
        {
            Log($"切换自启动失败: {ex.Message}");
        }
    }

    private static bool IsAutoStartEnabled()
    {
        using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        var value = Convert.ToString(key?.GetValue(AutoStartName) ?? "");
        return !string.IsNullOrWhiteSpace(value)
            && value.Contains(Application.ExecutablePath, StringComparison.OrdinalIgnoreCase);
    }

    private static void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
        }
        catch { }
    }

    private void Log(string message)
    {
        if (IsDisposed) return;

        if (InvokeRequired)
        {
            try { BeginInvoke(() => Log(message)); }
            catch (InvalidOperationException) { }
            return;
        }

        _log.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
    }

    private static string FindProjectRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (!string.IsNullOrWhiteSpace(dir))
        {
            if (File.Exists(Path.Combine(dir, "package.json")) &&
                Directory.Exists(Path.Combine(dir, "proxy-server")) &&
                Directory.Exists(Path.Combine(dir, "python-bridge")))
                return dir.TrimEnd(Path.DirectorySeparatorChar);

            var parent = Directory.GetParent(dir);
            if (parent == null) break;
            dir = parent.FullName;
        }
        return Directory.GetCurrentDirectory();
    }
}

internal sealed class ManagedService
{
    public ManagedService(
        string name,
        int port,
        string workingDirectory,
        string fileName,
        string arguments,
        string? fallbackFileName = null,
        string? fallbackArguments = null,
        Dictionary<string, string>? envVars = null,
        bool isVoiceWorker = false)
    {
        Name = name;
        Port = port;
        WorkingDirectory = workingDirectory;
        FileName = fileName;
        Arguments = arguments;
        FallbackFileName = fallbackFileName;
        FallbackArguments = fallbackArguments;
        EnvVars = envVars;
        IsVoiceWorker = isVoiceWorker;
    }

    public string Name { get; }
    public int Port { get; }
    public string WorkingDirectory { get; }
    public string FileName { get; }
    public string Arguments { get; }
    public string? FallbackFileName { get; }
    public string? FallbackArguments { get; }
    public Dictionary<string, string>? EnvVars { get; }
    public bool IsVoiceWorker { get; }
    public Process? Process { get; set; }
}
