# Dragon Board AI 协作指南

本文是 `dragon-board` 仓库的后续代理入口文档，替代旧的 `PROJECT_CONTEXT.md`。进入本项目后，应先阅读本文，再按任务范围读取对应专题文档和源码。

## 1. 基本协作原则

- 全程使用中文沟通，结论先行，说明问题、原因、改法和影响面。
- 先读代码和现有文档，再下结论；不要凭历史印象修改业务逻辑。
- 每次改动保持小范围、可验证、可回退，不做与当前任务无关的大重构。
- 尊重工作区现状：未提交、未跟踪或已修改文件默认属于用户或其他协作者，不要覆盖、回滚或格式化无关文件。
- 禁止使用破坏性 Git 命令，例如 `git reset --hard`、`git checkout -- <path>`，除非用户明确要求。
- 禁止批量删除文件或目录。不得使用 `del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`。如需删除文件，只能一次删除一个明确路径的文件。

## 2. 项目定位

`dragon-board` 是股票热榜、市场情绪、题材轮动、龙头识别、排名趋势和量化研究的综合工作台。仓库不是单一前端项目，而是由多个子系统组成：

- 根项目：Vue 3 + TypeScript + Vite 前端，提供 Dragon Board 主看板。
- `src/services/**`：核心业务层，包含数据加载、数据层、分析器、快照和 QuantBoard 桥接。
- `proxy-server/`：Node.js 股票数据代理服务，默认端口 `3000`。
- `python-bridge/`：本地 `mootdx + WebSocket` 行情桥，默认提供 `ws://127.0.0.1:8765/ws/quotes`。
- `tools/TdxL2Helper/`：独立 x86 .NET helper，用于通达信 DLL、L2 权限和深度行情探针。
- `quant-board/`：Python QuantBoard 子项目，用于 RankTrend golden 对齐、数据导入、回测、优化和报告展示。

根目录 `README.md` 仍有 Vue 模板残留，不能作为唯一事实来源。涉及 QuantBoard 时，以 `quant-board/docs/README.md` 和 `quant-board/docs/AI_COLLABORATION.md` 为准。

## 3. 关键目录

```text
/
├── src/                    # Dragon Board 主前端源码
│   ├── components/          # Vue 组件和业务面板
│   ├── services/            # 核心业务逻辑层
│   ├── stores/              # Pinia 状态
│   ├── type/ types/         # TypeScript 类型与默认值
│   └── main.ts              # 应用入口和 window 服务挂载
├── docs/                   # Dragon Board 主项目文档与历史方案
├── proxy-server/            # 本地 HTTP 代理服务
├── python-bridge/           # 通达信行情 WebSocket 桥
├── tools/                   # 原生 helper 和启动器
├── quant-board/             # Python 量化研究子项目
└── e2e/                    # Playwright 端到端测试
```

核心前端服务优先从这些文件定位：

- `src/services/DataLayer.ts`：中心化内存数据层和 IndexedDB 快照基础。
- `src/services/dataLoader.ts`：八平台热榜加载、清洗、合并和综合排名。
- `src/services/RankTrendAnalyzer.ts`：前端 RankTrend 分析入口。
- `src/services/rankTrend/**`：RankTrend 拆分后的 golden 标准模块。
- `src/type/rankTrendDefaults.ts`：RankTrend 默认参数和默认快照类型。
- `src/services/quantBoardBridge.ts`：Dragon Board 与 QuantBoard 的 IndexedDB/Golden 桥接。
- `src/services/quantBoardGolden/**`：仅用于导出 TypeScript golden case，不承载回测、优化或交易模拟。
- `src/services/snapshot/**` 与 `src/services/quality/**`：快照质量、覆盖率和门禁。

## 4. 业务硬约束

### 4.1 Dragon Board 主项目

- 默认 RankTrend 快照类型来自 `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`，当前为 `half_hour`。
- RankTrend 默认运行参数来自 `DEFAULT_RANK_TREND_RUNTIME_CONFIG`，不要复制旧文档中的过期参数。
- 快照、策略信号和 QuantBoard 桥接逻辑必须显式处理空数据、NaN、时间乱序、低样本量、缺字段和类型回退。
- 数据质量门禁失败时必须返回结构化原因，不允许静默吞掉并继续产出“看似可用”的交易结果。
- 面板层应通过公开服务 API 调用业务逻辑，不要调用服务私有成员或绕过已有数据层。
- Dragon Board 根项目不承载回测平台职责；涉及回测、优化、参数搜索、交易模拟和报告展示的功能统一放在 `quant-board/`。

### 4.2 QuantBoard 子项目

QuantBoard 的规则以 `quant-board/docs/README.md`、`quant-board/docs/AI_COLLABORATION.md` 和专题文档为准：

- TypeScript `src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/**`、`src/type/rankTrendDefaults.ts` 是 Python 移植的 golden 标准。
- QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
- 原 `src/services/strategyBacktest` 职责已迁移到 QuantBoard Python 后端：`backend.analysis.ranktrend`、`backend.core.backtest`、`backend.services`。
- 默认 `snapshot_type` 是 `half_hour`；`quarter_hour` 只能由用户显式选择，不能替代默认口径。
- 回测、优化、API、CLI 和前端展示必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- QuantBoard 存储主链为 SQLite 主库 + Supabase 后端备份库；存储、同步、恢复和冲突规则以 `quant-board/docs/database-migration-plan.md` 为准。
- Dragon Board 正式快照写库必须走 QuantBoard 后端 `POST /api/snapshots/ingest`；历史 JSON/IndexedDB 迁移入口为 `POST /api/migrations/snapshots/import-json`，IndexedDB 只保留为迁移源、缓存或失败重放来源。
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

1. 先用 `rg` 定位相关文件、调用链和测试，不要先全局改动。
2. 阅读与任务直接相关的文档。QuantBoard 任务至少先看 `quant-board/docs/README.md` 和 `quant-board/docs/AI_COLLABORATION.md`。
3. 给出简短计划：问题、原因、改法、影响文件和验证方式。
4. 修改时保持最小范围，优先复用现有服务、类型、工具函数和测试模式。
5. 改完运行必要验证；如果验证受环境限制无法运行，明确说明原因和未覆盖风险。
6. 最终回复包含：改动摘要、验证结果、风险点或后续建议。

## 7. 代码风格

- TypeScript/Vue 使用现有 Vue 3 `<script setup>`、Pinia、Vite 和 `@` 路径别名风格。
- 格式约束参考 `.prettierrc.json`：无分号、单引号、`printWidth=100`。
- 不引入新的框架或大型依赖，除非任务明确要求并说明收益。
- 复杂算法可加少量解释性注释；避免把显而易见的赋值写成注释。
- 对金融、回测、优化类逻辑，优先保证可复现、可解释和边界条件明确。
- Python 代码要保持模块名清晰，对个人开发者友好；新增服务优先落在 `quant-board/backend/**` 的现有分层中。

## 8. 文档维护规则

- 根 `AGENTS.md` 只放跨项目入口规则、当前口径和常用命令。
- Dragon Board 主项目细节写入根 `docs/`。
- QuantBoard 细节写入 `quant-board/docs/`，不要散落到后端或前端 README 中。
- 发现旧文档仍把 Dragon Board 根项目描述为回测平台时，应删除或改为当前 QuantBoard 口径。
- 修改默认值、策略合同、API 合同或数据表字段时，必须同步更新相关专题文档。
- 修改存储、同步、快照入库、数据库表字段、Supabase payload、恢复策略或 API/CLI 请求响应字段时，必须同批更新相关文档；QuantBoard 相关改动至少检查 `quant-board/docs/database-migration-plan.md`、`quant-board/docs/architecture.md`、`quant-board/docs/api-cli.md` 和 `quant-board/docs/AI_COLLABORATION.md`。

## 9. 测试与验收优先级

- UI 或组件改动：至少运行相关构建或类型检查；有交互风险时补充浏览器验证。
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
