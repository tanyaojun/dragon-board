# 环境门去噪：多帧确认 + 迟滞（WP2）设计

状态：待批准（2026-09-06）
前置：编码不依赖 WP1，但 **2c 调参扫描必须在 WP1c 修复 lookahead 之后**执行（不许在被污染 regime 上调参——用户四条"不建议做"之一）；扫描基线依赖 WP3.2 翻转率指标先行。

## 动机

half_hour 帧粒度下，lifecycle veto/B-D 降档与 regime state 的单帧跳变直接改变档位与禁门，产生信号抖动（原始问题"half_hour 快照计算变化太快产生噪音太多"的门控侧表现）。当前无任何文档量化过门控翻转频率。

## 硬约束（用户已定）

- **默认零行为变化**：K=1、α=1、迟滞关闭时所有现有测试与 golden 不漂移。
- **fail-visible**：被单帧翻转抑制的 veto/降档必须在 reasons 可见，不允许隐藏数据。
- 不给 lifecycle 加方向投票（A/B 不单调 + 阈值坐标下降不可调已双重证伪）。
- 2c 调参扫描是研究任务，走 `skills/ranktrend-tier-longterm-test/SKILL.md` 8 步流程，**不进本轮编码**。

## 现状锚点（侦察已确认）

- `lifecycle_decision`（`analysis/ranktrend/trend/lifecycle.py:215`）与 `_synergy_tier`（`ranking/volume_price.py:292`）均为纯函数、零跨帧状态；B/D 降档在 volume_price.py:364-367，veto 入口 lifecycle.py:261-272，lc_tier=="E" 连锁在 volume_price.py:316-317。
- 每帧每股票调用链：`_build_signal`（`engine/runtime.py:1031` 起，L1065/1075 两处 lifecycle）；live 单股经 `api/ranktrend_routes.py:364 _analyze_one_stock` 同接口。
- 回测 replay 帧循环 `runtime.py:869`，regime 每帧一次 L903；引擎实例级跨帧容器先例 `_atr_meta_by_code`（runtime.py:1169 setdefault 模式）。
- regime state（strong/normal/weak/retreat）判定 `trend/risk.py:149-154`；门禁消费 `compose_analysis_candidate_tier`（runtime.py:753-766），参数 `regimeGateStrongBan`/`banStrongA`/`banStrongB`（`engine/config.py:116-120`）。
- reasons 输出位：`observation.lifecycle.reasons` / `veto`（runtime.py:404-405）、`observation.synergy.tierReasons`（volume_price.py:415-416）、`strategy.regime.reasons`（runtime.py:826）。

## 范围 2a：lifecycle 门控 K 帧确认

### 语义

- veto 条件成立需**连续 K 帧**成立才真正 veto；`_synergy_tier` 的 B/D 降档条件同理。
- 连续性按 **per-stock**（lifecycle stage 是个股级）计：连续计数按 code 维护，条件帧间不成立即清零。
- `K` 可配，默认 `K=1` = 现行为（单帧即触发，golden 不漂移）。
- 被抑制的单帧翻转：档位维持前一帧结果，并在 reasons 追加（如"周期 veto 单帧确认 1/K=N 未达，暂缓"）——观察字段，不影响 golden（默认 K=1 时该分支不触发）。

### 实现位置（不改纯函数本体，golden 安全）

- 新增 `analysis/ranktrend/trend/gate_confirm.py`：`GateConfirmState` 纯状态机（per-key 连续计数 + 判定），无 I/O。
- 挂载点按调用链分三类：
  1. **回测 replay**：引擎实例属性 per-code 持有（`_atr_meta_by_code` setdefault 先例）；在 `_build_signal` 拿到 lifecycle 结果后、写入 observation 前过确认层。
  2. **live frames 链路**（`ranktrend_routes.py:471 _analyze_frames`、`main.py:931`）：单请求内帧序列 → 请求级容器按序处理。
  3. **live 单股单帧**（`_analyze_one_stock`）与 `replay_frame_at` 无帧序列上下文：退化为 K=1（现行为），spec 明示此边界。
- 配置：`RankTrendConfig` 新增 `lifecycleConfirmFrames: int = 1`。

## 范围 2b：regime score EMA + state 迟滞

- `market_regime`（risk.py:74）纯函数本体不动；新增平滑包装 `RegimeSmoother`（`analysis/ranktrend/trend/` 就近文件）：
  - score EMA：`ema = α*score + (1-α)*prev_ema`，`α` 默认 `1.0`（直通 = 现行为）；state 由 EMA 后的分数判定（阈值沿用 `REGIME_STRONG_SCORE` 等）。
  - state 迟滞：双阈值参数化（如进 strong 需 ≥70、退出需 <65），默认**关闭**（直通）。
- 挂载：replay 帧循环 L903（股票循环外）持有 smoother（引擎实例属性）；`replay_frame_at` 与无实例调用链退化为直通。
- state 消费端（`compose_analysis_candidate_tier` 门禁、`signal["regime"]`）不改——只是 state 来源可选平滑后值。
- 配置：`regimeScoreEmaAlpha: float = 1.0`、`regimeStateHysteresis: bool = False` + 迟滞阈值对。

## 参数管理与登记

- 三个新参数全部进 `RankTrendConfig`（默认值 = 现行为）并登记 L1 档案（新参数入档案组管理，8 月冻结纪律适用：未经证实不得改默认值）。

## 2c 调参扫描（后续研究任务，非本轮编码）

- K∈{1,2,3} 单变量、α 档位单变量、longterm-test skill 8 步流程（逐参数扫描→组合验证→样本外复核→四类判定）。
- 前置：WP1c 已修复 lookahead（否则在被污染 regime 上调参）+ WP3.2 翻转率基线已产出。
- 效果度量：WP3.2 翻转率指标 WP2 前后对比；只有"证实"类才动默认值。

## 非范围

- lifecycle 方向投票（证伪）。
- `market_regime` 打分构成（REGIME_STAGE_ADJUST 等）改动。
- 门禁参数（`regimeGateStrongBan`/`banStrongA`/`banStrongB`）默认值变更——那是 2c 扫描证实后的事。
- 2c 扫描进本轮编码。

## 测试策略（TDD）

1. **golden 不漂移**：默认参数（K=1/α=1/迟滞关）下现有全部测试绿（含 `test_ranktrend_golden_alignment`）。
2. K=2 单测：合成帧序列——veto 条件连续 2 帧才 veto；第 1 帧被抑制且 reasons 可见；中断后计数清零。
3. B/D 降档 K 确认同理；`lc_tier=="E"` 连锁行为不回归。
4. α=0.5 / 迟滞开启单测：score 序列 EMA 值、state 进出双阈值。
5. 状态隔离：两个 dataset/两次 replay 调用互不污染；live 单股退化路径 = 现行为。
6. 验证：pytest 相关子集（先 `--collect-only`）。

## 风险与回退

- 门控变迟钝可能放过真实 reversal——K 只对"触发"加确认，reversal 首帧仍记 reasons（fail-visible）；2c 扫描验证。
- 跨帧状态引入 replay 顺序耦合：状态容器只在引擎实例/请求级存活，`replay_frame_at` 混用语义跟随 `_atr_meta_by_code` 的"调用方保证"惯例并在代码注释声明。
- 回退：三参数默认值即现行为，revert 代码即可；无 schema/存储变化。
