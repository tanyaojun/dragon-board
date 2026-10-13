using System.Text.Json;

namespace YiDongJingLing.Settings;

public enum VoiceMode
{
    StrongOnly,
    All,
    Muted,
}

public enum StockPoolSource
{
    TdxBlock,
    Hotlist,
}

public sealed class AppSettings
{
    public string BlockDirectory { get; set; } = @"D:\APP_SOFT\TDX\T0002\blocknew";
    public List<string> SelectedBlockFiles { get; set; } = [];
    public string BridgeUrl { get; set; } = "ws://127.0.0.1:8765/ws/quotes";
    public StockPoolSource StockPoolSource { get; set; } = StockPoolSource.TdxBlock;
    public bool TopMost { get; set; }
    public bool FilterStStocks { get; set; }
    public bool SyncMessages { get; set; }
    public decimal RiseBreakthroughPct { get; set; } = 7m;
    public decimal DropBreakthroughPct { get; set; } = 7m;
    public decimal FiveMinuteMovePct { get; set; } = 5m;
    public decimal LargeAmountThresholdWan { get; set; } = 10_000m;
    public decimal LargeOrderThresholdWan { get; set; } = 1_000m;
    public decimal OpenGapPct { get; set; } = 1m;
    public decimal LongBodyPct { get; set; } = 4m;
    public int CheckpointWindowThresholdSeconds { get; set; } = 30;
    public decimal OpeningSupportImproveMinPctPoint { get; set; } = 1.2m;
    public decimal AuctionPriceLiftMinPctPoint { get; set; } = 0.8m;
    public decimal AuctionAmountLiftMinRatio { get; set; } = 0.35m;
    public decimal AuctionLatePriceLiftMinPctPoint { get; set; } = 0.3m;
    public decimal AuctionLateAmountLiftMinRatio { get; set; } = 0.2m;
    public decimal OpeningSupportAmountMinRatio { get; set; } = 1m;
    public bool VoiceEnabled { get; set; } = true;
    public double VoiceRate { get; set; } = 1;
    public int VoiceVolume { get; set; } = 100;
    public string VoiceName { get; set; } = "";
    public VoiceMode VoiceMode { get; set; } = VoiceMode.All;
    public int StateChangeCooldownSeconds { get; set; } = 30;
    public int NoiseCooldownSeconds { get; set; } = 180;
    public int HotlistTopVoiceCount { get; set; }
    public double Opacity { get; set; } = 1;
    public Dictionary<string, bool> EnabledEvents { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    /// <summary>语音层白名单：键存在以键为准（只影响语音，表格/飞书不受影响）；
    /// 空集合 = 未固化勾选，沿用历史行为（All 全播 / StrongOnly 默认强信号集）。</summary>
    public Dictionary<string, bool> VoiceEvents { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public bool SectorEventsEnabled { get; set; } = true;
    public bool ConceptMapEnabled { get; set; } = true;
    public int ConceptMapRefreshMinutes { get; set; } = 30;
    public int SectorMinMoveCount { get; set; } = 3;
    public decimal SectorMoveRatio { get; set; } = 0.6m;
    public decimal SectorMoveMinAvgPct { get; set; } = 1.0m;
    public int SectorWaveThreshold { get; set; } = 2;
    public int SectorWaveWindowSeconds { get; set; } = 600;
    public int SectorCooldownSeconds { get; set; } = 600;

    public bool IsEventEnabled(string eventName)
    {
        return !EnabledEvents.TryGetValue(eventName, out var enabled) || enabled;
    }

    public bool IsVoiceEventEnabled(string eventName)
    {
        return !VoiceEvents.TryGetValue(eventName, out var enabled) || enabled;
    }

    public AppSettings Clone()
    {
        return new AppSettings
        {
            BlockDirectory = BlockDirectory,
            SelectedBlockFiles = SelectedBlockFiles.ToList(),
            BridgeUrl = BridgeUrl,
            StockPoolSource = StockPoolSource,
            TopMost = TopMost,
            FilterStStocks = FilterStStocks,
            SyncMessages = SyncMessages,
            RiseBreakthroughPct = RiseBreakthroughPct,
            DropBreakthroughPct = DropBreakthroughPct,
            FiveMinuteMovePct = FiveMinuteMovePct,
            LargeAmountThresholdWan = LargeAmountThresholdWan,
            LargeOrderThresholdWan = LargeOrderThresholdWan,
            OpenGapPct = OpenGapPct,
            LongBodyPct = LongBodyPct,
            CheckpointWindowThresholdSeconds = CheckpointWindowThresholdSeconds,
            OpeningSupportImproveMinPctPoint = OpeningSupportImproveMinPctPoint,
            AuctionPriceLiftMinPctPoint = AuctionPriceLiftMinPctPoint,
            AuctionAmountLiftMinRatio = AuctionAmountLiftMinRatio,
            AuctionLatePriceLiftMinPctPoint = AuctionLatePriceLiftMinPctPoint,
            AuctionLateAmountLiftMinRatio = AuctionLateAmountLiftMinRatio,
            OpeningSupportAmountMinRatio = OpeningSupportAmountMinRatio,
            VoiceEnabled = VoiceEnabled,
            VoiceRate = VoiceRate,
            VoiceVolume = VoiceVolume,
            VoiceName = VoiceName,
            VoiceMode = VoiceMode,
            StateChangeCooldownSeconds = StateChangeCooldownSeconds,
            NoiseCooldownSeconds = NoiseCooldownSeconds,
            HotlistTopVoiceCount = HotlistTopVoiceCount,
            Opacity = Opacity,
            EnabledEvents = new Dictionary<string, bool>(EnabledEvents, StringComparer.OrdinalIgnoreCase),
            VoiceEvents = new Dictionary<string, bool>(VoiceEvents, StringComparer.OrdinalIgnoreCase),
            SectorEventsEnabled = SectorEventsEnabled,
            ConceptMapEnabled = ConceptMapEnabled,
            ConceptMapRefreshMinutes = ConceptMapRefreshMinutes,
            SectorMinMoveCount = SectorMinMoveCount,
            SectorMoveRatio = SectorMoveRatio,
            SectorMoveMinAvgPct = SectorMoveMinAvgPct,
            SectorWaveThreshold = SectorWaveThreshold,
            SectorWaveWindowSeconds = SectorWaveWindowSeconds,
            SectorCooldownSeconds = SectorCooldownSeconds,
        };
    }
}

public sealed class SettingsStore
{
    private readonly string _path;

    public SettingsStore()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "DragonBoard",
            "YiDongJingLing");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "settings.json");
    }

    public AppSettings Load()
    {
        if (!File.Exists(_path)) return new AppSettings();

        try
        {
            return JsonSerializer.Deserialize<AppSettings>(
                File.ReadAllText(_path),
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? new AppSettings();
        }
        catch
        {
            return new AppSettings();
        }
    }

    public void Save(AppSettings settings)
    {
        var json = JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(_path, json);
    }
}
