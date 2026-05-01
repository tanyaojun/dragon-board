# AI 协作规范

本文是 QuantBoard 项目的固定协作合同。后续 AI 助手进入项目时，必须先读本文件和 [README.md](README.md)，再根据任务读取相关专题文档。

## 当前首期方案

- 项目目标：把 dragon-board 的 `rankTrend` TypeScript 分析链落地为 Python 后端可回测、可优化、可展示的 QuantBoard。
- Golden 标准：`src/services/RankTrendAnalyzer.ts`、`src/services/rankTrend/*`、`src/type/rankTrendDefaults.ts`。
- 当前主链：QuantBoard 负责参数研究、回测、优化、交易模拟和报告展示。
- Dragon Board 根项目只提供实时看板、快照数据和 TypeScript golden 导出。
- 默认快照：`snapshot_type=half_hour`。
- 可选快照：`quarter_hour` 可用于细颗粒度研究，但必须显式选择，不能替代默认口径。

## 工作边界

当任务明确限定为文档时：

- 只修改 `quant-board/docs/**`。
- 不修改 `quant-board/backend/**`、`quant-board/frontend/**`、根项目 `src/**`。
- 如发现代码和文档不一致，先记录在文档中，不主动改代码。

当任务允许实现时：

- 先定位现有模块和测试，再做最小改动。
- 不回滚、不覆盖他人正在修改的文件。
- 如果发现未跟踪或已修改文件，默认认为是用户或其他协作者的工作成果。

## 回答风格

- 全程中文。
- 结论先行，说明问题、原因、改法、影响面。
- 面向个人开发者，Python 后端概念要解释清楚，尽可能展开相关教学。
- 不用空泛建议；每次输出都要能指导下一步实现或验收。

## 硬约束

1. `rankTrend` TypeScript 是 golden 标准。
2. QuantBoard 是参数研究、回测、优化、交易模拟和报告展示的唯一主链。
3. 默认 `snapshot_type` 是 `half_hour`。
4. `quarter_hour` 是可选项，不是默认项。
5. 回测和优化必须保存 `random_seed`、`config_hash`、`dataset_id`、`snapshot_type`、`strategy_version`。
6. 数据质量门禁失败必须结构化返回，不允许静默吞掉。
7. Python 端 rankTrend 输出字段必须能和 golden case 对齐。
8. 前端展示不得把 `finalSignal` 当成唯一交易结论，应优先展示状态、候选分层、风险、样本质量和交易解释。

## 推荐执行流程

1. 定位：用 `rg` 或目录列表确认相关文件。
2. 对齐：确认当前任务涉及哪篇 docs 专题文档。
3. 计划：说明要改什么、为什么、影响哪些文件。
4. 落地：只改必要范围。
5. 验证：文档任务至少检查链接、关键词和文件列表；代码任务运行相关测试。
6. 总结：列出改动文件、验证结果、剩余风险。

## 文档维护规则

- README 只放总览、索引和首期硬约束。
- 专题细节写入对应文档，不把所有内容堆到 README。
- 修改默认值、策略合同、API 合同时，必须同步更新交叉引用文档。
- 发现旧文档把 Dragon Board 根项目描述为回测平台时，必须删除或改为当前 QuantBoard 口径。

## 给后续 AI 的上下文提示

开始新任务时优先阅读：

1. [README.md](README.md)
2. [ranktrend-golden.md](ranktrend-golden.md)
3. [ranktrend-python-port.md](ranktrend-python-port.md)
4. 与任务直接相关的专题文档

如果用户要求实现首期功能，推荐顺序是：

1. 数据导入与质量门禁；
2. golden case 生成与校验；
3. Python rankTrend 移植；
4. 回测引擎；
5. API/CLI；
6. 前端展示；
7. 参数优化。
