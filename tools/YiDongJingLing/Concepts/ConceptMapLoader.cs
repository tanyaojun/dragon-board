using System.Text.Json;
using YiDongJingLing.Blocks;

namespace YiDongJingLing.Concepts;

/// <summary>板块归属映射：板块 → 成员代码 + 反向索引。失败可见：Errors 携带全部降级原因。</summary>
public sealed record ConceptMapResult(
    IReadOnlyDictionary<string, IReadOnlyList<string>> SectorToStocks,
    IReadOnlyDictionary<string, IReadOnlyList<string>> StockToSectors,
    DateTimeOffset? FetchedAt,
    bool Stale,
    IReadOnlyList<string> Errors)
{
    public static ConceptMapResult Empty { get; } = new(
        new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal),
        new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal),
        null,
        false,
        Array.Empty<string>());

    public IReadOnlyList<string> SectorsOf(string code)
    {
        return StockToSectors.TryGetValue(code, out var sectors) ? sectors : Array.Empty<string>();
    }
}

public sealed record ConceptSector(string Code, string Name, decimal? ChangePct, IReadOnlyList<string> Stocks);

public sealed class ConceptMapLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _client;
    private readonly string _cachePath;
    private readonly Action<string>? _log;
    private readonly int _maxAttempts;
    private readonly TimeSpan _retryDelay;

    public ConceptMapLoader(HttpClient? client = null, string? cachePath = null, Action<string>? log = null,
        int maxAttempts = 13, double retryDelaySeconds = 15)
    {
        _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "DragonBoard",
            "YiDongJingLing");
        Directory.CreateDirectory(dir);
        _cachePath = cachePath ?? Path.Combine(dir, "concept-map-cache.json");
        _log = log;
        _maxAttempts = Math.Max(1, maxAttempts);
        _retryDelay = TimeSpan.FromSeconds(Math.Max(0, retryDelaySeconds));
    }

    /// <summary>
    /// 拉取 /api/concepts/map 并与 .blk 自定义板块合并（同名板块以 blk 覆盖服务器概念）。
    /// 服务器失败时回退本地缓存（标记 stale）；缓存也没有则抛出，由调用方记录并沿用旧映射。
    /// </summary>
    public async Task<ConceptMapResult> LoadAsync(
        Uri proxyBaseUri,
        IEnumerable<KeyValuePair<string, IReadOnlyList<string>>> blkSectors,
        CancellationToken cancellationToken = default)
    {
        var errors = new List<string>();
        IReadOnlyList<ConceptSector> sectors = Array.Empty<ConceptSector>();
        DateTimeOffset? fetchedAt = null;
        var stale = false;

        // 服务端首刷需 1-2 分钟（506 板块成分），以 refreshing 标记后台进行中：
        // 这里轮询等待（15s×12≈3 分钟上限），等待期间 .blk 板块维度已可独立工作
        for (var attempt = 1; attempt <= _maxAttempts; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(proxyBaseUri, "/api/concepts/map"));
                using var response = await _client.SendAsync(request, cancellationToken);
                response.EnsureSuccessStatusCode();
                await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                (sectors, var serverErrors, fetchedAt, stale, var refreshing) = ParseResponse(document.RootElement);
                errors.Clear();
                errors.AddRange(serverErrors);
                var retryable = refreshing || errors.Any(item => item.StartsWith("invalid_payload", StringComparison.Ordinal));
                if (!retryable)
                {
                    SaveCache(document.RootElement);
                    break;
                }
                _log?.Invoke($"概念映射后台刷新中（查询 {attempt}/{_maxAttempts}）…");
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                errors.Clear();
                errors.Add($"server_unavailable: {ex.Message}");
                _log?.Invoke($"概念映射请求失败（{attempt}/{_maxAttempts}）: {ex.Message}");
            }
            if (attempt < _maxAttempts)
            {
                await Task.Delay(_retryDelay, cancellationToken);
            }
        }

        if (sectors.Count == 0)
        {
            var cached = LoadCache();
            if (cached is not null)
            {
                (sectors, var cacheErrors, fetchedAt, _, _) = cached.Value;
                stale = true;
                errors.Add("serving_local_cache");
                errors.AddRange(cacheErrors);
                _log?.Invoke("概念映射服务不可用，已回退本地缓存。");
            }
        }

        return BuildResult(sectors, blkSectors, fetchedAt, stale, errors);
    }

    public static ConceptMapResult BuildResult(
        IReadOnlyList<ConceptSector> sectors,
        IEnumerable<KeyValuePair<string, IReadOnlyList<string>>> blkSectors,
        DateTimeOffset? fetchedAt,
        bool stale,
        IReadOnlyList<string> errors)
    {
        var sectorToStocks = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        var stockToSectors = new Dictionary<string, List<string>>(StringComparer.Ordinal);

        // 先完成正向表（blk 同名覆盖服务器概念），再从最终正向表统一构建反向索引，
        // 避免覆盖后反向索引残留服务器旧成员。
        void AddSector(string name, IEnumerable<string> codes)
        {
            var key = name.Trim();
            if (key.Length == 0) return;
            sectorToStocks[key] = codes
                .Where(code => BlockFileParser.IsLikelyAshareCode(code))
                .Distinct(StringComparer.Ordinal)
                .ToArray();
        }

        foreach (var sector in sectors)
        {
            AddSector(sector.Name, sector.Stocks);
        }
        foreach (var pair in blkSectors)
        {
            AddSector(pair.Key, pair.Value);
        }

        foreach (var pair in sectorToStocks)
        {
            foreach (var code in pair.Value)
            {
                if (!stockToSectors.TryGetValue(code, out var list))
                {
                    list = new List<string>();
                    stockToSectors[code] = list;
                }
                list.Add(pair.Key);
            }
        }

        var frozenStockToSectors = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (var pair in stockToSectors)
        {
            frozenStockToSectors[pair.Key] = pair.Value;
        }

        return new ConceptMapResult(sectorToStocks, frozenStockToSectors, fetchedAt, stale, errors);
    }

    /// <summary>解析 /api/concepts/map 响应。无有效成员的板块计入 errors，不静默丢弃。</summary>
    public static (IReadOnlyList<ConceptSector> Sectors, IReadOnlyList<string> Errors, DateTimeOffset? FetchedAt, bool Stale, bool Refreshing)
        ParseResponse(JsonElement root)
    {
        var errors = new List<string>();
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("data", out var data) ||
            data.ValueKind != JsonValueKind.Array)
        {
            errors.Add("invalid_payload: data missing");
            return (Array.Empty<ConceptSector>(), errors, null, false, false);
        }

        DateTimeOffset? fetchedAt = null;
        if (root.TryGetProperty("fetchedAt", out var fetchedEl) &&
            fetchedEl.ValueKind == JsonValueKind.String &&
            DateTimeOffset.TryParse(fetchedEl.GetString(), out var parsed))
        {
            fetchedAt = parsed;
        }
        var stale = root.TryGetProperty("stale", out var staleEl) && staleEl.ValueKind == JsonValueKind.True;
        var refreshing = root.TryGetProperty("refreshing", out var refreshingEl) && refreshingEl.ValueKind == JsonValueKind.True;

        if (root.TryGetProperty("errors", out var serverErrorsEl) && serverErrorsEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in serverErrorsEl.EnumerateArray())
            {
                var text = item.ValueKind == JsonValueKind.String ? item.GetString() : item.ToString();
                if (!string.IsNullOrWhiteSpace(text)) errors.Add(text);
            }
        }

        var sectors = new List<ConceptSector>();
        foreach (var item in data.EnumerateArray())
        {
            var name = item.TryGetProperty("name", out var nameEl) ? nameEl.GetString()?.Trim() ?? "" : "";
            var code = item.TryGetProperty("code", out var codeEl) ? codeEl.GetString()?.Trim() ?? "" : "";
            if (name.Length == 0 && code.Length == 0) continue;
            if (name.Length == 0) name = code;

            var stocks = new List<string>();
            if (item.TryGetProperty("stocks", out var stocksEl) && stocksEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var stockEl in stocksEl.EnumerateArray())
                {
                    string rawCode;
                    if (stockEl.ValueKind == JsonValueKind.Array && stockEl.GetArrayLength() >= 1)
                    {
                        rawCode = stockEl[0].ToString();
                    }
                    else if (stockEl.ValueKind == JsonValueKind.String)
                    {
                        rawCode = stockEl.GetString() ?? "";
                    }
                    else if (stockEl.ValueKind == JsonValueKind.Object &&
                             stockEl.TryGetProperty("code", out var codeProp))
                    {
                        rawCode = codeProp.ToString();
                    }
                    else
                    {
                        continue;
                    }

                    var digits = new string(rawCode.Where(char.IsDigit).ToArray());
                    if (digits.Length == 7 && digits[0] is '0' or '1' or '3')
                    {
                        digits = digits[1..];
                    }
                    if (digits.Length > 0 && BlockFileParser.IsLikelyAshareCode(digits))
                    {
                        stocks.Add(digits);
                    }
                }
            }

            if (stocks.Count == 0)
            {
                errors.Add($"{code} {name}: no_valid_members");
                continue;
            }
            sectors.Add(new ConceptSector(code, name, null, stocks));
        }

        return (sectors, errors, fetchedAt, stale, refreshing);
    }

    private void SaveCache(JsonElement root)
    {
        try
        {
            File.WriteAllText(_cachePath, root.GetRawText());
        }
        catch (Exception ex)
        {
            _log?.Invoke($"概念映射缓存写入失败: {ex.Message}");
        }
    }

    private (IReadOnlyList<ConceptSector> Sectors, IReadOnlyList<string> Errors, DateTimeOffset? FetchedAt, bool Stale, bool Refreshing)? LoadCache()
    {
        try
        {
            if (!File.Exists(_cachePath)) return null;
            using var document = JsonDocument.Parse(File.ReadAllText(_cachePath));
            return ParseResponse(document.RootElement);
        }
        catch (Exception ex)
        {
            _log?.Invoke($"概念映射缓存读取失败: {ex.Message}");
            return null;
        }
    }
}
