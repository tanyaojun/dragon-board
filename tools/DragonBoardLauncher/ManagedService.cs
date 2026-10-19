using System.Diagnostics;

namespace DragonBoardLauncher;

/// <summary>子进程日志落盘级别策略（P2.1 配置化，替代分散的 logOnlyErrors 硬编码）。</summary>
internal enum ServiceLogLevel
{
    /// <summary>全量输出落盘（默认）。</summary>
    All,

    /// <summary>仅错误/警告级输出落盘（stdout 全忽略），如行情桥的 INFO 轮询噪音。</summary>
    ErrorsOnly,

    /// <summary>全量输出，但过滤高频访问日志（uvicorn 访问行、proxy 每请求行、健康检查）。</summary>
    FilterAccess
}

/// <summary>子进程日志策略。</summary>
internal sealed record ServiceLogPolicy(
    ServiceLogLevel Level = ServiceLogLevel.All,
    bool SuppressHealth = false)
{
    /// <summary>等价于旧 logOnlyErrors=true 的语义。</summary>
    public bool ErrorsOnly => Level == ServiceLogLevel.ErrorsOnly;
}

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
    /// <summary>
    /// 本次退出是否为管理器主动停止（StopService）。
    /// 仅用于退出日志定性："主动停止"与"意外退出/被杀"必须能区分
    /// （2026-10-19 复盘：旧日志无法区分，盘中突然退出无法归因）。
    /// </summary>
    public bool StopRequested { get; set; }

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
        ServiceExternalPolicy externalPolicy = ServiceExternalPolicy.Managed,
        ServiceLogPolicy? logPolicy = null,
        string? dumpRdbPath = null,
        string? dumpRdbOwner = null,
        string? processSignature = null,
        string? openUrl = null)
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
        // 显式 logPolicy 优先；否则按旧 logOnlyErrors 映射（兼容默认值回退路径）。
        LogPolicy = logPolicy ?? new ServiceLogPolicy(
            logOnlyErrors ? ServiceLogLevel.ErrorsOnly : ServiceLogLevel.All);
        DumpRdbPath = dumpRdbPath;
        DumpRdbOwner = dumpRdbOwner;
        ProcessSignature = processSignature;
        OpenUrl = openUrl;
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
    /// <summary>子进程日志策略（P2.1）：级别 + 是否抑制健康检查行。</summary>
    public ServiceLogPolicy LogPolicy { get; }
    public ServiceExternalPolicy ExternalPolicy { get; }
    /// <summary>launcher 直接拉起的进程（引导进程）。uvicorn 类服务下该进程可能不监听端口。</summary>
    public Process? Process { get; set; }
    /// <summary>实际监听端口的进程（uvicorn 在 Windows 上 spawn 出的真 server 子进程）。
    /// 停止时优先终止该进程，再终止引导进程；单进程服务下为 null（Process 即监听者）。</summary>
    public Process? PortOwnerProcess { get; set; }
    /// <summary>Refuse 策略下接管的"自家残留"进程的可执行文件路径（用于停止前核对，
    /// 防 PID 复用误杀外部进程；仅当路径仍匹配时才允许终止）。</summary>
    public string? AdoptedExe { get; set; }
    /// <summary>启动后需检查文件所有者的 RDB 路径（如 Redis dump.rdb）；null 表示无需检查。</summary>
    public string? DumpRdbPath { get; }
    /// <summary>RDB 文件的期望所有者（如 "TANNY-PC\\Think"）；实际所有者不符时自动修复权限。</summary>
    public string? DumpRdbOwner { get; }
    /// <summary>TCP 表损坏时按命令行识别孤儿进程的签名（2026-10-09）；null 时默认
    /// 用 "--port {Port}"。仅对 Managed 服务、且 netstat 表查不到端口 PID 时作为回退证据。</summary>
    public string? ProcessSignature { get; }
    /// <summary>「打开」按钮的目标 URL（services.json openUrl，2026-10-12 外置化）。
    /// null = 不显示打开按钮（无 Web UI 的基础设施类服务）；
    /// mongo/redis 的本地管理工具拉起仍由 Form 特判，不走此字段。</summary>
    public string? OpenUrl { get; }
}
