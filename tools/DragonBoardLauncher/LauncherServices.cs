using System.Text.Json;

namespace DragonBoardLauncher;

internal static class LauncherServices
{
    public const string VoiceServiceKey = "voice";
    public const int VoiceWorkerPort = 32145;

    /// <summary>服务定义配置文件（相对启动器工程根）。缺失或解析失败时回退内嵌默认。</summary>
    private const string ServicesConfigFileName = "config/services.json";

    public static readonly string[] OrderedKeys =
    [
        "mongo",
        "redis",
        "proxy",
        "bridge",
        "collector",
        "quant-api",
        "frontend",
        "quant-ui",
        VoiceServiceKey
    ];

    private static readonly string[][] DefaultStages =
    [
        ["mongo", "redis"],
        ["proxy", "bridge"],
        ["quant-api"],
        ["collector"]
    ];

    /// <summary>核心启动依赖链（阶段顺序即依赖顺序，来自 services.json stages，加载失败回退默认）。</summary>
    private static string[][] _coreStartupStages = DefaultStages;

    public static string[][] CoreStartupStages => _coreStartupStages;

    public static Dictionary<string, ManagedService> Create(string root)
    {
        // 每次 Create 先重置为默认，避免重复调用时残留上一次加载的 stages。
        _coreStartupStages = DefaultStages;
        var loaded = TryLoadFromConfig(root);
        if (loaded is null)
        {
            return CreateDefaults(root);
        }

        // 解析 stages：services.json 里 stage 顺序即依赖顺序（核心服务必须按序启动）。
        var stages = ParseStagesFromConfig(root, loaded);
        if (stages is not null && stages.Length > 0)
            _coreStartupStages = stages;
        return loaded;
    }

    private static string[][]? ParseStagesFromConfig(
        string root,
        Dictionary<string, ManagedService> services)
    {
        try
        {
            var path = Path.Combine(root, "tools", "DragonBoardLauncher", ServicesConfigFileName);
            if (!File.Exists(path)) return null;

            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var rootElement = document.RootElement;
            if (!rootElement.TryGetProperty("stages", out var stages) ||
                stages.ValueKind != JsonValueKind.Array)
            {
                return null;
            }

            var result = new List<string[]>();
            foreach (var stage in stages.EnumerateArray())
            {
                if (!stage.TryGetProperty("keys", out var keys) ||
                    keys.ValueKind != JsonValueKind.Array)
                {
                    return null;
                }

                var stageKeys = new List<string>();
                foreach (var key in keys.EnumerateArray())
                {
                    if (key.ValueKind != JsonValueKind.String) return null;
                    var stageKey = key.GetString() ?? "";
                    // 防御：stage 引用不存在的服务 key 时整体回退默认，
                    // 避免 StartAll 阶段索引 _services[key] 抛异常。
                    if (!services.ContainsKey(stageKey)) return null;
                    stageKeys.Add(stageKey);
                }
                if (stageKeys.Count > 0)
                    result.Add(stageKeys.ToArray());
            }
            return result.Count > 0 ? result.ToArray() : null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>从 config/services.json 加载服务定义；文件缺失/解析失败/必选 key 缺失
    /// 时返回 null（调用方回退内嵌默认，避免部分加载导致索引异常）。</summary>
    private static Dictionary<string, ManagedService>? TryLoadFromConfig(string root)
    {
        try
        {
            var path = Path.Combine(root, "tools", "DragonBoardLauncher", ServicesConfigFileName);
            if (!File.Exists(path)) return null;

            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var rootElement = document.RootElement;
            var result = new Dictionary<string, ManagedService>(StringComparer.Ordinal);

            if (!rootElement.TryGetProperty("services", out var services) ||
                services.ValueKind != JsonValueKind.Array)
            {
                return null;
            }

            foreach (var item in services.EnumerateArray())
            {
                var parsed = ParseService(item, root);
                // key 为英文标识（mongo/redis/proxy/...），全代码以 key 索引服务字典。
                // 任一服务解析失败即整体回退默认，避免部分加载导致后续 _services[key] 抛异常。
                if (parsed is null)
                    return null;
                result[parsed.Value.Key] = parsed.Value.Service;
            }

            // 必选核心 key 必须齐全，否则回退默认。
            var requiredKeys = new[] { "mongo", "redis", "proxy", "bridge", "collector", "quant-api" };
            foreach (var key in requiredKeys)
            {
                if (!result.ContainsKey(key))
                    return null;
            }

            return result.Count > 0 ? result : null;
        }
        catch
        {
            return null;
        }
    }

    private static (string Key, ManagedService Service)? ParseService(JsonElement item, string root)
    {
        try
        {
            var key = GetString(item, "key");
            if (string.IsNullOrWhiteSpace(key)) return null;

            var name = GetString(item, "name") ?? key;
            var port = GetInt(item, "port", 0);
            var workingDirectory = Expand(GetString(item, "workingDirectory"), root);
            var fileName = Expand(GetString(item, "fileName"), root);
            var arguments = GetString(item, "arguments") ?? "";
            var fallbackFileName = ExpandNullable(GetString(item, "fallbackFileName"), root);
            var fallbackArguments = GetString(item, "fallbackArguments");
            var isVoiceWorker = GetBool(item, "isVoiceWorker", false);
            var logOnlyErrors = GetBool(item, "logOnlyErrors", false);
            var externalPolicy = ParsePolicy(GetString(item, "externalPolicy"));
            var logPolicy = ParseLogPolicy(item, logOnlyErrors);
            var dumpRdbPath = ExpandNullable(GetString(item, "dumpRdbPath"), root);
            var dumpRdbOwner = GetString(item, "dumpRdbOwner");
            var processSignature = GetString(item, "processSignature");

            Dictionary<string, string>? envVars = null;
            if (item.TryGetProperty("envVars", out var envElement) &&
                envElement.ValueKind == JsonValueKind.Object)
            {
                envVars = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (var prop in envElement.EnumerateObject())
                    envVars[prop.Name] = prop.Value.GetString() ?? "";
            }

            var service = new ManagedService(
                name,
                port,
                workingDirectory ?? "",
                fileName ?? "",
                arguments,
                fallbackFileName,
                fallbackArguments,
                envVars,
                isVoiceWorker,
                logOnlyErrors,
                externalPolicy,
                logPolicy,
                dumpRdbPath,
                dumpRdbOwner,
                processSignature);
            return (key, service);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>解析 logPolicy 对象（{level, suppressHealth}）；缺省按旧 logOnlyErrors 映射。</summary>
    internal static ServiceLogPolicy? ParseLogPolicy(JsonElement item, bool logOnlyErrors)
    {
        if (!item.TryGetProperty("logPolicy", out var policy) ||
            policy.ValueKind != JsonValueKind.Object)
        {
            return null; // 让 ManagedService 按 logOnlyErrors 兜底
        }

        var level = ServiceLogLevel.All;
        if (policy.TryGetProperty("level", out var levelEl) &&
            levelEl.ValueKind == JsonValueKind.String)
        {
            level = levelEl.GetString() switch
            {
                "errors-only" => ServiceLogLevel.ErrorsOnly,
                "filter-access" => ServiceLogLevel.FilterAccess,
                _ => ServiceLogLevel.All
            };
        }

        var suppressHealth = false;
        if (policy.TryGetProperty("suppressHealth", out var suppressEl) &&
            suppressEl.ValueKind == JsonValueKind.True)
        {
            suppressHealth = true;
        }

        return new ServiceLogPolicy(level, suppressHealth);
    }

    private static ServiceExternalPolicy ParsePolicy(string? value) =>
        value switch
        {
            "reuse" => ServiceExternalPolicy.Reuse,
            "refuse" => ServiceExternalPolicy.Refuse,
            _ => ServiceExternalPolicy.Managed
        };

    private static string? GetString(JsonElement item, string name) =>
        item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int GetInt(JsonElement item, string name, int fallback) =>
        item.TryGetProperty(name, out var value) && value.TryGetInt32(out var parsed)
            ? parsed
            : fallback;

    private static bool GetBool(JsonElement item, string name, bool fallback) =>
        item.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True
            ? true
            : value.ValueKind == JsonValueKind.False ? false : fallback;

    private static string Expand(string? value, string root) =>
        string.IsNullOrWhiteSpace(value)
            ? value ?? ""
            : value.Replace("${repoRoot}", root.TrimEnd(Path.DirectorySeparatorChar));

    private static string? ExpandNullable(string? value, string root) =>
        value is null ? null : Expand(value, root);

    /// <summary>内嵌默认服务定义（services.json 缺失/解析失败时的回退，与旧代码行为一致）。</summary>
    private static Dictionary<string, ManagedService> CreateDefaults(string root)
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
                @"--dbpath D:\APP_SOFT\MongoDB\data --logpath D:\APP_SOFT\MongoDB\log\mongod.log --port 27017",
                externalPolicy: ServiceExternalPolicy.Refuse),
            ["redis"] = new(
                "Redis 缓存",
                6379,
                @"D:\APP_SOFT\redis\Redis-8.10.0",
                @"D:\APP_SOFT\redis\Redis-8.10.0\redis-server.exe",
                @"redis.conf",
                externalPolicy: ServiceExternalPolicy.Reuse,
                dumpRdbPath: @"D:\APP_SOFT\redis\Redis-8.10.0\dump.rdb",
                dumpRdbOwner: @"TANNY-PC\Think"),
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
            ["bridge"] = new(
                "通达信行情桥",
                8765,
                root,
                "python",
                "python-bridge/main.py",
                logOnlyErrors: true),
            ["quant-api"] = new(
                "量化后端 API",
                8000,
                quantRoot,
                Path.Combine(quantRoot, ".venv", "Scripts", "python.exe"),
                "-m uvicorn backend.main:app --host 127.0.0.1 --port 8000",
                "python"),
            ["collector"] = new(
                "快照采集服务",
                8001,
                quantRoot,
                Path.Combine(quantRoot, ".venv", "Scripts", "python.exe"),
                "-m uvicorn backend.collector_main:app --host 127.0.0.1 --port 8001",
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
