# THSBigOrder 调试归档与 Redis 缓存方案计划

## 目标

归档 2026-07-16 THSBigOrder 双数据源调试记录，重点固化 Longhu 分页真实合同；参照 THS L2 主力资金与 RankTrend Redis 方案，形成 BigOrder Redis TTL 缓存设计。

## 成功标准

1. 调试复盘可独立说明现象、根因、证据、修复和防回归规则。
2. Redis 方案明确正常请求入口、缓存 key、TTL、增量刷新、并发合并、stale、熔断和客户端行为。
3. 方案复用现有 `ProxyRedisCache` / `ProcessMemoryCache`，不把 Redis 依赖引入 WinForms。
4. Redis/语音实施完成后，审计发现的完整性、风控、容量和回归测试缺口全部闭环。
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
- [完成] 12. 用失败测试复现完成度审计中的剩余缺口
- [完成] 13. 补齐 Longhu 缓存完整性、风控、调度、容量与诊断合同
- [完成] 14. 补齐 WinForms last-good 与增量语音边界测试
- [完成] 15. 同步 design/plan/API 文档并运行最终验证和 code review（2026-07-18；自动化增量合同已闭环，真实盘中门禁仍待部署验收）
- [完成] 16. 研究点火、砸盘、买活跃与承接的微观结构口径，完成扩展样本重放并写入正式算法设计；盘中人工验收另列为后续门禁
- [完成] 17. 探测 THS/Longhu 指定交易日历史逐笔能力；确认日期参数被忽略，不实施误导性的主界面日期筛选
- [完成] 18. 按批准设计用 TDD 实现高置信事件 detector、附加 marker 和延迟确认语音；自动化与 7/17 生产重放已通过，盘中准确率待下一交易日人工验收

## 约束

- 保留现有未提交改动，不覆盖、不回滚、不格式化无关文件。
- 2026-07-17 用户已明确授权完成 Redis 与语音剩余实现；继续在当前工作区保留并扩展既有未提交 code-review 修复。
- 不使用破坏性 Git 或批量删除命令。
- `proxy-server/helpers/proxyCache.js` 已包含本功能的 L1/L2 基线；只修改 BigOrder 单值容量所必需的局部逻辑，不改无关 hotlist TTL/格式。
- 提交前逐项核对工作区；本地 DLL、EXE 配置、窗口设置和 `.claude/worktrees/` 不纳入提交。

## Errors Encountered

| 错误 | 尝试 | 处理 |
|---|---|---|
| `superpowers/using-superpowers/SKILL.md` 本机路径不存在 | 首次读取 skill | 改读已安装的 `C:\Users\Think\.codex\skills\using-superpowers\SKILL.md` |
| 最终合同检查脚本把 PowerShell 嵌套数组展开，错误输出 `True: FAIL` | 首次最终合同扫描 | 改用有序哈希表逐项保存布尔值后重新运行；这是验证脚本错误，不是文档合同失败 |
| 使用 `BaseIntermediateOutputPath=obj\ReleaseVerify` 构建 net48 时找不到引用程序集 | 语音计划提交前构建 | 不再重定向中间目录，只用 `OutputPath` 避开正在运行的标准 Release EXE |
| Crossref DOI 直查在当前 PowerShell URL 编码下返回 404 | marker 外部研究首次检索 | 改用 Crossref 标题检索并以 DOI、期刊和出版社元数据交叉核对，不重复相同请求 |
| Semantic Scholar 匿名 API 连续返回 429 | marker 论文摘要检索 | 停止访问该源，改用 OpenAlex、Crossref 与出版页；不把空响应当研究证据 |
| OpenAlex 搜索请求超时；OUP DOI 落地页返回 403 | marker 论文正文检索 | 改用公开 arXiv/SSRN 版本和 Crossref DOI 元数据，引用时明确区分原文结论与工程推导 |
| marker 阈值敏感性脚本对每秒反复全表过滤，30 秒超时 | 本地样本参数扫描首版 | 改为按秒聚合、前缀和/滑动窗口，避免重复 O(n²) 扫描 |
| 扩展归档重放按 6 列解析时遇到缺失时间字段 | 17 只股票样本重算首版 | 先统计并跳过非 6 列/非法时间/非法价格行，输出丢弃数量后再计算；数据清洗进入算法合同 |
| THS 历史日期探测基线和紧凑日期请求分别在 15/30/35 秒超时 | 三次独立探测 | 保留成功的 `date=2026-07-16` 对照作为有效证据；它仍返回 `2026-07-17`，不再以增加超时重复请求 |
| grep.app 返回 429，百度公开搜索两次超时 | 历史 action/参数公开检索 | 停止依赖不稳定搜索渠道；以真实上游响应中的权威行日期判定当前合同，不猜测未证实参数 |
| C# runner 的既有快速切源测试两次偶发等待 Longhu 超时 | marker GREEN 全量回归 | 同一代码新鲜复跑通过，失败发生在 Longhu stub 调用前且 detector 尚未执行；记录为既有非稳定时序，不修改算法或扩大本轮范围 |
| 32 位 PowerShell 重放两次无法实例化 provider/解析 HttpClient 类型 | 生产 detector 重放工具 | 显式选择 `(HttpClient,string)` 构造器并加载 `System.Net.Http` 后成功；未修改业务代码 |
| 优化后重放脚本用整数构造 GZipStream 产生重载歧义 | 性能复测工具 | 恢复显式 `CompressionMode.Decompress` 后成功；未修改业务代码 |
