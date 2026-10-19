using System.Diagnostics;
using System.Net.NetworkInformation;

namespace DragonBoardLauncher;

internal static class LauncherPorts
{
    public static bool IsPortOpen(int port)
    {
        var properties = IPGlobalProperties.GetIPGlobalProperties();
        if (properties.GetActiveTcpListeners().Any(endpoint => endpoint.Port == port))
            return true;
        if (properties.GetActiveTcpConnections().Any(connection =>
            connection.LocalEndPoint.Port == port &&
            connection.State is TcpState.Listen or TcpState.Established))
            return true;

        // Windows 更新后系统 TCP 表可能损坏（netstat / Get-NetTCPConnection 的
        // LISTENING 行缺失或 PID=0，2026-10-09 复盘 KB5127773/KB5127757）：
        // 表里查不到时回退真实 TCP 连接探测——连接成功即端口可用，这是权威信号，
        // 不依赖系统表；避免把「活着的服务」误判为未运行而重复拉起（端口 10048 风暴）。
        // 同时探测 IPv6 回环（评审 P2）：仅绑 [::1] 的服务在表损坏时不至于误判死。
        return IsTcpListeningOn("127.0.0.1", port) || IsTcpListeningOn("::1", port);
    }

    public static bool IsTcpListeningOn(string host, int port, int timeoutMs = 500)
    {
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            var task = client.ConnectAsync(host, port);
            return task.Wait(TimeSpan.FromMilliseconds(timeoutMs)) && client.Connected;
        }
        catch
        {
            return false;
        }
    }

    public static IReadOnlyList<int> GetPidsByPort(int port)
    {
        var result = new List<int>();
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = "netstat.exe",
                Arguments = "-ano -p tcp",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true
            };
            using var process = Process.Start(info);
            if (process == null) return result;

            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(3000);
            foreach (var line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 5 || !IsEndpointForPort(parts[1], port)) continue;
                // 只取 LISTENING 状态的 PID：netstat -ano -p tcp 列序为
                // Proto Local Foreign State PID，状态在 parts[^2]、PID 在 parts[^1]。
                // ESTABLISHED 是残留连接（健康检查等），不代表进程在监听该端口，
                // 误取会导致端口 owner 错绑/误杀。
                if (!string.Equals(parts[^2], "LISTENING", StringComparison.OrdinalIgnoreCase)) continue;
                if (int.TryParse(parts[^1], out var pid) && pid > 0 && !result.Contains(pid))
                    result.Add(pid);
            }
        }
        catch { }

        return result;
    }

    private static bool IsEndpointForPort(string endpoint, int port)
    {
        // 精确匹配端口：取最后一个冒号后的段做全等比较，避免 :16379 误命中 6379
        // （EndsWith(":6379") 对 127.0.0.1:16379 也成立，会把无关进程纳入清理/接管）。
        var colonIndex = endpoint.LastIndexOf(':');
        if (colonIndex > 0 && colonIndex < endpoint.Length - 1)
        {
            // IPv6 端点形如 [::1]:8001，括号外最后一个冒号才是端口分隔。
            var afterColon = endpoint[(colonIndex + 1)..];
            if (int.TryParse(afterColon, out var parsedPort) && parsedPort == port)
                return true;
        }

        return endpoint.Equals($"[::1]:{port}", StringComparison.OrdinalIgnoreCase)
            || endpoint.Equals($"[::]:{port}", StringComparison.OrdinalIgnoreCase);
    }
}
