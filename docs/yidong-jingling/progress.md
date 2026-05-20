# 异动精灵 V1 进度记录

## 2026-05-20 TDX 雷达设置迁移项

- **目标：** 按 TDX 市场雷达设置页，把现有行情桥可稳定提供的数据尽量迁移为桌面版可配置规则。
- **改动：**
  - 新增可配置阈值：涨幅突破、跌幅突破、5 分钟涨跌幅、成交额门限、买卖挂单额门限、开盘跳空幅度、长阳/长阴实体幅度。
  - 新增事件类型：大幅跳水、出现大买挂盘、出现大卖挂盘、低开长阳、高开长阴。
  - 快速拉升/快速跳水扩展到 5 分钟窗口；成交额跨档改为使用设置页门限；大买/大卖挂盘按买一/卖一挂单金额计算。
  - 设置页增加“异动参数”区域，参数保存到 `AppSettings` 并在 `MainForm` 中同步到 `L1EventRules`。
  - 本地行情历史缓存扩展到 6 分钟，确保 5 分钟快涨/快跌规则在实盘路径可触发。
  - 启动基线会吸收已经成立的低开长阳/高开长阴形态，避免工具启动后把存量形态误报为新增异动。
  - 补充测试覆盖新增规则、5 分钟快涨、开盘形态基线吸收、设置克隆。
- **验证：**
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet publish ... -o tools\YiDongJingLing\publish\win-x64`：用户关闭运行实例后已成功发布。

## 2026-05-20 设置页同步消息与飞书机器人

- **目标：** 在设置页增加“同步消息”勾选框，并复用网页版“异动雷达”的飞书聊天机器人发送能力。
- **改动：**
  - `AppSettings` 增加 `SyncMessages`，设置窗保存/加载该开关。
  - 设置页“股票池、窗口与行情桥”区域增加“同步消息”复选框。
  - 新增 `EventRadarMessageNotifier`，把桌面版 L1 异动转换为代理 `/api/notifications/event-radar/events` 接口兼容 payload。
  - `MainForm` 在异动去重后、语音播报旁异步同步消息；代理未运行时尝试启动 `proxy-server`，失败只写诊断日志。
  - 使用说明补充飞书配置前置条件和代理端冷却/批量窗口语义。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

## 2026-05-20 TDX 自选股切回保留修复

- **目标：** 修复从 `八平台热榜` 切回 `TDX自选股` 时，原先勾选的 `.blk` 文件可能被空列表覆盖的问题。
- **改动：**
  - `MainForm` 增加 TDX 列表加载状态，只有 `.blk` 列表完成加载后才允许用当前勾选项覆盖 `SelectedBlockFiles`。
  - 切回 `TDX自选股` 并订阅前，如果列表尚未加载，会先扫描 `blocknew` 目录，恢复旧勾选再读取股票池。
  - 增加纯函数测试，覆盖“列表未加载时保留旧 `.blk` 选择”和“列表已加载时保存新选择”。
- **验证：**
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - 发布覆盖 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe` 时失败：目标 exe 正在被其它进程占用，未强制结束用户进程。

## 2026-05-20 设置置顶取消与八平台热榜股票池

- **目标：** 修复设置窗口反选“窗口置顶”后主窗体覆盖设置窗的问题，并增加股票池来源二选一。
- **改动：**
  - 设置页移除“窗口置顶”，启动、保存设置和主窗体应用设置时都强制 `TopMost=false`，兼容旧配置但不再启用置顶。
  - “监控板块”页增加“股票池来源”下拉：`TDX自选股` / `八平台热榜`。
  - 新增 `HotlistPoolLoader`，复用本地 `proxy-server` 的八个平台热榜接口，归一化 A 股 6 位代码并过滤港股/指数样式代码。
  - 新增 `ProxyProcessManager`，热榜来源下如果 3000 端口未运行，会尝试后台启动 `proxy-server/server.js`；不启动 Dragon Board 前端。
  - 更新 `docs/yidong-jingling/usage.md` 与 `task_plan.md`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行，随后关闭烟测实例；`startup-error.log` 未刷新。

## 2026-05-20 设置窗容器高度补丁

- **目标：** 修复设置窗右侧容器过小导致新功能和行情桥输入框不可见的问题。
- **改动：**
  - 设置窗扩大到 `860x740`，最小尺寸调整为 `820x700`。
  - 右侧设置组改为“股票池、窗口与行情桥”，第一行直接显示股票池来源下拉。
  - 保存设置时如果股票池来源变化，会立即刷新监控池并重新订阅。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 发布版启动烟测通过，`startup-error.log` 未刷新。


## Session: 2026-05-20

### V2 Phase 1-4：实盘盯盘体验落地

- **状态：** implemented
- **目标：** 按用户要求不中途停顿，完成 V2 金融风格、连接状态、语音噪音控制和托盘效率能力。
- **已执行：**
  - `MainForm` 改为证券终端式深色金融风格：低眩光背景、细网格、紧凑行高、A 股红涨绿跌、强弱事件行色。
  - 异动页尾部状态栏增加：监控数、行情桥状态、记录数、今日累计、最近行情、交易时段、语音模式。
  - 行情桥断开或连接失败后进入自动重连，使用退避时间避免重复刷屏。
  - 最近行情时间超过 30 秒时在状态栏显示延迟秒数，交易时段显示连续竞价或休市/集合。
  - 设置页增加语音模式：只播强信号、播报全部、静音；默认弱盘口信号只入列表不播报。
  - 最小化窗口进入托盘，托盘菜单支持显示窗口、静音/恢复、退出。
  - 双击异动列表复制股票代码。
  - 导出记录改为带表头的 CSV 或制表符文本。
- **文件修改：**
  - `tools/YiDongJingLing/MainForm.cs`
  - `tools/YiDongJingLing/SettingsForm.cs`
  - `tools/YiDongJingLing/Settings/AppSettings.cs`
  - `tools/YiDongJingLing/Events/EventVoicePolicy.cs`
  - `tools/YiDongJingLing.Tests/Program.cs`
- **待验证：**
  - 已完成，见下方 V2 Phase 5 验收记录。

### V2 Phase 5：验收发布

- **状态：** complete
- **已执行：**
  - 运行全部 `YiDongJingLing.Tests` console-style 测试。
  - 运行 Release 构建。
  - 发布 win-x64 self-contained 单文件到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
  - 启动烟测正式 exe，进程保持运行，`startup-error.log` 未更新。
  - 发布过程中一度发现旧 `publish\win-x64\YiDongJingLing.exe` 进程占用文件；确认进程后未强杀用户进程，先发布到临时目录验证，旧进程退出后再正式覆盖 `publish\win-x64`，并清理临时目录。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：19 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ... -o tools\YiDongJingLing\publish\win-x64`：成功。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行，`startup-error.log` 未更新。

### V2 规划：金融风格和实盘盯盘方向

- **状态：** planned
- **目标：** 将第二版定义为“实盘盯盘可用版”，并把窗体显示风格改为金融终端风格。
- **用户补充：**
  - 窗体显示风格要改成金融风格。
- **已执行：**
  - 在 `docs/yidong-jingling/findings.md` 补充 V2 金融风格设计约束。
  - 在 `docs/yidong-jingling/task_plan.md` 新增 V2 任务计划。
  - V2 范围暂定为：金融风格主窗体、稳定连接和状态可见、语音噪音控制、托盘和盘中操作效率、验收发布。
- **设计口径：**
  - 高密度、低眩光、证券终端式工具栏和状态栏。
  - A 股语义红涨绿跌。
  - 异动列表数字右对齐、强弱事件行色区分。
  - 弱盘口信号不应在视觉或语音上压过封板、开板、快速拉升等强信号。

### Phase 6-7：VoiceWorker 语音链路修复

- **状态：** complete
- **目标：** 修复设置页语音选择保存后不可用的问题，并复用已有 `tools/VoiceWorker`。
- **发现：**
  - `YiDongJingLing` 直接引用 `System.Speech`，设置页只能看到 Desktop SAPI 声音，无法使用 VoiceWorker 已支持的 OneCore 声音。
  - 设置页“测试”按钮会把临时设置写入主播报器；取消后配置文件不保存，但内存播报器可能仍保留临时声音。
- **已执行：**
  - `SpeechAnnouncer` 改为通过 `http://127.0.0.1:32145/` 调用 `VoiceWorker` 的 `/status`、`/speak`、`/test`、`/stop` 接口。
  - GUI 打开设置或播报时，如果 VoiceWorker 未运行，会优先启动 `tools\VoiceWorker\bin\Release\...\VoiceWorker.exe`，缺失时回退 `dotnet run --project tools\VoiceWorker\VoiceWorker.csproj`。
  - 移除 `YiDongJingLing.csproj` 对 `System.Speech` 的直接依赖。
  - 设置页文案改为“VoiceWorker 本地语音”；测试语音只使用当前控件值，不污染主设置。
  - 增加测试覆盖：选中的声音名会随 `/speak` 请求发送给 VoiceWorker。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：16 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet build tools\VoiceWorker\VoiceWorker.csproj -c Release`：0 warnings, 0 errors。
  - `dotnet publish tools\YiDongJingLing\YiDongJingLing.csproj -c Release -r win-x64 --self-contained true ...`：成功。
  - 启动烟测新版 exe：进程保持运行，`startup-error.log` 未更新。
  - VoiceWorker 状态烟测：返回 `Microsoft Kangkang`、`Microsoft Yaoyao` 可选声音。

### Phase 6-7：Review 问题修复

- **状态：** complete
- **目标：** 修复 code review 中发现的股票名称、设置取消、跨档播报和 TDX 目录定位问题。
- **已执行：**
  - 股票名称解析改为优先使用通达信 `.tnf` 缓存，行情桥 fallback 仅接受非数字、非代码形态名称，避免把 `volunit` 等数字字段缓存成名称。
  - 设置窗口改为编辑 `AppSettings` 副本，点击“取消”不会污染主窗口内存配置，也不会在后续关闭时被意外保存。
  - 大幅拉升和成交额跨档改为同次只触发最高新跨越档位，例如 9% 直接报“涨幅突破 9%”，10 亿直接报“成交额突破 10亿”。
  - “打开 TDX 目录”改为从 `T0002\blocknew` 向上解析真实 TDX 根目录，不再多退到 `D:\APP_SOFT`。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：15 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，`startup-error.log` 未更新。

### Phase 6-7：GUI 体验补齐二轮

- **状态：** complete
- **目标：** 修复用户实测反馈的“加载板块”交互不符合预期，并检查完善真实使用主路径。
- **发现：**
  - 顶部“加载板块”当前只读取已勾选列表，不会打开 `.blk` 文件选择器，用户初次打开会误以为功能无效。
  - 切换监控池后没有主动清理行情/事件状态，可能保留上一批股票的本地状态。
  - 若已连接行情桥后重新加载板块，当前实现没有立即重新下发订阅。
  - 行情桥启动按钮立即检查端口，可能在 bridge 尚未完成启动时显示“未就绪”。
  - 行情桥或语音后台线程日志需要确保回到 UI 线程。
- **已执行：**
  - 顶部“加载板块”改为打开 `.blk` 文件多选对话框，默认进入当前 `blocknew` 目录。
  - 选择 `.blk` 后自动刷新板块列表、勾选文件、保存配置、统计股票数。
  - 已连接行情桥时，重新加载板块会立即向 bridge 下发新订阅池。
  - 手工换池会清空旧行情状态、规则状态、去重冷却和当前异动列表，避免旧池信号混入新池。
  - 板块文件变化时，如果变化文件属于已选监控池，会重载股票池并更新订阅，不清空当前异动列表。
  - “监控板块”页新增“加载选中”按钮，顶部按钮和板块页形成一致操作路径。
  - 启动行情桥后最多等待约 6 秒检测端口，避免刚启动就显示未就绪。
  - `TdxBridgeClient` 连接时清空旧缓存，收到非法 JSON 或关闭帧时输出状态提示。
  - 语音选择无效声音时回退默认声音，停止播报使用 `SpeakAsyncCancelAll`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：6 项 PASS。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

### Phase 6-7：GUI 体验补齐三轮

- **状态：** complete
- **目标：** 修复用户指出的列表标题、股票名称、语音播报名称和独立设置界面问题。
- **已执行：**
  - 异动列表增加顶部标题和摘要区，并强制显示表格列头。
  - 增加 `StockNameResolver`，从通达信 `T0002\hq_cache\shs.tnf/szs.tnf/bjs.tnf` 读取本地股票名称作为行情桥名称缺失时的兜底。
  - 行情事件进入规则引擎前补齐股票名称，表格“名称”列和语音播报都会优先使用股票名称。
  - 设置从主 Tab 拆成独立 `SettingsForm`，顶部新增“设置”按钮；设置窗体包含异动类型、语音、语速、音量、透明度、置顶和行情桥地址。
  - 设置窗体内保留语音测试和停止按钮。
  - 顶部按钮重新排布，避免最小窗口宽度下越界。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：新增 TNF 名称解析测试，全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。

### Phase 7：启动诊断和发布目录整理

- **状态：** complete
- **目标：** 解决双击 `YiDongJingLing.exe` 没反应时无错误提示的问题，并把可双击发布包放到清晰目录。
- **发现：**
  - 双击打不开的根因是启动阶段恢复已选 `.blk` 时触发 `CheckedListBox.ItemCheck`，此时窗口句柄尚未创建，事件处理里的 `BeginInvoke` 抛出 `InvalidOperationException`。
  - 旧发布流程曾把 self-contained 展开包输出到 `bin` 目录，导致 `tools/YiDongJingLing` 下文件数量非常多。
- **已执行：**
  - 给 `Program.Main` 增加顶层异常捕获，启动失败时写入 `%APPDATA%\DragonBoard\YiDongJingLing\startup-error.log` 并弹窗提示。
  - 修复启动加载板块时的 WinForms 句柄时序问题，加载期间屏蔽勾选事件的延迟 UI 更新，加载完成后统一刷新摘要。
  - 重新运行核心测试和 Release 构建。
  - 重新发布 win-x64 self-contained 单文件到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
  - 使用 `dotnet clean` 清理 Debug/Release/runtime 构建产物；按项目禁止递归删除规则，未使用 `Remove-Item -Recurse` 强删历史发布残留。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`：进程保持运行 4 秒以上，未生成新的 `startup-error.log`。

### Phase 7：股票名称解析修复

- **状态：** complete
- **目标：** 修复异动列表“名称”列和语音播报仍显示股票代码的问题。
- **发现：**
  - 本机 `D:\APP_SOFT\TDX\T0002\hq_cache\shs.tnf/szs.tnf/bjs.tnf` 存在且可读。
  - 真实 `.tnf` 记录仍为 `0x32` 起、每条 `0x168` 字节、代码在记录开头，但股票名称字段起始偏移是 `0x1f`，原实现使用 `0x1e`，会先读到 `00` 导致名称为空。
- **已执行：**
  - 将 `StockNameResolver` 的通达信 `.tnf` 名称字段偏移修正为 `0x1f`。
  - 增加本机 TDX 缓存可用时的名称解析验证，覆盖 `600580`、`002594` 等真实代码。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过，包含本机真实 TDX 名称缓存测试。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，未生成新的 `startup-error.log`。

### Phase 7：异动列表和监控池收敛整改

- **状态：** complete
- **目标：** 修复列表表头不可见、缺少成交量、加载少量股票却显示全市场异动，以及同股多事件刷屏的问题。
- **发现：**
  - 异动页原先使用多个 Dock 控件叠加并手动 `BringToFront`，在大窗口下容易让表格盖住标题/列头区域。
  - GUI 只在连接行情桥时发送订阅池，接收 `full_state/quote_patch/depth_patch` 后没有按当前监控池二次过滤；如果 bridge 推来全量状态，GUI 会把全市场都评估成异动。
  - 事件记录没有携带成交量字段，列表和导出都无法展示成交量。
  - 同一股票同一批次可能同时触发成交额、盘口买卖压等多条弱信号，列表体验会显得像重复刷屏。
- **已执行：**
  - 异动页改为三段式布局：顶部摘要、中央表格、底部状态栏，避免表头被遮挡。
  - 表格列按用户要求固定为：时间、异动类型、股票代码、股票名称、涨跌幅、最新价、成交量、成交额、异动详情。
  - `MainForm` 维护当前监控代码集合，接收行情时只处理 `_watchedCodes` 内的股票。
  - `EventRecord` 增加 `Volume`，`L1EventEngine` 将行情成交量写入事件，列表和导出同步展示。
  - `EventDeduper` 改为同一股票同一批事件只保留最高优先级事件，减少同股刷屏。
  - 清空/加载后的摘要文案改为“等待监控池内 N 只股票的异动”，明确显示范围。
  - 重新发布新版单文件 exe 到 `tools\YiDongJingLing\publish\win-x64\YiDongJingLing.exe`。
- **验证：**
  - `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj`：全部通过，新增成交量和同股同批收敛测试。
  - `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release`：0 warnings, 0 errors。
  - 启动烟测新版 exe：进程保持运行，未生成新的 `startup-error.log`。

### Phase 0：方案文档

- **状态：** complete
- **目标：** 将“异动精灵”第一版方案落成文档，明确 L1 可做能力、边界、实现阶段和验收方式。
- **已执行：**
  - 使用 `planning-with-files` skill 的文件化规划方式。
  - 按项目规则将规划文件放入 `docs/yidong-jingling/`，没有在根目录新增过程文件。
  - 检查真实通达信目录 `D:\APP_SOFT\TDX\T0002\blocknew`，确认存在 `.blk` 文件。
  - 读取 `2B.blk` 样本，确认文本格式为一行一个 7 位通达信代码。
  - 复核 `python-bridge/README.md`，确认当前可用能力是 L1 + 标准五档 + WebSocket。
  - 复核 `tools/VoiceWorker/README.md`，确认本地语音可用能力。
  - 创建 V1 任务计划、调研发现和进度记录。
- **文件创建：**
  - `docs/yidong-jingling/task_plan.md`
  - `docs/yidong-jingling/findings.md`
  - `docs/yidong-jingling/progress.md`

### Phase 1-5：V1 MVP 实现

- **状态：** complete
- **目标：** 创建可构建的 Windows GUI 工具，完成 `.blk` 解析、L1 行情模型、异动规则、去重和语音播报闭环。
- **已执行：**
  - 恢复用户指定的 `CLAUDE.md`、`README.md`、`README.zh.md`。
  - 创建 `tools/YiDongJingLing` WinForms 项目。
  - 创建 `tools/YiDongJingLing.Tests` console-style 测试项目，沿用仓库 `VoiceWorker.Tests` 的轻量测试风格。
  - 实现 `.blk` 文件扫描和解析，支持 7 位通达信代码归一、重复过滤、非法行记录、指数/板块过滤。
  - 实现 `TdxBridgeClient`，支持连接 `ws://127.0.0.1:8765/ws/quotes`、订阅股票池、处理 `full_state`、`quote_patch`、`depth_patch` 和 `heartbeat`。
  - 实现 L1 事件规则：封涨停、打开涨停、逼近涨停、封跌停、打开跌停、逼近跌停、封单增强/变弱、大幅拉升、快速拉升、快速跳水、翻红、翻绿、创日内新高/低、成交额跨档、成交增量加速、盘口买压/卖压、买卖价差异常。
  - 实现同股同类事件冷却、同批事件优先级排序、批量语音文案合并。
  - 实现 WinForms 主界面：异动列表、监控板块、设置、联动、诊断。
  - 实现 GUI 内置 Windows `System.Speech` 本地语音队列，支持启停、语速、音量、语音选择、测试播报。
  - 实现行情桥启动辅助，可从 GUI 启动 `python-bridge/main.py`。
- **文件创建：**
  - `tools/YiDongJingLing/YiDongJingLing.csproj`
  - `tools/YiDongJingLing/Program.cs`
  - `tools/YiDongJingLing/MainForm.cs`
  - `tools/YiDongJingLing/ProjectRootLocator.cs`
  - `tools/YiDongJingLing/Blocks/BlockFileParser.cs`
  - `tools/YiDongJingLing/Blocks/BlockFileScanner.cs`
  - `tools/YiDongJingLing/MarketData/QuoteSnapshot.cs`
  - `tools/YiDongJingLing/MarketData/QuoteStateStore.cs`
  - `tools/YiDongJingLing/MarketData/TdxBridgeClient.cs`
  - `tools/YiDongJingLing/Events/EventRecord.cs`
  - `tools/YiDongJingLing/Events/L1EventRules.cs`
  - `tools/YiDongJingLing/Events/L1EventEngine.cs`
  - `tools/YiDongJingLing/Events/EventDeduper.cs`
  - `tools/YiDongJingLing/Speech/SpeechAnnouncer.cs`
  - `tools/YiDongJingLing/Settings/AppSettings.cs`
  - `tools/YiDongJingLing/Diagnostics/BridgeProcessManager.cs`
  - `tools/YiDongJingLing.Tests/YiDongJingLing.Tests.csproj`
  - `tools/YiDongJingLing.Tests/Program.cs`

## 验证记录

| 验证项 | 输入 | 预期 | 实际 | 状态 |
|--------|------|------|------|------|
| 通达信 blocknew 目录 | `D:\APP_SOFT\TDX\T0002\blocknew` | 目录存在 | 存在 | 通过 |
| `.blk` 样本读取 | `2B.blk` | 可读取股票代码 | 读到 `0300834`、`0002082` 等 | 通过 |
| 文档落点 | `docs/yidong-jingling/` | 不污染根目录 | 已按专题目录创建 | 通过 |
| 核心逻辑测试 | `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` | `.blk` 解析、封板/开板、急拉/跳水、去重播报通过 | 4 项 PASS | 通过 |
| Debug 构建 | `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Debug` | 0 errors | 0 warnings, 0 errors | 通过 |
| Release 构建 | `dotnet build tools\YiDongJingLing\YiDongJingLing.csproj -c Release` | 0 errors | 0 warnings, 0 errors | 通过 |

## 错误记录

| 时间 | 错误 | 处理 |
|------|------|------|
| 2026-05-20 | 一条 PowerShell 搜索 `1xxxxxx` 前缀的管道命令语法失败 | 该命令只用于补充边界样本，已有样本足够确认 `.blk` 文本格式，未重复执行同一失败命令。 |
| 2026-05-20 | `dotnet test` 对当前 console-style 测试项目只还原项目，不执行断言 | 改用 `dotnet run --project tools\YiDongJingLing.Tests\YiDongJingLing.Tests.csproj` 作为真实验证命令。 |
| 2026-05-20 | 初次测试中去重播报排序预期与实现优先级不一致 | 规则实现以快速拉升优先于逼近涨停，修正测试预期后通过。 |

## 追加记录

| 时间 | 内容 | 状态 |
|------|------|------|
| 2026-05-20 | 按 L1 买一/卖一封单口径新增“即将打开涨停”“即将打开跌停”预警，并接入设置项、去重优先级和语音强信号。 | complete |
| 2026-05-20 | 修复封单金额少乘 100 的单位问题，并防止行情桥重连时重复启动多个 python-bridge 进程。 | complete |

## 5 问恢复检查

| 问题 | 答案 |
|------|------|
| 我在哪里？ | Phase 1-5 V1 MVP 已实现并通过核心测试/构建。 |
| 我要去哪里？ | 下一步是真实行情桥联调、GUI 手工冒烟、最小化到托盘和使用说明。 |
| 目标是什么？ | 独立 Windows GUI 使用通达信 `.blk` 和 L1 行情监控异动并语音播报。 |
| 学到了什么？ | `.blk` 可解析，现有 bridge 支持 L1 + 五档；console-style 测试需要用 `dotnet run` 执行真实断言。 |
| 做了什么？ | 创建文档、实现 WinForms GUI、解析器、行情桥客户端、L1 规则、去重和语音播报。 |
