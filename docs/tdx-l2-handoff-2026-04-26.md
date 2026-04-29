# 通达信 L2 工程交接文档

更新时间：2026-04-26

## 1. 目的

这份文档用于在会话中断、或多人接力时，快速恢复《通达信 L2 十档实时行情重构计划》的真实进度。

重点不是重复背景，而是把下面四件事固定下来：

1. 现在已经落地了什么
2. 这些东西在哪些文件里
3. 已经做过哪些实机验证
4. 现在最应该继续做什么

---

## 2. 当前总状态

当前项目分成两条线：

1. 已稳定可用的过渡链路：
   `mootdx -> python-bridge -> websocket -> Vue`
   产出是 `7709 / L1 + 标准五档`
2. 正在继续攻关的最终链路：
   `tpbus.dll / tc.dll / TDXDeep.dll / 7719 / 真 L2 十档`

当前结论很明确：

- `7709 / 五档` 已经是生产可用链路，但不是最终验收结果。
- `7719 / 真 L2` 仍未打通。
- 最大进展已经从“静态猜测”推进到“独立 x86 宿主 + 官方 DLL 真实调用 + 登录参数矩阵探测”。

---

## 3. 已完成事项

### 3.1 WebSocket 实时主链路

已经完成：

- `python-bridge/main.py` 用 `mootdx` 拉标准行情
- 本地 WebSocket 广播
- 前端 `websocket.ts -> dataLoader.ts -> DataLayer.ts -> Vue UI` 接收实时数据
- HTTP fallback 保留
- 热榜池分批拉取、动态节流、优先级调度
- 右键详情面板展示盘口/逐笔占位

当前稳定事实：

- `7709` 可返回标准五档
- `7719` 可握手，但业务数据仍为空

### 3.2 x86 helper 基础能力

已经完成：

- 新增 `tools/TdxL2Helper`
- 真实发布 `win-x86` 可执行文件
- 以独立 `x86` 进程加载：
  - `tc.dll`
  - `TDXDeep.dll`
- 解析关键导出：
  - `TC_Init_Environ`
  - `TC_Login`
  - `TC_Login2`
  - `TC_GetLoginRet`
  - `TC_GetRightInfo`
  - `TC_GetL2Info`
  - `TC_SetL2UserInfo`
  - `TC_Uninit`

### 3.3 helper runtime 布局同步

已经确认：

- `tc.dll` 不是只看 `--tdx-root`
- 它还依赖 helper 可执行文件目录中的宿主资源：
  - `etrade.xmb`
  - `TcOem.xmb`
  - `TCPlugins\*.dll`
  - `Users\Profile`

已经实现：

- `sync-runtime-layout`
- `host-runtime` 启动前自动同步 runtime 布局

### 3.4 host-runtime 长驻宿主

已经完成：

- `host-runtime` 命令
- `--event-stream` NDJSON 事件流
- 事件顺序已成型：
  - `boot`
  - `modules`
  - `tc_init`
  - `probe_login_state`
  - `tc_login`
  - `post_login_state`
  - `getl2info`
  - `heartbeat`
  - `shutdown`

### 3.5 bridge 接 helper runtime

已经完成：

- `python-bridge/main.py` 可启动 helper 子进程
- 消费 helper NDJSON 事件流
- 把 runtime 状态挂到 websocket 输出里的 `l2.runtime`
- 具备 bounded restart/backoff

当前 bridge 暴露的 helper 关键信息包括：

- `pid`
- `processArchitecture`
- `runtimeLayout`
- `modules`
- `tcInit`
- `probeGetLoginRet`
- `probeGetRightInfo`
- `loginRequest`
- `loginResult`
- `postLoginGetLoginRet`
- `postLoginGetRightInfo`
- `lastGetL2Info`

### 3.6 登录矩阵探针

已经完成：

- `probe-tc-login-matrix`
- `probe-tc-login-attempt`
- 从本机 `T0002` 缓存读取登录材料
- 组合固定小矩阵，分别测试 `TC_Login / TC_Login2`
- 每个候选组合隔离到独立子进程，避免单次原生崩溃打断整轮探测

当前已使用的缓存材料来源：

- `D:\APP_SOFT\TDX\T0002\user.ini`
- `D:\APP_SOFT\TDX\T0002\usercomm.ini`
- `D:\APP_SOFT\TDX\T0002\datacache.json`
- `D:\APP_SOFT\TDX\T0002\hostip.ini`

当前重点候选字段：

- `TDXID`
- `TDXToken`
- `TPSession`
- `OID`
- `UserPUID`
- `RegUID`
- `JYMainQSID`
- `HostIP`
- `ConnectQSID`

### 3.7 自动缓存 profile 接入

已经完成：

- helper 支持 `--login-profile <name|auto>`
- `auto` 当前按下面顺序选 profile：
  1. `tdxid-token-userpuid-oid`
  2. `tdxid-token-connectqsid-oid`
  3. `tdxid-token-jymainqsid-oid`
  4. `tdxid-token-oid-reguid`
  5. `tdxid-token-reguid-empty`
  6. `tdxid-token-reguid-hostip`
- bridge 支持环境变量：
  - `TDX_L2_HELPER_LOGIN_PROFILE`

补充：

- helper 现在会额外读取 `D:\APP_SOFT\TDX\connect.cfg` 中的 `QSID=tdxlevel`
- 当前把这个值以 `ConnectQSID` 名义纳入矩阵，单独验证 “QSID 候选” 这一轴
- `JYMainQSID` 与 `ConnectQSID` 当前不应再混为同一个假设字段
- `probe-tc-login-matrix` 报告已新增：
  - `attempts[].signalHints`
  - `signalSummaries`

---

## 4. 关键文件

### 4.1 helper

- `tools/TdxL2Helper/Program.cs`
- `tools/TdxL2Helper/Program.SelfHost.cs`
- `tools/TdxL2Helper/TdxL2Helper.csproj`
- `tools/TdxL2Helper/README.md`

### 4.2 bridge

- `python-bridge/main.py`

### 4.3 主文档

- `docs/vue3-tdx-l2-python-realtime-solution.md`
- `docs/tdx-l2-phase2-exploration.md`
- `docs/tdx-l2-protocol-findings.md`
- `docs/tdx-l2-handoff-2026-04-26.md`

---

## 5. 已完成的实机验证

以下验证都已经实际跑过，不是纸面设计。

### 5.1 helper 编译与发布

成功执行：

```powershell
dotnet build tools\TdxL2Helper\TdxL2Helper.csproj -c Release
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true
```

说明：

- 正常发布目录有时会被运行中的旧 helper 进程锁住
- 临时验证可直接发到：
  - `.tmp\tdxhelper-login-matrix`
  - `.tmp\tdxhelper-login-profile`

### 5.2 helper 基线验证

成功执行：

```powershell
TdxL2Helper.exe probe-tc-baseline --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout
```

已确认：

- `processArchitecture = X86`
- `TC_Init_Environ returnValue = 1`
- `TC_GetL2Info returnValue = 1`

### 5.3 host-runtime 事件流验证

成功执行：

```powershell
TdxL2Helper.exe host-runtime --tdx-root D:\APP_SOFT\TDX --event-stream --sample-count 1 --heartbeat-interval-ms 200
```

已确认事件流顺序可用：

- `boot`
- `modules`
- `tc_init`
- `getl2info`
- `heartbeat`

### 5.4 probe-login-state 验证

成功执行：

```powershell
TdxL2Helper.exe host-runtime --tdx-root D:\APP_SOFT\TDX --event-stream --probe-login-state
```

已确认：

- `TC_GetLoginRet returnValue = 1`
- `TC_GetRightInfo returnValue = 1`
- 初始 buffer 多数仍为空

### 5.5 登录矩阵探测验证

成功执行：

```powershell
TdxL2Helper.exe probe-tc-login-matrix --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout --buffer-size 4096
```

当前稳定结论：

- 24 组候选矩阵已能完整跑完
- 崩溃组合只影响单个子进程，不再打断整轮探针
- 多轮复核中，真正反复出现信号的组合集中在：
  - `TDXID + TDXToken + UserPUID + OID`
  - `TDXID + TDXToken + JYMainQSID + OID`
  - `TDXID + TDXToken + OID + RegUID`
  - `TDXID + TDXToken + RegUID + <empty>`

### 5.6 当前最有价值的返回信号

多轮复核中，最常见的非空 `TC_GetLoginRet` 返回是：

```text
服务器分组未配置。
```

这条信号的含义：

- 不是“已经打通 L2”
- 但也不是“完全没进登录路径”
- 它说明 `TC_Login` 的部分参数已经碰到真实服务器分组/券商分组校验链路

当前尚未出现的信号：

- `TC_GetRightInfo` 明显非空
- `TC_GetL2Info` 明显非空
- 合法 `L2ZH / L2Right / QSID` 态

### 5.7 bridge helper runtime 验证

已验证：

- helper runtime 状态已经能通过 websocket heartbeat 暴露
- `l2.runtime` 中可看到：
  - helper `pid`
  - `X86`
  - `runtimeLayout`
  - `modules`
  - `tcInit`

### 5.8 2026-04-26 ConnectQSID 扩展验证

已验证：

- 新版 helper 已成功发布到：
  - `.tmp\tdxhelper-connectqsid`
- `probe-tc-login-matrix` 本轮实际完成 `32` 组尝试
- 新增 `ConnectQSID` profile 已进入矩阵：
  - `tdxid-token-connectqsid-oid`
  - `tdxid-session-connectqsid-oid`
  - `tdxid-token-connectqsid-reguid`
  - `tdxid-session-connectqsid-reguid`
- 报告中已出现：
  - `materials.entries[].key = ConnectQSID`
  - `attempts[].signalHints`
  - `signalSummaries`

本轮结果：

- `interestingAttempts = 0 / 32`
- `signalSummaries = []`

说明：

- 这次没有打出新的非空信号
- 但 helper 已具备单独验证 `QSID` 候选的能力
- 后续应继续多轮复核，而不是再把 `JYMainQSID` 单独当作唯一 QSID 代理

---

## 6. 当前最重要结论

### 6.1 已经排除的错误方向

以下方向现在不该再反复兜圈：

1. “是不是 64 位 Python 不能调 32 位 DLL”
   - 已解决，helper 已落地
2. “是不是只能停在静态分析”
   - 已经进入真实 DLL 调用和登录矩阵实测
3. “是不是随便填用户名密码就能打通 7719”
   - 不是

### 6.2 当前最可信的判断

当前更可信的判断是：

1. `TC_Login / TC_Login2` 的参数风格不是简单账号密码
2. 真实参数更像：
   - `TDXID`
   - `TDXToken`
   - `OID / UserPUID / RegUID / JYMainQSID / ConnectQSID`
3. 当前命中的报错“服务器分组未配置。”说明还差：
   - 券商分组
   - QSID
   - 或上游 `tpbus.dll` 组包里的某个分发字段

### 6.3 当前不能误判的点

这些都不能当作“已经完成”：

- `loginResult.returnValue = 0`
- `TC_GetLoginRet` 变成非空
- helper 能加载 `TDXDeep.dll`
- bridge 有 `l2.runtime`

真正的下一层验收必须是：

1. `TC_GetRightInfo` 出现稳定非空变化
2. `TC_GetL2Info` 出现稳定非空变化
3. 之后再进入 `TC_SetL2UserInfo`
4. 最后 `TdxDeep_StartInit / TdxDeep_Data` 回流真实深度数据

---

## 7. 当前推荐的继续顺序

### 第一步：继续压缩“服务器分组未配置。”

优先方向：

1. 把 `JYMainQSID / OID / UserPUID / RegUID / HostIP` 的组合继续缩小
   - 当前要把 `ConnectQSID` 单独并进这一轮，不要继续让 `JYMainQSID` 兼任 QSID 候选
2. 对照 `tpbus.dll` 文档线索里的：
   - `InputQSID`
   - `YYB`
   - `SSOMode`
   - `AuthInfo`
3. 确认当前命中的 profile 里，到底缺的是券商分组还是 QSID

### 第二步：让 host-runtime 长驻输出 post-login 状态

这一步已经完成一半：

- `post_login_state` 事件已加

后续要继续观察：

- `postLoginGetLoginRet`
- `postLoginGetRightInfo`

### 第三步：在拿到 RightInfo 之后再推进 SetL2

不要倒序做。当前顺序应保持：

1. `TC_Login / TC_Login2`
2. `TC_GetLoginRet / TC_GetRightInfo`
3. `TC_SetL2UserInfo`
4. `TC_GetL2Info`
5. `TdxDeep_StartInit`

### 第四步：bridge 侧只做承接，不做过度猜测

bridge 当前职责应该只是：

- 启动 helper
- 暴露 runtime 状态
- 记录 helper 事件

不要在 bridge 里硬编码更多业务推断。

---

## 8. 当前可直接复现的命令

### 8.1 编译

```powershell
dotnet build tools\TdxL2Helper\TdxL2Helper.csproj -c Release
python -m py_compile python-bridge\main.py
```

### 8.2 临时发布到不冲突目录

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true -o .tmp\tdxhelper-login-profile
```

### 8.3 跑登录矩阵

```powershell
.tmp\tdxhelper-login-profile\TdxL2Helper.exe probe-tc-login-matrix --tdx-root D:\APP_SOFT\TDX --sync-runtime-layout --buffer-size 4096
```

### 8.4 跑 host-runtime 自动 profile

```powershell
.tmp\tdxhelper-login-profile\TdxL2Helper.exe host-runtime --tdx-root D:\APP_SOFT\TDX --event-stream --probe-login-state --login-profile auto --sample-count 1 --heartbeat-interval-ms 200
```

### 8.5 跑 bridge 接 helper

示例环境变量：

```powershell
$env:TDX_L2_HELPER_ENABLED='1'
$env:TDX_L2_HELPER_EXE_PATH='D:\dragon-board\.tmp\tdxhelper-login-profile\TdxL2Helper.exe'
$env:TDX_L2_HELPER_TDX_ROOT='D:\APP_SOFT\TDX'
$env:TDX_L2_HELPER_PROBE_LOGIN_STATE='1'
$env:TDX_L2_HELPER_LOGIN_PROFILE='auto'
$env:TDX_L2_HELPER_LOGIN_FUNCTION='login'
python python-bridge\main.py
```

---

## 9. 当前已知风险

1. 原生调用仍可能 `0xC0000005`
   - 已通过“每组组合一个子进程”隔离
2. 登录矩阵结果存在波动
   - 所以必须看多轮复核，不看单次命中
3. `loginReturn = 0` 与 buffer 空之间并不矛盾
   - 当前 DLL 语义不能按常规 HTTP 登录接口理解
4. 正常 publish 目录可能被旧 helper 进程锁住
   - 临时验证时优先发到 `.tmp\...`

---

## 10. 如果会话中断，下一任继续做什么

直接按下面顺序继续：

1. 先读本文件
2. 再读：
   - `docs/tdx-l2-phase2-exploration.md`
   - `docs/tdx-l2-protocol-findings.md`
3. 跑：
   - `probe-tc-login-matrix`
   - `host-runtime --login-profile auto --probe-login-state --event-stream`
4. 优先追“服务器分组未配置。”与 `JYMainQSID / InputQSID / YYB / OID` 的关系
5. 只有当 `RightInfo / L2Info` 非空后，才进入 `TC_SetL2UserInfo`

这就是当前最短的继续路径。

# 附件：

# 通达信 L2 十档实时行情重构计划

## 摘要

- 本轮改造的根因固定为：现有 `腾讯/新浪/东财 HTTP 轮询` 延迟过高，盘中会出现“通达信已涨停，八合一仍显示几分钟前旧价”的问题；目标是改成 **`通达信 L2 + mootdx + Python 本地 WebSocket`** 的实时主链路。
- 主改造点仍然是 **`src/services/websocket.ts`**，但由于你已经确认要上 **十档行情**，本轮必须同步规划 `dataLoader / DataLayer / DataTable / snapshot` 的后续承接工作，避免只把数据拉进来却没有完整的内存管理、字段映射和存储方案。
- 订阅范围固定为：**仅八合一平台热榜股票池**，不订阅全市场。
- v1 实时能力固定为：**量价、涨跌、成交额、十档盘口、逐笔成交**。
- 存储策略固定为：**实时流常驻内存，持久化只在现有正式快照时点发生**；不把 100ms/逐笔流直接持续写入快照库。

## 关键改动

### 1. Python 中间层

- 新增独立 Python bridge，使用 `mootdx` 维护与通达信 L2 的长效 TCP 连接，固定 `100ms` 采集热榜池行情，固定 `5s` 心跳。
- Python 直接向浏览器暴露本地 WebSocket，不经过 Node 中转。
- 订阅集严格等于八合一热榜池；热榜池变化时，由前端重发订阅集。
- 下行协议固定为：
  - `full_state`：首次连接、重连成功、热榜池变更后下发当前热榜池全量基线数据。
  - `quote_patch`：量价、涨跌、成交额等基础行情增量。
  - `depth_patch`：十档盘口增量，字段标准化为 `bids[10] / asks[10]`。
  - `ticks_batch`：100ms 窗口内逐笔成交批量。
  - `heartbeat`：连接状态、订阅数、服务端时间。
- `full_state` 中包含基础行情 + 当前十档盘口，不包含无限制原始逐笔历史。

### 2. `websocket.ts` 作为实时主入口

- `src/services/websocket.ts` 重构为真实客户端，职责固定为：
  - 连接 Python WS
  - 发送热榜池订阅
  - 接收 `full_state / quote_patch / depth_patch / ticks_batch / heartbeat`
  - 自动重连、超时判 stale、切换 fallback
  - 维护本地 transport cache
  - 发出统一应用事件
- 内部缓存固定为：
  - `latestQuotesByCode`
  - `latestDepth10ByCode`
  - `recentTicksByCode`
  - `hotPoolCodes`
- `recentTicksByCode` 采用 ring buffer，默认保留 **最近 60 秒或最近 300 条**，二者先到上限即淘汰旧数据。
- 对外接口固定为：
  - `connect()`
  - `disconnect()`
  - `setHotPool(codes: string[])`
  - `getStatus()`
  - `getDepth10(code: string)`
  - `getRecentTicks(code: string)`
- 旧 AllTick 轮换语义全部移除，不再保留“5只订阅/45秒轮换/currentBatchIndex”。

### 3. `dataLoader` 与 `DataLayer` 的承接边界

- `dataLoader` 继续负责八合一热榜加载和订阅池同步，不负责网络连接细节。
- `dataLoader` 在首屏完成热榜加载和后续热榜刷新完成后，统一调用 `webSocketService.setHotPool(codes)`。
- `dataLoader` 监听 WebSocket 事件并负责字段映射：
  - `quote_patch` -> 表格基础行情字段
  - `depth_patch` -> 十档盘口结构与衍生指标
  - `ticks_batch` -> 逐笔缓存与聚合摘要
- `DataLayer` 本轮仍然**不承担任何联网逻辑**，但需要承接内存层数据模型扩展，成为最新 L2 状态的内存权威层。
- `DataLayer` 新增内存结构，不新增连接职责：
  - `realtime.quotes`
  - `realtime.depth10`
  - `realtime.recentTicks`
  - `realtime.l2Summary`
- `DataLayer` 存储策略固定为：
  - 基础行情：保存最新一份
  - 十档盘口：每只股票只保存最新一份
  - 逐笔成交：每只股票保存有限 ring buffer
  - 派生指标：保存最新计算结果
- `DataLayer` 对 `merged.stocks` 只同步写入表格真正需要的字段，不把整套十档数组平铺到每一行股票对象上。

### 4. 字段映射与 DataTable 展示

- 十档原始结构统一标准化为：
  - `bids: [{ price, volume }, ... x10]`
  - `asks: [{ price, volume }, ... x10]`
- `DataTable` 本轮不直接渲染 20 档完整盘口，而是消费 `DataLayer` 里的 L2 摘要字段：
  - `bid1Price`
  - `bid1Volume`
  - `ask1Price`
  - `ask1Volume`
  - `spread`
  - `bid10Total`
  - `ask10Total`
  - `depthImbalance`
  - `tickBuyVolume`
  - `tickSellVolume`
- 十档完整盘口和逐笔明细不放进大表常规列，统一作为：
  - 详情面板数据源
  - tooltip / side panel 数据源
  - 后续复盘或盘口分析模块数据源
- 基础行情字段仍沿用现有股票对象字段：
  - `price`
  - `change`
  - `volume`
  - `turnover`
  - `turnoverRate`
  - `updatedAt`

### 5. 快照存储与后续复盘

- 不把 100ms `quote_patch / depth_patch / ticks_batch` 持续写入快照库，否则会造成写放大和存储失控。
- 持久化策略固定为：**只在现有正式快照时点 / 手工快照时点**，把当时最新 L2 状态投影进快照。
- 快照中新增的持久化内容固定为：
  - 最新基础行情字段
  - 最新十档盘口压缩结构
  - 最新盘口摘要字段
  - 最近一小段逐笔聚合摘要
- 逐笔持久化范围固定为“聚合摘要”，不存全量逐笔原始流；默认保存：
  - `tickBuyVolume`
  - `tickSellVolume`
  - `tickBuyCount`
  - `tickSellCount`
  - `lastTradePrice`
  - `lastTradeVolume`
- 正式快照读取后，可以复原：
  - 当时的基础量价状态
  - 当时的十档盘口结构
  - 当时的逐笔交易强弱摘要
- 不能复原正式快照之间每个 100ms 的完整逐笔流，这是本轮有意选择的边界。

## 接口与类型

- Python -> 前端消息类型：
  - `full_state`
  - `quote_patch`
  - `depth_patch`
  - `ticks_batch`
  - `heartbeat`
- 前端核心类型固定新增：
  - `QuotePatch`
  - `DepthLevel`
  - `Depth10Book`
  - `TickTrade`
  - `L2Summary`
  - `RealtimeStreamStatus`
- `L2Summary` 固定包含：
  - `bid1Price`
  - `bid1Volume`
  - `ask1Price`
  - `ask1Volume`
  - `spread`
  - `bid10Total`
  - `ask10Total`
  - `depthImbalance`
  - `tickBuyVolume`
  - `tickSellVolume`
- 应用事件固定为：
  - `WEBSOCKET.STATUS_CHANGED`
  - `WEBSOCKET.FULL_STATE`
  - `WEBSOCKET.QUOTE_PATCH`
  - `WEBSOCKET.DEPTH_PATCH`
  - `WEBSOCKET.TICKS_BATCH`
  - `WEBSOCKET.HEARTBEAT`

## 测试与验收

- 实时性：
  - 盘中样本股在通达信软件价格变化后，前端表格在 `100~300ms` 内同步更新。
  - 涨停、炸板、盘口快速撤单等场景不再出现“几分钟旧价”。
- 十档正确性：
  - 至少选 3 只热榜股，对比通达信客户端十档盘口，价格档位与数量一致。
- 逐笔正确性：
  - `ticks_batch` 到达后，最近成交方向、价格、数量与通达信客户端一致。
- 热榜池订阅：
  - 订阅数始终等于八合一热榜池去重结果，不会扩展到全市场。
  - 热榜池变更后，WebSocket 收到新的 `full_state` 并完成对齐。
- 内存稳定性：
  - 300 只热榜股连续运行 2 小时，内存占用稳定，无逐笔缓存无限增长。
- 快照存储：
  - 正式快照记录中可读到基础行情、十档盘口和逐笔摘要。
  - 快照写入频率仍与原正式快照机制一致，不出现 100ms 高频持久化。
- 降级链路：
  - Python bridge 中断后，前端在 `2s` 左右进入 HTTP fallback。
  - Python 恢复后自动切回 WebSocket 主链路。

## 假设与默认值

- 不能再假设 `mootdx` 已经能取到真十档、真逐笔或 `L2_AMO` 分档资金。当前 `mootdx + 7709` 只作为标准行情过渡链路。
- 当前资金字段如果标记为 `moneyFlowSource = tdx_estimate`，属于基于总主动买卖量、OHLC、成交额等字段的估算，不是通达信 `L2_AMO` 正式口径。
- 通达信主力资金完全对齐需要真实 L2 数据面：至少要拿到 `L2_AMO(0..3, 0..3)` 等价分档成交金额，或可还原该分档的完整逐笔/逐单明细。十档盘口深度本身不等于 `L2_AMO`。
- 真正验收仍然取决于 `TC_GetL2Info / TDXDeep_StartInit / TdxDeep_Data / TdxDeep_Func / callback` 能否返回可验证的 `7719 / QSTP / TDXDeep` 业务数据。
- 八合一热榜池规模按 `200~300` 只设计。
- 本轮重点依然是 `websocket.ts` 主链路重建；`dataLoader / DataLayer / DataTable / snapshot` 的改动仅用于承接十档与逐笔数据，不改变它们的根本职责边界。
- 正式快照持久化的是“当时最新状态”和“逐笔摘要”，不是全量逐笔历史回放数据。
