# Dragon Board Skills 使用指南

本文定义 `dragon-board` 项目中 Codex/Superpowers skills 的推荐使用方式。项目入口规则仍以根目录 `AGENTS.md` 为准；本文只补充“遇到什么任务时应启用哪些 skills”。

项目级 skill 正文、模板、引用材料和工作流清单统一放在根目录 `skills/`。根 `SKILLS.md` 只保留总索引和使用指南；后续新增的 `SKILL.md` 不再散落到根目录、`docs/`、`src/`、`quant-board/` 或个人 `.codex/skills` 路径中。

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

### 3.3 `frontend-design`

用于前端页面、组件、面板、仪表盘、表格、图表、视觉美化和交互体验改造，目标是避免泛化、低辨识度的 AI 式界面。

典型场景：

- 用户指出界面“不好看、没质感、和参考图差距大、对比度/字体/颜色不好”。
- 新增或重做 Dragon Board 面板、弹窗、工作台、数据表、图表或工具栏。
- 修改 QuantBoard 前端报告页、优化任务页、参数面板或数据可视化。
- 需要形成明确视觉方向，例如工业金融、暗色数据工作台、精致极简、高密度交易台等。

使用要求：

- 在 `brainstorming` 阶段先明确用途、用户、视觉方向、密度、字体、颜色层级和状态反馈。
- 实现时优先匹配项目现有 Vue/TypeScript/CSS 组织方式，不为视觉效果引入大型依赖。
- 视觉创意不能牺牲金融工作台的可读性、扫描效率、对比度和状态辨识度。
- 和 `ui-ux-pro-max` 同用时，`frontend-design` 负责视觉方向和质感，`ui-ux-pro-max` 负责系统化 UI/UX 规则、可访问性、颜色/字体/布局检查。
- UI 改动必须结合浏览器真实渲染验证；有响应式风险时检查桌面和移动端截图、横向溢出和控制台错误。

### 3.4 计划自审和工程审查

`autoplan / plan review` 与 `plan-eng-review` 在本项目中默认作为人工审查阶段，不假定存在同名可调用 skill。

计划自审检查：

- 需求是否完整，目标和非目标是否清楚。
- 范围是否过大，是否需要拆成多个可独立验证的子项目。
- 验收标准是否可测，是否有明确命令或浏览器检查路径。
- 是否涉及文档、数据合同、默认值、存储/API 或跨子项目同步。

工程审查检查：

- 文件边界和模块职责是否符合 `AGENTS.md`。
- 是否绕过公开 facade/API、把业务逻辑塞进组件或 Pinia。
- 是否过度抽象、引入不必要依赖或混入无关重构。
- 测试策略是否覆盖关键行为和边界条件。
- 是否触碰 RankTrend golden、快照、QuantBoard、存储/API 或 TDX L2 能力边界。

### 3.5 计划落盘

遇到需要计划落盘的任务时，优先使用项目内 `skills/` 中沉淀的计划模板或说明；如本地同时安装了 `planning-with-files` skill，应遵循其流程并把项目级长期计划、阶段状态和验收清单落到仓库内合适位置，避免上下文压缩、会话中断或多轮协作后丢失状态。

典型场景：

- 任务横跨根前端、QuantBoard 后端、数据库/API 文档或多轮实现。
- 需要分阶段推进 RankTrend golden、快照入库迁移、优化任务主链或 UI 工作台改造。
- 用户希望暂停后继续，或者后续可能由不同 agent 接手。
- 计划中包含多个验收命令、风险项和回退点。

使用要求：

- 计划文件应放在合适文档目录，根项目放 `docs/`，QuantBoard 任务放 `quant-board/docs/`。
- 文件内容至少包含目标、范围、影响文件、阶段清单、验证命令、当前状态和未决问题。
- 更新计划时只改对应计划文件，不在根目录新增一次性草稿。
- 文件计划不能替代源码、测试和专题文档；合同变化仍要同步正式文档。

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

### 4.3 多视角 Code Review

较大改动后优先使用 `superpowers:requesting-code-review`；如果用户明确允许并行 agent 审查，再结合可用的子 agent 或项目内 `skills/` 中的 review 流程做多视角审查。若工具支持置信度过滤，应优先处理高置信度、高影响面问题，避免被低置信度假阳性牵着走。

典型场景：

- RankTrend、快照、QuantBoard、存储/API 或质量门禁出现多文件改动。
- UI 面板、服务 facade、后端 API、文档合同同时变化。
- 准备提交 PR、合并分支或交付复杂功能前。

使用要求：

- Review 输入必须包含需求、diff 范围、关键业务约束和已运行验证命令。
- 问题按 Critical、Important、Minor 处理；Critical 和 Important 不应跳过。
- 对不符合项目事实的 review 建议，使用 `receiving-code-review` 的原则验证和反驳。
- Code Review 只审查质量，不替代 `verification-before-completion`。

## 5. 实现后整理 Skills

### 5.1 实现后简化

代码实现完成、测试通过后，可以按本节规则或项目内 `skills/` 中的简化流程做一次人工简化检查，确认是否存在可以安全简化的重复逻辑、过长函数或局部复杂度。

典型场景：

- 同一模块内出现重复的字段映射、边界判断、格式转换或错误处理。
- 新功能为赶进度写出临时分支逻辑，需要回看是否能收束。
- 测试已经覆盖关键行为，可以安全做小范围整理。

使用要求：

- 只能合并真实重复、稳定重复的逻辑；不要为了抽象而抽象。
- 不跨业务边界抽象，例如不要把 RankTrend、快照、QuantBoard 回测的不同口径强行合成一个通用函数。
- 不把业务配置、默认参数或主题配置移动到不符合 `AGENTS.md` 目录职责的位置。
- 简化后必须重新运行受影响测试和类型检查。

## 6. Git 和 GitHub 仓库管理

Git/GitHub 操作必须先遵守 `AGENTS.md` 的工作区保护规则：不回滚用户改动、不使用破坏性 Git 命令、不批量删除文件或目录。

### 6.1 推荐使用的 Skills

- 提交或 PR 前：使用 `superpowers:verification-before-completion`，先运行能证明改动正确的验证命令。
- 大改动准备合并前：使用 `superpowers:requesting-code-review`，审查 diff、需求符合度和潜在回归。
- 多 agent 或多视角审查：优先使用 `superpowers:requesting-code-review`，必要时在用户允许后结合可用子 agent 审查，聚焦高置信度、高影响面问题。
- 处理 PR review 或外部建议：使用 `superpowers:receiving-code-review`，先验证建议是否符合本项目架构和业务边界。
- 合并、收尾或分支清理：可按需使用 `superpowers:finishing-a-development-branch`，但必须先确认用户希望我执行 GitHub/分支操作。

### 6.2 允许的常规 Git 检查

```powershell
git status --short
git diff -- <path>
git diff --stat
git log --oneline -n 20
git branch --show-current
git remote -v
```

这些命令只用于了解工作区、diff 和远端状态。发现无关改动时默认视为用户或其他协作者的内容，不覆盖、不格式化、不回滚。

### 6.3 提交前检查

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

### 6.4 禁止或需先确认的操作

- 禁止使用 `git reset --hard`、`git checkout -- <path>` 等会回滚文件的命令，除非用户明确要求。
- 禁止用 Git 命令或 shell 命令批量删除文件。
- 不要自动执行 `git push`、创建 PR、合并 PR、删除分支或改远端配置，除非用户明确要求。
- 不要把 `dist/`、`.tmp/`、`node_modules/`、`coverage/`、`playwright-report/`、`test-results/`、数据库文件或大体积运行产物提交进仓库。
- 如果需要处理冲突、rebase、merge 或历史改写，先说明当前状态、风险和建议路径，再等用户确认。

### 6.5 GitHub PR 和 Review

创建或更新 PR 前：

- 先运行 `verification-before-completion` 对应验证。
- 较大改动先跑 `requesting-code-review`。
- PR 描述应包含改动摘要、验证命令和影响范围。
- 如果 review 涉及 API、数据库、快照合同、RankTrend golden 或 QuantBoard 存储策略，必须同时检查相关文档是否需要更新。

收到 review 后：

- 使用 `receiving-code-review` 逐条理解、验证和处理。
- 对错误或不适合本项目的建议，给出技术性说明。
- 对已修复项，说明改动位置和验证结果。

## 7. UI 和浏览器验证 Skills

### 7.1 浏览器和 Playwright 验证

遇到需要浏览器真实渲染、交互验证、截图或 Playwright 自动化的任务时，按本节规则或项目内 `skills/` 中的浏览器验证流程执行。

典型场景：

- 修改 `src/components/**`、`src/App.vue`、主题样式、面板布局或交互状态。
- 修改 QuantBoard 前端页面、报告展示、优化任务 UI 或 API 代理配置。
- 需要验证移动端/桌面端布局、文本是否溢出、按钮是否可点击、图表是否渲染。
- 修复只有浏览器中才能复现的问题。

使用要求：

- 优先用 Playwright 脚本验证关键用户路径，并在必要时截图。
- 若应用需要 dev server，应先启动对应服务并报告本地 URL。
- 检查桌面和移动端关键视口；有图表、canvas 或复杂面板时确认非空渲染和无明显遮挡。
- 浏览器验证不能替代单元测试和类型检查；UI 改动完成前仍需运行对应构建或类型验证。

## 8. 推荐组合

### 明确 bug 或测试失败

```text
systematic-debugging
test-driven-development
verification-before-completion
```

### 新功能或行为变更

```text
brainstorming
autoplan / plan review
writing-plans
计划落盘
plan-eng-review
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
autoplan / plan review
writing-plans
计划落盘
plan-eng-review
test-driven-development
requesting-code-review
verification-before-completion
```

### UI 或前端交互改动

```text
brainstorming
frontend-design
ui-ux-pro-max（需要系统化 UI/UX 检查时）
autoplan / plan review
writing-plans（多步骤或高风险 UI 改动）
plan-eng-review
test-driven-development
浏览器和 Playwright 验证
verification-before-completion
requesting-code-review
```

### UI 美化或视觉质感问题

```text
brainstorming
frontend-design
ui-ux-pro-max
test-driven-development（结构/视觉合同或行为变化）
浏览器和 Playwright 验证
verification-before-completion
```

### GitHub PR 或合并前

```text
verification-before-completion
requesting-code-review
receiving-code-review
```

### 发布或交付前

```text
verification-before-completion
requesting-code-review（较大改动）
finishing-a-development-branch（需要分支收尾或合并时）
```

### 实现后整理

```text
实现后简化
test-driven-development
verification-before-completion
```

## 9. 项目级验证速查

- 普通 Vue/TypeScript 改动：`pnpm test`，必要时运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- RankTrend 改动：`pnpm test:ranktrend` 和 `pnpm typecheck:ranktrend`。
- QuantBoard 后端改动：在 `quant-board` 目录运行 `.\.venv\Scripts\python.exe -m pytest`。
- QuantBoard 前端改动：在 `quant-board\frontend` 目录运行 `npm run build`。
- 文档-only 改动：检查相关文档与 `AGENTS.md`、源码常量、API/数据库口径是否一致。
- UI/浏览器交互改动：结合浏览器和 Playwright 验证运行关键路径检查和必要截图，再运行相关构建或类型检查。

## 10. 不适合用 Skills 代替的事项

- Skills 不能覆盖用户明确指令。
- Skills 不能绕过 `AGENTS.md` 的删除、Git 和目录边界限制。
- Skills 不能作为业务事实来源；业务事实以源码、根 `docs/`、`quant-board/docs/` 和当前测试为准。
- Skills 不能替代真实验证命令。
