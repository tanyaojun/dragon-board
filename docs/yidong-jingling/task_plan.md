# 异动精灵 V1 任务计划

## 目标

实现一个独立 Windows GUI 工具“异动精灵”，通过通达信 `.blk` 股票池和 L1 行情监控盘中异动，并使用本地语音播报，不启动 Dragon Board 前端，不依赖选股通 API。

## 当前阶段

Phase 6：V1 MVP 已实现，进入体验补齐和真实行情联调。

## 成功标准

1. GUI 可选择 `T0002\blocknew` 目录，列出并加载一个或多个 `.blk` 文件。
2. 能把 `.blk` 中的 7 位通达信代码解析为标准 6 位股票代码，并过滤无效项。
3. GUI 不启动 Dragon Board 前端、不调用选股通 API。
4. 能连接或托管启动本地通达信 L1 行情桥，持续接收指定股票池行情。
5. V1 覆盖 L1 稳定可做的全部核心异动：封板、开板、即将开板、逼近涨跌停、急拉、跳水、翻红翻绿、日内新高新低、成交额跨档、成交增量加速、盘口买卖压、封单变化。
6. 语音播报支持启停、语速、音量、冷却、批量合并和测试播报。
7. 所有异动规则都有可复现单元测试，GUI 至少通过构建和手工冒烟。

## 非目标

- 不实现或宣称真 L2 十档、逐笔委托、官方选股通事件。
- 即将打开涨停/跌停按用户指定口径把 L1 买一/卖一视为盘口封单数据使用，文档和界面不宣称真 L2 十档或逐笔委托。
- 不在第一版加入回测、候选池、QuantBoard、主看板面板或大型平台能力。
- 不改 `python-bridge/main.py` 默认生产行为来尝试高风险 L2 探针。

## 目录建议

```text
tools/YiDongJingLing/
├── YiDongJingLing.csproj
├── Program.cs
├── MainForm.cs
├── Blocks/
│   ├── BlockFileScanner.cs
│   └── BlockFileParser.cs
├── MarketData/
│   ├── TdxBridgeClient.cs
│   ├── QuoteSnapshot.cs
│   └── QuoteStateStore.cs
├── Events/
│   ├── L1EventEngine.cs
│   ├── L1EventRules.cs
│   ├── EventDeduper.cs
│   └── EventRecord.cs
├── Speech/
│   └── SpeechAnnouncer.cs
├── Settings/
│   └── SettingsStore.cs
└── Diagnostics/
    └── HealthCheck.cs

tools/YiDongJingLing.Tests/
├── BlockFileParserTests.cs
├── L1EventEngineTests.cs
└── EventDeduperTests.cs
```

## Phase 1：项目骨架和 GUI 外壳

- [x] 新建 `tools/YiDongJingLing` WinForms 项目。
- [x] 新建 `tools/YiDongJingLing.Tests` 测试项目。
- [x] 实现主窗口基础布局：异动列表、监控板块、设置、诊断日志。
- [x] 保存窗口位置、透明度、语音设置和规则开关；置顶功能已在后续版本取消。
- **验证：** `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj`
- **状态：** complete

## Phase 2：`.blk` 监控池

- [x] 扫描用户选择的 `T0002\blocknew` 目录。
- [x] 列出 `.blk` 文件名、路径、大小、股票数、最后修改时间。
- [x] 支持添加、删除、保存监控文件列表。
- [x] 解析一行一个 7 位代码，归一为 6 位代码。
- [x] 过滤空文件、重复代码、明显非 A 股代码，并在 UI 显示过滤原因。
- [x] 监听已选 `.blk` 文件变化，变更后提示或自动重载。
- **验证：** `YiDongJingLing.Tests` 覆盖 7 位前缀、重复、非法行、指数过滤、混合市场。
- **状态：** complete

## Phase 3：L1 行情接入

- [x] 实现 `TdxBridgeClient`，连接 `ws://127.0.0.1:8765/ws/quotes`。
- [x] 上行发送 `{ "type": "set_hot_pool", "codes": [...] }`。
- [x] 处理 `full_state`、`quote_patch`、`depth_patch`、`heartbeat`。
- [ ] `ticks_batch` 暂未消费，因 V1 不承诺逐笔口径。
- [x] 行情桥未运行时，显示诊断并允许一键启动 `python-bridge/main.py`。
- [x] 缓存最新价、涨跌幅、成交量、成交额、最高、最低、五档盘口。
- [x] 对行情延迟、断线、空数据给出状态提示。
- **验证：** 用 mock WebSocket 或 fake client 注入报价，验证状态更新和断线重连。
- **状态：** partial

## Phase 4：L1 异动规则引擎

- [x] 实现涨跌停价计算：普通 10%、ST 5%、创业板/科创板 20%、北交所 30%，无法确认时用涨幅阈值兜底。
- [x] 封涨停板、打开涨停板、逼近涨停。
- [x] 封跌停板、打开跌停板、逼近跌停。
- [x] 即将打开涨停：上一帧已封涨停，本帧仍在涨停价，买一封单金额在 5-10 秒内明显下降或低于阈值。
- [x] 即将打开跌停：上一帧已封跌停，本帧仍在跌停价，卖一封单金额在 5-10 秒内明显下降或低于阈值。
- [x] 涨停/跌停封单额增加、封单额下降、封单变弱。
- [x] 大幅拉升，支持跨 3%、5%、7%、9% 档。
- [x] 快速拉升和快速跳水，基于 30 秒、60 秒本地滑窗。
- [x] 翻红、翻绿。
- [x] 创日内新高、创日内新低。
- [x] 成交额跨档，默认 1 亿、3 亿、5 亿、10 亿。
- [x] 成交增量加速，基于单位时间成交量或成交额增量。
- [x] 五档买压增强、卖压增强、买卖价差异常。
- **验证：** `L1EventEngineTests` 为每种规则构造前后两帧行情，断言触发和不触发。
- **状态：** complete

## Phase 5：去重、优先级和播报

- [x] 同一股票同一事件类型设置冷却时间。
- [x] 同一股票同一批次只保留最高优先级事件。
- [x] 批量事件合并播报，默认最多读 3 条，重要事件可插队。
- [x] GUI 复用 `tools/VoiceWorker` 播报队列，不再直接依赖 `System.Speech`。
- [x] 支持 VoiceWorker 本地语音选择、语速、音量、停止当前播报、测试播报。
- [x] 支持导出异动记录到 txt。
- **验证：** `EventDeduperTests` 覆盖冷却、优先级、批量合并；手工验证语音测试。
- **状态：** complete

## Phase 6：GUI 体验补齐

- [x] 异动列表展示时间、类型、代码、名称、涨幅、价格、成交额、触发原因。
- [x] 规则设置页提供全选、反选、清空、保存。
- [x] 监控板块页显示选中 `.blk` 的股票数和异常行数量。
- [x] 诊断区显示行情桥状态、订阅数量、最近行情时间、语音状态。
- [ ] 支持最小化到托盘。
- [x] 支持透明度；置顶功能因设置窗遮挡风险已取消。
- [x] 联动页先提供复制代码、尝试打开通达信目录；具体通达信定位方式需实测后确认。
- **验证：** 手工打开 GUI，切换各页，加载真实 `D:\APP_SOFT\TDX\T0002\blocknew`。
- **状态：** partial

## Phase 7：验收和打包

- [x] 运行全部 .NET 测试。
- [x] 构建 GUI。
- [ ] 用真实 `.blk` 文件进行手工冒烟。
- [ ] 验证行情桥离线、行情桥在线、语音不可用、空板块、重复股票等场景。
- [ ] 形成第一版使用说明。
- [ ] 可选：发布 `win-x64` self-contained 包。
- **验证：**

```powershell
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
```

- **状态：** partial

## 第一版默认规则参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 行情桥地址 | `ws://127.0.0.1:8765/ws/quotes` | 可配置。 |
| 逼近涨停阈值 | 距涨停 1.0% 内 | 10% 票约等于涨幅 9% 以上。 |
| 逼近跌停阈值 | 距跌停 1.0% 内 | 与涨停对称。 |
| 即将打开涨停/跌停窗口 | 10 秒 | 直接使用 L1 买一/卖一封单变化。 |
| 即将开板封单衰减 | 降至近 10 秒高点或上一帧的 35% 以下 | 用于“即将打开涨停/跌停”预警。 |
| 即将开板最小封单额 | 500 万 | 当前买一/卖一封单金额低于该值时提示；五档量按通达信常见“手”换算为股。 |
| 即将开板最小封单量 | 1 万手 | 当前买一/卖一量低于该值时提示。 |
| 快速拉升窗口 | 30 秒、60 秒 | 任一窗口达标触发。 |
| 快速拉升阈值 | 30 秒 2%、60 秒 3% | 后续可按市场微调。 |
| 快速跳水阈值 | 30 秒 -2%、60 秒 -3% | 后续可按市场微调。 |
| 大幅拉升档位 | 3%、5%、7%、9% | 跨档触发一次。 |
| 成交额档位 | 1 亿、3 亿、5 亿、10 亿 | 跨档触发一次。 |
| 同股同类冷却 | 180 秒 | 封板、开板等关键事件可单独设置。 |
| 批量播报上限 | 3 条 | 超出时播报总数和前三条。 |
| 全市监控 | 默认关闭 | 防止第一版对行情桥造成过大压力。 |

## 关键权衡

| 方案 | 优点 | 缺点 | V1 选择 |
|------|------|------|---------|
| 复用 `python-bridge` | 已验证 L1 可用，开发快，字段与主项目一致 | 依赖 Python/mootdx 或需要托管启动子进程 | 选择 |
| 纯 .NET 重写 TDX 协议 | 单 exe 更干净 | 协议风险高，第一版周期明显变长 | 暂不选 |
| 继续用主前端异动雷达 | 现有功能多 | 依赖 Dragon Board 和选股通 API，违背目标 | 不选 |
| 直接读通达信客户端缓存 | 可能更贴近本地客户端 | 文件结构和实时性不稳定 | 不作为主链 |

## 错误记录

| 错误 | 处理 |
|------|------|
| 用户提到 `T002`，本机真实目录为 `T0002` | 文档统一使用 `T0002\blocknew`，实现时允许用户手动选择路径。 |

## 交付判断

V1 交付时，只要用户可以打开一个 GUI、选择通达信板块文件、看到真实 L1 行情驱动的异动列表，并听到本地语音播报，就认为第一版核心目标达成。盘口弱信号、新股开板和全市扫描可以存在，但必须清晰标记能力边界。

---

# 异动精灵 V2 任务计划

## V2 目标

把 V1 从“功能跑通版”升级为“实盘盯盘可用版”：提升连接稳定性、语音噪音控制、盘中操作效率，并将窗体视觉改为证券终端式金融风格。

## V2 成功标准

1. 打开软件后自动进入可盯盘状态，行情桥断线后可自动重连或明确提示。
2. 主窗体采用金融终端风格：高密度、低眩光、红涨绿跌、状态清晰、表格可快速扫读。
3. 异动列表最多保留 100 条，尾部显示当前显示记录数和今日累计捕获数。
4. 语音播报可以按强弱等级控制，避免弱信号频繁打扰。
5. 支持最小化到托盘，关闭/退出语义清晰。
6. 核心状态可见：最近行情时间、监控数量、行情桥状态、交易时段状态、语音状态。
7. 发布包仍保持独立 Windows GUI，不启动 Dragon Board 前端，不依赖选股通 API。

## V2 非目标

- 不承诺真 L2 十档或逐笔委托。
- 不在 V2 中引入大型回测、策略平台或 QuantBoard 主链。
- 不做花哨营销式界面；金融风格以盯盘效率为准。

## V2 视觉方向：金融终端风格

| 项目 | 方向 |
|------|------|
| 整体气质 | 证券终端、低眩光、高信息密度 |
| 主背景 | 深色或深灰蓝黑，避免纯黑刺眼 |
| 涨跌色 | A 股红涨绿跌，弱信号降低饱和度 |
| 表格 | 紧凑行高、细网格线、数字右对齐、表头固定感强 |
| 状态栏 | 显示监控数、记录数、累计捕获、行情桥、最近行情、语音、交易时段 |
| 按钮 | 工具栏式矩形按钮，主操作明确，少圆角、少阴影 |
| 字体 | 使用系统中文字体，数字列优先等宽或清晰右对齐 |

## V2 Phase 1：金融风格主窗体

- [x] 建立 `MainForm` 金融风格色板和统一控件样式方法。
- [x] 顶部工具栏改为证券终端式深色工具栏，突出当前连接/交易状态。
- [x] 异动列表改为深色表格、红绿涨跌、强弱事件行色。
- [x] 页尾状态栏增加：显示记录数、今日累计捕获、监控数、最近行情时间。
- [x] 保持当前列顺序：时间、异动类型、股票代码、股票名称、涨跌幅、最新价、成交量、成交额、异动详情。
- **验证：** `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`，手工启动检查表头、列宽、尾部状态不重叠。
- **状态：** complete

## V2 Phase 2：稳定连接和状态可见

- [x] 行情桥断开后自动重连，设置合理退避，避免刷屏。
- [x] 显示最近行情时间和行情延迟。
- [x] 行情超过阈值未更新时在状态栏提示。
- [x] 明确显示连续竞价/午休/非交易时段。
- **验证：** 模拟桥断开、重启、午休时间行情，确认不会误报。
- **状态：** complete

## V2 Phase 3：语音噪音控制

- [x] 为事件类型配置强/中/弱等级。
- [x] 增加“只播强信号/播报全部/静音”模式。
- [x] 弱盘口信号默认只入列表不播报。
- [x] 页尾或顶部显示当前语音模式。
- **验证：** 单元测试覆盖语音过滤；手工测试模式切换。
- **状态：** complete

## V2 Phase 4：托盘和盘中操作效率

- [x] 支持最小化到托盘。
- [x] 托盘菜单提供显示窗口、静音/恢复、退出。
- [x] 双击异动记录复制股票代码。
- [x] 导出记录改进为包含表头的 CSV 或制表符文本。
- **验证：** 手工验证托盘、恢复窗口、退出释放行情桥。
- **状态：** complete

## V2 Phase 5：股票池来源和设置稳定性

- [x] 设置页取消窗口置顶入口，旧配置中的 `TopMost` 启动和保存时强制忽略。
- [x] “监控板块”页增加股票池来源下拉：`TDX自选股` / `八平台热榜`。
- [x] 八平台热榜来源复用本地 `proxy-server` 八个平台接口，只合并 A 股 6 位代码后订阅行情桥。
- [x] 八平台热榜来源下自动尝试启动本地代理服务，不启动 Dragon Board 前端。
- **验证：** `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`。
- **状态：** complete

## V2 Phase 6：飞书消息同步

- [x] 设置页增加“同步消息”勾选框，保存到 `AppSettings.SyncMessages`。
- [x] 开启后，桌面版捕获到已启用且通过去重的异动时，复用本地代理 `/api/notifications/event-radar/events` 同步到飞书聊天机器人。
- [x] 复用网页版异动雷达的代理侧飞书配置、签名、冷却和批量发送逻辑，不在桌面端重复实现飞书 webhook 签名。
- [x] 代理未运行时自动尝试启动 `proxy-server`；发送失败只写诊断日志，不影响行情监控和语音播报。
- **验证：** `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`。
- **状态：** complete

## V2 Phase 7：TDX 雷达设置迁移

- [x] 设置页增加“异动参数”区域，支持配置涨幅突破、跌幅突破、5 分钟涨跌幅、成交额门限、挂单额门限、开盘跳空幅度、长阳/长阴幅度。
- [x] 基于 TDX L1 行情桥现有字段迁移：大幅跳水、5 分钟快涨快跌、出现大买/大卖挂盘、低开长阳、高开长阴、成交额门限。
- [x] 新增事件进入异动类型勾选列表、去重优先级和语音策略。
- [x] 不接入不稳定逐笔口径，不迁移自由流通股占比类规则。
- **验证：** `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`。
- **状态：** complete

## V2 Phase 8：验收和发布

- [x] 更新 `docs/yidong-jingling/progress.md`。
- [x] 更新使用说明。
- [x] 运行测试、Release 构建、发布 win-x64 单文件 exe。
- [x] 启动烟测，确认 `startup-error.log` 未更新。
- **验证：**

```powershell
dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj
dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release
dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o tools\YiDongJingLing\publish\win-x64
```

- **状态：** complete

---

# 异动精灵 V3 任务计划：开盘竞价弱转强

## V3 目标

在不接入 QMT L2、不恢复 TDX 真十档探针的前提下，使用当前 `mootdx + python-bridge` 的 L1 行情链路，于早盘 `09:25` 记录集合竞价最后可见价，并在 `09:30-09:35` 快速识别“竞价弱转强”股票。

规则口径校正：`002552 宝鼎科技` 只是“竞价尾价弱、开盘跳空上移”的子形态。V3 不把弱转强写死成单一公式，而是使用 `variant + score + factors + riskFlags` 的模式族合同。

技术校正：网页板 `opening_weak_to_strong` 第一版主检测源必须使用 `python-bridge` WebSocket 实时行情，不使用选股通/同花顺 HTTP 异动事件 feed。选股通/同花顺 feed 只保留为普通盘中异动辅助线索。

子 Agent 交叉评审门禁：实施前必须补齐强制采样、跨端语音仲裁、统一 fixture、dry-run、可观测字段和离线矩阵。

V3 第一版必须同时覆盖三个实现点：

1. 网页板异动雷达：TypeScript 检测，进入现有异动雷达列表和本地语音链路。
2. 桌面版异动精灵：纯 C# 独立检测，`YiDongJingLing.exe` 主表高亮并语音提醒。
3. Dragon Board 主界面：行情主表对命中股票显示醒目信号标识。

详细方案见：[opening-weak-to-strong-plan.md](opening-weak-to-strong-plan.md)。
Superpowers 设计规格见：[../superpowers/specs/2026-05-22-opening-weak-to-strong-design.md](../superpowers/specs/2026-05-22-opening-weak-to-strong-design.md)。

## V3 成功标准

1. `09:24:50-09:25:10` 网页板和桌面版都能对当前监控池锁定 `auctionFinalPrice`。
2. `09:30:00-09:35:00` 两端都能计算 `auctionPct`、`firstWindowPct` 和 `jumpPctPoint`。
3. 满足条件时触发 `竞价弱转强` 事件，事件包含 `variant`、`score`、`confidence`、`factors`、`riskFlags`、`baselineQuality`、`ruleVersion`、`configHash`，`confidence >= strong` 时按 proxy `voiceOwner` 仲裁后播报。
4. 异动精灵主表格高亮显示该事件，详情包含 `09:25` 价、`09:30` 价、跳空百分点、成交额和距涨停。
5. 网页板异动雷达显示同一事件，复用现有去重、列表和语音服务。
6. Dragon Board 行情主界面展示同一信号徽标或短时行高亮。
7. 本地代理缓存今日信号，并按 `tradingDate + code + signalType` 去重，避免网页板和桌面版重复刷屏。
8. 缺少 `09:25` 基线、非开盘窗口、低成交额和重复触发都不会误报。

## V3 非目标

- 不接入 QMT L2。
- 不宣称真 L2 十档、逐笔委托、撤单队列。
- 不做默认全市场高频扫描。
- 不把盘后分钟线当作 `09:25` 竞价历史数据来源。
- 不把选股通/同花顺 HTTP 事件接口当作竞价弱转强主数据源。
- 不把信号写入 QuantBoard 正式数据库；第一版只做本地当日缓存。
- 不把 `python-bridge` 改成策略引擎；但允许新增强制采样快照、`capturedAt/bridgeTs` 等行情元数据。

## V3 Phase 1：共享口径和事件合同

- [x] 固化 `signalType = opening_weak_to_strong`、显示名“竞价弱转强”和 `dedupeKey = tradingDate + code + signalType`。
- [x] 明确共享字段：`auctionFinalPrice`、`auctionPct`、`officialOpen`、`officialOpenPct`、`firstWindowPrice`、`firstWindowPct`、`jumpPctPoint`、`amount`、`amountDelta`、`limitDistancePct`、`triggerAt`、`source`、`variant`、`score`、`confidence`、`factors`、`riskFlags`、`baselineQuality`、`capturedAt/bridgeTs`、`ruleVersion`、`dryRun`。
- [x] 明确单位：`*Pct` / `*PctPoint` 为百分数点，金额为元，成交量为股。
- [x] 固化模式族：`auction_gap_reversal`、`low_open_red_reversal`、`strong_open_board_attempt`；`previous_day_divergence_repair` 和 `auction_late_lift` 先作为增强因子或后续扩展。
- [x] 收紧 `strong_open_board_attempt`：必须有弱转强前置条件；无前置条件只能作为普通开盘冲板观察，不强播。
- [x] 固化硬门槛、评分模型和强信号升级规则，避免只用单个 `jumpPctPoint` 阈值判断全部形态。
- [x] 为 TS 和 C# 准备同一组样例测试数据，包含 `002552` 命中样例、低开翻红样例、冲板抢筹样例、缺少基线、普通冲板和 `09:35` 后不触发。
- [x] 新增 `docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json`，TS/C# 测试共同读取。
- **验证：** `OpeningWeakToStrongDetector.test.ts`；`YiDongJingLing.Tests` 共享 fixture 测试。
- **状态：** complete

## V3 Phase 2：桌面版纯 C# 检测和语音

- [x] 在 C# 检测器中实现开盘竞价采样窗口和弱转强检测窗口。
- [x] 新增 `OpeningAuctionStateStore` 保存当日 `09:25` 基线。
- [x] 新增 `OpeningWeakToStrongDetector`，只负责弱转强检测。
- [x] 新增桌面 opening signal 上报路径，不绑定飞书同步开关。
- [x] 增加 `L1EventType.OpeningWeakToStrong`、去重优先级和强信号语音策略。
- [x] `L1EventEngine.Prime` 在 `09:24:50-09:25:10` 采样竞价基线。
- [x] `09:30-09:35` 把检测结果并入现有事件链路。
- [x] 设置页增加“竞价弱转强”事件开关。
- [ ] 设置页或状态栏支持 dry-run 演练模式。
- [x] 主表格和摘要栏突出显示“竞价弱转强”。
- **验证：** `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`；`dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`。
- **状态：** partial

## V3 Phase 2A：python-bridge 强制采样元数据

- [x] 在开盘窗口提供强制 `quote_patch`，确保价格不变也能证明每只订阅股票被采样。
- [x] quote payload 提供 `capturedAt/bridgeTs`、`elapsedMs`、`requestedCount/receivedCount`、`slowBatches/truncatedBatches`。
- [x] 避免把 `last_close` fallback 当成有效当前价，新增 `lastPriceSource`。
- [x] 不在 bridge 中计算 `opening_weak_to_strong`，只提供行情和采样质量。
- **验证：** `python -m py_compile python-bridge/main.py`；真实 `09:24:50-09:25:10` 覆盖率仍需早盘实盘确认。
- **状态：** partial

## V3 Phase 3：网页板异动雷达检测

- [x] 在 `src/services/hotlist/**` 增加网页端 `OpeningAuctionStateStore` 和 `OpeningWeakToStrongDetector`。
- [x] 在 `src/services/hotlist/**` 增加 realtime buffer，把 opening realtime 事件合并后再进入面板状态。
- [x] 监听 `webSocketService` 的 `FULL_STATE` / `QUOTE_PATCH`，并支持开盘强制采样元数据，在浏览器内维护 `09:25` 基线和 `09:30-09:35` 检测窗口。
- [x] 明确 `opening_weak_to_strong` 不从 `XuangubaoAbnormalEventFeed` / `ThsLimitUpEventFeed` 读取检测输入；两者只保留为普通异动事件源。
- [x] 网页端只消费现有 WebSocket 订阅池，不直接抢占 `webSocketService.setHotPool`。
- [x] 检测器直接消费 WebSocket `QuotePatch`，不从不完整的 DataLayer 投影反推 `open/preClose`。
- [x] 将命中结果转换为现有 `HotStockEvent`，进入 `HotStockEventMonitorService` 列表、去重和 `HotStockEventSpeechService`。
- [x] `HotStockEventMonitorPanel.vue` 对“竞价弱转强”使用高优先级显示。
- [x] `HotStockEventMonitorPanel.vue` 数据源文案从单一“选股通数据源”调整为“实时行情 + 异动事件源”。
- **验证：** `OpeningRealtimeEventBuffer.test.ts`；`OpeningRealtimeEventBridge.test.ts`；`HotStockEventMonitorService.test.ts`；`HotStockEventSpeechService.test.ts`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- **状态：** complete

## V3 Phase 4：本地代理信号缓存

- [x] `proxy-server` 增加 `POST /api/opening-signals` 和 `GET /api/opening-signals/today`。
- [x] 以内存缓存当日信号，重启后可接受丢失，不进入 QuantBoard。
- [x] 按 `tradingDate + code + signalType` 去重，缓存 `canonicalSignal`、`reportsBySource`、`sources`、`firstTriggerAt`、`lastReportedAt`。
- [x] `POST /api/opening-signals` 返回 `accepted/isNew/dedupeAction/voiceOwner/canonicalSignal/sources`。
- [x] 桌面版和网页板触发后都可上报同一信号合同。
- [x] 明确代理不采样行情、不计算 `auctionFinalPrice`，只缓存已生成信号。
- [x] 新 API 接入 `proxy-server/app.js` 和 `proxy-server/openapi.js`。
- **验证：** `node --test __tests__\openingSignals.test.mjs`；`node --test __tests__\docs.test.mjs`。
- **状态：** complete

## V3 Phase 5：Dragon Board 主界面信号

- [x] 前端增加今日 opening signal 读取服务 `OpeningSignalClient`。
- [x] `DataTable.vue` 在股票名称旁展示“竞强”徽标，并支持行级高亮。
- [x] 主表展示不改变现有排序和信息密度，不使用大卡片或弹窗。
- [x] `/api/opening-signals/today` 轮询只用于展示同步，不作为行情轮询或弱转强检测输入。
- **验证：** `DataTable.test.ts`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；`pnpm build`。
- **状态：** complete

## V3 Phase 6：早盘实盘联调和复盘

- [ ] `09:20` 前启动工具并加载 100-300 只候选池。
- [ ] `09:25` 检查网页板和桌面版竞价基线覆盖率。
- [ ] `09:30-09:35` 记录触发延迟、播报、主表高亮和重复情况。
- [ ] 盘后导出命中记录，保留 `09:25` 价、首次上移价、跳空百分点和冲板状态。
- [ ] 第一轮实盘默认 dry-run，按 `09:20/09:24:50/09:25:10/09:29:59/09:30:00/09:35:01` 检查表记录。
- [ ] 验证 bridge 离线、proxy 离线、只开网页、只开桌面、跨日清理和时区边界。
- **验证：** 基线覆盖率大于 95%，有 per-code `capturedAt/bridgeTs`，信号首次满足后 2 秒内展示，网页板和桌面版不重复刷屏/不重复语音。
- **状态：** pending

## V4 Phase 1：竞价量价核心补强

- [x] 共享 fixture 增加 `auction_late_lift`、`price_lift_without_volume`、`volume_without_price_lift`、`auction_late_high_retreated`、`09:15-09:20` 虚高忽略样例。
- [x] Web 端 `OpeningAuctionStateStore` 保存 `09:20:00-09:25:10` 不可撤单阶段样本，并在 `09:25` 基线中附带 `auctionProfile`。
- [x] 桌面端 C# `OpeningAuctionStateStore` 保存同样的量价序列画像，保持 TS/C# 共用 fixture 口径一致。
- [x] `auction_late_lift` 升级为正式 variant：必须价格抬升、`09:24-09:25` 临门抬价、成交额同步放大且未出现高位回落。
- [x] 价格抬升但成交额不动标记 `price_lift_without_volume`，成交额放大但价格压不动标记 `volume_without_price_lift`，高位回落未收回标记 `auction_late_high_retreated`，均降为 `watch`。
- [x] `09:15-09:20` 可撤单阶段样本不参与强依据，避免虚高影响 `auction_late_lift`。
- **验证：** `pnpm exec vitest run src/services/hotlist/__tests__/OpeningWeakToStrongDetector.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBuffer.test.ts src/services/hotlist/__tests__/OpeningRealtimeEventBridge.test.ts src/services/hotlist/__tests__/OpeningSignalClient.test.ts src/services/hotlist/__tests__/HotStockEventMonitorService.test.ts`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；`dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`。
- **状态：** complete
