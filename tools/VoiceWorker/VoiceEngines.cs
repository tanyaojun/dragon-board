using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Speech.Synthesis;
using System.Text;
using System.Text.Json;
using WinRtSpeechSynthesizer = Windows.Media.SpeechSynthesis.SpeechSynthesizer;

public interface IVoiceEngine : IDisposable
{
  string Name { get; }
  bool IsConfigured { get; }
  string? ActiveVoiceName { get; }
  IReadOnlyList<SapiVoiceInfo> GetVoices();
  void Speak(VoiceUtterance utterance);
  void Stop();
}

public sealed record VoiceUtterance(string Text, double Rate = 1, int Volume = 100, string? Voice = null);

public sealed record SapiVoiceInfo(string Name, string Culture, string Gender);

public sealed class LocalSpeechEngine : IVoiceEngine
{
  private readonly SpeechSynthesizer _speaker = new();
  private readonly Lazy<IReadOnlyList<SapiVoiceInfo>> _voices;
  private readonly Action<string> _selectVoice;
  private readonly Action<VoiceUtterance, int, int> _speak;

  public LocalSpeechEngine()
    : this(
      Environment.GetEnvironmentVariable("VOICE_SAPI_VOICE_NAME"))
  {
  }

  public LocalSpeechEngine(
    string? defaultVoiceName,
    Func<IReadOnlyList<SapiVoiceInfo>>? getVoices = null,
    Action<string>? selectVoice = null,
    Action<VoiceUtterance, int, int>? speak = null)
  {
    _speaker.Rate = 1;
    _speaker.Volume = 100;
    _voices = new Lazy<IReadOnlyList<SapiVoiceInfo>>(
      () => getVoices?.Invoke() ?? GetInstalledSapiVoices(),
      LazyThreadSafetyMode.ExecutionAndPublication);
    _selectVoice = selectVoice ?? _speaker.SelectVoice;
    _speak = speak ?? SpeakWithSynthesizer;
    DefaultVoiceName = ResolveAvailableVoiceName(NormalizeVoiceName(defaultVoiceName));
  }

  public string Name => "local-sapi";
  public bool IsConfigured => OperatingSystem.IsWindows();
  public string? DefaultVoiceName { get; }
  public string? ActiveVoiceName => DefaultVoiceName ?? _speaker.Voice?.Name;
  public IReadOnlyList<SapiVoiceInfo> GetVoices() => _voices.Value;

  public void Speak(VoiceUtterance utterance)
  {
    var voiceName = ResolveVoiceName(utterance.Voice);
    if (!string.IsNullOrWhiteSpace(voiceName))
    {
      _selectVoice(voiceName);
    }
    _speak(utterance, ToSapiRate(utterance.Rate), Math.Clamp(utterance.Volume, 0, 100));
  }
  public void Stop() => _speaker.SpeakAsyncCancelAll();
  public void Dispose() => _speaker.Dispose();

  private static int ToSapiRate(double rate)
  {
    var normalized = double.IsFinite(rate) ? rate : 1;
    return Math.Clamp((int)Math.Round((normalized - 1) * 5), -5, 4);
  }

  private string? ResolveVoiceName(string? requestedVoice)
  {
    return ResolveAvailableVoiceName(NormalizeVoiceName(requestedVoice) ?? DefaultVoiceName);
  }

  private string? ResolveAvailableVoiceName(string? requestedVoice)
  {
    if (string.IsNullOrWhiteSpace(requestedVoice)) return null;

    return GetVoices()
      .FirstOrDefault(voice => voice.Name.Equals(requestedVoice, StringComparison.OrdinalIgnoreCase))
      ?.Name;
  }

  private static string? NormalizeVoiceName(string? value)
  {
    var text = value?.Trim();
    return string.IsNullOrWhiteSpace(text) ? null : text;
  }

  private void SpeakWithSynthesizer(VoiceUtterance utterance, int rate, int volume)
  {
    _speaker.Rate = rate;
    _speaker.Volume = volume;
    _speaker.Speak(utterance.Text);
  }

  private static IReadOnlyList<SapiVoiceInfo> GetInstalledSapiVoices()
  {
    using var speaker = new SpeechSynthesizer();
    return speaker.GetInstalledVoices()
      .Where(voice => voice.Enabled)
      .Select(voice => new SapiVoiceInfo(
        voice.VoiceInfo.Name,
        voice.VoiceInfo.Culture.Name,
        voice.VoiceInfo.Gender.ToString()))
      .OrderByDescending(voice => voice.Culture.Equals("zh-CN", StringComparison.OrdinalIgnoreCase))
      .ThenBy(voice => voice.Name, StringComparer.OrdinalIgnoreCase)
      .ToArray();
  }
}

public sealed class OneCoreSpeechEngine : IVoiceEngine
{
  private readonly Lazy<IReadOnlyList<SapiVoiceInfo>> _voices;
  private readonly Func<VoiceUtterance, byte[]> _synthesize;
  private readonly Action<byte[], int> _playAudio;
  private readonly Action _stopAudio;

  public OneCoreSpeechEngine()
    : this(
      Environment.GetEnvironmentVariable("VOICE_ONECORE_VOICE_NAME"),
      GetInstalledOneCoreVoices,
      null,
      null,
      null)
  {
  }

  public OneCoreSpeechEngine(
    string? defaultVoiceName,
    Func<IReadOnlyList<SapiVoiceInfo>>? getVoices = null,
    Func<VoiceUtterance, byte[]>? synthesize = null,
    Action<byte[], int>? playAudio = null,
    Action? stopAudio = null)
  {
    _voices = new Lazy<IReadOnlyList<SapiVoiceInfo>>(
      () => getVoices?.Invoke() ?? GetInstalledOneCoreVoices(),
      LazyThreadSafetyMode.ExecutionAndPublication);
    DefaultVoiceName = ResolveAvailableVoiceName(NormalizeVoiceName(defaultVoiceName));
    _synthesize = synthesize ?? SynthesizeWithWinRT;
    _playAudio = playAudio ?? NativeAudioPlayer.PlayMemory;
    _stopAudio = stopAudio ?? NativeAudioPlayer.Stop;
  }

  public string Name => "local-onecore";
  public bool IsConfigured => OperatingSystem.IsWindows() && GetVoices().Count > 0;
  public string? DefaultVoiceName { get; }
  public string? ActiveVoiceName => DefaultVoiceName ?? GetVoices().FirstOrDefault()?.Name;
  public IReadOnlyList<SapiVoiceInfo> GetVoices() => _voices.Value;

  public void Speak(VoiceUtterance utterance)
  {
    var voiceName = ResolveAvailableVoiceName(NormalizeVoiceName(utterance.Voice)) ?? ActiveVoiceName;
    var audio = _synthesize(utterance with { Voice = voiceName });
    _playAudio(audio, VolcengineTtsEngine.GetWavePlaybackTimeoutMs(audio));
  }

  public void Stop() => _stopAudio();
  public void Dispose() { }

  private string? ResolveAvailableVoiceName(string? requestedVoice)
  {
    if (string.IsNullOrWhiteSpace(requestedVoice)) return null;

    return GetVoices()
      .FirstOrDefault(voice => voice.Name.Equals(requestedVoice, StringComparison.OrdinalIgnoreCase))
      ?.Name;
  }

  private static string? NormalizeVoiceName(string? value)
  {
    var text = value?.Trim();
    return string.IsNullOrWhiteSpace(text) ? null : text;
  }

  private static IReadOnlyList<SapiVoiceInfo> GetInstalledOneCoreVoices()
  {
    if (!OperatingSystem.IsWindows()) return Array.Empty<SapiVoiceInfo>();

    return WinRtSpeechSynthesizer.AllVoices
      .Select(voice => new SapiVoiceInfo(
        voice.DisplayName,
        voice.Language,
        voice.Gender.ToString()))
      .OrderByDescending(voice => voice.Culture.Equals("zh-CN", StringComparison.OrdinalIgnoreCase))
      .ThenBy(voice => voice.Name, StringComparer.OrdinalIgnoreCase)
      .ToArray();
  }

  private static byte[] SynthesizeWithWinRT(VoiceUtterance utterance)
  {
    using var synthesizer = new WinRtSpeechSynthesizer();
    var voiceName = NormalizeVoiceName(utterance.Voice);
    if (!string.IsNullOrWhiteSpace(voiceName))
    {
      var selectedVoice = WinRtSpeechSynthesizer.AllVoices.FirstOrDefault(voice =>
        voice.DisplayName.Equals(voiceName, StringComparison.OrdinalIgnoreCase));
      if (selectedVoice != null)
      {
        synthesizer.Voice = selectedVoice;
      }
    }

    synthesizer.Options.SpeakingRate = Math.Clamp(double.IsFinite(utterance.Rate) ? utterance.Rate : 1, 0.6, 1.8);
    synthesizer.Options.AudioVolume = Math.Clamp(utterance.Volume, 0, 100) / 100d;

    using var stream = synthesizer.SynthesizeTextToStreamAsync(utterance.Text).GetAwaiter().GetResult();
    using var input = stream.AsStreamForRead();
    using var output = new MemoryStream();
    input.CopyTo(output);

    var audio = output.ToArray();
    if (audio.Length == 0) throw new InvalidOperationException("onecore synthesis returned empty audio");
    return audio;
  }
}

public sealed class FallbackVoiceEngine : IVoiceEngine
{
  private readonly IVoiceEngine _primary;
  private readonly IVoiceEngine _fallback;
  private readonly TimeSpan _retryAfterFailure;
  private volatile string _activeEngineName;
  private DateTimeOffset _primaryUnavailableUntil = DateTimeOffset.MinValue;

  public FallbackVoiceEngine(IVoiceEngine primary, IVoiceEngine fallback, TimeSpan? retryAfterFailure = null)
  {
    _primary = primary;
    _fallback = fallback;
    _retryAfterFailure = retryAfterFailure ?? TimeSpan.FromMinutes(1);
    _activeEngineName = primary.IsConfigured ? primary.Name : fallback.Name;
  }

  public string Name => _activeEngineName;
  public bool IsConfigured => _primary.IsConfigured || _fallback.IsConfigured;
  public string? ActiveVoiceName =>
    _activeEngineName == _fallback.Name ? _fallback.ActiveVoiceName : _primary.ActiveVoiceName;
  public IReadOnlyList<SapiVoiceInfo> GetVoices() =>
    _activeEngineName == _fallback.Name ? _fallback.GetVoices() : _primary.GetVoices();

  public void Speak(VoiceUtterance utterance)
  {
    if (!_primary.IsConfigured || DateTimeOffset.UtcNow < _primaryUnavailableUntil)
    {
      _activeEngineName = _fallback.Name;
      _fallback.Speak(utterance);
      return;
    }

    try
    {
      _primary.Speak(utterance);
      _activeEngineName = _primary.Name;
    }
    catch (Exception error)
    {
      Console.Error.WriteLine($"VoiceWorker primary engine failed: {error.Message}");
      _activeEngineName = _fallback.Name;
      _primaryUnavailableUntil = DateTimeOffset.UtcNow.Add(_retryAfterFailure);
      _fallback.Speak(utterance);
    }
  }

  public void Stop()
  {
    _primary.Stop();
    _fallback.Stop();
  }

  public void Dispose()
  {
    _primary.Dispose();
    _fallback.Dispose();
  }
}

public sealed class VolcengineTtsOptions
{
  private const string Tts2ResourceId = "seed-tts-2.0";

  public string AppId { get; init; } = "";
  public string AccessToken { get; init; } = "";
  public string ResourceId { get; init; } = "";
  public string VoiceType { get; init; } = "";
  public string Endpoint { get; init; } = "https://openspeech.bytedance.com/api/v3/tts/unidirectional";
  public int SpeechRate { get; init; } = -20;
  public int LoudnessRate { get; init; } = 20;

  public bool IsConfigured =>
    !string.IsNullOrWhiteSpace(AppId)
    && !string.IsNullOrWhiteSpace(AccessToken)
    && !string.IsNullOrWhiteSpace(ResourceId)
    && !string.IsNullOrWhiteSpace(VoiceType);

  public static VolcengineTtsOptions FromEnvironment() => new()
  {
    AppId = Environment.GetEnvironmentVariable("VOLC_TTS_APP_ID") ?? "",
    AccessToken = Environment.GetEnvironmentVariable("VOLC_TTS_ACCESS_KEY")
      ?? Environment.GetEnvironmentVariable("VOLC_TTS_ACCESS_TOKEN")
      ?? "",
    ResourceId = NormalizeResourceId(Environment.GetEnvironmentVariable("VOLC_TTS_RESOURCE_ID")),
    VoiceType = Environment.GetEnvironmentVariable("VOLC_TTS_VOICE_TYPE") ?? "",
    Endpoint = Environment.GetEnvironmentVariable("VOLC_TTS_ENDPOINT")
      ?? "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
    SpeechRate = ReadIntEnvironment("VOLC_TTS_SPEECH_RATE", -20, -50, 100),
    LoudnessRate = ReadIntEnvironment("VOLC_TTS_LOUDNESS_RATE", 20, -50, 100),
  };

  private static int ReadIntEnvironment(string key, int defaultValue, int min, int max)
  {
    var value = Environment.GetEnvironmentVariable(key);
    if (!int.TryParse(value, out var parsed)) return defaultValue;
    return Math.Clamp(parsed, min, max);
  }

  private static string NormalizeResourceId(string? value)
  {
    var text = value?.Trim() ?? "";
    if (text.StartsWith("TTS-SeedTTS2.", StringComparison.OrdinalIgnoreCase)) return Tts2ResourceId;
    return text;
  }
}

public sealed class VolcengineTtsEngine : IVoiceEngine
{
  private readonly VolcengineTtsOptions _options;
  private readonly HttpClient _client;
  private readonly Action<byte[]> _playAudio;

  public VolcengineTtsEngine(
    VolcengineTtsOptions options,
    HttpClient? client = null,
    Action<byte[]>? playAudio = null)
  {
    _options = options;
    _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
    _playAudio = playAudio ?? PlayWaveAudio;
  }

  public string Name => "volcengine";
  public bool IsConfigured => _options.IsConfigured;
  public string? ActiveVoiceName => _options.VoiceType;
  public IReadOnlyList<SapiVoiceInfo> GetVoices() => Array.Empty<SapiVoiceInfo>();

  public void Speak(VoiceUtterance utterance)
  {
    if (!IsConfigured) throw new InvalidOperationException("volcengine tts is not configured");

    using var request = new HttpRequestMessage(HttpMethod.Post, _options.Endpoint);
    request.Headers.TryAddWithoutValidation("X-Api-App-Id", _options.AppId);
    request.Headers.TryAddWithoutValidation("X-Api-Access-Key", _options.AccessToken);
    request.Headers.TryAddWithoutValidation("X-Api-Resource-Id", _options.ResourceId);
    request.Headers.TryAddWithoutValidation("X-Api-Request-Id", Guid.NewGuid().ToString());
    request.Content = new StringContent(BuildRequestJson(utterance), Encoding.UTF8, "application/json");

    using var response = _client.SendAsync(request).GetAwaiter().GetResult();
    var body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
    if (!response.IsSuccessStatusCode)
    {
      throw new InvalidOperationException($"volcengine tts failed: {(int)response.StatusCode} {body}");
    }

    var audio = DecodeAudio(body);
    _playAudio(audio);
  }

  public void Stop() { }
  public void Dispose() => _client.Dispose();

  private string BuildRequestJson(VoiceUtterance utterance)
  {
    var payload = new
    {
      req_params = new
      {
        text = utterance.Text,
        speaker = _options.VoiceType,
        audio_params = new
        {
          format = "wav",
          sample_rate = 24000,
          speech_rate = ToVolcengineRate(utterance.Rate),
          loudness_rate = ToVolcengineLoudness(utterance.Volume),
        },
      },
    };

    return JsonSerializer.Serialize(payload, JsonOptions());
  }

  private int ToVolcengineRate(double rate)
  {
    var normalized = double.IsFinite(rate) ? rate : 1;
    return Math.Clamp(_options.SpeechRate + (int)Math.Round((normalized - 1) * 50), -50, 100);
  }

  private int ToVolcengineLoudness(int volume)
  {
    var normalized = Math.Clamp(volume, 0, 100);
    return Math.Clamp(_options.LoudnessRate + normalized - 100, -50, 100);
  }

  private static byte[] DecodeAudio(string json)
  {
    using var audio = new MemoryStream();

    foreach (var line in SplitJsonLines(json))
    {
      using var document = JsonDocument.Parse(line);
      if (document.RootElement.TryGetProperty("code", out var codeElement) &&
        codeElement.TryGetInt32(out var code) &&
        code != 0 &&
        code != 3000 &&
        code != 20000000)
      {
        var message = document.RootElement.TryGetProperty("message", out var messageElement)
          ? messageElement.GetString()
          : "unknown error";
        throw new InvalidOperationException($"volcengine tts returned {code}: {message}");
      }

      if (!document.RootElement.TryGetProperty("data", out var dataElement) &&
        !document.RootElement.TryGetProperty("audio", out dataElement))
      {
        continue;
      }

      var base64 = dataElement.GetString();
      if (string.IsNullOrWhiteSpace(base64)) continue;
      var chunk = Convert.FromBase64String(base64);
      audio.Write(chunk, 0, chunk.Length);
    }

    if (audio.Length == 0)
    {
      throw new InvalidOperationException("volcengine tts response missing audio data");
    }

    return NormalizeWaveHeader(audio.ToArray());
  }

  private static IEnumerable<string> SplitJsonLines(string value)
  {
    return value
      .Split(new[] { "\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries)
      .Select(line => line.Trim())
      .Where(line => line.Length > 0);
  }

  private static byte[] NormalizeWaveHeader(byte[] audio)
  {
    if (audio.Length < 44 ||
      Encoding.ASCII.GetString(audio, 0, 4) != "RIFF" ||
      Encoding.ASCII.GetString(audio, 8, 4) != "WAVE")
    {
      return audio;
    }

    var normalized = (byte[])audio.Clone();
    BitConverter.GetBytes((uint)(normalized.Length - 8)).CopyTo(normalized, 4);

    var dataOffset = FindAscii(normalized, "data");
    if (dataOffset >= 0 && dataOffset + 8 <= normalized.Length)
    {
      BitConverter.GetBytes((uint)(normalized.Length - dataOffset - 8)).CopyTo(normalized, dataOffset + 4);
    }

    return normalized;
  }

  private static int FindAscii(byte[] bytes, string text)
  {
    var needle = Encoding.ASCII.GetBytes(text);
    for (var i = 0; i <= bytes.Length - needle.Length; i++)
    {
      var matched = true;
      for (var j = 0; j < needle.Length; j++)
      {
        if (bytes[i + j] == needle[j]) continue;
        matched = false;
        break;
      }
      if (matched) return i;
    }
    return -1;
  }

  private static void PlayWaveAudio(byte[] audio)
  {
    var filePath = Path.Combine(Path.GetTempPath(), $"dragon-board-voice-{Guid.NewGuid():N}.wav");
    File.WriteAllBytes(filePath, audio);
    try
    {
      NativeAudioPlayer.PlayFile(filePath);
      Thread.Sleep(GetWavePlaybackTimeoutMs(audio));
      NativeAudioPlayer.Stop();
    }
    finally
    {
      TryDeleteFile(filePath);
    }
  }

  private static void TryDeleteFile(string filePath)
  {
    try
    {
      File.Delete(filePath);
    }
    catch (IOException) { }
    catch (UnauthorizedAccessException) { }
  }

  public static int GetWavePlaybackTimeoutMs(byte[] audio)
  {
    var dataOffset = FindAscii(audio, "data");
    var fmtOffset = FindAscii(audio, "fmt ");
    if (dataOffset < 0 || dataOffset + 8 > audio.Length || fmtOffset < 0 || fmtOffset + 24 > audio.Length)
    {
      return 10_000;
    }

    var dataSize = BitConverter.ToUInt32(audio, dataOffset + 4);
    var channels = BitConverter.ToUInt16(audio, fmtOffset + 10);
    var sampleRate = BitConverter.ToUInt32(audio, fmtOffset + 12);
    var bitsPerSample = BitConverter.ToUInt16(audio, fmtOffset + 22);
    var bytesPerSecond = sampleRate * channels * bitsPerSample / 8;
    if (bytesPerSecond == 0) return 10_000;

    var durationMs = (int)Math.Ceiling(dataSize * 1000d / bytesPerSecond);
    return Math.Clamp(durationMs + 1_500, 2_000, 35_000);
  }

  private static JsonSerializerOptions JsonOptions() => new()
  {
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
  };
}

internal static class NativeAudioPlayer
{
  private const uint SndSync = 0x0000;
  private const uint SndAsync = 0x0001;
  private const uint SndMemory = 0x0004;
  private const uint SndNodefault = 0x0002;
  private const uint SndFilename = 0x00020000;

  public static void PlayFile(string filePath)
  {
    if (!PlaySound(filePath, IntPtr.Zero, SndAsync | SndFilename | SndNodefault))
    {
      throw new InvalidOperationException("winmm PlaySound failed");
    }
  }

  public static void PlayMemory(byte[] audio, int timeoutMs)
  {
    if (!PlaySound(audio, IntPtr.Zero, SndAsync | SndMemory | SndNodefault))
    {
      throw new InvalidOperationException("winmm PlaySound memory failed");
    }

    Thread.Sleep(timeoutMs);
    Stop();
  }

  public static void Stop() => PlaySound((string?)null, IntPtr.Zero, SndSync);

  [DllImport("winmm.dll", SetLastError = true)]
  private static extern bool PlaySound(string? pszSound, IntPtr hmod, uint fdwSound);

  [DllImport("winmm.dll", SetLastError = true)]
  private static extern bool PlaySound(byte[] pszSound, IntPtr hmod, uint fdwSound);
}

public sealed class VoiceWorker : IDisposable
{
  private readonly ConcurrentQueue<VoiceUtterance> _queue = new();
  private readonly AutoResetEvent _signal = new(false);
  private readonly Thread _thread;
  private readonly IVoiceEngine _engine;
  private volatile bool _disposed;
  private volatile bool _speaking;
  private string _currentText = "";

  public VoiceWorker(IVoiceEngine? engine = null)
  {
    _engine = engine ?? CreateDefaultEngine();
    _thread = new Thread(Run)
    {
      IsBackground = true,
      Name = "VoiceWorker.SpeechLoop",
    };
    _thread.SetApartmentState(ApartmentState.STA);
    _thread.Start();
  }

  public int QueueLength => _queue.Count + (_speaking ? 1 : 0);

  public object GetStatus() => new
  {
    ok = true,
    supported = _engine.IsConfigured,
    engine = _engine.Name,
    speaking = _speaking,
    currentText = _currentText,
    queueLength = QueueLength,
    voice = _engine.ActiveVoiceName,
    voices = _engine.GetVoices(),
  };

  public void Enqueue(string text, double rate = 1, int volume = 100, string? voice = null)
  {
    _queue.Enqueue(new VoiceUtterance(text, NormalizeRate(rate), Math.Clamp(volume, 0, 100), NormalizeVoice(voice)));
    _signal.Set();
  }

  public void Stop()
  {
    while (_queue.TryDequeue(out _)) { }
    _engine.Stop();
    _currentText = "";
    _speaking = false;
  }

  public void Dispose()
  {
    _disposed = true;
    _signal.Set();
    _engine.Dispose();
    _signal.Dispose();
  }

  private void Run()
  {
    while (!_disposed)
    {
      if (!_queue.TryDequeue(out var text))
      {
        _signal.WaitOne();
        continue;
      }

      _currentText = text.Text;
      _speaking = true;
      try
      {
        _engine.Speak(text);
      }
      catch (Exception error)
      {
        Console.Error.WriteLine($"VoiceWorker speak failed: {error.Message}");
      }
      finally
      {
        _speaking = false;
        _currentText = "";
      }
    }
  }

  private static double NormalizeRate(double rate)
  {
    if (!double.IsFinite(rate)) return 1;
    return Math.Clamp(Math.Round(rate, 2), 0.6, 1.8);
  }

  private static string? NormalizeVoice(string? voice)
  {
    var text = voice?.Trim();
    return string.IsNullOrWhiteSpace(text) ? null : text;
  }

  private static IVoiceEngine CreateDefaultEngine()
  {
    var local = new LocalSpeechEngine();
    var selected = Environment.GetEnvironmentVariable("VOICE_ENGINE") ?? "local";
    if (selected.Equals("onecore", StringComparison.OrdinalIgnoreCase))
    {
      return new FallbackVoiceEngine(new OneCoreSpeechEngine(), local);
    }

    if (!selected.Equals("volcengine", StringComparison.OrdinalIgnoreCase))
    {
      return local;
    }

    return new FallbackVoiceEngine(new VolcengineTtsEngine(VolcengineTtsOptions.FromEnvironment()), local);
  }
}
