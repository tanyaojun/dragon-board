namespace YiDongJingLing;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        try
        {
            System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
            ApplicationConfiguration.Initialize();
            Application.Run(new MainForm());
        }
        catch (Exception ex)
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "DragonBoard",
                "YiDongJingLing");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "startup-error.log");
            File.WriteAllText(path, ex.ToString());
            MessageBox.Show(
                $"异动精灵启动失败，错误已写入：{path}\n\n{ex.Message}",
                "异动精灵",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }
}
