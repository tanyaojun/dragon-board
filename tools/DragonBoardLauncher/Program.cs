using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
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
    private const int HotkeyId = 0x4452;
    private const int WmHotkey = 0x0312;
    private const uint ModAlt = 0x0001;
    private const uint ModControl = 0x0002;
    private const Keys HotkeyKey = Keys.D;
    private const string AutoStartName = "DragonBoardLauncher";

    private readonly string _root;
    private readonly Dictionary<string, ManagedService> _services;
    private readonly Dictionary<string, ServiceRow> _rows = new();
    private readonly System.Windows.Forms.Timer _timer;
    private readonly System.Windows.Forms.Timer _dockTimer;
    private readonly TextBox _log = new();
    private readonly Label _summary = new();
    private readonly Label _redisCache = new();
    private readonly Button _autoStartButton = new();
    private readonly NotifyIcon _trayIcon;

    private bool _allowExit;
    private bool _collapsed;
    private bool _refreshInProgress;
    private Rectangle _expandedBounds;

    public LauncherForm()
    {
        _root = FindProjectRoot();
        var quantRoot = Path.Combine(_root, "quant-board");
        _services = new Dictionary<string, ManagedService>
        {
            ["redis"] = ManagedService.WindowsService("Redis 缓存", 6379, "Redis"),
            ["proxy"] = ManagedService.ProcessService("本地代理服务", 3000, Path.Combine(_root, "proxy-server"), "node", "server.js"),
            ["frontend"] = ManagedService.ProcessService("龙头看板前端", 5173, _root, "cmd.exe", "/c npm run dev -- --host 127.0.0.1"),
            ["bridge"] = ManagedService.ProcessService("通达信行情桥", 8765, _root, "python", "python-bridge/main.py"),
            ["quant-api"] = ManagedService.ProcessService(
                "量化后端 API",
                8000,
                quantRoot,
                Path.Combine(quantRoot, ".venv", "Scripts", "python.exe"),
                "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000",
                "python"),
            ["quant-ui"] = ManagedService.ProcessService("量化面板前端", 5174, Path.Combine(quantRoot, "frontend"), "cmd.exe", "/c npm run dev -- --host 127.0.0.1 --port 5174")
        };

        Text = "龙头看板启动管理器";
        Width = 680;
        Height = 680;
        MinimumSize = new Size(640, 560);
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.FromArgb(18, 20, 24);
        ForeColor = Color.FromArgb(236, 240, 244);
        Font = new Font("Segoe UI", 9);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        ShowInTaskbar = true;

        Controls.Add(BuildLayout());
        PositionAtBottomRight();
        _expandedBounds = Bounds;

        _trayIcon = BuildTrayIcon();
        _trayIcon.Visible = true;

        _timer = new System.Windows.Forms.Timer { Interval = 1500 };
        _timer.Tick += (_, _) => RefreshStatuses();
        _timer.Start();

        _dockTimer = new System.Windows.Forms.Timer { Interval = 350 };
        _dockTimer.Tick += (_, _) => UpdateDockState();
        _dockTimer.Start();

        FormClosing += OnFormClosing;
        Resize += (_, _) =>
        {
            if (!_collapsed && WindowState == FormWindowState.Normal)
            {
                _expandedBounds = Bounds;
            }
        };
        Shown += (_, _) =>
        {
            RegisterLauncherHotkey();
            Log("启动管理器已就绪。");
            Log($"项目目录: {_root}");
            Log("快捷键: Ctrl+Alt+D。");
            RefreshStatuses();
        };
    }

    protected override void WndProc(ref Message message)
    {
        if (message.Msg == WmHotkey && message.WParam.ToInt32() == HotkeyId)
        {
            ToggleWindow();
            return;
        }

        base.WndProc(ref message);
    }

    private Control BuildLayout()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(14),
            BackColor = BackColor
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 130));

        root.Controls.Add(BuildHeader(), 0, 0);
        root.Controls.Add(BuildActions(), 0, 1);
        root.Controls.Add(BuildServiceList(), 0, 2);

        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.Dock = DockStyle.Fill;
        _log.Font = new Font("Consolas", 9);
        _log.BackColor = Color.FromArgb(10, 12, 16);
        _log.ForeColor = Color.FromArgb(198, 210, 225);
        _log.BorderStyle = BorderStyle.FixedSingle;
        root.Controls.Add(_log, 0, 4);

        return root;
    }

    private Control BuildHeader()
    {
        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 12)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

        var title = new Label
        {
            AutoSize = true,
            Text = "龙头看板启动管理器",
            Font = new Font("Segoe UI Semibold", 15, FontStyle.Bold),
            ForeColor = Color.FromArgb(255, 176, 70),
            Margin = new Padding(0, 0, 0, 2)
        };
        _summary.AutoSize = true;
        _summary.ForeColor = Color.FromArgb(140, 155, 170);
        _summary.Text = "正在检查服务...";

        var left = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            Margin = Padding.Empty
        };
        left.Controls.Add(title);
        left.Controls.Add(_summary);

        _redisCache.AutoSize = true;
        _redisCache.ForeColor = Color.FromArgb(128, 213, 255);
        _redisCache.Text = "缓存: 检查中";
        _redisCache.Padding = new Padding(8, 7, 8, 7);
        _redisCache.BackColor = Color.FromArgb(28, 34, 43);

        panel.Controls.Add(left, 0, 0);
        panel.Controls.Add(_redisCache, 1, 0);
        return panel;
    }

    private Control BuildActions()
    {
        var actions = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            Margin = new Padding(0, 0, 0, 12),
            WrapContents = true
        };
        actions.Controls.Add(MakeButton("启动核心", (_, _) => StartCore()));
        actions.Controls.Add(MakeButton("启动全部", (_, _) => StartAll()));
        actions.Controls.Add(MakeButton("停止托管", (_, _) => StopManaged()));
        actions.Controls.Add(MakeButton("打开看板", (_, _) => OpenUrl("http://127.0.0.1:5173")));
        actions.Controls.Add(MakeButton("打开量化", (_, _) => OpenUrl("http://127.0.0.1:5174")));
        actions.Controls.Add(MakeButton("健康检查", async (_, _) => await RefreshStatusesAsync()));
        _autoStartButton.Text = IsAutoStartEnabled() ? "自启动: 开" : "自启动: 关";
        StyleButton(_autoStartButton);
        _autoStartButton.Width = 116;
        _autoStartButton.Click += (_, _) => ToggleAutoStart();
        actions.Controls.Add(_autoStartButton);
        return actions;
    }

    private Control BuildServiceList()
    {
        var list = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ColumnCount = 1,
            Margin = Padding.Empty
        };

        foreach (var service in _services.Values)
        {
            var row = new ServiceRow(
                service,
                () => StartService(service),
                () => StopService(service),
                () => OpenService(service));
            _rows[service.Key] = row;
            list.Controls.Add(row.Panel);
        }

        return list;
    }

    private Button MakeButton(string text, EventHandler onClick)
    {
        var button = new Button { Text = text };
        StyleButton(button);
        button.Click += onClick;
        return button;
    }

    private static void StyleButton(Button button)
    {
        button.Width = 92;
        button.Height = 30;
        button.Margin = new Padding(3);
        button.FlatStyle = FlatStyle.Flat;
        button.BackColor = Color.FromArgb(42, 48, 58);
        button.ForeColor = Color.FromArgb(238, 242, 246);
        button.FlatAppearance.BorderColor = Color.FromArgb(72, 82, 96);
        button.FlatAppearance.MouseOverBackColor = Color.FromArgb(58, 68, 82);
    }

    private NotifyIcon BuildTrayIcon()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("显示 / 隐藏", null, (_, _) => ToggleWindow());
        menu.Items.Add("启动核心", null, (_, _) => StartCore());
        menu.Items.Add("启动全部", null, (_, _) => StartAll());
        menu.Items.Add("停止托管", null, (_, _) => StopManaged());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("打开龙头看板", null, (_, _) => OpenUrl("http://127.0.0.1:5173"));
        menu.Items.Add("打开量化面板", null, (_, _) => OpenUrl("http://127.0.0.1:5174"));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("退出启动器", null, (_, _) => ExitLauncher());

        var icon = new NotifyIcon
        {
            Text = "龙头看板启动管理器",
            Icon = SystemIcons.Application,
            ContextMenuStrip = menu
        };
        icon.DoubleClick += (_, _) => ToggleWindow();
        return icon;
    }

    private void StartCore()
    {
        StartService(_services["redis"]);
        StartService(_services["proxy"]);
        StartService(_services["frontend"]);
        StartService(_services["bridge"]);
        StartService(_services["quant-api"]);
        RefreshStatuses();
    }

    private void StartAll()
    {
        StartCore();
        StartService(_services["quant-ui"]);
        RefreshStatuses();
    }

    private void StopManaged()
    {
        StopService(_services["quant-ui"]);
        StopService(_services["quant-api"]);
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services["proxy"]);
        RefreshStatuses();
    }

    private void StartService(ManagedService service)
    {
        if (service.Kind == ServiceKind.WindowsService)
        {
            StartWindowsService(service);
            return;
        }

        try
        {
            if (IsPortOpen(service.Port))
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
                Log($"{service.Name} 可执行文件不存在: {fileName}; 改用 {service.FallbackFileName}。");
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

            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"{service.Name}: {e.Data}"); };
            process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) Log($"{service.Name}: {e.Data}"); };
            process.Exited += (_, _) => Log($"{service.Name} 已退出。");

            if (!process.Start())
            {
                Log($"{service.Name} 启动失败。");
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

    private void StartWindowsService(ManagedService service)
    {
        try
        {
            if (GetWindowsServiceState(service.WindowsServiceName) == "RUNNING")
            {
                Log($"{service.Name} Windows 服务已经在运行。");
                return;
            }

            RunHidden("sc.exe", $"start {service.WindowsServiceName}", _root);
            Log($"已请求启动 Windows 服务: {service.WindowsServiceName}。");
        }
        catch (Exception ex)
        {
            Log($"启动 {service.Name} 失败: {ex.Message}");
        }
    }

    private void StopService(ManagedService service)
    {
        if (service.Kind == ServiceKind.WindowsService)
        {
            try
            {
                RunHidden("sc.exe", $"stop {service.WindowsServiceName}", _root);
                Log($"已请求停止 Windows 服务: {service.WindowsServiceName}。");
            }
            catch (Exception ex)
            {
                Log($"停止 {service.Name} 失败: {ex.Message}");
            }
            return;
        }

        StopProcessService(service);
    }

    private static void OpenService(ManagedService service)
    {
        if (service.Port <= 0)
        {
            return;
        }

        OpenUrl($"http://127.0.0.1:{service.Port}");
    }

    private void StopStartedProcesses()
    {
        StopManaged();
    }

    private void StopProcessService(ManagedService service)
    {
        var targetPids = new HashSet<int>();
        if (service.Process is { HasExited: false })
        {
            targetPids.Add(service.Process.Id);
        }

        foreach (var pid in GetPidsByPort(service.Port))
        {
            targetPids.Add(pid);
        }

        targetPids.Remove(Environment.ProcessId);

        if (targetPids.Count == 0)
        {
            service.Process = null;
            Log($"{service.Name} 未发现可停止的进程。");
            return;
        }

        foreach (var pid in targetPids)
        {
            StopProcessTree(service, pid);
        }

        service.Process = null;
    }

    private void StopProcessTree(ManagedService service, int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            process.Kill(entireProcessTree: true);
            process.WaitForExit(3000);
            Log($"已停止 {service.Name} 进程树，PID={pid}。");
        }
        catch (ArgumentException)
        {
            Log($"{service.Name} 进程 PID={pid} 已退出。");
        }
        catch (Exception ex)
        {
            Log($"停止 {service.Name} 进程 PID={pid} 失败: {ex.Message}");
        }
    }

    private void RefreshStatuses()
    {
        _ = RefreshStatusesAsync();
    }

    private async Task RefreshStatusesAsync()
    {
        if (_refreshInProgress)
        {
            return;
        }

        _refreshInProgress = true;
        try
        {
            var online = 0;
            foreach (var service in _services.Values)
            {
                var status = GetServiceStatus(service);
                if (status.Running)
                {
                    online++;
                }

                _rows[service.Key].Update(status);
            }

            _summary.Text = $"服务在线 {online}/{_services.Count}  ·  {DateTime.Now:HH:mm:ss}";
            _trayIcon.Text = $"龙头看板: {online}/{_services.Count} 个服务在线";
            _redisCache.Text = await GetQuantCacheStatusAsync();
        }
        catch (Exception ex)
        {
            Log($"健康检查失败: {ex.Message}");
        }
        finally
        {
            _refreshInProgress = false;
        }
    }

    private ServiceStatus GetServiceStatus(ManagedService service)
    {
        var pids = GetPidsByPort(service.Port);
        var processNames = pids.Select(GetProcessName).Where(name => !string.IsNullOrWhiteSpace(name)).Distinct().ToList();
        var serviceState = service.Kind == ServiceKind.WindowsService
            ? GetWindowsServiceState(service.WindowsServiceName)
            : "";
        var running = service.Kind == ServiceKind.WindowsService
            ? serviceState == "RUNNING" || IsPortOpen(service.Port)
            : IsPortOpen(service.Port);

        return new ServiceStatus(
            service,
            running,
            pids,
            processNames,
            serviceState);
    }

    private async Task<string> GetQuantCacheStatusAsync()
    {
        if (!IsPortOpen(8000))
        {
            return "缓存: 后端离线";
        }

        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1.5) };
            var body = await client.GetStringAsync("http://127.0.0.1:8000/api/snapshots/frames?dataset_id=dragonboard_live&snapshot_type=half_hour&limit=1&projection=ranktrend");
            if (body.Contains("\"store\":\"redis\"", StringComparison.OrdinalIgnoreCase))
            {
                return "缓存: Redis";
            }

            if (body.Contains("\"store\":\"sqlite\"", StringComparison.OrdinalIgnoreCase))
            {
                return "缓存: SQLite";
            }

            return "缓存: 未知";
        }
        catch
        {
            return "缓存: 检查失败";
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

            _autoStartButton.Text = IsAutoStartEnabled() ? "自启动: 开" : "自启动: 关";
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

    private void RegisterLauncherHotkey()
    {
        if (RegisterHotKey(Handle, HotkeyId, ModControl | ModAlt, (uint)HotkeyKey))
        {
            return;
        }

        Log("注册 Ctrl+Alt+D 快捷键失败。");
    }

    private void ToggleWindow()
    {
        if (Visible && WindowState != FormWindowState.Minimized)
        {
            Hide();
            ShowInTaskbar = false;
            return;
        }

        ShowInTaskbar = true;
        Show();
        WindowState = FormWindowState.Normal;
        ExpandFromEdge();
        Activate();
    }

    private void UpdateDockState()
    {
        if (!Visible || WindowState != FormWindowState.Normal)
        {
            return;
        }

        var screen = Screen.FromControl(this).WorkingArea;
        var cursorInside = Bounds.Contains(Cursor.Position);
        var nearRight = Math.Abs(Right - screen.Right) <= 12;

        if (!_collapsed && nearRight && !cursorInside && ContainsFocus == false)
        {
            CollapseToEdge(screen);
        }
        else if (_collapsed && cursorInside)
        {
            ExpandFromEdge();
        }
    }

    private void CollapseToEdge(Rectangle screen)
    {
        if (!_collapsed)
        {
            _expandedBounds = Bounds;
        }

        _collapsed = true;
        Bounds = new Rectangle(screen.Right - 16, _expandedBounds.Top, 16, _expandedBounds.Height);
        Opacity = 0.72;
    }

    private void ExpandFromEdge()
    {
        if (!_collapsed)
        {
            return;
        }

        _collapsed = false;
        Bounds = _expandedBounds;
        Opacity = 1.0;
    }

    private void PositionAtBottomRight()
    {
        var screen = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        Location = new Point(screen.Right - Width - 14, screen.Bottom - Height - 14);
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        if (_allowExit || e.CloseReason != CloseReason.UserClosing)
        {
            _timer.Stop();
            _dockTimer.Stop();
            UnregisterHotKey(Handle, HotkeyId);
            _trayIcon.Visible = false;
            _trayIcon.Dispose();
            StopStartedProcesses();
            return;
        }

        e.Cancel = true;
        Hide();
        ShowInTaskbar = false;
        Log("窗口已隐藏到托盘。需要退出请使用托盘菜单。");
    }

    private void ExitLauncher()
    {
        _allowExit = true;
        Close();
    }

    private static bool IsPortOpen(int port)
    {
        var properties = IPGlobalProperties.GetIPGlobalProperties();
        return properties.GetActiveTcpListeners().Any(endpoint => endpoint.Port == port)
            || properties.GetActiveTcpConnections().Any(connection =>
                connection.LocalEndPoint.Port == port &&
                connection.State is TcpState.Listen or TcpState.Established);
    }

    private static IReadOnlyList<int> GetPidsByPort(int port)
    {
        var result = new List<int>();
        try
        {
            var output = RunHidden("netstat.exe", "-ano -p tcp", Directory.GetCurrentDirectory());
            foreach (var line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5 || !parts[1].EndsWith($":{port}", StringComparison.Ordinal))
                {
                    continue;
                }

                if (int.TryParse(parts[^1], out var pid) && pid > 0 && !result.Contains(pid))
                {
                    result.Add(pid);
                }
            }
        }
        catch
        {
            // Best effort only.
        }

        return result;
    }

    private static string GetProcessName(int pid)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return process.ProcessName;
        }
        catch
        {
            return "";
        }
    }

    private static string GetWindowsServiceState(string? serviceName)
    {
        if (string.IsNullOrWhiteSpace(serviceName))
        {
            return "";
        }

        try
        {
            var output = RunHidden("sc.exe", $"query {serviceName}", Directory.GetCurrentDirectory());
            foreach (var line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (!line.Contains("STATE", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                if (line.Contains("RUNNING", StringComparison.OrdinalIgnoreCase))
                {
                    return "RUNNING";
                }

                if (line.Contains("STOPPED", StringComparison.OrdinalIgnoreCase))
                {
                    return "STOPPED";
                }
            }
        }
        catch
        {
            return "UNKNOWN";
        }

        return "UNKNOWN";
    }

    private static string RunHidden(string fileName, string arguments, string workingDirectory)
    {
        var info = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory,
            CreateNoWindow = true,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        using var process = Process.Start(info);
        if (process == null)
        {
            return "";
        }

        var stdout = process.StandardOutput.ReadToEnd();
        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit(3000);
        return string.IsNullOrWhiteSpace(stdout) ? stderr : stdout;
    }

    private static void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true
            });
        }
        catch
        {
            // Opening a browser is a convenience action; failure is non-fatal.
        }
    }

    private void Log(string message)
    {
        if (IsDisposed)
        {
            return;
        }

        if (InvokeRequired)
        {
            try
            {
                BeginInvoke(() => Log(message));
            }
            catch (InvalidOperationException)
            {
                // The form can be closing while background output events are still draining.
            }

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
            {
                return dir.TrimEnd(Path.DirectorySeparatorChar);
            }

            var parent = Directory.GetParent(dir);
            if (parent == null)
            {
                break;
            }

            dir = parent.FullName;
        }

        return Directory.GetCurrentDirectory();
    }

    [DllImport("user32.dll")]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll")]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
}

internal sealed class ServiceRow
{
    private readonly ManagedService _service;
    private readonly Action _start;
    private readonly Action _stop;
    private readonly Action _open;
    private readonly Label _dot = new();
    private readonly Label _name = new();
    private readonly Label _meta = new();
    private readonly Label _status = new();
    private readonly Label _pid = new();

    public ServiceRow(ManagedService service, Action start, Action stop, Action open)
    {
        _service = service;
        _start = start;
        _stop = stop;
        _open = open;
        Panel = BuildPanel();
    }

    public Panel Panel { get; }

    public void Update(ServiceStatus status)
    {
        var running = status.Running;
        _dot.Text = running ? "●" : "●";
        _dot.ForeColor = running ? Color.FromArgb(44, 210, 140) : Color.FromArgb(220, 75, 85);
        _status.Text = running ? "运行中" : "已停止";
        _status.ForeColor = running ? Color.FromArgb(44, 210, 140) : Color.FromArgb(255, 120, 130);
        _pid.Text = status.Pids.Count > 0
            ? $"进程 {string.Join(",", status.Pids)} · {string.Join("/", status.ProcessNames)}"
            : status.ServiceState.Length > 0 ? $"服务状态 {TranslateServiceState(status.ServiceState)}" : "无进程";
    }

    private Panel BuildPanel()
    {
        var panel = new Panel
        {
            Height = 76,
            Dock = DockStyle.Top,
            Margin = new Padding(0, 0, 0, 8),
            BackColor = Color.FromArgb(29, 33, 40),
            Padding = new Padding(10)
        };

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            RowCount = 2,
            BackColor = panel.BackColor,
            Margin = Padding.Empty,
            Padding = Padding.Empty
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 28));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 44));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 36));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 164));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));

        _dot.AutoSize = true;
        _dot.Font = new Font("Segoe UI", 13, FontStyle.Bold);
        _dot.Anchor = AnchorStyles.Left;

        _name.AutoSize = true;
        _name.Text = _service.Name;
        _name.ForeColor = Color.FromArgb(238, 242, 246);
        _name.Font = new Font("Segoe UI Semibold", 10, FontStyle.Bold);
        _name.Anchor = AnchorStyles.Left;

        _meta.AutoSize = true;
        _meta.Text = $"端口 {_service.Port}";
        _meta.ForeColor = Color.FromArgb(148, 160, 174);
        _meta.Anchor = AnchorStyles.Left;

        _status.AutoSize = true;
        _status.Font = new Font("Segoe UI Semibold", 9, FontStyle.Bold);
        _status.Anchor = AnchorStyles.Left;

        _pid.AutoSize = true;
        _pid.ForeColor = Color.FromArgb(148, 160, 174);
        _pid.Anchor = AnchorStyles.Left;

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Margin = Padding.Empty,
            Padding = new Padding(0, 12, 0, 0)
        };
        buttons.Controls.Add(MakeRowButton("启动", _start));
        buttons.Controls.Add(MakeRowButton("停止", _stop));
        buttons.Controls.Add(MakeRowButton("打开", _open));

        layout.Controls.Add(_dot, 0, 0);
        layout.SetRowSpan(_dot, 2);
        layout.Controls.Add(_name, 1, 0);
        layout.Controls.Add(_meta, 1, 1);
        layout.Controls.Add(_status, 2, 0);
        layout.Controls.Add(_pid, 2, 1);
        layout.Controls.Add(buttons, 3, 0);
        layout.SetRowSpan(buttons, 2);

        panel.Controls.Add(layout);
        return panel;
    }

    private static Button MakeRowButton(string text, Action action)
    {
        var button = new Button
        {
            Text = text,
            Width = 50,
            Height = 24,
            Margin = new Padding(2),
            FlatStyle = FlatStyle.Flat,
            BackColor = Color.FromArgb(42, 48, 58),
            ForeColor = Color.FromArgb(238, 242, 246)
        };
        button.FlatAppearance.BorderColor = Color.FromArgb(72, 82, 96);
        button.FlatAppearance.MouseOverBackColor = Color.FromArgb(58, 68, 82);
        button.Click += (_, _) => action();
        return button;
    }

    private static string TranslateServiceState(string state)
    {
        return state switch
        {
            "RUNNING" => "运行中",
            "STOPPED" => "已停止",
            "UNKNOWN" => "未知",
            _ => state
        };
    }
}

internal sealed record ServiceStatus(
    ManagedService Service,
    bool Running,
    IReadOnlyList<int> Pids,
    IReadOnlyList<string> ProcessNames,
    string ServiceState);

internal enum ServiceKind
{
    Process,
    WindowsService
}

internal sealed class ManagedService
{
    private ManagedService(
        string key,
        string name,
        int port,
        ServiceKind kind,
        string workingDirectory,
        string fileName,
        string arguments,
        string? fallbackFileName,
        string? fallbackArguments,
        string? windowsServiceName)
    {
        Key = key;
        Name = name;
        Port = port;
        Kind = kind;
        WorkingDirectory = workingDirectory;
        FileName = fileName;
        Arguments = arguments;
        FallbackFileName = fallbackFileName;
        FallbackArguments = fallbackArguments;
        WindowsServiceName = windowsServiceName;
    }

    public string Key { get; }
    public string Name { get; }
    public int Port { get; }
    public ServiceKind Kind { get; }
    public string WorkingDirectory { get; }
    public string FileName { get; }
    public string Arguments { get; }
    public string? FallbackFileName { get; }
    public string? FallbackArguments { get; }
    public string? WindowsServiceName { get; }
    public Process? Process { get; set; }

    public static ManagedService ProcessService(
        string name,
        int port,
        string workingDirectory,
        string fileName,
        string arguments,
        string? fallbackFileName = null,
        string? fallbackArguments = null)
    {
        return new ManagedService(
            KeyFromName(name),
            name,
            port,
            ServiceKind.Process,
            workingDirectory,
            fileName,
            arguments,
            fallbackFileName,
            fallbackArguments,
            null);
    }

    public static ManagedService WindowsService(string name, int port, string serviceName)
    {
        return new ManagedService(
            KeyFromName(name),
            name,
            port,
            ServiceKind.WindowsService,
            Directory.GetCurrentDirectory(),
            "",
            "",
            null,
            null,
            serviceName);
    }

    private static string KeyFromName(string name)
    {
        return name.ToLowerInvariant().Replace(" ", "-");
    }
}
