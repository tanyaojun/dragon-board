using System.Text;
using System.Text.Json;
using YiDongJingLing.Events;

namespace YiDongJingLing.Notifications;

public sealed class OpeningSignalReporter : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly HttpClient _client;

    public OpeningSignalReporter(HttpMessageHandler? handler = null)
    {
        _client = handler is null
            ? new HttpClient()
            : new HttpClient(handler, disposeHandler: false);
    }

    public async Task<OpeningSignalReportResult> ReportAsync(
        EventRecord item,
        Uri proxyBaseUri,
        CancellationToken cancellationToken = default)
    {
        if (item.OpeningSignal is null) return new OpeningSignalReportResult(false, "none", "");

        var request = new OpeningSignalRequest("desktop", OpeningSignalPayload.FromSignal(item.OpeningSignal));
        var json = JsonSerializer.Serialize(request, JsonOptions);
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await _client.PostAsync(
            new Uri(proxyBaseUri, "/api/opening-signals"),
            content,
            cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(ReadMessage(body) ?? $"竞价信号上报失败: HTTP {(int)response.StatusCode}");
        }

        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        return new OpeningSignalReportResult(
            ReadBool(root, "accepted"),
            ReadString(root, "voiceOwner") ?? "none",
            ReadString(root, "dedupeAction") ?? "");
    }

    public void Dispose()
    {
        _client.Dispose();
    }

    private static bool ReadBool(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var value) &&
            value.ValueKind is JsonValueKind.True or JsonValueKind.False &&
            value.GetBoolean();
    }

    private static string? ReadString(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static string? ReadMessage(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            return ReadString(document.RootElement, "message");
        }
        catch
        {
            return string.IsNullOrWhiteSpace(body) ? null : body;
        }
    }
}

public sealed record OpeningSignalReportResult(bool Accepted, string VoiceOwner, string DedupeAction);

internal sealed record OpeningSignalRequest(string Source, OpeningSignalPayload Signal);

internal sealed record OpeningSignalPayload(
    string Stage,
    string Status,
    string Code,
    string Name,
    DateTimeOffset Time,
    decimal Price,
    decimal Pct,
    decimal Amount,
    bool VoiceEligible,
    string Reason)
{
    public static OpeningSignalPayload FromSignal(OpeningWeakToStrongSignal signal)
    {
        return new OpeningSignalPayload(
            signal.Stage,
            signal.Status,
            signal.Code,
            signal.Name,
            signal.Time,
            signal.Price,
            signal.Pct,
            signal.Amount,
            signal.VoiceEligible,
            signal.Reason);
    }
}
