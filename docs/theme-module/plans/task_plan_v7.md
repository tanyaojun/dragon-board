# 题材模块优化升级方案 V7：Legacy Adapter 瘦身与调用面清零

## 目标

- 删除 `rotationService` 和 `sectorAnalyzer` 内部不可达旧计算逻辑。
- 保留旧公开 API 和 window 全局对象，但只作为 `themeFacade` 的兼容 adapter。
- 新代码不再从 `sectorAnalyzer/rotationService` 获取题材事实。

## 实施内容

- `rotationService` 缩为 thin adapter：只消费 `themeFacade.refreshRuntime()` 的 rotation summary，保留定时分析、lastAnalysis、主线联动触发和旧返回结构。
- `sectorAnalyzer` 缩为 legacy adapter：保留成分股懒加载、标签同步、leader 同步和旧 API；删除旧热度计算、旧 JXBK 热度更新、旧板块预警逻辑。
- `config/factors`、`ContextBuilder`、算法预热依赖改为读取 `themeFacade`。
- `SectorRotation` 移除 `rotationService.forceAnalyze()` 防御 fallback。

## 验证

- 新增 legacy adapter 测试、题材因子配置测试和 Dragon ContextBuilder 测试。
- 回归运行 `pnpm test`、`pnpm test:ranktrend`、`vue-tsc` 和 `git diff --check`。

## Review Gate

- 完成后保持未提交状态。
- 用户 review 通过后再提交。
