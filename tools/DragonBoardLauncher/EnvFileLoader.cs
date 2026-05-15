using System.Text.RegularExpressions;

internal static class EnvFileLoader
{
    private static readonly Regex PowerShellEnvLine = new(
        @"^\s*\$env:(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.+?)\s*$",
        RegexOptions.Compiled);

    private static readonly Regex PlainEnvLine = new(
        @"^\s*(?<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.+?)\s*$",
        RegexOptions.Compiled);

    public static Dictionary<string, string> Load(string path)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(path)) return values;

        foreach (var rawLine in File.ReadLines(path))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith('#')) continue;

            var match = PowerShellEnvLine.Match(line);
            if (!match.Success) match = PlainEnvLine.Match(line);
            if (!match.Success) continue;

            var key = match.Groups["key"].Value;
            var value = Unquote(match.Groups["value"].Value.Trim());
            values[key] = value;
        }

        return values;
    }

    private static string Unquote(string value)
    {
        if (value.Length >= 2 &&
            ((value.StartsWith('\'') && value.EndsWith('\'')) ||
             (value.StartsWith('"') && value.EndsWith('"'))))
        {
            return value[1..^1];
        }

        return value;
    }
}
