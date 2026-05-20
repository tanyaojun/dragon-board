using System.Text;

namespace YiDongJingLing.Blocks;

public sealed record BlockStockCode(string RawCode, string Code);

public sealed record BlockParseIssue(int LineNumber, string RawLine, string Reason);

public sealed record BlockParseResult(
    string Path,
    IReadOnlyList<BlockStockCode> Codes,
    IReadOnlyList<BlockParseIssue> Issues)
{
    public int DuplicateCount => Issues.Count(issue => issue.Reason == BlockFileParser.DuplicateReason);
}

public sealed class BlockFileParser
{
    public const string DuplicateReason = "duplicate";

    public BlockParseResult ParseFile(string path)
    {
        if (!File.Exists(path))
        {
            return new BlockParseResult(
                path,
                Array.Empty<BlockStockCode>(),
                [new BlockParseIssue(0, path, "file_not_found")]);
        }

        var lines = File.ReadAllLines(path, Encoding.Default);
        return ParseLines(path, lines);
    }

    public BlockParseResult ParseLines(string path, IEnumerable<string> lines)
    {
        var codes = new List<BlockStockCode>();
        var issues = new List<BlockParseIssue>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var lineNumber = 0;

        foreach (var line in lines)
        {
            lineNumber++;
            var raw = (line ?? string.Empty).Trim();
            if (raw.Length == 0) continue;

            var code = NormalizeTdxBlockCode(raw);
            if (code is null)
            {
                issues.Add(new BlockParseIssue(lineNumber, raw, "invalid_code"));
                continue;
            }

            if (!seen.Add(code))
            {
                issues.Add(new BlockParseIssue(lineNumber, raw, DuplicateReason));
                continue;
            }

            codes.Add(new BlockStockCode(raw, code));
        }

        if (codes.Count == 0 && issues.Count == 0)
        {
            issues.Add(new BlockParseIssue(0, string.Empty, "empty_file"));
        }

        return new BlockParseResult(path, codes, issues);
    }

    public static string? NormalizeTdxBlockCode(string raw)
    {
        var text = new string((raw ?? string.Empty).Where(char.IsDigit).ToArray());
        var marketPrefix = '\0';
        if (text.Length == 7 && text[0] is '0' or '1' or '3')
        {
            marketPrefix = text[0];
            text = text[^6..];
        }
        else if (text.Length != 6)
        {
            return null;
        }

        return IsLikelyAshareCode(text, marketPrefix) ? text : null;
    }

    public static bool IsLikelyAshareCode(string code, char marketPrefix = '\0')
    {
        if (code.Length != 6 || !code.All(char.IsDigit)) return false;
        if (code.StartsWith("88", StringComparison.Ordinal)) return false;
        if (marketPrefix == '1')
        {
            return code.StartsWith("60", StringComparison.Ordinal) ||
                   code.StartsWith("68", StringComparison.Ordinal);
        }
        if (marketPrefix is '0' or '3')
        {
            return code.StartsWith("00", StringComparison.Ordinal) ||
                   code.StartsWith("30", StringComparison.Ordinal) ||
                   code.StartsWith("4", StringComparison.Ordinal) ||
                   code.StartsWith("8", StringComparison.Ordinal);
        }

        return code.StartsWith("00", StringComparison.Ordinal) ||
               code.StartsWith("30", StringComparison.Ordinal) ||
               code.StartsWith("60", StringComparison.Ordinal) ||
               code.StartsWith("68", StringComparison.Ordinal) ||
               code.StartsWith("8", StringComparison.Ordinal) ||
               code.StartsWith("4", StringComparison.Ordinal);
    }
}
