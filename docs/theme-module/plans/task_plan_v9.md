# 题材模块 V9：迁移校验工具化 + 题材基础读口彻底收口

## 目标

- 为 QuantBoard `themeDATA.db` 增加只读迁移校验能力，支持 API 和 CLI 对比旧 JSON 源与 SQLite 当前事实。
- 把 `sectorAnalyzer.loadSectorStocks()` 的成分股懒加载、缓存和刷新职责迁入 `JxbkThemeFeed`，`sectorAnalyzer` 退为兼容委托。

## 范围

- 后端新增 `POST /api/migrations/themes/verify-json` 和 `verify-themes --path` CLI。
- 校验输出包含 `ok/expected/actual/mismatches/missingThemes/extraThemes/missingMappings/extraMappings/source`。
- 前端新增 `JxbkThemeFeed.loadSectorStocks()`、缓存统计和清理能力。
- 更新题材模块过程文档与 QuantBoard API/数据库迁移文档。

## 非目标

- 不改题材因子、轮动、预警算法和 UI 布局。
- 不自动修复迁移差异，不自动重新导入。
- 不移除 `sectorAnalyzer` 公开 API 或 window 挂载。

## 阶段

1. **后端 TDD**
   - 扩展 theme 后端测试，先覆盖 verify-json 正常、diff、归一化和 CLI。
   - 运行测试确认红灯。

2. **后端实现**
   - 增加 theme 校验服务方法和 repository 查询支撑。
   - 增加 API 和 CLI 命令。

3. **前端 TDD**
   - 新增/扩展 JXBK feed 与 legacy adapter 测试。
   - 运行测试确认红灯。

4. **前端实现**
   - 将成分股懒加载、缓存、并发复用、DataLayer 写入和 runtime refresh 迁入 `JxbkThemeFeed`。
   - `sectorAnalyzer` 改为委托，保留公开合同。

5. **文档同步**
   - 更新 `docs/theme-module/findings.md/progress.md`。
   - 更新 `quant-board/docs/api-cli.md` 和 `quant-board/docs/database-migration-plan.md`。

6. **验证**
   - `cd quant-board; .\.venv\Scripts\python.exe -m pytest`
   - `pnpm test`
   - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`

## 风险和约束

- 不使用批量删除命令；当前计划不删除文件。
- 校验必须只读，不写 `themeDATA.db`。
- `sectorAnalyzer` 兼容 API 必须继续可用。
