namespace DragonBoardLauncher;

internal static class LauncherServices
{
    public const string VoiceServiceKey = "voice";
    public const int VoiceWorkerPort = 32145;

    public static readonly string[] OrderedKeys =
    [
        "mongo",
        "redis",
        "proxy",
        "bridge",
        "quant-api",
        "frontend",
        "quant-ui",
        VoiceServiceKey
    ];

    public static readonly string[][] CoreStartupStages =
    [
        ["mongo", "redis"],
        ["proxy", "bridge"],
        ["quant-api"]
    ];

    public static Dictionary<string, ManagedService> Create(string root)
    {
        var quantRoot = Path.Combine(root, "quant-board");
        var voiceWorkerExe = Path.Combine(
            root,
            "tools",
            "VoiceWorker",
            "bin",
            "Release",
            "net8.0-windows10.0.19041.0",
            "VoiceWorker.exe");

        return new Dictionary<string, ManagedService>
        {
            ["mongo"] = new(
                "MongoDB 数据库",
                27017,
                @"D:\APP_SOFT\MongoDB\bin",
                @"D:\APP_SOFT\MongoDB\bin\mongod.exe",
                @"--dbpath D:\APP_SOFT\MongoDB\data --logpath D:\APP_SOFT\MongoDB\log\mongod.log --port 27017"),
            ["redis"] = new(
                "Redis 缓存",
                6379,
                @"D:\APP_SOFT\redis",
                @"D:\APP_SOFT\redis\redis-server.exe",
                @"D:\APP_SOFT\redis\redis.windows-service.conf"),
            ["proxy"] = new("本地代理服务", 3000, Path.Combine(root, "proxy-server"), "node", "server.js"),
            [VoiceServiceKey] = new(
                "本地语音服务",
                VoiceWorkerPort,
                root,
                voiceWorkerExe,
                "",
                "dotnet",
                @"run --project tools\VoiceWorker\VoiceWorker.csproj",
                isVoiceWorker: true),
            ["frontend"] = new(
                "龙头看板前端",
                5173,
                root,
                "node",
                "\"node_modules/vite/bin/vite.js\" --host 127.0.0.1 --port 5173",
                envVars: NoColorEnv()),
            ["bridge"] = new("通达信行情桥", 8765, root, "python", "python-bridge/main.py"),
            ["quant-api"] = new(
                "量化后端 API",
                8000,
                quantRoot,
                Path.Combine(quantRoot, ".venv", "Scripts", "python.exe"),
                "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000",
                "python"),
            ["quant-ui"] = new(
                "量化面板前端",
                5174,
                Path.Combine(quantRoot, "frontend"),
                "node",
                "\"node_modules/vite/bin/vite.js\" --host 127.0.0.1 --port 5174",
                envVars: NoColorEnv())
        };
    }

    private static Dictionary<string, string> NoColorEnv() => new()
    {
        ["NO_COLOR"] = "1",
        ["FORCE_COLOR"] = "0"
    };
}
