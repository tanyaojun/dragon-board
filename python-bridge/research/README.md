# TDX 7719 Research

本目录只放 `7719 / 真 L2` 的隔离探测工具。这里的目标不是单纯记录探索结果，而是服务《通达信 L2 十档实时行情重构计划》的最终验收：找到真实 L2 鉴权 / 权限同步入口，并验证十档盘口和分笔数据可以返回。

边界：

- 不接入 `python-bridge/main.py`
- 不影响当前 `7709 + WebSocket` 生产链路
- 不修改通达信客户端文件
- 不注入官方客户端进程
- 不恢复 `pytdx` 依赖
- 不把 `7709 / 五档` 当成 L2 十档最终验收结果

当前默认分析客户端：

```text
D:\APP_SOFT\TDX
```

本机还存在其他通达信目录，例如 `D:\TDX_PLUS`。除非文档明确说明，第二阶段所有 `tdxw.exe / TDXDeep.dll / nacomte.dat / nbcomte.dat` 结论均指 `D:\APP_SOFT\TDX`。

## 当前脚本

```bash
python python-bridge/research/tdx_l2_probe.py --timeout 8
```

官方客户端 live 连接发现：

```bash
python python-bridge/research/tdx_live_route_probe.py --ports 7719,7712,7615 --output python-bridge/research/out/APP_SOFT_TDX/tdx_live_route_probe.json
```

静态只读扫描：

```powershell
powershell -ExecutionPolicy Bypass -File python-bridge/research/inspect_tdx_l2_artifacts.ps1 -TdxRoot D:\APP_SOFT\TDX -OutputDir python-bridge\research\out\APP_SOFT_TDX
```

PE import 表扫描：

```bash
python python-bridge/research/pe_imports.py D:\APP_SOFT\TDX\TDXDeep.dll D:\APP_SOFT\TDX\tdxw.exe --output python-bridge/research/out/APP_SOFT_TDX/pe_imports.json
```

PE export 表扫描：

```bash
python python-bridge/research/pe_exports.py D:\APP_SOFT\TDX\tc.dll D:\APP_SOFT\TDX\TDXDeep.dll D:\APP_SOFT\TDX\tpbus.dll D:\APP_SOFT\TDX\TDXRun.dll --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_candidate_modules_exports.json
```

带文件偏移的关键词上下文扫描：

```bash
python python-bridge/research/tdx_l2_string_context.py D:\APP_SOFT\TDX\tdxw.exe D:\APP_SOFT\TDX\TDXDeep.dll --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_string_context.json
```

L2 鉴权相关字符串 xref 扫描：

```bash
python python-bridge/research/tdx_l2_xref_probe.py --tdx-root D:\APP_SOFT\TDX --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_xref_probe.json
```

L2 鉴权相关全局对象 xref 扫描：

```bash
python python-bridge/research/tdx_l2_object_xref_probe.py --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_object_xref_probe.json
```

TP/TPL2 鉴权检查上下文扫描：

```bash
python python-bridge/research/tdx_l2_tpcheck_probe.py --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_tpcheck_probe.json
```

该脚本只做静态分析，用于定位：

- `tdxw.exe` 中 `TC_SetL2UserInfo / TC_GetL2Info` 等字符串被哪些代码引用。
- `GetProcAddress` 风格解析后的全局函数指针槽。
- 函数指针槽后续被调用的位置。
- `TDXDeep.dll` 导出函数在 `tdxw.exe` 中的解析槽和调用点。

可指定节点：

```bash
python python-bridge/research/tdx_l2_probe.py --servers 106.52.50.92:7719,124.71.222.84:7719
```

可指定样本股票：

```bash
python python-bridge/research/tdx_l2_probe.py --symbols 000001,600000
```

可输出 JSON 报告：

```bash
python python-bridge/research/tdx_l2_probe.py --output .tmp/tdx_l2_probe.json
```

原始命令握手/超时行为复核：

```bash
python python-bridge/research/tdx_l2_raw_command_probe.py --servers 203.195.161.155:7719,124.71.154.218:7712,47.106.34.194:7615 --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_raw_command_probe_live_routes.json
```

TC L2 入口静态探针：

```bash
python python-bridge/research/tc_l2_entry_probe.py --output python-bridge/research/out/APP_SOFT_TDX/tc_l2_entry_probe_static.json
```

受保护的加载检查：

```bash
python python-bridge/research/tc_l2_entry_probe.py --load-only --output python-bridge/research/out/APP_SOFT_TDX/tc_l2_entry_probe_load_only.json
```

当前本机 Python 是 64 位，`D:\APP_SOFT\TDX` 关键 DLL 是 32 位，因此 `--load-only` 会返回 `bitness_mismatch`，不会尝试加载或调用 DLL。

64 位 `D:\TDX_PLUS` 探测：

```bash
python python-bridge/research/tc_l2_entry_probe.py --tdx-root D:\TDX_PLUS --output python-bridge/research/out/TDX_PLUS/tc_l2_entry_probe_static.json
python python-bridge/research/tc_l2_entry_probe.py --tdx-root D:\TDX_PLUS --load-only --output python-bridge/research/out/TDX_PLUS/tc_l2_entry_probe_load_only.json
python python-bridge/research/tdx_deep_load_probe.py --tdx-root D:\TDX_PLUS --output python-bridge/research/out/TDX_PLUS/tdx_deep_load_probe.json
```

当前发现：`D:\TDX_PLUS\TDXDeep.dll` 是 64 位，可以被当前 Python 加载并解析导出；但 `D:\TDX_PLUS\NewTc\tc.dll` 仍是 32 位，不能被当前 64 位 Python 加载。

独立 `x86 helper` 构建与运行：

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe inspect --tdx-root D:\APP_SOFT\TDX
```

输出样本：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_x86_helper_inspect.json
```

## 当前结论

2026-04-26 探测结果：

- `218.6.170.47:7709` 可返回标准行情与五档字段。
- `106.52.50.92:7719` TCP/连接可达，但标准行情命令为空。
- `124.71.222.84:7719` TCP/连接可达，但标准行情命令为空。
- 官方客户端本轮重启后，live 连接还出现 `203.195.161.155:7719`、`124.71.154.218:7712`、`47.106.34.194:7615`。
- 对这组 live 节点做只读复核后，`203.195.161.155:7719` 仍然是“setup 可达、标准业务命令超时”；`124.71.154.218:7712` 对标准 setup 直接超时；`47.106.34.194:7615` 对标准 setup 直接 reset。
- `x86 helper` 已完成最小动态验证：发布出的 `win-x86` 可执行文件实际运行在 `X86 / 32-bit` 进程中，并能真实 `LoadLibraryExW + GetProcAddress` 解析 `tc.dll / TDXDeep.dll` 的目标导出函数。

因此当前阻塞点仍判断为 `7719` 业务协议分支不兼容。

补充判断：

- `7719` 仍是当前最接近真实 L2 的数据端口。
- `7712` 更像客户端内部另一类专用通道，不兼容公开标准行情 setup。
- `7615` 与 `TP/page/icfqs` 内容链路高度相关，不是十档入口。

当前环境下 `pktmon` 抓包需要管理员权限；本机会返回“拒绝访问”。因此本轮先采用 `tdx_live_route_probe.py` 固化 live 路由，再结合只读探针继续推进。

当前已跨过的工程门槛：

- 不再停留在“64 位 Python 无法直调 32 位 DLL”的纯分析阶段。
- `tools/TdxL2Helper` 已把 32 位进程、DLL 实际加载、导出解析三件事跑通。
- 下一步可以进入首批低风险动态验证：`LoadLibrary/GetProcAddress -> TC_Init_Environ -> TC_GetL2Info`。

## 当前攻关重点

下一步优先围绕真实 L2 鉴权入口推进：

- `tpbus.dll`：登录、SSO、QSID、Token、RightInfo 等权限字段来源。
- `tc.dll`：`TC_SetL2UserInfo / TC_GetL2Info` 权限同步与读取入口。
- `TDXDeep.dll`：`TdxDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 深度行情入口。
- `QSTPLevel2_SepcComte / nacomte.dat / nbcomte.dat`：L2 主站和 QSTP 链路材料。
- `tools/TdxL2Helper`：后续官方 DLL 动态验证与 bridge 接入的 32 位代理进程。

只有当隔离验证能证明 L2 权限态可建立、可读取，并能驱动 `7719 / TDXDeep / QSTP` 返回真实十档或分笔数据后，才进入生产 bridge 接入设计。

当前动态验证顺序建议：

1. `LoadLibraryExW / GetProcAddress`
2. `TC_Init_Environ`
3. `TC_GetL2Info`
4. 仅在确认权限来源后，再进入 `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo`
5. 最后才是 `TC_SetL2UserInfo`
6. `TdxDeep_StartInit` 放在权限态之后

## 2026-04-26 xref 新增结论

新增输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_xref_probe.json
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_callsite_probe.json
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_object_xref_probe.json
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_tpcheck_probe.json
```

本轮新增事实：

- `tdxw.exe` 会动态解析 `tc.dll` 的 `TC_SetL2UserInfo`，解析后写入全局函数指针槽 `VA 0x01227E20`。
- `TC_SetL2UserInfo` 槽位在 `tdxw.exe` 中发现一个明确间接调用点：`RVA 0x003221D1`，调用后清栈 `0x0C`，继续支持 3 参数结论。
- `tdxw.exe` 会动态解析 `TDXDeep.dll` 的 `TdxDeep_StartInit`，槽位为 `VA 0x012285C8`。
- `TdxDeep_StartInit` 的明确调用点在 `tdxw.exe RVA 0x00325731`，调用后清栈 `0x1C`，静态上约为 7 参数。
- `TdxDeep_RegisterCallBackFunc` 槽位为 `VA 0x012285CC`，调用点 `RVA 0x00325759`，调用后清栈 `0x0C`，静态上约为 3 参数。
- `TC_SetL2UserInfo` 调用点前可见券商标识 `"CITICS"` 与格式串 `"%s#CFV"`，并先构造本地缓冲，再进入 3 参数调用。
- `TdxDeep_StartInit` 调用点前可见 `connect.cfg`、一个 byte 标志和若干 `.data` 全局对象，当前更像深度行情运行时初始化上下文，而不是直接的账号密码入口。
- `0x011D4FEC` 这个全局对象同时出现在 `SSOMode 13/15` 的 `L2ZH/L2Right/QSID` JSON 构造点、`##L2ZH##` 模板替换点，以及 `CITICS/%s#CFV -> TC_SetL2UserInfo` 调用点。
- `TP_Check_GTJAL2` 函数体已锚定在 `tdxw.exe RVA 0x00511F10`，唯一直接调用者为 `RVA 0x00383BE5`。
- `TP_Check_GTJAL2` 函数体附近集中出现 `Start TP_Check_GTJAL2`、`TP_Check_GTJAL2 return...`、`RightInfo`、`L2ZH`、`Local.GetLoginRetInfo`、`TdxW_GetLoginRetInfo`、`TPL2_Check` 和 `TPL2_Check Sync OK!`。

当前推断：

- `TC_SetL2UserInfo` 已从“导出函数”进一步推进到“官方客户端中存在真实调用点”。
- `TC_SetL2UserInfo` 的 3 个参数仍未确认，但调用点附近存在本地字符串构造和格式化行为，下一步应围绕 `tdxw.exe RVA 0x003221D1` 的上游局部变量来源继续下探。
- `TdxDeep_StartInit` 的 7 参数调用点说明深度行情 DLL 初始化不是无参开关，后续需要确认这些参数中是否包含窗口句柄、路径、回调、权限态或主站配置。
- 当前更偏向的判断是：`TC_SetL2UserInfo` 更接近 L2 权限同步入口；`TdxDeep_StartInit` 更接近在权限态已经具备后的深度行情引擎初始化入口。
- 当前最有价值的链路收敛为：`SSO/JSSO.applysso` 组装 `L2ZH/L2Right/QSID` 权限 JSON，再进入 `TP_Check_GTJAL2 / TPL2_Check / Local.GetLoginRetInfo` 权限同步检查，随后经由同一类 MFC 字符串对象或 helper 流向 `TC_SetL2UserInfo` 的 3 参数同步入口。

## 2026-04-26 LoginProcess / applysso 再收敛

新增输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tpbus_loginprocess_xref_probe.json
python-bridge/research/out/APP_SOFT_TDX/tpbus_applysso_xref_probe.json
python-bridge/research/out/APP_SOFT_TDX/tdxw_applysso_xref_probe.json
```

本轮新增事实：

- `tpbus.dll` 的 `LoginProcess.cpp` 相关字符串锚点已经不只是“散点命中”，而是能压到 3 个明确内部函数层级：
  - `sub_100EF760`：命中固定 `SSOMode=2`、`Token`、`InputQSID`、`InputZHLB=340` 这一支。
  - `sub_100F028D`：命中 `Token`、`AuthInfo`、`m_nSSOMode`、`InputQSID`、`YYB` 这一支。
  - `sub_100F0C20`：是上面两支的共享分发函数；其内部在 `0x100F0EC5` 调 `sub_100EF760`，在 `0x100F0EF1` 调 `sub_100F028D`。
- `sub_100F0C20` 目前发现两个明确直接调用点：`tpbus.dll RVA 0x00107B08` 和 `0x001091CD`。这说明在 `tpbus.dll` 侧，真正共享的“请求组装入口”已经可以收敛到 `sub_100F0C20`，而不是继续把注意力放在 `tc.dll` 导出上。
- `sub_100F0F25` 会处理 `SSOMode` 配置读取和缓存，命中 `SSOMode=%d cfgName=%s` 日志串，并在 `0x00105037` 被调用；它更像 `m_nSSOMode` 的配置 helper，而不是最终请求入口。
- `tdxw.exe RVA 0x00510740` 是 `SSO.applysso / JSSO.applysso` 那条 `TdxWL2` 权限 JSON 组装 worker：
  - 同函数体内可见 `SSOMode 13/15`、`L2ZH`、`L2Right`、`TdxWL2`、`SSO.applysso`、`JSSO.applysso`。
  - 该函数比之前“只知道字符串在附近”更进一步，已经能作为一个明确的内部函数体来讨论。
- `tdxw.exe RVA 0x007012B0` 是更窄的 `ReqLscjmxTdxSSO / tc.JSSO:applysso|%s` worker：
  - 同函数体内可见 `tc.JSSO:applysso|%s`。
  - 同函数体内可见 `[{"SSOMode":"396","Token":"%s_%s","invalidTime":"%d"}]`。
  - 在 `0x007015C1` 调用前格式化 `ReqLscjmxTdxSSO,TQLName=%s,TQLParam=%s`。
  - 在 `0x0070163E` 记录 `ReqLscjmxTdxSSO,ans=%s`。

当前更精确的判断：

- 如果讨论的是“登录/SSO 权限字段在谁那里真正成形”，当前最小共享入口应记为：`tpbus.dll sub_100F0C20`。
- 如果讨论的是“L2 专用 applysso / ReqLscjmxTdxSSO 在谁那里真正发起”，当前最小核心 worker 应记为：`tdxw.exe sub_007012B0`。
- 因而当前不宜再笼统说“入口在 `tc.dll`”或“只知道在 `tpbus.dll/LoginProcess.cpp`”。更准确的表述是：

```text
tpbus.dll
  sub_100F0C20
    -> sub_100EF760    (SSOMode=2 / Token / InputQSID)
    -> sub_100F028D    (Token / AuthInfo / m_nSSOMode / InputQSID)

tdxw.exe
  sub_00510740         (SSO/JSSO.applysso + L2ZH/L2Right/TdxWL2)
  sub_007012B0         (tc.JSSO:applysso|%s + ReqLscjmxTdxSSO + SSOMode 396)
```

下一步优先级应调整为：

1. 继续反推 `sub_100F0C20` 两个直接调用点 `0x00107B08 / 0x001091CD` 的上游业务入口，确认哪一支会稳定落到 L2。
2. 继续反推 `sub_007012B0` 的外部调用者参数差异，确认哪些调用分支只是复用 helper，哪些才是真正触发 L2 applysso 的 UI/状态入口。
3. 只有在这两处最小 worker 的上游入口再缩一层后，才进入 `TC_SetL2UserInfo` 三参数和 `TdxDeep_StartInit` 七参数的动态验证。

## 2026-04-28 live auth probe 补充

新增只读动态探针：

```bash
python python-bridge/research/tdx_live_auth_state_probe.py --sample-count 20 --interval-ms 500 --diff-only
```

当前用途：

- 不注入、不加载 DLL，只读 `tdxw.exe` 内存和 TCP 连接
- 连续采样 `L2ZH / L2Right / SysSource`
- 连续采样 `TP_Check_GTJAL2` 直接调用者附近的 gate/mirror dword
- 把本地持久化材料一起带上，方便和 live 状态对照

当前已接入的关键 live 字段：

- `0x011D4FEC` -> `L2ZH` (`CString*`)
- `0x011BEE80` -> `L2Right` (inline buffer)
- `0x011BED6C` -> `SysSource` (inline buffer)
- `0x011CE73C / 0x011C8DF4` -> `loginret_seq_mirror_*`
- `0x00E7F17C / 0x00E7F259 / 0x00E7F07E` -> `TP_Check / LoginRet / SSO` gate dword

2026-04-28 当前 idle 实测值：

- `L2ZH = tdxPC1891093`
- `L2Right = C`
- `SysSource = tdxlevel`
- `loginret_seq_mirror_a = 1`
- `loginret_seq_mirror_b = 1`
- `tpcheck_mode_gate = 0`
- `loginret_zero_gate = 0`
- `sso_switch_gate = 0`

当前判断：

- 这条探针比继续堆 `TC_Login / TC_Login2` profile 更有价值，因为它能直接回答“手工触发登录/刷新时，到底哪些 live 状态在动”。
- 如果这些 gate/mirror 在手工登录时依然完全不动，下一步就该继续追 `tpbus.dll sub_100F0C20` 的上游业务入口，而不是继续在 helper 里堆四参数组合。

## 2026-04-28 TdxWL2 / TDXDeep 新结论

新增 live 进程字符串扫描：

```bash
python python-bridge/research/tdx_live_memory_string_probe.py --max-mb 512 --limit-per-keyword 8 --output .tmp/tdx_live_memory_string_probe_2026-04-28.json
```

新增 TDXDeep 槽位使用反汇编：

```bash
python python-bridge/research/tdx_deep_call_uses_probe.py --slots TdxDeep_Func,TdxDeep_Data,TdxDeep_SetMainWnd --before 112 --after 112 --output .tmp/tdx_deep_call_uses_probe_2026-04-28.json
```

本轮关键事实：

- live `tdxw.exe` 堆里已发现真实 `TdxWL2` applysso 返回 JSON。
- 返回 JSON 包含 `RightInfo=C / L2ZH / Code=0 / DataName=TdxWL2`。
- 同一内存区还能看到 `SSOMode=13 / SysSource=tdxlevel / Reserve.L2ZH / Reserve.L2Right` 请求 JSON。
- helper 用这些 live JSON 派生出 `tdxwl2-*` setl2 profile 后，`TC_SetL2UserInfo` 仍然只是返回 `1`，没有让 `RightInfo / L2Info` 非空。

因此：

- `TC_SetL2UserInfo` 直接喂 live JSON 的路线已判为无效。
- `TdxDeep_StartInit` 的旧崩溃原因已经收敛到实参形态，尤其是第 6 参数不能传空。
- 复刻官方第 6 参数的 `扩展市场行情` 静态描述缓冲后，helper 内 `TdxDeep_StartInit` 已能稳定返回 `1`。

新的剩余 blocker：

- `TdxDeep_StartInit` 成功后还没有 callback。
- `TdxDeep_Func` 静态上是 10 参数，官方调用后清栈 `0x28`。
- 空上下文调用 `TdxDeep_Func` 会阻塞，因此 helper 侧已把它单独放到 `--unsafe-deep-func-probe`，不随 `--unsafe-deep-start` 自动执行。
