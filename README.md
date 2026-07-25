# Dragon Board

Dragon Board 是一个面向 A 股热榜、市场情绪、题材轮动、龙头识别、RankTrend 分析和量化研究的个人工作台。这个仓库不是单一前端项目，而是由根 Vue 看板、股票数据代理、本地行情桥、通达信 / QMT L2 探针和 QuantBoard 量化研究子项目共同组成。

根项目负责实时看板、热榜聚合、快照采集、前端 RankTrend golden 输出和 QuantBoard 桥接。回测、优化、参数搜索、交易模拟和报告展示统一归属 `quant-board/`。

## 项目组成

```text
/
├── src/                     # Dragon Board 根 Vue 3 + TypeScript 看板
├── proxy-server/            # Node.js 股票数据 HTTP 代理，默认端口 3000
├── python-bridge/           # mootdx + WebSocket 本地行情桥，默认端口 8765
├── tools/                   # 启动器、TdxL2Helper、隔离探针和辅助工具
├── quant-board/             # Python QuantBoard，量化研究、回测、优化和报告主链
├── docs/                    # Dragon Board 根项目文档
├── skills/                  # 项目级 AI 协作 skill 与 workflow 文档
└── e2e/                     # Playwright 端到端测试
```

### 根 Vue 看板

根项目是 Dragon Board 的单页工作台，使用 Vue 3、TypeScript、Vite、Pinia 和 ECharts。核心入口包括：

- `src/App.vue`：主页面和面板装配入口。
- `src/components/panels/**`：业务面板。
- `src/services/dataLoader.ts`：八平台热榜加载、清洗、合并和综合排名。
- `src/services/DataLayer.ts`：运行态内存数据层，只保存内存状态、版本和订阅通知。
- `src/services/RankTrendAnalyzer.ts` 与 `src/services/rankTrend/**`：前端 RankTrend 分析和 golden 标准。
- `src/services/snapshot/**`：快照保存、读取、覆盖率、备份和 QuantBoard 后端适配。
- `src/services/quantBoardBridge.ts` 与 `src/services/quantBoardGolden/**`：Dragon Board 到 QuantBoard 的数据桥和 golden 导出。

根项目不承载回测平台职责。任何回测、优化、交易模拟和报告展示都应放入 `quant-board/`。

### proxy-server

`proxy-server/` 是本地股票数据代理服务，用于把前端请求转发到外部数据源，并处理跨域、编码、cookie 和缓存等问题。默认监听：

```text
http://localhost:3000
```

根 Vite 开发服务通过 `/api` 代理到该服务。

### python-bridge

`python-bridge/` 是本地 `mootdx + WebSocket` 行情桥，默认提供：

```text
ws://127.0.0.1:8765/ws/quotes
```

当前真实能力边界：

- 已跑通：`7709 / L1 + 标准五档 + 本地 WebSocket`。
- QMT L2 作为更高优先级的合法 Level2 接入方向，已有探针和 provider 入口。
- 未完成：`7719 / 真 L2 十档 / 真 L2 逐笔`。
- 当前五档行情不能描述成官方客户端级 L2。
- `TDX_L2_USERNAME`、`TDX_L2_PASSWORD` 只是预留变量，不代表已实现真实 L2 登录。

日常优先用根目录 `DragonBoardLauncher.exe` 启动，它会隐藏启动 bridge，并在 bridge 离线时允许前端回退到 HTTP 备用链路。

### TdxL2Helper

`tools/TdxL2Helper/` 是独立 x86 .NET helper，目标是隔离验证通达信 32 位 DLL、L2 权限状态和深度行情调用面。它不属于根前端运行时，不应把高风险探针直接接入 `python-bridge/main.py` 的默认生产行为。

涉及 `--unsafe-deep-start`、`--unsafe-deep-func-probe` 的操作属于高风险探针，必须确认任务确实需要。

### QuantBoard

`quant-board/` 是 Dragon Board 的量化研究子项目，也是参数研究、回测、优化、交易模拟和报告展示的唯一主链。它的首要目标是把根项目已经稳定运行的 TypeScript RankTrend 分析链迁移到 Python 后端，并形成可导入数据、可复现回测、可比较优化、可查看报告的个人研究平台。

关键口径：

- TypeScript `src/services/RankTrendAnalyzer.ts` 与 `src/services/rankTrend/**` 是 Python 移植的 golden 标准。
- 默认 `snapshot_type` 是 `half_hour`。
- `quarter_hour` 只能由用户显式选择，不能替代默认口径。
- 回测、优化、API、CLI 和前端展示必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- 当前运行主库以 `quant-board/docs/README.md` 和 `quant-board/docs/AI_COLLABORATION.md` 为准；截至当前文档，QuantBoard 已转向 MongoDB 主链，SQLite、Supabase、Parquet 和 IndexedDB 旧链路只作为迁移前历史、审计/离线备份参考或显式禁用入口。
- Dragon Board 正式快照写入和读取只通过 QuantBoard 后端 API；前端不得直连 MongoDB 或 Supabase。
- 数据质量门禁失败必须返回结构化原因，不允许静默吞掉后继续产出看似可用的交易结果。

进入 QuantBoard 任务前先读：

```text
quant-board/docs/README.md
quant-board/docs/AI_COLLABORATION.md
```

## 快速启动

### 根项目前端

```powershell
pnpm install
pnpm dev
```

默认开发地址：

```text
http://localhost:5173
```

构建：

```powershell
pnpm build
```

类型检查：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

### 股票数据代理

```powershell
cd proxy-server
npm install
npm run start
```

### 本地行情桥

推荐：

```powershell
DragonBoardLauncher.exe
```

手工调试：

```powershell
pip install -r python-bridge/requirements.txt
python python-bridge/main.py
```

### QuantBoard 后端

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

常用 CLI：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli list-datasets
```

### QuantBoard 前端

```powershell
cd quant-board\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

默认地址：

```text
http://localhost:5174
```

## 常用验证

根项目通用测试：

```powershell
pnpm test
```

RankTrend 专项：

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

根前端类型检查：

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Playwright：

```powershell
pnpm test:e2e
```

QuantBoard 后端：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
```

QuantBoard 前端：

```powershell
cd quant-board\frontend
npm run build
```

## 目录边界

### 根 `src/`

- `components/**` 负责展示和交互，不直接拼远端 API，不访问服务私有成员，不承载回测/优化逻辑。
- `services/**` 负责业务能力和外部适配，公开 facade/API 给组件使用。
- `stores/**` 只保存应用级和 UI 状态，不替代服务层。
- `types/**` 只放类型、接口、字面量联合类型和类型推导必需的 `as const` 数据。
- `config/**` 放稳定运行时配置、默认参数、存储 key 和业务常量。
- `themes/**` 统一承载主题 TS 配置和 CSS。
- `data/**` 只放静态业务数据或生成数据源。
- `devtools/**` 只服务人工诊断，不被业务代码 import，不作为自动化验收依据。
- `utils/**` 保持无状态、可复用、无领域编排。

不要恢复或新增旧入口：`src/type/**`、`src/constants/**`、`src/router/**`、`src/views/**`、`src/assets/**`，除非先同步修改项目协作指南并说明新职责。

### QuantBoard

- `quant-board/backend/**` 是 FastAPI 后端、回测、优化、数据服务和领域核心。
- `quant-board/frontend/**` 是 QuantBoard 独立前端，默认端口 `5174`。
- `quant-board/data/**` 是本地研究数据、warehouse、staging、reports，默认不提交运行产物。
- `quant-board/docs/**` 是 QuantBoard 架构、API、数据库、优化和协作细则的唯一文档区。

回测、优化、参数搜索、交易模拟、报告展示只放在 `quant-board/**`，不要回流到根项目 `src/services/**`。

## 文档入口

- [AGENTS.md](AGENTS.md)：AI 协作规则、目录边界、业务硬约束和常用命令。
- [SKILLS.md](SKILLS.md)：项目级 skills 使用指南。
- [quant-board/docs/README.md](quant-board/docs/README.md)：QuantBoard 文档中心。
- [quant-board/docs/AI_COLLABORATION.md](quant-board/docs/AI_COLLABORATION.md)：QuantBoard AI 协作硬约束。
- [python-bridge/README.md](python-bridge/README.md)：本地行情桥状态、协议和 L2 边界。
- [tools/TdxL2Helper/README.md](tools/TdxL2Helper/README.md)：x86 helper 构建、探针和当前结论。

## 协作注意事项

- 全程小范围、可验证、可回退。
- 不使用破坏性 Git 命令，例如 `git reset --hard`、`git checkout -- <path>`，除非用户明确要求。
- 不批量删除文件或目录。
- 未提交、未跟踪或已修改文件默认属于用户或其他协作者，不要覆盖、回滚或格式化无关文件。
- 修改默认值、策略合同、API 合同、数据库字段、存储同步、快照入库或恢复策略时，必须同步更新相关专题文档。
- UI 或组件改动必须做真实浏览器验证，不能只靠代码阅读或类型检查声称完成。
- 涉及金融、回测、优化和策略信号的逻辑，必须显式处理空数据、NaN、时间乱序、低样本量、缺字段和类型回退。
