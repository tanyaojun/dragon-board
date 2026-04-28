using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace TdxL2Helper;

internal static partial class Program
{
    private static SelfHostRuntimeReport BuildSelfHostRuntimeReport(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var deepPath = ResolvePath(options.DeepPath, Path.Combine(tdxRoot, "TDXDeep.dll"));
        var report = new SelfHostRuntimeReport
        {
            GeneratedAt = DateTimeOffset.Now,
            Command = "host-runtime",
            ProcessArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
            FrameworkDescription = RuntimeInformation.FrameworkDescription,
            PointerSizeBits = IntPtr.Size * 8,
            TdxRoot = tdxRoot,
            TcPath = tcPath,
            DeepPath = deepPath,
            BufferSize = options.BufferSize,
            HeartbeatIntervalMs = options.HeartbeatIntervalMs,
            SampleCount = Math.Max(0, options.SampleCount),
            InitArgs = new TcInitArgsSnapshot
            {
                Arg1 = options.InitArg1,
                Arg2 = options.InitArg2,
                Arg3 = options.InitArg3,
                Arg5 = options.InitArg5,
                Arg6 = options.InitArg6,
            },
            ProbeLoginState = options.ProbeLoginState,
            LoginRequest = options.HasLoginInvocationRequest ? BuildLoginRequestSnapshot(options) : null,
            SetL2Args = new TcSetL2ArgsSnapshot
            {
                Arg1 = options.SetL2Arg1,
                Arg2 = options.SetL2Arg2,
                Arg3 = options.SetL2Arg3,
            },
        };

        report.RuntimeLayout = SyncRuntimeLayout(options, "host-runtime");

        try
        {
            using var session = SelfHostSession.Open(tdxRoot, tcPath, deepPath);
            report.Modules.Add(session.TcModule.Report);
            report.Modules.Add(session.DeepModule.Report);

            if (!string.IsNullOrWhiteSpace(session.Error))
            {
                report.Error = session.Error;
                report.Notes.Add("The host loaded at least one module unsuccessfully. See modules[].error for detail.");
                return FinalizeSelfHostReport(report);
            }

            report.InitResult = session.TryInitialize(options);
            if (options.ProbeLoginState)
            {
                report.ProbeGetLoginRet = session.CaptureLoginRet(options.BufferSize);
                report.ProbeGetRightInfo = session.CaptureRightInfo(options.BufferSize);
            }

            if (options.HasLoginInvocationRequest)
            {
                report.LoginResult = session.TryLogin(options);
                if (options.ProbeLoginState)
                {
                    report.PostLoginGetLoginRet = session.CaptureLoginRet(options.BufferSize);
                    report.PostLoginGetRightInfo = session.CaptureRightInfo(options.BufferSize);
                }
            }

            if (options.HasSetL2Args)
            {
                report.SetL2Result = session.TrySetL2UserInfo(options);
            }

            report.DeepInit = session.TryInitializeDeep(options.UnsafeDeepStart, options.UnsafeDeepFuncProbe, options.UnsafeDeepFuncCodes);

            if (session.CanGetL2Info)
            {
                report.InitialGetL2Info = session.CaptureL2Info(options.BufferSize);
            }

            report.DeepData = session.CaptureDeepData();

            for (var sampleIndex = 0; sampleIndex < report.SampleCount; sampleIndex++)
            {
                if (sampleIndex > 0 && options.HeartbeatIntervalMs > 0)
                {
                    Thread.Sleep(options.HeartbeatIntervalMs);
                }

                report.HeartbeatSamples.Add(
                    new SelfHostHeartbeatSample
                    {
                        Timestamp = DateTimeOffset.Now,
                        SampleIndex = sampleIndex,
                        GetL2Info = session.CanGetL2Info ? session.CaptureL2Info(options.BufferSize) : null,
                        DeepData = session.CaptureDeepData(),
                    });
            }

            report.Notes.Add("host-runtime always syncs the helper-side runtime layout before loading official DLLs.");
            report.Notes.Add("This is the standalone x86 host baseline: tc.dll is initialized in-process and queried over stdio-safe JSON.");
            report.Notes.Add("Sequence: TC_Init_Environ -> optional login-state probe -> optional TC_Login/TC_Login2 -> optional TC_SetL2UserInfo -> TDXDeep register -> optional TDXDeep start -> TC_GetL2Info -> heartbeats.");
            report.Notes.Add("TDXDeep signatures are provisional: RegisterCallBackFunc uses 3 IntPtr args, StartInit uses 7 IntPtr args, Func uses 10 IntPtr args, callback uses IntPtr/uint/IntPtr/IntPtr.");
            report.Notes.Add("TdxDeep_StartInit is gated behind --unsafe-deep-start. TdxDeep_Func is separately gated behind --unsafe-deep-func-probe because empty-context calls can block.");
            report.Notes.Add("Use --event-stream to switch stdout into compact NDJSON heartbeat mode for an outer bridge.");
            return FinalizeSelfHostReport(report);
        }
        catch (Exception error)
        {
            report.Error = error.Message;
            report.Notes.Add($"{error.GetType().Name}: {error.Message}");
            return FinalizeSelfHostReport(report);
        }
    }

    private static SelfHostRuntimeReport FinalizeSelfHostReport(SelfHostRuntimeReport report)
    {
        if (string.IsNullOrWhiteSpace(report.Error))
        {
            var stepErrors = new[]
            {
                DescribeStepError("TC_Init_Environ", report.InitResult?.Error),
                DescribeStepError("TC_GetLoginRet", report.ProbeGetLoginRet?.Error),
                DescribeStepError("TC_GetRightInfo", report.ProbeGetRightInfo?.Error),
                DescribeStepError("TC_Login", report.LoginResult?.Error),
                DescribeStepError("TC_SetL2UserInfo", report.SetL2Result?.Error),
                DescribeStepError("TdxDeep_RegisterCallBackFunc", report.DeepInit?.RegisterResult?.Error),
                DescribeStepError("TdxDeep_StartInit", report.DeepInit?.StartResult?.Error),
                DescribeStepError("TC_GetL2Info", report.InitialGetL2Info?.Error),
            }.Where(error => !string.IsNullOrWhiteSpace(error)).ToArray();

            if (stepErrors.Length > 0)
            {
                report.Error = stepErrors[0];
            }
        }

        report.Ok = string.IsNullOrWhiteSpace(report.Error)
            && report.Modules.All(module => module.Exists && module.Loaded && string.IsNullOrWhiteSpace(module.Error));
        return report;
    }

    private static string DescribeStepError(string stepName, string? error)
    {
        return string.IsNullOrWhiteSpace(error) ? string.Empty : $"{stepName}: {error}";
    }

    private static int RunSelfHostEventStream(CliOptions options)
    {
        var tdxRoot = Path.GetFullPath(options.TdxRoot);
        var tcPath = ResolveTcPath(tdxRoot, options.TcPath);
        var deepPath = ResolvePath(options.DeepPath, Path.Combine(tdxRoot, "TDXDeep.dll"));
        var runtimeLayout = SyncRuntimeLayout(options, "host-runtime");
        var startedAt = DateTimeOffset.Now;

        try
        {
            WriteHostEvent(
                "boot",
                new
                {
                    generatedAt = startedAt,
                    command = "host-runtime",
                    processArchitecture = RuntimeInformation.ProcessArchitecture.ToString(),
                    pointerSizeBits = IntPtr.Size * 8,
                    tdxRoot,
                    tcPath,
                    deepPath,
                    bufferSize = options.BufferSize,
                    heartbeatIntervalMs = options.HeartbeatIntervalMs,
                    sampleCount = options.SampleCount,
                    durationMs = options.DurationMs,
                    probeLoginState = options.ProbeLoginState,
                    loginRequest = options.HasLoginInvocationRequest ? BuildLoginRequestSnapshot(options) : null,
                    setL2Args = options.HasSetL2Args
                        ? new TcSetL2ArgsSnapshot
                        {
                            Arg1 = options.SetL2Arg1,
                            Arg2 = options.SetL2Arg2,
                            Arg3 = options.SetL2Arg3,
                        }
                        : null,
                    runtimeLayout,
                });

            using var session = SelfHostSession.Open(tdxRoot, tcPath, deepPath);

            WriteHostEvent(
                "modules",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    modules = new[] { session.TcModule.Report, session.DeepModule.Report },
                    session.Error,
                });

            if (!string.IsNullOrWhiteSpace(session.Error))
            {
                WriteHostEvent(
                    "shutdown",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        ok = false,
                        error = session.Error,
                    });
                return 2;
            }

            var initResult = session.TryInitialize(options);
            WriteHostEvent(
                "tc_init",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    result = initResult,
                });

            if (options.ProbeLoginState)
            {
                WriteHostEvent(
                    "probe_login_state",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        getLoginRet = session.CaptureLoginRet(options.BufferSize),
                        getRightInfo = session.CaptureRightInfo(options.BufferSize),
                    });
            }

            if (options.HasLoginInvocationRequest)
            {
                var loginResult = session.TryLogin(options);
                WriteHostEvent(
                    "tc_login",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        request = BuildLoginRequestSnapshot(options),
                        result = loginResult,
                    });

                if (options.ProbeLoginState)
                {
                    WriteHostEvent(
                        "post_login_state",
                        new
                        {
                            generatedAt = DateTimeOffset.Now,
                            getLoginRet = session.CaptureLoginRet(options.BufferSize),
                            getRightInfo = session.CaptureRightInfo(options.BufferSize),
                        });
                }
            }

            if (options.HasSetL2Args)
            {
                WriteHostEvent(
                    "tc_setl2",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        args = new TcSetL2ArgsSnapshot
                        {
                            Arg1 = options.SetL2Arg1,
                            Arg2 = options.SetL2Arg2,
                            Arg3 = options.SetL2Arg3,
                        },
                        result = session.TrySetL2UserInfo(options),
                    });
            }

            var deepInit = session.TryInitializeDeep(options.UnsafeDeepStart, options.UnsafeDeepFuncProbe, options.UnsafeDeepFuncCodes);
            WriteHostEvent(
                "deep_register",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    result = deepInit.RegisterResult,
                    deepState = deepInit.State,
                });
            WriteHostEvent(
                "deep_start",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    result = deepInit.StartResult,
                    deepState = session.CaptureDeepData().State,
                });

            if (session.CanGetL2Info)
            {
                WriteHostEvent(
                    "getl2info",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        sampleIndex = -1,
                        result = session.CaptureL2Info(options.BufferSize),
                    });
            }

            using var cts = new CancellationTokenSource();
            Console.CancelKeyPress += (_, eventArgs) =>
            {
                eventArgs.Cancel = true;
                cts.Cancel();
            };

            var emitted = 0;
            var deadline = options.DurationMs > 0 ? startedAt.AddMilliseconds(options.DurationMs) : DateTimeOffset.MaxValue;
            while (!cts.IsCancellationRequested)
            {
                if (options.SampleCount > 0 && emitted >= options.SampleCount)
                {
                    break;
                }

                if (DateTimeOffset.Now >= deadline)
                {
                    break;
                }

                if (emitted > 0 && options.HeartbeatIntervalMs > 0)
                {
                    Thread.Sleep(options.HeartbeatIntervalMs);
                }

                var deepData = session.CaptureDeepData(drainCallbacks: true);
                foreach (var callback in deepData.Callbacks)
                {
                    WriteHostEvent(
                        "deep_callback",
                        new
                        {
                            generatedAt = DateTimeOffset.Now,
                            data = callback,
                        });
                }

                WriteHostEvent(
                    "heartbeat",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        sampleIndex = emitted,
                        uptimeMs = (int)(DateTimeOffset.Now - startedAt).TotalMilliseconds,
                        getL2Info = session.CanGetL2Info ? session.CaptureL2Info(options.BufferSize) : null,
                        deepState = deepData.State,
                    });

                emitted += 1;
            }

            var finalDeepData = session.CaptureDeepData(drainCallbacks: true);
            foreach (var callback in finalDeepData.Callbacks)
            {
                WriteHostEvent(
                    "deep_callback",
                    new
                    {
                        generatedAt = DateTimeOffset.Now,
                        data = callback,
                    });
            }

            WriteHostEvent(
                "shutdown",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    ok = true,
                    uptimeMs = (int)(DateTimeOffset.Now - startedAt).TotalMilliseconds,
                    sampleCount = emitted,
                    deepState = finalDeepData.State,
                });
            return 0;
        }
        catch (Exception error)
        {
            WriteHostEvent(
                "error",
                new
                {
                    generatedAt = DateTimeOffset.Now,
                    ok = false,
                    errorType = error.GetType().Name,
                    error = error.Message,
                });
            return 1;
        }
    }

    private static void WriteHostEvent(string eventType, object payload)
    {
        Console.WriteLine(
            JsonSerializer.Serialize(
                new
                {
                    @event = eventType,
                    payload,
                },
                JsonOptions.Compact));
        Console.Out.Flush();
    }

    private sealed class SelfHostSession : IDisposable
    {
        private const int DeepCallbackBufferLimit = 16;
        private const int DeepCallbackPreviewBytes = 128;
        private readonly string previousDirectory;
        private readonly string tdxRoot;
        private readonly object deepSync = new();
        private readonly Queue<DeepCallbackSample> deepCallbacks = new();
        private readonly TdxDeepCallbackFn deepCallbackThunk;
        private int deepCallbackSequence;
        private int deepCallbackCount;
        private bool deepRegisterAttempted;
        private bool deepRegisterSucceeded;
        private bool deepStartAttempted;
        private bool deepStartSucceeded;
        private bool deepSetMainWndAttempted;
        private bool deepSetMainWndSucceeded;
        private bool deepUnsafeFuncProbeAttempted;
        private bool deepUninitAttempted;
        private DeepCallbackSample? lastDeepCallback;
        private DeepCallReport? lastDeepRegister;
        private DeepCallReport? lastDeepStart;
        private DeepCallReport? lastDeepSetMainWnd;
        private bool tcInitialized;
        private bool disposed;

        private SelfHostSession(
            string previousDirectory,
            string tdxRoot,
            LoadedModule tcModule,
            LoadedModule deepModule,
            string error)
        {
            this.previousDirectory = previousDirectory;
            this.tdxRoot = tdxRoot;
            TcModule = tcModule;
            DeepModule = deepModule;
            Error = error;
            deepCallbackThunk = HandleDeepCallback;

            if (tcModule.Exports.TryGetValue("TC_Init_Environ", out var initPtr) && initPtr != IntPtr.Zero)
            {
                init = Marshal.GetDelegateForFunctionPointer<TcInitEnvironFn>(initPtr);
            }

            if (tcModule.Exports.TryGetValue("TC_GetL2Info", out var getL2Ptr) && getL2Ptr != IntPtr.Zero)
            {
                getL2Info = Marshal.GetDelegateForFunctionPointer<TcGetL2InfoFn>(getL2Ptr);
            }

            if (tcModule.Exports.TryGetValue("TC_Login", out var loginPtr) && loginPtr != IntPtr.Zero)
            {
                login = Marshal.GetDelegateForFunctionPointer<TcLoginFn>(loginPtr);
            }

            if (tcModule.Exports.TryGetValue("TC_Login2", out var login2Ptr) && login2Ptr != IntPtr.Zero)
            {
                login2 = Marshal.GetDelegateForFunctionPointer<TcLoginFn>(login2Ptr);
            }

            if (tcModule.Exports.TryGetValue("TC_GetLoginRet", out var getLoginRetPtr) && getLoginRetPtr != IntPtr.Zero)
            {
                getLoginRet = Marshal.GetDelegateForFunctionPointer<TcGetLoginRetFn>(getLoginRetPtr);
            }

            if (tcModule.Exports.TryGetValue("TC_GetRightInfo", out var getRightInfoPtr) && getRightInfoPtr != IntPtr.Zero)
            {
                getRightInfo = Marshal.GetDelegateForFunctionPointer<TcGetRightInfoFn>(getRightInfoPtr);
            }

            if (tcModule.Exports.TryGetValue("TC_SetL2UserInfo", out var setL2UserInfoPtr) && setL2UserInfoPtr != IntPtr.Zero)
            {
                setL2UserInfo = Marshal.GetDelegateForFunctionPointer<TcSetL2UserInfoFn>(setL2UserInfoPtr);
            }

            if (tcModule.Exports.TryGetValue("TC_Uninit", out var uninitPtr) && uninitPtr != IntPtr.Zero)
            {
                uninit = Marshal.GetDelegateForFunctionPointer<TcUninitFn>(uninitPtr);
            }

            if (deepModule.Exports.TryGetValue("TdxDeep_RegisterCallBackFunc", out var deepRegisterPtr) && deepRegisterPtr != IntPtr.Zero)
            {
                deepRegister = Marshal.GetDelegateForFunctionPointer<TdxDeepRegisterCallBackFuncFn>(deepRegisterPtr);
            }

            if (deepModule.Exports.TryGetValue("TdxDeep_StartInit", out var deepStartPtr) && deepStartPtr != IntPtr.Zero)
            {
                deepStart = Marshal.GetDelegateForFunctionPointer<TdxDeepStartInitFn>(deepStartPtr);
            }

            if (deepModule.Exports.TryGetValue("TdxDeep_SetMainWnd", out var deepSetMainWndPtr) && deepSetMainWndPtr != IntPtr.Zero)
            {
                deepSetMainWnd = Marshal.GetDelegateForFunctionPointer<TdxDeepSetMainWndFn>(deepSetMainWndPtr);
            }

            if (deepModule.Exports.TryGetValue("TdxDeep_Func", out var deepFuncPtr) && deepFuncPtr != IntPtr.Zero)
            {
                deepFunc = Marshal.GetDelegateForFunctionPointer<TdxDeepFuncFn>(deepFuncPtr);
            }

            if (deepModule.Exports.TryGetValue("TdxDeep_Uninit", out var deepUninitPtr) && deepUninitPtr != IntPtr.Zero)
            {
                deepUninit = Marshal.GetDelegateForFunctionPointer<TdxDeepUninitFn>(deepUninitPtr);
            }
        }

        private readonly TcInitEnvironFn? init;
        private readonly TcLoginFn? login;
        private readonly TcLoginFn? login2;
        private readonly TcGetLoginRetFn? getLoginRet;
        private readonly TcGetRightInfoFn? getRightInfo;
        private readonly TcGetL2InfoFn? getL2Info;
        private readonly TcSetL2UserInfoFn? setL2UserInfo;
        private readonly TcUninitFn? uninit;
        private readonly TdxDeepRegisterCallBackFuncFn? deepRegister;
        private readonly TdxDeepStartInitFn? deepStart;
        private readonly TdxDeepSetMainWndFn? deepSetMainWnd;
        private readonly TdxDeepFuncFn? deepFunc;
        private readonly TdxDeepUninitFn? deepUninit;

        public LoadedModule TcModule { get; }

        public LoadedModule DeepModule { get; }

        public string Error { get; }

        public bool CanGetLoginRet => getLoginRet is not null;

        public bool CanGetRightInfo => getRightInfo is not null;

        public bool CanGetL2Info => getL2Info is not null;

        public static SelfHostSession Open(string tdxRoot, string tcPath, string deepPath)
        {
            var previousDirectory = Directory.GetCurrentDirectory();
            Directory.SetCurrentDirectory(tdxRoot);

            var tcModule = LoadModule("tc.dll", tcPath, TcExports);
            var deepModule = LoadModule("TDXDeep.dll", deepPath, DeepExports);
            var errors = new[] { tcModule.Report.Error, deepModule.Report.Error }
                .Where(error => !string.IsNullOrWhiteSpace(error))
                .ToArray();

            return new SelfHostSession(previousDirectory, tdxRoot, tcModule, deepModule, string.Join("; ", errors));
        }

        public TcInitCallReport? TryInitialize(CliOptions options)
        {
            if (init is null)
            {
                return null;
            }

            var result = InvokeTcInitEnviron(init, options);
            tcInitialized = string.IsNullOrWhiteSpace(result.Error);
            return result;
        }

        public TcLoginCallReport? TryLogin(CliOptions options)
        {
            if (!options.HasLoginInvocationRequest)
            {
                return null;
            }

            var functionName = options.LoginFunction ?? string.Empty;
            var target = string.Equals(functionName, "login2", StringComparison.OrdinalIgnoreCase)
                ? login2
                : login;
            if (target is null)
            {
                return new TcLoginCallReport
                {
                    Invoked = false,
                    Function = functionName,
                    Error = $"missing export for {functionName}",
                };
            }

            return InvokeTcLogin(target, functionName, options);
        }

        public TcGetLoginRetCallReport? CaptureLoginRet(int bufferSize)
        {
            if (getLoginRet is null)
            {
                return null;
            }

            return InvokeTcGetLoginRet(getLoginRet, bufferSize);
        }

        public TcGetRightInfoCallReport? CaptureRightInfo(int bufferSize)
        {
            if (getRightInfo is null)
            {
                return null;
            }

            return InvokeTcGetRightInfo(getRightInfo, bufferSize);
        }

        public TcGetL2InfoCallReport? CaptureL2Info(int bufferSize)
        {
            if (getL2Info is null)
            {
                return null;
            }

            return InvokeTcGetL2Info(getL2Info, bufferSize);
        }

        public TcSetL2UserInfoCallReport? TrySetL2UserInfo(CliOptions options)
        {
            if (!options.HasSetL2Args)
            {
                return null;
            }

            if (setL2UserInfo is null)
            {
                return new TcSetL2UserInfoCallReport
                {
                    Invoked = false,
                    Error = "missing export for TC_SetL2UserInfo",
                };
            }

            return InvokeTcSetL2UserInfo(setL2UserInfo, options);
        }

        public SelfHostDeepInitReport TryInitializeDeep(bool allowUnsafeStart, bool allowUnsafeFuncProbe, IReadOnlyList<int> unsafeFuncCodes)
        {
            var registerResult = TryRegisterDeepCallback();
            var startResult = TryStartDeep(allowUnsafeStart);
            var funcProbeResults = allowUnsafeFuncProbe && allowUnsafeStart && string.IsNullOrWhiteSpace(startResult.Error)
                ? TryProbeDeepFunc(unsafeFuncCodes)
                : new List<DeepCallReport>();
            return new SelfHostDeepInitReport
            {
                RegisterResult = registerResult,
                StartResult = startResult,
                FuncProbeResults = funcProbeResults,
                State = CaptureDeepState(),
            };
        }

        public SelfHostDeepDataSnapshot CaptureDeepData(bool drainCallbacks = false)
        {
            lock (deepSync)
            {
                var callbacks = deepCallbacks.ToList();
                if (drainCallbacks)
                {
                    deepCallbacks.Clear();
                }

                return new SelfHostDeepDataSnapshot
                {
                    State = BuildDeepStateSnapshotUnsafe(),
                    Callbacks = callbacks,
                };
            }
        }

        private DeepCallReport TryRegisterDeepCallback()
        {
            var report = new DeepCallReport
            {
                Invoked = deepRegister is not null,
                Function = "TdxDeep_RegisterCallBackFunc",
                SignatureAssumption = "cdecl int fn(IntPtr callback, IntPtr arg2, IntPtr arg3)",
            };

            if (deepRegister is null)
            {
                report.Error = "missing export for TdxDeep_RegisterCallBackFunc";
                return report;
            }

            deepRegisterAttempted = true;
            var started = DateTime.UtcNow;
            try
            {
                var callbackPtr = Marshal.GetFunctionPointerForDelegate(deepCallbackThunk);
                report.ReturnValue = deepRegister(callbackPtr, IntPtr.Zero, IntPtr.Zero);
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
                deepRegisterSucceeded = string.IsNullOrWhiteSpace(report.Error);
                lastDeepRegister = report;
            }

            return report;
        }

        private DeepCallReport TryStartDeep(bool allowUnsafeStart)
        {
            var report = new DeepCallReport
            {
                Invoked = deepStart is not null,
                Function = "TdxDeep_StartInit",
                SignatureAssumption = "cdecl int fn(IntPtr arg1, IntPtr arg2, IntPtr arg3, IntPtr arg4, IntPtr arg5, IntPtr arg6, IntPtr arg7)",
            };

            if (!allowUnsafeStart)
            {
                report.Invoked = false;
                report.Skipped = true;
                report.SkipReason = "disabled unless --unsafe-deep-start";
                return report;
            }

            if (deepStart is null)
            {
                report.Error = "missing export for TdxDeep_StartInit";
                return report;
            }

            deepStartAttempted = true;
            var started = DateTime.UtcNow;
            try
            {
                using var arg1 = OptionalAnsiString.From(EnsureTrailingSlash(tdxRoot));
                using var arg2 = OptionalAnsiString.From(EnsureTrailingSlash(Path.Combine(tdxRoot, "T0002")));
                using var arg3 = OptionalAnsiString.From(Path.Combine(tdxRoot, "connect.cfg"));
                using var arg6 = BuildDeepMarketDescriptorBuffer();
                report.ReturnValue = deepStart(
                    arg1.Pointer,
                    arg2.Pointer,
                    arg3.Pointer,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    arg6.Pointer,
                    IntPtr.Zero);
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
                deepStartSucceeded = string.IsNullOrWhiteSpace(report.Error);
                lastDeepStart = report;
            }

            return report;
        }

        private static string EnsureTrailingSlash(string path)
        {
            return path.EndsWith(Path.DirectorySeparatorChar)
                ? path
                : path + Path.DirectorySeparatorChar;
        }

        private static HGlobalBuffer BuildDeepMarketDescriptorBuffer()
        {
            var buffer = new HGlobalBuffer(128);
            var textBytes = Encoding.GetEncoding("GB18030").GetBytes("扩展市场行情");
            Marshal.Copy(textBytes, 0, buffer.Pointer, textBytes.Length);
            Marshal.Copy(textBytes, 0, IntPtr.Add(buffer.Pointer, 50), textBytes.Length);

            WriteInt32(buffer.Pointer, 100, 0x00020002);
            WriteInt32(buffer.Pointer, 108, 1);
            WriteInt32(buffer.Pointer, 112, 1);
            WriteInt32(buffer.Pointer, 116, 1);
            return buffer;
        }

        private static void WriteInt32(IntPtr pointer, int offset, int value)
        {
            var bytes = BitConverter.GetBytes(value);
            Marshal.Copy(bytes, 0, IntPtr.Add(pointer, offset), bytes.Length);
        }

        private List<DeepCallReport> TryProbeDeepFunc(IReadOnlyList<int> unsafeFuncCodes)
        {
            var reports = new List<DeepCallReport>();
            deepUnsafeFuncProbeAttempted = true;
            TraceUnsafeDeepFuncProbe("creating hidden message window");
            using var messageWindow = HiddenMessageWindow.Start();
            var hwnd = messageWindow.Handle != IntPtr.Zero
                ? messageWindow.Handle
                : NativeMethods.GetConsoleWindow();
            TraceUnsafeDeepFuncProbe($"calling TdxDeep_SetMainWnd hwnd={FormatPointer(hwnd)} hiddenWindow={FormatPointer(messageWindow.Handle)}");
            var setMainWndResult = TrySetDeepMainWnd(hwnd, messageWindow);
            reports.Add(setMainWndResult);
            TraceUnsafeDeepFuncProbe($"TdxDeep_SetMainWnd returned error={setMainWndResult.Error} returnValue={setMainWndResult.ReturnValue}");
            if (hwnd == IntPtr.Zero || !string.IsNullOrWhiteSpace(setMainWndResult.Error))
            {
                return reports;
            }

            if (deepFunc is null)
            {
                reports.Add(
                    new DeepCallReport
                    {
                        Invoked = false,
                        Function = "TdxDeep_Func",
                        SignatureAssumption = "cdecl int fn(10 pointer-sized args)",
                        Error = "missing export for TdxDeep_Func",
                    });
                return reports;
            }

            foreach (var code in unsafeFuncCodes)
            {
                TraceUnsafeDeepFuncProbe($"calling TdxDeep_Func code={code} hwnd={FormatPointer(hwnd)}");
                reports.Add(TryCallDeepFuncCode(code, hwnd));
                TraceUnsafeDeepFuncProbe($"TdxDeep_Func code={code} returned error={reports[^1].Error} returnValue={reports[^1].ReturnValue} elapsedMs={reports[^1].ElapsedMs}");
            }

            return reports;
        }

        private static void TraceUnsafeDeepFuncProbe(string message)
        {
            Console.Error.WriteLine($"[unsafe-deep-func-probe] {DateTimeOffset.Now:O} {message}");
            Console.Error.Flush();
        }

        private DeepCallReport TrySetDeepMainWnd(IntPtr hwnd, HiddenMessageWindow messageWindow)
        {
            var report = new DeepCallReport
            {
                Invoked = deepSetMainWnd is not null,
                Function = "TdxDeep_SetMainWnd",
                SignatureAssumption = "cdecl int fn(hwnd, 0x13d7, 0, 0)",
                Details = $"hwnd={FormatPointer(hwnd)}; hiddenWindowHandle={FormatPointer(messageWindow.Handle)}; hiddenWindowError={messageWindow.Error}",
            };

            if (deepSetMainWnd is null)
            {
                report.Error = "missing export for TdxDeep_SetMainWnd";
                return report;
            }

            if (hwnd == IntPtr.Zero)
            {
                report.Invoked = false;
                report.Error = "no valid HWND for TdxDeep_SetMainWnd";
                return report;
            }

            deepSetMainWndAttempted = true;
            var started = DateTime.UtcNow;
            try
            {
                report.ReturnValue = deepSetMainWnd(hwnd, new IntPtr(0x13d7), IntPtr.Zero, IntPtr.Zero);
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
                deepSetMainWndSucceeded = string.IsNullOrWhiteSpace(report.Error);
                lastDeepSetMainWnd = report;
            }

            return report;
        }

        private DeepCallReport TryCallDeepFuncCode(int code, IntPtr hwnd)
        {
            if (code == 4)
            {
                return TryCallDeepFuncCode4(hwnd);
            }

            var report = new DeepCallReport
            {
                Invoked = true,
                Function = $"TdxDeep_Func:{code}",
                SignatureAssumption = "cdecl int fn(0, empty, empty, code, 0, 0, 0, result*, 0, hwnd)",
                Details = $"hwnd={FormatPointer(hwnd)}",
            };

            var started = DateTime.UtcNow;
            try
            {
                using var empty = new HGlobalBuffer(1);
                using var result = new HGlobalBuffer(16);
                report.ReturnValue = deepFunc!(
                    IntPtr.Zero,
                    empty.Pointer,
                    empty.Pointer,
                    new IntPtr(code),
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    result.Pointer,
                    IntPtr.Zero,
                    hwnd);
                report.Win32LastError = Marshal.GetLastWin32Error();
                report.ResultHex = Convert.ToHexString(result.ToArray().Take(16).ToArray());
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

        private DeepCallReport TryCallDeepFuncCode4(IntPtr hwnd)
        {
            var report = new DeepCallReport
            {
                Invoked = true,
                Function = "TdxDeep_Func:4",
                SignatureAssumption = "cdecl int fn(0, empty, empty, 4, 0, 0, buffer*, len*, 0, hwnd)",
                Details = $"hwnd={FormatPointer(hwnd)}; bufferSize=0x96",
            };

            var started = DateTime.UtcNow;
            try
            {
                using var empty = new HGlobalBuffer(1);
                using var buffer = new HGlobalBuffer(0x96);
                using var lengthBuffer = new HGlobalBuffer(16);
                WriteInt32(lengthBuffer.Pointer, 0, 0x96);

                report.ReturnValue = deepFunc!(
                    IntPtr.Zero,
                    empty.Pointer,
                    empty.Pointer,
                    new IntPtr(4),
                    IntPtr.Zero,
                    IntPtr.Zero,
                    buffer.Pointer,
                    lengthBuffer.Pointer,
                    IntPtr.Zero,
                    hwnd);
                report.Win32LastError = Marshal.GetLastWin32Error();
                report.ResultHex = Convert.ToHexString(lengthBuffer.ToArray().Take(16).ToArray());
                report.OutputPreview = NativePointerPreview.FromBytes(buffer.ToArray());
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

        private void HandleDeepCallback(IntPtr arg1, uint arg2, IntPtr arg3, IntPtr arg4)
        {
            var sample = new DeepCallbackSample
            {
                Sequence = System.Threading.Interlocked.Increment(ref deepCallbackSequence),
                Timestamp = DateTimeOffset.Now,
                ThreadId = Environment.CurrentManagedThreadId,
                Arg1 = FormatPointer(arg1),
                Arg2 = arg2,
                Arg3 = FormatPointer(arg3),
                Arg4 = FormatPointer(arg4),
                Arg1Preview = TryReadPointerPreview(arg1, DeepCallbackPreviewBytes),
                Arg4Preview = TryReadPointerPreview(arg4, DeepCallbackPreviewBytes),
            };

            lock (deepSync)
            {
                lastDeepCallback = sample;
                deepCallbackCount += 1;
                while (deepCallbacks.Count >= DeepCallbackBufferLimit)
                {
                    deepCallbacks.Dequeue();
                }

                deepCallbacks.Enqueue(sample);
            }
        }

        private DeepStateSnapshot CaptureDeepState()
        {
            lock (deepSync)
            {
                return BuildDeepStateSnapshotUnsafe();
            }
        }

        private DeepStateSnapshot BuildDeepStateSnapshotUnsafe()
        {
            return new DeepStateSnapshot
            {
                RegisterSupported = deepRegister is not null,
                StartSupported = deepStart is not null,
                SetMainWndSupported = deepSetMainWnd is not null,
                UninitSupported = deepUninit is not null,
                RegisterAttempted = deepRegisterAttempted,
                RegisterSucceeded = deepRegisterSucceeded,
                StartAttempted = deepStartAttempted,
                StartSucceeded = deepStartSucceeded,
                SetMainWndAttempted = deepSetMainWndAttempted,
                SetMainWndSucceeded = deepSetMainWndSucceeded,
                UninitAttempted = deepUninitAttempted,
                CallbackCount = deepCallbackCount,
                BufferedCallbackCount = deepCallbacks.Count,
                LastRegister = lastDeepRegister,
                LastStart = lastDeepStart,
                LastSetMainWnd = lastDeepSetMainWnd,
                LastCallback = lastDeepCallback,
            };
        }

        private static string FormatPointer(IntPtr value)
        {
            return $"0x{value.ToInt64():X}";
        }

        private static NativePointerPreview TryReadPointerPreview(IntPtr pointer, int size)
        {
            if (pointer == IntPtr.Zero)
            {
                return NativePointerPreview.Empty("null");
            }

            var pid = Environment.ProcessId;
            var processHandle = NativeMethods.OpenProcess(ProcessVmRead | ProcessQueryInformation | ProcessQueryLimitedInformation, false, pid);
            if (processHandle == IntPtr.Zero)
            {
                return NativePointerPreview.Empty(new Win32Exception(Marshal.GetLastWin32Error()).Message);
            }

            try
            {
                var buffer = new byte[size];
                if (!NativeMethods.ReadProcessMemory(processHandle, pointer, buffer, size, out var bytesRead) || bytesRead <= 0)
                {
                    return NativePointerPreview.Empty(new Win32Exception(Marshal.GetLastWin32Error()).Message);
                }

                var data = buffer.Take(bytesRead).ToArray();
                return NativePointerPreview.FromBytes(data);
            }
            finally
            {
                NativeMethods.CloseHandle(processHandle);
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            try
            {
                if ((deepRegisterAttempted || deepStartAttempted) && deepUninit is not null)
                {
                    if (!deepUnsafeFuncProbeAttempted)
                    {
                        deepUninitAttempted = true;
                        try
                        {
                            deepUninit();
                        }
                        catch
                        {
                            // Best-effort cleanup only.
                        }
                    }
                }

                if (tcInitialized && uninit is not null)
                {
                    try
                    {
                        InvokeTcUninit(uninit);
                    }
                    catch
                    {
                        // Best-effort cleanup only.
                    }
                }
            }
            finally
            {
                if (!deepUnsafeFuncProbeAttempted)
                {
                    DeepModule.Dispose();
                    TcModule.Dispose();
                }

                Directory.SetCurrentDirectory(previousDirectory);
            }
        }
    }

    private sealed class HiddenMessageWindow : IDisposable
    {
        private readonly ManualResetEventSlim ready = new(false);
        private readonly Thread thread;
        private uint threadId;
        private IntPtr handle;
        private string error = string.Empty;
        private bool disposed;

        private HiddenMessageWindow()
        {
            thread = new Thread(Run)
            {
                IsBackground = true,
                Name = "TdxDeepMessageWindow",
            };
            thread.SetApartmentState(ApartmentState.STA);
        }

        public IntPtr Handle => handle;

        public string Error => error;

        public static HiddenMessageWindow Start()
        {
            var window = new HiddenMessageWindow();
            window.thread.Start();
            if (!window.ready.Wait(TimeSpan.FromSeconds(3)) && string.IsNullOrWhiteSpace(window.error))
            {
                window.error = "timed out while creating hidden message window";
            }

            return window;
        }

        private void Run()
        {
            threadId = NativeMethods.GetCurrentThreadId();
            try
            {
                handle = NativeMethods.CreateWindowExW(
                    0,
                    "STATIC",
                    "TdxL2HelperDeepWindow",
                    0,
                    0,
                    0,
                    1,
                    1,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero);
                if (handle == IntPtr.Zero)
                {
                    error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
                }
            }
            catch (Exception createError)
            {
                error = $"{createError.GetType().Name}: {createError.Message}";
            }
            finally
            {
                ready.Set();
            }

            while (NativeMethods.GetMessageW(out var message, IntPtr.Zero, 0, 0) > 0)
            {
                NativeMethods.TranslateMessage(ref message);
                NativeMethods.DispatchMessageW(ref message);
            }

            if (handle != IntPtr.Zero)
            {
                NativeMethods.DestroyWindow(handle);
                handle = IntPtr.Zero;
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }

            disposed = true;
            if (threadId != 0)
            {
                NativeMethods.PostThreadMessageW(threadId, NativeMethods.WM_QUIT, IntPtr.Zero, IntPtr.Zero);
            }

            if (thread.IsAlive)
            {
                thread.Join(1000);
            }
        }
    }

    private sealed class LoadedModule : IDisposable
    {
        internal LoadedModule(ModuleReport report, IntPtr handle, Dictionary<string, IntPtr> exports)
        {
            Report = report;
            Handle = handle;
            Exports = exports;
        }

        public ModuleReport Report { get; }

        public IntPtr Handle { get; }

        public Dictionary<string, IntPtr> Exports { get; }

        public void Dispose()
        {
            if (Handle != IntPtr.Zero)
            {
                NativeMethods.FreeLibrary(Handle);
            }
        }

        public static LoadedModule Missing(string name, string path)
        {
            return new LoadedModule(
                new ModuleReport
                {
                    Name = name,
                    Path = path,
                    Exists = false,
                    Error = "missing_file",
                },
                IntPtr.Zero,
                new Dictionary<string, IntPtr>(StringComparer.Ordinal));
        }
    }

    private static LoadedModule LoadModule(string name, string path, IReadOnlyList<string> exportNames)
    {
        if (!File.Exists(path))
        {
            return LoadedModule.Missing(name, path);
        }

        var report = new ModuleReport
        {
            Name = name,
            Path = path,
            Exists = true,
            FileArchitecture = ReadPeArchitecture(path),
        };

        const uint loadWithAlteredSearchPath = 0x00000008;
        var handle = NativeMethods.LoadLibraryExW(path, IntPtr.Zero, loadWithAlteredSearchPath);
        if (handle == IntPtr.Zero)
        {
            report.Error = new Win32Exception(Marshal.GetLastWin32Error()).Message;
            return new LoadedModule(report, IntPtr.Zero, new Dictionary<string, IntPtr>(StringComparer.Ordinal));
        }

        report.Loaded = true;
        report.ModuleHandle = ToHex(handle);

        var exports = new Dictionary<string, IntPtr>(StringComparer.Ordinal);
        foreach (var exportName in exportNames)
        {
            var exportAddress = NativeMethods.GetProcAddress(handle, exportName);
            exports[exportName] = exportAddress;
            report.Exports.Add(
                new ExportReport
                {
                    Name = exportName,
                    Resolved = exportAddress != IntPtr.Zero,
                    Address = exportAddress == IntPtr.Zero ? string.Empty : ToHex(exportAddress),
                });
        }

        return new LoadedModule(report, handle, exports);
    }
}

internal sealed class SelfHostRuntimeReport
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

    [JsonPropertyName("deepPath")]
    public string DeepPath { get; init; } = string.Empty;

    [JsonPropertyName("bufferSize")]
    public int BufferSize { get; init; }

    [JsonPropertyName("heartbeatIntervalMs")]
    public int HeartbeatIntervalMs { get; init; }

    [JsonPropertyName("sampleCount")]
    public int SampleCount { get; init; }

    [JsonPropertyName("runtimeLayout")]
    public RuntimeLayoutReport RuntimeLayout { get; set; } = new();

    [JsonPropertyName("initArgs")]
    public TcInitArgsSnapshot InitArgs { get; init; } = new();

    [JsonPropertyName("probeLoginState")]
    public bool ProbeLoginState { get; init; }

    [JsonPropertyName("loginRequest")]
    public TcLoginRequestSnapshot? LoginRequest { get; init; }

    [JsonPropertyName("setL2Args")]
    public TcSetL2ArgsSnapshot SetL2Args { get; init; } = new();

    [JsonPropertyName("modules")]
    public List<ModuleReport> Modules { get; init; } = new();

    [JsonPropertyName("initResult")]
    public TcInitCallReport? InitResult { get; set; }

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

    [JsonPropertyName("setL2Result")]
    public TcSetL2UserInfoCallReport? SetL2Result { get; set; }

    [JsonPropertyName("initialGetL2Info")]
    public TcGetL2InfoCallReport? InitialGetL2Info { get; set; }

    [JsonPropertyName("deepInit")]
    public SelfHostDeepInitReport? DeepInit { get; set; }

    [JsonPropertyName("deepData")]
    public SelfHostDeepDataSnapshot? DeepData { get; set; }

    [JsonPropertyName("heartbeatSamples")]
    public List<SelfHostHeartbeatSample> HeartbeatSamples { get; init; } = new();

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;

    [JsonPropertyName("notes")]
    public List<string> Notes { get; init; } = new();
}

internal sealed class SelfHostHeartbeatSample
{
    [JsonPropertyName("timestamp")]
    public DateTimeOffset Timestamp { get; init; }

    [JsonPropertyName("sampleIndex")]
    public int SampleIndex { get; init; }

    [JsonPropertyName("getL2Info")]
    public TcGetL2InfoCallReport? GetL2Info { get; init; }

    [JsonPropertyName("deepData")]
    public SelfHostDeepDataSnapshot? DeepData { get; init; }
}

internal sealed class SelfHostDeepInitReport
{
    [JsonPropertyName("registerResult")]
    public DeepCallReport? RegisterResult { get; init; }

    [JsonPropertyName("startResult")]
    public DeepCallReport? StartResult { get; init; }

    [JsonPropertyName("funcProbeResults")]
    public List<DeepCallReport> FuncProbeResults { get; init; } = new();

    [JsonPropertyName("state")]
    public DeepStateSnapshot State { get; init; } = new();
}

internal sealed class SelfHostDeepDataSnapshot
{
    [JsonPropertyName("state")]
    public DeepStateSnapshot State { get; init; } = new();

    [JsonPropertyName("callbacks")]
    public List<DeepCallbackSample> Callbacks { get; init; } = new();
}

internal sealed class DeepCallReport
{
    [JsonPropertyName("invoked")]
    public bool Invoked { get; set; }

    [JsonPropertyName("function")]
    public string Function { get; init; } = string.Empty;

    [JsonPropertyName("signatureAssumption")]
    public string SignatureAssumption { get; init; } = string.Empty;

    [JsonPropertyName("skipped")]
    public bool Skipped { get; set; }

    [JsonPropertyName("skipReason")]
    public string SkipReason { get; set; } = string.Empty;

    [JsonPropertyName("elapsedMs")]
    public int ElapsedMs { get; set; }

    [JsonPropertyName("returnValue")]
    public int ReturnValue { get; set; }

    [JsonPropertyName("win32LastError")]
    public int Win32LastError { get; set; }

    [JsonPropertyName("details")]
    public string Details { get; set; } = string.Empty;

    [JsonPropertyName("resultHex")]
    public string ResultHex { get; set; } = string.Empty;

    [JsonPropertyName("outputPreview")]
    public NativePointerPreview? OutputPreview { get; set; }

    [JsonPropertyName("errorType")]
    public string ErrorType { get; set; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; set; } = string.Empty;
}

internal sealed class DeepStateSnapshot
{
    [JsonPropertyName("registerSupported")]
    public bool RegisterSupported { get; init; }

    [JsonPropertyName("startSupported")]
    public bool StartSupported { get; init; }

    [JsonPropertyName("setMainWndSupported")]
    public bool SetMainWndSupported { get; init; }

    [JsonPropertyName("uninitSupported")]
    public bool UninitSupported { get; init; }

    [JsonPropertyName("registerAttempted")]
    public bool RegisterAttempted { get; init; }

    [JsonPropertyName("registerSucceeded")]
    public bool RegisterSucceeded { get; init; }

    [JsonPropertyName("startAttempted")]
    public bool StartAttempted { get; init; }

    [JsonPropertyName("startSucceeded")]
    public bool StartSucceeded { get; init; }

    [JsonPropertyName("setMainWndAttempted")]
    public bool SetMainWndAttempted { get; init; }

    [JsonPropertyName("setMainWndSucceeded")]
    public bool SetMainWndSucceeded { get; init; }

    [JsonPropertyName("uninitAttempted")]
    public bool UninitAttempted { get; init; }

    [JsonPropertyName("callbackCount")]
    public int CallbackCount { get; init; }

    [JsonPropertyName("bufferedCallbackCount")]
    public int BufferedCallbackCount { get; init; }

    [JsonPropertyName("lastRegister")]
    public DeepCallReport? LastRegister { get; init; }

    [JsonPropertyName("lastStart")]
    public DeepCallReport? LastStart { get; init; }

    [JsonPropertyName("lastSetMainWnd")]
    public DeepCallReport? LastSetMainWnd { get; init; }

    [JsonPropertyName("lastCallback")]
    public DeepCallbackSample? LastCallback { get; init; }
}

internal sealed class DeepCallbackSample
{
    [JsonPropertyName("sequence")]
    public int Sequence { get; init; }

    [JsonPropertyName("timestamp")]
    public DateTimeOffset Timestamp { get; init; }

    [JsonPropertyName("threadId")]
    public int ThreadId { get; init; }

    [JsonPropertyName("arg1")]
    public string Arg1 { get; init; } = string.Empty;

    [JsonPropertyName("arg2")]
    public uint Arg2 { get; init; }

    [JsonPropertyName("arg3")]
    public string Arg3 { get; init; } = string.Empty;

    [JsonPropertyName("arg4")]
    public string Arg4 { get; init; } = string.Empty;

    [JsonPropertyName("arg1Preview")]
    public NativePointerPreview Arg1Preview { get; init; } = new();

    [JsonPropertyName("arg4Preview")]
    public NativePointerPreview Arg4Preview { get; init; } = new();
}

internal sealed class NativePointerPreview
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

    [JsonPropertyName("uint32")]
    public List<uint> UInt32 { get; init; } = new();

    [JsonPropertyName("error")]
    public string Error { get; init; } = string.Empty;

    public static NativePointerPreview Empty(string error)
    {
        return new NativePointerPreview
        {
            Error = error,
        };
    }

    public static NativePointerPreview FromBytes(byte[] data)
    {
        var scalarCount = Math.Min(data.Length / 4, 8);
        var values = new List<uint>(scalarCount);
        for (var index = 0; index < scalarCount; index++)
        {
            values.Add(BitConverter.ToUInt32(data, index * 4));
        }

        return new NativePointerPreview
        {
            Size = data.Length,
            NonZeroBytes = data.Count(value => value != 0),
            HexPrefix = FormatHexPrefix(data, 64),
            AnsiPreview = PreviewText(data, Encoding.ASCII),
            Gb18030Preview = PreviewText(data, Encoding.GetEncoding("GB18030")),
            UInt32 = values,
        };
    }

    private static string FormatHexPrefix(byte[] data, int limit)
    {
        return string.Join(" ", data.Take(limit).Select(value => value.ToString("X2")));
    }

    private static string PreviewText(byte[] data, Encoding encoding)
    {
        var slice = data.SkipWhile(value => value == 0).TakeWhile(value => value != 0).Take(64).ToArray();
        if (slice.Length == 0)
        {
            return string.Empty;
        }

        var text = encoding.GetString(slice);
        return new string(text.Select(character => char.IsControl(character) ? ' ' : character).ToArray()).Trim();
    }
}
