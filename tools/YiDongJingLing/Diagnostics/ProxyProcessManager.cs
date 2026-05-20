using System.Diagnostics;

namespace YiDongJingLing.Diagnostics;

public sealed class ProxyProcessManager
{
    private readonly string _root;
    private Process? _process;

    public ProxyProcessManager(string root)
    {
        _root = root;
    }

    public bool StartProxy(Action<string> log, int port = 3000)
    {
        if (BridgeProcessManager.IsPortOpen(port))
        {
            log($"本地代理已在 {port} 端口运行。");
            return true;
        }

        if (_process is not null)
        {
            if (!_process.HasExited)
            {
                log($"本地代理仍在启动或未释放，PID={_process.Id}。");
                return true;
            }

            _process.Dispose();
            _process = null;
        }

        var server = Path.Combine(_root, "proxy-server", "server.js");
        if (!File.Exists(server))
        {
            log($"本地代理入口不存在: {server}");
            return false;
        }

        var info = new ProcessStartInfo
        {
            FileName = "node",
            Arguments = "server.js",
            WorkingDirectory = Path.Combine(_root, "proxy-server"),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        info.Environment["PORT"] = port.ToString();

        _process = new Process { StartInfo = info, EnableRaisingEvents = true };
        _process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log($"[proxy] {e.Data}"); };
        _process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log($"[proxy] {e.Data}"); };
        _process.Start();
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
        log($"已启动本地代理，端口={port}，PID={_process.Id}。");
        return true;
    }

    public void StopStartedProxy()
    {
        try
        {
            if (_process is { HasExited: false })
            {
                _process.Kill(true);
            }
        }
        catch
        {
        }
        finally
        {
            _process?.Dispose();
            _process = null;
        }
    }
}
