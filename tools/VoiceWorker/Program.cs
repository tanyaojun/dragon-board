using System.Net;
using System.Text.Json;

const string DefaultPrefix = "http://127.0.0.1:32145/";
const string TestText = "语音测试。中南文化，逼近涨停，涨幅百分之九点五四。";
const int MaxTextLength = 200;

var prefix = args.FirstOrDefault(arg => arg.StartsWith("--url=", StringComparison.OrdinalIgnoreCase))?.Split('=', 2)[1]
  ?? Environment.GetEnvironmentVariable("VOICE_WORKER_URL")
  ?? DefaultPrefix;
if (!prefix.EndsWith('/')) prefix += "/";

using var worker = new VoiceWorker();
using var listener = new HttpListener();
using var shutdown = new CancellationTokenSource();
listener.Prefixes.Add(prefix);
listener.Start();

Console.WriteLine($"VoiceWorker listening on {prefix}");

while (!shutdown.IsCancellationRequested)
{
  try
  {
    var context = await listener.GetContextAsync();
    _ = Task.Run(() => HandleRequestAsync(context, worker, listener, shutdown));
  }
  catch (HttpListenerException) when (shutdown.IsCancellationRequested)
  {
    break;
  }
  catch (ObjectDisposedException) when (shutdown.IsCancellationRequested)
  {
    break;
  }
}

static async Task HandleRequestAsync(
  HttpListenerContext context,
  VoiceWorker worker,
  HttpListener listener,
  CancellationTokenSource shutdown)
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
      var payload = await ReadSpeakRequestAsync(request);
      var text = NormalizeSpeechText(payload?.Text);
      if (string.IsNullOrWhiteSpace(text))
      {
        await WriteJsonAsync(context.Response, 400, new { ok = false, message = "speech text is empty" });
        return;
      }

      worker.Enqueue(text, NormalizeRate(payload?.Rate), NormalizeVolume(payload?.Volume), payload?.Voice);
      await WriteJsonAsync(context.Response, 200, new { ok = true, queued = true, queueLength = worker.QueueLength });
      return;
    }

    if (request.HttpMethod == "POST" && path == "/test")
    {
      var payload = await ReadSpeakRequestAsync(request);
      worker.Enqueue(TestText, NormalizeRate(payload?.Rate), NormalizeVolume(payload?.Volume), payload?.Voice);
      await WriteJsonAsync(context.Response, 200, new { ok = true, queued = true, queueLength = worker.QueueLength });
      return;
    }

    if (request.HttpMethod == "POST" && path == "/stop")
    {
      worker.Stop();
      await WriteJsonAsync(context.Response, 200, new { ok = true, queueLength = worker.QueueLength });
      return;
    }

    if (request.HttpMethod == "POST" && path == "/shutdown")
    {
      worker.Stop();
      await WriteJsonAsync(context.Response, 200, new { ok = true, shuttingDown = true });
      _ = Task.Run(() =>
      {
        Thread.Sleep(100);
        shutdown.Cancel();
        listener.Stop();
      });
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

static async Task<SpeakRequest?> ReadSpeakRequestAsync(HttpListenerRequest request)
{
  if (!request.HasEntityBody || request.ContentLength64 == 0) return null;
  return await JsonSerializer.DeserializeAsync<SpeakRequest>(request.InputStream, JsonOptions());
}

static double NormalizeRate(double? value)
{
  if (value is null || !double.IsFinite(value.Value)) return 1;
  return Math.Clamp(Math.Round(value.Value, 2), 0.6, 1.8);
}

static int NormalizeVolume(int? value)
{
  return Math.Clamp(value ?? 100, 0, 100);
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

sealed record SpeakRequest(string? Text, double? Rate, int? Volume, string? Voice);
