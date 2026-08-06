# 题材动量 v2（独立第四维板块动量）实施记录

> 日期：2026-08-06 · 状态：**已实施完成**
> Spec：`quant-board/docs/theme-rotation/2026-08-06-theme-momentum-redesign.md`（brainstorming 已批准）
> 执行方式：Subagent-Driven（用户确认）；结构迁移由父代理直接执行（机械重构需精确控制）。

## 目标

把题材动量从"个股共振调节项"解耦为独立第四维：日线级六维动量 + 槽位日内辅口径；废弃 theme_rotation 的 lifecycle 状态机，rotationState 改为方向标签；前端新增 OBSERVATION 第4轨 + 独立题材动量面板。

## 提交记录（740e0b0..HEAD，8 commits）

| Commit | 内容 |
| --- | --- |
| 740e0b0 | **结构迁移**：`backend/analysis/theme/` 与 `backend/analysis/ranktrend/` 包归拢，去前缀命名，旧路径薄 stub 兼容；49 个文件 import 更新；AGENTS.md 等 golden 路径文档同步 |
| 24fec97 | **Task 2 v2 纯函数**：`theme/momentum_config.py`（窗口/权重/阈值）；`theme/momentum.py` 追加 `compute_theme_momentum_v2`（RPS 5/10/20 / 距年内高点 / 多窗口动量 / 整体性 / 资金量能 / 拥挤惩罚）+ phaseLabel（非状态机）+ intraday；9 golden case |
| 7a562ec | **Task 3 analyze 解耦**：`ranktrend_routes.py` 移除 fuse_theme_resonance，resonance 回归纯六因子；新增 `_compute_theme_momentum_v2_context` + `_theme_momentum_projection`；frame 输出 `themeMomentumContext`、每股 `analysis.themeMomentum` |
| 46a6518 | **Task 4 lifecycle 废弃**：`theme/rotation/` engine/lifecycle/config 收敛，rotationState 改 4 方向标签（mainline/inflow/outflow/neutral）；`theme/trend.py` 信号/分层/迁移跟踪改用 rotationState；services.py 执行分层同步 |
| 61da228 | **Task 5 前端第4轨**：`RankTrendObservationPanel.vue` TRACK 04 题材动量；`ObservationService` theme 轨；DataTable tooltip 移除题材段；types.ts 新增 RankTrendThemeMomentum |
| 3db6b7e | **Task 6 面板 + API**：`GET /api/theme-momentum/summary`（Redis 缓存）；`ThemeMomentumPanel.vue` 全字段排行 + 行展开；App.vue 题材 tab 联动打开 |
| 6148ba5 | **Task 7 回放验证 + 文档**：`compare_theme_momentum_v1_v2`（v1 融合代理 vs v2 独立维度）；architecture/api-cli/theme-module 文档同步 |
| b268484 | **Review should-fix**：`_n_day_return` 窗口语义修正（off-by-one）；crowding 用日 breadthScore 代理并标注 `crowding_proxy`；intraday 输出标注 `unavailable`（fail-visible）；API 数据窗口 5000→20000（覆盖 21+ 交易日） |

## 关键设计落地

### 结构（结构迁移后）

```
quant-board/backend/analysis/
├── theme/
│   ├── __init__.py          # re-export 公开符号
│   ├── heat.py              # ← theme_heat.py
│   ├── momentum.py          # v1（保留回放）+ v2（compute_theme_momentum_v2）
│   ├── momentum_config.py   # v2 参数唯一来源
│   ├── daily_series.py      # 日线聚合：收盘槽 change 累乘虚拟收益指数
│   ├── momentum_validation.py  # v1 回放 + v2 对比
│   ├── support.py / trend.py
│   └── rotation/            # 轮动引擎（lifecycle 废弃，rotationState 方向标签）
└── ranktrend/
    ├── engine.py            # ← ranktrend.py（golden 事实标准）
    ├── jump_research.py / live_gate_shadow_audit.py / simple_backtest.py
```

旧路径（`backend.analysis.theme_heat` 等）保留薄 stub 转发，迁移期双兼容。

### 指标体系（v2 六维）

| 维度 | 权重 | 说明 |
| --- | --- | --- |
| 板块 RPS（5/10/20 横截面百分位） | 0.25 | 短窗加权（5×0.5+10×0.3+20×0.2），A 股扩散期短 |
| 距年内高点（虚拟收益指数接近度） | 0.15 | 数据不足降级为数据窗内高点 |
| 多窗口动量（5/10/20 加权符号强度） | 0.20 | 50 + Σ w·ret·coef |
| 整体性（日 breadth + 涨停贡献） | 0.20 | breadth×0.8 + min(zt×5, 20) |
| 资金量能（净流入 + 成交额占比） | 0.15 | inflow×0.6 + ratio×0.4 |
| 拥挤惩罚（门禁） | 扣分 | 日 breadthScore 代理，reasons 标注 `crowding_proxy` |

`themeMomentumScore = Σ(wᵢ·scoreᵢ) − crowdingPenalty`；可用维度 < 3 不产分；`direction ∈ {up, neutral, down}`；`phaseLabel ∈ {启动, 扩散, 过热, 退潮, 中性}`（非状态机）。

### 合同

- 帧级 `frame.themeMomentumContext`：`{version, factors(top-20), qualityFlags, computedAt}`
- 每股 `analysis.themeMomentum`：`{status, themeId, themeName, score, direction, role, phaseLabel, reasons}`（只读，不参与 decision）
- `GET /api/theme-momentum/summary`：`{ok, status, version, factors(top-50), qualityFlags, computedAt, cache}`
- `resonance` 回归纯个股六因子（不再含 `theme` 子对象）
- `rotationState ∈ {mainline, inflow, outflow, neutral}`（lifecycle 恒 None）

## 验证结果

- 后端 theme 全量：**221 passed**（v2 golden 9、集成 5、API 2、validation 3、rotation 方向标签 4、trend/support/research 等）
- 后端完整回归：tests/ + backend/tests/ 1321+ passed（4 个 golden_alignment monkeypatch 适配后全过）
- 前端：**851 passed**（新增 themeMomentumTrack 4、DataTableThemeTooltip 1、ThemeMomentumPanel 4；RankTrendObservationService 新合同）
- `vue-tsc --noEmit -p tsconfig.app.json`：0 错误

## 遗留与后续建议

1. **intraday 槽位口径**：v2 纯函数层 intraday 标注 `unavailable=True`（真实槽位增量由 analyze 槽位数据补充，当前未接入）。后续可把 `_compute_theme_momentum_v2_context` 扩展为传当前/前一槽行。
2. **crowding 代理**：拥挤惩罚用日 breadthScore 代理，非真实 crowdingRisk；后续 theme_heat 日聚合补 crowding 列后可替换。
3. **52 周高**：`near_high_full_window_days=250` 需 250 个交易日数据，迁移期降级为数据窗内高点（reasons 标注 `near_high_window_limited`）。
4. **theme_trend 字段命名**：`prevLifecycle/lifecycleTransition` 字段名保留但值已是 rotationState 方向标签（命名语义错位，前端无消费，低风险）。
5. **B_IGNITION 语义**：执行分层 `elif rotation_state == "inflow"` 使任意 momentum≥55 非主线题材入 B_IGNITION（语义漂移），后续可细化。
6. **首日观察清单**：上线第 1 个完整交易日后人工验证 MongoDB 实际入库行数 + `GET /api/theme-momentum/summary` factors 分布 + 前端第4轨/面板渲染（spec §8.3 Task 7 清单）。
