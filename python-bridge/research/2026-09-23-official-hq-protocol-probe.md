# 通达信官方行情主站软拒绝根因与新协议握手探测结论（2026-09-23）

## 结论

官方双线主站拒绝 tdxpy 的根因**不是 IP 失效、不是 IP 限流、也不是协议升级无法兼容**，
而是 tdxpy `TdxHq_API.setup()` 连接时发送的三连握手中的 **SetupCmd3 携带旧版
"招商证券金钻"客户端标识串**（`setup_commands.py` 中 `d5 d0 c9 cc d6 a4 a8 af` =
"招商证券"、`c9 cc bd f0 d7 ea` = "商金钻" 的 GBK 字节）。官方主站将该标识会话判定为
旧第三方客户端，对 `get_security_quotes`(0x053E) / `get_security_bars`(0x052D) 返回
4 字节空响应（软拒绝）；**只发 SetupCmd1+2 即可完全解锁官方 48 个主站的行情、K线、指数**。

- 探测脚本：`research/tdx_official_protocol_probe.py`（E1-E10 变体矩阵，可复现）
- 修复：`main.py` 顶部 `TdxHq_API.setup` 运行时补丁（跳过 SetupCmd3），
  回退开关 `TDX_KEEP_TDXPY_SETUP3=1`
- 服务器池：`main.py` 读 `tdx_hosts.json`（官方 48 + 国泰君安兼容 10），扫描面板
  `/api/tdx-servers` 与重连候选池 `candidate_servers()` 共用该文件

## 证据链（E1-E10 关键项）

| 实验 | 官方主站 | 国泰君安对照 | 判定 |
|---|---|---|---|
| E1 基线 quotes（三连握手） | 4B 空壳 `01 26 00 00` | 85B 真实行情 | 软拒绝确认 |
| E2 跳过全部握手 | 超时无响应 | 超时无响应 | 握手是两代服务器都必须的 |
| E4/E5/E6/E7 flags/压缩位/版本字节/种子 全变体 | 仍 4B 空壳 | 变体帧失效或正常 | 单字段变体不可解锁 |
| E8 命令字邻域(0x053C-0x2111) | 一律不回包至超时 | 无效命令 | 0x053E 被认识但被故意拒 |
| **E9 只发 SetupCmd1+2** | **行情/K线/指数全部正常** | 正常 | **毒源=SetupCmd3** |
| E10 只发 SetupCmd3 | EMPTY | EMPTY | SetupCmd3 不能独立成立 |

命令白名单摸底（官方主站，三连握手下）：`get_security_count`、`get_security_list`、
`get_minute_time_data`（当日/历史）正常——证明会话与帧解析完全有效，拒绝仅针对
quotes/bars 命令；SetupCmd3 在场与否是唯一判别因子。

## IP 列表现状（同期排查结论）

- 前端 140 个旧 IP = `tdxpy.constants.hq_hosts`(102) + `mootdx.consts.HQ_HOSTS`(38)，
  两包均为 PyPI 最新（0.2.7 / 0.11.7）且列表未再更新。
- 官方现行表：`D:\APP_SOFT\TDX\connect.cfg [HQHOST]` 48 个主站（GBK ini，本日解析）。
  旧 mootdx 表仅 12/38 与现行 IP 重合，tdxpy 102 个旧券商 IP 与现行表 0 重合。
- 国泰君安段仍走旧协议：`117.34.114.14/15/16/17/18/20/27` 7 个可用
  （113.105.92.x 东莞段已被软拒绝，与官方主站同款行为）。

## 生产改动与验证（2026-09-23）

1. `python-bridge/tdx_hosts.json` 新增（58 候选）；`main.py`：
   `load_tdx_hosts()` + `candidate_servers()` 追加池候选 + `scan_tdx_servers()` 文件优先。
2. `main.py`：`TdxHq_API.setup` 补丁跳过 SetupCmd3（`TDX_KEEP_TDXPY_SETUP3=1` 回退）。
3. bridge 重启后 `/api/tdx-servers` 返回 58 节点（7 可用 + 48 官方 TCP 可达 + 3 不可达）。
4. 端到端：`POST /api/tdx-servers/select` 切到官方主站 129.204.230.128（深圳双线7）→
   行情循环 236/236 全收、0 失败；运行中自动跳到 43.139.95.83（深圳双线6）仍 236/236；
   已切回 117.34.114.14（国泰君安），两种主站均可正常服役。

## 回退方式

- 握手补丁：设环境变量 `TDX_KEEP_TDXPY_SETUP3=1` 重启 bridge。
- 服务器池：还原 `tdx_hosts.json`（删除后自动回退 tdxpy/mootdx 内置 140 列表）。
- 两者均为 `main.py` 内最小 diff，可直接 git revert 对应提交。

## 补丁对旧 140 列表的复活效果（2026-09-23 追加实测）

用补丁后握手（SetupCmd1+2）重扫原 tdxpy+mootdx 内置 140 个 IP：**44 个可用**（补丁前 7 个）。

- 复活构成：海通 7、杭州电信/联通 5、华林 4、广发 3、上海电信主站 Z1/Z80(含 80 端口)、
  北京联通主站 Z80(80 端口)、安信 1、以及与官方现行表重合的上海/广州/深圳双线主站与
  武汉电信主站1 共 14 个。
- 其余 96 个为真死 IP（TCP 不通或仍拒绝），任何握手都救不回。
- 与 `tdx_hosts.json` 去重后**净增 23 个 `legacy-recovered` 节点**，池总数 81。
  这些是 aging 基础设施，定位为官方 48 主站之后的兜底层。
