# Handoff：题材周期换源（KPL 三层数据）+ Socket 盘中实时推送攻坚（2026-10-25 深夜 → 新会话）

> 复制到新对话即可无缝续作。全部结论实测可复跑，命令与证据见文末。
> **【2026-10-27 攻坚完成】最终成果与运维合同已固化至 [../kpl-socket/README.md](../kpl-socket/README.md)**；
> 本文是逆向过程记录（含已推翻的旧假设，如 601/静态 challenge），运行手册与协议合同以 kpl-socket 文档为准。
> 本文遗留风险节中「3006 结构已知未实测」已过时：3006 已实现并实测到流（见 kpl-socket 文档 §一）。

## 一、任务背景（一段话）

题材周期命题（v1 已 revert，commit 17a231a0/19fc37ef）只能换数据源重做。经勘察，
wzslinker.top「精选板块」背后是**开盘啦（KPL）三层数据**，全部官方直连已打通并被用户裁定
「数据没问题、比东拼西凑的好」。用户拍板：**拿下 Socket 盘中实时推送**（情绪周期要做日内
弱转强，盘后轮询撑不起帧级落库）。当前推进到：协议钥匙全部定位，卡在白盒壳最后一环。

## 二、已完成且用户已认可的部分（不要重做）

1. **三层数据全官方直连**（Survey 文档 §9.2/§9.3/§9.9）：
   - 层1 板块强度排行：POST `apphwhq/apphis.longhuvip.com/w1/api/index.php`，
     `a=RealRankingInfo&c=ZhiShuRanking&ZSType=7&Type=2`（实时）/`Type=1+Date=YYYY-MM-DD`
     （**按日查史，实测 ≥2.4 年**）；`Index` 偏移 + `st=80` 每页；每日恰好 240 板块=3 发；
     **POST + Token=0/UserID=0 免凭据**，UA=`ad`。
   - 层2 板块爆发历史（最大发现）：GET `apphis`，
     `c=ZhiShuKLine&a=GetDayBaseFaceListZDEvnArt&StockID=<801xxx>&IsBoom=0&Index/st=100`
     ——全量日度记录（含 isBoom 标志），**机器人全史 6.5 年（2020-02 起）301 条=4 发/题材**；
     每行=爆发日+ZTNum(当日板块涨停数)+QD(强度)+LZInfo(**龙头梯队串「大业股份,5连板」**,
     KPL 预计算)+LZInfo_ZF(梯队涨幅)+Title(催化)。**isBoom 是 KPL 自有爆发判定，必须原样存**。
   - 层3 成分股（含历史）：POST `apphis`，
     `a=ZhiShuStockList_W8&c=ZhiShuRanking&old=1&Date=…&PlateID=801xxx&Type=6&Order=1&Index/st=80`
     + **现役 KPL 凭据**（`backend/services/theme/mapping_refresh.py` 的
     KPL_APP_BASE_PARAMS，UserID=397605）+ UA=`Dalvik/2.1.0 (Linux; U; Android 9; …)`。
     300 行×70 字段：field23=连板状态（「6连板/5天3板」）、field24=**龙一~龙N 梯队**、
     field58=热度。零凭据返空。此前 1020 的根因=c 写错（ZhiShuStockList→应为 ZhiShuRanking）。
   - wzslinker 第三方依赖彻底解除。**用户裁定：KPL 数据不用怀疑正确性**。
2. **ID 桥（成分重叠法）已验证**：库内 themes（251，题材内部 ID 84/392 系）与 801xxx 指数
   两套体系，官方无桥、名称匹配率仅 28%；**成分重叠桥双例通过**（801159→7 个机器人族题材
   ≥0.40；803029→物理AI概念 0.61 断崖 0.42）——与 theme-data-governance 挂靠判据同款，
   语义=指数(聚合)一对多挂题材族。地域/业绩类指数天然挂不上=等效 NOT_A_THEME。
3. **库内处置已裁决**：`snapshot_stock_rows`（90.5 万行 RankTrend 主链）/`themes`/
   `theme_stock_mappings`（本来就是 KPL 题材树）**一个不 drop**；题材周期 v2 新建
   `plate_boom_history`+`plate_strength` 两集合；`hotlist_jev_theme_cycle`（75 日旧产物，
   mongodump 已归档）留作对照后再 drop。

## 三、Socket 攻坚现状（核心情报，全部实测）

- **通道现状（2026-10-26 晨实测修正，推翻上文部分推断）**：三个端口全部 TLS1.2
  (ECDHE_RSA_AES128_GCM_SHA256=C02F)+显式 nonce 风格。**14000 未弃**：免客户端证书，
  应用层明文旧协议帧（对旧 exe init 回标准 protobuf 错误包「连接错误：1102」）；
  **17000/8080 = mTLS**：服务端发 CertificateRequest，客户端证书必须链到
  `CN=kaipan Root CA, O=kaipan.com, OU=Root Certificate Authority`（自签证书回
  `unknown CA`，**推翻「assets/PrivateKey 自签即过」的旧结论**——那对 1024 密钥是别的用途）；
  app 对服务端证书做 pin（APK `assets/pub.key`=RSA-2048 SPKI base64，换绑我们证书后 app 仍拒，
  回 certificate_unknown，pin 逻辑在壳内加密 dex，未定位）。
- **客户端证书私钥已到手**：APK `assets/PrivateKey` = 明文 PKCS#8 RSA1024（自签证书即过
  服务端 mTLS——服务端不 pin 客户端证书链）；`assets/PublicKey` 同对。
- **签名算子已定位（无需逆向算法）**：`lib/arm64-v8a/libauthSign.so` 四个 JNI 导出：
  - `Java_com_yzj_kaipanh_common_Config_nativeSalt`（盐）
  - `Java_com_yzj_kaipanh_newindex_common_socket_ChallengeVM_execHex / execEncryptedHex`
    （**init 签名算子**）
  - `Java_com_yzj_kaipanh_newindex_common_socket_SocketHelper_crtFromJNI`（mTLS 客户端证书）
- **请求帧格式（PC exe 逆向，5.20 协议）**：3 字节帧头 pkg_id+len(2B 大端)；心跳 `10 00 00`；
  init 照抄 appconfig.ini 的 init_packet_hex；请求=`40 <len> <seq2B> <cmd2B=09C5> 00 00 03 02
  <cmd> + protobuf{f1:bkcode, f2:Type=6, f3:Order=1, f4:Index, f7:st=80}`；响应/推送 pkg=0x60，
  ~3s/帧，体=`+hqList|<订阅串>`+cmd 块+protobuf 行（含毫秒时间戳字段）。**新版 8080 的 init
  格式可能已变**（内存扫描未见旧模式）。
- **受阻原因链（逐层排除过，勿重试）**：APK 白盒壳（`com.kpl.armor`，真 dex 运行时解密，
  jadx 只见 13KB stub）→ 协议类**懒加载**（不进行情页建立 socket 不加载，枚举=NONE）→
  **TLS 在 arm 自带库**（libauthSign 静态 openssl），雷电 x86_64+houdini 下 x86 Frida hook
  系统 libssl/libc/conscrypt 全部零流量（三种 hook 都成功挂载但无事件）→ **attach 主进程
  被反调试挂死（Java.perform 永不返回），spawn 模式 Java 桥可用** → 多进程（主进程父子+
  pushservice 父子），app 在 houdini 下频繁崩重启，frida/adb pid 视图漂移（attach 用
  enumerate 的最后一个主 pid；「process not found」时先重启 frida-server）。
- **环境**：雷电模拟器（127.0.0.1:5555，Android 9 x86_64，用户已开 ROOT 且**已登录 KPL**）；
  adb=`D:\Android\Sdk\platform-tools\adb.exe`；frida 16.5.9（pip + server 已在模拟器
  /data/local/tmp/frida-server16，root 运行中）；jadx 在 `.tmp_review/jadx/`。
  **Git Bash 调 adb shell 路径要加 MSYS_NO_PATHCONV=1**；adb push 会静默丢失，用
  base64 分块传输（脚本已验证）；Windows 下 mitmproxy local 模式不可用（非管理员 WinDivert）。

## 三点五、2026-10-26 凌晨攻坚战果（重大进展，全部实测固化）

**已拿到**：
1. **新版 init protobuf 完整明文（296B）**：`D:\dragon-board\.tmp_review\init_pb.bin`
   ——f1=设备UUID `4a81acf4-b516-3e79-ae26-40a67af7b97c`、f2=1、f3=`6.3.20.2`、f4=129、
   **f5=190 字符十六进制签名块**（新格式，非旧 32hex）、**f6=UserID `<脱敏，见 .tmp_review/kpl_credentials.env>`**、
   **f7=Token `<脱敏，同上>`**（HTTP 层同款凭据进 init 了）、f8=99、
   f10=`w48`。按旧组帧 `30 <len> 0002 0259 100000 + pb` 发 14000 实测：服务器能解析、
   回「连接错误：1102」→ 组帧对、**f5 校验不过**（可能绑 mTLS 通道或动态质询）。
2. **解密后推送帧已在 dalvik 堆目视确认**（session1 时代）：`hqList|26:20030/3006-0/`、
   `hqStock|26:20040/2016-0/002614`（奥佳华分时订阅推送）——新版推串格式与旧协议同族。
3. **app 层帧封装推测**：TLS 首条应用记录恒 360B（明文 331B）= init；其后心跳 73/70B、
   订阅 78/150B 等。331-296=35B 开销未定（旧帧头 10B 对不上，疑有第二帧或加密封装）。
4. **TLS 是 BoringSSL/openssl（DOWNGRD 哨兵确认）**，master secret 四轮全量内存扫描
   （dalvik+native、多会话随机数、零块跳过优化）均未命中→疑被清零/白盒化，离线解密不可行。
5. **MITM 基础设施已建**：`relay_mitm.py`（TLS 终结中继）+ 自签 CA 已装模拟器系统区
   （bind-mount `/data/local/tmp/cacerts -> /system/etc/security/cacerts`，重启失效）；
   app 因服务端证书 pin 拒绝 MITM 证书——**pin 不破，MITM 无法看到明文**。
6. **客户端证书（mTLS）在内存可见但副本撕裂**：c8d80000 区发现
   `OU=Client Authentication, CN=mobile2026, email=client2026@kaipan.com`（kaipan Root CA 签发，
   2026-01-26 起十年效期），DER 尾部签名区被覆写，多次刻取均解析失败——**这是下一步的钥匙**。
7. APK 原地重建技术已验证（zip 重建+替换 assets/pub.key 实操成功后已回滚原包，
   备份在设备 `/data/local/tmp/base_backup.apk`）。

**运维状态（务必知道）**：模拟器 iptables DNAT 已清空、透明中继/MITM 进程已停，
app 直连服务器正常工作；系统区多了一张无害的自签 CA（重启即消失）。
攻坚脚本/转储全在 `D:\dragon-board\.tmp_review\`（relay.py、relay_mitm.py、init_pb.bin、
memf/memx/mem5/mem6/mem7 转储、probe_live.py 实测器、findkey*.py 扫描器、ca/ 证书）。

## 三点六、2026-10-26 上午战果：mTLS 已通，init 已被服务器接受（重大突破）

**已固化工件**（`D:\dragon-board\.tmp_review\`）：
- `client_cert.der/.pem`：**mTLS 客户端证书完整重建**（CN=mobile2026, OU=Client Authentication,
  kaipan Root CA 签发, 2026-01-26→2036 十年效期, RSA-2048）。内存里存的是
  BoringSSL 解析后的三分量（TBS 850B + sigalg 15B + sig 517B），缺外层 SEQUENCE 头，
  已手工拼装 `30 82 05 66 + 三分量` 成功解析。
- `client_key.pem`：**配对 RSA-2048 私钥完整重建**。方法：全内存扫 BIGNUM 结构
  （d,top=32,dmax,neg,flags）→ RSA 结构体指针追踪（n,e,d,p,q 八成员）→ p×q==n 数学验证。
  **证书+私钥长期有效，拿到即永久可用，不再依赖模拟器**。
- `init_pb.bin`：296B，字段结构：f1=UUID(36B) f2=1 f3=版本 f4=129 f5=**190B 签名**
  f6=UserID f7=Token(32hex) f8=99 f10="w48"。**f9 不存在**（proto 跳号），pb 本身完整。

**协议实测结果**（复跑脚本 `kpl_live*.py`）：
1. **17000 mTLS 直连成功**：`client_cert.pem + client_key.pem`，TLS1.2 C02F，
   SNI=socket.kaipan.com，服务端不再要求 unknown CA。
2. **init 重放被接受**：发旧组帧 `30 <len> <seq> <cmd=0259> 100000 + init_pb.bin`，
   服务器回 0x20 包（52B）：`seq=0104, cmd=0000, status=00, pb{1: unix秒, 2: 32hex 会话
   ticket, 3: 1}`。**无 1102/2004 错误，ticket 每次连接都发放**。f5 静态重放可过认证。
3. **但服务器随后主动关连接**（init 响应后 1-2s 内 close_notify）。以下变体均无效：
   init 后立即心跳/双 init/ticket 回发/0x09C5 订阅/pipeline 同帧发送/f7 替换 ticket 重连。
4. **app 真实 init 流量 = 360B/记录**，比我们的 init 帧(306B) 多 54B——
   **同一条 TLS 记录里 init 帧后还 pipelined 了一个 54B 帧**（内容未知，极可能是它
   维持会话；app 同秒连发后续 78/75/112B 订阅帧）。
5. **f5 签名每会话变化**（重连后内存新 pb 的 f5 前缀变），静态重放能过认证但
   可能就是 f3=1/被降级/被关的原因之一。
6. 14000 免证书 + 新 pb → 回「连接错误：1102」后**连接保持存活**（错误后还会推第二帧）。

**下一步（按优先级）**：
1. **拿那 54B 帧**：三条路 —— (a) 强制 app 重连后 1 秒内 dd 全内存，搜输出缓冲区
   （试 `0259100000`/init 帧头 `30012f0001` 附近的连续 360B）；(b) 解密 app TLS 会话
   （重连瞬间转储 + master secret 扫描，客户端证书私钥已在手但 ECDHE 会话密钥仍需内存）；
   (c) frida spawn + libcore.io.IoBridge hook（本次实测 spawn 后 app 网络全停，反调试
   已封死此路，需先破 watchdog）。
2. **白盒签名 harness**：f5 动态 ⇒ 建 benign arm64 进程加载 libauthSign.so 调 execHex
   （内存已见签名原料串：userId+UUID+盐 `<脱敏，见 .tmp_review/kpl_credentials.env>`）。工程量大但一劳永逸。
3. **mTLS 通道已打通的部分可固化**：client_cert/key + 连接脚本 `kpl_live.py` 已可复跑，
   任何后续实验不用再过模拟器。

## 三点七、2026-10-26 下午：壳全破解 + 协议 100% 还原（决定性突破）

**A. 壳完全解开（KplArmor 自研壳）**：
- `assets/payload.bin` = KPLA 容器：6B 头 + N×(BE32 len + 数据)；每 chunk = IV(16B) + AES-128-CBC 密文，解密后 zlib inflate = dex
- 密钥就在 libnsc.so（19KB，直接反汇编）：key = ASCII **`KplArmor16ByteKy`**（`eed5c9e4... ^ 0xa5` 的混淆基字节在 .data 0x6800）
- 产物：`payload_dex/classes0-4.dex`（36MB 全部主代码）→ jadx 全量反编译 `main_src/`，**SocketHelper/GameClient/ChallengeVM/ReconnectManager/io 全部源码在手**
- 注意：R8 混淆后 GameClient 主类 = `defpackage/vu`（源文件 ChallengeClient.kt），但其 j() 为 throw null 桩（真身被合并/移走）——**实际连接路径是 SocketHelper（x() 帧序列化 + SocketReader/WriterThread）**

**B. 协议 100% 还原（user.proto 从 dex 里直接读出）**：
```proto
AuthReq { deviceId=1, platformId=2, versionName=3, channelId=4, signature=5,
          userId=6, token=7, connType=8, curTime=9(未赋值不序列化), apiVersion=10, appType=11 }
ChallengeAuthNt { serverTime=1, challenge=2, codeType=3 }
AntiCheatChallenge { data=1 }
```
**认证时序**：
① 服务器下发 cmd 260 ChallengeAuthNt（serverTime + challenge 32hex + codeType）
② 客户端 whiteBoxEncrypt(challenge, deviceId, connType, serverTime) → signature(190hex)
③ 客户端发 cmd 601 AuthReq（status=3, seq=2, body 可 AES-GCM 加密）
④ 服务器 601/602 AuthResp → ⑤ 服务器 cmd 261 AntiCheatChallenge{data 36+N}
⑥ 客户端 execEncryptedHex(data[36:], BE32(data[32:36])) → cmd 262 应答（token32+int32）
⑦ 服务器 262 回执 = 认证完成

**之前的三大谜团全部解释**：
- 52B「ticket」响应其实就是 **cmd 260 challenge**，我们从未应答 → 必然被踢
- init pb 的 296B 并不缺 f9（curTime proto3 未赋值不序列化），差 30B = **encodeAESGCMMsg 的 GCM 开销（12B nonce+16B tag）+ 帧头差异**
- f5 静态重放能过第一关（服务器容忍），但卡在 challenge 应答

**帧格式（逐字节验证）**：发送 `[pkg=status<<4][len 4B BE][seq 2B][cmd 2B][flags 1B=(seq<<3)+enc][extLen 2B][body]`；接收 `[pkg][len 4B][cmd 2B][status 1B][extLen 2B][body]`。与老抓包 `30 0165 0002 0259 10 0000` 逐字节吻合。

**C. 白盒签名服务（signsvc，基建 80% 跑通）**：
- 方案：模拟器 `app_process32` + DexClassLoader 加载真实 SocketRepository 类，JNI 绑定 libauthSign.so（x86 原生）
- 已打通：伪 Application（systemMain+createPackageContext+Instrumentation.newApplication 塞进 mInitialApplication）、nativeGuard ok、**native nativeDecrypt 5 chunks 全部成功**（复现 app 启动喂白盒状态）、initBaxPwd ok
- 工件：`signsvc/`（源码+classes.dex）、`/data/local/tmp/signsvc.dex`+`classes3.dex`+`nsc_lib/`
- **剩余唯一问题**：调 whiteBoxEncrypt/execEncryptedHex 时触发 `killProcess`（libauthSign 反篡改深层检测，检测点未定位；so 路径伪装、包名伪装均无效；patch so 自检失败会立即 SIGABRT）
- 线索：`whiteBoxEncryptTest` 测试 JNI、check 函数 0x347ec0（签名校验链）、`wbe_full.asm`（主流程 727 行待分析）

**D. 下一步（按优先级）**：
1. **签名对重放**：app 每次重连时内存转储抓 (challenge, f5 signature) 配对（dv dump 已见 190hex f5），hold_relay 方案成熟；同 challenge 的签名若可重放则直接通
2. **killProcess 检测点定位**：细读 wbe_full.asm 主流程失败分支
3. 或在真 app 进程存活时用 `/proc/pid/mem` 抓 encodeAESGCMMsg 密钥

**E. 文件清单（`.tmp_review/`）**：`payload_dex/`（5 dex）、`main_src/`（全源码）、`signsvc/`、`kaipan_payload.bin`、`libauthSign_patched.so`（勿用，会 SIGABRT）、`nsc_out/`（libnsc+payload）、`hold_relay.py`（S→C 扣留中继）、`kpl_live5.py`（协议客户端雏形）

## 三点八、2026-10-26 晚：白盒全破 + signsvc 可稳定出真实签名（决定性突破二）

**总战果：whiteBoxEncrypt 在模拟器 app_process32 环境下可稳定输出 95B 真实签名（190 hex，与 app 格式完全一致），白盒反篡改已全部破解。**

### A. killProcess 之谜全解（三层洋葱）

1. **d8 静默失败**：`--output signsvc` 相对路径错 → classes.dex 从未更新 → "改了没生效"假象。**教训：每次 d8 后必须 `python -c "print(b'标记' in open('classes.dex','rb').read())"` 验证。**
2. **NoSuchMethodException → handler 拦截成功**：killProcess 其实是未捕获 Java 异常的 RuntimeInit handler；`Thread.setDefaultUncaughtExceptionHandler` 自定义 handler 可拦截并让进程存活。
3. **FindClass abort 真因**：whiteBoxEncrypt 入口 FindClass("com/yzj/kaipanh/common/Config")——单 classes3.dex 的 DexClassLoader 找不到 → pending CNFE → 第二次 FindClass(ApiConfig) 时 ART AssertNoPendingException abort。**修：multi-dex loader（classes3:0:1:2:4 冒号分隔）。**

### B. check 函数（0x347ec0）完全解码

- 链条：ActivityThread.currentApplication → getPackageName → getPackageManager().getPackageInfo(pkg, GET_SIGNATURES) → signatures[0].toByteArray() → **SHA256(cert DER)** → 与 so 内常量比对（0x938b0=cert hash 前16B `b6e12a59...`，0x92d90=后16B）+ 包名白名单（`com.yzj.kaipanh`/`.debug`/`com.aiyu.kaipanl`）。
- **返回语义：al=1 通过（走真加密主流程）；al=0 拒绝（NewByteArray(0) 空数组）**。
- **运行时 patch**：NDK 编 `libpatch.so`（hooksrc/patch.c），ctor 里从 /proc/self/maps 找 libauthSign 基址，`mprotect` 后把 check 函数头改 `mov al,1; ret`（b0 01 c3）。**内存 patch 不触发文件完整性自检**（文件 patch 会 SIGABRT）。

### C. 主流程依赖链逐个喂齐（缺一即空数组/崩溃）

1. **Config.<clinit>**：需 `MyApplication.getInstance()` 非 null → **Unsafe.allocateInstance**（零构造器副作用，防内部线程 crash）+ 反射注入 `ApplicationLike.application` 字段 = fake app。
2. **ApiConfig.apiVersion**：native 主流程 GetStaticObjectField 要求非 null → **反射强写 "w48"**（final 用 accessFlags hack，非 final 直接 set）。
3. **multi-dex loader**：`DexClassLoader("/data/local/tmp/classes3.dex:/data/local/tmp/classes0.dex:/data/local/tmp/classes1.dex:/data/local/tmp/classes2.dex:/data/local/tmp/classes4.dex", dexopt, libdir, parent)`。
4. **native nativeDecrypt 5 chunks**（喂白盒状态）+ **initBaxPwd(kplCtx.getAssets())** —— patch check 后全部真实执行，全局标志 [base+0x385970] = 白盒上下文指针（非零=成功）。

### D. 1002 排查矩阵（手工 601 仍被拒，已排除项）

| 项 | 状态 |
|---|---|
| 帧格式 pkg+len4+seq2+cmd2+flags1+extlen2+body | ✅ 服务器能解析（返回结构化 201 错误） |
| flags=0x10（d=2 from v() 工厂）| ✅ 已用 |
| WBE 签名 95B→190hex、challenge/serverTime 同会话 | ✅ 已用真实输出 |
| token 未过期（UserInfo.db 有效期至 1793462399）| ✅ |
| apiVersion="w48"（ApiConfig.apiv 硬编码常量）| ✅ 内存 dump 确认 app 同值 |
| connType=99/1/2 | ✅ 均试 |
| TLS1.2 强制 | ✅ 已试 |
| 游客模式（userId="0"、无 token）| ✅ 已试 |
| ext 字段 | ✅ 源码确认 601 无 ext |
| 601 body AES-GCM 加密 + encflag=1（qn0: l(codeType=1) → h()=true → x() 走 encodeAESGCMMsg）| ✅ 已试（257B→285B），仍 1002 |
| connType=99 + 加密 body 组合 | ✅ 已试 |
| **待查**：challenge 时效窗口（手工流程 ~2-9s vs app <0.5s）；**app 真实 601 帧字节级 diff** | ❌ |

### E. 新武器：signsvc 内跑真 SocketHelper（半通）

- `ApiConfig.initConfig(0)` → socketIP=hwsockapp.longhuvip.com:17000，全部 API_* 常量就位。
- `Looper.prepareMainLooper()`（**不是 prepare**！Volley 的 `Looper.getMainLooper()` 需要它）。
- Unsafe 实例的 Collection 字段批量 new（CopyOnWriteArrayList 等）。
- `SocketHelper.H().init(callback)` 构造成功；**Connect 线程在创建 SSLContext 时崩于 conscrypt `NativeCrypto.get_cipher_names` UnsatisfiedLinkError**（app_process32 + LD_LIBRARY_PATH 的 conscrypt native 注册问题）——这是 E 路线唯一残点。

### F. 工件清单（.tmp_review/）

- `signsvc/src/.../SignSvc.java`：完整服务（PING 心跳保活、WBE/ENC/DEC/EXEC/CFG/SIGN/CONN 命令）
- `hooksrc/patch.c` + `libpatch.so`：check 函数运行时 patch
- `kpl_live8.py`：完整协议客户端（TLS→260→WBE→601→261→262），常驻 signsvc + PING 心跳
- `payload_dex/classes0-4.dex` 已推 `/data/local/tmp/`
- so 目录 `/data/app/com.aiyu.kaipanla-MibnEsTYjx-z7wDAymTrqQ==/lib/x86_sig/`（含 libpatch.so）

### G. 下次开工顺序

1. **首查 challenge 时效**：live8 计时打印 260 收到→601 发出的耗时；若 <2s 仍 1002 则排除。
2. **抓 app 真实 601 帧**：杀 app 网络（svc data disable/enable）触发重连，enable 后 1.5s 精确 SIGSTOP，dump 后 PC 搜 `0002 02 59` 帧模式（上次 dump 不完整，需确认 heap 段 dd 全部成功——先 `ls ap2798 | wc -l` 对照 maps rw 段数）。
3. **或修 conscrypt**（E 路线收尾）：排查 LD_LIBRARY_PATH 移除后 TLS 是否恢复；若通，signsvc 内 SocketHelper 直接完成认证（app 全同环境，无 1002 可能）。
4. 1002 速破后：261/262 反作弊轮 + 心跳 + 订阅命令（ServiceHqList）→ 推送落地。


## 三点九、2026-10-26 深夜：varint 大 Bug 修复 + 白盒差异实锤（决定性突破三）

### A. 【最大成果】pb_str varint 编码 Bug（1002 的隐藏污染源）

kpl_live8.py 的 `pb_str(f, b) = bytes([f<<3|2, len(b)]) + b` 把字段长度硬塞 1 字节。**f5 长度 190 > 127，varint 必须 2 字节（0xBE 0x01），实际只写 1 字节 0xBE** → 服务器 varint 解析错位 → f5 越界吞掉 f6/f7 → AuthReq 缺 userId/token → **1002**。

**后果：此前全部 1002 实验（游客模式、connType、加密/明文、flags、TLS 版本）都被此 bug 污染，结论全部作废需重测。**
**已修**：`pb_str` 用真 varint 编码长度，AuthReq 现 296B 与 app 模板对齐。修后仍 1002 → 还有其他差异。

### B. app 真实 f5 签名结构（内存 dump 三实例实证）

- f5 = **190 字符 ASCII hex** = hex(95B 原始输出)
- 95B 前端 = **32 位纯数字 ASCII**（`61451887755777639901511587432083`，三实例恒定，疑为 baxId/设备指纹 16B），**不是 challenge 回显**
- 三次 dump 提取工件：`ap16502/`（pid 16502/5736/14120 三轮）
- dump 脚本产物 = `/data/local/tmp/ap2798.tar`（m_*.bin 打包后自删），PC 端 `tar xf` 解包

### C. signsvc 白盒输出与 app 不一致（实锤）

- signsvc WBE 输出 95B：**前 12 字节 = challenge 前 12 字符 ASCII 回显** + 83B 二进制
- app 真实输出 95B：**前 16B = 纯数字 ASCII** + 密文
- **两者结构不同 → signsvc 的白盒 VM 状态 ≠ app**（nativeDecrypt 5 chunks / initBaxPwd / envStatus=6145 都喂了，仍缺更深初始化）

### D. check 函数 patch 的教训（勿再犯）

1. `mov al,1; ret`（跳过全部）：白盒走"退化路径"输出 95B 假签名，不崩但内容错。
2. `jne→jmp 0x34838a`：成功尾部有 stack canary 校验（`cmpl 0xb8(%esp)`），栈布局不符 → **SIGABRT**。
3. 内联 `mov al,1; mov [ebx+0x6964],1; ret` @0x348220：标志=1 走真路径 → **SIGSEGV（野调用 0x...3cd，白盒表未完全初始化）**。
4. 无 patch（环境修好后 check 自然执行）：也 SIGSEGV——check 内部 JNI 链（getPackageInfo 等）在 signsvc 环境不完整。
- 0x34838a = check 尾部（movb al,1 → [ebx+0x6964] → canary → ret）；**whiteBoxEncrypt = 0x3483c0**；真路径上下文判断在 0x34854c（`cmp [ebx+0x6958],0`）。
- **当前部署**：libpatch.so 已改名 .bak（无 patch 运行）。

### E. challenge 事实修正

- app 三个不同实例收到的 challenge 恒为同一串？——**存疑**：f5 前端是纯数字静态头，**"app challenge = 61451887..." 的判断不可靠**（可能把静态头误当 challenge）。app 真实 challenge 未实证。
- live8 每次连接收到不同 challenge（66405ac0/f3a6012e/...，真 hex）——challenge 含服务器随机成分。
- **【2026-10-26 深夜已解决】app 真实 challenge 实证**：AppLogManager.f() 双落点 = fe0.b("KplSocket", ...)（logcat，release 关）+ GreenDAO insert 进 **KPL_CACHE 库 APP_LOG 表**（/data/data/com.aiyu.kaipanla/databases/KPL_CACHE，mg=xi.e().c()）。用 su cat 拉库后直接字节扫描 UTF-8 模式 `鉴权前挑战包信息`，拿到 6 条：
  - challenge = 990db8913237506fa961c5c8fc7db948 / a9032140... / f63f7363... / 37003c9e... / 8762fbf6... / a4e24d91... —— **每次连接都不同（服务器随机）**
  - `userAuth=>ok,curTime:<serverTime>,connType:99` —— connType=99 实证
  - **静态 challenge 说彻底推翻**；f5 前 32 位纯数字 = 静态设备指纹（疑 initBaxPwd 的 baxId 16B ASCII），与 challenge 无关
  - dump 中 f5 190 字符串只出现 1 次（Java HashMap 序列化块 `604f1270` marker），是缓存值
  - APP_LOG 无 AuthReq/whiteBox 日志（签名不落盘）

### F. 下次开工顺序

1. **从 dump 精确定位 app 真实 challenge**：搜 `12 20`+32hex / `12 10`+16B 高熵，配对 serverTime（`08` varint）。
2. **白盒 VM 差异定位**：signsvc 输出前 12B challenge 回显 vs app 前 16B 纯数字——反汇编 WBE 主流程开头（0x3485xx 起），找出"头 16B 从哪个全局状态来"；或 diff [0x6958] 上下文指针指向的表内容（app 进程 vs signsvc 进程各 dump 一次 rw 段）。
3. **重放路线重启**：拿真实 (challenge, f5) 配对后，用修好 varint 的 live8 重放（varint bug 修复让所有重放结论重新有效！若 challenge 真恒定，直接成功）。
4. SocketHelper/conscrypt 路线保持备选。


## 三点十、2026-10-26 深夜第二波：SSL 明文钩子基础设施 + 帧格式全面确认

### A. 【基础设施】libredir3.so = LD_PRELOAD(wrap prop) SSL 钩子

- `setprop wrap.com.aiyu.kaipanla "LD_PRELOAD=/data/local/tmp/libredir3.so"`（ro.debuggable=1 生效）→ app 进程加载我们的 so
- 导出 `SSL_write`/`SSL_read`/`SSL_do_handshake` 符号 → **libjavacrypto.so（conscrypt）的懒解析调用被拦截**（注意：GOT patch 不可用——constructor 时刻 libjavacrypto 未加载；靠 LD_PRELOAD 符号优先）
- 全部明文记录到 `/data/local/tmp/sslcap.bin`：格式 `[8B tag][4B len LE][data]`，tag=SSLW/SSLR/HDSK
- **预建文件必须 root touch + chmod 666**（app uid 无法在 /data/local/tmp 创建）
- **wrap 用完必须 `setprop wrap.com.aiyu.kaipanla ""` + 重启 app**（否则 app 网络异常风险）

### B. 【帧格式终极确认】（与之前认知的差异修正）

- **服务器→客户端帧**：`[pkg=0x20][len 4BE][cmd 2][status 1][extlen 2][payload]`（cmd 在前！live8 的 read_frame 一直是对的）
  - 260 例：`20 0000002f 0104 00 0000 08<serverTime varint> 12 20 <32B challenge ASCII> 18 01`（52B）
- **客户端→服务器帧**：`[pkg=0x30 或 0x40][len 4BE][seq 2][cmd 2][flags 1][extlen 2][body]`
  - **pkg = e(N) << 4**：e(3)→0x30（行情 socket 帧），e(4)→0x40（订阅推送帧）
  - **flags = (d << 3) + (加密?1:0)**：ux0.s(z)；601 (g(2)→d=2) 加密=0x11；610=0x11；602=0x01（d=0）
- **live8 的组帧全对**（pkg 0x30、flags 0x10|enc、seq 已改 1）——但 601 仍 1002

### C. 【已捕获的 app 帧谱系】（sslcap.bin，多次累计）

- 0x30 行情 socket：610（SSLW/SSLR, flags 0x11）、602（SSLW/SSLR, flags 0x01）
- 0x40 订阅 socket：2301(0x08fd, flags 0x09)、2303(0x08ff, 0x01)、2304(0x0900, 0x01)——**task-4 的订阅命令素材已到手**（含 ext=3B 的帧）
- HTTP API（POST /get_config 等）
- **9 个完整 260 帧**（challenge 全历史可提取）

### D. 【未解之谜】601 帧从未被捕获

- SSLW 里没有 cmd=0259 的帧、Java 堆内存扫描（`30 000001?? 0001 0259 11 0000` 帧头模式 + `2a be 01`+190hex 模式）都零命中
- 而 610/602/2301 全被捕获、260 全被捕获、userAuth 日志证明 601 发送了
- **下次开工头号课题**：601 的写路径为何绕过被钩的 SSL_write（候选：zygote 时代已绑定的调用点/其他写函数/BufferedOutputStream 合并）

### E. call_wbe（app 内 JNI 调 whiteBoxEncrypt）两轮挂死 SSL 线程

- try_260 解析 260 成功（wbdbg.txt 有 "T260 chal=..."），call_wbe 后线程挂死（app 网络断）
- 嫌疑：与 app 自身 WBE 调用并发竞态（白盒非线程安全）；推迟到 SSL_write 触发也挂（wbeout.txt 空 + socket 断）
- **JNI 调用要点**（复用）：JavaVM 函数表 GetEnv=槽位 6（3 reserved + Destroy 3 + Attach 4 + Detach 5）；JNIEnv 函数表：NewStringUTF=167、GetByteArrayElements=184、GetArrayLength=171
- **此路线暂停**（app 稳定性约束）

### F. 其他事实修正

- signsvc 的 stdin 必须用 `printf 'cmd
' | su -c "... app_process"`（adb 管道直喂 su 的 stdin 已失效——今天才发现的回归）
- app 使用的 8080 连接是 IPv6-mapped AF_INET6 socket（IPv4 iptables DNAT 抓不到）
- MITM 不可行：app 校验服务器证书（sslv3 alert certificate unknown）
- libssl.so 为系统动态库（libjavacrypto 导入 SSL_write/SSL_read/SSL_do_handshake）

### G. 下次开工顺序（修订）

1. **破 601 之谜**：a) 检查 conscrypt 版本是否有 `SSL_write_ex`（设备 /system/lib 里 grep 所有 so 的 SSL_write 导入者）；b) 用 LD_PRELOAD 同时导出更多候选符号（SSL_write_ex/SSL_do_handshake 的兄弟）；c) 或放弃 601 抓取，转 signsvc 修复
2. **signsvc 白盒对拍**：用 wbdbg 提取的真实 (challenge, serverTime) 对 signsvc WBE 做同参数调用，其输出结构（echo 12B+83B）与 app 成功认证这一事实自洽——直接用 signsvc 输出重放 601（live8），若 1002 仍在则差异在 WBE 字节层面
3. **E 路线（SocketHelper）备选**；conscrypt UnsatisfiedLinkError 问题未解
4. **task-4 可先行**：0x40 订阅帧（2301/2303/2304）的 pb 结构已到手——解析订阅协议可以在认证通过前推进（订阅命令清单 + 推送帧格式）——**降低总链路风险**


## 三点十一、2026-10-26 收官：0x40 订阅通道协议地图（task-4 核心发现）

### A. 订阅命令全景（源码 + 捕获双证实）

| cmd | pkg(e<<4) | 请求 pb | 回包 pb | 说明 |
|-----|-----------|---------|---------|------|
| 2301 | 0x40 (e4) | Hq.VersionReq(version) | Hq.PlateSearchListResp（含 timestamp，回写 version 增量轮询） | 板块列表 |
| 2303 | 0x40 (e4) | Hq.VersionReq | Hq.StockSearchListNewResp | 股票列表 |
| 2304 | 0x40 (e4) | Hq.VersionReq | Hq.StockSearchListNewResp（version 增量） | 股票列表(另一版本) |
| 2300 | 0x40 (e4) | - | Hq.IndexSearchListResp | 指数列表 |
| 3001 | 0x40 (e4) | mn0.a(list, 0,2,0,size,rc.j()) | - | 板块/股票批量订阅（StockBatchAdd 等） |
| 3006 | 0x40 (e4) | mn0.h(板块id...) → Hq.HQStockIdListReq{f1: repeated string stockIds} | - | 底部索引行情 |
| 402 | 0x50 (e5) | mn0.j(subId) → Base.UnsubIdReq{addSubIds} | Base.ResubNt(220) | 退订 |
| 262 | 0x30 (e3) | User.AntiCheatChallenge(data) | - | 反作弊应答 |

- 通用订阅入口：SocketPresenter.y(subId) → `ux0.v().c(cmd).g(优先级).f(true).d(pb).e((byte)4).a()` → SocketRepository.m(subId, packet)
- mn0.h(String... stockIds) = Hq.HQStockIdListReq.newBuilder().addAllStockIds(...) —— **f1 = repeated string**
- qn0.k(cmd→pb) 映射表在 qn0.java 586-640

### B. 0x40 通道 = 路由化消息通道（MQTT 风格）

- 客户端帧：`[40][len4BE][seq2][cmd2][flags1=0x9|0x1][extlen2][ext][body]`
- **ext = 明文路由 topic**：`02 08fd 03 0017 "global|26:20020/2301-1/"`（cmd echo + 长度 + ascii 路由串：`[dc]|[?]/[cmd-subid]/`）
- 服务器回包 extlen=29/30（含 topic 回显），body=加密
- **body 全部 AES-GCM 加密**（依赖连接态的 encodeAESGCMMsg/decodeAESGCMMsg——signsvc 的 ENC/DEC 命令即此）
- app 周期性重发 2301/2303/2304（VersionReq.version 增量轮询，服务器只回变化部分）
- **推送模型 = 客户端轮询式订阅（version 协商）+ 服务器增量应答**，不是纯服务器推送

### C. 鲁棒解析器（sslcap.bin 并发写损坏问题）

多进程/多线程 O_APPEND 并发写导致记录交错——解析需逐字节扫合法记录头（`SSLW/SSLR/HDSK` + len 合理性校验），已验证 2227 条记录可恢复。

### D. task-4 剩余工作（下次开工）

1. 3001/3006 的请求 pb 完整结构（mn0.a 的参数含义）
2. body 解密：认证通过后用连接态 GCM（signsvc DEC）解 0x40 帧——**需要 601 先通**
3. 推送帧的股票/板块字段映射（StockSearchListNewResp 字段：价格/涨跌幅等——Hq.java 里有完整 proto 定义）
4. 组装 PC Python 客户端的订阅循环 + 解析器 + 30 分钟稳定流验证


## 三点十二、2026-10-27 凌晨：全链路打通（认证→订阅→推送→WebSocket→浏览器）

### A. 【决定性勘误】认证命令号 = 610，不是 601

SocketRepository.java:168：`ux0.v().c(TypedValues.MotionType.TYPE_QUANTIZE_MOTIONSTEPS)` = **c(610)**。
反编译常量名误导了此前所有会话（TYPE_QUANTIZE_MOTIONSTEPS=610，601 从未被 app 发送）。
**live8 把 cmd 601 改为 610 的瞬间，1002 消失**——服务器回加密 AuthResp 而非 ErrResp。
此前抓不到"601 帧"之谜同步告破：app 从不发 601，捕获里的 0262(610) 就是认证帧。

### B. 完整认证链（全部实测通过）

1. TLS 1.2（client_cert.pem mTLS）→ 260（challenge 每连接随机）
2. 610 AuthReq（WBE 签名 95B→190hex，GCM 加密 body，d=2 flags=0x11）
3. 610 ack（echo 格式，加密 AuthResp）→ **DEC 解密 = `192.168.0.x:port`（服务器 dispatch 内网地址，仅参考，不需重连）**
4. 602 LoginStateReq{userId, token, deviceId}（d=0 flags=0x01）→ ack
5. 订阅（pkg 0x40 + ext 路由头 `02 <cmd 2BE>`）：2301(d=1 flags=0x09)/2303(d=0 0x01)/2304(d=0 0x01) VersionReq{version} → 应答带 CDN 快照 URL（appimgcdn.kaipanla.com/plate/133_*.data 等，可直接下载解析板块/股票清单）
6. 3001 GroupStockQuotasReq{quotaType:0, sortType:2, start:0, count=len(stockIds), f10: repeated string stockIds}（**count 必须 = stockIds 数量**，不符→ErrResp 2000）→ **板块行情数据**（801044 土地流转 890.098 / 885423 安防 1201.486）
7. 0x60 推送帧：[extlen2][ext 路由 ascii][cmd2][flags1][inner_extlen2][payload 加密]——服务器在订阅后主动推送行情增量
8. DEC 解密依赖 connType=99 的固定派生（非会话密钥），signsvc 独立进程即可解

### C. 服务器会话时长规律（2026-10-27 修正：非固定 TTL，与"认证速度/重复 seq"相关）

- **认证+订阅在 <1s 内完成的连接 → 服务器 ~6s 即断**（机器人检测）；拟人延迟后 → 15-25s；
  adb 链路 5-8s 完成（kpl_collector）→ 75-160s。心跳频率（3s/5s/14s）不影响寿命
- **重复 seq 会被服务器拒绝并断连**（110/2000）：keepalive 重发必须递增 seq（实测 seq=4 重复 → 立即断）
- 客户端策略 = app 同款 ReconnectManager：断开后 2s 重连，数据流跨会话连续
- **实测：25 会话重连链维持 32.3 分钟连续收流**（44 帧解码行情、26KB、零丢弃），期间 app 正常运行
- 心跳/保活：610 AuthReq 重发（递增 seq，内容原样）+ 602 + 3001 轮询交替
- 261/262 反作弊轮：整个测试期间服务器从未下发 261（auth 不依赖它）；EXEC 注入未实现，若未来触发需补

### D. QuantBoard 集成组件（全部落库 quant-board/）

| 文件 | 职责 |
|------|------|
| backend/services/kpl_socket_protocol.py | 协议纯逻辑：帧构造/解析/pb（tag 是 varint！f100→a2 06）、260/610/602/3001/推送帧全解析 |
| backend/services/kpl_collector_service.py | 采集服务：signsvc codec（ENC/DEC/WBE，EOF 自愈重建）+ 会话状态机 + 事件广播（_json_safe 兜底） |
| backend/serve_kpl_socket.py | FastAPI 入口（:8002）：WS /ws/kpl-quotes + /api/kpl/status|start|stop + /kpl 页面 |
| backend/kpl_page/index.html | 浏览器实时面板：行情表 + 事件日志 + fail-visible 降级提示 |
| backend/services/__tests__/test_kpl_socket_protocol.py | 14 用例（真实捕获帧 fixture） |
| backend/services/__tests__/test_kpl_collector_service.py | 7 用例（FakeCodec/FakeSocket 全 mock 会话状态机 + fail-visible 断言） |

- 端到端实测：WS 57 事件 / 6 轮完整 auth→streaming→quotes 周期，跨 TTL 会话连续
- 测试红线遵守：pytest 全 mock（FakeCodec/FakeSocket），零真实连接

### E. 运维事项

- 启动服务：`.\.venv\Scripts\python.exe -m uvicorn backend.serve_kpl_socket:app --host 127.0.0.1 --port 8002`（8001 被占用）
- 面板：http://127.0.0.1:8002/kpl （点"启动采集"）
- 依赖：模拟器在线（adb -s emulator-5554）+ signsvc（/data/local/tmp/signsvc.dex）+ client_cert.pem（环境变量 KPL_CLIENT_CERT/KEY 可覆盖，默认指向 .tmp_review）
- signsvc segfault 自愈：codec 检测 EOF 后自动重建进程（EOF 死旋 bug 已修，readline 空串 50 次即抛）
- **app 保活**：wrap prop 已清空；PC 客户端与 app 同时在线互不踢（实测 deviceId 冲突不存在）；app 被 force-stop 后 am start 即恢复
- 模拟器重启后：adb 设备号可能变化（127.0.0.1:5555 → emulator-5554），KPL_ADB_DEVICE 环境变量调整

### F. 遗留风险与未竟

1. **quotas 字段语义为推断**：Item.f100 数组顺序对应 app 展示列（价格/涨跌/成交额…），已见 890.098/-0.244/9124052992 等，但未逐一与 app UI 对照确认——接入前建议收盘时段与 app 同屏核对
2. **261/262 反作弊轮未实测**：EXEC 注入未实现；若服务器开始下发 261，需把 signsvc EXEC 接入 collector
3. **3001 批量订阅规模**：实测 2 个板块稳定；全市场 1571 板块未测（count 一致性约束）
4. **2301/2303/2304 仅版本轮询**：实时行情主通道是 3001；个股级订阅（3006 HQStockIdListReq）结构已知未实测
5. **认证身份**：游客模式（userId=0）即可收行情；正式账户 token 轮换未跟踪
6. **单连接 TTL**：若未来服务器缩短 TTL，重连风暴风险——已按 2s 间隔重连，未见限流

### G2. :8000 集成与个股订阅（2026-10-27 审计整改）

- **:8000 集成**：backend/api/kpl_proxy_routes.py（include 进 main.py）——
  /api/kpl/status|start|stop 透传 :8002（fail-visible 结构化 502），
  **WS /api/kpl/ws/kpl-quotes 双向中继**（注意 router prefix：路径含 /api/kpl 前缀）
- **个股订阅**：3006 HQStockIdListReq{f1 repeated stockIds}，ext=02 0bbe——
  **个股实时价实测到流**：000001 平安银行 price=113000（×10000 缩放=11.30），
  IndexSimpleQuotasResp{f1 items[{id,name,price,incPrice,incRate}]}
- 持久化证据：.tmp_review/ws_8000_sample.jsonl（174 事件：auth 27/status 27/stock_quotes 27/quotes 14/raw 5/ping 47）
- 服务实例管理注意：venv python.exe 是 launcher+child 双进程对；多次 nohup/kill 会残留旧实例
  → 采集线程互踢（会话 ~6s）。启动前必须确认只有一个 serve_kpl_socket 进程对

### G. 任务清单完成状态（goal mvp9ogq0-7cd2al）

1. ✅ challenge 定位（KPL_CACHE APP_LOG，每连接随机）
2. ✅ 白盒 VM 差异定位（上下文表 16KB diff=0，无差异；此前误判澄清）
3. ✅ 认证通过（cmd 610 勘误 + 261/262 未触发说明 + 心跳/重连链 ≥5min）
4. ✅ 订阅推送解析（协议全景表 + 32.3min 稳定流 + 0x60 推送破解）
5. ✅ QuantBoard 集成（WS + 面板 + 21 mock 测试 + 端到端 57 事件验证）
6. ✅ 交接文档（本节）


## 四、历史破局路径（已完成，留档）

**路径 A'（2026-10-26 上午已部分完成，见三点六）**：客户端证书✅、私钥✅、mTLS✅、
init 重放✅（ticket 已发放）。剩余：54B 第二帧 + f5 动态签名。原计划存档：
1. 强制 app 重连（杀透明中继上游）后**秒级**全量 native 转储（dd 直读 /proc/<pid>/mem，
   脚本 dump_x.sh 模板在 .tmp_review，注意 32 位 shell 算术溢出要用十进制 skip）；
2. 找 `Client Authentication`/`mobile2026` 客户端证书完整 DER + 配对私钥 ✅已完成；
3. 证书+私钥建 mTLS 连 17000/8080 → 发 init ✅已完成（ticket 发放但会话被关）；
4. 剩余靠白盒 harness 或 54B 帧提取（见三点六下一步）。
**路径 A（盘中 spawn+hook，仍有效）**：交易日盘中：
1. `frida -f spawn` KPL（spawn 模式 Java 桥已验证可用）；
2. adb 自动导航进行情页（点龙虎榜/个股分时，触发 socket+类加载；盘中行情页才有流量）；
3. `Java.enumerateClassLoaders` 找壳 loader → `Java.ClassFactory.get(loader).use(
   'com.yzj.kaipanh.newindex.common.socket.ChallengeVM')` → **hook execHex 观察真实输入
   输出**（init 请求参数+签名直接现形）→ 依样复刻；
4. 或把模拟器常驻成 **RPC 签名服务**（frida RPC 暴露 execHex，自研客户端建连前调用取签名，
   不逆向算法），mTLS 用 assets/PrivateKey + crtFromJNI。
**路径 B（并行）**：HTTP 轮询方案落地盘中弱转强——层1（60s/轮 3 发 240 板块强度）+层3
（观察名单板块成分股盘中实时），分钟级帧落 `plate_strength_intraday`；用户已认可轮询是
官方容忍节奏（wzslinker 网页自己盘中 TTL 15s）。

**之后的完整链**（等 Socket 或轮询任一落地）：采集落库（plate_strength/plate_boom_history
+盘中帧）→ 一次性回填（层2 ~1000 发、层1 3 发×交易日，先 50 发试水限流）→ ID 桥
`plate_index` 映射表（成分重叠 ≥0.40 自动+人工复核）→ **先拿爆发史样例日给用户盘感对账**
→ v2 四阶段状态机方案讨论稿逐条裁定 → 预登记。

## 五、关键文件与命令

- **总记录**：`quant-board/docs/hotlist-jev/theme-corpus-extra-sources-survey-20261023.md`
  §9（精选板块勘察）~§9.11（Socket 五轮）——本轮一切细节都在里面。
- 证据：`data/backups/kpl-corpus-probe-20261025/`（排行/成分股/爆发史/apifox md/exe 提取）；
  攻坚脚本在 `D:\dragon-board\.tmp_review\`（kpl_sock_probe.py、kpl_hook*.js、
  kpl_frida16*.py、evil_8080.py、kpl.apk、apk_unzip/lib/arm64-v8a/libauthSign.so），
  **固化时移入 data/backups**。
- 快速复跑（全部零 token，间隔 ≥2s）：
  ```bash
  # 层1 排行（实时）
  curl -s -X POST "https://apphwhq.longhuvip.com/w1/api/index.php" -H "User-Agent: ad" \
    -H "Content-Type: application/x-www-form-urlencoded; charset=utf-8" \
    --data "Index=0&Order=1&PhoneOSNew=2&Type=2&VerSion=5.13.0.1&ZSType=7&a=RealRankingInfo&apiv=w35&c=ZhiShuRanking&st=80&Token=0&UserID=0"
  # 层2 爆发历史（机器人全史，Index 分页 0/100/200…）
  curl -s "https://apphis.longhuvip.com/w1/api/index.php?Index=0&IsBoom=0&PhoneOSNew=2&StockID=801159&Type=0&VerSion=5.16.0.5&a=GetDayBaseFaceListZDEvnArt&apiv=w38&c=ZhiShuKLine&st=100" -H "User-Agent: ad"
  # 层3 历史成分股（凭据取 mapping_refresh.py，勿拷贝第二份）
  curl -s -X POST "https://apphis.longhuvip.com/w1/api/index.php" -H "User-Agent: Dalvik/2.1.0 (Linux; U; Android 9; HPB-AN00 Build/PQ3A.190605.003)" \
    --data "Type=6&Order=1&Index=0&st=80&PlateID=801159&Date=2026-10-23&a=ZhiShuStockList_W8&c=ZhiShuRanking&PhoneOSNew=2&DeviceID=<uuid>&VerSion=5.13.0.0&old=1&apiv=w21&UserID=397605&Token=<现役token>"
  ```
- 记忆文件：`theme-cycle-v1.md`（本任务全程已记录）；AGENTS.md/SKILLS.md 已读约束照旧。

## 六、纪律提醒（新会话务必遵守）

- 调外部接口：单发间隔 ≥2s，禁连发；1000 发级回填前先 50 发试水限流。
- 层3 用现役凭据走 `mapping_refresh.py` 公共出口，**禁止另拷一份凭据常量**。
- isBoom/ZTNum/LZInfo 等 KPL 原始字段**原样落库不自算**；阴性结果不当终局判决。
- 下一步动作以用户裁决为准：**A. 盘中继续攻签名 / B. 先落地 HTTP 轮询 + A 并行**（AI 建议 B+A）。
