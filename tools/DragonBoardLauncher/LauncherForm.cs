using System.Diagnostics;
using DragonBoardLauncher.Core;
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
    private readonly Dictionary<string, Button> _startButtons = new();
    private readonly Dictionary<string, Button> _stopButtons = new();
    private bool _isRefreshingStatuses;
    private bool _isManagerActionRunning;
    // 管理动作互斥量（P1，2026-10-31 复盘）：UI 管理动作（启动/停止/全部停止/重启）
    // 与守卫后台修复共用，停止流程执行期间守卫修复非阻塞放弃本轮，杜绝
    // “停止流程进行中又被守卫拉起”的并发交错。
    private readonly SemaphoreSlim _actionGate = new(1, 1);
    private bool _allowExit;
    private bool _trayNoticeShown;

    // 采集健康决策内核：防抖 + Restartable 判定 + 恢复日志（无 UI 依赖）。
    private readonly CollectorHealthGuard _collectorGuard = new();
    // 上一次刷新得到的每服务运行状态：用于记录状态跳变（"掉线又自动恢复"取证）。
    private readonly Dictionary<string, bool> _lastStatuses = new(StringComparer.Ordinal);
    // 自动重启策略：冷却 + 连续失败上限 + 指数退避（防重启风暴）。
    private readonly RestartPolicy _restartPolicy = new();
    // 重启被冷却拦截时，仅当原因变化才记日志，避免每 3 秒刷一条。
    private string _lastRestartBlockedReason = "";

    // 基础设施存活守护（P0-A，2026-10-09 审计）：mongo/redis 盘中静默死亡曾导致
    // 最长 45 分钟无库。离线即自动拉起（不杀进程）；冷却/上限由 _restartPolicy 管。
    private static readonly string[] InfraGuardKeys = { "mongo", "redis" };
    private readonly InfraHealthGuard _infraGuard = new();
    private readonly Dictionary<string, string> _lastInfraBlockedReason = new(StringComparer.Ordinal);

    // 交易时段推迟停启式修复（P0-B）的日志去重：轮询间隔 3 秒，避免刷屏。
    private static readonly TimeSpan DeferredRepairLogInterval = TimeSpan.FromMinutes(5);
    private DateTime? _lastCollectorDeferredUtc;

    // 用户显式停止过的服务 key 已下沉到 LauncherProcessManager（P0，2026-10-31 复盘）：
    // StartService 入口强制检查，任何启动路径都无法违背停止意图；UI 层仅转发。

    // 用户启停偏好持久化（P1.2）：launcher 重启后恢复用户手动启动过的展示/辅助服务。
    private readonly DesiredStateStore _desiredState;
    private readonly HashSet<string> _desiredEnabled;

    // 状态防抖（P1）：key → (待确认状态, 已连续次数)。连续 2 次轮询一致才提交跳变。
    private readonly Dictionary<string, (bool Value, int Count)> _pendingStatuses = new(StringComparer.Ordinal);

    public LauncherForm()
    {
        _root = ProjectRootLocator.Find();
        LogFile.Initialize(_root);
        _services = LauncherServices.Create(_root);
        _processManager = new LauncherProcessManager(_root, _services, Log);
        _desiredState = new DesiredStateStore();
        _desiredEnabled = _desiredState.LoadEnabled();
        Log($"启动管理器启动，本地日志: {LogFile.CurrentLogPath()}");
        if (LauncherServices.LastLoadUsedFallback)
            Log("警告: services.json 加载失败，已回退内嵌默认服务定义（入口按钮/启动参数可能与配置不一致），请检查 tools/DragonBoardLauncher/config/services.json。");

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
            // 等待在途管理动作（核心启动/全部重启/全部停止）结束再全量停止，
            // 避免退出停止与后台启动交错、launcher 退出后新拉起进程成孤儿
            // （review P1，2026-10-31）；等不到（>10s）则照旧强停并留痕。
            if (!_actionGate.Wait(TimeSpan.FromSeconds(10)))
                Log("退出等待在途管理动作超时（10s），直接执行退出停止。");
            _processManager.StopStartedProcesses();
        };
        FormClosed += (_, _) =>
        {
            _trayIcon.Dispose();
            _trayMenu.Dispose();
        };
        Shown += async (_, _) =>
        {
            Log("启动管理器已就绪。");
            Log($"项目目录: {_root}");
            Log("启动管理器正在自动启动核心服务，确保盘中快照调度持续运行。");
            await StartAllAsync();
            await RestoreDesiredServicesAsync();
        };
    }

    private void BuildTrayIcon()
    {
        _trayMenu.Items.Add("显示窗口", null, (_, _) => ShowFromTray());
        _trayMenu.Items.Add("打开看板", null, (_, _) => OpenBoard());
        _trayMenu.Items.Add("核心启动", null, async (_, _) => await StartAllAsync());
        _trayMenu.Items.Add("全部重启", null, async (_, _) => await RestartAllAsync());
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
        var iconKeys = new[] { "DB", "RD", "PX", "BR", "KP", "SC", "RP", "QA", "FE", "QU", "VO" };
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
        openQBtn.Click += (_, _) => OpenUrl("量化面板", "http://127.0.0.1:5174");
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

        var restartAllBtn = new Button
        {
            Text = "全部重启",
            FlatStyle = FlatStyle.Flat,
            Size = new Size(96, 36),
            Location = new Point(512, btnBarY),
            BackColor = Color.FromArgb(176, 130, 44),
            ForeColor = Color.White,
            Font = new Font("Microsoft YaHei UI", 10f, FontStyle.Bold),
            Cursor = Cursors.Hand,
        };
        restartAllBtn.FlatAppearance.BorderSize = 0;
        restartAllBtn.Click += async (_, _) => await RestartAllAsync();
        Controls.Add(restartAllBtn);

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
        startBtn.Click += async (_, _) =>
        {
            // 清除“手动停止”标记必须在 gate 内进行（review P1，2026-10-31）：
            // 若在持 gate 前清除，此时“全部停止”正在执行，其收尾的批量
            // UserStoppedAdd 会在启动动作运行前覆盖标记，StartService 入口
            // 拒绝本次显式启动，用户点击被静默吞掉。
            await RunManagerActionAsync(() =>
            {
                UserStoppedRemove(key);
                _processManager.StartService(svc);
            });
            MarkDesired(key, enabled: true);
        };
        p.Controls.Add(startBtn);
        _startButtons[key] = startBtn;

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
        stopBtn.Click += async (_, _) =>
        {
            // 先记录用户手动停止意图（StartService 入口按此拒绝一切后续启动路径，
            // 2026-10-31 复盘 P0），再执行停止。
            UserStoppedAdd(key);
            MarkDesired(key, enabled: false);
            await RunManagerActionAsync(() => _processManager.StopService(svc));
        };
        p.Controls.Add(stopBtn);
        _stopButtons[key] = stopBtn;

        // 「打开」按钮（2026-10-12 外置化）：openUrl 配置驱动，无白名单无 switch。
        // 2026-10-31 修复：外置化迁移不完整导致 bridge/voice 按钮消失、mongo/redis
        // 只拉起工具不再打开浏览器（旧版 switch 是全服务兜底 + 工具拉起后自动
        // OpenUrl）。现约定：openUrl 指向该服务的入口页（mongo/redis 指管理工具页），
        // 点击时 mongo/redis 先拉起管理工具再打开浏览器；OpenUrl 失败记日志不静默。
        if (!string.IsNullOrWhiteSpace(svc.OpenUrl))
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
            openBtn.Click += (_, _) =>
            {
                if (svc.Port == 27017)
                    _processManager.StartMongoExpress();
                else if (svc.Port == 6379)
                    _processManager.StartRedisCommander();
                OpenUrl(svc.Name, svc.OpenUrl!);
            };
            p.Controls.Add(openBtn);
        }

        return p;
    }

    private Task StartAllAsync()
    {
        return RunManagerActionAsync(() =>
        {
            // 核心启动视为用户显式意图：先清除“手动停止”标记再启动。
            // StartService 入口会拒绝仍在停止集合中的服务（P0），顺序不能反。
            foreach (var key in _services.Keys)
                UserStoppedRemove(key);
            _processManager.StartAll();
        });
    }

    private Task StopAllAsync()
    {
        return RunManagerActionAsync(() =>
        {
            _processManager.StopAll();
            // 全部停止视为用户显式意图：全部服务加入"手动停止"标记，避免自动重启拉起。
            foreach (var key in _services.Keys)
                UserStoppedAdd(key);
        });
    }

    /// <summary>
    /// 全部重启：停止全部服务 → 清除手动停止标记（恢复自动重启）→ 启动核心 → 恢复偏好服务。
    /// </summary>
    private async Task RestartAllAsync()
    {
        await RunManagerActionAsync(() =>
        {
            _processManager.StopAll();
            // 重启视为用户显式意图：清除手动停止标记，恢复自动重启。
            foreach (var key in _services.Keys)
                UserStoppedRemove(key);
            _processManager.StartAll();
        });
        await RestoreDesiredServicesAsync();
    }

    /// <summary>
    /// 恢复用户上次显式启动过的展示/辅助服务（P1.2 DesiredState）。
    /// 核心服务由 StartAll 启动，这里只补拉起用户偏好中已启用的服务。
    /// </summary>
    private async Task RestoreDesiredServicesAsync()
    {
        var restored = new List<string>();
        foreach (var key in LauncherServices.OrderedKeys)
        {
            if (!_desiredEnabled.Contains(key)) continue;
            if (!_services.TryGetValue(key, out var svc)) continue;

            // 核心服务已由 StartAll 处理，跳过；只处理展示/辅助服务。
            if (LauncherServices.CoreStartupStages.Any(stage => stage.Contains(key))) continue;

            if (!LauncherProcessManager.IsServiceRunning(svc))
            {
                // 经 RunGuardRepairAsync 纳入管理动作互斥（review P2）：避免与 timer
                // 触发的 guard 修复并发进入 _starting（非同步 HashSet）。
                await RunGuardRepairAsync(() => _processManager.StartService(svc));
                // 启动后再确认（StartService 内部失败仅记日志，不抛异常）。
                if (LauncherProcessManager.IsServiceRunning(svc))
                    restored.Add(svc.Name);
            }
        }

        if (restored.Count > 0)
            Log($"已按上次偏好恢复服务: {string.Join("、", restored)}");
    }

    private bool UserStoppedContains(string key) => _processManager.IsUserStopped(key);

    private void UserStoppedAdd(string key) => _processManager.UserStoppedAdd(key);

    private void UserStoppedRemove(string key) => _processManager.UserStoppedRemove(key);

    /// <summary>记录服务启用/停用偏好并持久化（P1.2）。</summary>
    private void MarkDesired(string serviceKey, bool enabled)
    {
        if (enabled)
            _desiredEnabled.Add(serviceKey);
        else
            _desiredEnabled.Remove(serviceKey);
        _desiredState.SaveEnabled(_desiredEnabled);
    }

    private async Task RunManagerActionAsync(Action action)
    {
        if (_isManagerActionRunning || IsDisposed) return;

        _isManagerActionRunning = true;
        _timer.Stop();
        UseWaitCursor = true;
        // 与守卫后台修复共用互斥量：管理动作执行期间，守卫修复非阻塞放弃本轮。
        await _actionGate.WaitAsync();
        try
        {
            await Task.Run(action);
        }
        finally
        {
            _actionGate.Release();
            _isManagerActionRunning = false;
            if (!IsDisposed)
            {
                UseWaitCursor = false;
                _timer.Start();
            }
        }

        await RefreshStatusesAsync();
    }

    /// <summary>
    /// 守卫后台修复动作（P1，2026-10-31 复盘）：与管理器动作（启动/停止/全部停止/
    /// 重启）共用 _actionGate 互斥。管理动作进行中时非阻塞放弃本轮修复（下轮 3s
    /// 轮询会重新评估），杜绝“停止流程进行中又被守卫拉起”的并发交错。
    /// </summary>
    private async Task RunGuardRepairAsync(Action action)
    {
        if (IsDisposed) return;
        if (!await _actionGate.WaitAsync(TimeSpan.Zero)) return;
        try
        {
            await Task.Run(action);
        }
        catch (Exception ex)
        {
            Log($"守卫修复动作执行失败: {ex.Message}");
        }
        finally
        {
            _actionGate.Release();
        }
    }

    private async Task RefreshStatusesAsync()
    {
        if (_isRefreshingStatuses || IsDisposed) return;

        _isRefreshingStatuses = true;
        var services = _services.ToArray();
        Dictionary<string, bool> statuses;
        SnapshotCollectorHealth? collectorHealth = null;
        try
        {
            statuses = await Task.Run(() => services.ToDictionary(
                kv => kv.Key,
                kv => LauncherProcessManager.IsServiceRunning(kv.Value)));
            // 采集健康以 HTTP 契约为准，不再用端口探测做门禁（2026-10-19 复盘）：
            // 端口探测是 netstat/TCP 表 + 500ms 连接回退的双重启发式，TCP 表损坏
            // （LISTENING 行缺失）叠加线程池争用时会对活着的 8001 连续假阴性，旧逻辑
            // 据此判"离线"→ EnsureHealthy 停掉健康实例 → 残留锁 + 等锁实例自杀，
            // 当日 10:30 就是这样打断采集链的。服务能自报健康契约即证明它在监听。
            collectorHealth = await SnapshotCollectorProbe.GetHealthAsync();
            // 端口探测与健康契约合并（Core 判定）：服务自报成功即视为运行中，
            // 修正端口探测的瞬断假阴性，避免误走离线重启路径（2026-10-19 复盘）。
            statuses["collector"] = CollectorStatusResolver.IsRunning(
                statuses.GetValueOrDefault("collector"),
                collectorHealth);
        }
        finally
        {
            _isRefreshingStatuses = false;
        }

        if (IsDisposed) return;

        // 状态防抖（P1，2026-10-31 复盘）：
        // 1) 托管进程仍活着的服务，端口探测失败一律按假阴性处理，视为运行中
        //    （事件循环被同步长任务阻塞时 500ms/2s 连接探测都会失败，但进程没死，
        //    本日 09:06-09:07 quant-api 每 ~8.5s "已停止↔运行中"震荡即此成因）；
        // 2) 其余跳变需连续 2 次轮询一致才提交，单次假阴性不再直接翻转状态、
        //    不再联动按钮与守卫判定。
        var confirmed = new Dictionary<string, bool>(StringComparer.Ordinal);
        foreach (var kv in statuses)
        {
            var key = kv.Key;
            var raw = kv.Value;
            if (!raw && LauncherProcessManager.HasLiveManagedProcess(_services[key]))
            {
                _pendingStatuses.Remove(key);
                confirmed[key] = true;
                continue;
            }

            if (!_lastStatuses.TryGetValue(key, out var committed))
            {
                confirmed[key] = raw; // 首轮无基线，直接采纳
                continue;
            }

            if (raw == committed)
            {
                _pendingStatuses.Remove(key);
                confirmed[key] = committed;
                continue;
            }

            if (_pendingStatuses.TryGetValue(key, out var pending) && pending.Value == raw)
            {
                if (pending.Count + 1 >= 2)
                {
                    _pendingStatuses.Remove(key);
                    confirmed[key] = raw;
                }
                else
                {
                    _pendingStatuses[key] = (raw, pending.Count + 1);
                    confirmed[key] = committed;
                }
            }
            else
            {
                _pendingStatuses[key] = (raw, 1);
                confirmed[key] = committed;
            }
        }
        statuses = confirmed;

        // 状态跳变记录（2026-10-19 复盘）："盘中掉线又自动恢复"此前在日志里完全无痕，
        // 无法判断是端口探测假阴性还是进程真的退出。
        foreach (var kv in statuses)
        {
            if (_lastStatuses.TryGetValue(kv.Key, out var previous) && previous != kv.Value &&
                _services.TryGetValue(kv.Key, out var changed))
            {
                Log(kv.Value
                    ? $"{changed.Name} 状态变为运行中。"
                    : $"{changed.Name} 状态变为已停止（端口探测与深探测均未通过）。");
            }

            _lastStatuses[kv.Key] = kv.Value;
        }

        // 采集健康决策走内核：guard 做防抖 + Restartable 判定 + 恢复日志，
        // policy 做冷却/连续失败上限/指数退避。只有 guard 判定"应重启"且
        // policy 允许时才调用 EnsureHealthy 实际重启。
        var decision = _collectorGuard.Evaluate(collectorHealth);
        if (decision.LogMessage is not null)
            Log(decision.LogMessage);

        if (collectorHealth is not null && collectorHealth.IsHealthy)
        {
            // 恢复健康：清零重启失败计数。
            _restartPolicy.Reset("collector");
        }
        else if (decision.ShouldRestart && !UserStoppedContains("collector"))
        {
            // P0-B（2026-10-09 审计，P1-C 细化）：交易时段（09:15-15:10）内只允许
            // “拉起已死服务”与“基于可靠证据的修复性重启”，推迟的只有“健康证据
            // 不可靠”一种情形（fingerprint=probe:*：探针超时/不可达，09-15 10:00
            // 误杀教训）。服务自报的契约异常（如调度器锁丢失自停后的“调度器未
            // 运行”，restartable=true）是可靠证据，随时允许修复——否则会复刻
            // 09-11 锁丢失自停后两小时无采集的空窗。不计入失败次数。
            var unreliableEvidence = collectorHealth is not null &&
                SnapshotCollectorProbe.IsUnreliableHealthEvidence(collectorHealth.Fingerprint);
            if (statuses.GetValueOrDefault("collector") &&
                unreliableEvidence &&
                TradingWindow.IsInsideNow())
            {
                var nowUtc = DateTime.UtcNow;
                if (!_lastCollectorDeferredUtc.HasValue ||
                    nowUtc - _lastCollectorDeferredUtc.Value >= DeferredRepairLogInterval)
                {
                    _lastCollectorDeferredUtc = nowUtc;
                    Log(
                        "快照采集健康证据不可靠（探针超时/不可达）：交易时段（09:15-15:10）内" +
                        "不做停启式重启，已推迟到收盘后自动重试。");
                }
            }
            else if (_restartPolicy.TryRequestRestart("collector", out var blocked))
            {
                _lastRestartBlockedReason = "";
                // 修复动作含 taskkill/Sleep/CIM 枚举（秒级）：经 RunGuardRepairAsync
                // 与管理动作互斥后后台执行，防 UI 卡顿且不与停止流程交错（评审 P1）。
                // RecordRestart 在 action 内真正开始执行时才记（review P2）：gate 被
                // 管理动作占用而放弃本轮时，不消耗冷却/失败计数，下轮可重新请求。
                _ = RunGuardRepairAsync(() =>
                {
                    _restartPolicy.RecordRestart("collector");
                    _processManager.EnsureHealthy("collector");
                });
            }
            else if (blocked is not null &&
                     !string.Equals(_lastRestartBlockedReason, blocked, StringComparison.Ordinal))
            {
                _lastRestartBlockedReason = blocked;
                var detail = _restartPolicy.DescribeBlock("collector");
                Log($"快照采集错误: {blocked}" + (detail.Length > 0 ? $"（{detail}）" : ""));
            }
        }
        else if (collectorHealth is not null &&
                 !collectorHealth.IsHealthy &&
                 SnapshotCollectorProbe.IsLockWaitStartupFailureMarker(collectorHealth.Fingerprint))
        {
            // P1-C：锁冲突“wait 标记”只应保护正在等锁的活进程。等待实例 50 秒重试
            // 耗尽后 RuntimeError 自行退出，标记仍新鲜（10 分钟窗口），此前会继续
            // 压制自动拉起——旧锁 TTL ≤120s 早已过期，造成最长 10 分钟无谓停采。
            // 是否还有活着的等锁实例用命令行签名探测判定（评审 P1：launcher 晚于
            // 等待实例启动时 Process 为 null、等锁孤儿也可能存在，不能只看 tracked）。
            // 进程已退出 → 标记失效 → 立即重拉（StartService 不杀任何进程；
            // 新实例按 TTL 等待/清理旧锁，不会双采）。
            if (!UserStoppedContains("collector"))
            {
                string? lockWaitBlocked = null;
                if (_restartPolicy.TryRequestRestart("collector", out lockWaitBlocked))
                {
                    // CIM 存活探测（秒级）：仍有活着的等锁实例（tracked 或孤儿）
                    // 时不重拉，等它拿到锁；全部退出才拉起。经 RunGuardRepairAsync
                    // 与管理动作互斥后后台执行；RecordRestart 在 action 内真正
                    // 开始执行时才记（review P2，同上）。
                    _ = RunGuardRepairAsync(() =>
                    {
                        _restartPolicy.RecordRestart("collector");
                        if (_processManager.HasLiveProcessByCommandLine("collector"))
                            return;
                        Log("快照采集等锁实例已全部退出，锁冲突标记失效，自动重新拉起。");
                        _processManager.StartService(_services["collector"]);
                    });
                }
                else if (lockWaitBlocked is not null)
                {
                    // 冷却中：静默跳过（避免 3 秒轮询刷屏）
                }
            }
        }

        // 基础设施存活守护（P0-A）：mongo/redis 离线即自动拉起。直接 StartService
        // （不杀进程，交易时段内也允许）；外部实例占端口时可达，不会进入此分支。
        // 冷却/上限由 _restartPolicy 管控；用户手动停止过则尊重意图。
        foreach (var infraKey in InfraGuardKeys)
        {
            var infraReachable = statuses.GetValueOrDefault(infraKey);
            var infraDecision = _infraGuard.Evaluate(infraKey, _services[infraKey].Name, infraReachable);
            if (infraDecision.LogMessage is not null)
                Log(infraDecision.LogMessage);

            if (infraReachable)
            {
                _restartPolicy.Reset(infraKey);
                _lastInfraBlockedReason.Remove(infraKey);
                continue;
            }

            if (UserStoppedContains(infraKey)) continue;

            if (_restartPolicy.TryRequestRestart(infraKey, out var infraBlocked))
            {
                var infraService = _services[infraKey];
                // StartService 含 netstat/TCP 探测（秒级）：经 RunGuardRepairAsync
                // 与管理动作互斥后后台执行，防 UI 卡顿且不与停止流程交错（评审 P1）；
                // RecordRestart 在 action 内真正开始执行时才记（review P2，同上）。
                _ = RunGuardRepairAsync(() =>
                {
                    _restartPolicy.RecordRestart(infraKey);
                    _processManager.StartService(infraService);
                });
            }
            else if (infraBlocked is not null &&
                     !string.Equals(
                         _lastInfraBlockedReason.GetValueOrDefault(infraKey),
                         infraBlocked,
                         StringComparison.Ordinal))
            {
                _lastInfraBlockedReason[infraKey] = infraBlocked;
                var infraDetail = _restartPolicy.DescribeBlock(infraKey);
                Log(
                    $"{_services[infraKey].Name}: {infraBlocked}" +
                    (infraDetail.Length > 0 ? $"（{infraDetail}）" : ""));
            }
        }

        // 用户手动停止过 collector：不标红为"采集异常"（尊重意图，属正常停止）。
        var collectorFailed = decision.CollectFailed && !UserStoppedContains("collector");
        var running = 0;
        foreach (var kv in statuses)
        {
            var key = kv.Key;
            var isRunning = kv.Value;
            var serviceFailed = key == "collector" && collectorFailed;

            if (_dots.TryGetValue(key, out var dot))
            {
                dot.BackColor = isRunning && !serviceFailed ? _green : _red;
            }

            if (_statusLabels.TryGetValue(key, out var statusL))
            {
                statusL.Text = serviceFailed ? "采集异常" : isRunning ? "运行中" : "已停止";
                statusL.ForeColor = isRunning && !serviceFailed ? _green : _red;
            }

            UpdateServiceButtons(key, isRunning, serviceFailed);

            if (isRunning) running++;
        }

        Text = $"龙头看板 · 启动管理器  [{running}/{_services.Count} 在线]";
    }

    /// <summary>按服务真实运行状态联动启动/停止按钮，防止重复点击重复拉起进程。</summary>
    private void UpdateServiceButtons(string key, bool isRunning, bool serviceFailed)
    {
        // 运行且健康：禁止再次启动，允许停止；运行但采集异常：允许重启；未运行：允许启动，禁止停止。
        var startEnabled = !isRunning || serviceFailed;
        if (_startButtons.TryGetValue(key, out var start))
            ApplyButtonState(start, startEnabled, Color.FromArgb(42, 98, 72), Color.White);

        if (_stopButtons.TryGetValue(key, out var stop))
            ApplyButtonState(stop, isRunning, Color.FromArgb(58, 42, 46), _text);
    }

    private static void ApplyButtonState(
        Button button,
        bool enabled,
        Color enabledBack,
        Color enabledFore)
    {
        button.Enabled = enabled;
        if (enabled)
        {
            button.BackColor = enabledBack;
            button.ForeColor = enabledFore;
        }
        else
        {
            button.BackColor = Color.FromArgb(36, 40, 46);
            button.ForeColor = Color.FromArgb(100, 110, 120);
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

    private void OpenBoard()
    {
        OpenUrl("龙头看板", "http://127.0.0.1:3000");
    }

    /// <summary>
    /// 用默认浏览器打开 URL。2026-10-31 修复：原静默 catch（catch { }）导致
    /// “点击无反应且无痕”，违反 fail-visible；现在成功/失败都记日志。
    /// </summary>
    private void OpenUrl(string name, string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
            Log($"已在浏览器打开 {name}: {url}");
        }
        catch (Exception ex)
        {
            Log($"打开 {name} 失败（{url}）: {ex.Message}");
        }
    }

    private Point _restoreLocation;

    private void HideToTray()
    {
        // 最小化时 DesktopLocation 会变成 (-32000,-32000)（屏幕外），必须改用
        // RestoreBounds 保留恢复后的位置；窗口从未最小化时 RestoreBounds 是
        // (-1,-1) 占位值，此时（如点关闭按钮）仍用 DesktopLocation。
        _restoreLocation = WindowState == FormWindowState.Minimized
            ? RestoreBounds.Location
            : DesktopLocation;
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
        WindowState = FormWindowState.Normal;
        if (!_restoreLocation.IsEmpty)
        {
            DesktopLocation = _restoreLocation;
        }
        Show();
        BringToFront();
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
        // 全量落盘（UI 过滤之外的所有原始行，含子进程 stdout/stderr），
        // 不因 BeginInvoke 重入重复写入。
        if (!string.IsNullOrWhiteSpace(message))
            LogFile.Append($"[{DateTime.Now:HH:mm:ss}] {message}");
        LogCore(message);
    }

    private void LogCore(string message)
    {
        if (IsDisposed) return;
        if (!ShouldShowLog(message)) return;

        if (InvokeRequired)
        {
            try { BeginInvoke(() => LogCore(message)); }
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
