# 规则情绪连续评分体系（路线 B）— 实施计划

> **For agentic workers:** 按 Task 顺序执行，TDD 先行；工作区纪律按 AGENTS.md（明确路径 git add、禁回滚命令）。

**Goal:** 按 `docs/superpowers/specs/2026-09-30-emotion-score-design.md` v2 实施：规则情绪档位主定义从布尔级联切换为连续评分驱动（score 0-100 + 分段校准 + 分数域确认），旧级联降级为 legacyCascadeStage 对照面；全量历史重算 + 回测新旧对照。

**Spec:** `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（v2，用户已拍板直接切换 + 等权进回测验证）

**影响面（已核实）**：RankTrend 策略层 `risk.py:134` 消费 `hotlistSentiment.stage`（五档枚举，合同不变）；前端 `stage/rawStage/stageConfirmState` 形状不变（确认语义平移分数域）；API 缓存 v2→v3。

---

### Task 1: 评分核心 + 校准配置（TDD）

**Files:** Create `backend/analysis/hotlist/emotion_score.py`；Test `tests/hotlist/test_emotion_score.py`

- [ ] `SCORE_WEIGHTS`（8 维等权）、`_CALIB`（分段边界，全部注明"1066 槽 half_hour 分布 2026-09-30 校准"来源）
- [ ] `compute_emotion_score(evidence, prev_score=None) -> dict`：8 维子分（分段线性插值）→ 等权合成 score；缺维跳过 + skippedDims + 权重归一化；返回 `{score, dims, skippedDims, stageCandidate}`
- [ ] `confirm_stage_by_score(score, prev_state, boundary_band=5) -> (stage, state)`：分数域确认（连续 2 槽越界 + ±5 防抖带），state 形状与 stageConfirmState 兼容
- [ ] 档位映射：≥75 高潮候选（风险行占比>70% 压制→发酵）/ 60-75 发酵 / 40-60 启动 / <40 按斜率分退潮/冰点
- [ ] 测试：分段插值边界、缺维降级（删 TRIN → skippedDims + 归一化重算）、映射边界、确认（连续越界/防抖带/回落不切）
- [ ] Commit：`feat(hotlist-sentiment): 连续评分核心与分数域确认（路线B）`

### Task 2: 链切换——档位来源切至评分（golden 触点）

**Files:** Modify `backend/operations/hotlist_sentiment.py`（build_hotlist_sentiment_document）、`backend/analysis/hotlist/sentiment.py`（resolve_stage 降级 legacy 不删）

- [ ] `build_hotlist_sentiment_document` 新增 evidence parts 参数（frame/stocks 已有，补 yesterday_rows/analysis_by_code/yesterday_amounts）；内部调 `collect_slot_evidence` + `compute_emotion_score` + `confirm_stage_by_score`
- [ ] 文档字段切换：`stage`=分数确认档位、`rawStage`=本帧映射档位、`stageConfirmState`=分数域状态、新增 `emotionScore` 子文档、新增 `legacyCascadeStage`（旧级联输出，resolve_stage 保留调用仅作对照）
- [ ] signals/warnings/metrics/四量：不变（证据层）
- [ ] 测试：score→stage 映射、分数域确认（V 型日不吞截面：单槽越界不切换）、legacyCascadeStage 对照字段、emotionScore 可分解
- [ ] Commit：`feat(hotlist-sentiment): EOD 档位主定义切换为评分驱动（legacyCascade 对照面保留）`

### Task 3: 写口接线 + API 缓存 v3

**Files:** Modify `backend/services/theme/hotlist_sentiment_compute.py`、`backend/snapshot_collector/service.py`、`backend/api/hotlist_routes.py`

- [ ] 三个写口（_compute_and_persist / compute_and_upsert_for_slot / run_for_date(_slots)）传递 evidence parts（yesterday_rows 复用 previous_day_stocks；analysis_by_code 复用 _join_display_status 的 load；yesterday_amounts 复用 jev 服务层模式）
- [ ] `_SERIES_CACHE_VERSION` v2→v3
- [ ] 测试：写口往返 emotionScore 字段保留、缓存版本断言更新
- [ ] Commit：`feat(hotlist-sentiment): 评分链写口接线与缓存 v3`

### Task 4: 前端情绪分展示

**Files:** Modify `src/types/hotlistSentiment.ts`、`src/components/panels/HotlistEmotionPanel.vue`

- [ ] 类型：`emotionScore?: {score, dims, skippedDims}`
- [ ] 面板：hero 区情绪分展示（score 数值 + 环形/数值均可）；stage 展示逻辑零改动（stage 仍五档）
- [ ] 测试 + vue-tsc
- [ ] Commit：`feat(frontend): 热榜情绪面板展示连续情绪分`

### Task 5: 历史重算 + 新旧档位 diff 报告

**Files:** Create `backend/operations/emotion_score_recompute.py`（backfill slots 模式全量重算）、Create `quant-board/docs/hotlist-jev/emotion-score-migration-report.md`

- [ ] dry-run → 全量重算（1066 槽 + 全部 EOD，幂等）
- [ ] diff 报告：新旧 stage 逐槽对照（一致率/分歧分布/典型分歧日深挖——09-29 修复日、09-24 退潮日必查）
- [ ] Commit：`feat(hotlist-sentiment): 历史重算与新旧档位对照报告`

### Task 6: 回测平台新旧对照

**Files:** 对照脚本（replay 链 `legacyCascadeStage` vs `stage` 对 regime score 与候选分层的 diff）

- [ ] replay 新旧档位对 `risk.py stage_adjust` regime 的影响 diff
- [ ] 报告落 docs（量化切换影响，供用户最终确认）
- [ ] Commit：`feat(hotlist-sentiment): 回测 replay 新旧档位对照报告`

### Task 7: 全量验证 + 文档同步

- [ ] quant-board 全量 pytest + 前端 vitest + vue-tsc
- [ ] 文档同步：architecture.md（情绪档位来源切换）、AI_COLLABORATION.md、api-cli.md（缓存 v3）、单一事实源登记更新
- [ ] 最终 git status/diff 核对

---

## Self-Review

- Spec 覆盖：直接切换（T2）、分数域确认（T1）、legacy 对照面（T2）、回测验证（T6）、历史重算（T5）、下游兼容（T3/T4 stage 合同不变）
- 回退方案：resolve_stage 函数保留，调用点切回即可（一次部署）
- 红线：metrics/signals/warnings 证据层不动；五档枚举与字段合同不变；测试数据只入 dragon_board_test
