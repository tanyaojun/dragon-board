# 手工诊断脚本

本目录只放浏览器控制台或临时开发诊断脚本，不属于自动化测试套件。

## 使用规则

- 文件名使用 `*Diagnostic.ts` 或描述性工具名，例如 `dataQualityChecker.ts`。
- 不使用 `.test.ts`、`.spec.ts` 后缀。
- 不放在业务目录的 `__tests__` 下。
- 需要纳入 CI/Vitest 的用例，应迁移到被测模块旁边的 `__tests__/*.test.ts`。

## 当前脚本

- `runAllDiagnostics.ts`：聚合运行手工诊断。
- `configServiceDiagnostic.ts`：配置存储手工诊断。
- `refreshManagerDiagnostic.ts`：刷新管理手工诊断。
- `dataQualityChecker.ts` / `dataQualityDiagnostic.ts`：数据质量检查工具和入口。
- `integrationDiagnostic.ts`：应用集成状态诊断。
- `dragonDiagnostic.ts`：龙头相关手工诊断。
- `validateRankTrendAnalyzer.ts` / `verifyRankTrendAnalyzer.ts`：RankTrend 浏览器侧验证脚本。
