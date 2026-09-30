# M2 分相位验收框架收口（2026-09-30）

## 1. 交付物

| 交付物 | 位置 | 测试 | 状态 |
|---|---|---|---|
| 北极星 harness | `backend/operations/phase_northstar.py`（commit 774b8fd9） | 4 passed | 实跑产出 `phase-northstar-v1.json` |
| 相位-收益地图（gen7 基线） | `ranktrend-phase-map-baseline.md`（c385911d） | —（数字逐格转录产物） | 落档 |
| 月度监控 | `backend/operations/phase_monitor_monthly.py`（684450db） | 3 passed | 首跑 `monthly-2026-09.json`（labelsFresh=true） |
| M1 链（依赖） | `phase_labeler` / `phase_label_run` / `phase_trade_slice`（a95b6db1/45ec3fe3/cd59ce71） | 5 passed（间接） | 复用 |

全部只读：无 Mongo 写、无引擎/config 改动、产物不入 git（data/reports/phase-monitor/）。

## 2. 北极星首期读数（2026-04-15 ~ 09-30，54 笔 roundTrip，sentiment_2b）

| 相位 | 机械线判定 | 关键读数 |
|---|---|---|
| offense | **未过**（wrxpf 0.355<0.78 ✗ / 35 笔<60 ✗ / maxDD −4.87%≤10% ✓） | sumNetReturn −12.10%，段内收益 +9.28% |
| defense | **过**（ddBetter ✓ + lossBetter ✓ 双项） | wrxpf 0.9729，sum +33.77%，maxDD −3.98%，段内收益 +12.81% |
| 满仓对照 | — | maxDD −4.87%，segReturn +11.91% |

**单期读数 ≠ 验收**——验收走月度走廊（连续 3 期达线）。首期方向与实盘体感相反（低情绪相位表现更好），解读与三种候选解释见地图基线 §3；M3 适配立项前必须看该方向跨期稳定性。

## 3. 月度监控运行说明

- 命令：`./.venv/Scripts/python.exe -m backend.operations.phase_monitor_monthly --month YYYY-MM`（次月数据落库后跑，约 1 分钟）。
- 产出：`data/reports/phase-monitor/monthly-YYYY-MM.json`——coverage（本月情绪文档数/交易日/标签新鲜度）+ 三监督线。
- **扩窗提醒**：labels 未覆盖当月时 `labelsFresh=false` 并提示——先按 M1 报告 §2.5 复判执行序重导 frames + 重打标（`phase_label_run`），再跑监控；否则当月北极星读数会静默缺失。
- 首期（2026-09）S+A 触发率与 insufficient 占比为 null（无自动源）——人工补读位置：S+A 触发率看面板 S+A 触发统计；insufficient 占比看周期列「样本不足」占比（floor3 后基线 ~9.4%）。

## 4. 监护触发器（动作指引）

| 触发 | 含义 | 动作 |
|---|---|---|
| S+A 触发率持续 <3.5% | R3 verdictRule 预警线 | 评估 buyScoreThreshold 微调（走一次一候选） |
| insufficient 占比 >15% | floor3 效果回弹（基线 ~9.4%，floor5 原水平 14.7%） | 检查出池回池股构成，评估 floor 回退 |
| 相位划分不稳（月度监控连续发现方向翻转/显著月消失） | sentiment_2b 证据恶化 | 标签重打 + 地图重算（升版本）+ 重新评估相位定义 |
| 北极星走廊：offense 或 defense 连续 3 期达线 | 验收达成/防守兑现 | 达成项进入 M3 优先级重排 |

## 5. 可选观察项（登记不执行）

- **TDX 大盘情绪指数（DXQX_AG）历史回填**：帧级 `marketContext.marketStats.emotionValue` 仅 205/1071 帧（19.1%）有效——4-6 月浏览器采集链未接入、7 月起服务端链间歇性获取失败。回填技术可行（TDX 接口支持历史日期查询，走 python-bridge 逐日拉取），但 M2 主线（sentiment_2b，113 日全覆盖）不依赖它，且 breadth_v1 已被 M1 证据裁定弃用。**重启条件**：若相位定义需换/加信号源，先用零成本代理（`(upCount-downCount)/(upCount+downDown)`，marketStats 全帧可用）验证宽度类信息是否有增量，确认后再投资回填工程。

## 6. M3 移交

- **对照物**：相位-收益地图 gen7 基线（c385911d）；一切适配候选以"地图读数是否改善 + 北极星走廊"验收。
- **候选顺序**（设计 §5）：① 差相位降仓/空仓开关（直接兑现防守线；首期 defense 已双项过线，此候选聚焦"把 defense 的防守优势固化进规则"）→ ② 好相位入场放宽/加码（**前置条件：走廊数据证实 offense 劣势方向稳定后再定方向**——首期 offense 未过线且方向反直觉，暂不具备放宽依据）→ ③ 卖点按相位重审（吸收卖点课题；tp×be 市场状态依赖六次复现）→ ④ O8 双强相位收尾。
- **纪律**：M3 任何默认值变更走一次一候选 + 用户决策 + TDD + 锚复现；M3 立项走 writing-plans 另出计划（候选 ① 可在 10 月首期月度监控后评估立项）。
