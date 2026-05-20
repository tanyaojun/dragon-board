using System.Diagnostics;
using System.Text;
using System.Text.Json;
using YiDongJingLing.Events;

namespace YiDongJingLing.Speech;

public sealed record VoiceInfo(string Name, string Culture, string Gender);

public sealed class SpeechAnnouncer : IDisposable
{
    private static readonly Uri WorkerBaseUri = new("http://127.0.0.1:32145/");
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _client;
    private readonly string _root;
    private readonly Action<string>? _log;
    private Process? _workerProcess;
    private bool _startedWorker;
    private volatile bool _enabled = true;

    public SpeechAnnouncer()
        : this(ProjectRootLocator.Find())
    {
    }

    public SpeechAnnouncer(string root, Action<string>? log = null, HttpMessageHandler? handler = null)
    {
        _root = root;
        _log = log;
        _client = handler == null ? new HttpClient() : new HttpClient(handler);
        _client.Timeout = TimeSpan.FromSeconds(2);
    }

    public bool Enabled
    {
        get => _enabled;
        set => _enabled = value;
    }

    public double Rate { get; set; } = 1;
    public int Volume { get; set; } = 100;
    public string Voice { get; set; } = "";

    public IReadOnlyList<VoiceInfo> GetVoices()
    {
        return GetVoicesAsync().GetAwaiter().GetResult();
    }

    public async Task<IReadOnlyList<VoiceInfo>> GetVoicesAsync()
    {
        var status = await GetStatusAsync(ensureWorker: true).ConfigureAwait(false);
        return status?.Voices ?? [];
    }

    public void Announce(IReadOnlyList<EventRecord> events)
    {
        _ = AnnounceAsync(events);
    }

    public async Task AnnounceAsync(IReadOnlyList<EventRecord> events)
    {
        if (!Enabled) return;
        var text = EventDeduper.BuildSpeechText(events);
        if (!string.IsNullOrWhiteSpace(text))
        {
            await SpeakAsync(text, Rate, Volume, Voice).ConfigureAwait(false);
        }
    }

    public void Test()
    {
        _ = TestAsync(Enabled, Rate, Volume, Voice);
    }

    public async Task TestAsync(bool enabled, double rate, int volume, string voice)
    {
        if (!enabled) return;
        await PostAsync("test", new VoiceRequest(null, rate, volume, NormalizeVoice(voice)), ensureWorker: true)
            .ConfigureAwait(false);
    }

    public void Stop()
    {
        _ = StopAsync();
    }

    public async Task StopAsync()
    {
        await PostAsync("stop", new { }, ensureWorker: false).ConfigureAwait(false);
    }

    public void Dispose()
    {
        try
        {
            StopAsync().GetAwaiter().GetResult();
            if (_startedWorker)
            {
                PostAsync("shutdown", new { }, ensureWorker: false).GetAwaiter().GetResult();
                _workerProcess?.WaitForExit(1200);
            }
        }
        catch
        {
        }

        _workerProcess?.Dispose();
        _client.Dispose();
    }

    private async Task SpeakAsync(string text, double rate, int volume, string voice)
    {
        if (!Enabled) return;
        await PostAsync("speak", new VoiceRequest(text, rate, volume, NormalizeVoice(voice)), ensureWorker: true)
            .ConfigureAwait(false);
    }

    private async Task<VoiceStatus?> GetStatusAsync(bool ensureWorker)
    {
        if (ensureWorker && !await EnsureWorkerAsync().ConfigureAwait(false)) return null;

        try
        {
            using var response = await _client.GetAsync(new Uri(WorkerBaseUri, "status")).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode) return null;
            await using var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false);
            return await JsonSerializer.DeserializeAsync<VoiceStatus>(stream, JsonOptions).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _log?.Invoke($"读取 VoiceWorker 状态失败: {ex.Message}");
            return null;
        }
    }

    private async Task PostAsync<T>(string path, T payload, bool ensureWorker)
    {
        if (ensureWorker && !await EnsureWorkerAsync().ConfigureAwait(false)) return;

        try
        {
            var json = JsonSerializer.Serialize(payload, JsonOptions);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using var response = await _client.PostAsync(new Uri(WorkerBaseUri, path), content).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                _log?.Invoke($"VoiceWorker 请求失败: {path} {(int)response.StatusCode}");
            }
        }
        catch (Exception ex)
        {
            _log?.Invoke($"VoiceWorker 请求失败: {path} {ex.Message}");
        }
    }

    private async Task<bool> EnsureWorkerAsync()
    {
        if (await IsHealthyAsync().ConfigureAwait(false)) return true;

        StartWorker();
        for (var i = 0; i < 16; i++)
        {
            await Task.Delay(250).ConfigureAwait(false);
            if (await IsHealthyAsync().ConfigureAwait(false)) return true;
        }

        _log?.Invoke("VoiceWorker 未就绪，语音播报暂不可用。");
        return false;
    }

    private async Task<bool> IsHealthyAsync()
    {
        try
        {
            using var response = await _client.GetAsync(new Uri(WorkerBaseUri, "health")).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode) return false;
            await using var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false);
            using var document = await JsonDocument.ParseAsync(stream).ConfigureAwait(false);
            return document.RootElement.TryGetProperty("service", out var service) &&
                string.Equals(service.GetString(), "VoiceWorker", StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private void StartWorker()
    {
        if (_workerProcess is { HasExited: false }) return;

        try
        {
            var info = CreateVoiceWorkerStartInfo();
            var process = new Process { StartInfo = info, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, e) =>
            {
                if (!string.IsNullOrWhiteSpace(e.Data)) _log?.Invoke($"[VoiceWorker] {e.Data}");
            };
            process.ErrorDataReceived += (_, e) =>
            {
                if (!string.IsNullOrWhiteSpace(e.Data)) _log?.Invoke($"[VoiceWorker] {e.Data}");
            };

            if (!process.Start())
            {
                _log?.Invoke("启动 VoiceWorker 失败。");
                return;
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            _workerProcess = process;
            _startedWorker = true;
            _log?.Invoke($"已启动 VoiceWorker，PID={process.Id}。");
        }
        catch (Exception ex)
        {
            _log?.Invoke($"启动 VoiceWorker 失败: {ex.Message}");
        }
    }

    private ProcessStartInfo CreateVoiceWorkerStartInfo()
    {
        var releaseExe = Path.Combine(
            _root,
            "tools",
            "VoiceWorker",
            "bin",
            "Release",
            "net8.0-windows10.0.19041.0",
            "VoiceWorker.exe");
        var debugExe = Path.Combine(
            _root,
            "tools",
            "VoiceWorker",
            "bin",
            "Debug",
            "net8.0-windows10.0.19041.0",
            "VoiceWorker.exe");

        var info = File.Exists(releaseExe)
            ? HiddenProcessInfo(releaseExe, "", _root)
            : File.Exists(debugExe)
                ? HiddenProcessInfo(debugExe, "", _root)
                : HiddenProcessInfo("dotnet", @"run --project tools\VoiceWorker\VoiceWorker.csproj", _root);

        info.Environment["VOICE_WORKER_URL"] = WorkerBaseUri.ToString();
        LoadVoiceWorkerEnv(info);
        return info;
    }

    private static ProcessStartInfo HiddenProcessInfo(string fileName, string arguments, string workingDirectory)
    {
        return new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            WorkingDirectory = workingDirectory,
            CreateNoWindow = true,
            UseShellExecute = false,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
    }

    private void LoadVoiceWorkerEnv(ProcessStartInfo info)
    {
        var envPath = Path.Combine(_root, "tools", "VoiceWorker", ".env.local");
        if (!File.Exists(envPath)) return;

        var count = 0;
        foreach (var line in File.ReadLines(envPath))
        {
            var text = line.Trim();
            if (text.Length == 0 || text.StartsWith('#')) continue;
            var index = text.IndexOf('=');
            if (index <= 0) continue;
            var key = text[..index].Trim();
            var value = text[(index + 1)..].Trim().Trim('"');
            if (key.Length == 0) continue;
            info.Environment[key] = value;
            count++;
        }

        if (count > 0) _log?.Invoke($"VoiceWorker 已加载环境变量: {envPath} ({count} 项)。");
    }

    private static string? NormalizeVoice(string value)
    {
        var text = value.Trim();
        return string.IsNullOrWhiteSpace(text) ? null : text;
    }

    private sealed record VoiceRequest(string? Text, double Rate, int Volume, string? Voice);

    private sealed record VoiceStatus(bool Ok, bool Supported, string Engine, string? Voice, VoiceInfo[]? Voices);
}
