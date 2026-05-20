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
    public bool VoiceEnabled { get; set; } = true;
    public double VoiceRate { get; set; } = 1;
    public int VoiceVolume { get; set; } = 100;
    public string VoiceName { get; set; } = "";
    public VoiceMode VoiceMode { get; set; } = VoiceMode.StrongOnly;
    public double Opacity { get; set; } = 1;
    public Dictionary<string, bool> EnabledEvents { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    public bool IsEventEnabled(string eventName)
    {
        return !EnabledEvents.TryGetValue(eventName, out var enabled) || enabled;
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
            VoiceEnabled = VoiceEnabled,
            VoiceRate = VoiceRate,
            VoiceVolume = VoiceVolume,
            VoiceName = VoiceName,
            VoiceMode = VoiceMode,
            Opacity = Opacity,
            EnabledEvents = new Dictionary<string, bool>(EnabledEvents, StringComparer.OrdinalIgnoreCase),
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
