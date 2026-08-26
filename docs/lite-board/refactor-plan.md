# lite-board 极简重构方案 v3（独立部署 + 移动优先）

> 状态：**方案 v3（2026-08-25）**。新增产品定位与移动优先约束。
> 归档：`docs/lite-board/`。

## 0. 产品定位（2026-08-25 明确，最重要）

**dragon-board 的简单想法**：本机回测找出可靠因子（五维信号已基本成型）→ 部署到云端服务器运行 →
**手机端随时查看**。

**两系统分工（不互删，各自职责）**：

| 系统 | 职责 | 运行位置 |
|---|---|---|
| **quant-board（现有）** | 回测/因子研究/参数搜索（五维信号成型地） | **本机**（保留不动） |
| **lite（新建）** | 云端生产：八平台热榜 + 五维信号 + 行情/资金 + 手机展示 | **云服务器**（独立，无 MongoDB/Redis） |

lite 是"生产展示层"：把本机研究出的五维信号引擎搬到云端跑（引擎拷贝独立，见 §3），
手机浏览器访问。**移动端查看是核心场景**，前端按移动 app 特点设计。

**硬约束**：完全脱离 quant-board、无 MongoDB/Redis、可云部署、**移动优先 UI**。

## 0.1 硬约束（沿用 v2）

1. **完全脱离 quant-board**：不 import、不引用 quant-board 目录，独立演进
2. **无 MongoDB / 无 Redis**：SQLite（stdlib sqlite3）
3. **可云部署**：仅 fastapi + uvicorn + httpx 三个 pip 包
4. **移动优先**：页面按手机 app 特点设计（手机端查看为主要场景）

## 1. 范围边界（不变）

**做**：八平台热榜排名、均榜 avgRankNum、综合 compRank、五维信号（共振/趋势/横截/量价/周期）、
排序、涨跌幅/主力净额基础列。
**不做**：题材/回测/优化/自动信号/L2/开盘信号/自选/主题系统/多面板/IndexedDB/备份/Supabase/Redis 缓存。

## 2. 已确认决策（D1-D4，沿用）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 热榜数据源 | A 实时抓取（进程内 TTL 缓存，无 Redis） |
| D2 | 均榜/综合 | B 后端算（py，复用 comprehensive_rank 算法移植进 lite） |
| D3 | 五维当前帧 | A 快照当前点（最新快照帧 avgRankNum 作为当前点） |
| D4 | 采集器 | B lite 自带采集（写 SQLite，独立运行） |

## 3. 系统架构（完全自包含）

```text
lite/                              # 独立项目，可整体拷贝到云服务器
├── server.py                      # FastAPI 单进程（~300 行）
│   ├── GET /api/board             # 实时热榜（进程内缓存）→ 后端算均榜/综合 → stocks
│   ├── GET /api/signals           # SQLite 历史序列 + 引擎 → 每股五维
│   └── 静态托管 index.html + app.js
├── collector.py                   # 定时采集（~100 行）：抓热榜 → 均榜/综合 → 写 SQLite
├── engine_use.py                  # 引擎薄封装（~80 行）：历史序列 → 五维
├── store.py                       # SQLite 读写（~120 行，sqlite3 stdlib）
├── market.py                      # 行情层（~150 行，httpx）：腾讯价格/涨幅/量额/PE/PB/市值
│                                  #   + 同花顺主力资金；60s 批量拉取 + 失败降级（进程内缓存）
├── hotlists.py                    # 八平台热榜抓取（从 quant-board market_proxy 拷贝，
│                                  #   仅 HotlistService 类，删 backend/Redis 入口，~240 行）
├── ranktrend/                     # 五维引擎（从 quant-board analysis/ranktrend 拷贝，4,958 行，
│   └── ...                        #   纯 Python stdlib，已验证零外部依赖；拷入后完全独立）
├── index.html                     # 单页（~100 行）
├── app.ts                         # 原生 TS：fetch 轮询 + 表格渲染 + 排序（~500 行）
├── data/                          # 运行数据目录（.gitignore；SQLite 文件 board.sqlite）
├── requirements.txt               # fastapi uvicorn httpx（仅 3 个）
├── run.sh                         # 云服务器启动脚本（uvicorn + 后台 collector）
└── README.md
```

**独立化方案（已验证可行）**：
- `analysis/ranktrend`：**零外部非 stdlib 依赖**（已用 import 扫描确认），整体拷贝 → `lite/ranktrend/`，
  之后与 quant-board 脱钩、独立演进
- `market_proxy/hotlists.py`：`HotlistService` 类纯 stdlib + httpx（已确认），Redis 是**可选参数**
  （None 时用进程内缓存）；backend 依赖只在入口函数 `get_hotlist_service()`（383-390 行），
  拷贝时删除该函数，lite 自行 `HotlistService(redis_client=None, ttl_seconds=60)` 构造
- 均榜/综合算法：从 ComprehensiveRankEngine（前端 TS 版）移植到 py（~120 行），与 quant-board
  的 comprehensive_rank.py 同构；拷 quant-board 版亦可（79 行纯函数）

## 4. 行情数据源（2026-08-25 补充，云部署关键）

**字段 → 数据源映射**（lite 全 httpx 直连，无本地依赖）：

| 字段 | 数据源 | 说明 |
|---|---|---|
| 价格 / 涨幅 / 成交量 / 成交额 | **腾讯 HTTP** `qt.gtimg.cn`（f5/f3/f6/f8 等，批量 100/次） | 一条接口同时覆盖 PE/PB/市值；字段映射已验证（quant-board `to_tencent_diff_item`） |
| PE(PB) / 总市值 / 流通市值 | **腾讯 HTTP** `qt.gtimg.cn`（f9=pe_ttm、f20=总市值、f21=流通市值、f23=pb） | 同上，同一请求 |
| 主力资金（zlje/zljzb） | **同花顺个股资金 HTTP**（10jqka，httpx 直连） | 参考 akshare `stock_individual_fund_flow(ths)`；lite 用 httpx 直连避免 akshare 重依赖 |

**关于 mootdx / python-bridge**（你提到的源）：`python-bridge` 是**本地 Windows 形态**（ws://127.0.0.1:8765），
云服务器不存在该桥。lite 云版的价格链路用**腾讯 HTTP**（覆盖价格/涨幅/量/额，已验证），
**不依赖 python-bridge**；如需更实时，可选集成 `mootdx`（纯 Python 直连 TDX 行情服务器，
不经过本地桥），作为 v1 之后的可选增强，不进 v1 必做项。

**lite 行情层设计**（`market.py`，~150 行，httpx 批量并发）：
- 腾讯：每 60s 批量拉全量热榜 code 的行情（100/批），合并进 stocks（价格/涨幅/量/额/PE/PB/市值）
- 同花顺资金：每 60s 拉热榜 code 的主力资金（zlje/zljzb），合并进 stocks
- 失败降级：单源失败返回最近一次结果（进程内缓存，fail-visible，无 Redis）

## 5. 存储设计（SQLite，替代 MongoDB）

```sql
-- lite/data/board.sqlite（sqlite3 stdlib，自动创建）
CREATE TABLE frames (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL DEFAULT 'lite',
  trading_date TEXT NOT NULL,
  slot_time TEXT NOT NULL,
  ts INTEGER NOT NULL,            -- 时间戳（排序）
  UNIQUE(dataset, trading_date, slot_time)
);
CREATE TABLE stock_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  frame_id INTEGER NOT NULL REFERENCES frames(id),
  code TEXT NOT NULL,
  name TEXT,
  change REAL,
  em_rank INTEGER, ths_rank INTEGER, kpl_rank INTEGER, tdx_rank INTEGER,
  xq_rank INTEGER, cls_rank INTEGER, tgb_rank INTEGER, dzh_rank INTEGER,
  platform_count INTEGER,
  avg_rank_num REAL, comp_rank INTEGER, comp_score REAL,
  zljzb REAL, zlje REAL, turnover REAL, turnover_rate REAL, fund_penetration REAL
);
CREATE INDEX idx_stock_rows_frame ON stock_rows(frame_id);
CREATE INDEX idx_stock_rows_code ON stock_rows(code);
```

- 五维历史序列：读最近 60 帧同 code 的 `(ts, avg_rank_num)` → 构造 percentile 序列（复用引擎同款
  attention percentile 逻辑，~30 行）
- 无 MongoDB/Redis：采集写 SQLite、analyze 读 SQLite、热榜用进程内缓存（TTL 60s）

## 5. 接口设计（不变）

```text
GET /api/board   → { ok, frameKey, updatedAt, stocks: [{ code, name, change, emRank, ..., avgRankNum, compRank }] }
GET /api/signals → { ok, signals: { code: { resonance, rankTrend, crossSection, volumePrice, lifecycle, displayStatus } } }
```

## 6. 前端（移动优先，单 HTML 应用）

**设计原则（手机 app 特点）**：
- **卡片式列表**替代桌面表格：每只股票一张卡（代码/名称/涨跌幅大红绿/均榜/综合/五维信号方向+分数），
  一屏约 5-6 张卡，信息密度适中、触控目标 ≥44px
- **顶部栏**：标题 + 最后刷新时间 + 自动刷新指示（60s）；下拉刷新手势
- **排序/筛选**：顶部横向 tab（综合/均榜/涨幅/资金）+ 升降序切换（点 tab 切换，长按/二次点反向）；
  "向上"方向恒前（沿用现有规则）
- **详情**：点击卡片弹出底部抽屉（移动 app 风格）展示单股五维明细（共振/趋势/横截/量价/周期
  方向+分数+档位+状态）+ 主力资金/市值/PE/PB
- **响应式**：手机（375px 起，主要场景）+ 平板/桌面（复用同列表，加宽卡片网格）
- **可安装**（可选增强，v1 后）：PWA manifest + 添加到主屏，全屏独立运行

**技术形态（D5/D6 已确认）**：
- `index.html` + `app.ts`（原生 TS + 移动优先 CSS，无框架）+ `sw.js`（service worker）+ `manifest.webmanifest`
- esbuild 一条命令构建 app.js；server.py 静态托管（含 manifest + sw 注册）
- **PWA**：manifest（name/图标/display: standalone）+ service worker（缓存静态资源 + 离线显示上次数据）；
  手机浏览器"添加到主屏" → 全屏独立运行，接近原生 app 体验（无应用商店）
- 轮询：board 60s / signals 5min；弱网/离线降级（上次数据 + 灰色"刷新于 xx:xx"）

## 7. 云部署

```bash
# 服务器（Linux）
pip install -r requirements.txt        # fastapi uvicorn httpx
export LITE_DATA_DIR=/var/lib/lite     # SQLite 数据目录（默认 ./data）
nohup python collector.py &            # 定时采集（落 SQLite）
uvicorn server:app --host 0.0.0.0 --port 8900 &
# 浏览器访问 http://<server>:8900
```

- 单进程 uvicorn 同时服务 API + 静态页面；collector 独立进程写 SQLite（WAL 模式支持并发读写）
- 前端构建产物 app.js 提交进仓库（或服务器上 esbuild 一次）
- systemd/进程管理器示例写入 README（可选）

## 8. 工作量拆解（约 1.5-2 天）

| 步骤 | 内容 | 预估 |
|---|---|---|
| 1 | 拷贝独立化：ranktrend/ + hotlists.py（删 backend/Redis 入口）+ 均榜/综合 py 移植 | 3 小时 |
| 2 | store.py（SQLite）+ collector.py（采集落库：热榜+行情+资金快照） | 3 小时 |
| 3 | market.py（腾讯行情 + 同花顺资金，httpx 批量 + 降级） | 3 小时 |
| 4 | server.py /api/board + /api/signals（engine_use） | 4 小时 |
| 5 | index.html + app.ts（表格/排序/轮询） | 4 小时 |
| 6 | 联调验证（本地浏览器实测）+ run.sh + README | 2-3 小时 |

## 9. 风险与缓解

1. **引擎拷贝后的独立维护**：v1 从 quant-board 一次性拷贝（已确认零依赖），之后 lite 自行演进；
   quant-board 的算法更新不会自动同步（可接受，lite 定位是稳定极简）。
2. **SQLite 并发**：采集写 + 查询读 → 开启 WAL（`PRAGMA journal_mode=WAL`），单机足够。
3. **上游可达性**：八平台热榜依赖外网；HotlistService 已有降级/负缓存，失败回退最近结果（fail-visible）。
4. **冷启动**：SQLite 新库需积累快照（采集器每 30 分钟一帧，3-5 天趋势/共振成熟）；
   可选导入现有 MongoDB 历史（一次性脚本，不强制）。
5. **端口**：8900（避开 3000/8000/8001/5173/5174）。
6. **回退**：lite 独立目录，不动现有仓库代码。

## 10. 已确认决策（D5/D6，前端技术）

| # | 决策 | 结论 | 说明 |
|---|---|---|---|
| D5 | 前端技术 | **A 原生 TS + 移动 CSS**（无框架） | esbuild 一条命令构建；卡片式列表 + 触控交互 |
| D6 | 移动形态 | **B 直接做 PWA** | v1 即带 manifest + service worker：手机添加到主屏、全屏独立运行（无应用商店）；**若后续要发 apk/上架，加 Capacitor 壳（web 代码不变，仅多一层打包）** |

## 11. 实施步骤

1. 建 lite 目录 + requirements + .gitignore（data/）
2. 拷贝独立化：ranktrend/ + hotlists.py（删 backend 耦合）+ 均榜/综合 py
3. store.py（SQLite WAL）+ collector.py → 本地跑通采集落库（热榜+行情+资金快照）
4. market.py（腾讯行情 + 同花顺资金）→ 接口验证
5. server.py /api/board（实时抓 + 均榜/综合）→ 接口验证
6. engine_use.py + /api/signals（五维 + 快照当前点）→ 接口验证
7. 前端（D5/D6 定后）：移动优先卡片列表 + 排序 + 轮询 → 手机浏览器实测
8. run.sh + README（云部署 + 手机访问说明）→ 交付
