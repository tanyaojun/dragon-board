using System.Diagnostics;
using YiDongJingLing.Blocks;
using YiDongJingLing.Diagnostics;
using YiDongJingLing.Events;
using YiDongJingLing.MarketData;
using YiDongJingLing.Notifications;
using YiDongJingLing.Settings;
using YiDongJingLing.Speech;

namespace YiDongJingLing;

public sealed class MainForm : Form
{
    private const int MaxEventRecords = 100;
    private static readonly Color TerminalBack = Color.FromArgb(12, 16, 22);
    private static readonly Color TerminalPanel = Color.FromArgb(18, 24, 32);
    private static readonly Color TerminalPanelAlt = Color.FromArgb(22, 30, 40);
    private static readonly Color TerminalHeader = Color.FromArgb(28, 37, 49);
    private static readonly Color TerminalGrid = Color.FromArgb(43, 54, 68);
    private static readonly Color TerminalText = Color.FromArgb(214, 222, 232);
    private static readonly Color TerminalMuted = Color.FromArgb(138, 151, 168);
    private static readonly Color AccentGold = Color.FromArgb(214, 160, 72);
    private static readonly Color UpRed = Color.FromArgb(238, 82, 82);
    private static readonly Color DownGreen = Color.FromArgb(56, 186, 118);
    private static readonly Color WarnAmber = Color.FromArgb(232, 176, 72);

    private readonly SettingsStore _settingsStore = new();
    private readonly BlockFileScanner _scanner = new();
    private readonly BlockFileParser _parser = new();
    private readonly QuoteStateStore _quoteStore = new();
    private readonly L1EventRules _eventRules = new();
    private readonly L1EventEngine _eventEngine;
    private readonly EventDeduper _deduper = new();
    private readonly SpeechAnnouncer _speech;
    private readonly StockNameResolver _nameResolver = new();
    private readonly HotlistPoolLoader _hotlistLoader = new();
    private readonly EventRadarMessageNotifier _messageNotifier = new();
    private readonly OpeningSignalReporter _openingSignalReporter = new();
    private readonly List<EventRecord> _eventRecords = [];
    private readonly string _root;
    private readonly BridgeProcessManager _bridgeManager;
    private readonly ProxyProcessManager _proxyManager;

    private AppSettings _settings;
    private TdxBridgeClient? _bridgeClient;
    private FileSystemWatcher? _blockWatcher;
    private bool _loadingBlocks;
    private bool _blockListLoadedForTdx;
    private bool _connecting;
    private bool _closing;
    private bool _healthTicking;
    private int _reconnectAttempt;
    private int _todayEventTotal;
    private DateOnly _todayEventDate = DateOnly.FromDateTime(DateTime.Now);
    private DateTimeOffset _nextReconnectAt = DateTimeOffset.MinValue;
    private DateTimeOffset? _lastQuoteTime;
    private HashSet<string> _watchedCodes = new(StringComparer.Ordinal);

    private readonly System.Windows.Forms.Timer _healthTimer = new();
    private readonly NotifyIcon _trayIcon = new();
    private readonly ContextMenuStrip _trayMenu = new();
    private readonly TextBox _blockDirBox = new();
    private readonly CheckedListBox _blockList = new();
    private readonly DataGridView _eventsGrid = new();
    private readonly DataGridView _blocksGrid = new();
    private readonly TextBox _logBox = new();
    private readonly Label _statusLabel = new();
    private readonly Label _watchCountLabel = new();
    private readonly Label _bridgeStatusLabel = new();
    private readonly Label _eventCountLabel = new();
    private readonly Label _todayCountLabel = new();
    private readonly Label _lastQuoteLabel = new();
    private readonly Label _sessionLabel = new();
    private readonly Label _voiceModeLabel = new();
    private readonly Label _eventsTitleLabel = new();
    private readonly Label _eventsSummaryLabel = new();
    private readonly Label _blockSummaryLabel = new();
    private readonly TextBox _bridgeUrlBox = new();
    private readonly ComboBox _poolSourceBox = new();

    public MainForm()
    {
        _root = ProjectRootLocator.Find();
        _eventEngine = new L1EventEngine(_eventRules);
        _bridgeManager = new BridgeProcessManager(_root);
        _proxyManager = new ProxyProcessManager(_root);
        _speech = new SpeechAnnouncer(_root, Log);
        _settings = _settingsStore.Load();

        Text = "异动精灵 V2";
        Width = 1220;
        Height = 780;
        MinimumSize = new Size(1040, 660);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9f);
        BackColor = TerminalBack;

        BuildUI();
        ApplySettingsToUi();
        LoadBlockFiles();

        FormClosing += OnFormClosing;
        Resize += (_, _) =>
        {
            if (WindowState == FormWindowState.Minimized)
            {
                HideToTray();
            }
        };
        _healthTimer.Interval = 5000;
        _healthTimer.Tick += async (_, _) => await HealthTickAsync();
        _healthTimer.Start();

        Shown += (_, _) =>
        {
            Log("异动精灵已就绪。");
            Log($"项目目录: {_root}");
            UpdateRuntimeStatus();
            _ = AutoConnectOnStartupAsync();
        };
    }

    private void BuildUI()
    {
        BuildTray();

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = TerminalBack,
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(root);

        var top = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = TerminalPanel,
        };
        root.Controls.Add(top, 0, 0);

        var topLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Padding = new Padding(16, 7, 12, 7),
            BackColor = top.BackColor,
        };
        topLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        topLayout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        top.Controls.Add(topLayout);

        var brand = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            BackColor = top.BackColor,
        };
        brand.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        brand.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        topLayout.Controls.Add(brand, 0, 0);

        var title = new Label
        {
            Text = "异动精灵",
            ForeColor = AccentGold,
            Font = new Font("Microsoft YaHei UI", 16f, FontStyle.Bold),
            Dock = DockStyle.Fill,
        };
        brand.Controls.Add(title, 0, 0);

        _statusLabel.Text = "未连接";
        _statusLabel.ForeColor = TerminalText;
        _statusLabel.Dock = DockStyle.Fill;
        _statusLabel.AutoEllipsis = true;
        _statusLabel.TextAlign = ContentAlignment.MiddleLeft;
        brand.Controls.Add(_statusLabel, 0, 1);

        var commands = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = top.BackColor,
            Padding = new Padding(0, 7, 0, 0),
        };
        topLayout.Controls.Add(commands, 1, 0);

        var loadBtn = HeaderButton("加载板块", 88);
        loadBtn.Click += async (_, _) => await PickBlockFilesAndSubscribeAsync();
        commands.Controls.Add(loadBtn);

        var refreshBtn = HeaderButton("刷新", 58);
        refreshBtn.Click += async (_, _) => await RefreshMonitoringAsync(manual: true);
        commands.Controls.Add(refreshBtn);

        var startBridgeBtn = HeaderButton("启动行情", 86);
        startBridgeBtn.Click += async (_, _) => await EnsureBridgeReadyAsync();
        commands.Controls.Add(startBridgeBtn);

        var connectBtn = HeaderButton("重连监控", 86);
        connectBtn.Click += async (_, _) => await ConnectBridgeAsync();
        commands.Controls.Add(connectBtn);

        var settingsBtn = HeaderButton("设置", 58);
        settingsBtn.Click += (_, _) => ShowSettingsDialog();
        commands.Controls.Add(settingsBtn);

        var tabs = new TabControl
        {
            Dock = DockStyle.Fill,
            Padding = new Point(14, 5),
            HotTrack = true,
            ItemSize = new Size(116, 34),
            BackColor = TerminalBack,
            DrawMode = TabDrawMode.OwnerDrawFixed,
            SizeMode = TabSizeMode.Fixed,
        };
        tabs.Appearance = TabAppearance.FlatButtons;
        tabs.DrawItem += DrawFinancialTab;
        root.Controls.Add(tabs, 0, 1);

        tabs.TabPages.Add(BuildEventsPage());
        tabs.TabPages.Add(BuildBlocksPage());
        tabs.TabPages.Add(BuildLinkPage());
        tabs.TabPages.Add(BuildDiagnosticsPage());
    }

    private static Button HeaderButton(string text, int width = 96)
    {
        var button = new Button
        {
            Text = text,
            Size = new Size(width, 30),
            FlatStyle = FlatStyle.Flat,
            BackColor = TerminalHeader,
            ForeColor = TerminalText,
            Cursor = Cursors.Hand,
            Margin = new Padding(4, 0, 0, 0),
        };
        button.FlatAppearance.BorderColor = TerminalGrid;
        return button;
    }

    private TabPage BuildEventsPage()
    {
        var page = new TabPage("异动精灵") { BackColor = TerminalBack, Padding = new Padding(10) };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 72));
        page.Controls.Add(layout);

        var header = new Panel
        {
            Dock = DockStyle.Fill,
            BackColor = TerminalPanelAlt,
            Padding = new Padding(12, 5, 12, 4),
        };
        _eventsTitleLabel.Text = "异动列表";
        _eventsTitleLabel.Font = new Font(Font, FontStyle.Bold);
        _eventsTitleLabel.ForeColor = TerminalText;
        _eventsTitleLabel.Location = new Point(12, 6);
        _eventsTitleLabel.AutoSize = true;
        header.Controls.Add(_eventsTitleLabel);

        _eventsSummaryLabel.Text = "等待行情事件";
        _eventsSummaryLabel.ForeColor = TerminalMuted;
        _eventsSummaryLabel.Location = new Point(12, 24);
        _eventsSummaryLabel.AutoSize = true;
        header.Controls.Add(_eventsSummaryLabel);
        layout.Controls.Add(header, 0, 0);

        ConfigureGrid(_eventsGrid);
        _eventsGrid.ColumnHeadersHeight = 30;
        _eventsGrid.Columns.Add("Time", "时间");
        _eventsGrid.Columns.Add("Type", "异动类型");
        _eventsGrid.Columns.Add("Code", "股票代码");
        _eventsGrid.Columns.Add("Name", "股票名称");
        _eventsGrid.Columns.Add("Change", "涨跌幅");
        _eventsGrid.Columns.Add("Price", "最新价");
        _eventsGrid.Columns.Add("Volume", "成交量");
        _eventsGrid.Columns.Add("Amount", "成交额");
        _eventsGrid.Columns.Add("Reason", "异动详情");
        _eventsGrid.Columns["Time"]!.FillWeight = 62;
        _eventsGrid.Columns["Type"]!.FillWeight = 90;
        _eventsGrid.Columns["Code"]!.FillWeight = 72;
        _eventsGrid.Columns["Name"]!.FillWeight = 90;
        _eventsGrid.Columns["Change"]!.FillWeight = 58;
        _eventsGrid.Columns["Price"]!.FillWeight = 58;
        _eventsGrid.Columns["Volume"]!.FillWeight = 76;
        _eventsGrid.Columns["Amount"]!.FillWeight = 76;
        _eventsGrid.Columns["Reason"]!.FillWeight = 250;
        _eventsGrid.Columns["Change"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        _eventsGrid.Columns["Price"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        _eventsGrid.Columns["Volume"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        _eventsGrid.Columns["Amount"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        _eventsGrid.DoubleClick += (_, _) => CopySelectedEventCode();
        layout.Controls.Add(_eventsGrid, 0, 1);

        var footer = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            BackColor = TerminalPanel,
            Padding = new Padding(8, 7, 8, 7),
        };
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        footer.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var statusFlow = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = true,
            BackColor = TerminalPanel,
        };
        _watchCountLabel.Text = "监控 0 只";
        StyleStatusLabel(_watchCountLabel);
        statusFlow.Controls.Add(_watchCountLabel);
        var bridgePort = ResolveBridgePort(_settings.BridgeUrl);
        _bridgeStatusLabel.Text = BridgeProcessManager.IsPortOpen(bridgePort)
            ? $"行情桥：{bridgePort} 运行"
            : $"行情桥：{bridgePort} 未就绪";
        StyleStatusLabel(_bridgeStatusLabel);
        statusFlow.Controls.Add(_bridgeStatusLabel);
        _eventCountLabel.Text = $"记录 0/{MaxEventRecords}";
        StyleStatusLabel(_eventCountLabel);
        statusFlow.Controls.Add(_eventCountLabel);
        _todayCountLabel.Text = "今日累计 0";
        StyleStatusLabel(_todayCountLabel);
        statusFlow.Controls.Add(_todayCountLabel);
        _lastQuoteLabel.Text = "最近行情 --";
        StyleStatusLabel(_lastQuoteLabel);
        statusFlow.Controls.Add(_lastQuoteLabel);
        _sessionLabel.Text = "交易时段 --";
        StyleStatusLabel(_sessionLabel);
        statusFlow.Controls.Add(_sessionLabel);
        _voiceModeLabel.Text = "语音 --";
        StyleStatusLabel(_voiceModeLabel);
        statusFlow.Controls.Add(_voiceModeLabel);
        footer.Controls.Add(statusFlow, 0, 0);

        var actions = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = TerminalPanel,
        };
        var exportBtn = SecondaryButton("导出记录", 88);
        exportBtn.Click += (_, _) => ExportEvents();
        actions.Controls.Add(exportBtn);

        var clearBtn = SecondaryButton("清空", 68);
        clearBtn.Click += (_, _) =>
        {
            ClearEventRows();
        };
        actions.Controls.Add(clearBtn);
        footer.Controls.Add(actions, 1, 0);
        layout.Controls.Add(footer, 0, 2);

        return page;
    }

    private TabPage BuildBlocksPage()
    {
        var page = new TabPage("监控板块") { BackColor = TerminalBack, Padding = new Padding(10) };
        var pageLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
        };
        pageLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 122));
        pageLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        page.Controls.Add(pageLayout);

        var top = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            BackColor = TerminalPanelAlt,
            Padding = new Padding(12, 8, 12, 8),
        };
        top.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        top.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        top.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        pageLayout.Controls.Add(top, 0, 0);

        var blockHeader = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
        };
        blockHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        blockHeader.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var title = new Label
        {
            Text = "监控板块",
            Dock = DockStyle.Fill,
            Font = new Font(Font, FontStyle.Bold),
            ForeColor = TerminalText,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        blockHeader.Controls.Add(title, 0, 0);
        _blockSummaryLabel.Text = "请选择要监控的 .blk 文件";
        _blockSummaryLabel.ForeColor = TerminalMuted;
        _blockSummaryLabel.AutoSize = true;
        _blockSummaryLabel.TextAlign = ContentAlignment.MiddleRight;
        blockHeader.Controls.Add(_blockSummaryLabel, 1, 0);
        top.Controls.Add(blockHeader, 0, 0);

        var sourceRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
        };
        sourceRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 138));
        sourceRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 240));
        sourceRow.Controls.Add(new Label
        {
            Text = "股票池来源",
            Dock = DockStyle.Fill,
            ForeColor = TerminalText,
            TextAlign = ContentAlignment.MiddleLeft,
        }, 0, 0);
        _poolSourceBox.Dock = DockStyle.Fill;
        _poolSourceBox.DropDownStyle = ComboBoxStyle.DropDownList;
        _poolSourceBox.Margin = new Padding(0, 3, 8, 0);
        _poolSourceBox.BackColor = TerminalPanel;
        _poolSourceBox.ForeColor = TerminalText;
        _poolSourceBox.Items.AddRange([StockPoolSourceOption.TdxBlock, StockPoolSourceOption.Hotlist]);
        _poolSourceBox.SelectedIndexChanged += async (_, _) =>
        {
            if (_poolSourceBox.SelectedItem is not StockPoolSourceOption selected ||
                _settings.StockPoolSource == selected.Source)
            {
                return;
            }

            _settings.StockPoolSource = selected.Source;
            SaveSettingsFromUi();
            SetBlockControlsEnabled();
            if (_settings.StockPoolSource == StockPoolSource.TdxBlock)
            {
                LoadBlockFiles();
            }
            UpdateBlockSelectionSummary();
            await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
        };
        sourceRow.Controls.Add(_poolSourceBox, 1, 0);
        top.Controls.Add(sourceRow, 0, 1);

        var pathRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 1,
        };
        pathRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 138));
        pathRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        pathRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var label = new Label
        {
            Text = "blocknew 目录",
            Dock = DockStyle.Fill,
            ForeColor = TerminalText,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        pathRow.Controls.Add(label, 0, 0);
        _blockDirBox.Dock = DockStyle.Fill;
        _blockDirBox.Margin = new Padding(0, 6, 8, 0);
        _blockDirBox.BackColor = TerminalPanel;
        _blockDirBox.ForeColor = TerminalText;
        _blockDirBox.BorderStyle = BorderStyle.FixedSingle;
        pathRow.Controls.Add(_blockDirBox, 1, 0);

        var blockActions = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Padding = new Padding(0, 3, 0, 0),
        };
        var browseBtn = SecondaryButton("选择", 66);
        browseBtn.Click += async (_, _) => await BrowseBlockDirectoryAsync();
        blockActions.Controls.Add(browseBtn);

        var scanBtn = SecondaryButton("扫描", 66);
        scanBtn.Click += (_, _) => LoadBlockFiles();
        blockActions.Controls.Add(scanBtn);

        var loadSelectedBtn = PrimaryButton("加载选中", 88);
        loadSelectedBtn.Click += async (_, _) => await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
        blockActions.Controls.Add(loadSelectedBtn);

        var saveBtn = SecondaryButton("保存", 66);
        saveBtn.Click += (_, _) =>
        {
            SaveSettingsFromUi();
            Log("监控板块设置已保存。");
        };
        blockActions.Controls.Add(saveBtn);
        pathRow.Controls.Add(blockActions, 2, 0);
        top.Controls.Add(pathRow, 0, 2);

        var split = new SplitContainer
        {
            Dock = DockStyle.Fill,
            SplitterWidth = 6,
            BackColor = TerminalBack,
        };
        split.Panel1.BackColor = TerminalBack;
        split.Panel2.BackColor = TerminalBack;
        split.HandleCreated += (_, _) => split.SplitterDistance = Math.Min(320, Math.Max(220, split.Width / 3));
        pageLayout.Controls.Add(split, 0, 1);

        var leftLayout = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2 };
        leftLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        leftLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        leftLayout.Controls.Add(SectionLabel("板块文件"), 0, 0);
        _blockList.Dock = DockStyle.Fill;
        _blockList.CheckOnClick = true;
        _blockList.BorderStyle = BorderStyle.FixedSingle;
        _blockList.BackColor = TerminalPanel;
        _blockList.ForeColor = TerminalText;
        _blockList.ItemCheck += (_, _) =>
        {
            if (_loadingBlocks) return;
            if (IsHandleCreated)
            {
                BeginInvoke(new Action(UpdateBlockSelectionSummary));
            }
            else
            {
                UpdateBlockSelectionSummary();
            }
        };
        leftLayout.Controls.Add(_blockList, 0, 1);
        split.Panel1.Controls.Add(leftLayout);

        var rightLayout = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, Padding = new Padding(8, 0, 0, 0) };
        rightLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        rightLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        rightLayout.Controls.Add(SectionLabel("扫描结果"), 0, 0);
        ConfigureGrid(_blocksGrid);
        _blocksGrid.Columns.Add("Name", "名称");
        _blocksGrid.Columns.Add("Count", "股票数");
        _blocksGrid.Columns.Add("Issues", "异常");
        _blocksGrid.Columns.Add("Path", "路径");
        _blocksGrid.Columns["Name"]!.FillWeight = 80;
        _blocksGrid.Columns["Count"]!.FillWeight = 50;
        _blocksGrid.Columns["Issues"]!.FillWeight = 50;
        _blocksGrid.Columns["Path"]!.FillWeight = 260;
        _blocksGrid.Columns["Count"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        _blocksGrid.Columns["Issues"]!.DefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleRight;
        rightLayout.Controls.Add(_blocksGrid, 0, 1);
        split.Panel2.Controls.Add(rightLayout);

        return page;
    }

    private TabPage BuildLinkPage()
    {
        var page = new TabPage("联动") { BackColor = TerminalBack, Padding = new Padding(18) };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 54));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        page.Controls.Add(layout);
        layout.Controls.Add(SectionLabel("通达信联动"), 0, 0);
        var info = new Label
        {
            Text = "联动先提供复制代码和打开通达信目录。精确定位股票需要后续实测通达信热键或命令行。",
            Dock = DockStyle.Fill,
            ForeColor = TerminalMuted,
            TextAlign = ContentAlignment.MiddleLeft,
        };
        layout.Controls.Add(info, 0, 1);

        var actions = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = 42,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            BackColor = TerminalBack,
        };
        var copyBtn = PrimaryButton("复制选中代码", 118);
        copyBtn.Click += (_, _) => CopySelectedEventCode();
        actions.Controls.Add(copyBtn);

        var openTdxBtn = SecondaryButton("打开 TDX 目录", 118);
        openTdxBtn.Click += (_, _) =>
        {
            var root = ResolveTdxRootFromBlockDirectory(_blockDirBox.Text.Trim());
            if (!string.IsNullOrWhiteSpace(root) && Directory.Exists(root))
            {
                Process.Start(new ProcessStartInfo(root) { UseShellExecute = true });
            }
        };
        actions.Controls.Add(openTdxBtn);
        layout.Controls.Add(actions, 0, 2);

        return page;
    }

    private TabPage BuildDiagnosticsPage()
    {
        var page = new TabPage("诊断") { BackColor = TerminalBack, Padding = new Padding(10) };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        page.Controls.Add(layout);
        var header = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            BackColor = TerminalBack,
        };
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        header.Controls.Add(SectionLabel("诊断日志"), 0, 0);
        var clearLogBtn = SecondaryButton("清空日志", 82);
        clearLogBtn.Click += (_, _) => _logBox.Clear();
        header.Controls.Add(clearLogBtn, 1, 0);
        layout.Controls.Add(header, 0, 0);
        _logBox.Dock = DockStyle.Fill;
        _logBox.Multiline = true;
        _logBox.ReadOnly = true;
        _logBox.ScrollBars = ScrollBars.Vertical;
        _logBox.Font = new Font("Consolas", 9f);
        _logBox.BackColor = Color.FromArgb(9, 12, 18);
        _logBox.ForeColor = TerminalText;
        _logBox.BorderStyle = BorderStyle.None;
        layout.Controls.Add(_logBox, 0, 1);
        return page;
    }

    private void ApplySettingsToUi()
    {
        _blockDirBox.Text = _settings.BlockDirectory;
        _bridgeUrlBox.Text = _settings.BridgeUrl;
        _poolSourceBox.SelectedItem = StockPoolSourceOption.FromSource(_settings.StockPoolSource);
        TopMost = false;
        Opacity = Math.Clamp(_settings.Opacity, 0.6d, 1d);
        SetBlockControlsEnabled();
        ApplyEventRuleSettings();
        ApplySpeechSettings();
        UpdateRuntimeStatus();
    }

    private void SaveSettingsFromUi()
    {
        _settings.BlockDirectory = _blockDirBox.Text.Trim();
        _settings.BridgeUrl = _bridgeUrlBox.Text.Trim();
        if (_poolSourceBox.SelectedItem is StockPoolSourceOption selected)
        {
            _settings.StockPoolSource = selected.Source;
        }
        _settings.SelectedBlockFiles = ResolveSelectedBlockFilesForSave(
            _settings.StockPoolSource,
            _settings.SelectedBlockFiles,
            CheckedBlockPaths(),
            _blockListLoadedForTdx);
        _settings.TopMost = false;
        _settingsStore.Save(_settings);
        ApplyEventRuleSettings();
        ApplySpeechSettings();
    }

    private void ApplyEventRuleSettings()
    {
        _eventRules.RiseTiers = [NormalizePositive(_settings.RiseBreakthroughPct, 7m)];
        _eventRules.DropTiers = [NormalizePositive(_settings.DropBreakthroughPct, 7m)];
        var fiveMinuteMovePct = NormalizePositive(_settings.FiveMinuteMovePct, 5m);
        _eventRules.FastRise300SecPct = fiveMinuteMovePct;
        _eventRules.FastDrop300SecPct = -fiveMinuteMovePct;
        _eventRules.AmountTiers = [NormalizePositive(_settings.LargeAmountThresholdWan, 10_000m) * 10_000m];
        _eventRules.LargeOrderAmount = NormalizePositive(_settings.LargeOrderThresholdWan, 1_000m) * 10_000m;
        _eventRules.OpenGapPct = NormalizePositive(_settings.OpenGapPct, 1m);
        _eventRules.LongBodyPct = NormalizePositive(_settings.LongBodyPct, 4m);
    }

    private void SetBlockControlsEnabled()
    {
        var enabled = _settings.StockPoolSource == StockPoolSource.TdxBlock;
        _blockDirBox.Enabled = enabled;
        _blockList.Enabled = enabled;
        _blocksGrid.Enabled = enabled;
    }

    private void ApplySpeechSettings()
    {
        _speech.Enabled = _settings.VoiceEnabled && _settings.VoiceMode != VoiceMode.Muted;
        _speech.Rate = _settings.VoiceRate;
        _speech.Volume = _settings.VoiceVolume;
        _speech.Voice = _settings.VoiceName;
        UpdateVoiceModeLabel();
    }

    private void ShowSettingsDialog()
    {
        using var dialog = new SettingsForm(_settings, _speech.GetVoices(), _speech);
        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        var shouldRefreshPool = _settings.FilterStStocks != dialog.Settings.FilterStStocks ||
            _settings.StockPoolSource != dialog.Settings.StockPoolSource;
        _settings = dialog.Settings;
        ApplySettingsToUi();
        SaveSettingsFromUi();
        TopMost = false;
        if (shouldRefreshPool)
        {
            _ = LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
        }
        Log("设置已保存。");
    }

    private void BuildTray()
    {
        _trayMenu.Items.Add("显示窗口", null, (_, _) => RestoreFromTray());
        _trayMenu.Items.Add("静音/恢复", null, (_, _) => ToggleMute());
        _trayMenu.Items.Add(new ToolStripSeparator());
        _trayMenu.Items.Add("退出", null, (_, _) =>
        {
            _closing = true;
            Close();
        });

        _trayIcon.Text = "异动精灵";
        _trayIcon.Icon = SystemIcons.Application;
        _trayIcon.ContextMenuStrip = _trayMenu;
        _trayIcon.DoubleClick += (_, _) => RestoreFromTray();
    }

    private void LoadBlockFiles()
    {
        var directory = _blockDirBox.Text.Trim();
        _nameResolver.LoadFromBlockDirectory(directory);
        if (_settings.StockPoolSource == StockPoolSource.Hotlist)
        {
            _blockListLoadedForTdx = false;
            _blockSummaryLabel.Text = "当前使用八平台热榜股票池";
            ResetBlockWatcher("");
            return;
        }

        _loadingBlocks = true;
        _blockListLoadedForTdx = false;
        try
        {
            _blockList.Items.Clear();
            _blocksGrid.Rows.Clear();

            var blocks = _scanner.Scan(directory);
            var selected = new HashSet<string>(_settings.SelectedBlockFiles, StringComparer.OrdinalIgnoreCase);
            foreach (var block in blocks)
            {
                var index = _blockList.Items.Add(new BlockListItem(block.Name, block.Path));
                _blockList.SetItemChecked(index, selected.Contains(block.Path));
                _blocksGrid.Rows.Add(block.Name, block.StockCount, block.IssueCount, block.Path);
            }

            Log($"扫描板块目录完成: {blocks.Count} 个 .blk 文件。");
            _blockListLoadedForTdx = true;
        }
        finally
        {
            _loadingBlocks = false;
        }

        UpdateBlockSelectionSummary();
        ResetBlockWatcher(directory);
    }

    private void ResetBlockWatcher(string directory)
    {
        _blockWatcher?.Dispose();
        _blockWatcher = null;
        if (!Directory.Exists(directory)) return;

        _blockWatcher = new FileSystemWatcher(directory, "*.blk")
        {
            NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.FileName | NotifyFilters.Size,
            EnableRaisingEvents = true,
        };
        _blockWatcher.Changed += (_, e) => BeginInvoke(new Action(() => _ = HandleBlockFileChangedAsync(e.FullPath)));
        _blockWatcher.Created += (_, _) => BeginInvoke(new Action(() => _ = RefreshMonitoringAsync(manual: false)));
        _blockWatcher.Deleted += (_, _) => BeginInvoke(new Action(() => _ = RefreshMonitoringAsync(manual: false)));
        _blockWatcher.Renamed += (_, _) => BeginInvoke(new Action(() => _ = RefreshMonitoringAsync(manual: false)));
    }

    private async Task BrowseBlockDirectoryAsync()
    {
        if (_settings.StockPoolSource == StockPoolSource.Hotlist)
        {
            Log("当前股票池来源为八平台热榜，无需选择 .blk 目录。");
            return;
        }

        using var dialog = new FolderBrowserDialog
        {
            Description = "选择通达信 T0002\\blocknew 目录",
            SelectedPath = Directory.Exists(_blockDirBox.Text) ? _blockDirBox.Text : Environment.GetFolderPath(Environment.SpecialFolder.Desktop),
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _blockDirBox.Text = dialog.SelectedPath;
            LoadBlockFiles();
            await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
        }
    }

    private async Task HandleBlockFileChangedAsync(string path)
    {
        Log($"板块文件变化: {Path.GetFileName(path)}");
        if (!_settings.SelectedBlockFiles.Contains(path, StringComparer.OrdinalIgnoreCase)) return;

        try
        {
            LoadBlockFiles();
            await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: false);
        }
        catch (Exception ex)
        {
            Log($"重载板块失败: {ex.Message}");
        }
    }

    private async Task RefreshMonitoringAsync(bool manual)
    {
        try
        {
            if (_settings.StockPoolSource == StockPoolSource.TdxBlock)
            {
                LoadBlockFiles();
            }
            await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
            Log(manual ? "已手动刷新股票池和监控订阅。" : "股票池变化，已自动刷新监控订阅。");
        }
        catch (Exception ex)
        {
            Log($"刷新失败: {ex.Message}");
        }
    }

    private async Task PickBlockFilesAndSubscribeAsync()
    {
        if (_settings.StockPoolSource == StockPoolSource.Hotlist)
        {
            await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
            return;
        }

        var initialDir = Directory.Exists(_blockDirBox.Text)
            ? _blockDirBox.Text
            : Directory.Exists(_settings.BlockDirectory)
                ? _settings.BlockDirectory
                : Environment.GetFolderPath(Environment.SpecialFolder.Desktop);

        using var dialog = new OpenFileDialog
        {
            Title = "选择通达信 .blk 板块文件",
            InitialDirectory = initialDir,
            Filter = "通达信板块文件 (*.blk)|*.blk|所有文件 (*.*)|*.*",
            Multiselect = true,
        };

        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        var directory = Path.GetDirectoryName(dialog.FileNames[0]);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            _blockDirBox.Text = directory;
            _settings.BlockDirectory = directory;
            LoadBlockFiles();
        }

        SelectBlockFiles(dialog.FileNames);
        await LoadSelectedBlocksAndSubscribeAsync(resetRuntimeState: true);
    }

    private async Task LoadSelectedBlocksAndSubscribeAsync(bool resetRuntimeState)
    {
        SaveSettingsFromUi();
        var loadResult = await LoadSelectedCodesAsync();
        var codes = loadResult.Codes;
        _watchedCodes = new HashSet<string>(codes, StringComparer.Ordinal);
        if (resetRuntimeState)
        {
            ClearRuntimeState();
            ClearEventRows();
        }
        _watchCountLabel.Text = $"监控 {codes.Count} 只";
        _statusLabel.Text = codes.Count > 0 ? $"已加载 {codes.Count} 只股票" : "未选择有效股票";
        UpdateRuntimeStatus();
        Log(loadResult.Message);

        if (_bridgeClient?.IsConnected == true)
        {
            await _bridgeClient.SendSubscriptionAsync(codes);
            Log(codes.Count > 0 ? "已向行情桥更新监控池。" : "已清空行情桥监控池。");
        }
    }

    private async Task<StockPoolLoadResult> LoadSelectedCodesAsync()
    {
        if (_settings.StockPoolSource == StockPoolSource.Hotlist)
        {
            return await LoadHotlistCodesAsync();
        }

        if (!_blockListLoadedForTdx)
        {
            LoadBlockFiles();
        }
        var codes = LoadSelectedBlockCodes();
        return new StockPoolLoadResult(
            codes,
            $"已加载监控池: {codes.Count} 只股票，来自 {CheckedBlockPaths().Count()} 个 .blk 文件。");
    }

    private IReadOnlyList<string> LoadSelectedBlockCodes()
    {
        var codes = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var path in CheckedBlockPaths())
        {
            var result = _parser.ParseFile(path);
            foreach (var item in result.Codes)
            {
                if (_settings.FilterStStocks && IsStStockName(_nameResolver.Resolve(item.Code)))
                {
                    continue;
                }
                codes.Add(item.Code);
            }
            if (result.Issues.Count > 0)
            {
                Log($"{Path.GetFileName(path)} 解析提示: {result.Issues.Count} 条异常。");
            }
        }

        return codes.ToArray();
    }

    private async Task<StockPoolLoadResult> LoadHotlistCodesAsync()
    {
        if (!BridgeProcessManager.IsPortOpen(3000))
        {
            _proxyManager.StartProxy(Log);
            await WaitForProxyPortAsync(3000, "八平台热榜可能加载失败");
        }

        var result = await _hotlistLoader.LoadAsync(new Uri("http://127.0.0.1:3000"));
        foreach (var stock in result.Stocks)
        {
            if (!string.IsNullOrWhiteSpace(stock.Name))
            {
                _nameResolver.Resolve(stock.Code, stock.Name);
            }
        }

        var codes = result.Stocks
            .Where(stock => !_settings.FilterStStocks || !IsStStockName(_nameResolver.Resolve(stock.Code, stock.Name)))
            .Select(stock => stock.Code)
            .Distinct(StringComparer.Ordinal)
            .Order(StringComparer.Ordinal)
            .ToArray();
        var failedText = result.Errors.Count > 0 ? $"，{result.Errors.Count} 个平台失败" : "";
        if (result.Errors.Count > 0)
        {
            Log("八平台热榜部分来源失败: " + string.Join("; ", result.Errors.Take(3)));
        }

        return new StockPoolLoadResult(codes, $"已加载八平台热榜股票池: {codes.Length} 只股票{failedText}。");
    }

    private void SelectBlockFiles(IEnumerable<string> paths)
    {
        var selected = new HashSet<string>(
            paths.Select(path => Path.GetFullPath(path)),
            StringComparer.OrdinalIgnoreCase);

        for (var i = 0; i < _blockList.Items.Count; i++)
        {
            if (_blockList.Items[i] is not BlockListItem item) continue;
            _blockList.SetItemChecked(i, selected.Contains(Path.GetFullPath(item.Path)));
        }

        UpdateBlockSelectionSummary();
        SaveSettingsFromUi();
    }

    private void ClearRuntimeState()
    {
        _quoteStore.Clear();
        _eventEngine.Clear();
        _deduper.Clear();
    }

    private void ClearEventRows()
    {
        _eventRecords.Clear();
        _eventsGrid.Rows.Clear();
        ResetTodayCounterIfNeeded();
        _eventsSummaryLabel.Text = _watchedCodes.Count > 0
            ? $"等待监控池内 {_watchedCodes.Count} 只股票的异动"
            : "等待行情事件";
        UpdateEventCountLabel();
    }

    private async Task AutoConnectOnStartupAsync()
    {
        try
        {
            _statusLabel.Text = "正在自动连接...";
            await EnsureBridgeReadyAsync();
            if (!IsDisposed)
            {
                await ConnectBridgeAsync();
            }
        }
        catch (Exception ex)
        {
            _bridgeStatusLabel.Text = "行情桥：自动连接失败";
            Log($"自动连接失败: {ex.Message}");
        }
    }

    private async Task EnsureBridgeReadyAsync()
    {
        var port = ResolveBridgePort(_settings.BridgeUrl);
        if (!BridgeProcessManager.IsPortOpen(port))
        {
            _bridgeManager.StartBridge(Log, port);
        }

        await WaitForBridgePortAsync(port);
    }

    private async Task ConnectBridgeAsync()
    {
        if (_connecting) return;
        _connecting = true;
        SaveSettingsFromUi();
        try
        {
            var codes = (await LoadSelectedCodesAsync()).Codes;
            _watchedCodes = new HashSet<string>(codes, StringComparer.Ordinal);
            if (codes.Count == 0)
            {
                _statusLabel.Text = "未选择有效股票";
                Log("没有可订阅的股票，请先选择 .blk 文件。");
                return;
            }

            _bridgeClient?.Disconnect();
            _bridgeClient?.Dispose();
            _bridgeClient = new TdxBridgeClient(_settings.BridgeUrl, SynchronizationContext.Current);
            _bridgeClient.StatusChanged += (_, status) =>
            {
                _bridgeStatusLabel.Text = status;
                if (!IsBridgeHeartbeatStatus(status))
                {
                    Log(status);
                }
                if (IsBridgeDisconnectedStatus(status))
                {
                    ScheduleReconnect();
                }
                UpdateRuntimeStatus();
            };
            _bridgeClient.QuotesReceived += (_, quotes) => HandleQuotes(quotes);
            ClearRuntimeState();
            await _bridgeClient.ConnectAsync(codes);
            _reconnectAttempt = 0;
            _nextReconnectAt = DateTimeOffset.MinValue;
            _watchCountLabel.Text = $"监控 {codes.Count} 只";
            _statusLabel.Text = $"已连接，监控 {codes.Count} 只股票";
            UpdateRuntimeStatus();
        }
        catch (Exception ex)
        {
            _bridgeStatusLabel.Text = "行情桥：连接失败";
            Log($"连接行情桥失败: {ex.Message}");
            ScheduleReconnect();
            UpdateRuntimeStatus();
        }
        finally
        {
            _connecting = false;
        }
    }

    private async Task WaitForBridgePortAsync(int port)
    {
        for (var attempt = 0; attempt < 20; attempt++)
        {
            if (BridgeProcessManager.IsPortOpen(port))
            {
                _bridgeStatusLabel.Text = "行情桥：运行";
                UpdateRuntimeStatus();
                Log($"行情桥端口 {port} 已就绪。");
                return;
            }

            await Task.Delay(300);
        }

        _bridgeStatusLabel.Text = "行情桥：未就绪";
        UpdateRuntimeStatus();
        Log($"行情桥启动后暂未检测到 {port} 端口，请查看诊断日志。");
    }

    private async Task WaitForProxyPortAsync(int port, string failureHint)
    {
        for (var attempt = 0; attempt < 20; attempt++)
        {
            if (BridgeProcessManager.IsPortOpen(port))
            {
                Log($"本地代理端口 {port} 已就绪。");
                return;
            }

            await Task.Delay(300);
        }

        Log($"本地代理启动后暂未检测到 {port} 端口，{failureHint}。");
    }

    private void HandleQuotes(IReadOnlyList<QuoteSnapshot> quotes)
    {
        var allEvents = new List<EventRecord>();
        var skippedOutsideSession = 0;
        var primed = 0;
        var acceptedQuotes = 0;
        foreach (var quote in quotes)
        {
            if (!_watchedCodes.Contains(quote.Code)) continue;

            var normalizedQuote = WithResolvedName(quote);
            if (_settings.FilterStStocks && IsStStockName(normalizedQuote.Name))
            {
                continue;
            }
            acceptedQuotes++;
            _lastQuoteTime = normalizedQuote.SourceTime;
            var previous = _quoteStore.Apply(normalizedQuote);

            if (previous is null)
            {
                _eventEngine.Prime(normalizedQuote);
                primed++;
                continue;
            }

            if (!TradingSession.IsContinuousAuction(normalizedQuote.SourceTime))
            {
                _eventEngine.Prime(normalizedQuote);
                skippedOutsideSession++;
                continue;
            }

            var history = _quoteStore.GetHistory(normalizedQuote.Code);
            allEvents.AddRange(_eventEngine.Evaluate(normalizedQuote, previous, history));
        }

        if (primed > 0)
        {
            _eventsSummaryLabel.Text = $"已建立 {primed} 只股票基线，等待交易时段增量异动";
        }
        if (skippedOutsideSession > 0)
        {
            _eventsSummaryLabel.Text = $"非连续竞价时段，已忽略 {skippedOutsideSession} 条静态行情";
        }

        if (acceptedQuotes > 0)
        {
            UpdateRuntimeStatus();
        }

        var enabled = allEvents
            .Where(item => _settings.IsEventEnabled(item.Type.ToString()))
            .ToArray();
        var emitted = _deduper.Filter(enabled);
        if (emitted.Count == 0) return;

        foreach (var item in emitted)
        {
            AddEventRow(item);
        }
        var openingEvents = emitted
            .Where(item => item.Type == L1EventType.OpeningWeakToStrong)
            .ToArray();
        var shouldAnnounceOpening = EventVoicePolicy.FilterForVoice(openingEvents, _settings.VoiceMode).Count > 0;
        var voiceEvents = EventVoicePolicy
            .FilterForVoice(emitted.Where(item => item.Type != L1EventType.OpeningWeakToStrong), _settings.VoiceMode)
            .ToList();
        if (openingEvents.Length > 0)
        {
            _ = ReportOpeningSignalsAndAnnounceAsync(openingEvents, shouldAnnounceOpening);
        }
        if (voiceEvents.Count > 0)
        {
            _speech.Announce(voiceEvents);
        }
        if (_settings.SyncMessages)
        {
            _ = SyncMessagesAsync(emitted.ToArray());
        }
    }

    private async Task SyncMessagesAsync(IReadOnlyList<EventRecord> events)
    {
        if (events.Count == 0) return;

        try
        {
            if (!BridgeProcessManager.IsPortOpen(3000))
            {
                _proxyManager.StartProxy(Log);
                await WaitForProxyPortAsync(3000, "同步消息可能发送失败");
            }

            var result = await _messageNotifier.SendEventsAsync(events, new Uri("http://127.0.0.1:3000"));
            if (result.Queued > 0 || result.Sent > 0)
            {
                Log($"同步消息已提交飞书机器人: 入队 {result.Queued} 条，已发 {result.Sent} 条。");
            }
            else if (result.Skipped > 0)
            {
                Log($"同步消息已跳过 {result.Skipped} 条重复或冷却中的异动。");
            }
        }
        catch (Exception ex)
        {
            Log($"同步消息失败: {ex.Message}");
        }
    }

    private async Task ReportOpeningSignalsAndAnnounceAsync(
        IReadOnlyList<EventRecord> events,
        bool announceWhenOwned)
    {
        if (events.Count == 0) return;

        try
        {
            if (!BridgeProcessManager.IsPortOpen(3000))
            {
                _proxyManager.StartProxy(Log);
                await WaitForProxyPortAsync(3000, "竞价信号语音仲裁可能失败");
            }

            var voiceEvents = new List<EventRecord>();
            foreach (var item in events)
            {
                var result = await _openingSignalReporter.ReportAsync(item, new Uri("http://127.0.0.1:3000"));
                Log($"竞价弱转强信号已上报: {item.Code} {result.DedupeAction} voiceOwner={result.VoiceOwner}");
                if (announceWhenOwned && result.VoiceOwner == "desktop")
                {
                    voiceEvents.Add(item);
                }
            }

            if (voiceEvents.Count > 0)
            {
                _speech.Announce(voiceEvents);
            }
        }
        catch (Exception ex)
        {
            Log($"竞价弱转强信号上报失败，已降级为本地播报: {ex.Message}");
            if (announceWhenOwned)
            {
                _speech.Announce(events);
            }
        }
    }

    private QuoteSnapshot WithResolvedName(QuoteSnapshot quote)
    {
        var name = _nameResolver.Resolve(quote.Code, quote.Name);
        return string.IsNullOrWhiteSpace(name) || name == quote.Name
            ? quote
            : quote with { Name = name };
    }

    private void AddEventRow(EventRecord item)
    {
        ResetTodayCounterIfNeeded();
        _todayEventTotal++;
        _eventRecords.Insert(0, item);
        var displayName = item.DisplayName;
        _eventsGrid.Rows.Insert(
            0,
            item.Timestamp.ToLocalTime().ToString("HH:mm:ss"),
            item.TypeName,
            item.Code,
            displayName,
            $"{item.ChangePct:0.##}%",
            $"{item.Price:0.00}",
            FormatVolume(item.Volume),
            FormatMoney(item.Amount),
            item.Reason);
        ApplyEventRowStyle(_eventsGrid.Rows[0], item);
        while (_eventRecords.Count > MaxEventRecords)
        {
            _eventRecords.RemoveAt(_eventRecords.Count - 1);
        }
        while (_eventsGrid.Rows.Count > MaxEventRecords)
        {
            _eventsGrid.Rows.RemoveAt(_eventsGrid.Rows.Count - 1);
        }

        _eventsSummaryLabel.Text = $"已捕获 {_eventRecords.Count} 条监控池内异动，最新 {displayName} {item.TypeName}";
        UpdateEventCountLabel();
    }

    private void UpdateEventCountLabel()
    {
        _eventCountLabel.Text = $"记录 {_eventRecords.Count}/{MaxEventRecords}";
        _todayCountLabel.Text = $"今日累计 {_todayEventTotal}";
    }

    private IEnumerable<string> CheckedBlockPaths()
    {
        return _blockList.CheckedItems
            .OfType<BlockListItem>()
            .Select(item => item.Path);
    }

    private void UpdateBlockSelectionSummary()
    {
        var selected = CheckedBlockPaths().ToArray();
        _watchCountLabel.Text = $"板块 {selected.Length} 个";
        if (_settings.StockPoolSource == StockPoolSource.Hotlist)
        {
            _blockSummaryLabel.Text = "当前使用八平台热榜股票池";
        }
        else
        {
            _blockSummaryLabel.Text = selected.Length == 0
                ? "请选择要监控的 .blk 文件"
                : $"已选择 {selected.Length} 个板块文件";
        }
        UpdateRuntimeStatus();
    }

    private void ExportEvents()
    {
        if (_eventRecords.Count == 0)
        {
            Log("没有可导出的异动记录。");
            return;
        }

        using var dialog = new SaveFileDialog
        {
            Filter = "CSV 文件|*.csv|制表符文本|*.txt",
            FileName = $"异动精灵-{DateTime.Now:yyyyMMdd-HHmmss}.csv",
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;

        var useCsv = Path.GetExtension(dialog.FileName).Equals(".csv", StringComparison.OrdinalIgnoreCase);
        var lines = BuildExportLines(_eventRecords, useCsv);
        File.WriteAllLines(dialog.FileName, lines, System.Text.Encoding.UTF8);
        Log($"已导出异动记录: {dialog.FileName}");
    }

    private string SelectedEventCode()
    {
        if (_eventsGrid.SelectedRows.Count == 0) return "";
        return _eventsGrid.SelectedRows[0].Cells["Code"].Value?.ToString() ?? "";
    }

    private void CopySelectedEventCode()
    {
        var code = SelectedEventCode();
        if (string.IsNullOrWhiteSpace(code)) return;

        Clipboard.SetText(code);
        Log($"已复制代码: {code}");
    }

    private void Log(string text)
    {
        if (IsDisposed) return;
        if (InvokeRequired)
        {
            BeginInvoke(new Action(() => Log(text)));
            return;
        }

        var line = $"[{DateTime.Now:HH:mm:ss}] {text}";
        _logBox.AppendText(line + Environment.NewLine);
    }

    private async Task HealthTickAsync()
    {
        if (_healthTicking || _closing || IsDisposed) return;
        _healthTicking = true;
        try
        {
            ResetTodayCounterIfNeeded();
            UpdateRuntimeStatus();
            if (_watchedCodes.Count == 0) return;
            if (_bridgeClient?.IsConnected == true) return;
            if (DateTimeOffset.Now < _nextReconnectAt) return;

            _statusLabel.Text = "行情桥断开，正在自动重连...";
            await EnsureBridgeReadyAsync();
            await ConnectBridgeAsync();
        }
        finally
        {
            _healthTicking = false;
        }
    }

    private void ScheduleReconnect()
    {
        if (_closing || _watchedCodes.Count == 0) return;

        _reconnectAttempt = Math.Min(_reconnectAttempt + 1, 6);
        var delaySeconds = Math.Min(60, Math.Pow(2, _reconnectAttempt));
        _nextReconnectAt = DateTimeOffset.Now.AddSeconds(delaySeconds);
        _statusLabel.Text = $"行情桥断开，{delaySeconds:0} 秒后重连";
    }

    private void UpdateRuntimeStatus()
    {
        if (IsDisposed) return;

        _watchCountLabel.Text = _watchedCodes.Count > 0
            ? $"监控 {_watchedCodes.Count} 只"
            : _watchCountLabel.Text.StartsWith("板块", StringComparison.Ordinal) ? _watchCountLabel.Text : "监控 0 只";
        UpdateEventCountLabel();
        UpdateLastQuoteLabel();
        UpdateSessionLabel();
        UpdateVoiceModeLabel();
    }

    private void UpdateLastQuoteLabel()
    {
        if (_lastQuoteTime is null)
        {
            _lastQuoteLabel.Text = "最近行情 --";
            _lastQuoteLabel.ForeColor = TerminalMuted;
            return;
        }

        var localQuoteTime = _lastQuoteTime.Value.ToLocalTime();
        var delay = DateTimeOffset.Now - localQuoteTime;
        var seconds = Math.Max(0, (int)delay.TotalSeconds);
        _lastQuoteLabel.Text = seconds > 30
            ? $"最近行情 {localQuoteTime:HH:mm:ss} 延迟{seconds}s"
            : $"最近行情 {localQuoteTime:HH:mm:ss}";
        _lastQuoteLabel.ForeColor = seconds > 30 ? WarnAmber : TerminalText;
    }

    private void UpdateSessionLabel()
    {
        var now = DateTimeOffset.Now;
        if (TradingSession.IsContinuousAuction(now))
        {
            _sessionLabel.Text = "交易时段 连续竞价";
            _sessionLabel.ForeColor = UpRed;
        }
        else
        {
            _sessionLabel.Text = "交易时段 休市/集合";
            _sessionLabel.ForeColor = TerminalMuted;
        }
    }

    private void UpdateVoiceModeLabel()
    {
        if (!_settings.VoiceEnabled)
        {
            _voiceModeLabel.Text = "语音 关闭";
            _voiceModeLabel.ForeColor = TerminalMuted;
            return;
        }

        _voiceModeLabel.Text = $"语音 {EventVoicePolicy.DisplayName(_settings.VoiceMode)}";
        _voiceModeLabel.ForeColor = _settings.VoiceMode == VoiceMode.Muted ? TerminalMuted : TerminalText;
    }

    private void ResetTodayCounterIfNeeded()
    {
        var today = DateOnly.FromDateTime(DateTime.Now);
        if (today == _todayEventDate) return;

        _todayEventDate = today;
        _todayEventTotal = 0;
    }

    private void HideToTray()
    {
        if (_closing) return;

        Hide();
        _trayIcon.Visible = true;
        ShowInTaskbar = false;
    }

    private void RestoreFromTray()
    {
        ShowInTaskbar = true;
        Show();
        WindowState = FormWindowState.Normal;
        Activate();
        _trayIcon.Visible = false;
    }

    private void ToggleMute()
    {
        _settings.VoiceMode = _settings.VoiceMode == VoiceMode.Muted ? VoiceMode.StrongOnly : VoiceMode.Muted;
        SaveSettingsFromUi();
        Log(_settings.VoiceMode == VoiceMode.Muted ? "语音已静音。" : "语音已恢复为只播强信号。");
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        _closing = true;
        _healthTimer.Stop();
        _trayIcon.Visible = false;
        SaveSettingsFromUi();
        _bridgeClient?.Disconnect();
        _bridgeClient?.Dispose();
        _blockWatcher?.Dispose();
        _messageNotifier.Dispose();
        _openingSignalReporter.Dispose();
        _speech.Dispose();
        _bridgeManager.StopStartedBridge();
        _proxyManager.StopStartedProxy();
        _trayIcon.Dispose();
        _trayMenu.Dispose();
    }

    private static string FormatMoney(decimal value)
    {
        if (value >= 100_000_000m) return $"{value / 100_000_000m:0.##}亿";
        if (value >= 10_000m) return $"{value / 10_000m:0.##}万";
        return $"{value:0}";
    }

    private static string FormatVolume(decimal value)
    {
        if (value >= 100_000_000m) return $"{value / 100_000_000m:0.##}亿";
        if (value >= 10_000m) return $"{value / 10_000m:0.##}万";
        return $"{value:0}";
    }

    public static IReadOnlyList<string> BuildExportLines(IEnumerable<EventRecord> records, bool csv)
    {
        var separator = csv ? "," : "\t";
        var lines = new List<string>
        {
            string.Join(separator, ExportHeaders.Select(value => EscapeExport(value, csv))),
        };
        lines.AddRange(records.Select(item =>
            string.Join(separator, BuildExportValues(item).Select(value => EscapeExport(value, csv)))));
        return lines;
    }

    private static readonly string[] ExportHeaders =
    [
        "时间",
        "异动类型",
        "股票代码",
        "股票名称",
        "涨跌幅",
        "最新价",
        "成交量",
        "成交额",
        "异动详情",
        "弱转强形态",
        "信号强度",
        "信号分数",
        "09:25价",
        "09:25涨幅",
        "官方开盘价",
        "官方开盘涨幅",
        "09:30价",
        "09:30涨幅",
        "跳空百分点",
        "成交额增量",
        "距涨停百分点",
        "基线质量",
        "竞价采样时间",
        "行情采样时间",
        "竞价采样数",
        "请求数",
        "返回数",
        "采样耗时ms",
        "慢批次",
        "截断批次",
        "风险标记",
    ];

    private static IEnumerable<string> BuildExportValues(EventRecord item)
    {
        var signal = item.OpeningSignal;
        return
        [
            item.Timestamp.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss"),
            item.TypeName,
            item.Code,
            item.DisplayName,
            $"{item.ChangePct:0.##}%",
            $"{item.Price:0.00}",
            FormatVolume(item.Volume),
            FormatMoney(item.Amount),
            item.Reason,
            signal?.Variant ?? "",
            signal?.Confidence ?? "",
            FormatNullable(signal?.Score),
            FormatNullable(signal?.AuctionFinalPrice),
            FormatNullable(signal?.AuctionPct),
            FormatNullable(signal?.OfficialOpen),
            FormatNullable(signal?.OfficialOpenPct),
            FormatNullable(signal?.FirstWindowPrice),
            FormatNullable(signal?.FirstWindowPct),
            FormatNullable(signal?.JumpPctPoint),
            signal is null ? "" : FormatMoney(signal.AmountDelta),
            FormatNullable(signal?.LimitDistancePct),
            signal?.BaselineQuality ?? "",
            FormatExportTime(signal?.AuctionCapturedAt),
            FormatExportTime(signal?.QuoteCapturedAt),
            FormatNullable(signal?.AuctionSampleCount),
            FormatNullable(signal?.RequestedCount),
            FormatNullable(signal?.ReceivedCount),
            FormatNullable(signal?.ElapsedMs),
            FormatNullable(signal?.SlowBatches),
            FormatNullable(signal?.TruncatedBatches),
            signal is null ? "" : string.Join(";", signal.RiskFlags.Select(item => item.Key)),
        ];
    }

    private static string FormatNullable(decimal? value)
    {
        return value.HasValue ? $"{value.Value:0.##}" : "";
    }

    private static string FormatNullable(int? value)
    {
        return value.HasValue ? $"{value.Value}" : "";
    }

    private static string FormatExportTime(DateTimeOffset? value)
    {
        return value.HasValue ? value.Value.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss") : "";
    }

    private static string EscapeExport(string value, bool csv)
    {
        if (!csv) return value.Replace("\t", " ");
        if (!value.Contains(',') && !value.Contains('"') && !value.Contains('\n') && !value.Contains('\r')) return value;
        return $"\"{value.Replace("\"", "\"\"")}\"";
    }

    private static bool IsBridgeDisconnectedStatus(string status)
    {
        return status.Contains("断开", StringComparison.Ordinal) ||
            status.Contains("关闭连接", StringComparison.Ordinal) ||
            status.Contains("连接失败", StringComparison.Ordinal);
    }

    private static bool IsBridgeHeartbeatStatus(string status)
    {
        return status.Contains("心跳正常", StringComparison.Ordinal);
    }

    public static int ResolveBridgePort(string bridgeUrl)
    {
        return Uri.TryCreate(bridgeUrl, UriKind.Absolute, out var uri) && uri.Port > 0
            ? uri.Port
            : 8765;
    }

    public static List<string> ResolveSelectedBlockFilesForSave(
        StockPoolSource source,
        IEnumerable<string> currentSelectedBlockFiles,
        IEnumerable<string> checkedBlockPaths,
        bool canPersistCheckedBlockPaths)
    {
        return source == StockPoolSource.TdxBlock && canPersistCheckedBlockPaths
            ? checkedBlockPaths.ToList()
            : currentSelectedBlockFiles.ToList();
    }

    public static bool IsStStockName(string name)
    {
        var text = name.Trim();
        if (text.Length == 0) return false;
        return text.StartsWith("ST", StringComparison.OrdinalIgnoreCase) ||
            text.StartsWith("*ST", StringComparison.OrdinalIgnoreCase) ||
            text.StartsWith("S*ST", StringComparison.OrdinalIgnoreCase) ||
            text.StartsWith("SST", StringComparison.OrdinalIgnoreCase) ||
            text.Contains("退", StringComparison.Ordinal);
    }

    private static decimal NormalizePositive(decimal value, decimal fallback)
    {
        return value > 0m ? value : fallback;
    }

    private static Color EventTextColor(EventRecord item)
    {
        return item.Type switch
        {
            L1EventType.LimitDownSealed or L1EventType.LimitDownOpened or L1EventType.NearLimitDown or
                L1EventType.UpcomingLimitDownOpen or L1EventType.FastDrop or L1EventType.TurnGreen or L1EventType.IntradayLow or
                L1EventType.AskPressure => DownGreen,
            L1EventType.BidPressure or L1EventType.SpreadWidened => TerminalMuted,
            _ => UpRed,
        };
    }

    private static void DrawFinancialTab(object? sender, DrawItemEventArgs e)
    {
        if (sender is not TabControl tabs || e.Index < 0) return;

        var bounds = tabs.GetTabRect(e.Index);
        var selected = e.Index == tabs.SelectedIndex;
        using var background = new SolidBrush(selected ? TerminalPanelAlt : TerminalPanel);
        using var border = new Pen(selected ? AccentGold : TerminalGrid);
        using var textBrush = new SolidBrush(selected ? Color.White : TerminalMuted);
        using var accentBrush = new SolidBrush(AccentGold);

        e.Graphics.FillRectangle(background, bounds);
        e.Graphics.DrawRectangle(border, bounds.X, bounds.Y, bounds.Width - 1, bounds.Height - 1);
        if (selected)
        {
            e.Graphics.FillRectangle(accentBrush, bounds.X + 1, bounds.Bottom - 3, bounds.Width - 2, 3);
        }

        var textRect = new Rectangle(bounds.X + 8, bounds.Y + 1, bounds.Width - 16, bounds.Height - 6);
        TextRenderer.DrawText(
            e.Graphics,
            tabs.TabPages[e.Index].Text,
            tabs.Font,
            textRect,
            selected ? Color.White : TerminalMuted,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }

    private void ConfigureGrid(DataGridView grid)
    {
        grid.Dock = DockStyle.Fill;
        grid.ReadOnly = true;
        grid.AllowUserToAddRows = false;
        grid.AllowUserToDeleteRows = false;
        grid.AllowUserToResizeRows = false;
        grid.BackgroundColor = TerminalPanel;
        grid.BorderStyle = BorderStyle.None;
        grid.CellBorderStyle = DataGridViewCellBorderStyle.Single;
        grid.GridColor = TerminalGrid;
        grid.ColumnHeadersVisible = true;
        grid.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.EnableResizing;
        grid.ColumnHeadersHeight = 30;
        grid.EnableHeadersVisualStyles = false;
        grid.ColumnHeadersDefaultCellStyle.BackColor = TerminalHeader;
        grid.ColumnHeadersDefaultCellStyle.ForeColor = TerminalText;
        grid.ColumnHeadersDefaultCellStyle.Font = new Font(Font, FontStyle.Bold);
        grid.ColumnHeadersDefaultCellStyle.Alignment = DataGridViewContentAlignment.MiddleLeft;
        grid.DefaultCellStyle.BackColor = TerminalPanel;
        grid.DefaultCellStyle.ForeColor = TerminalText;
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(58, 74, 96);
        grid.DefaultCellStyle.SelectionForeColor = Color.White;
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(15, 21, 29);
        grid.DefaultCellStyle.Font = new Font("Microsoft YaHei UI", 9f);
        grid.RowTemplate.Height = 26;
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        grid.RowHeadersVisible = false;
        grid.MultiSelect = false;
    }

    private static Button PrimaryButton(string text, int width)
    {
        var button = BaseButton(text, width);
        button.BackColor = Color.FromArgb(130, 68, 46);
        button.ForeColor = Color.White;
        button.FlatAppearance.BorderColor = Color.FromArgb(185, 92, 64);
        return button;
    }

    private static Button SecondaryButton(string text, int width)
    {
        var button = BaseButton(text, width);
        button.BackColor = TerminalHeader;
        button.ForeColor = TerminalText;
        button.FlatAppearance.BorderColor = TerminalGrid;
        return button;
    }

    private static Button BaseButton(string text, int width)
    {
        var button = new Button
        {
            Text = text,
            Size = new Size(width, 30),
            FlatStyle = FlatStyle.Flat,
            Cursor = Cursors.Hand,
            Margin = new Padding(0, 0, 8, 0),
        };
        button.FlatAppearance.BorderSize = 1;
        return button;
    }

    private Label SectionLabel(string text)
    {
        return new Label
        {
            Text = text,
            Dock = DockStyle.Fill,
            Font = new Font(Font, FontStyle.Bold),
            ForeColor = TerminalText,
            TextAlign = ContentAlignment.MiddleLeft,
        };
    }

    private static void StyleStatusLabel(Label label)
    {
        label.AutoSize = true;
        label.BackColor = TerminalHeader;
        label.ForeColor = TerminalText;
        label.Padding = new Padding(8, 4, 8, 4);
        label.Margin = new Padding(0, 0, 7, 5);
    }

    private static void ApplyEventRowStyle(DataGridViewRow row, EventRecord item)
    {
        if (item.Type == L1EventType.OpeningWeakToStrong)
        {
            row.DefaultCellStyle.BackColor = Color.FromArgb(58, 31, 24);
            row.DefaultCellStyle.ForeColor = Color.FromArgb(255, 216, 148);
            row.Cells["Type"].Style.BackColor = Color.FromArgb(92, 38, 31);
            row.Cells["Type"].Style.ForeColor = Color.FromArgb(255, 221, 154);
            row.Cells["Reason"].Style.ForeColor = Color.FromArgb(255, 196, 96);
            row.Cells["Change"].Style.ForeColor = UpRed;
            row.Cells["Price"].Style.ForeColor = UpRed;
            return;
        }

        row.DefaultCellStyle.BackColor = item.Severity switch
        {
            L1EventSeverity.Critical => Color.FromArgb(42, 24, 28),
            L1EventSeverity.Important => Color.FromArgb(37, 31, 22),
            _ => row.DefaultCellStyle.BackColor,
        };
        row.DefaultCellStyle.ForeColor = EventTextColor(item);
        row.Cells["Change"].Style.ForeColor = item.ChangePct >= 0 ? UpRed : DownGreen;
        row.Cells["Price"].Style.ForeColor = item.ChangePct >= 0 ? UpRed : DownGreen;
        row.Cells["Type"].Style.ForeColor = EventTextColor(item);
    }

    public static string ResolveTdxRootFromBlockDirectory(string blockDirectory)
    {
        if (string.IsNullOrWhiteSpace(blockDirectory)) return "";

        var dir = new DirectoryInfo(blockDirectory);
        while (dir is not null)
        {
            if (dir.Name.Equals("TDX", StringComparison.OrdinalIgnoreCase) ||
                Directory.Exists(Path.Combine(dir.FullName, "T0002", "hq_cache")))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        return "";
    }

    private sealed record BlockListItem(string Name, string Path)
    {
        public override string ToString() => Name;
    }

    private sealed record StockPoolLoadResult(IReadOnlyList<string> Codes, string Message);

    private sealed record StockPoolSourceOption(StockPoolSource Source, string Label)
    {
        public static StockPoolSourceOption TdxBlock { get; } = new(StockPoolSource.TdxBlock, "TDX自选股");
        public static StockPoolSourceOption Hotlist { get; } = new(StockPoolSource.Hotlist, "八平台热榜");

        public static StockPoolSourceOption FromSource(StockPoolSource source)
        {
            return source == StockPoolSource.Hotlist ? Hotlist : TdxBlock;
        }

        public override string ToString() => Label;
    }
}
