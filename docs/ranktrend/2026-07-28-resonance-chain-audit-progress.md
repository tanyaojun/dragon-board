# 共振强度数据链路核查进度

## 2026-07-28

- 已读取项目规则与 skills 指南。
- 已启用 systematic-debugging，按端到端边界取证。
- 已确认主工作区存在大量相关未提交修改，后续保留并基于当前状态审计。
- 已建立本次核查计划。
- 已读取 QuantBoard README/AI 协作规范及 2026-07-26 共振设计与实施计划。
- 已提取设计公式、输入字段、样本不足和 live-only 边界。
- 已通过代码搜索和相关 diff 建立 collector → Mongo → RankTrend → 页面字段的初步映射。
- 已核对页面展示字段、当前帧去重和共振窗口点数。
- 已逐项对照设计核对共振公式、方向覆盖、新入榜和时间轴质量逻辑。
- 已核对 Mongo attention rank 的全帧重排、totalCount、API 参数和前端百分位方向。
- 已确认 Python collector 与前端均榜公式、平台权重和默认名次完全一致。
- 端口枚举首次超时，已切换轻量检查方式。
- 已确认 3000/8000/8765 服务监听和 Quant API 12:00 后重启事实；继续区分 run state 与 scheduler state。
- 已通过 `/api/health` 和 scheduler status 确认调度器正在运行、无错误、无逾期缺槽。
- Mongo/API 查询首次因 PowerShell 搜索字符串解析失败，已调整命令。
- frames API 确认今日上午 5 个半小时槽位均存在；开始做 Mongo 精简字段审计。
- 已完成今日五个半小时槽位的 frame/rows/排名字段/provenance/run 精确审计。
- 已用当前真实启动缓存只读验证 provider：221 行完整，公式零偏差。
- 已用真实 context 验证 builder 与 quality gate，不丢字段、不误阻断。
- 已统计真实 rank-series：最新四帧共同覆盖 156 只、bar 合法，但公共 frame 并集异常扩大到 498。
- 已发现 scheduler 直写可能绕过 Redis 快照缓存失效，进入根因确认。
- 已确认 Critical：scheduler 直写后不失效默认 2 小时的 RankTrend Redis 缓存。
- 已完成缓存失效 TDD 修复，collector 与 FastAPI ingest 共用同一失效函数。
- 已完成 per-code 并集污染全市场时间轴的 TDD 修复，同时保留个股历史与缺帧门禁。
- 为加载新代码停止旧 Quant API；启动管理器 30 秒未自动拉起，转为手动恢复服务。
- Quant API 于 12:54:24 恢复，scheduler 运行正常。
- 13:00 三种槽位自然采集完成；half_hour 221 行排名合同与公式生产验收通过。
- rank-series 首次重载、二次缓存命中均包含 13:00，缓存链闭环。
- 定向验证：Python 271 passed；前端 48 passed；vue-tsc 与 git diff --check 退出码 0。
