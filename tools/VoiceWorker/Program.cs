using System.Net;
using System.Text.Json;

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

sealed record SpeakRequest(string? Text);
