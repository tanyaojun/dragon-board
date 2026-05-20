using System.Diagnostics;
using System.Net.Sockets;

namespace YiDongJingLing.Diagnostics;

public sealed class BridgeProcessManager
{
    private readonly string _root;
    private Process? _process;

    public BridgeProcessManager(string root)
    {
        _root = root;
    }

    public static bool IsPortOpen(int port)
    {
        try
        {
            using var client = new TcpClient();
            var task = client.ConnectAsync("127.0.0.1", port);
            return task.Wait(TimeSpan.FromMilliseconds(300)) && client.Connected;
        }
        catch
        {
            return false;
        }
    }

    public bool StartBridge(Action<string> log, int port = 8765)
    {
        if (IsPortOpen(port))
        {
            log($"行情桥已在 {port} 端口运行。");
            return true;
        }

        if (_process is not null)
        {
            if (!_process.HasExited)
            {
                log($"行情桥进程仍在启动或未释放，PID={_process.Id}。");
                return true;
            }

            _process.Dispose();
            _process = null;
        }

        var script = Path.Combine(_root, "python-bridge", "main.py");
        if (!File.Exists(script))
        {
            log($"行情桥脚本不存在: {script}");
            return false;
        }

        var info = new ProcessStartInfo
        {
            FileName = "python",
            Arguments = "python-bridge/main.py",
            WorkingDirectory = _root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        info.Environment["TDX_BRIDGE_PORT"] = port.ToString();

        _process = new Process { StartInfo = info, EnableRaisingEvents = true };
        _process.OutputDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log($"[bridge] {e.Data}"); };
        _process.ErrorDataReceived += (_, e) => { if (!string.IsNullOrWhiteSpace(e.Data)) log($"[bridge] {e.Data}"); };
        _process.Start();
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
        log($"已启动行情桥，端口={port}，PID={_process.Id}。");
        return true;
    }

    public void StopStartedBridge()
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
