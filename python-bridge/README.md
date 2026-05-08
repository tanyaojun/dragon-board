# TDX Python Bridge

更新时间：2026-04-26

## 当前定位

本目录提供本地 `mootdx + WebSocket` 中间层，用来把通达信标准行情转成前端可直接消费的本地实时流。

当前真实状态是：

- 已跑通：`7709 / L1 + 标准五档 + 本地 WebSocket`
- 未跑通：`7719 / 真 L2 十档 / 真 L2 逐笔`

因此本目录虽然保留 `L2` 协议验证上下文，但**当前 bridge 不能视为已经实现了通达信官方客户端级别的 L2 深度能力**。`7709 / 五档` 是过渡可用链路，不是《通达信 L2 十档实时行情重构计划》的最终验收结果。

`7719 / L2` 的验证结论见：

- [docs/tdx-l2-protocol-findings.md](../docs/tdx-l2-protocol-findings.md)
- [docs/tdx-l2-phase2-exploration.md](../docs/tdx-l2-phase2-exploration.md)

---

## 第二阶段说明

当前已进入实时行情第二阶段。第二阶段的主线是继续完成 `L2 十档行情 + 分笔` 的最初目标：找到并验证真实 L2 鉴权 / 权限同步入口，再进入 `7719 / TDXDeep / QSTP` 深度行情接入设计。开源方案探索只是辅助线索，不是最终验收。

2026-05-08 起，实时 L2 主线调整为 QMT / miniQMT 合法 Level2 接入。TDX `7719` 探针保留为低优先级研究项，不再作为主线反复尝试。QMT 接入文档见：

- [docs/market-data-l2/qmt-l2-integration-plan.md](../docs/market-data-l2/qmt-l2-integration-plan.md)
- [docs/market-data-l2/qmt-l2-field-mapping.md](../docs/market-data-l2/qmt-l2-field-mapping.md)

执行边界：

- 当前 bridge 继续服务 `7709 / L1 + 标准五档 + WebSocket` 主链路。
- 任何 `7719` 试验都必须走隔离脚本或独立研究分支。
- 不直接修改 `python-bridge/main.py` 的默认生产行为。
- 不重新安装或恢复 `pytdx` 作为依赖。
- 不把 `TDX_L2_USERNAME / TDX_L2_PASSWORD` 当成已实现登录。
- 不把当前五档实时能力当成 L2 十档计划已完成。

如果后续发现可用开源项目，必须先完成文档评估和最小隔离实测，再决定是否进入 bridge 接入设计。更高优先级是验证 `tpbus.dll / tc.dll / TDXDeep.dll` 权限链路，尤其是 `TC_SetL2UserInfo / TC_GetL2Info` 是否能形成可复现的 L2 权限态。

当前隔离探针入口：

```bash
python python-bridge/research/tdx_l2_probe.py --timeout 8
```

说明：

- 该脚本只做只读探测。
- 默认对比 `7709` 与两个 `7719` 候选节点。
- 输出 TCP、连接、`stock_count`、`quotes`、`transaction`、traffic stats 摘要。
- 当前实测结论仍是 `7709` 标准五档可用，`7719` 标准命令为空。

---

## 推荐启动方式

优先使用根目录：

```bash
DragonBoardLauncher.exe
```

原因：

- 启动器会隐藏启动 `python-bridge/main.py`
- 会检测 `8765` 端口
- 不需要手工保留 Python 黑窗
- bridge 关闭时前端会自动退回 HTTP 备用

手工启动只适合调试：

```bash
python python-bridge/main.py
```

默认监听：

- `ws://127.0.0.1:8765/ws/quotes`

---

## 安装

```bash
pip install -r python-bridge/requirements.txt
```

当前依赖只有：

- `mootdx==0.11.7`
- `websockets==14.2`

说明：

- `pytdx` 已在 2026-04-25 完成评估并卸载，不作为当前 bridge 依赖
- 当前桥接实现基于 `mootdx`

---

## 当前可用环境变量

- `TDX_BRIDGE_HOST`：默认 `127.0.0.1`
- `TDX_BRIDGE_PORT`：默认 `8765`
- `TDX_BRIDGE_PATH`：默认 `/ws/quotes`
- `TDX_POLL_INTERVAL_MS`：默认 `100`
- `TDX_TARGET_CYCLE_INTERVAL_MS`：默认 `600`，整轮拉取的目标周期
- `TDX_HEARTBEAT_INTERVAL_MS`：默认 `5000`
- `TDX_QUOTE_BATCH_SIZE`：默认 `40`
- `TDX_QUOTE_BATCH_MIN_SIZE`：默认 `20`
- `TDX_QUOTE_BATCH_MAX_SIZE`：默认 `50`
- `TDX_QUOTE_BATCH_DELAY_MS`：默认 `40`
- `TDX_SLOW_BATCH_THRESHOLD_MS`：默认 `1200`
- `TDX_TICK_WINDOW`：默认 `60`
- `TDX_TICK_CODES_PER_CYCLE`：默认 `0`，表示每轮处理全部订阅股票
- `TDX_SERVER_HOST` / `TDX_SERVER_PORT`：可选，指定单个上游节点
- `TDX_SERVER_CANDIDATES`：L1 / fallback 候选节点列表，格式 `host1:port1,host2:port2`
- `TDX_L2_ENABLED`：默认 `1`，启动时优先扫描 L2 候选池
- `TDX_L2_SERVER_HOST` / `TDX_L2_SERVER_PORT`：默认 `124.71.222.84:7719`，L2 首选节点
- `TDX_L2_SERVER_CANDIDATES`：L2 候选池，默认内置官方客户端连接过的 `7719` 节点列表
- `TDX_L2_TIMEOUT_SECONDS`：默认 `3`，L2 池单节点探测超时，避免不可达节点拖慢整轮扫描
- `TDX_L2_PROBE_INTERVAL_MS`：默认 `30000`，后台 L2 池轮询间隔
- `TDX_L2_REQUIRED`：默认 `0`，为 `1` 时 L2 池不可用不再回退到 L1
- `TDX_USE_BESTIP`：默认 `0`，避免每次启动都跑全网测速
- `TDX_TIMEOUT_SECONDS`：默认 `15`
- `TDX_PROBE_SYMBOL`：默认 `000001`
- `TDX_L2_USERNAME` / `TDX_L2_PASSWORD`：当前仅预留，不会形成真实登录流程
- `L2_PROVIDER`：设置为 `qmt` 时启用 QMT L2 Provider
- `QMT_L2_ENABLED`：默认 `0`，为 `1` 时尝试通过 `xtquant.xtdata` 获取 QMT L2
- `QMT_L2_CODE_LIMIT`：默认 `80`，限制每轮 QMT L2 股票数
- `QMT_L2_POLL_INTERVAL_MS`：默认 `600`
- `QMT_L2_REQUIRE_OFFICIAL`：默认 `1`，要求 L2 来源按正式资金流口径标记

---

## QMT L2 探针

```bash
python python-bridge/l2/probe_qmt_l2.py --codes 000001.SZ,600000.SH
```

探针输出结构化状态：

- `ok`
- `missing_xtquant`
- `qmt_not_running`
- `permission_denied`
- `empty_l2_data`
- `field_mismatch`
- `unknown_error`

启用 bridge QMT L2：

```bash
set L2_PROVIDER=qmt
set QMT_L2_ENABLED=1
python python-bridge/main.py
```

QMT 可用时，WebSocket 会新增 `money_flow_patch`，资金流标记为 `moneyFlowSource=qmt_l2`、`moneyFlowEstimated=false`、`capitalFlowSource=broker_l2`。QMT 不可用时，现有 TDX L1 fallback 保持不变。

## 当前协议

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

- `full_state`：当前订阅池的全量基线包
- `quote_patch`：基础量价增量
- `depth_patch`：盘口增量
- `ticks_batch`：分笔批量
- `heartbeat`：链路健康包

---

## 当前行为说明

### 1. 订阅池

- bridge 采集池按所有前端上报代码做并集
- 当前前端实际只会上报“八合一热榜股票池”

### 2. 轮询节奏

- 单轮基础轮询起点：`100ms`
- 默认目标周期：`600ms`
- heartbeat：`5000ms`

说明：

- bridge 不再把 200+ 热榜股一把塞进一次 `quotes(symbol=codes)` 请求
- 当前实现会按批分段拉取，再合并成一轮结果广播给前端
- 批大小会根据“是否截断 / 是否过慢 / 是否失败”自动缩放，优先保证稳定，不追求极限频率

### 3. 节点探测

bridge 建连后会先对 `TDX_PROBE_SYMBOL` 拉一笔行情。

如果节点表现为：

- TCP 可以连通
- 但行情接口返回空

则当前节点会被视为不可用，并自动切到下一个候选节点。

说明：

- 默认生产行情连接不会被 L2 池阻塞，会先使用 `TDX_SERVER_CANDIDATES` 中的 L1/fallback 节点保持行情可用。
- L2 `7719` 候选池由后台探测循环独立扫描，并通过 heartbeat 的 `l2` 字段报告 `live / protocol_pending` 状态。
- 只有设置 `TDX_L2_REQUIRED=1` 时，bridge 才会把 L2 池放进生产连接候选链，且不再自动回退 L1。

### 4. 默认候选节点

默认 L2 候选池来自官方客户端 `7719` 连接记录，当前内置：

```text
124.71.222.84:7719
139.9.2.221:7719
106.52.50.92:7719
115.159.210.142:7719
124.70.201.50:7719
139.159.214.37:7719
110.41.14.158:7719
123.249.28.184:7719
49.233.65.70:7719
139.9.208.12:7719
175.178.1.74:7719
139.9.211.54:7719
123.60.164.170:7719
49.235.186.69:7719
123.60.162.102:7719
124.220.164.89:7719
175.24.205.60:7719
150.158.160.127:7719
139.9.1.206:7719
43.138.33.225:7719
43.136.49.71:7719
203.195.161.155:7719
106.52.221.102:7719
119.3.183.88:7719
139.9.143.183:7719
120.46.206.187:7719
106.54.40.15:7719
124.220.73.3:7719
49.235.176.135:7719
116.205.235.110:7719
116.205.238.42:7719
116.205.239.160:7719
1.94.169.137:7719
```

默认 fallback 候选为：

- `218.6.170.47:7709`

当前实测：

- `7709` 可直接返回实时行情与五档字段
- `7719` TCP 可达，但标准 `mootdx` 行情命令仍需进一步协议验证

---

## 当前数据能力

### 已验证可用

- 最新价
- 涨跌幅
- 成交量
- 成交额
- 标准五档盘口
- 部分标准分笔

### 当前限制

- `depth_patch` 会统一发成最多 10 档结构
- 但如果上游只返回五档，后五档为空
- `ticks_batch` 是否持续有值，取决于上游节点实际返回

因此当前不能把：

- `depth_patch`
- `ticks_batch`

直接理解成“已经等于官方客户端 L2 十档 / L2 逐笔”。

---

## 7719 / L2 账号说明

目前已确认：

- `7719` 很可能是官方客户端真实使用的 L2 端口
- 但 `mootdx 0.11.7 + tdxpy` 公共代码里没有显式“账号 / 密码登录”入口

所以当前不能把：

- `TDX_L2_USERNAME`
- `TDX_L2_PASSWORD`

接进去之后就当作 L2 已登录成功。

示例：

```bash
set TDX_SERVER_HOST=106.52.50.92
set TDX_SERVER_PORT=7719
set TDX_L2_USERNAME=你的账号
set TDX_L2_PASSWORD=你的密码
python python-bridge/main.py
```

这组配置当前只会让 bridge：

- 优先尝试 `7719`
- 记录你已提供凭据

不会自动生成 `mootdx` 并不存在的专有登录能力。

---

## 已知结论

1. 当前 bridge 是解决“HTTP 轮询太慢”的实时方案，不是已经完成的 L2 十档方案。
2. 如果 WebSocket 正常，前端会优先使用 bridge 实时数据。
3. 如果 bridge 离线或心跳失效，前端会自动切回 HTTP 备用。
4. `pytdx` 已完成一次验证，结论是不优于当前 `mootdx` 方案，且未解决 `7719`，因此已卸载。
5. 最终验收仍要求真实十档盘口和分笔数据；当前五档链路只能用于过渡运行。
