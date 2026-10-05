# jev 涨停打标链路代码审查与四批次落地记录（2026-10-05）

> 审查对象：`backend/operations/jev_label_jiuyan.py`（写入端主链）、`backend/services/jev/*`、
> `backend/api/hotlist_jev_limitup_routes.py`（读口）、`backend/operations/schedule.py`（盘后挂链）。
> 用户裁决：批次 A→B→C→D 全部执行；I6/I7 不整月重跑（旧文档留档、新文档新口径）；M1 死代码删除。
> 全程未触发真实 jev 调用；全部测试 mock/fixture。全量 pytest 3221 passed（2026-10-05）。

## 关键事实修正

- `hotlist_jev_limitup_routes.py` 是纯读口（31 行）；打标写入端是 `operations/jev_label_jiuyan.py`。
- 已落库读数契约：`hotlist_jev_driver_labels`（个股 `_id={date}:{code}`、相位 `_id={date}:PHASE`）。

## 已落地（按批次）

### 批次 A：解析层与读口（红线 §1.2-3 / 领域红线⑥③）

| 项 | 修复 |
|---|---|
| C2 | `parse_jev_response` 增 `expected_keys`：Completed 但缺题 → `degraded/partial_answers`，已答部分保留；`done` 幂等集合不再把缺题文档当完成，下轮重跑补齐 |
| I1 | score 缺 legend/缺 score 不再产出负数（旧实证 5→-500）/KeyError，分数如实缺席 |
| I2 | `call_jev` 捕获面补 `JSONDecodeError`/`http.client.HTTPException`（HTML 错误页不再炸 run） |
| C1 | `collect_limitup_labels` 不再按 `status=ok` 静默过滤：`summary.degraded/degradedCount`、`phaseStatus/phaseError` 结构化暴露；`stocks` 保持 ok-only（前端合同不变）；`noData`=该日零文档 |
| I5 | `schedule.py` 5 处 `mongo_error` 吞异常改结构化回传（`mongoWarning`/`verifyError`）；打标步新增 `degradedToday` |

### 二次修正（2026-10-05 用户裁决「涨跌停阈值公共函数，禁硬编码副本」）

- 新增唯一权威源 `backend/core/limit_rules.py`（分层=core 交易规则）：`limit_ratio`（精确比例 0.10/0.20/0.30）、`limit_up_price/limit_down_price`（真实涨跌停价）、`limit_threshold_pct(code, tolerance_pct)`（pctChange 判定线，默认容差 0.2pp → 9.8/19.8/29.8；heat 链 0.7 → 9.3/19.3/29.3 逐位等价）、`is_limit_down_pct`。
- 委托改造：`hotlist/sentiment.limit_threshold`、`snapshot_derivation/projection._limit_ratio_for`、`theme/heat._limit_up_threshold`、jev `_limit_pct_of`/`dieban_count` 全部单源化（历史副本退役，行为逐位等价）。
- **口径修正**：撤销批次 B 的 ST ±5% 特判（含 dieban ST -4.8）——2026-09 新规主板 ST 亦 ±10%，全市场无 ST 特判（与前端 StockUtils/规则链/快照派生一致）；相关测试改为新规断言。
- **ranktrend 域 4 处副本不接入**（`ranking/volume_price._daily_limit_pct`、`engine/config.regimeLimitUpChange`、`trend/risk.REGIME_LIMIT_UP_CHANGE`、`research/live_gate_shadow_audit`）：golden 红线，行为冻结；其前缀口径（`4`/`9` 单字符、300/301/688/689）与权威源（`30`/`43`/`8`/`92`）存在已知差异，留待 golden 改门时统一。
- 测试：新增 `tests/platform/test_limit_rules.py`（9 例）；jev 原料测试 ST 断言改新规。

### 批次 B：原料口径（领域红线⑥①，新文档盖 `ammoVersion="2026-10-05a"`，不重跑历史）

| 项 | 修复 |
|---|---|
| I6 | 涨停判定线精确化 `×1.10/0.20/0.30/0.05`（旧 ×1.098 系统性少算 1–6 分钱致近板误判） |
| I7 | `dieban_count` 补 ST ±5%（创业/科创/北交 ST 仍按板籍；行缺 name 按主板，不伪造） |
| I8 | `ths_positions/market_metrics/dieban_count/advdec_ratio/hotlist_ranks` 全部带 `datasetId`，帧查询带 `type` 并 `sort` 取最新帧；缓存键=(dataset, date)；CLI 增 `--dataset-id` |
| I9 | `trading_dates_before` 改查 `snapshot_frames`（不再全表扫 `snapshot_stock_rows`） |

### 批次 C：稳定与成本

| 项 | 修复 |
|---|---|
| I3 | `work()` 单股异常隔离：单股异常重试后放弃并打印 `last_error`，不炸整日/后续日期 |
| I4 | TDX 全节点不可用 → 5 分钟负缓存（旧实现每股重探 8 节点×6s，100 只会撞 2700s 超时） |
| I12 | `FINAL` 成本口径=本次运行实付（`_usage_tokens`：total_tokens 优先，≤0 回退 input+output），不再全集合扫历史 |
| I13 | 预算护栏：`run()` 未 `confirm_budget=True` 拒绝开火（排程链 `--confirm-budget` 携带 2026-10-03 挂链裁决）；`--max-stocks` 上限；`tests/conftest.py` 新增 autouse 护栏——测试触真实 CF 端点立即显式失败 |
| I15 | 打标/相位/周期文档盖 `questionSetVersion="v3.1"` + `questionSetHash`（题集哈希，改一字即换代）；相位补跑幂等判断优先哈希、旧文档回退整 dict 比对 |

### 批次 D：结构整理（行为不变）

| 项 | 修复 |
|---|---|
| I14 | 新增 `backend/analysis/hotlist/jev_driver_ammo.py`（295 行纯函数层：全部题目常量、题集哈希、`_strip`/`percentile_rank`/`_limit_pct_of`、三个 TDX 叙事纯计算 `*_from_bars`）；runner 留 IO/编排薄壳（873 行），对测试保持原符号名 |
| M1 | 删除 v2 残留 `jev_state.build_jiuyan_label_narrative` 及其测试（生产零调用，git 留档） |
| M2 | `SCORE_ANCHORS` 单源（jev_client 重复副本删除）；CF 账户 ID 单源 `jev_client.DEFAULT_ACCOUNT_ID`（原 4 处字面量） |
| M3 | `_DAY_STAGE_CRITERIA_V2` 空操作 replace 改直拷贝（行为逐字不变） |
| M4 | TDX 节点配置路径相对化（仓库同级 `python-bridge/tdx_hosts.json`）+ `TDX_HOSTS_PATH` 环境变量覆盖 |
| — | `assert tok`/`assert start` 改显式 `SystemExit`（M5）；打标步子进程命令带 `--confirm-budget` |

## 测试影响

- 修正 3 处「部分答案冒充 ok」的旧 fixture（test_jev_sentiment_compute / test_hotlist_jev_api ×2）——它们正是 C2 缺陷的复刻。
- `parse_jev_response` 补丁 lambda 统一 `**_kw`；schedule 步测试 FakeCol 补 `status` 字段并断言 `degradedToday`。
- 新增测试：`test_jev_client`（partial/score/网络异常 6 例）、`test_jev_limitup_labels`（degraded 暴露 3 例）、`test_jev_label_raw_material`（阈值/ST/datasetId/ammoVersion 11 例）、`test_jev_label_run_guards`（隔离/负缓存/成本口径/代际戳 7 例）、预算护栏 1 例。

## 遗留与未决

0. **ranktrend 域阈值副本**（见上「二次修正」）为已知独立口径，golden 改门时统一。

### Subagent code review 结论（2026-10-05，reviewer 独立审查：APPROVE）

- **无 Critical**；委托点逐位等价、partial 重跑闭环、预算护栏、conftest 护栏、golden 未触碰均核验通过。
- **Important 1（存量，须改门任务，勿顺手改）**：`core/backtest/execution.py:1585` `_limit_pct_threshold` 是另一份未收敛阈值副本（302 误归主板 9.8；`"9"` 单字符前缀会误吃沪 B 900xxx）——属回测口径红线，须独立改门裁决后以 `limit_threshold_pct` 委托改造。
- **Important 2（已修）**：`jev_label_jiuyan_report.py` 的 `LIAN_BAN_PCT=9.8` 全板块单线，会把创业/科创 +9.8%~19.7% 非涨停涨幅误计为连板——已改为 `limit_threshold_pct(code)` 按板籍判定线。
- **Minor（已修）**：`stock_board_shape_line` 壳后残留重复 except（批次 D 平移残留）已删；`test_jev_label_raw_material` 模块 docstring 与新规断言漂移已同步。
- **登记知悉**：① partial 文档下轮重跑遇更差结果会被 `replace_one` 覆盖（status/errorCode 可见非静默，建议后续字段级合并）；② 预算护栏覆盖面=run()（其余入口按既定批准口径）；②两个 pilot 文件的 `expected_keys` 未扩展（非本次声明范围）；③ `_daily_bars` 失败永久缓存 `[]`（跨进程自愈，存量行为）。

1. **I11（未动，需数据验证）**：同股多板块时 `items[code]=` 静默保留最后板块，与 `board_position` 取封板序最前可能不一致；影响面需查库后裁决。
2. **前端展示增强（未做）**：limitup-labels 新增 `phaseStatus/phaseError/summary.degraded/degradedCount` 为 additive 字段，TS 类型未扩展、面板未展示降级计数——建议后续 UI 任务带浏览器验证一并做。
3. **M6**：TDX 日线 60 根/5 分钟 800 根窗口限制仍在（回填更早日期板型如实缺失）；**M9**：`/series`、`/range` 全量拉取未加 projection；**M10**：叙事硬截断无标记。均低优先。
4. **代际断层**：`ammoVersion`/`questionSetHash` 只对新落库文档存在；历史文档按「缺戳=旧代」解读（fail-visible），跨代对比需按 `tradingDate` 分段（同 2026-10-02 拥挤离散化教训）。
