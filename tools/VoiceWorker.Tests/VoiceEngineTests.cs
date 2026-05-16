using System.Net;
using System.Text;

public sealed class VoiceEngineTests
{
  [Fact]
  public void VolcengineOptionsRequiresAppIdAccessKeyResourceAndVoiceType()
  {
    var missingToken = new VolcengineTtsOptions
    {
      AppId = "app",
      AccessToken = "",
      ResourceId = "volc.service_type.10029",
      VoiceType = "S_7BMNX9V22",
    };

    var complete = new VolcengineTtsOptions
    {
      AppId = "app",
      AccessToken = "token",
      ResourceId = "volc.service_type.10029",
      VoiceType = "S_7BMNX9V22",
    };

    Assert.False(missingToken.IsConfigured);
    Assert.True(complete.IsConfigured);
  }

  [Fact]
  public void FallbackEngineUsesLocalEngineWhenPrimaryIsNotConfigured()
  {
    using var primary = new RecordingVoiceEngine("volcengine", isConfigured: false);
    using var fallback = new RecordingVoiceEngine("local-sapi", isConfigured: true);
    using var engine = new FallbackVoiceEngine(primary, fallback);

    engine.Speak("中南文化即将打开涨停");

    Assert.Empty(primary.SpokenTexts);
    Assert.Equal(["中南文化即将打开涨停"], fallback.SpokenTexts);
    Assert.Equal("local-sapi", engine.Name);
  }

  [Fact]
  public void FallbackEngineUsesLocalEngineWhenPrimarySpeakFails()
  {
    using var primary = new RecordingVoiceEngine("volcengine", isConfigured: true, failOnSpeak: true);
    using var fallback = new RecordingVoiceEngine("local-sapi", isConfigured: true);
    using var engine = new FallbackVoiceEngine(primary, fallback, TimeSpan.FromMinutes(1));

    engine.Speak("金富科技打开涨停板");
    engine.Speak("中南文化逼近涨停");

    Assert.Equal(["金富科技打开涨停板"], primary.SpokenTexts);
    Assert.Equal(["金富科技打开涨停板", "中南文化逼近涨停"], fallback.SpokenTexts);
    Assert.Equal("local-sapi", engine.Name);
  }

  [Fact]
  public void VolcengineEnginePostsExpectedRequestAndPlaysReturnedAudio()
  {
    var audioBytes = new byte[] { 82, 73, 70, 70 };
    using var handler = new CapturingHandler(
      HttpStatusCode.OK,
      $$"""{"code":3000,"data":"{{Convert.ToBase64String(audioBytes)}}" }""");
    using var httpClient = new HttpClient(handler);
    var played = new List<byte[]>();
    using var engine = new VolcengineTtsEngine(
      new VolcengineTtsOptions
      {
        AppId = "app-id",
        AccessToken = "access-token",
        ResourceId = "volc.service_type.10029",
        VoiceType = "S_7BMNX9V22",
        Endpoint = "https://example.test/api/v3/tts/unidirectional",
      },
      httpClient,
      played.Add);

    engine.Speak("热榜异动语音测试");

    Assert.Equal(HttpMethod.Post, handler.Request?.Method);
    Assert.Equal("https://example.test/api/v3/tts/unidirectional", handler.Request?.RequestUri?.ToString());
    Assert.NotNull(handler.Request);
    Assert.True(handler.Request.Headers.TryGetValues("X-Api-App-Id", out var appIds));
    Assert.True(handler.Request.Headers.TryGetValues("X-Api-Access-Key", out var accessKeys));
    Assert.True(handler.Request.Headers.TryGetValues("X-Api-Resource-Id", out var resourceIds));
    Assert.Equal("app-id", Assert.Single(appIds));
    Assert.Equal("access-token", Assert.Single(accessKeys));
    Assert.Equal("volc.service_type.10029", Assert.Single(resourceIds));
    Assert.Contains("\"speaker\":\"S_7BMNX9V22\"", handler.Body);
    Assert.Contains(@"""text"":""\u70ED\u699C\u5F02\u52A8\u8BED\u97F3\u6D4B\u8BD5""", handler.Body);
    Assert.Single(played);
    Assert.Equal(audioBytes, played[0]);
  }

  private sealed class RecordingVoiceEngine : IVoiceEngine
  {
    private readonly bool _failOnSpeak;

    public RecordingVoiceEngine(string name, bool isConfigured, bool failOnSpeak = false)
    {
      Name = name;
      IsConfigured = isConfigured;
      _failOnSpeak = failOnSpeak;
    }

    public string Name { get; }
    public bool IsConfigured { get; }
    public List<string> SpokenTexts { get; } = [];

    public void Speak(string text)
    {
      SpokenTexts.Add(text);
      if (_failOnSpeak) throw new InvalidOperationException("primary failed");
    }

    public void Stop() { }
    public void Dispose() { }
  }

  private sealed class CapturingHandler : HttpMessageHandler
  {
    private readonly HttpStatusCode _statusCode;
    private readonly string _responseBody;

    public CapturingHandler(HttpStatusCode statusCode, string responseBody)
    {
      _statusCode = statusCode;
      _responseBody = responseBody;
    }

    public HttpRequestMessage? Request { get; private set; }
    public string Body { get; private set; } = "";

    protected override async Task<HttpResponseMessage> SendAsync(
      HttpRequestMessage request,
      CancellationToken cancellationToken)
    {
      Request = request;
      Body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
      return new HttpResponseMessage(_statusCode)
      {
        Content = new StringContent(_responseBody, Encoding.UTF8, "application/json"),
      };
    }
  }
}
