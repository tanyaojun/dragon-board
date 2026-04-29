# 通达信 7719 / L2 协议验证记录

更新时间：2026-04-26

## 1. 结论摘要

截至目前，已经能确认的事实是：

- `7719` 确实是通达信客户端实际使用的 `L2` 行情端口之一。
- `mootdx/tdxpy` 当前公开的标准行情命令集不能直接跑通 `7719` 业务数据。
- 当前 bridge 能稳定跑通的是 `7709 + 标准五档 + 本地 WebSocket`。
- `7709 + 标准五档` 只是为了解决 HTTP 旧价问题的过渡可用链路，不是《通达信 L2 十档实时行情重构计划》的最终验收结果。
- 仅靠配置 `L2` 账号、密码或把端口改成 `7719`，不足以解锁真 `L2` 十档。
- `pytdx` 并没有比当前 `mootdx` 更接近解决这条问题。
- 2026-04-26 进入第二阶段后，公开 GitHub/开源搜索仍未发现可直接替代 `mootdx/pytdx` 并打通 A 股 `7719 / 真 L2 十档` 的成熟方案。
- 2026-04-26 带偏移字符串上下文与 PE import 复核后，`TDXDeep.dll / TC_SetL2UserInfo / TC_GetL2Info / TPL2_Check / QSTPLevel2_SepcComte` 的关联性增强，但仍只是协议路径线索，不等于已经拿到 `7719` 真业务包。
- 后续任务的收敛目标必须继续指向真实 L2 鉴权入口：确认 `tpbus.dll / tc.dll / TDXDeep.dll / QSTP` 链路如何完成权限同步，并最终拿到可验证的十档盘口和分笔数据。
- 2026-04-26 xref 下探后，`tdxw.exe` 中已经定位到 `TC_SetL2UserInfo` 的动态解析槽和明确调用点，说明该入口确实被官方客户端调用；同时定位到 `TdxDeep_StartInit` 的动态解析槽和约 7 参数调用点。
- 2026-04-26 `x86 helper` 最小验证已通过：发布出的 `win-x86` 可执行文件真实运行在 `32-bit` 进程中，并能加载 `tc.dll / TDXDeep.dll`、解析 `TC_Init_Environ / TC_GetL2Info / TC_SetL2UserInfo / TdxDeep_StartInit` 等导出。

---

## 2. 已验证事实

### 2.1 官方客户端确实在连 `7719`

本机 `netstat` 与进程核对结果表明：

- `tdxw.exe` 会建立到 `124.71.222.84:7719` 的 `ESTABLISHED` 连接
- 还曾出现 `106.52.50.92:7719` 的连接记录
- 2026-04-26 本轮重启后，`tdxw.exe` 当前 live 连接还出现：
  - `203.195.161.155:7719`
  - `124.71.154.218:7712`
  - `47.106.34.194:7615`

这说明：

- `7719` 不是猜测
- 它确实属于官方客户端正在使用的行情链路
- 官方客户端在同一会话里还会同时挂载额外的 `7712` / `7615` 专用链路

### 2.2 当前 bridge 实际跑在 `7709`

本地 Python bridge 当前稳定连接的是：

- `218.6.170.47:7709`

这条链路已经能稳定返回：

- 实时报价
- 标准五档盘口
- 部分标准分笔数据

因此当前项目里“已可用的实时链路”本质上是：

- `7709 / L1 + 五档`

不是：

- `7719 / 真 L2 十档`

这条 `7709` 链路只能作为过渡生产链路。最初优化目标仍然是 `L2 十档行情 + 分笔`，当前止步于五档的原因是尚未找到可复现的 L2 鉴权 / 权限同步入口。

---

## 3. `7719` 的当前验证结果

### 3.1 `mootdx/tdxpy` 对 `7719` 的表现

当前验证结果一致表明：

- `7719` 可以完成基础 `setup` 握手
- 但握手后标准业务命令拿不到有效数据

具体现象包括：

- `stock_count()` 返回空
- `quotes()` 返回空
- `transaction()` 返回空
- 2026-04-26 的隔离探针再次确认：`106.52.50.92:7719`、`124.71.222.84:7719` 均 TCP 可达，`mootdx` 连接可建立，但标准行情命令仍返回空。
- 2026-04-26 对 live 节点 `203.195.161.155:7719` 复核后，结果仍然相同：TCP 可达，`mootdx` 连接可建立，但 `stock_count / quotes / transaction` 仍为空。
- 对同次 live 会话的 `124.71.154.218:7712` 复核后，TCP 可达，但 `mootdx` 标准连接直接超时。
- 对同次 live 会话的 `47.106.34.194:7615` 复核后，TCP 可达，但标准连接被远端直接 reset。

因此更准确的判断不是“7719 完全不通”，而是：

- TCP 层可达
- 业务协议层不兼容

### 3.2 为什么不能把问题简单理解成“需要 L2 账号密码”

当前已核对过：

- `mootdx`
- `tdxpy`
- `Quotes.factory(...)`
- `TdxHq_API`

都没有找到公开的显式登录接口，例如：

- `login(username, password)`
- `auth(token)`
- `set_l2_account(...)`

所以现在不能把：

- `TDX_L2_USERNAME`
- `TDX_L2_PASSWORD`

接进 bridge，就当作已经补齐了真实 `L2` 登录流程。

---

## 4. 客户端内部线索

### 4.1 `connect.cfg` 不是 L2 主站来源

本机实测：

- [connect.cfg](</d:/APP_SOFT/TDX/connect.cfg>) 的 `[HQHOST]` 里全是 `7709`
- 但客户端实际却连的是 `7719`
- 同一个 [connect.cfg](</d:/APP_SOFT/TDX/connect.cfg>) 里还能找到一组 `7712` 条目，并且 `IPAddress03=124.71.154.218` 与本轮 live 连接一致
- 同一个 [connect.cfg](</d:/APP_SOFT/TDX/connect.cfg>) 里 `TPHost01/02/03=page{1,2,3}.tdx.com.cn:7615`，与本轮 `47.106.34.194:7615` live 连接一致

说明：

- 新版客户端的 L2 运行时主站来源不依赖这份明文配置
- 但 `connect.cfg` 仍暴露了 `7712` 和 `7615` 这两条并行链路的静态入口

### 4.2 当前更像是 `zhb.zip -> nacomte.dat / nbcomte.dat`

已确认文件链路：

- [zhb.zip](</d:/APP_SOFT/TDX/T0002/hq_cache/zhb.zip>)
- [nacomte.dat](</d:/APP_SOFT/TDX/nacomte.dat>)
- [nbcomte.dat](</d:/APP_SOFT/TDX/nbcomte.dat>)

日志 [tdxsys3.log](</d:/APP_SOFT/TDX/T0001/tdxsys3.log>) 的顺序吻合：

1. 获取 `zhb` 成功
2. 更新 `nacomte.dat / nbcomte.dat`
3. 后续切换到 `7719` 主站

补充观察：

- [tdxsys3.log](</d:/APP_SOFT/TDX/T0001/tdxsys3.log>) 在历史片段中多次出现 `203.195.161.155`，说明它不是一次性偶发连接，而是官方客户端真实使用过的 `7719` 主站之一。

### 4.3 `comte.dat` 不是明文站点表

已验证：

- 文件里搜不到真实 IP
- 也搜不到这些 IP 的 packed 形式
- 头部更像二进制编码或加密内容

因此至少可以确认：

- 这不是靠改明文 IP 就能复用的配置

### 4.4 `TDXDeep.dll` 与 `QSTPLevel2` 是关键线索

从 `tdxw.exe` 字符串与模块导出中已经找到：

- `L2HOST`
- `SDKL2Agent`
- `NoSDKUseQSTPCheckL2`
- `QSTPLevel2_SepcComte`
- `TdxDeep_StartInit`
- `TdxDeep_Data`
- `TdxDeep_Uninit`

这说明：

- 官方客户端内部明显区分了 `L1 / L2 / QSTP / TdxDeep` 相关流程
- `7719` 更像是绑定在另一套 L2 业务分支上
- 当前公开的标准行情实现并没有覆盖这条分支

### 4.5 当前目标客户端

本机存在多套通达信客户端。用户已确认第二阶段优先分析：

```text
D:\APP_SOFT\TDX
```

本机同时还发现：

- `D:\TDX_PLUS`
- `D:\APP_SOFT\TDX\Update\2025121120_bak`

后续文档中如果没有特别说明，`tdxw.exe / TDXDeep.dll / nacomte.dat / nbcomte.dat` 均指 `D:\APP_SOFT\TDX` 目录下的文件。

### 4.6 `D:\APP_SOFT\TDX` 静态扫描新增事实

2026-04-26 对 `D:\APP_SOFT\TDX` 做只读字符串和导出函数扫描。

`TDXDeep.dll` 导出：

- `TdxDeep_Data`
- `TdxDeep_Func`
- `TdxDeep_RegisterCallBackFunc`
- `TdxDeep_SetMainWnd`
- `TdxDeep_StartInit`
- `TdxDeep_Uninit`

`tdxw.exe` 中新增确认的关键字符串：

- `L2HOST`
- `L2UserName`
- `LEVEL2_ID=`
- `LEVEL2_PWD=`
- `LEVEL2ID=`
- `LEVEL2PWD=`
- `TC_GetL2Info`
- `TC_SetL2UserInfo`
- `Start TPL2_Check`
- `TPL2_Check Sync OK!`
- `Start TP_Check_GTJAL2: %s,%s,%s`
- `TP_Check_GTJAL2 return,SyncMode=%d,code=%d,ans: %s`
- `https://%s/quotes/now-auth-tdx`

`l2plugin.cfg` 明确包含：

```ini
[Version]
HasLevel2Engine=1
EverTdxLevel2=1
```

这些线索表明，`7719` 的前置流程很可能不是单个 TCP setup，而是包含：

- Level2 账号或权限信息设置
- Level2 权限检查
- TP/TPL2 同步检查
- QSTP/Level2 主站选择
- `TDXDeep.dll` 初始化

当前下一步应优先梳理这些初始化/鉴权路径，而不是直接尝试十档解析。

### 4.7 带偏移上下文与 import 表复核新增事实

2026-04-26 继续新增只读脚本：

```text
python-bridge/research/tdx_l2_string_context.py
python-bridge/research/pe_imports.py
```

生成输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_string_context.json
python-bridge/research/out/APP_SOFT_TDX/pe_imports.json
```

关键新增事实：

- `tdxw.exe` 中 `TC_SetL2UserInfo` 与 `TC_GetL2Info` 相邻，前后同组还包含 `TC_TQLAnswer / TC_OperateUser / TC_SetFeedBackMsg / TC_Uninit`。
- `tdxw.exe` 中 `TdxDeep_Uninit / TdxDeep_Data / TdxDeep_Func / TdxDeep_SetMainWnd / TdxDeep_RegisterCallBackFunc / TdxDeep_StartInit` 与 `%sTDXDeep.dll` 相邻。
- `tdxw.exe` 中 `QSTPLevel2_SepcComte / Level2_SepcComte` 与 `l2plugin.cfg / Level2_AutoupId / QSUserCfgName` 相邻。
- `tdxw.exe` 中 `TPL2_Check / TP_Check_GTJAL2 / TPL2_Check Sync OK!` 与 `Level-2 / RightInfo / Local.GetLoginRetInfo / :Comte` 等字符串相邻。
- `tdxw.exe` 中可见包含 `SSOMode / L2Right / QSID / l2FunctionFlag` 的 SSO JSON 模板。
- `TDXDeep.dll` import 表包含 `TGear.dll` 的 `DirectConnect / SendToSocket / ParseMessageStr / GetFileMD5Str`，以及 socket 相关导入。
- `tdxw.exe` import 表包含 `LoadLibraryA / LoadLibraryExA / GetProcAddress`，并导入 `TdxAsioComm.dll` 的 `MakeUserCommModule / DelUserCommModule`。

这使当前工程推断更具体：

1. `TDXDeep.dll` 很可能通过动态加载和导出函数表参与深度行情链路。
2. `TC_SetL2UserInfo / TC_GetL2Info` 可能是 Level2 权限信息传递入口。
3. `SSOMode / L2Right / QSID / TPL2_Check` 更像前置权限同步链路的一部分。
4. `QSTPLevel2_SepcComte / Level2_SepcComte` 更像 L2/QSTP 主站或 comte 选择链路的一部分。

但仍需强调：

- 当前没有调用 `TDXDeep.dll`。
- 当前没有函数签名。
- 当前没有十档或逐笔业务命令号。
- 当前没有 `7719` 真实业务返回包。
- 当前没有任何新增逻辑接入生产 bridge。

### 4.8 前置鉴权 / 权限同步入口定位

2026-04-26 继续只读定位后，当前已确认：

- `TC_SetL2UserInfo` 与 `TC_GetL2Info` 不是只存在于 `tdxw.exe` 的普通字符串。
- 二者是 `D:\APP_SOFT\TDX\tc.dll` 的明确导出函数。

`tc.dll` 关键导出：

| ordinal | RVA | 导出函数 |
| --- | --- | --- |
| `22` | `0xA5480` | `TC_GetL2Info` |
| `23` | `0xA5220` | `TC_GetLoginRet` |
| `24` | `0xA5330` | `TC_GetRightInfo` |
| `28` | `0xA4700` | `TC_Login` |
| `29` | `0xA4C10` | `TC_Login2` |
| `36` | `0xA5B80` | `TC_SetL2UserInfo` |

`tpbus.dll` 中则出现了更完整的登录/SSO 字段组装线索：

- `InputQSID`
- `SSOMode`
- `InputZHLB`
- `InputZH`
- `Token`
- `AuthInfo`
- `PWD`
- `ZH`
- `SetSSOInfo SSOMode=%d`
- `TDXToken`
- `RightEx`

因此当前最合理的链路推断更新为：

```text
tdxw.exe
  -> tpbus.dll 组装登录 / SSO / QSID / Token / AuthInfo 请求
  -> tc.dll: TC_Login / TC_Login2
  -> tc.dll: TC_GetLoginRet / TC_GetRightInfo
  -> 写入 L2ZH / L2Right / QSID / Token 等权限态
  -> tc.dll: TC_SetL2UserInfo(...)
  -> tc.dll: TC_GetL2Info(...)
  -> TDXDeep.dll / QSTPLevel2_SepcComte / 7719
```

入口附近机器码的低风险检查显示：

- `TC_SetL2UserInfo` 引用约 3 个入参。
- `TC_GetL2Info` 引用约 2 个入参。
- `TC_GetLoginRet` 引用约 1 个入参。
- `TC_GetRightInfo` 引用约 2 个入参。

这还不是完整函数签名，但已经足以说明：`TDX_L2_USERNAME / TDX_L2_PASSWORD` 不能直接等价为十档行情能力，必须先跑通 `tpbus.dll / tc.dll` 这条前置登录与权限同步链路。

下一步应新增隔离探针，只做 DLL 加载和导出解析，不写真实凭据，不接入生产 bridge：

```text
python-bridge/research/tc_l2_entry_probe.py
```

### 4.9 `tc_l2_entry_probe.py` 探针结果

2026-04-26 已新增并运行隔离探针：

```text
python-bridge/research/tc_l2_entry_probe.py
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tc_l2_entry_probe_static.json
python-bridge/research/out/APP_SOFT_TDX/tc_l2_entry_probe_load_only.json
```

新增确认：

- 当前本机 Python 是 `64bit`。
- `tc.dll / TDXDeep.dll / tpbus.dll / tdxw.exe` 均为 `x86 / 32bit`。
- 因此当前 64 位 Python 不能直接加载或调用这些 DLL。
- `--load-only` 会返回 `bitness_mismatch`，不会尝试调用 DLL。

静态探针按导出 RVA 裁剪函数范围后，关键参数估算如下：

| 函数 | 参数数量推断 | 备注 |
| --- | ---: | --- |
| `TC_SetL2UserInfo` | 3 | 32 字节薄封装，明确压入 3 个外部参数后调用内部实现 |
| `TC_GetL2Info` | 2 | 明确检查并读取两个外部参数 |
| `TC_GetLoginRet` | 1 | 更像输出登录结果 buffer |
| `TC_GetRightInfo` | 3 | 比上一轮的 2 参数判断更准确，存在第 3 参数检查 |
| `TC_Init_Environ` | 约 6 | 初始化环境入口 |
| `TC_Login / TC_Login2` | 至少 4 | 仍需进一步确认完整签名 |

`TC_SetL2UserInfo` 的入口行为已经非常明确：

```text
push arg3
push arg2
push arg1
mov ecx, fixed_context
call internal_impl
ret
```

这说明：

- L2 权限写入入口已经定位。
- `TC_SetL2UserInfo` 很可能不是直接执行登录，而是把已经获得的 L2 权限态写入 `tc.dll` 内部上下文。
- 三个参数的含义仍需继续确认，不能直接假设为 `username / password / token`。

后续如果要动态验证，必须先准备 32 位运行环境；当前 64 位 Python 只能继续做静态分析。

### 4.10 `TC_SetL2UserInfo` 内部转发逻辑

进一步静态下探确认：

- `TC_SetL2UserInfo` 导出层调用 `tc.dll RVA 0x32C20`。
- 内部实现检查固定上下文对象的 `+0xE0` 字段。
- 如果该字段为空，返回 `0`。
- 如果该字段存在，则把 3 个外部参数继续压栈转发给该内部对象，并返回 `1`。

这说明 `TC_SetL2UserInfo` 更像：

```text
TC 已初始化上下文 -> L2 子对象 -> 写入/同步 L2 用户权限态
```

而不是：

```text
账号 + 密码 -> 直接登录 L2
```

因此当前关键点进一步收敛为：

1. 必须先让 `tc.dll` 初始化出内部 L2 子对象。
2. 必须从 `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo` 链路拿到官方认可的权限态。
3. `TC_SetL2UserInfo` 的 3 个参数大概率来自该权限态，而不是简单的裸账号密码。
4. `TC_GetL2Info` 才是验证 L2 权限态是否写入成功的读入口。

`TC_GetL2Info` 核心内部入口落在 `tc.dll RVA 0x33E60`，明确引用两个外部参数，疑似输出 L2 状态或权限信息。

### 4.11 `tdxw.exe` xref 下探新增事实

新增静态 xref 探针：

```text
python-bridge/research/tdx_l2_xref_probe.py
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_xref_probe.json
```

本轮从 `tdxw.exe` 侧确认：

| 入口 | 动态解析 / 调用线索 |
| --- | --- |
| `TC_SetL2UserInfo` | 导出名字符串 `RVA 0x00861454`，解析后函数指针槽 `VA 0x01227E20`，明确间接调用点 `RVA 0x003221D1` |
| `TdxDeep_StartInit` | 解析后函数指针槽 `VA 0x012285C8`，明确调用点 `RVA 0x00325731`，调用后清栈 `0x1C`，约 7 参数 |
| `TdxDeep_RegisterCallBackFunc` | 解析后函数指针槽 `VA 0x012285CC`，明确调用点 `RVA 0x00325759`，调用后清栈 `0x0C`，约 3 参数 |

`TC_SetL2UserInfo` 的调用点清栈 `0x0C`，与 `tc.dll` 导出层 3 参数薄封装一致。这个事实把当前判断推进了一步：

- `TC_SetL2UserInfo` 不是孤立导出。
- 官方客户端确实解析并调用它。
- 下一步应追踪 `tdxw.exe RVA 0x003221D1` 前三个实参的来源。

`TdxDeep_StartInit` 的约 7 参数调用点则说明深度行情 DLL 初始化依赖一组上下文，后续需要确认这些参数是否包含权限态、路径、主站、回调或窗口句柄。

### 4.12 调用点参数形态新增事实

新增输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_callsite_probe.json
```

对 `TC_SetL2UserInfo` 调用点 `RVA 0x003221D1` 的静态还原结果：

```text
mov esi, "CITICS"
push esi
lea edx, [ebp-0x28]
push "%s#CFV"
push edx
call mfc100.dll ordinal 4283
...
call [TC_SetL2UserInfo slot]
add esp, 0x0c
```

这带来两个更具体的判断：

- `TC_SetL2UserInfo` 调用现场明确出现券商标识 `"CITICS"` 与格式串 `"%s#CFV"`。
- 它更像消费已经组装好的券商/L2 通道标识串和权限态结果，而不是直接接收裸账号密码。

对 `TdxDeep_StartInit` 调用点 `RVA 0x00325731` 的静态还原结果：

```text
push "connect.cfg"
...
push 0
push 0x00E75858
push ecx
push edx
...
call [TdxDeep_StartInit slot]
add esp, 0x1c
```

这说明 `TdxDeep_StartInit` 现场明显依赖配置和运行时上下文。当前更合理的判断因此变成：

- `TC_SetL2UserInfo` 更接近前置权限同步入口。
- `TdxDeep_StartInit` 更接近在权限态已建立后的深度行情引擎初始化入口。

也就是说，当前主线仍应优先追 `TC_SetL2UserInfo` 的 3 个实参来源，而不是先试图完整还原 `TdxDeep_StartInit` 的 7 个参数。

### 4.13 全局对象 xref 新增事实

新增输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_object_xref_probe.json
```

`TC_SetL2UserInfo` 调用点使用的 `0x011D4FEC` 是复用型 MFC 字符串/上下文对象，不是 L2 专属对象。但它的 L2 相关引用很集中：

| RVA | 线索 |
| --- | --- |
| `0x001D4FA1` | `##L2ZH## / ##localjointoken## / ##secumobileno##` |
| `0x003221BA` | `CITICS / %s#CFV`，随后进入 `TC_SetL2UserInfo` |
| `0x00510833` | `SSOMode 13/15 / QSID / L2ZH / L2Right / SSO.applysso / JSSO.applysso` |

这说明当前最有价值的鉴权链路不再只是 `tc.dll` 导出层，而是：

```text
SSO/JSSO.applysso
  -> L2ZH / L2Right / QSID 权限 JSON
  -> 0x011D4FEC 相关字符串对象 / MFC helper
  -> CITICS / %s#CFV 通道标识
  -> TC_SetL2UserInfo 三参数入口
```

相比之下，`TdxDeep_StartInit` 相关对象大量命中 `connect.cfg / L2PrimaryHost / PrimaryTPHost / 代理 / 主站配置`，更像深度行情引擎和站点上下文初始化，不是当前最前置的权限来源。

### 4.14 `x86 helper` 最小动态验证

新增工程：

```text
tools/TdxL2Helper
```

构建与运行：

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe inspect --tdx-root D:\APP_SOFT\TDX
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_x86_helper_inspect.json
```

本轮确认：

- helper 进程 `processArchitecture = X86`
- `pointerSizeBits = 32`
- `tc.dll` 实际加载成功，并解析：
  - `TC_Init_Environ`
  - `TC_Login`
  - `TC_Login2`
  - `TC_GetLoginRet`
  - `TC_GetRightInfo`
  - `TC_GetL2Info`
  - `TC_SetL2UserInfo`
  - `TC_Uninit`
- `TDXDeep.dll` 实际加载成功，并解析：
  - `TdxDeep_StartInit`
  - `TdxDeep_Data`
  - `TdxDeep_Func`
  - `TdxDeep_RegisterCallBackFunc`
  - `TdxDeep_SetMainWnd`
  - `TdxDeep_Uninit`

这意味着当前阻塞已经变化：

- 之前的阻塞是“64 位 Python 不能直接调用 32 位 DLL”。
- 现在这道门槛已经由独立 `x86 helper` 跨过。
- 后续阻塞转成“哪些函数可以先安全调用，以及参数语义如何确认”。

### 4.15 首批动态验证顺序修正

结合静态分析与 helper 落地结果，当前更合理的最小动态验证顺序是：

1. `LoadLibraryExW / GetProcAddress`
2. `TC_Init_Environ`
3. `TC_GetL2Info`
4. `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo`
5. `TC_SetL2UserInfo`
6. `TdxDeep_StartInit`

原因：

- `TC_Init_Environ` 应先于所有 `TC_*` 读写，避免 `TC_SetL2UserInfo` 命中空的内部 `+0xE0` 子对象。
- `TC_GetL2Info` 是当前最适合先做的只读基线调用。
- `TC_SetL2UserInfo` 不是登录函数，更像权限态同步入口。
- `TdxDeep_StartInit` 明显更重，且更像权限态已建立后的深度行情引擎初始化入口。

---

## 5. `pytdx` 评估结论

### 5.1 文档层面

已阅读本地资料：

- [pytdx接口说明.md](</c:/Users/Think/Downloads/pytdx接口说明.md>)

文档中明确能看到的是：

- `pytdx.hq`：标准行情
- `pytdx.exhq`：扩展行情
- `get_security_quotes`
- `get_transaction_data`
- `get_instrument_quote`

但文档里没有明确覆盖：

- A 股 `7719`
- 真 `L2`
- 十档盘口登录流程

### 5.2 实测层面

已实际安装并探测 `pytdx 1.72`，结果如下：

- `218.6.170.47:7709`
  - 可返回标准行情
  - 可返回标准五档
  - 可返回标准分笔
- `106.52.50.92:7719`
  - 连接能建
  - `get_security_quotes()` 返回空
  - `get_transaction_data()` 返回空
- `124.71.222.84:7719`
  - 结果同样为空

也就是说：

- `pytdx` 在 `7709` 上成立
- 在 `7719` 上同样没有突破

### 5.3 项目决策

截至本次评估，`pytdx` 的定位不优于当前 `mootdx` 方案：

- 没有解决 `7719`
- 没有证明自己支持真 `L2` 十档
- 还会引入额外迁移成本

因此结论是：

- **不切换主链路到 `pytdx`**
- `pytdx` 已从本机 Python 环境卸载

---

## 6. 当前项目中可以成立的部分

当前已经成立且可继续使用的能力：

- `Python bridge + mootdx + 7709 + 本地 WebSocket`
- 热榜股票池实时刷新
- 标准五档盘口详情展示
- WebSocket 主链路 + HTTP fallback

当前仍未成立的能力：

- `7719` 的真实业务命令
- 真 `L2` 十档盘口
- 真 `L2` 逐笔
- 可能存在的专有鉴权 / 初始化流程

---

## 7. 当前最合理的判断

综合本轮实测，最接近事实的结论是：

1. `7719` 不是简单的“把 7709 换成 7719”。
2. 官方客户端在 `7719` 上用了另一套 `L2 / QSTP / TDXDeep` 相关流程。
3. `mootdx/tdxpy` 的公开标准行情实现没有覆盖这条流程。
4. `pytdx` 也没有比当前方案更接近解决该问题。

---

## 8. 后续建议

下一步优先级应当是：

1. 继续以当前 `7709 + WebSocket + HTTP fallback` 方案服务前端实时需求，但只把它视为过渡可用链路。
2. 独立推进真实 L2 鉴权入口验证，优先确认 `TC_SetL2UserInfo / TC_GetL2Info` 与上游登录/权限返回之间的参数关系。
3. 重点围绕：
   - `tpbus.dll`
   - `tc.dll`
   - `TDXDeep.dll`
   - `QSTPLevel2_*`
   - `nacomte.dat / nbcomte.dat`
   - 官方客户端运行时对比

不建议继续在：

- `mootdx` 和 `pytdx` 之间来回切换
- 仅靠增加账号密码字段做无效试错

---

## 9. 2026-04-26 第二阶段攻关记录

### 9.1 攻关边界

本阶段目标不是把问题停留在文档探索，而是围绕最初的 `L2 十档行情 + 分笔` 目标继续推进。公开方案调研、静态扫描、隔离探针都只是手段，最终收敛点是找到真实 L2 鉴权 / 权限同步入口，并证明它能驱动 `7719 / TDXDeep / QSTP` 链路返回真十档和分笔。

当前约束：

- 开源优先。
- 商业或券商 Level2 API 只作为风险备选记录。
- 不修改当前 `python-bridge/main.py` 默认生产链路。
- 不重新安装 `pytdx`。
- 不做客户端注入、不修改通达信安装目录、不做侵入式逆向。

### 9.2 第一批搜索关键词

- `通达信 7719 Level2 十档`
- `TDXDeep.dll QSTPLevel2`
- `TdxDeep_StartInit`
- `QSTPLevel2_SepcComte`
- `通达信 L2 python github`
- `tdx level2 quote github`
- `site:github.com 通达信 level2`
- `site:github.com tdx level2 行情`

### 9.3 候选项目分级

| 等级 | 含义 | 当前处理 |
| --- | --- | --- |
| A | 明确支持 A 股 `7719` 十档/逐笔，可实测 | 可进入隔离验证 |
| B | 只支持 `7709` 五档或标准行情，可作为参考 | 不替换当前 bridge |
| C | 商业/闭源/Token/OpenAPI 路线，不能直接验证协议 | 只作为风险备选 |
| D | 归档、过期、不可用或无关 | 不采用 |

### 9.4 当前候选结论

| 仓库 / 方案 | 等级 | 是否支持 `7719` | 是否支持十档 | 是否维护 | 是否可试验 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `mootdx/mootdx` | B | 未证明 | 未证明 | 是 | 已用于当前 bridge | 保留现有 `7709` 主链路，不作为 `7719` 解法 |
| `rainx/pytdx` / pytdx forks | D | 实测未通 | 未证明 | 主仓库已归档 | 不再试验 | 历史评估关闭，不恢复依赖 |
| `zsdtdx` | B | 未证明 | 未证明 | 可安装包存在 | 可只读评估 | 更像标准行情 wrapper，未看到真 L2 证据 |
| `quant1x/gotdx` | B | 未证明 | 未证明 | Go 生态项目 | 仅参考协议思路 | 暂无 A 股 `7719` 十档证据 |
| `NodeQuant/opentdx` / `nodetdx` 类项目 | B/D | 未证明 | 未证明 | 项目状态不一 | 暂不接入 | 更接近标准行情接口，不作为第二阶段主线 |
| `jvQuant/OpenAPIDemo` | C | 非通达信 `7719` | 声称 Level2 OpenAPI | 商业/OpenAPI 路线 | 可作为备选调研 | 不替代当前开源协议主线 |

### 9.5 当前判断

截至本轮搜索，未发现“开箱即用、开源、明确支持 A 股 `7719` 十档盘口和逐笔”的成熟项目。

因此第二阶段下一步仍应围绕真实鉴权入口继续推进：

- `tpbus.dll`
- `tc.dll`
- `TDXDeep.dll`
- `QSTPLevel2_*`
- `nacomte.dat / nbcomte.dat`
- 官方客户端运行时连接行为

做隔离验证和必要的静态分析。只有当鉴权态可以被合法建立、读取，并驱动深度行情返回真实数据后，才算进入接入实现阶段。

### 9.7 当前验收差距

当前还不能验收《通达信 L2 十档实时行情重构计划》，因为缺口仍然是：

- 未确认 `TC_SetL2UserInfo` 的 3 个参数含义。
- 未确认 `TC_GetL2Info` 的输出 buffer 格式。
- 未跑通 `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo -> L2Right / L2ZH / QSID / Token` 的权限来源链路。
- 未确认 `TDXDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 如何消费 L2 权限态。
- 未拿到 `7719` 真十档或真分笔业务包。
- 未拿到通达信资金公式所需的 `L2_AMO(0..3, 0..3)` 或等价分档成交金额。

补充结论：

- `L2_AMO` 不是十档盘口本身。十档盘口提供档位价格和挂单量，不能直接等价为超大/大单/中单/小单成交金额。
- 当前 `mootdx + 7709` 标准行情字段只能支持资金估算，不能保证逐票对齐通达信主力资金。
- 如果最终目标包含主力资金完全对齐，验收数据面必须同时覆盖真十档、真逐笔/逐单，或直接返回 `L2_AMO` 等价字段。

### 9.6 隔离探针

已新增只读探针：

```text
python-bridge/research/tdx_l2_probe.py
```

当前探测范围：

- TCP 连接耗时
- `mootdx` 标准行情连接耗时
- `stock_count`
- `quotes`
- `transaction`
- tdxpy traffic stats

2026-04-26 运行摘要：

| 节点 | 结果 |
| --- | --- |
| `218.6.170.47:7709` | 可返回标准行情和五档字段 |
| `106.52.50.92:7719` | TCP/连接可达，但 `stock_count / quotes / transaction` 为空 |
| `124.71.222.84:7719` | TCP/连接可达，但 `stock_count / quotes / transaction` 为空 |

这进一步支持当前判断：`7719` 的阻塞点在业务协议层，不在基础网络连通性。

---

## 10. 边界说明

本文件中的结论分两类：

- **实测事实**：来自本机网络连接、原始返回结果、日志、二进制文件
- **工程推断**：例如 `TDXDeep.dll` 很可能参与 L2 业务流程，这类判断有证据支撑，但仍非官方公开文档结论

公开资料与仓库入口：

- `mootdx`: https://github.com/mootdx/mootdx
- `pytdx`: https://github.com/rainx/pytdx
- `jvQuant OpenAPI Demo`: https://github.com/jvQuant/OpenAPIDemo
- `zsdtdx`: https://pypi.org/project/zsdtdx/

---

## 11. 2026-04-26 TP/TPL2 鉴权检查链路补充

新增只读探针：

```text
python-bridge/research/tdx_l2_tpcheck_probe.py
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_tpcheck_probe.json
```

本轮把 `TP_Check_GTJAL2 / TPL2_Check` 从字符串线索推进到函数体和直接调用点：

| 项 | RVA | 结论 |
| --- | --- | --- |
| `TP_Check_GTJAL2` 函数体 | `0x00511F10` | 内含启动日志、返回日志、`RightInfo/L2ZH`、`Local.GetLoginRetInfo`、`TPL2_Check` |
| 唯一直接调用者 | `0x00383BE5` | `call rel32 -> 0x00511F10` |
| `Start TP_Check_GTJAL2` 引用 | `0x00511F6C` | 函数启动 |
| `TP_Check_GTJAL2 return...` 引用 | `0x0051204F` | 同步模式、返回码、响应文本 |
| `Local.GetLoginRetInfo` 引用 | `0x005129F3` | 本地登录返回查询 |
| `TPL2_Check` 引用 | `0x00512C31` | L2 同步检查阶段 |
| `TPL2_Check Sync OK!` 引用 | `0x0051273F` | 同步成功日志 |

当前链路收敛为：

```text
SSO/JSSO.applysso
  -> L2ZH / L2Right / QSID 权限 JSON
  -> TP_Check_GTJAL2 / TPL2_Check
  -> Local.GetLoginRetInfo / RightInfo / L2ZH
  -> TC_SetL2UserInfo
  -> TdxDeep_StartInit / 7719 深度行情链路
```

这进一步降低了 `TdxDeep_StartInit` 作为最前置鉴权入口的可能性。当前更合理的职责划分是：

- `SSO/JSSO.applysso`：发起或构造权限请求。
- `TP_Check_GTJAL2 / TPL2_Check`：检查 L2 权限返回和同步状态。
- `TC_SetL2UserInfo`：把已获得的 L2 用户/权限态写入 `tc.dll`。
- `TdxDeep_StartInit`：在权限态具备后初始化深度行情引擎。
