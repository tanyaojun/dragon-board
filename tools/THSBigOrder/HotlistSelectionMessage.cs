using System;
using Newtonsoft.Json.Linq;

namespace THSBigOrder
{
    internal sealed class HotlistSelectionMessage
    {
        public string Code { get; private set; }
        public string Name { get; private set; }

        public static bool TryParse(string json, out HotlistSelectionMessage message)
        {
            message = null;
            if (string.IsNullOrWhiteSpace(json)) return false;

            try
            {
                var value = JObject.Parse(json);
                var code = NormalizeCode((string)value["code"]);
                if (code == null) return false;
                message = new HotlistSelectionMessage
                {
                    Code = code,
                    Name = ((string)value["name"] ?? string.Empty).Trim(),
                };
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static string NormalizeCode(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return null;
            var code = value.Trim().ToUpperInvariant();
            if (code.StartsWith("SH", StringComparison.Ordinal) ||
                code.StartsWith("SZ", StringComparison.Ordinal) ||
                code.StartsWith("BJ", StringComparison.Ordinal))
            {
                code = code.Substring(2);
            }
            return code.Length == 6 &&
                code[0] >= '0' && code[0] <= '9' &&
                long.TryParse(code, out _) ? code : null;
        }
    }
}
