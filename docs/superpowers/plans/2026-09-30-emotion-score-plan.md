# 规则情绪连续评分体系（路线 B）— 实施计划

> **For agentic workers:** 按 Task 顺序执行，TDD 先行；工作区纪律按 AGENTS.md（明确路径 git add、禁回滚命令）。

**Goal:** 按 `docs/superpowers/specs/2026-09-30-emotion-score-design.md` v3 实施：规则情绪档位主定义从布尔级联切换为连续评分驱动（score 0-100 + 分段校准 + 分数域确认），旧级联降级为 legacyCascadeStage 对照面；全量历史重算 + 回测新旧对照。

**Spec:** `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（v3，经对抗性审计修订 `2026-09-30-emotion-score-audit.md`）

**影响面（已核实）**：RankTrend 策略层 `risk.py:134` 消费 `hotlistSentiment.stage`（五档枚举，合同不变；stage=null 安全降级为不加分不减分已验证）；前端 `stage/rawStage/stageConfirmState` 形状不变（确认语义平移分数域）；API 缓存 v2→v3 + ingest 模型扩字段。

---

### Task 1: 评分核心 + 校准配置（TDD）✅ 已完成（commit 028bae8a）

**Files:** `backend/analysis/hotlist/emotion_score.py`；`tests/hotlist/test_emotion_score.py`

- 交付：`compute_emotion_score`（8 维等权 + 缺维降级）、`map_stage`（含 slope 参数）、`_CALIB`（1066 槽校准——**注意：出处为规则链口径，T1.5 替换为 jev 口径**）、6 测试通过。
- **审计遗留（T2 接线时修复）**：compute 层从不传 slope（B2，退潮档不可达）；压制阈值 70 无出处（B3，待 T1.5 定稿）。

### Task 1.5: 1066 槽 jev 口径重放校准 + 五档可达性验证 ✅ 已完成（2026-09-30，报告 `2026-09-30-emotion-score-calibration.md`）

**Files:** `backend/operations/emotion_score_calibration_replay.py`（只读重放）；`emotion_score.py`（_CALIB 替换 + 删压制 + slope 参数）；`jev_state.py`（pctChange→change 回退）

- [x] 1068 槽全量重放（04-15~09-30），scoreNone=0
- [x] **新发现并修复**：2026-07-03 前历史行无 pctChange（约 470 槽）→ collect_slot_evidence 增加 change 回退 + degraded 注记（生产行零影响）
- [x] jev 口径全维分位数表替换 `_CALIB`（limitStruct 三维 198 真信号槽实测，样本局限已披露）
- [x] 五档可达率：冰点 24.4% / 启动 36.4% / 退潮 18.2% / 发酵 14.9% / **高潮 6.1%（旧级联 0）**；映射边界 75/60/40 经分布核对保持
- [x] **B3 终稿：压制条款删除**（64/65 高潮槽被旧条款压制，坐实二次不可达）
- [x] 相关性：riskRowsPct×riskShare=0.82（保留两维，回测消融）；upRatio×attackShare=0.22（无重叠，S4 关闭）
- [x] 断言：join 率≈100%（fallback 可忽略）、change/pctChange 不匹配 0.71%、zhabanRate 百分数量纲 ✓
- [x] 测试回归全绿（217 passed）；Commit：`feat(hotlist-sentiment): T1.5 jev 口径重放校准与五档可达性验证`

### Task 2: 链切换——档位来源切至评分（golden 触点）✅ 已完成（bf10480a）

### Task 2: 链切换——档位来源切至评分（golden 触点）✅ 已完成（bf10480a）

**Files:** Modify `backend/operations/hotlist_sentiment.py`（build_hotlist_sentiment_document）、`backend/services/theme/hotlist_sentiment_compute.py`（_collect_intraday_state 扩展）、`backend/analysis/hotlist/sentiment.py`（resolve_stage 降级 legacy 不删）

- [ ] `build_hotlist_sentiment_document` 新增 evidence parts 参数（frame/stocks 已有，补 yesterday_rows/analysis_by_code/yesterday_amounts）；内部调 `collect_slot_evidence` + `compute_emotion_score` + `confirm_stage`
- [ ] **slope 接线（审计 B2）**：`_collect_intraday_state` 扩展收集当日早槽 `emotionScore.score`（scorePoints），当前槽 `slope = score − prev_score`；prev 缺失（首槽/旧文档）→ slope=None → 低分判冰点 + diagnostics
- [ ] **score=None 语义（审计 B4，按用户裁决方案）**：rawStage=null（禁字符串 "None"）、确认重放跳过该槽、stage=当日已确认值或 null、diagnostics 结构化标注；`stageCandidate` 与 rawStage 同值（审计 S10）
- [ ] 文档字段切换：`stage`=分数确认档位、`rawStage`=本帧映射档位（含 slope）、`stageConfirmState`=既有确认状态机（confirm_stage 复用零改动，审计 S1）、新增 `emotionScore` 子文档、新增 `legacyCascadeStage`（旧级联输出，resolve_stage 保留调用仅作对照）
- [ ] signals/warnings/metrics/四量：不变（证据层；riskLevel 仍级联截面源，审计 N1）
- [ ] 测试：score→stage 映射、确认复用（V 型日分数谷底可见、单槽越界被吸收）、slope 接线（含 prev 缺失分支）、score=None 语义、legacyCascadeStage 对照字段、emotionScore 可分解
- [ ] Commit：`feat(hotlist-sentiment): EOD 档位主定义切换为评分驱动（legacyCascade 对照面保留）`

### Task 3: 写口接线 + API 缓存 v3 ✅ 已完成（d9f3a9b1）

**Files:** Modify `backend/services/theme/hotlist_sentiment_compute.py`、`backend/snapshot_collector/service.py`、`backend/api/hotlist_routes.py`

- [ ] 三个写口（_compute_and_persist / compute_and_upsert_for_slot / run_for_date(_slots)）传递 evidence parts（yesterday_rows 复用 previous_day_stocks；analysis_by_code 复用 _join_display_status 的 load 与 jev 服务层取数模式；yesterday_amounts 复用 jev 服务层 `_yesterday_total_amounts_by_slot` 模式）
- [ ] `_HOTLIST_SENTIMENT_CACHE_VERSION` v2→v3
- [ ] **`HotListSentimentPayload` 白名单增加 `emotionScore`/`legacyCascadeStage` 字段（审计 S2，禁止 ingest 静默丢弃）**
- [ ] 测试：写口往返 emotionScore/legacyCascadeStage 字段保留、缓存版本断言更新、ingest 往返新字段
- [ ] Commit：`feat(hotlist-sentiment): 评分链写口接线与缓存 v3`

### Task 4: 前端情绪分展示 ✅ 已完成（e8e654b9）

**Files:** Modify `src/types/hotlistSentiment.ts`、`src/components/panels/HotlistEmotionPanel.vue`

- [ ] 类型：`emotionScore?: {score, dims, skippedDims}`
- [ ] 面板：hero 区情绪分展示（score 数值 + 环形/数值均可）；stage 展示逻辑零改动（stage 仍五档）
- [ ] 测试 + vue-tsc
- [ ] Commit：`feat(frontend): 热榜情绪面板展示连续情绪分`

### Task 5: 历史重算 + 新旧档位 diff 报告 ✅ 已完成（0a3656ed）

**Files:** Create `backend/operations/emotion_score_recompute.py`（backfill slots 模式全量重算）、Create `quant-board/docs/hotlist-jev/emotion-score-migration-report.md`

- [ ] dry-run → 全量重算（1066 槽 + 全部 EOD，幂等；**legacyCascadeStage 一并重算写入——回退可执行的前提，审计 S7**）
- [ ] diff 报告：新旧 stage 逐槽对照（**旧链基线 = confirm_stage(legacyCascadeStage 当日序列) 重放重建，审计 S8**；一致率/分歧分布/典型分歧日深挖——09-29 修复日、09-24 退潮日必查）；报告含五档可达率（退潮 >0 为 B2 验收）
- [ ] Commit：`feat(hotlist-sentiment): 历史重算与新旧档位对照报告`

### Task 6: 回测平台新旧对照 ✅ 已完成（a07da87f）

**Files:** 对照脚本（replay 链旧确认投影 vs `stage` 对 regime score 与候选分层的 diff）

- [ ] **对照三方：旧确认投影（confirm_stage(legacyCascadeStage 序列)）vs 新 stage（分数确认）vs 新 rawStage（审计 S8）**
- [ ] replay 新旧档位对 `risk.py stage_adjust` regime 的影响 diff
- [ ] 报告落 docs（量化切换影响，供用户最终确认）
- [ ] Commit：`feat(hotlist-sentiment): 回测 replay 新旧档位对照报告`

### Task 7: 全量验证 + 文档同步 ✅ 已完成

- [ ] quant-board 全量 pytest + 前端 vitest + vue-tsc
- [ ] 文档同步：architecture.md（情绪档位来源切换）、AI_COLLABORATION.md、api-cli.md（缓存 v3）、单一事实源登记更新
- [ ] 最终 git status/diff 核对

---

## Self-Review（v3 审计后更新）

- Spec 覆盖：直接切换（T2）、jev 口径重放校准（T1.5）、确认机制复用（T2，审计 S1）、slope 接线（T2，审计 B2）、score=None 语义（T2，审计 B4）、legacy 对照面（T2）、回测验证（T6）、历史重算（T5，含 legacyCascadeStage）、下游兼容（T3/T4 stage 合同不变 + ingest 扩字段）
- 回退方案：resolve_stage 函数保留，调用点切回 + 历史 stage 从 legacyCascadeStage 重算恢复（审计 S7）
- 红线：metrics/signals/warnings 证据层不动；五档枚举与字段合同不变；测试数据只入 dragon_board_test；T1.5 重放只读生产库
