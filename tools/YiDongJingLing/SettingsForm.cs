using YiDongJingLing.Events;
using YiDongJingLing.Settings;
using YiDongJingLing.Speech;

namespace YiDongJingLing;

internal sealed class SettingsForm : Form
{
    private readonly AppSettings _settings;
    private readonly IReadOnlyList<VoiceInfo> _voices;
    private readonly SpeechAnnouncer _speech;
    private readonly CheckedListBox _eventTypeList = new();
    private readonly CheckBox _voiceEnabledBox = new();
    private readonly CheckBox _topMostBox = new();
    private readonly CheckBox _filterStBox = new();
    private readonly TrackBar _volumeBar = new();
    private readonly TrackBar _rateBar = new();
    private readonly TrackBar _opacityBar = new();
    private readonly ComboBox _voiceBox = new();
    private readonly ComboBox _voiceModeBox = new();
    private readonly TextBox _bridgeUrlBox = new();
    private readonly Label _rateValueLabel = new();
    private readonly Label _volumeValueLabel = new();
    private readonly Label _opacityValueLabel = new();

    public SettingsForm(AppSettings settings, IReadOnlyList<VoiceInfo> voices, SpeechAnnouncer speech)
    {
        _settings = settings.Clone();
        _voices = voices;
        _speech = speech;

        Text = "异动精灵设置";
        Width = 760;
        Height = 660;
        MinimumSize = new Size(700, 620);
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 9f);
        BackColor = Color.FromArgb(241, 244, 248);

        BuildUi();
        LoadSettings();
    }

    public AppSettings Settings => _settings;

    private void BuildUi()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            Padding = new Padding(14),
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 300));
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        Controls.Add(root);

        var left = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 3,
            BackColor = BackColor,
            Padding = new Padding(0, 0, 12, 0),
        };
        left.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        left.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        left.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        root.Controls.Add(left, 0, 0);

        var typeLabel = SectionLabel("异动类型");
        left.Controls.Add(typeLabel, 0, 0);
        _eventTypeList.Dock = DockStyle.Fill;
        _eventTypeList.CheckOnClick = true;
        _eventTypeList.BorderStyle = BorderStyle.FixedSingle;
        _eventTypeList.BackColor = Color.White;
        foreach (var item in EventTypeOptions())
        {
            _eventTypeList.Items.Add(item, true);
        }
        left.Controls.Add(_eventTypeList, 0, 1);

        var typeButtons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Padding = new Padding(0, 8, 0, 0),
        };
        var allBtn = SecondaryButton("全选", 72);
        allBtn.Click += (_, _) => SetAllEventTypes(true);
        var noneBtn = SecondaryButton("清空", 72);
        noneBtn.Click += (_, _) => SetAllEventTypes(false);
        var invertBtn = SecondaryButton("反选", 72);
        invertBtn.Click += (_, _) => InvertEventTypes();
        typeButtons.Controls.AddRange([allBtn, noneBtn, invertBtn]);
        left.Controls.Add(typeButtons, 0, 2);

        var right = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            RowCount = 4,
            BackColor = BackColor,
        };
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 236));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 162));
        right.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.Controls.Add(right, 1, 0);

        var heading = new Label
        {
            Text = "设置",
            Dock = DockStyle.Fill,
            Font = new Font("Microsoft YaHei UI", 16f, FontStyle.Bold),
            ForeColor = Color.FromArgb(15, 23, 42),
            TextAlign = ContentAlignment.MiddleLeft,
        };
        right.Controls.Add(heading, 0, 0);

        var voiceGroup = SectionBox("语音播报");
        var voiceLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            RowCount = 5,
            Padding = new Padding(14, 18, 14, 10),
        };
        voiceLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 74));
        voiceLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        voiceLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 72));
        voiceLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 72));
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        voiceGroup.Controls.Add(voiceLayout);
        _voiceEnabledBox.Text = "VoiceWorker 本地语音";
        _voiceEnabledBox.Dock = DockStyle.Fill;
        _voiceEnabledBox.AutoSize = true;
        voiceLayout.Controls.Add(_voiceEnabledBox, 0, 0);
        voiceLayout.SetColumnSpan(_voiceEnabledBox, 4);

        voiceLayout.Controls.Add(FieldLabel("模式"), 0, 1);
        _voiceModeBox.Dock = DockStyle.Fill;
        _voiceModeBox.DropDownStyle = ComboBoxStyle.DropDownList;
        _voiceModeBox.Margin = new Padding(0, 3, 8, 0);
        _voiceModeBox.Items.AddRange([
            VoiceModeOption.StrongOnly,
            VoiceModeOption.All,
            VoiceModeOption.Muted,
        ]);
        voiceLayout.Controls.Add(_voiceModeBox, 1, 1);
        voiceLayout.SetColumnSpan(_voiceModeBox, 3);

        voiceLayout.Controls.Add(FieldLabel("音色"), 0, 2);
        _voiceBox.Dock = DockStyle.Fill;
        _voiceBox.DropDownStyle = ComboBoxStyle.DropDownList;
        _voiceBox.Margin = new Padding(0, 3, 8, 0);
        voiceLayout.Controls.Add(_voiceBox, 1, 2);
        var testVoiceBtn = PrimaryButton("测试", 62);
        testVoiceBtn.Click += async (_, _) =>
        {
            await _speech.TestAsync(
                _voiceEnabledBox.Checked,
                _rateBar.Value / 10d,
                _volumeBar.Value,
                _voiceBox.SelectedItem?.ToString() ?? "");
        };
        voiceLayout.Controls.Add(testVoiceBtn, 2, 2);
        var stopVoiceBtn = SecondaryButton("停止", 62);
        stopVoiceBtn.Click += async (_, _) => await _speech.StopAsync();
        voiceLayout.Controls.Add(stopVoiceBtn, 3, 2);

        voiceLayout.Controls.Add(FieldLabel("语速"), 0, 3);
        _rateBar.Minimum = 6;
        _rateBar.Maximum = 18;
        _rateBar.TickFrequency = 2;
        _rateBar.Dock = DockStyle.Fill;
        _rateBar.ValueChanged += (_, _) => UpdateValueLabels();
        voiceLayout.Controls.Add(_rateBar, 1, 3);
        voiceLayout.SetColumnSpan(_rateBar, 2);
        voiceLayout.Controls.Add(ValueLabel(_rateValueLabel), 3, 3);

        voiceLayout.Controls.Add(FieldLabel("音量"), 0, 4);
        _volumeBar.Minimum = 0;
        _volumeBar.Maximum = 100;
        _volumeBar.TickFrequency = 10;
        _volumeBar.Dock = DockStyle.Fill;
        _volumeBar.ValueChanged += (_, _) => UpdateValueLabels();
        voiceLayout.Controls.Add(_volumeBar, 1, 4);
        voiceLayout.SetColumnSpan(_volumeBar, 2);
        voiceLayout.Controls.Add(ValueLabel(_volumeValueLabel), 3, 4);
        right.Controls.Add(voiceGroup, 0, 1);

        var appGroup = SectionBox("窗口、过滤与行情桥");
        var appLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 4,
            Padding = new Padding(14, 18, 14, 10),
        };
        appLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 74));
        appLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        appLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 72));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        appGroup.Controls.Add(appLayout);

        appLayout.Controls.Add(FieldLabel("透明度"), 0, 0);
        _opacityBar.Minimum = 60;
        _opacityBar.Maximum = 100;
        _opacityBar.TickFrequency = 5;
        _opacityBar.Dock = DockStyle.Fill;
        _opacityBar.ValueChanged += (_, _) => UpdateValueLabels();
        appLayout.Controls.Add(_opacityBar, 1, 0);
        appLayout.Controls.Add(ValueLabel(_opacityValueLabel), 2, 0);

        _topMostBox.Text = "窗口置顶";
        _topMostBox.Dock = DockStyle.Fill;
        _topMostBox.AutoSize = true;
        appLayout.Controls.Add(_topMostBox, 1, 1);
        appLayout.SetColumnSpan(_topMostBox, 2);

        _filterStBox.Text = "过滤 ST 股";
        _filterStBox.Dock = DockStyle.Fill;
        _filterStBox.AutoSize = true;
        appLayout.Controls.Add(_filterStBox, 1, 2);
        appLayout.SetColumnSpan(_filterStBox, 2);

        appLayout.Controls.Add(FieldLabel("行情桥"), 0, 3);
        _bridgeUrlBox.Dock = DockStyle.Fill;
        _bridgeUrlBox.Margin = new Padding(0, 5, 0, 0);
        appLayout.Controls.Add(_bridgeUrlBox, 1, 3);
        appLayout.SetColumnSpan(_bridgeUrlBox, 2);
        right.Controls.Add(appGroup, 0, 2);

        var footer = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            Height = 48,
            FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false,
            Padding = new Padding(0, 14, 0, 0),
        };
        var okBtn = PrimaryButton("保存", 92);
        okBtn.DialogResult = DialogResult.OK;
        okBtn.Click += (_, _) => SaveSettings();
        footer.Controls.Add(okBtn);
        AcceptButton = okBtn;

        var cancelBtn = SecondaryButton("取消", 92);
        cancelBtn.DialogResult = DialogResult.Cancel;
        footer.Controls.Add(cancelBtn);
        CancelButton = cancelBtn;
        right.Controls.Add(footer, 0, 3);
    }

    private void LoadSettings()
    {
        _voiceEnabledBox.Checked = _settings.VoiceEnabled;
        _rateBar.Value = Math.Clamp((int)Math.Round(_settings.VoiceRate * 10), 6, 18);
        _volumeBar.Value = Math.Clamp(_settings.VoiceVolume, 0, 100);
        _opacityBar.Value = Math.Clamp((int)Math.Round(_settings.Opacity * 100), 60, 100);
        _topMostBox.Checked = _settings.TopMost;
        _filterStBox.Checked = _settings.FilterStStocks;
        _bridgeUrlBox.Text = _settings.BridgeUrl;

        _voiceBox.Items.Clear();
        _voiceBox.Items.Add("");
        foreach (var voice in _voices)
        {
            _voiceBox.Items.Add(voice.Name);
        }
        _voiceBox.SelectedItem = _voiceBox.Items.Contains(_settings.VoiceName) ? _settings.VoiceName : "";
        _voiceModeBox.SelectedItem = VoiceModeOption.FromMode(_settings.VoiceMode);

        for (var i = 0; i < _eventTypeList.Items.Count; i++)
        {
            if (_eventTypeList.Items[i] is EventTypeOption option)
            {
                _eventTypeList.SetItemChecked(i, _settings.IsEventEnabled(option.Type.ToString()));
            }
        }

        UpdateValueLabels();
    }

    private void SaveSettings()
    {
        _settings.BridgeUrl = _bridgeUrlBox.Text.Trim();
        _settings.VoiceEnabled = _voiceEnabledBox.Checked;
        _settings.VoiceRate = _rateBar.Value / 10d;
        _settings.VoiceVolume = _volumeBar.Value;
        _settings.VoiceName = _voiceBox.SelectedItem?.ToString() ?? "";
        _settings.VoiceMode = _voiceModeBox.SelectedItem is VoiceModeOption selectedVoiceMode
            ? selectedVoiceMode.Mode
            : VoiceMode.StrongOnly;
        _settings.Opacity = _opacityBar.Value / 100d;
        _settings.TopMost = _topMostBox.Checked;
        _settings.FilterStStocks = _filterStBox.Checked;
        _settings.EnabledEvents.Clear();
        for (var i = 0; i < _eventTypeList.Items.Count; i++)
        {
            if (_eventTypeList.Items[i] is EventTypeOption option)
            {
                _settings.EnabledEvents[option.Type.ToString()] = _eventTypeList.GetItemChecked(i);
            }
        }
    }

    private void SetAllEventTypes(bool enabled)
    {
        for (var i = 0; i < _eventTypeList.Items.Count; i++)
        {
            _eventTypeList.SetItemChecked(i, enabled);
        }
    }

    private void InvertEventTypes()
    {
        for (var i = 0; i < _eventTypeList.Items.Count; i++)
        {
            _eventTypeList.SetItemChecked(i, !_eventTypeList.GetItemChecked(i));
        }
    }

    private void UpdateValueLabels()
    {
        _rateValueLabel.Text = $"{_rateBar.Value / 10d:0.0}x";
        _volumeValueLabel.Text = $"{_volumeBar.Value}%";
        _opacityValueLabel.Text = $"{_opacityBar.Value}%";
    }

    private Label SectionLabel(string text)
    {
        return new Label
        {
            Text = text,
            Dock = DockStyle.Fill,
            Font = new Font(Font, FontStyle.Bold),
            ForeColor = Color.FromArgb(15, 23, 42),
            TextAlign = ContentAlignment.MiddleLeft,
        };
    }

    private static Label FieldLabel(string text)
    {
        return new Label
        {
            Text = text,
            Dock = DockStyle.Fill,
            ForeColor = Color.FromArgb(51, 65, 85),
            TextAlign = ContentAlignment.MiddleLeft,
        };
    }

    private static Label ValueLabel(Label label)
    {
        label.Dock = DockStyle.Fill;
        label.ForeColor = Color.FromArgb(71, 85, 105);
        label.TextAlign = ContentAlignment.MiddleRight;
        return label;
    }

    private static GroupBox SectionBox(string text)
    {
        return new GroupBox
        {
            Text = text,
            Dock = DockStyle.Fill,
            BackColor = Color.White,
            ForeColor = Color.FromArgb(15, 23, 42),
            Padding = new Padding(8),
            Margin = new Padding(0, 0, 0, 12),
        };
    }

    private static Button PrimaryButton(string text, int width)
    {
        var button = BaseButton(text, width);
        button.BackColor = Color.FromArgb(29, 78, 216);
        button.ForeColor = Color.White;
        button.FlatAppearance.BorderColor = Color.FromArgb(29, 78, 216);
        return button;
    }

    private static Button SecondaryButton(string text, int width)
    {
        var button = BaseButton(text, width);
        button.BackColor = Color.White;
        button.ForeColor = Color.FromArgb(30, 41, 59);
        button.FlatAppearance.BorderColor = Color.FromArgb(203, 213, 225);
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

    private static IReadOnlyList<EventTypeOption> EventTypeOptions()
    {
        return
        [
            new EventTypeOption(L1EventType.LimitUpSealed, "封涨停板"),
            new EventTypeOption(L1EventType.LimitUpOpened, "打开涨停板"),
            new EventTypeOption(L1EventType.UpcomingLimitUpOpen, "即将打开涨停"),
            new EventTypeOption(L1EventType.NearLimitUp, "逼近涨停"),
            new EventTypeOption(L1EventType.LimitDownSealed, "封跌停板"),
            new EventTypeOption(L1EventType.LimitDownOpened, "打开跌停板"),
            new EventTypeOption(L1EventType.UpcomingLimitDownOpen, "即将打开跌停"),
            new EventTypeOption(L1EventType.NearLimitDown, "逼近跌停"),
            new EventTypeOption(L1EventType.SealOrderIncreased, "封单增强"),
            new EventTypeOption(L1EventType.SealOrderWeakened, "封单变弱"),
            new EventTypeOption(L1EventType.BigRiseTier, "大幅拉升"),
            new EventTypeOption(L1EventType.FastRise, "快速拉升"),
            new EventTypeOption(L1EventType.FastDrop, "快速跳水"),
            new EventTypeOption(L1EventType.TurnRed, "翻红"),
            new EventTypeOption(L1EventType.TurnGreen, "翻绿"),
            new EventTypeOption(L1EventType.IntradayHigh, "创日内新高"),
            new EventTypeOption(L1EventType.IntradayLow, "创日内新低"),
            new EventTypeOption(L1EventType.AmountTier, "成交额跨档"),
            new EventTypeOption(L1EventType.VolumeAcceleration, "成交增量加速"),
            new EventTypeOption(L1EventType.BidPressure, "盘口买压增强"),
            new EventTypeOption(L1EventType.AskPressure, "盘口卖压增强"),
            new EventTypeOption(L1EventType.SpreadWidened, "买卖价差异常"),
        ];
    }

    private sealed record EventTypeOption(L1EventType Type, string Label)
    {
        public override string ToString() => Label;
    }

    private sealed record VoiceModeOption(VoiceMode Mode, string Label)
    {
        public static VoiceModeOption StrongOnly { get; } = new(VoiceMode.StrongOnly, "只播强信号");
        public static VoiceModeOption All { get; } = new(VoiceMode.All, "播报全部");
        public static VoiceModeOption Muted { get; } = new(VoiceMode.Muted, "静音");

        public static VoiceModeOption FromMode(VoiceMode mode)
        {
            return mode switch
            {
                VoiceMode.All => All,
                VoiceMode.Muted => Muted,
                _ => StrongOnly,
            };
        }

        public override string ToString() => Label;
    }
}
