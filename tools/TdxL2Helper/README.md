# TdxL2Helper

最小 `x86 helper`，目标只有两件事：

1. 确认我们能从一个 32 位进程加载 `D:\APP_SOFT\TDX` 下的官方 DLL。
2. 确认 `tc.dll / TDXDeep.dll` 的关键导出函数能被真实解析。

当前版本支持两类低风险动作：

- `LoadLibraryExW`
- `GetProcAddress`
- `TC_Init_Environ -> TC_GetL2Info -> TC_Uninit` 基线探针
- `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo` 缓存参数矩阵探针
- `host-runtime --event-stream` 长驻 `x86` 宿主事件流
- JSON 报告输出

## 为什么单独做 helper

当前主工程运行在 64 位环境，而通达信关键 DLL 观测为 32 位。  
64 位 Python/Node 不能直接加载 32 位 DLL，所以必须先把“32 位加载能力”拆到独立进程里。

## 构建

建议先产出独立 `win-x86` 可执行文件：

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true
```

输出目录默认类似：

```text
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\
```

## 运行

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe inspect --tdx-root D:\APP_SOFT\TDX
```

同步宿主运行时布局：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe sync-runtime-layout --tdx-root D:\APP_SOFT\TDX
```

执行 `TC_Init_Environ / TC_GetL2Info` 基线探针：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe probe-tc-baseline --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout
```

执行缓存登录参数矩阵探针：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe probe-tc-login-matrix --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout
```

执行长驻宿主，并让 helper 自动选择当前优先级最高的缓存登录 profile：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe host-runtime --tdx-root D:\APP_SOFT\TDX --event-stream --probe-login-state --login-profile auto
```

执行实验性只读内存扫描，查找正在运行的 `tdxw.exe` 中疑似十档深度结构：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe read-l2-depth --tdx-root D:\APP_SOFT\TDX --scan
```

持续读取已扫描到的候选地址：

```powershell
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe read-l2-depth --tdx-root D:\APP_SOFT\TDX --monitor --interval-ms 500 --output l2-depth.jsonl
```

说明：

- `read-l2-depth` 是隔离只读探针，只读取运行中 `tdxw.exe` 的进程内存，不注入、不写入目标进程。
- 扫描结果是“疑似深度结构候选”，需要人工和官方客户端画面对照验证。
- 该入口不代表 `7719 / 官方 L2 十档 / 官方逐笔` 已经接入，也不能直接接入 `python-bridge/main.py` 的生产默认路径。
- 地址缓存写在 helper 运行目录下的 `.tdx_l2_cache/`，属于本地探针状态，不提交。

如需显式尝试 `TdxDeep_StartInit` 探针，再额外加：

```powershell
--unsafe-deep-start
```

当前 `TdxDeep_StartInit` 已按官方调用点复刻 `root / T0002 / connect.cfg / 扩展市场行情` 参数形态，实机可稳定返回 `1`。默认仍不自动调用它，原因是启动后还没有完成 `TdxDeep_Func / TdxDeep_Data` 的订阅和回流闭环。

`TdxDeep_Func` 探针被单独放在更危险的开关后面：

```powershell
--unsafe-deep-start --unsafe-deep-func-probe
```

当前空上下文 `TdxDeep_Func` 会阻塞，不建议在生产 bridge 路径启用。

输出 JSON 重点看：

- `processArchitecture` 是否为 `X86`
- `pointerSizeBits` 是否为 `32`
- `modules[].loaded`
- `modules[].exports[].resolved`

`probe-tc-baseline` 额外重点看：

- `runtimeLayout.ok`
- `initResult.returnValue`
- `postInitGetL2Info.returnValue`
- `postInitGetL2Info.arg1 / arg2`

`probe-tc-login-matrix` 额外重点看：

- `materials.entries`
- `attempts[].profileName`
- `attempts[].function`
- `attempts[].signalScore`
- `attempts[].postGetLoginRet.arg1`
- `attempts[].postGetRightInfo`
- `attempts[].postGetL2Info`

说明：

- `loginResult.returnValue = 0` 不等于已经进入合法 L2 权限态。
- 当前更有价值的信号是：`TC_GetLoginRet / TC_GetRightInfo / TC_GetL2Info` 的 buffer 是否相对 pre-state 发生变化。
- 登录矩阵探针现在按“一次候选组合一个子进程”执行，避免单组原生调用 `0xC0000005` 时把整轮探针打崩。

## 运行时布局

`tc.dll` 不是只依赖 `--tdx-root`。

当前已经确认：`TC_Init_Environ` 会读取 **helper 可执行文件目录** 下的宿主资源，包括：

- `etrade.xmb`
- `TcOem.xmb`
- `TCPlugins\*.dll`
- `Users\Profile\`

只把当前目录切到 `D:\APP_SOFT\TDX` 还不够。如果 helper 自身目录里没有这套布局，`tc.dll` 会在初始化阶段报：

- `TcComm部件不存在！`
- `TcGina部件不存在！`
- `TcGUIUtility部件不存在！`

因此基线探针应优先执行 `sync-runtime-layout`，或者直接给 `probe-tc-baseline` 传 `--sync-runtime-layout`。

## 当前状态

截至 2026-04-26，helper 已完成：

1. `win-x86` 独立宿主加载 `tc.dll / TDXDeep.dll`
2. `host-runtime --event-stream` NDJSON 心跳流
3. `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo` 调用面
4. 缓存登录材料矩阵探针
5. `--login-profile <name|auto>` 自动把缓存 profile 接进 `host-runtime`

当前自动优先顺序：

1. `tdxid-token-userpuid-oid`
2. `tdxid-token-connectqsid-oid`
3. `tdxid-token-jymainqsid-oid`
4. `tdxid-token-oid-reguid`
5. `tdxid-token-reguid-empty`

## 下一步

当前更高优先级的后续工作：

1. 继续收缩 `服务器分组未配置。` 对应的券商/QSID/分组字段
2. 找到能让 `TC_GetRightInfo / TC_GetL2Info` 发生非空变化的登录 profile
3. 在确认合法权限态后再推进 `TC_SetL2UserInfo`
4. 最后再推进 `TdxDeep_StartInit / TdxDeep_Data`

补充说明：

- helper 现在会额外读取 `connect.cfg` 里的 `QSID`，并把它作为 `ConnectQSID` 材料纳入登录矩阵。
- helper 现在也会读取 `connect.cfg` 里的 `WTPreNAME / JyLogin_Style / JyLogin / SpecIPLogin`，其中 `WTPreNAME` 仅作为低置信度交易端显示名/券商名轴保留，不当作已确认 `YYBID`。
- `JYMainQSID` 与 `ConnectQSID` 会被视为两条不同假设轴：前者更像券商/分组名，后者更像 `InputQSID` 候选。
- `usercomm.ini:SAVEZH` 当前已确认不是可直接复用的 `L2ZH` 业务值；helper 不再把它镜像成 `L2ZH`。
- helper 现在会优先尝试从运行中的 `tdxw.exe` 只读加载 live `L2ZH / L2Right / SysSource`：
  - `L2ZH`：`0x011D4FEC`，按 `CString*` 读取
  - `L2Right`：`0x011BEE80`，当前 live 形态是原位字节缓冲
  - `SysSource`：`0x011BED6C`，当前 live 形态是原位字节缓冲，实测值为 `tdxlevel`
- 如果当前 TDX 根目录下没有匹配的 `tdxw.exe` 进程，`L2ZH` 轴会自动缺席；这时仍可用 live probe 或手工 `--setl2-arg*` 注入。
- 登录矩阵新增了更贴近 `InputQSID + YYB/LoginType` 假设的 profile，例如：
  - `tdxid-token-connectqsid-jymainqsid`
  - `tdxid-session-connectqsid-jymainqsid`
  - `tdxid-token-connectqsid-lastlogintype`
  - `tdxid-token-connectqsid-wtprename`
- 2026-04-28 实机复核结果：以上新 profile 仍未打出 `RightInfo / L2Info` 非空变化；当前观测仍以 `0xC0000005` 和 `SEHException` 为主。
- `probe-tc-login-matrix` 报告新增 `signalSummaries`，会把重复出现的 `loginRet / RightInfo / L2Info` 信号聚合出来，便于快速识别像 `服务器分组未配置。` 这类高价值返回。
- 2026-04-28 新增 live `TdxWL2` applysso JSON profile 后，`TC_SetL2UserInfo` 仍然只返回 `1`，没有带来 `RightInfo / L2Info` 非空变化；这条直接注入路线已基本判为无效。
- 2026-04-28 `TdxDeep_StartInit` 已从“会崩”推进到“返回 `1`”，但 `TdxDeep_Func / TdxDeep_Data` 的真实调用上下文仍未闭环。
- `host-runtime` 现在会默认输出 `deep_register / deep_start / heartbeat.deepState`；其中 `deep_start` 默认是 `skipped=true`，只有显式加 `--unsafe-deep-start` 才会触发当前的探针。
