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
- **工作台消费端已上线（2026-10-27；2026-10-28 更名「板块行情」+ 精选/行业页签）**：JEV 叙事
  工作台（:8008）侧栏「KPL 行情 › 板块行情」——「精选」页签=强度排行（含服务端
  list_son 二级板块，序号 n / n.k），「行业」页签=881xxx 行业板块（2301 树 flag='4'，
  104 个并入订阅，App「行业」同款，仅实时模式）——当日走本链 WS（经 :8000 中继，
  :8002 新增 `POST /api/kpl/subscriptions` 动态订
  阅），历史走 HTTP 直连（`kpl_ranking_service.py` + `GET /api/kpl/sector-ranking|
  sector-stocks`，凭据走 `mapping_refresh` 公共出口）；quotas[2]/[3]/[7]/[8]/[9] 列
  已独立源核实（§四），强度（[56]）/涨停家数（`zt_stocks` 事件按 plate 顿号归属聚合，
  口径=当前封住，与 App「涨停」列含触板口径不同）/封单额/涨停时间后续逐项接。成分股
  分页一批 100 只（`sector-stocks?page=`，服务端 st=1000 单发全量+30s 缓存切片）。
- **直播双流合同（2026-10-28 反汇编实测）**：
  ① 解说流（App 直播页同源，默认）：`a=ZhiBoContent&c=ConceptionPoint`（apphwhq 域，
  **需 App 凭据**UserID/Token/DeviceID 走 mapping_refresh 公共出口，仅进请求参数不入库）；
  反汇编路径：网页版 szlive.html+szlive.js（pchq 域需登录态）→ apphwhq 同参数可用，
  与 App 直播页逐字一致（样本 zhibo_raw.json）。响应 {List,Notice,Status,Time,date,errcode}；
  List 项 ID/Time(epoch)/Comment/Type/PlateCode/PlateName/PlateZDF/Stock=[[code,name,pct],…]。
  内容=AI 大模型根据行情自动生成（App 同款标注）；15s TTL；读口 `GET /api/kpl/live?st=`。
  ② 个股异动雷达流（个股级，App 市场雷达同源）：`a=Radar&c=HomeDingPan&apiv=w38`（匿名），
  每页约 15 条，5s TTL；读口 `GET /api/kpl/radar?st=`。
  两流历史变体（HisConceptionPoint/pchis）未验证，v1 仅实时（不猜数）。
  消费端：工作台「KPL 行情 › 直播」——左栏文本流页签（解说 15s / 雷达 8s 轮询），
  右栏个股表字段同板块行情个股列表（解说模式未到流用消息内 pct 兑底；地位/换手/概念
  无来源显式 `--`；行情列 3006 WS 覆盖，涉及个股动态并入订阅）。pytest 全 mock。
- **市场雷达/直播流合同（2026-10-28 反汇编实测）**：`a=Radar&c=HomeDingPan&apiv=w38`
  （apphwhq 域，匿名可调，无 Token/UserID 亦可；社区 apifox 接口文档 + 直连双源验证）。
  响应 `{list:[...], num, date, time, ttag, errcode}`；list 项字段：time(epoch 秒)/
  status/stock_name/stockid/plate_type/status_color/zf/content/content2/LBstatus。
  每页上限约 15 条（st=60 仍返 15），Index 翻页；纯个股事件流（plate_type=1），无官方
  长解说（直播页顶部长文另源未定位，不猜数）。status_color 实测仅见 1（涨停系红）。
  消费端：工作台「KPL 行情 › 市场雷达」——左栏文本流（8s 轮询，服务端 5s TTL 兑底，
  不共用 30s 缓存）、右栏个股表（字段同板块行情个股列表；地位/换手/概念雷达无来源
  显式 `--`，连板列用 LBstatus；行情列由 3006 WS 覆盖，直播涉及个股动态并入订阅）。
  读口：`GET /api/kpl/radar?st=`。pytest 全 mock，零真实请求。
- **直播语音播报合同（2026-10-28）**：解说/雷达新消息接入 `tools/VoiceWorker`（本地
  32145，`POST /speak {text≤200}`、`GET /status`、`POST /stop`，无 CORS 头）。
  代理读口：`GET|POST /api/kpl/voice/status|speak|stop`（:8000 已放开 CORS，页面直呼，
  不依赖 :3000）。用户裁决：**语音端口开启=自动播报**——开关默认开（localStorage
  `kplLiveVoice`）；冷启动首轮流只武装不播报（历史积压不当新闻）；**单一播报：仅当前
  激活流入队，切流即 POST /stop 清旧队列+在途轮询作废，两窗口永不叠加发声**；
  离线 fail-visible 200+offline，每轮探测自动接上。播报文本：解说=
  （板块名，）+去 AI 标注全文；雷达=名称，状态，短句。路由测试全 mock（零真实发声）。
- **二级板块显示合同（2026-10-28 反汇编实测）**：App 精选板块的子板块行不是客户端按强度
  过滤，而是排行接口响应顶层 ``list_son``（获得子板块行的父板块 id 列表）+ ``list_soninfo``
  （子板块行，同 19 列格式）服务端直接下发，等长按位配对。实测样本：list_son=[801159]、
  list_soninfo=[智元机器人 801928]，与 App 同屏一致；同期排行宇宙 241 板块中 40+ 个在
  2301 树里有子板块，但服务端仅下发此 1 个——旧启发式（父强度>1000 且子强度>0，
  2026-10-27 用户裁决）会多出数据采集/滚珠丝杠等 10 行，已推翻。`get_sector_ranking`
  已解析为 ``sons``（不等长时不猜配对，透出 ``sons_unpaired``）；工作台精选板块渲染改用
  sons 名单（sons 从未拿到时才回退旧启发式）。Type=1 查史与 Type=2 实时响应均带此字段。
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
- 读口：`GET :8002/api/kpl/daban-list?pid_type=8|0|6`（:8000 同路径代理透传）→
  `{ok, items[合并全量], max_size, pages, pages_expected, pages_missing, date, ts}`；
  页缺口显式透出（如即将涨停页盘后 maxSize=30 但推送 items 空，属上游语义非链路故障）。
- 无快照（采集未运行/未订阅）返回结构化降级 `{ok:false, degraded:true,
  reason:"no_daban_list_snapshot"}`，不伪装空列表。
- 前端：WS `daban_stocks` 事件（单页 30 行）只做节流触发（1.5s），渲染唯一源=REST 合并快照，
  页合并逻辑单源在后端（避免双写漂移）。
- **【竞昨比】列（2026-10-28 用户需求，工作台派生列，非 App 原生列）**：
  `竞昨比 = 竞价成交量 / 昨日成交量 × 100%`。2103 竞价 quotas（28 位实测）**不含量列**，
  故派生：`竞价成交量(手) = 竞价成交额 ÷ (竞价价 × 100)`，`竞价价 = 昨收 × (1 + 竞价涨幅/100)`；
  原料读口 `GET /api/kpl/daban-prev-day-basis?date=&codes=a,b,c`（`kpl_ranking_service.
  get_daban_prev_day_basis`，腾讯 ifzq 日K：**param 必须带 sh/sz/bj 前缀**，裸码返 param error；
  qfq 前复权价=除权基准价，与 App 竞价涨幅分母同口径；量列不复权=手）。按日缓存 12h、
  失败单股 10 分钟内不重试，`missing` 显式透出（fail-visible，列显 `--` 不猜数）。
  口径自洽校验（2026-10-28 盘中样本 8/8）：`竞价成交额/实际流通` 与 2103 `竞价换手` 逐只吻合
  （0.46↔0.46、0.54↔0.55、0.12↔0.12…）；竞昨比实测 0.51%–4.29%。
- **空帧抑制（2026-10-28 盘中修复）**：风向标页（pid 6）上游帧全部为 Resp 形态（无 push），且在
  列表重建窗口高频回空帧（实测 35s 内 14 帧 12 空/2 满 25 项）——collector 原先每帧无条件覆盖页
  缓存，读口绝大多数时间为空（页面恒无数据）。已改为**空帧不覆盖非空页缓存**（仅刷 ts + 记
  `last_empty_seen`；空帧本身仍 fail-visible 广播），真清空（盘后）随日期切换/采集重启重置；
  含回归用例（test_kpl_collector_service 空帧抑制三段式）。

### 11.3 顺带根治（同轮）：3006 订阅分块

- 精选板块引导后订阅 id≈713，`3006 HQStockIdListReq` 原为**单帧全发** → 每会话触发
  server error 1106（单请求 id 超 ~241 上限，工作台横幅可见）。已改为与 3001 同款 200 分块
  （`_chunks`），实测横幅消失、行情照常到流；含 3 帧全量无丢失回归用例。

### 11.4 历史回看读口（HisDaBanList，2026-10-27 三期；2026-10-28 验收收口）

- 合同（逆向自 BiddingZTlQuotaPresenter.a0 → ox0.L2 → j00.P1 → qg.q1；
  **2026-10-28 实测修订：该端点为严格白名单参数**）：POST apphis
  ``a=HisDaBanList&c=HisHomeDingPan&Day=YYYY-MM-DD`` + 全局五件套（DeviceID/apiv/
  PhoneOSNew/VerSion/Red）+ 凭据；**Day 之外多传任何键（PidType/Type/Order/Is_st/
  Index/st/Filter 家族全部）一律 errcode 1020**，裸参数返回真数据。因此 pid_type 在
  服务端不透传上游（保留作路由/前端语义），无分页（Index/st 不被接受）；**三页签返回
  同一默认集合**（实测 2026-10-27 仅 9 行 ≠ 竞价页当日快照 183 行），页签过滤待 MITM
  抓包对照真实 App 请求后补——前端已有 note 横幅显式透出，不伪装成页签数据。
- **历史行格式与 socket quotas 不同**——row[0]=代码、row[1]=名称、row[2]=labelType(int)、
  row[3]=板块标签，row[i]（i≥4）直接按统一数组位取值（解析器 `_parse_daban_history_row`，
  列名表 `_DABAN_HIST_POS_NAMES`）。
- **列语义已独立源核对收口（2026-10-28，EM push2his + 腾讯/新浪不复权 K 线交叉 + 自洽验证）**：
  pos4 涨幅（002639=5.24%、603366=5.26% 双源精确一致）、pos13 成交额（2231432699 与 EM
  分毫不差）、pos17 价格（14.27/7.41）、pos14 实际换手×pos15 实际流通（24.59% = 东财成交量
  ÷实际流通盘，实际流通口径确认）；pos12 主力净额沿用既有语义。**pos29 换手率与 pos18-27/
  30-32 本轮默认集合内全 0/恒等，无法核对，待 App 历史页同屏或 MITM 抓包补**。坑：历史列
  核对必须用不复权源（腾讯 qfq 曾致 603366 pct 表观 3.20% vs 真实 5.26%）。核对样本与结论：
  `.tmp_review/hisdaban_column_check_20261028.json`（本地）。
- 读口：`GET /api/kpl/daban-list-history?date=&pid_type=`（:8000 直连 HTTP，与
  sector-ranking 同层）；30s TTL 缓存按日共享（三页签同日共用一份，兑限频）；空列表抛结构化
  `upstream_empty_list`（fail-visible，不伪装空页；历史模式单发不轮询，重拉需切换日期/重进页签）；
  历史 note（默认集合口径说明）在成功态同样经页内横幅透出；前端三页（集合竞价/即将涨停/风向标）已加
  精选板块同款日期切换 + 回实时工具条，历史模式单发不轮询。
- **2026-10-27 晚上游异常实录（阴性记录，已于 2026-10-28 复测解除）**：当晚 HisDaBanList
  全参数形态 errcode 1020 / ZhiShuStockList_W8 errcode 0+空列表，两种形态抖动；
  游客/现役凭据/socket 凭据、apiv w21-w48、Day/Date/Isst 变体、apphis/apphwhq/applhb
  三域名全试一致；同通道 RealRankingInfo/DaBanList/plate-tree 正常。时段内本机探针 ~50 发
  （远超 App 正常频率），疑触发上游频控——当晚已停止探测。
  **2026-10-28 验收复测：3 发（07:47-07:50，间隔≥65s）date=2026-10-27 pid_type 8/0/6
  全 ok=true 返真数据，1020 解除；根因即参数白名单——旧行为多传 PidType 等键被拒**。
  探测登记 `.tmp_review/hisdaban_retest_log_20261028.json`（本地）。

### 11.5 打板头订阅（2100 DaBanHeadResp，KPI 三卡昨日侧来源，2026-10-27）

- 工作台 kpl 组 KPI 条重排（用户需求，App 市场情绪头同款）：删综合强度/板块强度/亏钱效应/
  空头气氛四卡，增**涨停板（今/昨）/封板率（今/昨）/跌停股（今/昨）**三卡（涨红绿跌，
  涨跌家数卡同步上色）。
- **数据源=socket 2100 打板头**（Hq.DaBanHeadResp：f1 todayZT/f2 yesterdayZT/f3 todayFB/
  f4 yesterdayFB/f5 todayDT/f6 yesterdayDT，f3/f4 为 float 封板率%；collector 订阅链追加
  EmptyReq 帧，事件名 daban_head）：**与 App 同屏精确一致**（41/55、59%/71%、21/25，
  yesterdayFB=70.51→71%）。封板率今日值=100−2119 破板率（59.42→59%）。
- HTTP 兜底 `GET /api/kpl/daban-head?date=`（HisDaBanHeadInfo）保留：socket 未供数时前端
  60s 节流拉取。**响应结构已按 2026-10-23 真实样本核对**：raw.nums.{tZhangTing/lZhangTing/
  tDieTing/lDieTing(int)、tFengBan/lFengBan(float 封板率%)}，t=查询日、l=前一交易日；
  上游限频（约分钟级 1 发，超频 1020），前端 headByDate 缓存 + 55s 节流自愈重试。
- **KPI 跟随日期（2026-10-27 用户需求）**：kpl 视图=工具条日期（kplDateChange/回实时），
  打板三页=各自日期；历史模式三卡走 daban-head（picked 日/前一日），涨跌家数/大盘指数/
  预测量能无历史来源显 "--"（卡题标注）。实测 10-23：84/33、87%/59%、7/49。缺数显式 "--"。
- **KPI 两卡历史修复（2026-10-28）**：大盘指数（沪/深/创）历史=新增 `GET /api/market/index-history`
  （腾讯 ifzq 日 K，pct 自前收盘计算）；涨跌家数历史=新增 `GET /api/market/breadth-history`
  （东财 push2ex 涨跌分布**仅最近完成交易日可得**，本地 `data/market_breadth_daily.json` 逐日持久化累积，
  更早日期结构化缺数 fail-visible 不伪装；服务 `backend/services/market_history_service.py`，
  测试 `test_market_history_service.py` 全 mock）。历史 note/缺数原因经 KPI 卡副行/页内横幅透出。

### 11.6 测试与证据

- `test_kpl_daban_protocol.py`：2103 请求构造（App 基线字节）/解析（竞价列+即将涨停列+乱码
  fail-visible）/注册表；`test_kpl_collector_service.py`：会话帧序含 14 帧 2103 分页订阅、
  页合并快照读口、3006 分块；`tests/api/test_kpl_proxy_routes.py`：daban-list 透传+502、
  daban-prev-day-basis 透传/校验；`test_kpl_ranking_service.py`：HisDaBanList 白名单参数/空列表
  fail-visible/按日共享缓存、竞昨比原料（昨日日K 解析/批量失败隔离/失败 10 分钟不重试）；
  `test_market_history_service.py`：涨跌分布合桶/本地累积缺数/KPI 指数历史。
  KPL 专项合计 **121 passed**（2026-10-28 实跑，全 mock，零真实连接）。
- 证据工件（本地 .tmp_review/）：`kpl_daban_frames_20261027.txt`（KPL_DEBUG 帧转储，
  含 count=200 请求密文）；真实快照对照：竞价页 183/183 全量零缺口，赛福天行与 App 竞价页
  同屏逐项一致（13.02 亿/10.01%/机器人概念、海洋经济/4连板/528.0 万/966.7 万）。

## 十二、总览页大盘走势（2026-10-28 增补，复刻 APP 直播页分时图）

### 12.1 读口与数据源

- `GET /api/market/index-minute?code=sh000001`（:8000，同步 def 入线程池）→
  `{ok, date, code, name, prevClose, points:[{t:"HHMM", price, vol, amount}], lastPrice,
  totalVol, totalAmount, source:"tencent_ifzq_minute"}`。
- 上游：腾讯 `web.ifzq.gtimg.cn/appstock/app/minute/query?code=<code>`（匿名、无凭据），
  行格式 `HHMM 价 累计量(手) 累计额(元)` → 归一化为**逐分钟增量**；昨收取 `qt[4]`；
  名称取本地 `INDEX_CODES` 映射（上游 name 为 GBK，不依赖其解码）。
- 缓存：20s TTL（`idxminute:<code>`）；空分时/缺昨收 → `upstream_empty_minute` 结构化 502
  （fail-visible，不伪装成平线）；非支持代码 → `invalid_code`。
- `:8008` relay 页新增 `/api/market/*` 透传前缀（与 `/api/kpl/*` 同款，不经 :3000）。

### 12.2 展示合同（总览页）

- 卡片「📈 大盘走势 · 上证指数分时」取代原「近15日 · 连板指数 vs 热度温度」（后者连同
  `drawChart()` 一并删除；相位分线图 `relayChart2` 不受影响）。
- 图 = 对称价格轴（昨收为中轴，顶/底分别标价格与涨跌幅，涨红跌绿）+ 昨收虚线 +
  蓝色分时线/渐变面积 + 逐分钟量柱（幂律压缩，开盘巨量不压平全天；分钟价升红/跌绿）+
  轴标 09:30 / 11:30-13:00 / 15:00。
- 看点气泡 = `/api/kpl/live?st=20` 最近 3 条解说按 `Time` 钉到对应分钟点，红底白字胶囊，
  三档垂直分层 + 横向避让，上方空间不足时翻到点下方；悬停 `<title>` 出全文。
  直播流不可用 → 只缺气泡，卡片 hint 显式标注「看点气泡不可用」，不影响分时底图。
- 刷新：进入总览页即取，30s 轮询（仅总览页运行）；失败显式原因 + 自动重试。
- 底部读数移出 SVG（避免压轴标签）：成交额/总量/末点时间价格涨跌幅/昨收/来源。

### 12.3 测试

- `tests/market/test_market_index_minute.py`（4 passed，全 mock httpx）：增量归一化、
  空行 fail-visible、非法代码、路由 502。

## 十三、龙虎榜链路（2026-10-29 增补，全部开火实测）

### 13.1 协议链（三条，全部预登记开火验证）

- **2112 会不会上龙虎榜预测**（链 A 主链，`kpl_daban_protocol.CMD_FORECAST_LHB`）：
  ServiceHqDaban 族 `SubForecastLHB(ForecastLHBReq)→ForecastLHBResp`，0x40 通道
  （PKG_ROUTE + ext=`02 0840`）。Req 基线 count=30/sortType=1/quotaType=0
  （LhbWillStockModel.k(2112)）；Resp 23 字段 Item（reason 上榜原因/plate/hot_val/
  main_net_amount 等）。09:35 前回 total=0 属正常时段态；之后满帧 26 items push。
- **3004/3101 RealtimeLHB**（链 B，`kpl_lhb_protocol.py` 新模块）：ServiceHqList 族
  `SubRealtimeLHB / GetRealtimeLHBRangeData`，同 0x40 通道 ext=`02 0bbc/0c1d`。
  Req 基线 quotaType=6/sortType=1/limitType=4/bjsType=1/count=30（App 原 UI count=1，
  采集放宽；`kpl_lhb_protocol.REALTIME_LHB_BASELINE`）。Resp total≈5438（全市场实时
  选股口径，非龙虎榜榜单专属）、minMT/maxMT=HHMM；items 复用 GroupStockQuotasResp.Item
  （70 列 quotas：[0]=板块标签 [1]=现价（nn0.l 实锤），其余原样保留展示层标注）。
  **已知边界**：3101 无区间/带当日区间均零应答（推断需 indexType 指数 id，非关键路径）。
- **HisBeOnTheLHB 历史 HTTP**（`kpl_lhb_history.py`）：POST apphis
  `a=OnTheLHBList|OnTheLHBStock&c=HisBeOnTheLHB&Date=YYYY-MM-DD`——**a/c 与 D1 参数
  顺序互换是关键坑**（mo0.d 第一参数→c、第二参数→a；记反即 1020）。OnTheLHBList=
  按上榜原因分组榜单（Reason/Index/stockList 12 列）；OnTheLHBStock=个股行 22 列
  （字段族与 2112 Item 同源）。当日未生成 info=[] + orderSign（结构化空态）。
  **分页坑（2026-10-30 修复）**：两端点默认页极小（个股 9 行/分组 3 组），必须显式
  `st=300` 翻满（实测 10-29 st=300 饱和：个股 129 行/分组 20 组去重 129，两端点一致；
  st=100 时个股端点被截到 100 行）；`Count` 字段≠info 行数（同日 61 vs 129），不可当
  总数用；`st` 必须进缓存 key。
- **营业部个股榜/机构榜 HTTP**（`kpl_lhb_sale.py`，2026-10-30 开火实测接入）：同域同
  参数合同——`a=GetStockList|GetAgencyListV2&c=LongHuBang&Time=YYYY-MM-DD&Index=0&
  Type=0&STAT_SDK_TYPE=500`（一页全量，实测 10-29：个股榜 69 行/机构榜 42 行）。
  GetStockList=`list` 每股一行（ID/Name/BuyIn 席位买入额元/JoinNum 疑席位家数语义待证/
  Turnover 成交额/IncreaseAmount…；`Count` 字典语义未考透传不消费）；GetAgencyListV2=
  **`List`（大写 L）** 每股一行（BuyIn **机构净买额元可负=净卖出**/JoinNum 机构家数/
  FengKou 风口不消费）；parse 后 raw 原样保留。同族 UpdateList 未接，边界显式。
- **营业部成交榜 HTTP**（`kpl_lhb_sale.py`，2026-10-29 逆向 j00.F + le0.p + 开火实测）：
  POST applhb（API_LHB 专用域）`a=GetBusinessList&c=LongHuBang&Time=YYYY-MM-DD&Index=0
  &Type=0&STAT_SDK_TYPE=500`（500 一页全量，App 每页 100 分页）；返回
  {ID, Name, Buy, Sell(元原样), JoinNum}，实测 2026-10-28 Total=229。**当日盘前/盘中
  list=[] 属结构化空态（榜约 17:00 盘后生成）**。同族 GetAgencyListV2（机构榜）/
  GetStockList（个股榜）未接，边界显式。证据 `.tmp_review/lhbsale_probe_results.jsonl`
  （本地，不入仓）。

### 13.2 开关与读口

- collector 开关：`daban_lhb=True`（2112）、`lhb_realtime=True`（3004/3101），构造器默认关、
  独立于 `daban_subs`。**生产入口 serve_kpl_socket 默认全开**（环境变量
  `KPL_DABAN_LHB=0` / `KPL_LHB_REALTIME=0` 显式关闭，切换需重启进程；2026-10-29 起
  生效——此前生产未传参导致 ：8008 页面「无快照」降级）。生产建议与 daban_subs 同开：
  最小订阅面会话寿命极短（16 sessions/100s error 1002 循环；全订阅面 2 sessions/100s）。
- 快照读口（:8002 / :8000 透传 / :8008 页面消费）：`GET /api/kpl/lhb-forecast`、
  `/api/kpl/lhb-realtime`（2112/3004 均空帧抑制同 2103 规——2112 以 total=0 为语义清空，
  午间休市推流 total>0/items=[] 不覆盖非空快照；无快照结构化降级 fail-visible）；
  `GET /api/kpl/lhb-history?date=`（:8000 本地处理 kpl_lhb_history，上游限频 30s TTL）；
  `GET /api/kpl/lhb-sale?date=&type_=0`（:8000 本地处理 kpl_lhb_sale 营业部榜，30s TTL；
  缺 date 422，空榜带结构化空态 note）。
- :8008 relay 页「KPL 行情 → 龙虎榜🏆」页签：预测卡 + 龙虎榜合并表卡（同板块行情
  个股列表形态；头部「选股/营业部」分段切换 + 日期选择：选股=默认当日 3004 实时
  5s 轮询、选历史日期同表切换 HisBeOnTheLHB 分组回看；营业部=GetBusinessList 按日榜
  （# / 营业部 / 买入额亿 / 卖出额亿 / 参与次数）；「今日」按钮回当日；回看/营业部模式
  轮询照跑仅停渲染，banner 按 view 分流互不顶掉；缺字段 `--`、降级 banner、
  失败保留旧快照不伪装）。DOM 验证：**人工执行 Playwright 断言（实时/回看/营业部
  三视图切换全过），脚本与截图只存本地 `.tmp_review/`，未入仓**
  （专项契约由 `tests/hotlist/test_relay_page_window.py` 与 :8000 透传 mock 测试覆盖）。

### 13.3 资金字段口径（task-3 裁决，防误消费）

- **×10000 缩放假设证伪：全部 int64 资金/市值/成交额字段 = 元原样**（2026-10-28
  603696 双源比对：成交额/市值与东财公开值精确一致）。详见
  [lhb-scaling-verification.md](lhb-scaling-verification.md)。
- mainBuy+mainSell=mainNetAmount（**卖出记负**）；口径=盘中主力大单资金流（与东财
  主力净流入同族差 ~0.2%），**非交易所龙虎榜席位额**，JE 语料消费须标注。

### 13.4 JEV 语料供给（task-6）

- `backend/analysis/hotlist/jev_lhb_ammo.py`：collect_lhb_facts（取数+归一）+
  build_lhb_facts_lines（纯事实行）。零引擎判断产物（禁喂清单合规）；取数失败/
  结构化空态显式 `--` 行不伪装。方向线消费入口与 driver/resonance ammo 同构；
  **题材龙头语料同源消费（AMMO 2026-10-30a，2026-10-30 用户指示）**：
  `theme_leader_ammo.lhb_line` 按「待判龙一+板内封板成员/双龙一+板内成员」代码过滤
  接入个股级与板块级叙事（四种结构化状态全 fail-visible；主力净额口径行内标注非
  席位额；题集 v13 hash 不变；预登记 theme-leader-nextday-preregistration-20261020
  §23）。**席位/机构扩维（LHB 事实层 2026-10-30c）**：collect_lhb_facts 新增
  stock_board/agency 两维（GetStockList 席位买入额/GetAgencyListV2 机构净买额可负），
  lhb_line 对相关个股追加对应段（不在榜/端点失败缺席不伪装）。
  **语料精简（AMMO 2026-10-30d，2026-10-30 用户确认删除清单后执行）**：删重复自我解释
  与工程注记（「无数据 ≠ 无催化」复述/fail-visible 行话/可推导语气/端点名/空间锚定义
  复述等），事实与防误读锚全保留；近 N 日家数序列 ≥3 日才出行；共享行（盘面事实/涨跌比）
  同步生效于打标链；题集 hash 不变，预登记 §23 补记。
  **15:00 收盘总结 + 板块名后缀桥（AMMO 2026-10-30e）**：两级叙事新增「盘面总结
  （KPL 15:00）」行（直播归档 15:00 空板块条目单载，缺席不出行；从板块播报排除防双现）；
  `board_keywords` 经济/产业后缀确定性互认（冰雪经济↔冰雪产业 10-29 漏配实证）。
- audit 同步：docs/hotlist-jev/jev-direction-material-audit.md §3 C 级第 4 条
  「龙虎榜未采」→ 已接入（大单监控线另行预登记）。

### 13.5 测试与证据

- pytest（全 mock 零真实调用）：`test_kpl_daban_protocol.py`（2112+packed varint）、
  `test_kpl_collector_service.py`（快照/空帧抑制/JSON 序列化合同）、
  `__tests__/test_kpl_lhb_history.py`（8）、`test_jev_lhb_ammo.py`（6）、
  `tests/api/test_kpl_proxy_routes.py`（透传+降级）。
- 开火证据（本地 .tmp_review/，不入仓）：`lhb2112_probe_events.jsonl`（39 帧）、
  `lhb3004_probe_events.jsonl`（68 帧）、`lhbhis_probe_results.jsonl`、
  `lhb_snapshot_probe_events.jsonl`、`lhb_page_screenshot.png`、侦察笔记
  `d:\dragon-board\.tmp_review\lhb_recon_notes_20261028.md`。
