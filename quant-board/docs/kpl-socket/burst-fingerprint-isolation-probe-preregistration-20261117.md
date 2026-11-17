# KPL 爆发指纹隔离探针预登记（2026-11-17）

> 状态：**预登记，未开火**。需用户批准 + 下一交易日（11-18）窗内执行。
> 议题来源：sub-registry-refactor-plan §7.1.1 / §12 遗留独立议题——「生产会话
> ~60.8s 被 10054 爆发指纹重置，短会话限制退订」。本文是该议题的实证收口设计，
> 不改变任何生产行为；探针定案后再裁生产杠杆（A/B）。
> 红线沿用 README §六 / AGENTS §1.2-9：pytest 全 mock；真实连接只走预登记 +
> 预算确认开火路径；先预算后动手。

## 0. 结论先行（待探针验证的假说）

1. **双因素模型已定案**（§7.1.1 实弹）：生产短命 (~56-63s) 由**爆发指纹风控
   10054 RST** 主导，非干净 TTL 轮换；610 重发是另一独立确定性杀连因素（已
   `KPL_KA_MODE=off` 消除）。最小订阅面 + kaoff 受控会话存活 **120s+**（右删失）
   = 真实干净 TTL ≥120s。
2. **待钉死的核心未知**：~110-120 帧/会话的订阅爆发里，**哪一族主导 10054
   指纹**——2103 页爆发（42 帧）？per-stock 2203/2013 爆发（~52 帧）？还是总量
   阈值/3001-3006 分块形态？现有证据只有「全订阅面 → ~60s 10054」与「最小面 →
   120s+」两端，中间族未隔离。
3. **死循环（短会话限制退订）**：短会话 (~60s) → 402 退订来不及触发（池成员退出
   + 防抖 5s 需更长窗）→ `unsub_sent_n=0` → 订阅面不收缩 → 下一会话仍全量爆发 →
   仍短命。402 机制 r5 已证成（removed=1），被短会话锁死。**破局点 = 降低初始
   爆发面让首会话活过 60s**，给 402 收缩时间，形成正循环。
4. **本探针目标**：隔离主导族 → 为生产杠杆裁决提供实证：
   - 杠杆 A：per-stock 稀疏起步（2203/2013 初始只订 Top-N 活跃池成员，存活后动态扩）
   - 杠杆 B：2103 页裁剪（非必需 pid 页延后/降频）
   - 不猜：哪族主导由探针定案，再选杠杆。

## 1. 测量底座（已落地，本提交，零行为变更）

`kpl_collector_service.py` 死因分类观测（纯增量，不参与退避计算）：

- `_classify_death_cause(exc)`：`rst_10054`（ConnectionResetError/winerror 10054，
  爆发指纹 RST）/ `abort_10053` / `errresp_<code>`（1106/1002 TTL·610 杀连、
  2008 明文 211 lethal）/ `send_dead`（drain send 失败门禁）/ `setup_fail`（收流前
  早退）/ `eof_clean`（无错误码服务器关连=干净轮换）/ `signsvc` / `anti_cheat` /
  `timeout` / `network:<Type>`。
- 判据优先级：异常类型/winerror → 本会话 ErrResp code（`_session_err_code`，
  CMD_ERROR/201 与 CMD_ERROR_NT/110 纯记录）→ `_sock_dead` → `_session_streaming`
  → eof_clean。
- 每会话死因进 `status()`：`last_death_cause` / `death_cause_counts` /
  `last_session_err_code`；并发 `session_death` 事件（cause/session_s/err_code/
  sock_dead），探针从事件流直读。
- **零行为变更实证**：`test_run_loop_records_death_without_changing_backoff`——
  10054 短命会话仍走原 <60s 螺旋退避（streak=1 → backoff=4.0），重连时机/阈值不变。
- 测试：TestDeathCause 4 用例；KPL 专项 209 / services+api 582 passed。

## 2. 探针设计（受控订阅面隔离，单会话禁重连）

方法论沿用 `scripts/probe_kpl_sub_batch.py`（ProbeCollector：禁用基础订阅面 +
首 drain 前插受控项 + `_run_loop` 覆写单会话不重开）。**固定控制变量**（消除已知
因素，唯一变量=订阅面族）：

- `ka_mode=off`（消除 610 确定性杀连，§7.1.1）
- `sub_batch_mode=direct`（不引入 211 风控面；402 日预算不动）
- `sub_registry_enabled=1` + `sub_unique_id=1`（生产同款注册表/唯一 hint）
- `human_delay=True, auth_phase_delay=5.0, auth_phase_jitter=3.0`（生产同款拟人）
- 同 device/token/connType=99；`enforce_trading_hours=False`（探针自管窗）
- 变体间冷却 **≥180s**（§3.4 螺旋实锤：冷却后打标衰减）

### 2.1 变体矩阵（每变体 ≥3 会话取中位，同 P4' 口径）

| 变体 | 订阅面 | 帧量级 | 假说检验 |
|------|--------|--------|----------|
| **S0** globals-only | daban 全局族（2114/2115/2116/2119/2120/2126/2100/2106/2111）+ 3001/3006 最小；**无 2103 页、无 per-stock** | ~10 | 基线：预期 120s+ `eof_clean`（复现最小面长寿） |
| **S1** globals+pages | S0 + 2103×42 页（pid 0/8/6/1/2/3 ×7）；**无 per-stock** | ~52 | 2103 页爆发是否单独触发 ~60s `rst_10054` |
| **S2** globals+perstock | S0 + 2203/2013 per-stock（~30 活跃池成员 ×2）；**无 2103 页** | ~70 | per-stock 爆发是否单独触发 ~60s `rst_10054` |
| **S3** full（对照） | 生产全订阅面（S1+S2，detail 关） | ~120 | 复现生产 ~60s `rst_10054` 基线（锚定） |

per-stock 池注入：S2/S3 用 ~30 只活跃涨停池成员（探针工具受控池列表，走真实
`_pool_stock_ids` → `_queue_zt_reason_new`/`_queue_theme_new` 生产路径，非假股）。
池来源：上一交易日 `kpl_daban_pool` 日档成员（只读，不写库）。

### 2.2 观测指标（每会话）

- `session_s` / `death_cause`（rst_10054 vs errresp_1106 vs eof_clean）/ `err_code`
- 订阅帧实发数（帧转储直读，按 cmd 族分组：2103/2203/2013/全局/3001/3006）
- 首推送到达时刻（time-to-first-push）/ 推送总量（按族）
- `setup_s`（订阅链完成耗时）/ `sock_dead`（drain send 是否撞死）
- 长寿会话（若 S0/S1/S2 活过 90s）：`unsub_sent_n` 是否 >0（正循环可行性观测）

### 2.3 裁决矩阵（定案 → 杠杆）

| 探针结果 | 定案 | 生产杠杆 |
|----------|------|----------|
| S1 ~60s rst_10054，S2 120s+ | **2103 页爆发主导** | B：非必需 pid 页裁剪/延后 |
| S2 ~60s rst_10054，S1 120s+ | **per-stock 爆发主导** | A：per-stock 稀疏起步 |
| S1/S2 均 ~60s rst_10054 | 两族叠加/总量阈值 | A+B 组合降面 |
| S1/S2 均 120s+，S3 ~60s | 总量阈值或 3001/3006 分块形态 | 进一步隔离 3001/3006（S4） |
| S0 也 ~60s rst_10054 | 全局族/分块即触发（推翻最小面长寿前提） | 重查 3001/3006 分块节奏（§3.4 背靠背指纹） |

**诚实披露**：探针是假说隔离，不是修复；任一变体若与 §7.1.1 既有结论矛盾
（如 S0 短命），先复核控制变量（kaoff 是否真生效、池注入是否漏帧）再归因，
不单凭结果调方案（AGENTS §1.2-6 归因顺序：原料→题目→协议→方案）。

## 3. 频控预算（AGENTS §1.2-9 硬红线，开火前对照）

| 项 | 预算 | 说明 |
|----|------|------|
| 会话总数 | **≤14**（4 变体 ×3 + 2 重试预留） | 单会话禁重连，失败不重开 |
| 每会话新增帧 | S0 ~10 / S1 ~52 / S2 ~70 / S3 ~120 | **超既有探针 ≤12 帧预算**——本探针测的就是生产爆发面本身，需显式新预算（本文） |
| 211 帧 | **0** | direct only，211 日预算（8/60）不动 |
| 402 帧 | **0** | 退订仅观测 unsub_sent_n（长寿会话自然触发），不主动射 402；402 日预算（2/2 已耗尽）不动 |
| 变体间冷却 | ≥180s | 打标衰减 |
| 总时长 | ~50-70min | 14 会话 ×（观察窗 120s + 冷却 180s）≈ 70min |
| 观察窗 | 120s/会话 | 盖过生产典型死亡点 ~60s + 验证长寿右删失 |
| 窗内执行 | 11-18 竞价窗 (09:15-09:27) 或下午盘 (13:00-14:30) | 推送交付需盘中；竞价窗优先（与首帧基线验收同窗） |

**累积风控披露**：本探针帧量级高于注册表探针（测全爆发面），单日 ≤14 会话 ×
~120 帧 ≈ 1680 帧上限；与生产日常重连帧量同量级（生产每日 ~数百会话 ×120 帧），
不新增异常指纹类型（全是生产已发的 direct 帧）。冷却 180s + 单会话纪律控制累积。

## 4. 工具与实施（探针批准后才动）

- 新增 `scripts/probe_kpl_burst_surface.py`（或扩展 probe_kpl_sub_batch.py 增
  S0-S3 变体）：复用 ProbeCollector 受控面注入 + 单会话纪律；新增：
  - 按变体配置 `daban_subs`/`daban_list_pids`/`zt_reason_subs`/`theme_subs` +
    受控池注入（~30 活跃成员，只读上一交易日日档）
  - summary 增 `death_cause`/`session_death` 事件/按族帧计数/`unsub_sent_n`
  - 变体默认观察窗 120s
- mock 测试：变体订阅面构成断言（S0 无 2103/per-stock、S1 无 per-stock、S2 无
  2103 页）+ death_cause 进 summary + 单会话禁重连回归。
- **生产代码零改动**（死因观测已落地）；探针工具独立，不入生产链路。

## 5. 开火路径与回退

1. 本文预登记 → **用户批准**（预算 §3 + 变体 §2.1）→ 11-18 窗内开火。
2. 开火前 :8002 生产采集 POST stop（单实例纪律，README §5.3）；探针毕 POST start
   恢复（idle_offhours 自动恢复或窗内直接 subscribing）。
3. 证据落仓库根 `tmp/`（gitignore）：帧转储/事件/摘要；分析完毕按 AGENTS 临时
   产物纪律逐个删除；结论固化本文 §6 + README §3.4/§3.5。
4. 回退：探针异常即停（单会话不重开）；生产行为始终未变（死因观测纯增量）；
   杠杆 A/B 生产变更需探针定案 + 另行用户裁决，不在本探针范围。

## 6. 裁决回填（开火后填）

### 6.0 工具 shakedown（2026-11-17 15:28 收盘前，S0×1，已清理临时产物）

- 工具 `scripts/probe_kpl_burst_surface.py` 实弹验证通过（单会话禁重连 + 死因分类入 summary）。
- **S0 globals-only：session_s=90.4（右删失）death=eof_clean err_code=None**；
  帧族 globals=7 / 3001_3006=39（轮询）/ auth 链 5；无 2103 页、无 per-stock。
- **初步信号**：最小面 90s+ 干净关连（无 10054）vs 生产全面 ~37-60s rst_10054
  （live death_cause_counts rst_10054×4）→ 指纹在新增族（2103 页/per-stock），
  不在 globals/3001-3006 基底。**诚实披露**：收盘前 15:29 服务器攻击性可能偏低，
  且 S0 仅 1 会话（非 ≥3 中位）；定案仍需 11-18 盘中完整矩阵 S1/S2/S3 隔离。

- [ ] S0-S3 各 ≥3 会话 session_s/death_cause 中位 + 按族帧计数
- [ ] 主导族定案（裁决矩阵 §2.3）
- [ ] 杠杆 A/B 推荐 + 生产变更预登记（另行文档）
- [ ] 长寿会话 unsub_sent_n>0 正循环观测
- [ ] README §3.4/§3.5 + AI_COLLABORATION 同步

## 7. 验证清单

- [x] 死因分类观测落地（零行为变更）：TestDeathCause 4 + KPL 267 / services+api 582 passed
- [x] 探针工具实施 + mock 测试：`scripts/probe_kpl_burst_surface.py` +
      `test_kpl_burst_surface_probe.py` 12 passed（变体面构成/控制变量/受控池/
      单会话死因/帧族）
- [x] S0 shakedown（11-17 收盘前×1）：90.4s eof_clean，工具实弹验证通过（§6.0）
- [ ] 完整矩阵实弹开火（用户已批准「开火」；11-18 竞价窗 09:15，今日 15:28 窗尽）
- [ ] 结论回填 + 文档同步