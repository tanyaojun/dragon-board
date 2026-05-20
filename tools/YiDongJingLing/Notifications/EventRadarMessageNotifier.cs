using System.Text;
using System.Text.Json;
using YiDongJingLing.Events;

namespace YiDongJingLing.Notifications;

public sealed class EventRadarMessageNotifier : IDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly HttpClient _client;

    public EventRadarMessageNotifier(HttpMessageHandler? handler = null)
    {
        _client = handler is null
            ? new HttpClient()
            : new HttpClient(handler, disposeHandler: false);
    }

    public async Task<EventRadarMessageSendResult> SendEventsAsync(
        IReadOnlyList<EventRecord> events,
        Uri proxyBaseUri,
        CancellationToken cancellationToken = default)
    {
        if (events.Count == 0) return new EventRadarMessageSendResult(0, 0, 0);

        var request = new EventRadarMessageRequest(
            "yidong-jingling",
            events.Select(ToPayload).ToArray());
        var json = JsonSerializer.Serialize(request, JsonOptions);
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await _client.PostAsync(
            new Uri(proxyBaseUri, "/api/notifications/event-radar/events"),
            content,
            cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(ReadMessage(body) ?? $"飞书消息同步失败: HTTP {(int)response.StatusCode}");
        }

        using var document = JsonDocument.Parse(body);
        var root = document.RootElement;
        if (root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False)
        {
            throw new InvalidOperationException(ReadMessage(root) ?? "飞书消息同步失败");
        }

        return new EventRadarMessageSendResult(
            ReadInt(root, "queued"),
            ReadInt(root, "sent"),
            ReadInt(root, "skipped"));
    }

    public static EventRadarMessagePayload ToPayload(EventRecord item)
    {
        var timestamp = item.Timestamp.ToUnixTimeMilliseconds();
        return new EventRadarMessagePayload(
            $"{item.Code}-{item.Type}-{timestamp}",
            item.TypeName,
            timestamp,
            item.Code,
            item.DisplayName,
            item.ChangePct,
            item.Price,
            [],
            false);
    }

    public void Dispose()
    {
        _client.Dispose();
    }

    private static int ReadInt(JsonElement root, string propertyName)
    {
        return root.TryGetProperty(propertyName, out var value) && value.TryGetInt32(out var number)
            ? number
            : 0;
    }

    private static string? ReadMessage(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            return ReadMessage(document.RootElement);
        }
        catch
        {
            return string.IsNullOrWhiteSpace(body) ? null : body;
        }
    }

    private static string? ReadMessage(JsonElement root)
    {
        return root.TryGetProperty("message", out var message) && message.ValueKind == JsonValueKind.String
            ? message.GetString()
            : null;
    }
}

public sealed record EventRadarMessagePayload(
    string Id,
    string TypeName,
    long Timestamp,
    string Code,
    string Name,
    decimal ChangePct,
    decimal Price,
    IReadOnlyList<string> RelatedPlates,
    bool MatchedCandidate);

public sealed record EventRadarMessageSendResult(int Queued, int Sent, int Skipped);

internal sealed record EventRadarMessageRequest(
    string Source,
    IReadOnlyList<EventRadarMessagePayload> Events);
