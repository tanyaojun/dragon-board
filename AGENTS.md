# Dragon Board AI 协作指南

> 本文件是 Codex / Pi / Claude Code 共享的项目总规则，优先级最高。
> skills 使用指南见根目录 `SKILLS.md`，skill 正文见 `skills/<name>/SKILL.md`。
> Claude Code 的少量差异见 `CLAUDE.md`。

## 0. 开始任务前必做

1. 已读本文件与 `SKILLS.md`；读完前不回复、不动手。
2. 用 `rg` 定位文件、调用链和测试；先读代码与文档再下结论，不凭历史印象改业务逻辑。
3. QuantBoard 任务至少先看 `quant-board/docs/README.md` 与 `quant-board/docs/AI_COLLABORATION.md`。
4. 判定本次改动归属：根前端 / proxy-server / python-bridge / TdxL2Helper / quant-board。
5. 判定是否触碰红线：RankTrend golden、快照默认值、回测口径、存储/同步/API 合同、L2 能力边界。
6. 选定最小验证命令（见 §7），先给出简短计划：问题、原因、改法、影响文件、验证方式。

## 1. 基本纪律

- 中文沟通，结论先行：问题、原因、改法、影响面。
- 每次改动小范围、可验证、可回退，不做无关重构。
- 未提交/未跟踪文件默认属于用户或协作者：不覆盖、不回滚、不格式化。
- 禁止 `git reset --hard`、`git checkout -- <path>` 等回滚命令（用户明确要求除外）。
- 禁止批量删除：不得使用 `del /s`、`rd /s`、`rmdir /s`、`Remove-Item -Recurse`、`rm -rf`；删除只能一次一个明确路径。
- 不自动执行 `git push`、建/合 PR、删分支、改远端，除非用户明确要求。
- 提交前 `git status --short` 与 `git diff` 必须人工读过，只 `git add <明确文件路径>`，不混入无关重构与本地产物。
- 不提交 `dist/ .tmp/ node_modules/ coverage/ playwright-report/ test-results/ *.tsbuildinfo *.exe` 及数据库/大体积产物。

### 1.1 隔离工作区硬规则

启用 worktree 或临时副本后，隔离边界是强约束：

- 默认只在隔离工作区读写任务文件；主工作区仅可只读核对。
- 同一轮任务禁止同时改主工作区与隔离工作区，除非用户明确要求；确需跨工作区必须先停下说明路径、文件清单、回滚方式和验证命令，等确认再动手。
- 任何写入/格式化/删除/`git reset`/测试生成文件/装依赖前，先确认 `pwd` 与 `git rev-parse --show-toplevel` 属于预期工作区。
- 汇报时必须分别给出每个工作区的 `git status --short`，不得用一个工作区的干净状态暗示另一个也干净。

## 1.2 工程硬红线（单一事实源，2026-10-02 增补；对全部 agent 生效）

1. **单一事实源**：同一数据/判定/配置任意时刻只有一个权威来源（§4.2「存储单主链」的通则）。并行双轨/双表只能是临时迁移态，新源上线即删旧源（数据 drop + 代码删除，回退靠 git）；对照数据落 `data/backups/` 文件归档，不进业务库。
2. **git 是代码版本管理唯一工具**：历史与回退只靠 git；禁止版本化文件名（`*_v2.py`、`*_bak.*`、`*_old*` 等）、注释留档、文件副本。改录用 `git mv`，旧代随淘汰删除，不做库内备份集合、不建平行目录。
3. **机密/凭据永不入数据库**：静态凭据只进 `.env.local`/环境变量；动态短时令牌用 Redis 带 TTL 缓存 + 失效显式删除；集合内不得持久化 token/secret/cookie/password。
4. **MongoDB 备份/恢复只走 `mongodump`/`mongoexport`**（产物落 `data/backups/`，gitignore）：禁止在业务库建 backup/对照/试点残留集合；drop 前先导出归档，drop 用单集合显式操作。

## 2. 项目结构

| 目录                 | 职责                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `src/`               | 根 Vue3 + TS + Vite 工作台，业务集中在 `src/services/**`            |
| `skills/`            | 仅 AI 协作流程与 skill 文档，不放业务源码、运行配置、测试夹具、产物 |
| `proxy-server/`      | 本地 HTTP 代理（3000），只做前缀转发与 Windows 服务类路由           |
| `python-bridge/`     | mootdx + WebSocket 行情桥（`ws://127.0.0.1:8765/ws/quotes`）        |
| `tools/TdxL2Helper/` | x86 .NET 通达信 DLL / L2 探针 helper                                |
| `quant-board/`       | Python 量化主链：RankTrend golden、数据导入、回测、优化、报告       |
| `e2e/`               | Playwright 端到端测试                                               |

- 指数/行情/热榜/涨停池/情绪/大单/事件接口已迁至 `quant-board/backend/market_proxy/**`（akshare + httpx 直连），proxy 仅按前缀转发到 8000。
- 新 skill 文档只放 `skills/<name>/SKILL.md`（references/templates/scripts 随子目录），不散落到根目录、`docs/`、`src/`、`quant-board/` 或本机 `.codex/skills`；外部 skill 引入前先整理进 `skills/`。
- 实施计划、阶段进度、审计与复盘不是 skill，放 `docs/<topic>/`（题材用 `docs/theme-module/`）；根目录不留 `task_plan*.md`、`findings.md`、`progress.md`。

### 2.1 `src/` 边界

- `components/**`：只展示与交互，不拼远端 API、不访问服务私有成员、不承载回测逻辑。
- `services/**`：业务与外部适配，公开 facade/API 给组件；私有常量就近放本模块。
- `stores/**`：只放 UI/应用状态，不把 Pinia 当业务服务或持久化层。
- `types/**`：只放类型、接口、字面量联合、`as const`；纯运行时配置去 `config/**`。
- `config/**`：稳定运行配置、默认参数、存储 key；不放主题系统。
- `themes/**`：主题 TS + CSS；不新增 `src/assets/**`。
- `data/**`：只放静态/导入数据；不放生成脚本、算法逻辑、运行态缓存。
- `devtools/diagnostics/**`：人工诊断，不被业务 import，不作自动化验收依据，不用 `.test.ts`/`.spec.ts` 后缀。
- `utils/**`：无状态、可复用、无领域编排；依赖股票业务上下文就移到 `services/**`。
- 不恢复 `src/type/`、`src/constants/`、`src/router/`、`src/views/`、`src/assets/`。

### 2.2 `quant-board/` 边界

- 算法 → `analysis/`（ranktrend、theme）；服务 → `services/`（theme、market）；路由 → `api/`；三者分离。
- 禁止新代码散落 `backend/` 根目录，禁止新增巨型 `services.py`。
- 回测、优化、参数搜索、交易模拟、报告只在 `quant-board/**`，不回流根 `src/services/**`。
- `docs/**` 是 QuantBoard 细节唯一文档区；`data/**` 下数据库/warehouse/reports 属本地状态，遵守 `.gitignore`。
- `.venv/`、`.pytest_cache/` 不是源码目录，不写入目录树、不提交。

## 3. 核心文件定位

- `src/services/DataLayer.ts`：只放运行态内存数据、版本号、订阅通知与内存读写。
- `src/services/dataLoader.ts`：八平台热榜加载、清洗、合并、综合排名。
- `src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/**`：前端 RankTrend 入口、消费契约、live-only 观察层与展示投影。
- `src/types/rankTrendDefaults.ts`：RankTrend 默认参数与默认快照类型（唯一来源）。
- `src/services/snapshot/**`、`src/services/quality/**`：快照读写、覆盖率、质量门禁。
- `src/services/quantBoardBridge.ts` 已移除；QuantBoard 桥接在 `snapshot/**` 与 `theme/**`。

## 4. 业务硬约束

### 4.0 数据链路禁止硬门禁（最高优先级，源自 2026-07 复盘）

- 任何采集、清洗、写库、同步、迁移、缓存、读取、查询、回放、分析、界面观察链路，设计前必须先读 `skills/fail-visible-data-pipelines/SKILL.md`。
- 唯一允许不写入的情形：本轮所有数据源均不可用，没有任何原始记录。其余情况（字段缺失、部分来源失败、非标代码、时间乱序、覆盖率不足）一律保存并打质量标记。
- 质量检查的职责是暴露、聚合、上报、展示；不得把问题静默转成"没有数据""全零结果"或不可恢复丢失。
- 读取/查询/回放/展示同样不得设硬门禁：只要有可用数据，就必须展示原始数据、可计算部分、缺失位置和结构化原因；分析结论可停产或标记不可靠，但不得连带阻断数据链路。
- 禁止用 `0`、空结果、单帧或其他体系评分伪装缺失。
- 测试必须证明：部分异常仍写入、仍可读取、仍可展示；仅全源无数据时才返回采集失败。

### 4.1 Dragon Board 主项目

- RankTrend 默认快照类型取 `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`（当前 `half_hour`）；默认参数取 `DEFAULT_RANK_TREND_RUNTIME_CONFIG`，不复制旧文档过期值。
- `DataLayer.ts` 职责保持极窄：不得新增回类型/接口、默认参数、HTTP 调用、IndexedDB/MongoDB/Supabase 读写、快照导入导出、读模型拼装、回测/优化、业务算法、UI 配置。
- 快照能力一律走 `src/services/snapshot/**` 公开 API，不经 `DataLayer.ts` 中转。
- 快照、策略信号、QuantBoard 桥接必须显式处理空数据、NaN、时间乱序、低样本量、缺字段、类型回退。
- 面板层只调公开服务 API，不绕过数据层、不访问私有成员。
- 自动化测试放被测模块邻近 `__tests__/*.test.ts`，通过 `pnpm test` 运行。
- 不保留 `*-bak.ts`、`*0310.ts` 等历史备份文件，历史对照用 Git。
- 根项目不承载回测平台职责。

### 4.2 QuantBoard 子项目

- RankTrend golden 以 `quant-board/backend/analysis/ranktrend/engine.py` 为生产事实标准；TS 只消费 `POST /api/ranktrend/analyze` 与 frames API，不保留本地 golden 链。
- 默认 `snapshot_type=half_hour`；`quarter_hour` 只能由用户显式选择。
- 回测、优化、API、CLI、前端展示必须保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- **存储单主链 MongoDB**（`dragon_board_quant`，R2 对象备份）：sqlite/Supabase 运行链已于 2026-09-29 物理退役，`storage_backend` 默认 `mongodb`，sqlite 需显式 `QUANT_BOARD_ALLOW_SQLITE_BACKEND=1`（仅限一次性诊断）。**生产/测试硬边界：回测与生产写库只入 `dragon_board_quant`；pytest 数据只入 `dragon_board_test` + Redis 强制 pytest 前缀**（护栏：conftest 三断言、`get_mongodb_database` pytest 护栏、生产入口 startup fail-fast）。测试库为「空结构+基础参照集合」，用 `quant-board/scripts/clone_mongo_test_db.py` 重建。规则以 `quant-board/docs/mongodb-migration-plan.md` 为准，`database-migration-plan.md` 降级为历史档案。
- 正式快照生产写入由 `snapshot_collector`（8001）直写 MongoDB；`POST /api/snapshots/ingest` 仅作手工/离线导入与前端诊断。两条路径共用 `save_snapshot_ingest`，**写入后处理（缓存失效、analyze 落库）必须由该数据层共享 after-save 钩子触发，不得各写一份**。
- 正式快照读口：`GET /api/snapshots/frames|records|stock-rows|sector-rows`；IndexedDB 只作历史迁移源与显式缓存，不新增浏览器端校验/补齐 API。
- 前端展示不得把 `finalSignal` 当唯一交易结论，须展示状态、候选分层、风险、样本质量与解释。

### 4.3 通达信实时行情与 L2

- 已跑通：`7709 / L1 + 标准五档 + 本地 WebSocket`。
- `7719 / 真 L2 十档 / 逐笔` 未完成，不得把当前五档描述成官方客户端级 L2。
- `7719` 与 DLL 探针必须隔离验证，不得改 `python-bridge/main.py` 默认生产行为。
- 依赖 `mootdx`，不恢复 `pytdx`；`TDX_L2_USERNAME/PASSWORD` 只是预留变量。

## 5. 常用命令

```powershell
# 根前端
pnpm test
pnpm test:ranktrend
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false

# proxy-server / python-bridge
cd proxy-server; npm run start          # :3000
python python-bridge/main.py            # ws :8765

# QuantBoard
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backend.cli list-datasets
cd frontend; npm run build              # dev :5174 / preview :4174
```
