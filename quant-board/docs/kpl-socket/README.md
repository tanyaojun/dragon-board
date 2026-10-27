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
双轨签名层（KPL_CODEC 切换，默认 pc）：
【pc 轨，默认】unicorn 本机模拟 libauthSign_x86.so（backend/services/kpl_pcemu/）
  工件 data/kpl_pcemu/{libauthSign_x86.so, assets/middle_new.bin, signer_cert.der}
  （scripts/extract_kpl_pcemu.py 从设备提取；不依赖 adb/模拟器）
【adb 轨，兑底】模拟器(emulator-5554, 开盘啦 App 正常运行)
  └─ signsvc (app_process32 常驻 /data/local/tmp/signsvc.dex)
       白盒加密 WBE / 帧加密 ENC / 帧解密 DEC（stdin/stdout 协议，经 adb shell）
            ↑ su -c（需 root 模拟器；LD_LIBRARY_PATH 指向 App x86_sig 目录）
PC Python 采集服务（独立进程 :8002）
  backend/services/kpl_socket_protocol.py   ← 协议纯逻辑：帧构造/解析/pb
  backend/services/kpl_collector_service.py ← 采集编排：codec 自愈 + 会话状态机 + 事件广播
  backend/services/kpl_pcemu/               ← 【pc 轨】ELF 加载 + JNIEnv mock + PCEmulatorCodec
  backend/serve_kpl_socket.py               ← FastAPI 入口 + 浏览器面板（KPL_CODEC 开关）
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
  - quotas[56]=板块强度（2026-10-27 双源对账：80 板块 55 个与 apphwhq `RealRankingInfo`
    Type=2 强度值相对误差 <0.1%，其余为两源取数时差；801159=18547.028 与 App 同屏值一致）
  - 核对样本：000001 平安银行 quotas[1]=11.3↔11.30、[2]=0.89↔0.89%、[3]=1485999504↔1485999504.06 精确匹配
  - 其余 60+ 列未逐一映射，接入新消费字段时按同样方法增量核对（独立源交叉 + 自洽验证）
- ~~3006 负数 varint 缺陷~~（2026-10-27 提交前已修复）：`_signed64` 补码还原负 inc_price/inc_rate，含负数回归用例；不再出现 uint64 回绕值。
- 3001 板块流与个股流会混合出现（stock_ids 可混合板块 ID 与股票代码）。
- 订阅规模：**240 板块全量实测稳定（2026-10-27，精选板块页引导订阅：~2s 轮询推 242 id、
  一次 signsvc 管道抖动 codec 自愈重连）**；全市场 1571 板块仍未测。
- **工作台消费端已上线（2026-10-27）**：JEV 叙事工作台（:8008）侧栏「KPL 行情 › 精选板块」
  ——当日走本链 WS（经 :8000 中继，:8002 新增 `POST /api/kpl/subscriptions` 动态订
  阅），历史走 HTTP 直连（`kpl_ranking_service.py` + `GET /api/kpl/sector-ranking|
  sector-stocks`，凭据走 `mapping_refresh` 公共出口）；quotas[2]/[3]/[7]/[8]/[9] 列
  已独立源核实（§四），强度（[56]）/涨停家数（`zt_stocks` 事件按 plate 顿号归属聚合，
  口径=当前封住，与 App「涨停」列含触板口径不同）/封单额/涨停时间后续逐项接。成分股
  分页一批 100 只（`sector-stocks?page=`，服务端 st=1000 单发全量+30s 缓存切片）。
- **打板页签消费端已上线（2026-10-27 二期+三期）**：工作台侧栏「KPL 行情 › 集合竞价 /
  即将涨停 / 风向标」——socket 2103 订阅快照读口（§十一），布局沿用精选板块「左板块右个股」，
  左侧=按板块字段聚合（家数+合计），右侧=App 竞价页字段全搬。

## 五、部署与运维 runbook

### 5.1 依赖（按 KPL_CODEC 双轨拆解）

**pc 轨（默认，`KPL_CODEC=pc`）——摆脱 adb/模拟器运行时依赖：**
- 工件三件套在 `quant-board/data/kpl_pcemu/`（gitignored 本地状态）：
  `libauthSign_x86.so`（白盒签名变体，非 APK 内 lib/x86/ 普通变体）、
  `assets/middle_new.bin`（白盒表）、`signer_cert.der`（签名证书 DER）。
  提取：`.venv/Scripts/python.exe scripts/extract_kpl_pcemu.py`（设备模式，需 root 模拟器在线一次）
  或 `--from-dir/--so/--cert` 归档模式（离线组装既有工件）。
- 缺工件时启动/首调 fail-visible 报错并给出修复指引（不静默回退）。
- Python 依赖：unicorn（.venv 已含）。首次初始化 ~7s（ELF 加载 + initBaxPwd + 指令翻译缓存），
  之后单次 wbe ~0.06s / enc ~0.09s。

**adb 轨（兑底对照，`KPL_CODEC=adb`）：**
- root 模拟器在线（adb 设备号可变：`127.0.0.1:5555`→`emulator-5554`，env `KPL_ADB_DEVICE` 调整；adb 路径 env `KPL_ADB_PATH`）
- signsvc.dex 已部署 `/data/local/tmp/signsvc.dex`（`app_process32` 常驻，segfault 由 codec EOF 自愈重建）

**两轨共用：**
- mTLS 客户端证书（env `KPL_CLIENT_CERT`/`KPL_CLIENT_KEY`，默认 `.tmp_review/client_cert.pem`）
- 认证身份（env `KPL_USER_ID`/`KPL_TOKEN`，**代码无凭据默认值**（2026-10-27 提交前脱敏，AGENTS.md 红线 3）；默认游客 userId=0 可收行情但会话较短；正式账户值放 `.env.local`/环境变量注入，本地参考值存 `.tmp_review/kpl_credentials.env`（gitignored）。`KPL_DEVICE_ID` 是参与 WBE
  签名的设备指纹，属非机密可默认，env 可覆盖）

### 5.2 启动 / 停止

```powershell
# 启动采集服务（:8002）；KPL_CODEC=adb 切 signsvc 兑底轨（默认 pc）
cd quant-board
set KPL_CODEC=adb && .\.venv\Scripts\python.exe -m uvicorn backend.serve_kpl_socket:app --host 127.0.0.1 --port 8002
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

- `backend/services/__tests__/test_kpl_socket_protocol.py`（16 用例，含负数 varint 回归）+ `test_kpl_collector_service.py`（14 用例，含 signsvc EOF 哨兵回归）+ `test_kpl_daban_protocol.py`（14 用例）+ `tests/api/test_kpl_proxy_routes.py`（4 用例，mock 上游 502 fail-visible + WS 双向中继）+ `test_kpl_pc_codec.py`（8 用例，全 mock PC codec 合同），**HEAD 口径合计 56 passed**（以 pytest 实跑为准；工作区含他人未提交测试时总数会更大）。
- **红线：pytest 一律全 mock（FakeCodec/FakeSocket/FakeCore），零真实 KPL 连接、零真实 WBE 调用、零真实 ELF 加载**。真实连接与 PC 模拟核差分只走预登记的开火路径（人工运维诊断 / 开发期差分脚本）。
- 会话状态机测试覆盖：全帧序（260/610/602/2301/2303/2304/3001/3006）、fail-visible 断言（解码失败必须广播 error 事件，不静默丢弃）。

## 七、证据工件（本地 .tmp_review/，不入仓）

| 工件 | 内容 |
|------|------|
| `ws_8000_sample.jsonl` | 38.8KB / 174 事件，经 :8000 WS 采集（audit 复核样本：auth 27 / status 27 / stock_quotes 27 / quotes 14 / error 27 / raw 5 / ping 47） |
| `kpl_push_stream.bin` | 30 分钟连续流采集（25 会话重连链，44 帧解码行情，26KB） |
| `sslcap*.bin`、`libredir3.c/.so`、`wbrd.c/.so`、`memscan.c` | 逆向期 SSL 明文钩子 / 内存读取工具与捕获（过程工具，见 handoff §3.10） |
| `client_cert.pem` | mTLS 客户端证书（重建产物） |
| `kpl_live8.py`、`kpl_collector.py` | 认证 / 采集原型脚本（服务化前身，仅参考） |
| `wbx_groundtruth.json` | 设备 WBE ground truth 4 组（不同 challenge/curTime，91B/组，字节级差分基准） |
| `wbx_encdec_groundtruth.json` | 设备 ENC/DEC ground truth 4 组（DEC roundtrip 实测 OK） |
| `wbx_emu.py`/`wbx_step3.py`/`wbx_step6.py`/`wbx_step8_encdec_diff.py` | PC 模拟核原型与差分脚本（正式实现已移植入 `backend/services/kpl_pcemu/`） |
| `svc8002_pc*.log` | :8002 PC 轨实测日志 |

## 八、遗留风险与后续工作

1. ~~**3006 有符号 varint 修复**~~：已修复（§四，含负数回归用例）。
2. ~~**quotas 列语义与 App UI 对照**~~：已完成（§四）——关键位（[0]/[1]/[2]/[3]/[7]-[12]）经独立源交叉对照与自洽验证确认；其余 60+ 列接入新消费字段时增量核对。
3. **261/262 反作弊轮**（条件性，无法主动触发）：服务器从未下发 261；若开始下发需把 signsvc EXEC 注入接入 collector——触发时再处理。
4. ~~**serve_kpl_socket.py 归档债**~~：已裁定（2026-10-27）——`backend/serve_relay_page.py + relay_page/` 是已入库的同款先例（独立进程入口 + 静态页目录），`serve_kpl_socket.py + kpl_page/` 布局遵循该先例，不再迁移。
5. **凭据已 env 化**（2026-10-27 提交前修复）：代码无凭据默认值（默认游客），正式账户值须环境变量注入，本地参考值存 `.tmp_review/kpl_credentials.env`（gitignored）；转常驻生产服务时统一收进 `.env.local` 加载链并考虑 token 失效监控。
6. **认证 token 轮换未跟踪**（条件性）：当前值失效时需重新提取；失效表现为 610 拒绝（非 1002，认证会 fail-visible 报错）。
7. ~~**低危收流细节**~~：已修复（2026-10-27 待办轮）——signsvc readline 改为守护读线程+队列+deadline 取行（adb 卡死不再永久阻塞采集线程，EOF 哨兵 fail-visible，含回归用例）；WS 中继路径已补 mock 测试覆盖（双向泵）；帧长度 8MB 上限已带。
8. **全部 KPL 待办项已收口**（2026-10-27）；新增改动请同步更新本文档与 AI_COLLABORATION.md KPL 节。

## 九、打板/情绪事件流协议合同（2026-10-27 增补，全部实测）

### 9.1 能力概览

- 复用既有 610 认证 / signsvc / 推送帧基建，新增**打板/情绪 7 个 cmd 的订阅、解析与结构化事件**：
  `zd_stat`（涨跌停统计）、`market_overview`（综合强度/预测量能）、`plate_strength`（板块强度+LiveMarkets 秒级事件流）、`weight_perf`（权重+大幅回撤）、`zt_situation`（连板天梯/破板率/昨日表现）、`zt_stocks`/`dt_stocks`（涨停/跌停个股封单与状态机）、`wind_vane`（风向标）。
- 浏览器面板 `kpl_page/index.html` 增补情绪仪表盘（6 卡 + 风向标标签 + 涨停个股表：封单/主力净额/状态徽章 + LiveMarkets 事件流区），缺失数据显式 missing 标注。
- 盘中 30 分钟实测（2026-10-28 09:30–10:00）：39.9MB 样本、封单变化 2137 次、回封/炸板状态翻转 6 次、情绪数字刷新 462 次；App UI 同屏对照 real_zt=44/real_dt=3 两次精确一致，预测量能 15158↔15137 亿（分钟级漂移内一致）。

### 9.2 通道与订阅帧

- **全部走 0x40 通道**（帧型同 2301/3001/3006，`e((byte)4)`），ext=`[02][cmd BE]`，`u(cmd)` 默认 0；响应 msgId 在 field 500（varint）。
- 请求体构造（`kpl_daban_protocol.py`）：
  - 2114/2115/2118/2119 → `QxMarketEnergyReq{f1 type}`（type 区分同类多面板）
  - 2116/2126 → 空 Req
  - 2120/2121 → `QxZtSituationStockReq{f1 bsType(1=涨停/2=跌停), f2 orderType, f3 sortType}`；**orderType 必须 4**（App `a0()` 基线，实测 orderType=0 无响应）
- cmd 号表（反编译 `qn0.java` 分发器）：2114=涨跌停统计、2115=综合强度、2116=板块强度+LiveMarkets、2118=权重+大幅回撤、2119=涨停表现V2、2120/2121=涨停/跌停个股、2126=风向标。

### 9.3 pb 响应 schema（实测核对）

- `QxNewZDStatResp{f1 date, f10 zdStat{f1 zt, f2 dt, f3 realZt, f4 realDt, f5 rise, f6 down, f20 zdList map}, f11 zdStatBx}`
- `QxZtSituationRespV2{f1-f4 一/二/三板/高度, f8 todayZbRatio, f9-f11 昨日表现, f13 fourPlate}`
- `QxZtSituationStockResp.Item` 21 字段：f5 price ×10000、f12 ztTur 封单、f11 ztState 字符串、f4 state（状态机）
- 2116 LiveMarkets=`f20{f1 time, f2 msg, f3 isNew}`、Trend=f10/f11/f12/f21
- 事件名映射 `DABAN_EVENT_NAMES`（collector 层），`parse_pb_f32` 支持 wire type 5/1。

### 9.4 collector / 转发集成

- `KplCollectorService(daban_subs=True, daban_market_type=1)` 启用订阅序列；dispatch 解密/解析 **fail-visible**（异常广播 `daban_error` 事件，不静默丢弃）。
- 610 ack 的 DEC 崩溃降级不杀会话（SignSvcError try/except）：认证已成功，server_ip 为可降级字段。
- :8000 WS（`/api/kpl/ws/kpl-quotes`）与 :8002 直连同构转发，6 类事件实测全到流。

### 9.5 已知限制与依赖

- **DEC SIGSEGV（signsvc 白盒库）为既有行为非回归**：首轮审计时 ~2s/会话，现 24–31s/会话是改善；稳定性合同=重连链，数据每会话完整到流（盘中 30 分钟 1801s 连续样本佐证）。
- **LiveMarkets isNew 计数**：采样窗口内 `live_market_msgs=0`（isNew 标记逻辑待核），事件文本本身实时到流（「封涨大减 剩余封单」等）。
- **模拟器依赖三层拆解**：①协议知识/展示/证据层——不依赖模拟器（来自 PC 本地 APK 反编译）；②认证签名层——**单点绑定**（signsvc=adb→模拟器 app_process32+已安装 app 的 x86_sig 白盒库），无模拟器则 610 认证断；③架构已隔离：`KplCollectorService(codec=...)` 只依赖 enc/dec/wbe 接口，换宿主=换 codec 实现（迁移路径：换 Android 宿主 ≈半天 → PC 模拟白盒 so → 纯算法还原，后者不必要）。
- 协议源码参考（PC 本地反编译，`.tmp_review/main_src/`）：`qn0.java`（分发器）、`MoodPresenterImpl.java k()`（请求构造）、`SocketPresenter.java y()`（帧型）、`ServiceHqDaban.java`/`Hq.java`（proto 描述符）；侦察笔记 `daban_recon_notes.md`。

### 9.6 证据工件（本地 .tmp_review/，不入仓）

| 工件 | 内容 |
|------|------|
| `daban_intraday_sample.jsonl` + `sampler_result.json` | 盘中 30 分钟样本（39.9MB / 3568 行）+ 事件统计汇总 |
| `daban_intraday_sampler.py` | 30 分钟采集+秒级事件统计器（60s 短测 + 1801s 盘中实测） |
| `kpl_daban_frames.txt` | KPL_DEBUG 帧转储（4.9MB） |
| `daban_recon_notes.md` | 协议逆向侦察笔记（cmd 分发表 / proto 合同 / 请求构造） |
| `kpl_daban_panel.png` | 面板 headless Chrome 渲染截图（与 App UI 数值一致） |

## 十、白盒签名 PC 化（2026-10-28 增补，全部实测）

> 目标 `mvq61fzc-dg4lme` 交付：签名层摆脱 adb/模拟器运行时依赖，`KPL_CODEC=pc|adb` 双轨。

### 10.1 能力与实测

| 项 | 结果 |
|----|------|
| PC 白盒 WBE 差分 | 4/4 组不同输入与设备 signsvc ground truth **逐字节一致**（91B/组，含 challenge ASCII 回显 + 二进制签名） |
| PC ENC/DEC 差分 | 设备 ENC → PC DEC 逐字节还原 4/4；PC roundtrip 5/5（密文含随机 IV，逐字节比对走 DEC 还原等价） |
| :8002 PC 轨实测 | `codec=pc` 完成 610 认证 → streaming：板块 quotes + 个股 stock_quotes + 打板/情绪 7 类事件全到流；会话 TTL 断连后重连链正常 |
| 长跑稳定性 | 420 次连续 enc/dec/wbe 调用输出零漂移（free-list + 临时数组回收修复后）；`/api/kpl/status` 的 `codec` 字段可观察当前轨 |

### 10.2 实现要点（勿回退的硬事实）

- **位置**：`backend/services/kpl_pcemu/{elf,jni,codec}.py`——ELF32 加载/重定位、JNIEnv mock
  （30 槽，canonical jni.h 索引）、libc/asset VFS、门位置位、PCEmulatorCodec。
- **JNI 槽位以 JDK jni.h 为准**：`ReleaseByteArrayElements=192(0x300)`、
  `GetByteArrayRegion=200(0x320)`、`SetByteArrayRegion=208(0x340)`。曾错标
  190/197/205 是 WBE 输出全零的真根因（输出数组三次 SetByteArrayRegion 落进空 stub）。
  ~~「白盒状态未预热」~~为当时误判：nativeGuard/nativeDecrypt 均不写 libauthSign 内存
  （前者=libnsc 自身完整性 + APK 头 sha256 + fork/ptrace 反调试；后者=SSSE3 AES 解密 dex chunk）。
- **门位**：`[BASE+0x38597C]`（WBE 签名校验早退）与 `[BASE+0x38597D]`（enc/dec 入口检查
  0x34b210 快路径）显式置 1——设备上由启动链写入的 .data 状态字节，PC 端等价 libpatch 语义。
- **EVP 层原生执行**：libauthSign 静态链接 OpenSSL（EVP_aes_256_gcm 等 val≠0 自重定位），
  CPUID hook 强制非 AESNI 纯软路径，无需 mock。
- **内存纪律（长跑命门）**：`imp_free` 必须真实回收（free-list 首次适配）+ enc/dec/wbe
  临时 jbyteArray 调用后回收，否则 EVP ctx/operator new 每次泄漏 → 数百次 dec 后堆耗尽
  `UC_ERR_WRITE_UNMAPPED`（codec 层有兜底：异常丢核重建，但根治靠回收）。
- **unicorn 教训**：UC_HOOK_CODE 首次执行前注册；R_386_32 必须 S+A；x86-32 GS 基址方案
  不生效（NULL 页映射替代 canary）；堆 64MB 与 0x56000000 arena 不得重叠。

### 10.3 双轨切换与工件提取

- 切换：`KPL_CODEC=pc`（默认）/ `adb`，重启进程生效；`/api/kpl/status` 返回 `codec` 字段。
- 工件：`scripts/extract_kpl_pcemu.py`（设备模式需 root 模拟器在线一次；归档模式
  `--from-dir/--so/--cert` 离线组装）。**so 必须用设备 `/data/app/.../lib/x86_sig/` 的
  白盒签名变体**，APK 内 `lib/x86/` 普通变体不可用。

## 十一、打板个股列表（2103：集合竞价 / 即将涨停，2026-10-27 增补，全部实测）

### 11.1 页签与参数（逆向三方对齐）

- 页签↔pidType：APK 资源数组 `PatternTabs × PatternTabsServerPidType`
  （androguard 解包 base_new.apk）：竞价=**8**、即将涨停=**0**、风向标=**6**、涨停=1、
  炸板=2、跌停=3、新股=7、自然涨停=4、曾跌停=5。已接 8/0/6 三页签，其余增量接。
  风向标页签列序（4,5,11,12,13,14,15=涨幅/涨速/板块/主力净额/成交额/实际换手/实际流通）
  与 App 同屏逐项核对一致（2026-10-27 盘后真帧：冰山冷热/襄阳轴承/九阳股份/百洋股份等 25 只）。
- 请求 `DaBanStockListReq{f1 pidType, f2 orderType, f3 sortType, f4 index, f5 count}`，
  基线=BiddingZTlQuotaPresenter 默认值：orderType=**18**、sortType=**1**（2120 的教训：
  orderType 必须用 App 在用基线，不自行填 0）；filter flags（stType/cxType/…）默认关=0 不编码。
- 构造/解析：`kpl_daban_protocol.build_daban_stock_list_req_pb / parse_daban_stock_list`；
  订阅在 collector 6d 段（`KplCollectorService`，daban_list_pids/daban_list_page_size/daban_list_pages）。

### 11.2 推送页语义（实测硬事实）

- **推送页固定 30 行**：请求 count=200 服务器接受（KPL_DEBUG 帧经 pcemu 离线 DEC 解密核对
  `28 c8 01`）但 Resp.count 恒 30、每帧 30 行——分页只能 index 偏移多页订阅（App 翻页同款）。
  collector 每页签订 7 页（0/30/…/180），按 (pidType, index) 页缓存，读口按 index 合并。
- Resp：`{f1 pidType, f2 orderType, f3 sortType, f4 index, f5 count, f20 items,
  f21 indexes, f22 maxSize, f23 date}`；Item：`{f1 stockId, f2 name, f3 stockTag,
  f4 financingTag, f5 backZT, f6 warnTag, f100 quotas(repeated string)}`。
- **quotas 列语义 = `nn0.U()`（quotas 下标→统一数组位置）× APK tinker 资产
  `assets/PatternDynamicQuota`（位置→列名）× `PatternTitleVisibleArrayPosition`
  （页签默认列序：竞价=18,19,11,4,20,22,21,15；即将涨停=17,4,5,11,12,13,14,15）** 三方对齐，
  代码常量 `DABAN_QUOTA_NAMES`。App 竞价页「实时涨幅」列下方的连板状态子标签
  （4连板/昨日首板/昨3连板…）= **quotas[10] state 列**（2026-10-27 与 App 同屏逐项核对）。
- 数值/单位：涨停委买额/竞价净额/竞价成交额/实际流通等为**数值元**（1302937361.0=13.02 亿，
  与 App 同屏一致）；解析层可转 float 的转 float，不可转的原样字符串保留（fail-visible，
  不猜换算）；quotas[20]/[21] 无目录名，只进 raw quotas。
- 读口：`GET :8002/api/kpl/daban-list?pid_type=8|0`（:8000 同路径代理透传）→
  `{ok, items[合并全量], max_size, pages, pages_expected, pages_missing, date, ts}`；
  页缺口显式透出（如即将涨停页盘后 maxSize=30 但推送 items 空，属上游语义非链路故障）。
- 无快照（采集未运行/未订阅）返回结构化降级 `{ok:false, degraded:true,
  reason:"no_daban_list_snapshot"}`，不伪装空列表。
- 前端：WS `daban_stocks` 事件（单页 30 行）只做节流触发（1.5s），渲染唯一源=REST 合并快照，
  页合并逻辑单源在后端（避免双写漂移）。

### 11.3 顺带根治（同轮）：3006 订阅分块

- 精选板块引导后订阅 id≈713，`3006 HQStockIdListReq` 原为**单帧全发** → 每会话触发
  server error 1106（单请求 id 超 ~241 上限，工作台横幅可见）。已改为与 3001 同款 200 分块
  （`_chunks`），实测横幅消失、行情照常到流；含 3 帧全量无丢失回归用例。

### 11.4 历史回看读口（HisDaBanList，2026-10-27 三期，上游当晚异常待复测）

- 合同（逆向自 BiddingZTlQuotaPresenter.a0 → ox0.L2 → j00.P1 → qg.q1）：POST apphis
  ``a=HisDaBanList&c=HisHomeDingPan``，``Day=YYYY-MM-DD``、``PidType``（8/0/6 同 socket）、
  ``Type=18``（orderType 基线）、``Order=1``、``Is_st/Filter/FilterMotherboard/FilterGem/
  FilterTIB=0``、``Index/st`` 分页；**历史行格式与 socket quotas 不同**——row[0]=代码、
  row[1]=名称、row[2]=labelType(int)、row[3]=板块标签，row[i]（i≥4）直接按统一数组位
  取值（与 PatternTitleVisibleArrayPosition 列序同源，解析器 `_parse_daban_history_row`，
  列语义未经真实样本核对——上游异常期拿不到样本，接入消费前须与 App 历史页同屏核对）。
- 读口：`GET /api/kpl/daban-list-history?date=&pid_type=`（:8000 直连 HTTP，与
  sector-ranking 同层）；前端三页（集合竞价/即将涨停/风向标）已加精选板块同款
  日期切换 + 回实时工具条，历史模式单发不轮询。
- **2026-10-27 晚上游异常实录（阴性记录，引用前须当日复测）**：HisDaBanList 与
  ZhiShuStockList_W8（成分股，:8000 既有功能）先后返回 1020 参数出错 / errcode 0+空列表，
  两种形态抖动；游客/现役凭据/socket 凭据、apiv w21-w48、Day/Date/Isst 变体、
  apphis/apphwhq/applhb 三域名全试一致；同通道 RealRankingInfo/DaBanList/plate-tree 正常。
  时段内本机探针 ~50 发（远超 App 正常频率），疑触发上游频控——当晚已停止探测待冷却复测。

### 11.5 打板头统计读口（HisDaBanHeadInfo，KPI 三卡昨日侧来源，2026-10-27）

- 工作台 kpl 组 KPI 条重排（用户需求，App 市场情绪头同款）：删综合强度/板块强度/亏钱效应/
  空头气氛四卡，增**涨停板（今/昨）/封板率（今/昨）/跌停股（今/昨）**三卡（涨红绿跌）。
- 今日值：zd_stat（2114）real_zt/real_dt + 封板率=100−破板率（2119 todayZbRatio，
  与 App 59% 同屏核对：41/59%/21 精确一致）。昨日值：`GET /api/kpl/daban-head?date=`
  （HisDaBanHeadInfo HTTP，预期字段 yesterdayZT/yesterdayFB/yesterdayDT——响应结构未获
  真实样本核对，同 §11.4 风控期限制）；缺数显式 "--" 不伪装。

### 11.6 测试与证据

- `test_kpl_daban_protocol.py`：2103 请求构造（App 基线字节）/解析（竞价列+即将涨停列+乱码
  fail-visible）/注册表；`test_kpl_collector_service.py`：会话帧序含 14 帧 2103 分页订阅、
  页合并快照读口、3006 分块；`tests/api/test_kpl_proxy_routes.py`：daban-list 透传+502。
  KPL 专项合计 50 passed（全 mock，零真实连接）。
- 证据工件（本地 .tmp_review/）：`kpl_daban_frames_20261027.txt`（KPL_DEBUG 帧转储，
  含 count=200 请求密文）；真实快照对照：竞价页 183/183 全量零缺口，赛福天行与 App 竞价页
  同屏逐项一致（13.02 亿/10.01%/机器人概念、海洋经济/4连板/528.0 万/966.7 万）。
