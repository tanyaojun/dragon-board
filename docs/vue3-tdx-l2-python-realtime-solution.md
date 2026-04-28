# Vue3 + 通达信实时行情 + Python Bridge 整体落地方案（第二阶段）

更新时间：2026-04-26

详细工程交接、实机验证结果和后续继续顺序见：

- `docs/tdx-l2-handoff-2026-04-26.md`

## 1. 当前结论

这轮改造的核心目标已经明确：

- 旧主链路 `腾讯 / 新浪 / 东财 HTTP 轮询 -> dataLoader` 延迟过高，盘中会出现明显旧价。
- 新主链路已经切为 `mootdx -> python-bridge -> websocket.ts -> dataLoader -> DataLayer -> Vue UI`。
- 当前**稳定可用**的是 `7709 / L1 + 标准五档 + 本地 WebSocket`。
- 当前**尚未打通**的是 `7719 / 真 L2 十档 / 真 L2 逐笔`。
- 热榜池实时拉取已经改为**分批拉取 + 动态节流**，不再追求“100ms 全池硬刷”。
- 当前进入第二阶段：目标不是停留在技术探索，而是继续完成最初的《通达信 L2 十档实时行情重构计划》，找到并验证真实 `L2` 鉴权入口，最终打通 `7719 / 真 L2 十档 / 真 L2 分笔`。

因此本方案不再把“L2 十档已经落地”当成既成事实，而是分成两层：

1. 当前过渡可用的 `7709 / L1 + 五档` 实时主链路
2. 仍必须继续攻关并作为最终验收目标的 `7719 / 真 L2 十档 / 真 L2 分笔` 链路

---

## 2. 第二阶段目标与边界

第二阶段目标：

- 保持第一阶段已经可用的 `7709 + WebSocket + HTTP fallback` 实时链路稳定运行，但不把它当作最终验收完成。
- 继续围绕真实 `L2` 鉴权入口推进，重点确认 `tpbus.dll / tc.dll / TDXDeep.dll / QSTPLevel2_* / nacomte.dat / nbcomte.dat` 之间的调用链。
- 验证 `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo / TC_SetL2UserInfo / TC_GetL2Info` 是否能形成可复现的合法 L2 权限同步流程。
- 当前技术路线已收敛到独立 `x86 helper + 官方 DLL 链`，先做 32 位代理进程，再进入最小动态调用验证。
- 公开方案和开源项目只作为辅助线索；最终是否验收，以本地能否返回真实十档盘口和分笔数据为准。
- 将任何候选方案先记录、评估、隔离验证，只有证明能返回真实十档或分笔后，才进入 bridge 接入设计。

第二阶段暂不处理：

- UI 细节、主表列、tooltip、详情面板文案等收尾问题。
- 修改 `DataTable / DataFreshness / StockL2DetailPanel`。
- 改动现有 `python-bridge/main.py` 的默认生产链路。
- 重新安装或迁回 `pytdx`。

第一阶段已经完成：

- `mootdx + 7709 + python-bridge + WebSocket + HTTP fallback`
- 八合一热榜池订阅
- 热榜池分批拉取、动态节流、优先级排序
- 标准五档盘口进入右键详情面板
- Python bridge 接入 `DragonBoardLauncher.exe`

当前新增确认：

- `tools/TdxL2Helper` 已能以真实 `win-x86` 进程加载 `tc.dll / TDXDeep.dll` 并解析目标导出。
- 因此当前已跨过“64 位 Python 不能直接调用 32 位 DLL”的入口级阻塞。
- 下一步最小动态验证顺序应是：`LoadLibrary/GetProcAddress -> TC_Init_Environ -> TC_GetL2Info`。
- 当前已继续推进到：
  - `host-runtime --event-stream`
  - `TC_Login / TC_Login2 / TC_GetLoginRet / TC_GetRightInfo`
  - 缓存登录参数矩阵探针
  - `--login-profile auto` 接入 helper/bridge

---

## 3. 当前已落地架构

```text
通达信标准行情节点（当前实测可用：7709）
        │
        │ 分批轮询，默认目标整轮约 600ms
        ▼
python-bridge/main.py
  - mootdx Quotes.factory(...)
  - 本地 WebSocket 广播
  - 5s heartbeat
  - 节点探测与自动降级
        │
        ▼
src/services/websocket.ts
  - 连接本地 ws://127.0.0.1:8765/ws/quotes
  - 维护实时缓存
  - 处理 full_state / quote_patch / depth_patch / ticks_batch / heartbeat
  - 处理重连、stale、fallback 状态
        │
        ▼
src/services/dataLoader.ts
  - 维护八合一热榜股票池
  - 将热榜池同步给 websocket.ts
  - 优先消费 WebSocket 实时数据
  - WebSocket 不健康时切回 HTTP 备用
        │
        ▼
src/services/DataLayer.ts
  - 存储 realtime.quotes / depth10 / recentTicks / l2Summary
  - 推动 DataTable / 详情面板刷新
```

备用链路：

```text
proxy-server/server.js
    └── /api/quotes/tencent
    └── /api/quotes/sina
    └── /api/quotes/eastmoney
```

---

## 4. 当前范围边界

### 4.1 订阅范围

当前订阅池只包含：

- 八合一平台热榜股票池

不包含：

- 全市场 5000+ 股票
- 选中股额外订阅
- 收藏池额外订阅
- 任意“全市场扫描”

代码口径以 `dataLoader.getAllHotCodes()` 为准。

### 4.2 实时数据范围

当前已稳定承接：

- 最新价
- 涨跌幅
- 成交量
- 成交额
- 标准五档盘口
- 部分节点可返回的分笔成交

当前刷新策略：

- 热榜池一次性提交给 bridge
- bridge 按优先级顺序分批拉取
- 优先目标是把整池延迟压到亚秒级，而不是把服务器硬顶到 100ms 全量

当前未承诺：

- `7719` 真 L2 十档盘口
- 官方客户端同级别的 L2 分笔 / 逐笔全量
- 独立账号密码登录后的专有协议流程

这些能力是当前未完成项，不是被放弃的范围。`7709 / 五档` 只能作为过渡方案，不能作为《通达信 L2 十档实时行情重构计划》的最终验收结果。

---

## 5. 当前实现职责划分

### 5.1 `python-bridge/main.py`

职责：

- 连接通达信标准行情节点
- 以分批轮询方式采集当前热榜池
- 以 `5s` 下发一次 `heartbeat`
- 对外提供本地 WebSocket
- 建连后先用探测股票验证节点是否真能返回行情
- 如果某节点只是 TCP 能连通、但行情接口为空，则自动切到下一个候选节点

当前说明：

- 默认候选节点中，`7709` 已验证可用
- `7719` 当前会握手，但业务接口仍为空

### 5.2 `src/services/websocket.ts`

职责：

- 连接 `ws://127.0.0.1:8765/ws/quotes`
- 发送 `set_hot_pool`
- 维护：
  - `latestQuotesByCode`
  - `latestDepth10ByCode`
  - `recentTicksByCode`
- 收到 `heartbeat` 时保持 `connected`
- `close / error / stale` 时切为 `fallback`
- 自动重连成功后恢复 WebSocket 主链路

当前状态判定口径：

- 心跳提示周期：`5s`
- stale 判定阈值：约 `11.5s`
- 只要最近消息或最近心跳仍新鲜，就继续视为 WebSocket 主链路健康

### 5.3 `src/services/dataLoader.ts`

职责：

- 负责八合一热榜装载
- 每轮热榜刷新后同步订阅池
- 优先从 `webSocketService.getQuotesBatch()` 取实时行情
- 对缺失字段做 HTTP 补齐
- WebSocket 不健康时自动回到 `3s` 一轮的 HTTP 备用

当前补齐策略：

- `turnoverRate` 缺失时只对缺口字段做 HTTP enrichment
- 不会因为单个字段缺失而把整条主链路退回全量 HTTP

### 5.4 `src/services/DataLayer.ts`

职责：

- 保存实时内存态
- 对 UI 提供统一读取入口
- 存储：
  - `realtime.quotes`
  - `realtime.depth10`
  - `realtime.recentTicks`
  - `realtime.l2Summary`

说明：

- 这里的 `depth10` 是统一结构名，不等于当前上游一定有十档
- 如果上游只给五档，后五档为空

### 5.5 `DataTable` 与详情面板

当前 UI 口径：

- 行 tooltip 不再继续堆叠盘口明细
- 十档 / 五档盘口数据统一走右键 `查看详情`
- 详情面板优先显示：
  - 最新价
  - 涨跌幅
  - 买1/卖1
  - 买卖盘总量
  - 盘口深度
  - 最近逐笔

如果当前上游没有提供逐笔，则详情面板会明确展示“当前上游未返回逐笔数据”。

---

## 6. 当前消息协议

客户端上行：

```json
{ "type": "set_hot_pool", "codes": ["600000", "000001"] }
```

服务端下行：

- `full_state`
- `quote_patch`
- `depth_patch`
- `ticks_batch`
- `heartbeat`

说明：

- `full_state` 是当前订阅池的全量基线包，不是历史快照
- `quote_patch` 是基础量价增量
- `depth_patch` 是盘口增量
- `ticks_batch` 是分笔批量
- `heartbeat` 只承担链路健康确认，不承担行情字段更新

---

## 7. 自动切换机制

### 7.1 正常情况

当以下条件同时成立时，前端使用 WebSocket 主链路：

- `websocket.ts` 状态为 `connected`
- `fallbackActive = false`
- 已存在有效订阅股票
- 最近消息或最近心跳未超时

### 7.2 自动降级到 HTTP

以下任一情况发生时，自动切到 HTTP：

- WebSocket `close`
- WebSocket `error`
- 超过 stale 阈值未收到消息或心跳
- 本地 Python bridge 未启动

HTTP 备用口径：

- 轮询间隔：`3000ms`
- 批次大小：`50`

### 7.3 自动回切到 WebSocket

当 Python bridge 恢复、WebSocket 重连成功并重新收到有效消息后：

- 状态重新回到 `connected`
- `dataLoader` 自动优先使用实时缓存
- HTTP 轮询退回备用角色

---

## 8. 已解决的问题

本轮已落地并验证过的改造点包括：

### 8.1 Python bridge 已接入启动器

- `DragonBoardLauncher.exe` 现在会检测 `8765`
- 不再需要手工保持 Python 黑窗常驻
- 启动器会隐藏启动 `python-bridge/main.py`
- 启动器停止服务时也会一并处理 bridge

### 8.2 `DataFreshness` 状态抖动已修正

此前问题：

- 前端按 `1.5s` 误判 WebSocket 超时
- 但 Python bridge 实际心跳是 `5s`
- 导致“订阅 / HTTP备用”来回跳

当前行为：

- WebSocket 心跳正常时保持订阅模式
- 真正失联时才切 HTTP

### 8.3 热榜面板展示已收口

- 只展示前 10 只订阅股票
- 优先排序：
  - 综合信号 = `买入`
  - `MACD` 金叉
- 移除了双滚动条
- 面板宽度已收窄

### 8.4 换手率缺失已处理

问题根因：

- WebSocket 标准行情并不总能带回 `turnoverRate`
- 旧逻辑把缺失值硬写成 `0`

当前处理：

- WebSocket 缺失时保持 `undefined`
- `dataLoader` 仅对缺失字段做 HTTP 补齐

---

## 9. 当前未完成项

### 9.1 `7719 / 真 L2 十档`

当前结论：

- `7719` 是官方客户端真实使用的 L2 端口之一
- 但 `mootdx/tdxpy` 当前公开 `std` 命令集无法直接获取有效业务数据

因此：

- 现在不能宣称已经拿到真 L2 十档
- 也不能把 `TDX_L2_USERNAME / TDX_L2_PASSWORD` 当成已生效能力

### 9.2 真 L2 逐笔

当前 `ticks_batch` 只是在 bridge 层保留了接口与缓存能力。

是否能持续、稳定、完整地拿到：

- 真正的 L2 逐笔
- 深市逐笔委托
- 官方客户端一致口径的十档深度

仍取决于后续 `7719 / QSTP / TDXDeep` 协议验证。

---

## 10. 关于 `pytdx` 的结论

2026-04-25 已完成一次单独评估，结论如下：

- `pytdx` 在 `7709` 上能拿到标准行情和五档
- `pytdx` 在 `7719` 上同样拿不到有效业务数据
- 其本地接口说明里没有 A 股 `7719 / L2 十档` 的明确实现说明
- 截至本次评估，`pytdx` 仓库已归档，只读不维护

因此当前决策为：

- **不切换主链路到 `pytdx`**
- 保留现有 `mootdx` bridge
- `pytdx` 已从本机环境卸载，不作为项目依赖

---

## 11. 第二阶段探索路线

第二阶段的实质是“边探索、边记录、边验证、边准备接入”的攻关阶段。文档更新不是独立验收项，必须服务于最终目标：找到真实鉴权入口，并证明 `7719 / TDXDeep / QSTP` 链路能返回真十档和真分笔。

### 11.1 开源优先

第二阶段先搜索和评估公开仓库、公开包和协议实现。

评估重点：

- 是否明确支持 A 股 `7719`
- 是否明确返回十档盘口
- 是否明确返回逐笔或逐笔委托
- 是否仍在维护
- 是否可以在隔离环境最小实测

初步公开搜索结论：

- `mootdx`：仍是当前可用 bridge 基础，但公开说明集中在标准行情读取，未证明可跑通 `7719` 真 L2。
- `pytdx`：历史评估不通过，不恢复依赖。
- `zsdtdx`：是 pytdx-style wrapper，公开说明包含标准行情连接池和最新价/K 线能力，未证明可返回 `7719` 十档。
- `gotdx / nodetdx / opentdx`：均更接近 `7709` 标准行情生态，暂未看到真 L2 十档证据。
- `jvQuant OpenAPI`：公开 demo 声称 Level2 WebSocket 推送，但属于商业/Token/OpenAPI 路线，不是通达信 `7719` 开源协议实现。

### 11.2 L2 鉴权入口验证

后续验证应保持隔离：

- 不修改通达信安装目录文件
- 不注入官方客户端进程
- 不修改生产 bridge 默认链路
- 不把账号密码字段当作已实现登录
- 先用独立研究脚本记录连接、握手、空返回、包长度、错误码
- 优先验证 `tc.dll` 的 L2 权限同步入口是否可被合法初始化和读取
- 再验证 `TDXDeep.dll` 是否消费该权限态进入 `7719 / QSTP` 深度行情链路

### 11.3 UI 收尾延后

UI 问题在实时链路收尾阶段统一处理。第二阶段不继续调整：

- 主表列
- row tooltip
- `DataFreshness`
- `StockL2DetailPanel`

---

## 12. 推荐后续路线

### 路线 A：先把现有实时链路稳定跑满

继续以当前能力落地生产使用：

- `7709`
- WebSocket 主链路
- HTTP fallback
- 热榜池实时刷新
- 五档详情展示

当前 bridge 额外采用：

- 综合排名前 50、综合信号买入、MACD 金叉优先
- 优先级顺序保留到 Python bridge
- 分批拉取并合并广播
- 根据实际响应自动收缩 / 回升批大小

这是当前最稳、最能立刻解决“几分钟旧价”问题的方案。

### 路线 B：继续独立攻 `7719`

如果后续必须拿到：

- 真 L2 十档
- 真 L2 逐笔
- 与官方客户端一致的深度数据

则后续重点应放在：

- `TDXDeep.dll`
- `QSTPLevel2_*`
- `nacomte.dat / nbcomte.dat`
- 官方客户端运行时对比 / 只读抓包

而不是单纯更换 `mootdx` / `pytdx` 这类公开标准行情库。

### 最终验收口径

《通达信 L2 十档实时行情重构计划》的验收不能停在 `7709 / 五档`。必须至少满足：

- 已定位并验证真实 L2 鉴权 / 权限同步入口。
- 可在隔离链路中返回真实十档盘口，字段能标准化为 `bids[10] / asks[10]`。
- 可返回真实 L2 分笔或逐笔批量，并能进入 `ticks_batch`。
- 前端 bridge 接入后仍保持热榜池订阅、WebSocket 主链路、HTTP fallback 和快照边界不被破坏。

---

## 13. 相关文档

- [TDX L2 7719 协议验证记录](./tdx-l2-protocol-findings.md)
- [TDX L2 第二阶段探索日志](./tdx-l2-phase2-exploration.md)
- [GUI 启动器操作手册](./gui-launcher-manual.md)
- [Python Bridge README](../python-bridge/README.md)
