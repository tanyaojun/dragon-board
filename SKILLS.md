# Dragon Board Skills 使用指南

本文定义 `dragon-board` 项目中「遇到什么任务启用哪个 skill」。项目入口规则以根目录 `AGENTS.md` 为准（优先级最高）；本文只做索引与使用指南，不另立业务规则。

项目级 skill 正文统一放 `skills/<name>/SKILL.md`（references/templates/scripts 随子目录）；新增 skill 不散落到根目录、`docs/`、`src/`、`quant-board/` 或个人 skill 路径。项目 skill 由 Codex / Pi 共用（Codex 接口配置见各 skill 的 `agents/openai.yaml`）。

## 1. 调用方式（Pi）

- Pi 通过项目 `.pi/settings.json` 的 `"skills": ["../skills"]` 自动发现项目 skill：启动时只注入 name + description，任务匹配时再读 `SKILL.md` 全文执行。
- 强制加载用 `/skill:<name>`（如 `/skill:fail-visible-data-pipelines`）；编辑 skill 后 `/reload` 刷新。
- 通用流程 skill 在用户级 `~/.pi/skills/`（跨项目共享）：brainstorming、writing-plans、executing-plans、systematic-debugging、test-driven-development、using-git-worktrees、subagent-driven-development、writing-skills、playwright。
- Skills 约束工作流程，不替代项目业务规则：不能覆盖用户明确指令，不能绕过 `AGENTS.md` 的删除、Git 和目录边界限制。
- 业务事实以源码、根 `docs/`、`quant-board/docs/` 和当前测试为准；skill 不是业务事实来源，也不能替代真实验证命令。

## 2. 项目级 Skills（`skills/`）

### 2.1 `fail-visible-data-pipelines`（数据链路强制）

凡涉及数据采集、清洗、写库、同步、迁移、缓存、读取、查询、回放、分析或界面观察，且需要处理缺字段、低覆盖率、部分来源失败、NaN、时间乱序、低样本或 fallback 时，**设计和编码前必须先读本 skill**（AGENTS §4.0 最高优先级）。它优先于通用的 defense-in-depth 输入拒绝模式：先识别所有可能丢弃、隐藏、归零或裁剪数据的分支再实现；质量异常保存并打标、不阻断；派生结论可停产，原始数据与缺失位置必须保留可观察；测试证明部分异常仍写入、仍可读取、仍可展示。

### 2.2 `single-source-of-truth`（设计门禁）

设计、评审或规划任何可能在 Dragon Board 前端与 QuantBoard 后端之间创建/保留/复制事实源的改动（数据池、快照生产、热榜合并、业务口径、分析算法、派生指标）时使用。核心：新算法/口径/采集默认落后端，前端只消费展示；双源只允许「保留面/迁移面」两类且须登记；方案文档必须显式回答三问（消除还是新增双源/权威侧与收敛路径/前端独立演化是否让目标原理性不可达）。现状盘点唯一登记处：`docs/single-source-of-truth-architecture.md`。

### 2.3 `playwright-cli`（浏览器验收，含 e2e 纪律）

修改 `src/components/**`、`src/App.vue`、主题样式、面板布局、交互状态，或 QuantBoard 前端页面/报告/优化 UI 后，交付前必须用本 skill 做真实浏览器验收（渲染、字段值、控制台错误、必要截图），不能只靠单测和类型检查。Windows/PowerShell 命令速查、环境准备（5173 主看板 / 5174 QuantBoard / 3000 / 8000）、标准验收流程、常见坑都在 skill 正文。

E2E 组织纪律（原 `e2e-verification` skill 已并入本 skill）：主代理单线程直接执行、不派发子代理；先测试后 e2e；证据先于结论，对照验收清单逐条留证（DOM/SVG/样式值、Console 错误分类、截图路径）后才可声称完成。

### 2.4 `ranktrend-signal-research`（信号研究流程）

RankTrend 信号参数长测与因子算法研发：Track A 参数线 / Track B 因子算法线 / 统一收口（判定卡 → saEx 盲区检查 → 交易复核终判 → 一次一候选落默认）。含 golden 锁基线、数据窗口纪律、harness 工程范式与扫描资源纪律。现行章程为分相位验收体系（`quant-board/docs/ranktrend-tier-backtest/ranktrend-phase-acceptance-design.md`）；月度批次模式已封存，前置纪律仍有效。

### 2.5 `a-stock-data`（取数工具包）

仅当任务需要**写代码实际获取** A 股及相关市场数据（行情/K线/逐笔、研报、龙虎榜、资金面、新闻、财务、公告、打板、期货期权、可转债等）时加载；概念解释、投资观点讨论、策略问答等无需取数的话题不要加载。优先用腾讯/交易所官方等不封 IP 源；频控遵守 AGENTS 红线 10（东财已封本机 IP，akshare 永久作废）。

## 3. 通用流程 Skills（用户级 `~/.pi/skills/`）

- **`systematic-debugging`**：任何 bug、测试失败、构建失败、接口/数据异常或非预期行为。先复现再定位根因，先读错误、调用链、近期改动和相似工作代码；多组件问题沿边界收集证据（前端 facade、后端 API、数据库、job runner）；修复针对根因，不做顺手重构。协议/链路异常另遵守 AGENTS 红线 9（先读破译源码）。
- **`test-driven-development`**：实现功能或修复 bug，尤其影响业务计算、数据合同或边界条件的改动（RankTrend 算法/默认参数/golden、快照 facade/ingest/frames、数据质量处理、回测/优化/随机种子）。优先补最小失败用例再实现；测试放被测模块邻近 `__tests__/*.test.ts`（QuantBoard 按现有 Python 测试结构）；不为测试方便绕过公开 facade；金融/回测测试覆盖空数据、样本不足、成本、T+1、止损止盈、随机种子等边界。测试禁调 jev 真实模型（AGENTS 红线 7）。
- **`brainstorming`**：新功能、行为变更、UI/交互设计和需求不清的任务。先读项目上下文再提问，提出 2-3 个方案和取舍，设计确认后再进入计划与实现。明确 bugfix、测试/类型错误、小范围字段补齐不优先使用。
- **`writing-plans` / `executing-plans`**：多步骤、跨模块或高风险改动（存储迁移、快照合同、RankTrend golden、优化主链）。计划必须含影响文件、改动顺序、测试策略、回退风险，每阶段有明确验收命令，不混入无关重构。
- **`using-git-worktrees`**：需要隔离工作区时；隔离边界严格遵守 AGENTS §1.1 硬规则。

**完成前验证（纪律，无独立 skill）**：声称「完成、修好、通过、可交付」之前，必须运行能证明当前结论的完整验证命令（AGENTS §5），读取退出码和失败数量，不能只看部分日志；不能用旧运行结果、局部检查或「看起来没问题」代替验证。环境限制导致无法验证时，最终回复必须明确说明未验证项和风险。

## 4. Git / 工作区保护与验证命令

- Git、删除、临时产物与工作区保护规则一律以 `AGENTS.md` §1 / §1.1 为准（不回滚用户改动、禁破坏性 Git 命令、禁批量删除、明确路径 `git add`、提交前人工读 diff），本文不重复立规。
- 验证命令速查以 `AGENTS.md` §5 为准。补充口径：文档-only 改动检查相关文档与 `AGENTS.md`、源码常量、API/数据库口径一致；UI/浏览器交互改动按 §2.3 做真实浏览器验收后，仍需运行对应构建/类型检查。
