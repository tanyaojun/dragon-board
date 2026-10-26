# KPL Socket 实时行情链路（最终成果文档）

> 状态：**已上线能力**（2026-10-27 审计通过，goal `mvp9ogq0-7cd2al` 6/6）。
> 定位：KPL（开盘啦）App 私有 socket 协议的 PC 端复刻——从逆向认证到 QuantBoard(:8000)
> WebSocket 端点转发与浏览器实时板块/个股面板，全链路实测打通。
> 本文只固化**成果与合同**；完整逆向攻坚过程见
> [hotlist-jev/socket-push-handoff-20261026.md](../hotlist-jev/socket-push-handoff-20261026.md)（过程记录，勿当运行手册）。

## 一、已完成能力（全部实测，非计划）

| 能力 | 实测证据 |
|------|----------|
| 私有协议认证 | 260 challenge（每连接随机）→ 610 AuthReq（白盒 WBE 签名）→ 610 AuthResp → 602 LoginStateReq，服务器回 ACK 而非 1002 |
| 板块实时行情 | 3001 订阅：801044 土地流转 890.098、885423 安防 1201.486（×10000 整数缩放） |
| 个股实时行情 | 3006 订阅：000001 平安银行 price=113000（=11.30）；IndexSimpleQuotasResp{id/name/price/incPrice/incRate} |
| 服务器推送帧解析 | 0x60 推送格式 `[extlen2][ext ascii 路由][cmd2][flags1][inner_extlen2][payload加密]`，DEC 解密依赖 connType=99 固定派生 |
| :8002 采集服务 | `backend/serve_kpl_socket.py`：WS `/ws/kpl-quotes` + `/api/kpl/status\|start\|stop` + `/kpl` 面板页 |
| :8000 集成 | `backend/api/kpl_proxy_routes.py`（include 进 main.py）：REST 透传 + **WS `/api/kpl/ws/kpl-quotes` 双向中继**，经 :8000 实测收到全部事件 |
| 浏览器面板 | `backend/kpl_page/index.html`：行情表 + 事件日志 + fail-visible 降级提示 |
| 连续稳定收流 | 重连链实测 25 会话 32.3 分钟连续（44 帧解码、零丢弃）；审计整改后经 :8000 复测持续到流 |
| App 保活 | 攻坚全程 App（模拟器内开盘啦）保持正常可用；PC 客户端与 App 同时在线互不踢 |
| 持久化证据 | `.tmp_review/ws_8000_sample.jsonl`（38.8KB，174 事件，经 :8000 采集）；`.tmp_review/kpl_push_stream.bin`（30 分钟连续流 26KB） |

## 二、架构与数据流

```text
模拟器(emulator-5554, 开盘啦 App 正常运行)
  └─ signsvc (app_process32 常驻 /data/local/tmp/signsvc.dex)
       白盒加密 WBE / 帧加密 ENC / 帧解密 DEC（stdin/stdout 协议，经 adb shell）
            ↑ su -c（需 root 模拟器；LD_LIBRARY_PATH 指向 App x86_sig 目录）
PC Python 采集服务（独立进程 :8002）
  backend/services/kpl_socket_protocol.py   ← 协议纯逻辑：帧构造/解析/pb
  backend/services/kpl_collector_service.py ← 采集编排：codec 自愈 + 会话状态机 + 事件广播
  backend/serve_kpl_socket.py               ← FastAPI 入口 + 浏览器面板
            ↑ TLS 1.2 mTLS（client_cert.pem）直连 KPL 行情服务器
QuantBoard 主后端 :8000
  backend/api/kpl_proxy_routes.py           ← REST 透传 + WS 双向中继（fail-visible 502）
            ↓
浏览器（:8002/kpl 面板，或任何连 ws://127.0.0.1:8000/api/kpl/ws/kpl-quotes 的前端）
```

- 采集进程独立于 :8000 主后端（同 snapshot_collector 先例：adb/signsvc 依赖不进主后端生命周期）。
- 本路由只做转发，不承载采集逻辑（api/ 层纪律）。

## 三、协议规范（事实合同）

### 3.1 帧格式

| 方向 | 格式 |
|------|------|
| 服务器帧 | `[pkg=0x20][len4BE][cmd2][status1][extlen2][payload]`（**cmd 在 status 前**） |
| 客户端帧 | `[pkg=0x30\|0x40][len4BE][seq2][cmd2][flags1][extlen2][body]` |
| pkg | `e(N)<<4`：e(3)→0x30 行情通道、e(4)→0x40 路由化订阅通道 |
| flags | `(d<<3) + (加密?1:0)`：610 d=2→0x11；602/610 keepalive d=0→0x01；2301 d=1→0x09 |
| 服务器推送 | pkg=0x60：`[extlen2][ext ascii 路由 topic][cmd2][flags1][inner_extlen2][payload加密]` |
| 路由 ext | `02 <cmd 2BE>`（如 2301→`02 08fd`、3001→`02 0bb9`、3006→`02 0bbe`）；0x40 订阅帧 ext 亦可用明文 topic（`global|26:20020/2301-1/` 风格） |

### 3.2 认证链（顺序敏感，全部实测）

1. TLS 1.2 + 客户端证书（mTLS，`client_cert.pem`；KPL 服务器校验客户端证书）
2. 服务器推 260 challenge：52B，challenge 32B **每连接随机**（不是设备指纹！f5 前 32 位数字=initBaxPwd 设备指纹是早期误判）
3. 客户端发 **610** AuthReq：pb{deviceId,userId,token,version...}，f5=白盒 WBE(challenge+payload) 190 hex 数字串，body GCM 加密，flags=0x11
   —— **认证命令号是 610 不是 601**（`TYPE_QUANTIZE_MOTIONSTEPS`=610；601 是反编译常量名误导，App 从未发送 601）
4. 服务器回 610 ACK（加密 AuthResp，DEC 解密=dispatch 内网地址 `192.168.0.x:port`，仅参考无需重连）
5. 602 LoginStateReq{userId, token, deviceId}（flags=0x01）
6. 订阅 2301/2303/2304 VersionReq{version}（增量轮询模型；应答带 CDN 快照 URL，可下载解析板块/股票清单——appimgcdn.kaipanla.com）
7. 3001 GroupStockQuotasReq{quotaType:0, sortType:2, start:0, **count=len(stockIds)**, f10: repeated stockIds}
   —— **count 必须=stockIds 数量**，不符→ErrResp 2000
8. 3006 HQStockIdListReq{f1: repeated stockIds}（个股实时价通道）

### 3.3 protobuf 编码要点

- **tag 是 varint**：field 100 → tag bytes `a2 06`（不是单字节 0x64！此前 1002 的隐藏污染源）
- `parse_pb` 返回 `{field_no: [values]}`；repeated 字段天然聚合
- 260 帧 serverTime 是 varint；GCM 加解密与 WBE 全部经 signsvc 进程（stdin 命令协议），PC 端不做本地实现

### 3.4 服务器会话时长规律（非固定 TTL）

- **认证+订阅 <1s 完成 → 服务器 ~6s 即断**（机器人检测）；拟人延迟→15-25s；adb 链路 5-8s→75-160s；心跳频率不影响
- **重复 seq 被拒并断连**（110/2000）：keepalive 重发必须递增 seq（服务内置 `next_seq()` 计数器）
- 稳定性合同 = 重连链（app 同款 ReconnectManager，2s 间隔重连），**不是单连接长寿命**
- 261/262 反作弊轮：实测从未下发；若未来触发需把 signsvc EXEC 注入接入 collector

## 四、数据语义与已知限制

- **价格是 ×10000 整数缩放**：113000=11.30 元、8900980=890.098（板块点位）。展示层需自行除以 10000 或标注口径。
- **3001 `quotas` 关键字段语义已独立源核实（2026-10-27，东方财富公开行情接口交叉对照 + 字段间自洽验证）**：
  - quotas[0]=板块归属标签（板块行空串、个股行为概念文字如「银行、业绩增长」）
  - quotas[1]=最新价（板块行=板块指数点位）；quotas[2]=涨跌幅%；quotas[3]=成交额（元）
  - quotas[7]/[8]/[9]=主力流入/流出（流出为负）/净额（[7]+[8]=[9] 自洽）
  - quotas[10]/[11]/[12]=流入/流出/净额占成交额比%（除法自洽）
  - 核对样本：000001 平安银行 quotas[1]=11.3↔11.30、[2]=0.89↔0.89%、[3]=1485999504↔1485999504.06 精确匹配
  - 其余 60+ 列未逐一映射，接入新消费字段时按同样方法增量核对（独立源交叉 + 自洽验证）
- ~~3006 负数 varint 缺陷~~（2026-10-27 提交前已修复）：`_signed64` 补码还原负 inc_price/inc_rate，含负数回归用例；不再出现 uint64 回绕值。
- 3001 板块流与个股流会混合出现（stock_ids 可混合板块 ID 与股票代码）。
- 订阅规模：实测 2 板块 + 1 股稳定；全市场 1571 板块未测。

## 五、部署与运维 runbook

### 5.1 依赖

- root 模拟器在线（adb 设备号可变：`127.0.0.1:5555`→`emulator-5554`，env `KPL_ADB_DEVICE` 调整；adb 路径 env `KPL_ADB_PATH`）
- signsvc.dex 已部署 `/data/local/tmp/signsvc.dex`（`app_process32` 常驻，segfault 由 codec EOF 自愈重建）
- mTLS 客户端证书（env `KPL_CLIENT_CERT`/`KPL_CLIENT_KEY`，默认 `.tmp_review/client_cert.pem`）
- 认证身份（env `KPL_USER_ID`/`KPL_TOKEN`，**代码无凭据默认值**（2026-10-27 提交前脱敏，AGENTS.md 红线 3）；默认游客 userId=0 可收行情但会话较短；正式账户值放 `.env.local`/环境变量注入，本地参考值存 `.tmp_review/kpl_credentials.env`（gitignored））

### 5.2 启动 / 停止

```powershell
# 启动采集服务（:8002）
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.serve_kpl_socket:app --host 127.0.0.1 --port 8002
# 面板 http://127.0.0.1:8002/kpl → 点"启动采集"
# :8000 主后端正常启动即含 KPL 代理路由（无需额外开关）

# 停止：按命令行过滤进程（venv python.exe 是 launcher+child 双进程对，两个 PID 都要杀）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*serve_kpl_socket*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### 5.3 运维纪律（踩坑固化）

- **单实例纪律**：残留旧实例会与新实例采集线程互踢（会话瞬间 ~6s 循环断连）。启动前必须确认只有一个 serve_kpl_socket 进程对。
- **App 保活红线**：不 force-stop 开盘啦 App；注入用的 wrap prop 必须保持清空（`setprop wrap.com.aiyu.kaipanla ""`）。App 挂掉后 `am start com.aiyu.kaipanla/com.yzj.kaipanh.splash.SplashActivity` 恢复。
- `KPL_DEBUG` 环境变量=帧转储文件路径，按 `C/S <ts> <hex>` 逐行追加（诊断用）。
- httpx 客户端一律 `trust_env=False`（防系统代理劫持 127.0.0.1）。

## 六、测试合同

- `backend/services/__tests__/test_kpl_socket_protocol.py`（16 用例，含负数 varint 回归）+ `test_kpl_collector_service.py`（8 用例，含 signsvc EOF 哨兵回归）+ `tests/api/test_kpl_proxy_routes.py`（4 用例，mock 上游 502 fail-visible + WS 双向中继），`28 passed`。
- **红线：pytest 一律全 mock（FakeCodec/FakeSocket），零真实 KPL 连接、零真实 WBE 调用**。真实连接只走预登记的开火路径（人工运维诊断）。
- 会话状态机测试覆盖：全帧序（260/610/602/2301/2303/2304/3001/3006）、fail-visible 断言（解码失败必须广播 error 事件，不静默丢弃）。

## 七、证据工件（本地 .tmp_review/，不入仓）

| 工件 | 内容 |
|------|------|
| `ws_8000_sample.jsonl` | 38.8KB / 174 事件，经 :8000 WS 采集（audit 复核样本：auth 27 / status 27 / stock_quotes 27 / quotes 14 / error 27 / raw 5 / ping 47） |
| `kpl_push_stream.bin` | 30 分钟连续流采集（25 会话重连链，44 帧解码行情，26KB） |
| `sslcap*.bin`、`libredir3.c/.so`、`wbrd.c/.so`、`memscan.c` | 逆向期 SSL 明文钩子 / 内存读取工具与捕获（过程工具，见 handoff §3.10） |
| `client_cert.pem` | mTLS 客户端证书（重建产物） |
| `kpl_live8.py`、`kpl_collector.py` | 认证 / 采集原型脚本（服务化前身，仅参考） |

## 八、遗留风险与后续工作

1. ~~**3006 有符号 varint 修复**~~：已修复（§四，含负数回归用例）。
2. ~~**quotas 列语义与 App UI 对照**~~：已完成（§四）——关键位（[0]/[1]/[2]/[3]/[7]-[12]）经独立源交叉对照与自洽验证确认；其余 60+ 列接入新消费字段时增量核对。
3. **261/262 反作弊轮**（条件性，无法主动触发）：服务器从未下发 261；若开始下发需把 signsvc EXEC 注入接入 collector——触发时再处理。
4. ~~**serve_kpl_socket.py 归档债**~~：已裁定（2026-10-27）——`backend/serve_relay_page.py + relay_page/` 是已入库的同款先例（独立进程入口 + 静态页目录），`serve_kpl_socket.py + kpl_page/` 布局遵循该先例，不再迁移。
5. **凭据已 env 化**（2026-10-27 提交前修复）：代码无凭据默认值（默认游客），正式账户值须环境变量注入，本地参考值存 `.tmp_review/kpl_credentials.env`（gitignored）；转常驻生产服务时统一收进 `.env.local` 加载链并考虑 token 失效监控。
6. **认证 token 轮换未跟踪**（条件性）：当前值失效时需重新提取；失效表现为 610 拒绝（非 1002，认证会 fail-visible 报错）。
7. ~~**低危收流细节**~~：已修复（2026-10-27 待办轮）——signsvc readline 改为守护读线程+队列+deadline 取行（adb 卡死不再永久阻塞采集线程，EOF 哨兵 fail-visible，含回归用例）；WS 中继路径已补 mock 测试覆盖（双向泵）；帧长度 8MB 上限已带。
8. **全部 KPL 待办项已收口**（2026-10-27）；新增改动请同步更新本文档与 AI_COLLABORATION.md KPL 节。
