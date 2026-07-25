# 精选板块独立服务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dragon Board 中新增由独立 FastAPI 进程提供的 `http://localhost:5000` 精选板块页面，按上游日期参数读取最近 10 个交易日及指定板块个股，且不写入 MongoDB 或其它持久化存储。

**Architecture:** `backend.selected_blocks_main:app` 与 QuantBoard 8000 主应用完全分离，只依赖 `httpx` 调用 longhuvip，并在 provider 层处理分页和上游数组字段归一化。独立 Vue/Vite 前端只调用 5000 的公开 API；生产运行时由该 FastAPI 应用托管前端 `dist`，DragonBoardLauncher 统一管理进程、端口、状态和打开页面。

**Tech Stack:** Python 3.10+、FastAPI、httpx、pytest、Vue 3、TypeScript、Vite、Vitest、Playwright、.NET 8 WinForms

---

## 1. 实施边界与成功标准

核心目标可以用五句话说明：

1. `localhost:5000` 是独立页面和独立 FastAPI 进程，不挂到 QuantBoard 8000 主应用。
2. 板块当前数据读 `apphq.longhuvip.com`，历史数据读 `apphis.longhuvip.com` 并传 `Date=yyyy-mm-dd`。
3. 最近 10 个交易日由上游实际返回的交易日去重得到，后端按 `offset/limit` 翻译上游分页，前端只使用公开分页合同。
4. 板块与个股只做上游读取和进程内短时缓存，不新增 MongoDB 集合、索引、写入、迁移、备份或降级链路。
5. Launcher 管理 5000 服务的启动、停止、探测、退出回收和打开页面。

验收必须同时满足：

- `GET http://127.0.0.1:5000/api/selected-blocks/health` 返回稳定服务身份 `dragon-board-selected-blocks`，且启动 5000 不要求 MongoDB、Redis、QuantBoard 8000 或 TLS 本地代理在线。
- 历史接口返回 10 个互不重复、倒序排列的真实交易日；切换日期时板块内容随 `Date` 改变。
- 上游结果超过单页时，API 将 `offset/limit` 原样翻译为 `index/st`，前端分页器可到达后续板块和个股页；实时轮询只刷新当前页，不抓取全部数据。
- 点击板块后右侧显示该板块个股；当前已知旧参数返回空列表，因此必须先通过 Task 1 的上游合同门禁。
- 页面有加载、空数据、错误、选中状态，桌面双栏可扫描，移动端无横向页面溢出（表格自身允许横向滚动）。
- `dotnet build` 通过，Launcher 能管理 5000，并保留用户当前 `LauncherForm.cs` 的托盘窗口位置恢复改动。

明确非目标：

- 不修复、不复用旧 `KPL-Win7+.exe`、TLSClient 或 Flask 5000 服务。
- 不修改 `quant-board/backend/main.py` 的 8000 生命周期。
- 不把本功能数据写入 MongoDB、Supabase、SQLite、IndexedDB 或本地 JSON。
- 不修改 RankTrend、快照、回测、优化、根项目 `src/**` 或 3000 代理。
- 不在首版恢复导出、自选板块、通达信跳转和参考站的右键股票操作；但必须实现竞价、即将涨停、风向标、历史折叠、二级板块选择和实时刷新。

## 1.1 参考页面取证与能力地图（2026-07-25）

已用 Playwright 打开 `https://www.59155188.xyz/page-TY-e7jjjz.html?` 并完成 DOM 取证。参考站实际使用自己的带签名 CSV 接口（`ban.csv`、`r88.csv`），不是 longhuvip 的可复用 API；因此只继承交互能力，不复制其请求、脚本或数据源。它的控制台存在 `updateSortIndicator is not defined`，新页面不得继承该错误。

| 区域 | 参考页可验证能力 | 新服务的确定实现 |
|---|---|---|
| 头部 | 竞价、即将涨停、风向标；日期默认当天 | 三个模式按钮传 `mode=auction`、`pre_limit`、`wind_vane`；默认 `auction`，日期使用上海时区当天 |
| 历史 | 倒三角展开/收起十列、每列十条板块 | `history` 返回 10 个去重交易日和每日前 10 条；折叠只影响前端显示，不重新请求 |
| 实时板块 | 八列板块表：板块、强度、主力净额、涨停个数、涨跌幅、300W 大单净额、成交额、量比 | 当天且 API 标记 `isLive=true` 时每 3 秒刷新板块和当前选中板块个股；历史日期完全停止轮询 |
| 二级板块 | 有子板块的行展示三角，菜单选择子板块后更新右表 | provider 从上游 `list_son`/`list_soninfo` 映射 `children`；点击三角仅展开菜单，点击子项才改变 `selectedBlockCode` 并加载其个股 |
| 个股 | 十列：名称、数板、价格、涨幅、人气值、主力净额、成交额、实际流通、量比、竞价金额 | FastAPI 归一化为具名字段，空值以 `null` 返回并由 UI 显示 `-`；不把数组下标泄露给 Vue |

实时状态机固定如下：`selectedDate == shanghaiToday && dashboard.isLive` 时启动单一 3000ms 轮询；改日期、页面卸载或接口返回 `isLive=false` 时立即清除计时器；切换模式时取消当前请求并以新模式重新开始；折叠历史只改变显示，不影响主区刷新。每轮使用 `AbortController` 取消未完成的前轮请求；失败保留上一次成功数据和刷新时间，显示非阻断错误，连续三次失败才暂停轮询并显示“重试”。非交易日不能以页面数据未变化判定轮询失败，首个交易日必须人工确认三次连续成功刷新。

## 2. 文件结构

计划新增：

```text
quant-board/
├── backend/
│   ├── api/selected_blocks_routes.py       # 5000 服务公开 HTTP 合同
│   ├── selected_blocks/
│   │   ├── __init__.py
│   │   ├── models.py                       # 归一化领域模型和响应类型
│   │   ├── provider.py                     # longhuvip 请求、分页、数组字段映射
│   │   └── service.py                      # 10 日聚合、选日、进程内缓存
│   └── selected_blocks_main.py             # 独立 FastAPI 入口和 dist 托管
├── selected-blocks-frontend/
│   ├── src/
│   │   ├── components/AppSidebar.vue
│   │   ├── components/HistoryMatrix.vue
│   │   ├── components/BlockTable.vue
│   │   ├── components/StockTable.vue
│   │   ├── components/WorkspaceToolbar.vue
│   │   ├── __tests__/App.test.ts
│   │   ├── api.ts
│   │   ├── App.vue
│   │   ├── useTheme.ts
│   │   ├── main.ts
│   │   ├── styles.css
│   │   └── types.ts
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── playwright.config.ts
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   └── vite.config.ts
├── scripts/probe_selected_blocks_upstream.py
├── tests/
│   ├── fixtures/selected_blocks/block_page.json
│   ├── fixtures/selected_blocks/stock_page.json
│   ├── test_selected_blocks_provider.py
│   ├── test_selected_blocks_service.py
│   └── test_selected_blocks_api.py
└── docs/selected-blocks.md
tools/
└── DragonBoardLauncher/
    └── SelectedBlocksServiceProbe.cs       # 5000 稳定服务身份探测
```

计划修改：

```text
quant-board/docs/README.md
tools/DragonBoardLauncher/LauncherServices.cs
tools/DragonBoardLauncher/LauncherProcessManager.cs
tools/DragonBoardLauncher/LauncherForm.cs
tools/DragonBoardLauncher/README.md
```

`LauncherForm.cs` 当前已有用户未提交的 `_restoreLocation`、`DesktopLocation`、`BringToFront()` 改动。实施前先运行 `git diff -- tools/DragonBoardLauncher/LauncherForm.cs`，只在服务卡、按钮和 URL 分支附近合并，禁止整文件替换或格式化。

## 2.1 页面布局：左目录、右工作区

页面采用图 2 的后台工作台结构，而不是旧版满宽深色表格：

```text
桌面（>= 1100px）
┌───────────────────────┬──────────────────────────────────────────────────┐
│ 精选板块              │ 顶栏：标题 | 日期 | 竞价/即将涨停/风向标 | 刷新状态 │
│ ───────────────────── │ ───────────────────────────────────────────────── │
│ • 盘中精选            │ 可折叠：10 个交易日题材矩阵                       │
│ • 十日题材            │ ───────────────────────────────────────────────── │
│                        │ 板块目录（34%） │ 个股列表（66%）               │
│ 状态：实时/历史       │                 │                                │
│ 左下：收起目录        │                 │                                │
└───────────────────────┴──────────────────────────────────────────────────┘
```

- 左侧导航固定宽 232px，承载品牌“精选板块”、`盘中精选`、`十日题材` 两个导航项和当前数据状态；它不是第二个数据卡片，也不复制旧板块表。
- 右侧顶栏高度 64px。日期位于标题右侧，三个模式使用紧凑分段控件；历史倒三角是仅图标按钮，位于日期附近，悬停提示“显示/隐藏十日题材”。
- 历史矩阵展开时占右工作区的完整一行，表格水平可滚动；收起后不占垂直空间，且不会影响实时轮询。
- 主数据区是同一工作台内的两列 pane，由细分隔线划分：左列是可选择、可展开二级板块的“板块目录”，右列是随选择同步的“个股列表”。不得再把两个 pane 包进嵌套卡片。
- 浅色模式使用浅中性背景和白色工作面，深色模式使用近黑蓝背景和深灰工作面；两者共用青绿色交互强调色。红色表示上涨/净流入，绿色表示下跌/净流出。边框、表头和次级文本使用各主题的中性色，不使用渐变、圆形装饰或营销式大标题。
- 数据密度优先：12 至 13px 表格字，40px 行高，sticky 表头，数值右对齐，名称左对齐；当前选中板块用 3px 青绿色左边线和浅色底区分，子板块菜单是贴近三角按钮的轻量浮层。
- 移动端（< 768px）侧栏默认收起为窄图标栏，点击菜单按钮打开抽屉；主数据区上下堆叠，历史矩阵和表格仅在自身容器横向滚动，页面根节点不产生横向滚动。

### 主题切换合同

- 主题值只有 `light` 和 `dark`，统一写入 `document.documentElement.dataset.theme`；所有页面颜色通过语义 CSS 变量定义，组件内不得硬编码两套颜色分支。
- 首次访问先读取 `localStorage['selected-blocks-theme']`；值无效或不存在时读取 `prefers-color-scheme`。用户点击后立即写入 localStorage，此后不再被系统主题变化覆盖。
- 主题按钮固定在侧栏底部、收起按钮上方。浅色模式显示月亮图标和“深色模式”，深色模式显示太阳图标和“浅色模式”；图标按钮在侧栏折叠后仍保留 tooltip 和 `aria-label`。
- `index.html` 在 Vue 挂载前用最小同步脚本设置 `data-theme`，避免首屏先亮后暗；该脚本只读主题 key 和 `matchMedia`，不承载其它业务逻辑。
- 两套主题都必须保证选中行、hover、focus、禁用态、错误、加载、红涨绿跌和图表矩阵可辨识；主题切换不触发 API 请求、不重置日期、模式、历史展开状态或选中板块。

## 3. 公开 API 合同

统一成功包络：`{"ok": true, "data": ...}`。统一失败包络：

```json
{
  "ok": false,
  "errorCode": "upstream_contract_changed",
  "message": "板块个股上游返回空列表，当前请求合同尚未确认"
}
```

公开接口：

| 方法与路径 | 参数 | 用途 |
|---|---|---|
| `GET /api/selected-blocks/health` | 无 | 返回 `serviceId=dragon-board-selected-blocks`、版本和进程存活，不访问数据库 |
| `GET /api/selected-blocks/history` | `days=10`、可选 `as_of=yyyy-mm-dd`、`mode=auction` | 对应模式最近 10 个交易日热门题材矩阵 |
| `GET /api/selected-blocks/dashboard` | 可选 `date`、`mode=auction`、`offset=0`、`limit=50` | 左侧板块表、二级板块、实际交易日、`isLive`、刷新时间 |
| `GET /api/selected-blocks/{block_code}/stocks` | 可选 `date`、`mode`、`offset=0`、`limit=80` | 右侧板块或二级板块个股表 |

分页响应固定为：

```json
{
  "items": [],
  "offset": 0,
  "limit": 50,
  "total": 0,
  "hasMore": false,
  "requestedDate": "2026-07-25",
  "tradingDate": "2026-07-24",
  "source": "apphis",
  "isLive": false,
  "refreshedAt": "2026-07-25T09:30:03+08:00"
}
```

日期输入始终保持用户请求的 `requestedDate`；周末或节假日可展示上游返回的最近 `tradingDate`，并明确标记 `isLive=false`，不得偷偷把日期控件改成最近交易日。`isLive` 必须同时满足：请求日和上游 `Day` 均为上海当天、上游更新时间距注入 clock 不超过 90 秒、当前时间处于 09:15-11:30 或 13:00-15:00；盘前、午休、盘后和陈旧响应都为 false，不能只比较 `Day`。

上游错误映射：超时/网络错误为 503 `upstream_unavailable`；非 2xx 为 502 `upstream_http_error`；`errcode` 非成功或字段结构变化为 502 `upstream_contract_changed`；不足 10 个历史交易日为 502 `history_incomplete` 并携带 `foundDays`；非法日期、分页和板块代码为 422 `validation_error`；未知 `/api/**` 为 404 `api_not_found`。FastAPI 的 `RequestValidationError`、`HTTPException` 和未知 API 路由都必须转换为统一失败包络，不能泄露默认 `detail` 结构，也不得把异常转换成 200 空数组。

---

### Task 0: 建立唯一执行工作区门禁

**Files:**
- Read only: `AGENTS.md`
- Read only: `SKILLS.md`
- Read only: `tools/DragonBoardLauncher/LauncherForm.cs`

- [ ] **Step 1: 检查主工作区重叠改动**

```powershell
Set-Location D:\dragon-board
git status --short
git diff -- tools/DragonBoardLauncher/LauncherForm.cs
```

Expected: 明确记录用户 `_restoreLocation` 等现有 diff。该 diff 未提交时，不得自行 stash、提交、复制或回滚；先让用户选择提交现有改动后创建 worktree，或明确授权在主工作区实施。

- [ ] **Step 2: 通过 using-git-worktrees 建立或确认唯一任务工作区**

进入最终获准的工作区后，在每个新 PowerShell 终端先执行：

```powershell
$TaskRoot = (git rev-parse --show-toplevel).Trim()
if (-not (Test-Path (Join-Path $TaskRoot 'AGENTS.md'))) { throw 'Invalid Dragon Board task root' }
Write-Output "TaskRoot=$TaskRoot"
```

Expected: `$TaskRoot` 是唯一允许写入的仓库根。启用 worktree 后，`D:\dragon-board` 主工作区只读；本计划后续所有相对路径均以 `$TaskRoot` 为根，禁止硬编码写回主目录。

- [ ] **Step 3: 记录两个工作区状态**

```powershell
git -C $TaskRoot status --short
git -C D:\dragon-board status --short
```

Expected: 后续每次写入、安装、构建和提交前重复第一条根路径校验；最终分别报告任务工作区和主工作区状态。

---

### Task 1: 确认并冻结 longhuvip 上游合同（阻塞门禁）

**Files:**
- Create: `quant-board/scripts/probe_selected_blocks_upstream.py`
- Create: `quant-board/tests/fixtures/selected_blocks/block_page.json`
- Create: `quant-board/tests/fixtures/selected_blocks/stock_page.json`
- Create: `quant-board/docs/selected-blocks.md`

- [ ] **Step 1: 编写只读探测脚本**

脚本用 `httpx.Client(timeout=10.0)`，固定打印 URL host、请求参数、HTTP 状态、`errcode`、`Count`、`Day`、当前页条数和首条数组长度；不得打印 cookie、token、设备标识或完整响应。板块基线请求固定为：

```python
BLOCK_PARAMS = {
    "c": "ZhiShuRanking", "a": "RealRankingInfo", "apiv": "w26",
    "Type": 1, "Order": 1, "ZSType": 7, "PhoneOSNew": 1,
    "index": 0, "st": 50, "VerSion": 5,
}
```

脚本必须支持 `--date 2026-07-24`、`--mode auction|pre_limit|wind_vane`、`--top-block-stocks` 和 `--children`；后两个参数分别读取指定日第一名板块的个股及 `list_son`/`list_soninfo`。输出必须冻结每种模式的 HTTP method、host、query/body 位置、必要 headers、action 参数、列表容器路径、`Count/Day` 实际类型、上游更新时间字段的路径/格式/时区/精度和数组下标；实测更新时间无法解析为上海时间或精度不足以判定 90 秒新鲜度也触发停止条件。历史板块请求使用 `https://apphis.longhuvip.com/w1/api/index.php` 并增加 `Date`；当日使用 `https://apphq.longhuvip.com/w1/api/index.php`。

- [ ] **Step 2: 运行板块探测并确认日期差异**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
foreach ($mode in 'auction','pre_limit','wind_vane') {
    .\.venv\Scripts\python.exe scripts\probe_selected_blocks_upstream.py --date 2026-07-24 --mode $mode --top-block-stocks --children
    if ($LASTEXITCODE -ne 0) { throw "Upstream contract failed for mode=$mode" }
}
.\.venv\Scripts\python.exe scripts\probe_selected_blocks_upstream.py --date 2026-07-23 --mode auction
```

Expected: 三种模式的板块与个股均为 HTTP 200、`errcode=0`、真实列表非空，子板块 ID/名称可配对；两个历史日期的 `Day` 对应请求交易日且排序内容不同。

- [ ] **Step 3: 确认当前有效的板块个股请求**

以 2026-07-24 返回的第一名板块代码为样本，核对当前客户端或可访问网页的真实网络请求，逐项记录 method、host、query/body、`c`、`a`、`PlateID`、`Type`、`Order`、`index`、`st`、`Date`、必要 headers、响应容器和字段类型。每种头部模式都必须取得可区分、非空的板块与个股真实响应；不能把三个按钮伪装为同一请求。旧合同 `a=ZhiShuStockList_W8&c=ZhiShuRanking` 当前在 `apphq` 和 `apphis` 都返回空列表，不能作为通过证据。

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe scripts\probe_selected_blocks_upstream.py --date 2026-07-24 --top-block-stocks
```

Expected: HTTP 200、`errcode=0`，且 `list` 或已确认的新列表字段至少有一条股票；首条必须能识别股票代码和名称。

**停止条件：** 任一模式的板块、个股、分页或字段映射未确认，立即停止 Task 2 及后续实现，保留探测输出摘要并向用户报告具体未确认模式。不得用模拟数据、同请求伪装三模式、旧 TLS、MongoDB 数据或 200 空列表绕过门禁；若产品决定取消某模式，必须先由用户修改需求和 UI 合同。

- [ ] **Step 4: 固化最小脱敏 fixture 和合同文档**

fixture 只保留两页分页边界及字段映射所需的 2 至 3 行，删除无关元数据和任何设备标识。`selected-blocks.md` 写明实测日期、两个 host、三种模式的有效参数、返回容器路径、`list_son`/`list_soninfo` 的对应关系、数组下标含义，以及“本功能无持久化”。

- [ ] **Step 5: 提交合同证据**

```powershell
git -C $TaskRoot add -- quant-board/scripts/probe_selected_blocks_upstream.py quant-board/tests/fixtures/selected_blocks quant-board/docs/selected-blocks.md
git -C $TaskRoot commit -m "docs: freeze selected blocks upstream contract"
```

---

### Task 2: 用 TDD 实现上游分页与字段归一化

**Files:**
- Create: `quant-board/backend/selected_blocks/__init__.py`
- Create: `quant-board/backend/selected_blocks/models.py`
- Create: `quant-board/backend/selected_blocks/provider.py`
- Create: `quant-board/tests/test_selected_blocks_provider.py`

- [ ] **Step 1: 写失败测试**

测试使用 `httpx.MockTransport`，覆盖：当前/历史 host 切换；`Date` 只出现在历史请求；API 的 `offset/limit` 精确映射到上游 `index/st`；`Count` 计算 `hasMore`；实时请求只取当前页；三模式 action 不同；数组映射为具名字段；超时、非 2xx、非成功 `errcode` 和结构变化抛出不同的 `SelectedBlocksUpstreamError.code`。

```python
def test_fetch_block_page_forwards_requested_window():
    provider, requests = make_provider([
        {"list": [["801002", "智能电网", 8.8, 2.4]], "Count": 51, "Day": "2026-07-24", "errcode": "0"},
    ])
    result = provider.fetch_block_page(date="2026-07-24", mode="auction", offset=50, limit=50)
    assert [item.code for item in result.items] == ["801002"]
    assert requests[0].url.params["index"] == "50"
    assert requests[0].url.params["st"] == "50"
    assert result.has_more is False
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_provider.py -v
```

Expected: FAIL，原因是 `backend.selected_blocks` 尚不存在。

- [ ] **Step 3: 实现最小模型与 provider**

`models.py` 定义 `BlockRow`、`SecondaryBlockRow`、`StockRow`、`DashboardSnapshot`、`PagedRows[T]`；`BlockRow.children` 只来自实测的 `list_son`/`list_soninfo` 配对，不能通过名称猜测。字段包括代码、名称、排名、涨幅、强度、量比、主力净额、涨停个数、300W 大单净额、成交额以及旧页面实际展示的个股字段。`provider.py` 只负责上游 I/O、分页和映射，不包含 UI 筛选、历史十日编排或数据库代码。

公开查询只取请求页，禁止在每次 3 秒刷新中聚合 1000 行：

```python
page = self._request_page(index=offset, st=limit, **params)
return PagedRows(
    items=map_rows(page.raw_items),
    offset=offset,
    limit=limit,
    total=page.total,
    has_more=offset + len(page.raw_items) < page.total,
)
```

历史矩阵每个日期只请求前 10 行。provider 校验 `Count >= 0`、返回行数不超过 `limit`，违反时抛 `upstream_pagination_invalid`，不静默截断。

- [ ] **Step 4: 运行测试确认通过**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_provider.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交 provider**

```powershell
git -C $TaskRoot add -- quant-board/backend/selected_blocks quant-board/tests/test_selected_blocks_provider.py
git -C $TaskRoot commit -m "feat: add paged longhuvip selected blocks provider"
```

---

### Task 3: 用 TDD 实现十交易日只读服务

**Files:**
- Create: `quant-board/backend/selected_blocks/service.py`
- Create: `quant-board/tests/test_selected_blocks_service.py`

- [ ] **Step 1: 写失败测试**

用 fake provider 和可注入上海时区 clock 覆盖：从 `as_of` 向前查询；周末/节假日空结果跳过；按上游 `Day` 去重；恰好收集 10 日后停止；最多回看 31 个自然日；不足 10 日抛 `history_incomplete`；结果按日期倒序；当前日 dashboard 使用实时 host；`isLive` 至少覆盖交易时段且更新时间在 90 秒内、交易时段但更新时间陈旧、同日盘前、午休、盘后和历史日；缓存只在进程内生效且历史 TTL 与实时 TTL 分开；mode 纳入 history/cache key；个股和子板块调用透传日期、模式和分页。

```python
def test_history_returns_ten_unique_upstream_trading_days():
    provider = FakeProvider(return_same_day_for_weekend=True)
    service = SelectedBlocksService(provider, cache=MemoryTtlCache())
    result = service.get_history(days=10, as_of=date(2026, 7, 25))
    assert len(result.days) == 10
    assert len({day.trading_date for day in result.days}) == 10
    assert result.days == sorted(result.days, key=lambda day: day.trading_date, reverse=True)
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_service.py -v
```

Expected: FAIL，原因是 service 尚不存在。

- [ ] **Step 3: 实现最小服务**

历史扫描以 `Asia/Shanghai` 日期为准，每次将候选自然日减一；是否交易日由上游非空结果与响应 `Day` 决定，不复用 `snapshot_collector/trading_calendar.py` 中标注为近似的节假日表。默认且最多 `days=10`；扫描 31 日仍不足时抛 502 `history_incomplete` 并携带 `foundDays`，前端显示“历史数据不足（N/10）”，不能以 200 部分结果通过验收。

缓存仅使用进程内字典和单调时钟：实时 dashboard/stock TTL 为 0 秒（保证 3 秒轮询真实取数），历史日 TTL 30 分钟，容量上限 128 个 key；进程退出即丢弃。服务另接收可注入的 `now_provider`，统一返回 `Asia/Shanghai` aware datetime，用于 90 秒新鲜度和 09:15-11:30、13:00-15:00 交易时段判断；不得直接散落调用系统时间。不得导入 `backend.data`、`pymongo`、`redis` 或文件写入模块。

- [ ] **Step 4: 运行服务测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_service.py -v
```

Expected: 全部 PASS。

- [ ] **Step 5: 提交服务层**

```powershell
git -C $TaskRoot add -- quant-board/backend/selected_blocks/service.py quant-board/tests/test_selected_blocks_service.py
git -C $TaskRoot commit -m "feat: aggregate ten trading days without persistence"
```

---

### Task 4: 用 TDD 建立独立 FastAPI 5000 应用

**Files:**
- Create: `quant-board/backend/api/selected_blocks_routes.py`
- Create: `quant-board/backend/selected_blocks_main.py`
- Create: `quant-board/tests/test_selected_blocks_api.py`

- [ ] **Step 1: 写失败 API 测试**

通过 `app.dependency_overrides[get_selected_blocks_service]` 注入 fake service，并在 pytest fixture teardown 清空 overrides。覆盖 health、history、dashboard、stocks；`mode` 枚举和分页参数 422；未知 API 404；上游 502/503 错误包络；dashboard 的 `requestedDate`、`tradingDate`、`isLive` 和 children 合同；静态首页缺失提示；以及启动应用不触发 QuantBoard 8000 的 startup scheduler。测试还通过可注入的 frontend 目录临时创建 `dist/index.html` 和 `dist/assets/app.js`，断言 `/` 返回 HTML、`/assets/app.js` 返回资源、未知 `/api/**` 始终返回统一 JSON 404 而不是 SPA HTML。

```python
def test_history_endpoint_uses_ten_days_by_default():
    fake = FakeSelectedBlocksService()
    app.dependency_overrides[routes.get_selected_blocks_service] = lambda: fake
    response = TestClient(app).get("/api/selected-blocks/history")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert fake.history_args == {"days": 10, "as_of": None, "mode": "auction"}
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_api.py -v
```

Expected: FAIL，原因是独立 app 和 routes 尚不存在。

- [ ] **Step 3: 实现 routes 与独立 app**

`selected_blocks_main.py` 提供接收可选 frontend 目录的 `create_app()`，只创建 FastAPI、注册 selected-blocks router、统一 API 异常处理器、允许 5175 开发源 CORS，并在存在 `selected-blocks-frontend/dist` 时挂载 `/assets` 与返回 `index.html`。dist 缺失时 `/` 返回 503 JSON，消息明确给出 `npm run build`，健康接口仍保持 200 并返回 `serviceId=dragon-board-selected-blocks`。禁止导入 `backend.main`、数据库 settings 或任一 scheduler。

- [ ] **Step 4: 运行 API 与完整后端测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_api.py tests\test_selected_blocks_provider.py tests\test_selected_blocks_service.py -v
```

Expected: 全部 PASS，且日志中没有 MongoDB、Redis、collector 或 migration 初始化。

- [ ] **Step 5: 提交 5000 API**

```powershell
git -C $TaskRoot add -- quant-board/backend/api/selected_blocks_routes.py quant-board/backend/selected_blocks_main.py quant-board/tests/test_selected_blocks_api.py
git -C $TaskRoot commit -m "feat: expose standalone selected blocks api"
```

---

### Task 5: 建立独立 Vue 前端及 API 合同测试

**Files:**
- Create: `quant-board/selected-blocks-frontend/index.html`
- Create: `quant-board/selected-blocks-frontend/package.json`
- Create: `quant-board/selected-blocks-frontend/package-lock.json`
- Create: `quant-board/selected-blocks-frontend/tsconfig.json`
- Create: `quant-board/selected-blocks-frontend/tsconfig.node.json`
- Create: `quant-board/selected-blocks-frontend/vite.config.ts`
- Create: `quant-board/selected-blocks-frontend/playwright.config.ts`
- Create: `quant-board/selected-blocks-frontend/src/main.ts`
- Create: `quant-board/selected-blocks-frontend/src/useTheme.ts`
- Create: `quant-board/selected-blocks-frontend/src/types.ts`
- Create: `quant-board/selected-blocks-frontend/src/api.ts`
- Create: `quant-board/selected-blocks-frontend/src/__tests__/api.test.ts`

- [ ] **Step 1: 使用 frontend-design 明确实现约束**

实施本 Task 前读取并使用 `frontend-design`。视觉方向固定为高密度、安静、工作台式金融界面：中性深灰/白色底按项目现有方向选择，红涨绿跌，表格优先，圆角不超过 8px，不使用营销 hero、渐变球、嵌套卡片或大字号装饰文本。

- [ ] **Step 2: 创建最小 Vite/Vitest 配置并写失败测试**

`package.json` 运行依赖只加入 Vue；开发依赖固定包含 Vite、TypeScript、`@vitejs/plugin-vue`、`vue-tsc`、`@types/node`、Vitest、jsdom、Vue Test Utils 和固定版本 `@playwright/test`。脚本固定为 `dev`、`test`、`build: vue-tsc --noEmit && vite build`、`test:e2e: playwright test`；Vite 开发端口 5175，`/api` 代理到 `http://127.0.0.1:5000`。

```typescript
it('encodes date and pagination for stock requests', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okJson({ ok: true, data: { items: [] } })))
  const controller = new AbortController()
  await api.getStocks('801001', {
    date: '2026-07-24', mode: 'auction', offset: 80, limit: 80,
    signal: controller.signal
  })
  expect(fetch).toHaveBeenCalledWith(
    '/api/selected-blocks/801001/stocks?date=2026-07-24&mode=auction&offset=80&limit=80',
    { signal: controller.signal }
  )
})
```

- [ ] **Step 3: 运行测试确认失败**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board\selected-blocks-frontend')
npm install
npm test
```

Expected: FAIL，原因是 API client 尚未实现。

- [ ] **Step 4: 实现类型和 API client**

`types.ts` 与第 3 节合同一一对应，并定义 `SelectedBlocksMode = 'auction' | 'pre_limit' | 'wind_vane'`、`DashboardSnapshot` 和 `SecondaryBlockRow`；`api.ts` 只访问同源 `/api/selected-blocks/**`，每个查询方法接受可选 `AbortSignal` 并传给 `fetch`，非 2xx 兼容解析统一包络后抛出包含 `status`、`errorCode`、`message` 的类型化错误。`useTheme.ts` 只负责初始化、切换和持久化 `light|dark`，不访问 API。组件不得直接调用 `fetch`。

- [ ] **Step 5: 运行测试与提交**

```powershell
npm test
npm run build
git -C $TaskRoot add -- quant-board/selected-blocks-frontend
git -C $TaskRoot commit -m "feat: scaffold selected blocks frontend"
```

Expected: 测试 PASS，类型检查和 Vite build 成功。

---

### Task 6: 用组件测试实现完整精选板块页面

**Files:**
- Create: `quant-board/selected-blocks-frontend/src/components/AppSidebar.vue`
- Create: `quant-board/selected-blocks-frontend/src/components/HistoryMatrix.vue`
- Create: `quant-board/selected-blocks-frontend/src/components/BlockTable.vue`
- Create: `quant-board/selected-blocks-frontend/src/components/StockTable.vue`
- Create: `quant-board/selected-blocks-frontend/src/components/WorkspaceToolbar.vue`
- Create: `quant-board/selected-blocks-frontend/src/__tests__/App.test.ts`
- Create: `quant-board/selected-blocks-frontend/src/App.vue`
- Create: `quant-board/selected-blocks-frontend/src/styles.css`

- [ ] **Step 1: 写失败组件测试**

覆盖：日期输入默认上海当天并分别展示 `requestedDate/tradingDate`、默认模式为竞价、三个模式按钮同时刷新 dashboard/history；左侧目录高亮与状态文字正确；历史倒三角只切换可见性；首次加载十日矩阵；默认选择 dashboard 第一板块；点击日期刷新左表；点击板块刷新右表；板块和个股分页器根据 `total/hasMore` 可前后翻页；有 `children` 的板块三角展开菜单，点击子项刷新右表；日期、模式、板块和分页切换均 abort 旧请求；generation id 阻止旧响应或混合快照提交；加载、历史不足、空数据和错误状态可见；涨跌值分别带 `is-up`、`is-down`；“重试”只重试失败区域；主题状态默认值、本地持久化、无效值回退、按钮切换和业务状态保持。首屏防闪烁只由 Task 9 的真实浏览器测试验收，组件测试不冒充 `index.html` 加载顺序。

```typescript
it('toggles theme without reloading dashboard state', async () => {
  localStorage.setItem('selected-blocks-theme', 'light')
  const wrapper = mount(App)
  await flushPromises()
  const callsBeforeToggle = vi.mocked(api.getDashboard).mock.calls.length
  await wrapper.get('[data-testid="theme-toggle"]').trigger('click')
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('selected-blocks-theme')).toBe('dark')
  expect(vi.mocked(api.getDashboard).mock.calls.length).toBe(callsBeforeToggle)
})
```

```typescript
it('loads stocks for the newly selected block', async () => {
  const wrapper = mount(App)
  await flushPromises()
  await wrapper.get('[data-block-code="801002"]').trigger('click')
  await flushPromises()
  expect(api.getStocks).toHaveBeenLastCalledWith('801002', expect.objectContaining({
    date: '2026-07-24'
  }))
  expect(wrapper.get('[data-testid="selected-block-name"]').text()).toBe('智能电网')
})
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board\selected-blocks-frontend')
npm test
```

Expected: FAIL，原因是页面组件尚未实现。

- [ ] **Step 3: 实现页面状态和交互**

按第 2.1 节实现 `AppSidebar`、`WorkspaceToolbar` 和无嵌套卡片的工作区。侧栏在桌面保持 232px、在移动端由菜单图标开关；`盘中精选` 高亮时展示实时 workspace，`十日题材` 仅展开并滚动到历史矩阵，不创建第二套页面或数据源；侧栏底部按主题合同放置浅色/深色切换和目录收起。顶栏左侧为页面标题，右侧依次为日期、三模式分段控件、历史图标按钮和“已更新 HH:mm:ss”状态。模式以 `aria-pressed` 标识，切换后保持请求日期并重新加载主区与该模式历史。左侧板块目录占工作区 34%，右侧个股列表占 66%；两个 pane 底部各有上一页、页码、下一页和总数，切页只请求对应 `offset/limit`。板块第一列的子板块三角是图标按钮，菜单定位在该行下方，选择子项后标题显示“父板块 / 子板块”。日期使用原生日期输入配合前后交易日按钮，选中日期和板块有稳定高亮。数据表使用语义化 `table`，表头固定，数值右对齐，代码/名称左对齐；不因加载文案或长名称改变列宽。

`App.vue` 单独维护递增 `generationId`、递归 `refreshTimeout`、`AbortController`、`consecutiveRefreshFailures` 和两个分区的刷新时间；`onUnmounted` 必须清除 timeout 和 abort 请求。每轮先把 dashboard 放入临时值，校正已消失的 selected block/child，再取 stocks；只有 generation 仍为最新且两次请求都成功时才原子提交整轮快照，任一失败保留上一轮完整快照。下一次 `setTimeout(3000)` 只在本轮结束后安排；历史日期不创建 timeout，绝不使用 `setInterval` 或提交混合新旧数据。

桌面最小验证宽度 1280；移动端 390 宽时侧栏收起、数据 pane 上下堆叠、工具栏换行，矩阵和表格在自己的滚动容器内横向滚动，页面本身 `scrollWidth === clientWidth`。所有图标按钮有可访问名称、悬停提示、键盘焦点和禁用态。

- [ ] **Step 4: 运行测试和构建**

```powershell
npm test
npm run build
```

Expected: 全部 PASS，`dist/index.html` 与 `dist/assets/**` 生成。

- [ ] **Step 5: 提交页面**

```powershell
git -C $TaskRoot add -- quant-board/selected-blocks-frontend/src
git -C $TaskRoot commit -m "feat: build selected blocks trading workspace"
```

---

### Task 7: 集成 FastAPI 静态页面并做无数据库冒烟验证

**Files:**
- Modify: `quant-board/docs/selected-blocks.md`
- Modify: `quant-board/docs/README.md`

- [ ] **Step 1: 构建前端并复跑静态托管测试**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_api.py -v
```

Expected: 全部 PASS；静态托管行为已在 Task 4 实现并转绿，本 Task 不再修改后端实现。

- [ ] **Step 2: 启动真实 5000 服务**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board\selected-blocks-frontend')
npm run build
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m uvicorn backend.selected_blocks_main:app --host 127.0.0.1 --port 5000
```

另一个终端验证：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/selected-blocks/health
Invoke-WebRequest http://127.0.0.1:5000/ -UseBasicParsing
```

Expected: health 为 200 JSON，首页为 200 HTML；不启动 MongoDB、Redis、8000 或 TLS 代理也成立。

- [ ] **Step 3: 更新专题文档和索引**

文档写明运行命令、API、上游依赖、分页规则、缓存 TTL、错误码、构建步骤和“无 MongoDB 持久化”边界。`quant-board/docs/README.md` 只增加专题链接，不修改数据库迁移文档。

- [ ] **Step 4: 提交集成文档**

```powershell
git -C $TaskRoot add -- quant-board/docs/selected-blocks.md quant-board/docs/README.md
git -C $TaskRoot commit -m "docs: document standalone selected blocks service"
```

---

### Task 8: 将 5000 服务接入 DragonBoardLauncher

**Files:**
- Create: `tools/DragonBoardLauncher/SelectedBlocksServiceProbe.cs`
- Modify: `tools/DragonBoardLauncher/LauncherServices.cs`
- Modify: `tools/DragonBoardLauncher/LauncherProcessManager.cs`
- Modify: `tools/DragonBoardLauncher/LauncherForm.cs`
- Modify: `tools/DragonBoardLauncher/README.md`

- [ ] **Step 1: 先保护用户现有 diff**

```powershell
Set-Location $TaskRoot
git diff -- tools/DragonBoardLauncher/LauncherForm.cs
```

Expected: 仍能看到 `_restoreLocation`、隐藏前保存 `DesktopLocation`、恢复后 `BringToFront()`；后续 diff 必须保留这些行。

- [ ] **Step 2: 实现稳定身份探测并先验证其可编译**

`SelectedBlocksServiceProbe.cs` 使用带 1500ms 超时的共享 `HttpClient` 请求 `http://127.0.0.1:5000/api/selected-blocks/health`，只在 HTTP 2xx、`ok=true` 且 `data.serviceId == "dragon-board-selected-blocks"` 时返回 `Healthy`；端口未监听返回 `Offline`，端口已监听但超时、非 JSON、错误包络或身份不符返回 `Conflict`。探测结果必须区分这三个状态，供启动、状态卡和打开页面共用，禁止只返回 bool 后丢失冲突语义。

```powershell
Set-Location $TaskRoot
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Debug
```

Expected: PASS。当前 Launcher 没有测试项目，本 Task 不为单一 HTTP probe 新建 xUnit 工程；身份分支由 Step 5 的正常/冲突人工验收覆盖。

- [ ] **Step 3: 注册服务并保护端口所有权**

在 `OrderedKeys` 增加 `selected-blocks`，在 `CoreStartupKeys` 增加同一 key，并在 `Create()` 注册：工作目录 `quant-board`，端口 5000，可执行文件 `.venv\Scripts\python.exe`，参数 `-m uvicorn backend.selected_blocks_main:app --host 127.0.0.1 --port 5000`，fallback 为 `python`。

`IsServiceRunning(selected-blocks)` 必须调用身份 probe：`Healthy` 才显示在线；`Conflict` 显示“5000 端口被其它服务占用”，不把旧 Flask/KPL 或任意 HTTP 服务认作精选服务，也不继续启动 Uvicorn。`StartService` 启动后只把自己创建的 `Process` 保存到 `ManagedService.Process`；对 selected-blocks 的 `StopService`、`StopAll()` 和 `StopStartedProcesses()` 都只调用 `StopStartedProcess(service)`，不得执行当前通用的 `GetPidsByPort(5000)` / `KillProcessTree` 回收路径。若 5000 上已有身份正确但不是本次 Launcher 启动的服务，可显示在线和打开页面，但停止/退出时必须保留它。

`StopAll()` 和 `StopStartedProcesses()` 都在 `quant-api` 前处理 `selected-blocks`，确保 Launcher 自己启动的 5000 被回收，同时不影响外部进程。

- [ ] **Step 4: 精确修改 Launcher UI**

`iconKeys` 在量化项前增加 `SB`；服务卡的可打开端口集合增加 5000，URL switch 显式映射到 `http://127.0.0.1:5000`。服务卡、托盘“打开精选”和底部 86px 宽“打开精选”按钮在打开前都调用同一身份 probe：只有 `Healthy` 才打开浏览器；`Offline` 提示服务未启动；`Conflict` 提示端口冲突且绝不打开占用者页面。窗体高度调整到能容纳第九张服务卡和日志，但不改变现有颜色、字体与卡片样式。

- [ ] **Step 5: 编译并做端口冲突验收**

```powershell
Set-Location $TaskRoot
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Debug
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
```

Expected: 0 errors。当前 Launcher 没有测试项目，本任务不为四个常量分支引入新的 xUnit 工程；以编译、端口探测和真实按钮流程验收。

正常路径人工验证：单独启动/停止精选服务；核心启动后 5000 在线；服务卡“打开”、底部“打开精选”和托盘“打开精选”均打开首页；“全部停止”和退出 Launcher 后，由 Launcher 启动的 5000 关闭；最小化恢复位置行为仍正常。

冲突路径必须单独验证：先运行 `$conflictProcess = Start-Process python -ArgumentList '-m','http.server','5000','--bind','127.0.0.1' -WindowStyle Hidden -PassThru` 并记录 `$conflictProcess.Id`，再启动 Launcher。Expected: 精选卡明确显示端口冲突；三个打开入口都不打开该测试页面；点击精选停止、全部停止及退出 Launcher 后，`$conflictProcess.Refresh(); $conflictProcess.HasExited` 仍为 `False`。测试完成后只执行 `$conflictProcess.Kill()` 停止这个受控 PID，Launcher 不得按端口终止它。

- [ ] **Step 6: 更新 Launcher 文档并提交**

```powershell
git -C $TaskRoot add -- tools/DragonBoardLauncher/SelectedBlocksServiceProbe.cs tools/DragonBoardLauncher/LauncherServices.cs tools/DragonBoardLauncher/LauncherProcessManager.cs tools/DragonBoardLauncher/LauncherForm.cs tools/DragonBoardLauncher/README.md
git -C $TaskRoot commit -m "feat: manage selected blocks service in launcher"
```

---

### Task 9: Playwright 真实浏览器验收与最终回归

**Files:**
- Create: `quant-board/selected-blocks-frontend/e2e/selected-blocks.spec.ts`
- Modify: `quant-board/selected-blocks-frontend/package.json`
- Modify: `quant-board/selected-blocks-frontend/playwright.config.ts`

- [ ] **Step 1: 固定可重复运行的 Playwright 环境**

实施本 Task 前读取并使用 `playwright` 技能。`playwright.config.ts` 固定 `baseURL: 'http://127.0.0.1:5000'`，只启用 Chromium；`webServer.command` 为 `.venv\\Scripts\\python.exe -m uvicorn backend.selected_blocks_main:app --host 127.0.0.1 --port 5000`，`webServer.cwd` 用 `fileURLToPath(new URL('..', import.meta.url))` 明确指向 `quant-board`，并设置 `reuseExistingServer: false`。启动前若 5000 已占用则直接失败，避免测试命中旧 Flask/KPL 服务。配置不得在测试时连接真实上游，公开 API 全部由 Playwright `page.route('**/api/selected-blocks/**', ...)` 提供确定 fixture。

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board\selected-blocks-frontend')
npm run build
npx playwright install chromium
```

Expected: `dist/**` 存在，项目锁定版本对应的 Chromium 可用。浏览器安装是首次环境准备，不在每次测试重复执行。

- [ ] **Step 2: 用路由 mock 和假时钟编写关键路径**

测试通过稳定 `data-testid` 定位，覆盖：首页非空；桌面侧栏为 232px 且“盘中精选”高亮；三个模式按钮分别发出正确 `mode` 的 dashboard/history 请求；历史矩阵恰有 10 个日期且倒三角可折叠；切换日期后左表日期一致；左右分页只请求当前 `offset/limit`；二级菜单可选择且右表标题和请求参数一致；API 503 时保留上一完整快照并出现错误与重试；历史日期不创建定时器；浏览器控制台无 error。

初始 dashboard/stocks 加载完成后清零计数，再循环三次执行“`page.clock.fastForward(3000)` -> 等待本轮 dashboard 和 stocks route 都完成 -> 断言下一轮 timeout 已安排”。一轮固定包含一个当前页 dashboard 请求和一个当前选中板块当前页 stocks 请求；route handler 记录同时在途轮次数并延迟响应，最终断言三轮完成且 `maxInFlightRounds === 1`。另用独立用例挂起旧请求后切换模式或日期，断言请求收到 abort 且旧 generation 不覆盖新状态。不得一次快进 9 秒、使用真实等待或依赖当天是否交易。

主题覆盖：预置 `selected-blocks-theme` 后刷新仍保持；按钮在 light/dark 间切换且不增加 API 调用。首屏防闪烁用例参数化覆盖 stored light、stored dark、missing + prefers light/dark、invalid + prefers light/dark；每例用 `page.addInitScript` 设置存储和 `matchMedia`，route 挂起主 JS，导航等待 `waitUntil: 'commit'` 后轮询根节点预期 `data-theme`，释放主 JS 并再次断言 Vue 未改错。桌面 1440x900 和移动 390x844 的 light/dark 四个组合使用 `expect(page).toHaveScreenshot(...)` 管理基线并断言 `document.documentElement.scrollWidth === clientWidth`；每套主题显式进入 focus、selected、disabled、error、loading、up/down 状态，断言对应 computed color/background/border 与普通状态不同，截图由实施者人工复核一次后纳入基线。

- [ ] **Step 3: 运行可重复的完整验证**

```powershell
Set-Location (Join-Path $TaskRoot 'quant-board')
.\.venv\Scripts\python.exe -m pytest tests\test_selected_blocks_provider.py tests\test_selected_blocks_service.py tests\test_selected_blocks_api.py -v

Set-Location (Join-Path $TaskRoot 'quant-board\selected-blocks-frontend')
npm test
npm run build
npm run test:e2e

Set-Location $TaskRoot
dotnet build tools\DragonBoardLauncher\DragonBoardLauncher.csproj -c Release
```

Expected: pytest、Vitest、Vite build、Playwright 和 dotnet build 全部退出码 0。

- [ ] **Step 4: 将真实上游冒烟与 mock E2E 分开验收**

先停止 Playwright webServer，再人工启动不带 route mock 的真实服务。在非 mock 服务上依次检查请求当天、前一交易日和一个跨周末日期；日期控件始终保留请求日期，同时确认 `tradingDate`、10 日去重、当前页分页总数、至少一个板块个股非空、红绿值与原始数值符号一致。非交易日只验证历史读取、`isLive=false`、无定时器和无控制台错误；首个交易日交易时段另外执行三轮 3 秒刷新，确认每轮 `refreshedAt` 前进、请求不重叠、失败时保留上次成功数据。mock E2E 通过不代表真实合同通过；上游不可用时记录为外部阻塞，不能改用数据库或假数据声称通过。

- [ ] **Step 5: 检查最终 diff**

```powershell
Set-Location $TaskRoot
git status --short
git diff --stat
git diff -- quant-board/backend/selected_blocks quant-board/backend/api/selected_blocks_routes.py quant-board/backend/selected_blocks_main.py quant-board/selected-blocks-frontend tools/DragonBoardLauncher quant-board/docs
rg -n "pymongo|MongoClient|backend\.data|redis|supabase|sqlite" quant-board/backend/selected_blocks quant-board/backend/selected_blocks_main.py quant-board/backend/api/selected_blocks_routes.py
```

Expected: `rg` 无匹配；diff 不包含根 `src/**`、QuantBoard 8000 主应用、数据库 schema/迁移或用户其它未提交文件；`LauncherForm.cs` 的原有托盘恢复改动仍在。

- [ ] **Step 6: 最终提交**

```powershell
git -C $TaskRoot add -- quant-board/selected-blocks-frontend/e2e/selected-blocks.spec.ts quant-board/selected-blocks-frontend/package.json quant-board/selected-blocks-frontend/package-lock.json quant-board/selected-blocks-frontend/playwright.config.ts
git -C $TaskRoot commit -m "test: cover selected blocks browser workflow"
```

## 4. 风险与回退

- **首要阻塞风险：** 当前已验证的旧个股合同返回空列表。Task 1 是硬门禁；`auction`、`pre_limit`、`wind_vane` 任一模式未取得可区分且非空的板块和个股真实响应，都不得进入 Task 2 以后实现。
- **上游字段风险：** longhuvip 使用数组下标字段。只在 provider 映射，并用脱敏 fixture 锁定；前端只消费具名字段。
- **上游负载风险：** history 每个候选日只请求前 10 条；实时 dashboard/stock 每轮只请求用户当前页。使用进程内 TTL、31 日扫描上限和去重，不做持久化，也不并发轰炸上游。
- **交易日风险：** 项目现有节假日表明确是近似值。本功能以历史接口实际 `Day` 和非空数据判断，不复制该表。
- **工作区风险：** 主工作区已有多处用户改动，且 `LauncherForm.cs` 与计划修改重叠。Task 0 未获得用户对工作区策略的明确选择前不得实施；启用 worktree 后只在 `$TaskRoot` 写入，直接实施则逐文件保护现有 diff。
- **端口身份风险：** 5000 可能已被旧 Flask/KPL 或任意本地服务占用。Launcher 必须以 health `serviceId` 区分在线与冲突，且只停止自己跟踪的 PID；绝不能按 5000 端口杀进程。
- **验收环境风险：** mock E2E 用于确定性验证刷新、错误和主题，真实上游冒烟用于合同与交易时段验证；两者必须分别报告，不能互相替代。
- **回退方式：** 从 Launcher 的注册、身份探测、生命周期和打开入口移除 `selected-blocks`，只停止 Launcher 自己启动并跟踪的 5000 进程；因为没有数据库变更，不需要数据迁移或回滚脚本。

## 5. 计划自审结论

- 需求覆盖：独立 5000、FastAPI、独立 Vue 页面、十交易日、日期选择、板块/个股联动、Launcher 管理、浏览器验收均有对应 Task。
- 范围检查：未修改 MongoDB/Supabase/SQLite、QuantBoard 8000 主应用、根前端、TLSClient 或 3000 代理。
- 合同检查：API 参数、响应包络、错误码、分页终止规则和日期语义前后一致。
- 占位检查：未发现悬空实现项；唯一未知的个股合同被定义为可验证的阻塞门禁，禁止猜测。
- 简洁性检查：只引入一个独立后端进程、一个独立前端和一个内存缓存，不增加数据库、队列、守护进程或新后端框架。
- 对抗性评审：独立 reviewer 首轮结论为 `With fixes`，修订后复审发现提交目录、递归 clock、`isLive` 时间合同、静态托管职责和主题矩阵仍需收口；逐项修正后的闭环复审为 `No blocking findings / Ready`。三模式合同门禁、`$TaskRoot`、前端依赖、Playwright 环境、Launcher 服务身份/PID 所有权、严格十日、公开分页、`AbortSignal`、原子快照、日期语义、统一错误包络、history mode、`dependency_overrides`、主题首屏和视觉基线均已有可执行步骤。剩余真实外部风险只有实施阶段尚未取得三模式及其个股的有效上游合同，Task 1 保持阻塞。
