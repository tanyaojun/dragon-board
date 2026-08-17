---
name: ranktrend-tier-longterm-test
description: 四维信号（共振/趋势/量价/周期）参数长测标准流程——参数盘点与参数化（TDD golden 不漂移）→ 逐参数 5 档扫描（防过拟合）→ 组合验证 → 样本外复核（市场状态窗口感知）→ 判定分类（证实/缺复核/证伪/冗余）→ 文档固化 → golden 变更。供 N 阶段长测直接调用，无需反复查阅历史长测记录。第一轮实践见 quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md 阶段 7/8/9。
---

# 四维信号参数长测流程（N 阶段通用）

## Overview

对任一信号维度（共振/趋势/量价/周期/新因子）做参数长测：把硬编码参数化、逐参数 5 档扫描找出真实可调参数、组合验证、**市场状态感知**的样本外复核，最后按"证实/缺复核/证伪/冗余"四类判定收口并固化文档。**全程不写回默认值**（golden 不变），只有完全证实才走 golden 变更流程。

## 触发条件

- 新信号维度参数研究（如量价、ATR、下一轮候选因子）
- 既有维度参数优化请求（"调参/搜索/长测"）
- 四维参数长测 N 阶段启动（第一阶段已归档，见 longterm-backtest-plan.md）

## 标准流程（8 步）

### 1. 参数盘点与参数化（TDD，golden 不漂移）

- 沿调用链找出该维度**全部参数**：已 config 字段（RankTrendConfig）+ **硬编码阈值**（函数内字面量）；
- 硬编码阈值**先参数化**进 RankTrendConfig（默认值 = 原硬编码，golden 不漂移），新字段按语义命名
  （如 `momentumDirectionThreshold`/`volumePriceNormalRatio`）；
- 新增测试：字段默认值断言 + 参数生效测试（改参数 → 输出变化）；
- **list 字段必须同步 `search_space._STRATEGY_LIST_KEYS`**（否则搜索映射失败/误导到 trade_config）；
- 验证：相关 pytest 全绿（golden alignment 无回归）。

### 2. 逐参数 5 档扫描（防过拟合）

- **每个参数分别 5 档候选**（含当前默认），单变量扫描——**不是打包 3 组配置**（用户明确偏好）；
- 档位设计覆盖参数单调方向（如阈值 ± 若干档），list 参数用整体缩放（×0.8~1.2）；
- 评估口径（沿用阶段 7）：`tier_forward_returns`（h1，可扩展 h8）→ synergy saEx（主）+ 关注维 saEx；
  score = 2×clamp(syn_sa,0,0.15) + passHard 加减 + 关注维贡献 + unknown 惩罚；
- **判定规则**：多档位**单调性/峰值稳定性**——单调上升且非单点尖峰 = 真实可调参数；
  各档完全一致 = 冗余（仅平移 score 不影响档位）；非单调微弱 = 无调参空间；
- 脚本：`backend/operations/optimize_core_signal_parameters.py`（PARAM_TRIALS 换成目标维度参数，
  evaluate 支持 focus_dim=rankTrend/resonance/volumePrice）。

### 3. 显著参数组合验证

- 显著参数（通常 1-2 个）+ 档位层有效参数组合（如 `fund10+over2`、`jump25+freshness06`）；
- 判定叠加是否有效（synergy saEx 相对 baseline 提升且 passHard 保持）；
- 组合不成立（样本外 synergy 恶化放大）也要记录——证伪证据。

### 4. 样本外复核（**市场状态窗口感知**，第一轮最大教训）

- 默认：chronological 切分（`split_frames` validation_ratio 0.3）；
- **⚠️ 必须检查 validation 窗口是否含极端行情月**（如 2026-07 股灾月）——含极端月的
  validation 负 saEx 是市场状态污染，**不代表参数无效**；
- **独立干净窗口复核**：validation 单独用极端月之后的正常窗口（如 8 月 110 帧），
  train 用其余（可含极端月作 in-sample 上下文）；
- 交叉验证：可用 quarter_hour 1399 帧（显式研究口径非默认）对照；
- 判定：候选在干净窗口相对 baseline 显著改善（如 +438%）→ 证据升级；
  跨窗口不一致（half_hour 正/quarter_hour 负）→ 检查是否同为极端月污染，否则证据不足。

### 5. 判定分类（四类收口）

| 类别 | 标准 | 处置 |
|---|---|---|
| **证实（可 golden）** | 干净窗口样本外 synergy saEx ≥ 0.05 且 passHard、跨窗口稳健 | 走 golden 变更（步骤 8） |
| **缺复核** | in-sample 显著/转正，样本外 <0.05 或窗口不足 | 扩充数据/regime 复核后再定 |
| **证伪** | 扫描无效（各档持平）或样本外无正贡献（synergy 恶化） | 记录结论，不采纳 |
| **冗余** | 各档完全一致（仅平移 score/confidence 不影响档位） | 记录，可移除调参入口 |

### 6. 文档固化

- 追加到 `quant-board/docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md`
  新阶段（阶段 N：背景/扫描表/组合表/样本外复核表/判定结论）；
- 同步 `ranktrend-factor-calibration-plan.md` 参数清单（新参数化字段 + 语义注释）；
- 涉及默认值/合同变更时同步 `ranktrend-signal-model.md`/`observation-discrete-tiers-design.md`。

### 7. 提交（conventional commit）

- 按主题分 commit（实现/参数化/研究结论分开），message 注明"不写回默认值"；
- 提交前 `git status` 确认范围仅预期文件。

### 8. Golden 变更流程（仅"证实"类触发）

- 更新 golden case（`test_ranktrend_golden_alignment`）+ 默认值；
- `strategy_version`/`ranktrend_version` 提升（`ranktrend-golden.md` 变更管理）；
- TS 契约/文档同批同步（AGENTS.md §8）；
- 第一个上线日人工核对（AGENTS.md §11 复盘清单）。

## 关键工具与命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests\<相关测试>        # 回归
.\.venv\Scripts\python.exe -m backend.operations.optimize_core_signal_parameters  # 5 档扫描
# 组合验证/样本外：临时脚本复用 load_frames / split_frames / tier_forward_returns / _tier_summary
```

核心复用：
- `load_frames`（half_hour；quarter_hour 需直接调 `MongoRepository.load_frame_bundles` snapshot_type="quarter_hour"）
- `split_frames`（chronological 切分）
- `tier_forward_returns`（signal_filter 支持按 direction/regime 分桶；DIMENSION_PATHS 覆盖
  resonance/rankTrend/volumePrice/lifecycle/synergy/atr）
- `optimize_core_signal_parameters.py` evaluate（score 公式）

## 验收标准（长测产物）

1. 参数盘点完整（已 config + 硬编码全识别）；
2. 硬编码参数化默认值=原值，golden 测试全绿；
3. 每参数 5 档扫描表（单调性/峰值结论）；
4. 样本外复核含**干净窗口**（避开极端行情月）+ 常规切分；
5. 判定分类四类齐全（证实/缺复核/证伪/冗余）；
6. 文档阶段固化 + factor-calibration 参数清单同步；
7. 全程不写回默认值（除非"证实"走 golden 变更）。

## 第一轮长测复盘教训（2026-08-17）

1. **样本外窗口必须感知市场状态**：7 月股灾月污染 validation（baseline −0.0112），
   单独跑 8 月干净窗口后候选翻案（fund10+over2 +438%）——**极端行情月单独处理**；
2. **用户洞察价值**："7 月是股灾月"一句纠正了整轮降级结论——长测中遇样本外异常，
   先问市场状态而非直接判参数无效；
3. **不写回默认值**是硬原则：四维全部候选（量价/共振/趋势）均 <0.05 验收线，无 golden 变更对象；
4. **参数化是前置**：18 个趋势硬编码阈值 + 量价 2 个参数化后才有扫描空间；list 字段
   白名单（_STRATEGY_LIST_KEYS）易漏；
5. **冗余参数识别**：jumpSustainCount/momentumZeroStrongConfirmThreshold/方向八档分值等
   不影响档位（仅平移 score/confidence）——扫描各档一致即冗余，节省后续调参精力；
6. **数据缺口影响结论**：high/low 缺失（28%）曾使 ATR 全 unknown——先确认数据可用性
   再下结论（收盘准 ATR 自适应口径解决）。
