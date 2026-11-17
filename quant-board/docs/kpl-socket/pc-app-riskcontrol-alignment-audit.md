# PC ↔ App 风控保护对齐审计（2026-11-17）

> 触发：用户「PC 端还有哪些风控保护发明，全部与 App 对齐」。
> 证据根：`.tmp_review/main_src/sources/`（jadx 反编译 App 官方源码）。
> 纪律：本文是审计 + 对齐裁决底座，**未改任何代码**；高风险风控行为变更须先裁决 + 受控探针。

## 0. 结论先行（核心论点：信任不对称）

**PC 多数风控「发明」App 根本没有，且不能盲目删除来「对齐」。** App 是受信任官方客户端
（真机指纹 / 官方 sign / connType=99），服务器对其宽松；PC 是模拟器（PCEmulatorCodec，
指纹不可信、codec 瞬时），服务器对其严苛。App 不需要这些保护是因为**受信任**，不是因为
「这些保护没用」。把 PC 护盾拆掉照搬 App 的爆发/瞬时行为，等于让不可信客户端做受信任
客户端才敢做的事——**会更快被风控杀**（§3.4 爆发指纹议题已实弹印证 PC 爆发被杀）。

对齐应分三类处理（§4）：
- **已 App 对齐**（协议/退避/保活）：保持。
- **PC 专属补偿**（拟人延时/限流/时段闸/grace）：App 无此代码，是 PC 不可信指纹的护盾，
  **默认保留**；若要验证「App 式行为 PC 能否存活」，走受控探针（用户并行 burst 探针正在做），
  不直接拆。
- **效果对齐但代码不同**（auth 延时 ≈ App 自然 sign 时延）：保留（删了反而暴露瞬时指纹）。

## 1. 逐项审计表

| # | PC 机制（代码） | PC 值 | App 实证 | 性质 | 对齐建议 |
|---|---|---|---|---|---|
| 1 | 重连退避 `_run_loop` | <60s 螺旋 2·2^n 封顶 120s + 死因感知（§14） | `ReconnectManager` 退避梯 {0,1,2,4,8,15,30}s±20%；服务端拒绝 base3s、>3→60s | **App 同款** | ✅ 已对齐（§14 死因感知）|
| 2 | 保活 `ka_mode` | off + 3001 轮转（610 重发→1106 杀） | App 3001 轮转保活；610 重发被杀（P4 实弹） | **App 同款** | ✅ 已对齐（P4，ka=off）|
| 3 | `next_seq` 递增 | ≥32767→1 | `t31.c()` seq ≥32767→1；重复 seq 立即断连 | **App 同款** | ✅ 已对齐 |
| 4 | connType/flags/auth d | connType=99 / flags=(d<<3)\|enc / auth d=2 | `SocketRepository.f6127a=99` 等 | **App 同款** | ✅ 已对齐（README §3.5）|
| 5 | pkg 路由头 | 全 build_frame 点 pkg=PKG_ROUTE(0x40) | App 帧 pkg 分类（SocketReaderThread kind=pkg>>4） | **App 同款** | ✅ 已对齐（2026-11-10 修复）|
| 6 | **订阅帧限流** `_DRAIN_TICK_FRAMES`+`_drain_pause` | 8 帧/tick + 0.3+U(0,0.15)s/帧 | `SocketWriterThread`：`take()→write()→flush()` **零 sleep 零节流背对背爆发**；qn0 重订 `for(e:registry) sendPacket()` 零延迟 | **PC 专属发明** | ⚠️ App 无；PC 爆发被杀（§3.4）→ 保留护盾；对齐=爆发，须探针验证 |
| 7 | **auth 拟人延时** `auth_phase_delay/jitter` | 5.0+U(0,3.0)s | App auth 走真机 sign **自然时延**（无人为 sleep）；writer 零节流 | **效果对齐/代码不同** | ⚠️ PC codec 瞬时→须延时模拟 App 自然 auth 时延（§3.4：<1s→6s 杀，5-8s→75-160s）；删=暴露瞬时指纹 |
| 8 | **auth 步骤 human_pause** | 602 前 0.6+0.3 / 2301 前 0.8+0.4 / 子帧 0.3+0.15 | App 各步背对背入 writer 队列，零停顿 | **PC 专属发明** | ⚠️ 同 #6，拟人节奏护盾；保留 |
| 9 | **发送宽限期** `loop_send_grace_s` | 5.0s（setup 后） | App 无宽限期，setup 即发 | **PC 专属发明** | ⚠️ 保留（避 setup 刚结束爆发被杀，§3.4）|
| 10 | **交易时段门禁** `_enforce_trading_hours` | 09:00-11:30/13:00-15:35，非盘 idle_offhours | App **无时间闸**；门控=前后台生命周期（`i5()` onAppResume 连 / `q()` 后台不重连） | **PC 专属适配** | ⚠️ headless 无生命周期→时间闸模拟 App「前台≈盘中」；保留（机理不同，非 App 代码）|
| 11 | 单实例纪律 / 频控预算 | 开火前 stop / 完毕 start；QPS/日帧预算 | App 单进程自然单实例 | **运维纪律** | ✅ 保留（AGENTS §1.2-9 硬红线，东财 IP 封禁前科）|
| 12 | 反作弊 261 处理 | 无法作答→断连重建 + 5s 退避（不发假答案） | qn0:126 `AntiCheatChallenge` 应答（真机可作答） | **App 同款行为** | ✅ 已对齐（App 同款断连重建）|

## 2. App 零节流爆发实证（关键）

`SocketWriterThread.java`（全文 67 行，写循环核心）：
```java
ux0 take = this.f.take();   // LinkedBlockingQueue 阻塞取
this.e.write(take.x());     // 立即写
this.e.flush();             // 立即 flush
// 无 sleep / 无 delay / 无 pace / 无 throttle
```
`qn0.java:209-216`（断连重订）：
```java
for (ux0 ux0Var : this.e) {           // 遍历注册表
    SocketHelper.H().sendPacket(ux0Var);  // 逐帧入 writer 队列，零帧间延迟
}
```
`SocketHelper.sendPacket():734-746`：入 `socketWriterThread.f(ux0Var)` 队列即走，无 pacing。

**结论：App 订阅/重订/保活全是背对背爆发，没有任何帧间拟人停顿。** PC 的 #6/#8/#9 限流
拟人护盾 App 完全没有。App 爆发不被杀 = 受信任；PC 爆发被杀 = 不可信（§3.4 实弹）。

## 3. App 门控实证（前后台，非时段）

`ReconnectManager.i5():123`（onAppResume）：`this.b=true` + `u("app-resume")` 归零失败计数
→ 链路未 up 则建连；后台 `>=a.d(60000ms)` 则恢复探针。
`ReconnectManager.q():188`（onSocketDisconnect）：`if(!this.b)`（后台）→ 置 state **return
不重连**；前台才退避重连。
socket 包 + SocketPresenter 全 grep **无** `HOUR_OF_DAY`/`isTradingTime`/开盘收盘判据。

**结论：App 连接门控 = 前台/后台生命周期 + 网络可用性，无交易时间闸。** PC #10 时间闸是
headless 守护进程对 App「前台≈盘中」有效模式的模拟，机理不同，非 App 代码功能。

## 4. 安全对齐路径（裁决建议）

### 4.1 已对齐（保持，无需动）
#1 退避（§14 死因感知）/ #2 保活 ka=off / #3 seq / #4 connType / #5 pkg / #12 反作弊。
这些是协议层 + 重连/保活策略，App 实证同款，已对齐。

### 4.2 PC 专属护盾（默认保留，不可盲删）
#6 订阅限流 / #8 auth 步骤拟人 / #9 send grace / #10 时段闸。
- **存在理由**：PC 不可信指纹 + 瞬时 codec，服务器严苛。这些是 PC 能存活 50-160s 的护盾。
- **「对齐 App」= 拆护盾照搬爆发/瞬时/无闸**：App 受信任敢这么做，PC 这么做会被秒杀
  （§3.4：PC 零间隔爆发→机器指纹→处决；<1s auth→6s 断）。
- **正确验证路径**：若想知道「PC 能否像 App 一样爆发存活」，走**受控探针**逐项消融
  （用户并行 `probe_kpl_burst_surface.py` S0/S1/S2/S3 + `--reconnect` 正在做订阅面消融）。
  探针裁决前不拆生产护盾。

### 4.3 效果对齐但代码不同（保留）
#7 auth 延时：App 无 sleep 但真机 sign 自然耗时；PC codec 瞬时，延时是**模拟 App 自然
auth 时延**（效果对齐）。删延时 = PC auth 变瞬时 = 暴露机器指纹（§3.4 单调相关实证）。
故保留——这不是「App 没有就该删」，而是「App 用自然时延达到的效果，PC 用延时达到」。

## 5. 与爆发指纹议题（§3.4 / §7.1.1）关系

PC 当前 ~56-63s 被 rst_10054 重置的根因仍在查（用户并行 burst 探针）。本审计的关键输入：
**App 爆发零节流却不被杀** → 证明「爆发本身」不是充分死因，**信任指纹**才是判别变量。
PC 限流护盾（#6）是缓解假设而非 App 行为；探针应消融「订阅面大小 vs 帧节奏 vs 指纹」
三变量，而非简单「对齐 App 爆发」。死因感知退避（§14）已使 rst_10054 走硬退避，防护不松。

## 6. 待补证项（诚实登记）

- App 3001 保活**精确间隔**：未定位心跳定时器（UI postDelayed 均非 socket 心跳）；PC ka=off
  +3001 轮转已由 P4 实弹验证 App 对齐，精确周期待补证。
- App auth 各步**自然时延实测**：§3.4 用 adb 链路 5-8s 间接实证，真机 sign 耗时未直接测量。
- App 是否对**订阅面大小**有隐式限制（PC 331 ids vs 探针 1 板块 confound）：用户 burst 探针
  `/api/kpl/subscription-ids` 复现生产全量面正在验证。

## 7. 裁决待用户定

「全部与 App 对齐」若理解为「删除 App 没有的 PC 保护」→ **不建议**（拆护盾，PC 会被秒杀，
信任不对称）。建议口径：
1. 协议/退避/保活已对齐项保持。
2. PC 专属护盾（#6/#8/#9/#10）保留；要验证 App 式行为能否存活，走受控探针消融，裁决后再定。
3. auth 延时（#7）保留（效果对齐 App 自然时延）。

**本文未改代码。** 用户若选定某项做探针对齐，按预登记 + 批准开火路径执行（AGENTS §1.2-9）。