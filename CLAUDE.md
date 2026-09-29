# Dragon Board — Claude Code 入口

本项目的完整规则在仓库根目录，**动手前必须先读**：

1. `d:\dragon-board\AGENTS.md` — 项目规则、目录边界、业务硬约束（§4.0 数据链路禁止硬门禁为最高优先级）、常用命令、设计前自检清单
2. `d:\dragon-board\SKILLS.md` — skills 索引：遇到什么任务启用哪些 skill

读完这两个文件之前，不要回复用户、不要执行任务、不要调用除 Read 之外的任何工具。

## Claude Code 专属

- 项目级 skill 正文在 `skills/<name>/SKILL.md`；启用的外部 skill（superpowers 等）按 `SKILLS.md` 索引执行。
- 前端改网页/组件/表格/面板/交互后，交付前必须用 `playwright-cli` 做真实浏览器验收（渲染、字段值、控制台错误、必要截图），不能只靠单测和类型检查。
- 工作流门禁（brainstorming → 计划自审 → writing-plans → 工程审查 → TDD → QA → ship）见 `AGENTS.md` §6。
- Git/删除/工作区保护、`src/` 与 `quant-board/` 目录边界、QuantBoard 存储与快照合同、TDX L2 能力边界一律以 `AGENTS.md` 为准，本文件不另立规则，避免双份事实源漂移。
