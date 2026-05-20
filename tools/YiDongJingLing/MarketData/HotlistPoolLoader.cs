using System.Text.Json;
using YiDongJingLing.Blocks;

namespace YiDongJingLing.MarketData;

public sealed record HotlistStock(string Code, string Name, string Source);

public sealed record HotlistPoolResult(IReadOnlyList<HotlistStock> Stocks, IReadOnlyList<string> Errors)
{
    public IReadOnlyList<string> Codes => Stocks.Select(stock => stock.Code).Distinct(StringComparer.Ordinal).ToArray();
}

public sealed class HotlistPoolLoader
{
    private static readonly PlatformEndpoint[] Platforms =
    [
        new("eastmoney", HttpMethod.Post, "/api/eastmoney/hot", "{}"),
        new("ths", HttpMethod.Get, "/api/ths/hot"),
        new("kpl", HttpMethod.Get, "/api/kpl/hot"),
        new("tdx", HttpMethod.Post, "/api/tdx/hot", """[{"listType":"0","cycle":"0"}]"""),
        new("xueqiu", HttpMethod.Get, "/api/xueqiu/hot"),
        new("cls", HttpMethod.Get, "/api/cls/hot"),
        new("tgb", HttpMethod.Get, "/api/tgb/hot"),
        new("dzh", HttpMethod.Get, "/api/dzh/hot"),
    ];

    private readonly HttpClient _client;

    public HotlistPoolLoader(HttpClient? client = null)
    {
        _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
    }

    public async Task<HotlistPoolResult> LoadAsync(
        Uri baseUri,
        CancellationToken cancellationToken = default)
    {
        var stocks = new Dictionary<string, HotlistStock>(StringComparer.Ordinal);
        var errors = new List<string>();

        foreach (var platform in Platforms)
        {
            try
            {
                using var request = new HttpRequestMessage(platform.Method, new Uri(baseUri, platform.Path));
                if (platform.Body is not null)
                {
                    request.Content = new StringContent(platform.Body, System.Text.Encoding.UTF8, "application/json");
                }

                using var response = await _client.SendAsync(request, cancellationToken);
                response.EnsureSuccessStatusCode();
                await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                foreach (var stock in ExtractStocks(platform.Name, document.RootElement))
                {
                    stocks.TryAdd(stock.Code, stock);
                }
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
            {
                errors.Add($"{platform.Name}: {ex.Message}");
            }
        }

        return new HotlistPoolResult(
            stocks.Values.OrderBy(stock => stock.Code, StringComparer.Ordinal).ToArray(),
            errors);
    }

    public static IReadOnlyList<HotlistStock> ExtractStocks(string platform, JsonElement root)
    {
        var rows = platform switch
        {
            "eastmoney" => ReadArray(root, "data"),
            "ths" => ReadArray(root, "data", "stock_list"),
            "kpl" => ReadFirstArray(root, ["List", "list", "data"]),
            "tdx" => root.ValueKind == JsonValueKind.Array ? root.EnumerateArray().Skip(3).ToArray() : [],
            "xueqiu" => ReadArray(root, "data", "items"),
            "cls" => root.TryGetProperty("errno", out var errno) && errno.GetInt32() == 0
                ? ReadArray(root, "data")
                : [],
            "tgb" => ReadArray(root, "dto"),
            "dzh" => ReadArray(root, "result"),
            _ => [],
        };

        return rows
            .Select((row, index) => ExtractStock(platform, row, index))
            .Where(stock => stock is not null)
            .Select(stock => stock!)
            .ToArray();
    }

    private static HotlistStock? ExtractStock(string platform, JsonElement row, int index)
    {
        var code = "";
        var name = "";

        switch (platform)
        {
            case "eastmoney":
                code = ReadString(row, "sc");
                name = ReadString(row, "sn");
                break;
            case "ths":
                code = ReadString(row, "code");
                name = ReadString(row, "name");
                break;
            case "kpl":
                if (row.ValueKind == JsonValueKind.Array && row.GetArrayLength() >= 2)
                {
                    code = ReadString(row[0]);
                    name = ReadString(row[1]);
                }
                break;
            case "tdx":
                if (row.ValueKind == JsonValueKind.Array && row.GetArrayLength() >= 3)
                {
                    code = ReadString(row[1]);
                    name = ReadString(row[2]);
                }
                break;
            case "xueqiu":
                code = ReadString(row, "code");
                if (string.IsNullOrWhiteSpace(code)) code = ReadString(row, "symbol");
                name = ReadString(row, "name");
                break;
            case "cls":
                if (row.TryGetProperty("stock", out var stock))
                {
                    code = ReadString(stock, "StockID");
                    name = ReadString(stock, "name");
                }
                break;
            case "tgb":
                code = ReadString(row, "fullCode");
                name = ReadString(row, "stockName");
                break;
            case "dzh":
                if (row.ValueKind == JsonValueKind.Object)
                {
                    var property = row.EnumerateObject().FirstOrDefault();
                    code = property.Name;
                }
                break;
        }

        var normalized = NormalizeStockCode(code);
        if (normalized is null) return null;

        return new HotlistStock(normalized, NormalizeName(name, normalized), platform);
    }

    public static string? NormalizeStockCode(string raw)
    {
        var source = (raw ?? string.Empty).Trim().ToUpperInvariant();
        if (source.StartsWith("HK", StringComparison.Ordinal)) return null;

        var hasLetters = source.Any(char.IsAsciiLetter);
        if (hasLetters &&
            !source.StartsWith("SH", StringComparison.Ordinal) &&
            !source.StartsWith("SZ", StringComparison.Ordinal) &&
            !source.StartsWith("BJ", StringComparison.Ordinal))
        {
            return null;
        }

        var text = new string(source.Where(char.IsDigit).ToArray());
        if (text.Length != 6) return null;
        return BlockFileParser.IsLikelyAshareCode(text) ? text : null;
    }

    private static string NormalizeName(string name, string code)
    {
        var text = name.Trim();
        if (string.IsNullOrWhiteSpace(text) || text == "-" || text == code || text.All(char.IsDigit))
        {
            return "";
        }

        return text;
    }

    private static JsonElement[] ReadFirstArray(JsonElement root, IReadOnlyList<string> keys)
    {
        foreach (var key in keys)
        {
            var rows = ReadArray(root, key);
            if (rows.Length > 0) return rows;
        }

        return [];
    }

    private static JsonElement[] ReadArray(JsonElement root, params string[] path)
    {
        var current = root;
        foreach (var key in path)
        {
            if (current.ValueKind != JsonValueKind.Object || !current.TryGetProperty(key, out current))
            {
                return [];
            }
        }

        return current.ValueKind == JsonValueKind.Array ? current.EnumerateArray().ToArray() : [];
    }

    private static string ReadString(JsonElement item, string key)
    {
        return item.ValueKind == JsonValueKind.Object && item.TryGetProperty(key, out var value)
            ? ReadString(value)
            : "";
    }

    private static string ReadString(JsonElement value)
    {
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString()?.Trim() ?? "",
            JsonValueKind.Number => value.ToString(),
            _ => "",
        };
    }

    private sealed record PlatformEndpoint(string Name, HttpMethod Method, string Path, string? Body = null);
}
