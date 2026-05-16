using System.Net;
using System.Reflection;
using System.Text.Json;

Run("FromEnvironmentNormalizesConsoleInstanceIdToModelResourceId", () =>
{
  var previous = SnapshotEnvironment();
  try
  {
    Environment.SetEnvironmentVariable("VOLC_TTS_APP_ID", "9862004553");
    Environment.SetEnvironmentVariable("VOLC_TTS_ACCESS_KEY", "token");
    Environment.SetEnvironmentVariable("VOLC_TTS_RESOURCE_ID", "TTS-SeedTTS2.02000000755457052322");
    Environment.SetEnvironmentVariable("VOLC_TTS_VOICE_TYPE", "saturn_zh_male_shuanglangshaonian_tob");

    var options = VolcengineTtsOptions.FromEnvironment();

    AssertEqual("seed-tts-2.0", options.ResourceId, nameof(options.ResourceId));
    AssertTrue(options.IsConfigured, nameof(options.IsConfigured));
  }
  finally
  {
    RestoreEnvironment(previous);
  }
});

Run("SpeakSendsVolcengineV3HeadersAndPayload", () =>
{
  HttpRequestMessage? captured = null;
  string? capturedBody = null;
  using var engine = new VolcengineTtsEngine(
    new VolcengineTtsOptions
    {
      AppId = "app-id",
      AccessToken = "access-token",
      ResourceId = "seed-tts-2.0",
      VoiceType = "saturn_zh_male_shuanglangshaonian_tob",
      Endpoint = "https://example.test/tts",
    },
    new HttpClient(new CaptureHandler(request =>
    {
      captured = request;
      capturedBody = request.Content!.ReadAsStringAsync().GetAwaiter().GetResult();
      return new HttpResponseMessage(HttpStatusCode.OK)
      {
        Content = new StringContent(
          "{\"code\":0,\"message\":\"\",\"data\":\"AQID\"}\n{\"code\":20000000,\"message\":\"ok\",\"data\":null}"),
      };
    })),
    _ => { });

  engine.Speak(new VoiceUtterance("语音测试", 1.2, 90));

  AssertTrue(captured != null, nameof(captured));
  AssertEqual("app-id", captured!.Headers.GetValues("X-Api-App-Id").Single(), "X-Api-App-Id");
  AssertEqual("access-token", captured.Headers.GetValues("X-Api-Access-Key").Single(), "X-Api-Access-Key");
  AssertEqual("seed-tts-2.0", captured.Headers.GetValues("X-Api-Resource-Id").Single(), "X-Api-Resource-Id");

  using var document = JsonDocument.Parse(capturedBody!);
  var reqParams = document.RootElement.GetProperty("req_params");
  AssertEqual("语音测试", reqParams.GetProperty("text").GetString(), "text");
  AssertEqual("saturn_zh_male_shuanglangshaonian_tob", reqParams.GetProperty("speaker").GetString(), "speaker");
  AssertEqual("wav", reqParams.GetProperty("audio_params").GetProperty("format").GetString(), "format");
  AssertEqual(-10, reqParams.GetProperty("audio_params").GetProperty("speech_rate").GetInt32(), "speech_rate");
  AssertEqual(10, reqParams.GetProperty("audio_params").GetProperty("loudness_rate").GetInt32(), "loudness_rate");
});

Run("LocalSpeechEngineReportsAndSelectsInstalledVoices", () =>
{
  var voices = new[]
  {
    new SapiVoiceInfo("Microsoft Huihui", "zh-CN", "Female"),
    new SapiVoiceInfo("Microsoft Kangkang", "zh-CN", "Male"),
  };
  string? selected = null;
  using var engine = new LocalSpeechEngine(
    "Microsoft Kangkang",
    () => voices,
    voiceName => selected = voiceName,
    (_, _, _) => { });

  AssertEqual("Microsoft Kangkang", engine.DefaultVoiceName, "DefaultVoiceName");
  AssertEqual(2, engine.GetVoices().Count, "voice count");
  engine.Speak(new VoiceUtterance("语音测试", 1, 100, "Microsoft Huihui"));

  AssertEqual("Microsoft Huihui", selected, "selected voice");
});

Run("LocalSpeechEngineCachesInstalledVoicesOffSpeechHotPath", () =>
{
  var reads = 0;
  var voices = new[]
  {
    new SapiVoiceInfo("Microsoft Huihui", "zh-CN", "Female"),
    new SapiVoiceInfo("Microsoft Zira", "en-US", "Female"),
  };
  using var engine = new LocalSpeechEngine(
    "Microsoft Huihui",
    () =>
    {
      reads++;
      return voices;
    },
    _ => { },
    (_, _, _) => { });

  _ = engine.GetVoices();
  _ = engine.GetVoices();
  engine.Speak(new VoiceUtterance("第一次播报", 1, 100, "Microsoft Huihui"));
  engine.Speak(new VoiceUtterance("第二次播报", 1, 100, "Microsoft Zira"));

  AssertEqual(1, reads, "voice enumeration count");
});

Run("OneCoreSpeechEngineListsAndSpeaksOneCoreVoices", () =>
{
  var voices = new[]
  {
    new SapiVoiceInfo("Microsoft Kangkang", "zh-CN", "Male"),
    new SapiVoiceInfo("Microsoft Yaoyao", "zh-CN", "Female"),
  };
  (string Text, string Voice, double Rate, int Volume)? spoken = null;
  var audio = new byte[] { 82, 73, 70, 70 };
  using var engine = new OneCoreSpeechEngine(
    "Microsoft Kangkang",
    () => voices,
    utterance =>
    {
      spoken = (utterance.Text, utterance.Voice ?? "", utterance.Rate, utterance.Volume);
      return audio;
    },
    (_, _) => { });

  AssertEqual("local-onecore", engine.Name, "Name");
  AssertEqual("Microsoft Kangkang", engine.ActiveVoiceName, "ActiveVoiceName");
  AssertEqual(2, engine.GetVoices().Count, "voice count");

  engine.Speak(new VoiceUtterance("语音测试", 1.1, 70, "Microsoft Yaoyao"));

  AssertEqual("语音测试", spoken?.Text, "spoken text");
  AssertEqual("Microsoft Yaoyao", spoken?.Voice, "spoken voice");
  AssertEqual(1.1, spoken?.Rate, "spoken rate");
  AssertEqual(70, spoken?.Volume, "spoken volume");
});

Run("OneCoreSpeechEngineSynthesizesAndPlaysMemoryAudio", () =>
{
  var voices = new[]
  {
    new SapiVoiceInfo("Microsoft Kangkang", "zh-CN", "Male"),
    new SapiVoiceInfo("Microsoft Yaoyao", "zh-CN", "Female"),
  };
  var audio = new byte[] { 82, 73, 70, 70 };
  VoiceUtterance? synthesized = null;
  (byte[] Audio, int TimeoutMs)? played = null;
  using var engine = new OneCoreSpeechEngine(
    "Microsoft Kangkang",
    () => voices,
    utterance =>
    {
      synthesized = utterance;
      return audio;
    },
    (bytes, timeoutMs) => played = (bytes, timeoutMs));

  engine.Speak(new VoiceUtterance("热榜异动，中南文化封涨停板", 1.2, 80, "Microsoft Yaoyao"));

  AssertEqual("热榜异动，中南文化封涨停板", synthesized?.Text, "synthesized text");
  AssertEqual("Microsoft Yaoyao", synthesized?.Voice, "synthesized voice");
  AssertEqual(1.2, synthesized?.Rate, "synthesized rate");
  AssertEqual(80, synthesized?.Volume, "synthesized volume");
  AssertTrue(ReferenceEquals(audio, played?.Audio), "played synthesized audio");
  AssertEqual(10_000, played?.TimeoutMs, "fallback playback timeout");
});

Run("OneCoreSpeechEngineStopsMemoryPlayback", () =>
{
  var voices = new[]
  {
    new SapiVoiceInfo("Microsoft Kangkang", "zh-CN", "Male"),
  };
  var stopped = false;
  using var engine = new OneCoreSpeechEngine(
    "Microsoft Kangkang",
    () => voices,
    _ => [82, 73, 70, 70],
    (_, _) => { },
    () => stopped = true);

  engine.Stop();

  AssertTrue(stopped, "stopped memory playback");
});

Run("VoiceWorkerUsesOneCoreWhenRequested", () =>
{
  var previous = SnapshotEnvironment();
  try
  {
    Environment.SetEnvironmentVariable("VOICE_ENGINE", "onecore");
    Environment.SetEnvironmentVariable("VOICE_SAPI_VOICE_NAME", "");
    Environment.SetEnvironmentVariable("VOICE_ONECORE_VOICE_NAME", "Microsoft Kangkang");

    using var worker = new VoiceWorker();
    var status = worker.GetStatus();

    AssertEqual("local-onecore", GetAnonymousString(status, "engine"), "production engine");
  }
  finally
  {
    RestoreEnvironment(previous);
  }
});

Run("FallbackVoiceEngineReportsActiveEngineVoices", () =>
{
  using var primary = new StubVoiceEngine(
    "local-onecore",
    true,
    "Microsoft Kangkang",
    [new SapiVoiceInfo("Microsoft Kangkang", "zh-CN", "Male")]);
  using var fallback = new StubVoiceEngine(
    "local-sapi",
    true,
    "Microsoft Huihui Desktop",
    [new SapiVoiceInfo("Microsoft Huihui Desktop", "zh-CN", "Female")]);
  using var engine = new FallbackVoiceEngine(primary, fallback);

  AssertEqual("local-onecore", engine.Name, "active engine");
  AssertEqual("Microsoft Kangkang", engine.GetVoices().Single().Name, "active engine voice");
});

if (Environment.ExitCode != 0)
{
  Environment.Exit(Environment.ExitCode);
}

Console.WriteLine("VoiceWorker tests passed.");

static void Run(string name, Action test)
{
  try
  {
    test();
    Console.WriteLine($"PASS {name}");
  }
  catch (Exception error)
  {
    Console.Error.WriteLine($"FAIL {name}: {error.Message}");
    Environment.ExitCode = 1;
  }
}

static void AssertEqual<T>(T expected, T actual, string label)
{
  if (EqualityComparer<T>.Default.Equals(expected, actual)) return;
  throw new InvalidOperationException($"{label}: expected {expected}, got {actual}");
}

static void AssertTrue(bool value, string label)
{
  if (value) return;
  throw new InvalidOperationException($"{label}: expected true");
}

static string GetAnonymousString(object value, string propertyName)
{
  return value.GetType().GetProperty(propertyName)?.GetValue(value) as string ?? "";
}

static Dictionary<string, string?> SnapshotEnvironment() => new()
{
  ["VOICE_ENGINE"] = Environment.GetEnvironmentVariable("VOICE_ENGINE"),
  ["VOICE_SAPI_VOICE_NAME"] = Environment.GetEnvironmentVariable("VOICE_SAPI_VOICE_NAME"),
  ["VOICE_ONECORE_VOICE_NAME"] = Environment.GetEnvironmentVariable("VOICE_ONECORE_VOICE_NAME"),
  ["VOLC_TTS_APP_ID"] = Environment.GetEnvironmentVariable("VOLC_TTS_APP_ID"),
  ["VOLC_TTS_ACCESS_KEY"] = Environment.GetEnvironmentVariable("VOLC_TTS_ACCESS_KEY"),
  ["VOLC_TTS_ACCESS_TOKEN"] = Environment.GetEnvironmentVariable("VOLC_TTS_ACCESS_TOKEN"),
  ["VOLC_TTS_RESOURCE_ID"] = Environment.GetEnvironmentVariable("VOLC_TTS_RESOURCE_ID"),
  ["VOLC_TTS_VOICE_TYPE"] = Environment.GetEnvironmentVariable("VOLC_TTS_VOICE_TYPE"),
};

static void RestoreEnvironment(Dictionary<string, string?> values)
{
  foreach (var kv in values)
  {
    Environment.SetEnvironmentVariable(kv.Key, kv.Value);
  }
}

internal sealed class CaptureHandler : HttpMessageHandler
{
  private readonly Func<HttpRequestMessage, HttpResponseMessage> _handle;

  public CaptureHandler(Func<HttpRequestMessage, HttpResponseMessage> handle)
  {
    _handle = handle;
  }

  protected override Task<HttpResponseMessage> SendAsync(
    HttpRequestMessage request,
    CancellationToken cancellationToken)
  {
    return Task.FromResult(_handle(request));
  }
}

internal sealed class StubVoiceEngine : IVoiceEngine
{
  private readonly IReadOnlyList<SapiVoiceInfo> _voices;

  public StubVoiceEngine(string name, bool isConfigured, string? activeVoiceName, IReadOnlyList<SapiVoiceInfo> voices)
  {
    Name = name;
    IsConfigured = isConfigured;
    ActiveVoiceName = activeVoiceName;
    _voices = voices;
  }

  public string Name { get; }
  public bool IsConfigured { get; }
  public string? ActiveVoiceName { get; }
  public IReadOnlyList<SapiVoiceInfo> GetVoices() => _voices;
  public void Speak(VoiceUtterance utterance) { }
  public void Stop() { }
  public void Dispose() { }
}
