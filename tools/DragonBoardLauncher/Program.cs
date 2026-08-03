using System.Threading;

namespace DragonBoardLauncher;

internal static class Program
{
    private const string MutexName = @"Local\DragonBoardLauncher_SingleInstance";

    [STAThread]
    private static void Main()
    {
        using var mutex = new Mutex(initiallyOwned: true, MutexName, out var createdNew);
        if (!createdNew)
        {
            // 单实例互斥：禁止双开 launcher。之前双实例各自重复拉起服务，
            // 是 8000/8001 多 PID 与残留采集锁的根因。
            MessageBox.Show(
                "DragonBoardLauncher 已在运行，请先退出已有实例（含托盘图标）后再启动。",
                "启动管理器",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }
        try
        {
            ApplicationConfiguration.Initialize();
            Application.Run(new LauncherForm());
        }
        finally
        {
            mutex.ReleaseMutex();
        }
    }
}
