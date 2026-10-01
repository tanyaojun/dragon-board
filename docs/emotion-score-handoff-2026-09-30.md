# HANDOFF — 规则情绪连续评分体系（路线 B）实施交接

- 日期：2026-09-30（午间休市时点交接，T1 已完成，T2 待审计后启动）
- 交接原因：对话过长 token 消耗大，开新对话继续实施
- **⚠️ T2 前置门槛（用户明确要求）：必须先对方案与计划做对抗性审计，优化修改后才能进入 T2**（见 §5）

---

## 1. 一段话现状

规则情绪五档（`sentiment.py::resolve_stage` 布尔级联）经历史实证确认存在结构性缺陷（阈值无验证、高潮档数学不可达、五档退化双档开关、确认机制压制当下状态），用户裁决走路线 B：**EOD 情绪档位主定义直接切换为连续评分驱动**（score 0-100，8 维等权，1066 槽历史分位校准），旧级联降级为 `legacyCascadeStage` 对照面。T1（评分核心 `emotion_score.py`）已完成提交；**T2（golden 链切换）未开始，且启动前必须完成对抗性审计**。

## 2. 必读文档（按序）

1. `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（**v2 设计规格**——切换方案、分段校准表、验收标准）
2. `docs/superpowers/plans/2026-09-30-emotion-score-plan.md`（7 Task 实施计划）
3. `quant-board/docs/hotlist-jev/hotlist-jev-emotion-observe-design.md`（jev 观察轨道 v3——评分的原料同源方）
4. `docs/superpowers/specs/2026-09-24-emotion-stage-multiframe-confirm-design.md`（现行确认机制——T2 要平移其语义）
5. `AGENTS.md`（项目纪律）+ `quant-board/docs/AI_COLLABORATION.md`

## 3. 决策链（用户裁决记录，勿再重议）

| 时间 | 裁决 |
|---|---|
| 09-30 早 | 方向重置：golden 不是 ground truth（循环论证作废）；jev 与规则=并列观察者；jev 轨道 v3（纯原始证据、零规则输出、双问题）已实施并上线 |
| 09-30 盘中 | 双轨对照（09-24~29 三日）：规则在修复日无梯度（09-29 全天退潮）vs jev 有轨迹（冰点→发酵→高潮）；用户复盘"规则无梯度确认、jev 弱转强给强定义，两者互补但都不对" |
| 09-30 午 | 用户质询强资阈值验证数据 → 实证：1066 槽强资 effective_spread 触发率 3.9%、crowdedShare 历史最大 0.057 vs 高潮门槛 0.16（**高潮档历史 0 次**）、五档退化双档开关；zljzb≥8 源自 tooltip 口径沿用，零验证记录 |
| 09-30 午 | 用户否路线 D（阈值校准=拟合弯路），**拍板路线 B：连续评分替代布尔级联**；两决策：①等权设计但须进回测平台验证；②**直接切换 EOD 主定义**（现行级联已确认瑕疵，不设并行观察期） |
| 09-30 午 | **T2 前必须对抗性审计**（本文档 §5） |

## 4. 当前状态

### 已完成（全部已提交，工作区无本任务未提交文件）

- **T1 评分核心**：`quant-board/backend/analysis/hotlist/emotion_score.py`（commit 028bae8a）
  - `compute_emotion_score(evidence) -> {score, dims, skippedDims, stageCandidate}`：8 维等权（广度/攻击占比/风险占比反向/TRIN反向/昨日承接/涨停结构/量能同期/风险行占比反向），分段线性插值，缺维跳过+权重归一化
  - `map_stage(score, risk_rows_pct, slope)`：≥75 高潮（风险行占比>70% 压制→发酵）/ 60-75 发酵 / 40-60 启动 / <40 按斜率分退潮·冰点
  - `_CALIB`：分段边界全部注明出处（1066 槽 half_hour 分位，2026-09-30 校准）
  - 测试 `tests/hotlist/test_emotion_score.py` 6 passed（含强多/强空/缺维/映射边界）
- **jev 轨道 v3 已上线**（前序工作）：`hotlist_jev_sentiment` 双问题评判，原料含 TRIN/强资风险标记/总额同期；8001 gate 已开（`quant-board/.env.local` 的 JEV_SENTIMENT_ENABLED=true + JEV_CF_TOKEN）
- 8000/8001 已重启（今日 13:00 槽起叙事带行级标记占比 + 指数×量能合并行）
- **历史实证数据**（分析已做，结论可直接引用）：1066 槽分布分位数见 spec §2 表格

### 待做（按 plan 顺序，T2 起步）

- **T2 链切换（本次交接的核心待办，审计后执行）**
- T3 写口接线 + API 缓存 v3
- T4 前端情绪分展示
- T5 历史重算（backfill slots + EOD）+ 新旧档位 diff 报告
- T6 回测 replay 新旧对照（regime/分层影响量化）
- T7 全量验证 + 文档同步

## 5. ⚠️ T2 前置门槛：对抗性审计（必须先做）

新对话接手后，**第一步不是写代码**，而是对 `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（v2）与 `docs/superpowers/plans/2026-09-30-emotion-score-plan.md` 做一轮对抗性审计（以"攻 disembowel 这个方案"的立场找漏洞），产出审计报告（放 `docs/superpowers/specs/2026-09-30-emotion-score-audit.md`），修订 spec/plan 后才进 T2。

### 审计必查清单（交接时已识别的风险线索，逐一攻防）

1. **score 缺失槽的档位语义未定义**：evidence 全缺（如帧存在但行全缺）→ score=None → stage 显示什么？spec 未写。回退级联？no_data？——必须定义（倾向：回退 legacyCascadeStage 并标 diagnostics，但需审计确认）。
2. **分数域确认与 `stage_confirm.confirm_stage` 复用的边界**：
   - 跨日重置语义（现行 stage_confirm 有跨日重置，分数域平移后是否保持）；
   - 当日首槽（无历史轨迹）确认状态；
   - prev_state 的存储与传递路径（EOD 锚定槽与槽位文档各自的确认状态如何演算——现行实现是每次用当日轨迹重放，分数域是否同样重放 score 序列？score 序列需要当日逐槽 score——重算成本与数据可得性）。
3. **维度相关性与双计**：riskShare（风险行占比）与 riskRowsPct（同一计数换基）**高度相关甚至同源**——等权下风险被双计；upRatio 与 attackShare 分子重叠（点火/扩散行同时是上涨行）。等权是否成立需要审计论证，或合并维度。
4. **分段校准的循环性**：1066 槽分布是旧市场结构的产物；市场结构变化（如牛熊切换）后分段漂移，score 语义随之漂移——是否需要周期性重校准机制？重校准的裁决流程？
5. **RankTrend 策略层影响量化不足**：`risk.py:134` `stage_adjust`（五档对 regime score 加减）消费 stage——切换改变档位序列 → 策略历史回放 diff 只在 T6（切换后）。审计要决定：diff 是否应前移到 T2 之前（先对照再上线）？用户已拍板直接切换，但审计需确认回退方案（resolve_stage 保留切回）在策略链上同样可回退。
6. **历史重算的 as-of 一致性**：重算改写 `hotlist_sentiment.stage` 历史 → RankTrend as-of 消费（消 lookahead 语义）的历史一致性；回测 replay 用 legacyCascadeStage 还是新 stage 对照需要明确。
7. **emotionScore 嵌入文档的合同影响**：缓存 v3 之外，`hotlist_sentiment` 的 ingest 合同（Pydantic payload）、`migrate_hotlist_sentiment_slot_eod.py` 等运维脚本是否受影响。
8. **强弱不对称**：强资判据（zljzb≥8）已实证失效但 v2 仍保留 strongMoney 进 attackShare 分子——审计需决定：保留（计数聚合口径）还是替换（如 zlje 合计分位）？替换判据同样需要出处说明。
9. **failedOrWeakRate 死因子**：历史 P25-P90 恒 1.0——jev 叙事还在引用它（yesterdayLimit 段），评分未用 ✓；审计确认评分维度清单无其他死因子。
10. **T2 实现细节**：三个写口的 evidence parts 传递一致性（_compute_and_persist / compute_and_upsert_for_slot / run_for_date_slots 的 part 来源各不相同）；analysis_by_code 获取（load_snapshot_analysis 与 _join_display_status 的关系）；性能（每槽多一次聚合）。

### 审计流程建议

1. 通读 spec v2 + plan + 本文档 → 2. 按清单逐项攻防（可再发散）→ 3. 产出审计报告（问题分级：阻塞/建议/记录）→ 4. 修订 spec（v3）与 plan → 5. **向用户展示审计结论与修订点** → 6. 用户确认后进 T2。

## 6. 关键技术事实（实施必需）

- **EOD/槽位文档构造唯一口径**：`backend/operations/hotlist_sentiment.py::build_hotlist_sentiment_document`（L608 起）——T2 的切换点。现行：rawStage=resolve_stage 截面、stage=确认投影（`stage_confirm.confirm_stage`）、stageConfirmState（pending/pendingStage/pendingSince/confirmSlots/historyStatus）。
- **策略消费点**：`backend/analysis/ranktrend/trend/risk.py:134` `phase = hotlistSentiment.get("stage")` → regime score += stage_adjust[phase]；as-of 注入：`ranktrend/engine/runtime.py::_ensure_hotlist_sentiment`（provider 按 (tradingDate, slotTime) 取 ≤帧时点最新文档）。
- **evidence 聚合器**：`backend/analysis/hotlist/jev_state.py::collect_slot_evidence`（评分输入同源；含 breadth[trin/upTurnover/downTurnover]、rowFlags[strongMoney/risk/judgeable]、lifecycle、limit、yesterdayLimit、totalAmount[amount/vsSamePct/yesterdaySame]）。注意：**upRatio 与 attackShare 尚未在聚合器中输出**，评分模块目前内部自算（T2 可考虑下沉到聚合器，审计定）。
- **写口三处**：`hotlist_sentiment_compute.py` 的 `_compute_and_persist` / `compute_and_upsert_for_slot`；`operations/hotlist_sentiment.py` 的 `run_for_date(_slots)`（backfill）。EOD 走 `run_for_date`（collector 链每槽也触发）。
- **确认状态机**：`backend/analysis/hotlist/stage_confirm.py::confirm_stage`（档位滞回、跨日重置）——v2 方案复用（分数域平移），函数零改动预期。
- **昨日对比部件**：jev 服务层 `_yesterday_total_amounts_by_slot`（同期总额映射）、`_latest_yesterday_rows`（昨日行）——T2/T3 复用模式。
- **五档语义权威**：`src/types/emotion.ts::EMOTION_STAGE_RULES`（intent/evidence）——档位映射的语义锚。
- **API 缓存**：`backend/api/hotlist_routes.py` `_HOTLIST_SENTIMENT_CACHE_VERSION` v2→v3（emotionScore 新字段）。
- **历史实证数字**（引用勿重算）：1066 槽；crowdedShare P100=0.057 vs 高潮门槛 0.16；strongMoney effective_spread 触发率 3.9%；riskShare P10=0.826；确认档位分布 启动 492/退潮 520/发酵 54/高潮 0/冰点 0；failedOrWeakRate 恒 1.0。

## 7. 环境与操作

- **服务**：8000（backend uvicorn）/ 8001（collector）/ 3000（proxy）/ 5173（前端 dev）本机运行中；重启命令模式见 AGENTS.md §5 与本对话模式（Start-Process + WorkingDirectory quant-board）。
- **Token**：`quant-board/.env.local` 含 `JEV_SENTIMENT_ENABLED=true` + `JEV_CF_TOKEN`（不入仓）。
- **验证命令**：
  - 后端定向：`cd quant-board && ./.venv/Scripts/python.exe -m pytest tests/hotlist/ -q`
  - 后端全量：`./.venv/Scripts/python.exe -m pytest -q`（**注意**：tests/research/ 有 17 个预先存在的 anchor 失败，与本任务无关，已用隔离 worktree 验证过）
  - 前端：`pnpm test` / `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
- **pytest 红线**：数据只入 dragon_board_test（conftest 强制）；FakeMongo 模式见 tests/hotlist/test_hotlist_sentiment_backfill.py。
- **生产库**：dragon_board_quant（MongoDB 127.0.0.1）；collections：hotlist_sentiment（规则）、hotlist_jev_sentiment（jev 轨道）。

## 8. 纪律提醒

- 未提交文件属于用户（src/ DataTable、ui 等是用户的，勿动勿提交）；
- commit 只 add 明确路径；禁 `git add -A`/`reset --hard`/`checkout --`；
- 中文沟通、结论先行；每次改动小范围可验证；
- **审计报告与 spec 修订须经用户确认后才进 T2**（用户明确要求，勿自行跳过）；
- **⚠️ 调用 jev 模型（Cloudflare LLM，JEV_CF_TOKEN）或任何外部付费 API 前，必须事先告知用户**：用户需先开启 API 令牌后才能执行该步骤（2026-09-30 侧聊用户裁决）。路线 B 的 T1.5 重放校准 / T5 全量重算 / T6 回测对照均为本地纯函数链，不调模型；若后续涉及 jev 回放等模型调用，执行前先打招呼等确认。
