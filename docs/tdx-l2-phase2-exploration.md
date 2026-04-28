# 通达信 7719 / L2 第二阶段探索日志

更新时间：2026-04-26

## 1. 阶段目标

第二阶段目标是继续完成最初的《通达信 L2 十档实时行情重构计划》，不是把工作停在 `L1 + 五档`。当前要在边探索、边记录、边验证的过程中，找到真实 L2 鉴权 / 权限同步入口，并最终验证 `7719 / 真 L2 十档 / 真 L2 分笔` 可以返回业务数据。

公开实现路径调研仍然保留，但它只是辅助方向。真正的收敛目标是：

- 找到 `tpbus.dll / tc.dll / TDXDeep.dll / QSTP` 之间的 L2 权限链路。
- 确认 `TC_SetL2UserInfo / TC_GetL2Info` 的参数和输出语义。
- 证明 `TDXDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 能在合法权限态下进入深度行情链路。
- 拿到真实十档盘口和分笔数据，再进入 bridge 接入设计。

当前稳定生产链路保持不变：

- `mootdx`
- `7709 / L1 + 标准五档`
- `python-bridge`
- 本地 WebSocket
- HTTP fallback

这条链路只是过渡可用链路，用于先解决 HTTP 轮询旧价问题；它不能作为 L2 十档方案的最终验收结果。

本阶段不处理 UI 收尾，不改 `DataTable / DataFreshness / StockL2DetailPanel`，不改现有 bridge 默认行为。

## 2. 搜索关键词

第一批固定关键词：

- `通达信 7719 Level2 十档`
- `TDXDeep.dll QSTPLevel2`
- `TdxDeep_StartInit`
- `QSTPLevel2_SepcComte`
- `通达信 L2 python github`
- `tdx level2 quote github`
- `site:github.com 通达信 level2`
- `site:github.com tdx level2 行情`

后续补充关键词：

- `SDKL2Agent 通达信`
- `NoSDKUseQSTPCheckL2`
- `L2HOST 通达信`
- `通达信 nacomte.dat nbcomte.dat`
- `通达信 TDXDeep_Data`

## 3. 候选分级规则

| 等级 | 判定标准 | 处理方式 |
| --- | --- | --- |
| A | 明确支持 A 股 `7719` 十档/逐笔，可在隔离环境实测 | 进入最小验证 |
| B | 支持 `7709` 标准行情或五档，可参考但不能解决真 L2 | 记录，不替换当前 bridge |
| C | 商业/闭源/Token/OpenAPI 路线，不是通达信 `7719` 开源协议 | 作为风险备选 |
| D | 归档、不可维护、不可用或无关 | 不采用 |

## 4. 第一轮公开搜索结论

| 仓库 / 方案 | 等级 | 结论 |
| --- | --- | --- |
| `mootdx/mootdx` | B | 当前 bridge 已使用；公开能力仍集中在标准行情读取，未证明支持 `7719` 真 L2 十档。 |
| `rainx/pytdx` | D | 已归档；本机历史实测 `7709` 可用、`7719` 为空；不恢复依赖。 |
| `zsdtdx` | B | 包说明更接近 pytdx-style 标准行情封装，未看到 A 股 `7719` 十档或逐笔证据。 |
| `quant1x/gotdx` | B | 可作为 Go 生态协议参考，未看到真 L2 十档证据。 |
| `NodeQuant/opentdx` / `nodetdx` 类项目 | B/D | 更接近标准行情接口，暂未发现 `7719 / 十档 / 逐笔` 明确实现。 |
| `jvQuant/OpenAPIDemo` | C | 商业/OpenAPI/Token 路线，可能提供 Level2 WebSocket，但不是通达信 `7719` 开源协议实现。 |

截至本轮，没有发现 A 级候选。

## 5. 本地协议验证边界

只读探测脚本已新增：

```text
python-bridge/research/tdx_l2_probe.py
```

探测内容限定为：

- TCP 连接是否建立
- 基础握手是否成功
- 标准行情命令是否仍为空
- 响应包长度、错误码、耗时
- 与 `7709` 标准命令返回差异

禁止事项：

- 不修改通达信客户端文件
- 不注入官方客户端进程
- 不替换 `python-bridge/main.py` 默认链路
- 不把 `TDX_L2_USERNAME / TDX_L2_PASSWORD` 当作已实现登录
- 不重新安装 `pytdx`

## 6. 2026-04-26 只读探针结果

执行命令：

```bash
python python-bridge/research/tdx_l2_probe.py --timeout 8
```

探测节点：

- `218.6.170.47:7709`
- `106.52.50.92:7719`
- `124.71.222.84:7719`

样本代码：

- `000001`
- `600000`

结果摘要：

| 节点 | TCP | mootdx connect | stock_count | quotes | transaction | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `218.6.170.47:7709` | 成功，约 29ms | 成功，约 145ms | 有值 | 2 行，含 `bid1~bid5 / ask1~ask5` | 0 行 | 标准行情和五档可用 |
| `106.52.50.92:7719` | 成功，约 21ms | 成功，约 159ms | 空 | 0 行 | 0 行 | TCP/握手可达，标准命令无业务数据 |
| `124.71.222.84:7719` | 成功，约 683ms | 成功，约 322ms | 空 | 0 行 | 0 行 | TCP/握手可达，标准命令无业务数据 |

关键观察：

- `7709` 返回字段只有标准五档：`bid1~bid5`、`ask1~ask5`、`bid_vol1~bid_vol5`、`ask_vol1~ask_vol5`。
- 两个 `7719` 节点都不是 TCP 不通，而是 `mootdx/tdxpy` 标准行情命令在业务层拿不到数据。
- `7719` 节点仍有收发包统计，说明连接和基础交互发生过，但不是当前公开标准命令能解析成行情的路径。

本轮结论：

- 当前问题继续定位为 `7719` 业务协议分支不兼容。
- 不是简单的节点不可达，也不是把端口改为 `7719` 就能获得真 L2。
- 下一步应继续围绕 `TDXDeep.dll / QSTPLevel2_* / nacomte.dat / nbcomte.dat` 做只读分析。

## 7. 下一步

优先方向：

1. 继续定位真实 L2 鉴权入口，优先从 `tpbus.dll -> tc.dll -> TDXDeep.dll` 的权限同步链路推进。
2. 确认 `TC_SetL2UserInfo / TC_GetL2Info` 的参数、输出 buffer 和初始化前置条件。
3. 梳理本机 `tdxw.exe`、`TDXDeep.dll` 中可见字符串与导出函数，重点追 `TdxDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 的调用顺序。
4. 扩展隔离探针，验证 `7719` 空返回与 L2 权限态缺失之间的关系。
5. 继续检索 `TDXDeep.dll / QSTPLevel2_* / SDKL2Agent` 相关公开资料；若仍无开源路径，再将商业/券商 Level2 API 作为风险备选方案单独评估。

## 8. 2026-04-26 `D:\APP_SOFT\TDX` 客户端静态只读扫描

用户确认后，第二阶段 `7719 / L2` 分析目标客户端固定为：

```text
D:\APP_SOFT\TDX
```

本机另有 `D:\TDX_PLUS`，但当前阶段不作为默认分析对象。

### 8.1 扫描脚本

新增只读扫描脚本：

```text
python-bridge/research/inspect_tdx_l2_artifacts.ps1
```

执行命令：

```powershell
powershell -ExecutionPolicy Bypass -File python-bridge/research/inspect_tdx_l2_artifacts.ps1 -TdxRoot D:\APP_SOFT\TDX -OutputDir python-bridge\research\out\APP_SOFT_TDX
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_artifacts_report.json
```

### 8.2 文件摘要

| 文件 | 结果 |
| --- | --- |
| `D:\APP_SOFT\TDX\tdxw.exe` | 存在，`14350256` 字节，SHA256 `F5F2E6025A4D80BB1AFBCB2A51C753D3C1909E09AA9D1BC8F7C3B701B081F74C` |
| `D:\APP_SOFT\TDX\TDXDeep.dll` | 存在，`312728` 字节，SHA256 `B1A4B08EFEFF964456004A56D6568913F01983D199DD0A9340478F697B3B09D4` |
| `D:\APP_SOFT\TDX\nacomte.dat` | 存在，`9572` 字节，未发现明文 L2 关键词 |
| `D:\APP_SOFT\TDX\nbcomte.dat` | 存在，`9572` 字节，内容 hash 与 `nacomte.dat` 一致，未发现明文 L2 关键词 |

### 8.3 `TDXDeep.dll` 导出函数

`TDXDeep.dll` 导出 6 个函数：

- `TdxDeep_Data`
- `TdxDeep_Func`
- `TdxDeep_RegisterCallBackFunc`
- `TdxDeep_SetMainWnd`
- `TdxDeep_StartInit`
- `TdxDeep_Uninit`

这说明 `TDXDeep.dll` 确实提供了外部可调用入口，但当前尚未确定函数签名、参数结构和调用顺序。

### 8.4 `tdxw.exe` 中的 L2 初始化/鉴权线索

`tdxw.exe` 可见字符串包括：

- `L2HOST`
- `L2UserName`
- `LEVEL2_ID=`
- `LEVEL2_PWD=`
- `LEVEL2ID=`
- `LEVEL2PWD=`
- `Level2_SepcComte`
- `QSTPLevel2_SepcComte`
- `SDKL2Agent`
- `AutoUseNoSDKL2Agent`
- `NoSDKUseQSTPCheckL2`
- `ProtectZHLoginLevel2`
- `TC_GetL2Info`
- `TC_SetL2UserInfo`
- `Start TPL2_Check`
- `TPL2_Check`
- `TPL2_Check Sync OK!`
- `Start TP_Check_GTJAL2: %s,%s,%s`
- `TP_Check_GTJAL2 return,SyncMode=%d,code=%d,ans: %s`
- `https://%s/quotes/now-auth-tdx`

这些字符串支持当前判断：`7719` 之前存在一套 Level2 权限检查、账号信息设置、SSO/鉴权或 TP/QSTP 初始化流程。

### 8.5 配置与日志线索

`D:\APP_SOFT\TDX\l2plugin.cfg` 内容：

```ini
[Version]
HasLevel2Engine=1
EverTdxLevel2=1
```

`connect.cfg` 中存在：

- `AutoUpZip=tdxw3_level2_tcpip`
- `[TPL2SYS]`
- `TPHost01=page1.tdx.com.cn`
- `TPHost02=page2.tdx.com.cn`
- `TPHost03=page3.tdx.com.cn`
- `[OTHERHOST]`
- `L2PrimaryHost=1`

`tdxsys3.log` 继续确认：

- 客户端反复获取 `zhb` 成功
- 随后更新 `D:\APP_SOFT\TDX\nacomte.dat`
- 随后更新 `D:\APP_SOFT\TDX\nbcomte.dat`
- 日志中出现 `106.52.50.92`、`124.71.222.84` 等 L2 主站切换记录

### 8.6 2026-04-26 重启后的 live 连接复核

官方客户端重启并恢复正常取 IP 后，基于 `tdxw.exe` 进程的实时连接复核到：

- `203.195.161.155:7719`
- `124.71.154.218:7712`
- `47.106.34.194:7615`

新增只读脚本：

```text
python-bridge/research/tdx_live_route_probe.py
```

执行命令：

```bash
python python-bridge/research/tdx_live_route_probe.py --ports 7719,7712,7615 --output python-bridge/research/out/APP_SOFT_TDX/tdx_live_route_probe.json
python python-bridge/research/tdx_l2_probe.py --servers 203.195.161.155:7719,124.71.154.218:7712,47.106.34.194:7615 --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_probe_live_routes.json
python python-bridge/research/tdx_l2_raw_command_probe.py --servers 203.195.161.155:7719,124.71.154.218:7712,47.106.34.194:7615 --output python-bridge/research/out/APP_SOFT_TDX/tdx_l2_raw_command_probe_live_routes.json
```

结果摘要：

- `203.195.161.155:7719`：TCP 可达，`mootdx` 连接可建立，`setup1/2/3` 仍正常，但标准 `quotes / transaction / 0x5053E` 仍为空或超时。
- `124.71.154.218:7712`：TCP 可达，但标准 `mootdx` 连接超时，原始 `setup1` 也直接超时。
- `47.106.34.194:7615`：TCP 可达，但标准连接和原始 `setup1` 都被远端 reset。

与配置文件的对应关系：

- `connect.cfg` 中存在 `7712` 条目，且 `IPAddress03=124.71.154.218`。
- `connect.cfg` 中 `TPHost01/02/03=page1/page2/page3.tdx.com.cn:7615`，与本轮 `7615` live 连接一致。
- `tdxsys3.log` 历史片段多次出现 `203.195.161.155`，说明它是官方客户端真实使用过的 `7719` 主站之一。

本轮判断：

- `7719` 仍是当前最值得继续追的真实 L2 数据链路。
- `7712` 更像客户端内部专用通道，不兼容公开标准行情 setup。
- `7615` 更接近 TP/page/icfqs 内容链路，不是十档入口。
- 当前权限下 `pktmon` 抓包会报“拒绝访问”，因此这轮先固定 live 路由，再继续走只读协议和 DLL 入口分析。

### 8.7 本轮判断

当前更合理的能力搭建顺序是：

1. 先确认 `TC_SetL2UserInfo / TC_GetL2Info / TPL2_Check / TP_Check_GTJAL2` 这类初始化和鉴权路径的职责。
2. 再确认 `QSTPLevel2_SepcComte / Level2_SepcComte` 如何影响 `7719` 主站选择。
3. 再分析 `TDXDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 的可能调用顺序。
4. 最后才进入十档盘口和逐笔业务命令解析。

当前仍不能直接写十档解析，因为还没有拿到 `7719` 十档原始业务包。

## 9. 参考入口

- `mootdx`: https://github.com/mootdx/mootdx
- `pytdx`: https://github.com/rainx/pytdx
- `jvQuant OpenAPI Demo`: https://github.com/jvQuant/OpenAPIDemo
- `zsdtdx`: https://pypi.org/project/zsdtdx/

## 10. 2026-04-26 带偏移字符串上下文与 PE import 复核

本轮继续保持只读边界：

- 不调用 `TDXDeep.dll`。
- 不注入或驱动 `tdxw.exe`。
- 不修改 `D:\APP_SOFT\TDX`。
- 不改变当前 `python-bridge/main.py` 生产链路。

### 10.1 新增脚本

新增带文件偏移的字符串上下文扫描：

```text
python-bridge/research/tdx_l2_string_context.py
```

执行命令：

```powershell
python python-bridge\research\tdx_l2_string_context.py D:\APP_SOFT\TDX\tdxw.exe D:\APP_SOFT\TDX\TDXDeep.dll --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_string_context.json
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_string_context.json
```

该脚本与此前 `inspect_tdx_l2_artifacts.ps1` 的区别是：

- 旧脚本适合确认关键词是否存在。
- 新脚本保留字符串文件偏移和前后邻近字符串，适合判断线索是否属于同一组函数表、配置组或日志组。

### 10.2 `tdxw.exe` 中的关键邻近关系

`TC_SetL2UserInfo` 与 `TC_GetL2Info` 相邻：

| 偏移 | 字符串 | 邻近线索 |
| --- | --- | --- |
| `0x860854` | `TC_SetL2UserInfo` | 前有 `TC_TQLAnswer / TC_OperateUser`，后接 `TC_GetL2Info / TC_SetFeedBackMsg` |
| `0x860868` | `TC_GetL2Info` | 与 `TC_SetL2UserInfo` 同组 |

这更像一组通过动态函数名解析的 `TC_*` 接口表，而不是孤立 UI 文案。

`TdxDeep_*` 与动态 DLL 路径相邻：

| 偏移 | 字符串 | 邻近线索 |
| --- | --- | --- |
| `0x860C88` | `TdxDeep_Uninit` | 前有 `TDX_Init / %sTDXRun.dll` |
| `0x860C98` | `TdxDeep_Data` | 后接 `TdxDeep_Func / TdxDeep_SetMainWnd` |
| `0x860CA8` | `TdxDeep_Func` | 同组包含 `TdxDeep_RegisterCallBackFunc / TdxDeep_StartInit` |
| `0x860D00` | `%sTDXDeep.dll` | 紧邻 `TdxDeep_StartInit` |

这支持当前判断：`tdxw.exe` 很可能通过 `LoadLibrary/GetProcAddress` 风格动态加载 `TDXDeep.dll` 并解析导出函数。

`QSTPLevel2_SepcComte`、`Level2_SepcComte` 与 `l2plugin.cfg` 相邻：

| 偏移 | 字符串 | 邻近线索 |
| --- | --- | --- |
| `0x8904B0` | `QSTPLevel2_SepcComte` | 前后可见 `TYBMode / l2plugin.cfg / externzh` |
| `0x8904DC` | `QSTPLevel2_SepcComte` | 同一邻近组再次出现 |
| `0x89051C` | `Level2_SepcComte` | 后接 `Level2_AutoupId / QSUserCfgName` |

这强化了此前判断：`nacomte.dat / nbcomte.dat` 可能只是运行时站点材料之一，`L2 / QSTP` 分支还受 `l2plugin.cfg`、用户配置和专用 comte 选择逻辑影响。

`TP/TPL2` 鉴权或同步检查相关日志相互邻近：

| 偏移 | 字符串 | 邻近线索 |
| --- | --- | --- |
| `0x896DC8` | `TP_Check_GTJAL2` | 邻近 `Level-2 / RightInfo` |
| `0x896E54` | `TP_Check_GTJAL2 return,SyncMode=%d,code=%d,ans: %s` | 后接 `Start TP_Check_GTJAL2` |
| `0x896ECC` | `TPL2_Check` | 前接 `TP_Check_GTJAL2 return...` |
| `0x896F60` | `TPL2_Check Sync OK!` | 邻近 `TdxW_GetLoginRetInfo / Local.GetLoginRetInfo` |
| `0x896F9C` | `Start TPL2_Check` | 后续邻近 `:Comte` |

这说明 `TPL2_Check` 不应被视为普通显示文案，更像登录态、权限态、主站态之间的同步检查路径。

### 10.3 SSO / Level2 权限参数线索

本轮确认两条与 `L2Right` 明确相关的 SSO JSON 模板：

```text
[{"TDXID":"%s","ZHLB":"99","SSOMode":13,"SysSource":"%s","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
[{"TDXID":"%s","ZHLB":"99","SSOMode":15,"SysSource":"%s","invalidTime":"%d","chanelType":"tdx","l2FunctionFlag":"1","QSID":"999","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
```

邻近字符串还包括：

- `SSO.applysso`
- `JSSO.applysso`
- `WatchMM.GetKey`

这支持一个更具体的工程推断：

- Level2 权限很可能先被编码进 SSO/权限返回，再写入或传入 `TC_SetL2UserInfo / TC_GetL2Info` 这一类接口。
- `TDX_L2_USERNAME / TDX_L2_PASSWORD` 这样的裸账号密码字段不足以替代这套 `SSO + L2Right + QSID/Token` 流程。

### 10.4 PE import 表复核

`TDXDeep.dll` import 表新增确认：

| DLL | 关键导入 |
| --- | --- |
| `KERNEL32.dll` | `LoadLibraryA / LoadLibraryExA / GetProcAddress` |
| `WSOCK32.dll` | socket 相关 ordinal 导入 |
| `TGear.dll` | `DirectConnect / SendToSocket / ParseMessageStr / GetFileMD5Str` |

`tdxw.exe` import 表新增确认：

| DLL | 关键导入 |
| --- | --- |
| `KERNEL32.dll` | `LoadLibraryA / LoadLibraryExA / GetProcAddress` |
| `TdxAsioComm.dll` | `MakeUserCommModule / DelUserCommModule` |
| `TGear.dll` | `GetTDXProfileInt / GetTDXProfileString / ParseMessageStr / Base64Encode / MD5_String / MD5_Buffer` |
| `WSOCK32.dll / WS2_32.dll` | socket / addrinfo 相关导入 |

这使 `TDXDeep.dll` 的角色更清晰：

- 它不是纯 UI DLL。
- 它有自己的网络发送、连接和消息解析依赖。
- 但仅凭 import 表仍不能得出它就是 `7719` 十档业务包解析器；当前只能判断它参与 L2/深度行情链路的概率升高。

### 10.5 本轮结论

本轮把第二阶段判断从“有若干 L2 字符串”推进到：

1. `tdxw.exe` 明显存在动态加载 `TDXDeep.dll` 并解析 `TdxDeep_*` 导出的结构性线索。
2. `TC_SetL2UserInfo / TC_GetL2Info` 与 `TC_*` 函数组相邻，可能是 Level2 权限信息传递入口。
3. `SSOMode / L2Right / QSID / TPL2_Check / TP_Check_GTJAL2` 共同指向一条前置鉴权或权限同步路径。
4. `QSTPLevel2_SepcComte / Level2_SepcComte / l2plugin.cfg` 共同指向 L2/QSTP 主站或 comte 选择路径。
5. `TDXDeep.dll` 自身导入 `DirectConnect / SendToSocket`，说明它具备网络通信能力。

仍未成立的能力没有变化：

- 没有拿到 `7719` 真业务包。
- 没有确认 `TdxDeep_StartInit / TdxDeep_Data / TdxDeep_Func` 的函数签名。
- 没有确认十档盘口或逐笔的命令号。
- 没有把任何逻辑接入生产 bridge。

下一步更合理的只读方向：

1. 从 `tdxw.exe` 的邻近字符串继续梳理 `TC_* / TCO_* / TDXRun.dll / TDXDeep.dll` 三组动态接口关系。
2. 对 `D:\APP_SOFT\TDX` 下可能相关 DLL 做同样的 PE import 和带偏移字符串扫描，尤其是 `TDXRun.dll`、`TControl.dll`、`TGear.dll`、`TdxAsioComm.dll`。
3. 仅在获得函数签名或公开资料佐证后，再考虑是否做独立进程的 DLL 调用试验。
4. 在此之前，不尝试把 `TDXDeep.dll` 嵌入 bridge，也不把账号密码变量解释为 L2 登录能力。

## 11. 2026-04-26 前置鉴权 / 权限同步入口定位

本轮目标从“找线索”收窄为：

- 找出 `TC_SetL2UserInfo / TC_GetL2Info` 的真实承载模块。
- 判断 `SSOMode / L2Right / QSID` 是由哪个模块组装。
- 找出后续是否可以做隔离 DLL 调用探针。

仍保持边界：

- 不记录真实账号、密码、Token。
- 不尝试绕过 Level2 权限。
- 不注入官方客户端进程。
- 不把未知签名 DLL 直接接入生产 bridge。

### 11.1 根目录 PE 关键词定位

只扫描 `D:\APP_SOFT\TDX` 根目录下的 `.dll / .exe`，避开 `vipdoc` 行情数据目录，结果如下：

| 文件 | 命中 |
| --- | --- |
| `tdxw.exe` | `TC_SetL2UserInfo / TC_GetL2Info / TPL2_Check / TP_Check_GTJAL2 / L2Right / SSOMode / QSTPLevel2_SepcComte / L2HOST / LEVEL2_ID / LEVEL2PWD` |
| `tc.dll` | `TC_SetL2UserInfo / TC_GetL2Info` |
| `tpbus.dll` | `SSOMode` |
| `TDXDeep.dll` | `TdxDeep_StartInit / TdxDeep_Data` |

这说明入口分工更清楚：

- `tdxw.exe`：调度、动态加载、日志和配置入口。
- `tc.dll`：交易/通用 TC 接口导出模块，也是 `TC_SetL2UserInfo / TC_GetL2Info` 的真实 DLL 落点。
- `tpbus.dll`：登录、SSO、Token、QSID、AuthInfo 这类请求字段的组装模块。
- `TDXDeep.dll`：深度行情相关 DLL，后续可能消费 `tc.dll` 传递的 L2 权限态。

### 11.2 `tc.dll` 导出表确认

新增 PE export 表解析脚本：

```text
python-bridge/research/pe_exports.py
```

执行命令：

```powershell
python python-bridge\research\pe_exports.py D:\APP_SOFT\TDX\tc.dll D:\APP_SOFT\TDX\TDXDeep.dll D:\APP_SOFT\TDX\tpbus.dll D:\APP_SOFT\TDX\TDXRun.dll --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_candidate_modules_exports.json
```

`tc.dll` 中确认的关键导出：

| ordinal | RVA | 导出函数 |
| --- | --- | --- |
| `22` | `0xA5480` | `TC_GetL2Info` |
| `23` | `0xA5220` | `TC_GetLoginRet` |
| `24` | `0xA5330` | `TC_GetRightInfo` |
| `28` | `0xA4700` | `TC_Login` |
| `29` | `0xA4C10` | `TC_Login2` |
| `36` | `0xA5B80` | `TC_SetL2UserInfo` |

因此现在可以把 `TC_SetL2UserInfo / TC_GetL2Info` 从“字符串线索”升级为：

- `tc.dll` 明确导出的 API。
- `tdxw.exe` 中同名字符串很可能用于 `LoadLibrary + GetProcAddress` 动态解析。

### 11.3 `tc.dll` 入口关系

`tc.dll` 的字符串上下文显示：

| 函数 | 邻近函数 |
| --- | --- |
| `TC_GetL2Info` | `TC_GetLoginRet / TC_GetRightInfo / TC_GetTCInfo / TC_GetVersion / TC_Login` |
| `TC_SetL2UserInfo` | `TC_RegisterCallBack / TC_RegisterCallBack2 / TC_SetFeedBackMsg / TC_SetFlag / TC_SetVersionInfo / TC_Uninit` |

这说明 `TC_GetL2Info` 更像读取当前 TC 内部保存的 L2 权限态；`TC_SetL2UserInfo` 更像写入 L2 用户/权限信息。

基于入口附近机器码的低风险检查，当前参数数量线索为：

| 函数 | 入口附近参数引用 | 初步推断 |
| --- | --- | --- |
| `TC_SetL2UserInfo` | 引用 `[ebp+08] / [ebp+0C] / [ebp+10]` | 约 3 个参数 |
| `TC_GetL2Info` | 引用 `[ebp+08] / [ebp+0C]` | 约 2 个参数 |
| `TC_GetLoginRet` | 引用 `[ebp+08]` | 约 1 个参数 |
| `TC_GetRightInfo` | 引用 `[ebp+08] / [ebp+0C]` | 约 2 个参数 |

这些函数入口附近均以普通 `ret` 返回，当前更像 `cdecl` 或由调用方清栈的约定，而不是 `stdcall ret imm16`。这只是静态线索，不能直接当作最终函数签名。

### 11.4 `tpbus.dll` 的 SSO/QSID 入口线索

`tpbus.dll` 没有导出 `TC_*`，但字符串上下文中明确出现登录请求字段组装：

```text
IXReq.SetItemLongValue("InputQSID", nQSID)
IXReq.SetItemLongValue("SSOMode", 2)
IXReq.SetItemLongValue("InputZHLB", 340)
IXReq.SetItemValue("InputZH", szValue)
IXReq.SetItemValue("Token", szSSO)
IXReq.SetItemLongValue("SSOMode", m_nSSOMode)
IXReq.SetItemValue("AuthInfo", szAuthInfo)
IXReq.SetItemValue("PWD", m_LoginInfoex.strPassword,TRUE)
IXReq.SetItemValue("ZH", m_LoginInfoex.strLoginName)
IXReq.SetItemValue("InputZH", m_LoginInfoex.strLoginName)
IXReq.SetItemValue("Token", szSSO,TRUE)
SetSSOInfo SSOMode=%d
LoginInfo ZHType=%d,LoginName=%s,YYBID=%s,LoginType=%d,Token=%s
SSOMode=%d cfgName=%s
TDXToken
RightEx
```

这说明 `SSOMode / QSID / Token / AuthInfo / PWD / ZH` 的组装更可能发生在 `tpbus.dll` 的登录链路里，而不是 `TDXDeep.dll` 内部。

当前最合理的链路推断：

```text
tdxw.exe
  -> tpbus.dll 组装登录 / SSO / QSID / Token / AuthInfo 请求
  -> tc.dll: TC_Login / TC_Login2
  -> tc.dll: TC_GetLoginRet / TC_GetRightInfo
  -> tdxw.exe 或 tc.dll 解析出 L2ZH / L2Right / QSID / Token
  -> tc.dll: TC_SetL2UserInfo(...)
  -> tc.dll: TC_GetL2Info(...)
  -> TDXDeep.dll: TdxDeep_StartInit / TdxDeep_Data / TdxDeep_Func
  -> QSTPLevel2_SepcComte / 7719 主站业务链路
```

### 11.5 当前关键落点

如果目标是“填入 L2 账号后拿十档”，当前落点不是直接连 `7719`，而是先把官方客户端的前置状态补齐：

1. 通过 `tpbus.dll / tc.dll` 登录链路拿到合法 `SSO / Token / QSID / RightInfo`。
2. 从返回中确认是否包含 `L2ZH / L2Right / l2FunctionFlag`。
3. 调用或复现 `TC_SetL2UserInfo` 写入 L2 权限态。
4. 调用 `TC_GetL2Info` 验证内部 L2 权限态是否成立。
5. 再进入 `TDXDeep_StartInit / QSTPLevel2_SepcComte / 7719`。

在没有完成 1-4 之前，直接把 `TDX_L2_USERNAME / TDX_L2_PASSWORD` 填到 bridge 或直接连 `7719`，仍然不会得到十档。

### 11.6 下一步最小可验证方案

下一步不应直接写生产代码，而应新增隔离探针：

```text
python-bridge/research/tc_l2_entry_probe.py
```

探针目标：

- 只加载 `D:\APP_SOFT\TDX\tc.dll`。
- 只解析导出函数地址。
- 先不传真实账号密码。
- 先验证 DLL 加载、导出解析、调用约定风险。
- 只有确认函数签名后，再考虑用环境变量传入测试账号。

环境变量建议只在本机 shell 临时设置，不写入文件：

```text
TDX_L2_USERNAME
TDX_L2_PASSWORD
```

仍需先解决的问题：

- `TC_Init_Environ / TC_Login / TC_Login2` 的完整参数签名。
- `TC_SetL2UserInfo` 三个参数分别是 `L2ZH / L2Right / QSID`，还是 `账号 / Token / 权限串`。
- `TC_GetL2Info` 两个参数是否为输出 buffer 与长度。
- `TC_LoginRet / TC_GetRightInfo` 的输出 buffer 格式。

因此本轮真正确定的是“入口模块和入口函数”，不是“账号密码已可直接换十档”。

## 12. 2026-04-26 `tc_l2_entry_probe.py` 隔离探针

本轮把第 11 节提出的最小探针落成脚本：

```text
python-bridge/research/tc_l2_entry_probe.py
```

默认模式是静态分析：

- 解析 `tc.dll / TDXDeep.dll / tpbus.dll / tdxw.exe` 的 PE 位数与导出表。
- 对 `tc.dll` 关键导出函数读取入口机器码。
- 估算 `[ebp+N]` 参数引用。
- 记录函数入口范围内的 `ret` 和直接 `call`。
- 不加载 DLL。
- 不调用 DLL。
- 不读取或写入账号密码。

执行命令：

```powershell
python python-bridge\research\tc_l2_entry_probe.py --output python-bridge\research\out\APP_SOFT_TDX\tc_l2_entry_probe_static.json
```

受保护的加载检查：

```powershell
python python-bridge\research\tc_l2_entry_probe.py --load-only --output python-bridge\research\out\APP_SOFT_TDX\tc_l2_entry_probe_load_only.json
```

### 12.1 位数约束

当前确认：

| 项 | 位数 |
| --- | --- |
| 本机当前 `python` | `64bit` |
| `tc.dll` | `x86 / 32bit` |
| `TDXDeep.dll` | `x86 / 32bit` |
| `tpbus.dll` | `x86 / 32bit` |
| `tdxw.exe` | `x86 / 32bit` |

因此当前 64 位 Python 不能直接加载 `tc.dll`。

`--load-only` 输出：

```json
{
  "mode": "load_only",
  "ok": false,
  "reason": "bitness_mismatch",
  "pythonBits": 64,
  "dllBits": 32,
  "path": "D:\\APP_SOFT\\TDX\\tc.dll"
}
```

这意味着后续如果要做真实 DLL 调用，必须使用：

- 32 位 Python；
- 或独立 32 位 helper 进程；
- 或继续只做静态分析，不进入 DLL 调用。

### 12.2 参数估算复核

静态探针按下一个导出 RVA 裁剪函数范围后，关键结果如下：

| 函数 | 分析长度 | 参数引用 | 参数数量推断 | 返回 |
| --- | ---: | --- | ---: | --- |
| `TC_Init_Environ` | `96` | `[ebp+08] / [ebp+0C] / [ebp+10] / [ebp+18] / [ebp+1C]` | 约 6 | `ret` |
| `TC_Login` | `768` | `[ebp+10] / [ebp+14]` | 至少 4 | 入口范围内出现异常 `ret_imm`，签名未定 |
| `TC_Login2` | `768` | `[ebp+10] / [ebp+14]` | 至少 4 | `ret` |
| `TC_GetLoginRet` | `64` | `[ebp+08]` | 1 | `ret` |
| `TC_GetRightInfo` | `112` | `[ebp+08] / [ebp+0C] / [ebp+10]` | 3 | `ret` |
| `TC_GetL2Info` | `160` | `[ebp+08] / [ebp+0C]` | 2 | `ret` |
| `TC_SetL2UserInfo` | `32` | `[ebp+08] / [ebp+0C] / [ebp+10]` | 3 | `ret` |
| `TC_Uninit` | `64` | 无显式外部参数引用 | 0 | `ret` |

其中最关键的是 `TC_SetL2UserInfo`：

```text
55 8b ec
8b 45 10 50
8b 4d 0c 51
8b 55 08 52
b9 10 c1 49 10
e8 87 d0 f8 ff
5d c3
```

这说明它是一个很薄的导出封装：

- 读取第 3 个参数并 `push`
- 读取第 2 个参数并 `push`
- 读取第 1 个参数并 `push`
- 设置一个固定对象地址或全局上下文到 `ecx`
- 调用内部实现
- 普通 `ret`

因此 `TC_SetL2UserInfo` 的 3 参数结论比上一轮更扎实。

`TC_GetL2Info` 的入口范围内明确检查并读取两个外部参数，因此 2 参数结论也更稳。

### 12.3 当前可执行判断

当前可以继续推进，但推进方式应分两条：

1. 静态线：继续从 `tc.dll` 内部实现函数 `RVA 0x32C20` 附近追踪三个参数如何落入字段名或内部状态。
2. 动态线：准备 32 位 Python 或 32 位 helper，只做 `LoadLibrary + GetProcAddress`，先不调用 `TC_Login / TC_SetL2UserInfo`。

仍然不能做的事：

- 不能在当前 64 位 Python 中直接调用 `tc.dll`。
- 不能把账号密码直接传给 `TC_SetL2UserInfo`，因为它三个参数的含义仍未确认。
- 不能把 `TC_SetL2UserInfo` 成功定位等同于十档行情已打通。

更准确的当前状态是：

- 前置权限同步入口已经定位到 `tc.dll`。
- `TC_SetL2UserInfo` 和 `TC_GetL2Info` 的参数数量已基本确认。
- 真正的 L2 登录参数来源仍在 `tpbus.dll -> TC_Login/TC_Login2 -> TC_GetLoginRet/TC_GetRightInfo` 链路中。

### 12.3A `x86 helper` 最小验证已经跑通

本轮新增工程：

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

验证结果：

- helper 真实运行在 `X86 / 32-bit` 进程中；
- `tc.dll` 与 `TDXDeep.dll` 都已实际加载成功；
- `TC_Init_Environ / TC_GetL2Info / TC_SetL2UserInfo / TdxDeep_StartInit` 等目标导出函数都已真实解析。

这说明当前已经不再卡在“64 位 Python 不能直接调 32 位 DLL”的入口级阻塞上。

### 12.4 `TC_SetL2UserInfo` 内部实现下探

`TC_SetL2UserInfo` 导出函数调用的内部实现为：

```text
tc.dll RVA 0x32C20
```

入口机器码摘要：

```text
55 8b ec 51
89 4d fc
8b 45 fc
83 b8 e0 00 00 00 00
74 21
8b 4d 10 51
8b 55 0c 52
8b 45 08 50
8b 4d fc
8b 89 e0 00 00 00
e8 e3 36 ff ff
b8 01 00 00 00
eb 02
33 c0
8b e5
5d
c2 0c 00
```

可读成：

```text
this = ecx
if this->field_0xE0 == null:
    return 0
push arg3
push arg2
push arg1
target = this->field_0xE0
call internal target handler
return 1
```

这一层进一步说明：

- `TC_SetL2UserInfo` 本身不是登录实现。
- 它是导出层到 TC 内部对象的转发入口。
- 真正保存或处理 L2 用户信息的对象挂在固定上下文的 `+0xE0`。
- 3 个参数仍然需要从上游 `tdxw.exe / tpbus.dll / tc.dll` 调用点确认含义。

这也解释了为什么只把账号密码填入 bridge 不会自动成功：

- 需要先让 `tc.dll` 的内部上下文完成初始化。
- 需要确保 `field_0xE0` 对象存在。
- 需要传入的是官方登录/SSO链路产生的 L2 权限态，而不一定是裸账号密码。

### 12.5 `TC_GetL2Info` 内部入口线索

`TC_GetL2Info` 导出函数核心调用落到：

```text
tc.dll RVA 0x33E60
```

该入口明确引用：

```text
[ebp+08]
[ebp+0C]
```

并有较大的局部栈空间，疑似把内部 L2 状态格式化或复制到调用方输出结构。

当前更合理的动态验证顺序因此变成：

1. 32 位运行环境中加载 `tc.dll`。
2. 调用 `TC_Init_Environ` 建立 TC 上下文。
3. 验证 `TC_GetL2Info` 在未登录状态下是否稳定返回空/失败。
4. 通过 `TC_Login / TC_Login2` 或官方上游链路拿到 `LoginRet / RightInfo`。
5. 只在确认参数含义后调用 `TC_SetL2UserInfo`。
6. 再次调用 `TC_GetL2Info` 验证 L2 权限态是否变化。

现阶段仍不建议跳过初始化直接调用 `TC_SetL2UserInfo`，因为内部实现依赖 `this->field_0xE0` 已存在。

新增收敛判断：

- 第一批 helper 自动调用只应做到：`LoadLibrary/GetProcAddress -> TC_Init_Environ -> TC_GetL2Info`。
- `TC_SetL2UserInfo` 和 `TdxDeep_StartInit` 都不应进入第一批自动调用。
- `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo` 这条官方权限来源链仍然必须补上。

## 13. 当前验收口径修正

2026-04-26 口径修正：

- `7709 / L1 + 五档 + WebSocket` 是过渡可用能力，不是最终验收。
- 最初优化目标仍然是 `L2 十档行情 + 分笔`。
- 当前未能验收的根因是尚未找到并跑通真实 L2 鉴权 / 权限同步入口。
- 文档更新必须跟随技术验证推进，不能把“探索记录完整”当作项目完成。

后续只有满足以下条件，才可以认为《通达信 L2 十档实时行情重构计划》进入验收：

1. 真实 L2 权限态来源已确认，至少能解释 `L2ZH / L2Right / QSID / Token` 中哪些字段进入 `TC_SetL2UserInfo`。
2. `TC_GetL2Info` 能在隔离环境中读出可解释的 L2 权限态。
3. `TDXDeep.dll / QSTP / 7719` 能在该权限态下返回真实十档盘口。
4. 分笔或逐笔数据能被稳定批量取回，并可映射到 `ticks_batch`。
5. bridge 接入不破坏现有热榜池订阅、WebSocket 主链路、HTTP fallback 和快照边界。

## 14. 2026-04-26 `tdxw.exe` xref 下探

本轮继续寻找真实鉴权入口，不调用 DLL、不写账号、不修改客户端文件。

新增静态 xref 探针：

```text
python-bridge/research/tdx_l2_xref_probe.py
```

执行命令：

```powershell
python python-bridge\research\tdx_l2_xref_probe.py --tdx-root D:\APP_SOFT\TDX --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_xref_probe.json
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_xref_probe.json
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_callsite_probe.json
```

### 14.1 `TC_SetL2UserInfo` 官方调用点

此前已经确认：

- `tc.dll` 明确导出 `TC_SetL2UserInfo`。
- `TC_SetL2UserInfo` 导出层是 3 参数薄封装。
- 内部实现依赖 TC 上下文中的 L2 子对象。

本轮新增确认：

| 项 | 结果 |
| --- | --- |
| `tdxw.exe` 中导出名字符串 RVA | `0x00861454` |
| 动态解析代码 RVA | `0x00321C52` 附近 |
| 解析后函数指针槽 | `VA 0x01227E20` |
| 明确间接调用点 | `tdxw.exe RVA 0x003221D1` |
| 调用后清栈 | `0x0C` |

`0x0C` 清栈与此前 `tc.dll` 入口机器码的 3 参数结论一致。

这使 `TC_SetL2UserInfo` 从“可能的权限入口”进一步升级为：

- 官方客户端确实动态解析该函数。
- 官方客户端确实存在调用该函数的代码路径。
- 该路径仍符合 3 参数调用形态。

但仍需强调：

- 3 个参数的语义尚未确认。
- 不能直接假设为 `账号 / 密码 / Token`。
- 该调用点附近存在局部字符串构造和格式化行为，下一步要追 `RVA 0x003221D1` 前的 3 个实参来源。

### 14.2 `TDXDeep.dll` 初始化入口调用点

本轮还确认 `tdxw.exe` 对 `TDXDeep.dll` 的导出函数做了同样的动态解析：

| 导出函数 | 函数指针槽 | 明确调用点 | 清栈量 | 静态参数量线索 |
| --- | --- | --- | --- | --- |
| `TdxDeep_StartInit` | `VA 0x012285C8` | `RVA 0x00325731` | `0x1C` | 约 7 参数 |
| `TdxDeep_RegisterCallBackFunc` | `VA 0x012285CC` | `RVA 0x00325759` | `0x0C` | 约 3 参数 |
| `TdxDeep_Data` | `VA 0x012285D8` | 暂未确认直接业务调用 | - | 待追 |
| `TdxDeep_Func` | `VA 0x012285D4` | 暂未确认直接业务调用 | - | 待追 |
| `TdxDeep_Uninit` | `VA 0x012285DC` | `RVA 0x00322F2B` | 未完整确认 | 待追 |

`TdxDeep_StartInit` 不是简单无参初始化。它的约 7 参数调用点说明深度行情 DLL 初始化大概率需要一组运行时上下文，例如窗口句柄、路径、回调、配置、权限态或主站材料。具体参数语义仍需继续静态下探。

### 14.3 当前收敛方向

下一步优先级更新为：

1. 以 `tdxw.exe RVA 0x003221D1` 为起点，反推 `TC_SetL2UserInfo` 三个实参来源。
2. 以 `tdxw.exe RVA 0x00325731` 为起点，反推 `TdxDeep_StartInit` 七个实参来源。
3. 判断 `TC_SetL2UserInfo` 是否必须先于 `TdxDeep_StartInit`，以及二者是否共享 `L2ZH / L2Right / QSID / Token / RightInfo`。
4. 只有确认权限态来源和初始化顺序后，再进入 32 位 helper 或隔离 DLL 调用试验。

## 15. 2026-04-26 调用点参数形态下探

本轮新增只读脚本：

```text
python-bridge/research/tdx_l2_callsite_probe.py
```

执行命令：

```powershell
python python-bridge\research\tdx_l2_callsite_probe.py --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_callsite_probe.json
```

### 15.1 `TC_SetL2UserInfo` 调用前的参数形态

当前静态下探到的调用前序列：

```text
mov esi, "CITICS"
push esi
lea edx, [ebp-0x28]
push "%s#CFV"
push edx
call mfc100.dll ordinal 4283
add esp, 0x0c
push 0x00C1C58C
mov ecx, 0x011D4FEC
call mfc100.dll ordinal 1448
push eax
lea ecx, [ebp-0x28]
call mfc100.dll ordinal 1448
push eax
call [TC_SetL2UserInfo slot]
add esp, 0x0c
```

当前含义判断：

- 调用前明确出现券商标识 `"CITICS"`。
- 本地缓冲通过 `"%s#CFV"` 模式构造，说明至少有一个参数更像券商/L2 通道标识串，而不是裸账号密码。
- `TC_SetL2UserInfo` 的 3 参数里，至少有 2 个来自 MFC helper 返回值，说明它更像接收已组装好的字符串或对象导出结果。
- `0x00C1C58C` 指向的内容目前解出为普通中文提示文案，不像直接的 L2 账号或 Token，因此更可能是 MFC helper 的上下文参数，而不是最终传给 `TC_SetL2UserInfo` 的业务权限串。

### 15.2 `TdxDeep_StartInit` 调用前的参数形态

当前静态下探到的调用前序列：

```text
push "connect.cfg"
lea eax, [ebp-0x10]
push 0x011D4340
push eax
call local helper
add esp, 0x0c
movzx ecx, byte ptr [0x00E7F11B]
mov edx, dword ptr [0x010FCF54]
push 0
push 0x00E75858
push ecx
push edx
mov ecx, eax
call mfc100.dll ordinal 1448
push eax
mov ecx, 0x011D41E0
call mfc100.dll ordinal 1448
push eax
mov ecx, 0x011D4340
call mfc100.dll ordinal 1448
push eax
call [TdxDeep_StartInit slot]
add esp, 0x1c
```

当前含义判断：

- `TdxDeep_StartInit` 现场明确使用 `connect.cfg`，说明它至少依赖配置材料。
- 其中一个 `.data` 参数 `0x010FCF54` 更像静态表项，不像直接的账号密码或 Token。
- 因此 `TdxDeep_StartInit` 当前更像深度行情引擎初始化入口，而不是最前置的权限同步入口。

### 15.3 当前阶段判断更新

截至本轮，更合理的顺序判断是：

1. `tpbus.dll / tc.dll` 侧先形成登录结果和权限态。
2. `TC_SetL2UserInfo` 用已经组装好的券商/L2 标识串与权限相关结果做同步。
3. `TdxDeep_StartInit` 在权限态已经具备后，启动深度行情引擎并消费配置/上下文。

因此下一步应继续优先追 `TC_SetL2UserInfo` 三个实参的最终来源，不应把主力放在 `TdxDeep_StartInit` 七个参数的完全还原上。

## 16. 2026-04-26 全局对象 xref 下探

本轮新增只读脚本：

```text
python-bridge/research/tdx_l2_object_xref_probe.py
```

执行命令：

```powershell
python python-bridge\research\tdx_l2_object_xref_probe.py --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_object_xref_probe.json
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_object_xref_probe.json
```

### 16.1 `0x011D4FEC` 的关键连接

`TC_SetL2UserInfo` 调用点里出现的 `0x011D4FEC` 不是 L2 专属对象，而是一个被多处复用的 MFC 字符串/上下文对象。但本轮 xref 发现它在三个 L2 相关窗口里同时出现：

| RVA | 命中线索 | 判断 |
| --- | --- | --- |
| `0x001D4FA1` | `##L2ZH## / ##localjointoken## / ##secumobileno##` | L2 用户标识和本地 token 模板替换 |
| `0x003221BA` | `CITICS / %s#CFV` | `TC_SetL2UserInfo` 调用前的券商/L2 标识构造 |
| `0x00510833` | `SSOMode 13/15 / QSID / L2ZH / L2Right / SSO.applysso / JSSO.applysso` | SSO/JSSO 权限 JSON 构造 |

其中 `RVA 0x00510833` 附近可见两条核心模板：

```text
[{"TDXID":"%s","ZHLB":"99","SSOMode":15,"SysSource":"%s","invalidTime":"%d","chanelType":"tdx","l2FunctionFlag":"1","QSID":"999","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
[{"TDXID":"%s","ZHLB":"99","SSOMode":13,"SysSource":"%s","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
```

这把当前链路从“`TC_SetL2UserInfo` 附近有 CITICS 字符串”推进到：

```text
SSO/JSSO.applysso
  -> 组装 L2ZH / L2Right / QSID 权限 JSON
  -> 复用 0x011D4FEC 相关字符串对象 / helper
  -> 构造 CITICS / %s#CFV 形式的券商或 L2 通道标识
  -> 调用 TC_SetL2UserInfo 三参数入口
```

### 16.2 `TdxDeep_StartInit` 相关对象判断

`TdxDeep_StartInit` 使用的 `0x011D41E0 / 0x011D4340 / 0x010FCF54 / 0x00E7F11B` 在 xref 中大量命中 `connect.cfg`、`PrimaryTPHost`、`L2PrimaryHost`、代理、站点和配置读取逻辑。

当前判断：

- 这些对象更像通用配置、主站和运行时上下文材料。
- 它们支持 `TdxDeep_StartInit` 是深度行情引擎初始化入口。
- 它们目前不如 `0x011D4FEC -> SSO/JSSO -> TC_SetL2UserInfo` 这条线更接近鉴权核心。

### 16.3 下一步优先级

下一步应继续以 `RVA 0x00510833` 的 SSO/JSSO 权限 JSON 构造点为中心，追：

1. `L2ZH` 和 `L2Right` 两个模板参数来自哪里。
2. `QSID` 为什么在模板中固定为 `"999"`，是否后续被替换或只用于特定 SSO 模式。
3. `SSO.applysso / JSSO.applysso` 返回值是否进入 `Local.GetLoginRetInfo`、`TC_GetRightInfo` 或 `TC_SetL2UserInfo`。
4. `CITICS/%s#CFV` 构造出的字符串在 `TC_SetL2UserInfo` 的 3 个参数中对应第几个参数。

## 17. 2026-04-26 `TP_Check_GTJAL2 / TPL2_Check` 函数体锚定

本轮新增只读脚本：

```text
python-bridge/research/tdx_l2_tpcheck_probe.py
```

执行命令：

```powershell
python python-bridge\research\tdx_l2_tpcheck_probe.py --output python-bridge\research\out\APP_SOFT_TDX\tdx_l2_tpcheck_probe.json
```

输出：

```text
python-bridge/research/out/APP_SOFT_TDX/tdx_l2_tpcheck_probe.json
```

该脚本不加载 DLL，只在 `tdxw.exe` 里根据字符串 VA 反查 `.text` 引用，并扫描 `call rel32` 直接调用者。

### 17.1 `TP_Check_GTJAL2` 入口与唯一直接调用者

当前可复现结果：

| 项 | RVA | 说明 |
| --- | --- | --- |
| `TP_Check_GTJAL2` 函数体锚点 | `0x00511F10` | 以 `Start TP_Check_GTJAL2` 和返回日志所在函数体为锚 |
| 唯一直接调用者 | `0x00383BE5` | `call rel32 -> 0x00511F10` |

`RVA 0x00383BE5` 调用前可见 5 个栈压入线索：

```text
push 0xFE
push esi
push eax
push ecx
push esi
call 0x00511F10
```

这里不能简单把它等同为 5 个业务参数，因为调用前窗口里可能混有上游 helper 的参数和寄存器临时值；但它确认了 `0x00383BE5 -> 0x00511F10` 是真实代码调用链，而不是单纯字符串邻近。

### 17.2 `0x00511F10` 函数体内部 L2 线索

`tdx_l2_tpcheck_probe.json` 中同一函数体附近的字符串引用集中如下：

| 引用 RVA | 字符串 / 线索 | 判断 |
| --- | --- | --- |
| `0x00511F6C` | `Start TP_Check_GTJAL2: %s,%s,%s` | 函数启动日志，支持 3 个文本形态入参或上下文值 |
| `0x0051204F` | `TP_Check_GTJAL2 return,SyncMode=%d,code=%d,ans: %s` | 返回码、同步模式和响应文本日志 |
| `0x00512133` | `RightInfo` | 解析登录或权限返回中的权限字段 |
| `0x005121F0` | `L2ZH` | 从权限返回或 JSON 中提取 Level2 账号/标识 |
| `0x005129F3` | `Local.GetLoginRetInfo` / `TdxW_GetLoginRetInfo` | 本地登录返回查询分支 |
| `0x00512B1C` | `RightInfo` | `TPL2_Check` 前继续处理权限字段 |
| `0x00512B76` | `L2ZH` | `TPL2_Check` 分支中的 Level2 字段 |
| `0x00512C31` | `TPL2_Check` | 同一检查链路的另一阶段 |
| `0x0051273F` | `TPL2_Check Sync OK!` | 权限同步成功日志 |

这说明 `TP_Check_GTJAL2` 不是普通日志点，而是一个同时覆盖：

- 请求启动日志
- 返回码和响应文本
- `RightInfo / L2ZH` 字段解析
- `Local.GetLoginRetInfo / TdxW_GetLoginRetInfo`
- `TPL2_Check` 同步检查

的 L2 权限检查函数体。

### 17.3 与 `SSO/JSSO` 和 `TC_SetL2UserInfo` 的关系

结合前两轮证据，当前更完整的候选链路是：

```text
RVA 0x00510833
  SSO/JSSO.applysso
  -> 组装 L2ZH / L2Right / QSID 权限 JSON

RVA 0x00511F10
  TP_Check_GTJAL2
  -> Start TP_Check_GTJAL2: %s,%s,%s
  -> Local.GetLoginRetInfo / TdxW_GetLoginRetInfo
  -> RightInfo / L2ZH
  -> TPL2_Check / TPL2_Check Sync OK!

RVA 0x003221D1
  TC_SetL2UserInfo
  -> CITICS / %s#CFV
  -> 3 参数权限同步入口
```

当前推断更新：

- `RVA 0x00510833` 更像 SSO/JSSO 权限请求或权限 JSON 构造点。
- `RVA 0x00511F10` 更像 L2 权限结果检查和同步确认点。
- `RVA 0x003221D1` 更像把已形成的权限态写入 `tc.dll` 的同步入口。
- `TdxDeep_StartInit RVA 0x00325731` 仍更像后续深度行情引擎初始化，而不是最前置鉴权入口。

### 17.4 入口再压缩

进一步把“入口”压到函数级别后，当前可以新增两组更窄的 worker 结论。

`tpbus.dll` 侧：

```text
sub_100F0C20
  -> sub_100EF760
  -> sub_100F028D
```

- `sub_100EF760` 命中固定 `SSOMode=2`、`Token`、`InputQSID`、`InputZHLB=340`。
- `sub_100F028D` 命中 `Token`、`AuthInfo`、`m_nSSOMode`、`InputQSID`、`YYB`。
- `sub_100F0C20` 是上面两支的共享分发函数；当前已发现两个明确直接调用点：`RVA 0x00107B08` 和 `RVA 0x001091CD`。

因此，如果要问“`tpbus.dll/LoginProcess.cpp` 里最小的共享请求组装入口是谁”，当前答案已经可以收敛到：

```text
tpbus.dll sub_100F0C20
```

`tdxw.exe` 侧：

```text
sub_00510740
  -> SSO.applysso / JSSO.applysso
  -> L2ZH / L2Right / TdxWL2

sub_007012B0
  -> tc.JSSO:applysso|%s
  -> [{"SSOMode":"396","Token":"%s_%s","invalidTime":"%d"}]
  -> ReqLscjmxTdxSSO,TQLName=%s,TQLParam=%s
  -> ReqLscjmxTdxSSO,ans=%s
```

- `sub_00510740` 是 `SSO/JSSO.applysso + L2ZH/L2Right` 那条权限 JSON 组装 worker。
- `sub_007012B0` 是更窄的 `ReqLscjmxTdxSSO / tc.JSSO:applysso|%s` worker。

因此，如果要问“当前最像真正 L2 applysso 发起点的最小核心函数是谁”，当前答案应改成：

```text
tdxw.exe sub_007012B0
```

### 17.5 下一步

下一步静态优先级调整为：

1. 展开 `RVA 0x00383BE5` 所在上游函数，确认它是否由登录完成、SSO 返回或菜单/初始化流程触发。
2. 反推 `RVA 0x00511F10` 内部 `RightInfo / L2ZH` 的解析结果是否写入 `0x011D4FEC` 或流向 `TC_SetL2UserInfo` 调用现场。
3. 继续确认 `TC_SetL2UserInfo` 三个实参中哪个对应 `CITICS/%s#CFV`，哪个对应 `L2ZH/L2Right/RightInfo` 派生结果。
4. 只有这些字段来源能闭环后，再进入 32 位 helper 的隔离加载或最小调用试验。

### 17.6 2026-04-26 合并验证结果

这一轮把上面的 3 个下一步合并成了一次连续验证，结论如下。

#### 17.6.1 `sub_007012B0` 的参数框架

`tdxw.exe sub_007012B0` 已确认不是 2~3 参数小函数，而是：

```text
thiscall ecx=this
9 个显式栈参
ret 0x24
```

当前 4 个直接调用点：

| 调用点 RVA | 结论 |
| --- | --- |
| `0x007019A1` | 函数内部递归/转发，固定压入 `arg1=1`，把当前上下文重新封装后再次调用自己。 |
| `0x00702ED8` | 当前最重要的真实鉴权调用点，固定压入 `arg1=0`，随后进入 `tc.JSSO:applysso|%s` / `ReqLscjmxTdxSSO` 分支。 |
| `0x0070344E` | 另一条 `arg1=0` 分支，参数里大量为 `0/空串`，更像兜底或轻量请求。 |
| `0x0070385B` | `arg1=1` 分支，压入一组本地结果缓冲区/字段指针，明显是响应或后处理路径。 |

对主调用点 `RVA 0x00702ED8`，压栈顺序已经明确：

```text
push eax      ; 来自 [esi+edx] 的格式化结果
push eax      ; dword ptr [esi]
push ebx
push ecx      ; [ebp-0x100]
push edi      ; [esi+0x43d]
push edx      ; byte ptr [eax+0x118]
push eax      ; [ebp-0xf0]
call mfc helper
push eax      ; helper 返回字符串
push 0
mov ecx, [ebp-0xec]
call sub_007012B0
```

因此 `sub_007012B0` 的业务语义应理解为：

- `arg1`：操作模式；`0` 对应 `ReqLscjmxTdxSSO` 鉴权发起，`1` 对应结果/后处理分支。
- `arg2`：进入 `tc.JSSO:applysso|%s` 和 `Token="%s_%s"` 的主字符串。
- `arg3~arg9`：由上游行情/券商上下文对象和局部缓冲区组成，按不同 `arg1` 分支复用，不是单纯账号密码。

也就是说，`sub_007012B0` 不是“账号/密码/Token”式简单入口，而是一个带模式位的 L2 SSO worker。

#### 17.6.2 `0x011CE734 / 0x011CE738` 的真实角色

之前这两个全局只知道和 `SSO/JSSO` 靠得很近；本轮通过它们的 getter 调用点把语义钉死了。

相关 getter：

- `RVA 0x005109E0`：读取 `0x011CE734`
- `RVA 0x00510AB0`：读取 `0x011CE738`

它们的 UI 调用现场分别挂在：

- `TP接入主站`
- `TPL2接入主站`

并且展示格式都是：

```text
%s:%d
```

因此这两个全局对象不是 `L2ZH / L2Right / Token` 字符串本身，而是：

| 全局地址 | 角色 |
| --- | --- |
| `0x011CE734` | `TP接入主站` 连接对象 |
| `0x011CE738` | `TPL2接入主站` 连接对象 |

这也解释了 `sub_00510740` 里的行为：

```text
根据 0x00E7F07E / 0x011CE7F8 选 TP 或 TPL2 主站对象
  -> 对该对象调用虚表 +0x18
  -> 发起 SSO.applysso / JSSO.applysso
```

所以这一步已经把“它们是不是权限态字段”的疑问排除了：不是，它们是承载请求发送的主站会话对象。

#### 17.6.3 `TP_Check_GTJAL2` 写入了哪些全局字段

对 `RVA 0x00511F10` 的解析窗口，当前已经能把 3 个关键字段与 3 个全局变量一一对应：

| 字段名 | 解析位置 | 写入目标 |
| --- | --- | --- |
| `RightInfo` | `0x00512132` 起 | `0x011BEE80` |
| `TDXID` | `0x00512192` 起 | `0x011CD740` |
| `L2ZH` | `0x005121EF` 起 | `0x011D4FEC` |

其中：

- `0x011BED6C` 的运行期内容已确认是固定 `SysSource="tdxlevel"`。
- `0x011BEE80` 会被拿去和 `"A"` / `"C"` 比较，符合权限串/RightInfo 的形态。
- `0x011D4FEC` 是活的全局 `CString`，当前运行时值已由只读探针确认存在。

这一步非常关键，因为它把此前“`0x011D4FEC` 更像 TDXID 还是 L2ZH”的歧义消掉了：

```text
0x011CD740 = TDXID
0x011D4FEC = L2ZH
0x011BEE80 = RightInfo / L2Right
```

#### 17.6.4 `sub_00510740` 的 JSON 占位符闭环

`sub_00510740` 里的两个核心模板现在可以按真实来源还原为：

```text
[{"TDXID":"%s","ZHLB":"99","SSOMode":15,"SysSource":"%s","invalidTime":"%d","chanelType":"tdx","l2FunctionFlag":"1","QSID":"999","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
[{"TDXID":"%s","ZHLB":"99","SSOMode":13,"SysSource":"%s","Reserve":{"L2ZH":"%s","L2Right":"%s"}}]
```

对应来源现在已经可以明确成：

| 占位符 | 来源 |
| --- | --- |
| `TDXID` | `0x011CD740` |
| `SysSource` | `0x011BED6C` = `tdxlevel` |
| `invalidTime` | 常量 `0x708` |
| `L2ZH` | `0x011D4FEC` |
| `L2Right` | `0x011BEE80` |

因此 `sub_00510740` 不只是“看起来像 JSON 组装”，而是已经可以按字段级闭环到：

```text
TP_Check_GTJAL2
  -> 解析 RightInfo / TDXID / L2ZH
  -> 写入 0x011BEE80 / 0x011CD740 / 0x011D4FEC
  -> sub_00510740 组装 SSO/JSSO.applysso JSON
  -> 选 TP / TPL2 主站对象发请求
```

#### 17.6.5 `TC_SetL2UserInfo` 的实参关系

`RVA 0x003221D1` 这条调用现场本轮也有了更明确的语义：

```text
mov esi, "CITICS"
...
push "%s#CFV"
...
mov ecx, 0x011D4FEC
call helper
push eax
lea ecx, [ebp-0x28]
call helper
push eax
call [TC_SetL2UserInfo slot]
add esp, 0x0c
```

结合 `0x011D4FEC = L2ZH` 这一新确认，可以把它改写成：

- `TC_SetL2UserInfo` 的 3 个参数里，**至少有 1 个明确就是 `L2ZH`**。
- 另一个明确参数来自 `CITICS + "%s#CFV"` 构造出的券商/营业部风格标识串。
- 剩下 1 个参数仍更像空串或保留位，不像裸密码。

这使 `TC_SetL2UserInfo` 的职责进一步收敛为：

```text
不是登录入口
而是把已经拿到的 L2 用户/券商权限态写入 tc.dll
```

#### 17.6.6 当前闭环结论

把这轮结果压缩后，现在可以把 L2 鉴权主链路写成：

```text
tpbus.dll sub_100F0C20
  -> 组装 Token / AuthInfo / SSOMode / InputQSID / YYB / PTYPE / PTOKEN

tdxw.exe sub_00511F10   (TP_Check_GTJAL2)
  -> 解析 RightInfo -> 0x011BEE80
  -> 解析 TDXID    -> 0x011CD740
  -> 解析 L2ZH     -> 0x011D4FEC

tdxw.exe sub_00510740
  -> 用上面 3 个字段组装 SSO.applysso / JSSO.applysso JSON
  -> 通过 0x011CE734 / 0x011CE738 主站对象发请求

tdxw.exe sub_007012B0
  -> 进入 tc.JSSO:applysso|%s
  -> 进入 ReqLscjmxTdxSSO
  -> 用 Token="%s_%s" + invalidTime 发起更窄的 L2 SSO 鉴权

tdxw.exe RVA 0x003221D1
  -> TC_SetL2UserInfo
  -> 把 L2ZH + 券商标识串 等权限态同步进 tc.dll
```

到这里，“入口函数定位”“上游字段来源”“下游写入点”三件事已经可以一起交代清楚。

## 18. 2026-04-26 helper 接入方向

并行评估结果表明，后续如果把 `x86 helper` 接到现有 bridge，最自然的位置不是替换 `mootdx`，而是作为 `TdxL2Bridge` 旁边的第二上游。

当前建议：

1. helper 生命周期挂在 `TdxL2Bridge.run()` / `main()`。
2. helper 健康状态并入 `heartbeat_loop()` 风格的状态上报。
3. 订阅池继续复用 `aggregate_pool()`。
4. helper 只负责回传十档/逐笔原始结果或标准化结果。
5. bridge 继续保留当前 `mootdx + 7709` 主链路，只把 helper 输出合并进 `depth_patch / ticks_batch`。

这样做的好处是：

- 不破坏当前生产链路；
- helper 可以独立开关、独立失败；
- 前端协议可以保持不变。

## 19. 2026-04-26 ConnectQSID 候选扩展

本轮没有继续扩大 `TC_Login` 参数矩阵的总规模，而是先把“券商分组”和“QSID 候选”两条线拆开。

新增工程动作：

- helper 现在会读取 `D:\APP_SOFT\TDX\connect.cfg`
- 把 `QSID=tdxlevel` 作为 `ConnectQSID` 材料接入 `LoadCachedLoginMaterials`
- 登录矩阵新增 profile：
  - `tdxid-token-connectqsid-oid`
  - `tdxid-session-connectqsid-oid`
  - `tdxid-token-connectqsid-reguid`
  - `tdxid-session-connectqsid-reguid`
- 对 `Embed_YybID=0` 增加过滤，避免把明显无效的营业部占位值继续送进矩阵
- `probe-tc-login-matrix` 报告新增：
  - `attempts[].signalHints`
  - `signalSummaries`

本轮实测：

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true -o .tmp\tdxhelper-connectqsid
.tmp\tdxhelper-connectqsid\TdxL2Helper.exe probe-tc-login-matrix --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout --buffer-size 4096
```

结果：

- 本轮完成 `32` 组尝试
- `ConnectQSID` 材料已进入报告
- 新增 `connectqsid` profile 已覆盖
- 本轮 `interestingAttempts = 0 / 32`
- `signalSummaries = []`

当前判断更新：

1. `JYMainQSID` 目前更像券商/分组名，不应继续被当成唯一 `InputQSID` 替身。
2. `connect.cfg:QSID=tdxlevel` 至少值得作为单独一条 `QSID` 候选轴保留。
3. 这轮没有新增信号，不说明 `ConnectQSID` 路线无效，只说明当前缓存态下还没压中更深的返回分支。
4. 后续应继续多轮复核，并优先观察 `signalHints / signalSummaries` 是否开始稳定聚集到某类 `loginRet / RightInfo` 文本。
