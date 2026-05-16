using System.Diagnostics;
using System.Net.NetworkInformation;

namespace DragonBoardLauncher;

internal static class LauncherPorts
{
    public static bool IsPortOpen(int port)
    {
        var properties = IPGlobalProperties.GetIPGlobalProperties();
        return properties.GetActiveTcpListeners().Any(endpoint => endpoint.Port == port)
            || properties.GetActiveTcpConnections().Any(connection =>
                connection.LocalEndPoint.Port == port &&
                connection.State is TcpState.Listen or TcpState.Established);
    }

    public static bool IsTcpListeningOn(string host, int port)
    {
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            var task = client.ConnectAsync(host, port);
            return task.Wait(TimeSpan.FromMilliseconds(500)) && client.Connected;
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
                if (int.TryParse(parts[^1], out var pid) && pid > 0 && !result.Contains(pid))
                    result.Add(pid);
            }
        }
        catch { }

        return result;
    }

    private static bool IsEndpointForPort(string endpoint, int port)
    {
        if (endpoint.EndsWith($":{port}", StringComparison.Ordinal))
            return true;

        return endpoint.Equals($"[::1]:{port}", StringComparison.OrdinalIgnoreCase)
            || endpoint.Equals($"[::]:{port}", StringComparison.OrdinalIgnoreCase);
    }
}
