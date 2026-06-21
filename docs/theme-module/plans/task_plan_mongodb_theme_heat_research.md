# MongoDB Theme 动态题材热度替代 JXBK 调研计划

## 目标

完整梳理 JXBK 5000 端口、题材运行态、快照 `sectorRows` 与 QuantBoard MongoDB theme 主数据链，形成不让前端直连 MongoDB、尽量保持现有公开合同不变的替代设计。

## 阶段

- [x] 读取项目规则、题材历史文档和 QuantBoard 协作约束
- [x] 梳理 JXBK 当前请求、缓存、运行态刷新和兼容接口
- [x] 梳理 MongoDB theme 集合、后端 API 与前端映射仓库
- [x] 梳理题材因子计算与快照 `sectorRows` 生成/写库链
- [x] 比较替代方案、风险和迁移边界
- [x] 向用户提交设计并确认
- [x] 写入正式设计文档并完成自审
- [ ] 用户审核书面设计

## 当前约束

- Dragon Board 前端不得直连 MongoDB。
- MongoDB theme 集合是题材基础映射事实源；快照事实集合与研究集合不能混入基础映射。
- `ThemeRuntimeCoordinator.refreshRuntime()` 与 `themeFacade` 保持运行态权威入口。
- `sectorAnalyzer` 只保留兼容 adapter 职责。
- 本轮只做调研和设计，不修改业务代码。

## 用户确认口径

- 同时修复 Dragon Board 根前端与 QuantBoard backend collector 两条数据链。
- 题材热度必须基于 MongoDB 映射覆盖的全市场约 4167 只股票，不接受仅热榜股票抽样。
- 全市场题材热度每 5 分钟刷新并缓存；正式 `sectorRows` 仍随 `half_hour`、`daily` 快照写入。
- 全市场基础行情主源必须使用腾讯行情，不能使用东财基础行情。
- 东财接口只提取资金字段；价格、涨跌幅、成交量、成交额、换手率和量比均以腾讯基础行情为准。

## 已确认调用链

1. `ThemeDataService -> GET /api/themes/mapping -> MongoThemeRepository` 提供 239 个题材、12219 条映射、4167 只股票的静态事实。
2. `sectorAnalyzer -> ThemeFacade -> ThemeRuntimeCoordinator -> ThemeFactorEngine` 是前端题材运行态主链。
3. 旧动态数据来自 `JxbkThemeFeed -> apiService theme context -> localhost:5000`，填充 JXBK blocks/stockMap。
4. 前端正式快照由 `snapshot/facade -> builders.buildSnapshotSectorRows()` 把 `jxbkBlocks`、`hotThemes`、`rotationAnalysis` 投影成 `sectorRows`，再经 QuantBoard ingest 写 MongoDB。
5. 独立后端 collector 的 `builder` 只会原样转换 `MarketDataContext.sectors`；当前 provider 装配没有 theme provider，也没有 sector 聚合器，所以 shadow collector 的 `sectorRows` 必然为空。

## 关键风险

- MongoDB theme 是映射，不是动态行情。必须再结合当前股票行情聚合题材热度。
- 前端 `DataLayer` 股票池主要来自热榜，覆盖率远低于 MongoDB 映射的 4167 只股票；直接复用会产生热榜抽样偏差。
- 前端与 Python collector 若各自独立定义热度公式，后续 `sectorRows` 会出现同一时点双口径。
- `jxbk_missing`、`source: static/jxbk/mixed`、`strength/netInflow/momentum` 等字段语义必须随替代源显式调整，不能把合成指标伪装成 JXBK 原始值。
- 腾讯与东财是两次独立采样，必须记录各自时间、覆盖率和批次失败；资金源失败不能静默写成 0。

## 错误记录

| 错误 | 处理 |
| --- | --- |
| 首次合并读取规则文件时工具输出被截断 | 改为按文件、按块读取关键规则和技能正文 |
