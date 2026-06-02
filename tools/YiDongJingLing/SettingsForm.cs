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
    private readonly CheckBox _filterStBox = new();
    private readonly CheckBox _syncMessageBox = new();
    private readonly TrackBar _volumeBar = new();
    private readonly TrackBar _rateBar = new();
    private readonly TrackBar _opacityBar = new();
    private readonly ComboBox _voiceBox = new();
    private readonly ComboBox _voiceModeBox = new();
    private readonly ComboBox _stockPoolSourceBox = new();
    private readonly TextBox _bridgeUrlBox = new();
    private readonly NumericUpDown _riseBreakthroughBox = new();
    private readonly NumericUpDown _dropBreakthroughBox = new();
    private readonly NumericUpDown _fiveMinuteMoveBox = new();
    private readonly NumericUpDown _largeAmountBox = new();
    private readonly NumericUpDown _largeOrderBox = new();
    private readonly NumericUpDown _openGapBox = new();
    private readonly NumericUpDown _longBodyBox = new();
    private readonly NumericUpDown _hotlistTopVoiceBox = new();
    private readonly Label _hotlistTopVoiceLabel = new();
    private readonly Label _hotlistTopVoiceHint = new();
    private readonly Label _rateValueLabel = new();
    private readonly Label _volumeValueLabel = new();
    private readonly Label _opacityValueLabel = new();

    public SettingsForm(AppSettings settings, IReadOnlyList<VoiceInfo> voices, SpeechAnnouncer speech)
    {
        _settings = settings.Clone();
        _voices = voices;
        _speech = speech;

        Text = "异动精灵设置";
        Width = 860;
        Height = 860;
        MinimumSize = new Size(820, 800);
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
            RowCount = 5,
            BackColor = BackColor,
        };
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 286));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 226));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 170));
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
            RowCount = 6,
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
        voiceLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
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

        _hotlistTopVoiceLabel.Text = "热榜前N名播报";
        _hotlistTopVoiceLabel.Dock = DockStyle.Fill;
        _hotlistTopVoiceLabel.Font = Font;
        _hotlistTopVoiceLabel.TextAlign = ContentAlignment.MiddleLeft;
        voiceLayout.Controls.Add(_hotlistTopVoiceLabel, 0, 5);
        _hotlistTopVoiceBox.Dock = DockStyle.Fill;
        _hotlistTopVoiceBox.Minimum = 0;
        _hotlistTopVoiceBox.Maximum = 500;
        _hotlistTopVoiceBox.Increment = 1;
        _hotlistTopVoiceBox.Margin = new Padding(0, 3, 8, 0);
        _hotlistTopVoiceBox.TextAlign = HorizontalAlignment.Right;
        voiceLayout.Controls.Add(_hotlistTopVoiceBox, 1, 5);
        voiceLayout.SetColumnSpan(_hotlistTopVoiceBox, 2);
        _hotlistTopVoiceHint.Text = "0=不限；仅过滤语音，不过滤异动列表";
        _hotlistTopVoiceHint.Dock = DockStyle.Fill;
        _hotlistTopVoiceHint.ForeColor = Color.FromArgb(100, 116, 139);
        _hotlistTopVoiceHint.TextAlign = ContentAlignment.MiddleLeft;
        voiceLayout.Controls.Add(_hotlistTopVoiceHint, 3, 5);

        right.Controls.Add(voiceGroup, 0, 1);

        var appGroup = SectionBox("股票池、窗口与行情桥");
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
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        appLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        appGroup.Controls.Add(appLayout);

        appLayout.Controls.Add(FieldLabel("股票池"), 0, 0);
        _stockPoolSourceBox.Dock = DockStyle.Fill;
        _stockPoolSourceBox.DropDownStyle = ComboBoxStyle.DropDownList;
        _stockPoolSourceBox.Margin = new Padding(0, 3, 8, 0);
        _stockPoolSourceBox.Items.AddRange([StockPoolSourceOption.TdxBlock, StockPoolSourceOption.Hotlist]);
        _stockPoolSourceBox.SelectedIndexChanged += (_, _) => UpdateHotlistVoiceRowVisibility();
        appLayout.Controls.Add(_stockPoolSourceBox, 1, 0);
        appLayout.SetColumnSpan(_stockPoolSourceBox, 2);

        appLayout.Controls.Add(FieldLabel("透明度"), 0, 1);
        _opacityBar.Minimum = 60;
        _opacityBar.Maximum = 100;
        _opacityBar.TickFrequency = 5;
        _opacityBar.Dock = DockStyle.Fill;
        _opacityBar.ValueChanged += (_, _) => UpdateValueLabels();
        appLayout.Controls.Add(_opacityBar, 1, 1);
        appLayout.Controls.Add(ValueLabel(_opacityValueLabel), 2, 1);

        var optionFlow = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Padding = new Padding(0, 4, 0, 0),
        };
        _filterStBox.Text = "过滤 ST 股";
        _filterStBox.AutoSize = true;
        _filterStBox.Margin = new Padding(0, 0, 28, 0);
        optionFlow.Controls.Add(_filterStBox);
        _syncMessageBox.Text = "同步消息";
        _syncMessageBox.AutoSize = true;
        _syncMessageBox.ForeColor = Color.FromArgb(220, 38, 38);
        optionFlow.Controls.Add(_syncMessageBox);
        appLayout.Controls.Add(optionFlow, 1, 2);
        appLayout.SetColumnSpan(optionFlow, 2);

        appLayout.Controls.Add(FieldLabel("行情桥"), 0, 3);
        _bridgeUrlBox.Dock = DockStyle.Fill;
        _bridgeUrlBox.Margin = new Padding(0, 5, 0, 0);
        appLayout.Controls.Add(_bridgeUrlBox, 1, 3);
        appLayout.SetColumnSpan(_bridgeUrlBox, 2);
        right.Controls.Add(appGroup, 0, 2);

        var ruleGroup = SectionBox("异动参数");
        var ruleLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 4,
            RowCount = 4,
            Padding = new Padding(14, 18, 14, 10),
        };
        ruleLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 118));
        ruleLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        ruleLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 118));
        ruleLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (var i = 0; i < 4; i++)
        {
            ruleLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        }
        ruleGroup.Controls.Add(ruleLayout);
        AddDecimalField(ruleLayout, "涨幅突破 %", _riseBreakthroughBox, 0, 0, 1, 30, 7);
        AddDecimalField(ruleLayout, "跌幅突破 %", _dropBreakthroughBox, 2, 0, 1, 30, 7);
        AddDecimalField(ruleLayout, "5分钟涨跌 %", _fiveMinuteMoveBox, 0, 1, 1, 30, 5);
        AddDecimalField(ruleLayout, "成交额 万", _largeAmountBox, 2, 1, 100, 1_000_000, 10_000);
        AddDecimalField(ruleLayout, "挂单额 万", _largeOrderBox, 0, 2, 100, 1_000_000, 1_000);
        AddDecimalField(ruleLayout, "开盘跳空 %", _openGapBox, 2, 2, 0.1m, 20, 1);
        AddDecimalField(ruleLayout, "长阳长阴 %", _longBodyBox, 0, 3, 0.1m, 30, 4);
        right.Controls.Add(ruleGroup, 0, 3);

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
        right.Controls.Add(footer, 0, 4);
    }

    private void LoadSettings()
    {
        _voiceEnabledBox.Checked = _settings.VoiceEnabled;
        _rateBar.Value = Math.Clamp((int)Math.Round(_settings.VoiceRate * 10), 6, 18);
        _volumeBar.Value = Math.Clamp(_settings.VoiceVolume, 0, 100);
        _opacityBar.Value = Math.Clamp((int)Math.Round(_settings.Opacity * 100), 60, 100);
        _stockPoolSourceBox.SelectedItem = StockPoolSourceOption.FromSource(_settings.StockPoolSource);
        _filterStBox.Checked = _settings.FilterStStocks;
        _syncMessageBox.Checked = _settings.SyncMessages;
        _bridgeUrlBox.Text = _settings.BridgeUrl;
        _riseBreakthroughBox.Value = ClampDecimal(_settings.RiseBreakthroughPct, _riseBreakthroughBox);
        _dropBreakthroughBox.Value = ClampDecimal(_settings.DropBreakthroughPct, _dropBreakthroughBox);
        _fiveMinuteMoveBox.Value = ClampDecimal(_settings.FiveMinuteMovePct, _fiveMinuteMoveBox);
        _largeAmountBox.Value = ClampDecimal(_settings.LargeAmountThresholdWan, _largeAmountBox);
        _largeOrderBox.Value = ClampDecimal(_settings.LargeOrderThresholdWan, _largeOrderBox);
        _openGapBox.Value = ClampDecimal(_settings.OpenGapPct, _openGapBox);
        _longBodyBox.Value = ClampDecimal(_settings.LongBodyPct, _longBodyBox);
        _hotlistTopVoiceBox.Value = Math.Clamp(_settings.HotlistTopVoiceCount, 0, 500);
        UpdateHotlistVoiceRowVisibility();

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
        _settings.StockPoolSource = _stockPoolSourceBox.SelectedItem is StockPoolSourceOption selectedPool
            ? selectedPool.Source
            : StockPoolSource.TdxBlock;
        _settings.Opacity = _opacityBar.Value / 100d;
        _settings.TopMost = false;
        _settings.FilterStStocks = _filterStBox.Checked;
        _settings.SyncMessages = _syncMessageBox.Checked;
        _settings.RiseBreakthroughPct = _riseBreakthroughBox.Value;
        _settings.DropBreakthroughPct = _dropBreakthroughBox.Value;
        _settings.FiveMinuteMovePct = _fiveMinuteMoveBox.Value;
        _settings.LargeAmountThresholdWan = _largeAmountBox.Value;
        _settings.LargeOrderThresholdWan = _largeOrderBox.Value;
        _settings.OpenGapPct = _openGapBox.Value;
        _settings.LongBodyPct = _longBodyBox.Value;
        _settings.HotlistTopVoiceCount = (int)_hotlistTopVoiceBox.Value;
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

    private void UpdateHotlistVoiceRowVisibility()
    {
        var isHotlist = _stockPoolSourceBox.SelectedItem is StockPoolSourceOption { Source: StockPoolSource.Hotlist };
        _hotlistTopVoiceLabel.Visible = isHotlist;
        _hotlistTopVoiceBox.Visible = isHotlist;
        _hotlistTopVoiceHint.Visible = isHotlist;
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

    private static void AddDecimalField(
        TableLayoutPanel layout,
        string label,
        NumericUpDown input,
        int column,
        int row,
        decimal increment,
        decimal maximum,
        decimal value)
    {
        layout.Controls.Add(FieldLabel(label), column, row);
        input.Dock = DockStyle.Fill;
        input.DecimalPlaces = increment < 1m ? 1 : 0;
        input.Increment = increment;
        input.Minimum = 0;
        input.Maximum = maximum;
        input.Value = Math.Clamp(value, input.Minimum, input.Maximum);
        input.Margin = new Padding(0, 2, 8, 0);
        input.TextAlign = HorizontalAlignment.Right;
        layout.Controls.Add(input, column + 1, row);
    }

    private static decimal ClampDecimal(decimal value, NumericUpDown input)
    {
        return Math.Clamp(value, input.Minimum, input.Maximum);
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
            new EventTypeOption(L1EventType.LimitUpSealed, "封涨停板", "涨停价+买一封单"),
            new EventTypeOption(L1EventType.LimitUpOpened, "打开涨停板", "跌离涨停封单"),
            new EventTypeOption(L1EventType.UpcomingLimitUpOpen, "即将打开涨停", "买一封单骤降"),
            new EventTypeOption(L1EventType.NearLimitUp, "逼近涨停", "距涨停1%内"),
            new EventTypeOption(L1EventType.LimitDownSealed, "封跌停板", "跌停价+卖一封单"),
            new EventTypeOption(L1EventType.LimitDownOpened, "打开跌停板", "脱离跌停封单"),
            new EventTypeOption(L1EventType.UpcomingLimitDownOpen, "即将打开跌停", "卖一封单骤降"),
            new EventTypeOption(L1EventType.NearLimitDown, "逼近跌停", "距跌停1%内"),
            new EventTypeOption(L1EventType.SealOrderIncreased, "封单增强", "封单较前帧增50%"),
            new EventTypeOption(L1EventType.SealOrderWeakened, "封单变弱", "封单较前帧减半"),
            new EventTypeOption(L1EventType.BigRiseTier, "大幅拉升", "当日涨幅破阈值"),
            new EventTypeOption(L1EventType.BigDropTier, "大幅跳水", "当日跌幅破阈值"),
            new EventTypeOption(L1EventType.FastRise, "快速拉升", "30/60秒或5分钟急涨"),
            new EventTypeOption(L1EventType.FastDrop, "快速跳水", "30/60秒或5分钟急跌"),
            new EventTypeOption(L1EventType.OpeningWeakToStrong, "竞价弱转强", "09:25弱到09:30转强"),
            new EventTypeOption(L1EventType.LowOpenLongYang, "低开长阳", "低开后大幅拉起"),
            new EventTypeOption(L1EventType.HighOpenLongYin, "高开长阴", "高开后大幅回落"),
            new EventTypeOption(L1EventType.TurnRed, "翻红", "涨跌幅由负转正"),
            new EventTypeOption(L1EventType.TurnGreen, "翻绿", "涨跌幅由正转负"),
            new EventTypeOption(L1EventType.IntradayHigh, "创日内新高", "刷新启动后高点"),
            new EventTypeOption(L1EventType.IntradayLow, "创日内新低", "刷新启动后低点"),
            new EventTypeOption(L1EventType.AmountTier, "成交额跨档", "累计成交额破门槛"),
            new EventTypeOption(L1EventType.VolumeAcceleration, "成交增量加速", "近30秒成交量放大"),
            new EventTypeOption(L1EventType.LargeBidOrder, "出现大买挂盘", "买一挂单额过大"),
            new EventTypeOption(L1EventType.LargeAskOrder, "出现大卖挂盘", "卖一挂单额过大"),
            new EventTypeOption(L1EventType.BidPressure, "盘口买压增强", "五档买量压卖量"),
            new EventTypeOption(L1EventType.AskPressure, "盘口卖压增强", "五档卖量压买量"),
            new EventTypeOption(L1EventType.SpreadWidened, "买卖价差异常", "买卖一价差过大"),
        ];
    }

    private sealed record EventTypeOption(L1EventType Type, string Label, string Note)
    {
        public override string ToString() => $"{Label} - {Note}";
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
