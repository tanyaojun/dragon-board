using System.Text;

namespace YiDongJingLing.MarketData;

public sealed class StockNameResolver
{
    private const int TnfRecordSize = 0x168;
    private const int TnfFirstRecordOffset = 0x32;
    private const int TnfNameOffset = 0x1f;

    private readonly Dictionary<string, string> _names = new(StringComparer.Ordinal);
    private string _loadedRoot = "";

    public void LoadFromBlockDirectory(string blockDirectory)
    {
        var root = ResolveTdxRoot(blockDirectory);
        if (string.IsNullOrWhiteSpace(root) || string.Equals(root, _loadedRoot, StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        _names.Clear();
        _loadedRoot = root;
        var hqCache = Path.Combine(root, "T0002", "hq_cache");
        LoadTnf(Path.Combine(hqCache, "shs.tnf"));
        LoadTnf(Path.Combine(hqCache, "szs.tnf"));
        LoadTnf(Path.Combine(hqCache, "bjs.tnf"));
    }

    public string Resolve(string code, string fallback = "")
    {
        if (_names.TryGetValue(code, out var name))
        {
            return name;
        }

        var fallbackName = fallback.Trim();
        if (IsValidFallbackName(code, fallbackName))
        {
            _names[code] = fallbackName;
            return fallbackName;
        }

        return "";
    }

    private static string ResolveTdxRoot(string blockDirectory)
    {
        var dir = new DirectoryInfo(blockDirectory);
        while (dir is not null)
        {
            if (dir.Name.Equals("TDX", StringComparison.OrdinalIgnoreCase) ||
                Directory.Exists(Path.Combine(dir.FullName, "T0002", "hq_cache")))
            {
                return dir.FullName;
            }

            dir = dir.Parent;
        }

        return "";
    }

    private void LoadTnf(string path)
    {
        if (!File.Exists(path)) return;

        var bytes = File.ReadAllBytes(path);
        for (var offset = TnfFirstRecordOffset; offset + TnfRecordSize <= bytes.Length; offset += TnfRecordSize)
        {
            var code = ReadAscii(bytes, offset, 6);
            if (code.Length != 6 || !code.All(char.IsDigit)) continue;

            var name = ReadGbk(bytes, offset + TnfNameOffset, 32);
            if (!string.IsNullOrWhiteSpace(name))
            {
                _names[code] = name;
            }
        }
    }

    private static bool IsValidFallbackName(string code, string fallback)
    {
        if (string.IsNullOrWhiteSpace(fallback)) return false;
        if (string.Equals(code, fallback, StringComparison.Ordinal)) return false;
        if (fallback.All(char.IsDigit)) return false;
        if (decimal.TryParse(fallback, out _)) return false;
        return true;
    }

    public static byte[] BuildTnfRecordForTest(string code, string name)
    {
        var record = new byte[TnfRecordSize];
        Encoding.ASCII.GetBytes(code).CopyTo(record, 0);
        Encoding.GetEncoding("GB18030").GetBytes(name).CopyTo(record, TnfNameOffset);
        return record;
    }

    private static string ReadAscii(byte[] bytes, int offset, int maxLength)
    {
        var length = 0;
        while (length < maxLength && offset + length < bytes.Length && bytes[offset + length] != 0)
        {
            length++;
        }

        return Encoding.ASCII.GetString(bytes, offset, length).Trim();
    }

    private static string ReadGbk(byte[] bytes, int offset, int maxLength)
    {
        var length = 0;
        while (length < maxLength && offset + length < bytes.Length && bytes[offset + length] != 0)
        {
            length++;
        }

        return Encoding.GetEncoding("GB18030").GetString(bytes, offset, length).Trim();
    }
}
