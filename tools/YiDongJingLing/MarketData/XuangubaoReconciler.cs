using System.Text.Json;

namespace YiDongJingLing.MarketData;

public sealed record XuangubaoGap(
    string Code,
    string Name,
    int EventType,
    DateTimeOffset EventTime);

public sealed record XuangubaoReconcileResult(
    int UpstreamCount,
    int CoveredCount,
    IReadOnlyList<XuangubaoGap> Gaps,
    IReadOnlyList<string> Errors)
{
    public static XuangubaoReconcileResult Empty { get; } = new(0, 0, Array.Empty<XuangubaoGap>(), Array.Empty<string>());
}

/// <summary>
/// 选股宝异动双源对账：拉取 /api/xuangubao/events 近端事件，与本地已触发事件的股票集合比对，
/// 报出"上游有、本地无"的漏报（detection gap），用于阈值调优。只对账、不转播、不落业务库。
/// </summary>
public sealed class XuangubaoReconciler
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _client;
    private readonly Func<DateTimeOffset> _now;

    public XuangubaoReconciler(HttpClient? client = null, Func<DateTimeOffset>? now = null)
    {
        _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        _now = now ?? (() => DateTimeOffset.Now);
    }

    /// <param name="localEventCodes">本地当日已触发过异动事件的股票代码集合。</param>
    /// <param name="recentWindow">只对账该窗口内的上游事件，避免历史事件误报漏报。</param>
    public async Task<XuangubaoReconcileResult> ReconcileAsync(
        Uri proxyBaseUri,
        IReadOnlyCollection<string> localEventCodes,
        TimeSpan? recentWindow = null,
        CancellationToken cancellationToken = default)
    {
        var window = recentWindow ?? TimeSpan.FromMinutes(30);
        var errors = new List<string>();
        var covered = 0;
        var gaps = new List<XuangubaoGap>();
        var now = _now();

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get,
                new Uri(proxyBaseUri, "/api/xuangubao/events?count=120"));
            using var response = await _client.SendAsync(request, cancellationToken).ConfigureAwait(false);
            response.EnsureSuccessStatusCode();
            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
            var (events, parseErrors) = ParseEvents(document.RootElement);
            errors.AddRange(parseErrors);

            var local = localEventCodes.ToHashSet(StringComparer.Ordinal);
            foreach (var (code, name, eventType, eventTime) in events)
            {
                if (now - eventTime > window) continue;
                if (local.Contains(code))
                {
                    covered++;
                    continue;
                }
                gaps.Add(new XuangubaoGap(code, name, eventType, eventTime));
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            errors.Add($"upstream_unavailable: {ex.Message}");
        }

        gaps.Sort((a, b) => b.EventTime.CompareTo(a.EventTime));
        return new XuangubaoReconcileResult(covered + gaps.Count, covered, gaps, errors);
    }

    /// <summary>解析选股宝事件数组。未知结构的条目计入 errors（fail-visible）。</summary>
    public static (IReadOnlyList<(string Code, string Name, int EventType, DateTimeOffset EventTime)> Events, IReadOnlyList<string> Errors)
        ParseEvents(JsonElement root)
    {
        var errors = new List<string>();
        var events = new List<(string, string, int, DateTimeOffset)>();
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("data", out var data) ||
            data.ValueKind != JsonValueKind.Array)
        {
            errors.Add("invalid_payload: data missing");
            return (events, errors);
        }

        foreach (var item in data.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var target = item.TryGetProperty("target", out var targetEl) ? targetEl.GetString() ?? "" : "";
            var code = NormalizeCode(target);
            var name = "";
            if (item.TryGetProperty("stock_abnormal_event_data", out var stockEl) &&
                stockEl.ValueKind == JsonValueKind.Object &&
                stockEl.TryGetProperty("name", out var nameEl))
            {
                name = nameEl.GetString() ?? "";
            }
            if (!item.TryGetProperty("event_type", out var typeEl) || !int.TryParse(typeEl.ToString(), out var eventType))
            {
                errors.Add($"event_missing_type: {target}");
                continue;
            }
            if (code.Length == 0)
            {
                // 板块类事件（plate_*）或无法归一到个股的事件：跳过但不告警，属上游正常类别
                continue;
            }
            if (!item.TryGetProperty("event_timestamp", out var tsEl) || !long.TryParse(tsEl.ToString(), out var ts))
            {
                errors.Add($"event_missing_timestamp: {target}");
                continue;
            }
            var eventTime = DateTimeOffset.FromUnixTimeSeconds(ts);
            events.Add((code, name, eventType, eventTime));
        }
        return (events, errors);
    }

    /// <summary>"002919.SZ" → "002919"；无法归一返回空串。</summary>
    public static string NormalizeCode(string target)
    {
        var text = (target ?? "").Trim().ToUpperInvariant();
        if (text.EndsWith(".SZ", StringComparison.Ordinal) || text.EndsWith(".SH", StringComparison.Ordinal) ||
            text.EndsWith(".BJ", StringComparison.Ordinal))
        {
            text = text[..^3];
        }
        return text.Length == 6 && text.All(char.IsDigit) ? text : "";
    }
}
