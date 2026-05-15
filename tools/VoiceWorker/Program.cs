using System.Net;
using System.Text;
using System.Text.Json;
using System.Speech.Synthesis;
using System.Collections.Concurrent;

const string DefaultPrefix = "http://127.0.0.1:32145/";
const string TestText = "热榜异动本地语音测试，当前语音提醒正常";
const int MaxTextLength = 200;

var prefix = args.FirstOrDefault(arg => arg.StartsWith("--url=", StringComparison.OrdinalIgnoreCase))?.Split('=', 2)[1]
  ?? Environment.GetEnvironmentVariable("VOICE_WORKER_URL")
  ?? DefaultPrefix;
if (!prefix.EndsWith('/')) prefix += "/";

using var worker = new VoiceWorker();
using var listener = new HttpListener();
listener.Prefixes.Add(prefix);
listener.Start();

Console.WriteLine($"VoiceWorker listening on {prefix}");

while (true)
{
  var context = await listener.GetContextAsync();
  _ = Task.Run(() => HandleRequestAsync(context, worker));
}

static async Task HandleRequestAsync(HttpListenerContext context, VoiceWorker worker)
{
  try
  {
    var request = context.Request;
    var path = request.Url?.AbsolutePath.TrimEnd('/').ToLowerInvariant() ?? "";

    if (request.HttpMethod == "GET" && (path == "" || path == "/health"))
    {
      await WriteJsonAsync(context.Response, 200, new { ok = true, service = "VoiceWorker" });
      return;
    }

    if (request.HttpMethod == "GET" && path == "/status")
    {
      await WriteJsonAsync(context.Response, 200, worker.GetStatus());
      return;
    }

    if (request.HttpMethod == "POST" && path == "/speak")
    {
      var payload = await JsonSerializer.DeserializeAsync<SpeakRequest>(request.InputStream, JsonOptions());
      var text = NormalizeSpeechText(payload?.Text);
      if (string.IsNullOrWhiteSpace(text))
      {
        await WriteJsonAsync(context.Response, 400, new { ok = false, message = "speech text is empty" });
        return;
      }

      worker.Enqueue(text);
      await WriteJsonAsync(context.Response, 200, new { ok = true, queued = true, queueLength = worker.QueueLength });
      return;
    }

    if (request.HttpMethod == "POST" && path == "/test")
    {
      worker.Enqueue(TestText);
      await WriteJsonAsync(context.Response, 200, new { ok = true, queued = true, queueLength = worker.QueueLength });
      return;
    }

    if (request.HttpMethod == "POST" && path == "/stop")
    {
      worker.Stop();
      await WriteJsonAsync(context.Response, 200, new { ok = true, queueLength = worker.QueueLength });
      return;
    }

    await WriteJsonAsync(context.Response, 404, new { ok = false, message = "route not found" });
  }
  catch (Exception error)
  {
    await WriteJsonAsync(context.Response, 500, new { ok = false, message = error.Message });
  }
}

static string NormalizeSpeechText(string? value)
{
  var text = string.Join(' ', (value ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).Trim();
  return text.Length > MaxTextLength ? text[..MaxTextLength] : text;
}

static JsonSerializerOptions JsonOptions() => new() { PropertyNameCaseInsensitive = true };

static async Task WriteJsonAsync(HttpListenerResponse response, int statusCode, object payload)
{
  response.StatusCode = statusCode;
  response.ContentType = "application/json; charset=utf-8";
  var bytes = JsonSerializer.SerializeToUtf8Bytes(payload, JsonOptions());
  response.ContentLength64 = bytes.Length;
  await response.OutputStream.WriteAsync(bytes);
  response.Close();
}

sealed class VoiceWorker : IDisposable
{
  private readonly ConcurrentQueue<string> _queue = new();
  private readonly AutoResetEvent _signal = new(false);
  private readonly Thread _thread;
  private readonly SpeechSynthesizer _speaker = new();
  private volatile bool _disposed;
  private volatile bool _speaking;
  private string _currentText = "";

  public VoiceWorker()
  {
    _speaker.Rate = 1;
    _speaker.Volume = 100;
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
    supported = OperatingSystem.IsWindows(),
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
    _speaker.SpeakAsyncCancelAll();
    _currentText = "";
    _speaking = false;
  }

  public void Dispose()
  {
    _disposed = true;
    _signal.Set();
    _speaker.Dispose();
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
        _speaker.Speak(text);
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
}

sealed record SpeakRequest(string? Text);
