# Backend Snapshot Collector 全量审查计划

## 目标

审查 backend snapshot collector 阶段 1–4 的全部实现与文档，修复确认的 Critical/Important 缺陷，并基于新鲜验证证据判断是否可进入阶段 5。

## 成功标准

- 需求、实现、测试、API/架构文档逐项一致。
- Collector、scheduler、provider、audit、CLI/API 的关键边界无未处理 Critical/Important 问题。
- 修复均有先失败后通过的回归测试。
- 相关测试与 QuantBoard 全量 pytest 通过；若不能通过，明确阻塞项。
- 给出阶段 5 Go/No-Go 及剩余风险。

## 阶段

1. **完成**：读取设计、实施计划、阶段进度和 QuantBoard 协作文档。
2. **完成**：确定审查基线和全部变更文件，建立需求—代码—测试映射。
3. **完成**：逐文件审查并运行基线测试，记录分级问题与根因。
4. **完成**：按 TDD 修复 Critical/Important 问题并同步必要文档。
5. **完成**：复审 diff，运行定向与全量验证。
6. **完成**：按阶段 5 入口条件给出 Go/No-Go 结论。

## 验证命令

- `quant-board\.venv\Scripts\python.exe -m pytest <collector 定向测试>`
- `quant-board\.venv\Scripts\python.exe -m pytest`
- 必要的 CLI/API 冒烟检查

## 约束

- 保留工作区现有未提交改动，不回滚、不批量格式化。
- 只修改可直接追溯到审查结论的代码、测试和合同文档。
- 默认 `snapshot_type=half_hour`；正式快照以 QuantBoard SQLite/后端为主链。

## 错误记录

| 错误 | 尝试 | 处理 |
| --- | --- | --- |
| worktree 无 `.venv`，项目文档命令无法直接运行 | 1 | 改用主工作区只读复用的 `D:\dragon-board\quant-board\.venv\Scripts\python.exe`，被测代码 cwd 仍为目标 worktree |
