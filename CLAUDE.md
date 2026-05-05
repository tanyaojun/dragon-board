# CLAUDE.md

本文件为 Claude Code（claude.ai/code）在本项目中工作时提供指导。

## 沟通与文档语言

- 全程使用中文与用户沟通交流。
- 所有文档、注释、提交信息使用中文编写。
- 代码标识符（变量名、函数名、类型名）使用英文。

## 项目概览

`dragon-board` 是一个股票市场综合工作台，包含五个子系统：

| 子系统                 | 目录                 | 技术栈                        | 用途                                                         |
| ---------------------- | -------------------- | ----------------------------- | ------------------------------------------------------------ |
| Dragon Board（根项目） | `src/`               | Vue 3 + TS + Vite             | 主看板：热榜、情绪、题材轮动、龙头识别                       |
| 代理服务               | `proxy-server/`      | Node.js                       | 股票数据 HTTP 代理，默认端`3000`                             |
| Python 行情桥          | `python-bridge/`     | Python + mootdx + WebSocket   | 通达信行情数据桥，`ws://127.0.0.1:8765/ws/quotes`            |
| QuantBoard             | `quant-board/`       | Python FastAPI + SQLite + Vue | 回测、优化、参数搜索、报告。后端端口 `8000`，前端端口 `5174` |
| TDX L2 Helper          | `tools/TdxL2Helper/` | .NET 8 x86                    | 通达信 DLL/L2 深度行情探针（L2 尚未生产绪）                  |

根 Vite 开发服务器将 `/api` 代理到 `http://localhost:3000`（代理服务）。QuantBoard 前端代理到 `http://localhost:8000`。

## 常用命令

```powershell
# 根前端
pnpm install
pnpm dev                    # Vite 开发服务器，localhost:5173
pnpm build                  # vite build（不等价于完整类型检查）
pnpm test                   # Vitest：src/**/__tests__/**/*.test.ts
pnpm test:ranktrend         # RankTrend 专项测试
pnpm typecheck:ranktrend    # tsc --noEmit -p tsconfig.ranktrend.json
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false

# 代理服务
cd proxy-server && npm install && npm run start

# Python 行情桥
pip install -r python-bridge/requirements.txt
python python-bridge/main.py

# QuantBoard 后端
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m pytest

# QuantBoard 前端
cd quant-board\frontend
npm install && npm run dev -- --host 127.0.0.1 --port 5174
npm run build
```

## 根 `src/` 架构

```
src/
├── main.ts                  # 应用入口：创建 Pinia，挂载服务到 window，挂载 Vue 应用
├── App.vue                  # 单页工作台根组件，面板装配入口
├── components/
│   ├── common/              # 可复用基础组件（不放股票业务逻辑）
│   └── panels/              # 业务面板 — 只能调用公开服务 API
├── composables/             # Vue 组合式函数 — 只做 UI 状态复用和浏览器交互
├── config/                  # 运行时配置、默认参数、存储 key、稳定业务常量
├── data/                    # 静态/生成的业务数据（不放算法、不放运行时缓存）
├── devtools/diagnostics/    # 手工诊断脚本，排除在测试和类型检查之外
├── services/                # 核心业务逻辑层
│   ├── DataLayer.ts         # 中心化内存数据层（版本、订阅通知、内存状态）
│   ├── dataLoader.ts        # 八平台热榜加载、清洗、合并、综合排名
│   ├── snapshot/            # 快照保存/读取/覆盖率/备份 + QuantBoard 适配
│   ├── rankTrend/           # RankTrend golden 标准模块
│   ├── dragon/              # 龙头/复盘业务规则和兼容投影
│   ├── hotness/             # 个股热度计算
│   ├── quality/             # 数据质量覆盖率和门禁
│   ├── quantBoardGolden/    # TypeScript golden case 导出（不做回测/优化）
│   └── quantBoardBridge.ts  # Dragon Board 与 QuantBoard 桥接
├── stores/                  # Pinia 状态 — 只放 UI/应用状态，不替代服务层
├── themes/                  # 主题 TS 配置 + CSS（含龙族主题）
├── types/                   # TypeScript 类型契约 + 类型推导所需的 as const 数据
└── utils/                   # 纯工具函数（无状态、可复用、无领域编排）
```

**关键规则：**

- 服务层暴露公开 facade；组件不得调用服务私有成员或直接拼远端 API。
- `types/` 放类型、接口和类型推导必需的 `as const` 数据。运行时配置放 `config/`。
- `stores/` 只做 UI 状态；不得将 Pinia 当作持久化层或业务逻辑层。
- 禁止创建 `src/router/`、`src/views/`、`src/assets/`、`src/constants/`、`src/type/` 目录。
- 测试放在被测模块旁的 `__tests__/*.test.ts`。诊断脚本放 `devtools/diagnostics/`。
- `DataLayer.ts` 必须保持窄边界：运行时内存状态、版本号、订阅通知。不放 API 调用、数据库访问、类型定义、常量或回测逻辑。

## QuantBoard `quant-board/` 架构

```
quant-board/
├── backend/
│   ├── main.py              # FastAPI 应用入口
│   ├── analysis/            # RankTrend 分析算法和特征计算
│   ├── api/                 # HTTP API 路由
│   ├── core/                # 回测引擎、交易规则、组合、领域核心模型
│   ├── data/                # SQLite/Supabase schema、仓库、数据访问
│   ├── optimization/        # 参数搜索、优化 runner、搜索空间
│   └── services/            # 后端业务服务编排
├── config/                  # QuantBoard 独立配置（与根 src/config/ 分离）
├── data/                    # 本地研究数据、warehouse、staging、reports（gitignore）
├── docs/                    # QuantBoard 文档（架构、API、数据库、优化等）
├── frontend/                # QuantBoard 独立前端（端口 5174）
└── tests/                   # 跨模块/集成测试
```

**关键规则：**

- 所有回测、优化、参数搜索、交易模拟和报告展示属于 `quant-board/` — 禁止放入根 `src/services/`。
- `src/services/RankTrendAnalyzer.ts` 和 `src/services/rankTrend/**` 是 TypeScript golden 标准，Python 移植必须对齐。
- SQLite 是主存储；Supabase 是备份存储。二者必须按 `quant-board/docs/database-migration-plan.md` 保持 schema 同构。
- 所有链路必须保留：`dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- 默认 `snapshot_type` 为 `half_hour`。`quarter_hour` 只能由用户显式选择。
- 前端展示必须包含候选分层、风险、样本质量和解释 — 禁止把 `finalSignal` 当作唯一交易结论。

## 业务硬约束

- **Golden 对齐**：TypeScript RankTrend 输出是 golden 标准。Python 移植必须产出字段对齐的输出，并通过 golden case 验证。
- **数据质量门禁**：失败时必须返回结构化原因（NaN、Inf、负值、低覆盖率、时间乱序）。禁止静默吞掉脏数据并产出"看似可用"的结果。
- **TDX/L2**：当前桥接使用 `7709 / L1 + 标准五档`。真 L2（7719 / 十档 / 逐笔）尚未生产就绪。禁止将当前能力描述为客户端级 L2。
- **快照持久化**：正式快照必须走 QuantBoard 后端 `POST /api/snapshots/ingest`。IndexedDB 仅作迁移/历史缓存。
- **工作区安全**：禁止使用破坏性 Git 命令（`reset --hard`、`checkout --`），禁止批量删除文件，禁止覆盖用户未提交的改动。

## 代码风格

- Prettier：无分号、单引号、`printWidth: 100`
- Vue 3 `<script setup>`、Pinia、Vite、`@` 路径别名指向 `./src`
- 不引入新框架或重型依赖，除非任务明确要求并说明收益
- 金融/回测逻辑：优先保证可复现、可解释、边界条件明确

## 文档索引

- **`AGENTS.md`** — 完整的跨项目规则、目录边界、工作区约束和详细约定。非简单任务应先阅读此文件。
- **`SKILLS.md`** — 不同任务类型应使用哪些 skills。
- **`docs/`** — Dragon Board 主项目文档和历史方案。
- **`quant-board/docs/README.md`** — QuantBoard 文档中心（架构、API、数据库、优化、golden 对齐）。
- **`quant-board/docs/AI_COLLABORATION.md`** — QuantBoard 专属 AI 协作约束。
