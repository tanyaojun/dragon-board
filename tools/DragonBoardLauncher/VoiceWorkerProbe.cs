namespace DragonBoardLauncher;

internal static class VoiceWorkerProbe
{
    private static readonly Uri BaseUri = new($"http://127.0.0.1:{LauncherServices.VoiceWorkerPort}");

    public static bool IsHealthy()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromMilliseconds(700) };
            var response = client
                .GetAsync(new Uri(BaseUri, "/health"))
                .GetAwaiter()
                .GetResult();
            if (!response.IsSuccessStatusCode)
                return false;

            var body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            return body.Contains("\"service\":\"VoiceWorker\"", StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
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
