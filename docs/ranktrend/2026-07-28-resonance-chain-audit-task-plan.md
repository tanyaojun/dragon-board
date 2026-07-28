# 共振强度数据链路核查计划

## 目标

确认当前行情主页“共振强度”从八平台热榜原料、半小时快照、MongoDB 读模型、RankTrend 算法到页面展示的数据链条完整，且计算口径与 2026-07-26 设计一致。

## 成功标准

1. 每个有效槽位保存八平台原始名次、派生排名字段和 `rankProvenance`。
2. MongoDB frame/stock rows 数量一致，读取后按真实槽位时间升序进入算法。
3. TypeScript 与 Python 对同一输入序列输出一致，共振强度公式与设计一致。
4. 行情主页展示值确实来自最新 RankTrend 结果，刷新、缓存与非交易时段行为可解释。
5. 仅运行受影响的定向测试与数据库检查，不跑全量测试。

## 阶段

| 阶段 | 状态 | 验证 |
| --- | --- | --- |
| 1. 读取设计、QuantBoard 规则和当前 diff | 完成 | 已提取公式、边界和工作区改动 |
| 2. 追踪采集、写入、读取、计算、展示链路 | 完成 | 各层输入输出与公式已可追溯 |
| 3. 检查当前 MongoDB 槽位和调度状态 | 完成 | 13:00 自然槽位生产验收通过 |
| 4. RankTrend 算法与定向测试 | 完成 | live-only TS 公式与定向测试通过 |
| 5. 修复确认的缺陷并复验 | 完成 | 缓存失效与市场质量窗口 TDD 转绿 |
| 6. 汇总结论与剩余风险 | 完成 | 已记录完整链路、生产证据和启动器风险 |
| 7. 排查定时刷新后全表共振归零 | 完成 | per-code 联集误作市场时间轴，已拆分正式 marketFrames 合同并回归验证 |

## 约束

- 不运行全量 tests。
- 不覆盖工作区既有改动。
- 采集器除完全采不到股票外必须保存并打质量标记。
- 历史 11:30 回填是盘后当前缓存代理值，不冒充原始精确值。

## Errors Encountered

| 错误 | 尝试 | 处理 |
| --- | --- | --- |
| PowerShell `Get-NetTCPConnection` 组合检查超过 10 秒 | 1 | 改用 `netstat -ano` 与直接 HTTP 健康接口 |
| `GET /health` 返回 404 | 1 | 读取 FastAPI 实际根健康路由，不重复猜测路径 |
| PowerShell 将 `@router` 正则误解析为语法 | 1 | 拆成简单关键词搜索后重试，只读 API 尚未据此下结论 |
| Windows 路径参数不接受 `test_snapshot_collector_*` 通配形式 | 1 | 改用目录 + `-g` 过滤定位 provider 测试 |
| Windows 路径参数不接受 `quant-board\\.env*` 通配形式 | 1 | 拆分 collector 引用、main 缓存实现和 settings 默认值查询 |
| PowerShell 截断带双引号的 `rg` 正则 | 1 | 改用无引号关键词分别搜索 service 测试 |
| 停止旧 Quant API 后启动管理器 30 秒内未自动拉起 | 1 | 午休窗口内按同一 uvicorn 命令手动隐藏启动，并复核 scheduler |
| 读取 proxy startup bundle 未命中，未取得代码集 | 1 | 不重复请求，改从可用代理热榜接口或 Mongo 最近 frame 提取代码 |
