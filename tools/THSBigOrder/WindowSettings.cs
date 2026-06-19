using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace THSBigOrder
{
    /// <summary>
    /// 窗口设置保存和恢复
    /// </summary>
    public static class WindowSettings
    {
        private static readonly string SettingsFile = Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory, "window_settings.ini");

        /// <summary>
        /// 保存窗口大小
        /// </summary>
        public static void SaveWindowSize(string windowName, Size size)
        {
            try
            {
                var lines = File.Exists(SettingsFile) 
                    ? new System.Collections.Generic.List<string>(File.ReadAllLines(SettingsFile))
                    : new System.Collections.Generic.List<string>();

                string key = windowName + "_Size";
                string value = string.Format("{0},{1}", size.Width, size.Height);
                string newLine = key + "=" + value;

                // 查找并替换或添加
                int index = lines.FindIndex(l => l.StartsWith(key + "="));
                if (index >= 0)
                    lines[index] = newLine;
                else
                    lines.Add(newLine);

                File.WriteAllLines(SettingsFile, lines);
            }
            catch { }
        }

        /// <summary>
        /// 读取窗口大小
        /// </summary>
        public static Size? LoadWindowSize(string windowName)
        {
            try
            {
                if (!File.Exists(SettingsFile)) return null;

                string key = windowName + "_Size=";
                foreach (var line in File.ReadAllLines(SettingsFile))
                {
                    if (line.StartsWith(key))
                    {
                        string value = line.Substring(key.Length);
                        var parts = value.Split(',');
                        if (parts.Length == 2)
                        {
                            int width = int.Parse(parts[0]);
                            int height = int.Parse(parts[1]);
                            return new Size(width, height);
                        }
                    }
                }
            }
            catch { }
            return null;
        }

        /// <summary>
        /// 应用窗口大小（如果有保存的设置）
        /// </summary>
        public static void ApplyWindowSize(Form form, string windowName)
        {
            var size = LoadWindowSize(windowName);
            if (size.HasValue)
            {
                // 确保不小于最小尺寸
                int width = Math.Max(size.Value.Width, form.MinimumSize.Width);
                int height = Math.Max(size.Value.Height, form.MinimumSize.Height);
                form.Size = new Size(width, height);
            }
        }
    }
}
