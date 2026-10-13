using System.Text.Json;

namespace YiDongJingLing.MarketData;

public sealed record LimitUpStreakResult(
    IReadOnlyDictionary<string, int> Streaks,
    IReadOnlyList<string> CoveredDates,
    IReadOnlyList<string> Errors,
    DateTimeOffset LoadedAt)
{
    public static LimitUpStreakResult Empty { get; } = new(
        new Dictionary<string, int>(StringComparer.Ordinal),
        Array.Empty<string>(),
        Array.Empty<string>(),
        DateTimeOffset.MinValue);
}

/// <summary>
/// 连板上下文加载器：拉取近几个交易日的同花顺涨停池（/api/limitup/10jqka?date=），
/// 自算每只股票"截至上一交易日的连续涨停天数"（0 = 昨日未涨停）。
/// 局限可见：候选日按自然日回溯并跳过周末，法定假日会提前终止连板计数（记入 errors）。
/// </summary>
public sealed class LimitUpStreakLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    private readonly HttpClient _client;
    private readonly string _cacheDir;
    private readonly Func<DateTimeOffset> _now;
    private readonly Action<string>? _log;
    private const int MaxLookbackDays = 8;

    public LimitUpStreakLoader(HttpClient? client = null, string? cacheDir = null, Func<DateTimeOffset>? now = null, Action<string>? log = null)
    {
        _client = client ?? new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        _cacheDir = cacheDir ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "DragonBoard",
            "YiDongJingLing");
        _now = now ?? (() => DateTimeOffset.Now);
        _log = log;
    }

    public async Task<LimitUpStreakResult> LoadAsync(Uri proxyBaseUri, CancellationToken cancellationToken = default)
    {
        var today = _now().ToLocalTime();
        var cachePath = Path.Combine(_cacheDir, $"limitup-streaks-{today:yyyy-MM-dd}.json");
        var cached = LoadCache(cachePath, today);
        if (cached is not null) return cached;

        var errors = new List<string>();
        var coveredDates = new List<string>();
        var perDateCodes = new List<HashSet<string>>();

        // 候选日：今天在前，跳过周末；today 当天数据仅用于确认交易日序列，不参与 streak 基准。
        var candidates = new List<DateTime>();
        var cursor = today.Date;
        while (candidates.Count < MaxLookbackDays)
        {
            if (cursor.DayOfWeek is not (DayOfWeek.Saturday or DayOfWeek.Sunday))
            {
                candidates.Add(cursor);
            }
            cursor = cursor.AddDays(-1);
        }

        var isToday = true;
        foreach (var date in candidates)
        {
            var dateText = date.ToString("yyyy-MM-dd");
            IReadOnlyList<string> codes;
            try
            {
                codes = await FetchDateAsync(proxyBaseUri, dateText, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                errors.Add($"{dateText}: {ex.Message}");
                break;
            }

            if (codes.Count == 0)
            {
                // 盘前/早盘"今日池为空"是常态：跳过今日继续回溯昨日基准；
                // 非今日候选空池视为非交易日（A 股每个交易日都有涨停），序列终止并留痕。
                if (isToday)
                {
                    isToday = false;
                    continue;
                }
                errors.Add($"{dateText}: empty_pool_treated_as_non_trading_day");
                break;
            }

            coveredDates.Add(dateText);
            perDateCodes.Add(codes.ToHashSet(StringComparer.Ordinal));
            isToday = false;
        }

        // streak 基准：候选[0]=今天（数据不参与计数），其前第一个有数据日为“昨日”（连板第 1 天）。
        // 回溯下限为 baseIndex，避免今日盘中封板污染“昨日连板”。
        var streaks = new Dictionary<string, int>(StringComparer.Ordinal);
        var baseIndex = coveredDates.Count > 0 && coveredDates[0] == today.ToString("yyyy-MM-dd") ? 1 : 0;
        for (var dayIndex = baseIndex; dayIndex < perDateCodes.Count; dayIndex++)
        {
            foreach (var code in perDateCodes[dayIndex])
            {
                var streak = 1;
                for (var back = dayIndex - 1; back >= baseIndex; back--)
                {
                    if (perDateCodes[back].Contains(code)) streak++;
                    else break;
                }
                streaks[code] = Math.Max(streaks.GetValueOrDefault(code), streak);
            }
        }
        var result = new LimitUpStreakResult(streaks, coveredDates, errors, _now());
        // 空结果（上游异常/基准日缺失）不落缓存，避免当日固化失效数据
        if (streaks.Count > 0)
        {
            SaveCache(cachePath, result);
        }
        return result;
    }

    private async Task<IReadOnlyList<string>> FetchDateAsync(Uri proxyBaseUri, string dateText, CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get,
            new Uri(proxyBaseUri, $"/api/limitup/10jqka?date={Uri.EscapeDataString(dateText)}"));
        using var response = await _client.SendAsync(request, cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken).ConfigureAwait(false);
        return ParseDateResponse(document.RootElement);
    }

    public static IReadOnlyList<string> ParseDateResponse(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("data", out var data) ||
            data.ValueKind != JsonValueKind.Object || !data.TryGetProperty("info", out var info) ||
            info.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<string>();
        }

        var codes = new List<string>();
        foreach (var item in info.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty("code", out var codeEl))
            {
                continue;
            }
            var code = codeEl.ToString()?.Trim() ?? "";
            if (code.Length == 6 && code.All(char.IsDigit))
            {
                codes.Add(code);
            }
        }
        return codes;
    }

    private LimitUpStreakResult? LoadCache(string cachePath, DateTimeOffset today)
    {
        try
        {
            if (!File.Exists(cachePath)) return null;
            using var document = JsonDocument.Parse(File.ReadAllText(cachePath));
            var root = document.RootElement;
            if (!root.TryGetProperty("loadedAt", out var loadedEl) ||
                !DateTimeOffset.TryParse(loadedEl.GetString(), out var loadedAt) ||
                loadedAt.ToLocalTime().Date != today.Date)
            {
                return null;
            }

            var streaks = new Dictionary<string, int>(StringComparer.Ordinal);
            if (root.TryGetProperty("streaks", out var streaksEl) && streaksEl.ValueKind == JsonValueKind.Object)
            {
                foreach (var pair in streaksEl.EnumerateObject())
                {
                    streaks[pair.Name] = pair.Value.GetInt32();
                }
            }
            var errors = ReadStrings(root, "errors");
            var dates = ReadStrings(root, "coveredDates");
            return new LimitUpStreakResult(streaks, dates, errors, loadedAt);
        }
        catch (Exception ex)
        {
            _log?.Invoke($"连板缓存读取失败: {ex.Message}");
            return null;
        }
    }

    private void SaveCache(string cachePath, LimitUpStreakResult result)
    {
        try
        {
            Directory.CreateDirectory(_cacheDir);
            var payload = new
            {
                loadedAt = result.LoadedAt.ToString("O"),
                coveredDates = result.CoveredDates,
                errors = result.Errors,
                streaks = result.Streaks,
            };
            File.WriteAllText(cachePath, JsonSerializer.Serialize(payload, JsonOptions));
        }
        catch (Exception ex)
        {
            _log?.Invoke($"连板缓存写入失败: {ex.Message}");
        }
    }

    private static IReadOnlyList<string> ReadStrings(JsonElement root, string property)
    {
        if (!root.TryGetProperty(property, out var el) || el.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<string>();
        }
        return el.EnumerateArray()
            .Select(item => item.ToString())
            .Where(text => !string.IsNullOrWhiteSpace(text))
            .Cast<string>()
            .ToArray();
    }
}
