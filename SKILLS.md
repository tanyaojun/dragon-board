# Dragon Board Skills 使用指南

本文定义 `dragon-board` 项目中 Codex/Superpowers skills 的推荐使用方式。项目入口规则仍以根目录 `AGENTS.md` 为准；本文只补充“遇到什么任务时应启用哪些 skills”。

## 1. 基本原则

- 先遵守 `AGENTS.md`：中文沟通、先读代码和文档、小范围修改、禁止破坏性 Git 命令、禁止批量删除文件或目录。
- Skills 用来约束工作流程，不替代项目业务规则。
- 涉及 RankTrend、快照、QuantBoard、数据质量门禁、存储/API 合同和 TDX L2 能力边界时，必须先确认现有源码和文档口径。
- 不能用“应该可以”作为交付结论；完成前必须用对应验证命令拿到新鲜结果。

## 2. 核心必备 Skills

### 2.1 `superpowers:systematic-debugging`

用于任何 bug、测试失败、构建失败、接口异常、数据异常或非预期行为。

典型场景：

- `pnpm test`、`pnpm test:ranktrend`、`vue-tsc`、`pytest` 失败。
- RankTrend 前后端结果不一致。
- 快照读取、写入、迁移、覆盖率或质量门禁异常。
- QuantBoard optimization job 状态、结果或持久化异常。
- Dragon Board 与 QuantBoard 桥接数据缺字段、NaN、时间乱序或样本不足。
- TDX bridge、proxy-server 或行情数据链路异常。

使用要求：

- 先复现，再定位根因，不能先猜测式修复。
- 先读错误、调用链、近期改动和相似工作代码。
- 多组件问题要沿边界收集证据，例如前端 facade、后端 API、数据库、job runner。
- 修复必须针对根因，不做顺手重构。

### 2.2 `superpowers:test-driven-development`

用于实现功能或修复 bug，尤其是会影响业务计算、数据合同或边界条件的改动。

典型场景：

- RankTrend 算法、默认参数、golden case 或输出字段变化。
- 快照 facade、ingest、frames、records、stock rows、sector rows 相关逻辑。
- 数据质量门禁、覆盖率、空数据、NaN、时间乱序和低样本量处理。
- QuantBoard 回测、优化、交易规则、随机种子和任务状态。
- 任何修复需要防止回归时。

使用要求：

- 优先补最小失败用例，再实现修复。
- 测试放在被测模块邻近的 `__tests__/*.test.ts`，QuantBoard 按现有 Python 测试结构归类。
- 不为了测试方便绕过公开 facade 或服务边界。
- 金融和回测逻辑测试要覆盖空数据、样本不足、成本、T+1、止损止盈、随机种子等关键边界。

### 2.3 `superpowers:verification-before-completion`

用于每次准备声称“完成、修好、通过、可交付”之前。

典型验证命令：

```powershell
# 根项目前端通用
pnpm test
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false

# RankTrend
pnpm test:ranktrend
pnpm typecheck:ranktrend

# QuantBoard 后端
cd quant-board
.\.venv\Scripts\python.exe -m pytest

# QuantBoard 前端
cd quant-board\frontend
npm run build
```

使用要求：

- 必须运行能证明当前结论的完整命令。
- 必须读取退出码和失败数量，不能只看部分日志。
- 不能用旧运行结果、局部检查或“看起来没问题”代替验证。
- 如果环境限制导致无法验证，最终回复必须明确说明未验证项和风险。

## 3. 设计和范围控制 Skills

### 3.1 `superpowers:brainstorming`

用于新功能、行为变更、UI/交互设计和需求不清的任务。

典型场景：

- 新增市场情绪、题材轮动、快照管理、优化任务或报告展示面板。
- 改变 RankTrend 信号解释、快照正式入库策略、数据质量门禁或 API 合同。
- 设计 Dragon Board 与 QuantBoard 的新桥接能力。
- 用户只给出方向，需要先确认目标、边界和验收标准。

不优先使用的场景：

- 明确 bugfix。
- 明确测试或类型错误。
- 小范围字段补齐、文档修正或按现有模式补参数。

使用要求：

- 先读项目上下文，再提问。
- 提出 2-3 个方案和取舍。
- 设计获得确认后，再进入计划和实现。

### 3.2 `superpowers:writing-plans`

用于多步骤、跨模块或高风险改动的实现计划。

典型场景：

- 同时涉及根前端、QuantBoard 后端、数据库/API 文档的改动。
- 需要迁移存储、调整快照合同、修改 RankTrend golden 或优化任务主链。
- 任务需要拆成可验证阶段。

使用要求：

- 计划必须包含影响文件、改动顺序、测试策略和回退风险。
- 每个阶段都要有明确验收命令。
- 不把无关重构混入计划。

## 4. Review Skills

### 4.1 `superpowers:receiving-code-review`

用于处理用户、同事、外部 AI 或工具给出的 review 意见。

典型场景：

- 用户贴出多条 review comment 要求处理。
- 外部建议修改架构、恢复旧链路、移动业务逻辑或新增依赖。
- Review 意见可能和 `AGENTS.md`、QuantBoard 文档或现有业务边界冲突。

使用要求：

- 先理解和验证 review 意见，不盲目实现。
- 对不符合项目口径的建议要技术性说明原因。
- 多条意见中有不清楚的，先澄清再批量处理。
- 正确意见按优先级逐项修复并验证。

### 4.2 `superpowers:requesting-code-review`

用于较大改动完成后主动做审查。

典型场景：

- 完成 RankTrend、快照、QuantBoard、存储/API 或质量门禁改动后。
- 准备合并较大功能前。
- 多文件修改涉及跨模块合同或业务口径时。

使用要求：

- 先整理实现范围、需求来源和 diff 边界。
- Critical 和 Important 问题必须处理或说明原因。
- Review 不能替代测试，最终仍要执行 `verification-before-completion`。

## 5. Git 和 GitHub 仓库管理

Git/GitHub 操作必须先遵守 `AGENTS.md` 的工作区保护规则：不回滚用户改动、不使用破坏性 Git 命令、不批量删除文件或目录。

### 5.1 推荐使用的 Skills

- 提交或 PR 前：使用 `superpowers:verification-before-completion`，先运行能证明改动正确的验证命令。
- 大改动准备合并前：使用 `superpowers:requesting-code-review`，审查 diff、需求符合度和潜在回归。
- 处理 PR review 或外部建议：使用 `superpowers:receiving-code-review`，先验证建议是否符合本项目架构和业务边界。
- 合并、收尾或分支清理：可按需使用 `superpowers:finishing-a-development-branch`，但必须先确认用户希望我执行 GitHub/分支操作。

### 5.2 允许的常规 Git 检查

```powershell
git status --short
git diff -- <path>
git diff --stat
git log --oneline -n 20
git branch --show-current
git remote -v
```

这些命令只用于了解工作区、diff 和远端状态。发现无关改动时默认视为用户或其他协作者的内容，不覆盖、不格式化、不回滚。

### 5.3 提交前检查

提交前至少确认：

- `git status --short` 中只包含本次任务应提交的文件。
- `git diff` 已人工读过，未混入无关重构、格式化或本地运行产物。
- 已按改动类型运行对应验证命令。
- 文档、测试和实现的业务口径一致。

提交建议使用非交互命令：

```powershell
git add <明确文件路径>
git commit -m "<type>: <简短说明>"
```

不要使用会把所有改动一并纳入的命令，除非用户明确要求并且已确认工作区没有无关改动。

### 5.4 禁止或需先确认的操作

- 禁止使用 `git reset --hard`、`git checkout -- <path>` 等会回滚文件的命令，除非用户明确要求。
- 禁止用 Git 命令或 shell 命令批量删除文件。
- 不要自动执行 `git push`、创建 PR、合并 PR、删除分支或改远端配置，除非用户明确要求。
- 不要把 `dist/`、`.tmp/`、`node_modules/`、`coverage/`、`playwright-report/`、`test-results/`、数据库文件或大体积运行产物提交进仓库。
- 如果需要处理冲突、rebase、merge 或历史改写，先说明当前状态、风险和建议路径，再等用户确认。

### 5.5 GitHub PR 和 Review

创建或更新 PR 前：

- 先运行 `verification-before-completion` 对应验证。
- 较大改动先跑 `requesting-code-review`。
- PR 描述应包含改动摘要、验证命令和影响范围。
- 如果 review 涉及 API、数据库、快照合同、RankTrend golden 或 QuantBoard 存储策略，必须同时检查相关文档是否需要更新。

收到 review 后：

- 使用 `receiving-code-review` 逐条理解、验证和处理。
- 对错误或不适合本项目的建议，给出技术性说明。
- 对已修复项，说明改动位置和验证结果。

## 6. 推荐组合

### 明确 bug 或测试失败

```text
systematic-debugging
test-driven-development
verification-before-completion
```

### 新功能或行为变更

```text
brainstorming
writing-plans
test-driven-development
verification-before-completion
requesting-code-review
```

### 收到 review 意见

```text
receiving-code-review
systematic-debugging
test-driven-development
verification-before-completion
```

### 跨 Dragon Board 与 QuantBoard 的改动

```text
brainstorming
writing-plans
test-driven-development
requesting-code-review
verification-before-completion
```

### GitHub PR 或合并前

```text
verification-before-completion
requesting-code-review
receiving-code-review
```

## 7. 项目级验证速查

- 普通 Vue/TypeScript 改动：`pnpm test`，必要时运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- RankTrend 改动：`pnpm test:ranktrend` 和 `pnpm typecheck:ranktrend`。
- QuantBoard 后端改动：在 `quant-board` 目录运行 `.\.venv\Scripts\python.exe -m pytest`。
- QuantBoard 前端改动：在 `quant-board\frontend` 目录运行 `npm run build`。
- 文档-only 改动：检查相关文档与 `AGENTS.md`、源码常量、API/数据库口径是否一致。

## 8. 不适合用 Skills 代替的事项

- Skills 不能覆盖用户明确指令。
- Skills 不能绕过 `AGENTS.md` 的删除、Git 和目录边界限制。
- Skills 不能作为业务事实来源；业务事实以源码、根 `docs/`、`quant-board/docs/` 和当前测试为准。
- Skills 不能替代真实验证命令。
