# KPL 订阅注册表化 + 211 批量订阅重构方案（2026-11-17）

> 状态：**P0-P4 全部实施，探针全部开火裁决（2026-11-17，全 mock 413 passed）**。
> 211：有条件受理、仅 hqDaban 族可批、收益不抵风控面 → 保持 direct 不启用；
> 402：语义钉死（ack=28B 状态块，subIds 按 seq 取原请求），flag 仍默认关——
> per-stock 共享 subId 误退阻塞（§12），需唯一 subId/topic 退订设计+探针后启用；
> P4：610 重发第 5 次→1106 确定性杀连（受控实验），**默认已切 KPL_KA_MODE=off**；
> 批内盘中推送交付已验证（==direct）。本文是 README §3.5「211 化是后续可选
> 重构（需协议 RE）」的 RE 收口与重构设计。flag：KPL_SUB_BATCH=direct、
> KPL_UNSUB_ENABLED=0、KPL_SUB_REGISTRY=1、KPL_KA_MODE=off。
> 实施记录见 §10，开火记录见 §11，下午盘裁决见 §7.1。
> 红线沿用 README §六：pytest 全 mock，零真实 KPL 连接 / 零真实 WBE / 零真实 ELF。

## 0. 结论先行

1. **用户前提需修正（源码实锤）**：当前 App 版本**并不发送 211 SubReqs**。
   对 `.tmp_review/main_src` + `c2_src`（payload_dex 反编译）全量检索，`SubReqs`
   只出现在两处：`Base.java`（proto 描述符）与 `qn0.o()`（211 **ack 展开**处理器）。
   App 实际订阅路径是**单帧 0x40 + ext attr2=subId**（`SocketViewModel.y` →
   `SocketRepository.m/k`），注册表是**客户端维护**的（`qn0.e` 列表），subId
   客户端给 hint（观测值=cmd）、**ack 帧 attr2 回填服务端分配值**。
   → 211 是「proto 与 ack 处理在、发送路径不在」的**服务端可选批量信封**，
   服务端是否仍启用、请求侧字段语义均**未验证**。
2. **重构主轴 = 注册表化（App 同款，已破译定案）**：subId 注册表 + ack attr3 topic
   捕获 + 402/pkg 0x50 退订 + 220 选择性重发。这层不依赖 211，单帧形态即可落地，
   风险低、收益确定（220 精准续命、真退订、订阅面可观测）。
3. **211 批量 = 可选增强（探针先行）**：把每会话 ~170 帧订阅爆发压到 ~20 帧量级，
   直接削弱「批量订阅=机器指纹」风控面（README §3.4 假说判别项）。但必须先探针
   钉死请求侧语义（§1.3），失败自动回退单帧（熔断），默认关。
4. **610 保活（每 8 tick 重发）确认非 App 行为**：App 无任何客户端心跳
   （README §3.5 已定案），改为 flag 门控 A/B，证据充分前默认保留现状。

## 1. RE 事实合同（源码证据，全部可复核）

证据根：`.tmp_review/main_src/sources/`（与 `c2_src` 交叉一致；gitignored 本地工件）。

### 1.1 pb 合同（`com/yzj/kaipanh/newindex/common/socket/data/Base.java:34` 描述符逐字）

```proto
message SubReqs {                    // cmd 211 批量订阅信封
  repeated Item reqs = 1;
  message Item {
    uint32 seqId   = 1;              // 项内虚拟 seq（ack 回填到逐项包）
    uint32 cmd     = 2;              // 内层订阅 cmd（2103/2203/2013/3001…）
    uint32 version = 3;              // 语义未验证（推测 23xx VersionReq 版本）
    uint32 codec   = 4;              // 语义未验证（推测 data 编码：0 明文/1 GCM）
    uint32 subId   = 5;              // 订阅 id hint；ack 回声带服务端分配值
    bytes  data    = 20;             // 请求侧=内层 req pb；ack 侧=首帧 resp 快照
  }                                  //   （qn0.o 用 x(data, cmd) 按 resp 解析）
}
message UnsubReq   { repeated string topics = 1; }   // 按 topic 退订（未见发送路径）
message UnsubIdReq { repeated uint32 subIds = 1; }   // 按 subId 退订（cmd 402 在用）
message ResubNt    { repeated string topics = 1; }   // cmd 220 注册表失效通知
```

### 1.2 App 实际订阅/注册表生命周期（定案，重构主轴依据）

| 环节 | 源码位置 | 事实 |
|------|----------|------|
| 订阅发送 | `SocketViewModel.y`（SocketPresenter.java:186-205 同构） | `ux0.v().c(cmd).g(d).f(true).d(pb).e(4)` 单帧 0x40；`SocketRepository.m(subId, pkt)` → `k()` 置 **ext attr2=subId** |
| subId 取值 | `w30.java:230`、`StockInfoBottomSelectBar.java:175`、`AttachAppTimerTask.java:341-349` | 全部观测点 **subId=cmd**（3006/2301/2303/2304）；`SocketPresenter.w(i)=i` 默认 key=cmd |
| attr2 线格式 | `ux0.n()` → `x6.a(int)` → `z6.c(int)` | **z6.c 只写 2 字节 BE**（不是 4 字节！）→ ext = `02 <subId 2BE>`，**与我们现行 `02 <cmd BE>` 逐字节同构** |
| 三列表模型 | `qn0`（PackManager）字段 b/c/d/e | c=已发待 ack（按 attr2 去重）；d=待回复（按 seq 匹配）；e=**已订阅注册表**（「订阅成功, cmd:X, 当前订阅个数:N」）；b=断线重试队列 |
| 订阅 ack | `SocketReaderThread.c()` kind4→msg13→`qn0.o()` | ack 按 seq 匹配 d 中请求；**注册表 key=ack 帧 attr2（服务端分配 subId）**，`s(subId)` 命中则原位更新 payload，否则入 e；**attr3（topic）从 ack 帧复制** |
| 211 ack 展开 | `qn0.o():434-443` | cmd==211 且 payload 是 SubReqs → 逐项构造包 `{cmd=item.cmd, attr2=item.subId, seq=item.seqId, payload=x(item.data,cmd)}` 预置入 d（**强烈暗示服务端随后按 item.seqId 逐项回 kind4 ack**，未验证） |
| 推送路由 | `SocketReaderThread.c()` kind6 + `qn0.m()` | kind6 外层 ext 按**字符串**读入 → attr3；推送按 **attr3 与注册表逐条匹配**（不是按 cmd！）；无匹配则丢弃 |
| 退订 | `SocketRepository.n(subId):132` | **cmd 402 / pkg e(5)=0x50** / `UnsubIdReq{subIds:[subId]}`；kind5→msg14→`qn0.q()` 按 subId 从 e 移除 |
| 220 重发 | `qn0.j(ResubNt)` | topics 空→e 全量重发；非空→`topics.contains(entry.attr3)` 选择性重发；重发走 `sendPacket`（**单帧，不是 211**）；重发项移出 e 待再 ack |
| 断线清理 | `qn0.f()` + msg101 | 断开清空 c/d/e；`t()`（重试标志）包入 b；重连后 b 队列全量重发（=我们「每会话重建订阅面」的 App 同款） |
| seq 计数器 | `t31.c()` | 1 起步递增，**≥32767 回绕到 1**；kind 3/4/5 帧带 seq（`t31.b`），kind 2/6 不带 |
| ext 属性线类型 | `SocketReaderThread.c()` ext 解析 | key1=Long(8B)、key2=Short(2B)、key3=String(len2+bytes)、key4=Int(4B)；kind6 外层 ext 整体当字符串（即 topic=ext 原始字节） |
| 心跳 | kind1（pkg 0x10） | 服务端→客户端单向，无需应答；**客户端零心跳**（§3.5 已定案） |

### 1.3 探针裁决（2026-11-17 实弹开火钉死，用户批准「211开火」；证据链 §11）

| # | 未知项 | 裁决 | 证据 |
|---|--------|------|------|
| U1 | 服务端是否受理 211 | **有条件受理**：codec=1 且仅 hqDaban 全局族（2114/2115/2116）；明文 data → ErrResp 2008 杀连；列表/个股通道（2103/2203/2013）批内逐项拒绝 2000 | plain×2/multi×3 全 2008；gcm 受理会话 45s 健康 |
| U2 | item.data 编码 | **必须 GCM（codec=1）**，data=ENC(内层 req pb)；codec=0 明文→2008 断连 | gcm 对照 plain 唯一变量 |
| U3 | version/codec 取值 | version=0 受理；codec=1 | gcm/multi 会话 |
| U4 | seqId 号空间 | **与帧 seq 共用计数器**；逐项 ack seq=item.seqId 精确匹配 | multi：项 seq 8-12、批帧 13，5/5 ack |
| U5 | 逐项 ack 形态 | **每项一个 kind4 echo**（seq=item.seqId、attr2=subId、attr3=topic）；批 ack payload=**28B 不透明状态结构**（非 SubReqs 回声，DEC 失败，与 110/610 状态帧共享 8B 前缀 `xxxxxxxx00000000`）→ App qn0.o 展开路径在本服务端永不触发 | gcm/multi 帧转储 |
| U6 | subId 分配 | **回声客户端 hint（=cmd）**，未见服务端唯一分配；per-stock 多股同 cmd 会撞 subId（注册表不合并只计数的设计因此必要） | 全部 ack attr2=cmd |
| U7 | 批 ack attr2/attr3 | ext=`02 00d3`（attr2=211，无 attr3） | 帧转储 |
| U8 | 211 帧外层 ext | `02 00d3` 受理且被回声；noext 变体未开火（包络层证据已足：ext 被正常解析回声，拒绝不在 ext 层） | 帧转储 |

**新增实弹事实（超出原矩阵）**：

1. **cmd 110 = 服务器错误通知通道**：payload=ErrResp{code,msg} GCM 加密（DEC 可解），
   非致命不断连；批内被拒项逐项下发 2000，与无 topic 的该项 ack 同时刻出现。
   已落地 `_dispatch` 110 分支（fail-visible 解析上报，不再当 raw）。
2. **批内通道白名单效应**：2103/2203/2013 批内 ack 无 attr3 + 110/2000；direct 对照
   同 5 项全获 topic 零 110（2103 topic 含页参数 `hqDaban|26:20010/2103-0/8:18:1:0:0:0:0:0`，
   2203/2013 per-stock `hqStock|26:20040/2203-1/000001`）→ 批量仅适用 hqDaban 全局族。
3. **推送 ext == ack attr3 topic 逐字节匹配**（3001 推送 5/5）——P1 topic 路由模型
   实弹验证通过；220 选择性重发的匹配基础成立。内联 3001/3006 已补登记（否则命中率观测缺口）。
4. **610 重发应答=48B 状态 blob**（非 AuthResp pb，与 211 批 ack 同 8B 前缀）——P4 保活 A/B 素材。
5. **残留未知已消（2026-11-17 下午盘实弹，§7.1/§11）**：批内订阅盘中推送交付
   ==direct（pushbatch 11/18/16 vs pushdirect 12/19/17，zd_stat/market_overview/
   plate_strength）；28B 批 ack/402 ack 同构不透明状态块语义不影响功能（逐项 ack
   与 seq 回填承担全部注册表语义）。新残留：off 模式 >120s 长窗上限待生产观测。

**灰度裁决（工程结论）**：**KPL_SUB_BATCH 保持 direct 默认，不建议启用 211**——
可批量化仅 ~8 帧 hqDaban 情绪族（2103 的 42 页 + 语料/详情 ~112 帧必须 direct），
每会话 ~170 帧仅省 ~7 帧，收益不抵新增风控面。211 代码路径保留（flag+熔断+
codec=1 安全默认）作归档能力；重构实际收益=P1 注册表（已验证）+P2 402 退订（待探针）。

## 2. 现状差距（`kpl_collector_service.py` / `kpl_socket_protocol.py` HEAD 4b0360ba）

| 差距 | 现状 | App 模型 | 影响 |
|------|------|----------|------|
| 无注册表 | `_resub_cache`=原料缓存（cmd+ext+req 去重，500 上限），无 subId/topic/状态 | qn0.e 注册表（subId key + attr3 topic + ack 状态） | 220 只能全量重发；订阅面不可观测 |
| 220 全量重发 | `_handle_resub_nt` 两种情况都全量重入 setup 队头 | topics 非空→选择性重发 | 重发风暴（~170 帧）本身是风控面 |
| 无退订 | `set_subscriptions` 只改 3001 轮询清单；2203/2013/detail 订阅面只增不减，靠会话重建清零 | 402/0x50 UnsubIdReq | 掉出池成员持续收推送（浪费+指纹）；merge 语义无法收缩 |
| 订阅爆发 | 每会话 setup 14 + daban 53 + zt ~30 + theme ~22 + detail ≤60 ≈ 170+ 帧，8 帧/tick×0.3s 拟人 | 单帧但 App 用户逐股查看天然稀疏 | 批量订阅=异常指纹（§3.4 假说判别项） |
| 610 保活 | `_ka_610=True` 硬编码，每 8 tick 重发 AuthReq | 无客户端心跳 | 非 App 指纹；历史调优产物 |
| 帧解析缺口 | `parse_incoming` 不认 pkg 0x50（退订 ack）/0x10（服务端心跳）→ FrameDecodeError | kind5→退订 ack；kind1→心跳 | 402 落地前必须补 |
| seq 不回绕 | `next_seq` 无限递增 | t31 ≥32767→1 | 长会话理论隐患（顺带修） |
| ack ext 未捕获 | echo 解析丢弃 ext（`parse_echo_frame` 只留 extlen） | ack attr2/attr3 是注册表 key | 注册表化的前置缺口 |

## 3. 目标架构

### 3.1 新模块 `backend/services/kpl_sub_registry.py`（纯逻辑，无 I/O，可全 mock 单测）

```text
SubEntry:
  sub_id_hint: int        # 客户端 hint（默认=cmd，App 观测口径）
  sub_id: int | None      # ack attr2 回填（服务端分配值，注册表权威 key）
  cmd: int                # 内层订阅 cmd
  req: bytes              # 内层 req pb 原料（重发/批量复用）
  ext: bytes              # 外层 ext（02 <cmd 2BE>）
  topic: bytes | None     # ack attr3 原始字节（推送/220 匹配 key）
  state: pending|acked|stale|unsubscribed
  lane: setup|zt|theme|detail|dynamic
  seq / sent_at / ack_at / resub_n

SubRegistry:
  register(entry) / on_ack(seq, attr2, attr3) → 匹配 pending→acked（按 seq），
      sub_id 冲突=原位更新（App s() 同款）；未匹配 ack 结构化丢弃计数（fail-visible）
  on_push_topic(ext) → entry | None（推送路由观测，P1 只记录不改 dispatch）
  on_resub(topics) → 待重发 entries（topics 空=全量；非空=topic 精确匹配；
      匹配不到任何 topic 时降级全量并结构化披露——不静默）
  diff_unsub(old_surface, new_surface) → subIds（402 退订计划）
  plan_batches(entries, max_items, max_bytes) → SubReqs 批计划（P3）
  clear_session()（断线清空=App qn0.f 同款；重发原料由 collector 订阅面重建）
  stats() → {pending, acked, stale, by_cmd, by_lane, push_topic_hit_n, ...}
```

**单一事实源迁移（AGENTS §1.2-1）**：P1 注册表与 `_resub_cache` 并行观察一个阶段；
P1 验收通过后 `_resub_cache`/`_cache_resub_item` **删除**，220 重发唯一来源=注册表；
回退靠 git，不保留双轨。

### 3.2 协议层增补（`kpl_socket_protocol.py`）

- `CMD_SUB_BATCH = 211`、`PKG_UNSUB = 0x50`、`PKG_HEARTBEAT = 0x10`（CMD_UNSUB=402 已在）。
- `build_sub_reqs_pb(items)` / `parse_sub_reqs_pb(payload)`（Item 六字段，data=f20）。
- `build_unsub_id_req_pb(sub_ids)` / `parse_unsub_id_req_pb`。
- ext 属性编解码：`encode_ext_attrs({2: int, 3: bytes})` / `parse_ext_attrs(ext)`
  （key2=2BE、key3=len2+bytes、key1=8B、key4=4BE，§1.2 线类型）。
- `parse_echo_frame` 增返 `ext` 原始字节（不破坏既有字段合同）。
- `parse_incoming` 补 kind5（0x50，带 seq，同 echo 形态）与 kind1（0x10 心跳，
  长度≠0 时 skip 并计数，App「receive a err heart len」同款）。
- `next_seq` 回绕 ≥32767→1（t31 同款）。

### 3.3 collector 集成（`kpl_collector_service.py`）

- 四个 drain 发送点（setup/zt/theme/detail）成功后 `registry.register`（替代
  `_cache_resub_item`）；`_dispatch` echo 分支提取 attr2/attr3 → `registry.on_ack`。
- 220：`registry.on_resub(topics)` 选择性重入队（保持 8 帧/tick 拟人节流与
  pid=8 priority 前插语义）；匹配失败降级全量 + 事件披露。
- 退订（P2，flag）：`set_subscriptions`/池成员收缩 → `diff_unsub` → 402/0x50 帧
  入专用退订队列（≤1 帧/tick，防抖 ≥5s）。
- 批量（P3，flag）：drain 从「逐帧 build_frame」改「plan_batches → 211 信封」；
  逐项 ack 跟踪（U4/U5 探针定案后实现）；**熔断**：211 批获 ErrResp/超时无 ack →
  本会话回退单帧 drain + 结构化事件 `batch_fallback`，stats 计数。
- 保活（P4，flag）：`KPL_KA_MODE=610|off`（默认 610 现状）；off 时 3001 分块轮询
  保留（它是行情刷新机制不是心跳，不在本次范围）。
- status() 增 `sub_registry`（stats 快照）/`sub_batch_mode`/`unsub_sent_n`/
  `batch_fallback_n`；WS 事件 `sub_ack`/`sub_unsub`/`batch_fallback`（fail-visible）。

## 4. 分阶段实施（每阶段独立可验证可回退）

| 阶段 | 内容 | 线上行为变更 | 验证 | 回退 |
|------|------|--------------|------|------|
| **P0** | 协议层增补（§3.2）+ `kpl_sub_registry.py` 纯逻辑 + 全 mock 测试 | **无**（不接线） | 新增 pytest 全过 + 既有 KPL 专项回归 | git revert |
| **P1** | 注册表接线观察：ack 捕获/220 选择性重发/删 `_resub_cache`；推送路由仍按 cmd（registry 只观测记录 topic 命中率） | 220 重发从全量→选择性（降级全量兜底）；其余零变更 | mock 会话级测试 + 盘中 status 观察 `push_topic_hit_n`/220 事件 | env `KPL_SUB_REGISTRY=0` 回旧全量路径（过渡期保留开关，验收后删） |
| **P2** | 402/0x50 退订（flag `KPL_UNSUB_ENABLED`，默认关） | 订阅面收缩时发退订帧 | **先探针 P3**（§7）钉死 ack 形态；mock 测试 | flag 关 |
| **P3** | 211 批量信封（flag `KPL_SUB_BATCH=211|direct`，默认 direct）+ 熔断回退 | 订阅帧形态变化 | **先探针 P1/P2**（§7）钉死 U1-U8；mock 测试 | flag=direct（熔断亦自动回退） |
| **P4** | 610 保活 A/B（`KPL_KA_MODE=610|off`，默认 610） | off 时停发 610 重发 | **先探针 P4** A/B 会话寿命对照；mock 测试 | flag=610 |

实施顺序硬约束：**P0→P1 可立即实施（零/低线上变更）；P2/P3/P4 的 flag 默认值
在对应探针收口前不得改为新行为**（AGENTS §1.2-9：先预算后动手；README §六：
真实连接只走预登记开火路径）。

## 5. 频控预算（AGENTS §1.2-9 硬红线，实施前对照）

现状每会话预算（生产配置，README §3.4 沿革）：

| 项 | 帧数/会话 | 节奏 |
|----|-----------|------|
| setup 内联（260/610/602/23xx/3001/3006） | ~14 | auth 相位 5+U(0,3)s，帧间 0.3/0.6/0.8s+抖动 |
| daban 家族 drain | ~53 | 8 帧/tick + 0.3s 拟人 |
| zt/theme drain | ~30+~22 | 同上，三队列交错 |
| detail 块 | ≤60（15 股×4 lane） | 整块块发（静默期 flush 合同），块内 0.375s |
| 3001 轮询 | ~1 帧/2s | 保活 tick 交替 |
| 610 重发 | ~1 帧/8s | 每 8 tick |
| 重连 | 2s 基础 + 短命(<60s)指数退避 2^n 封顶 120s | 交易时段门控 09:15-11:30/13:00-15:35 |

重构后预算（P3 开启时）：

- 211 批：**≤10 项/批、≤2 批帧/tick**，批帧间 0.3+U(0,0.3)s 拟人（沿用已验证节奏）；
  订阅帧总量 ~170 → **≤20 帧/会话**（压缩 ≥80%）；单批 payload ≤64KB（帧长 8MB 上限内远量级）。
- 402 退订：**≤1 帧/tick、变更防抖 ≥5s、≤20 帧/会话**上限（超出并入下一会话重建）。
- 220 选择性重发：重发帧数=失效条目数（全量兜底时=注册表大小，与现状同量级，不新增）。
- 探针预算（§7）：每探针 ≤3 会话、每会话新增帧 ≤12、探针间隔 ≥180s 冷却
  （README §3.4 螺旋实锤：冷却 180s 后存活 67.6s）；当日探针总帧 ≤60。
- 退避/门控/单实例纪律全部沿用现状，不新增重试循环。

## 6. 测试合同（全 mock，红线 README §六）

新增 `backend/services/__tests__/test_kpl_sub_registry.py`（纯逻辑）：
注册/ack 匹配/subId 原位更新/断线清空/220 选择性+降级全量/diff_unsub/
plan_batches 上限与保序/stats。

`test_kpl_socket_protocol.py` 增补：SubReqs 构造字节（六字段 varint tag，f20→`a2 01`）/
ack 解析/UnsubIdReq 往返/ext 属性四类型编解码/kind5/kind1 帧解析/seq 回绕。

`test_kpl_collector_service.py` 增补（FakeCodec/FakeSocket）：
ack attr2/attr3 捕获入注册表；220 topics 选择性重发（含 topic 不匹配降级）；
402 退订帧 pkg=0x50 断言；211 批帧 pkg=0x40+cmd=211+逐项字段断言；
批熔断回退单帧；`KPL_KA_MODE=off` 不发 610；既有会话帧序/空帧抑制/drain 限流回归。

验收基线：既有 KPL 专项全过（HEAD 口径 298+，以实跑为准）+ 新增用例全过；
零真实连接/零 WBE/零 ELF。

## 7. 开火探针预登记（需用户批准后执行，证据落 `.tmp_review/` 不入仓）

前置：单实例纪律（README §5.3）、交易时段或盘后低峰、KPL_DEBUG 帧转储开启、
App 保活红线不动。每探针独立会话，间隔 ≥180s。

| 探针 | 目的 | 设计 | 预算 |
|------|------|------|------|
| **P1** | U1/U2/U3/U6/U7/U8：211 受理与请求侧语义 | 基线会话（auth 链同生产）后发 1 个 211 批（2 项：2114+2116 空 Req，data 明文 codec=0 version=0，外层 ext=`02 00d3`）；变体：data GCM/codec=1、ext 空。对照 ErrResp/静默/ack | ≤3 会话×2 帧 |
| **P2** | U4/U5：逐项 ack 形态与 subId 分配 | P1 受理形态下扩到 5 项（2103 pid=8 index=0 + 2203 单股等），抓全部 kind4 ack 的 seq/attr2/attr3；观察推送 attr3 是否=ack attr3 | ≤2 会话×3 帧 |
| **P3** | 402 退订 ack 形态 | 先单帧订 2114（ack 捕获 subId）→ 发 402/0x50 UnsubIdReq{该 subId} → 抓 kind5 ack；再观察推送是否停 | ≤2 会话×3 帧 |
| **P4** | 610 保活 A/B | 同配置两会话：KA=610 vs KA=off（其余帧序逐字节一致），对照会话寿命/推送量；≥3 轮取中位 | ≤6 会话×0 新增帧 |

收口标准：P1 若 211 被 ErrResp/静默忽略 → **P3 阶段终止**，211 合同归档为阴性
（README §八同款），重构保留 P0/P1/P2/P4 收益；P1 受理 → 钉死 U1-U8 回填本文 §1.3
与 README §3.5 后方可实施 P3 阶段代码。

## 8. 风险与回退

| 风险 | 缓解 |
|------|------|
| 211 服务端已废弃/语义漂移 | 探针先行 + flag 默认 direct + 会话级熔断回退；阴性即归档不实施 |
| 注册表 ack 匹配率不足（服务端 ack 不带 attr2/attr3） | P1 只观测不改推送路由（仍按 cmd 解析）；220 降级全量兜底=现状行为 |
| 402 触发风控（退订帧也是指纹） | 防抖+限量+探针先行；flag 默认关 |
| 删 610 保活后会话劣化 | P4 A/B 证据先行；flag 默认 610 |
| 双轨漂移（registry vs _resub_cache） | P1 验收即删旧源（§1.2-1），过渡期开关有明确删除时点 |
| 频控累积 | §5 预算硬上限 + 既有退避/门控沿用；探针冷却 180s |

总回退：任一阶段异常 → 对应 flag 回默认（行为=现状）；代码回退靠 git；
不涉及存储/快照/API 合同变更（读口/落库/前端零改动，status 只增字段）。

## 9. 验收清单

- [ ] P0：协议层 + 注册表纯逻辑 + 全 mock 测试通过，零接线（生产帧序逐字节不变）。
      **✓ 2026-11-17 完成**（§10）。
- [ ] P1：220 选择性重发上线，`_resub_cache` 删除，status `sub_registry` 可观测；
      盘中 220 事件（若服务端下发）topic 命中率有数据；无 220 时行为=现状。
      **✓ 代码完成（默认生效）**；盘中观测待下一个交易日。
- [ ] P2/P3/P4：各自探针收口（§7）→ 用户批准 → flag 灰度 → 盘中实弹观测
      （会话寿命/推送量/退避 streak 对照基线）→ README §3.5 与本方案回填实测结论。
      **P2/P3 代码完成（flag 默认关/direct，探针未开火）；P4 未实施**。
- [ ] 文档同步：README §3.5（211 条目改「RE 收口+方案链接」）、§六测试合同、
      AI_COLLABORATION.md KPL 节同批更新（README §八.8 纪律）。**✓ 2026-11-17 完成**。

## 10. 实施记录（2026-11-17，P0-P3，用户批准「P0-3 211 批量增强一并处理」）

**影响文件**：

| 文件 | 变更 |
|------|------|
| `backend/services/kpl_socket_protocol.py` | +CMD_SUB_BATCH=211/PKG_UNSUB=0x50/PKG_HEARTBEAT=0x10；build/parse_sub_reqs_pb（Item 六字段，f20 tag=a2 01）；build/parse_unsub_id_req_pb（packed 兼容）；encode/parse_ext_attrs（四类型，未知 key/截断 fail-fast）；parse_echo_frame 透出 ext 原始字节；parse_push_frame +ext_raw；parse_incoming 补 kind5（fmt=unsub_ack）/kind1（heartbeat） |
| `backend/services/kpl_sub_registry.py`（新） | SubEntry/SubRegistry 纯逻辑：register/on_ack（含 211 批展开）/on_push_topic/on_resub（选择性+降级全量）/unsub_candidates/mark_unsub_sent/on_unsub_ack/plan_batches/track_batch/timed_out_batches/clear_session/stats；与 App 有意差异：subId 冲突不合并只计数（重发原料逐条保留） |
| `backend/services/kpl_collector_service.py` | 构造参数 sub_registry_enabled/sub_batch_mode/sub_batch_codec/sub_batch_max_items/sub_batch_ack_timeout_s/unsub_enabled；**删 `_resub_cache`/`_cache_resub_item`（单一事实源 §1.2-1）**；四 drain + inline flush 统一经 `_drain_send`（direct 逐字节同旧）/发送后 register；`_capture_sub_ack`（echo attr2/attr3 → 注册表，非订阅 ack 不计 orphan）；220 选择性重发（mode=selective/fallback_all/all_legacy）；`_sync_unsub_surface`（2103 pid=1 页更新钩子）+`_drain_unsub`（防抖 5s、≤20 id/帧、≤1 帧/tick）；`_check_batch_timeouts`+`_batch_fallback`（会话级熔断：超时/批 ack 解析失败/未决批期 ErrResp）；next_seq ≥32767→1 回绕（t31 同款）；新会话 clear_session+熔断复位；status +sub_registry/sub_batch_*/unsub_* 观测 |
| `backend/serve_kpl_socket.py` | env KPL_SUB_REGISTRY（默认开）/KPL_SUB_BATCH（direct\|211，非法值 fail-fast）/KPL_SUB_BATCH_CODEC（0\|1）/KPL_SUB_BATCH_MAX_ITEMS（10）/KPL_SUB_BATCH_ACK_TIMEOUT（10s）/KPL_UNSUB_ENABLED（默认关） |
| 测试 | 新 `test_kpl_sub_registry.py`（25）；`test_kpl_socket_protocol.py` +17（SubReqs/UnsubIdReq/ext/kind5/kind1/ext_raw）；`test_kpl_collector_service.py` 旧 2 个 _resub_cache 用例改注册表语义 + 新增 P1/P2/P3 集成用例（ack 捕获/批信封字节/批 ack 展开/逐项 ack/超时熔断/ErrResp 熔断/codec1/inline 保持 direct/会话级 211/退订 diff+防抖+ack） |

**验证（全 mock，零真实连接）**：KPL 九文件专项 **413 passed**；
`backend/services/__tests__ + tests/api` **573 passed**；`tests/hotlist`
**1582 passed, 6 skipped**。direct 模式会话帧序旧用例逐字节断言全过
（test_full_session_emits_auth_and_quotes 等）= 订阅帧形态零变更实证。

**已完成（2026-11-17 下午盘）**：P4 ka_mode flag + A/B 裁决（默认切 off）；
§7 探针 P1-P4 全部开火裁决（§1.3/§7.1/§11）；402 ack seq 回填修正；
批内盘中推送交付验证。**待办**：211 批 ack 内 item.data 首帧快照暂不 dispatch
（实弹已证逐项 ack 自带快照数据且推送正常，双处理风险大于收益，维持不 dispatch）；
盘中 220 topic 命中率观测（下一个交易日）；402 启用被 per-stock 共享 subId 误退阻塞
（§12，需唯一 subId/topic 退订设计+确认探针，非单纯批准即可启）；off 模式长窗寿命生产观测。
**过渡开关删除时点**：KPL_SUB_REGISTRY 开关在盘中 220 选择性重发验收后删除
（方案 §3.1 单一事实源纪律，不长期双政策）。
## 11. 开火记录（2026-11-17 11:29-12:00，用户批准「211开火」，午休低峰窗）

工具：`scripts/probe_kpl_sub_batch.py`（正式脚本，复用生产 collector 全链路 +
受控订阅面注入；单会话禁重连）。前置：:8002 生产采集 POST stop（单实例纪律），
探针毕 POST start 恢复（idle_offhours，13:00 自动恢复）。pc codec 白盒轨，
凭据 .env.local（userId=4012184 正式账户）。

| 轮次 | 变体 | 会话数 | 211 帧 | 结果 |
|------|------|--------|--------|------|
| 1 | plain（2 项 codec=0）+ multi（5 项 codec=0） | 6（**自动重连膨胀，披露见下**） | 5 | 全部：28B 批 ack + ErrResp 2008 + 杀连（~10s） |
| 2 | control（direct 2 项） | 1 | 0 | 健康 46.6s，2/2 ack 带 topic，零错误 → 2008 专属 plain-211 |
| 2 | gcm（2 项 codec=1） | 1 | 1 | **受理**：45.4s 健康，批 ack + 2/2 逐项 ack（seq=item.seqId，topic=hqDaban\|…） |
| 3 | multi（5 项 codec=1） | 1 | 1 | 5/5 ack；2114/2115 带 topic；2103/2203/2013 无 topic + 3×cmd110/ErrResp 2000（非致命） |
| 4 | dmulti（direct 5 项对照） | 1 | 0 | 5/5 ack 全带 topic（2103 含页参数、2203/2013 per-stock），零 110；2203/2013 初始快照到达 |

**预算审计**：合计 10 会话 / 7×211 帧（日预算 ≤60 ✓）；变体间冷却 ≥180s ✓。
**偏差披露**：轮 1 探针脚本未禁生产重连链，45s 观察窗内自动重开共 6 会话（预登记
≤3），每会话再发一帧 211；发现后即修脚本（_run_loop 覆写单会话），轮 2-4 严格
单会话。轮 1 的 multi 帧转储被轮 3 同名文件覆盖（拒绝证据已由 plain 转储与
summary JSON 承载，结论不受影响）。

**证据工件**：帧转储/事件/摘要落仓库根 tmp/（gitignore），分析完毕已按 AGENTS
临时产物纪律删除；结论固化于本文 §1.3 与 README §3.5。28B 批 ack 样本（前 8B
`238ca62f00000000`，与 110/610 状态帧同前缀）；110 解密样本
`08d00f1213e8bf9ee68ea5e99499e8afafefbc9a32303030` = ErrResp{2000,"连接错误：2000"}。

**开火后代码修正（同轮落地，559 passed）**：
- `CMD_ERROR_NT=110` + `_dispatch` 110 分支（GCM 解密 → ErrResp 解析 → error 事件
  channel=110 + err_nt_n 计数，不再静默当 raw）。
- 内联 3001/3006 订阅入注册表（topic 命中率观测补全；220 覆盖列表型订阅）。
- **sub_batch_codec 默认 0→1**（collector + serve env）：明文=2008 杀连，安全默认。
- 注册表 +batch_item_no_topic_n 计数（批内无 topic ack 与 110/2000 同现的观测位）。
- 探针脚本修正：单会话禁重连、multi codec=1、dmulti 对照变体、受理判据修正
  （批 ack 事件存在≠受理，须无 2008/110 且逐项 ack 带 topic）。

## 7.1 下午盘增补预登记（2026-11-17 用户批准「实施待办项」，13:00 开火）

前置同 §7（单实例 stop/start、KPL_DEBUG 抓帧、冷却 ≥180s）。时钟校正：批准时
12:0x 仍午休，推送交付验证必须盘中 → 定时 13:00 开火。工具：
`scripts/probe_kpl_sub_batch.py --tag r3/r4`（单会话禁重连，变体观察窗内置）。

| 探针 | 目的 | 设计 | 预算 |
|------|------|------|------|
| **P-push** | 批内订阅盘中推送交付（§1.3 残留未知） | pushbatch：211 批 3 项（2114/2115/2116，codec=1）；pushdirect：同 3 项 direct 对照；观察窗 90s，比 daban 推送量/registry topic 命中 | 2 会话；211 帧 +1（日累计 8≤60） |
| **P3'** | 402 退订 ack 形态 + 推送停差分 | unsub：direct 订 2114+2116 → 读循环 20s 后只退 2114（生产 `_drain_unsub` 真实路径，防抖/频控全继承）→ 抓 kind5 ack + 2114 推送停/2116 继续；观察窗 90s | 1 会话；**402/0x50 首射 1 帧≤2** |
| **P4'** | 610 保活 A/B | ka610/kaoff 交替 3 轮（唯一变量 ka_mode，订阅面同构 2 项）；观察窗 120s（盖过生产典型寿命 57-80s）；计 session_s/死亡原因/推送量/610 重发帧数，≥3 轮取中位 | 6 会话；零新增帧类型 |

合计 9 会话（+2 重试预留）；每会话新增帧 ≤12；总时长 ~45min（13:00-13:45）。
P4 代码已落地：`ka_mode=610|off` flag（collector+serve `KPL_KA_MODE`，默认 610
零行为变更）+ mock 3 用例（562 passed）。裁决前生产不切 off。

### 7.1.1 下午盘裁决（2026-11-17 13:00-13:50 实弹，证据链 §11 第二轮）

| 探针 | 裁决 | 关键证据 |
|------|------|----------|
| **P-push** | **批内盘中推送交付 == direct** | pushbatch push 量 zd_stat/market_overview/plate_strength = 11/18/16 vs pushdirect 12/19/17；初始快照随逐项 ack 到达（2114≈490B/2115=95B/2116≈6.4KB，两臂同量级）；registry topic 命中 71/77、miss=0 |
| **P3'** | **402 语义钉死**：受理（pkg 0x50 窗口合法）；kind5 ack seq=请求 seq、payload=**28B 不透明状态块**（与 211 批 ack 同构，DEC 失败，非 UnsubIdReq 回声）→ subIds 按 seq 从已发原请求取（App qn0.d/q 同款，已修正 `_unsub_seq_ids` 映射）；**差分成立**：退 2114 后 zd_stat 推送即停（post=0/1 在途帧），未退 2116 plate_strength 继续 37s（post=9/12） | r3 s3 + r4 s7（修正后 removed=1、state=unsubscribed） |
| **P4'** | **610 重发=确定性杀连因素**（最小订阅面受控实验）：ka610 3/3 被 1106 杀（72.7/67.0/66.4s，中位 67.0），死亡时刻=**第 5 次重发 dt=0**（C610=6=初始 1+重发 5）；kaoff 3/3 零错误存活 121.5/120.5/120.1s（右删失，中位 120.5），C610=1 仅初始认证，推送持续至 ~111-113s 非僵尸；推送速率两臂相当（~0.85/s），off 总量 ~2×。生产全订阅面另受爆发指纹 10054（见附隸定案校正） | r4 s1-s6 交替 3 轮；**默认已切 KPL_KA_MODE=off**（回退置 610） |

**附带定案与诚实校正**：1106 错误经 cmd 110 通知通道下发后随 cmd 201 杀连（双帧）。
初版曾推断「生产 57-80s 短命 = 610 第 5 次重发处决」——**生产重启 off 后实测校正**：
全订阅面（~170 帧爆发）会话仍 ~56-63s 被 10054 重置（非 1106），即生产短命由
**爆发指纹风控**主导（既有问题，§3.4 螺旋控流方向），610 杀连是最小订阅面受控
实验证明的独立确定性因素（生产爆发死得更早，610 因素往往来不及触发）。off 消除
① 不加剧 ②，重连链兑底正常（backoff 8s/streak 2 正常档）；registry topic 命中
84/miss 0 生产实证。

## 11.1 开火记录第二轮（2026-11-17 13:00-13:50 下午盘，用户批准「实施待办项」）

前置：12:0x 批准时仍午休 → 定时 13:00:05 开火（推送交付必须盘中）；:8002
POST stop，完毕 POST start 恢复。工具同 §11（--tag r3/r4，单会话禁重连）。

| 轮次 | 变体 | 会话 | 结果 |
|------|------|------|------|
| r3 | pushbatch / pushdirect / unsub | 3 | 推送交付两臂同量级；三会话均 ~70s 被 1106 杀（第 5 次 610 重发 dt=0）；402 首射受理但 ack 解析源错误（removed=0，触发修正） |
| r4 | ka610/kaoff 交替 ×3 + unsub 确认 | 7 | P4 裁决（§7.1.1）；s7 用修正后 handler 复证 402（removed=1，差分 post=0 vs 9） |

**预算审计**：下午盘 10 会话（预登记 9 + 重试预留 1：r4 s7 为 402 修正后确认射，
披露）；211 帧 +1（日累计 8≤60 ✓）；402 帧 2≤2 ✓；冷却 ≥180s ✓（r3→r4 间隔
~10min）；每会话新增帧 ≤12 ✓。观察窗：push/unsub 90s、ka 120s（kaoff 全右删失）。
**分析层踩坑（披露）**：首轮摘要 push_events 只计 type=daban，漏计实际事件名
zd_stat/market_overview/plate_strength 致「推送恒 0」假象——已修脚本计数器，
原始 events jsonl 未受影响，裁决以事件流重算为准。

**证据工件**：tmp/kplprobe_r3/r4_*（帧转储/事件/摘要）分析完毕已按 AGENTS
临时产物纪律逐个删除；结论固化 §1.3/§7.1.1 与 README §3.5/§六/§9.5。

**开火后代码修正（同轮落地，413/573/1582 passed）**：
- 402 ack subIds 按 seq 从 `_unsub_seq_ids` 原请求映射回填（App qn0.d/q 同款）；
  payload 可解时兼容旧路径；双源皆空 → `unsub_ack_unmatched_n` fail-visible。
- **ka_mode 默认 610→off**（collector + serve `KPL_KA_MODE`）：P4 3/3 确定性裁决。
- 探针摘要 push_events/timeline 补 zd_stat/market_overview/plate_strength 事件名。

## 12. 402 启用阻塞（2026-11-17 生产实证，用户「请启用」裁决前必解）

**KPL_UNSUB_ENABLED 暂不能安全启用**——per-stock 退订存在确定性误退缺陷：

- 生产 registry 实证：`sub_id_collision_n=133`，2203×39 / 2013×32 条目**全部共享
  subId=cmd**（服务端回声客户端 hint，多股不分配唯一 subId；U6 单股观测不足以
  覆盖多股，此处生产计数补证）。
- `_sync_unsub_surface` 仅处理 per-stock 三 lane（zt/theme/detail），subId 全=cmd。
  池中一股退出 → `402{subIds:[cmd]}`  targeting 共享 subId（服务端语义不明，可能
  整通道或任意一股）；`on_unsub_ack([cmd])` 把**全部同 cmd 条目**标 unsubscribed
  （确定误退）。加「仅退唯一 subId」护栏则 per-stock 全被跳过 → 启用=空操作。
- P3' 探针只验证单订阅全局通道（2114，subId 唯一），未覆盖多股同 cmd。

**正确路径（待用户裁决 + 开火批准）**：
1. per-stock 改**唯一 subId hint**（每股一个，App 对齐）使 ack attr2 回填唯一 id；
   **或**改 `UnsubReq{topics}`（Base.java 另有此消息，按 topic 退，per-stock topic
   天然唯一 `hqStock|…/2203-1/<stock>`）——两条均需先验证服务端多股语义。
2. 确认探针：多股同 cmd 订阅 → 退一股 → 差分验证其余继续。
3. 验证后再启用 KPL_UNSUB_ENABLED。

在此之前 flag 维持默认关；402 代码作为 flag 门控实验能力提交（休眠，不影响生产）。

## 13. 独立 code review 修复（2026-11-17，reviewer fresh-context 只读审查）

裁决 **OK with notes，无 blocker**；4 major + 8 minor + 3 nit 全部同批修复
（修复后 KPL 九文件 413 / services+api 573 / hotlist 1582 passed）：

- **M1 heartbeat 接线**：kind1（pkg 0x10）帧无 cmd 键，`_dispatch` 首行加
  heartbeat skip+`heartbeat_n` 计数；260/610 auth 等待窗 `fr["cmd"]`→`fr.get("cmd")`
  （防 KeyError 杀会话，off 长寿会话放大暴露）。补 dispatch 级用例。
- **M2 211 白名单**：`_BATCHABLE_CMDS=frozenset(daban.DABAN_SUB_CMDS)`（hqDaban
  全局族），`_drain_send` 分流——非白名单（2103 页/2203/2013/detail/lhb）恒 direct，
  杜绝批内必拒通道入批被静默置 ACKED（U1 裁决）。改两条旧测试断言 + 新增分流用例。
- **M3 402 冲突护栏**：`unsub_candidates` 跳过被 >1 活跃条目共享的 subId
  （`sub_id_shared_skip_n` 计数），防 on_unsub_ack 误退整族（U6 sub_id=cmd 回声，
  生产 collision_n=133 实证）。**这是 §12 启用阻塞的安全护栏**：per-stock 全共享 →
  护栏使退订安全空操作，精准退订仍需唯一 subId/topic 设计 + 探针。补 registry 用例。
- **M4 README 漂移**：§3.5 旧 `_resub_cache`「两种情况都全量」段改写为注册表语义。
- **m1** 211 item enc 失败预检 → 熔断 + 全 direct，绝不产 codec=0 明文项（U2）。
- **m2** `KPL_SUB_BATCH_CODEC` 值域 fail-fast（serve ∈{0,1} RuntimeError；collector
  非 (0,1) ValueError），非法整数不再静默变 lethal 明文。
- **m3** serve 注释改双因素口径（610 受控因素 + 爆发指纹 10054 主导）。
- **m4** 220 重发保留 key/lane：`_handle_resub_nt` requeued dict + `_drain_setup_subs`
  items 重建均携带 key/lane（根因在 setup drain 重建丢字段），重发后 per-stock
  条目仍可被 unsub diff 命中。补用例。
- **m5** 402 ack seq 映射**优先**于 payload 解析（防宽容 parse_pb 从 blob 提取垃圾
  f1 varint 误清）。补垃圾 payload 用例。
- **m6** 402 会话级帧预算 `_UNSUB_MAX_FRAMES=20`（_session 复位 + 门禁，§5）。补用例。
- **m7** 注册表 docstring 改「stats() 跨线程尽力快照」（GIL 安全依据），消除自述合同矛盾。
- **m8** 补 28B 不透明批 ack collector 级用例（expanded=0/不熔断/逐项 ack 仍匹配）。
- **n1/n2/n3** seq 回绕文档 ≥32766→≥32767 对齐代码；§4 `topic_matched_n`→
  `push_topic_hit_n`；all_legacy 注释明示仅重发 ACKED（略窄于旧全量）。

**灰度前置硬条件复核**：M2/M3/m1/m2 已修——`KPL_SUB_BATCH=211` 现有白名单+enc 护栏；
`KPL_UNSUB_ENABLED=1` 现有冲突护栏（per-stock 安全空操作，精准退订待 §12 设计）。
默认生产路径（direct + 注册表观测 + ka off + 402/211 关）行为不变。
