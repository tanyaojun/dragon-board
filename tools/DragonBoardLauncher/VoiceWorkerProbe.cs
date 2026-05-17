using System.Text.Json;

namespace DragonBoardLauncher;

public sealed record VoiceWorkerHealth(bool IsHealthy, string ProcessPath);

internal static class VoiceWorkerProbe
{
    private static readonly Uri BaseUri = new($"http://127.0.0.1:{LauncherServices.VoiceWorkerPort}");

    public static bool IsHealthy()
    {
        return GetHealth().IsHealthy;
    }

    public static VoiceWorkerHealth GetHealth()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromMilliseconds(700) };
            var response = client
                .GetAsync(new Uri(BaseUri, "/health"))
                .GetAwaiter()
                .GetResult();
            if (!response.IsSuccessStatusCode)
                return new VoiceWorkerHealth(false, "");

            using var body = response.Content.ReadAsStream();
            using var json = JsonDocument.Parse(body);
            var root = json.RootElement;
            if (!root.TryGetProperty("service", out var service) ||
                !string.Equals(service.GetString(), "VoiceWorker", StringComparison.OrdinalIgnoreCase))
            {
                return new VoiceWorkerHealth(false, "");
            }

            var processPath = root.TryGetProperty("processPath", out var path)
                ? path.GetString() ?? ""
                : "";
            return new VoiceWorkerHealth(true, processPath);
        }
        catch
        {
            return new VoiceWorkerHealth(false, "");
        }
    }

    public static bool Shutdown()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            using var response = client
                .PostAsync(new Uri(BaseUri, "/shutdown"), new StringContent("{}"))
                .GetAwaiter()
                .GetResult();
            return response.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
