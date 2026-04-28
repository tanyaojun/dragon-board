using System.Diagnostics;
using System.Net.NetworkInformation;
using System.Text;

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
    private readonly string _root;
    private readonly Dictionary<string, ManagedService> _services;
    private readonly System.Windows.Forms.Timer _timer;

    private readonly Label _proxyStatus = new();
    private readonly Label _frontendStatus = new();
    private readonly Label _bridgeStatus = new();
    private readonly TextBox _log = new();

    public LauncherForm()
    {
        _root = FindProjectRoot();
        _services = new Dictionary<string, ManagedService>
        {
            ["proxy"] = new("Proxy Server", 3000, Path.Combine(_root, "proxy-server"), "node", "server.js"),
            ["frontend"] = new("Frontend", 5173, _root, "cmd.exe", "/c npm run dev -- --host 127.0.0.1"),
            ["bridge"] = new("Python Bridge", 8765, _root, "python", "python-bridge/main.py")
        };

        Text = "Dragon Board Launcher";
        Width = 760;
        Height = 560;
        MinimumSize = new Size(680, 480);
        StartPosition = FormStartPosition.CenterScreen;

        Controls.Add(BuildLayout());

        _timer = new System.Windows.Forms.Timer { Interval = 1500 };
        _timer.Tick += (_, _) => RefreshStatuses();
        _timer.Start();

        FormClosing += (_, _) => _timer.Stop();
        Shown += (_, _) =>
        {
            Log("Launcher ready.");
            Log($"Project root: {_root}");
            RefreshStatuses();
        };
    }

    private Control BuildLayout()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(14)
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var title = new Label
        {
            AutoSize = true,
            Text = "Dragon Board Service Launcher",
            Font = new Font(Font.FontFamily, 15, FontStyle.Bold),
            Margin = new Padding(0, 0, 0, 12)
        };
        root.Controls.Add(title);

        root.Controls.Add(BuildServiceRow(_services["proxy"], _proxyStatus));
        root.Controls.Add(BuildServiceRow(_services["frontend"], _frontendStatus));
        root.Controls.Add(BuildServiceRow(_services["bridge"], _bridgeStatus));

        var actions = new FlowLayoutPanel
        {
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            Margin = new Padding(0, 8, 0, 8)
        };
        actions.Controls.Add(MakeButton("Start All", (_, _) => StartAll()));
        actions.Controls.Add(MakeButton("Stop All", (_, _) => StopAll()));
        actions.Controls.Add(MakeButton("Open App", (_, _) => OpenUrl("http://127.0.0.1:5173")));
        actions.Controls.Add(MakeButton("Open Manager", (_, _) => OpenUrl("http://127.0.0.1:3000/launcher.html")));
        actions.Controls.Add(MakeButton("Refresh", (_, _) => RefreshStatuses()));
        root.Controls.Add(actions);

        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.Dock = DockStyle.Fill;
        _log.Font = new Font("Consolas", 9);
        root.Controls.Add(_log);

        return root;
    }

    private Control BuildServiceRow(ManagedService service, Label status)
    {
        var panel = new TableLayoutPanel
        {
            ColumnCount = 5,
            AutoSize = true,
            Dock = DockStyle.Top,
            Margin = new Padding(0, 0, 0, 8)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 95));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 95));
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        panel.Controls.Add(new Label
        {
            Text = $"{service.Name} :{service.Port}",
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            Padding = new Padding(0, 7, 0, 0)
        }, 0, 0);

        status.AutoSize = true;
        status.Anchor = AnchorStyles.Left;
        status.Padding = new Padding(0, 7, 0, 0);
        panel.Controls.Add(status, 1, 0);

        panel.Controls.Add(MakeButton("Start", (_, _) => StartService(service)), 2, 0);
        panel.Controls.Add(MakeButton("Stop", (_, _) => StopService(service)), 3, 0);

        return panel;
    }

    private static Button MakeButton(string text, EventHandler onClick)
    {
        var button = new Button
        {
            Text = text,
            Width = 86,
            Height = 32,
            Margin = new Padding(4)
        };
        button.Click += onClick;
        return button;
    }

    private void StartAll()
    {
        StartService(_services["proxy"]);
        StartService(_services["frontend"]);
        StartService(_services["bridge"]);
        RefreshStatuses();
    }

    private void StopAll()
    {
        StopService(_services["bridge"]);
        StopService(_services["frontend"]);
        StopService(_services["proxy"]);
        RefreshStatuses();
    }

    private void StartService(ManagedService service)
    {
        try
        {
            if (IsPortOpen(service.Port))
            {
                Log($"{service.Name} already appears to be running on port {service.Port}.");
                return;
            }

            if (!Directory.Exists(service.WorkingDirectory))
            {
                Log($"{service.Name} working directory missing: {service.WorkingDirectory}");
                return;
            }

            var info = new ProcessStartInfo
            {
                FileName = service.FileName,
                Arguments = service.Arguments,
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
            process.Exited += (_, _) => Log($"{service.Name} exited.");

            if (!process.Start())
            {
                Log($"Failed to start {service.Name}.");
                return;
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            service.Process = process;
            Log($"Started {service.Name}, pid={process.Id}.");
        }
        catch (Exception ex)
        {
            Log($"Start {service.Name} failed: {ex.Message}");
        }
    }

    private void StopService(ManagedService service)
    {
        try
        {
            if (service.Process is { HasExited: false })
            {
                service.Process.Kill(entireProcessTree: true);
                service.Process.WaitForExit(3000);
                Log($"Stopped {service.Name} process tree.");
                service.Process = null;
            }

            var pids = GetPidsByPort(service.Port);
            foreach (var pid in pids)
            {
                try
                {
                    using var process = Process.GetProcessById(pid);
                    process.Kill(entireProcessTree: true);
                    Log($"Killed process on port {service.Port}, pid={pid}.");
                }
                catch (Exception ex)
                {
                    Log($"Could not kill pid={pid} on port {service.Port}: {ex.Message}");
                }
            }
        }
        catch (Exception ex)
        {
            Log($"Stop {service.Name} failed: {ex.Message}");
        }
    }

    private void RefreshStatuses()
    {
        SetStatus(_proxyStatus, IsPortOpen(3000));
        SetStatus(_frontendStatus, IsPortOpen(5173));
        SetStatus(_bridgeStatus, IsPortOpen(8765));
    }

    private static void SetStatus(Label label, bool running)
    {
        label.Text = running ? "Running" : "Stopped";
        label.ForeColor = running ? Color.ForestGreen : Color.Firebrick;
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
            var info = new ProcessStartInfo
            {
                FileName = "netstat.exe",
                Arguments = "-ano -p tcp",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true
            };
            using var process = Process.Start(info);
            if (process == null)
            {
                return result;
            }

            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(3000);
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
            // Best effort only. The UI log already covers explicit stop failures.
        }

        return result;
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
        if (InvokeRequired)
        {
            BeginInvoke(() => Log(message));
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
}

internal sealed class ManagedService
{
    public ManagedService(string name, int port, string workingDirectory, string fileName, string arguments)
    {
        Name = name;
        Port = port;
        WorkingDirectory = workingDirectory;
        FileName = fileName;
        Arguments = arguments;
    }

    public string Name { get; }
    public int Port { get; }
    public string WorkingDirectory { get; }
    public string FileName { get; }
    public string Arguments { get; }
    public Process? Process { get; set; }
}
