# THSBigOrder 调试归档与 Redis 缓存方案计划

## 目标

归档 2026-07-16 THSBigOrder 双数据源调试记录，重点固化 Longhu 分页真实合同；参照 THS L2 主力资金与 RankTrend Redis 方案，形成 BigOrder Redis TTL 缓存设计。

## 成功标准

1. 调试复盘可独立说明现象、根因、证据、修复和防回归规则。
2. Redis 方案明确正常请求入口、缓存 key、TTL、增量刷新、并发合并、stale、熔断和客户端行为。
3. 方案复用现有 `ProxyRedisCache` / `ProcessMemoryCache`，不把 Redis 依赖引入 WinForms。
4. 本轮只修改文档，不修改 `tools/THSBigOrder` 或 `proxy-server`。
5. 外部对抗性审计中的每一项都有明确判定，成立项同步进入 design/plan，过程记录不再声称未实际落地的结论。
6. Redis 增量刷新后，WinForms 语音只播报本次新进入的符合条件大单，不因全天快照重复播报，也不再固定截断为最近两条。

## 阶段

- [完成] 1. 检查工作区、近期改动和运行产物
- [完成] 2. 追踪数据源到 UI 的完整调用链
- [完成] 3. 复现并验证单一根因假设
- [完成] 4. 汇总结论和最小修复建议
- [完成] 5. 核对 Longhu 当前实现、真实分页合同和既有调试记录
- [完成] 6. 对比 THS 主力资金与 RankTrend Redis 缓存模式
- [完成] 7. 写入调试复盘和 BigOrder Redis 缓存设计
- [完成] 8. 文档自审、链接与工作区范围验证
- [完成] 9. 核验外部对抗性审计并修订 design/plan/关联文档
- [完成] 10. 核对现有语音调用链，补充增量播报合同、TDD 任务和验收标准
- [完成] 11. 复核全部待提交 diff，运行文档验证并按明确范围提交

## 约束

- 保留现有未提交改动，不覆盖、不回滚、不格式化无关文件。
- 当前仅归档和设计，不实施 Redis 或语音代码改造。
- 不使用破坏性 Git 或批量删除命令。
- 不修改用户已有的 `proxy-server/helpers/proxyCache.js` 未提交改动。
- 提交前逐项核对工作区；本地 DLL、EXE 配置、窗口设置和 `.claude/worktrees/` 不纳入提交。

## Errors Encountered

| 错误 | 尝试 | 处理 |
|---|---|---|
| `superpowers/using-superpowers/SKILL.md` 本机路径不存在 | 首次读取 skill | 改读已安装的 `C:\Users\Think\.codex\skills\using-superpowers\SKILL.md` |
| 最终合同检查脚本把 PowerShell 嵌套数组展开，错误输出 `True: FAIL` | 首次最终合同扫描 | 改用有序哈希表逐项保存布尔值后重新运行；这是验证脚本错误，不是文档合同失败 |
| 使用 `BaseIntermediateOutputPath=obj\ReleaseVerify` 构建 net48 时找不到引用程序集 | 语音计划提交前构建 | 不再重定向中间目录，只用 `OutputPath` 避开正在运行的标准 Release EXE |
