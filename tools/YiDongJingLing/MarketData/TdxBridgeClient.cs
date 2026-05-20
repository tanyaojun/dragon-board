using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace YiDongJingLing.MarketData;

public sealed class TdxBridgeClient : IDisposable
{
    private readonly Uri _uri;
    private readonly SynchronizationContext? _syncContext;
    private ClientWebSocket? _socket;
    private CancellationTokenSource? _cts;
    private readonly Dictionary<string, QuoteSnapshot> _quotes = new(StringComparer.Ordinal);

    public TdxBridgeClient(string url, SynchronizationContext? syncContext = null)
    {
        _uri = new Uri(url);
        _syncContext = syncContext;
    }

    public event EventHandler<IReadOnlyList<QuoteSnapshot>>? QuotesReceived;
    public event EventHandler<string>? StatusChanged;

    public bool IsConnected => _socket?.State == WebSocketState.Open;

    public async Task ConnectAsync(IReadOnlyList<string> codes, CancellationToken cancellationToken = default)
    {
        Disconnect();
        _quotes.Clear();
        _cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _socket = new ClientWebSocket();
        RaiseStatus("正在连接行情桥...");
        await _socket.ConnectAsync(_uri, _cts.Token);
        RaiseStatus("行情桥已连接");
        await SendSubscriptionAsync(codes, _cts.Token);
        _ = Task.Run(() => ReceiveLoopAsync(_cts.Token));
    }

    public async Task SendSubscriptionAsync(IReadOnlyList<string> codes, CancellationToken cancellationToken = default)
    {
        if (_socket?.State != WebSocketState.Open) return;

        var payload = JsonSerializer.Serialize(new
        {
            type = "set_hot_pool",
            codes = codes.Distinct(StringComparer.Ordinal).ToArray(),
        });
        var bytes = Encoding.UTF8.GetBytes(payload);
        await _socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);
    }

    public void Disconnect()
    {
        try
        {
            _cts?.Cancel();
            _socket?.Dispose();
        }
        catch
        {
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            _socket = null;
        }
    }

    public void Dispose() => Disconnect();

    private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
    {
        var buffer = new byte[64 * 1024];
        var message = new MemoryStream();

        try
        {
            while (!cancellationToken.IsCancellationRequested && _socket?.State == WebSocketState.Open)
            {
                message.SetLength(0);
                WebSocketReceiveResult result;
                do
                {
                    result = await _socket.ReceiveAsync(buffer, cancellationToken);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        RaiseStatus("行情桥已关闭连接");
                        return;
                    }
                    message.Write(buffer, 0, result.Count);
                } while (!result.EndOfMessage);

                var text = Encoding.UTF8.GetString(message.ToArray());
                HandleMessage(text);
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            RaiseStatus($"行情桥断开: {ex.Message}");
        }
    }

    private void HandleMessage(string text)
    {
        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(text);
        }
        catch (JsonException ex)
        {
            RaiseStatus($"行情桥消息解析失败: {ex.Message}");
            return;
        }

        using var _ = document;
        var root = document.RootElement;
        var type = root.TryGetProperty("type", out var typeElement) ? typeElement.GetString() : "";
        var serverTime = ReadServerTime(root);
        var changed = new List<QuoteSnapshot>();

        if (type == "full_state")
        {
            var touchedCodes = new SortedSet<string>(StringComparer.Ordinal);
            if (root.TryGetProperty("quotes", out var quotes) && quotes.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in quotes.EnumerateArray())
                {
                    var quote = ParseQuote(item, serverTime);
                    if (quote is not null)
                    {
                        _quotes[quote.Code] = MergeDepth(quote);
                        touchedCodes.Add(quote.Code);
                    }
                }
            }

            if (root.TryGetProperty("depth", out var depth) && depth.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in depth.EnumerateArray())
                {
                    var updated = ApplyDepth(item, serverTime);
                    if (updated is not null)
                    {
                        touchedCodes.Add(updated.Code);
                    }
                }
            }

            changed.AddRange(touchedCodes.Select(code => _quotes[code]));
        }
        else if (type == "quote_patch")
        {
            if (root.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in items.EnumerateArray())
                {
                    var quote = ParseQuote(item, serverTime);
                    if (quote is not null)
                    {
                        _quotes[quote.Code] = MergeDepth(quote);
                        changed.Add(_quotes[quote.Code]);
                    }
                }
            }
        }
        else if (type == "depth_patch")
        {
            if (root.TryGetProperty("items", out var items) && items.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in items.EnumerateArray())
                {
                    var updated = ApplyDepth(item, serverTime);
                    if (updated is not null)
                    {
                        changed.Add(updated);
                    }
                }
            }
        }
        else if (type == "heartbeat")
        {
            RaiseStatus("行情桥：心跳正常");
        }

        if (changed.Count > 0)
        {
            RaiseQuotes(changed);
        }
    }

    private static DateTimeOffset ReadServerTime(JsonElement root)
    {
        if (root.TryGetProperty("serverTs", out var item) && item.TryGetInt64(out var ms))
        {
            return DateTimeOffset.FromUnixTimeMilliseconds(ms);
        }

        return DateTimeOffset.Now;
    }

    private QuoteSnapshot? ParseQuote(JsonElement item, DateTimeOffset sourceTime)
    {
        var code = ReadString(item, "code");
        if (string.IsNullOrWhiteSpace(code)) return null;

        return new QuoteSnapshot(
            code,
            ReadString(item, "name"),
            ReadDecimal(item, "lastPrice"),
            ReadDecimal(item, "changePct"),
            ReadDecimal(item, "changeAmount"),
            ReadDecimal(item, "volume"),
            ReadDecimal(item, "amount"),
            ReadDecimal(item, "open"),
            ReadDecimal(item, "high"),
            ReadDecimal(item, "low"),
            ReadDecimal(item, "preClose"),
            _quotes.TryGetValue(code, out var previous) ? previous.Bids : Array.Empty<QuoteLevel>(),
            _quotes.TryGetValue(code, out previous) ? previous.Asks : Array.Empty<QuoteLevel>(),
            sourceTime);
    }

    private QuoteSnapshot MergeDepth(QuoteSnapshot quote)
    {
        if (!_quotes.TryGetValue(quote.Code, out var previous)) return quote;

        return quote with
        {
            Bids = previous.Bids,
            Asks = previous.Asks,
        };
    }

    private QuoteSnapshot? ApplyDepth(JsonElement item, DateTimeOffset sourceTime)
    {
        var code = ReadString(item, "code");
        if (string.IsNullOrWhiteSpace(code) || !_quotes.TryGetValue(code, out var quote)) return null;

        var updated = quote with
        {
            Bids = ReadLevels(item, "bids"),
            Asks = ReadLevels(item, "asks"),
            SourceTime = sourceTime,
        };
        _quotes[code] = updated;
        return updated;
    }

    private static IReadOnlyList<QuoteLevel> ReadLevels(JsonElement item, string key)
    {
        if (!item.TryGetProperty(key, out var levels) || levels.ValueKind != JsonValueKind.Array)
            return Array.Empty<QuoteLevel>();

        return levels
            .EnumerateArray()
            .Select(level => new QuoteLevel(ReadDecimal(level, "price"), ReadDecimal(level, "volume")))
            .Where(level => level.Price > 0 || level.Volume > 0)
            .ToArray();
    }

    private static string ReadString(JsonElement item, string key)
    {
        if (!item.TryGetProperty(key, out var value)) return "";
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString()?.Trim() ?? "",
            JsonValueKind.Number => value.ToString(),
            _ => "",
        };
    }

    private static decimal ReadDecimal(JsonElement item, string key)
    {
        if (!item.TryGetProperty(key, out var value)) return 0m;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDecimal(out var parsed)) return parsed;
        if (value.ValueKind == JsonValueKind.String && decimal.TryParse(value.GetString(), out parsed)) return parsed;
        return 0m;
    }

    private void RaiseQuotes(IReadOnlyList<QuoteSnapshot> quotes)
    {
        if (_syncContext is null)
        {
            QuotesReceived?.Invoke(this, quotes);
            return;
        }

        _syncContext.Post(_ => QuotesReceived?.Invoke(this, quotes), null);
    }

    private void RaiseStatus(string text)
    {
        if (_syncContext is null)
        {
            StatusChanged?.Invoke(this, text);
            return;
        }

        _syncContext.Post(_ => StatusChanged?.Invoke(this, text), null);
    }
}
