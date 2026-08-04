---
name: e2e-verification
description: Use when UI/组件/面板/表格/图表等前端改动准备声称完成或交付前，需要真实浏览器 e2e 验收（渲染、交互、控制台错误、截图）。e2e 由主代理单线程直接执行（不派发子代理），主 agent 不得仅凭自查结论声称前端改动完成。
---

# E2E 验收流程（主代理单线程执行）

## 核心原则

- UI/前端改动完成 ≠ 代码自查通过；必须按真实浏览器流程验收并带回可复核证据（DOM/SVG/样式、Console、截图）。
- 证据先于结论：验收结果必须包含具体证据，主代理记录后才可声称完成（与 verification-before-completion 一致）。
- 当前环境子代理消息派发不可用，e2e 验收由主代理直接单线程执行，不派发子代理。

## 何时使用

- 修改任何前端页面/面板/表格/图表或交互状态后，交付/声称完成前，包括：Dragon Board 主看板（行情页、各业务面板）、QuantBoard 前端（回测/优化/报告展示）等。
- 需要验证新 skill 或新流程在真实任务上的可操作性（forward-test 同样由主代理执行）。
- 需要复核只在浏览器中出现的现象。

不使用：纯后端/算法改动（跑 pytest）；文档-only 改动；dev server 无法启动的环境。

## 流程

1. **先测试后 e2e**：先跑单元测试与类型检查，通过后再进入浏览器验收。
2. **确认服务**：按验收对象检查 5173（主看板）/5174（QuantBoard 前端）/3000/8000，必要时启动对应 dev server（端口与启动命令见 `skills/playwright-cli/SKILL.md` 环境准备）。
3. **明确验收清单**：目标页面/组件、可验证标准（关键字段/状态/样式/路径）、Console 错误基线、是否需要截图。
4. **执行浏览器流程**：按 `skills/playwright-cli/SKILL.md` 操作：`open` → `snapshot` → `find`/`click` → `eval` 读取证据 → 检查 console → `screenshot`。
5. **逐条核对**：对照验收清单逐项记录证据；不满足项先修复再重新验收。
6. **记录并声明**：声称完成必须引用本次验收证据；结果写入 PR 描述或相关文档。

## 验收清单模板

```text
验收对象：<改动说明>
REQUIRED SKILL: 先读 D:\dragon-board\skills\playwright-cli\SKILL.md 并按流程执行。
服务：<URL>；端口检查：
  Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 3000,8000,5173,5174 }
验收清单：
- <可验证标准 1>
- <可验证标准 2>
输出：逐条证据（DOM/SVG/样式值/文本）、Console 错误数及分类、截图路径。
```

## 常见错误

| 错误 | 后果 | 对策 |
| --- | --- | --- |
| 跳过 playwright-cli skill 直接乱点 | 拿不到稳定 ref、步骤缺失 | 先完整读 skill 再操作 |
| 验收错了服务/端口（5173 vs 5174） | 验的不是目标改动 | 按验收对象选 URL（主看板 5173、回测平台 5174） |
| 只截一张图就当验收完成 | 漏关键状态 | 逐条核对清单并记录证据 |
| 验收结果无证据 | 无法复核 | 记录 DOM/SVG/样式值/console 计数 |
| 在单测/类型检查前验收 | e2e 掩盖代码错误 | 先测试后 e2e |
| 服务未就绪就开跑 | 连接失败浪费时间 | 先确认端口/启动 dev server |
| 把"看起来正常"当结论 | 假阳性交付 | 对照验收清单逐项取证 |

## 与其它规则的关系

- 浏览器操作细节：REQUIRED 使用 `skills/playwright-cli/SKILL.md`。
- 最终声称完成：遵循 verification-before-completion（证据先于结论）。
- 本流程是组织规则（e2e 必须由主代理单线程执行并留证），不替代单元测试、类型检查与 playwright-cli skill。
