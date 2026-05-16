using System.Diagnostics;

namespace DragonBoardLauncher;

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
        bool isVoiceWorker = false)
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
    public Process? Process { get; set; }
}
