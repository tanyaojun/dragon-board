using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace TdxL2Helper;

/// <summary>
/// 实验性深度行情内存扫描器。从正在运行的 tdxw.exe 进程中查找疑似十档订单簿结构。
/// </summary>
internal static class L2DepthReader
{
    private const uint ProcessVmRead = 0x0010;
    private const uint ProcessQueryInformation = 0x0400;
    private const uint ProcessQueryLimitedInformation = 0x1000;
    private const uint MemCommit = 0x1000;
    private const uint MemPrivate = 0x20000;

    private static readonly HashSet<uint> ReadableProtects = new()
    {
        0x02, 0x04, 0x06, 0x08, 0x20, 0x40, 0x80, 0x100, 0x200
    };

    // ── 扫描报告 ────────────────────────────────────────────────────

    internal sealed class ScanReport
    {
        [JsonPropertyName("ok")]
        public bool Ok { get; set; }

        [JsonPropertyName("pid")]
        public int ProcessId { get; set; }

        [JsonPropertyName("regions")]
        public int RegionsScanned { get; set; }

        [JsonPropertyName("candidates")]
        public List<DepthSlot> Candidates { get; init; } = new();

        [JsonPropertyName("cached")]
        public bool FromCache { get; set; }

        [JsonPropertyName("error")]
        public string Error { get; set; } = string.Empty;
    }

    internal sealed class DepthSlot
    {
        [JsonPropertyName("address")]
        public string Address { get; set; } = string.Empty;

        [JsonPropertyName("score")]
        public int Score { get; set; }

        [JsonPropertyName("bidPrices")]
        public List<float> BidPrices { get; init; } = new();

        [JsonPropertyName("askPrices")]
        public List<float> AskPrices { get; init; } = new();

        [JsonPropertyName("bidVolumes")]
        public List<int> BidVolumes { get; init; } = new();

        [JsonPropertyName("askVolumes")]
        public List<int> AskVolumes { get; init; } = new();

        [JsonPropertyName("codeHint")]
        public string CodeHint { get; set; } = string.Empty;

        [JsonPropertyName("nameHint")]
        public string NameHint { get; set; } = string.Empty;
    }

    internal sealed class DepthSnapshot
    {
        [JsonPropertyName("ts")]
        public long Timestamp { get; set; }

        [JsonPropertyName("addr")]
        public string Address { get; set; } = string.Empty;

        [JsonPropertyName("code")]
        public string Code { get; set; } = string.Empty;

        [JsonPropertyName("bids")]
        public List<Level> Bids { get; init; } = new();

        [JsonPropertyName("asks")]
        public List<Level> Asks { get; init; } = new();
    }

    internal sealed class Level
    {
        [JsonPropertyName("p")]
        public float Price { get; set; }

        [JsonPropertyName("v")]
        public int Volume { get; set; }
    }

    // ── 查找进程 ──────────────────────────────────────────────────────

    internal static Process? FindTdxProcess(string tdxRoot)
    {
        var expectedPath = Path.GetFullPath(Path.Combine(tdxRoot, "tdxw.exe"));
        var candidates = new List<(Process Process, string Path, bool Matches)>();

        foreach (var process in Process.GetProcessesByName("tdxw"))
        {
            try
            {
                var path = process.MainModule?.FileName ?? string.Empty;
                candidates.Add((
                    process,
                    path,
                    string.Equals(Path.GetFullPath(path), expectedPath, StringComparison.OrdinalIgnoreCase)));
            }
            catch
            {
                process.Dispose();
            }
        }

        var best = candidates
            .OrderByDescending(c => c.Matches)
            .ThenByDescending(c =>
            {
                try { return c.Process.StartTime; }
                catch { return DateTime.MinValue; }
            })
            .FirstOrDefault();

        // Dispose non-selected processes
        foreach (var (process, _, _) in candidates)
        {
            if (process != best.Process)
            {
                process.Dispose();
            }
        }

        return best.Process ?? null;
    }

    // ── 内存工具 ───────────────────────────────────────────────────────

    public sealed class ProcessMemoryReader : IDisposable
    {
        private readonly IntPtr handle;
        private bool disposed;

        public ProcessMemoryReader(int pid)
        {
            handle = NativeMethods.OpenProcess(
                ProcessVmRead | ProcessQueryInformation | ProcessQueryLimitedInformation,
                false,
                pid);
            if (handle == IntPtr.Zero)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }

        public bool TryReadBytes(int address, int size, out byte[] bytes)
        {
            bytes = Array.Empty<byte>();
            var buffer = new byte[size];
            if (!NativeMethods.ReadProcessMemory(handle, new IntPtr(address), buffer, size, out var bytesRead) || bytesRead <= 0)
            {
                return false;
            }

            bytes = buffer.Take(bytesRead).ToArray();
            return true;
        }

        public float ReadFloat(int address)
        {
            if (TryReadBytes(address, 4, out var bytes) && bytes.Length >= 4)
            {
                return BitConverter.ToSingle(bytes, 0);
            }

            return float.NaN;
        }

        public int ReadInt32(int address)
        {
            if (TryReadBytes(address, 4, out var bytes) && bytes.Length >= 4)
            {
                return BitConverter.ToInt32(bytes, 0);
            }

            return 0;
        }

        public List<MemoryRegion> EnumerateRegions()
        {
            var regions = new List<MemoryRegion>();
            var address = IntPtr.Zero;
            var structSize = Marshal.SizeOf<NativeMethods.MEMORY_BASIC_INFORMATION>();
            while (true)
            {
                var mbi = new NativeMethods.MEMORY_BASIC_INFORMATION();
                var result = NativeMethods.VirtualQueryEx(handle, address, ref mbi, structSize);
                if (result == 0)
                {
                    break;
                }

                if (mbi.State == MemCommit && mbi.Type == MemPrivate && ReadableProtects.Contains(mbi.Protect))
                {
                    var baseAddr = mbi.BaseAddress;
                    var regionSize = mbi.RegionSize.ToUInt32();
                    if (baseAddr != IntPtr.Zero && regionSize > 0 && regionSize < 512U * 1024 * 1024)
                    {
                        regions.Add(new MemoryRegion
                        {
                            Base = baseAddr.ToInt32(),
                            Size = (int)regionSize,
                        });
                    }
                }

                address = IntPtr.Add(mbi.BaseAddress, (int)mbi.RegionSize.ToUInt32());
                if (address == IntPtr.Zero)
                {
                    break;
                }
            }

            return regions;
        }

        public void Dispose()
        {
            if (!disposed && handle != IntPtr.Zero)
            {
                disposed = true;
                NativeMethods.CloseHandle(handle);
            }
        }
    }

    internal sealed class MemoryRegion
    {
        public int Base { get; init; }
        public int Size { get; init; }
    }

    // ── 深度数据扫描 ────────────────────────────────────────────────────

    private static bool IsValidPrice(float val)
    {
        return float.IsFinite(val) && val > 0.01f && val < 10000f;
    }

    private static bool IsMonotonic(List<float> values, bool descending)
    {
        for (var i = 1; i < values.Count; i++)
        {
            if (descending && values[i] > values[i - 1])
            {
                return false;
            }

            if (!descending && values[i] < values[i - 1])
            {
                return false;
            }
        }

        return true;
    }

    private static int ScoreDepth(ReadOnlySpan<float> prices)
    {
        if (prices.Length < 20)
        {
            return 0;
        }

        var bids = new List<float>();
        var asks = new List<float>();
        for (var i = 0; i < 10; i++)
        {
            if (IsValidPrice(prices[i]))
            {
                bids.Add(prices[i]);
            }
        }

        for (var i = 10; i < 20; i++)
        {
            if (IsValidPrice(prices[i]))
            {
                asks.Add(prices[i]);
            }
        }

        if (bids.Count < 3 || asks.Count < 3)
        {
            return 0;
        }

        var score = 0;
        if (IsMonotonic(bids, true))
        {
            score += bids.Count * 3;
        }

        if (IsMonotonic(asks, false))
        {
            score += asks.Count * 3;
        }

        if (bids[0] < asks[0] && bids[^1] < asks[^1] && bids[0] < asks[^1])
        {
            score += 8;
        }

        if (bids.Count >= 5 && asks.Count >= 5)
        {
            score += 4;
        }

        return score;
    }

    private static DepthSlot? TryParseDepthSlot(int address, byte[] data, int offset = 0)
    {
        if (offset + 160 > data.Length)
        {
            return null;
        }

        var floats = new float[40];
        for (var i = 0; i < 40; i++)
        {
            floats[i] = BitConverter.ToSingle(data, offset + i * 4);
        }

        var score = ScoreDepth(floats.AsSpan());
        if (score < 15)
        {
            return null;
        }

        var bids = new List<float>();
        var asks = new List<float>();
        var bidVols = new List<int>();
        var askVols = new List<int>();

        for (var i = 0; i < 10; i++)
        {
            if (IsValidPrice(floats[i]))
            {
                bids.Add(floats[i]);
            }
        }

        for (var i = 10; i < 20; i++)
        {
            if (IsValidPrice(floats[i]))
            {
                asks.Add(floats[i]);
            }
        }

        // Try reading volumes from floats[20..40] or next 40 floats as ints
        for (var i = 20; i < 30; i++)
        {
            if (floats[i] > 0 && floats[i] < 1_000_000_000)
            {
                bidVols.Add((int)floats[i]);
            }
        }

        for (var i = 30; i < 40; i++)
        {
            if (floats[i] > 0 && floats[i] < 1_000_000_000)
            {
                askVols.Add((int)floats[i]);
            }
        }

        return new DepthSlot
        {
            Address = ToHex(address + offset),
            Score = score,
            BidPrices = bids,
            AskPrices = asks,
            BidVolumes = bidVols,
            AskVolumes = askVols,
        };
    }

    private static List<DepthSlot> ScanRegion(ProcessMemoryReader reader, MemoryRegion region)
    {
        var candidates = new List<DepthSlot>();
        var scanSize = Math.Min(region.Size, 8 * 1024 * 1024); // 最多扫 8MB
        byte[] data;
        try
        {
            if (!reader.TryReadBytes(region.Base, scanSize, out data) || data.Length < 160)
            {
                return candidates;
            }
        }
        catch
        {
            return candidates;
        }

        // 扫描所有 4 字节对齐位置
        for (var i = 0; i < data.Length - 160; i += 4)
        {
            var slot = TryParseDepthSlot(region.Base, data, i);
            if (slot is not null)
            {
                candidates.Add(slot);
                i += 40; // 跳过已匹配区域加速扫描
            }
        }

        // 去重：相近地址只保留最高分
        candidates.Sort((a, b) => b.Score.CompareTo(a.Score));
        var unique = new List<DepthSlot>();
        foreach (var candidate in candidates)
        {
            if (!unique.Any(u => Math.Abs(ParseHex(u.Address) - ParseHex(candidate.Address)) < 16))
            {
                unique.Add(candidate);
                if (unique.Count >= 100)
                {
                    break;
                }
            }
        }

        return unique;
    }

    // ── 盘口读取 ────────────────────────────────────────────────────────

    internal static DepthSnapshot? ReadDepth(ProcessMemoryReader reader, int address)
    {
        if (!reader.TryReadBytes(address, 160, out var data) || data.Length < 160)
        {
            return null;
        }

        var floats = new float[40];
        for (var i = 0; i < 40; i++)
        {
            floats[i] = BitConverter.ToSingle(data, i * 4);
        }

        var bids = new List<Level>();
        var asks = new List<Level>();

        for (var i = 0; i < 10 && i < 20; i++)
        {
            if (IsValidPrice(floats[i]))
            {
                var vol = i + 20 < 40 && floats[i + 20] > 0 ? (int)floats[i + 20] : 0;
                bids.Add(new Level { Price = (float)Math.Round(floats[i], 2), Volume = vol });
            }
        }

        for (var i = 10; i < 20 && i < 20; i++)
        {
            if (IsValidPrice(floats[i]))
            {
                var vol = i + 20 < 40 && floats[i + 20] > 0 ? (int)floats[i + 20] : 0;
                asks.Add(new Level { Price = (float)Math.Round(floats[i], 2), Volume = vol });
            }
        }

        if (bids.Count == 0 || asks.Count == 0)
        {
            return null;
        }

        return new DepthSnapshot
        {
            Timestamp = DateTimeOffset.Now.ToUnixTimeMilliseconds(),
            Address = ToHex(address),
            Bids = bids,
            Asks = asks,
        };
    }

    // ── 扫描入口 ────────────────────────────────────────────────────────

    internal static ScanReport Scan(int pid)
    {
        var report = new ScanReport { ProcessId = pid };
        using var reader = new ProcessMemoryReader(pid);
        var regions = reader.EnumerateRegions();
        var heapRegions = regions
            .Where(r => r.Size > 256 * 1024)
            .OrderByDescending(r => r.Size)
            .ToList();

        report.RegionsScanned = heapRegions.Count;
        var scanned = 0;
        foreach (var region in heapRegions)
        {
            scanned++;
            var regionCandidates = ScanRegion(reader, region);
            // Take top 2 from each large region
            report.Candidates.AddRange(regionCandidates.Take(2));
        }

        var sortedCandidates = report.Candidates
            .OrderByDescending(c => c.Score)
            .Take(50)
            .ToList();
        report.Candidates.Clear();
        report.Candidates.AddRange(sortedCandidates);

        report.Ok = report.Candidates.Count > 0;
        if (!report.Ok)
        {
            report.Error = "未找到 L2 深度数据。请确保通达信客户端已打开 L2 行情面板，且当前为交易时段。";
        }

        return report;
    }

    // ── 监控循环 ────────────────────────────────────────────────────────

    internal static void Monitor(int pid, List<int> addresses, int intervalMs, string? outputPath)
    {
        using var reader = new ProcessMemoryReader(pid);
        var lastPayloads = new Dictionary<long, string>();
        TextWriter? fileWriter = null;

        try
        {
            if (outputPath is not null)
            {
                fileWriter = new StreamWriter(outputPath, append: true, Encoding.UTF8) { AutoFlush = true };
            }

            var output = fileWriter ?? Console.Out;

            while (true)
            {
                var cycleStarted = Stopwatch.GetTimestamp();

                foreach (var addr in addresses)
                {
                    var snapshot = ReadDepth(reader, addr);
                    if (snapshot is null)
                    {
                        continue;
                    }

                    var payload = JsonSerializer.Serialize(snapshot, JsonOptions.Compact);
                    if (lastPayloads.TryGetValue(addr, out var last) && last == payload)
                    {
                        continue;
                    }

                    lastPayloads[addr] = payload;
                    output.WriteLine(payload);
                }

                var elapsed = (Stopwatch.GetTimestamp() - cycleStarted) / (double)Stopwatch.Frequency * 1000.0;
                var sleep = Math.Max(50, intervalMs - (int)elapsed);
                Thread.Sleep(sleep);
            }
        }
        finally
        {
            fileWriter?.Dispose();
        }
    }

    // ── 地址缓存 ────────────────────────────────────────────────────────

    private static string CacheDir =>
        Path.Combine(
            Path.GetDirectoryName(Environment.ProcessPath) ?? Directory.GetCurrentDirectory(),
            ".tdx_l2_cache");

    internal static void SaveAddressCache(string tdxRoot, List<int> addresses)
    {
        Directory.CreateDirectory(CacheDir);
        var path = Path.Combine(CacheDir, "addresses.json");
        var data = new
        {
            tdxRoot = Path.GetFullPath(tdxRoot),
            addresses = addresses.Select(ToHex).ToList(),
            ts = DateTimeOffset.Now.ToUnixTimeSeconds(),
        };
        File.WriteAllText(path, JsonSerializer.Serialize(data, JsonOptions.Default));
    }

    internal static List<int>? LoadAddressCache(string tdxRoot)
    {
        var path = Path.Combine(CacheDir, "addresses.json");
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var root = doc.RootElement;
            if (root.TryGetProperty("tdxRoot", out var cachedRoot)
                && !string.Equals(cachedRoot.GetString(), Path.GetFullPath(tdxRoot), StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            if (root.TryGetProperty("addresses", out var addrs))
            {
                var list = new List<int>();
                foreach (var addr in addrs.EnumerateArray())
                {
                    list.Add(ParseHex(addr.GetString() ?? "0"));
                }

                return list;
            }
        }
        catch (IOException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
        catch (FormatException)
        {
            return null;
        }

        return null;
    }

    // ── 辅助 ──────────────────────────────────────────────────────────

    private static string ToHex(int value) => $"0x{value:X}";

    public static int ParseHex(string value)
    {
        if (value.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
        {
            value = value[2..];
        }

        return int.Parse(value, System.Globalization.NumberStyles.HexNumber);
    }

    internal static bool TryFindStockCodeHint(ProcessMemoryReader reader, int addr, out string code, out string name)
    {
        code = string.Empty;
        name = string.Empty;
        // 尝试在地址前 64 字节范围内查找 6 位数字代码
        var searchStart = Math.Max(0, addr - 64);
        if (reader.TryReadBytes(searchStart, (int)(addr - searchStart + 32), out var data))
        {
            var text = Encoding.ASCII.GetString(data);
            // 查找 6 位数字
            for (var i = 0; i <= text.Length - 6; i++)
            {
                if (text[i] >= '0' && text[i] <= '9'
                    && text[i + 1] >= '0' && text[i + 1] <= '9'
                    && text[i + 2] >= '0' && text[i + 2] <= '9'
                    && text[i + 3] >= '0' && text[i + 3] <= '9'
                    && text[i + 4] >= '0' && text[i + 4] <= '9'
                    && text[i + 5] >= '0' && text[i + 5] <= '9')
                {
                    // 检查边界（不在另一个数字中间）
                    var before = i > 0 ? text[i - 1] : ' ';
                    var after = i + 6 < text.Length ? text[i + 6] : ' ';
                    if (!char.IsDigit(before) && !char.IsDigit(after))
                    {
                        code = text.Substring(i, 6);
                        break;
                    }
                }
            }

            // 尝试 GB18030 解码找股票名称
            var gbkText = Encoding.GetEncoding("GB18030").GetString(data);
            if (!string.IsNullOrWhiteSpace(gbkText) && gbkText.Length < 32)
            {
                name = gbkText.Trim('\0', ' ');
            }
        }

        return !string.IsNullOrEmpty(code);
    }
}
