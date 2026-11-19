---
name: playwright-cli
description: Use when 需要在真实 Chrome 浏览器中验收或调试 Dragon Board / QuantBoard 前端页面（面板、组件、表格、图表渲染、交互、控制台错误、截图），或其它 AI 协作者需要复现 playwright-cli 打开页面做浏览器验证的工作流时。适用于 Windows/PowerShell 环境；UI 或组件改动交付前必须由主代理单线程做真实浏览器 e2e 验收并留证（含验收纪律与清单模板，原 e2e-verification skill 已并入本 skill）。
---

# Playwright CLI 浏览器验收（Windows / PowerShell）

## 核心要点

- 用 `npx --yes --package @playwright/cli playwright-cli <cmd>` 驱动真实浏览器，CLI 优先，不要为了验证临时写 Playwright test 规格文件。
- 单元测试/类型检查通过 ≠ 页面验收通过；UI/面板/组件改动交付前必须做真实浏览器验收（AGENTS.md 硬性要求）。
- 交互靠 `snapshot` 拿稳定元素 ref（如 `e123`），DOM 变化后 ref 会失效，必须重新 `snapshot`。

## 环境准备

1. 按验收对象确认对应服务：

   | 验收目标 | URL | 启动命令 |
   | --- | --- | --- |
   | Dragon Board 主看板（行情页、各业务面板） | `http://localhost:5173` | 根目录 `pnpm dev` |
   | QuantBoard 前端（回测/优化/报告展示） | `http://localhost:5174` | `cd quant-board\frontend; npm run dev -- --host 127.0.0.1 --port 5174`（预览 4174） |
   | 观察类面板/依赖后端数据的页面 | 需要 proxy 3000 与 QuantBoard API 8000 | 见 AGENTS.md 常用命令 |

   端口检查：

   ```powershell
   Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 3000,8000,5173,5174 }
   ```

2. 未监听时按上表启动对应 dev server（隐藏窗口，避免弹出终端）：

   ```powershell
   Start-Process -FilePath 'pnpm.cmd' -ArgumentList 'dev' -WorkingDirectory 'D:\dragon-board' -WindowStyle Hidden -PassThru
   Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port','5174' -WorkingDirectory 'D:\dragon-board\quant-board\frontend' -WindowStyle Hidden -PassThru
   ```

3. 等端口就绪后再打开页面。本机 dev server 可能只绑定 IPv6 localhost，浏览器地址统一用 `http://localhost:<port>`；确需 127.0.0.1 时用 `--host 127.0.0.1` 重启。

## 常用命令速查

| 命令 | 用途 |
| --- | --- |
| `open <url>` | 打开浏览器并导航 |
| `goto <url>` | 当前会话重新导航（浏览器停留在错误页时用这个） |
| `snapshot` | 抓取页面快照：稳定元素 ref + Console 错误数 |
| `find "文本"` | 在快照中搜索文本/正则，返回匹配节点 |
| `click <ref>` | 点击元素（ref 来自最新快照） |
| `eval "() => ({...})"` | 在页面执行 JS 读取 DOM/样式/SVG 路径（支持 async IIFE） |
| `screenshot` | 截图到 `.playwright-cli/`（已 gitignore，无需清理） |
| `close` | 关闭浏览器会话 |

## 标准验收流程（适用于任意页面/面板）

1. 按验收对象打开页面并等待加载（主看板 5173；QuantBoard 回测平台等用 5174）：

   ```powershell
   npx --yes --package @playwright/cli playwright-cli open http://localhost:5173
   Start-Sleep -Seconds 6
   ```

2. `snapshot` 定位目标区域，`find "关键字"` 快速搜索，再 `snapshot` 拿可交互元素 ref。
3. `click <ref>` 进入目标面板/页面；若该页要调后端 API（如 analyze、frames），等 3~5 秒再继续。
4. 用 `eval` 读取验收清单要求的证据（DOM 文本、SVG path 的 `d`、计算样式、表格行数等；选择器按验收目标确定）：

   ```powershell
   npx --yes --package @playwright/cli playwright-cli eval "() => ({ title: document.querySelector('h2')?.textContent.trim(), rows: document.querySelectorAll('tbody tr').length, cell: document.querySelector('.target-cell')?.textContent.trim() })"
   ```

5. 检查 Console：快照头部显示 `Console: N errors`；打开最新 `.playwright-cli\console-*.log` 确认错误类型。环境性错误（`ws://127.0.0.1:8765` 行情桥 refused、`/api/hotlist-sentiment/ingest` 404）不算回归。
6. `screenshot` 留证；`close` 关闭。

多步交互（点击/切换后逐项读取状态）用 async IIFE：

```powershell
npx --yes --package @playwright/cli playwright-cli eval "async () => { const items = [...document.querySelectorAll('.tab, .row')]; const out = []; for (const el of items) { el.click(); await new Promise(r => setTimeout(r, 120)); out.push({ label: el.textContent.trim(), value: document.querySelector('.target-value')?.textContent.trim() }); } return out; }"
```

## 常见坑

- **ref 过期**：点击/导航/打开抽屉后必须重新 `snapshot`，旧 ref 会失效。
- **选错服务/端口**：主看板是 5173，QuantBoard 回测平台是 5174，预览 4174；按验收对象选 URL，别用混。
- **中文匹配乱码**：PowerShell 管道里 `rg`/`Select-String` 匹配中文不可靠，改用 `find` 或 `eval` 读 DOM。
- **页面一直"正在载入数据..."**：调后端 API 的面板/页面加载需要数秒甚至更久，等待或先探测接口是否就绪再断言，不要立即判定空结果。
- **面板长时间 loading 且没有任何请求发出**：先查请求队列 `window.apiService.getQueueStatus()`；若 high 队列积压且 highCount=2，是 QuantBoard analyze 慢把 2 个 high 并发槽占满，面板的 rank-series/analyze 请求排队等不到——这不是代码改动导致的，等待队列排空或后端恢复后再验收。
- **127.0.0.1 拒绝连接**：dev server 只绑了 `::1`，用 `http://localhost:<port>`。
- **浏览器停留在错误页**：先 `goto <url>` 重新导航，而不是再 `open`。
- **Console 错误甄别**：先看 `.playwright-cli\console-*.log`，区分环境性错误（8765 桥、ingest 404、WebSocket refused）与本次改动引入的 JS 错误。
- **不要用 playwright test 规格文件**：CLI 驱动即可，除非用户明确要求写测试文件。

## 验收标准

- 关键字段/状态/图表在真实浏览器中渲染正确；必要时用 `eval` 读 SVG path、计算样式作为证据。
- 无新增控制台错误；环境性错误单独说明。
- 需要时截图，并在最终回复中给出截图路径。
- 浏览器验证不能替代 `pnpm test` 与类型检查；交付前仍需运行对应构建/类型验证。

## E2E 验收纪律（主代理单线程；原 e2e-verification 并入）

- UI/前端改动完成 ≠ 代码自查通过；交付前必须按真实浏览器流程验收并带回可复核证据（DOM/SVG/样式、Console、截图）。**证据先于结论**：逐条记录后才可声称完成，不得仅凭自查结论交付。
- e2e 验收由主代理直接单线程执行，**不派发子代理**。
- **先测试后 e2e**：先跑单元测试与类型检查，通过后再进入浏览器验收；服务未就绪不开跑。
- 适用：修改任何前端页面/面板/表格/图表或交互状态后（主看板、QuantBoard 前端），交付/声称完成前；新流程 forward-test 与只在浏览器中出现的现象复核同样适用。不适用：纯后端/算法改动（跑 pytest）、文档-only 改动、dev server 无法启动的环境。
- 验收前明确清单：目标页面/组件、可验证标准（关键字段/状态/样式/路径）、Console 错误基线、是否需要截图；不满足项先修复再重新验收，只截一张图不算验收完成。
- 验收结果写入 PR 描述或相关文档；声称完成必须引用本次验收证据。

验收清单模板：

```text
验收对象：<改动说明>
服务：<URL>（主看板 5173 / QuantBoard 前端 5174；端口检查见「环境准备」）
验收清单：
- <可验证标准 1>
- <可验证标准 2>
输出：逐条证据（DOM/SVG/样式值/文本）、Console 错误数及分类、截图路径。
```
