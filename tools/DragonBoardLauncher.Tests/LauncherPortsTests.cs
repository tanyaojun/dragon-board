using DragonBoardLauncher;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class LauncherPortsTests
{
    // IsEndpointForPort 是 private；通过 GetPidsByPort 间接测端口匹配代价高。
    // 用反射访问 private 方法做精确断言，防 :16379 误命中 6379 类回归。
    private static bool Match(string endpoint, int port)
    {
        var method = typeof(LauncherPorts).GetMethod(
            "IsEndpointForPort",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            binder: null,
            types: new[] { typeof(string), typeof(int) },
            modifiers: null);
        Assert.NotNull(method);
        return (bool)method!.Invoke(null, new object[] { endpoint, port })!;
    }

    [Theory]
    [InlineData("127.0.0.1:8001", 8001, true)]
    [InlineData("0.0.0.0:6379", 6379, true)]
    [InlineData("127.0.0.1:16379", 6379, false)] // 端口后缀误匹配防护
    [InlineData("127.0.0.1:18001", 8001, false)]
    [InlineData("127.0.0.1:63790", 6379, false)]
    [InlineData("[::1]:8001", 8001, true)]
    [InlineData("[::]:8001", 8001, true)]
    [InlineData("[::1]:18001", 8001, false)]
    public void EndpointPort_MatchOnlyExactPort(string endpoint, int port, bool expected)
    {
        Assert.Equal(expected, Match(endpoint, port));
    }

    [Fact]
    public void IsPortOpen_TrueForRealListeningSocket()
    {
        // 契约：真实监听中的端口必须判定为打开——即使系统 TCP 表损坏
        // （2026-10-09 Windows 更新后 LISTENING 行缺失/PID=0），连接探测回退仍要救回。
        // 局限（评审 P2）：本机 TCP 表正常时断言走 GetActiveTcpListeners 快路径，
        // 未直接覆盖回退分支；回退分支已在 2026-10-09 故障机上实测验证。
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        try
        {
            var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
            Assert.True(LauncherPorts.IsPortOpen(port), $"端口 {port} 正在监听但 IsPortOpen 返回 false");
        }
        finally
        {
            listener.Stop();
        }
    }

    [Fact]
    public void IsPortOpen_FalseForClosedPort()
    {
        // 先占用再释放，拿到一个确定空闲的端口
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        Thread.Sleep(150); // 等内核回收
        Assert.False(LauncherPorts.IsPortOpen(port), $"端口 {port} 已释放但 IsPortOpen 返回 true");
    }

    [Theory]
    [InlineData("python.exe", "D:\\venv\\python.exe -m uvicorn app:app --port 8001", "python", "--port 8001", true)]
    [InlineData("PYTHON.EXE", "python python-bridge/main.py", "python", "python-bridge/main.py", true)] // 进程名忽略大小写/扩展名
    [InlineData("node.exe", "node server.js", "node", "server.js", true)]
    [InlineData("node.exe", "node vite.js --port 5173", "node", "--port 5174", false)] // 端口不同不匹配
    [InlineData("chrome.exe", "chrome --single-argument --port 8000", "python", "--port 8000", false)] // 进程名不符不匹配（防误杀编辑器等）
    [InlineData("python.exe", "", "python", "--port 8000", false)] // 空命令行不匹配
    public void MatchesServiceSignature_MatchesOnlySameProcessAndSignature(
        string processName,
        string commandLine,
        string expectedProcess,
        string signature,
        bool expected)
    {
        Assert.Equal(
            expected,
            DragonBoardLauncher.LauncherProcessManager.MatchesServiceSignature(
                processName, commandLine, expectedProcess, signature));
    }
}
