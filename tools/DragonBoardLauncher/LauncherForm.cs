using System.Diagnostics;
using Microsoft.Win32;

namespace DragonBoardLauncher;

internal sealed class LauncherForm : Form
{
    private const string AutoStartName = "DragonBoardLauncher";
    private const int MaxLogLines = 300;
    private const int MaxLogLineChars = 600;

    private readonly string _root;
    private readonly Dictionary<string, ManagedService> _services;
    private readonly LauncherProcessManager _processManager;
    private readonly System.Windows.Forms.Timer _timer;

    private readonly TextBox _log = new();
    private readonly BoundedLogView _logView = new(MaxLogLines);
    private readonly Button _autoStartButton = new();
    private readonly NotifyIcon _trayIcon = new();
    private readonly ContextMenuStrip _trayMenu = new();

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
    private bool _isRefreshingStatuses;
    private bool _isManagerActionRunning;
    private bool _allowExit;
    private bool _trayNoticeShown;

    public LauncherForm()
    {
        _root = ProjectRootLocator.Find();
        _services = LauncherServices.Create(_root);
        _processManager = new LauncherProcessManager(_root, _services, Log);

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
        BuildTrayIcon();

        _timer = new System.Windows.Forms.Timer { Interval = 3000 };
        _timer.Tick += async (_, _) => await RefreshStatusesAsync();
        _timer.Start();

        Resize += (_, _) =>
        {
            if (WindowState == FormWindowState.Minimized)
                HideToTray();
        };
        FormClosing += (_, e) =>
        {
            if (!_allowExit && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                HideToTray();
                return;
            }

            _timer.Stop();
            _trayIcon.Visible = false;
            _processManager.StopStartedProcesses();
        };
        FormClosed += (_, _) =>
        {
            _trayIcon.Dispose();
            _trayMenu.Dispose();
        };
        Shown += (_, _) =>
        {
            Log("启动管理器已就绪。");
            Log($"项目目录: {_root}");
            _ = RefreshStatusesAsync();
        };
    }

    private void BuildTrayIcon()
    {
        _trayMenu.Items.Add("显示窗口", null, (_, _) => ShowFromTray());
        _trayMenu.Items.Add("打开看板", null, (_, _) => OpenBoard());
        _trayMenu.Items.Add("核心启动", null, async (_, _) => await StartAllAsync());
        _trayMenu.Items.Add("全部停止", null, async (_, _) => await StopAllAsync());
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("退出", null, (_, _) => ExitApplication());

        _trayIcon.Text = "龙头看板 · 启动管理器";
        _trayIcon.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application;
        _trayIcon.ContextMenuStrip = _trayMenu;
        _trayIcon.Visible = true;
        _trayIcon.DoubleClick += (_, _) => ShowFromTray();
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
        var keys = LauncherServices.OrderedKeys;
        for (int i = 0; i < keys.Length; i++)
        {
            var card = BuildServiceCard(_services[keys[i]], iconKeys[i], keys[i], y);
            Controls.Add(card);
            y = card.Bottom + 6;
        }

        var btnBarY = y + 8;
        var startAllBtn = new Button
        {
            Text = "核心启动",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(110, 36),
            Location = new Point(18, btnBarY),
            BackColor = _green,
            ForeColor = Color.White,
            Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold),
            Cursor = Cursors.Hand,
        };
        startAllBtn.FlatAppearance.BorderSize = 0;
        startAllBtn.Click += async (_, _) => await StartAllAsync();
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
        stopAllBtn.Click += async (_, _) => await StopAllAsync();
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
        openAppBtn.Click += (_, _) => OpenBoard();
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
        startBtn.Click += async (_, _) => await RunManagerActionAsync(() => _processManager.StartService(svc));
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
        stopBtn.Click += async (_, _) => await RunManagerActionAsync(() => _processManager.StopService(svc));
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
                if (svc.Port == 27017)
                    _processManager.StartMongoExpress();
                if (svc.Port == 6379)
                    _processManager.StartRedisCommander();
                OpenUrl(url);
            };
            p.Controls.Add(openBtn);
        }

        return p;
    }

    private Task StartAllAsync()
    {
        return RunManagerActionAsync(_processManager.StartAll);
    }

    private Task StopAllAsync()
    {
        return RunManagerActionAsync(_processManager.StopAll);
    }

    private async Task RunManagerActionAsync(Action action)
    {
        if (_isManagerActionRunning || IsDisposed) return;

        _isManagerActionRunning = true;
        _timer.Stop();
        UseWaitCursor = true;
        try
        {
            await Task.Run(action);
        }
        finally
        {
            _isManagerActionRunning = false;
            if (!IsDisposed)
            {
                UseWaitCursor = false;
                _timer.Start();
            }
        }

        await RefreshStatusesAsync();
    }

    private async Task RefreshStatusesAsync()
    {
        if (_isRefreshingStatuses || IsDisposed) return;

        _isRefreshingStatuses = true;
        var services = _services.ToArray();
        Dictionary<string, bool> statuses;
        try
        {
            statuses = await Task.Run(() => services.ToDictionary(
                kv => kv.Key,
                kv => LauncherProcessManager.IsServiceRunning(kv.Value)));
        }
        finally
        {
            _isRefreshingStatuses = false;
        }

        if (IsDisposed) return;

        var running = 0;
        foreach (var kv in statuses)
        {
            var key = kv.Key;
            var isRunning = kv.Value;

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

    private static void OpenBoard()
    {
        OpenUrl("http://127.0.0.1:3000");
    }

    private static void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
        }
        catch { }
    }

    private void HideToTray()
    {
        Hide();
        ShowInTaskbar = false;
        WindowState = FormWindowState.Normal;

        if (_trayNoticeShown) return;

        _trayNoticeShown = true;
        _trayIcon.ShowBalloonTip(
            2000,
            "龙头看板仍在运行",
            "窗口已最小化到系统托盘。右键托盘图标可退出或停止服务。",
            ToolTipIcon.Info);
    }

    private void ShowFromTray()
    {
        ShowInTaskbar = true;
        Show();
        WindowState = FormWindowState.Normal;
        Activate();
        _ = RefreshStatusesAsync();
    }

    private void ExitApplication()
    {
        _allowExit = true;
        Close();
    }

    private void Log(string message)
    {
        if (IsDisposed) return;
        if (!ShouldShowLog(message)) return;

        if (InvokeRequired)
        {
            try { BeginInvoke(() => Log(message)); }
            catch (InvalidOperationException) { }
            return;
        }

        _logView.Append(_log, $"[{DateTime.Now:HH:mm:ss}] {TrimLogLine(message)}");
    }

    private static bool ShouldShowLog(string message)
    {
        if (string.IsNullOrWhiteSpace(message)) return false;

        var text = message.Trim();
        return ContainsAny(text,
            "启动管理器", "项目目录", "自启动",
            "已启动", "启动 ", "启动失败",
            "已停止", "停止 ", "停止失败",
            "已退出", "退出", "重启", "已终止",
            "失败", "异常", "警告", "错误", "无法", "缺失", "不存在", "仍在运行",
            "WARNING", "[WARN", " WARN ", "ERROR", "[ERROR", "ERR_", "Exception", "Traceback");
    }

    private static bool ContainsAny(string text, params string[] needles)
    {
        return needles.Any(needle => text.Contains(needle, StringComparison.OrdinalIgnoreCase));
    }

    private static string TrimLogLine(string message)
    {
        var text = message.Trim();
        if (text.Length <= MaxLogLineChars) return text;

        return text[..MaxLogLineChars] + "...";
    }
}
