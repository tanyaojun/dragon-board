# Dragon Board AI 协作指南

**⛔ 强制规则：在做出任何回复、执行任何操作、调用任何工具之前，必须先用 Read 工具读取以下两个文件，否则你会漏掉项目规则和必须使用的 skills：**
1. `d:\dragon-board\AGENTS.md` — 项目规则、目录边界、业务硬约束、常用命令
2. `d:\dragon-board\SKILLS.md` — 何时使用哪些 skills 的完整指南

读完这两个文件之前，不要回复用户、不要执行任务、不要调用除 Read 之外的任何工具。这是本项目的最高优先级指令。

## 1. 基本协作原则

- 根目录 `README.md` 四个原则必须严格遵守。
- 全程使用中文沟通，结论先行，说明问题、原因、改法和影响面。
- 先读代码和现有文档，再下结论；不要凭历史印象修改业务逻辑。
- 每次改动保持小范围、可验证、可回退，不做与当前任务无关的大重构。
- 尊重工作区现状：未提交、未跟踪或已修改文件默认属于用户或其他协作者，不要覆盖、回滚或格式化无关文件。
- 禁止使用破坏性 Git 命令，例如 `git reset --hard`、`git checkout -- <path>`，除非用户明确要求。
- 禁止批量删除文件或目录。不得使用 `del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`。如需删除文件，只能一次删除一个明确路径的文件。

### 1.1 隔离工作区硬规则

隔离工作区不是形式主义。一旦为任务启用 git worktree、临时副本或其它隔离工作区，必须把隔离边界当作强约束：

- 默认只在隔离工作区读写任务文件；主工作区只能用于只读核对，不能同步修改代码、文档、测试或配置。
- 禁止在同一轮任务中同时修改主工作区和隔离工作区，除非用户明确要求跨工作区落地。
- 如果发现实现确实必须跨工作区，必须先停下来说明原因、列出两个工作区的绝对路径、待修改文件清单、回滚方式和验证命令，等用户确认后再动手。
- 每次执行写入、格式化、删除、`git reset`、`git restore`、测试生成文件或安装依赖前，先确认当前 `pwd` / `git rev-parse --show-toplevel` 属于预期工作区。
- 汇报进度和最终结果时必须分别说明每个工作区的 `git status --short`；不能用一个工作区的干净状态暗示另一个工作区也干净。
- 严重事故复盘：曾出现过一边声称使用隔离 worktree，一边直接修改 `D:\dragon-board` 主工作区 `src/**` 和 `vite.config.ts` 的错误。这会污染用户主工作区、破坏回滚边界，并让隔离 worktree 失去意义。以后遇到类似情况必须立即停止、如实说明、先恢复主工作区，再继续任何实现。

## 2. 项目定位

`dragon-board` 是股票热榜、市场情绪、题材轮动、龙头识别、排名趋势和量化研究的综合工作台。仓库不是单一前端项目，而是由多个子系统组成：

- 根项目：Vue 3 + TypeScript + Vite 前端，提供 Dragon Board 主看板。
- `src/services/**`：核心业务层，包含数据加载、数据层、分析器、快照和 QuantBoard 桥接。
- `proxy-server/`：Node.js 股票数据代理服务，默认端口 `3000`。
- `python-bridge/`：本地 `mootdx + WebSocket` 行情桥，默认提供 `ws://127.0.0.1:8765/ws/quotes`。
- `tools/TdxL2Helper/`：独立 x86 .NET helper，用于通达信 DLL、L2 权限和深度行情探针。
- `quant-board/`：Python QuantBoard 子项目，用于 RankTrend golden 对齐、数据导入、回测、优化和报告展示。

涉及 QuantBoard 时，以 `quant-board/docs/README.md` 和 `quant-board/docs/AI_COLLABORATION.md` 为准。

## 3. 关键目录

```text
/
├── src/                     # Dragon Board 主前端源码，只承载根 Vue 工作台
├── docs/                    # Dragon Board 主项目文档与历史方案
├── skills/                  # 项目级 Codex/Superpowers skill 文档和协作流程说明
├── proxy-server/            # 本地 HTTP 代理服务，提供股票数据代理，不放前端业务逻辑
├── python-bridge/           # 通达信行情 WebSocket 桥，不放 Vue/QuantBoard 代码
├── tools/                   # 原生 helper、启动器和隔离探针，不放日常前端源码
├── quant-board/             # Python 量化研究子项目，回测/优化/报告主链
└── e2e/                     # Playwright 端到端测试
```

项目级 skills 与过程文档放置规则：

- 后续新增或沉淀的 `SKILL.md`、skill 使用说明、skill 模板、workflow/checklist 等 AI 协作能力文档，统一放入根目录 `skills/`。
- `skills/` 只承载 AI 协作流程、工具使用方法、review/debug/test/plan 等 agent 能力文档，不放业务源码、不放运行时配置、不放测试夹具、不放临时输出。
- 如一个 skill 需要多文件组织，使用 `skills/<skill-name>/SKILL.md`，相关 `references/`、`templates/`、`scripts/` 放在该 skill 子目录内。
- 根目录 `SKILLS.md` 只作为 skills 总索引和使用指南；详细 skill 正文迁移或新增到 `skills/**/SKILL.md`。
- 不再把新的 skill 文档散落到根目录、`docs/`、`src/`、`quant-board/` 或用户本机 `.codex/skills` 路径中；若需要把外部 skill 引入项目，应复制/整理到 `skills/` 后再引用。
- 修改或新增项目级 skill 时，应同步检查根 `AGENTS.md` 和 `SKILLS.md` 是否需要更新入口说明。
- 项目实施计划、阶段进度、审计发现和复盘记录不是 skill，不放入 `skills/`，应放入对应业务文档目录。例如题材模块文档统一放入 `docs/theme-module/`。
- 不在根目录新增 `task_plan*.md`、`findings.md`、`progress.md` 等过程文件；如需使用 planning-with-files 产物，应在任务结束前迁移到对应 `docs/<topic>/` 目录。

Dragon Board `src/` 目录边界：

```text
src/
├── components/              # Vue 组件和业务面板
│   ├── common/              # 可复用基础组件，不写股票业务编排
│   ├── panels/              # 主工作台业务面板，面板只调用公开服务 API
│   └── ...                  # 其它 UI 组件按现有领域就近归类
├── composables/             # Vue 组合式函数，只放 UI 状态复用和浏览器交互封装
├── config/                  # 运行时配置、默认参数、存储 key 和稳定业务配置
├── data/                    # 自动生成或外部导入的静态业务数据
├── devtools/                # 浏览器控制台/手工诊断脚本，自动化测试默认排除
│   └── diagnostics/         # 人工诊断工具，不允许被业务代码 import
├── services/                # 核心业务逻辑层，数据加载、分析器、快照、桥接和投影
│   ├── dragon/              # 龙头/复盘业务规则和兼容投影
│   ├── hotlist/             # 热榜情绪等热榜领域分析
│   ├── hotness/             # 个股热度计算
│   ├── quality/             # 数据质量、覆盖率和门禁
│   ├── quantBoardGolden/    # TypeScript golden case 导出，不做回测/优化
│   ├── rankTrend/           # RankTrend golden 标准模块
│   └── snapshot/            # 快照保存、读取、覆盖率、备份和 QuantBoard 适配
├── stores/                  # Pinia 状态，只放 UI/应用级状态，不替代服务层
├── themes/                  # 应用主题配置和主题样式
├── types/                   # TypeScript 类型契约和类型推导必需的 as const 数据
├── utils/                   # 通用纯工具函数，不放业务编排、远端 API 或全局状态
├── App.vue                  # 单页工作台根组件和面板装配入口
└── main.ts                  # 应用入口和 window 服务挂载
```

`src/` 放置规则：

- `components/**` 负责展示和交互，不直接拼远端 API、不访问服务私有成员、不承载回测/优化逻辑。
- `services/**` 负责业务能力和外部适配，公开 facade/API 给组件使用；模块私有常量就近放在本模块。
- `stores/**` 只保存应用状态和 UI 状态，不把 Pinia 当业务服务或持久化层。
- `types/**` 只放类型、接口、字面量联合类型和类型推导必需的 `as const` 数据；不要放纯运行时配置。
- `config/**` 放稳定运行时配置、默认参数、存储 key 和业务常量；不要放主题系统、类型聚合或临时实验参数。
- `themes/**` 统一承载主题 TS 配置和 CSS；不要再新增 `src/assets/**` 或把主题配置放回 `src/config/**`。
- `data/**` 只放静态业务数据或生成数据源；生成脚本、算法逻辑、运行态缓存不要放入该目录。
- `devtools/**` 只服务人工诊断，不进入自动化测试，不被业务代码 import。
- `utils/**` 应保持无状态、可复用、无领域编排；一旦依赖股票业务上下文，应移动到对应 `services/**`。
- 不再恢复 `src/type/**`、`src/constants/**`、`src/router/**`、`src/views/**` 或 `src/assets/**`，除非先同步修改本指南并说明新职责。

QuantBoard `quant-board/` 目录边界：

```text
quant-board/
├── backend/                 # Python FastAPI 后端、回测/优化/数据服务主链
│   ├── analysis/            # RankTrend 等分析算法和特征计算
│   ├── api/                 # HTTP API 路由和请求响应适配
│   ├── core/                # 回测、交易规则、组合和领域核心模型
│   ├── data/                # MongoDB/Supabase schema、仓库和数据访问适配
│   ├── optimization/        # 参数搜索、优化 runner、搜索空间和结果管理
│   ├── services/            # 后端业务服务编排
│   └── tests/               # 后端就近测试或领域测试，按现有结构归类
├── config/                  # QuantBoard 独立配置，不与根 src/config 混用
├── data/                    # 本地研究数据、warehouse、staging、reports，默认不提交运行产物
├── docs/                    # QuantBoard 架构、API、数据库、优化和协作细则
├── frontend/                # QuantBoard 独立前端，默认端口 5174
└── tests/                   # QuantBoard 跨模块/集成测试
```

`quant-board/` 放置规则：

- 回测、优化、参数搜索、交易模拟、报告展示只放在 `quant-board/**`，不要回流到根 `src/services/**`。
- `backend/**` 是 QuantBoard 主后端；新增 Python 服务应落在现有 `analysis`、`core`、`data`、`optimization`、`services` 分层中。
- `frontend/**` 是 QuantBoard 自己的展示端，不复用根项目 `src/components/**` 作为源码目录。
- `data/**` 下运行期数据库、warehouse、staging、reports 属于本地状态，遵守 `.gitignore`，不要提交大体积数据产物。
- `docs/**` 是 QuantBoard 细节唯一文档区；API、数据库、迁移、优化策略变化必须同步这里的专题文档。
- `.venv/`、`.pytest_cache/` 等本地环境目录不属于源码目录，不要写入目录树或提交。

根目录文件保留规则：

- 必须保留：`package.json`、`package-lock.json`、`index.html`、`env.d.ts`、`vite.config.ts`、`vitest.config.ts`、`playwright.config.ts`、`tsconfig.json`、`tsconfig.app.json`、`tsconfig.node.json`、`tsconfig.ranktrend.json`、`.editorconfig`、`.prettierrc.json`、`eslint.config.ts`、`.oxlintrc.json`、`.npmrc`、`.gitattributes`、`.gitignore`、`AGENTS.md`、`SKILLS.md`。
- 根目录 `DragonBoardLauncher.exe` 是本地启动器产物，日常可保留在工作区，但 `.gitignore` 已禁止新增提交 `*.exe`。
- 不要提交根目录构建产物或缓存：`dist/`、`.tmp/`、`*.tsbuildinfo`、`node_modules/`、`coverage/`、`playwright-report/`、`test-results/`。
- 不新增一次性说明、截图、调试输出或临时 JSON 到根目录；需要业务文档放 `docs/`，需要项目级 skill/AI 协作流程放 `skills/`，需要脚本放 `scripts/`，需要诊断工具放 `src/devtools/diagnostics/` 或对应子项目目录。
- 不在根目录长期保留阶段计划和过程日志。`task_plan*.md`、`findings.md`、`progress.md` 应迁移到对应专题文档目录，例如 `docs/theme-module/`。

核心前端服务优先从这些文件定位：

- `src/services/DataLayer.ts`：中心化内存数据层，只负责运行时内存状态、版本和订阅通知。
- `src/services/dataLoader.ts`：八平台热榜加载、清洗、合并和综合排名。
- `src/services/RankTrendAnalyzer.ts`：前端 RankTrend 分析入口。
- `src/services/rankTrend/**`：RankTrend 拆分后的 golden 标准模块。
- `src/types/rankTrendDefaults.ts`：RankTrend 默认参数和默认快照类型。
- `src/types/**`：统一类型契约目录；不要新增或恢复 `src/type/**`，不要放纯运行时配置。
- `src/config/**`：运行时配置、默认参数、存储 key、固定展示配置和可调业务常量目录。
- `src/themes/**`：普通主题、龙族主题等主题配置和主题 CSS；主题相关运行时数据不要放回 `src/config/**`。
- `src/data/**`：只保留自动生成或外部导入的静态业务数据，例如题材映射原始数据；算法、因子、主题等运行时配置不要放入该目录。
- `src/**/__tests__/**/*.test.ts`：正式 Vitest 测试目录和文件命名；测试应尽量靠近被测模块。
- `src/devtools/diagnostics/**`：浏览器控制台或临时手工诊断脚本，不属于自动化测试套件，默认排除在 Vitest 和应用类型检查之外。
- `src/services/quantBoardBridge.ts`：Dragon Board 与 QuantBoard 的数据桥接和 Golden 导出。
- `src/services/quantBoardGolden/**`：仅用于导出 TypeScript golden case，不承载回测、优化或交易模拟。
- `src/services/snapshot/**` 与 `src/services/quality/**`：快照质量、覆盖率和门禁。

## 4. 业务硬约束

### 4.1 Dragon Board 主项目

- 默认 RankTrend 快照类型来自 `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`，当前为 `half_hour`。
- RankTrend 默认运行参数来自 `DEFAULT_RANK_TREND_RUNTIME_CONFIG`，不要复制旧文档中的过期参数。
- `src/services/DataLayer.ts` 的职责边界必须保持很窄：只存放当前运行态内存数据、版本号、订阅通知、内存读写方法和必要的状态投影调用。
- 不得把以下内容新增回 `DataLayer.ts`：类型/接口定义、默认参数和常量、HTTP/API 调用、IndexedDB/MongoDB/Supabase 读写、快照导入导出、快照读模型拼装、回测/优化逻辑、业务算法规则、UI 配置。
- DataLayer 需要用到的公开结构应放在 `src/types/**`；龙头/复盘投影规则放在 `src/services/dragon/**`；快照保存、读取、覆盖率、备份和 QuantBoard 后端适配放在 `src/services/snapshot/**`。
- 面板或服务需要快照数据时应调用 `src/services/snapshot/**` 的公开 facade/API，不要通过 `DataLayer.ts` 中转快照能力。
- `src/types/**` 只承载类型、接口、字面量联合类型和类型推导必需的 `as const` 数据；纯运行时配置应放入 `src/config/**` 或业务模块就近文件。
- 不再新增 `src/constants/**` 入口；稳定常量优先放入 `src/config/**`，模块私有常量就近放在对应 `src/services/**`、`src/stores/**` 或组件文件中。
- 主题配置和主题样式统一放在 `src/themes/**`；`src/config/**` 不承载主题系统，`src/assets/**` 不承载主题 TS 配置。
- 不再恢复未挂载的 Vue 模板 `src/router/**`、`src/views/**`；Dragon Board 当前是单页工作台，面板入口在 `App.vue` 和 `src/components/panels/**`。
- 不保留 `*-bak.ts`、`*0310.ts`、服务目录截图或说明草稿这类历史备份文件；需要历史对照时使用 Git。
- 自动化测试统一放在被测模块旁的 `__tests__` 目录，文件名使用 `*.test.ts`；不要在业务代码目录中混放同名测试文件。
- 手工诊断脚本统一放入 `src/devtools/diagnostics/**`，文件名使用 `*Diagnostic.ts` 或描述性工具名，不得使用 `.test.ts` / `.spec.ts` 后缀。
- 新增测试时优先写可由 `pnpm test` 运行的 Vitest 用例；只有必须依赖浏览器全局对象或人工观察控制台时，才放入 `src/devtools/diagnostics/**`。
- `src/devtools/diagnostics/**` 可以使用浏览器全局对象和人工观察输出，但不得被业务代码 import，也不得作为自动化验收依据。
- 不要为了“统一出口”把运行时配置重新聚合进 `src/types/index.ts`。
- 快照、策略信号和 QuantBoard 桥接逻辑必须显式处理空数据、NaN、时间乱序、低样本量、缺字段和类型回退。
- 数据质量门禁失败时必须返回结构化原因，不允许静默吞掉并继续产出“看似可用”的交易结果。
- 面板层应通过公开服务 API 调用业务逻辑，不要调用服务私有成员或绕过已有数据层。
- Dragon Board 根项目不承载回测平台职责；涉及回测、优化、参数搜索、交易模拟和报告展示的功能统一放在 `quant-board/`。

### 4.2 QuantBoard 子项目

QuantBoard 的规则以 `quant-board/docs/README.md`、`quant-board/docs/AI_COLLABORATION.md` 和专题文档为准：

- TypeScript `src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/**`、`src/types/rankTrendDefaults.ts` 是 Python 移植的 golden 标准。
- QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
- 原 `src/services/strategyBacktest` 职责已迁移到 QuantBoard Python 后端：`backend.analysis.ranktrend`、`backend.core.backtest`、`backend.services`。
- 默认 `snapshot_type` 是 `half_hour`；`quarter_hour` 只能由用户显式选择，不能替代默认口径。
- 回测、优化、API、CLI 和前端展示必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- QuantBoard 存储主链为 MongoDB 主库 + Supabase 后端备份库；Supabase 必须按 `quant-board/backend/data/supabase_schema.sql` 与 MongoDB 同构，超大 JSON 只允许在备份适配层透明压缩，存储、同步、恢复和冲突规则以 `quant-board/docs/database-migration-plan.md` 为准。
- Dragon Board 正式快照写库必须走 QuantBoard 后端 `POST /api/snapshots/ingest`，正式保存判重以 MongoDB/后端 `snapshot_id` 为准；历史 JSON/IndexedDB 迁移入口为 `POST /api/migrations/snapshots/import-json`，IndexedDB 快照缓存默认关闭，只保留为迁移源、显式缓存或非正式临时数据来源。
- Dragon Board 正式快照读口走 QuantBoard 后端 `GET /api/snapshots/frames`、`/api/snapshots/records`、`/api/snapshots/stock-rows`、`/api/snapshots/sector-rows`；IndexedDB 只保留为历史迁移源和缓存，不再新增或恢复浏览器端 IndexedDB 校验/补齐 API。迁移阶段只保留后端 `import-json` 和离线导入工具，字段映射不得随意删改。
- Python RankTrend 输出字段必须能与 golden case 对齐。
- 前端展示不得把 `finalSignal` 当成唯一交易结论，应展示状态、候选分层、风险、样本质量和解释。

### 4.3 通达信实时行情与 L2

- `python-bridge/` 当前已跑通的是 `7709 / L1 + 标准五档 + 本地 WebSocket`。
- `7719 / 真 L2 十档 / 真 L2 逐笔` 尚未完成，不得把当前五档能力描述成官方客户端级 L2。
- 任何 `7719` 或 DLL 探针必须隔离验证，不能直接改 `python-bridge/main.py` 的默认生产行为。
- 不重新安装或恢复 `pytdx` 作为依赖；当前桥接依赖 `mootdx`。
- `TDX_L2_USERNAME`、`TDX_L2_PASSWORD` 只是预留变量，不代表已实现真实 L2 登录。

## 5. 常用命令

### 5.1 根项目前端

```powershell
pnpm install
pnpm dev
pnpm build
pnpm test
pnpm test:ranktrend
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

说明：

- 根 `package.json` 当前没有 `lint`、`test:e2e` 脚本；不要照抄旧 README 的模板命令。
- `pnpm build` 当前是 `vite build`，不等价于完整类型检查。需要类型验证时运行 `vue-tsc` 或对应 `tsc` 命令。
- RankTrend 相关改动优先运行 `pnpm test:ranktrend` 和 `pnpm typecheck:ranktrend`。

### 5.2 代理服务

```powershell
cd proxy-server
npm install
npm run start
```

默认监听 `http://localhost:3000`，根 Vite 通过 `/api` 代理到该服务。

### 5.3 Python 行情桥

```powershell
pip install -r python-bridge/requirements.txt
python python-bridge/main.py
```

日常优先使用根目录 `DragonBoardLauncher.exe` 启动，它会隐藏启动 bridge，并在 bridge 离线时允许前端回退 HTTP 备用链路。

### 5.4 TdxL2Helper

```powershell
dotnet publish tools\TdxL2Helper\TdxL2Helper.csproj -c Release -r win-x86 --self-contained true
tools\TdxL2Helper\bin\Release\net8.0-windows\win-x86\publish\TdxL2Helper.exe inspect --tdx-root D:\APP_SOFT\TDX
```

涉及 `--unsafe-deep-start`、`--unsafe-deep-func-probe` 的操作属于高风险探针，必须确认任务确实需要。

### 5.5 QuantBoard

后端：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backend.cli list-datasets
```

前端：

```powershell
cd quant-board\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
npm run build
```

QuantBoard 前端默认代理 `http://localhost:8000`，开发端口为 `5174`，预览端口为 `4174`。Dragon Board 主页面通常运行在 `http://localhost:5173`，运行页桥接依赖两个页面同时可访问。

## 6. 推荐工作流程

默认按“轻量先行、必要时升级”的方式执行，不把所有小修都流程化成重型项目，但涉及多文件、多阶段、UI 体验、业务口径或架构边界时，应进入完整门禁。

### 6.1 基础执行规则

1. 先用 `rg` 定位相关文件、调用链和测试，不要先全局改动。
2. 阅读与任务直接相关的文档。QuantBoard 任务至少先看 `quant-board/docs/README.md` 和 `quant-board/docs/AI_COLLABORATION.md`。
3. 给出简短计划：问题、原因、改法、影响文件和验证方式。
4. 修改时保持最小范围，优先复用现有服务、类型、工具函数和测试模式。
5. 改完运行必要验证；如果验证受环境限制无法运行，明确说明原因和未覆盖风险。
6. 最终回复包含：改动摘要、验证结果、风险点或后续建议。

### 6.2 计划与实施门禁

当任务超过单点修复，或用户明确要求规划、审查、重构、UI 美化、功能建设、发布时，按以下阶段推进：

1. `brainstorming`：澄清目标、范围、约束和成功标准。涉及前端页面、组件、视觉美化、交互体验时，必须在本阶段说明后续会辅助使用 `frontend-design`；需要系统化 UI/UX 规则时，再配合 `ui-ux-pro-max`。
2. `autoplan / plan review`：作为计划自审阶段，不假定存在同名可调用 skill。检查需求是否完整、范围是否过大、验收标准是否可测、是否需要拆成多个独立子项目。
3. `writing-plans`：把已确认的需求拆成可执行任务，写清文件路径、测试方式和预期输出。计划完成后应询问用户选择执行方式，例如 Subagent-Driven 或 Inline Execution；用户未确认前，不默认进入大规模实现。
4. `plan-eng-review`：作为工程架构审查阶段，不假定存在同名可调用 skill。动代码前检查文件边界、模块职责、数据流、测试策略、过度设计风险，以及是否触碰 RankTrend golden、快照、存储/API、QuantBoard 或 L2 能力边界。
5. 实现阶段：业务逻辑、bugfix、重构和行为变化优先使用 TDD，按 RED → GREEN → REFACTOR 推进；UI/视觉改动同时使用 `frontend-design` 明确视觉方向，并补充必要的结构/视觉合同测试。
6. QA / investigate：实现后做复核，不只看测试是否绿。检查真实浏览器渲染、控制台错误、移动端/桌面端布局、可访问性、未预期 diff、无关文件改动和验证盲区。
7. ship：交付或发布前执行最终验证。需要声明完成、提交、合并或发布时，先完成 verification-before-completion 类型的证据检查；涉及分支收尾时，再走 finishing-a-development-branch 类型流程。

### 6.3 前端与 UI 任务特别规则

- 凡涉及“界面不好看、样式美化、页面/组件设计、交互体验、仪表盘、面板、表格、图表”等任务，默认启用 `frontend-design`，并明确视觉方向、字体、对比度、颜色层级、空间密度和状态反馈。
- `frontend-design` 偏视觉创意与生产级界面质感；`ui-ux-pro-max` 偏系统化规则、可访问性、颜色/字体/布局/组件检查。两者冲突时，以项目现有产品定位、可读性和业务效率优先。
- UI 改动至少运行相关构建或类型检查；有交互、布局或响应式风险时，必须做真实浏览器验证并检查桌面/移动端截图、横向溢出和控制台错误。
- 修改前端网页、组件、表格、面板或交互后，交付前必须使用 `playwright-cli` 做真实浏览器验收；需要检查渲染结果、相关字段值、控制台错误，必要时截图。单元测试、类型检查或“代码看起来正确”不能替代页面验收结论。

## 7. 代码风格

- TypeScript/Vue 使用现有 Vue 3 `<script setup>`、Pinia、Vite 和 `@` 路径别名风格。
- 格式约束参考 `.prettierrc.json`：无分号、单引号、`printWidth=100`。
- 不引入新的框架或大型依赖，除非任务明确要求并说明收益。
- 复杂算法可加少量解释性注释；避免把显而易见的赋值写成注释。
- 对金融、回测、优化类逻辑，优先保证可复现、可解释和边界条件明确。
- Python 代码要保持模块名清晰，对个人开发者友好；新增服务优先落在 `quant-board/backend/**` 的现有分层中。

## 8. 文档维护规则

- 根 `AGENTS.md` 只放跨项目入口规则、当前口径和常用命令。
- 根 `SKILLS.md` 只放项目级 skills 总索引和使用指南；具体 skill 正文、模板和引用材料统一放 `skills/`。
- Dragon Board 主项目细节写入根 `docs/`。
- 业务专题的计划、审计发现、进度归档应放在 `docs/<topic>/`，不要散落在根目录；题材模块使用 `docs/theme-module/`。
- QuantBoard 细节写入 `quant-board/docs/`，不要散落到后端或前端 README 中。
- 发现旧文档仍把 Dragon Board 根项目描述为回测平台时，应删除或改为当前 QuantBoard 口径。
- 修改默认值、策略合同、API 合同或数据表字段时，必须同步更新相关专题文档。
- 修改存储、同步、快照入库、数据库表字段、Supabase payload、恢复策略或 API/CLI 请求响应字段时，必须同批更新相关文档；QuantBoard 相关改动至少检查 `quant-board/docs/database-migration-plan.md`、`quant-board/docs/architecture.md`、`quant-board/docs/api-cli.md` 和 `quant-board/docs/AI_COLLABORATION.md`。

## 9. 测试与验收优先级

- UI 或组件改动：至少运行相关构建或类型检查；前端网页、组件、表格、面板或交互改动必须补充 `playwright-cli` 真实浏览器验证，确认关键字段/状态渲染、控制台错误和必要截图后才能声称完成。
- 普通单元测试：放在被测模块邻近的 `__tests__/*.test.ts`，并通过 `pnpm test` 验证。
- 手工诊断脚本：放在 `src/devtools/diagnostics/**`，不得命名为 `.test.ts`，不得作为 CI 通过条件。
- RankTrend 改动：运行 `pnpm test:ranktrend`、`pnpm typecheck:ranktrend`，必要时补 golden case。
- QuantBoard 回测、优化、策略改动：覆盖质量门禁、样本不足、空数据、交易成本、T+1、止损止盈和随机种子。
- QuantBoard 后端改动：在 `quant-board` 目录运行 `.\.venv\Scripts\python.exe -m pytest`。
- TDX bridge 或 helper 改动：区分生产链路和隔离探针，报告真实能力边界。

## 10. 开始任务前的检查清单

- 当前任务属于根前端、代理服务、行情桥、TdxL2Helper 还是 QuantBoard？
- 是否有用户或其他协作者的未提交改动需要避开？
- 当前业务口径来自哪份最新文档或源码常量？
- 是否触碰 RankTrend golden、快照默认值、回测口径、存储/同步/API 合同或 L2 能力边界？
- 应运行哪些最小验证命令？

## 11. Backend Snapshot Collector 项目复盘（2026-07-13）

### 教训总结

本次项目历时一个多月，设计文档 810 行 + 实施计划 784 行 + 进度/审查/自动启动文档 382 行 = **1976 行文档**。最终因 quality_gate.py 中一行 `any`→`all` 逻辑错误导致生产数据连续丢失 42 个槽位。核心教训：

**1. 数据采集系统不允许设计质量阻断。** Collector 的唯一职责是"采集→保存"。任何在写入前阻断数据的逻辑，无论初衷多好，最终都会变成数据丢失的根因。唯一可以阻断的是：热榜数据源全部不可用（采不到任何东西）。其余所有情况——字段缺失、部分来源失败、非标代码——一律保存并打标记。判定数据好坏是下游的事，不是采集器的事。

**2. 设计文档要短，实施计划要更短。** 810 行设计文档导致注意力分散到影子数据集、对比审计、守护进程等次要问题上，忽略了最核心的调度器和质量门禁。如果用 50 行写完"后端定时采集 → 存 MongoDB"，不会漏掉代码审计。

**3. 禁止"any→all"类的语义偏差。** 设计写"全为"意味着 `all()`，实现写成了 `any()`。任何涉及集合条件判断的代码，必须在 Code Review 时对着设计文档逐行比对。

**4. 分阶段实施是错的。** 7 个 Phase 把简单问题复杂化。影子验证阶段投入大量精力做 shadow/live 对比、守护进程、自动启动，但这些都无法暴露 `invalid_stock_code` 误阻断的问题——因为 shadow 和 live 共享同一套有 bug 的质量门禁代码。真正有效的是：直接切生产、小范围观察、快速修复。

**5. 新功能上线后必须人工验证第一个完整交易日的数据。** 不能只看 collector 状态 API 返回 `running=true`、`error_count=0`，必须查 MongoDB 确认 frames 实际入库数、stock rows 数量、blocked runs 的 blockingIssues。

**6. 环境变量是运行时命脉，必须和代码一起管理。** `.env.local` 被遗忘在 worktree 里，合并后丢失了 collector 的生产配置，导致调度器停摆了一周才被发现。任何依赖环境变量的服务，必须在合并时同步检查目标环境的配置完整性。

### 后续设计必查清单

在编写任何新方案设计文档之前，必须逐条确认：

- [ ] 核心目标是否可以用 5 句话以内说清楚？
- [ ] 是否有质量门禁/阻断逻辑？→ 删除，改为"保存+打标记"
- [ ] 是否引入了分阶段验证？→ 删除，直接生产小范围观察
- [ ] 是否有独立守护进程/计划任务？→ 删除，集成到主进程生命周期
- [ ] 是否定义了新的 MongoDB 集合/API/CLI？→ 问自己：没有这个能不能工作？
- [ ] 所有条件判断函数的语义是否正确？→ 逐行对比设计文档的"任一/全部/至少"措辞
- [ ] 环境变量是否有默认值？默认值是生产安全还是开发便利？
- [ ] 第一个上线日有没有人工验证计划？（查 MongoDB，不只看 API status）
