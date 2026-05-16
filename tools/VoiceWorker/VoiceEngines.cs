using System.Collections.Concurrent;
using System.Speech.Synthesis;
using System.Text;
using System.Text.Json;

public interface IVoiceEngine : IDisposable
{
  string Name { get; }
  bool IsConfigured { get; }
  void Speak(string text);
  void Stop();
}

public sealed class LocalSpeechEngine : IVoiceEngine
{
  private readonly SpeechSynthesizer _speaker = new();

  public LocalSpeechEngine()
  {
    _speaker.Rate = 1;
    _speaker.Volume = 100;
  }

  public string Name => "local-sapi";
  public bool IsConfigured => OperatingSystem.IsWindows();

  public void Speak(string text) => _speaker.Speak(text);
  public void Stop() => _speaker.SpeakAsyncCancelAll();
  public void Dispose() => _speaker.Dispose();
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

  public void Speak(string text)
  {
    if (!_primary.IsConfigured || DateTimeOffset.UtcNow < _primaryUnavailableUntil)
    {
      _activeEngineName = _fallback.Name;
      _fallback.Speak(text);
      return;
    }

    try
    {
      _primary.Speak(text);
    }
    catch (Exception error)
    {
      Console.Error.WriteLine($"VoiceWorker primary engine failed: {error.Message}");
      _activeEngineName = _fallback.Name;
      _primaryUnavailableUntil = DateTimeOffset.UtcNow.Add(_retryAfterFailure);
      _fallback.Speak(text);
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
  public string AppId { get; init; } = "";
  public string AccessToken { get; init; } = "";
  public string ResourceId { get; init; } = "";
  public string VoiceType { get; init; } = "";
  public string Endpoint { get; init; } = "https://openspeech.bytedance.com/api/v3/tts/unidirectional";

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
    ResourceId = Environment.GetEnvironmentVariable("VOLC_TTS_RESOURCE_ID") ?? "",
    VoiceType = Environment.GetEnvironmentVariable("VOLC_TTS_VOICE_TYPE") ?? "",
    Endpoint = Environment.GetEnvironmentVariable("VOLC_TTS_ENDPOINT")
      ?? "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
  };
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

  public void Speak(string text)
  {
    if (!IsConfigured) throw new InvalidOperationException("volcengine tts is not configured");

    using var request = new HttpRequestMessage(HttpMethod.Post, _options.Endpoint);
    request.Headers.TryAddWithoutValidation("X-Api-App-Id", _options.AppId);
    request.Headers.TryAddWithoutValidation("X-Api-Access-Key", _options.AccessToken);
    request.Headers.TryAddWithoutValidation("X-Api-Resource-Id", _options.ResourceId);
    request.Headers.TryAddWithoutValidation("X-Api-Request-Id", Guid.NewGuid().ToString());
    request.Content = new StringContent(BuildRequestJson(text), Encoding.UTF8, "application/json");

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

  private string BuildRequestJson(string text)
  {
    var payload = new
    {
      req_params = new
      {
        text,
        speaker = _options.VoiceType,
        audio_params = new
        {
          format = "wav",
          sample_rate = 24000,
        },
      },
    };

    return JsonSerializer.Serialize(payload, JsonOptions());
  }

  private static byte[] DecodeAudio(string json)
  {
    using var document = JsonDocument.Parse(json);
    if (document.RootElement.TryGetProperty("code", out var codeElement) &&
      codeElement.TryGetInt32(out var code) &&
      code != 0 &&
      code != 3000)
    {
      var message = document.RootElement.TryGetProperty("message", out var messageElement)
        ? messageElement.GetString()
        : "unknown error";
      throw new InvalidOperationException($"volcengine tts returned {code}: {message}");
    }

    if (!document.RootElement.TryGetProperty("data", out var dataElement) &&
      !document.RootElement.TryGetProperty("audio", out dataElement))
    {
      throw new InvalidOperationException("volcengine tts response missing audio data");
    }

    var base64 = dataElement.GetString();
    if (string.IsNullOrWhiteSpace(base64))
    {
      throw new InvalidOperationException("volcengine tts response audio data is empty");
    }

    return Convert.FromBase64String(base64);
  }

  private static void PlayWaveAudio(byte[] audio)
  {
    using var stream = new MemoryStream(audio);
    using var player = new System.Media.SoundPlayer(stream);
    player.PlaySync();
  }

  private static JsonSerializerOptions JsonOptions() => new()
  {
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
  };
}

public sealed class VoiceWorker : IDisposable
{
  private readonly ConcurrentQueue<string> _queue = new();
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
  };

  public void Enqueue(string text)
  {
    _queue.Enqueue(text);
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

      _currentText = text;
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

  private static IVoiceEngine CreateDefaultEngine()
  {
    var local = new LocalSpeechEngine();
    var selected = Environment.GetEnvironmentVariable("VOICE_ENGINE") ?? "local";
    if (!selected.Equals("volcengine", StringComparison.OrdinalIgnoreCase))
    {
      return local;
    }

    return new FallbackVoiceEngine(new VolcengineTtsEngine(VolcengineTtsOptions.FromEnvironment()), local);
  }
}
