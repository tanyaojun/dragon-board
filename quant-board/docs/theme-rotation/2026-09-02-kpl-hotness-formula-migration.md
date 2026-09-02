# KPL 题材热度公式迁移（theme-market-v2）

日期：2026-09-02
范围：`backend/analysis/theme/heat.py`、`backend/services/theme/heat_service.py`、`backend/services/theme/kpl_hotness_cache.py`（新增）、`backend/analysis/theme/trend.py`、`backend/main.py`、`backend/core/settings.py`

## 背景与问题

原 `compute_theme_heat` 的 `heatScore` 是 0-100 归一加权分（breadth/fund/leadership/correlation 加权）。该口径的问题：

- "归一百分比"不是真实热度：所有题材挤在 0-100 区间，热门题材之间的差异被压缩，无法体现 KPL 题材库的真实人气量级。
- 与 Dragon Board 前端 `DragonBreathPanel` 的 3000/1500 热度阈值口径不一致（前端按人气总量分层）。
- 权重设计缺乏外部基准，属于自造口径。

## 新口径（对齐 tck2.js）

参照 `D:\TDX外挂\KPL题材库1.0\tck2.js` 的 `fetchThemeData`：

```text
heatScore = Σ 个股人气值（题材内去重）
```

- 数据源：longhuvip Theme API（`a=InfoGet&apiv=w43&c=Theme&ID=<themeId>`），复用 `mapping_refresh.py` 的 client。
- 提取顺序（决定同股优先级）：`Table.Level1.Stocks(Hot)` → 逐个 `Table.Level2[].Stocks(Hot)` → `StockList(HotNum)`；按 `StockID` 去重，只收 `> 0` 的值；`Hot <= 0` 不占位，同股后续来源仍可贡献。
- `heatScore` 是绝对值（热门题材可达数千），`rank` 按它降序。
- `momentumScore` 改为热度环比驱动：`clamp(50 + hotness环比变化率 × 150 + trimmedMeanChange × 4)`。

## 数据链路

```text
KplHotnessCache（后台线程，每 QUANT_BOARD_THEME_KPL_HOTNESS_REFRESH_SECONDS=600s 全量刷新，
  启动即预热；失败题材保留 last-good 并在 lastResult.failedThemeIds 结构化上报）
  → ThemeHeatService._refresh（按主题列表取已缓存人气）
  → compute_theme_heat(kpl_hots=...)（heatScore = 人气总和）
  → /api/themes/heat 快照（sources.kplHotness 暴露缓存健康）
```

- 缓存线程由 `get_theme_heat_service()` 工厂创建时即启动（start 幂等）；`main.py` lifespan 在 mongodb 模式下再调一次 start/stop（对称双保险）。工厂内启动保证 lifespan 启动失败后首次请求重建服务也能自愈，不会出现整进程缓存为空。
- `GET /api/health` 返回 `kplHotness` 段；`heat_service` 对缓存读路径异常做隔离（降级为缺失 + `sources.kplHotness.reason=kpl_cache_error:...`），缓存坏不炸 heat 快照。
- 读路径零上游请求：`get_theme_hots` 只返回已缓存的题材。

## fail-visible 约束（重要）

- KPL 缺失（缓存未预热/拉取失败/题材无数据）时该题材 `heatScore=null`、`rankEligible=false`，`qualityFlags` 带 `kpl_hotness_unavailable`；**不伪装成 0**。
- 快照整体 `ok` 只由行情覆盖率决定，KPL 缺失不阻断（行情侧因子照常返回）；`quality.kplHotnessCoverage` 给出全市场人气覆盖比例。
- 口径切换残留保护：上一帧 `heatScore` 还是旧 0-100 值（`0 < prev < 101` 且当前 `>= 101`）时不计算环比，flags 带 `kpl_hotness_baseline_reset`，下一帧自愈。
  - 已知边界窗口（2026-09 审计 M1，按文档口径接受）：上一帧为旧 0-100 残留、当前新口径绝对值恰好 `<= 100` 的小题材不会触发 baseline_reset（环比照算）。该窗口只出现在 v1→v2 升级后的第一个环比帧，且仅影响 momentum 单帧；`heatScore` 绝对值主要题材远超 100，实际暴露面极小。彻底修复需在落库行携带 factorVersion 口径标记（见下方 TODO）。

## 消费方适配（trend.py / momentum.py / rotation）

`backend/analysis/theme/trend.py` 的 themeContext 回放路径和 sector rows 路径原本按 0-100 阈值（70/45/20）消费 `heatScore`。适配：

- `heatLevel`（0-100 相对分）：themeContext 路径按 rank 百分位就地附加（rank1 → 100）；无热度/无 rank 时为 `null`。role 分层（core/follower/noise）、exposure 贡献度、signal score 的热度读点统一走 `_ts_heat_level()`。
- `_ts_heat_level()`：themeContext factor 读 `heatLevel`；sector rows factor 回退落库 `heatScore`（0-100 形态），`>100` 的新口径绝对值落库值视为缺失返回 `null`，`_build_factor` 不再对 heatScore 做 0-100 clamp（非数值同样按缺失，不伪装 0）。`heatLevel` key 显式存在但为 null（降级帧 rank 全 0）时不回退 heatScore。
- `_theme_context_frames` 的因子过滤从 `rankEligible`（现含"热度非空"语义）改为行情覆盖门槛（`metadata.quoteCoverage >= 0.5`）——KPL 缺失不再连带清空题材因子和 exposures。
- themeContext 支持可选 `kplHots` 字段（快照侧将来可直接带人气数据）；生产 themeContext 暂无该字段 → 热度诚实缺失。
- exposures 的 `themeScore` 字段语义改为 heatLevel（0-100 相对分或 null）。
- `backend/services/backtest_service.py`：执行信号的 `confidence`/`themeConfluenceScore` 的热度分量改走 `_persisted_heat_level()`（落库值缺失或 `>100` 按 0 计），避免新口径绝对值被 clamp 成满分导致 `hotlist_theme_confluence` 的 75 分门槛恒真；`themeHeat` 透传字段改显式 None 判断（真实 0 不被 fallback 顶掉）。
- `backend/analysis/theme/momentum.py`（2026-09 审计 H1）：动量序列跳过 `>100` 绝对值 bar（`/15.0` 归一、`THEME_JUMP_HEAT_DELTA=15` 等量纲按 0-100 校准，混入绝对值恒饱和）；`_role_for` 的 70/45/20 阈值只对 0-100 有限值生效，热度缺失/绝对值时只按涨跌判定 noise（正涨跌不误判 noise）。
- `backend/analysis/theme/rotation/factors.py`（审计 H1）：`strength_score` 对 `>100` 绝对值 heatScore 按缺失返回（`_clamp` 恒 100 + 斜率项恒饱和），由 `combine_scores` 按剩余可用因子归一。robust_z 横截面是尺度无关的，同帧同口径截面下主线判定不受影响。

## 前端影响（Dragon Board）

- `heatScore` 从 0-100 变为绝对值：所有直接展示/阈值判断 heatScore 的组件需要确认口径（DragonBreathPanel 的 3000/1500 阈值与新口径同量级）。
- 两套口径以 `factorVersion` 区分：`theme-market-v1`（旧归一分）→ `theme-market-v2`（KPL 人气总和）。
- 空值显示：`heatScore=null` 应显示"--"而不是 0。

## 黄金样本

- `tests/fixtures/theme_heat_market_golden_v2.json`：heat 引擎新口径 golden（AI=2000、POWER=null）。
- `tests/fixtures/theme_trend_ts_golden_v13.json`：trend 回放新口径 golden（themeContext 带 kplHots；POWER 诚实缺失路径一并锁定）。

## 2026-09-03 code review 修复记录

subagent 审计（H1/M1-M4/L1-L5）后已修复：

- **H1**：`momentum.py` 动量序列跳过 `>100` 绝对值 bar；`_role_for` 热度阈值只对 0-100 有限值生效。`rotation/factors.py` `strength_score` 对 `>100` 按缺失返回。修复前新口径热门题材会被 `_clamp` 成满分、斜率/动量项恒饱和，与 confluence 75 分门槛恒真是同类失真。
- **M2**：`get_theme_heat_service()` 工厂内 `kpl_cache.start()`（幂等），lifespan 启动失败后首次请求可自愈；`heat_service` 对缓存读路径异常隔离（`kpl_cache_error` 降级标注）；新增 `ThemeHeatService.kpl_cache` 公开属性。
- **M3**：`_ts_heat_level` 对显式 `heatLevel=None`（降级帧 rank 全 0）不回退 heatScore，冷题材 ≤100 绝对值不再被反向解释成高相对分。
- **M4**：恢复 `test_theme_heat_service.py` 被误删的 10 个服务级行为测试（singleflight 合并、fund 版本失效、mapping_empty、降级快照、缓存读取、formal scope、缺行缺失、工厂守卫）。
- **L1/L2**：`ThemeFactorFrame.heatScore: float | None`；`_num_or_none` 保证非法值/NaN 按缺失而非 0。
- **L3**：`KplHotnessCache.stop()` join 超时保留线程引用（防 stop 后 start 双循环）；删除 `_fetched_at` 死代码。
- **L4**：`main.py` shutdown 的 kpl 块加 mongodb 守卫（与 startup 对称）。
- **L5**：`backtest_service` 的 `themeHeat` 透传字段改显式 None 判断。

## 残留 TODO（后续迁移）

1. **heatLevel 落库**：sector rows / hotThemes 投影（`snapshot_collector/service.py factor_to_sector`、`snapshot_derivation/projection.py`）目前只落绝对值 heatScore；落库 heatLevel（rank 百分位，持久层字段已存在）后，momentum/rotation 可恢复完整热度动量而非当前的"绝对值按缺失降级"。
2. **momentum 量纲重校准**：`/15.0` 归一、`drawdown/20.0`、`THEME_JUMP_HEAT_DELTA=15` 按 0-100 校准；heatLevel 落库后重新核定。
3. **口径标记**：落库行携带 factorVersion/heat 口径 metadata，替代 `>100` 启发式，消除 M1 边界窗口与混合窗口歧义。
4. **前端消费点确认**（同量级阈值问题）：`src/config/factors.ts` themeScore 的 `Math.min(100)`、`src/services/hotness/StockHotnessCalculator.ts`、`src/services/dragon/BattlefieldBuilder.ts`、`DataLayer.ts` 的 `themeHeat ?? 0`（缺失伪装 0）。DragonBreathPanel 3000/1500 阈值与新口径同量级，无需改。
5. **golden 合同**：v14 起把 `heatLevel` 纳入 trend golden fixture。

## 验证

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_theme_heat_engine.py tests/test_theme_trend.py tests/test_theme_trend_heat_level.py tests/test_kpl_hotness_cache.py tests/test_theme_heat_service.py tests/test_theme_momentum_series.py tests/test_theme_rotation_factors.py tests/test_theme_backtest.py
```
