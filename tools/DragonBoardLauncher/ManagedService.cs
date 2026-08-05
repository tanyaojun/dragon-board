using System.Diagnostics;

namespace DragonBoardLauncher;

/// <summary>外部进程占用端口时的处置策略（P1.1 services.json 外置）。</summary>
internal enum ServiceExternalPolicy
{
    /// <summary>由启动器拉起并托管；端口被未知进程占用时清理后重启。</summary>
    Managed,

    /// <summary>外部实例（如 Windows 服务方式 Redis）直接复用，不清理不重复启动。</summary>
    Reuse,

    /// <summary>发现端口被外部进程占用时只显示 PID/进程名，不杀不清理。</summary>
    Refuse
}

internal sealed class ManagedService
{
    public ManagedService(
        string name,
        int port,
        string workingDirectory,
        string fileName,
        string arguments,
        string? fallbackFileName = null,
        string? fallbackArguments = null,
        Dictionary<string, string>? envVars = null,
        bool isVoiceWorker = false,
        bool logOnlyErrors = false,
        ServiceExternalPolicy externalPolicy = ServiceExternalPolicy.Managed)
    {
        Name = name;
        Port = port;
        WorkingDirectory = workingDirectory;
        FileName = fileName;
        Arguments = arguments;
        FallbackFileName = fallbackFileName;
        FallbackArguments = fallbackArguments;
        EnvVars = envVars;
        IsVoiceWorker = isVoiceWorker;
        LogOnlyErrors = logOnlyErrors;
        ExternalPolicy = externalPolicy;
    }

    public string Name { get; }
    public int Port { get; }
    public string WorkingDirectory { get; }
    public string FileName { get; }
    public string Arguments { get; }
    public string? FallbackFileName { get; }
    public string? FallbackArguments { get; }
    public Dictionary<string, string>? EnvVars { get; }
    public bool IsVoiceWorker { get; }
    /// <summary>仅把子进程错误级输出写入启动器日志（如行情桥的 INFO 轮询日志量过大）。</summary>
    public bool LogOnlyErrors { get; }
    public ServiceExternalPolicy ExternalPolicy { get; }
    public Process? Process { get; set; }
}
