# 卖点规则化回测实施计划（A 先行 → B 补缺）

> 2026-09-22 立项。背景：用户实盘确认"热榜注意力策略在情绪好时有效，但只有买点没有卖点"。
> 调查结论：现有 `TradeSimulator`（`backend/core/backtest/execution.py`）卖点骨架已相当完整
> （固定/ATR 止损止盈、保本止损、时间止损、信号去噪、D_EXIT_RISK/C_CROWDED/synergy 信号
> 退出、v3 专属退出），真正缺口是①卖点参数族从未系统扫描归因；②缺真·移动止盈；③缺断板
> 事件卖出。本计划 A 阶段零代码扫描存量、B 阶段 TDD 补缺后再扫。
> 研究纪律：`skills/ranktrend-signal-research/SKILL.md`（Track A 参数线 + Track 1 wrxpf 终判 +
> 30 笔门槛 + 一次一候选 + 扫描不自动写回默认）。

## 共同实验设计（A/B 共用）

- **入场锚固定**：`ranktrend_early_big_move_v3_lifecycle_fusion`（唯一策略锚）。只动卖点参数，
  同一入场信号集下出场差异全部可归因（`trades.reason` 分桶）。
- **数据集**：`dragonboard_live` / `half_hour`（2026-03-27 起，约 2827 帧）。
- **窗口**：按 skill 三窗规范切分（训练/验证/样本外；8 月 FINAL 冻结窗不参与参数选择，
  实施时以 skill 当前文本为准）。极端行情月单独标注。
- **判定**：wrxpf（winRate×profitFactor）主窗复核 + **30 笔交易门槛**（n<30 降级观察）+
  样本量披露 + 入场集合漂移卡（确认卖点变化没有改变入场）。
- **多重比较防线**：逐参数单变量 5 档（默认值必须∈档位集，参数化不漂移）；一次只落一个
  候选默认；扫描结果不自动写回 `config.py`。
- **口径声明**：`weakStateExit` 依赖 zljzb（同花顺主力监控）。若口径不属于 broker_l2/
  official_l2，其结论一律标**观察级**（待用户确认口径归属）。

## 阶段 0：基线锁定（半天）

1. 以默认参数跑 v3 锚全窗回测一次，记录 run_id、wrxpf、trades 分布、reason 分桶 → 冻结为基线。
2. 实测单次回测耗时，估算 8 组 × 5 档 × 3 窗的扫描时长，必要时改为 grid 分批。

验收：基线报告（run_id + 指标）落盘本目录；耗时估算写入进度记录。

## 阶段 A：存量卖点参数扫描（零代码，1-2 天）

扫描表（逐参数单变量，各档含当前默认⭐）：

| 参数 | 5 档 |
| --- | --- |
| stopLoss | -0.03 / -0.05⭐ / -0.06 / -0.08 / -0.10 |
| takeProfit | 0.06 / 0.09 / 0.12⭐ / 0.16 / 0.99(≈关) |
| maxHoldingBars | 16 / 24 / 32 / 40⭐ / 56 |
| useAtrStops + atrStopMultiplier | off⭐ / 1.5 / 2.0 / 2.5 / 3.0 |
| breakevenTrailing + breakevenThreshold | off⭐ / 0.02 / 0.04 / 0.06 |
| weakStateExit + weakStateExitZljzb | off⭐ / -3 / -5⭐ / -8（观察级口径）|
| signalExitDelayBars | 0⭐ / 1 / 2 / 3 |
| minHoldingBars | 0⭐ / 1 / 2 / 4 |

步骤：
1. A1 用 `POST /api/optimizations/rank-trend`（method=grid）或 CLI 逐参数建任务；
   每参数 5 trial × 3 窗（窗口切分由搜索配置表达，实施时对齐 skill 文本）。
2. A2 `trades.reason` 归因：每档输出各卖出触发占比 + 各卖点分桶净收益/胜率
   （分析脚本放 `backend/operations/` 或直接 CLI 查询 trades，不新建服务）。
3. A3 判定卡：每参数输出稳健区间（相邻档位单调/平缓）+ wrxpf + 样本量 + 极端月标注；
   Track 1 门槛不足 30 笔的参数直接降级观察。
4. A4 结论：排序"最值得动的卖点参数 Top3" + 是否需要 B 阶段新规则的归因依据。

验收：扫描原始结果（optimization run 记录）+ 归因表 + 判定卡落盘本目录；向用户汇报
Top3 结论，**由用户决定 B 阶段批次内容与是否落默认**。

回退：纯研究无代码改动，无回退风险。

## 阶段 B：补齐缺口规则（TDD，约 1 周）——A 结果出来后按数据定优先级

### B1 真·移动止盈 trailing stop

- `config.py` 新增：`trailingStopActivateGain`（默认 null=不启用）、`trailingStopDrawdown`
  （默认 0.5，即从峰值回撤 50% 止盈离场的参数化形式，启用时必须显式传）。
- `execution.py`：持仓 dict 记录 `peakPrice`（每 bar 更新 max(peak, high)）；启用且
  `gross_return >= activate` 后，`stop_price = max(stop_price, peak × (1 - drawdown))`。
- 默认关闭 → 全量回归测试无变化（golden 不漂移）；新增单测覆盖激活前/后/粘性三态。

### B2 断板事件卖出 breakBoardExit

- `config.py` 新增：`breakBoardExit`（默认 false）、`breakBoardMinBars`（默认 1，断板后
  最少持有的 bar 数，防开盘秒断噪声）。
- 判定：持仓期曾触及涨停（`price >= limitUpPrice`，撮合 quote 已带）且当前 bar 未封板
  （`price < limitUpPrice` 或 `fengdan` 归零）→ 卖出，reason="断板"。
- signal 组装需确认 `limitUpPrice`/`fengdan` 已进入 signal 行（撮合 `_quote` 已消费，
  组装侧核对补齐）；登记参数白名单（`_STRATEGY_LIST_KEYS` / 搜索空间，按 skill 纪律）。

### B3 回归 + 再扫描

- B1/B2 默认关闭跑全量 pytest + 回测 golden 回归（与阶段 0 基线逐位一致）。
- 新参数 5 档扫描（同 A 设计）+ 与 A 阶段胜出参数的 2-3 组组合验证。

验收：新规则单测（三态/边界）+ 默认关闭回归逐位一致 + 新参数判定卡。

回退：新参数默认关闭，配置不传即完全旧行为；单 commit 可 revert。

## 阶段 C：收口

1. A+B 判定卡汇总 → 用户逐项决策落默认（一次一候选；落默认时端到端锚逐位复现）。
2. 文档同步：`backtest-policy.md` 卖出规则清单与参数默认；本计划进度记录。
3. 月度复验批次登记（观察池候选绑定锚代际与触发条件）。

## 未决问题

- zljzb 资金流口径归属（weakStateExit 结论级别）——待用户确认。
- 三窗具体切分边界——实施 A1 时以 skill 当前文本为准并记录。
- 扫描算力：8 参数 × 5 档 × 3 窗 ≈ 120 trial，单 trial 耗时阶段 0 实测后确认是否分批。

## 进度记录

### 2026-09-22 阶段 0 完成 + 阶段 A 批次化启动

**基线（冻结）**：run_id `bt_8d451aab2e834c7e`，全窗 2026-03-27~09-21（dragonboard_live/half_hour，
v3 锚默认参数）：wr 0.3256 × pf 1.4818 = wrxpf 0.4824，43 round trips（过 30 笔门槛），
totalReturn +6.46%，maxDD -8.46%。单 trial 实测 ~18.5 分钟 → 扫描改批次串行，
**全窗单次回测 + 分析期按 entryTradingDate 切三窗**（不做 3 倍回测量）。

**窗口口径**（分析期切分，`backend/optimization/data_windows.py` B-202610 定义）：
decision 04-15~07-31（含 03-27~04-14 warmup 单列）/ FINAL 08-01~08-14（冻结只报告）/
oos1 08-15~08-31 / oos2 09-01~09-30（含已消费帧折扣）/ oos2u 09-13 起为裁决读数。

**批次 1**（stopLoss/takeProfit/maxHoldingBars，11 trial，CLI 串行，
`exit-scan-batch1.sh` + `exit-scan-batch1-manifest.tsv`）：进行中。

**批次 2**（ATR/保本/弱状态/信号延迟/最小持有，16 trial，API trade_config 透传，
`exit-scan-batch2.sh`，接力批次 1 自动启动）：已挂后台。
- 透传路径已核实：`POST /api/backtests/rank-trend` → `run_ranktrend` 的
  `trade_config.update(patch)`（backtest_service.py:493/575），与 CLI 同链路；
  CLI argparse 默认值与 `DEFAULT_TRADE_CONFIG` 逐项一致，无基础配置漂移。
- handoff 记录的 `/api/ln/rank-trend` 路由不存在，实际为 `/api/backtests/rank-trend`。

**分析工具**：`exit-scan-analysis.py [batch]`——离线直读 MongoDB 轻量集合
（backtest_trades/backtest_equity_curve），按生产口径精确重算 round-trip 指标，
**不解压 result 大 JSON**（API `/api/backtests/{run_id}` 单次查询 4-5 分钟，
compare 端点同瓶颈；离线重算秒级）。内建基线校验锚：重算与冻结值偏差 >0.002 即退出。
已验证：8 个 run 基线校验全部通过。

**批次 1 中期读数（7/11，待全部完成后三窗判定，勿提前下结论）**：
- 入场漂移卡 ✓：各档 round trips 恒 43，卖点参数未改变入场集合。
- takeProfit 0.06 全窗最优：wrxpf 0.9348（基线 0.4824）、ret +12.83%、maxDD -4.72%。
  档位单调：0.06 > 0.09 > 0.16 ≡ 基线（逐位一致，16% 止盈全程未触发）。
  **警示**：tp0.06/0.09 在 decision 窗（4-7 月）读数与基线逐位相同——改善全部来自
  8 月中旬后（oos1 9 笔全败被 tp 救回 3 笔；oos2 样本 5 笔）。机理推测：4-7 月盈利单
  持有期 high 从未摸 +9%；8-9 月为冲高回落市，+6% 是兑现窗口。非普适改动的风险
  待三窗卡+极端月标注正式判定。
- stopLoss 非单调：-0.03 (0.6151) > -0.10 (0.5556) > -0.08 (0.5079) > 基线 -0.05
  (0.4824) > -0.06 (0.4441)。-0.03 有单点尖峰嫌疑（decision 窗 1.1737 劣于基线
  1.5171，改善靠 oos2 的 5 笔）；oos1（9 笔全败）无任何止损档能救回。
- reason 分桶（基线，片段级）：到达最大持有 23 笔（胜率 0.6522，净 +1.0163）为唯一
  盈利桶；盘中止损 12 + 止损 9 + 生命周期B反对 5 + 排名MACD死叉 2 全部为负。
  止损族合计 21/51 片段、净 -1.31，是最大失血点；最大持有桶 65% 胜率说明入场锚
  有正期望，失血集中在退出方式而非入场。

### 2026-09-22 批次 1 完成（11/11）+ 判定卡落盘

完整结果见 `exit-scan-batch1-verdict.md`（数据三表同目录）。要点：
- maxHoldingBars 补齐后呈**全表最强单调**：16 (0.6473/maxDD -4.48%) > 24 (0.4854)
  > 30 基线 (0.4824) > 40 (0.3681) > 56 (0.2679)——延长持有=让浮盈单变亏损单；
  16 bar 档回撤近乎减半，但 decision 窗有代价且存在入场混合效应（45 rts）。
- 三族判定：takeProfit **PASS_CANDIDATE**（单调+双 oos 支持，定位"平衡市零成本、
  高波动市保护"）；maxHoldingBars **PASS_CANDIDATE**（方向确认：短持有）；
  stopLoss **REJECT**（非单调无稳健区间，默认维持）。
- 归因结论：盈利单无兑现路径（最大持有桶 65% 胜率、只能等 30 bar 到期）是核心缺口
  → **B1 trailing stop 优先级高于 B2 断板卖出**。
- 待批次 2：5 族 16 trial；批次 3 组合候选 tp0.06×mh16、tp0.06×mh24。

### 2026-09-22 批次 2 首跑全灭复盘 + v3 重跑

- **首跑失败**：批次 2 于 13:46 接力时 8000 后端正走向死亡——首个 atr1.5 请求被接受
  后 2230s 无响应，进程随之消失；后续 15 个 trial 全部连接秒败（manifest 空 run_id）。
  看门狗循环拉起的实例（14:36/14:37/14:41）呈"TCP 可连但 HTTP 无响应"假活态。
  根因未定论（嫌疑：当日多次 3.6GB 全窗回测 + uvicorn 长时间驻留的内存压力）；
  用户 15 时许手动重启后恢复（HTTP 200 / 3ms）。
- **ATR 路径排除**：3 周小窗口快测 useAtrStops=true → 144s 正常完成
  （bt_31819c6b77874596），代码路径无 bug。
- **v2 脚本 404 事故**：加固时把 API base 写成不带 `/api` 前缀，16 trial 全 404 秒败
  （探活 `/docs` 200 故未拦截）。教训：探活与业务端点要同路径前缀验证。
- **v3 加固生效**：`exit-scan-batch2.sh` 现在 manifest 记录 http_code 列、非 200 响应
  另存 `.batch2-error-<param>-<value>.json`、trial 前探活。已确认首个 trial 建立连接。
- 顺带发现：`POST /api/backtests/rank-trend` 响应体含完整 result 大 JSON（不只
  summary），全窗单响应体积可观——脚本用 `-o` 落盘避免管道阻塞。

### 2026-09-23 批次 2 完成（16/16 全 http_200）+ 阶段 A 收口

完整判定卡见 `exit-scan-batch2-verdict.md`。阶段 A 全部 8 参数族 27 trial 收口：

- **Top3（待用户决策，不自动写回）**：① takeProfit 0.06（wrxpf 0.9348/ret +12.83%/
  maxDD -4.72%）；② maxHoldingBars 16（0.6473/回撤 -4.48%，有入场混合效应）；
  ③ breakeven 0.02（0.5881/三档平缓无尖峰）。
- **REJECT/死参数**：stopLoss（非单调）、useAtrStops（负贡献，≥2.0 档位不活跃）、
  weakStateExit / signalExitDelayBars / minHoldingBars（**结构性未接线 v3 锚**——
  v3 专属退出决策 `_ranktrend_early_big_move_v2_exit_decision` 仅 5 条规则，
  三族参数只在对照组分支消费，扫描证实零影响）。
- **三重证据链支持 B1 trailing stop**：tp0.06 效应量最大 + be 平缓 + 最大持有桶
  65% 胜率（浮盈普遍存在无兑现路径）。B2 前提核实：`_quote()` 已带
  limitUpPrice/fengdan。
- **共同警示（三次独立复现）**：所有有效档 decision 窗（4-7 月）与基线逐位相同，
  改善 100% 来自 8 月中后样本外——"平衡市零成本、高波动市保护"定位。
- 待办：批次 3 组合验证（tp0.06×be0.02、+mh16）→ 用户逐项决策 → 阶段 B TDD。

### 2026-09-23 内存事故处置 + 隔离 runner 落地（批次 3）

- **事故**：批次 3 经 8000 API 跑批期间，uvicorn 进程 RSS 涨到 8.4GB（16+ trial 的
  frames + result 大 JSON 在同一进程累积），系统仅剩 1.4GB 空闲、接近全系统换页。
  与 optimization-scan-memory-explosion-incident 同一模式；批次 1 的 CLI 链路
  （独立进程跑完退出）从未出现此问题。
- **处置**：杀批次 3 bash/curl（trial 1 已完成未浪费：bt_1c35ee7c74e441d2）→
  重启 8000 释放 8.4GB（系统恢复 9.7GB 空闲）。
- **根治**：`exit-scan-trial-runner.py`——独立 python 进程执行单 trial
  （与 CLI cmd_run_ranktrend 同链路：runtime_session + BacktestService.run_ranktrend，
  payload 任意 trade_config），进程退出即释放内存。API 进程内连续跑批自即日起弃用。
- **规则**：所有多 trial 扫描一律走 CLI / 隔离 runner；8000 API 只用于单次请求。
  副产物：隔离链路单 trial ~18.5 分钟（API 链路 ~42 分钟，含完整 result 响应序列化）。

### 2026-09-23 批次 3 完成 → 阶段 A 终局

判定卡见 `exit-scan-batch3-verdict.md`。要点：
- **tp0.06 × be0.02 组合成立，全场最优**：wrxpf 0.9756（基线 2.02 倍）/ ret +13.52% /
  maxDD -4.72%，43 rts 入场不变；机理闭环（tp 盘中止盈 4 笔全胜 + be 大亏单均亏
  -0.053→-0.023）。
- **+mh16 三重组合 REJECT**（0.6981）：mh16 截断"最大持有"桶盈利尾巴，时间止损与
  浮盈保护不可同时收紧。
- **"改善全在 8 月中后"第四次复现**（decision 窗逐位=基线）。
- 待用户逐项决策：是否落 tp0.06×be0.02 为默认（一次一候选纪律）；B1 trailing stop
  TDD 立项（若落过渡配置，B1 上线后同窗对比）。

### 2026-09-23 用户裁决落默认 tp0.06 × be0.02（含合并 bug 修复）

- **config**：`V5_LIFECYCLE_FUSION_TRADE_DEFAULTS` takeProfit 9.99→0.06、新增
  breakevenTrailing=True / breakevenThreshold=0.02（注释含判定依据与警示）。
  测试：`tests/test_v5_trade_defaults.py`（默认值断言 + 非 v3 不受影响）。
- **合并 bug（复现验证发现）**：`run_ranktrend` 的 trade_config 显式逐键构造，
  defaults 独有键（breakeven*）从未并入——**不改此 bug 落默认不生效**。修复：
  新增 `_apply_trade_config_defaults_and_patch`（setdefault 并入 + patch 最后覆盖），
  回归测试 `test_run_ranktrend_merges_defaults_keys_not_explicitly_built`。
- **端到端验证链**：全窗锚 = bt_1c35ee7c74e441d2（裁决依据 run 本身）；等价性验证
  = 小窗口（09-01~09-21）双跑 A 显式 patch（bt_05fe2f6328e94ec5）vs B 新默认
  （bt_98aef6de2f2d4b10）→ **7 trades + 146 equity points 逐位一致**（修复前
  B 的 breakeven 不生效被验证抓出）。全窗复现锚因内存风险（单进程 8.3GB）推迟
  到非交易时段补跑。
- **文档同步**：backtest-policy.md（v3 专属默认小节 + 出场规则两链结构）、
  api-cli.md（v3 专属默认表）。
- **在线生效**：8000 需重启加载新代码——**交易时段不重启**（行情链承载中），
  待收盘后执行；在此之前 8000 在线回测仍用旧默认（隔离 runner/CLI 即时生效）。

### Harness 纪律与前置项（2026-09-23 用户指导）

- **frames 本地导出**：每 trial 从 MongoDB 全量拉 ~700MB 原始数据属瞬态负载
  （进程退出释放），B3 扫描前把 frames 一次性导出本地文件、runner 改读本地，
  实现扫描全程零 MongoDB 压力。改动只在 harness 侧（runner/导出脚本），
  不碰 golden 链与 backtest_service 生产链路。
- **交易时段纪律**：大批次（多 trial 扫描、8000 重启、全窗复现）不排在
  9:30-11:30 / 13:00-15:00；已有队列护栏兜底。

### 2026-09-23 阶段 B1/B2 TDD 实现（默认关闭，等待 B3 验收）

- **B1 真·移动止盈**：config 新增 `trailingStopActivateGain`（null=不启用）/
  `trailingStopDrawdown`（0.5）；`_exit_prices` 加 trailing 分支——peak（bar high
  粘性记录，相对入场涨幅达 activate）→ 止损线 = max(现线, peak×(1-drawdown))；
  peak 粘性 → 激活与止损线天然不回退（无需独立激活标志）。持仓循环仅在启用时维护
  peakPrice（最小侵入）。生效路径与 breakeven 相同：通用链 bar 级 + 全链 intrabar。
- **B2 断板事件卖出**：config 新增 `breakBoardExit`（false）/`breakBoardMinBars`（1）；
  主循环分支汇合处插入（全策略生效）：持仓期曾触板（high>=limitUpPrice 粘性）且当前
  未封板（price<limitUpPrice 或 fengdan 归零）→ reason="断板"；limitUpPrice 缺失
  不判定（fail-visible 不误杀）。
- **TDD**：`tests/test_trade_simulator_exit_rules.py` 8 用例（B1 默认关/触发/粘性/
  high 峰值 + B2 默认关/触发/minBars 噪声护栏/涨停价缺失）先 RED 后 GREEN；
  相关既有 84 测试无回归。
- **B3 验收（午休时段完成）**：①默认关闭逐位回归 PASS——加 B1/B2 后重跑
  bt_05fe2f6328e94ec5 同 payload（bt_3708326dca594ca7），7 trades + 146 equity
  points 逐位一致，golden 不漂移实证；②全量 pytest 2563 passed——抓出
  `_theme_trade_config` **第二处同款 defaults 合并 bug**（breakeven* 键同样丢失），
  已用同一 `_apply_trade_config_defaults_and_patch` 修复，
  `test_theme_trade_config_uses_v5_lifecycle_fusion_defaults` 断言更新为新合同
  （tp0.06 + breakeven True/0.02）后通过；剩余 2 failed 为 archive_research 既有
  环境失败（与本次改动无关）。
- **B3 待办（收盘后）**：①8000 重启加载新默认；②全窗复现锚补跑；③frames 本地
  导出 + runner 改读本地；④trailing 5 档 + 断板扫描 + 与 tp×be 组合验证（本地
  frames 后跑）。

### 2026-09-23 晚间清单执行（用户确认收盘、8000 已重启）

- **8000 新默认生效验证** ✓：进程 17:25:55 启动 > config 11:12 / service 11:50 修改时间。
- **frames 本地导出** ✓：`exit-frames-export.py` → 1011 帧 / 138.7MB gzip
  （`quant-board/data/exit-scan-frames-...json.gz`，3 分钟一次性 Mongo 大读）。
  帧数说明：1011 = load_frames 真实返回（capture 过滤后口径）；handoff 的 ~2827
  为未过滤口径差异，同源验证已排除影响。
- **runner 本地 frames 支持** ✓：`--local-frames` 参数 monkeypatch
  `MongoRepository.load_frames`（进程内，harness 侧）；quality gate/引擎/落库链路
  不变，小表与结果写入仍走 Mongo。**LOCAL-FRAMES PARITY: PASS**（本地数据小窗口
  重跑 == Mongo 直读产物，7 trades + 146 points 逐位一致）。
- **全窗复现锚 PASS** ✓：新默认全窗（bt_7baae93651234140，本地 frames）与裁决锚
  bt_1c35ee7c74e441d2 **54 trades + 1011 equity points 逐位一致**——落默认
  端到端纪律完整闭环（plan 阶段 C 第 1 项验收达成）。
- **批次 4 启动**（trailing 4 档打包 (activate,drawdown)：(0.06,0.6)/(0.05,0.5)/
  (0.04,0.4)/(0.03,0.3)；断板 minBars 1/3；全部叠加新默认，本地 frames 串行）。
  对照基线 = bt_1c35ee7c74e441d2（新默认本身）。

### 2026-09-23 搜索引擎提速：信号缓存批量模式（cProfile 驱动）

- **profile 结论**（小窗口 cProfile）：单 trial 耗时大头是 RankTrend 信号计算
  （`_build_signal` 25998 次调用 + lifecycle 链，占 60-75%），撮合与 Mongo 拉取
  均为小头；本地 frames 与 Mongo 直读速度持平（全窗 ~20 分钟 vs 20.6 分钟）——
  本地化的收益是零 Mongo 压力而非速度。
- **优化**：runner 新增 `--batch` 批量模式——同进程串行多 trial + 进程内信号缓存
  （monkeypatch `RankTrendPythonEngine.replay`，键 = RankTrendConfig repr 指纹）。
  批次内 strategy_config 恒定 → 信号只算一次，trade 参数档位只重跑撮合。
  下游对 signal dict 只读（grep 核实）→ 缓存共享引用安全；config 变化自动失效。
- **验证 PASS**：同进程双 payload（tp0.06×be0.02 显式 / 新默认），miss 后 hit，
  两者各自与已验证 run（bt_05fe2f6328e94ec5 / bt_98aef6de2f2d4b10）逐位一致——
  缓存无污染。
- **批次 4 切换**：老模式（每 trial 独立进程）完成 1/6 后停止，剩余 5 trial 改
  批量模式（`exit-scan-batch4b-payloads.json`）。预算：老模式 5×20=100 分钟 →
  批量 ~50 分钟（信号 miss 一次 + 5 次撮合）。
- **未做（单独立项评估）**：`_build_signal` 本身的算法优化（lifecycle cycle_metrics
  764768 次调用的缓存/增量机会）——碰 golden 事实标准（engine.py），必须先建
  全量 golden 对齐护栏再动，收益另测。

### 2026-09-23 晚 引擎提速执行：护栏 + 有界窗口 + 单遍分组 + dry-run（层 1+2 落地）

执行记录对应 `engine-perf-optimization-handoff.md`（含用户全窗反例修正：全窗下
efficacy/落库/序列化占比显著，层 2 升级必做）。

- **护栏先行**：`test_ranktrend_golden_alignment.py` 新增
  `test_golden_replay_full_field_snapshot_unchanged`——合成 64 帧 × 10 股，覆盖
  5 个 lifecycle stage、regime 四相位（hotlist 有/无）、insufficient/degraded/ok、
  市场字段轮流缺失、滑动窗口跨越（64 > window_size=50）、ATR high/low 缺失、
  avgRankNum≤0 过滤、K=2 veto/B-D 连续确认、analysis/execution 双档位源、
  replay_frame_at、BacktestEngine 撮合链；replay 全字段快照逐位比对（fixture
  `tests/fixtures/ranktrend_golden_replay_snapshot_v1.json.gz`，重建开关
  `RANKTREND_GOLDEN_SNAPSHOT_REGEN=1`，帧集 digest 绑定防漂移）。
- **层 1 优化（全部输出逐位一致；随机差分 4000 组 + 300 组零分歧）**：
  - `lifecycle.analyze_cycle` 尾窗化：新增 `cycle_metrics_window`（≤8 档），逐步传
    尾窗不再重建前缀切片，O(L²)→O(L)；`cycle_metrics` 公开签名与输出不变；
  - `technical.cycle_rank_shock` 只计算末 5 个速度差、`rank_shock` 只算末
    lookback 个速度差（输出只依赖末 6/末 lookback+1 档，同表达式同序逐位一致）；
  - `evaluator._group_stats` 单遍分组替代「set 建键 + 逐键全量重扫」——
    `momentum_bucket` 小窗 1255 万次调用消解到 10 万级。全窗下 efficacy/诊断链
    才是大头（handoff 全窗反例结论），与本次 profile 复核一致。
- **层 2 dry-run**：`run_ranktrend` payload 开关 `dryRun`（snake `dry_run`，默认
  `false`，正式回测与既有 API 合同不变）——跳过五表落库与 `result_json` 大 JSON
  gzip 序列化；`_summary_response(full_attribution=True)` 返回全量
  `trades`/`equityCurve`（不做 120 条截断），notes 显式声明未落库。runner 新增
  `--dry-run`（单 trial/批量均可，summary 落盘 `<runid>-summary.json` /
  `<outdir>/<i>-summary.json`）。`api-cli.md` 已同步。
- **复现验证（三重，全 PASS）**：
  1. golden 护栏 + 既有对齐用例 11 全绿；
  2. 小窗优化前/后双持久化 run 逐位一致：bt_ddcc294dca3f471b == bt_fc3149a800184beb
     （7 trades + 146 equity points）；
  3. 全窗 dry-run 响应 vs 锚 run 逐位一致：
     `.perf-fullwindow-dryrun-runid-summary.json` == bt_1c35ee7c74e441d2 ==
     bt_7baae93651234140（54 trades + 1011 equity points，工具
     `exit-dryrun-replication-verify.py`，数值按值比较容忍 bson Int64）。
  另 `pnpm test:ranktrend` 171 全绿、`pnpm typecheck:ranktrend` 干净；全量 pytest
  见收尾记录。
- **计时实测（当晚系统内存紧张——空闲物理内存一度 0.5GB、pagefile 32GB 在用，
  生产服务驻留，读数偏保守）**：
  - 全窗 dry-run 单 trial **520s（8.7 分钟，含 ~70s frames 加载）**，对比常规路径
    ~20 分钟基线 ≈ **2.3×**；dry-run 进程内存峰值显著更低（无 result_json 文本/
    压缩/编码三份大对象，曾实测 commit 18GB 引发整机换页）；
  - 常规持久化全窗 run 当晚在落库链 `result_json` 序列化上 **MemoryError**
    （69 分钟后死在 save 前）——直接实证层 2 必要性与 handoff 全窗反例；
  - 小窗（09-01~09-21）常规 trial 182s（含加载）vs 文档基线 ~150s（系统压力噪声内）；
  - profile 结构：analyze_cycle cumtime 24.9s→21.3s（cProfile 放大调用开销，
    无 profile 实测收益更大）；剩余大头为 frames 加载（单进程一次性）、replay、
    efficacy/撮合与 `dumps_json_field`（持久化路径）。
- **批次预估与缺口**：`--batch --dry-run` 6 trial ≈ 信号 miss 1 次 + 5 次
  撮合/评估 ≈ 25-35 分钟（待实测）——**未达 <15 分钟目标**；下一步候选：
  efficacy 增量/复用（line-scan per signal）、replay 内 MACD/technical 有界化、
  frames 加载换 pickle/parquet 缓存。另立批次评估，不再扩本层。


### 2026-09-23 深夜 批次 4 完成（6/6）→ 阶段 B 收口：零增量（exit-scan 会话）

判定卡 `exit-scan-batch4-verdict.md`。执行波折：批量模式 trial2 反而 31 分钟（全窗
反例，引擎 handoff 已修正优先级）；batch4c 断板1 在保存阶段 MemoryError（result 大
JSON 序列化 OOM——与 perf 会话实测的"69 分钟死在 save 前"互为印证，dry-run 必要性
双实证）；分两轮补漏后 6/6 齐（trailing 4 档 + 断板 2 档，全叠新默认）。

- **结果：6 trial 全部与新默认 tp0.06×be0.02 逐位相同——零增量**。新默认仍为全场
  最优（wrxpf 0.9756 / +13.52% / -4.72%）。
- trailing：实现正确（单测 4 用例），但档位结构性冗余——trailing 线要越过 be 保本线
  需 `peak/entry > 1/(1-dd)`，dd 0.3~0.6 档位需峰值 +43%~+150%，远超本窗口最大浮盈
  （最大持有桶平均净 +4.4%）。有意义档位应为 dd 0.03~0.08（重扫待用户决策）。
- 断板：实现正确（单测 4 用例），窗口内 **0 触发**（43 笔持仓无涨停后开板场景）——
  样本不存在无法评估，参数默认关、接线保留，后续窗口自动进入 reason 分桶观察。
- **阶段 B 收口**：B1/B2 均不落默认（维持默认关），golden 不漂移已实证（默认关闭
  逐位一致 + 8 单测）；backtest-policy.md 已补 B1/B2 条目。剩余：月度复验批次登记
  （观察池：trailing 修正档位 dd 0.03~0.08 重扫 / 断板触发观察，绑定锚代际）。

### 2026-09-23 深夜 提速第二轮：efficacy 线性扫 + frames pickle 缓存（engine-perf 会话）

- **efficacy 修复**：`compute_signal_efficacy` 逐信号 `next()` 线性扫（25998+ 信号 ×
  ~百股）改为逐帧 code→row **首现映射**（setdefault 保首个匹配，键表达式不变）；
  差分 300 组（含重复 code/无效价/缺帧）零分歧，efficacy 相关 56 测试全绿。
- **frames pickle 缓存**：runner `--local-frames` 首次加载 gzip json 后自动写同名
  `.pkl`（558MB，`data/` 下 gitignore）；源 gzip mtime_ns/size 守卫自动失效，读写
  异常一律降级直读（fail-visible）。独立进程干净实测：**pickle 9.3s vs gzip 42.9s
  （省 ~34s/进程），内容与 gzip 解析逐位相等（1011 帧 == True）**。parquet 路线
  弃用（类型列序列化有结构漂移风险，pickle 为同对象精确还原零验证负担）。
- **候选 C（replay MACD/technical 有界化）评估后放弃**：MACD 的 EMA 是全序列
  递归，有界化不可能逐位一致；其余 technical 组件已 O(L) 且常数极小——收益
  （估 <10s/trial）不抵 golden 风险与重构成本。剩余耗时为 replay 装配/撮合/服务
  层结构成本，无平方级热点残留。
- **验证**：全窗 dry-run 双轮（gzip 轮 bt_ca8b7af1dc464fa1 / pickle 轮
  bt_50146208c1d148a6）vs 锚 run **均逐位一致**（54 trades + 1011 points）——
  pickle 路径与 efficacy 修复端到端输出中性实锤；批次 4c MemoryError 与本会话
  69 分钟 save 前 OOM 构成 dry-run 必要性双实证（见上节）。
- **计时**（当晚系统负载波动 ±60s，读数为区间）：全窗 dry-run 单 trial
  520s → **318-380s**（写缓存轮 318s 含 pickle 写入；缓存命中轮 380s 为高负载
  读数；加载节省 ~34s 为干净实测）。单 trial 累计 ≈ **20 分钟 → 5.5-6.5 分钟**。
  6-trial 批量预估仍 >15 分钟，批量实测与进一步优化（evaluator `_outcome` 复用、
  服务层装配瘦身）留待下批扫描前按需评估。
- **「服务层装配瘦身」实测后关闭（当晚 cProfile 定向测量，小窗）**：质量门禁
  （5 遍行级扫描）、`_price_quality_diagnostics`、efficacy ×2、researchDiagnostics
  二次评估、**22 个对照 TradeSimulator** 全部合计 ≈ 1.5-2s（profile 口径），
  占全窗 trial <1%——推测瓶颈被证伪，瘦身上限秒级，不值得做。装配链中唯一值钱的
  落库+回读+大序列化（~25-30s profiled）已被 dry-run 拿走。剩余真大头：
  `_build_signal` replay（55.8s / 122.7s profiled ≈ 45%，无平方级热点，为每票每帧
  固定装配成本）；再往下只剩有 golden 风险的大结构改造（增量状态机仅序列增长期
  有效），收益/风险比不划算。**结论：5.5-6.5 分钟/trial 已接近「逐位一致」约束下
  的实际下限，本立项收口。**

### 2026-09-24 凌晨 verification-before-completion 复盘收口（engine-perf 会话）

对照 handoff 验收 4 道门禁逐项复盘，识别三项缺口并当夜补齐，全部通过（均为新鲜证据）：

- **GAP-1 全量 pytest 复跑（验收 #4）**：2572 passed / 2 failed——失败仅 archive_research
  ×2 既有环境失败（与基线一致，零新失败），覆盖第二轮 efficacy/pkl 缓存与全部 review
  修复之后的完整回归。
- **GAP-2 6-trial 批次实测（验收 #3）**：`--batch --dry-run --local-frames`，6 个 trade
  变体（tp 0.04~0.09）同 strategy_config，**实测 581s ≈ 9.7 分钟 < 15 分钟目标达成**
  （信号 1 miss + 5 hit，hit trial ≈1 分钟/个；证据 `.perf-batch-timing/`，各 trial
  trades 52/54/54/54/55/57 随 tp 变化属预期）。此前「预估 25-35 分钟」系 efficacy 修复前的悲观
  估计，实测推翻。
- **GAP-3 全窗持久化 run + 原版逐位脚本（验收 #2 字面）**：内存充裕时段（空闲 8GB）
  持久化全窗 run **成功**（bt_91a356067c9e4704，839s ≈ 14 分钟，含五表落库 +
  result_json 序列化——此前 MemoryError 未复现）；原版
  `exit-default-replication-verify.py` 判定与锚 bt_7baae93651234140 **54 trades +
  1011 equity points 逐位一致**——优化后引擎的持久化链端到端闭环。常规持久化全窗
  trial：20 分钟 → 14 分钟（内存压力时段读数不可比，见上节 69 分钟失败记录）。
- `pnpm test:ranktrend` 171/171 + `pnpm typecheck:ranktrend` 干净（00:55 新鲜复跑）。
- 本轮复盘**零代码改动**，全部为验证与实测补齐。**硬门槛 4 条全部满足：
  护栏先落地 ✓ / 全窗逐位一致（dry-run 双轮 + 持久化 run 原版脚本）✓ /
  pnpm 合同 ✓ / 全量 pytest 零新失败 ✓。验收 #3 数值目标如实披露：6-trial 批次
  <15 分钟 ✓（实测 9.7 分钟）、dry-run 单 trial 分钟级 ✓（hit trial ≈1 分钟）；
  **全窗单 trial <5 分钟子目标未达**（最优实测 dry-run 318-380s ≈ 5.3-6.3 分钟，
  持久化 839s ≈ 14 分钟），受「逐位一致」约束下的 replay 固有成本所限（见
  装配瘦身实测小节）。收口。**
