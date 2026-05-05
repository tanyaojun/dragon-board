# 题材模块文档索引

本目录归档题材模块 V1-V7 重构过程中的计划、审计发现和实施记录。

## 当前口径

- 题材模块运行态主链以 `ThemeRuntimeCoordinator.refreshRuntime()` 为权威入口。
- `themeFacade` 是 UI、服务层、预警和调试读口的统一 facade。
- `sectorAnalyzer/rotationService/alertService` 继续保留旧公开 API，但运行态事实来源均已降级为 `themeFacade` 兼容 adapter。
- QuantBoard schema 和回测主链在 V6 不再扩展，沿用 V2 已落地的稳定字段和执行开关。

## 文件说明

- `findings.md`：审计发现、残留调用和后续清理边界。
- `progress.md`：V1-V7 实施过程日志归档。
- `plans/`：各版本执行计划归档。

## 后续维护

- 新的题材模块方案、审计报告和实施计划继续放在本目录。
- 不再把 `task_plan*.md`、`findings.md`、`progress.md` 放在仓库根目录。
- 若形成可复用 agent 工作流，应单独沉淀到根目录 `skills/`，不要混入业务文档。
