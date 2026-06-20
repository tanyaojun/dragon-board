using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reflection.PortableExecutable;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace TdxL2Helper;

internal static partial class Program
{
    private const uint SemFailCriticalErrors = 0x0001;
    private const uint SemNoGpFaultErrorBox = 0x0002;
    private const uint SemNoOpenFileErrorBox = 0x8000;
    private const uint ProcessVmRead = 0x0010;
    private const uint ProcessQueryInformation = 0x0400;
    private const uint ProcessQueryLimitedInformation = 0x1000;
    private const int LiveSysSourceCStringAddress = unchecked((int)0x011BED6C);
    private const int LiveL2RightCStringAddress = unchecked((int)0x011BEE80);
    private const int LiveL2ZhCStringAddress = unchecked((int)0x011D4FEC);

    private static readonly string[] PreferredCachedLoginProfiles =
    {
        "tdxid-token-connectqsid-reguid",
        "tdxid-token-connectqsid-oid",
        "tdxid-token-jymainqsid-oid",
        "tdxid-token-userpuid-oid",
        "tdxid-token-oid-reguid",
        "tdxid-token-reguid-empty",
        "tdxid-token-reguid-hostip",
    };

    private static readonly string[] TcExports =
    {
        "TC_Init_Environ",
        "TC_Login",
        "TC_Login2",
        "TC_GetLoginRet",
        "TC_GetRightInfo",
        "TC_GetL2Info",
        "TC_SetL2UserInfo",
        "TC_Uninit",
    };

    private static readonly string[] DeepExports =
    {
        "TdxDeep_StartInit",
        "TdxDeep_Data",
        "TdxDeep_Func",
        "TdxDeep_RegisterCallBackFunc",
        "TdxDeep_SetMainWnd",
        "TdxDeep_Uninit",
    };

    private static int Main(string[] args)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

        var options = CliOptions.Parse(args);
        if (!options.DisableProcessErrorMode)
        {
            ApplyProcessErrorMode();
        }
        if (options.ShowHelp)
        {
            Console.WriteLine(CliOptions.HelpText);
            return 0;
        }

        ResolveCachedLoginProfile(options);

        try
        {
            if (options.Command == "host-runtime" && options.EventStream)
            {
                return RunSelfHostEventStream(options);
            }

            if (options.Command == "read-l2-depth")
            {
                RunReadL2Depth(options);
                return 0;
            }

            object report = options.Command switch
            {
                "inspect" => BuildInspectReport(options),
                "sync-runtime-layout" => SyncRuntimeLayout(options),
                "probe-tc-baseline" => RunTcBaselineProbe(options),
                "probe-tc-login-matrix" => RunTcLoginMatrixProbe(options),
                "probe-tc-login-attempt" => RunTcLoginAttemptProbe(options),
                "probe-tc-setl2" => RunTcSetL2Probe(options),
                "probe-tc-setl2-matrix" => RunTcSetL2MatrixProbe(options),
                "host-runtime" => BuildSelfHostRuntimeReport(options),
                _ => throw new ArgumentException($"unsupported command: {options.Command}"),
            };

            var json = JsonSerializer.Serialize(report, JsonOptions.Default);
            Console.WriteLine(json);
            return ResolveExitCode(report);
        }
        catch (Exception error)
        {
            var payload = JsonSerializer.Serialize(
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    ok = false,
                    errorType = error.GetType().Name,
                    error = error.Message,
                },
                JsonOptions.Default);
            Console.WriteLine(payload);
            return 1;
        }
    }

    private static void RunReadL2Depth(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var process = L2DepthReader.FindTdxProcess(tdxRoot);
        if (process is null)
        {
            Console.Error.WriteLine("[错误] 未找到运行中的 tdxw.exe 进程。请先启动通达信客户端。");
            Environment.Exit(1);
        }

        var pid = process.Id;
        Console.Error.WriteLine($"[进程] tdxw.exe PID={pid}");

        // 加载缓存或扫描
        var addresses = options.L2ForceScan ? null : L2DepthReader.LoadAddressCache(tdxRoot);

        if (addresses is null || addresses.Count == 0)
        {
            Console.Error.WriteLine("[扫描] 正在搜索 L2 深度数据内存地址...");
            var report = L2DepthReader.Scan(pid);

            if (!report.Ok)
            {
                Console.Error.WriteLine($"[错误] {report.Error}");
                Environment.Exit(2);
            }

            Console.Error.WriteLine($"[结果] 扫描 {report.RegionsScanned} 个区域，找到 {report.Candidates.Count} 个候选:");
            foreach (var candidate in report.Candidates.Take(15))
            {
                Console.Error.WriteLine(
                    $"  {candidate.Address} score={candidate.Score,3}  "
                    + $"bid1={candidate.BidPrices.FirstOrDefault():F2}  "
                    + $"ask1={candidate.AskPrices.FirstOrDefault():F2}  "
                    + $"bids={candidate.BidPrices.Count} asks={candidate.AskPrices.Count}");
            }

            addresses = report.Candidates
                .Where(c => c.Score >= Math.Max(report.Candidates[0].Score * 0.6, 15))
                .Select(c => L2DepthReader.ParseHex(c.Address))
                .ToList();

            if (addresses.Count > 0)
            {
                L2DepthReader.SaveAddressCache(tdxRoot, addresses);
                Console.Error.WriteLine($"[缓存] 已保存 {addresses.Count} 个地址");
            }
        }
        else
        {
            Console.Error.WriteLine($"[缓存] 已加载 {addresses.Count} 个地址");
        }

        // 监控模式
        if (options.L2Monitor)
        {
            Console.Error.WriteLine($"[监控] 间隔 {options.L2IntervalMs}ms, 按 Ctrl+C 退出");
            L2DepthReader.Monitor(pid, addresses, options.L2IntervalMs, options.L2Output);
        }
        else
        {
            // 单次读取
            using var reader = new L2DepthReader.ProcessMemoryReader(pid);
            foreach (var addr in addresses.Take(10))
            {
                var snapshot = L2DepthReader.ReadDepth(reader, addr);
                if (snapshot is not null)
                {
                    var json = JsonSerializer.Serialize(snapshot, JsonOptions.Default);
                    Console.WriteLine(json);
                }
            }
        }

        process.Dispose();
    }

    private static int ResolveExitCode(object report)
    {
        return report switch
        {
            InspectReport inspect => inspect.Ok ? 0 : 2,
            RuntimeLayoutReport layout => layout.Ok ? 0 : 2,
            TcBaselineProbeReport baseline => baseline.Ok ? 0 : 2,
            TcLoginMatrixProbeReport loginMatrix => loginMatrix.Ok ? 0 : 2,
            TcLoginMatrixAttemptReport loginAttempt => string.IsNullOrWhiteSpace(loginAttempt.Error) ? 0 : 2,
            TcSetL2ProbeReport setL2 => setL2.Ok ? 0 : 2,
            TcSetL2MatrixProbeReport setL2Matrix => setL2Matrix.Ok ? 0 : 2,
            SelfHostRuntimeReport host => host.Ok ? 0 : 2,
            _ => 1,
        };
    }

    private static InspectReport BuildInspectReport(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var deepPath = ResolvePath(options.DeepPath, Path.Combine(tdxRoot, "TDXDeep.dll"));

        var modules = new List<ModuleReport>
        {
            InspectModule("tc.dll", tcPath, TcExports),
            InspectModule("TDXDeep.dll", deepPath, DeepExports),
        };

        return new InspectReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Ok = modules.All(module => module.Exists && module.Loaded && string.IsNullOrWhiteSpace(module.Error)),
            Command = "inspect",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            Modules = modules,
            Notes =
            {
                "This helper must run as x86 before any 32-bit TDX DLL calls are attempted.",
                "Current command only loads modules and resolves export addresses; it does not call TC_* or TdxDeep_* functions.",
                "LoadLibraryEx executes DllMain. Keep this helper isolated from the production bridge until signatures are confirmed.",
            },
        };
    }

    private static string ResolveTcPath(string tdxRoot, string? explicitPath)
    {
        if (!string.IsNullOrWhiteSpace(explicitPath))
        {
            return Path.GetFullPath(explicitPath);
        }

        var candidates = new[]
        {
            Path.Combine(tdxRoot, "tc.dll"),
            Path.Combine(tdxRoot, "NewTc", "tc.dll"),
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return candidates[0];
    }

    private static string ResolvePath(string? explicitPath, string fallback)
    {
        return string.IsNullOrWhiteSpace(explicitPath)
            ? Path.GetFullPath(fallback)
            : Path.GetFullPath(explicitPath);
    }

    private static ModuleReport InspectModule(string name, string path, IReadOnlyList<string> exportNames)
    {
        var report = new ModuleReport
        {
            Name = name,
            Path = path,
            Exists = File.Exists(path),
        };

        if (!report.Exists)
        {
            report.Error = "missing_file";
            return report;
        }

        report.FileArchitecture = ReadPeArchitecture(path);

        const uint loadWithAlteredSearchPath = 0x00000008;
        var handle = NativeMethods.LoadLibraryExW(path, IntPtr.Zero, loadWithAlteredSearchPath);
        if (handle == IntPtr.Zero)
        {
            report.Error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            return report;
        }

        try
        {
            report.Loaded = true;
            report.ModuleHandle = ToHex(handle);
            foreach (var exportName in exportNames)
            {
                var exportAddress = NativeMethods.GetProcAddress(handle, exportName);
                report.Exports.Add(new ExportReport
                {
                    Name = exportName,
                    Resolved = exportAddress != IntPtr.Zero,
                    Address = exportAddress == IntPtr.Zero ? string.Empty : ToHex(exportAddress),
                });
            }
        }
        finally
        {
            NativeMethods.FreeLibrary(handle);
        }

        return report;
    }

    private static TcBaselineProbeReport RunTcBaselineProbe(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var report = new TcBaselineProbeReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Command = "probe-tc-baseline",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            TcPath = tcPath,
            BufferSize = options.BufferSize,
            InitArgs = new TcInitArgsSnapshot
            {
                Arg1 = options.InitArg1,
                Arg2 = options.InitArg2,
                Arg3 = options.InitArg3,
                Arg5 = options.InitArg5,
                Arg6 = options.InitArg6,
            },
        };

        report.RuntimeLayout = options.SyncRuntimeLayout
            ? SyncRuntimeLayout(options, "probe-tc-baseline")
            : CaptureRuntimeLayout(tdxRoot, "probe-tc-baseline");

        if (!File.Exists(tcPath))
        {
            report.Error = $"missing tc.dll: {tcPath}";
            return report;
        }

        var previousDirectory = Directory.GetCurrentDirectory();
        Directory.SetCurrentDirectory(tdxRoot);

        const uint loadWithAlteredSearchPath = 0x00000008;
        var handle = NativeMethods.LoadLibraryExW(tcPath, IntPtr.Zero, loadWithAlteredSearchPath);
        if (handle == IntPtr.Zero)
        {
            report.Error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            Directory.SetCurrentDirectory(previousDirectory);
            return report;
        }

        try
        {
            report.ModuleHandle = ToHex(handle);

            var initPtr = NativeMethods.GetProcAddress(handle, "TC_Init_Environ");
            var getL2Ptr = NativeMethods.GetProcAddress(handle, "TC_GetL2Info");
            var uninitPtr = NativeMethods.GetProcAddress(handle, "TC_Uninit");

            report.ResolvedExports = new Dictionary<string, bool>
            {
                ["TC_Init_Environ"] = initPtr != IntPtr.Zero,
                ["TC_GetL2Info"] = getL2Ptr != IntPtr.Zero,
                ["TC_Uninit"] = uninitPtr != IntPtr.Zero,
            };

            if (getL2Ptr != IntPtr.Zero && options.PreInitGetL2Info)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PreInitGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (initPtr != IntPtr.Zero)
            {
                var init = Marshal.GetDelegateForFunctionPointer<TcInitEnvironFn>(initPtr);
                report.InitResult = InvokeTcInitEnviron(init, options);
            }

            if (getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PostInitGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (uninitPtr != IntPtr.Zero)
            {
                var uninit = Marshal.GetDelegateForFunctionPointer<TcUninitFn>(uninitPtr);
                report.UninitResult = InvokeTcUninit(uninit);
            }

            report.Ok = string.IsNullOrWhiteSpace(report.Error);
            report.Notes.Add("This probe uses cdecl delegate guesses from current static analysis.");
            report.Notes.Add("TC_Init_Environ defaults to null/zero arguments unless explicit overrides are provided.");
            report.Notes.Add("TC_GetL2Info receives two writable buffers to capture unknown output shapes.");
            if (!report.RuntimeLayout.Ok)
            {
                report.Notes.Add("Runtime layout is incomplete under the helper executable directory. Use --sync-runtime-layout before probing tc.dll.");
            }
            return report;
        }
        finally
        {
            NativeMethods.FreeLibrary(handle);
            Directory.SetCurrentDirectory(previousDirectory);
        }
    }

    private static TcSetL2ProbeReport RunTcSetL2Probe(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var report = new TcSetL2ProbeReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Command = "probe-tc-setl2",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            TcPath = tcPath,
            BufferSize = options.BufferSize,
            InitArgs = new TcInitArgsSnapshot
            {
                Arg1 = options.InitArg1,
                Arg2 = options.InitArg2,
                Arg3 = options.InitArg3,
                Arg5 = options.InitArg5,
                Arg6 = options.InitArg6,
            },
            SetL2Args = new TcSetL2ArgsSnapshot
            {
                Arg1 = options.SetL2Arg1,
                Arg2 = options.SetL2Arg2,
                Arg3 = options.SetL2Arg3,
            },
            LoginRequest = options.HasLoginInvocationRequest ? BuildLoginRequestSnapshot(options) : null,
            ResolvedLoginProfile = options.ResolvedLoginProfile ?? string.Empty,
        };

        report.RuntimeLayout = options.SyncRuntimeLayout
            ? SyncRuntimeLayout(options, "probe-tc-setl2")
            : CaptureRuntimeLayout(tdxRoot, "probe-tc-setl2");
        report.Materials = LoadCachedLoginMaterials(tdxRoot);

        if (!File.Exists(tcPath))
        {
            report.Error = $"missing tc.dll: {tcPath}";
            return report;
        }

        if (!options.HasSetL2Args)
        {
            report.Error = "probe-tc-setl2 requires at least one of --setl2-arg1/--setl2-arg2/--setl2-arg3";
            return report;
        }

        var previousDirectory = Directory.GetCurrentDirectory();
        Directory.SetCurrentDirectory(tdxRoot);

        const uint loadWithAlteredSearchPath = 0x00000008;
        var handle = NativeMethods.LoadLibraryExW(tcPath, IntPtr.Zero, loadWithAlteredSearchPath);
        if (handle == IntPtr.Zero)
        {
            report.Error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            Directory.SetCurrentDirectory(previousDirectory);
            return report;
        }

        try
        {
            report.ModuleHandle = ToHex(handle);

            var initPtr = NativeMethods.GetProcAddress(handle, "TC_Init_Environ");
            var loginPtr = NativeMethods.GetProcAddress(handle, "TC_Login");
            var login2Ptr = NativeMethods.GetProcAddress(handle, "TC_Login2");
            var getLoginRetPtr = NativeMethods.GetProcAddress(handle, "TC_GetLoginRet");
            var getRightInfoPtr = NativeMethods.GetProcAddress(handle, "TC_GetRightInfo");
            var getL2Ptr = NativeMethods.GetProcAddress(handle, "TC_GetL2Info");
            var setL2Ptr = NativeMethods.GetProcAddress(handle, "TC_SetL2UserInfo");
            var uninitPtr = NativeMethods.GetProcAddress(handle, "TC_Uninit");

            report.ResolvedExports = new Dictionary<string, bool>
            {
                ["TC_Init_Environ"] = initPtr != IntPtr.Zero,
                ["TC_Login"] = loginPtr != IntPtr.Zero,
                ["TC_Login2"] = login2Ptr != IntPtr.Zero,
                ["TC_GetLoginRet"] = getLoginRetPtr != IntPtr.Zero,
                ["TC_GetRightInfo"] = getRightInfoPtr != IntPtr.Zero,
                ["TC_GetL2Info"] = getL2Ptr != IntPtr.Zero,
                ["TC_SetL2UserInfo"] = setL2Ptr != IntPtr.Zero,
                ["TC_Uninit"] = uninitPtr != IntPtr.Zero,
            };

            if (getL2Ptr != IntPtr.Zero && options.PreInitGetL2Info)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PreInitGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (initPtr != IntPtr.Zero)
            {
                var init = Marshal.GetDelegateForFunctionPointer<TcInitEnvironFn>(initPtr);
                report.InitResult = InvokeTcInitEnviron(init, options);
            }

            if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
            {
                var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                report.PreLoginGetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
                if (options.ProbeLoginState)
                {
                    report.ProbeGetLoginRet = report.PreLoginGetLoginRet;
                }
            }

            if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
            {
                var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                report.PreLoginGetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
                if (options.ProbeLoginState)
                {
                    report.ProbeGetRightInfo = report.PreLoginGetRightInfo;
                }
            }

            if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PreLoginGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (options.ProbeLoginState)
            {
                report.Notes.Add("probe-login-state reuses the same pre-login snapshots captured after TC_Init_Environ.");
            }

            if (options.HasLoginInvocationRequest)
            {
                var functionName = string.Equals(options.LoginFunction, "login2", StringComparison.OrdinalIgnoreCase)
                    ? "login2"
                    : "login";
                var loginTarget = string.Equals(functionName, "login2", StringComparison.OrdinalIgnoreCase)
                    ? login2Ptr
                    : loginPtr;
                if (loginTarget != IntPtr.Zero)
                {
                    var login = Marshal.GetDelegateForFunctionPointer<TcLoginFn>(loginTarget);
                    report.LoginResult = InvokeTcLogin(login, functionName, options);
                }
                else
                {
                    report.LoginResult = new TcLoginCallReport
                    {
                        Invoked = false,
                        Function = functionName,
                        Error = $"missing export for {functionName}",
                    };
                }

                if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
                {
                    var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                    report.PostLoginGetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
                }

                if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
                {
                    var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                    report.PostLoginGetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
                }

                if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
                {
                    var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                    report.PostLoginGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
                }
            }

            if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
            {
                var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                report.PreSetL2GetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
            }

            if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
            {
                var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                report.PreSetL2GetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
            }

            if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PreSetL2GetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (setL2Ptr != IntPtr.Zero)
            {
                var setL2 = Marshal.GetDelegateForFunctionPointer<TcSetL2UserInfoFn>(setL2Ptr);
                report.SetL2Result = InvokeTcSetL2UserInfo(setL2, options);
            }

            if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
            {
                var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                report.PostSetL2GetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
            }

            if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                report.PostSetL2GetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
            {
                var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                report.PostSetL2GetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
            }

            if (uninitPtr != IntPtr.Zero)
            {
                var uninit = Marshal.GetDelegateForFunctionPointer<TcUninitFn>(uninitPtr);
                report.UninitResult = InvokeTcUninit(uninit);
            }

            report.SignalScore = ComputeSetL2SignalScore(report);
            report.StateChanged = HasAnyStateDelta(report);
            report.SignalHints = BuildSetL2SignalHints(report);
            report.Ok = string.IsNullOrWhiteSpace(report.Error);
            report.Notes.Add("This probe uses cdecl delegate guesses from current static analysis.");
            report.Notes.Add("Sequence: optional pre-init TC_GetL2Info -> TC_Init_Environ -> pre-login loginret/rightinfo/l2 snapshots -> optional TC_Login/TC_Login2 -> post-login snapshots -> pre-setl2 snapshots -> TC_SetL2UserInfo -> post-setl2 snapshots -> TC_Uninit.");
            report.Notes.Add("Persisted files do not currently expose a confirmed L2ZH string. Use live runtime memory or direct CLI args for that axis.");
            report.Notes.Add("probe-tc-baseline now defaults to skipping the crash-prone pre-init TC_GetL2Info path.");
            return report;
        }
        finally
        {
            NativeMethods.FreeLibrary(handle);
            Directory.SetCurrentDirectory(previousDirectory);
        }
    }

    private static TcLoginMatrixProbeReport RunTcLoginMatrixProbe(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var report = new TcLoginMatrixProbeReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Command = "probe-tc-login-matrix",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            TcPath = tcPath,
            BufferSize = options.BufferSize,
            RepeatCount = Math.Max(1, options.RepeatCount),
        };

        report.RuntimeLayout = options.SyncRuntimeLayout
            ? SyncRuntimeLayout(options, "probe-tc-login-matrix")
            : CaptureRuntimeLayout(tdxRoot, "probe-tc-login-matrix");

        if (!File.Exists(tcPath))
        {
            report.Error = $"missing tc.dll: {tcPath}";
            return report;
        }

        report.Materials = LoadCachedLoginMaterials(tdxRoot);
        var profiles = ApplyProfileFilter(BuildCachedLoginProfiles(report.Materials), options);
        if (profiles.Count == 0)
        {
            report.Error = string.IsNullOrWhiteSpace(options.ProfileFilter)
                ? "no cached login materials found under the current TDX root"
                : $"no cached login profiles matched --profile-filter '{options.ProfileFilter}'";
            report.Notes.Add("Expected fields include TDXToken, TPSession, TDXID, UserPUID, RegUID, ConnectQSID, or OID.");
            return report;
        }

        report.SelectedProfiles = profiles.Select(profile => profile.Name).ToList();
        var functionNames = string.IsNullOrWhiteSpace(options.LoginFunction)
            ? new[] { "login", "login2" }
            : new[] { options.LoginFunction.Trim().ToLowerInvariant() };

        for (var repeatIndex = 0; repeatIndex < report.RepeatCount; repeatIndex++)
        {
            foreach (var profile in profiles)
            {
                foreach (var functionName in functionNames)
                {
                    report.Attempts.Add(RunTcLoginAttemptIsolated(options, tcPath, functionName, profile, repeatIndex));
                }
            }
        }

        var interestingAttempts = report.Attempts.Where(attempt => attempt.StateChanged || attempt.SignalScore > 0).ToList();
        report.ProfileSummaries = BuildProfileSummaries(report.Attempts);
        report.SignalSummaries = BuildSignalSummaries(interestingAttempts);
        report.Ok = string.IsNullOrWhiteSpace(report.Error) && report.Attempts.Count > 0;
        report.Notes.Add("This probe uses cached local TDX identity/session materials and small fixed candidate permutations.");
        if (!string.IsNullOrWhiteSpace(options.ProfileFilter))
        {
            report.Notes.Add($"Applied profile filter: {options.ProfileFilter}");
        }
        if (!string.IsNullOrWhiteSpace(options.LoginFunction))
        {
            report.Notes.Add($"Applied login function filter: {options.LoginFunction}.");
        }
        report.Notes.Add($"Selected profiles: {profiles.Count}; repeats: {report.RepeatCount}.");
        report.Notes.Add("Actual argument values are intentionally not echoed back; only source names, lengths, and state deltas are reported.");
        report.Notes.Add("A meaningful signal usually means post-login buffers changed relative to pre-login snapshots, not merely returnValue=1.");
        report.Notes.Add($"Interesting attempts: {interestingAttempts.Count} / {report.Attempts.Count}.");
        return report;
    }

    private static void ResolveCachedLoginProfile(CliOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.LoginProfile))
        {
            return;
        }

        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var materials = LoadCachedLoginMaterials(tdxRoot);
        var profiles = BuildCachedLoginProfiles(materials);
        if (profiles.Count == 0)
        {
            throw new ArgumentException("no cached login profiles could be built from the current TDX root");
        }

        var requested = options.LoginProfile.Trim();
        CachedLoginProfile? selected = null;
        if (string.Equals(requested, "auto", StringComparison.OrdinalIgnoreCase))
        {
            foreach (var preferredName in PreferredCachedLoginProfiles)
            {
                selected = profiles.FirstOrDefault(
                    profile => string.Equals(profile.Name, preferredName, StringComparison.OrdinalIgnoreCase));
                if (selected is not null)
                {
                    break;
                }
            }

            selected ??= profiles.First();
        }
        else
        {
            selected = profiles.FirstOrDefault(
                profile => string.Equals(profile.Name, requested, StringComparison.OrdinalIgnoreCase));
        }

        if (selected is null)
        {
            var available = string.Join(", ", profiles.Select(profile => profile.Name));
            throw new ArgumentException($"unknown --login-profile '{requested}'. available profiles: {available}");
        }

        options.ApplyResolvedLoginProfile(selected);
    }

    private static TcLoginMatrixAttemptReport RunTcLoginAttemptProbe(CliOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.LoginFunction))
        {
            throw new ArgumentException("probe-tc-login-attempt requires --login-function");
        }

        var profile = new CachedLoginProfile
        {
            Name = "direct-cli",
            Arguments =
            {
                new CachedLoginArgument { Slot = 1, Source = "login-arg1", Value = options.LoginArg1 },
                new CachedLoginArgument { Slot = 2, Source = "login-arg2", Value = options.LoginArg2 },
                new CachedLoginArgument { Slot = 3, Source = "login-arg3", Value = options.LoginArg3 },
                new CachedLoginArgument { Slot = 4, Source = "login-arg4", Value = options.LoginArg4 },
            },
        };

        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        return RunTcLoginAttempt(tdxRoot, tcPath, options.LoginFunction, profile, options);
    }

    private static TcLoginMatrixAttemptReport RunTcLoginAttempt(
        string tdxRoot,
        string tcPath,
        string functionName,
        CachedLoginProfile profile,
        CliOptions options)
    {
        var attempt = new TcLoginMatrixAttemptReport
        {
            Function = functionName,
            ProfileName = profile.Name,
            Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
        };

        var previousDirectory = Directory.GetCurrentDirectory();
        Directory.SetCurrentDirectory(tdxRoot);

        const uint loadWithAlteredSearchPath = 0x00000008;
        var handle = NativeMethods.LoadLibraryExW(tcPath, IntPtr.Zero, loadWithAlteredSearchPath);
        if (handle == IntPtr.Zero)
        {
            attempt.Error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            Directory.SetCurrentDirectory(previousDirectory);
            return attempt;
        }

        try
        {
            var initPtr = NativeMethods.GetProcAddress(handle, "TC_Init_Environ");
            var loginPtr = NativeMethods.GetProcAddress(handle, functionName == "login2" ? "TC_Login2" : "TC_Login");
            var getLoginRetPtr = NativeMethods.GetProcAddress(handle, "TC_GetLoginRet");
            var getRightInfoPtr = NativeMethods.GetProcAddress(handle, "TC_GetRightInfo");
            var getL2Ptr = NativeMethods.GetProcAddress(handle, "TC_GetL2Info");
            var uninitPtr = NativeMethods.GetProcAddress(handle, "TC_Uninit");

            attempt.ResolvedExports = new Dictionary<string, bool>
            {
                ["TC_Init_Environ"] = initPtr != IntPtr.Zero,
                [functionName == "login2" ? "TC_Login2" : "TC_Login"] = loginPtr != IntPtr.Zero,
                ["TC_GetLoginRet"] = getLoginRetPtr != IntPtr.Zero,
                ["TC_GetRightInfo"] = getRightInfoPtr != IntPtr.Zero,
                ["TC_GetL2Info"] = getL2Ptr != IntPtr.Zero,
                ["TC_Uninit"] = uninitPtr != IntPtr.Zero,
            };

            if (initPtr != IntPtr.Zero)
            {
                var init = Marshal.GetDelegateForFunctionPointer<TcInitEnvironFn>(initPtr);
                attempt.InitResult = InvokeTcInitEnviron(init, options);
            }

            if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
            {
                var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                attempt.PreGetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
            }

            if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
            {
                var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                attempt.PreGetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
            }

            if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                attempt.PreGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            if (loginPtr != IntPtr.Zero)
            {
                var login = Marshal.GetDelegateForFunctionPointer<TcLoginFn>(loginPtr);
                attempt.LoginResult = InvokeTcLogin(login, functionName, profile);
            }

            if (!options.SkipLoginRetProbe && getLoginRetPtr != IntPtr.Zero)
            {
                var getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
                attempt.PostGetLoginRet = InvokeTcGetLoginRet(getLoginRet, options.BufferSize);
            }

            if (!options.SkipRightInfoProbe && getRightInfoPtr != IntPtr.Zero)
            {
                var getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
                attempt.PostGetRightInfo = InvokeTcGetRightInfo(getRightInfo, options.BufferSize);
            }

            if (!options.SkipL2InfoProbe && getL2Ptr != IntPtr.Zero)
            {
                var getL2 = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
                attempt.PostGetL2Info = InvokeTcGetL2Info(getL2, options.BufferSize);
            }

            attempt.SignalScore = ComputeSignalScore(attempt);
            attempt.StateChanged = HasAnyStateDelta(attempt);
            attempt.SignalHints = BuildSignalHints(attempt);

            if (!options.SkipTcUninit && uninitPtr != IntPtr.Zero)
            {
                var uninit = Marshal.GetDelegateForFunctionPointer<TcUninitFn>(uninitPtr);
                attempt.UninitResult = InvokeTcUninit(uninit);
            }

            return attempt;
        }
        catch (Exception error)
        {
            attempt.Error = error.Message;
            attempt.ErrorType = error.GetType().Name;
            return attempt;
        }
        finally
        {
            NativeMethods.FreeLibrary(handle);
            Directory.SetCurrentDirectory(previousDirectory);
        }
    }

    private static List<CachedLoginProfile> ApplyProfileFilter(List<CachedLoginProfile> profiles, CliOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.ProfileFilter))
        {
            return profiles;
        }

        var terms = options.ProfileFilter
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(term => !string.IsNullOrWhiteSpace(term))
            .ToArray();
        if (terms.Length == 0)
        {
            return profiles;
        }

        return profiles
            .Where(
                profile => terms.Any(
                    term => profile.Name.Contains(term, StringComparison.OrdinalIgnoreCase)))
            .ToList();
    }

    private static TcLoginMatrixAttemptReport RunTcLoginAttemptIsolated(
        CliOptions options,
        string tcPath,
        string functionName,
        CachedLoginProfile profile,
        int repeatIndex)
    {
        var executablePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(executablePath) || !File.Exists(executablePath))
        {
            return new TcLoginMatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                Function = functionName,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ExecutableResolutionFailed",
                Error = "unable to resolve current helper executable path for isolated login probe",
            };
        }

        var childExecutablePath = executablePath;
        var isolatedAppBase = string.Empty;
        if (options.IsolateChildAppBase)
        {
            isolatedAppBase = CreateIsolatedChildAppBase(executablePath);
            childExecutablePath = Path.Combine(isolatedAppBase, Path.GetFileName(executablePath));
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = childExecutablePath,
            WorkingDirectory = Path.GetDirectoryName(childExecutablePath) ?? Directory.GetCurrentDirectory(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        startInfo.ArgumentList.Add("probe-tc-login-attempt");
        startInfo.ArgumentList.Add("--tdx-root");
        startInfo.ArgumentList.Add(options.TdxRoot);
        startInfo.ArgumentList.Add("--tc-path");
        startInfo.ArgumentList.Add(tcPath);
        startInfo.ArgumentList.Add("--buffer-size");
        startInfo.ArgumentList.Add(options.BufferSize.ToString());
        startInfo.ArgumentList.Add("--login-function");
        startInfo.ArgumentList.Add(functionName);
        if (options.DisableProcessErrorMode)
        {
            startInfo.ArgumentList.Add("--disable-process-error-mode");
        }
        if (options.DisableChildDialogWatchdog)
        {
            startInfo.ArgumentList.Add("--disable-child-dialog-watchdog");
        }
        if (options.SkipLoginRetProbe)
        {
            startInfo.ArgumentList.Add("--skip-loginret-probe");
        }
        if (options.SkipRightInfoProbe)
        {
            startInfo.ArgumentList.Add("--skip-rightinfo-probe");
        }
        if (options.SkipL2InfoProbe)
        {
            startInfo.ArgumentList.Add("--skip-l2info-probe");
        }
        if (options.SkipTcUninit)
        {
            startInfo.ArgumentList.Add("--skip-tc-uninit");
        }

        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg1", options.InitArg1);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg2", options.InitArg2);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg3", options.InitArg3);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg5", options.InitArg5);
        startInfo.ArgumentList.Add("--init-arg6");
        startInfo.ArgumentList.Add(options.InitArg6.ToString());

        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg1", profile.Arguments.FirstOrDefault(argument => argument.Slot == 1)?.Value);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg2", profile.Arguments.FirstOrDefault(argument => argument.Slot == 2)?.Value);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg3", profile.Arguments.FirstOrDefault(argument => argument.Slot == 3)?.Value);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg4", profile.Arguments.FirstOrDefault(argument => argument.Slot == 4)?.Value);

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            return new TcLoginMatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                Function = functionName,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ProcessStartFailed",
                Error = "failed to start isolated login probe child process",
            };
        }

        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        using var dialogWatchdogCts = options.DisableChildDialogWatchdog ? null : new CancellationTokenSource();
        var dialogWatchdogTask = dialogWatchdogCts is null
            ? Task.CompletedTask
            : Task.Run(
                () => WatchAndCloseChildDialogs(process.Id, dialogWatchdogCts.Token),
                dialogWatchdogCts.Token);

        if (!process.WaitForExit(60000))
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch
            {
                // Ignore cleanup failures; the timeout result is already definitive.
            }
            finally
            {
                dialogWatchdogCts?.Cancel();
            }

            TryWaitForExit(process, 2000);

            return new TcLoginMatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                Function = functionName,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ProbeTimeout",
                Error = "isolated login probe timed out after 60000 ms (child process likely blocked by an interactive dialog)",
            };
        }

        dialogWatchdogCts?.Cancel();
        TryWaitTask(dialogWatchdogTask, 2000);
        process.WaitForExit();

        var stdout = stdoutTask.GetAwaiter().GetResult();
        var stderr = stderrTask.GetAwaiter().GetResult();

        if (process.ExitCode != 0 && string.IsNullOrWhiteSpace(stdout))
        {
            return new TcLoginMatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                Function = functionName,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ChildProcessFailed",
                Error = $"isolated login probe exited with code {process.ExitCode}: {stderr.Trim()}".Trim(),
            };
        }

        try
        {
            var attempt = JsonSerializer.Deserialize<TcLoginMatrixAttemptReport>(stdout, JsonOptions.Default)
                ?? new TcLoginMatrixAttemptReport();

            attempt.Function = functionName;
            attempt.ProfileName = profile.Name;
            attempt.RepeatIndex = repeatIndex;
            attempt.Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList();
            if (process.ExitCode != 0 && string.IsNullOrWhiteSpace(attempt.Error))
            {
                attempt.ErrorType = "ChildProcessFailed";
                attempt.Error = $"isolated login probe exited with code {process.ExitCode}: {stderr.Trim()}".Trim();
            }

            return attempt;
        }
        catch (Exception error)
        {
            return new TcLoginMatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                Function = functionName,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = error.GetType().Name,
                Error = $"failed to parse isolated login probe output: {error.Message}",
            };
        }
        finally
        {
            TryDeleteDirectory(isolatedAppBase);
        }
    }

    private static TcSetL2MatrixProbeReport RunTcSetL2MatrixProbe(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var report = new TcSetL2MatrixProbeReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Command = "probe-tc-setl2-matrix",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            TcPath = tcPath,
            BufferSize = options.BufferSize,
            RepeatCount = options.RepeatCount,
        };

        report.RuntimeLayout = options.SyncRuntimeLayout
            ? SyncRuntimeLayout(options, "probe-tc-setl2-matrix")
            : CaptureRuntimeLayout(tdxRoot, "probe-tc-setl2-matrix");

        if (!File.Exists(tcPath))
        {
            report.Error = $"missing tc.dll: {tcPath}";
            return report;
        }

        report.Materials = LoadCachedLoginMaterials(tdxRoot);
        var profiles = BuildSetL2CandidateProfiles(report.Materials);
        var directProfile = BuildDirectSetL2CandidateProfile(options);
        if (directProfile is not null)
        {
            profiles.Insert(0, directProfile);
        }

        profiles = ApplySetL2ProfileFilter(profiles, options);
        if (profiles.Count == 0)
        {
            report.Error = string.IsNullOrWhiteSpace(options.ProfileFilter)
                ? "no setl2 candidate profiles could be built from the current TDX root"
                : $"no setl2 candidate profiles matched --profile-filter '{options.ProfileFilter}'";
            report.Notes.Add("Expected persisted materials include TDXID, OID, ConnectQSID, or JYMainQSID. A live L2ZH value currently needs direct CLI injection.");
            return report;
        }

        report.SelectedProfiles = profiles.Select(profile => profile.Name).ToList();
        for (var repeatIndex = 0; repeatIndex < options.RepeatCount; repeatIndex++)
        {
            foreach (var profile in profiles)
            {
                report.Attempts.Add(RunTcSetL2AttemptIsolated(options, tcPath, profile, repeatIndex));
            }
        }

        var interestingAttempts = report.Attempts.Where(attempt => attempt.StateChanged || attempt.SignalScore > 0).ToList();
        report.AttemptSummaries = BuildSetL2AttemptSummaries(interestingAttempts);
        report.ProfileSummaries = BuildSetL2ProfileSummaries(report.Attempts);
        report.SignalSummaries = BuildSetL2SignalSummaries(interestingAttempts);
        report.Ok = string.IsNullOrWhiteSpace(report.Error) && report.Attempts.Count > 0;
        report.Notes.Add("This probe builds small fixed TC_SetL2UserInfo candidate permutations from current local TDX materials.");
        report.Notes.Add("Current fixed matrix axis: CITICS#CFV + {TDXID|L2ZH when available} + {empty|ConnectQSID|JYMainQSID|OID}, plus arg1/arg2 swap.");
        if (options.HasLoginInvocationRequest)
        {
            report.Notes.Add("Configured login invocation is replayed inside each isolated setl2 attempt before TC_SetL2UserInfo.");
        }
        if (!string.IsNullOrWhiteSpace(options.ProfileFilter))
        {
            report.Notes.Add($"Applied profile filter: {options.ProfileFilter}");
        }

        report.Notes.Add($"Interesting attempts: {interestingAttempts.Count} / {report.Attempts.Count}.");
        return report;
    }

    private static TcSetL2MatrixAttemptReport RunTcSetL2AttemptIsolated(
        CliOptions options,
        string tcPath,
        SetL2CandidateProfile profile,
        int repeatIndex)
    {
        var executablePath = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(executablePath) || !File.Exists(executablePath))
        {
            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ExecutableResolutionFailed",
                Error = "unable to resolve current helper executable path for isolated setl2 probe",
            };
        }

        var childExecutablePath = executablePath;
        var isolatedAppBase = string.Empty;
        if (options.IsolateChildAppBase)
        {
            isolatedAppBase = CreateIsolatedChildAppBase(executablePath);
            childExecutablePath = Path.Combine(isolatedAppBase, Path.GetFileName(executablePath));
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = childExecutablePath,
            WorkingDirectory = Path.GetDirectoryName(childExecutablePath) ?? Directory.GetCurrentDirectory(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        startInfo.ArgumentList.Add("probe-tc-setl2");
        startInfo.ArgumentList.Add("--tdx-root");
        startInfo.ArgumentList.Add(options.TdxRoot);
        startInfo.ArgumentList.Add("--tc-path");
        startInfo.ArgumentList.Add(tcPath);
        startInfo.ArgumentList.Add("--buffer-size");
        startInfo.ArgumentList.Add(options.BufferSize.ToString());
        if (options.SyncRuntimeLayout)
        {
            startInfo.ArgumentList.Add("--sync-runtime-layout");
        }
        if (options.PreInitGetL2Info)
        {
            startInfo.ArgumentList.Add("--pre-init-getl2info");
        }
        if (options.DisableProcessErrorMode)
        {
            startInfo.ArgumentList.Add("--disable-process-error-mode");
        }
        if (options.ProbeLoginState)
        {
            startInfo.ArgumentList.Add("--probe-login-state");
        }
        if (options.SkipLoginRetProbe)
        {
            startInfo.ArgumentList.Add("--skip-loginret-probe");
        }
        if (options.SkipRightInfoProbe)
        {
            startInfo.ArgumentList.Add("--skip-rightinfo-probe");
        }
        if (options.SkipL2InfoProbe)
        {
            startInfo.ArgumentList.Add("--skip-l2info-probe");
        }
        if (options.SkipTcUninit)
        {
            startInfo.ArgumentList.Add("--skip-tc-uninit");
        }

        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg1", options.InitArg1);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg2", options.InitArg2);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg3", options.InitArg3);
        AppendOptionalArgument(startInfo.ArgumentList, "--init-arg5", options.InitArg5);
        startInfo.ArgumentList.Add("--init-arg6");
        startInfo.ArgumentList.Add(options.InitArg6.ToString());

        AppendOptionalArgument(startInfo.ArgumentList, "--login-function", options.LoginFunction);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-profile", options.ResolvedLoginProfile);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg1", options.LoginArg1);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg2", options.LoginArg2);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg3", options.LoginArg3);
        AppendOptionalArgument(startInfo.ArgumentList, "--login-arg4", options.LoginArg4);

        AppendOptionalArgument(startInfo.ArgumentList, "--setl2-arg1", profile.Arguments.FirstOrDefault(argument => argument.Slot == 1)?.Value);
        AppendOptionalArgument(startInfo.ArgumentList, "--setl2-arg2", profile.Arguments.FirstOrDefault(argument => argument.Slot == 2)?.Value);
        AppendOptionalArgument(startInfo.ArgumentList, "--setl2-arg3", profile.Arguments.FirstOrDefault(argument => argument.Slot == 3)?.Value);

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ProcessStartFailed",
                Error = "failed to start isolated setl2 probe child process",
            };
        }

        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        using var dialogWatchdogCts = options.DisableChildDialogWatchdog ? null : new CancellationTokenSource();
        var dialogWatchdogTask = dialogWatchdogCts is null
            ? Task.CompletedTask
            : Task.Run(
                () => WatchAndCloseChildDialogs(process.Id, dialogWatchdogCts.Token),
                dialogWatchdogCts.Token);

        if (!process.WaitForExit(60000))
        {
            try
            {
                process.Kill(entireProcessTree: true);
            }
            catch
            {
                // Ignore cleanup failures; the timeout result is already definitive.
            }
            finally
            {
                dialogWatchdogCts?.Cancel();
            }

            TryWaitForExit(process, 2000);

            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ProbeTimeout",
                Error = "isolated setl2 probe timed out after 60000 ms (child process likely blocked by an interactive dialog)",
            };
        }

        dialogWatchdogCts?.Cancel();
        TryWaitTask(dialogWatchdogTask, 2000);
        process.WaitForExit();

        var stdout = stdoutTask.GetAwaiter().GetResult();
        var stderr = stderrTask.GetAwaiter().GetResult();

        if (process.ExitCode != 0 && string.IsNullOrWhiteSpace(stdout))
        {
            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = "ChildProcessFailed",
                Error = $"isolated setl2 probe exited with code {process.ExitCode}: {stderr.Trim()}".Trim(),
            };
        }

        try
        {
            var probe = JsonSerializer.Deserialize<TcSetL2ProbeReport>(stdout, JsonOptions.Default)
                ?? new TcSetL2ProbeReport();
            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                Probe = probe,
                LoginFunction = probe.LoginRequest?.Function ?? options.LoginFunction ?? string.Empty,
                LoginProfileName = probe.LoginRequest?.ProfileName ?? options.ResolvedLoginProfile ?? string.Empty,
                StateChanged = probe.StateChanged,
                SignalScore = probe.SignalScore,
                SignalHints = probe.SignalHints,
                ErrorType = probe.ErrorType,
                Error = probe.Error,
            };
        }
        catch (Exception error)
        {
            return new TcSetL2MatrixAttemptReport
            {
                RepeatIndex = repeatIndex,
                ProfileName = profile.Name,
                Arguments = profile.Arguments.Select(ToMaskedArgumentSnapshot).ToList(),
                ErrorType = error.GetType().Name,
                Error = $"failed to parse isolated setl2 probe output: {error.Message}",
            };
        }
        finally
        {
            TryDeleteDirectory(isolatedAppBase);
        }
    }

    private static void AppendOptionalArgument(ICollection<string> args, string optionName, string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        args.Add(optionName);
        args.Add(value);
    }

    private static string CreateIsolatedChildAppBase(string executablePath)
    {
        var sourceDirectory = Path.GetDirectoryName(executablePath);
        if (string.IsNullOrWhiteSpace(sourceDirectory) || !Directory.Exists(sourceDirectory))
        {
            throw new DirectoryNotFoundException("unable to resolve helper executable directory for isolated child app base");
        }

        var destinationDirectory = Path.Combine(
            Path.GetTempPath(),
            "TdxL2HelperAttempts",
            $"{Path.GetFileNameWithoutExtension(executablePath)}-{Guid.NewGuid():N}");
        CopyDirectory(sourceDirectory, destinationDirectory);
        return destinationDirectory;
    }

    private static void CopyDirectory(string sourceDirectory, string destinationDirectory)
    {
        Directory.CreateDirectory(destinationDirectory);

        foreach (var filePath in Directory.GetFiles(sourceDirectory))
        {
            var destinationPath = Path.Combine(destinationDirectory, Path.GetFileName(filePath));
            File.Copy(filePath, destinationPath, overwrite: true);
        }

        foreach (var childDirectory in Directory.GetDirectories(sourceDirectory))
        {
            var name = Path.GetFileName(childDirectory);
            if (string.Equals(name, ".git", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            CopyDirectory(childDirectory, Path.Combine(destinationDirectory, name));
        }
    }

    private static void TryDeleteDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Directory.Exists(path))
        {
            return;
        }

        try
        {
            Directory.Delete(path, recursive: true);
        }
        catch
        {
            // Best-effort cleanup only.
        }
    }

    private static void WatchAndCloseChildDialogs(int processId, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            TryCloseOwnedWindows(processId);
            cancellationToken.WaitHandle.WaitOne(500);
        }
    }

    private static void TryCloseOwnedWindows(int processId)
    {
        var ownedWindows = new List<IntPtr>();
        NativeMethods.EnumWindows(
            (windowHandle, _) =>
            {
                NativeMethods.GetWindowThreadProcessId(windowHandle, out var ownerProcessId);
                if (ownerProcessId == processId && NativeMethods.IsWindowVisible(windowHandle))
                {
                    ownedWindows.Add(windowHandle);
                }

                return true;
            },
            IntPtr.Zero);

        foreach (var windowHandle in ownedWindows)
        {
            NativeMethods.PostMessageW(windowHandle, NativeMethods.WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
        }
    }

    private static void TryWaitForExit(Process process, int timeoutMs)
    {
        try
        {
            process.WaitForExit(timeoutMs);
        }
        catch
        {
            // Best-effort cleanup only.
        }
    }

    private static void TryWaitTask(Task task, int timeoutMs)
    {
        try
        {
            task.Wait(timeoutMs);
        }
        catch
        {
            // Best-effort cleanup only.
        }
    }

    private static CachedLoginMaterialsReport LoadCachedLoginMaterials(string tdxRoot)
    {
        var report = new CachedLoginMaterialsReport
        {
            TdxRoot = tdxRoot,
        };

        var t0002Root = Path.Combine(tdxRoot, "T0002");
        var userIniPath = Path.Combine(t0002Root, "user.ini");
        var userCommIniPath = Path.Combine(t0002Root, "usercomm.ini");
        var dataCachePath = Path.Combine(t0002Root, "datacache.json");
        var hostIpPath = Path.Combine(t0002Root, "hostip.ini");
        var connectCfgPath = Path.Combine(tdxRoot, "connect.cfg");

        report.SourceFiles.Add(new LoginMaterialFileSnapshot { Path = userIniPath, Exists = File.Exists(userIniPath) });
        report.SourceFiles.Add(new LoginMaterialFileSnapshot { Path = userCommIniPath, Exists = File.Exists(userCommIniPath) });
        report.SourceFiles.Add(new LoginMaterialFileSnapshot { Path = dataCachePath, Exists = File.Exists(dataCachePath) });
        report.SourceFiles.Add(new LoginMaterialFileSnapshot { Path = hostIpPath, Exists = File.Exists(hostIpPath) });
        report.SourceFiles.Add(new LoginMaterialFileSnapshot { Path = connectCfgPath, Exists = File.Exists(connectCfgPath) });

        var userIni = LoadIniValues(userIniPath);
        AddMaterial(report, "OID", TryGetValue(userIni, "OID"), @"T0002\user.ini");
        AddMaterial(report, "TPSession", TryGetValue(userIni, "TPSession"), @"T0002\user.ini");
        AddMaterial(report, "RegUID", TryGetValue(userIni, "RegUID"), @"T0002\user.ini");
        AddMaterial(report, "RegPhone", TryGetValue(userIni, "RegPhone"), @"T0002\user.ini");
        AddMaterial(report, "TDXToken", TryGetValue(userIni, "TDXToken"), @"T0002\user.ini");
        AddMaterial(report, "JYMainQSID", TryGetValue(userIni, "JYMainQSID"), @"T0002\user.ini");
        AddMaterial(report, "LastLoginType", TryGetValue(userIni, "LastLoginType"), @"T0002\user.ini");
        AddMaterial(report, "Embed_YybID", NullIfZeroOrWhiteSpace(TryGetValue(userIni, "Embed_YybID")), @"T0002\user.ini");

        var userCommIni = LoadIniValues(userCommIniPath);
        AddMaterial(report, "UserPUID", TryGetValue(userCommIni, "UserPUID"), @"T0002\usercomm.ini");
        AddMaterial(report, "SSOLoginYMD", TryGetValue(userCommIni, "SSOLoginYMD"), @"T0002\usercomm.ini");
        AddMaterial(report, "SSOLoginSeconds", TryGetValue(userCommIni, "SSOLoginSeconds"), @"T0002\usercomm.ini");
        AddMaterial(report, "SAVEZH", TryGetValue(userCommIni, "SAVEZH"), @"T0002\usercomm.ini");
        AddMaterial(report, "UseSpecTPHost", TryGetValue(userCommIni, "UseSpecTPHost"), @"T0002\usercomm.ini");

        if (File.Exists(dataCachePath))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(dataCachePath));
            if (document.RootElement.TryGetProperty("LoninExtendSvc", out var loginExtendSvc)
                && loginExtendSvc.ValueKind == JsonValueKind.Object)
            {
                AddMaterial(report, "TDXID", TryGetJsonString(loginExtendSvc, "TDXID"), @"T0002\datacache.json:LoninExtendSvc.TDXID");
                AddMaterial(report, "OID", TryGetJsonString(loginExtendSvc, "OID"), @"T0002\datacache.json:LoninExtendSvc.OID");
            }
        }

        var hostIpIni = LoadIniValues(hostIpPath);
        AddMaterial(report, "HostIP", TryGetValue(hostIpIni, "HostIP"), @"T0002\hostip.ini");

        var connectCfg = LoadIniValues(connectCfgPath);
        AddMaterial(report, "ConnectQSID", TryGetValue(connectCfg, "QSID"), @"connect.cfg");
        AddMaterial(report, "WTPreNAME", TryGetValue(connectCfg, "WTPreNAME"), @"connect.cfg");
        AddMaterial(report, "JyLogin_Style", TryGetValue(connectCfg, "JyLogin_Style"), @"connect.cfg");
        AddMaterial(report, "JyLogin", TryGetValue(connectCfg, "JyLogin"), @"connect.cfg");
        AddMaterial(report, "SpecIPLogin", TryGetValue(connectCfg, "SpecIPLogin"), @"connect.cfg");

        TryLoadLiveRuntimeMaterials(report, tdxRoot);
        AddTdxWl2RuntimeMaterials(report);

        if (report.ValueMap.ContainsKey("TDXID"))
        {
            report.Notes.Add("TDXID came from datacache.json, which is currently the strongest local identity candidate.");
        }

        if (report.ValueMap.TryGetValue("SAVEZH", out var saveZhValue))
        {
            report.Notes.Add($"usercomm.ini:SAVEZH={saveZhValue} is treated as a persistence flag only; it is not used as an L2ZH proxy.");
        }

        if (report.ValueMap.ContainsKey("TPSession") || report.ValueMap.ContainsKey("TDXToken"))
        {
            report.Notes.Add("Cached session/token materials are present; these are the current best substitutes for live tpbus SSO request fields.");
        }

        if (report.ValueMap.TryGetValue("ConnectQSID", out var connectQsid))
        {
            report.Notes.Add($"connect.cfg exposes QSID={connectQsid}; treat this as a low-confidence InputQSID candidate, not proof of tc.dll login arg semantics.");
        }

        if (report.ValueMap.TryGetValue("JYMainQSID", out var jyMainQsid)
            && report.ValueMap.TryGetValue("ConnectQSID", out connectQsid)
            && !string.Equals(jyMainQsid, connectQsid, StringComparison.OrdinalIgnoreCase))
        {
            report.Notes.Add("JYMainQSID and connect.cfg QSID differ; treat broker-group and QSID hypotheses as separate candidate axes.");
        }

        if (report.ValueMap.ContainsKey("WTPreNAME"))
        {
            report.Notes.Add("connect.cfg:WTPreNAME is present; treat it as a low-confidence trading/broker display name axis, not a confirmed YYBID.");
        }

        if (report.ValueMap.ContainsKey("TdxWl2ApplySsoResult"))
        {
            report.Notes.Add("Built TdxWL2 applysso request/result JSON from live runtime materials; these match the live heap shape observed in tdxw.exe.");
        }

        return report;
    }

    private static void AddTdxWl2RuntimeMaterials(CachedLoginMaterialsReport report)
    {
        if (!report.ValueMap.TryGetValue("TDXID", out var tdxId)
            || !report.ValueMap.TryGetValue("L2ZH", out var l2Zh)
            || !report.ValueMap.TryGetValue("L2Right", out var l2Right))
        {
            return;
        }

        var sysSource = report.ValueMap.TryGetValue("SysSource", out var resolvedSysSource)
            ? resolvedSysSource
            : report.ValueMap.TryGetValue("ConnectQSID", out var connectQsid)
                ? connectQsid
                : string.Empty;
        var phoneName = report.ValueMap.TryGetValue("RegPhone", out var regPhone)
            ? MaskPhoneName(regPhone)
            : string.Empty;

        AddMaterial(report, "DataName", "TdxWL2", "derived:tdxwl2");
        AddMaterial(report, "RightInfo", l2Right, "derived:L2Right");

        var applySsoRequest = JsonSerializer.Serialize(
            new[]
            {
                new
                {
                    TDXID = tdxId,
                    ZHLB = "99",
                    SSOMode = 13,
                    SysSource = sysSource,
                    Reserve = new
                    {
                        L2ZH = l2Zh,
                        L2Right = l2Right,
                    },
                },
            },
            JsonOptions.Compact);
        AddMaterial(report, "TdxWl2ApplySsoRequest", applySsoRequest, "derived:tdxwl2-applysso-request");

        var applySsoResult = JsonSerializer.Serialize(
            new
            {
                TDXID = tdxId,
                PhoneName = phoneName,
                NickName = string.Empty,
                RightInfo = l2Right,
                L2ZH = l2Zh,
                QSHQToken = string.Empty,
                Code = 0,
                DataName = "TdxWL2",
            },
            JsonOptions.Compact);
        AddMaterial(report, "TdxWl2ApplySsoResult", applySsoResult, "derived:tdxwl2-applysso-result");
    }

    private static string MaskPhoneName(string value)
    {
        var digits = new string(value.Where(char.IsDigit).ToArray());
        if (digits.Length >= 7)
        {
            return digits[..3] + "****" + digits[^4..];
        }

        return value;
    }

    private static void TryLoadLiveRuntimeMaterials(CachedLoginMaterialsReport report, string tdxRoot)
    {
        var expectedPath = Path.GetFullPath(Path.Combine(tdxRoot, "tdxw.exe"));
        var candidate = TrySelectLiveTdxProcess(expectedPath);
        if (candidate is null)
        {
            report.Notes.Add("No running tdxw.exe matched the current TDX root; live L2ZH material was not loaded.");
            return;
        }

        report.LiveRuntimeProcessId = candidate.ProcessId;
        report.LiveRuntimeProcessPath = candidate.ProcessPath;

        if (!TryReadLiveCStringObject(candidate.ProcessId, LiveL2ZhCStringAddress, out var l2ZhValue, out var error))
        {
            report.Notes.Add(
                $"Live runtime probe failed for pid={candidate.ProcessId} at 0x{LiveL2ZhCStringAddress:X8}: {error}");
        }
        else if (string.IsNullOrWhiteSpace(l2ZhValue))
        {
            report.Notes.Add($"Live runtime probe for pid={candidate.ProcessId} returned an empty L2ZH string.");
        }
        else
        {
            AddMaterial(report, "L2ZH", l2ZhValue, $@"process://tdxw.exe/{candidate.ProcessId}/0x{LiveL2ZhCStringAddress:X8}");
            report.Notes.Add(
                $"Loaded live L2ZH from running tdxw.exe pid={candidate.ProcessId}; persisted files still do not expose a confirmed L2ZH value.");
        }

        if (!TryReadLiveAnsiBuffer(candidate.ProcessId, LiveL2RightCStringAddress, 256, out var l2RightValue, out error))
        {
            report.Notes.Add(
                $"Live runtime probe failed for pid={candidate.ProcessId} at 0x{LiveL2RightCStringAddress:X8}: {error}");
        }
        else if (!string.IsNullOrWhiteSpace(l2RightValue))
        {
            AddMaterial(report, "L2Right", l2RightValue, $@"process://tdxw.exe/{candidate.ProcessId}/0x{LiveL2RightCStringAddress:X8}");
        }
        else
        {
            report.Notes.Add($"Live runtime probe for pid={candidate.ProcessId} returned an empty L2Right string.");
        }

        if (!TryReadLiveAnsiBuffer(candidate.ProcessId, LiveSysSourceCStringAddress, 256, out var sysSourceValue, out error))
        {
            report.Notes.Add(
                $"Live runtime probe failed for pid={candidate.ProcessId} at 0x{LiveSysSourceCStringAddress:X8}: {error}");
        }
        else if (!string.IsNullOrWhiteSpace(sysSourceValue))
        {
            AddMaterial(report, "SysSource", sysSourceValue, $@"process://tdxw.exe/{candidate.ProcessId}/0x{LiveSysSourceCStringAddress:X8}");
        }
        else
        {
            report.Notes.Add($"Live runtime probe for pid={candidate.ProcessId} returned an empty SysSource string.");
        }
    }

    private static LiveProcessCandidate? TrySelectLiveTdxProcess(string expectedPath)
    {
        var candidates = new List<LiveProcessCandidate>();
        foreach (var process in Process.GetProcessesByName("tdxw"))
        {
            using (process)
            {
                var path = TryGetProcessPath(process);
                if (string.IsNullOrWhiteSpace(path))
                {
                    continue;
                }

                candidates.Add(
                    new LiveProcessCandidate
                    {
                        ProcessId = process.Id,
                        ProcessPath = path,
                        MatchesExpectedPath = string.Equals(
                            Path.GetFullPath(path),
                            expectedPath,
                            StringComparison.OrdinalIgnoreCase),
                        StartedAtUtc = TryGetProcessStartTimeUtc(process),
                    });
            }
        }

        return candidates
            .OrderByDescending(candidate => candidate.MatchesExpectedPath)
            .ThenByDescending(candidate => candidate.StartedAtUtc)
            .FirstOrDefault();
    }

    private static string? TryGetProcessPath(Process process)
    {
        try
        {
            return process.MainModule?.FileName;
        }
        catch
        {
            return null;
        }
    }

    private static DateTime TryGetProcessStartTimeUtc(Process process)
    {
        try
        {
            return process.StartTime.ToUniversalTime();
        }
        catch
        {
            return DateTime.MinValue;
        }
    }

    private static bool TryReadLiveCStringObject(int processId, int staticAddress, out string? value, out string error)
    {
        value = null;
        error = string.Empty;

        var access = ProcessVmRead | ProcessQueryInformation | ProcessQueryLimitedInformation;
        var handle = NativeMethods.OpenProcess(access, false, processId);
        if (handle == IntPtr.Zero)
        {
            error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            return false;
        }

        try
        {
            if (!TryReadProcessBytes(handle, staticAddress, sizeof(int), out var pointerBytes) || pointerBytes.Length < sizeof(int))
            {
                error = "failed to read CString pointer";
                return false;
            }

            var pointer = BitConverter.ToInt32(pointerBytes, 0);
            if (pointer == 0)
            {
                error = "CString pointer is null";
                return false;
            }

            if (!TryReadProcessBytes(handle, pointer, 512, out var stringBytes) || stringBytes.Length == 0)
            {
                error = "failed to read CString payload";
                return false;
            }

            var end = Array.IndexOf(stringBytes, (byte)0);
            if (end < 0)
            {
                end = stringBytes.Length;
            }

            value = Encoding.GetEncoding("GB18030").GetString(stringBytes, 0, end).Trim();
            return true;
        }
        catch (Exception exception)
        {
            error = exception.Message;
            return false;
        }
        finally
        {
            NativeMethods.CloseHandle(handle);
        }
    }

    private static bool TryReadLiveAnsiBuffer(int processId, int staticAddress, int maxBytes, out string? value, out string error)
    {
        value = null;
        error = string.Empty;

        var access = ProcessVmRead | ProcessQueryInformation | ProcessQueryLimitedInformation;
        var handle = NativeMethods.OpenProcess(access, false, processId);
        if (handle == IntPtr.Zero)
        {
            error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            return false;
        }

        try
        {
            if (!TryReadProcessBytes(handle, staticAddress, maxBytes, out var stringBytes) || stringBytes.Length == 0)
            {
                error = "failed to read inline ANSI buffer";
                return false;
            }

            var end = Array.IndexOf(stringBytes, (byte)0);
            if (end < 0)
            {
                end = stringBytes.Length;
            }

            value = Encoding.GetEncoding("GB18030").GetString(stringBytes, 0, end).Trim();
            return true;
        }
        catch (Exception exception)
        {
            error = exception.Message;
            return false;
        }
        finally
        {
            NativeMethods.CloseHandle(handle);
        }
    }

    private static bool TryReadProcessBytes(IntPtr handle, int address, int size, out byte[] bytes)
    {
        bytes = Array.Empty<byte>();
        var buffer = new byte[size];
        if (!NativeMethods.ReadProcessMemory(handle, new IntPtr(address), buffer, size, out var bytesRead))
        {
            return false;
        }

        if (bytesRead <= 0)
        {
            return false;
        }

        if (bytesRead == size)
        {
            bytes = buffer;
            return true;
        }

        bytes = buffer[..bytesRead];
        return true;
    }

    private static List<CachedLoginProfile> BuildCachedLoginProfiles(CachedLoginMaterialsReport materials)
    {
        var profiles = new List<CachedLoginProfile>();
        var seen = new HashSet<string>(StringComparer.Ordinal);

        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-oid-reguid", "TDXID", "TDXToken", "OID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-oid-reguid", "TDXID", "TPSession", "OID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-userpuid-oid", "TDXID", "TDXToken", "UserPUID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-userpuid-oid", "TDXID", "TPSession", "UserPUID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-oid", "TDXID", "TDXToken", "ConnectQSID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-connectqsid-oid", "TDXID", "TPSession", "ConnectQSID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-oid", "TDXID", "TDXToken", "JYMainQSID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-jymainqsid-oid", "TDXID", "TPSession", "JYMainQSID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-reguid", "TDXID", "TDXToken", "ConnectQSID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-connectqsid-reguid", "TDXID", "TPSession", "ConnectQSID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-userpuid", "TDXID", "TDXToken", "ConnectQSID", "UserPUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-empty", "TDXID", "TDXToken", "ConnectQSID", null);
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-hostip", "TDXID", "TDXToken", "ConnectQSID", "HostIP");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-embedyybid-oid", "TDXID", "TDXToken", "Embed_YybID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-embedyybid-oid", "TDXID", "TPSession", "Embed_YybID", "OID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-jymainqsid", "TDXID", "TDXToken", "ConnectQSID", "JYMainQSID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-connectqsid-jymainqsid", "TDXID", "TPSession", "ConnectQSID", "JYMainQSID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-connectqsid", "TDXID", "TDXToken", "JYMainQSID", "ConnectQSID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-jymainqsid-connectqsid", "TDXID", "TPSession", "JYMainQSID", "ConnectQSID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-lastlogintype", "TDXID", "TDXToken", "ConnectQSID", "LastLoginType");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-connectqsid-lastlogintype", "TDXID", "TPSession", "ConnectQSID", "LastLoginType");
        AddProfile(profiles, seen, materials.ValueMap, "userpuid-token-connectqsid-jymainqsid", "UserPUID", "TDXToken", "ConnectQSID", "JYMainQSID");
        AddProfile(profiles, seen, materials.ValueMap, "userpuid-session-connectqsid-jymainqsid", "UserPUID", "TPSession", "ConnectQSID", "JYMainQSID");
        AddProfile(profiles, seen, materials.ValueMap, "reguid-token-connectqsid-jymainqsid", "RegUID", "TDXToken", "ConnectQSID", "JYMainQSID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-connectqsid-wtprename", "TDXID", "TDXToken", "ConnectQSID", "WTPreNAME");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-connectqsid-wtprename", "TDXID", "TPSession", "ConnectQSID", "WTPreNAME");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-reguid", "TDXID", "TDXToken", "JYMainQSID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-userpuid", "TDXID", "TDXToken", "JYMainQSID", "UserPUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-empty", "TDXID", "TDXToken", "JYMainQSID", null);
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-jymainqsid-hostip", "TDXID", "TDXToken", "JYMainQSID", "HostIP");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-reguid-hostip", "TDXID", "TDXToken", "RegUID", "HostIP");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-reguid-hostip", "TDXID", "TPSession", "RegUID", "HostIP");
        AddProfile(profiles, seen, materials.ValueMap, "userpuid-session-oid-reguid", "UserPUID", "TPSession", "OID", "RegUID");
        AddProfile(profiles, seen, materials.ValueMap, "reguid-session-oid-userpuid", "RegUID", "TPSession", "OID", "UserPUID");
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-token-reguid-empty", "TDXID", "TDXToken", "RegUID", null);
        AddProfile(profiles, seen, materials.ValueMap, "tdxid-session-reguid-empty", "TDXID", "TPSession", "RegUID", null);

        return profiles;
    }

    private static List<SetL2CandidateProfile> BuildSetL2CandidateProfiles(CachedLoginMaterialsReport materials)
    {
        var profiles = new List<SetL2CandidateProfile>();
        var seen = new HashSet<string>(StringComparer.Ordinal);

        var identityKeys = new List<string> { "TDXID" };
        if (materials.ValueMap.ContainsKey("L2ZH"))
        {
            identityKeys.Add("L2ZH");
        }
        string?[] tailKeys = { null, "ConnectQSID", "JYMainQSID", "OID", "L2Right", "SysSource" };
        foreach (var identityKey in identityKeys)
        {
            foreach (var tailKey in tailKeys)
            {
                var tailName = (tailKey ?? "empty").ToLowerInvariant();
                var identityName = identityKey.ToLowerInvariant();
                AddSetL2Profile(
                    profiles,
                    seen,
                    $"citicscfv-{identityName}-{tailName}",
                    "CITICS#CFV",
                    "literal:CITICS#CFV",
                    identityKey,
                    tailKey,
                    materials.ValueMap);
                AddSetL2Profile(
                    profiles,
                    seen,
                    $"{identityName}-citicscfv-{tailName}",
                    identityKey,
                    identityKey,
                    "CITICS#CFV",
                    tailKey,
                    materials.ValueMap,
                    secondSource: "literal:CITICS#CFV");
            }
        }

        AddSetL2Profile(profiles, seen, "tdxwl2-l2zh-rightinfo", "TdxWL2", "literal:TdxWL2", "L2ZH", "RightInfo", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-rightinfo-l2zh", "TdxWL2", "literal:TdxWL2", "RightInfo", "L2ZH", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-l2zh-syssource", "TdxWL2", "literal:TdxWL2", "L2ZH", "SysSource", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxid-l2zh-rightinfo", "TDXID", "TDXID", "L2ZH", "RightInfo", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "l2zh-rightinfo-syssource", "L2ZH", "L2ZH", "RightInfo", "SysSource", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "citicscfv-l2zh-tdxwl2-result", "CITICS#CFV", "literal:CITICS#CFV", "L2ZH", "TdxWl2ApplySsoResult", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-l2zh-tdxwl2-result", "TdxWL2", "literal:TdxWL2", "L2ZH", "TdxWl2ApplySsoResult", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-tdxid-tdxwl2-result", "TdxWL2", "literal:TdxWL2", "TDXID", "TdxWl2ApplySsoResult", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-request-result", "TdxWL2", "literal:TdxWL2", "TdxWl2ApplySsoRequest", "TdxWl2ApplySsoResult", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "tdxwl2-result-request", "TdxWL2", "literal:TdxWL2", "TdxWl2ApplySsoResult", "TdxWl2ApplySsoRequest", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "result-tdxwl2-request", "TdxWl2ApplySsoResult", "TdxWl2ApplySsoResult", "DataName", "TdxWl2ApplySsoRequest", materials.ValueMap);
        AddSetL2Profile(profiles, seen, "request-tdxwl2-result", "TdxWl2ApplySsoRequest", "TdxWl2ApplySsoRequest", "DataName", "TdxWl2ApplySsoResult", materials.ValueMap);

        return profiles;
    }

    private static SetL2CandidateProfile? BuildDirectSetL2CandidateProfile(CliOptions options)
    {
        if (!options.HasSetL2Args)
        {
            return null;
        }

        return new SetL2CandidateProfile
        {
            Name = "direct-cli",
            Arguments =
            {
                new SetL2CandidateArgument { Slot = 1, Source = "setl2-arg1", Value = options.SetL2Arg1 },
                new SetL2CandidateArgument { Slot = 2, Source = "setl2-arg2", Value = options.SetL2Arg2 },
                new SetL2CandidateArgument { Slot = 3, Source = "setl2-arg3", Value = options.SetL2Arg3 },
            },
        };
    }

    private static void AddSetL2Profile(
        ICollection<SetL2CandidateProfile> profiles,
        ISet<string> seen,
        string name,
        string firstValueOrKey,
        string firstSource,
        string secondValueOrKey,
        string? thirdKey,
        IReadOnlyDictionary<string, string>? values,
        string? secondSource = null)
    {
        var arguments = new List<SetL2CandidateArgument>
        {
            BuildSetL2Argument(1, firstValueOrKey, firstSource, values),
            BuildSetL2Argument(2, secondValueOrKey, secondSource ?? secondValueOrKey, values),
            BuildSetL2Argument(3, thirdKey, thirdKey ?? "empty", values),
        };

        if (arguments[0].Value is null || arguments[1].Value is null)
        {
            return;
        }

        var signature = string.Join(
            "|",
            arguments.Select(argument => $"{argument.Slot}:{argument.Source}:{argument.Value ?? string.Empty}"));
        if (!seen.Add(signature))
        {
            return;
        }

        profiles.Add(
            new SetL2CandidateProfile
            {
                Name = name,
                Arguments = arguments,
            });
    }

    private static SetL2CandidateArgument BuildSetL2Argument(
        int slot,
        string? valueOrKey,
        string source,
        IReadOnlyDictionary<string, string>? values)
    {
        if (string.IsNullOrWhiteSpace(valueOrKey))
        {
            return new SetL2CandidateArgument
            {
                Slot = slot,
                Source = source,
                Value = null,
            };
        }

        if (source.StartsWith("literal:", StringComparison.Ordinal))
        {
            return new SetL2CandidateArgument
            {
                Slot = slot,
                Source = source["literal:".Length..],
                Value = valueOrKey,
            };
        }

        if (source.EndsWith("#CFV", StringComparison.Ordinal) && valueOrKey.EndsWith("#CFV", StringComparison.Ordinal))
        {
            return new SetL2CandidateArgument
            {
                Slot = slot,
                Source = source,
                Value = valueOrKey,
            };
        }

        if (values is not null && values.TryGetValue(valueOrKey, out var resolved) && !string.IsNullOrWhiteSpace(resolved))
        {
            return new SetL2CandidateArgument
            {
                Slot = slot,
                Source = source,
                Value = resolved,
            };
        }

        return new SetL2CandidateArgument
        {
            Slot = slot,
            Source = source,
            Value = null,
        };
    }

    private static List<SetL2CandidateProfile> ApplySetL2ProfileFilter(List<SetL2CandidateProfile> profiles, CliOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.ProfileFilter))
        {
            return profiles;
        }

        var terms = options.ProfileFilter
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(term => !string.IsNullOrWhiteSpace(term))
            .ToArray();
        if (terms.Length == 0)
        {
            return profiles;
        }

        return profiles
            .Where(
                profile => terms.Any(
                    term => profile.Name.Contains(term, StringComparison.OrdinalIgnoreCase)
                        || profile.Arguments.Any(argument => argument.Source.Contains(term, StringComparison.OrdinalIgnoreCase))))
            .ToList();
    }

    private static void AddProfile(
        ICollection<CachedLoginProfile> profiles,
        ISet<string> seen,
        IReadOnlyDictionary<string, string> values,
        string name,
        string? arg1Key,
        string? arg2Key,
        string? arg3Key,
        string? arg4Key)
    {
        var arguments = new List<CachedLoginArgument>
        {
            BuildProfileArgument(1, arg1Key, values),
            BuildProfileArgument(2, arg2Key, values),
            BuildProfileArgument(3, arg3Key, values),
            BuildProfileArgument(4, arg4Key, values),
        };

        if (arguments[0].Value is null || arguments[1].Value is null)
        {
            return;
        }

        if (arg3Key is not null && arguments[2].Value is null)
        {
            return;
        }

        if (arg4Key is not null && arguments[3].Value is null)
        {
            return;
        }

        if (arguments.Count(argument => !string.IsNullOrWhiteSpace(argument.Value)) < 3)
        {
            return;
        }

        var signature = string.Join(
            "|",
            arguments.Select(argument => $"{argument.Slot}:{argument.Source}:{argument.Value ?? string.Empty}"));

        if (!seen.Add(signature))
        {
            return;
        }

        profiles.Add(new CachedLoginProfile
        {
            Name = name,
            Arguments = arguments,
        });
    }

    private static CachedLoginArgument BuildProfileArgument(
        int slot,
        string? key,
        IReadOnlyDictionary<string, string> values)
    {
        if (key is null)
        {
            return new CachedLoginArgument
            {
                Slot = slot,
                Source = "empty",
            };
        }

        values.TryGetValue(key, out var value);
        return new CachedLoginArgument
        {
            Slot = slot,
            Source = key,
            Value = string.IsNullOrWhiteSpace(value) ? null : value,
        };
    }

    private static void AddMaterial(
        CachedLoginMaterialsReport report,
        string key,
        string? value,
        string source)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        value = value.Trim();
        report.Entries.Add(new CachedLoginMaterialSnapshot
        {
            Key = key,
            Source = source,
            ValueLength = value.Length,
            MaskedValue = MaskValue(value),
        });

        if (!report.ValueMap.ContainsKey(key))
        {
            report.ValueMap[key] = value;
            return;
        }

        if (!string.Equals(report.ValueMap[key], value, StringComparison.Ordinal))
        {
            report.Notes.Add($"Conflicting cached value for {key}; keeping the first discovered source.");
        }
    }

    private static Dictionary<string, string> LoadIniValues(string path)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!File.Exists(path))
        {
            return values;
        }

        foreach (var rawLine in File.ReadAllLines(path, Encoding.GetEncoding("GB18030")))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith(";") || line.StartsWith("#") || line.StartsWith("["))
            {
                continue;
            }

            var separator = line.IndexOf('=');
            if (separator <= 0)
            {
                continue;
            }

            var key = line[..separator].Trim();
            var value = line[(separator + 1)..].Trim();
            if (key.Length == 0)
            {
                continue;
            }

            values[key] = value;
        }

        return values;
    }

    private static string? TryGetValue(IReadOnlyDictionary<string, string> values, string key)
    {
        return values.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : null;
    }

    private static string? NullIfZeroOrWhiteSpace(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return null;
        }

        value = value.Trim();
        return string.Equals(value, "0", StringComparison.Ordinal) ? null : value;
    }

    private static string? TryGetJsonString(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var property))
        {
            return null;
        }

        return property.ValueKind switch
        {
            JsonValueKind.String => property.GetString(),
            JsonValueKind.Number => property.ToString(),
            JsonValueKind.True => bool.TrueString,
            JsonValueKind.False => bool.FalseString,
            _ => null,
        };
    }

    private static MaskedArgumentSnapshot ToMaskedArgumentSnapshot(CachedLoginArgument argument)
    {
        return new MaskedArgumentSnapshot
        {
            Slot = argument.Slot,
            Source = argument.Source,
            Provided = !string.IsNullOrWhiteSpace(argument.Value),
            ValueLength = argument.Value?.Length ?? 0,
            MaskedValue = argument.Value is null ? string.Empty : MaskValue(argument.Value),
        };
    }

    private static MaskedArgumentSnapshot ToMaskedArgumentSnapshot(SetL2CandidateArgument argument)
    {
        return new MaskedArgumentSnapshot
        {
            Slot = argument.Slot,
            Source = argument.Source,
            Provided = !string.IsNullOrWhiteSpace(argument.Value),
            ValueLength = argument.Value?.Length ?? 0,
            MaskedValue = argument.Value is null ? string.Empty : MaskValue(argument.Value),
        };
    }

    private static TcLoginRequestSnapshot BuildLoginRequestSnapshot(CliOptions options)
    {
        var profileName = !string.IsNullOrWhiteSpace(options.ResolvedLoginProfile)
            ? options.ResolvedLoginProfile
            : HasDirectLoginArguments(options)
                ? "direct-cli"
                : string.Empty;

        return new TcLoginRequestSnapshot
        {
            Function = options.LoginFunction ?? string.Empty,
            ProfileName = profileName ?? string.Empty,
            Arg1Provided = !string.IsNullOrWhiteSpace(options.LoginArg1),
            Arg2Provided = !string.IsNullOrWhiteSpace(options.LoginArg2),
            Arg3Provided = !string.IsNullOrWhiteSpace(options.LoginArg3),
            Arg4Provided = !string.IsNullOrWhiteSpace(options.LoginArg4),
        };
    }

    private static bool HasDirectLoginArguments(CliOptions options)
    {
        return !string.IsNullOrWhiteSpace(options.LoginArg1)
            || !string.IsNullOrWhiteSpace(options.LoginArg2)
            || !string.IsNullOrWhiteSpace(options.LoginArg3)
            || !string.IsNullOrWhiteSpace(options.LoginArg4);
    }

    private static string MaskValue(string value)
    {
        if (value.Length <= 2)
        {
            return new string('*', value.Length);
        }

        if (value.Length <= 8)
        {
            return $"{value[0]}***{value[^1]}";
        }

        return $"{value[..4]}...{value[^4..]}";
    }


    private static RuntimeLayoutReport SyncRuntimeLayout(CliOptions options)
    {
        return SyncRuntimeLayout(options, "sync-runtime-layout");
    }

    private static RuntimeLayoutReport SyncRuntimeLayout(CliOptions options, string commandName)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var report = CaptureRuntimeLayout(tdxRoot, commandName);

        EnsureDirectory(Path.Combine(report.AppBaseDirectory, "Users"));
        EnsureDirectory(Path.Combine(report.AppBaseDirectory, "Users", "Profile"));
        EnsurePlaceholderXml(
            Path.Combine(report.AppBaseDirectory, "eTrade.xml"),
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<ProfileOfSystem/>\n",
            report);
        EnsurePlaceholderXml(
            Path.Combine(report.AppBaseDirectory, "TcOem.xml"),
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<ProfileOfOEM/>\n",
            report);

        CopyFileIfNeeded(
            Path.Combine(tdxRoot, "etrade.xmb"),
            Path.Combine(report.AppBaseDirectory, "etrade.xmb"),
            report);
        CopyFileIfNeeded(
            ResolveExistingPath(Path.Combine(tdxRoot, "TcOem.xmb"), Path.Combine(tdxRoot, "tcoem.xmb")),
            Path.Combine(report.AppBaseDirectory, "TcOem.xmb"),
            report);
        SyncPluginsDirectory(
            Path.Combine(tdxRoot, "TCPlugins"),
            Path.Combine(report.AppBaseDirectory, "TCPlugins"),
            report);

        return CaptureRuntimeLayout(tdxRoot, commandName, report);
    }

    private static RuntimeLayoutReport CaptureRuntimeLayout(
        string tdxRoot,
        string commandName,
        RuntimeLayoutReport? existing = null)
    {
        var report = existing ?? new RuntimeLayoutReport();
        var appBaseDirectory = Path.GetFullPath(AppContext.BaseDirectory);

        report.GeneratedAt = DateTimeOffset.Now;
        report.Command = commandName;
        report.TdxRoot = tdxRoot;
        report.AppBaseDirectory = appBaseDirectory;
        report.CurrentDirectory = Directory.GetCurrentDirectory();
        report.TcPluginsPath = Path.Combine(appBaseDirectory, "TCPlugins");
        report.TcPluginsDllCount = CountFiles(report.TcPluginsPath, "*.dll");
        report.EtradeXmbPath = Path.Combine(appBaseDirectory, "etrade.xmb");
        report.EtradeXmbPresent = File.Exists(report.EtradeXmbPath);
        report.TcOemXmbPath = Path.Combine(appBaseDirectory, "TcOem.xmb");
        report.TcOemXmbPresent = File.Exists(report.TcOemXmbPath);
        report.EtradeXmlPath = Path.Combine(appBaseDirectory, "eTrade.xml");
        report.EtradeXmlPresent = File.Exists(report.EtradeXmlPath);
        report.TcOemXmlPath = Path.Combine(appBaseDirectory, "TcOem.xml");
        report.TcOemXmlPresent = File.Exists(report.TcOemXmlPath);
        report.UsersProfilePath = Path.Combine(appBaseDirectory, "Users", "Profile");
        report.UsersProfilePresent = Directory.Exists(report.UsersProfilePath);
        report.Ok = report.EtradeXmbPresent
            && report.TcOemXmbPresent
            && report.TcPluginsDllCount > 0
            && report.UsersProfilePresent
            && report.Errors.Count == 0;

        if (!report.Notes.Any())
        {
            report.Notes.Add("tc.dll consults the helper executable directory for eTrade.xmb / TcOem.xmb / TCPlugins during TC_Init_Environ.");
            report.Notes.Add("Setting only --tdx-root or the current directory is not sufficient when the host runtime layout is incomplete.");
        }

        return report;
    }

    private static void EnsurePlaceholderXml(string path, string contents, RuntimeLayoutReport report)
    {
        if (File.Exists(path))
        {
            return;
        }

        File.WriteAllText(path, contents, Encoding.UTF8);
        report.SyncedItems.Add(path);
    }

    private static void SyncPluginsDirectory(string sourceDirectory, string targetDirectory, RuntimeLayoutReport report)
    {
        if (!Directory.Exists(sourceDirectory))
        {
            report.Errors.Add($"missing source plugin directory: {sourceDirectory}");
            report.Ok = false;
            return;
        }

        var targetInfo = new DirectoryInfo(targetDirectory);
        if (targetInfo.Exists && !string.IsNullOrWhiteSpace(targetInfo.LinkTarget))
        {
            var linkTarget = Path.GetFullPath(targetInfo.LinkTarget);
            if (string.Equals(linkTarget, Path.GetFullPath(sourceDirectory), StringComparison.OrdinalIgnoreCase))
            {
                report.Notes.Add($"TCPlugins already points to the TDX runtime: {targetDirectory} -> {linkTarget}");
                return;
            }
        }

        EnsureDirectory(targetDirectory);
        foreach (var sourcePath in Directory.EnumerateFiles(sourceDirectory, "*.dll"))
        {
            var targetPath = Path.Combine(targetDirectory, Path.GetFileName(sourcePath));
            CopyFileIfNeeded(sourcePath, targetPath, report);
        }
    }

    private static void CopyFileIfNeeded(string sourcePath, string targetPath, RuntimeLayoutReport report)
    {
        if (!File.Exists(sourcePath))
        {
            report.Errors.Add($"missing source file: {sourcePath}");
            report.Ok = false;
            return;
        }

        EnsureDirectory(Path.GetDirectoryName(targetPath)!);

        var shouldCopy = true;
        if (File.Exists(targetPath))
        {
            var sourceInfo = new FileInfo(sourcePath);
            var targetInfo = new FileInfo(targetPath);
            shouldCopy = sourceInfo.Length != targetInfo.Length
                || sourceInfo.LastWriteTimeUtc != targetInfo.LastWriteTimeUtc;
        }

        if (!shouldCopy)
        {
            return;
        }

        File.Copy(sourcePath, targetPath, overwrite: true);
        File.SetLastWriteTimeUtc(targetPath, File.GetLastWriteTimeUtc(sourcePath));
        report.SyncedItems.Add(targetPath);
    }

    private static string ResolveExistingPath(params string[] candidates)
    {
        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return candidates[0];
    }

    private static void EnsureDirectory(string path)
    {
        if (!Directory.Exists(path))
        {
            Directory.CreateDirectory(path);
        }
    }

    private static int CountFiles(string directory, string filter)
    {
        return Directory.Exists(directory) ? Directory.EnumerateFiles(directory, filter).Count() : 0;
    }

    private static TcInitCallReport InvokeTcInitEnviron(TcInitEnvironFn init, CliOptions options)
    {
        using var arg1 = OptionalAnsiString.From(options.InitArg1);
        using var arg2 = OptionalAnsiString.From(options.InitArg2);
        using var arg3 = OptionalAnsiString.From(options.InitArg3);
        using var arg5 = OptionalAnsiString.From(options.InitArg5);

        var started = DateTime.UtcNow;
        var report = new TcInitCallReport { Invoked = true };
        try
        {
            var returnValue = init(
                arg1.Pointer,
                arg2.Pointer,
                arg3.Pointer,
                IntPtr.Zero,
                arg5.Pointer,
                options.InitArg6);

            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcLoginCallReport InvokeTcLogin(TcLoginFn login, string functionName, CliOptions options)
    {
        using var arg1 = OptionalAnsiString.From(options.LoginArg1);
        using var arg2 = OptionalAnsiString.From(options.LoginArg2);
        using var arg3 = OptionalAnsiString.From(options.LoginArg3);
        using var arg4 = OptionalAnsiString.From(options.LoginArg4);

        var started = DateTime.UtcNow;
        var report = new TcLoginCallReport
        {
            Invoked = true,
            Function = functionName,
        };

        try
        {
            var returnValue = login(arg1.Pointer, arg2.Pointer, arg3.Pointer, arg4.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcLoginCallReport InvokeTcLogin(TcLoginFn login, string functionName, CachedLoginProfile profile)
    {
        var arg1Value = profile.Arguments.FirstOrDefault(argument => argument.Slot == 1)?.Value;
        var arg2Value = profile.Arguments.FirstOrDefault(argument => argument.Slot == 2)?.Value;
        var arg3Value = profile.Arguments.FirstOrDefault(argument => argument.Slot == 3)?.Value;
        var arg4Value = profile.Arguments.FirstOrDefault(argument => argument.Slot == 4)?.Value;

        using var arg1 = OptionalAnsiString.From(arg1Value);
        using var arg2 = OptionalAnsiString.From(arg2Value);
        using var arg3 = OptionalAnsiString.From(arg3Value);
        using var arg4 = OptionalAnsiString.From(arg4Value);

        var started = DateTime.UtcNow;
        var report = new TcLoginCallReport
        {
            Invoked = true,
            Function = functionName,
        };

        try
        {
            var returnValue = login(arg1.Pointer, arg2.Pointer, arg3.Pointer, arg4.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcGetLoginRetCallReport InvokeTcGetLoginRet(TcGetLoginRetFn getLoginRet, int bufferSize)
    {
        using var arg1 = new HGlobalBuffer(bufferSize);

        var started = DateTime.UtcNow;
        var report = new TcGetLoginRetCallReport
        {
            Invoked = true,
            BufferSize = bufferSize,
        };

        try
        {
            var returnValue = getLoginRet(arg1.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
            report.Arg1 = BufferSnapshot.From(arg1);
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcGetRightInfoCallReport InvokeTcGetRightInfo(TcGetRightInfoFn getRightInfo, int bufferSize)
    {
        using var arg1 = new HGlobalBuffer(bufferSize);
        using var arg2 = new HGlobalBuffer(bufferSize);
        using var arg3 = new HGlobalBuffer(bufferSize);

        var started = DateTime.UtcNow;
        var report = new TcGetRightInfoCallReport
        {
            Invoked = true,
            BufferSize = bufferSize,
        };

        try
        {
            var returnValue = getRightInfo(arg1.Pointer, arg2.Pointer, arg3.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
            report.Arg1 = BufferSnapshot.From(arg1);
            report.Arg2 = BufferSnapshot.From(arg2);
            report.Arg3 = BufferSnapshot.From(arg3);
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcGetL2InfoCallReport InvokeTcGetL2Info(TcGetL2InfoFn getL2Info, int bufferSize)
    {
        using var arg1 = new HGlobalBuffer(bufferSize);
        using var arg2 = new HGlobalBuffer(bufferSize);

        var started = DateTime.UtcNow;
        var report = new TcGetL2InfoCallReport
        {
            Invoked = true,
            BufferSize = bufferSize,
        };

        try
        {
            var returnValue = getL2Info(arg1.Pointer, arg2.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
            report.Arg1 = BufferSnapshot.From(arg1);
            report.Arg2 = BufferSnapshot.From(arg2);
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static TcSetL2UserInfoCallReport InvokeTcSetL2UserInfo(TcSetL2UserInfoFn setL2UserInfo, CliOptions options)
    {
        using var arg1 = OptionalAnsiString.From(options.SetL2Arg1);
        using var arg2 = OptionalAnsiString.From(options.SetL2Arg2);
        using var arg3 = OptionalAnsiString.From(options.SetL2Arg3);

        var started = DateTime.UtcNow;
        var report = new TcSetL2UserInfoCallReport { Invoked = true };
        try
        {
            var returnValue = setL2UserInfo(arg1.Pointer, arg2.Pointer, arg3.Pointer);
            report.ReturnValue = returnValue;
            report.Win32LastError = Marshal.GetLastWin32Error();
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static int ComputeSignalScore(TcLoginMatrixAttemptReport attempt)
    {
        var score = 0;

        if (attempt.LoginResult?.ReturnValue != 0)
        {
            score += 1;
        }

        if (HasStateDelta(attempt.PreGetLoginRet?.Arg1, attempt.PostGetLoginRet?.Arg1))
        {
            score += 4;
        }

        if (HasStateDelta(attempt.PreGetRightInfo?.Arg1, attempt.PostGetRightInfo?.Arg1))
        {
            score += 3;
        }

        if (HasStateDelta(attempt.PreGetRightInfo?.Arg2, attempt.PostGetRightInfo?.Arg2))
        {
            score += 2;
        }

        if (HasStateDelta(attempt.PreGetRightInfo?.Arg3, attempt.PostGetRightInfo?.Arg3))
        {
            score += 2;
        }

        if (HasStateDelta(attempt.PreGetL2Info?.Arg1, attempt.PostGetL2Info?.Arg1))
        {
            score += 3;
        }

        if (HasStateDelta(attempt.PreGetL2Info?.Arg2, attempt.PostGetL2Info?.Arg2))
        {
            score += 3;
        }

        return score;
    }

    private static int ComputeSetL2SignalScore(TcSetL2ProbeReport report)
    {
        var score = 0;
        var loginInvoked = report.LoginResult?.Invoked == true;

        if (loginInvoked && (report.LoginResult?.ReturnValue ?? 0) != 0)
        {
            score += 1;
        }

        if ((report.SetL2Result?.ReturnValue ?? 0) != 0)
        {
            score += 1;
        }

        if (loginInvoked && HasStateDelta(report.PreLoginGetLoginRet?.Arg1, report.PostLoginGetLoginRet?.Arg1))
        {
            score += 2;
        }

        if (HasStateDelta(report.PreSetL2GetLoginRet?.Arg1, report.PostSetL2GetLoginRet?.Arg1))
        {
            score += 4;
        }

        if (HasStateDelta(report.PreSetL2GetRightInfo?.Arg1, report.PostSetL2GetRightInfo?.Arg1))
        {
            score += 3;
        }

        if (HasStateDelta(report.PreSetL2GetRightInfo?.Arg2, report.PostSetL2GetRightInfo?.Arg2))
        {
            score += 2;
        }

        if (HasStateDelta(report.PreSetL2GetRightInfo?.Arg3, report.PostSetL2GetRightInfo?.Arg3))
        {
            score += 2;
        }

        if (HasStateDelta(report.PreSetL2GetL2Info?.Arg1, report.PostSetL2GetL2Info?.Arg1))
        {
            score += 3;
        }

        if (HasStateDelta(report.PreSetL2GetL2Info?.Arg2, report.PostSetL2GetL2Info?.Arg2))
        {
            score += 3;
        }

        return score;
    }

    private static List<string> BuildSignalHints(TcLoginMatrixAttemptReport attempt)
    {
        var hints = new List<string>();

        AddSignalHint(hints, "loginRet", attempt.PreGetLoginRet?.Arg1, attempt.PostGetLoginRet?.Arg1);
        AddSignalHint(hints, "rightInfo.arg1", attempt.PreGetRightInfo?.Arg1, attempt.PostGetRightInfo?.Arg1);
        AddSignalHint(hints, "rightInfo.arg2", attempt.PreGetRightInfo?.Arg2, attempt.PostGetRightInfo?.Arg2);
        AddSignalHint(hints, "rightInfo.arg3", attempt.PreGetRightInfo?.Arg3, attempt.PostGetRightInfo?.Arg3);
        AddSignalHint(hints, "l2Info.arg1", attempt.PreGetL2Info?.Arg1, attempt.PostGetL2Info?.Arg1);
        AddSignalHint(hints, "l2Info.arg2", attempt.PreGetL2Info?.Arg2, attempt.PostGetL2Info?.Arg2);

        var loginReturnValue = attempt.LoginResult?.ReturnValue;
        if (loginReturnValue is not null && loginReturnValue != 0)
        {
            hints.Add($"loginReturn={loginReturnValue}");
        }

        return hints;
    }

    private static List<string> BuildSetL2SignalHints(TcSetL2ProbeReport report)
    {
        var hints = new List<string>();

        AddSignalHint(hints, "loginPrelude.loginRet", report.PreLoginGetLoginRet?.Arg1, report.PostLoginGetLoginRet?.Arg1);
        AddSignalHint(hints, "loginPrelude.rightInfo.arg1", report.PreLoginGetRightInfo?.Arg1, report.PostLoginGetRightInfo?.Arg1);
        AddSignalHint(hints, "loginPrelude.rightInfo.arg2", report.PreLoginGetRightInfo?.Arg2, report.PostLoginGetRightInfo?.Arg2);
        AddSignalHint(hints, "loginPrelude.rightInfo.arg3", report.PreLoginGetRightInfo?.Arg3, report.PostLoginGetRightInfo?.Arg3);
        AddSignalHint(hints, "loginPrelude.l2Info.arg1", report.PreLoginGetL2Info?.Arg1, report.PostLoginGetL2Info?.Arg1);
        AddSignalHint(hints, "loginPrelude.l2Info.arg2", report.PreLoginGetL2Info?.Arg2, report.PostLoginGetL2Info?.Arg2);

        AddSignalHint(hints, "setl2.loginRet", report.PreSetL2GetLoginRet?.Arg1, report.PostSetL2GetLoginRet?.Arg1);
        AddSignalHint(hints, "setl2.rightInfo.arg1", report.PreSetL2GetRightInfo?.Arg1, report.PostSetL2GetRightInfo?.Arg1);
        AddSignalHint(hints, "setl2.rightInfo.arg2", report.PreSetL2GetRightInfo?.Arg2, report.PostSetL2GetRightInfo?.Arg2);
        AddSignalHint(hints, "setl2.rightInfo.arg3", report.PreSetL2GetRightInfo?.Arg3, report.PostSetL2GetRightInfo?.Arg3);
        AddSignalHint(hints, "setl2.l2Info.arg1", report.PreSetL2GetL2Info?.Arg1, report.PostSetL2GetL2Info?.Arg1);
        AddSignalHint(hints, "setl2.l2Info.arg2", report.PreSetL2GetL2Info?.Arg2, report.PostSetL2GetL2Info?.Arg2);

        var loginReturnValue = report.LoginResult?.ReturnValue;
        if (loginReturnValue is not null && loginReturnValue != 0)
        {
            hints.Add($"loginReturn={loginReturnValue}");
        }

        var setL2ReturnValue = report.SetL2Result?.ReturnValue;
        if (setL2ReturnValue is not null && setL2ReturnValue != 0)
        {
            hints.Add($"setL2Return={setL2ReturnValue}");
        }

        return hints;
    }

    private static void AddSignalHint(List<string> hints, string label, BufferSnapshot? before, BufferSnapshot? after)
    {
        if (!HasStateDelta(before, after) || after is null)
        {
            return;
        }

        var preview = SelectBestPreview(after);
        if (string.IsNullOrWhiteSpace(preview))
        {
            preview = $"changed nonZeroBytes={after.NonZeroBytes}";
        }

        hints.Add($"{label}:{preview}");
    }

    private static string SelectBestPreview(BufferSnapshot snapshot)
    {
        var gb = NormalizePreview(snapshot.Gb18030Preview);
        if (!string.IsNullOrWhiteSpace(gb))
        {
            return gb;
        }

        var ansi = NormalizePreview(snapshot.AnsiPreview);
        if (!string.IsNullOrWhiteSpace(ansi))
        {
            return ansi;
        }

        return string.Empty;
    }

    private static string NormalizePreview(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var text = value.Replace('\0', ' ').Trim();
        if (text.Length <= 96)
        {
            return text;
        }

        return text[..96];
    }

    private static List<TcLoginSignalSummary> BuildSignalSummaries(IEnumerable<TcLoginMatrixAttemptReport> attempts)
    {
        return attempts
            .Select(
                attempt => new
                {
                    Attempt = attempt,
                    Signature = string.Join(" | ", attempt.SignalHints.Where(hint => !string.IsNullOrWhiteSpace(hint))),
                })
            .Where(item => !string.IsNullOrWhiteSpace(item.Signature))
            .GroupBy(item => item.Signature, StringComparer.Ordinal)
            .Select(
                group => new TcLoginSignalSummary
                {
                    Signature = group.Key,
                    AttemptCount = group.Count(),
                    MaxSignalScore = group.Max(item => item.Attempt.SignalScore),
                    StateChanged = group.Any(item => item.Attempt.StateChanged),
                    Functions = group.Select(item => item.Attempt.Function).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(value => value, StringComparer.OrdinalIgnoreCase).ToList(),
                    ProfileNames = group.Select(item => item.Attempt.ProfileName).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(value => value, StringComparer.OrdinalIgnoreCase).ToList(),
                    RepeatIndices = group.Select(item => item.Attempt.RepeatIndex).Distinct().OrderBy(value => value).ToList(),
                })
            .OrderByDescending(summary => summary.AttemptCount)
            .ThenByDescending(summary => summary.MaxSignalScore)
            .ThenBy(summary => summary.Signature, StringComparer.Ordinal)
            .ToList();
    }

    private static List<TcLoginProfileSummary> BuildProfileSummaries(IEnumerable<TcLoginMatrixAttemptReport> attempts)
    {
        return attempts
            .GroupBy(attempt => attempt.ProfileName, StringComparer.OrdinalIgnoreCase)
            .Select(
                group => new TcLoginProfileSummary
                {
                    ProfileName = group.Key,
                    AttemptCount = group.Count(),
                    InterestingAttemptCount = group.Count(attempt => attempt.StateChanged || attempt.SignalScore > 0),
                    NonZeroLoginReturnCount = group.Count(attempt => (attempt.LoginResult?.ReturnValue ?? 0) != 0),
                    MaxSignalScore = group.Max(attempt => attempt.SignalScore),
                    Functions = group.Select(attempt => attempt.Function).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(value => value, StringComparer.OrdinalIgnoreCase).ToList(),
                    RepeatIndices = group.Select(attempt => attempt.RepeatIndex).Distinct().OrderBy(value => value).ToList(),
                    SampleSignalHints = group
                        .SelectMany(attempt => attempt.SignalHints)
                        .Where(hint => !string.IsNullOrWhiteSpace(hint))
                        .Distinct(StringComparer.Ordinal)
                        .Take(5)
                        .ToList(),
                })
            .OrderByDescending(summary => summary.InterestingAttemptCount)
            .ThenByDescending(summary => summary.MaxSignalScore)
            .ThenByDescending(summary => summary.NonZeroLoginReturnCount)
            .ThenBy(summary => summary.ProfileName, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static List<TcSetL2SignalSummary> BuildSetL2SignalSummaries(IEnumerable<TcSetL2MatrixAttemptReport> attempts)
    {
        return attempts
            .Select(
                attempt => new
                {
                    Attempt = attempt,
                    Signature = string.Join(" | ", attempt.SignalHints.Where(hint => !string.IsNullOrWhiteSpace(hint))),
                })
            .Where(item => !string.IsNullOrWhiteSpace(item.Signature))
            .GroupBy(item => item.Signature, StringComparer.Ordinal)
            .Select(
                group => new TcSetL2SignalSummary
                {
                    Signature = group.Key,
                    AttemptCount = group.Count(),
                    MaxSignalScore = group.Max(item => item.Attempt.SignalScore),
                    StateChanged = group.Any(item => item.Attempt.StateChanged),
                    ProfileNames = group.Select(item => item.Attempt.ProfileName).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(value => value, StringComparer.OrdinalIgnoreCase).ToList(),
                    RepeatIndices = group.Select(item => item.Attempt.RepeatIndex).Distinct().OrderBy(value => value).ToList(),
                })
            .OrderByDescending(summary => summary.AttemptCount)
            .ThenByDescending(summary => summary.MaxSignalScore)
            .ThenBy(summary => summary.Signature, StringComparer.Ordinal)
            .ToList();
    }

    private static List<TcSetL2ProfileSummary> BuildSetL2ProfileSummaries(IEnumerable<TcSetL2MatrixAttemptReport> attempts)
    {
        return attempts
            .GroupBy(attempt => attempt.ProfileName, StringComparer.OrdinalIgnoreCase)
            .Select(
                group => new TcSetL2ProfileSummary
                {
                    ProfileName = group.Key,
                    AttemptCount = group.Count(),
                    InterestingAttemptCount = group.Count(attempt => attempt.StateChanged || attempt.SignalScore > 0),
                    NonZeroSetL2ReturnCount = group.Count(attempt => (attempt.Probe?.SetL2Result?.ReturnValue ?? 0) != 0),
                    MaxSignalScore = group.Max(attempt => attempt.SignalScore),
                    RepeatIndices = group.Select(attempt => attempt.RepeatIndex).Distinct().OrderBy(value => value).ToList(),
                    SampleSignalHints = group
                        .SelectMany(attempt => attempt.SignalHints)
                        .Where(hint => !string.IsNullOrWhiteSpace(hint))
                        .Distinct(StringComparer.Ordinal)
                        .Take(5)
                        .ToList(),
                })
            .OrderByDescending(summary => summary.InterestingAttemptCount)
            .ThenByDescending(summary => summary.MaxSignalScore)
            .ThenByDescending(summary => summary.NonZeroSetL2ReturnCount)
            .ThenBy(summary => summary.ProfileName, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static List<TcSetL2AttemptSummary> BuildSetL2AttemptSummaries(IEnumerable<TcSetL2MatrixAttemptReport> attempts)
    {
        return attempts
            .OrderByDescending(attempt => attempt.SignalScore)
            .ThenByDescending(attempt => attempt.StateChanged)
            .ThenBy(attempt => attempt.ProfileName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(attempt => attempt.RepeatIndex)
            .Take(32)
            .Select(
                attempt => new TcSetL2AttemptSummary
                {
                    RepeatIndex = attempt.RepeatIndex,
                    ProfileName = attempt.ProfileName,
                    LoginProfileName = attempt.LoginProfileName,
                    StateChanged = attempt.StateChanged,
                    SignalScore = attempt.SignalScore,
                    SignalHints = attempt.SignalHints.ToList(),
                    LoginReturnValue = attempt.Probe?.LoginResult?.ReturnValue ?? 0,
                    SetL2ReturnValue = attempt.Probe?.SetL2Result?.ReturnValue ?? 0,
                    ErrorType = attempt.ErrorType,
                    Error = attempt.Error,
                })
            .ToList();
    }

    private static bool HasAnyStateDelta(TcLoginMatrixAttemptReport attempt)
    {
        return HasStateDelta(attempt.PreGetLoginRet?.Arg1, attempt.PostGetLoginRet?.Arg1)
            || HasStateDelta(attempt.PreGetRightInfo?.Arg1, attempt.PostGetRightInfo?.Arg1)
            || HasStateDelta(attempt.PreGetRightInfo?.Arg2, attempt.PostGetRightInfo?.Arg2)
            || HasStateDelta(attempt.PreGetRightInfo?.Arg3, attempt.PostGetRightInfo?.Arg3)
            || HasStateDelta(attempt.PreGetL2Info?.Arg1, attempt.PostGetL2Info?.Arg1)
            || HasStateDelta(attempt.PreGetL2Info?.Arg2, attempt.PostGetL2Info?.Arg2);
    }

    private static bool HasAnyStateDelta(TcSetL2ProbeReport report)
    {
        var loginInvoked = report.LoginResult?.Invoked == true;
        return (loginInvoked && HasStateDelta(report.PreLoginGetLoginRet?.Arg1, report.PostLoginGetLoginRet?.Arg1))
            || (loginInvoked && HasStateDelta(report.PreLoginGetRightInfo?.Arg1, report.PostLoginGetRightInfo?.Arg1))
            || (loginInvoked && HasStateDelta(report.PreLoginGetRightInfo?.Arg2, report.PostLoginGetRightInfo?.Arg2))
            || (loginInvoked && HasStateDelta(report.PreLoginGetRightInfo?.Arg3, report.PostLoginGetRightInfo?.Arg3))
            || (loginInvoked && HasStateDelta(report.PreLoginGetL2Info?.Arg1, report.PostLoginGetL2Info?.Arg1))
            || (loginInvoked && HasStateDelta(report.PreLoginGetL2Info?.Arg2, report.PostLoginGetL2Info?.Arg2))
            || HasStateDelta(report.PreSetL2GetLoginRet?.Arg1, report.PostSetL2GetLoginRet?.Arg1)
            || HasStateDelta(report.PreSetL2GetRightInfo?.Arg1, report.PostSetL2GetRightInfo?.Arg1)
            || HasStateDelta(report.PreSetL2GetRightInfo?.Arg2, report.PostSetL2GetRightInfo?.Arg2)
            || HasStateDelta(report.PreSetL2GetRightInfo?.Arg3, report.PostSetL2GetRightInfo?.Arg3)
            || HasStateDelta(report.PreSetL2GetL2Info?.Arg1, report.PostSetL2GetL2Info?.Arg1)
            || HasStateDelta(report.PreSetL2GetL2Info?.Arg2, report.PostSetL2GetL2Info?.Arg2);
    }

    private static bool HasStateDelta(BufferSnapshot? before, BufferSnapshot? after)
    {
        if (before is null && after is null)
        {
            return false;
        }

        if (before is null || after is null)
        {
            return true;
        }

        return before.NonZeroBytes != after.NonZeroBytes
            || !string.Equals(before.HexPrefix, after.HexPrefix, StringComparison.Ordinal)
            || !string.Equals(before.AnsiPreview, after.AnsiPreview, StringComparison.Ordinal)
            || !string.Equals(before.Gb18030Preview, after.Gb18030Preview, StringComparison.Ordinal);
    }


    private static TcUninitCallReport InvokeTcUninit(TcUninitFn uninit)
    {
        var started = DateTime.UtcNow;
        var report = new TcUninitCallReport { Invoked = true };
        try
        {
            uninit();
            report.Win32LastError = Marshal.GetLastWin32Error();
        }
        catch (Exception error)
        {
            report.ErrorType = error.GetType().Name;
            report.Error = error.Message;
        }
        finally
        {
            report.ElapsedMs = (int)(DateTime.UtcNow - started).TotalMilliseconds;
        }

        return report;
    }

    private static string ReadPeArchitecture(string path)
    {
        using var stream = File.OpenRead(path);
        using var peReader = new PEReader(stream);
        return peReader.PEHeaders.CoffHeader.Machine switch
        {
            Machine.I386 => "x86",
            Machine.Amd64 => "x64",
            _ => peReader.PEHeaders.CoffHeader.Machine.ToString(),
        };
    }

    private static string ToHex(IntPtr value)
    {
        return $"0x{value.ToInt64():X}";
    }

    private static void ApplyProcessErrorMode()
    {
        try
        {
            NativeMethods.SetErrorMode(SemFailCriticalErrors | SemNoGpFaultErrorBox | SemNoOpenFileErrorBox);
        }
        catch
        {
            // Best effort only; lack of support should not block probes.
        }
    }
}

internal static class JsonOptions
{
    internal static readonly JsonSerializerOptions Default = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    internal static readonly JsonSerializerOptions Compact = new()
    {
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };
}

internal sealed class CliOptions
{
    public string Command { get; private set; } = "inspect";
    public string TdxRoot { get; private set; } = @"D:\APP_SOFT\TDX";
    public string? TcPath { get; private set; }
    public string? DeepPath { get; private set; }
    public string? InitArg1 { get; private set; }
    public string? InitArg2 { get; private set; }
    public string? InitArg3 { get; private set; }
    public string? InitArg5 { get; private set; }
    public int InitArg6 { get; private set; }
    public int BufferSize { get; private set; } = 4096;
    public bool PreInitGetL2Info { get; private set; }
    public bool SyncRuntimeLayout { get; private set; }
    public bool ShowHelp { get; private set; }
    public string? SetL2Arg1 { get; private set; }
    public string? SetL2Arg2 { get; private set; }
    public string? SetL2Arg3 { get; private set; }
    public bool EventStream { get; private set; }
    public bool UnsafeDeepStart { get; private set; }
    public bool UnsafeDeepFuncProbe { get; private set; }
    private readonly List<int> unsafeDeepFuncCodes = new() { 2, 3, 11, 12, 13, 14 };
    public int HeartbeatIntervalMs { get; private set; } = 1000;
    public int SampleCount { get; private set; } = 1;
    public int DurationMs { get; private set; }
    public int RepeatCount { get; private set; } = 1;
    public bool ProbeLoginState { get; private set; }
    public bool StableLoginRetSurface { get; private set; }
    public bool DisableProcessErrorMode { get; private set; }
    public bool DisableChildDialogWatchdog { get; private set; }
    public bool IsolateChildAppBase { get; private set; }
    public bool SkipLoginRetProbe { get; private set; }
    public bool SkipRightInfoProbe { get; private set; }
    public bool SkipL2InfoProbe { get; private set; }
    public bool SkipTcUninit { get; private set; }
    public string? LoginFunction { get; private set; }
    public string? LoginProfile { get; private set; }
    public string? ProfileFilter { get; private set; }
    public string? ResolvedLoginProfile { get; private set; }
    public string? LoginArg1 { get; private set; }
    public string? LoginArg2 { get; private set; }
    public string? LoginArg3 { get; private set; }
    public string? LoginArg4 { get; private set; }

    public IReadOnlyList<int> UnsafeDeepFuncCodes => unsafeDeepFuncCodes;

    public bool L2Monitor { get; private set; }
    public bool L2ForceScan { get; private set; }
    public int L2IntervalMs { get; private set; } = 500;
    public string? L2Output { get; private set; }

    public bool HasSetL2Args =>
        !string.IsNullOrEmpty(SetL2Arg1)
        || !string.IsNullOrEmpty(SetL2Arg2)
        || !string.IsNullOrEmpty(SetL2Arg3);

    public bool HasLoginInvocationRequest =>
        !string.IsNullOrWhiteSpace(LoginFunction);

    public static string HelpText =>
        """
        TdxL2Helper inspect [--tdx-root <path>] [--tc-path <path>] [--deep-path <path>]
        TdxL2Helper sync-runtime-layout [--tdx-root <path>]
        TdxL2Helper probe-tc-baseline [--tdx-root <path>] [--tc-path <path>] [--buffer-size <n>]
                                        [--init-arg1 <text>] [--init-arg2 <text>] [--init-arg3 <text>]
                                        [--init-arg5 <text>] [--init-arg6 <0|1>]
                                        [--pre-init-getl2info] [--sync-runtime-layout]
        TdxL2Helper probe-tc-login-matrix [--tdx-root <path>] [--tc-path <path>] [--buffer-size <n>]
                                          [--init-arg1 <text>] [--init-arg2 <text>] [--init-arg3 <text>]
                                          [--init-arg5 <text>] [--init-arg6 <0|1>]
                                          [--login-function <login|login2>]
                                          [--stable-loginret-surface]
                                          [--repeat-count <n>] [--profile-filter <term[,term...]>]
                                          [--disable-process-error-mode]
                                          [--disable-child-dialog-watchdog]
                                          [--isolate-child-app-base]
                                          [--skip-loginret-probe] [--skip-rightinfo-probe]
                                          [--skip-l2info-probe] [--skip-tc-uninit]
                                          [--sync-runtime-layout]
        TdxL2Helper probe-tc-setl2 [--tdx-root <path>] [--tc-path <path>] [--buffer-size <n>]
                                   [--init-arg1 <text>] [--init-arg2 <text>] [--init-arg3 <text>]
                                   [--init-arg5 <text>] [--init-arg6 <0|1>]
                                   [--probe-login-state]
                                   [--login-function <login|login2>]
                                   [--login-profile <name|auto>]
                                   [--login-arg1 <text>] [--login-arg2 <text>]
                                   [--login-arg3 <text>] [--login-arg4 <text>]
                                   [--skip-loginret-probe] [--skip-rightinfo-probe]
                                   [--skip-l2info-probe]
                                   [--setl2-arg1 <text>] [--setl2-arg2 <text>] [--setl2-arg3 <text>]
                                   [--pre-init-getl2info] [--skip-tc-uninit] [--sync-runtime-layout]
        TdxL2Helper probe-tc-setl2-matrix [--tdx-root <path>] [--tc-path <path>] [--buffer-size <n>]
                                          [--init-arg1 <text>] [--init-arg2 <text>] [--init-arg3 <text>]
                                          [--init-arg5 <text>] [--init-arg6 <0|1>]
                                          [--probe-login-state]
                                          [--login-function <login|login2>]
                                          [--login-profile <name|auto>]
                                          [--login-arg1 <text>] [--login-arg2 <text>]
                                          [--login-arg3 <text>] [--login-arg4 <text>]
                                          [--skip-loginret-probe] [--skip-rightinfo-probe]
                                          [--skip-l2info-probe]
                                          [--setl2-arg1 <text>] [--setl2-arg2 <text>] [--setl2-arg3 <text>]
                                          [--pre-init-getl2info] [--skip-tc-uninit]
                                          [--repeat-count <n>] [--profile-filter <term[,term...]>]
                                          [--sync-runtime-layout]
        TdxL2Helper host-runtime [--tdx-root <path>] [--tc-path <path>] [--deep-path <path>]
                                 [--buffer-size <n>] [--init-arg1 <text>] [--init-arg2 <text>]
                                 [--init-arg3 <text>] [--init-arg5 <text>] [--init-arg6 <0|1>]
                                 [--probe-login-state]
                                 [--login-function <login|login2>]
                                 [--login-profile <name|auto>]
                                 [--stable-loginret-surface]
                                 [--unsafe-deep-start] [--unsafe-deep-func-probe]
                                 [--unsafe-deep-func-codes <csv>]
                                 [--disable-process-error-mode]
                                 [--skip-loginret-probe] [--skip-rightinfo-probe]
                                 [--skip-l2info-probe] [--skip-tc-uninit]
                                 [--login-arg1 <text>] [--login-arg2 <text>]
                                 [--login-arg3 <text>] [--login-arg4 <text>]
                                 [--setl2-arg1 <text>] [--setl2-arg2 <text>] [--setl2-arg3 <text>]
                                 [--sample-count <n>] [--heartbeat-interval-ms <n>]
                                 [--duration-ms <n>] [--event-stream]
        TdxL2Helper read-l2-depth [--tdx-root <path>] [--scan] [--monitor]
                                   [--interval-ms <n>] [--output <jsonl-path>]

        Current command:
          inspect   Load tc.dll and TDXDeep.dll from an x86 process and resolve target exports.
          sync-runtime-layout
                    Mirror eTrade.xmb / TcOem.xmb / TCPlugins into the helper executable
                    directory so tc.dll sees a host-style runtime layout.
          probe-tc-baseline
                    Use the current signature guesses to call:
                    optional pre-init TC_GetL2Info -> TC_Init_Environ -> TC_GetL2Info -> TC_Uninit
          probe-tc-login-matrix
                    Load cached local identity/session materials, build a small fixed
                    argument matrix for TC_Login / TC_Login2, and compare pre/post
                    LoginRet / RightInfo / L2Info buffer state deltas.
                    Use --stable-loginret-surface to apply the current best low-noise template:
                    disable process error mode + isolate child app base + skip L2Info probe.
                    Use --login-function to isolate only login or only login2.
                    Use --isolate-child-app-base to launch each isolated child from its own copied helper directory.
                    Use skip-* flags to shrink the native call surface around login.
                    Use --repeat-count to rerun the same profile set and compare stability.
                    Use --profile-filter to focus on names like connectqsid,jymainqsid,userpuid.
                    Current preferred auto order:
                    tdxid-token-connectqsid-reguid -> tdxid-token-connectqsid-oid -> tdxid-token-jymainqsid-oid
                    -> tdxid-token-userpuid-oid -> tdxid-token-oid-reguid
          probe-tc-setl2
                    Use the current signature guesses to call:
                    optional pre-init TC_GetL2Info -> TC_Init_Environ -> pre-login LoginRet/RightInfo/L2Info
                    -> optional TC_Login/TC_Login2 -> post-login LoginRet/RightInfo/L2Info
                    -> pre-setl2 LoginRet/RightInfo/L2Info -> TC_SetL2UserInfo
                    -> post-setl2 LoginRet/RightInfo/L2Info -> TC_Uninit
          probe-tc-setl2-matrix
                    Load cached local identity materials, build a small fixed
                    TC_SetL2UserInfo candidate matrix, and compare pre/post
                    LoginRet / RightInfo / L2Info buffer state deltas.
                    Use --login-function / --login-profile when the setl2 call
                    must be replayed on top of a cached login attempt.
                    Use --profile-filter to focus on names like citicscfv,tdxid,connectqsid.
          host-runtime
                    Run the standalone x86 host baseline:
                    sync runtime layout -> load tc.dll / TDXDeep.dll -> TC_Init_Environ
                    -> optional TC_GetL2Info snapshots -> steady-state heartbeat output
                    Use --unsafe-deep-start to attempt the current TdxDeep_StartInit probe.
                    Use --unsafe-deep-func-probe only in an isolated process; empty-context TdxDeep_Func calls can block.
                    Use --unsafe-deep-func-codes to isolate function codes, for example 2 or 11,12,13.
                    Use --event-stream for NDJSON stdout events that an outer bridge can consume.
          read-l2-depth
                    Experimental read-only process-memory scanner for candidate depth-book
                    structures in a running tdxw.exe. This is an isolated probe, not a
                    production L2 feed and not proof that 7719 / official L2 is implemented.
        """;

    public static CliOptions Parse(IReadOnlyList<string> args)
    {
        var options = new CliOptions();
        for (var index = 0; index < args.Count; index++)
        {
            var arg = args[index];
            switch (arg)
            {
                case "-h":
                case "--help":
                case "help":
                    options.ShowHelp = true;
                    break;
                case "inspect":
                case "sync-runtime-layout":
                case "probe-tc-baseline":
                case "probe-tc-login-matrix":
                case "probe-tc-login-attempt":
                case "probe-tc-setl2":
                case "probe-tc-setl2-matrix":
                case "host-runtime":
                case "read-l2-depth":
                    options.Command = arg;
                    break;
                case "--tdx-root":
                    options.TdxRoot = RequireValue(args, ref index, arg);
                    break;
                case "--tc-path":
                    options.TcPath = RequireValue(args, ref index, arg);
                    break;
                case "--deep-path":
                    options.DeepPath = RequireValue(args, ref index, arg);
                    break;
                case "--buffer-size":
                    options.BufferSize = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--init-arg1":
                    options.InitArg1 = RequireValue(args, ref index, arg);
                    break;
                case "--init-arg2":
                    options.InitArg2 = RequireValue(args, ref index, arg);
                    break;
                case "--init-arg3":
                    options.InitArg3 = RequireValue(args, ref index, arg);
                    break;
                case "--init-arg5":
                    options.InitArg5 = RequireValue(args, ref index, arg);
                    break;
                case "--init-arg6":
                    options.InitArg6 = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--skip-pre-init-getl2info":
                    options.PreInitGetL2Info = false;
                    break;
                case "--pre-init-getl2info":
                    options.PreInitGetL2Info = true;
                    break;
                case "--sync-runtime-layout":
                    options.SyncRuntimeLayout = true;
                    break;
                case "--setl2-arg1":
                    options.SetL2Arg1 = RequireValue(args, ref index, arg);
                    break;
                case "--setl2-arg2":
                    options.SetL2Arg2 = RequireValue(args, ref index, arg);
                    break;
                case "--setl2-arg3":
                    options.SetL2Arg3 = RequireValue(args, ref index, arg);
                    break;
                case "--event-stream":
                    options.EventStream = true;
                    break;
                case "--unsafe-deep-start":
                    options.UnsafeDeepStart = true;
                    break;
                case "--unsafe-deep-func-probe":
                    options.UnsafeDeepFuncProbe = true;
                    break;
                case "--unsafe-deep-func-codes":
                    options.unsafeDeepFuncCodes.Clear();
                    foreach (var code in RequireValue(args, ref index, arg).Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                    {
                        options.unsafeDeepFuncCodes.Add(ParseIntOrHex(code));
                    }

                    break;
                case "--probe-login-state":
                    options.ProbeLoginState = true;
                    break;
                case "--stable-loginret-surface":
                    options.StableLoginRetSurface = true;
                    break;
                case "--monitor":
                    options.L2Monitor = true;
                    break;
                case "--scan":
                    options.L2ForceScan = true;
                    break;
                case "--interval-ms":
                    options.L2IntervalMs = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--output":
                    options.L2Output = RequireValue(args, ref index, arg);
                    break;
                case "--disable-process-error-mode":
                    options.DisableProcessErrorMode = true;
                    break;
                case "--disable-child-dialog-watchdog":
                    options.DisableChildDialogWatchdog = true;
                    break;
                case "--isolate-child-app-base":
                    options.IsolateChildAppBase = true;
                    break;
                case "--skip-loginret-probe":
                    options.SkipLoginRetProbe = true;
                    break;
                case "--skip-rightinfo-probe":
                    options.SkipRightInfoProbe = true;
                    break;
                case "--skip-l2info-probe":
                    options.SkipL2InfoProbe = true;
                    break;
                case "--skip-tc-uninit":
                    options.SkipTcUninit = true;
                    break;
                case "--login-function":
                    options.LoginFunction = RequireValue(args, ref index, arg).Trim().ToLowerInvariant();
                    break;
                case "--login-profile":
                    options.LoginProfile = RequireValue(args, ref index, arg).Trim();
                    break;
                case "--profile-filter":
                    options.ProfileFilter = RequireValue(args, ref index, arg).Trim();
                    break;
                case "--login-arg1":
                    options.LoginArg1 = RequireValue(args, ref index, arg);
                    break;
                case "--login-arg2":
                    options.LoginArg2 = RequireValue(args, ref index, arg);
                    break;
                case "--login-arg3":
                    options.LoginArg3 = RequireValue(args, ref index, arg);
                    break;
                case "--login-arg4":
                    options.LoginArg4 = RequireValue(args, ref index, arg);
                    break;
                case "--heartbeat-interval-ms":
                    options.HeartbeatIntervalMs = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--sample-count":
                    options.SampleCount = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--duration-ms":
                    options.DurationMs = int.Parse(RequireValue(args, ref index, arg));
                    break;
                case "--repeat-count":
                    options.RepeatCount = int.Parse(RequireValue(args, ref index, arg));
                    break;
                default:
                    throw new ArgumentException($"unknown argument: {arg}");
            }
        }

        if (options.RepeatCount <= 0)
        {
            throw new ArgumentException("--repeat-count must be greater than 0");
        }

        if (!string.IsNullOrWhiteSpace(options.LoginFunction)
            && !string.Equals(options.LoginFunction, "login", StringComparison.OrdinalIgnoreCase)
            && !string.Equals(options.LoginFunction, "login2", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("--login-function must be either 'login' or 'login2'");
        }

        if (options.StableLoginRetSurface)
        {
            options.DisableProcessErrorMode = true;
            options.IsolateChildAppBase = true;
            options.SkipL2InfoProbe = true;
        }

        return options;
    }

    private static int ParseIntOrHex(string value)
    {
        return value.StartsWith("0x", StringComparison.OrdinalIgnoreCase)
            ? Convert.ToInt32(value[2..], 16)
            : int.Parse(value);
    }

    internal void ApplyResolvedLoginProfile(CachedLoginProfile profile)
    {
        ResolvedLoginProfile = profile.Name;

        foreach (var argument in profile.Arguments)
        {
            if (string.IsNullOrWhiteSpace(argument.Value))
            {
                continue;
            }

            switch (argument.Slot)
            {
                case 1 when string.IsNullOrWhiteSpace(LoginArg1):
                    LoginArg1 = argument.Value;
                    break;
                case 2 when string.IsNullOrWhiteSpace(LoginArg2):
                    LoginArg2 = argument.Value;
                    break;
                case 3 when string.IsNullOrWhiteSpace(LoginArg3):
                    LoginArg3 = argument.Value;
                    break;
                case 4 when string.IsNullOrWhiteSpace(LoginArg4):
                    LoginArg4 = argument.Value;
                    break;
            }
        }

    }

    private static string RequireValue(IReadOnlyList<string> args, ref int index, string optionName)
    {
        if (index + 1 >= args.Count)
        {
            throw new ArgumentException($"missing value for {optionName}");
        }

        index += 1;
        return args[index];
    }
}

internal sealed class InspectReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; init; }

    [JsonPropertyName("ok")]
    public bool Ok { get; init; }

    [JsonPropertyName("command")]
    public string Command { get; init; } = string.Empty;

    [JsonPropertyName("processArchitecture")]
    public string ProcessArchitecture { get; init; } = string.Empty;

    [JsonPropertyName("frameworkDescription")]
    public string FrameworkDescription { get; init; } = string.Empty;

    [JsonPropertyName("pointerSizeBits")]
    public int PointerSizeBits { get; init; }

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("modules")]
    public List<ModuleReport> Modules { get; init; } = new();

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class TcBaselineProbeReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; init; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("command")]
    public string Command { get; init; } = string.Empty;

    [JsonPropertyName("processArchitecture")]
    public string ProcessArchitecture { get; init; } = string.Empty;

    [JsonPropertyName("frameworkDescription")]
    public string FrameworkDescription { get; init; } = string.Empty;

    [JsonPropertyName("pointerSizeBits")]
    public int PointerSizeBits { get; init; }

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("tcPath")]
    public string TcPath { get; init; } = string.Empty;

    [JsonPropertyName("moduleHandle")]
    public string ModuleHandle { get; set; } = string.Empty;

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("runtimeLayout")]
    public RuntimeLayoutReport RuntimeLayout { get; set; } = new();

    [JsonPropertyName("initArgs")]
    public TcInitArgsSnapshot InitArgs { get; init; } = new();

    [JsonPropertyName("resolvedExports")]
    public Dictionary<string, bool> ResolvedExports { get; set; } = new();

    [JsonPropertyName("preInitGetL2Info")]
    public TcGetL2InfoCallReport? PreInitGetL2Info { get; set; }

    [JsonPropertyName("initResult")]
    public TcInitCallReport? InitResult { get; set; }

    [JsonPropertyName("postInitGetL2Info")]
    public TcGetL2InfoCallReport? PostInitGetL2Info { get; set; }

    [JsonPropertyName("uninitResult")]
    public TcUninitCallReport? UninitResult { get; set; }

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class TcSetL2ProbeReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; init; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("command")]
    public string Command { get; init; } = string.Empty;

    [JsonPropertyName("processArchitecture")]
    public string ProcessArchitecture { get; init; } = string.Empty;

    [JsonPropertyName("frameworkDescription")]
    public string FrameworkDescription { get; init; } = string.Empty;

    [JsonPropertyName("pointerSizeBits")]
    public int PointerSizeBits { get; init; }

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("tcPath")]
    public string TcPath { get; init; } = string.Empty;

    [JsonPropertyName("moduleHandle")]
    public string ModuleHandle { get; set; } = string.Empty;

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("repeatCount")]
    public int RepeatCount { get; init; } = 1;

    [JsonPropertyName("runtimeLayout")]
    public RuntimeLayoutReport RuntimeLayout { get; set; } = new();

    [JsonPropertyName("initArgs")]
    public TcInitArgsSnapshot InitArgs { get; init; } = new();

    [JsonPropertyName("setL2Args")]
    public TcSetL2ArgsSnapshot SetL2Args { get; init; } = new();

    [JsonPropertyName("loginRequest")]
    public TcLoginRequestSnapshot? LoginRequest { get; set; }

    [JsonPropertyName("resolvedLoginProfile")]
    public string ResolvedLoginProfile { get; set; } = string.Empty;

    [JsonPropertyName("materials")]
    public CachedLoginMaterialsReport Materials { get; set; } = new();

    [JsonPropertyName("resolvedExports")]
    public Dictionary<string, bool> ResolvedExports { get; set; } = new();

    [JsonPropertyName("preInitGetL2Info")]
    public TcGetL2InfoCallReport? PreInitGetL2Info { get; set; }

    [JsonPropertyName("initResult")]
    public TcInitCallReport? InitResult { get; set; }

    [JsonPropertyName("preLoginGetLoginRet")]
    public TcGetLoginRetCallReport? PreLoginGetLoginRet { get; set; }

    [JsonPropertyName("preLoginGetRightInfo")]
    public TcGetRightInfoCallReport? PreLoginGetRightInfo { get; set; }

    [JsonPropertyName("preLoginGetL2Info")]
    public TcGetL2InfoCallReport? PreLoginGetL2Info { get; set; }

    [JsonPropertyName("probeGetLoginRet")]
    public TcGetLoginRetCallReport? ProbeGetLoginRet { get; set; }

    [JsonPropertyName("probeGetRightInfo")]
    public TcGetRightInfoCallReport? ProbeGetRightInfo { get; set; }

    [JsonPropertyName("loginResult")]
    public TcLoginCallReport? LoginResult { get; set; }

    [JsonPropertyName("postLoginGetLoginRet")]
    public TcGetLoginRetCallReport? PostLoginGetLoginRet { get; set; }

    [JsonPropertyName("postLoginGetRightInfo")]
    public TcGetRightInfoCallReport? PostLoginGetRightInfo { get; set; }

    [JsonPropertyName("postLoginGetL2Info")]
    public TcGetL2InfoCallReport? PostLoginGetL2Info { get; set; }

    [JsonPropertyName("preSetL2GetLoginRet")]
    public TcGetLoginRetCallReport? PreSetL2GetLoginRet { get; set; }

    [JsonPropertyName("preSetL2GetRightInfo")]
    public TcGetRightInfoCallReport? PreSetL2GetRightInfo { get; set; }

    [JsonPropertyName("preSetL2GetL2Info")]
    public TcGetL2InfoCallReport? PreSetL2GetL2Info { get; set; }

    [JsonPropertyName("setL2Result")]
    public TcSetL2UserInfoCallReport? SetL2Result { get; set; }

    [JsonPropertyName("postSetL2GetLoginRet")]
    public TcGetLoginRetCallReport? PostSetL2GetLoginRet { get; set; }

    [JsonPropertyName("postSetL2GetRightInfo")]
    public TcGetRightInfoCallReport? PostSetL2GetRightInfo { get; set; }

    [JsonPropertyName("postSetL2GetL2Info")]
    public TcGetL2InfoCallReport? PostSetL2GetL2Info { get; set; }

    [JsonPropertyName("uninitResult")]
    public TcUninitCallReport? UninitResult { get; set; }

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("signalScore")]
    public int SignalScore { get; set; }

    [JsonPropertyName("signalHints")]
    public List<string> SignalHints { get; set; } = new();

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class TcLoginMatrixProbeReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; init; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("command")]
    public string Command { get; init; } = string.Empty;

    [JsonPropertyName("processArchitecture")]
    public string ProcessArchitecture { get; init; } = string.Empty;

    [JsonPropertyName("frameworkDescription")]
    public string FrameworkDescription { get; init; } = string.Empty;

    [JsonPropertyName("pointerSizeBits")]
    public int PointerSizeBits { get; init; }

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("tcPath")]
    public string TcPath { get; init; } = string.Empty;

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("repeatCount")]
    public int RepeatCount { get; init; } = 1;

    [JsonPropertyName("runtimeLayout")]
    public RuntimeLayoutReport RuntimeLayout { get; set; } = new();

    [JsonPropertyName("materials")]
    public CachedLoginMaterialsReport Materials { get; set; } = new();

    [JsonPropertyName("attempts")]
    public List<TcLoginMatrixAttemptReport> Attempts { get; init; } = new();

    [JsonPropertyName("selectedProfiles")]
    public List<string> SelectedProfiles { get; set; } = new();

    [JsonPropertyName("profileSummaries")]
    public List<TcLoginProfileSummary> ProfileSummaries { get; set; } = new();

    [JsonPropertyName("signalSummaries")]
    public List<TcLoginSignalSummary> SignalSummaries { get; set; } = new();

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class CachedLoginMaterialsReport
{
    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("liveRuntimeProcessId")]
    public int? LiveRuntimeProcessId { get; set; }

    [JsonPropertyName("liveRuntimeProcessPath")]
    public string? LiveRuntimeProcessPath { get; set; }

    [JsonPropertyName("sourceFiles")]
    public List<LoginMaterialFileSnapshot> SourceFiles { get; init; } = new();

    [JsonPropertyName("entries")]
    public List<CachedLoginMaterialSnapshot> Entries { get; init; } = new();

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();

    [JsonIgnore]
    public Dictionary<string, string> ValueMap { get; } = new(StringComparer.OrdinalIgnoreCase);
}

internal sealed class LiveProcessCandidate
{
    public int ProcessId { get; init; }

    public string ProcessPath { get; init; } = string.Empty;

    public bool MatchesExpectedPath { get; init; }

    public DateTime StartedAtUtc { get; init; }
}

internal sealed class LoginMaterialFileSnapshot
{
    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    [JsonPropertyName("exists")]
    public bool Exists { get; init; }
}

internal sealed class CachedLoginMaterialSnapshot
{
    [JsonPropertyName("key")]
    public string Key { get; init; } = string.Empty;

    [JsonPropertyName("source")]
    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("valueLength")]
    public int ValueLength { get; init; }

    [JsonPropertyName("maskedValue")]
    public string MaskedValue { get; init; } = string.Empty;
}

internal sealed class TcLoginMatrixAttemptReport
{
    [JsonPropertyName("repeatIndex")]
    public int RepeatIndex { get; set; }

    [JsonPropertyName("function")]
    public string Function { get; set; } = string.Empty;

    [JsonPropertyName("profileName")]
    public string ProfileName { get; set; } = string.Empty;

    [JsonPropertyName("arguments")]
    public List<MaskedArgumentSnapshot> Arguments { get; set; } = new();

    [JsonPropertyName("resolvedExports")]
    public Dictionary<string, bool> ResolvedExports { get; set; } = new();

    [JsonPropertyName("initResult")]
    public TcInitCallReport? InitResult { get; set; }

    [JsonPropertyName("loginResult")]
    public TcLoginCallReport? LoginResult { get; set; }

    [JsonPropertyName("preGetLoginRet")]
    public TcGetLoginRetCallReport? PreGetLoginRet { get; set; }

    [JsonPropertyName("postGetLoginRet")]
    public TcGetLoginRetCallReport? PostGetLoginRet { get; set; }

    [JsonPropertyName("preGetRightInfo")]
    public TcGetRightInfoCallReport? PreGetRightInfo { get; set; }

    [JsonPropertyName("postGetRightInfo")]
    public TcGetRightInfoCallReport? PostGetRightInfo { get; set; }

    [JsonPropertyName("preGetL2Info")]
    public TcGetL2InfoCallReport? PreGetL2Info { get; set; }

    [JsonPropertyName("postGetL2Info")]
    public TcGetL2InfoCallReport? PostGetL2Info { get; set; }

    [JsonPropertyName("signalScore")]
    public int SignalScore { get; set; }

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("signalHints")]
    public List<string> SignalHints { get; set; } = new();

    [JsonPropertyName("uninitResult")]
    public TcUninitCallReport? UninitResult { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcLoginSignalSummary
{
    [JsonPropertyName("signature")]
    public string Signature { get; set; } = string.Empty;

    [JsonPropertyName("attemptCount")]
    public int AttemptCount { get; set; }

    [JsonPropertyName("maxSignalScore")]
    public int MaxSignalScore { get; set; }

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("functions")]
    public List<string> Functions { get; set; } = new();

    [JsonPropertyName("profileNames")]
    public List<string> ProfileNames { get; set; } = new();

    [JsonPropertyName("repeatIndices")]
    public List<int> RepeatIndices { get; set; } = new();
}

internal sealed class TcLoginProfileSummary
{
    [JsonPropertyName("profileName")]
    public string ProfileName { get; set; } = string.Empty;

    [JsonPropertyName("attemptCount")]
    public int AttemptCount { get; set; }

    [JsonPropertyName("interestingAttemptCount")]
    public int InterestingAttemptCount { get; set; }

    [JsonPropertyName("nonZeroLoginReturnCount")]
    public int NonZeroLoginReturnCount { get; set; }

    [JsonPropertyName("maxSignalScore")]
    public int MaxSignalScore { get; set; }

    [JsonPropertyName("functions")]
    public List<string> Functions { get; set; } = new();

    [JsonPropertyName("repeatIndices")]
    public List<int> RepeatIndices { get; set; } = new();

    [JsonPropertyName("sampleSignalHints")]
    public List<string> SampleSignalHints { get; set; } = new();
}

internal sealed class TcSetL2MatrixProbeReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; init; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("command")]
    public string Command { get; init; } = string.Empty;

    [JsonPropertyName("processArchitecture")]
    public string ProcessArchitecture { get; init; } = string.Empty;

    [JsonPropertyName("frameworkDescription")]
    public string FrameworkDescription { get; init; } = string.Empty;

    [JsonPropertyName("pointerSizeBits")]
    public int PointerSizeBits { get; init; }

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; init; } = string.Empty;

    [JsonPropertyName("tcPath")]
    public string TcPath { get; init; } = string.Empty;

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("repeatCount")]
    public int RepeatCount { get; init; } = 1;

    [JsonPropertyName("runtimeLayout")]
    public RuntimeLayoutReport RuntimeLayout { get; set; } = new();

    [JsonPropertyName("materials")]
    public CachedLoginMaterialsReport Materials { get; set; } = new();

    [JsonPropertyName("attempts")]
    public List<TcSetL2MatrixAttemptReport> Attempts { get; init; } = new();

    [JsonPropertyName("attemptSummaries")]
    public List<TcSetL2AttemptSummary> AttemptSummaries { get; set; } = new();

    [JsonPropertyName("selectedProfiles")]
    public List<string> SelectedProfiles { get; set; } = new();

    [JsonPropertyName("profileSummaries")]
    public List<TcSetL2ProfileSummary> ProfileSummaries { get; set; } = new();

    [JsonPropertyName("signalSummaries")]
    public List<TcSetL2SignalSummary> SignalSummaries { get; set; } = new();

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class TcSetL2MatrixAttemptReport
{
    [JsonPropertyName("repeatIndex")]
    public int RepeatIndex { get; set; }

    [JsonPropertyName("profileName")]
    public string ProfileName { get; set; } = string.Empty;

    [JsonPropertyName("arguments")]
    public List<MaskedArgumentSnapshot> Arguments { get; set; } = new();

    [JsonPropertyName("loginFunction")]
    public string LoginFunction { get; set; } = string.Empty;

    [JsonPropertyName("loginProfileName")]
    public string LoginProfileName { get; set; } = string.Empty;

    [JsonPropertyName("probe")]
    public TcSetL2ProbeReport? Probe { get; set; }

    [JsonPropertyName("signalScore")]
    public int SignalScore { get; set; }

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("signalHints")]
    public List<string> SignalHints { get; set; } = new();

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcSetL2AttemptSummary
{
    [JsonPropertyName("repeatIndex")]
    public int RepeatIndex { get; set; }

    [JsonPropertyName("profileName")]
    public string ProfileName { get; set; } = string.Empty;

    [JsonPropertyName("loginProfileName")]
    public string LoginProfileName { get; set; } = string.Empty;

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("signalScore")]
    public int SignalScore { get; set; }

    [JsonPropertyName("signalHints")]
    public List<string> SignalHints { get; set; } = new();

    [JsonPropertyName("loginReturnValue")]
    public int LoginReturnValue { get; set; }

    [JsonPropertyName("setL2ReturnValue")]
    public int SetL2ReturnValue { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcSetL2SignalSummary
{
    [JsonPropertyName("signature")]
    public string Signature { get; set; } = string.Empty;

    [JsonPropertyName("attemptCount")]
    public int AttemptCount { get; set; }

    [JsonPropertyName("maxSignalScore")]
    public int MaxSignalScore { get; set; }

    [JsonPropertyName("stateChanged")]
    public bool StateChanged { get; set; }

    [JsonPropertyName("profileNames")]
    public List<string> ProfileNames { get; set; } = new();

    [JsonPropertyName("repeatIndices")]
    public List<int> RepeatIndices { get; set; } = new();
}

internal sealed class TcSetL2ProfileSummary
{
    [JsonPropertyName("profileName")]
    public string ProfileName { get; set; } = string.Empty;

    [JsonPropertyName("attemptCount")]
    public int AttemptCount { get; set; }

    [JsonPropertyName("interestingAttemptCount")]
    public int InterestingAttemptCount { get; set; }

    [JsonPropertyName("nonZeroSetL2ReturnCount")]
    public int NonZeroSetL2ReturnCount { get; set; }

    [JsonPropertyName("maxSignalScore")]
    public int MaxSignalScore { get; set; }

    [JsonPropertyName("repeatIndices")]
    public List<int> RepeatIndices { get; set; } = new();

    [JsonPropertyName("sampleSignalHints")]
    public List<string> SampleSignalHints { get; set; } = new();
}

internal sealed class RuntimeLayoutReport
{
    [JsonPropertyName("generatedAt")]
    public DateTimeOffset GeneratedAt { get; set; }

    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("command")]
    public string Command { get; set; } = string.Empty;

    [JsonPropertyName("tdxRoot")]
    public string TdxRoot { get; set; } = string.Empty;

    [JsonPropertyName("appBaseDirectory")]
    public string AppBaseDirectory { get; set; } = string.Empty;

    [JsonPropertyName("currentDirectory")]
    public string CurrentDirectory { get; set; } = string.Empty;

    [JsonPropertyName("tcPluginsPath")]
    public string TcPluginsPath { get; set; } = string.Empty;

    [JsonPropertyName("tcPluginsDllCount")]
    public int TcPluginsDllCount { get; set; }

    [JsonPropertyName("etradeXmbPath")]
    public string EtradeXmbPath { get; set; } = string.Empty;

    [JsonPropertyName("etradeXmbPresent")]
    public bool EtradeXmbPresent { get; set; }

    [JsonPropertyName("tcOemXmbPath")]
    public string TcOemXmbPath { get; set; } = string.Empty;

    [JsonPropertyName("tcOemXmbPresent")]
    public bool TcOemXmbPresent { get; set; }

    [JsonPropertyName("etradeXmlPath")]
    public string EtradeXmlPath { get; set; } = string.Empty;

    [JsonPropertyName("etradeXmlPresent")]
    public bool EtradeXmlPresent { get; set; }

    [JsonPropertyName("tcOemXmlPath")]
    public string TcOemXmlPath { get; set; } = string.Empty;

    [JsonPropertyName("tcOemXmlPresent")]
    public bool TcOemXmlPresent { get; set; }

    [JsonPropertyName("usersProfilePath")]
    public string UsersProfilePath { get; set; } = string.Empty;

    [JsonPropertyName("usersProfilePresent")]
    public bool UsersProfilePresent { get; set; }

    [JsonPropertyName("syncedItems")]
    public List<string> SyncedItems { get; init; } = new();

    [JsonPropertyName("errors")]
    public List<string> Errors { get; init; } = new();

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class TcInitArgsSnapshot
{
    [JsonPropertyName("arg1")]
    public string? Arg1 { get; init; }

    [JsonPropertyName("arg2")]
    public string? Arg2 { get; init; }

    [JsonPropertyName("arg3")]
    public string? Arg3 { get; init; }

    [JsonPropertyName("arg5")]
    public string? Arg5 { get; init; }

    [JsonPropertyName("arg6")]
    public int Arg6 { get; init; }
}

internal sealed class TcSetL2ArgsSnapshot
{
    [JsonPropertyName("arg1")]
    public string? Arg1 { get; init; }

    [JsonPropertyName("arg2")]
    public string? Arg2 { get; init; }

    [JsonPropertyName("arg3")]
    public string? Arg3 { get; init; }
}

internal sealed class TcLoginRequestSnapshot
{
    [JsonPropertyName("function")]
    public string Function { get; init; } = string.Empty;

    [JsonPropertyName("profileName")]
    public string ProfileName { get; init; } = string.Empty;

    [JsonPropertyName("arg1Provided")]
    public bool Arg1Provided { get; init; }

    [JsonPropertyName("arg2Provided")]
    public bool Arg2Provided { get; init; }

    [JsonPropertyName("arg3Provided")]
    public bool Arg3Provided { get; init; }

    [JsonPropertyName("arg4Provided")]
    public bool Arg4Provided { get; init; }
}

internal sealed class MaskedArgumentSnapshot
{
    [JsonPropertyName("slot")]
    public int Slot { get; init; }

    [JsonPropertyName("source")]
    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("provided")]
    public bool Provided { get; init; }

    [JsonPropertyName("valueLength")]
    public int ValueLength { get; init; }

    [JsonPropertyName("maskedValue")]
    public string MaskedValue { get; init; } = string.Empty;
}

internal sealed class CachedLoginProfile
{
    public string Name { get; init; } = string.Empty;

    public List<CachedLoginArgument> Arguments { get; init; } = new();
}

internal sealed class CachedLoginArgument
{
    public int Slot { get; init; }

    public string Source { get; init; } = string.Empty;

    public string? Value { get; init; }
}

internal sealed class SetL2CandidateProfile
{
    public string Name { get; init; } = string.Empty;

    public List<SetL2CandidateArgument> Arguments { get; init; } = new();
}

internal sealed class SetL2CandidateArgument
{
    public int Slot { get; init; }

    public string Source { get; init; } = string.Empty;

    public string? Value { get; init; }
}

internal sealed class TcInitCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcLoginCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("function")]
    public string Function { get; init; } = string.Empty;

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcGetL2InfoCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("arg1")]
    public BufferSnapshot? Arg1 { get; set; }

    [JsonPropertyName("arg2")]
    public BufferSnapshot? Arg2 { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcGetLoginRetCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("arg1")]
    public BufferSnapshot? Arg1 { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcGetRightInfoCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("arg1")]
    public BufferSnapshot? Arg1 { get; set; }

    [JsonPropertyName("arg2")]
    public BufferSnapshot? Arg2 { get; set; }

    [JsonPropertyName("arg3")]
    public BufferSnapshot? Arg3 { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcUninitCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class TcSetL2UserInfoCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; init; }

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class BufferSnapshot
{
    [JsonPropertyName("size")]
    public int Size { get; init; }

    [JsonPropertyName("nonZeroBytes")]
    public int NonZeroBytes { get; init; }

    [JsonPropertyName("hexPrefix")]
    public string HexPrefix { get; init; } = string.Empty;

    [JsonPropertyName("ansiPreview")]
    public string AnsiPreview { get; init; } = string.Empty;

    [JsonPropertyName("gb18030Preview")]
    public string Gb18030Preview { get; init; } = string.Empty;

    public static BufferSnapshot From(HGlobalBuffer buffer)
    {
        var bytes = buffer.ToArray();
        return new BufferSnapshot
        {
            Size = bytes.Length,
            NonZeroBytes = bytes.Count(value => value != 0),
            HexPrefix = BuildHexPrefix(bytes, 128),
            AnsiPreview = Preview(bytes, Encoding.ASCII),
            Gb18030Preview = Preview(bytes, Encoding.GetEncoding("GB18030")),
        };
    }

    private static string BuildHexPrefix(byte[] bytes, int maxBytes)
    {
        return BitConverter.ToString(bytes.Take(maxBytes).ToArray()).Replace("-", " ").ToLowerInvariant();
    }

    private static string Preview(byte[] bytes, Encoding encoding)
    {
        var limit = Array.IndexOf(bytes, (byte)0);
        var count = limit >= 0 ? limit : Math.Min(bytes.Length, 96);
        if (count <= 0)
        {
            return string.Empty;
        }

        var text = encoding.GetString(bytes, 0, count);
        var builder = new StringBuilder(text.Length);
        foreach (var ch in text)
        {
            builder.Append(char.IsControl(ch) ? '.' : ch);
        }

        return builder.ToString();
    }
}

internal sealed class ModuleReport
{
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("path")]
    public string Path { get; init; } = string.Empty;

    [JsonPropertyName("exists")]
    public bool Exists { get; init; }

    [JsonPropertyName("fileArchitecture")]
    public string FileArchitecture { get; set; } = string.Empty;

    [JsonPropertyName("loaded")]
    public bool Loaded { get; set; }

    [JsonPropertyName("moduleHandle")]
    public string ModuleHandle { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("exports")]
    public List<ExportReport> Exports { get; init; } = new();
}

internal sealed class ExportReport
{
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("resolved")]
    public bool Resolved { get; init; }

    [JsonPropertyName("address")]
    public string Address { get; init; } = string.Empty;
}

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcInitEnvironFn(
    IntPtr arg1,
    IntPtr arg2,
    IntPtr arg3,
    IntPtr arg4,
    IntPtr arg5,
    int arg6);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcLoginFn(IntPtr arg1, IntPtr arg2, IntPtr arg3, IntPtr arg4);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcGetLoginRetFn(IntPtr arg1);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcGetRightInfoFn(IntPtr arg1, IntPtr arg2, IntPtr arg3);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcGetL2InfoFn(IntPtr arg1, IntPtr arg2);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TcSetL2UserInfoFn(IntPtr arg1, IntPtr arg2, IntPtr arg3);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate void TcUninitFn();

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TdxDeepStartInitFn(
    IntPtr arg1,
    IntPtr arg2,
    IntPtr arg3,
    IntPtr arg4,
    IntPtr arg5,
    IntPtr arg6,
    IntPtr arg7);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TdxDeepRegisterCallBackFuncFn(IntPtr arg1, IntPtr arg2, IntPtr arg3);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TdxDeepSetMainWndFn(IntPtr arg1, IntPtr arg2, IntPtr arg3, IntPtr arg4);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TdxDeepFuncFn(
    IntPtr arg1,
    IntPtr arg2,
    IntPtr arg3,
    IntPtr arg4,
    IntPtr arg5,
    IntPtr arg6,
    IntPtr arg7,
    IntPtr arg8,
    IntPtr arg9,
    IntPtr arg10);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate void TdxDeepCallbackFn(IntPtr arg1, uint arg2, IntPtr arg3, IntPtr arg4);

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
internal delegate int TdxDeepUninitFn();

internal sealed class OptionalAnsiString : IDisposable
{
    private OptionalAnsiString(IntPtr pointer)
    {
        Pointer = pointer;
    }

    public IntPtr Pointer { get; }

    public static OptionalAnsiString From(string? value)
    {
        return string.IsNullOrEmpty(value)
            ? new OptionalAnsiString(IntPtr.Zero)
            : new OptionalAnsiString(Marshal.StringToHGlobalAnsi(value));
    }

    public void Dispose()
    {
        if (Pointer != IntPtr.Zero)
        {
            Marshal.FreeHGlobal(Pointer);
        }
    }
}

internal sealed class HGlobalBuffer : IDisposable
{
    public HGlobalBuffer(int size)
    {
        Size = size;
        Pointer = Marshal.AllocHGlobal(size);
        Span<byte> zeros = new byte[size];
        Marshal.Copy(zeros.ToArray(), 0, Pointer, size);
    }

    public IntPtr Pointer { get; }

    public int Size { get; }

    public byte[] ToArray()
    {
        var bytes = new byte[Size];
        Marshal.Copy(Pointer, bytes, 0, Size);
        return bytes;
    }

    public void Dispose()
    {
        if (Pointer != IntPtr.Zero)
        {
            Marshal.FreeHGlobal(Pointer);
        }
    }
}

internal static partial class NativeMethods
{
    internal const uint WM_CLOSE = 0x0010;
    internal const uint WM_QUIT = 0x0012;

    internal delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern IntPtr LoadLibraryExW(string lpFileName, IntPtr hFile, uint dwFlags);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool FreeLibrary(IntPtr hModule);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    internal static extern IntPtr GetProcAddress(IntPtr hModule, string procName);

    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern uint SetErrorMode(uint uMode);

    [DllImport("kernel32.dll")]
    internal static extern uint GetCurrentThreadId();

    [DllImport("kernel32.dll")]
    internal static extern IntPtr GetConsoleWindow();

    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern IntPtr OpenProcess(uint dwDesiredAccess, [MarshalAs(UnmanagedType.Bool)] bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool ReadProcessMemory(
        IntPtr hProcess,
        IntPtr lpBaseAddress,
        [Out] byte[] lpBuffer,
        int nSize,
        out int lpNumberOfBytesRead);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool CloseHandle(IntPtr hObject);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    internal static extern uint GetWindowThreadProcessId(IntPtr hWnd, out int lpdwProcessId);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PostMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern IntPtr CreateWindowExW(
        uint dwExStyle,
        string lpClassName,
        string lpWindowName,
        uint dwStyle,
        int x,
        int y,
        int nWidth,
        int nHeight,
        IntPtr hWndParent,
        IntPtr hMenu,
        IntPtr hInstance,
        IntPtr lpParam);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool DestroyWindow(IntPtr hWnd);

    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern int VirtualQueryEx(
        IntPtr hProcess,
        IntPtr lpAddress,
        ref MEMORY_BASIC_INFORMATION lpBuffer,
        int dwLength);

    [StructLayout(LayoutKind.Sequential)]
    internal struct MEMORY_BASIC_INFORMATION
    {
        public IntPtr BaseAddress;
        public IntPtr AllocationBase;
        public uint AllocationProtect;
        public ushort PartitionId;
        public UIntPtr RegionSize;
        public uint State;
        public uint Protect;
        public uint Type;
    }

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern int GetMessageW(out Message lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool TranslateMessage([In] ref Message lpMsg);

    [DllImport("user32.dll")]
    internal static extern IntPtr DispatchMessageW([In] ref Message lpMsg);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PostThreadMessageW(uint idThread, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    internal struct Message
    {
        public IntPtr HWnd;
        public uint Msg;
        public IntPtr WParam;
        public IntPtr LParam;
        public uint Time;
        public int PointX;
        public int PointY;
    }
}
