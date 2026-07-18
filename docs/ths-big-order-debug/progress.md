# THSBigOrder 排查进度

## 2026-07-16

- 已读取项目规则、skills 指南和 `systematic-debugging` 流程。
- 已确认工作区存在与 THSBigOrder 数据链路直接相关的未提交改动。
- 已列出 THSBigOrder 文件和近期提交。
- 已读取双数据源设计、当前 diff 和数据源关键调用链。
- 已发现截图实际请求代码为 `999999`，首要假设转为通达信内存跟随产生无效代码。
- 已通过本地代理对比正常代码与 `999999`，确认截图直接根因。
- 已确认代理进程和端口正常，排除代理未启动。
- 已核对龙虎代理行为：单页与部分 all-day 请求可正常返回数据。
- 已运行构建：主项目通过，测试项目因构造函数签名变更无法编译。
- 已完成根因层级和最小修复范围整理。
- 已按批准方案重新实现 Longhu direct/proxy、完整分页、THS summary 混合、分源 stale cache 和 ComboBox 切换。
- 已补齐 Tests 构造注入及 Longhu parser/client/provider/UI 回归测试。
- subagent 首轮 review 发现 1 Critical、4 Important、1 Minor；修复后复审无剩余 Critical/Important。
- THSBigOrder 与 THSBigOrder.Tests Release 构建均为 0 warning / 0 error。
- 完整测试仅剩两个既有固定日期涨停夹具失败，与 Longhu 功能无关。
- 已开始把前述调试过程整理为正式复盘，并分析 BigOrder Redis TTL 改造。
- 已核对 `docs/API/ths-l2-api-analysis.md`、`docs/ranktrend-redis-cache/*`、`proxy-server/helpers/proxyCache.js`、`proxy-server/routes/bigOrder.js` 和当前 C# Longhu 客户端。
- 已确认 Redis 方案的核心不能只是分页 TTL：必须让正常流量进入 proxy，并以全天快照增量刷新避免 TTL miss 后再次全量分页。
- 已新增 `2026-07-16-debug-retrospective.md`，记录 `999999`、Longhu 分页、三条线、切源刷新和验证结果。
- 已新增 `big-order-redis-cache-design.md`，推荐“L1 内存 + L2 Redis、全天快照、增量头页、SWR、熔断、proxy 正常入口”。
- 已新增 `big-order-redis-cache-implementation-plan.md`，列出精确影响文件、TDD 用例和验证命令。
- 已纠正既有双数据源设计/计划中的 500 条页大小和对应偏移旧口径，并在 API 分析文档补充真实页大小限制。
- 自审发现并修正两项架构遗漏：
  - `cache.enabled() ? cache : runtimeCache` 不能处理 Redis 运行中断线，方案改为 `LayeredProxyCache`。
  - proxy 成为正常入口后不能继续使用 `ProxyFallback`，方案增加 `ProxyPrimary` 正常传输状态。
- 独立只读审查无 Critical，提出 5 个 Important，已全部处理：
  - 明确当前 proxy 仍是 GET/逐页 DeviceID，POST 合同只在 C# direct 已落地。
  - 增量刷新增加 prepend-only 实测门禁、所有页 Total 校验和历史页轮转审计。
  - 当时记录了 DeviceID snapshot、逻辑快照偏移和 20 秒预算，但正文未充分落地，且 20 秒后来被外部审计证明不足；现已修订为 45 秒。
  - Longhu key 统一为 row `sessionDate` + `latest` 指针，避免周末按自然日冷重建。
  - 增加 L1/L2 字节预算、money allowlist、冷重建队列和等待上限。
- 二次复审提出 3 个 Important，已处理：
  - 拆分 `off/prepend-device-snapshot/prepend-logical` 三种模式，默认 fail-closed `off`。
  - 所有 Longhu 上游请求统一全局并发 1。
  - 全源 breaker 与单 `{stock,money}` 完整性冷却分离。
- 最后复审提出 2 个 Important，已处理：
  - 冷启动 Total 变化失败条件按三种 mode 明确分支，`prepend-logical` 的正常增长不再与通用失败规则冲突。
  - 冷 miss、头刷、历史审计统一进入 running=1/queued=4 的有界调度器。
- 当时的独立复审报告称无剩余 Critical / Important；后续外部对抗性审计证明该结论只覆盖了有限检查面，不能作为当前 design/plan 的最终结论。
- 本地 Markdown 相对链接检查无缺失，目标文档 `git diff --check` 通过。
- 收到外部对抗性审计后重新核验，确认此前“最终无 Critical / Important”的结论不能继续成立：design/plan 正文仍存在 2 个 Critical 和多项合同缺口。
- 已开始把审计结论逐项回写 design、implementation plan、API/双数据源关联文档；本轮仍保持文档-only，不修改源码。
- 已完成外部审计修订：
  - 冷 miss 时序收敛为 8 秒排队、45 秒重建、Longhu 专用 60 秒客户端，并要求 deadline 中止上游请求。
  - 全局并发固定 1；全源 breaker 与单 key 完整性冷却分离；显式增量模式默认 `off`。
  - envelope 增加 `sessionDate`，technical stale 与 UI stale 分离，`latest` 指针前移到冷启动读路径。
  - 历史审计改为普通请求搭便车；旧 money 合同不收紧；补空 key、盘前、字节预算、部署顺序和文档同步。
- 文档验证通过：8 个目标文件相对链接无缺失；14 项关键合同扫描通过；行尾空白/占位词扫描通过；`git diff --check` 无输出。

## 2026-07-17

- 收到语音增量播报补充需求：Redis 缓存返回全天快照时，WinForms 只播报本次新增的大单，且不固定截断为最近两条。
- 已确认不能只删除调用方的两条限制：`VoiceService` 当前每次播报会取消上一条，多条新增必须采用单批次合并播报或显式队列策略。
- 已完成语音调用链核对：当前只检查最新 10 条、首条命中立即返回、每次播报取消前一条。
- 已把完整语音合同写入 Redis design/implementation plan，并同步双数据源 design/plan：
  - 完整列表先做 scope 增量识别，再应用当前筛选。
  - 指纹按历史最大出现次数处理合法重复。
  - 首次/切股/切源/跨日只建基线，语音关闭仍推进基线。
  - 同轮全部有效新信号合为一个批次顺序播报，不限制条数。
- 提交前 C# 测试新鲜结果：62 项中 60 项通过，只剩此前已记录的两个固定日期 limit-up fixture 失败；Longhu、三线图、切源和刷新回归均通过。
- 首次独立输出构建误用了新的 `BaseIntermediateOutputPath`，导致 net48 引用程序集解析失败；改为保留现有 obj、只重定向 `OutputPath` 后重新验证。
- 只重定向 `OutputPath` 的 THSBigOrder Release 构建通过：0 warning / 0 error，输出到 `tools/THSBigOrder/bin/ReleaseVerify/`。
- subagent 只读复核语音合同：无 Critical，提出 4 Important/2 Minor，已全部采纳：
  - THS 补权威 `sessionDate` 和 null fail-closed 语义。
  - 重新开启语音增加首份 accepted snapshot barrier。
  - 特殊 marker 筛选覆盖默认播报优先级。
  - 增加可注入 `ISpeechQueue`，验证 FIFO/CancelPending/Dispose。
  - 固定 marker→Observe→Filter→Map→Batch 顺序。
  - tracker 对 `sessionDate.Date` 归一化。
- subagent 二次复审追加 2 Important，已处理：
  - THS 只有时分秒的 order 强制规范化为权威 `sessionDate.Date + timeOfDay`，避免跨午夜指纹漂移。
  - re-enable barrier 只有可信日期完整快照成功建基线后才清除，null/失败/迟到响应均保留。
- subagent 最终复审无剩余 Critical / Important。
- 已提交当前 Longhu/图表/切源源码与测试：`c709101 feat(thsbigorder): add Longhu big-order source`。
- `proxy-server/helpers/proxyCache.js` 属于无关的热榜 TTL/格式化改动，本轮未纳入提交；DLL、EXE config、窗口设置和 `.claude/worktrees/` 同样排除。

## 2026-07-17 Redis / 增量语音实施

- proxy 新增 L1/L2 `LayeredProxyCache`、BigOrder 容量上限、Longhu 全局串行有界调度器和结构化 `/api/big-order/longhu/all-day`。
- Longhu 上游统一使用 POST form、`st=200`、同轮 DeviceID；完整快照校验 `Total`、短页、超量和混合交易日后才写缓存。
- 默认增量模式保持 `off`，300 秒内不重复 full rebuild；`prepend-device-snapshot` 支持头部 delta + 连续重叠校验。`prepend-logical` 在逻辑偏移合同未完整落地前显式 fail-closed 为 `off`。
- canonical 空结果使用短 TTL empty key，不覆盖最近非空 `latest`；网络/403/429/5xx 连续失败触发 60 秒全源 breaker，45 秒主动预算中止不计入全源失败。
- THS detail 接入 L1/L2 并返回权威 `sessionDate`；WinForms 使用 proxy-primary，Longhu 聚合客户端 60 秒，普通行情客户端保持 15 秒。
- WinForms 增加订单出现次数 tracker、可信交易日 scope、re-enable barrier 和单批次 FIFO 语音；首份/切股/切源只建基线。
- 修复两个固定日期涨停夹具：向 `ThsLimitUpSourceClient` 注入日期时钟，生产默认系统日期，测试固定日期。
- 修复腾讯分时 stale 测试的硬编码 6 秒，使其跟随正式 TTL。
- code review 修复 technical stale/UI stale、full rebuild 冷却、混合日期、正常代理状态颜色、direct 诊断 User-Agent 和本地 last-good 5 分钟上限。

## 2026-07-17 提交 6982d0d 的 code review 修复轮

- 针对提交 `6982d0d` 的 code review 发现（3 High / 7 Medium / 若干 Low）完成修复：
  - H1 时段 TTL：新增 `longhuCacheSlot`，落地设计 §7 时段表（交易 10/300、盘前/午间/收盘后半小时 60/900、闭市与周末 1800/604800）；off 模式完整重建冷却分时段（交易 300 秒、闭市 6 小时），消除收盘后每 5 分钟重复全量分页。
  - H2 sessionDate 容错：个别坏行只跳过日期提取，全部行无日期才拒写，与 C# 解析器"跳过个别坏行"合同一致；混合日期仍拒绝。
  - H3 loadPage 完整性：公共分页聚合以 `Total` 为完整性标准，短页低于目标即判截断，分页中 `Total` 变化即失败；不再把短页当末页静默截断。
  - M1 增量节流：头部刷新恢复页间 delayMs、20 秒总预算；`delta+overlap` 超过 10 页直接转受冷却保护的完整重建。
  - M2 历史页审计：搭增量刷新便车，每 5 分钟轮转核对一个历史页，漂移时标 stale 并触发受冷却保护的完整重建；不新增定时器。
  - M4 页缓存：`big-order:longhu:page:v2` 10s/120s 页缓存落地（L1 128 entries/32MB/1MB，L2 复用 Redis）；sessionDate 用 `latest` 指针解析，指针缺失时退化为上海自然日。
  - M5 日志：完整重建、后台刷新失败、熔断开启、历史页漂移均有日志；logger 可注入，测试静默。
  - M7 last-good：`BigOrderLastGoodMaxAge` 分时段（交易 5 分钟、收盘后/周末 12 小时）。
  - L1 `LoadProxyAsync` 先 `EnsureSuccessStatusCode` 再解析；L2 C# `InferThsSessionDate` 兼容 pricechange 对象/数组两种行形态；L3 服务引用 `PROXY_CACHE_TTLS` 常量。
- 按修订版设计回退两处与设计冲突的初版修复：不新增旧路由 money allowlist（设计 §5.2/验收 21）；uiStale 交易阈值保持 30 秒（设计 §5.1/验收 20）。
- 验证：proxy `node --test` 93/93；THSBigOrder.Tests 68/68（新增 last-good 分时段测试）；两个 C# 项目 Release 构建 0 警告 0 错误；`git diff --check` 通过。
- 已知未实现项已于后续审计收口轮全部补齐，详见下一节；增量模式仍默认 `off`，只有显式配置和实测证据才启用。
- 已知观察项：THS detail 交易时段 fresh TTL(30s) 等于 uiStale 阈值(30s)，SWR stale 命中会有约每 36 秒一次的短暂"数据陈旧"提示；如需消除可将 THS TTL 降为 15 秒（需同步设计 §7 表），Longhu 主链路(TTL 10s)不受影响。
- 待人工盘中验收（plan Task 8）：冷加载页数、10 秒内重复刷新 0 上游、新单只抓头页、快速切源无迟到覆盖、money≠0 的 `Total` 语义实测。

## 2026-07-17 运行环境接通与本地永久归档

- 盘中验收发现两条要求实际未生效，根因是运行环境而非代码：
  - 白天运行的 proxy 是 8:51 启动的修复前版本（staleTtl 300 秒，无 7 天保留代码）。
  - `.env.local` 缺 `PROXY_REDIS_URL`，本机 Redis（127.0.0.1:6379）空库，L2 从未启用——重演 Collector 复盘教训 #6（环境变量与代码脱节）。
- 已修复并当场实测：`.env.local` 增加 `PROXY_REDIS_URL=redis://127.0.0.1:6379`，重启 proxy 后 600519 冷重建 7.8 秒完成 7127 行，Redis `all-day:v2` 与 `latest:v1` key TTL 实测 7.00 天；二次请求 0 上游、收盘后档 TTL 1800s 生效。用户随后清理了 `.env.local` 中已弃用的坚果云配置。
- 新需求（用户 2026-07-17 提出）：把大单全天快照作为数据资产永久保存在本地。方案 A"proxy 写通式归档"已实施：
  - 新增 `proxy-server/services/bigOrderArchive.js`：快照写缓存同一时刻异步归档 `proxy-server/data/big-order/{sessionDate}/{stock}.money{money}.json.gz`，临时文件+rename 原子覆盖，失败只告警；无守护进程、无定时任务、无新门禁。
  - `longhuBigOrderCache` 在完整重建和增量合并成功后触发归档；空结果与无 sessionDate 不归档。
  - 新增 `bigOrderArchive.test.mjs` 6 项测试；`.gitignore` 增加 `proxy-server/data/`。
  - 文档同步：design 新增 §7.1，§13 非目标改为"不建线上/数据库形态历史库，本地文件归档除外"；plan 文件边界与完成度审计表补第 11 项。
- 验证：proxy 全量 `node --test` 113/113 通过。
- 增量门禁探针脚本暂不做；下周一（2026-07-20）用户盘中招呼后再执行实测。

## 2026-07-17 归档回填与收盘后候选池采集

- 用户指出方案 A 两个缺点并确认扩展：① 只归档 exe 查看过的股票；② 冷启动不回填归档。范围决策：采集"当日进入候选池/交易池的股票（一般 ≤5 只）"，收盘后自动触发。
- 已通读 `docs/candidate-pool/` 全部文档确认口径：入池（自动 V5/Fusion 严格合同 + 手动右键）发生在 Dragon Board 前端，数据源为八平台热榜实时投影；候选记录经 proxy 转发到 QuantBoard journal；目前无任何收盘后自动机制；每日入池个位数，与用户"≤5 只"一致。
- 缺点 ② 已实现（设计 §7.1 补充）：`loadAllDay` 冷 miss 先读本地归档回填 L1/L2（stale 身份）并恢复 `latest` 指针；周末回填 0 上游有测试锁定；归档缺失照旧冷重建。
- 缺点 ① 已实现（设计 §7.2）：`bigOrderCollector.js` + `POST /api/big-order/longhu/collect-list`（登记，去重/校验/单日上限 20、落盘防重启丢失）+ `POST /api/big-order/longhu/collect`（手动兜底）+ 主进程内 60 秒 tick worker（工作日 15:10~16:00 每天一轮，`unref()` 不阻塞退出，参照 eventRadar 先例）。无质量门禁，单只失败记日志跳过。
- 修复一次自伤：路由测试曾经由默认 archiver 读写真实 `data/big-order/` 造成互相污染——archiver/collector 改为可注入，`thsBigOrder.test.mjs` 8 处 app 构造注入 noop，删除被污染的 002297 归档文件（后由真实采集重新生成）。
- server.js 正式路由清单与 openapi.js 已补两个 POST 端点；设计 §13 非目标同步修订（本地归档+主进程内采集 worker 为明确例外，全市场采集仍禁止）。
- 验证：proxy 全量 118/118；重启 proxy 后端到端实测——000001 归档回填冷 miss 立即返回（0 上游等待）；collect-list 去重登记；collect 2/2 成功；`data/big-order/2026-07-17/` 已有 000001/002297/600519 三份当日终稿，`collect-list/2026-07-17.json` 落盘。
- 遗留接线（待用户确认后另行实施，涉及 `src/services/candidate/**`）：前端在自动/手动入池时调用 `POST /api/big-order/longhu/collect-list` 完成全自动闭环；接线前可手动登记。

## 2026-07-17 design / plan 审计收口

- 修复交易时段写入的全天快照只物理保留 300 秒的问题：fresh TTL 仍按时段变化，全天快照 L1/L2 统一保留 7 天，使周末和节假日能通过 `latest` 读取上一交易日 stale；周末不触发重建，工作日旧 session 最多每 60 秒探测一次头页，空头页不覆盖 `latest`。
- 冷启动固定快照模式在同一 45 秒 `AbortController` 预算内最多执行 3 次完整尝试，每次使用新的 DeviceID；`prepend-logical` 已实现冷启动和多页增量的逻辑偏移，覆盖 Total 增长、下降、单页超过 2 次变化和预算中止。
- 增量头页及后续页统一按 `Total/index/st=200` 校验完整页，短头页不再被重叠校验误接受；连续 2 次增量完整性失败或交易时段缓存年龄超过 60 秒时触发受 60 秒冷却保护的完整重建。
- 风控拆为两层：403/429/网络/5xx 连续失败触发全源 60 秒 breaker；短页、Total、日期和重叠完整性失败按 `{stock,money}` 计数，连续 3 次只冷却该 key 60 秒。服务自身 45 秒预算中止只记单 key，不污染全源 breaker。
- 历史页审计从头刷任务内联调用改为独立 `audit` 队列项，优先级低于 cold/head；重建后等待满 5 分钟才轮转核对，不在冷建完成后立即追加上游请求。
- Redis 写入新增 per-value 字节上限：all-day 8MB、page 1MB；超限仅跳过对应缓存层写入，不影响本次响应。`dragonMeta.refresh` 补齐 `inProgress/pagesFetched/newRows/total/elapsedMs/incrementFailureCount`，路由 TTL 改为当前时段动态值。
- WinForms last-good 改为权威 `sessionDate` 匹配：只有同股、同源、同交易日且未超时才复用；日期缺失不保存为跨请求兜底。新增跨日拒绝测试。
- 增量语音回归补齐同日不同 `DateTime.Kind`、切源/跨日 scope、筛选变化、特殊 marker 覆盖、marker 重算、日期缺失 barrier、关闭期间基线推进和 re-enable 首帧屏障。
- 自动验证：proxy `npm test` 106/106；C# runner 全部通过；THSBigOrder 独立 Release 验证构建 0 warning / 0 error。人工盘中观察项仍保留为部署验收，不作为代码完成度的替代证据。
